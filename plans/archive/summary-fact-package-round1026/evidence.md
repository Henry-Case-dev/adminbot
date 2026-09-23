# evidence.md — S4 `summary-fact-package-round1026` (Step 4 @Builder, блоки B–F)

> Контракт: `spec.md` (§1–§15, SC-01…SC-10) + **ADR-1026-6** (D1–D6, Accepted).
> Область Step 4: **только** модуль + схема + валидатор + бюджет + логи + тесты.
> **Врезка `L1 → пакет → L2` НЕ делалась** — GATED (S5/S6), блок G (T-3299) не трогался.
> Базис: HEAD `59f5921` (closing-docs S3), baseline `APP_VERSION` 2.58.22.

## Итог Step 4 (23.09.2026)

- **Новые файлы:** `services/summary_fact_package.py` (чистый модуль, 0 LLM-вызовов),
  `tests/test_summary_fact_package.py` (52 теста).
- **Изменённые файлы:** `config/settings.py` (bump `APP_VERSION` 2.58.22 → **2.58.23**),
  `README.md` (v2.58.23 + описание S4), `plans/docs/param-registry-round1025.meta.md`
  (`APP_VERSION`), 13 Python-тестов + 4 JS-теста (версионные пины `2.58.22 → 2.58.23`
  атомарно, значения только; ярлыки-комментарии не трогались — прецедент S3 I-R1026S3-1).
- **Не изменялись:** `services/summary_generator.py`, `services/summary_xml.py`,
  `services/telegram_send.py`, `services/image_generation.py`, `web/**`,
  `services/database.py`, `services/pg_db.py`, `services/param_catalog.py`,
  `plans/docs/canon/**`, промпты/каноны — подтверждено `git diff --name-only`
  (пусто) и тестами `TestLivePathInvariants`.
- **`plans/current_task.md`** не читался/не изменялся этим шагом (R17/R18);
  `plans/workflow_state.md`/`MEMORY.md`/`backlog.md` — правки Step 0 @Memory (не Step 4).

## Реализация по блокам

### Блок B — схема/модель/fail-closed (T-3286…T-3288)
- `services/summary_fact_package.py`:
  - топ-уровень ровно `{schema_version:1, status, threads[], unassigned_message_ids[], service{response_mode,cover_prompt}, budget{kind,limit,estimated,fits}}` — `TOP_LEVEL_FIELDS`, фиксированный порядок;
  - тема ровно `{thread_id, name, description, chronology[], facts[], evidence_ids[], fragments[]}` — `THREAD_FIELDS`;
  - `name` = `topic` verbatim; `facts` verbatim из L1; `evidence_ids` = union evidence ASC;
  - `FactPackageResult{status, package|None, reason, metrics, budget}` + `deliverable`/`usable`;
  - `build_fact_package(l1_result, payload_items, *, budget=None, correlation_id=None)` — `correlation_id` добавлен **аддитивно** (§109/R17; формальный `run_id` — S7), канонический вызов S5 `(l1_result, payload_items, budget=...)` не затронут;
  - fail-closed `ok→ok`; `truncated→truncated`+проброс `skipped_ids/skipped_tg_ids/chunk_count`; `empty/invalid/error → threads=[]` (объект строится, в L2 не идёт); `not_built` (нет `L1Result` / неизвестный статус / `ok|truncated` без `payload`) → `package=None`;
  - ID-целостность: TG `message_id` (§92/§95); DB `id` → `missing_source`/`invalid`; `evidence_message_ids ⊆ message_ids`; дубли между темами → `invalid`; `unassigned` конфликт/висячий → `invalid`.

### Блок C — отбор/дедуп/хронология/детерминизм (T-3289…T-3291)
- `fragments` — из §92-payload (`build_l1_payload`), приоритет evidence-first, внутри ASC `(timestamp,message_id)`; пустой `text` в фрагменты не попадает (остаётся в `chronology`); лимиты `FRAGMENT_MAX_CHARS=1000`, `MAX_FRAGMENTS_PER_THREAD=30`, `MAX_FRAGMENTS_TOTAL=500` (превышение — явное: `skipped_ids` + WARN + `truncated`);
- `description` — детерминированная агрегация `facts[].text` (дедуп casefold+схлопывание пробелов, разделитель `" · "`, кап `DESCRIPTION_MAX=500` по границе слова; нет фактов → `""`); флаг `description_truncated` — в `metrics`, не в L2-контент; **никакой LLM/прозы**;
- `chronology` — ASC пары `{message_id,timestamp}`; темы — ASC по первой паре;
- детерминизм: `serialize_package` (канонический JSON), двойной прогон байт-идентичен; вход не мутируется (`deepcopy`-сверка в тестах).

### Блок D — бюджет/усечение (T-3292…T-3293)
- `resolve_fact_package_budget()` → `resolve_chat_limit(limits.summary_max_context_tokens, 30000, "SUMMARY_MAX_CONTEXT_CHARS", chars, "SUMMARY_FACT_PACKAGE")` (тот же приём, что `resolve_l1_budget`);
- приоритет усечения: (1) `fragments` — **самый старый глобально** первым (`(timestamp,message_id)`), последние сохраняются; (2) `description` → `""`; (3) целые темы — старая первой; факты/evidence не режутся частично;
- любое вытеснение → `status=truncated` + `skipped_ids`/`skipped_threads` + WARN `FACT_PACKAGE_TRUNCATED` (§93/§96);
- ноль тем в бюджете → `status=empty` (`reason=budget_empty`) → L2 не вызывается;
- **Δ каталога=0**: новых env/ключей нет; `resolve_fact_package_budget` использует существующие `summary_*`.

### Блок E — логи/метрики (T-3294…T-3295)
- события `FACT_PACKAGE_START`/`COMPLETE`/`ERROR`/`TRUNCATED` (WARN) — аддитивно, R17-safe (только числа/коды/id; без текстов/ключей/сырых ответов);
- аддитивные счётчики в `metrics`: `threads_count/facts_count/fragments_count/evidence_count/truncated_count/skipped_fragments_count/skipped_threads_count/descriptions_cleared_count/description_truncated/fragment_char_truncated_count/kind/limit/estimated/fits/l1_skipped_count/l1_chunk_count/duration_ms` + `skipped_ids`/`skipped_threads` (кортежи id) — без узлов ExecutionGraph (S8).

### Блок F — тесты (T-3296…T-3298)
- `tests/test_summary_fact_package.py` — **52 теста** (зелёные): схема/поля/порядок ключей; `description` из фактов (дедуп/кап/пусто); `chronology` ASC; детерминизм (байт-идентичность) + не-мутация входа; все статусы fail-closed (`ok/truncated/empty/invalid/error/not_built`); DB-id/висячие/фабрикованные → `invalid`; `evidence_ids ⊆ message_ids`; дубли/конфликты; evidence-first + компактность (§96 «не дублировать сырой лог»); лимиты фрагментов; бюджет/усечение (`truncated`/`skipped_ids`/`skipped_threads`/description/empty) + WARN; транзит `service`; резолвер бюджета (hot-first/chars-fallback/default/unlimited); Δ каталога=0; `APP_VERSION==2.58.23`; **0 LLM** (модуль не импортирует `llm_client`, не async); **регресс `await_count==2`** (`steps=[stage1,stage2]`) в живом пути; `summary_generator`/`summary_xml` без врезки.

## Прогоны (фактические)

| Проверка | Команда | Результат |
|---|---|---|
| Новый файл тестов | `.venv\Scripts\python.exe -m pytest tests/test_summary_fact_package.py -q` | **52 passed / 0 failed** (2.54 s) |
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **8737 passed / 0 failed / 1 warning** (108.99 s) — baseline 8685 + 52 |
| JS-тесты | `node tests/js/<file>.js` (все 43) | **43/43 OK, 0 fail** |
| `node --check` (изменённые JS) | `node --check tests/js/round1025_hotfix{7,8,9,10}_*.js` | exit **0** |
| Каталог (импорт) | `python -c "from services import param_catalog..."` | REGISTRY **468** / Settings **426** / categorized **443** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21** → **Δ=0** |
| Δ DDL | `git diff --name-only` по DB-файлам + `test_zero_ddl` в полном прогоне | **0** (`database.py`/`pg_db.py` вне diff; SQLite v12) |
| Живой путь вне diff | `git diff --name-only -- services/summary_generator.py services/summary_xml.py services/telegram_send.py services/image_generation.py web/` | пусто |
| `git diff --check` | `git diff --check` | exit **0** |
| R17 | тест `TestBudget::test_logs_r17_safe` + `TestDescription::test_module_has_no_llm_dependency` | секрет не в логах; `llm_client` в модуле отсутствует |

## Соответствие приёмке (SC)

SC-01 ✅ (полнота темы) · SC-02 ✅ (0 LLM; `await_count==2`) · SC-03 ✅ (fail-closed) ·
SC-04 ✅ (ID TG/DB) · SC-05 ✅ (компактность, evidence-first) · SC-06 ✅ (явное усечение + WARN + последние сохранены) ·
SC-07 ✅ (байт-идентичность, вход не мутируется) · SC-08 ✅ (`description`/`chronology` детерминированы) ·
SC-09 ✅ (транзит `service`) · SC-10 ✅ (Δ каталога=0, живой путь/XML вне изменений).

## Проверки, которые не выполнялись (вне scope Step 4 / недоступны)

- **Врезка `L1Result → пакет → L2`** — НЕ делалась (GATED, блок G/T-3299): живой пайплайн по-прежнему 2 вызова без пакета (S5).
- **Live-проверка на проде** — не выполнялась (нет SSH в этой роли; deploy — T-3305 @DevOps).
- **F8-переиздание** — N/A: Δ каталога=0, ADR-1026-2 не запускается.
- **`?v=` cache-bust** — версия транзитна через `web/app.py` (`__APP_VERSION__`), сервер получает 2.58.23 автоматически; отдельный передел HTML не требуется.

## Handoff

@Orchestrator → **T-3300 @Reviewer** (ревью S4: §96-полнота/компактность/доказательства, fail-closed D5, ID-пространства, отсутствие врезки/3-го вызова, Δ каталога=0, отсутствие ложных закрытий) и **T-3301 @Scanner** (независимый аудит: Δ DDL=0, Δ каталога=0, R17/R18, CSP/zero-build, публикация/`summary_generator` вне diff, 0 новых зависимостей).
Блок **G (T-3299)** — **GATED, не трогался**.

## T-3305 [@DevOps] — пост-деплой VERIFIED (23.09.2026)

- **Коммиты/пуш:** `08219ab` (код+тесты, `APP_VERSION` 2.58.23) → `7722d66` (планы/архив: Merge §75 + архивация + Scanner/Reviewer-аудит); push `59f5921..7722d66 master -> master` в `origin` (без force). `origin/master` = `7722d66`.
- **Преддеплойный гейт (`.venv`):** `tests/test_summary_fact_package.py` + `test_param_catalog.py` + `test_webapp_api.py` — **247 passed / 0 failed**; JS **43/43**; `git diff --check` = 0; **Δ DDL=0** (БД/миграции вне diff); каталог импортом REGISTRY **468**, F8 `--check` **OK**.
- **Прод:** `/var/www/admin_bot`, `3ccb1bb..7722d66` **ff-only** pull (40 файлов); `sudo systemctl restart admin_bot` → **active (running)**, MainPID **425178**, ActiveEnterTimestamp **2026-09-23 08:52:54 UTC**.
- **Прод-факты:** `APP_VERSION` = **2.58.23**; `/api/health` **200** `{"status":"ok"}`; served `?v=2.58.23`; `database is locked` = **0**; `FACT_PACKAGE_*` в логах = **0** (модуль не врезан — GATED S5/S6); планировщик `services.summary_scheduler - SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)`; бот `@PERMsoc_bot` (id=8802473181) polling; каталог **468**; Traceback/CRITICAL/ImportError от нового PID = **0** (единственный `Traceback` в журнале — от прежнего PID 394949, 07:01:24, LLM-timeout `summary_memory`, обработан, с S4 не связан); миграции не запускались.
- **Откат:** `git fetch --tags && git reset --hard pre-round1026-s4` (annotated → `59f5921`) + рестарт; hot-OFF не требуется (живой путь не тронут). R18: теги/бэкапы `var/backups/s4-round1026-20260923-202326/`, `.env.bak.round1026-s4`, `stash@{0}` не удалялись; `deploy_commands.txt` не изменялся.
- **Оговорка:** HTTP 200 и старт сервиса ≠ корректность построения пакета фактов — врезка `L1→пакет→L2` GATED (S5/S6); live-приёмка — PENDING OWNER VERIFICATION. Гигиена секретов: `deploy_commands.txt` (gitignored) хранит SSH/sudo-креды в открытом виде — рекомендован secret-manager и ротация (вне рамок S4).

**Handoff:** @Orchestrator → T-3305 закрыт, поставка **VERIFIED**; далее Architect reconciliation §75, PM-архив, Memory sync/metrics, следующий F.
