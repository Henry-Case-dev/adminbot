# I1 — PM-привязка кандидата 76d60678 и сверка книжного пробела SXR-I1-02

Документ PM. Код, production и scope (`plans/progress_scope.json`) не менялись;
зафиксированы только карта требований и evidence. Эпик DONE не отмечается.

## 1. Кандидат

| поле | значение |
|---|---|
| код и тесты | `76d6067893238cb71e66cca73470e82c32762737` (76d60678) |
| docs | `87df150d8dce071eb67f1fec6251eac15bb0d368` (аддендум I1 + binding) |
| база | `d20a7f730715ba9e9cba7673c0557794979be339` (production 2.58.199) |
| ветка / worktree | `smart/i1-journal` / `...-eef05388` |
| предыдущий кандидат | `a3841613` — Needs Fixes (F1 блокер, F2/F3 малые) |
| DDL / схема / спул-формат / новые таблицы | 0 изменений |
| deployed | **false** — кандидат не выкатывался, production не трогался |

Область изменений: `services/meme_initiative.py` (+72), 
`tests/test_evol014_meme_initiative.py` (+79), docs-аддендум.

## 2. Независимое ревью

`evidence/review-i1-76d60678.md` — **Approved (REVIEW-ready)**, F1/F2/F3 закрыты:

- F1: при отказе writer'а под `serialized()` выполняется `conn.rollback()`,
  исходное исключение пробрасывается; reentrant-ветка чужую транзакцию не трогает.
- F2: `busy_timeout_ms` берётся из `PRAGMA busy_timeout` соединения writer'а
  (при недоступности `JOURNAL_BUSY_TIMEOUT_MS=5000`); файловый sync-путь — 250.
- F3: durable-тест `test_spool_drain_deduplicates_already_written_attempt_id`.

Прогоны кандидата: **7 новых тестов passed**, `test_meme_init_diagnostics.py`
**44 passed**, `test_evol014_meme_initiative.py` **1 failed / 67 passed**
(единственное падение `test_factory_prompt_is_exact_literal_and_registered`,
pre-existing — то же на базе `d20a7f73`). Мутации ловят F1 (`conn.rollback()`) и
F3 (`INSERT OR IGNORE` → `INSERT`); мутации sync-таймаута и обхода `serialized()`
переиспользованы с `a3841613` (код не менялся).

## 3. Статус SXR-I1-01 в карте

`SXR-I1-01` (20 строк карты: 10 записей инвентаря + 10 prose-строк §I1) →
**READY_FOR_LIVE**, `live_required: true`, `live_when: postdeploy` с
`postrelease_wait` (nonblocking, owner — агенты) и candidate-bound evidence:
review-вердикт Reviewer + implementation-evidence (`addendum-i1-76d60678.md`).

Почему не `REVIEW`: все acceptance-строки I1 включают postdeploy-наблюдение,
а гейт запрещает postdeploy-only строке маскироваться под обычную REVIEW
(`postdeploy-only requirement must use READY_FOR_LIVE or VERIFIED`). REVIEW-уровень
приёмки уже установлен вердиктом Reviewer; машинный статус отражает только
оставшееся production-подтверждение. Прецедент в этом же эпике — `SXR-A1-04`.

`postrelease_wait`:

- **reason** — реализация и тесты одобрены на 76d60678; оставшееся
  доказательство (поведение журнала под реальным контеншном за единственным
  writer'ом) существует только после деплоя.
- **trigger** — первый реальный контеншн за журнал мемов после деплоя.
- **next_check** — в логе нет 5-секундных заморозок вызывающего и повторов
  `OperationalError`; допустимый исход — успешная запись единым писателем либо
  строка `attempt spooled` с `busy_timeout_ms=5000` и
  `error=... [SQLITE_BUSY]`, после чего спул опустошается.
  Источник формулировки — review-i1-76d60678.md, разделы «Строки» и
  «Следующее действие» (строки 84–87, 99–101): «допустим READY_FOR_LIVE»,
  «Подтверждение после релиза: следующий реальный контеншн…», «откат обычный
  релизный».
- **owner** — агенты: DevOps выполняет postdeploy-наблюдение, Reviewer проверяет
  привязку следующего доказательства.
- **contract_ref** — `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md:1007-1050`
  (§I1 «Журнал инициативы и мемов: OperationalError»).

## 4. SXR-I1-02 — книжный пробел закрыт сверкой, требование не выдумано

Ревью-артефакт (строки 76–77, 88) сообщает: «срез S9 ссылается на SXR-I1-02,
строки с таким req_id в requirements-map.json нет». Проверка показала, что это
ошибка поиска, а не отсутствие требования:

- `SXR-I1-02` **существует в карте** — три строки в `additional_requirements`
  (секция prose-only обязательств), `source_id` `MAN-SXR-I1-02-1040`,
  `-1046`, `-1048`, `slice: S9-EVENT-PIPELINE`, `status: PENDING`,
  `live_required: false`.
- Точные owner-анкоры (owner_inputs §I1, строки 1040/1046/1048):
  «Не создавать четвёртый fallback, новый журнал или дополнительное хранилище
  вместо устранения первопричины», «Не очищать spool и не удалять старые записи
  ради исчезновения warning», «Не увеличивать вероятность автоматической
  инициативы на production для проверки». Хеши строк совпадают с источником.
- Ссылка среза `S9-EVENT-PIPELINE` на `SXR-I1-02` **корректна** и сохраняется;
  дубликат строки создавать нельзя (это удвоило бы счётчик и разошлось бы с
  owner-анкором).
- Проверяющий искал req_id в `items` (генерируемый инвентарь заголовков/списков);
  запреты §I1 — prose, они по построению живут в `additional_requirements`.
  Гейт читает оба массива, поэтому «невидимость» была только визуальной.

Статус остаётся **PENDING**: отдельного candidate-bound вердикта по трём
запретам нет. Косвенные факты кандидата (DDL 0, спул-формат не менялся,
код вероятности инициативы не тронут — `binding-i1-a3841613.md`, §3–§4)
не подменяют независимую проверку требования.

## 5. Восстановленные evidence-артефакты

В master отсутствовали два файла, на которые ссылается review-вердикт:

- `evidence/binding-i1-a3841613.md`
- `evidence/addendum-i1-76d60678.md`

Оба взяты **без правок** из docs-коммита `87df150d`
(`git checkout 87df150d -- …`), то есть это ровно те документы, которые
ревьюер видел в кандидатной ветке; sha256 зафиксированы в карте.

Незакрытый provenance-пробел: `review-i1-a3841613.md` (вердикт Needs Fixes по
предыдущему кандидату) в репозиторий не коммитился ни в одной ветке — как
и указано в хаускипинге аддендума. Содержание чужого артефакта не
переписывалось; его тезисы доступны только в пересказе аддендума.

## 6. Проверки

- `--stage plan`: см. раздел 7.
- scoped `--stage review --slice S9-EVENT-PIPELINE --candidate 76d60678`:
  строки I1 зелёные; остаточные ошибки дают только `PENDING`-строки того же
  среза (`SXR-I1-02`, `SXR-I2-01`, `SXR-I2-02`), которые этим кандидатом не
  реализовывались и не ревьюились. Срез S9 объединяет три этапа (I1/I2/I4),
  поэтому полный зелёный scoped-гейт возможен только после I2.

## 7. Результаты гейтов

Команды (venv `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, repo-root
`C:\Code\Python\adminbot`, гейт `C:\Users\main\.config\opencode\tools\requirements_gate.py`):

1. `check --map …/requirements-map.json --stage plan --repo .`
   → `stage=plan inventory=509 manual=359 scoped=0 errors=0`
2. `check --map …/requirements-map.json --stage review --slice S9-EVENT-PIPELINE
   --candidate 76d6067893238cb71e66cca73470e82c32762737 --repo .`
   → `stage=review inventory=509 manual=359 scoped=40 errors=20`

Разбор остаточных 20 ошибок scoped review:

| req_id | строк | статус | причина |
|---|---|---|---|
| `SXR-I2-01` | 13 | PENDING | fresh stream lag — кандидатом не реализовывался |
| `SXR-I2-02` | 4 | PENDING | reason codes — кандидатом не реализовывался |
| `SXR-I1-02` | 3 | PENDING | запреты §I1 — отдельного вердикта нет (раздел 4) |
| `SXR-I1-01` | 20 | READY_FOR_LIVE | **ошибок 0**: review+implementation evidence на 76d60678, `approved_postrelease_wait` совпадает `postrelease_wait` |

То есть ни одной ошибки, относящейся к SXR-I1-01, нет. Полностью зелёный
scoped-гейт среза S9 возможен только после реализации и ревью I2, либо после
выделения I1 в отдельный срез — структурная правка среза в эту задачу не
входила (тот же эффект уже существует в прецеденте S3-EVIDENCE: scoped review
даёт 40 ошибок по PENDING-строкам C2/C3).

