# BGS-INTEGRATION-CONTRACT — BEHAVIOR-GATES-SIMPLIFICATION-01

- Статус: ARCHITECT_VALIDATED, план интеграции по факту дерева (не новый эпик).
- Дерево: worktree `WorkspaceData/worktrees/6f4c07e43141f379/hotfix-meme-publication-initia-d78f499866ee-6ef91e44`, branch `evol/impl`, HEAD `ba3ff21e`, дерево чистое.
- Источник: `plans/owner_inputs/2026-11-05-behavior-gates-simplification.md` (BGS-01..08, §8 матрица конфликтов).
- Активные полосы на момент фиксации: `ur/b-search` (UR-B) — правит `services/direct_execution.py` / `direct_l1.py` (снятие privacy-вето, BGS-01); UR-C — смержена (9ac64a61); CMV — смержена; PVR-FC — не стартовала; prompt-versioning — отдельная полоса. `services/evidence_policy.py` — один писатель (полоса BGS).

## 0. Канонические решения (фиксируются этим документом)

1. **BGS-01 (privacy)**: единственное живое место критерия — `services/evidence_policy.py` (ветка в `allowed()`). Поле `privacy_ok` и код `BLOCK_PRIVACY` удаляются; producer'а в runtime НЕТ (`_evidence_context` уже не передаёт `privacy_ok`, дефолт True — вето спит, но ветка и поле обязаны исчезнуть окончательно, чтобы никто не «включил» снова). Query-деперсонализатор фактчека `_strip_privacy` — обязателен к снятию как политика (BGS-01 п.4 «обязательный обезличиватель», §8 угол 3, DoD-1 «даже через Factcheck»). Классификатор-замену не вводить (запрет §0.1).
2. **BGS-02/03/04**: guard'ы `guard_egress`/`drop_claim_sentence`, `public_speech_guard`, retry-петли `verbalize_validated` переводятся в observability-only / сжимаются по триггерам. Технические санитайзеры не трогаются.
3. **BGS-05**: константы `ORCHESTRATOR_*` = legacy-дефолты; динамическое решение живёт в существующих `model_capacity`/`auto_budget` (UR-C), без нового лимитера. Жёсткие провайдерные/петлевые пределы остаются.
4. **BGS-06**: один источник истины — `param_catalog.py` + backend effective settings. Deprecated-ключи помечаются `replaced_by`, старые значения читаются при миграции и архивно сохраняются. UI-работа НЕ стартует до UR-F/PVR-UI (нет параллельного UI); BGS сейчас готовит только дельту каталога.
5. **Не путать флаги**: `mca_gates.egress_guard_enabled()` (`MCA_EGRESS_GUARD_ENABLED`, loopback/media egress, ADR-1027-5 D12) и `TELEGRAM_SEND_GUARD_ENABLED` НЕ являются объектами BGS и не отключаются. Удаляемый контекст — только `evidence_policy.egress_guard_enabled()` (`EVIDENCE_EGRESS_GUARD_ENABLED`, bounded outbound evidence guard) и сам guard.

## 1. Карта владения на HEAD `ba3ff21e`

Легенда: владелец-полоса и требуемый порядок. `SERIALIZE` = два потенциальных писателя, порядок обязателен.

| Файл (функции) | BGS-пункт | Текущий владелец/полоса | Порядок |
|---|---|---|---|
| `services/evidence_policy.py` (`allowed`, `BLOCK_PRIVACY`, `privacy_ok`, `guard_egress`, `drop_claim_sentence`, `egress_guard_enabled`) | 01, 02 | полоса BGS (единственный писатель) | после join ur/b-search; до FC-BACKEND |
| `services/direct_chat_service.py` (`_evidence_context`:2645, `_run_evidence_egress_guard`:2702, call-sites 5413/13182, `_ev_lookup`/`allowed` 6545, `_l1_tool_subset`:6645, `_l1_tool_phase`:6734→`run_adaptive_chain`:6765) | 01, 02 | UR-цепочка A→C(смерж.)→D→E, файл в scope UR-D и UR-E | SERIALIZE: BGS-02 врезается в серийную цепочку ПОСЛЕ UR-D (или когда цепь свободна), согласовано с UR-E |
| `services/factcheck_planner.py` (`_strip_privacy`:423, вызовы 706/866, `dropped_privacy` 309/982) | 01 | PVR-FC `FC-BACKEND` (не стартовала) | SERIALIZE: BGS-01-фактчек ПЕРВЫЙ, затем FC-BACKEND |
| `services/factcheck_attribution.py` (`external_safe_claim`/`privacy_version` 302–331) | 01 | PVR-FC `FC-BACKEND` | то же: BGS-01-фактчек первый |
| `services/factcheck_orchestrator.py` (privacy-claim план 1094/1144/1150–1153/1189/1378; `_guard_outbound` 380–389) | 01, 03 | PVR-FC `FC-BACKEND` | то же; guard-вызов — в BGS-03 |
| `services/factcheck_service.py` (`metatext_retry_reason` 189; `verbalize_validated` 1968/2685) | 03, 04 | PVR-FC `FC-BACKEND` | BGS правит только metatext-retry/скрипку триггеров ДО FC-BACKEND; numeric/negation-контроль фактчека НЕ ослаблять (FC-01–05 без изменений) |
| `services/tool_router.py` (`guard_public_text` на verdict_text 4072–4073; комментарий 4236) | 01, 03 | UR-B (активна) | после merge ur/b-search |
| `services/public_speech_guard.py` (`guard_public_text`:596, `_BACKSTAGE_FAMILIES`:165, `find_backstage_metatext`:217, `find_semantic_metatext`:437, `_strip_matches`) | 03 | полоса BGS | один писатель; потребители — по строкам выше |
| `services/negative_constraints.py` (`verbalize_validated`:720, `_MAX_RETRIES_HARD_CAP=2`:46, form-gate 813–814, `strip_guard_findings` 867) | 04 | UR-E (не стартовала; scope W5) | SERIALIZE: сначала UR-E, поверх — усечение BGS-04 (либо единый коммит по согласованию) |
| `services/direct_execution.py` (`ORCHESTRATOR_*` 94–99, `_limit` 134/175/180, срезы 808/814/824; adaptive chain) | 01, 05 | UR-B (активна) | после merge ur/b-search |
| `services/direct_l1.py` | 01, 05 | UR-B (активна; также в scope UR-A/UR-C/CLOCK — смержены) | после merge ur/b-search |
| `services/model_capacity.py`, `services/auto_budget.py` | 05 | UR-C (смержена) | READ_ONLY для BGS (использовать resolve_stage_window / resolve_evidence_window_tokens) |
| `services/prompt_composer.py`, `services/style_policy.py` | 04 | UR-E (не стартовала) | BGS не пишет; проверка дублей машинных инструкций — через UR-E + CRM |
| `services/param_catalog.py` | 06 | UR-C-CLOCK (смержена), далее UR-F | BGS: только спека дельты каталога; байты — владелец очереди |
| `web/app.js`, `web/index.html`, `web/static/app.css`, `web/api/*` | 06 | UR-F / PVR-UI (не стартовали; внешний барьер CMV — выполнен) | BLOCKED_BY:UR-F+PVR-UI; никакого параллельного UI |
| `services/outgoing_guard.py`, `services/telegram_send.py`, `services/safe_fetch.py`, `services/persistent_throttling.py`, `services/initiative_observer.py`, `services/mca_gates.py` (`MCA_EGRESS_GUARD_ENABLED`) | — | существующие владельцы | НЕ ТРОГАТЬ (технические инварианты, §0.3/§0.5) |
| `tests/test_evol_evidence_routing.py`, `tests/test_evol_evidence_corpus.py`, `tests/test_evol_source_reader.py`, `tests/test_evol_w17_small_canon_reqs.py`, `tests/test_cfg07_*` | 08 | полоса, владеющая соответствующим src-файлом | тесты переписываются вместе с контрактом, не «чинятся до зелёного» |

Двойная запись в один файл запрещена; любой новый писатель обязан встать в цепочку выше.

## 2. Точные call-сайты privacy (что теряет вето)

Определения — только `services/evidence_policy.py`:
- `:96` `EvidenceSkipReason.RBAC_OR_PRIVACY_BLOCKED` + `:130`/`:223` маппинги → остаются ТОЛЬКО как декодеры старых событий; новые события этого класса не генерируются.
- `:156` `BLOCK_PRIVACY = "privacy_blocked"`, `:167` маппинг в `CAPABILITY_NOT_READY` — удалить вместе с веткой.
- `:398` поле `EvidenceContext.privacy_ok` — удалить (runtime-производителей нет; ставят только тесты).
- `:512–513` ветка в `allowed()` — удалить; порядок проверок становится RBAC → запрет сети → провайдер → квота → SSRF (комментарий `:480` поправить).

Потребители `allowed()` (проверить при реализации, не по памяти):
- `direct_chat_service.py:6545` `_evp.allowed("web_search", context)` — lookup самого egress-guard'а (умирает вместе с guard-веткой BGS-02).
- политика обязательности: `direct_chat_service.py:6268–6275` (`evaluate_evidence_need` + `_evidence_context`), `evidence_policy.py:814` (`effective_capabilities` внутри evaluate).
- adaptive chain: `_l1_tool_phase` → `run_adaptive_chain` (`direct_execution`), гейтится тем же `allowed()` через политику — после удаления ветки privacy в цепи не остаётся.
- Initiative: `direct_chat_service.py:13160–13162` — `is_external_forbidden` (это `user_forbids`, явный запрет сети) — **сохранить**, это не privacy-вето.

Query-деперсонализация (вторая скрытая политика — снять как обязательную):
- `factcheck_planner.py::_strip_privacy` (423) + вызовы 706, 866; метаданные `dropped_privacy` 309/982.
- `factcheck_attribution.py` 302–331 (`external_safe_claim`/`privacy_version`, импорт `_strip_privacy` 321–322).
- `factcheck_orchestrator.py` 1094, 1144, 1150–1153, 1189, 1378 (план строится от privacy-клейма).
- Комментарии-следы: `mca_events.py:340`, `tool_router.py:4236`, docstring `direct_chat_service.py:6226`.
- Сохранить: semantic claim→query, evidence coverage, уточняющие запросы (суть `_claim_units`/`build_retrieval_plan` не меняется — меняется только отсутствие обязательной вычистки имён).
- Секреты/API-ключи и «весь чат в запрос» — обычные правила (не privacy-политика), остаются.

Тесты с `privacy_ok=False`: `tests/test_evol_evidence_routing.py:73`, `tests/test_evol_evidence_corpus.py:142`, `tests/test_evol_source_reader.py:1305+` — переписать на новые инварианты (поиск доходит, reason-кодов privacy нет).

Карта UR всё ещё требует `privacy_blocked` (`plans/features/unified-reply/requirements-map.json:502, 2650, 2665`; `slice-graph.json:80`; `arch/unified-reply-contract.md:122, 323`) — обязательная часть S1: поправить acceptance этих строк по BGS §8 (UR-06/07/08 «Заменено BGS-01»), иначе ревью/следующие билдеры восстановят вето по устаревшей карте.

## 3. Классификация guard'ов (BGS-02/03/04)

### Observability-only (диагностика без изменения текста, без LLM-retry по словарю, без fail-closed на разговорный контент)
- `evidence_policy.guard_egress` / `GUARD_DROP_CLAIM` (919) / `GUARD_ONE_LOOKUP`/`GUARD_SKIP_CLASSES` (922) / `drop_claim_sentence` (1197): вердикт можно оставить как код события `EVIDENCE_EGRESS_CHECK`, но ветки lookup-после-Writer (§2.3 п.3), hint-rewrite (`EVIDENCE_EGRESS_HINT` 2694) и удаление предложения — убрать.
- `direct_chat_service._run_evidence_egress_guard` (2702): сжать до наблюдения (stats+event), оба call-site — 5413 (Direct) и 13182 (Initiative); текст не мутирует.
- `public_speech_guard`: `guard_public_text` (596), `_BACKSTAGE_FAMILIES` (165), `find_backstage_metatext` (217), `find_semantic_metatext` (437), `_strip_matches` — детект остаётся (событие для владельца), модификация/блокировка живого ответа — нет. Потребители, подлежащие переводу: `factcheck_orchestrator._guard_outbound` (380–389), `tool_router` 4072–4073, `negative_constraints.strip_guard_findings` (867), `factcheck_service.metatext_retry_reason` (189, bounded metatext-retry — LLM-reroll по словарю: снять для обычных ответов).
- kill-switch `EVIDENCE_EGRESS_GUARD_ENABLED` (1239/1262) и `EVIDENCE_ROUTING_POLICY_ENABLED` — после BGS-02 потеряют смысл; задокументировать как legacy, не переиспользовать.

### Технические, СОХРАНИТЬ (не приписывать к «цензуре»)
- `outgoing_guard.sanitize_outgoing` + chokepoint `telegram_send` (`SEND_POINTS`/`SEND_ALLOWLIST`, env `TELEGRAM_SEND_GUARD_ENABLED`) — машинные маркеры `<thought>`/`fact:ID`/`msg:ID`/target.
- Протокольный sanitizer; SSRF/`SafeFetcher`; RBAC/`capability_registry`; master-гейты `flags.search_enabled` (`handlers/search.py:140`, `handlers/direct_chat.py:117`), `flags.webpage_enabled` (`handlers/web.py:142`, `handlers/direct_chat.py:119`); квоты/мoney-gates; chunking/dedup доставки; `style_policy` — только явно выбранные владельцем нормализации; UR-18/19 (finish_reason/continuation); anticliche — уже diagnostic-only (`cliche_observed`, `anti_cliche_retries==0`) — не реанимировать.
- **НЕ отключать по созвучию имени**: `mca_gates.egress_guard_enabled()` (720–725, `MCA_EGRESS_GUARD_ENABLED`, loopback/media), а также `MCA_SAFE_FETCH_ENABLED`.

### Retry-петли, которые сжимаются (BGS-04)
- `negative_constraints.verbalize_validated` (720): триггеры Form/Numeric/Metatext/Format → только невалидный протокол/структурированный формат или явно выбранная владельцем операция; клише/метатекст/«неподтверждённое число» в свободном ответе reroll не запускают. `_MAX_RETRIES_HARD_CAP=2` (46) остаётся техническим потолком, меняется набор триггеров. Гейты `mca_gates.postprocess_form_guard_enabled` (1227–1237; consumer 813–814) и `numeric_claim_guard_enabled` (822–823) остаются включателями ТОЛЬКО для легитимных трансформаций (перефраз/OCR/verbatim-операции, фактчек).
- Фактчек: numeric/negation/quoted-evidence контроль — без ослабления (FC-01–05). Вызовы `verbalize_validated` в `factcheck_service` (1968, 2685) и `summary_generator` (4248) — трактовать по их контракту (спец. трансформации), не по «свободному ответу».
- Свободный Direct/Initiative: после Writer не остаётся ни одной петли, способной удалить содержательное предложение или перегенерировать ответ по речевой эвристике.

## 4. Бюджеты (BGS-05) — что мигрировать

Legacy-дефолты (`services/direct_execution.py`):
- `ORCHESTRATOR_MAX_STEPS=4` (94), `ORCHESTRATOR_MAX_TOTAL_TOKENS=6000` (95), `ORCHESTRATOR_MAX_METERED_CALLS=4` (96), `ORCHESTRATOR_QUERY_CHARS=800` (97; срезы 814, 824), `ORCHESTRATOR_EVIDENCE_SNIPPET_CHARS=400` (99; срез 808).
- env-оверрайды `DIRECT_ORCHESTRATOR_MAX_STEPS/_MAX_TOTAL_TOKENS/_MAX_METERED_CALLS` (134/175/180) — сохранить как **жёсткий потолок** защиты, не как основной источник значения.

Куда переносится динамическое решение (код уже есть, писать новый лимитер запрещено):
- `model_capacity.resolve_stage_window` / `capacity_resolver_enabled` (используется в `direct_chat_service.py:8852–8858`), `auto_budget` (`resolve_evidence_window_tokens`, `auto_budget.py:370`), Stage Auto Budget в `direct_l1.py:1357/1408`. Дефолты становятся нижними fallback'ами при недоступном резолвере.

Остаётся жёсткой защитой (не трогать): `LLM_TOTAL_BUDGET` (дедлайн), `tool_loop.METERED_TOOLS` + `budget_gate`/`mca_money_limits`, таймауты сети/Telegram, предохранители от зацикливания, частота/cooldown инициативы (`persistent_throttling.resolve_direct_chat_limits`:344, `initiative_observer`) — параметры темпа владельца не пересматриваются этим эпиком.

Владение: `direct_execution.py` — полоса UR-B (правка ПОСЛЕ её merge); `model_capacity`/`auto_budget` — UR-C смержена (только чтение); `direct_chat_service` — серийная цепочка UR-D/E (§1).

## 5. Админка/параметры (BGS-06)

- Источник истины один: `param_catalog.py` (+PG/hot seed) → backend GET effective settings → params-meta → UI. Никаких дублирующих экранов.
- Ключи, теряющие потребителей после BGS: `flags.postprocess_form_guard_enabled` (param_catalog 2961–2968, группа `flags_character`, advanced; env `MCA_POSTPROCESS_FORM_GUARD_ENABLED` в `mca_process_registry:1334`, `module_registry:659`) и env-ы `EVIDENCE_*_ENABLED` (§3). Процедура: runtime перестаёт читать → каталог помечает ключ `deprecated` + `replaced_by` (или «удалён, значение архивно») → старые записи НЕ разрушать, читать при миграции → UI не показывает действующий ползунок без consumer. Прецедент отрицательной дельты каталога: ASAP-2.1 (−8 ключей/−2 группы).
- `MCA_EGRESS_GUARD_ENABLED` — оставить как есть (§0.5), это другой механизм.
- UI-группировка «Поиск и инструменты / Речь и характер / Проверка фактов / Частота участия / Технические ограничения», трасса correlation_id до/после — реализует UR-F/PVR-UI. BGS сейчас: только дельта каталога + строки CRM. Никакого параллельного UI и CSS-скрытия живого backend'а.

## 6. Порядок слияний и чекпойнты

1. **S0 — join ur/b-search**: мерж privacy-снятия в `direct_execution/direct_l1` + правка acceptance-строк UR-карты (502/2650/2665, slice-graph 80, contract 122/323). Чекпойнт: в трассе Direct нет privacy-кодов, карта не требует `privacy_blocked`.
2. **S1 — BGS-01-остаток** (полоса BGS, единственный писатель `evidence_policy.py`): удалить ветку/поле/константу; снять `_strip_privacy`-политику в factcheck-троице; переписать privacy-тесты на новые инварианты. ДО старта FC-BACKEND. Чекпойнт: сценарии BGS §9 A/B/C/I на реальных вызовах.
3. **S2 — BGS-02**: `guard_egress`→observability, `_run_evidence_egress_guard` без мутаций, оба call-site. Врезка в серийную цепочку `direct_chat_service.py` (после UR-D/по освобождении файла). Чекпойнт: `GUARD_DROP_CLAIM` недостижим, доставка байт-в-байт при несвязанных срабатываниях.
4. **S3 — BGS-04**: усечение триггеров `verbalize_validated` (после/вместе с UR-E по согласованию), form/numeric — только для реальных трансформаций; фактчек-контроль не ослаблен.
5. **S4 — BGS-03**: `public_speech_guard` → observability; потребители: `factcheck_orchestrator`/`factcheck_service` (до FC-BACKEND), `tool_router` (после UR-B), `negative_constraints` (после S3). Чекпойнт: фразы «по моим наблюдениям»/цитаты — байт-в-байт; `<thought>`/маркеры удаляются как раньше.
6. **S5 — BGS-05**: константы → capacity-резолвер (после UR-B для `direct_execution.py`). Чекпойнт: нет усечения середины предложения из-за локальных дефолтов; жёсткие пределы работают.
7. **S6 — BGS-06**: дельта каталога (+deprecated/replaced_by-маркировка) — по мере S1–S5; UI — BLOCKED_BY UR-F+PVR-UI. Чекпойнт: у удалённого guard'а нет включателя в UI, effective-status подтверждается backend'ом.
8. **S7 — CRM + приёмка BGS-08**: матрица ниже прикладывается к результату эпика и дополняется по каждому merge.

## 7. Conflict Resolution Matrix (скелет, обязателен к заполнению по BGS-07/§8)

| Прежний пункт | Заменён/сохранён | Удалённые consumer'ы (реальные) | Что осталось | Тест-доказательство |
|---|---|---|---|---|
| UR-06 (privacy_blocked при «небезопасном» запросе) | ЗАМЕНЁН BGS-01 | ветка `allowed()` 512–513; acceptance-строки UR-карты | RBAC/флаги/SSRF/квота/провайдер | privacy-сценарии A/B/C, `rbac_denied`/SSRF/provider-down остаются |
| UR-07 (обязательное обезличивание запроса) | ЗАМЕНЁН BGS-01 | `_strip_privacy` + `dropped_privacy` + privacy-клейм-план | смысловой query, запрет секретов/всего чата | fixture-тест запроса без обязательной вычистки |
| UR-08 («0 утечек» + privacy-причина) | ЗАМЕНЁН для query (BGS-01) | privacy reason-генерация | реальные вызовы, отсутствие экспорта чата/секретов | интеграционные сценарии, трасса search_called/status/sources |
| UR-15 (Form/Numeric retry в Writer) | УТОЧНЁН BGS-04 | reroll по стилевым эвристикам | контроль при реальной трансформации + фактчек | numeric-сохранение в спец. операциях |
| UR-18/19 | БЕЗ ИЗМЕНЕНИЙ | — | finish_reason/continuation | существующие тесты |
| UR-20–22 | БЕЗ ИЗМЕНЕНИЙ + дополнение (мертвые настройки убрать, трасса шире) | устаревшие ключи каталога | effective settings, Inspector | UI-тесты UR-F/PVR |
| UR-23–30 | БЕЗ ИЗМЕНЕНИЙ | — | история/ChatClock | существующие тесты |
| PVR-FC FC-01–05, FC-07, PVR-01–06 | БЕЗ ИЗМЕНЕНИЙ | — | claims/verdicts/provenance/SafeFetcher | фактчек-матрица (сценарий E) |
| 06G.3 privacy-фильтр запросов фактчека | ЗАМЕНЁН BGS-01 (DoD-1: «даже через Factcheck») | `_strip_privacy`-ветки planner/attribution/orchestrator | semantic claim→query, coverage | FC-SEMQUERY-тесты без privacy-ветки |
| Владелец: стиль/мат/кавычки/no_emoji | БЕЗ ИЗМЕНЕНИЙ | независимые hardcode-ножницы | `style_policy`/persona-правила | byte-preserve тесты BGS-03 |
| Расходные решения (billing/tool budget) | БЕЗ ИЗМЕНЕНИЙ | — | spending cap, анти-цикл | BGS-05 тесты |

Заполнение: каждая строка получает конкретные файл/строки удаления и ссылку на тест до закрытия эпика. Матрица — приложение к реализации, не замена кода.

## 8. Топ-3 интеграционных риска

- **R1. Устаревшая UR-карта как «закон»**: acceptance-строки UR-06/07/08 всё ещё требуют `privacy_blocked`; если правится только код, ревью/следующие полосы восстановят вето по карте. Митигация: S1 включает правку карты, CRM фиксирует supersede.
- **R2. `direct_chat_service.py` — самый общий файл**: параллельная правка BGS-02 против полос UR-D/UR-E (обе в scope файла) создаст конфликт в тех же регионах (5413/13182, hint-петля). Митигация: серийная врезка по цепочке A→C→D→E, один писатель в момент времени.
- **R3. PVR-FC не стартовала, но её scope = factcheck_***: если FC-BACKEND начнёт до S1/S4, `_strip_privacy` и metatext-retry будут переписаны/возрождены (VERIFIED-строки review-06g3 считаются инвариантом). Митигация: порядок S1/S4 → FC-BACKEND, строка CRM «06G.3 → ЗАМЕНЁН», запрет повторного ввода деперсонализатора.

## 9. Наблюдаемость/приёмка (сводно)

- События: privacy-кодов нет в новых трассах; `EVIDENCE_EGRESS_CHECK` — только наблюдение; guard-события public_speech — только детект; фактическая доставка = L2-оригинал ± явно объяснённые владельческая нормализация и техническая санитаризация.
- Регресс-матрица BGS §9 (A–J) — на реальных вызовах с манифестами, не только unit-моки; DoD §9 (7 пунктов) — критерий закрытия эпика.
