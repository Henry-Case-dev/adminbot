# Deploy 2.58.168 — MEMORY-07 волны 3–4: сборка сообществ, active-build канал retrieval

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`). APPROVED-кандидат
Reviewer'а `f09ba143` + релизный bump → `ea9a7141`. Схема БД не меняется
(`user_version` остаётся **44**), гейт `MCA_MEMORY_COMMUNITIES_ENABLED` остаётся
**OFF**, таблицы `mca_community_*` в проде пусты.

## 1. Идентичность выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.168` = `ea9a71415dfbeb9f5363363ab4461e4e2a2a0d2f` |
| APPROVED-кандидат | `f09ba143` (parent `4cfe02a4`) |
| Релизный коммит | `ea9a7141` = `f09ba143` + bump 31 файл (41/38) |
| Предыдущий прод | 2.58.167 @ `153063b2` |
| MUTABLE_WORKTREE_REQUIRED | **no** — immutable checkout по SHA, `dirty_after=0` |
| Repo write scope | `config/settings.py`, `README.md`, `plans/docs/…meta.md`, 22 py + 4 js пина версии, 1 пин каталога |

### Дельта `153063b2..f09ba143`

Продуктовых файлов **6** (в постановке было «пять» — фактически шесть, все одной
волны, продуктовое поведение вне гейта не меняется):

| Файл | Что |
|---|---|
| `services/memory_communities.py` (+1196) | детерминированный сборщик, провенанс-веса, lifecycle, подписи, стабильные `community_id` |
| `services/memory_maintenance.py` (+80) | job `memory_communities_build` (1 ч, `max_instances=1`, `coalesce=True`), гейт на каждом тике |
| `services/mca_retrieval_context.py` (+39/−7) | `_community_candidates` — только `status='active'`, только thematic |
| `services/mca_gates.py` (+50) | гейт `MCA_MEMORY_COMMUNITIES_ENABLED` (env AND каталог), default OFF |
| `services/param_catalog.py` (+16) | `flags.memory_communities_enabled` (598) |
| `services/config_cache.py` (+4) | PG-default `False` |

**DDL = 0**, `services/database.py` не менялся, `user_version` не меняется, новых
миграций нет. `DROP/CREATE TABLE` в дельте — только в тестовом setup.

## 2. Предрелизная проверка (точный кандидат)

`py -3 -m pytest … -q -p no:cacheprovider`, cwd — worktree кандидата.

| Прогон | Результат |
|---|---|
| `test_memory_communities_{maintenance,retrieval,migration}` + `test_round1025_f8_registry` + `test_param_catalog` | **106 passed** |
| smoke памяти/retrieval: `test_memory_core_round1020`, `test_memory_lookup_round1026`, `test_memory_unified_retrieval_06`, `test_mca07_retrieval_context_round1027`, `test_memory_maintenance` | **204 passed** |
| После bump: пины версии/каталога (`f8`, `param_catalog`, `scope_selector`, `tool_coordinator`, communities×3) | **175 passed** |

Полный suite намеренно не гонялся (по указанию).

**Найден и устранён пин-дрейф кандидата:** `tests/test_tool_coordinator_round1026.py::
test_version_and_catalog` требовал жёсткое `categorized == 572`, тогда как принятая
дельта каталога добавляет categorized-ключ `flags.memory_communities_enabled` → **573**
(`REGISTRY 598`). Пин переиздан точным равенством в релизном коммите (комментарий с
причиной), прогон после правки — зелёный. Продуктовое поведение не менялось.

## 3. Выкладка

Один SSH-коннект (BatchMode, ключ, port 22), без ретраев, по правилам AGENTS.md.

- pre-state: `release/2.58.167`, `head=153063b2`, `tracked_dirty=0`, healthz `2.58.167`.
- `git fetch` → `ea9a7141` есть; `origin/release/2.58.168 = ea9a7141`; rollback-объект `153063b2` есть.
- Снимок ДО: `/tmp/predeploy-258168.db` — **1 742 491 648 б**, read-back `user_version 44`,
  `quick_check ok`, `schema_migrations 33`, `smart_messages 2 073 960`, `nodes 33 244`,
  `edges 64 432`, `graph_facts 23 323`, community-таблицы **0/0**.
- Ретенция: удалён `predeploy-258166.db`; сохранены `258167` и `258168` (диск 27G/67G).
- `git checkout -B release/2.58.168 ea9a7141` → `dirty_after=0`, `APP_VERSION = "2.58.168"`.
- `systemctl restart admin_bot` в **2026-11-08T12:11:08Z**; миграций нет
  (`pending=[]`, `user_version=44`, total 0.0s).

## 4. Постдеплойная проверка

| Проверка | Факт |
|---|---|
| SERVER HEAD | `ea9a71415dfbeb9f5363363ab4461e4e2a2a0d2f`, branch `release/2.58.168` |
| `/healthz` локально | `{"status":"ok","version":"2.58.168"}`, 200 |
| `/web/`, `/api/health` | 200, 200 |
| Публично `https://admin-bot.duckdns.org/healthz` | 200, `2.58.168` |
| Публично `/web/` | 200, 1 276 327 б, `2.58.168` — 17, `2.58.167` — 0 |
| Сервис | `active`, `enabled`, **NRestarts=0**, MainPID 3111193 |
| Журнал от рестарта (527 строк) | `Traceback` **0**, `ERROR` **2** (оба — `anticliche_worker` fetch wikipedia, вне релиза), `WARNING` 1 (известный embedding/smart_archive) |
| Строки `memory07|community` в журнале | **0** |
| Регистрация job | `apscheduler: Added job "MemoryMaintenanceService._tick_communities"` |
| Schema | `user_version 44`, `schema_migrations 33`, `quick_check ok`, таблиц 128 |
| `mca_community_builds` / `mca_community_members` | **0 / 0** (сборок не создано) |
| `nodes`/`edges`/`graph_facts`/`smart_messages` | 33 244 / 64 432 / 23 323 / 2 073 960 — как в снимке |
| Served `/web/app.js` | 2 062 901 б, sha256 `495d4882…c3050c6`, `cmp` identical с checkout |

Проверка гейта в проде (standalone, read-only): `env_flag_enabled=False`,
`code_default=False`, каталожный ключ присутствует (`category=flags`, `REGISTRY=598`),
`job_id=memory_communities_build`, а тик при OFF **не делает ни одного SQL**
(подставной объект с падающим `.db` не затронут).

## 5. Измерение на копии БД (read-only, прод не мутировался)

Копия прод-БД через sqlite backup API → `/tmp/m07-measure-258168.db`
(1 742 516 224 б, `user_version 44`, `quick_check ok`, community-таблицы 0/0).
Сборщик вызван на копии с гейтом, принудительно включённым в процессе измерения;
конфиг прода не менялся; после измерения копия удалена.

### 5.1 Сборка

| Чат | nodes | раунд 1, мс | раунд 2, мс | сообществ | членство |
|---|---|---|---|---|---|
| -1002661910336 | 31 552 | 4 553 | 7 054 | 3 613 | 31 550 |
| -1004482340693 | 1 294 | 42 | 86 | 428 | 1 294 |
| 5885953495 | 385 | 15 | 17 | 111 | 385 |
| 1313107079 | 11 | 1.2 | 1.2 | 5 | 11 |
| 529151103 | 2 | 0.7 | 0.8 | 1 | 2 |

- **p50 = 15.1 мс**, **p95 = 7 054 мс** (n=10 сборок); суммарный тик ≈ 4.6 с (раунд 1) / 7.2 с (раунд 2).
- Статусы: все `active`, `error=None`, `unresolved_identity_nodes=[]`, `dropped_links=0`.
- Размеры сообществ: min 2, медиана **2**, max 4 172 (большой чат) / 73 / 38 / 3 / 2.
  Преобладают пары узлов — граф прода фрагментирован.

### 5.2 Провенанс-веса (фактически использованные связи)

| Класс | Кол-во связей | Доля |
|---|---|---|
| confirmed (1.0) | 64 | 0.10 % |
| tentative (0.5) | 22 | 0.03 % |
| legacy (0.25) | 64 346 | **99.87 %** |
| cooccurrence (0.1) | 0 | 0 % |
| всего | 64 432 | = все `edges` |

### 5.3 Подписи

Все проверенные подписи — **нейтральные**: «Сообщество N», `dominant_names=[]`,
basis «сформировано по реальным связям чата: узлов N, связей подтверждённых…».
Доминирующих подписей нет ни в одном чате: правило требует вес от
confirmed/tentative-связей, а таких связей в проде 86 из 64 432.

### 5.4 Стабильность `community_id` (два последовательных пересбора)

| Чат | reused | created | dropped |
|---|---|---|---|
| -1002661910336 | 3 613 | 0 | 0 |
| -1004482340693 | 428 | 0 | 0 |
| 5885953495 | 111 | 0 | 0 |
| 1313107079 | 5 | 0 | 0 |
| 529151103 | 1 | 0 | 0 |

Идентификаторы полностью переиспользованы, дрейфа нет.

### 5.5 Аномалии

**0** (нет сообществ < 2 членов, нет узлов с весом 0, нет дублей членства, нет падений).

### 5.6 Паритет обычного retrieval (те же запросы, та же копия; 34 запроса × 2 режима)

| Сценарий | Идентичных (по порядку) | Отличий | Медиана, мс |
|---|---|---|---|
| A: гейт OFF, сборок нет (базовая линия прода) | — | — | 0.12 |
| A → B: гейт ON, сборок нет (specific / thematic) | 34 / 34 | 0 | 0.12 → 0.12 / 0.10 → 0.20 |
| A → C: гейт ON, сборки есть (specific) | 34 | 0 | 0.12 → 0.10 |
| A → E: гейт OFF, сборки есть (specific / thematic) | 34 / 34 | 0 | 0.12 → 0.15 / 0.10 → 0.10 |
| A → D: гейт ON, сборки есть (thematic) | 9 | 25 | 0.10 → 0.88 |

Вывод: пока сообщества не читаются (гейт OFF либо режим не thematic), обычная выдача
**побайтово та же** и по составу, и по порядку, задержка не меняется. Единственное
ожидаемое отличие — thematic-режим при включённом гейте и наличии активной сборки.

## 6. Покрытие требований

| Строка | Чем закрыта | Статус |
|---|---|---|
| MEMORY-07 build/lifecycle/веса/подписи/стабильность id (волны 3–4) | сборка на реальной копии: 5 чатов, 4 158 сообществ, 0 аномалий, 100 % reuse id | код на проде; гейт OFF |
| MEMORY-07 retrieval-канал | паритет A→B/C/E = 34/34; thematic-вклад только при ON | код на проде; гейт OFF |
| Регистрация фонового job | APScheduler `Added job …_tick_communities`; OFF-тик без SQL; 0 сборок в проде | подтверждено |
| Схема | `user_version 44`, миграций нет, таблицы пусты | подтверждено |
| Эпик-карта | gate release: `inventory=153 manual=146 scoped=146 errors=148`, exit 1 — карта уровня эпика привязана к старому кандидату, чужие строки PENDING | эпик **не DONE** (как и было) |

## 7. Откат

- Кодовый: `git checkout release/2.58.167` (`153063b2`) → `systemctl restart admin_bot`
  (объект на сервере подтверждён, сервис `enabled`).
- Снимок данных: `/tmp/predeploy-258168.db` (read-back ok) и `/tmp/predeploy-258167.db`.
- Схемный откат не нужен: v44-таблицы пусты и при OFF не читаются/не пишутся.
- Независимый бэкап владельца: `WorkspaceData/backups/adminbot-postmigration-2026-10-29/`.

## 8. Рекомендация по включению гейта

Технически включать **безопасно**: OFF-паритет полный (34/34 по составу и порядку),
сборка детерминирована и стабильна (0 created/dropped при повторе), аномалий нет,
стоимость — ~7 с раз в час на самый большой чат, вне горячего пути, и thematic-вклад
в выдачу появляется только при ON.

Ограничение — **продуктовая ценность на текущих данных**: 99.87 % связей имеют класс
`legacy`, поэтому все подписи нейтральные («Сообщество N»), а половина сообществ —
пары узлов. Включать имеет смысл, когда появится подтверждённая провенанс-связность
(confirmed/tentative), иначе пользователь увидит «Сообщество 1/2/3…» без смысловых имён.

Обоснование включения: паритет OFF (A→E 34/34), 0 аномалий, 100 % reuse id,
p95 сборки 7 с при часовом периоде, thematic-диффы только при ON.
