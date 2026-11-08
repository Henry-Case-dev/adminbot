# Deploy 2.58.169 — MEMORY-07 §14 (proof/WEAK) + MEMORY-08 S1–S2 (read-модель, единый поиск), сообщества включены

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`). Кандидат принят Reviewer на `e3ae13ae`;
bump-коммит `b2fed707` (только версия/пины, продуктовый код не менялся).

## 1. Границы выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.169` = `b2fed7077e3dac5b5904fc5d999c69bc4363de30` |
| Предыдущий прод | `ea9a7141` @ `release/2.58.168`, healthz 2.58.168, schema 44, флаг OFF |
| MUTABLE_WORKTREE_REQUIRED | **no** — immutable checkout по SHA, `dirty_after=0` (кроме `?? .cache/`) |
| Repo write scope | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 28 test-файлов |
| Δ DDL | **0** (`user_version` остаётся 44, новых миграций нет) |
| Δ каталога | 0 (598), ключ `flags.memory_communities_enabled` не менялся |

### Дельта `ea9a7141..e3ae13ae` (продуктовый код)

| Коммит | Суть |
|---|---|
| `fd198eb8` | заводской default `flags.memory_communities_enabled` OFF → ON (override владельца и env-авария сохраняются) |
| `44a10e28` | MEMORY-08 S1–S2: контракт поискового ответа + read-модель сообществ поверх существующего `retrieve` |
| `c816e83c` | MEMORY-07 §14: provenance в источнике, PROVEN/WEAK по порогам `size ≥ 3`, `S ≥ 1.0`, `S/T ≥ 0.5` |
| `6af6b1c8` | read-модель отдаёт только proven; пустой набор → `items=[]`, без утечки нейтральной подписи |
| `e3ae13ae` | единый `MemoryManager` в `create_app`; `/api/memory/search` с честной деградацией `vector_unavailable` |

Продуктовые файлы: `bot.py`, `services/{config_cache,mca_gates,mca_retrieval_context,memory_communities,memory_contracts,memory_search,param_catalog,summary_memory}.py`,
`web/app.py`, `web/api/cognitive_map.py`. `services/database.py` не тронут; DDL/schema-version в диффе нет.

## 2. Предрелизная проверка (точно на кандидате)

| Набор | Результат |
|---|---|
| quality contract 07 + communities migration/maintenance/retrieval + mem08 read model + unified retrieval 06 + settings persistence + param catalog + config cache + f8 registry + bot main flow + cog-map API | **273 passed** |
| identity migration + avatars UI + tool coordinator + summary exit/shutdown + memory core/lookup + mca07 retrieval context + memory maintenance | **289 passed, 1 failed** |
| version-пины после bump (20 файлов) | **778 passed, 6 failed → исправлено, повтор зелёный (6 + 162 + 50 passed)** |

**Классификация падений (все — предсуществующие, доказано на базовом `ea9a7141` в отдельном worktree):**
- `test_webapp_avatars_ui.py::TestAvatarFrontAudit::test_close_and_fullscreen_buttons` — статический аудит `web/index.html`
  (7 кнопок `✕` против пина 5); blob `web/index.html` идентичен на базе и кандидате (`3c45d015`), дельта его не касается;
- 6+2 тестов держали categorized-ключи равенством `572` при фактических `573` (ключ `flags.memory_communities_enabled`
  добавлен ещё в 2.58.168; там же были исправлены только 2 пина). Пины переизданы в bump-коммите.

Полный прогон не запускался (по условию задачи).

## 3. Выкладка

- SSH: одиночные key-auth подключения (BatchMode), без паролей и поллеров.
- Снапшот до выкладки: `/tmp/predeploy-258169.db` — **1 745 891 328 B**, read-back `user_version 44`, `quick_check ok`,
  `schema_migrations 33`, `mca_community_builds 0`. Удалён самый старый `predeploy-258166.db`.
- `git fetch origin release/2.58.169` → `git checkout -B release/2.58.169 b2fed707` → `APP_VERSION 2.58.169`.
- `systemctl restart admin_bot` → healthz 2.58.169 через 6 c.

## 4. Пост-деплой

| Проверка | Факт |
|---|---|
| Unit | `active`, **NRestarts=0**, MainPID `3200807`, старт 2026-11-08T19:28:38Z |
| `/healthz` локально | `{"status":"ok","version":"2.58.169"}` |
| `/healthz` публично | `{"status":"ok","version":"2.58.169"}` |
| `/web/` | маркер `2.58.169` — 17 вхождений |
| Журнал (новый PID) | `Traceback` **0**, ` ERROR ` **0**; релизных ошибок нет |
| Schema | `user_version 44`, `schema_migrations 33` (без новых), `quick_check ok` |
| Данные | `nodes 33501`, `edges 65188`, `graph_facts 23351` — без изменений |
| Served asset | `/web/app.js` sha256 `495d4882…c3050c6` = sha256 файла в checkout |
| Роуты | `/api/memory/search`: **404 → 401** (роут появился, требует TMA-auth); `/api/memory/cognitive-map`: 401 |
| Планировщик | `Added job "MemoryMaintenanceService._tick_communities"` (interval 3600 c, `max_instances=1`, `coalesce=True`) |

## 5. Effective-state флага (не каталог, а фактическое значение)

| Слой | Значение |
|---|---|
| `env MCA_MEMORY_COMMUNITIES_ENABLED` | не задан (`None`) → env-гейт ON |
| factory default | `True` |
| `hot.get("flags.memory_communities_enabled")` из PG | `True` |
| effective глобально (`chat_id=None`) | **True** |
| effective по 5 чатам с `nodes` | **True** для всех (5/5) |

Скрытого ранее сохранённого `false` в PG нет — OFF-состояние 2.58.168 было только заводским дефолтом.

## 6. Реальная сборка сообществ и потребление

Первый автоматический тик планировщика — только через 3600 c после рестарта, поэтому сборка запущена штатным кодом
(`memory_communities.build_chat_communities`) под пользователем `adminbot` на живой БД (`DatabaseService`), т.е. тем же
путём, что и `_tick_communities`.

| Чат | communities | proven | weak | доля proven | длительность |
|---|---|---|---|---|---|
| -1002661910336 | 3 618 | **1** | 3 617 | 0.0276 % | 4.8 c |
| -1004482340693 | 428 | 0 | 428 | 0 % | 0.1 c |
| 5885953495 | 111 | 0 | 111 | 0 % | <0.1 c |
| 1313107079 | 5 | 0 | 5 | 0 % | <0.1 c |
| 529151103 | 1 | 0 | 1 | 0 % | <0.1 c |

- Всего 5 активных сборок (`mca_community_builds 5`, `mca_community_members 33 499`), статус `active`, `error=None`.
- Единственное proven-сообщество: `c76861`, `size 5`, `label = «Сообщество: леха и вдовин»` (не нейтральное).
- `weak_communities` в `change_summary_json` — только счётчик; сами WEAK-id не персистятся, поэтому утечки «по построению» нет.

### Проверка отсутствия WEAK-утечки (read-only, прод-БД)

| Проверка | Результат |
|---|---|
| read-модель (блок `communities` карты) | `state=ok`, `items=1`, `total=1`, `weak_in_items=0`, `label_kind=['named']` |
| остальные 4 чата | `state=ok`, `reason_code=no_proven_communities`, `items=[]` |
| community-канал retrieval (`_community_candidates` → `_community_candidate`) | 5 кандидатов, `statuses=['proven']`, `provenance_backed=True` у всех, `ids ⊆ proven`, `weak_present=0`, нейтральных подписей 0 |
| прочие чаты | 0 кандидатов |

## 7. Откат

- Код: `git checkout release/2.58.168` (`ea9a7141`) + `systemctl restart admin_bot` → заводской флаг снова OFF,
  тик и retrieval-канал ничего не читают и не пишут в `mca_community_*`.
- Данные: `/tmp/predeploy-258169.db` (read-back ok); предыдущие `/tmp/predeploy-258167.db`, `/tmp/predeploy-258168.db` оставлены.
- Созданные сборки при откате удалять не нужно: при OFF таблицы инертны, v44-схема совместима со старым кодом.

## 8. Что не проверено

- Первый автоматический часовой тик (`_tick_communities`) в 20:28 UTC — не дожидались; проверено, что job
  зарегистрирован и что тот же код успешно строит сообщества на живой БД.
- Тело авторизованного ответа `/api/memory/search` (нужен TMA `initData` реального администратора) — проверен только
  факт публикации роута (401 без токена) и то, что эндпоинт идёт через живой `MemoryManager` (внедрён в `create_app`
  из `bot.py`, второго инстанса нет).
- Визуальный рендер блока сообществ в мини-аппе: в этом релизе UI не менялся.
- Диск: снапшоты `/tmp/predeploy-258167/258168/258169.db` (~5.2 GB) оставлены; `df` = 27G/99G (29 %).
