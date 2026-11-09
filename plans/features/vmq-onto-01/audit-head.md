# VMQ-ONTO-01 — VMQ-A: карта HEAD и дельта

**База:** ветка `integ/unify-release`, HEAD `c816e83c` (фикс качества MEMORY-07 §14) поверх `44a10e28` (MEMORY-08 S1/S2), `fd198eb8` (MEMORY-07 default ON), релиз `ea9a7141` = 2.58.168. Источник: `plans/owner_inputs/2026-11-09-vmq-onto-01.md` (1201 стр.) + поправка `2026-11-09-vmq-qrng-provider-management.md`. Код не изменялся.

## 1. VOICE-01 (P0) — реальность HEAD

| Что | Факт |
|---|---|
| `handlers/voice_transcription.py:178-212` `_inject_memory` | Пишет текст в `smart_messages` через `update_smart_message_text` (строка 193), затем отдельно `memorize_facts(..., source_type='voice_transcript')` (210-212). Инъекция идёт **только** при `transcribe_media_message` (316-319) |
| Ревизия/атомарность | `services/database.py:8175+` обновляет `text` и переиндексирует FTS5; **колонки `transcript_status/transcript_revision/transcript_updated_at` отсутствуют** — есть `media_type`,`media_ref`,`reply_to_id` (database.py:2294-2296, 302). Ревизии транскрипта как версии содержимого нет |
| Маркер медиа | `services/media_marker.py:106-139` — `[медиа: voice tg:<id>]`; при пустом тексте подставляется в `chat_context` (chat_context.py:255-257). После ready текст перекрывает маркер — но **только если строка попала в свежее окно**: кэш/снапшот не инвалидируется (`voice_transcription.py` не вызывает ни один cache-invalidate) |
| Direct-путь | `services/direct_chat_service.py:10184-10285` `_prepare_turn_media_evidence` → `media_readiness.prepare_media_evidence` (10226); ревизия перечитывается перед финальной сборкой `_refresh_turn_media_evidence` (10324-10370). Это **готовый шов**, но он про изображения: `is_media_dependent` (864-884) открывается по `own_media`/`reply_media`/`vision_intent`/`explicit_ref`, а сам `prepare_media_evidence` работает с `media_assets` Vision. Текстовый вопрос о двух уже полученных соседних голосовых не поднимает этот шов и голосового группового резолва не имеет |
| Группа медиа | `services/media_readiness.py` работает с `media_assets`/`media_group_id`; `services/media_group_buffer.py` живёт только in-memory TTL и только для фото-альбомов. Групповой резолв «два соседних голосовых по дейксису» **отсутствует** |
| Дефект «не вижу голосовые» | Причина по коду: транскрипт публикуется отдельным сообщением бота (`_reply_media`, 312-313), а в `smart_messages` текст исходного голоса обновляется асинхронно; если Writer собрал payload до `ready` — он видит только `[медиа: voice tg:N]`. Второго чтения перед Writer для голоса нет (в отличие от картинок) |
| Событийность | `voice_ready/voice_selected/voice_delivered_to_writer/stt_lag` отсутствуют; STT-событий нет. Единственный канал — `mca_events`/`pipeline_events` (R17-safe) |

**Вывод:** каркас доставки есть (readiness + refresh + FTS-переиндексация), не хватает: статуса/ревизии транскрипта как версии source-ref, инвалидации материализованного контекста, группового резолва голосовых, участия voice в `is_media_dependent`, сквозных событий.

## 2. MEMORY-09 — реальность HEAD

- `services/mca_retrieval_context.py:1319` `retrieve()` — единый вход; `RetrievalRequest` (468-542) уже несёт scope/mode/time_range/subject/speaker/reply_target/quote_source_ref, 10 каналов (`_CHANNEL_ORDER` стр.426), `_DEFAULT_CHANNELS` (444), режимы `specific|episodic|thematic` через `_INTENT_TO_MODE` (447). Есть `_episode_candidates` (2033), `_community_candidates` (1838), `apply_identity_prior` (588), `apply_subject_gate` (990), `ambiguity_variants` (1025), `compute_context_version` (344), `emit_stage_event` (376).
- Нет query-intent класса `person_overview | relationship_history | temporal_change`; `RETRIEVAL_INTENTS` (438) — плоский список без coverage-семантики. Multi-period coverage/evidence expansion как отдельной ступени нет.
- Эпизоды: `services/mca_episodes.py` (сегментация по гэпу/reply: 58-61, 134 `segment_messages`, детерминированная карточка 255). Готовый L1-слой — расширять, не дублировать.
- Продольного представления субъекта (L3) нет: `dossier`/`lore`/summary есть, но поля `source_coverage/recurrent_observations/counterexample/temporal_status` отсутствуют.
- `services/memory_search.py` (MEMORY-08 S1/S2, 44a10e28) — read-модель поиска и сообществ: **новый файл того же кандидата**, учитывать при записи.
- `services/memory_communities.py` — сборка (`building→active→superseded`, 130-133), provenance-классы `confirmed|tentative|legacy|cooccurrence` (136-139), `PROVEN/WEAK` (195-199), нейтральные метки (186). `flags.memory_communities_enabled` default ON (`config_cache.py:113`), env-аварийный OFF.

## 3. ONTO-01 — реальность HEAD

- `services/memory_contracts.py`: `LINK_TYPES|VERIFICATIONS|INDEPENDENCES|ASSERTION_KINDS` (84-87), enum'ы `AssertionMode`(181), `OriginClass`(198), `RelationStatus`(222), `EntityResolutionStatus`(233), `SearchIntent`(1225), `RelationView`(895), `EntityRef`(507), `MediaMemoryAttribution`(1989), `MemoryView/MemoryViewRef`(1651-1693). Это **готовый контракт смыслов** — ONTO обязан проецироваться в него.
- `services/entity_resolver.py`: `mca_entity_canonical` (64), методы alias/explicit/manual (111-113), `casefold_unique|casefold_multiple|casefold_prefix_overflow` (124-126) — резолвер неоднозначности уже есть.
- `services/relation_evidence.py`: `attach_edge_evidence` (184), plan-ы для bot-self/world-knowledge/no-address (137-165) — владелец независимости источников.
- `services/graphrag_provenance.py`: `EDGE_CONFIDENT|TENTATIVE|LEGACY_UNVERIFIED` (44-46), `classify_fact_provenance` (112), `independent_roots_count` (129), `classify_origin_class` (160), `plan_correction` (255), `read_policy_rank` (288).
- Отсутствует: `SemanticConceptView`/`SemanticRelationView`/`SemanticQueryPlan` как проекция, реестр терминов/версий смысловых определений, façade `resolve_semantic_terms|get_typed_relation_view|expand_claim_evidence|explain_choice`. `nodes.entity_type` ограничен `user|topic|event|fact` (см. ТЗ §5.3) — новые типы не вводить.

## 4. QAN-01 — реальность HEAD

- `services/mca_random_source.py` (2305 стр.): `AnuClient` (382), `RandomStore` (636, reserve_draw 727 / reserve_chunk 682), `ExplorationPolicy` (1007), `RandomSourceService` (1283) с `selected_mode/fallback_enabled/exploration_probability`, `resolve_effective` (1448), `draw_index` (1492), `choose` (1577), `activate` (1801), `test_connection` (1873, singleflight), `refill_if_needed` (1941), `status_snapshot` (2096), `quota_snapshot` (2138), `for_dream` (2293).
- Purpose-реестр (73-116): `less_studied_periods|sleep_after_consolidation|conversation_variant|memory_recall|archive_sample|belief_review|association_pair|meme_trigger|initiative_trigger`, `SANCTIONED_DRAW_PURPOSES`, `purpose_sanctioned`. `services/mca_dream_random.py` — `PURPOSE_LESS_STUDIED` (31), `DeterministicUniformRandomSource` (48), `DreamRandomSource` protocol (38).
- Настройки: `memory.random_source`, `keys.random_quantum_*` (146-153), дефолты (155-164). Валидация endpoint жёстко прибита к ANU (`validate_endpoint` → `host != ANU_HOST` отклоняется, 306-330; `ANU_HOST` стр.168). `_resolve_key` (1354) читает `hot` → `settings.RANDOM_QUANTUM_API_KEY`.
- **Один провайдер.** LfDR/Lizaonair/IBM в коде отсутствуют (поиск по `services/*.py`, `config/*.py` — 0 совпадений). `qiskit`/`numpy` нет в `requirements.txt`. Нет IBM-пула, нет job-lifecycle, нет boxing `fresh|pooled|late_to_pool`, нет деления `direct|seeded|prng`.
- Есть PRNG-примесь в режимах: `MODE_QUANTUM|pseudorandom`, `memory.random_fallback_to_pseudorandom` (`DEFAULT_FALLBACK=True`, 156), `_as_mode` (1226) — это «продуктовый режим», который ТЗ запрещает как OFF/SHADOW-переключатель, но терпим как явный последний fallback (см. §6 открытый вопрос 1).
- Потребители: `meme_initiative.py:1321-1349`, `dream_worker.py:2225`, `mca_exploration.py:299-300,394,408,591,820`, `goodmorning_relay.py:216-234`, `initiative_observer.py:741` — все идут через единый сервис, что соответствует ТЗ.

## 5. Поправка: управление QRNG-провайдерами в админке

**Уже есть на HEAD:**
- Единый секрет-механизм: `services/chat_keys.py` (`mask_key_info` 74, `mask_chat_key_info` 84, `GLOBAL_SECRET_KEYS` 25, allowlist `BYOK_KEYS_WHITELIST` 20), глобальные секреты пишутся в `ConfigCache` + аудит `record_global_secret_audit` (176). Маска — `{configured,last4}`, raw не отдаётся.
- API: `GET /api/config/keys/own` (routes.py:1405, глобальная ветка 1418-1425), `PUT /api/config/keys/own` (1438; `scope=global` пишет `cache.set` + аудит 1466-1473), `DELETE /api/config/keys/own/{key}` (1503), `GET /api/config/keys/status` (1555), `_mask_secret` (306).
- «Проверить подключение» ANU: `POST /api/random/test` (routes.py:2891-2907) → `RandomSourceService.test_connection` (1873) — реальная партия, singleflight, draft-ключ не сохраняется, ошибка очищается.
- Фронт: маска `SECRET_MASK`/`hasSecretMask` (app.js:21-34), гашение неизменной маски (`_seedSecretMasks` 16332-16340, `saveKeyItem` 24609-24612), safe-PUT глобального секрета (`saveProviderSecret` 11322), проверка/статус (24643-24697), поля группы `keys_random` (index.html:6425-6450), каталог параметров (`param_catalog.py:1153-1170`, группа `keys_random` 489).

**Чего не хватает для поправки:**
1. Динамические поля по провайдеру. Сейчас `keys_random` — фиксированный набор ANU-полей (`provider/endpoint/api_key/plan/data_type/batch_length/buffer_max/refill_low_watermark/timeout`). Селектора `primary_provider`/`fallback_order` нет, IBM `token/instance/CRN`, LfDR/Lizaonair endpoints и `adaptive_wait_policy` отсутствуют. Показывать/скрывать поля по выбору провайдера нечем.
2. «Применить без рестарта» для нового провайдера: `RandomSourceService` кэширует единственный `AnuClient` (`_get_client` 1314-1329, `set_client` 1310) и конфигурируется из ANU-полей; смена провайдера/ключа не имеет точки пересборки адаптера. `_invalidate_provider_health` (routes.py:80, вызовы 1470/1497/1532/1551) инвалидирует только health-кэш LLM-реестра.
3. Диагностика по провайдеру: `status_snapshot` (2096) отдаёт только ANU (`anu_state`, `key_present`, `reserve_remaining`). Полей `provider_id/effective/config_status/last_valid_sample_at/probe_age_sec/circuit_state/ibm_*` нет. Нет фонового singleflight-probe по провайдеру.
4. IBM требует «проверить QPU job и попадание битов в пул» — пула и job-driver нет вовсе.

**Трудности, как факт (не догадка):**
- `validate_endpoint` (306-330) жёстко разрешает только `ANU_HOST` → для LfDR/Lizaonair/IBM нужен per-provider allowlist origin+path, иначе SSRF-guard заблокирует.
- `AnuError`/`AnuBatch`/`RandomStore` завязаны на ANU-семантику (`data_type uint8/uint16/hex8/hex16`, `MAX_HEX_SIZE=10`, 166-177). Единый пул под 4 провайдера потребует обобщения ключа партии, а не второй таблицы.
- `RANDOM_QUANTUM_API_KEY` читается и из `settings` (env) — это не «env-only провайдер», но adminka сейчас не может задать IBM/LfDR-параметры вообще, потому что их ключей в каталоге нет.
- Секреты ANU/IBM должны быть раздельными; сейчас один `keys.random_quantum_api_key`.

**Влияние на порядок:** поправка не меняет место эпика в очереди. Она расширяет `VMQ-Q0` (реестр провайдеров + per-provider settings/secrets/health) и `VMQ-U` (динамическая форма, маска, «проверить», переключение). Добавляет строки приёмки: `Q-01` (селектор+поля), `Q-02` (selected/effective/fallback), `S-01/S-02` (health/probe/IBM pool), `U-01/U-02`, плюс новые `Q-10` (per-provider settings persist/apply/restart) и `Q-11` (секрет: маска не перезаписывает, delete, замена, не в логи/API).

## 6. Таблица: компонент → изменение → сценарий → тест

| Компонент | Изменение | Сценарий | Тест |
|---|---|---|---|
| `smart_messages` + `voice_transcription._inject_memory` | Добавить `transcript_status/revision/updated_at` (аддитивная миграция существующим механизмом) | 2-3 голосовых, готовые до вопроса | Реальный payload Writer содержит оба текста с авторами |
| `media_readiness.is_media_dependent` | Учесть voice/video_note как зависимость; групповой резолв соседних медиа по Reply/дейксису/хронологии | «что думаешь про верхние голосовые?» без Reply | Fixture группы + payload source list |
| `_prepare_turn_media_evidence`/`_refresh` | Распространить существующий refresh-шов на голос (без второго пайплайна) | STT завершился между snapshot и Writer | Race-fixture: один ответ, без повторного STT |
| `chat_context.format_chat_context` | Инвалидация/перерисовка маркера при `ready` (сейчас только FTS reindex) | Старый кэш со `[медиа: voice]` | После ready контекст содержит текст |
| `mca_retrieval_context.retrieve` | +intent-классы `person_overview/relationship_history/temporal_change`; coverage-ступень перед expansion | «главные черты X за всё время» | 30-50 золотых кейсов, multi-period recall |
| `mca_retrieval_context` каналы | Переиспользовать `episode`/`community`/`subject`; новые каналы не вводить | старый конфликт двух собеседников | Покрытие периодов/тем |
| `mca_episodes` | +привязка к `subject_ref`/coverage; без нового LLM на реплику | эпизод из 2019 и 2024 не склеивается | Сегментация + counterexample |
| `dossier/lore/summary` views | Продольное представление как **derived** view поверх существующих | «что изменилось за два года» | edit/delete → stale/rebuild |
| `memory_contracts` | +`SemanticConceptView/SemanticRelationView/SemanticQueryPlan` как проекция существующих enum'ов | «Папаха/папаха», два одинаковых ника | Negative examples, ambiguity |
| `entity_resolver` | Принимает typed hint, остаётся единственным резолвером | ник = нарицательное | casefold не сливает |
| `relation_evidence`/`graphrag_provenance` | Валидация typed relation; legacy остаётся слабым hint | legacy-ребро без sources | Не verified без первоисточника |
| `mca_random_source` | Реестр 4 адаптеров внутри сервиса + `primary_provider`/`fallback_order` | переключение ANU→LfDR | Матрица 4 провайдеров |
| IBM driver | on-demand-first, adaptive deadline, late→pool, атомарные claims | primary=ibm без квоты | reason_codes: `not_submitted/skipped` |
| Чистота IBM-тракта | Никакого PRNG/seed-expansion на пути effective=ibm | аудит пути | code-path audit + replay бит-в-бит |
| Поле/аномалии | `attractor|void|power|blind_spot` + null-калибровка + multiple comparison | 50 ячеек, max-statistic | Property/stat тесты, PRNG-null |
| 6 потребителей | memory/nostalgia/sleep/deep_sleep/initiative/meme через общий API | e2e на каждый | 6 трасс `eligible→published/persisted` |
| События/UI | reuse `mca_events` + `status_service`; новые виджеты в существующих вкладках | реальные события | Browser: сеть ↔ БД |
| Settings/secrets | per-provider поля, маска, delete, «проверить», apply без рестарта | смена/удаление/замена ключа | API + UI + restart |

## 7. Дубли, которые эпик НЕ создаёт

Второй voice-пайплайн · второй STT-воркер · второй retrieval/`retrieve()` · вторую read-модель поиска · второй graph store/таблицу смыслов · второй random source/пул/счётчики · второй observer/Planner/Writer · вторую analytics-БД (только `mca_events`+существующие агрегаты) · новый routing-LLM · NVIDIA Auto Ontology/FastAPI/Next.js/pgvector как runtime · Mem0/Graphiti/Neo4j/OpenViking/Headroom в runtime · новый модуль секретов или настроек · новые `nodes.entity_type` (`personality_trait/meme/relationship`).

## 8. Конфликты с идущей работой

| В работе | Файлы | Что делать VMQ |
|---|---|---|
| MEMORY-07 корректировка (активация + качество: PROVEN/WEAK, provenance в источнике) — `c816e83c` только что лёг; ожидаются ещё правки качества | `services/memory_communities.py`, `memory_contracts.py`, `mca_retrieval_context.py`, `summary_memory.py` | **Ждать.** Не трогать эти 4 файла до закрытия MEMORY-07. Семантическая карта QAN (§6.5 ТЗ) зависит от стабильных сообществ — строить после |
| MEMORY-08 S1/S2 (контракт поискового ответа + read-модель) — `44a10e28`, S3+ впереди | `services/memory_search.py`, `web/api/cognitive_map.py` | **Ждать** по этим файлам; ONTO-проекция читает, не пишет |
| `MEM-06-RUNTIME` — `READY_FOR_LIVE` (postdeploy, наблюдение: факты теряют тексты в `retrieve(purpose=dossier, channels=("subject",))`) | `mca_retrieval_context.py` | Учесть в ONTO-C как входное ограничение; не «чинить» внутри VMQ, вернуть в MEMORY |

**Можно параллельно на разных файлах:** VOICE-01 (`handlers/voice_transcription.py`, `services/media_readiness.py`, `services/chat_context.py`, `services/database.py` — миграция) и QAN-ядро (`services/mca_random_source.py`, новый `services/qan_ibm.py`, `services/qan_providers.py`, `web/api/routes.py` — секция `/api/random/*`, `web/app.js`/`index.html` — блок `keys_random`) — при условии, что миграционный реестр сериализован.

## 9. Порядок (DAG) и владельцы

1. `VMQ-A` mapping — Architect (этот артефакт). ✅
2. `VMQ-V` voice P0 — Builder/Reviewer. Файлы: `handlers/voice_transcription.py`, `services/media_readiness.py`, `services/chat_context.py`, миграция `database.py`.
3. `VMQ-ONTO-A/B` контракты смыслов — Architect→Builder поверх `memory_contracts.py` (после MEMORY-07).
4. `VMQ-M1` эпизоды/продольные представления — Builder, **параллельно** с (3), разные файлы (`mca_episodes.py`/новый `memory_longitudinal.py`), тот же контракт.
5. `VMQ-M2 + ONTO-C/D` единый retrieval/Composer — Builder (один писатель в `mca_retrieval_context.py`), после (3)+(4).
6. `VMQ-Q0` ядро QAN + реестр провайдеров + per-provider settings/secrets/health — Builder; можно начинать раньше, подключать к retrieval только после (5).
7. `VMQ-Q1` шесть потребителей — Builder, после (5)+(6).
8. `VMQ-O/U` телеметрия и админ-UI — Builder/UI, после реальных событий из (2)/(6)/(7).
9. `VMQ-R` релиз — Reviewer + DevOps.

**Сериализовано (один писатель):** `services/mca_retrieval_context.py`, `services/memory_communities.py`, `services/memory_contracts.py`, `services/memory_search.py`, `services/mca_random_source.py`, `web/api/routes.py`, `web/app.js`, `web/index.html`, `services/param_catalog.py`, миграционный реестр `services/pg_db.py`/`database.py`, `config/settings.py`.

## 10. Внешняя блокировка: IBM QPU

**Можно и должно быть сделано без credentials:** все 4 адаптера и `RandomSourceService`-реестр; `primary_provider`/`fallback_order` и их персистентность; per-provider поля/маска/delete/«проверить»; реальные probes LfDR (`GET https://lfdr.de/qrng_api/qrng?length=N&format=HEX`, ответ `qrn` hex-строкой длиной `2*N`) и Lizaonair (`GET https://lizaonair.com/qrng/rand?min=&max=` c `Accept: application/json` → `{value}`; `GET /qrng/meta` → `seed_age_sec/counter/last_anu_ok_age_sec/last_anu_err`) и ANU; failover-матрица на контролируемых отказах; IBM job-driver, состояние `unconfigured`, полная форма событий (`attempted_fresh/job_submitted/late_to_pool/ibm_pool_claimed`), атомарные claims пула, восстановление после рестарта, чистота IBM-тракта (отсутствие PRNG в `effective=ibm` — проверяется code-path audit + replay); null/статистика, шесть потребителей, UI.

**Остаётся `BLOCKED_EXTERNAL` (не VERIFIED, не симулировать):** `Q-04` — реальные IBM shots с `is_simulator=false`, `job_id`, реальные bitstrings; `S-02` в части фактического QPU job/queue/quota; on-demand-first в реальном железе. При отсутствии токена честный статус `unconfigured`; остальные провайдеры работают; релиз не объявляется полностью завершённым.

**Известный внешний факт:** IBM Open Plan — исполнение через job/batch, sessions недоступны, batch TTL для Open = 10 минут (docs `quantum.cloud.ibm.com/docs/en/guides/run-jobs-batch`). Это подтверждает требование bounded wait и запрет `job.result()` без дедлайна.

## 11. Открытые инженерные вопросы (не human gate)

1. **Судьба `memory.random_source` = `pseudorandom`.** Рекомендация: оставить как явный последний локальный PRNG-провайдер с честной меткой (`prng_fallback`), но убрать как «режим продукта» — провайдер выбирается, функционал всегда активен.
2. **Хранение L1/L2/L3.** Рекомендация: derived-таблицы-индексы (`mca_episode_index`, `mca_subject_longitudinal`) с `source_fingerprint`/`derived_version`, атомарная активация по образцу `mca_community_builds`; не переиспользовать `lore_stories` как source of truth.
3. **Эпизоды без LLM на реплику.** Рекомендация: детерминированная сегментация уже есть (`SEGMENT_GAP/SOFT_GAP/REPLY_HORIZON`); LLM только для карточки hot-эпизодов в существующем maintenance.
4. **Хранение смысловых терминов.** Рекомендация: вычисляемая проекция + минимальные indexed derived rows только для версионирования (`semantic_revision`), без второй таблицы «онтологии».
5. **Стабильная карта QAN при меняющихся сообществах.** Рекомендация: карта строится от `episode`+`community` снимка по `build_id`; смена build → revalidate/abandon, не переиспользовать чужой ID.
6. **Параметры QAN (N, таймауты, пороги null).** Рекомендация: единый policy-конфиг с `policy_version`, значения подобрать измерением на VPS; никаких разбросанных констант.
7. **Где живут durable-агрегаты.** Рекомендация: `mca_events` + существующие агрегаты `status_service`/`analytics`; TTL событий не должен стирать знаменатель — агрегат отдельно.
8. **Replay.** Рекомендация: защищённый bounded-стор с ACL и retention, только биты+refs для тестового воспроизведения; raw энтропия и приватный текст не в общие логи.
9. **Единая точка пересборки провайдер-адаптера.** Рекомендация: `RandomSourceService.reconfigure()` — единственный путь применения admin-изменений, вызывается из PUT/DELETE секрета и из смены `primary_provider`; без рестарта процесса.
10. **Совместимость существующих ключей.** Рекомендация: `keys.random_quantum_api_key` остаётся ключом ANU; IBM получает `keys.ibm_quantum_token`/`keys.ibm_quantum_instance`; миграция не перезаписывает существующие значения, `keys.random_quantum_endpoint` остаётся ANU-endpoint (allowlist не расширяется до чужих хостов).

## 12. Классификация

`VMQ READY FOR PM LEDGER` — карта снята с реального HEAD, архитектурная развилка одна (где живут derived-слои L1–L3 и как пересобирается провайдер), внешний блокер только IBM hardware acceptance; очередь эпика не меняется, поправка по QRNG-провайдерам входит в `VMQ-Q0`/`VMQ-U` и не создаёт второго модуля настроек.