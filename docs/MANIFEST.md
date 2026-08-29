# docs/ — MANIFEST

Project documentation. Two kinds: dated handover snapshots
(`handover_claude_code_YYYY-MM-DD.md`) that record implementation
state at a point in time, and the governance subdirectories — ADRs,
lessons learned, implementation plans, test specifications, and
persona-scoped guides.

| ID | File | Description |
|---|---|---|
| 0001 | [handover_claude_code_2026-05-15.md](handover_claude_code_2026-05-15.md) | Implementation handover snapshot, 2026-05-15. Superseded by the 05-16 doc — read only for diff context. |
| 0002 | [handover_claude_code_2026-05-16.md](handover_claude_code_2026-05-16.md) | Implementation handover snapshot, 2026-05-16. Adds prompt caching (commit `f7e47a1`). |
| 0003 | [handover_claude_code_2026-05-26.md](handover_claude_code_2026-05-26.md) | Implementation handover snapshot, 2026-05-26. Latest implementation reality. |

## Subdirectories

| ID | Path | Description |
|---|---|---|
| S0001 | [decisions/](decisions/) | MADR 4.0 architecture decision records — see [decisions/MANIFEST.md](decisions/MANIFEST.md). 16 ADRs covering runtime model choice, retrieval strategy, demo scope, STT/TTS, dashboard, caching, ID format, parsing strategy, date validation, taxonomy authoring, topic_paths derivation, and register selection. |
| S0002 | [lessons/](lessons/) | 5-Why root-cause analyses for things that surprised us — see [lessons/MANIFEST.md](lessons/MANIFEST.md). 10 lessons covering cache calculation, SDK behavior, dotenv gotcha, Streamlit cache, unused artifacts, mixed CSV formats, encoding fallback, body normaliser stratification, substring matching, and ID typos. |
| S0003 | [implementation-plans/](implementation-plans/) | Phase-aligned implementation plans — see [implementation-plans/MANIFEST.md](implementation-plans/MANIFEST.md). 7 plans for runtime app, web UI, embedding audit, biography ingest, book corpus addition, voice/TTS integration, and topic-map evolution process. |
| S0004 | [test-specs/](test-specs/) | Verification specifications for each layer — see [test-specs/MANIFEST.md](test-specs/MANIFEST.md). 5 specs for generator contract, topic-map matchers, topic_paths derivation, voice card protocol, and end-to-end smoke. |
| S0005 | [guides/](guides/) | Persona-scoped guides — see [guides/MANIFEST.md](guides/MANIFEST.md). 4 guides for end users, reviewers, admins, and project managers. |

## Reading order by audience

**New engineer / contributor.**
[handover_claude_code_2026-05-26.md](handover_claude_code_2026-05-26.md)
→ [PROJECT.md](../PROJECT.md) → relevant ADRs in [decisions/](decisions/)
→ relevant plans in [implementation-plans/](implementation-plans/) →
test specs in [test-specs/](test-specs/).

**Reviewer / curator.**
[guides/GUIDE-reviewer.md](guides/GUIDE-reviewer.md)
→ [PROJECT.md](../PROJECT.md) §3-§7 for context →
[corpus/voice/voice_card.md](../corpus/voice/voice_card.md) +
[corpus/voice/topic_map.json](../corpus/voice/topic_map.json).

**Project manager / FLP lead.**
[guides/GUIDE-manager.md](guides/GUIDE-manager.md)
→ [implementation-plans/MANIFEST.md](implementation-plans/MANIFEST.md)
for roadmap.

**End user.**
[guides/GUIDE-end-user.md](guides/GUIDE-end-user.md) only.

**Operator / admin.**
[guides/GUIDE-admin.md](guides/GUIDE-admin.md)
→ [PROJECT.md](../PROJECT.md) §7 + §11.
