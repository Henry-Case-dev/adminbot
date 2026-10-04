# ASAP 4.3 `cover-style-surgical` — review.md (T-4861, единый Reviewer pass)

Дата: 04.10.2026. Verdict: **Approved** (C0/H0; 1 non-blocking Low + notes).
Блокирующих дефектов нет; canary/live — owner-gates, не закрыты и не засчитаны.

## Binding

| Поле | Значение |
|---|---|
| Reviewed-Commit (HEAD) | `2e80071dca65f63f4f985490a1d42845e71df4eb` (без коммитов, candidate = working tree) |
| Working-Tree-Hash | `39E5330BA309B0B05F3925192138E8FF59D13A014121CE927D71AF360C9AFDD7` |
| WTH recipe | SHA-256 UTF-8 файла `plans/reports/asap43_wth_manifest_review.txt`: заголовок `WTH-MANIFEST … HEAD=2e80071…` + CRLF-строки `path|size_bytes|SHA256` (30 in-scope файлов: 11 runtime/tool, 11 py-тестов+2 js-теста, 3 staged `extra_images/`, 3 feature-дока, geometry-артефакт), пути отсортированы. Любая правка файлов из манифеста (кроме review.md) инвалидирует approval. |
| Spec | `plans/current_task.md:25459–26361` (не изменялся, сверено) |
| Scope staged | только `extra_images/` (3 файла, 475189/2105937/401490 B) — подтверждено `git diff --cached --stat`. Изменённые `plans/metrics.md`/`workflow_state.md`/`round1027-frames` — запланированная bookkeeping-запись, не стейджилась, runtime не трогает. Скоуп §13 соблюдён: `summary_generator.py`, `handlers/`, MCA/GraphRAG/Direct — в диффе отсутствуют. |

## Что я запустил сам (воспроизведено, не принято на слово)

1. pytest: `test_asap43_cover_style_surgical.py + test_asap42_step2c2_miniapp_seeds.py + test_extra_cover_style_jobs.py + test_extra_cover_styles_api.py` → **94 passed**; `test_asap42_step3_style_integration.py + test_extra_cover_style_pipeline.py` → **25 passed**.
2. `node tests/js/asap43_cover_style_surgical_test.js` → OK; `node tests/js/round1029_extra_cover_styles_test.js` → OK; `node --check web/app.js` → OK.
3. `.venv\Scripts\python.exe tools\ui_asap32_cover_styles_e2e.py` → **OK, 3 viewports**, `failures: []`, `console_errors: []`, `test_starts: 3` (1/viewport, double-tap safe), `placeholder_hits: 6`; артефакт `_ui_asap43_cover_styles_geometry.json`: `docOverflow=false`, sticky-save/saveBtn `inViewport`, `saveNavOverlap=false`, `moreSheetPresent=false` (closed), preview `horizontalOrder/bottomAligned/fitsWidth/arrowIsMsr=true` — на portrait 390×844, landscape 844×390, desktop 1280×800.

## Проверено по рантайм-коду (не по отчётам)

- **§2 durable job:** `web/api/cover_styles.py` POST → короткий `start_preview_job` (`{job_id,status:"queued"}`, тестовая ассертка elapsed<2s); `GET /cover/test-style/{job_id}` — бесплатный snapshot (`task_jobs`+checkpoint, без provider-вызовов), только safe-диагностика provider/model/human/machine/stage/URLs, breakdown — числа; `api_key` отсутствует (тест-класс). Double-tap: активный job того же стиля → тот же `job_id` (`_START_LOCK` + `_ACTIVE`+`_PENDING`); 404 unknown; 503 без durable-DB — честно. Provider task id `provider_task_id` живёт в CoverJobState и поднимается в resume (`existing_task_id`), `run_style_preview` теперь прокидывает `db/job_id/state` (durability больше не no-op).
- **§4 atomic pair:** `set_preview` — ОДИН UPDATE (before+after+revision+job_id); `preview_job_id` — additive nullable DDL (CREATE + `ALTER … IF NOT EXISTS`, без новой таблицы). Провал job идёт в `_fail_job` ДО записи pair — pair не тронута (тесты: `persisted == first pair`, `set_preview==[]`, `preview_after_url is None` на fail). `preview_pair_current` валидирует оба ассета + revision == current; stale ≠ current; placeholder-состояние (`preview_revision NULL`) не пара.
- **§5 placeholders:** `SEED_FILES` = только reference; `placeholder_files()` берёт фактические имена из listing `extra_images` (`.png`/`.jpg`); read-only route `/cover/placeholders/{name}` (path traversal 404 — тест), « Ch/Б UI fallback замещается реальной pair после completed (`coverStyleLoadMeta`+`loadCoverStyles`, `preview_pair_valid`); `_repair_seeded_profile` чистит legacy example-указатели (`preview_revision IS NULL → NULL`) идемпотентно, файлы не удаляются, владелец-отредактированная инструкция не перезаписывается.
- **§6 Medved:** цепочка db_row→file→mime_ok→readable; `reference_paths` реально в edit_call; sha256 bytes == medved_press.png, `style_example` не подменяет; seeded edit — только global admin (403 non-admin, `start_preview_job` НЕ await). Staged в git — checkout-дуративность.
- **§7/§8:** precedence resolve: manual (`bot_settings cover_style.prompt_limit_overrides`, per provider+base_url+model+**operation**) поверх dynamic/legacy (_apply_manual); observed `record_runtime_limit` per route (чужой route/model не получает — тест); «prompt too long» → UNKNOWN; unknown не пре-блок (тест `len(prompts)==1`); AST-guard 800 на 4 файлах; в web/app.js `800` — только comment/таймеры, лимит не управляет. Bounded retry: `retry_ok = not exceeded and shorter`, иначе второй paid call не отправляется (`skipped:"exceeded"`, `len(prompts)==1`) — тесты обновлены не в пользу старой логики. Компакт-инструкция §8 сохраняет все invariants (PERMsoc один, номер один, логотип без дублей, references по ролям, comic/graphic-novel) и мигрирует существующую строку только при точном legacy-значении.
- **§9 budget:** `Инструкция: N символов · Лимит текущей модели: M/неизвестно`; `задано вручную`; breakdown Style/Context/Refs-meta/System/Итого; unknown-фраза §9 дословная; test_starts mock 800 нет (проверено AST+grep).
- **§10–§11 UI:** переписанный `ui_asap32_cover_styles_e2e.py` содержит реальные DOM-rect assertions (не скриншот-only): docScrollWidth, editor head/body/foot в viewport, body — единственный скроллер, nav перекрыта overlay, ghost more-sheet, preview-группа, двойной тап → 1 job, stage-текст человеческий, elapsed только информационный. Mobile grid track `minmax(0,1fr)` — структурный фикс §10.2 (не `+Npx`). Поллэтап reconnect: ephemeral network-error → человеческая фраза + повторный poll, сырой `Failed to fetch` не финал (`ApiError(0,'network')`).
- **§3 honest errors:** `preview_human_message` единая таблица; `developer_reason` только в collapsed `<details>`; transient poll-failure не ставит финальный failed.
- **§12/§22 DoD:** `classify_cover_result` ladder тест зелёный; фабрика preview = production контур (`run_style_job`, mode=preview, issue_calls==0, no publish).
- **Спец-внимание (п.10):** `test_medved_reference_chain_into_edit_request` и `test_unknown_limit_does_not_pre_block` проверяю по коду тестов — ослабления нет: первый усилился (sha256 bytes vs исходник + build_edit_payload с input_references), второй теперь честно через реальный `run_style_job` с caps UNKNOWN и запретом второго вызова.

## Findings

| # | Severity | Location | Finding | Blocking |
|---|---|---|---|---|
| 1 | Low | `web/api/cover_styles.py` GET `/cover/test-style/{job_id}` | status доступен любому пользователю с `access` (job_id детерминирован по стилю): в момент админ-теста другой пользователь может читать provider/model/URLы preview. Секретов/prompt нет (проверено), инфо низкочувствительно — не блокирует. | no |
| 2 | Low (note) | `services/cover_style_preview.py:check_resume` | resume с потерянным base-ассетом регенерирует base от `_BRIEF_DEFAULT` (не оригинального брифа) — safe-by-default, дефолт идентичен TEST_STYLE_BRIEF; только если ассет исчез. | no |

## Специальные owner-gates (POST-DEPLOY, НЕ закрыты, НЕ засчитаны мной)

- **Canary A (T-4859)** — реальный Test Style на configured production provider: base создана, style edit выполнен, reference передан, status completed, pair атомарна, issue counter не изменён, no `Failed to fetch`.
- **Canary B (T-4860)** — production publish: опубликована именно styled cover (base fallback ≠ style success).
- **Live acceptance A/B (T-4863/4864)** — реальный Telegram WebView (mobile) + реальный Summary с Medved Press; live ladder.
- Статические Playwright/тесты не заменяют canary — DoD-20/22 остаются PENDING OWNER.

## DoD §18 (22 пункта; сверено с 26236–26257)

1 нет долгого fetch — verified (короткий start, polling). 2 durable прогресс UI — verified (polling+stage, mock-e2e+frontend). 3 reconnect без 2-го paid — verified (тесты). 4 нет raw Failed to fetch финал — verified. 5 atomic pair — verified. 6 fail без смешанной pair — verified. 7 Ч/Б fallback — verified. 8 не DB preview assets — verified. 9 success → реальная pair — verified (код+UI mock). 10 Medved reference — verified (целевая цепочка; canary-A остаётся). 11 нет 800 — verified. 12 manual override — verified. 13 compiler сохраняет смысл — verified (текст+инварианты, реальный рендер — canary A). 14 budget UI — verified. 15 portrait — verified (DOM rects). 16 landscape — verified. 17 SaveBar/nav geometry — verified. 18 нет horizontal overflow — verified. 19 compact before→after — verified. 20 Test Style canary — **PENDING OWNER (canary A)**. 21 production canary — **PENDING OWNER (canary B)**. 22 ladder не сломан — verified targeted; live — T-4864.

## Отсутствующие обязательные проверки

- Отсутствуют: реальный провайдер (canary A/B) и живой Telegram WebView — только post-deploy owner gates (перечислены выше). Иное замещено: pytest 119 (моё подмножество), 3 JS/синтакс, Playwright e2e 3 viewport c DOM-rect (воспроизведено).

## Вывод

Один verdict: **Approved**. C0/H0 blocking-дефектов нет; two Low non-blocking; следующий шаг Orchestrator — deploy (T-4862) с последующими Canary A/B и live acceptance POST-DEPLOY.
