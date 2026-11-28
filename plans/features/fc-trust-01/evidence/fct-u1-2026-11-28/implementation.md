# FCT-113 / FCT-192 — residual unit U1 (Builder, 28.11.2026)

Роль: Builder. Ветка `feat/fct-u1-assertion-binding-2026-11-28` от tip
`release/2.58.272` = `a2195fe3f9289d75461f27c7278d52779e2b812a`
(продуктовый кандидат `f6cd011e0`, bump 2.58.272).
Контракт: `plans/features/fc-trust-01/evidence/fct-contract-decisions-2026-11-28/decisions.md`
sha256 `69b3ed93ca50d6b83303a8451b32ea39bb2cd5d79bbb36c1ea2bf85d8c00d0af` (§1 — FCT-113,
§2 — FCT-192, §3 — строки карты).

Кандидат: `45313f3fb2387f4a53fdc449921a874ddb8c0c9c` (продуктовый код —
`324923b19`, второй коммит трогает только тест-фикстуру).

## 1. Что реализовано (U1 — `temporal_factcheck.py`, `search_aggregator.py`)

### 1.1 FCT-113 — аддитивное поле части `assertion_kind`

* JSON-схема `TEMPORAL_ANALYST_SYSTEM` (единственный вызов Analyst'а,
  `services/temporal_factcheck.py:1155-1212` в базе) получила
  `"assertion_kind": "decision_status|normative_state_on_date|unknown"` в примере
  части **и** два аддитивных правила (14, 15). Существующие правила 1–13 и
  `ANALYST_DIRECTIVE` не сокращены: удалённых строк инструкций — **0**
  (`raw/temporal-factcheck-diff.txt`, единственное удаление — расширяемая
  строка схемы `"evidence_refs": ["ev-1"]}`).
* Нормализация на единственном входе модели (`verdict_from_payload`,
  `_normalized_analyst_part`):
  * принимаются только `decision_status` / `normative_state_on_date`;
  * `image_content` / `public_statement_attribution` от модели **отвергаются**
    (→ `unknown`), конфликт пишется в существующий `logger`
    (`[temporal] analyst part assertion_kind rejected …`); новых reason-кодов
    нет — `verdict.reason` не подменяется (тест);
  * значение вне закрытого набора, не-строка, `None`, bool → `unknown` без
    исключения; отсутствующее поле не добавляется (аддитивность).
* Набор значений берётся из `factcheck_planner.ASSERTION_KINDS` (второй копии
  оси нет; импорт ленивый — planner импортирует `temporal_factcheck`).
* Структурный приоритет (`image_content` из caption/ocr,
  `public_statement_attribution` из tool'а атрибуции) обеспечен на двух слоях:
  вход модели отвергает структурные значения, а существующий merge
  (`part.update(metadata)`, единственный писатель метаданных части) ставит тип
  из `ClaimUnit`. Проверено сквозным тестом: медиа-тезис с `decision_status`
  от модели остаётся `image_content`; цитата без атрибуции не «разблокируется»
  моделью (понижение `assertion_kind_unknown` сохраняется).

### 1.2 FCT-192 — узкий year conflict в evidence-профиле

`services/search_aggregator.py`, `claim_relevance(..., require_anchor=True)`:
если у тезиса есть явный 4-значный год (из `timeframe`), в пассаже есть явные
годы, но **ни один** год пассажа не попадает в интервал годов тезиса —
`supports`/`contradicts` понижаются до `qualifies`, basis получает
`time:year_conflict`, `strength` → `indirect`.

Сужения (проверены тестами и мутациями):

* профиль по умолчанию (`require_anchor=False`, потребители
  `direct_execution`/`evidence_policy`) не изменён — байт-паритет сохранён;
* нет года у тезиса или нет явного года в пассаже (кросс-язычный кейс
  «30 октября 2026» ↔ «October 30») — конфликта нет;
* диапазон тезиса (`2023–2025`) не конфликтует с годом внутри интервала;
* год внутри URL пассажа (`https://…/2024/report`) утверждением источника не
  считается (URL извлекается отдельным стрип-шагом).

### 1.3 FCT-192 — аддитивное поле части `evidence_quotes`

* Схема Analyst'а: `"evidence_quotes": {"ev-1": "<дословная фраза>"}` + правило
  15 («не пересказ и не цитата из другой выдержки»).
* Форма валидируется на входе вердикта: не-словарь, не-строковая/пустая фраза,
  ID вне allowlist выдержек текущего прогона — отбрасываются; ключи
  нормализуются, пробелы по краям снимаются; поле переживает коррекцию
  validator'ом.
* Дословное вхождение цитаты в cited-пассаж и понижение непривязанных
  positive-частей — merge-стадия (U2), здесь **не** реализованы и не
  подменяются (см. §4).

## 2. Сопутствующее (не продуктовое поведение)

Изменение текста канонического промпта обязывает бамп реестра (fail-closed
печать, `services/prompt_registry.py`): метка `temporal-analyst-fct113-192-u1`,
печать `3f7ecbff8509`, прежние байты 2.58.272 — `5baf6afaf2d8`
(`temporal-analyst-fc04-corrective`); наборный отпечаток
`10efa51a8dae` → `bd06a8a1a782`. Обновлён литерал метки в существующем
тесте `tests/test_asap_fc_voice01_verbalizer.py::test_temporal_analyst_seal`
(проверка печати сохранена), запись о бампе — в истории реестра.

Не менялись: модель, лимиты, квоты инструкций, флаги/настройки, DDL/схема БД,
`routes.py`/`web/*`, `relation_evidence.py`, `factcheck_service.py`,
`factcheck_prompts.py`, версия продукта.

## 3. Тесты

Новые файлы: `tests/test_fc_trust_assertion_kind.py` (19 тестов),
`tests/test_fc_trust_relation_binding.py` (26 тестов) — 45 всего.

| Прогон | База `a2195fe3f` (+ те же новые файлы) | Кандидат `45313f3fb` |
|---|---|---|
| новые тесты | **28 failed / 17 passed** (`raw/red-base-tests.txt`) | **45 passed** (`raw/green-new-tests.txt`) |
| `test_fc_trust_s1_contract.py` | — | 27 passed |
| `test_fc_trust_retrieval.py` | — | 70 passed |
| `test_fc_trust_verdict.py` | — | 24 passed |
| `test_fc_trust_render.py` | — | 35 passed |
| 6 файлов FC-TRUST (новые + 4 обязательных) | — | **201 passed** (`raw/green-focused-201.txt`) |
| 20 затронутых файлов (factcheck/search/voice) | — | **451 passed** (`raw/green-broad-451.txt`) |

RED на базе именно по проверяемому механизму: на `a2195fe3f` нет ни
нормализации полей части (значения модели проходят как есть, включая
`image_content`/мусор и `evidence_quotes` с чужими ID), ни year conflict
(2024-пассаж остаётся `supports`). 17 «зелёных на базе» — контрольные кейсы
(кросс-язычный без года, тезис без года, тот же год, диапазон, дефолтный
профиль, приём смысловых значений), они доказывают, что механизм узкий и не
ломает прежнее поведение.

Мутации (каждая — на кандидате, откат `git checkout`):

| # | Мутация | Результат |
|---|---|---|
| M1 | принимать структурные значения от модели (снять отвержение) | 2 failed: `test_structural_kind_from_model_is_rejected[image_content|public_statement_attribution]` |
| M2 | снять gate `require_anchor` у year conflict | 1 failed: `test_default_profile_keeps_previous_behaviour` |
| M3 | не вырезать URL при извлечении годов пассажа | 1 failed: `test_year_inside_url_is_not_a_passage_year` |
| M4 | не фильтровать цитаты по allowlist выдержек | 2 failed: `test_quote_for_foreign_evidence_is_dropped`, `test_mixed_quotes_keep_only_current_run_evidence` |
| M5 | точное членство вместо интервала годов тезиса | 1 failed: `test_year_interval_of_the_claim_covers_passage_year` |

Сырые выводы: `raw/mutation-m1.txt` … `raw/mutation-m5.txt`.

### Предсуществующие падения (не связаны с кандидатом)

На самой базе `a2195fe3f` (без изменений кандидата) падают два теста:
`test_evol018_prompt_audit.py::test_grep_audit_counts_are_stable` (пин 323
против фактических 331 файлов — дрейф после пина) и
`test_asap_fc_voice_l1_decision_profile.py::test_direct_service_l1_payload_gets_profile_from_turn_frame`
(стаб теста не принимает `preserve=` у `_l1_reply_block`). Оба падают
одинаково до и после изменения; в объём U1 не входят и не «чинились»
(`raw/pre-existing-failures-base.txt`).

### Измеримое acceptance FCT-113 из решения

`test_four_fixtures_produce_all_four_owner_values`: четыре тезиса владельца
дают четыре разных значения оси — атрибуция (структурный tool) и
изображение (caption/ocr) из планировщика, `decision_status` и
`normative_state_on_date` — из scripted-ответа Analyst'а; множество значений
не содержит `unknown` и не дублируется. **Граница U1:** запись смысловых
значений в итоговый `parts[]` (и общий инвариант «все четыре в одной части
вердикта») выполняет merge-стадия U2 — на базе и на U1-кандидате merge
по-прежнему ставит тип из `ClaimUnit`, поэтому сквозной четырёхзначный
инвариант в `parts[]` здесь честно не заявляется (см. §4).

## 4. Что осталось — U2 (`services/factcheck_service.py`, не делалось)

Передано следующему исполнителю (один файл, тот же контракт §1.3/§2.3):

1. `merge_claim_coverage` (`:2832-2963`): принять смысловое значение части
   только для `decision_status`/`normative_state_on_date` (структурный
   не-`unknown` тип побеждает; иначе `unknown`), чтобы `parts[]` нёс значение
   Analyst'а — это закрывает четырёхзначное acceptance в одном вердикте.
2. Привязка цитаты: нормализация (NFKC/casefold/схлопывание пробелов/снятие
   кавычек) и проверка вхождения `evidence_quotes[eid]` в `support` именно
   этой выдержки; эквивалент для количественного тезиса — существующий
   `number:<метрика>+<единица>` в `basis`.
3. `parts[i].relation_binding` (`metric|quote|""`), понижение
   `supported`/`refuted` без валидной привязки до `insufficient_evidence` с
   причиной в `gap_note`; `snippet_only` привязкой быть не может; `mixed`
   требует привязки для каждой положительной стороны.
4. Тесты U2 (в этом файле сознательно отсутствуют, чтобы не кодировать
   неверное поведение): цитата из чужой выдержки → `insufficient`; валидная
   цитата → `supported`/`refuted` сохраняется; качественный тезис без цитаты →
   `insufficient`; `snippet_only` + цитата → не привязка; `relation_binding`
   заполнен.

## 5. Ограничения и честные замечания

* Семантическая точность модели на реальных формулировках (живой прогон двух
  owner-фраз) в U1 не проверялась: она требует U2 для наблюдаемого эффекта в
  вердикте и выполняется на объединённом кандидате.
* Формулировка правил 14/15 — аддитивная инструкция существующей стадии;
  новых LLM-вызовов/стадий нет (существующий тест
  `test_no_extra_llm_call_added` зелёный в общем прогоне).
* Квоты инструкций не вводились; сокращений текста промпта — 0 удалённых
  строк (см. diff).

## 6. Конфигурация и окружение

Python 3.12 (`C:\Code\Python\adminbot\.venv`), pytest 9.1.1, cwd — worktree
`…/WorkspaceData/worktrees/c742e4de9e92c489/fc-trust-01-u1-3f69efb80e96-d491fedf`.
Флаги/настройки не менялись; поведение проверено при заводских значениях
(`FACTCHECK_PIPELINE_V2_ENABLED` в тестах включается фикстурой существующего
S1-файла). DDL/миграций нет; версия продукта не менялась (база уже 2.58.272).

## 7. corrective r1: F1 (`FCT-U1-R1-F1`, 28.11.2026)

Продуктовая правка — только `services/search_aggregator.py` (year-guard) и тесты U1;
`factcheck_service.py`, `temporal_factcheck.py`, рендер, DDL, флаги, `prompt_registry.py`
не тронуты. Fix-коммит `0fc7201ea` (родитель — `45313f3fb`), ветка
`feat/fct-u1-assertion-binding-2026-11-28`.

### 7.1 Finding и root cause

Ревью r1 §4 F1: `_EXPLICIT_YEAR_RE` + `_year_conflict` считали годом любой 4-значный токен
`(19|20)\d{2}`, не отличая дату от суммы/количества. `strip_publication_labels` такие токены
не убирает. Пассаж «Билет на выставку стоит 2025 рублей, выбросы ЭкоПром снизились на 12%»
при тезисе «…в 2024 году» получал `time:year_conflict`, роль `qualifies`/`indirect`, и merge
понижал валидный вердикт `supported` → `insufficient_evidence` при пустом `gap_note`
(`status_detail="verified"`): регрессия относительно базы `a2195fe3f` и нарушение контроля
«пассаж без явного года → конфликта нет» (решения §2.1 п.1, §2.4).

### 7.2 Что изменено в guard'е

`_explicit_years` теперь пропускает токен, если `_year_is_quantity` признал его числом:

* **единица/валюта/масштаб сразу после числа** (`_YEAR_QUANTITY_TAIL_RE`):
  `тыс…`, `млн`, `млрд`, `трлн`, `миллион…`, `миллиард…`, `рубл…`, `руб.`, `₽`, `$`, `€`,
  `евро`, `долл…`, `процент…`, `%`, `тонн…`, `человек…`, `чел…`, `кг`, `шт` —
  с обязательной границей слова/числа после единицы;
* **валюта/масштаб перед числом** (`$`, `€`, `₽`) — кейс `$2025 млн`, `₽2025`.

Список — единицы и валюты, а не «слова-годы»: годовые маркеры (`2025 году`, `2025 г.`,
`с 2023 по 2024`) в него не входят, поэтому настоящие годы ведут себя как раньше, а реальный
другой год по-прежнему даёт `time:year_conflict`. Фильтр применяется симметрично к тезису и
пассажу (сумма в `timeframe` — тоже не год). Docstring `_year_conflict` дополнен.

Diff: `raw/f1-corrective-diff.txt`; blob `search_aggregator.py` — `59632eb02`
(до правки `628abdde2`). Строк: +36/−3.

### 7.3 Тесты (добавлено 6 кейсов в `tests/test_fc_trust_relation_binding.py`)

| Кейс | Что доказывает |
|---|---|
| `test_amount_instead_of_year_behaves_like_no_year` (4 параметра: «2025 рублей» из repro, «2025 млн рублей», `$2025 млн`, «2025 тыс. тонн») | на реальном пути `claim_relevance(require_anchor=True)`: роль `supports`, `direct`, нет `time:year_conflict` |
| `test_amount_instead_of_year_keeps_supported_verdict` | сквозь `merge_claim_coverage`: merged и part `factual_verdict=supported` (наблюдаемая регрессия закрыта) |
| `test_amount_and_real_other_year_still_conflict` | сумма не маскирует настоящий другой год в том же пассаже: `qualifies`/`indirect` + `time:year_conflict` |

Результаты (кандидат `0fc7201ea`): файл — **32 passed**; два U1-файла — **51 passed**
(45 прежних + 6); обязательный набор `s1_contract`+`retrieval`+`verdict`+`render`+2 U1 —
**207 passed**; широкий прогон 62 файлов — **1506 passed, 3 failed**, все три падения
предсуществующие и те же, что в независимом прогоне ревью. Точные команды и списки файлов —
`raw/f1-runs.md`, `raw/broad-f1-files.txt`, `raw/broad-f1-part{1..4}-files.txt`.

### 7.4 Мутации

| # | Мутация | Факт |
|---|---|---|
| A | `_year_conflict`: `return False` | **6 failed, 45 passed** — 5 ожидаемых ревью + новый conflict-кейс (`raw/mutation-f1-a-no-year-conflict.txt`) |
| B | Вернуть старое поведение: убрать фильтр сумм из `_explicit_years` | **5 failed, 46 passed** — ровно новые amount-кейсы и merge-тест (`raw/mutation-f1-b-amounts-as-years.txt`) |

### 7.5 Repro до/после и RED на базе

* до правки: `raw/probe-f1-before.txt` — `qualifies/indirect` + `time:year_conflict`,
  merged `insufficient_evidence`, `gap_note=""`;
* база `a2195fe3f`: `raw/probe-f1-base.txt` — `supports/direct`, merged `supported`;
* после правки: `raw/probe-f1-after.txt` — amount-кейсы как на базе, `real_other_year`
  и `amount_plus_other_year` — конфликт (функция U1 сохранена).

RED на базе: `tests/test_fc_trust_relation_binding.py` → **6 failed, 26 passed**
(`raw/red-f1-new-tests-on-base.txt`). Честно: amount-кейсы на базе проходят, потому что
проверяют паритет с поведением «без года»; RED даёт кейс «сумма + реальный другой год»
(и прежние conflict-тесты U1). Скрипт воспроизведения — `raw/probe_f1_repro.py`
(скрипты ревью `repro/` в репозитории отсутствуют, сценарий воспроизведён независимо).

### 7.6 F2 / F3 и честные ограничения

* **F2** (NON-BLOCKING): не реализован; строка добавлена в `plans/backlog.md`
  (прокинуть `allowed_refs` в `apply_validator`).
* **F3** (NON-BLOCKING): закрыт гигиеной evidence — для каждого широкого прогона записаны
  точная команда и список файлов (`raw/f1-runs.md`); единый прогон 62 файлов дважды прерван
  перезапуском сервера инструментов, поэтому выполнен 4 частями с суммой 1506/3 (не падения
  тестов, а инфраструктурный обрыв).
* Guard распознаёт количество по форме записи рядом с числом: суммы без единицы/валюты
  (`USD 2025`, `2025 единиц`) по-прежнему могут считаться годом — консервативное ложное
  ослабление, не ложное подтверждение; суммы с разделителем разрядов (`2 024`) годом не
  считаются и раньше. Живой LLM-прогон и UI не выполнялись: изменение детерминированное,
  рендер/публикация не затронуты.
