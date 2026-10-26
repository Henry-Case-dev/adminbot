# P0 CORRECTIVE §2 — аудит всей цепочки имён/алиасов (LANE ALIAS-RUNTIME-AUDIT)

- Worktree: `C:\Code\Python\adminbot-wt-speech-p0`, HEAD `a97ba573` (`9650e099` + evidence).
- Дата: 2026-10-25. Режим: **read-only**, без прода, без LLM-вызовов, код не изменялся.
- Пункт ТЗ: `plans/features/asap-speech-arch/source-owner-p0-corrective-2026-10-25.md` §2.1–§2.3,
  отдельно строка 148 («установить источник имени "Гипербореец"»).

> Граница аудита: значения `limits.summary_aliases` в production `bot_settings` и
> `chat_profiles.chat_params` в этой линии **не читались** (запрет на прод). Поэтому
> источник «Гипербореец» ниже дан как ранжированное дерево причин + решающая
> read-only проверка (§3), а не как «подтверждённый факт». Всё, что утверждается о
> коде, подтверждено текущими файлами и `file:line`.

---

## 0. Итог

1. Единственный владелец порядка имён — `AliasResolver.resolve()`
   (`services/summary_aliases.py:163-198`): chat-алиас → global-алиас → nickname →
   username → `memory_name` → user_id. Порядок из §2.1 в нём реализован.
2. В Direct-рендере **все** блоки имён идут через резолвер: карта, окно
   `<Global_Context>`, `<Conversation_Thread>`, `<Conversation_Branch>`,
   `<Old_Episode>`, middle, `<Target_User>`, `<user_relations>`, L1-«УЧАСТНИКИ»,
   L1-окно, L2 `<Fresh_Chat_Window>`. «Второго резолвера» в речевом контуре нет.
3. «Гипербореец» может попасть в ответ **пятью** разными путями (§3). Два из них —
   не кеш и не резолвер, а **конфиг** (чатовый override важнее глобального) и
   **исторический текст** (конспект/RAG/лор/старые ответы бота).
4. Найдено 8 конкретных дефектов (§4). Ключевые: L1 reply-блок берёт имя из
   Telegram-ника, а не из алиаса; Observer/Initiative несут историческое
   `author_name` в `goal`; фоновые воркеры живут на стартовом снапшоте
   глобальных алиасов (без чатовых override и без инвалидации); шаг каскада
   `memory_name` не вызывается ни из одного места.
5. Минимальные точки исправления — только существующие механизмы (§5), тестовые
   пробелы по 11 пунктам §2.3 — §6.

---

## 1. Карта владельцев имени (кто и что решает)

| Компонент | `file:line` | Роль |
|---|---|---|
| `_coerce_alias_payload` / `parse_alias_map` / `merge_alias_maps` | `summary_aliases.py:38-97` | JSON/двойное кодирование, ключ = `str(int(user_id))`, пустые значения отбрасываются (77-84) |
| `AliasResolver` | `summary_aliases.py:100-198` | `_aliases` (115), обратная карта `_by_name` с защитой от неоднозначности (119-128), `canon_name` (145-161), `resolve` (163-198), `_cache` (129) |
| `LiveAliasView` | `summary_aliases.py:201-232` | стабильный DI-объект: `resolve/canon_name/_aliases` → резолвер текущего asyncio-контекста, иначе `fallback` |
| `_TURN_ALIAS` + `bind_turn_aliases` | `summary_aliases.py:237-264` | per-turn/per-update резолвер в `contextvars` |
| `alias_scope_middleware` | `summary_aliases.py:267-298`, регистрация `bot.py:959` | per-update `bind_turn_aliases` (только Telegram-апдейты) |
| `build_alias_resolver(chat_id)` | `summary_aliases.py:329-393` | global (`hot.get`, 349) + chat override (`_read_chat_alias_layer`, 303-326), merge, `scope_report` |
| Стартовый снапшот | `bot.py:467-472` | `AliasResolver(hot.get(...))` → `LiveAliasView(fallback)`; **строится один раз** |
| Global-запись | `web/api/routes.py:1151-1269`, `services/config_cache.py:709-735` | `bot_settings` + in-memory `ConfigCache` (тот же процесс → hot) |
| Chat-запись | `web/api/routes.py:610-725`, `services/chat_params.py:407-497` | `chat_params.overrides` + `NOTIFY` + `invalidate_chat` (489-494) |
| Chat-кэш | `services/chat_params.py:234-300` | TTL `_CACHE_TTL = 120.0` (38), fail-open `{}` |
| `hot.get` | `services/hot_config.py:71-76` | только `ConfigCache`, без TTL |
| Direct Chat | `direct_chat_service.py:2267-2280` (`_refresh_turn_aliases`), вызовы 2288, 8963, 9075 | per-turn bind |
| Summary | `summary_generator.py:718-729` | per-run bind |
| Tool/Image/Memory-rebuild/Web | `tool_router.py:1733-1741`, `image_context_memory.py:278-292`, `memory_rebuild.py:359-365`, `web/api/chat_lore.py:580,835`, `oversight.py:62`, `stories.py:140` | `build_alias_resolver(chat_id)` по требованию |
| Наблюдатель | `initiative_observer.py` | **резолвера нет** (см. D2) |

---

## 2. Таблица «путь → имя → источник → приоритет → кеш»

Приоритет везде один и тот же (chat > global > nickname > username > id), различаются
**источник ника** и **кеш**.

| Путь (что видит модель) | Кто формирует | Источник имени | Кеш / актуализация |
|---|---|---|---|
| `<UserResolutionMap>` (Direct) | `direct_chat_service.py:8315-8322`, roster `8347-8397` | `aliases.resolve(uid, row.author_name, None)` (8385) | per-turn резолвер; строки режутся «с конца» под бюджетом (позже RAG/thread/global, 7618-7620) |
| `<Target_User>` | `5484-5488` ← `_resolve_name` `8897-8902` | alias → **живой** first+last → username → uid | per-turn |
| `<Global_Context>` строки окна | `_row_speaker` `8753-8760` → `_context_row_line` `8762-8779` | alias → `smart_messages.author_name` (снимок на момент записи) → uid | per-turn |
| `<Conversation_Thread>` / `<Conversation_Branch>` | `thread_chain` + `_row_speaker` / `_chain_line` `8807-8813` | то же | per-turn |
| `<Old_Episode>`, middle | `5812-5814`, `6263-6298` | то же | per-turn |
| `<Current_Question>` | `6729-6775` | имени нет | — |
| L1 «УЧАСТНИКИ» (`Говорящий`/`Адресат`) | `direct_l1.py:708-711` ← `4293-4307` | `target_name` (alias) / `bundle.addressee` (роль или alias, 6613) | per-turn |
| L1 «ОТВЕТ НА (reply/цитата)» | `direct_chat_service.py:4151-4166` | **`reply.from_user.first_name` напрямую, без uid и без alias** | — (**D1**) |
| L1 «ПОСЛЕДНИЕ СООБЩЕНИЯ» | `direct_l1.py:829-888` | `alias_resolver.resolve(uid, author_name, None)` (855-860) | передан `self.aliases` (4307) |
| Initiative L1 «Адресат» | `direct_chat_service.py:8985-9010` | alias по `addressee_user_id`, `author_name` только как ник | bind в начале `plan_initiative_decision` (8963) |
| Initiative L1 задача / L2 `<Initiative_Context>` | `9011-9019`, `9089-9097` | **текст `goal` от Observer** (сгенерирован по сырым `author_name`) | — (**D2**) |
| L2 Writer user-blocks | `_l2_write_answer` `4719-4840`, blocks из `_build_user_content` `5400-5560` | alias-aware блоки | per-turn |
| `<RAG_Memory>` | `summary_memory.py:1386-1437` | **текст факта дословно**; поле `author` (если есть) — историческое | по дизайну, имя не переписывается |
| `running summary` / `level-2` (голова `<Global_Context>`) | `direct_chat_service.py:5660-5695` | **текст конспекта, созданного при старом алиасе** | по дизайну |
| `<protected_facts>` / `<chat_lore>` / PG-лор | `7962-7981`, `7985+` | текст по **имени** (`get_protected_facts(..., user_name)`, `database.py:10417-10436`) | — (**D5**) |
| Global-алиасы | `hot.get("limits.summary_aliases")` | `bot_settings` | ConfigCache, hot-reload в том же процессе |
| Chat-алиасы | `chat_params.overrides` | PG-профиль чата | TTL 120 c + NOTIFY + инвалидация при `set_chat_params` |
| **Fallback `LiveAliasView`** | `bot.py:467` | глобальные алиасы **на момент старта** | **не инвалидируется** (**D3**) |
| Summary-контур | `summary_generator.py:718-729`, `_resolve_author` `4189-4195` | per-run резолвер (chat+global) | ок |
| Observer eval/digest | `initiative_observer.py:658-694`, `697-711` | **`author_name` из БД без резолвера** | — (**D2**) |
| Dream / Lore / Relations-воркеры | `bot.py:707,741,823-827`; `dream_worker.py:1231-1257`; `lore_worker.py:398-404,750-756`; `lore_compiler_service.py:350-358` | `LiveAliasView` → **стартовый снапшот**, chat override не виден | (**D3**) |
| Web (chat_lore/oversight/stories) | `build_alias_resolver(chat_id)` | chat+global | per request |

---

## 3. Почему «Гипербореец» мог выиграть — 5 причин и как их различить

| # | Причина | Механизм (`file:line`) | Когда верна | Чем подтвердить |
|---|---|---|---|---|
| **P1** | Чатовый override всё ещё содержит старое имя, а менялся глобальный | `merge_alias_maps` `summary_aliases.py:93-97`; chat перекрывает global (372-374) | `<UserResolutionMap>` показывает «Гипербореец — <uid>» | `py -3 manage.py diag aliases --chat-id <chat_id> --show-names` (`manage.py:799-809,1787-1935`) — печатает `chat_alias/global_alias/effective/source` |
| **P2** | Имя пришло из **исторического текста**: конспект, level-2, RAG-факт, лор, старый ответ бота | `5660-5695` (конспект), `1386-1437` (RAG дословно), `7962-7981` (protected/lore) | карта показывает **новое** имя, а «Гипербореец» встречается в тексте блоков | сравнить `<UserResolutionMap>` с текстом `<Global_Context>`/`<RAG_Memory>` в реальном payload (offline-harness, не прод) |
| **P3** | L1 reply-блок отдал ник автора цитаты, L1 смешал роли | `_l1_reply_block` `4151-4166` | «Гипербореец» в ответе относится к **цитируемому** сообщению, а не к адресату | в L1 payload есть `автор: <ник>` без `[user:ID]` |
| **P4** | Observer положил историческое имя в `goal`, дальше оно ушло в L1 и Writer инициативы | `658-694`, `9011-9019`, `9089-9097` | имя всплывает только в **инициативных** сообщениях | в `goal`/`<Initiative_Context>` есть имя; в `<Fresh_Chat_Window>` — новое |
| **P5** | Фоновый воркер (Dream/Lore/Relations) использовал стартовый снапшот | `bot.py:467-472`, `707`, `741`, `823-827` | «Гипербореец» попал в **факты/лор/кластеры**, а потом в RAG | после рестарта имя в новых фактах меняется; до рестарта — нет |

**Решающая проверка (2 шага, read-only):**

1. `py -3 manage.py diag aliases --chat-id <chat_id> --show-names` — если `effective`
   для нужного uid = «Гипербореец» и `source = chat`, то это **P1** (конфиг, не кеш);
   Direct честно использует действующее значение. Лечение — сброс чатового
   override («↪ глобальное») или правка именно чатового слоя, код менять не нужно.
2. Если `effective` = новое имя, а в ответе старое — снять payload (существующий
   offline-harness/`l1_input`-дамп) и посмотреть, в каком блоке живёт «Гипербореец»:
   `UserResolutionMap` (тогда P1), `Global_Context`/`RAG_Memory`/`protected` (P2),
   `ОТВЕТ НА` (P3), `Initiative_Context` (P4).

Кеш как причина **исключён** для прямого ответа: `_refresh_turn_aliases` вызывается
в начале хода (`2288`), `AliasResolver` собирается заново, `chat_params` инвалидируется
при записи (`chat_params.py:489-494`) и по NOTIFY (`303-315`). Остаточное окно — ≤120 c
TTL и только в мультипроцессном сценарии (сейчас процесс один).

---

## 4. Дефекты

### D1. L1 reply-блок не знает uid и алиаса
`services/direct_chat_service.py:4151-4166` — `@staticmethod _l1_reply_block` берёт
`reply.from_user.first_name` и не передаёт ни `user_id`, ни резолвер. В L1 уходит
`автор: Игорь` при карте `Гипербореец — 1001`; связать автора цитаты с участником
нельзя. Прямо нарушает §2.1 «не путать автора, автора цитируемого сообщения и
адресата» и пункт §2.3 «ответ на reply адресуется правильному человеку».

### D2. Observer и Initiative несут историческое имя
`initiative_observer.py:672,704` — `author_name` из `smart_messages` без резолвера
(в промпт окна и в промпт дайджеста), при этом `build_opportunity_row`/`goal`
(`831-871`) идут в `plan_initiative_decision` (`9011-9019`) и в
`generate_initiative_reply` (`9089-9097`). Итог: L1 и Writer инициативы видят имя,
которого уже нет в настройках; адресат при этом корректен (числовой
`addressee_user_id` → alias, `8985-9010`).

### D3. Стартовый снапшот — вечный и без чатового слоя
`bot.py:467-472` создаёт `AliasResolver` один раз и больше никогда; `LiveAliasView`
использует его как fallback. Фоновые потребители (`LoreWorker` 707, `DreamWorker`
741, `RelationsService` 823-827, `lore_worker.py:750-756`, `dream_worker.py:1231-1257`,
`lore_compiler_service.py:350-358`) не вызывают `bind_turn_aliases` и потому видят
**только глобальные алиасы на момент старта** — ни чатовых override, ни поздних
правок. Это и есть «`_aliases`/`_cache` сохраняют устаревшее состояние» из §2 ТЗ,
в наиболее точной формулировке: не per-turn резолвер, а fallback-снапшот.
`AliasResolver._cache` (`summary_aliases.py:129`) на этом инстансе тоже не
инвалидируется (per-key, без TTL).

### D4. Шаг каскада «имя из памяти» не реализован в runtime
`memory_name` объявлен (`summary_aliases.py:168,177-178,191-192`), но **ни один
вызов** его не передаёт (grep по `memory_name` даёт только определение). §2.1 п.5
(«достоверные сведения памяти — последний fallback») фактически не работает:
при отсутствии alias/nickname/username отображается `user_id`.

### D5. Protected-факты и `/clear`,`/forget` привязаны к имени, не к ID
`direct_chat_service.py:7962-7981` → `database.py:10417-10436` (`user_name = ?`),
`8062-8079` (`clear_direct_dialogue`/`forget_direct_facts` по `target_name`).
После переименования: свои protected-факты перестают попадать в payload (в RAG при
этом остаются старые), `/clear` и `/forget` не находят старые записи. Устойчивый ID
уже существует (`subject_ref_id`, `get_persona_card(..., user_id=)`,
`database.py:11008-11021`; `_person_scope_clause`) — используется только в досье.

### D6. `author_name` — это алиас, замороженный при записи
`handlers/summary.py:351-355` пишет в `smart_messages.author_name` результат
`_aliases.resolve(...)`, т.е. **алиас на момент сообщения**. Поэтому все
потребители, читающие `author_name` напрямую (`initiative_observer.py:672,704`,
`chat_context.py:135`, `nostalgia_prompts.py:138`, `mca_experience_jobs.py:412`,
`lore_worker.py:765,1272`), показывают исторический алиас. Это объясняет, почему
«Гипербореец» массово живёт в старых данных и почему переименование «не действует»
для этих путей, даже когда резолвер исправен.

Дополнительное следствие (не требует прода): **удаление** алиаса возвращает
замороженный алиас, а не актуальный ник. `_row_speaker` передаёт
`nickname = row.author_name` (`8753-8760`), а в этой колонке лежит прежний алиас
(`handlers/summary.py:351`). То есть после «убрать алиас» карта пуста, и окно/тред
показывают старый алиас, пока в БД есть строки, записанные при нём. Тест
`test_a8_delete_global_alias_returns_next_source` этот случай не ловит: в нём
`author_name` — настоящий ник, а не замороженный алиас.

### D7. Дискриминатор коллизий всегда «(#хвост)»
`direct_chat_service.py:8389-8395` вызывает `_collision_suffix(uid)` без username,
хотя сигнатура (`696-703`) и docstring (`8356-8358`) обещают «({username})».
UX-мелочь, но при двух «Лёха» модель видит `#1234` вместо различимого ника.

### D8. В историческом тексте имя не маркируется как историческое
`_alias_map_block` (`8315-8322`) — только пары «имя — uid», без указания, что в
конспекте/RAG/лоре могут быть прежние имена того же uid. Модель не имеет
инструкции предпочитать карту; пункт §2.3 «старое имя из RAG/Memory не вытесняет
актуальный алиас» кодом не обеспечен (тексты намеренно не переписываются —
`summary_memory.py:1386-1437`, `direct_chat_service.py:5660-5695`).

---

## 5. Минимальные точки исправления (в существующих механизмах)

| # | Точка | Что сделать | Почему это не «вторая система» |
|---|---|---|---|
| F1 | `direct_chat_service.py:4151-4166` + вызов `4297` | сделать `_l1_reply_block` методом инстанса; имя = `self.aliases.resolve(reply.from_user.id, nickname, username)`, в строку добавить `[user:<id>]` | тот же каскад и тот же формат, что `render_window_lines` (`direct_l1.py:855-860`) |
| F2 | `initiative_observer.py:658-694,697-711` + `InitiativeObserverRunner` (`881-897`) | опциональный `alias_resolver` (как в `render_window_lines`): при наличии резолвить `row.user_id` | параметр-опция, без резолвера — прежний байт-в-байт вывод |
| F3 | `bot.py:707,741,823-827`; тики `DreamWorker`/`LoreWorker` | в начале обработки чата вызывать существующий `bind_turn_aliases(chat_id)` (или `build_alias_resolver(chat_id)`) | это ровно та функция, что уже используют Direct/Summary |
| F4 | `_alias_map_block` `8315-8322` | +1 строка-инструкция: «в конспекте/памяти/лоре имена могут быть прежними — актуальное имя участника брать из этой карты по user_id» | расширение существующего блока, без нового блока/тега |
| F5 | `_build_protected_facts` `7962-7981`, `clear_user_dialogue`/`forget_user_fact` `8062-8079` | передавать `target_user_id` и читать/удалять по `subject_ref_id` при наличии (fallback — имя, как сейчас) | `subject_ref_id` и `_person_scope_clause` уже есть (`database.py:11008-11021`) |
| F6 | `summary_aliases.py:168-192` | либо заполнять `memory_name` из roster/`subject_ref_id`, либо убрать шаг из docstring | убирает ложный контракт, нового кода не добавляет |
| F7 (опц.) | `web/api/routes.py:758-789` | в `/direct/context-diagnostics` добавить R17-safe `alias_source` по uid из `_collect_aliases_diag` | диагностика источника имени без раскрытия значений |

Порядок по эффекту: **F1 → F3 → F2 → F4 → F5 → F6**. F1/F2/F3 закрывают
«имя в payload», F4 закрывает «старое имя из RAG вытесняет», F5 — переименование
без потери фактов.

---

## 6. 11 проверок §2.3 — покрытие и пробелы

Существующий файл: `tests/test_asap3_identity_aliases.py` (22 теста) + юнит
`tests/test_summary_aliases.py`.

| # | Требование §2.3 | Существующий тест | Статус | Что добавить |
|---|---|---|---|---|
| 1 | Локальный алиас > глобального | `test_a2_chat_alias_wins_only_in_its_chat`, `test_a3_partial_chat_map_inherits_global_aliases`, `test_a7_delete_chat_override_returns_global` | покрыто | — |
| 2 | Глобальный алиас > никнейма | `test_a1_global_alias_beats_nickname_username_memory` | покрыто | — |
| 3 | Никнейм > username | `test_summary_aliases.py::test_nickname_second`, `::test_username_third_without_at` | покрыто (юнит) | payload-тест на Direct не нужен, поведение ветки общее |
| 4 | Изменение применяется без рестарта | `test_a4_global_change_applies_next_turn`, `test_a5_chat_change_applies_next_turn_without_restart`, `test_a6_after_restart_saved_aliases_apply` | покрыто на уровне резолвера | `test_a19_background_job_sees_chat_override_without_restart` (D3) |
| 5 | Старый кеш не возвращает устаревшее имя | — (только A4/A5) | **пробел** | `test_a19` + `test_a20_startup_snapshot_not_used_for_chat_bound_paths` |
| 6 | Исторические упоминания остаются доступными для поиска | `test_a14_quotes_and_history_text_untouched` | частично (текст не переписан) | `test_a22_history_searchable_by_old_name` (FTS/поиск по старому имени + имена по alias) |
| 7 | Ответ на reply адресуется правильному человеку | — | **пробел** (D1) | `test_a17_reply_block_uses_alias_and_uid` |
| 8 | Упоминание третьего лица не подменяет адресата | косвенно `test_mca04a_provenance_round1027.py`, `test_mca18_memory_subject_block_b_round1042.py` | частично (атрибуция факта, не адресат) | `test_a25_third_party_mention_keeps_addressee` |
| 9 | Два похожих имени не объединяются | `test_a9_one_uid_many_historical_names_is_one_person`; `_by_name` ambiguity `summary_aliases.py:119-128`; same-name → `unresolved` `provenance.py:544-587` | частично | `test_a21_two_uids_same_display_not_merged` (одинаковое значение алиаса у двух uid) |
| 10 | Старое имя из RAG/Memory не вытесняет актуальный алиас | `test_a11_old_graphrag_name_does_not_override_in_resolution_map` | частично (только карта) | `test_a20_old_name_in_rag_does_not_replace_map_name` (текст RAG со старым именем + карта + инструкция F4) |
| 11 | Все пути (чат/analysis/Initiative/…) по одним правилам | `test_a13_direct_summary_tool_and_media_share_one_order`, `test_a13_initiative_l1_and_l2_use_alias_not_author_name`, `test_a16_harness_telegram_id_to_context_and_result` | покрыто, **кроме Observer** | `test_a18_observer_eval_uses_alias_not_author_name` |

Итог: 4 покрыто полностью (1-4), 5 частично (6, 8-11), 2 пробела (5 и 7).
Новые тесты (8 штук) закрывают ровно строки 5-11 без дублирования существующих.

---

## 7. Риски и границы

1. **Прод-конфигурация не читалась** → P1/P2 не подтверждены фактически. Без шага
   §3 любой вывод «это кеш» будет недоказанным; код показывает, что per-turn кеш
   актуализируется.
2. **Payload-артефакты не содержат текста имён**: `probes_full/raw_full_*.json`
   хранят только `chars`/`sha12` (`l1_input`, `user`), поэтому по текущему evidence
   источник «Гипербореец» доказать нельзя — нужен новый дамп с текстом (offline,
   без прода).
3. **F4 меняет объём payload** (одна строка в `<UserResolutionMap>`). Тесты
   проверяют только тег/порядок (`test_direct_chat.py:515,557,...`), но нужно
   убедиться, что бюджетные тесты (`2572-2605`) не полагаются на точный размер.
4. **F1 меняет L1 payload** (появляется `[user:ID]` в reply-блоке). Инвариант
   «reply-блок ≤400 символов» сохраняется, но нужен review на возможные
   snapshot-тесты L1-контекста.
5. **D6 — архитектурное следствие**, а не баг: `author_name` = алиас на момент
   записи. Полное устранение потребовало бы перечитать историю по uid; §2.2
   прямо запрещает массовую переписку истории, поэтому решение — резолв по uid
   в местах чтения (F1-F3) + маркировка (F4), а не миграция данных.
6. **D3 в одном процессе** проявляется только для фоновых воркеров; рестарт
   «лечит» симптом, поэтому дефект легко принять за «кеш» — в отчёте это
   разделено явно.
7. В этой линии **код не менялся**; все точки — предложения к следующему Builder-срезу.
