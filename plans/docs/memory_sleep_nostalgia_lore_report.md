# Память, «сон», ностальгия и лор чатов: как всё это работает сегодня

**Назначение отчёта.** Это подробный разбор того, как в проекте `adminbot` реально
устроены память, синтез воспоминаний («сон»), ностальгия, лор чатов и сборка
контекста. Отчёт написан по коду, а не по задумкам: я прошёл по модулям
`services/`, `config/settings.py`, `handlers/`, `web/api/`, схеме БД и рабочим
таймерам. Где приведены конкретные числа — рядом указано имя параметра, чтобы
можно было найти его в админке/каталоге (`services/param_catalog.py`).

**Важная оговорка про «сегодня».** Код и дефолты я смотрел на текущем состоянии
репозитория. Фактические значения на проде могут быть переопределены владельцем
через TMA/PostgreSQL (таблица `bot_settings` и per-chat `chat_params`). Ниже я
отдельно привожу срез прод-значений из `plans/docs/prod-params-audit-2026-09.md`
(аудит от 06.09.2026) — он показывает, что реально включено, потому что часть
«тяжёлых» фич по коду выключена по умолчанию, а на проде включена.

---

## 1. Общая картина: из чего состоит «память»

У бота есть **два разных хранилища**, и это важно не путать:

1. **Локальная база SQLite** (`local_database.db`) — «сырая память»: сообщения
   чатов, факты, граф, вектора, состояние воркеров. Именно её называют памятью.
   Работает через `services/database.py` (`DatabaseService`).
2. **PostgreSQL** — «настройки и метаданные»: параметры (`bot_settings`),
   профили чатов (`chat_profiles`: ручной и авто-лор, тумблеры, отношения,
   гейты), дневные бюджеты фоновых воркеров (`worker_budget`). Работает через
   `services/pg_db.py` и связанные сервисы.

Логически память разделена на **три уровня** (`services/summary_memory.py`,
`MemoryManager`):

- **L1 — «рабочее окно»**. Свежие сообщения за последние
  `limits.summary_window_hours` часов (дефолт 6 ч). Одно SQL-обращение
  (`get_window_messages`). Это то, что бот держит «перед глазами» при сборке
  ответа и при саммари.
- **L2 — «сырьё»**. Те же сообщения, но в полной таблице `smart_messages`;
  хранятся `limits.full_memory_retention_days` дней (дефолт 30). По ним есть
  полнотекстовый поиск FTS5 (`search_long_term`) — без дополнительных вызовов
  нейросети.
- **L3 — «архив»**. Когда сообщение старше 30 дней, оно **сжимается** нейросетью
  в короткие факты (`smart_archive_facts`, хранятся
  `limits.archive_memory_retention_days` дней, дефолт 90) и получает вектор для
  смыслового поиска (`vector_search`, sqlite-vec). Сырьё после сжатия удаляется
  — так база не растёт бесконечно.

Поверх этого работает **GraphRAG v2** — отдельная долговременная память в виде
фактов (`graph_facts`) и связей-триплетов (`nodes`/`edges`). Именно оттуда бот
достаёт «что известно по теме», когда человек пишет в чат.

Плюс есть **краткие конспекты чата** (running summary), которые не дают окну
L1 «раздуться»: когда сообщений в окне накапливается слишком много, старая часть
пересказывается, а свежий хвост остаётся дословно.

Проще говоря: L1 — «что вижу сейчас», L2 — «что было в последний месяц, ищу
поиском», L3 — «что было давно, сжатое и находимое по смыслу», граф — «что бот
уже знает и как это связано», конспекты — «сжатая летопись окна».

---

## 2. Что сохраняется и куда

**Все сообщения чатов.** В `bot.py` первым роутером стоит
`summary_observer_router` (`handlers/summary.py`, `summary_observer`). Он
срабатывает на каждое сообщение и **всегда возвращает UNHANDLED** — то есть
только сохраняет, ничего не отвечает. Записываются: автор (`user_id`,
`author_name`), текст, `chat_id`, `reply_to_id`, время, тип медиа, признаки
форварда и `tg_message_id`. Служебные события (вход/пин) и команда `/summary` в
память не пишутся; сообщения **самого бота тоже не пишутся** — их ловит мёртвая
зона. Это ключевой факт: ностальгия и лор считают «жизнью чата» именно
пользовательские сообщения.

**Транскрипты.** Голосовые и видео сначала сохраняются как медиа-заглушка, а
после распознавания текст подменяется в той же строке
(`update_smart_message_text`) — чтобы память видела реальную речь.

**Ответы бота.** Хранятся отдельно, в таблице `bot_replies` (и `bot_reply_parents`
для цепочек). Они не попадают в «сырьё» памяти, но используются для стилевых
якорей и восстановления диалоговых цепочек.

**Факты.** `memorize_facts()` (`services/summary_memory.py`) прогоняет текст через
промпт-экстрактор `FACT_EXTRACT_PROMPT` (канон R46-2), получает триплеты
«субъект — предикат — объект» и пишет их в `nodes`/`edges`
(сущности и связи), а также сохраняет человекочитаемую строку предложения в
`graph_facts` (с осью `origin`, весом, важностью, сроком годности). При наличии
sqlite-vec к каждому факту пишется вектор в `graph_facts_vec`.

**Вектора и их кэш.** Эмбеддинги считает модель
`models.embedding_model_name` (на проде `gemini-embedding-001`, размерность
`models.embedding_dim=3072`). Есть кэш эмбеддингов `embedding_cache` (ключ
SHA-256 от нормализованного текста, TTL `limits.embed_cache_ttl_days=30` дней,
потолок `limits.embed_cache_max_rows=20000` строк, хранение во float16 — экономия
места). Если основной провайдер эмбеддингов недоступен, работает каскад
фоллбэков (Google AI Studio, два ключа).

---

## 3. Долговременная память: факты, граф, поиск (подробно)

### 3.1. Откуда берутся факты

Факты рождаются из нескольких источников (`origin`):

- **`chat_history`** — из переписки. Это основа долговременной памяти.
- **`bot_direct_reply`** — из личных диалогов с ботом (запрос + ответ).
- **`search_fact`**, **`youtube_content`**, **`web_content`** — из пересказов
  поиска, видео и статей (то, что бот «узнал» по заказу пользователя).
- **`voice_transcript`**, **`video_transcript`** — из расшифровок.
- **`user_memory`** — по команде «запомни» (см. ниже).
- **`history_import`** — из импортированной истории (фаза 2).
- **`derived_belief`** — это уже «убеждения», продукт «сна» (раздел 4).

У каждого источника свой **стартовый вес** (`_origin_weight`): `chat_history` —
0,5; `bot_direct_reply` — `limits.graph_fact_weight_direct` (0,7); архивные
источники (поиск/видео/статьи) — `limits.graph_fact_weight_archive` (0,4);
`user_memory` — 1,0 (максимум). Вес влияет и на срок годности: чем важнее, тем
дольше живёт.

### 3.2. Дедупликация и «антиотравление»

Перед записью факт проверяется на дубли (Epic 60, флаг
`flags.graph_dedup_enabled`):

- **Точный дубль** (та же тройка слов) → ничего не пишем, но **подтверждаем**
  старый факт: вес растёт на `limits.graph_dedup_weight_bonus` (0,1), но не выше
  1,0.
- **Смысловой дубль** (косинус ≥ `limits.graph_dedup_similarity_high` = 0,95) →
  тоже подтверждение (noop).
- **Похоже, но изменилось** (косинус в диапазоне
  `[limits.graph_dedup_similarity_low`=0,85; 0,95)) → **supersede**: старый факт
  инвалидируется (помечается, что его заменил новый), новый пишется как
  «неподтверждённый». Пишется журнал «что во что превратилось»
  (`graph_fact_compressions`).
- **Совсем новое** (< 0,85) → обычное добавление.

Защищённые факты (`protected_facts`) дедуп не трогает вообще — ни подтверждает,
ни инвалидирует.

### 3.3. Веса, затухание и сроки жизни

- **Time-decay**: эффективный вес при чтении = вес × 0.5^(дней / half-life), где
  half-life = `limits.graph_time_decay_half_life_days` (60 дней), но не ниже
  `limits.graph_time_decay_floor` (0,1). То есть старые факты постепенно «тускнеют»
  в ранжировании, но не удаляются. Выключатель — `flags.graph_time_decay_enabled`.
- **TTL**: `chat_history` живёт вечно (`expires_at = NULL`); `bot_direct_reply`
  — `limits.chat_direct_reply_ttl_days` (30) × (0,5 + вес) ≈ 36 дней; архивные
  источники — `limits.graph_fact_ttl_days` (14) × (0,5 + вес) ≈ 13–17 дней;
  `user_memory` — по `limits.memory_commands_remember_ttl_days` (365 дней, 0 =
  вечно); убеждения — вечно.
- **Продление при упоминании** (`flags.graph_fact_touch_enabled`): если факт
  «вытащили» из памяти в ответ, его срок продлевается на
  `limits.graph_fact_touch_extend_days` (7 дней), но не более чем до
  `created_at + 2 ×` базовый TTL. Так востребованные факты живут дольше.
- **Квота на человека** (`flags.graph_user_quota_enabled`,
  `limits.graph_facts_per_user_quota` = 50): у каждого не больше 50 «личных»
  фактов; сверх этого вытесняется самый лёгкий и старый (оценка
  вес / (возраст+1)).

### 3.4. Как бот ищет по памяти

Смысловой поиск (`_search_graph_facts`) — гибридный:

1. **Векторный KNN** по `graph_facts_vec`: сначала грубый поиск по сжатым
   int8-векторам (`flags.vec_int8_enabled`), затем **реранг** точной косинусной
   близостью по обычным векторам. Это ускоряет поиск без потери качества.
2. **MMR-разнообразие** (`flags.graph_mmr_enabled`, λ=`limits.graph_mmr_lambda`
   = 0,6, просмотр `limits.graph_mmr_fetch_k` = 20 кандидатов): чтобы в выдачу не
   попали 10 почти одинаковых фактов.
3. **FTS-фолбэк**: если вектора недоступны или KNN пуст — текстовый поиск
   SQLite FTS5, результаты пересортировываются по эффективному весу.
4. Факты фильтруются по сроку годности и по чату; `bot_direct_reply` по умолчанию
   не подмешивается в чужие сценарии (только в личный диалог).

На выходе — не больше `limits.graph_rag_facts_limit` фактов (дефолт 10), и
готовый контекст не длиннее `limits.graph_rag_context_max_chars` символов
(2000).

### 3.5. Команды «запомни» и «забудь»

Если функция включена (`flags.memory_commands_user_enabled`; на проде выключена —
значит, команда доступна только админу/модератору), пользователь может явно
попросить запомнить факт. Такой факт пишется **дословно**, без экстракции, с
максимальным весом 1,0 и origin `user_memory`. Повторный тот же текст не
дублируется. «Забудь» и `/clear` работают всегда — на них ограничение
бессрочного хранения не распространяется.

### 3.6. Сжатие (L3) и обслуживание базы

- **Сжатие сырья** идёт по крону **4 раза в сутки**: 00:00, 06:00, 12:00, 18:00
  по `limits.summary_timezone` (прод: `Asia/Yekaterinburg`) — это
  `services/summary_scheduler.py`. Сначала вызывается `compress_and_purge`,
  потом генерируется само саммари. Пачки по
  `limits.summary_compress_batch` (100) сообщений сжимаются промптом
  `COMPRESS_PROMPT` в максимум 10 строк-фактов, по ним дополнительно строится
  граф (`EXTRACT_PROMPT`), затем сырьё удаляется.
- **Слияние повторяющихся эпизодов** (`flags.graph_episode_merge_enabled`):
  раз в `limits.graph_episode_merge_interval_days` (7 дней), до
  `limits.graph_episode_merge_batch` (20) кластеров за прогон, в кластере не
  больше `limits.graph_episode_merge_max_facts_per_cluster` (5) фактов.
- **Пересмотр** (`flags.graph_review_enabled`): раз в
  `limits.graph_review_interval_days` (3 дня) — склейка дублей по векторам,
  удаление просроченных и «неподтверждённых» фактов (старше
  `limits.graph_unconfirmed_retention_days` = 14 дней), чистка лога сжатий
  (`limits.graph_compression_log_retention_days` = 90 дней).
- **WAL-checkpoint** (`flags.db_wal_checkpoint_enabled`) каждые
  `limits.db_wal_checkpoint_hours` (6 ч) — чтобы WAL-журнал SQLite не разрастался.
- **Бэкап памяти** (`flags.memory_backup_enabled`): ежедневно в
  `limits.memory_backup_hour` (05:00) делается `VACUUM INTO` копия БД и
  текстовый экспорт фактов (`facts_*.txt`); хранится
  `limits.memory_backup_keep` файлов (прод: 7, код-дефолт 1).

### 3.7. Бессрочное хранение (важная особенность прода)

Тумблер `memory.infinite_retention` (дефолт `false`) отключает удаление и сжатие
по срокам: сырьё и архивные факты живут вечно, а старые сообщения не архивируются,
а только прогоняются через экстрактор графа. Это сделано для импорта истории.
**На проде этот тумблер включён (`true`)** — значит, физической чистки TTL сейчас
нет, но «протухшие» факты всё равно не выдаются в ответы, потому что фильтр по
`expires_at` остаётся на чтении. Исключение — команды «забудь», они работают
всегда.

---

## 4. «Сон»: синтез убеждений (DreamWorker)

**Идея.** Когда одни и те же мысли встречаются в чате снова и снова, из них
можно вывести устойчивое «убеждение». Этим занимается фоновый воркер
`services/dream_worker.py` (`DreamWorker`). Он не создаёт шум из единичных
сообщений, а обобщает повторяющееся.

### 4.1. Когда он просыпается

- Воркер ставит тик каждые `memory.dream_tick_minutes` минут (60) — но только
  если включён `memory.dream_enabled` (код-дефолт `false`; **на проде включён**).
- **Сам «сон» (трата денег на нейросеть) возможен только в окне**
  `[memory.dream_window_start_hour` (4); `memory.dream_window_end_hour` (6))
  по местному времени `limits.summary_timezone` (`Asia/Yekaterinburg`). Вне окна
  воркер может бесплатно подобрать кандидатов и кластеры, но дистилляцию
  откладывает (`status='window_skip'`) и «водяной знак» не двигает.
- Периодичность тика имеет случайный разброс (jitter) до ⅓ интервала, если
  задан `limits.worker_budget_jitter_minutes`.
- Первый «сон» нового чата (без отметки) смотрит факты за
  `memory.dream_initial_window_hours` (168 ч = неделя), чтобы импорт истории не
  захлебнул первый прогон.
- Есть **ручной запуск** через API (`POST /api/memory/dream/run`): окно 4–6 он
  игнорирует, но бюджеты соблюдает.

### 4.2. Что он обрабатывает

1. **Чаты-кандидаты**: только там, где появилось не меньше
   `memory.dream_min_new_facts_per_chat` (5) новых фактов; за один тик не больше
   `memory.dream_max_chats_per_run` (10), отбираются топ по количеству новинок.
   «Не пик»: если в чате писали последние `memory.dream_quiet_check_minutes`
   (30) минут, он пропускается.
2. **Кандидаты-факты**: только живые, подтверждённые (`status='confirmed'`) и
   только «жизненные» источники: `chat_history`, `history_import`,
   `bot_direct_reply`, `user_memory`. Производные (поиск/видео/статьи) и сами
   убеждения не передистиллируются — чтобы не было рекурсии. Факты, попавшие в
   `protected_facts`, исключаются.
3. **Кластеризация без нейросети**: факты группируются по значимым словам
   (длина ≥ 5) и именам участников; в кластер нужно не меньше
   `memory.dream_cluster_overlap_tokens` (2) общих слов.
4. **Порог на дистилляцию**: в «сон» идёт кластер, где не меньше
   `memory.dream_repeat_threshold` (3) членов **и** сумма важностей не меньше
   `memory.dream_importance_sum_threshold` (12). За тик — максимум
   `memory.dream_max_clusters_per_run` (5) лучших кластеров.

### 4.3. Что получается на выходе

На каждый кластер — **один вызов нейросети** (`DREAM_DISTILL_PROMPT`), который
возвращает до 2 убеждений в формате JSON; каждое убеждение обязано опираться
минимум на 2 реальных факта из кластера (защита от галлюцинаций — иначе запись
отбрасывается). Убеждение сохраняется в `graph_facts` с:

- `origin='derived_belief'`, `kind='belief'`, срок — вечный;
- вес 0,6; важность = min(10, сумма важностей источников);
- список id фактов-источников и метаданные (`confidence`, число источников,
  время синтеза, id кластера).

Если новое убеждение похоже на старое того же чата (общий «якорный» токен темы),
старое **не удаляется**, а помечается ссылкой «заменён новым» (supersede).
Убеждения затем участвуют в обычном поиске по памяти и в ответах помечаются
как `[убеждение]`.

### 4.4. Лимиты «сна» (деньги)

- `memory.dream_distillations_per_day` (30) — максимум успешных синтезов в сутки.
- `memory.dream_tokens_per_day` (60000) — суточный запас «слов» на синтез
  (оценка len/4).
- При приближении к пределу (меньше 5 синтезов или 5000 токенов) тик завершается
  досрочно.
- Дополнительно работает общий дневной бюджет фоновых воркеров: глобально
  `limits.worker_daily_llm_calls_global` (200 вызовов) и
  `limits.worker_daily_llm_tokens_global` (500 000), на чат —
  `limits.worker_daily_llm_calls_per_chat` (35) и
  `limits.worker_daily_llm_tokens_per_chat` (100 000). При исчерпании глобального
  бюджета первым «падает» именно dream, потом lore, последней — ностальгия
  (`limits.worker_priority_order` = `nostalgia,lore,dream`).

### 4.5. Где это видно

- Аудит — таблица `memory_dream_log` (успех/пропуск/ошибка/окно, сколько токенов).
- API: `GET /api/memory/dream/beliefs`, `GET /api/memory/dream/log`,
  `DELETE /api/memory/dream/beliefs/{id}` (мягкое удаление),
  `POST /api/memory/dream/beliefs/{id}/protect` (сделать защищённым).
- Убеждения сами подмешиваются в контекст как обычные факты памяти.

---

## 5. Ностальгия

**Идея.** В тихой группе бот может сам «вспомнить» старое и написать одну-две
фразы в стиле «кстати…». Это тёплый проактивный штрих, а не ответ на запрос.
Есть два слоя:

- **Слой A** — «маркер при ответе». Если в памяти нашёлся «золотой» факт по теме
  текущего сообщения, бот получает подсказку вплести его в ответ. Дополнительных
  вызовов нейросети нет.
- **Слой B** — фоновый `NostalgiaWorker` (`services/nostalgia_worker.py`),
  который сам пишет в затихшую группу.

### 5.1. Слой B: когда и как

- Тик — каждые `memory.nostalgia_tick_minutes` (60) минут, только для **групп**
  (`chat_id < 0`) и только для активных профилей из PG. Если
  `memory.nostalgia_enabled` выключен (код-дефолт `false`; **на проде включён**),
  тик не ставится. Ручной запуск тоже уважает глобальный рубильник и
  per-chat гейт.
- **Дешёвые гейты** (просто пропускают чат без записей в лог):
  1. тишина: последнее пользовательское сообщение старше
     `memory.nostalgia_min_silence_minutes` (45) минут;
  2. «тихие часы»: местное время в `[23; 8)` (`nostalgia_quiet_start_hour` = 23,
     `nostalgia_quiet_end_hour` = 8);
  3. пауза между отправками: не меньше `memory.nostalgia_cooldown_hours` (12)
     часов с прошлой отправки;
  4. дневной лимит: не больше `memory.nostalgia_max_per_day` (3) отправок за
     местные сутки;
  5. анти-спам: если подряд `memory.nostalgia_unanswered_max` (2) проактивных
     сообщения остались без ответа, чат замолкает, пока не пройдёт
     `memory.nostalgia_pause_hours` (24 ч) или человек не ответит.
- **Кандидаты**:
  - «год назад в этот день» — сообщения чата в окне «ровно год назад ±
    `memory.nostalgia_year_back_days_window` (2) дня», до 3 строк; вес 0,7;
  - «золотые» факты по теме последних 5 сообщений: возраст ≥
    `memory.nostalgia_golden_min_days` (60) дней, важность ≥
    `memory.nostalgia_golden_min_importance` (5); вес 0,3 + 0,05 × важность.
- **Порог срабатывания** = 0,3 + `memory.nostalgia_aggressiveness` × 0,5. При
  дефолтной агрессивности 0,3 порог равен 0,45. Агрессивность влияет только на
  «насколько слабый повод сработает», частота ограничена лимитами выше.
- Если кандидат прошёл порог — **один вызов нейросети** (`NOSTALGIA_PROMPT`).
  Ответ «UNCHANGED» или пустой = не отправляем и дневной лимит не тратим.
  Готовый текст обрезается до `memory.nostalgia_max_send_chars` (400) символов и
  отправляется обычным сообщением.
- Все исходы пишутся в `nostalgia_log` (kind: `year_back`/`golden`/`none`,
  status: `sent`/`skipped`/`error`).

### 5.2. Слой A: маркер в контексте

При сборке ответа в личном чате бот ищет «золотой» факт по тексту запроса
(`fetch_golden_facts`). Если найден и его ещё нет в блоке RAG — формируется
короткая подсказка (не больше `memory.nostalgia_layer_a_max_hints` = 1 штуки,
длиной до `memory.nostalgia_hint_max_chars` = 300 символов), которая вставляется
в контекст как отдельный блок `nostalgia`. Слой A работает только в группах и при
включённом `memory.nostalgia_layer_a_enabled` (на проде включён).

---

## 6. Лор чатов

**Идея.** Лор — это короткая «легенда» конфы/чата, которую бот держит в голове,
чтобы понимать контекст и людей: откуда чат, кто в нём, какие внутренние шутки и
события. Он может быть **ручным** (написал админ) и **авто** (бот сам
обновляет по свежей переписке).

### 6.1. Где живёт

В PostgreSQL, таблица `chat_profiles` (`services/chat_lore_store.py`,
`services/lore_cache.py`). У профиля есть:

- `manual_lore` — ручной текст;
- `auto_lore` — автотекст;
- `auto_enabled` (по умолчанию `true`) — разрешена ли авто-генерация;
- `auto_period_hours` (по умолчанию 24) — как часто генерировать;
- `auto_window_hours` (по умолчанию 24) — за какой период брать сообщения;
- `is_active` (по умолчанию `true`) — участвует ли чат в обработке;
- `last_auto_at` — когда последний раз успешно прогонялись;
- `relations`, `relations_enabled` — ручные стадии отношений и тумблер их инжекта.

Чтение — через RAM-кэш `ChatLoreCache` с TTL 120 секунд и инвалидацией по
`pg_notify('lore_updated')`.

### 6.2. Авто-лор: пайплайн

Воркер `services/lore_worker.py`:

- Тик — каждые `limits.lore_tick_minutes` (30) минут, при включённом
  `flags.lore_worker_enabled` (дефолт `true`; на проде `true`).
- Обходит только активные профили (список `list_active_chats` отбирает ещё и
  `auto_enabled=true`); лички в список не попадают.
- Для чата: проверяет, что профиль активен, `auto_enabled`, глобальный
  `flags.lore_auto_enabled` (дефолт `true`) и per-chat гейт `lore_auto`; что
  прошёл период (`last_auto_at + auto_period_hours`) и что не идёт другой прогон
  (блокировка `pg_advisory_lock`).
- **Окно**: берутся «осмысленные» сообщения — текст непустой, длина не меньше
  `limits.lore_min_message_chars` (20) символов, не начинается с `/`, не от бота.
  Если таких меньше `limits.lore_min_messages` (15) — «тихое окно», пропуск без
  траты токенов. Само окно — до `limits.lore_window_max_messages` (300) сообщений
  и не длиннее `limits.lore_window_max_chars` (20000) символов. Строки
  оформляются как `[ГГГГ-ММ-ДД ЧЧ:ММ] автор: текст`.
- **Контекст**: если авто-лор уже есть — режим MERGE (текущий лор + новое окно +
  чат-уровневые защищённые факты), если нет — INIT. Нейросеть получает лимит
  `limits.lore_max_words` (150 слов) и возвращает либо новую версию лора, либо
  `UNCHANGED`.
- **Запись**: изменение → `auto_lore` обновляется, в историю
  (`chat_lore_history`, field=`auto`) пишется строка; `UNCHANGED` →
  просто отметка времени. Ошибка/пустой ответ профиль не портит.

### 6.3. Ручной лор и инжект

- Ручной текст задаётся через TMA/API (кнопка ручной правки), хранится в
  `manual_lore`; изменение идёт в историю (`field='manual'`).
- При сборке контекста блок `<chat_lore>` собирается так: сначала ручной текст,
  затем разделитель `---`, затем автотекст. Общий блок не длиннее
  `limits.lore_inject_max_chars` (прод/дефолт 3000 символов); при обрезке в
  первую очередь режется автотекст, маркер `…[обрезано]`.
- Инжект включается `flags.lore_inject_enabled` (дефолт `true`; на проде `true`).
  Если PG-лор активен, легаси-канал чат-уровня в `protected_facts` не
  дублируется.
- Есть и «зашитый» лор конкретной конфы (чат `-1002661910336`) — константа в
  `services/chat_lore.py`, которая при старте идемпотентно кладётся и в
  `protected_facts`, и в `graph_facts` как `user_memory`.

### 6.4. Opt-in и гейты

Есть двухслойная система «гейтов» (`services/feature_gates.py`):

- колонка `chat_profiles.gates_opt_in` — чат вообще участвует в «тяжёлых» фичах;
- `chat_params.gates` — конкретно `dream`, `nostalgia`, `lore_auto`, `permsoc`.

Резолв: явный per-chat гейт → глобальный флаг
(`flags.lore_auto_enabled`/`memory.dream_enabled`/`memory.nostalgia_enabled`) →
`false`. Для новых чатов при создании профиля гейты проставляются выключенными —
это безопасный opt-in. При первом включении тяжёлой фичи `gates_opt_in`
переключается в `true` автоматически.

Дополнительно в раунде 10.10 введена изоляция личек: при создании DM-профиля
`ensure_scope_profile(dm=True)` кладёт `gates.dream=false`,
`gates.nostalgia=false` и override-выключатели
`memory.dream_enabled`/`memory.nostalgia_enabled`/`flags.summary_enabled`/
`flags.chat_running_summary_enabled`. То есть **в личке «сон», ностальгия и
периодическое саммари по умолчанию выключены**.

---

## 7. Отношения (A-Life) — рядом с памятью

Хотя это отдельная механика, она участвует в контексте и тесно связана с
«памятью о людях».

- В SQLite `users_meta` считается «стадия» участника: `stranger` → «нюфаг»,
  `acquaintance` → «знакомый», `regular` → «свой», `veteran` → «ветеран».
  Пороги — конъюнкция сообщений и дней:
  `limits.relations_acquaintance_min_msg` (10) и
  `..._min_days` (7); `regular` — 200/90; `veteran` — 1000/365.
- Активность затухает: вес сообщения = 0,5^(дней /
  `limits.relations_decay_half_life_days`, 14).
- Понижение стадии не мгновенное: держится при отсутствии дольше
  `limits.relations_hold_absent_days` (60), меняется не чаще
  `limits.relations_stage_change_min_days` (30) и только если за 30 дней меньше
  `limits.relations_downgrade_msg_30d` (10) сообщений. Максимум на одну ступень.
- Инжект в контекст — блок `<user_relations>` о собеседнике: имя, стадия, с какого
  месяца в чате, сколько сообщений за 30 дней, пометка админа. Кап —
  `limits.relations_inject_max_chars` (600).
- **Тон по стадиям** включается `flags.relations_tone_enabled` (код-дефолт
  `false`; **на проде `false`**) плюс per-chat `relations_enabled`. То есть
  механика считается, но сегодня на прод-тон не влияет — блок не добавляется.

---

## 8. Инструмент `dig_into_lore` («копание»)

Отдельный инструмент, доступный модели в личном чате (`services/tool_router.py`).
Нужен, когда человек вспоминает: «помнишь», «как мы тогда», «в 2024», «что было
с (имя)». Он делает FTS-поиск по старым сообщениям и фактам графа, умеет
фильтровать по году/периоду и по человеку, подтягивает связанные имена через
обход графа. Лимиты: `limits.dig_max_snippets`, `limits.dig_max_facts`,
`limits.dig_max_symbols`, `limits.dig_graph_hop_depth`,
`limits.dig_year_back_window_days` (дефолты 8/3/3500/2/2; прод:
15/5/5000/2/2). Рубильник — `flags.dig_enabled` (дефолт `true`).

Есть ещё **пре-гейт** `flags.dig_pre_gate_enabled` (дефолт `false`; на проде
`true`): если в сообщении есть маркеры ностальгии, бот **принудительно** вызывает
`dig_into_lore` ещё до генерации и кладёт результат в блок `<dig_result>` перед
`<Target_User>`. Системный промпт также инструктирует модель вызывать
`dig_into_lore` при подобных вопросах.

---

## 9. Тайминги и лимиты: сводка

### 9.1. Расписания воркеров

| Что | Когда | Параметр |
|---|---|---|
| Сжатие L3 + саммари | 00:00/06:00/12:00/18:00 local | cron в `summary_scheduler.py` |
| Сон (дистилляция) | тик 60 мин, реальная работа 04:00–06:00 local | `memory.dream_tick_minutes`, окно `4–6` |
| Ностальгия | тик 60 мин, только группы | `memory.nostalgia_tick_minutes` |
| Лор чатов | тик 30 мин | `limits.lore_tick_minutes` |
| Слияние эпизодов графа | раз в 7 дней | `limits.graph_episode_merge_interval_days` |
| Пересмотр графа | раз в 3 дня | `limits.graph_review_interval_days` |
| WAL-checkpoint | каждые 6 ч | `limits.db_wal_checkpoint_hours` |
| Бэкап памяти | ежедневно 05:00 | `limits.memory_backup_hour` |

### 9.2. Память/RAG

- Окно L1: `limits.summary_window_hours` = 6 ч.
- Сырьё L2: `limits.full_memory_retention_days` = 30 дней.
- Архив L3: `limits.archive_memory_retention_days` = 90 дней.
- Пачка сжатия: `limits.summary_compress_batch` = 100 сообщений; ≤10 фактов.
- RAG-фактов: `limits.graph_rag_facts_limit` = 10; контекст:
  `limits.graph_rag_context_max_chars` = 2000.
- TTL фактов: `limits.graph_fact_ttl_days` = 14; `bot_direct_reply`:
  `limits.chat_direct_reply_ttl_days` = 30; «запомни»:
  `limits.memory_commands_remember_ttl_days` = 365.
- Веса: `limits.graph_fact_weight_direct` = 0,7;
  `limits.graph_fact_weight_archive` = 0,4; `chat_history` = 0,5;
  `user_memory` = 1,0.
- Дедуп: HIGH `limits.graph_dedup_similarity_high` = 0,95; LOW `..._low` = 0,85;
  бонус `limits.graph_dedup_weight_bonus` = 0,1.
- Затухание: half-life `limits.graph_time_decay_half_life_days` = 60; пол
  `limits.graph_time_decay_floor` = 0,1.
- Продление: `limits.graph_fact_touch_extend_days` = 7.
- Квота: `limits.graph_facts_per_user_quota` = 50.
- MMR: `limits.graph_mmr_lambda` = 0,6; `limits.graph_mmr_fetch_k` = 20.
- Кэш эмбеддингов: TTL `limits.embed_cache_ttl_days` = 30; строк
  `limits.embed_cache_max_rows` = 20000.
- Бэкап: `limits.memory_backup_keep` = 1 (прод 7).

### 9.3. Сон

- `memory.dream_min_new_facts_per_chat` = 5; `dream_max_chats_per_run` = 10;
  `dream_quiet_check_minutes` = 30.
- Кластер: `dream_cluster_overlap_tokens` = 2; `dream_repeat_threshold` = 3;
  `dream_importance_sum_threshold` = 12; `dream_max_clusters_per_run` = 5.
- Бюджеты: `dream_distillations_per_day` = 30; `dream_tokens_per_day` = 60000.
- Прогрев: `dream_initial_window_hours` = 168.
- Воркер-бюджеты: см. 9.5.

### 9.4. Ностальгия

- Тик `nostalgia_tick_minutes` = 60; тишина `nostalgia_min_silence_minutes` = 45;
  тихие часы 23–8; пауза `nostalgia_cooldown_hours` = 12; дневной лимит
  `nostalgia_max_per_day` = 3; стоп после `nostalgia_unanswered_max` = 2
  неотвеченных; окно паузы `nostalgia_pause_hours` = 24.
- «Золотые»: возраст `nostalgia_golden_min_days` = 60; важность
  `nostalgia_golden_min_importance` = 5.
- Слои A: хинтов `nostalgia_layer_a_max_hints` = 1, длина
  `nostalgia_hint_max_chars` = 300.
- Порог: 0,3 + `nostalgia_aggressiveness` × 0,5 (дефолт 0,3 → 0,45).
- Прочее: окно «год назад ±» `nostalgia_year_back_days_window` = 2; длина
  сообщения `nostalgia_max_send_chars` = 400.

### 9.5. Суточный бюджет фоновых воркеров (общий)

- Глобально: `limits.worker_daily_llm_calls_global` = 200;
  `limits.worker_daily_llm_tokens_global` = 500000.
- На чат: `limits.worker_daily_llm_calls_per_chat` = 35;
  `limits.worker_daily_llm_tokens_per_chat` = 100000.
- Порядок деградации: `limits.worker_priority_order` = `nostalgia,lore,dream`
  (первым падает dream). Разброс тиков: `limits.worker_budget_jitter_minutes` = 5.

### 9.6. Лор

- `limits.lore_min_messages` = 15; `limits.lore_min_message_chars` = 20;
  `limits.lore_window_max_messages` = 300; `limits.lore_window_max_chars` = 20000;
  `limits.lore_max_words` = 150; `limits.lore_inject_max_chars` = 3000;
  `limits.lore_generate_cooldown` = 60 (сек, in-memory).
- Период/окно профиля чата — 24 ч и 24 ч по умолчанию.

---

## 10. Сборка контекста: как всё это попадает в промпт

### 10.1. Личный диалог (самое важное)

Перед ответом `DirectChatService._build_user_content`
(`services/direct_chat_service.py`) собирает блоки в строгом порядке — сначала
«фон», а самое важное ближе к концу («важное к концу» лучше удерживается
моделью):

1. `map` — `<UserResolutionMap>`: кто есть кто (имя — user_id) по активным
   участникам за `limits.chat_map_participants_hours` (24 ч), не больше
   `limits.chat_map_participants_cap` (150).
2. `branch` — `<Conversation_Branch>`: краткий итог reply-ветки (если это ответ
   на сообщение), последние `limits.chat_branch_context_hops` (3) хода.
3. `rag` — `<RAG_Memory>`: факты памяти по теме текущего сообщения.
4. `global` — `<Global_Context>`: конспект чата + дословный свежий хвост (или
   последние `limits.chat_global_context_limit` сообщений, если конспекта нет).
5. `thread` — `<Conversation_Thread>`: цепочка ответов вглубь до
   `limits.chat_thread_max_depth` (6).
6. `target` — `<Target_User>`: к кому обращаемся (имя + uid).
7. `relations` — `<user_relations>` о собеседнике (если включено; на проде
   выключено).
8. `protected` — `<protected_facts>`: важные факты, которые нельзя размазывать
   при сжатии (карточки-слоты, чат-лор).
9. `lore` — `<chat_lore>`: ручной + авто-лор чата.
10. `nostalgia` — подсказка слоя A.
11. `mood` — `<mood>`: эвристика тона по словам.
12. `current` — `<Current_Question>`: текущее сообщение (обрезанное до
    `limits.chat_current_question_max_chars` = 800).
13. `anchors` — `<style_anchors>`: последние ответы бота для интонации.
14. `sandwich` — короткое напоминание в конец.

**RAG-блок** строится двухпроходно: сначала считается `global`, потом по нему
отсеиваются факты, которые уже упомянуты в фоне (`dedup_rag_vs_global`, порог
`limits.chat_rag_dedup_overlap_ratio` = 0,8). Затем — при включённом
`flags.chat_rag_rerank_enabled` (**на проде `true`**) — лишние кандидаты
отфильтровываются ещё одним вызовом нейросети. Факты рендерятся с метками
источника: `[чат]`, `[личный диалог]`, `[поиск]`, `[видео]`, `[статья]`,
`[запомнено]`, `[убеждение]` и датой.

**Бюджеты контекста** (`_apply_context_budget`). Общий бюджет —
`limits.chat_context_budget_tokens` (код-дефолт 4000; **на проде 24000**). Из
него вычитаются «неприкосновенные» блоки: `target`, `relations`, `protected`,
`lore`, `current`, `sandwich`. Остаток делится по долям:

| Блок | Параметр доли | Доля |
|---|---|---|
| map | `limits.chat_budget_map_ratio` | 0,05 |
| rag | `limits.chat_budget_rag_ratio` | 0,15 |
| global | `limits.chat_budget_global_ratio` | 0,30 |
| thread | `limits.chat_budget_thread_ratio` | 0,20 |
| anchors | `limits.chat_budget_anchors_ratio` | 0,05 |
| branch | `limits.chat_budget_branch_ratio` | 0,03 |
| target | `limits.chat_budget_target_ratio` | 0,05 (для mood) |
| nostalgia | (внутренняя константа) | 0,02 |

Порядок «жертв» при переполнении: **сначала style_anchors, потом rag, потом
thread, потом global (режется с начала, но конспект-голова держится и есть пол),
затем map, в последнюю очередь — ностальгия**. Блоки `lore`, `protected`,
`target`, `relations`, `current` не режутся. Внутри `Global_Context` есть свой
потолок: `limits.chat_global_context_max_tokens` (прод `null`) → если не задан,
действует `limits.chat_global_context_max_chars` (4000). Стилевые якоря —
`limits.chat_style_anchors_count` (код-дефолт 3; **на проде 20**), каждый до
`limits.chat_style_anchor_max_chars` (400).

**Конспект окна.** Когда сообщений в L1-окне накапливается больше
`limits.chat_context_fill_ratio` × `limits.summary_max_window_messages` (0,8 ×
500; прод max = 2000), в фоне строится «бегущий конспект»: голова окна сжимается,
хвост `limits.chat_running_summary_tail` (30) сообщений остаётся дословно. TTL
записи `limits.running_summary_ttl_minutes` (60), но при чтении конспект не
удаляется по сроку. Дополнительно из старого конспекта строится «широкий фон»
(level 2) при `limits.chat_level2_min_raw_count` (250) — он показывается строкой
«широкий фон:» первой в `Global_Context`.

### 10.2. Группы и лички: в чём разница

- **Личный диалог** — это `DirectChatService`; работает и в группах (обращения
  «бот», реплаи, упоминания).
- **Ностальгия** (оба слоя) — только группы.
- **Отношения** — только группы; на проде тон выключен.
- **Лор и ностальгия** в фоновых обходах берут только группы (`chat_id < 0`),
  лички в списки не попадают.
- **Периодическое саммари** (крон) — только группы; ручная команда `/summary` в
  личке работает. В личке «тяжёлые» модули по умолчанию выключены профилем.
- **RAG/память/граф** — общие для групп и личек, но разделены по `chat_id`
  (память одного чата не видна в другом).

### 10.3. Другие пайплайны

- **`/summary`** (`services/summary_generator.py`): сжатие/очистка → L1-окно →
  XML → L2-цитаты (`limits.summary_rag_l2_limit` = 10) → L3-вектора
  (`limits.summary_rag_l3_limit` = 10) → связи графа
  (`limits.graph_top_edges_limit` = 5) → RAG-контекст (канон
  `<context>/<user_gossip>/<bot_knowledge>`) → нейросеть. Итоговый `user_content`
  ограничен `limits.summary_max_context_tokens` (прод 60000) или
  `limits.summary_max_context_chars` (прод 30000).
- **Поиск/фактчек** (`services/chat_context.py`): к запросу добавляется маленькое
  окно последних `limits.factcheck_context_messages`/`search_context_messages`
  (6) сообщений, помеченное как «болтовня, НЕ доказательства», не длиннее 2000
  символов, и RAG-контекст.

---

## 11. Что реально включено на проде (срез 06.09.2026)

По аудиту `plans/docs/prod-params-audit-2026-09.md`:

**Включено:** `memory.dream_enabled=true`, `memory.nostalgia_enabled=true` (слой
B) и `memory.nostalgia_layer_a_enabled=true` (слой A),
`flags.dig_enabled=true`, `flags.dig_pre_gate_enabled=true`,
`memory.infinite_retention=true`, `flags.graph_rag_enabled=true`,
`flags.lore_worker_enabled=true`, `flags.lore_auto_enabled=true`,
`flags.lore_inject_enabled=true`, `flags.chat_rag_rerank_enabled=true`,
`flags.relations_tone_enabled=false` (механика отношений считается, но на тон не
влияет).

**Выключено:** `flags.memory_commands_user_enabled=false` (команды «запомни/забудь»
только для админа/модератора), `flags.summary_streaming_enabled=false`,
`flags.relations_tone_enabled=false`.

**Нестандартные прод-значения, влияющие на память/контекст:**
`limits.chat_context_budget_tokens=24000` (дефолт 4000),
`limits.chat_global_context_limit=200`, `limits.chat_style_anchors_count=20`,
`limits.summary_max_window_messages=2000`,
`limits.summary_max_context_tokens=60000`, `limits.summary_max_context_chars=30000`,
`limits.summary_max_symbols=8000`, `limits.memory_backup_keep=7`,
`limits.dig_max_snippets=15`, `limits.dig_max_facts=5`, `limits.dig_max_symbols=5000`,
`limits.token_safety_multiplier=0.8`.

**Что это значит на практике.** «Сон» и ностальгия реально работают. Бессрочное
хранение включено: физической TTL-чистки фактов и сырья нет, но «протухшее» не
выдаётся. RAG в личном чате делает дополнительный вызов нейросети на реранг
кандидатов. Лор авто-обновляется и инжектится. Отношения считаются и видны в
админке, но тон по стадиям пока не подмешивается. Команды «запомни» участникам
недоступны.

---

## 12. Управление: дефолты, горячие параметры, per-chat

- **Каталог параметров** — `services/param_catalog.py`. Все ключи памяти
  (`memory.dream_*`, `memory.nostalgia_*`, `limits.graph_*`,
  `limits.lore_*`, `limits.relations_*`, `limits.dig_*`, `flags.*`) имеют
  русское название и простое описание.
- **Дефолты** — `config/settings.py` (константы `DREAM_*`, `NOSTALGIA_*`,
  `LORE_*`, `GRAPH_*` и т.д.).
- **Горячее чтение** — `services/hot_config.py` (`hot.get`): сначала значение из
  PG/TMA, иначе дефолт из `settings`. Большинство параметров меняется без
  перезапуска.
- **Per-chat** — `services/chat_params.py` (`get_chat_param`): разрешённые
  per-chat ключи берутся из `chat_params.overrides` (с приведением типа по
  каталогу), иначе падают на глобальное значение. Категории `prompts`, `limits`,
  `flags`, `reactions`, `content`, `memory` переносимы на чат; `models.*` и
  `keys.*` — строго глобальные.
- **Feature gates** — `services/feature_gates.py` (см. 6.4).

---

## 13. Что стоит держать в голове (нюансы и неоднозначности)

1. **Терминология «L1/L2/L3» пересекается.** В памяти это «окно / сырьё /
   архив», а в конспектах `chat_summary_levels` level 2 — это «широкий фон», а не
   второй уровень памяти. В отчёте я развёл эти понятия, но в коде на них легко
   наткнуться и перепутать.
2. **Бессрочное хранение ≠ «всё видно».** При `infinite_retention=true` записи
   не удаляются, но сроки `expires_at` продолжают влиять на выдачу: старый факт
   может лежать в базе, но не попадать в ответы, пока его не «тронут» повторным
   упоминанием.
3. **Год назад — ровно один год.** Ностальгия ищет сообщения около «now − 365
   дней ± 2 дня»; более старые годы подтягиваются только инструментом
   `dig_into_lore`, а не слоем B.
4. **Порядок сборки контекста менялся между раундами.** Если будете сверять с
   более старыми описаниями, ориентируйтесь на текущий docstring
   `_build_user_content` и порядок, приведённый в разделе 10.
5. **RAG-реранг — платный.** При `flags.chat_rag_rerank_enabled=true` каждое
   личное сообщение с найденными фактами памяти тратит дополнительный вызов
   нейросети. Это осознанное прод-решение, но его стоит помнить при разборе
   расходов.
6. **Прод-значения могут измениться.** Срез 06.09.2026 — не истина в последней
   инстанции; актуальные числа всегда смотрите в `bot_settings`/TMA.
7. **Защищённые факты — «святая святых».** Их не трогают ни дедуп, ни «сон», ни
   удаление дублей. Это сделано, чтобы важные карточки людей и чат-лор не
   «съедались» автоматикой.
8. **Бот-сообщения в память не пишутся.** Это влияет на то, что «жизнью чата»
   для ностальгии/лора считаются только человеческие реплики; ответы бота живут
   отдельно (`bot_replies`) и используются для стиля и цепочек.
