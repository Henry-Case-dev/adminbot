# AdminBot — Memory Index (plans/MEMORY.md)

Индекс долговременной памяти. Архитектура — `plans/ARCHITECTURE.md` (§1–§27);
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
> **Синк STEP 10 (финал) 10.09.2026: раунд 10.3 ПОЛНОСТЬЮ ЗАВЕРШЁН** — HEAD ==
> origin/master == `1410a68` (коммит 09.09.2026 12:33 UTC, автор Henry), тесты
> **4831 passed / 0 failed**, @Reviewer APPROVED, Scanner 0 blocker/major
> (R10.3-1…R10.3-6 → ARCH §24); деплой 09.09.2026 (рестарт 12:37 UTC, active);
> прод-диагностика задачи 5 проведена (чат -1002661910336 без своего ключа,
> глобальный ключ 25/25 → sandbox R16, сброс бакета 00:00 Екб — детали в KG
> `recon: direct-chat-sandbox-budget`); F-13/F-14/F-15 заархивированы
> (plans/archive/ — **18 папок**, plans/features/ — снова 6 активных F-1…F-6);
> MEMORY.md ВПЕРВЫЕ вошёл в коммит; граф обновлён (милстоун `round10.3-epic` →
> COMPLETED+DEPLOYED, фичи → ARCHIVED_IN/WAS_PART_OF). Цикл раунда полностью закрыт.
> **Step 0 recon 10.09.2026 (раунд 10.4, 9 пунктов ТЗ реструктуризации TMA):**
> RESEARCH ONLY — дерево чистое (только plans/MEMORY.md modified, остаток шага 10),
> HEAD == origin/master == `1410a68`. Изучены структура миниаппа (TABS/MENU_ORDER/
> generic-рендер, web/app.js + web/index.html), каталог параметров (REGISTRY 383 /
> 71 групп / Settings 359, TAB_RULES param_catalog.py:1374-1406, паттерн добавления
> раздела), локализованы все 9 пунктов ТЗ по группам/ключам. Всё зафиксировано —
> KG-сущность **`recon: tma-structure-10.4`** (полные координаты, реестры ключей
> реакций/лимитов/памяти/провайдеров/отношений, тест-риски, конфликты с F-1…F-6).
> Планирование — @PM (конфликт-матрица не строилась).
> **Синк STEP 3 (планирование 10.4) 10.09.2026:** раунд 10.4 распланирован и
> **ЗААРХИТЕКТИРОВАН** — **8 фич** (plans/features/, spec.md @Architect + tasks.md
> @PM для каждой, стадия ARCHITECTED, Builder не начат): **D**
> `frontend-advanced-collapse-default` (T-1018…T-1023), **C**
> `frontend-memory-sleep-nostalgia` (T-1006…T-1017), **E**
> `frontend-llm-providers-layout` (T-1024…T-1032), **A**
> `frontend-reorg-modules-reactions` (T-974…T-989), **B**
> `frontend-limits-temperature-budgets` (T-990…T-1005), **F**
> `frontend-relations-participants` (T-1033…T-1044), **H**
> `backend-relations-nickname` (T-1057…T-1065), **G**
> `backend-chat-1002661910336-scaling` (T-1045…T-1056) — итого T-974…T-1065
> (92 задачи). Порядок исполнения: **D → C → E → A → B → F → H → G** (обоснование:
> D — аккордеоны первыми; C/E/A — реструктуризация вкладок после D; B — per-chat
> алиасы/виджет ДО F и H; H — фикс каскада после B; G — деплой-бэкфил последним).
> Ключевое: REGISTRY **383/71/359 ЗАМОРОЖЕН** по всем 8 фичам (MED-017 — только
> переносы/разметка/поля виджета select); SQLite v8, порядок роутеров bot.py,
> каноны промптов, known_sections() — без дифов; R16/R17 сохранены; **девиансия
> D-A1** (фича A: war/common/goodmorning/word_reactions ТАКЖЕ переезжают в
> «Функции PERMsoc» — канон спеки §2, шире tasks.md T-975); общий новый тест
> `test_progressive_tab_basic_coverage` (≥1 basic-группа на каждую config-вкладку;
> пишется в D, зелёный после C/E/A; MED-022-маркеры обновляются в каждой
> фронт-фиче). Конфликт-матрица с F-1…F-6 зарегистрирована в backlog.md:
> **F-1 ДО B/G** (атомарный POST, касты T-651/652, NaN T-654), **F-3 T-663 ПОСЛЕ
> раунда** (DM-перепроверка), **F-4 Баг-4 ПОСЛЕ раунда** (сверка по новой карте
> вкладок), **F-5 ПОСЛЕ G/B** (реестры новых read-путей), **F-6 SUPERSEDED_BY
> round10.4** (аудит каскада → H T-1058/1059/1063, live-эффект → B T-1005,
> верификация → владельцу). Граф обновлён (Step 3): AdminBot HAS_PLAN → 8 фич,
> милстоун `round10.4-epic` → ARCHITECTED (PLANNED_IN/ARCHITECTED_IN plans-structure),
> цепочка DEPENDS_ON D→C→E→A→B→F→H→G; наблюдения добавлены в param-catalog
> (TAB_RULES-реструктуризация), DirectChatService (бюджеты B + overrides G),
> chat-lore (каскад имён H + перенос F), plans/features/user-aliases-admin
> (SUPERSEDED_BY).
> **Merge Phase 10.4 (10.09.2026, @Architect)** — 8 фич раунда (D/C/E/A/B/F/H/G,
> T-974…T-1065) IMPLEMENTED в рабочем дереве (HEAD 1410a68 + 10.4: 24 модифицированных
> файла, 8 новых фич-папок, 2 backfill-скрипта `scripts/backfill_104_{chat_flags,overrides}.py`,
> 2 новых тест-файла), @Reviewer APPROVED, Scanner-аудит 10.4: **0 blocker/major**
> (minor/info R10.4-1…R10.4-7 → ARCHITECTURE.md §25; R10.4-1/-2/-3 закрыты
> follow-up @Builder и сверены), pytest **4860 passed / 0 failed** (4831 → +29),
> `node --check web/app.js` clean, `git diff --check` чист. ARCHITECTURE.md обновлён:
> **§24** (раунд 10.4: карта вкладок — PERMsoc 17 групп/Модули/Память+Сон+Ностальгия/
> секции LLM Провайдеров/Имена людей/Участники и отношения/Лор-расширенные; select-виджет
> (widget='select' + select_options/select_labels, 422); бюджет-флаг per-chat
> `chat_context_budgets_enabled` + backfill_104_chat_flags (-1002661910336 off);
> `build_alias_resolver(chat_id)` per-chat/ЛС алиасы; аккордеоны «Расширенные» свёрнуты
> по умолчанию (expandOpen+персист); каскад имён username-всем строкам (Semaphore 5,
> кэш 1ч, фото топ-50, R16); per-chat скейлинг -1002661910336 — 15 ключей ×1.5–×2,
> backfill_104_overrides, `_resolve_from_root` _cast_type_ok+isfinite, граница G-4,
> KPI 25 req → флаг бюджетов off) + **§25** «Известные ограничения и техдолг»
> (R10.4-1…R10.4-7 со статусами + обновлённые R10.3-*); кросс-указатели §3/§4/§9/§16
> (+ исправлен счётчик групп каталога **71→74** — ре-дизайн 10.2 BUG-3 +3 группы;
> сверка: GROUPS=74 на HEAD и в 10.4). Локальные спеки 8 фич НЕ тронуты (архивная
> фаза — @PM); коммит/деплой + прогон обоих бэкфилов (@DevOps) — финальный шаг раунда.
> **Финальный синк KG/графа, статусов милстоуна `round10.4-epic` и архивирование —
> шаг 10 @Memory.**
> **Синк STEP 10 (финал, post-commit+деплой) 10.09.2026: раунд 10.4 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `0bdf272` (feat(admin,web,chat,api):
> раунд 10.4 — реструктуризация админки (Модули/PERMsoc/Память/Сон/Ностальгия/
> Провайдеры/Отношения), бюджеты per-чат и температура-select, имена людей
> per-чат/ЛС, каскад имён, лимиты ×1.5-×2 для -1002661910336); тесты **4860 passed /
> 0 failed** (4831 → +29), @Reviewer APPROVED, Scanner 10.4 **0 blocker/major**
> (minor/info R10.4-1…R10.4-7 → ARCHITECTURE.md §25; R10.4-1/-2/-3 закрыты follow-up
> и сверены); деплой 10.09.2026 (198.46.175.136): git pull, **.env +=
> CHAT_THREAD_MAX_CHARS=2000**, **бэкфилы применены** — backfill_104_chat_flags.py
> (флаг бюджетов OFF для -1002661910336) + backfill_104_overrides.py
> (15 ключей ×1.5–×2), рестарт, bot active; ARCHITECTURE.md §24 (карта вкладок/
> бюджеты/каскад имён) + §25 (техдолг R10.4-*, B-13 points 2-4, HIGH-004-остаток);
> 8 фич заархивированы (@PM) — plans/archive/ **26 папок**, plans/features/ снова
> 6 активных F-1…F-6; README тесты 4860; граф обновлён (round10.4-epic →
> **COMPLETED+DEPLOYED**, 8 фич → ARCHIVED_IN/WAS_PART_OF, HAS_PLAN/PLANNED_IN/
> ARCHITECTED_IN удалены, создан `tech-debt-round10.4`). Цикл раунда полностью закрыт.
> **Синк STEP 3 (планирование 10.5) 10.09.2026:** раунд 10.5 «Редизайн TMA по
> референсу Relume + гигиена репозитория» распланирован и **ЗААРХИТЕКТИРОВАН** —
> фича **`tma-relume-redesign`** (`plans/features/tma-relume-redesign/`):
> `tasks.md` @PM (T-1066…T-1089, продолжает T-1065), `reference-analysis.md` @PM
> (recon-разбор референса, стадия ANALYSIS), `spec.md` @Architect (686 строк,
> §0–§11). Референс `relumesite_example/` — статический Relume-экспорт (15 страниц,
> 0 input/form/table) ⇒ редизайн визуальный + IA, не функциональный порт; ~90%
> функциональности уже есть (18 вкладок в 5 секциях MENU_ORDER). T-1066 (гигиена)
> **ВЫПОЛНЕНО** — `.gitignore += relumesite_example/` (отдельный раздел),
> `media/` НЕ тронут (политика project.md). ⏸ Решения **D1–D8** требуют владельца
> (рекомендации @Architect: C hybrid / поэтапно / остаться на Vue3 global / палитра
> P3 teal `#14CBB6` на dark `#161616` / emoji now + Material Symbols follow-up /
> Чат-Профиль на усмотрение / B1-B2 отложить / hash-роутинг при C); секция E
> (реализация) заблокирована до апрува D1 (T-1076). Конфликт-матрица с F-1…F-6:
> **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ редизайна 10.5**, F-1/F-2/F-3/F-5
> независимы, F-6 SUPERSEDED_BY round10.4. Граф обновлён (Step 3): entity
> `tma-relume-redesign` обогащена (+5 наблюдений: артефакты, инварианты/фазы/AC,
> `.gitignore`-гигиена, D1–D8, конфликт-матрица; дублей нет — добавлено в
> существующую сущность @Architect), создано 7 связей: `AdminBot HAS_PLAN
> tma-relume-redesign`, `CONFLICTS_WITH plans/features/frontend-admin-bugfixes`,
> `RELATED_TO` ×5 (post-deploy-admin-minors, admin-debug-webview,
> scam-incident-security-followup, config-read-path-audit, user-aliases-admin).
> Следующий шаг — решение владельца D1–D8 → @Builder секция E.
> **Синк STEP 3 (design-project) 10.09.2026 (вечер):** главный deliverable раунда
> 10.5 ГОТОВ и находится на **GATE** — `plans/features/tma-relume-redesign/design-project.md`
> (835 строк, RU, §0–§14; статус 🟡 DESIGN/GATE). `spec.md` → **v2** (согласован с
> решениями владельца **OD1–OD6**, которые отменяют/заменяют рекомендации spec v1 и
> прежние D1–D8); `tasks.md` секция **E (T-1090…T-1097) ✅ ВЫПОЛНЕНО**; секции
> **F/G (T-1098…T-1118) ⛔ заблокированы до явного апрува владельцем**. **OD1–OD6
> (LOCKED):** OD1 навигация = **вариант B, ПОЛНЫЙ ребейлд** по модели эталона
> (navbar 6 пунктов + hub-карточки + отдельные экраны); OD2 **big-bang всё сразу**
> (внутренний порядок токены→shell/navbar→hubs→15 экранов→QA); OD3 **та же
> технология** (Vue3 global / zero-build, единый `index.html`+`app.js`); OD4 палитра
> эталона как база + **АНИМИРОВАННЫЕ плавные градиенты** (reduced-motion + WCAG AA);
> OD5 **Material Symbols Rounded** primary + карта emoji-fallback; OD6 **структура
> эталона = ЭТАЛОН** композиции (15 страниц). **КРИТИЧНО:** hash-роутинг обязателен
> (следствие OD1+OD3); Telegram кладёт `initData` в `window.location.hash`
> (`#tgWebAppData=...`) — читать/кэшировать **ДО** первой записи `location.hash`,
> парсить только роуты с префиксом `#/`, **vue-router НЕ использовать** (ломает
> кодирование `tgWebAppData`, vuejs/router#2155). **Верифицированная коррекция:**
> в приложении **17 вкладок** `TABS` (`web/app.js:18-145`), а НЕ 18 (off-by-one в
> `tasks.md`/`spec.md`); паритет — «0 бездомных» из 17. **Предложения (§10):**
> **ADD A1–A10** (initData-guard, Telegram BackButton+deep-link, единые
> empty/error/retry, hub-карточки+drill-down, self-host subset Material Symbols,
> prefers-contrast:more, тема-переключатель 4 схемы, quick-search, скелетоны
> relations, breadcrumb); **REMOVE R1–R7** (sidebar как primary nav, хардкод
> `#8b5cf6/#3b82f6/#2b2b40`+Tailwind-токены, дубль локальных админов в `chat_lore`,
> emoji как основные иконки, отдельная navbar-секция «Чат-Профиль», Tailwind CDN
> runtime, 409 no-op reload); **OPTIMIZE O1–O7** (`@property inherits:false` → до
> 848% быстрее recalc, ограничение площади анимации + `contain:paint`, ленивые
> аватары R10.4-4, кэш params-meta/chats, namespace-модульность без разбиения файла,
> DM models read-only, единый fetch-слой); **NOT DO N1–N5** (bundler/vue-router,
> backend B1/B2, текст на движущемся градиенте, анимация за таблицами/формами/логами,
> изменения param_catalog/settings/SQLite v8/PG-DDL/порядок `bot.py`). Открыты
> **D6** (реком. свернуть «Чат-Профиль» в AI-hub), **D7** (реком. отложить B1/B2,
> B3 опц.), **D8** (реком. включить BackButton/deep-link). Exa-research успешен
> (6 тем: docs.telegram-mini-apps.com, core.telegram.org, W3C WCAG 2.3.3, web.dev
> @property, MDN, Google Fonts Material Symbols, admin IA). Граф обновлён:
> `tma-relume-redesign` +4 наблюдения (deliverable/status+GATE, OD1–OD6, proposals
> A/R/O/N, gotcha initData/17-vs-18); relation `HAS_DESIGN_PROJECT →
> tma-relume-redesign-design-project`; дублей нет (Voxy-сущности не затронуты,
> ничего не удалено). **Следующий шаг — владелец: D6/D7/D8 + GO → @Builder T-1098.**
> **Синк STEP 3 (догон, T-1119/T-1120) 10.09.2026 (вечер, @Memory):** доуточнения
> проекта по обратной связи владельца **ВЫПОЛНЕНЫ** — `tasks.md` секция **E2**:
> **T-1119 ✅** (Exa-research back-навигации) и **T-1120 ✅** (plain-language
> разъяснения D6 + B1/B2/B3); `design-project.md` (1105 строк) обновлён: **§0 TL;DR**
> (+п.9 «back без своей кнопки»), **§6.4 переписан** (нативный `Telegram.WebApp.BackButton`:
> `show()` на глубине >0 заменяет ✕ на ←, `hide()` на корне возвращает ✕ — один header-слот,
> конфликта нет; мы владеем history/stack, Telegram — header+OS-back; Android hardware-back
> эмитит `back_button_pressed` только при `is_visible=true`, иначе закрывает WebView;
> `onClick` регистрируется ОДИН раз → `goBack()` = детерминированный parent-route, НЕ
> `history.back()`, без popstate; единственный applier = `hashchange`; Bot API 6.1+),
> **§11** (+ **§11.1 D6**, + **§11.2 D7**), **§12** (Exa расширен **6→7 тем** + источники
> **§12.7**), **§13** (AC-5 routing переформулирован под нативный BackButton, AC-9 —
> Scanner re-check), **§14 GATE**. Новый маркер-тест `test_webapp_back_button` (§9.4).
> Тумблеры: `__TMA_BACK__=true` (решено), `__TMA_DEEPLINK__` (ждёт владельца, default false).
> **Статусы решений:** **D8 — RESOLVED-in-intent** (back-навигация подтверждена владельцем,
> паттерн определён); **D6/D7 — OPEN** (ждут решения владельца; рекомендации: свернуть
> «Чат-Профиль» в «Настройки AI» — 6 navbar-пунктов как в эталоне; B1/B2 отложить, B3
> опционально). **GATE остаётся ЗАКРЫТ** — 0 кода, реализация (F/G) не стартует до явного
> GO владельца + решения deep-link. Репо: HEAD `0bdf272`, worktree dirty (`.gitignore`,
> `plans/MEMORY.md`, `plans/backlog.md` modified; `plans/features/tma-relume-redesign/`
> untracked). Граф: обновлены `tma-relume-redesign`, `tma-relume-redesign-design-project`,
> `TMA BackButton navigation pattern`, `D6 D7 plain-language clarifications` (только
> добавление наблюдений; дублей нет; Voxy-сущности не затронуты).
> **Синк STEP 3 (v3, секция E3 — OD7–OD10) 10.09.2026 (поздний вечер, @Memory):** главный
> deliverable раунда 10.5 обновлён до **v3** — `design-project.md` **1105 → 1817 строк**,
> добавлен **§15** (15.1 scope-switcher/OD7, 15.2 key-availability/OD8, 15.3
> role-matrix/OD10, 15.4 font-delivery/D11, 15.5 deep-link/D9, 15.6 Q-NEW-1..5, 15.7
> трассировка E3); обновлены §0/§2/§3/§5/§7/§10/§11/§12/§13/§14. `tasks.md`
> **T-1121…T-1126 ✅ done (E3)**; `spec.md` согласован (v3-указатель, v2 частично
> SUPERSEDED). **OD7–OD10:** OD7 «Чат-Профиль» = глобальный scope-switcher GLOBAL/ЧАТ/ЛС
> (не 7-й nav-пункт); OD8 B1 key-availability В СКОУПЕ (in-memory ring, без PG-DDL/
> SQLite v8); OD9 B2 custom-modules CRUD OUT (read-only); OD10 B3 role-matrix В СКОУПЕ и
> расширена (per-param read/write + role CRUD). **Q-NEW-1..5** (каталог 383→385?;
> key-history in-memory vs persisted; deep-link; файл шрифта; delete/rename ролей?) и
> **D9/D11** открыты владельцу; font-delivery spec готова (§15.4: self-host woff2 subset
> `web/static/fonts/`, `@font-face`, CSP `font-src 'self'`, ~2–15 КБ, emoji-fallback).
> **GATE ЗАКРЫТ: 0 кода**, T-1127+ (F4) и F/G не стартуют без GO владельца. Граф обновлён:
> добавлены наблюдения в `tma-relume-redesign` (+5), `tma-relume-redesign-design-project`
> (+1), `tma-relume-redesign v3 design-project` (+7: §15-карта, Q-NEW, трассировка, gate);
> связи — `v3 SUPERSEDES design-project`, `tma-relume-redesign HAS_DESIGN_PROJECT v3`,
> `OD7-OD10 owner decisions DECIDES tma-relume-redesign`. Дублей нет; Voxy-сущности не
> затронуты; удалений нет.
> **Синк STEP 3 (v4, секция E4 — OD11–OD15, T-1136…T-1138) 10.09.2026 (@Memory):**
> главный deliverable раунда 10.5 ревизован **v3 → v4** — `design-project.md`
> **1817 → 2119 строк**, добавлен **§16** (16.1 hardcode-аудит H1–H22; 16.2 замеры
> шрифта; 16.3 персистентность истории; 16.4 роли; 16.5 **Q1–Q4**; 16.6 Scanner);
> обновлены шапка/§0 (пп.12–17)/§5.2/§6.4.5/§10.4 N5/§11/§13 (**AC-14…AC-18**)/
> §14/§15.2/§15.3/§15.4/§15.5/§15.8. `tasks.md` секция **E4 (T-1136/T-1137/T-1138)
> ✅ ВЫПОЛНЕНО**; **T-1139…T-1142 (F5, реализация OD11–OD15) ⛔ заблокированы до GATE**.
> `spec.md` согласован (v4). **0 кода.** **Итоги:** (OD11) исчерпывающий аудит —
> **9 активных P0-хардкодов / 4 уникальных значения** (Groq/OpenRouter base_url +
> STT-модели whisper-large-v3 / openrouter/free) в `services/status_service.py`,
> `SmartModule/transcriber/{groq,openrouter}_transcriber.py`, `services/video_cascade_client.py`;
> миграция **аддитивная** `hot.get(key, literal)` (дефолт = текущая константа ⇒ вывод
> идентичен, существующие значения не меняются); санкционированное исключение
> **param_catalog +2 PG-only записи STT → REGISTRY 385 / GROUPS 74 / Settings 359**
> (было 383/74/359), сид `code_source` + `ON CONFLICT DO NOTHING`; P1 — дефолт-фолбэки
> (не трогать), P2 — фикс-endpoint'ы, T — tooling. (OD12) история доступности ключей
> **персистится**: in-memory ring + **атомарный JSON-снимок `var/status_key_history.json`**
> (gitignored, 288 точек/провайдер, R17-safe) — **0 PG-DDL, SQLite остаётся v8** ⇒
> **исключение у владельца НЕ требуется**. (OD13) **deep-link OFF** — D9 CLOSED,
> `__TMA_DEEPLINK__=false`, задач реализации нет. (OD14) шрифт
> `MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2` **инспектирован T-1137**:
> валидный WOFF2, Material Symbols Rounded v2.967, 6607 глифов / 4277 лигатур,
> оси `FILL 0..1 / GRAD -50..200 / opsz 20..48 / wght 100..700`, **26/26 иконок**,
> Apache-2.0, но **5.36 МБ (5.11 МиБ) = не shippable** ⇒ обязателен субсет
> (`pyftsubset`): all-axes 36.3 КБ, **FILL-only 5.5 КБ**, **FILL+wght 13.2 КБ
> (рекомендован)**, static 3.7 КБ; **КРИТИЧНО:** `--unicodes-file` **теряет лигатуры**
> (`rlig/rclt→0`) ⇒ иконки рендерятся **PUA-кодпоинтом** (`&#xE850;`), а не текстом-именем;
> `--text` сохраняет лигатуры, но 4.03 МиБ (отвергнут); источник 5.11 МиБ **не
> коммитить** (`.gitignore`), коммитим субсет ~13.2 КБ + Apache-2.0 LICENSE; build-time
> зависимости `fonttools`+`brotli` (не рантайм). (OD15) **rename/delete ролей разрешены,
> КРОМЕ superuser** (жёсткая защита 403/409 + UI disabled; встроенные/занятые — нельзя).
> Открыты владельцу только **4 не-блокирующих выбора Q1–Q4** (base-url UI +2 записи
> → 387?; `fonttools`+`brotli` как build-dep?; 5.11 МиБ источник вне git?; файл
> `var/status_key_history.json`?). **GATE по-прежнему ЗАКРЫТ: 0 кода**, старт
> реализации (F/F4/F5/G) — только после общего GO владельца на v4. Граф обновлён:
> создана сущность **`tma-relume-redesign v4 design-project`** (+11 наблюдений) и
> **`OD11-OD15 owner decisions`** (+7); добавлены наблюдения в `tma-relume-redesign`
> (+2) и `tma-relume-redesign v3 design-project` (+1, SUPERSEDED); связи —
> `v4 SUPERSEDES v3`, `tma-relume-redesign HAS_DESIGN_PROJECT v4`,
> `v4 implements OD11-OD15`, `OD11-OD15 DECIDES tma-relume-redesign`.
> Дублей нет; Voxy-сущности не затронуты; удалений нет.
> **Синк STEP 3 (v5, секция E5 — OD16–OD19, T-1144) 10.09.2026 (@Memory):**
> главный deliverable раунда 10.5 ревизован **v4 → v5** — `design-project.md`
> **2119 → 2312 строк**, добавлена трассировка **§16.7 (E5)**; обновлены
> шапка/§0/§3/§9/§10/§11/§13/**AC-19/AC-20**/§14/§15.2/§15.3/§15.4/§16.1–§16.7.
> `tasks.md` секция **E5 (T-1144) ✅ ВЫПОЛНЕНО** (pre-gate, 0 кода, landing notes);
> **T-1145…T-1148 (F6, реализация OD16–OD19) ⛔ заблокированы до GATE**.
> `spec.md` согласован (v5). **Итоги:** **(OD16)** адреса провайдеров
> (`base_url` Groq/OpenRouter) **ОБЯЗАТЕЛЬНЫ в UI** — провайдер, модель и адрес
> редактируемы из мини-аппа, владелец **переключает провайдера И модель**; отменяет
> прежнее «base_url hot-only» (§15.2.2/§16.5 Q1); **+2 PG-only записи каталога**
> `models.groq_base_url` = `https://api.groq.com/openai/v1`,
> `models.openrouter_base_url` = `https://openrouter.ai/api/v1` ⟹ каталог-финал
> **REGISTRY 387 / GROUPS 74 / Settings 359** (383 → +2 STT OD11 → 385 → +2 адреса
> OD16 → **387**; миграция аддитивная, значения не меняются, `GET /api/status.llm[]`
> байт-идентичен, R17 — адрес НЕ секрет). **(OD17)** `fonttools`+`brotli` —
> **build-time only** (в runtime `requirements.txt` не входят). **(OD18)** тяжёлый
> источник шрифта **5.11 МиБ** → **`.gitignore`** (в git только субсет ~13.2 КБ +
> `LICENSE` Apache-2.0; на 10.09.2026 файл **untracked и ещё НЕ ignored** ⟹ T-1147
> добавит паттерн). **(OD19)** `var/status_key_history.json` **утверждён** с
> **обязательной leak-safety-верификацией**: allowlist-схема (module id, provider,
> model, key-configured bool, HTTP-код, timestamp, version, generated_at); запрет
> сырых ключей/токенов/`Authorization`/`Bearer`/`sk-`/`gsk_`/cookies/`initData`/
> credentials-in-`base_url`/тел LLM; права 0600 (каталог 0700); gitignored; **не
> отдаётся `GET /api/config`** и **не пишется в логи/`log_ring`/BetterStack**;
> атомарная запись (tmp + `os.replace`); corrupt/missing → пустая история + WARNING
> (fail-open). AC: grep-маркер (нет паттернов ключей) + unit-сериализатор +
> проверка прав + `git check-ignore` + выживание рестарта; **R17 доказан**.
> Scanner E5: `plans/reports/` — новых отчётов по 10.5 нет (последний — Round 10.4,
> 0 blocker/0 major); учтены MED-017/MED-021/LOW-012/R10.4-2/-4/-5, MED-003
> подтверждает OD16. **ВСЕ решения закрыты (D6–D12 = OD7–OD15; Q1–Q4 = OD16–OD19)** —
> открытых вопросов/выборов НЕ осталось. **GATE по-прежнему ЗАКРЫТ: 0 кода**;
> реализация (F/F5/F6/G, T-1098…T-1148) стартует только после **явного общего GO
> владельца на v5**. Граф обновлён: созданы сущности
> **`tma-relume-redesign v5 design-project`** (+10 наблюдений) и
> **`OD16-OD19 owner decisions`** (+6); добавлены наблюдения в `tma-relume-redesign`
> (+1) и `tma-relume-redesign v4 design-project` (+1, SUPERSEDED); связи —
> `v5 SUPERSEDES v4`, `tma-relume-redesign HAS_DESIGN_PROJECT v5`,
> `v5 implements OD16-OD19`, `OD16-OD19 DECIDES tma-relume-redesign`.
> Цепочка SUPERSEDES: **v5 → v4 → v3**. Дублей нет; Voxy-сущности не затронуты;
> удалений нет.
> **Синк STEP 10 (финал, post-commit+деплой) 10.09.2026: раунд 10.5 ПОЛНОСТЬЮ
> ЗАВЕРШЁН — HEAD == origin/master == `c01ed72`** (`918f675` — фича, 49 файлов;
> `c01ed72` — docs деплой-верификация; поверх `0bdf272`). Единственная фича
> `tma-relume-redesign` (T-1066…T-1148) реализована целиком (Builder Pass 1–6:
> токены/градиенты, hash-router + нативный BackButton, scope-switcher GLOBAL/ЧАТ/ЛС,
> hubs + 15 экранов, key-availability + persisted chart, матрица ролей + role CRUD
> кроме superuser, hardcode H1–H22 → безопасная аддитивная миграция, каталог
> 387/74/359, font-subset ~13.2 КБ + self-host DOMPurify 3.4.15 fail-closed).
> @Reviewer: REJECTED → fixes D1–D4 → APPROVED WITH MINOR → R1–R4 закрыты.
> @Scanner: **CLEAN — 0 blocker / 0 major**; R10.5-1/-2/-4 закрыты, R10.5-3/-5/-6/-7
> — техдолг (ARCH §25); отчёт `plans/reports/round10.5_scanner_audit.md`.
> @Architect: merge в `plans/ARCHITECTURE.md` (§9 обновлён, §25 «по состоянию на 10.5»
> + блок R10.5, новый **§26 «Раунд 10.5»** — последняя секция). **Тесты: 4962 passed /
> 0 failed** (baseline 10.4 = 4860, +102); `node --check web/app.js` clean;
> `git diff --check` чист. @PM: фича заархивирована — `plans/archive/tma-relume-redesign/`
> (**plans/archive/ — 27 папок**, plans/features/ — снова 6 активных F-1…F-6), backlog
> epic 10.5 закрыт. @DevOps: README обновлён (ироничный тон); push origin/master;
> **деплой 198.46.175.136:/var/www/admin_bot** — git pull fast-forward, `.env` без
> изменений, `systemctl restart admin_bot` → active (running), `/api/health` = 200,
> **0 startup-ошибок**. Граф обновлён: милстоун `round10.5-epic` → COMPLETED + DEPLOYED,
> фича → WAS_PART_OF + ARCHIVED_IN plans-structure + COMPLETED_IN/DEPLOYED_IN, создан
> `tech-debt-round10.5` (R10.5-3/5/6/7). **Осталось вручную:** live Telegram
> smoke-тест (T-1153), опциональный betterstack-401 fix, вердикт владельца.

## Активные фичи (plans/features/)

| Фича | Скоуп |
|---|---|
| `admin-debug-webview` (F-2) | `/debug_config` в HTML WebView поверх HTTPS |
| `scam-incident-security-followup` (F-3) | Секьюрити-фоллоу-ап после скам-инцидента 30.08 |
| `frontend-admin-bugfixes` (F-4) | Багфиксы админ-минги и `<Красивые ссылки>` |
| `config-read-path-audit` (F-5) | Аудит read-путей: settings.X vs hot.get |
| `user-aliases-admin` (F-6) | Алиасы юзеров в разделе «Лор чатов» (частично в master; SUPERSEDED_BY round10.4) |
| `post-deploy-admin-minors` (F-1) | Пост-деплойные миноры Epic 85 (T-648:T-655) |

> **Раунд 10.4 — 8 фич ЗАВЕРШЁН и ЗААРХИВИРОВАН (10.09.2026)** — см. раздел
> «Раунд 10.4 — финал» ниже; их спеки — в `plans/archive/`
> (frontend-advanced-collapse-default, frontend-memory-sleep-nostalgia,
> frontend-llm-providers-layout, frontend-reorg-modules-reactions,
> frontend-limits-temperature-budgets, frontend-relations-participants,
> backend-relations-nickname, backend-chat-1002661910336-scaling);
> конфликт-матрица backlog.md «Раунд 10.4»: F-1 PRECEDES B/G — учтён; F-3 T-663 +
> F-4 Баг-4 + F-5 — остаются ПОСЛЕ раунда (фичи активны); F-6 — SUPERSEDED_BY
> round10.4-epic (подтверждена; папка F-6 остаётся в plans/features/).

> **Раунд 10.5 — DESIGN-PROJECT v3 ГОТОВ, на GATE (10.09.2026, поздний вечер)** — активная
> фича `tma-relume-redesign` в `plans/features/`: решения владельца **OD1–OD6 LOCKED**
> (полный ребейлд по эталону / big-bang всё сразу / Vue3 global zero-build /
> анимированные градиенты + reduced-motion + WCAG AA / Material Symbols Rounded +
> emoji-fallback / структура эталона = эталон) + **OD7–OD10 LOCKED** (OD7 «Чат-Профиль» =
> глобальный scope-switcher GLOBAL/ЧАТ/ЛС, НЕ 7-й nav-пункт; OD8 B1 key-availability
> В СКОУПЕ (in-memory ring, без PG-DDL/SQLite v8); OD9 B2 custom-modules CRUD OUT;
> OD10 B3 role-matrix В СКОУПЕ и расширена). Главный deliverable —
> **`design-project.md` v3 (1817 строк, RU, §0–§15, статус 🟡 DESIGN/GATE)**; `spec.md`
> согласован (v3-указатель, v2 частично SUPERSEDED); `tasks.md` секция
> **E/E2/E3 (T-1090…T-1126) ✅ ВЫПОЛНЕНО**; **T-1127…T-1133 (F4) + F/G ⛔ заблокированы
> до явного апрува владельцем**. **§15 (E3):** 15.1 scope-switcher/OD7, 15.2
> key-availability/OD8, 15.3 role-matrix/OD10, 15.4 font-delivery/D11, 15.5 deep-link/D9,
> 15.6 **Q-NEW-1..5**, 15.7 трассировка. **Открыто владельцу:** Q-NEW-1 (+2 строки каталога
> 383→385?), Q-NEW-2 (key-history in-memory vs persisted), Q-NEW-3 (deep-link, реком. OFF),
> Q-NEW-4 (файл шрифта, emoji до поставки), Q-NEW-5 (delete/rename ролей?), **D9**
> (`__TMA_DEEPLINK__`=false), **D11** (шрифт поставляет владелец) + **GO на реализацию**.
> **RESOLVED:** D6/D7 → OD7–OD10; D8 — back через нативный `BackButton` (`__TMA_BACK__`=true).
> `.gitignore += relumesite_example/` (T-1066); `media/` НЕ тронут. **Коррекция:** 17 вкладок
> `TABS` (`web/app.js:18-145`), не 18. Конфликт-матрица: **F-4 frontend-admin-bugfixes
> (Баг-4) — ПОСЛЕ 10.5** (редизайн меняет карту вкладок); F-1/F-2/F-3/F-5
> независимы; F-6 SUPERSEDED_BY round10.4. Спека референса — `relumesite_example/`
> (gitignored). Детали — KG `tma-relume-redesign` + `tma-relume-redesign v3 design-project`.
> (Блок выше — исторический снимок v3; актуальный статус — ниже.)

> **Раунд 10.5 — DESIGN-PROJECT v4 ГОТОВ, на GATE (10.09.2026, E4/OD11–OD15)** — активная
> фича `tma-relume-redesign` в `plans/features/`: **OD1–OD10 LOCKED** (см. блок v3 выше)
> + **OD11–OD15 LOCKED** (ответы владельца на §15.6 Q-NEW-1..5): **OD11** — ноль
> захардкоженных моделей (аудит T-1136: 9 P0-хардкодов, аддитивная миграция без смены
> значений, `REGISTRY 385 / 74 / 359`); **OD12** — история ключей персистится
> (`var/status_key_history.json`, 0 PG-DDL, SQLite v8, исключение не нужно); **OD13** —
> deep-link **OFF** (`__TMA_DEEPLINK__=false`); **OD14** — шрифт инспектирован (валиден
> как источник; 5.11 МиБ не shippable → субсет ~13.2 КБ + рендер по PUA-коду); **OD15** —
> rename/delete ролей, **кроме superuser**. Главный deliverable —
> **`design-project.md` v4 (2119 строк, RU, §0–§16, статус 🟡 DESIGN/GATE)**; `spec.md`
> согласован (v4); `tasks.md` секции **E/E2/E3/E4 (T-1090…T-1138) ✅ ВЫПОЛНЕНО**;
> **T-1127+ и F/F4/F5/G (T-1098…T-1143) ⛔ заблокированы до явного GO владельца на v4**.
> **D6–D12 — все RESOLVED** (OD7–OD15). `.gitignore += relumesite_example/` (T-1066) +
> 5.11 МиБ источник шрифта (OD14); `media/` НЕ тронут. **Коррекция:** 17 вкладок `TABS`
> (`web/app.js:18-145`), не 18. Открыты только **4 не-блокирующих выбора Q1–Q4** (§16.5).
> Конфликт-матрица: **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ 10.5**; F-1/F-2/F-3/F-5
> независимы; F-6 SUPERSEDED_BY round10.4. Детали — KG `tma-relume-redesign` +
> `tma-relume-redesign v4 design-project` + `OD11-OD15 owner decisions`.
> (Блок выше — исторический снимок v4; актуальный статус — ниже.)

> **Раунд 10.5 — DESIGN-PROJECT v5 ГОТОВ, на GATE (10.09.2026, E5/OD16–OD19) — исторический снимок v5, см. финал ниже** —
> активная фича `tma-relume-redesign` в `plans/features/`: **OD1–OD15 LOCKED** (см. блоки v3/v4
> выше) + **OD16–OD19 LOCKED** (ответы владельца на §16.5 Q1–Q4): **OD16** — адреса
> провайдеров (`base_url`) **обязательны в UI**, провайдер/модель/адрес редактируемы из
> мини-аппа ⟹ каталог **REGISTRY 387 / GROUPS 74 / Settings 359** (383→385→387);
> **OD17** — `fonttools`+`brotli` **build-time only**; **OD18** — источник шрифта **5.11 МиБ**
> → **`.gitignore`** (в git субсет ~13.2 КБ + Apache-2.0 LICENSE); **OD19** —
> `var/status_key_history.json` утверждён при **обязательной leak-safety** (allowlist-схема,
> права 0600/0700, gitignored, не в `GET /api/config`/логах, атомарная запись, R17 доказан).
> Главный deliverable — **`design-project.md` v5 (2312 строк, RU, §0–§16.7, статус
> 🟡 DESIGN v5 / GATE)**; `spec.md` согласован (v5); `tasks.md` секции
> **E/E2/E3/E4/E5 (T-1090…T-1144) ✅ ВЫПОЛНЕНО**; **F/F4/F5/F6/G (T-1098…T-1148)
> ⛔ заблокированы до явного GO владельца на v5**. Новые **AC-19** (UI-редактируемость
> провайдера/модели/адреса) и **AC-20** (leak-safety файла истории). Коррекции: 17 вкладок
> `TABS` (`web/app.js:18-145`), не 18; `.gitignore += relumesite_example/` + источник шрифта;
> `media/` НЕ тронут. **ВСЕ решения закрыты (D6–D12 = OD7–OD15; Q1–Q4 = OD16–OD19)** — открытых
> вопросов нет. Конфликт-матрица: **F-4 frontend-admin-bugfixes (Баг-4) — ПОСЛЕ 10.5**;
> F-1/F-2/F-3/F-5 независимы; F-6 SUPERSEDED_BY round10.4. Детали — KG `tma-relume-redesign`
> + `tma-relume-redesign v5 design-project` + `OD16-OD19 owner decisions`.

> **Раунд 10.5 — ФИНАЛ: ЗАВЕРШЁН, ЗАКОММИЧЕН И ЗАДЕПЛОЕН (10.09.2026, HEAD
> `c01ed72`) — АКТУАЛЬНО** — милстоун **`round10.5-epic`** (COMPLETED + DEPLOYED).
> Коммиты `918f675` (фича, 49 файлов) + `c01ed72` (docs memory-sync), push
> origin/master. Тесты **4962 passed / 0 failed**; `node --check web/app.js` clean;
> @Reviewer APPROVED; @Scanner CLEAN (0 blocker/0 major; R10.5-3/-5/-6/-7 → техдолг
> ARCH §25); ARCHITECTURE.md §9/§25/§26. Деплой: 198.46.175.136:/var/www/admin_bot —
> git pull fast-forward, `.env` без изменений, restart active (running),
> `/api/health`=200, 0 ошибок. Фича заархивирована — `plans/archive/tma-relume-redesign/`
> (**plans/archive/ — 27 папок**; features/ — 6 активных F-1…F-6); README обновлён;
> backlog epic 10.5 закрыт. **Осталось вручную:** live Telegram smoke-тест (T-1153),
> опц. betterstack-401 fix, вердикт владельца. Детали — KG `round10.5-epic` +
> `tma-relume-redesign` + `tech-debt-round10.5`. (Снимки v3/v4/v5 выше — историчны.)

> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.6 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `4055434` (`6f91e8b` — фича, 37 файлов;
> `4055434` — docs деплой-верификация; поверх `be7b85b` = задеплоенный 10.5).
> Единственная фича **`tma-ia-modules-rework`** (T-1155…T-1223) реализована
> целиком: sidebar удалён (только top navbar 6 пунктов, иконка + подпись),
> «Модули» = 11 `mod_*` с реальными тумблерами + модалка параметров,
> «Настройки AI» = 7 подразделов (RAG → «Память»), PERMsoc очищен (10 параметров →
> модули 5/6/7), Леха/Костик раздельно, LLM Провайдеры — 9 блоков по модулям +
> `POST /api/llm/test`, proxy/cookies → M6, diagnostics → M9, emoji→Material,
> эксклюзивный аккордеон «Доступы и роли». 5 master-флагов default ON
> (FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP) с реальными гейтами OFF→UNHANDLED.
> **Каталог 392 / 91 / 364 / mapped 89 / TAB_RULES 19**; ноль PG-DDL, SQLite v8,
> `bot.py` и `media/` не тронуты. @Reviewer: REJECTED → fixes → APPROVED WITH MINOR
> → миноры закрыты. @Scanner: **CLEAN — 0 blocker / 0 major** (R10.6-1/-3 закрыты;
> R10.6-2/-4/-5/-6 — техдолг; отчёт `plans/reports/round10.6_scanner_audit.md`).
> @Architect: merge в `plans/ARCHITECTURE.md` (§27 + §25/§9/§6/§2). **Тесты:
> 5027 passed / 0 failed** (baseline 10.5 = 4962; +65); `node --check web/app.js`
> clean; `tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
> @PM: фича заархивирована — `plans/archive/tma-ia-modules-rework/`
> (**plans/archive/ — 28 папок**; plans/features/ — 6 активных F-1…F-6). @DevOps:
> README обновлён (ироничный тон); push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward до `4055434`, `.env`
> без изменений, restart → `is-active=running`, `/api/health`=200, **0 tracebacks**.
> Граф обновлён: милстоун `round10.6-epic` → COMPLETED + DEPLOYED, фича →
> WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.6` (R10.6-2/-4/-5/-6). **Осталось вручную:** live Telegram
> smoke-тест (desktop/Android WebView), опциональный betterstack-401 fix.
> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.7 ПОЛНОСТЬЮ
> ЗАВЕРШЁН** — HEAD == origin/master == `bb59476` (`7f3b790` — fix, 19 файлов;
> `bb59476` — docs деплой-верификация; поверх `2ccf558` — docs 10.6; прод до
> деплоя `4055434`).
> Единственная фича **`admin-ui-bugfixes-round107`** (spec @Architect T-1224)
> реализована целиком: 1a `scope*` → computed (фикс `function () { [native code] }`),
> 1b header safe-area padding, 1c компактный user block, 1d nav labels меньше/без
> per-letter wrap, 2a ellipsis таблицы ключей, 2b uptime gap-fill (непрерывная
> 5-мин сетка, `down` для пустых слотов, `last_heartbeat` = last up else None),
> 3a clipboard-ghost focusable (без visibility:hidden) + удалён, 3b фикс. ширины
> лог-колонок + flex последней, 3c copy-on-row-click с feedback, R106-5 dead ICONS
> удалены (26→20). @Reviewer: REJECTED (visibility:hidden сломал execCommand-фолбэк)
> → fix → APPROVED WITH MINOR ISSUES → doc nit закрыт. @Scanner: **CLEAN — 0 blocker /
> 0 major** (R10.7-1 (minor) + R10.7-2..5 (info/nit) — техдолг; R10.6-5 ЗАКРЫТ; отчёт
> `plans/reports/round10.7_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§28 «Раунд 10.7»** (+§9/§25). **Тесты: 5042 passed /
> 0 failed** (baseline 10.6 = 5027; +15); каталог 392/91/364. @PM: фича
> заархивирована — `plans/archive/admin-ui-bugfixes-round107/`
> (**plans/archive/ — 29 папок**; plans/features/ — 6 активных F-1…F-6). @DevOps:
> README обновлён (ироничный тон); push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward до `7f3b790`, `.env`
> без изменений, restart → active, `/api/health` = 200, **0 errors**. Граф обновлён:
> милстоун `round10.7-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.7` (R10.7-1…R10.7-5). **Осталось вручную:** live Telegram
> smoke-тест исправленного UI, опциональный betterstack-401 fix.
> **Синк STEP 10 (финал, post-commit+деплой) 11.09.2026: раунд 10.8 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `976e335`** (`31d2ce7` — фича,
> 30 файлов, тесты 5076; `976e335` — docs деплой-верификация; поверх `636a75d` —
> docs-финал 10.7; прод до деплоя `7f3b790` = задеплоенный 10.7).
> Единственная фича **`admin-ui-round108`** (spec @Architect + tasks @PM; T-1243…)
> реализована целиком: (1) переименование разделов — «Доступы»/«PERMsoc»/«ИИ»/
> «Справка»/«Сводка» (route-ключи `#/how|ai|permsoc|access|oversight` не менялись);
> (2) emoji→Material-иконки, субсет шрифта **20→37** (13 428→**18 388 B**),
> идемпотентность build-script по `sha256(source_sha+ICON_NAMES)`,
> `build/icon_codepoints.json`, R10.7-4 cmap-тест; (3) фикс логов на Android —
> Material-шеврон только при `exc_text` (без невидимого глифа), дата
> **DD.MM HH:MM:SS**, блочная раскладка (без `<pre><span>`, без жёстких ширин),
> `.log-msg` full-width, R10.7-3 closed; (4) «Доступы» — подразделы отдельными
> **route-driven модалками** (`#/access/roles|local|admins`), «Администраторы»→
> «Роли», аккордеон удалён, «Мой доступ»/«Telegram ID админа» вне окон,
> BackButton/deep-link/Esc; (5) удалён внешний GLOBAL-бейдж; README переструктурирован
> (users-first, гайд «Управление и деплой», changelog под `<details>`), счётчик 5076;
> `APP_VERSION` 2.51.0→**2.52.0**, шрифт cache-busted `?v=__APP_VERSION__`.
> @Reviewer: APPROVED WITH MINOR ISSUES (doc-nit исправлен). @Scanner: **0 blocker /
> 0 major** (R10.8-1 Esc и R10.8-5 APP_VERSION/кэш субсета закрыты follow-up;
> R10.8-2/-3/-4 — info/техдолг; **R10.7-3 и R10.7-4 ЗАКРЫТЫ**; отчёт
> `plans/reports/round10.8_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§29 «Раунд 10.8»** (+§1/§9/§25). @PM: фича заархивирована —
> `plans/archive/admin-ui-round108/` (spec.md, tasks.md, **ADR-001-access-windows-modal**,
> **ADR-002-icon-subset-parity**); **plans/archive/ — 30 папок**; plans/features/ —
> 6 активных F-1…F-6. @DevOps: README счётчик 5073→5076; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `7f3b790..31d2ce7`,
> `.env` без изменений, restart active, `/api/health`=200, шрифт `?v=2.52.0` → 200
> (wOF2, 18 388 B), 0 ошибок. Граф обновлён: милстоун `round10.8-epic` → COMPLETED +
> DEPLOYED, фича → WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure,
> создан `tech-debt-round10.8` (R10.8-2/-3/-4 + закрытые R10.8-1/-5). **Осталось
> вручную:** live Android smoke **T-1254** (логи) и **T-1258** (окна «Доступов»);
> опциональный betterstack-401 fix.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.9 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `f928225`** (`d2d1215` — фича,
> 34 файла, тесты 5105; `f928225` — docs деплой-верификация; поверх `51f308b` —
> docs-финал 10.8; прод до деплоя `31d2ce7` = задеплоенный 10.8).
> Единственная фича **`admin-ui-round109`** (spec @Architect + tasks @PM + ADR-109;
> T-1270…T-1314) реализована целиком: (1) PERMsoc — 4 сворачиваемых owner-блока
> (Славик/Оля/Мимикрия/Общее), в каждом ровно один рабочий тумблер; новый
> `flags.slavik_enabled` (default True), `reactions_persons` удалена,
> `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`;
> (3) `_preserveScroll` для `document.scrollingElement` И `.scroll-area` —
> сохранение не прыгает вверх, вкл. fullscreen; (4) все описания и титулы
> параметров/групп переписаны (plain ironic language, без жаргона/AI-паттернов);
> (5) карточка «Тяжёлые фичи» удалена; (6) «Бюджет фона» перенесён в «Сводку»
> (backend/endpoint не тронуты); (7.1) dashboard «Доступность ключей» из 4
> функциональных групп + реальный health `probe_openai` (ok/error/timeout/
> unreachable/not_configured; STT groq POST `/audio/transcriptions` multipart WAV;
> кэш per `module_id`: 2xx 60с, ошибки 10с; stale-200 не отдаётся); (7.2) 7
> `models.*_display_name` первым полем каждого провайдер-блока, форма `max-w-3xl`;
> (8) градиент быстрее (`--grad-speed:14s`, `grad-drift 18s`). **Каталог 400 / 90 /
> 372 / mapped 88 / TAB_RULES 19**; ноль PG-DDL, SQLite v8, `bot.py`/`media/` не
> тронуты. @Reviewer: REJECTED → фиксы → APPROVED WITH MINOR ISSUES → follow-ups
> закрыты. @Scanner: **0 blocker / 0 major / 0 medium** (3 low R10.9-1/-2/-3 +
> 3 info R10.9-4/-5/-6; R10.9-6 закрыт архивацией; отчёт
> `plans/reports/round10.9_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` §30 (+§1/§9/§25). **Тесты: 5105 passed / 0 failed**
> (baseline 10.8 = 5076; +29); `node --check web/app.js` clean; `tests/js/routing_test.js`
> → `JS-UNIT-OK`; `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/admin-ui-round109/` (spec.md + tasks.md + ADR-109.md);
> **plans/archive/ — 31 папка**; plans/features/ — 6 активных F-1…F-6. @DevOps:
> README 5105 + APP_VERSION **2.53.0**; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward `31d2ce7..d2d1215`,
> `.env` без изменений, restart active, `/api/health` 200, 0 ошибок. Граф обновлён:
> милстоун `round10.9-epic` → COMPLETED + DEPLOYED, фича → WAS_PART_OF +
> COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN plans-structure, создан
> `tech-debt-round10.9` (R10.9-1/-2/-3 low + R10.9-4/-5 info; R10.9-6 закрыт).
> **Осталось вручную:** live Android smoke — T-1277/1290/1292/1294/1302/1305;
> опциональный betterstack-401 fix. ⚠️ Пункт 2 исходного ТЗ (инфраструктура
> локального IDE владельца) — **вне скоупа проекта**, в репозитории/графе
> не фиксируется.

> **Синк STEP 10 (финал, post-commit+деплой) 12.09.2026: раунд 10.10 ПОЛНОСТЬЮ
> ЗАВЕРШЁН и ЗАДЕПЛОЕН — HEAD == origin/master == `772db08`** (`d082800` — фича,
> тесты 5144; `a477747` — fix scripts standalone sys.path bootstrap + CLI-тест,
> тесты 5145; `772db08` — docs деплой-верификация; поверх `da85b60` — docs
> memory-sync 10.9; прод до деплоя — `d2d1215` = задеплоенный 10.9).
> Единственная фича **`admin-ui-round1010`** (spec @Architect + tasks @PM +
> ADR-1010-1/2/3; T-1315…T-1328) реализована целиком: (1) header fullscreen
> padding — `max(env(safe-area-inset-*), --tg-content-safe-area-inset-*,
> --tg-safe-area-inset-*)`, профиль-блок не перекрывается нативными кнопками;
> (2) мобильный график доступности ключей — окно строится ОТ КОНЦА, новейшие
> сэмплы не отбрасываются, дорожки на провайдера + временная сетка 300с (min 12
> бакетов), адаптивная высота, `api_payload` не изменён; (3) «Провайдеры» —
> реальные значения полей через `blockFieldValue` (`:value`+`@input`), секреты
> замаскированы; (4) ЛС heavy-modules OFF — `scripts/disable_dm_heavy_modules.py`
> (идемпотентный; dry-run/`--apply`/`--restore`/`--chat-id`/snapshot) + new-DM
> defaults OFF (сон/ностальгия/саммаризация; F-14 gate не тронут); (5) «Роли» —
> аватар+ник+мелкий серый ID, backend `global_user_display_info` (RAM-TTL 1ч,
> fail-open, транзиентные ошибки не кэшируются), ширины w-24/flex-1 min-w-0/
> shrink-0. **Каталог 400 / 90 / 372 / mapped 88 / TAB_RULES 19**; ноль PG-DDL,
> SQLite v8, `bot.py`/`media/`/`.env` не тронуты. @Reviewer: REJECTED (график
> отбрасывал новейшие данные) → fix → APPROVED WITH MINOR ISSUES → restore
> exit-code Low закрыт. @Scanner: **0 blocker / 0 major / 0 medium** (low
> R10.10-1/-2/-3 + info R10.10-4/-5; большинство закрыто;
> `plans/reports/round10.10_scanner_audit.md`). @Architect: merge в
> `plans/ARCHITECTURE.md` **§31** (+§3/§9/§25). **Тесты: 5145 passed / 1 skipped /
> 0 failed** (baseline 10.9 = 5105; Scanner 5140 + 1 skipped на момент аудита);
> `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
> `git diff --check` чист. @PM: фича заархивирована —
> `plans/archive/admin-ui-round1010/` (spec.md + tasks.md + ADR-1010-1/2/3.md);
> **plans/archive/ — 32 папки**; plans/features/ — 6 активных F-1…F-6.
> @DevOps: README 5145 + `APP_VERSION` **2.54.0**; push origin/master; **деплой
> 198.46.175.136:/var/www/admin_bot** — git pull fast-forward, `.env` без
> изменений, restart active, `/api/health` 200, 0 ошибок; **DM data-run применён**
> (1 активный ЛС; snapshot `var/dm_modules_off_snapshot_20260911T201219Z.json`;
> повторный dry-run 0). Граф обновлён: милстоун `round10.10-epic` → COMPLETED +
> DEPLOYED, фича → WAS_PART_OF + COMPLETED_IN/DEPLOYED_IN + ARCHIVED_IN
> plans-structure, создан `tech-debt-round10.10` (R10.10-1..-5). **Осталось
> вручную:** live Android QA — T-1317/1320/1323/1332; UI spot-check DM-тумблеров
> OFF (T-1328). ⚠️ П.6 Headroom (saved-tokens stats, внешняя IDE-инфраструктура) —
> **вне скоупа проекта**, в репозитории/графе не фиксируется.

> **Раунд 10.3 (F-13/F-14/F-15) завершён и заархивирован** — см. раздел
> «Раунд 10.3 — финал (09–10.09.2026)» ниже; их спеки — в `plans/archive/`
> (`tma-chat-selector-fixes`, `dm-user-settings`, `direct-sandbox-budget-investigation`).

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

### Раунд 10.3 — финал (09–10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (1410a68)

По ультиматуму юзера (7 пунктов ТЗ; задачи 1–4, 6 → F-13/F-14, задачи 5 и 7 →
F-15). HEAD == origin/master == `1410a68` (был d30b203). **Статус: COMPLETED +
DEPLOYED.** Все 3 фичи заархивированы, цикл раунда полностью закрыт (Step 10).

- **Коммит (master):** `1410a68` feat(admin,web,chat,api): раунд 10.3 — единый
  селектор чата в TMA, отдельные настройки ЛС (саммари default-off), диагностика
  sandbox budget и graphrag memorize (тесты 4831) — автор Henry, 09.09.2026
  12:33 UTC; push origin/master; `git diff --check` чист. **plans/MEMORY.md ВПЕРВЫЕ
  вошёл в коммит** (в раундах 10–10.2 был untracked намеренно).
- **Тесты:** 4831 passed / 0 failed (4760 baseline + ~71 новых). @Reviewer
  APPROVED; Scanner 0 blocker/major (миноры R10.3-1…R10.3-6 → ARCHITECTURE.md §24);
  `node --check web/app.js` clean.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 1410a68; рестарт
  09.09.2026 12:37 UTC; `systemctl status admin_bot` → active (running); .env без
  изменений. Прод-диагностика задачи 5 проведена (см. ниже).
- **Фичи (все ARCHIVED, plans/archive/ — 18 папок):**
  - `tma-chat-selector-fixes` (F-13, T-925…T-944): единый нативный <select> +
    бейдж #id/«ЛС #id», удалены openChatPicker/✕ closeApp, фикс v-if/v-for
    precedence (<template v-for> + v-if на дочернем div; configError-баннер),
    .sidebar z-index:45 + safe-area. ARCH §23.
  - `dm-user-settings` (F-14, T-945…T-964): DM-скоуп is_dm_scope=chat_id>0 на
    chat_profiles/chat_params (ноль DDL), is_dm_owner (rank=local_admin,
    DM_OWNER_PRESET без chat_lore), ensure_scope_profile, саммари в ЛС default-off
    (S1–S5), изоляция WHERE chat_id<0 (6 точек), синтез DM-строки в
    /api/access/chats|me, TMA «Личные сообщения» в селекторе. ARCH §23.
  - `direct-sandbox-budget-investigation` (F-15, T-965…T-973): прод-диагностика
    T-965/T-966 ДО фикса; NoApiKeyForChat.details (снапшот resolve_path/day/
    used|limit calls|tokens/allow_global) + WARNING с details; BYOK-фоллбэк
    свой→глобал-бюджет→свой-фоллбэк→sandbox; parse_fact_list: _mask_llm_raw +
    _fallback_parse_facts + 1 ретрай (только fire-and-forget memorize, крон без
    ретрая). ARCH §23/§24.
- **Прод-диагностика задачи 5 (ВЫВОД):** у чата -1002661910336 НЕТ собственного
  ключа (chat_keys пуст) → работает глобальный ключ с суточным лимитом 25
  запросов; 09.09.2026 счётчик дошёл 25/25 в 09:55 UTC, WARNING reason=budget в
  09:57 — исчерпание суточного лимита; sandbox-фраза = штатный дизайн R16 (не
  баг); восстановление автоматическое после сброса бакета chat_usage в 00:00
  Екб. Рекомендации: BYOK-ключ для чата (chat_keys /api/config/keys/own) ИЛИ
  поднять limits.chat_global_key_budget_requests (25 → 50/100) через hot config.
  Детали — KG `recon: direct-chat-sandbox-budget` (+ фикс-слой F-15 уже в проде).
- **README.md:** тесты 4831, раздел раунда 10.3 (ироничный тон сохранён).

### Раунд 10.4 — финал (10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (0bdf272)

По 9 пунктам ТЗ реструктуризации TMA. HEAD == origin/master == `0bdf272`
(был 1410a68). **Статус: COMPLETED + DEPLOYED.** Все 8 фич заархивированы,
цикл раунда полностью закрыт (Step 10).

- **Коммит (master):** `0bdf272` feat(admin,web,chat,api): раунд 10.4 —
  реструктуризация админки (Модули/PERMsoc/Память/Сон/Ностальгия/Провайдеры/
  Отношения), бюджеты per-чат и температура-select, имена людей per-чат/ЛС,
  каскад имён, лимиты ×1.5-×2 для -1002661910336 (тесты 4860); push origin/master;
  `git diff --check` чист.
- **Тесты:** 4860 passed / 0 failed (4831 baseline + 29: test_104_backend_additions 11,
  test_progressive_tab_basic_coverage 3, маркеры webapp_*/frontend_tab_mapping).
  @Reviewer APPROVED; Scanner 10.4 — 0 blocker/major (minor R10.4-1…R10.4-4,
  info R10.4-5…R10.4-7 → ARCH §25; R10.4-1/-2/-3 закрыты follow-up @Builder и сверены);
  `node --check web/app.js` clean.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull до 0bdf272; **.env —
  добавлена `CHAT_THREAD_MAX_CHARS=2000`**; **бэкфилы применены:**
  `scripts/backfill_104_chat_flags.py` (flags.chat_context_budgets_enabled=false
  для -1002661910336) + `scripts/backfill_104_overrides.py` (15 ключей ×1.5–×2:
  thread_max_chars ×2, global_context_max_chars/limit ×1.5, level2 ×2,
  map_participants_cap ×2, summary_*/ретенция/graph_rag_* ×2;
  graph_edge_weight_increment НЕ менялся); рестарт — `systemctl status admin_bot`
  → active (running).
- **Фичи (все ARCHIVED, plans/archive/ — 26 папок):**
  - `frontend-advanced-collapse-default` (D, T-1018…T-1023): «Расширенные» свёрнуты
    по умолчанию (:open="expandOpen(activeTab)"); 0-basic группы — свёрнуты с видимым
    summary; BUG-5-семантика сохранена; новый тест test_progressive_tab_basic_coverage. §24.
  - `frontend-memory-sleep-nostalgia` (C, T-1006…T-1017): «Память» (memory_rag) +
    отдельные «Сон»/«Ностальгия»; _ADVANCED_GROUPS минус dream/nostalgia; явная
    progressive-разметка; мини-блоки перенесены. §24.
  - `frontend-llm-providers-layout` (E, T-1024…T-1032): 4 секции
    (модели→ключи→фолбэк→расширенные), sections-зеркало TABS; маскировка/BYOK
    без изменений. §24.
  - `frontend-reorg-modules-reactions` (A, T-974…T-989): девиансия D-A1 —
    «Функции PERMsoc» 17 групп (+war/common/goodmorning/word_reactions);
    «Реакции и Триггеры» 4 группы; «Модули» (modules_switches); лор-настройки
    в «Лор чатов». §24.
  - `frontend-limits-temperature-budgets` (B, T-990…T-1005): бюджет-гейт per-chat
    (limits_chat_budgets, override false для -1002661910336); select-температура
    (widget='select' + select_options/select_labels, 422); «Имена людей» (people_names)
    + build_alias_resolver(chat_id); реестр read-путей T-993 для F-5. §24.
  - `frontend-relations-participants` (F, T-1033…T-1044): вкладка «Участники и
    отношения» (type 'relations'); перенос блока участников + «Настройки отношений»;
    DM-заглушка; серверные API без изменений. §24.
  - `backend-relations-nickname` (H, T-1057…T-1065): username для ВСЕХ строк
    (Semaphore(5), кэш 1ч; фото топ-50); каскад alias→nickname→username→''; R16. §24.
  - `backend-chat-1002661910336-scaling` (G, T-1045…T-1056): per-chat лимиты ×1.5–×2
    (12 точек чтения → get_chat_param; ревью-фикс №5: _thread_limit/_cp_g/budget_tokens),
    _resolve_from_root +_cast_type_ok+isfinite; граница G-4 задокументирована. §24/§25.
- **Диагнозы раунда:** per-chat бюджеты — флаг переведён в limits_chat_budgets,
  для -1002661910336 OFF (KPI-риск F-15: глобальный ключ 25 req/сутки; восстановление —
  1 клик); лимиты ×1.5–×2 — thread ×2 через chat_thread_max_chars (R10.4-3-фикс),
  global ×1.5 через max_chars; каскад имён — username всем строкам, R16 сохранён,
  per-chat алиасы (точка 1) через build_alias_resolver.
- **Техдолг (кандидаты следующего раунда, KG `tech-debt-round10.4`):** R10.4-4
  (фото-обогащение всех 100 строк), R10.4-5 (409-модалка relations «Перезагрузить»),
  R10.4-6 (бэкфилы без optimistic-метки), R10.4-7 (граница G-4: direct RAG-cap/
  get_rag_facts глобальные — кандидат F-5), B-13 points 2-4 (per-chat алиасы не
  доходят до инжекта <user_relations>), HIGH-004 (полный LLM request/response-лог).
- **README.md:** тесты 4860, раздел раунда 10.4.

### Раунд 10.5 — финал (10.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (918f675)

«Редизайн TMA по референсу Relume + гигиена репозитория». Единственная фича —
`tma-relume-redesign` (T-1066…T-1148, продолжает T-1065). HEAD == origin/master
== `c01ed72` (`918f675` + `c01ed72`, поверх `0bdf272`). **Статус: COMPLETED +
DEPLOYED.** Цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `918f675` feat(admin,web,chat,api): раунд 10.5 — редизайн
  TMA по референсу Relume: navbar, hubs, hash-роутинг, scope-switcher, key-history,
  матрица ролей, градиенты, Material Symbols (тесты 4962) — 49 файлов; `c01ed72`
  docs(plans): деплой-верификация раунда 10.5; push origin/master.
- **Тесты:** 4962 passed / 0 failed (baseline 10.4 = 4860, +102); `node --check
  web/app.js` clean; `git diff --check` чист; HTML tag-balance 0.
- **Реализация (Builder Pass 1–6):** токены/анимированные градиенты (T-1098);
  hash-router + нативный `Telegram.WebApp.BackButton` (Bot API 6.1+, single
  onClick, `goBack`=routeParent, deep-link OFF) (T-1099); scope-switcher
  GLOBAL/ЧАТ/ЛС + scopeEpoch (T-1127); 6-item navbar + 3 hubs + 15 экранов
  (T-1100…T-1112); key-availability + chart + `services/key_history.py` (ring 288
  + атомарный `var/status_key_history.json`, allowlist, 0 DDL, SQLite v8)
  (T-1128/1129/1132/1139/1140/1145/1148); матрица ролей + создание/rename/delete
  кроме superuser (T-1130/1131/1133/1141/1142); hardcode H1–H22 → безопасная
  аддитивная миграция `hot.get(key, literal)`; каталог **387/74/359**; font-subset
  ~13.2 КБ + self-host DOMPurify 3.4.15 fail-closed (T-1146/1147).
- **Ревью/Scanner:** @Reviewer REJECTED → fixes D1–D4 → APPROVED WITH MINOR →
  R1–R4 закрыты. @Scanner **CLEAN — 0 blocker / 0 major**; R10.5-1/-2/-4 закрыты;
  R10.5-3/-5/-6/-7 — техдолг (ARCH §25). Отчёт
  `plans/reports/round10.5_scanner_audit.md`.
- **Архитектура:** @Architect — §9 обновлён, §25 «по состоянию на раунд 10.5» +
  блок R10.5, новый §26 «Раунд 10.5» (последняя секция, ARCHITECTURE.md 320 строк).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward; `.env`
  без изменений; `systemctl restart admin_bot` → active (running);
  `/api/health` = 200; 0 startup-ошибок.
- **Архивация:** `tma-relume-redesign` → `plans/archive/tma-relume-redesign/`
  (**plans/archive/ — 27 папок**; plans/features/ — 6 активных F-1…F-6); backlog
  epic 10.5 закрыт. README обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест (T-1153), опциональный
  betterstack-401 fix, вердикт владельца.
- **Техдолг раунда (KG `tech-debt-round10.5`):** R10.5-3 (GET
  /api/status/key-history открыт любому авторизованному TMA-юзеру),
  R10.5-5 (rename_role race → 500 вместо 409), R10.5-6 (мёртвый setMenu,
  пре-существующий), R10.5-7 (sync `key_history.maybe_save()` I/O в async path).

### Раунд 10.6 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (6f91e8b + 4055434)

«Переработка IA TMA — единый navbar, 11 Модулей с реальными тумблерами, Настройки AI
из 7 подразделов, чистка PERMsoc». Единственная фича — `tma-ia-modules-rework`
(T-1155…T-1223; follow-up после round10.5-epic). HEAD == origin/master == `4055434`
(`6f91e8b` + `4055434`, поверх `be7b85b`). **Статус: COMPLETED + DEPLOYED.** HARD GATE
T-1156 пройден владельцем 11.09.2026 (GO на IA). Цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `6f91e8b` feat(admin,web,api,plans): раунд 10.6 — редизайн IA
  TMA: одна навигация, 11 модулей-тумблеров, RAG в память, тест провайдеров, чистка
  PERMsoc (тесты 5027) — **37 файлов**; `4055434` docs(plans): раунд 10.6 — деплой-
  верификация; push origin/master.
- **Тесты:** 5027 passed / 0 failed (baseline 10.5 = 4962; +65; Scanner зафиксировал
  5023 на момент аудита — до follow-up R10.6-1/-3). `node --check web/app.js` clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- **Реализация (@Builder, T-1157…T-1223):** sidebar/`MENU_ORDER`/`sidebarOpen`/
  `setMenu` удалены — только top navbar (6 пунктов: Статус/Как это работает/Модули/
  Настройки AI/Функции PERMsoc/Доступы и Роли), иконка + подпись под ней; модель
  скролла `.app-shell` flex-col + `.scroll-area` (desktop fullscreen ⛶ скроллится);
  «Модули» = 11 `mod_*` (Саммаризация, Прямые ответы, Фактчек, Поиск, Транскрипт
  голосовых и видео, Выжимка видео, Скачивание медиа, Веб-страницы, Диагностика, Сон,
  Ностальгия) с реальными toggle + модалка параметров; «Настройки AI» = 7 подразделов
  (LLM Провайдеры, Промпты, Память+RAG, Умный кэш, Имена, Отношения, Лор чата;
  «Лимиты» растворены); 5 master-флагов default ON
  (FACTCHECK/SEARCH/VIDEO_SUMMARY/WEBPAGE/CHECKUP) с реальными гейтами OFF→UNHANDLED
  (youtube — только summary-ветка); PERMsoc очищен — 10 миселённых параметров
  разнесены по модулям 5/6/7; Леха/Костик раздельно (`limits_alan`/`limits_kostik`,
  `reactions_kostik`); LLM Провайдеры — 9 блоков по модулям + `POST /api/llm/test`
  (global admin, rate-limit 5с, R17); `keys_youtube` → M6, `models_checkup`/
  `keys_betterstack` → M9; emoji→Material icons; эксклюзивный аккордеон «Доступы и роли».
- **Каталог (locked):** REGISTRY **392** / GROUPS **91** / Settings **364** /
  mapped **89** / `TAB_RULES` **19**. Расщепления: `limits_media`→4, `limits_persons`→2,
  `limits_youtube_web`→2, `limits_cooldowns`→растворена, `flags_modules`→7, `flags_chat_behavior`→3,
  `reactions_persons`→+`reactions_kostik`, `limits_chat_budgets`→+`limits_rag` (RAG→«Память»).
  **Ноль новых PG-DDL**; SQLite **v8**; порядок роутеров `bot.py` и `media/` не тронуты.
- **Ревью/Scanner:** @Reviewer REJECTED → fixes (BLOCKER nav-gating модулей, test-buttons,
  Sleep/Nostalgia-панели в модалке) → APPROVED WITH MINOR ISSUES → миноры закрыты
  (SSRF-префикс, search per-key, clear field). @Scanner **CLEAN — 0 blocker / 0 major**;
  R10.6-1 (дубль LLM-редакторов) и R10.6-3 (422-эхо `api_key`) закрыты; R10.6-2/-4/-5/-6 —
  техдолг (ARCH §25/§27). Отчёт `plans/reports/round10.6_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§27 «Раунд 10.6»** + обновлены
  §25 (техдолг R10.6-*), §9 (фронт/каталог/provider-блоки), §6 (таблица master-гейтов),
  §2 (гейты внутри существующих роутеров).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward до `4055434`;
  `.env` без изменений; `systemctl restart admin_bot` → `is-active=running`;
  `/api/health` = 200; 0 tracebacks.
- **Архивация:** `tma-ia-modules-rework` → `plans/archive/tma-ia-modules-rework/`
  (**plans/archive/ — 28 папок**; plans/features/ — 6 активных F-1…F-6). README
  обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест (desktop/Android WebView),
  опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.6`):** R10.6-2 (SSRF-периметр
  `POST /api/llm/test`: https для любого хоста без private-range-проверки),
  R10.6-4 (info — `media_share` вне списка блоков спеки), R10.6-5 (info — мёртвые
  записи `ICONS` после удаления вкладок), R10.6-6 (info — rate-limit расходуется
  до валидации блока).

### Раунд 10.7 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (7f3b790 + bb59476)

«UI/UX-багфиксы админ-минги». Единственная фича — `admin-ui-bugfixes-round107`
(spec @Architect T-1224). HEAD == origin/master == `bb59476` (`7f3b790` + `bb59476`,
поверх `2ccf558` — docs 10.6; прод до деплоя — `4055434`).
**Статус: COMPLETED + DEPLOYED.** FOLLOWS
round10.6-epic; цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `7f3b790` fix(admin,web): раунд 10.7 — UI/UX-багфиксы
  (scope*-computed, safe-area шапки, компактный юзер-блок, ellipsis ключей,
  gap-fill uptime, clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20)
  — **19 файлов**; `bb59476` docs(plans): деплой-верификация раунда 10.7;
  push origin/master.
- **Тесты:** 5042 passed / 0 failed (baseline 10.6 = 5027; +15). Каталог
  **392 / 91 / 364** (без изменений).
- **Реализация:** 1a `scope*` → computed (фикс `function () { [native code] }`);
  1b header safe-area padding; 1c компактный user block; 1d nav labels меньше/без
  per-letter wrap; 2a ellipsis таблицы ключей; 2b uptime gap-fill (непрерывная
  5-мин сетка, `down` для пустых слотов, `last_heartbeat` = last up else None);
  3a clipboard-ghost focusable (без `visibility:hidden`) + удалён; 3b фиксированные
  ширины лог-колонок + flex последней; 3c copy-on-row-click с feedback; R106-5
  dead ICONS удалены (26→20).
- **Ревью/Scanner:** @Reviewer REJECTED (`visibility:hidden` сломал
  `execCommand`-фолбэк) → fix → APPROVED WITH MINOR ISSUES → doc nit закрыт.
  @Scanner **CLEAN — 0 blocker / 0 major**; R10.7-1 (minor) + R10.7-2..5
  (info/nit) — техдолг; R10.6-5 ЗАКРЫТ. Отчёт
  `plans/reports/round10.7_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§28 «Раунд 10.7»** + обновлены
  §9/§25.
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward до
  `7f3b790`; `.env` без изменений; `systemctl restart` → active; `/api/health` =
  200; 0 errors.
- **Архивация:** `admin-ui-bugfixes-round107` →
  `plans/archive/admin-ui-bugfixes-round107/` (**plans/archive/ — 29 папок**;
  plans/features/ — 6 активных F-1…F-6). README обновлён (ироничный тон).
- **Осталось вручную:** live Telegram smoke-тест исправленного UI, опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.7`):** R10.7-1 (minor — gap-fill
  помечает текущий незавершённый 5-мин слот `down` до ~60 с; §2b trade-off),
  R10.7-2 (info — `[-288:]` может отсечь единственный ранний `up`-бакет),
  R10.7-3 (info — `copiedTimer` не чистится при смене вкладки),
  R10.7-4 (info — `test_font_subset` проверяет JS, не cmap WOFF2),
  R10.7-5 (info/nit — неточная формулировка «context-loss» в `copyAllLogs`).

### Раунд 10.8 — финал (11.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (31d2ce7 + 976e335)

«Точечные UI-правки админ-минги». Единственная фича — `admin-ui-round108`
(spec @Architect + tasks @PM, T-1243…; продолжает 10.7). HEAD == origin/master ==
`976e335` (`31d2ce7` + `976e335`, поверх `636a75d` — docs-финал 10.7; прод до
деплоя — `7f3b790`). **Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.7-epic;
цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `31d2ce7` feat(admin,web,plans): раунд 10.8 — переименование
  разделов, emoji→иконки, фикс логов на Android, окна «Доступов» (тесты 5076) —
  **30 файлов**; `976e335` docs(plans): раунд 10.8 — деплой-верификация; push origin/master.
- **Тесты:** 5076 passed / 0 failed (baseline 10.7 = 5042; +34; Scanner зафиксировал
  5073 на момент аудита — до follow-up R10.8-1/-5). Каталог **392 / 91 / 364**
  (mapped 89, `TAB_RULES` 19); `node --check web/app.js` clean;
  `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` чист.
- **Реализация:** (1) переименования разделов «Доступы»/«PERMsoc»/«ИИ»/«Справка»/«Сводка»;
  (2) emoji→Material-иконки, субсет шрифта 20→37 глифов (18 388 B), идемпотентность
  build-script по sha256(source_sha+ICON_NAMES), `build/icon_codepoints.json`,
  R10.7-4 cmap-тест; (3) Android-логи — шеврон только при `exc_text`, дата
  DD.MM HH:MM:SS, блочная раскладка без `<pre><span>` и жёстких ширин, `.log-msg`
  full-width, `copiedTimer` cleanup (R10.7-3); (4) три route-driven модалки
  `#/access/roles|local|admins`, «Администраторы»→«Роли», аккордеон удалён, «Мой доступ»/
  «Telegram ID админа» без изменений, BackButton/deep-link/Esc; (5) удалён внешний
  GLOBAL-бейдж; README-реструктуризация.
- **Ревью/Scanner:** @Reviewer APPROVED WITH MINOR ISSUES → doc-nit закрыт.
  @Scanner **CLEAN — 0 blocker / 0 major**; R10.8-1 (Esc) и R10.8-5 (APP_VERSION
  2.51.0 vs README 2.52.0 + кэш старого субсета без `?v=`) закрыты точечно follow-up;
  R10.8-2 (stale-комментарий `section`/ветка `openHubCard`), R10.8-3 (мёртвый
  `TABS.icon`/`visibleTabs`/`tabMat`), R10.8-4 (doc-drift backlog — закрыт архивацией)
  — техдолг; **R10.7-3 и R10.7-4 ЗАКРЫТЫ**. Отчёт `plans/reports/round10.8_scanner_audit.md`.
- **Архитектура/ADR:** @Architect — ARCHITECTURE.md **§29 «Раунд 10.8»** (+§1/§9/§25).
  ADR-001 — «Доступы» как route-driven модалки (hash — источник истины, `git revert`
  как откат); ADR-002 — паритет `ICONS`==`ICON_NAMES`↔cmap WOFF2 (PUA из GSUB,
  идемпотентность учитывает `ICON_NAMES`, fontTools/brotli build-time only).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `7f3b790..31d2ce7`; `.env` без изменений; restart → active; `/api/health` = 200;
  шрифт `?v=2.52.0` → 200 (wOF2, 18 388 B); 0 ошибок.
- **Архивация:** `admin-ui-round108` → `plans/archive/admin-ui-round108/`
  (**plans/archive/ — 30 папок**; plans/features/ — 6 активных F-1…F-6). README
  счётчик 5073→5076; `APP_VERSION` 2.52.0.
- **Осталось вручную:** live Android smoke-тест **T-1254** (логи: ширина/дата/текст/
  отсутствие невидимого поля) и **T-1258** (три отдельных окна «Доступов»); опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.8`):** R10.8-2 (info — stale-комментарий/
  осиротевшая ветка `openHubCard`), R10.8-3 (info — мёртвый `TABS.icon`/`visibleTabs`/
  `tabMat`, pre-existing), R10.8-4 (info — doc-drift backlog, закрыт @PM); закрытые
  R10.8-1/-5; закрытые из 10.7 — R10.7-3/-4.

### Раунд 10.9 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d2d1215 + f928225)

«UI/UX-правки админ-минги — PERMsoc owner-блоки и под-флаг Славика, сохранение
скролла, переписанные описания, удаление «Тяжёлых фич»/перенос «Бюджета»,
dashboard-health, display-name, градиент». Единственная фича — `admin-ui-round109`
(spec @Architect + tasks @PM + ADR-109; T-1270…T-1314, продолжает T-1269).
HEAD == origin/master == `f928225` (`d2d1215` + `f928225`, поверх `51f308b` —
docs-финал 10.8; прод до деплоя — `31d2ce7`). **Статус: COMPLETED + DEPLOYED.**
FOLLOWS round10.8-epic; цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `d2d1215` feat(admin,web,plans): раунд 10.9 — PERMsoc-блоки,
  сохранение скролла, описания, доступность ключей по функциям, display-name,
  градиент (тесты 5105) — **34 файла**; `f928225` docs(plans): раунд 10.9 —
  деплой-верификация; push origin/master.
- **Тесты:** 5105 passed / 0 failed (baseline 10.8 = 5076; +29; 1 pre-existing
  warning + «closed 12 leaked aiosqlite connection(s)» — ресурс-предупреждение).
  Каталог **400 / 90 / 372 / mapped 88** (`TAB_RULES` 19, `CONFIG_TAB_TITLES` 19);
  `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` чист.
- **Реализация:** (п.1) PERMsoc — 4 сворачиваемых `<details class="owner-block">`
  (Славик/Оля/Мимикрия/Общее), в каждом ровно один рабочий тумблер
  (`PERMSOC_OWNER_BLOCKS`/`_permsocOwnerGroups`/`PERMSOC_TOGGLE_KEYS`; generic-bool
  дубли и master-карта удалены); backend — новый `flags.slavik_enabled`
  (`SLAVIK_ENABLED` default True), `reactions_persons` удалена,
  `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`,
  `TAB_PERMSOC` без persons; (п.3) `_preserveScroll` для `document.scrollingElement`
  И `.scroll-area` (restore в `$nextTick`) — скролл не прыгает при сохранении,
  вкл. fullscreen; (п.4) ВСЕ описания/титулы переписаны (plain ironic language,
  тест на 28 запрещённых жаргон-подстрок + AI-шаблон); (п.5) карточка «Тяжёлые
  фичи» удалена (per-chat dream/nostalgia/lore_auto остаются в «Сводке»);
  (п.6) «Бюджет фона» перенесён в «Сводку» (`loadBudgetInfo` из `loadOversight`;
  backend/endpoint не тронуты); (п.7.1) dashboard «Доступность ключей» — 4
  функциональные группы (main+fallback / транскрибация / саммаризация видео /
  эмбеддинги) + реальный health `probe_openai` (ok/error/timeout/unreachable/
  not_configured; `stt_groq` → `POST /audio/transcriptions` multipart WAV, таймаут
  5с; кэш per `module_id`: 2xx 60с, ошибки 10с, stale-200 не отдаётся), старый
  блок → «История доступности ключей»; (п.7.2) 7 `models.*_display_name` первым
  полем каждого провайдер-блока, ширина формы `max-w-3xl`; (п.8) градиент быстрее
  (`--grad-speed:14s`, `grad-drift 18s`).
- **ADR-109 (Accepted @Architect 12.09.2026):** ADR-109-1 — display-name как 7
  новых `ParamSpec` (`models.*_display_name`, Settings, глобальные); ADR-109-3 —
  health реальным POST вместо `GET /models` (`probe_openai` chat/embeddings/stt,
  кэш per `module_id`); ADR-109-4 — `SLAVIK_ENABLED` для независимого тумблера
  Славика; ADR-109-5 — «Бюджет фона» → «Сводка».
- **Ревью/Scanner:** @Reviewer REJECTED (1 Critical + 1 High + 2 Medium + 3 Low) →
  фиксы (STT probe, AI-описания, титулы, fullscreen-скролл, dead code, owner-блоки,
  JS-единицы) → APPROVED WITH MINOR ISSUES → follow-ups закрыты. @Scanner
  **CLEAN — 0 blocker / 0 major / 0 medium**; 3 low R10.9-1/-2/-3 + 3 info
  R10.9-4/-5/-6; R10.9-6 закрыт архивацией. Отчёт
  `plans/reports/round10.9_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§30 «Раунд 10.9»** (+§1/§9/§25).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward
  `31d2ce7..d2d1215`; `.env` без изменений; restart → active; `/api/health` = 200;
  0 ошибок.
- **Архивация:** `admin-ui-round109` → `plans/archive/admin-ui-round109/`
  (spec.md + tasks.md + ADR-109.md) (**plans/archive/ — 31 папка**;
  plans/features/ — 6 активных F-1…F-6). README счётчик 5105; `APP_VERSION` 2.53.0.
- **Осталось вручную:** live Android smoke — **T-1277** (owner-блоки/тумблеры
  PERMsoc), **T-1290** (скролл при сохранении), **T-1292/T-1294**
  (dashboard-health/«Доступность ключей»), **T-1302** (форма провайдеров/
  display-name), **T-1305** (градиент); реальное Android-устройство недоступно
  @Builder, статически покрыто `tests/test_webapp_round109_ui.py` + JS-юниты;
  опциональный betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.9`):** R10.9-1 (low — `model_source`
  запасных/эмбеддинг-записей снова `"code"` при конфиге, metadata-only),
  R10.9-2 (low — эмбеддинг-фоллбэки читаются из `settings`, не через
  `hot`/`_resolve`; `emb_fallback*` исчезают без env-ключа), R10.9-3 (low —
  устаревший docstring `status_service.py`), R10.9-4 (info — кэш health по
  `module_id` не инвалидируется при смене base_url/key/model ≤60с), R10.9-5
  (info — docstring `_LLM_BLOCKS` без `transcribe_groq`; `ConnectTimeout` →
  «timeout»); R10.9-6 закрыт архивацией; R10.8-2/-3 остаются открытыми.
- **⚠️ Вне скоупа:** пункт 2 исходного ТЗ — инфраструктура локального IDE
  владельца (не часть бота); в репозитории и в графе не фиксируется.

### Раунд 10.10 — финал (12.09.2026) — ЗАКОММИЧЕН И ЗАДЕПЛОЕН (d082800 + a477747 + 772db08)

«UI/UX-правки админ-минги — шапка в fullscreen, мобильный график доступности
ключей, реальные значения «Провайдеров», ЛС heavy-modules OFF, «Роли» с
аватарами». Единственная фича — `admin-ui-round1010` (spec @Architect + tasks @PM +
ADR-1010-1/2/3; T-1315…T-1328, продолжает 10.9). HEAD == origin/master == `772db08`
(`d082800` + `a477747` + `772db08`, поверх `da85b60` — docs memory-sync 10.9; прод
до деплоя — `d2d1215`). **Статус: COMPLETED + DEPLOYED.** FOLLOWS round10.9-epic;
цикл раунда полностью закрыт (Step 10).

- **Коммиты (master):** `d082800` fix(admin,web,api,scripts,plans): раунд 10.10 —
  fullscreen safe-area, mobile key-chart, реальные значения провайдеров, ЛС
  heavy-modules OFF, роли с аватарами (тесты 5144); `a477747` fix(scripts): раунд
  10.10 — standalone-запуск `disable_dm_heavy_modules` (sys.path bootstrap) +
  регресс-тест CLI (тесты 5145); `772db08` docs(plans): раунд 10.10 —
  деплой-верификация; push origin/master.
- **Тесты:** 5145 passed / 1 skipped / 0 failed (baseline 10.9 = 5105; Scanner
  зафиксировал 5140 + 1 skipped на момент аудита — до CLI-регресс-теста).
  `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` чист. Каталог **400 / 90 / 372 / mapped 88** (`TAB_RULES` 19,
  `CONFIG_TAB_TITLES` 19) — без изменений; ноль новых PG-DDL; SQLite v8;
  `bot.py` router order, `media/` и `.env` не тронуты.
- **Реализация:** (п.1) fullscreen-паддинг шапки — `.fullscreen-mode
  header.header-sticky` padding `calc(base + max(env(safe-area-inset-*),
  var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*)))` —
  профиль-блок не перекрывается нативными кнопками Telegram; 10.7 (ширина) и 10.9
  (`.scroll-area`) не тронуты; (п.2) мобильный график key-availability —
  RENDER-фикс: окно строится ОТ КОНЦА (`minStart`, cap ≤ `MAX_HISTORY_POINTS`,
  без `break`/`slice`) — новейшие сэмплы больше не отбрасываются; дорожки на
  провайдера + временная сетка `SAMPLE_BUCKET=300` (min 12 бакетов), динамическая
  высота, `pointRadius:3` при 1 сэмпле, пропуск = `null` + `spanGaps:false`;
  контракт `/api/status/key-history` (`api_payload`) НЕ изменён; (п.3)
  «Провайдеры» показывают реальные значения — `:value="blockFieldValue(f)"` +
  `@input` вместо `v-model`; `blockFieldValue` возвращает `''` для пустого
  черновика и значение `configItems` при отсутствии черновика, секреты
  (`type==='object'`) → `''` (placeholder-маска); `blockDrafts`/`blockResults`
  сброшены в `loadConfig` и `setActiveChat`; `saveBlock`/MINOR-3 (`null`=не
  трогать, `''`=очистить) не менялись; (п.4) ЛС heavy-modules OFF; (п.5) «Роли» —
  аватар + ник + мелкий серый ID, backend `global_user_display_info` (RAM-TTL 1ч,
  `get_chat(user_id)`→first/last→username, фото через `getUserProfilePhotos`;
  транзиентные `TelegramRetryAfter`/`TelegramNetworkError` НЕ в негатив-кэш,
  fail-open), `/api/admins` обогащает КОПИИ под `requires_permission("access")`,
  `Semaphore(5)`+`gather`; фронт `admin.avatarUrl` (blob через прокси, `@error`),
  `adminInitial`, `display_name||username`, ID `text-[10px] text-gray-500
  font-mono`; ширины `w-36→w-24`, ID-инпут `flex-1 min-w-0`, кнопка `shrink-0`.
- **ADR-1010:** ADR-1010-1 — ЛС heavy-modules OFF (`gates.dream/nostalgia=false` +
  4 override=false; `ensure_scope_profile(dm=True)` DM-дефолты;
  `scripts/disable_dm_heavy_modules.py` dry-run/`--apply`/`--restore`/`--chat-id`/
  snapshot, без DDL); ADR-1010-2 — key-chart render-only, дорожки + временная
  сетка 300с, контракт `api_payload` не меняется; ADR-1010-3 —
  `global_user_display_info(user_id)`, RAM-TTL 1ч, fail-open, обогащение
  `/api/admins`, фронт аватар/инициалы + мелкий серый ID.
- **Ревью/Scanner:** @Reviewer REJECTED (график отбрасывал новейшие данные) →
  фикс → APPROVED WITH MINOR ISSUES → restore exit-code Low закрыт. @Scanner
  **0 blocker / 0 major / 0 medium**; low R10.10-1/-2/-3 + info R10.10-4/-5
  (большинство точечно исправлено); отчёт
  `plans/reports/round10.10_scanner_audit.md`.
- **Архитектура:** @Architect — ARCHITECTURE.md **§31 «Раунд 10.10»** (+§3/§9/§25).
- **Деплой (198.46.175.136:/var/www/admin_bot):** git pull fast-forward; `.env` без
  изменений; `systemctl restart` → active (running); `/api/health` = 200; 0 ошибок.
- **DM data-run (прод, 12.09.2026):** `scripts/disable_dm_heavy_modules.py`
  применён — **1 активный ЛС изменён** (сон/ностальгия/саммаризация OFF),
  снапшот `var/dm_modules_off_snapshot_20260911T201219Z.json`; повторный dry-run —
  **0 изменений** (идемпотентно). F-14 gate (`bot.py flags.summary_enabled`) не
  тронут.
- **Архивация:** `admin-ui-round1010` → `plans/archive/admin-ui-round1010/`
  (spec.md + tasks.md + ADR-1010-1/2/3.md) (**plans/archive/ — 32 папки**;
  plans/features/ — 6 активных F-1…F-6). README счётчик 5145; `APP_VERSION` 2.54.0.
- **Осталось вручную:** live Android QA — **T-1317** (шапка fullscreen),
  **T-1320/T-1323/T-1332** (мобильный график/провайдеры/роли), UI spot-check
  DM-тумблеров OFF (**T-1328**); реальное Android-устройство недоступно @Builder,
  статически покрыто `tests/test_webapp_round1010_ui.py` +
  `tests/test_scripts_round1010_dm_off.py` + JS-юниты; опциональный
  betterstack-401 fix. Не блокирует закрытие цикла.
- **Техдолг раунда (KG `tech-debt-round10.10`):** R10.10-1 (low — скрипт DM:
  `total`/`noop`/dry-run-count игнорируют `--chat-id`; операторский вывод),
  R10.10-2 (low — `meta.note` перезаписывается и не откатывается snapshot'ом),
  R10.10-3 (low — `renderKeyHistoryChart` ранний return без `destroy()` старого
  Chart.js), R10.10-4 (info — `loadAdmins` без `avatarSkipped`/`.catch`, повторные
  blob-запросы), R10.10-5 (info — `adminInitial` дублирует `avatarInitial`,
  ветка `admin.username` недостижима).
- **⚠️ Вне скоупа:** П.6 ТЗ — Headroom saved-tokens stats (внешняя
  IDE-инфраструктура владельца, не часть бота); в репозитории и в графе НЕ
  фиксируется как сущность.

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

## Свежие архивы (plans/archive/ — 32 папки)

- `admin-ui-round1010` — **Раунд 10.10, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-1010-1/2/3, T-1315…T-1328: fullscreen safe-area паддинг шапки, мобильный график доступности ключей (окно от конца, дорожки + 300с сетка), реальные значения полей «Провайдеров» (`blockFieldValue`), ЛС heavy-modules OFF (`disable_dm_heavy_modules.py`, прод data-run 1 ЛС), «Роли» с аватаром+ником+мелким серым ID; каталог 400/90/372/mapped 88; тесты 5145 passed / 1 skipped; §31)
- `admin-ui-round109` — **Раунд 10.9, 12.09.2026** (единственная фича, spec @Architect + tasks @PM + ADR-109; T-1270…T-1314: PERMsoc owner-блоки + `flags.slavik_enabled`, сохранение скролла (`_preserveScroll`), переписанные описания/титулы, удаление «Тяжёлых фич», «Бюджет фона»→«Сводка», dashboard «Доступность ключей» (4 группы) + реальный health `probe_openai`, 7 `models.*_display_name`, `max-w-3xl`, градиент 14s/18s; каталог 400/90/372/mapped 88; тесты 5105; §30)
- `admin-ui-round108` — **Раунд 10.8, 11.09.2026** (единственная фича, spec @Architect + tasks @PM, T-1243…: переименование разделов, emoji→Material-иконки (субсет 20→37, 18 388 B), фикс логов на Android, route-driven окна «Доступов», README; тесты 5076; §29; ADR-001-access-windows-modal + ADR-002-icon-subset-parity)
- `admin-ui-bugfixes-round107` — **Раунд 10.7, 11.09.2026** (единственная фича, spec T-1224: UI/UX-багфиксы админ-минги — scope*-computed, safe-area шапки, компактный юзер-блок, ellipsis ключей, uptime gap-fill, clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20; тесты 5042; §28)
- `tma-ia-modules-rework` — **Раунд 10.6, 11.09.2026** (единственная фича, T-1155…T-1223: IA-ребейлд TMA — единый navbar, 11 Модулей-тумблеров, Настройки AI (7) + RAG→Память, чистый PERMsoc, Леха/Костик раздельно, provider-блоки + `POST /api/llm/test`; каталог 392/91/364/mapped 89; тесты 5027; §27)
- `tma-relume-redesign` — **Раунд 10.5, 10.09.2026** (единственная фича, T-1066…T-1148: полный редизайн TMA по Relume — navbar/hubs/hash-роутинг/scope-switcher/key-history/матрица ролей/градиенты/Material Symbols; тесты 4962; §26)
- `frontend-advanced-collapse-default` — **Раунд 10.4, 10.09.2026** (D, T-1018…T-1023: аккордеоны «Расширенные» свёрнуты по умолчанию, AC-B1-тест; §24)
- `frontend-memory-sleep-nostalgia` — **Раунд 10.4, 10.09.2026** (C, T-1006…T-1017: «Память» + вкладки «Сон»/«Ностальгия», progressive-разметка; §24)
- `frontend-llm-providers-layout` — **Раунд 10.4, 10.09.2026** (E, T-1024…T-1032: LLM Провайдеры — 4 секции: модели→ключи→фолбэк→расширенные; §24)
- `frontend-reorg-modules-reactions` — **Раунд 10.4, 10.09.2026** (A, T-974…T-989: «Функции PERMsoc» 17 групп (девиансия D-A1), «Модули», лор-настройки; §24)
- `frontend-limits-temperature-budgets` — **Раунд 10.4, 10.09.2026** (B, T-990…T-1005: бюджеты per-чат (флаг + бэкфил), select-температура, «Имена людей» + build_alias_resolver; §24)
- `frontend-relations-participants` — **Раунд 10.4, 10.09.2026** (F, T-1033…T-1044: вкладка «Участники и отношения», перенос блока участников; §24)
- `backend-relations-nickname` — **Раунд 10.4, 10.09.2026** (H, T-1057…T-1065: username для всех строк каскада имён, Semaphore(5), фото топ-50, R16; §24)
- `backend-chat-1002661910336-scaling` — **Раунд 10.4, 10.09.2026** (G, T-1045…T-1056: per-chat лимиты ×1.5–×2 (15 override, бэкфил), _resolve_from_root-харденинг, граница G-4; §24/§25)
- `tma-chat-selector-fixes` — **Раунд 10.3, 09–10.09.2026** (F-13, T-925…T-944: единый селектор чата, удаление ✕/пикера, фикс пустых вкладок, z-index 45; §23)
- `dm-user-settings` — **Раунд 10.3, 09–10.09.2026** (F-14, T-945…T-964: ЛС-настройки вариант A, саммари default-off; §23)
- `direct-sandbox-budget-investigation` — **Раунд 10.3, 09–10.09.2026** (F-15, T-965…T-973: прод-диагностика sandbox budget + graphrag JSON, фиксы; §23/§24)
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

- **adminbot-backend** — aiogram 3.31 (polling) + FastAPI (`web/app.py`) + asyncpg + aiosqlite; APP_VERSION=2.54.0 (раунд 10.10); порядок роутеров bot.py: slava_presence → alan_greeting → kostik → alan → dead_page → war_alert → common → olya → slavik → vasya (без изменений). F-12 добавил oversight-API (web/api/oversight.py), F-7/F-10 — access/gates/budget-роуты.
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
«Безопасность сервера» выше); **милстоун `round10.3-epic` (AdminBot → COMPLETED +
DEPLOYED, конвенция round10.2-fixes)** — раунд 10.3 ЗАВЕРШЁН, ЗАКОММИЧЕН и
ЗАДЕПЛОЕН (коммит 1410a68, 09.09.2026 12:33 UTC; рестарт 12:37 UTC, active;
тесты 4831; прод-диагностика задачи 5 — recon: direct-chat-sandbox-budget);
3 фичи F-13 tma-chat-selector-fixes + F-14 dm-user-settings + F-15
direct-sandbox-budget-investigation (T-925…T-973) → **ARCHIVED_IN plans-structure
+ WAS_PART_OF round10.3-epic** (HAS_PLAN/PLANNED_IN/PART_OF/ARCHITECTED удалены,
конвенция F-7…F-12); ARCHITECTURE.md §23/§24;
**милстоун `round10.4-epic` (AdminBot → COMPLETED + DEPLOYED, 10.09.2026)** —
раунд 10.4 «Реструктуризация TMA-миниаппа + точечные фиксы» (9 пунктов ТЗ):
8 фич feature-frontend-advanced-collapse-default (D), feature-frontend-memory-sleep-nostalgia
(C), feature-frontend-llm-providers-layout (E), feature-frontend-reorg-modules-reactions
(A), feature-frontend-limits-temperature-budgets (B), feature-frontend-relations-participants
(F), feature-backend-relations-nickname (H), feature-backend-chat-1002661910336-scaling
(G) — **все COMPLETED + ARCHIVED** (WAS_PART_OF round10.4-epic + ARCHIVED_IN
plans-structure; HAS_PLAN/PLANNED_IN/ARCHITECTED_IN удалены — конвенция F-7…F-12;
HAS_SPEC/HAS_TASKS и цепочка DEPENDS_ON D←C←E←A←B←F←H←G сохранены как исторический
факт); архитектурная фаза зафиксирована @Architect (KG: round10.4-specs +
round10.4-dependencies; Step 0 — recon: tma-structure-10.4); конфликт-матрица:
F-1 PRECEDES B/G — учтён (фича активна), F-3/F-4 AFTER round10.4-epic (активны),
F-5 AFTER B/G (активна, R10.4-7 — её кандидат), F-6 (plans/features/user-aliases-admin)
SUPERSEDED_BY round10.4-epic — подтверждена; REGISTRY 383/**74**/359 (коррекция
71→74 — ре-дизайн 10.2 BUG-3; MED-017); техдолг-кандидаты следующего раунда —
KG `tech-debt-round10.4` (R10.4-4…R10.4-7, B-13 points 2-4, HIGH-004-остаток);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **26 папок**;
HEAD == origin/master == `0bdf272` (коммит раунда 10.4: бэкфилы применены,
CHAT_THREAD_MAX_CHARS=2000, тесты 4860, прод active);
**милстоун `round10.5-epic`** (AdminBot → COMPLETED + DEPLOYED, 10.09.2026) —
раунд 10.5 «Редизайн TMA по референсу Relume + гигиена репозитория»: единственная
фича `tma-relume-redesign` (T-1066…T-1148) → COMPLETED + DEPLOYED + WAS_PART_OF
round10.5-epic + ARCHIVED_IN plans-structure (HAS_PLAN/HAS_FEATURE/RELATED_TO/
HAS_DESIGN_PROJECT — сохранены как исторический факт; HAS_PLAN не удалялся);
ARCHITECTURE.md §9/§25/§26; R10.5-1/-2/-4 закрыты, техдолг-кандидаты — KG
`tech-debt-round10.5` (R10.5-3/-5/-6/-7, ARCH §25); plans/features/ — **6 активных**
(F-1…F-6); plans/archive/ — **27 папок**; HEAD == origin/master == `c01ed72`
(коммиты 918f675 + c01ed72, тесты 4962, деплой 198.46.175.136 active/health 200,
0 ошибок); остаётся ручной live-smoke T-1153 + опц. betterstack 401.
**милстоун `round10.6-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.6 «Переработка IA TMA»: единственная фича `tma-ia-modules-rework` (T-1155…T-1223)
→ COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.6-epic +
ARCHIVED_IN plans-structure; sidebar удалён, «Модули» (11) + «Настройки AI» (7) + чистый
PERMsoc + provider-блоки + `POST /api/llm/test`; каталог 392/91/364/mapped 89/TAB_RULES 19;
5 master-флагов default ON с реальными гейтами; ARCHITECTURE.md §27 (+§25/§9/§6/§2);
Scanner 0 blocker/0 major (R10.6-1/-3 закрыты; техдолг-кандидаты — KG `tech-debt-round10.6`:
R10.6-2/-4/-5/-6); plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **28 папок**;
HEAD == origin/master == `4055434` (коммиты 6f91e8b + 4055434, тесты 5027, деплой
198.46.175.136 active/health 200, 0 tracebacks); остаётся ручной live-smoke (desktop/Android
WebView) + опц. betterstack 401.
**милстоун `round10.7-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.7 «UI/UX-багфиксы админ-минги»: единственная фича `admin-ui-bugfixes-round107`
(spec T-1224) → COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.7-epic
+ ARCHIVED_IN plans-structure; scope*-computed, safe-area шапки, компактный юзер-блок,
nav labels без per-letter wrap, ellipsis ключей, uptime gap-fill (5-мин сетка/down),
clipboard-ghost, лог-колонки, copy-on-row, dead ICONS 26→20; ARCHITECTURE.md §28 (+§9/§25);
Scanner 0 blocker/0 major (R10.6-5 закрыт; техдолг-кандидаты — KG `tech-debt-round10.7`:
R10.7-1…R10.7-5); plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **29 папок**;
HEAD == origin/master == `bb59476` (коммиты 7f3b790 + bb59476, тесты 5042, деплой
198.46.175.136 active/health 200, 0 errors); остаётся ручной live-smoke исправленного UI
+ опц. betterstack 401.
**милстоун `round10.8-epic`** (AdminBot → COMPLETED + DEPLOYED, 11.09.2026) —
раунд 10.8 «Точечные UI-правки админ-минги»: единственная фича `admin-ui-round108`
(T-1243…) → COMPLETED + DEPLOYED + WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.8-epic
+ ARCHIVED_IN plans-structure; переименование разделов, emoji→Material (субсет 20→37,
18 388 B), Android-логи, route-driven окна «Доступов», README, APP_VERSION 2.52.0;
ARCHITECTURE.md §29 (+§1/§9/§25); Scanner 0 blocker/0 major (R10.8-1/-5 закрыты;
техдолг — KG `tech-debt-round10.8`: R10.8-2/-3/-4; R10.7-3/-4 закрыты);
plans/features/ — **6 активных** (F-1…F-6); plans/archive/ — **30 папок**;
HEAD == origin/master == `976e335` (коммиты 31d2ce7 + 976e335, тесты 5076, деплой
198.46.175.136 active/health 200, 0 errors, шрифт wOF2 18 388 B); остаётся ручной
Android smoke T-1254 (логи)/T-1258 (окна «Доступов») + опц. betterstack 401.
**милстоун `round10.9-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.9 «UI/UX-правки админ-минги»: единственная фича `admin-ui-round109`
(T-1270…T-1314, spec @Architect + tasks @PM + ADR-109) → COMPLETED + DEPLOYED +
WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.9-epic + ARCHIVED_IN plans-structure;
PERMsoc owner-блоки (4) + `flags.slavik_enabled`, `_preserveScroll` для
`document.scrollingElement`/`.scroll-area`, переписанные описания/титулы,
«Тяжёлые фичи» удалены, «Бюджет фона»→«Сводка», dashboard «Доступность ключей»
(4 группы) + реальный health `probe_openai` (TTL 2xx 60с/ошибки 10с), 7
`models.*_display_name`, форма `max-w-3xl`, градиент 14s/18s; каталог
400/90/372/mapped 88; ARCHITECTURE.md §30 (+§1/§9/§25); Scanner 0 blocker/0 major/
0 medium (3 low R10.9-1/-2/-3 + 3 info R10.9-4/-5/-6; R10.9-6 закрыт; техдолг —
KG `tech-debt-round10.9`); plans/features/ — **6 активных** (F-1…F-6);
plans/archive/ — **31 папка**; HEAD == origin/master == `f928225` (коммиты
d2d1215 + f928225, тесты 5105, деплой 198.46.175.136 active/health 200, 0 ошибок,
APP_VERSION 2.53.0); остаётся ручной live Android smoke T-1277/1290/1292/1294/
1302/1305 + опц. betterstack 401. ⚠️ Пункт 2 ТЗ (инфраструктура локального IDE
владельца) — вне скоупа проекта.
**милстоун `round10.10-epic`** (AdminBot → COMPLETED + DEPLOYED, 12.09.2026) —
раунд 10.10 «UI/UX-правки админ-минги»: единственная фича `admin-ui-round1010`
(spec @Architect + tasks @PM + ADR-1010-1/2/3; T-1315…T-1328) → COMPLETED + DEPLOYED
+ WAS_PART_OF/COMPLETED_IN/DEPLOYED_IN round10.10-epic + ARCHIVED_IN plans-structure;
fullscreen safe-area padding шапки, мобильный график доступности ключей (окно от
конца), реальные значения полей Провайдеров (`blockFieldValue`), ЛС heavy-modules
OFF (`disable_dm_heavy_modules.py` + data-run 1 ЛС), «Роли» с аватаром+ником+мелким
ID; каталог 400/90/372/mapped 88; ARCHITECTURE.md §31 (+§3/§9/§25); Scanner
0 blocker/0 major/0 medium (low R10.10-1/-2/-3 + info R10.10-4/-5; техдолг —
KG `tech-debt-round10.10`); plans/features/ — **6 активных** (F-1…F-6);
plans/archive/ — **32 папки**; HEAD == origin/master == `772db08` (коммиты
d082800 + a477747 + 772db08; тесты 5145 passed / 1 skipped / 0 failed; деплой
198.46.175.136 active/health 200, 0 ошибок, APP_VERSION 2.54.0); остаётся ручной
live Android QA T-1317/1320/1323/1332 + UI spot-check DM-тумблеров OFF T-1328.

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
- **Раунд 10.4 (ЗАВЕРШЁН + DEPLOYED, 10.09.2026, коммит 0bdf272):** порядок фич
  D→C→E→A→B→F→H→G выполнен; REGISTRY 383/**74**/359 без изменений (коррекция счётчика
  групп 71→74 — ре-дизайн 10.2 BUG-3; MED-017; новые ключи/группы ЗАПРЕЩЕНЫ);
  SQLite v8, роутеры bot.py, каноны промптов, known_sections() — без дифов;
  девиансия D-A1 реализована (фича A: war/common/goodmorning/word_reactions →
  «Функции PERMsoc», 17 групп); бэкфилы backfill_104_chat_flags.py +
  backfill_104_overrides.py применены; техдолг-кандидаты следующего раунда:
  R10.4-4…R10.4-7, B-13 points 2-4, HIGH-004 (KG `tech-debt-round10.4`);
  конфликт-матрица исходно: F-1 (T-648 атомарный POST) — учтён ДО B/G.
