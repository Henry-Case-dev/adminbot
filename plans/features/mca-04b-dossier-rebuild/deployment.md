# deployment.md — `mca-04b-dossier-rebuild` (round1027, деплой 2.58.41 с миграцией SQLite v20)

> **Feature-ID:** `mca-04b-dossier-rebuild`
> **Risk-Level:** R3
> **Deploy:** `nik@198.46.175.136:/var/www/admin_bot` (systemd `admin_bot`, Ubuntu 24.04, venv `/var/www/admin_bot/venv`; sudoers-allowlist: `systemctl {start,stop,restart,status} admin_bot`, `journalctl -u admin_bot`)
> **Дата:** 01.10.2026 (сервер UTC 03:19–03:40; коммиты и пуш — 01.10)
> **Разрешение:** @Reviewer round 2 `Approved for release` (review.md, Binding round 2: HEAD `486b3e9` + WTH `B790BE30…6B9F` + Spec `18DF2178…A3D2`) + приказ владельца через @Orchestrator (очередь MCA-tasks после ASAP)
> **Статус: VERIFIED**

## 0. Binding (re-measure на commit-момент)

| Параметр | Review round 2 (гейт) | На момент коммита (DevOps) | Вывод |
|---|---|---|---|
| Reviewed-Commit (HEAD) | `486b3e913db18811e4392c0a03b327663378bbbb` | `486b3e9` — совпадает | ✓ |
| Spec-Hash | `18DF21787EEF3462F79E9301A109F6D004E68F65730110EAE6F755CC28C5A3D2` | пересчитан — совпадает байт-в-байт | ✓ |
| ADR-1027-9 | `0492EC240BABAF343E765B9525E3303E01654915FD473C4160E75A531E4CEB24` | пересчитан — совпадает | ✓ |
| Working-Tree-Hash (гейт) | `B790BE30846034D87AF20646C17F4166ED4902CA224CE019352E292B7C7A6B9F` (48 записей: 36 M + 7 A + 3 DIR + 2 FOREIGN) | **структура воспроизведена байт-точно: 48/36/7/3/2**; pre-commit WTH = `09D10533B2ACAE189838BD4DDF922D23513BE54E8B6BD59B709420AB66AAD5D4` | ✓ дрейф объяснён (ниже) |
| Дрейф гейта → pre-commit | — | только `review.md` (round-2 секция дописана ПОСЛЕ расчёта гейта — self-declared в Binding round 2, «единственное post-binding изменение — сам этот отчёт»); код-файлы не менялись | ✓ |
| Нулевой дрейф кода | полный pytest 10369/2 | **воспроизведён точно: 10369 passed / 2 failed** (те же 2 якорных чужих bounds-дрейфа `TestBounds`/`TestBoundsA3`, вне скоупа) | ✓ |
| WTH at-commit | — | **`35748A6C6FBF0BC5F242AB2269422559EBCF96E9B37507F9FF52F33D25E05490`** — манифест `plans/reports/mca04b_wth_at_commit.txt` (15 записей: 5 M + 5 A + 3 DIR + 2 FOREIGN; закоммиченная часть гейт-манифеста = содержимое FEAT-коммита; сам манифест исключён — самореференс) | ✓ зафиксирован |

**Release-mechanical delta (задокументированное отклонение от байт-состояния ревью, санкция приказа владельца «APP_VERSION 2.58.41»):** бамп версии + re-pin версии — единственные правки вне ревью-манифеста:
- `config/settings.py` — строка `APP_VERSION = "2.58.41"` + релизный баннер mca-04b (код фичи — байт-идентичен ревью);
- 23 тест-файла — version-пины `2.58.40`→`2.58.41` (24 замены; механика прецедента ASAP-3.2 T-4233; после пина — 1005 passed / 2 known);
- `README.md` — `Версия: v2.58.41` + сегмент mca-04b; `plans/docs/param-registry-round1025.meta.md` — APP_VERSION 2.58.41 (F8 `--check` зелёный).

Файлы ASAP-3.2 из приказа (`summary_fact_package.py`, `graphrag_rebuild.py`, `summary_semantic_reduction.py`, `tests/test_summary_fact_package.py`, semantic-reduction-тесты) — **уже в HEAD с релиза 2.58.40** (`5aa4626`/`0483386`), в дереве чистые — в FEAT-коммит вошли как no-op (действий не требовали).

## 1. Коммиты (пуш `486b3e9..cf33e6d`, ff без force)

1. **FEAT `8281434`** — `feat(round1027): mca-04b dossier-rebuild — subject-of-fact semantics, person-facts persistence, full-history rebuild, staging+activation, migration v20 (APP_VERSION 2.58.41)` — **56 файлов, +4502/−139**:
   - прод-код (10): `services/database.py` (v20 + dossier-generation/staging/activation API + `activate_embedding_generation` + FIX `upsert_generated_dossier` + `dossier_generation_id` в `insert_graph_fact` + `facts_without_evidence_links`), `services/lore_worker.py` (keyset full rebuild `rebuild_dossier_full`, врезка local→SourceRef, N-2 person_facts, `resume_candidates`, честная финализация), `services/dossier_rebuild_jobs.py` (paused/completed, persist-before-pause, staging→активация, каскад, события, mca-17a-корреляция), `web/api/chat_lore.py` (progress от полного диапазона, resume-on-paused, cancel-paused, read-time reconstruction), `services/provenance.py`, `services/mca_gates.py` + `config/settings.py` (7 kill-switch + 2 env-лимита), `services/mca_events.py` (+reason-коды), `services/mca_process_registry.py` (dossier.rebuild v2), `tools/history_import/loader.py` (namespace v2 + стриминговый SHA-256 1 MiB);
   - тесты: новый `tests/test_mca04b_dossier_rebuild_round1027.py` (50) + 21 аддитивная правка существующих + 23 version-pin re-pin;
   - артефакт фичи: `plans/features/mca-04b-dossier-rebuild/threat-failure-analysis.md` (M-1); README + F8-мета (релизная механика).
2. **DOCS `cf33e6d`** — `docs(round1027): mca-04b …` — 7 файлов: spec/ADR-1027-9/tasks/evidence/review (rounds 1+2) + `plans/reports/full_audit_results.md` (записи round 1+2; история сохранена) + `plans/reports/mca04b_wth_at_commit.txt` (манифест at-commit).
3. **DEPLOY-DOCS** — этот файл (коммит после верификации).

**Чужой WIP не тронут и не закоммичен** (§6): `plans/docs/mca-round1027-arch-frames.md`, `plans/docs/mca-round1027-plan.md`, `plans/metrics.md`, `plans/workflow_state.md` (модифицированные, чужие), `extra_images/`, `.playwright-mcp/`, `node_modules/`, `package.json`, `package-lock.json` (untracked). `plans/current_task.md` не менялся.

## 2. Локальные гейты перед пушем

| # | Проверка | Результат |
|---|---|---|
| 1 | Полный pytest (pre-commit дерево, `.venv`) | **10369 passed / 2 failed** — точное воспроизведение ревью-чисел (нулевой дрейф кода; оба failed — до-существующие чужие bounds) |
| 2 | Срез на закоммиченном дереве: пины (23 файла) + тест фичи + test_database | **1005 passed / 2 known**; фича+миграции+loader+memory: **133 passed** |
| 3 | Свежие импорты (`python -B`): все 9 прод-модулей фичи + summary_fact_package/graphrag_rebuild/summary_semantic_reduction | OK; `APP_VERSION=2.58.41` |
| 4 | F8 `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 488**, Δ каталога = 0, R17-чисто |
| 5 | `git diff --cached --check` | только CRLF-шум (известная особенность `core.autocrlf=true`, прецедент задокументирован) |
| 6 | R17-скан стейджа (sk-/xox/ghp/AKIA/PEM/tg-token/JWT/AIza/DSN/password/api_key) | **0 попаданий** |

## 3. Прод-деплой

| Шаг | Результат |
|---|---|
| prod HEAD до | `4cb267a` (2.58.40 full); tracked-дерево чистое (только известный untracked-мусор .bak/дампы) |
| **Бэкап ДО миграции (mca-14)** | **`VACUUM INTO` → `/home/nik/backups_adminbot/local_database_20261001-031932_pre_v20.db`** — 1153.4 MB, `PRAGMA quick_check` = ok, user_version=19, данные: graph_facts 15056, smart_messages 1 987 406 |
| `git pull --ff-only` | `4cb267a` → **`cf33e6d`**; дельта — только ожидаемые префиксы (`config/`, `plans/`, `README.md`, `services/`, `tests/`, `tools/`, `web/`); bot.py/pytest.ini/web-UI не тронуты |
| Предполёт (прод-venv, `python -B`) | импорты всех модулей фичи OK; `APP_VERSION=2.58.41`; миграционный шаг v20 присутствует; **8 kill-switch-резолверов = True** (env .env не менялся — Δenv=0), `batch_max_messages=500`; реестр: **`dossier.rebuild` version=2, stages = (snapshot, extract, synthesize, activate, cascade, finalize)**; литералы `summary_fact_package` по кодпоинтам — **LITERALS_OK** (тема «Общий ход обсуждения», разделитель ` · ` = U+0020 U+00B7 U+0020, U+FFFD = 0) |
| Рестарт | `sudo -n systemctl restart admin_bot` → **active** 03:25:23 UTC, PID 2640824, NRestarts=0; полный старт ~2.5 мин (FTS/graph init на 1.9M сообщений); миграция v20 применена при старте 03:27:47–48 UTC |
| Δ env / seeds | Δenv=0 (все kill-switch default ON); ручных seeds нет |

## 4. DDL-факты (миграция v20, реестр mca-14)

| Гейт | Ожидание | Факт |
|---|---|---|
| `PRAGMA user_version` | 19 → **20** | **20** ✓ (журнал: `[database] migration v20: mca_dossier_generations` / `…mca_dossier_staging_items` / `…graph_facts.dossier_generation_id` / `migration v20 applied | dossier_staging`) |
| Книга `schema_migrations` | ровно одна строка `20/dossier_staging` | **ровно 1** ✓ (хвост: 20/dossier_staging, 19/observability_core, 18/embedding_identity) |
| Таблицы | `mca_dossier_generations` + `mca_dossier_staging_items` | обе созданы ✓ (18 и 10 колонок; пустые — staging-заполнение только при первой пересборке) |
| Индексы (4) | partial UNIQUE `idx_mca_dossier_gen_active` + `idx_mca_dossier_gen_subject` + `idx_mca_dossier_staging_gen` + `idx_graph_facts_dossier_gen` | **все 4** ✓ |
| `graph_facts.dossier_generation_id` | nullable TEXT | **TEXT, notnull=0** ✓ (существующие строки — NULL, legacy-путь не затронут) |
| Идемпотентность | повтор no-op | self-guard `sqlite_master`/`PRAGMA table_info`; применение при рестарте прошло без ошибок; повторный прогон шага — no-op по построению ✓ |
| Данные целы | — | graph_facts = **15056** (байт-паритет с бэкапом), smart_messages ~1.99M ✓ |
| PG (D14) | `cover_style_connections` идемпотентно | **присутствует** ✓ (cover_style_* 6/6 таблиц; 0 строк — как до деплоя; рестарт пересоздание no-op) |

## 5. Пост-деплой верификация (прод, 03:25–03:40 UTC)

| # | Гейт | Ожидание | Факт |
|---|---|---|---|
| 1 | `GET /healthz` | 200 + `2.58.41` | `{"status":"ok","version":"2.58.41"}` ✓ |
| 2 | `GET /api/health` | 200 | 200 ✓ |
| 3 | Каталог F8 на проде (`--check` read-only) | 488/427/463/105/103/21 | **CHECK OK: реестр 488**, карта полна, идемпотентно, Δ=0 ✓ |
| 4 | Kill-switches | 7 MCA_DOSSIER_* + direct priority = ON | **все ON** (резолверы на прод-коде+env; Δenv=0) ✓ |
| 5 | dossier.rebuild v2 стадии живы | registry v2: snapshot/extract/synthesize/activate/cascade/finalize | **version=2, все 6 стадий** ✓; эндпоинты `POST /api/chat_lore/{chat}/dossier/{user}/rebuild` (+latest/{job_id}/cancel) зарегистрированы в живом openapi и отвечают **401 unauth** (TMA/admin-гейтинг сохранён — ADR D13) ✓ |
| 6 | cover_style_connections (D14) | жива | ✓ (см. §4) |
| 7 | Ladder/parity на прод-venv | тест фичи зелёный | **50 passed** (`tests/test_mca04b_dossier_rebuild_round1027.py`) ✓ |
| 8 | Error-spike | нет новых ошибок | journal с рестарта: 2 ERROR + 1 Traceback — **весь известный фон GraphRAG embed-429** (LLMRateLimitError, honest-fail + resume с checkpoint — хвост ASAP-3.2); новых/неизвестных — **0** ✓ |
| 9 | R17-скан журнала | секреты не в логах | **0 попаданий** ✓ (паттерны sk-/xox/ghp/AKIA/PEM/JWT/tg-token/DSN) |
| 10 | Encoding integrity (LITERALS_OK) | литералы по кодпоинтам | ✓ (предполёт, см. §3) |

**Инцидент-заметка (честно):** в ходе верификации первый зонд API использовал неверные пути (без литерального сегмента `dossier`) и давал 404 «Not Found» — была зафиксирована ложная гипотеза «баг роутинга FastAPI 0.141.1»; после воспроизведения на минимальном репро и корректных путях опровергнута: **все dossier/rebuild-маршруты матчатся и отдают 401 unauth** как задумано; фреймворк и код здоровы. В журнал прод-проверок ошибки не попали (read-only пробы).

## 6. Browser smoke

NOT_APPLICABLE — ревью round 2: «browser OPTIONAL — рендеринг не менялся»; web-UI (`web/index.html`/`app.js`/`app.css`/`routes.py`) вне диффа, изменён только API-файл `web/api/chat_lore.py`; API-поверхность верифицирована гейтами 5/§4 (unauth 401, openapi-регистрация).

## 7. Watch / фон / честные границы

- **Живая пересборка досье на проде не запускалась** — платные LLM-вызовы и запуск на реальных данных не входят в DevOps-контур без прямого приказа (staging-перечень п.3; U-2/GEN-R20 ревью — «по spec не блокирует деплой»). Первый запуск — владелец через мини-апп (admin-only) или CLI.
- **GraphRAG embed rebuild** (хвост ASAP-3.2) — продолжился с checkpoint при рестарте (resumed=True, job 7ed322e6…); при 429 — честный failed + resume на следующем старте; наблюдение штатное.
- Скорость/стоимость полного прохода на прод-объёмах, precision/recall A95 на реальной выборке — по факту первой живой пересборки (GEN-R20, за владельцем/следующим циклом).
- L1 (dead knob `dossier_direct_priority_enabled` — объявлен, резолвится; приоритет direct достигнут архитектурно) и L2–L8 — non-blocking долг ревью, переносится.

## 8. Откат

- **Soft (без отката кода):** `MCA_DOSSIER_REBUILD_ENABLED=false` + рестарт → legacy-раннер байт-паритет baseline (под-гейты инертны при master OFF; проверено ревью и `test_master_off_legacy_parity`); v20-объекты старым кодом не читаются.
- **Cold:** `cd /var/www/admin_bot && git reset --hard 4cb267a` + рестарт → 2.58.40; v20 аддитивна (таблицы/колонка останутся — безопасны для старого кода; legacy на v20-БД работает — rollback-compat верифицирован ревью).
- **Точечный откат досье:** `backup_ref` поколения + реактивация предыдущего (`memory_backup`); аварийный restore БД — `local_database_20261001-031932_pre_v20.db` (R18).

## 9. Итог

**VERIFIED.** Прод: `cf33e6d` (feat `8281434`), **APP_VERSION 2.58.41**, health 200, каталог 488/427/463/105/103/21 (Δ=0), **SQLite v20 применена** (книга 20/dossier_staging, 2 таблицы, 4 индекса, nullable `graph_facts.dossier_generation_id`; бэкап `local_database_20261001-031932_pre_v20.db` до миграции), PG `cover_style_connections` идемпотентно жива (D14), kill-switches ON, dossier.rebuild v2 стадии живы + API 401 unauth, ladder/parity 50 на проде, encoding LITERALS_OK, ошибок нет, R17 чист, откат готов (soft env / cold revert `4cb267a` / restore бэкапа).
