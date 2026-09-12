# Runbook — venue network for the two-robot kit

**Written 2026-09-12.** Applies to the two-robot installation (operator
console, floor lease). Companion to [`config/robots.json`](../config/robots.json)
and [`scripts/provision_kit_wifi.sh`](../scripts/provision_kit_wifi.sh).

## What actually has to travel

Two needs, and only one is fragile:

| Traffic | Between | Needs |
|---|---|---|
| Floor lease + mode/profile/persona | the two robots | a LAN, ~1 small HTTP poll per second. **No internet.** |
| Router, composer, TTS, STT | Panganiban and the cloud | real internet; latency lands in the answer |

The Host robot never needs the internet. It plays pre-rendered audio.

## The property that decides everything

The authority robot leases the floor **from itself over loopback**
(`http://127.0.0.1:8080`). So:

- If the network dies, **Panganiban keeps its mic and keeps answering** for as
  long as the internet holds. Only the Host goes quiet.
- That inverts if you **swap roles**, because the machine playing Panganiban
  would then reach the authority over the network, and a dropout closes its
  mic (the lease fails closed, by design).

**Keep the authority on whichever machine is playing Panganiban.** If you must
swap for a failure, expect the new Panganiban to depend on the link.

## Why a travel router

Carrying your own router means robot-to-robot never depends on the venue:
one network name saved before you travel, one subnet, nothing configured on
site. It also side-steps the two ways a venue network breaks this silently:

- **Client isolation.** Common on guest WiFi. Both robots associate, both look
  online, and traffic between them is dropped. The lease fails closed and the
  exhibit stops.
- **Blocked mDNS.** The lease resolves the authority by a `.local` name.

The router's own uplink (venue WiFi, or a phone) may fail freely: that only
costs you live conversation, not the link between the robots.

## Setup, once

1. **Provision both robots** (the SSID is the router's, not the venue's):

   ```bash
   # on the authority robot (config/robots.json -> authority.host)
   sudo scripts/provision_kit_wifi.sh --authority "KitSSID" "kitsecret"
   # on the second robot
   sudo scripts/provision_kit_wifi.sh --secondary "KitSSID" "kitsecret"
   ```

   Add `--dry-run` first to see the commands. The kit profile is saved at
   autoconnect priority 100; every venue profile on these machines sits at 10
   or below, so the router always wins when it is in range. Re-running is safe
   and is how you change the passphrase.

2. **Reserve the authority's address** on the router (DHCP reservation by MAC).

3. **Put that address in `config/robots.json`** on *both* machines:

   ```json
   "authority": { "host": "reachy-cjap", "port": 8080, "ip": "192.168.8.2", ... }
   ```

   `host` still names the **machine** — each robot compares its hostname
   against it to know whether it *is* the authority. Never put an address
   there. Setting `ip` removes mDNS from the link.

4. **Restart** `pi-dashboard` and `supervaise` on both.

## Failure chain, by design

| What breaks | What happens |
|---|---|
| Venue uplink / internet | Router and lease fine. No live composition: run **duet**. |
| Travel router | Authority raises its own `CJAP Reachy` hotspot after ~60 s; the second robot joins it (a profile the `--secondary` run saved) and the lease returns. No internet. |
| Link to the authority | Second robot's mic closes, persona **HELD**. Panganiban is unaffected *if* it is the authority. |
| Authority robot | Everything stops. There is no second authority. |

`--secondary` also delays that machine's own setup-hotspot to ~10 min
(`CJ_SETUP_MISSES=30`), because if both robots raise an AP at the same time
neither can join the other, and the pair only recovers on the next ~5 min
probe.

## Before the doors open

- [ ] Both robots on the kit router; `nmcli -t -f NAME,DEVICE c show --active`
      shows `KitRouter`.
- [ ] From the second robot: `curl -s http://<authority-ip>:8080/api/state | head -c 80`.
- [ ] `/console` shows both robots reporting, not "no report".
- [ ] Pull the router's uplink and confirm the lease survives.
- [ ] Power-cycle the router and confirm both rejoin without a keyboard.

## Known gaps as of 2026-09-12

- The second machine has never joined: `cj-beta.local` does not resolve, and
  `config/robots.json` expects exactly that hostname.
- **Duet is not yet a network-free fallback.** The mode profile says "zero
  network", which is true of the *internet*, but the code drives duet playback
  from the lease, so it still needs the LAN. And the pre-rendered exchange was
  never built — there is no prerendered audio directory and no renderer script.
  Duet today means both robots stand idle.
