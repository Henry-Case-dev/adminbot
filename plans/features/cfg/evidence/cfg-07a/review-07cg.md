# Review CFG-07CG — независимое ревью волны 07C-G (egress-словарь + тест-гварды)

- **Вердикт: Approved** (скоуп лейна; коммит-биндинг и ledger-статусы — оркестратор после коммита).
- **Ревьюер:** REV-CFG07CG (read-only), 21.10.2026.
- **Кандидат:** незакоммиченное дерево поверх `4d79182a` (HEAD; база прод-линии 2.58.102 = `a3535b68`).
- **Волна-диф подтверждён точно:** `services/public_speech_guard.py` (новый), `tests/test_cfg07_egress_dictionary.py` (новый), evidence `07cg-dictionary.md` / `07cg-reuse-audit.md` / `07cg-tests.txt`, `plans/features/cfg/requirements-map.json` (+53/−6). W3-фриз цел: `factcheck_prompts.py`/`prompt_migrations.py` вне диффа. Прочий грязный фон дерева (asap8/samples-ux/owner-файлы/tools-скретч) — ДО-волновой, в коммит волны не брать.

## Acceptance ledger (скоуп лейна)

| Пункт | Статус | Доказательство |
|---|---|---|
| Словарь: 4 honesty-класса, 107 фраз из 29 живых пулов + 6 PC-примеров | VERIFIED | runtime-подсчёт 2+31+71+3=107; identity-механизм = прямые ссылки-объекты пулов, закреплён `test_honesty_classes_reference_live_pools` |
| FORBIDDEN: 14 семей / 42 маркера, границы слов | VERIFIED | подсчёт 14/42; корпус MB-01..09/13..17 покрыт (машинные MB-10/11/12 вне скоупа → 07D.5, заявлено честно); «история ии» не флагается — тест |
| overclaim 07D.2: 3 паттерна; админ-маркеры 15 | VERIFIED | тесты ×4 ловят / ×5 не ловят; structural disjoint 107 фраз |
| 07A.3 гварды (моки v2) | VERIFIED | 67/67 green; miss-маршрут возвращается ДО retrieval (factcheck_orchestrator.py:347–357), платная проверка не стартует (`svc.check_calls==[]`) |
| 07A.5 гварды | VERIFIED | admin-контекст разрешает честное объяснение, backstage флагается, checkup-жанр цел |
| 07D.1 гварды (инженерная часть) | VERIFIED | ON чист / OFF (gates и toggle) → skip_reason=humor_disabled; сарказм цел. Live-глазами владельца — вне гейтов (standing rule, owner_live_checks §6) |
| 07D.2 | VERIFIED | «проверил всё в интернете» ловится; честные формулировки и техсправка админу — чисты |
| 07A.F reuse-аудит | VERIFIED | матрица бьётся с реальным git-состоянием (Core байт-цел, каноны не тронуты, suppress=коммит 6388899d, route-coverage 18 / 07A-2 38 / humor W4 / F1 51 — green); хвост 07C.1–.6 прописан отдельной работой |
| Ложные срабатывания | VERIFIED | PC 12/12 чисты, SF чисты, структурный скан 202 canned-текстов всех пулов + renderer/checkup/humor/Core — 0 флагов; маркеры ловятся только на грязных репликах |
| Тесты/гейты | VERIFIED | новый файл 67 CONTRACT; фокус воспроизведён: 255 passed / 0 failed (точно по брифу; +W6 = 261/0); plan-гейт 0 errors (EXIT 0); sha256 3 артефактов = карте (686f6ca7/bab89d8a/b2f8f0ae) |
| Строки карты 07A.3/.5/07D.1/.2/.F | PENDING (оговорено) | ledger-долг оркестратора после коммита, не блокер |

## Наблюдения (NONBLOCKING, в хвост 07C.1–.6 / бэклог)

1. `test_attribution_miss...`: `agg.searches == []` — пустышка (SpyAggregator не инжектится в `run_factcheck`). Поведение обеспечено структурой кода (return до поиска) и CFG-06 attribution-тестами; ассерт либо связать (инжект `service.aggregator`), либо убрать.
2. Инверсный порядок «весь интернет проверил» (глагол после) не ловится закрытым сетом — сознательно закрытый список; расширять только с источником (07A.7).
3. `honest_failure_is_allowed` покрывает только refusal/unavailability: PC-01 и «Недостаточно данных» (honest_limitation) им не пропускаются. Хвостовому guard'у на delivery-швах нужно определить allow-путь для honest_limitation, иначе честное ограничение будет резаться.
4. Маркер «в логах видно» (MB-01) флагает и легитимную техсправку админу — по корпусу так и задумано; развязка через `is_explicit_admin_context` — задача runtime-guard'а хвоста.

## Биндинг

Кандидат = worktree 21.10.2026 поверх `4d79182a` (2.58.102 + F1-коммит). После коммита оркестратору: strict-gate `--stage review/release` с фактическим SHA, фиксация статусов строк карты и точный список файлов коммита (только волна).
