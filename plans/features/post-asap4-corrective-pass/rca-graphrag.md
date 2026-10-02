# RCA: GraphRAG/embeddings прод-runtime — бесконечный EMBEDDING_GENERATION_PAUSED rate_limit:quota_group (T-4501)

Feature: `post-asap4-corrective-pass` · Задача: **T-4501 [@DevOps]** · Режим: **read-only** (ничего не менялось, сервис не рестартился) · R17 соблюдён (ключи не читались/не выводились; только env-имена, alias'ы и длины значений).
Собрано: 2026-10-02, 11:08–11:20 UTC. Прод: `racknerd-f4e3456` (198.46.175.136), сервис `admin_bot` (WorkingDirectory `/var/www/admin_bot`), код на проде = деплой 2.58.45 (HEAD `b5eaecd`), процесс PID 3008232.
Источники: `journalctl -u admin_bot`, SQLite `/var/www/admin_bot/local_database.db` (все запросы `file:...?mode=ro`), PG `bot_settings` (read-only, имена/длины без значений), исходники на проде (`services/embedding_control_plane.py`, `services/graphrag_rebuild.py`).

---

## 0. Резюме механизма (3 предложения)

Пул из **3 ключей** резолвится в **одну квота-группу `unknown`**, потому что ladder-резолв групп (§5) не находит ни provider-metadata, ни label'ов (`EMBEDDING_QUOTA_GROUP_LABELS` не задан) — safe default «все ключи = одна группа». Провайдер (Gemini embedding) отдаёт 429 класса **spend** (дневной бюджет) **без Retry-After**, на что контрол-плейн отвечает парковкой группы на дефолтные **20 секунд** (`next_allowed_at = now + 20s`), после чего auto-resume джобы обязан разбудить rebuild. Получается замкнутый цикл «resume → 1 реальный HTTP-429 → pause 20с → resume…» ≈3 попытки/мин без шанса на успех до суточного reset — ротации на другой ключ нет, потому что все ключи в одной заблокированной группе.

---

## 1. (а) Почему группа одна / `unknown`

**Код резолва** — `services/embedding_control_plane.py`:

- Ladder описан в docstring (строки 15–17): provider/runtime metadata → hot `keys.embedding_quota_group_labels` (формат `alias:group[,…]`) → unknown.
- `resolve_quota_group()` (строки 218–231): шаг 1 (provider metadata) пропускается — «machine-readable project metadata недоступна»; `group = labels.get(alias)`; если label нет → `return UNKNOWN_GROUP_ID, False`. Комментарий явно: «unknown → ОДНА общая группа (safe default)».
- `build_credential_pool()` (строки 246–292): label'ы берутся из `_hot_get("keys.embedding_quota_group_labels", _settings_value("EMBEDDING_QUOTA_GROUP_LABELS", ""))`. **Все** entries получают один и тот же `base_url`/`model`/`provider`; group — результат `resolve_quota_group` для своего alias.

**Конфиг на проде (без секретов):**

| Источник | Факт |
|---|---|
| PG `bot_settings` (hot-config) | `keys.embedding_api_key` SET (len 55), `keys.embedding_fallback_api_key` SET (len 55), `keys.embedding_fallback_api_key_2` SET (len 55); `keys.embedding_quota_group_labels` — **отсутствует** |
| `.env` (имена only) | `EMBEDDING_BASE_URL` SET, `EMBEDDING_FALLBACK_API_KEY` SET, `EMBEDDING_FALLBACK_API_KEY_2` SET, `EMBEDDING_MODEL_NAME` SET; `EMBEDDING_API_KEY` в env нет (primary приходит из hot-config); `EMBEDDING_EXTRA_API_KEYS` нет; `EMBEDDING_QUOTA_GROUP_LABELS` — **не задан** |
| Итог пул | **3 credential'а**: alias `primary` + `fallback_1` + `fallback_2`. Extras: 0 |
| Endpoint/model (из реестра поколений, не секрет) | provider `generativelanguage.googleapis.com`, model `gemini-embedding-001`, dims 3072 — **одни на все три ключа** |

**Подтверждение в рантайме:** каждая строка rate-limit в journald имеет `group=unknown` (148 строк за 4ч, 100% совпадение структуры). Сплит «fallback_2 = другой аккаунт» (гипотеза из prod-facts Q1) без label'ов **не различим коду**: даже если ключи принадлежат разным проектам, они все попадают в одну группу `unknown`, и §10-семантика «не дёргать ту же группу другим ключом» блокирует ротацию целиком.

Побочное наблюдение: `build_credential_pool()` читает только `models.embedding_base_url` — hot-ключ `models.embedding_fallback_base_url` (SET, len 57) пулом **не используется**: все три ключа бьют в один endpoint по построению.

---

## 2. (б) Механика 20-секундного re-hit (цепочка с file:line)

Наблюдаемый journald-паттерн (каждые ~20.4с, пример 11:02:50–11:09:21 UTC):

```
services.graphrag_rebuild      INFO  EMBEDDING_GENERATION_BUILD_START | index=graph_facts_vec | gen=1 | resumed=True | job=7ed322e68a0d433b   (+0.0s)
services.embedding_control_plane WARN embed rate limit | group=unknown | state=exhausted | kind=spend | retry_after=None | cooldown_s=20.0 | 429_last_10m=59   (+0.3s)
services.graphrag_rebuild      WARN  EMBEDDING_GENERATION_PAUSED | reason=paused_rate_limit | kind=rate_limit:quota_group | cooldown_s=20.0 | checkpoint preserved   (+0.4s)
```

Каденция BUILD_START за окно (4ч): 298 стартов; интервалы: 20s×63, 21s×62, 22s×12, 19s×2, остальное — края окна. Каденция rate-limit строк по 10-мин бакетам: 10:20→25, 10:30→30, 10:40→29, 10:50→29, 11:00→29.

Кодовая цепочка цикла:

1. **Auto-resume**: `_schedule_auto_resume()` → `_resume_later()` — `services/graphrag_rebuild.py:329–365`: `asyncio.sleep(delay)` → джоба в `AUTO_RESUME_STATUSES` (вкл. `paused_rate_limit`, строки 73–75, 87) → сверка `gen.next_allowed_at` (если ещё в будущем — перепланирование на остаток, 346–349) → `_job_cas(queued, reason_code="cooldown_expired")` → `_registry_resume` (сброс pause_reason/next_allowed_at, 252–265) → `maybe_schedule_rebuilds()`. (`cooldown_expired` — это reason_code джобы в task_jobs, в journald не логируется — поэтому grep по журналу даёт 0.)
2. **Планировщик**: `maybe_schedule_rebuilds()` — `graphrag_rebuild.py:1382+`: gen `building` с совпавшим fingerprint → `_ensure_job` → lease `embedding_rebuild_lease` (permit `embedding_full_rebuild_permit`, §23) → `run_job` → `EMBEDDING_GENERATION_BUILD_START` (лог 971–973).
3. **Реальный HTTP-вызов**: `executor.embed()` — `embedding_control_plane.py:999+`: `_pick_credential()` (1096–1108) → первый healthy ключ группы, не blocked. Спустя 20с группа auto-heal из exhausted → healthy (`group_blocked`, 448–461: «if next_allowed_at expired → set healthy»). → HTTP к Gemini → **429 spend**.
4. **Обработка 429**: `_on_error()` — `embedding_control_plane.py:1134–1190`:
   - `classify_rate_limit()` (316–357): маркеры тела `_SPEND_MARKERS = ("billing","spend","budget","balance")` (312–315) → `kind=spend`; `retry_after=None` (Gemini не отдаёт header — прод-факт Q4, комментарий 362–365).
   - `retry_after_seconds()` (361–370): нет Retry-After → **дефолт `EMBED_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS` = 20.0** (kind не учитывается!).
   - `is_quota_unavailable()` (372–390): `kind in (RATE_DAILY, RATE_SPEND) → True` → `state=GROUP_EXHAUSTED`.
   - **`next_allowed = int(time.time() + delay)` = now+20s (1153, 1158)** — для дневного лимита выдаётся тот же 20-секундный horizon, что и для burst.
   - `mark_credential(текущий, HEALTH_COOLDOWN, cooldown_s=20)` (1163–1165); `set_group_state(exhausted, now+20)` с persist в `embedding_quota_state` (1167–1169; SQL 470–495); лог 1178–1183; `return "defer"`.
5. **Ротации нет**: возврат в цикл embed → `_pick_credential()` (1096–1108): ключ1 health-cooldown, ключи 2–3 healthy, но `group_blocked("unknown")` → True для **всех** ключей одной группы → None → ветка «группа cooling» → `acquire()` бросает `EmbeddingGroupCoolingDown` (680–711, 773–780). §10-защита «тот же group не дёргается другим ключом» при одной группе = **ни один ключ не пробуется**, пул фактически вырожден в первый ключ.
6. **Pause-конверсия**: обработчик в `graphrag_rebuild.py` (1290–1316): ловит `EmbeddingGroupCoolingDown` → берёт `exc.next_allowed_at` → `delay = next_allowed - now` (~19–20с; отсюда виденный в 10:18:59 `cooldown_s=19.0` — остаток) → `_apply_pause(ST_PAUSED_RATE_LIMIT, reason="rate_limit:quota_group")` → `_registry_pause` инкрементирует `attempts_total` (241–244) → `_schedule_auto_resume(delay)` → **GOTO 1**.

Итого цикл = 19–20с парковка + ~0.3–0.4с на BUILD_START→429 ≈ 20.4с. Это ровно «rebuild повторно долбится каждые ~20 сек».

---

## 3. (в) Почему 429-шторм при «exhausted» — кто продолжает слать

- Единственный отправитель — **сам auto-resume цикл rebuild-джобы** `7ed322e68a0d433b89f03ef66117c367` (task_jobs: kind `graphrag_rebuild`, status `paused_rate_limit`, checkpoint_ref `cp:graph_facts_vec:1`). Онлайн-трафика, дёргающего embeddings, в окне не видно: каждая rate-limit строка 1:1 сопровождает BUILD_START цикла.
- Реальная интенсивность: **1 исходящий HTTP-429 за цикл** ≈ 29–30/10мин (~3/мин). Публичный счётчик `429_last_10m=59` **задвоен**: `record_rate_limit()` вызывается дважды за цикл — один раз на реальном 429 (`embedding_control_plane.py:1160`) и второй раз в pause-конверсии CoolingDown (`graphrag_rebuild.py:1297`). Стабильные 59 ≈ 2 × 29.5 циклов/10мин.
- Шторм принципиально не может succeed: kind=spend — дневной бюджет проекта провайдера; 20-секундные попытки не могут его восстановить, но каждая стоит реального запроса и инкремента `attempts_total`.

---

## 4. Хронология (деплой-корреляция)

| Время (UTC) | Событие |
|---|---|
| ≤ 29.09 ~14:39 | Созданы оба generation (registry `created_at=1790678362`), gen=1, fp `96f80838f683` |
| до 10:14 | Предыдущий процесс (PID 2796224). За 08:00–10:14 — **0** событий rate-limit/pause в journald. При этом `attempts_total` уже был 14 (prod-facts Q1, requirements-map) — редкие ретраи копились с 29.09. Spend-бюджет периодически исчерпывался и раньше |
| 10:14:17 | Деплой 2.58.45: SIGTERM, systemd stop |
| 10:15:17 | Старт нового процесса (PID 3008232). При старте `load_group_states()` подтягивает persisted-строку `embedding_quota_state` (state из прошлых сессий) |
| 10:18:40 | Первый BUILD_START после рестарта: `resumed=True`, job `7ed322e6…`, checkpoint ~processed=5500 (рестарт-персистентность сработала, позиция не потеряна) |
| 10:18:59 | Первый 429: `429_last_10m=1`, PAUSED c `cooldown_s=19.0` (остаток next_allowed_at) |
| 10:19–10:28 | Интерливинг прогресс/429: processed 5500→5508→5594→…→6371→6379 (батчи проходили, квота ещё имела headroom; счётчик 1→3→5→…→+2/цикл) |
| 10:41:40 / 10:49:12 | Последние прогресс-строки: processed=6387→**6395**, frontier=7608 |
| ~с 10:50 | Чистый цикл без прогресса: каждый BUILD_START → мгновенный (0.3с) 429 spend |
| 10:20–11:10 | Стабильно 25–30 rate-limit строк/10мин, `429_last_10m` ~59, счётчик циклов BUILD_START: 326, PAUSED: 162 (10:15–11:15) |
| 11:13:48 | Состояние БД: `embedding_quota_state` = единственная строка `unknown/exhausted/next_allowed_at=updated_at+20/note="429 kind=spend ra=None"`; registry `graph_facts_vec`: `attempts_total=157` (14 → 157 за ~1ч цикла) |

Вывод: **exhausted-spend — провайдерная реальность** (дневной бюджет Gemini-проекта), а не следствие деплоя. Но деплой-рестарт **разбудил** застрявшую paused-джобу через стартовый `maybe_schedule_rebuilds` (graphrag_rebuild.py:331–332 «до рестарта добирает») и запустил бесконечный 20-секундный цикл, которого утром не было.

**smart_archive** (отдельная ветка, не циклит): 10:18:59 `BUILD_START gen=1 resumed=False` → немедленно `EMBEDDING_GENERATION_FAILED reason=knn_source_empty (source empty)` (source-таблица `smart_archive_facts` пуста). В реестре: `status=building, pause_reason=NULL, attempts_total=0` — терминальный fail не отразился на статусе (мелкое расхождение, к шторму отношения не имеет).

---

## 5. SQLite-факты (read-only снимок 11:13–11:15 UTC)

**`embedding_quota_state` — все строки (1 шт.):**

| quota_group_id | state | next_allowed_at | note | updated_at |
|---|---|---|---|---|
| `unknown` | exhausted | 1790939648 | `429 kind=spend ra=None` | 1790939628 |

Разница next_allowed_at − updated_at = **20с** — инвариант цикла.

**`mca_embedding_index_generations`:**

| index | gen | status | pause_reason | next_allowed_at | attempts_total |
|---|---|---|---|---|---|
| graph_facts_vec | 1 | building | `rate_limit:quota_group` | 1790939648 | **157** |
| smart_archive | 1 | building | NULL | NULL | 0 |

**`task_jobs`:**
- Rebuild-джоба `7ed322e68a0d433b89f03ef66117c367`: kind `graphrag_rebuild`, status `paused_rate_limit`, reason `rate_limit:quota_group`, checkpoint payload `{"cursor": {"last_id": 7608, "processed": 6395}}`, coalesce_key `graphrag_rebuild:graph_facts_vec:96f80838…`. Checkpoint **сохраняется** (работа не дублируется, но и не двигается: processed 6395 = последняя прогресс-строка 10:49:12).
- **Lease-шторм**: 163 строки `embedding_rebuild_lease` (все `finished/released`) за 10:18:40–11:15:30 — по одной на каждый цикл (~163 строк/час мусора в task_jobs; churn-побочный эффект).
- Вторая graphrag-джоба — `validation_failed` (историческая, к циклу не относится).

---

## 6. Credential pool: структура (без секретов)

```
pool (3 entries, строятся лениво на каждый вызов — embedding_control_plane.py:970-974, 246-292):
  primary     ← hot keys.embedding_api_key          (PG, len 55)
  fallback_1  ← hot keys.embedding_fallback_api_key (PG, len 55; env EMBEDDING_FALLBACK_API_KEY тоже SET)
  fallback_2  ← hot keys.embedding_fallback_api_key_2 (PG, len 55; env тоже SET)
  extras      ← EMBEDDING_EXTRA_API_KEYS отсутствует → 0
  base_url    ← models.embedding_base_url (общий для всех; fallback_base_url кодом пула игнорируется)
  model       ← gemini-embedding-001; provider: generativelanguage.googleapis.com
  quota labels: keys.embedding_quota_group_labels / EMBEDDING_QUOTA_GROUP_LABELS → НЕ заданы
  ⇒ все 3 alias → quota_group_id="unknown" (quota_group_known=False) → ОДНА группа
```

Ответ на «проверь логику группировки»: labels нет → группировка вырождена; **распределения по группам объективно нет** (consistent с риск-строкой tasks.md «Распределения по ключам объективно нет»).

---

## 7. (г) Точки для механизма-фикса (для T-4502 @Architect)

1. **Kind-aware парковка группы** (главное): `embedding_control_plane.py:1153–1169` — при `kind ∈ {spend, daily}` (и/или RA>ceiling) ставить `next_allowed_at` на горизонт до reset/длинный horizon (часы), а не `now + retry_after_seconds()`. Сейчас kind влияет только на state (exhausted), но не на длительность. Точка принятия решения: `_on_error`, delay приходит из `retry_after_seconds()` (361–370), который kind не видит.
2. **Auto-resume с нелинейным backoff + рестарт-персистентностью**: `graphrag_rebuild.py:329–365` — сейчас честно уважает `next_allowed_at` (346–349), но при 20с-horizon это даёт вечный цикл; горизонт пауз (`retry_horizon`, §25) до исчерпания не срабатывает, т.к. статус не terminal и бюджет attempt не тратится (defers не считаются лобовыми попытками, `embedding_control_plane.py:1008–1011`). Нужен счётчик подряд-исчерпаний группы с персистентной меткой (переживает рестарт) или parking-until-reset в самой группе.
3. **Честная ротация/диагностика**: `_pick_credential` (1096–1108) корректно блокирует same-group перебор, но при одной unknown-группе — «распределять некуда»; панель/логи должны это явно репортить (сейчас `group=unknown` только в warning). Опция `EMBEDDING_QUOTA_GROUP_LABELS` (owner-config, env/hot) уже поддержана кодом (193–216, 253–254) — позволит разделить ключи по группам без изменений кода.
4. **Задвоение счётчика 429**: убрать повторный `record_rate_limit()` в `graphrag_rebuild.py:1297` (уже учтён в `embedding_control_plane.py:1160`) — метрика 429_last_10m завышена ×2, что маскирует реальную интенсивность.
5. **Lease-churn**: `_ensure_job`/lease создают строку task_jobs на каждый цикл (163/час) — парковка из п.1 автоматически устранит; при желании — retention для finished lease-строк.
6. **Пул строится на каждый вызов** (`pool()` → `build_credential_pool()` каждый embed, 970–974) — не баг для цикла, но отметка: hot-config изменения подхватываются живьём, включая labels (значит fix label'ами возможен без рестарта).

Kill-switch контекст для фикса: `EMBED_QUOTA_GROUP_COOLDOWN_ENABLED` (env-only, default ON, `embedding_control_plane.py:92–94`) — при OFF group-cooldown отключается полностью (перебор ключей «как раньше»); новый механизм должен следовать тому же паттерну (env-only, default ON, OFF = бит-в-бит).

---

## 8. Воспроизводимость (read-only команды)

```bash
# Логи: каденция и счётчики
journalctl -u admin_bot --since "-4 hours" --no-pager -o short-iso \
  | grep -E "EMBEDDING_GENERATION_BUILD_START|embed rate limit|EMBEDDING_GENERATION_PAUSED" | tail -100

# SQLite (read-only URI)
sqlite3 "file:/var/www/admin_bot/local_database.db?mode=ro" \
  "SELECT * FROM embedding_quota_state; SELECT index_name,status,pause_reason,next_allowed_at,attempts_total FROM mca_embedding_index_generations;"
# (фактически выполнено python3 + sqlite3 stdlib: file:...?mode=ro; sqlite3 CLI на хосте отсутствует)

# Код
grep -n "next_allowed = int(time.time() + delay)" services/embedding_control_plane.py   # :1158
grep -n "EMBED_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS" services/embedding_control_plane.py # :370 (default 20.0)
sed -n '329,365p' services/graphrag_rebuild.py                                          # auto-resume
```

Секретов в отчёте нет: ключи представлены alias/env-именами и длинами значений; тексты запросов/ответов не копировались (R17).
