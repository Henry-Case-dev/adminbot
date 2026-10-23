# DEPLOY-258113 — релиз 2.58.113 на прод (23.10.2026)

## Итог

- **DEPLOY_SOURCE:** commit `e4ee54f3cc12c39492c60eb2a0865f5da429454c` (bump 2.58.113), развёрнут точным checkout на `/var/www/admin_bot`; локальная `master` переведена на этот commit.
- **До деплоя:** `fbf9013d` (2.58.111), healthz 200 `{"status":"ok","version":"2.58.111"}`, tracked-дерево чистое.
- **После деплоя:** healthz 200 `{"status":"ok","version":"2.58.113"}`; `systemctl` active, MainPID **715288**, NRestarts **0**, ExecMainStatus **0**, старт `2026-10-23 05:53:08 UTC`.
- **Откат:** ветка `release/fix-2.58.111` = `fbf9013d89b03e38473ce6824a460fdbb736fff8` (создана в origin и присутствует на сервере); backup БД `backups/pre_deploy_258113_1792734640.db` (1 497 432 064 B, `integrity_check=ok`). Процедура: `git checkout fbf9013d && systemctl restart admin_bot`, проверить healthz 2.58.111; схема БД не менялась (ΔDDL=0).
- **SSH-коннектов:** 3 (recon, основной прогон, диагностика панели), все успешные, интервал >60 с.

## Предусловия (факт)

| Проверка | Факт |
|---|---|
| healthz | 200, version `2.58.111` |
| HEAD до | `fbf9013d89b03e38473ce6824a460fdbb736fff8`, branch `master` |
| tracked-изменения | 0 (untracked 13, `.env` не трогался) |
| Свободно на `/` | 7 219 MB (после backup 5 791 MB) |
| `systemctl` до | active, MainPID 516119, NRestarts 0, старт 2026-10-22 13:14:31 UTC |
| БД до | `local_database.db` 1 497 411 584 B, `user_version=37` |
| Точка отката | `release/fix-2.58.111` = `fbf9013d` (локально + origin) |

## Деплой

- `git fetch origin master release/fix-2.58.111` → `origin/master=57ba2042`, `origin/release/fix-2.58.111=fbf9013d`, `FETCH_RC=0`.
- `git diff --name-only fbf9013d e4ee54f3 -- requirements.txt requirements-dev.txt pyproject.toml` — **пусто**; `pip install` не запускался.
- `git checkout -B master e4ee54f3` → `HEAD_POST=e4ee54f3`, tracked-изменений 0, `APP_VERSION = "2.58.113"` найден.
- Штатный рестарт: `systemctl restart admin_bot` → `RESTART_RC=0`, T0 `2026-10-23 05:52:58 UTC`.
- Healthz 2.58.113 получен на 5-й попытке (`05:53:41 UTC`).

## Совместимость эмбеддингов / adopt

```
05:53:35 [database] embedding generation ADOPTED (gateway compat) | index=graph_facts_vec ns=default gen=1 fp=96f80838f683
05:53:36 EMBEDDING_COMPAT_ADMITTED | index=graph_facts_vec | gen=1 | checked=12 | mean=1.0 min=1.0 hit5=1.0 | fingerprint сохранён (провенанс)
```

Реестр поколений (read-only SQLite):

| index | generation | fingerprint | status | activated_at | config_revision |
|---|---|---|---|---|---|
| graph_facts_vec | 1 | 96f80838f683 | **active** | 1792734815 (05:53:35Z) | **adopt1:e540d4ad890e121d:a93485483697c3c3:12:1.00** |
| smart_archive | 1 | 96f80838f683 | building | — | — |
| smart_archive | 2 | 2d0efab0e817 | building | — | — |

- `graph_facts_vec` — **active/adopt1**, `activated_at` заполнен, fingerprint старого шлюза сохранён.
- Полная перевекторизация **не запускалась**: `EMBEDDING_GENERATION_BUILD_START` = **0** за весь период; старый job `graph_facts_vec` (`7ed322e68a0d433b89f03ef66117c367`, `paused_rate_limit`) переведён в `cancelled` в 05:53:36 — ожидаемое поведение adopt.
- **Отклонение:** появилась новая строка `smart_archive` gen2 `building` (05:53:27, provider apinet.cloud). `smart_archive_facts=0` (source_empty), job/сборка не создавались; на `graph_facts_vec` не влияет. B11 честно показывает по ней attention (см. ниже).

## Журнал после рестарта

- `J_LINES=548`, `ERROR=0`, `CRITICAL=0`, `Traceback=0`, `database is locked=0`.
- `EMBEDDING_COMPAT_ADMITTED=1`, `embedding generation ADOPTED=1`.
- `EMBEDDING_GENERATION_BUILD_START=0`.

## Backfill / свободные векторы

| Точка | graph_facts_vec | backlog graph | Комментарий |
|---|---|---|---|
| До рестарта (05:50:4x) | 16 003 | 4 234 | baseline |
| T1 (05:53:55) | 16 053 | 4 184 | стартовый backfill идёт |
| T2 (06:02:55, +9 мин) | 16 503 | **3 734** | `SmartModule graph backfill: re-embedded 500 facts` (05:56:04) |
| B11 (06:03) | — | **3 619** | `backlog_status=ok` |

Backlog снижается (−615 к B11), `graph_facts_vec` не уменьшился (+500). Тикер backfill — 600 с; следующий цикл продолжится после окна наблюдения.

## API `/api/memory/embeddings` (TMA initData владельца, значения не печатаются)

HTTP 200. Блок `generation.graph_facts_vec`:

```
state=active, serviceable=true, reindex_required=false,
compat_state=compatible, compat_class=ADMITTED_COMPATIBLE, action=none, needs_probe=false,
compat.space=e540d4ad890e121d, compat.conn=a93485483697c3c3,
canary={verdict:compatible, source:admission, checked:12, mean:1.0, min:1.0, hit5:1.0, at:1792734815}
```

**Источник полей п.10:** блок `generation` того же API (а не агрегированный `compat`). Агрегированный `compat` пуст (`serviceable=false, state=null, indexes={}`), потому что `vector_memory.indexes=0`: по коду `vector_memory_panel` строит записи из `task_jobs` kind `graphrag_rebuild`, а их legacy `payload` не содержит `index` (rebuild-блок отдаёт `index=null`). Это дефект панели/данных job'ов, не отказ совместимости: резолвер и adopt отработали (лог + `generation`). Рекомендация — отдельная задача Builder/Reviewer: derive index из `coalesce_key` или заполнять `payload.index`.

## Реальный семантический поиск (ACC-10)

Запрос «что обсуждали в этом чате» эмбеддингнут штатным `LLMClient` (gemini-embedding-001, текущий шлюз), KNN top-5 по `graph_facts_vec` (read-only, sqlite-vec):

```
SEM_QUERY name=generic n=5 top=[(17273,0.832),(11458,0.8047),(12662,0.7973),(16698,0.7953),(16564,0.7952)]
```

Выдача непустая, косинусы 0.83–0.80 — семантика, а не только совпадение размерности. Контрольный canary: `checked=12, mean=min=hit5=1.0`.

Ограничение: второй probe взял самый новый «старый» факт `id=20522` (возраст 2 дня), который ещё в backlog без вектора; self-hit=false ожидаемо и в зачёт не берётся.

## B11 (read-only, `tools/v63_b11_mechanisms_report.py`)

- `summary_scheduler`: **degraded** — последняя попытка `1e2aa19a74ec48ae8d19f70dba0b43bc` (published, health=degraded); не ложный `ok`.
- `graph_memory` / `embeddings`: **attention** (job cancelled — не успешный терминал), backlog `3619`, `backlog_status=ok`; не ложный `ok`.
- Сводка: `ok=6, attention=2, unknown=1 (experience, pre-existing), degraded=1`.
- JSON: `OPENCODE_WORKFLOW_SCRATCH/deploy-258113/b11-258113.json`.

## Вердикт postdeploy (пп. 7–13)

| # | Проверка | Вердикт | Основание |
|---|---|---|---|
| 7 | healthz 2.58.113, active | **PASS** | 200 `version=2.58.113`; MainPID 715288, NRestarts 0, ExecMainStatus 0 |
| 8 | журнал: 0 CRITICAL/Traceback/locked; ADMITTED/adopt1; нет BUILD_START | **PASS** | 0/0/0; ADOPTED+ADMITTED; BUILD_START=0 |
| 9 | поколение graph_facts_vec active/adopt1; нет новых building; count не уменьшился | **PASS с отклонением** | active/adopt1/activated_at; новых building для graph_facts_vec нет; появилась `smart_archive` gen2 building (source_empty, без job); count 16 003→16 503 |
| 10 | compat.serviceable, generation.state=active, reindex_required=false | **PASS (источник: generation + журнал)** | generation: active/serviceable=true/reindex_required=false, canary 12/1.0/1.0/1.0; агрегированный compat пуст из-за legacy payload job'ов |
| 11 | backlog снижается | **PASS** | 4 234 → 3 734 (T2) → 3 619 (B11); +500 векторов |
| 12 | реальный семантический поиск непустой | **PASS** | top-5, cosine 0.832–0.795; canary hit5=1.0 |
| 13 | B11 Summary → attention, backlog число/unknown | **PASS** | Summary `degraded` (не ok); backlog `3619` (ok) |
| 14 | следующий тик Summary 19:00Z | **WAITING_EXTERNAL** | не наступил; в лейне не ждали |

**Итог: деплой 2.58.113 успешен, обязательные пункты 7–13 — PASS.** Блокеров отката нет. Полный `DONE` релиза не ставится: тик Summary 19:00Z впереди, плюс родительские release-гейты/карты.

## Находки

1. **MEDIUM (панель/данные, не блокер):** агрегированный `compat` в `/api/memory/embeddings` пуст, т.к. `vector_memory.indexes=0` — legacy `graphrag_rebuild.payload` без `index`. Фактическая совместимость подтверждена `generation`-блоком и логом. Отдельная задача Builder/Reviewer.
2. **LOW (реестр):** новая `smart_archive` gen2 `building` при пустом источнике; сборка не запускалась, B11 attention. Не влияет на graph-индекс.
3. **ВНЕ РЕЛИЗА:** B11 `experience` = unknown (механизм Experience, не связан с изменением эмбеддингов/W4).

## Следующее

- Тик Summary `2026-10-23 19:00:00Z` (местное 07:00 UTC+12) — проверить `coverage>0`, anchor-map, `revision_fixed_count`, published-cancel; вне этого лейна (`WAITING_EXTERNAL`).
- Обновить карту `embed-identity-compat`: `ACC-10` → VERIFIED с production-evidence на этот файл, `deployed_commit=e4ee54f3`; затем `requirements_gate.py check --stage release --candidate e4ee54f3 --deployed-commit e4ee54f3`.
