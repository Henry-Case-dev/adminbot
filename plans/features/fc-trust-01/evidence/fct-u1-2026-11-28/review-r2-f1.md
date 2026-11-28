# REVIEW R2 (адресное) — FC-TRUST-01 / U1: исправление `FCT-U1-R1-F1`

Роль: Reviewer (независимый). Дата: 28.11.2026.
Объём: только закрытие `FCT-U1-R1-F1` (4-значная сумма принималась за год), регрессия
затронутой зоны и честность evidence. Полный повторный аудит U1 не выполнялся;
неизменённые части U1 опираются на проверки `review-r1.md`.

## 0. Кандидат, база, состояние дерева (проверено фактически)

| Поле | Значение |
|---|---|
| Ветка | `feat/fct-u1-assertion-binding-2026-11-28` |
| Tip кандидата | `49d8a51115794ce7a733f3d96c5df3f3fddfd970` |
| Corrective-коммит | `0fc7201ea1bcf7a9b74dbe7f5febf260442d8da1`, родитель — `45313f3fb` |
| База / прод | `a2195fe3f9289d75461f27c7278d52779e2b812a` (2.58.272), предок кандидата |
| Worktree | `…\WorkspaceData\worktrees\c742e4de9e92c489\fc-trust-01-u1-3f69efb80e96-d491fedf` |
| Состояние | `git status --porcelain` пуст до ревью; blob `search_aggregator.py` = `59632eb0` |
| Контракт | `decisions.md`, sha256 `69b3ed93…d0af` — совпал |
| Fix diff | только `services/search_aggregator.py` (+36/−3), `tests/test_fc_trust_relation_binding.py` (+54), `plans/backlog.md` (+8) |

## 1. ВЕРДИКТ

**APPROVED_FOR_RELEASE_PREPARATION** — `FCT-U1-R1-F1` закрыт; блокирующих IN_SCOPE
finding'ов нет. FCT-113 (4 строки) и FCT-192 остаются **REVIEW** до U2 (см. §8).

## 2. Repro через реальный путь (claim_relevance → merge_claim_coverage)

Тезис `«ЭкоПром снизила выбросы на 12% в 2024 году.»`, `timeframe="2024"`,
`claim_relevance(..., require_anchor=True)` → `fsp.ClaimEvidence` → `fsvc.merge_claim_coverage`.

| Пассаж | Кандидат `0fc7201ea` | Старое поведение `45313f3fb` | База `a2195fe3f` |
|---|---|---|---|
| «…стоит 2025 рублей…» | supports/direct, merged **supported** | qualifies/indirect, merged insufficient_evidence | supports/direct, supported |
| «…стоит 2025 млн рублей…» | supports/direct, supported | qualifies/indirect, insufficient_evidence | supports/direct, supported |
| «…стоит $2025 млн…» | supports/direct, supported | qualifies/indirect, insufficient_evidence | supports/direct, supported |
| «сэкономлено 2025 тыс. тонн» | supports/direct, supported | qualifies/indirect, insufficient_evidence | supports/direct, supported |
| «в 2023 году» (реальный другой год) | **qualifies/indirect + `time:year_conflict`** | то же | supports/direct (функции нет) |
| «в 2024 году» (тот же год) | supports/direct | supports/direct | supports/direct |

Дополнительно независимо проверены формы вне тестов: `2025%`, `₽2025`, `2025 руб.`,
`2025 долларов` → не годы (`_explicit_years` = `()`); `2025 году`, `2025 г.`,
`с 2023 по 2024`, `2024 году` → годы (`(2025,)` / `(2023,2024)` / `(2024,)`).
Год внутри URL по-прежнему вырезается: `https://…/2023/report` + сумма → конфликта нет.

**Вывод:** сумма ведёт себя ровно как «пассаж без года» (паритет с базой), реальный
другой год не ослаблен, контроль решений §2.1 п.1/§2.4 восстановлен.

## 3. Дискриминирующие тесты и мутации (свои, не по evidence)

Тесты читались: 4 параметра `test_amount_instead_of_year_behaves_like_no_year`
(«2025 рублей», «2025 млн рублей», `$2025 млн`, «2025 тыс. тонн»),
`test_amount_instead_of_year_keeps_supported_verdict` (сквозь merge) и
`test_amount_and_real_other_year_still_conflict` — все на production-функциях,
не тавтологии.

| Мутация на кандидате | Результат |
|---|---|
| `_year_is_quantity` → `return False` (вернуть старое поведение) | **5 failed / 27 passed** — ровно 4 amount-параметра + merge-тест |
| `_year_conflict` → `return False` (выключить конфликт) | **6 failed / 26 passed** — прежние conflict-тесты, planner-wrapper, amount+real-year |

Откат `git checkout HEAD -- services/search_aggregator.py`; после каждой —
`git status` пуст, blob `59632eb0`. Значит новые кейсы падают при возврате старого
поведения и не проходят «вхолостую».

## 4. Прогоны

| Команда | Результат |
|---|---|
| `pytest tests/test_fc_trust_relation_binding.py -q` | **32 passed** |
| `pytest tests/test_fc_trust_assertion_kind.py tests/test_fc_trust_relation_binding.py -q` | **51 passed** |
| 6 файлов (`s1_contract`+`retrieval`+`verdict`+`render`+2 U1) | **207 passed** |
| 62 файла `factcheck|search|voice|trust|temporal` одним прогоном (кандидат) | **6 failed / 1503 passed** |
| те же 60 файлов на базе `a2195fe3f` (без 2 новых U1-файлов) | **6 failed / 1452 passed** |
| те же 60 файлов на кандидате | **6 failed / 1452 passed** (тот же набор) |

Набор падений **идентичен на базе и кандидате**:
`test_asap_fc_voice_l1_decision_profile::test_direct_service_l1_payload_gets_profile_from_turn_frame`,
3× `test_rlr_factcheck_numeric_stage`, 2× `test_selfdiag_corrective_research`.
rlr-тесты по отдельности на кандидате — **11 passed**, т.е. это order-dependent
предсуществующая хрупкость, не регрессия кандидата (подтверждено базой).

## 5. Честность evidence (замечание, не блокер)

* Evidence заявляет широкий прогон «1506 passed / 3 failed» суммой четырёх частей;
  это воспроизводимо **только** в разбиении на части. Тот же список одним процессом
  даёт 6 failures: 3 rlr-падения всплывают из-за порядка тестов и **также падают
  на базе**. Число «3» корректно для их инвокаций, но занижает известную
  order-dependent хрупкость; сам кандидат регрессии не даёт.
* `raw/*.txt` части сохранены как binary в git (UTF-16/CRLF) — читаемость ниже, но diff
  воспроизводим: `git diff 45313f3fb 0fc7201ea`.
* F3 закрыт: для широкого прогона записаны команда и списки файлов (`raw/f1-runs.md`,
  `raw/broad-f1-part{1..4}-files.txt`), проверял существование всех 62 путей.
* Карта ещё ссылается на старую implementation.md (`sha256 8b2d61ed…`); текущий файл —
  `29022aed…` (добавлен §7). `next_execution` в 4 строках FCT-113/FCT-192 тоже ещё
  указывает на r1 NEEDS_FIXES — это административная правка Orchestrator, не дефект кода.

## 6. Границы diff и канон инструкций

* Corrective не трогает `factcheck_service.py`, `temporal_factcheck.py`, рендер, DDL,
  флаги, `prompt_registry.py`, `relation_evidence.py` — подтверждено `git show --stat`.
* Полный diff `a2195fe3f..49d8a5111` затрагивает только U1-файлы (`temporal_factcheck.py`,
  `search_aggregator.py`, `prompt_registry.py` — метка/печать), тесты и evidence.
* Отрендеренный `temporal.analyst` (база vs кандидат): 3639 → 4341 символов; `difflib`
  даёт только расширения схемы и правила (14)/(15) — ни одна инструкция/правило не
  удалены и не урезаны. Квот инструкций нет (правило владельца 24.10 соблюдено).

## 7. Findings

| ID | Severity | Scope | Суть |
|---|---|---|---|
| `FCT-U1-R1-F1` | — | — | **ЗАКРЫТ**: сумма больше не считается годом; паритет с базой, реальный год конфликтует. |
| `FCT-U1-R2-N1` | minor | BACKLOG | Список префиксных валют — `$ € ₽`; суммы вида `£2024`/`¥2024`/`₸2024` всё ещё могут считаться годом. Направление консервативное (ложное ослабление, не ложное подтверждение), именованные в F1 формы покрыты; не блокирует. |
| `FCT-U1-R2-N2` | minor | BACKLOG (evidence) | Широкий прогон «3 failed» — сумма 4 частей; единый прогон даёт 6 order-dependent падений, идентичных базе. Кандидату не приписывать. |
| `FCT-U1-R2-N3` | minor | BACKLOG (admin) | `requirements-map.json` хранит устаревший sha implementation.md и `next_execution` r1; обновить при закрытии ревью. |

## 8. Рекомендация по статусам (карту не правил)

* **FCT-113, все 4 строки** (`requirements-map.json`: `L00092`–`L00095`) — оставить
  **REVIEW**. Структурная ось реализована и проверена, но наблюдаемое acceptance
  «четыре значения в одной части вердикта» требует merge-стадии U2; VERIFIED был бы ложным,
  PENDING занижал бы уже сделанное.
* **FCT-192** — оставить **REVIEW**, не PENDING: детерминированная часть (year conflict,
  форма `evidence_quotes`) поставлена и подтверждена, но «связка claim↔passage оценена по
  существу» (дословная привязка, понижение, `relation_binding`, живой replay) — U2/S4.
  VERIFIED без U2 и независимого ревью U2 невозможен.

## 9. Ограничения этой проверки

* Живой LLM-replay и UI не выполнялись: изменение детерминированное, рендер/публикация не
  затронуты; наблюдаемый эффект U1 наступает после U2.
* Новый тест-файл на базе повторно не запускался: RED доказывался собственной мутацией
  (`_year_is_quantity`→False) и сравнением версий кода на реальном пути, что строже для
  проверяемого поведения.
* Для сравнения с базой создавался временный worktree `fc-trust-01-u1-r2-base-…`; после
  прогонов он удалён (`git worktree remove`, без `--force`), временные скрипты вне
  репозитория удалены. Продукт/тесты/ветка не изменялись, кроме этого артефакта ревью.

## 10. Точные команды (воспроизведение)

```
$py = C:\Code\Python\adminbot\.venv\Scripts\python.exe
$py -m pytest tests/test_fc_trust_relation_binding.py -q
$py -m pytest tests/test_fc_trust_assertion_kind.py tests/test_fc_trust_relation_binding.py -q
$py -m pytest tests/test_fc_trust_s1_contract.py tests/test_fc_trust_retrieval.py ^
    tests/test_fc_trust_verdict.py tests/test_fc_trust_render.py ^
    tests/test_fc_trust_assertion_kind.py tests/test_fc_trust_relation_binding.py -q
# широкий: список из evidence raw/broad-f1-files.txt
$py -m pytest @files -q
```
