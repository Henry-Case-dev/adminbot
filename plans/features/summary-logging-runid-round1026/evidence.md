# S7 `summary-logging-runid-round1026` — evidence (Step 4 @Builder, 24.09.2026)

> **Статус:** блоки **B–F** реализованы и проверены (T-3383…T-3401 ✅). **Rework T-3405 по ревью T-3403 (24.09.2026): B-R1026S7-1 ✅, L-R1026S7-2 ✅; L-R1026S7-1 — follow-up S8/хотфикс.** **Rework 2 (24.09.2026): B-R1026S7-2 ✅ (Medium, блокер), L-R1026S7-3 ✅ (Low, попутно).** Deploy/merge **не выполнялись** (T-3408/T-3406 — вне Step 4/5). Публикационные события `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` **не реализованы (GATED, D4/S6)**. Live-приёмка владельцем — **PENDING**.

## 1. Baseline (точка отката, T-3380 — подтверждено фактически)

| Параметр | Значение |
|---|---|
| HEAD / `origin/master` | `f774ecc6af823c4191dd5f833fa2cce1d0a5bad2` (closing-docs S9; == HEAD) |
| Annotated-тег | `pre-round1026-s7` → `f774ecc` (tag-object `bd7c822`) |
| Откат | `git revert` / вернуться на `pre-round1026-s7`; бэкап `var/backups/s7-round1026-20260924-003537/`; `.env.bak.round1026-s7` (R18: не удалять) |
| `APP_VERSION` на baseline | 2.58.25 |
| pytest `.venv` (заявлено T-3380) | 8854/0 — Builder'ом **не перемерялось**; после изменений — **8887/0** |
| JS (заявлено T-3380) | 44/44 — после изменений **45/45** |
| Каталог | 469/426/444/100/98/21 (перемерено после изменений — без дельты) |
| Δ DDL | 0 (SQLite v12; `db/`, миграции — вне diff) |

**Замечание к спеке:** `spec.md`/`tasks.md` ожидали baseline HEAD `59e5b12`, фактически тег стоит на `f774ecc` — на один **docs-only** коммит позже (closing-docs S9 `59e5b12`→`f774ecc`). Код/версия/тесты идентичны; расхождение — только документационное.

## 2. Состояние после обрыва (что было найдено) и что доделано

Найдено (не переписывалось):
* `services/summary_run_log.py` — `RunContext`/`provider_host`/`http_status_of`/`attempts_of`/`log_summary_*`/`finish_run` — корректны, **дополнены** helper-ами `log_format_start/complete/error`, `log_cover_start/complete/error` + best-effort защита всех лог-функций.
* `services/summary_generator.py` — врезка `_run`/`_run_hybrid_l2`/`_deliver_rich` — корректна, но **не завершена**: отсутствовал импорт `provider_host` (латентный `NameError` при ON-пути) и не изменены `_deliver_l2_plain`/`_deliver_l2_rich` (вызовы с `ctx=`/`correlation_id` уже были).

Доделано (D1–D8):
1. **D1:** `run_id` = `correlation_id` (`usage_events.new_correlation_id()`, UUID4 hex); ровно одна точка на прогон — `summary_generator._run:364` (живой) и `summary_test_run.run_summary_test:495` (dry-run); второй id не введён; проброс параметром через `_apply_filter → _restore → _run_hybrid_l2 → run_l1 → build_fact_package → run_l2 → _deliver_l2_*`; тот же id уходит в `llm.generate(..., correlation_id=)` (учёт `llm_usage_events`).
2. **D2:** добавлены `SUMMARY_START/COMPLETE/FAILED`, `FORMAT_START/COMPLETE` (+`run_id`/`reason` в существующий `FORMAT_ERROR`), `COVER_START/COMPLETE/ERROR`; `FILTER_*`/`RESTORE_*`/`L1_*`/`L2_*`/`TEST_*` переиспользованы; поля — spec §5; аддитивно, R17-safe (числа/коды/id/host/HTTP-статус/тип/причина/попытки). `L1_ERROR`/`L2_ERROR` дополнены `http_status`/`attempts` (SC-07). `PUBLISH_*` — **отсутствуют**.
3. **D3:** Δ DDL=0; события — ring-buffer + файловые логи (retention не менялся); токены/стоимость — существующая `llm_usage_events` по `run_id`; сбор контекста — `RunContext` (in-memory) + существующие `_filter_metrics`.
4. **D4 (§110):** клиентский чип «Саммари» в существующем viewer (`web/app.js`: `logSummaryOnly`/`logSummaryMarkers`/`isSummaryLog`/`summaryErrorLabel`/`toggleLogSummary`/computed `shownLogs`; `web/index.html` — кнопка/разметка; `web/static/app.css` — стиль активного чипа). Без нового endpoint и без diff `web/api/routes.py`; раскрытие (`expanded`) и копирование (`copyLogRow`/`logText`) сохранены; ON → `logLevel='INFO'`, OFF → прежний уровень.
5. **D5:** dry-run S9 — 0/0/0 сохранены, тот же `run_id`, `TEST_*` + этапные `L1_*`/`L2_*`/`FORMAT_*`; `SUMMARY_*`/`PUBLISH_*`/`COVER_*` не эмитятся; второй контур логирования не создан.
6. **D6:** `*_ERROR` у каждого этапа + `SUMMARY_FAILED` (вместо `SUMMARY_COMPLETE`); `provider` — host; лог-стор best-effort (сбой логирования не рвёт пайплайн); голая «Ошибка Саммари» отсутствует.
7. **D7:** Δ DDL=0; Δ каталога=0 (F8 **не переиздаётся** — обновлена только провенанс-строка `APP_VERSION` в `plans/docs/param-registry-round1025.meta.md`; TSV/реестр не тронуты); CSP/zero-build; 0 новых зависимостей; 2-вызовность (`await_count==2`); §104/обложка/XML/`image_generation.py`/`telegram_send.py` — вне diff; R17/R18; OFF-путь по артефактам/поведению неизменен (аддитивные лог-строки — по §108).
8. **D8:** `APP_VERSION` 2.58.25 → **2.58.26** + README (`v2.58.26`) + cache-bust (`?v=__APP_VERSION__` — существующий механизм) + атомарные пины версии в тестах/JS.
9. **T-3400 (follow-up S9):** `L-R1026S9-8` — `exc_info=True` в `web/api/summary_test.py` (`_execute`, cover) и `services/summary_test_run.py` (чтение окна) заменён на R17-safe `error_type=<класс>` без traceback; `I-R1026S9-1/-2` (`has_more` — эвристика) не трогались (касания не было, остаётся Info-follow-up); регресс `S-R1026S9-5` не подтверждён (тесты S9 зелёные).

## 3. Изменённые/новые файлы (unstaged worktree; staged — нет)

**Новые:**
* `services/summary_run_log.py` — D1/D2/D6: `RunContext`, `provider_host`, `http_status_of`, `attempts_of`, логгеры жизненного цикла/этапов (best-effort).
* `tests/test_summary_logging_runid.py` — **32 теста** (SC-01…SC-16).
* `tests/js/round1026_s7_log_summary_filter_test.js` — поведенческий JS-тест §110.
* `plans/features/summary-logging-runid-round1026/` — spec/ADR/tasks (Step 1/2; не Builder).

**Изменённые (код/UI):**
* `services/summary_generator.py` — `_run` (SUMMARY_START/COMPLETE/FAILED, `saved_count/restored_count` из метрик прогона), `_run_hybrid_l2` (ctx/degraded/failed), `_deliver_l2_plain/_deliver_l2_rich` (FORMAT/COVER, сигнатуры), `_deliver_rich` (COVER_*), импорт `provider_host`.
* `services/summary_l1_clusterizer.py`, `services/summary_l2_writer.py` — `L1_ERROR`/`L2_ERROR`: +`http_status`/`attempts` (SC-07).
* `services/summary_test_run.py` — FORMAT_START/COMPLETE в dry-run; window-error без traceback (T-3400).
* `web/api/summary_test.py` — T-3400: `error_type` вместо `exc_info=True` (2 точки).
* `web/app.js`, `web/index.html`, `web/static/app.css` — §110-фильтр.
* `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md` — bump 2.58.26 + провенанс.
* 19 файлов тестов — пины `2.58.25`→`2.58.26` (15 Python + 4 JS) и регистрация нового JS-теста (`tests/test_webapp_js_unit.py`).

**Не Builder (были изменены до Step 4, не трогались):** `plans/MEMORY.md`, `plans/backlog.md`, `plans/workflow_state.md` (PM/Architect docs; для Reviewer — в манифесте).

**Rework T-3405 (24.09.2026):** дополнительно тронуты `services/summary_generator.py` (OFF-путь `_run` — `ctx.model`/`ctx.provider`), `tests/test_summary_logging_runid.py` (пин B-R1026S7-1 + `attempts`), `web/app.js` (OFF-условие `toggleLogSummary`), `tests/js/round1026_s7_log_summary_filter_test.js` (кейс L-R1026S7-2). Новых файлов нет; staged нет.

**Rework 2 (24.09.2026, B-R1026S7-2/L-R1026S7-3):** тронуты `services/summary_run_log.py` (`attempts_of` — R17-safe разбор текста), `services/summary_test_run.py` (`SUMMARY_TEST_FORMAT_ERROR` без `exc_info`), `tests/test_summary_logging_runid.py` (+3 теста, пины на реальные тексты llm_client). Новых файлов нет; staged нет.

**Вне diff (проверено `git diff --name-only`):** `web/api/routes.py`, `services/param_catalog.py`, `services/image_generation.py`, `services/telegram_send.py`, `db/**`.

## 4. Прогоны и фактические результаты

| Команда | Результат |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **8887 passed**, 0 failed, 1 warning (117.14s) |
| `node tests/js/*.js` (все 45 файлов) | **45/45 OK** (вкл. новый `round1026_s7_log_summary_filter_test.js`) |
| `.venv\Scripts\python.exe -m pytest tests/test_summary_logging_runid.py -q` | **32 passed** |
| `node --check web/app.js`; `node --check tests/js/round1026_s7_log_summary_filter_test.js` | OK |
| `git diff --check` | чисто (0 whitespace-ошибок) |
| Импорт каталога | `APP_VERSION 2.58.26`; **469/426/444/100/98/21** |
| `git status --porcelain` | 34 modified + 4 untracked (см. §3); staged нет |
| Δ DDL | 0 (нет изменений `db/**`, миграций, SQLite v12) |
| **Rework T-3405 (24.09.2026)** | повторные прогоны — **§7**: 32/32 (S7-файл), **8887/0** (полный), JS **45/45**, `node --check` OK, `git diff --check` чисто, каталог 469/426/444/100/98/21, `APP_VERSION` 2.58.26 (без нового bump) |
| **Rework 2 (24.09.2026, B-R1026S7-2)** | S7-файл — **35/35** (+3 пина на реальные тексты); полный pytest `.venv` — **8890 passed / 0 failed** (1 warning, 119.64s); JS — **45/45**; `node --check` OK; `git diff --check` чисто; каталог 469/426/444/100/98/21; `APP_VERSION` 2.58.26 (без нового bump) — детали **§8** |

## 5. Покрытие SC (тесты)

| SC | Где покрыто |
|---|---|
| SC-01 | `test_single_run_id_all_events` (все строки несут один `_RID`); `test_hybrid_events_same_run_id` |
| SC-02 | `test_single_run_id_all_events` (ok), `test_empty_window_complete_empty`, `test_hybrid_l1_not_usable_degraded`/`test_hybrid_l2_error_degraded`, `test_db_failure_summary_failed`/`test_llm_failure_summary_failed_http`/`test_hybrid_package_raise_summary_failed` |
| SC-03 | `test_single_run_id_all_events` (FILTER_START/COMPLETE, `event=FILTER_*`); поля — существующие S1-тесты |
| SC-04/SC-05 | `test_hybrid_events_same_run_id` (L1/L2 + токены/темы/абзацы); `TestStageErrorDetails` |
| SC-06 | `test_cover_complete_ok_and_format_rich`, `test_cover_unavailable_falls_back_to_plain`, `test_cover_error_on_exception`, `test_format_error_has_run_id_and_reason`, `test_legacy_rich_cover_events`; 0 LLM — L2-счётчики |
| SC-07 | `TestStageErrorDetails` (http_status/attempts: атрибут + **реальные тексты llm_client** — L1/L2), `SUMMARY_FAILED`-тесты (OFF-путь на реальном `LLMRateLimitError` без атрибута), отсутствие голой строки (reason=класс) |
| SC-08 | `test_r17_no_secret_in_events`, `test_fail_from_exc_r17_fields`, `test_dry_run_window_failure_r17_no_traceback` |
| SC-09/SC-10 | `round1026_s7_log_summary_filter_test.js` (маркеры/`shownLogs`/формулировки/toggle/раскрытие/копирование) |
| SC-11 | `gen.llm.correlation_ids == [_RID,_RID]`; `call.kwargs["correlation_id"] == _RID` |
| SC-12 | `TestInvariants` (каталог 469/426/444/100/98/21; запрещённые модули) + §4 |
| SC-13 | 2-вызовность (OFF/hybrid), доставленный текст, `test_forbidden_modules_untouched` |
| SC-14 | `TestDryRunContour` (0/0/0, `TEST_*`-контур, без `SUMMARY_*`/`PUBLISH_*`/`COVER_*`) |
| SC-15 | `test_publish_events_absent_gated` + `caplog`-проверки |
| SC-16 | `test_app_version_bumped` + пины README/JS/тестов (deploy — T-3408, не выполнен) |

## 6. Ограничения / не выполнялось

* Deploy, merge, архивация — не выполнялись (вне Step 4).
* Live-приёмка S1–S5/S9/Эпика 1 — PENDING OWNER VERIFICATION (без изменений).
* Baseline pytest 8854/0 и JS 44/44 — заявлены T-3380, Builder'ом не перемерялись (см. §1).
* `I-R1026S9-1/-2` (`has_more` — эвристика) — не трогались; остаются Info-follow-up.
* Baseline-тег стоит на `f774ecc` вместо ожидаемого `59e5b12` (docs-only разница, §1).

## 7. Rework T-3405 по ревью T-3403 (24.09.2026)

| ID | Статус | Правка / доказательство |
|---|---|---|
| **B-R1026S7-1** (Medium, блокер) | ✅ закрыт | `services/summary_generator.py` — в `_run` сразу после `RunContext(...)` заполняются `ctx.model`/`ctx.provider` (host, R17-safe) для **OFF-пути (default)**; доступ best-effort (`getattr(self, "llm", None)`) — legacy-тесты с `object.__new__(SummaryGenerator)` не падают. ON-ветка сохраняет идемпотентное заполнение. Пин — `test_llm_failure_summary_failed_http`: `model=model-x`, `provider=api.example.com`, `stage=run`, `http_status=429`, `error_type=LLMError`, `attempts=3`, ключ не течёт. |
| **L-R1026S7-2** (Low, UX) | ✅ закрыт | `web/app.js` `toggleLogSummary`: OFF возвращает «до-чиповый» уровень, **только если уровень не меняли вручную** при активном чипе (`logLevel === 'INFO'`); ручной выбор сохраняется. Поведенческий кейс добавлен в `tests/js/round1026_s7_log_summary_filter_test.js` (секция 4). |
| **L-R1026S7-1** (Low, вне diff) | ⏭ follow-up | `FILTER_ERROR` с `exc_info=True` (`summary_generator.py`, baseline S1) — в S7 **не тронут** (вне диффа; R17-хардненинг аналогично T-3400) → S8/хотфикс (отмечено в `tasks.md`). |
| **I-R1026S7-2** (Info) | ✅ | `tasks.md` T-3402 отмечен выполненным (границы: `PUBLISH_*` отсутствуют/S6 GATED; S8/S9-контуры не созданы). |

**Проба OFF-пути (репро находки, `--log-cli-level=INFO`):**
`SUMMARY_FAILED | run_id=RID-S7-0001 | chat_id=-1001 | stage=run | model=model-x | provider=api.example.com | http_status=429 | error_type=LLMError | reason=LLMError | attempts=3 | duration_ms=1` — `stage=run` корректен для OFF-этапа генерации; `http_status`/`error_type`/`attempts` сохранены.

**Прогоны rework:** `pytest tests/test_summary_logging_runid.py` — **32/32**; полный pytest `.venv` — **8887 passed / 0 failed** (1 warning, 116.50s); JS **45/45 OK**; `node --check web/app.js` и JS-теста — OK; `git diff --check` — чисто; каталог импортом — 469/426/444/100/98/21 (Δ=0); `APP_VERSION` 2.58.26 (нового bump нет); `git diff --name-only f774ecc` — `db/**`, `routes.py`, `param_catalog.py`, `image_generation.py`, `telegram_send.py`, `summary_xml.py` отсутствуют (Δ DDL=0, Δ каталога=0, §104/XML/публикация вне diff).

**Промежуточная находка (закрыта):** первый полный прогон после фикса дал 1 failed — legacy `tests/test_token_analytics_round1023.py::...::test_summary_run_creates_single_id` (`object.__new__(SummaryGenerator)` без атрибута `llm`); закрыто best-effort-доступом в `_run`; повторный полный прогон — 8887/0.

**Хэши файлов rework (SHA-256, для манифеста Reviewer):** `services/summary_generator.py` `377B5C61FC42CCF67CFF0A6339951EEF45A3C821E24144842914E2333B74606E`; `tests/test_summary_logging_runid.py` `66CB384FAC5922013AD0D5073068764203694D56477C7E2DF71818C715E0FFAD`; `web/app.js` `6191274E22E99AC46BDF72433CB60D0635BCD76C0DEB75844B6814B3039CBDF8`; `tests/js/round1026_s7_log_summary_filter_test.js` `2DF92F44206A7F8A5231C634C7708EA3BBBE3F8A3EAA49787FEC3A62CD5970FE` (на момент прогонов §7; правки `evidence.md`/`tasks.md` после — документные).

## 8. Rework 2 по ревью T-3403 — B-R1026S7-2 (24.09.2026)

| ID | Статус | Правка / доказательство |
|---|---|---|
| **B-R1026S7-2** (Medium, блокер; SC-07/§109) | ✅ исправлен | `services/summary_run_log.py`: `attempts_of()` — сначала **R17-safe разбор текста** (`_ATTEMPTS_RE`: `after (\d+) attempts?` + `attempts[=:]\d+`), затем fallback на атрибут `exc.attempts`, затем `None`; в лог попадает только число. `http_status_of()` **не менялся** — консистентность подтверждена на реальных текстах. Пины **без искусственного атрибута**: `test_attempts_of_real_llm_texts` (RateLimit→3, Server→3, Timeout→2, без текста→`None`, fallback атрибута, приоритет текста); `test_llm_failure_summary_failed_http` переведён на реальный `LLMRateLimitError("LLM rate limited (429) after 3 attempts: …")` без `exc.attempts` (OFF-путь: `attempts=3`, `http_status=429`, `error_type=LLMRateLimitError`, `reason=LLMRateLimitError`; сырой текст/URL/ключ не текут); `test_l1_error_real_llm_text_attempts` (502/3); `test_l2_error_real_llm_text_attempts` (429/3); `test_http_status_of` дополнен реальными классами. |
| **L-R1026S7-3** (Low, R17; pre-existing, тест-контур) | ✅ исправлен (попутно) | `services/summary_test_run.py`: `SUMMARY_TEST_FORMAT_ERROR` — убран `exc_info=True`, добавлен `error_type=%s` (хардненинг как T-3400); пин `test_dry_run_format_error_test_code`: `error_type=RuntimeError`, `reason=formatter_error`, `rec.exc_info is None`, сырой текст не течёт. |
| **L-R1026S7-1** (Low, pre-existing S1, вне diff) | ⏭ follow-up | `FILTER_ERROR` с `exc_info=True` (`summary_generator.py`, baseline S1) — по-прежнему вне диффа S7 → S8/хотфикс. |

**Проба (реальные тексты llm_client, атрибута нет):** `LLMRateLimitError("…(429) after 3 attempts…")` → `attempts=3`, `http_status=429`; `LLMServerError("…502 after 3 attempts…")` → `3/502`; `LLMTimeoutError("…after 2 attempts…")` → `2/-`; `LLMError("no info")` → `-/-`.

**Проба OFF-пути и этапов (факт, `--log-cli-level=INFO`):**
`SUMMARY_FAILED | run_id=RID-S7-0001 | chat_id=-1001 | stage=run | model=model-x | provider=api.example.com | http_status=429 | error_type=LLMRateLimitError | reason=LLMRateLimitError | attempts=3 | duration_ms=1`;
`L1_ERROR | … | error=LLMServerError | reason=llm_error | http_status=502 | attempts=3`;
`L2_ERROR | … | error=LLMRateLimitError | reason=llm_error | http_status=429 | attempts=3`.

**Прогоны rework 2:** `pytest tests/test_summary_logging_runid.py` — **35/35**; полный pytest `.venv` — **8890 passed / 0 failed** (1 warning, 119.64s); JS — **45/45 OK**; `node --check web/app.js` и S7-JS — OK; `git diff --check` — чисто; каталог импортом — 469/426/444/100/98/21 (Δ=0); `APP_VERSION` 2.58.26 (нового bump нет); `git diff --name-only f774ecc -- db services/param_catalog.py web/api/routes.py services/image_generation.py services/telegram_send.py services/summary_xml.py services/summary_article_formatter.py` — **пусто** (Δ DDL=0, Δ каталога=0, §104/XML/публикация вне diff); 2-вызовность не тронута (S7-файл: `await_count==2`).

**Хэши файлов rework 2 (SHA-256, для манифеста Reviewer):** `services/summary_run_log.py` `B2B980245E3562CDB557F2E4A7E2AC65D21C33F2DAC9DC8A1116BA52CA48A506`; `services/summary_test_run.py` `84C0089E44C99A67FBB77400F375EE780AFEFBCB445910AA00D3EC88FD9E4413`; `tests/test_summary_logging_runid.py` `A13DC956FF5500879F4FEDDA68CD2757B14A1CC63F0038400CD6CEB092EF6C1D` (хэш S7-теста из §7 — устарел; правки `evidence.md`/`tasks.md` после хэширования — документные).
