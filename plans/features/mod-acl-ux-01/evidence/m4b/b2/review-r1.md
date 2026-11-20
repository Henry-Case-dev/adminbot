## Вердикт

```json
{
  "review": "MOD-ACL-UX-01 M4B B2 — observer KPI/funnel/decisions/check + compact last call",
  "candidate_tip": "09ef444d83eb6b3e6b1fcb89928c99c629c0a415",
  "product_sha": "db92c73ce122ee09a461696ba4d0a8c69b07cbb6",
  "base_sha": "275a1b7cd320f67e0ac089d8d5c4b14ca31dbcfa",
  "version": "2.58.224",
  "schema": 48,
  "ddl": 0,
  "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
  "blockers": [],
  "required_before_release_record": ["NB-1"],
  "non_blocking_findings": ["NB-1", "NB-2", "NB-3", "NB-4", "NB-5", "NB-6"],
  "backlog": ["BL-1"],
  "partial": ["MAC-S6-345", "MAC-AC-15"],
  "rfl": ["MAC-S6-346"],
  "release_ready": true,
  "final_verified": false
}
```

Файл сохранён по разрешению Orchestrator (2026-11-21); выводы ниже — без изменения.

---

## Кандидат и фактический diff

- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\mod-acl-ux-01-m4b2-fb6b9cda16d7-65c53857`
- HEAD: `09ef444d83eb6b3e6b1fcb89928c99c629c0a415`; продуктовый коммит: `db92c73ce122ee09a461696ba4d0a8c69b07cbb6`; tip отличается только evidence-документами.
- Рабочее дерево чистое.

Продуктовый diff `275a1b7c..09ef444d8`:

| Файл | Изменение |
|---|---|
| `web/app.js` | +262/−78 |
| `web/index.html` | +249/−107 |
| `web/static/app.css` | +32/−15 |
| `web/api/analytics.py` | +39/−1 |
| `web/api/memory_overview.py` | +38/−0 |

Других продуктовых изменений нет: `config/`, `services/`, `migrations/`, `prompts/`, `storage/`, DDL, флагов, версии и `deploy` — нет. `APP_VERSION` остаётся `2.58.224`. Bump/deploy отсутствуют.

---

## Покрытые строки

Полностью проверены по коду, тестам и отрисованному UI:

`MAC-S6-306`, `MAC-S6-309`, `MAC-S6-331`, `MAC-S6-332`, `MAC-S6-333`, `MAC-S6-334`, `MAC-S6-335`, `MAC-S6-336`, `MAC-S6-FUN-01`, `MAC-S6-FUN-02`, `MAC-AC-14`, `MAC-S15-02`, `MAC-S6-344`, `MAC-S6-347`, `MAC-S15-01`, `MAC-S0-11` (rest).

Частично:

- `MAC-S6-345`, `MAC-AC-15` — D1 даёт latency/error/finish, но полноценной страницы трассы нет (D2 gap); в UI только `correlation_id` + ссылка в существующую Аналитику. Честно подписано «отдельной страницы полной трассы нет».
- `MAC-S6-346` — image-only состояние проверено детерминированным stub; натуральное событие не фабриковалось, строка остаётся RFL-кандидатом.

---

## Что проверено лично

### D1 — `/api/analytics/usage/latest`

`web/api/analytics.py`:

- `_SELECT_STEPS_SQL` читает ровно `plan_meta->>'latency_ms'`, `plan_meta->>'l1_failure_mode'`, `plan_meta->>'l1_finish_reason'`; SQL фиксированный, без пользовательского ввода.
- `_step_row()` отдаёт nullable `latency_ms` (`float|None`), `l1_failure_mode|None`, `l1_finish_reason|None`.
- `_opt_float` возвращает `None` для отсутствующего/пустого/битого значения, не `0`; `_opt_str` обрезает код до 64 символов.
- Второго endpoint/стора нет; `/analytics/execution/latest` использует тот же `_step_row`/тот же SQL аддитивно.
- `plan_meta` — JSONB (v35, `services/database.py:1691`), `->>` уже используется в production-коде (`services/execution_graph_source.py:1443`), поэтому диалект PostgreSQL корректен. R17-whitelist ключей подтверждён в `services/usage_events.py:48–78`.

### D3 — `/api/memory/intel-funnels`

`web/api/memory_overview.py`:

- `_initiative_domains(init_job, init_events)` использует уже полученные durable-счётчики и оконные события; нового запроса/таблицы нет.
- Возвращает `intents` (durable snapshot, `created_total`, `active_source=status.intents.active`), `publications` (`initiative_sent` 24ч/7д), `same_cohort=false`, `explain`.
- Данные добавлены в существующий ответ `initiative.domains`; кэш payload сохраняет их.
- Семантика: 0 активных намерений при N публикациях объясняется как разные домены, а не арифметическая конверсия.

### UI

`web/index.html` + `web/app.js` + `web/static/app.css`:

- Health: `Версия: statusData.bot.version`, `проверено: uptime.generated_at`; серверные поля подтверждены в `services/status_service.py:1227/1270`.
- Ровно 6 KPI: `observed`, `opportunities`, `decisions`, `written`, `published`, `intents`; у каждого окно/scope/снимок; `observer-kpi` вместо `.funnel-grid`; `.funnel-grid/.funnel-cell` удалены из HTML и CSS.
- Нет линейной «воронки»; есть строка «это независимые числа, а не конверсия»; `same_cohort=false`.
- Две сущности: намерения и публикации; `domains.explain` выводится.
- «Почему сейчас ничего не опубликовано?» / «Что происходит с публикациями?» — `activity.title/warning/recommendation`.
- Топ-5 причин — кликабельные `<details>` с кодом; полный список — в раскрытии; каждая строка имеет touch-min-height 44px.
- Последние 5 решений с датой/action/причиной/доставкой; полный ledger (решения/отказы/доставки) — в раскрытии.
- «Проверить инициативу»: что проверяется, mock vs real, dry-run ≠ send; trace в раскрытии.
- «Последний вызов»: `ok|empty|unavailable`, checked-at, причина unknown; 1–2 строки время/модуль/модель/результат/латентность/токены/стоимость только при `price_known`; `tokens_estimated`; error/finish; `correlation_id` + ссылка `#/oversight?tab=models` (валидный deep link); image-only отдельно; global badge; `.funnel-grid` нет; `min-height` у `.exec-preview` нет; `align-self:start` для `.status-sleep`/`.exec-preview`.
- B1-контракт (5 лент/сетка) не изменён: `.cognition-ribbons` не тронут.

---

## Независимые прогоны (не по отчёту Builder)

| Проверка | Результат |
|---|---|
| `py -3 -m pytest` (24 mandatory-файла) | **386 passed, 0 failed** |
| `node` 6 файлов (B2 observer/lastcall, W3, Soul1-W5, F6, B1) | **6/6 rc=0**, маркеры `...OBSERVER-OK`, `...LASTCALL-OK`, `W3-STATUS-UNIT-OK`, `SOUL1-W5-PANEL-OK`, `F6-ANALYTICS-MEMORY-OK`, `...B1-FEEDS-OK` |
| Python D1/D3 + regression (5 файлов) | **94 passed, 0 failed** — артефакт `test-output/pytest-d1-d3-regression.txt` тоже говорит 94 |
| Broad JS 127 файлов | **124 passed, 3 failed**; на базе те же 3: `evol_cog_scene` (`_cogBlitLabel`), `round1025_ia_routing`, `ur_ui_settings` — воспроизведено на `275a1b7c` |
| B2 Playwright e2e | **92 checks, 0 failures**, 1920/1440/1280/768/390/320, no console errors |
| B1 Playwright e2e | **138 checks, 0 failures** |
| W3 status e2e | **OK**, включая observed 420, liveness, 6 KPI, 0 funnel, domains explain, entities=2 |
| W10 sections e2e | **3 pre-existing** (modules catalog 1280/390 + scoped toggle); на базе те же 3 |
| W15 composition e2e | **71 fails, 0 status/observer-related**; Builder заявлял 72 — расхождение только в счётчике, не в B2-поверхности |
| RED на `275a1b7c` | 4 node-теста падают с ожидаемыми сообщениями (`funnel-grid`, `data-exec-preview`, KPI CSS, KPI-строка); pytest **4 failed/1 passed**, `KeyError: latency_ms`/`domains` |
| Мутации | KPI slice(0,5) → fail; возврат `.funnel-grid` в CSS → fail; `min-height:320px` → fail; scope `global→чат` → fail; снятие лимита 5 причин → fail; псевдоконверсия publications `sent+created` → fail; D1 null→0 и malformed→0 → fail; D3 `same_cohort=True` → fail. Все restore → green. |

### Browser Use / реальный Chrome

Browser Use (`browseruse`) на 1440:

- `kpis=6`, `funnel=0`, `entities=2`, `reasons=5`, `decisions=5`, `execState=ok`, `overflow=false`;
- KPI-ячейки 377×84, без горизонтального overflow;
- observer 1053 px, `exec=143` vs `sleep=353` — независимые высоты;
- 2 строки последнего вызова, корректные latency/error/cost, `correlation_id: corr-b2`;
- клик по причине раскрывает `код: min_gap`;
- health-строка видна: `Версия: 2.58.225 · проверено: ...` (в стенде версия 2.58.225 — синтетический stub; код читает `statusData.bot.version`).

Реальный Chrome (`browse`) независимо:

- 1440×900: те же 6 KPI/0 funnel/2 entities/5 reasons/5 decisions/no overflow; console errors — 0.
- 390×844: 6 KPI в 2 колонки по 167 px, без overflow; observer 1505 px; `exec=231` vs `sleep=364`; 2 строки last call; health видна.
- Визуально проверены `status-b2-desktop_1440.png`, `status-b2-mobile_390.png`, `status-b2-tablet_768.png`, `status-b2-lastcall-empty.png`, `status-b2-lastcall-503.png`, `status-b2-lastcall-image.png`, `status-b2-observer-1440.png`.

---

## Находки

### Блокеры

**Нет.** Контракт B2 по наблюдаемому acceptance выполнен; critical security/data/concurrency/DDL-рисков не найдено.

### Не блокирующие (требуют фикса/учёта, но не блокируют release preparation)

**NB-1 — evidence-счётчик D1/D3 завышен: 110 vs 94.**
- Где: `plans/.../b2/tests.json:48–52`, `implementation.md` §3.
- Факт: точная команда из `tests.json` даёт **94 passed**; артефакт `test-output/pytest-d1-d3-regression.txt:19` — **94 passed**.
- Ожидаемо: сводка совпадает с артефактом.
- Действительно: в summary написано 110. Продукт не затронут; перед release-записью число нужно исправить на 94.
- Дополнительно: полный `git diff --check 275a1b7c..09ef444d8` даёт rc=2 из-за trailing whitespace в captured-log evidence; `git diff --check -- web tests tools` — rc=0. Утверждение «git diff --check rc=0» верно только для продуктовых путей.

**NB-2 — W15: заявлено 72 fails, воспроизведено 71.**
- Все 71 — `prompt-editor`/adaptive, **0** про status/observer. Не регрессия B2; счётчик в `tests.json` стоит поправить/пометить как environment-dependent.

**NB-3 — image-only дублирует фразу и даёт двойной разделитель.**
- Где: `web/index.html:16360–16368` + `web/app.js:9298–9306` (`imageNote`).
- Факт: в `status-b2-lastcall-image.png` видно дважды «Это вызов изображения, а не текстовый LLM-вызов…», а строка имеет `… 1.20 с · · стоимость: $0.04`.
- Ожидаемо: одна фраза + один разделитель.
- Классификация: candidate-caused, in-scope polish; по project anti-loop — non-blocking follow-up (не нарушает обязательный acceptance B2). Одно-строчный fix уместен в B3 или отдельным follow-up.

**NB-4 — D3 `explain` всегда содержит «0 активных намерений…».**
- Где: `web/api/memory_overview.py` (`explain`) + `data-observer-domains-explain`.
- Факт: при `Активные намерения = 3` рядом выводится «…поэтому 0 активных намерений при публикациях — нормальное состояние…».
- Ожидаемо: условная формулировка («если активных намерений 0, …») или показ этой части только при 0.
- Влияние: смысловая шероховатость, не ложное число; non-blocking.

**NB-5 — начальное состояние last call показывает ложную причину «пустой ответ» до первого ответа.**
- Где: `web/app.js` `execPreview` (ветка `!steps.length`) + `web/index.html:16353–16358`.
- Факт: до завершения первого запроса `state=empty`, `checkedAt='—'`, reason «сервер вернул пустой ответ…».
- Ожидаемо: «проверка не выполнялась/идёт» без ложной причины.
- Non-blocking UX polish.

**NB-6 — correlation только из tool-строк даёт пустую карточку `ok` без строк.**
- Где: `web/app.js` фильтр `s.step !== 'tool'`; `primary` может стать пустым.
- Факт: `state='ok'`, `rows=[]`, заголовок и «Глобальная аналитика…» без содержимого.
- Ожидаемо: compact unknown/пояснение.
- Редкий edge; non-blocking/backlog.

### Backlog (не вызвано B2)

**BL-1 — `_funnels_cached` не учитывает `chat_id`.**
- Где: `web/api/memory_overview.py:92–102`, TTL 60 c.
- Факт: первый запрос `/api/memory/intel-funnels?chat_id=A` кэширует payload; запрос `?chat_id=B` в течение 60 c получает события A. Это pre-existing баг; B2 не менял кэш, но новые scope-подписи делают его заметнее.
- Влияние: только global-admin, только оконные счётчики, не raw-сообщения; не security/data-loss. Нужен отдельный фикс cache key (chat_id) — не блокирует B2.

---

## Ограничения доказательств

- D1 не исполнялся на живом PostgreSQL: проверены SQL-диалект (`plan_meta` JSONB, `->>` уже в production-коде), R17-whitelist и unit-тесты с fake-row; живой PG-фикстуры не было.
- D3 проверен на fake DB; живой прогон production-данных не выполнялся.
- Playwright/Browser Use — локальный стенд с синтетическими API; не production TMA. Эмуляция viewport через `browseruse` работала нестабильно (CDP screenshot timeout), поэтому 390 проверялся реальным Chrome через `browse` + Playwright; 1920 — только Playwright.
- Image-only и 503 — детерминированные stub-состояния; натуральные события не фабриковались (RFL для S6-346).
- D2: отдельной страницы полной трассы LLM-вызова нет; S6-345/AC-15 остаются partial.
- Синтетические фикстуры e2e используют `NOW=1791900000` и ISO `2026-11-20T12:00:00Z` одновременно; в скриншотах даты расходятся (14.10 vs 21.11). Это дефект фикстуры/evidence, не продукта.
- W15 — шумный baseline (71 fail, 0 status/observer); W10 — 3 pre-existing (подтверждены на базе).

---

## Готовность к релизу

**APPROVED_FOR_RELEASE_PREPARATION.**

- Продуктовый diff строго в заявленном scope; DDL 0, schema 48, без флагов/промптов/storage, без bump/deploy.
- Mandatory 386, targeted node 6/6, B1 138/0, B2 92/0 (6 viewport), W3 OK, broad 124/3 с базовым подтверждением, RED и мутации воспроизведены.
- Визуальный контракт B2 подтверждён Playwright + Browser Use/реальный Chrome: 6 KPI, 0 funnel, 2 entities, top-5, 5 decisions, health version/checked-at, compact unknown/503, image отдельно, независимые высоты, no overflow.
- Перед release-записью: исправить evidence-счётчик 110→94 (NB-1). NB-3/NB-4/NB-5 можно закрыть в B3 или отдельным малым follow-up; они не блокируют подготовку релиза, но не должны потеряться.
- После deploy: привязать строки к deployed SHA; `S6-345`/`AC-15` оставить partial (D2), `S6-346` — RFL; финальный VERIFIED только после production-проверки.