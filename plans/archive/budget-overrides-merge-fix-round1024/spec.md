# spec.md — F20 `budget-overrides-merge-fix-round1024`

> **Раунд:** 10.24 (UPD5-critical) · **Приоритет:** P0 / Critical · **Шаг 2 @Architect** · **Тип:** backend-багфикс (merge per-chat значений)
> **ТЗ:** `plans/current_task.md`, строка 404 · **Задачи:** `tasks.md` T-2353…T-2359 · **Baseline:** HEAD `00eab85` (прод `4314ea4`)
> **ADR:** `ADR-1024-21.md` (AMEND ADR-1019-8, AMEND ADR-1012-1) · **Backlog:** 10.24, F20
> **Границы:** F22 `budget-data-repair-round1024` (ремонт уже утерянных данных) · F21 `budget-global-toggle-round1024` (master-тумблер). F20 только **прекращает потерю**, данные не ремонтирует.

---

## 1. Цель

Устранить **корневую причину потери per-chat значений** при одиночном сохранении из мини-аппа:

Сейчас `POST /api/config` (с `X-Chat-Id`) берёт за базу merge **матрицу прав** (`perm_overrides`) вместо **значений** (`overrides`) и целиком перезаписывает namespace `overrides`. Любой одиночный save (клиент шлёт один ключ за POST) уничтожает все прочие per-chat значения. У целевого чата `-1002661910336` так стираются 8 seed-ключей (`config/chat_settings_seed.json:11-20`), включая бюджет `-1` (безлимит). После этого бюджетный гейт упирается в глобальный cap → `NoApiKeyForChat('budget')` → бот отвечает фразой-заглушкой `content.no_key_reply` («самоизлечение» сидом при рестарте даёт петлю: рестарт вернул → следующая правка снова стёрла).

**Итог после фикса:** одиночный save сохраняет только целевой ключ, **не трогая** остальные per-chat значения; `perm_overrides` живёт отдельно и продолжает работать как матрица прав.

---

## 2. Что уже есть (координаты, подтверждены)

| Зона | Координата | Роль |
|---|---|---|
| **Баг merge (база)** | `web/api/routes.py:482` — `chat_overrides = dict(root.get("perm_overrides") or {})` | База merge взята из **матрицы прав**, а не значений |
| **Баг merge (перезапись)** | `web/api/routes.py:523-524` — `new_overrides = dict(chat_overrides); new_overrides.update(patch_overrides)` | В значения попадает ∪ матрицы прав |
| **Баг merge (запись)** | `web/api/routes.py:528-529` — `set_chat_params(..., {"overrides": new_overrides, "meta": meta})` | Namespace `overrides` **полностью** перезаписывается |
| **Легитимное чтение матрицы** | `web/api/routes.py:498-500` — `effective_matrix(item.key, db_overrides.get(item.key), chat_overrides.get(item.key))` | Единственное место, где `perm_overrides` нужен в POST |
| **Эталон значений (GET)** | `web/api/routes.py:372-377` — `overrides = chat_root.get("overrides") or {}` | Показывает per-chat значение при `per_chat=True` |
| **Эталон значений (DELETE)** | `web/api/routes.py:728-733` — `overrides = dict(root.get("overrides") or {}); overrides.pop(key)` | Удаляет ровно один override, merge `meta` |
| **Эталон merge (сид)** | `services/chat_settings_seed.py:156-179` — `current = dict(root.get("overrides") or {})` → merge → `set_chat_params` | Читает значения из `overrides`, семантику сохраняем |
| **Матрица прав (запись)** | `web/api/access.py:443-447` — `set_chat_params(..., {"perm_overrides": {key: value}})` | Отдельный endpoint; в F20 **не меняется** |
| **Клиент (одиночный save)** | `web/app.js:4454-4461` — `items:[{key,value}]` + `updated_at`; `global` при `per_chat=false` | В F20 **не меняется** |
| **Последствие** | `services/chat_usage.py:61-65` (env-cap 100/500k) → `services/llm_client.py:404-420` (`NoApiKeyForChat('budget')`) → `services/direct_chat_service.py:767-781` → `services/sandbox_reply.py:8-11` | Объясняет «заглушку» |
| **Петля сида** | `bot.py:1049-1051` + `services/chat_settings_seed.py` | Сид возвращает overrides на рестарте; правка снова стирает |

**Опорные контракты (не менять):**
- `services/chat_params.py:304-361` — `set_chat_params` пишет namespace **целиком** (`new_root[ns] = dict(patch[ns])` для `overrides/gates/keys/perm_overrides/meta`), одна транзакция (UPDATE + history + NOTIFY), `expected_updated_at` → `ChatParamsConflict`.
- `services/chat_params.py:275-301` — `get_all_chat_params(chat_id, pg=None)` возвращает root-лейаут `{v, overrides, gates, keys, perm_overrides, meta}`.

---

## 3. Разделение пространств имён (ключевая модель)

Это **два независимых namespace** в одном `chat_params`-root. Их смешение и есть баг.

| Namespace | Что хранит | Кто пишет | Как читается | Семантика |
|---|---|---|---|---|
| **`overrides`** | **Значения** per-chat настроек (`limits.*`, `memory.*`, `flags.*`, `prompts.*` …) | `POST /api/config` (+X-Chat-Id), `DELETE /api/config/chat/{key}`, `services/chat_settings_seed.py` | GET `routes.py:372-377`; `chat_params.get_chat_param`; `worker_settings`/`chat_usage` резолв | Ручное per-chat значение; удаляется только явным DELETE. **`manual-overrides-immutable`** |
| **`perm_overrides`** | **Матрица прав**: chat-скоуп `view_roles`/`edit_roles` для конкретного ключа | `web/api/access.py:443-447` (`PUT` прав чата) | GET `routes.py:348-350`, `:364-367`; POST `routes.py:498-500` → `effective_matrix` | Управление RBAC; **никогда не является значением настройки** |

**Инвариант `manual-overrides-immutable`:** ручные per-chat **значения** из `overrides` не могут быть разрушены последующей записью другого значения; единственный путь удаления — `DELETE /api/config/chat/{key}`. Не путать с `perm_overrides` (матрица прав): её и `overrides` нельзя сводить в одно пространство.

---

## 4. Требуемое поведение (контракт)

### 4.1. `POST /api/config` с `X-Chat-Id` — merge по значениям
1. Прочитать root чата (`root`).
2. **База merge значений** = `root["overrides"]` (значения), **не** `root["perm_overrides"]`.
3. `new_overrides = base ∪ patch_overrides` (только ключи текущего запроса; остальные сохраняются).
4. Записать `{"overrides": new_overrides, "meta": merged_meta}` через **одну** транзакцию `set_chat_params`.
5. `perm_overrides` в запись **не попадает** и не смешивается с `overrides`.

### 4.2. `perm_overrides` — только матрица прав (read-only в POST)
`perm_overrides` используется **исключительно** для `effective_matrix`/`can_edit_param` (проверка права на редактирование ключа) и **не влияет** и **не переносится** в значения. После фикса проверка прав для `-1002661910336` не должна измениться.

### 4.3. Глобальный путь (`per_chat=false`) — без изменений
`_post_config_global` (`routes.py:752+`) и клиентская ветка `app.js:4451-4461` (`global:true`, без `X-Chat-Id`) работают **байт-в-байт как раньше**; per-chat `overrides` не задеваются (кроме случая, когда клиент сам шлёт `X-Chat-Id` для per-chat ключа).

### 4.4. Optimistic concurrency (`expected_updated_at` / 409) — без изменений
`payload.updated_at` по-прежнему прокидывается в `set_chat_params`; несовпадение → `ChatParamsConflict` → `409 {code:"conflict", current_updated_at}`. Поведение GET `updated_at`/`chat_updated_at` не меняется.

### 4.5. Идемпотентность и «пустой save»
- Повторный save того же значения: набор ключей в `overrides` не меняется; history-строка `field='chat_params'` **не пишется** (существующее поведение `set_chat_params`, `old_json == new_json`). `updated_at` может обновиться — это допустимо и совпадает с прежним контрактом (не является регрессом).
- Отсутствующий в запросе ключ **не создаётся**.
- Пустой `items`/`patch` → `422` (как сейчас).
- Лог `[api] config chat updated | chat=%s | keys=%d | by=%s` сохраняется; `keys` = число ключей текущего запроса (R17-safe, без значений).

### 4.6. Паритет GET / DELETE
- GET (`routes.py:372-377`) после save отдаёт сохранённое значение для `per_chat=True` с `chat_source="chat"` и корректным `global_value`.
- DELETE (`routes.py:729`) удаляет **ровно один** ключ; прочие ключи остаются; `meta` не затирается.
- Набор ключей после двух save и после DELETE согласован с ожидаемым (тесты §7).

### 4.7. Разрыв петли сида
После UI-save 8 seed-ключей (в т.ч. `-1`) остаются в `overrides`; при рестарте `apply_chat_settings_seed` видит `current.get(key) == value` → `skipped` (no-op), а не «самоизлечение». Сид и его политику (`enforce`, `version_bump`, `force`) **не меняем**.

---

## 5. Изменения по файлам

### 5.1. `web/api/routes.py` (единственный обязательный файл, T-2354/T-2355)
- **`:482`** — читать **два** namespace раздельно: `perm_overrides = dict(root.get("perm_overrides") or {})` (для прав) и `value_overrides = dict(root.get("overrides") or {})` (база значений).
- **`:498-500`** — в `effective_matrix(..., chat_overrides.get(item.key))` подставить `perm_overrides`.
- **`:523-524`** — `new_overrides = dict(value_overrides); new_overrides.update(patch_overrides)`.
- **`:528-529`** — запись без изменений по форме (`{"overrides": new_overrides, "meta": meta}`), т.е. `perm_overrides` в patch **не добавляется**.
- **`:527-538`** — `409`/лог/ответ — без изменений.
- GET (`:372-377`) и DELETE (`:728-733`) **не меняются** (они уже эталонны).

**Ориентир по величине диффа:** только переименование/разведение переменных (≈3-4 строки), `_post_config_global` не трогается.

### 5.2. Прочие файлы
- `web/app.js` — **не меняется** (клиент шлёт один ключ за POST — это нормально).
- `services/chat_settings_seed.py`, `config/chat_settings_seed.json`, `web/api/access.py` — **не меняются**.
- `services/chat_params.py` — **не меняется** (namespace-семантика корректна; изоляция — забота вызывающего).

---

## 6. Контракты

**POST `/api/config`** (заголовок `X-Chat-Id: <chat_id>`), тело:
```json
{ "items": [{"key": "limits.chat_global_key_budget_requests", "value": -1}],
  "updated_at": "<ISO|null>" }
```
Успех `200`:
```json
{ "updated": ["limits.chat_global_key_budget_requests"],
  "chat_id": -1002661910336,
  "updated_at": "<ISO>" }
```
Гарантии:
- В `overrides` остаются все ранее сохранённые ключи ∪ `patch`; `perm_overrides` не изменяется.
- `updated` отражает только ключи текущего запроса.

Ошибки (без изменений): `422` (неизвестный ключ / `keys.*` / `per_chat=false` / битое значение / пустой `items`), `403` (нет права по `perm_overrides`), `503` (PG down), `409` (`expected_updated_at`).

**Инвариант R16:** контракт ответа аддитивен/совместим — новые поля не вводятся, существующие сохраняются.
**Инвариант R17/R18:** значения-секреты в этом пути не участвуют (`keys.*` → 422); в лог — только `chat_id`, счётчик ключей, `user.id`.

---

## 7. План тестов (T-2356/T-2357)

Рекомендуемая локация: новый файл `tests/test_budget_overrides_merge_round1024.py` (или класс в `tests/test_webapp_api.py`), по образцу `tests/test_chat_settings_seed_round1019.py` — с фейковым `chat_params` (in-memory dict) через `monkeypatch`. Обязательные кейсы:

1. **(a) Два последовательных save — оба ключа целы.** Предзаполнить `overrides` ключом `K1`; POST `K2`; затем POST `K3`. Ожидаем `{K1, K2, K3}`; каждый save не стирает предыдущие.
2. **(b) Seed-overrides выживают после UI-save.** Предзаполнить `overrides` 8 ключами из `config/chat_settings_seed.json:11-20` (включая `limits.chat_global_key_budget_requests: -1`); POST один новый/другой per-chat ключ. Ожидаем: все 8 seed-ключей на месте + сохранённый; `-1` не потерян.
3. **(c) Паритет с DELETE.** После (a) выполнить DELETE одного ключа → удалён только он, остальные на месте; повторный DELETE того же → `404`.
4. **(d) `perm_overrides` не утекает в `overrides`.** Предзаполнить `perm_overrides` записью для некоторого ключа `P`; POST значения ключа `V`. Ожидаем: `P` **отсутствует** в `overrides`; `perm_overrides` без изменений; проверка права через `effective_matrix` срабатывает как прежде (например, не-глобальный админ получает `403` на ключ с ограничением, глобальный — `200`).
5. **(e) `updated_at`/409.** POST с неверным `updated_at` → `409 {code:"conflict"}`; с верным → `200`. GET `updated_at` согласован.
6. **(f) `per_chat=false` — глобальный путь.** POST для ключа с `per_chat=false` без `X-Chat-Id` (или с `global:true`) не задевает per-chat `overrides` (проверить, что chat-профиль не изменился).
7. **(g) GET показывает сохранённое.** После save GET с `X-Chat-Id` отдаёт значение, `chat_source="chat"`, корректный `global_value`.
8. **(h) Идемпотентность/no-op.** Повтор того же значения: набор ключей и данные не меняются; history-строка не создаётся; лог-счётчик корректен.
9. **(i) Пустой/некорректный ввод.** `items: []` → `422`; неизвестный ключ → `422`; `keys.*` → `422`.

**Тест-гейт:** полный pytest — `0 failed`; `node --check web/app.js` — OK; `git diff --check` — чист.

---

## 8. Риски и митигации

| # | Риск | Уровень | Митигация |
|---|---|---|---|
| R1 | Недостаточный фикс (значения всё ещё затираются) | Critical | Тесты (a)/(b) как контракт; дифф минимален и обозрим |
| R2 | Смешение namespace ломает матрицу прав (`permsoc`/`can_edit_param`) | High | Тест (d); `perm_overrides` только в `effective_matrix`; запись `perm_overrides` остаётся в `access.py` |
| R3 | Конфликт `web/api/routes.py` с F11/F22 | Medium | Ступень **F11 → F20 → F22**; F20 изолирован от web-очереди |
| R4 | Регресс `expected_updated_at`/409 на конкурентных save | Medium | Тест (e) |
| R5 | Утечка секретов в логи/отчёты (R17/R18) | Low | В путь не попадают `keys.*`; лог — без значений |
| R6 | База merge читается через процесс-кэш (`get_all_chat_params` без `pg`) | Low | Кэш инвалидируется при каждом успешном `set_chat_params`; изоляцию держит `expected_updated_at`. Прямое PG-чтение — возможное упрочнение (см. §12) |

---

## 9. Критерии приёмки

1. Одиночный save любого per-chat значения **не удаляет** остальные per-chat значения (доказано тестами (a)/(b)).
2. `perm_overrides` **не попадает** в `overrides`; матрица прав работает как прежде (тест (d)).
3. 8 seed-ключей целевого чата (в т.ч. `-1` = безлимит) сохраняются после UI-save (тест (b)).
4. GET/DELETE-паритет подтверждён (тесты (c)/(g)).
5. `409`/`updated_at` и `per_chat=false`-путь не сломаны (тесты (e)/(f)).
6. Полный pytest — `0 failed`; `node --check web/app.js` — OK; `git diff --check` — чист.
7. **Δ DDL = 0, Δ каталога = 0.**

---

## 10. Флаг и раскатка

- **Feature flag не вводится** (T-2353): это поведенческий фикс корректности, не rollout-переключатель. Kill-switch — `git revert`.
- Progressive delivery: не требуется; проверка — live на целевом чате (T-2359): сохранить значение бюджета → перезагрузить → значение и прочие per-chat значения на месте; бот не уходит в заглушку без причины.

## 11. Откат

- `git revert` коммита F20 (или ручной возврат трёх строк). Данные не мигрируются → обратной миграции нет.
- Побочный эффект отката: возврат бага затирания (приемлемо как аварийная мера).

## 12. Инварианты и вне scope

**Соблюдаются:** `manual-overrides-immutable` (§3), R16 (аддитивность API), R17/R18 (секреты/креды), порядок роутеров `bot.py` (не трогается), `physical-two-call` (LLM-конвейер System 2 не затрагивается: путь сохранения — не LLM-вызов; Δ вызовов = 0), Δ DDL = 0, Δ каталога = 0.

**Вне scope F20:**
- Ремонт уже утерянных значений целевого чата — **F22** (F20 лишь прекращает потерю).
- Master-тумблер бюджетов `flags.budgets_enabled` — **F21**.
- **Связанное наблюдение (не F20):** `web/api/access.py:443-447` пишет `{"perm_overrides": {key: value}}`, а `set_chat_params` заменяет namespace целиком → одиночная запись прав чата теоретически может затирать прочие `perm_overrides`. Это **другой** namespace и **другой** endpoint; в F20 не меняем. Рекомендация: вынести в отдельный follow-up (merge-по-правам) после F20–F22, чтобы не расширять scope.

## 13. Ссылки

- `plans/features/budget-overrides-merge-fix-round1024/tasks.md` (T-2353…T-2359)
- `plans/backlog.md` §10.24 (F20–F23), `plans/current_task.md:404`
- `plans/archive/budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md` (AMEND)
- `plans/archive/providers-kostik-round1012/ADR-1012-1.md` (AMEND)
- `web/api/routes.py`, `services/chat_params.py`, `services/chat_settings_seed.py`, `config/chat_settings_seed.json`, `web/api/access.py`, `web/app.js`
