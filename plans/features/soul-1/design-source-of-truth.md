# SOUL-1 / ARCH-DESIGN — источник истины: Core, Speech Style Policy, Sample Library

- **Lane:** ARCH-DESIGN (read-only wrt app code). **Baseline:** master HEAD `a854ad95` + рабочее дерево на 2026-10-16.
- **Покрывает:** SOUL-15 §1–7 (единая схема источников, двухфазная миграция, права, hot apply, флаги, no-silent-degradation, размер/эффективность) + SOUL-16.1.4 (запись правила) + SOUL-02.1/02.7 (полный и compact Core, версии) + SOUL-09 п.9 для Sample Library (поля §8–§9 источника).
- **Не покрывает:** UI-вёрстку/Visual Preservation Map (владелец — W6, SOUL-10/11/16.5/17), исполнение правил на финальном тексте (W3), выборку примеров/фидбек (W4). Границы указаны в §7.
- Все поведенческие утверждения ниже проверены по коду, ссылки `file:line` в тексте. Утверждения из `audit-prompt-matrix.md`, которые я не смог подтвердить или которые устарели, перечислены в §8.

---

## 0. Решения (кратко)

| # | Решение |
|---|---|
| R1 | **Никакого второго config service.** Core, Speech Style Policy и политика выборки примеров живут в существующем контуре `bot_settings` (ключи/батч-транзакция `ConfigCache.set_many`, `services/config_cache.py:709-735`) + per-chat слой `chat_params.overrides` (`services/chat_params.py:344-377,407+`), RBAC и optimistic-конфликт — существующие (`web/api/routes.py:609-725`, `:2451-2620`). |
| R2 | Sample Library — **одна новая таблица** в существующем PG-контуре миграций (построчный CRUD, ревизия на запись, запросы по тегам/технике). Это единственная новая сущность хранения; обоснование в §3.4. |
| R3 | Один ключ = один JSON-документ сущности (Core; Style Policy) ⇒ «atomic save» получается бесплатно (одна строка/одна транзакция), версия — `revision` внутри документа + `bot_settings.updated_at` как optimistic-токен. |
| R4 | Миграция **не переписывает** ни один `custom_legacy`; супersession старых «токсичных» канонов делается детерминированной вычисткой известных слепков на сборке (прецедент `services/response_extent.py:478-498`), а не правкой PG. |
| R5 | Core **всегда аддитивный слой**; выбор «включать/не включать» — флаг композера + `enabled` в документе Core, а не новый env-рубильник. |
| R6 | Компактная runtime-редакция Core — **хранимая** (не LLM-пересказ на ходу), с измерением токенов и preview (SOUL-02.7). |

---

## 1. Единая схема источников (inventory)

Формат: `источник → (scope, owner, effective priority, migration, rollback)`.
`effective priority` — место в контракте уровней SOUL-03 (L1…L7, см. `design-composer-contract.md` §3).

### 1.1 Персона / характер (существующее, НЕ удалять)

| Источник | Где | Scope | Owner | Priority | Migration | Rollback |
|---|---|---|---|---|---|---|
| `personas.name/biography` | `services/bot_persona.py:60-67` (SQL), рендер `:300-305` | global + per-chat (`is_global`,`chat_id`) | владелец/admin чата | L3 идентичность | не мигрируется (остаётся как есть), Core рендерится **отдельным** слоем | нет (данные не меняются) |
| `personas.system_prompt_overrides` («Характер: …») | `bot_persona.py:304-305`, `mca_self_model.py:1779-1780` | global + per-chat | владелец/admin чата | L3 owner style | фаза A: классификация (core-эквивалент / custom_legacy); фаза B: **не перезаписывается** | сохранённое значение неизменно |
| `personas.is_aware_ai` | `bot_persona.py:312-313` (`_NO_AI_DISCLOSURE_BLOCK`), idx кадра `mca_self_model.py:1781,1810-1811` (`SELF_MODEL_FALSE_BLOCK`) | global + per-chat | владелец | L2/L3 (граница) | нет | нет |
| `persona_traits` | `bot_persona.py:104,383`, лимит `PERSONA_TRAITS_MAX` | global (пул), чтение per-run | производные системы (сон/legacy-parse) | L4 | нет (SelfModel сохраняется) | нет |
| `persona_state` (pause/resume, health) | `bot_persona.py:108`, `web/api/routes.py:2545-2589` | global | система/владелец | — | нет | нет |
| read-side слои `owner_core/owner_style/derived_traits` | `bot_persona.py:43-47` (`CHARACTER_LAYERS`, `CHARACTER_PRECEDENCE`) | global (read) | — | L3/L4 | **новый Core обязан стать содержимым слоя `owner_core`** (имя уже занято, второй сущности не создаём) | — |
| `flags.persona_enabled` | резолв per-chat `direct_chat_service.py:2357-2359`; default `settings.PERSONA_ENABLED` (`config/settings.py:2759`) | global + per-chat (`_cpg`) | admin (RBAC категории `flags`) | выключатель L3-блока | не мигрируется | OFF → ровно прежнее поведение |

### 1.2 `prompts.*` (25 читаемых ключей, 24 в каталоге → исправляется в рабочем дереве)

Читателей **25** (проверено grep по `"prompts.*"` в `services|handlers|web|config`, 94 вхождения), каталог `_PROMPTS` — `services/param_catalog.py:546-…`.
Ключ `prompts.direct_l1_planner_system_prompt` отсутствовал в каталоге на HEAD; в рабочем дереве он уже добавлен (см. §8.1).

| Группа ключей | Где читается | Scope | Owner | Priority | Migration | Rollback |
|---|---|---|---|---|---|---|
| `prompts.direct_chat_system_prompt` | `direct_chat_service.py:2344-2347` (единственный per-chat слот) | global + per-chat | admin (категория `prompts`) | L1 база канала/техники | известные слепки → superseded при композере ON; кастом не трогаем | `UNIFIED_COMPOSER_ENABLED=false` → байт-паритет |
| `prompts.direct_chat_verbalizer_system_prompt` | `:3943,4116` (+ kill-switch OFF → `PREV_CHAT_VERBALIZER_R1023`, `:3942-3945`) | global (per-chat не читается, `:3640-3642,3942-3945,4095-4097,4115-4118`) | admin | L1 база | как выше (база остаётся, Core — отдельный блок) | как выше |
| `prompts.direct_chat_synthesizer_system_prompt` | `:4095-4097` | global | admin | L1 база | нет | нет |
| `prompts.direct_l1_planner_system_prompt` | `:3640-3642` (Direct L1), `:7550-7554` (Initiative L1) | global | admin | L1 база | нет | нет |
| `prompts.verbilizer_mode_* / verbilizer_default_mode` | `prompt_style_blocks.py:216,222`, каталог `:663-…` | global | admin | совместимость (`extent_block` **заменяет** MODE, `prompt_style_blocks.py:314-317`) | не мигрируется; при композере ON MODE-блоки = legacy-совместимость | OFF → прежняя сборка |
| `prompts.factcheck_*` (3) | `factcheck_service.py:181,223,251` | global | admin | L1 база (машинная стадия) | нет | нет |
| `prompts.summary_*` (7, включая per-chat `summary_cover_style`) | `summary_generator.py:987,3765,3805`, `summary_l1_clusterizer.py`, `summary_l2_writer.py`, `summary_execution_input.py:114` | global (+per-chat cover) | admin | L1 база (редакционный канал) | 6 ключей **доказанно custom** в проде (baseline 2.58.33) → `custom_legacy`, эффект сохраняется | значения не меняются |
| `prompts.search/checkup/youtube*/webpage/extract/compress` | `search_service.py:92`, `checkup_service.py:47`, `youtube_summarizer_service.py:112,147`, `web_summarizer_service.py:73`, `summary_memory.py` | global | admin | L1 база | статус custom неизвестен (см. §8.2) | нет |

**Вне каталога** (не PG-редактируемо, ключа нет): `dream_prompts.py`, `lore_prompts.py`, `nostalgia_prompts.py`, `dossier_prompts.py`, `smartmodule_phrases.py:161` (+ рендер `handlers/direct_chat.py:253`), `anticliche_worker.py`, `negative_constraints.py`, `mca_episodes.py`, `mca_vision.py`, `self_reflection.py`, `memory_maintenance.py`, `initiative_observer.py:895`. Любая инъекция Core, работающая «по каталогу», эти пути не видит — прямой вход в решение §4 (owner-decisions «(b)»).

### 1.3 `style.scope`, anti-cliché, tones

| Источник | Где | Scope | Owner | Priority | Migration | Rollback |
|---|---|---|---|---|---|---|
| `flags.style_scope_enabled` + env `MCA_STYLE_SCOPE_ENABLED` | `mca_gates.py:1054-1064` (`_module_catalog_flag` → `hot_config.get`, **global-only**), `settings.py:2516` | global | admin (категория `flags`) | L5 scoped prefs | не мигрируется; **новый** Style Policy — отдельная сущность, scoped-просьбы остаются источником L5 | OFF → парity 2.58.54 |
| `mca_style_requests` (+ `MAX_ACTIVE_PER_CHAT/PARTICIPANT`) | `mca_style_scope.py:47-78,293-331,515,616`; рендер `<Style_Requests>` `:331+`; врезка `direct_chat_service.py:2053-2076,2390-2391` | per-chat/participant/topic | участники + admin чата | L5 (форма) | не мигрируется | OFF → пусто |
| анти-клише (`anticliche_cache`, `negative_constraints`) | `:4010,4167` (`dynamic_rules`), `negative_constraints.py:25` | global + dynamic ban-list | система | L7 форма (частично) | не мигрирует; в W3 подчиняется единому порядку нормализации (SOUL-16.4.1) | OFF → прежний путь |
| tone/temperature пресеты | `direct_chat_service.py:2694-2695` (`settings.tone_temperature`) | per-user/chat | пользователь | L6 | нет | нет |

### 1.4 `response_extent` / direct prompt modes

| Источник | Где | Scope | Owner | Priority | Migration | Rollback |
|---|---|---|---|---|---|---|
| `DIRECT_RESPONSE_PLAN_ENABLED` | `response_extent.py:133-142`, `settings.py:617` | global env | инженер | L6 | нет | OFF → legacy-путь |
| `DIRECT_RICH_DELIVERY_ENABLED`, `DIRECT_TOOL_PLAN_ENABLED` | `response_extent.py:145-163`, `settings.py:619-621` | global env | инженер | доставка | нет | OFF |
| `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS` | `response_extent.py:166-182` | global env | инженер | L6 | нет | <=0 → None |
| `SMART_VERBALIZER_MODES_ENABLED` | `direct_chat_service.py:3940,4112`, `settings.py:568` | global env | инженер | L1 база | нет | OFF → `PREV_CHAT_VERBALIZER_R1023` |
| `EXTENTS` (нет `one_word`) | `response_extent.py:36`; схлопывание `direct_l1.py:146-147` | — | W3 | L6 | фикс в W3 (SOUL-05) | — |
| `plan_response_mode` | `direct_l1.py:171-190` (ветка `isinstance(plan, L1Plan)` `:181-185` на Direct/Initiative **недостижима**: обе точки конвертируют в `ResponsePlan` — `direct_chat_service.py:2660,7611`) | — | W3 | совместимость | не трогаем | — |

### 1.5 SelfModel / Experience (сохраняются как есть)

| Источник | Где | Scope | Owner | Priority | Migration | Rollback |
|---|---|---|---|---|---|---|
| `flags.self_model_enabled` + `MCA_SELF_MODEL_ENABLED` | `mca_gates.py:1410-1421`, `settings.py:1620` | global | admin | L4 | нет | OFF → legacy-персона |
| `flags.trait_rules_enabled`, `flags.legacy_traits_migration_enabled` | `mca_gates.py:1433,1445` | global | admin | L4 | нет | OFF |
| `flags.character_layers_enabled` + `MCA_CHARACTER_LAYERS_ENABLED` | `mca_gates.py:1032-1040`, `settings.py:2507` | global | admin | L3/L4 форма | нет | OFF → legacy-персона |
| `flags.character_speech_enabled` + env | `mca_gates.py:1043-1051`, `settings.py:2509` | global | admin | L5 | нет | OFF |
| SelfModel precedence/guards/awareness | `mca_self_model.py:378-427` (хеши версий), `:803-899` (guards), `:1643` (`select_behavior`), `:1763-1812` (`render_frame_block`) | chat/global | система | L4 | **версия Core обязана войти в `persona_version_hash`/`_snapshot_version`** (см. §5, seam 1) | LKG (`_lkg_*`, `:967-1005`) |
| `memory.experience_learning_enabled` | `module_registry.py:394-405`; лимиты env-only `mca_experience.py:426-463`, `settings.py:1528-1555` | global | admin | L5 | расширяется типами SOUL-08, второй контур не создаётся | `MCA_EXPERIENCE_LESSONS_ENABLED/…FEEDBACK_ENABLED` |
| `flags.postprocess_form_guard_enabled` + env | `mca_gates.py:1066-1077`, `settings.py:2518` | global | admin | L7 | нет | OFF → 2.58.54 |

---

## 2. Данные новых сущностей

### 2.1 Personality Core (`character.core`)

Один JSON-документ на scope. Глобальный — строка `bot_settings(key='character.core')`; per-chat — `chat_params.overrides['character.core']` (тот же ключ ⇒ один резолвер, один RBAC-путь, один горячий путь: `chat_params.ChatParamsCache` + `pg_notify('chat_params_updated')`, `chat_params.py:37,96,303`).

```jsonc
{
  "revision": 7,                       // монотонно, инкремент при любом сохранении
  "enabled": true,                     // owner-visible выключение слоя (не env)
  "full_text": "…владельческий полный текст (byte-stable)…",
  "compact_text": "…runtime-редакция 150–250 слов, согласована вручную…",
  "compact_words": 213,
  "compact_tokens_est": 286,           // измеряется тем же оценщиком, что в опыте
  "detail_level": "compact",           // "compact" | "full" (настраиваемый уровень подробности)
  "origin": "owner_edit",              // owner_edit | migrated_core | imported_note
  "updated_at": "2026-10-16T…Z",
  "updated_by": 123456,
  "history": [                          // bounded ≤ 20; предыдущие ревизии сохраняются
    {"revision": 6, "full_text": "…", "compact_text": "…", "updated_at": "…", "updated_by": 1, "reason": "…"}
  ]
}
```

Инварианты: `revision` растёт только при изменении `full_text|compact_text|detail_level|enabled`; `full_text` никогда не перезаписывается автоматикой; compact-редакция имеет тот же смысл/запреты (SOUL-02.7) — это подтверждается owner-видимым preview и токен-метрикой, не LLM-пересказом.

Происхождение и версии трассируются полями `(revision, updated_by, updated_at, origin)`; в Writer уходит ровно `compact_text` выбранной ревизии; `full_text` доступен только в редакторе/Inspector.

**Отдельный ключ миграции:** `character.migration_snapshots` (тот же контур `bot_settings`, категория `content`, json) хранит неизменяемые оригиналы owner-текстов, захваченные фазой A/B:

```jsonc
{"captured_at": "…", "items": {
   "prompts.direct_chat_system_prompt": {"sha256_12": "…", "text": "…", "class": "canon_current"},
   "personas.system_prompt_overrides":  {"sha256_12": "…", "text": "…", "class": "custom_legacy"}}}
```

Ничего не удаляется при последующих нормализациях; ключ read-only для владельца (перезапись запрещена, только дополнение новыми записями).

### 2.2 Speech Style Policy (`style.policy`)

Тот же документ-per-scope подход: глобальный `bot_settings(key='style.policy')`, per-chat — `chat_params.overrides['style.policy']`.

```jsonc
{
  "revision": 12,
  "presets_applied": ["no_quotes", "no_trailing_period"],
  "rules": [
    {
      "id": "quotation_marks.hard.no_graphic",   // стабильный id (никаких автогенераций)
      "kind": "quotation_marks",                 // закрытый набор kind (W3 фиксирует значения)
      "params": {"classes": ["«»", "„“", "\"\"", "\"", "'"], "detect_apostrophe": true},
      "strictness": "hard",                      // hard | soft
      "scope": "global",                         // global | chat | initiative | editorial | code_or_structured
      "enabled": true,
      "owner": "…telegram_id…",
      "revision": 3,                             // ревизия самой записи
      "created_at": "…", "updated_at": "…",
      "reason": "владелец: без кавычек в обычной речи",
      "conflict_strategy": "exempt_protected",    // exempt_protected | deny_incompatible | prefer_task
      "content_type_exemptions": ["verbatim_quote","url","code","json","markdown_markup","version_literal","ellipsis"],
      "origin": "preset:no_quotes"                // preset:* | owner|migration:<key>|experience_proposal
    }
  ],
  "soft_instructions": [ {"id": "…", "text": "…", "scope": "chat", "enabled": true, "owner": 1, "revision": 1} ],
  "history": [ {"revision": 11, "rules_sha256_12": "…", "updated_at": "…", "updated_by": 1} ]
}
```

Требования SOUL-16.1.4 покрыты перечисленными полями (`id, kind, params, strictness, scope, enabled, owner, revision, created_at, updated_at, reason/description, conflict strategy, content-type exemptions, migration origin`).
Ключи-правила **не** превращаются в десятки `prompts.*` (прямое требование §16.1.4).
Per-chat merge — детерминированный и явный: правило с одинаковым `id` в chat-доке **заменяет** глобальное; правило с новым `id` **добавляется**; удаление = `enabled=false` в chat-доке (не «пустой документ»). Итоговый merge-результат показывается как `effective_style_policy` (источник на каждое правило: `global|chat|preset|inherited`).

### 2.3 Few-Shot Sample Library (SOUL-07/§8)

Единственная новая таблица (обоснование §3.4). Поля — ровно требуемые источником + технические:

`id BIGSERIAL PK`, `input_text TEXT NOT NULL`, `reply_text TEXT NOT NULL`, `technique TEXT NULL` (закрытый набор W4: `literalism|absurd_escalation|deadpan|bureaucratic_logic|unexpected_analogy|other`), `context_note TEXT`, `language TEXT DEFAULT 'ru'`, `tags TEXT[]`, `rudeness_level SMALLINT` (0–3, без «promise»-семантики), `author_user_id BIGINT`, `source_kind TEXT CHECK IN ('owner_manual','bot_suggested','verified_success')`, `scope TEXT CHECK IN ('global','chat')`, `chat_id BIGINT NULL`, `owner_approved BOOLEAN DEFAULT false`, `status TEXT CHECK IN ('active','archived')`, `library_version TEXT` (A/B-ось), `revision INT DEFAULT 1`, `created_at`, `updated_at`, `created_by`, `updated_by`.
Отбор (1–3 примера, diversity, recency, penalty) и «почему выбраны» — политика в `bot_settings(key='humor.selection')` (bounded: max_items, max_tokens, diversity_min_distance, recency_penalty, per-chat isolation) + трасса выбора в существующую телеметрию (`mca_events`/Experience application links), без нового стора.
Изоляция: выборка никогда не возвращает сэмпл `scope='chat'` чужого чата; leakage-guard (имена/персональные данные) — на записи и на отборе (двойная защита), тест в W4.

### 2.4 Фичи-флаги внутри документов-сущностей

`character.core.enabled`, `style.policy` отсутствие/выключенность, `humor.selection.enabled` — управляются владельцем в UI и видны в манифесте. Env-рубильники новых сущностей — см. §6.

---

## 3. Хранилище и обоснование

1. **`bot_settings` (JSONB, `key`, `category`, `updated_at`)** — `services/pg_db.py:36-44`; чтение/запись — `ConfigCache` (in-memory + `set`/`set_many` с одной транзакцией, `config_cache.py:681-735`); optimistic-токен — `get_updated_at` (`:675-677`) + `POST /api/config` `expected_updated_at` (`web/api/routes.py:609-725`).
2. **`chat_params.overrides` per-chat** — `chat_params.py:114,344-377,407+`: резолвер `chat → global → default`, каст по каталогу, инвалидация кэша `pg_notify`, конфликты 409. Это готовый механизм для «явных per-chat наследуемых настроек» (SOUL-02.8) и hot apply (SOUL-15.5).
3. **RBAC** — существующие права: `param.<category>.<key>` для глобального пути (`web/api/deps.py:242`), `edit_persona`-экшн и секция `content` для чата (`routes.py:2458-2493`). Мы **не** вводим новые фронтенд-чекбоксы: для `character.core` глобально требуется право на ключ (категория `content`), для chat — существующий chat-level edit-путь; для Sample Library — отдельное право-экшн (W4/§6).
4. **Sample Library — новая таблица, обоснование:** построчный CRUD/архив/ревизии/фильтры/счётчики показов не выражаются одним JSON-документом без гонок и без перезаписи всей библиотеки; таблица создаётся идемпотентным DDL в существующем контуре миграций (`services/database.py` MigrationStep / `schema_migrations`), пишется через существующий `write_transaction`-паттерн Experience. Второго config service нет: чтение политики — через `bot_settings`, контент — таблица.
5. **История изменений** глобальных ключей сегодня не хранится (в `bot_settings` нет истории; история есть у `chat_params` — `chat_params.py:39,92`). Поэтому версионирование Core/Style Policy делается **внутри документа** (`history`, bounded), а не новой инфраструктурой. Для Sample Library ревизия — поле записи.
6. **Категории/группы каталога:** новые ключи регистрируются в `param_catalog` (категория `content`, тип `json`, `per_chat=true` — свойство выводится из категории, `param_catalog.py:123-131`), с новыми `GroupSpec` (`character_core`, `character_style_policy`, `humor_selection`) в том же diff. Значения доступны и через generic `/api/config` (ops/rollback), и через purpose-built endpoints «Речи и характера» — **один и тот же объект**, расхождение UI↔Writer запрещено (SOUL-15.2). Если `_coerce_value` не принимает объект для `json`-типа — правится в одном месте (`web/api/routes.py`) в рамках W2.

---

## 4. Двухфазная миграция

### Фаза A — read-only inventory + dry-run (без записи)

Инструмент (W1): `tools/soul1_migration_dry_run.py` (черновик имени; фактическое имя — за W1). Вход: `ConfigCache` (PG) + `chat_params` per-chat + каталог. Выход: `plans/features/soul-1/evidence/migration-preview.json` + человекочитаемая Migration Preview.

Классификация каждого ключа/значения (детерминированная, по sha256 и по байтовому сравнению с известными слепками `PREV_*`, `prompt_migrations.py:116,317-351`):

| Класс | Что значит | Предсказанное действие |
|---|---|---|
| `absent` | ключа в PG нет | ничего (сид поставит канон; поведение не меняется) |
| `canon_current` | == текущий код-канон | снапшот оригинала в `character.migration_snapshots`; при композере ON — supersede известного «токсичного» сегмента |
| `canon_prev_step` | == известный `PREV_*`-слепок | то же + запись «миграция известного канона», без переписывания текста |
| `custom_legacy` | ничему не равен | **не трогаем**; помечаем `custom_legacy`, эффект сохраняется; строка в Migration Preview с текстом (RBAC) и sha |
| `conflicting_legacy` | custom, чей эффект противоречит Core/owner-hard (например, «обязательно мат»/«будь токсичен») | попадает в Preview как конфликт, требует решения владельца (§owner-decisions a) |

Прогноз: для каждого ключа — какой блок попадёт в сборку при композере ON/OFF, сколько символов/токенов добавится, какие слои будут `superseded|kept|conflict`. Dry-run печатает точный список будущих записей (ключ → класс → действие) и **не имеет** флага записи.

### Фаза B — идемпотентная транзакционная запись

Один прогон = один `ConfigCache.set_many([...])` (одна PG-транзакция, `config_cache.py:709-735`) + по одному `chat_params.set_chat_params(...)` на затронутый чат (`chat_params.py:407+`, транзакционно, optimistic).
Идемпотентность: каждая запись гейтится парой `(key, expected_sha256_12)`; повторный прогон видит уже новое значение и делает no-op (тот же контракт, что `migrate_prompt_canons`: «уже новый канон → skip», `prompt_migrations.py:344-346`).
Сохранение оригиналов: тексты известных канонов/кастомов копируются в `character.migration_snapshots` (неизменяемый блок, D1 §2.1) — источник не теряется даже при последующей нормализации.
`custom_legacy` в фазе B не перезаписывается **никогда**; витрина конфликтов — Migration Preview + предупреждение на странице «Характер» (W6).
Откат: (1) ревизия Core/Style Policy откатывается в редакторе (history); (2) `UNIFIED_COMPOSER_ENABLED=false` возвращает точную старую сборку без отката данных (ключи `prompts.*` не изменялись); (3) для известных канонов дополнительно доступен `rollback_prompt_canons`-путь (`prompt_migrations.py:354-380`) — он уже существует и уважает кастом.
Прогноз «до/после» для PG: `effective before/after` по каждому ключу в отчёте (SOUL-15.9).

---

## 5. Права, hot apply, деградация (SOUL-15.3/15.4/15.5/15.7)

| Требование | Реализация |
|---|---|
| Глобальный Core/hard-правила — только уполномоченный админ | `POST /api/config` с категорией `content` → `can_edit_param` (`routes.py:_post_config_global`), RBAC-матрица ключа; сервер повторно проверяет user_id/роль |
| Scoped-чат и правка примеров — отдельные права | чат: существующий chat-level edit-путь (`access_for`+`can_edit_param`, `routes.py:631-681`); библиотека: отдельное право-экшн (например `edit_humor_library`) — не выводится из одного чекбокса |
| Оптимистичная защита версии | global: `expected_updated_at` → 409 (`routes.py` `_post_config_global`); chat: `ChatParamsConflict` → 409 (`chat_params.py:46`, `routes.py:710-716`); внутри документа — `revision`, сервер отклоняет запись при несовпадении |
| Секретность/маскирование | полный текст Core/Style/манифеста — по правам; в обычном UI не отдаём (SOUL-15.4, SOUL-10.6) |
| Hot apply (следующий ответ, без рестарта) | global: `ConfigCache` обновляется в `set_many` синхронно с БД; chat: TTL 120 c + `pg_notify` (`chat_params.py:38,96,303`) — SLA «следующий ответ» подтверждается тестом `test_soul1_hot_apply_two_chats` |
| Immutable snapshot начатого запроса | композер собирает `PromptManifest` с `versions{...}` в начале хода и передаёт в Writer/нормализацию; значения читаются один раз за ход (не «половина новых правил») |
| No silent degradation | **правило:** ни один OFF/пустой/недоступный источник не даёт тихой подмены — каждый случай даёт `skip_reason` в манифесте + notable-событие (`mca_events`) + строку в защищённой диагностике. Требуемые причины: `core_absent`, `core_disabled`, `style_policy_unavailable`, `samples_unavailable`, `lessons_unavailable`, `persona_disabled`, `character_layers_disabled`, `response_plan_disabled`, `verbilizer_modes_disabled`, `pg_outage` |
| PG outage не теряет настройки | при PG down записи не выполняются (503/честная ошибка), кэш остаётся последним известным; `prompt_migrations`-подобные пути → skip (`prompt_migrations.py:323-325`); проверка restart/stale — тест W2 |
| Флаг провалившегося hard-правила не «styled=true» | нормализация возвращает `pass|repaired|exempted|conflict|failed` в манифест; `failed` никогда не маскируется (W3 исполняет, W2 обязан довести до payload) |

---

## 6. Флаги

| Флаг | Тип/резолв | Семантика OFF (ровно паритет) | Композиция с существующими |
|---|---|---|---|
| `flags.unified_composer_enabled` (env `UNIFIED_COMPOSER_ENABLED`) | hot, per-chat-capable (category `flags`) | сборка system/user = байт-в-байт текущая (`prompt_style_blocks.compose_verbalizer_system` + существующие хвосты); Core/Style/Examples/Humor-инъекции не рендерятся | не дублирует `SMART_VERBALIZER_MODES_ENABLED` (тот про тело вербализатора), `flags.persona_enabled` (тот про персону), `MCA_CHARACTER_LAYERS_ENABLED`, `DIRECT_RESPONSE_PLAN_ENABLED` — каждый сохраняет свой смысл |
| `flags.speech_style_policy_enabled` (env `SPEECH_STYLE_POLICY_ENABLED`) | hot | нет effective policy: ни semantic hint, ни валидации/нормализации; Core жив; downgrade виден в манифесте (`style_policy_disabled`) | не заменяет `flags.postprocess_form_guard_enabled` (тот про form-гард вербализатора) |
| `flags.humor_library_enabled` (env `HUMOR_LIBRARY_ENABLED`) | hot | нет отбора примеров и нет few-shot слоя; Humor Craft (статические приёмы) может работать | не дублирует `memory.experience_learning_enabled` |
| `flags.humor_feedback_enabled` (env `HUMOR_FEEDBACK_ENABLED`) | hot | нет сбора feedback/обновлений выборки; **речь работает** | расширяет существующие `MCA_EXPERIENCE_FEEDBACK_ENABLED`/`_LESSONS_ENABLED` (не плодит второй learning-контур), `memory.experience_learning_enabled` остаётся мастер-гейтом Experience |
| `flags.character_core_enabled` (env `CHARACTER_CORE_ENABLED`) | hot | Core не рендерится (и никакая часть Style Policy, зависящая от Core-«характера»), остальное без изменений | оправдан: позволяет диагностически выключить Core, сохранив композер/стиль (SOUL-06.6 «toggle для диагностического выключения» относится к Humor Craft, но та же полезность нужна Core) |

Env-половины регистрируются в существующем реестре kill-switch'ей `services/mca_gates.KILL_SWITCHES` (`mca_gates.py:29+`) с описанием OFF-паритета: политика «env-emergency AND catalog-toggle, OFF = документированный паритет» уже действует (`mca_gates.py:225-294,1298-1306`). Δ каталога: +5 ключей `flags.*` + 3 ключа сущностей; новые флаги **не** дублируются с 4 уже существующими «тихими» рубильниками (см. §8.3).

---

## 7. Границы W1/W2/W3/W4/W6 (не пересекаться)

- **W1:** dry-run/inventory tooling, `migration-preview.json`, классификация кастомов, право-модель в отчёте. Ничего в рантайме.
- **W2:** документы Core/Style Policy + аксессоры, композер, флаги, версии в SelfModel-хешах, hot apply, тесты слоёв.
- **W3:** типизированные hard/soft правила, `StylePolicyValidator/formatter`, единый порядок нормализации, `one_word` end-to-end, анти-клише в общем окне.
- **W4:** таблица samples + CRUD + отбор + feedback внутри `mca_experience`.
- **W6:** UI «Речь и характер», редактор «Стиль письма», Prompt Inspector, Visual Preservation Map (SOUL-10.P1–P5), мобильная доступность промптов (SOUL-11).
- **W5/W8:** Initiative-диагностика и телеметрия/флаги-канарейка — потребляют `PromptManifest.versions`, ничего не пишут в документы Core.

---

## 8. Поправки к аудиту (проверено по коду)

1. **`prompts.direct_l1_planner_system_prompt` уже в каталоге** в рабочем дереве (`services/param_catalog.py:656`, незакоммиченный diff) — на HEAD `a854ad95` он действительно отсутствовал. Считать задачу закрытой W?-lane, в W2 не переделывать; счёт «24 ключа против 25 читателей» актуален только для HEAD.
2. **Статус custom для direct/factcheck/search/checkup/youtube/web/memory не проверен** — audit это честно помечает (§0.1); в дизайне это учитывается как риск: фаза A обязана классифицировать и эти ключи (иначе «Core over custom» невозможно предсказать).
3. **«Тихие» рубильники шире 4:** кроме перечисленных в аудите, `flags.character_layers_enabled`, `flags.character_speech_enabled`, `flags.style_scope_enabled`, `flags.self_model_enabled` читаются **только глобально** (`mca_gates.py:1360-1362` → `hot_config.get`), хотя `ParamSpec.per_chat` (`param_catalog.py:123-131`) объявляет категорию `flags` переносимой на чат, и `POST /api/config` с `X-Chat-Id` такую запись **разрешает** (`routes.py:672-675`). Это существующее нарушение «UI показывает одно, runtime читает другое» (запрещено SOUL-15.2). В W2 чините одну из сторон: либо чтение per-chat через `chat_params`, либо `per_chat=False` для этих ключей. Регресс-тест обязателен.
4. **«Двойной рендер персоны в одном ходу»** точнее формулировать так: это два **разных LLM-вызова** одного хода — tool-phase получает `system_prompt` с персоной (`direct_chat_service.py:2371-2430,2690,2841/2891`), а L2 Writer — тот же `character_block` в своём system (`:3948-3953`). Один и тот же персона-текст уходит модели дважды за ход и по **разным** базам-канонам (`direct_chat_system_prompt` vs `direct_chat_verbalizer_system_prompt`), каждая из которых несёт свою «токсичную» личность. Дубликат внутри одного сообщения (как у `system_prompt_overrides` + Core) — отдельный риск, который и закрывается SOUL-03.6.
5. **`plan_response_mode`** для `L1Plan` недостижим на штатных путях (обе точки конвертируют в `ResponsePlan`: `direct_chat_service.py:2660,7611`), поэтому «silent fallback serious» инертен именно там, где аудит его наблюдал (P2) — это не боевой конфликт, а совместимость; чинить не требуется, но W3 должен знать, что MODE-алиас не управляет длиной (это делает `extent_block`, `prompt_style_blocks.py:314-317`).
6. **`EXTENTS` без `one_word`** подтверждено (`response_extent.py:36`), `to_response_plan` подтверждён (`direct_l1.py:146-147`); дизайн композера **не опирается** на этот маппинг (см. `design-composer-contract.md` §4).
7. **`strip_cap_phrases`** (`response_extent.py:478-491`) — существующий прецедент детерминированной вычистки известного legacy-текста из финальной сборки без правки PG; дизайн переиспользует именно этот механизм для supersede «токсичных» канонов, а не новый.
