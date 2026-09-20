# Аудит раунда 10.24 — F20 `budget-overrides-merge-fix-round1024` (шаг 5)

- **Ревьюер:** @Reviewer
- **Коммит:** `070f31c` (HEAD работы) · База сравнения: `070f31c^`
- **Спека/ADR/задачи:** `spec.md`, `ADR-1024-21.md`, `tasks.md` (T-2353…T-2359)
- **ТЗ:** `plans/current_task.md`, строка 404 (критический баг бюджетов). Секреты не цитируются (R17/R18).
- **Артефакты коммита:** `web/api/routes.py` (+12/−3), `tests/test_budget_overrides_merge_round1024.py` (+401). **Δ DDL = 0, Δ каталога = 0.**

**Статус: Approved**

Итог: первопричина устранена точечно и доказательно. База merge значений в `POST /api/config` (+`X-Chat-Id`) переведена с матрицы прав `perm_overrides` на значения `root["overrides"]`; матрица прав осталась **единственным** потребителем для `effective_matrix`/`can_edit_param` и в запись не попадает. Namespace-ы окончательно разведены. Все обязательные сценарии (a)–(i) покрыты реальным TestClient через реальный роут с in-memory `chat_params`; тесты **не тавтологичны** — на до-фиксовом коде (a)/(b)/(d) падают. Полный pytest: **7510 passed, 0 failed**; `node --check web/app.js` — OK; `git diff --check` — чист. Инварианты `manual-overrides-immutable`, R16/R17/R18, `physical-two-call` не нарушены.

---

## Findings

Блокирующих дефектов нет. Ниже — незначительные наблюдения, не влияющие на приёмку фикса.

### [Severity: Low] Тест привязывается к `chats[0]`, а не к целевому `chat_id`

- **Файл:** `tests/test_budget_overrides_merge_round1024.py:56-58`
- **Локация:** `SEED_OVERRIDES = json.loads(...)["chats"][0]["overrides"]`
- **Проблема:** фикстура берёт нулевой элемент массива `chats`, а не ищет чат по `chat_id == -1002661910336`. Сейчас порядок совпадает (проверено: `chats` = 1, `chat_id` = `-1002661910336`, `n=8`, `budget=-1`), но при добавлении/перестановке чатов в `config/chat_settings_seed.json` тест молча начнёт валидировать другой набор.
- **Почему не блокирует:** контрактные утверждения (b) содержат явные `overrides[K_BUDGET] == -1` и `len == len(SEED_OVERRIDES)+1`, т.е. даже при сдвиге индекса проверка `-1` сохранит смысл семантически. Это техдолг читаемости теста, не корректности фикса.
- **Рекомендация (не обязательно в F20):** выбирать seed-чат по `chat_id` из константы `CHAT`, а не по индексу.

### [Severity: Low] 403-ветка (d') проверяется через мок, а не через реальную матрицу

- **Файл:** `tests/test_budget_overrides_merge_round1024.py:337-343`
- **Проблема:** `test_permission_gate_still_blocks_403` подменяет `access_srv.can_edit_param` на `lambda: False`. Спека §7 (d) в качестве примера просила «не-глобальный админ получает 403 на ключ с ограничением, глобальный — 200», т.е. e2e по реальной матрице.
- **Почему не блокирует:** фактическое требование — «`perm_overrides` доходит до `effective_matrix` и гейтит запись» — закрыто тестом (d) через spy на `access_srv.effective_matrix` (подтверждён `seen[K2] == perm[K2]`), а общий RBAC-403 для `POST /api/config` покрыт существующим `tests/test_webapp_api.py` (множество 403-кейсов). Дубль e2e не приносит новой доказательной силы.
- **Рекомендация:** при желании — e2e с реальным moderator/local-admin контекстом и `perm_overrides`-ограничением.

### [Info] База значений читается через `get_all_chat_params(chat_id)` без `pg=cache.pg`

- **Файл:** `web/api/routes.py:481`
- **Проблема:** чтение `root` идёт по процесс-кэшу, а не напрямую из PG (в отличие от DELETE `:734`, где передаётся `pg=cache.pg`).
- **Почему не блокирует:** путь не менялся F20 (существовал до коммита), риск отмечен самой спекой §8 R6, изоляция держится `expected_updated_at`/409 и инвалидацией кэша при каждом успешном `set_chat_params`. Это заявленное «возможное упрочнение», а не регресс.

_Примечание: обязательный по регламенту запрос Context7 выполнить не удалось — API-ключ отклонён (`Invalid API key`); выводы сделаны по коду, спеке/ADR и прогонам._

---

## Контракт: чекбоксы spec §4 / tasks.md

### Merge и namespace (spec §4.1–4.2)
- [x] База merge значений = `root["overrides"]`: `value_overrides = dict(root.get("overrides") or {})` (`routes.py:488`); **не** `perm_overrides`.
- [x] `perm_overrides` используется ТОЛЬКО для `effective_matrix` (`routes.py:487,504-506`); в запись `{"overrides":..., "meta":...}` (`:534-535`) не попадает.
- [x] `new_overrides = dict(value_overrides); new_overrides.update(patch_overrides)` (`:529-530`) — только ключи текущего запроса.
- [x] Не-целевой namespace — отдельная переменная `perm_overrides`, старый `chat_overrides` полностью устранён (grep: остатков нет).

### Сценарии (spec §7)
- [x] (a) два последовательных save сохраняют оба ключа — `test_two_sequential_saves_preserve_all_keys`.
- [x] (b) 8 seed-ключей целевого чата (в т.ч. `-1`) выживают после UI-save — `test_seed_overrides_survive_ui_save` (проверено: seed = 8 ключей, `-1` = безлимит, `chat_id` совпадает).
- [x] (c) паритет с DELETE — удаляется ровно один, повторный → 404 — `test_delete_parity_removes_exactly_one`.
- [x] (d) `perm_overrides` не утекает в `overrides`, матрица применяется — `test_perm_overrides_not_leaked_and_matrix_used` (+403-ветка `test_permission_gate_still_blocks_403`).
- [x] (e) `updated_at`/409 — `test_updated_at_conflict_and_ok`.
- [x] (f) `per_chat=false` (глобальный путь) не задевает per-chat — `test_global_path_untouched_per_chat`.
- [x] (g) GET показывает сохранённое (`chat_source="chat"`, `global_value`, `value`) — `test_get_shows_saved_chat_value`.
- [x] (h) идемпотентность/no-op без history-строки — `test_idempotent_repeat_no_history`.
- [x] (i) пустой/неизвестный/секретный ввод → 422 — `test_invalid_inputs_422`.

### Инварианты
- [x] `manual-overrides-immutable`: ручное значение не разрушается последующей записью (тесты a/b).
- [x] R16 (аддитивность API): формат ответа `{"updated", "chat_id", "updated_at"}` не изменён.
- [x] R17/R18 (секреты): лог `routes.py:543-544` — только `chat_id`, счётчик ключей, `user.id`; `keys.*` → 422 (тест i). Секреты в отчёт не цитируются.
- [x] `per_chat=false` → 422 (код `routes.py:500-503`) — не изменён коммитом.
- [x] 409/`ChatParamsConflict` (`:538-542`) — не изменён.
- [x] Глобальный путь `_post_config_global` (`:758+`) — не изменён (диффом не затронут).
- [x] Паритет GET `:372-377` и DELETE `:728-739` — не изменены, соответствуют POST.
- [x] `physical-two-call`: LLM-конвейер не затронут (путь сохранения — не LLM-вызов), Δ вызовов = 0.
- [x] Δ DDL = 0, Δ каталога = 0 (коммит = только `routes.py` + новый тест).
- [x] Feature flag не вводится (D7): поведенческий фикс, kill-switch — `git revert`.

---

## Тесты / прогон

| Проверка | Команда | Результат |
|---|---|---|
| Целевой файл | `pytest tests/test_budget_overrides_merge_round1024.py -q` | **10 passed** |
| Связанные (webapp/api/chat_params/config/access/routes/parity) | `pytest test_webapp_api.py test_chat_params.py test_config_cache.py test_access.py test_routes_helpers.py test_webapp_parity_smoke.py -q` | **238 passed** |
| Полный прогон | `pytest -q` | **7510 passed, 0 failed** (97.03s) |
| JS-синтаксис | `node --check web/app.js` | OK |
| Whitespace | `git diff --check 070f31c^ 070f31c` | чисто |

**Не тавтологичны:** на до-фиксовом коде (a) терял `K1`, (b) терял seed-ключи, (d) переносил `perm_overrides` в `overrides` — все три утверждения падали бы. Способ проверки — реальный `TestClient` + реальные роуты `post_config`/`get_config`/`delete_chat_param`; подменено только хранилище `chat_params` (его namespace-семантика зеркалит `set_chat_params`, включая `ChatParamsConflict`).

---

## Заключение

Критический фикс F20 выполнен в полном объёме и соответствует `spec.md`/`ADR-1024-21` без отклонений. Дифф минимален и обозрим, namespace-ы разведены, регресс-тесты доказательно ловят именно исходный баг, полный pytest зелёный. Задача **T-2358 закрыта**. Остаётся T-2359 (@DevOps) — live-проверка на целевом чате.

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше (T-2359 @DevOps).
