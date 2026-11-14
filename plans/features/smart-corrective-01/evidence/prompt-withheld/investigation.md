# Prompt withheld — почему канареечный probe видел `provenance_missing` (2.58.202 / 0beed63d)

Дата: 2026-11-15. Роль: Builder (read-only investigation). Production:
`0beed63d` (release/smart-corrective-01), APP_VERSION 2.58.202, unit active
PID 837957, старт 2026-11-14 15:14:44Z, healthz 200 `2.58.202`.
Ни одной production-записи не сделано: PG — только `SELECT` на соединении с
`default_transaction_read_only=on`; SQLite — `mode=ro`; Telegram/провайдер не
вызывались. Chat id в отчёте заменён ссылкой `chat-bb8fd239`.

## 1. Итог

1. Боевой путь доставки **исправен**: в процессе бота (после штатной стартовой
   проводки) тот же deployed-резолвер на тех же сохранённых данных возвращает
   `source=chat`, `prompt_base_chars=12469`, `prompt_base_hash=31d1750654615bf4`,
   `prompt_withheld=false` — ровно то, что требует AC-15/AC-19. Живого чекапа в
   чате с сохранённой редакцией после активации не было (§7) — это остаётся
   событийной проверкой, а не дефектом.
2. Наблюдение финальной канарейки (`source=default`, `base_chars=3462`,
   `withheld=true`, `reason=provenance_missing`) **воспроизведено точно** — но
   только в процессе, который НЕ выполнял стартовую проводку релизной политики.
   Это артефакт измерительного probe, а не дефект продукта.
3. Дефекта в резолвере/провенансе/данных реестра не найдено. Код приложения не
   менялся (предложения — §6); коммит содержит только это расследование.

Доказательство тождества: в состоянии A probe получил
`prompt_base_hash16=3140bb3640446797` и строку журнала
`persisted speech value withheld | ... | stored_sha=31d175065461 | stored_chars=12469`
— байт-в-байт значения финальной канарейки
(`evidence/postdeploy/live/canary-final-20261114T153116Z.md` §3).

## 2. Механизм (file:line)

Релизная политика провенанса — **процесс-локальный флаг**, а не производная от
журнала:

- `services/prompt_registry.py:856` — `_RELEASE_POLICY_ACTIVE = False` (дефолт
  процесса);
- `services/prompt_registry.py:863-871` — `set_release_policy_active()` /
  `release_policy_active()`;
- `services/prompt_registry.py:3760-3798` — если политика **не** активна:
  `provenance_state()` даёт `provenance_missing`, значение удерживается,
  действует заводская редакция (`source="default"`), пишется WARN
  `persisted speech value withheld` (`:3786-3791`);
- `services/prompt_registry.py:3799-3818` — если политика активна (EVOL-016
  §1.6): удерживается только `legacy_incompatible`; иначе persisted-текст и есть
  эффективный слой (`diagnostics=("release_policy_persisted_effective", reason)`).

Кто включает флаг — единственное место в продовом коде:

- `services/prompt_release_policy.py:2252-2254` —
  `pr.set_release_policy_active(True)` в конце успешного `_apply_release_packet`;
- `services/prompt_migrations.py:956-958` (`migrate_prompt_canons`) →
  `prp.apply_release(cache, release_id=CUTOVER_RELEASE_ID)`;
- `bot.py:1403-1404` — вызов стартовой проводки из bootstrap.

Маршрут чекапа читает именно этот флаг через общий резолвер:

- `services/checkup_service.py:112-157` — `_resolve_checkup_base_prompt(chat_id)`;
  при `chat_id` использует `prompt_registry.resolve_chat_speech_ex`;
- `handlers/checkup.py:143-144` — пользовательская команда передаёт
  `chat_id=message.chat.id`.
- `services/prompt_registry.py:3954-3973` — `resolve_chat_speech_ex`: слой
  определяется `_chat_present()` (`:3719-3730`), затем `resolve_speech_value`.

Следствие: **любой** процесс, который импортирует deployed-код, но не выполняет
`apply_release` (ad-hoc probe, отдельный скрипт), видит состояние «до cutover» и
удерживает сохранённую редакцию. В самом боте флаг выставлен при каждом старте
(в т.ч. при no-op рестарте: успешный возврат пакета всегда доходит до `:2254`).

## 3. Факты из production (read-only)

Systemd journal (один старт после деплоя):

```
2026-11-14 15:14:48,465 - services.prompt_release_policy - INFO -
[prompt_release] релиз применён | release=evol-016-cutover | blocks=112 | changed=0 | retired=0
```

- `journalctl -u admin_bot --since "2026-11-14 15:14:40" | grep -c "persisted speech value withheld"` → **0**;
- `prompt_release` строк за окно: 1; строка `релиз применён` — единственная и
  означает, что `set_release_policy_active(True)` выполнен в процессе бота.

Реестр/данные (PG, read-only; тексты не печатались):

| факт | значение |
|---|---|
| ревизия чата | `rev:d31300ef35a0`, `origin=manual`, `retired=false`, 12 469 симв., `content_sha12=31d175065461` |
| заводская ревизия | `rev:9ed7b22b0d8c`, 3 462 симв., `content_sha12=3140bb364044` |
| активации | 2942 `manual_rollback/applied` → `rev:d31300ef35a0` (15:14:52.896Z); 2943 `skipped_same` (15:14:52.902Z) |
| chat override | присутствует, 12 469 симв., sha12 `31d175065461` |
| global PG-значение | присутствует, 3 030 симв., sha12 `b0c70f974e0e` |

## 4. Воспроизведение

### 4.1 Локально (deployed-код + in-memory двойники, без prod-данных)

`probes/local_policy_state_repro.py` (deployed worktree `0beed63d`): синтетическая
редакция 12 469 символов, chat override присутствует, провенанса нет.

| состояние процесса | source | withheld | text chars | sha12 |
|---|---|---|---|---|
| A: без стартовой проводки | `default` | `true` (`provenance_missing`, class `unclassified`) | 3 462 | `3140bb364044` |
| B: после `apply_release` | `chat` | `false` | 12 469 | (синтетика) |

WARN из A совпадает с канареечным: `persisted speech value withheld | key=prompts.checkup_system_prompt | block=checkup.base.system | reason=provenance_missing | class=unclassified`.

### 4.2 На production (deployed-код + реальные данные, read-only)

`probes/prod_policy_state_probe.py` — тот же deployed-метод
`CheckupService._resolve_checkup_base_prompt`, что вызывал канареечный probe;
значения `bot_settings`/`chat_profiles` читаются из PG read-only и подставляются
в штатные точки (`hot.set_config_cache`, `chat_params.set_chat_params_cache`).
Поведение сравнивается в двух состояниях процесс-флага на **реальном** владельческом тексте:

| поле | A: без стартовой проводки | B: как в процессе бота |
|---|---|---|
| `prompt_layer` | `default` | `chat` |
| `prompt_withheld` | `true` | `false` |
| `prompt_provenance_reason` | `provenance_missing` | `provenance_missing` |
| `prompt_base_chars` | **3 462** | **12 469** |
| `prompt_base_hash16` | **3140bb3640446797** | **31d1750654615bf4** |
| diagnostics | `persisted_value_withheld, provenance_missing` | `release_policy_persisted_effective, provenance_missing` |

Значения A (`3 462` / `3140bb3640446797`) **точно** совпадают с финальной
канарейкой — значит её probe работал в состоянии A.

Побочно (не наш scope): global-слой в A тоже подменялся заводским
(`source=default`, 3 462), а в B эффективен (`source=global`, 3 021 симв.,
sha12 `e429735b74bf`; разница с сохранёнными 3 030 — штатное вычищение известного
legacy-сегмента). О содержании этого global-слоя — §10.

## 5. Следствия для приёмки

1. Канареечный prompt-provenance FAIL — дефект **измерения**, не доставки:
   probe не повторял стартовую проводку политики.
2. Тот же общий корень искажает телеметрию pinned SMART `checkup_real`
   (`prompt_source=default`, `prompt_chars=3453`): harness запускает
   `CheckupService` в отдельном процессе и с `chat_id=None`. Эти значения
   описывают процесс harness-а, а не боевой слой; их нельзя использовать как
   доказательство global-слоя прода.
3. Данные и код на проде не требуют правки: сохранённая редакция активна
   (журнал), резолвер в состоянии бота отдаёт её, WARN об удержании в сервисном
   журнале отсутствует.

## 6. Предлагаемая минимальная правка (и почему не внедрена)

Вариант 1 (приёмочный, без кода): повторить evidence-прогон в процесс-состоянии
бота — read-only probe, который **не вызывает** `apply_release` на проде, а
выставляет флаг после подтверждения durable-факта старта (строка журнала /
`prompt_activations.release_id=evol-016-cutover`) — ровно как в §4.2; либо ждать
естественный чекап в чате с сохранённой редакцией и прочитать
`mca_events.source_ref_json.prompt_layer` (см. §7).

Вариант 2 (harden, требует контрактного решения — не внедрялся): сделать
`release_policy_active()` производной от durable-состояния (маркер применённого
cutover в `bot_settings`/журнале) с ленивым кэшем. Это устранит класс ложных
«withheld» у любых out-of-process читателей, но вводит новую durable-поверхность
состояния, затрагивает каталог настроек/контракт §1.6 и требует отдельного
ревью — не «самоочевидная» правка в рамках S6-guard.

Вариант 3 (не предлагается): новый диагностический модуль/эндпоинт. Нет
требования, это расширение scope; достаточно §6.1.

## 7. Что осталось непроверенным

- Живого чекапа **в процессе бота** после активации 2942 не было. Последние
  chat-scoped `checkup_triggered` — 2026-11-14 05:48:23Z и два более ранних, и
  все они в **другом** чате (`chat-316e52bad714`), а сохранённая редакция живёт
  в `chat-bb8fd239`. Поэтому live-событие для AC-15 — чекап именно в
  `chat-bb8fd239`; при редком использовании этого чата событие может быть
  нечастым. Это остаётся честным `postrelease_wait`, а не задачей владельца:
  при появлении строки `checkup_triggered` с `chat_id` этого чата агент читает
  `source_ref_json` и ожидает `prompt_layer=chat`, `prompt_withheld=false`,
  `prompt_base_chars=12469`.
- Probe из §4.2 доказывает именно резолв базы (deployed-код, реальные данные,
  состояние процесса как у бота), но не LLM-вызов и не доставку сообщения.

## 8. Тесты (существующие durable, менять не потребовалось)

Контракт уже закреплён и прошёл на deployed-кандидате:

- `tests/test_smart_corrective_prompt_delivery.py` (20 passed): при активной
  политике chat-редакция применяется (`prompt_source/layer=chat`,
  `prompt_base_chars/hash`, `prompt_withheld=false`), global/без chat_id —
  прежний порядок, другой чат не задет;
- `tests/test_soul1_registry_completeness.py`, `tests/test_evol016_prompt_activation.py`,
  `tests/test_evol016_prompt_journal_v39.py`, `tests/test_checkup_contract.py`:
  80 passed, 1 skipped, 1 **предсуществующий** провал
  `test_registry_consumer_pointers_point_at_real_lines` (устаревший line-pointer
  `lore_worker.py:709`, воспроизводится на самом 0beed63d; к этой теме
  отношения не имеет — backlog).

## 9. Как перезапустить

```
# локально (deployed worktree 0beed63d, без prod-данных)
<venv>/python plans/features/smart-corrective-01/evidence/prompt-withheld/probes/local_policy_state_repro.py

# на проде, read-only (DSN из /var/www/admin_bot/.env, соединение read-only)
/var/www/admin_bot/venv/bin/python <copy of prod_policy_state_probe.py>
```

Probe печатает только машинные значения (длины, sha12/hash16, коды) и
redacted-ссылку чата; тексты промптов, chat id и DSN в вывод не попадают.

## 10. Побочная находка (вне lane, на решение PM/Orchestrator)

При измерении global-слоя выяснилось: в процессе бота эффективный **global**
базовый промпт чекапа — это persisted-значение 3 030 символов
(`sha12=b0c70f974e0e`), т.е. **заводская** ревизия `rev:3be4841bca08`
(`origin=factory`, создана cutover-ом 2026-10-31), а не текущий код-фабричный
текст S6 (3 462 символа). Проверка без вывода текста:

```
resolved global (state B): 3 021 chars, sha12 e429735b74bf
  mentions "betterstack": true
  mentions "401": true
factory text (code, S6): 3 462 chars
  mentions "betterstack": false
  mentions "401": false
```

Причина: S6 изменил текст фабрики и печать, но **метку** блока не менял. Печать
на базе 2.58.200 (`0e4a144d`) — `("checkup-p0-24-10", "b0c70f974e0e")`, на S6
(`5d2eb427`) — `("checkup-p0-24-10", "3140bb364044")`, а
`FACTORY_REVISION_LABELS[...] = "checkup-p0-24-10"` не менялась. Поэтому
`activation_plan` даёт `PLAN_NOOP` (`code_revision = fac:sha12(label)`), новая
заводская редакция не активируется, и global-слой остаётся прежним.
Журнал подтверждает: global-ревизии этого блока — только 2026-10-31
(legacy 2 312 + factory 3 030), активаций после этого нет.

Следствие: для чатов **без** своего override действующая инструкция чекапа
по-прежнему упоминает удалённый сценарий Betterstack/401, хотя код-фабрика его
уже не содержит (SC-PRM-STALE-01..04 проверялись на active/historical
*контуре кода*, `live_required: false`). Это осознанное решение S6
(«метку не менять, чтобы не активировать фабрику поверх ручной редакции чата»)
— но теперь, когда есть S6-guard (`factory_superseded_manual`), метку можно
поднять без потери ручной редакции. Это отдельный продуктовый/контрактный шаг
(изменение метки = новая активация global-слоя на следующем старте), поэтому
здесь **не** выполняется и требует решения PM/Orchestrator; правок данных прода
не делалось. Перед поднятием метки нужен аудит chat-override-ов этого ключа в
других чатах: guard сохраняет только чаты, у которых есть живая manual-ревизия,
а override без неё по прежней семантике EVOL-016 будет снят.
