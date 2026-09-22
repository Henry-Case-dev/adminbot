# F5 `module-workspace-tabs-round1025` — Scanner audit (Step 6 @Scanner, T-2738, повторный)

> Дата: 22.09.2026. **База:** HEAD `12a55bb` (`pre-round1025-f5`, == `origin/master`). Правки **НЕ закоммичены** — аудит рабочего дерева. Секреты не цитировались (R17).
> Вход: `plans/features/module-workspace-tabs-round1025/{spec.md,adr-1025-15,evidence.md,review.md,tasks.md}`; `plans/current_task.md` §46–§49/§84/§85 (untracked, не изменялся).
> **Вердикт: Critical 0 / High 0 / Medium 0 / Low 0 / Info 2. К деплою — ДА.** Все находки итер.1 ([M-F5S-1], [L-F5S-1..3]) закрыты по коду и доказательно; новых Critical/High/Medium от правки нет.

---

## 1. История: что правилось между итерациями аудита

### Итерация 1 (первый аудит) — блокер [M-F5S-1]
Для `mod_summary`/`mod_sleep` клик по промпту из «ИИ → Библиотека промптов» строил `#/modules/<slug>/prompts/<key>`; т.к. промпт-вкладка не объявлена в `m.tabs`, `applyRoute` нормализовал маршрут в «Обзор» — редактор не открывался. Также L-F5S-1 (тач-цель табов < 44px), L-F5S-2 (`role="listitem"` на `<button>`), L-F5S-3 («пустая» библиотечная дверь).

### Итерация 2 (этот аудит)
- **M-F5S-1 fix:** `parsePromptLibraryRoute` теперь читает `promptKey` (`#/ai/prompts/<slug>[/<stage>]/<key>`); `workspace()` прокидывает `promptKey` для двери `library`; `openWorkspacePrompt` для `door==='library'` остаётся в библиотеке (не строит модульную вкладку); `routeParent` учитывает `promptKey`.
- **L-F5S-1:** CSS `[data-workspace-tabs] button { min-height: 44px; }` (+ `.prompt-tree-item`, `.conn-*`).
- **L-F5S-2:** `web/index.html` `<aside class="prompt-tree card p-3" role="group" aria-label="Промпты">`, кнопки без `role="listitem"`.
- **L-F5S-3:** `applyRoute` при `!MODULE_PROMPT_GROUPS[plm.id]` → `#/ai/prompts`.
- **T-2714 (§49-карточка):** `buildConnectionCard`/`workspaceModelCards`/`connectionCard`/`toggleConnectionSettings`/`testConnection` + шаблон `data-connection-card` (название/назначение/основная/резервная модель/статус + «Проверить»/«Настроить»).
- **T-2703/T-2733:** Playwright-матрица `tools/ui_round1025_matrix.py` (+`F5_PROBE_JS`, 4 F5-маршрута, touch/overflow-пробы), red→green в `evidence.md`.

---

## 2. Независимо воспроизведённые прогоны (итер.2)

| Проверка | Результат |
|---|---|
| `node --check web/app.js` | OK |
| `tests/js/round1025_f5_workspace_route_test.js` | `MODULE-WORKSPACE-OK` |
| `tests/js/round1025_f5_prompts_single_source_test.js` | `PROMPTS-SINGLE-SOURCE-OK` |
| `tests/js/round1025_f5_models_test.js` | `MODELS-GROUPS-OK` |
| `tests/js/routing_test.js` | `JS-UNIT-OK` (exit 0) |
| `tests/js/round1024_image_module_test.js` | exit 0 (`IMAGE-MODULE-OK`) |
| `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` | exit 0 |
| `py -3 -m pytest tests/test_webapp_f5_round1025.py -q` | **19 passed** |
| Регресс-пины: `test_webapp_js_unit`, `test_hotfix_round1025_cachebust`, `test_scope_selector_round1025`, `test_webapp_design_tokens_round1025`, `test_webapp_hotfix6_round1025`, `test_webapp_hotfix7_round1025`, `test_round106_ia_smoke`, `test_webapp_round1011_ui` | **202 passed** |
| `git diff --check` | exit 0 (только CRLF-предупреждения) |
| Δ backend (`services/`,`web/api/`,`handlers/`,`bot.py`,`migrations/`) | 0 строк — вне диффа |
| Δ DDL | 0 |
| Δ каталога | **459 / 98 / 96 / 21 / 418**; `services/param_catalog.py` не тронут |
| `APP_VERSION` | **2.58.10** синхронен (`config/settings.py:1702`, `README.md:5`) |
| Откат/гигиена | тег `pre-round1025-f5`→`940ba40`, бэкап `var/backups/f5-round1025-20260922-142358`, `.env.bak.round1025-f5`, `stash@{0}` — целы; 14 тегов `pre-round1025*`. В изменениях нет `.env`/`current_task.md`/zip/скриншотов |

Полный pytest не перезапускался (опора на @Builder/@Reviewer: 8245/1/5 — предсуществующие/env); целевые подмножества F5 зелёные.

## 3. Доказательство закрытия [M-F5S-1] (probe на реальном `web/app.js`)

Независимый harness (require реального `web/app.js`, Vue-стаб, `computed.workspace`/`workspacePromptFocus`/`workspacePromptList`), **PROBE-ALL-PASS**:

| Сценарий | Маршрут | Результат |
|---|---|---|
| summary, ключ без stage | `#/ai/prompts/summary/prompts.summary_system_prompt` | door=library, tab=prompts, focus=`prompts.summary_system_prompt`, list=2 ✔ |
| summary, stage+ключ | `#/ai/prompts/summary/synthesizer/prompts.summary_system_prompt` | stage=synthesizer, focus найден ✔ |
| sleep, ключ без stage | `#/ai/prompts/sleep/prompts.memory_extract` | focus=`prompts.memory_extract`, list=1 ✔ |
| factcheck, stage+ключ | `#/ai/prompts/factcheck/synthesizer/prompts.factcheck_system_prompt` | focus найден ✔ |
| модульная дверь (регресс) | `#/modules/factcheck/synthesizer/prompts.factcheck_system_prompt` | door=modules, focus найден ✔ |
| `openWorkspacePrompt` (library, без stage) | — | `#/ai/prompts/summary/prompts.summary_editor` ✔ |
| `openWorkspacePrompt` (library, stage) | — | `#/ai/prompts/summary/synthesizer/prompts.summary_system_prompt` ✔ |
| `openWorkspacePrompt` (modules) | — | `#/modules/factcheck/synthesizer/prompts.factcheck_system_prompt` ✔ |

Покрытие тестами: `round1025_f5_prompts_single_source_test.js` блок (g) + `test_webapp_f5_round1025.py::test_...` проверяют summary/sleep-клик (не только factcheck). Блокер снят.

## 4. Проверка новой §49-карточки (T-2714)

- **Секреты не читаются/не выводятся.** `buildConnectionCard`/`modelOf` читают только поля `role === 'model'`; в diff добавленных строк `app.js` нет `last4`/`console.*`; поле `api_key` — только в комментарии. Тест (g) `round1025_f5_models_test.js` спаем на `blockFieldValue` доказывает: `keys.*` не читаются, `last4`/`configured` не попадают в значения карточки.
- **0 POST при открытии/раскрытии.** `workspaceModelCards`/`connectionCard` — чистое чтение `configItems`; `toggleConnectionSettings` меняет только UI-объект `connectionSettingsOpen` (тест (h): `wrote === 0`); запись — только `saveBlock` по кнопке. `testConnection` = `testBlock` только по клику (тест (i)).
- **«Не менять сохранённую модель».** `modelOf` = `blockFieldValue` (сохранённое значение, без подстановки дефолта); тест (g): `primary === 'saved-model-XYZ'`, `fallback === 'fallback-model-ABC'`; для изображений — честно пусто.
- **Reuse:** поля из `PROVIDER_BLOCKS`/`subBlocks`, «Проверить» → существующие `/api/llm/test`,`/api/images/test`, форма — существующий `saveBlock`. Новых API/хранилищ нет.
- **Шаблон:** summary показывает только несекретные поля; раскрытая форма — существующий masked-secret инпут (`:type="f.secret && !keyReveal[f.key] ? 'password' : 'text'"`), без нового канала. Тач-цели ≥44px (`.conn-*`).

## 5. Находки

### Medium — нет (все закрыты)
- **[M-F5S-1] RESOLVED (итер.2).** Доказательство — §3.

### Low — нет (все закрыты)
- **[L-F5S-1] RESOLVED** — `[data-workspace-tabs] button { min-height: 44px; }` (+ `.prompt-tree-item`), проверено pytest.
- **[L-F5S-2] RESOLVED** — `role="group" aria-label="Промпты"`, кнопки без `role="listitem"`.
- **[L-F5S-3] RESOLVED** — `applyRoute`: модуль без `MODULE_PROMPT_GROUPS` → `#/ai/prompts` (тест b3).

### Info
- **[I-F5S-1]** `directStageCards` L1/L2 — одна модель `models.llm_model_name` (честно по §84). Принято.
- **[I-F5S-2]** Полный pytest, Playwright-матрица T-2703 и live-гейт владельца T-2742 (реальный Telegram WebView) @Scanner не воспроизводились — опора на @Builder/@Reviewer/владельца. Принято. `tools/ui_round1025_matrix.py` использует только `http://127.0.0.1` — без внешних URL/секретов.

## 6. Инварианты и «чисто» (итер.2)

- **CSP / zero-build:** в добавленных строках `web/**` 0 внешних URL/CDN/`data:`-URI/inline-скриптов (`http(s)://`/`cdn`/`<script src=`); `innerHTML`/`v-html`/`insertAdjacentHTML`/`eval(`/`new Function`/`document.write` — 0; WebGL (`getContext('webgl`) отсутствует; новых библиотек/state-менеджеров нет.
- **R17:** новых логов/`console.*`/сырых ключей нет; `keys.*`-копий в модулях нет (pytest `test_api_keys_not_copied_into_module`); R17-проба маски зелёная.
- **R18:** тег `pre-round1025-f5`→`940ba40`, бэкап `f5-round1025-20260922-142358`, `.env.bak.round1025-f5`, `stash@{0}` целы; `plans/current_task.md` не изменялся; `.env`/zip/скриншотов нет.
- **Δ DDL=0, Δ каталога=0** (459/98/96/21/418); ноль backend-строк диффа; новых эндпоинтов нет (reuse `/api/llm/test`,`/api/images/test`); `APP_VERSION` **2.58.10** синхронен.
- **Маркер-тесты не ослаблены:** diff `tests/**` = только версионные пины (2.58.9→2.58.10), `providerGrouped` (замена устаревшего `providerConnectionBlocks`, `providerAdvancedBlocks`/«Расширенные настройки» удержаны) + аддитивная регистрация 3 F5-раннеров; плюс новые F5-тесты (M-F5S-1, L-F5S-1..3, §49-карточка). Никаких «тихих» удалений проверок.
- **Совместимость:** IA F1/`ROUTE_*` целы; `routeToTab`= `m.tab` → RBAC (`canViewTab`) и kill-switch `mod_images` (`_flagTabHidden`) работают (`IMAGE-MODULE-OK`); store F4 §37–§42 и `persistItems` не переписаны; токены F2, shell hotfix6/7 не тронуты; `openModuleWindow` — живой регресс-путь + fallback (тест (e)).
- **Логика:** «один промпт — один источник» — обе двери резолвят один `configItems`-элемент; один write-path F0; «0 POST при открытии» §49/§84; пустая общая вкладка не рендерится; 6 групп §49 покрывают каждый блок ровно раз.

## 7. Изменённые файлы

`web/app.js` (+752), `web/index.html` (+384), `web/static/app.css` (+58), `tools/ui_round1025_matrix.py` (+72), `config/settings.py`, `README.md`, 12 `tests/**`, docs (untracked): `spec.md`, `adr-1025-15`, `evidence.md`, `review.md`, `plans/reports/round1025_f5_ai_map.md`.

## 8. Ссылки

- Сводка: `plans/reports/full_audit_results.md` (round 10.25 F5), `plans/reports/audit_backlog.md`, `plans/reports/global_map.md`.
- Вход: `plans/features/module-workspace-tabs-round1025/`; AI-карта: `plans/reports/round1025_f5_ai_map.md`.
