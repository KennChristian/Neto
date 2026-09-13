# Pre-event checklist — two-robot installation

Work through this on BOTH machines before doors open. Tick in order.
Machine names are read from `config/robots.json`; never identify a robot
by its hostname alone — the console shows `machine · role` together.

## The night before

- [ ] **Re-enable the voice app**: `sudo systemctl enable --now supervaise.service`
      on both machines. It was disabled on 2026-09-10 while the two-robot
      configuration was being built so a reboot could not autostart a
      half-built branch. Check `systemctl is-enabled supervaise.service`
      says `enabled` on both.
- [ ] `git status` clean on both machines, same commit:
      `git log -1 --oneline` matches. Sync path: `git push sync <branch>` /
      `git pull sync <branch>` (the bare repo `~/git/cjap.git`; add the other
      machine as a remote when it is reachable — see `config/robots.json`).
- [ ] `config/robots.json`: both machine names correct, `authority.host` is
      the machine that will serve the console (port 8080), `bind` is
      `0.0.0.0`.
- [ ] `/etc/systemd/system/supervaise.service.d/wakeword.conf` on each
      machine carries only that machine's identity (`CJ_ROBOT_SLOT`) and
      secrets stay in `app/.env`. Listening knobs live in
      `config/modes/*.json`, not in the drop-in.
- [ ] Both machines have the pre-rendered audio: host intro variants and the
      duet exchanges (`data/prerendered/`) — duet must play with the venue
      WiFi down. `scripts/render_duet.py --check` reports nothing missing.
- [ ] Voice cache warm for the canned answers: `scripts/prerender_canned.py`.
- [ ] Wireless mic receivers: each robot's receiver on, the handheld
      transmitter heard by whichever robot holds the floor (open `/console`,
      give the floor to one robot, talk, watch the room level move; repeat
      for the other).

## One hour before

- [ ] Open `http://<authority>.local:8080/console?key=cjap` on the laptop.
      Both robots report (no "no report" pills).
- [ ] Choose who is Panganiban (`cjap_is`), then mode and profile:
      `direct` + `event` for emcee-driven Q&A, `duet` for the loop.
- [ ] Room level vs "loudness that counts as talking": no amber warning on
      either robot with the crowd in. Raise the setting if it fires.
- [ ] Locked gates all ON (specifics rule, fact audit, year gate,
      AI-self-description gate, corpus grounding).
- [ ] **Kill the Bluetooth route hijack FIRST**, on both machines:
      `sudo systemctl disable --now speaker-watchdog.service`. It polls every
      15 s and re-routes audio onto ANY paired speaker that powers on (C41,
      EMBERTON, Sony ULT FIELD 1, HTM-222 are all paired on alpha), which
      would flip the route — and lose the XMOS echo cancellation — in the
      middle of the event. Confirm with `systemctl is-enabled
      speaker-watchdog.service` → `disabled`. Nothing re-connects a Bluetooth
      speaker afterwards; `~/bin/audio-out <name>` does it by hand, and the
      voice app still falls back to the internal speaker on its own when a
      route dies (it runs `~/bin/audio-out ensure` on a playback failure).
- [ ] Speaker route correct on both (`~/bin/audio-out status`).
- [ ] **External PA**: plug the USB DAC in, check `~/bin/audio-out
      dac-present` prints a sink, then `~/bin/audio-out dac` and
      `~/bin/audio-out test` — the test tone must come out of the powered
      speaker, not the robot. No restart is needed: the app re-reads the ALSA
      route before each output open. Without a DAC the only external path is a
      Bluetooth PA (`~/bin/audio-out bt`); HDMI is not a route target.
- [ ] **Echo cancellation is OFF on an external route** until the DAC delay
      has been measured: run `~/tools/aec_ref_calib.py` with the DAC as the
      live route and put the printed value in the drop-in as
      `CJ_AEC_REF_DELAY_DAC_MS` (the app refuses to arm the reference feed
      without it). Until then the robot hears itself through the PA.
- [ ] **Barge-in at show volume**: play one full answer through the PA at the
      level the room will hear, then read the journal line `[stop] answer
      played out — peak …` (and `/dev/shm/cj_stop_live.json`). Set
      `CJ_STOP_OWW_THRESHOLD` to ~3x the highest non-stop peak — it is 0.02 on
      alpha / 0.01 on beta, tuned to a small Bluetooth speaker, not a ballroom
      PA. If the peaks approach a real stop (~0.09), set
      `CJ_STOP_WORD_ENABLED=0` for the event: a robot that cannot be
      interrupted beats one that interrupts itself.
- [ ] **PA placement**: not behind the robot. `CJ_LISTEN_DIRECTION=back`
      parks the two fixed beams at 225°/315° (the robot's back), so the
      speaker belongs in front of or beside it, firing at the audience.
- [ ] A dry-run turn each (console "Rehearse silently" on, ask a question,
      watch the journal, turn it off again).

## If the console goes away mid-event

- Both robots close their microphones within 3 s and keep their last role.
- Duet keeps playing (no network needed). Direct mode needs the console
  back: restart `pi-dashboard.service` on the authority machine.
