# ASAP 8 F4 — Exact prompt UX (C5/C6/C7) + REV-F3 хвосты (отчёт Builder-лейна F4)

Базовый HEAD: `2e145a4` (2.58.76, F5 закоммичен). Кандидат в рабочем дереве,
НЕ закоммичен (после Reviewer). Зависимость F3 (`a12e6bf`) соблюдена:
`compile_style_prompt` НЕ менялся — только вызов.

## 1. Latest-mode auto-load (§4.1, C5) — server-side resolve

Новый **`GET /api/analytics/pipeline/runs/latest`** (`web/api/analytics.py`,
зарегистрирован ДО параметрического `/runs/{run_id}` — иначе FastAPI съел бы
`latest` как run_id; тест-пин на порядок маршрутов в новом файле):

* RBAC: `requires_global_admin()` — fail-closed 403, идентично drill-down;
* latest run_id резолвится **той же сортировкой, что список инспектора**:
  `pa.collect_runs_list(db, limit=1)` (SUMMARY_RUN_DONE `ts DESC, id DESC`,
  dedup по run_id); потом `pa.collect_run(db, rid)`;
* `?include_prompt=true` → `cover_prompts` + `cover_prompts_status`
  (top-level и внутри `cover_prompts`); без параметра — оба ключа
  отсутствуют (прежний R17-safe контракт, тест);
* нет run'ов/ошибка чтения → fail-open `{"run": None}` без ошибок.

Клиент (`web/app.js::loadPipelineInspector`): в режиме «Последний запуск»
(пустой `pipelineSelectedRunId`) и при начальной загрузке/поллинге — прямой
вызов `/runs/latest?include_prompt=true` (§28.7 — никакого скрытого
extra-click). `pipelineData.run` подменяется run'ом из latest-ответа —
карточка прогона и промпты гарантированно про ОДИН run (нет рассинхрона
`collect_latest` vs список). Не-глобал latest-endpoint **не вызывает**
(403 fail-closed без спама в 15-секундном поллинге). `setPipelineMode`
изменений не требует — делегирует в `loadPipelineInspector`.

## 2. Missing manifest → явная причина (§4.2, C6)

`load_run_cover_prompts` (services/cover_style_jobs.py — ТОЛЬКО reader,
F3-компилятор не тронут) возвращает, помимо манифестов,
`cover_prompts_status: {base, style}`:

| код | условие (детерминированное, по durable-артефактам) |
|---|---|
| `ok` | манифест найден |
| `base_manifest_missing` | modern-run без Base-манифеста (kind=cover_base) |
| `style_job_not_linked` | Base есть, Style-джобы для run нет |
| `style_job_failed` | Style-джоба есть (coalesce_key), `prompt_manifest` в state нет |
| `legacy_run` | нет ни Base-манифеста, ни Style-джобы (прогон до эпохи манифестов; absent/legacy по этим артефактам неразличимы — честный общий код) |

Degenerate-ветка (нет БД/run_id) возвращает прежний `{"base": None,
"style": None}` БЕЗ status-ключей (нечего определять). Оба
analytics-endpoint'а дублируют статус top-level. R17: reader не логирует
тексты; статус — enum-коды.

UI: блок «Фактический промпт» для global admin **виден всегда** (пока
показан run — блок и так внутри `v-if="pipelineRunView"`);
`pipelineCoverPromptsVisible` больше не гаснет по отсутствию манифестов.
Новые computed/methods: `pipelineCoverPromptsStatus` (top-level или вложенный
источник), `pipelineCoverPromptStatusRu` (RU-карта пяти кодов, unknown-код —
fallback как есть), `pipelineCoverPromptMissingRows` — построчно
«Базовая обложка (Base): фактический промпт недоступен — манифест Base не
 найден» (§28.8). Частичный кейс (Base ok, Style not linked) показывает
манифест Base + одну reason-строку.

## 3. Preview-compile v2 (§4.3, C7)

`POST /api/cover/preview-compile` + параметр **`mode: "base"|"style"`
(default `base` — полная обратная совместимость; invalid → 422;
`mode` добавлен в оба ответа для симметрии)**.

`mode="style"` (web/api/cover_styles.py::_preview_compile_style):

* **Тот же server compiler**: `jobs.compile_style_prompt` (F3-контракт:
  preservation + runtime + story identity + instruction профиля + refs +
  base_style) — JS-дубликата нет (§28.9);
* **Тот же лимит-резолвер и budget**: `resolve_generate_prompt_limit_async`
  + `_budget` — переиспользованы, не продублированы; capabilities для
  компилятора строятся из того же резолва (`PromptLimit(value, unit,
  source)`), unknown → сборка без cap с честным `resolved_limit=null`;
* base_style = draft.instruction (textarea «Стиль обложки» = production
  `base_style_prompt`); фолбэк на profile.instruction здесь НЕ делается
  (это другой компонент P1 — было бы фейком), пусто → честный
  `style_source="empty"`;
* профиль — детерминированный резолв с честным источником: явный
  `profile_id` → per-chat выбор (`resolve_selected_style_id` — ТОТ ЖЕ
  резолв, что production Style-стадия, DC-5) → первый enabled; ни одного →
  честный `no_profile` placeholder;
* контекст — тот же `_resolve_preview_context` (свои test-прогоны, R17);
  нет контекста / пустая статья → честный placeholder «Контекст
  недоступен…» + reserved budget (паттерн Base-placeholder §9.4), БЕЗ
  фейкового final prompt;
* ответ ok: `style_source`, `profile_source`/`profile_id`, `context`,
  `manifest` (единый `cpa.build_style_manifest` — sent/trimmed/omitted по
  факту, `route="preview_compile"`), `final_prompt`, `budget`,
  **`style_publish_skip_reason`** (F3 fail-soft: `prompt_limit_exceeded` /
  `story_identity_dropped` → UI честно пишет «в проде будет Base»),
  `exceeded`/`compile_reason`;
* compile-only: изображение не генерируется, платных вызовов нет, номер
  выпуска не расходуется. R17: exact-текст только в global-admin ответе.

Страница «ИИ → Промпты → Стиль обложки» (web/index.html, generic-карточка
ключа `prompts.summary_cover_style`): под raw textarea — server-compiled
preview блок (только `isGlobalAdmin`): переключатель стадий **Style Edit /
Base** (один endpoint, оба режима C7), test-контекст (accessChats, 0 = без
контекста), meta-строка (источник стиля / профиль / контекст / маршрут),
exact compiled prompt + копировать, таблица компонент (тот же рендер, что
Cover Style Editor: `coverManifestSourceLabel/StatusText/StatusClass/
ReasonText` — переиспользованы), budget-строка (общий
`coverCompileBudgetText(result)` — хелперы обобщены опциональным
аргументом, поведение прежнее). `promptStylePreview` — топ-уровень data
(страница «Промпты» не зависит от загрузки Cover Style Editor).

## 4. REV-F3 хвосты

a. `coverManifestSourceLabel`: + `CONTENT_PRESERVATION: 'Инвариант
   сохранения сюжета'` (JS-тест).
b. CSS: `gap-x-4`/`gap-y-1` отсутствовали в prebuilt
   `vendor/tailwind.css` (build отстал от разметки; zero-build/CSP —
   компиляции нет, конфиг `tailwind.config.js` предполагает ручной
   rebuild). Минимальный фикс — ровно 2 утилиты в `web/static/app.css`
   (подключается ПОСЛЕ tailwind.css, значения Tailwind-канона:
   column-gap 1rem / row-gap 0.25rem). Playwright-проверка computed
   `column-gap: 16px` на embeddings-панели; структурный тест на наличие
   классов.

## 5. Тесты

Новый **tests/test_asap8_f4_prompt_truth.py** — 18
(TEST-LIFECYCLE: CONTRACT/REGRESSION owner=ASAP8/F4; маркер `asap4` —
prod-дефолт pipeline-events):

* C6 status-модель reader'а: both-ok / base_missing+style_not_linked /
  style_job_failed (linked без манифеста) / legacy_run — 4;
* C5 latest endpoint: 401 / 403 не-глобал (модератор + без роли, промптов
  нет в тексте) / сортировка = список инспектора (run-new, чужой exact-текст
  не утекает) / без include_prompt — ключей нет / нет run'ов → честный
  пустой ответ — 5;
* C7 preview-compile style: 422 invalid mode / 403 не-глобал (R17) /
  no_context placeholder + reserved budget / no_profile / **parity с
  прямым `compile_style_prompt`** (final_prompt байт-в-байт, preservation
  + story + base_style kept, attempt sent, skip_reason None) / overflow
  (лимит 200) → `style_publish_skip_reason="prompt_limit_exceeded"` +
  attempt failed + base_style omitted / default mode=base back-compat — 7;
* хвосты: gap-утилиты в app.css (ровно 2) / порядок регистрации
  latest-маршрута — 2.

`tests/js/asap7_f8_cover_prompts_test.js` — расширен: рендер-гейт F4
(admin → блок виден всегда; не-глобал → скрыт), RU-причины всех C6-кодов +
частичный кейс, latest-режим loader'а (admin → вызов
`/runs/latest?include_prompt=true`, run-карточка = latest-деталь; не-глобал
→ вызова нет; ошибка сети → честная пустота), статус top-level сохраняется,
`coverManifestSourceLabel(CONTENT_PRESERVATION)` → RU, `promptStylePreview
Compile` (mode=style + draft=значение редактора; mode=base + context) —
запуск `node` OK; `test_asap7_cover_readpath.py::test_js_unit_f8_cover_
prompts` OK.

Обновлённые пины (2, осознанно — контракт F4 изменил форму ответа reader'а):
`test_asap7_cover_readpath.py::test_reader_fail_open` (absent-run →
legacy_run статусы; degenerate-ветка прежняя) и
`::test_include_prompt_absent_run_honest_empty` (+ top-level статус).

## 6. Прогоны (финальное дерево)

* новый файл + смежные: `test_asap8_f4_prompt_truth.py` +
  `test_asap7_cover_readpath.py` + `test_asap7_cover_preview.py` +
  `test_asap5_cover_manifest_web.py` + `test_extra_cover_styles_api.py` →
  **81 passed**;
* фокус cover-сweep (как в F3 + F4): asap44_closure, asap5 manifest/web,
  extra_cover_style_jobs, wave_b_asap4, readpath, cover_fix, cover_preview,
  asap43, cover_styles_contract, wave_f_asap41, asap42_step3,
  asap8_f3, asap8_f4 → **265 passed**;
* analytics/pipeline: webapp_analytics_api + pipeline_analytics_asap4 +
  zone_g_asap41 + extra_cover_style_pipeline → 118 + 45 passed;
* routes-freeze (f8_registry/mca12/mca17c) → 59 passed (аддитивный
  endpoint в analytics_router пин не трогает — прецедент MCA-23/F8);
* JS: asap7_f8 / asap5_cover_manifest / asap7_f7_cover_compile — OK;
  `node --check web/app.js` OK; test_webapp_js_unit 38 passed;
  test_asap7_module_completeness 16 passed.

## 7. UI-проверка (Playwright + Browser Use)

**Playwright** (детерминированные flow-пробы, route-stub по образцу
ui_round1025_matrix; scratch `f4_ui_checks.py`): **30/30 PASS**,
0 console errors на всех сценариях:

* C5 (desktop 1280×800): блок «Фактический промпт» появляется в режиме
  «Последний запуск» БЕЗ клика по run-строке; exact Base+Style тексты,
  обе попытки Style, карточка прогона = latest-деталь; ok-статус — без
  reason-строк;
* C6: block виден без манифестов; RU-причины base_manifest_missing и
  style_job_failed отрендерены;
* C7: preview-блок виден; no_context → «Контекст недоступен» + reserved
  budget («Резерв: сцена ≥160 · контекст ≤400 (SUMMARY_CONTEXT_MAX_CHARS)») и БЕЗ фейкового final
  prompt; введённый в textarea текст уходит в `draft.instruction`;
  `mode=style`/`mode=base` в телах запросов; exact compiled == ответ
  сервера (JS-сборки нет); meta (источники + preview_compile);
* хвост b: computed `column-gap: 16px` на `.gap-x-4`
  (embeddings-панель, memory-вкладка);
* mobile 390×844: auto-load промптов, частичная причина
  style_job_not_linked, preview-блок в границах вьюпорта, нет
  горизонтального overflow, 0 console errors.
  Скриншоты — в scratch (`f4_desktop_inspector_ok/missing.png`,
  `f4_desktop_prompts_*.png`, `f4_mobile_*.png`).

**Browser Use** (реальный рендер, stub-сервер server-side
`f4_bu_server.py`; сценарий через `?f4scenario=` → Referer): инспектор
ok/missing/partial — exact-промпты и причины видны; страница «Промпты» —
honest placeholder + reserved budget, style-ok exact compiled + meta,
переключение mode=base; визуальный осмотр скриншотами desktop + mobile
390 (Эмуляция CDP): блоки читаемы, без overflow, кнопки/таблица на месте.

Попутный фикс во время UI-прогона: `promptStylePreview` изначально был
вложен в `coverStyles` в data → render-ошибка «Cannot read properties of
undefined (reading 'mode')» на странице Промптов — перенесён на
топ-уровень data (до UI-каналов, покрыто Playwright/BU).

## 8. Файлы

* `web/api/analytics.py` — latest endpoint (+top-level статус в drill-down);
* `web/api/cover_styles.py` — mode в body/ответах, `_resolve_style_preview
  _profile`, `_style_preview_placeholder`, `_preview_compile_style`;
* `services/cover_style_jobs.py` — ТОЛЬКО reader `load_run_cover_prompts`
  (+status-поля, docstring);
* `web/app.js` — loader (latest-ветка, статус в drill-down), computed
  (visible/status/missingRows), methods (StatusRu, promptStylePreview*),
  обобщение coverCompileFinalText/BudgetText, состояние promptStylePreview;
* `web/index.html` — reason-строки в блоке «Фактический промпт»; preview
  блок «Стиль обложки» на странице Промптов;
* `web/static/app.css` — ровно 2 gap-утилиты;
* `tests/test_asap8_f4_prompt_truth.py` — НОВЫЙ (18);
* `tests/js/asap7_f8_cover_prompts_test.js` — расширен;
* `tests/test_asap7_cover_readpath.py` — 2 осознанных пина (форма reader'а).

ΔDDL = 0. Секретов нет (R17: exact-промпты только в global-admin
поверхностях, в логи не пишутся; status — enum-коды). DO_NOT_TOUCH
соблюдено: F3-компилятор не менялся (только вызов), F5-зона не переоткрыта.

## 9. Инцидентальные находки

* `related-nonblocking`: на странице Промптов при V2 OFF («ИИ → Промпты»,
  аккордеонная раскладка) generic-карточка `sec.advanced` рендерит
  `prompts.summary_cover_style` второй раз (promptVisibleItems уже включает
  ключ) — дублирование карточки существовало до F4; preview-блок при этом
  добавлен только в основную сетку. В зону F6/вёрстки.
* `unrelated/pre-existing`: `/api/config`-стаб матрицы подтверждает
  рендер 559 items без ошибок; дефектов вокруг изменённых зон не видно.
* Неопределённостей, блокирующих релиз, нет. Live-проверка на проде
  (реальные манифесты) — owner/post-deploy evidence волны (как для F3).
