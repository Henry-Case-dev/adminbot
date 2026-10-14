# Ревью F4 `dossier-live-feed-round1024` — Шаг 5, раунд 10.24

- **Коммит:** `7eb7c69` — `feat(services,web,tests): раунд 10.24 F4 — вертикальная кликабельная лента досье (user_id, переход в досье)`
- **Ревьюер:** @Reviewer
- **Дата:** 20.09.2026
- **Артефакты:** `plans/features/dossier-live-feed-round1024/spec.md`, `ADR-1024-8.md`, `tasks.md`; `plans/current_task.md` UPD2 п.2 (строки 167–172) + UPD3 №9 (строка 270); секреты не цитировались (R17/R18).
- **Верификация:** `git show 7eb7c69 --stat` / `git diff 7eb7c69^ 7eb7c69` (8 файлов, +698/−5); полный `pytest` на рабочем дереве — **7842 passed**; `node --check web/app.js` — OK; все 15 гейтов `tests/js/*.js` вручную — OK (`round1024_dossier_feed_test.js` → `DOSSIER-FEED-OK`, `vue_mount_test.js` → `VUE-MOUNT-OK`).

## Статус (итог, итерация 2)

**Approved**

- **Статус (iter2):** **Approved** — все findings итерации 1 закрыты по существу; см. раздел «Итерация 2» ниже.
- **Статус (iter1):** Changes Requested (история проверки сохранена ниже).

## Итерация 1 — статус

**Changes Requested**

Итог: ядро фичи сделано верно — лента действительно вертикальная и медленная (бесшовный `translateY(-50% − gap/2)` с дублированием, `max(72s, N×6s)`, пауза по hover/focus, `prefers-reduced-motion` сохранён), строки кликабельны и ведут по контракту «сначала `setActiveChat`, потом `openDossier`», бэкенд резолвит `user_id` read-time без DDL (R16-аддитивно, `user_id`/`user_name` в `items[]`), флаг `DOSSIER_LIVE_FEED_ENABLED` доставлен через `ui_flags` (OFF → прежняя горизонталь 42s), Δ DDL = 0, Δ каталога = 0, полный pytest зелёный. Но **главный поведенческий контракт F4 — клик-путь GLOBAL → чат → досье — не защищён ни одним тестом в штатном прогоне**: JS-гейт написан, но не подключён к `pytest`, а Python-тесты проверяют только API и подстроки в статике. Плюс есть отклонение от спеки §3.2(2) на null-`chat_id` и двойные таб-стопы/озвучивание из-за интерактивных seamless-клонов. Это не «почти готово, зальём» — это зелёный прогон, который ничего не говорит о центральном сценарии владельца.

---

## Findings

### [High] JS-гейт F4 не подключён к pytest — клик-путь не проверяется автоматически

- **Файлы/строки:**
  - `tests/js/round1024_dossier_feed_test.js:1-223` — тест существует и вручную зелёный.
  - `tests/test_webapp_js_unit.py` — **нет** записи для `round1024_dossier_feed_test.js` (список `_run_js` заканчивается строками `:70` nodeflow, `:78` image_module, `:85` prompts_ui, `:92` image_key).
- **Проблема:** в коммите `7eb7c69` не изменён `tests/test_webapp_js_unit.py`. Соседние фичи того же раунда зарегистрировали свои гейты (`+7` строк каждая): F3 — `68b7c81`, F5 — `d820a14`, F6 — `109cbce`, F11 — `1e93c92`. F4 — единственная из web-четвёрки, чей JS-тест не подхватывается `pytest`. `conftest.py` авто-запуска всех `tests/js/*.js` тоже нет (раздел `js` в conftest отсутствует).
- **Почему это важно:** единственное автоматическое доказательство центрального контракта UPD3 №9 (`user_id == null` → no-op; GLOBAL → сначала `setActiveChat(chat_id)`, затем `openDossier` с верным `user_id`; совпадение чата → без переключения; ошибка `setActiveChat` → toast без модалки) живёт **только** в этом файле. В штатном прогоне он не исполняется — регресс в `openFeedDossier`/`dossierFeedLoop`/`dossierFeedSpeed` пройдёт молча. Python-тесты клик-путь не покрывают вообще (только API-резолв и grep-подстроки).
- **Required fix:** добавить в `tests/test_webapp_js_unit.py` тест-обёртку:
  `def test_js_unit_round1024_dossier_feed(): _run_js(os.path.join("tests", "js", "round1024_dossier_feed_test.js"), ok_marker="DOSSIER-FEED-OK")` и подтвердить, что `pytest` увеличивает счётчик и гоняет файл.

### [Medium] Кликабельные seamless-клоны: двойные таб-стопы, двойное озвучивание, дубликат в reduced-motion

- **Файлы/строки:**
  - `web/app.js:1622-1624` — клон создаётся без признака «дубль» (`Object.assign({}, it, { key: it.key + '-dup' })`).
  - `web/index.html:1549-1559` — `v-for` по `dossierFeedLoop` (2N) и на **каждой** строке `:role="... 'button'"`, `:tabindex="... 0"`, `@click`, `@keydown`.
- **Проблема:** дорожка дублируется для бесшовного цикла, и обе копии получают `role="button"` + `tabindex="0"` + обработчики. Нет ни флага у клона, ни `aria-hidden="true"`. При N=16 в таб-порядок попадают 32 кнопки, скринридер объявляет каждый факт дважды. В `prefers-reduced-motion` анимация снята, но список остаётся продублированным (2N строк) — пользователь прокручивает каждый факт два раза. Для не-интерактивных лент «Осмысления» это было безобидно, но F4 впервые сделала строки фокусируемыми, поэтому дефект привнесён именно этим изменением.
- **Why it matters:** ложные таб-стопы и дубли контента — прямой a11y-регресс на виджете, который сам же заявлен как доступный (`role`/`tabindex`/клавиатура в спеке §3.2).
- **Required fix:** маркировать клон (например `dup: true` в `marked.map`), в шаблоне для клона ставить `aria-hidden="true"`, не давать `tabindex`/`role` и не вешать обработчики (либо рендерить клон отдельным `v-for` с `aria-hidden`), чтобы в дерево доступности и таб-порядок попадала только одна копия. В reduced-motion — аналогично скрывать клон от AT.

### [Medium] `openFeedDossier` отклоняется от спеки §3.2(2) при `it.chat_id == null` и открывает досье в чужом активном чате

- **Файлы/строки:** `web/app.js:3399-3412`.
  ```js
  var chatId = (it.chat_id == null) ? null : String(it.chat_id);
  if (chatId != null && String(this.activeChatId) !== chatId) { this.setActiveChat(chatId); }
  if (this.activeChatId == null) { toast; return; }
  await this.openDossier(...);
  ```
- **Проблема:** спека §3.2(2) требует условия `activeChatId == null ИЛИ String(activeChatId) !== String(it.chat_id)` → `setActiveChat(String(it.chat_id))`, без оговорки `chatId != null`. При `it.chat_id == null` и непустом `activeChatId` текущий код **не переключает** scope и открывает досье в текущем активном чате, хотя факт принадлежит другому/неизвестному чату. Спека в этом случае ушла бы в `setActiveChat(null)` (сброс в GLOBAL) и `openDossier` корректно стал бы no-op. Сейчас API всегда шлёт `int` (0 при отсутствии), поэтому практический риск низкий, но контракт нарушен и «неверное досье» не заблокировано.
- **Why it matters:** это ровно риск R1 (GLOBAL-лента ↔ per-chat досье) — открытие чужого досье без переключения контекста; контракт, зафиксированный ADR D4, в коде не выполнен буквально.
- **Required fix:** реализовать условие спеки без `chatId != null`; для `chat_id == null/0` — явный `toast` «не удалось определить чат факта» и `return` (без открытия модалки).

### [Low] keyframes вертикали хардкодят `.25rem` вместо `--dossier-gap/2`

- **Файлы/строки:** `web/static/app.css:1043-1046` (`to { transform: translateY(calc(-50% - .25rem)); }`) при `--dossier-gap: .5rem` (`:1006`).
- **Проблема:** половина gap зашита магической константой. Цикл бесшовен ровно при `gap/2`; любое изменение `--dossier-gap` даст скачок на стыке цикла.
- **Required fix:** выразить через переменную (`calc(-50% - (var(--dossier-gap) / 2))`) либо оставить одну Константу с комментарием-инвариантом.

### [Low] Тест коллизий не воспроизводит реальный порядок БД и противоречит своему докстрингу

- **Файлы/строки:** `tests/test_dossier_feed_round1024.py:195-206`; комментарий-обоснование — `web/api/oversight.py:46-47`.
- **Проблема:** `_rows([(9, "Аня"), (3, "Аня")])` использует `SELECT user_id, author_name FROM t` без `ORDER BY` (фактически порядок вставки), а боевой `get_active_participants` (`services/database.py:3714-3726`) гарантирует `ORDER BY cnt DESC, user_id ASC`. Тест утверждает `user_id == 9`, тогда как при равном `cnt` боевой порядок дал бы **3** (меньший uid идёт первым). Докстринг теста («побеждает … меньший uid») прямо противоречит ассерту. Комментарий в коде («первым побеждает более активный (меньший uid)») тоже смешивает два правила: приоритет по `cnt DESC`, а `user_id ASC` — только tiebreaker.
- **Why it matters:** фейк не воспроизводит контракт метода, поэтому тест не поймает регресс приоритета; вводит в заблуждение при чтении.
- **Required fix:** либо гонять фейк с сортировкой `ORDER BY cnt DESC, user_id ASC`, либо проверять приоритет через реальный `get_active_participants`; выровнять докстринг/комментарий с фактическим порядком.

### [Low] `_feed_key` без Unicode-нормализации; R17-проверка логов (spec §6) отсутствует

- **Файлы/строки:** `web/api/oversight.py:35-38` (`strip().casefold()`); `tests/test_dossier_feed_round1024.py` (нет `caplog`-ассертов).
- **Проблема:** одинаковые имена в разных формах Unicode (NFKC/NFD) не совпадут → `user_id=null` без причины. Spec §6 требует «нет plaintext-секретов (R17)» — теста на логи в новом файле нет (путь секретов не содержит, но заявленная проверка не выполнена).
- **Required fix:** применить `unicodedata.normalize("NFKC", ...)` в `_feed_key`; добавить `caplog`-ассерт отсутствия сырых значений (паттерн F12 `test_probe_error_redacts_unprefixed_key`) либо явно исключить пункт из спеки.

---

## Контракт

**Чекбоксы `tasks.md`:**

| Задача | Статус | Комментарий |
|---|---|---|
| T-2213 ADR (вертикаль, click-through, GLOBAL-UX) | ✔ | `ADR-1024-8.md` D1–D5 на месте, согласован с UPD3 №9. |
| T-2214 Backend `user_id`/`user_name` | ✔ | `web/api/oversight.py:41-95,262-298`; аддитивно, read-time, без DDL. |
| T-2215 CSS вертикаль/медленнее/reduced-motion | ✔ | `web/static/app.css:997-1046,1093-1106`; бесшовность подтверждена математикой `gap` (см. Low по магической `.25rem`). |
| T-2216 Frontend клик → досье + GLOBAL switch | ⚠ | GLOBAL-путь работает; отклонение на `chat_id == null` (Medium выше). |
| T-2217 Seamless-скролл/пустое состояние | ⚠ | Дубль-массив и пустое состояние ок; клоны не помечены `aria-hidden` (Medium выше). |
| T-2218 Тесты API/клик/GLOBAL/node | ⚠ | Python-тесты есть; JS-тест написан, но **не подключён** к pytest (High выше). |
| T-2219 Ревью | — | Текущий отчёт. |
| T-2220 Деплой + приёмка | — | Вне ревью. |

**Инварианты:**

- **R16 (аддитивность API):** ✔ `items[] = {chat_id, name, excerpt, user_id, user_name}`; старые ключи не тронуты, лишних полей нет (`test_api_resolves_user_id_by_name`).
- **Δ DDL = 0:** ✔ коммит не трогает миграции/`schema`; `services/database.py` не изменён, колонка не создаётся.
- **Δ каталога = 0:** ✔ `DOSSIER_LIVE_FEED_ENABLED` — env-only `ClassVar` (`config/settings.py:652-653`), в `param_catalog` не входит (grep пуст).
- **R17/приватность:** ✔ `user_id` только в `requires_global_admin`-эндпоинте (`oversight.py:249`), новых ПД нет; △ проверки логов нет (Low).
- **`parse_mode=None`:** ✔ путь не затронут.
- **`tma-menu-freeze`:** ✔ `round1021_ui_audit_test.js` зелёный; позиционирование меню не менялось.
- **Флаг OFF → прежняя разметка:** ✔ `index.html:1567-1575` — исходный горизонтальный `role="marquee"` + 42s; front принимает `ui_flags` (`app.js:2521-2527`, default ON).
- **F1–F22 не сломаны:** ✔ полный pytest **7842 passed**; все 15 JS-гейтов зелёные.

**Тесты:**

- API-резолв/фолбэк/коллизия/мульти-чат — есть, осмысленны (кроме слабого теста коллизий).
- JS-клик-путь/скорость/флаг — осмысленны, но **не исполняются pytest** (High).
- CSS/HTML статика — по подстрокам (регресс-маркеры, допустимо, но не доказательство рендера).
- `node --check web/app.js` — OK; `node tests/js/*.js` — OK (все 15).

---

## Точный список исправлений

1. **Обязательно:** зарегистрировать `tests/js/round1024_dossier_feed_test.js` в `tests/test_webapp_js_unit.py` (маркер `DOSSIER-FEED-OK`) — соседние F3/F5/F6/F11 это сделали.
2. **Обязательно:** пометить seamless-клон и исключить его из a11y/таб-порядка (`aria-hidden="true"`, без `role`/`tabindex`/обработчиков); в reduced-motion не показывать дубль как отдельную интерактивную строку.
3. **Обязательно:** привести `openFeedDossier` к спеке §3.2: условие переключения без `chatId != null`; при `chat_id == null/0` — toast и выход без открытия модалки.
4. **Желательно:** убрать магическую `.25rem` из `@keyframes dossier-ticker-scroll-y` (выразить через `--dossier-gap`).
5. **Желательно:** переписать `test_api_collision_prefers_active_tiebreaker` под реальный порядок `ORDER BY cnt DESC, user_id ASC`; выровнять докстринг и комментарий `oversight.py:46-47`.
6. **Желательно:** Unicode-нормализация в `_feed_key`; `caplog`-проверка отсутствия секретов (R17, spec §6) — либо явное исключение пункта из спеки.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — повторный аудит (коммиты `e4c4e89` + `fea70ae`)

- **Коммиты:** `e4c4e89` — `fix(web,services,tests): раунд 10.24 F4 — регистрация JS-гейта, a11y строк, NFKC/R17, тест коллизий (review iter1)`; `fea70ae` — `fix(tests): раунд 10.24 F4 — убрать дубль регистрации JS-гейта (review iter1)`.
- **Состояние:** итоговое **HEAD `fea70ae`** (рабочее дерево по коду чистое; изменён только `plans/backlog.md`).
- **Размежевание:** между итерациями поверх влит **F11-фикс `4542311`** (`services/chat_keys.py`, `web/api/routes.py`, `tests/js/round1024_image_key_test.js`, `tests/test_byok_image_key_round1024.py`) — к F4 **не приписывается**. Собственно F4-итерация 1 — только `e4c4e89`+`fea70ae` (`web/api/oversight.py`, `web/app.js`, `web/index.html`, `web/static/app.css`, `tests/test_dossier_feed_round1024.py`, `tests/js/round1024_dossier_feed_test.js`, `tests/test_webapp_js_unit.py`).
- **Верификация:** `git show e4c4e89 --stat` (7 файлов, +173/−37), `git show fea70ae --stat` (−8), `git diff` по обоим; полный `pytest` — **7854 passed / 0 failed** (1 warning — deprecation starlette, не F4); `node --check web/app.js` — OK; все 15 гейтов `tests/js/*.js` — OK; `tests/test_dossier_feed_round1024.py` + `tests/test_webapp_js_unit.py` — 26 passed.

## Статус итерации 2

**Approved**

Итог: все шесть пунктов итерации 1 закрыты по существу, а не «на бумаге». JS-гейт F4 действительно исполняется pytest (в `tests/test_webapp_js_unit.py` ровно одна регистрация, `:96-101`; дубль из `e4c4e89` удалён `fea70ae`), клик-путь защищён реальными ассертами (включая новый кейс `chat_id null/0 → toast`), a11y-дубликаты выведены из таб-порядка и дерева доступности, условие переключения контекста строго по спеке §3.2(2), бесшовность через `--dossier-gap/2`, тест коллизий приведён к боевому `ORDER BY cnt DESC, user_id ASC` (два кейса: активность и tiebreak), добавлены NFKC-совпадение и `caplog`-проверка R17. Инварианты не нарушены: Δ DDL=0, Δ каталога=0, `parse_mode=None` не затронут, `tma-menu-freeze` зелёный, R16/R17/R18 соблюдены, `prefers-reduced-motion` сохранён и усилен. Новых дефектов итерация 2 не внесла.

## Findings итерации 2

Критических/высоких нет. Ниже — только подтверждение закрытия findings итерации 1 (без новых замечаний, блокирующих выкат).

### Закрытие [High] — JS-гейт исполняется pytest ✅

- `tests/test_webapp_js_unit.py:96-101` — ровно одна обёртка `test_js_unit_round1024_dossier_feed` с `ok_marker="DOSSIER-FEED-OK"` (проверено `grep -c` = 1).
- `e4c4e89` добавил регистрацию, `fea70ae` удалил дубль-функцию (`git show fea70ae` — чистое удаление 8 строк, содержимое верхней копии идентично).
- Проверка по существу: `pytest tests/test_webapp_js_unit.py` → зелёный, гейт `round1024_dossier_feed_test.js` реально вызывается через `_run_js` (subprocess node).

### Закрытие [Medium] a11y seamless-клонов ✅

- `web/app.js:1620,1627` — оригинал `dup: false`, клон `dup: true` (признак не теряется при `Object.assign`).
- `web/index.html:1551-1558` — класс `--dup`, `:aria-hidden="it.dup ? 'true' : null"`, `:role`/`:tabindex` только для `!it.dup`, клик/Enter/Space под `!it.dup`.
- `web/static/app.css:1109` — в `prefers-reduced-motion` `.dossier-ticker__item--dup { display: none !important; }` (в статичном списке факт не дублируется).
- JS-тест: `loop[0].dup === false`, `loop[2]/loop[3].dup === true`; статические ассерты на `aria-hidden`, `!it.dup && it.user_id != null`.

### Закрытие [Medium] контракт `openFeedDossier` / `chat_id null/0` ✅

- `web/app.js:3403-3410` — `chat_id == null || '' || '0'` → `toast('Не удалось определить чат факта')` + `return` (модалка не открывается, контекст не переключается).
- `web/app.js:3411` — условие ровно по спеке §3.2(2): `this.activeChatId == null || String(this.activeChatId) !== chatId`.
- JS-тест (блок 3a-2): два вызова (null и 0) → `switched === 0`, `opened === 0`, `toasts.length === 2`.

### Закрытие [Low] `--dossier-gap/2` ✅

- `web/static/app.css:1047` — `translateY(calc(-50% - (var(--dossier-gap) / 2)))`; валидный `calc` (деление на число, `.5rem/2`). Статический тест `test_css_seamless_uses_gap_var` + JS-ассерт на точную строку.

### Закрытие [Low] тест коллизий под боевой порядок ✅

- `tests/test_dossier_feed_round1024.py:35-49` — `_active_rows` воспроизводит `ORDER BY cnt DESC, user_id ASC`; `test_api_collision_prefers_more_active` (uid 9 с cnt 5 побеждает uid 3) и `test_api_collision_tiebreak_smaller_uid` (равный cnt → меньший uid 3). Комментарий `web/api/oversight.py:48-50` выровнен (приоритет `cnt` DESC, `user_id ASC` — tiebreaker).

### Закрытие [Low] NFKC + R17 ✅

- `web/api/oversight.py:36-40` — `unicodedata.normalize("NFKC", ...)` + `strip().casefold()`; тест `test_api_nfkc_name_match` (NFD vs NFC, с проверкой различия форм как предусловия).
- `test_api_logs_do_not_leak_raw_values` — `caplog` на `web.api.oversight` при сбое резолва: canary-excerpt и имя участника отсутствуют в логах (R17). Тест исполняет реальную warning-ветку `_feed_user_index`.

## Инварианты (итог итерации 2)

- **Δ DDL = 0:** ✅ `git diff 7eb7c69 HEAD` не затрагивает миграции/`services/database.py`.
- **Δ каталога = 0:** ✅ `DOSSIER_LIVE_FEED_ENABLED` остаётся env-only `ClassVar`, в `param_catalog` нет.
- **R16 / R17 / R18:** ✅ аддитивные `user_id`/`user_name` сохранены; добавлен `caplog`-тест R17; секреты в отчёте не цитировались.
- **`parse_mode=None`:** ✅ путь не затронут.
- **`tma-menu-freeze`:** ✅ `round1021_ui_audit_test.js` зелёный, полный pytest зелёный.
- **`prefers-reduced-motion`:** ✅ сохранён и усилен (скрытие клона).
- **Регрессы F1–F22:** ✅ полный pytest **7854 passed**, 15/15 JS-гейтов OK.

## Вердикт

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше (`T-2220` — деплой и живая приёмка в TMA: направление/скорость и переход в досье по клику).
