# AdminBot — Memory Index (plans/MEMORY.md)

> **Сжат 2026-10-15 (plans cleanup CLEAN-1).** Полный слепок прежнего файла (539 КБ, баннеры
> Step 0–Step 10 всех эпиков, раунды 10–10.48) — **plans/archive/MEMORY-full-snapshot-2026-10-15.md**.
> Здесь только проверенные durable-знания: правила, архитектурные контракты, релизный процесс,
> уроки. Операционные статусы — plans/workflow_state.md; метрики раундов —
> plans/archive/metrics-2026-10-15.md; история эпиков — plans/archive/ (карта: archive/INDEX.md).
> Детальные durable-сущности — OpenViking: `viking://user/default/memories/entities/project/*.md`
> (asap7_chat_membership_lifecycle, asap7_cover_prompt_manifest, asap7_cover_prompt_ordering,
> asap7_direct_chat_architecture, asap7_help_canon, asap7_module_contract, asap7_release_workflow,
> asap7_test_infra_settings_reload, mca_round_1027, incident_summary_01, soul_1_status,
> release_isolation_and_gate_semantics, deploy_baseline_pointers, pet_project_standing_rule,
> fullscreen_direction и др.).

## 1. Действующие правила (нарушать нельзя)

- **SECRETS / R17 / R18.** `plans/current_task.md` — личный git-ignored файл владельца (проверено: ни в дереве, ни в истории git); деплой-заметки и секреты туда не переносить. Секреты никогда не логируются и не отдаются; API маскирует ключи до `{configured, last4}` (R17). Массовая замена секрета через git-историю (filter-repo) — ЗАПРЕЩЕНА (решение владельца, UPD3 раунда 10.17; R17-инцидент закрыт как Risk Accepted 16.09.2026).
- **Fail2ban на проде (198.46.175.136)** — подозрительные SSH-подключения → бан IP ~1 ч (бот/HTTP живы, banится только SSH). Запрещены: перебор логинов/паролей, коннекты чаще ~1/мин, поллеры с ретраями, сканы портов. Паттерн: один recon (~15 с) → один логин `nik` (креденшелы в `deploy_commands.txt`, не печатать) → порт закрыт = бан/cooldown, пауза ≥22 мин, макс 1 автоповтор → эскалация владельцу. Статус прода — HTTP `/healthz`:443 (не ограничен). Дублировано в `AGENTS.md`.
- **Канон промптов (ADR-1013-3).** Прод-промпты — модульные константы в коде; правка только через `PREV_…`-снапшот + байт-тесты; `services/prompt_migrations.py` (`PROMPT_MIGRATIONS`) не трогать; HEAD-каноны в `plans/docs/canon/`. Примеры пинов: `services/{factcheck,search,web,youtube,summary}_prompts.py` («перенесено ДОСЛОВНО из plans/ARCHITECTURE.md §…»).
- **No-false-acceptance.** Live-приёмки с платными вызовами/реальными ключами/реальным чатом — только владелец; имитация и выдача контурных проверок за live — запрещены; непроверенное помечается NOT_VERIFIED-with-причиной / PENDING OWNER.
- **PET_PROJECT — стоячее согласие (решение владельца 18.10.2026).** Проект — пет-проект (1–2 личных чата): готовые и проверенные функции включаются штатным релизом сразу во всех чатах — без канареечных этапов, сухих прогонов «для согласования» и отдельных разрешений на флаги; канареечные и владельческие approval-гейты отменены (JB-3 закрыт); новые искусственные гейты/согласования по инициативе агентов запрещены. Сохраняются: тесты, честные проверки, изоляция релиза, быстрый откат (защита данных). После выката — проверка поведения/публикаций/ошибок/логов; при серьёзной проблеме — чинить/откатывать. Device-проверки владельца фиксируются в `plans/owner_questions.md` и не блокируют. Правило — корневой `AGENTS.md` («Режим PET_PROJECT»); детали — OpenViking `pet_project_standing_rule`.
- **Единый Reviewer gate.** @Scanner удалён из контура (решение ~10.19) — секьюрити/аудит-линза внутри единого ревью; не назначать отдельного сканера.
- **Каталог параметров.** Новые ключи — только через REGISTRY `services/param_catalog.py` с rationale; перед добавлением grep по PG-only ключам (errata T-5074); `models.*`/`keys.*` — строго глобальные (`per_chat=True` только для {prompts, limits, flags, reactions, content, memory} и secret=False).
- **Бинарные артефакты/дебрис** (скриншоты, временные JSON, untracked-инструменты) в коммит не включать; рабочие пробы — в OPENCODE_WORKFLOW_SCRATCH.

## 2. Архитектурные контракты (durable)

- **Стек:** Python 3.12 / aiogram 3.x (polling) + FastAPI (`web/app.py`) + asyncpg (PG) + aiosqlite (SQLite+FTS5+vec0) + Vue3 global zero-build TMA. Порядок роутеров `bot.py` — DI-kwargs, не менять без конфликт-чека.
- **Хот-конфиг:** `hot.get(pg_key, default)` + ConfigCache (in-memory над PG, fail-open); per-chat слой: `chat_params` → `bot_settings` → дефолт. Правило S-1 (MCA): **«где читается — там и enforce»** (рассинхрон read/enforce — класс бага).
- **RBAC v2:** `services/permissions.py` + неймспейсы `section./param./key./action.`; GET /api/config маскирует секреты; per-chat роли `chat_admins.role_name`; priority: явный chat-гейт → `flags.<feature>_enabled` → False.
- **Канон инструментов:** R9=10 (`services/tool_schemas.py::TOOL_CALLING_TOOLS`), freeze ADR-1026-13, расширения только санкционированными фичами (A1/A2 tool-coordinator/chains; MCA довёл до 14). Каждому инструменту — категория {memory_read/external_read/paid_media/admin}, unknown → external_read, никогда admin.
- **Direct chat — physical-two-call-pipeline** (AMEND ADR-1022-3/4 + ADR-1023-3): Stage-1 Синтезатор → `parse_direct_synthesis` (`services/system2_handoff.py`) → Stage-2 Вербализатор (только текст по фактам); решение о действии ≠ итоговый текст; **третий LLM-вызов запрещён**; tool-loop `TOOL_MAX_ROUNDS=4`, ≤2 вызова/раунд, plain-fallback при провайдер-reject. Детали — OpenViking `asap7_direct_chat_architecture`, архив `plans/archive/features/asap7-cognitive-direct-pipeline/`.
- **Worker-бюджеты:** суточный ledger PG `worker_budget` (global/per-chat лимиты вызовов/токенов); тяжёлые фичи под Opt-In `gates`/`gates_opt_in`; деградация nostalgia→lore→dream.
- **SQLite-версионирование:** миграции идемпотентные, `user_version` строго по fortress-конвенции; на 2.58.69 — v33; guard mca-14: перед DDL — авто-бэкап + read-back, запас места ≥×2.0 оценки миграции; пины миграций в тестах — frontier-конвенция `>=` (урок F-5 mca-08).
- **Порядок мержа документации:** фича-артефакты живут в `plans/features/<slug>/`, после закрытия — `plans/archive/<slug>-round<NNNN>/`; с 15.10.2026 завершённые фичи — `plans/archive/features/<slug>/` (см. archive/INDEX.md).

## 3. Ключевые решения по темам (выборочно, с provenance)

- **Chat membership lifecycle (asap7).** Вход/выход бота — отдельный `@chat_lifecycle_router.my_chat_member` (ChatMemberUpdatedFilter IS_NOT_MEMBER→IS_MEMBER и обратно); synth join/leave/re-add/migrate покрыты REGRESSION-тестами; chat_member-события не удалять (fallback-ensure по флагам). Источник: `plans/archive/features/asap7-cognitive-direct-pipeline/architecture.md` §P7-C, sweep-fix-report; OpenViking `asap7_chat_membership_lifecycle`.
- **Cover Prompt Manifest / ordering (asap5→asap7).** CoverPromptManifest + admin-only web-просмотр кадров, STORY-minimum, минимальные артефакты; порядок промптов обложки зафиксирован манифестом (ordering) — дрейф ловится тестами. Источник: `plans/archive/asap5-final-fixes-round1049/` (rca_cover), `plans/archive/features/asap7-cognitive-direct-pipeline/audit-cover.md`; OpenViking `asap7_cover_prompt_manifest`, `asap7_cover_prompt_ordering`.
- **Help-канон (v6 D14).** INFO v8→v9 (стиль обложки меняет внешность, не сюжет; потерявшая сюжет стилизованная версия не публикуется), GUIDE v5→v6 (stale-guard D01, карта переопределений D07, воронка Инициативы C06A, тумблер Случайности D08, цепочка опыта D05, honest-исходы D09–D13); слепки `PREV_ASAP8V6_*` байт-в-байт; help-утверждения приколоты к живому коду (TestHelpMatchesShippedRuntime). Источник: commit `51a243f`, `plans/features/asap8-v6-remediation/f10-report.md`; OpenViking `asap7_help_canon`.
- **Module contract (v6 D11 + mca-17a).** Продуктовые модули декларируют anchors ∈ PROCESS_REGISTRY; реестр процессов code-declared (41+), lifecycle-состояния, heartbeat; неполный реестр = класс дефекта (D11 registry completeness). Источник: commit `2e40615`, OpenViking `asap7_module_contract`.
- **Release workflow.** Волны фич деплоятся агрегатно: per-feature деплой = `DEFERRED_TO_RELEASE` (§20 mca-plan); релиз = bump-коммит (APP_VERSION в коде+README/meta+version-пины) → prod fast-forward → `systemctl restart` → healthz 200 → boot-проверка; откат: cold `git revert` (DDL=0) или soft-откат env-kill-switch; binding фичи: Reviewed-Commit + Working-Tree-Hash (+product-hash), **без процесс-журналов** (урок mca-15 [I-1]: workflow_state в WTH = ложные дрейфы). OpenViking `asap7_release_workflow`.
- **Test infra / settings reload.** Цепочка `importlib.reload(config.settings)` в тестах ломает class-identity (Settings до/после reload — разные классы) → массовые флуктуации (кейс asap7 sweep-fix: 97 failed → 2 failed после развязки); правила живут в `tests/conftest.py` (docstring + комментарии про reload-паттерн и reset кэшей после reload). Источник: `plans/archive/features/asap7-cognitive-direct-pipeline/sweep-fix-report.md`; OpenViking `asap7_test_infra_settings_reload`.
- **MCA round 1027 (программа 10.27–10.48).** 26 фич MCA-01…22 «Память, контекст, автономия»: волны 0–5, агрегатный релиз 2.58.67 (ADR-1027-1…-25 + ADR-1028-х); итог 2.58.31→2.58.67, v12→v33, каталог 473→523; эффективные состояния §20.2 (RED-зоны owner-gate: deep sleep PG-flag, квантовый ANU, vision). OpenViking `mca_round_1027`; план — `plans/docs/mca-round1027-plan.md`.
- **SOUL-1 (речь/характер) — ЗАДЕПЛОЕН 18.10.** Прод 2.58.86 (`eafbe2e7`) → 2.58.87 (`82e110d6`); все оси ON (gates 10/10): unified composer, character.core (фабричный авторский SOUL-02, rev `act:040581a3b4b0`, 2835 зн.), style.policy, humor craft/library/feedback, диагностика инициативы; `HUMOR_CANDIDATE_EVAL` OFF (механизм есть, 0 вызовов); withheld=11 (старые заводские удержаны, в effective не идут); style-global-save фикс (`68cd05b2`) подтверждён живьём (rev1→rev2); live-остаток 29 RFL — окно владельца 24–48 ч. OpenViking `soul_1_status` (id soul-1-release).
- **WIN-GLASS-P0 (fullscreen) — выпущен 2.58.85** (`95526863`): Windows launch-fullscreen — клиентский баг tdesktop#30963 (веб-код не управляет окном; обход `owner-steps.md`); Android — слой `web/static/glass-refraction.js` (только контролируемый фон, реальные смещения у кромок, ≤3 поверхностей); регрессия dropdown («Аналитика») исправлена в 2.58.87 (unclip на open; ассерт U02.4). OpenViking `fullscreen_direction` (id win-glass-p0).
- **CFG-блок (старт 18.10).** Строго последовательная очередь CFG-01→…→FINAL (CFG-01 в работе); CFG-05 = reuse существующего стекла, без нового.

## 4. Релизные/операционные инварианты

- Крон-прогон саммари: при деградации ожидаем `L1_FALLBACK_PACKAGE`/`LEGACY_FALLBACK`, но **никогда** пустой пакет в `L2_START` и **никогда** мета-текст в публикации; `SUMMARY_COVERAGE_DEGRADED reason=…` — диагностика.
- Kill-switch-паттерн: каждая MCA-фича имеет env-only флаг(и) default ON с OFF = бит-в-бит предыдущему релизу; мягкий откат — выключение флага.
- **Релизные конвенции (серия 18.10):** dual-line карты — `candidate_commit` = ревью-линия master, `deployed_commit` = релиз-линия; release-стадия гейта требует равенства и при двух линиях по дизайну не проходит (документируется `release-line`-файлом). SOUL-делы — семантический порт (`git apply` ханков на прод-блоки; P0: 5/8 byte-equal). Деплой: `%%`-эскейпинг (T0), F3-health → PID-анкер, автопод-откат при health-miss подтверждён. OpenViking `release_isolation_and_gate_semantics` (id release-conventions).
- **Graceful-exit контур (INC-SUMMARY-01, 2.58.82/83):** SIGTERM обрабатывают только собственные хендлеры (uvicorn `handle_signals=False` — aiogram иначе переустанавливает сигнал); runtime SQLite owner закрывается на shutdown (aiosqlite-поток non-daemon); bounds пред-генерации — kill-switch `SUMMARY_PREGEN_BOUNDS_ENABLED` (default ON) + orphan-run финализатор на старте. Детали — OpenViking `incident_summary_01`.
- GraphRAG rebuild: honest-fail на лимитах провайдера (429) → терминальный failed с checkpoint; resume — при рестарте, cooldown/parking kind-aware; NATURAL RESUME подтверждён (03.10.2026). `smart_archive` knn_smoke_failed — fail-soft (FTS serviceable).
- `EMBED_ASYNC_BATCH_ENABLED` — OFF до live-верификации Batch API владельцем.
- Денежные лимиты (`MCA_MONEY_LIMITS_ENABLED`) — default OFF; Episode backfill не включать до wired worker-budget (M-MCA05-3).
- Пустая публикация `msg 1120810` (29.09.2026) — кандидат на удаление, **только по прямому указанию владельца**.
- Restore-якоря: `pre_migration_*.db` последних миграций не удалять без ревизии (disk retention покрывает `pre_t*.db`, keep=2).

## 5. Уроки (воспроизведённые/root-cause, durable)

- Мок-тесты маскируют рантайм (B-1 mca-17c): persistence-пути проверять без моков; audit-пути — реальными чтениями.
- Async-воркеры vs синхронные миграции (T-5150): guard read-back выглядит как hang — лог-след цепочки миграций обязателен.
- Полный pytest при hang #121 — сегментными прогонами; финальные прогоны foreground (не фоновые задачи).
- Fresnel/Liquid Glass: level-A `feDisplacementMap` может не работать в реальном Telegram WebView — визуальные эффекты проверять в реальном WebView, не только в Chromium (hotfix6 round1025); оконные режимы tdesktop — клиентское поведение: launch-fullscreen веб-кодом не управляется (баг #30963, WIN-GLASS-P0).
- BetterStack 401: причина была в ingest-контракте (path-token → Bearer), не в хосте; US-регион × Bearer = 202.
- SSH-fleet: транзиентные таймауты порта 22 — не форсировать смену порта, переждать окно (запасные порты закрыты).
- TG Bot API: контейнер без `--local` даёт `getFile` ≤20 МБ; единый рубильник `TELEGRAM_LOCAL` (ADR-1025-6).
- owner-решения с ожиданием (хранить до закрытия): стартовый номер сида обложек (`SEEDED_COUNTER_START`, D8); edit-capable image-провайдер в Connections (DC-4).

## 6. Инфраструктура сервера (состояние, 09.09.2026 → активно)

- fail2ban 1.0.2 (`jail.local`: sshd maxretry=3/24h + recidive 1w; backend systemd, nftables), ufw: deny incoming, 22 LIMIT, 80/443 ALLOW (остальное закрыто снаружи: 4416/8000/8081/9000/5432/2019/10808), sshd hardening (`00-hardening.conf`: PermitRootLogin no, MaxAuthTries 3, LoginGraceTime 20…), password auth сохранена по требованию владельца.
- Follow-up владельца (открыто): миграция на SSH-ключи; `ignoreip` для статического IP владельца; CrowdSec как альтернатива; перенос `migrate_history` (1.1G) вне диска.
- Диск: retention-cron еженедельно Mon 06:30 UTC (denylist защищает БД/якоря/media/env/GraphRAG); journalctl vacuum 100M; при DDL — ревизия старых `pre_migration_*` (последний якорь — не удалять).

## 7. Указатели

- Текущее состояние задачи — `plans/workflow_state.md` (владеет Orchestrator), runtime-дневник — `plans/runtime_task.md`.
- Карта архива и журнал перемещений — `plans/archive/INDEX.md`; полные слепки — `plans/archive/MEMORY-full-snapshot-2026-10-15.md`, `plans/archive/backlog-history-2026-10-15.md`, `plans/archive/metrics-2026-10-15.md`.
- Канон (архитектура/бэклог-канон) — `plans/docs/canon/`; исследования — `plans/docs/`; pinned-отчёты — `plans/reports/` (там же 4 отчёта, читаемых тестами round1025 — не перемещать).
- Темы для деталей — OpenViking entities (см. шапку); исторические баннеры эпиков — слепок в archive.
