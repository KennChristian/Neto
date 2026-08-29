# LL-007: Latin-1 fallback let CP1252 undefined bytes through as YAML-breaking control chars

* Date: 2026-05-26
* Severity: moderate (2 of 79 .md files unparseable; silent until YAML lint)
* Related: [ADR-0012](../decisions/0012-permissive-csv-enrichment-parsing.md)

## Symptom

After the first successful corpus run (79 files), running a YAML
sanity check on the generated `.md` frontmatter reported:

```
corpus/columns/A_liberty_rule_of_law/CA011.md:
  yaml error unacceptable character #x0097: special characters are not allowed
corpus/columns/B_prosperity_economic_philosophy/CB005.md:
  yaml error unacceptable character #x0083: special characters are not allowed
```

The bytes `0x97` and `0x83` are valid printable characters in CP1252
(em-dash, low-case ƒ-letter respectively) but are **undefined control
slots** in Latin-1. They surfaced as Unicode control characters
`U+0097` / `U+0083` in the output UTF-8 — which YAML rejects.

## 5 Whys

1. **Why did 0x97 and 0x83 appear as control chars in the output?**
   Because the column CSV was read with `encoding='latin-1'`, which
   maps every byte 1:1 to its same-numbered Unicode code point. Byte
   0x97 became code point U+0097 (control char).
2. **Why was Latin-1 chosen for the column CSV?** Because earlier
   attempts (`utf-8-sig`, `utf-8`, `cp1252`) all failed with
   `UnicodeDecodeError` at various positions, and Latin-1 was the
   final fallback because it accepts any byte.
3. **Why did `cp1252` fail?** Because the CSV had **at least one byte**
   (`0x9d`, at position 28993) that is in CP1252's "undefined" set.
   CP1252 has 5 undefined byte values (`0x81`, `0x8D`, `0x8F`, `0x90`,
   `0x9D`), and a single one of them raises `UnicodeDecodeError` for
   the strict decoder.
4. **Why was there a `0x9d` byte in the CSV?** The CSV was apparently
   double-encoded mojibake at some prior pipeline step — the bytes
   `c3 a2 e2 80 9d` are the UTF-8 encoding of `â€\x9d`, which is a
   CP1252 mis-decode of UTF-8 `e2 80 9d` (right-double-quote U+201D).
   So the file is CP1252 text that *contains* mojibake bytes from an
   even earlier encoding round-trip.
5. **Why was the fallback chain CP1252-strict → Latin-1 instead of
   CP1252-with-replace?** Because the original fallback chain was a
   straight `for enc in (...)` loop with `errors='strict'` everywhere,
   added in the order of "most likely correct" first. Latin-1 was the
   "always works" terminator, never reconsidered against a stronger
   intermediate option (`cp1252` with `errors='replace'`).

## Root Cause

The encoding-fallback chain treated CP1252 and Latin-1 as
strict alternatives, when the actual right choice was *CP1252 with
errors='replace'*: that mapping handles the 99% of bytes correctly
(em-dashes, smart quotes, `ñ`) and replaces only the 5 undefined slots
with `U+FFFD`. Latin-1, by contrast, *succeeds* on the undefined
slots but produces output that breaks the next consumer (YAML).

A "best fallback" choice was made on the success-criterion *"does the
decoder return without error?"* rather than *"does the output
round-trip through downstream consumers cleanly?"*

## Fix Applied

The fallback chain in `read_csv_robust()` is now:

```python
for enc in ("utf-8-sig", "utf-8", "cp1252"):  # strict
    try ...
# Final fallback:
open(path, encoding="cp1252", errors="replace")
```

The new terminal fallback (`cp1252+replace`) preserves all readable
text (em-dashes, smart quotes) and replaces only the truly unmappable
bytes with `U+FFFD`. The unrepresentable replacement character is
visible at runtime and at lint time; control chars are not produced.

After the fix, both `CA011.md` and `CB005.md` parse cleanly through
YAML.

## Generalizable Lesson

When designing an encoding-fallback chain, evaluate each candidate on
two criteria:

1. **Decoder success** — does it decode without raising?
2. **Downstream parser success** — does the output parse through every
   downstream consumer (YAML, JSON, regex, model input)?

Latin-1 is a decoder-success terminator, not a *correct* decoder for
non-Latin-1 source. A safer terminator for ambiguous Western-European
sources is `cp1252` with `errors='replace'` — that gets the
99% of high bytes right (CP1252 is what Excel saves as on Windows) and
loudly substitutes the 5 undefined slots with the replacement
character instead of silently smuggling control bytes through.

Specifically: if you find yourself writing `latin-1` as a fallback,
verify by reading 200 bytes from the file and checking that none of
them are in CP1252's undefined slots (`0x81, 0x8D, 0x8F, 0x90, 0x9D`)
*and* none are in the C1 control range (`0x80–0x9F` excluding the
printable CP1252 slots). If any are, prefer `cp1252+replace`.
