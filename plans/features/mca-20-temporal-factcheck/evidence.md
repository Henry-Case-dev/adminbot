# `mca-20-temporal-factcheck` — evidence.md (Builder: блоки A–F + интеграция, 06.10.2026)

**Lane:** `B1-mca20-build` (Builder T-5132…T-5146). Baseline: HEAD `d298f1f` (= origin/master), SQLite v32, каталог 519, KS 80, reason 269, тулы 13 (METERED 8), `temporal.factcheck` v0.
**Статус:** ✅ все блоки A–F реализованы и зелёные; интеграционная верификация пройдена; готово к независимому ревью (T-5148). Блок G — вне скоупа.
**Примечание:** fan-out недоступен (depth-limit на сабагентов) — все lane-и выполнены последовательно одним Builder-ом в одном worktree.

---

## A — ClaimEnvelope и единый вход (T-5132/T-5133; MCA20-R1; A72)

**Δ:** NEW `services/temporal_factcheck.py` — `TemporalClaimEnvelope` (frozen, поля ровно §30.1; **CA-20-14**: символ `ClaimEnvelope` не занят, DTO mca-22 не тронут — `services/claim_envelope.py` без изменений), `InputRef(kind ∈ command|reply|tool|ui|auto)`, `build_envelope()` — единый resolver из канонических метаданных (Origin-блок v32 через новый тонкий метод БД `get_smart_message_origin_block`); серверная валидация scope: невалидный target → `(None, "temporal_envelope_rejected")` без выдуманных подстановок; tool без цели → `free_text` + `date_unknown` + `uncertainty.origin=explicit_unknown`.
AMEND `services/factcheck_service.py` — `check_claim_envelope()` (соседний к `check_claim:79`; OFF-метод не тронут). AMEND `handlers/factcheck.py` — ON-путь K1 (`_temporal_on()` → `_factcheck_temporal()`), OFF-путь `:228–324` бит-в-бит.
AMEND `services/tool_schemas.py` — `TOOL_FACT_CHECK` (канон 13→14, аргументы только claim/target/mode/period-hint; EN-only description — канон 3.3), `FACT_CHECK_TOOL_NAME`, гейт `_fact_check_tool_enabled()` (K2 + каталог-тумблер). AMEND `services/tool_router.py` — диспетч `_fact_check` (прецедент `_recognize_image`: JSON-ToolResult, scope из доверенного runtime, чужой чат → `temporal_envelope_rejected`; сервис-адаптер создаётся без `tool_router` → рекурсия невозможна, CA-20-12).

**Evidence (тесты):** `tests/test_mca20_temporal_round1044.py` — frozen-DTO, контракт полей, CA-20-14 (символьная изоляция mca-22), telegram_origin/telegram_message/hidden_user cascade, rejection без выдумок, explicit unknown для tool-свободного текста; `tests/test_mca20_integration_round1045.py::TestFactCheckTool` — disabled/чужой-чат/ready-payload.

## B — правила выбора времени и режимы (T-5134…T-5136; MCA20-R2; A69/A71)

**Δ:** в `services/temporal_factcheck.py`: priority-каскад D5 (telegram_origin → telegram_message → publication_metadata → extracted_claimed → unknown; extracted никогда не повышается молча — конфликт сохраняется в `date_uncertainty["conflicts"]`), детерминированное извлечение заявленных дат (`_extract_claimed_period`: точная дата/год/относительные), относительные «сегодня/вчера» от автора фрагмента (не от пересылки; без даты автора — честный `temporal_date_unknown`, now не подставляется), tzr1: неизвестный TZ → интервал пограничных суток ±14 ч (`TEMPORAL_TZ_RESOLUTION_VERSION="tzr1"`), режимы D7 (`resolve_requested_mode`: «сейчас правда?» → current, «было ли верно тогда?» → historical_truth, knowable_at_time ТОЛЬКО явно; дефолт — каталог владельца `temporal.default_mode`).

**Evidence (тесты):** A69 — `test_today_resolves_to_original_2022_not_repost` (2026-репост 2022 со «сегодня» → период 2022); A71 — `test_relative_without_author_date_stays_unknown`, `test_tz_unknown_day_becomes_boundary_interval`, `test_claim_period_beats_publication_for_content`; SC-R2c — `test_extract_conflict_recorded_not_resolved`, `test_hidden_user_has_date`; D15/F-3 — `test_extract_failed_note` (`temporal_date_extract_failed` ≠ unknown); режимы — `TestModes` (4 теста).

## C — поиск, TemporalVerdict, сквозной пайплайн (T-5137…T-5140; MCA20-R3; A70)

**Δ:** `decompose_claim()` — части с собственными периодами; числа — NumericClaim-совместимые словари (REUSE mca-15, второй числовой контур не строится); `search_queries_for()` — запросы сущность+событие+год (REUSE существующего агрегатора, поисковых движков новых нет); `evidence_rows_from_results()` — evidence-контракт D9 (URL/support/retrieved_at; published_at честно unknown — snippet не доказательство); `TemporalVerdict` (frozen: factual_verdict ≠ temporal_status, evaluated_period, assessment_mode, as_of, evidence_refs, uncertainty, parts); guard CA-20-11 — `misleading_reuse` только при маркерах предъявления («сейчас/только что»), иначе честный downgrade → `outdated`; enum-валидация — чужие значения не проходят, refuted без evidence невозможен серверно.
Пайплайн (8 стадий реестра): data-only стадии БЕЗ инструментов (тест «рекурсия запрещена» на `chat_with_tools`), отказ движков → серверный `insufficient_evidence`+`temporal_insufficient_evidence` (никогда refuted, F-1), невалидный JSON аналитика → fallback-вызов → `_temporal_fallback_text` (детерминированный текст с датами; пользователь всегда получает ответ), вербализатор REUSE (`verbalize_validated`/cleanup) получает вердикт-JSON с периодом/статусом/оговорками (BehaviorFrame после вердикта, CA-20-13).

**Evidence (тесты):** `test_analyst_and_verbalizer_get_same_envelope` (A72: один envelope + payload вербализатора содержит период/статус), `test_fallback_keeps_mode_and_dates` (режим не меняется молча), `test_no_recursive_fact_check`, `test_search_engines_down_gives_insufficient`, `test_missing_source_not_proof_of_fake`, `TestDecomposition` (multipart-периоды, numeric-REUSE, временные ограничения в запросах).

## D — кеш и freshness (T-5141/T-5142; MCA20-R4; A70/SC-R4a/4b)

**Δ:** AMEND `services/smart_cache.py` — slug **`factcheck_temporal`** (+`_NORMALIZERS`); legacy slug `factcheck` не тронут (ON-путь не читает/не пишет). Ключ — каноническая сериализация компонентов D12 (scope + canonical claim + target revision/content_hash + origin fingerprint + режим + период + tzr1 + related + pipeline_version + **freshness bucket**); unknown origin → ключ `None` → авто-bypass (`temporal_cache_disabled`), кеш поиска/загрузок не тронут. Запись — payload JSON с ВНУТРЕННИМ `as_of` (CA-20-9: hit не «омолаживается»); чтение — проба volatile→stable с честным TTL каждого бакета (REUSE `get/set_update_marker` — mca-22 не дублируется, mca-04a `freshness_status` не пишется); TTL — каталог `temporal.freshness_current_ttl_hours` (6 ч, volatile: current/misleading_reuse) / `temporal.freshness_historical_ttl_hours` (720 ч, stable: old_but_valid/outdated) с per-chat резолвом.

**Evidence (тесты):** `TestCacheKey` — разные ключи по году/чату/режиму/revision; unknown origin → bypass; legacy-ключ ≠ temporal-ключ; buckets; TTL 6/720 ч; handler cache-hit — `test_on_path_cache_hit_replies_without_llm` (LLM не зовётся, текст из payload).

## E — UI, trace, наблюдаемость (T-5143/T-5144; MCA20-R5; A73)

**Δ:**
- **DDL v33** (AMEND `services/database.py`): `_SCHEMA_VERSION_FACTCHECK_TEMPORAL = 33`; `mca_factcheck_runs` (CHECK-enum source_type/factual_verdict/temporal_status) + `mca_factcheck_evidence` + 3 индекса (runs(chat_id,created_at), runs(access_scope,created_at), evidence(run_id)); `MigrationStep(33, "factcheck_temporal")` в реестре mca-14 (backup-guard общий runner, идемпотентно, PG no-op — pg_db.py не тронут); тонкие методы: `get_smart_message_origin_block`, `record_factcheck_run` (write-once, повтор run_id → False), `record_factcheck_evidence` (потолок), `list_factcheck_runs`/`get_factcheck_run`/`get_factcheck_evidence`. Smoke: fresh-БД → `user_version=33`, roundtrip записи/чтения.
- **Процесс** (AMEND `services/mca_process_registry.py`): `temporal.factcheck` v0→v1 — стадии ровно `target_resolve → origin_date_resolve → claim_decompose → temporal_search → evidence_validate → verdict → verbalize → deliver`, события `factcheck_temporal` (component `factcheck.temporal`, только id/коды/стадии — R17), enabled_gate K1, widget_id **«Временной фактчек»** (контракт mca-17c), `_GATE_RESOLVERS` + master.
- **Reason +10** (AMEND `services/mca_events.py`): 269→279, полный санкционный перечень, `temporal_date_extract_failed` ≠ `temporal_date_unknown`.
- **Routes +2** (AMEND `web/api/routes.py`): `GET /api/factcheck/temporal/runs` и `GET /api/factcheck/temporal/runs/{run_id}` — RBAC прецедент /api/random/test (global admin); список — компакт БЕЗ claim/verdict-текста (R17), детали — с JSON-распарсенными объектами; `+ "temporal": "Временной фактчек"` в `_category_title`.
- **Kill-switches +3** (AMEND `services/mca_gates.py`, `config/settings.py`): 80→83, env-only ClassVar default ON, инертность K2/K3 при K1 OFF; env-потолки `MCA_TEMPORAL_MAX_RUNS_LIST`/`MCA_TEMPORAL_MAX_EVIDENCE_PER_RUN`.
- **Каталог** (AMEND `services/param_catalog.py` + F8): категория `temporal`, группа `temporal_factcheck` на `mod_factcheck` (TAB_RULES in-place, 22), ровно +4 ParamSpec (`temporal.default_mode` select ×4, `temporal.freshness_current_ttl_hours`=6, `temporal.freshness_historical_ttl_hours`=720, `temporal.tool_enabled`=ON); **REGISTRY 519→523, GROUPS 112→113, _TAB_BY_GROUP 110→111, TAB_RULES 22, delta 108→112, Settings 450→454, секреты 42/33 без изменений**.
- **Web** (AMEND `web/index.html`, `web/app.js`): виджет «Временной фактчек» внутри существующей «Аналитики» (#/oversight, global-admin-only; новых разделов/маршрутов нет): компакт-таблица runs (время/чат/режим/итог/актуальность/дата-из/метки кеш-fallback) + модалка деталей (timeline original/repost/период/as_of, «почему выбрана дата» = date_source+conflicts+precision, evidence-карточки, trace стадий, версии pipeline/tz); настройки владельца — автоматически из каталога на вкладке mod_factcheck.

**Evidence (тесты):** `TestObservabilityContract` (v1/8 стадий/widget/gate/not_run/reasons 279/инертность/fail-open событий), `TestRunRecording` (v33 roundtrip, evidence-cap, fail-open без БД), `TestRoutes` (+2 зарегистрированы; compact-vs-full R17), `TestSanctions` (канон 14/METERED 9/каталог-ключи/слаг/Settings), JS: `tests/js/round1044_temporal_factcheck_ui_test.js` → `MCA20-TEMPORAL-UI-OK` (URL/форматтеры-честный unknown/детали/структура; `node --check web/app.js` OK).

## F — контрактные тесты и smoke (T-5145/T-5146; A69–A73)

**Δ:** NEW `tests/test_mca20_temporal_round1044.py` (33 теста), NEW `tests/test_mca20_integration_round1045.py` (28 тестов) — фикстуры транспорт/даты БЕЗ LLM + ScriptedLLM (офлайн-запись маршрута). Покрытие приёмок: **A69** (old-forward+«сегодня»→2022; old_but_valid ≠ refuted; актуальность отделена), **A70** (разные ключи за разные годы/контексты; cache-hit без LLM с честным as_of; режимы различаются), **A71** (unknown не заменён now; TZ-интервал; historical ≠ knowable), **A72** (один envelope через analyst/verbalizer/fallback; tool↔handler согласованность через общий resolver; рекурсии нет), **A73** (v33+routes+process v1 8/8, версии/ошибки раскрываются). Матрица §30.4: старый channel-forward ✓ (smoke), hidden_user с датой ✓, обычный старый target ✓, спорная дата (conflict) ✓, «сегодня» в оригинале ✓, явный прошлый год ✓, неизвестный TZ ✓, одинаковый текст за разные годы ✓, режимы различаются ✓, edited target (revision-ключ) ✓, исчезнувший источник (honest insufficient) ✓, tool/handler согласованный envelope ✓, отказ поиска без refuted ✓. Поздний media → `temporal_media_pending` зарезервирован reason-словарём (медиа-ветка потребляет контракты mca-19 через related_* поля envelope).
**T-5146 smoke:** offline full-route прогон сценария §30 (2026-репост 2022 со «сегодня», contextual) — `TestOfflineSmokeA69A70::test_age_is_not_falsehood_contextual` (возраст ≠ ложность, old_but_valid, период 2022, актуальность отдельно). Живой LLM-smoke — на живом контуре приёмки (T-5151, вне Builder-окна); новых провайдеров не требуется (GEN-R2).

## Интеграция (финальная)

- Прогон после каждого блока + смежные слайсы; **F8 --check OK 523** (`tools/gen_param_registry_round1025.py --check` → exit 0; артефакты TSV/meta/screen-map регенерированы тулом `tools/_mca20_reissue_f8.py`, идемпотентен; переиздан повторно после переименования TTL-титулов по jargon-гейту round109).
- Guard-перенос прецедентом mca-19: ROUTES_SHA256_F11 переутверждён осознанно (L-F11S-1) = `8153b8bd389711e9cb7a61352e58f6f8217c0a236575f75489ca617c0d0c7b45`; fixture `f8_baseline.json` (counts+sha+routes+note), `catalog_baseline.json` (523); пины Settings 450→454 (~30 файлов), канон 13→14 (11+4 файлов), categorized 494→498 (8 файлов), каталог 519/112/110/108→523/113/111/112, mca-19-guard тесты обновлены (TSV 524, KS 83, reasons 279, канон-хвост), mca-01 write-points 186→189 (аудит в комментарии), mca-05 mark хвоста реестра →v33 (конвенция волн), mca-17a future-features: temporal.factcheck вышел из «будущих» (v1).
- **Полный pytest (foreground, ~7,3 мин): 12265 passed / 5 failed — ВСЕ 5 pre-existing на чистом HEAD `d298f1f`** (верифицировано полным прогоном HEAD-бейлайна в изолированном worktree: тот же набор; состав: `test_history_cli::test_scope_is_required` — флейк в обе стороны, `test_mca09_intents_block_e::test_registry_process_intent_initiative` — order-dependent flake, изолированно зелёный, `test_tool_loop::test_query_chat_memory_count_reaches_model`, `test_webapp_nav_disclosure_ui::test_memory_rag_and_sleep_tabs`, `test_webapp_status_control::test_status_public_for_all_roles`). Дельта mca-20 добавляет **0** красных; collect-only: **12270 tests, 0 ошибок**.
- **js 60/60** (вкл. новый `round1044_temporal_factcheck_ui_test.js`); `node --check web/app.js` OK.
- R17: секретов нет; в события/логи — только id/коды/стадии/числа (claim-текст не логируется); git status дельта перечислена ниже.

### Хеши ключевых файлов (кандидат финала, 06.10.2026)

| файл | sha256 (первые 16) |
|---|---|
| services/temporal_factcheck.py | `b82353892044c831` |
| services/factcheck_service.py | `81b26ec8d0e9f32e` |
| services/database.py | `db4b4131d6eea1c7` |
| services/param_catalog.py | `e49880e2cf991dc1` (= `f8_baseline.sha256`, репин F8) |
| services/mca_gates.py | `7842fb76a758adc2` |
| services/mca_events.py | `df863e946391fec4` |
| services/tool_schemas.py | `e1a0eef00fac28a4` |
| services/tool_router.py | `bfa1ae87a8b9ea6a` |
| services/tool_loop.py | `b2e786fca0d3c23c` |
| services/smart_cache.py | `a2f387e8a18c7c58` |
| services/mca_process_registry.py | `ada32fa96b9a086f` |
| handlers/factcheck.py | `5ff09b98532035f0` |
| config/settings.py | `b046387e586f6d3c` |
| web/api/routes.py | `8153b8bd389711e9` (= ROUTES_SHA256_F11, L-F11S-1) |
| web/app.js | `a2c1b65f429008b7` |

### Дельта-файлы (git status, реализация mca-20; plans/*-файлы параллельных lane-ов не тронуты)

- **AMEND (код):** `config/settings.py`, `handlers/factcheck.py`, `services/{database,factcheck_service,mca_events,mca_gates,mca_process_registry,param_catalog,smart_cache,tool_loop,tool_router,tool_schemas}.py`, `web/api/routes.py`, `web/app.js`, `web/index.html` — 14 файлов
- **NEW (код/тулы):** `services/temporal_factcheck.py`, `tools/_mca20_reissue_f8.py`
- **NEW (тесты):** `tests/test_mca20_temporal_round1044.py` (33), `tests/test_mca20_integration_round1045.py` (28), `tests/js/round1044_temporal_factcheck_ui_test.js`; `plans/features/mca-20-temporal-factcheck/evidence.md`
- **F8-артефакты/fixtures:** `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md`, `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`
- **Guard-пины (счётчики только):** 60 файлов `tests/*.py` (Settings 450→454, канон 13→14, categorized 494→498, каталог 519/112/110/108, KS 80→83, reasons 269→279, TSV 520→524, write-points 186→189, mark v32→v33, future-features) — полный список в git status; содержательных изменений логики чужих тестов нет (кроме документированных переносов frontier-пинов по конвенции волн)
- **НЕ тронуты:** `services/claim_envelope.py` (mca-22), `pg_db.py` (PG no-op), vision-контур mca-19 (кроме санкционного переноса guard-пинов в тестах), `bot.py`, `plans/current_task.md` (R17), git-индекс

### Числа финала

catalog **523** (GROUPS 113, _TAB_BY_GROUP 111, TAB_RULES 22, delta 112, Settings 454, categorized 498) · F8 --check **OK 523** · KS **83** · reason **279** · тулы **14** (METERED **9**) · routes **41** (+2) · процесс `temporal.factcheck` **v1** (8 стадий) · slug `factcheck_temporal`/`tzr1` · OFF = бит-в-бит `d298f1f` (легаси-путь handler'а сохранён, K1 OFF).

**Готовность к T-5148 (Review): готова.** remaining risk: живой LLM-smoke (T-5146 live-часть) переносится на живой контур приёмки; поведение вербализатора на реальных моделях проверяется A70/A72-интеграциями после восстановления деплой-канала mca-19 (план `:244`, вне Builder-скоупа).

## Rework R1 (T-5148 итер.1, lane B2-mca20-rework1, 06.10.2026) — F-1 + F-2

Разбор ревью принят целиком; non-blocking N-1..N-9 не тронуты (disposition — в review.md). Изменены ТОЛЬКО: `services/temporal_factcheck.py`, `services/factcheck_service.py` (блок verdict `check_claim_envelope` + новый `_temporal_validator_payload`; легаси `check_claim`/хендлер-шов не тронуты), `services/tool_router.py` (`_fact_check`), тесты (`tests/test_mca20_rework1_f1_f2.py` NEW; `test_mca20_integration_round1045.py` — единственная адаптация фейка `ScriptedLLM`: ветка validator-agree, иначе все happy-path тесты молча становились тестами сбоя validator). mca_vision-зону mca-19, каталог/KS/reason-словарь/тулы/реестр процесса v1 (8 стадий) — не трогал.

### F-1 (High) — явный mode tool-вызова больше не отбрасывается

- Механизм подтверждён ДО: `resolve_requested_mode("historical_truth")` → `("contextual", False)` для всех 4 enum; end-to-end `dispatch("fact_check", {claim, mode:"historical_truth"})` → payload.assessment_mode=contextual, v33 requested_mode=assessment_mode=contextual (репро ревьюера воспроизведён).
- Фикс: `InputRef.explicit_mode` (новое структурное поле, D7) — валидное enum-значение из tool-вызова идёт в `TemporalClaimEnvelope.requested_mode` МИМО фразового resolver'а (`build_envelope`: приоритет explicit_mode над фразовым resolver'ом по hint). Фразовый матчинг остался только для естественного языка (command/reply, TestModes зелёные). Невалидный mode — честный отказ: tool возвращает `{status: "failed", reason: "temporal_envelope_rejected", note: "invalid mode"}`; resolver-уровень — вторая линия (тот же существующий reason-код), молчаливой подмены дефолтом нет, reason-словарь не расширен.
- Отклонение от скетча ревьюера (`build_envelope(..., explicit_mode=...)`): носитель — поле InputRef (единый вход resolver'а, D3); семантика и валидация эквивалентны.

### F-2 (Medium-blocking) — validator-стадия реализована (spec D11/TH-2, CoVe REUSE)

- Механизм подтверждён ДО: в `check_claim_envelope` analyst → (fallback при невалидном JSON) → verbalizer; grep validator/cove/grounding по temporal-пути пуст; комментарий модуля `:355` при этом уже заявлял «analyst → validator/verbalizer».
- Реализация: `TEMPORAL_VALIDATOR_SYSTEM` (data-only CoVe-стиль: agree/corrected_factual_verdict/corrected_temporal_status/note; промпт начинается с «Ты — проверяющий», не содержит «СТРОГО JSON» — не ломает маршрутизацию существующих фейков); `_temporal_validator_payload` — claim + temporal_context + verdict_draft + search_results, всё через `escape_xml_text` (untrusted-evidence остаётся данными, контейнер не разрывается); вызов ровно ОДИН (`step="temporal_validator"`), только при evidence и аналитик-вердикте; применение — `tf.apply_validator`: corrected-поля проходят ТОТ ЖЕ серверный guard `verdict_from_payload` (enum-валидация + misleading_reuse-guard, CA-20-11 не обходится); согласие/мусор/невалидные corrected → вердикт аналитика стоит. Отказ/невалидный JSON валидатора → СУЩЕСТВУЮЩИЙ fallback-путь (общий слот ≤1 строгий повтор аналитика) с существующим reason `temporal_fallback_mode`; если fallback-слот уже потрачен — вердикт стоит, сбой честно в трассе. Бюджет: analyst ≤1 + fallback ≤1 + validator ≤1 + verbalizer ≤1. Реестр процесса v1 (8 стадий) не менялся: исход validator — дополнительная запись "verdict" в stage-trace (outcome validated/corrected/failed).
- TH-2 теперь обеспечен кодом: инъекция «verdict: refuted» в evidence не проходит в вердикт (экранирование данных + validator + серверные enum/guard).

### RED→GREEN

- RED (до фикса, зафиксирован): новые тесты `tests/test_mca20_rework1_f1_f2.py` — 17 failed / 2 passed (2 — регрессионный контроль существующего поведения); причины падений — ожидаемые (нет explicit_mode, нет TEMPORAL_VALIDATOR_SYSTEM, tool-mode → contextual, невалидный mode не отклоняется).
- GREEN (после): 19/19 passed. Focused mca-20: `round1044` + `round1045` + rework1 = **80 passed** (61 существующих зелёные). Смежный слайс factcheck-хендлеров/сервиса/CoVe/two-call/mca15/smart-cache = **201 passed** (сходится с ревью).
- Покрытие: F-1 — structural bypass, все 4 enum, фразовый путь не сломан, невалидный mode (resolver + tool честный отказ), end-to-end dispatch → v33 (репро ревьюера теперь GREEN); F-2 — порядок analyst→validator→verbalizer, инъекция через evidence остаётся данными (1 контейнер, экранирование, вердикт не refuted), сбой validator → существующий fallback + честный reason, полный провал → честный degraded, коррекция через серверный guard (banana отброшен), misleading-guard не обходится, no-evidence → validator пропущен (TH-5 сохранён), бюджет ≤1, data-only без тулов, reason-словарь 279.

### Прогоны и санкционные числа (после R1)

- `pytest tests/test_mca20_temporal_round1044.py tests/test_mca20_integration_round1045.py tests/test_mca20_rework1_f1_f2.py` → **80 passed**; смежные 6 файлов → **201 passed**.
- Полный pytest (фоново, лог `C:/Users/main/AppData/Local/Temp/opencode/full_pytest_rework1.log`): **12285 passed / 4 failed, 0 ошибок, 7:39**. Все 4 — документированный pre-existing бейлайн: `test_mca09_intents_block_e_round1040` (mca09-pollution), `test_tool_loop::test_query_chat_memory_count_reaches_model`, `test_webapp_nav_disclosure_ui`, `test_webapp_status_control`; history_cli-флейк в этом прогоне не проявился (документирован как флейк). Новых падений нет; 19 новых тестов зелёные. Первый foreground-прогон был оборван tool-таймаутом 2 ч (hang `test_summary_memory.py::db` на close под нагрузкой — infra-флейк, без кириллицы в деле: фоновый прогон тех же 12289 прошёл чисто).
- F8 `--check` → **OK 523** (exit 0); `--collect-only` → **12289, 0 ошибок** (12270 + 19 новых); REASONS **279** (не расширен), KS **83**, REGISTRY **523**, tool-канон **14** (METERED 9) — финальные числа на месте; реестр `temporal.factcheck` v1 (8 стадий) не менялся.
- R17: 0 секретов (скан дельты по key/token/password/secret/bearer/ssh — пусто); в событиях/трассе только id/коды/стадии; claim/evidence идут только в LLM-канал стадий (санкционно §30.3).

### Дельта и хеши (rework-кандидат, рабочее дерево поверх HEAD d298f1f)

| Файл | Изменение (R1) | SHA256 (начало) |
|---|---|---|
| `services/temporal_factcheck.py` | InputRef.explicit_mode + валидация/приоритет в build_envelope; TEMPORAL_VALIDATOR_SYSTEM; apply_validator | `1905d61af2e50b1b` |
| `services/factcheck_service.py` | блок verdict: validator-врезка; `_temporal_validator_payload` | `cd2f1d9e6f6314c` |
| `services/tool_router.py` | `_fact_check`: invalid mode → честный отказ; explicit_mode вместо hint | `3e8e1ae7f83a5eb` |
| `tests/test_mca20_rework1_f1_f2.py` | NEW, 19 тестов F-1/F-2 | `a9a74523a5bf215` |
| `tests/test_mca20_integration_round1045.py` | ScriptedLLM: + ветка validator-agree | `96ac435abb67056` |

Остальные файлы манифеста ревью (включая mca_vision-зону mca-19, web, каталог/fixtures, легаси-хендлер) реворком не тронуты; хеши остальных 11 ключевых файлов из таблицы выше остаются в силе.

**Готовность:** к дельта-речеку ревьюера (оба файла + 61 mca-20 + репро F-1/F-2; полный suite не требуется). Полный suite прогнан: 12285/4, все 4 — документированный pre-existing. Incidental: hang `db`-fixture test_summary_memory при 2-часовом foreground-прогоне (фоновый прогон без конкуренции прошёл за 7:39) — вне скоупа, отмечен для Scanner T-5149 (uncertain, load-флейк Windows).
