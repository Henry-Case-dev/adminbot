# P7-C — Forensic Audit: Module Contract / Initiative / Chat selector / CLAIM→REALITY

Phase 0 (Scanner), read-only. HEAD `08a8849` (master). Прод проверен живым HTTP `GET /healthz`
(SSH запрещён по AGENTS.md/fail2ban): `{"status":"ok","version":"2.58.71"}` — зафиксировано в ходе аудита.
Незакоммиченный шум (M `services/disk_retention.py`, `plans/MEMORY.md`, `plans/backlog.md`,
`plans/runtime_task.md`, `plans/workflow_state.md`, untracked `.playwright-mcp/`, `node_modules/`,
evidence-скриншоты asap6) — отмечен, НЕ тронут.

Вердикты: VERIFIED / PARTIAL / FALSE / LIVE_PENDING / UNVERIFIED / SUPERSEDED.

---

## 1. Блок 1 — Module inventory

### 1.1. Источники гейтов

- `services/mca_gates.py:29` `KILL_SWITCHES` — **85 env-only kill-switches**, все default ON
  (комментарии mca-18 «73→76», mca-19 «76→80», mca-20 «80→83», mca-12 «83→85»).
  Прод: release-маркеры 2.58.65/2.58.66 — «KS — 0 env-оверрайдов (все 85 ON)».
- `config/settings.py` — те же значения как ClassVar (напр. Intent-блок :1514–1534).
- `services/param_catalog.py` — настройки продукта: 113 GroupSpec. MCA_* kill-switches в каталог
  СОЗНАТЕЛЬНО не дублируются (:2226–2227 «Kill-switches K1–K4 — env-only (в каталоге НЕ дублируются)»).
- `web/app.js:521–612` `MODULES` — **hardcoded JS-список, 14 карточек** (комментарий :512 «ровно 11»
  устарел — добавлены mod_budgets, mod_images, mod_vision). Workspace-вкладки `WORKSPACE_TABS` :619–650.

### 1.2. Инвентарь кандидатов §6.1

| Фича | Runtime owner | Master/effective gates | Settings surface | MODULES | Status/Analytics | Help | Класс (rationale) | Вердикт |
|---|---|---|---|---|---|---|---|---|
| **Initiative / Intents** | `services/mca_intents.py` (heartbeat 300s, due-скан :1160, recheck :524) | `MCA_INTENTS_ENABLED` K1 + K2/K3/K4 + 5 лимитов — env-only ON (gates :375–394, :1304–1327; settings.py :1514–1534) | **НЕТ** — 0 ключей MCA_INTENT_* в каталоге (grep = 0) | **НЕТ** | Status-блок «Инициатива» read-only (index.html:6397–6440; `intent_snapshot` status_service.py:1034; лейблы app.js:6746–6750); mca17c map `intent.initiative` (app.js:7807) | словарь гайда v4 «Намерение» (info_service.py:1448) | **Product Module** (самостоятельное проактивное поведение, включаемое/выключаемое, есть параметры) | **ORPHAN** — нет ни карточки, ни настроек (§5.1 подтверждён) |
| **Stories / Episodes** | `web/api/stories.py`, episodes-фасад mca-05 | `MCA_STORIES_VITRINA_ENABLED`, `MCA_STORIES_MANAGE_ENABLED`, `MCA_EPISODES_*` (gates :181–194, :477–488) — env-only | **НЕТ** группы | **НЕТ** | Status «Истории чата» (index.html:6589+), `/api/stories/*` | нет (осознанно: заглушка не рекламируется) | **Submodule** (Память) — управляем витриной/мутациями | **ORPHAN** (P1, → F4) |
| **Experience / Lessons** | `services/mca_experience*`, review-job | K1–K4 `MCA_EXPERIENCE_*` env-only (:354–373) | **ЕСТЬ** — группа `memory_experience` «Опыт и уроки»: `EXPERIENCE_LEARNING_ENABLED`, `EXPERIENCE_REVIEW_CADENCE` (param_catalog.py:2228–2239) | **НЕТ** | Memory-карточка (index.html:2038–2056) + Status-лента `data-experience` (:6937–6970); процесс `self_learning.run` | словарь «Урок» (:1450) | **Submodule** Памяти (настройки есть, registration нет) | **PARTIAL-ORPHAN** (→ F4: добавить subsection/родителя, не дублируя настройки) |
| **SelfModel / Character evolution** | `services/mca_self_model.py`, persona/traits | `MCA_SELF_MODEL_ENABLED`, `MCA_TRAIT_RULES_ENABLED`, `MCA_LEGACY_TRAITS_MIGRATION_ENABLED`, `MCA_CHARACTER_LAYERS_ENABLED`, `MCA_CHARACTER_SPEECH_ENABLED`, `MCA_STYLE_SCOPE_ENABLED`, `MCA_POSTPROCESS_FORM_GUARD_ENABLED` — env-only (:257–274, :400–416) | **НЕТ** (правка Личности/Досье есть, оси-рубильники — нет) | **НЕТ** | Досье-модалка (index.html:7459+), self_model в mca17c (app.js:7803) | словарь «Динамические черты»/«Черта» | **Submodule** (Характер, parent Persona/Досье) | **ORPHAN** — 7 env-only осей без UI-владельца (→ F4) |
| **Random / Quantum** | `services/mca_random_source.py` + `mca_exploration.py` | `MCA_RANDOM_SOURCE/QUANTUM/REFILL/EXPLORATION/USES_ENABLED` env-only (:325–352) | **ЕСТЬ (богатая)** — `memory_random` (RANDOM_SOURCE, FALLBACK, 2×probability, param_catalog.py:2199–2222), `random.uses.*` ×6 (:1134–1162), `keys_random` ×9 (1 secret, :770–800) | **НЕТ** | Status «Источник случайности» + лента применений (status_service.py:1022) | словарь «Источник случайности» (:1449) | **Submodule/shared subsystem** (owner между Памятью/Сном/Инициативой не зафиксирован) | **PARTIAL-ORPHAN** (настройки есть, owner-карточки нет; → F4, low) |
| **Temporal Factcheck** | factcheck temporal pipeline | `MCA_TEMPORAL_FACTCHECK_ENABLED/TOOL/CACHE` env-only (:451–468) | **ЕСТЬ** — группа `temporal_factcheck` «Временной фактчек» на вкладке mod_factcheck (param_catalog.py:484–489) | parent `mod_factcheck` **ЕСТЬ** | mca17c `temporal.factcheck` (app.js:7805) | INFO §1 (время/свежесть) | **Submodule** parent'а Фактчек (эталон §M3) | **OK** |
| **Cover Styles** | cover style pipeline (`cover_style_*`) | env UI-флаги + `prompts.summary_cover_style` | style editor через workspace-вкладку `styles` «Стили обложки» (app.js:627–628, 663–664) | parent `mod_summary` **ЕСТЬ** | CoverPromptManifest, TSTYLE-роут | INFO §10 (обложка/стиль/номера) | **Submodule** Сводок | **OK** на уровне registration (truth-аудит контента — Workstream G, lane P7-B) |
| **Embeddings / GraphRAG** | `services/embedding_control_plane.py`, graphrag_rebuild | `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`, `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED`, GRAPHRAG_SHADOW_REBUILD — env-only (:172–180) | **ЕСТЬ** — `models_embeddings`, `limits_graph`, `limits_rag`, `flags_memory` + UI профилей (asap6 evidence-скриншоты embedding_profiles_*) | **НЕТ** (infra) | Analytics/Status | admin-строка namespace-safety | **Infrastructure** с operator-facing настройками в родителе «Память» | **OK** (проверить раскладку Advanced в F4) |
| **Dossier rebuild / episode backfill / maintenance** | `dossier_rebuild_jobs`, retention, episodes backfill | `MCA_DOSSIER_*` ×5, `MCA_EPISODES_BACKFILL_ENABLED` env-only (:150–168, :186) | частично (UI кнопка/прогресс пересборки index.html:7526+) | **НЕТ** | процесс `dossier.rebuild` v2, `maintenance.retention` | словарь «Пересборка» | **Maintenance** → Advanced/Maintenance в родителях (Досье/Память) | **OK при условии** явного Advanced-места; episodes backfill остаётся env-only — отметить |

### 1.3. Единый ModuleSpec/registry и drift-инвариант

- `grep ModuleSpec|module_registry|PRODUCT_MODULES` по *.py — **0 совпадений**. Канонического реестра НЕТ
  (§4.4 подтверждён). `MODULES` — hardcoded JS; связь карточек с каталогом — по соглашению (`toggleKey`,
  `tab`), без автопроверки.
- Инвариант-теста «крупный operator-facing gate ⇒ module/submodule owner ИЛИ infrastructure-rationale»
  (§14, M2) — **НЕТ**. Drift-тест реестра (M4) — **НЕТ**. Existing `tests/test_webapp_hubs_matrix_ui.py`
  покрывает только маршруты.

---

## 2. Блок 2 — Initiative / Intents (Workstream D)

### 2.1. Полный список флагов и лимитов

Объявлены: `config/settings.py:1514–1534`; гейт-функции: `services/mca_gates.py:1263–1327`; реестр
kill-switches: `:375–394`. Читатели: `services/mca_intents.py` (K1–K4 :367–369, :524; batch due-скан
:1160; attempts/abandoned :1120; retention :1190), карточка процесса `intent.initiative`
(`mca_process_registry.py:1088–1125`, settings_ref :1101–1106), тесты off-parity
(`tests/test_mca09_intents_off_parity_round1040.py`).

| ENV | Default | Смысл |
|---|---|---|
| `MCA_INTENTS_ENABLED` | **True (ON)** | K1 мастер; OFF = бит-в-бит 2.58.59 |
| `MCA_INTENT_HEARTBEAT_ENABLED` | True | K2 due-тик; OFF → кандидатов нет |
| `MCA_INTENT_DECISION_ENABLED` | True | K3 решения/делегирование nostalgia |
| `MCA_SEND_RECHECK_ENABLED` | True | K4 recheck-слой на границе отправки |
| `MCA_INTENT_HEARTBEAT_BATCH_MAX` | 20 (≥1) | батч due-скана |
| `MCA_INTENT_MAX_ATTEMPTS` | 3 (≥1) | → abandoned |
| `MCA_INTENT_CANDIDATES_MAX` | 8 (≥1) | кандидаты на решение |
| `MCA_INTENT_RETENTION_DAYS` | 180 (≥1) | архив прунах |
| `MCA_INTENT_DEFER_BACKOFF_SECONDS` | 1800 (≥60) | deferred backoff |

### 2.2. UI-поверхность

- `web/app.js::MODULES` (:521–612): **карточки Initiative/Intents НЕТ** — подтверждено.
- Status: read-only блок «Инициатива» (index.html:6397–6440): state `ok/not_run/disabled/restricted/
  unavailable` (app.js:6746–6750), активные намерения, последнее действие/причина. Источник —
  `status_service.py:1034` → `intent_snapshot()`.
- «Настройки блока» (index.html:6456–6460) рендерит `storiesSettingsMeta()` (app.js:6755–6804) —
  это **random/budget ключи** (`memory.random_exploration_probability`, `random_source`,
  `limits.worker_daily_llm_calls_*`, `flags.budgets_enabled`, `limits.chat_context_budget_tokens`).
  **Собственных Intent controls НЕТ** — и не может быть: в `param_catalog.py` нет ни одного
  MCA_INTENT-ключа (grep = 0). §5.1 подтверждён полностью.

### 2.3. Effective state (честно)

- Код-дефолт всех 4 тумблеров ON; прод-`.env`: 0 MCA_-оверрайдов (release-маркеры 2.58.65/2.58.66 —
  «KS — 0 env-оверрайдов (все 85 ON)»). Heartbeat регистрируется при старте (маркер 2.58.60:
  «Added job _tick_intent_heartbeat»; `mca_intents` была пуста — честный unknown/not_run).
- **Гипотеза «runtime disabled при code-default ON» статически НЕ подтвердилась**: effective = ON по
  коду+прод-фактам релизных маркеров; `disabled`-ветка UI срабатывает только при K1 OFF. Возможные
  источники расхождения (env, hot config, parent gates, startup wiring) — проверены статически, разрыва
  не найдено. Живой `/api/status` в этой сессии не забирался (нужен auth-контур) — точный
  прод-лейбл (ok vs not_run при пустой таблице) остаётся наблюдением владельца (LIVE_PENDING-наблюдение).
- Реальный разрыв — не effective-state, а **Module Contract**: фича ON и работает, но невидима и
  неуправляема как продукт (нет карточки/настроек/effective-дисплея requested-vs-effective).

---

## 3. Блок 3 — Chat selector (Workstream F)

### 3.1. Цепочка с file:line

1. **Список чатов**: `GET /api/access/chats` — `web/api/access.py:192–238`; SQL
   `CHATS_FOR_USER_SQL` :46–53: `SELECT p.chat_id, p.is_active, a.role_name FROM chat_profiles p
   LEFT JOIN chat_admins a ... WHERE p.chat_id < 0`. Selector видит **только существующие строки
   PG chat_profiles**; `is_active` возвращается (:224), но **не фильтруется**; title best-effort
   `chat_display_info` с fallback `Чат <id>` (:215–226).
2. **Фронт**: `loadAccessCtx()` app.js:4828–4860 (GET /api/access/me + /api/access/chats);
   вызывается **только** из `mounted` (:4491) и `retryInitData()` (:4591). `toggleScope()`
   (:10829–10839) НЕ перевыгивает список — рендер из кэша `accessChats`.
   Stale localStorage обрабатывается: несуществующий saved-id → очистка + null/первый доступный
   (:4834–4849) — C8 не сломан.
3. **Рендер селектора**: `activeChatOptions` (app.js:4242–4265) — inactive-чаты показываются **без
   badge «неактивен»** (badge только ЛС, :4251); фильтра `is_active` нет ни на сервере, ни на клиенте.
4. **Материализация профиля**: `handlers/chat_lifecycle.py` — join `:76–107` (→
   `upsert_profile_on_join` + `set_active(True)` + gates-defaults), leave `:148–168`, migrate
   `:171–216`. Роутер зарегистрирован: `bot.py:895` + `setup_chat_lifecycle(lore_store, bot_id, db)`
   `bot.py:654`.
5. **КЛЮЧЕВОЙ РАЗРЫВ**: хендлеры висят на observer **`chat_member`** (`@chat_lifecycle_router.
   chat_member`, aiogram 3.31). В aiogram 3 `my_chat_member` и `chat_member` — **разные observers**
   (`.venv/.../aiogram/dispatcher/router.py:58–59`). Собственное вступление бота Telegram доставляет
   как update **`my_chat_member`** (всегда, вне allowed_updates) → попадает в ПУСТОЙ `my_chat_member`
   observer → `on_bot_joined` НЕ срабатывает. Update-ы `chat_member` (о чужих) требуют бот-админа в
   чате и явного allow; в фильтре `_is_bot_user` они всё равно отбрасываются (`:66–73`, `:84–85` →
   UNHANDLED). `dp.start_polling(bot)` без allowed_updates (`bot.py:1220`) → aiogram
   `resolve_used_update_types()` запрашивает только типы с хендлерами (`chat_member` да,
   `my_chat_member` не нужен — доставляется всегда). **Профиль нового чата не создаётся.**
6. **Fallback на первое входящее сообщение: ОТСУТСТВУЕТ** (§7.3 не реализован). Все точки INSERT в
   `chat_profiles`: `chat_lore_store.py:45` (`ensure_profile` :373–386 — production-вызов только из
   lifecycle; `_put_relation` :630/:710/:740 — ручные web-действия), `chat_params.py:104`
   (`ensure_scope_profile` :523–557 — вызывают web-записи DM-скоупа routes.py:630/859/984,
   bot_persona.py:573, seed/backfill-скрипты `chat_settings_seed.py:152`, `backfill_104_*.py`).
   Ни один message-handler ensure_profile не вызывает. Существующие чаты в селекторе — наследие
   ручных/бэкфилл-путей.
7. **RBAC** (§7.4): global admin видит ВСЕ `chat_profiles` (chat_id<0) c `access=global_admin`
   (:209–211); local admin/moderator — только строки с грантом `chat_admins` (:211–214); прочие —
   только синтетическая DM-строка (:230–237). `/api/access/me` — та же SQL и логика (:152–189).
   Соответствует контракту.

### 3.2. Ранжированная root-cause гипотеза «новый чат не появился в selector»

1. **P0 — собственное вступление бота не обрабатывается**: `my_chat_member`-update не имеет
   хендлера; хендлеры на `chat_member`-observer + узкий `_is_bot_user`-фильтр → событие add-to-group
   теряется, `chat_profiles`-строка не создаётся (handlers/chat_lifecycle.py:76/148 + aiogram
   router.py:58–59 + bot.py:1220).
2. **P0-усилитель — нет fallback-материализации**: первое сообщение из неизвестного group-чата ничего
   не создаёт (§7.3 Fallback registration отсутствует; grep INSERT INTO chat_profiles — только
   ручные/seed-пути). Если join пропущен — чат невидим, пока не выполнится ручное web-действие/скрипт.
3. **P1-усилитель — refresh UX**: `loadAccessCtx()` только на mounted/retry — даже после починки БД
   новый чат появится лишь после переоткрытия MiniApp; `toggleScope` не рефрешит (app.js:10829).
4. **Edge**: в группах, где бот НЕ админ, `chat_member` не доставляется вовсе (ограничение Bot API) —
   join-детект возможен только через `my_chat_member`.
5. **Не причина невидимости, но незакрытый UX-контракт**: `is_active=false` чаты показываются без
   badge (сервер :220–226, клиент :4244–4257) — контракт §7.3 «badge/скрыть» не зафиксирован.

---

## 4. Блок 4 — CLAIM → REALITY (отчёт ASAP 6)

| # | CLAIM | IMPLEMENTATION PATH (evidence) | VERDICT |
|---|---|---|---|
| 1 | «ANU quantum live VERIFIED, ключ в protected store, provider_unconfigured исчез» | Слот ключа: `keys.random_quantum_api_key` — catalog secret=True (param_catalog.py:780–781, группа `keys_random` :228–231), резолв `mca_random_source.py:123,1331`; synthetic-mask без plaintext-строк (config_cache.py:477–499). `POST /api/random/test` routes.py:2005–2021 (RBAC global admin ∨ право на ключ; draft-ключ в body; key_present в ответе). UI: одна кнопка «Проверить подключение» index.html:2712–2721; таксономия — ровно 1 secret, остальные 8 полей обычные (:770–800) — регрессии ASAP 6 нет. Live: `plans/features/asap6-current-task-closure/evidence/deploy-live-acceptance.md:12–16` — было `blocked/provider_unconfigured`, test_connection healthy=True/state=active/key_present=True/persisted=True (latency 594ms, batch 1024), после рестарта `{'status':'ok','remaining':1023}`; ключ через protected path (config_cache.set), plaintext не в логах. **Но** `provider_unconfigured` как честное состояние НЕ удалено из кода (`mca_random_source.py:158,1453,1791`...) — «исчез» только из прод-статуса после установки ключа | **PARTIAL** — подключение/UI/protected-store VERIFIED (статика + задокументированный live-прогон), формулировка «исчез» неточна (состояние честное, осталось by design); независимый повтор live-пробы в этой сессии невозможен (нужен auth/ключ) |
| 2 | «MCA-17: 19 instrumented + 2 честных» | `services/mca_process_registry.py`: **47 ProcessDefinition**-карточек, у **40** есть `instrumentation=(...)`; **7 без** (не-инструментированные честно): `scheduler.reactions`, `uptime.heartbeat`, `telemetry.events` (v1 без instrumentation) + v0-плейсхолдеры `context.compress`, `context.selective`, `memory.lifecycle`, `relations.semantic`. Честный механизм: `declared_instrumented` (:75), `STATUS_NOT_INSTRUMENTED` (:35, резолв :1377–1378) | **SUPERSEDED** — механизм честного учёта существует и вырос: 19+2 (волна ASAP 6) → 40+7 (после mca-09/10b/12/15/16/18/19/20). Числа из отчёта устарели, претензии к честности нет |
| 3 | «embeddings namespace-safety v34» | Классы совместимости: `embedding_control_plane.py:1780–1783` (`INSTANT_COMPATIBLE`/`REINDEX_REQUIRED`/`INCOMPATIBLE_DIMENSION`/`COMPATIBILITY_UNKNOWN`, fail-safe unknown :1955–1961); инвариант §8.1 (namespace,semantic_index)→одна ACTIVE :2096; миграция `_migrate_embedding_generation_ns_v34` `services/database.py:3888+` (+namespace, +config_revision, backup-guard, идемпотентно, PG no-op, :1626–1639); тесты `test_asap5_embedding_identity.py`, `test_asap6_embedding_generations.py` | **VERIFIED** (статика: код+миграция+тесты на месте). Прод-применение v34 — по deploy-факту 2.58.71 (commit 8b44669 «ΔDDL=+1 применена»); независимая проверка БД в этой сессии невозможна (SSH запрещён) — вернуть к VERIFIED-прод после первой authed-проверки владельцем (формально LIVE_PENDING-нюанс) |
| 4 | «Help re-sync v4/v7 доставлен» | Канон: `INFO_CANON_VERSION = 7` (info_service.py:590) + DEFAULT_INFO_TEXT v7 с §13 «Просьбы посложнее» (:450–564); `GUIDE_CANON_VERSION = 4` (:651); слепки `PREV_MCA23_DEFAULT_INFO_TEXT` (v6, :340/:599) и `PREV_MCA23_INTELLIGENCE_GUIDE` (v3, :1105/:1462) в `KNOWN_*_SNAPSHOTS` (:1459–1463); идемпотентная доставка через `config_cache._migrate_intelligence_guide_r1023` (:385–443, канон-файл plans/docs/intelligence_user_guide.md, backup prev_markdown, drift-guard) + info-механизм; тесты `test_mca23_guides_content.py`, `test_help_ui_round1020/22/23.py`. Деплой-факт «доставлен» — commit 9f803aa + 08a8849; на 2.58.68 canon-gate фиксировал ещё v6/v3 (asap5 deployment.md), далее доставка v7/v4 в 2.58.71 | **PARTIAL** — статика (канон/слепки/миграции/тесты) VERIFIED; содержимое прод-PG (v7/v4 в bot_settings) в этой сессии не проверялось независимо (нужен auth) → прод-часть LIVE_PENDING до authed-пробы или подтверждения владельцем |
| 5 | «prod 2.58.71» | `config/settings.py:3209` `APP_VERSION = "2.58.71"`; в ходе этого аудита живой `GET https://admin-bot.duckdns.org/healthz` → `{"status":"ok","version":"2.58.71"}` | **VERIFIED** (live) |
| 6 | «полный pytest 12670+ passed» | Не запускать (ограничение аудита). Тестовая база: 507 test-файлов (512 py в tests/), 69 JS-харнессов. Предыдущее evidence: commit 8b44669 («полный pytest 12670+ passed / 4 pre-existing + mca09-flake изолированно»), asap6 evidence (`deploy-live-acceptance.md` — 12586 на 2.58.70-слайсе; release-маркеры 2.58.62–2.58.67 — 12088→12359 с ростом) | **LIVE_PENDING** — независимого воспроизведения на текущем HEAD нет; прод-acceptance фазы 2 (live-сценарии владельца) отдельно остаётся owner-gate (H4) |
| 7 | H5 — Help обещает больше, чем умеет planner | См. §5 ниже | **PARTIAL** |

---

## 5. H5 — Hooks для кросс-проверки с P7-A

Статика `services/response_extent.py` (планировщик MCA-23 фазы 2):

1. **Multi-tool ≠ semantic DAG**: `build_tool_plan` (:483–543) активируется ТОЛЬКО при маркере
   совместного чтения `_MULTI_READ_RE` (:507) и ≥2 уникальных URL (:514); шаги — только
   `fetch_article` (+опциональный `execute_web_search` :525–536); <2 шагов → `[]` (обычный
   model-driven путь). Help §13 «Бот спланирует цепочку сам» фактически покрывает узкий сценарий
   «2+ ссылки + сравнение». → P7-A: сверить реальный Direct route (где вызывается build_tool_plan,
   доля покрытых сценариев).
2. **Extent — детерминированный, не semantic**: `classify_request` (:270–363) — regex task-kind
   (:286–305), explicit short/long (:307–330), короткий вопрос ≤3 слов с «?» → micro (:337–343),
   болтовня → `social_chat`+`compact` (:349–353). Это подтверждает H1: «MCA-23 phase 2 complete» как
   semantic-планирование — PARTIAL. → P7-A: проверить, что ничто в финальной сборке промпта не душит
   extent (H3 `_SANDWICH_REMINDER`).
3. **Clarification — фиксированная формулировка**: `CLARIFY_MEDIA_TARGET` (:548–550), домен только
   `media_download`/`transcription` (`_CLARIFY_KINDS` :552), «context-aware» = boolean has_target
   (:555–562). Help §13 «задаст один конкретный уточняющий вопрос» — соответствует «один вопрос», но
   не обещает cover всех туманных просьб; пере-обещания нет, генерализации тоже.
4. **Терминология**: «ResponsePlan»/«DAG» в пользовательскую справку не утекли (grep по v7-тексту —
   нет) — commit-обещание соблюдено.
5. Для M3/§7-проверок Direct: смежные вопросы (гарантия ответа на прямое обращение, «попросил
   подробно — получишь подробно» INFO §7) — cross-check с фактическим Direct pipeline в лейне P7-A.

---

## 6. Подтверждённые баги/разрывы

| ID | Severity | Разрыв | Маппинг |
|---|---|---|---|
| P7-C-1 | **P0** | Собственное вступление бота (update `my_chat_member`) не обрабатывается: хендлеры на `chat_member`-observer, `my_chat_member`-observer пуст → `chat_profiles` не материализуется, новый чат невидим в `/api/access/chats` (chain §3.1 п.5) | **F5** |
| P7-C-2 | **P0** | Нет fallback-registration при первом входящем сообщении из неизвестного group-чата (все INSERT-пути — ручные/seed/web) | **F5** |
| P7-C-3 | **P1** | Initiative: продукт ON, но нет module-карточки, нет settings surface (0 ключей в каталоге), «Настройки блока» показывает чужие random/budget ключи | **F3** |
| P7-C-4 | **P1** | Нет канонического ModuleSpec/registry и инвариант-тестов (M2/M4, §14 acceptance mechanics); `MODULES` hardcoded, комментарий «ровно 11» устарел (14) | **F3** |
| P7-C-5 | **P1** | Inventory-orphans: Stories/Episodes (нет registration и настроек), SelfModel/Character (7 env-only осей без UI-владельца), Random (богатые настройки без owner-карточки), Experience (настройки есть, registration нет) | **F4** |
| P7-C-6 | **P2** | Selector не рефрешится при открытии (`toggleScope` без re-fetch); контракт показа inactive-чатов (badge/скрыть) не зафиксирован ни сервером, ни клиентом | **F5** |

Не-баги, зафиксированные как норма: Temporal Factcheck (эталон submodule), Cover Styles registration,
Embeddings/GraphRAG как infrastructure с настройками в «Памяти», RBAC `/api/access/*`, stale-
localStorage-обработка (C8-поведение уже корректно).

---

## 7. Вопросы для Architect

1. **Module registry** (§4.4): аддитивный registry рядом с hardcoded `MODULES` + обязательные
   invariant-тесты M2/M4 — подтверждает ли Architect аддитивный путь для F3?
2. **Initiative classification**: top-level карточка «Инициатива / Намерения» (§5.2) — подтвердить
   parent-модель (top-level vs submodule), и где разместить 5 лимитов (catalog-группа new vs
   Advanced в родителе) без дублирования storage keys (единый источник = catalog→Settings).
3. **my_chat_member fix** (F5): отдельные хендлеры на `my_chat_member`-observer (дублируя фильтры)
   vs один ChatMemberUpdated-хендлер на обоих observers — выбрать и покрыть тестами C1–C9; учесть
   группы без бот-админа.
4. **UX-контракт inactive**: показывать с badge «неактивен» или скрывать (§7.3 «один понятный
   контракт») + точка рефреша списка (открытие селектора/pull-to-refresh).
5. **Random ownership**: родитель для «Случайность» (Память vs отдельная карточка vs Сон/
   Инициатива-связка) с учётом §6.1 «shared subsystem».
6. **Help-правки после truth** (F9): сузить §13-формулировки («цепочка» → «пакет ссылок») после
   результатов P7-A, не трогая v7-канон до runtime-правды.

---

## 8. Метод и ограничения

- Толькот чтение; полный pytest НЕ запускался; SSH не использовался; единственный внешний вызов —
  `GET /healthz` (200, 2.58.71). Секреты не печатались (ключ ANU — только факты наличия/маски).
- Подсчёт карточек реестра: 49 уникальных `process_id=` в файле; regex-разбор блоков дал 47
  ProcessDefinition/40 instrumentation (погрешность склейки блоков ±2 на общую картину не влияет:
  honesty-механизм и порядок чисел подтверждены).
- Прод-факты (PG-содержимое help-канонов, v34-применение, живой /api/status intents) — вне досягаемости
  без auth/SSH; помечены LIVE_PENDING-нюансами, не «VERIFIED по умолчанию».
