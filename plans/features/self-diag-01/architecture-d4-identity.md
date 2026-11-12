# SELF-DIAG-01 / D4-IDENT — контракт deployed identity и локального snapshot

**Роль:** Architect. **Дата:** 12.11.2026. **Версия контракта: 1.1** (Amendment 1 — уточнение path-правила,
закрытых наборов и схемы манифеста; схема записи остаётся 1). **Область:** только слайс D4 (`SD1-D4-*`, `SD1-SEM-04`,
`SD1-D2-25`, `SD1-D2-29a`, `SD1-AC-03/06/17`). **Предшественники:** `plan.md` §2–§4, `slice-graph.json`
(`D4`, `dependency_decisions`), `requirements-map.json` (19 записей / 18 `req_id` в D4),
`evidence/d1/review-d1-2026-11-12.md` §9, `reports/deploy-2.58.188.md`.

Документ фиксирует **решения**, а не новый план эпика. Карта, `slice-graph.json`, `progress_scope.json`
и код этим документом не меняются; изменения в них вносит PM/Builder по своим процедурам.

---

## 0. Что проверено в репозитории и что осталось неизвестным

Проверено на `release/2.58.197` = `2587616759de31283585ffc105c91e7193c2e89e` (локально, read-only):

| Факт | Доказательство |
|---|---|
| `services/deploy_identity.py` отсутствует | `git ls-tree 25876167 services/` — файла нет |
| `git grep 'deployed_sha\|deploy_identity\|DEPLOY_SHA\|release_manifest'` по `25876167` = 0 совпадений в коде | поиск по дереву коммита |
| `services/source_reader.py` — **единственный** провайдер `GitHubProvider`; расширение предусмотрено `Protocol SourceProvider` (`search_repos/resolve_repo/resolve_commit/list_tree/read_file`) | `25876167:services/source_reader.py:466-485`, `:510`, `:1115-1133` |
| В `SourceReader` **нет** маршрутизации по провайдеру: один `provider` property | `:1129-1133` |
| Декодирование/сниппеты уже общие (`decode_source_bytes`, `build_snippet`, `_verified_url`, `_source_id`) | `:849-1094`, `:2084-2098` |
| `capability_registry` — per-chat реестр способностей с закрытым набором `ready/disabled/not_configured/temporarily_unavailable/quota_exhausted/unsupported/unknown` и TTL-кэшем 60 c | `25876167:services/capability_registry.py:43-70`, ключ `(capability_id, chat_id)` |
| `APP_VERSION` — модульная константа `config/settings.py` (`2.58.197`), отдаётся публичным `/healthz` и `status`/`debug_config` | `config/settings.py:3550`, `web/app.py:361-371`, `services/status_service.py:32,78`, `services/debug_config.py:26,245` |
| Бот — **хостовый** python-процесс systemd `admin_bot` из корня проекта; контейнер только у `telegram-bot-api` | `25876167:docker-compose.yml:1-4`, `AGENTS.md` (VPS `192.255.209.205`, `/var/www/admin_bot`) |
| Реальный деплой = `git fetch/checkout -f -B release/X <sha>` → `dirty_tracked=0` → `systemctl restart admin_bot` → `/healthz` 200 | `reports/deploy-2.58.188.md` §3 |
| `process started_at` и `uptime_seconds` уже есть | `services/status_service.py:75,86,1186,1194` |
| `git status --porcelain` уже используется как источник `dirty_tracked` в релизной отчётности | `reports/deploy-2.58.188.md` §1 (`dirty_tracked=0`) |
| `handlers/checkup.py` и `services/checkup_service.py` — **эксклюзивно D6** | `plan.md` §2/§4 (`serialized_files`) |
| Промпт чекапа неизменяем; данные подаются отдельной секцией user-контента (прецедент `<memory_health>`) | `plan.md` §4; `25876167:services/checkup_service.py:76-100` |
| Существующие evidence-артефакты D-слайсов: `plans/features/self-diag-01/evidence/<slice>/sd1_<req>.json` | `evidence/d1/sd1_d1_01.json` |
| 4 строки D2 в `READY_FOR_LIVE` — `SD1-AMX-08`, `SD1-AC-10`, `SD1-AC-11`, `SD1-AC-14`, все `live_when=postdeploy` | `requirements-map.json` (`additional_requirements`) |

**Неизвестно (не выдумывать):**
1. Реальное содержимое systemd unit и `EnvironmentFile` на прод-хосте — в этом проходе прод не читался.
   Следствие: механизм «env как источник» описан как **резервный**, его активация проверяется на первом
   живом шаге D4-B/C, а не предполагается.
2. Есть ли доступная админ-правка hot-ключа, не зарегистрированного в `services/param_catalog.py`
   (факт: сам `flags.checkup_enabled` в каталоге не зарегистрирован, `hot.get` его читает).
   Следствие: способ «смена repo identity через админку» (`SD1-D4-03`) фиксируется на D4-B после
   проверки на дереве `25876167`, без догадок; минимальный допустимый вариант указан в §2.4.

---

## 1. Решение 1 — источник `deployed_sha`

### 1.1 Итоговый порядок источников

Порядок **фиксирован** и не настраивается (никаких флагов выбора источника):

| Приоритет | Источник | Что даёт | Условие использования |
|---|---|---|---|
| 1 | **release manifest** `<repo_root>/.deploy/release.json` | `deployed_sha`, `deployed_at`, `version`, `effect`, `previous_sha` | файл существует, читается, проходит схему |
| 2 | **`.git` рабочего checkout** (чистое чтение файлов: `HEAD` → ref → `packed-refs`) | `checkout_sha` (всегда) | `.git` доступен и разрешается в 40-hex |
| 3 | **env** `ADMINBOT_DEPLOYED_SHA` (одна переменная, не `.env`) | `deployed_sha` только если манифеста нет | переменная валидна (40-hex) |
| — | image/artifact | **не применимо**: артефакт здесь — сам git checkout; контейнера бота нет | см. §1.4 |

**Правила приоритета.**
- `deployed_sha` = значение манифеста, если манифест валиден; иначе env; иначе `null`.
- env **никогда** не перебивает валидный манифест: манифест пишет тот же шаг, который делал checkout и
  restart, а env может быть унаследован/скопирован. Если валидны оба и **различаются** → `mismatch`
  с `conflict: ["release_manifest", "env"]`, оба значения в записи, ни одно не выбирается молча.
- `checkout_sha` берётся **только** из `.git`, независимо от манифеста и env. Это второй, независимый
  факт; именно его несовпадение с `deployed_sha` даёт `mismatch`.
- `verified_deployed` требует **одновременно**: валидный манифест, `manifest.deployed_sha == checkout_sha`,
  `dirty == false`, совпадение `manifest.version` с `APP_VERSION` **загруженного модуля**, и запуск
  процесса не раньше `manifest.deployed_at` (§1.3).

### 1.2 Release manifest: путь, формат, владелец

**Путь:** `<repo_root>/.deploy/release.json` (внутри checkout, вне `.git`, **не отслеживается git**).
Одна строка `.deploy/` добавляется в `.gitignore` — это единственная правка отслеживаемого файла,
которую влечёт контракт (в write_scope D4 её вносит Builder вместе с манифест-контрактом, отдельным
коммитом «deploy contract», без изменения поведения).

Почему не внутри `.git`: внутренности git не являются внешним контрактом, их формат не наш; `.deploy/`
читается человеком и ops-скриптом, переносится в бэкап конфигурации и переживает `git checkout`
(untracked-файлы checkout не удаляет). Почему не `backups/`: `backups/` — данные БД, не идентичность релиза.

**Формат (schema 1, только эти ключи, закрытый набор):**

```json
{
  "schema": 1,
  "deployed_sha": "2587616759de31283585ffc105c91e7193c2e89e",
  "release_branch": "release/2.58.197",
  "version": "2.58.197",
  "deployed_at": "2026-11-12T20:31:07Z",
  "effect": "deploy",
  "previous_sha": "c087253dd7afdbcfa0c5ee96927324dc349627b2",
  "previous_version": "2.58.188",
  "dirty_tracked": false,
  "schema_version": 47,
  "deployer": "devops"
}
```

- `deployed_sha`, `deployed_at`, `version`, `effect` — обязательны; остальные опциональны.
- `deployed_at` — UTC ISO8601 `...Z`, момент **до** restart (см. §1.3). Другие часовые пояса запрещены.
- `deployer` — роль/идентификатор агента, без персональных данных.
- Значения не содержат секретов, путей хоста, URL с credentials, PID, окружения. `repo_origin` в манифесте
  **не дублируется** (он берётся из `.git/config`/конфигурации SELF-DIAG, §2.4).
- Запись атомарная: `release.json.tmp` → `os.replace` (никогда не частичный JSON), режим `0644`.

**Владелец:** DevOps (deploy-прогон). Это **единственная** новая обязанность пайплайна; второго
deploy-механизма не вводится, `git pull --ff-only`/`checkout` + `systemctl restart` остаются как есть.

### 1.3 Обязательный порядок шагов деплоя (и почему именно такой)

```
1. git fetch origin <release-branch> && git checkout -f -B <release-branch> <sha>
2. git status --porcelain --untracked-files=no  → обязано быть пусто
3. записать .deploy/release.json (deployed_at = сейчас, effect=deploy)   ← ДО restart
4. systemctl restart admin_bot
5. /healthz 200; при провале — откат (шаг 6)
6. откат: git checkout <previous_sha> → restart → записать манифест с effect=rollback,
   deployed_sha=<previous_sha>, previous_sha=<откатываемый sha>
```

Свойство, ради которого манифест пишется **до** restart: если restart не удался или процесс не поднялся,
`process_started_at < manifest.deployed_at` → identity честно уходит в `mismatch`, а не рапортует
«выложено». Окно «манифест записан — сервис ещё старый» длится секунды и разрешается само.

**Откат ничего не требует от кода:** `git checkout <previous_sha>` + restart + перезапись манифеста тем же
атомарным способом. Если манифест переписать не удалось, `HEAD != manifest.deployed_sha` → `mismatch`,
и это правильное поведение (не «тихая ложь»). Отдельного состояния/хранилища истории отката нет:
`effect`+`previous_sha` в той же записи — достаточно, чтобы объяснить «предыдущий релиз».

### 1.4 Image/artifact identity

В этом проекте **нет** образа приложения: бот — хостовый процесс из git-checkout. Поэтому:

- артефакт = дерево checkout на `deployed_sha`; identity артефакта = `checkout_sha` + `dirty == false`;
- `version` (`APP_VERSION` дерева) — человекочитаемая метка того же артефакта, не замена SHA;
- если появится контейнер, идентичность образа задаётся тем же манифестом (`deployed_sha` + digest в
  `effect`-совместимом поле) и **не** новым механизмом; сейчас это не проектируется.

### 1.5 Поведение при отсутствии манифеста

Нет манифеста (текущее состояние прода) → `deployed_sha` берётся из env, если он валиден, иначе `null`;
код — **`local_unverified`** (никогда `verified_deployed`), с отдельным вложенным `local_identity`:
`{checkout_sha, dirty, checkout_mtime, branch, upstream_ref}`. Это прямое требование `SD1-D4-08`
(«не называть строки `verified_deployed_code` до получения доказательства») и `SD1-D4-07`
(«наличие исходников локально ≠ подтверждение тождества»).

Из этого следует: **D4 не блокируется деплой-пайплайном**. Код D4-A в проде без манифеста честно
показывает `local_unverified`; `verified_deployed` включается сам, как только DevOps начнёт писать
манифест. Зависимость регистрируется как `EXT-DEPLOY-MANIFEST` (см. §7.3), а не как Human Gate.

---

## 2. Решение 2 — одна запись identity

### 2.1 Где живёт

**Новый маленький модуль `services/deploy_identity.py`.** `services/capability_registry.py` в D4
**не расширяется** и остаётся без изменений. Причины (проверены по коду):

1. **Гранулярность.** `capability_registry` кэширует по `(capability_id, chat_id)` — identity процесса
   одинакова для всех чатов; ключ-по-чату размножил бы один факт на N копий и дал бы расхождения между
   чатами ровно того класса, который запрещает `SD1-D4-06`.
2. **Словарь статусов.** Закрытый набор `ready/disabled/not_configured/temporarily_unavailable/
   quota_exhausted/unsupported/unknown` не выражает `verified_deployed|mismatch`; пришлось бы придать
   `ready` второе значение — это и есть «параллельная машина состояний».
3. **TTL 60 c.** Кэш реестра отдавал бы старый `deployed_sha` сразу после деплоя — то есть показывал бы
   выложенной ревизию, которая уже не выложена.
4. **Смысл контракта.** Реестр отвечает «можно ли пробовать инструмент X в этом чате», identity отвечает
   «какая ревизия исполняется». Смешение не даёт D6 показать два независимых факта раздельно
   (`SD1-D4-05`: `repo_origin`, `deployed_sha`, `local_source_verification`, `upstream_head` — раздельно).

`capability_registry.py` остаётся в write_scope D4 как **резерв**; если он не тронут, D4 это фиксирует
явно (не «молчаливое» изменение).

### 2.2 Поля единственной записи (закрытая схема, версия 1)

```json
{
  "schema": 1,
  "code": "verified_deployed | local_unverified | mismatch | unknown | unavailable",
  "reason": "<закрытый код причины, см. ниже>",
  "repo_origin": "Henry-Case-dev/adminbot",
  "deployed_sha": "2587616…|null",
  "checkout_sha": "2587616…|null",
  "dirty": false,
  "upstream_head": {"sha": "…|null", "ref": "refs/remotes/origin/release/2.58.197", "observed_at": "…|null"},
  "version_provenance": {"runtime": "2.58.197", "manifest": "2.58.197", "consistent": true},
  "local_source_verification": "verified_deployed | local_unverified | unknown",
  "artifact": {"kind": "git_checkout", "release_branch": "release/2.58.197", "schema_version": 47},
  "deployed_at": "2026-11-12T20:31:07Z|null",
  "observed_at": "2026-11-12T20:44:10Z",
  "sources": ["release_manifest", "git_head", "git_cli", "env", "runtime_app_version", "process_start"],
  "conflict": ["release_manifest", "env"],
  "local_identity": {"checkout_sha": "…", "dirty": false, "checkout_mtime": "…", "branch": "release/2.58.197"}
}
```

Правила:
- `dirty` — `true|false|null` (`null` = не удалось определить: нет `git`, таймаут, ошибка → код не может быть
  `verified_deployed`).
- `upstream_head` **никогда** не требует сети: берётся локальный `refs/remotes/origin/<branch>` (и
  `packed-refs`), `observed_at` = mtime этого ref-файла. `stale`-эвристик не вводим: возраст известен
  потребителю по `observed_at`. Нет ref → `sha: null`, причина `no_remote_ref`.
- `version_provenance.runtime` = `config.settings.APP_VERSION` **загруженного** модуля (факт о том, что
  импортировано в процесс), `manifest` — из манифеста. Расхождение = `mismatch`.
- `local_source_verification` — **производное** поле (`code` + `dirty`), не четвёртое состояние:
  `verified_deployed` если `code=verified_deployed`, иначе `local_unverified` при известном
  `checkout_sha`, иначе `unknown`.
- `repo_origin` — `owner/name` без схемы и без userinfo; если URL содержал credentials, они **вырезаются**
  до попадания в запись (`SD1-D2-29a`).
- Запись не содержит: абсолютных путей хоста, значений env целиком, токенов, PID, списка файлов.

### 2.3 Коды и причины (закрытые наборы)

| `code` | Когда | `local_source_verification` |
|---|---|---|
| `verified_deployed` | манифест валиден ∧ `deployed_sha == checkout_sha` ∧ `dirty=false` ∧ версия совпала ∧ процесс не старше манифеста | `verified_deployed` |
| `local_unverified` | checkout известен, но доказательства тождества нет: нет манифеста, `dirty=true/null`, нет `process_start` | `local_unverified` |
| `mismatch` | источники расходятся: манифест≠HEAD, манифест≠env, версия≠манифест, процесс старше манифеста | `local_unverified` |
| `unknown` | осмотр возможен, но значение не определено: нет `.git`, битый/неполный манифест, неразрешённый ref, `gitdir` недоступен, отказ по политике путей | `unknown` |
| `unavailable` | осмотр невозможен: `repo_root` отсутствует/не каталог, ошибка доступа/IO | `unknown` |

Причины: `no_manifest`, `manifest_invalid_json`, `manifest_incomplete`, `manifest_sha_invalid`,
`no_git`, `gitdir_unavailable`, `head_unresolved`, `dirty_unknown`, `git_unavailable`, `git_timeout`,
`sha_conflict`, `version_conflict`, `process_predates_deploy`, `no_remote_ref`, `root_missing`,
`root_not_dir`, `permission_denied`, `path_denied`, `""` (для `verified_deployed`).

`unknown` и `unavailable` **не** взаимозаменяемы: `unknown` = «посмотрели, не смогли определить»,
`unavailable` = «посмотреть нельзя».

### 2.4 `repo_origin` (канонический repo identity) — `SD1-D4-03`, `SD1-AC-06`

- Источник значения: (1) `[remote "origin"] url` из `.git/config` — нормализуется до `owner/name`
  (с обрезкой userinfo/схемы/`.git`); (2) если remote отсутствует — значение конфигурации SELF-DIAG.
- Значение по умолчанию: `Henry-Case-dev/adminbot` (из ТЗ, `SD1-AC-06`).
- Смена — **только** явной настройкой владельца через существующую админ-поверхность конфигурации,
  с записью события смены (`self_diag.repo_identity_changed`: старое, новое, кто). Никаких «выводов»
  repo identity из текста сообщения, README или памяти модели (прямой запрет `SD1-D4-03`).
- Не секрет: отображается в админке как обычный идентификатор; в промпт/чат уходит только как
  человекочитаемое имя без токенов.
- Механизм конкретной настройки (hot-ключ `self_diag.repo_url` + заводской дефолт в модуле, либо запись
  `param_catalog`) определяется на старте D4-B после проверки на дереве `25876167`: факт из §0 — ключи
  `flags.*` работают без записи в каталоге, но видимость в админ-UI может требовать записи каталога.
  Минимальный допустимый вариант — существующий hot-слой + одна запись каталога (без новой БД/стора).

### 2.5 Единственный потребитель для D6

- **Одна функция**: `deploy_identity.collect_identity(repo_root, *, process_started_at=None)` — синхронная,
  только чтение, без сети, без shell.
- **Один шов данных**: D6 добавляет объект в уже аутентифицированную поверхность статуса
  (`GET /api/status` → поле `deploy_identity`, либо `GET /api/status/deploy-identity` при необходимости
  отдельного кэша) — один маршрут, один вызов. `web/app.py:/healthz` **не меняется** (см. §4.3).
- **Никакой второй машины состояний**: D6 не хранит свою копию SHA, не кэширует дольше запроса, не
  сравнивает SHA сам — только отображает `code`/поля. Любой новый потребитель обязан импортировать
  `collect_identity`, а не переписывать чтение `.git`/манифеста.

---

## 3. Решение 3 — доверие локальному snapshot (`source_reader`)

### 3.1 Два провайдера, один протокол, один порядок

`SourceReader` расширяется **вторым** провайдером, реализующим уже существующий `Protocol SourceProvider`
(`25876167:services/source_reader.py:468-485`): `LocalSnapshotProvider` (`name = "local_snapshot"`).
Никакого рефакторинга `GitHubProvider`, никакого второго `SourceReader`, никакого нового инструмента
(сигнатура `read_source_code` не меняется — `SD1-D4-01`, `SD1-D4-04`).

Порядок для **своего** репозитория (`SD1-D4-07`):

1. если `collect_identity(...).local_source_verification == "verified_deployed"` → читаем локальный
   snapshot, ссылка коммит-пиннится на `deployed_sha` (источник честно = «проверенная локальная копия»);
2. иначе → локальный snapshot **всё ещё разрешён**, но ответ помечается `local_unverified`
   (в `provenance` и в человекочитаемой строке), и если доступен GitHub — допускается commit-pinned
   чтение **того же** SHA как второе подтверждение;
3. если ни локального, ни пина нет → честный `not_checked`/`error` с причиной, без догадок (`SD1-AC-03`).

Для **сторонних** репозиториев поведение не меняется вообще: обычный `GitHubProvider` по явному
repo/ref (`SD1-D4-01`, `SD1-SEM-04`, `SD1-AC-17`). Канонический repo identity **никогда** не подставляется
в чужой вопрос: локальный провайдер выбирается только при точном совпадении `owner/name` с
`repo_origin` (или для вопроса «про себя», где repo не указан явно).

### 3.2 Локальное чтение без исполнения

Провайдер только читает байты и отдаёт их в **уже существующий** конвейер (`decode_source_bytes`,
`split_lines`, `build_snippet`, `_source_id`). Запрещено в этом пути: `import`/`exec`/`eval` файлов
из репозитория, `subprocess` любого содержимого репозитория, загрузка `.pyc`, вызов git-хуков,
раскрытие значений из файлов. Файл — это текст, а не код для запуска (`SD1-D4-12`).

Обязательные ограничения чтения:
- путь нормализуется и обязан остаться **внутри** `repo_root` после `realpath` (никаких `..`, абсолютных
  путей, симлинков, выводящих наружу, иных ФС-корней);
- `.git/` **не читается** через `read_source_code` (кроме отдельных узких чтений identity, которые
  не отдают содержимое objects/config наружу);
- размер файла ограничен существующим `SOURCE_READ_MAX_FILE_BYTES`, карта — существующими лимитами
  `SOURCE_READ_MAX_FILES/DEPTH/REQUESTS`; новых квот не вводится;
- ссылка на источник для локального чтения — **repo-relative и commit-pinned**:
  `repo://adminbot@<sha>/services/x.py#L10-L20`; абсолютные пути хоста в ссылки/трейсы не попадают.

### 3.3 Denylist путей (единый, обязательный для всех scope)

Канонический предикат — **один** на проект (живёт рядом с identity, `path_is_denied(rel_path)`; D4-B
импортирует его и не дублирует список). Совпадает с фактическим `.gitignore` `25876167` (проверено):

```
.env, .env.* (кроме .env.example), *.pem, id_rsa*, id_ed25519*,
*credentials*, *secret*, *.key, *.p12,
backups/, *.db, *.db-wal, *.db-shm, pre_migration_*.db, local_database.db,
deploy_commands.txt, deploy_*.py, deploy_result.json, check_remote_bot.py,
*cookies*, media/*cookies*, chrome-profile/, bot-chrome-profile/,
migrate_history/, logs/, *.log, .git/
```

Семантика: отказ **независимо от scope/прав** (`SD1-D2-25`), ответ — закрытый код отказа
(`path_denied`), без намёка на содержимое и без подтверждения существования файла. Безопасные поля
конфигурации берутся через typed settings/hot-слой, а не чтением `.env`.

### 3.4 `local_unverified` — что это значит практически

- Разрешено: показать файл и строки, явно сказав «это локальная копия, тождество исполняемой ревизии не
  подтверждено», с `checkout_sha` и `dirty`.
- Запрещено: называть такой ответ «кодом работающего экземпляра», винить commit из этого дерева
  (`SD1-D4-06`/`SD1-D4-14`) или выдавать `local_unverified` за `verified_deployed_code`.
- Если `dirty=true`, дополнительно помечается, что рабочее дерево изменено после релиза.

---

## 4. Решение 4 — шов D6 (без реализации в D4-A)

### 4.1 Вызов на каждый explicit чекап (`SD1-D4-09`)

`handlers/checkup.py` (владение D6) на каждый **explicit** чекап (bare «чекап»/префикс-триггер, т.е.
существующие точки входа после гейта `flags.checkup_enabled` и `_checkup_diagnostic_gate`) вызывает:

1. `deploy_identity.collect_identity(repo_root, process_started_at=status.started_at)`;
2. `deploy_identity.recent_commits(repo_root, limit=5, basis=deployed_sha|HEAD)`.

Бюджет: не более **3** узких вызовов git на чекап (`status --porcelain`, `log`, `rev-list` — последние
два не нужны, если базис `deployed_sha`), фиксированный `limit≤5`, таймаут 3 c на вызов, **без сети**,
без обхода дерева репозитория и без diff без потребности. Вне чекапа identity не вызывается (никакого
фонового опроса, планировщика, кэша).

Факт попытки обязан быть наблюдаемым: одна существующая структурная строка лога
`[checkup] identity | code=… | deployed_sha=… | checkout_sha=… | dirty=… | calls=… | ms=…` — она и есть
live-доказательство `SD1-D4-09` (trace чекапа + уложившийся бюджет).

### 4.2 Корреляция traceback с deployed SHA (`SD1-D4-10`, `SD1-D4-14`)

В user-контент чекапа (по прецеденту секции `<memory_health>`, **не в системный промпт**) добавляется
секция данных с: `code`, `deployed_sha`, `checkout_sha`, `dirty`, `deployed_at`, `version_provenance`,
и списком `recent_commits` с явным флагом `deployed: true|false`.

Инвариант: коммит, не достижимый из `deployed_sha`, помечается `deployed: false` и **не может** быть
назван виновным; при `local_unverified`/`mismatch` секция прямо говорит «сверка с исполняемой ревизией
не подтверждена». Время событий логов сопоставляется с `deployed_at`; изменения «между релизами»
ограничиваются коммитами до `deployed_sha` включительно.

Жёсткие границы: `prompts.checkup_system_prompt` и его активная ревизия не меняются байт-в-байт
(AC-09/`SD1-D6-03`); стиль/характер чекапа не трогается (`SD1-GRAL-02`); D4 не правит
`handlers/checkup.py`, `services/checkup_service.py` — это D6.

### 4.3 Видимость (D6 UI) и `/healthz`

- `deployed_sha` уходит в **аутентифицированную** админ-поверхность как non-secret (`SD1-AC-06`), под
  существующей policy-классификацией `bot_server_state` (класс уже используется чекапом) — новый класс
  прав не вводится.
- Публичный `/healthz` **не расширяется**: остаётся `{status, version}`. Причина: SHA исполняемой
  ревизии — сведения о раскладке уязвимостей, а не health-статус; публичная диагностика уже покрыта
  `version`.
- Публичному пользователю (если строка вообще показывается) доступны `version` и
  `local_source_verification`, но не SHA.

---

## 5. Минимальный слайс D4-A (Builder)

### 5.1 Что именно делается

**Файлы:** `services/deploy_identity.py` (новый), `tests/test_deploy_identity.py` (новый).
Больше ничего. Ни `source_reader.py`, ни `capability_registry.py`, ни `handlers/*`, ни
`config/settings.py`, ни `web/*`, ни `.gitignore` (последний меняется только вместе с манифест-контрактом,
см. §7.4).

**Публичный API (ровно это, версия схемы 1):**

```python
CODES = ("verified_deployed", "local_unverified", "mismatch", "unknown", "unavailable")

def collect_identity(repo_root: str | os.PathLike | None = None, *,
                     process_started_at: datetime | None = None) -> dict
    """Единственная запись identity. Только чтение, без сети и без исполнения кода репозитория."""

def recent_commits(repo_root=None, *, limit: int = 5, basis: str = "deployed") -> dict
    """Ограниченная выборка последних коммитов; записи вне basis помечаются deployed=false."""

def path_is_denied(rel_path: str) -> bool
    """Единый предикат запрещённых путей (§3.3). Один на проект, без копий."""

DEFAULT_REPO_ORIGIN = "Henry-Case-dev/adminbot"
MANIFEST_REL_PATH = ".deploy/release.json"
```

Правила реализации (обязательны к ревью):
- `collect_identity` **никогда не бросает**: любая беда → `code` + `reason` (§2.3); не `None`.
- Все чтения — только внутри `repo_root` после `realpath`; симлинк `.git` и `gitdir` вне допустимого
  каталога → `unknown/path_denied|gitdir_unavailable` (§2.3).
- Чтение `HEAD`: файл → `packed-refs`; ничего больше (без сети, без `git`).
- `git` вызывается только фиксированным argv (`["git", "-C", root, "-c", "core.fsmonitor=false",
  "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all"]`), `shell=False`,
  таймаут 3 c, без наследования произвольного env, без `fetch/pull/ls-remote`.
  Нет git/таймаут → `dirty=null`, `reason=git_unavailable|git_timeout`, код не `verified_deployed`.
- Env читается **только** точечно (`os.environ.get("ADMINBOT_DEPLOYED_SHA")`), окружение целиком
  не перечисляется и не логируется.
- В `repo_origin` вырезаются userinfo/токены; ни один секрет не попадает в запись и в лог.
- Никакого кэша, глобального изменяемого состояния, планировщика, БД.

### 5.2 Обязательные тесты (`tests/test_deploy_identity.py`)

Герметично: `tmp_path` + рукописные `.git`-структуры; для `dirty` — `git init` в `tmp_path` (локально,
без сети), при отсутствии git-бинаря тест пропускается явным `skipif` с причиной.

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | `.git` есть, манифеста нет | `code=local_unverified`, `reason=no_manifest`, `deployed_sha is None`, `checkout_sha` заполнен, `local_source_verification=local_unverified` |
| 2 | манифест `deployed_sha` ≠ git HEAD | `code=mismatch`, `reason=sha_conflict`, **оба** SHA в записи |
| 3 | грязное дерево (изменён отслеживаемый файл) при совпадающих манифесте и HEAD | `code=local_unverified`, `dirty=true` (никогда `verified_deployed`) |
| 4 | нет `.git` (просто каталог файлов) | `code=unknown`, `reason=no_git`, `checkout_sha is None` |
| 5 | битый JSON в манифесте | `code=unknown`, `reason=manifest_invalid_json`, текст ошибки не содержит путей/значений файла |
| 6 | `.git` — симлинк наружу; `gitdir:` вне допустимого корня | `code=unknown`, `path_denied`/`gitdir_unavailable`, чтение не выполнено |
| 7 | denylist: `.env`, `.env.local`, `backups/db.sqlite`, `*.db`, `*.pem`, `deploy_commands.txt`, `cookies.txt`, `.git/config` | `path_is_denied(...) == True` для каждого; разрешены `.env.example`, `services/deploy_identity.py`, `tests/test_x.py` |
| 8 | «код из репозитория не исполняется» | файл-ловушка в `tmp_path` (модуль, пишущий маркер при импорте/`exec`) после `collect_identity`/`recent_commits` маркера **нет**; подменённый `sys.modules`/`subprocess` не содержит содержимого репозитория |
| 9 | манифест совпал, `dirty=false`, `process_started_at > deployed_at` | `code=verified_deployed`, `local_source_verification=verified_deployed`, `reason=""` |
| 10 | манифест совпал, но процесс старше `deployed_at` | `code=mismatch`, `reason=process_predates_deploy` |
| 11 | нет `repo_root` / путь — файл | `code=unavailable`, `reason=root_missing|root_not_dir`, без исключения |
| 12 | `recent_commits(limit=0|100)` и `basis` без SHA | кламп `1..5`, `code`/`reason` вместо исключения, `deployed=false` у коммитов вне базиса |
| 13 | манифест валиден, но `version` не равна runtime `APP_VERSION` | `code=mismatch`, `reason=version_conflict` |
| 14 | env-фолбэк: манифеста нет, `ADMINBOT_DEPLOYED_SHA` валиден | `deployed_sha` из env, `sources` содержит `env`, код не выше `local_unverified` |

Отдельно проверяется **негатив по утечкам**: полный JSON записи (все коды/причины) не содержит
подстрок секретов из подготовленного `tmp_path/.env` и абсолютных путей хоста за пределами
`repo_origin`/repo-relative ссылок.

### 5.3 Чего D4-A НЕ включает (и почему)

| Не входит | Почему |
|---|---|
| Реализация локального провайдера `source_reader` | D4-B: требует маршрутизации провайдера в `SourceReader` и проверки, что GitHub-путь не регрессировал (`SD1-AC-17`) — отдельный проверяемый шаг |
| Изменения `handlers/checkup.py`, `checkup_service.py` | Эксклюзивное владение D6 (`plan.md` §2/§4); D4 не имеет права писать туда |
| Настройка `repo_origin` в админке + событие смены | D4-B/C: нужна проверка фактического механизма на дереве (§2.4), в D4-A её нет |
| D3 (collector/probes) и D5 (prompt readback) | Отдельные слайсы с собственными write_scope |
| Live-проверки (`SD1-D4-09`, `SD1-AC-03`, `SD1-AC-17`), реальный контейнер/прод | D4-A — чистая функция + тесты; live требует выкладки и реального чекапа (D4-C/D6/D7) |
| Манифест на прод-хосте | Обязанность DevOps (§7.3), не код слайса; до неё прод честно в `local_unverified` |

---

## 6. Инварианты и семантика отказов (сводно)

1. `deployed_sha` без манифеста не считается подтверждённым; локальная копия максимум `local_unverified`.
2. Никакое одиночное согласие источников не даёт `verified_deployed`: нужны манифест **и** HEAD **и**
   чистоту **и** версию **и** порядок запуска.
3. `HEAD` никогда не выдаётся за исполняемую ревизию — по построению (`disabled`/`local_unverified`).
4. Отказы закрыты кодами; исключения наружу не выходят; «пустой» ответ вместо кода запрещён.
5. Секреты, `.env`, backup/dump, `.git` objects, полное окружение — не читаются и не выдаются ни при каком
   scope; в записи/трейсах/ссылках секретов нет (`SD1-D2-25`, `SD1-D2-29a`).
6. Ровно одна запись identity и одна функция-источник; второй SHA-парсер, второй кэш и вторая машина
   состояний запрещены.
7. Деплой/откат остаются `git checkout` + `systemctl restart`; новый deploy-механизм не вводится.
8. Никаких фоновых проверок: identity считается по запросу (explicit чекап / админ-запрос).

---

## 7. Зависимости, порядок и release-gate

### 7.1 `D4 depends_on D2` — снять жёсткое ребро

Факты: D2 принят (`Approved` на `02e9d301`, выложен `c087253d`; в проде байт-в-байт), строки D4 и D2
не пересекаются ни по файлам, ни по политике:

- D4-A файлы: `services/deploy_identity.py`, `tests/test_deploy_identity.py` — пересечение с D2 = 0;
- 4 строки D2 в `READY_FOR_LIVE` (`SD1-AMX-08`, `SD1-AC-10`, `SD1-AC-11`, `SD1-AC-14`) — `live_when=postdeploy`,
  т.е. ожидание реальных живых событий по **коду D2**, который уже выложен; они не содержат кода и не
  меняют контракт, на который опирается D4-A.

Поэтому — как в `DEP-D2-D1-2026-11-11`: это **ordering + writer-сериализация**, не prerequisite приёмки.
Предлагаемая запись (применяет PM, не Architect):

```json
{
  "id": "DEP-D4-D2-2026-11-12",
  "slice": "D4",
  "previous_depends_on": ["D2"],
  "decision": "не prerequisite — ordering",
  "ruling": "Код D2 принят и выложен; 4 READY_FOR_LIVE строки D2 — postdeploy-ожидание живых событий по уже выложенному коду и не содержат работ для D4. Жёсткое ребро D4 -> D2 снимается; порядок остаётся объявлением работ.",
  "evidence": [
    "write_scope D4 (services/deploy_identity.py, services/source_reader.py, services/capability_registry.py, tests/test_deploy_identity.py) и D2 (roles/access/telegram_role_check/diagnostic_policy/output_projection/tool_router/checkup/handlers/web-api) — общих путей 0",
    "D2 принят на 02e9d301 и выложен c087253d (reports/deploy-2.58.188.md), файлы среза байт-в-байт",
    "4 READY_FOR_LIVE строки D2 имеют live_when=postdeploy; это наблюдение живого поведения, а не изменение кода или контракта"
  ],
  "consequences": "Выпуск D4-A не требует VERIFIED по 4 postdeploy-строкам D2. Сами строки остаются READY_FOR_LIVE честно.",
  "revalidation": "Если D4 начнёт менять файлы D2 или политику выдачи (services/*policy*, handlers/checkup.py, services/tool_router.py), ребро возвращается на время этих правок."
}
```

В `slice-graph.json` минимум изменений: `slices[D4].depends_on: []` + запись выше; `dependency_order`
дополняется фразой «D2 -> D4 как порядок работ». Пока PM это не применил, ребро D4→D2 остаётся
формально, но **не блокирует** исполнение D4-A: зависимость касается выпуска, а не разработки.

### 7.2 Release-gate D4-A

- Гейт слайса считает только строки D4: `SD1-AC-03`, `SD1-AC-06`, `SD1-AC-17`, `SD1-D4-01/03/04/05/06/07/08/09/10/12/13/14`,
  `SD1-SEM-04`, `SD1-D2-25`, `SD1-D2-29` (19 записей / 18 `req_id`; `SD1-D2-29` закрывается вместе с
  29b в D6 — при закрытии D4-A строка обязана остаться `PENDING` с явной пометкой «ждёт 29b»).
- Строки D2 в `READY_FOR_LIVE`, строки D1/D0/D3/D5/D6/D7 в гейт D4-A **не входят**.
- D4-A закрывает своим доказательством те строки, которые проверяются чистой функцией и тестами:
  `SD1-D4-05` (раздельные поля + отсутствие подмены), `SD1-D4-06`, `SD1-D4-07` (частично: семантика
  `local_unverified`), `SD1-D4-08`, `SD1-D4-12` (часть «не исполнять»), `SD1-D2-25` (denylist-предикат),
  `SD1-D2-29a` (часть «нет секретов в записи/ссылках»).
- Остальные строки D4 требуют D4-B (провайдер/конфиг) и D4-C/D6 (живой чекап) и остаются `PENDING`
  до своих доказательств — это не дефект D4-A.

### 7.3 Внешняя зависимость (не Human Gate)

`EXT-DEPLOY-MANIFEST` — DevOps обязанность: запись `.deploy/release.json` по §1.2–§1.3 в штатном
деплой-прогоне. Влияет на: `SD1-D4-05`, `SD1-D4-06`, `SD1-D4-08`, `SD1-AC-06` в части «подтверждён
`deployed_sha` работающего экземпляра». До её появления прод показывает `local_unverified` — состояние
честное и допустимое (`SD1-D4-08` прямо это предписывает). Она **не блокирует**: разработку D4-A,
ревью D4-A, выкладку D4-A и независимую работу других слайсов; блокирует только переход
`local_unverified → verified_deployed` в проде. Это записывается строкой в `external_dependencies`,
без вопроса владельцу (решение техническое, реализуемое агентом-DevOps).

### 7.4 Release-механика (существующая, без изобретений)

Релиз D4-A идёт обычным путём: ветка-кандидат от `release/2.58.197` (`25876167`), порт на текущий прод,
bump `APP_VERSION` + пины версии (26 файлов — существующая практика, `reports/deploy-2.58.188.md` §1),
`git checkout -f -B release/<new> <sha>`, `systemctl restart`, `/healthz` 200, запись `.deploy/release.json`
(если DevOps уже её внедрил). Версия-пины и `.gitignore` не входят в ревью-объём логики D4-A.

---

## 8. Параллельность и риски

**Классификация:**

- `services/deploy_identity.py`, `tests/test_deploy_identity.py` — `PARALLEL_SAFE` (новые файлы, пересечение 0)
  с D3 — как и записано в `plan.md` §2 (не более двух writes: D3 и D4).
- `services/source_reader.py` — `SERIALIZE` внутри D4 (только D4-B; другие слайсы файл не трогают).
- `services/capability_registry.py` — `READ_ONLY_PARALLEL` (в D4 не меняется).
- `handlers/checkup.py`, `services/checkup_service.py` — `READ_ONLY_PARALLEL` для D4, writer — D6.
- `config/settings.py`, `bot.py`, `web/app.js` — `BLOCKED_BY:D1` только на время правок D1; в D4-A не нужны.
- `web/api/routes.py`, `web/index.html` — writer D6, D4 не пишет.

**Риски:**

| Риск | Уровень | Что делаем |
|---|---|---|
| Identity трактуется как «доказанная ревизия» при отсутствии манифеста | R2 | Жёсткое правило §1.5 + тест 1; `verified_deployed` недостижим без манифеста |
| Расхождение источников маскируется | R1 | `mismatch` с обоими SHA, `conflict` перечисляет источники; тесты 2/13 |
| Чтение локального snapshot обходит запрет на `.env`/бэкапы | R1 | Единый `path_is_denied` + тест 7 + отказ независимо от scope |
| `git`-вызов в hot-path | R1 | Только explicit чекап/админ-запрос, 3 c таймаут, ≤3 вызова, без сети; тест 12 (кламп лимитов) |
| Ложное «выложено» после неудачного restart | R2 | Порядок §1.3 + `process_predates_deploy` (тест 10) |
| Дублирование парсера SHA/манифеста в D6 | R2 | §2.5: один потребитель, один вызов; новый парсер = отклонение ревью |
| Регрессия сторонних репозиториев при добавлении локального провайдера | R2 | D4-B: GitHub-путь не меняется; `SD1-AC-17` проверяется отдельно |

**Откат:** слайс аддитивен (новый модуль + тесты). Откат = `git checkout` предыдущего SHA + restart;
identity при этом автоматически уходит в `local_unverified`/`mismatch`, данных и схемы не трогает
(ΔDDL=0, миграций нет, флагов нет).

---

## 9. Что считается доказательством (без владельца в роли QA)

| Строка | Доказательство | Слайс |
|---|---|---|
| `SD1-D4-05/06/07/08/12(часть)`, `SD1-D2-25`, `SD1-D2-29a(часть)` | зелёные тесты 1–14 (`tests/test_deploy_identity.py`) + наблюдаемый JSON записи в артефакте `evidence/d4/sd1_*.json` (существующий формат) | D4-A |
| `SD1-D4-01/03/04/13`, `SD1-SEM-04`, `SD1-AC-06`, `SD1-AC-17` | тесты провайдера/маршрутизации + `AC-17`: реальный GitHub-прогон discovery/locate/read стороннего репозитория без изменений | D4-B |
| `SD1-D4-09`, `SD1-AC-03` | trace живого explicit чекапа: строка `[checkup] identity | …` + факт чтения файла/строк и бюджет вызовов | D4-C/D6 |
| `SD1-D4-10/14` | тест корреляции: коммит вне `deployed_sha` помечен `deployed=false` и не называется виновным; `deployed_at` участвует в сопоставлении | D4-B/C |
| `EXT-DEPLOY-MANIFEST` | `local_unverified → verified_deployed` на проде после первого деплоя с манифестом (агентская проверка HTTP/лога, не владелец) | DevOps |

Ревью D4-A: три обязательные опоры — (1) личное чтение изменённого пути `collect_identity` и
отсутствия исполнения кода репозитория; (2) чтение ассертов тестов и проверка, что они падают при
поломке контракта (например, тест 3 при возврате `verified_deployed` на грязном дереве); (3) независимый
контрпример — манифест и HEAD совпадают, но `dirty=true` **или** процесс старше `deployed_at`, и запись
обязана быть не `verified_deployed`.

---

## 10. Вердикт и первое задание Builder

**Вердикт для D4-A: `ARCH_REUSE_CONFIRMED`.**

Контракт заморожен этим документом; новых архитектурных решений, хранилищ, сервисов, планировщиков и
согласований не требуется. Всё строится на существующем: git-checkout + systemd restart + `/healthz` +
существующий `SourceProvider`/`decode_source_bytes`, существующий hot/settings слой, существующие тесты и
формат evidence. Единственная новая внешняя обязанность — запись `.deploy/release.json` силами DevOps
(`EXT-DEPLOY-MANIFEST`), и она не блокирует разработку, ревью и выкладку D4-A.

**Точное первое задание Builder:**

> Slice D4-A. База — `release/2.58.197` = `2587616759de31283585ffc105c91e7193c2e89e` (не `master`: в нём
> нет `services/source_reader.py`), worktree через `tools/workflow_housekeeping.py worktree-path` +
> `git worktree add` + `register-worktree`.
> Создать `services/deploy_identity.py` с API §5.1 (`collect_identity`, `recent_commits`, `path_is_denied`,
> `DEFAULT_REPO_ORIGIN`, `MANIFEST_REL_PATH`), кодами/причинами §2.3, полями §2.2, правилами чтения §3.2–§3.3
> и инвариантами §6 — без сети, без shell, без исполнения кода репозитория, без кэша.
> Создать `tests/test_deploy_identity.py` со сценариями 1–14 §5.2 (герметично, `tmp_path`).
> Ничего больше не менять: ни `source_reader.py`, ни `capability_registry.py`, ни `handlers/*`,
> ни `config/settings.py`, ни `web/*`, ни `.gitignore`, ни карту/граф/`progress_scope`.
> Прогнать `pytest tests/test_deploy_identity.py` на кандидате и приложить JSON-артефакты
> `evidence/d4/sd1_d4_05..08.json` (существующий формат, `claimed_verified=false`).
> Handoff: SHA кандидата, число тестов, перечень строк, которые D4-A реально закрывает (§7.2), и явный
> список оставшихся `PENDING` с указанием слайса-владельца.

Housekeeping: этот проход не создавал временных артефактов вне прочитанных файлов; рабочее дерево не
изменялось, кроме этого документа.

---

## Amendment 1 — уточнение path-правила, закрытых наборов и схемы манифеста

**Дата:** 12.11.2026. **Основание:** независимое ревью `673fa0e6` (доки `393064d8`), блокеры B1–B3.
Решения §1.1 (manifest→git→env), §1.5 (`local_unverified` без манифеста), §2.2 (пять условий
`verified_deployed`), §2.5 (один потребитель), §3.2 (без shell/сеть/`.env`/бэкапов, без исполнения кода
репозитория), шов `process_started_at`, кламп `recent_commits` 1..5, запрет кэша/записи **в силе без
изменений**. Риск `.gitignore:7` (packaging) остаётся BACKLOG/D4-B и контрактом не является.
Схема записи остаётся **1**; версия контракта — 1.1.

### B1. Правило путей (закрытое, вместо §3.3-списка по basename)

Нормализация `rel_path`: `\`→`/`, разбить по `/`, отбросить `""` и `.`; `..`, абсолютный путь, буква
диска, пустая/нестроковая строка → **denied**. Для каждого компонента: `c = part.strip().lower()`;
для сравнения точных имён `ct = c.rstrip(". ")` (Windows-алиасы вида `.env.`).

Deny, если выполняется **любое**:
1. любой компонент `== ".git"`;
2. любой компонент **содержит** одну из подстрок: `credential`, `secret`, `cookie` — **на любой глубине**
   (покрывает `config/credentials/…`, `config/secrets/…`, `media/cookies/…`); подстроки `token` в наборе
   **нет** (ложные срабатывания на `tokenizer.py` и подобных исходниках);
3. любой компонент входит в `{backups, logs, migrate_history, chrome-profile, bot-chrome-profile}`;
4. basename (`ct`) совпадает с набором: `.env`, `.env.*` (кроме ровно `.env.example`), `*.pem`, `*.key`,
   `*.p12`, `id_rsa*`, `id_ed25519*`, `*.db`, `*.db-wal`, `*.db-shm`, `pre_migration_*.db`,
   `local_database.db`, `*.log`, `deploy_commands.txt`, `deploy_result.json`, `check_remote_bot.py`;
5. basename совпадает с `deploy_*.py` — **на любой глубине** (покрывает `services/deploy_evil.py`).
   Единственное исключение, точное совпадение полного пути: `services/deploy_identity.py` (self-read кода
   модуля). Исключение не расширяется на другие каталоги, подкаталоги и варианты регистра пути.

`True` = отказ; симлинк/выход за корень по-прежнему отвергаются отдельно (`_within`/`realpath`), поэтому
правило покрывает только лексику пути и не заменяет проверку `realpath`. Минимальная правка Builder:
в существующем `path_is_denied` проверять подстроки и denied-dirs по **всем** компонентам (сейчас только
basename) и убрать ограничение `len(parts) == 1` у `deploy_*.py`; новый модуль не создаётся.
Консервативные ложные срабатывания (`docs/secret-management.md`) — намеренное поведение, не дефект.

### B2. Закрытые наборы: решение по каждому лишнему элементу

`REASONS` — дополняется ровно тремя, смысл фиксирован:
- `no_process_start` — **в schema 1**: `process_started_at` не передан/не разобран → `local_unverified`;
  D6-потребитель: `deploy_identity.reason` в блоке identity («проверка запуска не выполнена»), снимает
  бейдж «подтверждено».
- `version_unknown` — **в schema 1**: манифест валиден, но runtime `APP_VERSION` недоступен →
  `local_unverified`; D6: тот же `reason`, UI не имеет права печатать «версия совпадает».
- `internal_error` — **в schema 1** с узким смыслом: только перехват непредвиденного исключения на
  верхнем уровне `collect_identity`/`recent_commits` (код `unavailable`); D6: `reason`, текст «проверка не
  выполнена». Не общая свалка для известных ветвей.
- Следствие закрытого набора: `dirty == true` при валидном манифесте обязано давать
  `reason = "dirty_tracked"`, а не `dirty_unknown` (`dirty_unknown` = «не удалось определить»).

Поля записи, **входящие в schema 1** (в §2.2 добавляются явно; `null`, если манифеста нет):
- `effect` (`"deploy"|"rollback"`, только из манифеста), `previous_sha`, `previous_version` —
  D6-потребитель: блок «релиз/откат» (что выложено и что было заменено); значения не выводятся.
- `upstream_head = {sha, ref, observed_at, reason}` — `reason` (`""`|`no_remote_ref`): D6 печатает
  «remote HEAD локально не наблюдается» вместо пустоты.
- `conflict_values` — **в schema 1**, только при `code="mismatch"`: `{source_name: value}` строго по
  источникам из `conflict`, значения = 40-hex SHA или строка версии; D6-потребитель: строка расхождения
  с обоими значениями (иначе env-значение нигде в записи не видно).
- `local_identity.upstream_ref` — **удалить**: дубль `upstream_head.ref`; тест/эвиденс выровнять на
  `upstream_head.ref`.

### B3. Схема манифеста: `schema` — опционально

`schema` **не обязателен**; отсутствие = схема 1 (обратная совместимость; минимальная обязанность DevOps —
четыре обязательных поля `deployed_sha`, `deployed_at`, `version`, `effect`). Если `schema` присутствует
и `!= 1` → `unknown/manifest_incomplete` (будущую версию не угадываем). Неизвестные ключи по-прежнему
отвергаются (`manifest_incomplete`) — закрытый набор §1.2 сохраняется.
Тесты Builder: (B3-a) манифест ровно из четырёх обязательных полей, HEAD/sha/version/process сходятся →
`verified_deployed`, `sources` содержит `release_manifest`; (B3-b) тот же манифест с `schema: 2` →
`unknown/manifest_incomplete`; (B1) четыре кейса ревьюера (`config/credentials/notes.txt`,
`config/secrets/notes.txt`, `media/cookies/notes.txt`, `services/deploy_evil.py`) → `True`, плюс
`services/deploy_identity.py` → `False`; (B2) `upstream_ref` отсутствует в записи, `dirty=true` даёт
`dirty_tracked`, `no_process_start`/`version_unknown` наблюдаемы.

### Builder D4-A fix list (только B1/B2/B3; D6 и D4-B не трогать)

1. `path_is_denied`: правило B1 целиком (все компоненты; `deploy_*.py` на любой глубине; одно точное
   исключение `services/deploy_identity.py`).
2. `collect_identity`: убрать `local_identity.upstream_ref`; `effect`/`previous_sha`/`previous_version`
   оставить в записи (уже парсятся); `conflict_values` — только при `mismatch`; `dirty=true` →
   `dirty_tracked`; три причины оставить и перечислить закрытым списком в docstring.
3. `_read_manifest`: `schema` опционален (отсутствие = 1), явная версия `!= 1` отвергается.
4. `tests/test_deploy_identity.py`: кейсы B1 (4+1), B2 (3 проверки), B3 (a+b); эвиденс `evidence/d4/`
   пересобрать на новом кандидате.

**Вердикт: `ARCH_AMENDMENT_READY`** — контракт v1.1; повторное ревью на новом SHA после правок B1/B2/B3,
без расширения слайса. Файл: `plans/features/self-diag-01/architecture-d4-identity.md`.
