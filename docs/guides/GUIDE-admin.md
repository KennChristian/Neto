# Admin guide — pipeline operations

Audience: **The person who runs the pipeline, adds documents,
re-curates the taxonomy, and interprets the run reports.**

This guide assumes you have a working Python environment and shell
access to the repo. It does not assume runtime / production
familiarity.

## 1. Repository map (admin-relevant)

```
data/
  csv/                  # ← curated CSV inputs (3 files)
  text/                 # ← source .txt files (80 files; one per CSV row + biography)
scripts/
  generate_corpus_files.py     # Phase 1 — CSV → .md + .json
  build_topic_map.py           # Phase 2 — taxonomy + matchers
  apply_topic_paths.py         # Phase 2b — backfill topic_paths
corpus/
  columns/              # 64 .md + .json pairs (Phase 1 output)
  speeches/             # 15 .md + .json pairs (Phase 1 output)
  biography/            # currently empty (GC001 pending date)
  voice/                # Phase 2 + 3 artifacts
    topic_map.json
    voice_card.md
reports/
  generation_report.json       # Phase 1 run summary
  validation_errors.log        # Phase 1 SKIP + WARN
  topic_map_report.json        # Phase 2 coverage / unmatched docs
```

## 2. Daily ops

### 2.1 Run the full pipeline (corpus → topic_map → topic_paths)

```
python scripts/generate_corpus_files.py --with-topic-paths
```

This is idempotent. Re-running cleanly overwrites previous outputs.
Expected run time: ~30 seconds.

### 2.2 Run only Phase 1 (after editing a CSV row)

```
python scripts/generate_corpus_files.py
```

Adds the new docs / refreshes changed docs in `corpus/columns/` and
`corpus/speeches/`. `topic_paths` will be empty until you run the
backfill step.

### 2.3 Run only Phase 2 (after editing the taxonomy)

```
python scripts/build_topic_map.py       # rebuild topic_map.json
python scripts/apply_topic_paths.py     # backfill topic_paths
```

### 2.4 Dry run (validate without writing)

```
python scripts/generate_corpus_files.py --dry-run --verbose
```

Use this when you want to preview what *would* change without
modifying corpus files.

### 2.5 Filter to one type

```
python scripts/generate_corpus_files.py --type columns
python scripts/generate_corpus_files.py --type speeches
python scripts/generate_corpus_files.py --type biography
```

## 3. Adding a new document

### 3.1 Author the source `.txt`

Place at `data/text/{ID}.txt`. ID convention:
`{Type}{Theme}{Number}` (see
[ADR-0011](../decisions/0011-corpus-id-format-type-theme-number.md)).
Number is zero-padded to ≥3 digits.

File template (column / speech / biography):

```
TITLE

Date:       2026-05-26
Publisher:  cjpanganiban.com OR Philippine Daily Inquirer
Source:     https://...

[optional descriptive line for speeches: "Address delivered at..."]

---

[body of the article here, headings as `SECTION NAME` (caps, no `#`)
or `## Section Name` (markdown). Both are normalised the same way.]
```

For columns: the `---` separator is optional; the generator's
`normalize_body()` strips header lines either way.

### 3.2 Author the CSV row

Open the appropriate CSV in `data/csv/`:

- Columns → `cjp_columns_curated.csv`
- Speeches → `cjp_speeches_curated.csv`
- Biography → `cjp_biography_curated.csv`

Add a row matching the 15-column schema. The columns are:

```
Date, Title, Article Code, Link, Keyword/s, primary_topics,
sub_topics, signature_phrases, entities, stances, notable_anecdotes,
target_audience, register_markers, decision_framework_signals,
one_paragraph_summary
```

For the enrichment columns, you can use either:

- **JSON array**: `["keyword1", "keyword2"]` — strict, recommended.
- **Semicolon-separated**: `"keyword1; keyword2"` — works but logs a
  WARN ([ADR-0012](../decisions/0012-permissive-csv-enrichment-parsing.md)).

For `entities`, prefer JSON object:

```json
{"people": ["..."], "institutions": ["..."], "cases": [], "laws_treaties": [], "events": []}
```

For `stances` and `notable_anecdotes`, prefer JSON array of objects:

```json
[{"claim": "...", "rhetorical_move": "...", "confidence": "..."}]
```

### 3.3 Run the pipeline

```
python scripts/generate_corpus_files.py --with-topic-paths
```

### 3.4 Verify

Open the generated `corpus/{type}/{theme_folder}/{ID}.md` and
`.json`. Confirm `topic_paths.primary` is sensible (see
[GUIDE-reviewer.md](GUIDE-reviewer.md) §3c for the checklist).

## 4. Re-curating the taxonomy

The taxonomy lives in `scripts/build_topic_map.py` as a Python list
called `TAXONOMY`. **Edit it directly.** Follow the operations
playbook in
[PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md):

- **Add a topic** — append a new dict to `TAXONOMY`.
- **Retire a topic** — delete the dict from `TAXONOMY`.
- **Tighten matchers** — edit the topic's `matchers.keywords` list,
  removing over-broad terms.
- **Loosen matchers** — add new keyword variants.
- **Split / merge** — author new entries, delete old.

After every edit:

```
python scripts/build_topic_map.py       # rebuild topic_map.json
python scripts/apply_topic_paths.py     # refresh topic_paths
```

Spot-check the matcher health:

- Open `reports/topic_map_report.json`.
- Check `unmatched_docs` is `[]`.
- Look at per-topic `doc_count` in `corpus/voice/topic_map.json`. No
  topic should claim >25% of corpus (currently 79 docs → cap at ~20).

## 5. Reading the reports

### 5.1 `reports/generation_report.json`

After every Phase 1 run:

```json
{
  "total_rows_processed": 80,
  "successful_generations": 79,
  "skipped_rows": 1,
  "missing_text_placeholders": 0,
  "by_type_and_theme": {
    "columns": {"A": 23, "B": 7, "C": 17, "D": 10, "E": 7},
    "speeches": {"E": 3, "D": 3, "B": 3, "A": 3, "C": 3}
  }
}
```

- **`skipped_rows > 0`** → look in `validation_errors.log` for the
  reason. Typically a date or ID issue.
- **`missing_text_placeholders > 0`** → at least one CSV row has no
  matching `data/text/*.txt`. Either author the `.txt` or remove the
  CSV row.

### 5.2 `reports/validation_errors.log`

Two categories:

- **`# ERRORS (rows skipped)`** — these did not produce files. Fix
  before re-running if you need the doc.
- **`# WARNINGS (row generated with notice)`** — these produced
  files with reduced fidelity. Worth re-curating in the long run.

### 5.3 `reports/topic_map_report.json`

After every Phase 2 run:

```json
{
  "n_docs": 79,
  "unmatched_docs": [],
  "per_doc": [
    {"id": "CA004", "title": "...", "theme": "A",
     "topics_hit": 5,
     "primary": ["impeachment_accountability", "constitutional_doctrine"],
     "secondary": ["due_process"],
     "top_scores": {...}}
    ...
  ]
}
```

- **`unmatched_docs` non-empty** → these docs have no topic_paths.
  Curator action needed
  ([PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)).

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Row skipped with "missing or unparseable Date" | CSV date cell empty / wrong format | Set a valid ISO date or known long-form (`October 23, 2023`). |
| Row skipped with "invalid Article Code" | Typo or unrecognised type/theme letter | Confirm `^[SCG][A-E]\d+$`; the normaliser handles common typos. |
| Row generates but `Keyword/s: JSON parse failed` WARN | Cell is `;`-separated, not JSON | Either accept the WARN or re-author the cell as JSON. |
| `body has `<!-- TEXT TO BE INSERTED -->`` | No matching `.txt` in `data/text/` | Author the `.txt` or check filename matches the ID. |
| Replacement characters (`?` / `U+FFFD`) in body | CSV had unmappable CP1252 bytes | Re-save CSV as UTF-8 or accept the lossy substitution. |
| Topic has 0 docs and shouldn't | Matchers too narrow | Loosen via PLAN-0007 §3d. |
| Topic claims >25% of corpus | Matchers too broad | Tighten via PLAN-0007 §3c. |

## 7. Git hygiene

Recommended commit pattern when changing the corpus:

- One commit for CSV / .txt source changes.
- One commit for the generated `corpus/**/*.md`, `.json` outputs.
- One commit for taxonomy edits + `topic_map.json` rebuilds (if
  any).
- Reviewer can see (a) what the curator changed in inputs and
  (b) what the generator produced as outputs as separate diffs.

For tighter / more atomic history, see
[GUIDE-manager.md](GUIDE-manager.md) §"Phase commit pattern".

## 8. When to escalate

- **Schema-affecting changes** (new type letter, new ID format, new
  `topic_paths` semantics) → file a new ADR before implementing.
- **New persona behaviour** (different out-of-corpus policy, new
  register tag) → file a new ADR; update voice card; update
  TS-004.
- **Recurring SKIP / WARN patterns** that look like curator
  workflow issues → file a 5-Why lesson (`docs/lessons/LL-XXX`)
  with the root cause.
