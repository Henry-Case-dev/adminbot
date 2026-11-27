# UR-E-ACCEPT — остаток unified-reply на выложенном 2.58.257

- **Дата:** 2026-11-27
- **Роль:** Builder
- **База:** `9516c912554bb1062f62a63b6689f418c1cb5425` (deployed 2.58.257,
  healthz `{"status":"ok","version":"2.58.257"}` — проверено на проде)
- **Ветка:** `feat/ur-e-accept-2026-11-27`
- **Коммиты ветки:** `87215cb4a` — тест-онли батч (пин схемы, BAN-08 UI,
  исторический диалог, evidence); `aeac505b4` — продуктовый корректив UR-BAN-02
  (`services/direct_execution.py`, см. раздел 7); `f2ba0c8…`-серия — правки
  evidence hygiene по ревью R1 (см. «Правки по ревью R1»).
- **Worktree:** `WorkspaceData/worktrees/…/ur-e-accept-1ef96b25076e-1e7769b0`
- **Триаж-вход:** `evidence/triage-2026-11-27.md`, sha256
  `2b5e92490ca1ae45051dfd9796cd038bab1fcb711c3b5fd54886872f2e49321f`
- **Продуктовый код:** в коммите `87215cb4a` не менялся (только тесты/фикстуры:
  `tests/test_ur_c_sched.py`, `tests/test_webapp_js_unit.py`,
  `tests/js/ur_ban08_ui_test.js`, `tests/test_ur_17_historical_dialog.py`,
  `tests/fixtures/unified_reply/historical_dialog_2026_11_04.json`); в коммите
  `aeac505b4` изменён ровно один продуктовый файл — `services/direct_execution.py`
  (UR-BAN-02, физический предел шагов).
- **Статус:** BUILT; доказательства ниже — фактические прогоны. VERIFIED не
  заявляется (нужен независимый Reviewer).

## Сводка по строкам

| Пункт | req_id | Результат | Где доказательство |
|---|---|---|---|
| 1. Устаревший schema-pin | (сборочный, не строка карты) | ЗАКРЫТО: RED → GREEN; 62 passed в 3 файлах | `raw/pytest-ur-c-sched-3files.txt`, этот раздел |
| 2. Расписание/пояса | UR-30.5, UR-ACC-E5, UR-ACC-E6 | Код подтверждён на 9516c9125 (file:line), тесты зелёные | `raw/ur30-e5-e6-implementation.txt`, `raw/ur30-e5-e6-test-names.txt` |
| 3. UI «Прямых ответов» | UR-BAN-08 | JS-тест + живой Playwright на реальном backend: структура соответствует строке, дефекта UI нет | `raw/pytest-ur-ban08-js.txt`, `raw/node-ur-ban08.txt`, `raw/ban08-visual.json`, `raw/ban08-*.png` |
| 4. Исторический диалог | UR-17, UR-17.3, UR-17.6, UR-ACC-D6 | Фикстура из прод-БД (read-only) + replay: 8 passed; мутационная защита 4/4 | `raw/ur17-fixture-red.txt`, фикстура, тест |
| 5. Живой E2E | UR-ACC-E9 | Прогон на проде через боевой venv systemd-unit: 7 passed (в т.ч. негативные) | `raw/prod-e9-live-run.txt` |
| 6. Adaptive chain | UR-BAN-02 | Реализовано: физический анти-цикл шагов применяется без явной политики; 16 вызовов / reason `max_steps` (было 201 при предохранителе) | `raw/ur-ban02-*.txt`, раздел 7 |

---

## 1. Устаревший schema-pin в `tests/test_ur_c_sched.py`

**Дефект.** `assert (await cursor.fetchone())[0] == latest == 48` (строки
448/458 базы) зашивал номер последней миграции. На выложенном SHA схема 49
(`_SCHEMA_VERSION_SELF_DIAG_SAMPLES = 49`, `services/database.py:1883`), поэтому
тест падал независимо от проверяемого поведения.

**Правка (тест-онли).** Пин номера убран; сохранены две дискриминирующие
проверки из независимых источников:

1. `PRAGMA user_version` после `initialize()` равен
   `max(s.version for s in DatabaseService.migration_steps())` — если бы цепочка
   миграций не доехала до последней объявленной ревизии, тест падает;
2. отдельный якорь `_SCHEMA_VERSION_SLOT_CLAIMS == 42` и `<= latest` плюс
   фактическое наличие таблицы `slot_claims` (v42-таблица этой полосы).

Это не ослабление: удалён только «замороженный номер», который ломал тест при
каждой новой миграции и ничего не доказывал про v42.

**RED (база 9516c9125, файл без правок, прогон через копию):**

```
py -m pytest tests/_red_probe_v42.py -q -k "test_v42_creates_table"
FAILED ...::test_v42_creates_table_and_repeat_is_noop
1 failed, 14 deselected
```

**GREEN (три затронутых файла, фактические имена тестов в
`raw/ur30-e5-e6-test-names.txt`):**

```
py -m pytest tests/test_ur_c_sched.py tests/test_ur_per_chat_schedule.py tests/test_ur_c_clock.py -q
62 passed in 10.06s
```

## 2. UR-30.5 / UR-ACC-E5 / UR-ACC-E6 — реализация подтверждена, продукт не менялся

Точные срезы кода: `raw/ur30-e5-e6-implementation.txt` (печатается из
фактических файлов с номерами строк).

| Механизм | Где |
|---|---|
| Локальные слоты 00/06/12/18 | `services/summary_scheduler.py:61` |
| Per-chat тик + `claim_slot_if_due` (зона чата через ChatClock, due-окно, атомарный claim) | `services/summary_scheduler.py:243-257` |
| PK claim `(kind, chat_id, local_date, local_slot)` — дедуп на чат | `services/slot_claims.py:58-69` |
| DST gap/fold | `services/slot_claims.py:112-153` |
| Одна точка решения слота | `services/slot_claims.py:411-425` |
| `next_due_utc` (UI «Следующий запуск», зона чата) | `services/slot_claims.py:520-538` |
| Каноническая цепочка пояса | `services/chat_clock.py:212-221` |
| `GOODMORNING_TZ` — только legacy-fallback слоя | `services/chat_clock.py:198-209` |
| Goodmorning: локальный слот каждого чата | `services/goodmorning_scheduler.py:165-174` |
| `GOODMORNING_TZ`/`SUMMARY_TIMEZONE` скрыты (read-only) | `services/param_catalog.py:4458-4466` |
| `/api/config` → `next_run_local`, ДМ без периодики | `web/api/routes.py:1306-1380` |

Фактический прогон: 62 passed (см. п.1). Покрытие: два чата в разных поясах на
одном свипе, DST Berlin spring, повторный тик/«рестарт» без дубля,
`missed_slot_expired` ровно один раз, GOODMORNING_TIME как час, пояс — ChatClock,
ручной /summary в зоне чата (дискриминирующий контраст Almaty/Berlin/UTC).

**Честная деталь, важная для Reviewer:** «GOODMORNING_TIME каждого чата» в коде
означает *час* из одного каталожного ключа (`param_catalog.py:2650`,
`settings.GOODMORNING_TIME`), применяемый в **поясе каждого чата**; отдельного
per-chat значения часа нет. Отдельного рабочего пояса рассылки нет
(`GOODMORNING_TZ` скрыт, только legacy-fallback ChatClock) — эта часть строки
выполнена буквально. Если Reviewer прочитает «локальное GOODMORNING_TIME каждого
чата» как per-chat значение часа, это отдельное требование, которого в 2.58.257
нет; тогда строку нельзя закрывать этим доказательством.

## 3. UR-BAN-08 — UI «Прямых ответов»

**Новый тест** `tests/js/ur_ban08_ui_test.js`, зарегистрирован в
`tests/test_webapp_js_unit.py::test_js_unit_ur_ban08_direct_workspace`
(`node` + `UR-BAN08-UI-OK`).

Что проверяется (на реальном `web/app.js`, а не на копии разметки):

1. карточка `mod_direct` собирается боевым путём реестра
   (`f3ApplyModuleRegistry` → `WORKSPACE_TABS`) и открывается ровно тремя
   смысловыми уровнями в порядке `overview → inspector → settings`, всего 8
   вкладок (не одна «простыня»);
2. подписи через боевую `workspaceTabLabel`: «Как бот отвечает» / «Что бот
   видел» / «Дополнительные настройки»;
3. 11 реальных групп параметров модуля (тот же список отдаёт
   `/api/config.modules[direct].settings_groups` — сверено на живом backend)
   раскладываются в рабочие вкладки `settings` (5) / `limits` (5) / `models`
   (1); на `overview` и `inspector` групп параметров нет вообще — запрещённая
   «панель огромных карточек» структурно не воспроизводится;
4. legacy-ключи (`GOODMORNING_TZ`, `SUMMARY_TIMEZONE`) в витрине read-only
   (ось — backend `eff.readonly`, контракт UI-21);
5. `inspector` применим только к `mod_direct` (нет мёртвой вкладки у других
   модулей).

**Мутационная защита (RED).** Копия `web/app.js` с переставленными вкладками и
с подменённой подписью (`raw/mutate.py`), запуск через `UR_BAN08_APP_JS`:

```
AssertionError: ... первые три уровня модуля обязаны быть overview → inspector → settings,
получено: inspector,overview,settings
AssertionError: подпись уровня «действие» изменена
```

**GREEN:**

```
node tests/js/ur_ban08_ui_test.js            -> UR-BAN08-UI-OK
py -m pytest tests/test_webapp_js_unit.py -q -k "ur_ban08"
1 passed, 48 deselected
```

**Живой Playwright против реального backend.** Поднят настоящий
`web/app.py` (FastAPI, реальные роуты/каталог/registry DTO) на локальном
SQLite (`raw/serve_local.py`), браузер — Chromium, вход — синтетическая
подпись локального тестового токена (реальный Telegram SDK не подменялся,
`sessionStorage['adminbot.initData']`). Ни одного POST, ни одного сообщения в
Telegram.

| Viewport | Вкладки (первые 3) | Всего вкладок | settings: групп/параметров | limits: параметров | Верхний статус | H-overflow |
|---|---|---|---|---|---|---|
| 1440×900 | overview «Как бот отвечает», inspector «Что бот видел», settings «Дополнительные настройки» | 8 | 2 / 3 | 4 | «Исполняется», «Источник: заводское значение», «Проверено: …» | нет (sw=cw=1440) |
| 390×844 | то же | 8 | 2 / 3 | 4 | то же | нет (sw=cw=390) |

Скриншоты: `raw/ban08-{1440x900,390x844}-{overview,settings,inspector,limits}.png`.
Машиночитаемо: `raw/ban08-visual.json`. `pageerrors` — 0 на обоих viewport.

**Честные ограничения живого прогона:**

- В прогоне участвует только часть каталога: локальный backend без PostgreSQL
  отдаёт 124 параметра и 21 модуль (in-memory режим), поэтому на `settings`
  видны 2 группы/3 параметра, а на `limits` — 4. Полный список 11 групп
  проверен JS-тестом и сверен с `settings_groups` живого DTO.
- Консоль браузера содержит `403`/`503` по чужим виджетам, которые дашборд
  грузит на старте (`/api/persona/self-model`, `/api/vision/state`,
  `/api/analytics/viz/activity`, `/api/factcheck/temporal/runs`,
  `/api/memory/embedding-change`, `/api/oversight/dossier_feed` — 403 из-за
  отсутствия PG-матрицы ролей; `/api/chat_lore/chats` — 503, эндпоинт требует
  PostgreSQL). Это артефакт локального backend без БД, не поведение «Прямых
  ответов»; страница модуля ошибок не пишет.
- Browser Use не использовался: визуальный контракт не менялся, изменений в
  `web/*` нет.

## 4. UR-17 / UR-17.3 / UR-17.6 / UR-ACC-D6 — исторический диалог

**Источник (read-only, прод-БД).** Один SSH-сеанс, `sqlite3` в режиме
`file:…?mode=ro`, таблицы `smart_messages` + `mca_bot_outputs`, окно
2026-11-04 04:45–05:15 UTC = **07:45–08:15 MSK**. Найдено 23 сообщения
(один чат) и 1 ответ бота (`initiative_reply`, 08:12 MSK). Копий БД не
создавалось, тексты в репозиторий не попали.

**Фикстура.** `tests/fixtures/unified_reply/historical_dialog_2026_11_04.json`:
uid → `u0…u5`/`ubot`, имена удалены, тексты заменены синтетическими
перефразами с сохранением речевого акта/класса длины/адресации, ссылки →
`example.invalid`, `tg_message_id` → токены `m#`/`ext#`. Порядок строк и
reply-рёбра — настоящие (8 внутренних рёбер + 5 на сообщения до окна; набор
зафиксирован в тесте).

**Replay-тесты** `tests/test_ur_17_historical_dialog.py` (детерминированные, без
модели): полнота серии и совпадение с провенансом (23+1), хронология, разрешение
каждого reply-ребра на автора адресата, запрет self-reply, инициативный ответ
бота без ложной адресации (эхо чужой шутки помечено), честная необъявляемость
межходового рефрена при одном ходе бота, покрытие тредов.

```
py -m pytest tests/test_ur_17_historical_dialog.py -q
8 passed
```

**RED (4 мутации фикстуры, `UR_HISTORICAL_DIALOG`):**

| Мутация | Падает на |
|---|---|
| ответ приписан не тому участнику | `test_reply_edges…` (`'u2' == 'u5'`), `test_reply_never_targets_the_sender_himself` |
| выдуманное reply-ребро | `test_reply_edges…` (набор рёбер не совпал) |
| потерянная реплика | `test_fixture_provenance…`, `test_reply_edges…` |
| ложное «рефрен наблюдаем» | `test_refrain_is_not_claimed…` |

**Что осталось живым (не подделано).** Сценарии из ТЗ («ты раньше был
Рофлославом?», «диагноз придумывал другой человек», «4 утра/диагноз») в
персистентной истории **отсутствуют**: поиск по `рофлослав|диагноз|придумыв|
4 утра` за 03–05.11.2026 дал одно нерелевантное «Не придумывай» (04.11 19:07).
Поэтому UR-17.2 и UR-17.4 (игра/утверждение/память, атрибуция после коррекции)
и межходовый рефрен UR-17.6 — live-наблюдение по названным сценариям, а не
результат этого прогона. UR-ACC-D6 «диалог пройден целиком» закрыт в объёме
реально существующего окна 07:45–08:15, а не гипотетического транскрипта.

## 5. UR-ACC-E9 — живой E2E на выложенном 2.58.257

Один SSH-сеанс на прод; прогон **на сервере**, интерпретатором из systemd-unit
(`/var/www/admin_bot/venv/bin/python`), на временной SQLite в `mktemp -d`.

```
SHA=9516c912554bb1062f62a63b6689f418c1cb5425
HEALTH={"status":"ok","version":"2.58.257"}
UNIT={ path=/var/www/admin_bot/venv/bin/python ; ... }
.......  [100%]
7 passed in 12.54s
```

Это реальный боевой путь исполнения (`svc.handle`, инициативный путь, реальный
слой БД, реальная эмиссия трассы хода), включая негативные случаи:
`test_initiative_silent_still_visible_without_tools` (silent → нет L2-вызова),
`test_refused_reaction_is_not_delivery_success` (отказ ≠ успешная доставка),
`test_failed_send_is_not_success_without_delivery`.

**Честные ограничения:** LLM и router в этом прогоне детерминированные
(заглушки) — реальных вызовов модели, внешних расходов и сообщений в рабочие
чаты не было. Независимый негативный Reviewer по строке остаётся за Reviewer,
не за Builder.

### Временные артефакты прогона (REV-UR-E-R1-01)

Первая попытка прогона не удалась (`No module named pytest`: выбран не тот
интерпретатор), и её `trap` был записан с невалидной спецификацией сигнала
(`trap: EXITINT: invalid signal specification`), поэтому её пустой каталог
`/tmp/ur-e9-*` остался. Успешный прогон завершился с `trap cleanup EXIT` и свой
каталог удалил; строка `TMPD_LEFT=/tmp/ur-e9-8sW1Vi` в
`raw/prod-e9-live-run.txt:9` — это эхо переменной, а не подтверждение
неудаления. Оставшийся пустой каталог был удалён отдельным шагом очистки в тот
же день; чистота проверена **повторно, отдельным read-only сеансом**:

```
raw/prod-cleanup-verification.txt
leftover_ur_e9_count=0
leftover_ur_e9_names=[]
tmp_entries=133
disk=/dev/vda1 99G 51G 44G 54% /
```

То есть: каталог удалён не в момент печати `TMPD_LEFT`, а позже отдельным шагом;
итоговое состояние — 0 каталогов `/tmp/ur-e9-*`. Транскрипт самого шага очистки
в raw не сохранялся — это ограничение фиксируется здесь, а не выдаётся за
захваченный лог.

## 6. UR-BAN-02 — точная семантика adaptive-chain и минимальное предложение

Продукт **не менялся**. Семантика на `9516c9125` (фактические строки в
`raw/ban02-static-semantics.txt`):

| Механизм | file:line | Заводское значение |
|---|---|---|
| Главный цикл | `services/direct_execution.py:1286` (`while True`) | — |
| Потолок шагов | `:1265-1266` (`max_steps = orchestrator_max_steps() or None` при `limits_on`) | `None` (функция `:174` возвращает только явную env-политику, `0` = нет) |
| Потолок токенов | `:1267-1268, 1317-1321, 1388-1391` | `None` |
| Fuse по времени | `ChainBudget.__init__` `:764` (`deadline` только если `fuse>0`), `limit_skip` `:786-793`, источник `tool_loop.py:995-1007` | `0.0` = fuse выключен |
| Объёмные потолки вызовов | `services/tool_loop.py:1051-1062`, `config/settings.py:1561-1566` | `0` (не задано) |
| Стоп по повтору tool+args | `direct_execution.py:1343-1352` | всегда |
| Стоп по отсутствию прироста | `:1203-1224`, `:1380-1385` | всегда |
| `finish` / invalid output / не-allowlist / denied | `:1330-1333`, `:1323-1328`, `:1335-1342`, `:1373-1378` | всегда |

**Точный дефект:** единственные гарантированные остановки — содержательные
(повтор аргументов, пустой/дублирующий/ошибочный результат, `finish`, отказ
LLM, invalid output, denied). При заводской конфигурации нет ни числа шагов, ни
дедлайна, поэтому модель, выдающая каждый раунд **новый** запрос с **новым
непустым** результатом, не ограничена ничем. Подтверждено runtime-пробой:
fake-LLM просит новый запрос каждый раунд, fake-router отдаёт новый непустой
материал → цепочка дошла до 40 шагов (41 вызов LLM) и остановилась **только**
потому, что проба сама вернула `finish`:

```
dispatched_steps: 40
stop_reason: finish
hard_max_constant: 16
factory_max_steps_policy: 0
factory_fuse_seconds: 0.0
UNBOUNDED
```

**Минимальное предложение (для решения Architect, без нового флага):**
в `run_adaptive_chain` при отсутствии явной операторской политики использовать
**уже вычисленный** в этой же функции `limits.max_steps` из
`resolve_orchestrator_budget` (`:1259`, `OrchestratorBudget.max_steps`;
потолок — существующая константа анти-цикла `ORCHESTRATOR_STEPS_HARD_MAX = 16`,
`:118`; пол — `ORCHESTRATOR_MAX_STEPS = 4`, `:101`), то есть
`max_steps = orchestrator_max_steps() or limits.max_steps`, с честным
`stop_reason="max_steps"` в существующем словаре. Никакой новой константы,
настройки или флага не вводится, поведение при явной политике оператора не
меняется. Альтернатива того же класса — ненулевой заводской
`MCA_TOOL_CHAIN_TIMEOUT_SECONDS` (fuse уже реализован и документирован как
«техническая страховка, не продуктовый дедлайн»); выбор между «предел шагов» и
«fuse по времени» — решение Architect, потому что текущие docstring'и прямо
фиксируют owner-решение «универсального продуктового дедлайна исследования
нет» (`direct_execution.py:185-198`, `tool_loop.py:995-1007`).

## Ограничения и что осталось

- `tests/test_webapp_js_unit.py`: на базе `9516c9125` — **7 failed / 41 passed**;
  на кандидате — **7 failed / 42 passed** (+1 новый зелёный
  `test_js_unit_ur_ban08_direct_workspace`). Падают те же 7 node id, все —
  pre-existing устаревшие пины, не связанные с этой задачей:
  4 JS-файла требуют `APP_VERSION = "2.58.255"`
  (`round1025_hotfix7/8/9/10`), остальные 3 падают на своих версионных
  ассертах. `web/app.js` и `config/settings.py` в этой задаче не менялись
  (`git status` чист по ним), поэтому это класс «протухший пин релиза», а не
  регрессия; правку не делал — это поверхность релизного bump'а и чужих строк.
- Коммит содержит только тесты/фикстуры/evidence; продуктовый вывод по
  UR-BAN-02 в этом коммите — предложение, реализация — в следующем коммите
  (раздел 7).
- Live-наблюдаемые части: UR-17.2/17.4/17.6 (сценарии отсутствуют в истории),
  UR-BAN-02 (сценарий не ограничен — нужен продуктовый предел по решению
  Architect), независимый негативный ревью UR-ACC-E9.

## Артефакты

`raw/` — фактические выводы прогонов и скрипты-обвязки; хеши — `raw/SHA256SUMS`.

---

# 7. UR-BAN-02 — реализация физического предела шагов (коммит 2)

Раздел выше (п. 6) фиксирует состояние ДО правки и предложение; номера строк в
нём относятся к базе `9516c9125` (после правки они сместились на ~+8). Решение
Orchestrator от 2026-11-27 принято: предел реализован узким коррективом без
нового флага и без изменения owner-политики «продуктового дедлайна
исследования нет». Fuse/время не трогались.

## 7.1 Изменение продукта (единственный файл)

`services/direct_execution.py`, `run_adaptive_chain` (`:1265-1280`):

```python
    # Явная объёмная политика оператора — только при budgets ON (как раньше).
    explicit_steps = (orchestrator_max_steps() or None) \
        if budget.limits_on else None
    max_tokens = (orchestrator_max_total_tokens() or None) \
        if budget.limits_on else None
    # UR-BAN-02 (safety, не продуктовая квота объёма): физический анти-цикл
    # шагов из окна модели (`ORCHESTRATOR_STEPS_HARD_MAX`, пол —
    # `ORCHESTRATOR_MAX_STEPS`). Считается ЧИСТОЙ деривацией окна ...
    safety_steps = orchestrator_budget_for_window(limits.window_tokens).max_steps
    max_steps = explicit_steps or safety_steps
```

- прежний код: `max_steps = (orchestrator_max_steps() or None) if budget.limits_on else None`
  → без env-политики `None` (цикл не ограничен ничем);
- новый: без явной политики действует **чистая** деривация окна
  (`ORCHESTRATOR_MAX_STEPS=4` — пол, `ORCHESTRATOR_STEPS_HARD_MAX=16` —
  потолок); env-политика оператора авторитетна и не зажимается этим пределом.
- `safety_steps` считается из `orchestrator_budget_for_window(limits.window_tokens)`,
  а НЕ из `limits.max_steps`: в `resolve_orchestrator_budget` уже применён
  `_apply_ceiling(..., orchestrator_max_steps())`, из-за чего env-значение
  протекало бы в safety-предел и при `budgets OFF` (регрессия контракта
  `limits_enforced=false`, которую поймал существующий
  `test_env_step_ceiling_ignored_when_off`).
- останов по пределу — существующая ветка `:1299-1302`: `stop_reason="max_steps"`
  в существующем словаре причин, `limitations.append`, `degraded=True`;
  накопленные `evidence_sources` сохраняются и попадают в `tool_context`.
- наблюдаемость: `chain_meta["max_steps"]` теперь = **фактический** предел
  (анти-цикл либо явная политика), а не только деривация окна; лог
  `[direct-exec] adaptive chain budget | max_steps=…` показывает то же число.
- обновлены устаревшие docstring'и (`orchestrator_max_steps`,
  `resolve_orchestrator_budget`, `run_adaptive_chain`), которые утверждали
  «число шагов не ограничивает».

Диффы: `services/direct_execution.py` (+28/−15 строк по существу),
`tests/test_unified_reply_ur_b_search_first.py` (+172, новый класс),
`tests/test_bgs05_budgets.py` (2 теста переписаны под новый контракт).
Новых флагов, таблиц, эндпоинтов, промптов и квот инструкций нет.

## 7.2 Новый дискриминирующий тест

`tests/test_unified_reply_ur_b_search_first.py::TestAdaptivePhysicalStepBound`
(7 тестов): fake-LLM каждый раунд просит новый запрос, fake-router отдаёт новый
непустой материал — единственный возможный ограничитель это предел шагов.

| Тест | Проверяет |
|---|---|
| `test_new_material_every_round_stops_at_physical_limit` | вызовов ровно `chain_meta["max_steps"]`, `4 ≤ N ≤ 16`, `reason=max_steps`, материал сохранён, `degraded=True` |
| `test_hard_cycle_cap_is_the_enforced_bound` | при инъекции окна 262144 — ровно 16 шагов и ни одного 17-го вызова |
| `test_material_is_kept_after_the_limit` | `tool_context` содержит все полученные факты, `tool_trace` не обрезан |
| `test_explicit_operator_policy_larger_than_window_cap_is_applied` | env=25 → 25 шагов (политика не зажимается анти-циклом) |
| `test_explicit_operator_policy_smaller_is_applied` | env=3 → 3 шага |
| `test_finish_still_wins_before_the_limit` | `finish` на 3-м раунде → 3 вызова, 2 инструмента |
| `test_repeated_arguments_still_stop_before_the_limit` | повтор args → `cycle_detected` на 2-м вызове |
| `test_empty_material_still_stops_before_the_limit` | пустой результат → `step_skipped` на 1-м вызове |

Предохранитель `_EndlessOrchestratorLLM.SAFETY=200` — свойство теста (чтобы RED
падал, а не зависал), не продуктовое поведение.

## 7.3 RED → GREEN (фактические прогоны)

**RED** — новый тест на коде базы `9516c9125` (временное дерево, скопирован
только тест-файл):

```
py -m pytest tests/test_unified_reply_ur_b_search_first.py -q -k "AdaptivePhysicalStepBound"
E  AssertionError: фактических вызовов 201, наблюдаемый предел 8   # assert 201 == 8
E  assert 201 == 16
3 failed, 4 passed
```

**GREEN** — тот же тест на кандидате: `8 passed`
(`raw/ur-ban02-green.txt`).

**Runtime-проба после правки** (`raw/probe_ban02_after.py`,
`raw/ur-ban02-after-runtime.txt`), тот же сценарий, что и RED-проба:

| Метрика | ДО (проба на 9516c9125) | ПОСЛЕ |
|---|---|---|
| вызовов оркестратора | 40 (остановлена только пробой) / 201 в тесте | **16** |
| шагов инструмента | 40 | **16** |
| `stop_reason` | `finish` (искусственный) | **`max_steps`** |
| `chain_meta["max_steps"]` | — (деривация 16, не применялась) | **16** |
| материал | — | 16 источников, все с контентом |

Примечание по числу: предел = `min(16, max(4, window/16384))`. В прод-подобном
окне 1 000 000 токенов это 16 (проба), при окне 131 072 — 8 (контекст
`test_bgs05_budgets`); тест «ровно 16» фиксируется инъекцией окна 262144.

## 7.4 Затронутые наборы и предсуществующие падения

Полный прогон 36 файлов, импортирующих `direct_execution`/`tool_loop`
(`raw/ur-ban02-regression-fullset.txt`):

```
9 failed, 1062 passed in 53.74s
```

Все 9 падений **предсуществующие на 9516c9125** (проверены в отдельном
detached-дереве базы, идентичные node id):

| node id | Причина (на базе тоже) |
|---|---|
| `test_addtr_tools_minifix.py::test_l1_seam_announce_then_execute_once` | `AttributeError: 'DirectChatService' object has no attribute 'llm'` |
| `test_direct_fallback_recompose_asap32.py::TestGenerateChatRecompose::test_chat_recomposed_under_fallback_budget_tools_kept` | `TypeError: fb_retries() got an unexpected keyword argument 'sent'` |
| `…::test_chat_no_adapter_primary_sized_payload_fallback` | то же |
| `…::test_chat_adapter_failure_loud_oversized_diagnostic` | то же |
| `…::TestGenerateStrengthenedDiagnostics::test_generate_adapter_error_loud_and_payload_intact` | `LLMError: primary down` (устаревший двойник) |
| `…::test_generate_adapter_invalid_shape_loud` | то же |
| `test_selfdiag_corrective_research.py::TestContinuationContext::test_continuation_plan_uses_real_ledger_report_and_reads_code` | падает на базе |
| `test_selfdiag_corrective_research.py::test_direct_l1_addendum_and_outage_keeps_previous_decision` | падает на базе |
| `test_ur_f_inspector_step1.py::test_identical_quotes_credit_only_the_surviving_item` | падает на базе |

Известный `tests/test_webapp_js_unit.py` (7 failed) не входит в этот набор и
не мой (см. ограничения выше).

## 7.5 Заменённое покрытие (обоснование)

Два теста `tests/test_bgs05_budgets.py` кодировали прежний owner-контракт
«шаги не ограничены деривацией окна» и после решения по UR-BAN-02 стали
неверными. Они переписаны, а не удалены — покрытие сохранено, но проверяет
новый контракт:

- `test_chain_not_capped_by_window_derived_steps` →
  `test_window_derived_steps_are_a_safety_limit`: при окне 128k исполняется
  8 шагов, 9-е решение не исполняется, `reason=max_steps`,
  `limits_enforced=True`, `max_total_calls=0` (объёмных квот по-прежнему нет);
- `test_chain_without_window_not_capped_to_legacy` →
  `test_chain_without_window_uses_legacy_floor_as_limit`: без резолвера окна
  действует нижний пол 4 шага, `reason=max_steps`, `window_source` остаётся
  честным `fallback_default`.

## 7.6 Остаточные ограничения

- Предел шагов — физический анти-цикл, а не дедлайн: цепочка из 16 дорогих
  шагов по времени не ограничена (owner-политика «дедлайна исследования нет»
  сохранена; fuse остаётся `0`).
- `meta["max_steps"]` теперь фактический предел; прежнее «деривация окна»
  видно там же только когда явной политики нет (значения совпадают).
- Правка не деплоилась; на 2.58.257 поведение прежнее до релиза.
- Пункт 4/5 (исторический диалог и live E2E) в этом коммите не перепрогонялись
  заново — продуктовое изменение не касается этих путей; прогон
  `tests/test_ur_17_historical_dialog.py` (8 passed) и
  `tests/test_ur_acceptance_trace.py` (7 passed) на кандидате подтверждён
  повторно.

## Правки по ревью R1 (evidence hygiene)

Ревью UR-инкремента: `APPROVED_FOR_RELEASE_PREPARATION`, 0 blocking,
5 nonblocking. Закрыты две evidence-находки; поведение кода не менялось.

| ID | Что сделано | Артефакт |
|---|---|---|
| **REV-UR-E-R1-01** | §5 больше не утверждает, что временный каталог E9 удалён тем же `trap`: описано, что первая (неудавшаяся) попытка оставила пустой `/tmp/ur-e9-*` из-за невалидной спецификации сигнала в `trap`, успешный прогон свой каталог удалил, остаток удалён отдельным шагом; `TMPD_LEFT=…` в raw — эхо переменной, а не доказательство неудаления. Добавлена фактическая read-only проверка пост-состояния | `raw/prod-cleanup-verification.txt` (`leftover_ur_e9_count=0`, `leftover_ur_e9_names=[]`, `tmp_entries=133`, диск 54%) |
| **REV-UR-E-R1-05** | docstring блока констант `services/direct_execution.py:93–104` приведён к фактическому safety-пределу (только комментарии, кода поведения не касается); числа `test_webapp_js_unit.py` исправлены: база **7 failed / 41 passed**, кандидат **7 failed / 42 passed**, те же 7 node id | этот файл (§«Ограничения»), раздел 7.5 |
| REV-UR-E-R1-03/04 | по указанию ревью — backlog, не трогались | — |

Проверка, что правка REV-05 — только комментарии:

```
git diff -U0 services/direct_execution.py   # все изменённые строки начинаются с '#'
py -m pytest tests/test_unified_reply_ur_b_search_first.py -q -k AdaptivePhysicalStepBound   # 8 passed
py -m pytest tests/test_bgs05_budgets.py tests/test_smart_exec_ab_round1114.py -q            # 36 passed
py -m pytest tests/test_round1025_f8_registry.py tests/test_asap7_cover_preview.py -q        # 50 passed (routes.py не менялся)
```
