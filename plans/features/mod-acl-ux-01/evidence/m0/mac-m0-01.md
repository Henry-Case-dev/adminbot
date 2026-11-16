# MAC-M0-01 — read-only baseline MOD-ACL-UX-01 (refresh 2026-11-16)

**Статус:** evidence подготовлен для проверки PM/Reviewer. `MAC-M0-01` **не закрыт**, `VERIFIED`
не заявлен. Продуктовый код, тесты, конфигурация, `requirements-map.json`, `slice-graph.json`
и существующие планы не изменялись. SSH к production не использовался.

**Локальное время сбора:** 2026-11-16 15:50 +12:00 (2026-11-16 03:50 UTC).

---

## 1. Идентификаторы

### 1.1. Плановая линия (planning checkout)

| Поле | Значение |
|---|---|
| Git root | `C:/Code/Python/adminbot` |
| Ветка | `master` |
| HEAD на старте среза | `ad06a034f044f5bb9a652bf245a586fc51b2d5b3` — `docs(acl): PM readiness …, first slice M0 refresh` (2026-11-16 15:41:14 +1200) |
| HEAD на момент сдачи | `6f91b88826a23281ec68f1825202e29958ebb6fb` — `docs(acl): M0 refresh started (FULL_BUILDER_ALLOWED)` (2026-11-16 15:41:57 +1200) |
| Дельта между ними | только `plans/workflow_state.md` (+1/−1), продуктового кода нет |
| План-гейт | `requirements_gate.py check --map plans/features/mod-acl-ux-01/requirements-map.json --stage plan --repo .` → `stage=plan inventory=279 manual=102 scoped=0 errors=0` |

Рабочее дерево содержит посторонние modified/untracked файлы (не мои); в коммит M0 они не
включены. Плановая линия — не runtime: `web/app.js` здесь 1 331 753 B, в отличие от
задеплоенного (см. 1.2), поэтому весь аудит кода ниже выполнен по checkout развёрнутого SHA.

### 1.2. Deployed production

| Поле | Значение | Источник |
|---|---|---|
| Версия | **2.58.205** | `plans/features/vmq-onto-01/evidence/release-2.58.205/identity.json`; live `/healthz` |
| Deployed SHA | **`bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1`** | `identity.json` (`code=verified_deployed`, checkout_sha = deployed_sha) |
| Ветка | `release/vmq-slice-d-2.58.205` | `identity.json` |
| Deployed at | 2026-11-15T09:47:15.317949Z, process start 09:47:17Z | `identity.json`, `deploy.md` §2–3 |
| Предыдущий | `2b419aa2…` / 2.58.204 | `manifest-after.json` |
| Хост/unit | prod VPS, `/var/www/admin_bot`, `admin_bot` | `deploy.md` |
| Схема | `PRAGMA user_version=47`, `max(schema_migrations)=47`, 130 таблиц | `deploy.md` §1, §3 |
| DDL | **0**: `migrations: current user_version=47 \| pending=[]`, до/после 47 | `deploy.md` §1 и §3 |
| Live health | `200 {"status":"ok","version":"2.58.205"}` | публичный `/healthz`, 2026-11-16 03:50Z |
| Live `/web/app.js` | 2 311 044 B, sha256 `3cf2c9168c350f49977127a1e6bb19363734e27923efeeeae4bce9fa9895f594` | публичный GET |
| `web/app.js` в checkout `bca18c1e` | тот же sha256 и размер (git blob `59a42e6d…`) | release-worktree `vmq-slice-d-release-…` |

Вывод: served `app.js` **байт-в-байт** соответствует checkout `bca18c1e` (2 311 044 B,
sha256 `3cf2c916…f594`). Served `index.html` отличается только подстановкой `__APP_VERSION__`:
17 вхождений в checkout (1 358 879 B) против 17 версий `2.58.205` в served (1 358 760 B),
разница 119 B; DOM-структура идентична. Аудит `app.js`/карточек относится к реально работающей
версии, а DOM-проба использовала checkout-шаблон `index.html` (см. 1.4, D3).

### 1.3. Конфигурационный бэкап: что есть и чего нет

| Артефакт | Что содержит | Винтаж | Пригодность для M0 |
|---|---|---|---|
| SQLite `pre_deploy_258205_20261115T094514Z.db` (3 354 996 736 B, sha256 `b388f068…a02a7`) | файловая БД, `user_version=47`, `integrity_check=ok` | 15.11.2026, pre-deploy 2.58.205 | это **SQLite**, не PostgreSQL-конфиг |
| `bot_settings` / `chat_profiles` snapshot pre/post | только counts + SHA-256 digest | 15.11.2026 | доказывает «deploy не менял настройки», но **не является restorable дампом** |
| `WorkspaceData/backups/adminbot-postmigration-2026-10-29/postgres.dump` (604 265 B, sha256 `8ca17e3a…fec9`) | PostgreSQL dump | 29.10.2026, app 2.58.141 | исторический; на 2.58.205 **устарел** (18 дней, десятки релизов) — как текущий baseline не используется |

**Итог:** в репозитории на 2.58.205 есть digest-снимок и метаданные полного gz-JSON
`bot_settings`/`chat_profiles` (MAC-M0-02, §6: файл на проде, 548/3 строки, read-back equal),
но нет restorable `pg_dump` (client на хосте не установлен). Это уточнение к прежней редакции
этого раздела, а не новый бэкап в репозитории.

### 1.4. Поправки D1–D3 (2026-11-16)

- **D1.** Внутренний sha256 распакованного JSON-снимка `config-tables-2.58.205.json.gz` —
  `1c5312feca6eba7a8386aeb39aaf712516f7f789f4bdc107a701e489c188ea78`, а не записанный ранее
  `309f1947…9914` (ошибочный хеш от `str(bytes)`). Gz не менялся: 92 356 B, sha256
  `1cae602d…9a4d`; 393 427 B JSON, 548/3 строки, read-back equal. Sidecar на проде исправлен:
  `.sha256` + `.meta.json` с `corrections[]`, `gz_modified_by_correction:false`; старый sidecar
  сохранён. Детали: `evidence/m0/effective-state-2.58.205.md` §6 и
  `evidence/m0/effective-state-2.58.205.json` (`snapshot.json_sha256_correction`).
- **D2.** `registry_for_frontend()` возвращает **10** записей — hidden `factcheck_temporal`
  отфильтрован внутри функции; **11** — это `MODULE_REGISTRY` целиком. Итоговый счёт
  «11 ModuleSpec, 10 видимых» не меняется.
- **D3.** «Байт-в-байт» верно только для `app.js`; `index.html` отличается подстановкой
  `__APP_VERSION__` (17 вхождений, 1 358 879 B checkout vs 1 358 760 B served, DOM идентичен).
  DOM-проба 21 карточки использовала checkout-шаблон `index.html`.

---

## 2. Аудит 21 видимой карточки

### 2.1. Метод

1. Статический список `MODULES` в `web/app.js` — 16 `mod_*` (L600–717; записи L601–712).
2. `GET /api/config.modules` ← `module_registry.registry_for_frontend()` возвращает **10**
   записей: hidden `factcheck_temporal` отфильтрован внутри функции; **11** — это
   `MODULE_REGISTRY` целиком. См. `services/module_registry.py:479–523`.
3. `f3ApplyModuleRegistry` (`web/app.js:17683–17786`) обогащает 16 статических карточек и
   добавляет отсутствующие записи реестра.
4. Проверка на реальном DOM: checkout-шаблон `web/index.html` + `web/app.js` (served sha
   совпадает, §1.2; `index.html` отличается только версией, 1.4/D3), `/api/config` — stub из
   deployed `registry_for_frontend()`, viewport 1280×800, Chromium/Playwright. Селектор
   карточки — `index.html:7639` `:data-mod="m.id"`.
   Результат: **21 элемент `[data-mod]`, 21 видимый**, порядок:
   `mod_summary, mod_direct, mod_factcheck, mod_search, mod_transcribe, mod_video_summary,
   mod_media_download, mod_web, mod_checkup, mod_sleep, mod_nostalgia, mod_budgets,
   mod_images, mod_vision, mod_initiative, mod_time, mod_stories, mod_character,
   mod_experience, mod_random, mod_embeddings`.
   Raw: `evidence/m0/catalog-dom-probe-2026-11-16.json`.

### 2.2. Канонический список 21 карточки

| # | DOM id | Подпись | Источник | Строка | parent / classification |
|---|---|---|---|---|---|
| 1 | `mod_summary` | Сводки чатов | static | `app.js:601` | — |
| 2 | `mod_direct` | Ответы в чате | static | `app.js:612` | — |
| 3 | `mod_factcheck` | Фактчек | static | `app.js:618` | registry `factcheck` (L214) |
| 4 | `mod_search` | Поиск | static | `app.js:624` | — |
| 5 | `mod_transcribe` | Транскрипт голосовых и видео | static | `app.js:630` | — |
| 6 | `mod_video_summary` | Выжимка видео | static | `app.js:636` | — |
| 7 | `mod_media_download` | Скачивание медиа | static | `app.js:641` | — |
| 8 | `mod_web` | Веб-страницы | static | `app.js:646` | — |
| 9 | `mod_checkup` | Диагностика | static | `app.js:651` | — |
| 10 | `mod_sleep` | Сон | static | `app.js:657` | registry `sleep` (L319) |
| 11 | `mod_nostalgia` | Ностальгия | static | `app.js:662` | registry `nostalgia` (L295) |
| 12 | `mod_budgets` | Бюджеты | static | `app.js:671` | — |
| 13 | `mod_images` | Генерация изображений | static | `app.js:680` | — |
| 14 | `mod_vision` | Распознавание изображений | static | `app.js:690` | registry `vision` (L271) |
| 15 | `mod_initiative` | Инициатива | static | `app.js:701` | registry `initiative` (L75) |
| 16 | `mod_time` | Время | static | `app.js:712` | — |
| 17 | `mod_stories` | Истории и эпизоды | registry-only | `module_registry.py:101` | `memory` / submodule |
| 18 | `mod_character` | Характер (SelfModel) | registry-only | `module_registry.py:125` | `persona` / submodule |
| 19 | `mod_experience` | Опыт и уроки | registry-only | `module_registry.py:152` | `memory` / submodule |
| 20 | `mod_random` | Случайность | registry-only | `module_registry.py:181` | `memory` / submodule |
| 21 | `mod_embeddings` | Векторная память (Embeddings/GraphRAG) | registry-only | `module_registry.py:346` | — / infrastructure |

`factcheck_temporal` (`module_registry.py:243`) — `visibility="hidden"`, карточкой не является и
в 21 не входит; его настройки остаются на поверхности Фактчека.

### 2.3. Три разных «числа модулей» и причина расхождения

| Источник | Число | Что именно считает |
|---|---|---|
| `MODULES` / config-вкладки `app.js` | **16** | статические `mod_*` карточки и их config-вкладки (L113–273 и L601–712; 16 уникальных id, каждый встречается в обоих списках) |
| Python-реестр `module_registry.py` | **11** записей, **10** видимых | ModuleSpec, включая hidden `factcheck_temporal`; `embeddings` — infrastructure без master |
| `m0-baseline.md` от 09.11.2026 | **11** | считал Python-реестр/комментарии, а не итоговый UI-union |
| Фактический UI после merge | **21** | 16 static + 5 registry-only (`stories, character, experience, random, embeddings`) |

Причина: комментарии в `app.js:112` («11 модулей») и `app.js:275` («Список-витрина 11 модулей»)
устарели; `f3ApplyModuleRegistry` добавил 5 подкарточек (ASAP 7 F4), а `MODULES` остался 16.
Ни один из трёх списков по отдельности не равен 21 — совпадение даёт только union.

### 2.4. Состав 21 не совпадает с перечнем M3 design freeze

`m3-design-freeze.md` §2 перечисляет 21 **название** (9 диалог/интеллект + 6 память + 4
проактивность + 2 политики), в котором есть «Диалог», «Анализ», «Мем-ветка» и одна карточка
«Генерация изображений/Vision». Фактический каталог 2.58.205 содержит вместо них отдельные
`mod_web`, `mod_checkup`, `mod_images` + `mod_vision`, и не содержит карточек «Диалог»,
«Анализ», «Мем-ветка». **Число 21 совпадает, состав — нет.** Это факт для M3/M4, а не
требование M0; решение о приведении состава принимает Architect/PM.

---

## 3. Реестр модулей, ключи и consumers

### 3.1. ModuleSpec (11 записей) и master-ключи

`ModuleSpec` — `services/module_registry.py:36–58`; регистрация — `:75–369`.

| id | title | parent | master_param | domain | default | env-ось (§ENV_GATES) | settings_groups | runtime_gate (декларация) |
|---|---|---|---|---|---|---|---|---|
| `initiative` | Инициатива | — | `flags.initiative_enabled` | overrides | True | `MCA_INTENTS_ENABLED` | `flags_intent`, `limits_intent` | global |
| `stories` | Истории и эпизоды | memory | `flags.stories_vitrina_enabled` | overrides | True | `MCA_STORIES_VITRINA_ENABLED` | `flags_stories` | global |
| `character` | Характер (SelfModel) | persona | `flags.self_model_enabled` | overrides | True | `MCA_SELF_MODEL_ENABLED` | `flags_character` | global |
| `experience` | Опыт и уроки | memory | `memory.experience_learning_enabled` | overrides | True | `MCA_EXPERIENCE_LESSONS_ENABLED` | `memory_experience` | **per_chat** |
| `random` | Случайность | memory | `memory.random_enabled` | overrides | True | `MCA_RANDOM_SOURCE_ENABLED` | `memory_random` | global |
| `factcheck` | Фактчек | — | `flags.factcheck_enabled` | overrides | True | — | `flags_module_factcheck`, `limits_factcheck`, `prompts_factcheck` | global |
| `factcheck_temporal` | Временная проверка | factcheck | `temporal.tool_enabled` | overrides | True | `MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED` | `temporal_factcheck` | global (hidden) |
| `vision` | Распознавание изображений | — | `flags.vision_enabled` | overrides | False | `MCA_VISION_ENABLED` | `flags_module_vision`, `limits_vision`, `models_vision`, `keys_vision` | global |
| `nostalgia` | Ностальгия | — | `memory.nostalgia_enabled` | overrides | False | — | `memory_nostalgia` | global |
| `sleep` | Сон и память | — | `memory.dream_enabled` | overrides | False | — | `memory_dream` | global |
| `embeddings` | Векторная память | — | *(пусто)* | — | — | `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED` | `models_embeddings`, `keys_llm` | global / infrastructure |

`PRODUCT_DEFAULTS` — `module_registry.py:394–405`; `ENV_GATES` — `:373–389`;
`MODULE_ENV_GATES` (84 env-оси, rationale-группы) — `:581–713`.

### 3.2. Фактические consumers master-ключей (runtime, не тесты)

| Ключ | Consumer | Строки |
|---|---|---|
| `flags.initiative_enabled` | `mca_gates.intents_enabled()` (env AND product) | `services/mca_gates.py:1874–1883` |
| `flags.stories_vitrina_enabled` | `mca_gates.stories_vitrina_enabled()` | `services/mca_gates.py:2673–2682` |
| `flags.self_model_enabled` | `mca_gates.self_model_enabled()` | `services/mca_gates.py:1974–1985` |
| `memory.experience_learning_enabled` | `mca_experience_jobs` — единый резолвер | `services/mca_experience_jobs.py:786`, `:816`, `:821`, `:849` |
| `memory.random_enabled` | `mca_gates.random_source_enabled()` | `services/mca_gates.py:1720–1735` |
| `flags.factcheck_enabled` | handler + tool schema + capability registry | `handlers/factcheck.py:1154`; `services/tool_schemas.py:1238`; `services/capability_registry.py:81` |
| `temporal.tool_enabled` | tool schema + capability registry | `services/tool_schemas.py:1246`; `services/capability_registry.py:666` |
| `flags.vision_enabled` | `mca_vision` (per-chat ветка) | `services/mca_vision.py:130`, `:174`, `:179`, `:631`, `:5145` |
| `memory.nostalgia_enabled` | `nostalgia_worker` → канонический `gates_enabled` | `services/nostalgia_worker.py:1031–1035`, `:1179–1185`; `services/feature_gates.py:47` |
| `memory.dream_enabled` | `dream_worker` (per-chat) + gates fallback | `services/dream_worker.py:557–567`, `:1012–1015`; `services/feature_gates.py:46`, `:68` |
| *(embeddings)* | env-only контур | `module_registry.py:633–637`; `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED` |

UI-потребитель реестра — единственный: `f3ApplyModuleRegistry` (`app.js:17683`), `f4ModuleGate`
(`app.js:17791`), фильтр групп `_workspaceGroupsFor`; API-продюсер — `web/api/routes.py:686`.
Отдельного `/api/modules` в `web/api` нет (проверено по всем router-decorators).

### 3.3. Домен gates (6 фич) — отдельный namespace

`ALL_GATED_FEATURES` — `services/feature_gates.py:36–38`; `FLAG_KEYS` — `:45–50`;
`DEFAULT_BY_FEATURE` — `:52–61`; `COMPAT_OVERRIDE_KEYS["permsoc"]` — `:75`.

| feature | глобальный ключ(и) | default | consumer |
|---|---|---|---|
| `dream` | `flags.dream_enabled` → `memory.dream_enabled` | False | `dream_worker.py:1015` |
| `nostalgia` | `flags.nostalgia_enabled` → `memory.nostalgia_enabled` | False | `nostalgia_worker.py:1077`, `:1185`, `:1669` |
| `lore_auto` | `flags.lore_auto_enabled` | True | `lore_worker.py:566` |
| `permsoc` | `flags.permsoc_enabled` | False | `permsoc.py:116` |
| `permsoc_reactions` | — (default ON) | True | `permsoc.py:211` |
| `permsoc_schedule` | — (default ON) | True | `permsoc.py:211` |

### 3.4. Декларация реестра vs фактический runtime (drift)

| Модуль | `runtime_gate` в реестре | Что реально читает runtime | Следствие |
|---|---|---|---|
| `sleep` | global | `dream_worker._key_for(chat_id, …)` → `memory.dream_enabled` per-chat (`dream_worker.py:557–567`, `:1014`) | карточка показывает только глобальный master, чат-состояние в ней не представлено |
| `nostalgia` | global | `gates_enabled(chat_id, "nostalgia")` — чат-гейт первым (`nostalgia_worker.py:1185`) | то же |
| `vision` | global | `mca_vision` читает per-chat `flags.vision_enabled` (`mca_vision.py:179`, `:5145`) | UI считает тумблер чата инертным (`app.js:22782–22790`), runtime — нет |
| `experience` | **per_chat** | канонический резолвер (`mca_experience_jobs.py:816–821`) | совпадает |
| `initiative/stories/character/random/factcheck` | global | только глобальный hot-ключ | совпадает |

Это baseline-факт: реестр объявляет per-chat только у `experience`, а фактических per-chat
читателей в deployed-линии три (`sleep`, `nostalgia`, `vision`). M0 не меняет ни реестр, ни
runtime; расхождение должен учесть M2/M4.

---

## 4. ACL guards и точки доступа

### 4.1. Канонические guard-функции

| Guard | Файл:строки | Семантика |
|---|---|---|
| `get_tma_user` | `web/api/deps.py:82–144` | HMAC initData, max-age, 401 |
| `tma_context` | `web/api/deps.py:179–190` | контекст TMA |
| `requires_permission(required)` | `web/api/deps.py:192–212` | 403, `user_has_permission` |
| `_role_type_of_user` | `web/api/deps.py:215–226` | `role_type` из кэша → канон `services.roles.role_type_of` |
| `user_is_global_admin` | `web/api/deps.py:229–237` | wildcard ИЛИ `global_admin` ИЛИ legacy `admin` |
| `user_has_permission` | `web/api/deps.py:240–249` | match_permission ИЛИ global admin |
| `requires_global_admin()` | `web/api/deps.py:252–266` | 403 для не-глобального админа |
| `can_view_key_value` | `web/api/deps.py:269–274` | `key.<pg_key>` |
| `can_edit_param` | `web/api/deps.py:277–283` | `param.<pg_key>` |
| `role_type_of` / `rank_of_type` | `services/roles.py:67–89` | role_type → ранг |
| `access_for` | `services/roles.py:140–221` | `AccessCtx`: global/local/DM/гранты |
| `effective_permissions` | `services/roles.py:234` | объединение прав |
| `can_access_chat` | `services/access.py:69–81` | global admin / грант чата / moderator |
| `effective_matrix` / `can_view_param` / `can_edit_param` | `services/access.py:229`, `:278`, `:288` | матрица view/edit ролей |
| `requires_permission` / `validate_permissions` / `guard_last_wildcard` | `services/permissions.py:117`, `:152`, `:178` | канон прав и защита последней wildcard-роли |
| `gate_authorization` | `services/feature_gates.py:124–153` | can_read/can_edit для гейтов |
| `gate_snapshot(..., state)` | `services/module_registry.py:444–476` | `can_read/can_edit` в снимке модуля |
| `is_admin` | `services/chat_access.py:43–50` | bot-side legacy: `ADMIN_USER_ID` или роль `admin` |
| `check_chat_admin` | `services/telegram_role_check.py:101+` | Bot API, fail-closed `unverified` |
| `is_meme_admin` | `handlers/meme_command.py:115–135` | `access_for` + `ADMIN_USER_ID` |
| `_has_chat_admin_rights` | `services/mca_style_scope.py:425–440` | admin или chat_admin, fail-closed |

### 4.2. Локальные guard-хелперы API (все проверены)

| Хелпер | Файл:строка | Реализация |
|---|---|---|
| `_require_global_admin` | `web/api/memory_agi.py:167–183` | `ADMIN_USER_ID` shortcut → `deps.user_is_global_admin`; используется 21× (20 endpoints) |
| `_require_global_admin` | `web/api/anticliche.py:53–61` | `roles.access_for(...).is_global_admin` |
| `_is_global_admin` | `web/api/chat_lore.py:159–169` | `ADMIN_USER_ID` → `deps.user_is_global_admin` |
| `can_access_chat` (lore) | `web/api/chat_lore.py:172–178` | global admin или `chat_admins` строка |
| `_viewer_is_admin` | `web/api/cover_styles.py:189–194` | `deps.user_is_global_admin` |
| `_assert_can_edit_seeded` | `web/api/cover_styles.py:197–207` | seeded-стиль только global admin |
| `_guard_mutable` | `web/api/cover_styles.py:458–462` | feature enabled + PG |
| `_require_chat_access` | `web/api/stories.py:66–77` | `access_for` + `can_access_chat` |
| `_require_memory_editor` | `web/api/stories.py:80–85` | `user_is_global_admin` |
| `_require_chat_access` | `web/api/routes.py:6436–6447` | `access_for` + `can_access_chat` |
| `_is_global_admin` | `web/api/routes.py:4139–4160` | локальная пере-реализация (wildcard/`admin`/`global_admin`); используется в `:4121` |
| `_ctx_global_admin` | `web/api/routes.py:367–369` | `roles.access_for` |
| `_persona_access` | `web/api/routes.py:4797` | доступ к персоне |
| `_prompt_hidden_admin` | `web/api/routes.py:5370–5373` | `deps.user_is_global_admin` |
| `_meme_template_guard` | `web/api/routes.py:6686` | валидация шаблона (не RBAC) |
| `_require_diag_admin` | `web/api/access.py:508–515` | диагностическая матрица |
| `_chat_visible` / `_avatar_allowed` | `web/api/avatars.py:402`, `:449` | scope чата/аватара |
| `_access` / `_guard_sample_chat_scope` | `web/api/speech.py:351`, `:3901` | доступ к речи и sample-чату |
| `_flag_guard` / `_chat_accessible` | `web/api/summary_test.py:48`, `:190` | env-флаг + чат |

`memory_overview.py:34`, `initiative_vitality.py:33`, `cognitive_map.py:85` импортируют
`_require_global_admin` из `memory_agi` — отдельной копии проверки там нет.

### 4.3. HTTP-поверхность

Измерено по `web/api/*.py`: **249 route-decorators**; единственный endpoint без auth —
`GET /api/health` (`routes.py:374–377`). Остальные 248 имеют auth-зависимость или явный
внутренний guard. Вне `/api`: публичные `/healthz` GET/HEAD (`web/app.py:361`, `:366`) и
статические `/`, `/web/*`, `/static/*` (`web/app.py:305–353`) — без TMA-auth по назначению;
данные они не отдают.

| Точка | Файл:строка | Guard |
|---|---|---|
| `GET /api/me` | `routes.py:380–413` | `get_tma_user`; отдаёт `is_global_admin` (`:409`) |
| `GET /api/config` | `routes.py:500–...` | `get_tma_user`; чат — 403 (`:524–526`); per-key `can_view_param` (`:550`); секреты фильтруются (`:545`, `:556`) |
| `POST /api/config` | `routes.py:767–...` | чат: `can_access_chat` (`:797–799`), per-key `can_edit_param` (`:847–852`); глобальный путь `_post_config_global` (`:2854`): `can_view_key_value` / `can_edit_param` (`:2869–2885`) |
| `DELETE /api/config/chat/{key}` | `routes.py:2650–2674` | DM-владелец / global admin / local admin, иначе 403 |
| `GET /api/config/overrides-map` | `routes.py:2745–2793` | RBAC-фильтр по чатам, чужие ЛС не видны |
| `GET/POST /api/admins`, `POST /api/admins/remove` | `routes.py:3027`, `:3055`, `:3074` | `requires_permission("access")` |
| `GET/POST /api/roles`, `DELETE /api/roles/{name}`, `POST /api/roles/{name}/rename` | `routes.py:3112–3234` | `requires_permission("access")`, `guard_last_wildcard` |
| `POST /api/control/{restart,stop,start}` | `routes.py:4178–4202` | `requires_permission("action.control.*")` |
| `GET /api/debug/config` | `routes.py:4207–4212` | `requires_permission("action.debug.config")` |
| `GET /api/chat/{id}/gates` | `web/api/gates.py:67–133` | DM-владелец / global / local / moderator, иначе 403 |
| `PUT /api/chat/{id}/gates` | `web/api/gates.py:136–193` | DM → 403; permsoc → только global; heavy → local admin; 409 |
| `/api/access/*` (16 endpoints) | `web/api/access.py:152–695` | `get_tma_user` + `access_for`; менеджмент — global admin, чтение — по scope |
| memory/analytics/oversight surfaces | `memory_agi` (20), `anticliche` (6), `memory_overview` (3), `initiative_vitality` (2), `cognitive_map` (2), `analytics` (10), `oversight` (8), `summary_test` (6) | `_require_global_admin` / `requires_global_admin` |
| `GET /api/roles/tree` | `routes.py:3272` | `requires_permission("access")` |

Фактические счётчики вхождений в `web/api` (regex, включая определения хелперов):
181 `Depends(get_tma_user)`, 33 `Depends(requires_permission(`,
40 `Depends(requires_global_admin())`. Endpoint-блоков с двумя auth-зависимостями не найдено.

### 4.4. Frontend guards (`web/app.js`)

| Guard | Строка | Что решает |
|---|---|---|
| `isGlobalAdmin` | `8443–8449` | приоритет `me.is_global_admin` с сервера; fallback — `admin`/wildcard |
| `isGlobalAdminEffective` | `8457–8462` | тот же серверный ответ (для global-секретов) |
| `hasPerm` | `27060–27085` | `params`/`keys`/`sections`/`actions` |
| `canViewTab` | `27087–...` | вкладки; сгенерированный `mod_<slug>` (`modules` fallback) — `27112–27122` |
| `canEditConfig` | `27597–27628` | per-key edit; global secret только global admin; DM-ограничения |
| `canEditModule` | `22772–22774` | `canEditConfig(m.toggleKey)` |
| `moduleGlobalCanEdit` | `23242–23245` | global admin + RBAC ключа |
| `moduleScopeCanEdit` | `23301–23304` | global vs chat scope |
| `moduleChatToggleReadonly` | `22782–22790` | chat-scope read-only для `runtimeGate=global` |
| `_isModuleTab` | `23630+` | сгенерированные module-вкладки |
| `isLocalAdminCtx` / `isDmCtx` | `27182`, `14119` | контекст локального админа / ЛС |

### 4.5. Состояние M1 false-403 в deployed-линии

Локальная копия проверки по имени роли в `memory_agi.py` заменена на канонический predicate
(`memory_agi.py:166–183`); `chat_lore.py:159–169` — тоже канон. Прогон на checkout `bca18c1e`:
`pytest tests/test_mod_acl_ux_01_m1_acl_false_403.py -q` → **17 passed** (4.95 s).
`tests/test_mod_acl_ux_m2_resolver.py -k six_case_table` → **2 passed** (4.31 s).
Остаётся один локальный re-implementation `routes.py:4139–4160`; по коду он эквивалентен
(wildcard / legacy `admin` / `role_type=global_admin`), но не использует `ADMIN_USER_ID` shortcut.

---

## 5. Матрица stored vs effective (без записи)

### 5.1. Винтаж и метод

Прямого SELECT на 2.58.205 в этом срезе не было (SSH не использовался). Использованы
существующие read-only артефакты:

| Артефакт | Что даёт | Винтаж |
|---|---|---|
| `evidence/m2/m2-deploy-2.58.175.md:103–147` | точные global gate flags + живой срез чата `-1002661910336` | 2.58.175, 09.11.2026 |
| `reports/m2-impact-3b1ba3b2.md:75–138` | 16 capability × 3 профиля; true/false/absent по master-ключам и gates; 0 изменённых пар | read-only прогон 09.11.2026 (прод 2.58.174) |
| `evidence/production-recon-2026-11-14/settings-layers.txt:13–23` | список override-ключей по 3 чатам + 3 global row | 13.11.2026, прод 2.58.199 |
| `vmq-onto-01/evidence/release-2.58.205/snapshot-{pre,post}.json` | 548 settings / 3 profiles; digest pre=post; overrides_count 8 / 32 / 5 | 15.11.2026, 2.58.204→205 |

Обозначения: `INH` — записи нет (INHERIT); `t`/`f` — явный bool; `n/r` — отдельным SELECT
на 2.58.205 не прочитано; `†` — наличие global-строки не подтверждено; `‡` — распределение по
чатам выведено из агрегата, индивидуального чтения нет.

Чаты (те же, что в прежних evidence): `G32 = -1002661910336` (31 override в 2.58.175, 32 в
2.58.205), `G8 = -1004482340693` (8), `DM5 = 5885953495` (владелец, 5). В snapshot 2.58.205
алиасы `CHAT_C1/C2/C3` = 8/32/5, то есть порядок алиасов другой; сопоставление — по количеству
override, не по alias.

### 5.2. Stored (что записано)

| Ключ | GLOBAL | G8 | G32 | DM5 |
|---|---|---|---|---|
| `flags.initiative_enabled` | n/r † | INH | INH | INH |
| `flags.stories_vitrina_enabled` | n/r † | INH | INH | INH |
| `flags.self_model_enabled` | n/r † | INH | INH | INH |
| `memory.experience_learning_enabled` | n/r † | INH | INH | INH |
| `memory.random_enabled` | n/r † | INH | INH | INH |
| `flags.factcheck_enabled` | n/r † | INH | INH | INH |
| `temporal.tool_enabled` (hidden) | n/r † | INH | INH | INH |
| `flags.vision_enabled` | n/r † | **t** | **t** | INH |
| `memory.nostalgia_enabled` | n/r † | INH | INH | **f** |
| `memory.dream_enabled` | n/r † | INH | INH | **f** |
| `gates.dream` | global `memory.dream_enabled` fallback = `t` (2.58.175 probe) | **f ‡** | INH | **f ‡** |
| `gates.lore_auto` | global `flags.lore_auto_enabled=t` | **f ‡** | INH | INH ‡ |
| `gates.nostalgia` | global `flags.nostalgia_enabled=t` | **t ‡** | INH | **f ‡** |
| `gates.permsoc` | global `flags.permsoc_enabled=f` | **f ‡** | **t** | INH ‡ |
| `gates.permsoc_reactions` | default ON, строки нет | INH | INH | INH |
| `gates.permsoc_schedule` | default ON, строки нет | INH | INH | INH |

Источники: master-ключи — `reports/m2-impact-3b1ba3b2.md:105–120`; gates-агрегат — там же
`:115–120`; точный `gates.permsoc=true` для G32 — `m2-deploy-2.58.175.md:110–147`;
global gate flags — `m2-deploy-2.58.175.md:142–144`; списки override — recon `settings-layers.txt:19–21`.

### 5.3. Effective (что реально исполняется)

| Capability | GLOBAL | G8 | G32 | DM5 | Расхождение |
|---|---|---|---|---|---|
| `module:initiative` | ON (default) | INH→ON | INH→ON | INH→ON | — |
| `module:stories` | ON | ON | ON | ON | — |
| `module:character` | ON | ON | ON | ON | — |
| `module:experience` | ON | ON | ON | ON | — (per_chat) |
| `module:random` | ON | ON | ON | ON | — |
| `module:factcheck` | ON | ON | ON | ON | — |
| `module:vision` | n/r † (default OFF) | t→**ON** (runtime) | t→**ON** (runtime) | INH→OFF | карточка `runtime_gate=global` показывает глобальный слой; runtime читает чат |
| `module:nostalgia` | n/r † (default OFF) | card n/r; `gates.nostalgia`→ON | card n/r; `gates.nostalgia`→ON ‡ | f→OFF | **разные источники**: карточка — `memory.nostalgia_enabled`, gates — `flags.nostalgia_enabled`/чат |
| `module:sleep` | n/r † (default OFF) | card n/r; `gates.dream`→OFF ‡ | card n/r; `gates.dream`→ON | f→OFF | **разные источники**: карточка — `memory.dream_enabled`, gates — per-chat fallback |
| `module:embeddings` | инфраструктура, toggle нет | — | — | — | — |
| `module:factcheck_temporal` | ON (default, hidden) | ON | ON | ON | — |
| `gate:dream` | `memory.dream_enabled` fallback = t → ON | f→OFF | INH→ON | f→OFF | — |
| `gate:lore_auto` | t → ON | f→OFF | INH→ON | INH→ON ‡ | — |
| `gate:nostalgia` | t → ON | t→ON ‡ | INH→ON | f→OFF | — |
| `gate:permsoc` | f → OFF | f→OFF ‡ | t→**ON** | INH→OFF ‡ | — |
| `gate:permsoc_reactions` | default ON | ON | ON | ON | — |
| `gate:permsoc_schedule` | default ON | ON | ON | ON | — |

Ключевые выводы матрицы:

1. Явных chat-значений модульных мастеров всего четыре: `vision=true` у G8 и G32,
   `dream=false` и `nostalgia=false` у DM5. Остальные 6 видимых мастеров + hidden
   `temporal.tool_enabled` (7 ключей) — INH у всех трёх чатов.
2. `GLOBAL OFF + CHAT ON` в последнем прочитанном срезе (2.58.175) есть только у
   `gate:permsoc` (G32, `t`) — совпадает с выводом `m2-impact-3b1ba3b2.md:127–138`;
   на 2.58.205 live-чтения не было (gap §7).
3. Для `sleep`/`nostalgia` карточка модуля и панель гейтов читают **разные ключи**:
   карточка — `memory.dream_enabled` / `memory.nostalgia_enabled`, gates — per-chat fallback
   (`memory.dream_enabled` для `dream`) и `flags.nostalgia_enabled` для `nostalgia`. Сами
   global-строки `memory.*` не прочитаны (`†`), поэтому расхождение значений **не
   утверждается**, но и не исключается: при разных глобальных строках UI покажет разные
   состояния. Точная проверка — gap §7, п.2/п.4; семантика M0 не меняется.
4. `vision` — обратный случай: карточка считает тумблер глобальным (read-only в чате), а
   runtime `mca_vision` читает per-chat override; у G8/G32 он `true`.
5. 0 изменённых пар (чат × capability) на 16 capability × 3 профилях в прогоне 2.58.175;
   digest `bot_settings`/`chat_profiles` 2.58.205 pre=post, то есть выкат 2.58.205 настройки
   не писал. Это **не** доказывает, что значения не менялись между 09.11 и 15.11.

---

## 6. Расхождения с baseline 09.11.2026

Снимок `m0-baseline.md` (09.11.2026, `integ/unify-release`) сохранён как исторический. Его
отличия от deployed-линии 2.58.205:

| # | Прежний baseline | Факт 2.58.205 | Причина / что делать |
|---|---|---|---|
| 1 | «11 модулей: 10 global, 1 per_chat» | 11 ModuleSpec, 10 видимых, но **21 карточка** UI (16 static + 5 registry) | baseline считал Python-реестр; UI union появился после F4 |
| 2 | `app.js` L691–696 — hardcoded MODULES + fallback | `f3ApplyModuleRegistry` (`17683–17786`) реально **добавляет** карточки; 16 static | baseline описывал прежний fallback, не merge |
| 3 | Effective-state — «два домена без единого ридера» | M2 добавил `chat_params.resolve_*` (`chat_params.py:1135`, `:1310`, `:1353`, `:1396`); gates/params/модули сведены | M2 выкачен в 2.58.175; baseline 09.11 этого не содержал |
| 4 | ACL false-403 — root cause в `memory_agi._is_global_admin` | Исправлено: `_require_global_admin` → `deps.user_is_global_admin`; 17/17 M1-тестов проходят | M1 выкачен; локальная копия по имени роли удалена |
| 5 | `web/app.js` и 5 других файлов — M-статус, in-flight MEMORY-08 | checkout `bca18c1e` чистый (`dirty=false`), файлы закоммичены | MEMORY-08 закрыт/влит |
| 6 | Схема в отчётах M2 — 46 | 47 (130 таблиц, migrations 47, DDL 0) | миграция между 2.58.175 и 2.58.205 |
| 7 | Роли и права — `index.html:9829–9988`, две модалки | `#/access/roles` — модалка `index.html:10549+` (`acc-roles-title` L10558), по-прежнему не отдельная страница | сдвиг строк; архитектура та же |
| 8 | EXP-FIX-01..10 — «present 10/10» на линии 09.11 | исторический вердикт; M5A/M5B изменили контур | M0 не переаудирует EXP-FIX; актуальность — в строках `MAC-EXP-*` |
| 9 | Ветка `integ/unify-release`, дата 09.11 | `master` / HEAD `6f91b888`, deployed 2.58.205 | плановая линия и runtime разошлись; аудит кода — по deployed checkout |

Отдельно: `m0-baseline.md` §1 (таблица 11 модулей) и §5b (Module Toggles) **устарели** и не
должны использоваться как текущая база; §4 (EXP-FIX) — исторический снимок, не текущий вердикт.

---

## 7. Gaps и что нужно от DevOps (без SSH со стороны Builder)

1. **Текущий конфигурационный бэкап PostgreSQL на 2.58.205.** В репозитории есть только
   digest-снимок. Нужен read-only экспорт `bot_settings` + `chat_profiles` (значения секретов
   маскированы; DSN/логины не печатать) с фиксацией `max(updated_at)` и sha256. Без этого
   нельзя назвать «бэкап конфигурации» текущим.
2. **Живая матрица stored/effective на deployed SHA.** В дереве уже есть
   `scripts/mod_acl_effective_state_report.py` (режим `--database`, только SELECT). Нужен
   прогон интерпретатором юнита на `bca18c1e`:
   `python -m scripts.mod_acl_effective_state_report --database --json --out <tmp>/m0.json`.
   Ожидаемый объём — 16 capability × 3 профиля; артефакт приложить к M0.
3. **Точное распределение gates по G8/DM5.** Агрегат (dream false ×2, lore_auto false ×1,
   nostalgia true/false ×1, permsoc true/false ×1) есть; индивидуальное чтение по чатам —
   только в п.2. До него ячейки `‡` — вывод, не факт.
4. **Global-строки модульных мастеров.** Нужен SELECT по 10 `master_param` (есть/нет, значение,
   `updated_at`) — иначе `†` остаётся.
5. **Live UI-каталог.** DOM-проба выполнена на checkout-шаблоне `index.html` (served
   отличается только подстановкой версии, D3) и served `app.js`; `/api/config` — stub из
   deployed-реестра, не живой ответ с прод-правами. Живой Mini App с owner-сессией в этом срезе
   не открывался; для M4 это отдельная проверка Playwright + Browser Use, не обязательная для M0.

Ни один пункт не является вопросом владельцу: это read-only работа DevOps/Builder.

---

## 8. Ограничения и уборка

- Матрица — реконструкция по существующим read-only evidence; точные live-значения 2.58.205
  не выдаются за прочитанные.
- Chat IDs не редактировались в новых таблицах (они уже присутствуют в прежних evidence
  проекта); секретов, DSN, токенов и IP в артефакте нет.
- Временных файлов не создавалось; DOM-проба работала in-memory, браузер закрыт, сервер
  остановлен. Единственные новые файлы — этот артефакт и raw JSON пробы.
- Продуктовый код, тесты, конфиги и `requirements-map.json` не изменялись.

---

## 9. Изменённые файлы

| Файл | Что |
|---|---|
| `plans/features/mod-acl-ux-01/evidence/m0/mac-m0-01.md` | этот артефакт (новый) |
| `plans/features/mod-acl-ux-01/evidence/m0/catalog-dom-probe-2026-11-16.json` | raw DOM-проба 21 карточки (новый) |
| `plans/features/mod-acl-ux-01/m0-baseline.md` | добавлен раздел 8 «Refresh 2026-11-16» со ссылкой; история 09.11 не переписана |

Коммит — docs/evidence, см. финальный отчёт сессии. Статус `MAC-M0-01` в карте не менялся;
после проверки PM должен обновить `baseline_sha256` (файл `m0-baseline.md` изменился).
