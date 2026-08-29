"""Wake-word subsystem (PLAN-0008).

Self-contained engine + audio-source seam. Designed so the same engine
runs on the laptop today (via `SoundDeviceSource`) and on Reachy Mini
later (via a future `ReachySource`) without modification to wake logic.

Read `docs/implementation-plans/PLAN-0008-wakeword-milestone-1.md`
before extending.
"""
