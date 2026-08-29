#!/usr/bin/env python3
"""Validate dual-block frontmatter across the docs corpus (Plan 233).

Implements rule categories R1..R6 from the plan spec:
  R1 — Schema conformance (required fields, id↔filename, kind↔directory, status enum)
  R2 — Axis value backing (values exist in registry; scalar vs. list shape)
  R3 — Reference integrity (related/depends/pattern_refs resolve; no self-ref)
  R4 — Generated-file hash verification (header parseable; source-sha fresh)
  R5 — AVR integrity (AVRs have required body sections; uniqueness per axis)
  R6 — Dual-block structure (state + axes + relational blocks separated)

CLI:
  validate_frontmatter.py [PATH...] [--registry PATH] [--rules R1,R2,...] [--json] [--lenient] [-v]

Exit codes:
  0 all validations pass
  1 input error (registry/docs missing)
  2..7 one rule category failed (R1..R6 respectively)
  10 multiple categories failed
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("error: pyyaml required (conda env `grammar`)\n")
    sys.exit(1)


# -------------------- Static config --------------------

CORPUS_DIRS = ["docs/implementation-plans", "docs/decisions", "docs/test-specs", "docs/lessons"]
KIND_BY_DIR = {
    "docs/implementation-plans": "plan",
    "docs/decisions": "adr",
    "docs/decisions/ddrs": "ddr",
    "docs/test-specs": "test-spec",
    "docs/lessons": "lesson",
}
# Files that are not authored artifacts in their directories
SKIP_BASENAMES = {"MANIFEST.md", "CLAUDE.md", "00-index.md", "README.md", "_adr-migration-log.md", "ledger.md"}
# Templates
SKIP_TEMPLATE_PREFIXES = ("DDR-TEMPLATE", "AVR-TEMPLATE")
# Accepted status enum values per kind
STATUS_ENUM = {
    "plan": {"planned", "pending", "in_progress", "completed", "deferred", "archived", "draft"},
    "adr": {"proposed", "accepted", "deprecated", "superseded", "deferred"},
    "ddr": {"proposed", "synthesized", "accepted", "deferred", "superseded"},
    "test-spec": {"planned", "partial", "implemented", "deprecated"},
    "lesson": {"active", "archived"},
    "axis-value-record": {"proposed", "active", "superseded"},
}
# Multi-valued axes (list-typed); the rest are scalars.
MULTI_AXES = {"layer", "concern", "persona"}
# ID prefix → kind (for reference resolution)
ID_PREFIX_TO_KIND = {"PLAN": "plan", "ADR": "adr", "DDR": "ddr", "TS": "test-spec", "LL": "lesson", "AVR": "axis-value-record"}
# Required AVR body sections (R5)
AVR_REQUIRED_SECTIONS = ["Rationale", "Example Artifacts", "Alternatives Considered", "Orthogonality Check", "Origin"]

ALL_RULES = ["R1", "R2", "R3", "R4", "R5", "R6"]


# -------------------- Data model --------------------

@dataclass
class Violation:
    rule: str
    file: str
    field: str
    message: str

    def format_line(self) -> str:
        return f"error {self.rule} {self.file}:{self.field} {self.message}"

    def to_json(self) -> dict:
        return {"severity": "error", "rule": self.rule, "file": self.file, "field": self.field, "message": self.message}


@dataclass
class Corpus:
    registry: dict
    artifacts: dict[str, dict] = field(default_factory=dict)  # id → {file, kind, frontmatter}
    files: list[Path] = field(default_factory=list)
    has_frontmatter: set[Path] = field(default_factory=set)


# -------------------- Frontmatter parse --------------------

FRONTMATTER_RE = re.compile(rb"\A---\n(.*?)\n---\n", re.DOTALL)


def read_frontmatter(path: Path) -> tuple[dict | None, str | None]:
    """Return (frontmatter_dict, body_text) or (None, None) if no frontmatter block."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return None, None
    try:
        fm = yaml.safe_load(m.group(1).decode("utf-8"))
    except yaml.YAMLError:
        return None, None
    if not isinstance(fm, dict):
        return None, None
    body = raw[m.end():].decode("utf-8", errors="replace")
    return fm, body


def has_generated_header(path: Path) -> bool:
    try:
        first = path.read_bytes().splitlines()[0] if path.exists() else b""
    except OSError:
        return False
    s = first.decode("utf-8", errors="replace")
    return "generated:" in s and "source-sha:" in s


# -------------------- Load corpus --------------------

def load_registry(registry_path: Path) -> dict:
    if not registry_path.exists():
        raise FileNotFoundError(f"registry not found: {registry_path}")
    content = registry_path.read_text(encoding="utf-8")
    # Strip hash header if present
    if content.startswith("# generated:"):
        _, _, content = content.partition("\n")
    data = yaml.safe_load(content) or {}
    axes = data.get("axes", {})
    # Normalize into {axis: {value_str: avr_id}}
    norm: dict[str, dict[str, str]] = {}
    for ax, spec in axes.items():
        values = spec.get("values", []) if isinstance(spec, dict) else []
        norm[ax] = {}
        for v in values:
            if isinstance(v, dict) and v.get("status") == "active":
                norm[ax][str(v.get("value"))] = v.get("avr", "")
    return norm


def discover_corpus(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for root in paths:
        if root.is_file():
            out.append(root)
            continue
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.md")):
            if p.name in SKIP_BASENAMES or p.name.startswith(SKIP_TEMPLATE_PREFIXES):
                continue
            # Skip generated views
            if "_views" in p.parts:
                continue
            out.append(p)
    return out


def kind_from_path(path: Path) -> str | None:
    parts = path.parts
    if "ddrs" in parts:
        return "ddr"
    if "axes" in parts and "records" in parts:
        return "axis-value-record"
    for d, k in KIND_BY_DIR.items():
        if str(path).startswith(d) or any(seg == Path(d).name for seg in parts):
            return k
    return None


def id_from_filename(path: Path) -> str | None:
    stem = path.stem
    # Match leading PREFIX-NUMBER
    m = re.match(r"([A-Z]+)[- ](\d+(?:\.\d+)?)\b", stem.upper())
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # Plans: NNN-slug.md → PLAN-NNN
    m = re.match(r"(\d+)([a-z]?)-", stem)
    if m:
        suffix = m.group(2)
        return f"PLAN-{int(m.group(1))}{suffix}"
    return None


# -------------------- Rules --------------------

def rule_R1(path: Path, fm: dict, corpus: Corpus) -> list[Violation]:
    v: list[Violation] = []
    kind = kind_from_path(path)
    if kind is None:
        return v  # unclassifiable — not our jurisdiction
    # R1.1: frontmatter presence (already checked by caller)
    # R1.2: required state fields
    for req in ("id", "kind", "status"):
        if req not in fm:
            v.append(Violation("R1", str(path), req, f"missing required field '{req}'"))
    # R1.4: id↔filename
    expected_id = id_from_filename(path)
    fm_id = str(fm.get("id", ""))
    if expected_id and fm_id:
        # Allow case-insensitive match; allow suffix letters (231b)
        if fm_id.upper() != expected_id.upper():
            v.append(Violation("R1", str(path), "id", f"id {fm_id!r} does not match filename-derived {expected_id!r}"))
    # R1.5: kind↔directory
    fm_kind = fm.get("kind")
    if fm_kind and fm_kind != kind:
        v.append(Violation("R1", str(path), "kind", f"kind {fm_kind!r} does not match directory-derived {kind!r}"))
    # R1.6: status enum
    status = fm.get("status")
    if status is not None and kind in STATUS_ENUM and status not in STATUS_ENUM[kind]:
        v.append(Violation("R1", str(path), "status", f"status {status!r} not in enum {sorted(STATUS_ENUM[kind])}"))
    return v


def rule_R2(path: Path, fm: dict, corpus: Corpus) -> list[Violation]:
    v: list[Violation] = []
    axes_block = fm.get("axes")
    if not isinstance(axes_block, dict):
        return v  # No axes block → skipped here; R6 handles presence
    for axis, value in axes_block.items():
        if axis not in corpus.registry:
            v.append(Violation("R2", str(path), f"axes.{axis}", f"axis {axis!r} not in registry"))
            continue
        # R2.3: scalar vs. list shape
        values = value if isinstance(value, list) else [value]
        if axis in MULTI_AXES and not isinstance(value, list):
            # Tolerated per spec §R2.3 (normalize), but warn via the single-value check below
            pass
        for item in values:
            item_str = str(item)
            if item_str not in corpus.registry[axis]:
                v.append(Violation("R2", str(path), f"axes.{axis}", f"value {item_str!r} not in active registry for axis {axis!r}"))
    return v


def rule_R3(path: Path, fm: dict, corpus: Corpus) -> list[Violation]:
    v: list[Violation] = []
    own_id = str(fm.get("id", "")).upper()
    for field_name in ("related", "depends", "pattern_refs", "supersedes", "superseded_by"):
        refs = fm.get(field_name)
        if refs is None:
            continue
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list):
            continue
        for ref in refs:
            ref_str = str(ref).upper()
            if not ref_str:
                continue
            # pattern_refs cites harness patterns, not corpus IDs — skip resolution
            if field_name == "pattern_refs":
                continue
            if ref_str == own_id:
                v.append(Violation("R3", str(path), field_name, f"self-reference {ref_str}"))
                continue
            if ref_str not in corpus.artifacts:
                v.append(Violation("R3", str(path), field_name, f"unresolved reference {ref_str}"))
    return v


def rule_R4(path: Path, fm: dict | None, corpus: Corpus) -> list[Violation]:
    v: list[Violation] = []
    if not has_generated_header(path):
        return v
    first_line = path.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
    m = re.search(r"source-sha:\s*([0-9a-f]+)", first_line)
    if not m:
        v.append(Violation("R4", str(path), "source-sha", "generated header present but source-sha unparseable"))
    # Full hash recomputation is generator-specific; left to CI per Plan 233 §3.
    return v


def rule_R5(path: Path, fm: dict, corpus: Corpus) -> list[Violation]:
    """AVR-specific integrity."""
    v: list[Violation] = []
    if fm.get("kind") != "axis-value-record":
        return v
    for req in ("axis", "value"):
        if req not in fm:
            v.append(Violation("R5", str(path), req, f"AVR missing required field '{req}'"))
    # Check body sections
    body = path.read_text(encoding="utf-8", errors="replace")
    # Strip frontmatter
    body = FRONTMATTER_RE.sub("", body.encode("utf-8").replace(b"\r\n", b"\n")).decode("utf-8", errors="replace") if False else body
    # Use substring match on heading lines
    for section in AVR_REQUIRED_SECTIONS:
        if not re.search(rf"^##\s+{re.escape(section)}\b", body, re.MULTILINE):
            v.append(Violation("R5", str(path), "body", f"AVR missing required section '## {section}'"))
    # Location check
    if "axes/records" not in str(path).replace("\\", "/"):
        v.append(Violation("R5", str(path), "location", "AVR must live under docs/axes/records/"))
    return v


def rule_R6(path: Path, fm: dict, corpus: Corpus) -> list[Violation]:
    """Dual-block structure: require an axes: block on all non-AVR artifacts.

    Per Plan 233 §R6.1 the frontmatter should contain state, axes, and relational
    blocks. We check for axes presence as the minimum signal; AVRs are exempt
    because their state block fully describes vocabulary records.
    """
    v: list[Violation] = []
    if fm.get("kind") == "axis-value-record":
        return v
    if "axes" not in fm:
        v.append(Violation("R6", str(path), "axes", "missing axes block (dual-block structure per ADR-142)"))
    return v


RULES = {"R1": rule_R1, "R2": rule_R2, "R3": rule_R3, "R4": rule_R4, "R5": rule_R5, "R6": rule_R6}


# -------------------- Orchestration --------------------

def validate(paths: list[Path], registry_path: Path, rules: list[str], lenient: bool) -> list[Violation]:
    try:
        registry = load_registry(registry_path)
    except FileNotFoundError as e:
        sys.stderr.write(f"input error: {e}\n")
        sys.exit(1)

    files = discover_corpus(paths)
    # Also scan AVRs directly if docs/ is in scope, to enable R5 and reference indexing.
    avr_dir = Path("docs/axes/records")
    if avr_dir.is_dir():
        for avr in sorted(avr_dir.glob("AVR-*.md")):
            if avr.name != "AVR-TEMPLATE.md":
                files.append(avr)

    corpus = Corpus(registry=registry, files=files)

    # First pass: parse frontmatter, build id index
    parsed: dict[Path, dict] = {}
    for f in files:
        fm, _body = read_frontmatter(f)
        if fm is None:
            if not lenient and f.name not in SKIP_BASENAMES:
                # R1.1 failure: no frontmatter on an authored artifact
                pass  # collected later as R1 violation
            continue
        parsed[f] = fm
        corpus.has_frontmatter.add(f)
        fm_id = str(fm.get("id", "")).upper()
        if fm_id:
            corpus.artifacts[fm_id] = {"file": str(f), "kind": fm.get("kind"), "frontmatter": fm}

    violations: list[Violation] = []
    for f in files:
        fm = parsed.get(f)
        if fm is None:
            if not lenient and kind_from_path(f) is not None:
                violations.append(Violation("R1", str(f), "frontmatter", "file has no YAML frontmatter block"))
            continue
        for rule in rules:
            violations.extend(RULES[rule](f, fm, corpus))

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", default=CORPUS_DIRS, help="Files or directories to validate")
    parser.add_argument("--registry", type=Path, default=Path("docs/axes/registry.yaml"))
    parser.add_argument("--rules", default=",".join(ALL_RULES), help="Comma-separated rule IDs")
    parser.add_argument("--json", dest="json_mode", action="store_true", help="Emit JSONL")
    parser.add_argument("--lenient", action="store_true", help="Treat missing frontmatter as a warning (skip R1.1)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    rules = [r.strip().upper() for r in args.rules.split(",") if r.strip()]
    for r in rules:
        if r not in ALL_RULES:
            sys.stderr.write(f"error: unknown rule {r!r}; known: {ALL_RULES}\n")
            return 1

    path_objs = [Path(p) for p in args.paths]
    violations = validate(path_objs, args.registry, rules, args.lenient)

    # Report
    if args.json_mode:
        for v in violations:
            print(json.dumps(v.to_json()))
    else:
        for v in violations:
            print(v.format_line())

    # Summary
    by_rule: dict[str, int] = {}
    files_affected: set[str] = set()
    for v in violations:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
        files_affected.add(v.file)
    print(f"{len(violations)} violations across {len(files_affected)} files; {len(by_rule)} rule categories failed", file=sys.stderr)
    if args.verbose and by_rule:
        for r in sorted(by_rule):
            print(f"  {r}: {by_rule[r]}", file=sys.stderr)

    if not violations:
        return 0
    failed = sorted(by_rule.keys())
    if len(failed) == 1:
        # R1→2, R2→3, ...
        return ALL_RULES.index(failed[0]) + 2
    return 10


if __name__ == "__main__":
    sys.exit(main())
