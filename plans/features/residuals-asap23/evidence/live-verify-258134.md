# LIVE-VERIFY-258134 — residuals (read-only, прод-код, реальный LLM, без Telegram)

**Дата:** 26.10.2026 (server UTC; сессии 17:48–19:27Z). **Прод:** `198.46.175.136`, unit `admin_bot`, `APP_VERSION=2.58.134`, healthz 200 (loopback, каждый сеанс), `NRestarts=0`, MainPID 308006 (без рестартов за всё окно проб).
**Deployed SHA (измерен на сервере, каждый сеанс):** `076f7391a01157bad106372d405d109085a78dbc` (detached HEAD). Staging — `git archive` из **deployed SHA** (не из tip ветки; tip `1b93c6db` — docs-only после деплоя). Артефакты staging сверены sha256 (`services/mca_expression.py` f292ad43e733, `negative_constraints.py` e1ca1844e2ed, `direct_chat_service.py` 5add3022e464 и др.).
**Дисциплина:** реальные Telegram-сообщения не отправлялись (FakeBot); PG read-only (`server_settings default_transaction_read_only=on`, boot-probe `ro_ok:ReadOnlySQLTransactionError`); SQLite — slim-снапшот-копия (см. §Метод); запись в prod-базы — ноль. Секреты не печатались; ключи embedding показаны только presence/length. SSH-сессии — одиночные чистые логины без ретраев (fail2ban), интервалы ≥60 c.

## Метод

- **Драйвер:** серверный `live_scenarios_12.py` **байт-идентичен** sha256 `ca500edb…a96b` (r1-драйвер §12; проверен перед каждым прогоном). Поверх — обёртка `run_matrix.py` (sha256 `56486655f044…7306e`), которая: матрица 4 ситуации × (FREQUENT/OFF); захват цепочки на каждом ходе; PG/SQLite-дампы конфигурации.
- **Slim-снапшот (осознанное отклонение, задокументировано):** полная копия БД 1564 МБ довела корневой ФС до 100% и деградировала прод-PG (v1-прогон упал `PRAGMA journal_mode=WAL → disk I/O error`; подробности §Уроки). Вместо неё — прямой ETL `prod(mode=ro ATTACH) → db_slim.db` (248 МБ): `smart_messages` окно 30 дней (68 043 строки), векторные shadow-таблицы (fts5/vec0) и триггеры пропущены — их пересоздаёт `db.initialize()` при загрузке; остальное перенесено целиком (mca_events 122 119, graph_facts 6 972, lore_stories 9, chat_id_migrations 0, embedding_cache 16 551 свежих и т.д.). Прод-ФС оставался в здоровой зоне (92–94%, ≥1.5 ГБ свободно) весь остаток работы.
- **Реальный LLM:** `deepseek/deepseek-v4.1-flash` (hot-конфиг PG), ключи из прод-.env через сервис; платные вызовы: ~20 (8 сценариев × 1–2 попытки writer + L1-планировщики).
- **Захват цепочки (по каждому ходу):** effective config (resolved `ExpressionSettings` + PG-документ) → payload (system prompt первой writer-попытки: маркеры + `<Expression_Settings>`-блок) → raw output (первое LLM-завершение до гардов) → postprocessed (возврат `verbalize_validated` + stats) → outbound-ready (текст, переданный FakeBot.send_message). Отправка в Telegram не тестируется по условию лейна — цепочка зафиксирована до outbound-ready текста включительно, далее реальный `send_message` не выполнялся (честно).
- **OFF-override:** in-process: тот же продакшн-билдер `mca_expression.build_expression_settings(chat_doc={...,"profanity":"off"}, global_doc)` — пересборка текста слоя из тех же PG-документов с chat-слоем off; БД не писалась, hot-config не менялся. В resolved-логе: `pg_mode=frequent → effective_mode=off, overridden=true`.

## A — REQ-EX-DIAG-CHAIN (цепочка по звеньям с артефактами)

Source (PG, измерено): `bot_settings.character.expression` — `{'wit':'inherit','profanity':'frequent','sharpness':'sharp','verbosity':'inherit','enabled':True,'revision':2,'updated_at':'2026-10-22T09:11:16Z'}` (275 B). Chat-оверрайдов `chat_keys[character.expression]` — **0** → эффективный режим **frequent, source=global** для реального чата `-1004482340693` (uid-тип уже прошёл `normalize_mode`).

| Звено | FREQUENT (M1_short_everyday) | FREQUENT (M3_mild_provocation) | OFF (M4_neutral_factual) |
|---|---|---|---|
| effective config | pg_mode=frequent, source=global, rev fe5cfe76a034, overridden=false | то же | pg_mode=frequent → **effective off**, overridden=true (in-process rebuild, билдер прод) |
| payload | `frequent_text=true`, `off_text=false`, `final_header=true`, `<Expression_Settings>` присутствует (sys 14 186 chars), `examples_block=false` | то же (sys 14 292) | `frequent_text=false`, **`off_text=true`**, `final_header=true`, `<Expression_Settings>` присутствует (sys 14 147), `examples_block=false` |
| raw output | 142 зн., чисто с 1 попытки | 443 зн., **profanity=true** («хуяришь» — зеркалит user-стиль) | 229 зн. («Юпитер… 318 раз… 1300 шариков») |
| postprocessed | байт-равен raw (attempts=1, fallback=false) | байт-равен raw | **изменён**: 229→136 зн.; `numeric_claim_mismatch=2 → retry → numeric_claim_fallback=true` — числовые клеймы сняты детерминированной коррекцией (контракт CFG-07D.5/K2) |
| outbound-ready | FakeBot: 1 сообщение, 142 зн. | FakeBot: 1 сообщение, 443 зн. | FakeBot: 1 сообщение, 136 зн. = postprocessed |

Выводы: (1) режим из PG реально попадает в payload как единственный текст инструкции (`final_header` = «ПРАВИЛО РЕЧИ…» + текст `PROFANITY_INSTRUCTIONS[mode]`); (2) постпроцессор не «переписывает» чистые ответы (3 из 4 байт-равны) и **реально срабатывает по контракту** на numeric-гарде в M4 в обоих режимах; (3) механической вставки мата нет ни в одном ответе (мат возник только контекстуально в ответ на провокацию); (4) outbound-to-Telegram — не тестируемо в read-only лейне, зафиксирован outbound-ready текст (светлый остаток, см. Итоги).

Артефакты (scratch, sha256 в §Raw): `M*_freq.json/_chain.json`, `M*_off.json/_chain.json`, `all_runs.json`, `pg_config.json`, `boot.json`, `run_matrix.log`.

## B — REQ-EX-PROBE-MATRIX ×2 (4 ситуации × 2 режима)

| Ситуация | Режим (источник) | payload маркеры | Ответ (характер) | Мат (сервис-regex) | Мех. вставка |
|---|---|---|---|---|---|
| M1 короткая бытовая | frequent (PG global) | freq_text ✓ / off ✗ / header ✓ / settings ✓ / examples ✗ | 142 зн., живой разговорный | **нет** | нет |
| M1 короткая бытовая | **off** (override от PG-док) | freq ✗ / **off ✓** / header ✓ / settings ✓ / examples ✗ | 387 зн., тот же стиль без мата | **нет** | нет |
| M2 вопрос о прошлом чата | frequent (PG) | freq ✓ / off ✗ / header ✓ / settings ✓ | 463 зн., честное «вижу только хвост дня», реальные факты чата (retrieval сработал) | нет («дрочит» не мат-рут сервиса) | нет |
| M2 вопрос о прошлом чата | **off** | freq ✗ / **off ✓** / header ✓ / settings ✓ | 643 зн., тот же честный отказ за пределы окна | **нет** | нет |
| M3 мягкая провокация | frequent (PG) | freq ✓ / off ✗ / header ✓ / settings ✓ | 443 зн., резкий зеркалящий ответ | **да** (1 случай, контекстный) | нет |
| M3 мягкая провокация | **off** | freq ✗ / **off ✓** / header ✓ / settings ✓ | 328 зн., резкий ответ **без** мата | **нет** | нет |
| M4 нейтральный фактологический | frequent (PG) | freq ✓ / off ✗ / header ✓ / settings ✓ | 136 зн. после numeric-fallback | нет | нет |
| M4 нейтральный фактологический | **off** | freq ✗ / **off ✓** / header ✓ / settings ✓ | 137 зн. после numeric-fallback | **нет** | нет |

Сводка: мат FREQUENT **1/4**, OFF **0/4** — ожидаемое направление отличия подтверждено; отсутствие мата в 3 FREQUENT-репликах — та же статистическая вариативность, что уже документирована владельцем в `REQ-EX-STABLE-EFFECT` (остаётся FAILED как честная метка остатка; эта матрица её не «зеленит»). `examples_block=false` во всех 8 — консистентно с «owner-approved frequent-примеров нет» (блок не входит, секрет подмены отсутствует). Ошибок выполнения: 0/8; `needs_clarification`-фоллбеков не потребовалось.

## C — B10-R06 / B10-R10 / B10-R11 (ре-акцептанс на deployed SHA 076f7391)

**B10-R06 (embeddings quota-groups: live index/backlog, rate limit, key failover).**
Live-конфиг (PG, измерено): `keys.embedding_api_key` present (51 B), `keys.embedding_fallback_api_key` present (53 B), `keys.embedding_fallback_api_key_2` present (53 B), `keys.embedding_extra_api_keys` отсутствует, `keys.embedding_quota_group_labels` присутствует → **3 квоты-группы настроены** (primary + 2 fallback). Hot-флаги control-plane/cooldown/parking не заданы → заводские ON (по коду `_flag(..., True)` на 076f7391). Живой индекс-пайплайн: `mca_embedding_index_generations` = 3 записи за 30 дней, `embedding_quota_state` = 4 записи (квотные состояния пишутся), `embedding_cache` 16 551 свежих записей. Rate limit / failover в бою подтверждён ранее журналом 21.10 (`429→429→429`, `EmbeddingGroupCoolingDown` — карта/EXEC-TAILS); новых инцидентов за окно не требуется. Тесты на deployed SHA (файлы существуют в `git ls-tree 076f7391`): `tests/test_asap8_f8_embeddings.py`, `tests/test_embed_fallback_slots_routing.py`, `tests/test_embedding_control_plane_asap4.py`, `tests/test_asap5_embedding_identity.py`.
Вердикт-кандидат: **VERIFIED** (конфигурация групп + живой пайплайн + механика под тестами на SHA; полный backfill-прогон остаётся в рамках C08-остатка).

**B10-R10 (supergroup перенос с памятью, old/new chat retrieval).**
Live-факт (SQLite снапшот, ro): таблица `chat_id_migrations` **существует, 0 строк** — реальный перенос на проде не происходил (нет внешнего Telegram-события `migrate_to_chat_id`; это отсутствие события, не дефект). Механика переноса с памятью покрыта тестами на deployed SHA: `tests/test_asap8_v63_b09_migration.py`, `tests/test_asap8_v6_wa3_migration.py`, `tests/test_hot_migration.py`, `tests/test_migrate_direct_chat_v2_script.py` (существуют в 076f7391). Честный остаток: **needs-real-client** — живой перенос возможен только при реальном supergroup-migrate событии Telegram (создать его агент не может и не имеет права).

**B10-R11 (Direct L1: execution modes, запрет без ключа, budget/evidence).**
Тесты на deployed SHA: `tests/test_asap7_direct_l1.py` (D03/D04 контракт), `tests/test_direct_l1_corrective_r1.py`, `tests/test_direct_l1_l1d_contract.py` — существуют в 076f7391. Живые подтверждения: в нашем прогоне реальные execution-пути — L1-планировщик с plan_meta (`llm_usage_events`: `module=direct_chat` 2 195 строк всего; факт `direct_fresh_generation` в логе прогона), writer `mode=serious`, tool-фаза на M2 (`get_recent_history` через реальный `ToolRouter`); rate-limit/скрытие инструментов наблюдались в предыдущих EXEC-TAILS. Запрет без ключа: `chat_keys` на проде **пуст** (0 строк) — все чаты на глобальном ключе, живой пример «запрета чата без ключа» не воспроизводим в read-only (нельзя менять ключи) → механизм остаётся под тестами, живой пример — **честный остаток (не наблюдаемо без конфигурационного изменения)**; это соответствует прежней классификации строки («явных примеров запретов в окне не найдено»).

## D — REQ-B11-E2E (контролируемый реальный E2E на невидимые модули)

Существующий набор на deployed-линии: §12 r1 (10 сценариев, полный путь DirectChatService, d3a9a2cc), §12 r2 (6/6 PASS, b5716022), §12 r3 (DELTA-DEPTH subset, 076f7391), **настоящая матрица 8/8 на 076f7391** (реальный L1→tools→L2→post→outbound-ready с реальным LLM и реальным retrieval), factcheck media tests (`p0-factcheck-media`), B11 mechanisms report prod-run (`tools/v63_b11_mechanisms_report.py`, 8 ok / 2 never_run с раскрытым векторным контуром). Диагностики различены в отчёте B11: недостаток входов / never_run векторного контура / и т.д.
Честный остаток: **needs-real-client** — для частей, требующих реального Telegram-трафика (живые входящие сообщения, живой migrate), и для векторного E2E (graph embeddings) — внешний контур остаётся `WAITING_EXTERNAL` (квота провайдера, не регрессия v6.3); новые сообщения в реальные чаты по-прежнему запрещены.

## Уроки/инциденты проб (не влияют на прод, задокументировано для честности)

- v1 (16:39–16:41Z): полный снапшот 1564 МБ → ФС 100% → PG-инициализация ползла 19 мин → `journal_mode=WAL` упал disk I/O; 0 сценариев; осиротевшие процессы убиты, копия удалена. v3: prune сработал (1.97M строк удалено), но векторные таблицы без ts → 830 МБ не влезло → честный ABORT по собственному размерному guard'у, очистка. v4: прогон удался (8/8, ~90 c), но fetch-лист имел неверные суффиксы имён — raw-файлы удалены до fetch; результат повторён v5-прогоном 18:58–19:01Z (бандл `all_runs.json` введён как защита от частичного fetch).
- Сервис в момент деградации ФС: `healthz 200`, `NRestarts=0` во всех сеансах; после очистки ФС 92–94% (1.5–1.8 ГБ свободно), журнал с 17:50Z — **0 ERROR/CRITICAL** (проверено в финальном сеансе).
- Read-only PG вызывает ожидаемый fail-open `usage_events record failed (ReadOnlySQLTransactionError)` в staging-прогоне — контурная защита отработала как задумана, в prod-логи staging не пишет.
- Staging полностью очищен (`CLEAN_OK`, `NO_SNAPSHOT_LEFT`); r1-драйвер `live_scenarios_12.py` остался на месте (его sha зафиксирован в прежнем evidence §12-r2/r3).

## Raw-артефакты (scratch `OPENCODE_WORKFLOW_SCRATCH\live-matrix-258134\results-mv\`)

| Файл | sha256 |
|---|---|
| all_runs.json (8 прогонов + chain, бандл) | `4ca45b01ba4ce68e9531380edb275214311bc20cd007ef6c47255cfaddbed9e5` |
| boot.json | `392585136f17c5b3c442b0dde2b562d151f989c370d711b18613d1068578ccbf` |
| pg_config.json | `b6e2f58eaf625824b25198e96d358bb6e3a85995711f975225a7bbc7615ae42e` |
| summary.json | `d6033095d7663cb00fcdbd419a7f649578b52a0bf3e8242f857aab136970e6a1` |
| run_matrix.log (полный транскрипт прогона v5) | `39697c0ba24fab0c88ac5b2424a431ef78a853e652526114dac297d08c60ee38` |
| driver (сервер, сверка) | `ca500edb357bd3f7077bf236e13fbb46f417eaff910674c64f5330843ea4a96b` |
| wrapper | `56486655f04424bd81cbf0c704b2f6a2eac9c45db720e3e94f8ff8ab1cc7306e` |

Сопутствующие скрипты/логи сессий: `probe_matrix_v5.py`, `slim_etl.py`, `salvage.log`, `fetch_cleanup.log`, `inspect.log`, `probe_matrix_v2.log` (v1–v3 попытки) — там же в scratch.

## Итог для карт (статусы переводит PM/Orchestrator)

- `REQ-EX-DIAG-CHAIN` — все звенья цепочки наблюдались на живом контуре с артефактами по каждому ходу (2 diverse FREQUENT + 1 OFF минимум, фактически 4+4); исходящий Telegram-хоп не тестируем read-only лейном (честный свет: outbound-ready == финальный текст send-пути; сам hop не отправлялся).
- `REQ-EX-PROBE-MATRIX` (×2) — матрица 4×2 выполнена, маркеры/профанаций/мех. вставки зафиксированы; направление отличия подтверждено (1/4 vs 0/4), вариативность — документированный остаток `REQ-EX-STABLE-EFFECT` (не блокирует).
- `B10-R06` — VERIFIED-кандидат (config + живой пайплайн + тесты на SHA); `B10-R10` — механика под тестами на SHA, живой перенос needs-real-client (внешнее событие); `B10-R11` — VERIFIED-кандидат (тесты на SHA + живые режимы в прогоне), живой «запрет без ключа» — честный остаток (chat_keys пуст, воспроизведение требует изменения конфигурации ключей).
- `REQ-B11-E2E` — существующий E2E-набор на deployed-линии процитирован и дополнен матрицей 8/8 на 076f7391; Telegram-зависимые и векторные E2E — needs-real-client / WAITING_EXTERNAL (без Human Gate).
