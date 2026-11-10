# VMQ-MEM — корневая причина «материал только из 2026»

Read-only, 10.11.2026. Деплой `32e018b9` (2.58.179) и кандидат `7bc8545a` читаны через `git show`; номера ниже = деплой.
Блобы деплоя: `mca_retrieval_context` `aeae04dd`, `summary_memory` `38c98086`, `database` `6f5dba62`, `direct_chat_service` `f661abd5`,
`direct_context_composer` `4637d2a7`, `tool_router` `500669c8`, `settings` `03d2840f`, `lore_compiler_service` `40b53112`.
Кандидат меняет только срез эпизодов и msg-якорь (`mca_retrieval_context` `ea45a331`, `composer` `0af4bfb5`); decay/quota/лимиты в `settings` идентичны — **годовой сдвиг кандидат не исправляет**.

## 1. Источники reply-материала
- Факты: `retrieve(mode="specific", channels=("vector",), top_k=10, preserve_channel_order=True)` (`direct_chat_service:12010,12042-12050`) → `retrieve_fact_candidates` (`summary_memory:5582`) → `_search_graph_facts` (`5840`) → KNN `_knn_graph_facts` (`6036`), SQL `graph_facts_vec … MATCH … k=?`.
- Сообщения/эпизоды: `retrieve(mode="history", top_k=8)` (`8849-8905`), каналы по умолчанию (`mca_rc:447`: exact+entity+lexical+vector+reply_graph+episode); потребитель берёт только `entity_type=="message"` (`8926`), вокруг хита `get_messages_around(±120/60)` (`8933`).
- Эпизоды: `_episode_candidates` (`2036-2091`) — `list_lore_stories(limit=200)`/фасад `mca_episodes`, отбор по overlap токенов темы, **без даты**.
- `smart_messages` FTS: `dig_into_lore` (`tool_router:2135-2137`, limit=40) и `search_long_term` — только как инструмент модели.
- Communities/тематические линии: канал `community` лишь при `mode=="thematic"` (`1592`) + гейт `MCA_MEMORY_COMMUNITIES_ENABLED` (default OFF) → в reply не активен.
- Профиль: `get_user_context` → `mode="specific", channels=("subject",)`, `top_k=10` (`tool_router:3626-3630,3688-3752`) → `get_user_context_facts` (`mca_rc:948-1023`).

## 2. Временные фильтры
Год из вопроса reply-путь **не разбирает**: в `direct_chat_service` есть только `extract_history_depth` (`7128`, «последние N») и `bind_quantitative_range` по краям готовой выборки (`8890-8892`); регулярки года/«N лет назад» — только в инструментах (`tool_router:5621-5656`). Поэтому без года:
- `_apply_filters` (`1335-1349`): `time_from/time_to=None` → фильтр не применяется вообще (при заданном окне `sent_at==0` проходит fail-open, в отличие от `_split_range` `1238`).
- RAG: окно `None` → бонус «внутри окна» (`838`) никому; `preserve_channel_order=True` (`1643-1648`) вообще отключает `typed_rank_score` на RAG-пути.
- Эпизоды: окна нет (появляется лишь из `history_sample`) → 2022 достижим. `dig` без года: `bounds=None` → `since_ts/until_ts` не ставятся (`2131-2132`).
- Вывод: **явного годового фильтра, отсекающего 2022-2024, нет нигде**. Режут два неявных отсечения: статус живости фактов и `LIMIT` после ранжирования.

## 3. Ранжирование — фактические константы
- `_CHANNEL_WEIGHTS` (`404-428`): exact 100, subject 95, entity 90, lexical 80, recent 70, vector 60, reply_graph 40, community 30, episode 20; score = вес − позиция (`1283`).
- `typed_rank_score` (`816-852`): `+8` provenance, `−8` legacy graph_fact, `+12·(1−возраст/365)` **только при возрасте <365 дней** (`829-833`, `_TYPED_RECENCY_BONUS=12.0` — `461`), `+12` внутри окна, `specific`: graph_fact `+4`, episode `−6`.
- Главный годовой член — в векторном канале (`summary_memory:6121-6124`): `score = cosine × w_eff × importance`, где `w_eff = weight × 0.5^(Δдней_от_last_confirmed_at / 60)` с **floor 0.1** (`948-964`; `settings:2962-2964`), `importance_factor=0.5+0.05·imp ∈ [0.55,1.0]` (`886-899`).
  При weight≈0.5 пол достигается на ~139 днях → **все факты старше ~4,5 месяцев получают один и тот же минимум 0.1**, свежие — до 0.5. Разрыв до 5× при разбросе cosine ~1.5× → при ≥10 свежих кандидатах старые не попадают никогда.
- Пул: KNN `fetch_k=max(limit, GRAPH_MMR_FETCH_K=20)` (`6053-6055`, `settings:2982`), overfetch ×4/cap 512 (`133-134`); MMR λ=0.6 (`settings:2981`) → `ranked[:limit]`, `limit=10` (`settings:2171`).
- `history_bias` (`1638-1642`) + `(eps+rest)[:limit]` (`1672-1677`): при `mode="history"` эпизоды встают выше канала с бо́льшим score; наблюдалось 8/8 слотов эпизодами при score 25 против 79-80 у message-хитов.
- Дедуп (`1321-1332`) — по `dedup_id` факта, оставляет максимальный score; SUPERSEDE-версия живёт одной строкой (`summary_memory:4865+`) → хронология изменения убеждения теряется.
- **Скрытый отсев, сильнее ранга** (`summary_memory:6065-6070`): в KNN-выдачу попадают только `status ∈ ("confirmed","archived_belief")` (`918-922`). `archived_fact` не рассматривается вовсе, т.к. reply-путь передаёт `include_archived=False` (`mca_rc:522`, `summary_memory:5593-5596`).

## 4. Профиль участника
Резолв — `AliasResolver` (`tool_router:3362-3363`), запрос = **только имя** (`3740-3742`) + `subject_entity_ids=(uid,)`; `biography` → `channels=("subject",)`, `top_k=10` (`3626-3630`, `185`). SQL канала (`database:12538-12548`):
`… WHERE chat_id=? AND (subject_ref_id=? OR (subject_ref_id IS NULL AND target_user=?)) AND status='confirmed' AND (expires_at IS NULL OR expires_at > ?) ORDER BY weight DESC, created_at DESC LIMIT ?` — **годового предиката нет**; год не участвует вообще.
Почему всё равно только 2026: квота `GRAPH_FACTS_PER_USER_QUOTA=50` (`settings:2969`) на каждом write вытесняет жертву `MIN(weight/(age_days+1))` (`get_quota_victim`), т.е. **самый старый** уходит в `archived_fact` (`database:12288-12330`, неразрушающе: строка+FTS+vec сохраняются). Обычные чтения — `confirmed`-only, поэтому у автора с 216 588 сообщениями живых фактов ~50, и это «последние ~50».
Итог: канал **может** дойти до 2023 — предиката даты нет; фактически не доходит, т.к. старшие факты уже архивны и отсечены статусом, а из выживших top-10 добирается по весу.

## 5. Сборка контекста
`composer`: `rag=P2`, `episode=P0`, `history_supplement=P2` (`57-86`); порядок слотов `episode(2)→supplement(3)→rag(4)→global_head(5)…` (`108-134`). RAG: 10 фактов, `graph_rag_context_max_chars=2000` (`settings:2173` → `summary_memory:5465`), рендер ASC (`direct_chat_service:12226`) — меняет порядок, не состав. `<Old_Episode>`: `MAX_COUNT=2`, `MAX_MESSAGES=40`, `gap=300` (`753-758`, `composer:169-181`), piece P0 — при давлении окна режется RAG (P2), эпизод остаётся. Профиль: JSON `_MEMORY_LOOKUP_RESULT_MAX_CHARS=4000` (`tool_router:175`), досье-портрет 1200 (`direct_chat_service:841`), авто-`<user_relations>` 600 симв. (`10956-10957`, только bot↔собеседник, `first_seen` месяцем).

## 6. Где именно теряется многолетняя история
**(a) Событийный вопрос без года — стадия ОТБОРА ФАКТОВ векторного канала** (`summary_memory._knn_graph_facts`, `6065-6070` + `6121-6124`). Не фильтр по времени: пул режут (1) статус-фильтр живости, куда старые факты попадают через возрастную квоту-вытеснение, и (2) мультипликативный `w_eff` (half-life 60 дн., floor 0.1), приравнивающий всё старше ~139 дней к минимуму. Усилитель — плотность корпуса: 2026 — 15 721/22 889 (68.7%), 2023 — 1 419 (6.2%), 2022 — 96 (0.4%). Доказательство: в 4 из 5 классов замера `retrieve` отдаёт 10/10 фактов 2026, а в классе E (тонкий свежий пул) — 4 разных года; поведение объясняется ранжированием пула, не запретом лет.
**(b) Вопрос о человеке без года — стадия ЧТЕНИЯ ПРОФИЛЯ** (`database.get_user_context_facts`, `12543-12546`): `status='confirmed' AND expires_at>now` + `LIMIT` по `weight DESC, created_at DESC`, где состав живого набора предопределён возрастной квотой (`summary_memory:4841-4863`). Замер: `subject` отдал 10 фактов, все 2026.
**Фиксабельность:** да. Оба механизма — существующие чтения и уже существующий архивный канал (`include_archived=True`, `mca_rc:522`); архивные строки, FTS и vec-строки сохраняются при вытеснении (`database:12304-12307`) → новых хранилищ и пересчёта эмбеддингов не нужно.

## 7. Минимальное изменение для «человека без года»
Изменить **фильтр живости и порядок** в `get_user_context_facts` (либо в `_subject_fact_rows`, `mca_rc:948-1023`): допустить `status IN ('confirmed','archived_fact')` для biography/identity и заменить `ORDER BY weight DESC, created_at DESC` на выборку с квотой **по годам** (по существующим `message_timestamp`/`created_at`), подняв `top_k` до ~15.
Что сломается: контракт MEMORY-06 §4.4 «обычные reply-пути архив не видят» (`mca_rc:519-522`) — вытесненные и SUPERSEDE-устаревшие убеждения покажутся как текущие; обязательны существующие пометки `read_policy_rank`/as-of и гейт по purpose (только вопрос о человеке, не «что сейчас»); растёт объём профиля (кап 4000 начнёт урезать хвост).
Для (a) симметрично: заменить мультипликативный `w_eff` на ограниченный аддитивный tie-breaker (порядка `_TYPED_RECENCY_BONUS=12`, что меньше разрыва каналов 20) и разрешить `archived_fact` с годовой квотой в `_knn_graph_facts`; риск — старые шумные факты вытеснят актуальное состояние, нужен гейт по intent.
**Мерка успеха:** тот же замер (`measurement-2.58.179.md` §2-§3) на кандидате для класса C — гистограмма `sent_at` профиля содержит ≥1 факт 2023, ≥1 факт 2024 и ≥3 разных года; known-answer проба: вопрос про участника без года о факте с `message_timestamp` 2023-2024 обязан вернуть этот факт в поданном материале; обратная проба «что сейчас» остаётся 2026-доминированной. Для (a) — гистограмма `<RAG_Memory>` ≥3 разных лет в ≥3 классах без года.

ROOT CAUSE ESTABLISHED — (a) событийный вопрос без года: отбор фактов в векторном канале (`_knn_graph_facts`: статус-фильтр живости + `cosine × w_eff` с half-life 60 дн./floor 0.1 при плотности корпуса 68.7% за 2026); (b) вопрос о человеке без года: чтение профиля (`get_user_context_facts`: `confirmed`-only + `LIMIT`/`ORDER BY weight, created_at DESC` поверх возрастной квоты 50, вытесняющей старейшие в `archived_fact`). Явного годового фильтра на обоих путях нет. Фиксабельность: **FIXABLE в существующих механизмах** — правка предиката/скоринга и включение уже существующего архивного чтения, без новой memory-системы и без пересчёта эмбеддингов.
