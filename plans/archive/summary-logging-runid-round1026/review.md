# S7 `summary-logging-runid-round1026` — review (T-3403, Step 5 @Reviewer, **ИТЕРАЦИЯ 3 — rework 2: B-R1026S7-2**)

- **Feature-ID:** `summary-logging-runid-round1026` (Эпик 2, §108–§110; T-3380…T-3409)
- **Risk-Level:** R2
- **Status:** **Approved** — Critical/High/Medium блокеров = 0. B-R1026S7-2 (Medium, итерация 2) — **CLOSED (воспроизведено)**; B-R1026S7-1/L-R1026S7-2 (итерация 1) и L-R1026S7-3 — закрыты.
- **АКТУАЛЬНЫЙ binding (T-3404, 24.09.2026):** Status **Approved** (единый gate: линза 1 — итер.3, линза 2 — focused change audit + миграция); **Reviewed-Commit** `f774ecc6af823c4191dd5f833fa2cce1d0a5bad2`; **Working-Tree-Hash** `6c7c90618755f82665361b3060bf1e568f107799e780a6cea4f092f274026891`; **Spec-Hash** `d9d11797fbc1e290825a53053ac90d7a49b16af324375305506cae54b74a9ac0` — детали в разделе «Единый gate T-3404 (линза 2 + миграция)». Bindings итер.3 (ниже) — исторические; Working-Tree-Hash `0c9cc82e…` устарел (миграция `tasks.md`).
- **Reviewed-Commit:** `f774ecc6af823c4191dd5f833fa2cce1d0a5bad2` (HEAD; == `origin/master`; annotated-тег `pre-round1026-s7` (tag-obj `bd7c822`) → `f774ecc`; правки feature — в worktree, не закоммичены)
- **Working-Tree-Hash:** `0c9cc82e856e0cdc902e0a46f4c5467a91e41e9e9dc2873a4be7387f093a46d2`
  - Рецепт: SHA-256 манифеста (UTF-8, LF) = строка `git-diff f774ecc sha256=3e8f523a3aa7c72fae249df162339ae2b5ffc3b23bb9e656de4f786cc122ad11` (SHA-256 сырых байт `git diff f774ecc` на момент фиксации) + по строке `<путь> sha256=<hash>` для каждого untracked-файла (сортировка, POSIX-пути), **кроме** `plans/features/summary-logging-runid-round1026/review.md` (сам отчёт; рецепт совпадает с итерацией 2): `plans/features/.../{adr=dabb88e2…, evidence=c36e61dd…, spec=d9d11797…, tasks=cb0d5f7e…}`, `services/summary_run_log.py=b2b98024…`, `tests/js/round1026_s7_log_summary_filter_test.js=2df92f44…`, `tests/test_summary_logging_runid.py=a13dc956…`.
  - Хэши Builder'а rework 2 подтверждены байт-в-байт: `summary_run_log.py` `B2B98024…`, `summary_test_run.py` `84C0089E…`, `test_summary_logging_runid.py` `A13DC956…`. Запись в `plans/reports/full_audit_results.md` сделана **до** хэширования и входит в diff-SHA; `review.md` — вне манифеста (артефакт ревью).
- **Spec-Hash:** `d9d11797fbc1e290825a53053ac90d7a49b16af324375305506cae54b74a9ac0` (не менялась с итерации 1)
- **Git base и scope:** база `f774ecc`; 35 modified + 4 untracked. Код: `services/summary_generator.py`, `summary_l1_clusterizer.py`, `summary_l2_writer.py`, `summary_test_run.py`, `web/app.js`, `web/index.html`, `web/static/app.css`, `web/api/summary_test.py`, `config/settings.py`, `README.md`, 20 test-файлов (пины версии + регистрация JS-теста), `plans/**`. **Вне diff (подтверждено пустым `git diff --name-only f774ecc`):** `web/api/routes.py`, `services/param_catalog.py`, `services/image_generation.py`, `services/telegram_send.py`, `services/summary_xml.py`, `services/summary_article_formatter.py`, `db/**`.

## История итераций

- **Итерация 1:** Changes requested — B-R1026S7-1 (OFF-путь `SUMMARY_FAILED` без model/provider). Rework T-3405: `ctx.model`/`ctx.provider` в `_run` (best-effort) + JS-кейс L-R1026S7-2. Закрыты.
- **Итерация 2:** Changes requested — B-R1026S7-2 (Medium): `attempts_of()` читал только `exc.attempts`, реальные исключения `llm_client` его не выставляют → «Количество попыток» (§109) не выводилось; пин был зелёным за счёт искусственного атрибута (ложное подтверждение SC-07).
- **Итерация 3 (текущая):** rework 2 — `attempts_of()` (текст → атрибут → `None`) + пины на реальные тексты + попутно L-R1026S7-3 (`SUMMARY_TEST_FORMAT_ERROR` без `exc_info`). **Approved.**

## Проверки (воспроизведено @Reviewer независимо, 24.09.2026)

| Проверка | Результат |
|---|---|
| `py -3 -m pytest -q` (`.venv`, `-p no:cacheprovider --timeout=120`) | **8890 passed / 0 failed** (115.51 s), 1 warning |
| `pytest tests/test_summary_logging_runid.py` | **35 passed** (было 32; +3) |
| `node tests/js/*.js` (45 файлов) | **45/45 OK** |
| `git diff --check` | чисто (0) |
| Импорт каталога | `APP_VERSION` **2.58.26**; **469/426/444/100/98/21** (Δ=0) |
| Δ DDL | **0** (`db/**` вне diff, untracked в `db/` нет) |
| R18 | тег `pre-round1026-s7` (tag `bd7c822`) → `f774ecc` ✓; `var/backups/s7-round1026-20260924-003537/` ✓; `.env.bak.round1026-s7` ✓; `stash@{0}` не тронут ✓ |
| `PUBLISH_*` | в коде отсутствуют (grep по 7 файлам — 0; тест `test_publish_events_absent_gated`) |
| Маркер-тесты | не ослаблены: в diff tests — только пины `2.58.25→2.58.26` и регистрация нового JS-теста |
| 2-вызовность | `await_count==2` (OFF/hybrid/dry-run) в тестах; полный регресс зелёный |

## Проверка B-R1026S7-2 (репро на реальных текстах, без атрибута)

- Проба @Reviewer (`services.llm_client`, реальные классы, `hasattr(exc,"attempts")=False`): `LLMRateLimitError("…(429) after 3 attempts…")` → `attempts=3`/`http_status=429`; `LLMServerError("…502 after 3 attempts…")` → `3/502`; `LLMTimeoutError("…after 2 attempts…")` → `2/None`; `LLMTransportError("…after 4 attempts…")` → `4`; `LLMError("no info")` → `None`.
- Fallback атрибута → `4`; **приоритет текста над атрибутом** → `5`; без текста и атрибута → `None`.
- Лог R17-safe: `SUMMARY_FAILED | … | http_status=429 | error_type=LLMRateLimitError | reason=LLMRateLimitError | attempts=3` — сырой текст/URL/ключ не текут (проверено assert'ами).
- Пины: `test_attempts_of_real_llm_texts` (RateLimit→3, Server→3, Timeout→2, без текста→None, fallback, приоритет); `test_llm_failure_summary_failed_http` переведён на реальный `LLMRateLimitError` c `assert not hasattr(exc,"attempts")` → OFF-путь `attempts=3`/`http_status=429`/`error_type=LLMRateLimitError`; `test_l1_error_real_llm_text_attempts` (502/3); `test_l2_error_real_llm_text_attempts` (429/3); `test_http_status_of` дополнен реальными классами. **Ложных подтверждений нет.**
- `http_status_of()` фактически разбирает реальные тексты (`429/502/None`); прямой diff с прежней версией невозможен (файл untracked), но функциональная консистентность подтверждена.
- L-R1026S7-3: `summary_test_run.py` — `SUMMARY_TEST_FORMAT_ERROR | … | error_type=%s | reason=formatter_error` без `exc_info`; пин `test_dry_run_format_error_test_code` (`rec.exc_info is None`).

## Контрпримеры (не только happy path)

- Реальные исключения без атрибута (4 класса) → число попыток извлекается; текст приоритетнее атрибута; пустой случай → `-` (None) ✓.
- `object.__new__(SummaryGenerator)` без `llm` → `_run` не падает (best-effort `getattr`) ✓; legacy round1023 в полном прогоне зелёный.
- Пустое окно → `SUMMARY_COMPLETE status=empty`; сбой БД → `SUMMARY_FAILED stage=db`; сбой лог-стора → текст доставлен ✓.
- `L1_ERROR`/`L2_ERROR` на реальных текстах — 502/3 и 429/3, URL не течёт ✓; `SUMMARY_TEST_FORMAT_ERROR` без traceback ✓.
- OFF-чип/ручной уровень (JS) ✓; `shownLogs` OFF = исходный список, счётчики не тронуты ✓; `PUBLISH_*`/`routes.py`/каталог/DDL вне diff ✓.

## Blocking findings

Нет. B-R1026S7-2 **CLOSED** (репро выше); Critical/High = 0.

## Non-blocking debt (owned follow-up)

- **L-R1026S7-1** (Low, pre-existing S1, вне S7-diff — подтверждено контекстом diff): `FILTER_ERROR` с `exc_info=True` (`summary_generator.py:973-977`) → R17-хардненинг в S8/хотфиксе.
- **I-R1026S7-1** (Info): машинный чекпоинт `plans/workflow_state.md` устарел («build in progress (partial)… evidence.md absent», review pending) → ✅ **закрыт 24.09.2026** (@Orchestrator, миграция управляющих документов — чекпоинт обновлён через `workflow_checkpoint`).

## Недоступные проверки

- Live-приёмка владельца (Telegram/WebView) — **PENDING OWNER VERIFICATION**; deploy T-3408 не выполнялся (вне Step 5).
- Baseline pytest 8854/0 и JS 44/44 на `f774ecc` не перемерялись (worktree занят; дельта +36/+1 согласуется с составом изменений).

## Миграция управляющих документов (24.09.2026, @Orchestrator)

- Scanner удалён из конфигурации workflow **намеренно**; все его обязанности окончательно включены в Reviewer (единый gate: линза 1 — requirements/correctness review; линза 2 — focused change audit). В `tasks.md` T-3404 переведён на @Reviewer (линза 2), статусы обновлены; активных/будущих исполняемых назначений и handoff на Scanner не осталось.
- **Binding итерации 3 стал устаревшим:** `tasks.md` изменён миграцией (Working-Tree-Hash `0c9cc82e…` рассчитан на прежнюю редакцию `tasks.md`). `spec.md` и product code миграцией **не изменялись**; Reviewed-Commit `f774ecc` не менялся.
- **Выполнено (T-3404, 24.09.2026):** целевая проверка миграции + focused change audit (Δ DDL=0, Δ каталога=0/F8 N/A, R17/R18, CSP/zero-build, публикация/§104/XML вне diff, зависимости, утечки/побочные эффекты) и **пересчёт binding** — в разделе «Единый gate T-3404 (линза 2 + миграция)» ниже (Status Approved; актуальные `Reviewed-Commit`/`Working-Tree-Hash`/`Spec-Hash`).

## Единый gate T-3404 (линза 2 — focused change audit + миграция управляющих документов), 24.09.2026

- **Status: Approved** — Critical/High = 0, блокирующих Medium = 0; «к деплою ДА». Отдельного Scanner-approval не существует (Scanner удалён намеренно; его обязанности включены в этот gate и исполнены фактически).
- **Reviewed-Commit:** `f774ecc6af823c4191dd5f833fa2cce1d0a5bad2` (HEAD == `origin/master`; annotated-тег `pre-round1026-s7` — tag-obj `bd7c822` → `f774ecc`; `git for-each-ref`/`cat-file`).
- **Working-Tree-Hash:** `6c7c90618755f82665361b3060bf1e568f107799e780a6cea4f092f274026891`
  - Рецепт (детерминированный): SHA-256 манифеста (UTF-8; строки соединены LF + завершающий LF) = строка `git-diff f774ecc sha256=3556c053f9bf6f2e2ab14506bfed4d2574318b28c7507b35f103ba30b5e335fa` (SHA-256 **сырых байт** stdout `git diff f774ecc`, cmd-редирект) + по строке `<путь> sha256=<hash>` для каждого untracked-файла (сортировка, POSIX-пути), кроме `plans/features/summary-logging-runid-round1026/review.md`; SHA-256 манифеста — значение выше.
  - Per-file (SHA-256, lowercase): adr `dabb88e2070af7827ff0f1a009fb916ea670992c124dae52f0e4c1709cb32411`, evidence `c36e61dd4a28f14e9136e7db9666b67368d60baada125630a68abb14bfe77b18`, spec `d9d11797fbc1e290825a53053ac90d7a49b16af324375305506cae54b74a9ac0`, tasks `e108dc4d248f674cd155cd08fc035aa72e3f8ad987ef6dda025c39b295933d43`, `services/summary_run_log.py` `b2b980245e3562cdb557f2e4a7e2ac65d21c33f2dac9dc8a1116ba52ca48a506`, `tests/js/round1026_s7_log_summary_filter_test.js` `2df92f44206a7f8a5231c634c7708ea3bbbe3f8a3eaa49787fec3a62cd5970fe`, `tests/test_summary_logging_runid.py` `a13dc956ff5500879f4fedda68cd2757b14a1cc63f0038400cd6ceb092ef6c1d`.
  - Запись в `plans/reports/audit_backlog.md` сделана **до** хэширования и входит в diff-SHA (прецедент итер.3 с `full_audit_results.md`); `review.md` — вне манифеста (артефакт ревью).
- **Spec-Hash:** `d9d11797fbc1e290825a53053ac90d7a49b16af324375305506cae54b74a9ac0` — перепроверено хэшем файла (spec миграцией не менялся).

**Requirements/correctness coverage (линза 1 — итерация 3, актуальна):** вердикт и полный набор проверок — выше (итер.3 Approved; B-R1026S7-1/-2, L-R1026S7-3 закрыты). После миграции перепроверено независимо: `spec.md`/`adr`/`evidence.md` — байт-в-байт (хэши совпали с итер.3); `tasks.md` изменён только миграцией (хэш `e108dc4d…` вместо `cb0d5f7e…`; правки — перевод T-3404 на @Reviewer, статусы, заметки); полный pytest **8890/0**; S7-файл **35/35**; JS **45/45**.

**Focused audit coverage (линза 2, пункты 1–8):**
1. **Scanner в исполняемых шагах — нет.** `plans/features/summary-logging-runid-round1026/**` — только исторические/миграционные упоминания (T-3405 ✅ DONE; T-3404 — @Reviewer); `plans/workflow_state.md` — активный указатель S7 без назначений Scanner (упоминания — история прошлых фич + заметка о миграции); `plans/backlog.md` — строки S7/S8/S10 без Scanner (S8/S10 — «Step 1 при старте Эпика 2»); `plans/project.md` — «миграции проверяет @Reviewer»; `plans/MEMORY.md` — активный указатель S7 без handoff. Исторические упоминания сохранены (`plans/reports/**`, `plans/archive/**`, `metrics.md`, исторические разделы, `current_task.md:7195/7220` — ТЗ только чтение).
2. **Обязанности Scanner не потеряны** — включены в T-3404 и фактически исполнены: Δ DDL=0; Δ каталога=0 (F8 N/A); R17/R18; CSP/zero-build; публикация/§104/XML вне diff; 0 новых внешних зависимостей; отсутствие утечек/скрытых побочных эффектов (2-вызовность, dry-run 0/0/0, шпион-тесты); тесты/evidence/release readiness.
3. **Два контура — две линзы одного gate:** T-3403 (линза 1, итер.3 Approved) + T-3404 (линза 2, этот раздел) в `review.md`/`tasks.md`; `plans/reports/round1026_s7_scanner_audit.md` отсутствует.
4. **Согласованность цепочки:** `current_task.md` §108–§110 (verbatim) ↔ REQ-карта/`spec.md` (REQ-S7-01…-13 → SC-01…SC-16) ↔ `tasks.md` (инварианты 1–12, карта ADR D1–D8) ↔ фактический diff (события/поля/§110-фильтр) ↔ тесты/`evidence.md` ↔ deployment-план (D8: deploy=ДА, bump 2.58.25→2.58.26, откат `pre-round1026-s7`→`f774ecc`) — противоречий не найдено; единственное документированное исключение — `PUBLISH_*` **GATED** (S6/D4), зафиксировано в spec/tasks/ADR и подтверждено фактически (в коде отсутствуют).
5. **Архивы не тронуты:** `git status --porcelain -- plans/archive` и `git diff f774ecc -- plans/archive` — пусто; evidence/ADR/unresolved risks/rollback — на месте (исторические упоминания сохранены).
6. **Product code миграцией не изменён:** 36 M = 30 code-файлов (как в итер.3) + 6 `plans/**` (к итер.3 добавился только `plans/project.md` миграции; `workflow_state/backlog/MEMORY` — миграционные правки уже изменённых файлов); untracked-код байт-в-байт == итер.3 (`B2B98024…`/`2DF92F44…`/`A13DC956…`); mtime: код ≤ 02:04, планы 02:16–02:31; новых изменений в `services/**`/`web/**`/`config/**`/`tests/**`/`db/**`/`README.md` после итер.3 нет.
7. **Findings закрыты (перепроверено по коду/тестам/прогону, без опоры на текст):** B-R1026S7-1 (`ctx.model`/`ctx.provider` на OFF-пути `_run`, пин `test_llm_failure_summary_failed_http`), B-R1026S7-2 (`attempts_of()` текст→атрибут→`None`, пины на реальные тексты `llm_client`), L-R1026S7-3 (`SUMMARY_TEST_FORMAT_ERROR` без `exc_info`). L-R1026S7-1 — OPEN (Low, pre-existing, вне diff) → S8/хотфикс.
8. **Binding пересчитан** (значения выше; WTH итер.3 `0c9cc82e…` устарел из-за `tasks.md`).

**Проверенные counterexamples (воспроизведено):**
- Полный регресс на `.venv` — **8890 passed / 0 failed** (114.40 s); S7-файл **35/35**; JS **45/45**; `git diff --check`=0.
- Каталог импортом: **469/426/444/100/98/21** (рецепт: `len(REGISTRY)`, `len(_SETTINGS_FIELDS)`, `len([s for s in REGISTRY.values() if s.category is not None])`, `len(GROUPS)`, `len(_TAB_BY_GROUP)`, `len(TAB_RULES)`).
- `PUBLISH_*` — grep по коду 0 + тест `test_publish_events_absent_gated`; `routes.py`/`param_catalog.py`/`image_generation.py`/`telegram_send.py`/`summary_xml.py`/`summary_article_formatter.py`/`db/**` — вне diff; untracked в `db/` нет; манифесты зависимостей вне diff.
- R17: `attempts_of`/`http_status_of` — из текста исключения только число/код; пины «сырой текст/URL/ключ не текут», `rec.exc_info is None`.
- R18: `bd7c822` → `f774ecc`; `var/backups/s7-round1026-20260924-003537/` и `.env.bak.round1026-s7` на месте; `stash@{0}` не тронут.
- Release readiness: `APP_VERSION` 2.58.26 (импорт), README v2.58.26, cache-bust `?v=__APP_VERSION__`; откат задокументирован (D8/T-3408).

**Blocking findings:** нет (Critical/High/блокирующих Medium = 0).

**Unavailable checks:** live-приёмка владельца (Telegram/WebView) — PENDING OWNER VERIFICATION; deploy T-3408 не выполнялся (вне T-3404); baseline pytest 8854/0 и JS 44/44 на `f774ecc` не перемерялись (worktree занят; дельта +36/+1 сходится с составом); прод не проверялся (нет SSH).

## Handoff

RESULT: **Approved** @Orchestrator — **единый gate T-3404 пройден** (линза 1: итер.3 Approved; линза 2: focused change audit + миграция — раздел выше). Актуальные bindings: Reviewed-Commit `f774ecc`, Working-Tree-Hash `6c7c9061…`, Spec-Hash `d9d11797…`. Отдельного Scanner approval не существует. Далее: T-3406 merge → T-3407 archive → T-3408 deploy (bump 2.58.26; откат `pre-round1026-s7`/`git revert`) → T-3409 handoff; live — PENDING OWNER VERIFICATION. B-R1026S7-1/-2, L-R1026S7-3 — закрыты; L-R1026S7-1 — Low follow-up (S8/хотфикс).
