# W4 — EVOL-006: качество фактов памяти (класс, долговечность, атрибуция)

Лейн: Builder W4, worktree `evol/impl` @ `a02aca0c` (без коммитов).
Источники: `plans/current_task.md` EVOL-006 (L97–105),
`plans/features/evol/audit/base-revalidation.md` §«EVOL-006/007 — facts pipeline»,
`plans/features/evol/audit/context-ui-audit.md` §2, `w3-memory-backend.md`,
`docs/prompt-versioning-contract.md`.

## 1. Где реально рождаются «мусорные факты» (проверено по коду)

| Путь | Промпт | Куда пишет | В виджете «Новые факты» |
|---|---|---|---|
| `_memorize_facts_inner` (live-хуки) | `FACT_EXTRACT_PROMPT` (`services/summary_memory.py:143-157` до правки) | `graph_facts` (+vec, +провенанс) | **да** (виджет читает `graph_facts`) |
| `_extract_and_save_graph` (крон сжатия) | `EXTRACT_PROMPT` (`services/summary_prompts.py:1076`) | только `nodes`/`edges` (`_write_graph_triplets`, `graph_facts` не создаёт — F3/T-1774) | нет |

Вывод: долговременный пул (и виджет) формирует **memorize-путь**, его промпт и
разбор — предмет этого лейна. Кроновый `EXTRACT_PROMPT` в UI-пул фактов не
пишет, поэтому его текст не менялся (иначе пришлось бы двигать второй канон и
байт-эталоны `tests/test_summary_prompts.py` без влияния на EVOL-006).

Уточнение к брифу: «FACTORY TEXT» экстрактора лежит в
`services/summary_memory.py` (`PREV_FACT_EXTRACT_PROMPT` + аддитивные абзацы), а
не в `services/summary_prompts.py`; реестровый блок —
`memory.fact_extract` (`code_source="services.summary_memory.FACT_EXTRACT_PROMPT"`).

### Что показал разбор до правки

* Промпт различал только «факт/триплет»; измерений **долговечности** и
  **атрибуции** не было вообще (ни `kind`, ни `subject_type`).
* Разбор (`_validate_fact`) принимал любую тройку `subject/predicate/object`:
  просьба «нарисуй кота», пересказ новости и описание персонажа запроса
  записывались одинаково — как личный факт (`target_user` спрашивающего).
* Провенанс-энтузиазм `services/provenance.py` (`world_knowledge`) включается
  флагом и пишется **после** записи факта: он описывает происхождение, но не
  мешает записи занять место в личном пуле.
* Прозаический fallback-парсер мог «дотянуть» тройку из текста валидного
  JSON-ответа, где элементы не прошли контракт (после введения класса это стало
  бы каналом мусора).

## 2. Контракт промпта: до / после

**До** (984 символа): роль архивариуса, «извлекай объективную информацию»,
«ВЫВОД: JSON со списком фактов» + абзац F5 «ФОКУС НА СОДЕРЖАНИИ» (формат
сообщений). Ни класса записи, ни атрибуции, ни опоры, ни правил провенанса.

**После** (3724 символа, `PREV_FACT_EXTRACT_PROMPT` и абзац F5 — байт-в-байт,
только дописан новый раздел):

* `КЛАССИФИКАЦИЯ И АТРИБУЦИЯ` — обязательное поле `kind` с закрытым списком:
  `durable_fact`, `one_off_request`, `world_news`, `quote`,
  `hypothetical_character`, `temporary_event`, `communication_pattern`;
  `subject_type`/`object_type`: `user | world | topic | character`;
* правила: разовая просьба — не свойство человека; новость принадлежит миру или
  источнику, а не переславшему; цитата принадлежит тому, кого цитируют;
  описание персонажа не становится биографией автора/адресата; временное
  событие не выдаётся за постоянное свойство; обобщение о манере общения
  допустимо только с опорой `basis`;
* `source_message_ids` — реальные номера сообщений входа (не выдумывать);
* «Лучше пустой список, чем запись ради количества».

Классы — смысловые категории, а не перечисление фраз: ни одного лексического
шаблона, ни стоп-слов, ни регексов по именам/цитатам/скриншотам.

## 3. Матрица классов (структурные последствия в коде)

Решение принимает `fact_durability_decision(fact)` (чистая функция, без LLM):

| `kind` | Пишется в `graph_facts` | Личный пул (`target_user`) | Атрибуция при записи | Счётчик `usage_json` |
|---|---|---|---|---|
| `durable_fact` (subject_type user/не задан) | да | да | прежняя эвристика провенанса | `saved` |
| `durable_fact` (world/topic/character) | да | нет | `world_knowledge` | `nonpersonal` |
| `one_off_request` | **нет** | — | — | `episodic_skipped` |
| `hypothetical_character` | **нет** | — | — | `episodic_skipped` |
| `world_news` (subject_type ≠ user) | да | нет | `world_knowledge` | `nonpersonal` |
| `world_news` (subject_type = user) | **нет** (публичное не приписывается человеку) | — | — | `world_attributed_to_person` |
| `quote` | да | нет | `third_party` / `opinion` | `nonpersonal` |
| `temporary_event` | да, с ограниченным `expires_at` | да | прежняя эвристика | `saved` |
| `communication_pattern` с `basis` | да | да | прежняя эвристика | `saved` |
| `communication_pattern` без `basis` | **нет** | — | — | `pattern_without_basis` |
| неизвестный `kind` (дрейф) | элемент отклоняется при разборе | — | — | `invalid` → `parse_error` |

Сырые сообщения (`smart_messages`), эпизоды и архив не удаляются: отказ
касается только записи в долговременный пул (пункт ТЗ «не удалять сырые
данные»). Если все кандидаты оказались недолговечными — исход
`no_new_facts` (честное «нет новых долговременных фактов»), а не `success`
с нулём записей и не пустая запись ради KPI.

## 4. Что изменено в коде

`services/summary_memory.py`:

1. `FACT_EXTRACT_PROMPT` — новый раздел контракта (см. §2).
2. Новые константы словаря: `FACT_KIND_*`, `FACT_KINDS`, `FACT_EPISODIC_KINDS`,
   `FACT_ENTITY_TYPES`, `FACT_NONPERSONAL_KINDS`.
3. `_validate_fact` — читает `kind`/`subject_type`/`object_type`/`basis`/
   `source_message_ids`; неизвестный класс → элемент отклоняется (честный
   дрейф), старый формат без `kind` → `durable_fact` (совместимость).
4. `fact_durability_decision` — матрица §3, без вызовов модели.
5. `_is_json_list` — прозаический fallback запускается только для не-списка:
   валидный JSON-массив, где элементы не прошли контракт, не «дотягивается»
   текстом ответа.
6. `_memorize_facts_inner` — решение применяется к `target_user`, `expires_at`
   (для `temporary_event` ограниченный TTL вместо «вечно»), к атрибуции
   (`attribution_method`/`assertion_kind`), к квоте и к счётчикам
   `usage_json`; добавлен честный исход `no_new_facts`.
7. `_attach_fact_provenance(..., declared_method=, declared_kind=)` — заявленная
   извлечением атрибуция приоритетнее текстовой эвристики; `None` → прежнее
   поведение всех старых путей.

Внешние вызовы не менялись: тот же один LLM-запрос, тот же парсер, тот же
писатель; новых сетевых/LLM-вызовов нет.

`plans/docs/canon/backlog.md` — канон R46-2 синхронизирован байт-в-байт
(ADR-1013-3 §2: код = эталон = тест) + примечание EVOL-006.

`services/prompt_registry.py` — поднята заводская ревизия (см. §5).
`services/prompt_factory.py` не менялся: ревизий/печатей он не хранит
(единственная точка — `prompt_registry`), поднимать там нечего.

## 5. Реестр: метка, печать, отпечаток набора

| Что | Было | Стало |
|---|---|---|
| `FACTORY_REVISION_LABELS["memory.fact_extract"]` | `fact-extract-w2a` | `fact-extract-evol006` |
| `FACTORY_REVISION_SEALS["memory.fact_extract"]` | `("fact-extract-w2a", "01be6c765713")` | `("fact-extract-evol006", "c41914057333")` |
| идентичность ревизии | `fac:sha12(fact-extract-w2a)` | `fac:30514648e135` |
| `FACTORY_SET_SHA256_12` | `03776db327b4` | `07ade6d16884` |

Хеши посчитаны из кода (`pr.sha12(factory_text(...))`,
`pr.factory_set_fingerprint()`), не выдуманы; `seal_integrity()` → `{}`.
Смена текста без бампа метки теперь невозможна: релизная политика при старте
сравнит метку и печать и промолчит только при совпадении — активация идёт
штатным путём `apply_release` (ручных миграций «по имени ключа» нет).

## 6. Тесты

Новый постоянный файл `tests/test_evol006_fact_quality.py` (21 тест,
offline, LLM-заглушка, `:memory:` БД):

* контракт промпта: все 7 классов, типы сущностей, правила атрибуции,
  `basis`, `source_message_ids`, «Лучше пустой список»; отсутствие лексических
  стоп-слов/регексов и прод-примеров из наблюдения владельца;
* разбор: класс и атрибуция читаются структурно; неизвестный класс → `invalid`;
  старый формат без `kind` → `durable_fact` (совместимость); матрица решений;
* запись: разовая просьба не попадает в долговременный пул; новость не
  приписывается человеку (`target_user IS NULL`, `world_knowledge`); новость с
  подменой субъекта на человека отклоняется; персонаж запроса не становится
  биографией и сырое сообщение остаётся в `smart_messages`; временное событие
  получает непустой `expires_at`; обобщение без опоры отклоняется, с опорой —
  пишется; провенанс (`tg_message_id`) сохранён;
* честный отказ: не-JSON → `skipped/parse_error` + WARNING `facts lost`;
  валидный `[]` → `no_new_facts`; дрейф класса → нет записи.

Прогоны (worktree, `.venv\Scripts\python.exe -m pytest`, cwd = worktree):

```
pytest tests/test_evol006_fact_quality.py -q                      → 21 passed
pytest tests/test_evol006_fact_quality.py tests/test_evol018_prompt_audit.py \
  tests/test_evol007_new_facts_widget.py tests/test_evol009_memory_diagnostics.py \
  tests/test_graphrag_memory.py tests/test_metafact_penalty_round1018.py \
  tests/test_mca17_summary_instrumentation.py tests/test_summary_memory.py \
  tests/test_summary_prompts.py tests/test_evol016_prompt_activation.py -q
                                                                  → 384 passed
+ tests/test_asap44_graphrag_batch_breaker.py tests/test_history_retention_toggle.py
                                                                  → 409 passed,
                                                                    1 failed (см. §8)
python -m compileall -q services                                  → exit 0
```

`tests/test_evol018_prompt_audit.py` зелёный: печати целы, отпечаток набора
совпал, grep-аудит не нашёл необъявленных констант.

## 7. Подтверждение: лексических фильтров нет

* В промпте — только смысловые классы и правила; ни одного списка «запрещённых
  слов», ни одного упоминания конкретных фраз из прод-наблюдения.
* В коде проверки структурные: класс ∈ закрытый список, наличие `basis`,
  тип сущности, список целых id, `expires_at`, `target_user`. Регексы
  используются только в существующем fallback-парсере (форма разделителей), не
  по именам и не по содержанию.
* Текст промпта проверяется тестом на отсутствие `blacklist/whitelist/стоп-слов/
  regex/…` и прод-фраз (`tests/test_evol006_fact_quality.py::TestPromptContract`).

## 8. Честные ограничения и неблокирующие наблюдения

1. **Номера сообщений от модели — не провенанс.** `source_message_ids` в этом
   пути нельзя сверить с окном (его нет: memorize получает `raw_text` и реальный
   `tg_message_id` от хука). Поэтому провенансом остаётся настоящий
   `tg_message_id`/`forward_from`, а `basis` используется как структурный
   признак опоры для `communication_pattern`. Выдавать модельные id за
   провенанс было бы выдумыванием.
2. **Retry-промпт** `_FACT_RETRY_SYSTEM_PROMPT` (блок `memory.fact_retry`) не
   менялся: он восстанавливает форму JSON, факты из него дефолтятся в
   `durable_fact`. Менять его — отдельное решение по реестру (второй бамп), на
   acceptance EVOL-006 не влияет.
3. **Счётчик кандидатов EVOL-009** (`services/memory_diagnostics.py`, вне моего
   write scope) считает `candidates = saved+skipped+deduped+superseded` и новых
   полей не знает: отброшенные по классу кандидаты видны отдельно в
   `usage_json` (`episodic_skipped`, `pattern_without_basis`,
   `world_attributed_to_person`, `nonpersonal`) и в INFO-логе, но в «кандидаты»
   не попадут, пока полоса EVOL-009 не учтёт их. Это осознанная граница
   лейна, а не скрытая потеря: событие и счётчики пишутся.
4. **Кроновый `EXTRACT_PROMPT`** (nodes/edges, в `graph_facts` не пишет) оставлен
   без изменений — см. §1; если владелец захочет тот же контракт и для графа,
   это отдельная канон-миграция с двумя байт-эталонами.
5. **Предсуществующие падения** (проверено `git stash` на базе `a02aca0c`, без
   моих правок): `tests/test_history_retention_toggle.py::TestCatalogSeed::
   test_group_and_categories` (каталог: `CHAT_DEDUP_*`, `SMART_CACHE_*`) и
   `tests/test_soul1_registry_completeness.py::
   test_legacy_persona_canons_are_registered_with_revision_labels`
   (`verbilizer.mode.deep_research`). К EVOL-006 не относятся.
6. **Общий worktree.** В `evol/impl` параллельно пишут другие полосы
   (`web/app.js`, `services/mca_vision.py`, `services/memory_diagnostics.py`,
   `services/episode_diagnostics.py`, …). Я их не трогал; единственная проверка
   «до/после» через `git stash` восстановила состояние байт-в-байт (сверено с
   сохранённым SHA стеша), после неё соседняя полоса дописала `web/app.js` —
   потерь нет.

## 9. Итог для владельца (RU)

Промпт-экстрактор фактов теперь требует от модели явно различать: устойчивый
факт о человеке, разовую просьбу, новость/репост, цитату, выдуманного персонажа,
временное событие и наблюдение о манере общения. Разовая просьба и описание
персонажа больше не занимают место в долговременной памяти о человеке (остаются
в истории и эпизодах), публичная новость записывается как сведение о мире, а не
как личный факт участника, а обобщение о характере без опоры на конкретные
сообщения отклоняется. Это сделано в том же самом вызове модели без новых
затрат: тот же промпт-вызов, тот же разбор, плюс честные счётчики отказов.
Промпт получил новую заводскую ревизию (`fact-extract-evol006`, печать
`c41914057333`), поэтому релиз подхватит его штатно. Тесты: 21 новый, набор по
памяти и промптам — 409 зелёных; два падения в каталоге/персона-канонах
существовали до правки и к задаче не относятся.
