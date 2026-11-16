# MAC-M0-02 — effective-state 2.58.205 (production, read-only)

**Статус:** evidence для закрытия пробела `MAC-M0-01 §7` (пункты 1–4). `VERIFIED` **не заявляется**:
это один read-only срез, а не непрерывное наблюдение. Продуктовый код, тесты, конфигурация,
`bot_settings`/`chat_profiles` и `requirements-map.json` не изменялись; рестартов не было.

**Локальное время сбора:** 2026-11-16 16:03 +12:00 (2026-11-16 04:03 UTC).

---

## 1. Идентификаторы среза

| Поле | Значение |
|---|---|
| Хост | `192.255.209.205`, `/var/www/admin_bot` |
| Deployed SHA | `bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1` |
| Ветка checkout | `release/vmq-slice-d-2.58.205` |
| `APP_VERSION` | `2.58.205` |
| Tracked dirty | **0**; единственный untracked — `.cache/` |
| `/healthz` (local) | `200 {"status":"ok","version":"2.58.205"}` |
| Unit `admin_bot` | `active`, `NRestarts=0`, старт `2026-11-15 09:47:17 UTC` |
| Скрипт отчёта | `scripts/mod_acl_effective_state_report.py`, 17 529 B, sha256 `621bdf1f…f35ec` = git-блob `HEAD` (совпадает) |
| Интерпретатор | `/var/www/admin_bot/venv/bin/python` 3.12.3 |
| PostgreSQL | 16.15, БД `adminbot`, транзакция `read_only=on` |
| SQLite | `user_version=47`, 130 таблиц, `max(schema_migrations)=47` |

### 1.1. Где скрипт лежит (важное расхождение с `mac-m0-01 §7.2`)

`mac-m0-01 §7.2` утверждал, что `scripts/mod_acl_effective_state_report.py` «уже есть
в дереве». Фактически:

| Ref | Наличие |
|---|---|
| `master` (плановая линия, HEAD `ad587012`) | **отсутствует** |
| `integ/unify-release` | присутствует (добавлен в `97cfdef1`) |
| `release/vmq-slice-d-2.58.205` / deployed `bca18c1e` | присутствует |

То есть скрипт существует только в deployed/release-линии, но не в плановом checkout.
Для M0 это не блокер (прогон выполнен на deployed checkout), но терять его из плановой
линии нельзя: при `git pull`/ветвлении от `master` отчёт исчезнет.

### 1.2. Дисциплина SSH/fail2ban

1 recon-коннект (~15 с, только чтение) + 1 основной прогон; далее — точечные read-only догрузки
артефактов. Параллельных коннектов, ретраев на auth и брутфорса не было; `.env`/DSN/токены
не выводились. Все прогоны — `SELECT` + `server_settings.default_transaction_read_only=on`.

---

## 2. Команды (как воспроизведено)

```bash
cd /var/www/admin_bot
venv/bin/python -m scripts.mod_acl_effective_state_report \
    --database --json --out /tmp/m0_acl_<ts>/effective-2.58.205.json     # rc=0, 7 309 B
```

Дополнительно (тот же read-only пул): `bot_settings`/`chat_profiles` SELECT + digest по формуле
`harness/snapshot.py`; DM-профиль — через тот же `scripts...` + `chat_params.resolve_*`
(официальный CLI ЛС не отдаёт, см. §7.1).

---

## 3. Digest: pre/post 2.58.205 vs фактическое состояние

| Метрика | 2.58.205 pre/post | 2026-11-16 04:03Z | Итог |
|---|---|---|---|
| `bot_settings` count | 548 | **548** | = |
| `bot_settings` digest | `e98edf0e…7460` | **`e98edf0e…7460`** | = |
| digest без `prompts.checkup_system_prompt` | `fefe4bca…c86d` | **`fefe4bca…c86d`** | = |
| `chat_profiles` count | 3 | **3** | = |
| `chat_profiles` digest | `323a6528…0f89` | **`323a6528…0f89`** | = |

`max(bot_settings.updated_at)` = `2026-11-14 18:56:52Z` — **до** выката 2.58.205 (15.11 09:47Z):
после деплоя ни одна глобальная настройка не переписана.

Оговорка: профиль `-1002661910336` имеет `updated_at=2026-11-15 11:26:38Z` (после деплоя), но
digest `chat_profiles` (считается по `chat_id` + `chat_params::text`) не изменился — значит запись
11:26Z не меняла `chat_params` (лор/relations-колонки вне digest). Значения конфигурации
считать неизменными с момента выката корректно; «строка профиля не обновлялась» — нет.

---

## 4. Матрица 16 capability × (GLOBAL + 3 профиля)

Профили: `G8 = -1004482340693`, `G32 = -1002661910336`, `DM5 = 5885953495`.
`INH` — записи чата нет (наследование), `EXP` — явное chat-значение.
Наблюдено **48 пар** (16 × 3). Все `emergency_block=false` (env-оси `MCA_*` не режут).

| # | capability | ключ | GLOBAL | G8 | G32 | DM5 |
|---|---|---|---|---|---|---|
| 1 | `module:initiative` | `flags.initiative_enabled` | ON | ON `INH` | ON `INH` | ON `INH` |
| 2 | `module:stories` | `flags.stories_vitrina_enabled` | ON | ON `INH` | ON `INH` | ON `INH` |
| 3 | `module:character` | `flags.self_model_enabled` | ON | ON `INH` | ON `INH` | ON `INH` |
| 4 | `module:experience` | `memory.experience_learning_enabled` | ON | ON `INH` | ON `INH` | ON `INH` |
| 5 | `module:random` | `memory.random_enabled` | ON *(строки нет → дефолт)* | ON `INH` | ON `INH` | ON `INH` |
| 6 | `module:factcheck` | `flags.factcheck_enabled` | ON | ON `INH` | ON `INH` | ON `INH` |
| 7 | `module:factcheck_temporal` (hidden) | `temporal.tool_enabled` | ON | ON `INH` | ON `INH` | ON `INH` |
| 8 | `module:vision` | `flags.vision_enabled` | ON | **ON `EXP`=t** | **ON `EXP`=t** | ON `INH` |
| 9 | `module:nostalgia` | `memory.nostalgia_enabled` | ON | ON `INH` | ON `INH` | **OFF `EXP`=f** |
| 10 | `module:sleep` | `memory.dream_enabled` | ON | ON `INH` | ON `INH` | **OFF `EXP`=f** |
| 11 | `gate:dream` | fallback `memory.dream_enabled` | ON | **OFF `EXP`=f** | ON `INH` | **OFF `EXP`=f** |
| 12 | `gate:lore_auto` | `flags.lore_auto_enabled` | ON | **OFF `EXP`=f** | ON `INH` | ON `INH` |
| 13 | `gate:nostalgia` | fallback `memory.nostalgia_enabled` | ON | **ON `EXP`=t** | ON `INH` | **OFF `EXP`=f** |
| 14 | `gate:permsoc` | `flags.permsoc_enabled` | **OFF** | **OFF `EXP`=f** | **ON `EXP`=t** | OFF `INH` |
| 15 | `gate:permsoc_reactions` | — (дефолт ON) | ON | ON `INH` | ON `INH` | ON `INH` |
| 16 | `gate:permsoc_schedule` | — (дефолт ON) | ON | ON `INH` | ON `INH` | ON `INH` |

### 4.1. Явные chat-значения мастеров (всего 11 из 48 пар)

| Профиль | Явные capability | Прочие override-ключи (не capability) |
|---|---|---|
| **G8** (8 overrides, 4 gates, opt-in `true`) | `vision=t`, `gate:dream=f`, `gate:lore_auto=f`, `gate:nostalgia=t`, `gate:permsoc=f` | `flags.budgets_enabled=f`, `flags.meme_initiative_enabled=t`, `flags.summary_enabled=f`, `initiative.meme_length_limit=800`, `memory.experience_review_cadence="hourly"`, `prompts.meme_image`, `prompts.meme_joke` |
| **G32** (32 overrides, 1 gate, opt-in `true`) | `vision=t`, `gate:permsoc=t` | 30 ключей лимитов/флагов/промптов (в т.ч. `limits.*`, `character.expression`, `prompts.checkup_system_prompt`, `prompts.summary_cover_style_id="medved_press"`) |
| **DM5** (5 overrides, 2 gates, opt-in `false`) | `nostalgia=f`, `sleep=f`, `gate:dream=f`, `gate:nostalgia=f` | `flags.chat_running_summary_enabled=f`, `flags.smart_cache_enabled=f`, `flags.summary_enabled=f` |

Остальные ячейки — `INH`: у 7 мастеров (`initiative, stories, character, experience, random,
factcheck, factcheck_temporal`) **ноль** явных chat-значений у всех трёх профилей.

### 4.2. GLOBAL-строки мастеров: 9 из 10 присутствуют

| Ключ | Есть | Значение | `updated_at` |
|---|---|---|---|
| `flags.initiative_enabled` | да | `true` | 2026-10-08 |
| `flags.stories_vitrina_enabled` | да | `true` | 2026-10-09 |
| `flags.self_model_enabled` | да | `true` | 2026-10-09 |
| `memory.experience_learning_enabled` | да | `true` | 2026-11-08 |
| `memory.random_enabled` | **нет** | дефолт `True` | — |
| `flags.factcheck_enabled` | да | `true` | 2026-09-10 |
| `temporal.tool_enabled` | да | `true` | 2026-10-15 |
| `flags.vision_enabled` | да | `true` | 2026-10-29 |
| `memory.nostalgia_enabled` | да | `true` | 2026-09-06 |
| `memory.dream_enabled` | да | `true` | 2026-09-06 |
| `flags.dream_enabled` (alias гейта) | **нет** | fallback → `memory.dream_enabled` | — |
| `flags.nostalgia_enabled` (alias) | **нет** | fallback → `memory.nostalgia_enabled` | — |
| `flags.lore_auto_enabled` | да | `true` | 2026-09-05 |
| `flags.permsoc_enabled` | да | `false` | 2026-09-07 |

Это закрывает `†`-метки `mac-m0-01 §5`: глобальные строки прочитаны, кроме одного мастера
(`memory.random_enabled`) и двух alias-ключей.

### 4.3. Гейты по G8/DM5 (бывшие `‡`)

| Гейт | G8 (факт) | DM5 (факт) | GLOBAL-слой |
|---|---|---|---|
| `dream` | `false` | `false` | `memory.dream_enabled=true` |
| `lore_auto` | `false` | `INH` → ON | `flags.lore_auto_enabled=true` |
| `nostalgia` | `true` | `false` | `memory.nostalgia_enabled=true` |
| `permsoc` | `false` | `INH` → OFF | `flags.permsoc_enabled=false` |

Агрегат `mac-m0-01` (dream false ×2, lore_auto false ×1, nostalgia t/f, permsoc t/f) **подтверждён**
поштучно: DM5 `lore_auto` — действительно `INH` (не `false`), а `permsoc` у DM5 — `INH` → OFF.

### 4.4. Пары `GLOBAL OFF + CHAT ON`

Ровно одна: `gate:permsoc` у G32 (`flags.permsoc_enabled=false`, чат `permsoc=true`) — совпадает
с прежним выводом `m2-impact-3b1ba3b2.md`. Других таких пар среди 48 нет.

### 4.5. Регресс relative к M2 (`old` vs `new`)

Официальный CLI на 2 групповых профилях: **`changed_pairs=0`** (32 строки, `old == new`).
То есть канонический резолвер M2 на текущей конфигурации не меняет ни одного решения —
переключение семантики прошло без фактических сдвигов. DM5 в CLI не входит (см. §7.1).

---

## 5. Sanitized-экспорт конфигурации

- `bot_settings`: 548 строк; категории `limits 231, flags 110, models 67, memory 43,
  reactions 39, prompts 29, keys 18, content 7, temporal 4`.
- `chat_profiles`: 3 строки (`G8` 8 overrides / 4 gates; `G32` 32/1; `DM5` 5/2).
- Маскирование: значения `keys.*`, `*token*`, `*secret*`, `*password*`, `*dsn*`, `*cookie*`,
  `*base_url*`, `*_url*` не выводились (только `chars` + `sha12`); длинные строки — `head` 80 симв.
- В evidence нет DSN, паролей, токенов и приватных ключей; IP-адреса инфраструктуры не печатались.

---

## 6. Бэкап конфигурации

| Поле | Значение |
|---|---|
| `pg_dump` / `pg_restore` на хосте | **не установлены** (`command -v` → нет) |
| Поэтому | custom-format архив **не создан**; это отдельное действие (установка `postgresql-client` — изменение инфраструктуры, не выполнялось без разрешения) |
| Что сделано вместо | gzip-JSON снапшот обеих таблиц (полные значения, сервер-сайд, mode `0600`) |
| Каталог | `/var/www/admin_bot/backups/m0-acl-config-2.58.205-20261116T040424Z/` |
| Файл | `config-tables-2.58.205.json.gz` — **92 356 B**, sha256 `1cae602d10dc8cd2fa3489e520e16065c77653a7e7c9d80e502ac2dec7029a4d` |
| Внутри | JSON **393 427 B**, sha256 `1c5312feca6eba7a8386aeb39aaf712516f7f789f4bdc107a701e489c188ea78`, `bot_settings=548`, `chat_profiles=3` |
| Read-back | gunzip → байт-в-байт равен исходному JSON (`readback_equal=true`); рядом `.sha256` |
| Продукт | не менялся (только чтение + файл в `backups/`) |

**Поправка D1 (2026-11-16).** Фактический inner sha256 — `1c5312fe…ea78`
(подтверждён `gzip -dc | sha256sum`). Ранее записанный `309f1947…9914` — ошибочный хеш от
`str(bytes)`, а не от распакованных байт. Gz не менялся: **92 356 B**, sha256
`1cae602d…9a4d`; размеры и строки прежние. Sidecar на проде исправлен: `.sha256` +
`.meta.json` с `corrections[]`, `gz_modified_by_correction:false`; бэкап старого sidecar
сохранён.

---

## 7. Отклонения и ограничения

1. **Официальный CLI отдаёт 2 профиля, а не 3.** `ChatLoreStore.list_profiles()`
   (`services/chat_lore_store.py`) жёстко фильтрует `WHERE chat_id < 0` («DM-профили исключены
   всегда»). DM5 дочитан тем же резолвером (`chat_params.get_all_chat_params` + `resolve_capability`)
   на read-only соединении; в матрице это помечено `measured_by`.
2. **`pg_dump` отсутствует** — полноценного дампа нет, см. §6.
3. **Один срез, не наблюдение.** Значения верны на `2026-11-16T04:03Z`; тренд/дрейф не проверялись.
4. **Расхождение «карточка модуля vs гейт» подтверждено фактически** (`sleep`/`nostalgia`):
   у G8 карточка `sleep` = ON (`memory.dream_enabled=true`), а `gate:dream` = OFF. Это разные
   namespace, не дефект выката; для M2/M4 это вход, не вывод.
5. **Скрипта отчёта нет в `master`** (см. §1.1) — риск потери отчёта в плановой линии.
6. Живой Mini App с owner-сессией не открывался: UI-часть M0 остаётся на прежнем DOM-срезе
   (`catalog-dom-probe-2026-11-16.json`), это отдельная проверка M4.

---

## 8. Артефакты

| Файл | Что | sha256 |
|---|---|---|
| `evidence/m0/effective-state-2.58.205.json` | сводный бандл (identity, digest, CLI, матрица 48 пар, stored, snapshot) | `9A0CBA41C752D7B0017EEE6BB5E5A6CF0705870C4A5614AA6C6EC42CC9D7AD31` |
| `effective-2.58.205.json` (prod `/tmp/m0_acl_20261116T040324Z/`) | вывод официального CLI | `85daf73a2bbd69b96aa130f2fe2f50cc42875d63cd621b3049c89f14c6a644cc` |
| `stored-and-matrix.json` (prod) | stored-слой + digest + матрица | `c29a69d8a0fbf9af821c9d33750cbb1232144806806d416a5e55f3dbcd9ff200` |
| `dm-and-snapshot.json` (prod) | DM5-профиль + серверный снапшот | `bcf516e9235b199f89044d124838416df3f39e6a293bb671cf19b836b7b56fc5` |

Три prod-файла скачаны побайтово (base64) и локально сверены по sha256 — совпадение с серверными
значениями. `/tmp`-каталог на проде не удалён (нужен для повторной сверки); это не продукт-состояние.

**Вывод для M0:** фактическая матрица на `bca18c1e`/2.58.205 получена, digest совпадает с
pre/post выката, явных chat-значений 11 из 48 пар, GLOBAL-строки мастеров прочитаны (9 из 10),
`changed_pairs=0`. Пункты 2–4 `mac-m0-01 §7` закрыты; пункт 1 (полноценный `pg_dump`) — нет.
