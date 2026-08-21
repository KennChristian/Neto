# Offline fallback clips

Pre-rendered WAVs played when ElevenLabs is unreachable, so the robot never
goes silent. `speak.py` looks up clips by exact normalized phrase in
`index.json` (`{normalized phrase: filename}`), falling back to espeak-ng
when no clip matches.

## Phrases worth pre-rendering

These are the canned situations wired into `speak.REASON_PHRASES`:

| Situation | Phrase |
|---|---|
| Connection lost / timeout / 5xx | "I seem to have lost my connection. Give me a moment." |
| Quota exhausted (429) | "My voice allowance is used up for now. Bear with me." |
| Generic error | "Something went wrong with my voice. Bear with me." |

Add any greeting or stock line your demo relies on — anything the robot
must be able to say with the network down.

## Generating

Run once while online (uses the same synth + EQ chain as live speech):

```bash
python -m voice.fallback.generate_fallback_clips
# or with extra phrases:
python -m voice.fallback.generate_fallback_clips "Welcome, everyone." "Goodbye for now."
```

Clips land in this directory as `<sha16>.wav` plus an updated `index.json`.
Both are safe to commit — they contain no credentials.
