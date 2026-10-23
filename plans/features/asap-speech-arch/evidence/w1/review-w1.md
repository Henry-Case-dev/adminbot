# REV-ASAP-W1 — независимое ревью W1-волны asap-speech-arch

**Вердикт по слайсам:** P0-C **VERIFIED** · P0-D **VERIFIED** · P0-E **VERIFIED** · P0-F **VERIFIED** · P0-G **VERIFIED** · P0-A **PENDING-W2 (корректно)** · P0-B **PENDING-W2 (корректно)** · INIT-LIVE/MIGR/REPORT/TESTS-строки — вне W1 (W2/W3).
**Итог лейна: Approved** (W1-фабрики + тесты + evidence). Поезд 2.58.111 — разрешён; полный epic НЕ закрыт (runtime-строки PENDING до W2/W3).

**Кандидат:** коммиты 700f762c → 809a4fac → d0b84d84 → 0f3ed53a → beb3f272; HEAD == beb3f272 (линейная цепочка, работа == кандидат). Карта: candidate 0f3ed53a, strict_evidence=true, slice_graph_path задан.

## Байт-точность (воспроизведено независимо, Python-сверка против снапшота)

- §3.2 Core full == `PERSONALITY_CORE_FULL_TEXT` (sha12 2ab417d11404, 1925 c) — точное совпадение.
- §3.3 Core compact == `PERSONALITY_CORE_COMPACT_TEXT` (9e6a4ec8b1ea, 556 c) — точное.
- §3.4 `EXPRESSION_HEADER` (7d16e6537563), `EXPRESSION_FOOTER`, режимы off/occasional/frequent — точные, побуквенно прежние.
- §3.1 вербализатор: константа be03964322aa (1982 c); diff против fence = РОВНО одна добавленная строка data-reader (P0A-RISK, разрешено владельцем: JSON-пакет «если передан», поля user_question/facts/answer_outline/limitations). Иных отклонений нет.
- §3.6: `_DIRECT_TOOL_PHASE_ROLE_W1` == fence (bec66d4edfab), точный substring `CHAT_SYSTEM_PROMPT`; diff vs `PREV_CHAT_W1_SYSTEM_PROMPT` = ровно замена ролевого блока (СИСТЕМНАЯ РОЛЬ/ПРИОРИТЕТЫ/ПРАВИЛА ОФОРМЛЕНИЯ/АНТИ-БОТ/АСИММЕТРИЯ сняты), tool/context-контракты — равные блоки байт-в-байт.
- §3.7: `_DIRECT_L1_PARTICIPATION_W1` == fence (2d37e32c6847), substring L1-канона; «ФОРМА УЧАСТИЯ» отсутствует; JSON-схема/поля целы.
- Мета-утечки: SOUL-16/«Выражение владельца»/owner_setting/«токсичный бот-абьюзер» в model-facing канонах отсутствуют. «СИСТЕМНАЯ РОЛЬ» в L1/factcheck-вербализаторе — пре-существующая жанровая структура (не §3.6-блок), ТЗ её не трогало.
- Вербализатор без личности/мата/типографики/форматных правил — подтверждено сканом.

## ДОП-2 п.4 / ДОП-1

Семантические таблицы на месте: core-full (7 строк), core-compact (8), verbalizer (9), tool-phase (9), l1 (8), expression (7), factcheck (5) — каждый удалённый фрагмент с обоснованием (дублирование/конфликт/перенос); удаление ПРИОРИТЕТЫ-1..4 и «верь более свежему» имеет явный перенос в §3.6-блоки. Примитивизации нет: v3 Core = авторский текст владельца байт-в-байт; якоря токсичности/цинизма/абсурда/непристойного юмора в §3.2 подтверждены лично («резким, злым, циничным и неприличным», «непристойный юмор», «абсурдное мышление»).

## Лестницы / FACTORY_SET / миграции

- FACTORY_SET воспроизведён независимым путём: ручной пересчёт формулы по `factory_texts()` = fd4e88754749 (= реестр); симуляция до-W1 (6 блоков на PREV-байты) = 553a281fe2fd; changed == ровно 6; sha12 всех пар совпали с README (включая W0-хеши d0ef0d376fc3/0fe9680ba280/ace6246bd360). Метки 6 канонов = заявленным (asap-core-*-v3, l2-writer-w1, direct-toolphase-w1, l1-planner-w1, factcheck-verbalizer-w1).
- Ступени PREV_*_W1 + ROLLBACK на 2.58.110 в prompt_migrations подтверждены; супerseded-core v1+v2: `core_selection` гасит прежние заводские байты на фабрику, кастом владельца не подменяется (тест).
- `owner_preserve_core_full_patch`: снимает ТОЛЬКО v2-ремарку «**Важно:**…» и точечные «см. SOUL-NN»; остальное байт-в-байт; v1/v2 байты уводит superseded-гвард; идемпотентен, не бросает. Применение к реальному rev6 f59ba0f42a48 — честно отложено на W2 (P0-B).

## Тесты

- test_asap_w1_semantics.py: **21 passed** (я запускал). Ассерты защищают контракт владельца: fence-сверка против ЖИВОГО снапшота (не копий), ровно эффективная ветка Expression (count «- Мат:» == 1, чужие ветки отсутствуют), легаси mode-блоки не подтягиваются при плане, verbalizer без identity/мата/форматов, tool-phase без повторов Core/Expression, парсер L1D под реальными именами (reply_binding_requested = совместная валидность; fallback без доставки), owner-patch/лестницы/фабрика-vs-active.
- Related (13 файлов, venv): **327 passed** — mca_expression/expression isolation, verbilizer modes, direct_chat_prompts (W1-эталон построен независимой композицией + байт-сверка PREV-слепка), soul1 factory/composer/doc, l1d contract, outgoing_guard, payload_builder, prompt_migrations, composer parity OFF.
- Runtime-дамп direct-runtime-assembly-w1.txt: P1/P2/P5b = новый канон (с data-reader-строкой), P4 = «ВЫБОР УЧАСТИЯ», P5a machine-стадия без характера; identity-маркеры только в P3.

## Полный набор / 7 failed

**Полный набор ревьюером исполнен на точном кандидате (HEAD beb3f272): 7 failed, 15181 passed, 39 skipped за 733 c** (лог: OPENCODE_WORKFLOW_SCRATCH/rev-w1/full-suite.txt). 7 failed = test_asap7_direct_settings (2: v35 DDL idempotency, backup-guard) + test_t5150_startup_migrations (5: DDL window/lock/retry/chain/guard) — **идентичный набор воспроизведён мной же на чистой базе 3b60887c** (worktree, до-W1): локальная схема v37 vs тест-ожидания v35; схемный долг, с речью W1 не связан; W1 не добавил ни одного отказа. Расхождение с лейн-отчётом (15180 vs 15181) — в пределах счётной погрешности отчёта, набор отказов совпадает байт-в-байт. Дополнительная независимая сетка PKG-111 (pins24 868p + офлайн-агрегат + целевые наборы, прецедент 107/108/109) остаётся плановым гвардом релиза.

## Гейты и гигиена

- plan asap-speech-arch EXIT 0 (120 inventory, strict); review P0-C/E/F/G EXIT 0 (воспроизведено); review P0-A/B EXIT 1 по PENDING-строкам ARCH-ADR / P0B-OWNER — обе genuinely runtime/W2-обязательства, классификация PENDING корректна. soul-1/cfg/asap8 plan EXIT 0 — карты не сломаны.
- Дифф == заявленным 26 файлам (5 services + 20 тестов + планы); чужие незакоммиченные изменения (workflow_state.md, owner_live_checks.md, cfg-06 json, node_modules, _upd.py) в коммиты не захвачены. Секрет-скан диффа: 0 попаданий.

## Риски / nonblocking

1. **Kill-switch SMART_VERBALIZER_MODES_ENABLED=0** (P3 дампа) отдаёт legacy-канон R1023 с identity — пре-существующий документированный аварийный путь (реестр: «OFF → legacy PREV-канон», дефолт ON), вне зоны W1. NONBLOCKING; переаттестация OFF-ветки — в W2-протокол (README §Границы).
2. ARCH-ADR (ADR «Почему L2 промпт Direct остаётся») — PENDING: не потерян (строка карты), закрыть в W2-волне.
3. Evals/режимы (EVAL-MODES/EVAL-EGRESS), INIT-I01…I09/48h, MIGR-таблица, REQ-PROOF-EFFECT — PENDING до W3/прода: не считаются закрытыми W1.

## Binding

Ревью привязано к HEAD beb3f272 (вся цепочка 700f762c..beb3f272) + карта ревизии beb3f272 + факт-наборы среды: venv CPython 3.x, локальная БД v37. Любое изменение канонов/снапшота инвалидирует байт-сверки (тесты падают — это защитное свойство).
