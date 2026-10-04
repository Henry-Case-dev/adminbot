# ASAP 4.3 — evidence.md (Builder continuation, T-4841…T-4858)

Дата: 04.10.2026. Контур: surgical corrective pass, только зоны ASAP 4.3
(§0–§21 блока владельца `plans/current_task.md:25459–26361`, не изменялся).
Коммитов нет; рабочее дерево — кандидат для Reviewer/деплоя.
Worktree fingerprint: HEAD `2e80071` + 22 modified файла (runtime/tests/tool,
2466+/755−) + 3 untracked новых; `extra_images/` staged
(`git ls-files extra_images` → 3 файла).

## T-4841 — root cause confirmation (подтверждено/опровергнуто)

| # | Recon-факт (_was_) | Код-подтверждение → что сделано | Итог |
|---|---|---|---|
| 1 | Один долгий синхронный POST `/cover/test-style` + no GET-status | `web/api/cover_styles.py:1060` теперь короткий start → `{job_id,status}`; `:1130` GET status; `services/cover_style_preview.py:211` (`start_preview_job`), `:342` (`run_preview_job`); UI polling `web/app.js:7638` | подтверждено, исправлено |
| 2 | `run_style_preview` без `db/job_id` → durability no-op | `services/cover_style_jobs.py:1662` прокидывает `db/job_id/state`; расхождение с recon не найдено | подтверждено, исправлено |
| 3 | Pair неатомарен (asset inserts autocommit, `preview_job_id` нет) | `services/pg_db.py` +`preview_job_id` (DDL + `ALTER … IF NOT EXISTS`); `services/cover_style_registry.py:336` — один UPDATE before+after+revision+job; `:391` `preview_pair_current`; public `preview_status` (`web/api/cover_styles.py:109`) | подтверждено, исправлено |
| 4 | `style_example_01/02` засеяны как DB preview assets | `cover_style_registry.py:96` `SEED_FILES`=только reference; `:105` `placeholder_files()` — фактический listing; `:759` `_repair_seeded_profile` (NULL legacy-указателей, идемпотентно); read-only route `/cover/placeholders/{name}` (`web/api/cover_styles.py:766`); UI fallback `web/app.js:7175` | подтверждено, исправлено |
| 5 | Medved reference-цепочка цела; RBAC enforced | `_resolve_reference_details` (DB-row/file/mime/signature); `_assert_can_edit_seeded` на POST test-style; targeted: sha256 файла == `extra_images/medved_press.png`, reference идёт в edit request; RBAC 403 — `tests/test_asap42_step2c2_miniapp_seeds.py`, `tests/test_extra_cover_styles_api.py` | подтверждено, дефектов не найдено |
| 6 | Hardcoded `800` нет; manual override только env; 400-retry мог слать второй paid call при `exceeded` | AST-guard зелёный (`tests/test_asap43_cover_style_surgical.py::test_no_hardcoded_800_in_new_runtime`); `services/image_capabilities.py:50,61,125` — manual override (bot_settings, operation-aware, высший приоритет); `services/cover_style_jobs.py:1528` — retry только если `not exceeded and shorter` | подтверждено, исправлено |
| 7 | Mobile: клиппинг save-бара, non-wrapping flex, editor без структурного контракта | `web/static/app.css` `.cover-editor-head/body/foot`, `.cover-preview-group`, `.sticky-save` wrap; **структурный фикс (§10.2)**: mobile-трек `main.scroll-area` `1fr !important` → `minmax(0,1fr) !important` (min-content пол выталкивал Save за экран) | подтверждено, исправлено |

Противоречий со спекой владельца не найдено → Architect не требуется.

## Изменения по зонам

- **Z1 (T-4842/4843):** new `services/cover_style_preview.py` (durable job, стадии,
  resume, double-tap dedup, honest human_message); `web/api/cover_styles.py`
  (short start + status + 404/503); `services/cover_style_jobs.py`
  (`kind`/`initial_state`/`get_cover_job`/`requeue_cover_job`/`STATE_SAVING_PREVIEW`,
  state diagnostics); `web/app.js` (polling-контур).
- **Z2 (T-4844):** `services/cover_style_registry.py` (`set_preview` atomic,
  `preview_pair_current`), `services/pg_db.py` (+column/ALTER, additive),
  `web/api/cover_styles.py` (`preview_job_id`/`preview_status` в public payload).
- **Z3 (T-4845/4846):** seed placeholders убраны, `placeholder_files`,
  seeded-repair, placeholders route, UI fallback (`coverPairAsset`);
  `extra_images/` в git (3 файла staged).
- **Z4 (T-4847/4848/4849):** `services/image_capabilities.py` (manual override
  per provider+base_url+model+operation, precedence top, env-совместимо),
  `cover_style_pipeline.py` (`operation`), `image_prompt_compiler.py`
  (components breakdown), `cover_style_jobs.py` (bounded retry), compact
  seeded-инструкция + миграция, prompt limit API (`/cover/prompt-limit`),
  UI счётчики/breakdown `web/app.js:7752`, `web/index.html`.
- **Z5 (T-4850/4851/4852):** `web/static/app.css` (editor head/body/foot,
  preview-group, `.sticky-save` wrap, mobile grid track `minmax(0,1fr)`),
  `web/index.html`.
- **Z6 (T-4853/4854):** `web/app.js` (stage-тексты, reconnect/дочитывание,
  `ApiError(0,'network')`, `developer_reason` только в details), `web/index.html`.
- **T-4855…4858:** обновлены/добавлены тесты (см. ниже), переписан
  `tools/ui_asap32_cover_styles_e2e.py` (3 viewport + DOM-rect assertions).

## Команды и результаты

1. `\.venv\Scripts\python.exe -m pytest tests/test_asap43_cover_style_surgical.py
   tests/test_asap42_step3_style_integration.py
   tests/test_asap42_step2c2_miniapp_seeds.py tests/test_extra_cover_styles_ui.py
   tests/test_extra_cover_styles_api.py tests/test_extra_cover_style_jobs.py
   tests/test_extra_cover_style_registry.py
   tests/test_cover_styles_contract_asap32.py
   tests/test_asap42_step2c_image_capacity.py -q`
   → **191 passed** (9 файлов).
2. Neighbors: `pytest tests/test_cover_style_wave_b_asap4.py
   tests/test_extra_cover_style_pipeline.py tests/test_extra_cover_style_runtime.py -q`
   → **48 passed**; `pytest tests/test_summary_cover_style_wave_f_asap41.py -q`
   → **16 passed**.
3. JS: `node tests/js/asap43_cover_style_surgical_test.js` → OK;
   `node tests/js/round1029_extra_cover_styles_test.js` → OK;
   `node tests/js/asap42_step2c2_layout_test.js` → OK; `node --check web/app.js` OK.
4. Playwright: `.venv\Scripts\python.exe tools\ui_asap32_cover_styles_e2e.py`
   → **OK, 3 viewports** (390×844 portrait, 844×390 landscape, 1280×800 desktop,
   safe-area 56/24 px на mobile-контекстах); артефакт
   `tools/_ui_asap43_cover_styles_geometry.json` + 6 скриншотов.
   Проверено DOM-rect: `scrollWidth<=clientWidth`; editor head/body/foot, footer
   и Save целиком во вьюпорте; body — единственный скроллер; nav закрыта
   overlay'ем; closed more-sheet отсутствует; preview `[До] msr [После]` одной
   группой и по ширине; sticky-save не пересекает nav; Test Style: 1 paid job
   на 3 клика (double-tap safe), stage-текст, completed pair; custom-стиль —
   Ч/Б placeholder с `naturalWidth>0`, source «Пример».

## Исправленные по ходу дефекты (в скоупе)

- `tests/js/round1029_extra_cover_styles_test.js` пинил старую формулировку
  unknown-лимита → обновлён на §9 («Инструкция: N символов · Лимит текущей
  модели: неизвестно»).
- `web/app.js::coverStylesEnsureAssets` запрашивал asset по фиктивному ключу
  `placeholder_*` (при не-404 ответе мог затенять реальный placeholder-blob) →
  пустые id пропускаются, placeholders грузятся своим циклом.
- `.sticky-save` в mobile grid-треке с min-content полом (`1fr !important`) —
  тот самый клиппинг `Сохранить изменения` из §10.2 → `minmax(0,1fr)`.

## Остаточные риски / gaps

- Canary A/B (T-4859/4860) и live acceptance (T-4863/4864) не выполнялись —
  PENDING OWNER; static Playwright не заменяет живой Telegram WebView.
- `preview_status` — аддитивное поле контракта §4 (UI использует pair-флаги).
- `_repair_seeded_profile` мигрирует только точную legacy-строку 979 chars;
  отредактированная владельцем инструкция не перезаписывается (by design).
- Артефакты `tools/_ui_asap43_*` оставлены unstaged (не коммитим; в репо есть
  прецедент трекинга `tools/_ui_*` — решение за Orchestrator/DevOps).
