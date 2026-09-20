# Review — F10 `aliases-render-real-fix-round1024` (раунд 10.24, ШАГ 5)

> Ревизор: @Reviewer · Итерация 1: коммит `75f7419` · Итерация 2: коммит `5021d1e`
> HEAD (итер. 2) = `5021d1e` · Ветка: `master` · Поверх F24 `2b0759e` (не приписывается F10)
> Спека: `plans/features/aliases-render-real-fix-round1024/spec.md` · ADR-1024-11 · `tasks.md`
> Секреты/имена не цитируются (R17/R18).

## Статус (актуальный, итерация 2): Approved

> История: итерация 1 (`75f7419`) — **Changes Requested** (см. §1–§5).
> Итерация 2 (`5021d1e`) — все замечания закрыты, финальный вердикт **Approved** (см. §6).

## 1. Резюме (жёстко)

Основной фикс — **правильный и действительно доказан**. `root.iconGlyph('delete')` —
это была реальная причина падения рендера при наличии пар, а `watch(item,{deep,immediate})`
+ `:key(configVersion)` — реальное устранение хрупкой реактивности prop. Render-тест
честный: монтирует настоящий Vue-рантайм (`createRenderer` + `Vue.compile`), проверяет
DOM без ручного `sync()`. Но **обязательная диагностика (Step 1, spec §3.1) врёт про
`global_value`**: для чата БЕЗ override она отдаёт `api_global_value_keys=None`, тогда как
реальный `GET /api/config` возвращает объект глобального слоя. Это тот самый сценарий,
который заявлен как прод-состояние («per-chat override нет»), и именно он — топ-риск R1
(повторное ложное закрытие). Один обязательный артефакт неверен → закрывать нельзя.

## 2. Findings

### [Severity: Medium] Диагностика искажает API-форму `global_value` (нарушение spec §3.1)
File: `manage.py:1821-1838` (`_collect_aliases_diag`)
Problem: в ветке `else` стоит `global_out = effective_global if override_present else None`
(строка 1829). При отсутствии per-chat override `api_global_value_keys` = `None`.
Реальный `GET /api/config` в этом же случае (`web/api/routes.py:442` + `450` + `459-462`)
выставляет `global_value = value` (глобальный слой) и нормализует его в объект —
то есть отдаёт объект, а не `None`.
Эмпирически подтверждено (реальный роут vs diag):
- real API, no override: `global_value = {"…": "…", "…": "…"}` (2 ключа);
- diag, no override: `api_global_value_keys = None`;
- diag, with override: `api_global_value_keys = 2`.
Why it matters: spec §3.1 требует, чтобы диагностика показывала «что реально отдаёт
`GET /api/config` … `global_value`». Диагностика — единственное доказательство для
закрытия F10 (анти-ложный отчёт, ADR-1024-11 D1/D4, риск R1=High). Оператор увидит
`api_global_value_keys=None` при непустом глобальном слое и снова закроет фичу с ложным
выводом «глобальных данных нет».
Required fix: `global_out` для chat-скоупа не-секретного keyvalue ВСЕГДА = эффективный
глобальный объект (как в `routes.py`); `None` — только когда `chat_id` не задан/неприменим.
Убрать хвост `if override_present else None`.

### [Severity: Medium] Тест диагностики обходит ровно тот кейс, где diag расходится с API
File: `tests/test_aliases_render_round1024.py:224-261` (`TestDiagReadOnly._DiagConn`)
Problem: `_DiagConn.fetchrow` для `chat_profiles` **всегда** возвращает override
(`"overrides": {ALIASES_KEY: {"1": "…"}}`), поэтому:
- ветка `override_present == False` (где diag врёт про `global_value`) не исполняется;
- `test_chat_without_override_is_global` (строки 198-208) не проверяет `global_value`.
Why it matters: тест «зелёный» на дефектном коде — маскирует баг и создаёт ложную
уверенность в доказательной базе.
Required fix: добавить кейс без override, где `api_global_value_keys == len(global)`
(и/или сверить `api_global_value_keys` с реальным ответом роута).

### [Severity: Low] `_aliases_shape.double_encoded` ложноположителен на скалярных JSON
File: `manage.py:1762-1770` (`_aliases_shape`)
Problem: `double_encoded=True` ставится для любой строки, которую `json.loads` смог
распарсить (включая `"123"`, `"null"`, `"[…]"`), хотя фактически это не двойное
кодирование объекта — `_ensure_keyvalue_object` вернёт `{}`. Диагностический шум.
Required fix: помечать `double_encoded=True` только если распарсенный результат — `dict`.

### [Severity: Low] Индикатор источника игнорирует `item.global_value` (spec §3.2)
File: `web/app.js:7501-7504` (`sourceLabel`)
Problem: спека §3.2 предписывает индикатор «через `item.chat_source` и
`item.global_value`»; реализация смотрит только `chat_source`. Функционально бейдж
корректен (backend уже резолвит эффективное значение), кейс не блокирующий.
Required fix: либо зафиксировать в spec/ADR осознанное сужение (только `chat_source`),
либо добавить использование `global_value`.

## 3. Что проверено и подтверждено (положительно)

- **Корень F10 (iconGlyph):** `web/index.html:3547` → `root.iconGlyph('delete')`;
  в шаблоне `#kv-editor-tpl` не осталось unqualified `iconGlyph(`. Паттерн совпадает
  с `list-editor` (`index.html:3581`). Регресс-маркеры в JS/Python тестах есть.
- **Реактивность:** `web/app.js:7485-7491` — `item:{deep:true,immediate:true}`;
  `loadConfig` инкрементит `configVersion` (`app.js:4660`) только после успешного
  ответа и после `_scopeGuard` (stale-ответ версию не двигает); `:key` на двух вызовах
  `<kv-editor>` (`index.html:826,1094`).
- **Data-binding доказан реально:** `tests/js/round1024_aliases_render_test.js` монтирует
  настоящий Vue (`Vue.createRenderer` + `Vue.compile` шаблона из `index.html`), проверяет
  DOM-value input-ов БЕЗ ручного `sync()`: первичный рендер, вложенная мутация (deep),
  замена `item`, reload (`configItems` + `configVersion++` → re-mount), массив пар
  `[[k,v]]`, Empty State, бейдж «значение чата»/«глобально», OFF-ветка (path-watcher).
  Прогон: `ALIASES-RENDER-OK`.
- **Backend-контракт:** `GET /api/config` для владельца отдаёт `widget='keyvalue'` и
  `value`-объект; `_ensure_keyvalue_object` снимает двойное кодирование; per-chat override
  → эффективное `value` + `chat_source='chat'` + `global_value`-объект (эмпирически).
- **`manage.py diag aliases`:** read-only — только `SELECT` (трасса в тесте), без
  `UPDATE/DELETE/INSERT/ALTER/DROP`; реальный прогон без PG завершается кодом 1 без
  traceback и без записи. Значения имён/ID в вывод не попадают (R17).
- **Регистрация JS-теста в pytest:** `tests/test_webapp_js_unit.py:96` → OK.

## 4. Контракт (чекбоксы/инварианты/тесты)

`tasks.md`:
- `[x]` **T-2265** Live-диагностика — реализована, но с дефектом fidelity `global_value` (см. Medium).
- `[x]` **T-2266** Data-binding + `root.iconGlyph` — выполнено.
- `[x]` **T-2267** Эффективное значение + бейдж источника — выполнено.
- `[x]` **T-2268** Тесты (render/API/flags/read-only diag) — выполнено.
- `[ ]` **T-2264** ADR — файл ADR-1024-11 присутствует (в tasks не отмечен).
- `[ ]` **T-2269** Ревью — выполняю сейчас.
- `[ ]` **T-2270** DevOps: деплой + **живая приёмка в TMA** + прод-прогон diag — НЕ выполнено.
  По spec §3.3/§8 закрытие F10 без live-приёмки **не допускается**.

Инварианты:
- `manual-overrides-immutable` — не затронут (нет записи, нет restore) ✔
- R16 — `ui_flags` аддитивно (`routes.py:369-373`) ✔
- R17 — diag/logs без значений имён/ID; restore из бэкапа запрещён и не реализован ✔
- R18 — секретов в диффе нет ✔
- `parse_mode=None` — не затронут ✔
- Δ DDL = 0 — миграций нет (`git diff --name-only` без migrations) ✔
- Δ каталога = 0 — `services/param_catalog.py` не изменён; флаг — env-only `ClassVar` ✔
- `tma-menu-freeze` — новых вкладок/карточек нет ✔
- Прочие фичи: полный pytest зелёный ✔

Тесты:
- Реальный Vue-харнесс — не тавтологичен ✔
- `node --check web/app.js` — OK (в репо есть гейт `test_webapp_round1024_providers.py:111`) ✔
- JS-гейты (`routing_test.js`, `vue_mount_test.js` и пр.) — зелёные ✔
- Полный pytest: **7882 passed** (3 независимых прогона) ✔

Примечания по прогонам (не дефекты кода):
- Заявленные в задаче «pytest 7869» не совпадают с фактической коллекцией — **7882**.
- На первом прогоне наблюдались 2 fail в `test_webapp_nav_disclosure_ui.py` и один
  холодный таймаут — оба не воспроизвелись на 3 последующих прогонах, связаны со
  stale `__pycache__`/холодным стартом, к диффу F10 отношения не имеют.

## 5. Точный список исправлений (Required)

1. `manage.py` `_collect_aliases_diag` (~1821-1838): для chat-скоупа не-секретного
   keyvalue `global_out` всегда = эффективный глобальный объект (паритет с
   `web/api/routes.py:450-462`). Убрать `if override_present else None`.
2. `tests/test_aliases_render_round1024.py` `TestDiagReadOnly`: добавить кейс
   **без override** и проверить `api_global_value_keys == len(global)`;
   желательно сверить с реальным ответом роута.
3. `manage.py` `_aliases_shape` (~1762-1770): `double_encoded=True` только для
   распарсенного `dict`.
4. (Low) spec §3.2 vs `sourceLabel` (`web/app.js:7501-7504`): либо использовать
   `global_value`, либо зафиксировать сужение в спеке/ADR.

После правок — повторный полный pytest и прогон `node tests/js/round1024_aliases_render_test.js`.

Верни исправленную версию. Текущий код отклонён.

---

# 6. Итерация 2 — коммит `5021d1e`

> Коммит: `5021d1e` · HEAD = `5021d1e` · поверх F24 `2b0759e` (его правки не приписывались F10).
> Затронуты только F10-файлы: `manage.py`, `web/app.js`, `web/index.html`,
> `tests/test_aliases_render_round1024.py`, `tests/js/round1024_aliases_render_test.js`.

## Статус: Approved

## 6.1. Закрытие замечаний итерации 1

| # | Замечание итер.1 | Факт | Вердикт |
|---|---|---|---|
| 1 | diag искажал `global_value` при отсутствии override | `manage.py`: `global_out = effective_global` вынесено безусловно (строки ~1824-1830); `if override_present else None` удалён | **Закрыто** |
| 2 | тест диагностики обходил кейс без override | `_DiagConn(overrides)`; `_run(..., *, overrides)`; добавлен `test_no_override_global_value_matches_global` | **Закрыто** |
| 3 | `double_encoded=True` для скалярных JSON | `_aliases_shape`: `double_encoded = isinstance(parsed, dict)` + `test_scalar_json_not_double_encoded` | **Закрыто** |
| 4 | `sourceLabel` игнорировал `global_value` | `web/app.js`: computed `sourceHint` (использует `chat_source` и `global_value`); `:title="sourceHint"` в `index.html`; ассерты в JS-тесте | **Закрыто** |

## 6.2. Перепроверка по существу (эмпирически)

Прямой прогон `_collect_aliases_diag` с фейковым PG:
- `NO_OVERRIDE`: `override_present=False`, `api_value_keys=2`,
  `api_global_value_keys=2`, `api_chat_source=''` — **совпадает** с реальным
  `GET /api/config` (value-объект, `global_value`-объект, `chat_source=''`);
- `WITH_OVERRIDE`: `api_value_keys=1`, `api_global_value_keys=2`, `api_chat_source='chat'` — совпадает;
- `_aliases_shape`: `123`/`"x"`/`null` → `double_encoded=False`;
- SQL-трасса — только `SELECT` (read-only, R17-безопасно; значения/имена в вывод не попадают).

## 6.3. Тесты (не тавтологичны)

- `test_no_override_global_value_matches_global` — падал бы на коде итер.1
  (`None != 2`), реальный регресс-гейт, а не само-подтверждение.
- `test_scalar_json_not_double_encoded` — проверяет новое поведение формы.
- JS: `sourceHint` вызывается напрямую как computed на реальных формах `item`
  (chat/global-value/global) + статический маркер `:title="sourceHint"`.
- `tests/test_aliases_render_round1024.py` + `..._round1022.py`: **21 passed**.
- `node --check web/app.js` → OK; `node tests/js/round1024_aliases_render_test.js` → `ALIASES-RENDER-OK`.
- Полный pytest: **7884 passed, 0 failed** (совпадает с заявленным;
  = 7882 итер.1 + 2 новых теста итер.2).

Примечание (окружение, не F10): во время итерации 2 рабочее дерево параллельно
правил другой actor (F24 «providers-fullscreen»: `web/app.js`, `config/settings.py`,
`README.md`, `tests/js/round1024_providers_fullscreen_test.js` и др. — файлы с
LastWriteTime 15:56-15:57, коммит `5021d1e` — 15:50). Прогоны F10 (целевые, JS,
полный pytest 7884) выполнены на состоянии коммита `5021d1e`: счёт ровно 7884 =
F10--only, поэтому чужие правки в эти числа не попали и F10 не приписываются.

## 6.4. Инварианты (итер. 2)

- `manual-overrides-immutable` — не затронут (нет записи/restore) ✔
- R16 — аддитивные `ui_flags` (в этом коммите не менялись) ✔
- R17 — diag/логи без значений имён/ID; в выводе только форма/число ключей ✔
- R18 — секретов в диффе нет ✔
- `parse_mode=None` — не затронут ✔
- Δ DDL = 0 — `git diff --name-only` без миграций ✔
- Δ каталога = 0 — `services/param_catalog.py` не изменён ✔
- `tma-menu-freeze` — новых вкладок/карточек нет ✔
- Прочие фичи: полный pytest зелёный, F24 не затронут ✔

## 6.5. Остаточные замечания

Блокирующих нет. Открытыми остаются только задачи вне зоны кода F10
(по `tasks.md`): **T-2270 [@DevOps]** — деплой (cache-bust) + **живая приёмка в TMA**
владельцем и прод-прогон `python manage.py diag aliases --chat-id <target>`.
Закрытие F10 по spec §3.3/§8 требует этого live-доказательства — но это не дефект
данного коммита, а следующий шаг процесса.

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.
