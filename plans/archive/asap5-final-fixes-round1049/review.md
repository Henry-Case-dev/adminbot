# review.md — asap5-final-fixes (T-5271, независимое ревью)

**ВЕРДИКТ: APPROVED** (к деплою 2.58.68; с обязательной диспозицией finding F1 до закрытия фичи)

Дата: 07.10.2026 · Ревьюер: parent Reviewer (leaf fan-out недоступен — depth limit, все линзы закрыты одиночно).
Кандидат: working tree поверх HEAD `e9d71c8` (mca-release 10.48, прод 2.58.67). 3 Builder-лейна + интеграционный барьер T-5270.

## 1. Binding

- Манифест: `t5270_candidate_hashes.json` (143 файла, SHA256). Моя сверка: **142/143 MATCH, 0 missing**; единственный дрейф `plans/workflow_state.md` — задокументированный чужой WIP параллельных сессий, вне кандидата (integration_evidence §6). Код/тесты/эвиденс — бит-в-бит.
- Пин-фикс mca01 write-points: `git hash-object tests/test_mca01_tx_task_supervisor_round1027.py` = `c10a151a740b1a9908da5f83b3a30c904cce3a92` — совпадает с integration_evidence §3.
- routes.py: НЕ в манифесте (= не менялся); файл-SHA256 `8153b8bd…c7b45` = байт-freeze пин цел. settings.py / mca_events.py — аналогично не тронуты.
- APP_VERSION (факт): `config/settings.py:3209` = **2.58.67**, бампа 2.58.68 в дереве НЕТ. Отклонение от SERIALIZE-5/D18 как написано («бамп на интеграции») санкционировано брифом/интеграцией: бамп — у DevOps при деплое. Зафиксировано; «пустой бамп» не образуется (код-дельта есть).
- Числа барьера брифа «12433/5» устарели: финальный лог барьера (`full_pytest_t5270.log`) = **12434 passed / 4 failed** (сегменты 12423 + `test_104_backend_additions` 11 — 11/11 перепрогнано мной; collect 12438/0 ошибок). Все 4 failed = поимённо документированные pre-existing identity (tool_loop / nav_disclosure / status_control / mca09-registry). mca09-cancelled флейк из брифа в финальном прогоне не воспроизвёлся.

## 2. Моя верификация (новые прогоны/замеры, не reuse)

| Проверка | Результат |
|---|---|
| Манифест хешей 143 файла | 142 MATCH / 1 дрейф (чужой WIP, см. §1) |
| Census импортом | каталог **529** (=санкция +6), KS **85**, reason **280**, тулы **14**, реестр **47** |
| DDL | `test_mca17c_invariants` (в составе 104/104) ассертит `user_version == 33` на свежей БД — Δ DDL = 0; v34 не активировалась |
| routes-пин | файл-SHA = `8153b8bd…c7b45`, конец `c7b45` — байт-в-байт |
| Новые домен-тесты 6 файлов | **73/73 passed** (19+21+6+15+7+5) |
| Пин-набор mca17c+f8+param_catalog+mca01 | **104/104** (вкл. mca01 33/33 после пин-фикса) |
| `test_104_backend_additions` | 11/11 (закрывает арифметику 12423+11=12434) |
| JS по-файлово (63 файла, exit-codes) | **63/63** |
| R17-скан дельты (93 файла services/web/tests, 6 паттернов) | 8 хитов — все комментарии санитайзера и синтетические анти-лифик фикстуры (`sk-1234…` в тестах маскирования). Новых секретов **0** |
| Трасса decision_trace | сквозная: `summary_generator` final_policy → `pipeline_analytics.py:1673` view → существующий inspector-API → `app.js:3239` computed → `index.html:4267+` рендер |

## 3. Findings

### F1 — CoverPromptManifest не подключён к API/UI (T-5252/T-5253 не доставлены) — related-nonblocking для кандидата, REQUIREMENT-DRIFT для фичи [High visibility]
- **Факт:** в `web/` (app.js, index.html, web/api/*) ноль использований `job_manifest`/`prompt_manifest` (grep). Манифест персистится в `task_jobs`, admin-reader `cover_style_preview.job_manifest` готов, но HTTP-поверхности нет.
- **Нарушенный критерий:** spec §6 R11 («Prompt Assembly-таблица», 15E#2/#3), R12 («Analytics: attempts 1/2, обе строки admin», 15E#4); D7-контракт чтения («расширение ответов существующих API»); INV-3 («каждое сокращение видно владельцу в UI»).
- **Механика/смягчение:** честно задокументировано в evidence B2 («Что осталось») и integration §1 (скоуп лейна без web-файлов). Корневой прод-дефект C2 (потеря сюжета в retry) исправлен в коде (compile/retry-core); персист + fail-closed masking работают; регрессий нет.
- **Impact:** владелец пока не видит «что реально ушло» по cover через UI; фича не завершена в части D7-прозрачности.
- **Действие:** явная диспозиция Orchestrator до закрытия фичи: отдельный web-слайс (T-5252/T-5253) до/вместе с T-5274 live-приёмкой. Деплой 2.58.68 не блокирует (аддитивно, fail-closed).
- **Smallest recheck:** появление `job_manifest` в web/api/cover_styles.py + рендер в Constructor/Analytics; visual 15E#2–#4.

### F2 — Не-await-нутая coroutine тика resume в тесте — Low, related-nonblocking
`full_pytest_t5270.log` warnings: `RuntimeWarning: coroutine 'start_resume_ticker.<locals>._loop' was never awaited` (test_summary_memory). Тест зелёный, функционального влияния нет; гигиена. Кандидат в backlog рядом с уже задокументированным Advisory (обернуть `set_embedding_generation_status`/`embedding_canary_check` в `serialized()` при активации воркера).

### F3 — Наблюдения (без действий)
- Anchor-mode: unknown-код находки остаётся minor-находкой (не dropped_invalid, как в не-anchor ветке) — НИКОГДА не blocking (severity server-owned); свойство целостности соблюдено, формулировка спека шире факта. Nonblocking.
- Soft-only degraded publish возвращает usable=True с `l2_review_degraded=1` (B1 incidental 4) — соответствует §50.29; health/policy помечают деградацию честно (тестами закреплено).
- B3-хвосты вне суженного скоупа (честно задекларированы): полный per-chat migration engine/GC/multi-chat fusion (13N#7–14/19/20/22/27), MiniApp embeddings UI (13J/13K, #23/#24). D12-субстрат (state machine, migration jobs, shadow-чанки) доставлен и протестирован. Требует той же диспозиции завершения фичи, что F1.

Блокеров: **0**.

## 4. Разбор доменов (инспекция кода)

### Summary (B1, D1–D6) — подтверждено
- **D1:** `summary_generator.py:1951-1959` — durable stage `l1` = `ok`|`degraded_map_fallback`; `failed_terminal` пишется ТОЛЬКО на empty-payload путях (`:1996-1998`, `:2022-2024`), когда Writer не стартовал; writer-source ON → fallback package, L1-fail не терминален. Витринная ось — `pipeline_analytics` (degraded по факту «L2-стадия была»), ⚠ вместо красного креста.
- **D2:** `summary_l2_review.py:193-216` — ровно 15 кодов: 13 hard (can_force_legacy=True) + 2 soft (duplicate_event, major_topic_omitted, False); `finding_severity` server-owned (`:225-231`), модельное поле advisory; anchor-mode `_verdict_from_anchor_result:462-478` — severity по коду.
- **D3:** `_unusable_gate_accepts:415-429` — terminal только при ≥2 hard И ≥2 разных кодов И ≥2 разных paragraph targets, либо `_deterministic_unusable_proof` (quote_reason_codes). 1 HARD ≠ terminal; даунгрейд → needs_fixes с трейс-событием `l2_unusable_gate` (`:1154-1180`); 0 findings после даунгрейда → degraded publish, не Legacy.
- **D4:** `_hard_fingerprints:432-441` = (code, paragraph, sorted refs); target ≡ paragraph_id (задокументировано — единственная якорная ось); progress = prev−curr ≠ ∅ (`:1203-1208`), стагнация = тот же набор ИЛИ неизменившийся документ (sha256[:16]); break с событием `l2_stagnation_fingerprint`. MAX_REVISIONS/CALL_BUDGET не растут (пин-тест).
- **D5:** итог цикла `:1387-1401` — soft-only → `_degraded_or_legacy(reason=l2_soft_only_needs_fixes)` (переиспользование §50.29, точная причина в `l2_review_degraded_reason`); HARD/deterministic proof → Legacy fail-closed (INV-1). Writer/Reviewer раздельные исходы; RU-текст `l2_review_unusable` честный (REASONS_RU `pipeline_analytics:110`).
- **D6:** `_final_policy` — 5 точек исхода (`:2302/2371/2386/2389/2401-2420`), строка `stage='final_policy'` в существующей `summary_run_stages` (Δ DDL=0); `_decision_trace` (`pipeline_analytics.py:1274-1310`) — 5 секций из существующих stage_events (≤24, R17-safe проекция, cap 12) + durable-строк; UI подключён (index.html:4267+, app.js:3239); JS-тест asap5_decision_trace в базлайне 63.
- Тесты: RED-first артефакт подтверждён (канон-тест `test_unusable_verdict_legacy_immediately` переписан в пару по новому контракту); audit-пути не mock-only (domain-тесты гоняют реальные функции разбора).

### Cover (B2, D7–D9) — подтверждено
- **SERIALIZE-1:** `summary_generator.py:92-100/289-300/3559` — shim re-export `compose_cover_image_prompt`/`COVER_IMAGE_PROMPT_MAX`/`_derive_fallback_cover_prompt` (делегация в `cover_prompt_assembly`); AST-пин `test_summary_deploy_round1026` верифицирует собранную логику в новой локации (26 passed в составе прогонов; файл в манифесте MATCH).
- **D7:** `cover_prompt_assembly.py` — схема `cover_prompt_manifest/1`, 6 компонент, `attempts[]` (обе строки, `:350-360`), `prompt_hash` sha256[:16]; `manifest_public:411-429` fail-closed (без include_prompt=True тексты вычищаются, включая components.original/sent); персист Style Edit → `CoverJobState.prompt_manifest` (task_jobs payload), Base → `record_base_cover_manifest` kind=cover_base; в generic логи полный prompt не попадает (SAFE_LOG_FIELDS не расширялись — grep).
- **D8:** Base = STORY+SUMMARY_CONTEXT+BASE_STYLE; SUMMARY_CONTEXT ≤400 от финального Summary, 0 LLM; без контекста — байт-в-бит legacy (тест `test_base_compose_without_context_matches_legacy` в 73).
- **D9:** `minimal=True` отсутствует (grep по services — 0 в retry-семантике); `compile_style_prompt(retry_core=True)` (`cover_style_jobs.py:1155-1217`) = runtime P0 полностью + `profile_identity_floor` (≥50%, граница слова) + base style + `reference_roles_text` (roles не выбрасываются молча) + `story_floor_text` (≥160 или 100%); unknown → `unit="unknown"`, `resolved_limit=None` без выдуманного числа, `reason="semantic_squeeze"`; retry ≤1, resend только если строго короче (`:1895-1905`); `budget_floor_text` в `image_prompt_compiler.compile_prompt:262-270` — floor перед drop'ом сюжета, legacy-OFF путь байт-в-байт.
- Репро: `TestPreFixReproduction`/`TestUnknownRetryStoryMinimum` кодируют прод-механику 911→708 (минимальный retry без «Сюжет»), RED на прежнем составе — проверено содержанием теста и зелёным прогоном на кандидате.

### B3 (D10–D15) — подтверждено
- **D10:** `RESUME_TICK_SECONDS=900` (`graphrag_rebuild.py:109`), `start_resume_ticker` идемпотентен, `resume_tick_once` = `maybe_schedule_rebuilds(include_failed=False)`; cooldown-окно → no-op (`:1770-1771`), после истечения — resume следующим тиком, в т.ч. в новом процессе; warning-коалисинг/guard не тронуты; `knn_source_empty` stable terminal при пустом источнике (`:1778-1786`) с reopen при появлении строк (`_source_empty`); rebuild_status → существующий GET /api/memory/embeddings (поле `rebuild`, без нового роута). Симуляция рестарта — в test_asap5_graphrag_recovery (6/6).
- **D11:** `embedding_identity_v2:1874` — sha256[:16] канонического JSON; key/quota/timeout identity не меняют (тесты 13N#3/#21); canary `CANARY_TEXTS` (3 фиксированные строки, нечувствительные) в `embedding_cache`, косинус mean<0.98/min<0.95 (`:1765-1766, 2031`), не byte-hash; недоступность → unknown fail-safe; `classify_identity_compatibility` — одна классификация; same dim + diff model → REINDEX (тест).
- **D12:** валидатор переходов OPT-IN, frozen-терминалы; migration jobs kind=`embedding_migration` (coalesce); чанки через существующие shadow-хелперы graphrag + checkpoint; shadow `{index}_g{gen}`; атомарный swap `_activate`; DDL=0 (v34 не потребовалась — entry-check задокументирован).
- **D13:** `config_cache.get_all:478-523` — синтетика ТОЛЬКО `keys_random` (`_SYNTHETIC_SECRET_GROUPS:50`), только незаданные ключи, секреты → "" (маска configured=false), не-секреты → честный дефолт Settings; деривация на чтении — строк в БД не создаёт; реальный ключ вытесняет синтетику (`key in self._settings` skip). routes.py не тронут (пин цел) — санкция «byte-freeze вместо region-фикса» соблюдена.
- **D14:** `memory_agi.py:660-666, 679-718` — scheduler-причины больше не подменяют last-attempt (`paradigms_reason` = `_last_deep_reason`); независимые поля `scheduler_gate`/`last_attempt_result`/`last_attempt_at`/`last_attempt_retry_class`/`next_auto_attempt_at`; класс C bootstrap: 2 ч интервал, кап 6/сутки по всем попыткам; класс B — существующий Gate 7a без ослабления (тест); структурные причины — прежний empty-state (паритет).
- **D15:** `app.js:15135-15526` — presentation-only: `drawThreshold/maxVisible`, zoom-гистерезис far/medium/close, `_graphFullLabels` + title, `graphApplySelectionLabels` neighborhood; DataSet не режется (тест nodes/edges до=после); routing-харнесс обновлён (стаб), инварианты 10.37 целы (js 63/63).

### Интеграция (кросс-лейн) — подтверждено
- SERIALIZE-1 порядок соблюдён (shim-зона B2 в summary_generator; B1-зоны L1/policy рядом без пересечения — хеши финальные MATCH).
- app.js/index.html: секции B1 (Run Inspector) и B3 (random/paradigms/graph) разнесены; B2 web-правок нет (что и зафиксировано как F1, не потеря правок — их не было).
- Инцидент git-checkout B3→B2 (откат 4 cover-тест-амендов): восстановлено, финальные хеши всех 4 файлов в манифесте MATCH; пин-фикс mca01 `c10a151a` подтверждён.
- Полный suite: 0 новых red; mca01 33/33; js 63/63; collect 12438/0.

## 5. Checks vs reused evidence

- Reuse (валидный, воспроизводимый): полный pytest 12434/4 (лог артефактом), фокус-прогоны лейн, F8 --check EXIT=0.
- Перепроверено мной: binding 143 хешей, census (5 чисел + DDL + пин роутов), 73 новых тестов, 104 пин-теста, 11 backend_additions, js 63/63 по-файлово, R17-скан, AST/hash пин-фикса, сквозная трасса decision_trace, код-инспекция всех шести D-доменов по чек-листу брифа.
- Security-репро из брифa: unusable-gate (1 HARD не терминален — код+тест), squeeze story-minimum (код+репро-тест) — закрыты.
- Недоступно/не требуется: живые real-provider приёмки T-5248/T-5254/T-5274 — owner-gate, no-false-acceptance (не имитируются; вне кодового ревью).

## 6. Итог

Кандидат целостен: санкции §1.2.14 цифра-в-цифру (DDL 0/v33; каталог 529=+6; KS 85; reason 280; тулы 14; реестр 47; routes-пин байт-в-байт; APP_VERSION 2.58.67 без бампа — бамп у DevOps), 0 новых red, сериализация и пин-фикс санкционированы и верифицированы, R17 чисто.

**APPROVED** → сигнал Scanner (параллельно) + деплой 2.58.68 (@DevOps; bump на деплое, миграционный smoke не требуется — Δ DDL=0).

Обязательно до закрытия фичи ASAP 5 (не блокирует деплой): диспозиция F1 (web-слайс CoverPromptManifest T-5252/T-5253) и хвостов B3 (embeddings UI 13J/13K, per-chat migration orchestration) + owner-gates T-5248/T-5254/T-5266/T-5274.

---

# Итерация 2 (web-слайс T-5252/T-5253) — дельта поверх итерации 1

**Вердикт: Approved (web-слайс)** — F1 закрыт в доставленном объёме; сигнал на деплой 2.58.69.

Дата: 07.10.2026 (дельта-речек, ревью итерации 1 в силе). Кандидат: working tree поверх HEAD `dd134cc` (прод 2.58.68). Дельта 5 файлов, +101/−0: `web/api/cover_styles.py` +10, `web/app.js` +46, `web/index.html` +45, `tests/test_asap5_cover_manifest_web.py` (new), `tests/js/asap5_cover_manifest_test.js` (new).

## 1. F1 диспозиция — закрыт (доставленный объём)
- Сервер: СУЩЕСТВУЮЩИЙ `GET /api/cover/test-style/{job_id}` при `_viewer_is_admin` (= `user_is_global_admin`, exception → False) дополняет ответ `prompt_manifest = preview_jobs.job_manifest(db, job_id, include_prompt=True)`; `None` → ключа нет. Не-админ — ключа нет вообще (R17, fail-closed). Новых роутов 0.
- UI: поллер `coverStylePollJob` держит `prompt_manifest` в ОБЕИХ ветках (completed/failed); блок «Что отправилось модели» (`data-cover-manifest`) с двойным гейтом: серверный `is_admin` + `coverStyles.isAdmin` в v-if и `coverManifestVisible` (нет манифеста/компонент → блок скрыт, не «пусто»). Слои независимы: устаревший/подменённый isAdmin не даёт данных — сервер их не отдаёт.
- Схема-матч: UI читает ровно существующие поля сериализации (`sent_chars/original_chars/priority/status/reason`, attempts `attempt/chars/outcome/reason/prompt_hash`, `resolved_limit/limit_source/provider/model/route/prompt_hash`).
- Репро через HTTP-поверхность (TestClient + durable job): тест 1 — админ получает полный манифест (include_prompt=True: 6 компонент D7, attempts с полными строками, prompt_hash); тест 2 — не-админ 200 и ключа НЕТ (базовый снимок жив); тест 3 — админ без манифеста — ключа нет; тест 4 — пин-сторож routes.py.

## 2. Binding (хеши пересчитаны мной post-дельтой, все MATCH evidence)
| Файл | sha256[:16] |
|---|---|
| web/api/cover_styles.py | `5f4ce81ee0b49218` |
| web/app.js | `d6c3f3a81d2b9f3b` |
| web/index.html | `1673bf0ed4580448` |
| tests/test_asap5_cover_manifest_web.py | `023d794a8bbaf045` |
| tests/js/asap5_cover_manifest_test.js | `edf4108c731445be` |

- routes.py: файл-SHA256 `8153b8bd389711e9cb7a61352e58f6f8217c0a236575f75489ca617c0d0c7b45` — пин `8153b8bd…c7b45` бит-в-бит, Δ эндпоинтов 0.
- `t5270_candidate_hashes.json`: 143 → 146 (обновлены app.js/index.html, добавлены cover_styles.py + 2 тест-файла; diff файла 5+/2−, CRLF сохранён; self-check drift=0).

## 3. Прогоны (мои, post-дельта)
- `tests/test_asap5_cover_manifest_web.py` — **4/4**.
- Cover-семейство (`-k cover`) — **539 passed / 0 failed** (надмножество заявленных 69).
- JS — **64/64** файлов exit 0 (вкл. новый `asap5_cover_manifest_test.js`).
- R17-скан дельты (6 паттернов) — **0 хитов** (синтетика тестов — фикстуры).

## 4. Честные остатки спеки (non-blocking для деплоя, хвост ASAP 5)
Доставленный слайс = read-surface манифеста (endpoint + карточка Constructor, счётчики/статусы/hash/причины). По спеке шире, остаётся открытым (как хвост фичи, НЕ регрессия, деплой 2.58.68→69 строго аддитивен и fail-closed):
- R11 «FINAL PROMPT полностью»: UI рендерит counts/hash, полные тексты (final_prompt/attempts.prompt/original_text/sent_text) приходят в ответ админу, но не отображаются.
- T-5253 Analytics-поверхность (Run Inspector Cover: Base/Style раздельно; visual 15E#4) — не в дельте.
- T-5252 «Settings UI: Что реально уйдёт модели» (pre-send прогноз) — не в дельте.
- «3 UI» из R8: доставлено 2 из 3 (карточка completed + failed-ветка).

## 5. Checks vs reused
- Reuse: ревью итерации 1 (Approved, код-субстрат D7/manifest_public не менялся — хеши services/ бит-в-бит).
- Новое: 5 хешей дельты, routes-пин, 4 py-теста, cover 539, js 64, R17, код-инспекция гейтов (fail-closed оба слоя), сверка схемы UI↔сериализации.
- Недоступно/не требуется: live visual 15E#2–#4 — owner-gate T-5274 (как в итерации 1).

## 6. Итог
**Approved (web-слайс)** — деплой 2.58.69 разрешён: Δ только read-side + UI + тесты, routes-пин цел, DDL/каталог/KS/reason не менялись, R17 чисто. Откат: soft `git revert` (read-side нейтрален).
