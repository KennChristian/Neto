# Context Handover: CJ Panganiban Knowledge Base App Development (FINAL — v3)

## Project Overview

We are building a conversational app that embodies the persona of retired Chief Justice Artemio V. Panganiban (CJP) using his curated body of work. The app serves three pillars: **(1) legal education, (2) opinions, and (3) biography** — all grounded in CJP's institutional knowledge and writings. Personality: **serious but sometimes witty**.

The app is being developed for the **Foundation for Liberty and Prosperity (FLP)**, which CJP founded, in support of FLP's mission to "instill in Filipinos a deep appreciation for the essential interdependence of liberty and prosperity under the rule of law." This is a chat-based app (no robot/TTS at this stage).

## What's Already Done

Data curation (extraction + enrichment) has been completed for:
- **65 columns**
- **15 speeches**
- **1 biography**

Total for Phase 1: **81 documents**.

*(Book is excluded from this phase and will be handled separately.)*

All curated data will be uploaded as separate `.csv` files **organized by document type** (one CSV for columns, one for speeches, one for biography).

**IMPORTANT**: The user will upload the **final consolidated CSVs**. Do NOT use any previously generated CSVs from prior conversations — only use the CSVs the user provides for this task.

## Themes (canonical, locked)

The theme letter means the same thing whether the document is a speech, column, or biography section.

| Letter | Label | Description |
|---|---|---|
| **A** | Liberty and Rule of Law | Constitutional doctrine, judicial reform, civil liberties, court history, judicial stewardship |
| **B** | Prosperity and Economic Philosophy | Economic policy, deferential interpretation, entrepreneurship, business law, twin-beacons doctrine |
| **C** | Biographical and Personal | Family, faith, personal journey, marriage, friends, mentors, eulogies, milestone events |
| **D** | FLP Mission and Foundation | FLP programs (scholarships, fellowships, dissertations, chairs), partners, donors, ultimate projects (Museum, Fund), scholars |
| **E** | Signature Current Events Commentary | CJP's commentary on contemporary issues — technology, AI, public policy, political developments, society |

## ID Convention (strict, locked)

Format: `{Type}{Theme}{Number}` — no separator, no prefix.

- **`S`** = Speech
- **`C`** = Column
- **`G`** = Biography
- Theme = single letter `A` | `B` | `C` | `D` | `E`
- Number = matches the source's numbering (zero-padded as needed)

ID format must match regex: `^[SCG][A-E]\d+$`

Examples:
- `SA136` — Speech, Theme A, Number 136
- `CA005` — Column, Theme A, Number 005
- `SE001` — Speech, Theme E, Number 001
- `GA001` — Biography, Theme A, Number 001

**The IDs are themselves meaningful** — they encode type + theme + number. No redundant `page` field is needed.

## Date Handling — Critical

Dates are **semantically significant** for the app's responses. CJP's persona naturally references temporal context — e.g., "last year I wrote about...", "during my term as Chief Justice...", "ten years ago at the Global Forum..."

Therefore:
- Every document MUST have a valid `date` field in ISO `YYYY-MM-DD` format
- The date appears in both the `.md` frontmatter and the `.json`
- A `year` field (integer) is derived from `date` for convenient runtime filtering
- Runtime composition (Sonnet) will use the date to compute relative time phrasing where appropriate
- If a CSV row has a missing or malformed date, **log it as a validation error and skip the row** — do NOT use a placeholder date, since this would corrupt temporal reasoning at runtime

## Architecture Decisions (locked, for context — NOT to be built in this phase)

### Retrieval approach: Direct Corpus Interaction
- No vector store at runtime
- No chunking — documents are sent whole to the response model
- Retrieval is **deterministic structured lookup** via a curated Topic Map → Document IDs
- Embeddings may be used ONLY for one-time offline audit, never at runtime

### Runtime model stratification (future phase)
- **Haiku** — Input Gate, Router, Fidelity Check
- **Sonnet** — Composition (voice fidelity)
- No Opus at runtime

### Offline model
- **Opus 4.7** — for any further enrichment, persona synthesis, Voice Card drafting

### Runtime pipeline (future phase)
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

### Persona / Behavioral Modeling (governs future composition step, NOT this phase)
- **First-person CJP always** — including when discussing the app's own nature
- When asked directly what it is: "I am an AI conversation robot built by the Foundation for Liberty and Prosperity to share my institutional knowledge and experience..."
- Canonical self-description: "I am a robot rendering of my own voice, not the man himself"
- Never claims to BE the biological CJP; never pretends not to know it is an AI
- Never invents views on matters not in the corpus
- Register depends on topic — see future Topic Map's `default_register` and `wit_calibration` per theme/subtopic

## What Claude Code Needs to Build — Phase 1: File Generation from CSV

### Task
Generate paired `.md` + `.json` files from the user-provided curated CSV files — one pair per document. Expected output: **81 `.md` files + 81 `.json` files** (65 columns + 15 speeches + 1 biography).

### Inputs (user will upload)
Separate CSV files organized by document type:
- One CSV for **columns** (65 rows expected)
- One CSV for **speeches** (15 rows expected)
- One CSV for **biography** (1 row expected)

All CSVs share the same column schema. Expected columns (15 total, **no `Page` column**):

```
Date | Title | Article Code | Link | Keyword/s | primary_topics | 
sub_topics | signature_phrases | entities | stances | notable_anecdotes | 
target_audience | register_markers | decision_framework_signals | 
one_paragraph_summary
```

If the user's uploaded CSV still contains a `Page` column (legacy from sample format), ignore it during processing — do not include it in the output `.json`.

Most cells in the enrichment columns contain JSON-encoded strings (arrays or objects) that must be parsed.

### Canonical Text Source
**LOCAL `.txt` files**
- The user will provide the original `.txt` files locally
- Match each CSV row to its `.txt` file by `Article Code` substring in filename
- If a `.txt` file is missing for a row, log the issue and insert a placeholder `<!-- TEXT TO BE INSERTED -->` in the `.md` body; do NOT skip the row for missing text alone

### Output Location
**Local directory, version-controlled via GitHub**
- Output root: `/corpus` at the project root
- Files will be committed to the GitHub repo after generation

### Directory Layout

```
/corpus
  /speeches
    /A_liberty_rule_of_law/
      SA015.md
      SA015.json
      SA041.md
      SA041.json
      SA136.md
      SA136.json
      ...
    /B_prosperity_economic_philosophy/
    /C_biographical_personal/
    /D_flp_mission_foundation/
    /E_current_events_commentary/
  /columns
    /A_liberty_rule_of_law/
      CA001.md
      CA001.json
      ...
    /B_prosperity_economic_philosophy/
    /C_biographical_personal/
    /D_flp_mission_foundation/
    /E_current_events_commentary/
  /biography
    /{theme}_*/             # whichever theme(s) apply
      GA001.md
      GA001.json

/scripts
  generate_corpus_files.py

/reports
  generation_report.json
  validation_errors.log
```

**Theme folder naming**: snake_case versions of the labels, prefixed by letter:
- `A_liberty_rule_of_law`
- `B_prosperity_economic_philosophy`
- `C_biographical_personal`
- `D_flp_mission_foundation`
- `E_current_events_commentary`

### `.md` File Schema (YAML frontmatter + canonical text)

```markdown
---
id: SA136
type: speech                        # speech | column | biography
theme: A
theme_label: "Liberty and Rule of Law"
number: 136
title: "Maraming Salamat Po"
date: 2006-12-06                    # REQUIRED — used at runtime for temporal phrasing
year: 2006                          # derived from date for convenient filtering
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

[Canonical text here, lightly normalized. Preserve section headings as `## SECTION NAME`.]
```

**No `page` field.**

**Field derivation rules**:

| Field | Derivation |
|---|---|
| `id` | from CSV `Article Code` |
| `type` | from first letter of `id` (`S`/`C`/`G` → `speech`/`column`/`biography`) |
| `theme` | from second letter of `id` |
| `theme_label` | from theme letter via canonical mapping (table below) |
| `number` | from third character onward of `id`, as integer |
| `title` | direct from CSV |
| `date` | normalize CSV `Date` to ISO `YYYY-MM-DD` |
| `year` | integer extracted from `date` |
| `venue`, `occasion`, `role_at_delivery` | extract from speech `.txt` header lines (the metadata block at the top); omit for columns/biography |
| `publisher` | from `.txt` header; default `"cjpanganiban.com"` if not specified |
| `source_url` | from CSV `Link` |
| `voice_register` | extract registry-style descriptors from CSV `register_markers` |
| `language` | always include `"English"`; add `"Tagalog"` if Tagalog words detected in body |
| `code_switching` | true if both languages detected |
| `word_count` | compute from canonical text body |
| `retrievable_for` | derive from theme (table below) |
| `orig_filename` | name of the `.txt` file used |

**Theme letter → label mapping**:
```python
THEME_LABELS = {
    "A": "Liberty and Rule of Law",
    "B": "Prosperity and Economic Philosophy",
    "C": "Biographical and Personal",
    "D": "FLP Mission and Foundation",
    "E": "Signature Current Events Commentary",
}
```

**Theme letter → retrievable_for mapping**:
```python
RETRIEVABLE_FOR = {
    "A": ["legal_education", "opinions"],
    "B": ["legal_education", "opinions"],
    "C": ["biography"],
    "D": ["biography", "opinions"],
    "E": ["opinions"],
}
```

**Theme folder names**:
```python
THEME_FOLDERS = {
    "A": "A_liberty_rule_of_law",
    "B": "B_prosperity_economic_philosophy",
    "C": "C_biographical_personal",
    "D": "D_flp_mission_foundation",
    "E": "E_current_events_commentary",
}
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

**No `page` field.**

**`year` field** is added as a convenience for runtime filtering (e.g., "what did CJP write last year about X?" — filter on year, then narrow by topic).

### Field Mapping CSV → JSON

| CSV column | JSON path | Transformation |
|---|---|---|
| ~~`Page`~~ | — | **DROPPED** — not used |
| `Date` | `date`, `year` | normalize to ISO `YYYY-MM-DD`; extract year as int; **REQUIRED** — skip row if missing/invalid |
| `Title` | `title` | direct |
| `Article Code` | `id` | validate against `^[SCG][A-E]\d+$` |
| `Link` | `source_url` | direct |
| `Keyword/s` | `keywords` | parse JSON → array of strings |
| `primary_topics` | `primary_topics` | parse JSON → array of strings |
| `sub_topics` | `sub_topics` | parse JSON → array of strings |
| `signature_phrases` | `signature_phrases` | parse JSON → wrap each string as object (note 1) |
| `entities` | `entities` | parse JSON → object |
| `stances` | `stances` | parse JSON → array; add `domain: ""` and `would_repeat_today: null` per item |
| `notable_anecdotes` | `notable_anecdotes` | parse JSON → wrap each string as object (note 2) |
| `target_audience` | `target_audience` | parse JSON → array of strings |
| `register_markers` | `register_markers` | parse JSON → array of strings |
| `decision_framework_signals` | `decision_framework_signals` | parse JSON → array of strings |
| `one_paragraph_summary` | `one_paragraph_summary` | direct |

**Transformation notes**:

1. **`signature_phrases`** — In the CSV this is `["phrase1", "phrase2", ...]`. Transform each string into:
   ```json
   {"phrase": "phrase1", "type": "tbd", "voice_marker": true, "reusable": true, "context": ""}
   ```

2. **`notable_anecdotes`** — In the CSV this is `["anecdote text 1", ...]`. Transform each string into:
   ```json
   {
     "summary": "anecdote text 1",
     "characters": [],
     "deployable_when": [],
     "tone": "tbd",
     "length": "tbd",
     "deployable_in_solemn_register": false
   }
   ```

3. **`stances`** — already objects in CSV; preserve existing `claim`, `rhetorical_move`, `confidence` and ADD empty `domain: ""` and `would_repeat_today: null`.

4. **`routing` block** — derive at generation time:
   - `primary_intent`: by theme:
     - A → `["legal_education", "opinions"]`
     - B → `["legal_education", "opinions"]`
     - C → `["biography"]`
     - D → `["biography", "institutional"]`
     - E → `["opinions"]`
   - `secondary_intent`: leave as `[]`
   - `audience_match`: copy from `target_audience` (best-effort categorization; if unclear, leave `[]`)
   - `complexity`: default `"medium"`
   - `emotional_register`: extract emotion-tone words from `register_markers`; if none, `[]`

5. **`topic_paths`** — always `{"primary": [], "secondary": []}` in this phase. Populated separately when the Topic Map is curated.

### Generation Script Requirements

Build `scripts/generate_corpus_files.py`:

1. **Configuration constants** at the top of the file:
   ```python
   INPUT_CSV_DIR = "data/csv"           # where uploaded CSVs live
   SOURCE_TEXT_DIR = "data/text"        # where .txt files live
   OUTPUT_ROOT = "corpus"
   REPORTS_DIR = "reports"
   ```

2. **CSV ingestion**:
   - Read each CSV in `INPUT_CSV_DIR`
   - Auto-detect document type from filename (e.g., `*columns*.csv` → columns) or from `Article Code` first letter
   - Validate that filename-implied type matches `Article Code` types in the rows
   - Parse all JSON-encoded cells safely (catch `json.JSONDecodeError`, log row, continue)

3. **Per-row validation** (in order; any failure → log and skip):
   - `Article Code` matches `^[SCG][A-E]\d+$`
   - `Date` is parseable to ISO format
   - `Date` is not missing
   - All JSON-encoded cells parse cleanly
   - Required fields are non-empty (`Title`, `Article Code`, `Date`)

4. **Text matching**:
   - For each valid row, locate the corresponding `.txt` file in `SOURCE_TEXT_DIR`
   - Strategy: glob for filenames containing the `Article Code` substring (e.g., `SA136*.txt`)
   - If multiple matches, prefer the one whose name most closely matches the title
   - If no match: insert placeholder `<!-- TEXT TO BE INSERTED -->` in `.md` body, log to `validation_errors.log` (as warning, not error)
   - If found: read text, normalize whitespace, preserve section headings as `## HEADING`

5. **File generation**:
   - Compute output directory: `OUTPUT_ROOT / {type_dir} / {theme_folder}`
     - `type_dir`: `speeches` | `columns` | `biography`
     - `theme_folder`: from `THEME_FOLDERS` mapping
   - Create directories if not exist
   - Write `{id}.md` with YAML frontmatter + body
   - Write `{id}.json` with structured record
   - UTF-8 encoding throughout
   - JSON pretty-printed with 2-space indent

6. **Reports**:
   - `reports/generation_report.json`:
     ```json
     {
       "run_timestamp": "2026-XX-XX...",
       "total_rows_processed": 81,
       "successful_generations": 80,
       "skipped_rows": 1,
       "missing_text_placeholders": 2,
       "by_type_and_theme": {
         "speeches": {"A": 3, "B": 3, "C": 3, "D": 3, "E": 3},
         "columns": {"A": 20, "B": 15, "C": 10, "D": 10, "E": 10},
         "biography": {"A": 1}
       }
     }
     ```
   - `reports/validation_errors.log`: human-readable log of skipped/warned rows with reasons

7. **CLI flags**:
   - `--dry-run`: validate and report without writing files
   - `--verbose`: print each row processed
   - `--type <speeches|columns|biography>`: process only one type (useful for incremental runs)

8. **Idempotency**: Running the script twice should cleanly overwrite existing files.

### GitHub Workflow

After generation:
1. Verify expected file pair counts (allowing for any documented skipped rows)
2. Review `generation_report.json` and `validation_errors.log`
3. Commit to GitHub with structured commit message:
   ```
   feat(corpus): generate initial CJP knowledge base (Phase 1)
   
   - 65 columns across themes A-E
   - 15 speeches across themes A-E
   - 1 biography (theme A)
   
   Paired .md + .json per document.
   ID format: {Type}{Theme}{Number} — meaningful IDs only, no Page field.
   topic_paths fields empty pending Topic Map curation.
   ```

### Acceptance Criteria

- ✅ Up to 81 `.md` files in correct `type/theme_*` subdirectories
- ✅ Up to 81 `.json` files in correct `type/theme_*` subdirectories
- ✅ All IDs match `^[SCG][A-E]\d+$`
- ✅ All JSON files validate against the schema
- ✅ All YAML frontmatter is parseable
- ✅ Every document has a valid `date` and `year`
- ✅ `reports/generation_report.json` summarizes counts
- ✅ `reports/validation_errors.log` records any anomalies
- ✅ Output committed to GitHub repo

## Out of Scope for This Phase

Do NOT build any of the following — they are separate downstream tasks:

- ❌ **Topic Map** (`/corpus/voice/topic_map.json`) — curated separately; `topic_paths` fields stay empty
- ❌ **Voice Card** (`/corpus/voice/voice_card.md`) — drafted separately
- ❌ **Runtime app** — Haiku Router, Sonnet composer, Memory layer
- ❌ **Web frontend / chat UI**
- ❌ **Embedding audit** — one-time offline task, runs after corpus is fully generated
- ❌ **Book** — excluded from Phase 1; will be added later
- ❌ **Enrichment of placeholder fields** (`type: "tbd"`, `tone: "tbd"`, `length: "tbd"`) — handled in subsequent enrichment passes

This phase ends when the file pairs exist on disk, validated, traceable to source CSV rows, and committed to GitHub.

## Inputs the User Will Provide

When the user starts the conversation with Claude Code, they will upload:

1. **CSV files** (one per document type):
   - Columns CSV (65 rows)
   - Speeches CSV (15 rows)
   - Biography CSV (1 row)
   - (Filenames may vary; auto-detect from content / filename hints)

2. **Source text files**: Original `.txt` files for each document, locally accessible.

3. **GitHub repository**: Already initialized; Claude Code should commit to it.

## What Claude Code Should Do First

1. Confirm receipt of the uploaded CSVs and `.txt` files
2. Inspect each CSV's column schema to verify it matches the expected 15-column structure (and tolerate but ignore a `Page` column if present)
3. Spot-check 2–3 rows of each CSV to confirm JSON-encoded cells parse cleanly
4. Verify a sample `.txt` file is readable and matches an expected CSV row
5. Confirm the GitHub repo structure (where `/corpus` should live)
6. **Then** proceed with full generation

---

**Hand-off complete. Claude Code: begin Phase 1 — File Generation from CSV — using the inputs the user will provide. Do NOT use any CSVs generated in prior Claude.ai conversations; only use the CSVs the user uploads directly to your session.**
