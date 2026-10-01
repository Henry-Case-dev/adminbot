# deployment.md — HOTFIX `cover-style-save-hotfix` (деплой 2.58.43, cover style select → «save failed»)

> **Feature-ID:** `cover-style-save-hotfix` (dir, архив: `plans/archive/hotfix-cover-style-select-save-round1029/`)
> **Risk-Level:** R1 (backend-only хотфикс одного роута + тесты; без миграций, auth-изменений, зависимостей)
> **Deploy:** `nik@198.46.175.136:/var/www/admin_bot` (systemd `admin_bot`, uvicorn `127.0.0.1:8000`, venv `/var/www/admin_bot/venv`)
> **Дата:** 01.10.2026 (сервер UTC 09:52–09:58; коммиты и пуш — 01.10)
> **Разрешение:** @Reviewer `Approved for release` (review.md, Binding: Reviewed-Commit `0dc5679…ecf9e` + WTH per-file ×4 + Spec N/A — hotfix-флоу, требованийный артефакт `evidence.md` входит в манифест) + приказ @Orchestrator (деплой 2.58.43, NO DDL, NO seeds)
> **Статус: VERIFIED**

## 0. Binding (re-measure на commit-момент)

| Параметр | Review-гейт | На момент коммита (DevOps) | Вывод |
|---|---|---|---|
| Reviewed-Commit (HEAD) | `0dc5679a32be6237e58cd17da35a1c33f82ecf9e` | `git rev-parse HEAD` = **совпадает байт-в-байт**; staged до коммита = EMPTY | ✓ |
| Working-Tree-Hash (per-file) | 4 стемпа: `web/api/cover_styles.py` `8C0D60A2…`, `tests/test_cover_styles_contract_asap32.py` `7AD40155…`, `tests/test_extra_cover_styles_api.py` `F94C835B…`, `evidence.md` `FAA5B8B0…` | SHA-256 всех 4 скоуп-файлов пересчитаны — **4/4 byte-exact** с рабочим деревом | ✓ дрейфа контента нет |
| Working-Tree-Hash (агрегат) | `1647d903…90994` | **Не воспроизведён** из 24 вариантов сериализации манифеста (sep/join/case/order/trail). По правилу самого ревью гейт инвалидируется только изменением **любого из 4 файлов** (или спеки) — per-file 4/4 byte-exact, дрейфа контента нет. Ожидание @Orchestrator «агрегат уйдёт из-за служебных» не подтвердилось: служебные файлы (чужой WIP) в скоуп-манифест ревью не входили и не изменились | ✓ гейт действителен (per-file binding) |
| Spec-Hash | N/A (hotfix-флоу, `spec.md` нет; `evidence.md` в манифесте) | `evidence.md` — byte-exact | ✓ |

## 1. Коммиты (пуш `0dc5679..e84600e`, ff без force)

1. **FEAT `f1057db`** — `fix(round1029): cover style selection save failed — pg= param + named dict form + pop on clear (APP_VERSION 2.58.43)` — **33 файла, +223/−36**: 3 скоуп-файла хотфикса (`web/api/cover_styles.py` +29/−4, 2 теста) + release-mechanics (bump `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, ре-пин 23 py + 4 js: `2.58.42`→`2.58.43`).
2. **DOCS `e84600e`** — `docs(round1029): hotfix cover-style-select-save-failed — evidence + review (APPROVED FOR RELEASE; WTH re-measure per-file 4/4 byte-exact)` — evidence.md + review.md (169 строк).
3. **DEPLOY-DOCS** — этот файл (коммит после верификации).

**Чужой WIP не тронут и не закоммичен:** `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/reports/full_audit_results.md`, `plans/workflow_state.md` (modified, bookkeeping Orchestrator'а/ревью), untracked `node_modules/`, `package.json`, `package-lock.json`, `extra_images/`, `.playwright-mcp/`. `plans/current_task.md` не менялся.

## 2. Локальные гейты перед пушем

| # | Проверка | Результат |
|---|---|---|
| 1 | Полный pytest (`.venv`, post-bump дерево) | **10437 passed / 2 failed в 295.61s** — точное воспроизведение анкера ревью (оба failed — те же якорные чужие bounds `TestBounds`/`TestBoundsA3`, pre-existing на чистом базисе); новых failed = 0. (Первая попытка прогона упёрлась в таймаут на teardown-флейке `test_summary_memory` (aiosqlite-close, известный долг N3 под нагрузкой) — повторный прогон чистый) |
| 2 | Целевые тесты хотфикса | `pytest tests/test_cover_styles_contract_asap32.py tests/test_extra_cover_styles_api.py -q` → **37 passed** |
| 3 | Свежие импорты (`python -B`) | OK; `APP_VERSION = 2.58.43`; `web.api.cover_styles` / `web.api.deps` импортируются |
| 4 | F8 `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 488 == REGISTRY**, exit 0 — Δ каталога = 0 |
| 5 | JS-набор (4 ре-пиннутых файла) | **4/4 passed** (`node tests/js/round1025_hotfix{6..10}…` — hotfix7/8/9/10) |
| 6 | R17-скан скоупа коммита (sk-/xox/ghp/AKIA/PEM/tg-token/JWT/DSN/password/api_key) | **0 попаданий** по 33 файлам |

## 3. Прод-деплой (UTC)

| Шаг | Результат |
|---|---|
| prod HEAD до | `6888d20` (2.58.42); tracked-дерево чистое (0 изменённых) |
| `git pull --ff-only` | `6888d20` → **`e84600e`**; дельта 44 файла — только ожидаемые префиксы (`web/api/cover_styles.py` — единственный web-файл, `config/`, `README.md`, `tests/`, `plans/`); **0 файлов `services/database.py`/миграций/`.sql`/seed** → NO DDL по составу дельты |
| Пре-рестарт health | `GET /healthz` → 200 `{"status":"ok","version":"2.58.42"}` |
| Предполёт (прод-venv, `python -B`) | импорты `config.settings` / `web.api.cover_styles` / `web.api.deps` / `web.app` OK; **`APP_VERSION = 2.58.43`** |
| Рестарт | `sudo -n systemctl restart admin_bot` 09:52:36 → **active** 09:53:42 (66s), **PID 2720688, NRestarts=0**; health 200 `2.58.43` первый — 09:53:57 |
| Миграции | **НЕТ** (NO DDL): `PRAGMA user_version = 21` — без изменений; книга `schema_migrations` хвост `(21, episodes_stories), (20, dossier_staging)` — без изменений; строки «migration» в журнале — только штатный идемпотентный `[prompt_migration] уже новый канон` стартовый чаттер; PG no-op |

## 4. Пост-деплой верификация (прод, 09:53–09:58 UTC)

| # | Гейт | Ожидание | Факт |
|---|---|---|---|
| 1 | `GET /healthz` | 200 + `2.58.43` | `{"status":"ok","version":"2.58.43"}` ✓ |
| 2 | `GET /api/health` | 200 | **200** ✓ |
| 3 | **Прод-смоук: `POST /api/cover/select`** (init-data, HMAC `WebAppData`, admin из `bot_admins`, приватный чат профиля id `***…95`) | 200 (до фикса — 503 «save failed») | **200** `{"chat_id":…95,"style_id":"medved_press"}` — 09:56:42.599Z ✓ |
| 4 | Персистенция (reload-эквивалент) | override в PG + резолв читающим путём | `chat_params.overrides["prompts.summary_cover_style_id"]="medved_press"` в PG ✓; `get_all_chat_params(chat_id, pg=)` резолвит тот же override ✓ (это тот read-path, по которому мини-апп восстанавливает выбор) |
| 5 | Снятие выбора (pop-путь Д-2-фикса) | 200 + удаление override | **200** — 09:56:42.661Z; `chat_lore_history`: ровно 2 записи (select+clear), `changed_by=user.id`, дублей нет ✓ |
| 6 | Отсутствие побочных эффектов | overrides чата = пре-состоянию | **байт-в-байт равны** (`flags.*` ×2, `memory.*` ×2 — не тронуты) ✓ |
| 7 | Каталог F8 на проде (`--check` read-only) | 488, Δ=0 | **CHECK OK: реестр 488** ✓ |
| 8 | Error-spike | нет новых ошибок | журнал с рестарта: 240 строк, 3 error-строки — **весь известный фон GraphRAG embed-429** (`LLMRateLimitError` / `EMBEDDING_GENERATION_FAILED` / `summary_memory embed`, наблюдался до деплоя); новых/неизвестных — **0** ✓ |
| 9 | R17-скан журнала | секреты не в логах | **0 попаданий** ✓ |

**Browser smoke: NOT_APPLICABLE** — `web/app.js` вне диффа (review: «UI-слой вне скоупа», 0 файлов `web/` кроме API-роута); HTTP-смоук §4.3–4.6 закрыл отложенную ревью live-проверку (реальный роутер + real PG на проде).

## 5. Инструментальные заметки (честно)

- `sudo -n` на произвольные команды (journalctl-альтернативы, /proc) требует пароль (allowlist-таймстамп истёк; у mca-04b/mca-05 наблюдалось то же) — не блокер: журнал читается группой без sudo, рестарт из allowlist прошёл, все журнальные гейты выполнены.
- Манифест-агрегат WTH не воспроизведён (см. §0) — binding удержан per-file 4/4 byte-exact + HEAD; для следующего касания: зафиксировать сериализацию манифеста явно (файлом в plans/reports, прецедент mca-05).

## 6. Откат

- **Cold:** `cd /var/www/admin_bot && git reset --hard 6888d20` + `sudo -n systemctl restart admin_bot` → 2.58.42. Данных последствий нет: NO DDL (user_version 21 не менялся), chat_params-оверрайды от смоука возвращены к пре-состоянию (§4.6).
- **Soft:** не применим — у роута нет kill-switch, но дефект хотфикса (503 на каждый выбор) сам и есть причина отката; cold-реверт покрывает.

## 7. Итог

**VERIFIED.** Прод: `e84600e` (feat `f1057db`), **APP_VERSION 2.58.43**, health 200, прод-смоук `POST /api/cover/select` → **200 + персистенция в PG + резолв read-path + чистый pop** (прежде — 503 «save failed» на каждый выбор), NO DDL (user_version 21, книга, PG — без изменений), каталог 488 Δ=0, 0 новых ошибок (только известный embed-429 фон), R17 чист, смоук оставил прод-состояние нетронутым, откат готов (cold revert `6888d20`).
