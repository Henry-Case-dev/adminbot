# evidence.md — S3 `summary-l1-clusterizer-round1026`

## T-3253 [@DevOps] — baseline + точка отката S3 (23.09.2026)

- **HEAD:** `4007081b96b40936f52f0d29bb836510955528ff` == `origin/master` (совпал с ожидаемым `4007081`).
- **Тег:** annotated **`pre-round1026-s3`** = tag-object `7637cc4e3700240d0cb41523ec5a5cc26124970c` → commit `4007081…`; **запушен в `origin`** (`git ls-remote --tags origin pre-round1026-s3` → `7637cc4e…`).
- **Бэкап:** `var/backups/s3-round1026-20260923-183119/` — `git archive HEAD` для `config/settings.py`, `services/summary_generator.py`, `services/summary_prompts.py`, `services/prompt_migrations.py`, `services/param_catalog.py`; blob-хеши всех 5 файлов совпадают с `git rev-parse HEAD:<path>`; `BASELINE.md` — в папке бэкапа.
- **`.env.bak.round1026-s3`:** размер 7131 = 7131, SHA256 совпадает с `.env` (содержимое не печаталось); `.gitignore` содержит `.env.bak*`.
- **Baseline:**
  - `APP_VERSION` = **2.58.21**
  - pytest (интерпретатор `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, Python 3.12.0): **8569 passed / 0 failed / 1 warning** (111.80s); `database is locked` = **0**
  - JS (`node v24.16.0`): **43/43**; `node --check web/app.js` — OK
  - каталог: REGISTRY **467** / Settings **426** / categorized **442** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21** (до санкционированного +1, D4)
  - Δ DDL = **0** (рабочий diff — только `plans/*.md` + untracked папка фичи; DDL/schema-файлов в diff нет)
- **Откат:** `git fetch --tags origin; git reset --hard pre-round1026-s3` (→ `4007081`); канон-откат — ROLLBACK T-3262 (S3-промпт на момент baseline ещё не создан).
- **R18:** теги/бэкапы/`stash@{0}` не удалялись; в git ничего не коммитилось; `deploy_commands.txt` не тронут.
- **Handoff:** @Orchestrator — T-3253 закрыт, baseline зафиксирован; далее **T-3254 @Architect** (Step 2: spec + ADR, открытые вопросы Q1–Q6).

## T-3256…T-3272 [@Builder] — Step 4: блоки A–F (23.09.2026)

**Контекст:** процесс был прерван; оба модуля уже существовали. Проверены против `spec.md`/ADR-1026-5: контракт §95 (схема/ID-пространства/лимиты/канонизация/fail-closed) и ядро (1 вызов/§93-упаковка/слот/логи) — корректны. Доделано недостающее; в ядро добавлен явный WARN при усечении (§4.2 «не резать молча»). Остальное — канон/каталог/слот/тесты/F8/bump.

### Новые/изменённые файлы
- **Новые:** `services/summary_l1_contract.py` (был создан до обрыва, проверен), `services/summary_l1_clusterizer.py` (+WARN-усечение), `tests/test_summary_l1_clusterizer.py` (116 тестов).
- **Изменены:** `services/summary_prompts.py` (канон L1 + `PREV_SUMMARY_L1_CLUSTERIZER_R1026`), `services/prompt_migrations.py` (ступень+ROLLBACK), `services/param_catalog.py` (+1 промпт-ключ), `config/settings.py` (env-only `SUMMARY_L1_*` + bump), `.env.example`, `README.md`, `plans/docs/canon/architecture.md` (эталон), `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md`, фикстуры F8, ~40 тестов (baseline-числа/версия-пины).

### Числа (импорт-проверка)
- каталог: REGISTRY **468** (467+1) / Settings **426** (не менялось) / categorized **443** (442+1) / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21**; prompts 21→**22**.
- F8: `--check` → `CHECK OK: реестр 468 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`; `f8_baseline.json` counts 467→468, delta 56→57; sha256 `param_catalog.py` = `6531f653b74bf10ac7e98dc351587a2efe79312eb60c25b120935322729dd812`; `catalog_baseline.json` 467→468 + ключ L1 в `registry_keys`.
- `APP_VERSION` 2.58.21 → **2.58.22** (settings + README + все версия-пины, Python/JS).

### Канон (ADR-1013-3)
- `SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT` = база (§94: темы/переплетённые разговоры/хронология/факты+evidence/строгий JSON §95/«НЕ ПИШЕШЬ САММАРИ») + `TARGET_INSTRUCTION_BLOCK`; `PREV_SUMMARY_L1_CLUSTERIZER_R1026` = база (слепок до ступени маркировки; прецедент `PREV_SUMMARY_EDITOR_R1023`).
- `PROMPT_MIGRATIONS[prompts.summary_l1_clusterizer_system_prompt]` + `ROLLBACK_MIGRATIONS` — идемпотентны, кастом не перезаписывается (тесты `TestCanonMigrations`).
- Эталон `plans/docs/canon/architecture.md` — байт-в-байт == коду (тест `test_canon_doc_byte_identical`).

### Прогоны (факт)
- `pytest -q --timeout=120` (`.venv`, Python 3.12): **8685 passed / 0 failed / 1 warning** (104.52s); baseline 8569 → **+116** (новый файл); `database is locked` = **0**.
- JS: **43/43** (`node tests/js/*.js`); `node --check web/app.js` OK (JS-рантайм не менялся).
- `git diff --check` — чисто; `tools/gen_param_registry_round1025.py --check` — exit 0.

### Покрытые сценарии
SC-02…SC-18: структура §95 (матрица валид/невалид, лишние поля, лимиты), ID-матрица (DB `id` vs TG `message_id`, evidence ⊆ треда, дубли, `unassigned`-конфликт, `id_space_mismatch` при конвертации §93), fail-closed `L1Result{ok|empty|invalid|truncated|error}`, покрытие/auto-`unassigned`, детерминизм (двойной прогон), «L1 не пишет саммари», чанки/overlap/усечение+WARN, слот (наследование/hot-first/fallback), ровно 1 вызов L1 (в т.ч. при >1 чанке), логи §108/§109 R17-safe, канон/миграция/ROLLBACK, живой путь (2 вызова, `step`-матрица, OFF байт-в-байт, `summary_generator`/`summary_xml` без L1-склейки).

### Не сделано (осознанно вне S3)
- **T-3273** (врезка L1) — **DEFERRED** (GATED S5/S6): `services/summary_generator.py`/`summary_xml.py` вне diff (тест `TestLivePathInvariants::test_generator_source_has_no_l1_wiring`), третий LLM-вызов не добавлялся.
- **T-3274** (S9 §113) — отдельная фича.
- UI/каталог модели-слота — S5 (D4: env-only, Δ каталога=0 по слоту).
- Deploy/merge — @DevOps/@Architect (T-3280/T-3278) после Reviewer/Scanner.

### Handoff
@Orchestrator → **T-3275 @Reviewer** (ревью S3), затем **T-3276 @Scanner** (аудит: Δ DDL=0/R17/2 вызова/D4). Замечания для ревью: `PREV_SUMMARY_L1_CLUSTERIZER_R1026` — слепок базы канона S3 без общего блока маркировки (прецедент `PREV_SUMMARY_EDITOR_R1023`), поэтому ступень миграции/откат содержательны (не identity; тесты `updated`/`rolled_back`); `id_space_mismatch` эмитится на пути конвертации DB→TG (§93-фрагменты), в неразбитом входе конвертация не требуется.
