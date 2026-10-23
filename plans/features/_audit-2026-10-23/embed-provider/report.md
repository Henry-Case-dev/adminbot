# EMBED-PROVIDER-CHECK — переключение эмбеддингов на apinet.cloud

Дата проверки: **2026-10-22T16:52–17:00Z** (сервер UTC; локально у владельца UTC+12 = 2026-10-23 05:00).
Прод: `198.46.175.136`, `/var/www/admin_bot`, HEAD `fbf9013d`, бот active, `NRestarts=0`, `/healthz` → 200 (`2.58.111`).
Режим: read-only + 3 контролируемых embed-вызова. Ничего не деплоил, не рестартовал, `.env` не менял.

## Вердикт

**Квота разблокирована (23.10, см. раздел «Разблокировка 23.10»): новый ключ apinet исправен, эмбеддинги через него идут. Векторная запись/retrieval остаются FTS-only до перестройки индекса под новую identity — это отдельная задача, не квоты.**

- Конфиг применён: primary → `https://apinet.cloud/v1`, модель `gemini-embedding-001`, ключ заменён в 16:40:20Z.
- Новый ключ apinet: **HTTP 200**, `model=gemini-embedding-001`, **вектор 3072**, 1.9–4.4 с — рабочий.
- Размерность совпадает с индексом (3072) — критичного несовпадения нет.
- Parking старого Google-аккаунта (`exhausted` до 2026-10-23T00:05Z) **снят с пути** сменой ярлыков квот-групп: `apinet_paid`, `google_free_1`, `google_free_2` — `healthy`; старые строки остались в БД, но у них 0 ключей и они ни на что не влияют.

## 1. Effective-конфиг

| Параметр | Значение (без секретов) | Источник |
|---|---|---|
| `models.embedding_base_url` | `https://apinet.cloud/v1` | PG hot, updated 2026-10-22T16:40:20Z (env совпадает) |
| `keys.embedding_api_key` | задан (len 51) | PG hot, updated 2026-10-22T16:40:20Z; env пуст |
| `models.embedding_model_name` | `gemini-embedding-001` | PG hot (29.08) + env |
| `models.embedding_dim` | `3072` | PG (29.08) + env default |
| `models.embedding_fallback1_base_url` | `https://generativelanguage.googleapis.com/v1beta/openai` | PG hot, 16:41:12Z |
| `models.embedding_fallback1_model` | `gemini-embedding-001` | PG hot, 16:41:12Z |
| `keys.embedding_fallback_api_key` | задан (len 53) | PG hot (12.09) + env |
| `models.embedding_fallback2_base_url` | `https://generativelanguage.googleapis.com/v1beta/openai` | PG hot, 16:41:34Z |
| `models.embedding_fallback2_model` | `gemini-embedding-001` | PG hot, 16:41:34Z |
| `keys.embedding_fallback_api_key_2` | задан (len 53) | PG hot (12.09) + env |
| `keys.embedding_quota_group_labels` | **не задан** | нет строки в PG, env пуст → группы авто по alias |
| `EMBED_CONTROL_PLANE_ENABLED` | True | env/default |

## 2. Пул креденшелов и группы (`build_credential_pool` + `pool_rotation_diagnosis`)

Диагноз: `keys=3, groups=[fallback_1, fallback_2, primary], known=true, degenerate=false, degraded=false, primary_present=true, primary_source=hot`. Warning «нет primary» не возникает.

| alias | provider (host) | model | quota_group | known | group source | key source |
|---|---|---|---|---|---|---|
| primary | apinet.cloud | gemini-embedding-001 | primary | да | auto (alias) | hot |
| fallback_1 | **apinet.cloud** | gemini-embedding-001 | fallback_1 | да | auto | hot |
| fallback_2 | **apinet.cloud** | gemini-embedding-001 | fallback_2 | да | auto | hot |

**Важно:** `build_credential_pool()` подставляет **один** base_url (primary) всем трём ключам. Отдельные Google-адреса из `models.embedding_fallback1/2_base_url` видны только в `resolve_embedding_profiles()` (панель/identity), но **executor их не использует**. То есть «два запасных Google-слота» в текущем dispatch-пути фактически не задействованы (см. находку F2).

## 3. Состояние квот (SQLite `embedding_quota_state`) — до смены labels (17:14Z)

| group_id | state | next_allowed_at (UTC) | note | updated_at (UTC) |
|---|---|---|---|---|
| primary | exhausted | 2026-10-23T00:05:00Z | parked kind=spend est=utc_day_end | 2026-10-22T00:14:55Z |
| fallback_1 | exhausted | 2026-10-23T00:05:00Z | parked kind=spend est=utc_day_end | 2026-10-22T00:14:59Z |
| fallback_2 | exhausted | 2026-10-23T00:05:00Z | parked kind=spend est=utc_day_end | 2026-10-22T00:15:06Z |
| unknown | exhausted | 2026-10-13T00:05:00Z (истёк) | parked kind=spend est=utc_day_end | 2026-10-12T00:05:08Z |

- Новый apinet-ключ получил группу **`primary`** (auto по alias — labels не заданы), т.е. **унаследовал `exhausted`** от прежнего ключа.
- Parking записан **22.10 00:14Z**, когда в `keys.embedding_api_key` был ещё Google-ключ; ключ заменён только 22.10 16:40Z. Принадлежность parking прежнему аккаунту доказана.
- После проверок состояние **не менял** (см. §9).

## 4. Backlog и очередь

- `graph_facts` = **20 051**; пригодных (`expires_at IS NULL OR > now`) = **15 819**.
- `graph_facts_vec` (live) = **16 003** строк; поколение `graph_facts_vec_g1` (building) = **9 797**.
- **Backlog = 4 170** пригодных фактов без вектора (ранее в аудите было 4 162 — сходится, +8 фактов за 50 мин).
  - chat `-1002661910336`: 3 658, самый старый **2026-10-02T18:23Z**;
  - chat `-1004482340693`: 507, самый старый 2026-10-08T16:26Z;
  - chat `1313107079`: 5.
- Просроченных без вектора: 497 (в backlog не входят — корректно).
- `smart_archive_facts` = **0** → архивного backlog нет (индекс пуст).
- Данные не потеряны: факты лежат в `graph_facts`, запись шла text-only (`FACTS_EXTRACT ... text_only_vector_deferred`).
- Последняя rebuild-джоба: `paused_rate_limit` (`rate_limit:quota_group`), processed 9 797; генерация создана 2026-09-29, 592 попытки.

## 5. Живой probe — первый раунд (3 вызова, штатный клиент `LLMClient`/control plane)

| # | Путь | Куда | Результат |
|---|---|---|---|
| 1 | `ecp.execute_embed` (как рантайм) | — | `EmbeddingGroupCoolingDown: primary until 1792713900` (2026-10-23T00:05Z), HTTP-вызова не было |
| 2 | `llm.embed_once` (тот же ключ/URL, обход parking — диагностика) | `https://apinet.cloud/v1/embeddings` | **200**, `model=gemini-embedding-001`, **dim=3072**, 1 915 мс, usage `prompt_tokens=28` |
| 3a | `llm.embed_once` fallback_1 | `generativelanguage.googleapis.com/v1beta/openai` | **200**, dim=3072, 454 мс |
| 3b | `llm.embed_once` fallback_2 | тот же Google | **200**, dim=3072, 470 мс |

- Вызов №2 шёл именно на **apinet** (зафиксирован `base_url` в перехвате `_post`), не на Google.
- Rate-limit заголовков провайдер не отдал (только `date`/`content-type`) → лимиты apinet **UNKNOWN**.
- Оба Google free-ключа сейчас отвечают 200 → их квота на текущий момент доступна (parking от 22.10 уже не отражает действительность).

## 6. Размерность и индекс

| Объект | Размерность |
|---|---|
| `graph_facts_vec` (vec0) | `float[3072]` (+ int8[3072]) |
| `graph_facts_vec_g1` (vec0) | `float[3072]` |
| `smart_archive`, `smart_archive_g1` | `float[3072]` |
| `embedding_cache` (11 656 строк) | min=max=**3072** |
| `mca_embedding_index_generations` | `dims=3072` |

**Совпадение: да (3072 = 3072).** Критичного блокера размерности нет.

Нюанс identity: отпечаток поколения (`96f808…`) привязан к host `generativelanguage.googleapis.com`. После смены host на `apinet.cloud` fingerprint текущего конфига станет другим → существующие поколения (все в `building`) не могут обслуживать/принимать новые векторы; для нового провайдера нужна новая генерация (rebuild). Индекс и так был в карантине (FTS-only) с 29.09, так что смена провайдера это не ухудшила, но и «просто заработать» без перестройки не даст.

## 7. Хватает ли квоты (с допущениями)

Факты с прода:
- сообщения: 1 142–3 328/сутки за 7 дней (среднее ≈1 820);
- новые факты: 68–449/сутки (среднее ≈210);
- прирост `embedding_cache`: ровно 256/сутки (наблюдаемо; трактую как нижнюю оценку фактических API-эмбеддингов);
- текущий batch = 50, concurrency стартует с 1 (AIMD), latency одиночного вызова apinet ≈1.9 с.

Расчёт:
- дневной поток в худшем допущении «каждое сообщение = вектор»: **до 5 000 векторов/сутки** ≈ 100 HTTP-вызовов/сутки при batch 50 ≈ 4 вызова/час;
- backlog 4 170 + перестройка под новую identity (пригодных фактов 15 819) → **≈316 HTTP-вызовов** на полный reindex;
- токены: ~150 токенов/факт × 15.8k ≈ 2.4M входных токенов на полную перестройку.

Вывод: по объёму это очень маленькая нагрузка (порядка сотни вызовов в сутки), любой платный тариф apinet её выдержит. Но конкретные RPM/RPD/TPM apinet **не публикует** (в docs только коды `429` «превышен лимит ключа» и `402` «недостаточно средств») → формально **UNKNOWN**. Практический риск — не rate-limit, а **баланс кошелька** (код 402) и отсутствие заголовков остатка. Google free-слоты: оба ключа сейчас 200; их RPD сбрасывается в полночь **Pacific**, а не UTC (док Google от 2026-10-15), т.е. оценка `utc_day_end` в приложении для Google неточна.

## 8. Применение без рестарта

- Код: `POST /api/config` → `_post_config_global` → `cache.set_many` (атомарно обновляет in-memory кэш) → `hot.get` на каждом embed-вызове; пул строится заново на каждый вызов (`EmbeddingExecutor.pool()` → `build_credential_pool`). **Рестарт для base_url/ключа не нужен.**
- Логи подтверждают: `[config_cache] set_many | keys=1` + `[api] config updated | key=keys.embedding_api_key` (16:40:20Z), затем `models.embedding_base_url` (16:40:20Z), `models.embedding_fallback1_*` (16:41:12Z), `models.embedding_fallback2_*` (16:41:34Z).
- Оговорка: при `EMBED_CONTROL_PLANE_ENABLED=false` (legacy-путь) `LLMClient` кэширует base_url в конструкторе → там рестарт понадобился бы. Сейчас флаг ON, путь executor'а.

## 9. Устаревший parking — что сделано и что нужно

**Сделано (на момент первой проверки):** ничего не менял. Доказано, что parking относится к прежнему аккаунту и блокирует новый; но штатного способа снять его у работающего процесса нет:
- admin API/CLI для сброса `embedding_quota_state` отсутствует (единственный writer — `set_group_state` из error-пути executor'а);
- правка SQLite не очистит in-memory mirror живого процесса (он перечитывает БД только при старте через `load_group_states`);
- рестарт запрещён рамками лейна (и сам по себе не поможет: загрузит те же `exhausted` до 00:05Z).

**Что нужно (одно из двух):**
1. **Владельцу в админке** задать `keys.embedding_quota_group_labels` новыми именами групп под новый аккаунт, например:
   `primary:apinet_paid, fallback_1:google_free_1, fallback_2:google_free_2`
   → применится без рестарта, группы будут `healthy`, старые строки останутся в БД для истории. Это же правильно и на будущее: каждый аккаунт = своя группа.
2. Либо **подождать до 2026-10-23T00:05Z** — `group_blocked()` сам снимет истёкший parking при следующем embed-вызове.

**Итог:** вариант 1 разрешён владельцем и выполнен — см. следующий раздел.

## Разблокировка 23.10 (сервер UTC: 2026-10-22T17:15Z)

Владелец разрешил одно ограниченное изменение конфигурации штатным путём приложения. Выполнено ровно одно действие: установка `keys.embedding_quota_group_labels`.

**Что изменено**

| | |
|---|---|
| Ключ | `keys.embedding_quota_group_labels` |
| Было | не задан (группы авто по alias: `primary`, `fallback_1`, `fallback_2`) |
| Стало | `primary:apinet_paid,fallback_1:google_free_1,fallback_2:google_free_2` |
| Путь | `POST /api/config` живого процесса (тот же эндпоинт, что у админки) с подписанным TMA initData владельца (id 5885953495, роль `admin`); без правки БД вручную, без рестарта |
| Ответ | `200 {"updated": ["keys.embedding_quota_group_labels"]}` |

**Где видно**
- Живой кэш: `GET /api/config` до — `None`, после — новое значение (ответ живого процесса).
- PG: `bot_settings['keys.embedding_quota_group_labels']` = новое значение.
- Лог процесса: `[config_cache] set_many | keys=1` + `[api] config updated | key=keys.embedding_quota_group_labels | by=5885953495` (17:15:00Z).
- `/api/memory/embeddings` (живой рантайм): rotation `grouped`, группы `apinet_paid`, `google_free_1`, `google_free_2`; все credential'ы `healthy`, `quota_group_source=explicit`.

**Состояние квот до/после**

| Группа | До | После |
|---|---|---|
| primary (старая) | exhausted → 2026-10-23T00:05Z | без изменений, **0 ключей**, ни на что не влияет |
| fallback_1 / fallback_2 (старые) | exhausted → 2026-10-23T00:05Z | без изменений, 0 ключей |
| unknown (старая) | exhausted (истёк 13.10) | без изменений |
| **apinet_paid** (primary) | — | **healthy** (строки в `embedding_quota_state` нет — штатное состояние здоровой группы) |
| **google_free_1 / google_free_2** | — | **healthy** |

Старые `exhausted`-строки остались в SQLite как история; панель показывает их только потому, что у них ещё активен cooldown, `keys: 0`.

**Probe после разблокировки (1 вызов, штатный control plane `execute_embed`, P2)**
- `EXECUTOR_OK`, HTTP **200**, host **apinet.cloud**, `model=gemini-embedding-001`, **dim=3072**, latency **4 356 мс** (одиночный вызов; ранее 1 915 мс — разброс сети/провайдера).
- Rate-limit заголовков по-прежнему нет → лимиты apinet UNKNOWN.

**Очередь**
- Таблицы `embedding_queue` в схеме нет; фактическая очередь — `task_jobs` (`graphrag_rebuild`) + text-only backlog.
- Backlog `graph_facts` без вектора: **4 170 до и 4 170 через 45 с** — не разгружается.
- Rebuild-джоба: `paused_rate_limit`, `rate_limit:quota_group`, processed 9 797; `embedding_cache` не пополнялся (newest 22.10 00:15Z).
- **Что именно блокирует (не квота и не тикер):** identity-гейт поколений. Живой процесс считает новый fingerprint `2d0efab0e817` (host apinet), а поколения в реестре — `96f80838f683` (host Google). Лог 17:14:55Z: `embedding generation not serviceable | gen_fp=96f80838f683 new_fp=2d0efab0e817 — FTS-only (A06)`. Поэтому `_vec_write_allowed()` = False: новые факты сохраняются text-only, backfill пишет 0, retrieval — FTS. Дополнительно rebuild-джоба сама ждёт `next_allowed_at` старого поколения (00:05Z).
- Массовый backfill/перестройку не запускал (запрещено рамками лейна).

**Что осталось**
1. Перестройка индекса под identity apinet (`graph_facts_vec`/`smart_archive`, 15 819 пригодных фактов, backlog 4 170) — отдельная задача; до неё векторная память работает в FTS-only, хотя эмбеддинги уже считаются. Старую paused-джобу, привязанную к прежнему fingerprint, вероятно придётся пересоздать/перезапустить под новый fp — это вне данного лейна.
2. `EMBED-FALLBACK-FIX` (отдельный лейн): fallback-ключи по-прежнему уходят на apinet base_url и получат 401; специально не проверял и не чинил — ожидаемо до фикса.
3. Старые `exhausted`-строки можно не трогать: они инертны и истекают 2026-10-23T00:05Z.

healthz до/после — 200; рестартов нет (`NRestarts=0`); SSH в этом раунде — **1 коннект** (17:14:55Z), всего по лейну 6.



## Источник трафика apinet (chat)

Дата проверки: **2026-10-22T17:31:33Z** (один SSH-коннект, read-only; healthz до — 200).

**Вердикт: прод-трафика chat на apinet нет.** За доступный период журнала `admin_bot` (2026-10-18T05:15:32Z … 2026-10-22T17:31:49Z, 234 613 строк, журнал хранится ~4.5 дня, 185.3 MB) **ни одного упоминания `apinet`** — ни успешных вызовов, ни ошибок, ни ретраев.

**Effective chat-провайдер живого процесса** (совпадает в env, PG hot и `GET /api/config`):

| Что | Значение |
|---|---|
| `settings.LLM_BASE_URL` (env) | `https://nano-gpt.com/api/v1` |
| `models.llm_base_url` (PG hot + live) | `https://nano-gpt.com/api/v1` |
| `models.llm_model_name` | `deepseek/deepseek-v4.1-flash` |
| `settings.LLM_FALLBACK_BASE_URL` (env) / `models.llm_fallback_base_url` | `https://api.deepseek.com` |
| fallback-модель | `deepseek-flash` (env: `deepseek-v4-flash`) |
| `models.embedding_base_url` | `https://apinet.cloud/v1` — **только эмбеддинги** |

**Что в журнале за период (по строкам `LLM request OK | url=…`)**:

| Направление | Host | Кол-во |
|---|---|---|
| chat (все успешные, не `/embeddings`) | `nano-gpt.com` | **1 395** |
| embeddings | `generativelanguage.googleapis.com` | 40 |
| **apinet** | — | **0** |
| HTTP-ошибки | `nano-gpt.com` | 33 |

- Успешные chat-модели: `deepseek/deepseek-v4.1-flash` — 1 208 записей `LLM generate OK`.
- Chat-fallback: 30 попыток, провайдер `api.deepseek.com`; успешных fallback 28 (`deepseek-flash`).
- Телеметрия PG `llm_usage_events` за 7 дней (колонки host нет, только model/source): 2 707 записей; `deepseek/deepseek-v4.1-flash` (global) 2 567, `deepseek-flash` (global) 33, image 107. Никаких признаков второго chat-провайдера.
- Эмбеддинги бота после переключения на apinet (16:40Z) в журнале ещё не появлялись: векторная запись заблокирована identity-гейтом (см. раздел «Разблокировка 23.10»), поэтому у apinet со стороны бота пока **0 вызовов**, кроме одного admin-пробника 17:15Z (вне процесса `bot.py`).

**Планировщики / сторонние процессы (только чтение)**

- `crontab -l` (nik): одна задача — `tools/disk_retention.py` (пн 06:30), к apinet отношения нет.
- `/etc/cron.d`, `/etc/cron.daily`, `/etc/cron.hourly` — стандартные системные (e2scrub, sysstat, apt, logrotate, man-db, dpkg).
- systemd timers — только системные (apt, logrotate, sysstat, fwupd, man-db, motd и т.п.), ни один не про apinet.
- Процессы: `bot.py` (MainPID 516119), `fail2ban`, `unattended-upgrade-shutdown` и `headroom proxy` (`--openai-api-url https://api.deepseek.com` — тоже не apinet). Других python-процессов нет.
- Grep по коду на сервере: `apinet` встречается только в `config/settings.py` (дефолт `EMBEDDING_BASE_URL`) и комментариях `services/param_catalog.py`. Ни `tools/`, ни `history_import`, ни systemd-юниты apinet не используют.

**Почему владелец видит расход `deepseek-v4-flash` в консоли apinet** (факты vs гипотезы):
- Факт: этот сервер и процесс `admin_bot` chat-вызовов на apinet не делают; единственный apinet-ключ на сервере — `keys.embedding_api_key`, и приложение шлёт его только на `/embeddings` с моделью `gemini-embedding-001`.
- Гипотеза 1: тот же apinet-аккаунт/ключ используют другие инструменты владельца или агентов вне этого сервера — консоль apinet считает расход по аккаунту/ключу, а не по серверу.
- Гипотеза 2: расход был раньше 18.10 — журнал `admin_bot` за более старый период не сохранился (185 MB, ~4.5 дня), проверить нельзя.
- Как проверить точно: в консоли apinet посмотреть разбивку по ключам; если `deepseek-v4-flash` идёт под ключом, отличным от того, что лежит в `keys.embedding_api_key`, это не этот сервер.



## Находки

| ID | Severity | Область | Факт / риск |
|---|---|---|---|
| F1 | ~~blocker~~ **закрыто 23.10** | квоты | Parking старого аккаунта снят с пути сменой labels: `apinet_paid`/`google_free_*` = healthy; старые строки инертны (0 ключей), истекают 2026-10-23T00:05Z |
| F2 | **high** | dispatch/failover | `build_credential_pool()` отправляет fallback-ключи на **primary** base_url (apinet), а не на их Google-адреса. При сбое apinet Google-слоты не спасут: ключи получат 401 и будут помечены `auth_failed` в памяти до рестарта. Передано в лейн `EMBED-FALLBACK-FIX`, здесь не чинилось |
| F3 | **high (теперь главный)** | vec-индекс | Оба индекса в `building`/FTS-only с 29.09; rebuild `paused_rate_limit`, 9 797 построено. Живой new_fp `2d0efab0e817` (apinet) ≠ gen_fp `96f80838f683` (Google) → запись векторов и backfill заблокированы до перестройки под новую identity |
| F4 | low | данные | 4 170 пригодных фактов без вектора (oldest 02.10); 497 просроченных без вектора — не блокер, данные в `graph_facts` целы |
| F5 | info | провайдер | apinet не отдаёт rate-limit заголовки; лимиты и остаток баланса видны только в консоли apinet (риск `402`) |
| F6 | info | chat/apinet | Chat-трафик бота идёт на `nano-gpt.com` (fallback `api.deepseek.com`); в журнале `admin_bot` за 4.5 дня **0** упоминаний apinet. Расход `deepseek-v4-flash` в консоли apinet — вне этого сервера |

## Артефакты и доступ

- `plans/features/_audit-2026-10-23/embed-provider/report.md` (этот файл)
- `raw/main.txt` — identity/env/config/pool/quota/index/journal (16:52:56Z)
- `raw/probe.txt` — control-plane probe + прямой вызов apinet (16:55:24Z)
- `raw/fbprobe.txt` — проверка двух Google-ключей (16:56:49Z)
- `raw/sql.txt` — SQLite-срез, throughput (16:58:05Z)
- `raw/sql2.txt` — vec0-подсчёты, backlog по чатам (17:00:37Z)
- `raw/apply.txt` — применение labels, до/после квот, probe, очередь (17:14:55Z)
- `raw/chat_audit.txt` — chat-трафик/apinet, журнал, планировщики, процессы (17:31:33Z)
- `probe.py` — воспроизводимый скрипт (main/probe/fbprobe/sql/sql2)
- SSH: **7 последовательных коннектов** по лейну (интервалы ≥76 с, один логин, без ретраев и параллельных сессий); последний — chat/apinet-аудит (17:31:33Z). Банов нет.
