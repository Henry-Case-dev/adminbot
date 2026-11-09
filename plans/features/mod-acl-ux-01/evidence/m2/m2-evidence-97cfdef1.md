# M2 — доказательство кандидата `97cfdef1`: канонический резолвер GLOBAL-дефолт → CHAT-override

Артефакт составлен PM после независимого ревью кандидата `97cfdef1` и связывает срез **M2**
карты `plans/features/mod-acl-ux-01/requirements-map.json` с фактически проверенным кодом.
Продуктовый код в этом проходе не менялся, тесты PM не перепрогонял: поведенческий вердикт
принадлежит Reviewer, здесь он зафиксирован построчно и с честной границей непроверенного.

Источник требований: `plans/owner_inputs/2026-11-09-mod-acl-ux-01.md` §2.1–§2.4, §3.2, §4.2,
§10, §11, §12 (строки 16–23, 48–49, 65–74, 81–92, 96–116, 570–619, 678–686).

## 1. Кандидат

| Что | Значение |
|---|---|
| Кандидат | `97cfdef114609512b2d340fd619fb108d82593cd` |
| Родитель | `adfd0d0c4125264f9a623e8169bf17ae47261470` |
| Сообщение | `feat(acl): MOD-ACL-UX-01 M2 — единый резолвер GLOBAL-дефолт → CHAT-override` |
| Ветка | `integ/unify-release` (`git merge-base --is-ancestor 97cfdef1 master` → 1, в master не влит) |
| Объём | 16 файлов, +1413 / −180 |
| Продуктовые файлы | `services/chat_params.py` (+289), `services/feature_gates.py`, `services/permsoc.py`, `services/worker_settings.py`, `services/mca_experience_jobs.py`, `web/api/gates.py`, `web/api/memory_agi.py`, `scripts/mod_acl_effective_state_report.py` (новый) |
| Тесты кандидата | новый `tests/test_mod_acl_ux_m2_resolver.py` (10 проверок); обновлены 4 legacy-файла |
| Развёрнуто | **нет**. M2 не имеет собственного деплоя: `deployed_commit` карты относится к релизу M5L (2.58.172 @ `bee14188`) и для M2 не применяется |

## 2. Почему карта требований живёт только на master и как из-за этого сломался gate

Ревьюер запускал review-gate из **изолированного checkout кандидата** и получил отказ:

```
requirements_gate.py check --map plans/features/mod-acl-ux-01/requirements-map.json ...
→ map недоступна: в дереве 97cfdef1 файла plans/features/mod-acl-ux-01/requirements-map.json нет
```

Причина — не дефект продукта и не «пропавшая» карта, а расхождение веток:

- дерево кандидата `97cfdef1` содержит только часть `plans/features/mod-acl-ux-01/`:
  `m2-resolver.md`, `reports/m2-impact-fixture.json`, `reports/m2-impact-fixture-dry-run.md`,
  `reports/deploy-2.58.172.md`, `evidence/mac-exp-06-live-2.58.170.md`;
- `requirements-map.json`, `plan.md`, `slice-graph.json`, `m0-baseline.md` существуют **только в
  master** (`a947b900` и ранее через `5e0fbc28 docs(plans): preserve MOD-ACL/SELF-DIAG/VMQ maps…`);
- release-ветка `integ/unify-release` исторически несёт лишь подмножество `plans/`, поэтому
  изолированный checkout кода физически не может выполнить gate против карты.

Это ограничение процесса, а не доказательство по требованиям. Два durable-варианта:

1. **Минимальный и уже применённый:** gate запускается **из main checkout** с `--repo .`,
   а `--candidate` указывает на SHA кандидата. Карта и артефакты лежат в рабочем дереве, Git-объект
   кандидата существует локально (`git cat-file -e 97cfdef1^{commit}` → ok), strict-проверка
   артефактов идёт относительно main checkout. Так и сделано в §15.
2. **Durable-дополнение (рекомендация):** при выпуске релиза переносить `plans/features/<epic>/`
   (`requirements-map.json`, `slice-graph.json`, `plan.md`, `evidence/`) в release-ветку тем же
   коммитом, что и релизный bump, либо закрепить в чек-листе релиза явное «gate запускается из
   main checkout против SHA кандидата». Второй вариант дешевле и не смешивает планы с релизным
   деревом; первый нужен, если ревью должно быть воспроизводимо из одного checkout.

Ограничение зафиксировано, чтобы следующий Reviewer не считал отсутствие карты в checkout
дефектом M2.

## 3. Шесть строк таблицы §2.1 — доказано

Таблица проверена для **двух** классов модулей, чтобы строка 5 не держалась на одном домене:

- глобальный модуль (`module_registry` → `flags.initiative_enabled`) —
  `tests/test_mod_acl_ux_m2_resolver.py::test_six_case_table_global_module`;
- per-chat модуль «Опыт и уроки» (`memory.experience_learning_enabled` + worker-гейт) —
  `test_six_case_table_per_chat_experience`.

| GLOBAL | CHAT | ожидаемый effective | ожидаемый source | что утверждает тест |
|---|---|---|---|---|
| ON | INHERIT | ON | `global` | `state.desired is True`, `effective_runtime is True`, `chat_state == "inherit"` |
| ON | ON | ON | `chat` | `chat_state == "on"` |
| ON | OFF | OFF | `chat` | `chat_state == "off"` |
| OFF | INHERIT | OFF | `global` | наследование выключенного дефолта |
| **OFF** | **ON** | **ON** | **`chat`** | **строка, сломанная до M2** (`if not global: return False` удалён) |
| OFF | OFF | OFF | `chat` | явное выключение чата |

`TRUTH_TABLE` в тесте — ровно эти шесть комбинаций; `chat=None` означает «записи нет», то есть
настоящий `INHERIT`, а не `false`. Дополнительно проверяется, что оси не схлопнуты: при проверке
таблицы `ready is None`, `authorized is None`, `observed is None`, `emergency_block is False`.

## 4. Три состояния чата: `INHERIT` отличим от явного `false`

- `services/chat_params.py`: `INHERIT = "inherit"` (L792), `CHAT_STATES = (INHERIT, ON, OFF)`
  (L795), `chat_state()` (L882–888): нет записи → `INHERIT`, `true` → `ON`, `false` → `OFF`.
- `test_absent_is_inherit_explicit_false_is_off`: при глобальном ON чат без записи даёт
  `chat_state=INHERIT / desired=True / source=global`, чат с записанным `false` даёт
  `chat_state=OFF / desired=False / source=chat`. Два состояния различимы и дают разный effective.
- `test_u4_global_off_chat_on_still_learns` дополнительно фиксирует, что `INHERIT` **не
  материализуется**: после прохода `-200 not in cache._by_chat` (запись не создана).

Что этим **не** доказано: путь записи «Наследовать» (удаление только своего override). Ни один
тест кандидата не вызывает удаление/очистку override. См. §13, группа D.

## 5. Один канонический резолвер; копии приоритета удалены в объявленных потребителях

`services/chat_params.py` — единственная реализация семантики: чистое ядро `resolve_capability()`
(L925) и три адаптера доменов — `resolve_param_capability()` (L983, `chat_params.overrides`),
`resolve_gate_capability()` (L1004, `chat_params.gates`), `resolve_module_capability()` (L1025,
`module_registry`).

| Потребитель | Было | Стало (кандидат) |
|---|---|---|
| `services/feature_gates.py` | собственный приоритет + тихий глобальный veto | `gate_state()` L134 и `gates_enabled()` L169 → `chat_params.resolve_gate_capability` |
| `services/permsoc.py` | своя копия `gates → overrides → hot` | `master_enabled()` L106 → `feature_gates.gates_enabled` → тот же резолвер |
| `services/mca_experience_jobs.py` | `if not global: return False` | `learning_state()` L762 / `learning_enabled_for_chat()` L777 → `resolve_param_capability` |
| `services/mca_experience_jobs.py` | глобальный продуктовый флаг глушил shared job | `review_enabled()` L805 — только аварийные env-оси K1/K3 |
| `services/worker_settings.py` | вторая копия `chat → global → default` | `chat_params.read_override` / `read_global` (L44–48) |
| `web/api/gates.py` | плоский bool по фиче | аддитивный `states{}` из `state.as_dict()` (GET `/api/chat/{id}/gates`) |

Доказательства согласованности: `test_one_resolver_no_second_gateway` (одинаковый вход →
одинаковый `desired`/`chat_state`/`source` для модульного и гейтового домена) и
`test_gate_domain_rows_and_permsoc_alias` (6 комбинаций домена `gates` + read-compat alias
`permsoc`; alias действует **только** при `INHERIT`, явный гейт важнее alias; второй потребитель
`permsoc.master_enabled` даёт тот же результат).

## 6. Сохранённые значения не переписываются

`test_stored_explicit_false_is_never_rewritten` — активное доказательство, а не декларация:

1. в чате сохранены `experience_learning_enabled=false`, `flags.initiative_enabled=false`,
   `gates={"dream": false, "permsoc": false}`; снимок хранилища снят через `copy.deepcopy`;
2. `chat_params.set_chat_params` подменён на функцию, которая **бросает `AssertionError`** —
   любая попытка записи уронила бы тест;
3. последовательно вызваны read-пути: `learning_enabled_for_chat`, `resolve_module_capability`,
   `feature_gates.gates_enabled` (дважды, для разных чатов);
4. утверждается: `cache.by_chat == snapshot` (побайтово то же содержимое), `cache.invalidated == []`
   (инвалидации кэша не было), сохранённый `false` остался `false`.

Плюс в `test_u4_global_off_chat_on_still_learns`: после тика `cache._by_chat[-100]` равен исходному
`{"memory.experience_learning_enabled": True}` — глобальное OFF не переписало чатовый override.

## 7. Раздельные оси: `desired` / `effective_runtime` / `readiness` / `authorisation` / `observed`

`CapabilityState` (L806) и `as_dict()` (L836) отдают 14 отдельных полей:
`capability, key, domain, chat_id, chat_state, desired, source, global_value, global_source,
emergency_block, effective_runtime, ready, authorized, observed`.

`test_state_snapshot_exposes_separate_axes` фиксирует одновременное состояние: `chat_state=inherit`,
`desired=True` (наследует глобальный ON), `source=global`, `ready=False` (своя ось),
`effective_runtime=False` (готовность блокирует исполнение), `authorized=True` (права — своя ось,
модуль не превращается в OFF), `observed=None` (наблюдения нет, и это не выводится из
`effective_runtime`). Тест утверждает и точный набор ключей снимка, то есть «один bool вместо осей»
структурно невозможен.

## 8. Shared worker при GLOBAL OFF

- `review_enabled()` (L805–820): решение shared-job принимают **только** `experience_lessons_enabled()`
  и `experience_review_enabled()` (аварийные env-оси K1/K3), продуктовый флаг в решении не участвует.
- Допустимость чата проверяется в самих проходах перед дорогими действиями:
  `learning_enabled_for_chat(...)` в L1585, L1643, L1700, L2180, L3699
  (`mca_experience_jobs.py`).
- `test_global_off_chat_on_worker_runs_and_selects`: при GLOBAL OFF `review_enabled() is True`,
  `learning_enabled_for_chat(-100) is True` (явный ON), `learning_enabled_for_chat(-200) is False`
  (INHERIT наследует OFF).
- `test_u4_global_off_chat_on_still_learns` (интеграционный, реальная SQLite-БД):
  `tick_experience_review → "completed"` при GLOBAL OFF; в `mca_experience_feedback` попал
  **только** чат `-100`; `detector_skipped == 1`, `detector_detected == 1`; сохранённый override не
  переписан; `-200` не материализован.
- `test_u4_chat_off_is_local_other_chat_learns`: чат `-100` с OFF пропущен осознанно (курсор
  продвинут, `detector_skipped == 1`), чат `-200` обработан; урок `-200` не виден в `-100`
  (межчатовая изоляция), виден в `-200`.

## 9. Аварийная env-ось

`test_env_kill_switch_overrides_table`: при `MCA_EXPERIENCE_LESSONS_ENABLED=False` и
`env:initiative=False` для чата с явным ON —
`desired is True` (желание пользователя не подменяется), `emergency_block is True`,
`effective_runtime is False`, `learning_enabled_for_chat is False`; то же для модуля `initiative`.
То есть kill-switch — отдельная техническая ось поверх `desired`, а не второй master и не тихая
замена глобального значения.

## 10. Impact-report: детерминированный read-only отчёт на фикстуре

Скрипт: `scripts/mod_acl_effective_state_report.py` (новый, 388 строк). Режим `--fixture` не
касается БД; режим `--database` заявлен как read-only (`SELECT` по `bot_settings`/`chat_profiles`,
без DDL/сида/миграций).

Вход: `plans/features/mod-acl-ux-01/reports/m2-impact-fixture.json` (4 глобальных ключа, 1 env-ось,
4 чата: `-100` override ON, `-200` gate OFF, `-300` без записи, `-400` gate ON).
Выход: `plans/features/mod-acl-ux-01/reports/m2-impact-fixture-dry-run.md`.

| Показатель | Значение |
|---|---|
| capability в отчёте | **16** |
| чатов | **4** |
| изменённых пар (чат × capability) | **3** |
| чатов с изменением поведения | **2** |
| направление изменений | только **OFF → ON** |
| пары | `-300`: `gate:dream`; `-100`: `gate:dream`, `module:experience` |
| без изменений | `-400`, `-200` |

`test_impact_report_is_deterministic_on_fixture` утверждает: два прогона `build_report` идентичны,
два рендера markdown идентичны, набор пар равен трём перечисленным, `changed_pairs == 3`,
`changed_chats == [-300, -100]`, каждый элемент `new=True, old=False`, в markdown нет процентов и
каждый чат назван отдельно. Это доказывает корректность и детерминизм механизма отчёта, но **не**
заменяет production-цифры (§13.1).

## 11. Обновлённые legacy-тесты

Кандидат изменил ожидания четырёх legacy-тестов, которые ранее утверждали снятую семантику
«GLOBAL OFF глушит все чаты». Reviewer проверил, что замена не ослабила всё ещё обязательное
свойство безопасности:

| Файл: тест | Что было | Что стало |
|---|---|---|
| `test_asap8_f5_module_truth.py::test_m6_global_default_is_inherited_not_prohibitive` | `test_m6_global_master_off_disables_all_chats` | GLOBAL OFF не запрет; чат ON исполняется, INHERIT наследует OFF, shared-job не остановлен |
| `test_asap8_v6_d05_experience.py::test_u4_global_off_chat_on_still_learns` | `test_u4_global_master_off_silences_all_chats` | тик `completed`, обработан только eligible-чат, override не переписан |
| `test_mca16_experience_block_e_round1039.py::test_settings_apply_without_restart` | проверял остановку shared-job продуктовым флагом | `review_enabled()` зависит только от K1/K3; глобальная ось видна там, где её читают |
| `test_settings_worker_sync_round1018.py::test_global_flag_is_default_not_veto`, `::test_global_flag_does_not_veto_cognition_active` | kill-switch-veto | глобальный флаг — дефолт, не veto |

## 12. Независимая проверка Reviewer (по его леджеру)

Reviewer работал на кандидате `97cfdef1` (родитель `adfd0d0c`) и подтвердил, все пункты VERIFIED:

1. GLOBAL — наследуемый дефолт, а не запрет;
2. три состояния `INHERIT/ON/OFF`, отсутствие записи отличимо от явного `false`;
3. все шесть комбинаций truth-table;
4. `GLOBAL OFF + CHAT ON` работает и для глобального модуля, и для per-chat модуля опыта;
5. один канонический резолвер, копии приоритета удалены в объявленных потребителях;
6. сохранённые значения не переписываются (доказано запрещённым `set_chat_params` и сравнением
   снимка);
7. оси `desired` / `effective_runtime` / `readiness` / `authorisation` / `observed` разделены;
8. shared worker продолжает тикать при GLOBAL OFF, обрабатывает только eligible-чат, `INHERIT`
   пропускает;
9. аварийная env-ось даёт `effective_runtime=False` при `desired=True`;
10. impact-fixture детерминирован и read-only, изменённые пары перечислены поштучно;
11. четыре обновлённых legacy-теста заменили снятую семантику и не ослабили обязательное свойство
    безопасности.

Первый вердикт Reviewer — **Needs Fixes только по размещению доказательств** (карта отсутствует в
изолированном checkout кандидата), продуктовая логика дефектной не признана. PM тесты не
перепрогонял: числа и имена тестов выше взяты из дерева кандидата и леджера Reviewer.

## 13. Честная граница: что этим артефактом НЕ доказано

### 13.1. Production impact report не выполнялся

`--database`-прогон `scripts/mod_acl_effective_state_report.py` по production PostgreSQL **не
запускался**: нет артефакта с реальными парами `GLOBAL OFF + сохранённый CHAT ON`, реальными
counters и подтверждением, что read-only режим ничего не изменил в БД. Фикстура (§10) доказывает
механизм, но не фактические данные владельца. Блокирует: `MAC-S2-106`, `MAC-S10-10`,
`MAC-S2-105` (снимок фактических сохранённых значений и коллизий).

Требуемое условие: read-only прогон DevOps, отчёт с перечнем пар по чатам, `git`-независимое
подтверждение отсутствия записи (например, `xmin`/`updated_at` до и после) и приложенный артефакт.

### 13.2. Живых наблюдений нет

Все строки M2 с `live_required: true` (live_when `preprod`) остаются `PENDING`: кандидат не
развёрнут, живого бота с этими настройками не наблюдали. Это:
`MAC-S2-TT-1…TT-6`, `MAC-S2-81`, `MAC-S2-AX-05`, `MAC-S2-SHARED-01`, `MAC-S10-01`,
`MAC-AC-02`, `MAC-AC-03`, `MAC-AC-04`, `MAC-S15-12`, `MAC-S15-1-01`.

Семантика `GLOBAL OFF + CHAT ON` **на уровне контракта** доказана тестами (§3), но строки TT-*
сами требуют живого подтверждения в runtime — этот разрыв честно сохраняется, а не закрывается
ссылкой на unit-тест.

### 13.3. Пробелы, не связанные ни с отчётом, ни с живым наблюдением (37 строк)

Кандидат их не покрывает. Часть — незакрытый объём самого M2, часть — вопрос владельца среза
(нужно решение координатора/Architect, а не пере-слайсинг карты PM-ом).

**D1. Полей/осей в ответе нет (5).** `MAC-S2-85` — требование перечисляет `observed_at`,
`last_activity_at`, `reason_code`, `pending_restart`, `version`, `can_read`, `can_edit`;
`CapabilityState.as_dict()` и `states{}` в `web/api/gates.py` отдают 14 других полей, этих семи нет.
`MAC-S2-AX-03` — readiness провайдера/worker/модели/зависимостей не вычисляется (`ready` приходит
извне и в API равен `None`). `MAC-S2-AX-04` — `authorized` не вычисляется для actor/scope/operation
(ось есть, значение не заполняется). `MAC-S15-1-02` — причина отказа `consent_required` /
`permission_denied` / `emergency_block` как различимые коды не реализована (есть только
`emergency_block`). `MAC-S2-GATE-01` — вторая часть (точная диагностика причины при несовместимости
старых gate-систем) не реализована; первая часть (kill-switch не подменяет master) доказана в §9.

**D2. Путь записи «Наследовать» (2).** `MAC-S0-02`, `MAC-S2-104` — чтение tri-state и различие
`INHERIT`/`false` доказаны (§4), но удаление только своего override при выборе «Наследовать» ни
одним тестом кандидата не проверено.

**D3. Старые opt-in (1).** `MAC-S2-92` — двойное veto снято (строка 5 таблицы), но семантика
`gates_opt_in`/старых chat gates на кандидате не проверялась: `test_m6_worker_skips_not_opted_in_chat`
гейтит `learning`-параметр, а не `gates_opt_in`.

**D4. Инвентаризация (1).** `MAC-S2-102` — в `m2-resolver.md` перечислены 6 потребителей, но нет
tool router, schedulers и UI; «все реальные runtime readers» не приложены.

**D5. Сохранность механизмов (1).** `MAC-S2-107` — `updated_at`/optimistic version/PG NOTIFY/cache
invalidation и доставка изменения из UI до hot-consumers без рестарта не проверены
(`test_settings_apply_without_restart` покрывает только чтение hot-значения).

**D6. Поведение за пределами проверенного (3).** `MAC-S2-113` (повторная проверка перед публикацией
инициативы), `MAC-S2-114` (история/прошлые ответы/индекс сохраняются при OFF), `MAC-S2-115`
(повторное включение без replay/backfill).

**D7. Каталог и UI-контракт (11).** `MAC-S0-04`, `MAC-S2-49`, `MAC-S2-89`, `MAC-S2-90`,
`MAC-S2-82`, `MAC-S2-83`, `MAC-S3-CAT-01`, `MAC-S3-TYPES-01`, `MAC-S3-SHARED-01`, `MAC-AC-01`,
`MAC-AC-05`. Это инвентаризация 21 карточки, `global_only`, независимое управление использованием
shared Embeddings/QRNG, «секреты/Telegram/сеть не тумблеры», заводское значение ON и подписи
состояний. Backend-оси под ними доказаны (§7), но acceptance этих строк — каталог/UI (по плану
M3/M4A), а не код резолвера. **Нужно решение координатора: оставить в M2 и расширять объём, или
перенести владельца строки.**

**D8. Сценарные проверки §10 (12).** `MAC-S10-02` (переключение A не меняет B), `MAC-S10-03`
(409 без потери записи, двойной клик), `MAC-S10-04` (stale-ответ при смене чата), `MAC-S10-05`
(рестарт/NOTIFY/кэш), `MAC-S10-06` (провайдер недоступен → requested ON, ready false),
`MAC-S10-07` (in-flight при CHAT OFF), `MAC-S10-08` (shared-инфраструктура и retrieval у B при OFF
у A), `MAC-S10-09` (старые сохранённые флаги не читаются как inherit), `MAC-S10-14` («Время» без
тумблера, timezone во всех consumers), `MAC-S10-15` (векторный поиск CHAT OFF), `MAC-S10-19`
(counters и ledger до/после), `MAC-S10-20` (отложенный результат не публикуется в отключённый чат).
Ни один из сценариев на кандидате не выполнен.

**D9. Сводная строка среза (1).** `MAC-M2-01` — «canonical GLOBAL default → CHAT override с
сохранением значений и межчатовой изоляцией, adapters каждого consumer, obsolete gates». Закрывается
только когда закрыты все строки M2, включая D1–D8 и §13.1–13.2.

### 13.4. Деплой (1 строка)

`MAC-S0-03` — «сохранённые значения, промпты и версии не перезаписываются при деплое; миграции
аддитивны, обратимы и имеют доказанный mapping». M2 не развёрнут, DDL в кандидате нет; нужен
деплой/аудит миграций, а не ссылка на отсутствие изменений.


## 14. Привязка строк карты

`candidate_commit` карты на время привязки среза — `97cfdef1`. `deployed_commit` не менялся
(он относится к релизу M5L и для M2 не применяется). Ниже — только строки, чей **полный** текст
acceptance покрыт доказательствами кандидата; всё остальное осталось `PENDING` с условием.

| Строка | Статус | Что именно доказано (артефакт/тест) |
|---|---|---|
| `MAC-S0-01` | VERIFIED | GLOBAL OFF + CHAT ON исполняется: `test_six_case_table_global_module` (строка 5), `test_six_case_table_per_chat_experience` (строка 5), `test_global_off_chat_on_worker_runs_and_selects` |
| `MAC-S0-08` | VERIFIED | Новый реестр не введён: резолвер построен на `chat_params` + существующем `module_registry` (`spec.master_param`, обязательное поле), новых хранилищ/таблиц в диффе нет; `test_one_resolver_no_second_gateway` |
| `MAC-S2-48` | VERIFIED | `overrides` и `gates` идут через одно ядро `resolve_capability`, хранение не дублируется: `test_one_resolver_no_second_gateway`, `test_gate_domain_rows_and_permsoc_alias`; baseline §2 фиксирует исходные два домена |
| `MAC-S2-91` | VERIFIED | Чатовый OFF локален, общий worker/индекс жив: `test_u4_chat_off_is_local_other_chat_learns` (чат `-200` учится при OFF у `-100`, курсор `-100` продвинут осознанно) |
| `MAC-S2-103` | VERIFIED | Единый резолвер на существующем слое + явный mapping `ModuleSpec.master_param → pg-ключ` (`resolve_module_capability` L1025–1050, `module_registry.py` L44); `test_one_resolver_no_second_gateway` |
| `MAC-S2-108` | VERIFIED | Read-пути не создают override: `test_stored_explicit_false_is_never_rewritten` (запрещённый `set_chat_params`, снимок равен, инвалидаций нет); GET-путь `web/api/gates.py` использует те же read-функции |
| `MAC-S2-116` | VERIFIED | Worker фильтрует eligible-чаты, у выключенного чата нет новых затратных задач: `test_global_off_chat_on_worker_runs_and_selects`, `test_u4_chat_off_is_local_other_chat_learns` (`detector_skipped`, обработка только `-200`) |
| `MAC-S2-AX-01` | VERIFIED | `desired = override != INHERIT ? override : global` и не смешивается с осями: код L925–980, шесть строк таблицы, `test_state_snapshot_exposes_separate_axes` |
| `MAC-S2-AX-02` | VERIFIED | `effective_runtime = desired AND NOT emergency_block AND ready is not False`; формула `global AND chat` запрещена (строка 5): `test_env_kill_switch_overrides_table`, `test_state_snapshot_exposes_separate_axes` |

Остальные строки среза `M2` (56 из 65: 48 инвентарных + 17 ручных, включая сводную
`MAC-M2-01`) остаются `PENDING`; точное условие для каждой группы — §13.

## 15. Результат review-gate (запуск из main checkout)

Команда (точная, из корня main checkout):

```
py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check ^
  --map plans/features/mod-acl-ux-01/requirements-map.json ^
  --stage review --slice M2 ^
  --candidate 97cfdef114609512b2d340fd619fb108d82593cd --repo .
```

Итог: `stage=review inventory=279 manual=99 scoped=65 errors=56`.

Все 56 ошибок одного вида — `mandatory not ['VERIFIED'] (got PENDING)`. **Ни одной** ошибки
привязки доказательств (`artifact_path`/`artifact_sha256`), ни `candidate mismatch`, ни ошибки
slice-graph нет: 9 привязанных строк прошли strict-проверку существования артефакта, его SHA-256,
Git-объекта кандидата и типа доказательства.

Это разделяет две разные проблемы, которые первый Reviewer увидел как одну:

1. **Размещение доказательств** — карты нет в изолированном checkout кандидата, поэтому gate там
   падает ещё до проверки строк. Устранено запуском из main checkout (§2, вариант 1).
2. **Реально недоказанные строки** — 56 `PENDING`: 15 живых наблюдений (§13.2), 3 строки
   production-отчёта и снимка реальных значений (§13.1), 1 деплойная (§13.4), 37 строк групп
   D1–D9 (§13.3), включая сводную `MAC-M2-01`.

Итог по срезу: доказанная часть M2 зафиксирована и не потеряна, но **полного VERIFIED у M2 нет** —
ровно потому, что перечисленные 56 строк не имеют доказательств на этом кандидате.


