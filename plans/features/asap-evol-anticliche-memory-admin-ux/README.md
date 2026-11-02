# ASAP-EVOL-ANTICLICHE-MEMORY-ADMIN-UX — карта требований FINAL v8

Снимок ТЗ: `plans/owner_inputs/2026-11-02-anticliche-memory-admin-ux-spec.md`
(1124 строки, §1–§17, дословно из `plans/current_task.md` строки 2902–4025).
Регистрация: задача `asap-evol-anticliche-memory-admin-ux`, вход
`OI-2026-11-02-ANTICLICHE-MEMORY-ADMIN-UX` (владелец `plans/progress_scope.json` —
Orchestrator; PM его не меняет).

## Что здесь лежит

| Файл | Назначение |
|---|---|
| `requirements-map.json` | машинная карта `openworkflow-coverage-v1`, `strict_evidence: true` |
| `slice-graph.json` | граф рабочих пакетов `openworkflow-slices-v1`: зависимости, write_scope, приёмка |
| `plan.md` | человеческий план: классификация существующего/отсутствующего, пакеты, волны, первые три пакета |
| `README.md` | этот файл |

## Цифры карты

- инвентарных строк источника: **521** (все классифицированы, 0 unassigned);
- дополнительных ручных строк (проза/таблицы/скриншоты): **148**;
- всего строк: **669**; обязательных (`required`): **573** под **511** `req_id`;
- контекстных (`context`): **96** (метаданные снимка, заголовки разделов,
  воспроизведение инцидента, макеты §12, явно необязательный объём §14.9);
- `user_excluded`: **0** — владелец не отменял ни одного пункта ТЗ;
- пакетов: **17**; статусы всех обязательных строк — `PENDING` (реализация не
  начиналась, файл ТЗ сам работу не запускает);
- `live_required`: 278 строк (263 `preprod`, 15 `postdeploy`).

### Распределение обязательных строк по пакетам

| Пакет | Строк | Пакет | Строк |
|---|---|---|---|
| AC-UI | 155 | MEM-PACKAGE | 34 |
| AC-PIPE | 74 | AC-P0 | 23 |
| AC-API | 66 | MEM-IDENTITY | 22 |
| AC-DATA | 52 | AC-LIVE | 21 |
| MEM-CONTRACT | 43 | UI-LOGS-BE | 10 |
| AC-COMPILER | 36 | UI-BOOT / UI-MODULES | 8 / 8 |
| UI-SELECTOR | 7 | MEM-TRACE | 7 |
| UI-MEME | 5 | UI-LOGS-FE | 2 |

## Проверка

```bash
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/asap-evol-anticliche-memory-admin-ux/requirements-map.json \
  --stage plan
```

Ожидаемый результат: `stage=plan inventory=521 manual=148 scoped=0 errors=0`
(граф зависимостей проверяется автоматически, так как задан `slice_graph_path`).

Проверка среза перед ревью и релизом:

```bash
python <OPENCODE_CONFIG>/tools/requirements_gate.py check --map ... --stage review \
  --slice AC-P0 --candidate <sha> --repo <repo>
python <OPENCODE_CONFIG>/tools/requirements_gate.py check --map ... --stage release \
  --candidate <sha> --deployed-commit <sha> --repo <repo>
```

`strict_evidence` включён: каждая строка обязана нести `evidence` c
`candidate_commit`, `ref`, `observation`, `type` и реальным repo-relative
`artifact_path` (плюс `artifact_sha256` для финальных отчётов). Строка не
считается доказанной по одному упоминанию в отчёте.

## Правила ведения

1. Пакеты не переименовываются и не удаляются: `slice-graph.json` — источник
   зависимостей, `plan.md` — человеческое объяснение.
2. Новая порция ТЗ от владельца добавляется как отдельный вход и дельта-строки;
   существующие `req_id` и уже проверенные `VERIFIED` сохраняются.
3. `live_required` / `live_when` показывают, где нужны реальные UI/провайдер/
   production доказательства; `NOT_VERIFIED` никогда не равен `PASS`.
4. Статусы меняются только по факту принятого кандидата и независимого ревью;
   PM привязывает доказательства, но не переписывает вердикт Reviewer.
