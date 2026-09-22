# F5 `module-workspace-tabs-round1025` — Review (финал, Step 5 @Reviewer, T-2737)

> Дата: 22.09.2026. Diff base: HEAD `12a55bb`. Секреты не цитировались (R17/R18).
> Проверены: M-F5S-1 (@Scanner), L-F5S-1..3, T-2714 (§49-карточка), T-2703 (Playwright), T-2733 (red→green).
> Вердикт: **Approved**.

## Checks performed (воспроизведено независимо)

| Проверка | Результат |
|---|---|
| `node --check web/app.js` | OK |
| Все `tests/js/*.js` (32 файла) | **0 падений** |
| F5-маркеры (workspace/prompts/models) + 6 регресс-маркеров | все зелёные |
| `py -3 -m pytest tests/test_webapp_f5_round1025.py -q` | **19 passed** |
| `py -3 -m pytest -q` | **8245 passed, 1 skipped, 5 failed** |
| `git diff --check` | exit 0 |
| Δ каталога | 459 / 98 / 96 / 21 / 418 |
| Δ backend/DDL (`services/**`,`web/api/**`,`handlers/**`,`bot.py`,`migrations`,`*.sql`) | 0 файлов |
| `APP_VERSION` | 2.58.10 |
| Red→green (независимые мутации, восстановление byte-identical) | см. ниже |

5 failed — env (`ImportError: InputRichMessageMedia`, aiogram 3.29.1) в файлах 10.22/10.23, вне диффа F5. Не регресс.

## Findings → статус

| # | Находка | Статус | Доказательство |
|---|---|---|---|
| M-F5S-1 | Клик из библиотеки для `mod_summary`/`mod_sleep` уводил на «Обзор» | **Закрыто** | `openWorkspacePrompt` учитывает `ws.door==='library'` → `#/ai/prompts/<slug>[/<stage>]/<key>` (`web/app.js:5174`); `parsePromptLibraryRoute` распознаёт `prompts.*` в слоте stage (985); `workspace()` пробрасывает `promptKey` (1711). Проба (независимая): `#/ai/prompts/summary` → редактор, клик → `#/ai/prompts/summary/verbalizer/<key>`, `applyRoute` маршрут сохраняет, фокус = **тот же объект** configItems. Мутация `ws.door==='library'`→false → тест падает. |
| L-F5S-1 | Тач-цель табов <44px | **Закрыто** | `app.css:2038` `[data-workspace-tabs] button { min-height:44px; }` + `.prompt-tree-item`; Playwright-проба даёт `tabsMinTouch=44`. |
| L-F5S-2 | ARIA `role=listitem` на `<button>` | **Закрыто** | `web/index.html:526` `<aside role="group" aria-label="Промпты">`, `role="listitem"` убран. |
| L-F5S-3 | «Пустая» библиотечная дверь | **Закрыто** | `applyRoute` (4044): модуль без `MODULE_PROMPT_GROUPS` → `#/ai/prompts`; тест (b3). |
| T-2714 | §49-карточка: поля/секреты/0 POST | **Закрыто** | `buildConnectionCard` читает только `role==='model'`; шаблон рендерит `data-conn-field=title/purpose/primary-model/fallback-model/status` + `data-conn-test`/`data-conn-configure`/`data-connection-settings`; `toggleConnectionSettings` только флаг. Тест (g/h/i) поведенческий: секреты не читаются, `last4` не в значениях, раскрытие = 0 POST, «Проверить» → reuse `testBlock`. Точная мутация чтения `keys.*` → тест падает; мутация POST при раскрытии → падает. |
| T-2703 | Playwright-матрица 10×17, failures 0 | **Артефакт подтверждён** | `tools/ui_round1025_matrix.py` — реальный `sync_playwright()`+`chromium`, поднимает сервер `127.0.0.1:8791`; `tools/_ui_round1025_raw.json`: viewports 10 (`320x700…2560x1440`), 17 маршрутов, `failures: []`, `overflow:false`, `tabsMinTouch=44`, `cardTest/CfgMinTouch=44`, скриншоты `_ui_round1025_shots/*`. **Сам браузерный прогон не перезапускал** — Playwright в моём окружении не установлен (см. Unavailable). |
| T-2733 | red→green | **Закрыто** | Ниже. |
| §48/§49/§46 инварианты | один источник, один write-path, `m.tab`/RBAC/kill-switch, `openModuleWindow` | **Сохранены** | `openModuleWindow: function` и fallback на месте (`app.js:4311`, `:5199`); `routeToTab` workspace → `m.tab`; маркеры `IMAGE-MODULE-OK`/`JS-UNIT-OK` зелёные; канон промптов (`services/**`) не тронут. |

## Независимый red→green (мутации в копии, restore SHA256-идентичен)

| Мутация | Красный |
|---|---|
| `openWorkspacePrompt`: убран `door==='library'` | prompts-тест exit 1 (M-F5S-1) |
| `buildConnectionCard`: чтение `keys.*` | `g: секреты карточкой не читаются` |
| `toggleConnectionSettings`: POST при раскрытии | `h: раскрытие формы не пишет (0 POST)` |
| `modelOf`: подстановка `default-model` | `g: пустая модель → честно пусто` |

## Non-blocking debt

- LOW: библиотечная дверь модуля без промптов теперь редиректится на `#/ai/prompts` (закрыто), но
  для `mod_summary` активного таба в шапке нет (вкладки `prompts` нет в `m.tabs`) — визуальная мелочь.
- LOW: `[I-F5S-1]` L1/L2 используют одну модель (`models.llm_model_name`) — соответствует §84 («честно, без роутинга»).
- LOW: тест «секреты не читаются» устойчив, но проверка зависит от порядка полей блока (api_key после model) — усилить явной пробой на блоке, где секрет — первое поле (необязательно).

## Unavailable checks

- **T-2703 браузерный прогон не перезапускал**: `playwright` не установлен в среде @Reviewer; опора — артефакт
  `_ui_round1025_raw.json` + исходник матрицы + скриншоты (согласованы: 10 вьюпортов × 17 маршрутов, failures 0).
- **Live-гейт владельца (T-2742)**: реальный Telegram WebView, `?v=2.58.10`, `/api/health` 200, `database is locked`=0.

## Verdict

**Status: Approved.** M-F5S-1 закрыт и доказан; L-F5S-1..3 и T-2714 закрыты; T-2703 подтверждён артефактом;
T-2733 red→green воспроизведён независимо. Новых блокеров нет; инварианты и регресс-пути сохранены.
Остаётся live-гейт владельца.
