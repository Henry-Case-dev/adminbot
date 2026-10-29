# EVOL-W1 — замороженные контракты

Статус: `ARCHITECT_ADJUSTMENT_REQUIRED`
Фича: `evol` (фундамент `EVOL-016` / `EVOL-012` / `EVOL-017` / `EVOL-018` и `EVOL-032`)
Ветка сверки: `evol/impl` @ `4aa91baf` (worktree, production 2.58.141 + docs)
Дата сверки кода: 2026-10-30

Источники, которые имеют приоритет над старым SOUL-1 правилом «обновление приложения не перезаписывает правку владельца» и над аудитом `plans/features/evol/audit/backend-defects-audit.md`:

- решение владельца 29.10.2026 в `EVOL-012` и семантика пунктов 1–5 `EVOL-016`;
- текущий код worktree, не номера строк аудита.

Аудит смотрел более короткий `prompt_registry.py` и `migrate_prompt_canons` около строки 716. В этом worktree файл реестра длиннее (функции до `resolve_chat_speech_ex`, около строки 2794), а `migrate_prompt_canons` живёт в `services/prompt_migrations.py:862`. Поведение то же: строковое равенство с каноном, иначе `WARNING` «кастом юзера — НЕ трогаем» и skip. Это и есть барьер, который надо снять. Номера строк аудита в реализацию не копировать.

Внешние источники не использовались. Контракт стекла снят с vendored `@liquidglassjs/core` 0.5.3 в этом worktree (`web/static/vendor/liquidglass.core.0.5.3.min.js` + `.css`) и с проектных `glass.js` / `glass-refraction.js` / `app.css`. Документация более новой версии библиотеки не применяется: в рантайме закреплена 0.5.3.

---

## 0. Что это за волна и чего в ней нет

Один Builder может сделать оба контракта. Они не делят файлы (карта параллельности в конце).

Не строить:

- второй рендерер стекла, второй canvas, второй `backdrop-filter`;
- второе хранилище активного текста промпта (активный текст остаётся в `bot_settings` / `chat_params.overrides`);
- новые вызовы LLM;
- декоратор на каждой строковой константе;
- UI «История версий» (`EVOL-017`) и переразметку экранов (`EVOL-033`);
- новый health engine, новую таблицу здоровья, парсер логов.

`EVOL-017` позже только вызывает API этого контракта. Не заводит свою таблицу и свой diff.

---

# CONTRACT 1 — версии промптов

## 1.1 Корректировка хранилища (обязательная)

Запрошенный `PRAGMA user_version = 37` **нельзя** занимать. В `services/database.py` версия 37 уже занята:

- `_SCHEMA_VERSION_HUMOR_SAMPLES_V36 = 36`
- `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` (`humor_samples`, шаг `_migrate_humor_samples_v37`)

Следующая свободная версия — **38**. Имя шага: `prompt_revision_journal_v38`. Константа: `_SCHEMA_VERSION_PROMPT_JOURNAL = 38`.

`migrate_history/` — это JSON-импорт Telegram Desktop (`manage.py`), не книга схемы. Книга схемы — таблица `schema_migrations` и раннер `_run_migrations` (`services/database.py` около строки 2925). Туда промпты не класть.

Активные тексты промптов живут не в SQLite:

- глобальные — PostgreSQL `bot_settings` через `ConfigCache.set` (`services/config_cache.py:705`, сначала PG, потом память);
- per-chat — `chat_profiles.chat_params.overrides` (`services/chat_params.py`);
- журнал SOUL-1 — один JSON-документ `character.prompt_history` (`prompt_registry.PROVENANCE_DOC_KEY`), bounded `HISTORY_MAX_PER_BLOCK = 12` (`prompt_factory.py:71`).

Поэтому канонический журнал версий — **аддитивные таблицы PostgreSQL**, тот же контур долговечности, что и `bot_settings`. Образец уже есть: v35 (`_migrate_llm_usage_plan_meta_v35`) — SQLite-шаг только фиксирует `user_version` и пишет книгу, DDL делает идемпотентный `PgDatabase.init()` (`services/pg_db.py:683`, `DDL_STATEMENTS`).

SQLite-шаг v38:

- не создаёт вторую продовую копию текстов;
- `PRAGMA user_version = 38` + строка в `schema_migrations`;
- если локально вдруг есть таблица `bot_settings` — не зеркалить в неё журнал;
- повтор — no-op;
- PG down на SQLite-шаге не блокирует фиксацию версии (как v35: версия — про книгу, DDL — про `PgDatabase.init`).

Откат схемы: cold git revert. Старый код таблицы не читает, они инертны. `user_version` назад не опускать (прецедент v36/v37). Повторный выкат — `CREATE TABLE IF NOT EXISTS`.

## 1.2 Модель данных (только добавление)

Две таблицы в `services/pg_db.py` `DDL_STATEMENTS`. Не трогать `ON CONFLICT DO NOTHING` сида `bot_settings`: сид по-прежнему не перезаписывает существующие значения. Активация идёт после `cache.init()`, как сегодня `migrate_prompt_canons` в `bot.py`.

```sql
CREATE TABLE IF NOT EXISTS prompt_revisions (
    revision_id        TEXT PRIMARY KEY,
    block_id           TEXT NOT NULL,
    pg_key             TEXT NOT NULL DEFAULT '',
    scope              TEXT NOT NULL,
    chat_id            BIGINT,
    origin             TEXT NOT NULL,
    content_sha12      TEXT NOT NULL,
    body               TEXT NOT NULL,
    factory_revision   TEXT NOT NULL DEFAULT '',
    schema_compat      TEXT NOT NULL DEFAULT '',
    release_id         TEXT NOT NULL DEFAULT '',
    actor              TEXT NOT NULL DEFAULT '',
    reason             TEXT NOT NULL DEFAULT '',
    source_updated_at  TEXT NOT NULL DEFAULT '',
    retired            BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prompt_revisions_block
    ON prompt_revisions (block_id, scope, created_at);

CREATE TABLE IF NOT EXISTS prompt_activations (
    activation_id              BIGSERIAL PRIMARY KEY,
    block_id                   TEXT NOT NULL,
    scope                      TEXT NOT NULL,
    chat_id                    BIGINT,
    revision_id                TEXT NOT NULL DEFAULT '',
    factory_revision_applied   TEXT NOT NULL DEFAULT '',
    kind                       TEXT NOT NULL,
    outcome                    TEXT NOT NULL,
    release_id                 TEXT NOT NULL DEFAULT '',
    actor                      TEXT NOT NULL DEFAULT '',
    detail_code                TEXT NOT NULL DEFAULT '',
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prompt_activations_latest
    ON prompt_activations (block_id, scope, activation_id DESC);
```

`revision_id` = `"rev:" + sha12(block_id + "\0" + scope + "\0" + str(chat_id or 0) + "\0" + origin + "\0" + content_sha12)`. Повторный импорт того же текста — `INSERT ... ON CONFLICT DO NOTHING`. Две одинаковые ручные правки одного текста — одна неизменяемая ревизия; каждое включение — отдельная строка `prompt_activations`.

`origin`: `factory | manual | restored | legacy`. Других значений нет.

`kind`: `legacy_import | deploy_activate | manual_edit | manual_rollback | manual_forward | integrity_reject`. `restart` строку не пишет.

`outcome`: `applied | skipped_same | skipped_empty | failed`.

`schema_compat` пустой = ревизия совместима с текущим runtime. Несовместимость в этой волне не выдумывать. Поле нужно `EVOL-017`: несовместимую ревизию можно читать и сравнивать, `activate_revision` возвращает `applied=false`, `reason=schema_incompatible`, активный указатель не меняется.

Активный текст **не** дублируется в этих таблицах как второй источник правды. Его читают пайплайны по-прежнему из `bot_settings` / chat override. Последняя строка `prompt_activations` с `outcome=applied` — указатель «какая ревизия включена» и «какая заводская ревизия уже применена» (`factory_revision_applied`).

`character.prompt_history` после одноразового импорта **замораживается**: `prompt_factory._append_history` и `_mark_provenance` больше не дописывают JSON. Документ не удалять. Обрезанные `HISTORY_MAX_PER_BLOCK` хвосты не восстанавливать и не выдавать за полную историю.

## 1.3 Идентичность заводской ревизии

Уже есть и остаётся:

- `factory_text` / `factory_revision` / `sha12` / `FACTORY_REVISION_LABELS` (`prompt_registry.py`);
- `factory_revision(block_id)` = `fac:<sha12>(<label>)`;
- сторож набора `FACTORY_SET_SHA256_12` (`tests/test_soul1_registry_completeness.py`).

Новая заводская ревизия — это **сменившаяся метка** в `FACTORY_REVISION_LABELS`, а не сам факт другого sha и не рестарт.

Добавить рядом с метками словарь печатей (один источник, не отдельный манифест-файл):

```text
FACTORY_REVISION_SEALS[block_id] = (label, sha12(factory_text(block_id)))
```

Правила:

| Что изменилось в коде | CI | Поведение при старте |
| --- | --- | --- |
| Ни метка, ни sha | pass | no-op, активный текст не трогать |
| Метка сменилась, печать обновлена в том же коммите, sha совпал с печатью | pass | это новая заводская ревизия: активировать |
| Текст сменился, метка та же | fail | **не писать в БД**. `ERROR` `integrity_label_unchanged`, `kind=integrity_reject`. Активный текст остаётся |
| Метка сменилась, печать не обновлена | fail | то же, fail-closed, БД не трогать |
| Рестарт, печать совпала с уже применённой | — | no-op, даже если активен ручной текст |

Сравнение строк с `PREV_*` / `PROMPT_MIGRATIONS` для этого решения запрещено.

## 1.4 Автомат активации

Состояние на scope (`global` или `chat` + `chat_id`): последняя `prompt_activations.outcome=applied` даёт `factory_revision_applied` и `revision_id`. Активные байты — в PG-слое, не в журнале.

`prompt_registry.activation_plan(...)` — чистая функция, без I/O. Вход: `code_revision` (`factory_revision()`), `code_label`, `sealed_sha`, `applied_revision` (или пусто), `has_import`. Выход: одно действие.

| Событие | Действие |
| --- | --- |
| Первый запуск механизма (`has_import=false`), печать цела | Сначала снимок, потом активация текущей заводской ревизии. Это явный миграционный релиз `release_id=evol-016-cutover`, не «рестарт» |
| Рестарт, `code_revision == applied_revision` | no-op. Ручная правка и откат, сделанные после этой ревизии, остаются |
| Рестарт, метка та же, sha другой | fail-closed, БД не менять, ERROR |
| Деплой, метка новее применённой, печать цела | заводской текст становится активным даже поверх ручной правки. Прежний активный текст остаётся ревизией |
| Ручная правка в админке | новая immutable-ревизия `origin=manual`, она активна. `factory_revision_applied` **не** сбрасывается: правка «поверх» уже применённой заводской ревизии |
| Ручной откат / вперёд | новая строка активации, история не удаляется. `factory_revision_applied` остаётся текущей заводской, чтобы следующий рестарт не откатил выбор. Следующая **новая метка** снова включает заводской текст |
| Пустой ключ (сида не было) | не выдумывать legacy-автора. Записать `skipped_empty`, затем обычная активация заводского текста |

Снимок legacy, обязательный до любой записи заводского текста в cutover:

- для каждого зарегистрированного `pg_key` прочитать фактическое значение `cache.get` и каждый per-chat override этого ключа;
- непустой текст → `prompt_revisions.origin=legacy`, `created_at` = время импорта (UTC, `now()`). Это не дата редактирования и не автор;
- `bot_settings.updated_at`, если он есть, писать только в `source_updated_at`. Не показывать его как «изменено владельцем»;
- `actor` пустой, `reason=legacy_import`;
- длина 1788 у `prompts.summary_narrator_system_prompt` — наблюдение прод-логов, **не** канон и не условие. В этом worktree заводской `SUMMARY_NARRATOR_SYSTEM_PROMPT` имеет длину 1608, `PREV_SUMMARY_NARRATOR_LEGFIX` — 1863, R1028 — 1690, R1023 — 1471. Ни один не равен 1788. Снимать то, что реально лежит в PG на момент cutover, каким бы ни был размер;
- если снятый sha совпал с заводским — origin всё равно `legacy`, не `manual`. UI не имеет права подписать это «Изменена в админке».

Cutover и любая пакетная активация — одна транзакция PostgreSQL:

1. `SELECT pg_advisory_xact_lock(hashtext('prompt_release_apply'))` (прецедент `chat_params.ADVISORY_LOCK_SQL`);
2. снимки + вставки ревизий + вставки активаций + `UPDATE`/`UPSERT` затронутых `bot_settings` и снятие устаревших chat override;
3. commit;
4. только после commit обновить память `ConfigCache` и инвалидировать кэш `chat_params` существующим `NOTIFY chat_params_updated`.

Падение до commit — в БД ничего нет, следующий старт повторяет cutover. Падение после commit — журнал и активный текст согласованы, повтор видит `applied_revision == code_revision` и делает no-op. Второй процесс берёт тот же advisory lock, после ожидания видит уже применённую ревизию и не пишет второй раз. Отдельный воркер не нужен: сегодня это один старт `bot.py` после `cache.init()`; замок закрывает гонку двух процессов.

PG недоступен: как сейчас у `migrate_prompt_canons` — skip с INFO, ничего не активировать «из констант поверх журнала». Кодовые дефолты при недоступном PG остаются прежним fail-open рантайма. Это не новая заводская публикация.

Пакет взаимозависимых промптов одного релиза — один commit. Частичная смесь старых и новых контрактов запрещена. Ошибка одного ключа откатывает весь пакет, активные тексты остаются прежними, `ERROR` с `block_id` / `detail_code`, без тела промпта.

Расхождение после аварии (журнал говорит `applied`, а `bot_settings` другой): не угадывать. `ERROR` `activation_drift`. Источник активного текста на этот старт — PG-значение (последняя долговечная запись). Если его sha ещё не в `prompt_revisions`, дописать снимок `origin=legacy`, `reason=drift_recovery`. Заводской текст заново не включать, пока метка не новее `factory_revision_applied`.

## 1.5 Scope

Существующее наследование не заменять:

- глобальный слой — `bot_settings` / `hot.get`;
- чат — `chat_params.overrides`, побеждает глобал (`resolve_chat_speech`);
- нет слоя — `factory_text`, `source=default`.

`PromptBlockSpec.scope` остаётся объявлением (`global` / `global_chat` / `code`). Настройки одного Telegram-чата в другой не перетекают.

Новая заводская метка обновляет эффективный промпт, а не только глобальную строку:

- глобальное значение становится заводским текстом;
- per-chat override этого `block_id`, у которого нет более поздней ручной активации поверх **этой** метки, снимается с эффективного пути: текст override уходит в ревизию `origin=legacy` или `manual` (если уже был в журнале как manual), ключ удаляется из `overrides`. Иначе старый override прячет новый заводской шаблон — это запрещено `EVOL-016`;
- ручной override, созданный **после** применения этой метки (`factory_revision_applied` ручной активации равен текущей метке), рестарт не снимает. Следующая новая метка снимает и его, сохранив в истории.

`code`-блоки без `pg_key` в `bot_settings` не копировать. Активный текст = `factory_text()`. При смене метки пишется ревизия `origin=factory` без второго хранилища. Пайплайн и так читает константу.

## 1.6 Как расширяется реестр, что меняется, что удаляется со старта

Расширять, не заменять.

Оставить как есть по смыслу:

- `PromptBlockSpec`, `all_blocks`, `block`, `by_pg_key`, `block_for`, `unregistered_catalog_keys`;
- `sha12`, `factory_text`, `factory_default`, `factory_revision`, `factory_texts`, `factory_set_fingerprint`, `FACTORY_SET_SHA256_12`;
- `registry_view` (добавить поля печатей и активной ревизии, не ломая старые ключи);
- `suppress_legacy_speech` и `CFG07A_PAYLOAD_CLEAN_KEYS` — это чистка известных маркеров на сборке payload, не шлагбаум миграции. В этой волне не расширять и не делать из них правило активации. PG-текст они не переписывают.

Добавить в `prompt_registry.py`:

- `declare_prompt(...)` — единственная точка объявления новых блоков. `_pg_blocks` и `_CODE_BLOCKS` собираются через неё. Декоратор на константах доменных модулей не вводить: тексты живут в `*_prompts.py`, каталог резолвит их строкой `code_source` (`pg_db.resolve_code_source`), декоратор даст цикл импортов и второй список;
- `FACTORY_REVISION_SEALS`;
- `activation_plan(...)`;
- `revision_id_for(...)`.

Изменить `resolve_speech_value`:

- перестать подменять persisted-текст заводским только из-за `provenance_missing` / `provenance_mismatch`. Это и есть тихий сброс ручной правки на каждом чтении. После cutover активный PG-текст и есть эффективный текст;
- `is_legacy_incompatible` / `WITHHELD_LEGACY_CLASS` оставить: известные токсичные слепки можно хранить и сравнивать, но в LLM не отправлять. Подмена на заводской текст + диагностика, один аудит-событие, не WARN на каждый старт за факт «текст другой»;
- 1788-символьный narrator в классификации токсичных хешей этого worktree нет. После снимка он доступен для отката, cutover включает заводской `summary-narrator-legfix`.

Добавить в `prompt_factory.py` (писатель уже здесь, новый сервис не заводить):

- `import_legacy_snapshots(cache)`;
- `apply_release(cache, *, release_id)`;
- `write_versioned_value(...)` — единственная запись активного текста: ревизия + активация + PG в одной транзакции. `write_speech_value` становится обёрткой над ней (`kind=manual_edit`);
- `activate_revision(block_id, revision_id, *, scope, chat_id, actor)` — откат и вперёд. Несовместимая / `retired` ревизия не включается, прежняя активная остаётся;
- `list_revisions` / `diff_revisions` — данные для `EVOL-017`, без UI в этой волне. Diff — по существующему `difflib` в `prompt_factory`, не новый движок.

`bot.py`: вызов `migrate_prompt_canons(cache)` заменить на `apply_release(cache, release_id=...)`. `migrate_core_owner_patch` со старта убрать: это строковая правка авторского Core на каждом запуске и она противоречит «рестарт без новой метки ничего не меняет». Абзацы, которые уже входят в заводской Core, доедут cutover-активацией заводской ревизии, а не патчем.

`prompt_migrations.py`: `PROMPT_MIGRATIONS`, `rollback_prompt_canons` и строковые ступени больше не вызываются стартом и не решают активацию. Модуль не удалять в этой волне (на нём висят байт-тесты и `PREV_*`). Функции пометить устаревшими; если их всё же вызвали — `ERROR` и отказ, без записи. `PREV_*` константы не массово удалять.

Провенанс `character.prompt_history.provenance` больше не является шлагбаумом effective-слоя. Одноразово перенести `items` в `prompt_revisions`: `owner_edit` → `manual`, `factory_reset` → `factory`, `backup_restore` → `restored`. Время брать из поля `at` записи, если оно есть; не выдумывать автора, если `by` пуст.

## 1.7 Регистрация будущих промптов и CI

Новый постоянный промпт объявляется только через `declare_prompt` (каталожный ключ + метаданные, либо `code_source` для текста в коде). Отдельная миграция «по имени ключа» запрещена.

CI — расширить `tests/test_soul1_registry_completeness.py`, не второй прогонщик:

1. `unregistered_catalog_keys() == ()` — уже есть, оставить.
2. Для каждого блока печать равна `(FACTORY_REVISION_LABELS[id], sha12(factory_text(id)))`. Расхождение = смена текста без бампа метки либо бамп без печати.
3. `factory_set_fingerprint() == FACTORY_SET_SHA256_12` — оставить.
4. Grep-аудит, реалистичный для этого репозитория: обойти `services/` и `handlers/`, пропустить `tests/`, `prompt_migrations.py`, сами `PREV_*` / `LEGACY_*`. Найти присваивания имён `^[A-Z][A-Z0-9_]*PROMPT$` (и `*_SYSTEM$`, если значение — тройная кавычка длиннее 80 символов). `module.attr` обязан встречаться в `code_source` какого-либо блока. Исключение — явный `PROMPT_AUDIT_ALLOWLIST` в `prompt_registry.py` с причиной в одну строку (ложные константы, не уходящие в LLM). Пустая причина не проходит.
5. Не сканировать тела переписки, tool results и f-string сборки запроса: это не шаблоны. Аудит ловит необъявленные константы, а не каждый динамический кусок.

Первичное заполнение `FACTORY_REVISION_SEALS` Builder генерирует из текущего кода в том же коммите, что и тест. Руками хеши не выдумывать.

## 1.8 Наблюдаемость

INFO, не WARN, для импорта, активации, ручной правки, отката: `block_id`, `sha12`, `scope`, `chat_id` если есть, `release_id`, `kind`, `outcome`. Тело промпта и секреты в лог не писать.

WARN/ERROR только при: PG-ошибке записи, `integrity_label_unchanged`, `activation_drift`, `schema_incompatible` на попытке включения, срыве пакета. Повторный рестарт эти ERROR не плодит, если состояние не изменилось: один ERROR на попытку применения, не на каждое чтение.

## 1.9 Матрица тестов (EVOL-018)

Файл: `tests/test_evol_prompt_activation.py`. Без Telegram и без LLM. Кэш — фейк с тем же `get`/`set`, транзакция — фейк, который умеет откатить пакет.

Обязательные переходы:

1. `factory A → manual M → factory B` (новая метка) → активен B, M в истории, origin manual.
2. Рестарт без новой метки после M → активен M, новых ревизий нет.
3. `manual/restore A` после B → активен A, рестарт не возвращает B.
4. Затем `factory C` (ещё одна новая метка) → активен C, A и M на месте.
5. Рестарт после C без новой метки → C не сбрасывается и не дублируется.
6. Неизвестный текст (не равный ни одному `PREV_*` и не равный заводскому; кейс narrator, длина не зашита) → снимок `origin=legacy`, время = время импорта, затем cutover включает заводской. Повторный старт no-op.
7. Два параллельных `apply_release` → одна активация, второй `skipped_same`.
8. Исключение на втором ключе пакета → ни один ключ пакета не изменён.
9. Global и два `chat_id`: override чата 1 не виден чату 2. Новая метка снимает старый override обоих чатов в историю. Override, записанный после метки, рестарт не снимает.
10. Смена заводского текста без смены метки → план `integrity_reject`, `cache.set` не вызван.
11. Переименованный/снятый ключ: старые ревизии читаются, `retired=true`, активный указатель осиротевшего ключа не молчит — `registry_view` помечает `retired`.
12. `schema_compat`, не входящий в пустой «совместимо всё» список блока, не активируется; просмотр ревизии доступен.
13. Пайплайн narrator/direct читает активный PG-текст, а не константу и не withheld-подмену, если текст не `legacy_incompatible`.
14. Grep-аудит: фиктивная необъявленная `SOMETHING_PROMPT = """..."""` роняет тест; объявленная через `declare_prompt` — нет.

Старые тесты, которые требуют `migrate_prompt_canons` → «кастом не трогаем», переписать на этот автомат. Не ослаблять байт-эталоны заводских текстов.

## 1.10 Файлы этой волны (промпты)

Трогать:

- `services/pg_db.py` — DDL;
- `services/database.py` — шаг v38 по образцу v35;
- `services/prompt_registry.py` — печати, `declare_prompt`, `activation_plan`, правка `resolve_speech_value`;
- `services/prompt_factory.py` — транзакция записи и `apply_release`;
- `bot.py` — замена вызова старта;
- `services/prompt_migrations.py` — только снятие со старта и запрет записи, не чистка `PREV_*`;
- `tests/test_soul1_registry_completeness.py`, новый `tests/test_evol_prompt_activation.py`;
- точечно тесты, которые зовут `migrate_prompt_canons` как шлагбаум.

Не трогать: `web/index.html` (UI каталога — `EVOL-017`), шейдеры, `polygon-background.js`, `aurora-flow.js`.

Оценка касания: порядка 400–700 строк логики плюс тесты. Не переписывать реестр.

---

# CONTRACT 2 — тонирование стекла по здоровью

## 2.1 Что реально рисует карточки

Три разных механизма. Путать их нельзя.

1. Vendored `@liquidglassjs/core` 0.5.3 монтируется только на `[data-glass-surface]` (`web/static/glass.js`). Функциональные карточки сознательно сняты с библиотеки (комментарий HOTFIX10 в `glass.js`: монтирование на `.status-block` давало белый frosted-fallback). `mountGlass` пишет скаляр `tint` в CSS `--g-tint` (дефолт библиотеки 12, обёртка проекта передаёт `tint: 6`). Цвет этой дымки — `--glass-paper` (дефолт `#fff`). Слой `.ps-glass__tint` в vendored CSS:

   `background: color-mix(in srgb, var(--glass-paper, #fff) calc(var(--g-tint) * 1%), transparent)`.

   В опциях `mountGlass` (`te` / `readGlassOptions`) нет hue/color: `radius, depth, profile, dome, strength, edge, glow, chroma, blur, tint, spec, vibrancy, backdrop, source`. `tint` — сила белой/paper-дымки, не аварийный цвет. Шейдер displacement и `feColorMatrix` карты линзы — не API тонирования.

2. Карточки Статуса/Аналитики — проектный материал, не эта библиотека. `.card` и `[data-glass="a|b"]` в `web/static/app.css`: `background-color: var(--glass-bg)` = `rgba(21, 27, 42, 0.5)`, `backdrop-filter` frost и, на tier A, `url(#lg-lens)`. `::before` — уже существующий tint/sheen (`--lg-tint-hero`), без фильтра на тексте. `::after` — кромка.

3. `web/static/glass-refraction.js` — слой преломления, когда `url()` в `backdrop-filter` недоступен (Android WebView/WebKit). Он копирует полигональный фон в canvas и поверх кладёт **ту же** подложку, что `getComputedStyle(el).backgroundColor`, с тем же alpha (`surfaceTint`, кап 0.8). Цвет снимается в `rebuild()`, не каждый кадр. Фильтр слоя — `blur + saturate + url(#lg-refract-lens-N)`. Второй backdrop-filter слой себе не ставит.

Вывод: у библиотеки нет совместимого hue-API для карточек здоровья, а монтировать её на эти карточки нельзя — это уже ломало оптику. Решение не откладывается: цвет модулируется у **существующего** материала карточки.

## 2.2 Замороженный путь тонирования

Меняется только RGB заливки стеклянного корня. Alpha остаётся байт-в-байт alpha нормального состояния. `backdrop-filter`, `url(#lg-lens)`, blur, saturate, радиус, рамка, `::before`/`::after`, z-index, padding, размеры — не меняются.

Токены, добавить в `:root` `app.css` рядом с `--glass-bg` / `--err` (`#F07178` = rgb(240, 113, 120)). Смешение задано явно, чтобы Builder не подбирал оттенок:

- норма, alpha 0.5: без правила, остаётся `--glass-bg` `rgba(21, 27, 42, 0.5)`;
- degraded, 32% `--err` + 68% базы: `rgba(91, 55, 67, 0.5)`;
- failed, 55% `--err` + 45% базы: `rgba(141, 74, 85, 0.5)`;
- если корень уже на `--glass-bg-strong` (alpha 0.85), те же RGB и alpha **0.85**, не 0.5. Атрибут `data-health-material="strong"` ставит только такой корень. Обычные карточки — `data-health-material="bg"`.

Селектор из двух атрибутов, без `!important`, чтобы победить `.card` и `[data-glass="a"]` и не задеть соседей:

```css
[data-health-state="degraded"][data-health-material="bg"] {
  background-color: rgba(91, 55, 67, 0.5);
}
[data-health-state="failed"][data-health-material="bg"] {
  background-color: rgba(141, 74, 85, 0.5);
}
```

`normal`, `unknown`, `disabled` правил `background-color` не получают. Красной заливки у них нет.

Почему рефракция сохраняется: displacement остаётся в том же `backdrop-filter` / том же SVG-фильтре canvas. Меняется цвет полупрозрачной подложки, которая и раньше лежала поверх преломлённых пикселей с тем же alpha. Это цветовая составляющая текущего материала, не новый слой и не второй blur.

Слой `glass-refraction.js`: добавить `refreshTint(el)`. На смене `data-health-state` перечитать `surfaceTint(el)` в уже существующую запись и не пересоздавать canvas, не менять размеры, маску, filter id, z-index. Если записи слоя нет — no-op. Вызов из компонента после смены атрибута: `window.__GlassRefraction.refreshTint(root)`. Без этого layer-носитель держал бы старый цвет до resize.

Переход: на `[data-health-state]` только `transition: background-color 420ms cubic-bezier(0.2, 0, 0, 1)`. Не анимировать filter, backdrop-filter, transform, box-shadow, width, height. `prefers-reduced-motion: reduce` — `transition: none`, состояние меняется сразу.

Внешнее свечение в этой волне **не добавлять**. Сетка `.status-block__grid` имеет gap 12px; даже мягкий красный `box-shadow` читается как авария соседа. Существующий `--card-shadow` не перекрашивать. Заметность даёт заливка всей стеклянной площади плюс текст и иконка.

`glass.js` `OPTS.tint = 6` не менять. Это декоративные `[data-glass-surface]`, не здоровье.

## 2.3 Компонент

Имя: `health-glass-surface`. Живёт в `web/app.js` (Vue 3 Options API, zero-build), шаблон использует существующий корень карточки. Второй DOM-узел вокруг карточки запрещён: компонент **заменяет** текущий корневой элемент карточки, классы и `data-glass` проходят на этот же корень (`inheritAttrs`). Геометрия, радиус, padding, border-width не задаются компонентом.

Props:

- `subsystem` — стабильный id (`bot`, `heartbeat`, `memory`, `vision`, `experience`, …);
- `scope` — `global` или конкретный `chat_id`;
- `source` — объект адаптера (ниже), не строка лога и не сырой HTTP-статус.

Корень получает `data-health-subsystem`, `data-health-scope`, `data-health-state`, `data-health-material`. Состояния компонента: `normal | degraded | failed | unknown | disabled`. Входное `problem` отображается как `degraded`.

Рядом с заголовком обязателен текст, не только цвет:

| state | текст | бейдж (уже есть) |
| --- | --- | --- |
| normal | Норма | `badge-ok` |
| degraded | Проблема | `badge-err` |
| failed | Сбой | `badge-err` |
| unknown | Неизвестно | `badge-warn` |
| disabled | Выключено | `badge-muted` |

Плюс краткая причина и время последнего достоверного состояния, если источник их дал. `aria-live="polite"` вешается на строку статуса, не на всю карточку. `aria-label` корня включает имя подсистемы, текст статуса и причину. Иконка дублирует статус (существующие Material Symbols, без нового набора). Hover/pressed не снимают `data-health-state`.

Клик по строке проблемы ведёт на уже существующий маршрут этой подсистемы или фильтр аналитики, если такой href уже есть у карточки. Новый маршрут не выдумывать. Нет href — строка не притворяется ссылкой.

Общий `.status-block` (сердцебиение + бот + сервер внутри одной стеклянной карточки, `web/index.html` около 9877) **не дробить** и не красить целиком из-за одной секции. Это смена layout, её нет в этой волне. У секций внутри общей карточки — текст, иконка и aria. Красное стекло — только у корня, который уже является отдельной стеклянной карточкой одной подсистемы (например `.status-hero` для бота, отдельные `.card` модулей). Разведение секций по своим стеклянным корням — дело `EVOL-033`, тем же компонентом, без нового рендерера.

Соседний здоровый корень не наследует атрибут. Custom property не ставить на `:root` и не на `.status-block`, если внутри несколько подсистем.

## 2.4 Единый источник статуса

Адаптер — функция в `web/app.js`, имя `healthStateFrom(subsystem, payload)`. Не парсит текст логов, слово `error`, CSS и произвольный процент виджета. Не создаёт таблицу и не ходит в новый endpoint.

Уже существующие входы (проверены в worktree):

| Подсистема | Откуда | Что считается состоянием |
| --- | --- | --- |
| Бот | `GET /api/status` → `status_service.build_snapshot`, поле `bot.state` | `running` / `polling` → normal; `polling_error` → failed; останов действием владельца → disabled; нет поля → unknown |
| Сердцебиение | уже посчитанный `hbState` после `_heartbeatTransition` (`web/app.js:17851`) | `healthy` → normal; `warning` → degraded; `critical` → failed; `unknown` → unknown. Пороги 0.90/0.70/0.65 и dwell N=2 не копировать и не заменять. Бейдж и стекло читают один и тот же `hbState` |
| Память | `GET /api/memory/health` | счётчики и нули — не авария. Ошибка запроса или `available` отсутствует так, что данных нет → unknown. Красный только если отдельное уже существующее поле явно говорит о сбое функции, а не о тишине фактов |
| Сон / опыт / инициатива | `GET /api/memory/cognition/status` и существующие флаги ворот | выключенный gate / флаг владельца → disabled, не failed. «Нет новых уроков» → не failed |
| Медиа | `GET /api/status/media-health` | эвристика `text_scan` / HTTP-успех списка — не failed. Нет данных → unknown |
| Vision | существующий результат проверки модуля | HTTP 200 сам по себе не normal и не failed (`EVOL-019`). Пока нет отдельного вердикта распознавания — unknown, не красное стекло |
| Процесс | `GET /healthz`, `GET /api/health` | никогда не красят карточку |

Не ставят красный сами по себе: HTTP 200, один WARN, устаревший снимок, пустая выборка, `errors_total` с момента старта, скачок метрики короче dwell сердцебиения, чужой чат, чужая подсистема, выключенный модуль.

Устаревшие данные: если источник уже пометил снимок stale (сердцебиение делает это в `_heartbeatTransition` → `unknown`), стекло возвращается к нормальному материалу и текст «Неизвестно» / «данные устарели», с датой последнего достоверного состояния. Фронтовый таймер «подержать красный» запрещён. Снятие красного — только смена достоверного состояния источника.

Scope: карточка чата не красится аварией другого чата. Глобальная сводка не красится частной аварией одного чата; она показывает затронутый чат текстом, если это поле уже есть в payload. Чужие подробности за RBAC не добавлять: адаптер не запрашивает то, что текущий API и так не отдаёт этой роли.

Интенсивность: degraded и failed оба красные и оба не норма. Failed заметно сильнее (55% против 32%), оба остаются с исходным alpha, текст на них читается существующими `--text-1` / `--err-text`.

## 2.5 Проверка

Без сообщений в Telegram.

1. Фикстуры состояний: normal → degraded → failed → normal; warning сердцебиения → degraded и не failed; один сэмпл выше порога до dwell → ещё normal; disabled; unknown; stale; HTTP 200 без вердикта функции → не красный; чужой `chat_id` не красит.
2. Соседние корни: у проблемного `background-color` из таблицы выше, у соседа вычисленный фон равен норме.
3. Оптика: на движущемся полигональном фоне (`polygon-background.js` + `aurora-flow.js`) сквозь normal и tinted видны те же преломлённые формы. Сравнить скриншоты Playwright и Browser Use. Доказательство — не статичная непрозрачная плашка.
4. Вычисленный `backdrop-filter` корня в normal и failed совпадает, включая `url(#lg-lens)` на tier A и его отсутствие на tier B. Alpha фона 0.5 или 0.85, как у материала корня, не 1.
5. Ширины 320, 768, 1280, 1920. Смена состояния не меняет `getBoundingClientRect` корня.
6. `prefers-reduced-motion`: нет transition, состояние мгновенное, фон не останавливать ради теста стекла (пауза фона — уже существующий `html.lg-bg-paused`, её не расширять).
7. Canvas сердцебиения не пересоздаётся из-за смены `data-health-state`.

## 2.6 Не трогать

- `web/static/vendor/liquidglass.core.0.5.3.min.js` и `.css`;
- `web/static/glass.js` (`OPTS`, `mountGlass`, селектор `[data-glass-surface]`);
- `web/static/polygon-background.js`, `web/static/aurora-flow.js`;
- шейдер/карту линзы, `--lg-frost`, `--lg-frost-hero`, `url(#lg-lens)`, blur, saturate, alpha нормального `--glass-bg`;
- радиус, border-width, padding, z-index, layout `.status-block`;
- пороги `_heartbeatTransition` и legacy-пороги 0.5/0.8.

Файлы волны стекла: `web/static/app.css`, `web/app.js`, точечные корни в `web/index.html`, аддитивный `refreshTint` в `web/static/glass-refraction.js`.

---

# Параллельность, риск, следующий шаг

| Область | Класс |
| --- | --- |
| `services/prompt_*.py`, `bot.py`, тесты активации | `PARALLEL_SAFE` относительно стекла |
| `services/database.py`, `services/pg_db.py` | `SERIALIZE` (схема; в этой волне пишет только лейн промптов) |
| `web/app.js`, `web/index.html`, `web/static/app.css`, `glass-refraction.js` | `PARALLEL_SAFE` относительно промптов, `SERIALIZE` между собой |
| `web/static/glass.js`, vendor, polygon, aurora | `READ_ONLY_PARALLEL` |
| UI истории версий `EVOL-017` | `BLOCKED_BY` API `list_revisions` / `activate_revision` этого контракта |
| Разрезание `.status-block` на отдельные стеклянные корни | `BLOCKED_BY` layout `EVOL-033`; до этого только текст+иконка внутри общей карточки |

Риск промптов: **R2** (данные PG, смягчено снимком до записи и одной транзакцией). Риск стекла: **R1** (обратимый CSS, оптика закреплена запретом трогать фильтр и alpha).

Открытого продуктового выбора нет. Развилки закрыты кодом и текстом владельца: версия схемы 38, журнал в PostgreSQL, активация по метке, 1788 только как снимок факта, tint — RGB существующей подложки, общее стекло `.status-block` не режется в этой волне.

Следующий шаг: Builder реализует оба контракта в своих файлах, без второго хранилища и без монтирования liquidglass на карточки здоровья.
