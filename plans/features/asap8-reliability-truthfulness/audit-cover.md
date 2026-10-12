# ASAP 8 / P8-B — Forensic audit: Cover Style Edit + Prompt Truth

Baseline: `master @ 0c4f3a5` (release 2.58.74). Режим: read-only, только этот файл.
Источник контракта: `plans/current_task.md` ASAP 8 §4–§7, §20 (C1–C7), §28 (запреты 5–9).

---

## 1. Style Edit style-first (symptom 3, §4) — CONFIRMED

### 1.1. Карта приоритетов `compile_style_prompt` (services/cover_style_jobs.py:1155–1238)

Компоненты в порядке добавления (`components = [...]`, cover_style_jobs.py:1218–1230):

| # | Компонент | P-уровень | Label | Источник |
|---|---|---|---|---|
| 1 | `runtime_invariants_text(issue_display)` | **P0** | `runtime_invariants` | cpa.runtime_invariants_text — cover_prompt_assembly.py:720–726 |
| 2 | `profile.instruction` | **P1** | `style_instruction` | профиль стиля (БД) |
| 3 | `base_style_prompt` (если непуст) | **P1** | `base_style_prompt` | caller; в prod = `prompts.summary_cover_style` (см. 1.4) |
| 4 | `style_reference_text(profile)` | **P2** | `references` | labels+описания референсов (cover_style_jobs.py:1148–1152) |
| — | `story_scene.strip() + " " + brief.render()` | budget_component (вне P-уровней) | `cover_brief` | cover_style_jobs.py:1231–1237; budget_floor = `cpa.story_floor_text` (STORY_MIN_CHARS=160, cover_prompt_assembly.py:40) |

### 1.2. Как `compile_prompt` (services/image_prompt_compiler.py:189–284) режет

Порядок строки: **P0 → P1(style_instruction) → P1(base_style_prompt) → P2(references) → brief → P3**
(`full_parts`, compiler:218–220; required = p0+p1, compiler:232).

- P0+P1 не влезают в лимит → `exceeded=True, reason="prompt_limit_exceeded"` → Base fallback (compiler:235–243; обработка в cover_style_jobs.py:1794–1809). Строковые ножницы на P0/P1 запрещены.
- P2 добавляется целиком, иначе **drop** (compiler:246–251).
- brief (сюжет): целиком → компакт (первое предложение, `_compact_semantic_brief`, compiler:179–186) → `budget_floor_text` (story-minimum, compiler:262–268) → **`dropped.append("cover_brief")`** (compiler:270).
- Т.е. сюжет — последняя надбавка и первая содержательная жертва: при давлении он падает до «первого предложения», затем до 160-char floor, затем исчезает — при этом P1-стиль гарантированно едет целиком.
- `retry_core=True` (semantic squeeze, cover_style_jobs.py:1180–1217): runtime → profile identity floor (≥50% instruction, cpa.profile_identity_floor:111) → **base_style тоже едет в ядре** (cover_style_jobs.py:1189) → reference roles → story floor. Описания refs и хвост instruction опускаются.

**Вывод: Base story-first — CONFIRMED** (`base_prompt_plan` story_first default: STORY_SCENE → SUMMARY_CONTEXT → BASE_STYLE в строке, protected story-minimum 160/style floor 160, cover_prompt_assembly.py:201–320, 162–178; env-откат `style_first`). **Style Edit семантически style-first — CONFIRMED**: сюжет идёт после всех style-блоков и режется раньше них.

### 1.3. Content-preservation инвариант — ОТСУТСТВУЕТ (CONFIRMED §4.3)

- `runtime_invariants_text()` (cover_prompt_assembly.py:720–726): только «Сохрани номер выпуска…» + запрет дубликатов. Ни subjects, ни actions, ни composition, ни «change style, not content».
- Grep по `services/` на preserve/композицию/сюжет-сохранение: единственный носитель такой семантики — **данные профиля** `SEEDED_INSTRUCTION` medved_press («Сохрани сцену, композицию и удачные плашки», cover_style_registry.py:61–69), т.е. P1-текст конкретного профиля, который при squeeze урезается до 50% identity floor; для кастомных профилей фразы может не быть вообще. Контрактного P0-preservation нет.
- Формулировки §5.3 TZ («Preserve the exact depicted event…») в коде отсутствуют.

### 1.4. Что передаёт `cover_style_edit.py` — Base image как input reference

- `edit_image(...)` (cover_style_edit.py:358–410): `images = [base_image_path] + reference_paths` (382–385); payload по маршруту: `input_references` = массив data-URL (build_edit_payload:167–179) или `imageDataUrl(s)` (190–201) или multipart `image`/`image[]` (204–222). Base — **первый элемент**, без какой-либо семантической маркировки «это content authority, не меняй».
- `route_unverified` → отказ без вызова (394–397). `max_input_images` по capability (386–387): при малом лимите base-first — base не вытесняется refs, но нигде не проверяется, что base реально попала (есть `no_input_images` check:411–413).

---

## 2. Дублирование BASE_STYLE — CONFIRMED

Production-цепочка (`services/summary_generator.py`):

1. `style = await self._resolve_cover_style_text(chat_id)` (summary_generator.py:2863) = `prompts.summary_cover_style` (per-chat override → global → дефолт, 3847–3868).
2. Base: `compose_base_cover_prompt(base_style=style_text, …)` (2993, 3003) → BASE_STYLE **уже применена к Base-изображению**.
3. Style: `_maybe_apply_cover_style(…, base_style=style, …)` (3113–3115) → `run_style_job(base_style_prompt=base_style)` (3333–3343).
4. `compile_style_prompt` кладёт её **вторым P1-блоком** (cover_style_jobs.py:1225–1227), который компилятор не режет никогда (compiler:232–243).

Итог: один и тот же generic-текст стиля присутствует в промпте Style Edit как доминирующий (неурезаемый) второй style-блок рядом с profile.instruction, хотя его эффект уже запечён в input image. Риск §5.2 «не дублировать generic BASE_STYLE» — **подтверждён структурно** (не зависит от текста ключа). Честный предпросмотр manifest'а это тоже фиксирует: `build_style_manifest` отдельными компонентами `BASE_STYLE` и style instruction (cover_style_jobs.py:692 cpa; _build_style_manifest:1441–1458).

---

## 3. Symptom 4 — exact prompt скрыт в «Последний запуск» — CONFIRMED

### 3.1. Механизм гейта (web/app.js::loadPipelineInspector, 5523–5551)

- Запрос detail строится **только внутри** `if (this.pipelineSelectedRunId)` (5530–5545): `GET /api/analytics/pipeline/runs/{id}` + `?include_prompt=true` лишь при `isGlobalAdminEffective` (5537–5539).
- Режим «Последний запуск»: `setPipelineMode` (5552–5557) и `openPipelineRun(null)`-ветки (5642–5644) сбрасывают `pipelineSelectedRunId = ''`; начальное значение тоже `''` (1861) → detail не запрашивается → `pipelineData.cover_prompts` не устанавливается никогда.
- Рендер: `pipelineCoverPrompts` (3671–3676) читает только `d.cover_prompts`; `pipelineCoverPromptsVisible` (3679–3683) = global-admin **И** (`cp.base || cp.style`); блок в index.html:4632–4643 под `v-if="pipelineCoverPromptsVisible"`, заголовок «Фактический промпт».

### 3.2. Бэкенд-контракт (web/api/analytics.py:630–670)

- `GET /analytics/pipeline/runs/{run_id}`: `requires_global_admin()` (fail-closed 403 не-глобалу), `include_prompt: bool = Query(default=False)`; без параметра ключ `cover_prompts` в ответе отсутствует вообще; с параметром — `csj.load_run_cover_prompts(db, rid)`.
- `load_run_cover_prompts` (cover_style_jobs.py:1328–1376): `{"base": base_manifest|None, "style": style_manifest|None}`; style ищется по `coalesce_key = "cover_style:<run_id>"` в `task_jobs` (cursor → CoverJobState.prompt_manifest), base — `load_base_cover_manifest` (kind=cover_base, cover_style_jobs.py:766–806).

### 3.3. Missing-manifest поведение — скрытый блок, причины нет (CONFIRMED §6.2-нарушение)

- Оба манифеста None (legacy run, недописанный job, PG fail-open) → `pipelineCoverPromptsVisible=false` → блок просто не рендерится. UI-элемента с reason (`base_manifest_missing`/`style_job_not_linked`/…) **не существует**; бэкенд причина тоже не отдаёт (возвращаются None-поля без кода причины). В режиме latest причина недостижима вдвойне — detail вообще не грузится.

---

## 4. Prompt editor «ИИ → Промпты → Стиль обложки» — raw textarea — CONFIRMED (§6.3)

- Страница «Промпты» рендерит `prompts.summary_cover_style` как обычный config-item: `SUMMARY_PROMPT_META` (app.js:734–737, группа «Обложка», «Стиль обложки»); видимость — `promptVisibleItems` (app.js:12143–12157, ключ всегда показан, ASAP-2.1); рендер — generic `<textarea v-model="item.value">` (index.html:2045–2110). **Никакого вызова preview-compile на этой странице нет** (единственный вызов `/api/cover/preview-compile` в app.js — 10704).
- Отличие от Cover Style Editor surface: там live-превью есть — `coverCompilePreview()` (app.js:10693–10717) → `POST /api/cover/preview-compile` (global admin), UI index.html:822–830 («Фактическая сборка промпта»).

### Переиспользование `/api/cover/preview-compile` (web/api/cover_styles.py:1463–1592+)

- Endpoint существует, global-admin, compile-only, тот же server compiler. **Но компилирует он ТОЛЬКО Base-сборку**: `cpa.base_prompt_plan`/`compose_base_cover_prompt` (1541, §9.2 docstring 1469–1473) — draft.instruction подставляется как BASE_STYLE (1489–1499), story/context — только из собственных Test-прогонов владельца (`_resolve_preview_context`, fail-closed, 1568–1574); body = `{profile_id, draft, context{chat_id}}` (PreviewCompileBody:1424–1431).
- Для «Промптов» (C7) этого **недостаточно как есть**: страница редактирует `prompts.summary_cover_style` = BASE_STYLE + (в Style Edit) base_style_prompt, но не умеет: (a) компилировать Style-стадию (`compile_style_prompt`: runtime invariants + instruction профиля + base_style + refs + story), (b) принимать произвольный Summary-context вне своих Test-прогонов. Переиспользуемая база — да (тот же лимит-резолвер 1500–1523, budget 1525–1537, честный placeholder 1539–1566), но нужен style-режим/расширение контракта.

---

## 5. E2E §7 (две сцены) — инфраструктура частичная, scene-identity проверок НЕТ

Существующее (`tests/test_asap44_cover_final_closure.py` и соседи):

- Полный worker-путь Summary→Base→Style с **функциональными стабами**: `monkeypatch generate_image_verbose` (base) + stub `run_style_job` (style), styled-байты — константа `b"STYLED-ASAP44-BYTES"` (test_asap44:125–171); `run_style_job` с `edit_call`-стабом, возвращающим байты (test_extra_cover_style_jobs.py:435+, test_cover_style_wave_b_asap4.py:577+, test_asap7_cover_readpath.py:149–154 — payload/manifest parity, retry).
- Base-компиляция production: test_asap7_cover_preview.py:260–294 (Summary Test → cover → compose_base_cover_prompt == отправленный prompt == manifest).
- preview-compile endpoint: test_asap7_cover_preview.py:528–704.

Чего не хватает для §7:
1. **Двухсценного fixture** (Scene A «человек чинит серверную стойку», Scene B «два человека спорят возле разбитой машины») — сцен как данных нигде нет.
2. Захвата **edit payload** (что base image реально в `input_references`, prompt совпадает с manifest) на полном пути — частично есть на уровне `run_style_job`-стабов, нет в E2E worker-прогона.
3. **Проверки styled-выхода**: styled-контент никогда не анализируется (константные байты); нет vision-acceptance хелпера и критерия «Styled A ≠ generic portrait», «A и B остаются семантически разными».
4. `provider request == durable manifest` для Style на живом маршруте (route image_api/image_edits) с реальными data-URL.

---

## 6. C1–C7 — карта покрытия тестами

| ID | Требование (§20) | Статус | Покрытие / разрыв |
|----|---|---|---|
| C1 | Base prompt story-first | **есть (код+тесты)** | test_asap7_cover_fix.py:71–160 (story_first канон, story-minimum, floor, misconfig); test_asap7_cover_preview.py:260–294 (порядок STORY→CTX→STYLE == отправленному); test_asap5_cover_prompt_manifest.py:102,501 |
| C2 | Style payload: Base image + preservation invariant + story identity | **частично** | Base image в payload — код (cover_style_edit.py:382–410) и стаб-тесты; story identity в prompt/manifest — test_asap5_cover_prompt_manifest.py:132,156,204. **Preservation invariant отсутствует в коде → теста нет** (глушится seeded-инструкцией профиля) |
| C3 | Две сцены + один стиль остаются разными | **нет** | Ни fixture сцен, ни content/vision-проверок styled-выхода (см. §5) |
| C4 | Pressure не молча снимает mandatory; core не влез → Base fallback | **частично** | P0+P1 overflow → Base: cover_style_jobs.py:1794–1809; тесты test_asap44:783–941 (cover12/12b/12c/12e), story floor test_asap5:240,396. Разрыв: **drop сюжета (`cover_brief`/P2) НЕ является fallback-условием** — сюжет может исчезнуть молча-для-результата (виден только в `dropped[]`/manifest) |
| C5 | Latest Run Inspector auto-показ exact prompt для global admin | **нет (рефакт CONFIRMED)** | Код гейтится на pipelineSelectedRunId (app.js:5530); тест test_asap7_cover_readpath.py:327–337 фиксирует текущее поведение (не latest-auto), 265–291 — drill-down backend |
| C6 | Missing manifest → явная причина, не скрытый блок | **нет** | Блок скрывается (app.js:3679–3683), reason-механизма нет; теста нет |
| C7 | Generic Prompt editor — server preview, без JS compiler | **нет** | Страница Промптов — raw textarea (index.html:2070/2110); preview-compile только на Cover Style Editor и только Base-сборка (cover_styles.py:1469–1473) |

---

## 7. Вопросы для Architect (реальные развилки)

1. **Preservation block (§5.3)**: отдельный P0-компонент в `compile_style_prompt` + расширение `runtime_invariants_text()` vs отдельный `CONTENT_PRESERVATION` текст; RU/EN формулировка; как соотносится с seeded-«Сохрани сцену…» medved_press (дублирование смысла в P0 и P1)? Входит ли preservation в retry_core-ядро и в `issue_present`-подобный диагностический флаг?
2. **Дубль base_style_prompt**: убрать из Style-промпта вовсе (Base уже применён, image едет как input reference) / понизить до P2–P3 / оставить P1? Учесть, что его же текст использует preview/`cover_style_preview.py:440` и ветка snapshot-OFF.
3. **C4-семантика**: считается ли drop сюжета (`cover_brief`) «semantic scene lost» → нужен ли fail-soft к Base (§5.4) при пустом sent-сюжете, или достаточно видимого `dropped[]`+reason в манифесте?
4. **C5-механика**: резолвить latest run_id на клиенте из inspector-данных и догружать detail, или backend-параметр `mode=latest&include_prompt=true` (серверный resolve)? 
5. **C6-причины**: где строить reason (`base_manifest_missing/style_job_not_linked/legacy_run`) — backend (`load_run_cover_prompts` возвращает причину) или frontend по None-полям?
6. **C7-reuse**: расширить `POST /api/cover/preview-compile` режимом style-stage (compile_style_prompt: runtime + draft + refs + issue_display) или новый endpoint; разрешить ли произвольный chat-context (сейчас — только свои Test-прогоны, fail-closed)?
7. **E2E §7**: vision-acceptance как helper — допустимая зависимость/модель для автопроверки scene identity, или ограничиться prompt/payload/manifest-равенствами + owner live gate?
