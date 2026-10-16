# SOUL-1 / W1 — аварийная копия речевой конфигурации: что внутри и как вернуть

**Файл:** `plans/features/soul-1/evidence/w1/backup-speech-config.json`
**Схема:** `soul1-w1-speech-backup/1` · **Слайс:** W1-REGISTRY · **Дата:** 16.10.2026

## Что внутри

| Секция | Содержимое |
|---|---|
| `keys` | 25 ключей `prompts.*` (все PG-управляемые речевые блоки): `factory_text` — полный заводской текст, `factory_sha256_12`, `factory_chars`, фабричная ревизия, потребители |
| `keys[*].known_prev_revisions` | все известные PREV/rollback-слепки лестницы `services/prompt_migrations` **полным текстом** (то, что может реально лежать в PG прода) |
| `keys[*].pg_value_at_backup` / `text` | живое значение `bot_settings` с `updated_at`/`updated_by` — **только если PG был доступен**; `text` — единственный источник для `restore_backup` |
| `prod_evidence.custom_summary_keys` | задокументированное прод-свидетельство 6 custom-summary ключей (baseline 2.58.33): sha256_12 + длина (полные тексты в архиве не сохранялись) |
| `restore` | машинное описание процедуры восстановления |

**Проверка «не плейсхолдеры»:** каждый `factory_text` — это реальный код-канон
(например `prompts.search_system_prompt` = 2622 символа, `sha256_12=ba43fb679db6`),
а не заглушка; `known_prev_revisions` содержат полные тексты слепков.

## Чего в снимке НЕТ (честная граница)

Локальный PG на момент снятия копии **недоступен** (`pg_status="down"`,
`WinError 1225` — то же состояние, что зафиксировал аудит
`audit-prompt-matrix.md` §0). Поэтому:

* живые значения `bot_settings` не сняты (`pg_value_at_backup` = `null`);
* per-chat overrides (`chat_profiles.overrides`) не сняты.

Это компенсировано: прод-значения `prompts.*` — это либо байт-в-байт один из
`known_prev_revisions`, либо один из код-канонов (сид `bot_settings`
`ON CONFLICT DO NOTHING` = код-канон), либо custom, чьи sha/длины записаны в
`prod_evidence`. Полное живое снятие обязан повторить DevOps на прод-хосте
перед включением флага (см. блокер ниже).

## Как восстановить

### 1. Восстановление значений из снимка (идемпотентно, обратимо)

```powershell
# dry-run: показать, что будет записано (ничего не пишет)
py -3 -m services.prompt_factory restore plans/features/soul-1/evidence/w1/backup-speech-config.json

# применение (запись в bot_settings; каждая запись попадает в историю)
py -3 -m services.prompt_factory restore plans/features/soul-1/evidence/w1/backup-speech-config.json --apply
```

Источник отката — **только** захваченное значение (`text`/`pg_value_at_backup`):
заводской текст (`factory_text`) намеренно не используется, иначе
восстановление могло бы молча затереть правку владельца, сделанную после
снятия копии. **В этом снимке PG был недоступен → ни у одного ключа нет
`text`, поэтому `restore_backup` вернёт `planned=0`.** Аварийные пути речи в
этом состоянии:

```powershell
# (а) вернуть ВСЮ речь к заводским редакциям (предпросмотр, затем запись)
py -3 -m services.prompt_factory reset-all
py -3 -m services.prompt_factory reset-all --apply

# (б) откат нормализации legacy-речи из character.migration_snapshots
#     (см. §2 ниже)
```

Поведение `restore_backup`: значение, уже совпадающее со снимком, не
переписывается; каждая запись идёт через `character.prompt_history`
(`kind=backup_restore`), поэтому откат вперёд/назад не теряет ревизий; данные
бота (память, SelfModel, биография, отношения, Experience, чаты, ключи,
бюджеты) не затрагиваются.

### 2. Откат нормализации legacy-речи (если выполнялся write-pass)

```powershell
# фаза A: предпросмотр (ничего не пишет)
py -3 -c "import asyncio;from services import config_cache,prompt_migrations as pm;c=config_cache.ConfigCache();print(asyncio.run(pm.plan_legacy_speech_removal(c)))"

# откат: вернуть оригиналы из character.migration_snapshots
py -3 -c "import asyncio;from services import config_cache,prompt_migrations as pm;c=config_cache.ConfigCache();print(asyncio.run(pm.rollback_legacy_speech(c)))"
```

Откат не перезаписывает ключ, значение которого владелец изменил после
миграции (`changed_after_migration` + WARNING).

### 3. Аварийный откат без PG (мгновенный)

`UNIFIED_COMPOSER_ENABLED=false` (значение по умолчанию) — сборка system/user
идёт прежним путём; подавление legacy-сегментов применяется только к
ПЕРСИСТЕНТНОМУ значению на сборке и не изменяет ни одной строки в PG.
Кодовый fallback (PG недоступен) остаётся байт-в-байт прежним.

## Блокер

`UNIFIED_COMPOSER_ENABLED` (env + `flags.unified_composer_enabled`) **не
включать**, пока не выполнены: (а) живой backup прод-значений (повтор снимка
при доступной PG), (б) запись нормализации legacy-речи (`normalize_legacy_speech
apply=True`, JB-3) либо явное решение Orchestrator'а оставить только
сборку-подавление, (в) повторная проверка паритета OFF. Маркер блокера —
`composer_flag_release_gate` в `plans/features/soul-1/w1-registry-report.md`.
