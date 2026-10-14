# Scanner — Эпик 2 / S3 `summary-l1-clusterizer-round1026` (Шаг 6, T-3276)

- **Дата:** 23.09.2026, Step 6 @Scanner
- **Diff base:** HEAD `4007081` (annotated-тег `pre-round1026-s3` = tag-object `7637cc4e…` → commit `4007081`), правки **НЕ закоммичены** — аудит дерева (57 tracked M + 4 untracked пути).
- **Режим:** focused diff-based аудит (новые модули + критичные зависимости + инварианты/канон/F8).
- **Вердикт:** **К ДЕПЛОЮ — ДА по технической части (C0/H0, блокирующих дефектов кода нет)**, при условии закрытия процессного гейта **T-3275 @Reviewer** (`review.md` отсутствует — см. M-R1026S3-1).
- **Severity:** Critical 0 / High 0 / **Medium 1 (процесс, не код)** / Low 3 (owned follow-up) / Info 5.

## 1. Область изменений (git status относительно HEAD)

**Новые (untracked):**
- `services/summary_l1_contract.py` (502 стр.) — строгая JSON-схема §95, `IdSpace` (TG), `L1Result` (ok/empty/invalid/truncated/error), парсер на `system2_handoff.parse_json_object`, канонизация/дедуп/ASC, `id_space_mismatch`.
- `services/summary_l1_clusterizer.py` (597 стр.) — `pack_l1_input` (§92→§93-упаковка в один вход), `build_l1_user_content`, `resolve_l1_slot`/`resolve_l1_budget`, ровно 1 вызов LLM (`generate(module="summary", step="l1_clusterizer")` либо dedicated `_post` с fallback-политикой), логи `L1_START/COMPLETE/ERROR`.
- `tests/test_summary_l1_clusterizer.py` (1098 стр., **116 тестов**).
- `plans/features/summary-l1-clusterizer-round1026/{spec.md,adr-1026-5-…,tasks.md,evidence.md}`.

**Изменённые (M):** `config/settings.py` (env-only ClassVar `SUMMARY_L1_*` + bump), `services/summary_prompts.py` (+канон `SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT`, `PREV_SUMMARY_L1_CLUSTERIZER_R1026`), `services/prompt_migrations.py` (+ступень/ROLLBACK), `services/param_catalog.py` (+1 промпт-ключ), `.env.example`, `README.md`, `plans/docs/canon/architecture.md` (эталон), `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md`, `plans/{MEMORY.md,backlog.md,workflow_state.md}`, фикстуры F8 + ~43 теста (version/count re-pin), 4 JS-теста.

**Вне diff (D4-гейт подтверждён):** `services/summary_generator.py`, `services/summary_xml.py`, `services/telegram_send.py`, `services/image_generation.py`, `web/**` — `git status --porcelain` пуст.

## 2. Инварианты (с доказательствами)

| Проверка | Результат | Доказательство |
|---|---|---|
| Δ DDL = 0 | ✅ | `services/pg_db.py` вне diff; `sha256(pg_db.py)` = `12a88191…` == фикстура F8; `test_zero_ddl` зелёный |
| Δ каталога = ровно +1 | ✅ | импорт: REGISTRY **468** (467+1) / Settings fields **426** (без изменений) / categorized **443** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21**; prompts 21→22 |
| `settings_field=None` у промпта | ✅ | `pc.REGISTRY['prompts.summary_l1_clusterizer_system_prompt']`: `settings_field=None`, `env_name=None`, `secret=False`, group `prompts_summary` |
| env-only слот (Δ каталога 0) | ✅ | `SUMMARY_L1_*` — ClassVar, не поля dataclass (426 не изменилось); `test_classvars_env_only_zero_catalog_delta` |
| `APP_VERSION` 2.58.22 синхронен | ✅ | settings=README=meta=tests-пины=2.58.22; старых функциональных пинов нет |
| Маркер-тесты не ослаблены | ✅ | diff тестов — только version/count re-pin + расширение `_ALL_KEYS`/`_PREV_BY_KEY`/`_NEW_BY_KEY`/`_ROLLBACK_*`; `skip`/`xfail` в новом файле = 0 |
| F8 переиздание (ADR-1026-2) | ✅ | `tools/gen_param_registry_round1025.py --check` → `CHECK OK` (exit 0); delta 56→57; `sha256(param_catalog.py)`=`6531f6…7812` == фикстура; TSV/meta/screen-map регенерированы |
| Байтфризы `pg_db.py`/`routes.py` | ✅ | файлы не менялись; `sha256(routes.py)`=`4b652cb1…` == `ROUTES_SHA256_F11` |
| Ровно 2 LLM-вызова / нет третьего | ✅ | в кластеризаторе ровно 1 `await call(` (1 `generate(` / 1 `_post(`); `TestLivePathInvariants`: `await_count==2`, `steps==["stage1","stage2"]`, OFF-цепочка байт-в-байт, `step="l1_clusterizer"` в живом пути отсутствует |
| R17 (логи) | ✅ | `L1_START/COMPLETE/ERROR` + WARN-усечение + `L1 invalid response` — только числа/коды/id/host; тесты `test_error_log_r17_safe`, `test_complete_log_no_raw_content`, `test_truncated_logged_not_silent` |
| R17 (канон/эталон/секреты) | ✅ | в каноне/эталоне только текст промпта; `.env.example` — пустые плейсхолдеры; `SUMMARY_L1_API_KEY` не логируется |
| R18 | ✅ | annotated-тег `pre-round1026-s3` → `4007081`; `var/backups/s3-round1026-20260923-183119/` (+BASELINE.md); `.env.bak.round1026-s3` (7131 B, ignored); `stash@{0}` цел |
| CSP / zero-build | ✅ | новых web-файлов/библиотек нет; импорты новых модулей — stdlib + существующие `services.*`; `web/**` вне diff |
| Гигиена индекса | ✅ | `git ls-files --cached` без `.env`/`current_task.md`/zip/`tools/_ui_*`/`var/backups`; `git diff --check` = exit 0 |
| Канон (ADR-1013-3) | ✅ | эталон == коду байт-в-байт (2846 символов); `PROMPT_MIGRATIONS[key]=[(PREV,canon)]`, `ROLLBACK_MIGRATIONS[key]=(canon,PREV)`; идемпотентность/кастом-не-перезаписывается/pre-seed-skip — тесты `TestCanonMigrations` |
| «L1 не пишет саммари» | ✅ | выход — только `topic`/атомарные `facts`/id; проза >500, markdown-заголовки, `contains_system_ids` → `invalid`; тесты `TestL1DoesNotWriteSummary` |
| ID-пространства (DB↔TG) | ✅ | `Fragment.message_ids` (DB) → `build_db_tg_map` (неоднозначность/пропуск → `IdSpaceMismatch` → `invalid`); валидатор — по payload-индексу TG; `evidence ⊆ thread`; авто-`unassigned` |
| Детерминизм | ✅ | двойной прогон байт-идентичен (тест + ASC `(timestamp,message_id)`, перенумерация `thread_001…`, дедуп фактов) |
| `kept`/S1/S2 не искажаются | ✅ | `pack_l1_input` не мутирует вход (`sorted()`/новые списки); S3 не врезан в живой путь (T-3273 DEFERRED) |

## 3. Прогоны @Scanner (собственные)

- `.venv\Scripts\python.exe -m pytest -q --timeout=120` → **8685 passed / 0 failed / 1 warning** (113.18 s; baseline 8569 → +116).
- Новый файл отдельно: **116 passed**.
- JS: **43/43** OK; `node --check web/app.js` OK.
- `tools/gen_param_registry_round1025.py --check` → exit 0; `git diff --check` → exit 0.
- Импорт-проверки каталога/версии/хешей — см. §2.

## 4. Находки

| ID | Severity | Статус | Локация | Суть | Влияние | Рекомендация |
|---|---|---|---|---|---|---|
| **M-R1026S3-1** | Medium (процесс) | OPEN | `plans/features/summary-l1-clusterizer-round1026/` | **`review.md` (T-3275 @Reviewer) отсутствует**, хотя tasks.md блок H требует ревью до аудита; workflow_state/backlog/MEMORY не отражают и Step 4 @Builder | Релизный гейт не подтверждён артефактом ревью (не код-дефект; независимые проверки Scanner выполнены) | Прогнать T-3275 @Reviewer → `review.md`; при findings — rework + повторные проверки; либо явное решение @Orchestrator о порядке шагов |
| **L-R1026S3-1** | Low | OPEN (non-blocking, hardening) | `services/summary_l1_clusterizer.py:469-475` | `resolve_l1_slot()` вызывается **вне** try/fail-closed-обёртки: исключение из резолва слота пробрасывается наружу (воспроизведено подменой `resolve_l1_slot` → `RuntimeError`), хотя docstring обещает «любое исключение → error/invalid» | При врезке S5 возможен не-fail-closed выброс на редком сбое hot-config; сейчас модуль не в живом пути | Перенести резолв слота внутрь try (или обернуть) — до врезки S5 |
| **L-R1026S3-2** | Low | OPEN (non-blocking, contract) | `services/summary_l1_contract.py:399-413` | `evidence_message_ids: []` принимается как валидный факт (проверено: `status=ok`, `facts=1`, evidence пуст) | «Проверяемый факт» без подтверждающего id может дойти до S4/L2 при врезке; §94 подразумевает наличие evidence | Требовать ≥1 evidence (`invalid_fact`) либо документировать политику в spec/ADR |
| **L-R1026S3-3** | Low | OPEN (non-blocking, edge) | `services/summary_l1_clusterizer.py:193-215` | Строка без `tg_message_id`: single-chunk ветка молча даёт `message_id: null` (вне id-space/auto-unassigned), fragmented ветка падает `IdSpaceMismatch` (воспроизведено) | Прод-инвариант S1/S2 гарантирует поле; расхождение поведения при врезке S5 | Унифицировать: fail-closed (`id_space_mismatch`) и в single-chunk ветке |
| **I-R1026S3-1** | Info | — | `tests/js/round1025_hotfix{7,8,9,10}_*.js` | Regex обновлён на `2\.58\.22`, но человекочитаемая метка assert осталась `'D: APP_VERSION 2.58.21'` | Косметика (тесты зелёные) | Поправить метку при следующем re-pin |
| **I-R1026S3-2** | Info | — | `services/summary_l1_contract.py:50-51,360` | `THREAD_ID_RE` c `$` принимает trailing `\n` (`"abc\n"` → ok) | Нулевое: `thread_id` всё равно перенумеровывается | При желании — `\Z` |
| **I-R1026S3-3** | Info | — | `services/summary_prompts.py:246-252` | Канон L1 содержит `TARGET_INSTRUCTION_BLOCK`, но `build_l1_user_content` не ставит маркер текущей команды — блок условный/инертный | Нулевое сейчас; учесть при врезке S5 (маркировка trigger-сообщения) | Решить судьбу маркера в S5 |
| **I-R1026S3-4** | Info | — | `services/llm_client.py:559-570` | Dedicated-путь идёт через `_post(api_key=…)` → `_get_client(key)` **подменяет общий chat-клиент** при смене ключа (паттерн уже есть у `generate_worker`) | Pre-existing архитектура; для S5 при параллельных вызовах — возможен churn/закрытие клиента | На S5 рассмотреть per-key кэш клиентов |
| **I-R1026S3-5** | Info | — | `plans/workflow_state.md` / `plans/backlog.md` / `plans/MEMORY.md` | Документы не отражают Step 4 @Builder (ожидаемо синхронизируются на Step 8–10 @PM/@Memory) | Нулевое (процесс) | Синк на шаге метрик/архивации |

## 5. Логика/совместимость (собственные наблюдения)

- `pack_l1_input`: ASC `(timestamp, id)`, overlap=1 через существующий `estimate_and_split`; дедуп DB id; маркеры границ — метки одного входа (не вызовы); усечение — самые старые, последнее сообщение сохраняется всегда; `truncated=True` + `skipped_ids`/`skipped_tg_ids` + WARN.
- `run_l1`: `empty` без LLM-вызова (пустое не публикуется); `invalid`/`error` → `payload=None`; `truncated` конвертируется из `ok` при усечении; `usable` = ok/truncated.
- Слот: согласованная пара (пустое поле добирается из глобальной модели), `dedicated=any(непустое)`, hot-first forward-compatible; ошибка dedicated → существующая `LLM_FALLBACK_*` (не подмена на глобальную); секрет не логируется.
- Бюджет: существующие `limits.summary_max_context_*` + chars-fallback (`resolve_chat_limit`); per-chat — S5 (документировано).
- Ретро-совместимость: публикация/обложка/`response_mode`/`cover_prompt`/XML/Stage-1/Stage-2 — вне diff; OFF-цепочка байт-в-байт (тест).

## 6. Handoff

**RESULT: SCANNED @Orchestrator** — код и инварианты чистые (C0/H0), к деплою **ДА** после закрытия процессного гейта **T-3275 @Reviewer** (`review.md`); L-R1026S3-1/-2/-3 — owned follow-up (не блокируют), Info 1–5 — наблюдаемые заметки. Отчёт: `plans/reports/round1026_s3_scanner_audit.md`.
