# P0 CORRECTIVE — полный Core, Writer без мета-структуры, code-canon L1

- **LANE_ID:** `P0-FINAL-CORE-WRITER` (Builder, writer-only; без прода/Telegram/LLM).
- **Worktree:** `C:\Code\Python\adminbot-wt-speech-p0`, база `52061e3f`, ветка `task/speech-p0-hotfix`.
- **Источник:** `source-owner-p0-corrective-2026-10-25.md` §1.1/§3; `evidence/p0-hotfix/probes_final.md`; `l1-harness-audit.md`.
- **Статус:** код + офлайн-проверки готовы; live A/B на новом каноне и независимое ревью остаются.

## 1. Core: payload без обрезки (§3)

`services/prompt_composer.py::simplify_core_for_prompt` — теперь identity/fail-safe:
возвращает текст без изменений, ничего не вырезает (прежние литералы
`_CORE_*` сохранены как исторические слепки и в сборке не участвуют).

| Редакция | chars | sha12 | payload |
|---|---|---|---|
| активный owner-Core (`character.core`, rev 8) | 3294 | `ead77b2ab509` | **3294 целиком** |
| было до правки (P2/P5/P3 вырезаны) | 3294 → 1246 | `4e67334b00ad` | 1246 (дефект) |
| заводской v3 | 3224 | `5597c09dd5f8` | 3224 целиком |

Хранимый Core в БД не меняется. Тесты:
`tests/test_speech_p0_core_serious.py::test_active_core_payload_keeps_all_paragraphs_verbatim`
(P1/P2/P3/P4/P5/P6 присутствуют, 3294, `ead77b2ab509`),
`::test_core_filter_is_pure_and_idempotent`, `::test_factory_core_is_not_truncated`;
`tests/test_p0_checkup_core_contract.py::test_core_paragraph_reaches_runtime_composition`
(абзац «Как говорить о реальных событиях» реально доходит до `manifest.system`).

## 2. Writer: без мета-вступлений и навязанной структуры (§3)

Точные `ANALYSIS_DIRECTIVE_TEXT` / `ANALYSIS_WRITER_TEXT` не изменены.
Добавлен `services/prompt_style_blocks.py::NO_META_STRUCTURE_TEXT` (173 симв.):

> Не анонсируй разбор и не сообщай, что сейчас будешь делать. Не нумеруй пункты и
> не делай отчётную структуру, если пользователь не просил об этом прямо.
> Начинай сразу с сути.

Он входит в `MODE_DEEP_RESEARCH_BLOCK` и в `direct_l1.build_l2_plan_block(include_analysis=True)`
(строка «как начать ответ: …»), т.е. покрывает и deep-режим, и serious-разбор,
где extent-блок вытесняет режимный блок. Лимитов длины и обязательных схем не
вводится. Тесты: `test_writer_no_meta_and_no_imposed_structure`,
`harness_probe_full.py --self-check → no_meta_directive_present`.

## 3. L1: code-canon и детерминизм (§1.1)

- Семантика ред.2 (без списков слов): если просьба соединяет разбор
  накопленного материала с финальным вопросом-оценкой, приоритет у разбора —
  оценка становится его выводом. Принудительной подмены плана нет.
- Активный канон: `DIRECT_L1_PLANNER_SYSTEM_PROMPT` = **9288 симв.,
  `23aae0c9499d`**; предыдущие активные байты — `PREV_DIRECT_L1_PLANNER_P0CS2`
  = **9145, `f6f5d3b1fc1d`**; `PREV_DIRECT_L1_PLANNER_P0CS` = 8574, `8ef75b632d12`;
  `PREV_DIRECT_L1_PLANNER_R3B` = `6c2ddc17c998` (не изменён).
- `PROMPT_MIGRATIONS`: `P0CS2 → ACTIVE`, `P0CS → ACTIVE`, `R3b → ACTIVE` —
  при деплое PG-значение (прод сейчас `6c2ddc17c998`) обновится до `23aae0c9499d`
  одним шагом; кастом владельца не перетирается (точное совпадение байт).
- `ROLLBACK_MIGRATIONS` (ADR-1013-3): `ACTIVE → P0CS2 → P0CS → R3b → R3 → 2.58.113`
  — пять вызовов, стек прежних ступеней цел.
- Реестр: метка `l1-planner-material-priority`, `verbilizer.mode.deep_research` —
  `mode-p0h-no-meta`; `FACTORY_SET_SHA256_12` = `9f28ff7f6a77` (было `9de29133885a`).

## 4. Harness: источник канона честно помечен (§1.2)

`probes_full/harness_probe_full.py`:
- новый явный флаг `--use-code-l1-canon` (эквивалент `--l1-prompt code`);
  `--l1-prompt pg` оставляет чтение PG;
- в результате `l1_canon.canon_source ∈ {code, pg}`, `code_canon_requested`,
  `pg_matches_code`, `code_sha12`; при PG ≠ code пишется `l1_canon_stale_pg=true`;
- `--self-check` теперь проверяет: счётчики 1×1, отсутствие ASCII-маркеров,
  предикат, mode=serious, семантику code-canon (`material routing`, приоритет
  разбора, отсутствие литеральных фраз запроса), что code-canon не равен ни
  одной прежней ступени, полный Core и наличие no-meta директивы.

Локальный `--self-check`: **PASS** (все 11 пунктов true), `code_l1_canon.sha12=23aae0c9499d`,
`prev_p0cs2_sha12=f6f5d3b1fc1d`.

## 5. Проверки

- `py_compile` семи изменённых модулей + harness — rc=0.
- `pytest` профильный набор (core-serious, corrective-route, prompt-migrations,
  asap2-clar, r3b-canon, l1d-contract, p0-prompts-core, expression-isolation,
  w1-semantics, checkup-core-contract, p0-hotfix-texts) — **170 passed**.
- `pytest tests -k "prompt or speech or core or composer or direct_l1"` —
  **1337 passed, 5 failed**; все 5 — предсуществующие на базе `52061e3f`
  (`tests/test_soul1_composer_parity_off.py`: записанный дамп SOUL-1 устарел;
  проверено отдельным worktree на чистом HEAD — те же 5 падений).
  `tests/test_samples_fewshot.py` (Expression `frequent`, 2 теста) —
  тоже предсуществующее расхождение констант, `mca_expression.py` не менялся.

## 6. Что остаётся

- Live A/B на code-canon `23aae0c9499d` (`--use-code-l1-canon --repeats 2`) +
  forced research — подтвердить research-маршрут и отсутствие метавступлений.
- Независимый Reviewer: Core 3294 в фактическом payload, отсутствие нумерации
  без просьбы, честность `canon_source`/`FACTORY_SET_SHA256_12`.
- Deploy-миграция PG `6c2ddc17c998 → 23aae0c9499d` выполняется штатным
  `migrate_prompt_canons` при старте; проверить на проде после выката.
