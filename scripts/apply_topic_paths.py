"""
Backfill `topic_paths` in the 79 generated .json files using the curated
taxonomy from build_topic_map.py.

Reads each .json under corpus/{columns,speeches,biography}/, computes
primary / secondary topic ids by scoring the doc against the taxonomy,
and writes the result back in place (idempotent).

Run after build_topic_map.py whenever the taxonomy changes.
"""

from __future__ import annotations

import json
from pathlib import Path

from build_topic_map import (  # type: ignore[import-not-found]
    CORPUS_ROOT,
    TAXONOMY,
    _doc_haystack,
    derive_topic_paths,
    score_topic,
)


def main() -> int:
    paths = sorted(
        list(CORPUS_ROOT.glob("columns/**/*.json"))
        + list(CORPUS_ROOT.glob("speeches/**/*.json"))
        + list(CORPUS_ROOT.glob("biography/**/*.json"))
    )
    # First pass: score every doc.
    doc_scores: dict[str, dict[str, int]] = {}
    docs: list[tuple[Path, dict]] = []
    for p in paths:
        doc = json.loads(p.read_text(encoding="utf-8"))
        docs.append((p, doc))
        hs = _doc_haystack(doc)
        doc_scores[doc["id"]] = {t["id"]: score_topic(t, hs) for t in TAXONOMY}
    # Second pass: write topic_paths back.
    updated = 0
    empty_primary = 0
    for p, doc in docs:
        tp = derive_topic_paths(doc["id"], doc_scores)
        if doc.get("topic_paths") != tp:
            doc["topic_paths"] = tp
            p.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            updated += 1
        if not tp["primary"]:
            empty_primary += 1
            print(f"  [warn] no primary topic for {doc['id']}")
    print(f"[apply] {updated} files updated of {len(docs)}; "
          f"{empty_primary} with empty primary path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
