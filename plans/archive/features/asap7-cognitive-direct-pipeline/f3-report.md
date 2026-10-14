# F3 — Module registry + Initiative corrective (ASAP 7, Wave 1)

Дата: 2026-10-09. База: HEAD `08a8849`. Режим: writer, LEAF (без subagent'ов).
Статус: готово к независимому ревью. Коммитов нет.

## 1. Изменения (file:line)

**Канон реестра — `services/module_registry.py` (NEW)**
- `ModuleSpec` (поля ровно §4.4 ТЗ: id, title, parent_id, description,
  master_param, runtime_gate, settings_groups, model_slots, status_source,
  analytics_anchor, help_anchor, visibility, classification, rationale) — :36.
- Реестр: `MODULE_REGISTRY` + запись `initiative` (top-level, master
  `flags.initiative_enabled`) — :60–110.
- §3.3: `effective_gate(module_id) -> (requested, effective, source)` — :121
  (env-emergency OFF → `emergency_env`; product OFF → `product_toggle`; оба ON
  → `both`); `env_enabled` (raw-ось) :113; `gate_snapshot` :136;
  `registry_for_frontend()` (сериализация для фронта) :151.
- M2: `MODULE_ENV_GATES` (4 Intent-switch → module) :185;
  `INFRASTRUCTURE_RATIONALE` — 4 exact-группы (F4-orphan / registered-submodule
  / dossier+embeddings / infra-maintenance) :197. Полное покрытие 85
  KILL_SWITCHES без дублей (тест M2).

**Каталог — `services/param_catalog.py`**
- Группы: `flags_intent` :428 (order 27), `limits_intent` :341 (order 37).
- 9 ParamSpec `_INTENT` :2310 (4 тумблера + 5 лимитов); pg_id-ренейм
  (`flags.initiative_enabled`, `limits.intent_defer_backoff_seconds`, …);
  settings-атрибуты БЕЗ изменений (9 ClassVar MCA_INTENT_* = env-ось).
- Вкладка: `TAB_MOD_INITIATIVE` :2716, `CONFIG_TAB_TITLES` :2643,
  `TAB_NAV` :2692, `TAB_RULES` :2910 (flags_intent+limits_intent →
  mod_initiative).

**AND-гейт — `services/mca_gates.py`** (минимально; mca_intents.py НЕ правился —
все читатели идут через гейты)
- `_intent_catalog_flag` :1265 / `_intent_catalog_int` :1324 (hot_config,
  fail-open → default, clamp ≥min).
- `intents_enabled` :1274 = env `MCA_INTENTS_ENABLED` AND catalog
  `flags.initiative_enabled`; K2 :1286 / K3 :1298 / K4 :1311 — каждая ось
  независимо (env важнее UI); 5 лимитов — hot (без рестарта), clamp сохранён.
- Composite-семантика OFF не изменилась: OFF = бит-в-бит 2.58.59 (тесты
  off-parity зелёные).

**Статус — `services/status_service.py`**
- `intent_snapshot`: аддитивный блок `module` во ВСЕХ ветках — :748 gate
  (requested/effective/source/env_param/master_param), :766 heartbeat
  (job/tick_seconds/enabled/restart_required_env=true — честная restart-
  семантика: env-ось с рестартом, каталог — hot), :851 pending /
  last_decision (initiative_decided) / last_skip (recheck_deferred |
  intent_abandoned | intent_expired + reason) / next_due (MIN next_check_at
  активных). Существующие ключи контракта mca-12 не менялись.

**API-носитель — `web/api/routes.py`** (1 аддитивный ключ, см. §5)
- `GET /api/config`: ключ `modules` = `registry_for_frontend()` :589–596
  (fail-open → []). Новых эндпоинтов нет; routes-набор f8_baseline не рос.

**Фронт — `web/app.js`** (9 хунков, все с маркером «ASAP 7 F3»)
- Карточка :630 (`mod_initiative`, toggleKey `flags.initiative_enabled`,
  runtimeGate global), WORKSPACE_TABS :677 (`overview/settings/limits`),
  TABS-зеркало :206, TAB_SECTION_ORDER :301, TAB_ICON :370.
- `f3ApplyModuleRegistry` :6907 + вызов в loadConfig :12103 (merge реестра:
  enrich существующих карточек, добавление НОВЫХ id — F4-путь без правки
  каркаса; один раз на загрузку; fallback витрины сохранён).
- `intentModuleStatus` :6882 + `gateSourceLabel` :6874 (ленивый догруз
  /api/status по прецеденту oversightTabEnter; без нового поллера).
- Фикс P7-C-3: `storiesSettingsMeta` :6955 — 9 СОБСТВЕННЫХ Intent-ключей
  (default/effective/источник/hot), чужие random/budget ключи УДАЛЕНЫ;
  `intentRelatedLinks` :7010 — Случайность/Бюджеты ссылками-переходами.

**`web/index.html`** (2 хунка)
- Обзор Initiative (workspace-регион) :358–410 — data-initiative-status:
  «Работает/Не работает» + requested/effective/source, heartbeat, pending,
  next due, последнее решение/пропуск; env-emergency ветка с restart-пометкой.
- Блок «Настройки блока» на Статусе :6563 — собственные ключи + ссылки
  (рендер `intentRelatedLinks`), честная подписка restart/hot.

**`config/settings.py`** — только комментарий :1514–1524 (stale «Δ каталога=0»
→ актуальная семантика ASAP 7). Новых записей Settings НЕТ (цель брифа
выполнена: 9 ClassVar = env-ось, каталог — product-ось).

## 2. Тесты

**NEW `tests/test_asap7_module_registry.py`** — 14 тестов, CONTRACT
owner=asap7/F3:
- M1: effective ON при дефолтах (both); тумблер OFF → `product_toggle` и
  runtime-гейт совпадает; env OFF → `emergency_env` (env важнее UI); K2–K4
  оси независимы; лимиты hot + clamp; `candidate_from_trigger` инертен при
  product OFF; `intent_snapshot().module` (disabled/restricted ветки) с
  restart_required_env=true.
- M4 (drift): каждый ProductModuleSpec — master_param в каталоге
  (migratable), settings_groups ⊆ GROUPS, непустые status_source/help_anchor,
  закрытые множества classification/visibility; Initiative-привязка
  (top-level, вкладка, группы, 9 ключей с pg_id и канон-дефолтами).
- M2 (inventory): KILL_SWITCHES = MODULE_ENV_GATES ∪ rationale (без пропусков,
  дублей, мёртвых имён); JS-пин карточки/зеркал/merge-механики.

**Обновлённые пины** (frozen-contract обновляется в том же коммите; прецедент
mca-19/mca-20/2.58.57): счётчики каталога (REGISTRY 529→538, GROUPS 113→115,
_TAB_BY_GROUP 111→113, TAB_RULES/TAB_NAV/CONFIG_TAB_TITLES 22→23,
categorized 504→513, delta 118→127, TSV 530→539) в ~50 test-файлах (механический
sweep); menu-freeze 14→15 модулей / 27→28 вкладок (budget_guardrails,
round106_ia_smoke, round1020/1021, webapp_f4, 5 JS-харнессов); stale-guard
ClassVar-whitelist +9 MCA_INTENT_*; mca12 `storiesSettingsMeta`-пин →
собственные Intent-ключи (+JS round1046); ROUTES_SHA256_F11 переутверждён
(canonical + локальная копия mca23 + inline mca10b); test_webapp_status_control
— пин ключей /api/status догнал HEAD (experience/intents были на HEAD, тест
был RED до F3) + аддитивная проверка intents.module.

**F8 re-issue** (прецедент `tools/_mca20_reissue_f8.py`): NEW
`tools/_asap7_f3_reissue_f8.py` — регенерация TSV/meta/screen-map, обновление
`f8_baseline.json`/`catalog_baseline.json` (counts/sha256/superseded_by-нота).
Routes-инвентарь НЕ менялся (0 новых эндпоинтов).

## 3. Проверка

- `pytest tests/test_asap7_module_registry.py -x -q` → **14 passed**.
- Таргет-контур F3 (75 файлов, включая все mca09-блоки, status/webapp,
  config/access/roles, catalog/tab-pins, JS-unit): **2031 passed, 0 failed**
  (`-p no:randomly`).
- `node --check web/app.js` → OK; JS-харнессы: round1046 MCA12-STORIES-UI-OK,
  round1024 IMAGE-MODULE-OK, round1025 MODULE-STORE-OK, round1021 OK.

## 4. UI/визуальное доказательство (обязательные оба канала)

1. **Playwright детерминированно** — NEW `tools/ui_asap7_f3_e2e.py`
   (прецедент ui_mca12_stories_e2e; server/TMA-стаб reuse): desktop 1280×800 +
   mobile 390×844, reduced-motion; **failures: 0**. Проверено: карточка
   «Инициатива» в «Модулях»; F4-путь (registry-only модуль появляется карточкой
   без правки JS); страница `#/modules/initiative` — табы
   overview/settings/limits, живой блок requested/effective/source, heartbeat,
   pending=2, решение/пропуск, next due; settings = flags_intent (4),
   limits = limits_intent (5); «Настройки блока» — свои ключи, чужие
   random/budget ОТСУТСТВУЮТ, ссылки-переходы на месте; env-emergency OFF →
   «Не работает» + «env-emergency OFF (важнее UI)» + restart-пометка; без
   horizontal overflow. Скриншоты: `tools/_ui_asap7_f3_*.png` (7 шт.),
   raw: `tools/_ui_asap7_f3_e2e.json`.
2. **Browser Use (реальный Chrome)** через Code Mode: страница
   `#/modules/initiative` и хаб «Модули» отрендерены в живом Chromium
   (server-level стаб-сервер, TMA-стаб инъекцией; скретч-сервер и диагностические
   скрипты — в OPENCODE_WORKFLOW_SCRATCH, в репозиторий не попадали):
   DOM-пробы hasStatus/тексты гейта/overflow=false/карточка видима/toggle ON;
   «Настройки блока»: ownMaster/ownBackoff=true, foreignRandom/foreignBudget=
   false, links=[#/modules/sleep, #/modules/budgets]. Скриншот viewport
   зафиксирован в сессии.

## 5. Инварианты (acceptance)

- effective ON при дефолтах — да (both; тест + UI «Работает»).
- env `MCA_INTENTS_ENABLED=false` → effective OFF, source=emergency_env — да
  (тест + UI-ветка «Не работает» + restart-пометка).
- Карточка не показывает чужие ключи — да (JS-тест + Playwright + Browser Use).
- Настройки реально влияют на Intent service — да: гейты/лимиты читают каталог
  через hot (тест hot/clamp + candidate_from_trigger), без рестарта.
- Restart-семантика честная — env-ось помечена restart_required_env, каталог —
  hot (тест + подпись в UI).
- M4/M2 — RED-механика на месте (см. §2).
- mca_intents.py не правился (нулевой диф): все читатели уже идут через
  mca_gates — AND-гейт подключён на самом нижнем слое.

## 6. Что оставлено F4

- Записи реестра для Stories/Episodes, SelfModel/Character, Random, Experience
  (rationale-группа «submodule→F4» в module_registry:197 — готовый маппинг).
- Submodule-карточки (parent_id) — merge-механика уже пропускает их
  (`if spec.parent_id: return` в f3ApplyModuleRegistry) — F4 решает
  parent-модель и раскладку Advanced.
- JS-drift «весь JS-список ⊆ registry» — жёсткий пин включается, когда F4
  зарегистрирует остальные 14 карточек (сейчас fallback-витрина легальна, §3.1).

## 7. Отклонения от брифа / примечания для ревью

1. `web/api/routes.py` отсутствовал в WRITE_SCOPE, но objective 1 требует
   «аддитивный ключ ответа config/meta-API» — добавлен ровно один ключ
   `modules` в существующий GET /api/config (носитель реестра). Иных правок
   routes.py нет; routes-набор/байт-инвентарь f8_baseline не менялись.
2. app.js: помимо ~:515-660/:6745-7010, touch-точки регистрации вкладки
   (TABS :206, TAB_SECTION_ORDER :301, TAB_ICON :370) и вызов merge в
   loadConfig :12103 — функционально необходимы (зеркала TAB_RULES —
   прецедент MCA-19 D16 для mod_vision), расположены вне чужих секций
   (DIRECT-UI/ACCESS/COVER).
3. index.html: два хунка — workspace-регион страницы модуля (:358, «регион
   табов» в расширенном смысле: контент вкладки Обзор mod_initiative) и блок
   «Настройки блока» (:6563, рендер чинимого блока из objective 3).
   Третий хунок :4375 — не мой (параллельный F8, Run Inspector).
4. В worktree есть незакоммиченные правки параллельных лейнов (bot.py,
   chat_lifecycle.py — F5; cover_style_jobs.py, web/api/analytics.py,
   app.js/index.html SECTION-COVER/ACCESS хунки — F8): не тронуты, в мой
   фингерпринт не входят.
5. `test_status_service.py::…` и др. — пины обновлены по факту контракта;
   `test_webapp_status_control` был RED ещё на HEAD (пин не знал про
   experience/intents) — чиню тем же коммитом (related-nonblocking).

## 8. Инцидентальные находки

- **related-nonblocking (закрыто здесь)**: stale-пин ключей /api/status
  (test_webapp_status_control) и stale-комментарий settings.py:1521.
- **uncertain (не воспроизведено после стабилизации)**: единичные отказы
  `test_mca09_intents_block_e` (`cancelled` → `sent`) в больших батчах при
  параллельной нагрузке; в изоляции пара «f3-файл + block_e» зелёная в ~37
  прогонах, block_e соло — 10 сидов чисто, финальный полный батч 2031/2031.
  Похоже на pre-existing порядок/нагрузку-зависимую поверхность (много тестов
  ставят hot-кэш глобально). К хирургии гейтов отношения не имеет (гейт на
  момент отказа True/False диагностирован чистым). Оставляю Ревьюеру как
  наблюдение.
- **unrelated/pre-existing (HEAD)**: test_asap5_paradigms_diagnostics::
  test_bootstrap_cooldown_bypass_then_cap, test_tool_loop::
  test_query_chat_memory_count_reaches_model — подтверждено RED на чистом
  HEAD (git stash-проба), к F3 не относятся.

## 9. Фингерпринт кандидата

- База: HEAD `08a8849`. Файлы F3 (новые): `services/module_registry.py`,
  `tests/test_asap7_module_registry.py`, `tools/ui_asap7_f3_e2e.py`,
  `tools/_asap7_f3_reissue_f8.py`.
- Файлы F3 (правки): `services/param_catalog.py` (+106), `services/mca_gates.py`
  (гейты :1265–1345), `services/status_service.py` (:732–864), `web/app.js`
  (9 F3-хунков), `web/index.html` (2 F3-хунка), `web/api/routes.py` (:589–596),
  `config/settings.py` (комментарий), `tests/fixtures/round1025/
  {f8_baseline,catalog_baseline}.json`, `plans/docs/param-registry-*` (re-issue),
  ~50 тест-файлов (пины), 6 JS-харнессов (пины).
- Проверка: pytest 2031/2031 (таргет-контур), registry-тесты 14/14,
  UI-e2e 0 failures, node --check OK.
