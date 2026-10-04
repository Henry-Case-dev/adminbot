# mca-06-sleep-paradigms — Review (final acceptance gate T-4732, R3)

Reviewer: @Reviewer (независимый gate). Дата: 04.10.2026. Вердикт ниже.

## Binding (reviewed state)

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48) + рабочие изменения mca-06 (без коммитов, R18).
- Working-Tree-Hash (Reviewer WTH, recipe: SHA-256 конкатенации per-file SHA-256 по 21 leaf-файлу git-status scope — 13 код/тест-файлов + feature-docs + reports; исключены `.playwright-mcp/`, `extra_images/`, `node_modules/`, `package*.json`, `verification_cache.json`):
  **`790C32120C46AFFA1AE0BD89270A277F1565A59C7C025B0BE1E6892DEC67CDE2`**
- Docs-хэши: spec `671936E6DD202FA9:`, ADR-1028-9 `766BDF09C253555E:`, tasks `4961E7FA2C68D49F:`, threat `D417CE4D5EABE6E1:`, requirements-map `2D4207F1221287BD:`.
- Код в ходе review не изменялся; рабочие правки — только мои проверки в temp вне репо.

## VERDICT: NEEDS FIXES (0 Critical / 0 High / 1 Medium-blocking [M-1] / 1 Medium-DoD [M-2] / 3 Low non-blocking)

Release-gate открывается сразу после микс-фикса отчёта прогона [M-1] (isolated, небольшой diff) и явного разрешения [M-2] (doc-only, Architect/Owner). Остальное — Approved-уровень.

## Проверено и подтверждено (owns-cheks)

1. **Gate-resolver (D1/D6, A91):** `mca_gates.resolve_dream_gate` — фиксированный порядок §3.2 (memory_service_missing → master → deep → rag_off → schedule → queue → cooldown → resource), 8 различимых причин в закрытом множестве `DREAM_GATE_REASONS` (тест `test_no_second_human_gate_reasons_are_closed_set`); sources chat/global/env/default + конкретный `detail` (имя ключа/лимита). Единый словарь — аддитивное расширение `mca_events.REASON_CODES`; `_DEEP_REASON_MAP` не дублируется (UI-ремап остался для legacy-лога). 4 потребителя — идентичный ответ (resolver — чистая функция; врезка worker/API/UI сверены). Human-gate не создан.
   - **Master/deep split + backward-compat:** `web/api/memory_agi.py::deep_sleep_status` — resolver вызывается **только** при `resolver_on and service_available` (`worker is not None and worker.memory is not None`); иначе OFF-паритет 2.58.48 (`master_off`-обобщённость, нули-при-ошибке) без `memory_service_missing` и без аддитивных полей — 5 регрессий round1024 закрыты, путь service-absent не течёт в `memory_service_missing` (evidence «регресс-фикс B+C», 7 passed frozen + `test_resolver_off_parity`/`test_master_deep_split`).
   - `counters_error` ≠ нули ≠ disabled (A91; `test_counters_error_not_zeros`).
2. **Исторические кандидаты (D3/D4, О5, A92):** `mca_dream_history.select_historical_candidates` — pre-limit ≥4×top_k → **возраст/период/scope-фильтр и дедуп ДО финального top_k** (`limits.deep_sleep_top_k` не тронут); возраст строго по `message_timestamp` (`rag_ts`/`created_at` не подставляются: `mca_dream_history.message_timestamp_of`), отсутствие времени → `missing_timestamp++` + не проходит порог (`test_age_uses_message_timestamp_not_created_at`); fixture «20 свежих + 1 старый» → старый в кандидатах (`test_old_relevant_survives_final_top_k`). **FTS-фолбэк без vec-предусловия (О12/CA-10):** сам канал `_search_graph_facts` уходит в FTS при неактивном vec-поколении; `_vec_available=False` не блокирует профиль (`test_fts_fallback_without_vec_precondition`); честный `no_anchors` при пустом результате — штатная ветка, не ошибка. Episодические кандидаты (`EpisodeRepository.list_episodes`) и resumable enrichment (bounded, checkpoint, `paused` ≠ гильотина) — есть, тесты зелёные. Легаси-путь (`get_rag_facts → top_k → возраст`) сохранён дословно как OFF-ветка. RAG-ошибка при профиле → `rag_failed`/`error` в worker-врезке (fake-канал умеет бросать; примечание L-4 ниже).
3. **Evidence core (D7/D8, О1, О6, О14, AM-5):** независимость по `(chat_id, tg_message_id)`/SourceRef (`primary_event_key`) — 2 пересказа одного tg=7 → independence=1 (`test_two_retellings_one_message_is_one`, S1); **порог «2 независимых якоря» не снижен** — hard gate `len(independent_keys) < 2 → insufficient_evidence` (`dream_worker.py:1908`), round1021-константы (top_k=20/max_paradigms=3/tokens=40000) не тронуты; `bot_self_reply` исключён из independence (`is_bot_self` → `provenance.is_self_referential_origin`, test-контрпример + `test_bot_self_excluded_from_independence`); 10-статусная матрица `DREAM_STATUSES` + `LEGACY_STATUS_MAP` (словарь один, `__main__`-маппинг disable/error/no_context/no_anchors/insufficient_evidence/unchanged/duplicate/budget/cooldown/written); мост-валидатор — 5 проверок (субъект/`time_order`/semantic_bridge/contradictions-сужение/`source_resolved`), случайная пара старых фактов → отказ (`test_random_old_fact_no_subject_insufficient`), обратный порядок → `insufficient_evidence` (S3b); типизация якорей через REUSE `provenance` (`anchor_source_ref` → message/graph_fact, v17-таблицы, honest unknown при отсутствии refs; `record_anchor_items_provenance`); supersede EvidenceLink + AM-5 applicability/valid_from/valid_to в `belief_meta` JSON — DDL=0 (`test_narrowed_applicability_in_belief_meta`); bounded RevisionQueue (cap=20, dead-dedup, pause) с kill-switch.
4. **Квоты/backoff/singleflight (D9, О3/О10, A93):** `count_deep_attempts(since_ts, *, chat_id)` — per-chat подсчёт поверх `memory_dream_log` с теми же kind/status правилами (реальная БД-тест); глобальный кап сохранён и не снят (`test_global_cap_still_works`); чат 1 с исчерпанной per-chat квотой не блокирует чат 2 (`test_single_chat_fails_only_its_per_chat_quota`); backoff — ограниченный экспоненциальный (base/cap env, cap-тест), различим в `detail`, сброс при новых dream-данных (S4b/`test_backoff_reset_on_new_data`); cooldown не подменяется master_off. Singleflight per-chat (`_deep_chat_inflight`) + manual anti-race recheck (`last_deep_attempt >= request_ts → skip`) + OFF-паритет recheck.
5. **mca-17a + durable отчёт (D5/D11, О11):** `sleep.deep` code-declared в `mca_process_registry` (стадии queued/collect/anchors/bridge/write, LLM-стадия — законная длительность, OFF → честный `not_run`); run-строка на каждый запуск (включая скип) через `mca_trace.start_run/finish_run/set_run_report`; **DDL v25** (`chat_id`/`report_json` + `idx_mca_pipeline_runs_chat`) через реестр mca-14 (MigrationStep, guard table_info/index, повтор = no-op — `test_v25_idempotent`); отчёт 8 групп = ровно `REPORT_GROUPS` (S-сценарии + `test_report_has_all_eight_groups`); R17-тест «нет сырого текста» + собственный осмотр `_deep_report_json` (только ID/счётчики/причины/диапазоны/seed-мета, cap 8000/списки). Исключение: причины отсева — [M-1] ниже.
6. **Граница AM-3 / RandomSource (О15, О13, THR-8/9):** structural boundary — `dream_worker.py` не содержит ни одного из `CHARACTER_CORE_WRITE_API`; traits пишут только `append_traits`/`record_trait_status` (derived-слой, spy-тест fix ON и OFF); ядро — зона mca-18, не эскизируется. `DreamRandomSource.pick(seed=(pipeline_run_id, chat_id))` — единственный селектор материала при explore-ON; вердикт только по доказательствам (`test_verdict_from_evidence_not_from_random_material`); explore-OFF → прежний ранжед-пайплайн, `selection` в отчёте отсутствует.
7. **OFF-паритет (THR-14, О13):** по всем слоям есть прямые OFF-тесты: resolver (`test_resolver_off_parity*`), API (тот же), quotas (`test_quotas_off_parity_global_only`), reports (`test_reports_off_no_run_row_no_events`), recheck (`test_manual_recheck_off_parity`), evidence typing (`test_evidence_typing_off_legacy_min_anchors`), explore (`test_explore_off_no_source_ranked_parity`), revision queue OFF→enqueue=0. **Исключение:** `MCA_DREAM_HISTORICAL_PROFILE_ENABLED` отдельного OFF-теста не имеет [L-1]; OFF-ветка при этом — тот же неизменённый legacy-код (:1873–1887), и он реально исполняется тысячами замороженных тестов, чьи фейки не имеют `retrieve_fact_candidates` → бит-в-бит гарантирован фактическим исполнением, но dedicated-теста нет. Состав и имена всех 7 kill-switch — в `mca_gates.KILL_SWITCHES` + `settings.py` (env-only, Δ каталога = 0 подтверждён F8=488).
8. **DDL v25 additive mca-14:** fresh in-memory `user_version 25`, колонки/индекс есть; `_migrate_dream_runs_v25` — guard + `IF NOT EXISTS`-индекс, без UPDATE/DELETE; PG вне diff (no-op, GEN-R4); fail-closed backup pre-DDL — на стороне release-процедуры T-4734 (DevOps).
9. **Version-pin дрейф легитимен:** все 6 падений полного прогона у Builder = pins v24→25 (mca-05 tail + 2 summary-fresh-init) и allowlist 155→159 (+4 commit `_migrate_dream_runs_v25`; все имена в `_migrate_` → guarded, `unguarded == []`). Не маскировка: мои независимые прогоны этих файлов и полный suite — зелёные. R17-визи: дифф не содержит секретов/ключей/сырых текстов (осмотр `_deep_report_json`, `_trace_deep`, метки app.js).
10. **Scope creep:** 27 R06 REQ ↔ блоки B–I; дифф соответствует скоупу (config/settings kill-switches + лимиты, gates, dream_history/evidence/random, worker врезки, trace/registry/events, API, app.js-метки карточки, тесты/tools). `allowed drift`-документы (metrics/workflow_state/arch-frames) — за пределами код-вопросов. Порог/капы round1021 не тронуты; второго резолвера/второго run-store/второго provenance-контракта/второго словаря — нет.
11. **Прогоны (все запущены мною заново, независимость):**
    - **Полный pytest: `11294 passed / 0 failed` / 1 warning, 360.36s** (детached, `-q -rf --tb=line`) — совпадает с ожиданием; 2 known-fails не воспроизвелись.
    - Точечный набор mca-06+соседей (12 файлов, вкл. 5 mca-06 файлов + round1024/manual-cascade/pins): **347 passed**.
    - **JS: 55/55 pass**, 0 fail (`node --test tests/js/*_test.js`).
    - **F8 `gen_param_registry_round1025.py --check`: CHECK OK, реестр 488**, Δ каталога = 0; `node --check web/app.js` OK; `py_compile` 18 изменённых файлов OK.
    - **A14 на реальном API (Reciever-скрипт, HTTP-слой):** живая FastAPI/jоутер `/api/memory/dream/chain` (TestClient, prefix `/api`) на SQLite v25 + `record_anchor_items_provenance`/`record_source_ids_provenance` → 200; обе группы ссылок (graph_fact-источник пакета + message-якоря) резолвятся до `(chat_id, tg_message_id)`=`{(-123,101),(-123,102)}`; `delta` = new+old+supersedes. deep-sleep карточка 200 (legacy-ветка при service-absent, честно).
    - **Playwright (T-4706) повторён независимо:** `tools/ui_mca06_sleep_card.py` → EXIT=0, 3 fixture-конфигурации (off/master_off/resource_limit), конкретные диагнозы с именем ключа/лимита, 0 console errors.

## Findings

### [M-1] Medium, requirement-blocking — отчёт §7.2: «причины отсева» не заполняются
- **Место:** `services/dream_worker.py` — `_deep_report_json` (246–297) читает `report["reject_reasons"]`, но **ни один writer его не заполняет** (grep: единственные два вхождения — consumer в `_deep_report_json`; в `_run_deep_once_core` bridge-отказы/профиль-фильтрация пишут только `_trace_deep`-лог и счётчики `anchors_filtered`/`validation.bridge_reject`); профильные счётчики `excluded_young`/`duplicates` из `HistoricalSelection` тоже не попадают в отчёт (только `missing_timestamp`).
- **Нарушено:** §7.2 п.2 (`current_task.md:378`) — «якоря найдено/отсеяно/независимые + **причины отсева**»; критерий T-4727; ослабляет THR-1/THR-2-наблюдаемость (отчёт не объясняет, почему якоря отсеяны).
- **Evidence:** grep (см. выше); тесты assert только `set(rep)==REPORT_GROUPS` — пустое содержимое `reject_reasons` не проверяется.
- **Impact:** Owner-требование к составу отчёта выполняется частично; диагностика «почему нет парадигмы» требует смотреть логи вместо durable-отчёта.
- **Corrective (маленький, изолированный):** в `_run_deep_once_core` при bridge-отказе аккумулировать `reject_reasons` из `bv.reason`; при профиле писать `result.excluded_young`/`result.duplicates` (и где применимо — reason) в `_rep`; добавить asserts в TestRunReport. Kill-switch-совместимо (только отчёт).
- **Верификация после фикса:** `pytest tests/test_mca06_sleep_fg_round1035.py tests/test_mca06_sleep_i_round1037.py` + отчёт-fixture с 2 отказами (no_subject/time_order) содержит заполненные причины в report_json.

### [M-2] Medium, DoD-неопределённость — T-4718 Browser-Verification («Playwright-проверка раскрытия», карточка delta) не выполнена; UI-рендер цепочки отсутствует
- **Место:** spec §12 (Browser-Verification REQUIRED) и tasks T-4718 (`[x]` с criterion «Playwright-проверка раскрытия») против факт: `web/app.js` не вызывает `/api/memory/dream/chain` (0 референсов), delta-карточка не рендерится; evidence заметка «Остатки: Playwright-карточка delta и UI-рендер unchanged» (tasks.md:76) не закрыта в блоках G/H/I.
- **Признаётся:** сам факт A14 «обе группы ссылок раскрываются» верифицирован на **реальном API** (см. мой HTTP-чек) — сужение критерия не нарушено; витрина «Аналитики» — формально mca-17c (GEN-R17, spec §1.2), и owner-текст :342 может раскрываться на реальном API + витрине иного фичи.
- **Нарушено (буквально):** spec §12 обещал Playwright-проверку раскрытия цепочки в mca-06; обещание не исполнено и не отменено явно. Несогласованность spec внутри фичи (§8.2 карточка vs §1.2 витрина=mca-17c).
- **Corrective (doc-only):** @Architect правит spec §8.2/§12/tasks T-4718 DoD: раскрытие цепочки — API-контракт (верифицирован реальным API-тестом), рендер delta-карточки — mca-17c; Playwright-проверка рендера переносится в T-фильтры mca-17c. Либо Owner требует UI-рендер сейчас — тогда это Builder-задача до release.
- **Верификация:** amended spec + ссылка на мой A14-real-API-check в evidence.

### [L-1] Low — нет dedicated OFF-теста `MCA_DREAM_HISTORICAL_PROFILE_ENABLED`
Legacy-ветка (:1872–1887) дословно сохранена и реально исполняется замороженными тестами (фейки без `retrieve_fact_candidates` пойдут на OFF-путь), но сверка на fake-памяти с двумя каналами + выключенным рубильником отсутствует. Не блокирует (структурная гарантию сохранения пути); рекомендовано добавить 1 тест воне [M-1]-фикса.

### [L-2] Low, doc-only — дрейф базовой версии в spec/ADR
spec/ADR-1028-9 (D12/AM-4, §11.3) говорят «bump 2.58.47→2.58.48», тогда как HEAD уже 2.58.48 (asap-4-2 Released round1032) и реальный релиз mca-06 = **2.58.48→2.58.49** (workflow_state так и описывает T-4734). OFF-паритет по совету Orchestrator'а — честно привязан к 2.58.48 (evidence согласован). Поправить текст spec/ADR при release-коммите.

### [L-3] Low — UI-мэппинг `unchanged→empty` (`_DEEP_REASON_MAP` :531 + отсутствие label `unchanged` в app.js)
unchanged/ошибка/дубль различимы в API (raw status честен в `log[]` rows и в report_json; `duplicate`/`error` имеют метки), но `unchanged` в empty-state UI сливается с общим «источников пока недостаточно». A94 (уровень API) выполнен; предсуществующее решение round1024 сохранено (паритет). Рекомендация: добавить метку `unchanged` в app.js при следующей UI-правке (mca-17c-зона).

## Acceptance summary (A14/A91–A94, дословная сверка)

| Приёмка | Дословно (якорь) | Статус | Evidence (Reviewer) |
|---|---|---|---|
| A14 (:895) «Парадигма из пакета и исторических якорей — обе группы ссылок раскрываются» | :340/:342/:350 | OK (API-уровень; UI-рендер — [M-2]) | Мой HTTP-тест реального роутера: обе группы → `(chat_id, tg_message_id)` `{101,102}`; i-round S2: chain → `{1,2}`; delta new+supersedes |
| A91 (:972) «UI и worker показывают один effective state и точную причину; ошибка не маскируется пустым пулом» | :374/:366 | OK | 8 различимых причин + `counters_error` (тесты + Playwright 3 fixture с конкретными ключами), service-absent путь — legacy, не `memory_service_missing` |
| A92 (:973) «Специализированный исторический поиск находит подходящие старые источники до финального ограничения» | :367/:368 | OK | `test_old_relevant_survives_final_top_k` (20 свежих + 1 старый → старый выживает); возраст по `message_timestamp`, FTS без vec |
| A93 (:974) «Другие чаты не блокируются чужой попыткой; ограниченный backoff без цикла и вечного starvation» | :369/:379 | OK | per-chat `count_deep_attempts(chat_id)`, global кап сохранён; backoff exponential с cap + reset по новым данным; singleflight/recheck |
| A94 (:975) «Валидный мост сохраняется и виден через API/UI; unchanged/ошибка/дубль различимы; self-traits не считаются успехом парадигм» | :377/:376 | OK (letter), UI-слияние unchanged — L-3 | мост-валидатор 5 проверок → written (S2/S3a); `test_traits_ok_does_not_bump_paradigm_counter`; 10 статусов; API raw-лог различает unchanged/error/duplicate; отчёт 8 групп |

No-false-acceptance (:381, О4): T-4733 prod-проверки не имитированы (см. PENDING OWNER).

## PENDING OWNER (не блокируют release-gate)

- **Live deep sleep на платных LLM**: полноценный ночной прогон реальными paid-вызовами с проверкой отчёта §7.2 в прод-«Аналитике» (fixture-контент — детерминированные фейки; T-4733).
- **Episodes pool**: пуст (v21-таблицы до live-извлечения владельцем) — episode-кандидаты/enrichment-ветка проверена fixture-уровнем; live pool — Owner-активация (mca-05 tails).
- **T-4733 prod effective-config + ограниченный реальный прогон** (или честный NOT_VERIFIED) и **T-4734 release/deploy** (bump 2.58.48→2.58.49 по D4; v25 идемпотентно + backup pre-DDL, health/locked-gate) — DevOps/Owner.
- Прод-приёмка A14–A94 в живом UI (после mca-17c-витрины) — на Owner-устройстве.

---

# Review round 2 — delta re-check rework M-1/L-1/L-3 + Architect amend M-2 (T-4732)

Дата: 04.10.2026 (после rework round 10.38 + AM-6). Код в ходе round-2 не менялся.

## Binding (round-2 reviewed state)

- HEAD: `4a6603b` (base 2.58.48, без коммитов — R18 сохранён). Дельта rework по mtime/git-статусу = ровно `services/dream_worker.py` + `tests/test_mca06_sleep_{bc,fg,i}_round1033/1035/1037.py` + доки (spec.md, adr-1028-9, tasks.md, evidence.md); все прочие код-файлы имеют mtime ≤ 17:10 (до round-1 ноты 18:09) — **иных изменений кода нет**.
- Дельта-rework fingerprint Builder'а **воспроизведён бит-в-бит** на текущем дереве: concat per-file SHA-256 (`dream_worker.py`, bc1033, fg1035, i1037 в порядке worker,bc,fg,i) → **`7b2a77134a0c098e…`** = записанный Builder'ом (`evidence.md:478`) — rework-файлы идентичны протестированному состоянию.
- Recipes round-1 WTH-агрегата и старых spec/adr/tasks хэшей бит-в-бит не восстанавливаемы (файлы перезаписаны; остались 16-hex префиксы). Для round-2 зафиксирован строго детерминированный полный рецепт `WTH-2`: **42 leaf-файла git-status scope** (все изменённые + untracked код/тест/док/отчёт-файлы, отсортированные по пути; concat per-file SHA-256 → SHA-256):
  **`02D5160D1783D77C2956068D1AF5C09142A9F09B738789D873FFF5CFEC32C10F`**
- Актуальные доки-хэши: spec `4CC8DD811B4015BC…`, ADR-1028-9 `EDF37EE8C2167912…`, tasks `EE98DAD083AB2424…`, threat `D417CE4D5EABE6E1` (= round-1, без изменений), requirements-map `2D4207F1221287BD` (= round-1, без изменений).

## Round-2 проверка findings

1. **[M-1] закрыт (код + тесты подтверждены):** `dream_worker.py::_run_deep_once_core` — `reject_reasons` init :1821; профильные `excluded_young`/`duplicates` (sel, только ненулевые) → `_rep(reject_reasons=*)` :1864–1868 **до** раннего `no_anchors`; мост-валидатор: аккумуляция `bv.reason` :2003 + `_rep(anchors_filtered, reject_reasons, validation)` :2011–2014 **до** раннего `insufficient_evidence` :2016 — отчёт причины не теряет; профильные счётчики мержатся в общий dict (наследуются в bridge-стадии). Consumer `_deep_report_json` :260–261 (cap ≤10, R17-safe). Тест-ассерты: `test_s3_reject_reasons_in_report` (i1037:317) → `{"no_subject":1,"time_order":1}` на пути `insufficient_evidence`, written=0; `test_report_profile_reject_reasons` (fg1035:387) → `{"excluded_young":3,"duplicates":2}`. Пайплайн-вердикты/пороги не тронуты — правка только в отчёте.
2. **[L-1] закрыт:** dedicated OFF-тест `test_profile_off_uses_legacy_rag_channel` (fg1035:400–450): `MCA_DREAM_HISTORICAL_PROFILE_ENABLED` → False (`_must_not_select` = AssertionError на `select_historical_candidates`), legacy `get_rag_facts` → `written`; asserts `mem.rag_calls == 1`, `mem.retrieve_calls == 0`. Тест в наборе, зелёный.
3. **[L-3] закрыт (заморожен):** мэппинг не менялся (`memory_agi.py:531 "unchanged":"empty"`, комментарий-инвариант :516–520); freeze-тест `test_unchanged_maps_to_empty_but_raw_distinct` (bc1033:525–534): `_DEEP_REASON_MAP["unchanged"]=="empty"` ≠ `"duplicate"`, raw-статусы лога различимы. UI-метка `unchanged` — mca-17c (doc-only остаток, принят).
4. **[M-2] закрыт (Architect amend, doc-only):** spec §8.2 :235 (AM-6: раскрытие = read-only API-контракт, A14 подтверждён на реальном HTTP-роутере, рендер delta-карточки + метка `unchanged` → mca-17c, Playwright остаётся для карточки сна T-4706); сводка приёмок :263; §12 :312 (раскрытие — реальный API, браузерный рендер — mca-17c); ADR-1028-9 AM-6 :47 (Accepted, полный rationale). Тексты согласованы между собой; **Δ кода/DDL = 0** (мэтч: mca-06 дифф кода после round-1 — только [M-1]-writer в отчёт, DDL остаётся v25).
5. **Targeted-прогоны (снова мои, независимость):** 5 mca-06 файлов **123 passed / 0 failed** (5.8s); расширенный набор 5 mca-06 + deep_sleep + dead_extractor_round1024 + sleep_manual_round1018 **220 passed / 0 failed** (9s). Числа Builder'а «73» в evidence/tasks-ноте не подтверждаются (фактическая коллекция 5 файлов = 36+39+26+11+11=123); «220» сходится. Счётная описка в доке — не влияет на вердикт.

## Остатки (не блокируют release-gate)

- **L-doc-1 (round-2):** tasks.md T-4718 (:58) — критерий не аннотирован AM-6 (остался старый текст «Playwright-проверка раскрытия» при замороженном inline-статусе T-4718 `[x]`); spec §8.2/§12 + ADR AM-6 авторитетны, противоречие только в нотации задачи — поправить @Architect'у заодно с L-2 при release-коммите.
- **L-doc-2 (round-2):** evidence.md/tasks — счётчик «73 passed» значится при фактических 123; исправить при следующей правке (зелёное состояние подтверждено).
- [L-2] round-1 (bump-текст 2.58.47→2.58.48 в spec/ADR §11.3) — остаётся на release-коммите.

## VERDICT ROUND 2: **APPROVED FOR RELEASE**

Blocking-findings round-1 (M-1, M-2) закрыты; L-1/L-3 закрыты сверх критерия. Ни одного Critical/High нет. Следующее: @Orchestrator → T-4733 (prod effective-config) и T-4734 release/deploy 2.58.49 (v25 идемпотентно; doc-хвосты L-doc-1/L-doc-2/L-2 — в release-коммит). Round-3 review не требуется; после T-4734 — подтверждение деплоя в мою ноту.

## Handoff

@Orchestrator: route review → **rework [M-1] (Builder, tiny fix: reject-reasons в отчёт + 2 профильных счётчика + asserts)** параллельно с якорной doc-правкой [M-2] (@Architect) → точечный rerun (mca-06 F/G/I + нулевой риск соседям) → DevOps T-4733/T-4734. После M-1/M-2 — мой delta re-check только этих двух зон (без повторного полного гейта).
