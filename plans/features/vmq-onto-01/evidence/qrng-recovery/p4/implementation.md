# QRNG P4 — UI «Модули → Случайность» (2026-11-17)

**Ветка:** `fix/qrng-p4`  
**База:** `6cf4c32c` (P3 corrective evidence; code `835b2433`, `fix/qrng-p3`)  
**Статус:** REVIEW (не VERIFIED, не deploy, версия не поднималась). P5 не начат.  
**Кандидат:** `52662927`.

## 1. Что реализовано

Контракт ARCH_DECISION (`arch-decision-2026-11-17.md` §4, D4/D6) и поручение
владельца §5/§9: отдельная config-вкладка «Случайность» с 4 смысловыми
блоками A–D, настоящим селектором провайдера, честной активностью и переносом
`keys_random` из «Моделей».

| Файл | Изменение |
|---|---|
| `services/param_catalog.py` | `TAB_MOD_RANDOM`; `CONFIG_TAB_TITLES`/`TAB_NAV` +1; `TAB_RULES` +1 (23): `memory_random`+`keys_random` → mod_random; те же группы убраны с `mod_sleep`/`llm_providers`. `GROUPS`/`_TAB_BY_GROUP`/REGISTRY не менялись (121/119/648). |
| `services/module_registry.py` | `ModuleSpec(random).config_tab="mod_random"` (memo/rationale обновлены). |
| `web/app.js` | `TABS` +mod_random (29 вкладок, `TAB_RULES` mirror); sources LLM/Sleep очищены; `TAB_TO_ROUTE`/`ROUTE_TO_TAB`/`ROUTE_PARENT`; `TAB_SECTION_ORDER`; `TAB_ICON`; `WORKSPACE_TABS.mod_random=['overview','settings','history']` (B3-совместимая строка); `MODULE_MODEL_BLOCKS.mod_random=[]`; `PROVIDER_GROUPS` — таймауты последними; `currentTabGroups`/`workspaceTabHasContent` — кастомная страница; `setTab` — один существующий `/api/status` при входе; 3 честных чипа в `moduleStateChips`; presentation трёх провайдеров; методы селектора/порядка/полей/активности; компонент `qrng-field`. |
| `web/index.html` | Кастомные блоки A–D: сводка; селектор (3 опции), fallback-переключатель и список (вверх/вниз/включить-исключить); ровно 3 карточки (IBM — «не подключён, P5», без полей; ANU — ключ/проверка/«Дополнительно»; LfDR — «ключ не требуется», состояние, ссылка); применения; активность; `<details>` D. Перенесённая подсказка о draft-ключе. Карточка на «Сне» ведёт на `#/modules/random`. Старый generic-блок ANU-проверки удалён (перенос, не копия). |
| `tests/js/qrng_p4_random_ui_test.js` | Новый JS-тест: карта вкладок, реальный POST селектора, fallback-порядок без primary/дублей, честная Activity, draft-подсказка, 3 карточки/3 опции, Lizaonair=0, порядок таймаутов. |
| `tests/js/*` | Осознанно обновлены пины: 29 вкладок, mod_random в expected-списках, порядок `PROVIDER_GROUPS`, перенос groups, history-исключение, fixture `module_registry_visible.json`. |
| `tests/*.py` | Осознанно обновлены TAB_RULES/NAV/TITLES 22→23, group_tab и expected ID, `F4_CONFIG_TABS["random"]`, fixture/sha каталога; baseline переиздан. |
| `tools/_qrng_p4_reissue_f8.py` | Переиздание F8-baseline/sha (без изменения REGISTRY/delta). |
| `tools/ui_qrng_p4_e2e.py` | Playwright e2e на реальных ассетах и API-стабах. |

## 2. Честные отклонения / ограничения

1. **`services/param_catalog.py` всё же изменён.** Стартовое ограничение
   запрещало трогать P3-файлы, но контракт P4 прямо требует `TAB_RULES +1=23`,
   `TAB_NAV` и перенос групп; без этого вкладка не существует и пины
   `test_frontend_tab_mapping`/`test_round1025_f8_registry` не проходят.
   Изменение минимальное и аддитивное: определения вкладки + перенос двух
   groups; P3 selector/resolution, `mca_random_source.py`, `config_cache.py`,
   `status_service.py`, `routes.py` НЕ изменялись.
2. **LfDR «Проверить подключение» — disabled с честной подписью.** В
   действующем backend есть только `POST /api/random/test` (ANU draft-key);
   провайдер-агностичного маршрута нет, новые endpoint'ы запрещены. Кнопка не
   имитирует проверку; карточка показывает `configured`/`consumable`/
   `quarantined` из `/api/status`. Требование к backend: отдельный read-only
   LfDR-проба (кандидат в P5) — не блокирует остальной UI.
3. **B3-история `oversight:random.uses`** в этой базе ещё не объявлена в
   `HISTORY_SOURCES` (её добавляет release-линия B3). Строка
   `WORKSPACE_TABS.mod_random` уже B3-совместима; на этой базе вкладка
   «История» честно не рендерится (`historyIsReady=false`), после merge B3 —
   заработает без правок P4.
4. **Browser Use недоступен (проверено повторно 2026-11-18):**
   `BU_CDP_URL=http://127.0.0.1:9222` — connection refused (dedicated
   automation Chrome не запущен). Обязательный визуальный контур выполнен
   Playwright/Chromium (реальные `index.html`/`app.js`/CSS).
5. **Скриншоты не сохранены** (бинарные файлы не нужны для приёмки); вместо
   них — измеренные метрики viewport в `playwright-e2e.json`.
6. **Полный `tests/test_webapp_*.py` не запускался** по указанию родителя
   (перезаписывает tracked W10–W12 evidence-блобы). `git status` после
   прогонов не содержит изменённых evidence-блобов.

### 2.1. Review F1–F5 (2026-11-18)

1. **F1 — Sleep-карточка.** Причина: блок жил под `activeModule`
   (`openModuleId`), который рабочий UI не выставляет. Разметка вынесена в
   ОДИН компонент `random-entry-card` (шаблон `#random-entry-card-tpl`);
   workspace-вход рендерится по `workspaceModule.id === 'mod_sleep'` на
   overview/settings, legacy-модалка использует тот же компонент. e2e:
   deep link `#/modules/sleep` и переход из каталога → карточка видима, ссылка
   ведёт на `#/modules/random`.
2. **F2 — e2e CSS/статус.** MIME исправлен (`text/css`, `font/woff2`,
   `application/javascript`); e2e проверяет `document.styleSheets`:
   `cssRules=2143`, `stateFont=12px` (иначе FAIL). Status stub больше не эхо
   primary: IBM `configured=false`; effective — первый доступный (ANU при
   key/reserve), иначе PRNG/deferred. Добавлены `ibm_not_green`,
   `effective_not_primary_echo`, 422-ветка и `no_fake_default` при disabled.
3. **F3 — fallback-стрелки.** Label+actions разведены в non-wrapping группы;
   на 390 и 320 стрелки в одной строке с провайдером (`arrowsAttached=true`,
   `scrollWidth=vw`), тип скрыт только на узком экране.
4. **F4 — ложный factory-default.** При `random.enabled=false` сводка больше
   не печатает «заводское значение»: только сохранённый raw или «нет данных»
   (e2e `off_no_fake_default`).
5. **F5 — test-gap.** `round1025_f5_workspace_route_test.js` для mod_random
   сверяет ПОЛНОЕ множество ключей страницы с каталог-фикстурой
   `tests/fixtures/qrng_p4_random_keys.json` (группы memory_random/keys_random,
   hidden и read-only master исключены). Новый ключ без страницы/фикстуры
   краснит тест.

## 3. Визуальный контракт (Visual Preservation Map)

- Шапка модуля (`workspace-head`), breadcrumb, tri-state, warning и кнопки
  сохранены; добавлены 3 честных чипа «Основной (настройка) / Сейчас
  используется / Квантовый запас» из runtime diagnostics, зелёный — только при
  подтверждённом quantum.
- `keys_random` перенесён (не скопирован): на `#/ai/llm` 0
  `[data-cfg-key^="keys.random"]`; группа больше не приходит с сервера.
- «Время ответа и защита» — последняя группа; поля/значения 180/360 не
  менялись.
- Карточка-вход «Случайность и источники» на «Сне» — один компонент на
  workspace-странице (overview/settings) и в legacy-модалке; чипы
  selected/effective/причина сохранены, ссылка ведёт на `#/modules/random`.
- Mobile 390/320: одна колонка, `scrollWidth=vw`, шрифт карточек 16px (≥12px),
  fallback-стрелки в строке своего провайдера.

## 4. Проверка (фактические результаты)

См. `tests-p4.json` (машиночитаемо) и `playwright-e2e.json`.

- P3 — 51/51; P1 — 29/29; P2 — 63/63.
- random/QND батч — 310/310.
- mandatory 386 — 386/386.
- JS full — 118 passed / 4 pre-existing failing (те же на базе).
- catalog guards — 45/1 (pre-existing dead knob).
- счётчиковые пины (help/decision/image/budget) — 244/244.
- Playwright — 35/35 проверок, `ok=true`, page_errors=[]; CSS реально
  применён (`cssRules=2143`, `stateFont=12px`), 1280/390/320.
- RED на `6cf4c32c`: новый тест падает (`вкладок 29 (28 + mod_random)`);
  подтверждены три факта базы (нет вкладки, `keys_random` на LLM, старая
  подсказка). `red-probe-6cf4c32c.json`.
- Мутации UI — 10/10 (`mutations.json`); e2e-мутации — 4/4
  (`mutations-e2e.json`: octet-stream CSS, IBM-зелёный stub, удалённая
  Sleep-карточка, оторванные стрелки). Все файлы восстановлены по sha256.

## 5. Что осталось непокрытым

- Живая LfDR-проверка соединения (нет backend-маршрута; см. §2.2).
- Живой прогон ANU/IBM/LfDR и production effective-state — после деплоя
  (P5/релизная приёмка), не заявляется здесь.
- Скриншот-ревью на реальном TMA-клиенте — после деплоя; локальный Playwright
  на реальных ассетах выполнен.
- B3-history merge: проверить в релизном поезде, что
  `HISTORY_SOURCES['oversight:random.uses']` и `WORKSPACE_TABS.mod_random`
  сходятся без конфликта. **F6:** наша запись `WORKSPACE_TABS.mod_random`
  дублирует B3 (строки 832/852 merged); при сборке поезда удалить НАШУ строку
  в пользу B3, не перестраивая B3-код. Конфликты
  `param-registry-round1025.meta.md` и history-теста также разрешаются на
  сборке, в этой ветке не трогаются.
- F7 (опционально, non-blocking): IBM-карточка на 1280 имеет ту же высоту
  grid-ряда, что ANU/LfDR (`card_heights_1280` в `playwright-e2e.json`);
  отдельная правка не требуется.
