# TS-001: Corpus generator contract — CSV → `.md` + `.json`

* Status: draft
* Verifies:
  [ADR-0011](../decisions/0011-corpus-id-format-type-theme-number.md),
  [ADR-0012](../decisions/0012-permissive-csv-enrichment-parsing.md),
  [ADR-0013](../decisions/0013-strict-date-validation-no-placeholders.md)
* Subject: `scripts/generate_corpus_files.py`
* Style: model-based — state-transition model of the row processor,
  given/when/then scenarios per transition

## 1. Model

The generator processes one CSV row at a time through these states:

```
                     ┌── normalised
INPUT ── normalise ──┤
                     └── rejected (logged)
                          │
normalised ── parse-date ─┤── dated
                          └── undated (row SKIP — strict)
                          │
dated ── parse-cells ─────┤── parsed-strict
                          ├── parsed-fallback (warn, continue)
                          └── (no failure path — always succeeds)
                          │
parsed ── locate-text ────┤── text-found
                          └── text-missing (placeholder; warn; continue)
                          │
text-found ─ write-files ─┤── written
text-missing              └── (no failure path)
```

The terminal states are `rejected`, `SKIP (undated)`, and `written`
(with optional warnings).

## 2. Given / When / Then scenarios — happy paths

### 2.1 Smoke — well-formed column row

**Given** a row with `Article Code = "CA001"`, `Date = "October 23,
2023"`, valid JSON arrays in every enrichment cell, and a matching
`data/text/CA001.txt`,
**When** the generator runs,
**Then** `corpus/columns/A_liberty_rule_of_law/CA001.{md,json}` are
written, body has no leading metadata, frontmatter is valid YAML,
JSON validates against the schema, `date == "2023-10-23"`, `year ==
2023`, `topic_paths == {"primary": [], "secondary": []}` until
PLAN-0002 backfill.

### 2.2 Smoke — well-formed speech row

**Given** `Article Code = "SA136"`, `Date = "December 6, 2006"`, full
JSON enrichment, matching `data/text/SA136.txt` with `---` separator
between header and body,
**When** generated,
**Then** `corpus/speeches/A_liberty_rule_of_law/SA136.{md,json}`
written, `type == "speech"`, body starts after the `---`,
`occasion` field carries the descriptive header line.

## 3. Given / When / Then — ID validation (ADR-0011)

### 3.1 `Article Code` matches regex strictly

**Given** `Article Code = "CA001"`,
**When** generator runs,
**Then** row writes successfully.

### 3.2 `Article Code` is 2-digit padded

**Given** `Article Code = "CA01"`,
**When** generator runs,
**Then** `normalize_article_code` returns `"CA001"`; row writes to
`CA001.{md,json}`; `id == "CA001"`.

### 3.3 `Article Code` has `O`-typo

**Given** `Article Code = "GCO01"`,
**When** generator runs,
**Then** `normalize_article_code` returns `"GC001"`; row writes
successfully.

### 3.4 `Article Code` is lowercased

**Given** `Article Code = "ca001"`,
**When** generator runs,
**Then** normalised to `"CA001"`; written.

### 3.5 `Article Code` has invalid type letter

**Given** `Article Code = "ZA001"`,
**When** generator runs,
**Then** row is rejected with reason
*"invalid Article Code ZA001 (must match ^[SCG][A-E]\d+$ after
normalisation)"*; logged in `validation_errors.log`.

### 3.6 `Article Code` is empty

**Given** `Article Code = ""`,
**When** generator runs,
**Then** row rejected.

### 3.7 `Article Code` has invalid theme letter

**Given** `Article Code = "CF001"`,
**When** generator runs,
**Then** row rejected.

## 4. Given / When / Then — date validation (ADR-0013)

### 4.1 ISO-format date

**Given** `Date = "2023-10-23"`,
**Then** parses; row writes; `year = 2023`.

### 4.2 Long-form English date

**Given** `Date = "October 23, 2023"`,
**Then** parses to `"2023-10-23"`.

### 4.3 Abbreviated month

**Given** `Date = "Oct 23, 2023"`,
**Then** parses.

### 4.4 Empty date

**Given** `Date = ""`,
**Then** row is **skipped** with reason
*"missing or unparseable Date '' for {id}"*; logged. No `.md` /
`.json` written.

### 4.5 `[Not specified]` placeholder

**Given** `Date = "[Not specified]"`,
**Then** treated as undated → row skipped (no auto-generated
placeholder date).

### 4.6 Malformed date

**Given** `Date = "October 32, 2023"`,
**Then** row skipped.

### 4.7 Future-dated row

**Given** `Date = "2099-01-01"`,
**Then** parses; row writes. (No business-rule check on future dates;
generator trusts the curator. Out-of-corpus reasoning is enforced at
runtime by the voice card.)

## 5. Given / When / Then — enrichment parsing (ADR-0012)

### 5.1 Valid JSON array

**Given** `Keyword/s = "[\"a\", \"b\", \"c\"]"`,
**Then** `keywords == ["a","b","c"]`; no warning.

### 5.2 Semicolon-separated list

**Given** `Keyword/s = "a; b; c"`,
**Then** `keywords == ["a","b","c"]`; row writes with WARN line in
`validation_errors.log`.

### 5.3 Single free-text item

**Given** `Keyword/s = "some prose description with no separator"`,
**Then** `keywords == ["some prose description with no separator"]`;
WARN.

### 5.4 Empty enrichment cell

**Given** `Keyword/s = ""`,
**Then** `keywords == []`; no warning.

### 5.5 `entities` cell is plain text

**Given** `entities = "FLP scholars from 2025 including Acidre..."`,
**Then** `entities == {"people":[],"institutions":[],"cases":[],
"laws_treaties":[],"events":[]}` (default empty object); WARN.

### 5.6 Mixed validity per row

**Given** valid `primary_topics` JSON but invalid `signature_phrases`
JSON in the same row,
**Then** both cells processed independently: `primary_topics` parsed
strictly; `signature_phrases` falls back. Two WARN lines if both fail
parsing; otherwise one per failed cell.

### 5.7 `signature_phrases` wraps strings as objects

**Given** valid JSON `["phrase A","phrase B"]`,
**Then** stored as
`[{"phrase":"phrase A","type":"tbd","voice_marker":true,
"reusable":true,"context":""}, ...]`.

### 5.8 `notable_anecdotes` wraps strings as objects

**Given** valid JSON `["anecdote text 1","..."]`,
**Then** each becomes
`{"summary":"...","characters":[],"deployable_when":[],"tone":"tbd",
"length":"tbd","deployable_in_solemn_register":false}`.

## 6. Given / When / Then — text source matching

### 6.1 Exact-id `.txt` exists

**Given** `id = "SA136"` and `data/text/SA136.txt` exists,
**Then** body loaded from that file.

### 6.2 Unpadded `.txt` filename

**Given** `id = "CA001"` and `data/text/CA1.txt` exists (no
`CA001.txt`),
**Then** unpadded fallback in `find_source_text()` locates
`CA1.txt`; body loaded.

### 6.3 No matching `.txt`

**Given** `id = "CA999"` and no matching `.txt`,
**Then** body = `<!-- TEXT TO BE INSERTED -->`; WARN logged;
`missing_text_placeholders` counter incremented.

### 6.4 Multiple `.txt` candidates

**Given** both `SA136.txt` and `SA136_alt.txt` exist,
**Then** first alphabetically is used; documented behavior.

## 7. Given / When / Then — encoding (ADR-0012)

### 7.1 UTF-8 with BOM

**Given** the CSV is UTF-8 with BOM,
**Then** read with `utf-8-sig`; all bytes decoded.

### 7.2 CP1252 with smart quotes

**Given** CSV contains em-dash `0x97` and right single quote `0x92`,
**Then** read with `cp1252`; characters preserved as Unicode in
output.

### 7.3 CP1252 with undefined byte

**Given** CSV contains `0x9D` (undefined in CP1252),
**Then** strict `cp1252` fails; terminal fallback `cp1252+replace`
substitutes `U+FFFD`; row writes; encoding `cp1252+replace` reported.

### 7.4 Body normaliser drops column header lines

**Given** `data/text/CA001.txt` has the title repeated, `Date:`,
`Publisher:`, `Source:`, `By:` header lines and no `---`,
**Then** body in `.md` starts at the first non-header line.

### 7.5 Body normaliser respects `---` for speeches

**Given** `data/text/SA136.txt` has metadata block ending with
`---`,
**Then** body starts after the `---`.

## 8. Edge cases & boundary conditions

| Case | Expected behavior |
|---|---|
| CSV has 0 data rows | Generator runs, 0 successes, 0 errors |
| CSV column header missing | Run aborts at CSV load with a clear error |
| Required field `Title` empty | Row skipped |
| `Date` is just whitespace | Row skipped (parsed as empty) |
| `Article Code` has trailing whitespace | Normaliser strips |
| `Article Code` is `"GA00"` (zero number) | Row rejected ("number ≤ 0") |
| Bytes in body fail UTF-8 decode | `errors='replace'` smooths; runs |
| Output file already exists | Idempotent overwrite |
| `data/csv/` has zero CSVs | Run aborts with message |
| `data/csv/` has unrecognised CSV name | Auto-detect type from `Article Code` first letter; runs |
| `--dry-run` flag | No files written; reports still produced |
| `--type columns` flag | Only that type's CSV processed |
| `--verbose` flag | Per-row sample line printed |

## 9. Smoke — first-of-each-stratum

Print one sample per type after generation:
```
[sample] CA001 (column, theme A): body=" This column is a shortened ..."
[sample] SA015 (speech, theme A): body=" YOUR HONORS, LADIES ..."
```

(Not yet implemented; captured as a `[sample]` deliverable in
[PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)
§5.)

## 10. Integration with downstream

- After a successful generator run, **every `.md` frontmatter parses
  through `yaml.safe_load`** (or equivalent strict YAML parser).
- **Every `.json` parses** through `json.loads`.
- IDs across `.md`, `.json`, and filename agree.
- A doc skipped by date never produces orphan files (no `.md` without
  `.json` or vice versa).

## 11. Failure modes (observability)

- `reports/generation_report.json` records per-run summary —
  `total_rows_processed`, `successful_generations`, `skipped_rows`,
  `missing_text_placeholders`, `by_type_and_theme`.
- `reports/validation_errors.log` records every SKIP and WARN with
  source-CSV filename + line number + reason.
- Generator returns exit code 0 on success (even with WARNs); 2 if
  the CSV directory is missing or unreadable.

## 12. Out-of-scope for this spec

- LLM-grounded behaviour (covered by
  [TS-004](TS-004-voice-card-protocol.md)).
- Topic-map matcher behaviour (covered by
  [TS-002](TS-002-topic-map-matchers.md)).
- End-to-end pipeline behaviour (covered by
  [TS-005](TS-005-end-to-end-pipeline-smoke.md)).
