# ADD-EXP — ledger: биндинг кандидата `4a09e29a` (LANE LEDGER-ADD-EXP, 20.10.2026)

- **Кандидат:** `4a09e29a62488b204acea7f821b81fa31dd91e0e` (26 файлов: 15 код/тест + `.gitignore` + `evidence/build/**`; родитель `d0afd2cc` — RECHECK `review-add-exp.md` Approved, BLOCK-1 закрыт).
- **Вход:** леджер-заметки ревью `review-add-exp.md` (RECHECK §«Леджер-заметки»): **24 → VERIFIED** (23 раунда 1 + `EXP-INSTR.FEWSHOT` после RECHECK), **5 → READY_FOR_LIVE** (Ф6 postdeploy).
- **Запись:** `plans/features/add-exp/requirements-map.json` — `candidate_commit := 4a09e29a…`; все 29 required-строк привязаны; 8 context-строк не тронуты (PENDING, без evidence); ранее закрытые F0-строки (`EXP-DIAG-PROD`/`EXP-DIAG-PAYLOAD`) сохранены как VERIFIED (как в раунде 1).

## Гейты (verbatim `py -3 requirements_gate.py`, `--repo .`)

| Гейт | scoped | errors | EXIT | Лог |
|---|---|---|---|---|
| plan | 0 | 0 | 0 | `gate-plan.txt` |
| review EXP-UI | 8 | 0 | 0 | `gate-review-EXP-UI.txt` |
| review EXP-INSTR | 4 | 0 | 0 | `gate-review-EXP-INSTR.txt` |
| review EXP-RUNTIME | 11 | 0 | 0 | `gate-review-EXP-RUNTIME.txt` |
| review EXP-ACCEPT | 6 | 0 | 0 | `gate-review-EXP-ACCEPT.txt` |

Итого review-scope = 8+4+11+6 = 29 required-строк; `stage=review inventory=20 manual=17`.

## Статусы

- **VERIFIED — 24:** `EXP-UI.MODES/OFF/OCC/FREQ/INHERIT/MIGRATION`, `EXP-INSTR.POSITIVE/FEWSHOT/NOPOST`, `EXP-RUNTIME.READSAVE/PRIORITY/DIAG`, `EXP-ACCEPT.PREVIEW/REVIEW`, `EXP-REG.QUEUE`, `EXP-DIAG-PROD/DIAG-PAYLOAD`, `ADD-1.E1–E7`.
- **READY_FOR_LIVE — 5:** `EXP-RUNTIME.WIRING`, `EXP-RUNTIME.PAYLOAD`, `EXP-ACCEPT.LIVE-SET`, `EXP-ACCEPT.ROUTES`, `EXP-ACCEPT.CRITERION` — с `live_note`: **Ф6 postdeploy** (набор 20–30 проб §7.2/Ф6: изоляция `frequent`/`off`-чатов, переключение без рестарта, reread после сохранения, preview vs production trace, реальный complete LLM payload прода); код-половина каждой строки закрыта evidence, живая — честно остаётся на постдеплой.
- **Context — 8:** не тронуты.

## Evidence-привязка

34 evidence-записи; каждая required-строка имеет ≥1 запись с `candidate_commit = 4a09e29a…`, непустыми `ref`+`observation`, `type`, `artifact_path` и `artifact_sha256`. 8 артефактов, все существуют, sha256 пересчитаны и совпали на момент биндинга:

- `plans/features/add-exp/review-add-exp.md` (вердикт раунд1+RECHECK);
- `plans/features/add-exp/evidence/build/README.md`, `green-focused.txt`, `red-block1.txt`, `ui-e2e.json`;
- `plans/features/add-exp/evidence/f0/README.md` (Ф0);
- `plans/features/add-exp/prep-add-exp.md`;
- `tests/test_add_exp_expression.py`.

## Девиации

1. У 5 RFL-строк добавлено поле `live_note` (конвенция CFG-01/02A); схема гейта его допускает, `status`/`live_required`/`live_when` соответствуют леджер-заметкам ревьюера.
2. RFL-строки **не закрыты**: release-стадия требует VERIFIED + production-typed evidence — только после деплоя и Ф6.
3. `deployed_commit` пуст — заполнит релизный лейн после выката.

## Следующее

Релизный лейн: изолированный деплой `4a09e29a` → `deployed_commit := <SHA>` → `check --stage release --candidate 4a09e29a… --deployed-commit <SHA>`; затем Ф6 закрывает 5 RFL-строк production-эвиденсом (harness сам сохраняет тексты ответов — прод их не хранит, Ф0 §3).
