# Scanner-аудит — Эпик 2 / S9 `summary-testing-ui-round1026` (T-3374, Step 6)

- **Дата:** 24.09.2026. **Аудитор:** @Scanner (focused diff-based).
- **Diff base:** HEAD `cc6105c` (`docs(plans): round1026 S5 — closing docs …`). Правки **НЕ закоммичены**.
- **Тип ревью:** только изменённые файлы + критические зависимости.
- **Итерация:** **2** (повторный аудит после rework T-3375). Итерация 1 — историческая запись ниже.
- **Вердикт итерации 2:** **К ДЕПЛОЮ ДА** — блокирующих нет (**C0 / H0 / блокирующих Medium 0**). Прежние блокеры `B-R1026S9-1` и `B-R1026S9-2`/`S-R1026S9-1` — **RESOLVED** (подтверждено независимыми пробами). Остаются **Low 5 / Info 2** (owned follow-up) + 1 новый **Low** (doc-drift `503`).
- **Связанные документы:** `plans/features/summary-testing-ui-round1026/{spec.md,adr-1026-8-…,evidence.md,tasks.md,review.md}`.
- **ID-пространство:** `S-R1026S9-*` (@Scanner). Новый: `S-R1026S9-5`.

---

## 1. Итерация 2 — что проверял и как (мои пробы, не пересказ Builder)

| Проба | Метод | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **8854 passed / 0 failed** (120.75 s) — совпало с заявленным |
| JS-набор | `node tests/js/*.js` (44 файла) + `node --check web/app.js` | **44/44 OK**; `round1026_s9_testing_test.js` → `SUMMARY-TESTING-UI-OK`; `node --check` exit 0. (Одиночный транзиентный сбой `routing_test.js` в моём первом цикле **не воспроизвёлся** — standalone exit 0; артефакт харнесса, не код.) |
| Контракт error-payload (4 пути) | `run_summary_test(generator=None)` / `error_result(TEST_RUN_FAILED)` / `empty_payload(running)` / ошибка чтения окна → `present_result` | **все 4** → полные `metrics`+`artifacts`+`display`, `metrics.tokens.l1` присутствует, `artifacts.source==[]`, `diagnostics≥1` (кроме running — 0), `drop_percent=None`. Нет `undefined.l1`. |
| UI-guards (реальная логика `app.js`) | `node tests/js/round1026_s9_testing_test.js` блоки (g)/(h) | error/частичный payload → guard `null` (без падения); **полный payload → guard truthy** (успешные секции не скрыты); `drop_percent=null → «Нет данных»`, `12.5 → «12.5%»`. |
| «Процент отсева» в UI | `Select-String "отсев\|drop_percent" web/index.html web/app.js` | **3 совпадения**: `data-summary-test-drop` «Процент отсева», computed `summaryTestDropPercent`. |
| Retention running (TTL) | собственный `_RunStore.put_running` + `created = now − TTL − 100` → `get` | **KEPT** (`active_count=1`) — running не вычищается. |
| Retention running (эвикция) | 1 running + 25 finished → `put_running` | running **сохранён**, размер store = 20. |
| Fail-open метрик | `build_test_rows` со stale `_filter_metrics[chat]` + `_apply_filter` fail-open | `filter_metrics == {}`, `restored_count == 0` — stale не подтягивается. |
| 0/0/0 (свои шпионы) | patch `telegram_send.{send_text,send_rich_message,send_photo,build_cover_media}`, `image_generation.{generate_image,generate_image_verbose}`, `summary_memory.*`, `SummaryGenerator.{_hybrid_l2_enabled,_run_hybrid_l2}` + fake LLM | `status=ok`; `await_count==2` (steps `l1_clusterizer`,`l2_writer`); **все шпионы 0**; `memory.writes==0`; `SUMMARY_HYBRID_L2_ENABLED` до==после; hybrid не вызван. |
| Каталог / версия / флаг | импорт `param_catalog` + `dataclasses.fields(Settings)` | **469 / 426 / 444 / 100 / 98 / 21**; `APP_VERSION == "2.58.25"`; `SUMMARY_TEST_UI_ENABLED == True`; ∉ REGISTRY и ∉ полей. |
| R18 | `git for-each-ref refs/tags/pre-round1026-s9` + `git rev-list -n 1` | annotated `9f4305a` → commit **`cc6105c`** (= HEAD). |
| Additive генератора | `git diff cc6105c --numstat -- services/summary_generator.py` | **55+/0−** (только `build_test_rows` + reset-строка внутри него; тело `_run`/`_run_hybrid_l2` не тронуто). |
| Вне diff | `git status --porcelain -- <files>` | `routes.py`/`image_generation.py`/`telegram_send.py`/`param_catalog.py`/`database.py`/`pg_db.py`/`summary_memory.py`/`summary_xml.py` — **пусто**. |
| Whitespace | `git diff --check` | exit 0 (только LF/CRLF-предупреждения). |

---

## 2. Статус прежних находок

- **B-R1026S9-1 [Medium, requirement gap] — RESOLVED.** §112 «Процент отсева» выведен: `web/index.html` `data-summary-test-drop`; `web/app.js` computed `summaryTestDropPercent` (`null`/неизвестно → «Нет данных», без выдуманного `0`). Подтверждено grep + JS-блок (h). ✅
- **B-R1026S9-2 / S-R1026S9-1 [High, UI-render] — RESOLVED.** Сервер: `_empty_metrics`/`_empty_artifacts`/`_empty_display` в `_base_result`; `present_result` нормализует `metrics`/`artifacts`; `error_result` (диагностика) для `_execute`-catch-all; `empty_payload` для running. UI: guards `v-if="summaryTestMetrics"`/`summaryTestArtifacts` (не скрывают успех). Мои 4 пробы payload + JS-блок (g). ✅
- **S-R1026S9-2 [Low, robustness] (== L-R1026S9-3) — RESOLVED.** `_purge` исключает `running`; эвикция не выбирает running. Пробы: KEPT после TTL, сохранён при переполнении. ✅
- **S-R1026S9-3 [Low, contract/docs] (== L-R1026S9-4) — RESOLVED (spec/README).** spec §5.2: `503 не используется` + контракт `202`/`200`+`status="error"`; README: «…кроме отдельного подтверждения обложки». **Остаточный doc-drift — новый `S-R1026S9-5` ниже.** ⚠️→Low
- **S-R1026S9-4 [Low, metrics] (== L-R1026S9-5) — RESOLVED.** Сброс `_filter_metrics[chat_id]` перед `_apply_filter` в `build_test_rows`; проба fail-open → `{}`/0. ✅
- **L-R1026S9-1 [Low, docs/R18] — RESOLVED.** `evidence.md`/`tasks.md` → deref-commit `cc6105c` (подтверждено). ✅
- **L-R1026S9-2 [Low, env] — OPEN (не регресс S9).** На глобальном `py -3` (aiogram 3.29.1) 5 пред-существующих падений rich-media (воспроизводимы на base). `.venv` (3.31.0) — 0. Non-blocking.
- **L-R1026S9-6 [Low, shared state] — OPEN (non-blocking).** dry-run пишет `SummaryGenerator._filter_metrics[chat_id]`; живых читателей нет.
- **L-R1026S9-7 [Low, API] — OPEN (non-blocking).** `window_hours` клампится (1..720) вместо 422; spec §5.2 vs §4.2.
- **L-R1026S9-8 [Low, R17] — OPEN (non-blocking, к S7).** `exc_info=True` в catch-all `_execute`/чтении окна.
- **I-R1026S9-1 / I-R1026S9-2 — Info (без изменений).**

---

## 3. Новые находки (итерация 2)

### S-R1026S9-5 — [Low, contract/docs] Остаточный `503` в docstring сервиса и ADR

- **Локация:** `services/summary_test_run.py:489` — docstring `run_summary_test`: «нет генератора → `status="error"`, код `TEST_NO_GENERATOR` **(API → 503)**»; `plans/features/summary-testing-ui-round1026/adr-1026-8-…md` (D4, раздел API) — перечень кодов включает `503 (TEST_NO_GENERATOR)`.
- **Суть:** rework привёл к факту **spec §5.2 и README**, но docstring изменённого файла и ADR сохранили прежнюю формулировку `503`. Фактическая реализация (`web/api/summary_test.py`): `POST /run` всегда `202`, ошибка отсутствия генератора приходит при polling как `200` + `status="error"`/`TEST_NO_GENERATOR`.
- **Доказательство (моя проба):** `run_summary_test(generator=None)` → `present_result.status == "error"`, `diagnostics[0].code == TEST_NO_GENERATOR`; API-тест `test_run_no_generator_still_polls_error` фиксирует `202`+poll.
- **Влияние:** только документация/комментарий; поведение и безопасность корректны (fail-closed, диагностика видна).
- **Fix:** убрать `(API → 503)` из docstring; в ADR-1026-8 D4 заменить `503 (TEST_NO_GENERATOR)` на `200`+`status="error"` (паритет со spec §5.2). **Статус:** OPEN (non-blocking, owned follow-up).

**Новых Critical/High нет.** Low-фиксы регрессий не дали (пробы retention + fail-open выше; полный pytest 8854/0).

---

## 4. Инварианты (итерация 2 — подтверждено)

- **0 публикаций / 0 памяти / 0 `generate_image` (dry-run):** свой шпион-прогон — все точки 0, `await_count==2`, флаг до==после, hybrid не вызван.
- **Живой путь вне изменений (кроме additive):** `summary_generator.py` = **55+/0−** (только `build_test_rows`).
- **Вне diff:** `routes.py`/`image_generation.py`/`telegram_send.py`/`param_catalog.py`/`database.py`/`pg_db.py` — пусто (`git status`).
- **Δ DDL=0** (SQL/DB вне diff); **Δ каталога=0** (469/426/444/100/98/21); `APP_VERSION` **2.58.25**; флаг default ON, OFF → 404 + скрытие секции.
- **UI-guards:** error/частичный payload безопасен; успешный полный payload guards **пропускают** (не скрывают).
- **R18:** annotated-тег `pre-round1026-s9` → `cc6105c`; `git diff --check`=0.

---

## 5. Изменённые файлы (дерево относительно `cc6105c`)

**Новые:** `services/summary_test_run.py`, `web/api/summary_test.py`, `tests/test_summary_test_run.py`, `tests/test_summary_test_api.py`, `tests/js/round1026_s9_testing_test.js`, `plans/features/summary-testing-ui-round1026/*`.
**Изменённые (код/UI):** `services/summary_generator.py` (55+/0− аддитивно), `services/web_runtime.py`, `bot.py`, `web/app.py`, `web/app.js`, `web/index.html`, `config/settings.py` (флаг + bump), `README.md`, `.env.example`, `plans/docs/param-registry-round1025.meta.md` (bump).

---

## 6. Handoff (итерация 2)

`RESULT: SCANNED — к деплою ДА @Orchestrator` — блокирующих нет (**C0/H0/блокирующих Medium 0**). Прежние `B-R1026S9-1` и `B-R1026S9-2`/`S-R1026S9-1` закрыты и подтверждены; Low-фиксы (retention running, fail-open, guards, «Процент отсева», spec/README) — без регрессий. Owned follow-up (non-blocking): **S-R1026S9-5** (503-doc-drift), L-R1026S9-2 (env), L-R1026S9-6/-7/-8, I-R1026S9-1/-2. Живой ON-путь (S6/S10) — GATED; live-приёмка владельца — PENDING OWNER VERIFICATION (вне скоупа @Scanner).

---

# Приложение — Итерация 1 (историческая запись, 23.09.2026)

- **Diff base:** HEAD `cc6105c`. **Вердикт:** **НЕ к деплою** — 2 блокирующих: `B-R1026S9-1` (@Reviewer, §112 «Процент отсева») + `S-R1026S9-1` (@Scanner, UI-краш error-результатов, эскалирован @Reviewer в `B-R1026S9-2 High`). C0 / H0 / M2 / L3 / I2.
- **ID-карта:** `S-R1026S9-1` == `M-R1026S9-1 @Scanner` (→ `B-R1026S9-2 High`); `S-R1026S9-2` == `L-R1026S9-1 @Scanner` == `L-R1026S9-3 @Reviewer`; `S-R1026S9-3` == `L-R1026S9-2 @Scanner` == `L-R1026S9-4 @Reviewer`; `S-R1026S9-4` == `L-R1026S9-3 @Scanner` == `L-R1026S9-5 @Reviewer`; `I-R1026S9-2` == `L-R1026S9-8 @Reviewer`.
- **Прогон:** pytest `.venv` **8847/0** (119.8 s); JS 44/44; шпион-прогон 0/0/0; каталог 469/426/444/100/98/21; `APP_VERSION` 2.58.25; R18 `cc6105c`; `git diff --check`=0.
- **Находки:** `B-R1026S9-1` (Medium, requirement gap) — `drop_percent` отдаётся API, но не рендерится. `S-R1026S9-1` (Medium→High, UI-render) — `web/index.html:490/:511` без guard; error-пути дают `metrics={}`/`artifacts={}` или payload без них → TypeError в render Vue. `S-R1026S9-2` (Low, robustness) — `_purge`/эвикция выбрасывают running. `S-R1026S9-3` (Low, contract/docs) — `503`/«0 `generate_image`». `S-R1026S9-4` (Low, metrics) — stale `_filter_metrics` при fail-open. Info: `I-R1026S9-1` (`has_more` — эвристика), `I-R1026S9-2` (`exc_info=True`).
- **Handoff:** `RESULT: NOT READY @Orchestrator` → возврат в @Builder.
