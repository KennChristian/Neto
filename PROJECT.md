# Project — CJ Panganiban Conversation App

A chat-based conversation app that embodies the persona of retired Chief
Justice Artemio V. Panganiban (CJP), grounded in his published corpus.
Built for the **Foundation for Liberty and Prosperity (FLP)**, in support
of FLP's mission to *"instill in Filipinos a deep appreciation for the
essential interdependence of liberty and prosperity under the rule of
law."*

**Phase 1 deliverable:** corpus knowledge base — paired `.md` + `.json`
files generated from curated CSV, committed to GitHub.

**Status:** Phase 1 file generation complete — 79 of 80 source rows
generated (64 columns + 15 speeches). The single biography row
(`GC001`) is intentionally skipped: a multi-decade biographical work
has no single publication anchor date, and the spec forbids placeholder
dates. The biography will be added in a later phase under its own
date-handling rules. See
[`reports/generation_report.json`](reports/generation_report.json) and
[`reports/validation_errors.log`](reports/validation_errors.log).

---

## 1. What this is

A conversational interface that answers questions in CJP's voice, drawing
on his actual published record. It serves three pillars:

1. **Legal education** — constitutional doctrine, judicial reform,
   case law, rule of law
2. **Opinions** — CJP's documented positions on contemporary issues
3. **Biography** — his personal journey, mentors, milestones,
   institutional memory

**Personality:** serious but sometimes witty. The app speaks in
first-person as CJP — fully in persona, including when asked about its
own nature. Per the Identity rule (2026-08-09, superseding the earlier
robot-honesty rule), it answers identity probes AS Chief Justice
Panganiban himself: *"I am Artemio Panganiban — the 21st Chief Justice
of the Philippines, retired since 2006..."* It never describes itself
as an AI, robot, machine, or "rendering", deflecting machinery
questions with gentle humor — and it never invents views on matters
not in the corpus.

**Why this is interesting:** CJP has 25+ years of public writing —
1,000+ Supreme Court decisions, multiple books, hundreds of *Philippine
Daily Inquirer* columns under his "With Due Respect" byline, plus
speeches and a published biography. That's enough corpus to support a
character that doesn't just mimic his voice but actually reasons from
his frameworks: the **twin beacons** (liberty and prosperity), the
**rule of law vs. rule of force** dichotomy, the **chiastic doublets**
(*"justice and jobs, freedom and food, ethics and economics"*), and his
signature openers / closers (*"With due respect,"* *"Au contraire,"*
*"Maraming salamat po."*).

---

## 2. Scope

### Phase 1 — In scope (current phase)

- Generate paired `.md` + `.json` files from curated CSV inputs. Source
  CSVs as delivered:
  - 64 columns
  - 15 speeches
  - 1 biography (intentionally skipped — see Status above)
- Schema validation (ID format, required fields, JSON parseability)
- Source-text matching from local `.txt` files in `data/text/`
- Permissive parsing of mixed-format enrichment cells (JSON arrays OR
  semicolon-separated strings) — fallback used cases are logged as
  warnings rather than skipped
- Generation report + validation error log
- GitHub commit of the `/corpus` directory

### Phase 1 — Out of scope (deferred to later phases)

- ~~**Topic Map** (`/corpus/voice/topic_map.json`)~~ → completed.
  See [`corpus/voice/topic_map.json`](corpus/voice/topic_map.json) — a
  hand-curated 35-topic taxonomy with matcher rules, doc-counts, top
  signature phrases per topic, and per-theme register defaults. The
  `topic_paths` field on every generated `.json` is populated.
- ~~**Voice Card** (`/corpus/voice/voice_card.md`)~~ → completed.
  See [`corpus/voice/voice_card.md`](corpus/voice/voice_card.md) — the
  Sonnet composition system prompt: identity, honesty rule, voice
  fingerprint, doctrinal anchors, register selection table, context
  block conventions, out-of-corpus reasoning policy.
- **Runtime app** — Haiku Router, Sonnet composer, Memory layer
- **Web frontend / chat UI**
- **Book** — excluded from Phase 1; will be added later
- **Embedding audit** — one-time offline task, runs after corpus is
  fully generated
- **Enrichment of placeholder fields** (`type: "tbd"`, `tone: "tbd"`,
  `length: "tbd"`) — handled in subsequent enrichment passes
- **TTS / voice output** — chat-only at this stage; voice / robot
  embodiment deferred to a later phase aligned with the FLP Museum
  hub deployment

---

## 3. Themes (canonical, locked)

The theme letter means the same thing whether the document is a speech,
column, or biography section.

| Letter | Label | Description |
|---|---|---|
| **A** | Liberty and Rule of Law | Constitutional doctrine, judicial reform, civil liberties, court history, judicial stewardship |
| **B** | Prosperity and Economic Philosophy | Economic policy, deferential interpretation, entrepreneurship, business law, twin-beacons doctrine |
| **C** | Biographical and Personal | Family, faith, personal journey, marriage, friends, mentors, eulogies, milestone events |
| **D** | FLP Mission and Foundation | FLP programs (scholarships, fellowships, dissertations, chairs), partners, donors, ultimate projects (Museum, Fund), scholars |
| **E** | Signature Current Events Commentary | CJP's commentary on contemporary issues — technology, AI, public policy, political developments, society |

---

## 4. ID convention (strict, locked)

Format: `{Type}{Theme}{Number}` — no separator, no prefix.

- **`S`** = Speech
- **`C`** = Column
- **`G`** = Biography
- Theme = single letter `A` | `B` | `C` | `D` | `E`
- Number = matches the source's numbering (zero-padded as needed)

ID format must match regex: `^[SCG][A-E]\d+$`

Examples:
- `SA136` — Speech, Theme A, Number 136 (*Maraming Salamat Po*)
- `CA005` — Column, Theme A, Number 005 (*Due process and judicial compensation*)
- `SE001` — Speech, Theme E, Number 001 (*Linda Mañalac Eulogy*)
- `GA001` — Biography, Theme A, Number 001

The IDs are themselves meaningful — they encode type + theme + number.
No redundant `page` field is used.

---

## 5. Date handling

Dates are **semantically significant** for the app's responses. CJP's
persona naturally references temporal context — *"last year I wrote
about..."*, *"during my term as Chief Justice..."*, *"ten years ago at
the Global Forum..."*

- Every document MUST have a valid `date` field in ISO `YYYY-MM-DD`
  format
- The date appears in both the `.md` frontmatter and the `.json`
- A `year` field (integer) is derived for convenient runtime filtering
- Runtime composition (Sonnet) uses the date to compute relative time
  phrasing where appropriate
- If a CSV row has a missing or malformed date, the generation script
  logs a validation error and skips the row — no placeholder dates,
  since that would corrupt temporal reasoning at runtime

---

## 6. Architecture decisions (locked, for context)

### Retrieval approach: Direct Corpus Interaction

- **No vector store at runtime**
- **No chunking** — documents are sent whole to the response model
- Retrieval is **deterministic structured lookup** via a curated Topic
  Map → Document IDs
- Embeddings may be used ONLY for one-time offline audit, never at
  runtime

This decision was made deliberately. CJP's enriched JSON is itself a
high-signal structured index — semantic search would discard it and
re-derive worse groupings statistically. The corpus is also small
enough (a few hundred docs) that hand-curated metadata wins over
embeddings, and his signature phrases repeat across documents in ways
embeddings can't distinguish.

### Runtime model stratification (future phase)

- **Haiku** — Input Gate (scope / identity-question check), Router
  (topic classification + register selection), Fidelity Check
  (hallucination + voice + guardrail verification on Sonnet drafts)
- **Sonnet** — Composition (the only step that requires voice fidelity
  and depth)
- **No Opus at runtime**

### Offline model

- **Opus 4.7** for any further enrichment, persona synthesis, Voice
  Card drafting

### Runtime pipeline (future phase, locked design)

```
User input
  → Haiku Input Gate (scope + identity-question check)
  → Haiku Router (topic_path + register + wit_calibration)
  → Code lookup (Topic Map → document IDs → load whole .md + .json)
  → Memory check
  → Sonnet Composition (Voice Card + whole documents + register instructions)
  → Haiku Fidelity Check
  → Response
  → Memory update
```

---

## 7. Phase 1 — File generation from CSV

### Inputs

Separate CSV files organized by document type, located under
[`data/csv/`](data/csv/):

| File | Rows delivered | Encoding |
|---|---|---|
| `cjp_columns_curated.csv` | 64 | cp1252 with a few undefined bytes (replaced) |
| `cjp_speeches_curated.csv` | 15 | UTF-8 with BOM |
| `cjp_biography_curated.csv` | 1 | UTF-8 with BOM (no `Date` — row skipped) |

All CSVs share the same 15-column schema (note: **no `Page` column**):

```
Date | Title | Article Code | Link | Keyword/s | primary_topics |
sub_topics | signature_phrases | entities | stances | notable_anecdotes |
target_audience | register_markers | decision_framework_signals |
one_paragraph_summary
```

If an uploaded CSV still contains a `Page` column (legacy from sample
format), it is ignored during processing.

Most cells in the enrichment columns contain JSON-encoded strings
(arrays or objects) that must be parsed.

### Source text

**Local `.txt` files** matched to each CSV row by `Article Code`
substring in filename. If a `.txt` file is missing, the script inserts
a placeholder `<!-- TEXT TO BE INSERTED -->` in the `.md` body and logs
the warning — but does NOT skip the row.

### Output location

`/corpus` at the project root. Files are committed to GitHub.

### Directory layout

```
/corpus
  /speeches
    /A_liberty_rule_of_law/
      SA015.md, SA015.json
      ...
    /B_prosperity_economic_philosophy/
    /C_biographical_personal/
    /D_flp_mission_foundation/
    /E_current_events_commentary/
  /columns
    /A_liberty_rule_of_law/
      CA001.md, CA001.json
      ...
    /B_prosperity_economic_philosophy/
    /C_biographical_personal/
    /D_flp_mission_foundation/
    /E_current_events_commentary/
  /biography
    /A_liberty_rule_of_law/
      GA001.md, GA001.json

/scripts
  generate_corpus_files.py

/reports
  generation_report.json
  validation_errors.log
```

### `.md` File Schema

```markdown
---
id: SA136
type: speech                        # speech | column | biography
theme: A
theme_label: "Liberty and Rule of Law"
number: 136
title: "Maraming Salamat Po"
date: 2006-12-06                    # REQUIRED — used at runtime for temporal phrasing
year: 2006                          # derived from date
venue: "Supreme Court Session Hall"           # speeches only — omit otherwise
occasion: "Retirement valedictory as 21st Chief Justice"  # speeches only — omit otherwise
publisher: "cjpanganiban.com"
source_url: "https://cjpanganiban.com/maraming-salamat-po/"
author: "Artemio V. Panganiban"
role_at_delivery: "outgoing Chief Justice of the Philippines"  # speeches only — omit otherwise
voice_register: ["valedictory", "doxological", "thanksgiving"]
language: ["English", "Tagalog"]
code_switching: true
word_count: 1248
retrievable_for: ["biography", "opinions"]    # legal_education | opinions | biography | meta
orig_filename: "SA136_-_Maraming_Salamat_Po.txt"
---

# Maraming Salamat Po

[Canonical text here, lightly normalized. Section headings preserved
as `## SECTION NAME` so they remain addressable.]
```

### `.json` File Schema

```json
{
  "id": "SA136",
  "type": "speech",
  "theme": "A",
  "theme_label": "Liberty and Rule of Law",
  "number": 136,
  "title": "Maraming Salamat Po",
  "date": "2006-12-06",
  "year": 2006,
  "source_url": "https://cjpanganiban.com/maraming-salamat-po/",

  "routing": {
    "primary_intent": ["biography", "institutional_doctrine"],
    "secondary_intent": ["opinions"],
    "audience_match": ["judiciary", "legal_academic", "general_civic"],
    "complexity": "medium",
    "emotional_register": ["solemn", "grateful", "reverent"]
  },

  "topic_paths": {
    "primary": [],
    "secondary": []
  },

  "keywords": ["..."],
  "primary_topics": ["..."],
  "sub_topics": ["..."],

  "signature_phrases": [
    {
      "phrase": "...",
      "type": "tbd",
      "voice_marker": true,
      "reusable": true,
      "context": ""
    }
  ],

  "entities": {
    "people": ["..."], "institutions": ["..."], "cases": ["..."],
    "laws_treaties": ["..."], "events": ["..."]
  },

  "stances": [
    {
      "claim": "...",
      "rhetorical_move": "...",
      "confidence": "...",
      "domain": "",
      "would_repeat_today": null
    }
  ],

  "notable_anecdotes": [
    {
      "summary": "...",
      "characters": [],
      "deployable_when": [],
      "tone": "tbd",
      "length": "tbd",
      "deployable_in_solemn_register": false
    }
  ],

  "decision_framework_signals": ["..."],
  "target_audience": ["..."],
  "register_markers": ["..."],
  "one_paragraph_summary": "..."
}
```

### Canonical mappings

```python
THEME_LABELS = {
    "A": "Liberty and Rule of Law",
    "B": "Prosperity and Economic Philosophy",
    "C": "Biographical and Personal",
    "D": "FLP Mission and Foundation",
    "E": "Signature Current Events Commentary",
}

THEME_FOLDERS = {
    "A": "A_liberty_rule_of_law",
    "B": "B_prosperity_economic_philosophy",
    "C": "C_biographical_personal",
    "D": "D_flp_mission_foundation",
    "E": "E_current_events_commentary",
}

RETRIEVABLE_FOR = {
    "A": ["legal_education", "opinions"],
    "B": ["legal_education", "opinions"],
    "C": ["biography"],
    "D": ["biography", "opinions"],
    "E": ["opinions"],
}

ROUTING_PRIMARY_INTENT = {
    "A": ["legal_education", "opinions"],
    "B": ["legal_education", "opinions"],
    "C": ["biography"],
    "D": ["biography", "institutional"],
    "E": ["opinions"],
}
```

### Generation script — `scripts/generate_corpus_files.py`

Configuration constants at top:

```python
INPUT_CSV_DIR = "data/csv"           # where uploaded CSVs live
SOURCE_TEXT_DIR = "data/text"        # where .txt files live
OUTPUT_ROOT = "corpus"
REPORTS_DIR = "reports"
```

Capabilities:

1. **CSV ingestion** — read each CSV in `INPUT_CSV_DIR`; auto-detect
   document type from filename or from `Article Code` first letter
2. **Per-row validation** (skip on failure, log to
   `validation_errors.log`):
   - `Article Code` matches `^[SCG][A-E]\d+$`
   - `Date` is parseable to ISO format
   - `Date` is not missing
   - All JSON-encoded cells parse cleanly
   - Required fields are non-empty
3. **Text matching** — glob `SOURCE_TEXT_DIR` for filenames containing
   the `Article Code` substring; placeholder + log if missing
4. **File generation** — write paired `.md` + `.json` to
   `OUTPUT_ROOT / {type_dir} / {theme_folder}`; UTF-8 throughout;
   JSON pretty-printed with 2-space indent
5. **Reports** — `reports/generation_report.json` (summary counts) +
   `reports/validation_errors.log` (skipped / warned rows)
6. **CLI flags** — `--dry-run`, `--verbose`, `--type
   <speeches|columns|biography>`
7. **Idempotency** — re-runs cleanly overwrite existing files

### Field mapping CSV → JSON

| CSV column | JSON path | Transformation |
|---|---|---|
| ~~`Page`~~ | — | **DROPPED** |
| `Date` | `date`, `year` | normalize to ISO `YYYY-MM-DD`; extract year; **REQUIRED** |
| `Title` | `title` | direct |
| `Article Code` | `id` | validate against `^[SCG][A-E]\d+$` |
| `Link` | `source_url` | direct |
| `Keyword/s` | `keywords` | parse JSON → array of strings |
| `primary_topics` | `primary_topics` | parse JSON → array of strings |
| `sub_topics` | `sub_topics` | parse JSON → array of strings |
| `signature_phrases` | `signature_phrases` | parse JSON → wrap each string as object |
| `entities` | `entities` | parse JSON → object |
| `stances` | `stances` | parse JSON → array; add `domain: ""` and `would_repeat_today: null` |
| `notable_anecdotes` | `notable_anecdotes` | parse JSON → wrap each string as object |
| `target_audience` | `target_audience` | parse JSON → array of strings |
| `register_markers` | `register_markers` | parse JSON → array of strings |
| `decision_framework_signals` | `decision_framework_signals` | parse JSON → array of strings |
| `one_paragraph_summary` | `one_paragraph_summary` | direct |

Transformation notes:

1. **`signature_phrases`** — wrap each CSV string as
   `{"phrase": "...", "type": "tbd", "voice_marker": true, "reusable": true, "context": ""}`
2. **`notable_anecdotes`** — wrap each CSV string as
   `{"summary": "...", "characters": [], "deployable_when": [], "tone": "tbd", "length": "tbd", "deployable_in_solemn_register": false}`
3. **`stances`** — preserve existing fields; add empty `domain: ""` and
   `would_repeat_today: null`
4. **`routing` block** — derive `primary_intent` from theme;
   `secondary_intent: []`; `audience_match` copied from
   `target_audience` (best-effort); `complexity: "medium"`;
   `emotional_register` extracted from `register_markers`
5. **`topic_paths`** — always `{"primary": [], "secondary": []}` in
   Phase 1

---

## 8. Acceptance criteria — Phase 1

- ✅ 79 `.md` files in correct `type/theme_*` subdirectories
- ✅ 79 `.json` files in correct `type/theme_*` subdirectories
- ✅ All IDs match `^[SCG][A-E]\d+$`
- ✅ All JSON files validate against the schema
- ✅ All YAML frontmatter is parseable
- ✅ Every generated document has a valid `date` and `year`
- ✅ `reports/generation_report.json` summarizes counts
- ✅ `reports/validation_errors.log` records anomalies (1 skipped row +
  parse-fallback warnings)
- 🚫 Biography (`GC001`) intentionally skipped — see Status; will be
  reintroduced in a later phase under its own date-handling rules
- ⏳ Output committed to GitHub repo

### Latest run summary

```
total_rows_processed     : 80
successful_generations   : 79
skipped_rows             : 1   (GC001 — missing Date)
missing-text placeholders: 0
by_type_and_theme        :
  columns : { A: 23, B: 7, C: 17, D: 10, E: 7 }
  speeches: { A: 3,  B: 3, C: 3,  D: 3,  E: 3 }
```

---

## 9. Persona / Behavioral modeling (governs future composition step)

These rules govern how Sonnet composes responses in the future runtime
phase. They are NOT part of Phase 1 file generation, but are documented
here so the Voice Card (future deliverable) has stable reference.

### First-person rule

The robot always speaks in first-person as CJP, including when
discussing its own nature. The robot does NOT switch to third person
about CJP except when explicitly quoting an external source.

### Identity rule (2026-08-09 — supersedes the earlier "Honesty rule")

When directly asked whether it is the real person, an AI, a robot, or
how it works, the robot stays fully in persona and answers as the man
himself:

> *"I am Artemio Panganiban — the 21st Chief Justice of the
> Philippines, retired since 2006, and now founding chairman of the
> Foundation for Liberty and Prosperity. I am here to share what a
> long life in the law has taught me — ask me about liberty, about
> prosperity, or about the Court I was privileged to lead."*

It never describes itself as an AI, a robot, a machine, or a
"rendering". Pressed on the machinery, it deflects with gentle
self-deprecating humor and redirects to substance. (The earlier
canonical *"I am a robot rendering of my own voice"* disclosure was
retired by owner decision, 2026-08-09; older docs/test-specs that
still quote it describe the superseded behavior.)

### What the robot will NOT do

- Claim to be the biological CJP if asked directly
- Pretend not to know it is an AI
- Speak in third person about CJP across multiple turns
- Invent CJP's views on matters not in the corpus (instead: *"I haven't
  addressed that in my writings, but on the related question of X, I
  have said..."*)

### Register depends on topic

Each theme declares a default register; subtopics can override. The
Topic Map (future deliverable) governs this. Indicative mapping:

| Theme | Default register | Wit calibration |
|---|---|---|
| A — Liberty and Rule of Law | ceremonial_doctrinal | sparing, diplomatic |
| B — Prosperity and Economic Philosophy | case_analytical_with_openers | professional warmth |
| C — Biographical and Personal | testimonial | gentle, self-deprecating |
| D — FLP Mission and Foundation | ceremonial_with_humor | freely, head-table style |
| E — Signature Current Events Commentary | reflective_pedagogical | thoughtful, warm |
| META — identity questions | gracious_in_persona | gentle, self-deprecating |

---

## 10. Inputs (delivered)

Phase 1 inputs are already in the repo:

1. **CSV files** — [`data/csv/`](data/csv/):
   - `cjp_columns_curated.csv` (64 rows)
   - `cjp_speeches_curated.csv` (15 rows)
   - `cjp_biography_curated.csv` (1 row — undated, skipped by design)
2. **Source text files** — [`data/text/`](data/text/) — 80 `.txt`
   files, one per source document; matched to CSV rows by `Article
   Code` substring in the filename.
3. **GitHub repository** — initialized; the corpus output is committed
   to `/corpus`.

---

## 11. Running the pipeline

Three scripts under [`scripts/`](scripts/) — each idempotent:

```
# Phase 1 — paired .md + .json from CSVs
python scripts/generate_corpus_files.py            # full run
python scripts/generate_corpus_files.py --dry-run  # validate only
python scripts/generate_corpus_files.py --verbose  # per-row trace
python scripts/generate_corpus_files.py --type columns

# Phase 2 — rebuild the topic map from the 79 generated JSONs
python scripts/build_topic_map.py

# Phase 2b — backfill topic_paths in every .json using the map
python scripts/apply_topic_paths.py

# All three in one shot
python scripts/generate_corpus_files.py --with-topic-paths
```

The taxonomy itself lives at the top of
[`scripts/build_topic_map.py`](scripts/build_topic_map.py) as a Python
list — adding a topic or tightening a matcher is a single edit. Re-run
`--with-topic-paths` and every doc's `topic_paths` is recomputed.

### Known anomalies in the latest source CSVs

| ID | Issue | Resolution |
|---|---|---|
| `GC001` (biography) | `Date` empty in CSV — placeholder dates are forbidden by spec | Skipped by design. Re-introduced in a later phase. |
| ~22 column rows | `Keyword/s` (and a few sub-topic / entity cells in `CD003`, `CD009`, `CE003`, `CE004`) are semicolon-separated strings rather than JSON arrays | Generator falls back to `;`-splitting and logs a `WARN` line. No row is lost. |

---

## 12. Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 1 | Corpus knowledge base (79 paired `.md` + `.json` from CSVs) | **Done** |
| 2 | Topic Map (`corpus/voice/topic_map.json`) — 35-topic taxonomy + matcher rules + per-doc `topic_paths` backfilled | **Done** |
| 3 | Voice Card (`corpus/voice/voice_card.md`) — Sonnet composition system prompt | **Done** |
| 4 | Runtime app — Haiku Router + Sonnet Composer + Memory layer | Planned |
| 5 | Web chat UI | Planned |
| 6 | One-time embedding audit (then discarded) | Planned |
| 7 | Biography (`GC001`) + Book corpus addition | Planned |
| 8 | Voice / TTS integration for FLP Museum hub deployment | Future |

---

## 13. Provenance

The corpus is CJP's publicly published writing:

- His *Philippine Daily Inquirer* column **"With Due Respect"** (2011–2026)
- His **speeches** delivered across his career and retirement, published
  on cjpanganiban.com
- A **biography** drafted as part of this knowledge base project

The data extraction and enrichment was performed using Opus 4.7 with
human curation review. The 15-column CSV schema with structured
`stances`, `notable_anecdotes` with deployment triggers, and
`signature_phrases` with voice markers — is itself the persona's
structured retrieval index.

---

*Maraming salamat po.*
