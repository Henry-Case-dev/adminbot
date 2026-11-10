# VMQ-MEM-06 — end-to-end путь до Writer (deployed `32e018b9`, 2.58.179)

Читаны блобы: mca_retrieval_context `aeae04dd`, direct_chat_service `f661abd5`, tool_router `500669c8`,
lore_compiler_service `40b53112`, database `6f5dba62`, tool_schemas `f9f6f438`, direct_l1 `d4056e19`,
direct_context_composer `4637d2a7`, memory_search `becfaa28`, chat_prompts `b6648fce`, settings `03d2840f`,
handlers/direct_chat `0bcc9170`. ONTO-01 `semantic_contracts`/`semantic_grounding` в выкате **отсутствуют**
(`git cat-file -e 32e018b9:services/semantic_contracts.py` → fatal) — онтологической подсказки в маршруте нет.

## 1. Трасса question → Writer
1. `handlers/direct_chat.py:551 direct_chat_handler` → `DirectChatService.handle` (direct_chat_service:3697) → `_handle_turn` (3759); `query = _message_user_text(message)` (3771).
2. Резолв субъекта: `_resolve_name` (3767), `_participant_roster`/`_alias_map_block` (8462/8465), `summary_aliases.bind_turn_aliases` (3744). `entity_resolver.resolve_entity` в маршруте **не участвует** (grep: только database/memory_communities/summary_memory/entity_merge). `build_memory_query`/`build_memory_request` (mca_rc:1117/1154) в прод-пути **не вызываются** (только тесты) → запрос памяти = сырой текст пользователя.
3. Семантический план: `direct_l1.build_l1_context` (1606) — «Полный Writer-контекст L1 НЕ получает» (1619), т.е. L1 видит окно+capabilities, не retrieval; `normalize_l1_plan` (601) заполняет `L1Plan.response_act/structure/capabilities_needed/search_intent` (285–347), `resolve_search_axis` (733), гейт доставки `lore_story_delivery_allowed` (415).
4. Кандидаты (два независимых вызова одного `retrieve`):
   - RAG-факты: `_build_rag_block` (12109) → `_rag_unified_rows` (12012) → `retrieve` (mca_rc:1352), request `mode="specific"`, `channels=("vector",)`, `top_k=GRAPH_RAG_FACTS_LIMIT=10`, `preserve_channel_order=True` (12042–12050); канал vector = `MemoryManager.retrieve_fact_candidates` (1571). exact/lexical/эпизоды здесь отключены осознанно (12001–12010).
   - Старые эпизоды: `_compose_user_content` (8991/9014) → `_build_old_episodes` (8849), request `mode="history"`, `top_k=8`, `channels` = политика по умолчанию → `retrieve` (8905); берутся только `entity_type=="message"` (8926), вокруг хита `get_messages_around(±120/60)` (8933), `compute_episode_span` gap 300 c, cap **2 эпизода/40 сообщений** (composer:169–181), piece priority **P0** (composer:65). Работает только при `composer_on()` (composer:137, default ON).
   - Тематические линии: канал `community` только `mode=="thematic"` (mca_rc:1592) + гейт `MCA_MEMORY_COMMUNITIES_ENABLED` (1941, default OFF по MEMORY-07) → в reply-пути не активен.
5. Валидация: `request_reason_code` (721) + `effective_chat_ids` (788) — chat scope строго `(chat_id,)`; `assess_relevance` (1068), `apply_subject_gate` (1023), SourceRef = `resolve_item_id`/`_message_candidate` (1726). `EvidenceBundle._build_evidence_bundle` (9584) собирает refs **regex-ом** `_REF_ID_RE` (864) только из `<RAG_Memory>` + branch/thread, ≤20 (9611–9613) — блок `<Old_Episode>` в bundle не попадает.
6. Writer: `build_messages(system_prompt, user_blocks)` (4824), system = `resolve_chat_speech` (4308); порядок блоков — `CANONICAL_ORDER` (composer:108).

## 2. Пять классов: где именно расходится путь
- **Юмористический рассказ.** При `response_act=creative`/`structure=story` модель видит `compile_lore_story` (tool_schemas:423–442, описание «tell a story … comprehensive historical overview») → `_compile_lore_story` (tool_router:5164) → `LoreCompilerService.compile` (lore:92): `lore_graph_slice` (database:9596, depth≤2, 30 фактов/4000 симв.) + `lore_dense_dialogs` (9736, точный COUNT, **страйд-сэмпл при >300 совпадений → поздние годы не выпадают**, топ-3 окна по 30 мин, ≤60 строк/6000 симв.) + first/last_seen; готовый текст отдаётся **дословно вместо Writer** (`lore_story_override` 1775).
- **Обычный пересказ.** Тот же инструмент может быть вызван, но act=summarization/explanation/report → гейт 435–437 даёт False, рассказ остаётся материалом, отвечает Writer.
- **Характеристика участника.** `get_user_context` (3335) purpose=biography/identity → `_memory_lookup_unified` (3688) c `channels=("subject",)` (202), `mode="specific"`, **query = только имя человека** (3742), `top_k`=5/10; канал subject = `get_user_context_facts` (mca_rc:948–1023: confirmed/TTL/`weight DESC`) — без эпизодов и без периодов. Без вызова инструмента остаётся лишь vector-топ-10 в ≤2000 симв.
- **Восстановление конфликта.** `dig_into_lore` (1998): FTS `search_long_term` limit=40 (2135–2137), окно `year`/`year_to` (2016–2045), вывод топ-8 сниппетов/3 факта/3500 симв. (`DIG_MAX_*`, settings:3232–3234); graph-expansion — через `retrieve` при K1 (2181–2191). Многолетний вопрос = один диапазон, не выборка по годам.
- **Отношения/взгляды за годы.** `purpose=relationships` (3649) → `channels=()` (3662) → `retrieve` возвращает пусто; связи только из `get_persona_card` (`_relations_projection`, mca_rc:894–907), у каждого ребра `ts=None` (3679) → временного ряда нет. Автоблок `<user_relations>` (10885) — только стадия бот↔собеседник + месяц `first_seen` + сообщений за 30 дней.

**Где обычный факт получает хуже:** (а) `_INTENT_TO_MODE` (450) + `resolve_channels` (780–782) — intent fact/who/relationship/current даёт `mode="specific"` и **удаляет канал episode** при `trigger_ref=None`; (б) `typed_rank_score` (829–833) — бонус свежести +12 только при возрасте <365 дней, старые годы его не получают; (в) `_episode_candidates` ограничен `top_k` (2083), эпизоды сортируются первыми (1638–1642) и после `ordered[:limit]` (1677) при ≥8 совпавших lore-историй занимают все 8 слотов, а потребитель их отбрасывает (8926) → блок эпизодов пуст (голодание message-хитов); (г) RAG-блок P2 (composer:76) усечён до 2000 симв. и вытесняется под давлением бюджета, эпизоды (P0) остаются; (д) `dedup_rag_vs_global` (12181, порог 0.8) выкидывает уже видимое, старые периоды не подставляются; (е) `assess_relevance` (1074–1081) при `subject_mismatch`/`ambiguous_subject` объявляет память неуместной.

## 3. Где теряется период/год
1. `_apply_filters` (1335–1349): `cand.sent_at` = 0 проходит любой фильтр (fail-open), в отличие от `_split_range` (1238, fail-closed).
2. Год в запросе автоматически не разбирается: `extract_history_depth` (tool_router:697) ловит только «последние N сообщений/реплик»; диапазон появляется лишь из аргументов модели (2016/1623/1855).
3. `is_history_query`/`_HISTORY_MARKERS` (709/465–468): «расскажи» есть, «рассказ» нет → маркер зависит от словоформы; работает только при `mode="auto"` (760), т.е. фактически в ui_search (memory_search:892).
4. `top_k` + recency-бонус + `ordered[:limit]` (1398/829/1672) — свежее вытесняет старые годы.
5. `_dedup`/`dedup_id` (1321/589) схлопывает повтор одного факта: обновлённая версия убеждения вытесняет прежнюю, хронология теряется.
6. `include_archived=False` по умолчанию (522): вытесненные квотой `archived_fact` не видны, кроме dig (2243).
7. Резолв субъекта требует алиаса: `_resolve_author_id` (1745–1762) — 0 совпадений → `author_unresolved`, >1 → `author_ambiguous`, инструмент отвечает `unsupported` (1800) и фильтр не выполняется.
8. `lore_dense_dialogs(since_ts=last_ts)` + `included_last_ts` (lore:106/250): при обновлении рассказа старые периоды повторно не читаются.
9. `lore_graph_slice` сканирует первые 2000 узлов по id (9624–9627) — узлы сверх лимита не находятся.

## 4. Получает ли творческий запрос более широкий retrieval?
**Через единый `retrieve()` — нет.** Оба класса проходят идентичные вызовы с идентичными лимитами (12042–12050 и 8884–8886). Разница только в трёх местах: (1) модель выбирает инструмент по EN-описанию `compile_lore_story` («tell a story», tool_schemas:428–430); (2) у Летописца **свой** материал-билдер (`lore_graph_slice`+`lore_dense_dialogs`, database:9596/9736) вне `retrieve()`; (3) delivery-гейт отдаёт готовый рассказ вместо Writer. Промпт Writer различает только форму («просят историю — пиши законченную историю», chat_prompts:324).

## 5. Отрицательное доказательство
Один маршрут: `git grep "def retrieve"` даёт единственную реализацию (mca_rc:1352); все потребители — chat_statistics:722, direct_chat_service:8905/12051, memory_search:896, nostalgia_worker:711, tool_router:3752, mca_exploration:1603/2095 — вызывают её. Ветвлений по формулировке внутри `retrieve` нет (только `mode`/`intent`/`channels`, 1394–1397). Лексический пре-гейт исторического поиска удалён: `dig_fired = False` (4033–4041); `_HISTORY_MARKERS` остаются лишь для `mode="auto"` (760) и на reply-путь не влияют. Второго summary-пайплайна нет: Летописец — существующий `LoreCompilerService` (не добавленный), отдельная реализация чтения, включается только как tool. Новых хранилищ нет: `graph_facts`, `smart_messages`, `nodes`/`edges`, `lore_stories`.

## 6. Что мерить DevOps на реальных 2,07 млн (по каждому классу)
Логировать: `run_id`, класс, точный запрос, `mode`, `purpose`, `channels_used`, `reason_code`, `relevance.reason_code`, `len(candidates)`, `len(fact_rows)`, `dropped[]`; по каждому кандидату — `id/entity_type/channel/sent_at/author_id/score`; гистограмму `sent_at` по годам, `min/max`, число независимых лет и независимых эпизодов; Old_Episode — `count/messages/hits/supplement_lines` (8979–8988); инструменты — имя, аргументы (`year`,`year_from`,`year_to`,`person`), статус, `coverage.{messages_total,messages_shown,facts_shown,sampling}`, `total_mentions`, `first_seen/last_seen` (2425–2433), Летописец — `graph_lines/dialog_lines/total/earliest/latest/is_update/unchanged` (lore:267–271); связи — `text/edge_id/fact_id/origin/weight/has_unsupported_sources/ts`; Writer payload — refs из `_REF_ID_RE`, символы и число фактов в `<RAG_Memory>`, число эпизодов, `excluded[]` (kind/reason_code/tokens). Метрики с фиксированными знаменателями: coverage, chronological_accuracy, relevance, invented_links.

VMQ-MEM PATH DOCUMENTED

Три наиболее вероятные причины наблюдаемой асимметрии:
1. Творческий запрос попадает в `compile_lore_story` с собственным период-сохраняющим билдером (`lore_graph_slice`+страйд-сэмпл `lore_dense_dialogs`) и подменой ответа, а обычный вопрос остаётся на `retrieve()` с vector-топ-10/2000 симв. и 2 эпизодами.
2. Для фактических интентов `mode="specific"` отключает канал episode, а recency-бонус и `top_k` смещают выдачу к свежим годам.
3. Эпизоды-first (`history_bias`) вместе с `top_k=8` в `_build_old_episodes` заполняют пул entity_type="episode", которые потребитель затем отбрасывает — блок старых эпизодов остаётся пустым.
