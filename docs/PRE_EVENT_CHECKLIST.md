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
- [ ] Speaker route correct on both (`~/bin/audio-out status`).
- [ ] A dry-run turn each (console "Rehearse silently" on, ask a question,
      watch the journal, turn it off again).

## If the console goes away mid-event

- Both robots close their microphones within 3 s and keep their last role.
- Duet keeps playing (no network needed). Direct mode needs the console
  back: restart `pi-dashboard.service` on the authority machine.
