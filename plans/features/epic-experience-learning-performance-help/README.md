# epic-experience-learning-performance-help

Треки **E** (реальное обучение на опыте), **P** (ускорение Mini App/desktop) и **H** (финальная
актуализация «Справки»). H — единственная строгая финальная зависимость и не открывается до тех пор,
пока все предыдущие задачи очереди (включая E и P) не будут реализованы, приняты Reviewer, развёрнуты
и проверены live.

## Источник

- Вход: `OI-2026-11-02-EXPERIENCE-LEARNING-PERFORMANCE-HELP` (new_task) + дополнение
  `OI-2026-11-02-PERF-PARITY` (amendment, паритет трека P).
- Дословный снимок: `plans/owner_inputs/2026-11-02-experience-learning-performance-help.md` (348 строк,
  `plans/current_task.md` 4030–4365) и `plans/owner_inputs/2026-11-02-performance-parity-clarification.md`
  (18 строк). Оба owner-файла не редактировались; для строгого гейта они собраны байт-в-байт в один
  авторитетный источник `source-2026-11-02-epic-and-parity.md` (368 строк: префикс эпик-входа без изменений,
  дополнение добавлено с L349).
- `requirements-map.json` привязан к этому консолидированному файлу (`source_path` + `source_sha256`),
  176 строк инвентаря + 64 ручных строк (таблицы сценариев, DoD, H-гейт, проза, гейты паритета).
- Расхождение веток: строки паритета были оформлены в коммите `2e397e59` (контракт — `bab15d68`), которые
  по ошибке попали в `master`; здесь они восстановлены в карте ветки `evol/impl`. `master` не менялся,
  stray-коммит не удалялся (подробности — `source_note` в карте).

## Состав

| Файл | Что внутри |
|---|---|
| `requirements-map.json` | 132 обязательных требования: E — 72 (включая E-01..E-26 как отдельные строки с дословным наблюдаемым результатом), P — 45 (включая P-01..P-16), P-паритет — 13 (`PAR-01..PAR-05`, `P-SPEC-PARITY`, `P-GENUINE`, `P-GATE-00..P-GATE-05`), H — 1 (`EP-H-HELP` с дословным гейтом открытия), 1 сквозной `EP-GUARD-ARCH` (§0.2 как проверяемое требование). 108 контекстных строк, в т.ч. §0.2 и §0.3 — чтобы запреты и разрешения конфликтов не потерялись. `strict_evidence: true`. |
| `slice-graph.json` | 15 слайсов (`openworkflow-slices-v1`): write_scope, depends_on, acceptance, риск. Пересечения внутри эпика сняты рёбрами; `EP-H-HELP` зависит от всех. В `acceptance` каждого из шести P-пакетов зашит гейт паритета: (a) метрика, (b) артефакт паритета, (c) состояния и вьюпорты. |
| `plan.md` | Пакеты работ, список сериализации общих файлов, волны (что можно начинать раньше очереди), контракт измерения P (5 пунктов), существующее-vs-отсутствующее по текущему дереву с `file:line`, архитектурная классификация. |

## Гейт

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/epic-experience-learning-performance-help/requirements-map.json --stage plan
```

Текущий результат: `stage=plan inventory=176 manual=64 scoped=0 errors=0`.

Строгий режим включён (`strict_evidence: true`): на review/release обязательны candidate-bound evidence
с реальным repo-relative `artifact_path`, а для live-строк — доказательство типа `live`/`ui`/`provider`
(review) и `live`/`production` (release). Для этого эпика live-строки: `E-01`, `E-02`, `E-26`,
`EP-E1-RESULT`, `EP-E8-DOD`, `P-01`, `P-03`, `P-04`, `EP-P-DOD`, `P-SPEC-PARITY`, `P-GENUINE`,
`PAR-01..PAR-05`, `P-GATE-00..P-GATE-05`, `EP-H-HELP`.

## Статусы

Все обязательные строки — `PENDING`. Ничего не помечено `VERIFIED`: реализация не начиналась.
`EP-H-HELP` остаётся `PENDING` (это зависимость, не human gate) и не должен переводиться в работу до
выполнения своего условия.

## Порядок

1. Волна 0 (можно сейчас): `EP-E-EXTRACT`, recon `EP-P-MEASURE`, `EP-P-ANIM` — файлы не пересекаются с
   COG-MAP S2–S4 и пакетами FINAL v8.
2. Волна 1 (после COG-MAP S4 + EVOL-RELEASE): `EP-P-CACHE`, эвристическая часть `EP-E-GATE`.
3. Волна 2 (после FINAL v8 UI-стека и MEM-*): `EP-E-LESSON` → `EP-E-OUTCOME` → `EP-P-SCRIPTS` →
   `EP-P-BOOT`, `EP-E-DIALOGUE`, `EP-P-API`.
4. Волна 3: `EP-E-ACCEPT`, `EP-P-ACCEPT`.
5. Волна 4: `EP-H-HELP` — только последним.

Подробности и обоснование — в `plan.md`.
