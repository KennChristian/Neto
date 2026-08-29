#!/usr/bin/env python3
"""Generate docs/axes/registry.yaml from Axis Value Records (Plan 231b, ADR-144).

Reads AVR files under docs/axes/records/, filters to status: active, dedupes by
(axis, value), emits registry.yaml with a hash header. Deterministic: same inputs
produce byte-identical output below the header.

Exit codes:
  0 success; file written or --check confirmed fresh
  1 input error (AVR dir missing / no active AVRs)
  2 drift detected in --check mode
  3 output error (cannot write)
  4 AVR parse error (missing required field, invalid YAML)
  5 duplicate (axis, value) across two active AVRs without supersession
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "error: pyyaml required. Activate grammar conda env: "
        "`conda run -n grammar python scripts/generate_axis_registry.py`\n"
    )
    sys.exit(1)

CANONICAL_AXIS_ORDER = ["stage", "depth", "layer", "concern", "persona"]
GENERATOR_TAG = "scripts/generate_axis_registry.py@v1"


def parse_frontmatter(path: Path) -> tuple[dict | None, bytes]:
    """Return (frontmatter_dict_or_None, raw_bytes). raw_bytes is LF-normalized."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    if not raw.startswith(b"---\n"):
        return None, raw
    end = raw.find(b"\n---\n", 4)
    if end == -1:
        return None, raw
    block = raw[4:end].decode("utf-8")
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML frontmatter in {path}: {e}") from e
    return (data if isinstance(data, dict) else {}), raw


def collect_avrs(avr_dir: Path) -> tuple[list[dict], list[Path], int]:
    """Scan avr_dir, return (active_avrs, ordered_paths, skipped_inactive_count)."""
    if not avr_dir.is_dir():
        raise FileNotFoundError(f"AVR dir not found: {avr_dir}")
    paths = sorted(p for p in avr_dir.glob("AVR-*.md") if p.name != "AVR-TEMPLATE.md")
    active: list[dict] = []
    skipped = 0
    for p in paths:
        try:
            fm, _raw = parse_frontmatter(p)
        except ValueError as e:
            sys.stderr.write(f"parse error: {e}\n")
            sys.exit(4)
        if not fm or fm.get("kind") != "axis-value-record":
            continue  # non-AVR file, silently skip per spec §1
        for required in ("id", "axis", "value", "status"):
            if required not in fm:
                sys.stderr.write(f"parse error: {p} missing required field '{required}'\n")
                sys.exit(4)
        if fm["status"] != "active":
            skipped += 1
            continue
        active.append({"file": p, "id": fm["id"], "axis": fm["axis"], "value": str(fm["value"])})
    return active, paths, skipped


def check_duplicates(active: list[dict]) -> None:
    seen: dict[tuple[str, str], dict] = {}
    for avr in active:
        key = (avr["axis"], avr["value"])
        if key in seen:
            other = seen[key]
            sys.stderr.write(
                f"duplicate (axis={key[0]}, value={key[1]}): "
                f"{avr['file']} and {other['file']}\n"
            )
            sys.exit(5)
        seen[key] = avr


def compute_source_sha(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        rel = str(p).encode("utf-8")
        h.update(rel)
        h.update(b"\x00")
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\x00")
    return h.hexdigest()


def build_registry_body(active: list[dict]) -> str:
    """Emit deterministic YAML content below the header."""
    by_axis: dict[str, list[dict]] = {}
    for avr in active:
        by_axis.setdefault(avr["axis"], []).append(
            {"value": avr["value"], "avr": avr["id"], "status": "active"}
        )
    # Sort within axis by value
    for axis in by_axis:
        by_axis[axis].sort(key=lambda e: e["value"])
    # Emit axes in canonical order; any additional axes appended alphabetically
    ordered_axes: dict[str, dict] = {}
    for ax in CANONICAL_AXIS_ORDER:
        if ax in by_axis:
            ordered_axes[ax] = {"values": by_axis[ax]}
    for ax in sorted(k for k in by_axis if k not in CANONICAL_AXIS_ORDER):
        ordered_axes[ax] = {"values": by_axis[ax]}
    doc = {"schema_version": 1, "axes": ordered_axes}
    # sort_keys=False preserves our canonical axis order; list items stay sorted.
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, allow_unicode=True)


def render_file(body: str, source_sha: str, timestamp: str) -> str:
    header = (
        f"# generated: {timestamp} | source-sha: {source_sha} | generator: {GENERATOR_TAG}\n"
    )
    return header + body


def strip_header(content: str) -> str:
    """Return content with the first '# generated:' line removed, for drift comparison."""
    lines = content.split("\n", 1)
    if lines and lines[0].startswith("# generated:"):
        return lines[1] if len(lines) > 1 else ""
    return content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--avr-dir", type=Path, default=Path("docs/axes/records"))
    parser.add_argument("--output", type=Path, default=Path("docs/axes/registry.yaml"))
    parser.add_argument("--check", action="store_true", help="Dry-run: exit 2 on drift")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        active, all_paths, skipped = collect_avrs(args.avr_dir)
    except FileNotFoundError as e:
        sys.stderr.write(f"input error: {e}\n")
        return 1
    if not active:
        sys.stderr.write("input error: no active AVRs found\n")
        return 1
    check_duplicates(active)

    source_sha = compute_source_sha(all_paths)
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    body = build_registry_body(active)
    new_content = render_file(body, source_sha, timestamp)

    if args.check:
        if not args.output.exists():
            sys.stderr.write(f"drift: {args.output} does not exist\n")
            return 2
        current = args.output.read_text(encoding="utf-8")
        if strip_header(current) != strip_header(new_content):
            sys.stderr.write(f"drift detected in {args.output}\n")
            return 2
        print(f"Registry fresh: {len(active)} active AVRs across {len(set(a['axis'] for a in active))} axes")
        return 0

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(new_content, encoding="utf-8")
    except OSError as e:
        sys.stderr.write(f"output error: {e}\n")
        return 3

    n_axes = len(set(a["axis"] for a in active))
    print(f"Registry generated: {len(active)} active AVRs across {n_axes} axes, {skipped} skipped (status != active)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
