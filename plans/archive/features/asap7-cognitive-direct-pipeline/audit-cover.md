# P7-B Forensic Audit — Cover Prompt Truth (Phase 0, read-only)

- HEAD: `08a8849` (master). Prod заявлен 2.58.71. Uncommitted-шум зафиксирован, не тронут:
  `services/disk_retention.py`, `plans/MEMORY.md`, `plans/backlog.md`, `plans/runtime_task.md`,
  `plans/workflow_state.md`, `plans/archive/mca-17c-*/evidence.md`, `plans/reports/mca20_wth_manifest_review.txt`,
  `tools/_ui_mca12_stories_e2e.json` + untracked junk (`node_modules/`, `.playwright-mcp/` и др.).
- Метод: статический call-graph по швам; runtime/SSH недоступен (fail2ban) — HTTP не даёт
  production-манифестов (см. §4), поэтому style-only симптом статически НЕ воспроизводится,
  но найдены конкретные дыры наблюдаемости и 4 реальных data-loss/дивергенс-дефекта.

---

## 1. Схема швов (Summary → cover → provider), file:line

### 1.1. Production Hybrid (SYSTEM2 ON, основной путь)
| # | Шов | Где | Тип / условие пустоты |
|---|-----|-----|------------------------|
| S1 | Stage-1 JSON `cover_prompt` ("english visual prompt", ≤300) | `services/summary_prompts.py:182,188,299–305,960` | LLM может вернуть generic-сцену или пусто — валидации «сюжетности» нет |
| S2 | `normalize_cover_prompt` (collapse, cut ≤300 по слову, fail-open `""`) | `services/system2_handoff.py:91–111` | не-строка/пусто → `""` |
| S3 | package `service.cover_prompt` | `services/summary_l1_contract.py:297–305,532` (пишется только если truthy) | пусто наследуется |
| S4 | Hybrid: `cover_prompt = normalize(service.cover_prompt)`; derive-fallback **только если `fallback_used`** (Stage-1 целиком упал) | `services/summary_generator.py:2351–2365` | пусто И NOT fallback_used → обложки не будет вовсе |
| S5 | **Гейт**: `if cover_prompt and ARTICLE_ENABLED and rich_supported → rich+cover, иначе plain` | `summary_generator.py:2366–2377` | пустой STORY_SCENE ⇒ обложки НЕТ (не style-only) |
| S6 | style resolve: per-chat override → global → default ("photorealistic, cinematic light") | `summary_generator.py:2830,3699–3720`; `cover_prompt_assembly.py:256–266`; дефолт `summary_prompts.py:221` | пусто невозможно (дефолт) |
| S7 | SUMMARY_CONTEXT = `summary_context_text(document.title, paragraphs)` ≤400, 0-LLM | `summary_generator.py:2836–2839`; `cover_prompt_assembly.py:116–138` | пусто только если у документа нет title И paragraphs |
| S8 | **Compiler Base** = BASE_STYLE(≤500, первым) + STORY_SCENE(остаток до 1000) + SUMMARY_CONTEXT | `summary_generator.py:2840–2841`; `cover_prompt_assembly.py:150–229,221` | см. B4: sent_style не перекапируется total_cap |
| S9 | Отправка: `generate_image_verbose` → POST `{prompt, model, n:1}`; **client-капа нет, prompt_limit для GENERATE-маршрута не резолвится вообще** | `summary_generator.py:2886`; `services/image_generation.py:1203–1346,1224` (пустой prompt→`empty_prompt`), payload — модуль docstring :6–17 | provider-side кап невидим; стиль стоит ПЕРВЫМ → хвост (story+context) режется первым |
| S10 | Base manifest: `build_base_manifest` → `task_jobs` kind=`cover_base` | `summary_generator.py:2859–2875`; `cover_style_jobs.py:766–795` | пишется на ok/failed; **читателей нет** (§4) |
| S11 | Style Edit: `_maybe_apply_cover_style(summary_text=_document_plain_text(document) or cover_prompt, story_scene=cover_prompt)` | `summary_generator.py:2965–2969,3185–3195` | компиляция `compile_style_prompt`: P0 runtime + P1 instruction/base_style + P2 refs + budget(story+brief) с floor 160 (`cover_style_jobs.py:1155–1238`; `image_prompt_compiler.py:189–284`) |
| S12 | Style manifest → `state.prompt_manifest` + meta hash/chars | `cover_style_jobs.py:1957–1968` | production-читателя нет (§4) |

### 1.2. Production Legacy/fallback (OFF / L2 unusable)
| # | Шов | Где | Условие пустоты |
|---|-----|-----|-----------------|
| L1 | `_resolve_cover_prompt`: `draft.cover_prompt` → иначе derive (первая фраза саммари ≤300) → иначе `""` | `summary_generator.py:3604–3658,3660–3666`; `cover_prompt_assembly.py:298–317` | все kill-switches OFF → `""` → plain |
| L2 | Гейт `if cover_prompt and … → _deliver_rich` | `summary_generator.py:1621–1632` | тот же контракт: пустой story ⇒ нет обложки |
| L3 | `document_from_plain_text(source, title)` → тот же `_publish_rich_document` | `summary_generator.py:3722–3746` | далее идентично S6–S12 |

### 1.3. Test Style (2 разных «теста»!)
- **Cover Test Style (профили стиля)**: `POST /api/cover/test-style` → preview job с НЕЙТРАЛЬНЫМ брифом
  `TEST_STYLE_BRIEF` (`web/api/cover_styles.py:45,1285–1359`); base = бриф без стиля
  (`cover_style_preview.py:511–520`), затем `run_style_job` MODE_PREVIEW — тот же
  `compile_style_prompt`, что в production edit. Манифест читается: `GET /cover/test-style/{job_id}`
  отдаёт `prompt_manifest` (include_prompt=True) **только global admin** (`cover_styles.py:1390–1399`).
- **Summary Test cover (админский прогон саммари)**: `web/api/summary_test.py:328–391` —
  **ЛЕГАЦИ-компилятор `compose_cover_image_prompt(style, cover_prompt)` (2 компоненты, БЕЗ
  SUMMARY_CONTEXT, БЕЗ манифеста)** (`summary_test.py:360–370`; `cover_prompt_assembly.py:241–253`);
  пустой cover_prompt → `no_cover_prompt` (не генерит).

## 2. Точки потери summary-контента

Статически: на production-путях (Hybrid S5, Legacy L2) style-only промпт **невозможен** — гейт
требует непустой STORY_SCENE, SUMMARY_CONTEXT строится из финального документа, компилятор
складывает все три компоненты. Найденные реальные дефекты:

- **B1 (P1, главный кандидат на наблюдаемый симптом)**: GENERATE-маршрут не знает prompt-limit
  провайдера (`image_capabilities` используется только EDIT-маршрутом; в
  `generate_image_verbose`/`generate` лимиты не запрашиваются), а компилятор ставит стиль ПЕРВЫМ.
  Любой provider-side кап/трим (например «первая фраза», URL-limit GET-режима) молча убивает
  story+context и оставляет ровно style-only — совпадает с симптомом владельца.
  Проверка в runtime: лог `summary cover: prompt composed | visual_len|context_len|final_len`
  (`summary_generator.py:2848–2857`) vs фактический prompt в durable media job
  (`image_generation.py:1272–1276` пишет prompt в `begin_media_job`) и в
  `task_jobs` kind=cover_base `manifest.final_prompt` — а также манифесты двух разных summary
  (Golden A/B, §12 ТЗ).
- **B2 (P1)**: §11 anomaly guard отсутствует: `cover_context_missing` — 0 вхождений в репо;
  детекции «summary has content AND STORY_SCENE="" AND SUMMARY_CONTEXT=""» нет нигде
  (и на current-коде она не сработала бы — такой путь не доходит до генерации, но derive/fallback
  и generic-сцены от L1 не отличить от честной сцены).
- **B3 (P1)**: нарушен §9.2 «один compiler»: production Base = `compose_base_cover_prompt`
  (3 компоненты), Summary Test = legacy `compose_cover_image_prompt` (2 компоненты),
  Style Edit = `compile_style_prompt` + budget/floor. Test Style ≠ production по составу.
- **B4 (P2)**: `base_prompt_plan` не перекапирует sent_style по total_cap
  (`cover_prompt_assembly.py:173` vs :184) — при env-миссконфиге
  `SUMMARY_COVER_PROMPT_MAX_CHARS < SUMMARY_COVER_STYLE_MAX_CHARS` стиль может превысить общий кап.
- **B5 (P2)**: feedback-loop learning: после успешного semantic-squeeze ретрая в
  `record_runtime_safe_ceiling` пишется ДЛИНА СЖАТОГО промпта как ceiling
  (`cover_style_jobs.py:1926–1939`) — будущие Style Edit могут хронически терять
  cover_brief/story (честно в `dropped`, но манифест никто не видит — B7).
- **B6 (P2)**: L1 не имеет контракта «сцена должна быть summary-specific» — generic-сцены
  («city street, people») дадут визуально одинаковые обложки при формально полном промпте.
  Это неотличимо от style-only без exact-prompt наблюдаемости (§12 это и ловит).
- НЕ подтвердилось: `minimal=True` retry — удалён (D9), retry_core сохраняет story-minimum
  (`cover_style_jobs.py:1168–1217,1885–1925`); `image_context_memory` — только direct-chat tool путь,
  обложки не трогает.

## 3. CoverPromptManifest reality

- Пишется: Base — production Base generation (ok/failed, `summary_generator.py:2859–2875` →
  `task_jobs` kind=cover_base); Style Edit — production + preview (`cover_style_jobs.py:1957–1968`,
  durable `state.prompt_manifest`). final_prompt, attempts (обе строки), hash — всё сохраняется.
- Читается: **единственная точка** — `GET /api/cover/test-style/{job_id}` (global admin,
  `include_prompt=True`; `cover_styles.py:1390–1399`). `load_base_cover_manifest`
  (`cover_style_jobs.py:798–806`) вызывается ТОЛЬКО тестами. Run Inspector
  (`/api/analytics/pipeline/runs/{run_id}`) промпты исключает явно («БЕЗ …полных промптов»,
  `web/api/analytics.py:616–636`).
- UI: блок «Что отправилось модели» есть ТОЛЬКО на Test Style surface и показывает
  **только char counts / статус / reason / hash** — exact `sent_text`/`final_prompt` не
  рендерится нигде, copy button нет (`web/index.html:795–841`; `web/app.js:10055,10074,10193–10234`).
  Live-превью компиляции в редакторе стиля саммари (`prompts.summary_cover_style`) отсутствует
  полностью; у профилей — только числовой budget (`cover_styles.py:337–...`; `app.js:10141–10192`).

**Вердикты**
- CLAIM «Cover Prompt Assembly реализован» — **VERIFIED** (модуль + production-вызовы S8/S11).
- CLAIM «прозрачность промпта обложки доставлена» — **FALSE** как продуктовая функция
  (PARTIAL в узком смысле: админский JSON на test-style endpoint). §10 exact prompt в
  Run Inspector — не реализован; §9.3 exact-тексты в UI — не реализованы; §13-индикатор
  («закрыто при незакрытых T-5252/T-5253 хвостах») подтвердился.
- §11 anomaly guard — **FALSE** (не существует).
- §12 Cover E2E A/B — не реализованы (тестов с semantic marker A/B нет).

## 4. Подтверждённые баги/разрывы → Builder slices

| Pri | Дефект | Evidence | Slice |
|-----|--------|----------|-------|
| P1 | §11 style-only guard отсутствует | grep `cover_context_missing`=0 | **F6** |
| P1 | GENERATE-маршрут без capability/prompt-limit + style-first ordering → тихий provider-side отрез хвоста (главная runtime-гипотеза symptom'а) | S9, `image_generation.py:1203+`, `image_capabilities` только EDIT | **F6** |
| P1 | §9.2 нарушен: 3 компилятора; Summary Test шлёт по легаци 2-компонентной сборке | `web/api/summary_test.py:370` | **F7** (+F6 touch) |
| P1 | Live editor: exact compiled prompt/budget text не показывается (§9.3/9.4) | `index.html:795–841`, `app.js:10141+` | **F7** |
| P1 | Production Base/Style манифесты не читаются никем; Run Inspector без exact prompt (§10) | `cover_style_jobs.py:798` (0 callers), `analytics.py:622–624` | **F8** |
| P2 | UI манифеста показывает counts, не exact тексты (sent_text/final_prompt приходят, но не рендерятся) | `index.html:826`, `app.js:10224–10234` | **F8** |
| P2 | runtime_safe ceiling учит длину сжатого промпта → хронический squeeze story | `cover_style_jobs.py:1926–1939` | **F6** (bound/observability) |
| P2 | `base_prompt_plan`: style не перекапируется total_cap (env-edge) | `cover_prompt_assembly.py:173` | **F6** (мелочь) |
| P2 | L1 cover_prompt без требования summary-specific → одинаковые сцены (§12 RED) | S1, `summary_prompts.py:188` | **F6** (промпт+guard §12) |

## 5. Вопросы для Architect (реальные развилки)

1. Base (GENERATE) маршрут: вводить capability-aware compile как у EDIT, или изменить порядок
   сборки (story до style / дублирование маркера в хвосте), или hardened-проба provider-лимита?
   Решение зависит от подтверждения B1 в runtime (нужен F8-минимум: чтение final_prompt).
2. Где открыть exact prompt владельцу: расширить `/analytics/pipeline/runs/{run_id}`
   (admin) чтением `load_base_cover_manifest` + `task_jobs` cover_style state, или отдельный
   `/cover/manifest/{run_id}`? (constraints: routes.py byte-freeze пин, R17 admin-only.)
3. Summary Test cover: перевести на `compose_base_cover_prompt` (summary_context доступен из
   `entry.result` документа) или оставить легаци с явной пометкой «не production-сборка»?

## 6. Что нужно для подтверждения root cause (без SSH)

1. F8-минимум (read-side): admin API, возвращающий `manifest.final_prompt` последних N
   cover_base джоб + `media job.prompt` — после этого symptom подтверждается владельцем в 2 клика
   (два разных summary → сравнить final_prompt).
2. Локальный тест: `compose_base_cover_prompt(owner_style, story, ctx)` — байт-в-байт сверка с
   наблюдаемой владельцем строкой (стиль владельца ≠ код-дефолт — уже подтверждает,
   что S6 отработал, а STORY/CONTEXT в наблюдаемой строке отсутствовали).
3. Provider probe: тот же final_prompt → image API напрямую (вне бота) — проверить трим.
   Опционально HTTP `/healthz` для фиксации живости.
