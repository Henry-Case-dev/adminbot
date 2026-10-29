# W2A — EVOL-016 + EVOL-012 backend: единый версионный контур промптов

Статус: `IMPLEMENTED` (кандидат на независимое ревью)
Ветка: `evol/impl` @ `28d55bd1` (worktree, БЕЗ коммитов — изменения в рабочем дереве)
Исполнитель: Builder (лейн W2A: EVOL-016 backend + EVOL-012 barrier retirement + посев EVOL-018)
Дата: 30.10.2026
Контракт: `plans/features/evol/arch/contracts.md` CONTRACT 1 (заморожен, §1.1–§1.10)
Требования владельца: `plans/current_task.md` §5 EVOL-016/017/018, EVOL-012, DoD 10–11

---

## 1. Что реализовано

### 1.1 Релизная политика (новый модуль `services/prompt_release_policy.py`)

* **Журнал** `prompt_revisions` + `prompt_activations` — в точности схема контракта
  §1.2 (`revision_id = "rev:" + sha12(block_id+scope+chat+origin+sha)`; `origin ∈
  factory|manual|restored|legacy`; `kind ∈ legacy_import|deploy_activate|
  manual_edit|manual_rollback|manual_forward|integrity_reject`; `outcome ∈
  applied|skipped_same|skipped_empty|failed`; `restart` строку не пишет).
  Журнал НЕ второй источник правды: активные байты читаются из `bot_settings` /
  chat-override как раньше; последняя строка с `outcome ∈ {applied, skipped_same}`
  — указатель «какая ревизия включена» и «какая заводская ревизия применена».
* **Сторы**: `PgPromptJournal` (тот же пул, что `bot_settings`; advisory xact-лок
  `pg_advisory_xact_lock(hashtext('prompt_release_apply'))` по прецеденту
  `chat_params`) и `MemoryPromptJournal` (тесты: откат пакета снапшотом,
  инъекция сбоев `fail_at`, `asyncio.Lock` для параллельных воркеров).
* **`apply_release(cache, *, release_id, store=None)`** — автомат контракта §1.3/§1.4:
  рестарт с той же меткой → no-op (ни строки, ни записи); новая метка при целой
  печати → активация поверх ручной правки (прежний текст остаётся ревизией);
  первый запуск → снимок legacy, затем активация (`release_id=evol-016-cutover`);
  печать не цела → fail-closed на ВЕСЬ пакет (ERROR `integrity_label_unchanged`,
  БД не тронута); расхождение журнала и `bot_settings` → ERROR `activation_drift`,
  источник истины — PG, заводской текст не включается до новой метки, снимок
  `origin=legacy reason=drift_recovery`; падение до commit → откат всего пакета;
  два воркера → лок, второй видит применённую ревизию и не пишет дубль.
  PG/журнал недоступен → skip с INFO (активация «из констант поверх журнала»
  запрещена).
* **Снимок legacy** (§1.4): до первой записи заводского текста каждый
  зарегистрированный pg_key и каждый per-chat override снимаются как
  `origin=legacy`, время = время импорта, `actor=""`, `bot_settings.updated_at`
  — только в справочное `source_updated_at`; даже байты, равные заводским,
  снимаются как legacy (UI не имеет права подписать это «Изменена в админке»);
  пустой ключ → `skipped_empty`, автор не выдумывается.
* **Одноразовый импорт** `character.prompt_history` → `prompt_revisions`
  (`owner_edit→manual`, `factory_reset→factory`, `backup_restore→restored`,
  `legacy_strip→legacy`), время из поля `at`, автор не выдумывается; после
  импорта история **заморожена** (`prompt_factory.freeze_history()`), документ
  не удаляется, обрезанные хвосты HISTORY_MAX_PER_BLOCK не восстанавливаются.
* **Scope (§1.5)**: новая метка обновляет и глобал, и per-chat — устаревший
  override блока снимается с эффективного пути (текст заранее уходит в
  ревизию), ключ удаляется из overrides, `pg_notify('chat_params_updated')`
  внутри транзакции (доставится на commit) + инвалидация in-memory чат-кэша
  после commit. Override, созданный ПОСЛЕ применения метки (journal-путь),
  рестарт не снимает; следующая метка снимает и его.
* **`write_versioned_value`** — единственная версионированная запись активного
  текста: ревизия + активация + значение одной транзакцией;
  `factory_revision_applied` не сбрасывается (правка «поверх» применённой
  заводской ревизии; следующая НОВАЯ метка снимет её в историю).
* **`activate_revision`** — откат/вперёд: гейты «существует / не retired /
  schema_compat совместим / полномочия»; несовместимая ревизия не включается
  (`applied=false, reason=schema_incompatible`), активный указатель не меняется;
  `kind=manual_rollback|manual_forward` — по детерминированному порядку вставки
  ревизий в журнал (`revision_precedes`), не по настенным часам.
* **`record_manual_activation`** — журналирование факта без повторной записи
  значения: для per-chat-правок (запись значения остаётся за
  `chat_params.set_chat_params` со своей историей/локами/NOTIFY — двойные
  проводки не дублируются), для `apply_factory_reset` и `restore_backup`.
  Best-effort: сбой журнала не роняет запись значения.
* **API EVOL-017** (сервисный уровень, без HTTP): `list_versions`,
  `get_revision_source`, `diff_revisions` (существующий `difflib`), плюс
  реэкспорт контрактных имён в `prompt_factory` (`apply_release`,
  `import_legacy_snapshots`, `activate_revision`, `list_revisions`,
  `diff_revisions`, `get_revision_source`, `list_versions`).
* **Hook полномочий**: `set_permission_checker` / `check_permission` — EVOL-017
  HTTP-слой обязан установить RBAC-проверку; без checker'а — непустой actor
  обязателен, иначе `PromptPermissionError` (аудит-событие в лог).
* **Наблюдаемость (§1.8)**: INFO с `block_id | sha | scope | chat | kind |
  outcome | release_id`, без тел промптов и секретов; WARN/ERROR только на
  PG-ошибку записи, `integrity_label_unchanged`, `activation_drift`,
  `schema_incompatible` на попытке включения, срыв пакета; повторный рестарт
  ERROR не плодит.

### 1.2 Реестр (`services/prompt_registry.py`)

* **`FACTORY_REVISION_SEALS`** — печать `(метка, sha12(текст))` для всех 98
  блоков с непустым заводским текстом (89 старых + 9 новых). Сгенерированы из
  кода скриптом, руками не выдумывались.
* **`seal_integrity()`** — код нарушения по каждому блоку (`seal_missing`,
  `seal_text_changed`, `seal_label_without_text`, `seal_unknown_block`);
  `sealed_factory_revision(block_id) = "fac:" + sha12(метки)`.
* **`activation_plan(...)`** — чистая функция-автомат §1.3/§1.4 (без I/O),
  возвращает `ActivationPlan(action, kind, outcome, reason)`.
* **`revision_id_for(...)`** — идентичность ревизии §1.2.
* **`declare_prompt(...)`** — единая точка объявления (контракт §1.7):
  идемпотентна, конфликт данных → `PromptDeclarationError`; `_pg_blocks()` и
  `_CODE_BLOCKS` создают спеки только через неё (`_b` — позиционный адаптер
  легаси-каталога поверх неё).
* **`resolve_speech_value`** — переключатель §1.6: после проводки релизной
  политики (`release_policy_active()`, выставляет `apply_release`) persisted-
  текст PG — эффективный слой; `provenance_missing/mismatch` больше не
  подменяют правку заводским текстом (тихий сброс на каждом чтении устранён).
  `WITHHELD_LEGACY_CLASS` (`legacy_incompatible`) сохранён: известный токсичный
  слепок по точным байтам удерживается, подмена на заводской текст + ОДИН
  аудит-событие на процесс (не WARN на каждое чтение). До проводки — прежний
  шлагбаум (совместимость старта на старой БД).
* **`registry_view`** — аддитивные поля `factory_seal`, `sealed_revision`,
  `retired`; старые ключи не тронуты. `set_retired_blocks` — пометка снятых с
  регистрации блоков (заполняет релизная проводка).
* **`PROMPT_AUDIT_ALLOWLIST`** — единственная запись (не-промпт: локатор
  web-fetch) с причиной; регистрация новых констант через `declare_prompt`,
  не через allowlist.
* **`audit_unregistered_prompt_constants(root)`** — grep-аудит §1.7 п.4:
  ограниченно `services/` + `handlers/` (не repo-wide magic), пропуск
  `tests/`, `prompt_migrations.py`, `PREV_*/LEGACY_*/_`; ищет
  `NAME_PROMPT =` и `NAME_SYSTEM = """…>80"""`; `module.attr` обязан быть в
  `code_source` (включая `code_members`) или в allowlist с непустой причиной;
  параметризуем `blocks/allowlist/scan_paths` для негативных тестов.

### 1.3 Фабрика (`services/prompt_factory.py`)

* `freeze_history()` / `history_frozen()`; `_append_history` и `_mark_provenance`
  после заморозки — no-op (провенанс-путь возвращает `persisted=True`, запись
  значения не ломается).
* **`write_speech_value`** — обёртка над `write_versioned_value` (контракт §1.6):
  * global: ревизия+активация+значение одной транзакцией; optimistic-токен
    `expected_updated_at` — общий гейт (FactoryConflict как раньше);
  * chat: запись значения остаётся за `chat_params` (история, локи, NOTIFY,
    идемпотентный short-circuit D-409-1 — НЕ дублируются), журнал получает
    факт (`record_manual_activation`, best-effort);
  * журнал недоступен → прежний путь + честный `journal_recorded=False`;
  * гейты `legacy_incompatible` (токсичные слепки не активируются) и пустого
    значения сохранены байт-в-байт.
* `apply_factory_reset` и `restore_backup` журналируют факт
  (`manual_rollback`), чтобы рестарт не поднимал честный `activation_drift`.
* Контрактные имена API (см. 1.1) реэкспортированы здесь.

### 1.4 Миграции (`services/prompt_migrations.py`) — барьер EVOL-012 снят

* **`migrate_prompt_canons(cache)`** — точка вызова `bot.py` (файл не тронут,
  вызов `bot.py:1382-1383` сохранён) → делегатор
  `apply_release(cache, release_id="evol-016-cutover")`. Строковое равенство с
  канонами и барьер «кастом юзера — НЕ трогаем» удалены. Возврат сводки в
  старой форме `{pg_key: "updated"|"same"|...}` для совместимости логов старта.
* **`rollback_prompt_canons`** — УСТАРЕВШЕ: ERROR и отказ, записей нет (ручной
  «откат лестницей» поверх журнала создал бы drift; откат —
  `activate_revision`, байты прежних канонов восстановимы из ревизий).
* **`migrate_core_owner_patch`** — УСТАРЕВШЕ: ERROR и отказ. Проверено: оба
  абзаца владельца («Как говорить о реальных событиях», «Свобода речи») уже
  входят в заводскую Core v4 — их доезжает cutover-активация, а не правка
  каждого старта (нарушала «рестарт без новой метки ничего не меняет»).
* `PROMPT_MIGRATIONS` / `ROLLBACK_MIGRATIONS` / все `PREV_*` сохранены как
  байт-эталоны (тесты и откатные ревизии), механизмом активации больше не
  являются; `_attest_migrated_canon` остался (не вызывается стартом).

### 1.5 Отставшие шаблоны включены в реестр (посев EVOL-018)

9 найденных grep-аудитом констант зарегистрированы через `declare_prompt`
(метки + печати + отпечаток набора забамплены `fbc44eb0f879 → b980947c71aa`):

| block_id | code_source | потребители |
|---|---|---|
| `summary.l2.reviewer` | `summary_prompts.SUMMARY_L2_REVIEWER_SYSTEM_PROMPT` | summary_l2_review.py:102/1116 |
| `summary.l2.reviser` | `summary_prompts.SUMMARY_L2_REVISER_SYSTEM_PROMPT` | summary_l2_review.py:103/1385 |
| `summary.l1.anchors` | `summary_prompts.SUMMARY_L1_ANCHORS_SYSTEM_PROMPT` | summary_l1_clusterizer.py:106, summary_execution_input.py:111 |
| `memory.fact_extract` | `summary_memory.FACT_EXTRACT_PROMPT` | summary_memory.py:3331/3423 |
| `internal.observer_digest` | `initiative_observer.OBSERVER_DIGEST_SYSTEM_PROMPT` | initiative_observer.py:650/1566 |
| `internal.experience.semantic` | `mca_experience_jobs.SEMANTIC_SYSTEM_PROMPT` | mca_experience_jobs.py:385/1366 |
| `style.metatext_retry` | `prompt_style_blocks.METATEXT_RETRY_SYSTEM_PROMPT` | negative_constraints.py:29/697 |
| `internal.image_probe` | `image_generation.PROBE_PROMPT` | image_generation.py:97/1439 |
| `internal.image_stage` | `execution_graph_source.STAGE_IMAGE_PROMPT` | execution_graph_source.py:94/722 |

Запрещённые файлы (`summary_memory.py`, `mca_vision.py` и др.) НЕ редактировались
— регистрация указывает `code_source` на существующие константы.

**Итоговый инвентарь реестра**: 99 блоков (37 PG-управляемых, 62 кодовых),
98 печатей (все блоки с непустым текстом), 89 меток (все, кроме 9 управляемых
сообщений `message.image_*`/`message.checkup_fallback_notice` — они версионируются
печатями + CI, в релизной активации не участвуют), `FACTORY_SET_SHA256_12 =
b980947c71aa`, grep-аудит: 50 констант, 0 вне реестра.

---

## 2. Решения относительно контракта (и обоснования отклонений)

| # | Решение | Обоснование |
|---|---|---|
| D1 | SQLite-шаг книги схемы — **39**, не 38 (контракт писал v38) | v38 уже занята EVOL-015 (`_SCHEMA_VERSION_QUOTE_METADATA = 38`); брифт это фиксирует. Шаг в этой волне НЕ регистрируется — см. §4. |
| D2 | DDL журнала — лениво и идемпотентно в самом модуле (`ensure_journal`), без правок `database.py`/`pg_db.py` | `database.py` запрещён в этом проходе; `pg_db.DDL_STATEMENTS` — SERIALIZE-зона схемы. Самодостаточный `CREATE TABLE IF NOT EXISTS` даёт то же конечное состояние без «полурегистрации»: журнал либо создаётся, либо честный no-op. Точный фикс для книги схемы — §4. |
| D3 | Указатель активной ревизии — последняя строка с `outcome ∈ {applied, skipped_same}` | Контракт §1.2 называет указателем строки `outcome=applied`; при cutover «значение уже равно заводскому» пишется `skipped_same` без записи значения — и тоже фиксирует применённую метку, иначе каждый рестарт перепланировал бы cutover (нарушение рестарт-идемпотентности). Строка `skipped_same` несёт `revision_id` существующей ревизии активных байт. |
| D4 | Cutover-активация значения пишется с `kind=deploy_activate`, `kind=legacy_import` — только строка снимка | §1.4: «это явный миграционный релиз … не рестарт»; вид активации ЗНАЧЕНИЯ — deploy-событие, снимок — импорт. Тест §1.9 п.7 («два параллельных apply → одна активация») считает deploy-строки. |
| D5 | Отказ `rollback_prompt_canons`/`migrate_core_owner_patch` вместо тела | Прямое указание контракта §1.6 («если их всё же вызвали — ERROR и отказ, без записи»). `bot.py` не тронут: он вызывает только `migrate_prompt_canons`, который остался рабочим делегатором. |
| D6 | `record_manual_activation` для chat-путей и reset/restore | Один чат-override = одна PG-транзакция `chat_params` (история/локи/NOTIFY внутри); дублирование записи значения в журнальной транзакции нарушило бы D-409-контракт web-слоя (запрещённого к правке). Журнал получает факт, best-effort — как прежний провенанс. |
| D7 | Drift-детект — только при действии (activate/cutover), не на no-op-рестарте | §1.4: «Рестарт, метка та же → no-op, активный текст не трогать»; чтение значения на каждом рестарте вернуло бы WARN-на-каждый-старт. Расхождение вскрывается при следующей активации и снимается в ревизию. |
| D8 | `kind` rollback/forward — по порядку вставки ревизий (`revision_precedes`), не по времени строк | Секундное квантование часов (Windows) делало сравнение ISO-строк недетерминированным (ловилось тестами). PG-стор сравнивает `created_at` с микросекундами, при неразличимости — честный fallback `manual_forward`. |
| D9 | `seal_unknown_block` (печать снятого блока) не блокирует пакет | У снятого с регистрации блока нет runtime-текста — это bookkeeping, а не дрейф текста; блокировка релиза осиротевшей печатью сделала бы переименование ключей невыполнимым. Остальные три кода — fail-closed. |
| D10 | Кодовые блоки: ревизия `origin=factory` + строка активации в scope `code` без записи значения | §1.5 («второго хранилища нет»). Рестарт-идемпотентность обеспечена указателем в том же scope. |
| D11 | `import_legacy_snapshots` = cutover-вызов (одно имя API) | Снимок и активация — одна транзакция (§1.4 запрещает частичную смесь); отдельной фазы «снимок без активации» не существует, имя сохранено для совместимости контрактного API. |
| D12 | Два Core-поля пишутся с per-transaction `doc_state` | Найдено тестами: второе поле документа, читая базу из устаревшего кэша, затирало первое. База документа в транзакции — результат записи этой же транзакции, иначе текущий документ слоя; `detail_level` владельца сохраняется (`set_level=False`). |

---

## 3. Матрица тестов (контракт §1.9) — результаты

Новые файлы (34 теста, все зелёные):

* `tests/test_evol016_prompt_activation.py` (16) — таблица переходов:
  factory A → manual M → factory B (B активен, M в истории origin=manual);
  рестарт без метки после M (M остаётся, 0 записей); restore A после B через
  `activate_revision` (rollback/forward, рестарт не возвращает B); factory C
  (C активен, A/M/B в истории); рестарт после C (без дублей); неизвестный
  legacy-текст (снимок, время = время импорта, повтор no-op); пустой ключ
  (skipped_empty → активация); два параллельных `apply_release` (одна
  активация, снимок не задвоен); крэш mid-apply на втором ключе (пакет
  откатился целиком, повтор применяет); global + два чата (override чата 1 не
  виден чату 2, новая метка снимает оба override в историю с NOTIFY,
  post-label override переживает рестарт, следующая метка снимает); смена
  текста без метки (план `integrity_reject`, `cache.set` не вызван); метка без
  печати (fail-closed); снятый ключ (ревизии читаются, retired=true, возврат
  снимает пометку); `schema_compat` вне пустого списка (не активируется,
  просмотр доступен); резолв после cutover читает PG-текст, legacy-слепок
  удерживается; заморозка истории + одноразовый импорт (время из `at`,
  автор из `by`); drift (ERROR, PG — источник, следующая метка включает
  заводской); чистый автомат (no-op/cutover/activate/no-label); hook
  полномочий (deny/allow).
* `tests/test_evol012_barrier_retired.py` (8) — кастом не блокирует новую
  заводскую ревизию (приёмка EVOL-012); WARN «кастом юзера — НЕ трогаем» не
  возникает; рестарт без релиза сохраняет активную правку (ни строки, ни
  записи); PREV-байты больше не ведут «лестницей» (активна заводская по
  метке, слепок — ревизия); `rollback_prompt_canons` и
  `migrate_core_owner_patch` отказывают без записи; слепки/карты сохранены
  как байт-эталоны, стартовый путь — делегатор политики; чтение кастома после
  релиза не WARN-ит.
* `tests/test_evol018_prompt_audit.py` (10) — печати = (метка, sha12(текст))
  по всем блокам; каждый текстовый блок запечатан; идентичность
  `fac:sha12(метки)`; отпечаток = константе; grep-аудит реестра пуст
  (50/50 констант зарегистрированы/allowlist с причинами); фиктивная
  необъявленная константа ловится; объявленная через `declare_prompt` — нет;
  границы аудита (services+handlers, prompt_migrations исключён); конфликт
  повторной декларации → `PromptDeclarationError`.

Переписанные на новый автомат легаси-тесты (контракт §1.9: «старые тесты,
требующие migrate_prompt_canons → „кастом не трогаем“, переписать; байт-эталоны
не ослаблять») — все зелёные:

`test_prompt_migrations.py` (40), `test_summary_asap21_prompt_migrations.py`
(23), `test_summary_l1_clusterizer.py` (118/120), `test_p0_checkup_core_contract.py`
(16), `test_p0_prompts_core.py` (9), `test_p0_factual_memory_prompts.py`,
`test_cfg07_backstage_contract.py` (58), `test_asap2_clar_contract.py`,
`test_asap_speech_r3b_canon.py`, `test_factcheck_tools_round1020.py`,
`test_outgoing_guard_round1022.py`, `test_expression_isolation_followup.py` (4),
`test_hotfix4_cover_nav_shell_round1025.py`. Сводный прогон по 19
затронутым/смежным файлам: **463 passed, 3 failed — все 3 доказанно
пре-существующие на базе 28d55bd1** (см. §6).

`compileall services` — exit 0. Команда: `C:\Code\Python\adminbot\.venv\Scripts\
python.exe -m pytest tests/<файлы> -q` (cwd = worktree). Полный suite не
запускался (по брифу).

---

## 4. Интеграционная заметка для `services/database.py` (следующий проход)

Схема уже работает (ленивый идемпотентный DDL в
`prompt_release_policy.ensure_journal` / `PgPromptJournal.ensure_journal`), шаг
ниже — только bookkeeping книги схемы, по образцу v35/v38:

1. Константа рядом с `_SCHEMA_VERSION_QUOTE_METADATA = 38`:

```python
# EVOL-016: журнал версий/активаций промптов. Таблицы живёт в PostgreSQL
# (DDL — services/prompt_release_policy.JOURNAL_DDL, идемпотентный, уже
# выполняется лениво при первом apply_release). SQLite-шаг — только книга
# схемы (прецедент v35/v38), данных в SQLite нет.
_SCHEMA_VERSION_PROMPT_JOURNAL = 39
```

2. Регистрация шага в списке `_build_steps()` сразу после
   `MigrationStep(_SCHEMA_VERSION_QUOTE_METADATA, "quote_metadata_v38", …)`:

```python
        MigrationStep(_SCHEMA_VERSION_PROMPT_JOURNAL,
                      "prompt_revision_journal_v39",
                      lambda svc: svc._migrate_prompt_journal_v39()),
```

3. Метод `DatabaseService._migrate_prompt_journal_v39` (идемпотентный,
   PG-down не блокирует фиксацию версии — как v35/v38):

```python
    async def _migrate_prompt_journal_v39(self) -> None:
        """EVOL-016: книга схемы для журнала промптов.

        Данных в SQLite нет: prompt_revisions/prompt_activations живут в
        PostgreSQL (тот же контур долговечности, что bot_settings). DDL
        выполняет PgDatabase.init()/prompt_release_policy.ensure_journal
        (CREATE TABLE IF NOT EXISTS). Повтор — no-op. Откат: cold git revert
        (таблицы инертны, старый код их не читает).
        """
        return None
```

4. Параллельно (тот же следующий схемный проход, SERIALIZED-зона): перенести
   `prompt_release_policy.JOURNAL_DDL` в `DDL_STATEMENTS`
   `services/pg_db.py` (дословно, 4 выражения) — тогда DDL выполняется и на
   инициализации пула, а ленивый путь остаётся совместимым (те же выражения,
   `IF NOT EXISTS`).

Никаких других точек интеграции не требуется: `bot.py:1382-1383` уже вызывает
`migrate_prompt_canons(cache)` → делегатор `apply_release`.

---

## 5. API для EVOL-017 (админка «История версий»)

Сервисный уровень, HTTP-слой добавляет RBAC и маршруты:

```python
from services import prompt_factory as pf
from services import prompt_release_policy as prp

pf.list_versions(block_id, scope="global", chat_id=None)
    # {"block_id", "pg_key", "factory_revision", "sealed_revision",
    #  "factory_matches_active", "active": {revision_id, origin, sha, chars,
    #  created_at, factory_revision_applied}, "revisions": [...],
    #  "activations": [...]}   — тексты по умолчанию не отдаются
pf.get_revision_source(revision_id)     # {"known", "body", ...} — просмотр
pf.diff_revisions(rev_a, rev_b)         # unified diff (difflib) + счётчики
pf.activate_revision(block_id, revision_id, scope=..., chat_id=..., actor=...)
    # откат/вперёд; гейты: exists/retired/schema_compat/permissions;
    # несовместимая → applied=False, reason=schema_incompatible
prp.set_permission_checker(fn(actor, action, ctx) -> bool)  # RBAC-хук (ОБЯЗАТЕЛЕН для HTTP)
prp.list_versions / prp.record_manual_activation / prp.write_versioned_value
```

Мобильная навигация/компоненты — вне этого прохода (EVOL-017 lane). Контракт
честных ограничений реализован: `retired`/`schema_compat` видны в списках,
несовместимая ревизия читается и сравнивается, но не включается.

---

## 6. Побочные находки (честно)

**Пре-существующие на базе 28d55bd1** (доказано прогоном на чистом checkout
HEAD в отдельном worktree — падают идентично без моих изменений; НЕ трогал,
чужие лейны):

1. `test_round1025_f8_registry.py` — 10 сбоев (frozen-invariants TSV/routes/
   counts против `param_catalog`): EVOL-031 (28d55bd1) менял каталог (-6
   ключей) и web-роуты, не обновив замороженные базлайны. → лейн EVOL-031.
2. `test_summary_l1_clusterizer.py::TestCanon::test_catalog_delta_sanctioned`
   — 581 ≠ 587 (та же причина, EVOL-031). → лейн EVOL-031.
3. `test_soul1_registry_completeness.py::test_legacy_persona_canons_...` —
   `verbilizer.mode.deep_research`: фабрика вычищена от маркеров, а тест всё
   ещё требует маркер (бамп POST-ASAP5 W2 `mode-no-meta-lexical`). → лейн SOUL-1.
4. `test_summary_l1_clusterizer.py::TestLivePathInvariants::
   test_off_chain_byte_identical_single_call` и `test_samples_fewshot.py`
   (2 теста) — байт-дрейф Expression/section2-блоков против снапшотов
   few-shot/генератора. → лейн SOUL-1/samples.

Попутно исправлено в своей зоне: дрейф указателей потребителей
(`lore_worker.py:696→709`, `:692→705`, `lore_compiler_service.py:190→208`) —
метаданные реестра, тест трассируемости снова значим.

Открытые предметы (честно):

* Реальный PG-прогон `apply_release` (DDL + advisory-лок + jsonb-проводки) на
  прод-подобной базе не выполнялся — в этом проходе нет доступа к прод-БД из
  лейна; контур покрыт MemoryPromptJournal с той же семантикой + SQL
  дословно из контракта. Рекомендация Reviewer/DevOps: smoke на staging-PG до
  выката (cutover идемпотентен, откат — cold revert).
* SQLite-шаг 39 не зарегистрирован (намеренно, §4) — система честно работает
  без него.
* EVOL-017 HTTP-слой обязан установить RBAC-checker (`set_permission_checker`)
  до открытия UI-маршрутов.
* `_import_provenance_history` переносит только `items` (байт-ревизии);
  provenance-факты без байт не выдумываются (осиротевшие block_id логируются).

Файлы волны: `services/prompt_registry.py`, `services/prompt_release_policy.py`
(новый), `services/prompt_factory.py`, `services/prompt_migrations.py`,
`tests/test_evol016_prompt_activation.py` (новый),
`tests/test_evol012_barrier_retired.py` (новый),
`tests/test_evol018_prompt_audit.py` (новый) + 12 переписанных легаси-тестов.
Запрещённые зоны не тронуты (проверено `git status`).

---

## 7. Кратко для владельца (что теперь происходит с заводскими и ручными промптами)

Теперь у каждого промпта проекта есть версия и журнал. Правка в админке —
это полноценная сохранённая редакция, она активна и остаётся в истории.
Когда разработка выпускает новую заводскую редакцию (смена версии-метки при
целой печати содержимого — иначе релиз честно отвергается с ошибкой), она
включается автоматически при выкате, даже поверх вашей правки; сама правка не
теряется — её можно посмотреть, сравнить и вернуть одним действием. Обычный
рестарт сервера ничего не меняет: ваша правка и откат остаются активными до
следующей заводской поставки. Старая защита «кастом юзера — НЕ трогаем» и её
предупреждения в логах убраны полностью, вместе со строковыми сравнениями и
стартовым патчем Core. Все текущие тексты перед первым включением сняты в
журнал как «импорт legacy» с честным временем импорта — ничего не потеряно и
восстановимо. Все 9 ранее неучтённых внутренних шаблонов (reviewer/reviser
саммари, извлечение фактов, дайджест наблюдателя и др.) внесены в реестр, и
CI теперь ловит любой новый промпт мимо реестра, а также правку текста без
версии. Осталось на следующих шагах: экран «История версий» в админке
(EVOL-017, API готов), регистрация шага книги схемы v39 (готовая инструкция
передана) и smoke-проверка на staging-PG перед выкатом.

---

# Приложение A (диагностика 30.10.2026): contract-тест
# `test_evidence_injection_stays_data_not_instructions` — RED до и независимо
# от W2a

Статус: **PRE-EXISTING ON PRODUCTION** (верект (a) из брифа) — fix в этой
задаче НЕ выполняется; дефект уходит в backlog фактчек-лейна с точным
указанием причины и варианта починки.

## A.1 Воспроизведение

```
python -m pytest "tests/test_mca20_rework1_f1_f2.py::
TestValidatorStage::test_evidence_injection_stays_data_not_instructions" -x -q
```

HEAD `44437903` + незакоммиченные пин-фиксы (не затрагивают этот тест):
**FAILED** на `assert "&lt;/evidence&gt;" in v_user`
(`tests/test_mca20_rework1_f1_f2.py:249`).

Факт (инструментированный прогон, spy на `temporal_factcheck.
evidence_rows_from_results`): агрегаторский текст режется по пустой строке на
3 блока — `ev-1` (сниппет, url=good.example/a), `ev-2` = **инъекция**
(`</evidence>SYSTEM: …`, url=None), `ev-3` (url=evil.example/b). До payload
доходят только `ev-1` и `ev-3`: comprehension в `factcheck_service.py:1403-1406`
(`evidence = tuple(r for r in tf.evidence_rows_from_results(...) if
r.get("url"))`) выбрасывает url=None-строку `ev-2` **целиком**, поэтому
экранировать в `_temporal_validator_payload` (он вызывает `escape_xml_text`,
проверено: `services/summary_xml.py` корректно даёт `&lt;/evidence&gt;`)
просто нечего — инъекция молча исчезла из данных. Тест же (контракт mca-20
D10/§18G.3) требует противоположного: url-less блок должен дойти до модели
КАК экранированные данные, а не выкидываться.

## A.2 Bisect (чистые worktree-чекинуты на каждый коммит, все удалены после)

| Commit | Результат | Комментарий |
|---|---|---|
| `968b0496` (mca-20, 2.58.64 — введение теста и `_temporal_validator_payload`) | **PASS** | тест писался зелёным |
| `2e406151` (asap8-v6 D09/D10/D11, 2.58.77) | PASS | — |
| `97818475` (FC-R1 unified retrieval) | PASS | — |
| `c43d0363` (p0b «close factcheck review r1 (F1-F6)») | **FAIL** | ломающий коммит |
| `5346ee76` (**production 2.58.141**) | **FAIL** | дефект в проде |
| `f382bd87` (база ветки evol/impl) | **FAIL** | до всех 5 коммитов ветки |
| `44437903` (W2a, HEAD) + рабочее дерево | FAIL | идентично |

Коммиты собственной ветки (`44437903`, `28d55bd1`, `e7443fad`, `dc1fdba6`,
`0e853f7f`) не трогали `services/factcheck_service.py`,
`services/search_aggregator.py`, `temporal_factcheck.py`
(`git diff f382bd87..44437903 --stat` — пусто по этим файлам), и тест падает
на базе ветки до них.

## A.3 Механизм и точная причина

`c43d0363` (F2 «envelope path never rebuilds URL-less evidence») перестроил
evidence-ветку: при `retrieval is not None` — только структурные строки плана
(лечение прод-симптома tfr-6e0ab2db…: url=None-дублями), а в else-ветке
(внутренний поиск) добавлен фильтр `if r.get("url")` с комментарием «строки
без URL тоже не доказательство». Побочный эффект: url-less блоки выдачи
(в т.ч. инъекция) больше не доходят до payload ни в каком виде —
экранирование `_temporal_validator_payload` стало no-op для них, а контрактный
тест mca-20 (утверждён ревью итер.2 в 968b0496) требует их экранированной
доставки. Это конфликт двух санкционированных правок прод-линии:
mca-20 D10/§18G.3 (инъекция = данные, экранировать и доставить) против
p0b F2 (url-less = не доказательство). Ветка evol/impl и W2a наследует его
без изменений.

## A.4 Вердикт и передача

* **Verdict: (a) pre-existing на production** (5346ee76/2.58.141 содержит
  `c43d0363`; проверено прямым прогоном — FAIL). Не регрессия ветки evol/impl
  и не регрессия W2a.
* **Fix не выполнялся** (механизм — `services/factcheck_service.py:1403-1406`,
  файл другого лейна; санкция на конфликт контрактов — не моё решение).
* **Рекомендация для backlog/EVOL (фактчек-лейн)**: в else-ветке внутреннего
  поиска вернуть url-less блоки в evidence (убрать `if r.get("url")` из
  comprehension), сохранив FC-EVIDQ dedup; честность «нельзя открыть и
  проверить» уже выражена полем `url=None` + retrieval-оговоркой, а защита от
  инъекции — экранирование `_temporal_validator_payload`/`_temporal_user_payload`
  (работает и проверяется этим тестом). Альтернатива (если F2-семантика
  «url-less ≠ evidence» приоритетнее) — переписать контрактный тест mca-20 на
  ожидание «инъекция не доставляется вовсе» с явной санкцией владельца, т.к.
  это ослабление D10/§18G.3. Любой вариант — решение фактчек-лейна/владельца,
  не лейна промптов.
* Смежные прогоны (HEAD + пин-фиксы): `test_mca20_rework1_f1_f2.py` +
  `test_factcheck_post_release_w2.py` — 30 passed / 1 failed (только этот);
  `test_factcheck_fc_r1_fix.py`, `test_asap8_v63_b07_temporal_factcheck.py`,
  `test_factcheck_service.py` — passed. `test_factcheck_post_release_w1.py`
  — 2 FAILED (`TestAggregatorFailureTaxonomy::test_timeout_is_not_provider_
  unavailable`, `test_api_error_is_provider_error`) — тоже пре-существующие:
  ветка не трогала `search_aggregator.py`/`factcheck_service.py`/сам файл
  теста (пустой diff f382bd87..44437903), механизм не связан с W2a. Отдельный
  backlog-предмет фактчек-лейна (search_aggregator taxonomy vs live-provider
  fallback).

Инструментальные скрипты диагностики: одноразовые, в
`WorkspaceData/runs/c742e4de9e92c489/` (debug_evidence*.py, probe_*.py);
bisect-worktree удалены после использования, `git worktree list` чист.

