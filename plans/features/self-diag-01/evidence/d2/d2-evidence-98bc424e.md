# SELF-DIAG-01 D2 — привязка доказательств кандидата `98bc424e`

Артефакт составлен PM после независимого ревью кандидата `98bc424ef719083b9392a84918bab0af3b87c587`
и связывает срез **D2** карты `plans/features/self-diag-01/requirements-map.json` с фактически
проверенным кодом. Продуктовый код в этом проходе не менялся, тесты PM не перепрогонял:
поведенческий вердикт принадлежит независимому Reviewer, здесь он зафиксирован построчно —
с именами тестов из дерева кандидата, текстом утверждений и честной границей непроверенного.

Вердикт Reviewer по кандидату: **Needs Fixes, но дефекта безопасности не найдено.** Все
поведенческие требования прошли; три блокера процессные (карта фичи отсутствует в checkout
кандидата, граница визуальной приёмки и граница живой приёмки Telegram).

## 1. Кандидат

| Что | Значение |
|---|---|
| Кандидат | `98bc424ef719083b9392a84918bab0af3b87c587` |
| Родитель | `3b1ba3b2c0b3cb69ecdc5fcc0c5cd54ddfc53515` |
| Сообщение | `feat(self-diag): SELF-DIAG-01 D2 — политика доступа к диагностике` |
| Ветка | `integ/unify-release` (`git merge-base --is-ancestor 98bc424e master` → 1, в `master` не влит) |
| Объём | 8 файлов, +2946 / −3 |
| Продуктовые файлы | `services/diagnostic_policy.py` (+939), `services/output_projection.py` (+294), `services/telegram_role_check.py` (+161), `services/access.py` (+117), `web/api/access.py` (+267), `services/tool_router.py` (+86/−3), `handlers/checkup.py` (+73) |
| Тесты кандидата | `tests/test_diagnostic_policy.py` — 40 функций `def test_` (35 async + 5 sync), включая FastAPI-путь админского API |
| Развёрнуто | **нет.** `deployed_commit` карты по-прежнему `""`; живой приёмки этого кандидата не существует |

Что именно делает кандидат (по коду, не по сообщению коммита): один слой решений
`(actor, chat_scope, data_class, action, destination) → allow|deny|unverified` с машинным
`reason_code`; жёсткие правила (`SECRET_VALUE`, промпт участнику, чужая область чата,
неудостоверяемая личность) стоят **до** матрицы; чат-админ подтверждается только онлайн
`getChatMember` по числовым `chat_id`/`from_user.id`; отзыв прав перепроверяется перед возвратом
результата инструмента и перед публикацией; секреты вычищаются структурно (по фактическим
значениям из типизированных источников, паттерны — вторая линия); аудит хранит только
метаданные. Второго ACL нет: роль владельца — `services.roles.access_for`, матрица — существующие
`param_permissions` + `chat_params.perm_overrides`.

## 2. Структурный блокер №1: карта фичи отсутствует в checkout кандидата

Проверено фактически:

```
git ls-tree 98bc424e plans/features/                    → 59 записей, среди них mod-acl-ux-01 есть
git ls-tree 98bc424e plans/features/self-diag-01/       → пусто
git ls-tree 98bc424e plans/owner_inputs/ | grep self-diag → пусто
```

Причина не в продукте: `plans/features/self-diag-01/` и `plans/owner_inputs/2026-11-09-self-diag-01.md`
созданы уже после точки ветвления `integ/unify-release`. Это та же структурная ситуация, что была
у MOD-ACL M2.

**Решение (то же, что зафиксировано для MOD-ACL):** review-gate **всегда** запускается из
основного checkout против SHA кандидата — `--repo . --candidate <sha>`. Карта в релизную ветку не
переносится: одна карта — один живой леджер, вторая копия немедленно разошлась бы с `master`.
Это процессное ограничение, а не дефект D2; строка «карта отсутствует в checkout» дефектом не
считается.

## 3. Решение по границе №2: визуальная приёмка принадлежит D6

Ревьюер проверял демо-поверхность потому, что политика упоминает админ-UI. Зафиксировано явно:

- **D2 — слой политики.** Строки D2, которые описывают только решение/класс/проекцию/аудит,
  закрываются политическими тестами и рендера не требуют.
- **D6 — отрисованная поверхность.** Строки, для закрытия которых нужен экран, перенесены
  владельцем в D6: `SD1-AMX-01` (подраздел «Самодиагностика» в разделе «Доступы») и
  `SD1-D2-32` (матрица и аудит в админке). Условие приёмки записано в карте и в
  `slice-graph.json`: **отрисованная поверхность Access/Self-Diagnosis, Playwright плюс
  независимый браузер, desktop и mobile**.
- Повторно открывать эти строки как дефект D2 нельзя: политическая часть (9 категорий,
  view/run/edit, отсутствие второго ACL, объяснение наследования, аудит без содержимого) уже
  доказана строками `SD1-D2-07`, `SD1-AC-16`, `SD1-AMX-02`, `SD1-AMX-07`.
- `SD1-D2-08` и `SD1-D2-11` перенесены владельцем в D5: их приёмка требует фактической выдачи
  промпта (дублируют `SD1-AMX-04` и `SD1-D5-08`), политическая часть уже доказана.

## 4. Решение по границе №3: живая приёмка Telegram — обязательство после выката

До деплоя реальную проверку выполнить нельзя, поэтому пять строк D2 переведены в
`READY_FOR_LIVE` с `live_when=postdeploy`, точным условием в `postdeploy_condition` и ссылкой на
откат в `rollback_ref`:

| Строка | Условие после выката |
|---|---|
| `SD1-D2-03` | настроенный числовой Telegram ID получает `chat_admin` по факту `getChatMember` (administrator и creator), участник — нет; отсутствие прав бота даёт `auth_unverified` без protected readback |
| `SD1-AMX-08` | реальная смена статуса администратора во время идущего чекапа — публикации нет, в аудите `revocation_detected` на переходе allow→deny; отдельно «бот не в чате» и отзыв через настройки без рестарта |
| `SD1-AC-10` | в реальном публичном чате участник задаёт произвольный технический вопрос без «чекап» и получает содержательный ответ без credential values и чужих chat contents |
| `SD1-AC-11` | в реальном чате попытки получить действующий промпт прямым запросом, через tool result, cache/metadata и prompt injection — все denied без фрагментов |
| `SD1-AC-14` | перебор маршрутов error/caching/source/tool/replay и запросов к промпту, логу, конфигу, исходникам — ноль раскрытий credential values, включая владельца и админа |

Откат для всех пяти один: возврат на предыдущий неизменяемый релиз **2.58.174 @ `ac943f40`**
(release branch, чистый SHA) без переноса состояния. Пока живое доказательство не снято, эти
строки не могут стать `VERIFIED`, а срез D2 — полным `VERIFIED`.

## 5. Леджер: 33 строки доказаны этим кандидатом

Для каждой строки доказательство — конкретное утверждение теста на дереве кандидата
(`tests/test_diagnostic_policy.py`, если не указано иное) либо читаемый участок кода.

### Роли и идентичность
- `SD1-D2-02` — `resolve_actor()` отдаёт `ROLE_MEMBER` любому удостоверяемому участнику, включая
  личный диалог (`chat_id>0 → STATUS_MEMBER`); публичные классы разрешены (`test_member_reads_public_tech_but_not_prompts`,
  `test_dm_scope_is_member_not_admin`).
- `SD1-D2-04` — владелец только из существующего контура `roles.access_for(...).is_global_admin`
  (`test_project_owner_from_existing_owner_contour`), не «первый админ Telegram».
- `SD1-D2-05` — без `from_user.id` право не возникает: `R_DENY_NO_IDENTITY`/`R_DENY_PROMPT_MEMBER`
  (`test_anonymous_sender_gets_no_prompt_rights`); `sender_chat` в `resolve_actor` не участвует.
- `SD1-D2-06` — проверка в момент решения; `bot=None` → `bot_unavailable`, исключение API →
  `telegram_api_error`, оба `unverified` без raise (`telegram_role_check.py:132-146`);
  `test_auth_unverified_denies_protected_only` (prompts → unverified, bot_server_state → allow).
- `SD1-AMX-02` — три роли матрицы + сопоставление актора со строкой существующей матрицы;
  `bot.calls == [(GROUP_A, ADMIN_ID)]` в `test_chat_admin_verified_by_telegram_api`,
  `test_nickname_and_claims_do_not_grant_admin`, `test_matrix_override_cannot_open_prompts_to_member`.

### Классы данных и матрица
- `SD1-D2-07` — пять классов и правило класса в `default_diag_matrix()`; `test_default_matrix_role_by_class`,
  `test_other_chat_data_rule`, `test_secret_value_class_never_allowed`.
- `SD1-D2-18` — контракт `(actor, chat_scope, resource_chat_id, data_class, action)` с машинными
  `reason_code`; матрица — существующий слой `param_permissions` + `chat_params.perm_overrides`
  (`test_chat_override_beats_global_and_survives_restart`, `test_matrix_snapshot_has_inheritance_and_legend`).
- `SD1-AC-16` — структурные метаданные класса, ресурсный ACL, типизированный каталог как источник
  истины о секретах, общий `sanitize()`; паттерны объявлены второй линией (`output_projection.py:53-64`).

### Жёсткие правила (до матрицы)
- `SD1-AMX-05` — `SECRET_VALUE` = deny участнику и владельцу, `configurable: false` в снапшоте
  (`test_secret_value_class_never_allowed`, `test_matrix_snapshot_has_inheritance_and_legend`).
- `SD1-D2-12` — значение не возвращается ни под настройкой, ни под исходником/логом/конфигом:
  `project_secret_value()` даёт только `name/configured/last4/status`, `sanitize()` применяется и к
  немаркированным инструментам (`test_secret_projection_never_returns_value`,
  `test_non_diagnostic_tool_result_is_sanitized`).
- `SD1-D2-13` — `PROMPT_CONTENT` отдельный класс, а не `SECRET_VALUE`
  (`sensitivity_of_pg_key('prompts.checkup_system_prompt') == PROMPT_CONTENT`).
- `SD1-D2-14` — значение недоступно при любой роли; владелец управляет ключом, но не получает текст
  (`test_secret_value_class_never_allowed`, `test_audit_records_decisions_without_secrets`).
- `SD1-D2-15` — маска + `partially_redacted` + маркер «скрыто:<имя>»; fail-closed для `prompt` при
  недоступных источниках (`test_sanitize_removes_values_and_fails_closed_for_raw_logs`).
- `SD1-D2-09` — участнику короткий отказ без фрагментов и без перечня инструкций, публичная техника
  сохраняется (`test_member_reads_public_tech_but_not_prompts`, `test_explain_is_plain_language_and_secret_aware`).
- `SD1-D2-10` — админ A в чате B получает deny, проверка идёт по `(GROUP_B, ADMIN_ID)`
  (`test_admin_of_chat_a_gets_no_chat_b_prompt`); чужие данные — отдельное hard_rule
  (`test_other_chat_data_rule`).

### Проверка до чтения, до результата и перед отправкой
- `SD1-AC-15` — отказ до чтения и до отправки (`test_checkup_entry_respects_policy_without_reading_logs`:
  `fetcher.fetch` и `service.checkup` не вызывались; `test_tool_call_is_denied_by_policy`).
- `SD1-D2-19` — три точки + `fresh_telegram=True` игнорирует TTL-кэш
  (`test_admin_status_changed_mid_session`, `test_revocation_blocks_publication_of_running_check`,
  `test_policy_change_revokes_running_chat_admin_check`, `test_checkup_entry_publishes_after_recheck`).
- `SD1-D2-20` — решение принимает сервер, подмена `user_id`/`role` в args не поднимает права
  (`test_paraphrased_request_and_args_do_not_elevate`).
- `SD1-D2-22` — отказ не гасит остальную диагностику (`test_auth_unverified_denies_protected_only`).
- `SD1-D2-17` — principal только из Telegram-контекста (`ToolContext.chat_id/user_id`,
  `message.from_user.id`), аргументы модели игнорируются.
- `SD1-D2-21` — у разрешения свой контекст (`DiagnosticGate`), содержимое не кэшируется и не
  логируется, переиспользования между акторами нет (`test_concurrent_admin_and_member_do_not_share_data`).
- `SD1-D2-34` — перед доставкой права перепроверяются заново (`publish → recheck_gate`).
- `SD1-D2-35` — одинаковый текст запроса не даёт общего результата (`[True, False]` в
  `test_concurrent_admin_and_member_do_not_share_data`).

### Секреты в выводе
- `SD1-D2-01` — фильтрация до модели и до Telegram (`ToolRouter._diagnostic_output`,
  `publish → sanitize(kind='final')`), `prompt_digest()` без текста (`test_prompt_digest_has_no_text`).
- `SD1-D2-26` — логи/traceback/любой результат проходят общий санитайзер, fail-closed для
  `logs/traceback/prompt` при недоступных источниках.
- `SD1-D2-27` — паттерны только вторая линия, не единственная защита и не маршрутизация намерения.
- `SD1-D2-28` — серверная проекция вывода, а не просьба в промпте
  (`test_tool_result_never_leaks_secret`, `test_checkup_report_redacts_secrets`).
- `SD1-D2-30` — имена настроек, факт наличия ключа и причина отказа остаются видимыми.

### Аудит
- `SD1-AMX-07` — `decision/denial/gate_open/publication/policy_change/role_check` с actor/chat/role/
  effect/reason/source, `changed_by`/`before`/`after` только в белом списке полей
  (`diagnostic_policy.py:260-267`), секрет и текст промпта отсутствуют и в снапшоте, и в `caplog`
  (`test_audit_records_decisions_without_secrets`), раскрытие фиксируется без текста
  (`test_prompt_disclosure_audit_without_text`).

### Все входы и прозрачность
- `SD1-GRAL-03` — нет скрытия по признаку «внутренности сервера», запрет только по классу/границе/секрету.
- `SD1-GRAL-05` — общей маски на исходный код нет: `source_code` открыт участнику
  (`test_member_reads_public_tech_but_not_prompts`).
- `SD1-SEM-05` — структурная карта `TOOL_CAPABILITIES` вместо regex по описанию/тексту; проверка
  после выбора инструмента в `ToolRouter.dispatch` (`test_indirect_tool_bypass_is_blocked`).
- `SD1-D2-31` — техническое обсуждение не блокируется, ограничен именно запрос промпта.

## 6. Что осталось и при каком условии

### 6.1 Шесть строк D2 остаются PENDING (привязкой этого кандидата не закрываются)

| Строка | Что не выполнено и точное условие |
|---|---|
| `SD1-AMX-09` | Доказано: гейт стоит в единой точке `ToolRouter.dispatch` и в обработчике чекапа, API матрицы требует global_admin (`test_api_requires_global_admin`), кнопки не единственная защита. Не закрыто: входа `inspect_runtime` ещё нет (D3) и отрисованной админской поверхности нет (D6); после их появления та же карта должна быть подтверждена на реальном вызове |
| `SD1-D2-16` | Классификация «заводской промпт, уже опубликованный в публичном GitHub» не реализована: кандидат защищает все промпты как `PROMPT_CONTENT`. Это не утечка (защита строже), но нормативная прозрачность не выполнена; владельца у пункта сейчас нет |
| `SD1-D2-23` | `sensitivity_of_pg_key` реализован по `param_catalog`, но «для нового провайдера sensitivity обязательна при регистрации» не обеспечено: `ParamSpec.secret` по умолчанию `False`, новый провайдер без флага молча становится `NON_SECRET_CONFIG` |
| `SD1-D2-24` | `DiagnosticEvidenceBundle` появится в D3 (`SD1-EVD-04`); типизированный settings adapter с `configured/effective/last_success/last_error_code/key_fingerprint` не добавлен |
| `SD1-D2-25` | Чтение `.env`/credential-конфигов инструментом не ограничено: source reader этим кандидатом не менялся (D4), typed settings adapter не добавлен; у пункта нет владельца-слайса |
| `SD1-D2-29` | Доказано только для tool result, финальной доставки, аудита и логов слоя. Не покрыто: observability traces, debug requests, retries, source references (D4), HTML/Markdown preview (D6); у этих поверхностей нет владельца-строки |

`SD1-AMX-09`, `SD1-D2-23`, `SD1-D2-25`, `SD1-D2-29` — не «остатки ревью», а **отсутствующие
владельцы** подпунктов: чтобы закрыть срез, нужно решить, какой слайс их исполняет, и только потом
ставить статус.

### 6.2 Пять строк `READY_FOR_LIVE` (см. §4) — только после выката.

### 6.3 Четыре строки перенесены владельцем (см. §3): `SD1-AMX-01`, `SD1-D2-32` → D6; `SD1-D2-08`, `SD1-D2-11` → D5.

## 7. Предсуществующие падения набора (не регресс D2)

Ревьюер зафиксировал три падения, которые воспроизводятся на родителе `3b1ba3b2` и не связаны с
этим кандидатом: `test_every_editable_prompt_has_reachable_surface`,
`test_forbidden_paths_out_of_diff`, `test_grep_audit_counts_are_stable`. Записано один раз в
`plans/backlog.md` как пункт обслуживания; D2 они не блокируют и в карту требований D2 не входят.

## 8. Результат gate (main checkout, `--repo .`)

План-гейт после привязки:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/self-diag-01/requirements-map.json --stage plan --repo .
→ stage=plan inventory=183 manual=53 scoped=0 errors=0
```

Ревью-гейт, срез D2, кандидат `98bc424e`:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/self-diag-01/requirements-map.json \
  --stage review --slice D2 --candidate 98bc424e… --repo .
→ stage=review inventory=183 manual=53 scoped=47 errors=6
  все шесть: mandatory not ['VERIFIED'] (got PENDING)
  SD1-AMX-09, SD1-D2-16, SD1-D2-23, SD1-D2-24, SD1-D2-25, SD1-D2-29
```

`scoped=47` — это строки среза (44 уникальных `req_id`: у `SD1-D2-03`, `SD1-AMX-07`, `SD1-GRAL-05`
по две исходные строки с одинаковой приёмкой). Ни одной ошибки привязки доказательств:
`artifact_path`/`artifact_sha256`, Git-объект кандидата, типы живых доказательств и граф слайсов
проходят проверку. Оставшиеся шесть ошибок — честный остаток работ из §6.1, а не дефект привязки.

## 9. Честная граница

- PM не перепрогонял тесты: имена тестов и утверждения взяты из дерева `98bc424e`, поведенческий
  вердикт — независимого Reviewer.
- Кандидат **не развёрнут**: ни одно живое поведение этим артефактом не подтверждено.
- Границы, зафиксированные в карте полем `boundary` у отдельных строк, означают: доказана часть
  D2, а названная часть принадлежит другому слайсу и там отслеживается (`SD1-EVD-04` для
  evidence-буфера, `SD1-EVD-13` для бюджета вывода, D5 для текста предупреждения и выдачи промпта,
  D3/D7 для попадания результата в память и историю LLM).
- Срез D2 **не является** полным `VERIFIED`: 33 строки доказаны, 5 ждут выката, 6 требуют
  исполнения или назначения владельца.

## 10. Решение владельца 2026-11-10: три подпункта получили исполнителя

§6.1 сохраняется как история состояния на момент привязки (`98bc424e`, 6 PENDING). После того как PM
честно зафиксировал, что у трёх подпунктов нет владельца-слайса, владелец назначил их сам — **без нового
гейта проверки, только распределение ответственности**:

| Строка | Владелец | Почему одной строкой |
|---|---|---|
| `SD1-D2-25` — чтение `.env`/credential-конфигов инструментом не ограничено | **D4** | ограничение принадлежит тому слайсу, который вводит сам механизм чтения (source reader, deploy identity, SHA, история коммитов) |
| `SD1-D2-29a` — observability traces, debug requests, retries, source references | **D4** | эти поверхности порождает та же runtime-introspection поверхность, что и D4 |
| `SD1-D2-29b` — HTML/Markdown preview | **D6** | предпросмотр — отрисованная поверхность, её приёмка идёт с Playwright и независимым браузером |
| `SD1-D2-16` — заводской промпт из публичного GitHub классифицируется как публичный | **D5** | раскрытие и классификацию промптов определяет prompt readback |

Форма записи: `SD1-D2-29` остаётся одной строкой с держателем **D4** и двумя подпунктами
(`sub_obligations`: `SD1-D2-29a` → D4, `SD1-D2-29b` → D6); строка закрывается после обеих частей, ни одна
не теряется. Приёмка, `source_line`/`source_sha256` и история строк не изменялись — сменился только
владеющий этап, поля `reassignment` и `remaining` описывают новое условие закрытия.

**Честно про `SD1-D2-16`:** реализованная защита **строже** требования — кандидат не раскрывает ничего,
включая владельца, поэтому утечки нет и дефекта безопасности нет. Открыта нормализация правила
прозрачности (какой заводской промпт уже публичен и где нельзя обещать секретность), а не исправление
утечки.

### Три оставшихся PENDING — не дефекты D2

| Строка | Чего ждёт |
|---|---|
| `SD1-AMX-09` | вход `inspect_runtime` появится в D3, отрисованная поверхность — в D6; затем та же карта `TOOL_CAPABILITIES` подтверждается на реальном вызове |
| `SD1-D2-23` | обязательный флаг sensitivity при регистрации провайдера (`ParamSpec.secret` сейчас по умолчанию `False`) |
| `SD1-D2-24` | evidence bundle D3 (`SD1-EVD-04`) и typed settings adapter с `configured/effective/last_success/last_error_code/key_fingerprint` |

### Границы после перераспределения

Доли слайсов: **D2 — 41, D4 — 18, D5 — 21, D6 — 32**, общий итог эпика по-прежнему **182** (ни одна
строка не удалена и не добавлена). Срез D2: **33 VERIFIED, 5 READY_FOR_LIVE, 3 PENDING**.

```
--stage plan                                   → inventory=183 manual=53 scoped=0  errors=0
--stage review --slice D2 --candidate 98bc424e → inventory=183 manual=53 scoped=44 errors=3
   SD1-AMX-09, SD1-D2-23, SD1-D2-24 — mandatory not ['VERIFIED'] (got PENDING)
```

Счёт ошибок в срезе D2 уменьшился с 6 до 3 **не потому, что работа сделана**, а потому, что три строки
перестали принадлежать срезу по решению владельца. На эпик это не влияет: те же обязательства теперь
ждут закрытия в D4/D5/D6 и обязаны быть там проверены.
