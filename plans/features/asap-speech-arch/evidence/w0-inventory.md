# W0 — Read-only инвентаризация речевой конфигурации PROD (2.58.110 @ a8d2a45a)

**Дата/время снятия:** 22.10.2026 ~09:55–10:10 UTC (локально +12:00, 22:0x).
**Метод:** 3 SSH-коннекта (одиночный nik, паузы ≥90с, без поллеров), только SELECT/чтение journalctl/systemd/git; записи в PG/файлы не выполнялись. Пароли/DSN не печатались.
**Raw-журналы (head/tail40, метки):** `OPENCODE_WORKFLOW_SCRATCH/asap-w0/probe*_out.txt` (не в git; содержит ники участников — не публиковать).

## 0. Состояние прода на момент снятия

- Код: `a8d2a45a` (release 2.58.110), git log: 2026-10-22 18:50:54 +1200; рабочее дерево чистое (только *.bak файлы).
- Процесс: systemd `admin_bot`, PID 455943, старт **08:08:39 UTC 22.10**; сегодня было ≥3 рестартов (~06:2x pid 434185, 07:26 pid 447331 — на нём deploy-миграция записала L1 07:26:44, 08:08 текущий).
- healthz по IP с машины агента не ответил (вероятно SNI-привязка домена Caddy); живость подтверждена journalctl (mca_events/llm_usage до 09:39 UTC).
- ENV: `UNIFIED_COMPOSER_ENABLED=1`; `SMART_VERBALIZER_MODES_ENABLED`/`MCA_CHARACTER_*` в .env отсутствуют → дефолты True.
- `FACTORY_SET_SHA256_12` кода 2.58.110 = **3507bd6f92eb** (guard «runtime==constant» по релиз-коммиту).

## 1. Фабричные тексты @ a8d2a45a (байт-точно, blob verified `git hash-object`)

| block | константа | sha256 (12) | chars | примечание |
|---|---|---|---|---|
| core.personality (soul02-author-full-v2) | `PERSONALITY_CORE_FULL_TEXT` | d98e72ec7926 | 2655 | «**Грубость.**» БЕЗ мата; абзац «**Важно:** … см. SOUL-16» присутствует |
| core.personality.compact (soul02-compact-v2) | `PERSONALITY_CORE_COMPACT_TEXT` | e0529832ba7c | 1775 | без мата |
| (историч.) PREV core full | `PREV_PERSONALITY_CORE_FULL_TEXT` | 040581a3b4b0 | 2835 | содержит «**Мат и грубость.**» — источник симптома владельца |
| direct.base.tool_phase (chat-canon-cfg07a) | `CHAT_SYSTEM_PROMPT` | 0fe9680ba280 | 5631 | = base + TARGET + STYLE_BLOCKS_SUFFIX (АНТИ-БОТ 6c1affb82004 + АСИММЕТРИЯ + ТИПОГРАФИКА 3270d0220360 внутри) |
| direct.base.l2_writer (verbalizer-canon-mca23) | `DIRECT_VERBALIZER_SYSTEM_PROMPT` | d0ef0d376fc3 | 1703 | «Ты — токсичный, саркастичный… (бот-абьюзер)… двача» + ТИПОГРАФИКА (обязательные `""`, запрет «») |
| direct.base.l1_planner (l1-planner-l1d) | `DIRECT_L1_PLANNER_SYSTEM_PROMPT` | ace6246bd360 | 4264 | новый L1D-канон 2.58.110 (поля delivery/target_message_id уже внутри) |
| summary.base.narrator (summary-narrator-r1028) | `SUMMARY_NARRATOR_SYSTEM_PROMPT` | f02b6ca755a4 | 1863 | «Ты — токсичный… бот-абьюзер и завсегдатай двача» — LEGFIX **не** в 2.58.110 |

`git merge-base --is-ancestor a1db2991 a8d2a45a` = false → канон LEGFIX **5086ba935081** (1788, без «двача») на прод НЕ доезжает (он в HEAD-мастере, ждёт следующего релиза).

## 2. Активные значения PG + effective (SELECT 22.10 ~09:55 UTC)

Хранилища: глобал — `bot_settings` (JSONB; `character.*`/`style.policy` cat=content, `prompts.*` cat=prompts), per-chat — `chat_profiles.chat_params->'overrides'`. Лестницы/история — `character.prompt_history` (items=1, provenance=1: только core).

| ключ | factory @110 | active PG (sha12/chars, updated) | effective | scope | расхождение |
|---|---|---|---|---|---|
| core.personality (full_text) | fac:d98e72ec7926 | **act:f59ba0f42a48 / 2327c** (doc rev 6, origin owner_edit, updated 22.10 08:04:26Z) | = active (не withheld) | global; chat-оверрайдов Core НЕТ в обоих чатах | differs (ожидаемо: правка владельца); «Мат и грубость» НЕТ; «SOUL-16» ЕСТЬ |
| core.personality.compact_text | fac:e0529832ba7c | поле пустое (document_field_absent) | = factory e0529832ba7c | global | нет |
| prompts.direct_chat_system_prompt | fac:0fe9680ba280 | **custom cf404931f84c / 5294c** (07.10, провенанса нет) | **withheld → cleaned factory act:7923178337b4 / 5562c** (stripped=4: legacy-сегменты сняты на сборке; «Разрешен мат», АНТИ-БОТ, ТИПОГРАФИКА маркеров в eff нет) | global (chat-оверрайдов нет) | UI/каталог покажет withheld-кастом; в LLM идёт cleaned-фабрика |
| prompts.direct_chat_verbalizer_system_prompt | fac:d0ef0d376fc3 | **custom 091115cadc28 / 1676c** (⚠ записан 22.10 **08:17:34Z МИМО реестра** — без провенанса; байты старого «Ты - токсичный…» канона) | **withheld → cleaned act:6d2fd1828476 / 1633c**, открывается «Ты получаешь ТОЛЬКО готовую справку в формате JSON» | global | ключевой W1-объект (§3.1) |
| prompts.direct_l1_planner_system_prompt | fac:ace6246bd360 | **act:ace6246bd360 / 4264c** (07:26:44Z, deploy-миграция) | = active = factory, known_canon | global | НЕТ — L1D-канон уже на проде |
| prompts.summary_narrator_system_prompt | fac:f02b6ca755a4 | **custom 43160d5f9c2c / 1850c** (28.09, без провенанса) | **withheld → cleaned act:8109cb81fcdd / 1787c** (без «токсичный/двача») | global | LEGFIX 5086ba935081 приедет только со следующим релизом |
| character.expression | PROFANITY_INSTRUCTIONS байт-в-байт (off/occasional/frequent); factory_default profanity=occasional | global doc rev 2 (22.10 09:11:16Z): **profanity=frequent, sharpness=sharp**, wit/verbosity=inherit; chat -1002661910336 override (20.10): **wit=high, sharpness=sharp, profanity=frequent**; chat -1004482340693 — нет override | chat1: wit=high(chat)/sharp(chat)/frequent(chat); chat2: sharp(global)/frequent(global) | global+chat1 | render global 2601d612404d (848c), chat1 2ea9d0b41706 (949c) — шапка «Выражение владельца…» (§1.4 → W1) |
| style.policy | пресеты (no_emoji/no_quotes/no_trailing_period) | doc rev 10 (22.10 08:13:31Z): 3 hard-правила (emoji off; кавычки «»„““”"'-class — запрет в обычной речи; точка в конце — срезать) + 3 soft | hint **eb7684a6a279** (321c) | global (chat-оверрайдов нет) | owner values — не трогать |
| fallback/suppression | suppress_legacy_speech + withheld_factory_governs; CFG07A_PAYLOAD_CLEAN_KEYS (7 ключей, вкл. tool_phase) | 3 withheld-кастома (см. выше) + chat1: prompts.summary_system_prompt custom 141016a95b95 (3484c, legacy-голова), verbilizer_default_mode=casual, cover_style/cover_style_id | withheld-кастомы в LLM не попадают | — | mode-блоки (verbilizer_mode_*, кастом 19.09) НЕ прочитаны — добрать в матрице W1 |

Все три withheld-кастома (cf404931f84c, 091115cadc28, 43160d5f9c2c) НЕ совпадают ни с одной ступенью `PROMPT_MIGRATIONS` (проверено хешами) → подлинные кастомы, резолвер их честно удерживает.

## 3. TRACE source-of-truth — ответ на вопрос владельца §5.2

1. **UI показывает ACTIVE, не factory**: `GET /web/api/speech.py /speech/core` отдаёт `editions.full.text = effective_prompt(pg_doc/chat_doc)` (документ по scope из заголовка x_chat_id), factory — отдельным полем.
2. **До 08:04 UTC** в `character.core.full_text` лежали байты v1 с «**Мат и грубость.**» (2835c = 040581a3b4b0; journal 08:04:26 «history +1 … chars=2835» фиксирует прежнее значение). Рестарты активные значения не переписывают → владелец в редакторе продолжал видеть абзац.
3. **Композер при этом уже играл фабрику v2**: манифест 06:26:36Z = `core:r5.d98e72ec7926` — guard **superseded-core** (sha12 поля == 040581a3b4b0/ff28f0720a23 → подмена на factory в effective-слое, данные в PG не трогаются). Т.е. «UI старый / модель новая» — расхождение реальное, но в пользу чистой речи.
4. **08:04:26Z владелец сохранил правку через реестр** (write_speech_value): новая длина 2327c, sha f59ba0f42a48, provenance owner_edit persisted, doc rev 6. «Мат и грубость» из active УДАЛЕН — SELECT подтверждает (маркер отсутствует).
5. **08:19:11Z манифест боя** (инициатива, чат -1004482340693): `core:r6.f59ba0f42a48, style:g10.91619cc970eb, composer:on` — владельческий Core реально в payload.
6. **«см. SOUL-16» остаётся законно**: ремарка входит и в factory v2 (d98e72ec), и в текущую владельческую правку (маркер SOUL-16=true). Её снятие — задача W1 (§3.2/§1.4), а не следствие «несохранившейся» правки.
7. Кэш/процесс: текущий процесс стартовал 08:08:39Z (после core-правки 08:04); expression-правка 09:11 — инвалидируется по NOTIFY (`chat_params_updated`, TTL 120с) для чат-слоя, глобальный ConfigCache — по записям через API. Следующий деплой 2.58.111 всё равно плановый restart.

Итог: «владелец видел мат при factory v2» = активный документ v1-байтов + UI, показывающий active. Ничего не «сломано» сейчас: активный документ чистый, модель играет его же. Остаточная служебная ремарка SOUL-16 — известный W1-объект.

## 4. Конфликты в effective payload (факты 2.58.110)

1. **Core → «…см. SOUL-16»** — служебная ремарка в model-facing тексте (владельч. правка унаследовала её от фабрики). §1.4/§3.2 → W1.
2. **Verbalizer eff (6d2fd1828476) открывается «Ты получаешь ТОЛЬКО готовую справку в формате JSON»** — риск §3.1 для L2-путей без facts/answer_outline. → W1 P0-A.
3. **Expression-шапка «Выражение владельца — прямые директивы…»** — служебное описание в model-facing (§1.4) → W1 P0-D (тексты режимов frequent/occasional/off байт-в-байт НЕ трогать).
4. **Конфликт «запрет кавычек» vs «обязательные кавычки» в effective payload НЕ подтверждён**: cleaned-варианты tool_phase (7923178337b4) и verbalizer (6d2fd1828476) не содержат маркеров «кавычки»/««»»/«ТИПОГРАФИКА»; Style hint eb7684a6a279 в checked-текстах безальтернативен. Остаточный пробел: mode-блоки verbilizer_mode_* (PG-кастомы от 19.09) не сняты — закрыть в матрице W1 до правок.
5. Мат-разрешения из старых канонов в payload не доходят (stripped=4 на tool_phase; verbalizer/narrator — withheld). Expression frequent доставляется (render 2601d612404d/2ea9d0b41706).
6. Прочее из журнала: `[direct] extent-conflict scrub … stage=l2_writer removed=1` (07:54), `[direct] style policy pass | repaired=1` (07:54) — механики работают.

## 5. Готовность к W1/W2 — что именно мигрировать

1. `core.personality`: factory d98e72ec7926 → §3.2; активный f59ba0f42a48 — owner-preserving patch (снять только SOUL-16-ремарку), историю не терять (механизм history/provenance работает).
2. `core.personality.compact`: factory e0529832ba7c → §3.3 (поле пустое — замены фабрики достаточно).
3. `prompts.direct_chat_verbalizer_system_prompt`: factory d0ef0d376fc3 → §3.1; PG-кастом 091115cadc28 перезаписать через write_speech_value (провенанс!), прежние байты — в history.
4. `prompts.direct_chat_system_prompt`: factory 0fe9680ba280 → §3.6 (role-block); PG-кастом cf404931f84c — идемпотентный upsert на новую фабрику + провенанс.
5. `prompts.summary_narrator_system_prompt`: канон 5086ba935081 придёт с a1db2991 в следующем релизе; PG-кастом 43160d5f9c2c → новая фабрика (лестница PREV_SUMMARY_NARRATOR_LEGFIX уже в коде мастера).
6. `direct_l1_planner`: prod уже ace6246bd360 (L1D c формами участия) — W2 только верифицирует §3.7 без переписывания.
7. Expression: заменить EXPRESSION_HEADER/FOOTER (§3.4); значения frequent/sharp/high и тексты режимов сохранить; чат-оверрайд -1002661910336 не сбрасывать.
8. style.policy: owner-правила (rev 10) не трогать; перед правками канонов снять mode-блоки (verbilizer_mode_casual/serious/deep_research/default) и добавить в матрицу конфликтов.
9. Все withheld-кастомы либо погасить перезаписью с провенансом, либо осознанно оставить; иначе при изменении механизма withholding они «всплывут» в effective.

## 6. Runtime-свидетельства (последний Direct/Initiative)

- 08:19:05–08:19:11Z чат -1004482340693: L1 planner (deepseek/deepseek-v4.1-flash) → L2 writer → initiative_delivery_manifest `core:r6.f59ba0f42a48, style:g10.91619cc970eb, manifest:fd773ff20195adb0, composer:on`.
- 09:39:27Z чат -1002661910336: l1_planner вызов; l2_writer 08:49-й волны — attempts=1, fallback=False.
- Machine-stage compose честно отключает character-слои (`status=core:profile:machine_stage … disabled`); speech-композиция включает core/identity/expression/style_hint (манифест), few_shot/humor — source_missing (не настроены владельцем).
