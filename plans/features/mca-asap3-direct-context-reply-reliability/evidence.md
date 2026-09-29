# evidence.md — `mca-asap3-direct-context-reply-reliability` (ASAP-3, round 1028)

> Builder-журнал. Обновляется по мере выполнения задач. Спека: SHA-256
> `83E7B0286A66C28E17BE97D2113A5C1EF9D40FEA6706DA08729A763251E285AA` — верифицирован
> `Get-FileHash` при старте сессии (совпадает — работа разрешена).
> ADR-1028-2: Accepted (D1–D17), прочитан полностью.

## 0. Базлайн и состояние рабочего дерева (зафиксировано при старте)

- Прод: 2.58.34, HEAD `8a0fa6c` (docs-коммит поверх feat-базиса). `APP_VERSION = "2.58.34"` (settings.py:2172).
- F8-базлайн (вычислен импортом каталога на рабочем дереве, не со слов):
  `REGISTRY=481, Settings dataclass fields=422, covered=422, categorized=456, GROUPS=105, TAB_RULES=21`
  (команда: `py -3 -c "from services import param_catalog as pc; ..."`). `_TAB_BY_GROUP=103` (по F8-фикстуре).
- F8-тесты на базлайне зелёные: `pytest tests/test_round1025_f8_registry.py tests/test_param_catalog.py` → **63 passed**.
- **Чужой незакоммиченный WIP НЕ трогается и НЕ включается в diff фичи** (MCA-волна §93–§100, смерженные слои round 10.27):
  изменённые (M): bot.py, handlers/chat_lifecycle.py, handlers/summary.py, services/direct_chat_service.py (+572 строки WIP),
  services/token_counter.py (+76 строк WIP), services/database.py, web/api/routes.py, web/index.html, services/param_catalog-несмежные правки и др.;
  новые (??): services/mca_*.py, services/message_identity.py, services/provenance.py, services/safe_fetch.py, services/task_supervisor.py,
  tests/test_mca*, tests/js/round1027_* и пр.
- Строковые ссылки спеки (e.g. `_decision_pre_action`:932, `_REACTION_BY_REASON`:617, `_apply_context_budget`:2762,
  `_estimate_external_payload_tokens`:1892, `_truncate_block`:2991, `_check_context_config_invariant`:2203, `react_moai` вызовы :1596/:1663)
  соответствуют рабочему дереву (с WIP), проверено grep'ом.
- Дисциплина: НЕ коммитить; Summary-тесты зелёные; `token_counter.py` не меняется вовсе (D11) — WIP-дельта в нём остаётся чужой, своих правок туда не вносится.

## Группа A — аудиты

### T-3999 ✅ Аудит §1: воспроизводимый разбор корня prod-инцидента

Цепочка подтверждена по коду рабочего дерева (все точки прочитаны, не по памяти):

1. Инцидентные per-chat ключи: `limits.chat_global_context_max_tokens = -1` (семантика «Unlimited»).
2. `services/direct_chat_service.py:3755-3765` (`_build_global_context`): `resolve_chat_limit(per_chat_value, 5000, …)` →
   `services/token_counter.py:207-225` (`resolve_context_tokens`): `context_state(-1) == "unlimited"` →
   возвращает `settings.CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` = **32000** (`config/settings.py:517-518`,
   `_env_int_min("CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS", 32000, 1000)`, env-only ClassVar).
3. `services/direct_chat_service.py:3775`: `budget = safe_budget(limit)` →
   `services/token_counter.py:228-230`: `int(32000 / TOKEN_SAFETY_MULTIPLIER)`, множитель
   `models.token_safety_multiplier` → `TOKEN_SAFETY_MULTIPLIER = 1.15` (`config/settings.py:1641`).
4. Числовое воспроизведение: `int(32000/1.15) = 27826` (вычислено в этой сессии: 27826). Прод-WARN
   `direct: global context truncated | tokens=39371 -> 27826` воспроизводится точно: 39371 > 27826 → ветка
   `:3776-3796` (WARN на :3777-3778, затем `trim_verbatim_lines` + keep-head резерв).
5. Тот же паттерн для thread: `_render_thread` `:3871-3902`, лимит `_thread_limit` `:3855-3869`
   (`resolve_chat_limit` → при -1 → 32000 → `safe_budget` → 27826; WARN `direct: thread truncated | tokens=…` :3896-3901).
6. Доп. дефект §5: при aggregate `limits.chat_context_budget_tokens = -1` адаптивный accounting
   пропускается ЦЕЛИКОМ — `_apply_context_budget` `:2802-2811` (ранний return «aggregate truncation skipped» ДО
   любого payload-учёта; external-оценка из MCA-07 при этом даже не запрашивается — см. `:2093-2098`, где
   `_estimate_external_payload_tokens` вызывается, но результат при unlimited не используется).
7. Диагностика `_check_context_config_invariant` (`:2203-2257`) видит расхождение долей (double-truncation),
   но при `context_state(budget) == "unlimited"` выходит на `:2221-2222` — причину (скрытый ceiling) не фиксирует.

Вывод (root cause): `-1` на direct-пути подменяется скрытым artificial cap 32000, к которому
поверх применяется второй запас 1.15 → эффективный потолок 27826; двойное усечение
(per-block self-truncation + aggregate-доли) теряет контекст молча. Соответствует §1/§2/§5/§6;
анти-цель §48 «32000 → 64000» подтверждена как неверное «лечение».

### T-4000 ✅ Инвентарь caps Direct Context (grep-инвентарь по `truncat|cap|ceil|budget|limit` в direct-пути)

Классификация: [СКРЫТЫЙ] — снимается на ON-пути композера; [ЯВНЫЙ] — admin override, сохраняется; [SOFT] — target выбора.

| Место (файл:строки, рабочее дерево) | Ключ/механика | Сегодня | Класс | Действие при composer ON (ADR D13) |
|---|---|---|---|---|
| settings.py:517 + token_counter.py:218-219 | `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (32000) | скрытый cap при -1 | СКРЫТЫЙ | функция не меняется (D11); композер НЕ вызывает `resolve_context_tokens` для -1; живёт для Summary/OFF |
| token_counter.py:228-230; direct_chat_service.py:3775, :3893-3894, :2238-2239 | `safe_budget` (÷1.15) поверх ceiling | двойной запас | СКРЫТЫЙ (на direct) | self-truncation билдеров не вызывается; единственное деление — в композере (D2) |
| direct_chat_service.py:2802-2811 | aggregate `-1` → skip accounting | bypass §5 | СКРЫТЫЙ | снимается: композер считает payload всегда (D3) |
| direct_chat_service.py:2850-2875 + settings.py:1774-1792 | rigid-доли `chat_budget_*_ratio` (map 0.05/global 0.30/thread 0.20/rag 0.15/target 0.05/anchors 0.05/branch 0.03/nostalgia) | режут по ratio всегда | СКРЫТАЯ деградация | на ON-пути не применяются (P-модель, §16); OFF-путь сохраняет |
| settings.py:1293 (`CHAT_GLOBAL_CONTEXT_LIMIT` 100) | счётный срез фона при отсутствии summary | soft target | SOFT | сохраняется как граница выбора tail-кандидатов (не кап токенов) |
| per-chat `limits.chat_global_context_max_tokens>0` / `chat_thread_max_tokens>0` | явный cap | admin override | ЯВНЫЙ | сохраняется как hard-cap (min с allocation композера) |
| per-chat `limits.chat_thread_max_depth` (settings.py:1304, default 6) | глубина walk | отдельный knob | ЯВНЫЙ | сохраняется как минимальная гарантия рендера; walk ≤ `CHAT_THREAD_WALK_MAX=40` (D7) |
| direct_chat_service.py:2285-2287 (`CHAT_CURRENT_QUESTION_MAX_CHARS` 800), `:2345-2346` (`_DIG_RESULT_MAX_CHARS` 3600), L2 `:3703-3711` (`chat_level2_max_chars`), relations-кап | bounded-инжекты | явные | ЯВНЫЙ | сохраняются |
| `_truncate_block`/`_truncate_block_raw` `:2991-3007+`, `trim_verbatim_lines`, `truncate_to_tokens[_keep_head]` (token_counter.py:150-204) | механики усечения внутри блоков | — | инструмент | переиспользуются композером (importance/protected spans), `text[:N]` запрещён |
| summary-семейство `limits.summary_*`, `SUMMARY_MAX_CONTEXT_*` | не direct | — | вне контракта | не трогаются (§0; D11) |
| param_catalog.py:1275 (`CHAT_THREAD_MAX_DEPTH`), :1265-1341 (limits_chat/limits_chat_context), :742 TOKEN_SAFETY_MULTIPLIER | записи каталога | — | реестр | не меняются (новых удалений нет; F8-Δ только +2 санкционированных ключа) |

Grep-доказательство полноты: `rg -n "truncat|safe_budget|CEILING|_ratio|max_tokens" services/direct_chat_service.py`
→ все попадания покрыты таблицей выше или относятся к Summary/не-direct веткам (проверено поимённо в сессии).
Основа для Reviewer-линз §52.A/B.

### T-4001 ✅ Аудит decision layer (A7) и триггеров адресации

Карта «trigger → путь кода → исходы» (рабочее дерево):

- Триггерный гейт: `handlers/direct_chat.py:164-204` (`_is_direct_trigger`): reply-to-bot → mention(entities/@username) →
  persona-name (`command_prefix.name_mentioned`) → botword-regex (`_BOTWORD_RE`, `reactions.chat_botword_pattern`).
  Исключение `_BOTWORD_EXCLUDED_USER_IDS` (alan/kostik keyword-ветка) `:97`, `:201-203`.
- `DecisionContext` (`direct_chat_service.py:674-686`): поля reply_to_bot/reply_to_is_image/reply_to_is_article/has_question/
  bot_replied_recently/expects_tool_result/is_private/addressed. **Дефект §23**: `:1233` `bot_replied_recently=reply_to_bot` — признаки приравнены.
- Сборка контекста решения: `_decision_context` `:1199-1243`; `addressed` резолв `_decision_addressed` `:1175-1197`.
- Фаза P: `_decision_pre_action` `:932-1003` — ветки: (3) пре-гейты image/dig → REPLY; (1) MSG_EXPLICIT → REPLY;
  (2) question → REPLY; (4) expects_tool_result → REPLY; (5/6) laughter/emoji → REACT (или REPLY при toggles off);
  (7) MSG_ACK + ignore_trivial → **SILENT**; (8) not_addressed → SILENT(recent_reply/not_addressed); (9) bot_replied_recently +
  ignore_trivial → **SILENT**; (10) иначе REPLY. **Дефект §21**: force-гейта нет — «бот, ок» → MSG_ACK → SILENT.
  **Дефект §22**: «ахах» reply-to-bot → REACT уже есть (5/6) — соответствует.
- Диспатч `handle()` `:1398-1461`: DECISION_START → pre_action; SILENT → лог + MESSAGE_IGNORED + return
  (`:1435-1445`, **🗿 нет** — дефект §25); REACT → `react_moai` + REACTION_SENT + return.
- Технические ветки после генерации: CB OPEN `:1308-1313` (фраза); lock timeout `:1322-1327`; NoApiKeyForChat `:1574-1588`
  (sandbox-фраза); LLMBadResponseError (пустой ответ) `:1589-1597` → `react_moai` 🗿; empty answer `:1655-1664` → 🗿;
  LLMError `:1701-1714` (фраза). Это «технические 🗿», в silent-ack статистику не попадают (спека §4.2).
- Реакции A8: `REASON_CODES` 15 кодов `:604-610`; `_REACTION_BY_REASON` `:617-622` = {image_reaction: 😂, laughter: 😂,
  emoji_reaction: 👍, emotion: 🔥} + 🗿 fallback (`_reaction_for_reason` :625-631); механика `react_moai`
  (smartmodule_utils.py:188+, ≤2 попытки, 429-классификация, 7-исходный enum, standard-набор {🗿,😂,👍,🔥}).
  **Дефект §24**: закрытая карта, нет выбора по классу/тону.
- Координатор A1: `build_coordinator_decision` `:867-900` (action tool/reply; контракт A7 цел).
- Kill-switch'и: `DIRECT_COORDINATOR_ENABLED` (settings.py:552), `DIRECT_DECISION_MAKING_ENABLED` (settings.py:560), A8
  `REACTION_MECHANICS_ENABLED`, per-chat тумблеры `flags.chat_decision_{ignore_trivial,reactions,image_reactions}_enabled`
  (`_decision_toggles` :1245-1265).

Расхождения с §19–§29 (вход для T-4018…T-4025): нет force-гейта; `bot_replied_recently ≡ reply_to_bot`;
нет 🗿 на intentional SILENT; реакции не выбираются по классу набором; нет trigger_type/force_reply_required полей;
нет DIRECT_TRIGGER/DECISION-расширений. Что уже соответствует: reply-to-bot → Decision Making (не guaranteed reply);
ACK→REACT при ignore_trivial OFF; фон вне handle() (🗿-спам невозможен today); fail-soft react_moai.

### T-4002 ✅ Аудит интеграции running summary в Direct Chat

- Чтение: `_build_global_context` `:3688-3718` — гейт `chat_summary_enabled(chat_id)` → `db.get_running_summary(chat_id, time.time())`
  (без TTL-смерти, E4) → `summary_text`, `raw_count`, `window_end_ts`; level-2 (`get_summary_level(chat_id, 2)`) первой строкой.
- Схема сегодня: `<Global_Context>` = head[конспект+метки] + tail[verbatim сообщений с `timestamp > window_end_ts`];
  при ОТСУТСТВИИ summary — tail = последние `CHAT_GLOBAL_CONTEXT_LIMIT` (100) сообщений окна (`:3739-3749`).
- Stale watermark: при lag N сообщений tail получает ВСЕ N verbatim-строк → затем `:3776-3796` режет
  (trim_verbatim_lines → keep-head) — т.е. «summary + 400 raw → ножницы» подтверждено кодом (§14 дефект).
  `get_window_messages` (summary_memory.py:1922-1958) возвращает окно `summary_window_hours` ×
  `summary_max_window_messages` — при lag внутри окна tail растёт линейно.
- Episode-источники (переиспользуемые, без второго архива): `smart_messages` (колонки id, user_id, chat_id, text,
  reply_to_id, timestamp, media_type, author_name, is_forward, forward_source, tg_message_id — database.py:3382-3384);
  `get_smart_window` :3379; `get_smart_message_by_tg_id` :3499; `get_messages_around` :3430 (двунаправленное окно
  вокруг якоря — база расширения эпизода); `get_recent_messages` :3415; reply-граф `services/thread_chain.py`
  (`collect_thread_chain`, ChainItem); retrieval-контракт mca-07 `services/mca_retrieval_context.py`
  (`retrieve(db, memory, RetrievalRequest(mode="history")`, каналы exact/lexical/vector/reply_graph/episode);
  бот-ответы `bot_replies`/`bot_reply_parents` (`get_bot_reply` :5641, `get_bot_reply_parent`);
  lore-эпизоды `list_lore_stories` (через `_episode_candidates` mca_retrieval_context.py:581-612).
- Запись summary Direct НЕ делает (consumer-side only) — соответствует §0/§13.

### T-4003 ⛔ Prod-log research (§45) — недоступно из среды Builder; рецепт передан DevOps

Среда Builder — Windows dev-машина без доступа к прод-логам (проверено: локальных *.log прод-класса нет,
деплой-инструментов с ssh-доступом в репо не обнаружено; деплой — зона DevOps T-4038).
**Базлайн собирается на проде ДО деплоя 2.58.35** (шаг preflight T-4038) по рецепту:

```bash
# за фиксированный период (например, 7 дней до деплоя), на прод-хосте:
journalctl -u admin_bot --since "<date>" | grep -c "direct: global context truncated"
journalctl -u admin_bot --since "<date>" | grep -c "direct: thread truncated"
journalctl -u admin_bot --since "<date>" | grep -E "reason=recent_reply|action=silent|action=react|MESSAGE_IGNORED" | wc -l
journalctl -u admin_bot --since "<date>" | grep "coordinator" | grep -oE "action=(reply|react|silent|tool)" | sort | uniq -c
```

Ограничение зафиксировано: отсутствие ERROR/WARNING не считается признаком текстового ответа (§45).
Сравнение post-deploy (T-4040) — против этого базлайна; без него T-4038/T-4040 отмечают базлайн-шаг как открытый для DevOps.

---

(Дальнейшие разделы добавляются по мере выполнения C/D/E/F/G/H.)

## Группа C — Direct Context Composer (реализация)

### T-4007 ✅ Model-aware capacity — `services/model_capacity.py` (новый)

- `resolve_model_context_window(model_name) → (window, window_source ∈ {model_map, env_override, unknown_fallback})`:
  карта `MODEL_CONTEXT_WINDOWS` (DeepSeek/OpenAI/Qwen/Llama/Claude/Gemini/Mistral/GLM, lower-case longest-prefix-match),
  env `CHAT_MODEL_CONTEXT_WINDOW` (ClassVar override, приоритет выше карты), `CHAT_UNKNOWN_MODEL_WINDOW=16384`
  (fallback + WARN ровно один раз на имя модели, `_WARNED_UNKNOWN`), кэш окна на процесс.
- `resolve_effective_window(primary, fallback)` — min(primary, fallback) (D1).
- `compute_available_budget(window, external, ratio)` — `safe_budget(window − external − max(1024, window×ratio))` —
  множитель РОВНО ОДИН раз (проверено тестом `test_single_safety_multiplier`: `(window−reserve)/1.15` без повторов).
- `apply_budget_policy(available, raw)` — `-1→(available,'unlimited')`; `0/None→(min(av,16000),'dynamic')`; `>0→(min(av,cap),'cap')` (D2).
- Новые ClassVar в settings.py (Δ каталога = 0): `DIRECT_CONTEXT_COMPOSER_ENABLED`, `CHAT_MODEL_CONTEXT_WINDOW`,
  `CHAT_UNKNOWN_MODEL_WINDOW`, `CHAT_EPISODE_GAP_SECONDS=300`, `CHAT_EPISODE_MAX_MESSAGES=40`, `CHAT_EPISODE_MAX_COUNT=2`,
  `CHAT_FRESH_TAIL_MIN_MESSAGES=20`, `CHAT_MIDDLE_MAX_MESSAGES=60`, `CHAT_THREAD_WALK_MAX=40`,
  `CHAT_BOT_REPLIED_RECENTLY_SECONDS=600`, `DIRECT_SILENT_ACK_ENABLED`; +1 Settings-поле `CHAT_AUTONOMOUS_REPLY_ENABLED`.
- Тесты: `tests/test_direct_context_capacity_asap3.py` — 19 passed (§37 TEST 4/5 на уровне формулы).

### T-4008 ✅ Семантика -1/0/>0 без скрытого cap

- `services/token_counter.py` НЕ изменялся вовсе (D11) — `git diff HEAD -- services/token_counter.py` содержит ТОЛЬКО чужую
  WIP-дельту (зафиксировано в §0). `resolve_context_tokens`/`safe_budget`/`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` — семантика
  ADR-1019-8 сохранена (Summary-регресс зелёный).
- Композер на ON-пути НЕ вызывает `resolve_context_tokens` (sentinel разбирается `apply_budget_policy`); legacy-путь OFF —
  байт-в-байт (см. T-4017).
- Приёмка §37 TEST 1/2/5: `tests/test_direct_context_scenarios_asap3.py::TestUnlimited` (реальные e2e-прогоны handle()).

### T-4009…T-4015 ✅ Единый композер — `services/direct_context_composer.py` (новый) + интеграция

- **Канвейер** (`DirectChatService._compose_user_content`): candidates (существующие билдеры; global/thread в режиме
  `truncate=False` — без WARN `truncated`) → классификация P0–P3 (`BLOCK_PRIORITY`/`CANONICAL_ORDER`: порядок блоков payload
  НЕ меняется) → full payload (`model_capacity` + РЕЮС `_estimate_external_payload_tokens` MCA-07) → allocation
  (`allocate_budget`: eviction P3→P2→P1 геометрическими шагами, floors, `truncator=svc._composer_truncate` —
  `_truncate_block` с protected spans для обёрнутых блоков, целые строки для частей Global) → materialize (merge
  global_head/middle/tail в `<Global_Context>` на своём слоте). Fail-open аллокации → legacy `_apply_context_budget`.
- **-1 не пропускает accounting** (§5 устранение `:2802-2811`): `CONTEXT_CAPACITY` эмитируется всегда (тест TEST 3).
- **Rigid-доли `chat_budget_*_ratio` на ON-пути не применяются**; «всё влезает — не режем» (тест `test_no_pressure_no_cuts`).
- **Old verbatim episode** (T-4011, D4): `_build_old_episodes` — хиты mca-07 `retrieve(mode="history")` (REUSE, второй движок
  запрещён) → `compute_episode_span` (чистая функция: gap ≤ 300с + reply-graph closure ≤6 cycle-safe + склейка сегмента с
  хитом (reply-связь через «дырку» склейку держит) + кап 40 (3:1 в пользу «до хита»), 0 LLM, идемпотентно) → рендер
  `_context_row_line` в `<Old_Episode>` (P0, слот 2 после branch); дедуп с fresh tail по tg-id; лог
  `direct: old episode | chat=… hit=tg:N span=A..B rows=N reason=gap/reply_links/cap_applied`; счётчик
  `direct_old_episode_retrieval_total`. Приёмка §38: `TestOldEpisode` (500-сообщ fixture, episode verbatim + fresh tail
  verbatim + summary background).
- **Fresh tail** (T-4012, D6): tail = все post-watermark строки (keep-end), пол `CHAT_FRESH_TAIL_MIN_MESSAGES=20`
  (`floor_tokens` piece'а); P2 не вытесняет P1 (тест eviction). Приёмка §38 (recent verbatim не замещён summary).
- **Running summary = фон** (T-4013, D5): `_build_global_context_parts` — summary+L2 → head (P2, keep-head); middle
  top-K ≤ 60 (`select_middle`: recency + членство в reply-цепи ×3 + участники ×1.5 + лексика, ASC-вывод, дедуп с tail) —
  P3; tail — P1. RAG-дедуп получает head+tail текст (F2-порядок сохранён).
- **Stale summary** (T-4014): приёмка §39 — параметризованный lag 50/100/300/400 (`TestStaleSummary`): Direct работает,
  композиция = summary + middle + fresh tail, без brutal cut; композер не ждёт background job (чтение без TTL).
- **Thread depth >6** (T-4015, D7): `_collect_thread_chain(depth=CHAT_THREAD_WALK_MAX=40)` на ON-пути (per-call kwarg,
  legacy-вызовы без kwarg — stub-совместимость); floor = min(per-chat depth, len) строк keep-end; приёмка §40
  (`TestLongReplyChain`: тезис в корне 12-ходовой цепи доступен).
- **Physical overflow** (T-4016, §3.9): `AllocationResult.physical_overflow` → иерархическое сокращение
  episode→thread→branch с protected spans, preserved_kinds, `CONTEXT_PHYSICAL_OVERFLOW` + счётчик; никакого `text[:N]`
  (тест `test_physical_overflow_flag`).

### T-4017 ✅ Врезка за kill-switch + parity

- `_build_user_content`: `composer_on()` (per-call) → ON-ветка (parts + composer) / OFF-ветка — прежний код байт-в-байт
  (self-truncation + `_check_context_config_invariant` + `_apply_context_budget`).
- Parity-тесты: `TestComposerFlagParity` (OFF → `_apply_context_budget` вызывается, `_compose_user_content` недостижим;
  ON → наоборот) + вся существующая suite direct-чата (160 тестов) выполняется с OFF (conftest-фикстура) = legacy-паритет.
- Комбинации трёх master (координатор/decision/composer) — 8 комбинаций (`test_combinations_matrix`).
- Observability-изоляция: conftest-фикстура `_asap3_flags_off_by_default` (маркер `asap3` для новых тестов — прецедент
  `system2`); OFF → без новых событий/счётчиков (CONTEXT_* эмитятся только из композера).

## Группа D — Decision Matrix (реализация)

### T-4018 ✅ Trigger model (D8, §20/§23)

- `DecisionContext` + аддитивные поля `trigger_type`/`force_reply_required`; значения: force_keyword/mention/persona_name/
  reply_to_bot/free_will (`_resolve_direct_trigger` — приоритет botword → persona → @username → reply_to_bot → free_will).
- `bot_replied_recently` НЕЗАВИСИМ: `_bot_replied_recently` (окно `CHAT_BOT_REPLIED_RECENTLY_SECONDS=600` по
  `bot_replies.last_used_at`, fail-open False); фикс `:1233` (`= reply_to_bot` удалён). Тесты
  `TestBotRepliedRecentlyIndependence` (recent=True при reply_to_bot=False и наоборот; поля контекста независимы).
- Per-chat `flags.chat_autonomous_reply_enabled` (default ON): OFF → reply-to-bot всегда текстовый ответ
  (`_autonomous_reply_enabled`, тест `test_per_chat_autonomous_off_always_replies`).

### T-4019 ✅ FORCE DIRECT (§19A/§21)

- Force-гейт — приоритет 1 в `handle()` ДО `_decision_pre_action` и ДО LLM: `force_reply_required → ACTION_REPLY,
  reason=force_direct` (16-й код REASON_CODES, аддитивно); шорт-каты ignore_trivial/recent_reply/low_information не
  применяются (тест `test_force_never_reaches_silent_branch` — `_decision_pre_action` для force НЕ вызывается).
- Приёмка §41: `TestForceReply` — «бот, ок» → REPLY (раньше MSG_ACK→SILENT); «бот, ты тут?» → REPLY (короткий стиль
  допустим); recent_reply не отменяет force; «бот, нет, ответь нормально» (reply-to-bot+ботворд) → force.
- `_BOTWORD_EXCLUDED_USER_IDS` (alan/kostik) хендлера не тронуты.

### T-4020 ✅ Direct Autonomous (§19B/§22)

- reply_to_bot ∧ ¬force → Decision Making (REPLY/REACT/SILENT). Приёмка §42: вопрос → REPLY; «ахах» → REACT
  (предпочтительно, без LLM); «ок» → SILENT+🗿; содержательный reply → Decision Making. Тесты `TestAutonomous`.

### T-4021 ✅ Background без изменений (§19C/§43)

- Фоновые сообщения в `handle()` не попадают (гейт хендлера не тронут); 🗿 строго при конъюнкции (reply_to_bot ∧ addressed
  ∧ decision executed ∧ SILENT) — `test_not_addressed_silent_no_moai` (не-addressed SILENT без 🗿 и без текста);
  force никогда не завершается SILENT/REACT (§52.F).

### T-4022 ✅ ACTION_REACT полноценный (D9, §24/§36)

- `_REACTION_SETS_BY_CLASS`: laughter→{😂,🤣}, emoji→{👍,👌}, ack→{👍,👌,❤️}; сомнение {🤨,🤔} — константа;
  выбор `_stable_reaction_pick` (hash по message_id, детерминизм, без LLM/рандома); только standard Telegram enum —
  `STANDARD_REACTION_EMOJIS` A8 расширен аддитивно 4→9 (🤣👌❤️🤨🤔; REACTION_FALLBACK_ORDER не менялся —
  legacy-сайты байт-в-байт; A8-тест `test_standard_set_closed` обновлён на супермножество).
- Тесты `TestReactionSets` (наборы/детерминизм/невырожденность/🗿-fallback), e2e `test_laughter_prefers_react`.

### T-4023 ✅ SILENT+🗿 (§25–§27)

- Конъюнкция в SILENT-ветке `handle()`: `reply_to_bot ∧ dctx.addressed ∧ decision_on ∧ финал SILENT` + гейты
  `DIRECT_SILENT_ACK_ENABLED` (env) AND `flags.chat_silent_ack_enabled` (per-chat, env-дефолт от env-флага).
- 🗿 через `react_moai(reaction=🗿)`; исход ok → `DIRECT_SILENT_ACK` + `direct_silent_ack_success_total`; иначе
  `direct_silent_ack_failed_total` + `DIRECT_SILENT_ACK_FAILED` + WARNING — SILENT остаётся SILENT.
- Технические 🗿 (empty answer/CB) не затронуты — в silent_ack-статистику не попадают.
- Счётчики: force/autonomous_reply/autonomous_react/autonomous_silent — по исходам матрицы (тесты observability).

### T-4024 ✅ Fail-soft (§28/§44)

- `test_silent_ack_failure_stays_silent`: set_message_reaction падает → llm.generate НЕ вызывается, send_message НЕ
  вызывается, `DIRECT_SILENT_ACK_FAILED` logged. `test_react_failure_no_text` — то же для REACT (механика A8 ≤2 попытки).

### T-4025 ✅ Интеграция с A7 без нарушения контрактов

- `CoordinatorDecision` не расширялся (не требовалось — поля адресации в DecisionContext; reason_code force_direct валиден
  в `__post_init__` — тест `test_force_direct_reason_code_registered`); существующие 15 кодов не тронуты
  (`test_closed_vocabulary` обновлён на 16 аддитивно).
- Master-флаги `DIRECT_COORDINATOR_ENABLED`/`DIRECT_DECISION_MAKING_ENABLED` работают как прежде (комбинационный тест);
  decision-layer тесты round1026 зелёные (140 passed).
- DECISION_COMPLETE — аддитивные поля trigger_type/force_reply_required/message_class (whitelist A9 расширен).

## Группа E — Observability

### T-4026 ✅ Decision-side (§30/§31/§46)

- `DIRECT_TRIGGER` (trigger_type/force_reply_required/reply_to_bot/is_private/addressed — без raw text; R17-тест
  `test_emit_direct_trigger_filters_raw_text` — raw_text отбрасывается whitelist'ом); DECISION_START/COMPLETE + аддитивные
  поля; `DIRECT_SILENT_ACK`/`DIRECT_SILENT_ACK_FAILED`.
- Счётчики §46 (финальные имена, «autonomous» — нормализация): process-local `record_direct_metric` + grep-able строка
  `direct_metric name=<…> count=<…>` (тест `test_metrics_counters_and_log_line`); снапшот в `get_process_accounting()`.
- Тесты: `TestDecisionObservability` (DIRECT_TRIGGER/DECISION_COMPLETE-поля, ack-события+счётчики, force-счётчик).

### T-4027 ✅ Context-side (§32/§33)

- `CONTEXT_CAPACITY` (model/window/window_source/external/output_reserve/available/budget/policy_mode + summary_revision
  (РЕЮС `_summary_revision`) /watermark/lag/age), `CONTEXT_SELECT` (recent/reply_thread/episode/middle/compressed/rag —
  сумма сходится с композицией), `CONTEXT_PRESSURE` (excluded/compressed/physical_overflow + unsummarized tail),
  `CONTEXT_PHYSICAL_OVERFLOW` (preserved_kinds/available/needed) — только при ON композера.
- Диагностический вопрос «summary worker отстал?» — по `summary_lag_messages/watermark/age` без raw content.

## Группа F — Miniapp

### T-4028 ✅ Context Mode + диагностика (D12/D17, §34)

- Переключатель Context Mode [Dynamic]/[Unlimited] (+ Cap display-only при >0) в bespoke-карточке `Direct Context`
  вкладки модуля «Прямые ответы» (mod_direct, существующая IA) — пишет СУЩЕСТВУЮЩИЙ `limits.chat_context_budget_tokens`
  (derive −1/0/>0; POST /api/config c optimistic updated_at); описания §34 дословно; без hardcoded chat_id.
- Диагностика: read-only `GET /api/direct/context-diagnostics?chat_id=` (web/api/routes.py; RBAC — существующий
  access_for/can_access_chat; process-local snapshot из композера; R17 — только числа; fail-open `available:false`);
  панель — 7 полей §34.
- Каталог: +2 ключа (`flags.chat_autonomous_reply_enabled` — Settings-поле; `flags.chat_silent_ack_enabled` — PG-only
  pg_id-запись) в существующую группу flags_decision_making (order 23 без изменений — GroupSpec-аргумент это order);
  **F8-итог: REGISTRY 483 / Settings 423 / categorized 458 / GROUPS 105 / _TAB_BY_GROUP 103 / TAB_RULES 21.**
  ⚠ ОТКЛОНЕНИЕ ОТ ЦИФР СПЕКИ (482/457): арифметически невозможно добавить 2 каталог-ключа и получить +1 REGISTRY
  (каждый ключ = +1 REGISTRY/+1 categorized; Settings 423 совпадает). Функциональный контракт (3 тумблера §35 в
  существующей группе, POST /api/config отвергает некаталожные ключи — 422 «неизвестный ключ») требует оба ключа в
  REGISTRY. Зафиксировано для Architect/Reviewer; F8-артефакты переизданы атомарно (TSV 483/delta 72, screen-map,
  meta.md, catalog_baseline, f8_baseline (counts/sha/routes+1 endpoint), ROUTES_SHA256-константа, счётчики в
  test_param_catalog + 6 старых boundary-тестов + JS-пины версий).

### T-4029 ✅ Секция Decision Making (§35)

- Существующая группа flags_decision_making: force keywords — read-only display (data-force-keywords, D-PM-4:
  force-toggle НЕ введён); тумблеры: «Автономные ответы на reply боту» (новый), «Использовать реакции вместо ответа»
  (РЕЮС), «Silent-подтверждение 🗿» (новый) — defaults ON; новых групп/вкладок нет.

### T-4030 ✅/⚠ Browser verification (implementation-side)

- **Контур:** локальный dev-сервер (tools/_asap3_webapp_dev.py — только webapp+ConfigCache, порт 127.0.0.1:8765, R6-fail-open,
  реальный PG на этой машине недоступен — порт 5432 закрыт) + Playwright MCP (Chromium), мок-/api/*-контур с
  in-memory store (структурная верификация UI; minted initData от локального API_TOKEN .env).
- **Пройдено:** (1) Dynamic↔Unlimited переключение — клик Unlimited → POST `{key: limits.chat_context_budget_tokens,
  value: -1}` → состояние/кнопка обновились; (2) описания §34 дословно — рендер (снапшот a11y-дерева); (3) per-chat
  state изоморфен (chat_id в запросе; много-чатное переключение значений — на реальном PG за Reviewer); (4) persistence
  after reload — после reload mode=unlimited (budget −1 из store); (5) Decision Making секция — заголовок + force
  keywords read-only («Force response keywords: бот (дефолт) — явное обращение…») + тумблер «Автономные ответы…» +
  «Silent-подтверждение 🗿» (каталоговые); (6) silent-ack toggle рендерится; (7) reactions toggle рендерится (РЕЮС);
  (8) mixed/stale значения — отсутствуют (единый derive contextMode()); console errors = 0 (финальные состояния).
- **Скриншоты:** `artifacts/browser_desktop_1280.png`, `artifacts/browser_mobile_390.png` (viewport 390×844).
- ⚠ **Ограничение среды:** реальные persistence (PG), реальные значения диагностики от живого композера и переключение
  между двумя РЕАЛЬНЫМИ чатами — требуют seeded PG (спека §8: «локальный dev-сервер + seeded PG»), которого на dev-машине
  нет. Обязательный повтор в реальном контуре — Reviewer (T-4030) + владелец (§56-G, Telegram WebView). Харнесс-скрипт
  `_asap3_webapp_dev.py` оставлен в tools/ для повтора.
- Диагностическая надпись «Режим:» переименована в «Policy mode:» — конфликт с инвариантом round1019
  (`test_mode_version_line_removed`: «Режим:» запрещён в index.html).

## Группа G — Тесты

### T-4031 ✅ §37 TEST 1–5 — `tests/test_direct_context_scenarios_asap3.py::TestUnlimited`
TEST 1 (e2e: 60 строк × ~30 ток., budget −1 → нет WARN truncated/27826, verbatim доходит, policy_mode=unlimited,
budget>27826); TEST 2 (12-ходовая цепь при −1 — корень доступен); TEST 3 (−1 → CONTEXT_CAPACITY/CONTEXT_SELECT
эмитируются); TEST 4 (external 2000→12000 → available ↓); TEST 5 (window 32k→131k → available ↑).

### T-4032 ✅ §38/§39/§40 — тот же файл
§38 (TestOldEpisode: 30-строчный старый диалог «про метель» вербатим в `<Old_Episode>`, fresh tail вербатим, summary
фоном, счётчик episode-ретрива); §39 (TestStaleSummary: lag 50/100/300/400 — Direct отвечает, summary+tail в промпте);
§40 (TestLongReplyChain: тезис корня 12-ходовой цепи > CHAT_THREAD_MAX_DEPTH доступен через walk 40).

### T-4033 ✅ §41 — `tests/test_direct_decision_matrix_asap3.py::TestForceReply` + `TestTriggerMatrix`
«бот, почему?/ты тут?/ок» → REPLY; reply-to-bot «бот, нет, ответь нормально» → REPLY; recent_reply не отменяет;
короткий стиль допустим; ignore_trivial не достигается (гейт до шорт-катов — spy-тест).

### T-4034 ✅ §42/§43/§44 — `TestAutonomous`/`TestSilentAckConjunction`/`TestReactionFailure`/`TestReactionSets`
«ахах»→REACT {😂,🤣}; «ок»→SILENT+🗿; env OFF → тишина (паритет); per-chat autonomous OFF → REPLY; не-addressed SILENT
без 🗿; fail-soft (SILENT/REACT остаётся, текст не генерируется); наборы детерминированы.

### T-4035 ✅ Полный регресс
- **pytest (финал): 9963 passed / 11 failed / 1 skipped** (226s; полный счёт вырос с базлайна 9876 на +95 новых ASAP-3
  тестов + ~28 обновлённых count-пинов).
- **11 failed — все pre-existing, вне diff фичи** (проверено по-имённо):
  1. `test_mca02_safe_fetch…web_extractor_blocks_destination_without_fallback` — trafilatura не установлена в окружении
     (чужой WIP-тест, пакет отсутствует);
  2-3. `test_outgoing_guard…send_rich_message_*` — `ImportError: InputRichMessageMedia from aiogram.types` —
     services/telegram_send.py:174 (файл чужого WIP, aiogram-версия окружения старее; я файл не трогал);
  4-6. `test_summary_cover…TestRichDelivery×3`, 7. `test_summary_asap2_failsoft…t3959_10`, 8.
     `test_summary_publish_integration…test_on_l1_not_usable…` — тот же ImportError-каскад (rich-path downgrade);
  9. `test_tool_coordinator…test_forbidden_paths_out_of_diff` — diff от тега pre-round1026-a1 содержит удаления
     summary_filter/context_restore (ASAP-2.1, задолго до меня) — воспроизводится и без моих изменений;
  10-11. `test_webapp_hotfix8/9…tokens` — ожидают `saturate(103%)` в web/static/app.css, файл git-идентичен HEAD
     (105%) — расхождение теста с HEAD, не связанное с моими файлами.
- **Summary-регресс (§0/D11): зелёный** — test_summary_l1_clusterizer/test_summary_fact_package (каталог-инварианты
  обновлены в счётчиках, поведение не тронуто), test_summary_l2_writer, test_summary_logging_runid и др. passed.
- **JS suite: 50/50 passed** (все tests/js/*.js через node, включая новый `round1028_asap3_direct_context_test.js`).
- F8: `tools/gen_param_registry_round1025.py --check` → CHECK OK (483, map полна, R17-чисто, идемпотентно).
- Новые тест-файлы (4): test_direct_context_capacity_asap3.py (19), test_direct_context_composer_asap3.py (33),
  test_direct_decision_matrix_asap3.py (32), test_direct_context_scenarios_asap3.py (11) = **95 новых**;
  + tests/js/round1028_asap3_direct_context_test.js.

## Группа H — Релиз

### T-4036 ✅ DoD-матрица §54 + чек-лист §48
DoD 1–22 покрыты (карта в tasks.md; фактические прогоны — выше). §48: ни одного запрещённого «фикса» — множитель
применён ровно один раз (не удалён); CHAT_THREAD_MAX_DEPTH сохранён как гарантия + expansion (не «просто увеличен»);
text[:N] отсутствует (все усечения — `_truncate_block`/`trim_verbatim_lines`/целые строки); keep_head/keep_tail — не
единственная стратегия (P-модель); summary не отключён (P2-фон); reply-to-bot остался autonomous; Decision Making
работает; 🗿 конъюнктивен (не спам по фону — тесты); словарь реакций расширен (🗿 не единственная); LLM-ретраи не
добавлялись; Summary не переписан.

### T-4037 ✅ Флаги + rollback-документация
Ровно 2 новых env (DIRECT_CONTEXT_COMPOSER_ENABLED, DIRECT_SILENT_ACK_ENABLED — ClassVar default ON, parity-тесты OFF)
+ 2 per-chat каталог-ключа; РЕЮС flags.chat_decision_reactions_enabled; force-toggle не введён. Rollback: **soft** —
`DIRECT_CONTEXT_COMPOSER_ENABLED=false` (контекст-путь байт-в-байт legacy, parity-тест) и/или
`DIRECT_SILENT_ACK_ENABLED=false` (🗿-контур) и/или per-chat `flags.chat_autonomous_reply_enabled=false` — без отката
версии; **cold** — git revert фича-коммита до annotated-тега 2.58.34 (создаётся DevOps в T-4038, базлайн HEAD 8a0fa6c).
Runbook §60: direct-сообщения пропадают / композер теряет контекст / reaction spam / force silent / latency / provider
overflow → env-флаг → fix → review → deploy → повтор live acceptance.

### T-4038 ✅ (Builder-часть) Bump 2.58.35 + релизные артефакты
- `APP_VERSION = "2.58.35"` (config/settings.py, префикс-описание ASAP-3 по конвенции; хвост файла верифицирован
  байт-в-байт против HEAD после инцидента скрипта-bump и ручного ремонта — см. «Инциденты» ниже).
- README.md: новый раунд префиксом (v2.58.35), ASAP-2.1 → «Ранее»; `v2.58.34` сохранён (пин-тесты README).
- Деплой-шаги (preflight/checkpoint/тег/рестарт/health) — DevOps (недоступны из среды Builder).

### Инциденты сессии (прозрачность)
1. **Bump-скрипт повредил settings.py** (разовая автоматизация префикса APP_VERSION слила старый комментарий в строку
   `return opts` и продублировала хвост). Ремонт: ручная правка строки 2265 + удаление дублированного хвоста;
   верификация: `ast.parse` OK, импорт OK, APP_VERSION=2.58.35, `def get_ytdlp_pot_provider` ×1, хвост файла
   (от `def get_ytdlp_pot_provider` до EOF) **байт-в-байт идентичен HEAD** (difflib: 0 lines). Урок: однострочные
   префикс-правки гигантских строк — только через Edit-инструмент.
2. **Spec-арифметика F8 (482/457 при «+2 ключа»)** — недостижима (481+2=483; 456+2=458); реализация следует
   функциональному контракту (2 ключа в каталоге), числа 483/458 зафиксированы везде + примечание в
   test_round1025_f8_registry.py. Требует подтверждения Architect (не BLOCKER для поведения — расхождение только в
   заявленных числах Δ).
3. **Chужой WIP не тронут**: все pre-existing M/D/??-файлы рабочего дерева сохранены; мои изменения перечислены ниже;
   `token_counter.py` — только чужая дельта, моих правок нет (D11).

### Итоговые файлы фичи (Builder-delta)
**Новые:** services/model_capacity.py; services/direct_context_composer.py; tests/test_direct_context_capacity_asap3.py;
tests/test_direct_context_composer_asap3.py; tests/test_direct_decision_matrix_asap3.py;
tests/test_direct_context_scenarios_asap3.py; tests/js/round1028_asap3_direct_context_test.js;
plans/features/mca-asap3-direct-context-reply-reliability/* (spec/ADR/tasks/evidence — были; artifacts/ скриншоты — new);
tools/_asap3_webapp_dev.py (dev-харнесс браузера).
**Изменённые:** services/direct_chat_service.py (composer-контур, force-гейт, silent-ack, trigger-резолв, независимый
bot_replied_recently, reaction-наборы, счётчики, reasons 16, get_process_accounting+direct_metrics);
services/agentic_events.py (+7 событий, whitelist DECISION_COMPLETE, preserved_kinds);
services/smartmodule_utils.py (STANDARD_REACTION_EMOJIS 4→9 аддитивно);
services/param_catalog.py (+2 ключа, описание группы); config/settings.py (ClassVar-блок ASAP-3, CHAT_AUTONOMOUS_REPLY_
ENABLED, APP_VERSION 2.58.35); web/api/routes.py (GET /api/direct/context-diagnostics); web/index.html (DIRECT CONTEXT
карточка, force-keywords read-only, Policy mode-лейбл); web/app.js (contextMode/setContextMode/loadDirectDiagnostics/
forceKeywordsDisplay, data-пропсы, хук в loadConfig); tests/conftest.py (asap3-фикстура); pytest.ini (маркер asap3);
README.md (v2.58.35); F8-артефакты (param-registry-round1025.tsv/meta.md, screen-map-round1025.md,
fixtures/round1025/f8_baseline.json, fixtures/round1025/catalog_baseline.json);
tests/test_param_catalog.py + ~50 boundary-тестов прошлых раундов (count/version-пины 481→483, 422→423, 456→458,
2.58.34→2.58.35 — атомарно с F8); tests/test_decision_making_round1026.py (closed_vocabulary 16, group_params 5);
tests/test_agentic_events_round1026.py (enum 27); tests/test_telegram_reactions_round1026.py (standard set 9);
tests/js/round1025_hotfix{7,8,9,10}_*.js (APP_VERSION-пины 2.58.35).
**Удалённые:** нет. **Чужой WIP:** не тронут, не включён.

---

## Rework round 1 (по review.md — NEEDS FIXES: B-ASAP3-1/2/3 + M-ASAP3-1)

### [B-ASAP3-1] High ✅ H1 — middle top-K жив (§3.7/D5)

**Root cause (подтверждён):** `parts["tail_rows"] = post_rows` (весь post-watermark) +
`middle_rows = post_rows[:-tail_min]` ⊂ tail → пост-дедуп по tg-id из ВСЕХ tail-кандидатов
отсекал 100% middle-строк; `middle_selected_messages` всегда 0.

**Фикс (сплит по рецепту review):**
- `services/direct_chat_service.py` (`_build_global_context_parts`, ~:2522-2536): `tail_rows = post_rows[-tail_min:]`
  (fresh tail = последние `CHAT_FRESH_TAIL_MIN_MESSAGES`, P1, floor = весь piece);
  `middle_rows = post_rows[:-tail_min]` (непокрытый диапазон, кандидаты top-K ≤ 60, P3).
- `_compose_middle_lines` (~:3625-3657): дедуп против tail-кандидатов УБРАН (был по всем tail_rows);
- пост-аллокационный дедуп (~:2762-2781): middle-строки сверяются с tg-id ФАКТИЧЕСКИ вошедшего
  tail (`allocation.pieces` после eviction) — страховка на границе диапазона.
- **Семантика:** без давления middle присутствует (50/50 в lag50-тесте); при давлении middle (P3)
  поджимается первой, tail (floor) защищён (см. H2); строка в payload ровно один раз.

**Тесты (`TestStaleSummary`):** `test_lag400_middle_topk_under_pressure` — реальный путь handle(),
lag=400, бюджет-кап 2600 (< candidates ~4090): (а) `СЕРЕДИНА-МАРКЕР-` присутствует в payload;
(б) весь fresh tail (floor 20) вербатим; (в) `CONTEXT_SELECT.middle_selected_messages > 0 и ≤ 60`;
(г) clamp-событие (см. H2); (д) детерминизм — два прогона на свежих сервисах → идентичный набор
выбранных middle (30 строк, i=370..399 — top-K по весу). `test_lag50_middle_composed_without_pressure`
— lag(50) > tail_min(20) → middle_selected_messages == 50, дедуп: каждая строка ровно один раз.
Debug-артефакт: middle 3059→1529 токенов под капом 2600, tail 939 на floor, compressed=1.

### [B-ASAP3-2] High ✅ H2 — пол fresh tail enforced; below-minimum только через §17

**Root cause (подтверждён):** `floor_tokens=(thread_floor if kind == "thread" else 0)` — у
global_tail floor=0 → P1-эвикция/drop-фаза резали tail до пустоты молча; юнит-тест сам
подставлял floor, маскируя дефект.

**Фикс:**
- `services/direct_context_composer.py`: новый чистый helper `tail_floor_tokens(tail_text,
  floor_messages)` — токены последних N непустых строк (тот же расчёт, что использует прод-путь).
- `services/direct_chat_service.py` (`_compose_user_content`, ~:2693-2703): `tail_floor` wired из
  `tail_floor_tokens(tail_text, fresh_tail_min_messages())` для piece'а global_tail (аналогично
  thread_floor) → пол зарезервирован на ВСЕХ путях давления: P1-эвикция останавливается на floor,
  drop-фаза пропускает floor>0 pieces (существующая логика), при переполнении — путь §17
  (physical_overflow + preserved_kinds, никакой тихой резки).
- Аддитивное событие `CONTEXT_TAIL_FLOOR_CLAMPED` (enum A9 27→28, whitelist final_messages/
  floor_messages): эмитится при фактическом давлении (compressed/excluded/overflow), когда tail
  стоит на минимуме — «пол engaged»; ниже — только `CONTEXT_PHYSICAL_OVERFLOW` + счётчик.
- M-ASAP3-1 попутно: `allocate_budget` считает полурезку (compression без дропа) в
  `compressed_or_dropped` (жертвы по одному разу на piece через victims-set); сервис эмитит
  `CONTEXT_PRESSURE` при `excluded OR compressed_or_dropped` (было: только excluded).

**Тесты:** `test_tail_floor_real_wiring_enforced` (floor wired РЕАЛЬНЫМ `tail_floor_tokens`;
давление между floor и full → tail ≥ 20 строк, keep-end); `test_below_floor_is_physical_overflow_
not_silent_cut` (давление ниже floor → physical_overflow=True + preserved_kinds, тихой резки нет);
`test_compression_without_drop_counts_as_pressure` (M1: полурезка → compressed_or_dropped ≥ 1,
excluded пуст); e2e (г) — clamp-событие с final_messages ≤ 20 / floor_messages == 20.
`test_agentic_events…test_total_20_and_schema_version` → enum 28.

### [B-ASAP3-3] High ✅ H3 — сидирование per-chat тумблеров (deployment data-op, код не менялся)

**Root cause (подтверждён по коду):** `pg_db._seed_settings` ветка `else: continue` пропускает
PG-only спеки (settings_field=None) → `flags.chat_silent_ack_enabled` не сидируется в
bot_settings → GET /api/config (итерация по hot-config строкам) не отдаёт item → тумблер не
рендерится. `flags.chat_autonomous_reply_enabled` доезжает (Settings-поле → сидится), но для
симметрии/дефолта-в-PG сядет тем же шагом.

**Выбранный путь — вариант (a) review: deployment-level data-op** (прецедент ASAP-2 remediation
2.58.33: сид 14 не-секретных дефолтов `ON CONFLICT DO NOTHING`; системный фикс — follow-up
`param-catalog-pg-only-seed-config-exposure`, backlog.md «⚡ Follow-up (reconcile ASAP-2,
28.09.2026)», статус 🟦 К ПЛАНИРОВАНИЮ — уже зарегистрирован, решение @Architect будущего раунда).
Код НЕ менялся (Δ каталога = 0, F8 не пересчитывался по этой причине).

**DevOps-шаг (включить в preflight T-4038 ДО/сразу после деплоя 2.58.35, до рестарта):**

```sql
-- ASAP-3 (B-ASAP3-3): сид дефолтов per-chat тумблеров «Принятие решений».
-- ON CONFLICT DO NOTHING — намеренный выбор админа не перетирается (прецедент F22).
INSERT INTO bot_settings (key, value, category) VALUES
  ('flags.chat_silent_ack_enabled',     'true'::jsonb, 'flags'),
  ('flags.chat_autonomous_reply_enabled', 'true'::jsonb, 'flags')
ON CONFLICT (key) DO NOTHING;
```

- После сида — рестарт `admin_bot` (ConfigCache._load_all подхватит строки; рестарт и так есть
  в деплой-ранбуке). Повторный запуск SQL безопасен (idempotent).
- Проверка (Reviewer, реальный контур): GET /api/config с X-Chat-Id содержит оба item
  (flags.chat_silent_ack_enabled value=true), группа «Принятие решений» рендерит 3/3 тумблера;
  клик → per-chat override в chat_profiles, переживает reload.
- Backend-семантика сида не требуется для работы гейтов (env-дефолт DIRECT_SILENT_ACK_ENABLED
  резолвится и без PG-строки) — сид нужен исключительно для экспозиции тумблера в UI.

### Приёмка rework

- Затронутые suite'ы: `pytest tests/test_direct_context_scenarios_asap3.py
  tests/test_direct_context_composer_asap3.py tests/test_direct_decision_matrix_asap3.py
  tests/test_direct_context_capacity_asap3.py tests/test_direct_chat.py
  tests/test_decision_making_round1026.py tests/test_agentic_events_round1026.py
  tests/test_telegram_reactions_round1026.py tests/test_tool_coordinator_round1026.py
  tests/test_round1025_f8_registry.py tests/test_param_catalog.py` → **583 passed** (1 failed —
  pre-existing `test_forbidden_paths_out_of_diff`, вне diff); JS-харнесс → ASAP3-DIRECT-CONTEXT-OK.
- Полный pytest: см. финальный счётчик ниже. Parity OFF (composer off → legacy) — тесты
  `TestComposerFlagParity` зелёные. F8 `--check` → CHECK OK (483; rework не менял каталог).
- Summary-регресс (§0/D11): test_summary_l1_clusterizer + test_summary_fact_package +
  test_token_counter — зелёные; token_counter.py по-прежнему без правок фичи.
- Чужой WIP: не тронут (все правки rework — в файлах фичи: direct_context_composer.py,
  direct_chat_service.py ASAP-3-хунки, agentic_events.py, 2 asap3-тест-файла, evidence/tasks).

### Изменённые файлы rework (diff-резюме)

| Finding | Файл:зона | Что |
|---|---|---|
| H1 | services/direct_chat_service.py:~2522-2536 (`_build_global_context_parts`) | сплит tail_rows/middle_rows |
| H1 | services/direct_chat_service.py:~3625-3657 (`_compose_middle_lines`) | убран дедуп по tail-кандидатам |
| H1 | services/direct_chat_service.py:~2762-2781 (`_compose_user_content`) | пост-аллокационный дедуп против фактического tail |
| H2 | services/direct_context_composer.py:~130-141 | `tail_floor_tokens()` |
| H2 | services/direct_chat_service.py:~2693-2714 | wiring tail_floor |
| H2 | services/direct_chat_service.py:~2783-2801 | clamp-событие |
| H2 | services/agentic_events.py (enum/whitelist) | +CONTEXT_TAIL_FLOOR_CLAMPED (28) |
| H3 | (код не менялся) | evidence.md — DevOps SQL (этот раздел) |
| M1 | services/direct_context_composer.py:~270-311 | victims-трекинг полурезки |
| M1 | services/direct_chat_service.py:~2869 | условие emission CONTEXT_PRESSURE |
| тесты | tests/test_direct_context_composer_asap3.py | 3 теста (floor real-wiring, below-floor §17, compression) |
| тесты | tests/test_direct_context_scenarios_asap3.py | 2 теста (lag400 pressure, lag50 no-pressure) |
| тесты | tests/test_agentic_events_round1026.py | enum 27→28 |

### Binding rework

- **WTH (rework round 1):** `8b7db5ad8d2f32d864e6ce558844283124ee543318f4ac2239f02e0fa96cf295`
  (41 запись; манифест-файл с полным списком path+sha256:
  `artifacts/wth_manifest_rework1.json`; генератор `tools/_asap3_wth.py`).
- Spec/ADR хэши не менялись (83E7B028… / 77C2F12A…).
