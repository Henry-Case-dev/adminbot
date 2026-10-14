# Round 10.25 F6 `memory-analytics-reorg-round1025` — Scanner-аудит (Step 6 @Scanner, T-2912) — **Итерация 2 (re-audit)** — SCANNED

- **База аудита:** HEAD `f103992` (тег `pre-round1025-f6` → `f103992`), правки **НЕ закоммичены** (worktree).
- **Итерация 1:** `plans/reports/round1025_f6_scanner_audit.md` (история ниже) — Critical 0 / High 0 / Medium 1 (M-F6S-1) / Low 5 / Info 4.
- **Итерация 2 (после ремедиации @Builder + AMEND-1 @Architect):** **Critical 0 / High 0 / Medium 0 / Low 2 / Info 4. Вердикт: к деплою — ДА.** Воспроизведено @Scanner независимо: `node --check` OK, JS **37/37**, F6 pytest **19 passed**, полный `pytest -q` **8334 passed / 1 skipped / 5 env-failed**, `git diff --check`=0. Открыт только live-гейт T-2917 (реальный Telegram WebView) — PENDING OWNER.

## Статус итерации 1 → итерация 2

| # | Было (итер.1) | Статус | Доказательство |
|---|---|---|---|
| **H2** (@Reviewer) | High: нет поиска и нет фильтра «статус» (§27) | **CLOSED** | `web/index.html:2027-2038` — `input type="search" v-model="execFilterQuery"` + `select v-model="execFilterStatus"` («Все статусы»); `web/app.js` — состояние `execFilterQuery`, computed `execStatusOptions`, `setExecFilter('query')`, `_execFilters` отдаёт `query`; adapter `web/static/execution_graph.js:243-272` — `searchHaystack` + `filter()` применяет подстроку (label/этап/module/model/tool). Тесты: `test_webapp_f6_round1025.py::test_search_and_status_controls_present`, JS №11 `query: 'web_search'/'M2'/'слой'/'неттакого'/'   '` |
| **M-F6S-1** (@Scanner) | Medium: фильтры трассировки «протекают» в агрегат → ложное «За период данных нет» | **CLOSED** | `web/app.js` `setExecMode`: `if (mode !== this.execMode) this.resetExecFilters();`; `execAggregate` применяет **только** `{ module: this.execFilterModule }`; кнопка «Сбросить» — в обеих ветках (`web/index.html`). Тесты: JS — сброс при смене режима, сохранение при повторном клике, агрегат не режется model/stage/status/query; pytest `test_reset...` |
| **L-F6S-3** (@Scanner) | Low: фильтр «статус» без UI | **CLOSED** | статус-селект + `execStatusOptions` (см. H2) |
| **L-F6S-4** (@Scanner) | Low: detail-диалог без `aria-modal`/backdrop/`Esc` | **CLOSED** | `web/index.html:4005-4008` — `.exec-detail-backdrop` c `@click.self="closeExecDetail()"`, `role="dialog" aria-modal="true" tabindex="-1"`; `web/app.js` `escClose` — `if (this.execDetailOpen) { this.closeExecDetail(); return; }`; CSS `.exec-detail-backdrop` (`z-index:59`). Тесты: pytest `test_detail_closes_on_esc_and_backdrop`, JS-проверки `aria-modal`/backdrop/`escClose` |
| **L-F6S-5** (@Scanner) | Low: мёртвый шов `card.memorySubgroup` + «залипание» подгруппы | **CLOSED** | `web/app.js` `openHubCard`: шов `card.memorySubgroup !== undefined` удалён, вместо него `this.memorySubgroup = '';` (сброс при входе) |
| **H1 §52** (@Reviewer) | High: 3 карточки «Памяти» vs 5 в §52 | **CLOSED (решением @Architect AMEND-1, код не менялся)** | `adr-1025-19a-memory-section-52-amend.md` — вариант A: 3 карточки приняты как честная реализация §52 (нет dedicated-рендеров «Досье»/«Факты», stub/алиас запрещены §0/§57/§116); код/маршруты/каталог не менялись |

## Открытый техдолг (не блокеры, зафиксирован)

- **L-F6S-1 [Low, OPEN]** — `fromSummary` (`execution_graph.js:183,198-205`) жёстко `priceKnown:true`, `summary` API (`web/api/analytics.py:198-203`) без `price_known` → в агрегате возможен «$0» при неизвестной цене (в трассировке честно «Нет данных»). Исправимо только сменой контракта (R16) — известное ограничение.
- **L-F6S-2 [Low, OPEN]** — OFF-ветка `TOKEN_FLOW_NODEFLOW_ENABLED` больше не byte-identical 10.23: badge «Итого» берёт `tokenFlowTree.totals` (`web/index.html:2119`). Честнее, но заявление ADR неточно.
- **Info I-F6S-1:** `evidence.md` «13 passed» устарело (факт **19**); Live WebView/PG — PENDING OWNER (T-2917).
- **Info I-F6S-2:** frontend-zip бэкапа нет; откат — тег `pre-round1025-f6`→`f103992` + `.env.bak.round1025-f6` + `stash@{0}`.
- **Info I-F6S-3:** AMEND `round1024_nodeflow_test.js` перенёс покрытие в adapter-тест; ослабления, скрывающего регресс, нет.
- **Info I-F6S-4:** residual a11y — фокус не переносится внутрь detail-панели при открытии (focus-trap не требовался L-F6S-4; не блокер).

## Проверка честности adapter / режимов / §28 / инвариантов (итер.2)

| Проверка | Итог |
|---|---|
| `cost=null` при `price_known!==true`; `$0` только для подтверждённого нуля | ✔ (`execution_graph.js:92,109-111,136-138`; `fmtCost(v,known)`) |
| `algorithm`/`format`/`publish` в enum, но не эмитятся из реальных `step` | ✔ (тест №8) |
| `parentIds` — только подтверждённая линейная последовательность (`tool`/первый → `[]`), `status='unknown'` | ✔ (тесты №2/№3) |
| Два режима не смешаны (`execIsTrace` ветвит рендер; `fromTrace` без `aggregate`) | ✔ (после M-F6S-1 фильтры тоже не смешиваются) |
| Δ DDL = 0 | ✔ `git diff --stat HEAD -- services handlers migrate_history migrations alembic web/api` пусто; analytics — 4 маршрута |
| Δ каталога = 0 | ✔ `param_catalog.py` не изменён; `test_ia_inventory_round1025` 459/98/96/21/418 |
| CSP `script-src 'self'` / zero-build | ✔ adapter — внешний same-origin `<script src>` с `?v=`; в `execution_graph.js` нет `http(s)://`/CDN/`eval`/`new Function`/`createElement`/`innerHTML`; inline не добавлялся |
| R17 | ✔ grep новых файлов на секреты чист |
| R18 | ✔ тег `pre-round1025-f6`→`f103992`, `.env.bak.round1025-f6`, `stash@{0}` целы |
| `APP_VERSION` 2.58.14 | ✔ `config/settings.py`, `README.md v2.58.14`, `?v=__APP_VERSION__`; «2.58.13» — только историч. комментарии/plans |
| Маркер-тесты не ослаблены | ✔ изменения = строки версий + добавленные проверки; AMEND nodeflow усилен, не ослаблен |
| XSS | ✔ только `{{ }}`/`:attr`/`v-model`; `v-html`/`innerHTML` в новом коде нет |
| §57–§64 / F1 / F4 §60 / F5 §61 / F0 / F9 / ADR-1024-24 / §20 / §76 | ✔ не тронуты (diff не затрагивает shell/store/write-path/cognition/logs) |

## Изменённые/новые файлы (diff HEAD, итер.2)

Новые: `web/static/execution_graph.js`, `tests/js/round1025_f6_{execution_graph,analytics_memory}_test.js`, `tests/test_webapp_f6_round1025.py`, `plans/features/.../{spec,evidence,review}.md`, `adr-1025-19-...md`, `adr-1025-19a-memory-section-52-amend.md`.
Изменённые (`web`): `web/app.js`, `web/index.html`, `web/static/app.css`. Прочее: `config/settings.py`, `README.md`, тесты/маркеры, `plans/**`.

## Независимые прогоны @Scanner (итер.2)
- `node --check web/app.js` / `execution_graph.js` — OK (exit 0).
- JS-тесты: **37/37 PASS**.
- `py -3 -m pytest tests/test_webapp_f6_round1025.py -q` — **19 passed**.
- `py -3 -m pytest -q` — **8334 passed / 1 skipped / 5 failed** (те же env: `test_outgoing_guard_round1022` 2 + `test_summary_cover_round1023` 3, `rich fallback ImportError`; `services/**` не менялся).
- `git diff --check` — exit 0.

## Handoff
**RESULT: SCANNED @Orchestrator** — H2/M-F6S-1/L-F6S-3/4/5 закрыты, H1 закрыт AMEND-1; новых Critical/High/Medium нет; к деплою — ДА. Остаток — техдолг L-F6S-1/L-F6S-2 (Low) и live-гейт T-2917 у владельца. Evidence: `plans/reports/round1025_f6_scanner_audit.md`.
