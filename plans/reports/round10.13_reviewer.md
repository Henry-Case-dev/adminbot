# Round 10.13 — Reviewer QA / Validator / Security Audit

> Аудитор: @Reviewer (Step 5, строгий QA). Дата: 13.09.2026. База: HEAD `ce25dc7`, рабочее дерево (uncommitted).
> Объём: 50 изменённых файлов + 7 новых модулей/каталогов/тестов (`git diff` + untracked).
> Спеки: F1–F8 (`plans/features/cognition-*-round1013/spec.md` + `tasks.md`), ADR-1013-1/2/3, `plans/current_task.md`.

## 1. Сводка

**ВЕРДИКТ: Approved** (финал). Итерация 1 — Rejected (см. §7, сохранено как история);
итерация 2 — все блокеры/замечания закрыты и подтверждены с `file:line` (см. §8).

_(Ниже — обоснование отклонения по итогам **итерации 1**; все перечисленные дефекты закрыты
и подтверждены в §8, итоговый вердикт — Approved.)_

Контракт (все чек-боксы `[x]`, `🟢 IMPLEMENTED`) выполнен формально, но при спот-проверке
кода найдены **две функциональные ошибки** (одна — прямой недодел мандатной задачи T-1439),
а также отклонение от спеки по анти-галлюцинациям парадигм и регрессии по производительности
дашборда. Код «на бумаге» по F3-T-1439 закрыт неправдой: серверный роутер `generate_worker`
не подключён к обязательным воркерам v1 (Lore/Dream). Validator-прогоны при этом зелёные —
именно это и опасно: задача закрыта тестами, которые не проверяют требуемое поведение.

## 2. Таблица по фичам

| Фича | Задач | Реализация в коде | Замечание |
|---|---|---|---|
| F1 `4d-memory` | T-1417…T-1423 | ✓ | `_fact_prefix`/`_stale_suffix`/4-кортежи/`dig_into_lore`/хроно-сон — подтверждено |
| F2 `belief-decay` | T-1424…T-1433 | ✓ | decay/resonance/reanimator/graph-activation — подтверждено тестами |
| F3 `deep-sleep` | T-1434…T-1442 | ✗ | T-1439 (роутер воркеров) выполнен ЧАСТИЧНО (см. BLOCKER-1) |
| F4 `llm-providers` | T-1443…T-1447 | ✓ | 2 блока, 8 ключей, probe, каталог — подтверждено |
| F5 `dashboard` | T-1448…T-1458 | ~ | UI/API на месте, но API ностальгии отдаёт неверные данные (BLOCKER-2); граф пере-рендерится каждые 15с |
| F6 `ekg-logs` | T-1459…T-1464 | ✓ | EKG + `ERROR+WARNING` + дефолт/рассинхрон — подтверждено |
| F7 `user-guide` | T-1465…T-1467 | ✓ | гайд без жаргона (grep 0), README — ок (счётчик тестов занижен на 1) |
| F8 `irony-dossier` | T-1468…T-1476 | ✓ | фильтр/`chat_meme`/блоки — подтверждено |

Итог: **60/60** задач проверено, **59** подтверждено в коде, **1** (T-1439) — не подтверждён.

## 3. Найденные проблемы

### BLOCKER-1 — [Severity: Critical] T-1439: роутер воркеров не подключён к обязательным воркерам v1

- Файл: `services/dream_worker.py:766`
- Локация: `DreamWorker._llm_once` → `raw = await self.llm.generate(messages, temperature=0.3)`
- Проблема: выделенная «LLM для фоновых проверок» (`keys.intel_bg_api_key`) не используется синтезом «сна».
  Вызов идёт напрямую основной моделью, минуя `generate_worker("background", ...)`.
- Файл: `services/lore_worker.py:468`
- Локация: `LoreWorker._run_generation` → `raw = await self._llm.generate([...])`
- Проблема: выделенная «LLM для Исторической памяти (Вехи/Лор)» (`keys.intel_history_api_key`) не используется
  самим воркером лора. На заявленную роль history уходит только **новый** «Мост времени» глубокого сна
  (`services/dream_worker.py:1280`), а на background — только **новый** шаг классификации досье
  (`services/lore_worker.py:578`).
- Доказательство: `grep -rn generate_worker services/` → только `dream_worker.py:1280` и `lore_worker.py:578`.
- Почему важно: spec F3 §5 (F3-Q5) прямо фиксирует «**Обязательные в v1: LoreWorker → history,
  DreamWorker → background**, deep-sleep bridge → history». T-1439 помечен `[x]`, README (раунд 10.13)
  утверждает «Лор и „Мост времени“ уходят к исторической модели, Сон и Ностальгия — к фоновой» — это
  не соответствует коду. Пользователь заполнит блоки в UI, но обычные синтез лора/сна продолжат ходить
  в основную модель; ТЗ §3 («перед вызовом нейросети в фоновых воркерах») не выполнен.
- Required fix: заменить `self._llm.generate(...)` на `generate_worker("history", ...)` в
  `LoreWorker._run_generation` и на `generate_worker("background", ...)` в `DreamWorker._llm_once`
  (роутер уже умеет фоллбэк при пустых ключах); добавить тесты, что роль history/background реально
  вызывается в этих путях (сейчас такие тесты отсутствуют).

### BLOCKER-2 — [Severity: High] `/api/memory/cognition/status`: перепутаны аргументы ностальгии

- Файл: `web/api/memory_agi.py:486`
- Локация: `"nostalgia": _nostalgia_state(sent_ts, last_user, now, silence_min, cooldown_h)`
- Проблема: сигнатура — `_nostalgia_state(last_user_ts, sent_ts, ...)` (`memory_agi.py:372`). Передано
  наоборот: первым идёт `sent_ts` (время отправки ностальгии), вторым — `last_user` (последнее сообщение).
  Из-за этого режим и таймеры считаются от чужих значений (например, при отправленной час назад ностальгии
  и последнем сообщении 10 мин назад виджет покажет «Кулдаун: ещё 12 ч» вместо «Тишина: 35/45 мин»).
- Дополнительно: `web/api/memory_agi.py:468` — `db.get_last_user_message_ts(int(chat_id), None)`.
  `database.py:2262` фильтрует `user_id != int(bot_id or 0)`, т.е. при `None` **сообщения бота не
  исключаются** (в `nostalgia_worker.py:299` передаётся `self.bot_id`). «Последнее юзерское сообщение»
  фактически становится последним сообщением вообще (включая бота).
- Почему важно: ТЗ §7 и F5 §4.3 требуют корректный таймер `[📻 Ностальгия]` (тишина/кулдаун).
  Тест `test_shape_and_budget` вызывает `cognition_status(chat_id=None)` и дефект не ловит.
- Required fix: вызвать `_nostalgia_state(last_user, sent_ts, ...)`; резолвить реальный bot_id (или
  расширить `get_last_user_message_ts` для корректного исключения бота) и добавить интеграционный тест
  с заданным `chat_id`, проверяющий режим/остаток.

### ISSUE-3 — [Severity: Medium] Анти-галлюцинации парадигм слабее спеки (min_anchors=1)

- Файл: `services/dream_prompts.py:235-236, 277` и `services/dream_worker.py:1172, 1182`
- Проблема: `parse_bridge_answer(..., min_anchors: int = 1)`; вызовы передают только `anchor_count=...`,
  поэтому парадигма с **одной** исторической опорой принимается и записывается. Спека F3 §4/промпт
  требует «Каждая парадигма опирается минимум на **2** исторических факта»; тест
  `test_anchors_out_of_range_dropped` даже фиксирует результат `anchors:[1]`.
- Почему важно: ослаблен анти-галлюцинационный контур; мета-факт может строиться на одном якоре.
- Required fix: вызывать `parse_bridge_answer(raw, anchor_count=len(historical), min_anchors=2)` и
  обновить тесты.

### ISSUE-4 — [Severity: Medium] F5: polling каждые 15с полностью пере-рендерит граф

- Файл: `web/app.js:4817` (`loadCognition`) → `:4840` `this.loadCognitionGraph()`; `:4886`
  (`loadCognitionGraph`) → `renderCognitionGraph` → `destroyCognitionGraph()` + `new vis.Network(...)`.
- Проблема: `startCognitionPolling` каждые 15с вызывает `loadCognition`, который всегда заново тянет
  граф и уничтожает/создаёт экземпляр vis-network. Это сбрасывает drag/zoom/physics (позиции узлов)
  каждые 15 секунд и нагружает Canvas на Android WebView.
- Почему важно: спека F5 §4.1 (влияние новых элементов «без полной перерисовки») и §10/ADR-1013-2
  («граф тормозит Android» → cap/lazy/physics-off) — прямое расхождение.
- Required fix: грузить/рендерить граф только при входе на вкладку/явном обновлении; в polling обновлять
  только данные лент/статуса (или сравнивать данные и не пересоздавать `vis.Network` при отсутствии изменений).

### ISSUE-5 — [Severity: Low] README: счётчик тестов занижен

- Файл: `README.md:5`
- Проблема: указано «**Тестов:** 5373», фактический полный прогон — **5374 passed**.
- Required fix: синхронизировать с фактическим числом (или зафиксировать тестом).

### ISSUE-6 — [Severity: Low] `worker_budget`: позиция deep_sleep противоречит комментарию

- Файл: `services/worker_budget.py:135-137`
- Проблема: `absolute.setdefault(WORKER_DEEP_SLEEP, 0)` даёт deep_sleep ту же позицию, что и dream
  (0), т.е. падает одновременно с обычным сном, а не «первым» (как утверждает docstring). Тестами
  это не покрыто (матрица в `test_feature_gates.py` использует только legacy-ids).
- Required fix: явно задать позицию (например, сдвинуть legacy-матрицу на 1 и дать deep_sleep=0) либо
  поправить комментарий и добавить deep_sleep в матричный тест.

### ISSUE-7 — [Severity: Low] Мелкие загрязнения/несоответствия

- `web/index.html:2919,2932` — класс `ribbon-static` вешается реактивно, но в CSS не определён
  (reduced-motion фактически закрыт media-query; класс мёртвый).
- `services/summary_memory.py:2066-2067` — устаревший комментарий про `[%Y-%m-%d] ` (код уже `[ММ.ГГГГ]`).
- `services/summary_memory.py:727` — алиас `_date_prefix = _fact_prefix` не используется (мёртвая обёртка).
- `web/app.js:1307` — `visibilitychange`-листенер добавляется и не снимается в `beforeUnmount`
  (приложение-синглтон, практического вреда нет — зафиксировано как долг).
- ADR-1013-2 §2 упоминает `vis-data.min.js`; закоммичен только `vis-network.min.js` (standalone UMD
  содержит vis-data, функционально ок — расхождение с ADR).
- `services/dream_prompts.py:189-190` `_anchor_date` использует локальную TZ, тогда как остальной рендер
  дат — UTC (`_fact_prefix`); незначительно, но несогласованно.

## 4. Результаты Validator

| Проверка | Команда | Результат | Exit |
|---|---|---|---|
| Python tests | `.venv/Scripts/python.exe -m pytest -q` | **5374 passed, 1 warning** (60.39s) | 0 |
| JS syntax | `node --check web/app.js` | clean | 0 |
| JS unit | `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| Whitespace | `git diff --check` | clean | 0 |

Примечание: `WARNING: closed 12 leaked aiosqlite connection(s)` — существующий шум тестов, не блокер.

## 5. Соответствие инвариантам

- **Ноль новых PG-DDL:** ✓ (в диффе нет `CREATE/ALTER/DROP/ADD COLUMN`; `pg_db.py`/миграции не тронуты).
- **SQLite schema v8:** ✓ (`_SCHEMA_VERSION_AGI_MEMORY = 8`, бампов нет).
- **Порядок роутеров `bot.py`:** ✓ не изменён; только DI-kwargs (`aliases=` в `LoreWorker`).
- **R17 (секреты `{configured,last4}`):** ✓ по коду и тестам (`/api/llm/test` без эха; в логах — только
  role/model/длина ответа); сырые ключи наружу не уходят.
- **Каталог:** ✓ проверено рантаймом — REGISTRY **427**, categorized **403**, GROUPS **90**, mapped **88**
  (`_TAB_BY_GROUP`), TAB_RULES **19**, Settings **399**.
- **vis-network без CDN:** ✓ self-host `/static/vendor/vis-network/vis-network.min.js` (vis 9.1.9, UMD,
  `window.vis`); CDN остался только для существующих tailwind/vue/chart.js (пре-экзистинг).
- **XSS:** ✓ в новых Vue-разделах только `{{ }}`; новых `v-html` нет (существующие `sanitizeHtml`).
- **Секреты в доках:** ✓ пароль/реквизиты из `plans/current_task.md` в README/гайд/ADR не попали.
- **F7 запрещённый жаргон:** ✓ grep по RAG/LLM/STT/API/токен/вектор/эмбеддинг/промпт/JSON/SQLite/PG/cron/
  воркер/пайплайн/«база данных» в `plans/docs/intelligence_user_guide.md` — **0** совпадений.

## 6. Формальный контракт

- Все 8 `tasks.md`: открытых `[ ]` — **0**, статус — `🟢 IMPLEMENTED`. ✓
- T-1417…T-1476 (60 задач): реализованы, кроме **T-1439** (BLOCKER-1). ✗

## 7. Вердикт итерации 1 (историческая запись)

**Rejected** (на момент итерации 1; впоследствии закрыто в §8).

Блокеры для @Builder (в порядке приоритета):

1. Подключить роутер `generate_worker` к мандатным воркерам v1: `LoreWorker._run_generation` → `history`,
   `DreamWorker._llm_once` → `background` (+ тесты на факт вызова роли и фоллбэк). (BLOCKER-1)
2. Исправить `cognition_status`: порядок аргументов `_nostalgia_state` и корректное исключение сообщений
   бота при расчёте тишины; добавить интеграционный тест с `chat_id`. (BLOCKER-2)
3. Ужесточить приём парадигм (`min_anchors=2`). (ISSUE-3)
4. Не пере-рендеривать vis-network в 15с-polling. (ISSUE-4)
5. Закрыть Low-замечания (README-счётчик, worker_budget-позиция, мёртвый класс/комментарии).

После исправления — повторный полный прогон Validator и повторное ревью.

---

## 8. Повторное ревью (итерация 2)

> Аудитор: @Reviewer. Дата: 13.09.2026. База: HEAD `ce25dc7`, рабочее дерево (uncommitted).
> Метод: прямая проверка кода с `file:line` + полный прогон Validator.

### 8.1. Подтверждение исправлений

**BLOCKER-1 [Critical] T-1439 — ПОДТВЕРЖДЕНО (закрыт).**
- `services/lore_worker.py:471` — `_run_generation` вызывает `self._worker_llm("history", [...])`.
- `services/lore_worker.py:580-588` — `_worker_llm`: `generate_worker(role, ...)` при наличии, фоллбэк `generate(...)` для легаси-моков.
- `services/dream_worker.py:779` — `_llm_once` вызывает `self._worker_llm("background", ...)` (темп. 0.3).
- `services/dream_worker.py:762-771` — `_worker_llm` с фоллбэком на `generate`.
- `services/dream_worker.py:1291-1301` — deep-sleep bridge `_deep_llm_once` → `_worker_llm("history")` (F3-Q5).
- `services/nostalgia_worker.py:585-593, 607` — Nostalgia → `background` (рекомендовано F3-Q5).
- `services/llm_client.py:921-954` — `generate_worker`: нет dedicated → `generate`; исключение/пустой контент → WARNING + `generate` (fail-open). R17: логируются только role/model/out_chars.
- Тесты: `tests/test_lore_worker.py:764-791` (history + legacy-фоллбэк), `tests/test_dream_worker.py:511-529` (background + legacy), `tests/test_nostalgia_worker.py:384-401` (background), `tests/test_deep_sleep.py:464-542` (dedicated/пусто→основная/ошибка→основная/unknown role/R17).
- Прямых вызовов `llm.generate(...)` в боевых путях воркеров не осталось — только fallback-ветки при отсутствии роутера (`grep` подтверждён).

**BLOCKER-2 [High] `/api/memory/cognition/status` — ПОДТВЕРЖДЕНО (закрыт).**
- `web/api/memory_agi.py:372` — сигнатура `_nostalgia_state(last_user_ts, sent_ts, ...)`.
- `web/api/memory_agi.py:492` — вызов `_nostalgia_state(last_user, sent_ts, now, silence_min, cooldown_h)` — порядок верный.
- `web/api/memory_agi.py:470-473` — реальный `bot_id` резолвится из `lore_runtime.get_nostalgia_worker().bot_id` и передаётся в `db.get_last_user_message_ts(int(chat_id), bot_id)`.
- `services/database.py:2255-2267` — фильтр `user_id IS NOT NULL AND user_id != int(bot_id or 0)`; бот исключается.
- Интеграционный тест: `tests/test_webapp_round1013_f5_ui.py:137-176` — с заданным `chat_id`, вставлены сообщение юзера (60 мин назад), сообщение бота (1 мин назад), sent-ностальгия (2 ч назад) → ожидается `mode=cooldown`, `cooldown_left_h=10` (swap дал бы 11ч, включение бота — silence). Проверка нетривиальная и ловит дефект.
- Модульный тест режимов: `tests/test_webapp_round1013_f5_ui.py:178-193`.

**ISSUE-3 [Medium] min_anchors — ПОДТВЕРЖДЕНО (закрыто).**
- `services/dream_prompts.py:238` — `parse_bridge_answer(raw, anchor_count=0, min_anchors=2)` (дефолт 2).
- `services/dream_worker.py:1186-1188` и `:1197-1198` — вызовы явно передают `min_anchors=2` (sync и retry).
- Гейт `dream_prompts.py:280` — `len(anchors) < max(1, int(min_anchors))` → при 2 парадигма с 1 якорем отбрасывается.
- Тесты `tests/test_deep_sleep.py:182-215` обновлены (в т.ч. явное ослабление `min_anchors=1` как отдельный кейс). Спека F3 §4/промпт (`dream_prompts.py:166`) требует «минимум на 2» — соответствие достигнуто.

**ISSUE-4 [Medium] vis-network polling — ПОДТВЕРЖДЕНО (закрыто).**
- `web/app.js:4901-4910` — `_graphSignature(g)` по узлам/рёбрам.
- `web/app.js:4920-4923` — `renderCognitionGraph`: если `this.cognitionNetwork` жив и `sig === this._cognitionGraphSig` → ранний `return` (без destroy/new).
- `web/app.js:4944-4950` — `destroyCognitionGraph` вызывается только при уходе с вкладки (`:5163`), unmount (`:5164`) и при реальном изменении данных (`:4923`).
- `web/app.js:4952-4960` — polling 15с и пауза при `document.hidden`. Обновление данных `/api/memory/graph` в polling сохранено (вариант спеки «сравнивать данные и не пересоздавать vis.Network»), drag/zoom/physics не сбрасываются.

**Low-пункты — ПОДТВЕРЖДЕНО (закрыты).**
- README-счётчик: `README.md:5` — «Тестов: 5383»; фактический прогон — **5383 passed**. Синхронизировано.
- `worker_budget` deep_sleep: `services/worker_budget.py:138` — `absolute.setdefault(WORKER_DEEP_SLEEP, -1)` (падает раньше dream); тест `tests/test_feature_gates.py:213-221` `test_deep_sleep_drops_before_dream` + приоритет `== 3` (`:188`).
- `ribbon-static`: класс удалён, `grep` по `web/` — 0 совпадений; reduced-motion закрыт media-query `web/index.html:722-728`.
- `summary_memory.py`: мёртвый алиас `_date_prefix` удалён (grep — 0); комментарий исправлен на `[ММ.ГГГГ | Автор: X]`/UTC (`:2062-2063`).
- `visibilitychange`-листенер: добавляется `web/app.js:1306-1308`, снимается в `beforeUnmount` `web/app.js:5164-5166`.
- ADR-1013-2: `adr-1013-2-graph-library.md:21-24` прямо фиксирует standalone-бандл с встроенным `vis-data` (отдельный не коммитим).
- TZ `_anchor_date`: `services/dream_prompts.py:191-192` — `datetime.timezone.utc` (согласовано с `_fact_prefix`).

### 8.2. Результаты Validator (итерация 2)

| Проверка | Команда | Результат | Exit |
|---|---|---|---|
| Python tests | `.venv/Scripts/python.exe -m pytest -q` | **5383 passed, 1 warning** (59.75s) | 0 |
| JS syntax | `node --check web/app.js` | clean | 0 |
| JS unit | `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| Whitespace | `git diff --check` | clean (только CRLF-предупреждения) | 0 |

### 8.3. Соответствие инвариантам (перепроверено)

- **Ноль новых PG-DDL:** ✓ `git diff` по `services/`/`web/`/`bot.py`/`config/` — 0 совпадений `CREATE/ALTER/DROP/ADD COLUMN/CREATE INDEX`.
- **SQLite schema v8:** ✓ `services/database.py:53` `_SCHEMA_VERSION_AGI_MEMORY = 8`; бампов нет.
- **Порядок роутеров `bot.py`:** ✓ дифф `bot.py` — только DI-kwarg `aliases=AliasResolver(...)` в `LoreWorker` (`bot.py:501-508`); регистрация/порядок роутеров не тронуты.
- **R17:** ✓ `web/api/routes.py:196-203` — секреты только `{configured,last4}`; `generate_worker` логирует role/model/out_chars; тест `test_deep_sleep.py:471-472` подтверждает отсутствие ключа в логах; скан диффа на hardcoded-секреты — чисто.
- **Каталог:** ✓ рантайм-проверка — REGISTRY **427**, categorized **403**, Settings **399**, GROUPS **90**, `_TAB_BY_GROUP` **88**, TAB_RULES **19**.
- **vis-network self-host:** ✓ `web/static/vendor/vis-network/vis-network.min.js` (688 911 байт); CDN — только пре-экзистинг tailwind/chart.js/DOMPurify.
- **Формальный контракт:** ✓ все 8 `tasks.md` — 0 открытых `[ ]`; T-1439 — `[x]` и подтверждён поведением.

### 8.4. Остаточные замечания (не блокеры, к сведению)

1. **[Low] Нет JS-регресс-теста на переиспользование vis.Network (ISSUE-4).** `tests/js/routing_test.js:1286-1291` проверяет только `destroy()`; ветка раннего `return` по `_cognitionGraphSig` автотестом не покрыта. Код корректен (подтверждено инспекцией + `node --check`), но регрессия в будущем не будет поймана. Рекомендация на будущее: юнит-тест `renderCognitionGraph` с прежней сигнатурой и счётчиком `new vis.Network`.
2. **[Low] `bot_id=None` при неустановленном NostalgiaWorker.** `web/api/memory_agi.py:470-473`: если воркер не установлен, `bot_id` = `None` → `database.get_last_user_message_ts` фильтрует `user_id != 0`, т.е. сообщения бота не исключаются. В проде воркер инсталлируется на startup, поэтому практического эффекта нет; чисто теоретический fail-open кейс.

Оба пункта — долг низкого приоритета, не влияют на корректность и не блокируют приёмку.

### 8.5. Вердикт итерации 2

**Approved.**

Все BLOCKER (1–2) и ISSUE (3–4), а также Low-замечания закрыты и подтверждены кодом с `file:line`;
Validator полностью зелёный; архитектурные инварианты соблюдены; регрессий тестов нет (5383/5383).
Остаточные замечания §8.4 — не блокирующий технический долг.
