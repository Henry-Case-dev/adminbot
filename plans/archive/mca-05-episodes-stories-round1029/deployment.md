# deployment.md — `mca-05-episodes-stories` (round1029, деплой 2.58.42 с миграцией SQLite v21)

> **Feature-ID:** `mca-05-episodes-stories`
> **Risk-Level:** R3 (workflow; ревью R2 без эскалации)
> **Deploy:** `nik@198.46.175.136:/var/www/admin_bot` (systemd `admin_bot`, Ubuntu, venv `/var/www/admin_bot/venv`)
> **Дата:** 01.10.2026 (сервер UTC 08:01–08:15; коммиты и пуш — 01.10)
> **Разрешение:** @Reviewer round 2 `APPROVED FOR RELEASE` (review.md, Binding round 2: HEAD `0b1ae9c…662` + WTH `BD1C0C4D…B55F3` per-file 50/50 + Spec `8177CB0F…E9EC0`) + приказ владельца через @Orchestrator (очередь: все фичи в прод)
> **Статус: VERIFIED**

## 0. Binding (re-measure на commit-момент)

| Параметр | Review round 2 (гейт) | На момент коммита (DevOps) | Вывод |
|---|---|---|---|
| Reviewed-Commit (HEAD) | `0b1ae9cc831661cda319dbea40253295d251c662` | `0b1ae9c` — совпадает; staged = EMPTY | ✓ |
| Working-Tree-Hash | `BD1C0C4D68253F46C558B4438A4E3CC6E11CD007683528A2E90B1C0378CB55F3` (манифест `plans/reports/mca05_wth_manifest_rework1.txt`) | **SHA-256 манифеста пересчитан — совпадает**; per-file SHA-256 всех **50 скоуп-файлов — 50/50 byte-exact** с рабочим деревом | ✓ дрейфа кода нет |
| Spec-Hash | `8177CB0F…E9EC0` | покрывается per-file (50/50) | ✓ |
| ADR-1027-12 | `2E7E110B…4C50` | покрывается per-file (50/50) | ✓ |
| N1 (манифест) | `DIFF_SHA256 A73871BF…` устарел (факт `349F6A6F…`) | принят как есть — оперативный биндинг per-file 50/50 + HEAD + staged-empty (санкция ревью R2.4-N1) | ✓ |
| Дрейф после замера гейта | только round-2 секция review.md + допись full_audit_results.md (артефакты ревью, вне кодовой цепочки — прецедент mca-04b) | подтверждено: код-файлы 50/50 byte-exact | ✓ |

Staging = ровно 50 файлов манифеста (10 изменённых prod/доков + 4 новых сервиса/теста + 26 py-репинов + test_mca07 + 4 JS-репина + 4 дока фичи + README + F8-мета). `web/api/cover_styles.py` и прочий EXTRA в коммит не входили.

## 1. Коммиты (пуш `0b1ae9c..6888d20`, ff без force)

1. **FEAT `9053fd5`** — `feat(round1029): mca-05 episodes-stories — episode/story schema, segmentation pipeline, LLM extraction, continuation, legacy facade (APP_VERSION 2.58.42)` — **50 файлов, +5527/−38** (staged-список побайтово = манифесту rework1).
2. **DOCS `6888d20`** — `docs(round1029): mca-05 episodes-stories — spec/ADR/tasks/evidence/review (round 2 APPROVED FOR RELEASE) + full_audit_results (rounds 1+2) + WTH manifests (round-1 D98B3780 / rework BD1C0C4D per-file 50/50)` — 4 файла: review.md, full_audit_results.md, оба WTH-манифеста.
3. **DEPLOY-DOCS** — этот файл (коммит после верификации).

**Чужой WIP не тронут и не закоммичен:** `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/workflow_state.md` (модифицированные, чужие), `.playwright-mcp/`, `extra_images/`, `node_modules/`, `package.json`, `package-lock.json` (untracked). `plans/current_task.md` не менялся.

## 2. Локальные гейты перед пушем

| # | Проверка | Результат |
|---|---|---|
| 1 | Полный pytest (pre-commit дерево, `.venv`) | **10432 passed / 2 failed в 301.88s** — точное воспроизведение анкера ревью round 2 (оба failed — те же якорные чужие bounds `TestBounds`/`TestBoundsA3` vs web/ чужого WIP; новых failed = 0) |
| 2 | Срез на закоммиченном дереве (фича + канал mca-07 + F8-реестр) | **135 passed** (63 + 43 + 29) |
| 3 | Свежие импорты (`python -B`): 10 prod-модулей фичи | OK; `APP_VERSION=2.58.42`; реестр миграций хвост = `21/episodes_stories` |
| 4 | F8 `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 488**, Δ каталога = 0, R17-чисто |
| 5 | JS-набор (`node tests/js/*.js`) | **52/52 passed** (все файлы папки, включая 4 re-pin) |
| 6 | R17-скан скоупа (sk-/xox/ghp/AKIA/PEM/tg-token/JWT/AIza/DSN/password/api_key) | **0 реальных попаданий** (2 совпадения `sk-` — фикстура-заглушка теста санитайзера `assert "sk-ab12…" not in …`) |

## 3. Прод-деплой

| Шаг | Результат |
|---|---|
| prod HEAD до | `cf33e6d` (2.58.41, mca-04b); tracked-дерево чистое (известный untracked-мусор .bak/extra_images) |
| **Бэкап ДО миграции (mca-14)** | **`VACUUM INTO` → `/home/nik/backups_adminbot/local_database_20261001-080155_pre_v21.db`** — 1 281 642 496 байт, `PRAGMA quick_check` = ok, user_version=**20**, graph_facts 15071 |
| `git pull --ff-only` | `cf33e6d` → **`6888d20`**; дельта 65 файлов, только ожидаемые префиксы (`config/`, `plans/`, `README.md`, `services/`, `tests/`); bot.py/web-UI/pg не тронуты |
| Предполёт (прод-venv, `python -B`) | импорты всех модулей фичи OK; `APP_VERSION=2.58.42`; миграционный хвост `21/episodes_stories`; **Δenv=0** (env `MCA_EPISODES_*` оверрайдов нет); резолверы: `episodes_enabled=True`, `episodes_backfill_enabled=True`, `episodes_continuation_enabled=True`, `episodes_compiler_facade_enabled=True`, `episodes_direct_priority_enabled=True`, `episodes_batch_max_messages=500`; send-path grep 3 новых модулей — **0 совпадений** |
| Рестарт | `sudo -n systemctl restart admin_bot` 08:07:49 UTC → **active** 08:08:49 UTC, PID 2699052, NRestarts=0; health 200 `2.58.42` первый — ~08:10:37 (полный старт ~2.8 мин, FTS/graph init на ~2M сообщений); **миграция v21 применена при старте 08:11:21 UTC** (журнал ниже) |

## 4. DDL-факты (миграция v21, реестр mca-14)

| Гейт | Ожидание | Факт |
|---|---|---|
| `PRAGMA user_version` | 20 → **21** (фактическая дельта; в приказе было «v19→v21» — устаревшее: прод уже был на v20 с релиза mca-04b) | **21** ✓ |
| Журнал миграции | применение при старте | **08:11:21 UTC**: `[database] migration v21: mca_episodes / mca_stories / mca_story_versions / mca_story_episode_links / mca_story_continuations / mca_story_redirects / mca_story_legacy_links` + `migration v21 applied \| episodes_stories` ✓ |
| Книга `schema_migrations` | ровно одна строка `21/episodes_stories` | **ровно 1** ✓ (хвост: 21/episodes_stories, 20/dossier_staging, 19/observability_core, 18/embedding_identity) |
| Таблицы (7) | `mca_episodes`, `mca_stories`, `mca_story_versions`, `mca_story_episode_links`, `mca_story_continuations`, `mca_story_redirects`, `mca_story_legacy_links` | **все 7 созданы** ✓ (пустые — наполнение только через episodes.build/backfill, не запускались) |
| Индексы | 6 явных DDL | **6 явных `idx_*`** ✓ (+8 sqlite_autoindex от PK/UNIQUE-контрактов; всего 14 индексных записей на v21-таблицах) |
| Override-колонки (5) | `override_title/summary/outcome/state/open_questions` на `mca_stories` | **5/5 присутствуют** ✓ |
| Идемпотентность | повтор no-op | self-guard `sqlite_master`/`PRAGMA table_info` (ревью §1.1); применение при рестарте без ошибок; повторный прогон шага — no-op по построению ✓ |
| Данные целы | — | graph_facts = **15071** (байт-паритет с бэкапом), smart_messages **1 987 787** (+18 живого трафика от бэкапа 1 987 769), `lore_stories` = 0 (legacy не тронут) ✓ |
| PG | no-op | по построению: `pg_db.py`/`web/**`/`param_catalog.py` вне дельты pull'а ✓ |

## 5. Пост-деплой верификация (прод, 08:10–08:15 UTC)

| # | Гейт | Ожидание | Факт |
|---|---|---|---|
| 1 | `GET /healthz` | 200 + `2.58.42` | `{"status":"ok","version":"2.58.42"}` ✓ |
| 2 | `GET /api/health` | 200 | 200 ✓ |
| 3 | Каталог F8 на проде (`--check` read-only) | 488, Δ=0 | **CHECK OK: реестр 488** ✓ |
| 4 | Kill-switches 4+2 | default ON, Δenv=0 | `episodes_enabled/backfill/continuation/compiler_facade/direct_priority = True`, `batch_max_messages=500` — **все ON** ✓ |
| 5 | Backfill в проде НЕ включён (обязательное условие релиза, M-MCA05-3) | нет вызывателя/запусков | прод-вызывателя `enqueue_episodes_backfill` нет; новых строк в `mca_stories`/`mca_episodes` = 0; ручных запусков не было ✓ |
| 6 | Ladder/parity на прод-venv | тест фичи зелёный | **63 passed** (`tests/test_mca05_episodes_stories_round1027.py`) ✓ |
| 7 | Send-path grep на проде | 0 telegram-вызовов | **0 совпадений** (`telegram_send\|send_message\|sendMessage\|sendRichMessage\|bot.send\|api.telegram` по 3 новым модулям) ✓ |
| 8 | Error-spike | нет новых ошибок | журнал с рестарта (252 строки): 2 ERROR + 1 Traceback — **весь известный фон GraphRAG embed-429** (`LLMRateLimitError`, `EMBEDDING_GENERATION_FAILED` honest-fail + resume — хвост ASAP-3.2, наблюдался до деплоя); новых/неизвестных — **0** ✓ |
| 9 | R17-скан журнала | секреты не в логах | **0 попаданий** ✓ |
| 10 | Реестр процессов | episodes.* зарегистрированы | `episodes.build` v1, `episodes.backfill` v1, `episodes.timeline` v0 в `PROCESS_REGISTRY` (статические определения прод-кода; runtime-инстансов нет — пайплайны не запускались, что соответствует «backfill выключен») ✓ |

**Инфра-заметка (честно):** `sudo -n journalctl -u admin_bot` на этот раз потребовал пароль (allowlist-таймстамп sudo истёк; у mca-04b проходило). Не блокер — журнал доступен пользователю `nik` через группу (чтение без sudo), все журнальные гейты выполнены так.

## 6. Browser smoke

NOT_APPLICABLE — web-UI вне диффа (в 50-файловом манифесте 0 файлов `web/`; рендеринг не менялся), UI эпизодов — будущий mca-12 Wave 5 (ревью: «UI — нет»); health/API-поверхность верифицирована гейтами §5 (curl, read-only).

## 7. Watch / фон / честные границы

- **Episodes-пайплайны на проде не запускались** (`episodes.build`/`episodes.backfill`): backfill — обязательное условие релиза (M-MCA05-3: до wired worker-budget не включать), build — осознанное ops-действие за владельцем. Первый живой прогон покажет скорость/стоимость на прод-объёмах (аналог GEN-R20).
- **GraphRAG embed rebuild** (хвост ASAP-3.2) — продолжил честный fail на 429 + resume на следующем старте; наблюдение штатное, вне скоупа mca-05.
- Non-blocking долг ревью переносится: M-MCA05-2 (unchanged-детектор без claims/участников/дат — до mca-12), N1 (перегенерация DIFF_SHA256 манифеста при следующем касании), N2 (объявлять full_audit в манифесте явно), N3 (aiosqlite-close флейк `test_summary_memory` под нагрузкой — backlog), L1–L6.
- Ревью-доступ к живому LLM-канону извлечения — unavailable (нет провайдера), закрыто офлайн-валидаторами (санкция ревью).

## 8. Откат

- **Soft (без отката кода):** `MCA_EPISODES_ENABLED=false` + рестарт → legacy-паритет baseline (под-гейты инертны при master OFF; тесты OFF-паритета ревью зелёные); v21-объекты старым кодом не читаются.
- **Cold:** `cd /var/www/admin_bot && git reset --hard cf33e6d` + рестарт → 2.58.41; v21 аддитивна (7 таблиц + 5 override-колонок останутся — безопасны; rollback-compat «старый реестр (v20) на v21-БД не применяет шагов» верифицирован ревью §1.1).
- **Аварийный restore БД:** `/home/nik/backups_adminbot/local_database_20261001-080155_pre_v21.db` (пре-миграционный снимок, quick_check=ok).

## 9. Итог

**VERIFIED.** Прод: `6888d20` (feat `9053fd5`), **APP_VERSION 2.58.42**, health 200, каталог 488 (Δ=0), **SQLite v20→v21 применена при старте 08:11:21 UTC** (книга `21/episodes_stories`, 7 таблиц, 6 индексов + autoindex-ы, 5/5 override-колонок; бэкап `local_database_20261001-080155_pre_v21.db` до миграции), PG no-op, kill-switches 4+2 ON (Δenv=0), backfill в проде не включён (условие релиза), ladder/parity 63 на проде, send-path 0, ошибок нет (только известный embed-429 фон), R17 чист, откат готов (soft env / cold revert `cf33e6d` / restore бэкапа).
