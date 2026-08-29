# docs/lessons/ — MANIFEST

Lessons learned, written as 5-Why root-cause analyses. One file per
surprise — the kind of "I would not have predicted this" finding that
is worth carrying into the next project. Append-only IDs.

| ID | File | Description |
|---|---|---|
| 0001 | [LL-001-cache-savings-18-not-55.md](LL-001-cache-savings-18-not-55.md) | Prompt-caching savings were 18%, not the projected 55% — overestimated voice card's share of inference input. |
| 0002 | [LL-002-haiku-ignores-cache-control.md](LL-002-haiku-ignores-cache-control.md) | Haiku 4.5 silently ignores `cache_control`; only Sonnet honors it on this SDK version. |
| 0003 | [LL-003-dotenv-override-false.md](LL-003-dotenv-override-false.md) | `python-dotenv`'s default `override=False` silently kept an empty shell-set `ANTHROPIC_API_KEY`. |
| 0004 | [LL-004-streamlit-caches-imported-modules.md](LL-004-streamlit-caches-imported-modules.md) | Streamlit caches imported modules across reloads — edits to `cj_chat.py` need Ctrl+C, not just dashboard reload. |
| 0005 | [LL-005-signature-library-loaded-but-unused.md](LL-005-signature-library-loaded-but-unused.md) | `signature_library.json` is loaded into memory but never reaches the inference call — 684 phrases contributing nothing. |
| 0006 | [LL-006-mixed-csv-cell-formats.md](LL-006-mixed-csv-cell-formats.md) | Strict JSON parsing rejected 22 of 64 column rows whose enrichment cells used semicolon-separated text. |
| 0007 | [LL-007-cp1252-control-bytes-through-latin1.md](LL-007-cp1252-control-bytes-through-latin1.md) | Latin-1 fallback let CP1252 undefined bytes through as YAML-breaking control characters. |
| 0008 | [LL-008-column-txt-no-separator.md](LL-008-column-txt-no-separator.md) | Column `.txt` files have no `---` block separator; body normaliser left header lines in the body. |
| 0009 | [LL-009-substring-matching-overbroad.md](LL-009-substring-matching-overbroad.md) | Substring topic matching let `supreme_court_history` claim 60 of 79 documents. |
| 0010 | [LL-010-article-code-typos-and-padding.md](LL-010-article-code-typos-and-padding.md) | Article codes inconsistent across CSVs — `CA01` vs `CA001`, `GCO01` for `GC001`. |
| 0011 | [LL-011-smoke-test-routing-miss-jmsu.md](LL-011-smoke-test-routing-miss-jmsu.md) | TS-006 question A4 (JMSU) routed to `supreme_court_history` instead of `eez_resource_sovereignty` — over-broad matcher beats specific topic. |
