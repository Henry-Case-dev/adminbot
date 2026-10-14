# Аудит раунда 10.24 — F7 `anticliche-cron-limit-round1024` (шаг 5)

- **Ревьюер:** @Reviewer
- **Коммит:** `7ca704e` (HEAD работы) · База сравнения: `7ca704e^`
- **Спека/ADR/задачи:** `spec.md`, `ADR-1024-3.md`, `tasks.md`; карта `round1024-architecture.md` (§3.3, §4, §5, §6)
- **ТЗ:** `plans/current_task.md` UPD2 п.5 (188–193), UPD3 п.3 (248–249). Секреты не цитируются (R17/R18).

**Статус: Changes Requested**

Итог: ядро задачи сделано — искусственный потолок 20 снят в логике (`cache`/`worker`/промпт/API), резолв `max_patterns()` с дефолтом 200, hard-ceiling 1000, clamp и fail-safe работают; крон получил `next_run_time = now + 5 мин` и `freshness-skip`, `max_instances/coalesce/misfire` сохранены; фазы пишутся через `external_log`. Каталоговые пины **фактически** совпадают (см. «Контракт»), полный pytest зелёный. Но в **той же самой фиче остался второй жёсткий потолок — `_MANUAL_INPUT_CAP = 200`**, который ломает ручную правку для лимитов >200 (вплоть до заявленных 1000) и отдаёт пользователю 422 на значение, которое UI сам разрешает. Плюс UI-поле лимита не имеет ни одного JS-теста на сохранение/валидацию, а в контексте чата правка уходит в per-chat слой, который воркер не читает. Это не «придирки к комментариям» — это реальные дыры приёмки UPD3 №3 («регулируемый лимит из UI реально применяется»).

---

## Findings

### [Severity: High] Ручная правка жёстко обрезана 200 при заявленном потолке 1000

- **Файл:** `web/api/anticliche.py`
- **Локация:** строка 29 (`_MANUAL_INPUT_CAP = 200`), строки 114–117 (`if len(payload.patterns) > _MANUAL_INPUT_CAP` → 422)
- **Проблема:** фича снимает хардкод 20 и делает лимит регулируемым до 1000 (`ANTICLICHE_MAX_PATTERNS_HARD_CEILING`), UI-поле объявляет `min=1 max=1000`, но путь `PUT /api/anticliche` (кнопка «Ручное редактирование» в той же карточке) по-прежнему отбивает всё, что длиннее 200.
- **Почему это больно:** владелец выставляет лимит, например, 500, воркер приносит 500 фраз, UI их показывает. При попытке отредактировать список кнопкой «Сохранить список» приходит `422 «слишком много паттернов (>200)»` и тост «Не удалось сохранить список анти-клише». То есть интерфейс обещает 1–1000, а половина управления на 201+ мертва. Это ровно тот класс дефектов («мёртвая ручка»), который в этом репозитории уже вычищали.
- **Fix (обязательно):** привязать лимит ручного ввода к резолвленному потолку, а не к константе. Например: `_MANUAL_INPUT_CAP` брать как `anticliche_cache.max_patterns()` (или `ANTICLICHE_MAX_PATTERNS_HARD_CEILING`), вычисляя его в момент запроса; серверная нормализация `build_patterns()` всё равно обрежет до `max_patterns()`. Добавить тест: список в 201–1000 элементов проходит (и усекается до резолвленного лимита), а не даёт 422.

### [Severity: Medium] Лимит, сохранённый из UI в контексте чата, — «мёртвая ручка»

- **Файл:** `web/app.js` (строка 4016 — `saveClicheLimit` → `saveConfigItem`), `services/anticliche_cache.py` (строки 36–52 — `max_patterns()`)
- **Локация смежная:** `web/app.js:4447` (`isGlobal = item.per_chat === false`), `web/app.js:1740` (X-Chat-Id), `services/hot_config.py:71` (`hot.get` читает только глобальный `_settings`)
- **Проблема:** ключ `limits.anticliche_max_patterns` категории `limits` → `ParamSpec.per_chat == True`. Если глобальный админ в селекторе контекста выбрал конкретный чат, `saveClicheLimit` → `saveConfigItem` уйдёт с `X-Chat-Id` и запишет per-chat слой. Воркер же резолвит лимит через `hot.get(...)` (глобальный слой) и `get_rules()` — это глобальный in-process детектор. Per-chat значение не читает никто.
- **Почему это больно:** владелец меняет число, видит «Сохранено», но фильтр бота не меняется — ровно симптом «лимит не применился», с которого начинался раунд. По умолчанию (`activeChatId == null`, «Весь бот») путь корректный, поэтому severity Medium, но ловушка реальная и тихая.
- **Fix (обязательно):** заставить именно это поле сохраняться в глобальный слой — вызвать `saveConfigItem` в режиме `global: true` (или в `saveClicheLimit` сделать выделенный POST `POST /api/config` с `global:true`), т.к. динамический кэш анти-клише — глобальная сущность. Альтернатива — явный per-chat-резолв в `max_patterns()`, но у воркера нет chat_id, поэтому предпочтительно глобальное сохранение.

### [Severity: Medium] Ноль JS-покрытия на сохранение/валидацию поля лимита; фикстура закрепляет старый 20

- **Файл:** `tests/js/round1023_verbilizer_tabs_test.js`
- **Локация:** строки 184 (`max_patterns: 20`), 197–210 (только инициализация черновика), `saveClicheLimit` не вызывается вообще
- **Проблема:** ключевой элемент приёмки UPD3 №3 — числовое поле ввода лимита — не покрыт: не проверены ни корректный save (payload с ключом `limits.anticliche_max_patterns` и int-значением), ни валидация `1..1000`, ни ветка «лимит не загружен», ни ре-загрузка. При этом мок до сих пор возвращает `max_patterns: 20` — старый снятый хардкод, что маскирует регрессию «дефолт 200».
- **Почему это больно:** сломать `saveClicheLimit` (переименование ключа, потеря int-приведения, отключённая кнопка) можно молча — Python-тесты этого не видят, JS-гейт тоже.
- **Fix (обязательно):** добавить в JS-тест сценарии `saveClicheLimit`: (1) валидное значение → ожидается POST `/api/config` с `items[0].key === 'limits.anticliche_max_patterns'` и числом; (2) `0`, `-1`, `1001`, `'abc'` → тоста ошибки и отсутствие POST; (3) мок `/api/anticliche` заменить на `max_patterns: 200` и утвердить `clicheLimitDraft === '200'` при пустом `configItems`.

### [Severity: Low] Устаревший docstring описывает «~20 паттернов»

- **Файл:** `services/anticliche_worker.py`
- **Локация:** строки 1–7 (модульный docstring: «просит LLM извлечь до ~20 популярных ИИ-паттернов»)
- **Проблема:** после снятия потолка 20 docstring противоречит коду и ADR-1024-3. Модуль теперь извлекает до резолвленного лимита (дефолт 200).
- **Fix:** обновить фразу docstring на «до резолвленного лимита (дефолт 200, регулируется `limits.anticliche_max_patterns`)».

### [Severity: Low] Поле лимита недоступно, если анти-клише API вернуло ошибку

- **Файл:** `web/index.html`
- **Локация:** строка 379 (`v-if="isGlobalAdmin && clicheAvailable"`), строка 450 (группа `limits_anticliche` исключена из generic-рендера)
- **Проблема:** параметр живёт только внутри карточки монитора. При `clicheAvailable === false` (сбой `GET /api/anticliche`) generic-карточка группы скрыта, а поле не рендерится — параметр становится недоступен для редактирования.
- **Fix (по возможности):** при `!clicheAvailable` оставлять generic-рендер группы `limits_anticliche` (то есть исключать её из generic-цикла только когда карточка монитора реально отрисована: `v-if="grp.id !== 'limits_anticliche' || !(isGlobalAdmin && clicheAvailable)"`).

### [Severity: Low] Изменения `web/**` влиты в Part-1 (backend-core) коммит

- **Файл:** `web/app.js` (+52), `web/index.html` (+25)
- **Локация:** `round1024-architecture.md` §5 (web-очередь Part 2) и `spec.md` §4 («Часть 2, web-очередь»)
- **Проблема:** карта фиксирует ступень `web/**` за Частью 2. Функционально это правильно (UPD3 требует поле), но процессно нарушает правило ступеней вливания — риск конфликтов с F3→F5→F6→F11→F4→F10.
- **Fix:** зафиксировать в отчёте раунда, что F7-UI влит вне очереди Части 2 (осознанное исключение владельца), либо перенести web-часть в UI-коммит. Блокером не считаю.

---

## Контракт: чекбоксы / инварианты / тесты / Δ каталога

### 1. Лимит
- [x] `ANTICLICHE_MAX_PATTERNS_DEFAULT=200`, `..._HARD_CEILING=1000`, deprecated-alias сохранён (`services/anticliche_cache.py:30-33`).
- [x] `max_patterns()`: `hot → settings → clamp [1,1000]`, fail-safe на мусор/None (проверено тестами 0/−5/1/5000/«мусор»).
- [x] Хардкод 20 снят в рабочих точках: `_rules_from_patterns` (`:120`), `build_patterns` (`anticliche_worker.py:177-178`), промпт `EXTRACT_SYSTEM_PROMPT.format(max=…)` (`:472-473`), API (`web/api/anticliche.py:79`).
- [x] Каталог: ключ `limits.anticliche_max_patterns` (группа `limits_anticliche`, вкладка `prompts`) + UI-числовое поле `1..1000`.
- [ ] **Ручной путь `PUT /api/anticliche` жёстко обрезан 200** — см. Finding High.

### 2. Крон
- [x] `next_run_time = now + ANTICLICHE_FIRST_RUN_DELAY_MINUTES` (env-only, 5), затем `IntervalTrigger(days=7, jitter=3600)` (`anticliche_worker.py:262-271`).
- [x] `max_instances=1`, `coalesce=True`, `misfire_grace_time=3600` сохранены.
- [x] `freshness-skip` по `fetched_at` (< `REFRESH_DAYS`) без job store и без DDL; `None`/мусор → fail-open (прогон состоится).
- [x] Ручной refresh — `force=True` (`web/api/anticliche.py:95`).
- [x] Проверено по исходникам APScheduler: `jitter` положительный (`random.uniform(0, jitter)`), поэтому «двойного пропуска» (refresh раз в ~14 дней) не возникает — снимаю как риск.

### 3. Логирование
- [x] `trace_step` фазы `schedule|gate|fetch|llm|parse|empty|write|budget`; `_refresh_level` относит `fresh/skip/empty/budget_skip/disabled` к INFO, сбои — ERROR.
- [x] R17-safe: в логах только `status/reason/count/version/source/raw_len/error`, фразы и секреты не пишутся.

### 4. Инварианты
- [x] Клише не в промпте и не режутся regex: `EXTRACT_SYSTEM_PROMPT` не менялся по смыслу (только `{max}`); grep-тест тропов `tests/test_anticliche_round1023.py:324` зелёный.
- [x] `physical-two-call` не затронут (фон вне счётчика).
- [x] Egress/secловые реестры, `parse_mode=None`, порядок роутеров `bot.py` — коммит их не трогает (`bot.py` отсутствует в `--stat`).
- [x] R16 (аддитивность API), R17/R18 — соблюдены.
- [x] `tma-menu-freeze`: `TAB_RULES == 20`, `TAB_NAV == 20`; новых табов нет, добавлена только группа внутрь `prompts`.

### 5. Δ каталога — проверено фактическим прогоном (не по комментариям)
```
REGISTRY 458 · GROUPS 97 · _TAB_BY_GROUP 95 · TAB_RULES 20
Settings fields 417 · categorized 433
categories: limits 192, models 56, flags 66, reactions 39, prompts 21,
            keys 20, content 5, memory 34, None 25
```
Пины совпадают со спекой и не «подогнаны»: тесты `param_catalog`, `frontend_tab_mapping`, `budget_settings`, `help_guide`, `round106_ia_smoke`, `settings_persistence`, `self_reflection`, `ui_verbilizer_tabs`, `webapp_api`, `webapp_parity` обновлены согласованно. `ANTICLICHE_FIRST_RUN_DELAY_MINUTES` — `ClassVar`, в `dataclass.fields` не входит, что корректно.

### 6. Тесты
Запущено:
- `tests/test_anticliche_cron_limit_round1024.py` + `test_anticliche_round1023.py` + `test_param_catalog.py` + `test_frontend_tab_mapping.py` → **168 passed**.
- `node tests/js/round1023_verbilizer_tabs_test.js` → **VERBILIZER-UNIT-OK**.
- `.venv/Scripts/python.exe -m pytest -q` → **7498 passed** (заявленная цифра подтверждена).

Содержание: резолв/дефолт/clamp/hard-ceiling/fail-safe, парсер >20, явный лимит, hot-лимит в парсере и правилах, `next_run_time` ≈5 мин и interval days=7, env-настройка задержки, freshness `recent/old/bad`, skip без LLM, force игнорирует freshness, устойчивость `tick` — **не тавтологичны**. Провал — JS-путь (см. Finding Medium).

### 7. F1/F2 не сломаны
Полный прогон 7498/0 после коммита F7 при уже влитых F1/F2 — регрессий нет.

---

## Вердикт

**Changes Requested.** Отклонить до устранения: (1) жёсткий потолок ручного ввода 200 при заявленном 1–1000 (`web/api/anticliche.py`); (2) сохранение лимита в глобальный слой, а не в невидимый воркеру per-chat (`web/app.js`); (3) JS-тесты на `saveClicheLimit`. Остальное — после исправления (Low).

После правок прошу приложить: целевой прогон `tests/test_anticliche_cron_limit_round1024.py` + `test_anticliche_round1023.py`, JS-гейт и подтверждение полного pytest.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — повторный аудит

- **Коммит правок:** `59f4cc4` (родитель — `7ca704e`; F1 `391f97d` и F2-фикс `27296bb` — предки, их не приписываю).
- **Изменённые файлы (`--stat`):** `services/anticliche_worker.py`, `web/api/anticliche.py`, `web/app.js`, `web/index.html`, `tests/js/round1023_verbilizer_tabs_test.js`, `tests/test_anticliche_round1023.py`. Никаких F1/F2-файлов, миграций и DDL.

**Статус: Approved**

## Проверка по замечаниям итерации 1

### [Закрыто — High] Ручной cap больше не 200
- `web/api/anticliche.py:29` — введена `_manual_input_cap() → ANTICLICHE_MAX_PATTERNS_HARD_CEILING` (1000); `:121` использует её; 422 только при `>1000`.
- Подтверждено тестами `TestAnticlicheApi` (12 passed) и целевым `-k "manual or put"`:
  - `test_put_over_resolved_limit_truncates` — 201 фраза → **200**, без 422;
  - `test_put_accepts_up_to_1000_with_custom_limit` — лимит 1000, 600 фраз → **600**;
  - `test_put_422_over_hard_ceiling` — 1001 → **422**.
- Мёртвой ручки `_MANUAL_INPUT_CAP` в коде не осталось (только упоминание в docstring теста).

### [Закрыто — Medium] Глобальное сохранение лимита
- `web/app.js:4013` — `saveClicheLimit` формирует `payload = Object.assign({}, it, { per_chat: false, value: val })`, поэтому `saveConfigItem` уходит по глобальному пути (`isGlobal = item.per_chat === false` → `global:true`, без `X-Chat-Id`).
- Серверный путь подтверждён: `web/api/routes.py:465-467` — при отсутствии `X-Chat-Id` вызов уходит в `_post_config_global`, где ветка `not spec.per_chat → 422` **не применяется** (она только для per-chat записи). Глобальная запись per-chat-ключа не отбивается.
- Цепочка «глобальная запись → воркер» подтверждена ад-хок прогоном: `ConfigCache.set` обновляет `_settings` (`config_cache.py:499-505`), `hot.get` его читает, `max_patterns()` вернул заданное значение (200 → 777). Итого: не per-chat no-op.
- JS-тест секции 3.7 утверждает `cfgPost.global === true` и корректный ключ/числовое значение — регресс вернёт `global:false` и тест покраснеет.

### [Закрыто — Medium] JS-покрытие `saveClicheLimit`
- Секции 3.7–3.9 JS-теста: (3.7) валидное 500 → ровно один `POST /api/config`, `global:true`, `items[0].key === 'limits.anticliche_max_patterns'`, значение — число 500, тост `ok`, `clicheBusy` сброшен; (3.8) `0/-1/1001/abc` → без POST, тост `err`; (3.9) пустой `configItems` → без POST, тост `warn`.
- Тесты используют реальные `methods.saveClicheLimit` и `methods.saveConfigItem` (не заглушки), проверяют наблюдаемый сетевой эффект — **не тавтологичны**. Мок `/api/anticliche` переведён на `max_patterns: 200`, черновик инициализируется `'200'`.

### [Закрыто — Low] Docstring и доступность поля
- `services/anticliche_worker.py:1-7` — «до резолвленного лимита (дефолт 200, … `limits.anticliche_max_patterns`; ADR-1024-3 D1)».
- `web/index.html:450` — группа `limits_anticliche` отдаётся generic-рендеру, если карточка монитора недоступна (`!(isGlobalAdmin && clicheAvailable)`); при доступном мониторе поле остаётся внутри карточки. Двойного рендера нет.

## Инварианты / Δ после итерации 2
- Δ каталога (фактический прогон): `REGISTRY 458 · GROUPS 97 · _TAB_BY_GROUP 95 · TAB_RULES 20 · TAB_NAV 20 · Settings 417 · categorized 433` — без изменений, подгонки нет.
- Δ DDL = 0: новых таблиц/колонок/миграций в коммите нет.
- `tma-menu-freeze`: `TAB_RULES/TAB_NAV` = 20, структура табов не менялась.
- Инварианты не затронуты: промпт `EXTRACT_SYSTEM_PROMPT`/grep тропов, `physical-two-call`, egress, R16/R17/R18, `parse_mode=None`, порядок роутеров `bot.py` — коммит их не касается.
- F1/F2 не сломаны: изменённые файлы относятся только к F7.

## Прогоны итерации 2
- `pytest tests/test_anticliche_round1023.py tests/test_anticliche_cron_limit_round1024.py tests/test_param_catalog.py tests/test_frontend_tab_mapping.py` → **170 passed**.
- `pytest tests/test_anticliche_round1023.py::TestAnticlicheApi` → **12 passed**.
- `node tests/js/round1023_verbilizer_tabs_test.js` → **VERBILIZER-UNIT-OK**.
- `.venv/Scripts/python.exe -m pytest -q` → **7500 passed / 0 failed** (заявленная цифра подтверждена).

## Остаточные (не блокирующие) замечания
- **[Low, UX]** При ручной вставке списка больше резолвленного лимита (например, 500 при лимите 200) сервер молча усечёт до 200 и вернёт `count=200`, а `saveCliche()` покажет общий тост «Список сохранён». Явного предупреждения об усечении нет. Не блокер (поведение соответствует «нормализация/усечение» из ADR-1024-3 D1), но в будущем полезно показать «сохранено N из M».
- **[Low]** JS-тест не покрывает граничные валидные значения `1` и `1000` (покрыты `500`, инвалидные 0/-1/1001/abc). Не блокер.

**Вывод:** замечания итерации 1 закрыты корректно и с тестами; регрессий нет. F7 принимается.

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.
