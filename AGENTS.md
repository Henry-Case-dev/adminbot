# AGENTS.md — правила проекта (обязательны для всех агентов)

## Обязательное включение новых функций при первом production-деплое (постоянное правило, 09.11.2026)

Проект — пет-проект. Любая **готовая** функция (реализована, независимо проверена, обязательные технические проверки пройдены) при **первом production-деплое включается глобально по умолчанию**.

Правила для всех агентов:

1. Заводское значение флага готовой функции при первом выкате — **включено**. Теневой режим, выключенное по умолчанию состояние, «отложенная активация» и ожидание отдельного разрешения **не могут** становиться постоянным состоянием готовой функции.
2. Существующие пользовательские настройки и чатовые override **не сбрасывать**; меняется только заводское значение и отсутствие явного пользовательского выбора.
3. Отключение флага **не является** способом закрыть дефект качества. Если функция даёт негодный результат, чинится причина: фильтрация, понижение в ранжировании, исправление источника данных — но не повторное выключение.
4. Технические проблемы и дефекты качества возвращаются на исправление ответственному исполнителю, а не оформляются как вопрос владельцу.
5. После выката проверяется **effective-state** (что реально включено в проде), сформированные данные, влияние на поиск/UI и результаты реальных проверок — с честной фиксацией того, что осталось непроверенным.

Это правило дополняет PET_PROJECT-политику (стоячее согласие на включение готовых функций) и не отменяет обязательных проверок, изоляции релиза и быстрого отката.

## Инфраструктура прод-сервера

**PRODUCTION (с 29.10.2026, миграция завершена):** новый VPS `192.255.209.205` (SSH `root`, рабочий каталог `/var/www/admin_bot`; штатный деплой: `git pull --ff-only` + `systemctl restart admin_bot`). Старый VPS `198.46.175.136` полностью очищен от Adminbot 29.10.2026 (адресная декомиссия, Reviewer ACCEPT): установка, данные, unit, контейнеры, volumes и cron удалены; данные отката существуют ТОЛЬКО в независимом бэкапе на машине владельца (`WorkspaceData/backups/adminbot-postmigration-2026-10-29/`, манифест и суммы проверены). НЕ деплоить туда и не считать резервом.

**FAIL2BAN.** На ОБОИХ серверах стоит fail2ban (старый — исторически, наблюдалось 06.10.2026: перебор имён пользователей → бан SSH ~1 час; новый — jail sshd включён 29.10.2026 при переключении): подозрительные подключения приводят к бану IP; при этом бот/HTTP остаются живы — банится только SSH-доступ.

Запрещено:
- перебор имён пользователей, паролей или ключей (логины строго из `deploy_commands.txt`: старый — `nik`, новый — `root`; значения не печатать и не коммитить);
- повторные/параллельные коннекты чаще ~1 раза в минуту;
- длинные поллеры с частыми попытками и ретраи сразу после неудачного auth;
- автобан-провокации любого рода (сканы портов хоста, брутфорс).

Разрешённый паттерн работы с продом:
1. **Один recon-коннект** коротким таймаутом (~15 с). Порт закрыт → считать это баном/cooldown: пауза ≥ 22 минут до следующей попытки, максимум 1 автоповтор, далее — эскалация владельцу.
2. Статус сервиса проверять по HTTP (порт 443, `/healthz`) — он не ограничен; HTTP 200 при закрытом SSH = «прод жив, недоступен только деплой-канал».
3. Деплой-коннекты: минимум подключений (один recon + один основной прогон), строгий одиночный логин, без фоновых поллеров с частыми ретраями.

## Режим PET_PROJECT — постоянное правило проекта (решение владельца 18.10.2026)

Проект — пет-проект: бот работает в 1–2 личных чатах владельца. Согласие владельца на включение **готовых и проверенных** функций — **стоячее**. Канареечные этапы, постепенное включение по чатам, сухие прогоны «для согласования» и отдельное разрешение на каждый флаг — не нужны и запрещены к введению по инициативе агентов.

Правила для всех агентов:
1. После реализации + независимого ревью + обязательных технических проверок — включать готовые функции **сразу во всех подключённых чатах** штатным релизом, без ожидания разрешений.
2. Технические проверки, изоляцию релиза и быстрый откат сохранять: это защита данных, а не формальность.
3. Не пропускать тесты и не выпускать заведомо сломанные функции.
4. После выката — проверять реальное поведение, публикации, ошибки и логи; при серьёзной проблеме — исправлять или откатывать без ожидания разрешений.
5. Проверки, требующие реального устройства/клиента: честно фиксировать, что осталось проверить у владельца, и **продолжать остальные задачи**, не блокируя релиз и независимую работу.
6. Запрещено по собственной инициативе создавать новые обязательные согласования, канареечные гейты и «ожидание владельца на флаг». Обращаться к владельцу — только при существенном продуктовом выборе, требующем его решения.

## Human Gate — обязательная сверка перед вопросом владельцу (постоянное правило, 18.10.2026)

Перед созданием любого Human Gate или вопроса владельцу агенты ОБЯЗАНЫ сверить: (1) актуальное ТЗ (`plans/current_task.md` и его поздние уточнения); (2) более поздние решения владельца (снапшоты `plans/features/**/source-*.md`); (3) существующие ответы (`plans/owner_questions.md`, `owner-decisions.md`, карты). Уже разрешённые вопросы не задаются повторно. Отменённые обязательные ручные проверки (например, device-чек-листы) не воссоздаются под новыми идентификаторами. Необязательная субъективная обратная связь не блокирует работу и не считается «ожиданием владельца». Реальный блокирующий вопрос задаётся немедленно через нативный `question`, а не откладывается в файл.

## Запрет самостоятельных квот на инструкции LLM (постоянное правило, 24.10.2026, ADDENDUM #3 §2.10)

**Запрещено без прямого требования владельца вводить самостоятельные токенные или символьные квоты, искусственно обрезающие управляющие инструкции LLM в любой функции проекта.**

Правило распространяется на новые компоненты, старые компоненты, рефакторинг, fallback-пути, вспомогательные LLM-вызовы, общие prompt builders и wrappers.

Правило **не** запрещает: технические пределы реального контекстного окна (`model_capacity`, `CHAT_CONTEXT_BUDGET_TOKENS`), лимиты генерации ответа (`max_tokens`, `{max_symbols}`), fallback/retry/таймауты/rate limits, функциональную обработку и сжатие данных, ограничения числа элементов выборки и ранжирования, существующий модуль «Бюджеты» чатов.

Признак нарушения: инструкция (Personality Core, Expression, Style Policy, авторские примеры, функциональные системные промпты) сокращается, вытесняется или исчезает из payload по локальному бюджету при достаточном реальном окне. Если ограничение одновременно затрагивает инструкции и данные — устраняется только квота инструкций, остальные функции механизма сохраняются.

Reviewer отклоняет новые искусственные квоты инструкций независимо от места реализации: имя переменной или функции значения не имеет.


## Project-specific workspace and backup hygiene (28 Oct 2026)

Create new workflow-owned temporary output only through the installed global `tools/workflow_housekeeping.py`. `allocate` writes under that config's `WorkspaceData/runs/`. New parallel Git worktrees use `worktree-path` (under `WorkspaceData/worktrees/`) and `git worktree add`, then `register-worktree`. Do not create sibling checkouts beside this repository. Do not hardcode a project path or a sibling worktree name pattern. Existing leftover checkouts must be classified against `git worktree list --porcelain`, cleanliness, commit reachability and active use before any `git worktree remove` (never `--force`, never delete the branch). Unknown or dirty trees stay.

Server-side `backups/`, `pre_migration_*.db`, `local_database.db`, and live production assets are not temporary workspace trash. `plans/reports/disk-analysis-2026-10-28.md` documents the owner's preference to retain 1–2 usable recent backups; only apply targeted retention after checking actual backup provenance, recoverability, and the rollback requirement. Preserve project-specific SSH/fail2ban rules and PET_PROJECT release policy unchanged.

## Owner is not mandatory QA (project rule, 2026-11-10)

Agents own verification. Never assign the owner unit, integration, regression or end-to-end tests; production observation; log, API, metric or scheduler checks; Telegram scenario checks; before/after comparisons; or "tell me if the bug returns". In this project the agents can reach the production host, the database, the logs and the Mini App harnesses, so these checks belong to Builder, Reviewer and DevOps.

`owner_live_checks` and similar pending items in this repository's maps, tickets and reports must be reclassified as: verified by agents with evidence; not verified due to a named technical unavailability; background observation the agents run themselves; or a genuine owner-only action. "The owner must run six P0 scenarios" and "the owner must watch the bot for a day" are not obligations and must not block DONE. Reassign them to the responsible agent or keep an honest internal status; never mark VERIFIED without proof and never delete a real unfinished check to raise a percentage.

Ask the owner only for a material product/architecture fork, an inaccessible credential or permission, or an irreplaceable action. Ordinary QA, visual assessment or re-checking a fix is never a human gate. In reports omit the owner-action topic entirely when there is nothing genuinely blocking; do not write "Действие владельца: не требуется" and do not repeat stale checks.

## PROJECT CONTINUITY AND ANTI-LOOP (permanent project rule, 2026-11-15)

The Orchestrator owns the whole approved project queue, not only the last active epic. Finishing a task, corrective, release train or slice is not a reason to stop the project. After a task is closed, record its actual state and evidence, update the canonical registry and `plans/workflow_state.md`, park only genuine future observations, identify the next unfinished task whose dependencies are satisfied, and continue work without waiting for a new owner command.

`Next execution: none` is allowed only when the owner explicitly paused the whole project, every approved engineering task is genuinely complete, no dependency-ready task exists, or a real external/owner gate blocks all safe work. A parked live observation, a completed release, an intermediate milestone, or the absence of a new owner message are not such grounds. Do not bypass safety, permissions or real human gates under the continuity rule; do not invent new gates for work that is already authorized.

State must survive session changes: keep the current task, phase, completed work, actual commit, open delta, blockers, applicable evidence, active agents and the next operation in the existing durable files. Resume from the last verified point; do not re-implement or re-review completed work because a session restarted.

Quality is not measured by the number of build-review-corrective cycles. Every new finding must be classified as a blocking product defect, a non-blocking follow-up, a procedural failure, or missing evidence. Start another corrective iteration only when an existing mandatory contract is demonstrably violated, and limit the repair and re-review to the actual affected area. A repeated problem after several fixes requires root-cause diagnosis and a different concrete strategy, not another identical cycle. When the mandatory engineering scope is complete and the evidence is sound, close the engineering task, park non-blocking observations separately, and continue the queue.