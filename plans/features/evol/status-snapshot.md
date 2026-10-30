# EVOL — статус по требованиям (снимок 31.10.2026)

Карта: `plans/features/evol/requirements-map.json` (46 обязательных требований: EVOL-001..045 + EVOL-DoD).
Ветка реализации: `evol/impl`, вершина `18baa36b`. Деплой не выполнялся.

## Как записан статус

Словарь `requirements_gate.py` строгий: `PENDING | BUILDING | REVIEW | VERIFIED | FAILED | BLOCKED_REAL_HUMAN_GATE | READY_FOR_LIVE`.
Поэтому ревью-принятые, но **не задеплоенные** требования держат `status: PENDING` + `review_verdict: "APPROVED"`,
`review_candidate`, `review_scope`, `review_note` и привязку доказательств (`evidence[]`: `ref`, `observation`, `type`,
`artifact_path`, `artifact_branch`, `artifact_sha256`, `candidate_commit`). `VERIFIED` сознательно не выставлен.
Артефакты-отчёты лежат в ветке `evol/impl` (`plans/features/evol/audit/w*.md`) и в `master` ещё не влиты.

## Таблица

| Задача | Backend | UI | Ревью | Деплой |
|---|---|---|---|---|
| EVOL-001 | PASS (`4fcbf684`+`98d16b94`) | PASS (живой рендер Playwright) | APPROVED | не задеплоено |
| EVOL-002 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-003 | PASS (`98d16b94`) | PASS (focus trap в review-fix) | APPROVED | не задеплоено |
| EVOL-004 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-005 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-006 | PASS (`4fcbf684`+`98d16b94`) | n/a (промпт/данные) | APPROVED | не задеплоено |
| EVOL-007 | PASS (`3d52e487`) | n/a (виджет закрыт в 001..005) | APPROVED | не задеплоено |
| EVOL-008 | PASS (`3d52e487`) | n/a | APPROVED | не задеплоено |
| EVOL-009 | PASS (`a02aca0c`) | n/a (данные, не экран) | APPROVED | не задеплоено |
| EVOL-010 | PASS (`0e853f7f`) | n/a | APPROVED | не задеплоено; live-проверка после релиза |
| EVOL-011 | PASS (`dc1fdba6`) | n/a | APPROVED | не задеплоено |
| EVOL-012 | PASS (`44437903`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-013 | PASS (`dc1fdba6`) | n/a | APPROVED | не задеплоено |
| EVOL-014 | PASS (`9eeb3532`+`a02aca0c`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-015 | PASS (`e7443fad`) | n/a | APPROVED | не задеплоено |
| EVOL-016 | PASS (`44437903`+`011fe8ff`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-017 | PASS (`be5ad652`) | PASS (`be5ad652`) | APPROVED | не задеплоено |
| EVOL-018 | PASS (док-контракт `95b8d275`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-019 | PASS (`4fcbf684`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-020 | PASS (`98d16b94`; F1/F2 в `18baa36b`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-021 | PASS (`4fcbf684`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-022 | n/a (фундамент) | PASS (слой токенов, `33a14034`) | APPROVED | не задеплоено |
| EVOL-031 | PASS (`28d55bd1`…`7492d325`) | n/a (UI-карточка удалена) | APPROVED | не задеплоено; live-проверка после релиза |
| EVOL-032 | n/a (фундамент) | PASS (`33a14034`) | APPROVED | не задеплоено |
| EVOL-023..030 | не начато | не начато | — | — |
| EVOL-033 | не начато | не начато — **интеграционный гейт** | — | — |
| EVOL-034..045 | не начато | не начато | — | — |
| EVOL-DoD | не достигнуто (нужен релиз + EVOL-033) | — | — | — |

Итого привязано доказательств: **24 требования** (001..022, 031, 032). Не начато: 23 требования (023..030, 033..045) + DoD.

## Гейт плана

`py C:\Users\main\.config\opencode\tools\requirements_gate.py check --map plans/features/evol/requirements-map.json --stage plan --repo .`
→ **EXIT 1**, `inventory=304 manual=236 errors=103`. До привязки доказательств было ровно то же: **errors=103** (мои правки новых ошибок не добавили).

Состав ошибок (пред-существующие, не связаны с этой привязкой):

1. `authoritative source changed: reconcile user task and rebuild map` — sha `plans/current_task.md` изменился
   (`dec5a583…` сейчас против `54454df5…` в карте).
2. 102 × `source item not mapped L00915..L01149` — владелец дописал в конец `current_task.md` новый блок директив
   (строки ~911-1155: социальный контекст, видео-intent, фактчек-критика, шов стекла EVOL-032, порядок работ).

Это **незакрытая дельта требований**, а не дефект карты. Её нужно обработать отдельно: снять неизменяемый
снапшот дописанного блока в `plans/owner_inputs/`, зарегистрировать вход, разложить новые пункты по требованиям/слайсам
(там появляются новые общие контракты → вероятно `ARCHITECT_REQUIRED`), после чего повторить гейт.

## Что дальше

1. Orchestrator: перенести обновлённую карту в ветку `evol/impl` (в `master` каталог `plans/features/evol/` сейчас **untracked**, правка живёт только в рабочей копии).
2. Orchestrator: закрыть дельту источника (owner_inputs + новые строки карты + слайсы), затем гейт должен упасть только на реально неготовых пунктах.
3. Ревью `18baa36b` → снять `ui_review: pending` у 014/019/020/021 и привязать UI-доказательства.
4. Затем EVOL-033 как интеграционный гейт, после него — релиз и `VERIFIED` (для 010/031 плюс live-проверка на проде).
