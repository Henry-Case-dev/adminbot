# REVIEW R1 — FC-TRUST-01 / U1 (FCT-113 `assertion_kind` + FCT-192 year conflict)

Роль: Reviewer (независимый). Дата: 28.11.2026. Писатель — только этот файл (`review-r1.md`) и `repro/`.

## 0. Кандидат и база (проверено фактически)

| Поле | Значение |
|---|---|
| Ветка | `feat/fct-u1-assertion-binding-2026-11-28` |
| Tip (кандидат) | `45313f3fb2387f4a53fdc449921a874ddb8c0c9c` |
| Продуктовый коммит | `324923b19` (второй коммит `45313f3fb` — только тест URL-года) |
| База | `release/2.58.272` = `a2195fe3f` (продукт `f6cd011e0`) |
| Worktree | `…\WorkspaceData\worktrees\c742e4de9e92c489\fc-trust-01-u1-3f69efb80e96-d491fedf` |
| Состояние worktree | `git status --porcelain` пуст (после моих мутаций всё восстановлено) |
| Blob'ы tip | `temporal_factcheck.py` `65ff21fae`, `search_aggregator.py` `628abdde2`, `prompt_registry.py` `d24667d65` |
| Контракт | `…/fct-contract-decisions-2026-11-28/decisions.md`, sha256 `69b3ed93…d0af` — совпал с заявленным |
| Evidence Builder | `…/fct-u1-2026-11-28/implementation.md`, sha256 `8b2d61ed…776b` — совпал с заявленным |

Изменено 6 файлов (`git diff --name-status a2195fe3f 45313f3fb`): `services/temporal_factcheck.py` (+110),
`services/search_aggregator.py` (+53), `services/prompt_registry.py` (метка/печать/отпечаток), литерал метки в
`tests/test_asap_fc_voice01_verbalizer.py`, 2 новых тест-файла (+451 строк). `factcheck_service.py`,
`factcheck_planner.py`, `relation_evidence.py`, `routes.py`, `web/*`, DDL, флаги — не тронуты (подтверждено diff).

## 1. ВЕРДИКТ

**NEEDS_FIXES** — один блокирующий IN_SCOPE дефект (`FCT-U1-R1-F1`).

Согласен, что **FCT-113/FCT-192 остаются REVIEW до U2** (обоснование — §6). U1 как residual-юнит сделан
добросовестно и в заявленных границах; дефект — в новом детерминированном guard'е года.

## 2. Покрытые ID и контрактные пункты

* FCT-113 — `plans/current_task.md:10828-10835` (L00092-95), решения §1.1–§1.5, строки работ §1.5 №1/№3/№4.
* FCT-192 — `MAN-FCT-39`, `current_task.md:10839-10841`, решения §2.1–§2.5, строки работ §2.5 №1/№2/№4/№5.
* Инварианты, проверенные отдельно: закрытый набор и приоритет структуры (§1.3 п.1–3), аддитивность
  (§1.3 п.6, §2.3), контроль «нет года в пассаже → поведение не меняется» (§2.1 п.1, §2.4), сохранение
  понижения `assertion_signal` (§1.3 п.4), невмешательство в `relation_evidence.py`/renderer/DDL.

## 3. Что проверено лично (три опоры)

### 3.1 Контракт ↔ код

| Пункт контракта | Фактическая реализация | Итог |
|---|---|---|
| закрытый набор, вне набора → `unknown` | `_analyst_assertion_kind`: `value in ASSERTION_KINDS` (набор из planner, второй копии нет) | соответствует |
| `image_content`/`public_statement_attribution` модель не ставит | те же два значения → `ASSERTION_KIND_UNKNOWN` + `logger.warning`, `verdict.reason` не подменяется | соответствует |
| смысловые значения принимаются | `decision_status`/`normative_state_on_date` проходят в `parts[]` | соответствует |
| аддитивность (нет поля — нет ключа) | `_normalized_analyst_part` добавляет ключ только при наличии | соответствует |
| `evidence_quotes` — форма {ID текущего прогона: непустая строка} | `_validated_evidence_quotes` + `allowed_refs`; production-вызовы передают allowlist (`factcheck_service.py:4166` → `:4217`, `:4347`) | соответствует |
| дословность/вхождение — не U1 | реализовано только в merge (U2), в U1 нет | честно ограничено |
| year conflict только в evidence-профиле | `require_anchor and _year_conflict(...)`; профиль по умолчанию байт-паритет (тест + моя проверка) | соответствует |
| «пассаж без года → конфликта нет» (контроль §2.4) | **нарушен для 4-значных сумм** («2025 рублей», «2025 млн рублей») — см. F1 | **НЕ соответствует** |
| диапазон тезиса не конфликтует | `low..high` | соответствует |
| кросс-язычный контроль | год берётся только из 4-значного токена; «October 30» не конфликтует | соответствует |

Дополнительно прочитан `merge_claim_coverage` (U2-файл, не изменён): `part.update(metadata)` (`:2952`) —
единственный писатель `assertion_kind` части, поэтому структурный тип действительно побеждает; понижение
`sensitive`-цитаты (`:2972-2984`) не обходится моделью.

### 3.2 Тест-ассерты (дискриминация, не тавтологии)

Прочитаны все 45 ассертов. Тесты вызывают production-функции (`claim_relevance`, `factcheck_planner._relevance_for`,
`verdict_from_payload`, `apply_validator`, `merge_claim_coverage`), проверяемая логика не замокана; ожидания
заданы контрактом (набор значений, allowlist, `time:year_conflict`, `indirect`), а не вычислены из того же кода.
`evidence_quotes`-тесты действительно проверяют отбрасывание (чужая выдержка, не-словарь, пустая фраза),
а не «поле есть». RED на базе воспроизведён (см. 3.3).

### 3.3 Самостоятельно выполненные прогоны и контрпримеры

Все — в worktree кандидата, venv `C:\Code\Python\adminbot\.venv`, Python 3.12.

| Проверка | Результат |
|---|---|
| новые тесты (2 файла) | **45 passed** (12.0 с) — заявленное число 45 подтверждено |
| `s1_contract` + `retrieval` + `verdict` + `render` + 2 новых | **201 passed** (10.1 с) — 201 подтверждено |
| база `a2195fe3f` + те же 2 новых файла (отдельный worktree) | **28 failed / 17 passed** — RED и «17 контрольных» подтверждены поимённо |
| 49 файлов `factcheck/search/voice` (мой более широкий набор) | **1120 passed, 3 failed**; все 3 (2× `test_selfdiag_corrective_research.py`, 1× `test_asap_fc_voice_l1_decision_profile.py`) падают одинаково **на базе** — кандидатом не вызваны |
| заявленные 451 (20 файлов) | не воспроизводимы из evidence: команда и список файлов не записаны (см. F3) |

Мутации (каждая — на кандидате, откат `git checkout --`, worktree после — чист):

| # | Мутация | Файл | Ожидание | Факт |
|---|---|---|---|---|
| A | принимать структурные значения от модели (`if False`) | `temporal_factcheck.py` | падает `test_structural_kind_from_model_is_rejected[image_content|public_statement_attribution]` | **2 failed** (ровно эти) |
| B | отключить year conflict (`return False`) | `search_aggregator.py` | падают тесты другого года и обёртки планировщика | **5 failed** (ровно: `test_passage_of_another_year_is_not_support`, 3×`test_any_other_year_is_a_conflict`, `test_planner_wrapper_passes_claim_timeframe`) |
| C | **зона, которую правка не трогала** (`factcheck_service.py`, merge): убрать запись `assertion_kind` из metadata | `factcheck_service.py` (U2-файл) | падает структурный приоритет | **1 failed** — `test_image_claim_keeps_image_kind_against_model_value`; оракул теста реальный |

Скрипты воспроизведения: `repro/mutate.py`, `repro/probe*.py`.

## 4. НАЙДЕННЫЕ ДЕФЕКТЫ

### F1 (BLOCKING, IN_SCOPE) — `time:year_conflict` принимает денежную/количественную сумму за год

* **finding_id:** `FCT-U1-R1-F1` (новый, ранее не открывался)
* **Где:** `services/search_aggregator.py`, `_EXPLICIT_YEAR_RE`/`_year_conflict` (новый код U1).
* **Контракт:** решения §2.1 п.1 и §2.4 — «пассаж без явного года → конфликта нет»; контрольный тест
  `year conflict: … пассаж без года → поведение не меняется`. Пассаж с суммой «2025 рублей / 2025 млн рублей»
  года не содержит.
* **Reproduction (реальный путь `claim_relevance`, `require_anchor=True`):**

```
claim:   "ЭкоПром снизила выбросы на 12% в 2024 году."   timeframe="2024"
passage: "Билет на выставку стоит 2025 рублей, выбросы ЭкоПром снизились на 12%."
                                                       (repro/probe2.py, probe.py)
```

* **Expected:** `role=supports`, `strength=direct`, без `time:year_conflict` (как на базе `a2195fe3f`).
* **Actual:** `role=qualifies`, `strength=indirect`, `basis=('entity:ЭкоПром','number:12+percent','time:year_conflict')`.
  Так же ложно срабатывает на `2025 млн рублей`, `$2025 млн`, `2025 тыс. тонн`; `strip_publication_labels` такие
  токены не убирает; каверзные `2 024` (с пробелом) — не срабатывают, то есть фильтр опирается не на смысл, а на форму записи.
* **Влияние на вердикт (проверено сквозь `merge_claim_coverage`, `repro/probe3.py`):**

| | база `a2195fe3f` | кандидат `45313f3fb` |
|---|---|---|
| evidence.role | `supports` / direct | `qualifies` / indirect |
| `merged.factual_verdict` | `supported` | **`insufficient_evidence`** |
| `part.factual_verdict` | `supported` | **`insufficient_evidence`** |

  То есть валидный подтверждённый тезис превращается в «недостаточно данных», причём `gap_note` пуст и
  `status_detail="verified"` — понижение пользователю никак не объясняется.
* **Почему блокирует:** доказанная регрессия кандидата относительно базы + прямое нарушение контрольного
  пункта контракта в новом коде (а не «полировка»). Направление ошибки консервативное (ложное ослабление,
  не ложное подтверждение), поэтому severity — major, не critical.
* **Ожидаемое исправление (узкое, в файле U1):** 4-значный токен считать годом только когда он не является
  количеством — исключить совпадения, за которыми сразу идёт единица/валюта/масштаб (`руб|₽|\$|€|тыс|млн|млрд|%|тонн|чел`)
  и/или требовать годовой маркер/границу токена; добавить в `test_fc_trust_relation_binding.py` два кейса
  («сумма вместо года — поведение как без года», «сумма + реальный другой год — конфликт по году»).
* **Disposition:** IN_SCOPE — исправить в текущем кандидате и пере-ревьюить только затронутый guard + F1-тесты.

### F2 (NON-BLOCKING, hardening / BACKLOG_ONLY) — повторная нормализация в `apply_validator` без allowlist

`apply_validator` (`temporal_factcheck.py:1030`) вызывает `verdict_from_payload(merged, envelope, …)` **без**
`allowed_refs`, поэтому на втором проходе фильтр «ID из текущего прогона» не применяется. Утечки сегодня нет:
части уже отфильтрованы первым проходом, а payload validator'а не содержит `parts`. Демонстрируемого дефекта нет,
защита держится на порядке вызовов. Рекомендация (backlog): прокинуть `allowed_refs` в `apply_validator`.

### F3 (NON-BLOCKING, evidence hygiene / BACKLOG_ONLY) — число 451 не воспроизводимо из evidence

`raw/green-broad-451.txt` содержит только вывод; команда и список 20 файлов не записаны. Мой более широкий
набор (49 файлов) даёт 1120/3 с тремя предсуществующими падениями, то есть регрессий не выявляет, но заявленное
число проверить нельзя. Рекомендация: в следующих evidence писать точную команду прогона.

### Прочие наблюдения (не дефекты, для честности)

* `_EXPLICIT_YEAR_RE` ограничен `19xx/20xx`: годы 18xx/21xx+ не считаются явными → возможен только пропуск
  конфликта (консервативно), искажения нет.
* `evidence_quotes` попадают в `payload["parts"]` (`factcheck_service.py:4677`, данные Writer'а). Рендер не
  изменён (`test_fc_trust_render` 35 passed), публикация не затрагивается; это данные существующей стадии.
* `test_model_attribution_cannot_unlock_sensitive_quote` проверяет существующее понижение через `claim.assertion_kind`
  и не зависит от записи metadata в merge (под мутацией C проходит). Тест валиден, но он не охраняет F1-зону.

## 5. Инструкции модели не урезаны (правило владельца 24.10)

Проверено не по diff, а по фактически отрендеренному канону (`prompt_registry.factory_text("temporal.analyst")`,
база vs кандидат, `repro`-скрипты `dump_prompt.py`/`cmp_prompt.py`):

* длина 3639 → 4341 символов; `difflib` даёт **только две вставки, ни одного удаления**:
  (1) расширение примера части `"evidence_quotes": {...}, "assertion_kind": "..."`,
  (2) правила `(14)` и `(15)` перед `ANALYST_DIRECTIVE`;
* правила 1–13 и `ANALYST_DIRECTIVE` присутствуют без изменений; квот/обрезок не добавлено;
* метка `temporal-analyst-fct113-192-u1`, печать `3f7ecbff8509`, отпечаток набора `bd06a8a1a782` —
  тест `test_asap_fc_voice01_verbalizer.py::test_temporal_analyst_seal` зелёный в широком прогоне;
  bump обязателен и выполнен корректно (fail-closed печать).

## 6. Границы U1 и статус FCT-113 / FCT-192 — согласен: остаются REVIEW

* `merge_claim_coverage` (U2) по-прежнему пишет `assertion_kind` из `ClaimUnit`, поэтому смысловое значение
  Analyst'а в итоговом `parts[]` не появляется — четырёхзначное acceptance («все четыре типа в одной части
  вердикта») **не достигнуто** и U1 его не заявляет (implementation.md §3, строки 138–142 — заявление честное).
* Дословная привязка цитаты к cited-пассажу, `relation_binding` и понижение непривязанных positive-частей
  не реализованы (U2); U1 проверяет только форму цитаты — это ровно объём контракта §2.5 №1.
* Живой replay двух owner-фраз в U1 не проводился; evidence фиксирует это как отложенное до U2 (§5) — корректно.
* Следовательно `VERIFIED` для FCT-113/FCT-192 сейчас был бы ложным; REVIEW до U2 + независимого ревью U2 — правильный статус.

## 7. Ограничения этой проверки

* Живой LLM-прогон не выполнялся (не требуется для U1: наблюдаемый эффект появляется только после U2).
* UI/Playwright/Browser Use не применимы: изменение не влияет на визуальный вывод или взаимодействие
  (рендер не тронут, публикация не изменена) — визуальный гейт не открывается.
* Число 451 (F3) не воспроизведено; вместо него выполнен более широкий прогон 49 файлов.
* Мутации выполнялись на рабочем дереве кандидата с точным откатом; финальное состояние — `git status` пуст,
  tip `45313f3fb`, blob'ы совпадают с evidence.

## 8. Итог

| Пункт | Значение |
|---|---|
| Вердикт | **NEEDS_FIXES** |
| Блокирующие findings | `FCT-U1-R1-F1` (year guard принимает сумму за год; регрессия вердикта `supported → insufficient_evidence`) |
| Неблокирующие | `FCT-U1-R1-F2` (apply_validator без allowlist — hardening), `FCT-U1-R1-F3` (число 451 не воспроизводимо) |
| FCT-113 / FCT-192 | остаются **REVIEW** до U2 — согласен |
| Следующее ре-ревью | только исправленный `_year_conflict`/`_EXPLICIT_YEARS` + новые F1-тесты + unchanged 45/201; полный аудит не требуется |
