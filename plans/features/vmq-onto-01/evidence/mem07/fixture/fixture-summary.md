# VMQ-MEM-07 - independent five-class evidence

- Generated (local): 2026-11-19 21:07:45 +1200
- Mode: fixture
- Command: plans\features\vmq-onto-01\evidence\mem07\harness\mem07.py --fixture --out plans\features\vmq-onto-01\evidence\mem07\fixture --code-root .
- Candidate: 0fce97a14338521a24d94f560e896ebcb19f9492
- Code root HEAD: d4abf5bc51d108eacf8e1b621f661ce6a84b85e0
- Product diff vs candidate: True
- Snapshot sha256: be686f390d22caa374a4106d9294924344f49d9c818d360332934db8e0dc5661
- Snapshot quick_check: ok; user_version: 48; messages: 376
- Chat: -1002661910336; current_year: 2026; years: {'2022': 68, '2023': 71, '2024': 71, '2025': 66, '2026': 100}
- Python: 3.12.0; sqlite: 3.42.0; sqlite-vec: 0.1.9; vector: {'vec_ok': False, 'vec_dim': None, 'sqlite_vec_off_reason': 'embed', 'sqlite_vec_loaded': True, 'vec_error': None}
- Stubs: embed_calls=1 generate_calls=33; socket_blocked=True

## Questions (auto policy)

| ID | class | template | expected years | delivered years | coverage anchor | coverage period | chrono | relevance | fabricated |
|---|---|---|---|---|---|---|---|---|---|
| H1 | H | напиши юмористический рассказ об основных шизах конфы | [2022, 2023, 2024, 2025, 2026] | {2022: 6, 2023: 6, 2024: 2, 2025: 4, 2026: 4} | 0.400 (22/55) | 1.000 (5/5) | 1.000 (22/22) | 0.545 (12/22) | 0.400 (8/20) |
| H2 | H | расскажи смешную историю про ремонт ванной | [2022] | {2022: 13, 2026: 11} | 0.929 (13/14) | 1.000 (1/1) | 1.000 (13/13) | 0.583 (14/24) | 0.364 (8/22) |
| R1 | R | перескажи, что происходило в чате в 2024 году | [2024] | {2024: 31, 2025: 5, 2026: 3} | 0.281 (9/32) | 1.000 (1/1) | 1.000 (9/9) | 0.769 (30/39) | 0.231 (9/39) |
| R2 | R | напомни, о чём говорили про собаку | [2024] | {2024: 5, 2025: 5} | 0.000 (0/14) | 1.000 (1/1) | n/a | 0.000 (0/10) | 1.000 (8/8) |
| R3 | R | что известно про основные шизы конфы? | [2022, 2023, 2024, 2025, 2026] | {2022: 6, 2023: 6, 2024: 2, 2025: 4, 2026: 4} | 0.400 (22/55) | 1.000 (5/5) | 1.000 (22/22) | 0.545 (12/22) | 0.400 (8/20) |
| R4 | R | что было с ремонтом ванной? | [2022] | {2022: 8, 2024: 4, 2026: 12} | 0.571 (8/14) | 1.000 (1/1) | 1.000 (8/8) | 0.583 (14/24) | 0.364 (8/22) |
| P1 | P | что за человек {P1}? что о нём известно за всё время? | [2022, 2023, 2024, 2025] | {2022: 15, 2023: 4, 2026: 6} | 0.225 (18/80) | 0.500 (2/4) | 1.000 (18/18) | 0.600 (15/25) | 0.348 (8/23) |
| P2 | P | какие истории и взгляды связаны с {P2}? | [2022, 2023, 2024, 2025] | {2024: 5, 2025: 5} | 0.125 (10/80) | 0.500 (2/4) | 1.000 (10/10) | 0.000 (0/10) | 1.000 (8/8) |
| C1 | C | из-за чего был конфликт на конфе? | [2023] | {2023: 12, 2026: 6} | 0.714 (10/14) | 1.000 (1/1) | 1.000 (10/10) | 0.444 (8/18) | 0.500 (8/16) |
| C2 | C | восстанови, из-за чего ругались в 2024 году | [2024] | {2024: 33, 2025: 1, 2026: 6} | 0.091 (2/22) | 1.000 (1/1) | 1.000 (2/2) | 0.000 (0/40) | 0.211 (8/38) |
| E1 | E | как менялось отношение чата к {E1_topic}? | [2023, 2026] | {2023: 8, 2024: 2, 2025: 5, 2026: 3} | 0.000 (0/29) | 1.000 (2/2) | n/a | 0.000 (0/18) | 0.500 (8/16) |
| E2 | E | кто с кем дружил и ссорился за всё время? | [2022, 2023, 2024, 2025, 2026] | {2024: 10, 2026: 14} | 0.000 (0/68) | 0.400 (2/5) | n/a | 0.000 (0/24) | 0.364 (8/22) |
| N1 | N | что сейчас с ремонтом ванной? | [2026] | {2022: 8, 2024: 4, 2026: 12} | 1.000 (11/11) | 1.000 (1/1) | 1.000 (11/11) | 0.583 (14/24) | 0.364 (8/22) |
| N2 | N | как сейчас обстоят дела с собакой? | [2026] | {2024: 12, 2026: 6} | 0.455 (5/11) | 1.000 (1/1) | 1.000 (5/5) | 0.444 (8/18) | 0.500 (8/16) |
| X1 | X | что сейчас с {X1_topic}? | [2024, 2026] | {2024: 12, 2026: 6} | 1.000 (2/2) | 1.000 (2/2) | 1.000 (2/2) | 0.000 (0/18) | 0.500 (8/16) |

## Classes (pooled)

| class | questions | coverage anchor | coverage period | chrono | relevance | fabricated |
|---|---|---|---|---|---|---|
| humor_story | H1,H2 | 0.507 (35/69) | 1.000 (6/6) | 1.000 (35/35) | 0.565 (26/46) | 0.381 (16/42) |
| plain_retelling | R1,R2,R3,R4 | 0.339 (39/115) | 1.000 (8/8) | 1.000 (39/39) | 0.589 (56/95) | 0.371 (33/89) |
| participant_characterization | P1,P2 | 0.175 (28/160) | 0.500 (4/8) | 1.000 (28/28) | 0.429 (15/35) | 0.516 (16/31) |
| conflict_reconstruction | C1,C2 | 0.333 (12/36) | 1.000 (2/2) | 1.000 (12/12) | 0.138 (8/58) | 0.296 (16/54) |
| relations_views_change | E1,E2 | 0.000 (0/97) | 0.571 (4/7) | n/a | 0.000 (0/42) | 0.421 (16/38) |

## Parity (MEM-04)

- ['H1', 'R3']: **pass**; reasons=[]
- ['H2', 'R4']: **fail**; reasons=['plain_worse:coverage.anchor']

## Controls (TIME-03/07/08)

- N1: pass=True; old_rows=12; unlabeled_old=0; current_rows=12
- N2: pass=True; old_rows=12; unlabeled_old=0; current_rows=6
- X1: pass=True; mode=runtime_changed_position; old_present=True; new_present=True; old_labeled=True

## TIME-07 within-candidate A/B

| ID | auto years | plan years | auto coverage | plan coverage | auto relevance | plan relevance |
|---|---|---|---|---|---|---|
| H1 | [2022, 2023, 2024, 2025, 2026] | [2022, 2023, 2025, 2026] | 0.400 (22/55) | 0.400 (22/55) | 0.545 (12/22) | 0.545 (12/22) |
| H2 | [2022, 2026] | [2022, 2024, 2025, 2026] | 0.929 (13/14) | 0.786 (11/14) | 0.583 (14/24) | 0.583 (14/24) |
| R1 | [2024, 2025, 2026] | [2024, 2025, 2026] | 0.281 (9/32) | 0.281 (9/32) | 0.769 (30/39) | 0.769 (30/39) |
| R2 | [2024, 2025] | [2024, 2025] | 0.000 (0/14) | 0.000 (0/14) | 0.000 (0/10) | 0.000 (0/10) |
| R3 | [2022, 2023, 2024, 2025, 2026] | [2022, 2023, 2025, 2026] | 0.400 (22/55) | 0.400 (22/55) | 0.545 (12/22) | 0.545 (12/22) |
| R4 | [2022, 2024, 2026] | [2022, 2024, 2026] | 0.571 (8/14) | 0.643 (9/14) | 0.583 (14/24) | 0.609 (14/23) |
| P1 | [2022, 2023, 2026] | [2022, 2023, 2024, 2026] | 0.225 (18/80) | 0.237 (19/80) | 0.600 (15/25) | 0.600 (15/25) |
| P2 | [2024, 2025] | [2022, 2024, 2025] | 0.125 (10/80) | 0.100 (8/80) | 0.000 (0/10) | 0.000 (0/9) |
| C1 | [2023, 2026] | [2022, 2023, 2024, 2026] | 0.714 (10/14) | 0.714 (10/14) | 0.444 (8/18) | 0.444 (8/18) |
| C2 | [2024, 2025, 2026] | [2024, 2025, 2026] | 0.091 (2/22) | 0.091 (2/22) | 0.000 (0/40) | 0.000 (0/40) |
| E1 | [2023, 2024, 2025, 2026] | [2023, 2025, 2026] | 0.000 (0/29) | 0.034 (1/29) | 0.000 (0/18) | 0.000 (0/17) |
| E2 | [2024, 2026] | [2024, 2026] | 0.000 (0/68) | 0.000 (0/68) | 0.000 (0/24) | 0.000 (0/24) |

## Assertions

| ID | Status | Expected | Actual (counts/hashes only) |
|---|---|---|---|
| MEM07-SNAPSHOT | **pass** | quick_check=ok, user_version=48, archive>=1, sha stable | `{"quick_check": "ok", "user_version": 48, "messages": 376, "readonly": true}` |
| MEM07-QUESTIONS | **pass** | 12 matrix questions, >=2 per class, exact owner query, 3 controls | `{"matrix": 12, "per_class": {"H": 2, "R": 4, "P": 2, "C": 2, "E": 2}, "owner_query": true, "controls": ["N1", "N2", "X1"]}` |
| MEM07-REFERENCES | **pass** | every matrix question has archive-derived anchors | `{"without_reference": []}` |
| MEM07-TRACE | **pass** | auto policy product retrieve + Writer payload for every matrix question | `{"without_trace": []}` |
| MEM07-METRICS | **pass** | four metrics with explicit denominators for every matrix question | `{"missing_denominators": []}` |
| MEM07-PARITY | **pass** | parity pairs computed from numbers (result stored separately) | `{"pairs": [{"pair": ["H1", "R3"], "result": "pass", "ordinary_no_worse": true, "reasons": [], "coverage.anchor": {"humor": 0.4, "plain": 0.4}, "coverage.period": {"humor": 1.0, "plain": 1.0}, "chrono": {"humor": 1.0, "plain": 1.0}, "relevance": {"humor": 0.5454545454545454, "plain": 0.5454545454545454}, "fabricated": {"humor": 0.4, "plain": 0.4}}, {"pair": ["H2", "R4"], "result": "fail", "ordinary_no_worse": false, "reasons": ["plain_worse:coverage.anchor"], "coverage.anchor": {"humor": 0.9285714285714286, "plain": 0.5714285714285714}, "coverage.period": {"humor": 1.0, "plain": 1.0}, "chrono":` |
| MEM07-CONTROLS | **pass** | N1/N2 negative computed, X1 executed or explicitly not_executed | `{"missing": [], "X1_pass": true, "X1_reference": null}` |
| MEM07-NO-TEXT | **pass** | no message/fact text, resolved personal query or fixture secret in output | `{"forbidden_fields": [], "secret_hits": []}` |
| MEM07-READONLY | **pass** | snapshot sha256 unchanged | `{"before": "be686f390d22caa374a4106d9294924344f49d9c818d360332934db8e0dc5661", "after": "be686f390d22caa374a4106d9294924344f49d9c818d360332934db8e0dc5661"}` |
| MEM07-NO-NETWORK | **pass** | LLM/embed stubs raised; socket egress blocked | `{"network_blocked": true, "stub_embed_calls": 1, "stub_generate_calls": 33}` |

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

