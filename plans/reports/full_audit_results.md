# Full Audit Results

> Comprehensive code audit of adminbot (C:\Code\Python\adminbot)
> Started: 2026-09-09
> Scanner: Autonomous code auditor

---

## Round 10.25 F7 `permsoc-local-space-round1025` (PERMsoc — локальное пространство чата §60–§67 + per-chat блок-гейты) — 23.09.2026, Step 6 @Scanner (T-2957) — **итерации 2–3 (финал)**

- **База:** HEAD `551847d` (тег `pre-round1025-f7`), правки **НЕ закоммичены**. Отчёт: `plans/reports/round1025_f7_scanner_audit.md`. Вход: `spec.md`/`adr-1025-20`/`evidence.md`/`tasks.md`/`review.md` (@Reviewer итер.3 — **Approved**).
- **Вердикт (итер.3, финал): к деплою — ДА.** Critical 0 / High 0 / Medium 0 / Low 3 / Info 3. Обязательных возвратов @Builder нет. (Итер.1: High 1 / Medium 1 + Low 2; итер.3-фикс: H-F7-7 — все закрыты.)
- **Закрыто фиксами @Builder (воспроизведено @Scanner):** **H-F7-7** — `list-editor._numericList()/toStoredValue()`: чисто-числовые ID → `Number` (только `PERMSOC_LIST_WIDGET_KEYS`), фразы Костика — строки; round-trip `includes(-100123)===true`/`includes('-100123')===false`; pytest-эмуляция `OlyaVideoFilter` int→True/str→False (сервер `filters/olya_video.py` сравнивает int). **H-F7-1** — подгруппы §62/§64/§66/§67 рендерятся (`permsocRenderItems`+`__subheader`+`.permsoc-subgroup`); матрица `permsoc_chat.subgroups` = **24**, titles совпадают. **M-F7-2** — списки ID Оли → `list-editor variant='ids'` (`PERMSOC_LIST_WIDGET_KEYS`+`_normalizeConfigItems`), матрица `olyaListStructured={hasListBtn:True,hasTextarea:False}`. **L-F7-3** — матрица no-chat (`_route_nochat`): `ownerCount=0`, banner. **L-F7-5** — тест 4→6. **L-F7-8** — «Лимит N ID/фраз». **L-F7-9** — `evidence.md` §5 уточнён (D1 клиентский; серверный denylist = follow-up).
- **Контур:** A scope «Только этот чат» + guard; B 6 блоков (key-level partition, 60 body + 5 toggle = 65); C OFF блока сохраняет дочерние; D `permsoc_reactions`/`permsoc_schedule` ∈ `feature_gates` (память `chat_params["gates"]`, Δ DDL=0, `PermsocBlockGate` в war/common/vasya/slavik/alan, `_tick` goodmorning no-send); E §62–§67 presentation; F kill-switch `PERMSOC_BLOCK_GATES_ENABLED` + bump 2.58.15.
- **Low (OPEN, owned follow-up, ноты):** L-F7S-1 — D1-guard «PERMsoc не пишется в global» реализован только на клиенте (`persistItems`/`saveConfigItem`); серверный global-путь `POST /api/config` (`_post_config_global`) не отклоняет per_chat-ключи (`spec.per_chat`-проверка лишь в chat-пути, `routes.py:620`) → global admin может записать PERMsoc-ключ в bot_settings (не эскалация, не регрессия, соответствует ADR D1; hardening — серверный denylist). L-F7-4 — `flags.dead_page_post_on_join` в блоке «Общие реакции» без рантайм-гейта (T-2939/2940). L-F7-6 — в ЛС global admin мастер рендерится, но `PUT /gates` для DM → 403 (pre-existing).
- **Info:** I-F7S-1 `review.md` найден; I-F7S-2 маркеры `round109_ui` переработаны под D1/D2 (не ослаблены); I-F7S-3 ADR changelist упоминает нетронутые `app.css`/`.env.example`.
- **Инварианты ✔:** Δ DDL=0 (миграции/alembic/schema не в диффе); Δ каталога=0 (`param_catalog.py` не тронут; 459/98/96/21/418; M-F7-2 закрыт клиентским оверрайдом); `APP_VERSION` **2.58.15** синхронен; CSP `script-src 'self'`/zero-build; XSS-safe (только `{{ }}`, новых `v-html` нет); R17 (логи/секреты чисты); R18 (`pre-round1025-f7`, `.env.bak.round1025-f7`, `stash@{0}`); §57–§65/F0/F1/F3/F4/F5/F6/ADR-1024-24 не тронуты; guard не молчит; default ON = baseline; fail-closed OFF; partition «ключ ровно в одном блоке».
- **Прогоны @Scanner (независимо, итер.3):** `node --check` OK; все `tests/js/*.js` **38/38 OK**; `py -3 -m pytest -q` → **8374 passed / 0 failed**; `git diff --check` exit 0; `tools/ui_round1025_matrix.py` → **failures: 0**. Серверный дифф D3/guard неизменен (11/9/57).
- **Handoff:** @Orchestrator → `SCANNED`.

## Round 10.25 F6 `memory-analytics-reorg-round1025` (Аналитика §21–§30 + adapter ExecutionGraph + «Память» §52–§59) — 23.09.2026, Step 6 @Scanner (T-2912) — **итерация 2**

- **База:** HEAD `f103992` (тег `pre-round1025-f6` → `f103992`), правки **НЕ закоммичены**. Отчёт: `plans/reports/round1025_f6_scanner_audit.md`. Вход: `spec.md`/`adr-1025-19`/`adr-1025-19a`/`evidence.md`/`review.md`/`tasks.md`.
- **Вердикт (итер.2): к деплою — ДА.** Critical 0 / High 0 / Medium 0 / Low 2 / Info 4. Обязательных возвратов @Builder нет. Live-гейт T-2917 (реальный Telegram WebView) — PENDING OWNER. (Итер.1 была Medium 1 / Low 5; все блокеры закрыты.)
- **Контур:** adapter `web/static/execution_graph.js` (`window.ExecutionGraph`) между `GET /api/analytics/usage/{latest,summary}` и рендером `tokenFlowTree`; 2 несмешиваемых режима (§26), фильтры §27 (модуль/модель/этап/статус + поиск) / detail side-panel/bottom-sheet (§27/§29), honest `fmtCost(v,known)`/«Нет данных» (§28), превью Статуса (§21), «Память» — 3 раздела + 5 подгрупп (§52–§56, presentation-level). `web/api/analytics.py`/`services/**`/миграции — read-only (Δ DDL=0).
- **Закрыто в итер.2:** **H2** (@Reviewer, поиск + фильтр «статус») — `input type="search" v-model="execFilterQuery"` + статус-селект/`execStatusOptions` + adapter `searchHaystack`/`query`-фильтр. **M-F6S-1** — `setExecMode` вызывает `resetExecFilters()` при смене режима, `execAggregate` применяет только `{module}`, кнопка «Сбросить» в обеих ветках. **L-F6S-3** — статус-селект. **L-F6S-4** — `aria-modal="true"` + `.exec-detail-backdrop` (`@click.self`) + `Esc` (`escClose`). **L-F6S-5** — мёртвый шов `card.memorySubgroup` удалён, `openHubCard` сбрасывает `memorySubgroup`. **H1 §52** — закрыт решением @Architect AMEND-1 (`adr-1025-19a`: 3 карточки, код не менялся).
- **Открытый техдолг (Low):** L-F6S-1 (summary API без `price_known` → в агрегате возможен «$0» при неизвестной цене; trace честен), L-F6S-2 (OFF-ветка nodeflow «Итого» больше не byte-identical — честнее). Info: Live-гейт T-2917; нет frontend-zip; residual a11y (фокус не переносится в detail-панель).
- **Инварианты ✔:** Δ DDL=0 (diff `services/handlers/migrations/alembic/web/api` пусто; analytics — те же 4 маршрута); Δ каталога=0 (459/98/96/21/418, `param_catalog.py` не тронут); `APP_VERSION` **2.58.14** синхронен; маркер-тесты не ослаблены; §57–§64/F1/F4/F5/F0/F9/ADR-1024-24/§20/§76 не тронуты; CSP `script-src 'self'`/zero-build (adapter — внешний same-origin `<script>`, без CDN/inline/`eval`); XSS-safe (`{{ }}`/`:attr`, без `v-html`/`innerHTML`); R17 (секретов нет); R18 (тег/`.env.bak.round1025-f6`/`stash@{0}`); `git diff --check`=0; индекса/`.env`/zip/скриншотов нет.
- **Прогоны @Scanner (независимо, итер.2):** `node --check` OK; JS **37/37 PASS**; F6 pytest **19 passed**; полный `pytest -q` **8334 passed / 1 skipped / 5 env-failed** (outgoing_guard/summary_cover, вне F6).
- **Handoff:** @Orchestrator → `SCANNED`.

## Round 10.25 F5 `module-workspace-tabs-round1025` (workspace модуля/промпты/модели §46–§49/§84/§85) — 22.09.2026, Step 6 @Scanner (повторный аудит после правки M-F5S-1)

**База:** HEAD `12a55bb` (`pre-round1025-f5`; правки **НЕ закоммичены** — аудит рабочего дерева). Отчёт: `plans/reports/round1025_f5_scanner_audit.md`. Вход: `spec.md`/`adr-1025-15`/`evidence.md`/`review.md`/`tasks.md`.

**Итог (итер.2): Critical 0 / High 0 / Medium 0 / Low 0 / Info 2. Вердикт: к деплою — ДА.** Итер.1: [M-F5S-1] + [L-F5S-1..3] закрыты по коду и доказательно; новых Critical/High/Medium от правки нет.
Прогон (independent @Scanner, итер.2): `node --check` OK; JS `MODULE-WORKSPACE-OK`/`PROMPTS-SINGLE-SOURCE-OK`/`MODELS-GROUPS-OK`/`JS-UNIT-OK` + `IMAGE-MODULE-OK` + hotfix7 OK; целевые pytest F5 **19 passed**, регресс-пины **202 passed**; `git diff --check` exit 0; Δ DDL=0; Δ каталога=0 (**459/98/96/21/418**, `services/param_catalog.py` не тронут); новых эндпоинтов нет (reuse `/api/llm/test`,`/api/images/test`); `APP_VERSION` **2.58.10** синхронен; ноль backend-строк диффа; тег `pre-round1025-f5`→`940ba40`, бэкап `f5-round1025-20260922-142358`, `.env.bak.round1025-f5`, `stash@{0}` целы; `.env`/zip/скриншотов нет. Полный pytest не перезапускался (опора @Builder/@Reviewer: 8245/1/5 — предсуществующие/env).

**Регресс итер.1 → закрытие:**
- **[M-F5S-1] RESOLVED** — `parsePromptLibraryRoute` читает `promptKey` (3-й сегмент библиотечного маршрута), `workspace()` прокидывает `promptKey` для `door='library'`, `openWorkspacePrompt` для библиотеки строит `#/ai/prompts/<slug>[/<stage>]/<key>` (не модульную вкладку). Probe на реальном `web/app.js` (PROBE-ALL-PASS): summary/sleep/factcheck — дверь library, редактор открыт на выбранном промпте (list>0, focus совпал); модульная дверь/`m.tab` не тронуты. Покрыто блоком (g) `round1025_f5_prompts_single_source_test.js` и pytest.
- **[L-F5S-1] RESOLVED** — `[data-workspace-tabs] button { min-height: 44px; }` (+ `.prompt-tree-item`); **[L-F5S-2] RESOLVED** — `role="group" aria-label`, без `listitem`; **[L-F5S-3] RESOLVED** — `applyRoute` при отсутствии `MODULE_PROMPT_GROUPS[m.id]` → `#/ai/prompts`.

**§49-карточка (T-2714) — новая, проверена:** `buildConnectionCard`/`modelOf` читают только `role === 'model'` (секреты `keys.*` не читаются и не выводятся — спай-тест (g): `last4`/`configured` отсутствуют в значениях карточки); открытие/раскрытие — 0 POST (`toggleConnectionSettings` меняет только UI-объект, тест (h): `wrote===0`); «Проверить» → `testBlock` по клику (тест (i)); сохранённая модель не подменяется (тест (g)); поля/действия в шаблоне `data-connection-card`/`data-conn-field`/`data-conn-test`/`data-conn-configure`/`data-connection-settings`; тач-цели ≥44px.

**Info:** I-F5S-1 (`directStageCards` L1/L2 — одна модель `models.llm_model_name`, честно по §84); I-F5S-2 (полный pytest/Playwright T-2703/live-гейт T-2742 не воспроизводились @Scanner; `tools/ui_round1025_matrix.py` — только `http://127.0.0.1`, без внешних URL/секретов).

**Чисто:** CSP/zero-build (нет CDN/внешних URL/`data:`-URI/новых inline-скриптов/WebGL; grep добавленных строк — 0); XSS-safe (новых `innerHTML`/`v-html`/`insertAdjacentHTML` нет, рендер — `{{ }}`/`:bind`); утечек rAF/observer/таймеров нет; R17 (нет `console.*`/секретов/`keys.*`-копий/сырых путей в новых строках; R17-проба маски зелёная; `api_key` — только в комментарии); R18 (тег/бэкап/`.env.bak`/`stash@{0}` целы; `current_task.md` не изменялся); инварианты — store F4 §37–§42 и `persistItems` не переписаны, `openModuleWindow` — рабочий регресс-путь+fallback, RBAC/kill-switch `mod_images` целы (`routeToTab`=m.tab), IA F1/токены F2/shell hotfix6-7 не тронуты, канон промптов (`services/**`) не изменён, маркер-тесты не ослаблены (diff `tests/**`: версионные пины + `providerGrouped` + аддитивная регистрация; снятие проверок отсутствует).

---

## Round 10.25 F4 `module-catalog-quickpanel-store-round1025` (каталог/панель/store §31–§45) — 22.09.2026, Step 6 @Scanner

**База:** HEAD `b5f8348` (`pre-round1025-f4`; правки **НЕ закоммичены** — аудит рабочего дерева, включая rework iter2 F4-M1). Отчёт: `plans/reports/round1025_f4_scanner_audit.md`. Вход: `spec.md`/`adr-1025-14`/`evidence.md` (iter1+iter2)/`review.md` (iter1 Changes requested).

**Итог: Critical 0 / High 0 / Medium 0 / Low 2 / Info 3. Вердикт: к деплою — ДА.**
Прогон (independent @Scanner): `node --check` OK; JS `MODULE-STORE-OK`/`MODULE-CATALOG-OK`/`JS-UNIT-OK`; целевые pytest **165 passed**; полный pytest **8229 passed / 0 failed**; `git diff --check` exit 0; Δ DDL=0 (`services/`/`web/api/`/миграции/`bot.py`/`handlers/` вне диффа); Δ каталога=0 (**459/98/96/21/418**, `services/param_catalog.py` не тронут); `APP_VERSION` **2.58.9** синхронен (`?v=__APP_VERSION__`/README/пины); тег `pre-round1025-f4`, бэкап `f4-round1025-20260922-073051`, `.env.bak.round1025-f4`, `stash@{0}` целы; `.env`/zip/скриншотов в изменениях нет.

**Low:**
- [L-F4S-1] `web/app.js:4428-4432`+`:6432`+`:2785-2787` — `stickyFailedKeys` (F0) не сбрасывается при `setActiveChat`/`loadConfig` → счётчик «Есть проблемы» и фильтр issues протекают между чатами. Только UI; фикс — сброс в `setActiveChat` или scope-ключ (follow-up F0).
- [L-F4S-2] `web/app.js:4356-4360`+`:4382-4386` — parent-gate (`flags.summary_enabled`) проверяется по **эффективному** `p.value`, а регистрация роутеров 0a–0i (`bot.py:752-786`) — **по глобальному** `hot.get`; при chat-override родителя дочерний модуль может показать `on`. ТЗ/ADR говорят «выключен глобально». Фикс — сравнивать `global_value === false`.

**Info:** I-F4S-1 (kill-switch `flags.dream_enabled`/`flags.nostalgia_enabled` вне `REGISTRY` → F4 их не видит при Δ каталога=0; статус Сна/Ностальгии по kill-switch не моделируется — известное ограничение); I-F4S-2 (Playwright-матрица и живой Telegram WebView T-2656 @Scanner не воспроизводились — опора на evidence/review); I-F4S-3 (техдолг L-F4-1/L-F4-6 из `review.md` оставлен @Builder явно — не блокеры).

**Чисто:** CSP/zero-build (нет новых внешних URL/CDN/data-URI/inline-скриптов/WebGL; только CSS + `@keyframes module-spin`); XSS-safe (новых `v-html`/`innerHTML`/`insertAdjacentHTML` нет; id избранного валидируются по `MODULES`; рендер — из доверенных `MODULES`); утечек rAF/observer/таймеров в F4-коде нет; R17 (код/отчёты без секретов, console-логов нет); §40–§42 (одна мутация `persistItems`, overlay не мутирует `configItems`, откат конструктивен, `key`+`epoch`, stale A≠B; fix F4-M1 подтверждён); §38–§39 (три контекста-ключа global/chatA/chatB, `get/set/refresh/subscribe` без новых библиотек); §34–§36 (избранное в `localStorage` `adminbot.modules_quickpicks.v1`, fail-open, ноль мутаций на закрепление); §44 (синонимы «саммари»/«сводка» → «Сводки чатов»); §33 (тач-цель 44×44, «карточка ≠ тумблер», «Настроить» → `openModuleWorkspace` → существующая модалка); совместимость — IA F1, shell/glass hotfix6/7, токены/фон F2, F3 guard/RBAC, F0 save-path не тронуты; маркер-тесты сетки не ослаблены (`nav_disclosure` усилен). `configItemNotice` F3 не изменён.

---

## Round 10.25 hotfix7 `hotfix7-shell-glass-heartbeat-round1025` (UPD «Срочный фикс фронта») — 22.09.2026, Step 6 @Scanner

**База:** HEAD `5a5465c` (`pre-round1025-hotfix7`, == `origin/master`; правки НЕ закоммичены — аудит рабочего дерева). Отчёт: `plans/reports/round1025_hotfix7_scanner_audit.md`. AA: `plans/reports/round1025_hotfix7_contrast.md`. Матрица: `plans/reports/round1025_hotfix7_ui_report.md`. Вход — spec/ADR-1025-13/evidence/review (итер.2 Approved).

**Итог: Critical 0 / High 0 / Medium 0 / Low 3 / Info 3. Вердикт: к деплою — ДА.**
Прогон (independent @Scanner): `node --check` OK; JS hotfix7-маркер OK + все `tests/js/*.js` PASS; полный pytest **8207 passed / 0 failed**; целевые 6 файлов **156 passed**, `test_hotfix4_cover_nav_shell_round1025.py` **28 passed**; `git diff --check` exit 0; Δ DDL=0; Δ каталога=0 (**459/98/96/21/418**, флаги вне `REGISTRY`); `backdrop-filter: url(`=0; WebGL=0 (только `getContext('2d')`); CSP/zero-build чист; `APP_VERSION` **2.58.8** синхронен (`?v=__APP_VERSION__`/README/пины). Playwright-матрица в среде @Scanner не перезапускалась (опора на @Builder `failures: 0`) — Info, не блокер.

**Low:**
- [L-H7-1] `web/static/app.css:1245-1250` — `@supports not (backdrop-filter)`-фолбэк shell-панелей «мёртв» для `.app-sidebar`/`.app-drawer`/`.bottom-nav`/`.more-sheet`: основные правила (`:1669/1699/1730/1785`, та же специфичность, позже) перекрывают `--shell-bg-strong` → фактический фон без blur = `--shell-bg` (.62). **Pre-existing** (в HEAD аналогично с `--glass-bg` .5), AA-безопасно (independent recompute `--text-2` = **6.46:1**). Фикс: перенести фолбэк ниже/продублировать в правилах панелей.
- [L-H7-2] `app.css:1270-1277` + `app.js:6852` — OFF-пути флагов не «байт-в-байт»: при `UI_SHELL_GLASS_V2=false` шапка получает `border-bottom: 1px solid` + `--glass-shadow` (в HEAD их не было); при `UI_HEARTBEAT_PREMIUM=false` legacy-рендер капается DPR=2. Функциональный откат сохранён.
- [L-H7-3] `app.css:87-88` — AA worst-case комбинированного specular(.10)+texture(.020) = **4.44:1** для `--text-2` (изолированно 4.73, без блика 6.46); тонкая 1px-полоса верхнего угла, не блокер. Fix: specular .10→.08 / texture .020→.015 либо допуск в AA-таблице.

**Info:** I-H7-1 (бэкап `hotfix7-round1025-20260922-052812/` — снимок рабочего дерева итер.1, не pre-hotfix7 baseline; hard-rollback через tag корректный и запушен); I-H7-2 (`README.md:5` «Тестов: 5936» устарело — pre-existing `L10.25F2-4`); I-H7-3 (`workflow_state.md` Step 4/5/6 ещё pending — док-статус).

**Чисто:** CSP/zero-build (нет CDN/внешних URL/`data:image`/новых inline-скриптов; specular/texture — CSS-градиенты); XSS-safe (новых `innerHTML`/`v-html` нет, рендер — canvas + `getComputedStyle`, классы `shell-*` статичны); утечек rAF/observer нет (lifecycle heartbeat не менялся); R17 (диффы/отчёты без секретов/сырых значений); R18 (tag `pre-round1025-hotfix7`→`5a5465c` запушен, 12 тегов `pre-round1025*`, `.env.bak.round1025-hotfix7`, `stash@{0}` целы; `.env`/zip/скриншотов в индексе нет); совместимость — IA F1/порядок hotfix4, write-path F0 `persistItems`, store §37–§42, fullscreen-sync ADR-1024-24, deny-list tier C — не тронуты; палитра §8/фон §10 сохранены (изменены только opacity wash .42→.30 и `--glass-shadow` .75→.55); `--shell-h`-фолбэк корректен (base `100vh` всегда + dvh/min() строго в `@supports`).

---

## Round 10.25 hotfix6 `hotfix6-webview-shell-heartbeat-round1025` (пакет «Волна 1.5») — 22.09.2026, Step 6 @Scanner

**База:** HEAD `441e8f7` (аудит рабочего дерева — правки НЕ закоммичены на момент скана). Диапазон правок пакета: `441e8f7` → `055525c` (код+тесты) + docs `ba75751` (Merge §58 + архивация + сканер-аудит). Отчёт: `plans/reports/round1025_hotfix6_scanner_audit.md`. AA-доказательство: `plans/reports/round1025_hotfix6_contrast.md`.

**Итог: Critical 0 / High 0 / Medium 1 / Low 3 / Info 3. Вердикт: к деплою — ДА.**
Прогон (на момент аудита): целевые pytest **119 passed**; JS-маркеры `HOTFIX6-LENS-HEARTBEAT-SHELL-OK` / `JS-UNIT-OK`; `node --check` OK; `git diff --check` exit 0. Полный pytest/матрица в среде @Scanner не воспроизведены (нет `playwright`) — опора на итоговый прогон @Builder/@DevOps (**8185/0**, JS **26/26**, matrix **0**).
Δ DDL=0, Δ каталога=0 (флаги env-only `ClassVar`), `backdrop-filter: url(` в `web/**` = 0, маркер-тесты F2/F3/hotfix4 переведены атомарно + усилены, `stash@{0}`/теги целы, `.env`/zip/секретов в диффе нет.

**Medium:**
- [M-H6-1] Перф-цена foreground SVG-линзы (`feTurbulence`+`feDisplacementMap`) на реальном WebKit/iOS **не измерена** (снятие UA-gate → tier A у WebView). Кап `UI_LENS_MAX_NODES=6` ограничивает узлы, абсолютная цена кадра не подтверждена. Не блокер; снимается env-ручкой без редеплоя + замер FPS в T-2617.

**Low:**
- [L-H6-1] `web/index.html:2793-2801` — Canvas-heartbeat `role="img"` на интерактивном элементе; `aria-describedby="hb-tip"` «висячая» ссылка при закрытом тултипе. Фикс — `role="button"`/`v-show`.
- [L-H6-2] `web/static/app.css:1064-1066` — линза `.app-sidebar`/`.app-drawer` скроллится вместе с контентом (`overflow-y:auto`). Декоративно, контент/контраст не затронуты.
- [L-H6-3] `web/app.js:6534-6535` — комментарий о stale-пороге (2×≈30 с) расходится с кодом (`> 120000` мс = 120 с). Формула безопасна.

**Info:** I-H6-1 (одноразовый `<canvas>` для feature-detect heartbeat), I-H6-2 (UI-матрица не воспроизведена — нет `playwright`), I-H6-3 (`README.md:5` «Тестов: 5936» устарело — предсуществующий `L10.25F2-4`).

**Чисто:** CSP/zero-build (один inline `<svg id="lg-lens">`, без `feImage`/data-URI/внешних ссылок, WebGL отсутствует); XSS-safe (нет `innerHTML`/`v-html`, `data-glass-*` из фиксированного множества, override санитизируется в `a|b|c|auto`, `_lensMaxNodes` — `parseInt`); утечек rAF/observer нет (останов по `document.hidden`, `watch activeTab`, `beforeUnmount`); R17 (диффы без новых логов с сырыми путями/токенами); R18 (`stash@{0}`/теги `pre-round1025-*` целы); доступность (⛶ — нативная `<button>` c `:aria-pressed`, тач-цель ≥44×44; canvas фокусируем, `@keydown.enter/esc`); каскад CSS панелей не ломается (`position:fixed`/`sticky` сохранены); C2-OFF откат `heartbeatLegacy` байт-в-байт подтверждён юнит-тестом; `APP_VERSION` 2.58.7 синхронен (`config/settings.py:1685`, `?v=`, README, тесты-пины).

---

## Round 10.25 hotfix5 `summary-cover-window-round1025` — 21.09.2026, Step 6 @Scanner

**Diff `0e43c37..b3fb6a5`** (коммит `b3fb6a5`, 9 файлов). Отчёт: `plans/reports/round1025_hotfix5_scanner_audit.md`.

**Итог: Critical 0 / High 0 / Medium 1 / Low 3 / Info 1. Вердикт: к деплою — ДА.**
Прогон: pytest **8124 passed / 0 failed** (113.19 s), `tests/js/*` **24/24 OK**.
Δ DDL=0, Δ каталога=0, `stash@{0}` цел, трекаемых zip нет, секретов в диффе нет.

**Medium:**
- [M10.25H5-1] `services/image_generation.py:810-828` + `:423-437` — внешний ретрай (2) × внутренний 429/503-ретрай (2)
  → до **4 HTTP-вызовов** и до ~4×окна (≈720 c) на обложку; комментарии заявляют «≤2×окно (360 c)». Проба: `HTTP_CALLS_ON_503 = 4`.
  Фикс: либо скорректировать доки/бюджет, либо не дублировать ретрай на 429/502/503.

**Low:**
- [L10.25H5-1] `image_generation.py:300-311` — `reason_class` уводит `empty`/`too_large`/`empty_prompt`/`temp_write_failed` в `error`
  (наблюдаемость), `no_image` — в `bad_json`.
- [L10.25H5-2] `image_generation.py:810-828` — ретрай невосстановимых `bad_request`/`unauthorized`/`forbidden`/`payment_required` бесполезен.
- [L10.25H5-3] `tests/test_webapp_dm_ui.py:124-131` — проверка планировщика через grep исходника (хрупко, дублирует поведенческие тесты).

**Info:** корневые `*.zip` (+ `backups/pre-round1025-hotfix5-src.zip`) — git-ignored балласт, в индекс не входят.

**Чисто:** бюджет — одно списание на запрос (`consume_budget=False` на попытках); отдельная env-ветка `image_calls`
не ломает `llm_calls`/`llm_tokens` и не обходится; R17 в WARNING (только reason-код, host, chat_id, latency);
`provider_label` = hostname (userinfo срезается), URL в `log_external_api` чистится `redact_url`;
scheduler `int()` не роняет тик, DM-фильтр сохранён; `CancelledError` не проглатывается; `probe`-таймаут 90 c не тронут;
новые тесты импортируют отсутствовавшие ранее символы/kwarg → падают на старом коде (не тавтологичны).

## Round 10.25 «F0: конфигурация + устойчивость к database is locked» — 20.09.2026, Step 6 @Scanner

**Diff `pre-round1025..HEAD`** (коммиты `c0cb8aa`…`9a5f265`), фича F0 (P0, Wave 0).
Полный отчёт: `plans/reports/round1025_f0_scanner_audit.md`.

**Сводка: Critical 0 / High 1 / Medium 3 / Low 8 / Info 6.**
_(исходный снимок на `9a5f265`; H 10.25-1 закрыт коммитом `5dd2b0d` — см. «Повторный аудит» ниже)._
Доказательство: `pytest` по 4 файлам раунда = **32 passed**;
`node tests/js/round1025_save_state_test.js` и `round1025_cliche_ui_test.js` = OK;
секретов в диффе нет (архивный R10.18-12 диффом не затронут).

**High (блокер Шага 7):**
- [H10.25-1] `web/app.js:3861-3908` (`saveBlock`) ложно сообщает «Сохранено:
  <title>» при частичном провале (saved непуст + failed непуст) и при полном
  in-flight-пропуске (`skipped` непуст, `saved`/`failed` пусты). Регрессия
  против pre-F0 (падавший POST всплывал в `catch`). Фикс: успех только при
  `res.state==='saved' && !failed.length && !skipped.length`.

**Medium:**
- [M10.25-1] `services/database.py:596-616` — `write_transaction` ловит
  `Exception`, а не `BaseException`: при `CancelledError` rollback не делается
  (вразрез с docstring `:580-583`) → возможны незакоммиченные «огрызки»,
  подхватываемые следующим `commit()`.
- [M10.25-2] `web/app.js:5217-5220` — global per-key `updated_at` не шлётся
  клиентом (GET его отдаёт, `routes.py:474`); global optimistic инертен через UI.
- [M10.25-3] `web/api/routes.py:995-1002` — 409 `conflicting` может вернуть
  `server_value` сырого секрета `keys.*` (R17); chat-путь безопасен.

**Low:** L10.25-1 `_patch_already_applied` meta-only → ложный revalidated
(недостижимо через роуты); L10.25-2 LRU `_chat_write_locks` soft-cap не
ограничивает рост при всех занятых локах; L10.25-3 `notify` читает `_opNotified`
до проверки типа; L10.25-4 очередь тостов молча вытесняет новый того же
приоритета; L10.25-5 `saveState` не возвращает `'saved'` (при `stateLabel`);
L10.25-6 дубль `_REFRESH_ACTIVE_CAP`; L10.25-7 cliche UI-тест статический
(grep); L10.25-8 `set_many` fallback без транзакции (тест-двойники).

**Подтверждённые инварианты:** single-writer сериализация (`write_transaction`);
rollback на не-lock исключение (ON и OFF); `commit_if` паритет
(`touch_graph_facts`); advisory-lock внутри транзакции; scope-изоляция A≠B;
idempotent short-circuit 200/`revalidated`; атомарная валидация global-пакета;
XSS-safe рендер тостов (`{{ }}`); R17-логи событий без фраз/значений;
анти-клише bounded (rounds/per-run/dedup).

**Вердикт:** к Шагу 7 без правок — **нет**; обязателен фикс H10.25-1
(желательно + M10.25-1).

**ПОВТОРНЫЙ АУДИТ (после `5dd2b0d`/`83fc4c4`): Critical 0 / High 0 → к Шагу 7
(Merge) ДА.** Закрыты H10.25-1, M10.25-1, M10.25-3, Low L10.25-1/3/4/5/6; M10.25-2
отложен и зафиксирован. Новых находок нет. pytest **7946 passed** (106.27s),
JS **19/19**; новые тесты падают на pre-fix `9a5f265`. Δ DDL=0, Δ каталога=0,
промпты/`smart_cache` не тронуты, `git diff --check` = 0, секретов нет.
Подробно: `round1025_f0_scanner_audit.md` §5.


---

## Round 10.24 «Disaster Recovery: UI & Backend Bloat» (UPD2–UPD6) — 20.09.2026, Step 6 @Scanner

**Baseline `00eab85` → HEAD `379cfdd`** (132 файла, +18264/−1016). Фичи F1–F24.
Полный отчёт: `plans/reports/round1024_scanner_audit.md`.

**Сводка: Critical 0 / High 0 / Medium 0 / Low 3 / Info 5.**
Доказательство: полный `pytest -q` = **7911 passed / 0 failed** (103.71 s);
SQLite v12 (Δ=0), PG DDL (Δ=0); канон инструментов = 10; `git diff --check` exit 0;
секретов в диффе/трекаемых файлах нет (только тестовые плейсхолдеры).

**Открытые Low (не блокеры):**
- [L10.24-1] `handlers/voice_transcription.py::force_repeat_from_reply` +
  `handlers/youtube.py::_handle_voice_command` — тристейт отдаёт `HANDLED`
  при раннем `return False` (`from_user is None`/бот-автор) без отправленной фразы →
  тихий пропуск ответа на командный форс-повтор.
- [L10.24-2] `services/tool_router.py:112` `_DOWNLOAD_NATIVE_MAX_BYTES=2_000_000_000`
  подписан «лимит Telegram», но это лимит локального Bot API server; для облачного
  Bot API (~50 МБ) гейт не срабатывает рано → обобщённая ошибка отправки.
- [L10.24-3] `services/image_generation.py::_download_bytes`/`_generate_get` —
  тело ошибочного ответа логируется через `safe_text` без `_redact_secret`; подписанный
  URL-токен может попасть в лог. Hardening R17.

**Info:** I10.24-1 (F13 cap vs медиа-маркер при экстремально малом cap),
I10.24-2 (неточный текст `GraphExtractionError`), I10.24-3 (N+1 alias-резолв в GLOBAL
`dossier_feed`), I10.24-4 (F16 полная загрузка видео на cache-miss — ADR-1024-17,
tmp чистится в `finally`), I10.24-5 (`bot.send_message` вне обёрток egress в F19 —
покрыт SEND_ALLOWLIST, review-accepted).

**Подтверждённые инварианты:** `physical-two-call` (F1 `generate_background` —
отдельный канал, общий `_post` дефолты сохранены); `validator-loop` (negative_constraints
не менялся); egress-реестр; `imported-history-immutable` (deny-list + sniff fail-closed
+ re-classify + verify); `manual-overrides-immutable` (F20 fix + merge-контракт
`set_chat_params`); R16/R17/R18; `parse_mode=None`; порядок роутеров `bot.py`;
каталог (GROUPS 98, `mod_images`/`mod_budgets`/`limits_anticliche`).
**Critical F20:** per-chat overrides больше не стирают остальные; F21/F22 согласованы.
**DDL:** новых PG-таблиц/колонок нет; SQLite v12 не тронут.

---

## Audit Summary

| Category | Files Scanned | Issues Found | Critical | High | Medium | Low |
|----------|---------------|--------------|----------|------|--------|-----|
| Total    | 180+          | 47           | 0        | 8    | 22     | 17  |

---

## Findings by Severity

### Critical (Production-blocking)
*None found*

### High (Significant risk)

#### [HIGH-001] bot.py: Global mutable state for services creates race conditions and testing difficulties
**Location**: `bot.py` lines 143-180 (16+ module-level globals)
**Issue**: Module-level globals hold service instances creating race conditions, testing impossibility, hidden dependencies
**Impact**: Flaky tests, potential production issues under load, maintenance burden
**Recommendation**: Use `ApplicationState` dataclass or DI container

#### [HIGH-002] bot.py: `on_shutdown` accesses globals without null checks
**Location**: `bot.py` lines 716-745
**Issue**: Some globals checked but others like `_search_aggregator`, `_web_extractor`, `_checkup_fetcher` accessed without verification
**Impact**: AttributeError on shutdown if SmartModule disabled
**Recommendation**: Add null checks or use centralized service registry

#### [HIGH-003] config/settings.py: Secrets in default values leak to `.env.example`
**Location**: `config/settings.py` - `LLM_API_KEY=""`, `TAVILY_API_KEY=""`, etc.
**Issue**: Default empty strings for secrets; `.env.example` contains all keys as templates
**Impact**: Developer may accidentally commit real secrets; secret rotation difficult
**Recommendation**: Use `None` defaults for secrets; separate secret schema from config

#### [HIGH-004] services/llm_client.py: No request/response logging for debugging LLM issues
**Location**: `services/llm_client.py` `_post` method
**Issue**: Only errors logged; successful requests/responses not logged at DEBUG level
**Impact**: Impossible to debug prompt issues, token usage, model behavior in production
**Recommendation**: Add structured DEBUG logging with request/response metadata (masked secrets)

#### [HIGH-005] services/database.py: SQL injection risk in dynamic queries
**Location**: Multiple methods using f-strings for table/column names
**Issue**: `_SCHEMA_SQL` uses f-strings; `insert_graph_fact` builds CHECK constraint dynamically
**Impact**: If origin values come from user input, potential injection
**Recommendation**: Use allowlists for dynamic SQL parts; validate origin against `_GRAPH_FACT_ORIGINS`

#### [HIGH-006] handlers/summary.py: Observer saves ALL messages including potential PII
**Location**: `handlers/summary.py` `summary_observer` function
**Issue**: No PII filtering; saves forward sources, user names, message content
**Impact**: GDPR/privacy compliance risk; sensitive data in SQLite
**Recommendation**: Add PII detection/filtering; configurable retention per chat

#### [HIGH-007] services/pg_db.py: No connection pool sizing for production load
**Location**: `services/pg_db.py` `PgDatabase` class
**Issue**: Default pool size not configured; no max_connections tuning
**Impact**: Connection exhaustion under load; "too many connections" errors
**Recommendation**: Configure pool size from settings; add pool monitoring

#### [HIGH-008] web/app.py: CORS allows all origins by default
**Location**: `web/app.py` FastAPI middleware
**Issue**: No explicit CORS configuration; defaults may be permissive
**Impact**: CSRF risk for TMA admin panel
**Recommendation**: Explicit CORS origins from config; credentials=false

### Medium (Should fix)

#### [MED-001] bot.py: Hardcoded router registration order fragile
**Location**: `bot.py` lines 632-710
**Issue**: Order critical but only enforced by comments; no tests verify
**Recommendation**: Add test validating router precedence; use priority system

#### [MED-002] bot.py: Duplicate LLMClient instantiation (5+ times)
**Location**: `bot.py` lines 467, 527, 557, 587, 617
**Issue**: DRY violation; inconsistent config possible
**Recommendation**: Extract `create_llm_client()` factory function

#### [MED-003] bot.py: Inconsistent `settings` vs `hot.get()` usage
**Location**: Throughout `bot.py`
**Issue**: Mix of static and dynamic config access confusing
**Recommendation**: Standardize on `hot.get()` for all runtime-configurable values

#### [MED-004] bot.py: No structured error handling for service init failures
**Location**: `bot.py` `on_startup()`
**Issue**: Broad `Exception` catches, only warnings logged
**Recommendation**: Structured error types; init status tracking via `/api/status`

#### [MED-005] config/settings.py: `_env_duration` parsing allows dangerous values
**Location**: `config/settings.py` `_parse_duration` function
**Issue**: No upper bounds; "999d" = 86M seconds accepted
**Recommendation**: Add max duration validation per parameter

#### [MED-006] config/settings.py: Type coercion silent failures
**Location**: `config/settings.py` `_env_int_min`, `_env_float_min`
**Issue**: Invalid values silently fall back to defaults with WARNING only
**Recommendation**: Fail-fast for critical config; structured config validation

#### [MED-007] services/config_cache.py: No cache invalidation TTL
**Location**: `services/config_cache.py` `ConfigCache` class
**Issue**: In-memory cache never expires; stale data until reload
**Recommendation**: Add TTL-based cache refresh; configurable max age

#### [MED-008] services/hot_config.py: No validation of coerced values
**Location**: `services/hot_config.py` `_coerce` function
**Issue**: Failed coercion returns original value silently
**Recommendation**: Raise on coercion failure for critical params; metrics

#### [MED-009] services/database.py: No WAL mode enforcement verification
**Location**: `services/database.py` `initialize()`
**Issue**: WAL mode set but not verified; could be disabled by SQLite config
**Recommendation**: Verify `PRAGMA journal_mode=WAL` after setting

#### [MED-010] services/database.py: FTS5 triggers not maintained
**Location**: `services/database.py` `save_smart_message`
**Issue**: Manual FTS sync; no triggers for UPDATE/DELETE
**Recommendation**: Use FTS5 triggers or explicit sync on all mutations

#### [MED-011] services/llm_client.py: Retry logic doesn't respect `Retry-After` for all 5xx
**Location**: `services/llm_client.py` `_post` method
**Issue**: `Retry-After` only for 429/5xx per code comment but implementation unclear
**Recommendation**: Explicit handling for all retryable status codes

#### [MED-012] handlers/common.py: Mimic victim IDs parsed once at module load
**Location**: `handlers/common.py` `_VICTIM_IDS` global
**Issue**: Changes to `MIMIC_VICTIM_USER_IDS` require restart
**Recommendation**: Parse dynamically in handler or use hot config

#### [MED-013] handlers/search.py: Exact match cache key doesn't include chat context
**Location**: `handlers/search.py` `smartsearch_handler`
**Issue**: Cache key only includes query; different contexts return same result
**Recommendation**: Include chat_id in cache key or disable cache for contextual search

#### [MED-014] handlers/factcheck.py: No rate limiting on external API calls
**Location**: `handlers/factcheck.py` (similar to search)
**Issue**: Tavily/Exa calls not rate-limited per provider
**Recommendation**: Add provider-level rate limiting in `SearchAggregator`

#### [MED-015] services/direct_chat_service.py: Massive function (800+ lines)
**Location**: `services/direct_chat_service.py` `generate_and_send`
**Issue**: Single function handles context building, LLM calls, tools, memory, sending
**Recommendation**: Split into pipeline stages; extract context builders

#### [MED-016] services/summary_memory.py: `rule_importance` magic numbers
**Location**: `services/summary_memory.py` `_IMPORTANCE_BASE` dict
**Issue**: Hardcoded importance weights per origin; not configurable
**Recommendation**: Move to param_catalog; hot-configurable

#### [MED-017] services/param_catalog.py: 383 parameters - no validation of registry completeness
**Location**: `services/param_catalog.py` `REGISTRY`
**Issue**: No test that all Settings fields have ParamSpec; drift likely
**Recommendation**: Add test comparing Settings fields to REGISTRY keys

#### [MED-018] services/permissions.py: Bitmask permissions lack audit trail
**Location**: `services/permissions.py` `Permissions` class
**Issue**: Changes to permissions not logged; no history
**Recommendation**: Log permission changes via `chat_lore_history`

#### [MED-019] services/access.py: `can_edit_param` logic complex, undertested
**Location**: `services/access.py` `can_edit_param` function
**Issue**: Multiple condition branches; edge cases for custom roles
**Recommendation**: Add comprehensive unit tests; simplify logic

#### [MED-020] web/api/config.py: Secret masking incomplete
**Location**: `web/api/config.py` `GET /api/config`
**Issue**: Only masks known secret keys; custom secrets may leak
**Recommendation**: Mask all values for keys containing secret patterns

#### [MED-021] web/app.js: No error boundary for WebSocket/API failures
**Location**: `web/app.js` Vue components
**Issue**: Failed API calls show generic errors; no retry UI
**Recommendation**: Add error boundaries; toast notifications; retry buttons

#### [MED-022] tests/: Low coverage for critical paths
**Location**: `tests/` directory
**Issue**: No integration tests for router chain; no contract tests for API
**Recommendation**: Add pytest-asyncio integration tests; API contract tests

### Low (Nice to have)

#### [LOW-001] bot.py: Inline SQL in channel_post handler
**Location**: `bot.py` lines 678-695
**Recommendation**: Move to `DatabaseService.save_relay_album_map()`

#### [LOW-002] bot.py: Magic numbers in router registration comments
**Location**: `bot.py` lines 632-710
**Recommendation**: Define `ROUTER_ORDER = [...]` constant

#### [LOW-003] config/settings.py: 400+ settings in single class
**Location**: `config/settings.py` `Settings` dataclass
**Recommendation**: Split into nested config objects (LLMConfig, MemoryConfig, etc.)

#### [LOW-004] services/database.py: `row_get` helper hides type errors
**Location**: `services/database.py` `row_get` function
**Issue**: Silently returns default on any access error
**Recommendation**: Use typed rows (dataclasses) or explicit dict access

#### [LOW-005] services/llm_client.py: `_mask_secrets` regex may miss edge cases
**Location**: `services/llm_client.py` `_mask_secrets`
**Issue**: Complex regex; new key formats may bypass
**Recommendation**: Use allowlist of known secret patterns; test extensively

#### [LOW-006] handlers/alan.py: Reply probability hardcoded in logic
**Location**: `handlers/alan.py` reply interval logic
**Issue**: `ALAN_REPLY_INTERVAL` used but probability not configurable
**Recommendation**: Add `ALAN_REPLY_PROBABILITY` setting

#### [LOW-007] handlers/kostik.py: Random reply uses `random.random()` without seed
**Location**: `handlers/kostik.py`
**Issue**: Non-deterministic; hard to test
**Recommendation**: Inject RNG for testing

#### [LOW-008] handlers/slavik.py: GIF counter logic mixed with message handling
**Location**: `handlers/slavik.py` `MessageCounterMiddleware`
**Issue**: Middleware does business logic (GIF trigger)
**Recommendation**: Separate counter persistence from reaction logic

#### [LOW-009] services/memory_backup.py: Backup path not validated
**Location**: `services/memory_backup.py` `MemoryBackupService`
**Issue**: Relative path; may write outside project if CWD changes
**Recommendation**: Resolve absolute path from project root

#### [LOW-010] services/memory_maintenance.py: No progress reporting for long jobs
**Location**: `services/memory_maintenance.py` `MemoryMaintenanceService`
**Issue**: Merge/review jobs can run minutes; no visibility
**Recommendation**: Add progress callbacks; expose via `/api/workers`

#### [LOW-011] services/oversight.py: Dashboard data not cached effectively
**Location**: `services/oversight.py` `build_summary`
**Issue**: 60-120s cache mentioned but implementation unclear
**Recommendation**: Explicit cache with TTL; cache invalidation on config change

#### [LOW-012] web/index.html: No CSP headers
**Location**: `web/index.html`
**Issue**: No Content-Security-Policy; inline scripts allowed
**Recommendation**: Add CSP meta tag; nonce for inline scripts

#### [LOW-013] docker-compose.yml: PostgreSQL no resource limits
**Location**: `docker-compose.yml` postgres service
**Issue**: No CPU/memory limits; can OOM host
**Recommendation**: Add `deploy.resources.limits`

#### [LOW-014] requirements.txt: Unpinned transitive dependencies
**Location**: `requirements.txt`
**Issue**: `aiogram>=3.31.0,<4.0.0` allows breaking patch updates
**Recommendation**: Pin exact versions; use `pip-tools` for lockfile

#### [LOW-015] pytest.ini: Timeout too short for integration tests
**Location**: `pytest.ini` `timeout = 60`
**Issue**: Some DB/LLM tests need >60s
**Recommendation**: Separate unit/integration test configs; longer timeout for integration

#### [LOW-016] .gitignore: `migrate_history/` ignored but 600MB+ files
**Location**: `.gitignore`
**Issue**: Large files in ignored dir still consume disk; no cleanup policy
**Recommendation**: Document cleanup; consider external storage for imports

#### [LOW-017] .env.example: Contains 200+ variables - overwhelming
**Location**: `.env.example`
**Issue**: New developers can't identify required vs optional
**Recommendation**: Split into `.env.required`, `.env.optional`, `.env.secrets`

---

## Detailed Findings by Component

### bot.py (Main Entry Point)
- **Architecture**: 700+ lines, single file orchestration
- **Globals**: 16 service instances as module-level variables
- **Startup**: 400+ line `on_startup()` violating SRP
- **Router Order**: 24 routers in fixed critical order
- **Positive**: Excellent spec-referencing comments; structured logging; secret masking

### config/settings.py (Configuration)
- **Size**: 77KB, 2000+ lines, 400+ settings
- **Parsing**: Custom `_env_*` helpers with validation
- **Issues**: No config schema validation; silent fallbacks; secret defaults
- **Positive**: Duration parsing; tuple parsing; comprehensive comments

### services/database.py (SQLite Layer)
- **Schema**: 8 migration versions; comprehensive tables
- **GraphRAG**: Complex fact storage with origins, importance, vectors
- **Issues**: Dynamic SQL; FTS sync manual; `row_get` hides errors
- **Positive**: Fail-open for infinite_retention; detailed migration logic

### services/pg_db.py (PostgreSQL Layer)
- **DDL**: Idempotent CREATE + ALTER statements
- **Tables**: 15+ tables for config, RBAC, chat profiles, budgets
- **Issues**: No pool sizing; no migration version tracking
- **Positive**: Comprehensive seeds; additive deltas pattern

### services/llm_client.py (LLM Client)
- **Resilience**: Retries, circuit breaker, fallback provider
- **Budget**: `LLM_TOTAL_BUDGET` hard timeout
- **Issues**: No request logging; secret masking regex complexity
- **Positive**: Structured error types; detailed retry logic

### services/direct_chat_service.py (Direct Chat)
- **Complexity**: 1200+ lines; single massive function
- **Features**: Token bucket, CB, tools, memory, RAG, personas
- **Issues**: Monolithic; hard to test; context building inline
- **Positive**: Comprehensive feature set; fail-open patterns

### services/summary_memory.py (Memory Manager)
- **Architecture**: 3-level (L1/L2/L3) + GraphRAG v2
- **Epic 60**: Phases A-D (dedup, merge, decay, quota, touch, int8)
- **Issues**: Magic numbers; complex MMR; vec reactivation logic
- **Positive**: Thorough documentation; spec references; pure functions

### handlers/ (23 routers)
- **Pattern**: Observer-style (UNHANDLED) for SmartModule routers
- **DI**: Global `_service`/`_db` pattern (testing difficult)
- **Filters**: Custom aiogram filters for word/user matching
- **Positive**: Clear separation; consistent error handling

### web/ (TMA Admin Panel)
- **Stack**: FastAPI + Vue 3 (no build) + vanilla JS
- **API**: 15+ endpoints; chat-scoped via header
- **Issues**: No CSP; CORS default; no error boundaries in JS
- **Positive**: Clean separation; spec-driven UI

### filters/ (12 custom filters)
- **Pattern**: aiogram `Filter` subclasses with `__call__`
- **Word Lists**: Centralized in `word_lists.py` (135+ danger words)
- **Issues**: Some filters compile regex at module load
- **Positive**: Reusable; well-documented

---

## Recommendations by Priority

### Immediate (Week 1-2)
1. **Fix bot.py globals**: Introduce `ApplicationState` class
2. **Add null checks in on_shutdown**: Guard all 16 globals
3. **Extract LLMClient factory**: Single creation point
4. **Validate pg_db pool sizing**: Configure from settings
5. **Add router order test**: CI gate for handler precedence

### Short-term (Month 1)
6. **Split bot.py**: `main.py`, `services.py`, `routers.py`, `lifecycle.py`
7. **Config validation**: Fail-fast schema validation at startup
8. **PII filtering in observer**: Detect/redact sensitive data
9. **Cache TTL in ConfigCache**: Auto-refresh stale entries
10. **Structured LLM logging**: DEBUG level request/response logs
11. **DirectChat refactor**: Pipeline stages for context/LLM/tools/memory
12. **Param catalog completeness test**: Settings ↔ REGISTRY sync

### Medium-term (Quarter)
13. **DI Container**: Lightweight dependency injection
14. **Integration Tests**: Router chain, API contracts, DB migrations
15. **Observability**: Metrics for LLM calls, cache hit rates, worker budgets
16. **CSP Headers**: Secure TMA admin panel
17. **Secret Management**: Vault integration; rotation automation

---

## Architecture Observations

### Strengths
1. **Fail-Open Resilience**: Services degrade gracefully (PG down → SQLite defaults)
2. **Hot Config**: Runtime parameter changes without restart (ConfigCache + NOTIFY)
3. **Spec-Driven Development**: Every feature references spec sections (T-XXX, Epic XX)
3. **Comprehensive Memory**: 3-level + GraphRAG + vector search + FTS fallback
4. **BYOK Support**: Per-chat API keys with budget enforcement
5. **Rich Observability**: In-memory log ring, uptime heartbeat, oversight dashboard

### Technical Debt
1. **God Object (bot.py)**: 700 lines, 16 globals, 400-line startup
2. **Global State Pattern**: Module-level `_service` in 20+ handlers
3. **Monolithic Functions**: `generate_and_send` (1200 lines), `on_startup` (400 lines)
4. **Config Sprawl**: 400+ flat settings in single dataclass
5. **Test Gaps**: No integration tests; globals prevent unit testing

### Scaling Risks
1. **SQLite Write Contention**: Single writer; WAL helps but not for high throughput
2. **PG Connection Pool**: Unconfigured; may exhaust under load
3. **LLM Budget**: Global daily limits; no per-chat fairness guarantees
4. **Memory Growth**: VACUUM INTO daily but no compaction of vec tables
5. **WebSocket Scaling**: Single-process uvicorn; no horizontal scaling design

---

## Security Posture

### Good
- ✅ Secrets never logged (R17 compliance throughout)
- ✅ BetterStack token only logged as length
- ✅ Custom log handler with secret masking
- ✅ BYOK keys stored in PG (not in code/.env.example)
- ✅ Fail2ban/UFW/SSH hardening on prod (per docs)

### Needs Attention
- ⚠️ No CSP headers on TMA
- ⚠️ CORS not explicitly configured
- ⚠️ PII in memory (names, forwards, message content)
- ⚠️ No secret rotation automation
- ⚠️ SQL injection surface in dynamic queries
- ⚠️ `.env.example` contains all secret keys as templates

---

## Test Coverage Assessment

| Area | Coverage | Notes |
|------|----------|-------|
| Config parsing | Medium | Unit tests for `_env_*` helpers |
| Database migrations | Low | No automated migration tests |
| Router precedence | None | Critical gap - order not tested |
| LLM client retries | Low | Mock tests only |
| DirectChat pipeline | None | Too monolithic to test |
| GraphRAG logic | Medium | Some pure function tests |
| API endpoints | Low | Manual testing only |
| Worker budgets | None | No integration tests |

---

## Final Assessment

**Overall Code Quality**: **B+** - Strong architecture with clear spec-driven development, excellent resilience patterns, but significant technical debt in monolithic entry point and global state management.

**Production Readiness**: **A-** for current scale (single chat, ~10 users) but **C+** for scaling due to global state, unconfigured PG pool, and test gaps.

**Recommended Investment**: 2-3 sprints to refactor `bot.py`, introduce DI, add integration tests, and harden security headers before any scale-out.

---

*Report generated by Scanner on 2026-09-09*
*180+ files scanned across 12 directories*

---

# Round 10.3 Audit (F-13 tma-chat-selector-fixes, F-14 dm-user-settings, F-15 direct-sandbox-budget-investigation)

> Аудит 2026-09-10. HEAD d30b203 + uncommitted working tree 10.3 (27 files, +1323/−171).
> Проверено: спеки F-13/F-14/F-15 (plans/features/*), диффы всех изменённых файлов, полные
> тексты services/access.py, roles.py, chat_params.py, llm_client.py, summary_memory.py
> (горячие зоны), web/api/routes.py, web/api/access.py, gates.py, chat_lore.py, web/app.js,
> web/index.html. pytest: **4831 passed** (66s; базa 4760 → +71). `node --check web/app.js` — clean.
> Бэклог: все пункты (включая новые файлы 10.3) просканированы → отмечены [x].

## Статус известных находок (из прошлых отчётов)

| ID | Статус в 10.3 | Комментарий |
|---|---|---|
| HIGH-004 | 🔶 частично | F-15 добавил диагностику budget-пути (details-снапшот в NoApiKeyForChat + WARNING `[direct] no key…` c `details=`) и маскированный raw-фрагмент в WARNING memorize. Полный LLM request/response DEBUG-лог — вне 10.3 (заявлено F-15 §6) → **остаётся открытой** |
| MED-021 | 🔶 частично | F-13 AC-3: configError-баннер в loadConfig (403/503/сеть) + «⟳ Повторить»/«✕», очистка при успехе/setActiveChat. Остальные API-сбои (гейты/оверсайт/лор) — без error-boundary → **частично закрыта** |
| MED-019 | 🔶 частично | F-14: can_edit_param/can_access_chat/eligible_type расширены is_dm-ветками; новые юнит-тесты test_dm_access.py + API-контракты (403 чужого ЛС, keys→False, fail-open). «Упрощение сложной логики» не выполнено (веток стало больше) → **частично** |
| MED-017 | ❌ открыта | REGISTRY 383/71, Settings 359 — без дифов (эталон test_param_catalog зелёный), но теста-сверки Settings↔REGISTRY не добавлено |
| MED-022 | 🔶 частично | +71 тест (маркеры F-13 AC-1/2/3/5, test_webapp_dm_ui, test_dm_access, fallback-парсер/ретрай, S1/S2/S3). Интеграционных тестов роутеров/миграций по-прежнему нет |
| MED-015 | ❌ открыта (by design) | direct_chat_service монолит не рефакторится; F-15 — только аддитивные правки (заявлено в границах) |

## Новые находки раунда 10.3

### [R10.3-1] severity: minor — DM-скоуп: контролы models.* (per_chat=False) редактируемы во фронте, но сервер всегда 422
**Файл**: `web/app.js` ~1334-1338 (`canEditConfig`, DM-ветка) + `web/index.html` ~599/705 (кнопки Save, `:disabled="!canEditConfig(item.key)"`).
**Суть**: ветка `if (this.isDmCtx() && String(key).split('.')[0] !== 'keys') return true;` включает редактирование ВСЕХ не-keys ключей, включая `models.*` (29 ключей, per_chat=False — проверено по REGISTRY). В DM-скоупе GET /api/config отдаёт models как «глобальную справку», но тумблеры/инпуты/«Сохранить» активны → каждый save даёт 422 «ключ нельзя переносить на уровень чата» (гейт routes.py POST). Спека F-14 §6.2/§3.2 явно требует **read-only** models в DM. Сервер защищён (не security-дыра), но UX-шум и несоответствие спеке; для group-local_admin этой проблемы нет (их canEditConfig упирается в sections/params) — регрессия только DM. Рекомендация: в DM-ветке учитывать `item.per_chat` (передавать item, а не key) либо скрывать per_chat=False на DM.

### [R10.3-2] severity: minor — configError-баннер не очищается при 401-тосте и дублирует 403-тост api()
**Файл**: `web/app.js` 1381-1398 (loadConfig.catch), `web/api`-обёртка api() (тост «Доступ запрещён»).
**Суть**: (а) при 403 баннер + toast api() одновременно (по спеке задумано, но шумно); (б) если после 403-баннера случится 401 (протухшая initData), баннер остаётся на экране (authLocked блокирует загрузку, баннер не очищен) — некритично, т.к. дальше идёт authError-экран. (в) `configError` не сбрасывается при переключении вкладок в том же чате — «✕» обязателен. Все три пункта — UX-мелочи; логика статус-кодов верная (403/503/сеть разделены, 401-тост не изменён).

### [R10.3-3] severity: info — несогласованная cap-семантика «лимит = 0» между parse_fact_list и _fallback_parse_facts
**Файл**: `services/summary_memory.py` ~416 (parse_fact_list) vs ~504-505 (_fallback_parse_facts).
**Суть**: parse_fact_list: `if len(facts) >= (hot.get(...) or 0): break` — при лимите 0 обрезает ПОСЛЕ ПЕРВОГО факта; fallback-парсер: `if limit and …` — 0 трактует как «без лимита». Дефолт каталога ненулевой (проверка: limits.graph_extract_max_triplets default), поэтому в проде не стреляет; код-стиль/консистентность. Заодно: поведение «0 = 1 факт» в parse_fact_list — pre-existing (не регрессия 10.3).

### [R10.3-4] severity: info — DM-владелец не может запретить allow_global для своего ЛС
**Файл**: контракты F-14 (web/api/routes.py POST /api/config keys.*→422; keys/own — только BYOK).
**Суть**: у ЛС-юзеров единственный способ не расходовать глобальный бюджет/ключ — поставить свой BYOK-ключ. Выставить `keys.allow_global=false` для своего ЛС нельзя (keys.* скрыты/422; oversight-global_key — только global admin). По спеке так задумано (§3.2), но это пробел приватности для юзера, который хочет «не пользоваться чужим ключом» без своего. DM key-status (GET /api/config/keys/status, 200 для владельца) показывает allow_global и бюджеты — видимость есть, управления нет.

### [R10.3-5] severity: info — fail-open/fail-closed асимметрия DM-гейта саммари (зафиксировать как поведение)
**Файл**: `services/chat_params.py` `chat_summary_enabled` / `get_chat_param_defaulted`.
**Суть**: DM-путь при недоступности PG/кэша (или пустом профиле) → False (fail-closed; саммари ЛС OFF), групповой путь → hot.get (fail-open). Осознанно (DM default OFF — единственное исключение из наследования), НО: при PG-down ЛС с явным override=True временно теряет инъекцию конспекта (S1/S2), пока кэш не восстановится. Плюс: ChatParamsCache негативно кэширует отсутствующий DM-профиль ({}, updated_at=None) до 120с — сразу после первого POST-создания профиля чтения консистентны (NOTIFY-инвалидация), но S1/S2 до профиля видят False — приемлемо.

### [R10.3-6] severity: info — F-15 fallback-ретрай memorize не лимитирован по числу параллельных фоновых вызовов
**Файл**: `services/summary_memory.py` ~1607-1626 (_memorize_facts_inner).
**Суть**: при «мусорном» ответе экстрактора каждый fire-and-forget memorize делает +1 LLM-вызов (жёсткий промпт). Всплеск «мусорных» ответов (промпт-дрейф/плохой фоллбэк-провайдер) = удвоение фоновых токенов memorize-хуков по всем чатам (бюджет LLM общий). Ретрай bounded = 1 на вызов, но не capped по частоте/чатам. Не блокер (фоновый, R16 не задет), но стоит держать в уме при бюджетах.

## Проверенные области — вердикты (логические дыры НЕ найдены)

1. **DM-матрица прав (roles.py/access.py)**: DM-ветка до chat_admins-лукапа, role_chat=None, is_local_admin=False (F-11-меню не открывается), DM_OWNER_PRESET без chat_lore/group-секций; rank=max(ранг,3). Чужой ЛС (в т.ч. global admin) → can_access_chat False → 403; gates PUT DM → 403; chat_lore DM → 404 (все эндпоинты через _require_chat); keys.* в POST /api/config → 422; BYOK-гейты DM-владельцу — открыты с ensure_scope_profile. Дыр обхода legacy-эндпоинтов не обнаружено (все X-Chat-Id-пути проверены: routes.py 364/380+/563+/590+, gates.py, chat_lore.py, oversight.py — oversight global-admin-only).
2. **Изоляция DM (П.1-П.6)**: chat_lore_store list_* + oversight PROFILE_COLS_SQL + access CHATS_FOR_USER_SQL — фильтр chat_id<0 добавлен везде, где списки. LoreWorker/ностальгия не видят DM. Ноль DDL — соблюдено.
3. **S1/S2/S3 саммари**: chat_summary_enabled — единственный резолвер; группа — байт-в-байт hot.get; ЛС — override→cast→fallback=False; scheduler _tick фильтрует chat_id>0 (None-guard есть). bot.py:613-643 не дифнут. L3/GraphRAG-память не гейтится (по спеке). Ретрай F-15 не попадает в крон _extract_and_save_graph (там parse_triplets, отдельный путь) и не в синхронные пути (все memorize-вызовы — fire_and_forget; summary_generator:153 — fire_and_forget).
4. **BYOK-фоллбэк (llm_client._resolve_api_key_and_source)**: повторное чтение своего ключа после budget_exceeded — ровно 1 доп. SELECT (нет циклов); usage-счётчик (_record_global_usage) вызывается только при source='global' → двойного расхода бюджета нет; details-снапшот секретов не содержит (used/limit/day/allow_global/resolve_path); WARNING direct_chat_service:546 логирует repr(details) — R17 ок. Исключение NoApiKeyForChat пробрасывается до _post (LLM не вызывается).
5. **Фронт F-13/F-14**: единый select (1 шт., picker-методы удалены, chatPickerOpen=0), `✕</button>` — 1 (сайдбар), closeApp=0, toggleFullscreen жив; v-for/v-if-развязка через `<template>` корректна (Vue3), выражение-фильтр сохранено на дочернем div; configError-логика (очистка в успехе/setActiveChat); isDmCtx/canViewTab/canEditConfig/resetChatOverride — серверные гейты дублируют фронт (403/422 защищают); setActiveChat не вызывает двойных loadConfig; бейдж «ЛС #id» и empty-states актуальны; z-index 45 (sidebar) < 50/60 — каскад соблюдён.
6. **int/str chat_id**: is_dm_scope делает int() с None-guard; _chat_id_or_none → int; scheduler int(chat_id) c None-guard; select String()/parseInt — консистентно. Отрицательные id групп не пересекаются с DM (>0). Гонок/двойных вызовов в изменённых путях не выявлено.

## Итог 10.3
- **Блокеров/major: 0.** Security-периметр (DM-изоляция, R17, бюджет) держится серверными гейтами.
- **Minor: 2** (R10.3-1, R10.3-2), **Info: 4** (R10.3-3…R10.3-6) — в основном UX/консистентность, код-правки не требуются для мержа.
- pytest **4831 passed**; node --check clean; git diff --check чист (проверено в выводе diff: только LF/CRLF-warnings).

*Round 10.3 report generated by Scanner on 2026-09-10*

---

# Round 10.4 Audit (A/B/C/D/E/F/G/H: реструктуризация админки + 8 фич)

> Аудит 2026-09-10. HEAD 1410a68 + working tree 10.4 (14 файлов модифицировано,
> 24 untracked; +1691/−400). Проверено: спеки 8 фич (A…H, plans/features/*),
> диффы всех изменённых файлов, полные тексты param_catalog.py (TAB_RULES/
> _TAB_BY_GROUP/select-поля/_MEMORY-разметка), chat_params.py (_resolve_from_root),
> direct_chat_service.py (_budget_gate/_apply_context_budget/_thread_limit/_cp_g),
> summary_memory.py (per-chat точки), web/api/routes.py (select-валидация обе
> ветки), web/api/chat_lore.py (H-2 обогащение), web/app.js (TABS/flatGroupRank/
> sectionTitle/relChat-гвард), web/index.html (select-виджет, аккордеоны,
> relations/lore-конфиг-блоки, карточки модулей), оба backfill-скрипта.
> pytest: **4860 passed** (57.8s; база 4831 → +29; ijson доустановлен в локаль —
> 2 history-теста не собирались до этого, не регрессия). `node --check web/app.js` — clean.
> `git diff --check` — чист (только LF/CRLF-warnings).

## Проверка покрытия «ни один из 383 не пропал» (главный риск раунда)

- **GROUP-покрытие**: HEAD: 72/74 групп на конфиг-вкладках (content_info/
  content_media — никогда не были; это категория content — не-конфиг); 10.4:
  **72/74 — множества групп идентичны HEAD** (ADDED=[], REMOVED=[]).
- **REGISTRY 383 = 383; GROUPS 74 = 74; SETTINGS 359 = 359** (эталон MED-017
  соблюдён; `test_param_catalog` зелёный).
- `_TAB_BY_GROUP` импортируется без ValueError; каждая группа ровно на одной
  вкладке (reactions_triggers 4 / permsoc 17 / modules_switches 2 / chat_lore 2 /
  people_names 1 / relations 2 / memory_rag 4 / memory_dream 1 / memory_nostalgia 1 /
  llm_providers 15 / prompts 8 / limits 15 = 72).
- **Вердикт: потерь параметров/групп НЕТ** (это главный негатив-критерий ТЗ 8).

## Новые находки раунда 10.4

### [R10.4-1] severity: minor — лог WARNING graphrag-обрезки показывает ГЛОБАЛЬНЫЙ лимит, режет per-chat
**Файл**: `services/summary_memory.py:1991-1993` (`get_rag_context`).
**Суть**: обрезка `context = context[:(_rag_max_chars or 0)]` идёт по per-chat
значению, но WARNING `"context truncated to %d chars"` подставляет
`hot.get("limits.graph_rag_context_max_chars", …)` — глобальное. При override
у -1002661910336 (×2) лог будет врать (напр., «truncated to 4000» при реальном
пороге 4000×2). Ремедиация: подставить `_rag_max_chars` в лог (строка 1993).

### [R10.4-2] severity: minor — смена активного чата НЕ сбрасывает/перезагружает список участников на вкладке relations → кросс-чатовая запись
**Файл**: `web/app.js:738-769` (`setActiveChat`) + `:2569-2614` (`saveRelationManual`).
**Суть**: ревью-фикс закрыл кросс-чат для перехода между ВКЛАДКАМИ (setTab-сброс
`chatLoreProfile`), но если юзер НА вкладке relations меняет чат в глобальном
селекторе: `setActiveChat` вызывает `loadConfig`, но НЕ перечитывает участников
и НЕ очищает `chatRelations`. Экран показывает участников чата A, все кнопки
`saveRelationManual/removeRelationManual/toggleRelationsEnabled` при этом пишут в
`relChat = activeChatId` (чат B) — ручная стадия/заметка уйдёт чату B (или
тумблер переключит B). Класс той же ошибки, что закрывалась ревью-фиксом №2.
Ремедиация: в `setActiveChat` добавить ветку `activeTab === 'relations'` →
`this.chatRelations = []` + (не DM) `loadRelations(id)` (как в setTab).

### [R10.4-3] severity: minor — бэкфил G молча НЕ создаёт override `chat_thread_max_tokens`/`chat_global_context_max_tokens` (Settings None) → «тред ×2» фактически не достигается
**Файл**: `scripts/backfill_104_overrides.py:43-63` (`_current_value`/`_target_value`)
+ `config/settings.py` (CHAT_THREAD_MAX_TOKENS=None, CHAT_GLOBAL_CONTEXT_MAX_TOKENS=None).
**Суть**: множители для этих двух ключей — в OVERRIDE_MULTIPLIERS (2.0 и 1.5), но
`hot.get(key, None)` → None → `float(None)` → TypeError → base None → **skip**
(печатается «skip (нет дефолта)», выхода нет). Итог: `_thread_limit`-helper
читает per-chat, но override никогда не пишется; тред остается на chars-лимите
CHAT_THREAD_MAX_CHARS=2000 (×1), хотя спека G §4 и round10.4_review_fixes.md
(«thread-токены/чары — _thread_limit + thread_limit у _render_thread», «таблица
значений бэкфила соответствует фактическому поведению») заявляют ×2.
Токенный лимит в actuelle кодовой семантике resolve_chat_limit — «cells-mode»:
для global_context «×1.5» достигается через max_chars (4000→6000) — там skip
безвреден; для треда — **цель не достигнута** (нужен override
`limits.chat_thread_max_chars`=4000, которого в таблице нет).
Ремедиация: добавить `limits.chat_thread_max_chars: (2.0, None)` в
OVERRIDE_MULTIPLIERS (или явно зафиксировать «тред остаётся глобальным» в отчёте).

### [R10.4-4] severity: minor — блок обогащения фото (H-2) тянет getUserProfilePhotos для ВСЕХ 100 строк, хотя фото нужны топ-50
**Файл**: `web/api/chat_lore.py:588-609` (`list_relations`).
**Суть**: `user_display_info` возвращает И username, И photo_file_id и кэширует
оба — первый проход (gather, Semaphore(5)) по всем 100 участникам делает и
`get_chat_member`, и `get_user_profile_photos` для каждого; второй проход (топ-50)
— кэш-хит (фото_meta создан заново, но кэш отдаёт). Итог на холодный рендер:
100 get_chat_member + **100** get_user_profile_photos вместо 100+50 (спека H-2:
«photo — только топ-50; остальные — ленивый догруз фронтом»). Лишние ~50
тяжёлых вызовов Bot API на первый рендер (кэш 1ч смягчает; семафор 5 держит
лимиты). Ремедиация (опционально): `user_display_info(chat_id, uid, with_photo=…)`
или отдельный фото-флаг для строк 51-100. **НЕ критично**: fail-open/кэш есть,
производительность в NFR-границах.

### [R10.4-5] severity: info — «Перезагрузить» в 409-модалке на вкладке relations не перезагружает участников
**Файл**: `web/app.js:2462-2467` (`confirmLoreReload`) + modal index.html:2187.
**Суть**: `confirmLoreReload` → `target = chatLoreSelectedId || chatLoreProfile.chat_id`
— на вкладке relations оба null (setTab-сброс; chatLoreSelectedId — лор-скоуп),
клик «Перезагрузить» закрывает модалку бездействием. Список участников остаётся
стейлом; recovery — кнопка ⟳ (есть). UX-пробел, не потеря данных.

### [R10.4-6] severity: info — бэкфилы (оба) без optimistic-метки: гонка «скрипт ↔ живой админ» может затереть чужой override
**Файл**: `scripts/backfill_104_chat_flags.py:47-49`, `backfill_104_overrides.py:102-104`.
**Суть**: `set_chat_params(..., expected_updated_at=None)` — «последняя запись
побеждает», но set_chat_params ЗАМЕНЯЕТ весь namespace `overrides` целиком
(chat_params.py:280-283). Если админ между `get_all_chat_params` (в скрипте) и
записью изменит ДРУГОЙ ключ — его запись затрётся (overrides снова полностью
из скриптового root). Окно мало (деплой-минуты), идемпотентность-гарантия
(«не перезаписываем существующие ключи») НЕ нарушается — только свежие записи
того же окна. Ремедиация (опционально): expected_updated_at=прочитанная метка +
retry на 409.

### [R10.4-7] severity: info — G-4-граница шире, чем задокументировано: direct-chat RAG-путь и `get_rag_facts` остались глобальными
**Файл**: `services/direct_chat_service.py:1649` (cap `graph_rag_context_max_chars`)
и `services/summary_memory.py:2015-2018` (`get_rag_facts` — `graph_rag_facts_limit`).
**Суть**: round10.4_review_fixes.md §4.2 фиксирует границу только для
`summary_xml.py`-рендера и `_participant_roster`; фактически НЕ переведены ещё и
(а) сборка <RAG_Memory> в direct чате (cap 1649), (б) список-кандидатов
`get_rag_facts` (лимит фактов). Override ×2 для `graph_rag_*` (G-бэкфил) применяется
в summary-callback-путях, но НЕ в direct-chat RAG-блоке. Воздействие: «×2 RAG в
прямом чате» частично не реализован — стоит дописать в §2 G-отчёта (документирование).

## Закрытое в раунде 10.4 (из старых находок)

| ID | Статус | Что именно закрыто |
|---|---|---|
| R10.3-1 (DM models.* редактируемы → 422) | 🔶 частично (by design) | Spec B §6: «фикс отложен (вне скоупа)» — не закрыто, но и не усугублено (canEditConfig DM-ветка не диффена) |
| R10.3-2 (configError-баннер) | 🔶 частично | Без изменений; остаётся «частично» (MED-021-состояние 10.3) |
| R10.3-3 (limit=0 cap-семантика) | ✅ закрыто | `window[-max(1, _g_limit):]` (direct_chat_service.py:1792) — Reviewers-наблюдение устранено; старый «-0 → всё окно» больше невозможен |
| R10.3-4 (DM нельзя выключить allow_global) | ❌ открыта | Вне скоупа; контракты не менялись |
| R10.3-5 (fail-open/fail-closed асимметрия) | ❌ открыта (by design) | Гейт саммари не диффнут |
| R10.3-6 (ретрай memorize без кэпа) | ❌ открыта | Не задевалось в 10.4 (пути не диффились) |
| HIGH-004 (LLM DEBUG-лог) | ❌ открыта | F-15 diagnostics остались; полный лог — вне |
| MED-015 (монолит direct_chat) | ❌ открыта (by design) | G-3 — только аддитивные per-chat точки |
| MED-017 (REGISTRY-сверка) | ❌ открыта | 383/71/359 соблюдены тестом, но теста Settings↔REGISTRY нет |
| MED-019 (can_edit_param сложность) | ❌ открыта | не упрощалась |
| MED-021 (error-boundary) | 🔶 частично | configError-баннер (10.3); остальные API сбои — без boundary |
| MED-022 (покрытие тестов) | 🔶 частично | **+29 теста** (test_104_backend_additions 11, test_progressive_tab_basic_coverage 3, test_frontend_tab_mapping +~120 строк маркеров, webapp_api/webapp_dm_ui/avatars/nav_disclosure) — интеграционных роутер-тестов нет |

**Новых блокеров/major: 0.** Периметры: R16 (id никогда имя — сохранён: каскад
H-5 без изменений, name==uid → удаление), R17 (секреты в select/labels отсутствуют;
details не диффились), DM-изоляция (relations-vкладка в ЛС — заглушка 404; записи
через /api/config X-Chat-Id=ЛС — per_chat=True и is_dm_owner — канон F-14),
F-15/бюджет (×2-контекст + flags.off — документированный баланс G-7; sandbox R16
при 25 req/сутки — прежнее поведение). Роутеры bot.py, каноны промптов, SQLite v8,
PG-DDL — без диффов (проверено диффом; ноль DDL).

## Итог 10.4
- **Блокеров: 0, Major: 0.** Minor: 4 (R10.4-1…R10.4-4), Info: 3 (R10.4-5…R10.4-7).
  Все — UX/лог/скрипт-точность; код-фиксы для мержа НЕ обязательны (но R10.4-1 и
  R10.4-3 — 1-строчные ремедиации, рекомендуются в follow-up).
- pytest **4860 passed**; node --check clean; git diff --check чист.
- Обновлены: full_audit_results.md (этот раздел), audit_backlog.md (10.4-пункты),
  global_map.md (Round 10.4 map additions).

*Round 10.4 report generated by Scanner on 2026-09-10*

---

# Round 10.5 Audit (tma-relume-redesign: Relume TMA redesign)

> Полный отчёт — `plans/reports/round10.5_scanner_audit.md`.
> HEAD `0bdf272` (10.4) + рабочее дерево 10.5 (38 записей; +2391/−159 tracked).
> pytest **4959 passed** (база 4860 → +99); `node --check` clean; `git diff --check` clean.

## Новые находки 10.5 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.5-1 | minor | `web/app.js:775/816-819/1767` | BackButton не переинициализируется после позднего контекста (`ready`) → in-app «←» + невызванный `goBack()` на depth>0 |
| R10.5-2 | minor | `web/app.js` canEditConfig (DM) + `param_catalog._MODELS_PG_ONLY` | DM: 4 новых `per_chat=False` `models.*` редактируемы во фронте → POST даёт 422 (класс R10.3-1, 29→33 ключей) |
| R10.5-3 | info | `web/api/routes.py:1080-1092` | `/api/status/key-history` — любой авторизованный юзер (как `/api/status`, RBAC-исключение; секретов нет) |
| R10.5-4 | info | `services/key_history.py:38-43` | `_ALLOWED_PROVIDER_KEYS` не используется; deny-list `"token"` широкий (только QA) |
| R10.5-5 | info | `config_cache.rename_role` + `routes.rename_role_endpoint` | гонка rename → 500 вместо 409 (optimistic-защиты нет) |
| R10.5-6 | info | `web/app.js:1982` | `setMenu` мёртв (pre-existing, не 10.5) |
| R10.5-7 | info | `status_service.py:316` | синхронный файловый I/O `key_history.maybe_save()` в async-пути (мал, 5-мин порог) |

**Верифицировано чисто:** каталог **387/74/359**; TABS↔TAB_RULES; ноль PG-DDL;
SQLite v8; `bot.py` не тронут; `media/` не тронут; секреты не коммитятся; R16/R17;
иконки (26/26 PUA совпадают с код-каноном и присутствуют в субсете); DOMPurify
self-host 3.4.15 fail-closed.

## Итог 10.5
- **Блокеров: 0, Major: 0.** Minor: 2 (R10.5-1, R10.5-2), Info: 5 (R10.5-3…R10.5-7).
- Обновлены: `round10.5_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.5 report generated by Scanner on 2026-09-10*

---

# Round 10.6 Audit (tma-ia-modules-rework: navbar/Модули(11)/AI(7)/PERMsoc)

> Полный отчёт — `plans/reports/round10.6_scanner_audit.md`.
> HEAD `be7b85b` + рабочее дерево 10.6 (24 modified + 4 untracked; +1920/−1136 tracked).
> pytest **5023 passed** (база 4962 → +61); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.6 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.6-1 | minor | `web/index.html:701-1053` + `:709-751`; `web/app.js:856-859,2517-2563` | На вкладке LLM Провайдеры generic-рендер `currentTabGroups` не подавлен → 21 из 37 параметров дублируются (prov-блок + generic-группа: base_url/model/api_key и др.); данные не страдают |
| R10.6-2 | minor | `services/llm_probe.py:58-80` (`_safe_base`); `web/api/routes.py:1225` | SSRF: `http` — только точный loopback, а `https` принимается для ЛЮБОГО хоста (127.0.0.1/localhost/internal/DNS-rebind) с возвратом до 300 симв. ответа; ограничено `requires_global_admin` |
| R10.6-3 | minor | `web/api/routes.py:126-132,1225` | 422-валидация Pydantic 2 возвращает `input` с присланным `api_key` (R17-эхо тому же админу при малформ-запросе; подтверждено на минимальном FastAPI) |
| R10.6-4 | info | `services/llm_probe.py:35-38`; `web/app.js:388-398` | `media_share` вне списка §6.3; `embeddings` в UI `testable:false`; `llm_guard` намеренно не тестируется |
| R10.6-5 | info | `web/app.js:228-233` (+208/229) | мёртвые записи `ICONS` (`speed/theater_comedy/toggle_off/toggle_on/stop_circle/account_balance_wallet`) после удаления вкладок |
| R10.6-6 | info | `web/api/routes.py:1240-1242` | rate-limit слот `(user,block)` расходуется до валидации блока (`_LLM_TEST_LAST[...] = now` до `probe_block`) |

**Закрыто в 10.6:** R10.5-1 (BackButton re-init на `ready` под `_boundBackApi`;
`goBack` при модалке закрывает окно) и R10.5-2 (DM `canEditConfig` учитывает
`per_chat===false` → `models.*`/`keys.*` read-only).

**Верифицировано чисто:** каталог **392/91/364/mapped 89**, `TAB_RULES`=19, каждая
группа ровно на одной вкладке; ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/`
не тронут; секреты не коммитятся; 5 master-флагов default True и реально гейтят
(5 handler-точек); 10 миселённых PERMsoc-ключей в М5/М6/М7; Леха/Костик раздельно;
sidebar удалён; fullscreen-scroll; emoji→Material в `#/how`/матрице; эксклюзивный
аккордеон `accessOpen`; `keys_youtube`→М6, `models_checkup`/`keys_betterstack`→М9;
per-block `POST /api/llm/test` (403/200/429/R17).

## Итог 10.6
- **Блокеров: 0, Major: 0.** Minor: 3 (R10.6-1…3), Info: 3 (R10.6-4…6).
  Для мержа не обязательны; R10.6-1/R10.6-3 — точечные ремедиации, рекомендуются.
- Обновлены: `round10.6_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.6 report generated by Scanner on 2026-09-11*

---

# Round 10.7 Audit (admin-ui-bugfixes-round107: header/nav, stats, logs)

> Полный отчёт — `plans/reports/round10.7_scanner_audit.md`.
> HEAD `2ccf558` + рабочее дерево 10.7 (9 modified + 2 untracked; +403/−125 tracked).
> pytest **5042 passed** (база 5023 → +19); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.7 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.7-1 | minor | `services/status_service.py:290-300,376-378` | gap-fill идёт до `now_slot` включительно: сразу после 5-мин границы текущий слот ещё без heartbeat (пишется раз в 60 с) → правый край графика до ~60 с помечен `down`, `last_heartbeat` откатывается к предыдущему слоту. Спека §2b предписывает такой trade-off; данные не искажаются |
| R10.7-2 | info | `services/status_service.py:291-301` | `[-288:]` может отбросить единственный ранний `up`-бакет (first_slot = floor(ts) до `since` на ≤299 с → сетка 289), тогда `last_heartbeat=None` при формально бывшем heartbeat. Узкий край |
| R10.7-3 | info | `web/app.js:741-742,3344-3352` | `copiedTimer` очищается только при следующем клике; при уходе со вкладки <800 мс таймер сработает и сбросит `copiedIndex` (косметика, корень не размонтируется) |
| R10.7-4 | info | `tests/test_font_subset.py:73` | Тест проверяет PUA-код в `app.js`, но не cmap WOFF2. Независимо (`fontTools`) подтверждено: все 20 `ICONS`-кодов есть в cmap (26 глифов). R106-5 безопасен; пробел покрытия pre-existing |
| R10.7-5 | info | `web/app.js:3305-3308,3354-3360` | Заявленный «context-loss» `this.logs.map(this.logText)` фактически отсутствовал (`logText` не использует `this`); правка безвредна, формулировка причины неточна |

**Закрыто в 10.7:** R10.6-5 (мёртвые записи `ICONS` — удалены `account_balance_wallet`
`stop_circle` `theater_comedy` `toggle_off` `toggle_on` `speed`; 0 обращений; все оставшиеся
20 PUA-кодов присутствуют в cmap субсета). R10.6-1/2/3 остаются открытыми (вне UI-скоупа,
кандидаты 10.8).

**Верифицировано чисто:** каталог **392/91/364/mapped 89**, `TAB_RULES`=19, `CONFIG_TAB_TITLES`=19;
ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/` не тронут;
`uptime_heartbeat.py`/`key_history.py` не тронуты; секреты не коммитятся; R17/RBAC/DM без
изменений; `scope*` — 6 computed-функций, шаблонные привязки без `()`; контракт `/api/status`
(`buckets/last_heartbeat/since/until/generated_at`) сохранён; `execCommand`-fallback проверяет
boolean → нет ложного тоста; ghost-textarea удаляется в `finally`.

## Итог 10.7
- **Блокеров: 0, Major: 0.** Minor: 1 (R10.7-1), Info: 3 (R10.7-2…R10.7-4) + R10.7-5 (nit).
- Обновлены: `round10.7_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.7 report generated by Scanner on 2026-09-11*

---

# Round 10.8 Audit (admin-ui-round108: renames, emoji→icons, Android logs, access windows)

> Полный отчёт — `plans/reports/round10.8_scanner_audit.md`.
> HEAD `636a75d` + рабочее дерево 10.8 (18 modified + 2 untracked; +610/−224 tracked, WOFF2 13 428→18 388 B).
> pytest **5073 passed** (база 5042 → +31); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.8 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.8-1 | minor | `web/app.js:1023-1027`; `web/index.html:1620,1663,1797` | Esc не закрывает окна «Доступов»: `@keydown.esc` на неавтофокусируемом `.modal-card`, глобальный `_onKeydown` знает только `openModuleId`. Работают ✕/backdrop/Back. AC-4 требует Esc → 1-строчная ремедиация |
| R10.8-2 | info | `web/app.js:275-277,2085-2093` | Комментарий про `section` для `#/access/*` устарел; ветка `if (card.section)` в `openHubCard` осиротела (10.8 убрал `section` у access-карточек) |
| R10.8-3 | info | `web/app.js:43,184,189,895-905,2191-2194` | `TABS[].icon`/`visibleTabs`/`tabMat` — мёртвый путь (таб-бар удалён в 10.6); замена TABS-иконок инертна. Pre-existing, не регресс |
| R10.8-4 | info | `plans/backlog.md` | Статус раздела 10.8 «🟡 ПЛАНИРОВАНИЕ» при выполненной реализации; закрывается @PM Step 8 |
| R10.8-5 | minor | `config/settings.py:1069`; `README.md`; `web/index.html:69`; `web/app.py:50,62` | README v2.52.0, а `APP_VERSION`=2.51.0 (`/api/status.version` покажет старое); `@font-face`-URL не версионирован, `.woff2` `max-age=86400` → старый субсет 10.7 в кэше до 24 ч → tofu новых иконок. app.js безопасен (no-cache). Ремедиация: bump APP_VERSION + `?v=__APP_VERSION__` на шрифт |

**Закрыто в 10.8:** **R10.7-3** (`copiedTimer`/`copiedIndex` очищаются в `setTab`) и
**R10.7-4** (тест `test_font_subset` парсит `ICONS`↔`ICON_NAMES` и сверяет cmap WOFF2 через
`fontTools` — тест выполняется, не skip). R10.7-1/-2, R10.6-1/2/3 остаются открытыми (вне UI-скоупа).

**Верифицировано чисто:** каталог **392/91/364/mapped 89**, `TAB_RULES` 19;
ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/` не тронут; секреты не коммитятся;
**ICONS 37 == ICON_NAMES 37**, все 37 PUA-кодов в cmap субсета (лишних PUA нет, мёртвых нет),
маркер идемпотентности = `sha256(src_sha|ICON_NAMES)`;
`#/access/roles|local|admins` — три взаимоисключающих route-driven окна, `sec-*`-id целы,
deep-link/BackButton/ROUTE_PARENT сохранены, RBAC (`isGlobalAdmin`/`canEditRole`/`canViewTab`)
не ослаблен; логи — блочная раскладка без жёстких ширин, `fmtLogTime` = `DD.MM HH:MM:SS`,
toggle — Material-иконка только при `exc_text`; ровно один GLOBAL-бейдж; в `web/` 0 pictographic-emoji;
README: единственный `<details>` сбалансирован, шапка v2.52.0/5073.

## Итог 10.8
- **Блокеров: 0, Major: 0.** Minor: 2 (R10.8-1, R10.8-5), Info: 3 (R10.8-2…R10.8-4).
  Для мержа не обязательны; R10.8-1 (Esc) и R10.8-5 (APP_VERSION/кэш шрифта) — точечные
  ремедиации, рекомендуются в follow-up.
- Обновлены: `round10.8_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.8 report generated by Scanner on 2026-09-11*

---

# Round 10.9 Audit (admin-ui-round109: PERMsoc owner-blocks, scroll, описания, «Тяжёлые»/«Бюджет», dashboard/health, display-name, градиент)

> Полный отчёт — `plans/reports/round10.9_scanner_audit.md`.
> HEAD `51f308b` + рабочее дерево 10.9 (23 modified + 2 untracked; +1326/−605).
> pytest **5105 passed** (база 5076 → +29); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.9 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.9-1 | low | `services/status_service.py:192-207,217-226,244-277` | `model_source` у `llm_fallback`/`video_openrouter`/`emb_*` снова `"code"` при конфиге (в 10.8 fallback отдавал `"config"`); UI не рендерит, но это поле `/api/status` |
| R10.9-2 | low | `services/status_service.py:257-277` | `EMBEDDING_FALLBACK_*` читаются из `settings` (env-only, не PG — сейчас безопасно); `emb_fallback*` исчезают из реестра без env-ключа, поэтому их display-name недостижим (ожидалось «не настроен») |
| R10.9-3 | low | `services/status_service.py:10-15` | Шапка модуля описывает старый health (`GET {base}/models`, кэш 60с) и хардкод-провайдеров — противоречит ADR-109-3 |
| R10.9-4 | info | `services/status_service.py:283-305` | Health-кэш ключёван по `module_id`: смена base_url/key/model не инвалидирует ok ≤60с (URL раньше инвалидировал); ошибки — 10с |
| R10.9-5 | info | `services/llm_probe.py:9-13,28-32,163-164,238-254` | `_LLM_BLOCKS` включает `transcribe_groq` (нужно для `KNOWN_BLOCKS`), docstring-контракт — нет; `httpx.ConnectTimeout ⊂ TimeoutException` → статус `timeout` (по спеке допустимо) |
| R10.9-6 | info | `plans/backlog.md:5` | Раздел 10.9 «🟡 ПЛАНИРОВАНИЕ» при выполненной реализации; закрывается @PM Step 8 |

**Верифицировано чисто:** каталог **400/90/372/mapped 88**, `TAB_RULES` 19, `CONFIG_TAB_TITLES` 19;
ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/`/`.env` не тронуты; секреты не коммитятся;
**Ссылок на инфраструктуру IDE в коде/конфиге/тестах нет** (единственный не-plan hit — gitignored
`local_database_2026-09-04_history.db`, данные истории, не код); owner-блоки (4, все 21 owner-ключ
и 4 owner-группы существуют), один тумблер в `<summary>`, generic-bool исключён; backend
`SLAVIK_ENABLED` default True + `DEFAULT_SUB_FLAGS` даёт байт-в-байт для нетронутых; health —
реальный POST (`/chat/completions`, `/embeddings`, `/audio/transcriptions` для Groq-Whisper),
stale-200 не отдаётся, `timeout`/`502`/`unreachable` различаются; скролл — оба контейнера
(`document.scrollingElement` + `.scroll-area`); «Тяжёлые» удалены без потери (killswitch в
«Сводке»), «Бюджет фона» только в «Сводке»; RBAC/DM не ослаблены; `APP_VERSION` 2.52.0 оставлен
сознательно (T-1307 «no README»).

## Итог 10.9
- **Блокеров: 0, Major: 0, Medium: 0.** Low: **3** (R10.9-1…R10.9-3), Info: **3** (R10.9-4…R10.9-6).
  Для мержа не обязательны; точечные ремедиации — в follow-up.
- Обновлены: `round10.9_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.9 report generated by Scanner on 2026-09-12*
---

# Round 10.10 Audit (admin-ui-round1010: fullscreen-padding, mobile key-chart, provider values, DM heavy-modules OFF, Roles avatar/nick/widths)

> Полный отчёт — `plans/reports/round10.10_scanner_audit.md`.
> HEAD `da85b60` + рабочее дерево 10.10 (10 modified + 4 untracked; +555/−55).
> pytest **5140 passed / 1 skipped** (база 5105); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
> П.6 (Headroom) — OUT OF SCOPE репозитория (в коде ссылок нет).

## Новые находки 10.10 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.10-1 | low | `scripts/disable_dm_heavy_modules.py:217-238` | `noop`/`total` и dry-run-count считают ВСЕ активные ЛС, игнорируя `--chat-id`: staged-прогон печатает «из 100 ЛС»/`noop=99`, хотя 99 чатов не рассматривались |
| R10.10-2 | low | `scripts/disable_dm_heavy_modules.py:139-140` + `build_snapshot:87-101` + `restore:156-182` | apply пишет `meta.note`, snapshot хранит только overrides/gates, restore meta не трогает → прежний `meta.note` теряется безвозвратно |
| R10.10-3 | low | `web/app.js:3541-3548` | `renderKeyHistoryChart` при `keyHistory==null` делает ранний `return` без `chart.destroy()` → стейл Chart.js-инстанс на отсоединённом canvas до след. успешного рендера |
| R10.10-4 | info | `web/app.js:2965-2974` | `loadAdmins` грузит blob-аватары без `avatarSkipped`/`.catch`: повторные запросы при негативе, необработанные reject (паттерн существующего кода) |
| R10.10-5 | info | `web/app.js:2977+` vs `:4098` | `adminInitial` дублирует `avatarInitial`; ветка `admin.username` в модели API недостижима (username свёрнут в `display_name`) — стилевой дубль |

**Верифицировано чисто:** каталог **400/90/372/mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19;
ноль PG-DDL; SQLite v8; `bot.py` router order не тронут; `media/`/`.env` не тронуты; секреты
не коммитятся; **Headroom-ссылок в коде/тестах нет**; fullscreen-CSS (`max(env, --tg-*)`,
10.7/10.9 целы); окно графика строится от конца (≤ `MAX_HISTORY_POINTS`, ≥ `MIN_BUCKETS`,
новейший сэмпл последний, пропуск=null, точка при 1 сэмпле, контракт `api_payload` неизменён);
«Провайдеры» — контролируемый `:value` из `configItems` + `''`-очистка, секреты не префиллятся;
DM-скрипт идемпотентен (пустой патч=no-op, snapshot до записи + abort, `--restore` не затирает
`meta`, partial-failure → exit 1), дефолты новых ЛС = `gates dream/nostalgia=false` + 4 override=false;
«Роли» — enrichment копий под `requires_permission("access")`, `Semaphore(5)`, RAM-TTL 1ч,
fail-open, транзиентные Bot API-ошибки не негатив-кэшируются, XSS-safe (`{{ }}` + blob-URL);
`>✕</button>` == 4; RBAC/DM не ослаблены.

## Итог 10.10
- **Блокеров: 0. Critical: 0. High: 0. Medium: 0.** Low: **3** (R10.10-1…-3), Info: **2** (R10.10-4/-5).
  Для мержа не обязательны; R10.10-1/-2 — точечные ремедиации перед прод-`--apply` (T-1327).
- Обновлены: `round10.10_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.10 report generated by Scanner on 2026-09-12*
---

# Round 10.11 Audit (llm-providers-refactor-round1011: saved-key probe, LLM Провайдеры refactor, key-history chart, память-отчёт)

> Полный отчёт — `plans/reports/round10.11_scanner_audit.md`.
> HEAD `ec5dd1f` + рабочее дерево 10.11 (13 modified + 3 untracked; +747/−137).
> pytest **5168 passed / 0 failed** (база 5144); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
> Пункт 4 (прозаичный отчёт о памяти/сне/ностальгии) — docs-only, кода не касается.

## Новые находки 10.11 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.11-1 | low | `web/index.html:934-937` vs `:1188-1190`; `web/app.js:2510-2519` | Внешний `<details>` «Расширенные настройки» и внутренние per-group details делят один localStorage-ключ `adminbot.expand:llm_providers`: `:open` пере-применяется на рендере, `toggle` флипает общий флаг → самопроизвольное открытие/закрытие вложенных секций (класс был и до 10.11, внешний details — новый участник) |
| R10.11-2 | low | `services/status_service.py:261-263` vs `services/llm_client.py:305-308` | `models.embedding_fallback_model`: при пустом значении в БД рантайм → основная embed-модель, карточка статуса → env `EMBEDDING_FALLBACK_MODEL` (расхождение только при явной очистке + непустом env) |
| R10.11-3 | low | `services/llm_client.py:170-172`, `config/settings.py:341-343` | Устаревшая подсказка «правьте `EMBEDDING_FALLBACK_API_KEY(_2)` в .env»: после ADR-1011-2 ключи — first-class каталог (админка/PG), `.env` уже не авторитетен при наличии строки в `bot_settings` |
| R10.11-4 | info | `services/llm_probe.py:247-250` + `_safe_base:109-131` | Probe прикрепляет сохранённый секрет к caller-supplied `base_url` (global-admin-only; не новая привилегия — base_url и так конфигурируем, но стоит зафиксировать hardening) |
| R10.11-5 | info | `web/app.js:3670` | Мёртвая ветка `destroy()` в `renderKeyHistoryChart` (инстанс уже уничтожен в начале `:3617-3620`; R10.10-3 закрыт корректно) |
| R10.11-6 | info | `web/app.js:3587-3610,3643-3661` | Нет headless-теста фактического рендера `spanGaps:true`/`parsing:false`/`{x,y:null}`; JS-юниты — только конфиг/модель; ADR-1011-3 §5 даёт fallback |

**Верифицировано чисто:** каталог **400/90/372/mapped 88**, `TAB_RULES`/`CONFIG_TAB_TITLES` 19;
sanctioned Δ ADR-1011-2 — categorized **376** (models 42/keys 15), infra **28→24**, без роста
REGISTRY/Settings; ноль PG-DDL; SQLite v8; `bot.py` router order не тронут; `media/`/`.env`
не тронуты; секреты не коммитятся; **Headroom-ссылок в коде нет**; saved-key резолв R17-safe
(сырой ключ не эхо/не логируется, маска `{configured,last4}`); все 4 embed-фоллбэк-записи
резолвятся `hot.get` с сохранёнными дефолтами; UI-семантика `null`/`''` не изменена; шаблон
Vue сбалансирован (stack-парсер: 0 рассогласований); chart — точки `{x,y(ms)}`, `spanGaps:true`,
`stepped:true`, `parsing:false`, `type:'linear'` + HH:MM callback, без `type:'time'`; контракт
`api_payload`/`key_history.py` неизменён; RBAC/DM не ослаблены; удалённый `sections`
использовался только `sectionTitle` (`groupedForTab` — по `sources`) → потери групп нет.

## Итог 10.11
- **Блокеров: 0. Critical: 0. High: 0. Medium: 0.** Low: **3** (R10.11-1/-2/-3), Info: **3** (R10.11-4/-5/-6).
  Для мержа не обязательны; R10.11-1/-2/-3 — точечные follow-up.
- Обновлены: `round10.11_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.11 report generated by Scanner on 2026-09-12*
---

# Round 10.12 Audit (providers-kostik-round1012: embed/direct base_url decoupling, 422 global-save fix, merged provider blocks, Kostik reply-list)

> Полный отчёт — `plans/reports/round10.12_scanner_audit.md`.
> HEAD `32d1aa9` + рабочее дерево 10.12 (24 modified + 2 untracked; +1030/−141).
> pytest **5210 passed / 0 failed** (база 5172); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.12 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.12-1 | low | `web/app.js:3092-3112` (POST `:3100`) | `saveKeyItem` (generic-редактор секретов/`keys.*`) не переведён на global-save: при активном чате `api()` добавит `X-Chat-Id` → серверный 422 для `CHECKUP_BETTERSTACK_SQL_USER/PASSWORD`, `YOUTUBE_COOKIES_FILE`, `YOUTUBE_TRANSCRIPT_PROXY_*` (все `per_chat=false`). Тот же класс, что item 1; pre-existing (spec §1.4 ограничил фикс `saveBlock`/`saveConfigItem`), не регресс |
| R10.12-2 | info | `services/llm_probe.py:14` | Устаревший docstring: «embeddings — UI не рендерит кнопку теста: base_url нет» — после ADR-1011/10.12 у `embeddings_main` есть свой base_url и кнопка «Проверить» |
| R10.12-3 | info | `config/settings.py:191,195` | Комментарий «env-ключа НЕТ» относится к `KOSTIK_REPLIES`, но `KOSTIK_ENABLED` использует `_env_bool("KOSTIK_ENABLED", True)` и в `.env.example` не перечислен — доковая нестыковка |
| R10.12-4 | info | `web/index.html:3181` | `:key="'le' + i"` + `v-model="rows[i]"` (`list-editor`): index-based key, при удалении/вставке середины — DOM-переиспользование (курсор/фокус); данные не теряются |
| R10.12-5 | low | `web/app.js:362,380,400`; `web/index.html:810` | parent-блоки `direct`/`transcription`/`video_summary` имеют `modules == title`, поэтому `blockDisplayName(parent)` (fallback на `modules`) рендерит дубль («Прямые ответы  Прямые ответы»); у `embeddings` дубля нет; названия моделей на подблоках транслируются верно |

**Верифицировано чисто:** каталог **405/90/377/mapped 88**, `TAB_RULES` 19, categorized **381**; sanctioned Δ
+5 (models +2 / keys +1 / flags +1 / reactions +1); **ноль PG-DDL**; SQLite **v8**; `bot.py` router order
не тронут (только 4 пары DI-kwargs `embed_base_url`/`embed_api_key` в 4 точках); `media/`/`.env` не тронуты;
секретов нет; **Headroom-ссылок в коде нет**; embed-decoupling полная (chat↔embed base/ключ независимы,
пустой embed-base → chat-base, пустой ключ → `keys.llm_api_key`, fallback-каскад `EMBEDDING_FALLBACK_*` цел,
отдельный httpx-кэш embed + закрытие); `status_service.emb_main` на embed-base; probe primary-embed
зеркалит runtime-фолбэк; 422-фикс клиентский, серверный гейт (`routes.py:414-417`) и DM read-only (R10.5-2)
не ослаблены, global-путь проверяет права → эскалации нет; Kostik handler: пустой список → молчание,
JSON/str/мусор → `[]`, флаг `flags.kostik_enabled` (default True) реально гейтит; alias `KOSTIK_REPLIES`
сохранён для импортов; `providerCoveredKeys` покрывает новые ключи (нет generic-дублей);
`loadConfig`/`saveConfigItem` корректно работают с `widget=list` (массив без повторного парсинга).

## Итог 10.12
- **Блокеров: 0. Critical: 0. High: 0. Medium: 0.** Low: **2** (R10.12-1 `saveKeyItem` не переведён на
  global-save; R10.12-5 дубль title/modules у parent-блоков), Info: **3** (R10.12-2/-3/-4).
  Для мержа не обязательны; R10.12-1 — точечный follow-up того же класса 422.
- Обновлены: `round10.12_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.12 report generated by Scanner on 2026-09-13*

---

# Round 10.14 Audit (самосознание и личность бота: F1–F8)

> Полный отчёт — `plans/reports/round10.14_scanner_audit.md`.
> HEAD `2edc65b` + рабочее дерево 10.14 (52 modified + 20 untracked по 8 фичам).
> pytest **5582 passed / 0 failed**; `node --check` OK; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
> `git diff --check` clean. Owner разрешил DDL/миграции (PG+SQLite) — не нарушение.

## Новые находки 10.14 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.14-1 | medium | `web/api/routes.py:1381-1386` vs `:1365-1378`; `web/app.js:2812-2823` | RBAC `edit_persona`: роль-редактор может `PUT /api/persona` global, но `GET` global → 403 (независимый probe подтверждён); global-экран «Личность» из UI недостижим. Спека F2 §5 объявляет GET «auth TMA». Частично переоткрывает H2 для global/editor-кейса |
| R10.14-2 | medium | `services/dream_worker.py:1442-1443` | LLM-вызов `_run_persona_traits_once` идёт напрямую через `_worker_llm`, без `_deep_budget_ok`/`worker_budget.consume` → токены traits вне суточного капа и ledger (спека F2 §3.4 п.5) |
| R10.14-3 | low | `web/api/routes.py:1439-1440` | GET `/api/persona` отдаёт `persona_enabled` глобальным `hot.get` (per-chat override не виден UI-индикатору; рантайм резолвит корректно) — residual @Reviewer |
| R10.14-4 | low | `web/api/routes.py:1441-1442`; `web/app.js:5153-5158` | `dynamic_traits` не фильтруются по `chat_id` — лента chat-scope показывает глобальный пул (по спеке F4 traits глобальны — UX-несогласованность) |
| R10.14-5 | low | `services/summary_memory.py:1771-1777` | Ветка `bot_self_reply` в `_memorize_facts_inner` недостижима (self идёт через `memorize_self_reply`) — мёртвый код |
| R10.14-6 | low | `tests/test_graphrag_database.py:394`; `tests/test_database.py:789`; `tests/test_history_migration_v7.py:5` | Устаревшие docstring «user_version=8» при фактическом 9 (ревьюер закрыл только один файл) |
| R10.14-7 | low | pytest warning | `closed 12 leaked aiosqlite connection(s)` сохраняется (pre-existing, L7) |
| I10.14-1 | info | `services/database.py:917-995` | Прямой v7→v9-каскад не покрыт фикстурой (v8→v9 и from-scratch покрыты); safe по guard-анализу |
| I10.14-2 | info | `services/bot_persona.py:504` | FIFO-ротация трейтов глобальная, не per-chat (соответствует модели «общий характер бота») |

**Верифицировано чисто:** SQLite **v9** (16 колонок 1:1, id сохранены → FTS/vec валидны, 5 индексов,
идемпотентность/двойной прогон/from-scratch, откат документирован); PG DDL `personas`/`persona_traits`/
`persona_state` идемпотентен, partial-unique + FK CASCADE + UPSERT соответствуют; H1 optimistic-409 сквозной
(реальный GET→PUT stale→409→fresh→200); H3 per-chat резолв `persona_enabled`/`self_awareness`/`weight_bot`
через `get_chat_param`; origin-фильтры self в Сне/золотых/dup/live/graph_stats; анти-эхо до cap; R17 без
утечек; XSS — все `v-html` через DOMPurify (fail-closed); SQL параметризован; каталог **435/406/411/90/88/19**,
`inventory.tsv` 411 строк с `content.intelligence_guide`; флаги ON; `TABS=19` и DI-порядок `bot.py` не тронуты.

## Повторный аудит 10.14 (итерация 2, 2026-09-13)
- **R10.14-1 → CLOSED** (`routes.py:1365-1372,1388-1399`; `app.js:2820-2825`; тесты `test_persona_api.py:197-222`, `routing_test.js:190-195`).
- **R10.14-2 → CLOSED** (`dream_worker.py:1460` budget-гейт до traits-LLM, `:1355-1368` кап `deep_traits`, `:1406-1415,1475-1479` логирование; тесты `test_dream_persona_traits.py:182-238`).
- Low: R10.14-3/-5/-6 закрыты; R10.14-4 (traits без chat_id — осознанно) и R10.14-7 (aiosqlite leak) остаются.
- Валидатор итерации 2: pytest **5589 passed** / 0 fail, `node --check` OK, `routing_test.js` JS-UNIT-OK, `git diff --check` OK.

## Итог 10.14
- **Critical: 0. High: 0. Medium: 0** (R10.14-1/-2 закрыты итерацией 2), **Low: 2** (R10.14-4/-7), **Info: 2**.
- **Контракт: открытых Critical/High — НЕТ.** (итерация 1: Medium 2 → итерация 2: 0)
- Обновлены аддитивно: `round10.14_scanner_audit.md` (§6), `audit_backlog.md`, `global_map.md` (без новых связей).

*Round 10.14 report generated by Scanner on 2026-09-13*

## Round 10.15 scan (2026-09-14) — diff-аудит 9 фич F1–F9 (HEAD 798e044 + worktree)

Полный отчёт: `plans/reports/round10.15_scanner_audit.md`.

| ID | Sev | File:line | Кратко |
|---|---|---|---|
| R10.15-1 | Medium | `command_prefix.py:51-58`; `handlers/youtube.py:186`; `handlers/web.py:82`; `info_text.md` §3/§4 | link-first пример гайда (`https://… Олег, поясни за видос`) не матчит fast-track (префикс якорён к `^`); до 10.15 substring-путь работал |
| R10.15-2 | Medium | `services/tool_router.py:578-596` | `get_bot_health` обходит `flags.checkup_enabled` (сетевой fetch+LLM при выключенном модуле); ср. `_download_media:549` |
| R10.15-3 | Medium | `handlers/youtube.py:1030-1040`; `handlers/web.py:125-137`; `command_registry.has_trigger_word` | триггер anywhere + безусловный консьюм без цели «съедает» обычные сообщения с словом-триггером |
| R10.15-4 | Low | `handlers/direct_chat.py:461-463`; `bot.py:739-748` | yield по hot-флагу при startup-регистрации download-роутера → возможная потеря при рантайм-включении флага |
| R10.15-5 | Low | `web/api/memory_agi.py:495-499` | `deep.active_until=null` при `dream_enabled=false`+`deep_enabled=true`+в окне |
| R10.15-6 | Low | `services/tool_router.py:612` | F9 `ctx.query` fallback из спеки §5 не реализован |
| R10.15-7 | Low | `services/command_prefix.py:85-87`; `command_registry.py:62-64` | мёртвый `is_functional_command`/`matches` (только тесты) |
| R10.15-8 | Low | `services/database.py:3651-3665` | seed-CTE может включать невидимые узлы (пустой entity_name), вытесняя валидные сиды |
| R10.15-9 | Low | `services/tool_router.py:539-572` | tool `download_media` не применяет download-кулдаун 4e |

**Верифицировано чисто:** F1 SQL параметризован и без коррелированного COUNT; F3 fallback 2/8 + `[Sleep]`
WARNING виден и не спамит (early-return при пустых rows); F4 PREV-слепок байт-в-байт, капы лора/мемов,
лор/мемы только в LLM-промпт (не HTML/XSS); F5 API аддитивен, `enabled` приоритетнее `active`, релокация без
дубля; F6 word-boundaries («загуглика»/«транскриптер» не матчатся), реестр 17+2, `is_direct_trigger` off-дефолты;
F7 миграция идемпотентна и не затирает ручные правки, `DEFAULT_INFO_TEXT==info_text.md`; F8 success только после
отправки, 7 схем валидны, лимиты tool-loop не тронуты; F9 chat-скоуп и R17. R17/R16, порядок роутеров `bot.py`,
каталог 435/406/411/90/88/19, `media/`/`.env`, `PROMPT_MIGRATIONS` — целы.

## Итог 10.15 (итерация 1)
- **Critical: 0. High: 0. Medium: 3. Low: 6. Info: 3.**
- **Контракт: открытых Critical/High — НЕТ.**
- Валидатор: pytest **5761 passed**/0 fail, `node --check web/app.js` clean, `routing_test.js` JS-UNIT-OK.

## Повторный аудит 10.15 (итерация 2, 2026-09-14) — верификация фиксов @Builder
- **R10.15-1 → CLOSED** (`command_prefix.split_prefix_anywhere():61-77`; `youtube.py:206-215`;
  `web.py:97-106`; тесты `test_command_registry_round1015.py:153-161,225-242`) — link-first воспроизведён.
- **R10.15-2 → CLOSED** (`tool_router.py:623` гейт `flags.checkup_enabled`; тест
  `test_tool_calling_round1015.py:438-455`).
- **R10.15-3 → CLOSED** (`youtube.py:200-205`, `web.py:91-96` — обычная речь без URL → `UNHANDLED`;
  тесты `:249-279`); residual R10.15-11.
- Low закрыты: R10.15-5 (`memory_agi.py:497-501`), R10.15-6 (`tool_router.py:657-661`), R10.15-7
  (мёртвый API удалён), R10.15-8 (`database.py:3651-3652`), R10.15-9 (`tool_router.py:576-591`).
- Остаются: **R10.15-4** (open, follow-up), **R10.15-10** (link-first по первому вхождению имени),
  **R10.15-11** (любой http-URL как цель консьюма) — Low.
- Валидатор итерации 2: pytest **5774 passed**/0 fail, `node --check` clean, `routing_test.js` JS-UNIT-OK,
  `git diff --check` OK. Инварианты: R17/R16, роутеры `bot.py`, `media/`/`.env`, каталог 435/406/411/90/88/19,
  tool-set 7, PREV байт-идентичен, `PROMPT_MIGRATIONS` — целы.

## Итог 10.15 (итерация 2)
- **Critical: 0. High: 0. Medium: 0** (R10.15-1/-2/-3 закрыты), **Low: 3** (R10.15-4 open + R10.15-10/-11), **Info: 3**.
- **Контракт: открытых Critical/High/Medium — НЕТ.** Остаточные Low шаг 7 не блокируют.

*Round 10.15 report generated by @Scanner on 2026-09-14 (iteration 2)*

## Round 10.17 scan (2026-09-14) — diff-аудит 5 фич F1–F5 (HEAD 772f192 + worktree)

Полный отчёт: `plans/reports/round10.17_scanner_audit.md`.

| ID | Sev | File:line | Кратко |
|---|---|---|---|
| S10.17-1 | Medium | `plans/archive/security-rotation-finalize-round1016/spec.md:3,72,79-83` | архивная спека F4-отменяемой фичи без CANCELLED-баннера; §8 «ротация обязательна в любом случае» |
| S10.17-2 | Low | `web/app.js:1216-1247,1234-1256` | при `cognition==null` бейджи «Сон через —» вместо «—» (spec §3.4 :86) |
| S10.17-3 | Low | `tool-download-quality/spec.md:245`; `sleep-badge-countdown/spec.md:125` | счётчики pytest 5951/5985 устарели (факт и tasks.md — 6007) |
| S10.17-4 | Info | `services/tool_router.py:675-686,722-742` | tool-путь не вызывает `log_download_env_once()` (Fast-Track — вызывает) |
| S10.17-5 | Info | `handlers/video_download.py:619-685` | callback `tdq:` не проверяет hot-флаг `flags.download_enabled` |
| S10.17-6 | Info | `web/app.py:256-268`; `tool_router.py:338,378,381` | unauth `/healthz` отдаёт APP_VERSION (принято спекой); pre-existing `query=%r`-логи |

**Верифицировано чисто:** F2 полный флоу probe→`tdq:`→`needs_quality`→callback (валидация высоты до consume,
busy без потери pending, TTL 600, единый меню-хелпер `media_send.py`, no URL в логах, лимиты 4/2 и tool-set 7);
F1 HEAD `/web/`,`/index.html`,`/healthz` (raw-ASGI: 200, тело пустое, CSP/no-store, content-type == GET),
startup host-only, no-CDN включая 6 vendor; F3 `fmtCountdown` (границы/NaN/кламп, эмодзи, «выключен» удалён,
оконная семантика 10.15 не сдвинута — backend `active = enabled and in_window or running`); F4 README/ARCHITECTURE/
backlog/tasks CANCELLED; F5 все 6 сайтов avatars.py с политикой транзиент/ожидаемое/неожидаемое и brotli-WONTFIX.
R17/R16, порядок роутеров `bot.py`, `media/`/`.env`, каталог 435/406/411/90/88/19, SQLite v9, PREV/`PROMPT_MIGRATIONS` — целы.

## Итог 10.17
- **Critical: 0. High: 0. Medium: 1. Low: 2. Info: 3.**
- **Контракт: открытых Critical/High — НЕТ.** Medium S10.17-1 — docs-only (архив), шаг 7 не блокирует.
- Валидатор: pytest **6007 passed / 0 failed**; `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`;
  `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0.

*Round 10.17 report generated by @Scanner on 2026-09-14*

## Round 10.18 scan (2026-09-15, БАТЧ 1/3: F7 settings-worker-sync + F1 betterstack-us-region-401, HEAD 118a03c + worktree)

Полный отчёт: `plans/reports/round10.18_scanner_audit.md`.

| ID | Sev | File:line | Кратко |
|---|---|---|---|
| S10.18-1 | **High** | `services/dream_worker.py:598-600,617-639,741-758`; `services/database.py:1976,1985` | per-chat лимиты Сна (`distillations/tokens_per_day`) сравниваются с ГЛОБАЛЬНЫМИ счётчиками (DB-методы не принимают `chat_id`) → per-chat override глушится чужим расходом или делит общий бюджет |
| S10.18-2 | Medium | `services/dream_worker.py:1196-1203` | `memory.deep_sleep_trigger`/`deep_sleep_hour` в `_deep_tick` — только глобально; per-chat `trigger='fixed'` неисполним, `'after_sleep'` при global fixed игнорируется (`_run_deep_once` триггер не проверяет) |
| S10.18-3 | Medium | `web/api/gates.py:68`; `services/feature_gates.py:190-201`; `services/oversight.py:172`; `web/api/memory_agi.py:452-459` | воркер использует `gates_enabled(..., fallback=master)`, а UI «Гейты/Тяжёлые фичи» — без fallback → per-chat ON / global OFF: воркер работает, UI показывает OFF; `cognition_status.enabled` не учитывает kill-switch |
| S10.18-4 | Medium | `services/dream_worker.py:307-345,430-434,966-985` | тик всегда зарегистрирован → `_maybe_decay` теперь исполняется при `dream_enabled=false` (гейт только `flags.belief_decay_enabled`) → beliefs могут архивироваться без включённого Сна |
| S10.18-5 | Medium | `services/dream_worker.py:378-382,413-417,1148-1187,1214-1254` | `run_once(deep=False)` уходит в deep-каскад по ВСЕМ `_last_chat_ids` (до 10 LLM-прогонов), игнорируя `deep_sleep_enabled`/trigger; `manual=True` не делает `break` (задел F2/ADR-1018-2 D4) |
| S10.18-6 | Medium | `bot.py:141-198`; `spec.md:33,141-148` | fail-safe «нет `BETTERSTACK_HOST` → нет хендлера» даёт WARNING (не ERROR); прод-`.env` без переменной → логи в панель исчезнут до шага @DevOps, явного алерта нет |
| S10.18-7 | Low | `services/chat_params_notify.py:125-135`; `bot.py:1005-1010,824-830` | `ChatParamsNotify.stop()` — мёртвый код: bot.py отменяет task напрямую (в отличие от конвенции `LoreNotify.stop()`); метод не покрыт тестами |
| S10.18-8 | Low | `bot.py:565-566`; `plans/ARCHITECTURE.md:161,211,223`; `README.md:676,1044-1045` | stale-документация: «джоб только при флаге»; EU-дефолт host, алиас `BETTERSTACK_SOURCE_TOKEN`, функции `looks_like_sentry_public_key`/`betterstack_source_env_name` (в коде отсутствуют) |
| S10.18-9 | Low | `plans/features/betterstack-us-region-401/spec.md:7,153-155`; `tasks.md:70`; `scripts/betterstack_host_token_probe.py:33-40` | спека §9 Q4 рекомендует оставить `logtail-python`, таск T-1706 — удаление (удалено); docstring `mask(keep=0)` неточен |
| S10.18-10 | Low | `tests/test_settings_worker_sync_round1018.py:412-432` | `importlib.reload(config.settings)` + re-import `bot` остаётся в `sys.modules` на весь прогон (хрупкая изоляция при `pytest-randomly`) |
| S10.18-11 | Low | `services/chat_params_notify.py:139-158` | `_on_notify` создаёт неотслеживаемые `create_task` (shutdown/всплеск NOTIFY) |
| S10.18-12 | Info | `services/nostalgia_worker.py:131,148-155` | остаточный РАЗРЫВ spec §2.3: `NostalgiaWorker` — global-only, backlog T-1764 |
| S10.18-13 | Info | `plans/archive/security-rotation-finalize-round1016/spec.md:35` | pre-existing фрагмент SSH-пароля в отслеживаемом файле (R10.18-12; значение не копируется) |
| S10.18-14 | Info | инварианты | `logtail`-импортов нет; DDL нет (SQLite v9); каталог 436/406/411/90/88/19; роутеры/`media`/каноны не тронуты; R16/R17 и fail-open целы |

**Верифицировано чисто:** accessor `worker_settings` (сентинел проходит `_coerce`; приоритет chat→global→default;
каст == `_resolve_from_root`); kill-switch побеждает `fallback` (R10.18-3); `gates_enabled` без `fallback` для
прочих вызовов байт-в-байт прежний; `start()` идемпотентен, `_run_lock` не даёт двойного запуска; LISTEN на
отдельном `asyncpg.connect` + backoff + закрытие conn (Critical R10.18-1 закрыт); статус-API аддитивен (R16);
BetterStack ctor/`ValueError`/`extract_sentry_public_key`/`hmac.compare_digest`/R17-маркер `last4`; `logtail-python`
удалён без остаточных импортов; probe-тесты без сети.

## Итог 10.18 (БАТЧ 1)
- **Critical: 0. High: 1. Medium: 5. Low: 5. Info: 3.**
- **Контракт: открытый High (S10.18-1) — переход к БАТЧУ 2 блокируется** (нужен фикс per-chat учёта бюджетов либо
  явная фиксация «бюджеты глобальные» и снятие per-chat резолва + запись в ADR/spec).
- Валидатор: pytest **6042 passed / 1 failed** (pre-existing `test_tool_download_quality_round1017::TestSchemaAndAdr`);
  каталог-интроспекция 436/406/411/90/88/19.

*Round 10.18 (batch 1) report generated by @Scanner on 2026-09-15*

## Round 10.18 (БАТЧ 1) — итерация 2 (повторный аудит после фиксов @Builder, 15.09.2026)

Полный отчёт: `plans/reports/round10.18_scanner_audit.md` §7.

**Закрыто (CLOSED):** S10.18-1 (per-chat `chat_id` в `count_dream_log`/`sum_dream_log_tokens` + per-chat расход
в `_process_chat`; регресс-тест «чат A с override 50 не глушится расходом чата B»), S10.18-2 (per-chat
`trigger`/`hour` в `_deep_tick` через `_deep_candidate_chat_ids`), S10.18-3 (`feature_gates.master_fallback`
во всех статус-поверхностях + аддитивный `dream.effective`), S10.18-4 (decay за глобальным `_dream_master_on()`),
S10.18-5 (`only_chat` + `_MANUAL_DEEP_CASCADE_MAX=1`), S10.18-6 (ERROR при отсутствии `BETTERSTACK_HOST`),
S10.18-7 (`stop()` в `on_shutdown` + жизненный цикл), S10.18-8/-9 (README/ARCHITECTURE/bot.py-комментарий, спека),
S10.18-11 (`_pending` — сильные ссылки + отмена в `stop()`).

**Открыто:** S10.18-15 [medium] `services/feature_gates.py:55-72` — `master_fallback` default
`DEFAULT_BY_FEATURE["dream"]=False` ≠ `settings.DREAM_ENABLED`; при env `DREAM_ENABLED=true` и отсутствии
DB-ключа `memory.dream_enabled` воркер ON, статус OFF (воспроизведено скриптом); S10.18-16 [low] мёртвые
sync-хелперы `_window_open`/`_daily_limit`/`_budget_reason`; S10.18-17 [low] `_deep_tick` выполняет SQL-выборку
каждый тик; S10.18-12 [info] nostalgia-РАЗРЫВ (backlog T-1764); S10.18-13 [info] pre-existing фрагмент SSH-пароля
в отслеживаемом архивном `spec.md:35` (R10.18-12); S10.18-18…-20 [info] (`?deep=1` без капа; `tokens_per_day` без
фильтра `kind`; `previous` kill-switch = effective). S10.18-10 закрыт: reload `config.settings` в тесте
восстанавливается в `finally`.

## Round 10.18 (БАТЧ 1) — итерация 3 (fix @Builder по §7.2, 15.09.2026)

**Закрыто (fix @Builder):** S10.18-15 (`feature_gates._master_fallback_default("dream")=settings.DREAM_ENABLED` —
единый env-дефолт с воркером `_key_for(..., settings.DREAM_ENABLED)`; тесты `TestDreamGateFallback::
test_master_fallback_default_matches_worker_env_on/_off`), S10.18-16 (удалены мёртвые sync-хелперы
`_window_open`/`_daily_limit`/`_budget_reason`; `_key()` сохранён), S10.18-17 (`_deep_tick` предгейт
`_deep_fixed_possible()` — глобальный `memory.deep_sleep_trigger=='fixed'` ИЛИ per-chat override триггера в
`ChatParamsCache.has_any_override` (без I/O; ключи-стикеры `note_overrides` переживают инвалидацию/`set_chat_params`);
тесты `test_deep_sleep.py::test_deep_tick_skips_candidate_sql_when_disabled`
/ `test_deep_tick_proceeds_when_per_chat_override` + unit `test_chat_params.py::test_has_any_override_scans_loaded_cache_only`
/ `test_set_chat_params_notes_override_for_pregate`).

**Осталось (Info, осознанно):** S10.18-12 (Nostalgia/backlog T-1764), S10.18-13 (SSH-фрагмент, R10.18-12, вне
батча), S10.18-18…-20 (`?deep=1` без капа; `tokens_per_day` без фильтра `kind`; `previous` = effective).

- Валидатор итерации 3: pytest **6057 passed / 0 failed**; `node --check web/app.js` OK; `routing_test.js`
  `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19.

*Round 10.18 (batch 1) iteration 3 fix note generated by @Builder on 2026-09-15*

## Итог 10.18 (БАТЧ 1, итерация 2)
- **Critical: 0. High: 0.** Medium: 1 (S10.18-15). Low: 2. Info: 5.
- **ВЕРДИКТ: БАТЧ 2 (F2 Сон/каскад/бейджи) — РАЗРЕШЁН** (S10.18-1 закрыт; открытый Medium — узкая env-ветка,
  к F2 не относится).
- Валидатор: pytest **6052 passed / 0 failed**; `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`;
  `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19.

*Round 10.18 (batch 1) iteration 2 report generated by @Scanner on 2026-09-15*

## Round 10.18 — БАТЧ 2 (F2 sleep-manual-cascade-badges) scan (2026-09-15, HEAD 118a03c + worktree)

Полный отчёт: `plans/reports/round10.18_scanner_audit.md` §8.

**Закрыто в Батче 2:** S10.18-15 [medium] (`feature_gates._master_fallback_default` → `settings.DREAM_ENABLED`),
S10.18-16 [low] (мёртвые sync-хелперы `_window_open`/`_daily_limit`/`_budget_reason` удалены),
S10.18-17 [low] (`_deep_tick` предгейт `_deep_fixed_possible`).

| ID | Sev | File:line | Кратко |
|---|---|---|---|
| S10.18-21 | Medium | `services/dream_worker.py:1282-1333`; `services/chat_params.py:150-183` | предгейт `_deep_tick` видит только прогретый кэш → per-chat `trigger='fixed'` молча пропускается на cold-start/после NOTIFY (частичный откат R10.18-2; тесты — только warm-cache) |
| S10.18-22 | Medium | `web/app.js:5440-5463`; `setTab:2737-2741`; `closeModule:2371-2373` | `_restoreCognitionPolling` стартует базовые 15с без проверки `activeTab` (+`closeModule` не снимает) → после ручного POST polling (6 GET/тик) идёт вне «Статуса» бессрочно; обоснован лишь пока открыта модалка «Сон» |
| S10.18-23 | Low | `web/api/memory_agi.py:590-601` | `manual` выводится как `running && !in_window` → плановый тик вне окна (каждые 60 мин) транзиентно помечается «ручным», `active_until` растягивается на 900с |
| S10.18-24 | Low | `services/dream_worker.py:168-170`; `config/settings.py:1101-1107` | новые дефолты 2/8 равны F3-fallback-константам → fallback «0 убеждений за 3 дня» при дефолтах no-op (тесты пиннуют 3/12) |
| S10.18-25 | Low | `services/dream_worker.py:723-733` | `0` как per-chat лимит: `_budget_reason_for`=«без лимита», near-limit при `dist_max=0` триппает сразу → чат стоп с `budget_stop` (0 достижим из UI, min/max в каталоге нет) |
| S10.18-26 | Info | `web/app.js:5431-5436` | `_retryCognition` таймеры (1/3/8с) не сохраняются/не чистятся → лишние `loadCognition()` вне вкладки |
| S10.18-27 | Info | `services/dream_worker.py:1428-1441,1640-1695` | manual deep игнорирует cooldown, суточный token-cap и worker_budget-деградацию (принято ADR/UPD п.5; `?deep=1` без chat_id — без капа, batch-1 S10.18-18) |
| S10.18-28 | Info | `config/settings.py:1090,1137`; `tasks.md:154-156` | `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` остались `False` (spec §4.1 таблица — «True») → прод-симптом не включается кодом; T-1713/T-1724/T-1725 открыты |

**Верифицировано чисто:** manual обходит gate/budget/window/near-limit с аудитом (`gate_override`/`budget_override`),
но не трогает локи/`protected_facts`/≥2 `source_ids`/`persona_enabled`/R17; двойного списания бюджета нет
(SQLite-счётчики vs `worker_budget.consume`); каскад без рекурсии (`only_chat`/кап 1), `_deep_result` — единая форма
(KeyError исключён); миграция порогов идемпотентна/кастом не трогает/PG down → skip/порядок в `bot.py` верный;
S10.17-2 закрыт (`cognition==null` → «—»); reason-коды Личности полны и R17-safe; per-chat учёт бюджетов F7 сохранён.

## Итог 10.18 (БАТЧ 2)
- **Critical: 0. High: 0.** Medium: 2 (S10.18-21, S10.18-22). Low: 4. Info: 8.
- **ВЕРДИКТ: БАТЧ 3 (F3 граф + миграция v10) — РАЗРЕШЁН** (открытые Medium локализованы и F3 не затрагивают).
- Валидатор: pytest **6083 passed / 0 failed** (69.6 c); `node --check web/app.js` OK; `JS-UNIT-OK`;
  `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19 (Δ F2 = 0).

*Round 10.18 (batch 2) report generated by @Scanner on 2026-09-15*

## Round 10.18 — БАТЧ 3 (F3 graph-density-scoring-stoplist + F4 graph-physics-stabilization) scan (2026-09-15, HEAD 118a03c + worktree)

Полный отчёт: `plans/reports/round10.18_scanner_audit.md` §9.

**Закрыто в Батче 3 (остатки Батча 1/2):** S10.18-21 [medium] (предгейт `_deep_fixed_possible` +
`has_any_override` удалены — per-chat `fixed` больше не зависит от прогретости кэша), S10.18-22 [medium]
(`_restoreCognitionPolling` — 15с только на «Статусе»; `closeModule` вне вкладки гасит polling), S10.18-23 [low]
(маркеры `manual_run_active`/`manual_deep_active`), S10.18-24 [low] (`_FALLBACK_MIN_IMPORTANCE_SUM=6`), S10.18-25 [low]
(`0` = «без лимита»), S10.18-26 [info] (ретраи снимаются в `stopCognitionPolling`).

| ID | Sev | File:line | Кратко |
|---|---|---|---|
| S10.18-30 | Medium | `services/database.py:3796-3833` | перф: ×2-фаза (`re.search` по belief-блобу на каждый из ≤2000 узлов пула) доминирует — замер на синтет. графе 15k рёбер/20k фактов/200 beliefs: полный `graph_snapshot` ≈238 мс, SQL-часть ≈59 мс, ×2-цикл ≈176 мс; blob 25 КБ (1000 beliefs) → ≈680 мс, 100 КБ (4000) → ≈2.3 с, 254 КБ (10 000) → ≈6.5 с; цикл в event loop на каждый `GET /api/memory/graph` (15с / 5с при manual) |
| S10.18-29 | Low | `services/dream_worker.py:464-503`; `web/api/memory_agi.py:483-489,614-621` | `run_once(deep=False)` (manual-каскад) не выставляет `_manual_deep_until` → `deep_sleep.manual=False`, `active_until=None` во время deep-фазы каскада вне окна (незакрытая половина T-1719 для deep); TTL маркера 900с не связан с локами |
| S10.18-31 | Info | `services/graph_stoplist.py:26-39` | нормализация не ловит «видео-сообщение»/«голосовое сообщение»/морфологию (жёстко по ADR); ложных срабатываний нет |
| S10.18-32 | Info | `services/database.py:3788-3798` | self-loop (source==target) считается дважды в degree/score (pre-existing UNION ALL); возможен при subject==object от LLM |
| S10.18-33 | Info | `services/database.py:1683-1692`; `services/summary_memory.py:1838-1852` | `upsert_edge` INSERT…SELECT при отсутствии узла молча вставляет 0 строк → факт закоммичен без ребра (гарантия B3-5 покрывает исключения, не этот кейс) |
| S10.18-34 | Info | — | открытые Info Батча 1: S10.18-18 (`?deep=1` без капа), S10.18-19 (`tokens_per_day` без фильтра `kind`), S10.18-20 (`previous` = effective) |

**Верифицировано чисто:** миграция v10 — guard/идемпотентность/порядок в `initialize()`, индекс вне `_SCHEMA_SQL`,
`user_version=10` после индекса (частичный сбой самовосстанавливается), legacy-строки сохранены, FTS5/vec не тронуты,
обратный путь документирован; скоринг — корректный `LEFT JOIN f.id = e.fact_id`, NULL → COALESCE(weight),
дубли рёбер не удваивают importance, параметризация SQL сходится; STOP_LIST — только центры, границы/эмодзи/регистр;
×2 — `re.escape`, границы токенов (substring-тест), многословные имена, fail-open; атомарность fact+edge —
`commit=False` + единый commit + rollback, `commit=True` по умолчанию у всех прочих вызовов; F4 — 150 итераций,
`once` + guard по тождеству инстанса, `reducedMotion`, destroy-before-create, `truncated` в UI.

## Итог 10.18 (БАТЧ 3)
- **Critical: 0. High: 0.** Medium: 1 (S10.18-30). Low: 1 (S10.18-29). Info: 8.
- **ВЕРДИКТ: БАТЧ 4 (F5 экстрактор + F6 матрица ролей) — РАЗРЕШЁН** (открытый Medium — перф ×2-фазы,
  F5/F6 не блокирует; рекомендация закрыть в этом раунде).
- Валидатор: pytest **6104 passed / 0 failed** (75.4 c); `node --check web/app.js` OK; `JS-UNIT-OK`;
  `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19 (Δ Батча 3 = 0); SQLite v10.

*Round 10.18 (batch 3) report generated by @Scanner on 2026-09-15*

## Round 10.18 — БАТЧ 4 (F5 metafact-penalty-extractor-prompt + F6 role-matrix-settings-actualization) scan (2026-09-15)

Полный отчёт: `plans/reports/round10.18_scanner_audit.md` §10 (+ итоговая сводка эпика §10.4).

| ID | Sev | File:line | Кратко |
|---|---|---|---|
| S10.18-35 | Low | `services/database.py:1833-1836`; `services/memory_maintenance.py:250-258` | F5-срез покрывает только memorise-путь (subject/object передаёт 1 из 8 call-сайтов); эпи-мерж ре-вычисляет importance от origin (chat_history → 4) → слитый мета-факт теряет пенальти (imp 1→4, factor 0.55→0.70) |
| S10.18-36 | Info | `plans/features/role-matrix-settings-actualization/spec.md:37-45`; ADR-1018-6 D4 | spec §3.1 говорит «3 nav-родителя», фактически 4 группы (3 backend + «Прочее» для 5 content-параметров с `tab=None`); интроспекция: nav-распределение 161/180/65/5 = 411 |
| S10.18-37 | Info | `services/summary_memory.py:2349-2351,2410` | F5-множитель меняет RAG-порядок для всех чатов (weight×decay → ×importance 0.55–1.0) — не дефект, но поведенческое изменение на живых данных |
| S10.18-38 | Info | — | сквозная сводка открытых остатков эпика (S10.18-30 Medium, S10.18-29/-35 Low, Info S10.18-12/-13/-18/-19/-20/-31/-32/-33/-34/-36/-37) |

**Верифицировано чисто:** F5-срез централизован в `insert_graph_fact`, покрывает оба направления (subject/object),
перекрывает `rule_importance`/явный importance, нормализация строгая (ложных срабатываний на «сообщения» нет);
`PREV_FACT_EXTRACT_PROMPT` байт-в-байт == HEAD-канон (AST-проба 649 симв.), новый промпт = PREV + аддитивный блок,
`PROMPT_MIGRATIONS` не расширен, `EXTRACT_PROMPT`/retry-промпт не тронуты, canon-doc синхронен (байт-тест);
`_importance_factor` монотонный/ограниченный, None→нейтраль 0.75, применяется в FTS и KNN (взаимоисключающие → нет
двойного применения), `f.importance` реально в SELECT обоих запросов, MMR/touch/дедуп/resurrection согласованы,
golden-путь отдельным SQL-порогом; F6 `NAV_*`/`TAB_NAV`/`tab_nav` — метаданные (каталог Δ=0), 19 вкладок покрыты,
`CONFIG_TAB_TITLES[TAB_PERMSOC]`=«PERMsoc» + инвариант-тест с `web/app.js` TABS, API-поля аддитивны (403/форма прав
не изменены), JS-зеркало parity-тестом, `web/index.html` рендерит вложенность, `#/access`/`#/ai/persona` вне матрицы.

## Итог 10.18 (БАТЧ 4 и ЭПИК F1–F7)
- **Эпик: Critical 0. High 0.** Medium: 1 (S10.18-30, перф ×2-фазы, Батч 3). Low: 2 (S10.18-29, S10.18-35).
  Info: 11.
- **ВЕРДИКТ ЭПИКА: 0 Critical / 0 High → готов к @Reviewer/@PM (T-1749/T-1757) → Merge/архивация → деплой @DevOps.**
  До деплоя рекомендовано закрыть S10.18-30 (перф) и, по желанию, S10.18-29/-35.
- Валидатор эпика: pytest **6137 passed / 0 failed** (67.8 c); `node --check web/app.js` OK; `JS-UNIT-OK`;
  `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19; SQLite v10.

*Round 10.18 (batch 4 + epic summary) report generated by @Scanner on 2026-09-15*

## Round 10.20 (T-1915, Step 6 @Scanner) — diff-based аудит эпика `round1020`
- Отчёт: `plans/reports/round1020_scanner_audit.md`. Baseline HEAD `2f3e1f0` + рабочее дерево
  (91 изменённый + 8 новых файлов: `canonical_context.py`, `context_middleware.py`,
  `lore_compiler_service.py`, `reply_postprocess.py`, round1020-тесты).
- Сводка: **Critical 0 / High 1 / Medium 7 / Low 9 / Info 5. ВЕРДИКТ: есть Critical/High → возврат к @Builder.**
- **S10.20-1 [High]** `web/index.html:170-700` — в generic-ветке конфиг-вкладок удалены точечные
  кнопки «Сохранить» (hunks `-539/-565/-589/-645/-662/-677`), `<sticky-save>` добавлен только в
  модалку «Модулей» (:962), ветку «Доступы» (:1544) и модалку досье (:2689) → на конфиг-вкладках
  (Промпты/Память/Имена/Умный кэш/LLM Провайдеры basic/Реакции/chat_lore) правки textarea/input/JSON
  и ключей сохранить НЕЛЬЗЯ (авто-сейв остался у bool/select). @Reviewer пропустил: его тесты
  проверяют отсутствие точечных кнопок (`test_webapp_round1020_ui.py:184-189`) и наличие компонента
  (`tests/js/round1020_ui_test.js:393`).
- Medium (7): S10.20-2 per-chat флаг «Летописца» игнорируется роутером (глобальный `hot.get`),
  S10.20-3 `dig_into_lore` JSON ломается капом `dig_max_symbols` (`_truncate` по символам),
  S10.20-4 `_LORE_RETURN_INSTRUCTION` + HTML в фактчеке (verdict=story, сырые `<b>`),
  S10.20-5 UPD `last_ts` обгоняет включённый материал (окна/капы) → пропуск сообщений,
  S10.20-6 `saveModalEdits` «благословляет» неудачное сохранение (snapshot без reload),
  S10.20-7 статус «Бюджет контекста»: `acct.context_limit` затирает per-chat cap,
  S10.20-8 подтверждение reviewer M1/M2/M3 (`_trim` режет header, кап скана узлов, `RANDOM()` в фиде).
- Low (9): pattern `legacy_rag` не соответствует рантайму (6-кортежи), обрыв HTML-тега на границе
  чанка → дубль ответа, `<a href="javascript:">`, Time Injection ломает user-префиксный cache
  (принято ADR-1020-3), `initialize_existing` не проверяет путь/схему, `_date()` UTC vs TZ чата,
  общий `_EMPTY_DENSE`, докстринг fail-open у `dossier_feed`, запись досье доступна moderator'у.
- Валидатор: pytest **6523 passed / 0 failed** (89.52 s); `node --check web/app.js` OK;
  `routing_test.js`/`round1020_ui_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` exit 0.
- Подтверждено корректным: per-turn `ctx.lore_compiled` (нет протечки на обычный ответ), деградация
  tool-loop (NoApiKeyForChat/1-й раунд/пустой финал/лимит), `strip_reasoning_tags` (no-op без тегов),
  `truncate_keep_header`, миграция v11→v12 (guard+порядок+PG no-op), `lore_stories`/`persona_dossier_overrides`
  без бампа, 17/17 параметров `memorize_facts`, `key_status`-паритет, D206/R42/R46, SQL-параметризация,
  RBAC/XSS, R17, retention-снапшот, меню-freeze.

### Round 10.20 — Re-audit (после фиксов @Builder, 16.09.2026)
- Ре-верификация по коду: **S10.20-1 (High) CLOSED** — `<sticky-save>` в конце ветки
  `currentTabIsConfig` (`web/index.html:704`) + тесты проверяют панель в каждой ветке.
- **S10.20-2…-8/M1/M2/M3 и S10.20-9…-16 — CLOSED** (per-chat флаг, валидный JSON dig, без
  «верни дословно»/HTML в фактчеке, `last_ts` по включённым диалогам, sticky не «благословляет»
  ошибки, per-chat cap приоритетнее acct, header-safe `_trim`, кап скана узлов, пул `dossier_feed`,
  паттерны 6-кортежа, plain-доставка длинной истории, `initialize_existing`, tz `_date`, `_empty_dense`).
- **Принято обоснованно:** S10.20-12 (Time Injection/prompt-cache, ADR-1020-3), S10.20-17 (RBAC-паритет досье).
- Новые счётчики: **Critical 0 / High 0 / Medium 0 / Low 0 (open) / Info 5.** Новых находок нет.
- Валидатор: pytest **6546 passed / 0 failed** (87.49 s); `node --check web/app.js` OK;
  `routing_test.js`/`round1020_ui_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` exit 0. **ВЕРДИКТ: «нет Critical/High».**

## Round 10.21 (Step 6 @Scanner, 18.09.2026) — diff-based аудит `System 2 Reasoning & Memory Rebuild`

- Отчёт: `plans/reports/round1021_scanner_audit.md`. Baseline HEAD `21cd54c` + рабочее дерево (6 фич F1–F6;
  новые `grounding_validator.py`, `memory_rebuild.py`, `prompt_style_blocks.py`, `tools/ui_audit_round1021.py` и др.).
- Сводка: **Critical 0 / High 0 / Medium 2 / Low 7 / Info 4.** **ВЕРДИКТ: 0 Critical / 0 High → шаг 7 разрешён**
  (@Reviewer Approved iter 3; полный pytest 6775/0 заявлен @Reviewer, независимо проверены 213 целевых тестов).
- **S10.21-1 [Medium]** F4 `memory_maintenance.consolidate` (`:850-864`) пишет парадигму на каждого кандидата —
  кап `DEEP_SLEEP_MAX_PARADIGMS` (применяется только в `dream_worker.py:1578-1582`) не соблюдён, вопреки
  докстрингу `:735`.
- **S10.21-2 [Medium]** F5 `memory_rebuild._chat_roster` (`:275-285`) берёт «ростер участников» из
  `nodes(entity_type='user')`, а узлы создаются только триплетным путём (`summary_memory.py:3250-3267`) →
  неполный ростер → ложные «галлюцинации» и удаление валидных `chat_meme` (`:531-544`). Митигация: бэкап + JSONL + dry-run.
- Low (7): S10.21-3 (каскад orphan→belief `missing_sources`), S10.21-4 (grounding не режет дата-теги без `fact:ID`),
  S10.21-5 (якоря из `<claim>`/`<user_hint>` — обход grounding), S10.21-6 (`memory audit` не строго RO: `initialize()`/WAL),
  S10.21-7 (пустой `memes` Слоя Б перетирается `memes_a`), S10.21-8 (парадигмы CLI без vec-эмбеддинга),
  S10.21-9 (`tools/_ui_audit_shots/` ≈9.2 МБ не в `.gitignore`).
- Info (4): S10.21-10 (хардкод `ADMIN_ID` в инструменте), S10.21-11 (audit на «чужой» БД молча даёт нули),
  S10.21-12 (`_MONTH_RE` читает `MM.YYYY` из `DD.MM.YYYY`), S10.21-13 (класс-счётчик orphan до перезаписи).
- Подтверждено корректным: F5 — allowlist + `RAW_HISTORY_TABLES` (в т.ч. через `extra`), единственный путь DELETE,
  бэкап ДО DELETE, сверка `candidates==archived`, guard целевого чата (`--all`/`--allow-target-chat`); F4 — fail-closed
  без `db_path`, нет авто-кронов/HTTP; F1 — изоляция `dossier_portrait` от RAG/KNN/`get_persona_card` и приоритет
  ручных overrides; F3 — `PREV_*_R1021` в `PROMPT_MIGRATIONS` + `ROLLBACK_MIGRATIONS`, docs-канон синхронен; F2 —
  fail-open, `_BRACKET_RE` без ReDoS; F6 — реальный fallback-рендер, `_syntheticGroup` в `methods`, секретов нет.
- Валидатор: целевой pytest **213 passed**; `node tests/js/round1021_ui_audit_test.js` → `JS-UNIT-OK`;
  `node --check web/app.js` OK; `git diff --check` — только LF/CRLF; `py_compile` изменённых файлов OK.
- **RE-AUDIT (18.09.2026, после пост-скан фиксов @Builder):** S10.21-1/-2/-3/-4/-5/-6/-7/-9 **закрыты**;
  открыто 1 Low (S10.21-8, вне скоупа) + 2 новых Low (N10.21-1 тест-покрытие четырёх фиксов; N10.21-2
  бинарный характер гарда `roster_incomplete`) + 4 Info. Регрессии целы: user_version=12, каталог Δ=0,
  сырая история/ручные overrides не мутируются, JS-UNIT-OK. Валидатор: 217 целевых тестов + 7 ad-hoc проб.
  **Сводка re-audit: Critical 0 / High 0 / Medium 0 открыто → @Orchestrator, шаг 7 (Merge/deploy).
  Детали — `round1021_scanner_audit.md` §«Re-audit после пост-скан фиксов».**

---

## Round 10.22 (UPD3, 19.09.2026) — diff-based аудит 8 фич (System-2 two-call + egress-guard + async rebuild досье)

- Baseline HEAD `acd9311` + рабочее дерево; @Reviewer `Approved` (iter 3), полный pytest 6953/0 (заявлен).
- Новые модули: `services/system2_handoff.py`, `services/negative_constraints.py`, `services/outgoing_guard.py`,
  `services/telegram_send.py`, `services/dossier_rebuild_jobs.py`; изменены `memory_rebuild.py`, `lore_worker.py`,
  `direct_chat_service.py`, `summary_generator.py`, `factcheck_service.py`, `info_service.py`, `manage.py`,
  `web/api/chat_lore.py`, `web/api/routes.py`, `web/app.js`, `web/index.html`.
- Сводка: **Critical 0 / High 0 / Medium 2 / Low 4 / Info 3.** **ВЕРДИКТ: 0 Critical / 0 High → шаг 7 разрешён.**
- **S10.22-1 [Medium]** F1 `memory_rebuild._belief_source_set` (`:775-812`, `except → return out`) — ошибка чтения
  beliefs молча обнуляет `protected_ids`; внешний обработчик не срабатывает → `confirmed`-факты-опоры beliefs
  удаляются (fail-open вместо fail-closed; прецедент-регресс S10.21-3). Проба: monkeypatch `_list_beliefs`→raise →
  возврат `set()` без throw.
- **S10.22-2 [Medium]** F8 `dossier_rebuild_jobs.run_dossier_rebuild` (`:694-710`) — job помечается `done` при
  `cleaned>0 && rebuilt==0`; инвариант F1 `rebuild_empty` не зеркалится, а `cancel` на `done` терминален (200) →
  откат из UI недостижим. Воспроизводимо при пустом окне (`rebuild_dossier_for_user` → `return 0`) после удаления
  confirmed-фактов. Тестов на ветку нет.
- Low (4): S10.22-3 (`handlers/voice_transcription.py:214` — ASR-транскрипт, модель-текст, мимо egress-guard под
  обоснованием «UX-фразы»), S10.22-4 (детектор `as_ai` ловит нейтральное «ведёт себя как искусственный интеллект»),
  S10.22-5 (`interrupted` в `_ACTIVE_STATUSES` + не prune → блокирует старт и копит job-store), S10.22-6 (F8 flag OFF
  → 404, но кнопка в UI не скрыта).
- Info (3): S10.22-7 (`.env.example` без новых env-флагов), S10.22-8 (raw-логирование ответа LLM в summary, R17,
  pre-existing), S10.22-9 (restore SQL строит column-list из JSON без allowlist — accepted defense-in-depth).
- Подтверждено корректным: F1 скоуп `kind='fact'/confirmed/непустой target_user`, keyset-пагинация без пропусков,
  JSONL-до-DELETE + сверка, guard-only DELETE, `RAW_HISTORY_TABLES`/overrides/beliefs/nodes/edges не мутируются,
  target-chat guard (`--all` исключает, `--target-chat`/`--allow-target-chat`); F6 — regex без ReDoS, fail-closed,
  validator-loop ≤2 ретраев, покрытие direct/factcheck/search/youtube/web/checkup через `_send_once`+summary обёртки;
  F3–F5 — изоляция Stage-2 (только валидированный JSON), fallback не теряет ответ; F2 — KV-объект, другие виджеты не тронуты;
  F7 — v3→v4 идемпотентно, байт-тест `info_text.md`, h3+ отсутствуют; F8 — единственный путь DELETE (guard), снапшот
  ДО cleanup, rollback идемпотентен, RBAC `_require_chat`, R17 job-view.
- Валидатор: целевой pytest **229 passed** (11 файлов раунда + prompt_migrations + param_catalog); JS-гейты
  `ALIASES-UNIT-OK`/`DOSSIER-REBUILD-UNIT-OK`/help OK + `node --check`; `git diff --check` clean; SQLite v12;
  справка байт-в-байт; схема `graph_facts` без BLOB. Секретов нет.
- Принятые остатки: R7 ADR-1022-1 (удаление валидных confirmed, компенсация бэкап+JSONL+снапшот); stale-lock TTL/
  рестарт; rollback snapshot missing; vec не восстанавливается; job-store single-writer in-process.
- **ИТОГ: Critical 0 / High 0 открыто → @Orchestrator, Шаг 7. Отчёт `round1022_scanner_audit.md`.**
- **Re-audit после пост-скан фиксов (итерация 2):** S10.22-1/-2 (Medium), S10.22-3/-4/-5/-6 (Low), S10.22-7/-8/-9
  (Info) — **все закрыты**. Доказательства: `memory_rebuild.py:787-814,841-847` + тест `test_belief_read_error_skips_chat_fail_closed`;
  `dossier_rebuild_jobs.py:720-732,41,295-312,526-541` + `chat_lore.py:975-994,1043-1044` + тесты/JS;
  `negative_constraints.py:50-59`; `.env.example:474-491`; `summary_generator.py:290-296`.
  Валидатор: целевой pytest **187+339+70+88 passed / 0 failed**; JS-гейты OK; каталог 439/92/20 (Δ=0, пин-тесты);
  v12; канон v4 байт-в-байт; `git diff --check` exit 0. Новая Info **S10.22-4b** (ложное `as_ai` при запятой:
  «Он, как искусственный интеллект, …») — не блокер. **ВЕРДИКТ: 0 Critical / 0 High / 0 Medium открыто →
  раунд 10.22 передаётся на Merge/деплой.**

## Round 10.25 hotfix `hotfix-media-tma-round1025` (медиа/транскрибация + cache-bust TMA) — 21.09.2026, Step 6 @Scanner

Diff `7c38f70..ee23e47` (коммиты `8b16c4a`, `ee23e47`). Отчёт: `plans/reports/round1025_hotfix_scanner_audit.md`.
**Итог: Critical 0 / High 0 / Medium 2 / Low 4 / Info 4.** Вердикт: к Шагу 7/9 — ДА.
Прогоны: pytest **7976 passed / 0 failed** (109.17 s, 1 pre-existing warning); JS **19/19**; новые тесты хотфикса **30 passed**; `git diff --check` exit 0.

**Medium:**
- [M10.25-2] `services/media_download.py:99-101` (+ новая ветка `:68-70`) — лог сырого `file_path`; абсолютный путь внутри корня содержит `<bot_id>:<token>`. Регресс R17, внесён хотфиксом; в проде маскируется `SecretMaskFilter`/`sanitize` (не блокер). Фикс: логировать `Path(file_path).name`.
- [M10.25-3] `handlers/youtube.py:164-197` vs `services/media_download.py:144` — «единый рубильник» ADR-1025-6 не единый: гейт размера читает `TELEGRAM_LOCAL`, диск-путь — `DOWNLOAD_ENABLED`; `status_service.local_api` расходится; `.env.example`/README без `TELEGRAM_LOCAL`. Риск отказа легитимных 20-50 МБ при `--local` мимо env.

**Low:**
- [L10.25-1] `tests/test_hotfix_round1025_media.py::TestLocalFilePathRound1025` — тесты абсолютного пути тавтологичны на win32 (новая POSIX-ветка не исполняется; старый код даёт тот же результат).
- [L10.25-2] `web/index.html:15,3616,3623` — cache-bust частичный: `telegram-init.js` починен, 3 vendor-скрипта без `?v=`.
- [L10.25-3] `handlers/youtube.py:1097-1121` — `_process_video_media` без пост-скачивающей проверки размера (предсуществующее; масштаб растёт с `--local`).
- [L10.25-4] `.gitignore:101` — бланкетный `*.zip` (сейчас zip не отслеживаются; риск для будущих легитимных архивов).

**Info:** I10.25-1 (паритет с образом подтверждён исходником `docker-entrypoint.sh`: `[ -n "$(printenv ...)" ]`); I10.25-2 (`_provider_host` — только hostname, `_safe_exc_text` безопасен); I10.25-3 (регрессий fetch/фраз нет, `{limit}` не утекает); I10.25-4 (README «Тестов: 5936» устарело — факт 7976).


## Round 10.25 F1 `ia-shell-navigation-round1025` (IA v2 + app-shell) — 21.09.2026, Step 6 @Scanner

Diff `65e39fb..b1c87b0` (`1ebbd7b`, `ff34115`, `b1c87b0`). Отчёт: `plans/reports/round1025_f1_scanner_audit.md`.
**Итог: Critical 0 / High 1 / Medium 2 / Low 4.** Вердикт: к Шагу 7 — нет (блокирует H-1).
Факт: pytest **7996 passed / 0 failed** (108.41 s, 1 warning); JS **21/21**; `git diff --check`=0; `node --check`=0;
Δ DDL=0; Δ каталога=0; F0/Epic-2 не тронуты; секретов/zip нет; `stash@{0}` цел.

**High:**
- [H10.25F1-1] `web/app.js:1355-1378` (`bottomNavItems`/`mobileMoreItems`) — bottom-nav считает роль «админской»
  по `canViewTab('modules') || canViewTab('llm_providers')`; для роли с правом только на «Память» (`chat_lore`),
  «Доступы» (`section.access`) или PERMsoc на <768 кнопка «Ещё» не рендерится → раздел недостижим из UI
  (в legacy-navbar пункт был). Воспроизведено прогоном computed: `access-only | nav: status,how,access | bottom: status,how`.
  Фикс: добавлять «Ещё», если в `navItems` есть любой `group !== 'public'`.

**Medium:**
- [M10.25F1-1] `web/app.js:3340-3349` (`_routeLabel`) — для `#/ai/persona` (нет в `TABS`) fallback отдаёт сырой hash;
  breadcrumb на экране «Личность» показывает `#/ai/persona`. Фикс: подпись special-screen.
- [M10.25F1-2] Kill-switch OFF откатывает только nav: help-layout (`index.html:3089`), mobile-редактор матрицы
  (`:1927`), ренейм «Сводка»→«Аналитика» (`:1353,2669`) остаются. По spec D5 это nav-only, но Off ≠ прежний UI буквально.

**Low:** L10.25F1-1 дубль `min-width` в `.bottom-nav-link` (`app.css:1352`); L10.25F1-2 `.more-sheet` `bottom:52px`
может наезжать на `.bottom-nav`; L10.25F1-3 `test_ia_shell_round1025.py` grep-only + matrix только global_admin
(H-1 не ловится); L10.25F1-4 baseline-фикстура post-change (см. `_provenance`); L10.25F1-5 пустые `.sidebar-sep`
без админ/локальных прав.


**Повторный аудит F1 после фикса `78e612a` (21.09.2026, Step 6 @Scanner):** **Critical 0 / High 0 → к Шагу 7 — ДА.**
- H-1 закрыт: `web/app.js:1355-1371` — «Ещё» строится от `navItems` по `group`; роли access-only / permsoc-only / chat_lore
  на <768 получают `bottom=[status,more]` с нужным пунктом. Поведенческий тест в `tests/js/round1025_ia_routing_test.js`
  на `b1c87b0` падал бы (`bottom=[status,how]`), на `78e612a` — `[status,more]` (проверено прогоном).
- M-1 закрыт: `_routeLabel` (`web/app.js:3339-3360`) — `#/ai/persona` → «Личность и стиль», `#/memory/rag` → «Память и RAG».
- M-2 закрыт: nav-scope OFF зафиксирован в ADR-1025-1 D5 + spec §6.4; «мёртвых» состояний нет.
- Low L-1 (дубль `min-width`) и L-5 (пустые `.sidebar-sep`) закрыты; L-2/L-3/L-4 — техдолг в `tasks.md`.
- Цифры: pytest **7996/0** (112.26 s); JS **21/21**; `node --check`=0; `git diff --check`=0; Playwright-матрица §71 **0 нарушений**.
- Инварианты: Δ DDL=0, Δ каталога=0, F0/Эпик 2 не тронуты, секретов нет, zip/env в индексе нет, `stash@{0}` цел.

## Round 10.25 P0 hotfix2 `fea2daa` (прод-инцидент) — 21.09.2026, Step 6 @Scanner

Полный отчёт: `plans/reports/round1025_hotfix2_scanner_audit.md`. Diff `78e612a..fea2daa`.

**Сводка: Critical 0 / High 0 / Medium 2 / Low 3 → к деплою — ДА.**
- P0-1 закрыт: `web/app.js:2142-2150` `stickyFieldFailed` вынесен computed→methods
  (тело не менялось); `web/index.html:851,970` снова вызывает его как функцию.
- P0-2 закрыт: `services/media_download.py:60-82` `normalize_api_file_path` —
  контейнерный `/var/lib/telegram-bot-api/<bot_id>:<token>/…` → host-корень;
  `read_host_file_bytes` подключён в `web/api/avatars.py:154` до прежнего fallback.
  Guard `_is_within_root` (resolve+is_relative_to) сохранён, `..`/symlink/чужой
  абсолют отсекаются → `bot.download`.
- [M-1] `services/media_download.py:153-155` — лог сырого `file_path` снова
  достижим (контейнерный путь в норме); в проде маскируется `SecretMaskFilter`,
  поэтому Medium; фикс — логировать `PurePosixPath(file_path).name`.
- [M-2] `web/api/avatars.py:157,199-201` — `exc_info=True` трейсбек при падении
  `download_file` может нести `<bot_id>:<token>`; фильтр маскирует только `msg`.
  Предсуществующий, фиксом не ухудшён.
- Цифры: pytest **8003 passed / 0 failed** (117.37 s); JS **21/21**;
  `git diff --check`=0; `git ls-files "*.zip"` пусто; `stash@{0}` цел (25 файлов/+971).
- Новые тесты (Python + JS) падали бы до фикса; L-1 — тавтологичный
  self-compare в JS-тесте; L-2 — `_config_stub()` при сбое импорта молча пуст.

## Round 10.25 hotfix3 `hotfix3-summary-stt-anticliche-round1025` — 21.09.2026, Step 6 @Scanner

Полный отчёт: `plans/reports/round1025_hotfix3_scanner_audit.md`. База HEAD `fe0f7bb`; изменения **в рабочем дереве (не закоммичены)**.
Скоуп: `system2_handoff.py`, `summary_generator.py`, `anticliche_worker.py`, `web/api/anticliche.py`, `llm_client.py`, `config/settings.py`,
`SmartModule/service.py`, `SmartModule/transcriber/audio_prep.py` (new), `web/app.js`, `web/index.html`, новые тесты.
`services/telegram_send.py`, `handlers/{youtube,voice_transcription}.py`, `negative_constraints.py` — не менялись (реюз).

**Сводка: Critical 0 / High 0 / Medium 2 / Low 4 / Info 1 → к деплою — ДА.**
Прогоны: pytest **8037 passed / 0 failed** (100.28 s, 1 сторонний Starlette-warning); JS **22/22**; `git diff --check`=0.

**Medium:**
- [M10.25H3-1] `SmartModule/service.py:105-128` — `_prepare_for_stt` (ffmpeg, `_COMPRESS_TIMEOUT_S=300` × до 3 попыток) вызывается **внутри** `async with self._semaphore` → один большой файл держит слот STT до ~15 мин. Фикс: подготовка вне семафора/в отдельном пуле.
- [M10.25H3-2] `config/settings.py:1087-1089`; `services/llm_client.py:133-135,879` — комментарий/ADR называют `LLM_FALLBACK_TIMEOUT_SECONDS` «бюджетом фоллбэк-цепочки», фактически это **per-attempt** таймаут одного POST (ретраи не менялись) → риск ложных таймаутов у медленного провайдера. Фикс: привести доки к реальности + наблюдать `llm_stats().timeout_share`.

**Low:**
- [L10.25H3-1] `SmartModule/transcriber/audio_prep.py::_chunk` — на успехе `outdir` (`stt_seg_*`) не удаляется; `cleanup()` (`:60-70`) удаляет только файлы (нет `rmtree`) → пустые temp-каталоги копятся.
- [L10.25H3-2] `SmartModule/service.py::_compress_target_mb` — берёт `min(limits)`, т.е. сжимает файл 20–25 МБ при доступном Groq (25 МБ) вопреки докстрингу «влезает во ВСЕ»; фикс — `max(limits)`.
- [L10.25H3-3] Нет теста baseline `SYSTEM2_SUMMARY_ENABLED=False` (ветка `_resolve_cover_prompt` → `""`/plain).
- [L10.25H3-4] `tests/js/round1025_hotfix3_cliche_report_test.js` — grep-based (без исполнения `saveCliche`).
**Info:** [I10.25H3-1] `_chunk` лексикографическая сортировка `part_*.ogg` (>999 частей — порядок сломается, нереалистично).

**Верифицировано чисто:** нет двойной отправки (rich XOR plain, `summary_generator.py:397-403`); reason-ветви `parse_summary_handoff_ex` корректны;
OFF-флаги (`SUMMARY_COVER_FALLBACK_ENABLED`, `STT_AUDIO_COMPRESS_ENABLED`) = baseline (тесты); ручные фразы не фильтруются, авто — фильтруются, `saved/dropped/count/total` честны,
канон 120 согласован; ffmpeg без `shell=True` (list-args), temp 0600/0700, traversal нет, вход ограничен 1000×120; R17 — только числа/коды/hostname;
Δ DDL=0; Δ каталога=0 (418, флаги `ClassVar`); `stash@{0}` цел; zip/секретов нет. `database is locked` по коду не оценивается — за @DevOps.

---

## Round 10.25 hotfix4 `hotfix4-cover-nav-shell-round1025` — 21.09.2026, Step 6 @Scanner

Полный отчёт: `plans/reports/round1025_hotfix4_scanner_audit.md`. Diff `5f624cd..HEAD` (HEAD `f458b8c`).
Область: `services/{summary_generator,summary_prompts,prompt_migrations}.py`, `plans/docs/canon/**`, `web/app.js`,
`web/static/{app.css,telegram-init.js}`, `web/index.html`, `tools/ui_round1025_matrix.py`, `config/settings.py`, новые тесты.

**Итог: Critical 0 / High 0 / Medium 1 / Low 5 → к деплою да.**
Прогоны: pytest **8065 passed / 0 failed** (106.91 s, 1 Starlette-warning); JS-тесты ок (в т.ч. hotfix4/ia_routing/shell_breakpoints/routing);
`tools/ui_round1025_matrix.py` **failures 0** (mobile bottomNav=True(4)); `git diff --check`=0; `node --check`=0.

**Medium:**
- [M10.25H4-1] `tests/js/round1025_hotfix4_shell_test.js:47-53` — локальная копия формулы offset (тавтология); регресс арифметики
  `telegram-init.js` может не поймать ни JS-unit, ни матрица (она выставляет CSS-переменную напрямую). Фикс: jsdom-стенд с реальным `applyInsets`.

**Low:**
- [L10.25H4-1] `telegram-init.js:54-56` — нет guard `stableH > 0`: при 0/отрицательном `viewportStableHeight` offset = `layoutH` → панель уезжает за экран.
- [L10.25H4-2] `app.css:1350-1352` — фолбэк на `100dvh` невалиден на старых WebKit (<15.4)/Chromium<108 при невыставленной переменной → `bottom: auto`.
- [L10.25H4-3] `summary_generator.py:149-150` — `has_heading` ловит подстроки `perm`/`title` → ложные срабатывания в логах.
- [L10.25H4-4] `index.html:5-7` — `viewport-fit=cover` не гейтится `IA_V2_ENABLED` (OFF на iOS без нижней safe-area-компенсации).
- [L10.25H4-5] `tests/test_hotfix4_...py` импортирует приватные хелперы hotfix3-тестов (хрупкая связность гейта).

**Верифицировано чисто:** `compose_cover_image_prompt` не изменён (порядок style→visual, капы 500/1000); `resolve_cover_style` — дефолт только при `None`/пробелах;
`PREV_SUMMARY_EDITOR_R1025_HOTFIX4` побайтово == прод-канон до правки (проверено по блобу `5f624cd`); R17 — логи без текста промпта (длины+маркеры),
секретов нет, CSP без inline/eval; навигация: status+how первыми у всех ролей, ≤4, «Ещё» только при скрытых, без дублей и недостижимых разделов; OFF-режим не задет.
Матрица проверена как детектор: с навязанным `.bottom-nav{bottom:0}` — **56 failures**, в baseline — 0.

**Инварианты:** Δ DDL=0, Δ каталога=0, `stash@{0}` цел, zip/секретов нет, `git diff --check`=0.

---

## Round 10.25 «F2: дизайн-токены §8 + Liquid Glass v2 + фон §10» — 21.09.2026, Step 6 @Scanner

**Дифф `f2328fb..HEAD`** (коммит `e895726`). Полный отчёт: `plans/reports/round1025_f2_scanner_audit.md`.
Область: `web/**` (app.css, index.html, app.js, telegram-init.js), `tools/ui_round1025_matrix.py`,
`tools/ui_audit_round1021.py`, `config/settings.py`, `README.md`, новые/обновлённые тесты.

**Сводка: Critical 0 / High 0 / Medium 3 / Low 4. Вердикт: к деплою — ДА.**
Цифры: pytest **8096 passed / 0 failed** (106.03 s); `tests/js/*` **24/24 OK**.
Δ DDL=0, Δ каталога=0, `stash@{0}` цел, zip/секретов нет, `git diff --check`=0.

**Medium:**
- [M10.25F2-1] `web/app.js:8011-8027` — `reconcileLiquidGlass` понижает `data-glass="a"`→`b` необратимо
  (апгрейд не предусмотрен), поэтому `_onResize` (`app.js:2082-2084`) после первого понижения мёртв;
  к тому же reconcile вызывается только в `mounted()` и на resize → `[data-glass="a"]` вкладки Сводка
  (`index.html:1375`, `activeTab==='oversight'`) на старте отсутствует в DOM и не проверяется вовсе.
  *Фикс:* хранить намерение (`glass-a`/`data-glass-intent`), переключать A↔B в обе стороны, вызывать после смены вкладки.
- [M10.25F2-2] `web/app.js:7998-8009` — `_liquidGlassSupported` оптимистичен на WebKit: `CSS.supports('backdrop-filter','url()')`
  парсится, но reference-backdrop-filter отбрасывается целиком (WebKit #68614) → на iOS-Telegram (WKWebView)
  `[data-glass="a"]`-панели могут потерять blur, `@supports`-фолбэк не сработает (регрессия против уровня B).
  *Фикс:* gate по Blink-UA / иной детект рендера, на не-Blink — B; проверить на устройстве.
- [M10.25F2-3] `web/app.css:916-924` + `index.html:1375/2713/2876` — цена `feTurbulence/feDisplacementMap`
  в backdrop-filter поверх анимированного градиента не измерена, а 240px-отсечка (см. M-1) на этих узлах не работает.
  *Фикс:* ограничить A одним узлом / ввести бюджет FPS в матрицу.

**Low:** L10.25F2-1 `app.css:701` — sticky-header alpha 0.96→0.85 без blur, контент просвечивает (против комментария :693-694);
L10.25F2-2 `tests/test_webapp_design_tokens_round1025.py:228` — `assert "240" in APP_JS` тавтологичен, min-ветка не покрыта;
L10.25F2-3 `tools/ui_round1025_matrix.py:_f2_failures` — точные `75s/105s` при диапазонном чеке 60–90/90–120;
L10.25F2-4 `README.md:5` — «Тестов: 5936» устарело (факт 8096).

**Верифицировано чисто:** F1 shell/safe-area/навигация, hotfix1–4, F0 save-слой, Эпик 2 не задеты; `IA_V2_ENABLED` OFF не тронут;
polling-пауза F8 цела (один `visibilitychange`, пауза фона до `return`); CSP/zero-build — только inline SVG, один `#lg-displace`,
без внешних ссылок/data-URI/WebGL, `feDisplacementMap` через backdrop (текст/кнопки не искажаются), `@supports`-фолбэки корректны;
blur не анимируется, hidden-пауза и reduced-motion гасят фон и преломление; SVG-дефы без layout shift; новых источников данных/R17-рисков нет;
inventory-тесты на множествах (потеря маркера/OD4-литералов ловится, vendor исключён), маркеры не ослаблены.


## Round 10.25 F3 `global-scope-selector-round1025` (`76a6c40`), Step 6 @Scanner (21.09.2026)

- **Diff `5dcc6bd..76a6c40`.** Отчёт: `plans/reports/round1025_f3_scanner_audit.md`.
- **Итог: Critical 0 / High 0 / Medium 1 / Low 4 / Info 3 — к деплою да.**
- Связи: `web/index.html` (`.scope-wrap`/`.scope-trigger`/`.scope-panel`, `.scope-tech`) → `web/app.js` (`scopeKind`, `configSourceLabel`/`configSourceTitle`/`configItemNotice`, `hasUnsavedEdits`) → `scopeEpoch`/`_scopeGuard` (`loadConfig`, `persistItems`) → `resetChatOverride` → `DELETE /api/config/chat/{key}` (`web/api/routes.py:852`) → `chat_params.set_chat_params` (merge overrides/meta). `web/static/app.css` §70 mobile. `config.settings.APP_VERSION=2.58.6`.
- M-F3-1 (`web/app.js:2472-2482` + `2538`): guard не покрывает `blockDrafts` (llm_providers) — вероятна тихая потеря черновика при смене scope.
- Инварианты: Δ DDL=0, Δ каталога=0 (459), `stash@{0}` цел, zip не в git, `git diff --check`=0. pytest 8142/5/1 (5 — env aiogram InputRichMessageMedia), JS SCOPE-SELECTOR-OK, matrix не воспроизведён (нет playwright).

---

## Round 10.25 ПАКЕТ F2+hotfix5+F3 — повторный аудит финальных коммитов — 22.09.2026, Step 6 @Scanner

**Диапазон `f2328fb..HEAD` (`3caddeb`).** Отчёт: `plans/reports/round1025_package_scanner_audit.md`.
Финалы: F2 `d2df8ca` (ревью `0f227a5`,`d2df8ca`), hotfix5 `412f844` (ревью `cbaec05`,`412f844`), F3 `4f31197` (ревью `fb49f29`,`4f31197`).
Пакет деплоится одним пакетом; базовые аудиты правки ревью не покрывали.

**Итог: Critical 0 / High 0 / Medium 1 / Low 5 / Info 4 → к деплою — ДА.**
Проверено по факту: `py -m pytest -q` → **8146 passed / 5 failed / 1 skipped** (5 — env `aiogram 3.29.1` без `InputRichMessageMedia`,
файлы вне пакета → не регрессия); целевые 5 файлов → **152 passed**; JS **25/25 OK**.
Δ DDL=0, Δ каталога=0, `stash@{0}` цел, zip/секретов нет, `git diff --check`=0.

**Статусы ранее найденных Medium:**
- [M10.25F2-1] `web/app.js:8122-8141` + `app.css:978-981` — **ЗАКРЫТ**: `reconcileLiquidGlass` не переписывает `data-glass`,
  ставит/снимает `data-glass-downgraded` (обратимо A↔B); транзитивность — watch `activeTab`→`$nextTick`, `MutationObserver` на `#app`,
  `ResizeObserver`, `_onResize`.
- [M10.25F2-2] `web/app.js:8004-8014` — **ЧАСТИЧНО**: UA-gate `AppleWebKit && !/Chrome|Chromium|Edg|OPR/` уводит общий WKWebView на B.
  Остаток (Low): iOS Edge UA `EdgiOS` содержит `Edg` → НЕ гейтится (воспроизведено regex-прогоном) — ниша, не блокер.
- [M10.25F2-3] `web/app.css:916-924` + `index.html:1420/2762/2930` — **ЧАСТИЧНО/ОТКРЫТ**: min-240 теперь реально проверяется
  (матрица + `TestMatrixF2Probe`), но цена `feTurbulence` не измерена и A по-прежнему на 3 узлах → остаточный **Medium**.
- [M10.25H5-1] `services/image_generation.py:897-901` — **ЗАКРЫТ**: внешний цикл владеет повторами (`retry=False` → `max_retries=0`),
  селективный `is_transient_reason`, дедлайн попытки `asyncio.wait_for` → worst-case = attempts×окно+backoff (362 c).
- [M-F3-1] `web/app.js:2481-2516` — **ЗАКРЫТ**: `hasUnsavedEdits` покрывает `blockDrafts`/`ownKeyDraft`/`personaDraft`/`dossierDraft`;
  guard вызывается до сброса (`:2521-2532`).

**Остаточные Low/Info:** L10.25F2-1 (`app.css:745-749` sticky-header alpha 0.85 без blur — открыт);
L10.25F2-2 (`tests/test_webapp_design_tokens_round1025.py:343` `assert "240" in APP_JS` — тавтологичен, поведенческое покрытие добавлено);
L10.25F2-4 (`README.md:5` «Тестов: 5936» — устарело, открыт); NEW-L1 (iOS Edge `EdgiOS`); NEW-L2 (`_initLiquidGlassObserver`
после стартового reconcile → стартовые allow-узлы не подписаны до следующего reconcile); I-3 (`_onResize` без троттлинга);
I-4 (downgraded-A сохраняет лишний inset box-shadow); I-1 (matrix «0» не воспроизведён — нет playwright); I-2 (5 env-падений).
Контраст D-1 пересчитан: `--text-3` 5.25:1, `--err-text` 6.07:1 (совпало). RBAC DELETE-override — паритет UI↔сервер (`routes.py:868-876`).
**Регрессий не обнаружено** (пакет не касается handlers/bot/database/media/F0/Эпик 2).

## Round 10.25 hotfix8 `hotfix8-shell-glass-aurora-round1025` (22.09.2026, Step 6 @Scanner, UPD2)

- **Найдено независимо** — аудит рабочего дерева относительно HEAD `a1e6db3` (`pre-round1025-hotfix8`); правки не закоммичены (bump 2.58.11 — Block G). Отчёт: `plans/reports/round1025_hotfix8_scanner_audit.md`; AA — `plans/reports/round1025_hotfix8_contrast.md`; UI — `plans/reports/round1025_hotfix8_ui_report.md`.
- **Вердикт: Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → к деплою (блокеров нет).** Обязательный live-гейт T-2776 (реальный Telegram WebView, FPS blob/safe-area) — по ADR, не новый блокер.
- **Новые зависимости/связи (подтверждены):**
  - `web/index.html` статичный `.aurora-bg` (5 `.aurora-blob` + `.aurora-grain`, `aria-hidden`, `z-index:0`) ↔ `web/static/app.css` (`body::before`/`body::after`/`.aurora-bg`, keyframes `aurora-flow`/`aurora-flow-rev`/`aurora-morph`/`aurora-blob-1..4`; `@media reduced-motion`; `prefers-contrast`) ↔ `web/app.js::_syncBgLayer` → `html.bg-wash-legacy` (legacy conic `body::before`).
  - Shell v3 §4: `data-glass="shell"` на sidebar/header/drawer/bottom-nav/more-sheet ↔ `app.css [data-glass="shell"]` (+ нейтральный `::after` sheen ≤.05, `#lg-lens`) ↔ `.app-shell.shell-v3`/`shell-v3-off` ↔ `web/app.js` computed `shellV3`/`auroraBgEnabled`.
  - `config/settings.py` env-only `ClassVar` `UI_SHELL_V3`/`UI_AURORA_BG_ENABLED` (default ON) → `web/api/routes.py` `/api/me.ui_flags` (bool) → `.env.example`. Δ каталога = 0.
- **Low:** L-H8S-1 перф-риск aurora (blur 64px + анимация `border-radius`/`background-position`, покрыт T-2776); L-H8S-2 mobile `.78` не ассертится матрицей, `None`-панель = pass; L-H8S-3 AA worst-case по одному blob (запас 7.33:1). **Info:** bump 2.58.11 в Block G; ослабление F2-чекера намеренно (есть `test_f2_checker_rejects_static_background`); `border-top:0` shorthand сбрасывает цвет рамки шапки (width 0).
- **Инварианты:** Δ DDL=0, Δ каталога=0 (459/98/96/21/418), CSP/zero-build (нет CDN/inline/WebGL/`backdrop-filter:url(`/новых библиотек), R17/R18 чисто (тег `pre-round1025-hotfix8`→`a1e6db3`, `.env.bak.round1025-hotfix8`, `stash@{0}` цел), `git diff --check`=0, `.env`/zip/PNG не в индексе. IA F1/F5 §61/F4 §37–§42/F0/F3, `computeBottomOffset`/hotfix4, fullscreen-sync ADR-1024-24, deny-list tier C, карточные `--glass-*` — не тронуты. pytest 78 passed (target) / JS-маркеры OK / matrix failures 0.

## Round 10.25 hotfix9 `hotfix9-shell-liquidglass-darkaurora-round1025` (22.09.2026, Step 6 @Scanner, UPD3) — NOT READY (High)

- **Границы:** дерево относительно HEAD `b374c0f` (`pre-round1025-hotfix9`), правки НЕ закоммичены. Отчёт: `plans/reports/round1025_hotfix9_scanner_audit.md`. Вход: `spec.md`/`adr-1025-17`/`evidence.md`.
- **Вердикт: Critical 0 / High 1 / Medium 0 / Low 3 / Info 2 — к деплою НЕ готово (H-H9S-1).**
- **[H-H9S-1] High (DOM/structure, блокирует):** `web/index.html:1919–1924` — пропущен `</div>`, закрывающий `.modal-body` модульной модалки (`v-if="activeModule"`, `:1678`). `footer.modal-actions` вложен ВНУТРЬ `.modal-body`; HTML-парсер фиксирует `IMPLICIT-CLOSE` `.modal-backdrop` на `</template>` (`:1930`). В HEAD `footer.modal-footer` был сиблингом `.modal-body` (ошибок нет) ⇒ регрессия. Impact: `.modal-actions > .sticky-save{position:static}` ⇒ SaveBar скроллится вместе с полями, нарушен D3/§6 (footer в экране). Не поймано: `H9_MODAL_PROBE_JS` прогоняется только для `#/access/roles`; тесты проверяют лишь соседство footer→sticky-save. Fix: вернуть `</div>` после `:1919`; расширить modal-probe на модульную модалку (`modalBody.bottom <= modalActions.y+1`).
- **[L-H9S-1] Low:** `aurora-flow.js:217–221` `stop()` не убирает `#aurora-flow-canvas` (застывший кадр при `UI_AURORA_FLOW_V2=OFF` после boot-`start()`); маскируется `.aurora-bg`, но при OFF+OFF перекроет legacy-wash.
- **[L-H9S-2] Low:** `UI_SHELL_V3` (settings:742, `/api/me`, `.env.example`) — «мёртвый»: `shellV3` (app.js:2450) не читается шаблоном (index.html:70 → `shellGraphiteV3`).
- **[L-H9S-3] Low:** `.status-block` (`index.html:3275`) несёт `data-glass="a"` (legacy `::before`+`url(#lg-lens)`) и одновременно цель `glass.js` — двойная обработка стекла.
- **Info:** I-H9S-1 текст лицензий MIT/Unlicense не поставлен (только README); I-H9S-2 `glass_prototype_probe.py` — локальный `127.0.0.1`, dev-only.
- **Инварианты:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418, флаги ∉ REGISTRY); `APP_VERSION` 2.58.12 синхронен; `--shell-texture`=0 в `web/**`; CSP (same-origin, без CDN/inline, `eval/new Function/document.write/insertAdjacentHTML/srcdoc`=0, внешние хосты=0); SHA-256 vendored совпадают с README (3/3); `backdrop-filter:url(`=0; нет root `package.json`, node_modules gitignored; R17 OK; R18 тег `pre-round1025-hotfix9`/`stash@{0}`; `git diff --check`=0; `node --check` OK; a11y тач ≥44 + AA `--text-2` на shell ≈7.28:1; IA F1/F4 §60/F5 §61/F0/F9/F3/`computeBottomOffset` — не тронуты.
- **Прогоны:** hotfix9 pytest 17/0; группа hotfix6/7/8+scope+tokens+ui_rework+js_unit 183/0; каталог 459/98/96/21/418.

## Round 10.25 hotfix9 `hotfix9-shell-liquidglass-darkaurora-round1025` — ПОВТОРНЫЙ аудит после фиксов (22.09.2026, Step 6 @Scanner, UPD3) — SCANNED

- **Границы:** дерево относительно HEAD `b374c0f` (`pre-round1025-hotfix9`), не закоммичено. Отчёт: `plans/reports/round1025_hotfix9_scanner_audit.md`.
- **Вердикт: Critical 0 / High 0 / Medium 0 / Low 0 / Info 3 — к деплою ГОТОВО.**
- **Закрыто:** H-H9S-1 (RESOLVED: `web/index.html:1920` восстановлен `</div>`; HTML-парсер — `footer.modal-actions` сиблинг `.modal-body` во всех 5 футерах, стек пуст, ошибок 0; парсер-тест red-on-regression; матрица модульной модалки `modalBody.bottom <= modalActions.y+1`, `stickyInActions=true`). M-H9R-1 (RESOLVED: `aurora-flow.js:101–122/153–167` — свежий canvas + реальный 2D-контекст при `webglcontextlost`; матрица `mode!=webgl`, `brightness>=3`). L-H9S-1 (RESOLVED: `stop()`→`detachCanvas()`). L-H9S-2 (RESOLVED: `shellGraphiteV3` AND `UI_SHELL_V3` — legacy-алиас). L-H9S-3 (RESOLVED: снят `data-glass="a"` у `.status-block`).
- **Info:** I-H9S-1 (текст лицензий vendored не поставлен — pre-existing); I-H9S-2 (`glass_prototype_probe.py` — локальный `127.0.0.1`, dev-only); I-H9S-3 (`scrollActiveModalField` на visualViewport resize/scroll — низкий риск джанка, наблюдать на live).
- **Инварианты:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418); `APP_VERSION` 2.58.12; CSP same-origin (0 внешних src/href, 0 инлайн, 0 eval); `--shell-texture`=0; `backdrop-filter:url(`=0; SHA-256 vendored 3/3; R17/R18 (тег+stash); `git diff --check`=0; маркер-тесты не ослаблены.
- **Прогоны @Scanner:** `node --check` OK; JS-тесты OK; `py -3 -m pytest -q` **8291 passed / 0 failed**.

## Round 10.25 hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (22.09.2026, Step 6 @Scanner, UPD4) — SCANNED

- **Границы:** дерево относительно HEAD `5184584` (`pre-round1025-hotfix10`), правки НЕ закоммичены. Отчёт: `plans/reports/round1025_hotfix10_scanner_audit.md`. Вход: `spec.md`/`adr-1025-18`/`evidence.md`/UI-отчёт.
- **Вердикт: Critical 0 / High 0 / Medium 0 / Low 1 / Info 2 — к деплою ГОТОВО (блокеров нет).** Live Telegram WebView — PENDING OWNER VERIFICATION.
- **Прод-дефект белых прямоугольников устранён:** `glass.js` `SELECTOR='[data-glass-surface]'` (TARGETS `.scope-trigger/.header-fs-btn/.status-block` удалён); флаг `UI_LIQUID_GLASS_LIB` default OFF; `mountGlass` на функциональные цели не вызывается; `--glass-paper` тёмный только на `.glass-surface` (`var(--surface-1)`); `backdrop-filter:url(`=0; vendored same-origin под CSP.
- **[L-H10-1] Low (OPEN):** `web/index.html:3271-3272` — статичный `.glass-surface` (`app.css height:44px`) остаётся в сетке «Статус» и при OFF (прод-default) → ~44 px + grid-gap пустого места (`mountedCount=0`, `surfaceCount=1`). Не блокирует. Fix: `.glass-surface:not([data-lg-mounted="1"]){display:none}` или `v-if`.
- **Info:** I-H10-1 OFF-проба матрицы не ассертит скрытие placeholder; I-H10-2 Playwright-матрица не перезапускалась @Scanner (опора на @Builder `failures:0`).
- **Инварианты:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418; `param_catalog.py` не тронут); `APP_VERSION` 2.58.13 синхронен; маркер-тесты атомарны; `--shell-texture`=0; R17/R18 (тег `pre-round1025-hotfix10`, `stash@{0}`); `git diff --check`=0; индекс без `.env`/zip/скриншотов.
- **Совместимость:** IA F1/роуты, F4 §60, F5 §61, F0, F9, F3, ADR-1024-24, flex-геометрия/графит §63, сердцебиение — не тронуты; второй вычет safe-area снят; `.more-sheet` один offset; Main без полосы (`--work-surface-bg`, лимит 1100 px); `__AuroraFlow.resize` экспортирован и вызывается (resize/fullscreen/visualViewport/RO); режим честный `frosted`; unmount идемпотентен.
- **Прогоны @Scanner:** `node --check` OK; JS `HOTFIX10-GLASS-GEOMETRY-BG-OK`; целевые pytest **166 passed**; полный `pytest -q` **8314 passed / 0 failed**.

## Round 10.25 hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` — ПОВТОРНЫЙ аудит после фиксов (22.09.2026, Step 6 @Scanner, UPD4) — SCANNED

- **Границы:** то же дерево относительно HEAD `5184584`, не закоммичено. Отчёт: `plans/reports/round1025_hotfix10_scanner_audit.md`.
- **Вердикт: Critical 0 / High 0 / Medium 0 / Low 0 / Info 1 — к деплою ГОТОВО (блокеров нет).** Live WebView — PENDING OWNER VERIFICATION.
- **Закрыто:** H-1 (@Reviewer High) — `app.css` `main.scroll-area{grid-auto-rows:max-content}`; матрица @Scanner `failures:0`, `.status-block` `scrollH==clientH` (320/360/390/430: 567/532/508/508) + fullscreen, `elementFromPoint` `.hb-canvas`/`__bot`/`__server` `self=true`, дизайн сердцебиения не тронут; гейт §5 не вакуумный. L-H10-1 (Low @Scanner) — `v-if="liquidGlassLib"`, OFF-проба `surfaceCount==0` (320/360/390/430/1280). L-1 — `clearAttrs` снимает `data-glass`/`data-uid`/`--g-*` (node-юнит). L-2 — `.env.example` актуализирован.
- **Инварианты:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418; `param_catalog.py` не тронут); `APP_VERSION` 2.58.13; CSP same-origin (0 внешних src/href); `--shell-texture`=0; `backdrop-filter:url(`=0; маркер-тесты не ослаблены (только version-бампы/токены/эквивалентный regex); R17/R18 (тег `pre-round1025-hotfix10`, `stash@{0}`); `git diff --check`=0.
- **Прогоны @Scanner:** `node --check` OK; JS `HOTFIX10-GLASS-GEOMETRY-BG-OK`; полный `pytest -q` **8319 passed / 0 failed**; матрица **failures: 0**.
