# VMQ-MEM-07 - independent five-class evidence

- Generated (local): 2026-11-19 21:52:07 +1200
- Mode: fixture
- Command: plans\features\vmq-onto-01\evidence\mem07\harness\mem07.py --fixture --out plans\features\vmq-onto-01\evidence\mem07\fixture --code-root .
- Candidate: 0fce97a14338521a24d94f560e896ebcb19f9492
- Code root HEAD: ceceb4dedf96dc2f75d92abf9077422a0a78610c
- Product diff vs candidate: True
- Snapshot sha256: 6276d4b03c06fbf05770a86b62c1552352de591675958f03d0a13dcbbcee67fb
- Snapshot quick_check: ok; user_version: 48; messages: 376
- Chat: -1002661910336; current_year: 2026; years: {'2022': 68, '2023': 71, '2024': 71, '2025': 66, '2026': 100}
- Python: 3.12.0; sqlite: 3.42.0; sqlite-vec: 0.1.9; vector: {'vec_ok': False, 'vec_dim': None, 'sqlite_vec_off_reason': 'embed', 'sqlite_vec_loaded': True, 'vec_error': None}
- GraphRAG effective: enabled=True limit=10 source=settings_instance
- Diagnostics: records=186 lines=186 log_sha256=3f5fd580ec9daaac9c98e0bcbadb8fefb7e947c0d19f2e8d8a8e1549a399fc64 unexpected=0/0
- Stubs: embed_calls=1 generate_calls=36; socket_blocked=True

## Questions (auto policy)

| ID | class | template | expected years | delivered years | coverage anchor | coverage period | semantic old | chrono period | exact chrono | relevance | fabricated |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | H | напиши юмористический рассказ об основных шизах конфы | [2022, 2023, 2024, 2025, 2026] | {2022: 6, 2023: 6, 2024: 2, 2025: 4, 2026: 4} | 0.400 (22/55) | 1.000 (5/5) | 1.000 (4/4) | 0.818 (18/22) | 1.000 (22/22) | 1.000 (22/22) | 0.400 (8/20) |
| H2 | H | расскажи смешную историю про ремонт ванной | [2022] | {2022: 13, 2026: 11} | 0.929 (13/14) | 1.000 (1/1) | 1.000 (1/1) | 0.542 (13/24) | 1.000 (13/13) | 1.000 (24/24) | 0.364 (8/22) |
| R1 | R | перескажи, что происходило в чате в 2024 году | [2024] | {2024: 31, 2025: 5, 2026: 3} | 0.281 (9/32) | 1.000 (1/1) | 1.000 (1/1) | 0.795 (31/39) | 1.000 (9/9) | 0.795 (31/39) | 0.231 (9/39) |
| R2 | R | напомни, о чём говорили про собаку | [2024] | {2024: 5, 2025: 5} | 0.000 (0/14) | 1.000 (1/1) | 0.000 (0/1) | 0.500 (5/10) | n/a | 0.000 (0/10) | 1.000 (8/8) |
| R3 | R | что известно про основные шизы конфы? | [2022, 2023, 2024, 2025, 2026] | {2022: 6, 2023: 6, 2024: 2, 2025: 4, 2026: 4} | 0.400 (22/55) | 1.000 (5/5) | 1.000 (4/4) | 0.818 (18/22) | 1.000 (22/22) | 1.000 (22/22) | 0.400 (8/20) |
| R4 | R | что было с ремонтом ванной? | [2022] | {2022: 8, 2024: 4, 2026: 12} | 0.571 (8/14) | 1.000 (1/1) | 1.000 (1/1) | 0.333 (8/24) | 1.000 (8/8) | 0.792 (19/24) | 0.364 (8/22) |
| P1 | P | что за человек {P1}? что о нём известно за всё время? | [2022, 2023, 2024, 2025] | {2022: 15, 2023: 4, 2026: 6} | 0.225 (18/80) | 0.500 (2/4) | 0.500 (2/4) | 0.760 (19/25) | 1.000 (18/18) | 0.720 (18/25) | 0.348 (8/23) |
| P2 | P | какие истории и взгляды связаны с {P2}? | [2022, 2023, 2024, 2025] | {2024: 5, 2025: 5} | 0.125 (10/80) | 0.500 (2/4) | 0.500 (2/4) | 1.000 (10/10) | 1.000 (10/10) | 1.000 (10/10) | 1.000 (8/8) |
| C1 | C | из-за чего был конфликт на конфе? | [2023] | {2023: 12, 2026: 6} | 0.714 (10/14) | 1.000 (1/1) | 1.000 (1/1) | 0.667 (12/18) | 1.000 (10/10) | 0.556 (10/18) | 0.500 (8/16) |
| C2 | C | восстанови, из-за чего ругались в 2024 году | [2024] | {2024: 33, 2025: 1, 2026: 6} | 0.091 (2/22) | 1.000 (1/1) | 1.000 (1/1) | 0.825 (33/40) | 1.000 (2/2) | 0.050 (2/40) | 0.211 (8/38) |
| E1 | E | как менялось отношение чата к {E1_topic}? | [2023, 2026] | {2023: 8, 2024: 2, 2025: 5, 2026: 3} | 0.000 (0/29) | 1.000 (2/2) | 0.000 (0/1) | 0.444 (8/18) | n/a | 0.000 (0/18) | 0.500 (8/16) |
| E2 | E | кто с кем дружил и ссорился за всё время? | [2022, 2023, 2024, 2025, 2026] | {2024: 10, 2026: 14} | 0.000 (0/68) | 0.400 (2/5) | 0.000 (0/4) | 0.417 (10/24) | n/a | 0.000 (0/24) | 0.364 (8/22) |
| N1 | N | что сейчас с ремонтом ванной? | [2026] | {2022: 8, 2024: 4, 2026: 12} | 1.000 (11/11) | 1.000 (1/1) | n/a | 0.500 (12/24) | 1.000 (11/11) | 0.792 (19/24) | 0.364 (8/22) |
| N2 | N | как сейчас обстоят дела с собакой? | [2026] | {2024: 12, 2026: 6} | 0.455 (5/11) | 1.000 (1/1) | n/a | 0.333 (6/18) | 1.000 (5/5) | 0.833 (15/18) | 0.500 (8/16) |
| X1 | X | что сейчас с {X1_topic}? | [2024, 2026] | {2024: 12, 2026: 6} | 1.000 (2/2) | 1.000 (2/2) | 0.000 (0/1) | 0.667 (12/18) | 1.000 (2/2) | 0.000 (0/18) | 0.500 (8/16) |

## Classes (pooled)

| class | questions | coverage anchor | coverage period | semantic old | chrono period | exact chrono | relevance | fabricated |
|---|---|---|---|---|---|---|---|---|
| humor_story | H1,H2 | 0.507 (35/69) | 1.000 (6/6) | 1.000 (5/5) | 0.674 (31/46) | 1.000 (35/35) | 1.000 (46/46) | 0.381 (16/42) |
| plain_retelling | R1,R2,R3,R4 | 0.339 (39/115) | 1.000 (8/8) | 0.857 (6/7) | 0.653 (62/95) | 1.000 (39/39) | 0.758 (72/95) | 0.371 (33/89) |
| participant_characterization | P1,P2 | 0.175 (28/160) | 0.500 (4/8) | 0.500 (4/8) | 0.829 (29/35) | 1.000 (28/28) | 0.800 (28/35) | 0.516 (16/31) |
| conflict_reconstruction | C1,C2 | 0.333 (12/36) | 1.000 (2/2) | 1.000 (2/2) | 0.776 (45/58) | 1.000 (12/12) | 0.207 (12/58) | 0.296 (16/54) |
| relations_views_change | E1,E2 | 0.000 (0/97) | 0.571 (4/7) | 0.000 (0/5) | 0.429 (18/42) | n/a | 0.000 (0/42) | 0.421 (16/38) |

## Parity (MEM-04)

- ['H1', 'R3']: **pass**; reasons=[]
- ['H2', 'R4']: **fail**; reasons=['plain_worse:coverage.anchor', 'plain_worse:chrono_period', 'plain_worse:relevance']

## Controls (TIME-03/07/08)

- N1 historical: pass=True; old_rows=11; unlabeled_old=0; current_rows=12; reason=
- N2 historical: pass=True; old_rows=12; unlabeled_old=0; current_rows=6; reason=
- X1 historical: pass=True; mode=fallback_event_completed; old_present=True; new_present=True; old_labeled=True; reasons=[]

## TIME-07 within-candidate A/B

| ID | auto years | plan years | auto coverage | plan coverage | auto relevance | plan relevance |
|---|---|---|---|---|---|---|
| H1 | [2022, 2023, 2024, 2025, 2026] | [2022, 2023, 2025, 2026] | 0.400 (22/55) | 0.400 (22/55) | 1.000 (22/22) | 1.000 (22/22) |
| H2 | [2022, 2026] | [2022, 2024, 2025, 2026] | 0.929 (13/14) | 0.786 (11/14) | 1.000 (24/24) | 0.917 (22/24) |
| R1 | [2024, 2025, 2026] | [2024, 2025, 2026] | 0.281 (9/32) | 0.281 (9/32) | 0.795 (31/39) | 0.795 (31/39) |
| R2 | [2024, 2025] | [2024, 2025] | 0.000 (0/14) | 0.000 (0/14) | 0.000 (0/10) | 0.000 (0/10) |
| R3 | [2022, 2023, 2024, 2025, 2026] | [2022, 2023, 2025, 2026] | 0.400 (22/55) | 0.400 (22/55) | 1.000 (22/22) | 1.000 (22/22) |
| R4 | [2022, 2024, 2026] | [2022, 2024, 2026] | 0.571 (8/14) | 0.643 (9/14) | 0.792 (19/24) | 0.783 (18/23) |
| P1 | [2022, 2023, 2026] | [2022, 2023, 2024, 2026] | 0.225 (18/80) | 0.237 (19/80) | 0.720 (18/25) | 0.760 (19/25) |
| P2 | [2024, 2025] | [2022, 2024, 2025] | 0.125 (10/80) | 0.100 (8/80) | 1.000 (10/10) | 0.889 (8/9) |
| C1 | [2023, 2026] | [2022, 2023, 2024, 2026] | 0.714 (10/14) | 0.714 (10/14) | 0.556 (10/18) | 0.556 (10/18) |
| C2 | [2024, 2025, 2026] | [2024, 2025, 2026] | 0.091 (2/22) | 0.091 (2/22) | 0.050 (2/40) | 0.050 (2/40) |
| E1 | [2023, 2024, 2025, 2026] | [2023, 2025, 2026] | 0.000 (0/29) | 0.034 (1/29) | 0.000 (0/18) | 0.059 (1/17) |
| E2 | [2024, 2026] | [2024, 2026] | 0.000 (0/68) | 0.000 (0/68) | 0.000 (0/24) | 0.000 (0/24) |

## Old_Episode explicit probes

| probe | empty | messages | spans | sources | resolved | years |
|---|---|---|---|---|---|---|
| 2023 | False | 30 | 2 | 30 | 30 | {2023: 30} |
| 2024 | False | 30 | 2 | 30 | 30 | {2024: 30} |

## Builder discrepancy table (context only, not proof)

| Q | Builder class | Builder years | Builder coverage | Builder relevance | Our auto years | Our plan years | Our semantic old | Our relevance | Note |
|---|---|---|---|---|---|---|---|---|---|
| H1 | A1_creative_owner | {'base': {'2024': 1, '2026': 8}, 'historical': {'2023': 1, '2024': 1, '2026': 8}} | {'base': '2/5', 'historical': '3/5'} | {'base': '1/9', 'historical': 'not_recorded'} | {2022: 6, 2023: 6, 2024: 2, 2025: 4, 2026: 4} | {2022: 7, 2023: 7, 2025: 4, 2026: 4} | 1.000 (4/4) | 1.000 (22/22) | our auto/plan values are recorded; compare only after the fresh reissue |
| H2 | no_direct_humor_topic | None | None | None | {2022: 13, 2026: 11} | {2022: 11, 2024: 1, 2025: 1, 2026: 11} | 1.000 (1/1) | 1.000 (24/24) | no direct Builder equivalent |
| R1 | B_retell_different_question | {'base': {'2026': 10}} | {'base': '1/5'} | {'base': 'not_recorded'} | {2024: 31, 2025: 5, 2026: 3} | {2024: 31, 2025: 5, 2026: 3} | 1.000 (1/1) | 0.795 (31/39) | Builder B was all-years; ours is explicit 2024 |
| R2 | no_direct_yearless_topic | None | None | None | {2024: 5, 2025: 5} | {2024: 5, 2025: 5} | 0.000 (0/1) | 0.000 (0/10) | no direct Builder equivalent |
| R3 | A1P_plain_twin | {'base': {'2026': 10}, 'historical': {'2023': 1, '2024': 1, '2026': 8}} | {'base': '1/5', 'historical': '3/5'} | {'base': '2/10', 'historical': 'not_recorded'} | {2022: 6, 2023: 6, 2024: 2, 2025: 4, 2026: 4} | {2022: 7, 2023: 7, 2025: 4, 2026: 4} | 1.000 (4/4) | 1.000 (22/22) | same topic family as Builder A1P; wording/reference differ |
| R4 | no_direct_ordinary_twin | None | None | None | {2022: 8, 2024: 4, 2026: 12} | {2022: 9, 2024: 4, 2026: 10} | 1.000 (1/1) | 0.792 (19/24) | ordinary twin of H2 |
| P1 | C_person_profile | {'base': {'2026': 10}, 'historical': {'2023': 1, '2024': 1, '2026': 8}} | {'base': '1/5', 'historical': '3/5'} | {'base': '0/10', 'historical': 'not_recorded'} | {2022: 15, 2023: 4, 2026: 6} | {2022: 16, 2023: 2, 2024: 1, 2026: 6} | 0.500 (2/4) | 0.720 (18/25) | different runtime participant; same profile class |
| P2 | C_person_profile | {'historical_p1_p3': {'2023': 1, '2024': 1, '2026': 8}, 'historical_p2': {'2024': 1, '2025': 1, '2026': 8}} | {'historical_p1_p3': '3/5', 'historical_p2': '3/5'} | {'historical': 'not_recorded'} | {2024: 5, 2025: 5} | {2022: 1, 2024: 3, 2025: 5} | 0.500 (2/4) | 1.000 (10/10) | different runtime participant |
| C1 | D_conflict_2023 | {'base': {'2025': 1, '2026': 8}, 'historical': {'2023': 1, '2026': 8}} | {'base': '0/1', 'historical': '1/1'} | {'base': '0/9', 'historical': 'not_recorded'} | {2023: 12, 2026: 6} | {2022: 1, 2023: 11, 2024: 1, 2026: 5} | 1.000 (1/1) | 0.556 (10/18) | ours is yearless conference conflict; Builder D was explicit 2023 |
| C2 | no_direct_conflict_2024 | None | None | None | {2024: 33, 2025: 1, 2026: 6} | {2024: 33, 2025: 1, 2026: 6} | 1.000 (1/1) | 0.050 (2/40) | explicit 2024 conflict; no direct Builder row |
| E1 | E_relations_years | {'base': {'2026': 10}} | {'base': '1/5'} | {'base': '5/10'} | {2023: 8, 2024: 2, 2025: 5, 2026: 3} | {2023: 9, 2025: 5, 2026: 3} | 0.000 (0/1) | 0.000 (0/18) | topic-specific attitude question; Builder E was generic |
| E2 | E_relations_years | {'base': {'2026': 10}} | {'base': '1/5'} | {'base': '5/10'} | {2024: 10, 2026: 14} | {2024: 10, 2026: 14} | 0.000 (0/4) | 0.000 (0/24) | friendship/quarrel wording; Builder E was generic |

## Assertions

| ID | Status | Expected | Actual (counts/hashes only) |
|---|---|---|---|
| MEM07-SNAPSHOT | **pass** | quick_check=ok, user_version=48, archive>=1, sha stable | `{"quick_check": "ok", "user_version": 48, "messages": 376, "readonly": true}` |
| MEM07-QUESTIONS | **pass** | 12 matrix questions, >=2 per class, exact owner query, 3 controls | `{"matrix": 12, "per_class": {"H": 2, "R": 4, "P": 2, "C": 2, "E": 2}, "owner_query": true, "controls": ["N1", "N2", "X1"]}` |
| MEM07-CONFIG | **pass** | settings instance true, facts_limit>0, unified retrieval path for every matrix question | `{"graph_rag_enabled": true, "graph_rag_facts_limit": 10, "config_source": "settings_instance", "not_unified": []}` |
| MEM07-REFERENCES | **pass** | every matrix question has archive-derived anchors | `{"without_reference": []}` |
| MEM07-TRACE | **pass** | auto policy unified retrieve + Writer payload for every matrix question | `{"without_trace": []}` |
| MEM07-METRICS | **pass** | exact + semantic/chrono metrics with explicit denominators for every matrix question | `{"missing_denominators": []}` |
| MEM07-PARITY | **pass** | parity pairs computed from numbers (result stored separately) | `{"pairs": [{"pair": ["H1", "R3"], "result": "pass", "ordinary_no_worse": true, "reasons": [], "coverage.anchor": {"humor": 0.4, "plain": 0.4}, "coverage.period": {"humor": 1.0, "plain": 1.0}, "semantic.old_coverage": {"humor": 1.0, "plain": 1.0}, "chrono_period": {"humor": 0.8181818181818182, "plain": 0.8181818181818182}, "relevance": {"humor": 1.0, "plain": 1.0}, "fabricated": {"humor": 0.4, "plain": 0.4}}, {"pair": ["H2", "R4"], "result": "fail", "ordinary_no_worse": false, "reasons": ["plain_worse:coverage.anchor", "plain_worse:chrono_period", "plain_worse:relevance"], "coverage.anchor": {"` |
| MEM07-CONTROLS | **pass** | N1/N2 historical negative has old rows and labels; X1 historical has old+new | `{"missing": [], "X1_pass": true, "detail": {"N1": {"old_rows": 11, "archive_marked": 0, "date_labeled": 3, "unlabeled_old": 0, "current_rows": 12, "pass": true, "reason": ""}, "N2": {"old_rows": 12, "archive_marked": 0, "date_labeled": 2, "unlabeled_old": 0, "current_rows": 6, "pass": true, "reason": ""}, "X1": {"old_present": true, "new_present": true, "old_labeled": true, "pass": true, "reasons": [], "mode": "fallback_event_completed"}}}` |
| MEM07-NO-TEXT | **pass** | no message/fact text, resolved personal query or fixture secret in output | `{"forbidden_fields": [], "secret_hits": []}` |
| MEM07-DIAGNOSTICS | **pass** | bounded log histogram + sha256; no unexpected errors/tracebacks | `{"records": 186, "lines": 186, "log_sha256": "3f5fd580ec9daaac9c98e0bcbadb8fefb7e947c0d19f2e8d8a8e1549a399fc64", "categories": {"embed_stub": 2, "other": 1, "readonly_write": 111, "rerank_stub": 72}, "exception_types": {"OperationalError": 111}, "unexpected_errors": 0, "unexpected_tracebacks": 0}` |
| MEM07-PRIVACY | **pass** | no personal display-name value in output | `{"hit_count": 0}` |
| MEM07-BUILDER-DIFF | **pass** | numeric Builder discrepancy table with sources and our values | `{"rows": 12}` |
| MEM07-OLDEP-2023 | **pass** | explicit 2023 Old_Episode non-empty, spans and resolved source refs, only target year | `{"empty": false, "messages": 30, "spans": 2, "resolved_sources": 30, "years": {"2023": 30}}` |
| MEM07-OLDEP-2024 | **pass** | explicit 2024 Old_Episode non-empty, spans and resolved source refs, only target year | `{"empty": false, "messages": 30, "spans": 2, "resolved_sources": 30, "years": {"2024": 30}}` |
| MEM07-READONLY | **pass** | snapshot sha256 unchanged | `{"before": "6276d4b03c06fbf05770a86b62c1552352de591675958f03d0a13dcbbcee67fb", "after": "6276d4b03c06fbf05770a86b62c1552352de591675958f03d0a13dcbbcee67fb"}` |
| MEM07-NO-NETWORK | **pass** | LLM/embed stubs raised; socket egress blocked | `{"network_blocked": true, "stub_embed_calls": 1, "stub_generate_calls": 36}` |

## Limitations

- Read-only snapshot; not the live process.
- LLM/embedding clients are failing stubs; no generated answer text.
- Vector leg is compat_not_proven when the embed stub fails; lexical path is measured, not semantic retrieval.
- Product block builders (_build_rag_block, _build_old_episodes) and canonical build_messages are used; the full L1 turn composer and system prompt are out of scope.
- One chat, one run per configuration; no statistical generalization.
- TIME-07 is within-candidate A/B (auto vs auto_plan), not a cross-release baseline.
- Fabricated-link metric covers payload/bundle refs, not generated prose.

## Note

This harness is evidence tooling. It does not change product code, maps or statuses;
it does not claim VERIFIED or product quality by itself. Text of messages/facts and
personal display names are not written; only ids, years, counts, hashes and codes.

