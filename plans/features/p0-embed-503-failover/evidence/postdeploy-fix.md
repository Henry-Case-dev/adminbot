# P0 EMBED-503-FAILOVER — postdeploy corrective (fix lane)

- Дата: 2026-11-22 (локально +12:00; работы 09:00–09:45).
- Deployed base: `d86bf66d408266c928e24714c2f5779a4ddf8ebe` (2.58.230,
  `release/p0-embed-503-failover-2.58.230`).
- Branch: `fix/embed-postdeploy-park`, code candidate
  **`7171a227d93fdb990c591a65fc0a33bd110ce092`**.
- Owner input: `plans/owner_inputs/2026-11-22-p0-embed-postdeploy-corrective.md`
  (sha256 `034360070dd14438a3f6a6afdcf23a3b7e5def9149cccc501a0894702a7fa3ec`).
- Forensic: `plans/features/p0-embed-503-failover/evidence/postdeploy-2026-11-22.md`
  (master `9faa164c2`).
- Scope: только `services/embedding_control_plane.py` (+ этот тест/evidence).
  MSI admission, `gemini-embedding-001`, индексы, DDL, config, UI, APP_VERSION
  не менялись. Production/LLM/SSH в этой полосе не трогались.

## 1. Подтверждённые дефекты

### D1 — early-return оставлял отказавший primary без cooldown

`_mark_transport_failure()` на базе:

```python
next_available = self._pick_credential(
    pool, set(excluded) | {credential.alias}) is not None
if not next_available and not excluded:
    return False          # ни park, ни exclusion
```

`next_available` учитывает ТЕКУЩЕЕ здоровье других credential'ов, а не факт их
конфигурации. Поэтому при 3-ноговом пуле (`primary`, `fallback_1`,
`fallback_2`), когда обе Google-группы временно group-blocked, отказавший
primary оставался `healthy`; `_pick_credential()` снова возвращал его и
логическая операция тратила все 4 попытки на известный 503. Следующая
операция повторяла те же 4 попытки — «между логическими операциями» ничего
не парковалось. Forensic: 113 `embed transport error` при **1**
`embed leg unavailable`, 33 `EmbeddingRetriesExhausted (budget=4)`.

### D2 — spend/daily parking переживал фактическое восстановление квоты

18:39:43/49 Google вернул 429 `kind=spend` без Retry-After; существующая
kind-эвристика припарковала `google_free_1/2` до `2026-11-22T00:05Z`
(`parked kind=spend est=utc_day_end`). В 21:22 те же ключи реально отвечали
200/3072/MSI `e540d4ad890e121d`, но live-процесс до 00:05Z вообще не пробовал
fallback: 493 новых факта text-only, backlog 4 367 → 4 860, ни одной vec-строки.

### D3 — (сопутствующий, найден при фиксе) спин без прогресса

Когда credential припаркован, а `pool[0]`-группа здорова (типично: primary
credential cooldown, Google-группы parked), старая ветка «нет usable» вызывала
`scheduler.acquire(pool[0].group)`: здоровая группа выдавала permit сразу,
цикл `continue` повторялся без HTTP и без терминала. В прод-сценарии D1 это
не проявлялось (primary ещё был healthy), но после park-фикса стало бы
достижимо; исправлено в этой же полосе.

## 2. Фикс (candidate `7171a227d`)

### 2.1. D1: park при наличии другой СКОНФИГУРИРОВАННОЙ ноги

- Если в пуле есть другой credential, 5xx/timeout-нога **немедленно**
  исключается из текущей операции и паркуется в существующем
  `credential_health` (`HEALTH_COOLDOWN`,
  `_PROVIDER_UNAVAILABLE_COOLDOWN_S=60`), даже если альтернатива сейчас
  непригодна. Лог: `embed leg parked (no alternative)` (R17: alias/provider).
- Реально единственная сконфигурированная нога сохраняет прежний bounded
  retry/backoff текущей операции (ADR-1028-7 D2, тесты
  `asap4::test_attempt_budget_ceiling_transport`,
  `evol010::test_transport_error_retries_preserved_honest_terminal` зелёные);
  её парковка выполняется на терминале операции, поэтому следующий logical
  request в пределах cooldown уже не делает HTTP.
- Второй breaker не создавался.

### 2.2. D2: bounded probe-recovery spend/daily-парковки

- `QuotaGroupRegistry`: in-memory `_group_probe_last` (как credential health);
  `group_parked_kind()` читает существующий note `parked kind=<kind> ...`;
  `spend_parked()` = group blocked + kind `spend|daily_project`;
  `group_probe_due()`/`note_group_probe()`, интервал
  `_GROUP_PROBE_INTERVAL_S=900`.
- `PriorityScheduler.acquire(..., ignore_group_cooldown=True)` — только для
  одной P2-repair пробы; concurrency/AIMD по-прежнему соблюдаются, обычные
  P0/P1/P3 запросы group cooldown уважают.
- `EmbeddingExecutor._pick_group_probe()` / `_attempt_group_probe()`:
  ровно одна попытка к spend/daily-припаркованной группе, отметка попытки
  ставится ДО HTTP (429/5xx тоже троттлятся); успех → существующий
  `set_group_state(..., healthy, "probe_ok")` + `_on_success`; 429/5xx →
  группа остаётся parked, без повторов в операции; 401/403 и code-defect
  идут прежними терминалами.
- Probe вызывается только `Priority.P2_REPAIR` (backfill/repair/probe,
  в т.ч. `embed_recovery_tick` → backfill) и срабатывает как на верхней
  ветке «нет usable credential», так и на терминале после 503 primary —
  именно прод-последовательность. Новых breaker/менеджеров/DDL нет.

### 2.3. D3: ожидание реально заблокированной группы

Ветка «нет usable credential, excluded пуст» выбирает группу с
`group_blocked=True` и минимальным `next_allowed_at` и ждёт/бросает
`EmbeddingGroupCoolingDown` по ней, а не по здоровой `pool[0]` — спина без
прогресса больше нет.

## 3. Exact call sequences before/after

| Сценарий | Base `d86bf66d4` | Candidate `7171a227d` |
|---|---|---|
| primary 503 + fb-группы временно непригодны, 1-я logical op | `primary ×4` (gaps 1/2/4 s) → `EmbeddingRetriesExhausted (budget=4)`; health primary = `healthy` | `primary ×1` → park (cooldown 60 s) → honest transport-терминал |
| 2-я logical op сразу | снова `primary ×4` (cooldown нет) | **0 HTTP**; `EmbeddingNoUsableCredential` (все ноги непригодны) |
| после истечения 60 s | `primary ×4` | ровно **1** probe-попытка primary; успех → healthy |
| P2 backfill tick, Google-группы spend-parked | `primary ×4` → `deferred processed=0` (при живом Google 200) | `primary ×1` (503) → ровно **1** проба `fallback_1` (200) → группа `healthy` → batch-векторы записаны; следующие batches идут в fallback |
| проба 429/5xx | не пробовалось | группа остаётся parked; повтор не раньше 900 s/группу; при cooldown credential пробы нет (0 HTTP) |
| все группы заблокированы, P1 | возможен спин по здоровой `pool[0]`-группе | `EmbeddingGroupCoolingDown` без HTTP; probe только P2 |

## 4. RED / GREEN (фактические прогоны)

RED на base `d86bf66d4` + финальные тесты (временная подмена только
`services/embedding_control_plane.py` на blob базы):

```
python -m pytest tests/test_p0_embed_503_failover.py -q --timeout=180
→ 11 failed, 8 passed
```

Падения: `test_single_credential_parks_without_cross_operation_spin`,
`test_failed_primary_parks_when_alternatives_unusable[server_error|timeout]`,
`test_parked_primary_gets_exactly_one_probe_after_cooldown`,
`test_recovered_fallback_serves_while_primary_parked`,
`test_group_probe_recovers_spend_parked_fallback`,
`test_group_probe_5xx_stays_parked_and_throttled`,
`test_group_probe_spend_429_stays_parked_without_spam`,
`test_group_probe_is_p2_only_and_single_attempt`,
`test_alternatives_unusable_text_only_without_repeated_primary_503`,
`test_group_probe_backfill_writes_vector_and_clears_group`.
Ключевое RED-значение: `['k-primary'] * 4 != ['k-primary']`, health primary
`healthy`; для probe-тестов — 4 вызова primary и отсутствие fallback.

GREEN на candidate:

```
tests/test_p0_embed_503_failover.py                  19 passed
tests/test_p0_embed_admission_msi.py                 10 passed
19-file profile (как release-2.58.230)               667 passed,
                                                     1 deselected (pre-existing)
tests/test_evol010_embedding_defects.py +
  tests/test_embed_meta_wire.py                      16 passed
pin-guard (24 файла)                                 856 passed / 4 failed
                                                     (same 4 pre-existing IDs)
B1 / B2 / B3 e2e                                     138/0, 92/0, 131/0 (8 shots)
JS version pins (hotfix7/8/9/10)                     4/4 rc=0
py_compile (service + test)                          rc=0
```

Новые тесты (10): park при недоступных альтернативах (503/timeout), single-leg
park на терминале, ровно один probe после 60 s, recovered fallback, P2 probe
успех/5xx/429, P2-only и единственная попытка, text-only без повторного 503,
E2E probe → vector row + idempotent backfill.

Мутации (временно, с восстановлением файла, sha256 до/после совпал):

- **M1** — вернуть старый early-return (no park/exclusion): 3 targeted FAIL
  (503/timeout + single-leg park).
- **M2** — `_pick_group_probe() -> None`: 4 probe-теста FAIL.
- **M3** — `group_probe_due() -> True` (без троттлинга): 1 throttling-тест FAIL.

## 5. Восстановление live-процесса после деплоя

Да, без ожидания 00:05Z — при условии, что Google снова отвечает 200 (live
forensic 21:22Z: fallback_1/2 = 200/3072/MSI `e540d4ad890e121d`):

1. Рестарт unit подхватывает `load_group_states()` из
   `embedding_quota_state`; группы остаются `exhausted` с note
   `parked kind=spend est=utc_day_end` — probe-путь это распознаёт.
2. Первый maintenance-tick (`embed_recovery_tick`, ≤600 с) при backlog > 0
   вызывает P2-backfill. Worker: `primary ×1` (503) → park → ровно одна проба
   `google_free_1` → 200 → группа `healthy` → batch-векторы записываются.
   Следующие batches идут в уже здоровый fallback; backlog начинает падать.
3. Вторая Google-группа остаётся parked до своего окна/пробы; для записи
   достаточно одной здоровой ноги.
4. Если Google вернёт 429/5xx — группа остаётся parked, повторов нет;
   следующая проба не раньше 900 с. Это честная деградация, не VERIFIED.

Фактический production smoke (реальный fallback → vector row → sqlite-vec KNN,
backlog before/after) в этой полосе **не выполнялся** (нет SSH/prod/LLM-
доступа) и остаётся deploy-проверкой DevOps. Локальный E2E доказывает
product-path: admitted same-MSI fallback → `graph_facts_vec=2`, повторный
backfill идемпотентен; существующий MSI-suite (10 passed) отдельно покрывает
реальный sqlite-vec KNN.

## 6. Ограничения

- Probe-счётчик in-memory на процесс (как и `credential_health`); forensic
  подтверждает ровно один production-процесс. При нескольких процессах
  худший случай — одна проба на процесс за 900 с; DDL/БД-координация не
  добавлялись по scope.
- Probe только для `spend|daily_project` kind-парковки **без** Retry-After;
  остальные cooldown/429/401/403 семантики не изменены.
- Probe только P2_REPAIR; P0/P1/P3 group cooldown уважают.
- `apinet` 503 остаётся внешним ограничением; фикс не делает его рабочим.
- Production KNN и backlog before/after в этой полосе не измерялись.
- Изменения: 2 product/test-файла + этот evidence; `progress_scope.json` и
  `workflow_state.md` не менялись. B1/B2/B3 сгенерированные артефакты
  восстановлены/удалены.
