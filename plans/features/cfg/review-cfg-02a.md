# REVIEW-CFG-02A — независимое ревью слайса CFG-02A (кандидат `669debfa`, 19 файлов)

| Поле | Значение |
|---|---|
| Кандидат | `669debfa8dd96fe19dcd74a6a1e816bc45163f0e` (19 файлов, +1854/−53), база `2bc13f44`, прод 2.58.88 |
| Входы | `evidence/cfg-02a/README.md` + `red-green.txt` + `ui/*` (8 PNG); строки карты slice=CFG-02A (9); `source-cfg-addendum.md` L63–L77 |
| Вердикт | **Needs Fixes** — 1 блокер (клиентский guard пропускает пустой ввод: живой POST `= 0`); нить изоляции (2 глиф-хунка речи) на решение PM до биндинга; функции ядра слайса — рабочие и хорошо закрытые тестами |

## 0. Блокер B1 — пустой ввод сохраняется как `0` («генерация запрещена»)

**Требование:** §02A.3 (L73) «Запретить ввод невалидных значений»; бриф REV — «невалидный ввод = 0 POST».
**Механизм (проверен и кодом, и ЖИВЫМ прогоном на стенде лейна):**
* `web/app.js::imageQuotaValueValid` принимает `''`/пробелы/`null`: `Number('') === 0`, `isFinite(0)` ✓, `Math.floor(0)===0` ✓, `0 >= −1` ✓ (node-проверка на извлечённой функции: `'' → true`, `' ' → true`, `null → true`; `'−7'/'2.5'/'abc' → false`).
* `saveImageDailyLimit` считает `'' → 0` валидным, сбрасывает ошибку, `item.value = 0`, идёт `saveConfigItem` → POST.
* **Живой репро** (stub-сервер лейна `--serve` + мой отдельный Playwright-скрипт, штатная навигация `#/modules/images/settings`, GLOBAL): поле `60` → очистка поля и коммит `change` → **`POST limits.image_daily_limit = 0`**, элемент ошибки НЕ появился, DOM показывает `0`, page errors нет. Скрипт: `…/review-cfg02a/probe_empty_input.py` (scratch).
**Влияние:** обычное на мобильном «очистить поле и уйти» молча выключает генерацию в выбранной области (0 = запрет), с тостом «Сохранено»; это ровно тот класс ввода, который требование велело запретить. Существующий тест `test_client_guard_blocks_invalid_value` проверяет guard **текстово** (regex по app.js), поэтому дыру не видит; E2E проверяет только `−7`.
**Минимальная коррекция:** в `imageQuotaValueValid` отклонять пустое/пробельное (`if (raw == null || String(raw).trim() === '') return false;`; при желании — тот же error-хинт), добавить кейс «пустой ввод → 0 POST» в E2E (или unit) и перепрогнать.
**Мини-речек:** мой `probe_empty_input.py` → `POSTs after EMPTY change: []`; `ui_cfg02a_image_quota_e2e.py` → `invalid_posts_count=0`; наборы §2 ниже остаются зелёными.

## 1. Состав — 19 файлов, чужих ФАЙЛОВ нет; blob sha сходятся

* `git show --stat 669debfa` = 19 файлов: 10 evidence (README, red-green, 8 PNG) + 9 кодовых (`services/{image_generation,worker_budget,tool_router}.py`, `web/{app.js,index.html}`, `tests/{test_cfg02a_image_quota_ui,test_soul1_capability_fallbacks,js/round1024_image_module_test}.py/js`, `tools/ui_cfg02a_image_quota_e2e.py`). Чужих путей/файлов нет; правки FIX-SPEECH-MOBILE по `web/app.js|index.html|app.css` остались uncommitted (см. нить N1 — но 2 хунка речи всё же внутри).
* blob sha12 (конвенция = git-object id, проверил 10/10 против `red-green.txt` §CANDIDATE): app.js `92f60ed1e28b`, index.html `312a2ed00691`, image_generation `c560e15d118a`, worker_budget `7cdf9ea20b0f`, tool_router `8ec679eb43e3`, cfg02a-тест `2734311de0ab`, soul1-тест `26e8128069d5`, js-тест `b9f43e8dbe7e`, e2e-инструмент `d3dbdcc67fd5`, README `914d00412dde`.
* Δ каталога = 0: `web/`+`services/param_catalog.py` не тронуты; `tests/test_param_catalog.py` и `test_round1025_f8_registry.py` зелёные; подписи — витринные (`CONFIG_GROUP_DISPLAY`/`CONFIG_ITEM_DISPLAY_OVERRIDES`, прецедент B07) ✓.

## 2. RED→GREEN воспроизведён (мои прогоны)

* **RED (мой worktree базы `2bc13f44` + те же новые тесты):** `test_cfg02a_image_quota_ui.py` → **10 failed, 17 passed** (ровно те же 10 имён, что в `red-green.txt`); `test_soul1_capability_fallbacks.py` → **1 failed, 40 passed** (`[budget-quota_exhausted]`).
* **GREEN (кандидат):** cfg02a-файл → **27 passed**; набор 6 файлов (cfg02a+soul1-capabilities+image_daily_limit+registry+param_catalog+frontend_tab_mapping) → **183 passed**; `node tests/js/round1024_image_module_test.js` → **IMAGE-MODULE-OK**; `pytest tests/test_webapp_js_unit.py` → **38 passed**.
* **Blast-radius (мой набор 24 файла: image/param/webapp/frontend/soul1/summary/budget/tool_router/settings/matrix) → 800 passed.**
* **F5-пин (item 3) не ослаблен, а усилен:** ожидается ровно `['flags_module_images','limits_images']` + `limits_images` не дублируется НИ в одной другой вкладке; старых ассертов не удалено.

## 3. Acceptance строк CFG-02A — что проверено и чем

* **02.D (UI-дефект):** корневая причина закрыта (зеркало `TAB_RULES` + маппинг `limits_images → settings` + секция/факты); RED на базе это подтверждает; e2e `settings_section_visible=true`, `no_limits_tab_for_module=true` (вкладки «Лимиты» больше нет — одно место).
* **02A.1/02A.2 (витрина):** подписи «Лимиты генерации»/«Изображений в сутки», единицы/политика списания, факты (значение/источник/расход/остаток/TZ/сброс/общий env-бюджет/честный режим/хинт) — тесты + мой визуальный просмотр скринов (1440 и 390): переполнения нет, цифры/подписи читаемы, «Источник: Заводской» и т.п. честные.
* **02A.3 (управляемость):** hot-reload GLOBAL без рестарта, CHAT override изолирован, сброс override → наследование без изменения GLOBAL, 0/−1/>0 семантика, no-op guard (0 POST при неизменном значении) — тесты + e2e `save_posts_count=1`, `chat_scope_*`.
* **02A.4 (реальный эффект):** 10→2→5 без рестарта; честный режим reserve/legacy (`kill_switch_off`/`budgets_off`) виден в UI (§27 `reserve_path`/`reserve_reason`); shared env-лимит отказывает при остатке квоты — тесты + e2e `legacy_mode_notice`/`budgets_off_notice`.
* **02A.5 (отказ):** deny ДО платного вызова (`calls['gen']==0`, журнал `denied/limit_chat`), речевая форма SOUL-1 + фактическая строка «Суточная квота обновится DD.MM.YYYY HH:MM (TZ)», без cooldown-лексики; helper fail-open (`''`) — тесты.
* **02A.6 (пути/границы):** direct/tool/replay (второго списания нет), ошибка провайдера возвращает квоту, ошибка доставки сохраняет списание; изоляция обложек Summary — граница CFG-02C: замер подтверждён и мной (`summary_generator.py:3390` вызывает `generate_image_verbose(chat_id=chat_id)` → обложка тратит тот же `chat:<id>` `image_calls`). README честно предупреждает, что это нарушает L67/L76/L105 до CFG-02C.
* **02A.7 (матрица тестов):** 27 тестов, песочница (in-memory PG-стаб из round1026, без внешних расходов); TZ/смена суток проверены на не-UTC зоне (Pacific/Kiritimati), `image_next_reset` = локальная полночь.
* **Фикс учёта при `−1` (R3) — подтверждён A/B-пробой** (мой скрипт, один и тот же сценарий): база → счётчик чата **None** (расход не учитывался), кандидат → **3**. Это исправление, а не маска: тот же `UPSERT_SQL`, что и в shared-контуре; при `−1` отказ невозможен, учёт ведётся.
* **AC1:** значение/счётчик дня переживают перезагрузку/рестарт (тест `test_restart_keeps_used_and_limit`, e2e `facts_value_after_save`).

## 4. Pre-existing RED — спот на базе без правок CFG-02A

Воспроизвёл на базовом worktree `2bc13f44` (мои копии — только тестов CFG-02A): `test_asap7_direct_settings.py` → **2 failed** (v35, известен с CFG-01) + `test_t5150_startup_migrations_round1046.py` → **5 failed** — состав совпадает с отчётом. Оговорка: `test_outgoing_guard_round1022.py` (2 из «12 предсуществующих») **изолированно зелёный и на базе, и на кандидате (25 passed)** → пара не воспроизводится вне полного прогона (порядко-зависимая краснота, не от CFG-02A).

## 5. UI/E2E и визуальная проверка

* Мой перезапуск `tools/ui_cfg02a_image_quota_e2e.py` → **RESULT: PASS**, `console_errors=[]`; ключевые факты совпали: `facts_value='60 генераций/сутки'`, `used/remaining`, `tz=Asia/Yekaterinburg`, `reset='19.10.2026, 00:00'`, `input{value:60,min:-1,step:1}`, `save_post={value:2,chat:false}`, `facts_value_after_save='2 генераций/сутки'`, `invalid_posts_count=0` (для −7), `mobile_section_visible=true`, `mobile_no_overflow=true`, `no_limits_tab_for_module=true`.
* Повторный прогон не изменил committed-скрины (git clean) — детерминизм.
* Просмотрел скрины: `01-settings-global` (1440: секция + факты + shared), `02-invalid-input` (ошибка «Допустимо целое число…», POST нет), `05-mobile-chat` (390×844 — без переполнения) и `browseruse-390-settings-section` (реальный рендер, мобильный макет). Нит: файл `browseruse-390-settings-section.png` фактически 1554×1359 (DPR-масштаб 390-макета) — имя вводит в заблуждение (косметика evidence).

## 6. Гейт (попытка) и пригодность evidence для биндинга

`check --stage review --slice CFG-02A --candidate 669debfa…` → `scoped=9 errors=10` EXIT 1 (ожидаемо, pre-binding). Не хватает: (1) `candidate_commit := 669debfa…` в карте (сейчас 0282fe4b от CFG-01); (2) candidate-bound evidence на все 9 строк (CFG-02.D, 02A.1–02A.7, CFG-02.AC1) — README-таблица покрывает их, sha/refs нужно оформить; (3) **6 live-строк — `live_required/preprod`**: review-гейт требует `VERIFIED` + live/ui-typed evidence на review-стадии, поэтому либо выполнить preprod-live до закрытия review, либо (прецедент CFG-01) переклассифицировать в `live_when=postdeploy` + `live_note` + `READY_FOR_LIVE`. Пригодность `evidence/cfg-02a/**`: README + red-green + 3 тестовых файла + e2e-инструмент + 8 PNG — реальные артефакты; мои прогоны подтверждают их числа (10/17, 1/40, 27, 183, 800, RESULT: PASS). Нит N2: README говорит «18 файлов» (2 места) — фактически 19 (поправить до биндинга, чтобы не копировать в карту).

## 7. Нить N1 (изоляция) — решение PM до биндинга

В кандидате есть **2 хунка из REFINE FIX-SPEECH-MOBILE** (`web/index.html`: «Речь и характер», `iconGlyph('record_voice_over')` → `edit_note`, строки 7459/10003; в базе `record_voice_over` отсутствовал в `ICONS` → рендерился пустой значок). Это противоречит (а) брифу REV «чужих 0» и (б) записи speech-лейна «мои правки в HEAD НЕ входят». Хунки безвредны функционально, но принадлежат другому лейну: до биндинга нужно либо откатить их в CFG-02A (2 строки, тогда их внесёт speech-коммит), либо явно переоформить владение (запись в evidence + корректировка speech-evidence + классификация в релизном payload). Решает PM/Orchestrator (REV-SPEECH-MOBILE уже смотрит «глиф, интеграция с `669debfa`»).

## 8. Нит N4 (не блокер)

Отказ по shared-env (`limit_global`) в `_reserve_or_consume` сводится к reason `budget`, поэтому и он получает строку «Суточная квота обновится … (TZ чата)»; при дефолтном `WORKER_BUDGET_TZ=Asia/Yekaterinburg` время фактически верное, но если у чата своя TZ — час сброса shared-контура может быть назван неверно. Кандидат на уточнение в CFG-02B/02C (истинный источник отказа в тексте), вероятность низкая.

## Итог

Ядро слайса (витрина, управление, реальный эффект, честный отказ, учёт при `−1`) подтверждено независимо и закрыто сильными поведенческими тестами; это полноценный фикс дефекта CFG-02.D. **Блокер один: пустой ввод сохраняется как `0` (живой POST) — требуется правка guard + кейс в тестах (мини-речек см. §0).** Отдельно до биндинга: нить N1 (2 глиф-хунка речи), N2 (18→19 в README), статусные семантики 6 live-строк (N3).
