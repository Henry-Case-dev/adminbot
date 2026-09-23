# Review — S9 `summary-testing-ui-round1026` (Эпик 2, шаг «Тестирование из Mini App», §113)

- **Feature-ID:** `summary-testing-ui-round1026`
- **Status:** **Approved** (итерация 2, T-3373 re-review) — оба прежних блокера закрыты и подтверждены независимо; Critical/High/обязательных Medium не осталось.
- **Ревьюер:** Step 5 @Reviewer (T-3373), 23.09.2026, итерация 2. Единый гейт: требования/корректность + focused change audit.
- **Скоуп:** §113 + §112 (+§106/§114/§46), ADR-1026-8 D1–D8, tasks.md T-3345…T-3379; закрытие rework T-3375.

## Git base and inspected change scope

- **База:** HEAD == `cc6105c`; annotated-тег `pre-round1026-s9` (объект `9f4305a`) → deref-commit **`cc6105c`** (`git cat-file -p` + `git rev-parse "pre-round1026-s9^{commit}"` — R18 ✅).
- **Правки не закоммичены:** `git status` = 33 modified + 5 untracked (новые `services/summary_test_run.py`, `web/api/summary_test.py`, `tests/test_summary_test_run.py`, `tests/test_summary_test_api.py`, `tests/js/round1026_s9_testing_test.js`).
- **Осмотренный дифф:** `summary_test_run.py` (716 стр.), `summary_test.py` (408 стр.), `summary_generator.py` (**55+/0−**, additive `build_test_rows` + reset), `web/app.js` (+148), `web/index.html` (+135), `config/settings.py`, `bot.py`, `web/app.py`, `web_runtime.py`, README/.env.example, пины версий, тесты.

## Checks performed (воспроизведено @Reviewer)

| Проверка | Результат |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **8854 passed / 0 failed** (116.6 s) ✅ |
| JS: `node --check web/app.js` + 44 файла `tests/js/*.js` | **44/44 OK**, exit 0 ✅ |
| Каталог импортом | **469/426/444/100/98/21** (CATEGORIZED=444 из теста `test_catalog_zero_delta`) ✅ |
| `APP_VERSION` | **2.58.25** ✅ |
| `SUMMARY_TEST_UI_ENABLED` | default **True**; ∉ REGISTRY/полей Settings ✅ |
| `git diff --check` | exit 0 (только LF/CRLF-предупреждения) ✅ |
| `summary_generator.py` | **55+/0−** (additive, 0 удалений) ✅ |
| Δ DDL=0 | `database.py`/`pg_db.py`/`param_catalog.py`/`routes.py` — вне diff ✅ |
| R18 | тег → `cc6105c` ✅ |
| Маркер-тесты | в изменённых тестах — только bump `2.58.24→2.58.25` + аддитивные блоки (ассерты не ослаблены) ✅ |

## Requirement / evidence coverage

- **B-R1026S9-2 (High, UI-краш error-путей) — ЗАКРЫТ.** `_base_result` всегда отдаёт `_empty_metrics/_empty_artifacts/_empty_display`; `present_result` нормализует (merge с пустыми); `error_result` (диагностика + полные структуры) + `empty_payload`; API `_result_payload` при `entry.result is None` → `empty_payload`, `_execute` catch-all → `error_result` (`TEST_RUN_FAILED`); `index.html` guard `v-if="summaryTestMetrics"/"summaryTestArtifacts"`; `app.js` computed-guard → `null` на неполном payload. Диагностика рендерится отдельным блоком (`v-if="...diagnostics.length"`) — ошибки не маскируются. Тесты: `test_no_generator_error_payload_contract`, `test_error_result_has_diagnostics_and_full_structures`, `test_empty_payload_running_contract`, `test_run_no_generator_still_polls_error` (расширен), `test_execute_exception_payload_contract`, JS-блок (g). ✅
- **B-R1026S9-1 (Medium, §112 «Процент отсева») — ЗАКРЫТ.** `index.html:491` `data-summary-test-drop` «Процент отсева»; `app.js` computed `summaryTestDropPercent` (`null`/`undefined`/`''` → «Нет данных»); JS-блок (h) — null→«Нет данных», 12.5→«12.5%». ✅
- **L-R1026S9-1 (tag docs) — ЗАКРЫТ** (`evidence.md`/`tasks.md` → `cc6105c`). **L-R1026S9-3 (running не эвиктится) — ЗАКРЫТ**: `_purge` + эвикция исключают `status=="running"`; тесты `test_store_ttl_keeps_running`, `test_store_eviction_keeps_running`. **L-R1026S9-4 (контракт/docs) — ЗАКРЫТ**: spec §5.2 (503 убран, 202/200+error), §7 `TEST_RUN_FAILED`, README «кроме отдельного подтверждения обложки». **L-R1026S9-5 (stale `_filter_metrics`) — ЗАКРЫТ**: reset слота в `build_test_rows` (аддитивно) + тест. ✅
- **0/0/0 dry-run:** модуль `summary_test_run.py` физически не импортирует `telegram_send`/`summary_memory`/`image_generation`; предпросмотр — локальный `format_rich_html/format_plain_html`; шпион-тесты + `await_count==2` (SC-12) зелёные. ✅
- **Живой путь байт-в-байт:** `_run`/`_run_hybrid_l2` — 0 удалённых строк; reset внутри `build_test_rows` (test-only). ✅
- **ON per-run 2 вызова; флаг не читается/не пишется; S6 GATED; Δ DDL=0; Δ каталога=0; R17/R18; bump; права (global admin, 401/403/404/409/422/429).** ✅

## Focused audit coverage

- Error-пути (no-generator, ошибка окна, исключение `_execute`) → контракт-валидный payload + видимая диагностика; guard’ы структурные, статус не скрывают. ✅
- Store: TTL/эвикция не выбрасывают running; `MAX_CONCURRENT`/409/429 не ослаблены. ✅
- XSS: `rich_preview/plain_preview` через `v-html`, но форматтер экранирует (`html.escape`). ✅
- `_flag_guard` до auth (OFF→404); `chat_id` валидируется; `routes.py` вне diff. ✅
- Логи `SUMMARY_TEST_*` — числа/коды/id/host (R17). ✅

## Blocking findings

**Нет.** Оба прежних блокера (B-R1026S9-2 High, B-R1026S9-1 Medium) закрыты и подтверждены кодом/тестами/прогоном.

## Non-blocking debt (OPEN, не блокирует релиз)

- **[L-R1026S9-2]** 5 пред-существующих падений rich-media на глобальном `py -3` (aiogram 3.29.1); воспроизведены на base `cc6105c` — не регресс S9; `.venv` (3.31.0) — 0.
- **[L-R1026S9-6]** dry-run пишет `SummaryGenerator._filter_metrics[chat_id]`; живых читателей нет.
- **[L-R1026S9-7]** `window_hours` клампится (1..720) вместо 422 — spec §5.2 vs §4.2; поведение безопасно.
- **[L-R1026S9-8]** catch-all `exc_info=True` в `_execute`/чтении окна — пересмотреть с S7.
- **Info [I-R1026S9-1]** `present_result.has_more` — эвристика (сумма list-артефактов).

## Unavailable checks

- **Live-приёмка владельца** (Эпик 1 / S1–S5 / S9) — PENDING OWNER VERIFICATION.
- **Реальная генерация обложки** — не выполнялась (мок); проверены `not_generated`/`COVER_GENERATION_FAILED`.
- **Живой ON-путь в проде** — GATED (default OFF; гейт S6/S10 + D4).

## Verdict

**Approved** — итерация 2: оба блокера закрыты фактически и подтверждены независимым прогоном (`pytest` 8854/0, JS 44/44, каталог 469/426/444/100/98/21, Δ DDL=0, `summary_generator.py` 55+/0−, `APP_VERSION` 2.58.25, R18 `cc6105c`). Остаток — non-blocking Low/Info (owned follow-up). Код @Reviewer не менял. К деплою — ДА (после независимого @Scanner T-3374 и live-приёмки владельца).
