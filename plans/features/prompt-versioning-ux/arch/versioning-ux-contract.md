# EPIC-PROMPT-VERSIONING-UX-01 — контракт версионирования и UX редакторов

Статус: **FROZEN** для реализации. Архитектурное решение по пакету
`plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md`
(дословный снимок `plans/current_task.md` 5535–5647).
Заменяет по baseline-семантике `docs/prompt-versioning-contract.md` §3–§4 только
в части owner baseline (документ дополняется, не переписывается).
Проверено на фактическом HEAD ветки `evol/impl` (`bce5e781`, worktree
`.../hotfix-meme-publication-initia-d78f499866ee-6ef91e44`).

Ключевые запреты пакета (не обсуждаются): тексты промптов не меняются
(включая `initiative.meme.joke` / `initiative.meme.image`), второго реестра и
второго журнала нет, новых LLM-вызовов нет, искусственных бюджетов нет,
разрушающей миграции нет, human gate на технические развилки нет.

---

## 1. Текущее состояние: факты с привязкой к коду

### 1.1 Схема журнала (существующая, менять не нужно)

`services/prompt_release_policy.py:61-102` (`JOURNAL_DDL`), дословный дубль в
`services/pg_db.py:577-615` (создаётся при инициализации пула; ленивый
`ensure_journal` — совместимый путь, `:604-611`).

`prompt_revisions`: `revision_id TEXT PRIMARY KEY`, `block_id TEXT NOT NULL`,
`pg_key TEXT NOT NULL DEFAULT ''`, `scope TEXT NOT NULL`,
`chat_id BIGINT`, `origin TEXT NOT NULL`, `content_sha12 TEXT NOT NULL`,
`body TEXT NOT NULL`, `factory_revision TEXT NOT NULL DEFAULT ''`,
`schema_compat TEXT NOT NULL DEFAULT ''`, `release_id TEXT NOT NULL DEFAULT ''`,
`actor TEXT NOT NULL DEFAULT ''`, `reason TEXT NOT NULL DEFAULT ''`,
`source_updated_at TEXT NOT NULL DEFAULT ''`,
`retired BOOLEAN NOT NULL DEFAULT false`, `created_at TIMESTAMPTZ DEFAULT now()`;
индекс `idx_prompt_revisions_block (block_id, scope, created_at)`.

`prompt_activations`: `activation_id BIGSERIAL PRIMARY KEY`, `block_id`,
`scope`, `chat_id BIGINT`, `revision_id TEXT DEFAULT ''`,
`factory_revision_applied TEXT DEFAULT ''`, `kind TEXT NOT NULL`,
`outcome TEXT NOT NULL`, `release_id`, `actor`, `detail_code`,
`created_at TIMESTAMPTZ`; индекс
`idx_prompt_activations_latest (block_id, scope, activation_id DESC)`.

**Гарантия неизменяемости — не схема, а дисциплина записи.** В БД нет ни
триггера, ни `REVOKE`: единственная защита — (а) `revision_id` =
`rev:sha12(block_id\0scope\0chat\0origin\0content_sha12)`
(`services/prompt_registry.py:694-703`) и (б) `ON CONFLICT (revision_id) DO
NOTHING` (`_INSERT_REVISION_SQL`, `prompt_release_policy.py:143-151`). Ни один
код не делает `UPDATE prompt_revisions ... SET body`. Единственный `UPDATE` —
`retired` (`_MARK_RETIRED_SQL`, `:201-203`). Прямой SQL-`UPDATE body` возможен
и ничем не остановлен — это известная граница, см. §7 (R5).

### 1.2 Как сегодня пишутся ревизии и активации

Три разных механизма, а не один:

| Механизм | Где | Свойства |
|---|---|---|
| `apply_release` (релизная поставка) | `prompt_release_policy.py:932-1029`; лок+транзакция `:994-1009` | revisions+activations+значение одной PG-транзакцией под `APPLY_LOCK_SQL` (`:58`) |
| `write_versioned_value` (глобальная ручная правка) | `:1486-1584` | одна транзакция, но `read_applied` **до** транзакции (`:1515`) и «текущий текст» — из памяти кэша (`:1524`, `_spec_current_text`), а не из PG |
| `record_manual_activation` (журналирование «постфактум») | `:1599-1644` | **best-effort**: значение уже записано другим путём, сбой журнала ловится и проглатывается (`:1632-1638`) |

Идентификаторы «включено/применено» читаются из последней строки
`prompt_activations` с `outcome ∈ {applied, skipped_same}`
(`_LAST_APPLIED_SQL`, `:159-166`). Журнал — не второй источник правды:
эффективные байты по-прежнему в `bot_settings` / `chat_profiles.overrides`.

### 1.3 Что `apply_release` делает с ручной правкой

`_apply_scope_release` (`:1197-1321`) + чистый автомат
`services/prompt_registry.py:739-775` (`activation_plan`):

- первый запуск (`has_import=false`) → `PLAN_LEGACY_CUTOVER`: снимок текущих
  байтов как `origin=legacy` (`:1256-1284`), затем активация заводской
  ревизии (`:1286-1311`);
- та же метка → `PLAN_NOOP`: ни строки, ни записи; ручная правка остаётся
  активной (`:1216-1236`);
- **новая метка → `PLAN_ACTIVATE`: заводской текст пишется поверх ручной
  правки** (`:1286-1297`), прежний текст остаётся ревизией;
- для `scope=chat` новая метка **снимает чатовый override** этого блока
  (`:1313-1321`), чтобы старый override не прятал новый шаблон;
- расхождение журнала и PG → `activation_drift`, снимок + ERROR
  (`_check_activation_drift`, `:1333-1379`).

Это и есть то самое «новая заводская ревизия перекрывает ручные правки»,
которое владелец запрещает **для закреплённого им scope** (§4 ТЗ).

### 1.4 Точки записи, которые обходят журнал (полный список)

Файл:строка — фактический путь записи значения без атомарной ревизии/активации.

1. `web/api/routes.py:4155-4259` `POST /api/initiative/meme-settings` —
   `prompt_joke`/`prompt_image` пишутся через
   `_write_chat_overrides_with_retry` (`:4245`, внутри `:642`/`:650`/`:660`
   → `chat_params.set_chat_params`). **Журнал не вызывается вообще** —
   ни ревизии, ни активации. Пустая строка = `removals` (`:4213-4220`,
   `:4239-4240`) → override удаляется без снимка последнего текста.
2. `web/api/routes.py:1073-1125` `DELETE /api/config/chat/{key}` — удаляет
   override любого ключа, включая промптные (`:1102-1115`), без ревизии.
3. `web/api/routes.py:666-788` `POST /api/config` (чат) — значение пишется
   первым (`:764`), журнал — после и best-effort
   (`_prompt_record_saved_snapshots`, `:3320-3351`, где сбой ловится `:3341-3344`).
4. `web/api/routes.py:1251-1376` `POST /api/config` (global) — `cache.set_many`
   (`:1353-1360`), журнал после (`:1365-1368`), тот же best-effort.
5. `services/prompt_factory.py:465-609` `write_speech_value`:
   - чат: запись через `_write_chat_speech_value` (`:515-522`), затем
     best-effort `record_manual_activation` (`:524-530`);
   - **global: журнал недоступен → «прежний путь» с записью значения без
     журнала** (`:570-586`) — прямое нарушение §3.2 ТЗ.
6. `services/prompt_factory.py:390-458` `apply_factory_reset` — значение
   (`_store_spec_value`, `:430`), затем best-effort
   `record_manual_activation` (`:434-442`).
7. `services/prompt_factory.py:829-916` `restore_backup` — `cache.set` (`:889`),
   затем best-effort `record_manual_activation` (`:892-900`).
8. `services/prompt_factory.py:693-733` `reset_chat_override` — удаляет override
   (`:721-727`), снимка нет (нарушение §3.4 ТЗ).
9. `web/api/speech.py:2692-2751` `POST /speech/block/{id}/reset` (mode=chat) →
   п.8; `:2620-2663` `POST /speech/block/{id}` → п.5; `:2754-2806`
   `.../rollback` → п.5 (источник — bounded `character.prompt_history`).
10. Старый bounded-журнал `prompt_factory._append_history` (`:420` и др.,
    `HISTORY_MAX_PER_BLOCK=12`) — заморожен после cutover
    (`prompt_release_policy.py:1032-1038`), но на путях 5–7 ещё пишется.

Не являются обходом (вне scope текстов промптов): `web/api/speech.py:2822-2900`
`_write_core_meta` (только `detail_level`/`enabled`), `:3060-3140`
(документ Expression), `web/api/routes.py:925-1020` (BYOK-ключи).

### 1.5 Факты, на которые опирается UX

- `GET /api/initiative/meme-settings` отдаёт `template.placeholders` числом
  (`web/api/routes.py:4100-4106`), экран печатает `{joke}: N`
  (`web/index.html:2159-2165`).
- Карточка мемов печатает в основной строке `ревизия <N> (заводская: fac:…)`
  (`web/index.html:2125-2127`, `:2156-2158`) — это и есть недопустимый сырой
  технический шум по §2.1 ТЗ.
- Готовый «библиотечный» редактор промптов с историей уже существует:
  `web/index.html:4063-4345` (`data-workspace-prompts`, `data-prompt-editor`,
  `data-prompt-history*`), второй экземпляр истории `:4758-4800`, состояние
  `web/app.js:3283-3296` (`promptHistory`). Мета-строка там тоже техническая:
  `web/index.html:4188-4195` (`prompt_id`, `активная`, `sha`).
- HTTP-слой истории/активации уже полный: `GET /api/prompts/catalog`
  (`:3474`), `GET /api/prompts/{key}/versions` (`:3513-3566`),
  `GET /api/prompts/revisions/{id}/source` (`:3413`),
  `GET /api/prompts/revisions/diff` (`:3378`),
  `POST /api/prompts/{key}/activate` (`:3569-3626`). Точка инъекции журнала в
  тестах — `_prompt_journal(cache)` (`:3142-3144`); **все новые пути обязаны
  резолвить стор через неё**, иначе тестовые двойники перестанут работать.

---

## 2. Owner baseline: расширение существующей PG-политики

### 2.1 Сущность

**Baseline — указатель на существующую неизменяемую ревизию.** Тело текста не
копируется, второго хранилища нет, второй реестр не появляется.

Хранение — **событие в существующем журнале активаций**, а не новая таблица и
не новая колонка:

- `kind='baseline_assign'`, `revision_id=<существующая ревизия>`,
  `actor`, `created_at`, `detail_code='baseline:<origin>'`;
- `kind='baseline_clear'`, `revision_id=''` — назначение снято.

Действующий baseline для `(block_id, scope, chat_id)` = **последнее** такое
событие по `activation_id`:

```sql
SELECT revision_id, activation_id, actor, detail_code, created_at
FROM prompt_activations
WHERE block_id = $1 AND scope = $2
  AND (chat_id = $3 OR (chat_id IS NULL AND $3 IS NULL))
  AND kind IN ('baseline_assign', 'baseline_clear')
ORDER BY activation_id DESC LIMIT 1
```

`kind='baseline_clear'` → baseline отсутствует (явное снятие, а не «не было»).
Индекс не добавляем: существующий `idx_prompt_activations_latest` покрывает
поиск по `(block_id, scope)` и порядку; при реальной деградации — аддитивный
индекс `(block_id, scope, chat_id, activation_id DESC)`, отдельным решением.

**DDL-дельта: отсутствует.** Ни новой таблицы, ни новой колонки, ни изменения
типов. Миграция «назначить всем текущее» не выполняется: без событий baseline
не существует ни у кого, поведение текущих промптов не меняется (§4 ТЗ,
последний абзац).

### 2.2 Почему исход события, а не `applied`

`read_applied` берёт последнюю строку с `outcome ∈ {applied, skipped_same}`
(`:159-166`). Поэтому baseline-события и событие снятия override пишутся с
**`outcome='recorded'`** — новое значение в `ACTIVATION_OUTCOMES`
(`services/prompt_registry.py:721`), которого нет в «применяющем» множестве.
Следствия:

- указатель «активная ревизия» такими событиями не двигается (требование §4:
  «назначение не активирует»);
- откат кода безопасен: старая версия вообще не увидит эти строки в
  `read_applied` и не сочтёт базовую ревизию активной.

Новые `kind`: `baseline_assign`, `baseline_clear`, `baseline_restore`,
`chat_inherit_reset` (снятие override), `factory_restore` (возврат исходной из
кода). Расширение кортежей `ACTIVATION_KINDS` / `ACTIVATION_OUTCOMES` —
аддитивное; рантайм их не валидирует, тесты проверяют конкретные значения.

### 2.3 Транзакция и блокировки

Ровно та же дисциплина, что `activate_revision` (`:1698-1740`):

1. `store.ensure_journal()`;
2. `async with store.apply_lock():` — `APPLY_LOCK_SQL`
   (`pg_advisory_xact_lock(hashtext('prompt_release_apply'))`), **тот же ключ**,
   что у релиза: назначение baseline и релизная поставка взаимно исключены;
3. `async with store.transaction():` — все чтения (ревизия, текущий baseline,
   текущий effective-текст) внутри транзакции на `_tx_conn`;
4. `read_baseline` → валидации → `insert_activation(outcome='recorded')` →
   commit.

`SET LOCAL lock_timeout = '5s'` на транзакции записи: занятый лок → честный
503, а не бесконечное ожидание в UI.

### 2.4 Правила семантики (заморожены)

1. **Назначение не активирует.** `baseline_assign` меняет только указатель.
   Активный текст остаётся прежним; UI обязан сказать
   «Базовая версия изменена, действующий текст пока прежний».
2. **Миграция ничего не назначает.** Нет событий — нет baseline.
3. **Закреплённый scope не перетирается новой поставкой.** Для
   `(block, scope, chat)` с baseline новый shipped factory:
   ревизия `origin=factory` пишется в историю, значение **не** пишется,
   событие `kind='deploy_activate'`, `outcome='skipped_same'`,
   `detail_code='factory_superseded_pinned'`,
   `factory_revision_applied=<новый fac:…>`, `revision_id=<действующая
   активная ревизия>`. Указатель применённой заводской метки двигается →
   следующий рестарт — истинный no-op; дрейфа нет.
4. **Снятие назначения (`Снять назначение`)** пишет `baseline_clear` и не
   меняет активный текст. После снятия действует обычная релизная политика
   (§3 существующего контракта), то есть следующая новая метка снова
   активирует заводской текст.
5. **Чатовый baseline относится только к этому чату.** Другая группа не
   затрагивается. При снятии чатового override чат наследует **global
   effective**, а не свой baseline; для применения baseline нужна отдельная
   явная кнопка «Восстановить базовую для чата»
   (`baseline_restore` + активация).
6. **Восстановление базовой** = `activate_revision(baseline.revision_id)`
   (тот же путь, те же гейты `retired`/`schema_compat`), с
   `kind='baseline_restore'`.
7. **`Вернуть исходную из кода`** — отдельная активация (`kind='factory_restore'`)
   с подтверждением; baseline при этом **не снимается** (снятие — отдельное
   действие). Допускается только при целой печати блока
   (`pr.seal_integrity()` без замечаний и `sha12(factory_text)==sealed_sha`);
   иначе `reason='factory_unverifiable'`, значение не меняется.
8. **Копирование чужого scope** («сделать чатовый текст глобальным») — только
   как **новая** ревизия целевого scope (`origin='restored'`,
   `reason='copied_from_chat:<revision_id>'`); `revision_id` не
   перепривязывается.
9. **Несовместимость**: `retired` или непустой `schema_compat` вне
   `SUPPORTED_SCHEMA_COMPAT` (`:107`) читаются и сравниваются, но не
   активируются и не назначаются базовыми (`reason='schema_incompatible'` /
   `'revision_retired'`).

### 2.5 Rollback story

- Код откатывается на предыдущую версию: baseline-события остаются в
  `prompt_activations`, старая версия их игнорирует (`outcome='recorded'` не
  входит в «применяющие»), значение и активный указатель не затронуты.
- Если нужно убрать и следы: `DELETE FROM prompt_activations WHERE kind IN
  ('baseline_assign','baseline_clear','baseline_restore','chat_inherit_reset',
  'factory_restore')`. Ревизии не удаляются никогда.
- Схемного отката нет — схема не менялась.

---

## 3. Единый атомарный слой записи

### 3.1 Одна функция для всех путей

```python
@dataclass(frozen=True)
class PromptWriteItem:
    block_id: str                      # или pg_key — резолв через pr.block_for()
    text: str
    expected_updated_at: str | None = None   # per-key CAS (global token) / chat CAS

async def write_prompt_values(
    items: list[PromptWriteItem],
    *,
    scope: str,                        # "global" | "chat"
    chat_id: int | None = None,
    cache=None,                        # ConfigCache (память + pg-пул)
    store=None,                        # журнал; HTTP-слой передаёт _prompt_journal(cache)
    pg=None,                           # Pool-адаптер для chat_profiles
    actor=None,
    reason: str = "",
    kind: str = "manual_edit",
    origin: str = "manual",
) -> PromptWriteResult
```

`PromptWriteResult` (dict, ключи заморожены): `applied: list[str]`,
`skipped_same: list[str]`, `rejected: list[{key, reason}]`,
`prompt_snapshots: list[{key, revision_id, sha256_12}]`,
`chat_updated_at: str | None`, `journal_recorded: bool` (всегда `True` при
успехе; поле сохранено ради совместимости ответа `/api/config`).

Единственная точка записи значения промпта. `write_versioned_value`
становится тонкой обёрткой (совместимость вызовов и тестов), `record_manual_activation`
**удаляется из продакшн-путей** (остаётся только как deprecated-обёртка над
`write_prompt_values`, если её использует внешний вызов — иначе удаляется).

### 3.2 Семантика одной транзакции

Порядок внутри `write_prompt_values` (заморожен):

1. Резолв каждого элемента в `PromptBlockSpec`; блок без `pg_key` →
   `rejected: block_not_pg_managed` (значение не пишется).
2. Гейты значения (те же, что сегодня): пустая строка →
   `rejected: empty_value`; `withheld_classification == legacy_incompatible` →
   `rejected: legacy_incompatible`; для `prompts.meme_image` — существующий
   `_meme_template_guard` (`web/api/routes.py:4020-4031`, ≥2 `{joke}` → 422).
3. `store.ensure_journal()`; недоступен → `JournalUnavailable` → **ни одно
   значение не пишется**, HTTP 503.
4. `SET LOCAL lock_timeout='5s'`; `apply_lock()` (тот же advisory-ключ);
   `transaction()`.
5. Внутри транзакции читаются: текущее значение (`bot_settings` /
   `chat_profiles.overrides` **из PG**, не из памяти кэша), текущий
   `read_applied`, документ `pg_doc_field` (для Core) — всё на `_tx_conn`.
6. Для каждого элемента: ревизия (`_insert_revision_once`, идемпотентно по
   `revision_id`) → `skipped_same` при совпадении байтов (ревизия не
   дублируется, событие пишется) → иначе запись значения в ту же транзакцию.
7. `scope=chat`: полный `overrides`-набор читается **внутри** транзакции и
   пишется одним `set_chat_params(conn=_tx_conn, expected_updated_at=…)` —
   сохраняются CAS-токен, `chat_params_history`, `meta.updated_by`, `NOTIFY`.
8. Строка активации на каждый элемент (`kind`, `outcome`, `factory_revision_applied`
   из `read_applied`, `actor`, `detail_code=reason`).
9. Commit. Только после commit — синхронизация памяти кэша (`cache.set`,
   `invalidate_chat`) и инвалидация чат-кэшей; сбой синхронизации логируется,
   но **не** превращает уже совершённый commit в «не сохранено».

### 3.3 Отказы (заморожено)

| Ситуация | Результат |
|---|---|
| журнал/PG недоступен | `JournalUnavailable` → HTTP **503**, значение не записано, форма сохраняет несохранённый текст |
| `SET LOCAL lock_timeout`/лок занят | то же 503 (`reason='lock_timeout'`) |
| CAS-конфликт `chat_params` | `ChatParamsConflict` пробрасывается без изменений → **409** с `current_updated_at`/`conflicting`/`applied: []` |
| устаревший global-токен | `FactoryConflict` (существующий тип) → **409** |
| байты равны действующим | `200`, `outcome='skipped_same'`, `applied` не содержит ключ, событие `manual_edit/skipped_same` — новая текстовая ревизия не создаётся |
| блок не PG-управляемый | `rejected: block_not_pg_managed`, ничего не пишется |
| гейты значения | `rejected: <code>` → 422 |

**Возврата `journal_recorded=False` как успеха больше нет.** Best-effort путь
`prompt_factory.py:570-586` удаляется.

### 3.4 Кто вызывает (полная карта после изменения)

| Путь | Вызов |
|---|---|
| `POST /api/config` (global) | `write_prompt_values(prompt_items, scope="global")`, затем `cache.set_many` для непромптных ключей |
| `POST /api/config` (chat) | `write_prompt_values(..., scope="chat", chat_id, expected_updated_at=payload.updated_at)`, затем существующий путь для непромптных ключей чата |
| `POST /api/initiative/meme-settings` | промптные поля — в `write_prompt_values` (тот же CAS-токен `payload.updated_at`), остальные настройки — прежним `_write_chat_overrides_with_retry`; пустая строка промпта → `remove_prompt_override` |
| `DELETE /api/config/chat/{key}` (промптный ключ) | `remove_prompt_override` |
| `POST /speech/block/{id}` / `.../rollback` / `.../reset?mode=factory` | `write_prompt_values` / `restore_shipped_factory` |
| `.../reset?mode=chat` | `remove_prompt_override` |
| `POST /api/prompts/{key}/activate` | `activate_revision` (уже атомарно) |
| `POST /api/prompts/{key}/baseline` / `DELETE .../baseline` | `assign_baseline` / `clear_baseline` |
| `POST /api/prompts/{key}/baseline/restore` | `restore_baseline` → `activate_revision(kind='baseline_restore')` |
| `POST /api/prompts/{key}/factory/restore` | `restore_shipped_factory` |
| миграции/старт | `apply_release` (не меняется) + `capture_pre_versioning_values` |

Аварийное восстановление (`restore_backup`, `services/prompt_factory.py:829-916`)
тоже идёт через `write_prompt_values`: без журнала оно отказывает (503), а не
пишет значения «вслепую». Это осознанно: `bot_settings` и журнал живут в одной
PG, поэтому «PG есть, журнала нет» — только сломанная схема, и лечится она
`ensure_journal`, а не тихой записью без истории.

### 3.5 Batch-семантика

Пакет `/api/config` может содержать промпты и обычные настройки.

- Промптные ключи — **один** `write_prompt_values` (одна транзакция,
  all-or-nothing по промптам).
- Непромптные ключи — существующий путь (`cache.set_many` / `set_chat_params`),
  байт-в-байт как сегодня.
- Порядок: сначала промпты (fail-closed на журнале), затем остальное. Если
  второй этап упал — ответ **честно** перечисляет уже сохранённые промптные
  ключи в `applied` и непромптные в `rejected`, код 503; «сохранено» ни для
  чего не выдумывается.
- Никогда не допускается обратный порядок (значение промпта → потом журнал).

### 3.6 `reset-to-inherit`

`remove_prompt_override(block_id, *, chat_id, actor, cache, store)` — одна
транзакция под теми же локами:

1. читает текущий чатовый override **из PG**;
2. если для этих байтов в этом scope/origin уже есть ревизия — только событие;
   иначе вставляет ревизию `origin='manual'`, `actor=<текущий>`,
   `reason='chat_override_removed'`, `created_at=now()` (время импорта/снятия,
   не выдуманная дата правки);
3. пишет событие `kind='chat_inherit_reset'`, `outcome='recorded'`,
   `revision_id=<снимок>`;
4. удаляет ключ из `overrides` тем же `set_chat_params(conn=_tx_conn)`;
5. commit → инвалидация чат-кэша.

История чата после сброса остаётся доступной (ревизия + событие), активный
указатель не меняется (`outcome='recorded'`).

### 3.7 Первый захват уже существующих значений (§3.6 ТЗ)

`capture_pre_versioning_values(store, cache)` — шаг внутри `apply_release`
(та же транзакция и лок), сразу после `_import_provenance_history`
(`:1041-1090`), поэтому необратимых изменений нет и повтор идемпотентен:

- для каждого блока с `pg_key` и каждого существующего чатового override, у
  которых **нет** ревизии с текущими байтами в этом scope (проверка по всем
  `REVISION_ORIGINS`, как в `_check_activation_drift:1350-1356`), вставить
  ревизию `origin='legacy'`, `reason='pre_versioning_import'`, `actor=''`,
  `created_at=now()`;
- событие `kind='legacy_import'`, `outcome='recorded'` (не активирует!);
- действующий текст, `factory_revision_applied` и активный указатель не
  меняются; байты `initiative.meme.joke` / `initiative.meme.image`
  сохраняются как есть.

Это закрывает фактическую дыру: `prompts.meme_joke` / `prompts.meme_image`
имеют метки `meme-joke-evol014` / `meme-image-evol014` и участвуют в
`apply_release`, но чатовый текст, введённый владельцем **после** применения
метки, сегодня в журнале отсутствует (рестарт с той же меткой = no-op).

---

## 4. Разделение «заводская» / «базовая владельцем»

| | Заводская («Исходный из кода») | Базовая («Базовый, назначен владельцем») |
|---|---|---|
| Идентичность | `origin='factory'` + `factory_revision='fac:sha12(метка)'` + запись в `FACTORY_REVISION_LABELS`/`FACTORY_REVISION_SEALS` (`prompt_registry.py:119,380`) + `release_id` релиза | событие `baseline_assign` с `revision_id` на **любую** совместимую существующую ревизию |
| Кто создаёт | только `apply_release` / `_insert_revision_once(origin='factory')` | только пользовательское действие «Назначить базовой» |
| Меняет ли активный текст | да (новая метка) | **нет** |
| Может ли быть переписана | только новой поставкой кода | только новым `baseline_assign`/`baseline_clear` |

Правила:

1. `origin` ревизии никогда не меняется: ручная запись не переименовывается в
   `origin=factory`. Запрет обеспечивается тем, что `origin` входит в
   `revision_id` (`pr:694-703`) — «переименование» потребовало бы новой строки
   с тем же телом и другим `origin`, то есть дубля; в коде такой операции нет
   и не будет.
2. `origin='factory'` создаётся только когда байты берутся из
   `pr.factory_text()` при целой печати (`restore_shipped_factory`) или из
   релизной поставки.
3. «Вернуть исходную из кода» = явная активация (`kind='factory_restore'`),
   не удаляет `baseline_assign` и не трогает историю.
4. Pin читается через `read_baseline(block_id, scope, chat_id)`; применяется
   до `activation_plan`: к `activation_plan` добавляется keyword-only
   `pinned: bool = False` и действие `PLAN_ACTIVATE_PINNED`
   (`prompt_registry.py:739-775`). Значение по умолчанию сохраняет прежнюю
   семантику — все существующие вызовы и тесты (`tests/test_evol016_prompt_activation.py:426`,
   `tests/test_evol_evidence_routing.py:2250`) остаются валидны.

---

## 5. Enforcement: аудит, который обязан уметь падать

Новый постоянный тест `tests/test_prompt_versioning_enforcement.py`
(`TEST-LIFECYCLE: CONTRACT owner=EPIC-PROMPT-VERSIONING-UX-01`). Три слоя.

### 5.1 Слой 1 — реестр ↔ UI-доступность

`EDITABLE = {b.pg_key for b in pr.all_blocks() if b.pg_key and b.ui != 'code_only'}`
(в HEAD: 39 PG-блоков из 112, `ui=code_only` — 55). Проверка:

- каждый ключ из `EDITABLE` присутствует в каталоге конфигурации
  (`GET /api/config` items) **или** в явно объявленном маленьком множестве
  `SPECIALIZED_CARDS` (сейчас: `prompts.meme_joke`, `prompts.meme_image`,
  `character.core` только как `pg_doc_field`-ключ двух блоков) — и каждая
  запись `SPECIALIZED_CARDS` покрыта тестом из слоя 2;
- блок с `ui='code_only'` в каталоге истории — read-only, без доступных
  кнопок активации (`can_activate=false`, `reason='code_only'`).

### 5.2 Слой 2 — поведенческая матрица (не строковый поиск)

Для каждой точки записи из §3.4 поднимается тестовое приложение с
`MemoryPromptJournal` через существующую инъекцию `routes_mod._prompt_journal`
(как в `tests/test_evol017_prompt_history_ui.py:98`). Для каждого пути
утверждается:

1. появляется **ревизия** с ожидаемым `origin/scope/chat_id/reason`;
2. появляется **событие активации** с ожидаемым `kind/outcome`;
3. значение в PG равно отправленному, а `GET /api/prompts/{key}/versions`
   показывает новую ревизию активной;
4. повторная отправка тех же байтов → `outcome='skipped_same'`, число
   ревизий не растёт;
5. журнал недоступен (`_prompt_journal → None` / бросающий двойник) →
   **HTTP 503 и значение не изменилось** (проверяется фактическое чтение PG).

### 5.3 Слой 3 — рантайм-страж обхода (главное)

`PromptJournalBypass(RuntimeError)` + `contextvars.ContextVar`
`_journal_write_token`. `ConfigCache.set`/`set_many`
(`services/config_cache.py:709,737`) и `chat_params.set_chat_params`
(`:407`, когда вызван **без** журнального `conn`) проверяют: если ключ
резолвится в блок реестра с `pg_key` (`pr.by_pg_key`) и токен для
`(block, scope, chat)` не установлен → **исключение**, запись не выполняется.
Токен ставит только `write_prompt_values` внутри своей транзакции.

Это превращает правило §5 ТЗ из «тест поймает» в «обход невозможен»:
специализированный POST, забывший журнал, падает в момент записи, а не через
сутки в истории.

**Мутация, доказывающая, что тест умеет падать** (`test_guard_catches_bypass`):
monkeypatch обработчика `POST /api/initiative/meme-settings` так, чтобы он
вызывал `chat_params.set_chat_params(chat_id, {"overrides": {...}})` напрямую
(ровно сегодняшнее поведение `routes.py:4245`) без `write_prompt_values`.
Ожидание: `PromptJournalBypass` поднят, значение `prompts.meme_joke` в PG **не
изменилось**, ревизий не появилось. Вторая мутация — то же для
`POST /api/config` (global) через `cache.set_many`, ожидание то же.

---

## 6. UI-контракт единого компонента

Приложение — Alpine.js (`web/app.js`), SPA нет; «компонент» = фабрика
состояния + партиал разметки, переиспользуемые **всеми** редакторами.

### 6.1 Surface

```text
promptCardState(opts) -> {
  // вход (props)
  key, blockId, scope, chatId, chatTitle,
  effectiveText, draftText,
  provenance: { kind: 'manual'|'factory'|'legacy'|'restored'|'owner_baseline',
                scopeLabel, changedAt, actorLabel, isActive },
  factory: { revisionId, matchesActive },
  baseline: { revisionId, assignedAt, assignedBy, origin } | null,
  placeholders: number | null,      // только meme.image
  capabilities: { canEdit, canActivate, canAssignBaseline, canRestore, journalAvailable },
  busy: { save, activate, baseline, history },
  draftDirty, lastError,
  history: { open, loading, error, revisions[], activations[], selA, selB, diff[], viewId, viewBody }
}
```

События (единые имена для всех карточек, `$dispatch`):
`save`, `discard`, `draft-change`, `open-history`, `load-history-page`,
`view-revision`, `diff`, `activate`, `assign-baseline`, `clear-baseline`,
`restore-baseline`, `restore-factory`, `clear-chat-override`,
`copy-to-global`.

### 6.2 Что показывает обычная карточка

- Название промпта, состояние одной человеческой фразой:
  `Действует в этом чате` / `Изменён вручную · 03.11 23:42` /
  `Наследуется от глобального` / `Изменён глобально` /
  `Базовый по выбору владельца` / `Исходный из кода`.
- Переключатель области (глобальный / этот чат), кнопки `История версий`, `⋯`.
- textarea с **эффективным** текстом; несохранённый черновик отличается
  визуально (существующий `memeDraftDirty`, `web/index.html:2103-2109`).
- Никаких `act:…`, `fac:…`, `revision_id`, `sha`, `factory seal` в основной
  карточке. Технические ID — только в раскрываемых «Подробностях»
  (по умолчанию закрыты; сейчас они в основной строке:
  `web/index.html:2125-2127`, `:2144`, `:4188-4195`).
- Мемы: две карточки рядом на широком экране, последовательно на мобильном,
  у каждой своя «История версий» (§2.1 ТЗ).
- Переключение чата при несохранённом черновике — предупреждение с выбором
  `сохранить / остаться / отменить` (переиспользовать существующий
  `_memeDraftLeaveGuard`, `web/app.js:10638`), без молчаливой потери текста.

### 6.3 Панель «История версий»

Существующая панель `web/index.html:4196-4345` + состояние
`web/app.js:3283-3296` расширяются, а не заменяются: боковая панель/модалка с
шириной для чтения, на мобильном — полноэкранная; постраничная загрузка
(stable cursor по `activation_id`/`(created_at, revision_id)`), полный список
без обрезки; строки с человеческим источником (`ручная`, `импортирована`,
`из релиза`, `восстановлена`), статусом (`активная`, `базовая`, `неактивная`,
`несовместимая`), действиями `Посмотреть` / `Применить эту версию` /
`Сравнить с текущей` / `Назначить базовой` / `Скопировать`. Diff — только
строки изменений; недоступная ревизия показывает причину, а не пустой текст.

### 6.4 `{joke}` без правки шаблона

`template.placeholders` (`web/api/routes.py:4103`) остаётся числом в API.
Меняется **только подпись** в карточке (`web/index.html:2159-2165`):

- `0` → «Прикол автоматически добавится после шаблона»;
- `1` → «Прикол вставится в отмеченное место»;
- `≥2` → существующая ошибка валидации «допускается не более одного {joke}»
  (`services/meme_initiative.py:634-649`).

Сырой `{joke}: 0` из видимой мета-строки удаляется. Текст шаблона не
изменяется, вставка плейсхолдера не навязывается.

---

## 7. Совместимость, тесты и риски

### 7.1 Тесты, которые фиксируют текущее поведение (обновлять осознанно)

| Тест | Что фиксирует | Почему остаётся/меняется | Клауза ТЗ |
|---|---|---|---|
| `tests/test_evol017_prompt_history_ui.py:272` (`test_save_creates_snapshot_and_keeps_old`) | `POST /api/config` → 200 + `prompt_snapshots[{key, revision_id}]` | **остаётся зелёным**: имя поля и форма ответа сохраняются | §3.8 |
| `tests/test_asap_prompt_history_integrity.py:312` | `prompt_snapshots` на ключ | остаётся | §3.1 |
| `tests/test_evol017_prompt_history_ui.py:309` | маркеры `data-prompt-history*` внутри `data-prompt-editor`, строки в `web/app.js`, CSS `.prompt-history`, `max-width: 420px` | **меняется осознанно**: маркеры сохраняем, добавляем новые; переименование запрещено | §2.2 п.1–2 |
| `tests/test_evol016_prompt_activation.py` (переходы `PLAN_*`, снятие чатового override `:389`) | релизная политика | остаётся для **незакреплённых** блоков; добавляются кейсы pinned | §4: «Для остальных, не закреплённых владельцем промптов, сохранить текущую релизную политику» |
| `tests/test_meme_pipeline_api.py` | контракт `POST /api/initiative/meme-settings` (`409/422/503`, `template.placeholders`) | **меняется осознанно**: ответ получает `prompt_snapshots`/`skipped_same`, журнал недоступен → 503; форма полей и `placeholders` не меняются | §3.1–3.2, §1 п.1 |
| `tests/ui_meme_ui_fields_e2e.py`, `tests/ui_initiative_rework_e2e.py`, `tests/test_meme_init_diagnostics.py` | маркеры карточки мемов (`data-meme-prompt-joke`, reset) | маркеры сохраняются при переезде в компонент | §2.1 |
| `tests/test_soul1_w6_speech_ui.py:292-294` | speech.py содержит `write_speech_value`/`apply_factory_reset`/`reset_chat_override` | **меняется осознанно** на новый entry point | §3.1 |
| `tests/test_soul1_factory_defaults.py` (`apply_factory_reset`, `reset_chat_override`, `restore_backup`) | семантика сбросов | дополняется проверкой ревизии при снятии override | §3.4 |
| `tests/test_evol018_prompt_audit.py` | печати + `FACTORY_SET_SHA256_12` + grep-аудит | **не меняется**: любая правка текста промпта уронит его — это и есть машинная защита §0.1 | §0.1 |

Дополнительно вводится байт-эталон: тест сравнивает `sha256` действующих
`prompts.meme_joke` / `prompts.meme_image` (из живого слоя конфигурации) со
значениями, снятыми до начала работ — правка текста в этом пакете ломает тест.

### 7.2 Что может испортить историю

1. Запись значения **до** ревизии на любом пути (сегодня — 4 таких места,
   §1.4) → ревизия «догоняет» с другим временем/автором.
2. Чтение текущего текста из памяти кэша внутри решения `skipped_same`
   (сегодня `prompt_release_policy.py:1524`) → два админа дают неверную
   классификацию и потерянное обновление.
3. `chat_params.set_chat_params` вне той же транзакции → значение есть,
   ревизии нет.
4. `origin='factory'` из ручного действия без проверки печати → история лжёт.
5. `PLAN_ACTIVATE` для закреплённого scope (без pinned-ветки) → молчаливая
   замена owner baseline новой поставкой.
6. Снятие чатового override без снимка → текст исчезает из истории навсегда.
7. `UPDATE prompt_revisions SET body` любым будущим кодом (схема не мешает).

### 7.3 Инварианты, которые Reviewer обязан попытаться опровергнуть

1. **Два админа одновременно** сохраняют один промпт: ровно одна ревизия на
   разные байты; `skipped_same` не теряет чужую правку; при CAS-конфликте —
   409 и ни одного изменения.
2. **Сбой PG между значением и ревизией**: недостижим — обе записи в одной
   транзакции; проверяется инъекцией `fail_at="insert_revision"`
   (`MemoryPromptJournal`, `:510-513`) → значение в PG не изменилось, ответ
   503.
3. **Перезапуск в ходе миграции/захвата**: `capture_pre_versioning_values`
   идемпотентен по `revision_id`; повторный старт не добавляет ревизий и не
   меняет действующий текст.
4. **Новая заводская поставка при pinned**: значение не изменилось,
   `factory_revision` в истории появился, следующая рестарт-проверка — no-op
   (`restart_same_revision`), `activation_drift` не возникает.
5. **Новая заводская поставка при unpinned**: прежняя семантика (заводской
   текст активен, ручной — в истории).
6. **Чужой чат**: активация `revision.scope='chat'` с чужим `chat_id` →
   отказ `revision_foreign_scope`, ни одного изменения; чтение тела чужой
   чатовой ревизии → 403 (`_prompt_require_revision_view`,
   `web/api/routes.py:3354-3375`).
7. **`reset-to-inherit`**: override удалён, ревизия со снятым текстом
   присутствует, действует global effective, `read_applied` не сдвинут.
8. **Batch**: пакет из промпта+настройки при недоступном журнале → 503 и
   настройка тоже не записана; при доступном журнале — оба сохранены и
   `skipped_same` честен по каждому ключу.

### 7.4 Риски

| # | Риск | Уровень | Смягчение |
|---|---|---|---|
| R1 | Инъекция `conn` в `chat_params.set_chat_params` затрагивает общий горячий модуль (8 вызовов) | R2 | default `None` = байт-в-байт прежнее поведение; отдельный тест с PG-двойником на одну транзакцию |
| R2 | Все записи промптов теперь под глобальным advisory-локом журнала → сериализация и риск зависания | R2 | `SET LOCAL lock_timeout='5s'`, честный 503; масштаб проекта (1–2 чата) допускает сериализацию |
| R3 | Чтение действующего значения из PG вместо кэша меняет классификацию `skipped_same` в тестах с предзаполненным кэшем | R2 | обновить фикстуры осознанно, зафиксировать в отчёте |
| R4 | Закреплённый чат + новая метка: ошибка в ветке снятия override молча меняет голос бота | R3 | отдельные тесты pinned/unpinned на chat scope, проверка фактических байтов override |
| R5 | Неизменяемость `body` не защищена схемой (нет триггера/REVOKE) | R1 | принять как границу; опционально аддитивный `BEFORE UPDATE`-триггер, разрешающий только `retired` — отдельным решением, не в этом пакете |
| R6 | `capture_pre_versioning_values` может подписать `legacy` значение, записанное в обход | R1 | страж §5.3 исключает обход; `legacy`+`pre_versioning_import` честно показывает происхождение |
| R7 | Рост `prompt_activations` (событие на каждое сохранение, включая `skipped_same`) | R0 | постраничное чтение; лимитов на ревизии не вводим (§3.5 ТЗ запрещает переносить `HISTORY_MAX_PER_BLOCK`) |

---

## 8. Приёмка (что должно быть доказано)

**Бэкенд:** каждый editable-ключ имеет полный version UI; сохранение через
любой из путей §3.4 даёт ревизию и событие; история без лимита, страницами;
rollback/forward/diff/baseline/reset работают после рестарта; оригинальный
`factory` не изменён; pin защищает, unpinned — прежняя семантика; `409` и
`503` не теряют текст; batch не обходится.

**Мемы:** оба поля — тот же компонент и тот же журнал;
`POST /api/initiative/meme-settings` больше не обходит журнал (проверяется
матрицей §5.2 и стражем §5.3); `render_image_prompt("X","Y")=="X Y"`,
`render_image_prompt("X {joke}","Y")=="X Y"`; `template.placeholders=0`
объясняется по-человечески; бюджет считается от эффективного шаблона.
**Тексты `meme_joke`/`meme_image` до/после идентичны по байтам** (хеши в отчёте).

**UI:** «История версий» доступна с каждого экрана с редактируемым промптом
(десктоп + мобильный Telegram WebView): редактор, просмотр, diff, включение,
назначение/снятие baseline, восстановление, честная область действия, ошибки,
несохранённый черновик. Метаданные человекочитаемы, ID — только в деталях.
Тема, анимации и прежние функции сохранены (скриншоты, не только unit).

**Отрицательные:** конкурирующие правки двух админов, запрос ревизии другого
чата, сбой PG между значением и ревизией, перезапуск в ходе захвата,
несоответствие журнала и конфигурации, очень длинный промпт, Unicode/переводы
строк, пустой чатовый override, legacy-значения, история 1000+, неизвестный
actor/time, новая заводская поставка при pinned и unpinned, сохранение из
специализированного API.

---

## 9. Параллельная безопасность (для Builder'ов)

Эта работа не пишет продуктовый код. Затрагиваемые файлы (только
координация, не пересечение с текущими лейнами):

- `services/prompt_release_policy.py`, `services/prompt_registry.py`,
  `services/prompt_factory.py` — **SERIALIZE** (одна точка правды, один
  writer);
- `services/chat_params.py`, `services/config_cache.py` — **SERIALIZE**
  относительно друг друга и относительно журнала (инъекция `conn`);
- `web/api/routes.py`, `web/api/speech.py` — **SERIALIZE** (router без
  параллельной записи);
- `web/index.html`, `web/app.js`, `web/static/app.css` — **SERIALIZE**
  (один UI-компонент);
- `tests/test_evol018_prompt_audit.py`, `tests/test_evol016_prompt_activation.py`
  — read-only контрактные тесты, менять только вместе с контрактом;
- `services/canonical_context*`, `services/media_marker*`,
  `services/thread_chain*`, `services/factcheck*`, `handlers/factcheck.py` —
  **READ_ONLY_PARALLEL** (не трогаем).

---

## 10. Привязка к карте требований PM

Карта `plans/features/epic-prompt-versioning-ux-01/requirements-map.json`
(`task_id=epic-prompt-versioning-ux-01`,
`owner_input_id=OI-2026-11-04-EPIC-PROMPT-VERSIONING-UX-01`) — источник
требований; этот документ — источник контракта. Каталог назван по-разному
(карта в `epic-prompt-versioning-ux-01/`, контракт в `prompt-versioning-ux/arch/`)
намеренно: путь контракта задан постановкой, карту ведёт PM; переносить и
дублировать их не нужно.

| Слайс | Разделы контракта |
|---|---|
| `PVR-S0-GUARD` | §5.3 (страж обхода), §5.1 |
| `PVR-S1-WRITE` | §3.1–3.7, §7.3 п.1–3, 8 |
| `PVR-S2-BASELINE` | §2.1–2.5, §4, §7.3 п.4–6 |
| `PVR-S3-HISTORY` | §1.1–1.2, §3.6, §7.2 |
| `PVR-S4-UX` | §6.1–6.4, §7.1 (UI-маркеры) |
| `PVR-S5-STD-DOC` | §4 правило 1–3, §7.1 (`test_evol018_prompt_audit.py`) |
| `PVR-S6-AUDIT` | §5.1–5.3, §8 |

Слайсы `PVR-S0` и `PVR-S1` — **SERIALIZE** относительно `PVR-S2` (общий
`prompt_release_policy.py`), `PVR-S4` не начинается до готовности HTTP-слоя
`PVR-S2`.
