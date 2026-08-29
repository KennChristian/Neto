#!/usr/bin/env python3
"""TF-IDF axis-value proposer for frontmatter backfill (Plan 235).

For every artifact lacking an `axes:` frontmatter block, propose candidate
axis values via TF-IDF term extraction + alias-table mapping against the
generated registry. Emits proposals YAML for human review (LL-068: bootstrap
must not auto-apply; this script NEVER writes to source files).

Inputs:
  docs/axes/registry.yaml  — generated (Plan 231b)
  docs/axes/aliases.yaml   — hand-authored synonym table (Plan 235)
  docs/{plans,decisions,test-specs,lessons}/*.md

Output:
  YAML file at --output (default: /tmp/axis-proposals.yaml)

CLI:
  propose_axis_seeds.py [--docs-root PATH] [--registry PATH] [--aliases PATH]
                       [--output PATH] [--min-confidence FLOAT]

Constraints (ADR-145): single-file, stdlib + pyyaml, no source mutation.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("error: pyyaml required (conda env `grammar`)\n")
    sys.exit(1)

CORPUS_DIRS = ["docs/implementation-plans", "docs/decisions", "docs/test-specs", "docs/lessons"]
SKIP_BASENAMES = {"MANIFEST.md", "CLAUDE.md", "00-index.md", "README.md", "ledger.md", "_adr-migration-log.md"}
FRONTMATTER_RE = re.compile(rb"\A---\n(.*?)\n---\n", re.DOTALL)
WORD_RE = re.compile(r"[a-z][a-z\-]{2,}")
STOPWORDS = set("""
the a an and or but for nor so yet if then else when while because since as
of in on at by to from into with without within over under through
is are was were be been being am been do does did done having have has had
this that these those it its they them their there here what which who whom
not no yes only own very same than too more most less many few some any all
each every other another such no not one two three four five six seven eight
nine ten plan plans adr adrs ll ts see also note notes used using use uses
may might can could should would will shall must per via etc eg ie e g i e
based new old full first last next prev each every above below across
within without during before after until during since against between among
""".split())


# -------------------- Load support --------------------

def read_frontmatter(path: Path) -> tuple[dict | None, str]:
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return None, raw.decode("utf-8", errors="replace")
    try:
        fm = yaml.safe_load(m.group(1).decode("utf-8")) or {}
    except yaml.YAMLError:
        return None, raw.decode("utf-8", errors="replace")
    body = raw[m.end():].decode("utf-8", errors="replace")
    return (fm if isinstance(fm, dict) else {}), body


def load_registry(path: Path) -> dict[str, set[str]]:
    content = path.read_text(encoding="utf-8")
    if content.startswith("# generated:"):
        _, _, content = content.partition("\n")
    data = yaml.safe_load(content) or {}
    out: dict[str, set[str]] = {}
    for ax, spec in (data.get("axes") or {}).items():
        out[ax] = set()
        for v in (spec.get("values") or []):
            if isinstance(v, dict) and v.get("status") == "active":
                out[ax].add(str(v.get("value")))
    return out


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k).lower(): str(v) for k, v in (data.get("aliases") or {}).items()}


# -------------------- Text processing --------------------

CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
YAML_FENCE = re.compile(r"```yaml.*?```", re.DOTALL)


def tokenize(body: str) -> list[str]:
    body = CODE_FENCE.sub(" ", body)
    body = body.lower()
    words = WORD_RE.findall(body)
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def compute_tfidf(docs: dict[Path, list[str]]) -> dict[Path, list[tuple[str, float]]]:
    """Return top terms by TF-IDF for each doc."""
    doc_freq: Counter = Counter()
    doc_tokens: dict[Path, Counter] = {}
    for p, toks in docs.items():
        tf = Counter(toks)
        doc_tokens[p] = tf
        for w in tf.keys():
            doc_freq[w] += 1
    n = len(docs)
    result: dict[Path, list[tuple[str, float]]] = {}
    for p, tf in doc_tokens.items():
        if not tf:
            result[p] = []
            continue
        total = sum(tf.values())
        scores: list[tuple[str, float]] = []
        for w, c in tf.items():
            idf = math.log((n + 1) / (1 + doc_freq[w])) + 1.0
            scores.append((w, (c / total) * idf))
        scores.sort(key=lambda x: (-x[1], x[0]))
        result[p] = scores[:10]
    return result


# -------------------- Proposal --------------------

KIND_TO_LAYER = {
    "plan": "none",
    "adr": "none",
    "test-spec": "test",
    "lesson": "none",
}


def kind_from_path(path: Path) -> str:
    s = str(path)
    if "implementation-plans" in s:
        return "plan"
    if "decisions/ddrs" in s:
        return "ddr"
    if "decisions" in s:
        return "adr"
    if "test-specs" in s:
        return "test-spec"
    if "lessons" in s:
        return "lesson"
    return "unknown"


def propose_for_artifact(
    path: Path,
    top_terms: list[tuple[str, float]],
    registry: dict[str, set[str]],
    aliases: dict[str, str],
) -> dict:
    kind = kind_from_path(path)
    proposed: dict[str, list[str] | str] = {}
    review: list[str] = []
    term_strs = [t for t, _s in top_terms]

    # stage: default from "completed"/"planned"/"deferred" signals in filename/body
    proposed["stage"] = "active"
    review.append("stage")

    # depth: heuristic by kind
    depth_map = {"plan": "D2", "adr": "D3", "test-spec": "D2", "lesson": "D1", "ddr": "D2"}
    proposed["depth"] = depth_map.get(kind, "D2")
    review.append("depth")

    # layer: match terms against registered layer values (exact + alias)
    layers: list[str] = []
    layer_vocab = registry.get("layer", set())
    for term in term_strs:
        mapped = aliases.get(term, term)
        if mapped in layer_vocab and mapped not in layers:
            layers.append(mapped)
    if not layers:
        layers = [KIND_TO_LAYER.get(kind, "none")]
        review.append("layer")
    proposed["layer"] = layers

    # concern: match top terms against concern vocabulary
    concerns: list[str] = []
    concern_vocab = registry.get("concern", set())
    for term in term_strs:
        mapped = aliases.get(term, term)
        if mapped in concern_vocab and mapped not in concerns:
            concerns.append(mapped)
        if len(concerns) >= 3:
            break
    if not concerns:
        review.append("concern")
    proposed["concern"] = concerns

    # persona: from kind heuristic
    persona_map = {
        "plan": ["architect"],
        "adr": ["architect"],
        "test-spec": ["qa"],
        "lesson": ["architect"],
        "ddr": ["designer"],
    }
    proposed["persona"] = persona_map.get(kind, ["architect"])
    review.append("persona")

    # Confidence: 0.95 if exact-match axes, 0.6 if heuristic, 0.4 if nothing
    confidence = 0.95 if layers and concerns else (0.6 if layers or concerns else 0.4)

    return {
        "file": str(path),
        "kind": kind,
        "proposed_axes": proposed,
        "top_terms": term_strs,
        "confidence": confidence,
        "review_needed": review,
    }


# -------------------- Orchestration --------------------

def discover(docs_root: Path) -> list[Path]:
    out: list[Path] = []
    for rel in CORPUS_DIRS:
        d = docs_root / Path(rel).relative_to("docs")
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.md")):
            if p.name in SKIP_BASENAMES:
                continue
            if p.name.startswith(("DDR-TEMPLATE", "AVR-TEMPLATE")):
                continue
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs-root", type=Path, default=Path("docs"))
    parser.add_argument("--registry", type=Path, default=Path("docs/axes/registry.yaml"))
    parser.add_argument("--aliases", type=Path, default=Path("docs/axes/aliases.yaml"))
    parser.add_argument("--output", type=Path, default=Path("/tmp/axis-proposals.yaml"))
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.registry.exists():
        sys.stderr.write(f"input error: registry not found: {args.registry}\n")
        return 1
    registry = load_registry(args.registry)
    aliases = load_aliases(args.aliases)

    files = discover(args.docs_root)
    # Tokenize all docs so TF-IDF has the full corpus; filter to un-tagged for proposals
    docs: dict[Path, list[str]] = {}
    needs_proposal: list[Path] = []
    for f in files:
        fm, body = read_frontmatter(f)
        docs[f] = tokenize(body or "")
        if fm is None or not isinstance(fm.get("axes"), dict):
            needs_proposal.append(f)

    if args.verbose:
        print(f"{len(files)} files scanned; {len(needs_proposal)} lack axes block", file=sys.stderr)

    tfidf = compute_tfidf(docs)
    proposals: list[dict] = []
    for f in needs_proposal:
        p = propose_for_artifact(f, tfidf.get(f, []), registry, aliases)
        if p["confidence"] >= args.min_confidence:
            proposals.append(p)

    out = {
        "proposals_version": 1,
        "generated_by": "scripts/propose_axis_seeds.py",
        "registry_source": str(args.registry),
        "total_files": len(files),
        "needs_backfill": len(needs_proposal),
        "returned": len(proposals),
        "review_required": True,
        "review_instructions": (
            "LL-068: bootstrap must not auto-apply. Every proposal requires "
            "human review before writing frontmatter. Confidence scores are "
            "term-match strength, NOT semantic-to-intent match strength."
        ),
        "proposals": proposals,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(out, sort_keys=False, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {len(proposals)} proposals to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
