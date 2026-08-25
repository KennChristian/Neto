# Moving CJAP to another Reachy Mini

Two things move: the **public repo** (code, models, clips, units, tuning —
branch `pi/deployment-snapshots`) and one **encrypted private bundle** (API
keys, certs, HeyGen key, voice print, optionally the clip cache) that the
repo must never contain. Total hands-on time ≈ 20 min; `install.sh` runs
10–15 min unattended on a CM4.

Repo: `https://github.com/Supervaise-Inc/CJAP.git` (the old
`KennChristian/Neto` URL redirects there).

## 0. Prerequisites on the NEW robot

- Stock Reachy Mini image (Debian 13, user `pollen`, `/venvs/mini_daemon`
  with `reachy_mini` 1.9.x, `reachy-mini-daemon` running).
- XMOS mic firmware ≥ 2.1.0 (needed for direction-of-arrival). Check:
  `/venvs/mini_daemon/bin/python /venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/audio_control_utils.py VERSION`
  → `VERSION: [0, 2, 1, x]` is fine.
- Internet on the new robot (WiFi via the Reachy setup flow, or Ethernet).
- Note its address: `hostname -I` / `<hostname>.local`.

## 1. On the OLD robot (reference) — push code, pack secrets

```bash
snapshot-push.sh                       # live system -> repo branch snapshot/<ts> + pi/deployment-snapshots
export-private.sh --with-cache         # asks for a passphrase; writes ~/backups/private-<host>-<ts>.tar.gz.enc
#   drop --with-cache for a ~10 KB bundle (keys only); with it, ~400 MB and the
#   ~150 canned/event answers play instantly on the new robot with no ElevenLabs spend
scp ~/backups/private-*.tar.gz.enc pollen@<new-robot>.local:~/
```

## 2. On the NEW robot — install

```bash
git clone -b pi/deployment-snapshots https://github.com/Supervaise-Inc/CJAP.git \
    ~/Supervaise-Reachy-Mini-Project-main
cd ~/Supervaise-Reachy-Mini-Project-main
bash deploy/pi/install.sh              # apt, venv (exact pins), models, clips, dotfiles,
                                       # PipeWire realtime fix, dashboard + cert, units, hotspot
import-private.sh ~/private-*.tar.gz.enc        # same passphrase; restores .env, voice/config.py,
                                                # certs, liveavatar.json, enrolled.npz, (.voice_cache)
sudo hostnamectl set-hostname reachy-cjap      # optional: keep the same name/URLs as the old robot
sudo reboot                                     # once — the PipeWire realtime limits need a fresh session
```

## 3. After the reboot — verify

```bash
verify.sh          # 23 checks: services, keys, models, clips, PipeWire fix, XMOS fw, DoA, venv, 3 APIs, journal
```
All PASS → say **"Hi Cee-Jap"** and ask a question. Then open
`http://<hostname>.local:8080/maintain?key=cjap` and check the Providers
chips are green and the wake meter moves when you talk.

## 4. Things that are robot-specific (re-do by hand)

| What | Why | How |
|---|---|---|
| Bluetooth speakers | pairings live in the OS, and `audio-out sony/marshall` are pinned to the reference speakers' MACs | pair from `/maintain` → Bluetooth card; then `audio-out sony` (or edit `~/bin/audio-out` MACs) |
| WiFi networks | NetworkManager profiles are not exported | Reachy setup flow or `/maintain` → WiFi card; the `ReachySetup` fallback hotspot is created by install.sh |
| Voice lock enrolment | `enrolled.npz` is restored by the bundle; re-enrol if a different person will host | `/maintain` → Enroll |
| Speaker turn direction (DoA) | head yaw sign is assumed | stand to the robot's LEFT, say "Cee-Jap"; if it turns right add `Environment=CJ_DOA_FLIP=1` to `/etc/systemd/system/supervaise.service.d/wakeword.conf`, `sudo systemctl daemon-reload && sudo systemctl restart supervaise` |
| XMOS chip tuning | AEC/NS values are chip-runtime and reset on power cycle (both robots run stock values) | nothing to do |
| Event mode | flag file `data/entities/event_mode.on` is in the repo state at snapshot time | toggle on `/event` or `/maintain` |

## 5. Rollback / restore points

Every push makes a `snapshot/YYYY-MM-DD-HHMM` branch. To put a robot back:
```bash
cd ~/Supervaise-Reachy-Mini-Project-main && git fetch && git checkout snapshot/2026-08-25-1813
bash deploy/pi/install.sh && sudo systemctl restart supervaise pi-dashboard
```

## 6. Keeping two robots in sync afterwards

Reference robot: `snapshot-push.sh` after changes. Other robot:
```bash
cd ~/Supervaise-Reachy-Mini-Project-main && git pull && bash deploy/pi/install.sh
sudo systemctl restart supervaise pi-dashboard
```
`install.sh` never overwrites `.env`, `voice/config.py`, `.asoundrc.route`,
certs or clips already present.
