# ASAP 4.1 — review.md (Step 5 @Reviewer, финальный gate T-4629)

> Независимый ревью всего эпика (волны 2–8; пер-волновых gate не было —
> предыдущая попытка gate оборвалась по транспортному таймауту до создания
> артефактов, эта сессия выполнена с нуля). Код ревьювером не правил,
> не коммитил. Ревью в один gate: (1) требования/корректность,
> (2) focused change-audit изменённого кода.

---

## ROUND 2 — дельта-ревью фикса [M-ASAP41-1] (03.10.2026, @Reviewer)

> Дельта-ревью только фикса [M-ASAP41-1] (doc-only); финальный gate round-1
> вердикт по ядру эпика в силе — все round-1 проверки/находки ниже
> пересмотрены и подтверждены заново в этой сессии. Код ревьювером не правил,
> не коммитил.

- **Feature-ID:** `asap-4-1-durable-whole-window-summary` (T-4629)
- **Risk-Level:** R3 (подтверждён: orchestration production Summary, новая
  SQLite DDL v23→v24, 9 новых kill-switches, Supervisor меняет тайминги
  главного пользовательского контура; blast radius диффа шире ожиданий
  не оказался — 42 изменённых + 34 новых файла, все в зонах A–G + тесты;
  round-2 дельта — doc-only, риск не меняет)
- **Status: Approved for release** (round 2: единственный blocking Medium
  [M-ASAP41-1] закрыт doc-only фиксом — детали в разделе Round 2 ниже;
  0 Critical/High)

## Binding

**Round-1 binding (исторический, для полноты):**

| Поле | Значение |
|---|---|
| Reviewed-Commit | `60f1c7c07a63192c749ba432f91ab44265adbc50` (HEAD master; фича — незакоммиченное рабочее дерево поверх 2.58.46, R18-режим без коммитов) |
| Working-Tree-Hash | `452AB73FCAF1F137AE716CACE3F680FD21E2692D85E6C6D78D940D2ECCA59341` — SHA-256 детерминированного манифеста `plans/reports/asap41_wth_manifest_review.txt` (76 файлов: 42 modified + untracked фичи/тесты/инструменты; per-file SHA-256; чужой WIP — `.playwright-mcp/`, `extra_images/`, `node_modules/`, `package.json`, `package-lock.json` — в манифест не входит и в дифф эпика не попадает, задокументировано). Recipe (уточнён в round 2): WTH = SHA-256 **сырых байтов файла-манифеста как есть** (UTF-8 BOM + CRLF + trailing CRLF); воспроизведён ревьювером байт-в-байт |
| Spec-Hash | `E6A6E5ECEF5ADBC18DC8551C3D0C923541AD38430A87675C965ABC91B542A0F6` (spec.md полный) |
| ADR-1028-8 | `6271450C3F07DE3C45FB916448173649DE496D4CCE3014A1C92879D6429CF137` |
| tasks.md | `A6137F16EB03AC1313D3C42925BEE2A89A03D6DCAC9C65BC3CB6C2A8B0C5F6A0` |

**Round-2 binding (актуальный, этой сессии):**

| Поле | Значение |
|---|---|
| Reviewed-Commit | `60f1c7c07a63192c749ba432f91ab44265adbc50` (HEAD master — не менялся; R18-режим без коммитов) |
| Working-Tree-Hash | `BA44A8CDD2BCC832B9C7E4541745EACCB0E6E98E19CC503F576DF12B37419246` — SHA-256 манифеста-копии `plans/reports/asap41_wth_manifest_review_round2.txt` (76 файлов, per-file SHA-256; recipe как round-1 — SHA-256 сырых байтов файла манифеста UTF-8 BOM + CRLF). Разница с round-1 ровно в 3 per-file хеша: `evidence.md` (6884F4B0…), `tasks.md` (D36756E7…), `workflow_state.md` (2E45CFAA…) — документация фикса и state-план орчестратора; остальные 73 файла байт-в-байт с round-1 (сверено ревьювером по хешам, не заявлением). Binding проставлен на актуальное состояние этой сессии round-2; пересчитан после фикса, а не унаследован |
| Spec-Hash | `E6A6E5ECEF5ADBC18DC8551C3D0C923541AD38430A87675C965ABC91B542A0F6` — байт-в-байт, spec.md не менялся весь эпик |
| ADR-1028-8 | `6271450C3F07DE3C45FB916448173649DE496D4CCE3014A1C92879D6429CF137` — байт-в-байт |
| tasks.md | `D36756E7FEC557F4940946CBFE495107667DFB2D323E1B67C0CF07667CACB773` — изменён фикс-документацией; round-1 A6137F16… исторической записи сохранён выше |
| evidence.md | `6884F4B0B4B3F800638342CFEA8A405D4CB9B443FE212481213BE5C652A91023` |

После любых изменений кода/спеки биндинг пересчитывается; повторное
использование этого вердикта по сообщению коммита — недопустимо.

## Git base и объём проверенных изменений

- Base: HEAD `60f1c7c` (docs-only reconcile round1030) = прод-контур
  2.58.46 (SQLite user_version=23). Пустой `git diff` не принимался как
  доказательство — проверен фактический `git diff HEAD` (5023+/517−,
  42 файла) + untracked новые модули/тесты/инструменты.
- Проверены критические зависимости и интеграционные кромки:
  `summary_generator ↔ summary_l1_clusterizer / l2_writer / l2_review /
  legacy_fullwindow / run_store / source_window`, `llm_client ↔
  summary_llm_supervisor` (per-call контракт, default-None = байт-в-бит),
  `model_capacity` (AMEND ADR-1028-3), `database.py` (v24-миграции +
  allowlist MCA-01 149→155), `pipeline_events/pipeline_analytics/mca_events`
  (observability), `cover_style_pipeline/cover_style_jobs` (зона F),
  `web/app.js + web/index.html` (зона G UI), `tests/conftest.py`
  (изоляция OFF-паритета).

## Checks performed (все — независимо, тесты запущены собственноручно)

1. **Прогоны (собственные):**
   - все 16 asap41-тест-файлов (зоны A–I): **236 passed** (40.6s);
   - полный pytest `tests -q --timeout 180`: **11074 passed / 3 failed** —
     2 failed = известные pre-existing web/-bounds
     (`test_tool_coordinator_round1026::test_forbidden_paths_out_of_diff`,
     `test_unified_image_request_round1026::..._vs_baseline`, падают только
     на web/-файлах прошлых санкционированных волн, воспроизводятся на
     чистой базе); 3-й failed =
     `test_betterstack_handler::test_real_302_not_followed_by_opener` —
     **флап на неизменённом коде** (серия из 6 одиночных прогонов: 5 pass /
     1 fail; betterstack-файлы в дифф эпика не входят). Сумма тестов
     11077 = отчёту Builder (11075+2) — расхождение объясняется флапом,
     пропавших тестов нет;
   - JS: **54/54** файлов tests/js (включая новый
     `asap41_zone_g_inspector_test.js` → ZONE-G-INSPECTOR-OK);
   - F8-чек каталога: **EXIT=0** («CHECK OK: реестр 488 == REGISTRY,
     карта полна, R17-чисто, TSV/map идемпотентны») — Δ каталога = 0;
   - browser-верификация (spec REQUIRED): `tools/ui_asap41_zone_g_e2e.py`
     выполнена ревьювером самостоятельно → **EXIT=0, failures: 0**,
     desktop 1280×800 и mobile 390×844; payload_sanity подтверждён
     (coverage_breakdown/capacity/cover_style присутствуют, mode=
     WHOLE_WINDOW, l1_result=failed, styled=styled); скриншот просмотрен
     — карточки «Покрытие источника — по стадиям» (L1 «не выполнено ·
     карта деградирована» рядом с Источник 839/839·100% — раздельные
     оси), «Контекст модели» (Provider/Model/Effective window 400 000/
     Serialized input 96 120/Output reserve 4 000/WHOLE_WINDOW + человеко-
     читаемая причина), «Активность стадий», «Обложка и стиль» (Styled +
     resolve-лестница) рендерятся из structured state и читаемы.

2. **AM-1 whole-window-first (зоны A/B):** механизм, не заглушка —
   `run_l1_capacity_first` меряет ПОЛНОЕ окно serialized §92-элементами
   (`build_l1_payload` всего rows; тот же `_serialized_len`, что pack);
   fit → ровно 1 L1-запрос без pack-эвикций (`_allow_chunking=False`), без
   `messages[:N]`; отсутствующий semantic map НЕ роняет Summary:
   L1 total failure → writer-source ветка с инструкцией «semantic map
   unavailable — structure source yourself», запрет прыжка в урезанный
   Legacy закреплён guard'ом (не writer_source → guard активен) и тестами
   G3/M1 (`_run_legacy_pipeline.assert_not_awaited`). `too_many_facts`-
   класс снят измерением (map v1 без кардинальности фактов), `MAX_FACTS_*`
   — потолки derived-view синтеза через `repair_capacity_overflow`.
   Тест «в L1 output нет текстов сообщений» (R6-B-002) в сюте; golden 839
   (G1) — 1 запрос, coverage 100%, run жив.

3. **AM-2 capacity engine:** цепочка §5 дословно в `model_capacity.py
   ._resolve_uncached` (runtime → каталог → registry → override(ур.4) →
   fallback 16384+WARNING); решение по фактическому serialized payload
   (`decide_summary_mode`, контрпример «только message.text» покрыт
   тестом serialized_len ≫ text_only); cache-key = provider+base_url+model
   +capability fingerprint, точечная инвалидация при runtime 400/404/413
   внутри Supervisor; авто re-plan (`replan_summary_capacity`): вмещает →
   same whole-window; меньше → CAPACITY_OVERFLOW (lossless); больше →
   whole-window только до создания сегментных артефактов
   (`segment_artifacts_exist`). Allowance (manual cap §137) суверенен:
   при расхождении план перестраивается с честной причиной —
   интерпретируется как «manual cap = размер ОДНОГО сегмента» (согласовано
   со spec A.2/§137; legacy_static — только при выключенном auto-budget,
   это и есть OFF-паритет той конфигурации).

4. **AM-3 Supervisor:** scope = Summary only — новые точки обёрнуты
   (кластеризатор `_make_llm_call`, writer/reviewer/revision operation-
   метки, legacy `_supervised_generate`); Direct/STT/image/embeddings не
   тронуты (новые kwarg'и `timeout`/`budget_reason_label`/
   `supervised_transport` default None → прежний канал, OFF-parity тесты);
   **attempt-потолок ≤4 HTTP закреплён тестом реальным подсчётом
   httpx.AsyncClient.post** (4 при вечном transport-фейле; 2 при 500 —
   `retry_statuses=()`; 3 при fallback); внутренний fallback-каскад
   llm_client для supervised-канала выключен (`generate` raise без
   каскада); умножения retry нет (stage-бюджеты логические: L1 ≤2, L2 ≤6 —
   transport-ретраи не входят); watchdog liveness-based: streaming — stall
   по неактивности (elapsed не убивает), sync — attempt-дедлайн от
   телеметрии успешных длительностей (timeout/failure НЕ обучают
   оценщик — тест), hard fuse — последний рубеж, clamp [600,7200],
   developer deep env-only; Mode C — честная реализованная база,
   Mode A/B — контрактные слоты (флаг default OFF + верифицированный
   адаптер; «stream ✓» при sync-транспорте невозможен — тест); no-ping
   тест (ровно 1 HTTP /chat/completions).

5. **AM-4 Writer/Reviewer/FactPackage:** `WriterInput` = source_window
   (обязателен, serialized §92 без срезов) + semantic_map? + fact_view?
   + length; FactPackage понижен до derived view (`summary_fact_view`,
   0 LLM, синтез детерминированный); Writer работает на полном окне с
   сильно урезанным/отсутствующим fact_view (тест); Reviewer сверяет
   против пакета ∪ РЕАЛЬНОГО окна (`ensure_full_id_space`), находки без
   refs/с выдуманным ID/с пустыми evidence_refs отбрасываются
   (`parse_review_verdict` + тест `test_finding_without_refs_rejected`);
   bounded revision ×2 / patch-контракт `replace_paragraphs` /
   progress criterion / budget ≤6 — без изменений (тест-пин); quote repair
   ladder не тронут.

6. **Durability (зона E):** DDL v24 — один MigrationStep на версию,
   3 additive таблицы (`summary_source_windows` write-once INSERT без
   overwrite; UPDATE-поверхность у окна/стадий отсутствует — scan-тесты;
   DELETE — только TTL-purge терминальных run'ов); state machine §20 с
   rank-guard'ом (checkpoint не отматывается, терминальные не реанимируются);
   resume после рестарта — докат того же стабильного run_id, окно ТОЛЬКО из
   durable snapshot'а (перечитка запрещена — окно дрейфует после
   compress_and_purge; fail-open к свежей перечитке честно отмечен);
   идемпотентность публикации — единый gate `_publication_gate` во всех
   трёх каналах доставки (plain/rich/rich-without-cover): PUBLISHING ДО
   send → published-skip → correlation-reconcile фактом `bot_output_ledger`
   → content-hash барьер (точное совпадение стабильного plain-рендера) →
   retry-лег; fixture «kill в PUBLISHING → рестарт → ровно одна публикация»
   зелёная (обе ветки: kill до/после send) + published блокирует второй
   финал + контрпример «другой текст → retry».

7. **Cover/text + лестница + registry (зона F):** cover-ветка подписана на
   approved text snapshot; rank-guard не даёт cover-checkpoint'ам отмотать
   TEXT_READY (тест); fallback-cover — детерминированный
   `_derive_fallback_prompt` из финального документа (text-fallbacks не
   наследуются); Medved Press fix — лестница `resolve_style_slot_inherited`
   (legs 1–2 байт-в-байт; 3a Connections default с capability image_edit —
   FALSE блокирует, UNKNOWN нет; 3c models.image_* — тот же слот, что
   сгенерировал base cover; 4 — честный not_configured), событие
   COVER_STYLE_RESOLVE с resolve_source; capabilities по ФИНАЛЬНОМУ слоту
   через существующий registry (`image_capabilities.resolve_capabilities*`)
   — хардкодов NanoGPT/Qwen в коде выбора нет (единственное упоминание —
   маршрут live-discovery каталога, существующий); fail-soft ladder §37
   закреплён матрицей M3/M4/M5 (style fail → base cover; base fail → Rich
   без image/plain; Rich fail → Plain с тем же ResponseDocument — текст
   никогда не уничтожается).

8. **Inspector (зона G):** `_coverage_breakdown` — раздельные оси
   source/l1 (input+result+map_degraded)/writer/final/overflow из
   structured state (usage_json + durable stage-rows; guard-тест «не
   парсинг логов»); «839/839 100%» рядом с L1 failed НЕ единый успех
   (fixture-тест обязателен и есть); capacity/liveness/cover-style карточки
   честные (см. п.1 browser-верификация). События §42 — аддитивные,
   существующие имена не переименованы (контрактный тест), overflow-run
   добавляет ровно три сегментных события; reason-коды через
   `mca_events.REASON_CODES` (+17 новых кодов эпика присутствуют);
   R17-скан fixture-тестами чист; нового admin-ключа L1_TIMEOUT нет.

9. **Settings contract (зона H):** запрещённые ключи
   L1_CHUNK_SIZE/L2_TIMEOUT/MAX_INPUT_CHARS/SUMMARY_CONTEXT_TOKENS не
   существуют нигде в коде/тестах; все 12+5+2 новых ключей — env-only
   ClassVar вне каталога (F8 EXIT=0, реестр 488 — Δ=0); демотирование
   `limits.summary_hybrid_context_*`/оконных капов каталога фактически
   обеспечено pre-existing Advanced/legacy-семантикой каталога ASAP-3.1
   (описания «аварийный/legacy, бюджет определяет модель автоматически»).

10. **No scope creep:** дифф целиком в зонах A–G + тесты + инфраструктура
    эпика (pytest.ini-маркер, conftest-изоляция, prompt-миграции с
    superseded-слепками PREV_*_ASAP41 и FORWARD/ROLLBACK ступенями);
    «бесконечный redesign» не наблюдается — второй контур Summary/media не
    построен (паттерн-доноры переиспользованы), Direct/STT/embeddings
    не тронуты, чёрные списки §0.4 соблюдены (числа капов, seeded стили,
    FTS fail-soft, LLM_TIMEOUT для не-Summary).

## Requirement/evidence coverage

- DoD 1–20, 22, 28–30: покрыты реализацией + независимыми тестами
  (236 asap41 + соседи + полный прогон; см. «Checks performed»).
- DoD 21 (no duplicate publication): fixture-доказано.
- DoD 12 (Legacy 50k truncation): dead-path в ON-ветке тестом;
  OFF-ветка = бит-в-бит (капы живы по спеке).
- DoD 13 (MAX_SUMMARY_PARTS input coverage): чтения только в Legacy
  output-каналах + soft target промпта; hybrid/SourceWindow/L1/L2/Rich не
  читают.
- DoD 31–35: **PENDING OWNER / последующие фазы** (PO-1…PO-5) — не
  блокируют этот gate, блокируют archive/DoD-финал (см. ниже).

## Counterexamples checked (позитивные/негативные сценарии)

- Плотное окно 839 → WHOLE_WINDOW 1 запрос; 31+ «факт»-класс → не invalid.
- Окно > allowance → CAPACITY_OVERFLOW, все covered, no truncation
  (ledger XOR-инвариант; «взять 300» невозможен по построению).
- Смена модели → новый cache-key + авто re-plan; fallback меньше →
  oversized НЕ отправляется (честный отказ + capacity-событие).
- Вечный transport-фейл → ровно 4 HTTP → конечная ошибка; 500 → 2 HTTP;
  stalled → cancel → finite fallback; fuse → execution_deadline_exceeded.
- L1 мусор ×2 → Writer от полного окна, Legacy не вызывается.
- Kill до/после send в PUBLISHING → ровно одна публикация; повторный
  заход skip; другой текст → retry (не false-skip).
- Комбинированный OFF всех 9 kill-switches на реальном прогоне с
  temp-SQLite: 0 строк в v24-таблицах, §95-v2 контракт, FactPackage-центр,
  без supervised_transport, legacy-капы живы, style-резолвер байт-в-бит.
- Повторная запись snapshot'а → fail-open без overwrite; UPDATE-скан
  поверхностей чист.

## Blocking findings

### [M-ASAP41-1] [Medium, requirement-blocking, OPEN → RESOLVED round 2] — каталог: аннотация «не управляет Summary» для LLM_TIMEOUT/LLM_TOTAL_BUDGET не добавлена

- **Требование:** spec.md §8.1 (Accepted; T-4602-зона): «`LLM_TIMEOUT` …
  Описание в каталоге дополняется пометкой „не управляет Summary“»
  (аналогично `LLM_TOTAL_BUDGET`). Смысл — закрыть прод-антипаттерн
  «повысить L1_TIMEOUT» (§50/§G.3): админ должен видеть, что ключ больше
  не управляет Summary.
- **Наблюдение:** `services/param_catalog.py:735-736` (LLM_TIMEOUT) и
  `:745-746` (LLM_TOTAL_BUDGET) — описания без пометки; файл в дифф эпика
  не входит вовсе (не редактировался ни одной волной); строка «не управляет»
  отсутствует во всём каталоге/фронте. Тест-контракт R6-H-008 «нет новых
  магических цифр» зелёный, но эта строка судьбы §8.1 не выполнена ни
  одной волной (T-4602 закрыт таблицей в спеке — actionable-часть
  выпала из волн).
- **Impact:** ограниченный (doc-only): поведение корректно (Summary не
  зависит от LLM_TIMEOUT — проверено), но админ-витрина вводит в
  заблуждение ровно так, как это было запрещено принятым контрактом
  настроек. Противоречие «spec §8.1 ↔ код» — конкретная находка цепочки
  «требование → спека → дифф».
- **Корректирующее действие:** дополнить описания двух ключей в REGISTRY
  `param_catalog.py` пометкой (например: «Не управляет фоновым Саммари —
  его длительность определяет супервизор исполнения»), перегенерировать
  meta-артефакты F8 (штатная процедура gen_param_registry_round1025.py
  без --check), F8 --check → EXIT=0. Code-изменение — одна-две строки
  описаний, поведение не трогает.

- **Верификация:** F8 --check EXIT=0 (реестр 488, описания в TSV/map),
  полный pytest известные числа, точечный тест каталога.

#### Round-2 разрешение [M-ASAP41-1] — RESOLVED (закрыт)

Независимые проверки дельты (все — собственные прогоны ревьювера):

1. **Дифф `services/param_catalog.py` — ровно 2 строки** (`git diff HEAD
   --numstat` = 2/2): у `LLM_TIMEOUT` (:736) и `LLM_TOTAL_BUDGET` (:746)
   добавлен только хвост `description` — маркер spec §8.1 «не управляет
   … Саммари (Summary)» дословно + причина «длительность Саммари
   определяет супервизор исполнения». Значения/типы/группы/
   settings_field байт-в-байт (assert-инварианты теста + diff-read).
   Runtime-семантика LLM_* для не-Summary не тронута (AM-3 boundary).
2. **Новый тест**
   `tests/test_summary_param_catalog_annotation_asap41.py` — **5 passed**
   (собственный прогон): маркер у обоих ключей; пояснение супервизора;
   **негативный sweep** — у остальных 486 ключей пометка отсутствует
   (охват ровно 2 ключа §8.1); doc-only инварианты
   type/group/settings_field.
3. **F8-артефакты перегенерированы штатно:** TSV-дифф = ровно 2 строки
   (llm_timeout/llm_total_budget); meta.md — счётчики 488/105/103/21/77
   без изменений (runtime-импорт `param_catalog` ревьювером: фактические
   счётчики совпадают); `gen_param_registry_round1025.py --check` →
   **EXIT=0** («CHECK OK: реестр 488 == REGISTRY…», собственный прогон).
4. **`f8_baseline.json` — минимальный дифф 2 строки** (sha256.map +
   superseded_by): sha256 `param_catalog.py` = ec2d9dc7… — сверено
   ревьювером с фактическим файлом (match); app_version остаётся
   историческим 2.58.15 (прецедент round1026/ASAP-2.1/extra-cover);
   замороженные invariants-тесты green. Маркеры/счётчики не ослаблены
   (REGISTRY 488, delta 77 — как было).
5. **Точечные прогоны (собственные):** целевые **68 passed**
   (annotation 5 + f8_registry 29 + param_catalog 34); сосед
   `test_settings_helpers.py` **48 passed**; prompt-миграции
   (asap21 + общий) **52 passed**; py_compile EXIT=0; выборочно
   asap41-соседей (supervisor + capacity + coverage-ledger + off-parity
   + deploy + resolver) — **141 passed**; JS
   `asap41_zone_g_inspector_test.js` → ZONE-G-INSPECTOR-OK. Полный
   pytest осознанно не перезапускался (doc-only дельта вне runtime;
   вердикт round-1: «полная ре-аудит-волна не требуется» — базис
   11074–11077 не зависит от строк описаний).
6. **WTH пересчитан (recipe round-1)**: манифест-протокол скопирован в
   `plans/reports/asap41_wth_manifest_review_round2.txt` — 76 файлов,
   per-file SHA-256, обновлены ровно 3 записи (evidence.md/tasks.md
   — добавленные секции пост-gate фикса, workflow_state.md);
   остальные 73 файла байт-в-байт с round-1. WTH-round2 =
   `BA44A8CD…7419246`; сам round-1 манифест воспроизведён ревьювером
   байт-в-байт (452AB73F… — SHA-256 сырых байтов файла как есть).
7. **Спека неизменна весь эпик** (Spec-Hash round-1 == round-2,
   байт-в-байт).

**Remediation:** единственный blocking Medium round-1 закрыт ровно
по предписанному корректирующему действию (без отклонений). Вердикт
round-2: **Approved for release** (полная ре-аудит-волна ядра не
требовалась — не выполнялась).

#### Round-2: недоступные проверки (Unavailable checks round 2)

- Полный pytest (базис 11074–11077) после doc-only фикса осознанно не
  перезапускался — покрыто выборочными точечными прогонами (см. выше)
  и вердиктом round-1 «полная ре-аудит-волна не требуется».
- Browser/JS-детали эпика — round-1 (в силе); в дельте UI-поверхность
  не менялась.
- PO-1…PO-5 (live-прогоны владельца) — PENDING OWNER, как в round-1.

## Non-blocking debt (bounded follow-up, регистрируется в full_audit_results)

- [L-ASAP41-1] [Low, disclosed]: иерархический Writer (CAPACITY_OVERFLOW)
  пропускает semantic review — видимо (ctx.health=degraded +
  L2_REVIEW_SKIPPED reason=writer_hierarchical), прецедент paged-L2;
  B.4-идеал (evidence-slices reviewer на этом пути) — отложенный업грейд.
- [L-ASAP41-2] [Low, disclosed]: stage-level resume skip — докат
  пере-прогоняет LLM-стадии по immutable snapshot с тем же run_id; дубликат
  публикации исключён gate'ом (DoD 21 доказан); persist map/draft-артефактов
  для переиспользования result_ref — отдельное решение.
- [L-ASAP41-3] [Low]: `SupervisedCallState.http_attempts` — верхняя
  граница ноги (≤2), а не точный счётчик; в `_fallback_attempt`
  не инкрементируется в asyncio.TimeoutError-ветке (чисто счётная
  косметика; потолок ≤4 закреплён transport-тестом).
- [L-ASAP41-4] [Low]: `purge_summary_source_windows_gated` при исключении
  fail-open к ungated purge — окна старше TTL активных run'ов могут быть
  удалены при сбое гейта; resume в этом случае честно отменяется
  (fail-open к свежей перечитке), потери контента нет.
- [L-ASAP41-5] [Low, pre-existing, вне эпика]: флап
  `test_betterstack_handler::test_real_302_not_followed_by_opener`
  (~1/6 локально) на неизменённом коде — гонка фонового флапера/досылки
  shutdown'а в тест-фикстуре; в дифф эпика не входит, к релизу не относится;
  рекомендуется отдельный собственнический фикс (стабилизация теста).
- [L-ASAP41-6] [Low, pre-existing]: 2 known web/-bounds падения
  (round1026) — вне эпика, ранее задокументированы; фиксятся санкцией
  allowlist'ов вне этой фичи.

## Unavailable checks

- Live production acceptance §48 Run 1/Run 2, §49 Medved Press, §50
  прод-замеры (PO-1, PO-2, PO-3, PO-5) — платные live-вызовы, ресурс
  владельца; не выполнялись ни Builder'ом, ни ревьювером (по планированию
  вне скоупа команды).
- Live-верификация Mode A/B провайдеров (PO-4) — контрактные слоты,
  честная база Mode C закреплена тестами.
- Атрибут-качество LLM (правильность атрибуции/прозы) — механизм полноты
  входа закреплён fixture-тестами; семантическое качество — прод-приёмка
  §48 Run 1 (PO-1).

## PENDING OWNER (честно, не blocking для этого gate)

| # | Гейт | Статус |
|---|---|---|
| PO-1 | §48 Run 1 — большой реальный прогон (839+, large-context) | PENDING OWNER |
| PO-2 | §48 Run 2 — lower-capacity прогон + возврат конфига | PENDING OWNER |
| PO-3 | §49 Medved Press — живой image-edit прогон | PENDING OWNER |
| PO-4 | Live-верификация Mode A/B адаптеров | PENDING OWNER |
| PO-5 | §50 прод-замеры (базис 622/155/1331, без SLA) | PENDING OWNER |

Без PO-1…PO-5 feature не финализируется (DoD 31/32/23–25) — это
known-blocker финализации, не расхождение планирования; деплой-работы
команды (T-4630) от них не зависят.

## Вердикт

**Round 1: Needs Fixes** — единственный блокер [M-ASAP41-1] (doc-only
аннотация каталога, ~2 строки + перегенерация F8-meta). После точечной
коррекции (без изменения поведения) достаточно ревью дельты: F8 --check
EXIT=0 + точечные тесты; полная ре-аудит-волна не требуется. Все 9
«проверь сам» линий gate независимо подтверждены (механизм против
заглушки, OFF-паритет, AM-1…AM-4, durability, лестницы, Inspector, DDL,
R17, прогоны).

**Round 2: Approved for release** — дельта-ревью фикса [M-ASAP41-1]
закрыл блокер ровно по предписанию (см. раздел Round 2 выше); вердикт
round-1 по ядру эпика в силе и не изменился. Binding актуализирован
(см. Round-2 binding). PO-1…PO-5 остаются PENDING OWNER (не блокируют
релиз, блокируют финализацию/DoD-архив — как и в round-1).

## MEMORY_DELTA (оркестратору)

- Финальный gate T-4629 эпика `asap-4-1-durable-whole-window-summary`
  (R3): round 1 Status **Needs Fixes** — 1 blocking Medium [M-ASAP41-1]
  (param_catalog.py: описания LLM_TIMEOUT/LLM_TOTAL_BUDGET без
  обещанной spec §8.1 пометки «не управляет Summary»; doc-only).
  Binding: HEAD 60f1c7c, WTH 452AB73F…, Spec-Hash E6A6E5EC….
  0 Critical/High; 6 Low non-blocking (в т.ч. 2 pre-existing web/-bounds
  и флап betterstack-теста вне эпика). PO-1…PO-5 — PENDING OWNER.
  Отчёт: plans/features/asap-4-1-durable-whole-window-summary/review.md;
  focused-audit запись: plans/reports/full_audit_results.md; WTH-манифест:
  plans/reports/asap41_wth_manifest_review.txt.
- **Round 2 (дельта-ревью фикса [M-ASAP41-1]): Status
  `Approved for release`**. Блокер закрыт (дифф param_catalog.py ровно
  2 строки описаний; новый тест 5 passed, негативный sweep 486 ключей;
  F8 --check EXIT=0, счётчики 488/105/103/21/77; f8_baseline.json
  минимальный дифф 2 строки — sha256 ec2d9dc7… сверён, app_version
  исторический 2.58.15). Binding: HEAD 60f1c7c (не менялся),
  WTH-round2 `BA44A8CD…7419246` (манифест round2: 76 файлов, 3 per-file
  хеша обновлены = документация фикса), Spec-Hash E6A6E5EC… байт-в-байт.
  Round-1 манифест 452AB73F… воспроизведён байт-в-байт. Полный pytest
  осознанно не перезапускался (doc-only дельта). round-1 Low-находки
  в силе. Отчёт round-2 — тот же review.md (раздел Round 2).
