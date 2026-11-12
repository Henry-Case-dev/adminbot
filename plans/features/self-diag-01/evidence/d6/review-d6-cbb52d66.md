# D6 B1-B4 - независимое re-review

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code `cbb52d66068e0e0595fd91717556ea9d4be22fb0`, docs `fb545aed7287d446b94a40ec9ad0f27c9f3adcf4`.
База: `722ccfc5`; предыдущий кандидат `61e50806` (Needs Fixes B1-B4).
Diff `fc0657ba..HEAD`: code/тесты в `services/checkup_service.py`, `handlers/checkup.py`,
`services/tool_router.py`, `web/api/routes.py`, `tests/test_checkup_contract.py` и
затронутых тестах; UI/промпты/настройки не менялись.

**Вердикт: Needs Fixes.** B1 и B4 исправлены и независимо подтверждены; B2/B3 исправлены частично.
B3 исправлен частично: остаётся воспроизводимый ложный `measured=true,value=0`
при blocked-checkup validation. D6/self-diag DONE не объявляются.

## 1. B1 - телеметрия эффективного промпта: исправлено

`services/checkup_service.py:56-140` принимает per-run `telemetry`, source берёт
через `resolve_prompt_with_source`, hash/длину считает по финальному `system`
после `{max_symbols}`, owner-block и fallback-notice. `handlers/checkup.py:425-
489` создаёт `run_telemetry` на вызов; общего `last_run` больше нет.

Независимый fake LLM (два конкурентных чата, `used_fallback=True`):

```text
CHAT 1 HASH_MATCH True LEN_MATCH True SOURCE default HAS_LAST_RUN False
CHAT 2 HASH_MATCH True LEN_MATCH True SOURCE default HAS_LAST_RUN False
DISTINCT_HASHES True
```

`prompt_readback_allowed` теперь эмитится только для `status=delivered`
(`services/tool_router.py:1645-1650`); partial/invalid_request/not_found/
revision_unavailable тестом исключены. B1 снят.

## 2. B2 - success-статусы: исправлено

`web/api/routes.py:3665-3750` использует закрытый `_self_diag_row_state`:
`report_sent`, `called`, `clean`, `delivered` -> complete;
`cooldown/denied/busy/no_gate/disabled` -> skipped; `degraded` и остальные
ошибки -> partial; `last_success_ts` заполняется по complete.

Независимый прогон `_self_diag_stats` на смеси событий:

```text
checkup_triggered: calls=5 partial=0 complete=1 skipped=4 partial_share=0.0 last_success_ts=1010
get_bot_health_called: calls=1 partial=0 complete=1 last_success_ts=1005
inspect_runtime_called: calls=2 partial=1 complete=1 partial_share=0.5
only_cooldown: calls=1 partial=0 complete=0 skipped=1 measured=false
```

B2 success-статусы исправлены, но есть остаточный блокер: комментарий `_SELF_DIAG_SKIP_STATUSES`
говорит «не идут в calls», но `calls` пока равен числу всех событий, включая
skipped; это не влияет на complete/partial/partial_share и не является
блокером, но стоит привести семантику к комментарию.

## 3. B3 - secret_value_disclosures: остаётся блокер

`handlers/checkup.py:439-448` эмитит `checkup_output_validated` ПОСЛЕ
`diagnostic_policy.publish`, но ДО проверки `publication.allowed`. Поэтому
валидация заблокированного отчёта тоже попадает в счётчик `checkup_validated`.
`web/api/routes.py:3761-3818` считает все `checkup_output_validated` без
фильтра статуса (`blocked` тоже считается). Дополнительно: `diagnostic_policy.Publication` имеет свойство `.status` и поле `.redaction`, но не `.report`; `getattr(publication, "report", None)` всегда None, поэтому `checkup_output_validated` получает status `unknown`, а не clean/partially_redacted/blocked.

Воспроизведение на уровне `_self_diag_validation_coverage`: один успешный
`checkup_triggered/report_sent`, один `checkup_triggered/publication_blocked` и
один `checkup_output_validated/blocked`:

```text
{"value": 0, "measured": true, "reason": "enforcement_measured",
 "deliveries": {"checkup": 1, ...},
 "validated": {"checkup": 1, "tools": {}}, "gaps": {}}
```

Успешный чекап в этом наборе не имеет собственного validation-события, но
blocked-событие закрывает gap и даёт ложный «измеренный 0». Это ровно тот
случай, который B3 должен исключать: validated должен коррелировать с
доставкой, а не с любой validation-записью.

**Минимальный fix:** брать `publication.status` (а не несуществующий `.report`), эмитить `checkup_output_validated` только после
`publication.allowed` (для отправленного отчёта) либо учитывать только
`status in ("clean","partially_redacted")` и не считать `blocked`. Добавить
тест: blocked validation + успешный checkup без своего validation ->
`measured=false`, `gaps.checkup=1`.

Остальные B3-сценарии подтверждены: посторонний tool validation ->
`measured=false`, `value=null`, `gaps.checkup=1`; paired checkup+inspect ->
`measured=true`, `value=0`.

## 4. B4 - configured источников: исправлено

`handlers/checkup.py:115-135` добавляет `checkup_probe_deps()` из существующих
db/memory/fetcher/status; `web/api/routes.py:3826-3840` передаёт deps в
`probe_catalog(deps=...)`. Probes не исполняются.

Независимый вызов с тематическими сервисами: `DEPS ProbeDeps` со всеми
четырьмя источниками, `TOTAL 24, CONFIGURED_FALSE 0`; `media.stt`,
`scheduler.jobs`, `memory.health` -> `configured=True`. Ловушка
`_probe_service_runtime` не вызвана (тест `test_catalog_does_not_execute_probes`).

## 5. Тесты и mutation

- `pytest tests/test_checkup_contract.py -q` -> **34 passed**.
- Broad focused D6+D3/D4/D5 (22 файла) -> **927 passed**, 1 warning.
- D4-B+prompt contracts -> **661 passed, 1 failed**; failure
  `test_mca10b_random_applications_block_d_round1041.py::test_blockE_f8_check_green_and_baselines`
  (`assert "643" in "CHECK OK: реестр 644"`), pre-existing D4-B pin; BACKLOG.
- **Independent mutation:** в отдельном worktree @ `cbb52d66` из
  `_SELF_DIAG_SUCCESS_STATUSES` удалён `report_sent`;
  `TestB2SuccessStatuses` -> **2 failed** (`complete == 0`); restore ->
  **34 passed**.
- RED/GREEN B1-B4 на старом кандидате (`61e50806`) по binding: 12 failed/1 passed;
  на новом кандидате все 34 green. B3 blocked-edge тестом не покрыт.

## 6. Строки D6

- **Исправлено и candidate-supported:** `SD1-D6-05` (B1),
  `SD1-D6-12/16` (B4; UI render D7).
- **Остаётся частично/FAILED:** `SD1-D6-18` (B2 skipped в calls/latency),
  `SD1-D6-17` (B3 blocked-validation edge).
- **Не REVIEW на этом кандидате:** остальные D6-строки; после B3 fix нужен
  короткий focused re-review. D7/live остаются: реальный Telegram/VPS,
  UI-рендер, golden eval, hypothesis shares, history growth, code-vs-wrong-SHA.
- D3/D5/D4 не сломаны: 927/661 проходят, merge-коммиты чистые, approved
  behavior сохранён. `SD1-D6-07` дважды в карте и `mca10b` pin - PM/backlog.
- API отказа self-diagnosis по-прежнему 200 restricted, не 403; данные не
  утекают; вопрос API-семантики не блокер без явного 403-контракта.

## 7. Три опоры

- **Implementation:** прочитаны diff B1-B4, checkup handler/service, prompt
  telemetry, validation correlation, probe deps, tool_router stage; проверены
  per-run telemetry, success mapping, mixed validation и отсутствие probe
  execution.
- **Test validity:** 34/927/661 запусканы; mutation B2 red/restore green;
  assertions B1-B4 прочитаны. B3-тесты не покрывают blocked validation +
  успешный checkup, поэтому 34 green не опровергают остаточный дефект.
- **Independent challenge:** fake LLM два чата (hash/source/length match, no
  shared last_run); `_self_diag_stats` success/skip/degraded; mixed validated;
  blocked validation + success -> false `measured=true`; `probe_catalog` 0/24
  false. Mutation отдельно.

## 8. Итог

**Needs Fixes** по остаточным B2 и B3. B1/B4 можно считать проверенными
на этом кандидате; после минимального B3 fix нужен focused re-review D6.
Карта/progress_scope не менялись; продуктовый код/настройки/прод не менялись;
деплоя не было; mutation worktree и probe-run закрыты.


## 9. B2 residual (blocking)

`_self_diag_stats` считает `calls` и `durations` по всем событиям, включая
`skipped`; `_SELF_DIAG_SKIP_STATUSES` в коде говорит «не идут в calls», но
`calls=len(subset)`. Поэтому cooldown/denied/busy/no_gate попадают в число
вызовов и в p50/p95 с duration 0.

Воспроизведение: `report_sent` 900 ms + `cooldown` 0 ms:

```text
{"calls": 2, "partial": 0, "complete": 1, "skipped": 1,
 "partial_share": 0.0, "p50_ms": 450.0, "p95_ms": 855.0, "measured": true}
```

Для одного реального чекапа это дает 2 вызова и заниженную latency; UI
показывает `analytics.checkup.calls` и p50/p95. Нужно исключить skipped из
`calls`, `durations`, `by_stage.calls` (или добавить отдельный triggered-count)
и тестом проверить `calls=1`, `p50=900`.

