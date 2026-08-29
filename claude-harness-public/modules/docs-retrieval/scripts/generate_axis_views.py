#!/usr/bin/env python3
"""Generate per-axis view files + regenerate MANIFESTs from corpus frontmatter (Plan 232).

Reads docs/axes/registry.yaml and every .md with dual-block frontmatter under
docs/{implementation-plans,decisions,test-specs,lessons}. Emits:
  docs/_views/by-<axis>/<value>.md            per-axis lists with Related-axes column
  docs/_views/intersections/<A>-<B>.md         top-10 populated pairs (stub-empty if <10)
  docs/_views/graph/reference-graph.md         adjacency list of ID references
  docs/_views/recent.md                        30 most-recent by last_touched
  docs/implementation-plans/MANIFEST.md        regenerated with File | Purpose schema
  docs/decisions/MANIFEST.md                   regenerated (ADR + DDR sections)
  docs/test-specs/MANIFEST.md                  regenerated
  docs/lessons/MANIFEST.md                     regenerated
  docs/implementation-plans/00-index.md        regenerated from plan frontmatter

Every generated file carries a hash header. Deterministic: same inputs produce
byte-identical bodies. See Plan 232 §3.

Exit codes:
  0 success / --check fresh
  1 input error
  2 drift in --check mode
  3 output error
  4 frontmatter parse error in an input file
  5 axis value used in frontmatter not in registry
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("error: pyyaml required (conda env `grammar`)\n")
    sys.exit(1)

CANONICAL_AXIS_ORDER = ["stage", "depth", "layer", "concern", "persona"]
GENERATOR_TAG = "scripts/generate_axis_views.py@v1"
CORPUS_DIRS = {
    "plan": "docs/implementation-plans",
    "adr": "docs/decisions",
    "test-spec": "docs/test-specs",
    "lesson": "docs/lessons",
}
SKIP_BASENAMES = {"MANIFEST.md", "CLAUDE.md", "00-index.md", "README.md", "_adr-migration-log.md", "ledger.md"}
FRONTMATTER_RE = re.compile(rb"\A---\n(.*?)\n---\n", re.DOTALL)
REF_PATTERNS = re.compile(r"\b(PLAN|ADR|DDR|TS|LL|AVR)-\d+[a-z]?\b")


@dataclass
class Artifact:
    path: Path
    id: str
    kind: str
    title: str
    status: str
    description: str
    axes: dict[str, list[str]]
    depends: list[str] = field(default_factory=list)
    last_touched: str = ""
    body: str = ""


# -------------------- Parsing --------------------

def read_frontmatter(path: Path) -> tuple[dict | None, str]:
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return None, raw.decode("utf-8", errors="replace")
    try:
        fm = yaml.safe_load(m.group(1).decode("utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML in {path}: {e}") from e
    body = raw[m.end():].decode("utf-8", errors="replace")
    return (fm if isinstance(fm, dict) else {}), body


def extract_title(path: Path, body: str, fm: dict) -> str:
    if fm.get("description"):
        return str(fm["description"])
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


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


def id_from_filename(path: Path, kind: str) -> str:
    stem = path.stem
    m = re.match(r"([A-Z]+)-?(\d+[a-z]?)", stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(\d+)([a-z]?)-", stem)
    if m:
        return f"PLAN-{int(m.group(1))}{m.group(2)}"
    return stem.upper()


def collect_artifacts(docs_root: Path, registry: dict[str, set[str]]) -> list[Artifact]:
    """Load every .md with an id-bearing name under the 4 corpus dirs.

    Artifacts without frontmatter are included with empty axes so MANIFEST
    regeneration stays lossless for unbackfilled content. Per-axis views only
    include artifacts whose frontmatter carries an `axes` block.
    """
    arts: list[Artifact] = []
    for kind, rel in CORPUS_DIRS.items():
        d = docs_root / Path(rel).relative_to("docs")
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            if f.name in SKIP_BASENAMES:
                continue
            if "_views" in f.parts or f.name.startswith(("DDR-TEMPLATE", "AVR-TEMPLATE")):
                continue
            try:
                fm, body = read_frontmatter(f)
            except ValueError as e:
                sys.stderr.write(f"parse error: {e}\n")
                sys.exit(4)
            if fm is None:
                fm = {}
                body = f.read_text(encoding="utf-8", errors="replace")
            axes_block = fm.get("axes") if isinstance(fm.get("axes"), dict) else {}
            axes_norm: dict[str, list[str]] = {}
            for ax, val in (axes_block or {}).items():
                vals = val if isinstance(val, list) else [val]
                vals = [str(v) for v in vals]
                if ax in registry:
                    for v in vals:
                        if v not in registry[ax]:
                            sys.stderr.write(
                                f"axis value not in registry: {f}: axes.{ax}={v}\n"
                            )
                            sys.exit(5)
                axes_norm[ax] = vals
            art_id = str(fm.get("id") or id_from_filename(f, kind))
            art = Artifact(
                path=f,
                id=art_id,
                kind=str(fm.get("kind", kind)),
                title=extract_title(f, body, fm),
                status=str(fm.get("status", "")),
                description=str(fm.get("description", "")),
                axes=axes_norm,
                depends=[str(x) for x in (fm.get("depends") or [])],
                last_touched=str(fm.get("last_touched") or fm.get("created") or ""),
                body=body,
            )
            arts.append(art)
    return sorted(arts, key=lambda a: a.id)


# -------------------- Hashing --------------------

def compute_source_sha(registry_path: Path, artifacts: list[Artifact]) -> str:
    h = hashlib.sha256()
    h.update(registry_path.read_bytes().replace(b"\r\n", b"\n"))
    h.update(b"\x00")
    for a in sorted(artifacts, key=lambda x: str(x.path)):
        h.update(str(a.path).encode("utf-8"))
        h.update(b"\x00")
        fm_bytes = a.path.read_bytes().replace(b"\r\n", b"\n")
        m = FRONTMATTER_RE.match(fm_bytes)
        if m:
            h.update(m.group(0))
        h.update(b"\x00")
    return h.hexdigest()


def header(source_sha: str, timestamp: str) -> str:
    return f"<!-- generated: {timestamp} | source-sha: {source_sha} | generator: {GENERATOR_TAG} -->\n"


def strip_header(content: str) -> str:
    lines = content.split("\n", 1)
    if lines and lines[0].startswith("<!-- generated:"):
        return lines[1] if len(lines) > 1 else ""
    return content


# -------------------- View rendering --------------------

def fmt_related_axes(a: Artifact, omit_axis: str) -> str:
    parts: list[str] = []
    for ax in CANONICAL_AXIS_ORDER:
        if ax == omit_axis or ax not in a.axes:
            continue
        vals = a.axes[ax]
        if len(vals) == 1:
            parts.append(f"{ax}={vals[0]}")
        else:
            parts.append(f"{ax}=[{', '.join(vals)}]")
    return ", ".join(parts) if parts else "—"


def render_axis_view(axis: str, value: str, arts: list[Artifact]) -> str:
    lines = [f"# {axis} = {value}", ""]
    lines.append(f"Artifacts tagged with `axes.{axis}` containing `{value}`, sorted by id.")
    lines.append("")
    if not arts:
        lines.append("_No artifacts currently tagged._")
        return "\n".join(lines) + "\n"
    lines.append("| ID | Title | Status | Related axes |")
    lines.append("|----|-------|--------|--------------|")
    for a in sorted(arts, key=lambda x: x.id):
        title = a.title.replace("|", "\\|")
        lines.append(f"| {a.id} | {title} | {a.status} | {fmt_related_axes(a, axis)} |")
    return "\n".join(lines) + "\n"


def render_intersection_view(value_a: str, value_b: str, arts: list[Artifact]) -> str:
    lines = [f"# Intersection: `{value_a}` ∩ `{value_b}`", ""]
    lines.append(f"Artifacts appearing in BOTH axis-value sets.")
    lines.append("")
    if not arts:
        lines.append("_No artifacts match this intersection._")
        return "\n".join(lines) + "\n"
    lines.append("| ID | Title | Status |")
    lines.append("|----|-------|--------|")
    for a in sorted(arts, key=lambda x: x.id):
        title = a.title.replace("|", "\\|")
        lines.append(f"| {a.id} | {title} | {a.status} |")
    return "\n".join(lines) + "\n"


def render_reference_graph(artifacts: list[Artifact]) -> str:
    lines = ["# Reference Graph", ""]
    lines.append("Adjacency list of ID references (`ADR-N`, `PLAN-N`, `TS-N`, `LL-N`, `DDR-N`, `AVR-N`) harvested from artifact bodies.")
    lines.append("")
    for a in sorted(artifacts, key=lambda x: x.id):
        refs = sorted(set(m.group(0) for m in REF_PATTERNS.finditer(a.body)) - {a.id})
        if not refs:
            continue
        lines.append(f"- **{a.id}** → {', '.join(refs)}")
    return "\n".join(lines) + "\n"


def render_recent(artifacts: list[Artifact]) -> str:
    lines = ["# Recent Artifacts (top 30)", "", "Sorted by `last_touched` descending.", ""]
    recent = sorted(
        [a for a in artifacts if a.last_touched],
        key=lambda x: x.last_touched,
        reverse=True,
    )[:30]
    if not recent:
        lines.append("_No artifacts carry `last_touched` yet._")
        return "\n".join(lines) + "\n"
    lines.append("| ID | Title | Last touched | Axes |")
    lines.append("|----|-------|--------------|------|")
    for a in recent:
        title = a.title.replace("|", "\\|")
        axes_str = fmt_related_axes(a, "")
        lines.append(f"| {a.id} | {title} | {a.last_touched} | {axes_str} |")
    return "\n".join(lines) + "\n"


# -------------------- MANIFEST regeneration --------------------

MANIFEST_HEADERS = {
    "docs/implementation-plans": "# implementation-plans/ MANIFEST\n\nStatus tracking and dependency graph: `00-index.md`\n",
    "docs/decisions": "# decisions/ MANIFEST\n\nMADR 4.0 format. Each ADR: Context, Decision Drivers, Considered Options, Decision Outcome, Consequences.\n",
    "docs/test-specs": "# test-specs/ MANIFEST\n\nModel-based test specs governed by dual-block frontmatter; `status` lives per-artifact.\n",
    "docs/lessons": "# lessons/ MANIFEST\n\nLessons learned from pipeline execution and design reviews.\n",
}


def render_manifest(dir_rel: str, artifacts: list[Artifact]) -> str:
    lines = [MANIFEST_HEADERS[dir_rel], "", "| File | Purpose |", "|------|---------|"]
    dir_arts = sorted(
        [a for a in artifacts if str(a.path).startswith(dir_rel)],
        key=lambda a: a.path.name,
    )
    for a in dir_arts:
        purpose = a.description or a.title
        purpose = purpose.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{a.path.name}` | {purpose} |")
    return "\n".join(lines) + "\n"


def render_00_index(plans: list[Artifact]) -> str:
    lines = [
        "# Implementation Plans — Index",
        "",
        "> Generated from per-plan frontmatter (ADR-142, ADR-143). Hand-edits rejected.",
        "",
        "| # | Plan | Status | Scope | Depends On |",
        "|---|------|--------|-------|------------|",
    ]
    for a in sorted(plans, key=lambda x: x.id):
        scope = (a.description or a.title).replace("|", "\\|").replace("\n", " ")
        deps = ", ".join(a.depends) if a.depends else "—"
        plan_num = a.id.replace("PLAN-", "").replace("plan-", "")
        lines.append(f"| {plan_num} | [{a.id}]({a.path.name}) | {a.status} | {scope} | {deps} |")
    return "\n".join(lines) + "\n"


# -------------------- Orchestration --------------------

def write_if_changed(path: Path, new_content: str, check: bool, drift_count: list[int]) -> None:
    if check:
        if not path.exists():
            sys.stderr.write(f"drift: {path} does not exist\n")
            drift_count[0] += 1
            return
        cur = path.read_text(encoding="utf-8")
        if strip_header(cur) != strip_header(new_content):
            sys.stderr.write(f"drift: {path}\n")
            drift_count[0] += 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")


def top_intersections(artifacts: list[Artifact], n: int = 10) -> list[tuple[tuple[str, str, str, str], list[Artifact]]]:
    """Return top-N populated (axis_a, value_a, axis_b, value_b) pairs."""
    buckets: dict[tuple[str, str, str, str], list[Artifact]] = {}
    for a in artifacts:
        flat: list[tuple[str, str]] = []
        for ax in CANONICAL_AXIS_ORDER:
            for v in a.axes.get(ax, []):
                flat.append((ax, v))
        for i in range(len(flat)):
            for j in range(i + 1, len(flat)):
                (ax1, v1), (ax2, v2) = flat[i], flat[j]
                if ax1 == ax2:
                    continue
                key = (ax1, v1, ax2, v2) if (ax1, v1) < (ax2, v2) else (ax2, v2, ax1, v1)
                buckets.setdefault(key, []).append(a)
    scored = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return scored[:n]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", type=Path, default=Path("docs/axes/registry.yaml"))
    parser.add_argument("--docs-root", type=Path, default=Path("docs"))
    parser.add_argument("--output", type=Path, default=Path("docs/_views"))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.registry.exists():
        sys.stderr.write(f"input error: registry not found: {args.registry}\n")
        return 1
    if not args.docs_root.is_dir():
        sys.stderr.write(f"input error: docs root not found: {args.docs_root}\n")
        return 1

    registry = load_registry(args.registry)
    artifacts = collect_artifacts(args.docs_root, registry)
    if args.verbose:
        print(f"Loaded {len(artifacts)} artifacts with frontmatter", file=sys.stderr)

    source_sha = compute_source_sha(args.registry, artifacts)
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    hdr = header(source_sha, timestamp)
    drift = [0]

    # Per-axis views
    for axis, values in registry.items():
        for value in sorted(values):
            matching = [a for a in artifacts if value in a.axes.get(axis, [])]
            content = hdr + render_axis_view(axis, value, matching)
            out = args.output / f"by-{axis}" / f"{value}.md"
            write_if_changed(out, content, args.check, drift)

    # Intersection views (top-10)
    for (ax1, v1, ax2, v2), arts in top_intersections(artifacts, n=10):
        matching = [a for a in arts]
        content = hdr + render_intersection_view(f"{ax1}={v1}", f"{ax2}={v2}", matching)
        out = args.output / "intersections" / f"{v1}-{v2}.md"
        write_if_changed(out, content, args.check, drift)

    # Reference graph
    write_if_changed(args.output / "graph" / "reference-graph.md", hdr + render_reference_graph(artifacts), args.check, drift)

    # Recent
    write_if_changed(args.output / "recent.md", hdr + render_recent(artifacts), args.check, drift)

    # Regenerate MANIFESTs
    for rel in MANIFEST_HEADERS:
        manifest_content = hdr + render_manifest(rel, artifacts)
        out = Path(rel) / "MANIFEST.md"
        write_if_changed(out, manifest_content, args.check, drift)

    # Regenerate 00-index.md
    plans = [a for a in artifacts if str(a.path).startswith("docs/implementation-plans")]
    index_content = hdr + render_00_index(plans)
    write_if_changed(Path("docs/implementation-plans/00-index.md"), index_content, args.check, drift)

    if args.check:
        if drift[0]:
            return 2
        print(f"Views fresh: {len(artifacts)} artifacts, {len(registry)} axes")
        return 0

    n_views = sum(len(v) for v in registry.values())
    print(f"Views generated: {n_views} per-axis, top-10 intersections, graph, recent, {len(MANIFEST_HEADERS)} MANIFESTs, 00-index.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
