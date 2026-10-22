# SUMMARY-REVISION-FIX — ревизия L2 покрывает все абзацы + durable-диагностика

Лейн: `SUMMARY-REVISION-FIX` (writer). HEAD базы: `468d1041`. Деплой не выполнялся,
прод/SSH/живые чаты не трогались. RCA-вход: `plans/features/_audit-2026-10-23/summary-review-rca.md`.

## 1. Что изменено

### F1 — ревизия чинит ВСЕ абзацы с находками (главный фикс)

Было (RCA §2, «ПОТЕРЯ-3»): `targeted_issue = anchor_issues[0]`
(`services/summary_l2_review.py:1250-1292` до фикса) — один `paragraph_id`
за вызов, максимум 2 ревизии. При 4–15 находках в 7–12 абзацах цикл не
мог сойтись арифметически.

Стало:

| Место | Изменение |
|---|---|
| `services/summary_l2_anchor_repair.py:255` | `group_issues_by_paragraph()` — находки группируются по `paragraph_id` (порядок по id; находка без валидного id не группируется) |
| `services/summary_l2_anchor_repair.py:310` | `build_targeted_revision_batch_content()` — один bounded запрос: все проблемные абзацы, их `problems` (reason/anchors/instruction), `source_excerpts`; output pinned `{"replace_paragraphs":[{paragraph_id,text,source_anchors}]}` |
| `services/summary_l2_review.py:574` | `apply_targeted_revision_batch()` — атомарно применяет замены ТОЛЬКО для `allowed_paragraph_ids` (абзацы, где Reviewer реально заявил находку), затем один §99/anchor-валидатор документа (`validate_l2_document_anchors`) |
| `services/summary_l2_review.py:1365-1412` | цикл: ≥2 абзацев с находками → один batch-вызов; ровно 1 абзац → прежний single-paragraph путь бит-в-бит (`:1413-1454`); `repair_target="targeted_batch"` |
| `services/summary_l2_review.py:645` | `_anchor_source_excerpts_many()` — excerpts для набора находок одного абзаца (anchors dedup, без raw id); одиночная функция делегирует в неё |

Бюджет вызовов не менялся: `MAX_REVISIONS=2`, `MAX_REVIEWS=3`,
`CALL_BUDGET_L2_STAGE=6`; одна ревизия = один LLM-вызов (проверено тестом
`l2_revision_calls == 1`). Планка не снижена: результат по-прежнему проходит
полную anchor-валидацию и полный повторный re-review; `unusable`-gate (D3)
не тронут.

### F2 — durable вердикт/коды/blocking/revision_fixed

`SUMMARY_L2_STAGE` уже эмитится всегда (вкл. прод-путь `_run_writer_source_stage`;
проверено `services/summary_generator.py:2643` — 12-space уровень, вне if/else).
Расширены только его `counts`; новых событий/таблиц/подсистем нет.

| Место | Изменение |
|---|---|
| `services/summary_l2_review.py:903-925` | `MAX_DURABLE_FINDING_CODES=8`, `_durable_review_metrics()` (verdict/blocking/≤8 sorted codes), `_revision_fixed_count()` |
| `services/summary_l2_review.py:1257-1261` | unusable-терминал: durable-поля + `revision_fixed_count` |
| `services/summary_l2_review.py:1535-1545` | approved: `revision_fixed_count` через общий helper + durable-поля |
| `services/summary_l2_review.py:1558-1562` | rejected/soft-only: durable-поля и `revision_fixed_count` теперь считаются и здесь (раньше rejected-путь оставлял дефолтный 0 — артефакт из RCA §7.3) |
| `services/summary_l2_review.py:1694-1699` | degraded-путь: `setdefault` даёт честный `l2_review_last_verdict="degraded"` там, где валидного вердикта модели нет |
| `services/pipeline_events.py:326-340` | `l2_stage()` кладёт в `counts` (usage_json, R17-safe): `review_verdict`, `review_blocking`, `review_finding_codes` (≤8), `revision_fixed` — на approved И rejected/unusable |

### Мусорный quote-hint (RCA §3, пункт 3 делегирования)

Подтверждено кодом: `quote_unverified_count = quotes_total − quotes_verified`
считается ДО deterministic repair (`services/summary_l2_writer.py:1083-1084`),
а repaired/removed цитаты остаются в документе в безопасной форме
(`services/summary_quote_repair.py:330-371`). Поэтому после успешной
валидации счётчик историчен: прод-пример 41/6/11 при `quotes_verified=0`.

`services/summary_l2_review.py:1587` — `_quote_unverified_is_live()`:
подсказка остаётся находкой, только если учёт не закрыт
(`verified + repaired + removed < total`) или есть живой
`quote_unresolved_blockers`. Без accounting-полей (legacy/OFF kill-switch)
сигнал сохраняется — живая проблема не скрывается. Проверки/критерии не
ослаблены: `quote_unresolved_blockers` по-прежнему находка.

## 2. Каноны/фабрика промптов

Изменения канонов НЕ требуются: `SUMMARY_L2_REVISER_SYSTEM_PROMPT`,
`SUMMARY_L2_TARGETED_REVISION_ANCHORS_BLOCK`, `summary_prompts.py` не менялись.
Новый batch-контракт — user-content той же ревизии (аддитивно, только
AnchorSpace targeted path); single-paragraph контракт не изменён.

## 3. Тесты

Новый файл: `tests/test_summary_l2_review_multi_paragraph.py` (11 тестов).

- `test_five_findings_in_three_paragraphs_approved_after_one_revision` —
  5 находок / 3 абзаца → 1 batch-ревизия → approved; проверено, что запрос
  несёт `revision_scope=multiple_paragraphs` и `paragraph_id=[0,1,2]`,
  4-й абзац не тронут.
- `test_batch_revision_that_does_not_fix_is_still_rejected` — анти-тест:
  ревизия применилась, находки те же → `l2_stagnation_fingerprint=1`,
  rejected, `l2_final_approved=0`, `l2_revision_fixed_count=0`.
- `test_unusable_gate_two_hard_two_paragraphs_stays_terminal` — ≥2 hard-кода
  в ≥2 абзацах → `l2_review_unusable`, `review_calls=1`, ревизий 0.
- `test_apply_targeted_revision_batch_*` — чужой `paragraph_id` отклоняется
  атомарно; все разрешённые абзацы применяются с сохранением anchors.
- `test_durable_l2_stage_carries_review_diagnosis_on_approved_path` /
  `..._on_rejected_path` / `test_durable_codes_capped_at_eight` — counts
  события на обоих путях, cap 8.
- `test_rejected_run_metrics_carry_durable_verdict_and_codes` — сквозной
  rejected-run: metrics несут `needs_fixes`, blocking=5, 4 кода, fixed=0.
- `test_quote_unverified_hint_*` — hint снят при закрытом учёте, сохранён
  при живом gap/blocker/legacy-метриках.

Команды и числа (Windows, `.venv\Scripts\python.exe -m pytest`):

| Прогон | До | После |
|---|---|---|
| RED нового файла | `8 failed, 3 passed` | — |
| Новый файл | — | `11 passed` |
| Фокусный набор (10 summary/L2/review файлов, см. ниже) | `330 passed` | `330 passed` |
| Широкий набор summary/l2/review/failsoft (74 файла, `-p no:randomly`) | `1636 passed, 4 failed` (чистый HEAD `468d1041` в изолированном worktree) | `1647 passed, 4 failed` (те же 4) |

Фокусный набор: `test_summary_anchors_wiring_asap42`, `test_asap44_l2_review_closure`,
`test_asap5_summary_domain`, `test_summary_reviewer_source_asap41`,
`test_summary_wave_d_asap4`, `test_summary_source_anchors_asap42`,
`test_asap8_f1_summary_l2_repair`, `test_pipeline_analytics_asap4`,
`test_summary_l2_integration`, `test_summary_l2_writer`.

## 4. Осталось / риски

1. **F3 сознательно не делался** (roster/`run_package` в ревью-контенте и
   правило «сверяй только по source_window») — по решению брифа, после
   деплоя 2.58.112 отдельным решением. Из F3 сделан только quote-hint
   (пункт 3 делегирования, подтверждён кодом).
2. **Деплой не выполнялся** (лейн работает на HEAD). После выката проверить
   в `SUMMARY_L2_STAGE.usage_json`: наличие `review_verdict`,
   `review_blocking`, `review_finding_codes`, `revision_fixed` на обоих
   исходах; и сравнить `findings_total` / долю approved-rejected-unusable
   до/после (RCA §6).
3. **Остаточный риск batch-ревизии:** размер user-контента растёт с числом
   абзацев с находками (ограничен самим черновиком ≤`RICH_MAX_CHARS=32000`;
   полный черновик и так подаётся ревьюеру на той же стадии). Если ревизор
   вернёт неполный batch — вторая ревизия закрывает остаток; если
   malformed — ревизия сгорает как раньше (`revision_invalid_patch`).
4. **Pre-existing, не мой scope:** 4 теста `tests/test_summary_generator.py`
   (`TestPipeline::test_llm_error_retry_then_ux_r13`, `test_db_error_ux_phrase`,
   `test_generic_error_ux_phrase`, `test_ux_send_failure_does_not_crash`)
   падают на чистом HEAD `468d1041` — причина: фикстура `no_sleep`
   (`tests/test_summary_generator.py:18-27`) подменяет
   `services.summary_generator.asyncio` на `MagicMock`, после чего
   `except asyncio.CancelledError` получает не-исключение. К этому лейну
   отношения не имеет; не исправлялось (вне write-scope).
