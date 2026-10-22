# Reconciliation — asap-speech-arch vs уже исполненные коррективы

Лейн: PM-ASAP-SPEECH-MAP, 22.10.2026. Источник: `source-2026-10-22.md` (420 строк, вкл. ДОП-1/ДОП-2, sha256 `3657b41ea8041953…`). Карта: `requirements-map.json` (inventory 120: 74 required + 35 context + 11 duplicate; manual 41 required; **итого 115 required**). Граф: `slice-graph.json` (21 слайс, `openworkflow-slices-v1`). Гейт plan: **EXIT 0** (strict_evidence=true).

Статусы дедупа — вердикты против уже исполненного кода на текущем HEAD, **не статусы карты** (в карте все строки `PENDING`: источник прямо требует подтверждения боевого пути, «наличие исправлений в исходниках само по себе не подтверждает работу»).

## 1. Дельта к 2.58.107 (FIX-CORRECTIVE-FOLLOWUP, speech-corrective)

| Обязательство | Вердикт | Факт на HEAD |
|---|---|---|
| Тема мата удалена из factory Core Full/Compact | **DONE-2.58.107** | `chat_prompts.py:653-706`: заголовок «Мат и грубость» → «Грубость», 2 мат-предложения удалены, `PREV_PERSONALITY_CORE_*` сохранены. Но **новые тексты §3.2/§3.3 НЕ применены** → REQ-P0B/REQ-P0C остаются NEW-текстами (PARTIAL-слайс) |
| SOUL-16 убран из model-facing | **NOT DONE** | Хвост `**Важно:** … см. SOUL-16` остаётся в `PERSONALITY_CORE_FULL_TEXT` (chat_prompts.py:686) → REQ-META-CLEAN, T-META-CLEAN актуальны |
| Тексты режимов мата off/occasional/frequent | **DONE** | `mca_expression.py:74-88` `PROFANITY_INSTRUCTIONS` = §3.4 байт-в-байт; зафиксировано P0D-BOUNDS (не трогать) |
| EXPRESSION_FOOTER | **DONE** | `</Expression_Settings>` — идентичен §3.4 |
| **EXPRESSION_HEADER** | **ДЕЛЬТА → NEW** | Текущий (после удаления нейтрализаторов) всё ещё: «Выражение владельца - прямые директивы…» + приоритетные строки (план/прямая просьба/канон/C16). Новый §3.4: «ПРАВИЛА МАНЕРЫ РЕЧИ» + правило «не переноси ограничения или разрешения из других речевых слоёв», без «Выражение владельца». Замена = REQ-P0D, слайс P0-D |
| «Выражение владельца» в model-facing | **NOT DONE** | Присутствует в текущем EXPRESSION_HEADER (mca_expression.py:124) → REQ-META-CLEAN |

## 2. Дельта к 2.58.110 (INITIATIVE-L1D)

| Обязательство | Вердикт | Факт на HEAD |
|---|---|---|
| `L1_DELIVERY_MODES=("chat","reply")`, closed-set normalize | **DONE** | `direct_l1.py:57,355` |
| `has_explicit_reply_intent` (референс ТЗ §3.7) | **НЕ НАЙДЕН** | Символ отсутствует во всём коде — ссылка ТЗ устарела; при W1 сверить фактическое имя хелпера (отмечено в acceptance P0G-PARSER) |
| Секция промпта «ВЫБОР УЧАСТИЯ» §3.7 | **NEW** | В L1-каноне отсутствует → REQ-P0G |
| Контракт action/delivery/target_message_id | **DONE (L1D)** | Сохраняется; REQ-REPLY-OPT (reply = выбор, не константа) — обязательный контрпример |

## 3. Связь с cfg-07A/07C (egress) и expression-bisect

- **07A/07C**: `TYPOGRAPHY_BLOCK` уже переписан, прод-байты с «Разрешен мат и сленг.» опознаются миграцией (`prompt_style_blocks.py:133-146`, `PREV_TYPOGRAPHY_BLOCK`). Но жёсткие правила «Только короткие дефисы (-) и обычные двойные кавычки ("")» **остаются в Direct L2** и конфликтуют с `HINT_QUOTES_HARD/SOFT` Style Policy → REQ-P0E / P0E-DEDUP / T-STYLE-CONFLICT остаются NEW.
- Legacy-suppression «токсичный…бот-абьюзер» на сборке существует (`prompt_registry.py:1893,1992`, `prompt_style_blocks.py:233`), но **фабричные тексты каналов всё ещё содержат identity** (verbalizer chat_prompts.py:391, direct-варианты 75-266, summary/search/web/youtube) → REQ-P0F + P0F-MATRIX NEW.
- **expression-bisect** (`plans/features/expression-bisect-2026-10-21.md`): baseline-гипотеза, не доказательство прод-работы — контекст (L00372).
- Verbalizer сейчас: `verbalizer-canon-mca23` («Ты — токсичный… (бот-абьюзер). Ты получаешь ТОЛЬКО готовую справку в формате JSON…» + TYPOGRAPHY_BLOCK, `prompt_registry.py:121,272-273`) — risk-фраза §3.1 подтверждена дословно → REQ-P0A NEW.

## 4. Разбивка required-строк по слайсам и вердиктам

| Слайс | Required | Вердикты |
|---|---|---|
| P0-A | 7 | NEW: REQ-P0A, REQ-L2-KEEP, REQ-PREFIX-SEP, P0A-RISK, CANON-EXACT(част.), ARCH-ADR, ADD-IDENTITY-L2; REQ-EXTENT — PARTIAL (MCA-23 extent-правило есть, сверить все пути) |
| P0-B | 10 | PARTIAL: REQ-P0B/REQ-P0C-смежн. (factory очищен, новые тексты не применены, SOUL-16 остался); NEW: P0B-OWNER, ADD1-CORE-SOURCE, ADD2-KEEP-FULL, ADD2-PERSONA-FULL, ADD2-BLOCK-MAP, ADD1-PERSONA, ADD2-NO-PRIMITIVE, REQ-EMBED (частично ADD-EXP), ADD2-PRESERVE(MIGR-смежн.) |
| P0-C | 1 | NEW: REQ-P0C (новый текст §3.3) |
| P0-D | 7 | NEW: REQ-P0D (дельта шапки), REQ-META-CLEAN, REQ-NOMETA, P0D-BOUNDS, P0D-INVARIANTS, P0D-QUOTED, ADD-EXPR-INTENSITY; режимы мата — DONE-2.58.107 (не трогать) |
| P0-E | 4 | NEW/PARTIAL: REQ-P0E, P0E-BOUNDS, P0E-DEDUP, ADD1-STYLE-ONLY (typed policy есть, конфликт кавычек жив) |
| P0-F | 5 | NEW: REQ-P0F, P0F-BOUNDS, P0F-MATRIX, ADD1-MODULE-NOVOICE, ADD-IDENTITY-TOOL (suppression есть, фабрика не очищена) |
| P0-G | 5 | PARTIAL: REQ-P0G (контракт L1D есть, секции нет), REQ-REPLY-OPT, P0G-MODELONLY, P0G-PARSER; NEW-секция §3.7 |
| MIGR | 15 | NEW (протокол §5 целиком): MIGR-INV…MIGR-ROLLBACK, REQ-STALE-CORE, REQ-SCOPE, REQ-REALDB, TRACE-GRAPH, REQ-W0-MAP, MAN-FACTORY-ACTIVE, MIGR-TABLE, ADD2-PRESERVE |
| INSPECTOR | 7 | NEW: INS-TRACE…INS-PRIVACY, REQ-HONEST-OFF |
| INIT-LIVE | 17 | NEW: INIT-I01…I09, INIT-TESTS, EVAL-MODES, REQ-PROOF-EFFECT, T-I-COVERAGE, T-DELIVERY-ERR, T-UI-*; **OWNER_LIVE/WAITING_EXTERNAL**: INIT-48H (48ч прод-наблюдение), EVAL-EGRESS (после deploy), REQ-PROOF-EFFECT (боевой путь) |
| TESTS | 17 | NEW: T-CORE-CLEAN…T-INTERNAL-CLEAN, REQ-ONE-OWNER, REQ-NOFORCE, ANTIPATTERN-MATRIX, REQ-LAYER-CONTRACTS, ADD1-DISTRIB, ADD1-NO-SOFTEN, ADD2-CANON-BASIS, ADD2-REVIEWER |
| UI-U01…U07, U09 | 7+1 | NEW (P1, по скриншотам) |
| UI-P2 | 1 | NEW (P2) |
| REPORT | 4 | NEW: REP-FORMAT, REP-NOFAKE, GOV-PENDINGLIVE, DOD-FINAL |

Итог по вердиктам: **DONE** (частично закрывает слайс, не снимает PENDING): тексты режимов мата, footer, factory-очистка Core от мат-темы, L1_DELIVERY_MODES, 07A/07C egress-миграция, MCA-23 extent. **PARTIAL**: Core-слайс (новые тексты+SOUL-16), P0-G (секция), P0-E (конфликт жив). **NEW**: всё остальное. **OWNER_LIVE**: REQ-PROOF-EFFECT, EVAL-EGRESS, INIT-48H (+ UI-скриншоты как опциональная обратная связь владельца по standing rule PET_PROJECT — не гейт). **WAITING**: INIT-48H (48-часовое окно наблюдения). Уточнение к брифу лейна: «video» в источнике — только существующая карточка «Выжимка видео» в U-03; отдельного видео-WAITING-требования в тексте нет.

## 5. ДОП-1/ДОП-2 (22.10.2026, verbatim) — встроены

10 новых inventory-строк (388-391, 409-414) → required: ADD1-CORE-SOURCE, ADD-EXPR-INTENSITY, ADD1-STYLE-ONLY, ADD1-MODULE-NOVOICE, ADD2-KEEP-FULL, ADD2-PERSONA-FULL, ADD2-CANON-BASIS, ADD2-BLOCK-MAP, ADD2-PRESERVE, ADD2-REVIEWER. Prose-строки → manual: ADD1-PERSONA (384), ADD1-DISTRIB (386), ADD-IDENTITY-L2/TOOL (393, по строке на слайс), ADD1-NO-SOFTEN (395), ADD2-NO-PRIMITIVE (403). Acceptance REQ-P0A/P0B/P0C/P0F/P0D расширены условиями дополнений (личность сохраняем, примитивизация запрещена, ревью проверяет выразительность). Запрещённые решения (скрытые ограничители, нейтрализаторы, автоцензура, примитивные инструкции, выбрасывание фрагментов ради токенов) — в acceptance ADD1-NO-SOFTEN / ADD2-NO-PRIMITIVE / ANTIPATTERN-MATRIX.

## 6. Волны (§10) → граф

W0 → REQ-W0-MAP/MIGR-INV/MIGR-TRACE · W1 → P0-A→B→C→E→F→G (serial, общий файл) ∥ P0-D (независимый) · W2 → MIGR (join всех P0) · W3 → INIT-LIVE (+TESTS) · W4 → INSPECTOR → UI-U01→…→U09→UI-P2 · W5 → гейты workflow. Не коммитить этим лейном — коммит следующим лейном вместе с W1.
