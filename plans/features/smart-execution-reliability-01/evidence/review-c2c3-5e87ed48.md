# Независимый focused re-review S3-EVIDENCE C2/C3

## Вердикт

**Approved** для S3-EVIDENCE slice scope, candidate `5e87ed48`. Это не закрывает system-wide требования C2-01/C3-02 и не является approval всего эпика.

## Binding

- Candidate: `5e87ed48`
- Previous candidate: `fa37e485`
- Base: `36dd6b232bf2705cc470764a7ab71451c5c49fdf`
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\SMART-EXECUTION-RELIABILITY-01-92d1db8aefb1-1754cefe`

## Три доказательных опоры

**Implementation:** повторно проверен diff `36dd6b23..5e87ed48` и callers для `direct_context_composer`, `evidence_bundle`, `response_extent`, SourceReader/tool-loop. `git diff -w fa37e485 5e87ed48 -- services/` не выводит изменений: correction только LF/trailing-whitespace. Factory caps сняты в scope; explicit policies, continuation, semantic selection сохранены. Нет DDL/migration, flag flip, paraphrase-stage или instruction-truncation quota.

**Test validity:** assertions нового `tests/test_smart_exec_evidence.py` и двух legacy-тестов проверяют counts/order, explicit env boundaries, continuation non-overlap, provenance, byte-identical role-tool payload и финальный ответ из payload. `C2/C3`: `C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest -q tests/test_smart_exec_evidence.py` -> **24 passed in 3.37s**. C1 regression: `... -m pytest -q tests/test_smart_c1_source_reader_limits.py tests/test_evol_source_reader.py` -> **101 passed in 4.69s**.

**Independent challenge:** повторно подтверждены adversarial explicit caps (middle=5, episode=10, fetch=3, longform=20000), no-cap при garbage/negative env, oversized evidence при `budget_tokens=0` без dropped и explicit budget с visible compression/provenance. Mutation proof из предыдущего review сохранён: возврат middle=60 дал 1 failure; после восстановления тест зелёный.

## Проверки correction

- `git diff --check 36dd6b23 5e87ed48 -- services handlers tests` -> **чисто, вывода нет**.
- `git diff -w fa37e485 5e87ed48 -- services/` -> **нет вывода**, behavior-relevant изменений нет.
- Документационные evidence-файлы не включались в code diff-check.

## Acceptance ledger

- `SXR-C1-01/02/03`: **VERIFIED** для slice; C1 suites зелёные.
- `SXR-C2-02`: **VERIFIED** для изменённого S3 поведения: semantic selection сохранён, continuation доступен, первая порция не объявляется exhaustive.
- `SXR-C3-01`: **VERIFIED для SourceReader seven-step path**. Для search/memory/OCR/transcript/factcheck в S3 проверены structured result -> ToolResult/evidence -> tool-loop -> payload (steps 2-6); provider step 1 для этих пяти типов остаётся вне этого slice.
- `SXR-C2-01`: **UNVERIFIED system-wide / integration-required**.
- `SXR-C3-02`: **UNVERIFIED system-wide / integration-required**.

## Integration-required / residual

Нужен integrated-release audit для untouched `tool_router`/search aggregation, vision/OCR providers, transcript engines, factcheck, `direct_chat_service` message-length/memory/L1/writer/fallback/reserve paths, а также provider-specific delivery. Production effective `flags.budgets_enabled`, chat overrides, production env caps и live provider LLM payload в этом review не наблюдались. Эти остатки не блокируют approval именно S3 slice scope, но не позволяют пометить C2-01/C3-02 system-wide VERIFIED.

Web sources не требовались: все утверждения проверяемы по repository diff/tests. Code/maps/statuses не изменялись этим review.
