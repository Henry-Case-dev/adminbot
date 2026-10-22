# Reconciliation — asap2-direct-chat против ASAP Speech Architecture (W1)

Дата: 23.10.2026. Источник: `plans/features/asap2-direct-chat/source-2026-10-22.md` (324 строки, SHA карты зафиксирован). Карта: `requirements-map.json` (71 инвентарная строка + 73 manual, из них 109 required).

## Вердикт

**Дубликатов-требований с ASAP Speech Architecture нет.** asap2 — точечное расширение (edit-in-place) уже заменённых W1 канонов + снятие второго диктующего пути. Ни один req asap2 не повторяет req speech-arch; пересечения — только в общих файлах-носителях.

## Таблица пересечений

| Поверхность | Что уже сделал W1 (speech-arch) | Что добавляет asap2 | Статус |
|---|---|---|---|
| L1-канон `prompts.direct_l1_planner_system_prompt` (`services/chat_prompts.py`) | Релиз-кандидат 2.58.111: секция «ВЫБОР УЧАСТИЯ» §3.7 вместо «ФОРМА УЧАСТИЯ» (factory L1 `f8ab20121c02`, 4641 c; `evidence/w1/semantics-l1.md`, `README.md`) | §4.1: замена ТОЛЬКО старого правила уточнения (в runtime-дампе W1 оно ещё стоит: `direct-runtime-assembly-w1.txt:280-282` «5. needs_clarification=true — только если задача неразрешима…») на блок «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА» | **Edit-in-place поверх W1** — не дубликат, а расширение того же канона (req CLAR-L1-CANON/KEYSCOPE) |
| L2 вербализатор `prompts.direct_chat_verbalizer_system_prompt` | §3.1 «КАК ПИСАТЬ» (+ единственная data-reader-добавка P0A-RISK) | §4.2: вставка ОДНОГО абзаца об уточнении в этот же раздел | **Edit-in-place**; не дублировать типографику/extent-правила W1; второй system prompt запрещён (req CLAR-L2-ONCE/CANON) |
| L1D-контракт инициативы (P0-G: action/delivery/target_message_id, L1_DELIVERY_MODES) | Заменена секция участия, парсер инициативы сохранён | Другая ось (уточнение, не доставка/цель) | **Не пересекается**; asap2 обязан сохранить контракт (матрица #35, DONE-D-группа) |
| Corrective 2.58.107 (Expression header / Core) | Шапка Expression, Core v3 | Не трогает Core/Expression/Style Policy | **Не пересекается**; guardrail GOV-CANON-EXACT + матрица #36 |
| MIGR-механика (prompt_registry/prompt_migrations, factory+active PG, owner-preserving) | Процедура миграции, PREV-цепочка | Те же ключи L1/L2, новый revision | **Переиспользование процедуры**, не перезапуск миграций speech-arch; бамп только для L1/L2-ключей |
| INIT-LIVE (48ч), EVAL-EGRESS, INSPECTOR/UI | Вне скоупа asap2 | asap2 не добавляет квот/наблюдателей | **Вне скоупа** |

## Координация последовательности с W1

- W1 уже в дереве (release-258111). CLAR-L1/CLAR-L2 правят те же каноны, что W1 P0-G/P0-A → **применять после фиксации базы W1**: перед правкой сверить hash текущего factory L1 (ожидаемо `f8ab20121c02`) и L2; если поезд W1 ещё движется — дождаться его ревью/релиза, чтобы не пересобирать канон-тесты дважды.
- Запрещено трогать в CLAR-L1: секцию «ВЫБОР УЧАСТИЯ», правила 1–7 кроме правила уточнения, схему JSON; в CLAR-L2: остальные абзацы «КАК ПИСАТЬ».
- Граф: CLAR-L2 depends_on CLAR-L1 (общий `services/chat_prompts.py`); MIGR depends_on CLAR-L1+CLAR-L2+CLAR-SPEECH.

## Дедупликация внутри источника (inventory)

- `duplicate`: L131→L19/L105, L132→L22, L133→L19, L134→L20 (конкретизации запретов §0), L289→сводка слайсов (manual duplicate), L322→TESTS-SCOPE (L215), L324→GOV-DIRECTIVE/GOV-MINIMAL-DIFF + TESTS-METHOD-REAL.
- `context` (30): заголовки разделов, ASCII-схема §3 (L67–91, инвентаризована L85), указатели §9. Проза вне инвентаря, чьи обязательства уже покрыты другими req (без отдельной строки): L13 (слоган = GOV-DIRECTIVE), L30 (симптом — обоснование, приёмка через матрицу), L36/L50/L52 (структура), L46 (граница = канон §4.1 + GOV-NOGAG), L93 (запрет второго валидатора = GOV-NONEWCMP + CLAR-L1-FLAGFALSE), L97/L101 (allowlist/«не подменять» = GOV-DIRECTIVE + GOV-HEURISTIC-DENY + TESTS-METHOD-FIX), L113 (пояснение контракта = CLAR-L1-группа), L154-168/L176-180/L186-188 (канон-тексты = CLAR-*-CANON), L311 (резюме).
- Ручные additional_requirements: 73 (72 required + 1 duplicate), включая все 36 строк матрицы §6.1–6.4 (T01–T36) — в инвентарь гейта таблицы не попадают.

## Покрытие (reverse-pass по §0–§9)

Все обязательства имеют владельца: §0/§3.1 guardrails → GOV; §1 различения/принцип → CLAR-L1; §2 таблица мест → по слайсам; §3.2 контракт → CLAR-L1/CLAR-BOOL/CLAR-PLAN; §3.3/§4.4 → CLAR-SPEECH; §3.4 → CLAR-CTX + CLAR-L1 (антицикл); §3.5 → CLAR-L2/CLAR-BOOL; §4.1–4.3 каноны → CLAR-L1/L2/PLAN; §5 → MIGR; §6 → TESTS (T01–T36 + методика); §7 роли → GOV/TESTS/MIGR/DONE-CRITERIA; §8 → DONE-CRITERIA (D1–D9); §9 — указатели (context). Слепых зон нет; «remaining backlog» не заводился.

## Гейты и граничные решения

- Human Gate: 0. §7 прямо разрешает продолжение без нового гейта; standing rule PET_PROJECT (18.10.2026) — канареечных согласований не вводить. `live_required=true` только у DONE-D9 (deploy/health — обязательная инженерная приёмка, postdeploy).
- Architecture: **ARCH_REUSE_CONFIRMED** — все изменения внутри существующих контрактов (`services/direct_l1.py`, `services/chat_prompts.py`, `services/claim_envelope.py`, `services/direct_chat_service.py`, процедур prompt_registry/migrations, проверенных W1); новых публичных интерфейсов, схемы БД и новых подсистем нет — это и есть требование §0/§3. Слайс GOV-ARCH-AUDIT фиксирует аудит фактического effective-состояния перед Builder.
- Пост-деплойные живые проверки семантики (матрица на реальной модели) — preprod-прогоны; причина конкретного прод-turn без приватной трассировки остаётся UNCONFIRMED (WAITING_EXTERNAL), не блокирует релиз.
