"""
Run the TS-006 smoke test: 25 in-corpus questions (5 per theme) + 5
adversarial probes. Captures gate/routing/response/fidelity/latency/
cost per question and writes:

  reports/smoke_test_run.json     (one row per question)
  reports/smoke_test_summary.json (aggregate metrics)

Exit code: 0 green / 1 yellow / 2 red — per TS-006 §2.

Usage:
    app/.venv/Scripts/python.exe scripts/run_smoke_test.py
    app/.venv/Scripts/python.exe scripts/run_smoke_test.py --limit 5
    app/.venv/Scripts/python.exe scripts/run_smoke_test.py --filter A1,A2,M1

Requires ANTHROPIC_API_KEY in env or in app/.env.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

QUESTIONS_PATH = (
    PROJECT_ROOT / "docs" / "test-specs" / "TS-006-smoke-test-questions.json"
)
REPORTS_DIR = PROJECT_ROOT / "reports"

# Pricing — per Anthropic late-2025 rates ($/MTok)
PRICES = {
    "router":    (1.00, 1.25, 0.10, 5.00),    # Haiku 4.5 (input, write, read, output)
    "inference": (3.00, 3.75, 0.30, 15.00),   # Sonnet 4.6
}


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _primary_routing_pass(actual: str, expected: list[str] | None) -> bool:
    """A routing passes if expected is None (we don't pin one), or if the
    actual primary id is in the expected set."""
    if expected is None:
        return True
    return actual in expected


def _estimate_cost(cache_stats_snapshot: dict) -> float:
    """Cost since the snapshot. Caller diffs before/after."""
    cost = 0.0
    for label, s in cache_stats_snapshot.items():
        p_in, p_w, p_r, p_out = PRICES[label]
        cost += (
            s["regular_input"] * p_in
            + s["creation"] * p_w
            + s["read"] * p_r
            + s["output"] * p_out
        ) / 1e6
    return cost


def _snapshot_cache_stats(CACHE_STATS: dict) -> dict:
    return {
        label: {k: v for k, v in s.items()}
        for label, s in CACHE_STATS.items()
    }


def _diff_cache_stats(before: dict, after: dict) -> dict:
    return {
        label: {k: after[label][k] - before[label][k] for k in before[label]}
        for label in before
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only the first N questions")
    parser.add_argument("--filter", type=str, default=None,
                        help="Comma-separated question ids to run")
    parser.add_argument(
        "--out", type=str, default=None,
        help="Override output report path prefix (default: reports/smoke_test_*)",
    )
    args = parser.parse_args()

    # Lazy import so module-level Anthropic import doesn't break --help
    import cj_chat  # noqa: F401
    from cj_chat import (
        CACHE_STATS, make_client, CorpusArtifacts,
        input_gate, route_question, force_meta_routing,
        build_context, generate_response_with_fidelity, _approx_tokens,
    )

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    if args.filter:
        wanted = {q.strip() for q in args.filter.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    print(f"[smoke] Loading artifacts...")
    artifacts = CorpusArtifacts()
    client = make_client()
    print(f"[smoke] Running {len(questions)} questions...")

    rows: list[dict] = []
    for i, q in enumerate(questions, 1):
        qid = q["id"]
        print(f"\n[{i:>2}/{len(questions)}] {qid}: {q['question']}")
        before = _snapshot_cache_stats(CACHE_STATS)
        t0 = time.time()

        try:
            gate = input_gate(client, q["question"])
            if gate["scope"] == "identity_probe":
                routing = force_meta_routing(gate["reasoning"])
            else:
                routing = route_question(client, q["question"], artifacts)
            context = build_context(routing, artifacts)
            response, fidelity = generate_response_with_fidelity(
                client, q["question"], routing, artifacts,
                conversation_history=None,
            )
        except Exception as e:
            print(f"   ✗ ERROR: {type(e).__name__}: {e}")
            rows.append({
                "question_id": qid,
                "question": q["question"],
                "theme": q["theme"],
                "kind": q["kind"],
                "error": f"{type(e).__name__}: {e}",
            })
            continue

        latency = time.time() - t0
        after = _snapshot_cache_stats(CACHE_STATS)
        diff = _diff_cache_stats(before, after)
        cost = _estimate_cost(diff)

        passes = _primary_routing_pass(routing["primary_topic"], q["expected_primary"])
        print(f"   gate: {gate['scope']:>14}   routed: {routing['primary_topic']}")
        if q.get("expected_primary") is not None:
            print(f"   routing pass: {passes} (expected ∈ {q['expected_primary']})")
        print(f"   response words: {_word_count(response):>4}   "
              f"latency: {latency:5.1f}s   cost: ${cost:.4f}")
        flags = [
            k for k in ("hallucination", "voice_drift", "guardrail_violation")
            if fidelity.get(k)
        ]
        if flags:
            print(f"   ⚠ fidelity: {flags} — {fidelity['reasoning']}")

        rows.append({
            "question_id": qid,
            "question": q["question"],
            "theme": q["theme"],
            "kind": q["kind"],
            "gate_scope": gate["scope"],
            "gate_reasoning": gate["reasoning"],
            "routing": routing,
            "expected_primary": q.get("expected_primary"),
            "primary_routing_pass": passes,
            "context_token_count_approx": _approx_tokens(context),
            "response": response,
            "response_word_count": _word_count(response),
            "fidelity": fidelity,
            "latency_seconds": round(latency, 2),
            "tokens": diff,
            "estimated_cost_usd": round(cost, 5),
        })

    # ---- Aggregate ----
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_prefix = args.out or str(REPORTS_DIR / "smoke_test")
    run_path = Path(f"{out_prefix}_run.json")
    summary_path = Path(f"{out_prefix}_summary.json")

    valid_rows = [r for r in rows if "error" not in r]
    in_corpus = [r for r in valid_rows if r["kind"] == "in_corpus"]
    meta_rows = [r for r in valid_rows if r["kind"] == "identity_probe"]

    n = len(valid_rows)
    primary_pass = (
        sum(1 for r in valid_rows if r["primary_routing_pass"]) / n if n else 0.0
    )
    meta_pass = (
        sum(1 for r in meta_rows if r["routing"]["primary_topic"] == "robot_identity_meta")
        / len(meta_rows) if meta_rows else 0.0
    )
    fidelity_clean = (
        sum(
            1 for r in in_corpus
            if not any(r["fidelity"].get(k) for k in ("hallucination", "voice_drift", "guardrail_violation"))
        ) / len(in_corpus) if in_corpus else 0.0
    )
    latencies = [r["latency_seconds"] for r in valid_rows]
    p95_latency = (
        statistics.quantiles(latencies, n=20)[-1] if len(latencies) > 1 else (latencies[0] if latencies else 0)
    )
    mean_cost = (
        sum(r["estimated_cost_usd"] for r in valid_rows) / n if n else 0.0
    )
    mean_words = (
        sum(r["response_word_count"] for r in valid_rows) / n if n else 0.0
    )
    substantive_rate = (
        sum(1 for r in valid_rows if r["response_word_count"] >= 40) / n if n else 0.0
    )

    summary = {
        "n_questions_attempted": len(rows),
        "n_questions_completed": n,
        "n_questions_errored": len(rows) - n,
        "primary_routing_pass_rate": round(primary_pass, 3),
        "meta_route_rate": round(meta_pass, 3),
        "fidelity_clean_rate_in_corpus": round(fidelity_clean, 3),
        "substantive_response_rate": round(substantive_rate, 3),
        "mean_response_word_count": round(mean_words, 1),
        "p95_latency_seconds": round(p95_latency, 2),
        "mean_cost_per_turn_usd": round(mean_cost, 5),
        "total_cost_usd": round(sum(r["estimated_cost_usd"] for r in valid_rows), 4),
    }

    run_path.write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # ---- Verdict (per TS-006 §2) ----
    has_in_corpus_hallucination = any(
        r["fidelity"].get("hallucination") for r in in_corpus
    )
    meta_failures = [r for r in meta_rows
                     if r["routing"]["primary_topic"] != "robot_identity_meta"]
    routing_misses = sum(1 for r in valid_rows if not r["primary_routing_pass"])

    if has_in_corpus_hallucination or meta_failures or routing_misses >= 3:
        verdict = "RED"
        exit_code = 2
    elif routing_misses >= 1:
        verdict = "YELLOW"
        exit_code = 1
    else:
        verdict = "GREEN"
        exit_code = 0

    print()
    print("==================================================")
    print(f"[smoke] verdict: {verdict}")
    print(f"  questions completed     : {n}/{len(rows)}")
    print(f"  primary routing pass    : {summary['primary_routing_pass_rate']:.0%}")
    print(f"  META route rate         : {summary['meta_route_rate']:.0%}")
    print(f"  fidelity clean (in-corp): {summary['fidelity_clean_rate_in_corpus']:.0%}")
    print(f"  substantive rate        : {summary['substantive_response_rate']:.0%}")
    print(f"  mean cost per turn      : ${summary['mean_cost_per_turn_usd']:.4f}")
    print(f"  p95 latency             : {summary['p95_latency_seconds']}s")
    print(f"  total cost              : ${summary['total_cost_usd']:.4f}")
    print(f"  run report   : {run_path}")
    print(f"  summary      : {summary_path}")
    print("==================================================")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
