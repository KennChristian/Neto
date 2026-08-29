# Manager guide — phases, status, roadmap interpretation

Audience: **Project leads, FLP program managers, and stakeholders**
who need to read project status without diving into code.

This guide is the high-altitude view. It complements
[PROJECT.md](../../PROJECT.md), which is the canonical source — read
this guide if you want orientation; read PROJECT.md for detail.

## 1. What this project is

A **conversation app** that embodies the persona of retired
Chief Justice Artemio V. Panganiban (CJP), built for the
**Foundation for Liberty and Prosperity (FLP)**. The app speaks in
CJP's voice, grounded entirely in his published corpus — columns,
speeches, and biography. Three pillars: legal education, opinions,
biography.

Demo target: **May 30, 2026** (chat-only; voice / robot embodiment
is post-launch).

## 2. Where we are — Phase status

Read this section to know what's done, what's next, and what's
deferred.

| Phase | Deliverable | Status | What it means |
|---|---|---|---|
| 1 | Corpus knowledge base — 79 paired `.md` + `.json` from 80 CSV rows | **Done** | The source documents the app uses are committed. 1 row (biography) is intentionally skipped pending a date decision. |
| 2 | Topic Map — 35-topic curated taxonomy + `topic_paths` backfilled on every doc | **Done** | The router has a deterministic way to map a question to a small set of documents. |
| 3 | Voice Card — composition system prompt | **Done** | The composer has a documented "how to speak as CJP" guide. |
| 4 | Runtime app — Haiku router + Sonnet composer + memory | Planned | The conversation works end-to-end. See [PLAN-0001](../implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md). |
| 5 | Web chat UI | Planned | End users can talk to it in a browser. See [PLAN-0002](../implementation-plans/PLAN-0002-web-chat-ui.md). |
| 6 | One-time embedding audit | Planned | Sanity-check the taxonomy with embeddings, just once. See [PLAN-0003](../implementation-plans/PLAN-0003-embedding-audit-offline.md). |
| 7a | Biography ingestion | Planned | Get the biography into the corpus once the date is decided. See [PLAN-0004](../implementation-plans/PLAN-0004-biography-gc001-ingestion.md). |
| 7b | Book corpus addition | Planned | Add *A Centenary of Justice* — 24-25 sections. See [PLAN-0005](../implementation-plans/PLAN-0005-book-corpus-addition.md). |
| 8 | Voice / TTS for FLP Museum kiosk | Future | Post-launch; for the Museum hub deployment. See [PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md). |

## 3. How to read project artifacts

When evaluating a status update or PR, look for these signals:

### 3.1 Generation report (`reports/generation_report.json`)

After every Phase 1 run, this file states:

- **total_rows_processed**: how many CSV rows the generator saw.
- **successful_generations**: how many produced .md+.json pairs.
- **skipped_rows**: how many were rejected (bad date / bad ID).
- **missing_text_placeholders**: how many produced files with no
  source `.txt` (the file exists but has a placeholder body).

Healthy state today: 80 / 79 / 1 / 0. The 1 skipped is GC001
(biography) by design.

### 3.2 Validation log (`reports/validation_errors.log`)

Two sections:

- **ERRORS** (rows skipped) — bad. Each entry is a CSV row that did
  not produce output. Either fix the row or accept the gap.
- **WARNINGS** (row generated with notice) — fine. Each entry is a
  CSV row that produced output but had to apply a parser fallback.
  Quality is slightly degraded; long-run we should re-curate.

Healthy state today: 1 error (GC001 by design); ~22 WARNs (column
rows with semicolon-list `Keyword/s` cells per
[ADR-0012](../decisions/0012-permissive-csv-enrichment-parsing.md)).

### 3.3 Topic map report (`reports/topic_map_report.json`)

After every Phase 2 run:

- **unmatched_docs**: list of doc ids with empty `topic_paths.primary`.
  Should always be `[]`.

Healthy state today: `[]`.

## 4. What "completion" of each phase means

Use this to evaluate whether a phase is *actually* done:

- **Phase 1 done** = `corpus/columns/` + `corpus/speeches/` contain
  the expected file count; `reports/generation_report.json` shows
  ≤1 skipped (biography); validation log shows no surprises.
- **Phase 2 done** = `corpus/voice/topic_map.json` exists; every doc
  has `topic_paths.primary` populated; matcher health check has
  flagged anything that needs attention.
- **Phase 3 done** = `corpus/voice/voice_card.md` exists; reviewer
  pass against the worked-example template signs off.
- **Phase 4 done** = the runtime serves the six build-kit sanity
  questions; per-turn cost ≤$0.05; latency ≤25s; honesty rule fires
  on identity probes; reviewer pass.
- **Phase 5 done** = web UI works in a mobile browser; identity
  banner present; sources panel populated; accessibility ≥90.

## 5. The biggest decisions, in plain language

Read these if you want to understand *why* the project is shaped
the way it is. Each ADR is short.

| What | Why it matters | ADR |
|---|---|---|
| No embeddings at runtime | Saves money, makes routing inspectable | [ADR-0003](../decisions/0003-reject-embeddings-for-v1.md) |
| Two-stage API (router → composer) | Saves money vs. stuffing everything in one call | [ADR-0004](../decisions/0004-pattern-1-topic-routed-two-stage-api.md) |
| Haiku for routing, Sonnet for composition | Cost / capability trade-off | [ADR-0002](../decisions/0002-llm-tiering-haiku-router-sonnet-inference.md) |
| Strict date validation | The persona references time; wrong dates are a serious bug | [ADR-0013](../decisions/0013-strict-date-validation-no-placeholders.md) |
| Permissive enrichment parsing | Doesn't lose 30% of column rows over semicolon-vs-JSON style | [ADR-0012](../decisions/0012-permissive-csv-enrichment-parsing.md) |
| Hand-curated taxonomy | Better than statistical clustering for a small, edited corpus | [ADR-0014](../decisions/0014-hand-curated-taxonomy-in-python-code.md) |
| Theme-anchored register | The app sounds different on different topics, on purpose | [ADR-0016](../decisions/0016-theme-anchored-register-selection.md) |
| Defer robot embodiment | May 30 demo is chat; robot is for post-launch | [ADR-0005](../decisions/0005-defer-robot-embodiment-for-may-30.md) |

## 6. The biggest risks, in plain language

| Risk | Mitigation | Where it lives |
|---|---|---|
| App invents a CJP quote | Voice card "Never" list + fidelity-check Haiku | [TS-004](../test-specs/TS-004-voice-card-protocol.md) §7 |
| App takes a stance on a `sub judice` case | Voice card *sub judice* rule | [TS-004](../test-specs/TS-004-voice-card-protocol.md) §6.3 |
| App pretends to be the biological CJP | Honesty rule | [TS-004](../test-specs/TS-004-voice-card-protocol.md) §3 |
| Curator updates CSV in a way that breaks generation | Permissive parsing + validation log | [LL-006](../lessons/LL-006-mixed-csv-cell-formats.md) |
| Topic over-broad → router becomes useless | Matcher health check + tightening process | [PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md) §3c |
| Cost spike from chatty users | Per-turn budget + cache + soft rate limit | [PLAN-0002](../implementation-plans/PLAN-0002-web-chat-ui.md) §7 |

## 7. Phase commit pattern (what to expect from engineering PRs)

The phase commits should look like:

```
feat(corpus): Phase 1 — generate CJP knowledge base from curated CSVs
feat(corpus): Phase 2 — Topic Map + topic_paths backfill
feat(corpus): Phase 3 — Voice Card (Sonnet composition prompt)
feat(runtime): Phase 4 — Haiku router + Sonnet composer wired
feat(ui): Phase 5 — web chat UI
chore(audit): Phase 6 — embedding audit report
feat(corpus): Phase 7a — biography GC001 ingested
feat(corpus): Phase 7b — book corpus added
feat(voice): Phase 8 — TTS integration
```

A clean commit history makes it possible to read the project's
evolution as a sequence of decisions.

## 8. Where the work happens

| Activity | Where |
|---|---|
| Curate a new document | Edit `data/csv/*.csv` + add `data/text/*.txt` |
| Edit the taxonomy | Edit `scripts/build_topic_map.py` `TAXONOMY` list |
| Edit the voice card | Edit `corpus/voice/voice_card.md` |
| Re-run the pipeline | `python scripts/generate_corpus_files.py --with-topic-paths` |
| Check what changed | Inspect `reports/*.json` + `reports/*.log` |
| Diagnose a routing issue | Open `corpus/voice/topic_map.json` + the specific doc's `.json` |
| Write a decision record | New file in `docs/decisions/` |
| Write a lesson learned | New file in `docs/lessons/` |
| Write an implementation plan | New file in `docs/implementation-plans/` |

## 9. Glossary

- **Corpus**: the curated body of CJP's published works that the app
  draws on.
- **Topic map**: the taxonomy that maps subjects → documents.
- **Voice card**: the system prompt that tells the LLM how to speak
  as CJP.
- **Composer / composition**: the LLM call that produces the
  response.
- **Router**: the LLM call that picks which topics are relevant.
- **Fidelity check**: a downstream LLM call that catches
  hallucinations or guardrail violations.
- **Topic paths**: per-document tags indicating which topics route
  to that document.
- **Theme**: one of five top-level subject letters (A: Rule of Law,
  B: Prosperity, C: Biographical, D: FLP, E: Current events).
- **Register**: the *tone* the composer adopts (ceremonial, warm,
  reflective, etc.), driven by the routed theme.
- **OOC**: out-of-corpus. The policy for handling questions whose
  answer is not in CJP's published record.
- **Sub judice**: legal Latin for "before the court". The app
  declines to opine on cases currently in active litigation.
- **MADR**: Markdown Architecture Decision Record format used for
  ADRs in `docs/decisions/`.
