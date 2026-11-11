# VMQ-MEM — диагноз index-compat (2.58.187)

`ARCHITECT_ADJUSTMENT_REQUIRED` к чтению side-`resolve` как живого PCI. Передопуск из этого чтения небезопасен. Формула PCI не менялась (`connection_identity`, `services/embedding_control_plane.py:2657`, с `30a2f868`).

1. PCI = sha256[:16] канон-JSON `{provider_family, endpoint_host, endpoint_path, credential_alias, quota_group}`. Порт, ключ, DSN, driver не входят. Текущий: `_current_conn()` → `resolve_embedding_profiles()["primary"]`. Группа: override `models.embedding_quota_group`, иначе `keys.embedding_quota_group_labels`, иначе авто-alias `primary` (`_profile_quota_group:2171`). `hot.get` при `_cache is None` отдаёт дефолт (`hot_config.py:71-75`). Допуск: `ensure_index_compat` → `format_admission` → `adopt_embedding_generation` пишет только `mca_embedding_index_generations.config_revision` (`adopt1:<space16>:<conn16>:<checked>:<mean>:<min>:<hit5>:<at>`). Валиден лишь при совпадении space и conn (`admission_valid:2725`).

2. Оба хеша воспроизведены той же формулой; host/path/family/alias одинаковы (`apinet.cloud`, `/v1`, `openai-compatible`, `primary`). Разница одно поле: `a93485483697c3c3` = `quota_group=apinet_paid`; `d2e6314e3586c547` = `quota_group=primary`. Допуск записал живой процесс 2.58.113 (2026-10-23T05:53:35Z) при labels `primary:apinet_paid,…` (с 2026-10-22T17:15Z): `release-258113/deploy.md`, `embed-provider/report.md`. Это не смена host/port и не смена формулы. `d2e6314e` — PCI процесса без hot-кэша; тот же хеш дал predeploy-скрипт без кэша (`resolver-pre/report.md:40`). Замер 2.58.187 — прямой `resolve_index_compat`, не API живого процесса. Старт MemoryManager зовёт `ensure_index_compat` (`summary_memory.py:2097`); при своём mismatch и успешной пробе он переписал бы `config_revision`. В заметке допуск всё ещё `a9348548…`, событий ADMITTED/INSUFFICIENT нет.

3. Передопуск в этом дизайне безопасен только из того же резолва, что у бота: одна проба 12 текстов (порог checked≥8, mean≥0.995, min≥0.990, hit5≥0.80), сеть только на выборке, `graph_facts_vec` не пишется, fingerprint/provider/endpoint не меняются. После adopt: `state=compatible`, `class=ADMITTED_COMPATIBLE`, `needs_probe=false`, canary `source=admission`. Side-процесс без кэша записал бы PCI `primary` и инвалидировал бы живой допуск `apinet_paid`. Это не путь. Пересборка не нужна.

4. Сначала живое чтение: `GET /api/memory/embeddings` → `generation` индекса `graph_facts_vec` (`generation_status` в процессе бота). Если `compat.state=compatible`, `conn=a93485483697c3c3`, `needs_probe=false` — передопуск не делать, нога уже допустима. Если живой процесс сам даёт `conn=d2e6314e` и `needs_probe` — один `ensure_index_compat` внутри него. Журнал: `SmartModule: embedding index serviceable | index=graph_facts_vec | class=ADMITTED_COMPATIBLE`.

5. Одна нога на ход (код `952b9ebd`): одно `mca_events` retrieval; `usage_json.period_fill` только у периодного вызова, нет у operative; `vector_leg=ok`. k=32 — `_RAG_PERIOD_POOL=32` → `fetch_k` → SQL `k=?`. В событии k не печатается; `period_vector_knn` — число оставленных, не k. Латентность: в логе нет `knn_ms`; потолок дизайна — p95 периодного вызова ≤ +400 мс к лексическому на той же копии. +110 мс лексики — не цена вектора.

Вне скоупа: смена модели, пересборка векторов, новое хранилище.

DIAGNOSIS READY. Следующее: read-only compat из живого процесса; передопуск только если его conn ≠ допуска. Риск R1 (ложный side-PCI); R2, если передопустить из процесса без hot-кэша.

## Живой замер 11.11.2026 (DevOps, read-only) — R1 ПОДТВЕРЖДЁН, передопуск не нужен

Ни изменений кода, ни перестроек индексов, ни повторной генерации эмбеддингов, ни adopt не выполнялось.

**Живой процесс сам сообщает допуск.** journal, `SmartModule: embedding index serviceable`:
`11.11 08:25:50` (2.58.187) и `11.11 09:21:12` (2.58.188, новый PID) —
`index=graph_facts_vec | class=ADMITTED_COMPATIBLE`. С 01.11 таких строк 1700, различных PID
с 10.11 — 11; строк `compat_not_proven` в логах — 0; `not serviceable | index=graph_facts_vec` — 0.
`ADMITTED_COMPATIBLE` код выставляет только при `admission_valid(admission, space_now, conn_now)`,
т.е. живой `conn` равен `a93485483697c3c3`, `space` — `e540d4ad890e121d`.

**Живой эквивалент PCI (реплика кэша из `bot_settings` через `normalize_value`):**
`{family: openai-compatible, host: apinet.cloud, path: /v1, alias: primary, group: apinet_paid}`
→ `a93485483697c3c3`; тот же профиль без `keys.embedding_quota_group_labels` → `primary`
→ `d2e6314e3586c547`. Обратная проверка «изменить только group» даёт ровно эти два хеша.
Панель провайдера живого процесса: `rotation.groups=[apinet_paid, google_free_1, google_free_2]`,
`primary_source=hot`.

**Страж (резолв с живым кэшем, read-only):**

| Индекс | state | reason_code | class | action | needs_probe |
|---|---|---|---|---|---|
| `graph_facts_vec` | `compatible` | `` | `ADMITTED_COMPATIBLE` | `none` | `false` |
| `smart_archive` | `source_empty` | `source_empty` | `COMPATIBILITY_UNKNOWN` | `none` | `false` |

`smart_archive`: ACTIVE-строки нет (gen1/gen2 `superseded`), векторов 0, фактов в источнике 0,
job `knn_source_empty` — расхождения нет, векторизовать нечего.

**Допуск:** `adopt1:e540d4ad890e121d:a93485483697c3c3:12:1.000000:1.000000:1.0000:1792734815`
(gen 1, `active`, fingerprint `96f80838…4337d`, `activated_at=2026-10-23T05:53:35Z`,
provider в строке — `generativelanguage.googleapis.com`: провенанс не перезаписывается).

**Целостность векторов, три среза (до и после рестарта/деплоя 2.58.188):**
`graph_facts_vec` 25652 строки, сумма длин блобов 315 211 776, digest `b2fff47fa132ffa9`
(все три среза совпали); `smart_archive` 0 строк. Реестр поколений не изменился.

**Вывод:** записанный в карте `compat_not_proven` — артефакт стороннего замера без hot-кэша
(группа падала в авто-alias `primary`). В проде гейт открыт, `needs_probe=false`; передопуск
(`ensure_index_compat`/`adopt`) не требуется и не выполнялся.

**Остатки, честно:** (1) реального direct-чата с периодным добором после выкатки не было
(строк `period_vector_leg=…` — 0), поэтому работа векторной ноги на ходе не наблюдалась;
триггер — первый живой ход с периодным вопросом. (2) Строки карты, зафиксировавшие
`compat_not_proven` (incl. VMQ-NEXT/guard), требуют правки статуса силами PM/Orchestrator.
(3) Линия деплоя: `952b9ebd` → `c087253d` (2.58.188) во время разбора, `952b9ebd` — предок;
локальный чекаут `4647adf1` этих коммитов не содержит.

---

## CORRECTION 11.11.2026 (PM) — запись `compat_not_proven` отменена

Исходный текст Architect'а (пункты 1–5 выше) не переписывается. Ниже — формальная поправка для карты требований и последующих чтений.

**1. Что было неверно.** Утверждение «identity соединения `d2e6314e3586c547` отличается от admitted
`a93485483697c3c3`, поэтому `state=insufficient`, `reason_code=compat_not_proven`,
`action=retry_canary`, `needs_probe=true`, векторная нога не активируется» — **неверно как описание
прода**. Оно верно только как описание резолва в процессе без hot-кэша.

**2. Что верно (живой процесс, read-only).**

- PCI различался **одним полем** — `quota_group`. Живой процесс с hot-кэшем берёт
  `apinet_paid` из `keys.embedding_quota_group_labels` → `a93485483697c3c3`; процесс без
  hot-кэша падает в авто-alias `primary` → `d2e6314e3586c547`.
- Provider family (`openai-compatible`), host `apinet.cloud`, path `/v1`, credential alias и
  embedding space `e540d4ad890e121d` **идентичны** в обоих случаях; MSI `e540d4ad890e121d` один и тот же.
- Следовательно **реальной смены соединения не было**. `compat_not_proven` — **артефакт замера
  сторонним процессом**, а не состояние прода.
- Живой журнал: `SmartModule: embedding index serviceable` с `class=ADMITTED_COMPATIBLE` для
  `graph_facts_vec` с 01.11.2026 — 1700 строк, 11 различных PID, **0** строк `compat_not_proven`,
  **0** строк `not serviceable | index=graph_facts_vec`.
- Допуск: `adopt1:e540d4ad890e121d:a93485483697c3c3:12:1.000000:1.000000:1.0000`, generation 1
  `active`, fingerprint `96f80838…`, активирован 2026-10-23.
- Страж по живому процессу: `graph_facts_vec` = `compatible` / `ADMITTED_COMPATIBLE` /
  `needs_probe=false`; `smart_archive` = `source_empty` / `COMPATIBILITY_UNKNOWN`.
- Целостность: `graph_facts_vec` 25652 строки, 315 211 776 байт, digest `b2fff47fa132ffa9` —
  одинаков до и после рестарта. Ничего не переписано, новых поколений и переэмбеддинга нет.

**3. `smart_archive` — не расхождение.** `source_empty` / `COMPATIBILITY_UNKNOWN` при отсутствии
ACTIVE-поколения — следствие **пустого источника**: 0 строк в `smart_archive`, 0 фактов в источнике,
встраивать нечего. Это не дивергенция с прод-допуском и не второй независимый блокер; job
`knn_source_empty` с этим согласован.

**4. Что меняется в карте.** Записи `compat_not_proven` (в `deployment_evidence.follow_up_2_58_187`,
`blocker_classification`, `next_executable`, `stage_2_58_187_2026_11_11` и в строках
VMQ-NEXT-01..05) помечены `superseded` с причиной; исходные формулировки сохранены как история.
Строки **VMQ-NEXT-01..05 остаются PENDING**, но причина другая: **допуск доказан, per-turn поведение
не наблюдалось** (строк `period_vector_leg` — 0, реального direct-хода с периодным вопросом после
выкатки не было).

**5. Что НЕ доказывает эта поправка.** Поведение векторной ноги на реальном ходе; доставку и
релевантность на 15+2 вопросах; латентность прод-пути вектора; защиту от пустого вердикта на реальном
архиве; C1/C2. Ни одна строка этой поправкой не переведена в VERIFIED, и передопуск
(`ensure_index_compat`/`adopt`) не выполнялся и не требуется.

**6. Lineage.** Рабочая ветка (master `88ebd845`) коммитов `952b9ebd` (release/2.58.187) и
`c087253d` (release/2.58.188) **не содержит**. Прод — 2.58.188 @ `c087253d`, рестарт 09:21:08Z,
`/healthz` = 2.58.188. Слияние релизных линий в рабочую — отдельный осознанный шаг интеграции, а не
следствие этой поправки.
