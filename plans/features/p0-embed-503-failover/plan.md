# P0-EMBED-503-FAILOVER — компактная карта узкого P0

- Задача очереди: `p0-embed-503-failover` (ticket `P0-EMBED-503-FAILOVER`, queue 47, P0). Запись в
  `plans/progress_scope.json` делает Orchestrator; эта карта очередь не переписывает.
- Owner input: `plans/owner_inputs/2026-11-22-p0-embed-503-failover.md`, sha256
  `d23bf6f96c69e8ddd1537a07f8f203fbf434b0022f693e5368a64c8731828f09`. Предыдущий текст
  «P0 OPERATIONAL» владельцем не отправлялся и не регистрируется.
- Карта: `requirements-map.json` (`openworkflow-coverage-v1`, `strict_evidence: true`) — 10 уникальных
  обязательных `req_id` (13 строк: `E503-ROUTE-01`, `E503-FAILOVER-01` и `E503-DIAG-01` опираются на
  две клаузы каждая), 6 ручных строк из прозы, 4 инвентарные строки помечены `context`/`delegated`,
  3 — `duplicate` заголовков.
- Граф: `slice-graph.json` (`openworkflow-slices-v1`, 3 среза: `E503-ROUTE-PROBE` →
  `E503-FAILOVER-CORE` → `E503-ACCEPT`).
- Статус: intake-only, все строки `PENDING`; кандидата, ревью, деплоя и live-evidence нет. Deploy/SSH/LLM
  этим планом не выполняются.

## 1. Что именно исправляется

Существующий `services/embedding_control_plane.py`: `_pick_credential()` берёт первый `healthy`, а
`_on_error()` на 5xx/timeout классифицирует ошибку как `transport`, не исключая отказавший
endpoint/credential. При primary-first пуле все ≤4 попытки логического запроса могут снова уйти в
primary, и независимые Google-слоты (`fallback_1`, `fallback_2`) не используются. Это гипотеза
владельца, подтверждаемая чтением кода; она проверяется одной реальной трассой до правки.

Цель — восстановить реальный failover **в существующем** Control Plane: независимые quota groups,
bounded retry/backoff, приоритеты, cooldown, честные 401/403/429, сохранение embedding identity и
использование действующих `embed_recovery_tick`/text-only backfill. Не новый менеджер retry, не
`budget=4`, не смена модели, не переиндексация.

## 2. Срезы и порядок

| Срез | Зависит от | Что даёт | Write scope |
|---|---|---|---|
| `E503-ROUTE-PROBE` | — | однократный реальный `POST /embeddings` по каждому фактическому профилю; evidence alias/host/model/status/config-source | `plans/features/p0-embed-503-failover/evidence/route/**` |
| `E503-FAILOVER-CORE` | `E503-ROUTE-PROBE` | failover-семантика 5xx/timeout, 401/403/429/нет ключей, embedding identity, recovery/backfill, диагностика | `services/embedding_control_plane.py`, `services/llm_client.py` (только доказанный seam), `tests/test_embedding_control_plane*.py`, `tests/test_embedding*.py`, `evidence/core/**` |
| `E503-ACCEPT` | `E503-FAILOVER-CORE` | негативная матрица, реальный embed smoke, границы диффа, отчёт | `tests/test_p0_embed_503_accept.py`, `evidence/accept/**` |

Старт — на ближайшей безопасной границе: активная работа (C1 M4C) не прерывается, её worktree/сессия
не пересекаются; перед первой записью — read-only сверка фактического HEAD/деплоя и write-scope. Один
writer на файл.

## 3. Приёмка (из owner-текста, без смягчений)

DoD A (`E503-ACCEPT-MATRIX-01`): primary 503 → совместимый `fallback_1` → `fallback_2`; все три
недоступны → сохранение текста и FTS; восстановление primary; независимые 401/403/429; несовместимый
вектор; сохранение и постепенный backfill; минимальный реальный embed smoke для корректно настроенных
профилей; evidence aliases/status/identity.

Разделять два факта: «продуктовый failover восстановлен» и «apinet снова работает». Внешние 503 не
блокируют выпуск исправленного failover, но apinet не объявляется починенным без реального ответа
шлюза. Причина пустого журнала apinet считается подтверждённой только при наличии данных
(`E503-ROUTE-01`).

## 4. Явные исключения

Не меняются UI, схема БД/DDL и embedding space; не затрагиваются текущая задача и другие P0; не
создаётся второй retry/circuit-breaker, второй экстрактор уроков или новая очередь; широкий ресёрч не
проводится; QA не перекладывается на владельца; ранее согласованный scope Experience-трека не
отменяется (`E503-EXCLUSIONS-01`).

## 5. Experience: только amendment

E-TRUNC/E-LAG не входят в эту карту и не создают новый эпик: они зарегистрированы как amendments
существующего трека в
`plans/features/smart-execution-reliability-01/requirements-map-exp-amendment.json`
(`EXP-E-TRUNC-01`, `EXP-E-LAG-01`, `EXP-E-DOD-B-01`, `EXP-E-AMEND-STAMP-01`) со связями
`EXP-FIX-02`/`EXP-FIX-03`, `SXR-I2-01`, `EP-E-EXTRACT`/`EP-E-ACCEPT`. Раздел B в этой карте помечен
`context` с указанием адреса делегирования — не discard.

## 6. Гейт

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/p0-embed-503-failover/requirements-map.json --stage plan --repo .
→ stage=plan inventory=15 manual=6 scoped=0 errors=0   (EXIT 0)

python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/smart-execution-reliability-01/requirements-map-exp-amendment.json --stage plan --repo .
→ stage=plan inventory=15 manual=2 scoped=0 errors=0   (EXIT 0)
```

## 7. Что осталось для Orchestrator

1. Связать карту с задачей `p0-embed-503-failover` (`maps`, `coverage_complete`) — только Orchestrator
   пишет `plans/progress_scope.json`.
2. Диспатч `E503-ROUTE-PROBE` на безопасной границе после C1; `E503-FAILOVER-CORE` — только после её
   evidence.
3. Amendments E-TRUNC/E-LAG остаются `PENDING` в существующем E-треке; они не блокируют и не
   задерживают P0 embeddings.
