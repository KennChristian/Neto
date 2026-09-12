# Host Card — the second robot

Authoring brief for the **Host**, the other Reachy Mini. Used by the render
scripts. **Never a runtime prompt**: the Host composes nothing, ever. It plays
pre-rendered audio and then is silent.

## Who the Host is

A museum docent, not a presenter. It stands beside the Chief Justice and does
the one thing he cannot do for himself: say plainly what he is.

Its voice is a stock ElevenLabs voice, chosen to be unmistakably **not** his —
he is an elderly Filipino man, so the Host is not. Set in `app/.env` as
`ELEVEN_HOST_VOICE_ID`; changed in one click from /maintain's Guest tab.
Currently *Matilda — Knowledgable, Professional* (female, middle-aged), picked
for a docent's register rather than an announcer's.

## Its two jobs

**1. The honest frame, and it is the important one.** The Host says that this
is a recreation built from published work, *before* the Chief Justice speaks.
That single line is what lets him stay fully in voice for an entire
conversation: an identity question never has to break the persona, because the
frame was set honestly up front. It is also the pitch — the product is
knowledge preservation, and the Host is the part that names it.

**2. Filling an empty room.** Two robots talking to each other is what makes
people stop walking. One robot sitting silent is furniture.

## Writing rules

- **Short.** A Host line is one or two sentences. It sets up; it does not
  explain.
- **Never in his voice.** The Host never speaks *for* him, never paraphrases
  his position, never answers on his behalf. It asks, frames, and invites.
- **Never claims he is real, never pretends he is not.** "A recreation, built
  from his own columns and speeches" is the exact register.
- **No facts of its own.** No dates, cases, figures or attributions. Anything
  factual belongs in *his* lines, drawn from the corpus.

## His side of a duet

Duet lines are words put in a living person's mouth, written ahead of time
rather than composed from the corpus at runtime — so they carry the fidelity
risk the live pipeline is built to avoid. Therefore:

- **Quote, or stay general.** Prefer phrasing that appears in the corpus.
  `data/entities/pronunciation_lexicon.json` and each document's
  `signature_phrases` are where to look.
- **No specifics that are not his.** No date, number, case title or
  person-organisation pairing unless it is in the corpus verbatim.
- Every line in [duet_script.json](duet_script.json) has a `source` field
  naming where its phrasing comes from, or `general` when it asserts no fact.

## Files

| File | What it is |
|---|---|
| [duet_script.json](duet_script.json) | The exchanges, in order. Hand-authored. |
| `scripts/render_duet.py` | Renders each line to `data/prerendered/duet/`. |
| `config/modes/duet.json` | `host_intro_text` and the duet mode profile. |
