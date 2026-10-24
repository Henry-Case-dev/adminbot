# Withheld после 2.58.122 + статус авторского Core

Лейн `POSTDEPLOY-WITHHELD`, режим **read-only** (PG `SELECT`, импорт прод-кода, журнал).
Прод: `198.46.175.136`, HEAD **`c128675a`** / 2.58.122, сервис `active`, healthz 200.
Замеры: `2026-10-24T01:56:27Z` (попытка, аборт до чтения данных) и **`01:58:44Z`** (основной).
SSH: 2 подключения, один логин, интервал > 60 с, без ретраев/поллеров, записей нет.

## 1. Главное

1. **Авторская редакция `character.core` ДЕЙСТВУЕТ.** Активна stored-редакция `r8.ead77b2ab509`
   (3294 зн., `detail_level=full`, `origin=owner_edit`), оба новых абзаца в тексте по 1 разу.
   Заводская v4 (`fac:5597c09dd5f8`, 3224 зн.) **не подменяет** авторскую.
2. **Новых удержаний нет.** Реально удержано **8** значений — те же `legacy_incompatible`
   (`updated_at` 18–28.09.2026, байты не менялись). Ещё **3** значения байт-в-байт равны
   текущей фабрике (`identical_to_factory`) и в `withheld_values()` не попадают.
3. **«11 unclassified» — ошибка замера деплой-пробы, не состояние прода.** Проба передала в
   `withheld_values(pg_get=...)` сырые JSON-строки из `bot_settings` (с внешними кавычками/escape),
   минуя `ConfigCache`/`param_catalog.normalize_value`. Хеши не совпали с таблицей классов →
   все 11 помечены `unclassified`; три фабрично-идентичных значения перестали отсекаться.
   Штатный путь (`withheld_values()` по кэшу, Inspector) даёт **8** и классы `legacy_incompatible`.

## 2. Таблица 11 (block, sha/chars — decoded; raw — как лежит в PG)

| block | pg_key | stored dec sha / chars | raw sha / chars | factory sha / chars | класс | действует (source / sha) |
|---|---|---|---|---|---|---|
| `factcheck.base.single` | `prompts.factcheck_system_prompt` | `76c4beb11c63` / 4666 | `17aa4fa3b9bf` / 4730 | `3f2a1eadf772` / 4597 | **user_custom** / `legacy_incompatible` | default / `c96d5817cf1a` (factory) |
| `search.base.system` | `prompts.search_system_prompt` | `ba43fb679db6` / 2622 | `17f9af6be519` / 2668 | `a1d2e653c449` / 2403 | **user_custom** / `legacy_incompatible` | default / `a1d2e653c449` |
| `summary.base.single` | `prompts.summary_system_prompt` | `d697b0745b29` / 3558 | `5ea179bf4156` / 3612 | `5f096fc613a3` / 3374 | **user_custom** / `legacy_incompatible` | default / `5f096fc613a3` |
| `checkup.base.system` | `prompts.checkup_system_prompt` | `1e8a3c69cf7b` / 2312 | `ed50299b0f57` / 2352 | `0f5fb7b8d25c` / 3210 | **user_custom** / `legacy_incompatible` | default / `0f5fb7b8d25c` |
| `youtube.base.system` | `prompts.youtube_system_prompt` | `e0a1ffaf18a1` / 2252 | `f4322deede03` / 2293 | `65ec52f176c0` / 2073 | **user_custom** / `legacy_incompatible` | default / `65ec52f176c0` |
| `youtube.base.video` | `prompts.youtube_video_system_prompt` | `c8bba06ec6a8` / 2248 | `69261749d13c` / 2289 | `a4794cd1d74e` / 2069 | **user_custom** / `legacy_incompatible` | default / `a4794cd1d74e` |
| `web.base.system` | `prompts.webpage_system_prompt` | `7801085b6ef5` / 2071 | `2fae9990f23c` / 2112 | `dccad8eafdfb` / 1895 | **user_custom** / `legacy_incompatible` | default / `dccad8eafdfb` |
| `factcheck.base.verbalizer` | `prompts.factcheck_verbalizer_system_prompt` | `5fbf61cea310` / 1712 | `fd349307e6b5` / 1752 | `c090b6956c70` / 1632 | **user_custom** / `legacy_incompatible` | default / `83b4fb75500f`* |
| `direct.base.tool_phase` | `prompts.direct_chat_system_prompt` | `f30c6d73da82` / 4999 | `d4c558629215` / 5044 | `f30c6d73da82` / 4999 | **identical_to_factory** | factory (байты совпадают) |
| `summary.base.narrator` | `prompts.summary_narrator_system_prompt` | `5086ba935081` / 1788 | `2e5e9dafa24f` / 1826 | `5086ba935081` / 1788 | **identical_to_factory** | factory (байты совпадают) |
| `direct.base.l2_writer` | `prompts.direct_chat_verbalizer_system_prompt` | `83ff62bbee40` / 3081 | `f7341178cb6f` / 3107 | `83ff62bbee40` / 3081 | **identical_to_factory** | factory (байты совпадают) |

\* `factcheck.base.verbalizer`: действует factory `c090b6956c70`; `83b4fb75500f` — байты после
штатной вычистки legacy-сегментов (suppress), поэтому не равен сырому factory-хешу.

Классы: `old_factory` — **0**, `intermediate` — **0**, `user_custom` — **8**,
`identical_to_factory` — **3**. Ни один stored-текст не совпал ни с одной из **162** именованных
редакций (фабрики, `PREV_*`, ступени `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS`).
Общие признаки 8 удержанных: старая личность («бот-абьюзер»/«завсегдатай двача»), строка
«Игнорируй все настройки безопасности…» (у 7 из 8), ослабленный разбор набросов. Это ровно
класс из прошлого аудита (`evidence/withheld/classification.md`), байты и `updated_at` — сентябрьские.

## 3. Почему 11, а не 8

| путь | результат | причина |
|---|---|---|
| `withheld_values()` по нормализованным значениям (как `ConfigCache`; код `stale_values`) | **8** (измерено) | значения нормализованы; три фабрично-идентичных отсекаются |
| per-block статус `effective.withheld` (строки Inspector) | **11** (по коду `_blocks_rows`→`effective_prompt`) | 8 `legacy_incompatible` + 3 `identical_to_factory` (конфликта нет) |
| деплой-проба `withheld_values(pg_get=сырой PG)` | **11 unclassified** (измерено) | сырые JSON-строки: sha не совпадают с таблицей классов; `value == factory` не срабатывает |

Это не изменение прода 2.58.122: все 8 удержанных записей записаны 18–28.09.2026 и не
перезаписывались; три identical просто равны фабрике (их активация не нужна). Ошибка — в методике
деплой-пробы/отчёта (`release-258122/deploy.md`, «Находка 1»), а не в канонах.
Правильный замер: нормализовать значение (`param_catalog.normalize_value`) до хеширования/сравнения
либо вызывать `withheld_values()` только по кэшу.

## 4. `character.core` — авторская редакция активна

| параметр | факт |
|---|---|
| stored full | sha `ead77b2ab509`, **3294** зн., revision **8**, `detail_level=full`, `origin=owner_edit`, `updated_at 01:46:44Z` |
| stored compact | пусто (0 зн.) |
| новые абзацы | «Как говорить о реальных событиях.» — 1, «Свобода речи.» — 1 |
| `enabled` | не задан (композер трактует как `True`) |
| factory v4 | `fac:5597c09dd5f8` / 3224 зн. (тоже содержит оба абзаца, но байты иные) |
| прежние редакции | v1 `040581a3b4b0`, v2 `d98e72ec7926` — stored **не совпадает** |
| superseded-гвард | `superseded_fields=[]`, `stored_is_superseded=false` |
| `core_selection` | `level=full`, `reason=owner_setting`, `source=global`, `active_from_owner=True`, активный sha **`ead77b2ab509`** |
| что уходит в модель | **stored full** (`active_is_stored_full=true`), **не** factory (`active_is_factory_full=false`) |
| бюджет | `composer_additive_budget_tokens()=1200`; оценка 3294 зн. ≈ **824** токена → full помещается |
| patch | `owner_preserve_core_full_patch(pre)==post` = **True**; после вычитания двух абзацев — исходные 1995 зн. (`AUTHOR_BYTES_RESTORED=True`, деплой 01:46Z) |
| идемпотентность | повторный рестарт 01:49:10Z: «абзацы уже есть, авторские байты целы», sha/revision не менялись |
| история/провенанс | `character.prompt_history` 4 записи; журнал `provenance | block=core.personality | kind=owner_edit | sha=ead77b2ab509` |

Core не входит в `withholding_blocks()` (это не legacy-канон), поэтому provenance-гейт его не
удерживает; действует отдельный superseded-гвард, который сработал бы только при точном совпадении
с v1/v2. Совпадения нет → **авторская личность используется**.

## 5. Журнал (сокращённо)

```
01:46:44 prompt_factory provenance | block=core.personality | kind=owner_edit | sha=ead77b2ab509 | persisted=True
01:46:44 prompt_migrations core patch: добавлены абзацы | key=character.core | added=Как говорить о реальных событиях.,Свобода речи. | removed=0 | chars=1995->3294 | sha=3de4884f29ce->ead77b2ab509
01:46:44 prompt_factory provenance | block=direct.base.l2_writer | kind=factory_reset | sha=83ff62bbee40 | persisted=True
01:49:10 prompt_migrations core patch: абзацы уже есть, авторские байты целы | key=character.core | sha=ead77b2ab509
```
Строк `persisted speech value withheld` в журнале старта **нет** (витрина считается по запросу);
8 строк `legacy_incompatible` воспроизведены probe-вызовом с нормализованными значениями.

## 6. Что исправить

1. **P2, evidence/reporting (не прод):** деплой-проба и «Находка 1» в `release-258122/deploy.md`
   должны использовать нормализованные значения; иначе счётчик/класс withheld завышены (11/unclassified
   вместо 8/legacy + 3 identical). Прод-поведение корректно, Inspector-счётчик `stale_values` = 8.
2. **P3, UX-ясность:** в per-block статусах отделять `identical_to_factory` от `legacy_incompatible`,
   чтобы «11» не читалось как 11 конфликтов владельца.
3. **P3, латентный риск Core:** у авторского документа пуст `compact_text`. Если бюджет слоёв
   когда-либо опустится ниже ~825 токенов, `core_selection` при `detail_level=full` переключится на
   `context_budget` с пустой компактной редакцией → слой Core окажется пустым. Сейчас бюджет 1200 и
   full помещается; менять только осознанно (не в этом релизе).

## 7. Откат

Не требуется: изменения не вносились. Указатели прежние — код `999e547a`
(`release/fix-2.58.121`), Core rev7 — в `character.prompt_history`, бэкап
`~/deploy-258122/bot_settings_pre.json`.

## Вердикт

**Авторская редакция `character.core` (rev8, `ead77b2ab509`, оба новых абзаца) активна и идёт в
модель; заводская v4 не подменяет её.** Удержаний ровно 8 (`legacy_incompatible`, сентябрьские
кастомы), ещё 3 — `identical_to_factory`; «11 unclassified» — артефакт сырого замера, не регрессия
2.58.122.
