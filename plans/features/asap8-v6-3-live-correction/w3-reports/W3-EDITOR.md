# W3-EDITOR — B05 (дрожащий редактор обложек) + U06 (Style editor — рабочий инструмент)

Полоса W3-EDITOR, фича `asap8-v6-3-live-correction`. Коммит НЕ делался (по брифу).
HEAD на момент работы: d6366e3 (Wave 2 закоммичена).

## 1. Реализации

### B05.1 — неподвижный непрозрачный фон редактора (CORR-1-совместимо)

- `web/static/app.css` (блок `/* ═══ W3-EDITOR ═══ */`, append 217 строк):
  `.cover-editor { background: var(--surface-1, #151B2A) }` — непрозрачная
  ЛОКАЛЬНАЯ поверхность контейнера редактора (дизайн-токен). Глобальный
  полигональный фон production не тронут (CORR-1): canvas/polygon-rendering
  stack без изменений; декоративный фон остаётся только ВНЕ рабочей области,
  за rgba-оверлеем.
- Секции редактора — solid-карточки `--surface-0` + `--surface-border`
  (Tier C по U08.4: «Style Editor и forms — Tier C без динамического
  refraction на textarea и selection»). Никакого стекла/refraction на
  textarea и «Фактическом промпте».
- `prefers-reduced-motion`: страхующее правило `animation/transition: none`
  внутри редактора; сам polygon-canvas уже останавливает rAF (проверено
  диагностику: `__PolygonBackground.getDiagnostics().frameCount` заморожен).

### B05.2 — данные и редактируемый state разделены; выделение/копирование непрерывны

- **RCA (REQ-B05-SYM)**: таймера, дёргающего `coverStyles.current`/`key`
  при вводе, в текущем master НЕТ (устранён в более ранних рефакторах
  ASAP 4.3 — трассировка по коду + Playwright-пруф: при активном polling
  test-style job (1.5 c цикл, завершение в окне наблюдения) удержание
  выделения 13 c — `selectionStart/End`, выделенная строка, `scrollTop`,
  DOM-идентичность textarea и pre неизменны; Playwright-пруф в e2e).
- Остававшийся канал порчи draft устранён: `coverStyleLoadMeta` раньше
  писал серверные метаданные (`references`, `preview_*`, `can_edit`,
  `next_issue_number`) прямо в `st.current` (редактируемый draft).
  Введён серверный снимок `coverStyles.server`
  (`_coverServerSnapshot`); фетч-ответы обновляют ТОЛЬКО `st.server` +
  `st.meta`; dirty draft (`st.current`) фетчи не трогают. Шаблон читает
  refs/preview/can_edit через `coverServer(prop, fallback)`.
- `next_issue_number`: meta-sync сохранён (контракт ASAP 4.4, тест
  asap44), но при `editorDirty` поле ввода не перетирается — синк идёт
  в `server.next_issue_number`.
- Попутный дефект (тот же слой, необходим для U06 «фактические limit»):
  `coverStyleLoadMeta` не клал `prompt_limit` в `st.meta`, поэтому
  `coverLimitText()` всегда показывал «неизвестно». Исправлено —
  «Лимит текущей модели: 800 символов (лимит провайдера)» теперь
  отображается из server state.
- Copy-кнопки копируют точную строку (`copyText(coverCompileFinalText())`,
  clipboard == pre-текст — Playwright clipboard-read проверка).
- `coverStyleSave`/`coverStylePreview` — права `can_edit` из серверного
  снимка (draft не источник прав).

### B05.3 — модалка 100dvh, один скроллер, guard, save contract

- `.cover-overlay` (mobile <640): `height: 100vh → 100dvh` (fallback);
  `overscroll-behavior: contain`. `html.cover-editor-open { overflow:hidden }`
  (ставит watch `coverStyles.editorOpen`) — no behind-overlay scroll
  (Playwright: wheel за пределом тела не двигает document/main.scroll-area).
- Единственный скроллер `.cover-editor-body` (было, сохранено); шапка/футер
  несжимаемые, safe-area один раз (foot-формула прежняя).
- **Guard закрытия**: `coverStyleEditorClose` при `editorDirty` открывает
  in-DOM alertdialog (`data-cover-guard`, Telegram WebView-совместимый):
  «Продолжить редактирование» (cancel — текст цел) / «Закрыть без
  сохранения» (confirm). Чистый редактор закрывается без диалога. Обе
  кнопки («← Закрыть» head, «Закрыть» foot) проходят guard.
- Save contract не изменён: POST `/api/cover/styles` с тем же телом
  (Playwright фиксирует тело стаба: те же ключи, instruction из draft).

### U06.1 — структура/порядок рабочего инструмента

Новый порядок `cover-editor-body` (index.html, секции с маркерами):
`data-cover-sec-profile` (название, режим, «Стиль активен», нумерация) →
`data-cover-sec-instruction` (редактируемая инструкция, бюджет, компактный
limit-selector в одну строку) → `data-cover-sec-refs` →
`data-cover-sec-compile` («Проверка итогового промпта», admin) →
`data-cover-sec-testedit` (before/after, «Проверить стиль», прогресс, stale)
→ `data-cover-sec-result` (результат/история + манифест) →
`data-cover-sec-more` («Подробнее» = `<details>`: «Модель и подключение»,
capability-линии). Разработческие метаданные — под «Подробнее».

### U06.2 — «Фактическая сборка» из edit_report (W1 API)

- Одна строка `Style N · SceneAnchor M · Refs R · System S · Final F /
  Limit L` (`coverEditSummaryLine`) — источники: `manifest.components`
  (STYLE_PROFILE/REFERENCES/CONTENT_PRESERVATION+RUNTIME_INVARIANTS
  sent_chars) + `edit_report` (scene_anchor.chars, final_prompt_chars,
  limit_value/unit). Цвет ТОЛЬКО при превышении (`.cover-limit-over`,
  `coverEditOverLimit`); при норме — нейтральный цвет, никакого зелёного
  «успеха».
- Точный промпт — моноширинный `pre.cover-prompt-pre` (max-height 16rem,
  overflow auto, непрозрачная подложка) + кнопка «Копировать» (exact
  string).
- `data-cover-compile-details` «Подробнее о сборке (edit_report)»:
  язык, headroom preflight, image_input_used, dropped+reason,
  semantic dedupe, limited_preview («ограниченный preview — провайдер
  не вызывался»).
- `prompt_limit_unknown`: строка `Final F / неизвестно`, честная строка
  «Лимит: неизвестно — провайдер не сообщил лимит» в деталях, без
  псевдоцвета (Playwright-сценарий).

### U06.3 — не сломано

- version-conflict guard/сохранение профиля/references/загрузка asset:
  эндпоинты и контракты тел не менялись (backend `web/api/cover_styles.py`
  и `services/cover_style_jobs.py` — 0 diff). JS canon-пины
  (asap42/43/44/5/7f7/7f8) зелёные.
- `prompt_limit_unknown` — псевдоуспеха нет (тест выше).

## 2. Тесты

- **Новый**: `tools/ui_asap8_w3_editor_e2e.py` — Playwright e2e
  (`--phase before|after`), TEST-LIFECYCLE: CONTRACT owner=REQ-B05/REQ-U06.
  RED-фаза: 27 passed / 9 failed (guard отсутствовал, порядок/сборка/скролл-pre/overscroll).
  GREEN-фаза: **40/40 passed** — выделение 13 c при активном polling,
  DOM-идентичность, copy==exact, dirty-draft защита, guard-цикл,
  save contract, 100dvh/скроллеры/safe-area, порядок секций,
  сборка/цвет/лимит-unknown, reduced-motion (frameCount заморожен),
  320px без overflow. Скриншоты before/after desktop+mobile+guard+320.
- **Re-pin канон-тестов** (поведение сохранено/усилено, канон U06.1 новее):
  - `tests/js/asap43_cover_style_surgical_test.js` — editor before/after
    читает `coverStyles.server` (B05.2 разделение данных/draft).
  - `tests/js/asap44_cover_final_closure_test.js` — meta-sync
    next_issue_number сохранён (+guard dirty в реализации).
  - `tests/js/asap7_f7_cover_compile_test.js` — зона compile ПОСЛЕ
    референсов (порядок U06.1 ТЗ v6.3 приоритетнее старого пина
    «до референсов»), заголовок «Проверка итогового промпта».
- Регрессия: asap42/43/44/5_manifest/5_decision_trace/7_f7/7_f8,
  asap31, asap6_wave2, w2_shell/w2_fullscreen js-пины — зелёные;
  pytest `test_extra_cover_styles_ui.py` + `test_asap42_step2c2_miniapp_seeds.py`
  — 28 passed. Python-бэкенд не тронут.

## 3. Checklist-гейт (секционная дисциплина Wave 3)

- Мой diff в `web/index.html` — ханки ТОЛЬКО в блоке cover-editor
  (~строки 906–1427). Чужие ханки в общем worktree-диффе
  (~5774, ~7058–7199 — «Мониторинг интеллекта»/«Сон»/U04) принадлежат
  параллельной полосе **W3-STATUS** (их маркеры «U03 (v6.3 W3-STATUS)»,
  «U04 (v6.3)» в коде) — мною не тронуты.
- Маркеры W3-STATUS на месте: `id="status-logs"` (card Статуса,
  ~строка 7905) присутствует.
- `web/static/app.css` — только append-блок `/* ═══ W3-EDITOR ═══ */`
  (217 вставок, 0 удалений).
- `web/app.js` — только cover-editor логика (state/open/close/guard/
  loadMeta/save/preview/compile-хелперы/лейбл SCENE_ANCHOR/watcher);
  остальные ханки app.js в worktree — W3-STATUS (U03/U04), без пересечений.
- Backend (`web/api/cover_styles.py`, `services/cover_style_jobs.py`) —
  0 diff (polling-разделение решено на фронте; W1 API использован как есть).

## 4. Evidence

`plans/features/asap8-v6-3-live-correction/w3-evidence-editor/`:
- `w3_editor_e2e_before.json` (RED: 27/9), `w3_editor_e2e_after.json` (40/40);
- before/after скриншоты: desktop top/compile/guard, mobile 390 top/bottom,
  mobile 320;
- визуальная инспекция: solid-фон, порядок секций, строка сборки
  `Style 250 · SceneAnchor 88 · Refs 62 · System 180 · Final … / 800 символов`,
  mono-pre + копирование, guard-диалог, футер/шапка закреплены.

## 5. PENDING-live (вне возможностей агента)

- Реальный Telegram WebView (Android/Desktop): 100dvh при раскрытой
  клавиатуре и поведение native safe-area — Playwright-мок не заменяет
  живой клиент (V-проверка Wave 4).
- Реальный preview-compile на живом профиле владельца (платный вызов) —
  форма edit_report покрыта стабом байт-в-байт по W1-контракту.

## 6. Incidental findings

- `related-nonblocking` (моя полоса, исправлено): `coverLimitText` всегда
  «неизвестно» — `prompt_limit` терялся в `st.meta`.
- `unrelated/pre-existing-in-flight`: `tests/js/asap8_d1213_save_contract_test.js`
  падает — `scrollToSleepWidget` удалён в секции «Мониторинг интеллекта»
  параллельной полосой W3-STATUS (их незавершённая правка sleep-бейджей
  U03; HEAD содержал 2 вхождения). Не мой регион; W3-STATUS должно
  закрыть пин при завершении полосы.
- Мелочь видимости: строка SceneAnchor в таблице компонент показывала
  сырой `summary_stage1` — добавлен лейбл «Якорь сюжета»
  (`coverManifestSourceLabel`).
