# ADD-TR — регистрация требований (хвост `plans/current_task.md`, строки 1631–1731)

Дата: 19.10.2026. Регистрация PM (LANE PM-TR-MAP). `plans/current_task.md` (sha256 `3D238E1E…` на момент регистрации) — read-only; источник зафиксирован снапшотом.

## Артефакты

| Файл | Назначение |
|---|---|
| `source-add-tr-2026-10-19.md` | VERBATIM-снапшот строк 1631–1731 `current_task.md` (sha256 `08cd6b4a…`) |
| `requirements-map.json` | `openworkflow-coverage-v1`: 32 inventory + 36 manual-строк = 58 required, 10 context; 30 live (postdeploy) |
| `slice-graph.json` | `openworkflow-slices-v1`: 6 слайсов, зависимости, последовательные соединения |

Проверка: `py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --stage plan --map plans/features/add-tr/requirements-map.json`.

## Слайсы и волны

- **W0 (реконсиляция)**: `ADTR-REG` — учёт/очередь/сверка master-vs-prod; фиксирует статус каждого сценария (`REUSE_VERIFIED/GAP/REGRESSION/PENDING_OWNER_E2E/BLOCKED`) — тот же проход выполняет TR-RECON и уточняет предварительные статусы в `note`-полях.
- **W1 (кандидатные писательские полосы)**: `ADTR-GRID` (CSS/компоновка «Речь и характер»), `ADTR-ENTRY` (Direct-вход: text/caption/вложения/reply), `ADTR-TOOLS` (сквозные tool-вызовы Vision/Factcheck/GenImage/Checkup). Источник (L13) сам допускает параллель маршрутизация/генерация+vision/CSS — но только при непересекающихся файлах; полные `write_scope` заполняет TR-RECON до старта Builder.
- **W2 (после TOOLS)**: `ADTR-POSTGEN` — intentional serial join (вероятное пересечение по `services/tool_router.py`; протокол потребляет стабилизированный generation/delivery путь).
- **W3 (финал)**: `ADTR-VERIFY` — 13 сценариев ADD-TR.5, edge-cases, DoD 1–5, человеческий отчёт; затем Reviewer → штатный деплой (PET_PROJECT: без канареечных согласований).

## Алиасы (ADD-1, без повторных реализаций)

| Строка | Тема | Алиасы |
|---|---|---|
| L7 | SOUL-1 §5 Capability/Tool Grounding | `soul-1-amd:SOUL-AMD.5.1/.5.11/.5.16` |
| L8 | Голос: Prompt Registry/Speech Style/CFG-07 | `soul-1:SOUL-16.0`, `cfg:CFG-07A.F`, `cfg:CFG-07B.F` |
| L9 | Factcheck (не третий путь) | `cfg:CFG-06.B-HIJ`, `cfg:CFG-06.B`, `mca-20:CA-20-1` (archive) |
| L10 | Vision (не второй pipeline) | `mca-19:CA-19-1` (archive), `p0-vision-universal:P0V-PIPE-CONTEXT` (активная работа) |
| L11 | generate_image/квоты/дедуп | `soul-1-amd:SOUL-AMD.5.16/.5.17`, `cfg:CFG-02A.6` |
| L12 | Регрессия сетки | `p0-save-init-ux:P0A-UX-COMPACT`, `cfg:CFG-04C.1` |
| L5/L13 | Учёт/очередь | `cfg:ADD-0.3/.5`, `cfg:ADD-0.Q/.1/.2` |

Решения и уточнения:

- Шесть формулировок «пересечений» (L7–L12) отнесены к **тематическим** слайсам (владельцам дельт), а не к `ADTR-REG` — по прецеденту `cfg` (CFG-02.F → CFG-02C); в `ADTR-REG` остаются учёт/очередь/сверка.
- `MCA-20` в тексте = archive `mca-20-temporal-factcheck` (factcheck, НЕ генерация); квоты/дедуп генерации — `CFG-02A/B/C` + `SOUL-AMD.5.16/.5.17`.
- Регрессия сетки честно фиксируется как поломка **после** VERIFIED-этапа `P0A-UX-COMPACT` (2.58.90), без переоткрытия всего CFG-04C/04D.
- Предварительные статусы сценариев (`note`-поля, напр. REGRESSION для S13, кандидаты REUSE_VERIFIED для канонических триггеров) уточняет TR-RECON по master-vs-prod.

## Live-пункты

30 required-строк помечены `live_required=true, live_when=postdeploy` (сквозные tool-вызовы, пост-генерационный протокол, сценарии на конечном Telegram-результате, DoD 1–4, native-проверка). На review для них допустим `READY_FOR_LIVE`; на release нужен production/live evidence. Устройство-специфичные проверки — «или честный PENDING_OWNER_E2E» (device-чек-листы владельца отменены, PET_PROJECT §5).
