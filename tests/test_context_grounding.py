"""The composer's grounding context (2026-09-12).

The voice card has always promised Sonnet "the whole .md + .json for 1-3
source documents". build_context only ever loaded the .json, so the corpus
itself never reached the composer and the fact gate — which grades an answer
against this same block — was checking it against summaries. These tests pin
the fix: the text goes in, the paraphrase of it comes out, and the budget
degrades in the direction that actually saves tokens.
"""
from __future__ import annotations

import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
import answer_pipeline as ap  # noqa: E402


def _node(name, docs):
    """A topic_map node, with the router scaffolding real ones carry."""
    return {"id": name, "display_name": name.replace("_", " ").title(), "tier": "anchor",
            "definition": "definition " + "word " * 120, "theme_anchor": "A",
            "default_register": "formal", "wit_calibration": "dry",
            "top_signature_phrases": [f"phrase {i} " + "word " * 35 for i in range(8)],
            "top_people": ["person"] * 6, "top_institutions": ["institution"] * 6,
            "top_cases": ["case"] * 4,
            # scaffolding: what got us here, useless once routing has happened
            "doc_ids": docs * 10, "matchers": {"any": ["re1", "re2"]}, "doc_count": 30,
            "date_range": ["2001-01-01", "2024-01-01"], "year_range": [2001, 2024],
            "type_distribution": {"column": 20, "speech": 10},
            "theme_distribution": {k: 6 for k in "ABCDE"}}


class FakeArtifacts:
    """Three documents on one topic: two short, one with a long body."""
    def __init__(self, bodies=None):
        self.topics = {"rule_of_law": _node("rule_of_law", ["CA001", "CA002", "CA003"]),
                       "adjacent_one": _node("adjacent_one", ["CA002"]),
                       "adjacent_two": _node("adjacent_two", ["CA003"])}
        self.docs = {}
        for i, did in enumerate(("CA001", "CA002", "CA003")):
            self.docs[did] = {
                "id": did, "title": f"Column {i}", "date": f"2023-0{i+1}-01",
                "theme": "A", "theme_label": "Liberty and Rule of Law",
                "primary_topics": ["rule_of_law"] * 6,
                "stances": [f"stance {n} " + "word " * 100 for n in range(4)],
                "signature_phrases": [f"phrase {n} " + "word " * 35 for n in range(8)],
                "notable_anecdotes": [f"anecdote {n} " + "word " * 80 for n in range(3)],
                "one_paragraph_summary": "summary " + "word " * 380,
            }
        self.bodies = bodies if bodies is not None else {
            "CA001": "body one " + "word " * 880,      # a column is ~880 words
            "CA002": "body two " + "word " * 880,
            "CA003": "body three " + "word " * 880,
        }

    def load_raw_doc(self, did):
        return self.docs.get(did)

    def load_doc_body(self, did):
        return self.bodies.get(did)


ROUTING = {"primary_topic": "rule_of_law", "secondary_topics": [], "confidence": "high"}
PARAPHRASE = ("stances", "one_paragraph_summary", "notable_anecdotes",
              "signature_phrases", "primary_topics")


def _docs(ctx):
    import json
    return json.loads(ctx.split("<source_documents>\n", 1)[1].split("\n</source_documents>")[0])


def test_the_text_goes_in_and_the_paraphrase_of_it_comes_out(monkeypatch):
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 2)
    ctx = ap.build_context(ROUTING, FakeArtifacts(), token_budget=100_000)
    docs = _docs(ctx)
    assert len(docs) == 3
    for d in docs[:2]:
        assert d["text"].startswith("body ")                  # his words
        assert not any(k in d for k in PARAPHRASE)            # and not a summary of them
        assert d["doc_id"] and d["title"] and d["date"]       # still citable
    assert "text" not in docs[2] and docs[2]["one_paragraph_summary"]


def test_zero_bodies_restores_the_old_shape(monkeypatch):
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 0)
    docs = _docs(ap.build_context(ROUTING, FakeArtifacts(), token_budget=100_000))
    assert all("text" not in d for d in docs)
    assert all(d["one_paragraph_summary"] for d in docs)


def test_a_missing_md_falls_back_to_the_sidecar(monkeypatch):
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 2)
    art = FakeArtifacts(bodies={"CA002": "body two " + "word " * 880})   # CA001's .md is gone
    docs = _docs(ap.build_context(ROUTING, art, token_budget=100_000))
    assert "text" not in docs[0] and docs[0]["one_paragraph_summary"]
    assert docs[1]["text"].startswith("body two")


def test_grounding_is_cheaper_than_the_paraphrase_it_replaces(monkeypatch):
    """The measurement behind the change: for a column the sidecar costs more
    than the column. So the budget must NOT 'save' tokens by demoting a
    document to its sidecar — that grows the block."""
    art = FakeArtifacts()
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 0)
    plain = ap._approx_tokens(ap.build_context(ROUTING, art, token_budget=100_000))
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 2)
    grounded = ap._approx_tokens(ap.build_context(ROUTING, art, token_budget=100_000))
    assert grounded < plain
    sidecar = ap._approx_tokens(str(ap._trim_doc(art.docs["CA001"])))
    body = ap._approx_tokens(str(ap._trim_doc(art.docs["CA001"], art.bodies["CA001"])))
    assert body < sidecar


def test_over_budget_drops_documents_rather_than_their_text(monkeypatch):
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 2)
    art = FakeArtifacts()
    full = ap._approx_tokens(ap.build_context(ROUTING, art, token_budget=100_000))
    ctx = ap.build_context(ROUTING, art, token_budget=int(full * 0.6))
    docs = _docs(ctx)
    assert ap._approx_tokens(ctx) <= int(full * 0.6)
    assert docs and all("text" in d for d in docs)             # kept the text, dropped a doc
    rep = ap.LAST_CONTEXT_DOCS
    assert len(rep) == 3 and sum(d["dropped_for_budget"] for d in rep) == 3 - len(docs)
    assert all(d["summary"] for d in rep)                      # the dashboard still sees summaries
    assert [d["body"] for d in rep][:len(docs)] == [True] * len(docs)


def test_a_body_longer_than_its_sidecar_is_demoted_not_dropped(monkeypatch):
    """A long speech is the other way round: there, losing the text is the
    cheaper move, and keeping the document's topics beats losing it."""
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 1)
    art = FakeArtifacts()
    art.bodies["CA001"] = "long " * 4000
    big = ap._approx_tokens(ap.build_context(ROUTING, art, token_budget=100_000))
    docs = _docs(ap.build_context(ROUTING, art, token_budget=int(big * 0.7)))
    assert len(docs) == 3 and "text" not in docs[0]            # demoted, every doc kept
    assert docs[0]["one_paragraph_summary"]


def test_the_fact_gate_now_sees_what_the_composer_saw(monkeypatch):
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 2)
    ctx = ap.build_context(ROUTING, FakeArtifacts(), token_budget=100_000)
    assert ap.LAST_CONTEXT_TEXT[0] == ctx and "body one" in ap.LAST_CONTEXT_TEXT[0]


# ── the preface (2026-09-12) ────────────────────────────────────────────────
# Loading the bodies alone changed nothing in production: a real routing
# carries three topic nodes, and at 2,526 tokens of a 3,500 budget they left
# no room for a single source document. The nodes are built for the ROUTER.

REAL_ROUTING = {"primary_topic": "rule_of_law",
                "secondary_topics": ["adjacent_one", "adjacent_two"], "confidence": "high"}


def _preface(ctx):
    return ctx.split("<source_documents>")[0]


def test_router_scaffolding_is_not_sent_to_the_composer():
    art = FakeArtifacts()
    primary = ap._trim_topic_node(art.topics["rule_of_law"], primary=True)
    assert not any(k in primary for k in ap._TOPIC_SCAFFOLDING)
    for k in ("definition", "top_signature_phrases", "top_people", "top_cases", "wit_calibration"):
        assert k in primary                                   # what the composer can use stays
    secondary = ap._trim_topic_node(art.topics["adjacent_one"], primary=False)
    assert set(secondary) <= set(ap._SECONDARY_KEEP) and secondary["definition"]
    assert "top_signature_phrases" not in secondary           # adjacency, not the subject


def test_a_real_routing_now_leaves_room_for_a_document(monkeypatch):
    """The regression that matters: primary + 2 secondary topics at the
    production budget must still reach the composer with source text."""
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 2)
    art = FakeArtifacts()
    ctx = ap.build_context(REAL_ROUTING, art, token_budget=3500)
    kept = [d for d in ap.LAST_CONTEXT_DOCS if not d["dropped_for_budget"]]
    assert kept, "every source document was dropped — the preface ate the budget"
    assert any(d["body"] for d in kept)
    assert ap._approx_tokens(_preface(ctx)) < 1500


def test_the_lean_preface_is_what_makes_room(monkeypatch):
    monkeypatch.setattr(ap, "CONTEXT_BODY_DOCS", 2)
    art = FakeArtifacts()
    lean_ctx = ap.build_context(REAL_ROUTING, art, token_budget=3500)
    lean = ap._approx_tokens(_preface(lean_ctx))
    lean_text = [d for d in ap.LAST_CONTEXT_DOCS if d["body"] and not d["dropped_for_budget"]]
    monkeypatch.setattr(ap, "_trim_topic_node", lambda n, primary: n)   # the old, whole-node preface
    ap.build_context(REAL_ROUTING, art, token_budget=3500)
    fat_text = [d for d in ap.LAST_CONTEXT_DOCS if d["body"] and not d["dropped_for_budget"]]
    assert ap._approx_tokens(_preface(lean_ctx)) < 1500 < 2 * lean
    assert len(lean_text) > len(fat_text) and not fat_text
