# VMQ-MEM — корневая причина «материал только из 2026»

Read-only анализ 10.11.2026. Деплой `32e018b9` (2.58.179) и кандидат `7bc8545a` читаны через `git show`.
Блобы деплоя: `mca_retrieval_context` `aeae04dd`, `summary_memory` `38c98086`, `database` `6f5dba62`,
`direct_chat_service` `f661abd5`, `direct_context_composer` `4637d2a7`, `tool_router` `500669c8`,
`settings` `03d2840f`, `lore_compiler_service` `40b53112`. Кандидат меняет только срез эпизодов и
msg-якорь (`mca_retrieval_context` `ea45a331`, `composer` `0af4bfb5`); `settings` по decay/quota
идентичен (`GRAPH_RAG_FACTS_LIMIT`/`HALF_LIFE`/`FLOOR`/`QUOTA`/`MMR_FETCH_K` совпали) — **годовой сдвиг
кандидат не трогает**. Номера строк ниже = деплой.

## 1. Источники (все пути reply-хода)
1. `graph_facts` через `retrieve(mode="specific", channels=("vector",), top_k=10, preserve_channel_order=True)`
   (`direct_chat_service:12010,12042-12050`) → `MemoryManager.retrieve_fact_candidates` (`summary_memory:5582`)
   → `_search_graph_facts` (`5840`) → KNN `_knn_graph_facts` (`6036`), SQL `graph_facts_vec … MATCH … AND k=?`.
2. Сообщения/эпизоды: `retrieve(mode="history", top_k=8)` (`8849-8905`), каналы по умолчанию
   (`mca_rc:447`) = exact+entity+lexical+vector+reply_graph+episode; потребитель берёт только
   `entity_type=="message"` (`8926`), вокруг хита `get_messages_around(±120/60)` (`8933`).
3. Эпизоды/lore: `_episode_candidates` (`2036-2091`) — `list_lore_stories(limit=200)` / `mca_episodes`
   фасад, отбор по overlap токенов темы, **без даты**.
4. `smart_messages` FTS — `dig_into_lore` (`tool_router:2135-2137`, limit=40) и `search_long_term`;
   только как инструмент модели, не в reply-материале.
5. Тематические линии/communities — канал `community` только `mode=="thematic"` (`1592`) + гейт
   `MCA_MEMORY_COMMUNITIES_ENABLED` (по MEMORY-07 default OFF) → в reply не активен.
6. `memory_mentions`/личный профиль — `get_user_context` → `mode="specific", channels=("subject",)`,
   `top_k=10` (`tool_router:3626-3630`, `3688-3752`), канал `subject` = `get_user_context_facts`
   (`mca_rc:948-1023`).

## 2. Временные фильтры
**Ни один reply-путь не разбирает год из вопроса.** `direct_chat_service` содержит только
`extract_history_depth` (`7128`, «последние N») и `bind_quantitative_range` по краям готовой выборки
(`8890-8892`); регулярки года/«N лет назад» живут исключительно в инструментах (`tool_router:5621-5656`).
Значит при вопросе без года:
- `_apply_filters` (`1335-1349`): `time_from/time_to = None` → фильтр не применяется **вообще**; при
  заданном окне `sent_at==0` проходит fail-open (в отличие от `_split_range` `1238`, fail-closed).
- RAG: `time_from=None` → бонус «внутри окна» (`838`) не начисляется никому; на RAG-пути
  `preserve_channel_order=True` (`1643-1648`) вообще отключает `typed_rank_score`.
- Эпизоды: окно отсутствует (только при `history_sample`), т.е. 2022 доступен.
- `dig_into_lore` без года: `bounds=None` → `since_ts/until_ts` не ставятся (`2131-2132`).
Вывод: **явного годового фильтра, отсекающего 2022-2024, нет ни на одном шаге.** Потери дают не фильтры,
а два «неявных» отсечения: статус-фильтр живости фактов и срез по лимиту после ранжирования.

## 3. Ранжирование — фактические константы
- `_CHANNEL_WEIGHTS` (`404-428`): exact 100, subject 95, entity 90, lexical 80, recent 70, vector 60,
  reply_graph 40, community 30, episode 20; score = вес − позиция в канале (`1283`).
- `typed_rank_score` (`816-852`): `+8` provenance, `−8` legacy graph_fact, **`+12·(1−возраст/365)` только
  при возрасте < 365 дней** (`829-833`, `_TYPED_RECENCY_BONUS=12.0` `461`), `+12` внутри запрошенного окна,
  `mode="specific"`: graph_fact/entity `+4`, episode `−6`.
- Главный член — внутри векторного канала (`summary_memory:6121-6124`):
  `score = cosine × w_eff × importance`, где
  `w_eff = weight × 0.5^(Δдней_от_last_confirmed_at / 60)`, **floor 0.1** (`948-964`; `settings:2962-2964`);
  `importance_factor = 0.5+0.05·imp ∈ [0.55,1.0]` (`886-899`).
  Порог пола для weight≈0.5 достигается на ~139 днях → **все факты старше ~4,5 месяцев получают один и
  тот же минимальный множитель 0.1**, а свежие — до 0.5. Разрыв до 5×, тогда как cosine меняется в
  пределах ~1.5×; поэтому при наличии ≥10 свежих кандидатов старые не попадают в выдачу никогда.
- Пул: KNN `fetch_k = max(limit, GRAPH_MMR_FETCH_K=20)` (`6053-6055`, `settings:2982`), overfetch ×4, cap 512,
  отбор `_KNN_SCOPE_*` (`133-134`); MMR λ=0.6 (`settings:2981`), затем `ranked[:limit]`, `limit=10` (`settings:2171`).
- Дедуп (`mca_rc:1321-1332`) — по `dedup_id` факта, оставляет максимальный score; версия убеждения после
  SUPERSEDE живёт одной строкой (`summary_memory:4865+`) → хронология изменения теряется.
- **Скрытый отсев, сильнее ранга** (`summary_memory:6065-6070`): в KNN-выдачу попадают только строки со
  `status ∈ ("confirmed","archived_belief")` (`918-922`). `archived_fact` не рассматривается вовсе, т.к.
  reply-путь передаёт `include_archived=False` (`mca_rc:522`, `summary_memory:5593-5596`).

## 4. Профиль участника
Резолв: `AliasResolver` в `_get_user_context` (`tool_router:3362-3363`), затем
`RetrievalRequest(query = ТОЛЬКО ИМЯ человека)` (`3740-3742`) + `subject_entity_ids=(uid,)` +
`subject_names`; `biography` → `channels=("subject",)`, `top_k=10` (`3626-3630`, `185`).
SQL канала (`database:12538-12548`):
`… WHERE chat_id=? AND (subject_ref_id=? OR (subject_ref_id IS NULL AND target_user=?)) AND status='confirmed'
AND (expires_at IS NULL OR expires_at > ?) ORDER BY weight DESC, created_at DESC LIMIT ?`
— **годового предиката нет; год вообще не участвует**. Возвращаются только «живые» confirmed-факты,
отсортированные по весу с `created_at DESC` как тай-брейк.
Почему это всё равно только 2026: квота `GRAPH_FACTS_PER_USER_QUOTA=50` (`settings:2969`) на каждом write
вытесняет жертву `MIN(weight/(age_days+1))` (`database` `get_quota_victim`), т.е. **самый старый факт
уходит в `archived_fact`** (`12288-12330`, неразрушающе, строка+FTS+vec сохраняются). Обычные чтения
`confirmed`-only, поэтому у автора с 216 588 сообщениями живых фактов остаётся ~50, и это «последние ~50».
Механически канал **может** дойти до 2023 — предиката даты нет; фактически не доходит, потому что старшие
факты к этому моменту архивны и отсечены статусом, а из выживших top-10 добирается по весу.

## 5. Сборка контекста
`direct_context_composer`: приоритеты `rag=P2`, `episode=P0`, `history_supplement=P2` (`57-86`); порядок
слотов `episode(2) → supplement(3) → rag(4) → global_head(5) …` (`108-134`). RAG: 10 фактов,
`graph_rag_context_max_chars=2000` (`settings:2173`, применяется `summary_memory:5465`), рендер ASC
(`direct_chat_service:12226`) — состав, а не порядок. `<Old_Episode>`: `CHAT_EPISODE_MAX_COUNT=2`,
`MAX_MESSAGES=40`, `gap=300` (`753-758`, `composer:169-181`), piece P0. Профиль: JSON
`_MEMORY_LOOKUP_RESULT_MAX_CHARS=4000` (`tool_router:175`), досье-портрет 1200 симв.
(`direct_chat_service:841`), авто-блок `<user_relations>` 600 симв. (`10956-10957`, только
bot↔собеседник, `first_seen` месяцем). При давлении окна режется RAG (P2), эпизод (P0) остаётся.

## 6. Где именно теряется многолетняя история
**(a) Событийный вопрос без года — стадия ОТБОРА ФАКТОВ в векторном канале**
(`summary_memory._knn_graph_facts`, `6065-6070` + `6121-6124`). Не фильтр по времени: кандидатов режут
(1) статус-фильтр живости `confirmed`/`archived_belief`, в который старые факты попадают через
возрастную квоту-вытеснение, и (2) мультипликативный `w_eff` с half-life 60 дн. и полом 0.1, который
приравнивает все факты старше ~139 дней к минимуму. Усилитель — плотность корпуса: 15 721 из 22 889
фактов (68.7%) относятся к 2026, 2023 — 1 419 (6.2%), 2022 — 96 (0.4%). Доказательство: во всех 4 из 5
классов замера `retrieve` отдаёт 10/10 фактов 2026, а в классе E (тонкий свежий пул) — 4 разных года;
т.е. поведение объясняется ранжированием пула, а не запретом старых лет.
**(b) Вопрос о человеке без года — стадия ЧТЕНИЯ ПРОФИЛЯ**
(`database.get_user_context_facts`, `12543-12546`): `status='confirmed' AND expires_at>now` + `LIMIT` по
`weight DESC, created_at DESC`, где состав живого набора предопределён возрастной квотой
(`summary_memory:4841-4863`). Замер: `subject` отдал 10 фактов, все 2026.
**Фиксабельность:** да. Оба механизма — существующие чтения и существующий архивный канал
(`include_archived=True` уже есть: `mca_rc:522`/`20`, `system`-путь `dig`); архивные строки, FTS- и
vec-строки сохраняются при вытеснении (`database:12304-12307`), новых хранилищ и пересчёта эмбеддингов
не требуется.

## 7. Минимальное изменение для «человека без года»
Изменить **фильтр живости и порядок** в `get_user_context_facts` (или в `_subject_fact_rows`,
`mca_rc:948-1023`), а не вводить поиск: допустить `status IN ('confirmed','archived_fact')` для
намерений biography/identity и заменить `ORDER BY weight DESC, created_at DESC` на выборку с квотой
**по годам** (по существующим `message_timestamp`/`created_at`), подняв `top_k` до ~15.
Что сломается: контракт MEMORY-06 §4.4 «обычные reply-пути архив не видят» (`mca_rc:519-522`) —
архивные/вытесненные и SUPERSEDE-устаревшие убеждения покажутся как текущие; поэтому обязательны
существующие пометки `read_policy_rank`/as-of и pурpose-гейт (только вопрос о человеке, не «что сейчас»);
растёт объём профиля (кап 4000 симв. начнёт урезать хвост).
Для (a) симметрично: заменить мультипликативный `w_eff` на ограниченный аддитивный tie-breaker
(порядка `_TYPED_RECENCY_BONUS=12 < разрыва каналов 20`) и разрешить `archived_fact` с годовой квотой в
`_knn_graph_facts`; риск — старые шумные факты вытеснят актуальное состояние, нужен гейт по intent.
**Мерка успеха:** тот же замер (`measurement-2.58.179.md` §2-§3) для класса C на кандидате — гистограмма
`sent_at` профиля должна содержать ≥1 факт 2023 и ≥1 факт 2024 и ≥3 разных года; плюс known-answer проба:
вопрос про участника без года о факте, чей `message_timestamp` лежит в 2023-2024, обязан вернуть этот
факт в поданном материале; и обратная проба «что сейчас» — выдача остаётся 2026-доминированной.
Для (a) — гистограмма `<RAG_Memory>` ≥3 разных лет в ≥3 классах без года.

ROOT CAUSE ESTABLISHED — (a) событийный вопрос без года: отбор фактов в векторном канале
(`_knn_graph_facts`: статус-фильтр живости + `cosine × w_eff` с half-life 60 дн./floor 0.1 при плотности
корпуса 68.7% за 2026); (b) вопрос о человеке без года: чтение профиля
(`get_user_context_facts`: `confirmed`-only + `LIMIT`/`ORDER BY weight, created_at DESC` поверх
возрастной квоты 50, вытесняющей старейшие в `archived_fact`). Явного годового фильтра на обоих путях
нет. Фиксабельность: **FIXABLE в существующих механизмах** — правка предиката/скоринга и включение уже
существующего архивного чтения, без новой memory-системы и без пересчёта эмбеддингов.
