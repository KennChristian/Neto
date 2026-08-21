"""
Build a curated topic map for the CJ Panganiban corpus.

Reads the 79 generated .json files under corpus/{columns,speeches,biography}/
and writes:
  - corpus/voice/topic_map.json   — taxonomy + per-topic stats
  - reports/topic_map_report.json — coverage / unmatched-docs report

The taxonomy is a hand-curated dict of ~35 topics with matcher rules
(case-insensitive substring matches against title, primary_topics,
sub_topics, keywords, and entity names). Each topic carries a default
register and wit calibration from PROJECT.md §9.

Each document is scored against every topic; the top scorers become the
doc's primary topic_paths, the next tier become secondary. The same
matcher data is used by `apply_topic_paths.py` to backfill the per-doc
.json files.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_ROOT = PROJECT_ROOT / "corpus"
VOICE_DIR = CORPUS_ROOT / "voice"
REPORTS_DIR = PROJECT_ROOT / "reports"

THEME_LABELS = {
    "A": "Liberty and Rule of Law",
    "B": "Prosperity and Economic Philosophy",
    "C": "Biographical and Personal",
    "D": "FLP Mission and Foundation",
    "E": "Signature Current Events Commentary",
}

# Default register by theme — per PROJECT.md §9.
THEME_REGISTER = {
    "A": ("ceremonial_doctrinal", "sparing, diplomatic"),
    "B": ("case_analytical_with_openers", "professional warmth"),
    "C": ("testimonial", "gentle, self-deprecating"),
    "D": ("ceremonial_with_humor", "freely, head-table style"),
    "E": ("reflective_pedagogical", "thoughtful, warm"),
}


# -- Taxonomy ----------------------------------------------------------------
#
# Each topic is a dict with:
#   id              : snake_case slug
#   display_name    : human readable
#   definition      : 1-2 sentence semantic anchor
#   tier            : anchor | core | subordinate | meta
#   theme_anchor    : "A".."E" or "META"
#   default_register: from THEME_REGISTER or topic-specific override
#   wit_calibration : same
#   matchers        : { keywords: list[str], entities: list[str] }
#     matched against title + primary_topics + sub_topics + keywords +
#     entity names + register_markers (all lowercased substring tests)
#
# Topic scoring: each unique matcher term that appears in the doc adds 1 to
# the score; documents are assigned primary topic_paths for their top 2
# scorers and secondary for the next 3.

TAXONOMY: list[dict[str, Any]] = [
    # ===== Anchors =====
    {
        "id": "rule_of_law",
        "display_name": "The Rule of Law",
        "definition": "CJP's most-repeated organizing concept — law over force, applied across constitutional, regional, and global domains; the negative list (NOT mob, NOT propaganda, NOT nuclear weapons) and the affirmative test (consensus + treaty fidelity).",
        "tier": "anchor",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "rule of law", "rule of force", "rule of the mob", "gray tactics",
                "consensus as our north star", "besieged",
            ],
            "entities": [],
        },
    },
    {
        "id": "twin_beacons_doctrine",
        "display_name": "Liberty and Prosperity — Twin Beacons",
        "definition": "The interdependence of liberty and prosperity under the rule of law: 'one is useless without the other.' The chiastic doublets (justice and jobs; freedom and food; ethics and economics; peace and development).",
        "tier": "anchor",
        "theme_anchor": "B",
        "matchers": {
            "keywords": [
                "twin beacons", "liberty and prosperity", "twin and inseparable",
                "justice and jobs", "freedom and food", "ethics and economics",
                "safeguard liberty", "nurture prosperity",
            ],
            "entities": [],
        },
    },
    {
        "id": "foundation_for_liberty_and_prosperity",
        "display_name": "Foundation for Liberty and Prosperity (FLP)",
        "definition": "FLP as the institutional vehicle for the twin-beacons philosophy in CJP's post-judicial life — scholarships, fellowships, dissertations, chairs, plus the two 'ultimate projects' (Museum and Prosperity Fund).",
        "tier": "anchor",
        "theme_anchor": "D",
        "matchers": {
            "keywords": [
                "foundation for liberty and prosperity", "flp", "flp awards",
                "flp board", "flp programs", "flp partners",
                "10th anniversary", "ultimate projects",
            ],
            "entities": ["Foundation for Liberty and Prosperity"],
        },
    },
    {
        "id": "with_due_respect_persona",
        "display_name": "'With Due Respect' — the columnist's stance",
        "definition": "The signature columnist register: firm but civil, critical but disciplined, IMHO + Au contraire + self-citation + chiastic enumerations.",
        "tier": "anchor",
        "theme_anchor": "E",
        "matchers": {
            "keywords": [
                "with due respect", "imho", "in my humble opinion",
                "au contraire", "respectfully submit",
            ],
            "entities": [],
        },
    },

    # ===== Core (A — Liberty / Rule of Law) =====
    {
        "id": "constitutional_doctrine",
        "display_name": "Constitutional Doctrine (1987 Constitution)",
        "definition": "Article-and-section exegesis of the 1987 Philippine Constitution — bill of rights, separation of powers, judicial review.",
        "tier": "core",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "1987 constitution", "1987 philippine constitution", "bill of rights",
                "article xii", "article xi", "article viii", "constitutional commission",
                "separation of powers", "cha-cha", "constitutional amendment",
                "charter change", "martial law", "authoritarian rule",
                "rebellion or invasion",
            ],
            "entities": ["1987 Philippine Constitution", "1987 Constitution"],
        },
    },
    {
        "id": "due_process",
        "display_name": "Due Process and Fair Trial",
        "definition": "Procedural and substantive due process — life, liberty, property; notice and hearing; the natural-law sources (Themistocles, Daniel Webster).",
        "tier": "core",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "due process", "notice and hearing", "themistocles", "daniel webster",
                "procedural due process", "fair trial", "strike but hear me first",
            ],
            "entities": [],
        },
    },
    {
        "id": "judicial_reform",
        "display_name": "Judicial Reform — Four Ins and ACID problems",
        "definition": "CJP's judicial-reform vocabulary: the four Ins (independence, integrity, industry, intelligence) versus the four ACID problems (access, corruption, incompetence, delay); the Action Program for Judicial Reform (APJR) and the Strategic Plan for Judicial Innovation.",
        "tier": "core",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "four ins", "acid problems", "judicial reform", "apjr",
                "strategic plan for judicial innovation",
                "action program for judicial reform",
                "judicial excellence", "benchbook",
            ],
            "entities": [],
        },
    },
    {
        "id": "supreme_court_history",
        "display_name": "Supreme Court — history and stewardship",
        "definition": "The Supreme Court as an institution — Chief Justices, centenary, judicial stewardship, the Panganiban Court, succession.",
        "tier": "core",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "panganiban court", "centenary of justice",
                "supreme court centenary", "21st chief justice",
                "ponente", "ponencia", "primus inter pares",
            ],
            "entities": [
                "CJ Alexander G. Gesmundo",
                "CJ Hilario G. Davide Jr.",
                "Justice Antonio T. Carpio",
            ],
        },
    },
    {
        "id": "impeachment_accountability",
        "display_name": "Impeachment and Accountability",
        "definition": "Impeachment as sui generis political-prosecutorial mechanism — House (prosecutorial) vs Senate (adjudicatory) roles; the Corona impeachment; the limit of due-process coverage.",
        "tier": "subordinate",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "impeachment", "impeach", "articles of impeachment",
                "sui generis", "corona", "moro-moro",
                "public office is a public trust",
            ],
            "entities": ["CJ Renato C. Corona"],
        },
    },
    {
        "id": "international_law_disputes",
        "display_name": "International Law — Arbitral Award, UNCLOS, EEZ",
        "definition": "South China Sea / West Philippine Sea Arbitral Award; UNCLOS; nine-dash line; EEZ; Permanent Court of Arbitration; Mutual Defense Treaty.",
        "tier": "core",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "arbitral award", "unclos", "nine-dash line", "eez",
                "exclusive economic zone", "west philippine sea",
                "south china sea", "wps", "permanent court of arbitration",
                "mutual defense treaty", "freedom of navigation",
                "jmsu", "joint marine seismic undertaking",
            ],
            "entities": [
                "Permanent Court of Arbitration",
                "United Nations Convention on the Law of the Sea",
            ],
        },
    },
    {
        "id": "icc_and_duterte",
        "display_name": "ICC and the Duterte case",
        "definition": "The Rome Statute, ICC jurisdiction post-withdrawal, the two-year prescriptive period, the Office of the Chief Prosecutor (Bensouda → Khan), and the Duterte mass-murder case.",
        "tier": "subordinate",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "icc", "international criminal court", "rome statute",
                "karim khan", "bensouda", "office of the chief prosecutor",
                "pre-trial chamber", "two-year prescriptive",
                "subsidiarity", "complementarity",
            ],
            "entities": [
                "International Criminal Court",
                "Rome Statute",
                "Karim Khan",
                "Rodrigo Duterte",
            ],
        },
    },
    {
        "id": "judicial_activism_and_political_question",
        "display_name": "Judicial Activism and the Political Question Doctrine",
        "definition": "Comparative US-Philippine judicial activism — political-question doctrine, deference, and the courts' role in checking the political branches.",
        "tier": "subordinate",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "judicial activism", "political question", "deferential interpretation",
                "deference",
            ],
            "entities": [],
        },
    },
    {
        "id": "asean_law_association",
        "display_name": "ASEAN Law Association and Regional Order",
        "definition": "ALA, the ASEAN consensus principle, regional rule-of-law leadership, and CJP's outgoing chairmanship.",
        "tier": "subordinate",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "asean law association", "ala general assembly",
                "kuala lumpur", "ala philippines", "asean consensus",
                "ala chairmanship",
            ],
            "entities": ["ASEAN Law Association", "ALA Philippines"],
        },
    },
    {
        "id": "death_penalty_and_echegaray",
        "display_name": "Death Penalty and the Echegaray Reflection",
        "definition": "CJP's 2006 personal-conscience reflection on the Leo Echegaray case after Congress abolished the death penalty — the conscience/institution distinction.",
        "tier": "subordinate",
        "theme_anchor": "A",
        "matchers": {
            "keywords": ["death penalty", "echegaray", "leo echegaray"],
            "entities": [],
        },
    },
    {
        "id": "bar_exam_and_legal_education",
        "display_name": "Bar Examination and Legal Education",
        "definition": "Bar exams, law-school formation, FEU, UP, the legal scholarship program, and the long arc from Sampaloc-newsboy to legal education benefactor.",
        "tier": "subordinate",
        "theme_anchor": "A",
        "matchers": {
            "keywords": [
                "bar exam", "bar examination", "bar topnotcher",
                "legal education", "law school formation",
                "feu law", "feu central student", "nusp",
                "philippine law school",
            ],
            "entities": [],
        },
    },

    # ===== Core (B — Prosperity / Economy) =====
    {
        "id": "economic_governance_and_business_law",
        "display_name": "Economic Governance and Business Law",
        "definition": "Deferential interpretation, the Gamboa-Teves line, business-friendly judicial doctrine, and the policy environment for entrepreneurship.",
        "tier": "core",
        "theme_anchor": "B",
        "matchers": {
            "keywords": [
                "deferential interpretation", "gamboa vs teves",
                "business law", "policy environment", "economic policy",
                "judicial deference",
            ],
            "entities": ["Gamboa vs Teves"],
        },
    },
    {
        "id": "eez_resource_sovereignty",
        "display_name": "EEZ Resource Sovereignty",
        "definition": "Article XII Section 2's twin safeguards — state control and 60-40 citizenship — applied to South China Sea joint-development negotiations.",
        "tier": "subordinate",
        "theme_anchor": "B",
        "matchers": {
            "keywords": [
                "full control and supervision", "60-40", "regalian doctrine",
                "natural resources", "joint development", "memorandum of understanding",
                "mou with china",
            ],
            "entities": [],
        },
    },
    {
        "id": "msme_and_entrepreneurship",
        "display_name": "MSME and Entrepreneurship — the Prosperity Fund",
        "definition": "The pro-poor, pro-private-initiative Prosperity Fund for MSMEs and the Esmel (Entrepreneurship, Sustainability, Management, Economics, Law) fellowship program.",
        "tier": "core",
        "theme_anchor": "B",
        "matchers": {
            "keywords": [
                "prosperity fund", "msme", "esmel", "entrepreneurship fund",
                "pro-poor", "private entrepreneurship", "multibillion-peso",
            ],
            "entities": [],
        },
    },

    # ===== Core (C — Biographical) =====
    {
        "id": "family_and_marriage",
        "display_name": "Family — Leni, children, grandchildren",
        "definition": "CJP's marriage to Leni Carpio Panganiban, his five children, grandchildren, and the household register he calls 'the real chief justice of this household.'",
        "tier": "core",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "leni", "marisita", "leni carpio", "panganiban family",
                "wife", "wedding anniversary", "children", "grandchildren",
            ],
            "entities": ["Leni Carpio-Panganiban", "Leni Panganiban"],
        },
    },
    {
        "id": "mentors_and_legal_lineage",
        "display_name": "Mentors and Legal Lineage",
        "definition": "Dr. Jovito R. Salonga as guru; Diokno and Teehankee as living moral architects; Salonga, Ordoñez and Associates as formative apprenticeship.",
        "tier": "core",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "salonga", "jovito r. salonga", "diokno", "pepe diokno",
                "teehankee", "claudio o. teehankee",
                "salonga, ordoñez", "mentor", "my guru",
            ],
            "entities": [
                "Dr. Jovito R. Salonga",
                "Jose W. Diokno",
                "Claudio O. Teehankee",
            ],
        },
    },
    {
        "id": "faith_journey",
        "display_name": "Faith Journey — BLD, Pontifical Council, Pro Ecclesia",
        "definition": "Catholic faith arriving late in life; Bukas Loob sa Diyos (BLD) covenant community with Leni; the Pontifical Council for the Laity appointment by John Paul II; the Pro Ecclesia et Pontifice papal award; Romans 8:28 and Isaiah 55:8-9 as touchstones.",
        "tier": "core",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "bld", "bukas loob sa diyos", "catholic", "pontifical council",
                "pro ecclesia", "papal award", "romans 8:28", "isaiah 55",
                "ignatian", "faith", "providence", "his own time",
            ],
            "entities": [
                "Pope John Paul II",
                "Bukas Loob sa Diyos",
                "Pontifical Council for the Laity",
            ],
        },
    },
    {
        "id": "early_life_sampaloc",
        "display_name": "Early Life — Sampaloc, FEU, the Bar",
        "definition": "From Sampaloc newsboy to FEU summa cum laude to 1960 bar 6th-placer; the 15-centavo bus fare; Mapa High; the Trinity-failure scholarship interview.",
        "tier": "subordinate",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "sampaloc", "newsboy", "mapa high", "victorino mapa",
                "15 centavos", "fifteen centavos",
                "juan luna elementary", "summa cum laude",
                "1960 bar", "sixth place",
            ],
            "entities": [],
        },
    },
    {
        "id": "jbc_discernment_and_appointment",
        "display_name": "JBC Discernment — the Seven Rejections",
        "definition": "Seven Judicial and Bar Council rejections (1992-1995), the January 1995 surrender prayer, the Ask-Seek-Knock and Transfiguration Gospel readings, and the October 1995 appointment by Ramos.",
        "tier": "subordinate",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "jbc", "judicial and bar council", "seven rejections",
                "ask and you shall receive", "transfiguration", "discernment",
            ],
            "entities": [],
        },
    },
    {
        "id": "eulogies_and_passing",
        "display_name": "Eulogies and Passing of Loved Ones",
        "definition": "Eulogies and remembrances — Linda Manuel Mañalac, Leni's passing, Fr. Michael Nolan, and the fragility-of-life pastoral framework.",
        "tier": "subordinate",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "eulogy", "passing", "in memoriam", "fragility of life",
                "widower", "love and magnanimity",
                "leni's passing", "in his heavenly kingdom",
            ],
            "entities": [
                "Linda Manuel Mañalac",
                "Fr. Michael Nolan",
                "Tong Manalac",
            ],
        },
    },
    {
        "id": "friendships_and_civic_circles",
        "display_name": "Friendships and Civic Circles",
        "definition": "CJP's friendships and patron network — Marixi R. Prieto, Manuel V. Pangilinan, the Ayalas, the Tan family, Rotary Club of Manila.",
        "tier": "subordinate",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "marixi prieto", "manuel v. pangilinan", "manny pangilinan",
                "rotary club of manila",
                "dear friend",
            ],
            "entities": [
                "Marixi R. Prieto",
                "Manuel V. Pangilinan",
                "Rotary Club of Manila",
            ],
        },
    },
    {
        "id": "honors_received",
        "display_name": "Honors Received",
        "definition": "Pro Ecclesia et Pontifice; Bantayog ng mga Bayani 'Haligi ng Bantayog'; Manila Overseas Press Club Journalist of the Year — Law; honorary doctorates.",
        "tier": "subordinate",
        "theme_anchor": "C",
        "matchers": {
            "keywords": [
                "bantayog", "haligi ng bantayog", "haligi",
                "journalist of the year", "honorary doctorate",
                "manila overseas press club",
            ],
            "entities": [
                "Bantayog ng mga Bayani",
                "Manila Overseas Press Club",
            ],
        },
    },

    # ===== Core (D — FLP Mission) =====
    {
        "id": "flp_scholarship_programs",
        "display_name": "FLP Scholarship and Fellowship Programs",
        "definition": "FLP Legal Scholarship, ESMEL Fellowship, Dissertation Writing Contest, Professorial Chairs, Panganiban Education Assistance Program.",
        "tier": "core",
        "theme_anchor": "D",
        "matchers": {
            "keywords": [
                "scholarship", "esmel fellowship", "dissertation writing contest",
                "professorial chair", "education assistance program",
                "panganiban education", "law scholarship",
            ],
            "entities": [],
        },
    },
    {
        "id": "museum_for_liberty_and_prosperity",
        "display_name": "Museum for Liberty and Prosperity",
        "definition": "The futuristic, AI-powered, immersive Museum as the liberty half of FLP's two ultimate projects; Palafox preliminary designs; Alabang Global City lot donated by Allen Roxas.",
        "tier": "core",
        "theme_anchor": "D",
        "matchers": {
            "keywords": [
                "museum for liberty", "center for liberty and prosperity",
                "ai-powered museum", "immersive museum", "palafox",
                "allen roxas", "alabang global city",
            ],
            "entities": [],
        },
    },
    {
        "id": "prosperity_fund_msme",
        "display_name": "Prosperity Fund (MSME)",
        "definition": "The pro-poor multibillion-peso Prosperity Fund — the prosperity half of FLP's two ultimate projects.",
        "tier": "core",
        "theme_anchor": "D",
        "matchers": {
            "keywords": [
                "prosperity fund", "msme fund", "multibillion-peso fund",
                "pro-poor fund",
            ],
            "entities": [],
        },
    },
    {
        "id": "flp_donors_and_partners",
        "display_name": "FLP Donors and Institutional Partners",
        "definition": "Tan Yan Kee Foundation, Metrobank Foundation, Ayala Corporation, SM Investments, BDO, MPIC, AIM — the institutional ecosystem behind FLP's programs.",
        "tier": "subordinate",
        "theme_anchor": "D",
        "matchers": {
            "keywords": [
                "tan yan kee foundation", "metrobank foundation",
                "ayala corporation", "sm investments", "bdo unibank",
                "metro pacific investments", "mpic", "asian institute of management",
                "aim",
            ],
            "entities": [
                "Tan Yan Kee Foundation",
                "Metrobank Foundation",
                "Ayala Corporation",
                "SM Investments Corporation",
                "Asian Institute of Management",
            ],
        },
    },
    {
        "id": "lawyer_ethics_initiative",
        "display_name": "Lawyer Ethics Initiative (Super Committee)",
        "definition": "Tessie Sy Coson's principle that lawyers must be 'not just talented, but also ethical and Godly,' the new Super Committee under SolGen Berberabe, and FLP's ethical-formation track.",
        "tier": "subordinate",
        "theme_anchor": "D",
        "matchers": {
            "keywords": [
                "ethical and godly", "lawyer ethics", "super committee",
                "ethical standards", "berberabe",
            ],
            "entities": ["Tessie Sy Coson", "SolGen Lelen Berberabe"],
        },
    },

    # ===== Core (E — Current Events) =====
    {
        "id": "ai_and_technology",
        "display_name": "AI, Technology, and the Judiciary",
        "definition": "Artificial intelligence in court administration; the Strategic Plan for Judicial Innovation 'for the Age of Artificial Intelligence'; technology and rule-of-law.",
        "tier": "subordinate",
        "theme_anchor": "E",
        "matchers": {
            "keywords": [
                "artificial intelligence", "ai-powered", "ai for the",
                "age of artificial intelligence", "technology",
            ],
            "entities": [],
        },
    },
    {
        "id": "global_geopolitics",
        "display_name": "Global Geopolitics and the ICJ",
        "definition": "Comparative international-court watch — ICJ genocide cases (South Africa v. Israel; Russia-Ukraine), Trump-era US constitutional contests, and the international rule-of-law erosion.",
        "tier": "subordinate",
        "theme_anchor": "E",
        "matchers": {
            "keywords": [
                "icj", "international court of justice", "genocide",
                "south africa v. israel", "gaza", "russia-ukraine",
                "trump", "presidential immunity",
            ],
            "entities": [],
        },
    },
    {
        "id": "philippine_political_landscape",
        "display_name": "Philippine Political Landscape",
        "definition": "Contemporary Philippine politics — Marcos administration, the First Lady's legal practice, GMA, post-Duterte realignment.",
        "tier": "subordinate",
        "theme_anchor": "E",
        "matchers": {
            "keywords": [
                "marcos jr", "bongbong marcos", "first lady",
                "louise araneta-marcos", "gma", "macapagal-arroyo",
            ],
            "entities": [
                "President Ferdinand Marcos Jr.",
                "First Lady Louise Araneta-Marcos",
                "President Gloria Macapagal-Arroyo",
            ],
        },
    },

    # ===== Meta =====
    {
        "id": "robot_identity_meta",
        "display_name": "Robot Identity (META)",
        "definition": "Questions about whether this is the real CJP, an AI, a robot, or how it works. Answered fully in persona as Chief Justice Panganiban himself — gracious, lightly amused, never describing himself as an AI, robot, machine, or rendering (the voice card's Identity rule).",
        "tier": "meta",
        "theme_anchor": "META",
        "default_register_override": ("gracious_in_persona", "gentle, self-deprecating"),
        "matchers": {
            "keywords": [
                "are you ai", "are you a robot", "are you real",
                "is this really cjp", "how do you work", "are you panganiban",
                "robot rendering", "ai conversation robot",
            ],
            "entities": [],
        },
    },
]


# -- Matching engine ---------------------------------------------------------

def _doc_haystack(doc: dict[str, Any]) -> str:
    """Build a single lowercased searchable string from doc fields."""
    parts: list[str] = [doc.get("title", ""), doc.get("one_paragraph_summary", "")]
    for k in ("primary_topics", "sub_topics", "keywords", "register_markers"):
        for item in doc.get(k, []) or []:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("phrase", "")))
                parts.append(str(item.get("summary", "")))
    ent = doc.get("entities", {}) or {}
    for k in ("people", "institutions", "cases", "laws_treaties", "events"):
        for item in ent.get(k, []) or []:
            if isinstance(item, str):
                parts.append(item)
    return " || ".join(p for p in parts if p).lower()


_KW_CACHE: dict[str, re.Pattern[str]] = {}


def _kw_pattern(term: str) -> re.Pattern[str]:
    """Compile a word-boundary regex for a matcher term (cached)."""
    if term not in _KW_CACHE:
        _KW_CACHE[term] = re.compile(r"\b" + re.escape(term.lower()) + r"\b")
    return _KW_CACHE[term]


def score_topic(topic: dict[str, Any], haystack: str) -> int:
    score = 0
    for kw in topic["matchers"]["keywords"]:
        if _kw_pattern(kw).search(haystack):
            score += 1
    for ent in topic["matchers"].get("entities", []):
        if _kw_pattern(ent).search(haystack):
            score += 1
    return score


# -- Aggregation -------------------------------------------------------------

def load_docs() -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    for p in sorted(CORPUS_ROOT.glob("columns/**/*.json")):
        out.append((p, json.loads(p.read_text(encoding="utf-8"))))
    for p in sorted(CORPUS_ROOT.glob("speeches/**/*.json")):
        out.append((p, json.loads(p.read_text(encoding="utf-8"))))
    for p in sorted(CORPUS_ROOT.glob("biography/**/*.json")):
        out.append((p, json.loads(p.read_text(encoding="utf-8"))))
    return out


def build_topic_map(docs: list[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    # Score every doc against every topic.
    doc_scores: dict[str, dict[str, int]] = {}
    for _, doc in docs:
        hs = _doc_haystack(doc)
        doc_scores[doc["id"]] = {t["id"]: score_topic(t, hs) for t in TAXONOMY}

    topics_out: dict[str, dict[str, Any]] = {}

    for topic in TAXONOMY:
        matched = [
            doc for _, doc in docs if doc_scores[doc["id"]][topic["id"]] > 0
        ]
        doc_ids = [d["id"] for d in matched]
        years = sorted({d["year"] for d in matched if d.get("year")})
        dates = sorted({d["date"] for d in matched if d.get("date")})
        date_range = [dates[0], dates[-1]] if dates else []

        type_dist: Counter[str] = Counter(d["type"] for d in matched)
        theme_dist: Counter[str] = Counter(d["theme"] for d in matched)

        # Aggregate signature phrases across matched docs, with frequency.
        phrase_counter: Counter[str] = Counter()
        phrase_docs: dict[str, set[str]] = {}
        for d in matched:
            for sp in d.get("signature_phrases", []) or []:
                if isinstance(sp, dict):
                    phrase = (sp.get("phrase") or "").strip()
                else:
                    phrase = str(sp).strip()
                if not phrase or len(phrase) > 200:
                    continue
                phrase_counter[phrase] += 1
                phrase_docs.setdefault(phrase, set()).add(d["id"])

        top_phrases = [
            {
                "phrase": phrase,
                "count": count,
                "doc_ids": sorted(phrase_docs[phrase]),
            }
            for phrase, count in phrase_counter.most_common(8)
        ]

        # Aggregate entities.
        people: Counter[str] = Counter()
        institutions: Counter[str] = Counter()
        cases: Counter[str] = Counter()
        for d in matched:
            ent = d.get("entities", {}) or {}
            for p in ent.get("people", []) or []:
                if isinstance(p, str):
                    people[p.split("(")[0].strip()] += 1
            for i in ent.get("institutions", []) or []:
                if isinstance(i, str):
                    institutions[i.split("(")[0].strip()] += 1
            for c in ent.get("cases", []) or []:
                if isinstance(c, str):
                    cases[c.split("(")[0].strip()] += 1

        # Register defaults.
        default_register = topic.get("default_register_override") or THEME_REGISTER.get(
            topic["theme_anchor"], ("doctrinal-formal", "sparing")
        )

        topics_out[topic["id"]] = {
            "id": topic["id"],
            "display_name": topic["display_name"],
            "definition": topic["definition"],
            "tier": topic["tier"],
            "theme_anchor": topic["theme_anchor"],
            "default_register": default_register[0],
            "wit_calibration": default_register[1],
            "doc_count": len(doc_ids),
            "doc_ids": sorted(doc_ids),
            "date_range": date_range,
            "year_range": [years[0], years[-1]] if years else [],
            "type_distribution": dict(type_dist),
            "theme_distribution": dict(theme_dist),
            "top_signature_phrases": top_phrases,
            "top_people": [k for k, _ in people.most_common(6)],
            "top_institutions": [k for k, _ in institutions.most_common(6)],
            "top_cases": [k for k, _ in cases.most_common(4)],
            "matchers": topic["matchers"],
        }

    return {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_stats": {
            "n_docs": len(docs),
            "n_topics": len(TAXONOMY),
            "doc_type_distribution": dict(
                Counter(d["type"] for _, d in docs)
            ),
            "theme_distribution": dict(
                Counter(d["theme"] for _, d in docs)
            ),
            "year_distribution": dict(
                sorted(Counter(d["year"] for _, d in docs).items())
            ),
        },
        "themes": {
            letter: {
                "letter": letter,
                "label": THEME_LABELS[letter],
                "default_register": THEME_REGISTER[letter][0],
                "wit_calibration": THEME_REGISTER[letter][1],
            }
            for letter in "ABCDE"
        },
        "topics": topics_out,
    }, doc_scores


# -- Per-doc topic_paths derivation -----------------------------------------

def derive_topic_paths(
    doc_id: str, doc_scores: dict[str, dict[str, int]],
    primary_n: int = 2, secondary_n: int = 3,
) -> dict[str, list[str]]:
    """Pick top topics for one doc — primary (≥2 keyword hits), secondary (≥1).

    Returns {primary: [...], secondary: [...]}.
    """
    scores = doc_scores.get(doc_id, {})
    # Sort topics by score desc, then by tier (anchor > core > subordinate > meta).
    tier_rank = {"anchor": 0, "core": 1, "subordinate": 2, "meta": 9}
    by_tier = {t["id"]: tier_rank.get(t["tier"], 5) for t in TAXONOMY}
    ranked = sorted(
        ((tid, sc) for tid, sc in scores.items() if sc > 0),
        key=lambda kv: (-kv[1], by_tier[kv[0]]),
    )
    primary: list[str] = []
    secondary: list[str] = []
    for tid, sc in ranked:
        if sc >= 2 and len(primary) < primary_n:
            primary.append(tid)
        elif len(secondary) < secondary_n:
            secondary.append(tid)
        if len(primary) >= primary_n and len(secondary) >= secondary_n:
            break
    # If no topic crossed the ≥2 threshold, promote the strongest scorer
    # to primary so every doc has at least one route.
    if not primary and ranked:
        primary = [ranked[0][0]]
        secondary = [tid for tid, _ in ranked[1 : 1 + secondary_n]]
    return {"primary": primary, "secondary": secondary}


# -- Write outputs -----------------------------------------------------------

def write_topic_map(tm: dict[str, Any]) -> Path:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = VOICE_DIR / "topic_map.json"
    out_path.write_text(
        json.dumps(tm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out_path


def matcher_health_check(
    tm: dict[str, Any],
    doc_scores: dict[str, dict[str, int]],
    docs: list[tuple[Path, dict[str, Any]]],
    over_broad_frac: float = 0.25,
    near_dup_jaccard: float = 0.50,
    dominant_term_frac: float = 0.80,
) -> list[dict[str, Any]]:
    """
    Per PLAN-0007 §4 — flag taxonomy issues that should trigger curator
    review. Returns a list of warning dicts; also prints them.

    Categories:
      - zero-coverage  : non-meta topic with 0 docs
      - over-broad     : topic claims > over_broad_frac of corpus
      - near-duplicate : topic pair with Jaccard overlap > near_dup_jaccard
      - dominant-term  : within a topic, ≥ dominant_term_frac of its docs
                         match on a single matcher term
    """
    warnings_out: list[dict[str, Any]] = []
    topics = tm["topics"]
    n_docs = len(docs)
    over_broad_cutoff = max(1, int(over_broad_frac * n_docs))

    # 1. Zero-coverage and over-broad
    for tid, t in topics.items():
        if t["tier"] == "meta":
            continue
        if t["doc_count"] == 0:
            warnings_out.append(
                {"kind": "zero-coverage", "topic": tid,
                 "msg": f"{tid} has 0 docs; consider loosening matchers or "
                        f"retiring (PLAN-0007 §3b/§3d)"}
            )
        elif t["doc_count"] > over_broad_cutoff:
            warnings_out.append(
                {"kind": "over-broad", "topic": tid, "doc_count": t["doc_count"],
                 "msg": f"{tid} claims {t['doc_count']} of {n_docs} docs "
                        f"({t['doc_count']/n_docs:.0%}); consider tightening "
                        f"matchers (PLAN-0007 §3c)"}
            )

    # 2. Near-duplicate topic pairs
    topic_ids = list(topics.keys())
    for i, a in enumerate(topic_ids):
        a_set = set(topics[a]["doc_ids"])
        if not a_set:
            continue
        for b in topic_ids[i + 1 :]:
            b_set = set(topics[b]["doc_ids"])
            if not b_set:
                continue
            intersection = a_set & b_set
            union = a_set | b_set
            if not union:
                continue
            jaccard = len(intersection) / len(union)
            if jaccard > near_dup_jaccard:
                warnings_out.append(
                    {"kind": "near-duplicate", "topics": [a, b],
                     "jaccard": round(jaccard, 3),
                     "msg": f"{a} and {b} overlap (Jaccard={jaccard:.2f}); "
                            f"consider merge or matcher-disjoint refactor "
                            f"(PLAN-0007 §3e)"}
                )

    # 3. Dominant-term per topic
    docs_by_id = {doc["id"]: doc for _, doc in docs}
    for tid, t in topics.items():
        members = t["doc_ids"]
        if len(members) < 3:
            continue  # Too small for the dominance ratio to mean much.
        all_terms = list(t["matchers"]["keywords"]) + list(
            t["matchers"].get("entities", [])
        )
        for term in all_terms:
            pat = _kw_pattern(term)
            hits = sum(
                1 for mid in members
                if mid in docs_by_id and pat.search(_doc_haystack(docs_by_id[mid]))
            )
            frac = hits / len(members)
            if frac >= dominant_term_frac:
                warnings_out.append(
                    {"kind": "dominant-term", "topic": tid, "term": term,
                     "fraction": round(frac, 3),
                     "msg": f"{tid}: '{term}' fires on {hits}/{len(members)} "
                            f"({frac:.0%}) of its docs; topic depends on one "
                            f"term — consider adding diversifying matchers"}
                )

    return warnings_out


def write_coverage_report(
    docs: list[tuple[Path, dict[str, Any]]],
    doc_scores: dict[str, dict[str, int]],
    health_warnings: list[dict[str, Any]] | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "topic_map_report.json"
    rows = []
    unmatched: list[str] = []
    for _, doc in docs:
        scores = doc_scores[doc["id"]]
        topic_paths = derive_topic_paths(doc["id"], doc_scores)
        nonzero = sum(1 for v in scores.values() if v > 0)
        if not topic_paths["primary"]:
            unmatched.append(doc["id"])
        rows.append(
            {
                "id": doc["id"],
                "title": doc["title"],
                "theme": doc["theme"],
                "topics_hit": nonzero,
                "primary": topic_paths["primary"],
                "secondary": topic_paths["secondary"],
                "top_scores": dict(
                    sorted(scores.items(), key=lambda kv: -kv[1])[:5]
                ),
            }
        )
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "n_docs": len(docs),
                "unmatched_docs": unmatched,
                "health_warnings": health_warnings or [],
                "per_doc": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out_path


def main() -> int:
    docs = load_docs()
    print(f"[load] {len(docs)} corpus documents")
    tm, doc_scores = build_topic_map(docs)
    health_warnings = matcher_health_check(tm, doc_scores, docs)
    tm_path = write_topic_map(tm)
    rep_path = write_coverage_report(docs, doc_scores, health_warnings)
    n_topics = len(tm["topics"])
    avg_docs = sum(t["doc_count"] for t in tm["topics"].values()) / n_topics
    unmatched = [
        d["id"] for _, d in docs
        if not derive_topic_paths(d["id"], doc_scores)["primary"]
    ]
    print(f"[write] {tm_path}")
    print(f"[write] {rep_path}")
    print(f"[stats] {n_topics} topics; avg {avg_docs:.1f} docs per topic")
    print(f"[stats] unmatched docs (no topic_path): {len(unmatched)}")
    for d in unmatched:
        print(f"        - {d}")
    # Matcher health summary
    if health_warnings:
        by_kind: dict[str, int] = {}
        for w in health_warnings:
            by_kind[w["kind"]] = by_kind.get(w["kind"], 0) + 1
        kind_summary = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        print(f"[health] {len(health_warnings)} taxonomy warning(s): {kind_summary}")
        for w in health_warnings:
            print(f"  [{w['kind']:>14}] {w['msg']}")
    else:
        print("[health] no taxonomy warnings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
