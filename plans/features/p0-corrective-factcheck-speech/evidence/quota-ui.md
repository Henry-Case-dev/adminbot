# QUOTA-UI-CLEANUP — evidence (ADDENDUM #3 §2.7, остатки в Inspector/API/UI)

Лейн: `QUOTA-UI-CLEANUP` (writer, после `QUOTA-REMOVAL` 73963d0c).
Кандидат: `git log -1 --format=%H` на коммите этого лейна.
Предыдущий кандидат backend-полосы: 73963d0c (A1–A6).

## 1. Что удалено

| Файл | Было | Стало |
|---|---|---|
| `web/api/speech.py` | `_composer_budget()` (обёртка над удалённым `mca_gates.composer_additive_budget_tokens()`, в проде всегда `0` через `except`) | удалена целиком |
| `web/api/speech.py` | `pr.core_selection_view(active_doc, source=source, budget_tokens=_composer_budget())` | `pr.core_selection_view(active_doc, source=source)` |
| `web/api/speech.py` | `pr.core_selection(doc, source=source, budget_tokens=_composer_budget())` в `_core_ref_from_doc` — **живой баг**: `core_selection` больше не принимает этот kwarg (A4), вызов падал `TypeError` и ломал предпросмотр Core в Inspector | `pr.core_selection(doc, source=source)` |
| `services/prompt_registry.py` | `core_selection_view(..., budget_tokens: int \| None = None)` + `del budget_tokens` — инертный параметр «уйдёт вместе с витриной» (так и было записано в docstring) | параметр и `del` удалены, docstring объясняет отсутствие квоты |

`web/app.js` и `web/index.html` **не менялись**: витрины аддитивного бюджета инструкций
там нет (проверено grep по `COMPOSER_LAYER_BUDGET`, `composer_budget`, `additive`, `1200`,
`композер` — совпадений по бюджету нет, остались только тексты про гейт
`unified_composer_enabled` и «тем же композером» в подписи предпросмотра).

## 2. Что сохранено осознанно (не «остаток квоты»)

`budget_excluded` как **состояние отображения** оставлен в `_STYLE_HINT_REASON_TITLES`,
`speechInspectorSkipText`, `speechStyleBuildStateText/StateClass/ReasonText`:
это честная диагностика технического исключения слоя при **реальном** переполнении окна
модели, и она прямо требуется пунктом S10 («не выдаётся за лимит владельца») и
проверяется `tests/ui_asap3_hint_speech_e2e.py` (строки 187–188, 384–387, 691–695,
ожидает текст «бюджет композитора»). Удаление подписей убрало бы честную причину и
сломало e2e вне рамок этого лейна. В комменте рядом с удалённой функцией это зафиксировано.

## 3. «Бюджеты» чатов не затронуты

`git diff --name-only` по этому лейну: `services/prompt_registry.py`,
`tests/test_asap3_acceptance.py`, `web/api/speech.py` (+ этот файл).
`web/app.js` (панель «Бюджеты», ключи `limits.chat_global_key_budget_tokens`,
`limits.chat_context_budget_tokens`) и `web/index.html` — без изменений.

## 4. S10 обновлён

Расхождение брифа с деревом: теста `test_s10_composer_style_layer_exclusion_is_visible`
больше нет — он переименован в `test_s10_composer_style_layer_has_no_local_quota`
ещё в 73963d0c (A3). Обновлён именно он (новый контракт), плюс добавлен регресс
на удаление проводки:

- `test_s10_composer_style_layer_has_no_local_quota` — при `COMPOSER_LAYER_BUDGET_TOKENS=1`
  слой Style Policy **рендерится**, `skip_reason` пуст, `policy.hint` физически присутствует
  в `manifest.system`, ни один слой не имеет `skip_reason == "budget_excluded"`,
  `budget_excluded` нет в `pc.SKIP_REASONS`, а исключения самой подсказки — только `user_limit`.
- `test_s10_no_composer_budget_plumbing_in_inspector` (REGRESSION) — у `web.api.speech`
  нет `_composer_budget`; в сигнатурах `core_selection_view`/`core_selection` нет
  `budget_tokens`; срез Core в Inspector не содержит ни ключа, ни строки `budget_tokens`;
  реальный путь предпросмотра `_core_ref_from_doc` собирается (падал до фикса).
- `test_s10_budget_exclusion_is_not_disguised_as_user_limit` оставлен как проверка
  «реальное переполнение окна показывается честно» (отдельно от квоты инструкций).

TEST-LIFECYCLE: REGRESSION owner=P0/QUOTA-UI-CLEANUP (ADDENDUM #3 §2.7).

## 5. Прогоны (локально, без сети/прода)

| Команда | Результат |
|---|---|
| `py -3 -m pytest tests/test_asap3_acceptance.py -q` | 8 passed |
| `py -3 -m pytest tests/test_quota_removal_composer.py -q` | 7 passed |
| `py -3 -m pytest tests/test_quotes_modes.py -q` | 29 passed |
| вместе (44) | 44 passed, 3.31s |
| `py -3 -m pytest tests/test_soul1_core_registry_api.py tests/test_soul1_core_doc_text.py tests/test_soul1_composer_layers.py -q` (соседние к `prompt_registry`) | 32 passed |
| `.venv\Scripts\python.exe tests/ui_asap3_hint_speech_e2e.py` | PASS: 10 проверок |
| `node --check web/app.js` | OK (файл не менялся) |

Playwright есть только в `.venv` (системный `py -3` без него) — e2e запускался
через `.venv\Scripts\python.exe`.

## 6. Отклонение от рамок (для Reviewer/родителя)

`services/**` был помечен «только чтение», но пункт 1 брифа прямо требует, чтобы
`core_selection_view` больше не принимал инертный аргумент, а сам файл в docstring
назначал это удаление «параллельной UI-полосе». Сделана точечная правка сигнатуры
(11 строк, без изменения поведения выбора): единственный вызывающий
(`web/api/speech.py`) обновлён в этом же коммите, других вызовов с `budget_tokens`
нет (проверено grep по `web/`, `services/`, `tests/`, `scripts/`, `tools/`).
