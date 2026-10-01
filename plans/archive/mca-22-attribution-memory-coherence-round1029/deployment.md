# deployment.md — mca-22-attribution-memory-coherence (деплой 2.58.44 на прод)

- **Feature-ID:** `mca-22-attribution-memory-coherence`
- **Дата деплоя:** 2026-10-02, окно ~04:08–04:35 UTC+12 (16:08–16:35 UTC 01.10)
- **Статус: VERIFIED**
- **Разрешение:** @Reviewer `Approved for release` (round 2, M-1…M-4 RESOLVED 4/4, 0 blocking — `review.md` Round 2) + Orchestrator-приказ (phase=delivery, next_agent=DevOps, деплой 2.58.44).

## 1. Связка с ревью (binding, re-measure at commit)

- **Base/Reviewed-Commit:** `7a86179688628bd060b47014db8bdec837de694c` (HEAD master на старте деплоя — совпадает с пином round 2; коммитов между ревью и релизом не было).
- **Spec-Hash:** `C4B4043E334373A40C6867CB0B1208516EBC6EE29840B2F65016992ABA5B192E` — воспроизведён байт-в-байт ✅.
- **Пер-файловые пины round 2:** spec.md / ADR-1028-6 / tasks.md — SHA-256 совпали независимо ✅ (tasks `E17B0D5A…`).
- **WTH re-measure at commit:** агрегат round-2 пина `F28E59B2…D208` (33 файла, `path|size|sha256`, sorted, LF, trailing-LF) локально НЕ воспроизвёл — диагностировано: единственная причина — **задокументированная самореференс-оговорка пина**: `review.md` переписан Reviewer'ом в 03:35 (финализация Round 2), ПОСЛЕ фиксации пина; пин по собственной конвенции ревью покрывает байт-в-байт остальные 32 файла. Независимые подтверждения целостности 32/32: (а) три явных пер-файловых пина — MATCH; (б) mtime-freeze — все 28 product/test-файлов + evidence.md не переписывались после финального билда Builder'а (02:49) и до верификации ревью (03:06–03:35); (в) numstat-кромки совпадают с ревью (`memory_agi.py` ровно 168+/1−, `smart_cache` 40+/3−, `dead_page_relay` 15+/0−). Дрейфа скоупа нет; агрегат over current 33 files at commit = `b3e44e8fd9bcef4b7174d4af649dc975dcff76802dc489c78cdcc73662a6bfb9` (отличается ровно review.md).
- **Release-prep (DevOps, санкционировано заданием):** APP_VERSION-бамп 2.58.43→2.58.44 в `config/settings.py` (по конвенции цепочки версий) + механический свип version-пинов: 23 py-теста (`== "2.58.43"` / `'APP_VERSION = "2.58.43"' in SETTINGS` / regex-группы), 4 JS-харнесса (`2\.58\.43`→`2\.58\.44`), README-баннер, `plans/docs/param-registry-round1025.meta.md`. Нулевые изменения логики; полный сьют после свипа — паритет (ниже).
- **Полный pytest после свипа (локально, at-commit):** **10520 passed / 2 failed** за 347 c — ровно пин ревью; оба failed — те же pre-existing bound-тесты round1026 (`test_tool_coordinator…test_forbidden_paths_out_of_diff`, `test_unified_image_request…vs_baseline`), не регресс MCA-22. F8 `--check` EXIT=0 (реестр 488). Импорт-смоук: `config.settings` (APP_VERSION 2.58.44) + все 6 новых сервисов + mca_gates/database — чисто.

## 2. Коммиты и push

- **Feat:** `9c78760` — `feat(round1029): mca-22 attribution-memory-coherence — canonical envelope, bot output ledger, quote resolver, correction revalidation, freshness guard (APP_VERSION 2.58.44)`; **55 файлов**, +4352/−73: 28 файлов скоупа ревью (20 изменённых product/tests + 8 новых) + 27 релизного свипа версий (README, param-meta, 21 py-пин сверх входящих в скоуп, 4 JS). Чужой WIP в коммит не вошёл (проверено: 0 staged-файлов из `plans/backlog.md`, `plans/metrics.md`, `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, `node_modules/`, `package*`, `.playwright-mcp/`, `extra_images/`).
- **Docs:** `aa9031a` — `docs(round1029): mca-22 … spec/ADR/tasks/evidence/review (round 2 APPROVED FOR RELEASE) + full_audit_results (rounds 1+2) + WTH …`; 6 файлов, +1008.
- **Push:** `7a86179..aa9031a master -> master` → `origin/master` (fast-forward, без force). После деплоя — третий docs(deploy)-коммит с этим файлом.
- **Срез до пуша:** в дереве остались только чужие WIP-файлы из перечня ревью — чисто.

## 3. Прод-деплой (сервер `198.46.175.136`, `/var/www/admin_bot`, systemd `admin_bot`)

| Шаг | Результат |
|---|---|
| prod HEAD до | `e84600e` (3 docs-коммита позади локального base `7a86179` — все docs-only; прод-код = отревьюенный хотфикс-базис 2.58.43) |
| worktree-грязь | только untracked (.bak-файлы, extra_images) — tracked чисто, pull безопасен |
| .env пред-чек | Δenv=0: ключей 4 новых рубильников / `MCA_CONTEXT_ANSWER_CACHE` / `CHAT_DEDUP` в .env НЕТ → все дефолты ON |
| Бэкап до миграции | ручной `VACUUM INTO`-эквивалент (sqlite3 backup API, venv-python, сервис живой): integrity ok, user_version=21, smart_messages 1 989 659, 1.26 GiB — верифицирован; ПОСЛЕ инцидента (§4) удалён как дубликат авто-бэкапа миграции |
| `git pull --ff-only` | успех: `e84600e..aa9031a`; прод HEAD = **`aa9031af8187f02cf9d51745f0133c2ee5211735`** |
| рестарт #1 (16:13:24 UTC) | **MigrationBackupError: «insufficient free space for migration copy»** — fail-closed guard mca-14 сработал как задуман; см. §4 |
| стабилизация | освобождено место (§4) → рестарт #2 (16:19:04 UTC): **active**, MainPID **2794785**→**2796224**, NRestarts=0 |
| миграция v22 | применена при старте **16:19:22 UTC**: авто-бэкап `pre_migration_20261001_161922.db` (1.2 GiB, каталог БД) → DDL → `user_version` 21→**22** |
| health | `GET http://127.0.0.1:8000/api/health` → **200 `{"status":"ok"}`** (uvicorn поднялся ~2.5 мин: 2M-строк БД + воркеры; первые пробы 000 в окне старта) |
| runtime-версия | `venv/bin/python -c "from config.settings import APP_VERSION"` → **2.58.44** |
| PG | no-op (pg_db.py вне диффа); прод-лог `[pg_db] DDL ok (таблицы + индексы)` — штатный идемпотентный прогон, seeded 420/462 — без изменений против прошлых стартов |

## 4. Инцидент деплоя (диск) — стабилизация, БЕЗ отката кода

- **Что произошло:** рестарт #1 упал на старте: `services.memory_backup.MigrationBackupError: backup: insufficient free space for migration copy` (16:13:47 UTC). Guard mca-14 требует перед DDL авто-бэкап БД со свободным местом ≥ (БД+WAL) × `_FREE_SPACE_SAFETY=2.0` ≈ **2.7 G+**. На момент рестарта свободно было 1.5 G — мой ручной pre-бэкап (1.35 G) съел запас. ВАЖНО: и до ручного бэкапа свободно было ровно 2.7 G — миграция упала бы в любом случае (диск был 89% ещё до деплоя): требование 2.0× не выполнялось «впритык».
- **Стабилизация (порядок):** удалён мой ручной pre_v22-бэкап (дублировал будущий авто-бэкап — то же до-DDL состояние v21) → 2.7 G — всё ещё недостаточно → удалены **устаревшие** миграционные бэкапы: `local_database_20260915-204606_pre_seed_fix.db` (0.72 G, 15.09) и `local_database_20261001-031932_pre_v20.db` (1.13 G; v20 применена и перекрыта v21). **Сохранён** `local_database_20261001-080155_pre_v21.db` (1.19 G, самый свежий независимый якорь) → свободно **3.8 G (84%)** → рестарт #2 → миграция и старт прошли штатно.
- **Вывод:** дефект кода отсутствует; fail-closed защита данных отработала корректно. Операционный долг: диск 80–89% — на следующую DDL-миграцию (≥2.7 G запас) места снова будет впритык (4.6 G на момент финиша, из них 1.2 G — новый авто-бэкап). Рекомендация владельцу: ревизия `pre_migration_*`/`.bak`-файлов иjournal vacuum.

## 5. DDL-факты (SQLite v21→v22)

- `user_version` = **22** (живой read-only PRAGMA на проде).
- Таблица **`mca_bot_outputs`** создана; ровно 3 индекса: `idx_mca_bot_outputs_chat_tg`, `idx_mca_bot_outputs_hash`, `idx_mca_bot_outputs_corr`.
- Строк: **0** (чистая append-only книга; запись начнётся с первым доставленным direct-ответом).
- Идемпотентность: `CREATE TABLE IF NOT EXISTS` + guard `sqlite_master` + реестр миграций mca-14 (тесты create/idempotent/legacy-untouched в скоупе ревью); авто-бэкап до DDL создан guard'ом — повторный рестарт безопасен (проверено фактически: упавший старт #1 не оставил полусостояний — DDL не начиналась, повторный старт применил v22 чисто).
- Данные целы: smart_messages 1 989 659 (сверено с пре-миграционной копией байт-в-байт по счётчику), PG не затронут.

## 6. Пост-деплой верификация (факты)

| Гейт | Результат |
|---|---|
| health | **200 `{"status":"ok"}`** |
| APP_VERSION (runtime) | **2.58.44** |
| SQLite `user_version` | **22** |
| `mca_bot_outputs` | жива, 3 индекса, 0 строк |
| kill-switches | все **4 = True** (runtime-резолв: `canonical_attribution_enabled`, `bot_output_ledger_enabled`, `response_freshness_guard_enabled`, `correction_revalidation_enabled`); Δenv=0 (в .env переопределений нет) |
| ladder/parity на прод-venv | **82 passed** (core 58 + truthset 24, вкл. OFF-паритет всех контуров и лестницу цитат) |
| каталог | F8 `--check` на проде: **CHECK OK, реестр 488, EXIT=0** (Δ=0) |
| новые API | `/api/memory/attribution/trace` → **401**, `/api/memory/attribution/metrics` → **401** без auth (эндпоинты живы, admin-only RBAC на месте) |
| error-spike | посторонних ошибок **0**; весь error-фон — единый известный класс: фоновый GraphRAG embed-воркер, Gemini embeddings **429** (6 вхождений 16:22, incl. 1 traceback `graphrag_rebuild._embed`) — тот же класс, что задокументирован в деплое mca-05 («фон: GraphRAG embed-429 resume»); mca-22 embed-путь не трогает |
| R17-скан журнала | чисто: сырых текстов переписки нет (скан длинных кириллических строк — 0 попаданий вне известных системных шаблонов); в логах только ID/коды/числа |
| стартовый журнал | `[pg_db] pool/DDL/roles/admins/settings seeded`, `[config_cache] settings=462`, `[prompt_migration] уже новый канон` ×N (без изменений), `Scheduler started`, `LoreWorker/MemoryBackup/MemoryMaintenance started` — штатно |

## 7. Откат (готовность)

- **Hot:** 4 env-рубильника в `false` + рестарт → legacy-паритет каждого контура (OFF-паритет подтверждён тестами на проде в §6); v22-таблица при OFF не читается и не пишется (безвредна).
- **Cold:** `git revert`/reset к `e84600e` на проде (v22 аддитивна — старый код её не читает; `user_version=22` при откате кода остаётся, безвредно).
- **Restore (крайний случай):** pre_v22 — `/var/www/admin_bot/pre_migration_20261001_161922.db` (1.2 GiB); пре-v21 — `/home/nik/backups_adminbot/local_database_20261001-080155_pre_v21.db` (1.19 GiB).

## 8. Browser smoke

NOT_APPLICABLE для этого инкремента — UI-виджеты Attribution Trace не входят в скоуп (`web/app.js` вне диффа; обязательный гейт T-4317 Browser-Verification перенесён на UI-инкремент по review). API-слой верифицирован на проде (401-unauth, §6).

## 9. Pending (вне сессии DevOps)

- **T-4319 prod-acceptance §37** (за владельцем/следующим шагом): live-смоук — direct Q&A → строка в `mca_bot_outputs` (kind=direct_reply); повторная доставка того же update спустя >5 мин → `DIRECT_UPDATE_DEDUP_HIT`, без второго ответа; новый текст → fresh generation; коррекционная фраза при provenance-факте → `conflicting` + contradicts-link; admin-сессия → 200 от trace/metrics.
- Наблюдение embed-429 фона (существующий, вне фичи).
- Диск: ревизия старых `pre_migration_*`/`local_database.db.bak.*` (рекомендация §4).
- релизные хвосты фичи: edit→revision ledger-строка (T-4287-хвост), UI-гейт T-4317/T-4320.
