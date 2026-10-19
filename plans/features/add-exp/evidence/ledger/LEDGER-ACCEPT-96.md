# LEDGER-ACCEPT-96 — привязка живой приёмки ADD-EXP (2.58.96)

Дата: 2026-10-20 (system local +12:00). Режим: docs-only; код, прод, `workflow_state.md`,
`progress_scope.json` и пользовательский `plans/current_task.md` не менялись.

Основание: `plans/features/add-exp/review-accept-96.md` (REV-ACCEPT-96, коммит `040c0496`,
вердикт **Needs Fixes**) + `plans/features/add-exp/acceptance-96-report.md` +
`plans/features/add-exp/evidence/release-25896/acceptance/**` (53 файла в checksums).

Кандидат/деплой: **2.58.96 @ `95d11472b9e533b554554918e3efa6b42125260b`**
(T0 2026-10-19 14:51:18Z, MainPID 3739015, NRestarts=0). Карта `add-exp` переведена на этот
candidate/deployed; старые evidence-записи сохраняют исторический candidate `4a09e29a`.

## 1. Статусы после леджера

| Статус | Кол-во |
|---|---:|
| VERIFIED | **28** |
| FAILED | **1** (`EXP-ACCEPT.CRITERION`) |
| READY_FOR_LIVE | **0** |

### Закрыто/подтверждено VERIFIED

| Строка | Что закрыто | Evidence |
|---|---|---|
| `EXP-RUNTIME.WIRING` | 27 ходов / 28 L2-вызовов с маркером; `wire_with_marker=28`, `wire_with_mode_line=28`, `wire_expected_text_present=28`; 54/81 composes с рендеренным слоем, 27 skip — только `profile:machine_stage`; Direct/tool_phase + Initiative/authorial (follow-up) | `…/acceptance/summary.json`; `…/followup/routes.json` |
| `EXP-RUNTIME.PAYLOAD` | `full_l2_system_sample` 7070 симв. с `<Expression_Settings>` и строкой `frequent`; raw == доставка; прямая просьба в `frequent` дала мат; fallback/ошибок LLM 0 | `…/followup/summary.json` |
| `EXP-ACCEPT.ROUTES` | A=`frequent` / B=`off` одновременно; wire-строки A 2/2 `frequent`, B 2/2 `off`, маркеры 2/2; B 0/2 мата; preview==resolve; reread; без рестарта. Основная волна `isolation=PARTIAL` раскрыта, follow-up PASS | `…/followup/isolation.json`; `…/acceptance/routes.json` |
| `EXP-ACCEPT.LIVE-SET` | Набор выполнен: 27 ходов основной волны (7 контекстов × 3 режима + 3 повтора + 2 жанровые) + 7 follow-up; L1 micro 16/compact 10/auto 1; все ответы сохранены | `…/acceptance/summary.json`; `…/followup/summary.json`; `checksums.json` |
| `EXP-ACCEPT.PREVIEW` | `preview_eq_resolve=true` для off/occasional/frequent; `text_sha12` = ревизия слоя (`9de5c885b622` / `537816072dab` / `6763c903ffc2`); `expected_text_present=true` в каждом L2-wire | `…/acceptance/summary.json`; `…/acceptance/routes.json` |
| `EXP-ACCEPT.REVIEW` | Независимый Reviewer проверил личность/речь/факты/цитаты/разметку/регрессии; отчёт «было/стало», тесты, версия прода | `plans/features/add-exp/review-accept-96.md` |
| `EXP-INSTR.FEWSHOT` | Остаётся VERIFIED: 12 драфтов `expression_register`, `owner_approved=0`, повторный seed skipped; `<Expression_Examples>` в composed/wire = 0, 54 trace `not_owner_approved` — в runtime не идут | `…/acceptance/p1-seed.json`; `…/acceptance/summary.json` |

**Оговорки, зафиксированные в note:**
- `LIVE-SET`: 7-я occasional-проба — точный дубль `occasional-04-everyday`, не новая вариация.
  Строка закрывает **факт выполнения набора**, а не поведенческое различие режимов.
- `FEWSHOT`: опциональный owner-вход 4+4 (behavior-diag) — **не Human Gate**, не блокирует F1;
  без одобрения черновики в runtime не идут.
- `ROUTES`: `isolation` основной волны = PARTIAL (дефект порядка harness), PASS только в follow-up.
- `PAYLOAD`: live-факт deployed code path, не per-turn журнал MainPID.

## 2. FAILED — критерий §4

`EXP-ACCEPT.CRITERION` → **FAILED** (схема допускает `FAILED`; release-гейт принимает только `VERIFIED`).

- `off`: 0/5 разговорных с матом — **PASS**.
- `occasional`: 0/7 (с добором 0/7) при требовании `>0` — **FAIL**.
- `frequent`: 0/7 (0/9 с follow-up) при требовании ≥50%, ≥2× occasional, ≥3 контекста — **FAIL**.
- Класс: `model_ignored_instruction` N=9; wire-слой доставлен и подтверждён, но модель не меняет речь.
- `note`: **«behavioral criterion FAILED at acceptance-96; source §4 not met»**.
- Follow-up: **F1** (операционный триггер/текст), **F4** (disjoint-пробы + полная матрица §7.2);
  после F1 эвиденс приёмки недействителен, матрицу нужно прогнать заново. **Parent не DONE.**
- Опциональный F2 (одобрение 4+4 few-shot) — owner-вход, не блокирует F1 и не является Human Gate.

## 3. Гейты

Полные логи: `plans/features/add-exp/evidence/ledger/accept96-gates.txt`.

| Прогон | rc | Итог |
|---|---:|---|
| plan | **0** | `inventory=20 manual=17 errors=0` |
| release `95d11472` | **1** | 22 ошибки = 21 историческая VERIFIED-строка без привязки к `95d11472` (только `4a09e29a`) + 1 ожидаемая `EXP-ACCEPT.CRITERION: mandatory not ['VERIFIED'] (got FAILED)` |
| review `EXP-RUNTIME` | **1** | 9 исторических строк без привязки (`READSAVE/PRIORITY/DIAG/DIAG-*/E1/E2/E4/E6`); WIRING/PAYLOAD проходят |
| review `EXP-ACCEPT` | **1** | 2 ошибки: `EXP-REG.QUEUE` без привязки + `EXP-ACCEPT.CRITERION` FAILED; LIVE-SET/ROUTES/PREVIEW/REVIEW проходят |
| review `EXP-INSTR` | **1** | 3 исторические строки (`ADD-1.E7`, `POSITIVE`, `NOPOST`); FEWSHOT проходит |
| review `EXP-UI` | **1** | 8 исторических строк без привязки; acceptance-touched UI-строк нет |

Release rc=1 — **обязательный и честный** результат: критерий §4 не достигнут. Остальные release-ошибки —
исторические строки, не перепривязанные к кандидату приёмки, а не новые дефекты.

## 4. Девиации и границы

1. Перепривязаны только acceptance-touched строки; 21 историческая VERIFIED-строка сохраняет
   evidence кандидата `4a09e29a` — поэтому release-гейт не зелёный. Массовый rebind без нового
   прогона этих строк не выполнялся (это было бы выдачей старого эвиденса за приёмку 96).
2. Неточности отчёта (`42` вместо `45` удалений, baseline restore, пометка follow-up в изоляции,
   дубль occasional, разделение 56/81 LLM-вызовов) **не исправлялись** — по заданию это отдельный лейн;
   в леджере используется проверенная цифра REV-ACCEPT-96 — **45 удалений, residual 0**.
3. `design-add-exp.md` и `evidence/instr-fix/` имеют чужие незакоммиченные изменения/файлы — не тронуты.
4. Код/прод/`workflow_state.md`/`progress_scope.json` не менялись; rollback не требуется
   (глобальный `character.expression` не менялся, A/B восстановлены, default `occasional`).
5. Секретов в добавленных путях нет; evidence уже checksum-bound (`checksums.json`, 53/53).
