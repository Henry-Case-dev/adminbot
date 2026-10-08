# F8 — Cover exact-prompt read path (Wave 1, первый слайс Cover-лейна)

- Дата: 09.10.2026. База: HEAD `08a8849` (shared worktree master; незакоммиченный
  шум и in-flight правки параллельных лейнов F3/F5 не тронуты — см. «Соседние лейны»).
- Контракт: architecture.md §2.5 (read path прозрачности), §2.6 (F8 идёт первым),
  §5.1 (freeze app.js: SECTION-COVER-RUNS). Audit-cover.md: production-читателей
  манифестов не было; Run Inspector исключал промпты; UI показывал только char counts.

## 1. Изменения (file:line)

### API — `web/api/analytics.py`
- `:621` `GET /api/analytics/pipeline/runs/{run_id}` + query-параметр
  `include_prompt: bool = Query(default=False)` (endpoint СУЩЕСТВУЮЩИЙ, путь не менялся).
- `:645-655` при `include_prompt=true` — `cover_prompts` из нового читателя
  `cover_style_jobs.load_run_cover_prompts`; fail-open (ошибка чтения →
  `cover_prompts=null`, warn без текстов промптов в логе, R17).
- **RBAC не тронут**: `requires_global_admin()` на endpoint — не-глобал получает
  403 ДО любого чтения (fail-closed). Без `include_prompt` — прежний R17-safe
  ответ, ключа `cover_prompts` в JSON нет вообще (analytics.py:616-636 не ослаблялись).
- **Δ routes = 0**: routes.py не менялся → `ROUTES_SHA256_F11` re-pin НЕ требуется
  (прецедент MCA-23 «аддитивный endpoint в analytics.py — пин цел»; здесь даже
  endpoint не добавлялся).

### Reader — `services/cover_style_jobs.py` (только чтение; запись не менялась)
- `:1328` `async load_run_cover_prompts(db, run_id) -> {"base": m|None, "style": m|None}`:
  Base = `load_base_cover_manifest` (task_jobs kind=cover_base, детерминированный
  ключ от run_id); Style = durable `state.prompt_manifest` production Style-Edit,
  поиск по `coalesce_key='cover_style:<run_id>'` (тот же путь, что
  `_cover_job_fallback` в pipeline_analytics.py:1601-1610). Fail-open, полный
  prompt отдаётся только admin-authorized вызывающему. `:2175` — добавлен в `__all__`.

### UI — Run Inspector (SECTION-COVER-RUNS только)
- `web/index.html:4431-4475` блок «Фактический промпт» (`#pipeline-cover-prompts`)
  сразу после карточки «Обложка и стиль» (Run Inspector-регион :4186-4440+;
  чужие регионы index.html не тронуты). На каждую группу Base/Style: provider·model·route,
  hash, каждая попытка (№, chars, кнопка «копировать» → существующий `copyText`,
  exact-текст в `<pre>`), «Итог: N симв. · лимит: X (source)»,
  machine reason попыток — только в свёрнутом `<details>` (developer details).
- `web/app.js:3602-3660` computed `pipelineCoverPrompts / pipelineCoverPromptsVisible /
  pipelineCoverPromptGroups`; `:5460-5476` `loadPipelineInspector` — drill-down
  добавляет `?include_prompt=true` ТОЛЬКО при `isGlobalAdminEffective`
  (не-глобал ходит по прежнему safe-URL); `:5490-5506` helpers
  `pipelineCoverPromptMeta / pipelineCoverAttemptReason` (методы, не computed —
  урок H-ASAP31-2). Render-гейт: admin И фактические данные; нет манифестов —
  блок скрыт (не «пусто»).

### Тесты (новые, `TEST-LIFECYCLE: CONTRACT owner=asap7/F8`)
- `tests/test_asap7_cover_readpath.py` — 12 тестов:
  - инвариант §2.6.3 **manifest.final_prompt == фактически отправленный prompt**:
    Base — durable-артефакт media job (coalesce_key с prompt_hash отправленного
    prompt; полный текст media job сознательно не хранит, R17) пересчитан из
    манифеста и сверен байт-в-байт; Style — `run_style_job` (production-паттерн
    begin_cover_job+state) с fake edit_call: durable `state.prompt_manifest`
    == фактически отправленные строки (attempts + final + hash + chars);
  - R17: 401 без initData; 403 (юзер без роли И модератор) при include_prompt=true;
    без include_prompt — «cover_prompts»/exact-текста нет в ответе даже у админа;
    админ+include_prompt — exact Base-манифест + честный `style:null`; absent run —
    `{"base":null,"style":null}`;
  - UI-контракт: нодовый тест `tests/js/asap7_f8_cover_prompts_test.js`
    (реальное поведение: computed-гейт admin+данные, loader include_prompt только
    у global admin, зоны/секреты) подключён pytest-ом; статические проверки блока.

## 2. Проверка (PASS-эвиденс)

| Проверка | Результат |
|---|---|
| `pytest tests/test_asap7_cover_readpath.py -x -q` | **12 passed** |
| Соседи analytics/cover read: test_pipeline_analytics_asap4 + test_asap5_cover_prompt_manifest + test_summary_publish_integration_round1026 + test_extra_cover_style_pipeline + test_extra_cover_styles_ui | **207/208 passed**; единственный RED `test_catalog_zero_delta` (ожидал REGISTRY 529, факт 538) — in-flight каталог F3 (param_catalog.py не мой файл), не мой diff |
| `node --check web/app.js` | OK |
| `node tests/js/asap7_f8_cover_prompts_test.js` | ASAP7-F8-COVER-PROMPTS-OK |
| test_round1025_f8_registry (routes-пин/каталог) | 9 RED — **все по in-flight F3** (routes.py +8 строк module_registry, param_catalog 529→538 — не мои файлы; до F3-правок эти же тесты зелёные); routes-pin-часть к моему diff отношения не имеет, мой вклад в routes.py = 0 байт |

### Playwright (реальный браузер, реальный код)
- Прод-Vue-компилятор компилирует точный фрагмент блока из index.html — без ошибок.
- Реальный app.js (песочница new Function) → реальные computed/methods:
  гейт visible(admin+данные)=true, hidden(не-админ)=true, hidden(нет данных)=true;
  mount: 2 группы (Base/Style), 3 exact-`<pre>` (base-1, style-1, style-2),
  3 copy-кнопки, developer-details с machine reason.
- Скриншоты 640px/390px (scratch `f8_block_desktop_640.png`/`f8_block_narrow_390.png`):
  layout чистый, `break-words`/`whitespace-pre-wrap` — нет горизонтального
  overflow (docScrollW==innerW на 390). Визуальная идентичность админки сохранена
  (существующие классы карточки/btn-ghost/серой типографики — REFINEMENT, не редизайн).

## 3. Инварианты
- R17: полный prompt ТОЛЬКО в ответе global-admin API с include_prompt=true;
  generic-ответ (без параметра) ключа не содержит; логи — числа/enum/хэши
  (новых логов с текстами нет; warn-и читателя текстов не логируют).
- manifest↔request: покрыт тестом по обоим durable-носителям (media job hash,
  task_jobs cursor-манифест); расхождение = RED (§22 п.17).
- Freeze §5.1: diff app.js содержит ТОЛЬКО hunks SECTION-COVER-RUNS
  (:3565+computed, :5365+loader, :5383+helpers); остальные hunks в общих файлах —
  F3 (MODULES/Initiative) и F5 (badge/access re-fetch), атрибуция сверена по hunkам.
- Запись манифестов не менялась (cover_style_jobs diff = +52 строки, только reader+__all__).

## 4. Соседние лейны / incidental findings
- **related-nonblocking**: test_round1025_f8_registry (9) и
  test_summary_publish_integration::test_catalog_zero_delta — RED из-за
  незакоммиченных правок F3 (routes.py/param_catalog.py/module_registry.py).
  После merge F3 их пины переутверждаются её слайсом; F8 на это не влияет.
- **uncertain (не блокер F8)**: `run_style_job` персистит state только при
  переданном `state=` — production передаёт (begin_cover_job), тест повторяет
  production-паттерн; поведение записи не тронуто.
- Owner live-check (§2.6.1): 2-click сверка final_prompt двух живых прогонов в
  Run Inspector — за владельцем (SSH/прод-ключи недоступны по правилам).

## 5. Остаточный риск
- Блок появляется в drill-down выбранного run (drill-down = единственный путь
  `/runs/{run_id}`); в режиме «Последний запуск» без выбора run'а exact-промптов
  нет (inspector-endpoint их не отдаёт) — соответствует контракту §2.5.
- Live-рендер проверен на локальном статике + реальном коде; живой prod-рендер —
  owner-чек при деплое Wave 1.
