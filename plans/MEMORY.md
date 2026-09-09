# AdminBot — Memory Index (plans/MEMORY.md)

Индекс долговременной памяти. Архитектура — `plans/ARCHITECTURE.md` (§1–§21);
бэклог — `plans/backlog.md`. Полная семантическая карта — knowledge graph
(Memory MCP, entity `AdminBot` + модули `adminbot-*` + entity `feature-*`
раунда 10).

> Создан заново 07.09.2026 (pre-планирование эпоса «Multi-chat scaling +
> Granular RBAC + BYOK + PERMsoc-плагин + TMA-навигация»). Прежние plans/
> файлы удалены 03.09.2026. Синк STEP 3 выполнен 07.09.2026 (HEAD fac1b9f):
> раунд 10 распланирован — 6 фич F-7…F-12, T-843…T-924, spec.md @Architect,
> tasks.md @PM, статус «запланирован»; граф обновлён (entity feature-*).
> **Синк STEP 9 (финал) выполнен 08.09.2026 (HEAD fac1b9f): раунд 10
> ЗАВЕРШЁН и заархивирован** — 4717 passed / 0 failed (подтверждён прогоном,
> 54.46s), аппрув @Reviewer, архив 15 папок, ARCHITECTURE.md §22, DevOps
> runbook готов; БЕЗ коммита (worktree dirty); граф обновлён
> (feature-* → archived + round10-epic + ARCHIVED_IN).
> **Синк STEP 9 (финал, post-commit) 08.09.2026: раунд 10 закоммичен и
> задеплоен** — HEAD == origin/master == `533bf13` (69be94e + 533bf13),
> прод обновлён (PID 133710, DDL ok, бэкфилы done); граф обновлён
> (round10-epic → completed+deployed, AdminBot → DEPLOYED).
> **Step 0 recon 08.09.2026 (post-deploy баг-репорт TMA):** 4 группы
> багов найдены в коде, подробные координаты — KG-сущность
> `recon: tma-round10-postdeploy-bugs` + `bug: tma-*` (4 шт). Кратко:
> (1) конфиг-вкладки Промпты/Лимиты/LLM Провайдеры/Память и RAG/Реакции
> и Триггеры пустые — `web/index.html:436,538,542` вызывают НЕСУЩЕСТВУЮЩИЕ
> `basicItems(grp)`/`advancedItems(grp)` (в `web/app.js` только
> неиспользуемый `itemAdvanced` :1168) → TypeError при рендере;
> (2) логи — сервер отдаёт newest-first (`services/log_ring.py:153`), но
> `loadLogs` автоскроллит ВНИЗ (`app.js:1700-1704`) → старые видны внизу;
> per-line «Скопировать» (index.html:1586), невидимое поле = textarea-
> фолбек `copyText` (app.js:1742-1748); (3) relations — обогащение
> username/photo_file_id только топ-30 (`web/api/chat_lore.py:562-568`),
> имена каскадом names-map(30д/200)→aliases(флаг summary_enabled)→uid
> (user_relations.py:346-349, bot.py:570-571), панель ограничена только lg
> (index.html:1122-1123); (4) modules_feats — placeholder «Выберите чат в
> шапке» при `activeChatId==null` (index.html:748-750), карточки в v-else
> (751-869), `loadGateInfo` early-return (app.js:780-784). Тесты — только
> маркерные, баги не ловят. Отдано @Builder (RESEARCH ONLY, без правок).
> **Синк STEP 9 (финал, хотфикс 10.1) 08.09.2026:** раунд 10.1 ЗАВЕРШЁН и
> ЗАДЕПЛОЕН — HEAD == origin/master == `8eae899` (поверх 533bf13), 4 группы
> багов рекона закрыты (review PASS), тесты 4726, README «Хотфикс 10.1 —
> бот взял себя в руки»; прод 198.46.175.136: PID 159455 (active, since
> 2026-09-07 16:27:04 UTC), journal чист; граф обновлён (милстоун
> `round10.1-hotfix` → COMPLETED+DEPLOYED, FIXES tma-frontend,
> RESOLVES recon, AdminBot → COMPLETED). Новых follow-up нет.
> **Step 0 recon 09.09.2026 (пост-10.1 баг-репорт TMA, 7 багов):** RESEARCH
> ONLY, 7 багов из ультиматума юзера (bug 8 — место на диске сервера,
> DevOps, вне кода). Подробные координаты — KG `recon: tma-bugs-7-post-10.1`
> + `bug: tma-*` (7 шт). Кратко: (1) селектор чата скрыт — `index.html:389`
> `accessChats.length > 1` для global admin (+вторично PG-down → пустой
> `/api/access/chats`); (2) сайдбар без `overflow-y` (index.html:347/328-340);
> (3) нет вкладки «Функции PERMsoc» — параметры разбросаны по
> reactions_persons/reactions_mimic/reactions_word_reactions/limits_mimic/
> flags_media, TAB_RULES (param_catalog.py:1359) «группа → ровно 1 вкладка»;
> (4) аватары только инициалы (топ-50 + негатив-кэш 1ч, chat_lore.py:574-580,
> avatars.py:113-136, app.js:536-550), имена = грязный author_name БЕЗ
> санитизации (_participant_names chat_lore.py:602-616); (5) аккордеон
> `(0)` — details.advanced рендерится всегда (index.html:559-567);
> (6) модалка прав — 2 select min-ролей + checkbox (index.html:1914-1952,
> access.py:129-143 дефолт view=user); (7) «невидимое поле» — off-screen
> textarea-фолбек copyText (app.js:1792-1816), CSS-класса нет (инлайн-стили).
> Тесты: маркерные test_webapp_* (nav_disclosure/rbac/avatars/tma_fixes),
> test_frontend_tab_mapping, test_access.py, test_relations_service.py —
> баги НЕ ловят, часть фиксирует текущее поведение и потребует обновления.
> Отдано @Builder (без правок).
> **Синк STEP 9 (финал) 09.09.2026 (раунд 10.2):** фиксы рекона
> `recon: tma-bugs-7-post-10.1` РЕАЛИЗОВАНЫ и УТВЕРЖДЕНЫ (@Reviewer PASS,
> минор B-1 TABS-зеркало закрыт), 4759 passed / 0 failed (прогон в .venv,
> 64.00s), НО НЕ ЗАКОММИЧЕНЫ — 26 файлов modified + untracked plans/MEMORY.md,
> HEAD == 8eae899; коммит/деплой ожидают решения юзера. Граф обновлён:
> милстоун `round10.2-fixes` (IMPLEMENTED + PENDING_COMMIT, RESOLVES recon,
> FIXES 7 bug: tma-*). Диск сервера уже исправлен DevOps (см. раздел ниже).
> **Синк STEP 9 (финал, post-commit) 09.09.2026: раунд 10.2 ЗАКОММИЧЕН и
> ЗАДЕПЛОЕН** — HEAD == origin/master == `d30b203` (поверх 8eae899,
> 28 файлов, +1576/−314), тесты 4760 passed / 0 failed, @Reviewer APPROVED
> (имена as-is: ID никогда не имя; каскад alias→nickname raw→username(без @)→'';
> avatarInitial графема); прод 198.46.175.136: PID 454654, DDL ok, polling,
> webapp 200 «Функции PERMsoc», без Traceback, .env без изменений; README
> обновлён; граф обновлён (милстоун `round10.2-fixes` → COMPLETED+DEPLOYED,
> AdminBot → DEPLOYED, создан `server-hardening-102` → DEPLOYED).
> **Безопасность сервера (DevOps, 09.09.2026) — fail2ban/ufw/SSH-харденинг
> АКТИВНЫ** (см. раздел «Безопасность сервера» ниже); follow-up: миграция
> на SSH-ключи (решение владельца), ignoreip для статического IP, CrowdSec
> альтернатива, migrate_history 1.1G перенос.
> **Step 0 recon 09.09.2026 (раунд 10.3, 7 задач ТЗ юзера):** HEAD ==
> origin/master == `d30b203` (10.2 закоммичен+задеплоен, PID 454654),
> ветка master, дерево ЧИСТОЕ (untracked: plans/MEMORY.md + plans/reports/
> только). 7 задач ТЗ → раунд 10.3: F-13 `tma-chat-selector-fixes`
> (задачи 1,2,3,6 = AC-1/AC-2/AC-3/AC-5) + F-14 `dm-user-settings`
> (задача 4 = AC-4), милстоун `round10.3-epic` — статус **ARCHITECTED**
> (T-925…T-964, PM+Arch done, Builder не начат). ⚠️ (коррекция ниже —
> файлы уже НЕ пустые). Задачи 5 (sandbox reason=budget) и 7
> (graphrag JSON list) — НОВЫЕ бэкенд-реконы (KG: `recon:
> direct-chat-sandbox-budget` + `recon: graphrag-memorize-json-list`);
> на Step 0 были «вне планирования», но далее включены в F-15 (см. ниже).
> **Синк STEP 3 (планирование 10.3) 09.09.2026:** раунд 10.3 перепланирован —
> **3 фичи**: F-13 `tma-chat-selector-fixes` (T-925…T-944; tasks.md пересоздан по
> KG-канону, файл был утрачен), F-14 `dm-user-settings` (T-945…T-964; tasks.md
> пересоздан по KG-канону), **F-15 НОВАЯ** `direct-sandbox-budget-investigation`
> (T-965…T-973; задачи 5 и 7 ТЗ — sandbox reason=budget + graphrag JSON list;
> прод-диагностика T-965/T-966 ДО фикса). spec.md для всех трёх фич — @Architect
> (F-13/F-14 — пересоздание по KG-наблюдениям, F-15 — создание). Статус милстоуна
> `round10.3-epic` → ARCHITECTED (F-13/F-14/F-15, всё spec.md+tasks.md на диске:
> пересозданы/созданы 09.09.2026 — наблюдение Step 0 «файлы отсутствуют»
> УСТАРЕЛО; F-15: прод-диагностика T-965/T-966 (TODO) ДО фикса, Builder не начат);
> конфликт-матрица с F-1/F-3/F-4/F-5 зарегистрирована в plans/backlog.md
> (раунд 10.3); аудит Scanner (plans/reports/full_audit_results.md) учтён
> (HIGH-004/MED-015/017/019/021/022 → задачи фич; остальное — кандидат в отдельный
> техдолг-эпик). Граф обновлён (Step 3): AdminBot HAS_PLAN → F-13/F-14/F-15,
> F-14 DEPENDS_ON F-13 (+F-1 post-deploy-admin-minors, RELATED_TO F-3 scam-followup),
> F-13 CONFLICTS_WITH F-4 frontend-admin-bugfixes (Баг-4, общий рендер :551-552),
> F-15 RELATED_TO DirectChatService/summary-subsystem, PART_OF round10.3-epic.
>
> **Merge Phase 10.3 (10.09.2026, @Architect)** — F-13/F-14/F-15 IMPLEMENTED в рабочем
> дереве (HEAD d30b203 + 10.3, 27 файлов), @Reviewer APPROVED, Scanner-аудит 10.3:
> **0 blocker/major** (minor/info R10.3-1…R10.3-6 → ARCHITECTURE.md §24), pytest
> **4831 passed / 0 failed**, `node --check web/app.js` clean. ARCHITECTURE.md обновлён:
> §23 (раунд 10.3: DM-скоуп и настройки ЛС /F-14, единый селектор чатов + z-index /F-13,
> sandbox-budget + memorize-JSON /F-15) + §24 «Известные ограничения и техдолг»
> (R10.3-1…R10.3-6 + ссылка на остаток полного аудита); кросс-указатели §3/§4/§5/§9/§16.
> Локальные спеки F-13/F-14/F-15 НЕ тронуты (архивная фаза — @PM); коммит/деплой
> (T-972/T-973) — финальный шаг раунда. **Финальный синк KG/графа, статусов милстоуна
> `round10.3-epic` и архивирование — шаг 10 @Memory.**

## Активные фичи (plans/features/)

| Фича | Скоуп |
|---|---|
| `admin-debug-webview` (F-2) | `/debug_config` в HTML WebView поверх HTTPS |
| `scam-incident-security-followup` (F-3) | Секьюрити-фоллоу-ап после скам-инцидента 30.08 |
| `frontend-admin-bugfixes` (F-4) | Багфиксы админ-минги и `<Красивые ссылки>` |
| `config-read-path-audit` (F-5) | Аудит read-путей: settings.X vs hot.get |
| `user-aliases-admin` (F-6) | Алиасы юзеров в разделе «Лор чатов» (частично в master) |
| `post-deploy-admin-minors` (F-1) | Пост-деплойные миноры Epic 85 (T-648:T-655) |
| `tma-chat-selector-fixes` (F-13) | Раунд 10.3: единый селектор чатов, удаление closeApp, пустые вкладки (template v-for+v-if), «Статус» (z-index 45) — IMPLEMENTED (Merge Phase 10.3, 10.09.2026; @Reviewer Approved, Scanner 0 blocker/major; ARCH §23/§24) |
| `dm-user-settings` (F-14) | Раунд 10.3: ЛС-настройки (вариант A, is_dm_scope=chat_id>0, саммари default-off) — IMPLEMENTED (Merge Phase 10.3, 10.09.2026; @Reviewer Approved, Scanner 0 blocker/major; ARCH §23/§24) |
| `direct-sandbox-budget-investigation` (F-15) | Раунд 10.3: задачи 5+7 ТЗ (sandbox reason=budget, graphrag JSON) — IMPLEMENTED (Merge Phase 10.3; диагностика T-965/T-966 выполнена, BYOK-фоллбэк + fallback-парсер/ретрай в коде; ARCH §23/§24) |

## Раунд 10 — ЗАВЕРШЁН, закоммичен и ЗАДЕПЛОЕН (07.09–08.09.2026, HEAD 533bf13; статус: done+deployed)

«Multi-chat scaling (Variant A)» по `plans/docs/multi-chat-scaling-research.md`: 6 фич,
82 задачи T-843…T-924 (нумерация продолжает T-842). spec.md @Architect (закрывает
Q-протоколы раздела A tasks.md), tasks.md @PM. **Итог (08.09.2026): полный pytest
4717 passed / 0 failed (+155; подтверждён прогоном — 54.46s, 1 StarletteDeprecationWarning),
аппрув @Reviewer PASS, `git diff --check` чист; все 6 фич заархивированы
(@PM Archive Phase), архитектура — `ARCHITECTURE.md` §22, backlog.md — «✅ Выполнен
и заархивирован (08.09.2026 @PM, HEAD fac1b9f, tests 4717)».** После финала —
**коммит `69be94e` (фича, 89 файлов, +8932/−216) + фикс `533bf13` (DSN, 2 файла),
push origin/master, прод-деплой — см. «Раунд 10 — закоммичен и задеплоен» ниже.**

| Фича | Задачи | Скоуп |
|---|---|---|
| `multi-chat-rbac-byok` (F-7) | T-843…T-869 (27) | Часть 1 — фундамент раунда: роли Global/Local/Moderator/User/Custom (`bot_roles.role_type`, `services/roles.py` ROLE_RANK), `services/access.py::access_for`, таблица `param_permissions` (view/edit_min_role+hidden_from_local, DEFAULT_MATRIX в коде), `chat_profiles.chat_params` JSONB {v:1, overrides, gates, keys:{allow_global}, perm_overrides, meta} + резолв `hot_chat` chat_params→bot_settings→дефолт (409 по updated_at, NOTIFY, кэш 120с), BYOK `chat_keys` + бюджет `chat_usage` + `limits.chat_global_key_budget_*` + sandbox `content.no_key_reply`, `resolve_api_key(chat_id)` в llm_client, API `/api/access/*` + X-Chat-Id в /api/config |
| `tma-ui-fixes` (F-8) | T-870…T-877 (8) | Часть 3.2 — 8 UI/UX-фиксов TMA: flex-шапка 380px (T-870), логи `<pre><code>` 0.75rem (T-871), relations Alias→nickname→username→id + аватар-фолбэк (T-872), title чатов вместо -100… (T-873), чип «авто» (T-874), компактные стадии+note (T-875), Telegram ID админа → «Доступы» (T-876), регресс-аудит (T-877). Только web/*, без API/БД-изменений |
| `permsoc-module-isolation` (F-9) | T-878…T-889 (12) | Часть 2.1 — `services/permsoc.py` (реестр 5 модулей: slavik/kostik/alan/olya/mimic) + `PermsocGateFilter` (гейт на уровне фильтра, порядок роутеров bot.py НЕ меняется); master `flags.permsoc_enabled` default false + `chat_params.gates.permsoc`; под-флаги olya/mimic/alan через hot_chat; новые чаты OFF, живые — бэкфил `scripts/backfill_permsoc_gates.py` (ON для -1002661910336/custom-профилей) |
| `feature-gates-worker-budget` (F-10) | T-890…T-902 (13) | Части 2.3+2.4 — жёсткий Opt-In: `gates_opt_in` колонка + gates в `chat_params.gates` (dream/nostalgia/lore_auto/permsoc), `services/feature_gates.py::set_feature_gate` единый write-path; бюджет-ледежер `worker_budget` в PG (day/scope/metric/used; WORKER_BUDGET_TZ=Asia/Yekaterinburg), `services/worker_budget.py::consume`, лимиты `limits.worker_daily_*`, деградация nostalgia→lore→dream, jitter ≤ interval/3, fail-open; API GET/PUT gates + GET /api/workers/budget |
| `tma-ia-progressive-disclosure` (F-11) | T-903…T-913 (11) | Части 2.2+3.1 — MENU_ORDER (Главная/Чат-Профиль/Модули и Фичи/Настройки AI/Доступы и Роли), новая вкладка `modules_feats`, вход Oversight (F-12); селектор чатов `GET /api/access/chats` + X-Chat-Id + localStorage active_chat_id; `progressive_level` (RAG/k/vector/timeout/context/budget → advanced) + нативный `<details>` аккордеон + adminbot.expand; user → read-only (только Статус/Как это работает) |
| `global-oversight-dashboard` (F-12) | T-914…T-924 (11) | Часть 3.1 — `services/oversight.py::build_summary` → `ChatSummary` (гейты/opt_in/key_status/admins_count/last_active_ts/budget; кэши 60-120с, без новых таблиц), kill-switch через `set_feature_gate`, запрет глобального ключа `chat_params.keys.allow_global=false`, API GET /api/oversight/summary|chat/{id} + POST killswitch/global_key, `requires_global_admin` (deps.py), зверю-таблица + модалка в TMA |

Взаимозависимости: F-7 — фундамент (chat_params/RBAC/chat_keys/X-Chat-Id/params-meta);
F-9 и F-10 пишут в `chat_params.gates` через единый патч-метод F-7 `set_chat_params`;
F-11 и F-12 построены поверх F-7/F-10; F-8 — независимый UI-фикс-слой.
**Все 6 фич раунда 10 (F-7…F-12) — archived** (`plans/archive/<feature>/{spec.md,tasks.md}`);
plans/features/ — снова 6 старых активных (F-1…F-6).

### Финал раунда — ключевые факты

- **Фиксы по ревью:** R1 (chat-scope EDIT требует chat-грант local_admin|moderator
  этого чата или global-ранг — `access.py::can_edit_param`), R6 (per-call BYOK-резолв
  `_resolve_api_key_and_source(chat_id)` без `_byok_chat_id`-инстансного стейта),
  S1–S3 (config-глобальный путь по ролям; `_mask_key_for_role` — `{configured,last4}`
  глобального только global-admin; модератор/юзер без chat-гранта — read-only);
  R17 — raw-ключи никогда не логируются/не отдаются.
- **Девиансия M-F-9 (08.09.2026, вариант (а)):** alan — master-only; `reactions.alan_mimic_enabled`
  остаётся легаси-выключателем common-мимикрии на Леху (нужны ОБА флага), в реестр модуля не входит
  (обоснование: прод-сид False выключил бы живое приветствие Лехи после бэкфила master ON).
- **RUNTIME WARNING соблюдён:** SQLite остаётся v8 (новых миграций нет — только идемпотентные
  PG-DDL: `bot_roles.role_type`, `param_permissions`, `chat_keys`, `chat_usage`, `worker_budget`,
  ALTER `chat_admins`/`chat_profiles`/`chat_lore_history`-CHECK); порядок роутеров bot.py,
  `hot.get`/ConfigCache, LEGACY/PREV-каноны — без дифов.
- **Каталог:** REGISTRY 372→**383** (limits +9 в т.ч. `limits_worker` 7 + chat_global_key_budget_*,
  flags +1 `permsoc_enabled`, content +1 `no_key_reply`); группы 70→**71**; Settings 349→**359**.
- **DevOps runbook ВЫПОЛНЕН (08.09.2026):** PG-DDL прогнан (`[pg_db] DDL ok`, 8 таблиц),
  роли засеяны (admin/moderator/user/local_admin), `scripts/backfill_permsoc_gates.py` success
  (gates.permsoc=True), `scripts/backfill_feature_gates.py` success (chat=-1002661910336:
  dream=False, lore_auto=True, nostalgia=False, opt_in=True); live-верификация — post-deploy
  journal чист (без Traceback/ERROR/CRITICAL, только пре-существующий betterstack/Logtail 401).
- **Известные follow-up (вне раунда):** тест-гап `backfill_permsoc_gates.py` (нет прямых
  unit-тестов бэкфила — только детерминированное правило), проверка имени CHECK-ограничения
  `chat_lore_history` на проде (field='gates'/'chat_keys' — DDL-имя под live-верификацию),
  предложение расширения `deploy_v2.9.2.py` (шаблон деплоя: DDL + бэкфилы + live-гистограммы).

### Раунд 10 — закоммичен и задеплоен (08.09.2026)

- **Коммиты (master):** `69be94e` feat(admin,web,chat): Multi-Chat раунд 10 — RBAC и BYOK
  (chat_params-слой, param_permissions), PERMsoc-изоляция, фичи-гейты и бюджет воркеров, TMA
  (5 секций, прогрессивное раскрытие, Oversight), UI-фиксы + docs(readme) (тесты 4717)
  — 89 файлов, +8932/−216; `533bf13` fix(scripts): бэкфиллы раунда 10 — DSN из
  os.getenv(POSTGRES_DSN) вместо несуществующего settings.POSTGRES_DSN (деплой: AttributeError,
  pg_db-резолв) — 2 файла.
- **Пуш:** origin/master; local master HEAD == origin/master ==
  `533bf13f421025dc3c9c900bd0fc798d0236521a`.
- **Деплой (198.46.175.136:/var/www/admin_bot):** `git pull` fast-forward до 533bf13; .env без
  изменений (только API_TOKEN — новых переменных не требуется); `systemctl restart admin_bot` OK
  (старый процесс — SIGKILL по таймауту, пре-существующее поведение; новый инстанс чист);
  status active (running), PID 133710.
- **Прод-состояние:** `[pg_db] DDL ok` (8 таблиц); роли засеяны (admin/moderator/user/local_admin);
  `backfill_feature_gates.py` done (chat=-1002661910336: dream=False, lore_auto=True,
  nostalgia=False, opt_in=True); `backfill_permsoc_gates.py` done (gates.permsoc=True);
  post-deploy journal чист (без Traceback/ERROR/CRITICAL).
- **README.md:** строка версии — тесты 4717, бейдж «Раунд 10», новый раздел «Multi-Chat, RBAC
  и BYOK (раунд 10)», TMA-таблица перестроена (5 секций меню), +3 пункта «Известные нюансы».
- **Follow-up (известные):** betterstack/Logtail 401 в journal — LOGTAIL_SOURCE_TOKEN невалиден
  в .env (пре-раунд-10, не регрессия); graceful-stop SIGKILL по таймауту (пре-существующее
  поведение); plans/MEMORY.md untracked намеренно (в коммиты раунда не входит).

### Хотфикс 10.1 — закоммичен и задеплоен (08.09.2026)

Post-deploy багфиксы TMA по рекону `recon: tma-round10-postdeploy-bugs` (БГ1–БГ4).
- **Коммит (master):** `8eae899` fix(admin,web): TMA хотфикс 10.1 — пустые вкладки
  (basicItems/advancedItems), логи (сверху свежие, клик-копия, шрифт 0.7rem), лор (ленивые
  аватары, каскад имён, скролл/фулскрин), Модули и Фичи (бюджет всегда) + docs(readme)
  (тесты 4726) — 8 файлов, +436/−151, поверх `533bf13`; local HEAD == origin/master ==
  `8eae8992a55a9a09255c345018d909759121a04b` (подтверждено git rev-parse).
- **Фиксы (review PASS, миноры закрыты):** (1) пустые конфиг-вкладки — реализованы
  `basicItems`/`advancedItems`, прогрессивное раскрытие Basic/Advanced работает (БГ1);
  (2) логи — `scrollTop=0` (сверху свежие), клик по строке = копирование, off-screen
  textarea-фолбек, шрифт `.log-code` 0.70rem (БГ2); (3) лор — обогащение топ-50 (было топ-30),
  ленивые аватары 300ms stagger, каскад имён alias→nickname→username→id (порядок — минор
  ревью), высоты панелей + fullscreen-mode (БГ3); (4) Модули и Фичи — бюджет виден всегда
  (без выбранного чата), плейсхолдеры + optInCount, master-тумблер disabled без чата (БГ4);
  миноры ревью: template filter → methods, lazy-фильтр исключает топ-50.
- **Тесты:** 4726 passed / 0 failed (4717 + 9 новых в 4 test_webapp-файлах).
- **README.md:** «Тестов: 4726 | Раунд: 10 (хотфикс 10.1 — TMA снова открывается)»,
  абзац «Хотфикс 10.1 — бот взял себя в руки», счётчик раундов +9.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 8eae899; .env БЕЗ изменений
  (API_TOKEN присутствует; PERMSOC_ENABLED/WORKER_* не нужны — работают дефолты);
  restart OK; active (running) PID **159455**, since 2026-09-07 16:27:04 UTC; journal чист
  (DDL ok, polling, webapp lifespan, без Traceback/CRITICAL).
- **Follow-up: НОВЫХ НЕТ.** Пре-существующие (не регрессия): betterstack/Logtail 401
  (LOGTAIL_SOURCE_TOKEN невалиден), graceful-stop SIGKILL-after-timeout.

### Раунд 10.2 — фиксы (09.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d30b203)

По рекону `recon: tma-bugs-7-post-10.1` (7 багов TMA от юзера; bug 8 — диск
сервера, DevOps вне кода). HEAD == origin/master == `d30b203` (был 8eae899).

- **Статус: COMPLETED + DEPLOYED.** Коммит + пуш + деплой выполнены 09.09.2026
  (см. «Раунд 10.2 — финал» ниже). планы-док plans/MEMORY.md остаётся
  untracked намеренно.
- **Фиксы (все 7 закрыты):**
  (1) селектор чата всегда виден для админов + кнопка/дропдаун «Выбрать чат»
  в шапке и empty states (`bug: tma-chat-selector-hidden`);
  (2) сайдбар скроллится — md:sticky md:h-screen md:overflow-y-auto + mobile
  overflow-y:auto (`bug: tma-sidebar-noscroll`);
  (3) НОВАЯ вкладка «Функции PERMsoc» — группы каталога
  `flags_permsoc`/`reactions_admin`/`reactions_permsoc`, TAB_PERMSOC,
  TABS-зеркало с except-списками, master-карточка + бейджи модулей + сводка
  modules_feats; runtime `services/permsoc.py` не тронут (`bug: tma-nopermsoc-tab`);
  (4) аватары — транзиентные Bot API ошибки НЕ в негатив-кэш; каскад имён
  alias→nickname(очищенный)→username(без @)→id (`bug: tma-relations-names-avatars`);
  (5) пустые «(0)» секции скрыты — v-if advancedItems>0, группа v-if
  basic||advanced (`bug: tma-empty-advanced-accordion`);
  (6) права → FLAGS-модель {view_roles, edit_roles}: DEFAULT_MATRIX —
  keys `[]`/`[]`, prompts `[local_admin]`/`[local_admin]`, прочие
  `[moderator,local_admin]`/`[local_admin]`; legacy-нормализация;
  DELETE `/api/access/param_permissions/{key}` = сброс; модалка с
  чекбокс-строками + «Сбросить на дефолт»; глобальный админ имплицитно
  (`bug: tma-perm-flags-ui`);
  (7) clipboard-ghost — одно переиспользуемое скрытое textarea
  (`bug: tma-invisible-copy-field`);
  (8) код-часть фикса диска: MEMORY_BACKUP_KEEP дефолт 7→1 + hot-лимит
  `limits.memory_backup_keep`.
- **Файлы (26):** web/app.js, web/index.html, services/access.py,
  services/param_catalog.py, web/api/access.py, web/api/routes.py,
  web/api/chat_lore.py, web/api/avatars.py, services/memory_backup.py,
  config/settings.py; 12 тест-файлов (test_access, test_webapp_api,
  test_webapp_rbac_ui, test_chat_params, test_frontend_tab_mapping,
  test_param_catalog, test_webapp_nav_disclosure_ui, test_webapp_avatars_ui,
  test_webapp_tma_fixes_ui, test_relations_service, test_memory_backup,
  test_settings_helpers); 4 plans-дока (backlog.md «Ре-дизайн 10.2» +
  archive spec-ы multi-chat-rbac-byok / permsoc-module-isolation /
  tma-ia-progressive-disclosure).
- **Тесты: 4759 → 4760 passed / 0 failed** (финал подтверждён прогоном;
  +1 тест «ID никогда не отображается как имя»; ранее 4759 в .venv — 64.00s,
  1 StarletteDeprecationWarning пре-существующий). Только .venv: системный
  python/py не имеет `ijson` → collection error в test_history_loader/parser.
- **Замечание ревью (APPROVED):** имена отношений as-is — ID никогда не
  отображается как имя (никогда не показывать идентификатор); каскад имён
  alias→nickname raw→username(без @)→''; avatarInitial — графема.
- **Диск сервера (DevOps, уже исправлено на проде 09.09.2026):** освобождено
  ~5.8G (16G→10G used); бэкапы ротированы до 1 через `/root/bak/rotate_bak.sh`
  + root cron 03:10 daily; journal SystemMaxUse=200M; очищены /home/nik/.cache,
  /tmp, apt cache, btmp; главные подозреваемые — /var/www/admin_bot/backups
  (2.8G) + /home/nik/backups_adminbot (2.0G); migrate_history 1.1G — данные,
  не кэш (сохраняется); рекомендация fail2ban; `limits.memory_backup_keep=1`
  теперь применим через hot config. Виновник бэкапов — ежедневный VACUUM INTO
  после импорта истории.

### Раунд 10.2 — финал (09.09.2026)

- **Коммит (master):** `d30b203` fix(admin,web,api): раунд 10.2 — раздел
  «Функции PERMsoc», права-флаги (view/edit_roles), фиксы TMA (селектор чата,
  скролл сайдбара, пустые секции, копи-поле), имена отношений as-is (ID не
  имя), лимит бэкапов 1 + docs(readme) (тесты 4760) — **28 файлов, +1576/−314**,
  поверх `8eae899`; local HEAD == origin/master == `d30b203` (подтверждено
  git rev-parse); `git diff --check` чист.
- **Тесты:** 4760 passed / 0 failed (было 4759; +1 тест «ID никогда не имя»).
- **Ревью:** APPROVED (@Reviewer) — имена отношений as-is: ID никогда не
  отображается как имя; каскад alias→nickname raw→username(без @)→'';
  avatarInitial — графема.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до d30b203; бот
  active (running), PID **454654**; [pg_db] DDL ok; polling активен; webapp 200
  с разделом «Функции PERMsoc»; БЕЗ Traceback после рестарта; .env без
  изменений.
- **README.md:** тесты 4760, бейдж «Раунд 10.2», раздел «Функции PERMsoc»
  (абзац), security-буллет в «Мониторинг», нюанс про имя (ID не отображается).
- **Следующие шаги (10.2):** закрыты; новые follow-up — только security-слой
  (см. «Безопасность сервера» ниже).

## Безопасность сервера (fail2ban / ufw / SSH-харденинг, 09.09.2026)

Применено DevOps на 198.46.175.136 (Ubuntu 24.04.4, OpenSSH 9.6p1),
research-based (референсы: fail2ban issues #3785/#3812 для OpenSSH 9.8 —
неактуально на 9.6p1, работает; ufw порядок правил). **Активно.**

- **fail2ban 1.0.2** (`/etc/fail2ban/jail.local`): backend=systemd,
  banaction=nftables, bantime 1h + increment до 1w; jail `sshd`: maxretry=3,
  bantime=24h, findtime=10m, journalmatch=_SYSTEMD_UNIT=ssh.service +
  _COMM=sshd + _SYSTEMD_UNIT=ssh.socket; jail `recidive`: 1w/1d/3.
  Живой бан подтверждён: **176.53.159.197** (nft f2b-table); фильтр — ~65k
  матчей; btmp сокращён (было 44M/3д).
- **ufw:** default deny incoming; 22/tcp LIMIT IN; 80/443 ALLOW. Снаружи
  открыты только 22/80/443; закрыты: 4416 (bgutil POT), 8000, 8081, 9000,
  5432, 2019, 10808 (проверено извне — timeout).
- **SSH `/etc/ssh/sshd_config.d/00-hardening.conf`:** PermitRootLogin no,
  MaxAuthTries 3, LoginGraceTime 20, MaxStartups 10:30:60, MaxSessions 3,
  ClientAliveInterval 300/2, X11Forwarding no, LogLevel VERBOSE, DebianBanner no;
  `sshd -t` + reload OK. **Password auth сохранена** (требование владельца),
  порт 22 не менялся. Lockout не произошёл.
- **Follow-up (решения владельца):** миграция на SSH-ключи (key migration
  proposal); добавить IP владельца в `ignoreip`, если он статический;
  CrowdSec как альтернатива fail2ban; перенос `migrate_history` (1.1G) вне
  диска.

## Свежие архивы (plans/archive/ — 15 папок)

- `multi-chat-rbac-byok` — **Раунд 10, 08.09.2026** (F-7, T-843…T-869: RBAC-роли + chat_params-слой + BYOK + бюджеты; §22)
- `tma-ui-fixes` — **Раунд 10, 08.09.2026** (F-8, T-870…T-877: 8 UI/UX-фиксов TMA; §22)
- `permsoc-module-isolation` — **Раунд 10, 08.09.2026** (F-9, T-878…T-889: плагин PERMsoc + девиансия M-F-9 (а); §22)
- `feature-gates-worker-budget` — **Раунд 10, 08.09.2026** (F-10, T-890…T-902: Opt-In-гейты + worker-бюджет; §22)
- `tma-ia-progressive-disclosure` — **Раунд 10, 08.09.2026** (F-11, T-903…T-913: IA/меню 5-секций + прогрессивное раскрытие; §22)
- `global-oversight-dashboard` — **Раунд 10, 08.09.2026** (F-12, T-914…T-924: Oversight + kill-switch; §22)
- `agi-memory-implementation` — Раунд 9, 06.09.2026 (relations A-Life, сон, ностальгия, dig_into_lore, канон R9; ARCHITECTURE §21)
- `context-layer-x-features` — Раунд 8 (24 пункта CONTEXT_RESEARCH; §20)
- `chat-lore-management-v2` — Раунд 7 (PG chat_profiles, TMA «Лор чатов»; §19)
- `history-import-hybrid-memory` — Раунд 6 (FTS5 + GraphRAG, миграция v7; §18)
- `betterstack-lore-prompts-round5` — Раунд 5 (§17)
- `betterstack-own-handler-video-memory-cmds` — Раунд 4 (§16)
- `multimodal-summarization-tools-reactions-ui` — Эпик 04.09 (§13)
- `tg-video-tool-calling-fixes` — Bugfix 04.09 (§14)
- `video-multimodal-pipeline-and-incidents` — Раунд 3 (§15)

## Research (plans/docs/)

`multi-chat-scaling-research.md` (07.09.2026 — ИСХОДНИК раунда 10, вариант A),
`prod-params-audit-2026-09.md`, `memory-project-overview.md`,
`CONTEXT_RESEARCH.md`, `agi-memory-research.md`, `chat-lore-management-research.md`,
`sqlite-to-pg-research.md`, `factcheck-audit.md`, `memory-import-research.md`,
`research-directchat-digest.md`, `canon/` (architecture.md, backlog.md).

## Граф: краткий обзор (узел AdminBot + feature-*)

- **adminbot-backend** — aiogram 3.31 (polling) + FastAPI (`web/app.py`) + asyncpg + aiosqlite; APP_VERSION=2.51.0; порядок роутеров bot.py: slava_presence → alan_greeting → kostik → alan → dead_page → war_alert → common → olya → slavik → vasya (без изменений). F-12 добавил oversight-API (web/api/oversight.py), F-7/F-10 — access/gates/budget-роуты.
- **adminbot-pg-schema** — `bot_settings` (key/value JSONB/category), `bot_roles` (permissions JSONB; F-7 добавил `role_type`), `bot_admins`, `chat_profiles` (manual/auto лор + `relations` JSONB; **F-7 добавил `chat_params` JSONB**, **F-10 добавил `gates_opt_in`**), `chat_lore_history` (F-7 расширил CHECK поля: chat_params/chat_keys/gates), `chat_links`, `chat_admins` (F-7 добавил `role_name`), `uptime_events`. **Новые таблицы раунда 10: `param_permissions`, `chat_keys`, `chat_usage`, `worker_budget`** (итог — DDL-код в `services/pg_db.py`, прод-DDL @DevOps).
- **adminbot-sqlite-schema** — `users_meta` (стадии отношений), `smart_messages` (FTS5), `nodes/edges`, `graph_facts` (v1–v8), `dream_state`, `memory_dream_log` (бюджет суток), `nostalgia_log` и др. Миграция памяти sqlite→PG ЗАМОРОЖЕНА (04.09.2026). Вне скоупа раунда 10.
- **hot-config-layer** — `services/hot_config.py::hot.get(pg_key, default)`; ConfigCache (`services/config_cache.py`) — in-memory над PG, R6 fail-open. Цепочка глобальная; **F-7 добавил per-chat слой `hot_chat` (chat_params → bot_settings → дефолт) параллельно — hot.get/ConfigCache не менялись**.
- **llm-client-key-resolution** — `services/llm_client.py`; ключ: `hot.get("keys.llm_api_key", settings.LLM_API_KEY)`; фоллбэки `keys.llm_fallback_api_key` + embed-каскад (Google AI Studio, 2 ключа). **F-7 добавил BYOK: `_resolve_api_key_and_source(chat_id)` — свой ключ чата → allow_global=false → бюджет → глобальный; sandbox `content.no_key_reply` (фикс R6: per-call, без инстанс-стейта).**
- **param-catalog** — `services/param_catalog.py` REGISTRY ParamSpec; F-7 добавил поле `per_chat` (whitelist), F-11 — `progressive_level`, F-9/F-10 — новые ключи (`flags.permsoc_enabled`, `limits.worker_daily_*`, `limits.chat_global_key_budget_*`, `content.no_key_reply`). Итог: REGISTRY 372→383, группы 70→71, Settings 349→359.
- **rbac-v2** — `services/permissions.py` + неймспейсы `section./param./key./action.`; GET /api/config маскирует секреты {configured,last4}; POST — per-key права. **F-7 расширил: role_type-иерархия (services/roles.py), access_for, param_permissions, локальные чат-роли (chat_admins.role_name)**; `permissions.py` остаётся чистым матчером.
- **tma-frontend** — Vue 3 global (без сборки): `web/index.html` + `web/app.js` + FastAPI `/api/*`. Вкладки: LLM Провайдеры, Промпты, Лимиты, Память и RAG, Реакции и Триггеры, Доступы, Лор чатов, Статус, Как это работает. **Раунд 10 реализован: F-8 (UI-фиксы) + F-11 (навигация 5 меню + селектор чатов + прогрессивное раскрытие + вкладка modules_feats) + F-12 (oversight) поверх F-7 (X-Chat-Id, роль-пикер, BYOK-поля).** **Хотфикс 10.1 (8eae899):** закрыты БГ1–БГ4 рекона — `basicItems`/`advancedItems` (+ прогрессивное раскрытие на всех конфиг-вкладках), логи (scrollTop=0, клик-копия, 0.70rem), лор (топ-50, ленивые аватары 300ms, каскад имён alias→nickname→username→id, фулскрин), modules_feats (бюджет всегда).
- **legacy-triggers-permsoc** — Славик (479167456), Костя (350803143), Леха/Алан (138811255), Оля (834424825, единственный с флагом `flags.olya_enabled`), передразнивания (`flags.mimic_enabled`); ID в группе `reactions_persons`. **F-9 изолировал в плагин services/permsoc.py с master-гейтом flags.permsoc_enabled + PermsocGateFilter (девиансия M-F-9 (а): alan — master-only).**
- **background-workers** — LoreWorker, DreamWorker, NostalgiaWorker, Summary/Goodmorning/валер-подобные; бюджет сна — `memory_dream_log.tokens` за local-сутки. **F-10 перевёл тяжёлые фичи под жёсткий Opt-In (gates + gates_opt_in) + суточный ledger `worker_budget` (global/per-chat лимиты LLM-вызовов/токенов, деградация nostalgia→lore→dream).**
- **plans-structure** — см. разделы выше; раунд 10 ЗАВЕРШЁН: 6 фич F-7…F-12 (entity `feature-*` в графе, статус **archived**, ARCHIVED_IN plans-structure), 82 задачи T-843…T-924; plans/archive/ — **15 папок**; раунд закоммичен (69be94e + 533bf13,
HEAD == origin/master == 533bf13); **милстоун `round10.1-hotfix`** (AdminBot → COMPLETED,
FIXES tma-frontend, RESOLVES recon: tma-round10-postdeploy-bugs) — хотфикс 10.1 закоммичен
и задеплоен (8eae899, PID 159455), HEAD == origin/master == 8eae899;
**милстоун `round10.2-fixes`** (AdminBot → COMPLETED + DEPLOYED; RESOLVES
recon: tma-bugs-7-post-10.1; FIXES 7 bug: tma-*) — раунд 10.2 ЗАКОММИЧЕН и
ЗАДЕПЛОЕН (d30b203, 28 файлов, тесты 4760, PID 454654),
HEAD == origin/master == d30b203; **новый милстоун `server-hardening-102`**
(AdminBot → DEPLOYED) — fail2ban/ufw/SSH-харденинг 09.09.2026 (см. раздел
«Безопасность сервера» выше); **Раунд 10.3 (IMPLEMENTED — Merge Phase 10.09.2026)**: 3 фичи
F-13 tma-chat-selector-fixes + F-14 dm-user-settings + F-15
direct-sandbox-budget-investigation (T-925…T-973; милстоун `round10.3-epic`,
AdminBot → IMPLEMENTED (PENDING_COMMIT), PART_OF-связи всех 3 фич, AdminBot HAS_PLAN → каждая;
ARCHITECTURE.md §23/§24; финальный синк графа/архив — шаг 10 @Memory;
plans/features/ — **9 активных**: F-1…F-6 + F-13 + F-14 + F-15; все spec.md/tasks.md
на диске с 09.09.2026).

## Факты для планирования (проект)

- HEAD промпт-каноны живут в `plans/docs/canon/`; миграции промптов — `services/prompt_migrations.py`.
- Отношения: manual-стадии в PG `chat_profiles.relations`, авто — SQLite `users_meta.relationship_stage`.
- Тумблеры персоналий по умолчанию выключены только для kucha/mimic/olya; сон/ностальгия/авто-лор — включены по умолчанию (раунд 10 перевёл на жёсткий Opt-In — F-10: `gates_opt_in` + `chat_params.gates`).
- Раунд 10, F-7 (Q5, РЕАЛИЗОВАНО): `per_chat=True` = категории {prompts, limits, flags, reactions, content, memory} и secret=False; `models.*`/`keys.*` — строго глобальные.
- Раунд 10, F-7 (R17/инвариант 2, РЕАЛИЗОВАНО): локальный админ НЕ видит глобальный ключ ни в каком виде; raw-ключи никогда не логируются/не отдаются (S1/S2/S3, R17-аудит).
- Раунд 10, F-9 (Q3, РЕАЛИЗОВАНО): дефолт новых чатов — permsoc OFF; живые чаты включаются бэкфилом `scripts/backfill_permsoc_gates.py` по правилу (-1002661910336 / relations_enabled / manual|auto_lore / chat_admins).
- Раунд 10, F-12 (Q2, РЕАЛИЗОВАНО): приоритет гейтов — явный chat-гейт → `hot.get('flags.<feature>_enabled')` → False; kill-switch = явный `gates[feature]=false`.
- **Follow-up раунда 10 (вне цикла):** unit-тест-гап `backfill_permsoc_gates.py` (прямых тестов бэкфила нет); live-проверка имени CHECK-ограничения `chat_lore_history` на проде (field='gates'/'chat_keys'); предложение расширения `deploy_v2.9.2.py` (DDL + бэкфилы + live-гистограммы при деплое).
- **Follow-up безопасности сервера (ожидают решения владельца):** миграция на SSH-ключи (key migration proposal — password auth пока оставлена по требованию); добавить IP владельца в fail2ban `ignoreip`, если он статический; CrowdSec как альтернатива fail2ban; перенос `migrate_history` (1.1G) на другой диск/раздел.
