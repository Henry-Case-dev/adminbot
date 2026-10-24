# B1 — owner-preserving патч Core подключён к старту (CORE-PATCH-WIRE)

Дата: 24.10.2026. Релизное ревью P0-CORRECTIVE (B1): `owner_preserve_core_full_patch`
существовал, но не вызывался ни стартом, ни миграцией, ни CLI → активная авторская
редакция `character.core.full_text` не получала абзацы «Как говорить о реальных
событиях» и «Свобода речи» после деплоя (работал бы только заводской v4).

## RED (до фикса, HEAD 5d0f8a2a)

```
git grep -n "owner_preserve_core_full_patch" HEAD -- services bot.py
HEAD:services/chat_prompts.py:922   # только комментарий
HEAD:services/chat_prompts.py:970   # только комментарий
HEAD:services/prompt_migrations.py:532: def owner_preserve_core_full_patch(...)
```

Вызовов — ноль. Функция-патч была мёртвым кодом в рантайме.

## Фикс: точка вызова (одна, штатная)

`services/prompt_migrations.py::migrate_prompt_canons` (единственный startup-вход
канонов, вызывается из `bot.py:1382` в `main()` сразу после `cache.init()`) в конце
выполняет новый шаг:

```
report.update(await migrate_core_owner_patch(cache))
```

`migrate_core_owner_patch(cache)`:
1. PG down / `cache=None` → skip (`[prompt_migration] core patch skip`), бот живёт на
   заводских редакциях (там оба абзаца уже есть).
2. Читает ГЛОБАЛЬНЫЙ документ `character.core`; per-chat overrides не трогаются.
3. Документа нет / пустой `full_text` → no-op (действует заводская v4).
4. Байты v1/v2 заводских редакций → no-op: их ведёт superseded-гвард
   `prompt_registry.core_selection` (не перезаписываем).
5. Иначе `owner_preserve_core_full_patch(text)`; пустой `changes` → no-op
   (повторный старт).
6. Запись — только при реальной вставке, через штатный
   `prompt_factory.write_speech_value("core.personality", …)`:
   журнал провенанса `character.prompt_history` (kind `owner_edit`,
   reason `core_patch_migration`) + history-ревизия прежнего текста.
   Новый keyword `set_level=False` — выбор владельца `detail_level`
   не переключается (правка поля не делает редакцию принудительно активной).
7. Возврат: `{"character.core": "core_patched"}` при вставке, иначе `{}`.
   Исключения глушатся (WARNING) — шаг не роняет старт.

Логи R17-safe: только заголовки вставленных абзацев, счётчик удалённых служебных
фрагментов, длины и sha12; сырой текст канона/секреты не пишутся.

Авторские байты: патч только вставляет недостающие абзацы в позицию после
«Как рождается юмор»/перед «Грубость·Ритм»; вычитание вставок даёт исходный текст
дословно (проверяется тестом). Откат: прежняя редакция сохранена в
`character.prompt_history`; автоматическое вырезание авторского текста намеренно
не делается (REQ-CORE-KEEP-VOICE / REQ-GOV-KEEP-CORE).

## Тесты (новые, tests/test_p0_checkup_core_contract.py)

`TEST-LIFECYCLE: REGRESSION owner=B1/CORE-PATCH-WIRE`

- `test_b1_startup_migration_patches_active_owner_core` — старт (`migrate_prompt_canons`)
  доставляет оба абзаца в активную авторскую редакцию; вычитание вставок == исходные
  байты; `detail_level="full"` и `compact_text` не тронуты; revision 6→7; провенанс
  `core.patch` записан.
- `test_b1_second_startup_is_noop_and_survives_restart` — второй старт/«рестарт» из
  сохранённого документа: `set` не вызывается, абзацы на месте.
- `test_b1_owner_level_choice_and_foreign_editions_are_not_rewritten` — `detail_level="compact"`
  сохраняется; редакция с уже имеющимся смыслом не перезаписана; байты v2 не тронуты
  (superseded); без документа — no-op.
- `test_b1_core_patch_is_skipped_without_pg_and_never_raises` — PG down → `{}` без
  исключения; битый raw → no-op.

## Прогон (локально, без сети/прода)

```
py -3 -m pytest tests/test_prompt_migrations.py tests/test_p0_prompts_core.py \
  tests/test_p0_checkup_core_contract.py tests/test_asap_w1_semantics.py \
  tests/test_asap2_clar_contract.py -q
112 passed

py -3 -m pytest tests/test_mca08_character_speech.py \
  tests/test_cfg07_backstage_contract.py tests/test_summary_asap21_prompt_migrations.py -q
132 passed
```

Примечание: файл `tests/test_asap_speech_r3b_canon.py` из брифа в репозитории
отсутствует (нет ни одного `*r3b*`/`*speech*canon*` теста); вместо него прогнаны
существующие speech/канон-контракты выше.

## Изменённые файлы

- `services/prompt_migrations.py` — `migrate_core_owner_patch` + вызов в
  `migrate_prompt_canons`.
- `services/prompt_factory.py` — `write_speech_value(..., set_level=True)`
  (аддитивно; поведение существующих вызовов не меняется).
- `tests/test_p0_checkup_core_contract.py` — 4 регрессионных теста B1.
