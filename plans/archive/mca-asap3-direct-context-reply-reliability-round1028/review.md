# review.md — `mca-asap3-direct-context-reply-reliability` (ASAP-3, round 1028)

- **Feature-ID:** `mca-asap3-direct-context-reply-reliability`
- **Risk-Level:** R3 (подтверждён: production-critical direct-контур; blast radius проверен по фактическому диффу)
- **Status: APPROVED** (round 2 — rework re-review, 29.09.2026; финальный вердикт дельты H1/H2/H3/M1 — секция «Round 2» внизу. Round 1: NEEDS FIXES 3 High + M1 — все подтверждённо закрыты)
- **Дата review:** 29.09.2026 (независимый Reviewer gate: requirements/correctness + focused change audit, одна гейт-процедура)

## Binding

| Поле | Значение |
|---|---|
| Reviewed-Commit | `87728dc81e3f2508beca3bc1a8c58e9748ec24c8` (HEAD). Заявленный в задаче `8a0fa6c` — это прод-деплой-коммит ASAP-2.1 (базлайн 2.58.34); `8a0fa6c..HEAD` — 2 docs-only коммита (plans), кодовая база не менялась — проверено `git diff --stat` |
| Объект review | HEAD `87728dc` + **незакоммиченное** ASAP-3-дерево в рабочей копии (коммитов фичи нет — иного и не заявлено) |
| Working-Tree-Hash | `a8c361becf1631b03f007b054a33d9f6fa42f8385e57097df086fa83d5b7b57d` — SHA-256 детерминированного манифеста (sorted path+file-SHA256, 43 записи): 35 файлов кода/доков (ASAP-3-скоуп + 2 пина чужих дельт: `tests/test_direct_chat.py`, `tests/test_tool_coordinator_round1026.py`) + 5 файлов `plans/features/mca-asap3-…/` + 3 файла artifacts/ (включая 2 скриншота Reviewer). Манифест НЕ включает сам `review.md` (артефакт review). Любое изменение файла манифеста инвалидирует binding |
| Spec-Hash | `83E7B0286A66C28E17BE97D2113A5C1EF9D40FEA6706DA08729A763251E285AA` (пересчитан `Get-FileHash` — совпадает с заявленным) |
| ADR-1028-2 Hash | `77C2F12AB6AF2E231130095F1025C83A690C3D627F8E058F1FC4255993F2356D` (совпадает) |
| Чужой WIP | ~190 dirty-файлов MCA-волны вне скоупа; в общие файлы (`direct_chat_service.py`, `web/index.html`, `web/api/routes.py`, `services/token_counter.py`, `tests/test_database.py` и др.) вмешательства чужого WIP отделены и перечислены в «Staging» |

## Git base и inspect scope

- База: HEAD `87728dc` (код == `8a0fa6c`), рабочий конфликт-free оверлей чужого WIP + ASAP-3.
- **ASAP-3 скоуп (35 файлов, отобран по "+"-строкам диффа с маркером ASAP-3 + новые файлы):** новые `services/model_capacity.py`, `services/direct_context_composer.py`, 4 новых тест-файла `tests/test_direct_{context_capacity,context_composer,context_scenarios,decision_matrix}_asap3.py`, `tests/js/round1028_asap3_direct_context_test.js`, `tools/_asap3_webapp_dev.py`; изменённые `services/direct_chat_service.py` (СМЕШАННЫЙ с чужим WIP mca-01/04a/07), `services/agentic_events.py`, `services/smartmodule_utils.py`, `services/param_catalog.py`, `config/settings.py`, `web/api/routes.py` (СМЕШАННЫЙ с mca-17a), `web/index.html` (СМЕШАННЫЙ с mca-17a), `web/app.js` (чисто ASAP-3, 3 хунка), `tests/conftest.py`, `pytest.ini`, `README.md`, F8-артефакты (`param-registry-round1025.tsv/.meta.md`, `screen-map-round1025.md`, `fixtures/round1025/{f8,catalog}_baseline.json`), ~15 старых boundary-тестов (count/version-пины).
- **`services/token_counter.py` (+76 строк): только чужой WIP mca-07** (protected spans, `estimation_method`); `resolve_context_tokens`/`safe_budget`/`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` — 0 изменений (D11 подтверждён по диффу и чтению функций).

## Checks performed (команда → факт → вывод)

1. **§0 граница Summary.** `git diff` по summary_* файлам фичи — пусто (Builder-дельта не содержит summary-файлов; `summary_memory.py`/`handlers/summary.py` — только чужой WIP, в списке файлов фичи их нет). `resolve_context_tokens`/`safe_budget` — 0 изменений (D11). Прогон summary-среза: `pytest test_summary_l1_clusterizer + test_summary_fact_package + test_token_counter + test_summary_l2_writer + test_summary_logging_runid + F8 + param_catalog` → **330 passed**. **Вывод: граница §0/D11 соблюдена.**
2. **Композер/арифметика.** Численное воспроизведение живым импортом: OLD `resolve_context_tokens(-1,5000)=32000` → `safe_budget=27826`; `39371>27826` → инцидент §1 воспроизводится точно. NEW `deepseek-chat → 131072 (model_map)`, external 5000 → reserve 13107 → `available=98230`, `policy(-1)=(98230,'unlimited')`; проверка «ровно одно деление»: `98230 == int((131072−5000−13107)/1.15)` — True. Политики: `0→(24000,'dynamic')`*  , `>0→cap`, мусор→dynamic, `None→dynamic`. (*24000 — из локального `.env` оператора `CHAT_CONTEXT_BUDGET_TOKENS=24000`; кодовый дефолт 16000 — spec корректен.) `MODEL_CONTEXT_WINDOWS` + env-override + `CHAT_UNKNOWN_MODEL_WINDOW=16384` + однократный WARN + `min(primary,fallback)` — по коду и 19 unit-тестам. **Вывод: §1–§7/§16 численно и кодом подтверждены; старый инцидент на ON-пути невозможен.**
3. **§52.A реестр caps.** `rg "resolve_context_tokens|safe_budget"` по direct-пути: на ON-пути композер не вызывает ни того, ни другого; оставшиеся вызовы `:3023-3028` — диагностика-инвариант, `:4565/:4701` — legacy-билдеры, которые при composer ON вызываются с `truncate=False`/заменяются parts-билдером. Rigid-доли `chat_budget_*_ratio` на ON-пути не применяются (путь `_compose_user_content`, `_apply_context_budget` недостижим — parity-тест `test_composer_on_skips_legacy_budget`). **Вывод: скрытый cap при −1 на ON-пути устранён.**
4. **Приоритеты §8/§12.** `BLOCK_PRIORITY`/`PIECE_KEEP`/`CANONICAL_ORDER` в композере; eviction P3→P2→P1, P0 `evictable=False`; tail-vs-thread: оба P1, тред — с floor, tail — без (см. H2); middle top-K ≤60 (см. H1 — dead code); per-chat `chat_thread_max_depth` → floor треда; walk ≤40. Порядок блоков payload не меняется (позиции = канонические слоты, тест `test_service_composer_materializes_canonical_order`).
5. **Матрица решений.** Force-гейт — в `handle()` ДО `_decision_pre_action` и ДО LLM (`direct_chat_service.py`, hunk `:1613+`): `_force_required → ACTION_REPLY/reason=force_direct`, шорт-каты не вызываются (тест `test_force_never_reaches_silent_branch`, e2e `test_bot_ok_gets_reply_not_silence`). `REASON_CODES` 15→16 аддитивно (тест `test_closed_vocabulary` 16; `test_force_direct_reason_code_registered`). `bot_replied_recently` независим (`_bot_replied_recently`, окно 600с по `bot_replies.last_used_at`; фикс `:1233`; тесты `TestBotRepliedRecentlyIndependence`). REACT — детерминированные наборы по классу, stable hash message_id, standard enum 4→9 аддитивно (fallback-порядок A8 не тронут). SILENT+🗿 — конъюнкция `_reply_bot ∧ addressed ∧ decision executed ∧ SILENT` + env AND per-chat гейты; not_addressed → без 🗿 (тест). Fail-soft: `react_moai` != ok → счётчик failed + событие + WARNING, текст не генерируется (тесты §44). **Вывод: §19–§29/§36 реализованы по контракту; тесты §41–§44 существуют и зелёные.**
6. **Observability.** `agentic_events.py`: +7 событий, `AGENTIC_EVENT_TYPES` 20→27 (тест enum 27 — зелёный); whitelists R17-полей для всех новых событий; `DIRECT_TRIGGER` без raw text (тест фильтрации). 9 счётчиков §46 — `DIRECT_METRIC_NAMES` ровно как в spec §5.3 (орфография autonomous), grep-строка `direct_metric name=… count=…`, снапшот в `get_process_accounting()["direct_metrics"]`.
7. **Miniapp/каталог.** `param_catalog.py`: +2 ключа в существующую `flags_decision_making` (order 23 сохранён), +0 групп/вкладок; Context Mode — derive существующего `limits.chat_context_budget_tokens` (без новых ключей, без миграций). `GET /api/direct/context-diagnostics` — read-only, RBAC `roles_srv.access_for` + `can_access_chat` (403), process-local, R17-числа, fail-open `available:false`. **Но см. H3 — silent-ack тумблер не доезжает до UI.**
8. **Тесты (прогнано Reviewer независимо).** 4 новых файла: **97 passed**. Полный pytest: **9963 passed / 11 failed / 1 skipped** (227s) — идентично Builder. Summary-срез: **330 passed**. JS: **50/50**. `gen_param_registry_round1025.py --check` → **CHECK OK (483)**. 11 failed — все pre-existing: worktree-проба на чистом HEAD воспроизвела 10/11 идентично; 11-й (`test_mca02_safe_fetch…`, trafilatura) — файл чужого WIP, на HEAD отсутствует физически; на HEAD дополнительно падают 4 stale-пина 2.58.32 (test-файлы, которые Builder атомарно обновил до 2.58.35 — в рабочем дереве эти 4 зелёные). **Ни одно из 11 падений не вызвано ASAP-3.**
9. **Boundary-пины (~50 старых тестов).** Покоммитный разбор «+»-строк 80 изменённых тест-файлов: у ASAP-3-атрибутированных — только count/version-пины (481→483, 456→458, 2.58.34→2.58.35, enum 27, REASON 16, reactions 9) и комментарии; семантические изменения в чужих тест-файлах (user_version 12→13 mca-14, MCA-02 egress и пр.) — чужой WIP, не ASAP-3.
10. **§48 запреты.** Ни одного «фикса»: множитель не удалён (1× на ON-пути), depth не «просто увеличен» (guarantee+expansion), `text[:N]` отсутствует (grep по композеру/сервису — 0), keep_head/keep_tail — не единственная стратегия (P-модель), summary не отключён, reply-to-bot остался autonomous, 🗿 конъюнктивен, словарь реакций расширен, LLM-ретраи не добавлены, Summary не переписан.
11. **Browser verification — НЕЗАВИСИМЫЙ реальный контур (см. отдельный раздел).**

## Browser verification (REQUIRED §53) — независимый прогон Reviewer

**Стенд:** dockerized PostgreSQL 16 (`postgres:16-alpine`, DSN из `.env` проекта) + схема `PgDatabase.init()` (19 таблиц, bot_settings=416 сидов, bot_admins/bot_roles) + реальные chat_profiles (2 чата) + prod-эквивалентный web-процесс (ConfigCache + ChatParamsCache + ChatParamsNotify LISTEN — wiring как `bot.py:1022-1035`; харнесс Builder'а `_asap3_webapp_dev.py` ChatParamsCache/listener НЕ поднимает). Сервер: `/healthz` → `{"status":"ok","version":"2.58.35"}`. Клиент: Playwright (чистый инстанс после закрытия контаминированной сессии Builder'а — у Builder'а оставался активный перехват `/api/**` с мок-ответами, из-за чего первый заход показывал мок-данные; проверено сравнением curl 419337 байт vs browser 2507), desktop 1280×800 + mobile 390×844, TMA initData, заминенный `API_TOKEN` из `.env` (пользователь 5885953495, global admin).

**Пройдено (реальный контур, реальные POST→PG→NOTIFY→GET):**
1. Context Mode рендер в карточке Direct Context; дефолт чата 24000 → корректный «Cap: 24000 (вручную)» (>0-derive).
2. Клик **Unlimited** (реальный клик) → `POST /api/config {limits.chat_context_budget_tokens: -1}` → 200 → строка в PG `chat_profiles.chat_params.overrides` + история `chat_lore_history`; UI → mode unlimited, кнопка активна.
3. Persistence after reload — после полной перезагрузки страницы чат A снова unlimited (−1 из PG).
4. Per-chat non-mixing — чат B одновременно cap 24000; клик **Dynamic** на B → value 0 (`chat_source:"chat"`, mode dynamic) → чат A остался unlimited. Никаких смешанных значений.
5. Описания §34 — дословно в UI (data-context-desc-unlimited/dynamic).
6. Секция «Принятие решений»: force keywords read-only (реальный configured `reactions.chat_botword_pattern`), тумблер «Автономные ответы на reply боту» (новый) и «Использовать реакции вместо ответа» (РЕЮС) рендерятся.
7. Диагностика: честный empty-state «Нет данных — композер ещё не запускался» (`available:false`); панель 7 полей рендерится при наличии данных.
8. Console errors = 0 (только favicon 404 — pre-existing), pageerror = 0.
9. Скриншоты: `plans/features/mca-asap3-…/artifacts/asap3_reviewer_desktop_1280_direct_context.png`, `…asap3_reviewer_mobile_390_direct_context.png` (+ мобильная вёрстка карточки 358px — OK).

**НЕ пройдено (→ H3):** тумблер **«Silent-подтверждение 🗿»** (`flags.chat_silent_ack_enabled`) в реальном контуре **не рендерится** — третьего обязательного тумблера §35 нет ни в базовых, ни в расширенных настройках группы.

**Ограничения (честно):** живой композер в реальном Telegram-диалоге не запускался (бот на стенде не поднят) — «живые» значения диагностики подтверждены кодом+тестами и честным empty-state; Telegram WebView — за владельцем (§56-G, спека это и требует). Ранее записанные проверки Builder'а выполнены на мок-контуре (in-memory `/api`), что скрыло H3.

## Requirement/evidence coverage (§37–§44 сценарий → тест)

| Сценарий владельца | Тест | Статус |
|---|---|---|
| §37 TEST 1 (39k при −1 без 39371→27826) | `TestUnlimited::test_test1_minus_one_no_hidden_truncation` | ✅ |
| §37 TEST 2 (thread 35k при −1 без cap 32000) | `test_test2_thread_no_hidden_cap` | ✅ |
| §37 TEST 3 (accounting при −1) | `test_test3_unlimited_still_accounts` | ✅ |
| §37 TEST 4 (external↑ → available↓) | `test_test4_growth_external_reduces_budget` + capacity unit | ✅ |
| §37 TEST 5 (window↑ → Unlimited↑) | `test_test5_window_growth_expands_unlimited` + `test_single_safety_multiplier` | ✅ |
| §38 (old episode verbatim + tail + summary-фон) | `TestOldEpisode::test_old_dialogue_returns_verbatim` | ✅ (см. оговорку H1 по middle) |
| §39 (lag 50/100/300/400 без brutal cut) | `TestStaleSummary::test_lag_composition_no_brutal_cut[4x]` | ✅ тесты, ⚠ композиция фактически «summary+весь tail» (H1) |
| §40 (цепь >6 hops) | `TestLongReplyChain::test_thesis_beyond_depth_6_reachable` | ✅ |
| §41 (force-матрица) | `TestForceReply` (4) + `TestTriggerMatrix` (6) | ✅ |
| §42 (autonomous) | `TestAutonomous` (5) | ✅ |
| §43 (фон без 🗿) | `TestSilentAckConjunction::test_not_addressed_silent_no_moai` + free_will-кейс матрицы | ✅ |
| §44 (fail-soft реакций) | `TestReactionFailure` (2) | ✅ |

DoD §54 1–22: покрыты задачами/тестами (карта tasks.md сверена); п.20 (miniapp↔backend) **нарушен фактически** — H3; п.8/11 — частично (H1/H2: recent verbatim держится, но минимальная гарантия хвоста и middle-композиция §3.7/§3.6 не реализованы как принято в спеке).

## Focused audit coverage

Изменённые/критические файлы прочитаны целиком или по диффу: оба новых модуля — полностью; `direct_chat_service.py` — все 37 хунков диффа (ASAP-3 отделены от чужого WIP mca-01/04a/07: answer-cache gate, EvidenceBundle, fact-attribution, write_transaction — чужие, не рецензируются как фича, но проверены на совместимость с ON/OFF-путями ASAP-3); settings/param_catalog/agentic_events/smartmodule_utils/routes/app.js/index.html/conftest/pytest.ini — полностью; F8-артефакты — дифф + `--check`; интеграционные рёбра: `mca_retrieval_context` (REUSE, untracked), `thread_chain` (committed), `chat_params` (per-chat хранилище), `bot_replies`, `get_messages_around`, `react_moai`, `emit_agentic_event`. Ошибка-пропагация: композер fail-open → legacy `_apply_context_budget` (проверено), все новые helpers — try/except с fail-open.

## Counterexamples checked (негативные/граничные)

- Инцидент §1 численно воспроизведён на OLD-пути и исключён на NEW (см. Checks 2).
- «бот, ок» при decision ON/OFF: при OFF (master `DIRECT_DECISION_MAKING_ENABLED=false`) force-гейта нет → легаси-поведение (документированный parity D10; допустимо, но см. Low-3).
- `bot_replied_recently=True` + force → REPLY (тест).
- per-chat `chat_autonomous_reply_enabled=false` → всегда REPLY (тест), но двойной подсчёт метрик (M2).
- reaction API fail → SILENT/REACT сохраняются, текста нет (тесты).
- unknown model → fallback 16384 + однократный WARN (тесты; window_source виден).
- Переполнение: physical_overflow флаг/событие (юнит), НО см. H2 о below-minimum пути.
- PG-stand: per-chat изоляция, reload, мобильная вёрстка, честный empty-state диагностики.
- Контаминация браузерной сессии Builder'а обнаружена и устранена (перехват `/api/**`); все браузерные факты пере собраны на чистом инстансе против реального сервера.

## Blocking findings

### [B-ASAP3-1] High — D5: importance-aware middle-подбор — dead code на живом пути (§3.7/§14/§39)
- **Где:** `services/direct_chat_service.py:2502-2508` (`parts["tail_rows"] = post_rows` — ВЕСЬ post-watermark; `parts["middle_rows"] = post_rows[:-tail_min]` — подмножество tail) + `:2707-2713` (`_compose_middle_lines`: дедуп middle-строк против `tail_tg`, построенного из ВСЕХ `tail_rows`).
- **Репродукция:** при наличии summary каждая middle-строка с tg_message_id присутствует и в tail → безусловно отсекается дедупом → `middle_lines == []` всегда (fixture-строки тестов тоже с tg-id; `TestStaleSummary` средний presence не ассертит — зелёный при мёртвой функциональности).
- **Импакт:** принятая композиция §3.7/D5 (summary + bounded top-K middle ≤60 + fresh tail) не выполняется: при stale watermark весь lag идёт verbatim в ОДИН tail-piece; spec-приёмка §39 выполнена «случайно» (ассерты слабые). Прямо противоречит спеке-контракту D5/§3.7 («unsummarized middle (ts > watermark, до tail_start) → bounded top-K»).
- **Исправление:** разделить куски: `tail_rows = post_rows[-tail_min:]` (fresh tail), `middle_rows = post_rows[:-tail_min]` (кандидаты middle); убрать дедуп-перекрытие (дедуп оставить только против реального tail). Прогнать §38/§39 с ассертом `middle_selected_messages>0` при lag>tail_min.
- **Проверка после фикса:** e2e lag 100 с уникальным маркером в middle и ассертом наличия middle-строк в payload; `CONTEXT_SELECT.middle_selected_messages>0`.

### [B-ASAP3-2] High — D6: минимум fresh tail (20) не enforced аллокатором; below-minimum без пути §17
- **Где:** `services/direct_chat_service.py:2695` — `floor_tokens=(thread_floor if kind == "thread" else 0)`: у `global_tail` floor=0; `services/direct_context_composer.py:259-298` — P1-эвикция режет tail до пустоты (floor 0), drop-фаза может выбросить tail целиком; `physical_overflow` ставится только если давление осталось после drop-фазы.
- **Репродукция:** собрать pieces как в проде (tail floor 0) с бюджетом между «tail целиком» и «tail-минимум» → tail режется ниже 20 сообщений без события `CONTEXT_PHYSICAL_OVERFLOW` (keep-end тихо). Юнит-тест `test_tail_floor_respected_while_p2_exists` маскирует дефект: он сам注入ляет floor (`_piece(..., floor=floor)`), который прод-код никогда не ставит. evidence T-4009 («пол … floor_tokens piece'а») не соответствует коду.
- **Импакт:** принятый инвариант D6/§3.6 («tail не ниже минимума; ниже — только путём §17 с событием») не выполняется: тихий below-minimum cut без наблюдаемости — тот же класс «молчаливой потери контекста», ради которого затевался эпик.
- **Исправление:** `floor_tokens` для `global_tail` = токены последних `CHAT_FRESH_TAIL_MIN_MESSAGES` строк tail-строк; ниже floor — только через `physical_overflow`-ветку (событие+счётчик). Тест: прод-wiring floor>0 + отсутствие тихого below-minimum; поправить evidence.
- **Проверка:** юнит «pressure между floor и full» → tail держит ≥20 строк; «pressure ниже floor» → `physical_overflow=True` + событие.

### [B-ASAP3-3] High — miniapp: тумблер «Silent-подтверждение 🗿» отсутствует в реальном контуре (§35/§5.4/DoD-20)
- **Где:** `services/pg_db.py:_seed_settings` (else: continue — PG-only спеки без `settings_field` не сидятся в `bot_settings`) + `web/api/routes.py:466` (GET /api/config итерирует ТОЛЬКО `cache.get_all()` = bot_settings) → `flags.chat_silent_ack_enabled` не попадает в items ни с chat-скоупом, ни глобально (проверено живым GET с X-Chat-Id: item отсутствует; UI-группа «Принятие решений» рендерит 2 из 3 требуемых тумблеров).
- **Репродукция:** реальный стенд (seeded PG + prod-wiring) → открыть «Ответы в чате» → чат → группа «Принятие решений»: есть «Автономные ответы…» и «Использовать реакции…», НЕТ «Silent-подтверждение 🗿». При этом `POST /api/config` ключ принимает (200, пишет глобальный слой в bot_settings — после ручной записи ключ «проявляется», но per-chat-поведение UI-слоя для владельца недоступно из коробки).
- **Импакт:** приёмка T-4029/§35 («ровно 3 тумблера… Silent acknowledgement», «переключения применяются backend-side и переживают reload») в реальном контуре не выполняется; владелец не может управлять 🗿 per-chat (только env-глобально). Browser-evidence Builder'а собрано на мок-/api-контуре и дефект скрыло.
- **Исправление (на выбор Architect/Builder):** (a) сидировать дефолт PG-only per-chat флагов в `bot_settings` (неразрушающе, ON CONFLICT DO NOTHING; +0 каталога), либо (b) включать в GET /api/config items PG-only `per_chat`-спеки из REGISTRY с env-дефолтом, либо (c) завести Settings-поле (F8 423→424, переиздание). Вариант (a)/(b) без Δ каталога предпочтительнее.
- **Проверка:** реальный стенд → тумблер рендерится, клик → per-chat override в `chat_profiles`, переживает reload; дефолт ON.

## Non-blocking debt

- **[M-ASAP3-1] Medium — CONTEXT_PRESSURE недо-эмитится:** `allocate_budget` пишет `excluded` только при полном дропе piece'а; полурезка (compression) без дропа не создаёт ни `excluded`, ни события `CONTEXT_PRESSURE` (поле `compressed_or_dropped` существует именно для этого). Наблюдаемость §32 ослаблена (частично компенсируется CONTEXT_SELECT). Чинить вместе с B-ASAP3-1/2.
- **[M-ASAP3-2] Medium (spec-typo → @Architect на reconcile): F8-числа спеки.** Спека §6/ADR D12 заявляют «481→482 / 456→457» при «+2 ключа» — арифметически невозможно (481+2=483; 456+2=458). Фактические значения подтверждены живым импортом: **REGISTRY=483, Settings dataclass=423, categorized=458, GROUPS=105, _TAB_BY_GROUP=103, TAB_RULES=21**; `tools/gen_param_registry_round1025.py --check` → CHECK OK (483); `test_param_catalog`/`test_round1025_f8_registry` — зелёные. «Исправленные значения для reconcile: 483/423/458/105/103/21» (Settings 423 верно и в спеке: +1 Settings-поле `CHAT_AUTONOMOUS_REPLY_ENABLED`, второй ключ PG-only).
- **[M-ASAP3-3] Medium — атрибуция счётчиков §46:** per-chat `flags.chat_autonomous_reply_enabled=false` инкрементит и `direct_force_reply_total`, и `direct_autonomous_reply_total` (hunks `:1655-1673` и `:1752-1758`) — не-force исход попадает в force-счётчик; исказит post-deploy-анализ §57.
- **[L-ASAP3-1] Low — `_resolve_direct_trigger` не применяет `_BOTWORD_EXCLUDED_USER_IDS` внутри handle():** excluded-пользователи (alan/kostik), отвечая боту реплаем с «бот» в тексте, получат гарантированный REPLY (раньше — Decision Making). Узкий кейс, Gate хендлера сохранён; требует осознанного решения Architect.
- **[L-ASAP3-2] Low — cosmetic:** `catalog_baseline.json` note-строка ASAP-3 reissue продублирована трижды (генератор), JSON функционально идемпотентен (F8 --check OK).
- **[L-ASAP3-3] Low — `direct_autonomous_silent_total` не инкрементится, когда silent-ack выключен (env/per-chat) — silent-исходы выпадают из метрики «слишком молчалив?»; считать исход до гейта ack.
- **[L-ASAP3-4] Low (release-integrity, не код):** `services/direct_chat_service.py` импортирует untracked-модули чужой волны `services/mca_gates.py` и `services/mca_retrieval_context.py` на уровне загрузки модуля — «единый релиз ASAP-3» физически не импортируется без staging хотя бы этих двух foreign-файлов (+ их зависимостей). DevOps: учесть в staging-перечне (см. ниже);@Orchestrator: решить порядок коммитов (ASAP-3 не самодостаточен в отрыве от волны).

## Staging-перечень (для DevOps; смешанные файлы — по хункам)

**ASAP-3 (стейджить):** 8 новых файлов (2 сервиса, 4 pytest, 1 JS-тест, 1 tools-харнесс); из изменённых — `config/settings.py`, `services/agentic_events.py`, `services/smartmodule_utils.py`, `services/param_catalog.py`, `web/app.js` (все 3 хунка), `tests/conftest.py`, `pytest.ini`, `README.md`, F8-артефакты (tsv/meta/screen-map/2 fixtures), пин-тесты (`test_param_catalog`, `test_round1025_f8_registry`, `test_decision_making_round1026`, `test_agentic_events_round1026`, `test_telegram_reactions_round1026`, `tests/js/round1025_hotfix{7,8,9,10}_*.js`, `test_direct_chat.py` — только asap3-хунки), `plans/features/mca-asap3-…/*`.
**СМЕШАННЫЕ (только ASAP-3 хунки):**
- `web/index.html`: СТЕЙДЖИТЬ хунки `@~1565` (карточка Direct Context) и `@~1659` (force-keywords read-only); **НЕ** стейджить хунки mca-17a `@~2365` (mca-metrics-block) и `@~4312` (mca-log-filters).
- `web/api/routes.py`: СТЕЙДЖИТЬ хунк `@~711` (`GET /direct/context-diagnostics`); **НЕ** стейджить mca-17a хунки `@~1674-1723` (фильтры `/status/logs` + `_is_global_admin`).
- `services/direct_chat_service.py`: ASAP-3 хунки = composer-контур, force/trigger/silent-ack, reaction-наборы, счётчики, parts-билдер, `_build_old_episodes`; **НЕ** ASAP-3 (чужой WIP mca-01/04a/07): answer-cache gate (`_legacy_text_replay_enabled`, `_answer_cache_disabled_notified`), EvidenceBundle (`_build_evidence_bundle`, `_bundle_scoped_slice`, `_block_with_tag`, out_excluded-проводка), fact-attribution (`_apply_fact_attribution`, `asker_user_id`), `write_transaction`-перевод `_reassign_fact_owners`. ВНИМАНИЕ: чужие mca-07 хунки того же файла импортируют `mca_gates`/`mca_retrieval_context` — см. L-ASAP3-4 (без них файл не импортируется вовсе; практический вывод — разделение «только ASAP-3» для этого файла не даёт работающего релиза без решений Orchestrator'а).
- `tests/test_direct_chat.py`: дельта — ЧУЖАЯ (mca-07 фикстура `_legacy_dedup_policy` + 2 теста answer-cache), НЕ стейджить в ASAP-3; в WTH-манифест включён как пин наблюдаемого состояния дерева.
**НЕ ASAP-3 (чужой WIP, не стейджить в релиз ASAP-3):** `services/token_counter.py` (+76, mca-07 — НО модуль нужен рантайму: protected spans импортируются композером! см. L-ASAP3-4), `services/database.py`, `handlers/*`, `services/summary_*`, `services/mca_*.py`, `services/{message_identity,provenance,safe_fetch,task_supervisor}.py`, все `tests/test_mca*`, mca-17a UI-хунки, `tools/ui_round1027_*`, `plans/archive/mca-*`.

## Unavailable checks

1. Живой прогон композера в реальном Telegram-диалоге (бот на стенде не поднят) — контекст-диагностика с живыми числами подтверждена кодом, тестами и honest empty-state; финально закрывается live acceptance §56-E/F.
2. Telegram WebView (iOS/Android) — владелец, §56-G (спека явно резервирует за владельцем).
3. §45 prod-log baseline (T-4003) — вне среды; grep-рецепт в evidence.md готов, включить в preflight DevOps (T-4038) — не блокёр кода, но обязательный шаг деплоя.
4. Live acceptance §56 / post-deploy §57 / gate §58 — по процессу после Fixes→re-review→deploy.
5. Нагрузочное поведение аллокации при lag≫1000 (O(tail-строк × halving-итерации)) — не замерялось; recommend замер в staging до прод-деплоя.

## Вердикт

**NEEDS FIXES.** Ядро фичи (root cause инцидента устранён численно и кодом; force-матрица; SILENT+🗿 конъюнкция; fail-soft; observability-контракты; OFF-паритет; F8-дисциплина с фактами 483/423/458; summary-граница не тронута) реализовано качественно и подтверждено независимыми прогонами. Блокируют три High: мёртвый middle-подбор (B-ASAP3-1), отсутствующий floor fresh tail с тихим below-minimum (B-ASAP3-2), нерендерящийся в реальном контуре silent-ack тумблер (B-ASAP3-3). После фикса — повторный re-review по затронутым линзам (композиция+аллокация+miniapp-реальный контур) с новым binding; далее деплой §55 и live acceptance §56–§58.

---

# Round 2 — rework re-review (дельта H1/H2/H3/M1) — 29.09.2026

- **Feature-ID:** `mca-asap3-direct-context-reply-reliability`
- **Risk-Level:** R3 (не пересматривался: дельта rework не расширяет blast radius — 3 backend-файла фичи + 3 тест-файла + docs)
- **Status: APPROVED**
- **Тип re-review:** дельта-валидация по затронутым линзам (полный re-review НЕ проводился — ядро round 1 не переоткрывалось). Код не правился, коммитов нет.

## Binding (round 2)

| Поле | Значение |
|---|---|
| Reviewed-Commit | `87728dc81e3f2508beca3bc1a8c58e9748ec24c8` (HEAD не менялся с round 1; фича по-прежнему незакоммиченное дерево) |
| Working-Tree-Hash | `8b7db5ad8d2f32d864e6ce558844283124ee543318f4ac2239f02e0fa96cf295` — **пересчитан Reviewer независимо** по рецепту round 1 (sorted path+file-SHA256, 41 запись, missing=0): совпадает с заявленным Builder и с манифестом `artifacts/wth_manifest_rework1.json`. Манифест не включает evidence.md/review.md (само-ссылка — прецедент round 1) |
| Spec-Hash | `83E7B0286A66C28E17BE97D2113A5C1EF9D40FEA6706DA08729A763251E285AA` (Get-FileHash — не изменился) |
| ADR-1028-2 Hash | `77C2F12AB6AF2E231130095F1025C83A690C3D627F8E058F1FC4255993F2356D` (не изменился) |

## Git base и inspected change scope (round 2)

База та же: HEAD `87728dc`. Дельта rework по mtimes + списку Builder подтверждена: файлы rework — окно 10:52–11:26 (`agentic_events.py`, 2 asap3-тест-файла, `test_agentic_events_round1026.py`, `direct_context_composer.py`, `direct_chat_service.py`, evidence/tasks); всё остальное скоупа — до 09:09 (`index.html` 09:09, `app.js` 07:46, `routes.py` 07:43, `param_catalog.py` 07:52, `settings.py` 08:24); `pg_db.py` — 25.09 (не тронут вовсе); `token_counter.py` 01:15 (чужой WIP, не тронут). Проверено чтением всех затронутых хунков: сплит parts (`:2502-2514`), `_compose_middle_lines` (`:2913-2948`), пост-аллокационный дедуп (`:2762-2781`), wiring пола (`:2693-2716`), clamp-событие (`:2783-2801`), emission PRESSURE (`:2868-2877`), `tail_floor_tokens` (composer `:165-174`), victims-set (`:270-319`), emit-функция (`:682-690`), enum/whitelist (`agentic_events.py:74/92/164-165`).

## Checks performed (round 2)

1. **H1 (middle top-K жив):** сплит `tail_rows=post_rows[-tail_min:]` / `middle_rows=post_rows[:-tail_min]` с guard'ом длины; дедуп по tail-кандидатам из `_compose_middle_lines` УБРАН (теперь чистый bounded top-K ≤60, хронологический ASC, стабильная сортировка); пост-аллокационный дедуп — против tg-id ФАКТИЧЕСКИ вошедшего tail (regex по тексту final tail piece), обновляет и payload, и `middle_lines` → счётчик `CONTEXT_SELECT.middle_selected_messages` честный. Слабые ассерты round 1 заменены: lag400 — middle реально в payload, весь tail-флор вербатим (оба маркера -0 и -19), `0<middle_selected≤60`, clamp-событие, детерминизм (два прогона на свежих сервисах → идентичный набор); lag50 — `middle_selected==50`, каждая строка ровно 1 раз. Оба теста зелёные поимённо.
2. **H2 (пол fresh tail):** `tail_floor_tokens` — реальный расчёт (токены последних N непустых строк); wired в piece `global_tail` прод-путём (`floor=(thread_floor if thread else tail_floor if global_tail else 0)`); `CONTEXT_TAIL_FLOOR_CLAMPED` эмитится при engaged-давлении (compressed/excluded/overflow) и непустом tail; enum A9 27→28 аддитивно (+whitelist final_messages/floor_messages; enum-тест 28 зелёный); ниже пола — только `CONTEXT_PHYSICAL_OVERFLOW`+счётчик. `test_tail_floor_real_wiring_enforced` — пол вычисляется ПРОДА-функцией `tail_floor_tokens` (самоподстановка round 1 убрана); `test_below_floor_is_physical_overflow_not_silent_cut` — зелёные. **Независимый динамический проб Reviewer:** (а) e2e handle() при давлении НИЖЕ пола (budget 900 < P0+head+tail≈1070) → tail цел (20 строк, оба маркера), `CONTEXT_PHYSICAL_OVERFLOW` (available=900, needed=998, preserved∋global_tail) + CLAMP — тихой резки нет; (б) контрфактический A/B на чистой функции: floor=0 → тихая резка до 10/5 строк keep-end без единого события; wired-пол → tail цел 20 строк + §17. Wiring доказан: именно пол (а не случайность давления) защищает tail.
3. **H3 (data-op, код не менялся):** подтверждено mtimes + F8 `--check` OK (483) — каталог/pg_db не тронуты. SQL сида в evidence.md сверён с DDL: `bot_settings(key TEXT PRIMARY KEY, value JSONB NOT NULL, category TEXT NOT NULL)` → `ON CONFLICT (key) DO NOTHING` валиден; `'true'::jsonb` соответствует; category `'flags'` == каталогу (`("flags.chat_silent_ack_enabled","flags",…)`) и SEED_CATEGORIES. **Динамический проб на throwaway PG-16 (точный деплой-порядок):** старт бота (ConfigCache.init → DDL+каталог-сид) → `flags.chat_silent_ack_enabled` ОТСУТСТВУЕТ (дефект round 1 воспроизведён; autonomous-ключ сидится сам — Settings-поле) → DevOps SQL из evidence → рестарт → **оба ключа в конфиг-пути GET /api/config** (value=true, spec visible: not hidden/not secret, per_chat=true, группа flags_decision_making). Повторный сид идемпотентен; осознанный админский OFF переживает повторный сид (ON CONFLICT DO NOTHING). Follow-up `param-catalog-pg-only-seed-config-exposure` подтверждён в plans/backlog.md («⚡ Follow-up (reconcile ASAP-2, 28.09.2026)», 🟦 К ПЛАНИРОВАНИЮ).
4. **M1 (pressure на полурезку):** victims-set по id(piece) — каждая жертва ≤1 раза: полурезка → `compressed_or_dropped+=1` (:294-296), полный дроп не задваивает (:311-313); emission `if allocation.excluded or allocation.compressed_or_dropped` (:2869). `test_compression_without_drop_counts_as_pressure` (полурезка → compressed≥1, excluded пуст, piece жив) — зелёный.
5. **Прогоны (Reviewer, независимо):** срез 11 затронутых файлов → **583 passed / 1 failed** (1 = pre-existing `test_forbidden_paths_out_of_diff`, вне дельты); parity OFF `TestComposerFlagParity` → **3 passed**; summary-срез (l1_clusterizer/fact_package/token_counter/l2_writer/logging_runid/param_catalog/f8_registry) → **330 passed**; JS → **50/50**; F8 `--check` → **CHECK OK (483)**; полный pytest → **9967 passed / 11 failed / 1 skipped** (232s) — 11 failed поимённо идентичны round 1 (mca02_safe_fetch/trafilatura; outgoing_guard ×2 rich; summary_cover ×3; summary_asap2_failsoft; summary_publish_integration; tool_coordinator forbidden_paths; webapp_hotfix8/9 tokens) — все pre-existing, вне дельты. 9963→9967 = +5 новых rework-тестов минус 1 заменённый слабый.
6. **Хэши:** WTH пересчитан независимо (совпадает, см. Binding); Spec/ADR — не изменились.

## Browser verification (round 2)

UI-дельта rework **отсутствует**: изменённые rework-файлы — только backend/тесты/docs (см. scope); `web/index.html`, `web/app.js`, `web/api/routes.py` не менялись с момента round 1 (mtimes до окна rework; хэши запинены в WTH-манифесте). **Browser pass round 1 (реальный контур: dockerized PG + prod-wiring + Playwright, desktop/mobile, скриншоты в artifacts/) остаётся в силе** для текущего состояния UI. Остаточное H3-подтверждение (рендер 3/3 тумблеров после сида + клик → per-chat override → reload) по построению выполняется на деплой-гейте T-4038/§56 — сид применяется DevOps при деплое; механизм экспозиции и рендера при наличии строки доказан (round 1 реальный стенд + round 2 динамический проб конфиг-пути).

## Requirement/evidence coverage (round 2, только затронутое)

| Пункт | Проверка | Статус |
|---|---|---|
| §3.7/D5/§39 (middle top-K ≤60) | код + lag400/lag50 тесты | ✅ закрыт |
| §3.6/D6/§17 (пол tail / overflow) | код + 2 юнит-теста + независимый проб (e2e+A/B) | ✅ закрыт |
| §32 (CONTEXT_PRESSURE полнота) | victims-set + emission OR + тест | ✅ закрыт |
| §35/§5.4/DoD-20 (3/3 тумблера) | SQL+DDL+каталог сверка; динамический проб exposure; рендер — деплой-гейт T-4038/§56 | ✅ закрыт код-ревью; live — на гейте |
| §30–§33 enum A9 28 | enum-тест 28 + whitelist | ✅ |

## Focused audit coverage (round 2)

Все хунки дельты прочитаны (перечень в scope); тесты rework прочитаны полностью (ассерты не слабее рецептов round 1: presence+cap+event+детерминизм вместо голых счётчиков); чужой WIP не затронут (mtimes + списки); интеграционные рёбра дельты: allocate_budget↔`_composer_truncate` (keep-end middle/tail, keep-head head — не менялись), victims-set↔excluded-финализация (пустые pieces в :339-345 не задваиваются — id-guard), clamp-событие↔whitelist (R17: только числа), пост-дедуп↔`CONTEXT_SELECT`/диагностика (тот же middle_lines).

## Counterexamples checked (round 2)

- Давление ниже пола (budget 900 e2e; 300/200 A/B) → overflow+события, tail цел; контрфакт floor=0 → тихая резка (воспроизвёл дефект round 1 на текущем коде — пол реально работает).
- lag50 без давления → middle отбирается и не дублируется (каждая строка 1 раз).
- Полный pytest: 11 падений — те же pre-existing поимённо (дельта не добавила ни одного).
- Повторный SQL-сид / админский OFF → идемпотентно, выбор админа не перетирается.
- Свежая БД без сида → дефект H3 воспроизводится (сид необходим и достаточен для экспозиции).

## Blocking findings

Нет.

## Non-blocking debt (перенесён из round 1, без изменений)

[M-ASAP3-2] F8 spec-typo 482/457 → факты 483/423/458/105/103/21 (@Architect, reconcile); [M-ASAP3-3] двойной счётчик force/autonomous при per-chat OFF; [L-ASAP3-1] `_BOTWORD_EXCLUDED_USER_IDS` внутри handle(); [L-ASAP3-2] cosmetic ×3 note в catalog_baseline; [L-ASAP3-3] autonomous_silent_total при ack-off; [L-ASAP3-4] release-integrity untracked foreign-модулей (порядок коммитов — @Orchestrator).

## Unavailable checks (round 2)

1. Живой прогон композера в реальном TG-диалоге — §56-E/F (как round 1).
2. Telegram WebView — владелец, §56-G.
3. §45 prod-log baseline — DevOps preflight T-4038.
4. Live acceptance §56 / post-deploy §57 / gate §58 — после деплоя.
5. Нагрузка аллокатора при lag≫1000 — рекомендованный staging-замер.
6. Визуальный рендер 3/3 тумблеров + per-chat клик после сида — на реальном стенде деплой-гейта T-4038 (стенд round 1 не запущен; экспозиция/механизм проверены динамически — см. H3).

## Вердикт (round 2)

**APPROVED.** Все четыре finding'а round 1 (B-ASAP3-1/2/3, M-ASAP3-1) закрыты в точности по рецептам ревью, с более сильными тестами, чем требовалось: middle-подбор жив и наблюдаем; пол fresh tail wired реальным расчётом и ниже пола работает только §17 (доказано независимым контрфактическим пробом); silent-ack тумблер доезжает до конфиг-экспозиции через задокументированный идемпотентный data-op (проверен на живом PG), системный фикс зарегистрирован в backlog; полурезка считается pressure-сигналом. Регрессий дельта не внесла (полный pytest 9967/11 — те же 11 pre-existing). Чужой WIP не тронут. Binding: HEAD `87728dc` + WTH `8b7db5ad…cf295` + Spec `83E7B028…285AA`. Далее по процессу: §55 деплой (staging-перечень round 1 + SQL-сид preflight T-4038) → live acceptance §56–§58; non-blocking debt — в бэклог.
