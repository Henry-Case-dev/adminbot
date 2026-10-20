# CFG-07A.F — reuse-аудит контейнера (свертка по M00037/L339)

- **Лейн:** CFG-07CG, 21.10.2026. Требование строки: «SOUL-01/04/02/16 уже покрывают общую
  матрицу Writers и Composer. Не строить её второй раз: переиспользовать их артефакты и
  проверить здесь только новые анти-backstage сценарии, конкретные internal→public утечки
  и доставку».
- **Кандидат:** uncommitted worktree поверх прод-линии 2.58.102 (attribution 06G.3, каноны
  07A-2, samples-ux — в проде). Коммитов нет по брифу; биндинг — оркестратор.

## 1. Что переиспользовано (матрица НЕ строилась второй раз)

| Артефакт SOUL | Что взято | Где живёт | Доказательство |
|---|---|---|---|
| SOUL-1 W2 (Composer/Core, unified) | `speech_owner_block` последним блоком system во ВСЕХ пользовательских маршрутах (factcheck/summary/direct/checkup/search/youtube/web) | `services/prompt_composer.py` (шов), call sites см. план §1 | 18 CONTRACT-тестов `tests/test_unified_core_route_coverage.py` (прогон 07cg-tests.txt — зелёные) |
| SOUL-02 (речь/юмор/мышление) | Personality Core full/compact байт-цел; юмор = свойство речи, не декларация | `services/chat_prompts.py::PERSONALITY_CORE_*` | `test_allowed_sarcasm_not_removed`, `test_humor_pools_have_no_backstage_direction` (07cg) |
| SOUL-04 (Writers-каноны) | Каноны 7 маршрутов НЕ переписывались вторым слоем — вычистка только по семантике suppress-правил + лестница ADR-1013-3 | `services/{search,youtube,web,checkup,summary,chat}_prompts.py`, `prompt_migrations.py` | `tests/test_cfg07_backstage_contract.py` (38): байт-паритет suppress(persisted)==канон, OFF-паритет, откат на непосредственный прежний канон |
| SOUL-05 (L1 ResponsePlan) | Источник выбора юмор-приёма — только совет L1 (`comic_strategy`); L1 не дублируется | `services/direct_l1.py`, `mca_humor_craft.select_technique` | `test_soul1_w4_humor_craft.py` (зелёные в 07cg-tests.txt) |
| SOUL-06 (Humor Craft) | Техники/рамка/toggle как есть; CFG-07A.6 не создавал второго юмориста | `services/mca_humor_craft.py` | `test_humor_on_renders_clean_layer`, `test_humor_gate_off_renders_nothing`, `test_humor_owner_toggle_off_disables_layer` (07cg) |
| SOUL-08 (humor feedback) | context_weight стратегии — существующий контур, не тронут | `services/mca_humor_feedback.py` | вне диффа (git status) |
| SOUL-16 (Inspector/payload-диагностика) | Диагностика выражения — closed-set из 07B.8; R17-дедуп | `services/mca_expression.py::EXPRESSION_DIAG_CLASSES` | `tests/test_mca_expression_diag*` (существующие, вне диффа) |
| CFG-06 W3/W5 (фриз фактчека) | Схемы CheckedVerdict/Presentation, egress-whitelist, renderer, delivery-швы — потребитель, не владелец | `services/factcheck_{orchestrator,renderer}.py` | `tests/test_factcheck_orchestrator_cfg06.py`, `test_factcheck_attribution_cfg06.py`, `test_factcheck_w6_cfg06.py` (зелёные) |

## 2. Что закрыто самим CFG-07A (новые анти-backstage сценарии — ровно дельта M00037)

- Корпус `07a1-corpus.{md,json}` (35 FORBIDDEN + 17 SOURCE_FIX + 12 POSITIVE) + deployed-аудит
  `07a1-audit.md` (07A-1, SHA 29cc49ba; postdeploy 2.58.102: effective = чистый заводской канон,
  кастомы удержаны провенанс-гейтом F1 — `f1-custom-suppress.md`, ревью `review-f1.md`).
- Вычистка 7 не-фактчек канонов по лестнице C14-прецедента + Writer-контракт Direct
  («СЛУЖЕБНЫЕ ПОМЕТКИ — данные, не сюжет») + человеческие пометки capability (`rejected_note`)
  + токен-гард nostalgia (`contains_unchanged_token`) — `07a2-summary.md`, тесты
  `test_cfg07_backstage_contract.py`.
- Словарь честности/метаречи + тест-гарды честных отказов (07A.3/.5, 07D.1/.2) — эта волна:
  `services/public_speech_guard.py`, `tests/test_cfg07_egress_dictionary.py`,
  `07cg-dictionary.md`.

## 3. Что переносится в 07C-G-хвост (не потеряно, вне этого лейна)

- **Egress-guard на точке outbound** (07C.1–.6): интеграция `public_speech_guard` после
  Composer/Writer до сериализации на delivery-швах (factcheck W5-швы, Direct/fallback/error,
  summary/checkup/search/youtube send); детекторы машинных артефактов корпуса (FA-*,
  MB-10/11/12 — reason-коды/tool-имена/поля), bounded retry для смысловой метаречи, честный
  fail-soft в стиле персонажа. Вход готов: словарь классов/FORBIDDEN-семей (§07cg-dictionary).
- **07D.5** (mock-Writer форсит артефакты → на Telegram ни одного), **07D.6** (воспроизведение
  регрессий ДО/ПОСЛЕ по контрольным фрагментам + deployed SHA/флаги, postdeploy), **07D.7**
  (переходы/дефолты SOUL-1/W3/W6, покрытие без «100%» по необследованному).
- **07A.1 live-хвост**: postdeploy-трассы effective payload после следующего релиза
  (READY_FOR_LIVE-семантика сохранена; техпроверки — без сообщений в чат).

## 4. Статус строк контейнера CFG-07A (сводка)

| Строка | Статус | Чем закрыта |
|---|---|---|
| 07A.1 | VERIFIED (postdeploy-проба 2.58.102) + live-хвост за release-слотом | 07A-1 аудит, F1 |
| 07A.2/.4/.6/.7/.8 | VERIFIED | 07A-2 контракт-тесты, лестницы, W3/W5-стык |
| 07A.3 | PENDING → guard-ready | 07cg-гарды (v2-контур, моки) — биндинг оркестратором |
| 07A.5 | PENDING → guard-ready | 07cg-гарды (админ-контекст, честные возможности) |
| 07D.1 | PENDING → guard-ready (инженерная часть) | 07cg-гарды humor-пулов ON/OFF; live-глазами владельца — опционально (`plans/owner_live_checks.md` §6, standing rule) |
| 07D.2 | PENDING → guard-ready | 07cg-гарды overclaim/честная техсправка |
| 07A.F (эта строка) | PENDING → готова к VERIFIED | этот аудит: матрица не строилась, дельта закрыта, хвост прописан |

## 5. Честные residual (зафиксированы, не теряются)

- Hostility-хвост в фактчек-каноне и identity-фраза Direct нового канона — W3-фриз/suppress-слой,
  сознательно не тронуты (07a2-summary §6.4; review-f1 «related-nonblocking»).
- Фактчек-часть 07A.8 принадлежит CFG-06 W3 (`stage2_payload`) — не дублирована (план §1).
