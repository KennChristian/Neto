"""WiFi control on /maintain and / (2026-09-12): every nmcli call goes through
sudo (the service has no login session; polkit refuses scan/activate
otherwise), saved networks are matched by SSID not profile name, a new
password replaces a saved one, hidden networks are explicit, and a failed
join puts the robot back on the previous network."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.expanduser("~"), "pi_dashboard"))
import ui_server as srv  # noqa: E402


class FakeNM:
    """Minimal nmcli: profiles {name: ssid}, active profile, scan list, and
    which SSIDs accept which password."""
    def __init__(self):
        self.profiles = {"Home": "Home", "ReachySetup": "CJAP Reachy", "Event": "Event Hall"}
        self.psk = {"Home": "oldpw"}
        self.active = "Home"
        self.scan = [("Event Hall", "80", "WPA2"), ("Home", "70", "WPA2"), ("Cafe:Wifi", "40", "")]
        self.accept = {"Event Hall": "eventpw", "Home": "oldpw", "Cafe:Wifi": None, "Ghost": "ghostpw"}
        self.calls = []

    def __call__(self, cmd, timeout=10):
        assert cmd[:3] == ["sudo", "-n", "nmcli"], cmd
        a = cmd[3:]
        self.calls.append(a)
        if a[:5] == ["-t", "-f", "NAME,TYPE", "connection", "show"]:
            return 0, "\n".join(f"{n.replace(':', chr(92) + ':')}:802-11-wireless" for n in self.profiles) + "\nlo:loopback"
        if a[:2] == ["-g", "802-11-wireless.ssid"]:
            return 0, self.profiles[a[4]].replace(":", "\\:")
        if a[:5] == ["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"]:
            act = self.active.replace(":", chr(92) + ":") if self.active else None
            return 0, (f"{act}:802-11-wireless:wlan0\n" if act else "") + "lo:loopback:lo"
        if a[:5] == ["-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "dev", "wifi"]:
            return 0, "\n".join(f"{s.replace(':', chr(92) + ':')}:{sig}:{sec}:{'*' if self.active and self.profiles.get(self.active) == s else ' '}"
                                for s, sig, sec in self.scan)
        if a[:2] == ["connection", "modify"]:
            self.psk[a[2]] = a[4]
            return 0, ""
        if a[:3] == ["connection", "up", "id"]:
            name = a[3]
            ssid = self.profiles[name]
            if self.psk.get(name) == self.accept.get(ssid):
                self.active = name
                return 0, "Connection successfully activated"
            self.active = None
            return 4, "Error: Connection activation failed: Secrets were required"
        if a[:3] == ["dev", "wifi", "connect"]:
            ssid = a[3]
            pw = a[a.index("password") + 1] if "password" in a else None
            hidden = "hidden" in a
            if ssid not in [x[0] for x in self.scan] and not hidden:
                return 10, f"Error: No network with SSID '{ssid}' found."
            self.profiles[ssid] = ssid          # nmcli makes the profile first
            if ssid in self.accept and self.accept[ssid] == pw:
                self.active = ssid
                return 0, f"Device 'wlan0' successfully activated with '{ssid}'."
            self.active = None
            return 4, "Error: Connection activation failed: (7) Secrets were required"
        if a[:3] == ["connection", "delete", "id"]:
            self.profiles.pop(a[3], None)
            return 0, ""
        if a[:2] == ["connection", "down"]:
            self.active = None
            return 0, ""
        raise AssertionError(f"unexpected nmcli {a}")


def _wire(monkeypatch):
    nm = FakeNM()
    monkeypatch.setattr(srv, "run", nm)
    srv._wifi_profiles_cache.update(ts=0.0, data=None)
    return nm


def test_nm_split_handles_escaped_colons():
    assert srv._nm_split("Cafe\\:Wifi:40:WPA2:*") == ["Cafe:Wifi", "40", "WPA2", "*"]
    assert srv._nm_split("a\\\\b:c") == ["a\\b", "c"]


def test_scan_and_status_use_sudo_and_ssids(monkeypatch):
    nm = _wire(monkeypatch)
    nets = srv.wifi_scan(rescan=True)
    assert [n["ssid"] for n in nets] == ["Event Hall", "Home", "Cafe:Wifi"]
    assert nets[1]["in_use"] and nets[2]["security"] == "open"
    assert ["-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "dev", "wifi", "list", "--rescan", "yes"] in nm.calls
    saved, current = srv.wifi_status()
    assert saved == ["CJAP Reachy", "Event Hall", "Home"] and current == "Home"   # SSIDs, not profile names


def test_join_saved_network_by_profile_name(monkeypatch):
    nm = _wire(monkeypatch)
    nm.accept["Event Hall"] = None                       # saved profile already holds the right secret
    nm.psk["Event"] = None
    ok, msg = srv.wifi_connect("Event Hall")
    assert ok and 'now on "Event Hall"' in msg and nm.active == "Event"
    assert ["connection", "up", "id", "Event"] in nm.calls and not any(a[:3] == ["dev", "wifi", "connect"] for a in nm.calls)


def test_new_password_replaces_saved_one(monkeypatch):
    nm = _wire(monkeypatch)
    nm.active = "Event"; nm.psk["Event"] = "eventpw"
    nm.accept["Home"] = "newpw"                          # the router password changed
    ok, msg = srv.wifi_connect("Home", "newpw")
    assert ok and nm.psk["Home"] == "newpw" and nm.active == "Home"
    assert ["connection", "modify", "Home", "wifi-sec.psk", "newpw"] in nm.calls


def test_failed_join_restores_previous_and_drops_half_profile(monkeypatch):
    nm = _wire(monkeypatch)
    ok, msg = srv.wifi_connect("Cafe:Wifi", "wrongpw")
    assert not ok and "back on 'Home'" in msg and nm.active == "Home"
    assert "Cafe:Wifi" not in nm.profiles                 # the failed first-join profile was deleted


def test_unknown_ssid_refused_unless_hidden(monkeypatch):
    nm = _wire(monkeypatch)
    ok, msg = srv.wifi_connect("Ghost", "ghostpw")
    assert not ok and "not in the last scan" in msg and nm.active == "Home"
    ok, msg = srv.wifi_connect("Ghost", "ghostpw", hidden=True)
    assert ok and nm.active == "Ghost"
    assert ["dev", "wifi", "connect", "Ghost", "password", "ghostpw", "hidden", "yes"] in nm.calls


def test_bad_ssid():
    assert srv.wifi_connect("")[0] is False
    assert srv.wifi_connect("x" * 33)[0] is False
