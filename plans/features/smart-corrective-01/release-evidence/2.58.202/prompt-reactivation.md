# Prompt reactivation — saved chat checkup edition

Дата: 2026-11-14 15:14:52Z (UTC). Chat: **CHAT_C2** (raw Telegram id намеренно
не включён в evidence). Block: `checkup.base.system`.

Механизм: официальный `services.prompt_release_policy.activate_revision`
(EVOL-017), scope `chat`. Вызов идёт через `PgPromptJournal.transaction()`,
который берёт apply-lock `APPLY_LOCK_SQL`; ручных SQL-записей тела, удаления,
клона ревизии и изменения factory-ревизии нет.

## Запрос

```
revision_id    rev:d31300ef35a0
origin         manual
scope          chat
body           12 469 chars
sha256         31d1750654615bf4e69e861ae66f393b31546b34982c7d5613052b67133b3701
retired        false
actor          devops
```

## Registry state

### Before

```
active revision        rev:9ed7b22b0d8c (factory)
active activation id   2941
active kind            deploy_activate
factory_revision_applied fac:d263c52f7871
chat_updated_at        2026-11-14T13:42:28.420641+00:00
chat override          absent
manual revision        present, 12 469 chars, sha256 31d17506…, retired=false
factory revision       present, 3 462 chars, sha256 3140bb36…, retired=false
global prompt          3 030 chars, sha256 b0c70f97…, present
```

### After first activation

```
activation_id          2942
activation_kind        manual_rollback
outcome                applied
applied                true
active revision        rev:d31300ef35a0 (manual)
active activation id   2942
chat override          present, 12 469 chars, sha256 31d17506…
chat_updated_at        2026-11-14T15:14:52.896133+00:00
manual revision        unchanged, 12 469 chars, sha256 31d17506…, retired=false
factory revision       unchanged, 3 462 chars, sha256 3140bb36…, retired=false
global prompt          unchanged, 3 030 chars, sha256 b0c70f97…
```

### After second activation (idempotence probe)

```
activation_kind        manual_rollback
outcome                skipped_same
applied                false
active revision        rev:d31300ef35a0 (manual)
active activation id   2943 (skipped_same event)
chat override          unchanged, 12 469 chars, sha256 31d17506…
chat_updated_at        unchanged 2026-11-14T15:14:52.896133+00:00
manual revision        unchanged
factory revision       unchanged
global prompt          unchanged
```

Важно: официальный сервис записывает событие `skipped_same` (activation
2943), поэтому указатель «последняя активация» ссылается на 2943. Это **не**
второе `applied`-событие и не повторная запись тела: active revision остаётся
manual, chat_updated_at не меняется, applied-счётчик manual не растёт
(`no_double_applied=true`). Иная трактовка потребовала бы менять сам
официальный сервис, что в задачу не входило.

## Checks

```
before_active_factory                 true
first_applied                         true
first_kind_manual_rollback            true
first_revision                        true
after_first_active_manual             true
override_after_first_manual           true
manual_unchanged_first                true
factory_unchanged_first               true
global_unchanged_first                true
second_skipped_same                   true
after_second_active_manual            true
second_no_body_or_pointer_change      true
no_double_applied                     true
failed                                []
```

## Notification behavior

```
official channel       pg_notify(chat_params_updated)
telegram_send          false
chat_updated_at        changed 13:42:28.420641Z -> 15:14:52.896133Z on first
                       unchanged on second (skipped_same)
```

Официальный путь пишет chat override через `chat_params.set_chat_params` и
отправляет только PostgreSQL `NOTIFY` для инвалидации кэша. Telegram-транспорт
в этом пути не участвует; сообщение в чат не отправлялось. Это не «тихая»
ручная запись: провенанс события сохранён в `prompt_activations` (actor
`devops`, `detail_code=activate:manual`, kind `manual_rollback`).

## Source of truth

- `prompt_revisions` — manual revision `rev:d31300ef35a0` (body/sha unchanged,
  `retired=false`) и factory `rev:9ed7b22b0d8c` (unchanged).
- `prompt_activations` — activation 2942 (`applied`) и 2943 (`skipped_same`).
- `chat_profiles` — `prompts.checkup_system_prompt` override restored with
  manual bytes (12 469 chars, sha256 `31d17506…`).
- Global `prompts.checkup_system_prompt` remains factory 3 030 chars
  (`b0c70f97…`), unchanged.
- Raw chat id and raw prompt body не публикуются в evidence; в отчёте chat
  обозначен как CHAT_C2, тело проверено по sha256/длине.
