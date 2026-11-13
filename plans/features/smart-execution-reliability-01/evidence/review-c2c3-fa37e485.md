# Независимое ревью S3-EVIDENCE / C2-C3

- Кандидат: fa37e48522ce3522943442a6e378cc2dc36eb139
- База: 36dd6b232bf2705cc470764a7ab71451c5c49fdf
- Статус: Needs Fixes до завершения обязательных проверок.

## Pillar 1: Implementation

Проверены diff и критические пути services/direct_context_composer.py,
services/evidence_bundle.py, services/response_extent.py и маршрут тестов до
ToolResult/tool-loop/context composer/LLM payload/final answer.

Заводские caps для middle/episode/memory/evidence page/traceback сняты через 0;
положительная явная политика сохраняется; claims больше 10 не обрезаются скрытой
константой; continuation отражается в page metadata. DDL/migration и feature-flag
flip в diff нет.

BLOCKER: git diff --check FAILED: trailing whitespace в измененном
services/direct_context_composer.py (строки 27, 155-224, 433-446, 551, 587-597,
1968-2033). Исправление и повторная проверка обязательны.

thread_walk_max и episode_max_count сохраняют заводские 40/2 и явно помечены
cross-slice residual; системный C2-01 не proven-here. Остальные системные семейства
(tool_router/search_aggregator, vision/OCR, transcripts, factcheck, direct_chat)
требуют integrated release audit и не входят в diff.

## Ledger (предварительно)

SXR-C1-01: UNVERIFIED; SXR-C1-02: UNVERIFIED; SXR-C1-03: UNVERIFIED;
SXR-C2-02: UNVERIFIED; SXR-C3-01: UNVERIFIED; SXR-C2-01: UNVERIFIED/integration-required;
SXR-C3-02: UNVERIFIED/integration-required.

## Pillar 2 / Pillar 3

Проверка тел assertions и запусков будут добавлены после ранней фиксации результата.
Approval невозможен до этого.

## Findings

1. BLOCKER, Builder: trailing whitespace в измененном файле нарушает обязательный
   git diff --check. Исправить только whitespace и повторить diff --check.

Пока reused только C1-документация как контекст; ее counts не являются доказательством
C2/C3. Postdeploy effective-config/live evidence отсутствует.