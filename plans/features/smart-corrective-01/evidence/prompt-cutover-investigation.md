# Расследование конфликта активации prompt — SMART-CORRECTIVE-01

Статус: завершено, read-only расследование. Код, production data и карты требований не изменялись.
Объект: production deploy 2.58.201, candidate `409f4e8a` (`409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9`).

## Итог

После deploy factory-редакция чекапа стала активной в CHAT_C2 поверх сохранённой ручной
редакции владельца. Manual bytes не потеряны: `rev:d31300ef35a0`, `origin=manual`,
12 469 символов, SHA-256 prefix `31d175065461`, `retired=false`. Активна factory
`rev:9ed7b22b0d8c`, 3 462 символа, `fac:d263c52f7871`, activation `2941`.

Причина — не нарушение целостности журнала, а несовместимость старой EVOL-012/016
семантики с более новым corrective-контрактом владельца. EVOL-016 признаёт scope
защищённым (`pinned`) только при наличии последнего события `baseline_assign`; простого
`origin=manual` или наличия незавершённой manual-ревизии недостаточно. В production
для этой редакции был `manual_edit` (activation `2940`), но не подтверждён
`baseline_assign`, поэтому cutover пошёл по обычной ветке `factory_activate`.

По последнему owner-тексту 2026-11-14, §8.1 / AC-15 / AC-19, сохранённая редакция
должна реально применяться на checkup route и не заменяться factory-текстом при
исправлении или deploy. Этот более новый контракт имеет приоритет над прежним
EVOL-012, допускавшим автоматическую активацию новой factory-редакции поверх ручной.

## Точная цепочка кода

1. `services/prompt_registry.py:792-849` — `activation_plan(...)`:
   - одинаковая factory revision → `PLAN_NOOP`;
   - `pinned=True` при новой factory revision → `PLAN_ACTIVATE_PINNED`, причина
     `factory_superseded_pinned`;
   - иначе → обычный `PLAN_ACTIVATE`, причина `new_factory_revision`.
   Сам по себе `origin=manual` в этот выбор не входит.
2. `services/prompt_release_policy.py:2437-2447` читает только
   `store.read_baseline_event(block_id, scope, chat_id)` и выставляет `pinned=True`,
   если событие существует, имеет `kind == "baseline_assign"` и `revision_id`.
   `manual_edit` activation `2940` таким событием не является.
3. `services/prompt_release_policy.py:2479-2525` — pinned-ветка сохраняет текущий
   указатель и пишет `factory_superseded_pinned`; она не была достигнута.
4. `services/prompt_release_policy.py:2532-2558` — обычная ветка вставляет factory
   revision, пишет active value и activation с `detail_code="factory_activate"`.
5. `services/prompt_release_policy.py:2560-2567` — для chat scope обычный cutover
   удаляет chat override и уведомляет chat. Это объясняет изменение nested overrides
   `32→31`; manual revision в `prompt_revisions` при этом не удаляется.
6. `services/checkup_service.py:112-156, 594-597` — runtime resolution имеет
   требуемый порядок chat override → global → factory. Поэтому после удаления
   override route использовал factory, а не историческую manual revision.
7. `services/checkup_service.py:675-675, 803-823` — telemetry фиксирует
   `prompt_source`, `prompt_base_hash` и `prompt_base_chars`; это подходящее
   наблюдаемое доказательство после восстановления.

## Доказательства production и охват

- `plans/features/smart-corrective-01/release-evidence/2.58.201/effective-config.txt:73-99`:
  manual `rev:d31300ef35a0`, activation `2940`; factory `rev:9ed7b22b0d8c`,
  activation `2941`, `deploy_activate/factory_activate/applied`; global
  `prompts.checkup_system_prompt` неизменён — 3 030 символов, SHA prefix `b0c70f974e0e`.
- `.../release-evidence/2.58.201/deploy.md:153-174` подтверждает сохранность manual
  revision и снятие chat override.
- `.../requirements-map.json` row `SC-PRM-OWNER` и
  `investigation/production-runs-and-incidents.md` подтверждают CHAT_C2 как единственный
  найденный сохранённый owner manual prompt; CHAT_DM8 override отсутствует.
- По имеющимся evidence подтверждён supersede только для CHAT_C2. Иных chat/DM manual
  prompt supersede не установлено; это не следует выводить из одного digest профилей.
  Для безопасного production remediation нужно отдельно перечислить все активные
  `prompt_activations` по `checkup.base.system` и сопоставить их с
  `prompt_revisions` до записи.

## Минимальная ремедиация

### Немедленно: data-only восстановление

Активировать именно существующую `rev:d31300ef35a0` в scope `chat` для CHAT_C2 через
штатный `activate_revision` (EVOL-017), не писать тело вручную, не удалять factory
revision и не создавать clone. При расхождении с текущим factory state API выберет
`manual_rollback`; ожидаемый activation detail — `activate:manual`, outcome `applied`.
Существующий тест `tests/test_evol016_prompt_activation.py:224-265` подтверждает, что
такое восстановление сохраняет исходный revision id, историю и переживает restart.

Перед записью обязательно:

1. CAS/lock и повторное чтение active state; убедиться, что target revision имеет
   `scope=chat`, правильный `chat_id`, `retired=false`, `schema_compat` совместим и
   body SHA равен `31d175065461...`.
2. Выполнить ровно одну активацию. Повторный запуск после успешной записи должен быть
   `skipped_same`/no-op, без второго содержательного переключения.
3. Проверить active pointer, chat override и post-restart cache invalidation.
4. Выполнить checkup в разрешённом production-проверочном контуре и зафиксировать
   `prompt_source=chat`, `prompt_base_chars=12469`,
   `prompt_base_hash=31d175065461...`, `prompt_withheld=false`; проверить, что
   global 3 030-символьная редакция и factory 3 462-символьная редакция не были
   изменены.

Это минимально исправляет уже возникшее состояние и не требует redeploy: код
2.58.201 уже умеет активировать конкретную совместимую revision.

### Защитный code fix: нужен до следующего factory cutover

Data-only восстановление не устраняет повторяемость: следующий релиз с изменившимся
factory content снова увидит отсутствие `baseline_assign` и может удалить chat
override. Поэтому для соответствия новому §8.1 нужен небольшой S6/EVOL-016 guard:

- при `scope=chat` перед обычным factory cutover проверять наличие активной или
  сохранённой, не retired manual revision этого же block/chat, а не только
  `baseline_assign`;
- при наличии такой revision не выполнять `_write_active_value` и
  `remove_chat_override`; оставлять manual pointer и писать диагностическое
  `factory_superseded_manual`/эквивалентное событие с новым явным detail code;
- factory revision продолжать регистрировать в истории, чтобы не терять поставку;
- baseline semantics для явно назначенного baseline не ломать и не смешивать с
  обычной manual history без отдельного owner choice.

Минимальные тесты: manual_edit без baseline + новый factory content не делает
cutover; restart/repeated release остаются no-op; explicit factory forward через
EVOL-017 по-прежнему работает; два разных chat scope изолированы. Это уже изменение
кода и требует review и redeploy (например, 2.58.202). До него не запускать новый
автоматический cutover, который может затронуть этот chat.

## Риск двойной активации и rollback

Не следует одновременно вручную писать chat override и вызывать release cutover:
это создаёт конкурирующие activation records и последний writer может вернуть factory.
Операция должна использовать существующий transaction/apply-lock путь `activate_revision`.
Rollback data-only — повторно активировать factory revision `rev:9ed7b22b0d8c` через
тот же API с явным `kind="manual_forward"` только при отдельной необходимости; это
не является рекомендуемым исправлением текущего owner-контракта. Кодовый rollback —
обычный возврат к последнему проверенному SHA, данные журнала не откатывать.

## Решение Architect и статус owner choice

`ARCHITECT_ADJUSTMENT_REQUIRED`: текущий EVOL-016 contract использует слишком узкий
признак pinned для нового §8.1; минимальная коррекция — временно восстановить
конкретную manual revision data-only и добавить guard против factory cutover поверх
существующей manual chat revision.

Новый вопрос владельцу не требуется: §8.1/AC-15/AC-19 уже однозначно задают
наблюдаемое поведение. Развилка «data-only сейчас или кодовый fix» техническая:
data-only исправляет текущий incident без redeploy, code fix обязателен для
устранения повторения перед следующим затрагивающим релизом.

## Ограничения доказательства

Production DB и live checkup в этой read-only архитектурной проверке не выполнялись;
факт активаций взят из сохранённых release-evidence. Поэтому восстановление,
post-action provenance и полный аудит других chat scopes остаются обязательными
операционными действиями исполнителя remediation, но не требуют изменения owner
контракта.

Риск: R1 — повторный cutover до guard; R1 — неверный chat scope при ручном вызове;
R2 — stale cache после activation; R2 — неполный аудит других overrides. R0/R3
рисков по сохранности bytes или схеме не обнаружено.
