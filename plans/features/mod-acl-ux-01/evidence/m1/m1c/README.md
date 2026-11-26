# MOD-ACL-UX-01 · M1-C — UI-сторона 401/403/404/503 и секретов, промпты в групповом чате

**База (деплой):** `ffdc6eadf38b479509b68ba653b6b0b50200774b` — 2.58.251, ветка
`release/mod-acl-m1b-2.58.251`. Работа — в отдельном registered worktree
(`WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-ux-01-1e46be007668-75a10b81`,
epic `mod-acl-ux-01`, unit `m1c`), ветка `feat/mod-acl-m1c` — от деплоя, не от
`master` (в `master` ACL-кода 2.58.251 нет).

**Метод.** Для каждой строки сначала воспроизведён реальный пробел поведением на
`ffdc6eadf` (RED), затем минимальная правка в существующем пути рендера, затем
тот же набор (GREEN). Всё, что уже было корректно, **заперто тестом** без
изменения поведения.

**Состав диффа:** UI-коммит `b3d4b95de` (`web/app.js`, `web/index.html`,
`tests/js/mod_acl_ux_m1c_ui_states_test.js`, `tools/ui_mod_acl_m1c_e2e.py`);
корректив r1 (F01/F02) — `services/access.py`, `web/api/routes.py`,
`tests/test_mod_acl_ux_01_m1c_prompt_chat_acl.py`, выравнивание source-пина в
`tests/test_webapp_deps.py`; корректив r2 (R2-F01/F02/F03) —
`web/api/prompt_access.py` (новый, единое решение), `web/api/speech.py`,
`web/api/routes.py` (витрина мемов), расширение замка и evidence.

```text
$ git diff --stat ffdc6eadf -- web services tests tools
 services/access.py                              |  18 +
 tests/js/mod_acl_ux_m1c_ui_states_test.js       | 326 +++++
 tests/test_mod_acl_ux_01_m1c_prompt_chat_acl.py | 527 ++++++
 tests/test_webapp_deps.py                       |  12 +-
 tools/ui_mod_acl_m1c_e2e.py                     | 316 +++++
 web/api/routes.py                               | 114 ++--
 web/api/speech.py                               |  88 ++-
 web/app.js                                      |  91 ++--
 web/index.html                                  |  10 +-
 web/api/prompt_access.py                        | 155 +++ (новый)
 10 files changed, 1421 insertions(+), 81 deletions(-)
```

## 1. Что именно было неверно на `ffdc6eadf`

| Строка | Факт базы (воспроизведено) |
|---|---|
| `MAC-S4-171` | в `api()` тело ответа 401 **выбрасывалось** (`throw` до `resp.json()`), оба серверных тела (`missing init data` / `invalid init data`, locked в M1-B) превращались в один `ApiError(401,'unauthorized')` и один баннер; причина не доходила до пользователя |
| `MAC-S4-171` | серверный 401 при первой загрузке **не показывался вообще**: `loadMe().then(...)` делал `if (!self.me) return;` с комментарием «блокировка выше», но выше блокировка ставилась только при полностью отсутствующем `initData` — при 401 оставалась пустая оболочка |
| `MAC-S4-171` | на телефоне (`≤767 px`) ошибка загрузки ролей (403/404/503) была **невидима**: `.roles-page__aside{display:none}` (`web/static/app.css:7869`) скрывает единственный блок с подписью состояния |
| `MAC-S4-172` | `errText()` при неизвестной форме `detail` делал `JSON.stringify(m)` — единственный путь «произвольный payload ответа → DOM/тост»; значение биндится в карточки (`index.html:12357`, `12625`, `12809`, панель промптов) |
| `MAC-S10-13` (F02 ревью r1) | **просмотр** истории/текста промпта в чатовом скоупе не применял `view_roles`: `_prompt_require_view` проверял только грант чата, поэтому роль, исключённая из `view_roles`, получала `200` и полный текст на `/revisions/{id}/source`, тогда как `GET /api/config` тот же ключ скрывал; запись (`edit_roles`) при этом резалась правильно |
| `MAC-S10-13` (R2-F01/F02) | `/api/speech/blocks` и `/api/speech/block/{id}` отдают **те же** блоки `services.prompt_registry` (и документы `character.core`/`style.policy`/`character.expression`) под вторым ACL `_persona_can_view`: local_admin вне `view_roles` получал 200 и полный текст; запись `/api/speech/block/{id}` решалась `_persona_can_edit`, а не `edit_roles` (при `edit_roles: []` запрос доходил до хранилища) |
| `MAC-S10-13` (R2-F01, ещё поверхность) | `GET /api/initiative/meme-settings` (витрина мемов) отдаёт `text` трёх `prompts.meme_*` и `template.text` при одном лишь доступе к чату — та же утечка в модульной карточке |
| `MAC-S10-13` (F01 ревью r1) | постоянного pytest-замка на ACL промптов в чате не было — только evidence-проба |

## 2. MAC-S4-171 — 401 ≠ 403 ≠ 404 ≠ 503 (UI)

**Реализовано** (минимально, в существующем механизме подписей):

* `api()` на 401 читает тело **до** `throw`, определяет причину через новый
  `initDataCause(body)` (ровно два серверных тела M1-B, иначе `'unknown'`) и
  ставит баннер существующей функцией `accessErrorHint(401, 'auth', cause)`;
  `ApiError.message` сохраняет серверный `detail` (UI не выдумывает причину).
* `accessErrorTitle(status, cause)` / `accessErrorHint(status, scope, cause)` —
  расширены **опциональным** третьим/вторым аргументом: `401/missing` →
  «Нет данных Telegram», `401/invalid` → «Сессия устарела» (прежняя подпись);
  без аргумента поведение прежнее, все существующие вызовы в `index.html` не
  менялись.
* `lockAuth(text)` — единая точка блокирующего состояния входа (баннер +
  снятие индикатора первичной загрузки, то же правило, что в `finally`
  `loadConfig`: «вечная загрузка» скрыла бы реальное состояние). Используется в
  трёх местах: нет контекста, серверный 401 при загрузке, `retryInitData`.
* `index.html`: у `<aside>` ролей в состоянии `rolesError` — `:style` с
  `display:block` (inline сильнее media-правила). В обычном состоянии раскладка
  телефона **не меняется**; показывается ровно существующая карточка
  `accessErrorTitle/Hint` + «Повторить».

**Заперто тестом (поведение не менялось):** 403 → «Нет доступа» + прежний тост
«Доступ запрещён», `authError` не выставляется; 404 → «Не найдено»; 503 →
«Сервис временно недоступен»; ни 404, ни 503 не выдают тост «Доступ запрещён»;
401 без разбираемого тела не утверждает «нет данных Telegram».

**Границы.** 401 = три различимых состояния: нет контекста на клиенте
(существующий текст), серверное «нет данных входа», серверное «подпись не
принята». Подписи живут в одном месте (`accessErrorTitle/Hint`), второго
механизма подписей не заведено.

## 3. MAC-S4-172 — секреты и payload в DOM/консоли (UI)

**Реализовано.** `errText()` больше не сериализует неизвестный объект `detail`:
известные поля (`code`/`reason`/`message`) отдаются как раньше, неизвестная
форма — нейтральное «ошибка сервера». Это закрывает единственный путь
«сырой payload → DOM/тост»; нового маскирующего слоя нет. Маскирование самих
секретов остаётся серверным (locked в M1-B) — UI его не дублирует.

**Заперто тестом (поведение не менялось):** ни один `console.*` не получает
payload ответа (в `web/app.js` вообще нет вывода данных ответа в консоль —
единственный `console.warn` про DOMPurify без данных); баннер выводится
текстом (`{{ authError }}`, не `v-html`).

**Положительный/чувствительный контроль** (оба в unit-тесте и в браузерном
прогоне): посаженный литерал `M1C-PLANT-SECRET-7f3a91` (без `sk-`/Bearer/URI —
иначе его скрыл бы общий регэксп) **есть** в теле ответа и в входе
`errText` — и **отсутствует** в DOM/HTML/консоли; не-секретный маркер
`M1C-BENIGN-MARKER-2c5d` в известном поле `message` **виден** пользователю,
т.е. проверка отсутствия не пустая.

**Границы.** Текст логов (`{{ log.message }}`, `{{ log.exc_text }}`) выводится
как текст, не как HTML; маскирование записи журнала — серверное (M1-B).
Загрузка файлов трассы (`initiativeTraceExport`) пишет файл, не DOM, и не
трогалась.

## 4. MAC-S10-13 — промпты по resource ACL в групповом чате

### 4.1 Что было неверно (review r1, F02)

`_prompt_require_view` (`web/api/routes.py`) в чатовом скоупе проверял только
грант чата (`can_access_chat` + `role_chat ∈ {local_admin, moderator}`) и
**не читал действующую матрицу ресурса**. Запись (`_prompt_require_edit`) и
значение в `GET /api/config` матрицу читали. Следствие на базе `ffdc6eadf`:

| проверка | на базе |
|---|---|
| `view_roles: ["moderator"]`, `edit_roles: ["moderator"]`, `local_admin` чата | |
| `GET /api/config` — ключ в списке | **нет** (правильно) |
| `GET /api/prompts/{key}/versions` | **200**, список ревизий |
| `GET /api/prompts/revisions/{id}/source` | **200**, `body` = полный текст промпта |
| `GET /api/prompts/revisions/diff` | **200**, unified diff с текстом |
| `GET /api/prompts/{key}/baseline` | **200**, метаданные ревизии |
| `POST /api/prompts/{key}/activate` | 403 (правильно) |

То есть роль, исключённая из `view_roles`, значения не видела, но читала
полный текст ревизии и её историю. Это и есть утечка, которую закрывает F02.

### 4.2 Исправление (одно правило, один владелец)

* `services/access.py` — новая `chat_param_matrix(pg_key, db_overrides,
  chat_root)`: **единственная** сборка «дефолт ⊕ DB-override ⊕ chat
  `perm_overrides`». Разбора матрицы у потребителей нет: они передают
  результат в существующие `can_view_param` / `can_edit_param`.
* `web/api/routes.py::_prompt_require_view` — в чатовом скоупе после проверок
  чата вызывает `can_view_param(ctx, matrix)` и при отказе отдаёт **403**
  `нет права на <pg_key>` (та же формулировка, что у записи; не 404 — запись
  и чат существуют, запрещён именно ресурс). Возвращает `(ctx, matrix)`.
* `_prompt_require_edit` — использует ровно этот `(ctx, matrix)`, второй
  сборки прав больше нет. Семантика записи не менялась: `view_roles |=
  edit_roles` (`_normalize_perms`), поэтому право записи не может потеряться
  из-за проверки просмотра — это отдельный кейс в тесте.
* `GET /api/config` — решения о видимости/записи в чатовом скоупе переведены
  на ту же `chat_param_matrix` (поведение байт-в-байт: те же
  `effective_matrix`/`can_view_param`/`can_edit_param`, тот же вход). Глобальный
  путь и путь `/` без `X-Chat-Id` не менялись.

**Закрытые потребители текста/history промпта в чатовом скоупе** (все через
`_prompt_require_view` → одна проверка):

| маршрут | что отдаёт |
|---|---|
| `GET /api/prompts/{key}/versions` | история ревизий (**list**) |
| `GET /api/prompts/revisions/{id}/source` | полный текст (**source**) |
| `GET /api/prompts/revisions/diff` | diff двух ревизий |
| `GET /api/prompts/{key}/baseline` | состояние baseline (метаданные) |
| `POST /api/prompts/{key}/activate` | активация (запись; 403 остаётся) |
| `POST/DELETE /api/prompts/{key}/baseline[/restore]`, `…/factory/restore`, `…/copy-to-global` | запись (тот же `_prompt_require_edit`) |
| `GET /api/prompts/catalog` | только метаданные реестра, глобальный админ (не менялся) |
| `GET /api/config` (значение) | уже решался `can_view_param`; теперь та же сборка |

**Не покрыто на этом шаге (закрыто в §4.4):** `/api/speech/*` отдаёт **те же**
блоки `services.prompt_registry` (в т.ч. `summary.base.narrator`) и документы
характера под вторым ACL (`_persona_can_view/_persona_can_edit`) — это не
«другое семейство», а тот же ресурс; см. R2-F01/F02 ниже.
Глобальная история (`X-Chat-Id` отсутствует) не менялась: там правило прежнее
(админ или явное право на ключ).

### 4.3 Постоянный замок (F01)

`tests/test_mod_acl_ux_01_m1c_prompt_chat_acl.py` — 30 тестов на реальных
роутерах и реальном слое прав (двойники — только хранилище и in-memory журнал):

* **просмотр по матрице**: `local_admin` вне `view_roles` получает 403 на
  `versions`, `source` (и тело ответа не содержит текста промпта), `diff`,
  `baseline`; контроль — с дефолтной матрицей тот же актор видит всё (403 выше
  создан override, а не безусловным отказом), и `GET /api/config` тот же ключ
  ему не отдаёт;
* **запись по `edit_roles`**: `view_roles: ["local_admin"]` + `edit_roles: []`
  → просмотр 200, активация 403; дефолтная матрица → активация 200;
  `view_roles: []` + `edit_roles: ["local_admin"]` → активация 200 (правило
  «запись подразумевает чтение»);
* **изоляция**: участник без гранта — 403 на просмотр и запись; чужой чат
  (`X-Chat-Id`) — 403; ревизия чужого чата без заголовка — 403 и без текста;
* **глобальный админ** — 200 на всех маршрутах при любой матрице.

RED/GREEN: на `a6e55ce70` (и на базовом дереве) падают ровно 4 кейса
просмотра (`versions`, `source`, `diff`, `baseline`); после F02 — 13/13
(позже замок расширен до 30 тестов, см. §4.4). Логи: `red-f02-view.txt`,
`python-suites.txt`.
Проба `probe_prompt_chat_acl.py` остаётся как быстрая ручная воспроизводимость
(6/6, включая кейс просмотра) — замком является pytest-файл.

### 4.4 Ревью r2: speech-поверхность и чатовый слой (R2-F01/F02/F03)

**R2-F01 (просмотр) — реальная утечка, закрыта.** `/api/speech/blocks` и
`/api/speech/block/{id}` отдают блоки ТОГО ЖЕ `services.prompt_registry`
(`summary.base.narrator` и др.) и документы характера (`character.core`,
`style.policy`, `character.expression`) под вторым ACL
(`_persona_can_view`). На `cc7491b35` при `view_roles: ["moderator"]`
local_admin чата получал 200 и полный `effective.text` (в т.ч. чатовый
override), тогда как `/api/prompts/...` уже отвечал 403, а `/api/config` ключ
скрывал.

**R2-F02 (запись) — второй write-ACL, закрыт.** `_can_edit_speech` в чате
решал только `_persona_can_edit`; POST `/api/speech/block/{id}` при
`edit_roles: []` проходил гейт и доходил до хранилища (409 двойника вместо
403).

**R2-F03 (замок) — чатовый слой не дискриминировался.** Тест сеял матрицу
только через `param_permissions`; мутация «`chat_param_matrix` игнорирует
`chat_root`» выживала. Добавлены два кейса (`perm_overrides` запрещает;
`perm_overrides` разрешает поверх DB-запрета) + speech-кейс через чатовый
слой — мутация убита.

**Исправление (одно решение, один владелец).** Новый
`web/api/prompt_access.py`:

* `chat_resources(cache, user_id, chat_id, ctx=…)` — контекст актора + входы
  матрицы, прочитанные ОДИН раз на запрос; `visible/editable(pg_key)` считают
  матрицу через `services.access.chat_param_matrix` и сравнивают штатными
  `can_view_param`/`can_edit_param` (своего разбора/сравнений нет);
* `resource_access(...)` — решение для поверхностей, отдающих ТЕКСТ ресурса
  (speech-блоки/документы, витрина мемов): hidden → только глобальный админ;
  чат → действующая матрица; глобально — не сужаем (значения промптов не
  секреты, паритет с `/api/config`);
* `decide(...)` — полное правило истории промпта; `_prompt_require_view/edit`
  в `routes.py` теперь только переводят отказ в 403 с прежними текстами
  (`нет права на <key>`, `нет доступа к чату`, `нет доступа к этому промпту`).

`web/api/speech.py` использует это решение во всех точках чтения/записи
реестрового текста (список блоков, деталь, запись/сброс/откат блока,
документы `core`/`style`/`expression` и их запись, live-check). Список блоков
фильтруется как `GET /api/config` (строки нет), одиночный блок/документ —
403. `web/api/routes.py` — витрина мемов (`/api/initiative/meme-settings`
GET/POST) не отдаёт `text` промптов `prompts.meme_*`, если матрица их не
разрешает (поля помечаются существующим `source: "unavailable"`).

**Мутации (все убиты, файлы восстановлены по git-blob):**

| # | мутация | убийца |
|---|---|---|
| M1 | `decide` без `can_view_param` | 4 view-теста + chat-override |
| M2 | `chat_param_matrix` игнорирует `chat_root` | 2 prompt-кейса + speech-кейс |
| M3 | `/speech/blocks` отдаёт все блоки | 2 speech-кейса |
| S1 | `/speech/block/{id}` без матрицы | `test_block_detail_denied` |
| S2 | POST `/speech/block/{id}` без `edit_roles` | `test_block_write_denied_by_edit_roles` |
| S3 | `/speech/core` без матрицы | `test_document_read_obeys_matrix[core]` |
| M4 | витрина мемов без матрицы | `test_prompt_text_denied_by_matrix` |

### 4.5 Инвентарь потребителей промпт-текста (чтобы третья поверхность не «нашлась» позже)

Поиск: `prompt_registry`/`all_blocks`/`effective_prompt`/`factory_text` по
`web/`, `handlers/`, `services/`; плюс прямые чтения `prompts.*` и витрины.

| потребитель | что отдаёт | решение |
|---|---|---|
| `GET /api/prompts/{key}/versions` | история ревизий | `prompt_access.decide` (чат — матрица) |
| `GET /api/prompts/revisions/{id}/source` | полный текст | `decide` |
| `GET /api/prompts/revisions/diff` | diff с текстом | `decide` |
| `GET /api/prompts/{key}/baseline` | метаданные baseline | `decide` |
| `POST /api/prompts/{key}/activate` | запись | `decide` (`edit_roles`) |
| `POST/DELETE …/baseline[/restore]`, `…/factory/restore`, `…/copy-to-global` | запись | `decide` |
| `GET /api/speech/blocks` | все блоки реестра + `effective.text` | **R2: `resource_access`**, строки без права скрыты |
| `GET /api/speech/block/{id}` | `effective.text`, история, diff | **R2: `resource_access`**, 403 |
| `POST /api/speech/block/{id}`, `/reset`, `/rollback` | запись значения | **R2: `resource_access(edit=True)`**, 403 |
| `GET /api/speech/core` + `POST /core/meta` | документ `character.core` | **R2: `resource_access`** |
| `GET /api/speech/style` + `POST /style`, `/style/reset-chat` | документ `style.policy` | **R2: `resource_access`** |
| `GET /api/speech/expression` + `POST`/`reset-chat`/`live-check` | документ `character.expression` | **R2: `resource_access`** |
| `GET/POST /api/initiative/meme-settings` | `text` трёх `prompts.meme_*` + `template.text` | **R2: `resource_access`** в витрине |
| `GET /api/config` (чат) | значение ключа | уже `can_view_param` + `chat_param_matrix` |
| `GET /api/config` (глобально) | значение ключа | **не сужается by design**: значения промптов не секреты (секреты — только admin), паритет с текущим поведением |
| `GET /api/prompts/catalog` | метаданные реестра | глобальный админ; текстов нет |
| `GET /api/debug/config`, `/api/debug/*` | RAM-дамп ключей | отдельная capability `action.debug.config` (не чат-поверхность) |
| `GET /api/speech/overview` | карточки разделов: состояние + число знаков | metadata-only (текстов нет) — не гейтится |
| `GET /api/speech/humor`, `/capabilities`, `/learning`, `/examples` | настройки/счётчики/библиотека примеров (не реестровый текст) | отдельные ресурсы/ACL, вне `prompts.*` |
| `POST /api/speech/try` | ответ модели (не текст промпта) | `_can_view`, вне класса |
| `GET /api/speech/inspector` | СКОМПОНОВАННЫЙ payload (base + core + style + expression) | отдельная capability `_can_edit_inspector` (глобальный админ или явное `edit_persona`); диагностическая поверхность, не per-key reader — **осознанно не гейтится матрицей**, зафиксировано как граница |
| `GET /api/config/...`, `/api/initiative/*` прочие | настройки (не текст промпта) | `can_view_param` там, где ключ показывается |
| `services/prompt_factory|readback|release_policy|capability_registry`, `handlers/*` | сборка промпта для ответа бота / релизный путь | **системные потребители**, не пользовательские чтения: ACL решает, кто видит/меняет текст через API, а не может ли бот его использовать |

## 5. Тесты и числа

Окружение: Node `v24.16.0`, `pytest` из `C:\Code\Python\adminbot\.venv`
(Python 3.12), Playwright/Chromium локально. База для RED — overlay с **точными
git-blob'ами** базы: `web/app.js` = `c1d1fa6cb…`, `web/index.html` =
`39e740eee…` (получены `git archive`, без перекодирования), тест-файл байт-в-байт
равен кандидатному (`b76cb4b57…`).

| Прогон | Команда | База `ffdc6eadf` | Кандидат | Файл |
|---|---|---|---|---|
| **Замок ACL промптов (30 тестов)** | `pytest tests/test_mod_acl_ux_01_m1c_prompt_chat_acl.py` | **15 failed** / 266 passed в prompt-наборе → 13 из них — кейсы замка (4 view + 1 chat-override + 7 speech + 1 meme); на `cc7491b35` — **8 failed** (7 speech + 1 meme) | **30 passed** | `red-f02-view.txt`, `red-r2-speech.txt`, `python-suites.txt` |
| **Prompt-набор (13 файлов)** | `pytest <13 files> -q` | 266 passed / **15 failed** (2 пре-существующих + 13 закрытых) | 279 passed / **2 failed** (оба пре-существующие) | `python-suites.txt` |
| **ACL/RBAC-набор (12 файлов)** | `pytest <12 files> -q` | 509 passed / 0 failed | 509 passed / 0 failed | `python-suites.txt` |
| **Speech/registry-набор (17 файлов)** | `pytest <17 files> -q` | 323 passed / **21 failed** (4 пре-существующих + 13 кейсов замка + 4 файла `plans/features/`, исключённых из оверлея) | 340 passed / **4 failed** (те же 4 пре-существующих) | `python-suites.txt` |
| **Широкий UI/config (84 файла)** | `pytest <84 files> -q` | те же 26 файлов на базе: 567 passed / 57 failed, списки FAILED совпадают (56 идентичных + 1 документ из исключённого `plans/features/`) | 2101 passed / **56 failed** (все идентичны базе) | `python-suites.txt` |
| Unit UI-состояний (15 проверок) | `node tests/js/mod_acl_ux_m1c_ui_states_test.js` | **FAILED (4)**: A2 (401/missing ≡ 401/invalid), A5 (`unauthorized` вместо серверной причины), B3 (литерал в DOM-привязке), B4 (`errText` отдал секрет) | **MOD-ACL-M1C-UI-OK** | `red-base-node.txt` |
| Браузерный DOM/консоль (7 сценариев × 1440/390) | `python tools/ui_mod_acl_m1c_e2e.py [--root <base>]` | **FAILED (11)** из 14 | **OK (14/14)** | `red-base-e2e.txt`, `candidate-e2e.txt` |
| Полный `tests/js/**` | 140 файлов, `node <file>` | 132 PASS / 8 FAIL *(7 пре-существующих + новый RED)* | 133 PASS / 7 FAIL | `base-js-suite.txt`, `candidate-js-suite.txt` |

Метод базового сравнения Python: `git archive ffdc6eadf` (без `media/` и
`plans/features`, с `plans/docs`) → отдельное дерево в `%TEMP%`, `git init` +
локальный коммит для inventory-тестов; для точного RED новых тестов — такое же
дерево `cc7491b35`. Проверено, что блобы изменённых файлов в деревьях равны
ожидаемым: `web/app.js` `c1d1fa6cb…`, `web/api/routes.py` `91b972111…`
(база) / `16f5999a7…` (cc7491b35), `services/access.py` `4a3f2afcc…` /
`3bf957fcc…`, `web/api/speech.py` `31a40eec3…` (в обоих — база).

**Выравнивание одного source-пина.** `tests/test_webapp_deps.py::
TestFrontNoContext::test_retry_locks_when_me_missing` пиновал буквальный
`self.authLocked = true` в теле `retryInitData`. После M1-C блокировка одна
(`lockAuth`), поэтому пин проверяет вызов `self.lockAuth(` в retry **и**
присваивание `this.authLocked = true` в теле помощника — тот же контракт
«`!me` → блокировка с текстом», без трёх копий присваивания. Убирание вызова
`lockAuth` из `!me`-ветки пин роняет.

`Compare-Object base-js-suite candidate-js-suite` → **ровно одна** строка
изменилась: `mod_acl_ux_m1c_ui_states_test.js` FAIL→PASS. Пре-существующие
падения JS (`evol_cog_scene`, `mod_acl_ux_m4a_w2b_history`, `round1024_image_key`,
`round1025_f7_permsoc_local`, `round1025_ia_routing`, `round1025_save_state`,
`routing`) в кандидате те же.

Что именно покраснело на базе в браузере (каждый пункт — отдельный сценарий):

* `auth_missing` / `auth_invalid` (1440 и 390): баннера нет вообще — остаётся
  пустая оболочка статуса (RED обеих строк 401);
* `audit_secret_detail` (1440 и 390): `M1C-PLANT-SECRET-7f3a91` **в тексте DOM и
  в HTML** (карточка аудита биндит `errText`);
* `access_403` / `access_404` / `access_503` (390): подпись состояния не видна
  (скрытый `aside`); на 1440 те же состояния **проходят и на базе** — это
  замок существующего корректного поведения, а не правка.

`audit_known_fields` проходит и на базе, и в кандидате — контроль
чувствительности подтверждает, что «литерала нет» не получается ценой «ничего
не отрисовано».

### Python: пре-существующие падения, зафиксированные ранее (review r1)

Отдельно прогнанный ранее 8-файловый набор затронутых швов давал `5 failed,
158 passed` и на базе, и на кандидате (ревью r1 воспроизвело то же). Эти пять
падений остаются пре-существующими и в F02-наборах — они не входят в новые
списки, но причины те же:

1. `test_webapp_js_unit.py` × 3 — те же `tests/js` файлы, что уже падают в
   `base-js-suite.txt` (`routing_test.js`, `round1024_image_key_test.js`,
   `round1025_f7_permsoc_local_test.js`, причина
   `this._embedModelSwapGuard is not a function`).
2. `test_104_backend_additions.py::test_user_facing_text_updated` — искомой
   строки `toggleModule(m, $event.target.checked)` нет и в **базовой** разметке
   (`git show ffdc6eadf:web/index.html`).
3. `test_webapp_evol_w14_states.py::…test_every_native_checkbox_is_a_design_system_control`
   — тот же «голый» чекбокс на базе: прогон одного и того же тела теста по двум
   файлам даёт `inputs=47, raw_outside_ds=1, tags=['']` и для базы, и для
   кандидата.

Полный 23k-набор не прогонялся: дифф — один сервисный помощник, промпт-маршруты,
speech-поверхность и витрина мемов (плюс архив UI-коммита). Вместо него
прогнаны четыре набора (84, 13, 12 и 17 файлов) с побитовым сравнением списков
падений с базой — см. `python-suites.txt`. Отдельно: 4 пре-существующих
падения `tests/test_initiative_speech_layers_chat_overrides.py` (двойник
`_StubService` без `_writer_evidence_capacity`; к web/ACL не относятся) —
идентичны на базе и кандидате.

## 6. Конфигурация и флаги

Новых флагов, kill-switch, гейтов, порогов и миграций нет. Поведение
определяется существующим механизмом подписей `accessErrorTitle/Hint` и
существующим серверным ACL промптов. Пользовательских override, которые могли
бы сброситься, инкремент не касается — заводские значения не менялись
(правило «включать готовую функцию при первом деплое» неприменимо по существу:
включать нечего).

## 7. Что не удалось проверить (честно)

* Живой Telegram WebView / живой групповой чат: использовался локальный стенд,
  `initData` — **локальный тестовый** токен (`sessionStorage` сид из
  `tools/ui_round1025_matrix.TMA_STUB`), production-идентичность не применялась.
  Стенд полностью офлайновый: SDK отдаётся из чекаута
  (`/static/vendor/telegram-web-app.js`), внешней сети и production нет.
* Реальный `PostgreSQL`-отказ и реальный 401 от Telegram-валидации: статусы
  поданы стабом на границе HTTP; серверные тела взяты дословно из `deps.py`
  (locked в M1-B).
* F02/R2: запись `param_permissions`/`chat_params.perm_overrides` через API на
  стенде не упражнялась (двойники не пишут: 503/409) — состояние матрицы
  засеяно напрямую (валидно по `_normalize_perms`/`tests/test_access.py`), а
  чатовый слой `perm_overrides` теперь заперт замком.
* R2: запись речи/мемов после гейта доходит до двойника хранилища и там
  падает (409/503) — end-to-end сохранение в реальный чат не доказано, но
  ACL-гейт проверен (403 до записи / «не 403» при праве).
* R2: `/api/speech/inspector` (скомпонованный payload) осознанно не гейтится
  матрицей — отдельная capability `_can_edit_inspector` (глобальный админ или
  явное `edit_persona`), см. инвентарь §4.5; это граница, а не забытая
  поверхность.
* F02: живой групповой чат с реальным `chat_admins` не использовался; матрица
  ключа и грант чата поданы двойником хранилища при реальном слое прав.
* 401-состояние теперь снимает индикатор первичной загрузки — это меняет
  картинку и для **существующего** случая «нет контекста»; проверено
  скриншотом 390 px, живой WebView не проверялся.
* Мобильная карточка ошибки ролей появляется только в состоянии ошибки; как она
  выглядит на реальном устройстве при реальном 403, не проверялось.

## 8. Гигиена

* Worktree `…m1c-75a10b81` — активная линия инкремента, зарегистрирован
  (`housekeeping register-worktree --epic mod-acl-ux-01 --unit m1c`),
  сохраняется до ревью/решения по доставке.
* Overlay базы и служебные скрипты сравнения — во временных каталогах
  `%TEMP%\opencode\m1c_probe` (UI-инкремент), `%TEMP%\opencode\m1c_f02`
  (F02-наборы) и `%TEMP%\opencode\m1c_r3` (R2: база, дерево `cc7491b35`,
  мутации) — удалены после употребления; репозиторий не затрагивали.
* Прогон UI-наборов `test_webapp_evol_w1x` пересоздаёт PNG в
  `plans/features/evol/audit/evidence/`; после прогонов они восстановлены из
  HEAD (`git show HEAD:path`), в коммиты не попадают.
* Evidence: логи RED/GREEN, сводка наборов (`python-suites.txt`), проба ACL,
  3 скриншота. Проба и логи JS-наборов перегенерированы в UTF-8 без BOM
  (F04 ревью r1). Полные JSON прогонов с консолью в репозиторий не
  копировались (воспроизводимы командой).

## 8. M1-C choke point (дизайн `612dd9ef…`) и R4 corrective

Реализация единой точки принуждения для ТЕКСТА промпта и доказательства —
`choke-point.md`: §1–7 — механизм, швы, инвариант A/B по `app.routes`,
мутации, числа; §8 — R4 corrective (F01: кэш провайдера/снимок хода,
инвентарь кэшей; F02: отказ ACL не проглатывается фолбэком; F03: AST ловит
все формы алиасинга). Поведенческий RED/GREEN: `red-choke-probe.txt`
(шесть поверхностей r3) и `red-r4-cache.txt` (кэши текста).


### R5 corrective (инвентарь кэшей + точечные формы AST)

`choke-point.md` §8.2 теперь содержит оба сырых источника design §1.9
(`services.hot_config.ConfigCache`, `services.chat_params._chat_params_cache`)
с поверхностями/гейтами и провенанс grep (команды + дата 2026-11-26), §8.4 —
новый AST-сканер, §8.9 — R5-F01/F02. RED/GREEN точечных форм AST:
`red-r5-ast.txt` (скрипт `r5_ast_redgreen.py`; файл восстанавливается по
содержимому, sha256 до/после совпадает).
