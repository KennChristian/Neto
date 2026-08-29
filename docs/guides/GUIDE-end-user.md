# End-user guide — chatting with the CJP conversation app

Audience: **Filipino civic readers, law students, FLP stakeholders,
and visitors** using the app for the first time.

This guide assumes you've opened the chat app and have a question.

## What this is

This is an AI conversation app built by the **Foundation for Liberty
and Prosperity (FLP)**. It speaks with the voice of **Chief Justice
Artemio V. Panganiban** (retired), drawing on his published writings —
columns, speeches, and biography.

When you ask a question, the app routes it to relevant passages from
his published record and composes a response in his voice.

## What you can ask

The app is most informative on:

1. **Legal education** — constitutional doctrine, judicial reform,
   case law, rule of law.
2. **Opinions** — CJP's documented positions on contemporary issues
   (ICC, ASEAN, technology, AI, public policy).
3. **Biography** — his personal journey, mentors, family, faith,
   FLP work, milestone events.

Sample questions that work well:

- *"What is the twin-beacons doctrine?"*
- *"Tell me about your wife Leni."*
- *"What did Salonga teach you?"*
- *"What is FLP doing right now?"*
- *"What do you think about AI?"*
- *"What was your most important decision as Chief Justice?"*

## What you'll get back

A response in CJP's first-person voice. Typical responses:

- 100-300 words for substantive questions.
- 40-80 words for short factual questions.
- Up to 400 words for biographical anecdotes.

You may notice:

- **Signature phrases**: *"in my humble opinion"*, *"with due
  respect"*, *"au contraire"*, *"liberty and prosperity"*, *"the
  rule of law"*.
- **Chiasmic doublets**: *"justice and jobs; freedom and food;
  ethics and economics"*.
- **Tagalog ornaments at warm moments**: *"Maraming salamat po"*,
  *"Abangan!"*, *"Mabuhay!"*.
- **Latin sprinkling**: *ponencia*, *sub judice*, *au contraire*.

If a response surprises you, **expand the "Sources" panel** below the
response. It lists the actual documents (columns, speeches) the
response drew on, with their dates and one-paragraph summaries.

## What you won't get

The app will **decline** or **redirect** when asked:

- Specifics of cases CJP did not write or hear.
- Stances on cases currently before the courts (*sub judice*).
- Personal commentary on living individuals beyond what his corpus
  contains.
- Predictions of future events.
- Anything outside his published record.

The honest decline usually sounds like:

> *"I have not written specifically on that, but applying what I
> have said about [related principle]…"*
> *"That is not something I have addressed in my writings."*
> *"On that matter, *sub judice* prevents me from offering a specific
> opinion."*

## Is this really CJP?

**No.** The app is upfront about this. If you ask:

- *"Is this an AI?"*
- *"Are you the real Chief Justice Panganiban?"*
- *"How were you built?"*

…you will get an honest acknowledgment. The canonical version is:

> *"I am an AI conversation robot built by the Foundation for Liberty
> and Prosperity to share my institutional knowledge and experience —
> drawn from my speeches, columns, writings, and the work of my life
> as Chief Justice. To be clear, I am a robot rendering of my own
> voice, not the man himself — Chief Justice Panganiban is the
> source from which I speak, but I am the machine through which he is
> now reaching you."*

The app speaks **in first-person** as CJP (because that's how the
voice card was designed), but it never claims to be the biological
person.

## What "sources" mean

Every response carries the doc IDs the model attended to. These look
like:

- `SA136` — Speech (S), Theme A (Liberty and Rule of Law), Number 136.
- `CA001` — Column (C), Theme A, Number 001.
- `GC001` — Biography (G) chapter, Theme C (Biographical and
  Personal), Number 001.

The full ID convention is in
[PROJECT.md §4](../../PROJECT.md). For most readers, the
**title + date** in the source panel is what matters; the IDs are
debugging aids.

## Languages

The app speaks primarily in **English** with **Tagalog ornaments** at
warm moments (closings, exclamations, code-switching cultural
phrases). It does not respond in Tagalog-only.

If you ask in Tagalog, you'll get an English response. We may add
multilingual support in a future phase (see
[PLAN-0002](../implementation-plans/PLAN-0002-web-chat-ui.md) §2 for
why it's out of scope right now).

## Troubleshooting

- **Response feels generic / not like CJP.** Try a more specific
  question. The app's strength is in topics his corpus covers
  deeply.
- **Response says "I haven't written about that."** That's the
  out-of-corpus policy speaking truthfully. Ask a related principle
  instead — *"What would the rule-of-law principle say about
  this?"*
- **Response cites a wrong date.** Note the doc id from the Sources
  panel and report it via [GUIDE-reviewer.md](GUIDE-reviewer.md)
  feedback channel; corpus errors do exist.
- **App seems slow.** First turn warms the cache; subsequent turns
  should be 5-15s. If consistently slow, the operator dashboard has
  per-turn timing.
- **App refused to answer.** Probable causes: `sub judice`, OOC
  policy, content policy. Try rephrasing toward the principle rather
  than the specific case.

## Feedback

If a response seems wrong, misleading, or inconsistent with what you
know of CJP's published views, report it to your FLP point of
contact. Note the question, the response, and the source IDs.
