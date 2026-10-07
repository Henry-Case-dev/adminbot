# RCA — GraphRAG Recovery + Random source + Парадигмы/граф runtime (Lane P3, T-5243)

Дата: 07.10.2026. Режим: read-only (код HEAD + прод 2.58.67). Ничего не изменено.
Прод-evidence: один recon + три батч-коннекта SSH (логин `nik`, AGENTS.md/fail2ban соблюдены), read-only sqlite (`mode=ro`), journalctl −72h, `/healthz` локально на сервере. R17: значения ключей не читались/не печатались (только presence/len), тексты фактов не выводились.

Прод-контекст на момент съёмки: health 200 `2.58.67`, сервис active, старт процесса 06.10 23:28:33 UTC; **114 systemd start/stop-событий за 72 ч** (~57 рестарт-циклов ≈ каждые 1.3 ч) — операционный фон, усиливающий оба дефекта ниже.

---

## 1. Вердикты (сводка)

| # | Пункт раздела | Вердикт |
|---|---|---|
| G1 | GraphRAG `status=building, gen_fp==new_fp → FTS-only` — rebuild vs stuck | **ADJUSTED → STUCK**: не config-mismatch и не «нормальный активный rebuild» — квот-paused job с resume-gap после рестартов |
| G2 | §13 «Stale building → bounded recovery» | **CONFIRMED (дефект есть)**: recovery существует, но имеет дыру — при `_ensure_job` с неистёкшим `next_allowed_at` future-resume никем не планируется |
| G3 | Warning `not serviceable` — спам? | **ADJUSTED**: не спам (55/72ч, коалисинг 300с работает), но коалисинг-память in-process → после каждого рестарта warning повторяется |
| G4 | Random `random_fallback blocker=provider_unconfigured` = config/degraded, не runtime-ошибка | **CONFIRMED** |
| G5 | Random: UI/analytics ясно объясняют degraded | **CONFIRMED для объяснения состояния**; **дефект — путь исправления из UI отсутствует** (14A.0 bootstrap paradox, confirmed) |
| G6 | Random: notable transition один, спама нет | **CONFIRMED** (once-per-state-key per process; 9 событий/72ч объясняются рестартами) |
| 13A | Парадигмы: UI показывает только cooldown, реальная причина последней попытки скрыта | **CONFIRMED** (код + прод: 16 подряд `no_anchors` за «cooldown») |
| 13A.3 | Cooldown одинаково бьёт по no_anchors и по техошибкам | **CONFIRMED** (код: `last_deep_attempt`/`count_deep_attempts` считают любые попытки) |
| 13B | Граф: стена текста, нет semantic zoom; данные не урезать | **CONFIRMED** (код: labels у всех узлов, фикс. шрифт, без scaling/drawThreshold) |

---

## 2. GraphRAG — «rebuild vs stuck» (G1–G3)

### 2.1 Механика status=building → FTS-only (кто выставляет, когда сбрасывается)

- Реестр поколений: `mca_embedding_index_generations`. `get_latest_embedding_generation` — `services/database.py:5501`; `ensure_embedding_generation(..., activate=False)` пишет `status='building'` при карантине — `services/database.py:5570`. Регистрация с `activate=False` — `services/summary_memory.py:1676` (`_register_index_generations`).
- Guard A06: `_index_generation_ok` — `services/summary_memory.py:1713–1765`: vec-path serviceable **только** при `status=='active'` И `fingerprint==current`. `building` → FTS-only + WARNING (коалисинг: тот же `(status, fp12)` в течение `GRAPHRAG_GEN_WARN_COOLDOWN_SECONDS`, default 300с — `summary_memory.py:1434–1440`, — идёт в DEBUG; `coalesced`-ветка :1747–1754).
- Сброс `building`: **только** атомарная активация shadow-rebuild — `_activate` — `services/graphrag_rebuild.py:897–948` (`building/validated → active` внутри одной транзакции с swap-таблицей). Альтернативный путь `activate_embedding_generation` (`database.py:5385`) gate'ится флагом и вызывается вне rebuild-лупа.
- Смысл `gen_fp == new_fp`: последнее поколение описывает **текущую** embedding-identity (96f80838f683), т.е. это НЕ config mismatch — это ещё не активированный build этой же конфигурации (шапка `services/graphrag_rebuild.py:5–7` описывает ровно этот вечный кейс preexisting-таблиц).

### 2.2 Прод-состояние (07.10 ~00:35 UTC)

```
graph_facts_vec gen=1 fp=96f80838f683 status=building
  provider=generativelanguage.googleapis.com model=gemini-embedding-001 dims=3072
  created ≈ 29.09 10:39 UTC
  pause_reason=rate_limit:quota_group  next_allowed_at=07.10 00:05 UTC (уже истёк)
  attempts_total=576   (576 pause-циклов за ~7.5 дней)
smart_archive gen=1 тот же fp, building, pause_reason=NULL, attempts_total=0
task_jobs (kind=graphrag_rebuild):
  7ed322e6  paused_rate_limit  reason=rate_limit:quota_group
            checkpoint processed=6627 last_id=7840   (graph_facts всего 16416 → ~40%)
            progress_at/updated_at/heartbeat = 06.10 03:57 UTC  (заморожено >20 ч)
  168adb23  validation_failed reason=knn_source_empty (smart_archive_facts: 0 строк)
Журнал 72ч: 0 событий PROGRESS/VALIDATED/ACTIVATED по graph_facts_vec;
каждый рестарт: BUILD_START→FAILED knn_source_empty по smart_archive (23:27:19, 23:28:51, …).
Предупреждения «not serviceable»: 55 за 72ч (0 coalesced).
```

### 2.3 Вердикт: STUCK, не healthy rebuild

Build не terminal и не «идёт»: он **квот-паузится в петле** и в окнах между рестартами не возобновляется:

1. **Первопричина — embedding-провайдер.** `rate_limit:quota_group` — классификация control-plane (`_handle_build_failure` → `EmbeddingGroupCoolingDown`, `graphrag_rebuild.py:1410–1444`). Фактический endpoint — `EMBEDDING_BASE_URL=https://apinet.cloud/v1` (модель gemini-embedding-001). 576 пауз за ~7.5 суток = провайдер стабильно режет по квоте/лимитам; прогресс (6627) стоит с 06.10 03:57.
2. **Дефект восстановления (код, G2).** Авто-resume — только in-process fire-and-forget: `_schedule_auto_resume` (`graphrag_rebuild.py:448–484`) умирает вместе с процессом. На рестарте `_ensure_job` для `paused_rate_limit` при неистёкшем `next_allowed_at` просто `return None` — **без планирования future-resume** (`graphrag_rebuild.py:1667–1673`). Post-release `maybe_schedule_rebuilds(include_failed=False)` не спасает: он вызывается после мгновенного фейла smart_archive, но `_ensure_job` снова даёт None (next_allowed в будущем на моменты 23:26/23:28 рестартов). Итог: job спит до **следующего рестарта после** истечения cooldown. При рестартах каждые ~1.3 ч это постоянный режим, а не исключение. (Смомент съёмки next_allowed_at=00:05 уже истёк при живом процессе — но в живом процессе никто больше `maybe_schedule_rebuilds` не вызовет.)
3. **Не скрытие warning:** guard честен, лечить надо recovery/провайдера, а не лог. Горизонт §25 (24ч wall-clock от `pause_started_at`, `graphrag_rebuild.py:423–445`) активен только при заходе в `run_job` — т.е. тоже ждёт resume-триггера; сброс горизонта после каждого успешного батча — by design (per-pause-run horizon).

### 2.4 Related-nonblocking (GraphRAG-окрестность)

- **smart_archive — бесконечный startup-цикл (low).** `smart_archive_facts` пуст (0) → каждый рестарт: BUILD_START→FAILED `knn_source_empty` → `validation_failed` (vectors preserved, T-4409) → на следующем startup переоткрывается (`_ensure_job` :1678–1684). Дешёвый, но вечный цикл + по паре событий в журнал на каждый рестарт; и поколение smart_archive навсегда `building` → свой warning на первый retrieval каждого процесса. Направление: `knn_source_empty` при пустом source — stable terminal с видимой причиной в health/UI, без переоткрытия по schedule.
- **UI-статус rebuild отсутствует (medium, §13/§9).** `rebuild_status()` (`graphrag_rebuild.py:1766–1786`) написан, но НЕ подключён ни к одному API/UI (grep web/ — 0 вхождений). Владелец видит только warning в логе; «Vector rebuild in progress N/M» и pause_reason/next_allowed в Analytics — нет. Направление: read-endpoint + карточка (B3 scope).
- **Warning-семантика (G3).** Коалисинг работает (0 coalesced-строк при 55 WARNING = предупреждения разрежены), но `_GEN_LOG_STATE` in-memory (`summary_memory.py:1431`) → рестарты обнуляют состояние и первый же retrieval каждого процесса снова WARNING. Направление: персистентный «последний warning-at» (реестр поколений) или прицепить к G2-карточке.

---

## 3. Random source — config-clarity (G4–G6)

### 3.1 Effective config на проде

```
mca_random_state: key_fingerprint=NULL, activated_at=NULL, has_batch=false,
  last_fallback_reason=provider_unconfigured, last_fallback_at=07.10 00:34:20 UTC
mca_random_batches: 0 партий
mca_random_draws: 30 (все pseudorandom; baseline 28/28 → +2)
События 72ч: random_fallback ×9, random_activation ×0, random_batch ×0
```

### 3.2 Вердикт: CONFIRMED — это configuration/degraded state

- `selected=quantum` подтверждается механикой: blocker отличен от NULL только при выбранном quantum (`resolve_effective` — `services/mca_random_source.py:1425–1437`; явный pseudorandom дал бы `(pseudorandom, None)` и **не** эмитил бы `random_fallback`). События есть → выбран quantum.
- Ключ реально отсутствует: `key_fingerprint=NULL`, партий 0 → `_provider_blocker` возвращает `provider_unconfigured` (`mca_random_source.py:1448–1453`). Это **корректный** код конфигурации, не runtime-сбой.
- Fallback честный: `memory.random_fallback_to_pseudorandom` default True (`:133`), pseudorandom-дераы журналируются с `fallback_reason` (`_prng_index_draw` :1630–1648); подпись в UI при фактическом PRNG — «псевдослучайный (локальный)», quantum-статус не показывается (`services/status_service.py:497–556`, `web/app.js:3623–3637`).
- **Notable transition (G6): CONFIRMED.** `_note_transition` — один emit на смену state-key, reset только на quantum-успех (`mca_random_source.py:1409–1422`). 9 событий/72ч ≈ по одному на процесс, реально сделавший fallback-draw (рестартов ~57; не каждый успел нарисовать). Спама per-draw нет (30 draws → 9 событий, и все — на границах рестартов). Минор: память перехода in-process → повтор события после рестарта (bounded, приемлемо).
- **UI/analytics (G5): состояние объясняется честно** (`blockerRu.provider_unconfigured = «ключ не настроен»`, `app.js:3607–3622`; snapshot отдаёт selected/effective/blocker/key_present — `status_service.py:536–548`). **Но путь исправления из UI физически отсутствует** — 14A.0 bootstrap paradox **CONFIRMED**: `GET /api/config` строит items только из `cache.get_all()` (`web/api/routes.py:489`), а сид секретов не создаёт строки (`services/pg_db.py:722` — `... and not spec.secret`). Незаданный `keys.random_quantum_api_key` не попадает в items → карточку «Случайность: подключение ANU» рисовать не из чего → ключ некуда ввести → `provider_unconfigured` вечен силами владельца. Прямой аналог задокументированного дефекта PG-only ключей (`plans/backlog.md:52`).
- Направление фикса (одной строкой): незаданный секрет присутствует в `/api/config` metadata как `configured=false` (синтез catalog-only items для secret-группы), без plaintext и без фиктивных строк в БД (контракт 14A.0, T-5262).

---

## 4. Парадигмы (13A) — CONFIRMED

### 4.1 Код

- Причина-гейт перекрывает результат попытки: `deep_sleep_status` — `web/api/memory_agi.py:635–636` ветка `gate_state.blocked → paradigms_reason=str(gate_state.reason)` стоит **раньше** ветки `_last_deep_reason(deep_log)` (:642–644). При активном cooldown владелец видит «cooldown» и никогда — реальную причину прошлой попытки. Ровно как сформулировано в 13A.
- Cooldown учитывает неуспешные попытки: `dream_worker.py:1821–1841` — `count_deep_attempts(...)>=1 → daily_limit`, `last_deep_attempt` + `memory.deep_sleep_min_interval_hours → skip cooldown`; комментарий на :1823–1825 фиксирует это как намерение («иначе … повторялись бы каждый тик»), т.е. развязка по классу причины (13A.3) отсутствует. Гейт-резолвер — `services/mca_gates.py:1664–1676`.

### 4.2 Прод

- Живой чат `-1002661910336`: **16 подряд `deep_skip status=no_anchors`** (с ~24.09 по 06.10 21:54 UTC, интервал ≈20ч = `deep_sleep_min_interval_hours`). Ни одной записи парадигмы; следующий автозапуск каждый раз закрыт cooldown'ом от неуспешной (пустой) попытки. В 00:34:20 scheduler-лог: `step=deep status=skip reason=cooldown … last_attempt=1791323675` — владельцу виден именно этот `cooldown`, а не `no_anchors`.
- Второй чат `5885953495`: `deep_skip deep_disabled (source=global)` — отдельная честная ветка master-флага.
- Направление фикса (одной строкой): в API/UI разъести `scheduler_gate` (cooldown/schedule/budget) и `last_attempt_result` (+счётчики anchors/candidates/written, 13A.1), и ввести bounded-backoff по классу причины для no_anchors/unchanged vs техошибок (13A.3).

## 5. Граф знаний runtime (13B) — CONFIRMED

- `renderCognitionGraph` — `web/app.js:14946–15001`: `nodes: { shape:'dot', size:14, font:{size:12} }`, `edges: { font:{size:10} }` — фиксированные подписи у **всех** узлов и рёбер на всех масштабах; `scaling`/`drawThreshold`/`maxVisible`/zoom-handler отсутствуют; семантического зума и selected-neighborhood-label нет (есть только detail-panel по `selectNode` :15013–15023). Стена текста при сотнях узлов — код-подтверждена.
- Данные не режутся presentation-слоем: DataSet из `/api/memory/graph` как есть (:14965–14966), canonical `label` из API; у API есть `truncated`-флаг (квота бэкенда, не UI-урезание).
- Направление фикса (одной строкой): semantic zoom через `scaling.label.drawThreshold/maxVisible` + zoom-listener и labels только для selected neighborhood; canonical labels/DataSet не трогать (13B.1–13B.3).

---

## 6. Incidental findings

| Классификация | Находка | Серьёзность |
|---|---|---|
| related-nonblocking | smart_archive вечный startup-цикл `knn_source_empty` (§2.4) | low |
| related-nonblocking | `rebuild_status()` не подключён к API/UI — GraphRAG rebuild невидим владельцу (§2.4) | medium |
| uncertain | Расхождение в дампе: registry `next_allowed_at=07.10 00:05` при job `updated_at=06.10 03:57` (оба пишет `_apply_pause` одним вызовом); точная линия последней записи не восстановлена по журналам. На вердикт STUCK не влияет (пауза/прогресс подтверждены независимо) | low |
| uncertain | В реестре поколений `provider=generativelanguage.googleapis.com`, а фактический endpoint — `EMBEDDING_BASE_URL=https://apinet.cloud/v1` (прокси); вероятно `_embedding_provider()` не отражает base-url (endpoint покрыт `endpoint_fingerprint`) | low |
| unrelated/pre-existing | 114 start/stop systemd-событий за 72ч — операционный контекст; сам по себе вне скоупа, но усиливает G2/G3/G6 | info |

## 7. Что НЕ делалось

Код/тесты/планы/прод не изменялись; SSH — read-only (запросы `mode=ro`, без мутаций); секреты не читались и не выводились.
