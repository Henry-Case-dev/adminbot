# MEMORY.md — AdminBot

> **Версия:** v2.28.0 DEPLOYED (прод, Epic 30, `714a4f6`, PID 939545). **Epic 31 (v2.29.0): IMPLEMENTED + REVIEW APPROVED (Шаг 6 @Memory, 2026-08-17) — @Builder реализовал T-235…T-239, @Reviewer APPROVED (1 Critical-фикс: утечка продового chat_id в .env.example откачена). 1366 тестов passed / 0 failed (baseline 1327 → +39). T-240 (коммит+пуш) и T-241 (деплой) — PENDING @DevOps.** **Epics 1–30 ALL DEPLOYED ✅.**
> **Дата:** 2026-08-17
> **Обновление:** 2026-08-17 — **Epic 31 (/summary для всех + setMyCommands + таймаут-фразы, v2.29.0) — Шаг 6 (@Memory, граф знаний после реализации и ревью): IMPLEMENTED ✅ + REVIEW APPROVED ✅. @Builder реализовал Epic 31 полностью: config/settings.py (SUMMARY_ADMIN_ONLY, _env_bool, False), handlers/summary.py (allow-check D94: 2 ветки admin_only→allowlist, silent deny сохранён), services/bot_commands.py (НОВЫЙ: setup_bot_commands, BotCommand("summary", «Саммари чата — прочитай, что ты пропустил, ленивец»), BotCommandScopeDefault, try/except → bool), bot.py (вызов в on_startup ДО start_polling, порядок роутеров НЕ тронут), services/summary_throttling.py (_THROTTLE_PHRASES 7 фраз: 2 канона дословно + 5 новых; format_remaining_seconds с _pluralize; ветка throttled: random.choice + .format(remaining=...) + event.reply best-effort; слот не перезаписывается; конструктор не менялся), .env.example, README.md (v2.29.0, 1366 тестов), тесты (tests/test_bot_commands.py новый; test_summary_throttling.py: silent→reply; test_summary_handlers.py: D94 комбинации). Тесты: **1366 passed / 0 failed** (baseline 1327 → +39). @Reviewer APPROVED: исправил 1 Critical (утечка продового chat_id в .env.example — GOODMORNING_TARGET_CHAT_IDS=-1002661910336 откачена на пустое значение) + 3 Minor (README про перезапись меню setMyCommands; риск 9 в ARCHITECTURE 40.7: denied-юзер при спаме получает фразу-отборку, т.к. троттлинг ДО allow-check; board.md синхронизирован). **Ключевой факт: BotFather НЕ нужен — setMyCommands из кода полностью заменяет BotFather-меню; scope = видимость (подсказка), НЕ ограничение доступа; доступ решает allow-check в коде; юзер может вызвать /summary даже без меню.** Впереди T-240 (коммит feat(summary) + пуш) и T-241 (деплой) — @DevOps: на проде .env снять ограничение (ALLOWED_SUMMARY_IDS пусто / SUMMARY_ADMIN_ONLY=False), бэкап .env.bak.epic31, рестарт, лог «set_my_commands ok». ⚠️ ВНИМАНИЕ для DevOps: в staged-диффе .env.example НЕ должно быть GOODMORNING_TARGET_CHAT_IDS=-1002661910336 (повторное появление — red flag).**
> **Обновление:** 2026-08-17 — **Новый запрос пользователя (Шаг 0, @Memory, синхронизация контекста): 3 пункта про /summary.** (1) Команда сейчас реагирует только на владельца (другой юзер — тишина): нужно сделать доступной для всех + добавить в конфиг параметр-переключатель доступности (все/только админы); false = для всех. (2) У пользователя нет доступа к BotFather — выяснить (Architect проверит в интернете), можно ли кодом добавить /summary в список команд бота с описанием и сделать её доступной любому юзеру (контекст: setMyCommands/BotCommandScope). (3) При повторном вызове саммари во время таймаута бот должен отвечать рандомной фразой из пула: 2 канона («хули ты дрочишь, подожди {время}», «угомонись нахуй, не можешь {время} подождать?») + ~5 новых в том же стиле; внутри — реальное оставшееся время таймаута из конфига. **Находки кода (verified):** ограничение доступа — `handlers/summary.py::cmd_summary` (строки 234–239): `settings.ALLOWED_SUMMARY_IDS` (дефолт пусто = всем, R9/D62); на проде список из одного ID; таймаут — `services/summary_throttling.py::ThrottlingMiddleware` (router-scoped outer, handlers/summary.py:253), ключ (chat_id, user_id), TTL=`SUMMARY_THROTTLE_SECONDS` (дефолт 60.0, `_env_float`, НЕ time-format), повторный вызов = silent return (R8) с INFO-логом «remaining=…» — фраз для троттлинга НЕТ (есть только `_UX_ACK_VARIANTS` 20 ack-фраз, `_UX_NOT_READY`, `_UX_EMPTY`, `_UX_BUSY`); **`set_my_commands`/`BotCommand`/`BotCommandScope` в коде ОТСУТСТВУЮТ полностью** (grep 0 совпадений) — меню команд бота нигде не настраивается, команды ловятся только aiogram `Command()`-фильтрами; BotFather /setprivacy → Disable уже сделан вручную (Н1, Epic 24). Admin-паттерн — inline `message.from_user.id != settings.ADMIN_USER_ID` (ADMIN_USER_ID=5885953495). Тесты `tests/test_summary_throttling.py` (235 строк) ассертят silent drop — потребуют правок. Baseline: прод v2.28.0 (`714a4f6`), 1327 тестов, 14 роутеров, PID 939545. Граф: создана сущность «AdminBot Request 2026-08-17 Summary Access Throttle Phrases» (+связи), обновлены SummaryHandler/ThrottlingMiddleware_summary/AdminBot.
> **Обновление:** 2026-08-17 — **Epic 31 (/summary для всех + setMyCommands + таймаут-фразы, v2.29.0) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): DESIGN ✅.** @Architect добавил Section 40 (40.1–40.8) в ARCHITECTURE.md; @PM ранее: R31-1…R31-8, решения D94–D98 (Шаг 1 ✅). Ключевое: (40.1) **BotFather НЕ нужен** — `setMyCommands` полностью заменяет BotFather-меню; scope = видимость меню, НЕ ограничение доступа (доступ решает allow-check в коде); BotCommandScopeDefault = все диалоги/юзеры; aiogram `bot.set_my_commands(commands, scope=None, language_code=None) -> bool`, идемпотентно, вызывать в on_startup ДО start_polling; (40.2) allow-check D94 в cmd_summary (2 ветки: SUMMARY_ADMIN_ONLY → ALLOWED_SUMMARY_IDS, silent deny СОХРАНЁН); (40.3) НОВЫЙ services/bot_commands.py::setup_bot_commands (только /summary, описание «Саммари чата — прочитай, что ты пропустил, ленивец», BotCommandScopeDefault, best-effort, INFO «set_my_commands ok»); (40.4) пул _THROTTLE_PHRASES (7 фраз: 2 канона дословно + 5 новых) + format_remaining_seconds (ceil, плюрализация) + reply-ветка middleware (D98: event.reply, try/except, слот не сжигается); порядок роутеров 0a/0b НЕ меняется, middleware остаётся router-scoped, троттлинг ДО allow-check. Статусы: T-235 (@Builder, первая) → T-236/T-237 параллельно → T-238 (@Builder+@Reviewer) → T-239 (@Builder); T-240/T-241 — @DevOps. Код НЕ писался — передача @Builder. Baseline: прод v2.28.0 (`714a4f6`, PID 939545), 1327 тестов; target v2.29.0. Граф: созданы SUMMARY_ADMIN_ONLY, setup_bot_commands, _THROTTLE_PHRASES, format_remaining_seconds, setMyCommands (Telegram Bot API), ResearchFinding_40.1_setMyCommands; обновлены SummaryHandler (allow-check D94), ThrottlingMiddleware_summary (reply-фраза вместо тишины), bot.py (on_startup + setup_bot_commands), AdminBot (target v2.29.0), Epic31/Tasks/Decisions; связи Epic31 → includes → T-235…T-241 (конвенция; дубли contains_task удалены).
> **Обновление:** 2026-08-16 — **Epic 29 (UX-полировка: удаление команды, ack-вариации, промпт v4) — Шаг 6 (@Memory, граф знаний после реализации и ревью): IMPLEMENTED ✅. @Builder (T-222…T-224) завершил, @Reviewer (T-225) PASS: 1002/1002 тестов (995 baseline + 7 новых), 0 failed, 0 skipped, `git diff --check` чист. Реализовано: (T-222) handlers/summary.py — порядок `triggered → _delete_command → ack (random.choice(_UX_ACK_VARIANTS), 20 фраз, канон «ща гляну, подожди» первым) → generate_and_send`; best-effort delete не тронут; (T-223) SYSTEM_PROMPT v4 — пункт 3 (типографика) удалён, нумерация-зазор «1,2,4,5,6,7» (D84; ⚠️ СУПЕРСЕД D90, Epic 30), пункт 6 — канон пользователя ДОСЛОВНО (не откачен, D83), эталон backlog.md 1518–1539 (22 строки), слайс `lines[1517:1539]`, тест :59 новый ассерт «используй СТРОГО дословное значение из атрибута author»; **байт-в-байт ЗЕЛЁНЫЙ**; (T-224) доки — ARCHITECTURE 38.x + 4753/4749/3938, README:176 («расстрельная бригада переехала в бэкенд»), board.md статусы. Ревью: 0 blocking; non-blocking N2 (запись IMPLEMENTED в MEMORY.md) закрыта этим же Шагом 6; N4/N5 — опциональные. Изменено 9 файлов. **Коммита ещё нет.** Впереди T-226 (@DevOps): коммит на русском `feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)` — ВКЛЮЧАЯ канон пользователя (M services/summary_prompts.py), пуш, деплой: git pull → restart (~95с SIGTERM pre-existing) → верификация (0 traceback, порядок логов `triggered → command deleted → ack sent`; при WARNING delete — права `delete_messages`).**
> **Обновление:** 2026-08-17 — **Epic 29 (UX-полировка: удаление команды, ack-вариации, промпт v4) — Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): DEPLOYED ✅. Коммит `7160a33` «feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)» запушен в origin/master (9 файлов). Канон-правка пункта 6 пользователя вошла ДОСЛОВНО; Builder восстановил только номера пунктов 4/5/6/7 (зазор D84; ⚠️ СУПЕРСЕД D90, Epic 30 — нумерация станет 1–6) — текст канона НЕ тронут. Деплой на прод 198.46.175.136 (/var/www/admin_bot): git pull ff `ac80ce8..7160a33` (прод был на ac80ce8 — docs-коммит ccfad99 на проде не было, не критично); .env НЕ тронут; systemctl restart admin_bot → Active: running, новый PID 937634 (был 936542); 0 traceback; «Dimension mismatch» НЕТ (штатный WARNING автолечения остаётся); «SUMMARY_ALIASES invalid JSON» НЕТ; sqlite-vec dim=3072. Ручных /summary за окно наблюдения не было — порядок «command deleted → ack sent» (D81/D82) проверится на первом реальном вызове (не блокер). Тесты: 1002 passed. Ревью PASS. T-221…T-226 DONE. Известное неблокирующее: journalctl требует sudo для nik. **ЭПИК 29 ЗАКРЫТ: Epics 1–29 ALL DEPLOYED, прод v2.27.0 (7160a33, PID 937634). docs-коммит для MEMORY.md сделает Orchestrator отдельно (@Memory не коммитит).**
> **Обновление:** 2026-08-17 — **Новый запрос пользователя (Шаг 0, @Memory, синхронизация контекста):** в проекте появились 3 новые медиа-папки: `media/common/selfdev/` (selfdev_01.mp4), `media/common/work/` (work_01.mp4), `media/common/goodmorning/` (goodmorning_01/02.mp4) — все UNTRACKED в git. Задача: (1) создать три функции в сервисе common — selfdev и work (реакция на слова в чате, паттерн otboy/danger, роутер 4c), goodmorning (утренняя рассылка; нужен планировщик — прецедент APScheduler `services/summary_scheduler.py`, т.к. старый time-based scheduler удалён в Dead Page V2); (2) исправить нумерацию SYSTEM_PROMPT v4 — зазор «1,2,4,5,6,7» (D84 ранее запрещал) перенумеровать 4→3, 5→4, 6→5, 7→6 (инвариант байт-в-байт vs backlog.md 1518–1539 требует синхронного обновления эталона и тестов `test_summary_prompts.py`). Baseline: прод v2.27.0 (7160a33, PID 937634), 1002 теста. Контекст зафиксирован в графе знаний (сущности: AdminBot Request 2026-08-17 (Common Expansion), media/common/{selfdev,work,goodmorning}).
> **Обновление:** 2026-08-17 — **Epic 30 (Common Expansion, v2.28.0) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): DESIGN ✅. @Architect добавил Section 39 (39.1–39.11) в ARCHITECTURE.md; @PM: R30-1…R30-8, решения D85–D93. Ключевое: selfdev/work — +2 хендлера ВНУТРИ common_router (4c, порядок otboy → danger → selfdev → work → mimic, D91), НЕ репосты (гейт `forward_origin is None`, D92), reply+quote, SELFDEV/WORK_COOLDOWN=5m (time-format) + общий COMMON_COOLDOWN, списки в filters/word_lists.py (SELFDEV_WORDS 48 форм/17 фраз; WORK_WORDS ~128 форм/31 фраза, D85/D86); CommonRelay — обобщение пер-сабдир коулдаунов (generic-словарь + алиасы обратной совместимости для Epic 18-тестов, 39.5); goodmorning — БЕЗ роутера: GoodmorningRelay (plain-send, прецедент OlyaRelay) + GOODMORNING_CAPTIONS (3 канона дословно + 3 новых, D89) + GoodmorningSchedulerService (APScheduler, прецедент summary_scheduler; GOODMORNING_TIME=07:00, TZ=Asia/Yekaterinburg, TARGET_CHAT_IDS пусто=выключено, WARNING; audio/voice skip, D93). **D90 СУПЕРСЕД D84:** нумерация промпта перенумеровывается последовательно 1–6 (4→3, 5→4, 6→5, 7→6), текст пунктов дословно; эталон backlog 1518–1539 (22 строки) и слайс `lines[1517:1539]` НЕ сдвигаются — правки Epic 30 в backlog только ниже 1539; код+эталон+тесты — одним коммитом T-233. Статусы: T-227 (@Builder, в работе) → T-228 (←T-227), T-229/T-230 (параллельно) → T-231 (@Builder+@Reviewer) → T-232/T-233 (@Builder) → T-234 (@DevOps). Код НЕ писался — передача @Builder. Baseline: прод v2.27.0 (`7160a33`, PID 937634), 1002 теста; target v2.28.0. Граф: сущности Epic30_CommonExpansion, SelfdevWordFilter, WorkWordFilter, GoodmorningRelay, GoodmorningSchedulerService, goodmorning_captions, T-227…T-234, D85–D93; обновлены CommonRelay/common-service/handlers common.py/SYSTEM_PROMPT/word_lists.py/медиа-папки.**
> **Обновление:** 2026-08-17 — **Epic 30 (Common Expansion, v2.28.0) — Шаг 6 (@Memory, граф знаний после реализации и ревью): IMPLEMENTED ✅ + REVIEW APPROVED ✅. @Builder реализовал Epic 30 полностью: `filters/selfdev_word.py`, `filters/work_word.py`, `filters/word_lists.py` (SELFDEV_WORDS 48 / SELFDEV_PHRASES 17 / WORK_WORDS 128 / WORK_PHRASES 31), `handlers/common.py` (+selfdev_handler/work_handler, порядок **otboy→danger→selfdev→work→mimic**), `services/common_relay.py` (generic subdir-cooldown + алиасы `_danger_*`), `services/goodmorning_captions.py` (6 капций: 3 канона дословно + 3 новых), `services/goodmorning_relay.py` (plain-send), `services/goodmorning_scheduler.py` (APScheduler, `_parse_hhmm` fallback 07:00, start() False при пустых targets), `config/settings.py` (SELFDEV_COOLDOWN/WORK_COOLDOWN=5m, GOODMORNING_TIME/TZ/TARGET_CHAT_IDS/MEDIA_DIR), `bot.py` (wiring on_startup/on_shutdown, **порядок роутеров НЕ изменён**), `services/summary_prompts.py` (нумерация 1–6, текст пунктов дословно, D90), `.env.example`, `README.md` (v2.28.0), plans (backlog/board/ARCHITECTURE/MEMORY). Тесты: **1327 passed / 0 failed** (baseline 1002 → +325: test_selfdev_word.py 87, test_work_word.py 183, test_goodmorning.py 39, +16 test_common.py, обновлён test_summary_prompts.py). @Reviewer **APPROVED**: каноны капций байт-в-байт, текст промпта байт-в-байт, пересечения SELFDEV/WORK × DANGER/отбой = ∅, коулдауны двухслойные, репост-гейты, планировщики изолированы (у goodmorning свой AsyncIOScheduler), кодировки целы (cp1251-инцидент без последствий), `git diff --check` чист; 2 doc-правки ревьюера внесены (цифры тестов в README/board). **Инцидент (закрыт):** временная lossy-перекодировка `plans/backlog.md` через cp1251 при массовой правке чекбоксов PowerShell-скриптом — восстановлено биективно, байт-в-байт зелёный; **урок:** не использовать PowerShell-скрипты для массовых правок UTF-8 файлов планов. **Коммита ещё нет.** Впереди T-233 (коммит+пуш) и T-234 (деплой) — за @DevOps: на проде задать `GOODMORNING_TARGET_CHAT_IDS` (иначе рассылка выключена), `SELFDEV_COOLDOWN=5m`, `WORK_COOLDOWN=5m`; бэкап `.env`; верификация логов.**
> **Обновление:** 2026-08-17 — **Epic 30 (Common Expansion, v2.28.0) — Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): DEPLOYED ✅. ЭПИК 30 ЗАКРЫТ — полный цикл воркфлоу (0–8) завершён.** Коммит `714a4f617a7c3434b74a5aad8f7333c68665872c` «feat(common): Epic 30 — selfdev/work-реакции, goodmorning-рассылка и фикс нумерации промпта (v2.28.0)» запушен в origin/master: **30 файлов** (14 изменённых + 16 новых, включая **8 медиа-файлов** media/common/{selfdev,work,goodmorning}). Деплой на прод 198.46.175.136 (/var/www/admin_bot): git pull ff `7160a33..714a4f6`; **.env обновлён** (бэкап `.env.bak.epic30`): GOODMORNING_TIME=07:00, GOODMORNING_TZ=Asia/Yekaterinburg, GOODMORNING_TARGET_CHAT_IDS=-1002661910336 (рассылка ВКЛЮЧЕНА), SELFDEV_COOLDOWN=5m, WORK_COOLDOWN=5m; systemctl restart admin_bot → active (running), **новый PID 939545** (был 937634); логи: «Goodmorning scheduler started (07:00 Asia/Yekaterinburg, 1 chats)», «Bot started, listening for messages...», **0 traceback**. Наблюдение: старый процесс (PID 937634) ушёл в SIGKILL после 90с таймаута stop-sigterm (systemd, pre-existing не-блокер) — новый стартовал штатно (зафиксировано DevOps). Тесты: **1327 passed**. Ревью APPROVED. **T-227…T-234 ALL DONE. Прод = v2.28.0. Epics 1–30 ALL COMPLETE и DEPLOYED ✅.**
> **Обновление:** 2026-08-16 — **Epic 29 (UX-полировка: удаление команды, ack-вариации, промпт v4) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): DESIGN ✅. @Architect добавил Section 38 (38.1–38.7) в ARCHITECTURE.md: D81 — cmd_summary удаляет команду ДО ack (порядок: allow-check → generator-check → INFO triggered → _delete_command → ack из пула → generate_and_send; логи triggered → command deleted/failed → ack sent); D82 — `_UX_ACK` → `_UX_ACK_VARIANTS`, пул из 20 фраз, канон «ща гляну, подожди» первым, `random.choice`; промпт v4 (D83/D84) — пункт 3 (типографика) удалён (её чинит `cleanup_llm_text` 37.6), пункт 6 — канон пользователя ДОСЛОВНО (уже в дереве `M services/summary_prompts.py:18` — НЕ откатывать), нумерация-зазор «1,2,4,5,6,7» (**⚠️ D84 СУПЕРСЕД D90, Epic 30: перенумеровано 1–6**), эталон backlog 22 строки 1518–1539, слайс `lines[1517:1539]`, плейсхолдеры {max_symbols}/{username} без изменений. Доки: ARCHITECTURE (сделано Architect), MEMORY.md (ссылки v3→v4: 1518–1539; B1/B7), README.md:176, board.md. Статусы: T-221 DONE (@Architect), T-222…T-225 READY FOR BUILDER, T-226 PENDING (@DevOps). Код НЕ писался — передача @Builder. Baseline: прод v2.26.0 (`ac80ce8`, PID 936542), 995 тестов; target v2.27.0.**
> **Обновление:** 2026-08-16 — **Epic 28 (Качество памяти: векторы, репосты, алиасы, очистка) — Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): DEPLOYED ✅. Коммит `ac80ce8` «feat(summary): Epic 28 — качество памяти: репосты, алиасы, векторное автолечение и cleanup (v2.26.0)» запушен в origin/master (18 файлов: 2 новых — services/summary_cleanup.py, tests/test_summary_cleanup.py; 16 изменённых). Деплой на прод 198.46.175.136 (/var/www/admin_bot): git pull ff `1d7bed4..ac80ce8`; .env НЕ тронут; systemctl restart admin_bot → active (running), новый PID 936542 (был 934174); 0 traceback. Автолечение сработало ШТАТНО на первом старте: «EMBEDDING_DIM=768 != actual API dim=3072 — using actual»; «vec dimension mismatch (stored=768, actual=3072) — dropping smart_archive (facts in smart_archive_facts are kept)»; «sqlite-vec loaded (dim=3072)». smart_archive_facts сохранён. «Dimension mismatch» как ошибка отсутствует. WARNING «SUMMARY_ALIASES invalid JSON» отсутствует. Тесты: 995 passed (939 + 56). Ревью PASS. Все задачи T-211…T-220 DONE. Теперь новые сообщения векторизируются в 3072 корректно, репосты маркируются, алиасы резолвятся на лету, ответы LLM чистятся от ёлочек/тире. Вся цепочка воркфлоу (0–8) завершена.**
> **Обновление:** 2026-08-16 — **Epic 28 (Качество памяти: векторы, репосты, алиасы, очистка) — Шаг 6 (@Memory, граф знаний после реализации и ревью): IMPLEMENTED ✅. @Builder (T-211…T-219) завершил, @Reviewer PASS: 995/995 тестов (939 baseline + 56 новых), 0 failed, 0 skipped, `git diff --check` чист. Реализовано: миграция smart_messages (+is_forward/forward_source, ALTER + SELECT'ы); observer forward_origin (4 типа origin, алиасы для User, обрезка 100); XML-атрибуты is_forward/forward_source в конце тега + ре-резолв алиасов на лету; генератор (_resolve_author/_format_l2_quote/_most_active_author с алиасами + cleanup после generate до шиз-постфикса); _build_batch_text с репост-маркерами; векторное автолечение (probe → actual_dim, DROP smart_archive только при stored≠actual, факты целы, пустой KNN → FTS5, INSERT-mismatch → _vec_available=False); SYSTEM_PROMPT v3 (правила 6/7, байт-в-байт == backlog; с Epic 29 v4 — 1518–1539, 22 строки, хелпер lines[1517:1539]); services/summary_cleanup.py (6 пар замен). 4 non-blocking замечания ревью закрыты (board.md статусы, ARCHITECTURE «6 пар замен», WARNING при непарсируемом DDL, docstring row_get). Девиации: row_get() хелпер (sqlite3.Row без .get), .replace на строке 115 (сдвиг от импортов), 56 тестов вместо 58. Коммита ещё нет. Впереди T-220 (@DevOps): коммит на русском `feat(summary): Epic 28 — … (v2.26.0)`, 12–13 файлов + деплой (git pull, restart, проверка логов: нет Dimension mismatch, алиасы работают, DROP smart_archive 768→3072 выполнится один раз — ожидаемо; прод .env править НЕ нужно).**
> **Обновление:** 2026-08-16 — **Epic 28 (Качество памяти: векторы, репосты, алиасы, очистка) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): DESIGN ✅. @Architect добавил Section 37 (37.1–37.10) в ARCHITECTURE.md. Ключевое: миграция smart_messages (+is_forward/forward_source, ALTER в initialize() с try/except OperationalError, прецедент dead_page_posts); forward-маркировка observer→XML→L2→L3 (_extract_forward_source по 4 типам origin, обрезка 100 симв., getattr-защита); ре-резолв алиасов на лету ВСЕГДА (aliases.resolve(user_id, author_name or None, None)); векторное автолечение (probe embed → actual_dim, DDL-разбор → stored_dim, DROP smart_archive ТОЛЬКО при несовпадении, smart_archive_facts сохраняется, self._vec_dim, рантайм-mismatch → _vec_available=False, пустой KNN → FTS5); SYSTEM_PROMPT v3 — правила 6 (алиас дословно, без алиаса — свобода + креативная интерпретация ника) и 7 (is_forward=\"true\" → содержание принадлежит forward_source), 23 строки (v3), эталон backlog **1518–1539** (с Epic 29 v4 — 22 строки), хелпер lines[1517:1539], плейсхолдеры {max_symbols} ×1, {username} ×2 без изменений; новый модуль services/summary_cleanup.py (REPLACEMENTS «»→\", „“→\", —→-, –→-), cleanup_llm_text после generate ДО _ensure_shiz_postfix. Решения D76–D80. **SYSTEM_PROMPT с Epic 28 — v3 (R11 v3); COMPRESS_PROMPT/EXTRACT_PROMPT остаются заморожены.** Статусы: T-211…T-215/T-217/T-219 READY FOR BUILDER (T-212…T-215, T-218 — параллельно), T-216/T-220 PENDING. Прод .env править НЕ нужно (опционально EMBEDDING_DIM=3072). Код НЕ писался — передача @Builder.**
> **Обновление:** 2026-08-16 — **Epic 27 (новый системный промпт + SUMMARY_ALIASES на прод) — Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): DEPLOYED ✅. Коммит `1d7bed4` «feat(summary): Epic 27 — новый системный промпт бота-абьюзера v2 и SUMMARY_ALIASES (v2.25.0)» запушен в origin/master (8 файлов). Деплой на прод nik@198.46.175.136 (/var/www/admin_bot): git pull ff `7c7c241..1d7bed4`; в .env добавлена SUMMARY_ALIASES (36 пар, бэкап .env.bak.epic27, верифицировано python3: JSON OK, sha1 совпал с репо); systemctl restart admin_bot → active (running), новый PID 934174 (был 926618); 0 traceback; WARNING «SUMMARY_ALIASES invalid JSON» отсутствует → AliasResolver распарсил 36 пар. Тесты: 939 passed. Ревью PASS. SYSTEM_PROMPT v2 байт-в-байт == backlog 1518–1538 (с Epic 29 эталон v4 — 1518–1539), плейсхолдеры {max_symbols} ×1, {username} ×2, подстановка .replace не тронута, COMPRESS/EXTRACT заморожены. Pre-existing не-блокер (не Epic 27): WARNING «SmartModule L3: vector search failed — FTS5 fallback» + OperationalError Dimension mismatch 3072 vs 768 (старые эмбеддинги) — FTS5-фоллбек сработал штатно; рекомендован отдельный тикет на миграцию векторов. Вся цепочка воркфлоу (0–8) завершена.**
> **Обновление:** 2026-08-16 — **Epic 27 (новый системный промпт + SUMMARY_ALIASES на прод) — Шаг 6 (@Memory, граф знаний после реализации и ревью): IMPLEMENTED ✅. @Builder (T-207/T-208) завершил, @Reviewer PASS: 939/939 тестов (полный прогон; точечно 50). SYSTEM_PROMPT v2 в services/summary_prompts.py (строки 8–28, 21 строка) байт-в-байт == эталон backlog.md 1518–1538 (с Epic 29 эталон v4 — 1518–1539); {max_symbols} ×1, {username} ×2; подстановка .replace в summary_generator.py:113 НЕ тронута; COMPRESS_PROMPT/EXTRACT_PROMPT не изменены. Тест test_max_symbols_is_the_only_placeholder переписан по D72 (regex `\{(\w+)\}` → set {max_symbols, username}); хелпер lines[1517:1538]. Доки: README (+ироничный блок «Промпт v2»), ARCHITECTURE.md Section 36 (4298–4360), MEMORY.md (строки 109/241/258/751), board/backlog T-207/T-208 done. Изменено ровно 8 файлов (.env.example с SUMMARY_ALIASES 36 пар — валидный JSON). Коммита ещё нет. Впереди: T-210 (коммит `feat(summary): Epic 27 … (v2.25.0)` + пуш) и T-209 (деплой .env.bak.epic27 + SUMMARY_ALIASES → прод .env, git pull, restart ~95с SIGTERM — штат, верификация).**
> **Обновление:** 2026-08-16 — **Epic 27 (новый системный промпт + SUMMARY_ALIASES на прод) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): DESIGN ✅. @Architect добавил Section 36 (36.1–36.8) в ARCHITECTURE.md: C1 (эталон промпта ТОЛЬКО в backlog.md 1518–1538, без дублей; с Epic 29 эталон v4 — 1518–1539), C2 (подстановка `SYSTEM_PROMPT.replace("{max_symbols}", …)` в summary_generator.py:113 НЕ меняется — `str.format` упал бы KeyError на `{username}`), C3–C5; тест-план 36.4 — меняются ТОЛЬКО хелпер `_backlog_system_prompt` (слайс 1517:1538) и `test_max_symbols_is_the_only_placeholder` (набор `{"max_symbols","username"}` по D72); деплой 36.6 — `.env.bak.epic27`, SUMMARY_ALIASES в одинарных кавычках с grep-гардом от дублей, git pull, restart (~95с SIGTERM), верификация. **SYSTEM_PROMPT с Epic 27 больше НЕ заморожен (R11 v2); COMPRESS_PROMPT/EXTRACT_PROMPT остаются заморожены.** Статусы: T-207/T-208 READY FOR BUILDER, T-209/T-210 PENDING (@DevOps). Код НЕ писался — передача @Builder (T-207/T-208).**
> **Обновление:** 2026-08-16 — **Epic 26 (GraphRAG-память) — Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): DEPLOYED ✅. Коммит `7c7c241` «feat(graphrag): Epic 26 — граф знаний nodes/edges, entity extraction и гибридный поиск /summary (v2.24.0)» запушен в origin/master (github.com/Henry-Case-dev/adminbot.git). Деплой на прод nik@198.46.175.136 (/var/www/admin_bot): git pull fast-forward `c364f18..7c7c241`; .env +GRAPH_RAG_ENABLED=True, GRAPH_EDGE_WEIGHT_INCREMENT=1, GRAPH_TOP_EDGES_LIMIT=5, GRAPH_EXTRACT_MAX_TRIPLETS=50 (бэкап .env.bak.epic26); systemctl restart admin_bot → active (running), Main PID 926618; таблицы nodes/edges созданы в продовой БД; 0 traceback. Тесты: 939 passed (860 baseline + 73 Epic 26 + 6 T-206); T-206 (P1, FTS-удаление медиа без подписи) исправлен в этом же релизе. Известный не-блокер: бот не отвечает на SIGTERM (~95с рестарт, pre-existing) — рекомендуется отдельный тикет graceful shutdown. Вся цепочка воркфлоу (0–8) завершена.**
> **Обновление:** 2026-08-16 — **Epic 26 (GraphRAG-память) — Шаг 6 (@Memory, граф знаний после реализации и ревью): T-200–T-204 IMPLEMENTED (@Builder), ревью дважды PASS, 939 тестов (860 baseline + 73 Epic 26 + 6 T-206), T-206 (P1, FTS-DELETE рассинхронизация) fixed, ARCHITECTURE.md 35.4 (JSON-объект-обёртка) зафиксирована. Код в рабочем дереве БЕЗ коммита. Осталось: T-205 (README+коммит+пуш+деплой) → @Builder+@DevOps.**
> **Обновление:** 2026-08-16 — **Epic 26 (GraphRAG-память) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): Section 35 (35.1–35.11) спроектирована @Architect (T-199/T26.0): DDL nodes/edges (chat_id + UNIQUE), EXTRACT_PROMPT дословно (35.3), flow extract→graph→delete в compress_and_purge (D68), graph traversal для /summary с тегом <historical_graph_facts> первым в user-промпте (D71), настройки GRAPH_* (D69), тест-план 35.8. Статус: DESIGN — ждёт PM-аппрув (T26.0-D); после аппрува T26.1…T26.4 → READY FOR BUILDER. Код НЕ писался.**
> **Обновление:** 2026-08-16 — **Epic 25 (багфикс /summary) — Шаг 8 (@Memory, ФИНАЛЬНАЯ синхронизация): T-197 DONE (коммит `c364f18`, 11 файлов, +1001/−84; docs `2a45f79`; пуш `818e195..c364f18`; 860 passed; .env не тронут) + T-198 DONE (прод 198.46.175.136: git pull ff `a68732c..c364f18`, .env не меняли, restart → active (running) PID 923954, старт чистый). Epic 25 DEPLOYED. Осталось вручную пользователю: живой тест /summary; Н1 BotFather /setprivacy → Disable; при WARNING удаления — админ-права delete_messages.**
> **Обновление:** 2026-08-16 — **Epic 25 (багфикс /summary) — Шаг 6 (@Memory, граф знаний после реализации и ревью): T-194/T-195 IMPLEMENTED (@Builder, B1–B9 в summary_throttling.py / summary_generator.py / handlers/summary.py), T-196 REVIEW APPROVED (@Reviewer, 860 тестов подтверждены лично, 4 Low-замечания не блокируют). Тесты: 860 PASS (835+25), 0 регрессий. Осталось: T-197 (коммит+пуш) и T-198 (деплой+верификация) → @DevOps.**
> **Обновление:** 2026-08-16 — **Epic 25 (багфикс /summary) — Шаг 3 (@Memory, граф знаний после фазы архитектуры): RCA ПОДТВЕРЖДЁН прод-логами (асимметрия ThrottlingMiddleware vs aiogram Command-фильтр), Section 34 (B1–B9) DESIGN APPROVED (PM: B6 ⚠️, B3 ⚠️). T-192/T-193 Done, T-194/T-195 READY FOR BUILDER.**
> **Обновление:** 2026-08-16 — **Epic 25 (багфикс /summary) — Шаг 0 (@Memory, синхронизация контекста по баг-репорту): «/summary не реагирует» + требование удалять сообщение команды из чата.**
> **Обновление:** 2026-08-16 — **Epic 24 «SmartModule: Summary» — Шаг 8 (@Memory, финальная синхронизация): ВЕСЬ запрос пользователя выполнен ✅. T-190 DONE (835 тестов PASS локально; коммит `a68732c`, 35 файлов, +4495/−28; docs-коммит `818e195`; пуш master; HEAD = origin/master). T-191 DONE (прод 198.46.175.136: git pull ff `756d237..a68732c`, .env +LLM-ключи, venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1, smoke T-191-D ✅ apinet.cloud/v1/models OK, restart → active (running) PID 920105). Осталось пользователю вручную: Н1 BotFather `/setprivacy` → Disable (критично) + живая проверка `/summary`.**
> **Статус:** Epics 1–30 ALL COMPLETE и DEPLOYED ✅ (v2.28.0, `714a4f6`, 1327 тестов, PID 939545, goodmorning ВКЛЮЧЕНА для чата -1002661910336). **Epic 30 «Common Expansion — selfdev/work-реакции, goodmorning-рассылка, фикс нумерации промпта» (v2.28.0): Шаг 1 (PM: R30-1…R30-8, D85–D93) ✅ → Шаг 2 (@Architect, Section 39) ✅ → Шаг 3 (@Memory, DESIGN) ✅ → Шаги 4–5: @Builder (T-227…T-230, T-232) ✅ + @Reviewer (T-231) APPROVED ✅ → Шаг 6 (@Memory): IMPLEMENTED ✅ → Шаг 7: @DevOps (T-233 коммит `714a4f6`+пуш, T-234 деплой) ✅ → **Шаг 8 (@Memory): DEPLOYED ✅. ЭПИК 30 ЗАКРЫТ — цикл воркфлоу (0–8) завершён.** 1327/1327 тестов (1002 + 325 новых), 0 failed. **T-227…T-234 ALL DONE.**** Ручные действия пользователя: живой тест `/summary` в чате (порядок «command deleted → ack sent» проверится на первом реальном вызове — не блокер), Н1 (BotFather `/setprivacy` → Disable), при WARNING удаления — выдать боту админ-права `delete_messages`.
> **Текущий коммит:** `714a4f6` (feat(common): Epic 30 — selfdev/work-реакции, goodmorning-рассылка и фикс нумерации промпта (v2.28.0)) — в origin/master (github.com/Henry-Case-dev/adminbot.git). Прод версия **v2.28.0** (PID 939545). **Epic 30 DEPLOYED (T-227…T-234 All Done, 1327 тестов, ревью APPROVED; 30 файлов в коммите: 14 изменённых + 16 новых, включая 8 медиа). Epics 1–30 ALL COMPLETE и DEPLOYED.**
> **Сервер:** 198.46.175.136:/var/www/admin_bot, systemctl active (running), PID 939545 (был 937634), 0 traceback после рестарта; git pull ff `7160a33..714a4f6`; .env обновлён (бэкап `.env.bak.epic30`): GOODMORNING_TIME=07:00, GOODMORNING_TZ=Asia/Yekaterinburg, GOODMORNING_TARGET_CHAT_IDS=-1002661910336, SELFDEV_COOLDOWN=5m, WORK_COOLDOWN=5m. Логи: «Goodmorning scheduler started (07:00 Asia/Yekaterinburg, 1 chats)», «Bot started, listening for messages...». sqlite-vec dim=3072. Известные не-блокеры (pre-existing): бот не отвечает на SIGTERM (~95с рестарт; старый PID 937634 ушёл в SIGKILL после 90с таймаута stop-sigterm — штатно), journalctl требует sudo для nik.
> **Epic 31 (v2.29.0, Шаг 6 @Memory, 2026-08-17): IMPLEMENTED + REVIEW APPROVED — 1366 тестов passed / 0 failed (1327 + 39). T-235…T-239 DONE; T-240 (коммит+пуш) / T-241 (деплой) — PENDING @DevOps.** ⚠️ DevOps: в staged-диффе `.env.example` НЕ должно быть `GOODMORNING_TARGET_CHAT_IDS=-1002661910336` (red flag). На проде для T-241: ALLOWED_SUMMARY_IDS пусто + SUMMARY_ADMIN_ONLY=False, бэкап `.env.bak.epic31`, рестарт, лог «set_my_commands ok». Прод пока v2.28.0 (`714a4f6`, PID 939545).

---

## 🚧 Epic 31: /summary для всех + setMyCommands + таймаут-фразы — v2.29.0 (IMPLEMENTED + REVIEW APPROVED, Шаг 6 @Memory, 2026-08-17)

> **Статус:** Шаг 0 (@Memory, sync) ✅ → Шаг 1 (PM: R31-1…R31-8, D94–D98) ✅ → Шаг 2 (@Architect, Section 40.1–40.8) ✅ → Шаг 3 (@Memory, DESIGN) ✅ → Шаги 4–5: @Builder (T-235 → T-236/T-237 параллельно → T-238 → T-239) ✅ + @Reviewer (T-238-E) **APPROVED** ✅ → **Шаг 6 (@Memory, IMPLEMENTED) ✅** → Шаг 7: @DevOps (T-240 коммит+пуш, T-241 деплой) — ВПЕРЕДИ. Тесты: **1366 passed / 0 failed** (baseline 1327 → +39).
> **Требования R31-1…R31-8, решения D94–D98, риски 1–8:** `plans/backlog.md` (Epic 31, строки 2570–2689, ниже эталона R11 1518–1539). **Дизайн:** `plans/ARCHITECTURE.md` Section 40 (40.1–40.8). **Target:** v2.29.0. **Baseline:** прод v2.28.0 (`714a4f6`), 1327 тестов, 14 роутеров (0a/0b summary). **Коммита ещё нет — всё в рабочем дереве.**

### 📐 Дизайн (Section 40, @Architect, 2026-08-17)

| Блок | Суть |
|---|---|
| **40.1 (исследование)** | **BotFather НЕ нужен** — setMyCommands полностью заменяет BotFather-меню; scope = видимость меню, НЕ ограничение доступа (backend обязан сам валидировать — allow-check D94); BotCommandScopeDefault = все диалоги/юзеры; aiogram `bot.set_my_commands(commands, scope=None, language_code=None) -> bool`, идемпотентно (перезапись списка), вызывать в on_startup ДО start_polling; deleteMyCommands существует (не используется); setChatMenuButton — вне скоупа. Стек исследования: exa (context7 API-key недоступен) |
| **40.2 (R31-1, D94)** | allow-check в cmd_summary (handlers/summary.py:234-239): 2 ветки — SUMMARY_ADMIN_ONLY → ALLOWED_SUMMARY_IDS; denied — silent absorb СОХРАНЁН (R9/D62/B8); user_id==0 → denied при admin_only; docstring модуля обновить; обратная совместимость (дефолт False = старое поведение байт-в-байт, тесты живы) |
| **40.3 (R31-2, D95)** | НОВЫЙ `services/bot_commands.py`: `_COMMANDS` (только /summary, описание «Саммари чата — прочитай, что ты пропустил, ленивец»), `setup_bot_commands(bot) -> bool`, BotCommandScopeDefault, language_code НЕ задаём, best-effort try/except, INFO «set_my_commands ok»; вызов в bot.py on_startup после SmartModule-блока ДО start_polling; /deadpage//alangreet в меню НЕ выносим |
| **40.4 (R31-3, D96/D97/D98)** | `_THROTTLE_PHRASES` (7: 2 канона дословно + 5 новых, плейсхолдер {remaining}) + `_pluralize` + `format_remaining_seconds` (ceil, «N секунд/минут») в services/summary_throttling.py; middleware-ветка: random.choice → event.reply(phrase) (bot через message._bot/data["bot"]), try/except → WARNING, return всегда, слот не сжигается повторно, конструктор не меняется, INFO-лог «throttled … remaining=» сохранён |
| **40.5 (T-235-A)** | `SUMMARY_ADMIN_ONLY: bool = _env_bool("SUMMARY_ADMIN_ONLY", False)` после ALLOWED_SUMMARY_IDS (settings.py:244) + .env.example с комментарием |
| **40.6 (T-238, R31-4)** | test_summary_throttling.py (silent→reply), test_summary_handlers.py (4 комбинации allow-check), test_bot_commands.py НОВЫЙ, юниты форматтера; полный pytest 1327 baseline + новые, 0 регрессий; git diff --check; ревью @Reviewer (T-238-E) |
| **40.7/40.8** | Риски 1–8 (перезапись BotFather-меню — ожидаемо по D95; групповая приватность — это ТЗ R31-1; двойные ответы исключены — одна middleware-ветка); файлы: 2 новых (bot_commands.py + тест) + 11 изменяемых; НЕ менять: порядок роутеров, attach middleware (summary.py:253), конструктор ThrottlingMiddleware, формат INFO-лога, B9-гейт наблюдателя |

### 🧠 Граф знаний (Шаг 3 @Memory, 2026-08-17)

- **Созданы сущности:** SUMMARY_ADMIN_ONLY (ConfigSetting), setup_bot_commands (ServiceFunction), _THROTTLE_PHRASES (Constant), format_remaining_seconds (HelperFunction), setMyCommands (Telegram Bot API) (ExternalAPI), ResearchFinding_40.1_setMyCommands.
- **Обновлены наблюдения:** SummaryHandler (allow-check D94, 2 ветки, silent deny сохранён), ThrottlingMiddleware_summary (reply-фраза из пула вместо тишины, D98), bot.py (on_startup + setup_bot_commands ДО polling), AdminBot (target v2.29.0), Epic31_SummaryAccess_v2.29.0 (DESIGN, Section 40, ограничения), AdminBot Request (Шаги 0–3 ✅, ответ на п.2: BotFather не нужен), Decision_D95 (aiogram-сигнатура), Decision_D98 (event.reply через message._bot), Task_T235…T-241 (ссылки на секции 40.2–40.6).
- **Связи:** Epic31 → includes → T-235…T-241 (конвенция `includes` как Epic 30; дубли contains_task удалены); Epic31 → modifies → SummaryHandler/ThrottlingMiddleware_summary/bot.py; Epic31 → has_research → ResearchFinding_40.1; ResearchFinding → informs → D95; setup_bot_commands → calls → setMyCommands (Telegram Bot API); bot.py → calls → setup_bot_commands; ThrottlingMiddleware_summary → uses → _THROTTLE_PHRASES и format_remaining_seconds; _THROTTLE_PHRASES → uses → format_remaining_seconds; SummaryHandler → uses → SUMMARY_ADMIN_ONLY; Task_T235 → implements → SUMMARY_ADMIN_ONLY; Task_T236 → creates → setup_bot_commands; Task_T237 → modifies → ThrottlingMiddleware_summary.

### ✅ Реализация (Шаг 6 @Memory, 2026-08-17)

| Компонент | Что сделано |
|---|---|
| **config/settings.py** | `SUMMARY_ADMIN_ONLY: bool = _env_bool("SUMMARY_ADMIN_ONLY", False)` |
| **handlers/summary.py** | allow-check D94: 2 ветки — SUMMARY_ADMIN_ONLY → ALLOWED_SUMMARY_IDS; silent deny СОХРАНЁН (R9/D62/B8) |
| **services/bot_commands.py** | НОВЫЙ: `setup_bot_commands(bot) -> bool`, `BotCommand("summary", «Саммари чата — прочитай, что ты пропустил, ленивец»)`, `BotCommandScopeDefault`, try/except → bool, INFO «set_my_commands ok» |
| **bot.py** | вызов setup_bot_commands в on_startup ДО start_polling; **порядок роутеров НЕ тронут** |
| **services/summary_throttling.py** | `_THROTTLE_PHRASES` 7 фраз (2 канона дословно + 5 новых); `format_remaining_seconds` + `_pluralize`; throttled-ветка: `random.choice` + `.format(remaining=...)` + `event.reply` best-effort; слот не перезаписывается; **конструктор не менялся** |
| **.env.example** | SUMMARY_ADMIN_ONLY=False (продовой chat_id убран — фикс ревью) |
| **README.md** | v2.29.0, 1366 тестов, меню команд, таймаут-фразы, SUMMARY_ADMIN_ONLY |
| **Тесты** | tests/test_bot_commands.py (новый); test_summary_throttling.py (silent→reply); test_summary_handlers.py (комбинации D94). **1366 passed / 0 failed (baseline 1327 → +39)** |

### 🔎 Ревью (T-238-E, @Reviewer, APPROVED, 2026-08-17)

1. **Critical:** утечка продового chat_id в `.env.example` (`GOODMORNING_TARGET_CHAT_IDS=-1002661910336`) — откат на пустое значение ✅
2. **Minor:** README — явное упоминание перезаписи меню setMyCommands ✅
3. **Minor:** риск 9 в ARCHITECTURE 40.7 — denied-юзер при спаме получает фразу-отборку (троттлинг ДО allow-check) ✅
4. **Minor:** board.md синхронизирован (T-235…T-239 → In Review/APPROVED) ✅

### 🧠 Граф знаний (Шаг 6 @Memory, 2026-08-17)

- **Обновлены:** Epic31_SummaryAccess_v2.29.0 (IMPLEMENTED & REVIEW APPROVED, 1366 тестов, урок про chat_id), Task_T235…T-239 (DONE), Task_T240/T-241 (PENDING @DevOps + red flag про staged-diff), AdminBot (Epic 31 IMPLEMENTED, факт BotFather не нужен), AdminBot Request (все 3 пункта реализованы), SummaryHandler (D94 IMPLEMENTED), ThrottlingMiddleware_summary (reply-ветка IMPLEMENTED), setup_bot_commands (IMPLEMENTED), SUMMARY_ADMIN_ONLY (IMPLEMENTED), _THROTTLE_PHRASES (IMPLEMENTED), format_remaining_seconds (IMPLEMENTED), ResearchFinding_40.1_setMyCommands (ПОДТВЕРЖДЕНО).
- **Создана сущность-урок:** `Lesson_env_example_chatid_leak` — продовые секреты/ID не должны попадать в .env.example; перед коммитом проверять staged-diff; связь `warns` → T-240/T-241.
- **Ключевой исследовательский факт:** BotFather НЕ нужен — setMyCommands из кода полностью заменяет BotFather-меню; scope = видимость меню (подсказка), НЕ ограничение доступа; реальный доступ решает allow-check в коде; юзер может вызвать /summary даже без меню.

### 📤 Впереди (Шаг 7, @DevOps)

- **T-240:** коммит `feat(summary): Epic 31 — /summary для всех, setMyCommands и таймаут-фразы (v2.29.0)` + пуш origin/master. ⚠️ В staged-диффе `.env.example` НЕ должно быть `GOODMORNING_TARGET_CHAT_IDS=-1002661910336` (повторное появление — red flag, фикс ревью не вошёл). .env не коммитим (R31-6).
- **T-241:** деплой — прод .env: `ALLOWED_SUMMARY_IDS=` пусто / `SUMMARY_ADMIN_ONLY=False` (бэкап `.env.bak.epic31`), git pull, restart, лог «set_my_commands ok», 0 traceback, живой тест /summary от НЕ-владельца.

## ✅ Epic 30: Common Expansion — selfdev/work-реакции, goodmorning-рассылка, фикс нумерации промпта — v2.28.0 (DEPLOYED, Шаг 8 @Memory, 2026-08-17)

> **Статус:** Шаг 1 (PM: R30-1…R30-8, D85–D93) ✅ → Шаг 2 (@Architect, Section 39.1–39.11) ✅ → Шаг 3 (@Memory, DESIGN) ✅ → Шаги 4–5: @Builder (T-227…T-230, T-232) ✅ + @Reviewer (T-231) **APPROVED** ✅ → Шаг 6 (@Memory, IMPLEMENTED) ✅ → Шаг 7: @DevOps (T-233 коммит `714a4f6`+пуш, T-234 деплой) ✅ → **Шаг 8 (@Memory, DEPLOYED) ✅. ЭПИК 30 ЗАКРЫТ — цикл воркфлоу (0–8) завершён. Прод v2.28.0 (`714a4f6`, PID 939545, goodmorning ВКЛЮЧЕНА для -1002661910336). 1327/1327 тестов, 0 failed.**
> **Требования R30-1…R30-8, решения D85–D93:** `plans/backlog.md` (Epic 30, строки 2423–2567). **Дизайн:** `plans/ARCHITECTURE.md` Section 39 (39.1–39.11).
> **⚠️ D90 СУПЕРСЕД D84:** нумерация SYSTEM_PROMPT v4 перенумеровывается последовательно 1–6 (4→3, 5→4, 6→5, 7→6); все записи ниже о «зазоре-нумерации» (Epic 29, D84) — УСТАРЕЛИ в части нумерации.

### 📐 Дизайн (Section 39, @Architect, 2026-08-17)

| Блок | Суть |
|---|---|
| **39.2/39.3 (T-227/T-228, D85/D86/D92)** | Списки в `filters/word_lists.py` (единый источник; env-оверрайда НЕТ): SELFDEV_WORDS 48 форм + SELFDEV_PHRASES 17 фраз; WORK_WORDS ~128 форм + WORK_PHRASES 31 фраза («ё»-формы дословно; «развиваться» НЕ включать). Новые фильтры `filters/selfdev_word.py` / `filters/work_word.py` (НЕ параметризация DangerWordFilter): кириллические границы, IGNORECASE, фразы ПЕРВЫМИ, text+caption, **гейт `forward_origin is None` (D92)**; возврат `{"matched_word"}` (исходный регистр — для quote) |
| **39.4 (D91)** | +2 хендлера ВНУТРИ `common_router` (4c): порядок **otboy → danger → selfdev → work → mimic**; паттерн otboy/danger (relay-None guard, try/except, `return UNHANDLED`); порядок РОУТЕРОВ bot.py НЕ меняется; goodmorning — БЕЗ роутера |
| **39.5 (D87)** | CommonRelay: обобщение пер-сабдир коулдаунов — generic `_subdir_cooldown_seconds` {danger,selfdev,work}; Layer 1 (сабдир) ПЕРЕД Layer 2 (shared COMMON_COOLDOWN); алиасы `_danger_cooldown_seconds`/`_danger_cooldowns` сохраняют Epic 18-тесты; сабдиры независимы; otboy — только shared |
| **39.6 (R30-3, D88/D89/D93)** | goodmorning: `services/goodmorning_captions.py` (пул 3 канона дословно + 3 новые, стиль-гард ❗️❗️❗️/CAPS/без мата) + `services/goodmorning_relay.py` (plain-send БЕЗ reply/quote, прецедент OlyaRelay; audio/voice — skip с WARNING; `goodmorning_05_gif.MP4` → animation) + `services/goodmorning_scheduler.py` (APScheduler: CronTrigger HH:MM+tz, MemoryJobStore, max_instances=1, coalesce=True; `_parse_hhmm` fallback 07:00; start() только при непустых TARGET_CHAT_IDS, иначе WARNING; start() ДО dp.start_polling; shutdown() в on_shutdown) |
| **39.7 (D88)** | Конфиг: `SELFDEV_COOLDOWN=5m`, `WORK_COOLDOWN=5m` (`_env_duration`); `GOODMORNING_TIME=07:00`, `GOODMORNING_TZ=Asia/Yekaterinburg`, `GOODMORNING_TARGET_CHAT_IDS=()` (пусто=выключено), `GOODMORNING_MEDIA_DIR=media/common/goodmorning` |
| **39.8 (R30-4, D90)** | **D90 СУПЕРСЕД D84:** нумерация SYSTEM_PROMPT v4 → 1–6 (4→3, 5→4, 6→5, 7→6), текст пунктов дословно; эталон backlog R11 1518–1539 (22 строки) и слайс `lines[1517:1539]` НЕ меняются; правки Epic 30 в backlog — только ниже 1539; `test_numbering_gap_4_5` → `test_numbering_sequential`; ассерты «6./7.» → «5./6.»; код+эталон+тесты — одним коммитом T-233; COMPRESS/EXTRACT заморожены |
| **39.9 (T-231, R30-5)** | Тест-план: `tests/test_selfdev_word.py`, `tests/test_work_word.py`, `tests/test_goodmorning.py` (НОВЫЕ), `tests/test_common.py` (расширение), `tests/test_summary_prompts.py`; полный pytest 1002 + новые, 0 регрессий; пересечения списков с DANGER/WAR/otboy — юнит-тест + дубль @Reviewer |
| **39.11** | Новые файлы: filters/selfdev_word.py, filters/work_word.py, services/goodmorning_captions.py, services/goodmorning_relay.py, services/goodmorning_scheduler.py, 3 тест-файла. Медиа-папки selfdev/work/goodmorning — в коммит T-233 (политика media/, НЕ .gitignore) |

### 📋 Задачи (T-227…T-234, статусы Шага 8 @Memory)

- **T-227** @Builder (P0) — selfdev (R30-1, D85/D87/D91/D92) → **DONE** (Шаг 6: filters/selfdev_word.py, SELFDEV_WORDS 48/фраз 17, 87 тестов)
- **T-228** @Builder (P0, ←T-227) — work (R30-2, D86) → **DONE** (Шаг 6: filters/work_word.py, WORK_WORDS 128/фраз 31, 183 теста)
- **T-229** @Builder (P0, параллельно) — goodmorning-рассылка (R30-3, D88/D89/D93) → **DONE** (Шаг 6: captions/relay/scheduler, 39 тестов)
- **T-230** @Builder (P1, параллельно) — фикс нумерации промпта (R30-4, D90) → **DONE** (Шаг 6: нумерация 1–6, байт-в-байт зелёный)
- **T-231** @Builder+@Reviewer (P0, ←T-227…T-230) — тесты + полный прогон + проверка конфликтов (R30-5) → **DONE** (Шаг 6: ревью APPROVED, 1327 passed / 0 failed)
- **T-232** @Builder (P1, ←T-227…T-230) — README + .env.example (R30-6) → **DONE** (Шаг 6: README v2.28.0, конфиг-таблица, changelog)
- **T-233** @Builder (P0, ←T-231/T-232) — коммит (включая медиа-папки) + пуш (R30-7) → **DONE** (Шаг 7/8: коммит `714a4f6` на master, 30 файлов (14 изменённых + 16 новых, 8 медиа), пуш origin/master `26268e5..714a4f6`)
- **T-234** @DevOps (P0, ←T-233) — деплой на прод (R30-8) → **DONE** (Шаг 7/8: git pull ff `7160a33..714a4f6`, .env обновлён (бэкап `.env.bak.epic30`: GOODMORNING_* + SELFDEV/WORK_COOLDOWN), restart → PID 939545, «Goodmorning scheduler started (07:00 Asia/Yekaterinburg, 1 chats)», 0 traceback)

### 🧠 Граф знаний (Шаг 3 @Memory, 2026-08-17)

- **Созданы сущности:** Epic30_CommonExpansion, SelfdevWordFilter, WorkWordFilter, GoodmorningRelay, GoodmorningSchedulerService, goodmorning_captions, T-227…T-234 (8 задач), D85–D93 (9 решений PM).
- **Обновлены наблюдения:** CommonRelay (обобщение subdir-cooldown 39.5 + алиасы обратной совместимости), common-service (=common_router: 5 хендлеров otboy→danger→selfdev→work→mimic), handlers/common.py, SYSTEM_PROMPT (D90 суперсед D84), word_lists.py (+4 списка), media/common/{selfdev,work,goodmorning} (состав, коммит T-233), AdminBot Request 2026-08-17 (статус Epic 30).
- **Связи:** Epic30 → includes → T-227…T-234 и D85–D93; Epic30 → modifies → SYSTEM_PROMPT/CommonRelay/word_lists.py; Selfdev/WorkWordFilter → imports_from → word_lists.py; Selfdev/WorkWordFilter → feeds_into → common-service; GoodmorningSchedulerService → follows_pattern → SummarySchedulerService; GoodmorningRelay → follows_pattern → OlyaRelay, uses → goodmorning_captions, sends_from → media/common/goodmorning; цепочки зависит: T-228←T-227, T-231←T-227, T-233←T-231, T-234←T-233.
- **Шаг 8 (@Memory, 2026-08-17):** Epic30_CommonExpansion — статус **DEPLOYED** (коммит `714a4f6`, прод PID 939545, goodmorning ВКЛЮЧЕНА для -1002661910336, .env.bak.epic30, 0 traceback); T-227…T-234 — **ALL DONE**; AdminBot — прод v2.28.0, 1327 тестов.

### ✅ Реализация (Шаг 6, @Builder + @Reviewer, 2026-08-17)

- **T-227/T-228 (selfdev/work):** `filters/selfdev_word.py` (SelfdevWordFilter) и `filters/work_word.py` (WorkWordFilter) — кириллические границы, IGNORECASE, фразы первыми, text+caption, гейт `forward_origin is None` (D92); списки в `filters/word_lists.py`: SELFDEV_WORDS 48 форм / SELFDEV_PHRASES 17 фраз, WORK_WORDS 128 форм / WORK_PHRASES 31 фраза; `handlers/common.py` +selfdev_handler/work_handler (порядок **otboy → danger → selfdev → work → mimic**); CommonRelay — generic пер-сабдир коулдауны + алиасы `_danger_*` (Epic 18-тесты живы); `SELFDEV_COOLDOWN=5m`, `WORK_COOLDOWN=5m`.
- **T-229 (goodmorning):** `services/goodmorning_captions.py` (6 капций: 3 канона дословно + 3 новые, стиль-гард), `services/goodmorning_relay.py` (plain-send без reply/quote, прецедент OlyaRelay; audio/voice skip с WARNING), `services/goodmorning_scheduler.py` (APScheduler: CronTrigger HH:MM+tz, MemoryJobStore, max_instances=1, coalesce=True, `_parse_hhmm` fallback 07:00, start() False при пустых TARGET_CHAT_IDS); конфиг GOODMORNING_TIME=07:00 / TZ=Asia/Yekaterinburg / TARGET_CHAT_IDS=() / MEDIA_DIR; bot.py: wiring on_startup/on_shutdown, **порядок роутеров НЕ изменён**.
- **T-230 (нумерация промпта, D90):** `services/summary_prompts.py` — нумерация последовательная **1–6** (4→3, 5→4, 6→5, 7→6), текст пунктов дословно; эталон backlog 1518–1539 и слайс `lines[1517:1539]` не сдвинуты; `test_numbering_gap_4_5` → `test_numbering_sequential`; **байт-в-байт зелёный**; COMPRESS/EXTRACT не тронуты.
- **T-231 (тесты + ревью):** **1327 passed / 0 failed** (baseline 1002 → +325: test_selfdev_word.py 87, test_work_word.py 183, test_goodmorning.py 39, +16 test_common.py, обновлён test_summary_prompts.py). @Reviewer **APPROVED**: каноны капций байт-в-байт, текст промпта байт-в-байт, пересечения SELFDEV/WORK × DANGER/отбой = ∅, коулдауны двухслойные, репост-гейты, планировщики изолированы (у goodmorning свой AsyncIOScheduler), кодировки целы, `git diff --check` чист; 2 doc-правки ревьюера внесены (цифры тестов в README/board).
- **T-232 (доки):** README.md v2.28.0 (+секции selfdev/work/goodmorning, конфиг-таблица, changelog «🆕 Новое в v2.28.0 (Epic 30)»), .env.example (SELFDEV_COOLDOWN, WORK_COOLDOWN, GOODMORNING_*), планы (backlog/board/ARCHITECTURE/MEMORY).
- **🚨 Инцидент cp1251 (закрыт):** временная lossy-перекодировка `plans/backlog.md` через cp1251 при массовой правке чекбоксов PowerShell-скриптом — восстановлено биективно, байт-в-байт зелёный. **Урок:** не использовать PowerShell-скрипты для массовых правок UTF-8 файлов планов — только точечные правки специализированными инструментами.
- **✅ Деплой (Шаг 7–8, @DevOps + @Memory):** **T-233 DONE** — коммит `714a4f6` «feat(common): Epic 30 — selfdev/work-реакции, goodmorning-рассылка и фикс нумерации промпта (v2.28.0)» (30 файлов: 14 изменённых + 16 новых, включая 8 медиа-файлов media/common/{selfdev,work,goodmorning}), пуш в origin/master, рабочее дерево чистое. **T-234 DONE** — деплой на прод 198.46.175.136: git pull ff `7160a33..714a4f6`; бэкап `.env.bak.epic30`; в .env: GOODMORNING_TIME=07:00, GOODMORNING_TZ=Asia/Yekaterinburg, GOODMORNING_TARGET_CHAT_IDS=-1002661910336 (рассылка ВКЛЮЧЕНА), SELFDEV_COOLDOWN=5m, WORK_COOLDOWN=5m; systemctl restart admin_bot → active (running), PID 939545 (был 937634); логи: «Goodmorning scheduler started (07:00 Asia/Yekaterinburg, 1 chats)», «Bot started, listening for messages...», 0 traceback. Наблюдение: старый PID 937634 ушёл в SIGKILL после 90с таймаута stop-sigterm (pre-existing не-блокер) — новый инстанс стартовал штатно.

---

## ✅ Epic 29: UX-полировка — удаление команды, ack-вариации, промпт v4 — v2.27.0 (DEPLOYED, Шаг 8 @Memory, 2026-08-17)

> **Статус:** Шаг 1 (PM: R29-1…R29-6, D81–D84) ✅ → Шаг 2 (@Architect, T-221, Section 38) ✅ → Шаг 3 (@Memory, DESIGN) ✅ → Шаги 4–5: @Builder (T-222…T-225) ✅ + @Reviewer PASS ✅ → Шаг 6 (@Memory): IMPLEMENTED ✅ → Шаг 7: @DevOps (T-226, коммит `7160a33` + пуш + деплой) ✅ → **Шаг 8 (@Memory): DEPLOYED ✅. ЭПИК 29 ЗАКРЫТ, цикл воркфлоу (0–8) завершён.** Прод v2.27.0 (коммит `7160a33`, PID 937634, 1002 тестов).
> **Требования R29-1…R29-6, решения D81–D84:** `plans/backlog.md` (Epic 29). **Дизайн:** `plans/ARCHITECTURE.md` Section 38 (38.1–38.7).

### 📐 Дизайн (Section 38, @Architect, 2026-08-16)

| Блок | Суть |
|---|---|
| **38.1 (T-221, D81)** | `cmd_summary` новый порядок: allow-check (R9/D62 silent absorb) → generator-check (`_generator is None` → UX без delete, B6) → INFO `triggered` → `_delete_command` → ack из пула → `generate_and_send(manual=True)`. Логи: `triggered` → `command deleted`/`command delete failed` → `ack sent`. Ack — `send_message` (не reply). `import random` в шапку; docstring модуля обновить |
| **38.2 (T-222, D82)** | `_UX_ACK` → `_UX_ACK_VARIANTS: tuple[str, ...]` — пул из 20 фраз, канон «ща гляну, подожди» первым; `random.choice` при каждом ручном `/summary`; стиль: маленькая буква, без эмодзи/маркдауна/мата. `_UX_NOT_READY`/`_UX_EMPTY`/`_UX_BUSY` — НЕ трогать |
| **38.3 (T-223, D83/D84)** | Промпт v4: пункт 3 удалён (типографика → `cleanup_llm_text` 37.6); пункт 6 — канон пользователя ДОСЛОВНО (уже в дереве `M services/summary_prompts.py:18`: «нечитаемая херня», «чел с пейзажем в нике», «используй СТРОГО дословное значение из атрибута author» — D83, НЕ переписывать/не чинить); нумерация — зазор «1,2,4,5,6,7» НЕ перенумеровывать (D84; **⚠️ СУПЕРСЕД D90, Epic 30: перенумеровано последовательно 1–6**); эталон backlog → 22 строки, 1518–1539, слайс `lines[1517:1539]`; плейсхолдеры `{max_symbols}`/`{username}` без изменений; канон содержит «—» и `"` — не чинить |
| **38.4 (T-224)** | Доки: ARCHITECTURE (правки Architect уже внесены — верифицировать), MEMORY.md (лента + ссылки v3→v4: 1518–1539, B1/B7 — выполнено @Memory в Шаге 3), README.md:176 («расстрел типографики» → cleanup бэкенда, иронично), board.md |
| **38.5 (T-225)** | Тесты: правки test_summary_handlers.py 400/405-423/438/661/700 (`assert in _UX_ACK_VARIANTS`, порядок `["delete", "ack", "generate"]`); test_summary_prompts.py 11/13/14 (Epic 29, 1518-1539, `lines[1517:1539]`), :59 (ассерт «используй СТРОГО дословное значение из атрибута author»); новые: канон в пуле, пул ≥ 20, «3. Типографика» отсутствует, зазор-нумерация 4/5 (**⚠️ D84, СУПЕРСЕД D90 Epic 30**); полный прогон 995 baseline, байт-в-байт зелёный после синхронизации эталона, 0 регрессий |
| **38.6 (T-226)** | Коммит на русском `feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)` — ВКЛЮЧАЯ канон пользователя (`M services/summary_prompts.py`); пуш; деплой: git pull → restart (~95с SIGTERM pre-existing) → верификация (0 traceback, порядок логов `triggered → command deleted → ack sent`) |

### ✅ Реализация (T-222…T-225, @Builder + @Reviewer, 2026-08-16)

- **T-222 (ack-пул, D81/D82):** `handlers/summary.py` — `_UX_ACK_VARIANTS` (20 фраз, канон «ща гляну, подожди» первым), `random.choice` при каждом ручном `/summary`; порядок `triggered → _delete_command → ack → generate_and_send`; best-effort delete (try/except → WARNING) НЕ тронут; denied-ветка (R9) и `_generator is None` — без delete/ack.
- **T-223 (SYSTEM_PROMPT v4, D83/D84):** пункт 3 (типографика) удалён; нумерация-зазор «1,2,4,5,6,7» НЕ перенумерована (**⚠️ D84 СУПЕРСЕД D90, Epic 30 — нумерация будет 1–6**); пункт 6 — канон пользователя ДОСЛОВНО (незакоммиченная правка НЕ откачена); эталон backlog.md **1518–1539** (22 строки), слайс `lines[1517:1539]`; тест :59 — новый ассерт «используй СТРОГО дословное значение из атрибута author»; **байт-в-байт ЗЕЛЁНЫЙ**; плейсхолдеры `{max_symbols}`/`{username}` без изменений; COMPRESS/EXTRACT не тронуты.
- **T-224 (доки):** ARCHITECTURE.md (Section 38.x + ссылки v3→v4: строки 4753/4749/3938), README.md:176 («расстрельная бригада переехала в бэкенд»), board.md статусы, backlog.md эталон.
- **T-225 (тесты + ревью):** **1002 passed (995 baseline + 7 новых), 0 failed, 0 skipped**; `git diff --check` чист. Ревью **PASS, 0 blocking**; non-blocking N2 (запись IMPLEMENTED в MEMORY.md) закрыта этим же Шагом 6; N4/N5 — опциональные.
- **Изменённые файлы (9):** `handlers/summary.py`, `services/summary_prompts.py`, `plans/backlog.md`, `plans/ARCHITECTURE.md`, `plans/board.md`, `README.md`, `tests/test_summary_handlers.py`, `tests/test_summary_prompts.py`, `plans/MEMORY.md`. **Закоммичено в `7160a33` и запушено (T-226).**

### 🚀 Деплой-дайджест (T-226 DONE, @DevOps + @Memory, Шаг 8, 2026-08-16/17)

- **Коммит:** `7160a33` — `feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)` — запушен в origin/master. **9 файлов** (handlers/summary.py +39, services/summary_prompts.py +7, tests +82 и др.), +541/−125. **Канон-правка пункта 6 пользователя — ДОСЛОВНО**; Builder восстановил только номера пунктов 4/5/6/7 (зазор D84; ⚠️ СУПЕРСЕД D90, Epic 30 — нумерация станет 1–6) — текст канона НЕ тронут.
- **Деплой:** прод 198.46.175.136:/var/www/admin_bot: `git pull` ff `ac80ce8..7160a33` (прод был на ac80ce8 — docs-коммит ccfad99 на проде отсутствовал, не критично); `.env` НЕ тронут; `systemctl restart admin_bot` → Active: running, **PID 937634** (был 936542); **0 traceback**; «Dimension mismatch» НЕТ (штатный WARNING автолечения остаётся); «SUMMARY_ALIASES invalid JSON» НЕТ; **sqlite-vec dim=3072**.
- **Тесты/ревью:** **1002 passed** (995 + 7), 0 failed, 0 skipped; ревью PASS; **T-221…T-226 ALL DONE**.
- **Непроверенное (не блокер):** ручных `/summary` за окно наблюдения не было — порядок «command deleted → ack sent» (D81/D82) проверится на первом реальном вызове.
- **Известное неблокирующее:** journalctl требует sudo для nik.
- **ЭПИК 29 ЗАКРЫТ:** Epics 1–29 ALL DEPLOYED. Проект PRODUCTION-READY v2.27.0.

### 📋 Задачи (финальные статусы, Шаг 8)

- **T-221** @Architect (P0) — Section 38: D81 (delete ДО ack), D82 (пул), промпт v4 (D83/D84), доки/тесты/деплой → **DONE** (2026-08-16, Шаг 2)
- **T-222** @Builder (P1, ←T-221) — `_UX_ACK_VARIANTS`: пул 20 фраз, канон первым, `random.choice` + правки ассертов + новые тесты → **DONE** (Шаг 6)
- **T-223** @Builder (P0, ←дизайн) — промпт v4: пункт 3 удалён, пункт 6 канон дословно, зазор-нумерация (**⚠️ D84, СУПЕРСЕД D90 Epic 30**), эталон 1518–1539, слайс `lines[1517:1539]`, тесты :11/:13/:14/:59 → **DONE** (Шаг 6, байт-в-байт зелёный)
- **T-224** @Builder (P2, параллельно) — доки: ARCHITECTURE, README.md:176, board.md → **DONE** (Шаг 6)
- **T-225** @Builder+@Reviewer (P0, ←T-222…T-224) — тесты + полный прогон + ревью → **DONE** (Шаг 6: 1002 passed, ревью PASS, 0 blocking)
- **T-226** @DevOps+@PM (P1, ←T-225) — коммит (включая канон пользователя) + пуш + деплой + верификация (38.6) → **DONE** (2026-08-16: коммит `7160a33` (9 файлов) в origin/master, деплой ff `ac80ce8..7160a33`, PID 937634, 0 traceback, dim=3072)

### ✅ Верификация деплоя (T-226 DONE — все предупреждения закрыты, Шаг 8)

- **Коммит на русском** ✅ `feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)` = `7160a33` — **канон пользователя вошёл ДОСЛОВНО** (`M services/summary_prompts.py`); Builder восстановил только номера пунктов 4/5/6/7 (зазор D84; ⚠️ СУПЕРСЕД D90, Epic 30 — нумерация станет 1–6) — текст канона НЕ тронут. 9 файлов в коммите, запушен в origin/master.
- **Деплой** ✅ прод 198.46.175.136:/var/www/admin_bot: `git pull` ff `ac80ce8..7160a33` (прод был на ac80ce8 — docs-коммит ccfad99 на проде не было, не критично); `.env` НЕ тронут; `systemctl restart admin_bot` → active (running), PID **937634** (был 936542); **0 traceback**.
- **Логи** ✅ «Dimension mismatch» НЕТ (штатный WARNING автолечения «EMBEDDING_DIM=768 != actual API dim=3072 — using actual» остаётся); «SUMMARY_ALIASES invalid JSON» НЕТ; sqlite-vec **dim=3072**.
- **Порядок логов `triggered → command deleted → ack sent`:** ручных `/summary` за окно наблюдения не было — проверится на первом реальном вызове (**НЕ блокер**); код порядка (D81/D82) задеплоен в `handlers/summary.py`.
- **Байт-в-байт:** в проде активен SYSTEM_PROMPT **v4** (22 строки, эталон backlog 1518–1539, слайс `lines[1517:1539]`); при правках backlog выше блока R11 пересчитывать диапазон (формула: конец = 1539 + N_вставленных).
- **НЕ тронуты:** `COMPRESS_PROMPT`/`EXTRACT_PROMPT`, `llm_client.py`, `summary_generator.py`, `summary_cleanup.py`, `bot.py`, scheduler, продовый `.env`.
- **Известное неблокирующее:** journalctl требует sudo для nik (ника в adm/systemd-journal нет).

---

## ✅ Epic 28: Качество памяти — векторы, репосты, алиасы, очистка — v2.26.0 (DEPLOYED, Шаг 8 @Memory, 2026-08-16)

> **Статус:** Шаг 1 (PM: R28-1…R28-6, D76–D80) ✅ → Шаг 2 (@Architect, Section 37) ✅ → Шаг 3 (@Memory, DESIGN) ✅ → Шаги 4–5: @Builder (T-211…T-219) ✅ + @Reviewer PASS ✅ → Шаг 6 (@Memory): IMPLEMENTED ✅ → Шаг 7: @DevOps T-220 (коммит `ac80ce8` + пуш + деплой) ✅ → **Шаг 8 (@Memory): DEPLOYED ✅. ЭПИК 28 ЗАКРЫТ, цикл воркфлоу (0–8) завершён.** Прод v2.26.0 (коммит `ac80ce8`, PID 936542, dim=3072).
> **Требования R28-1…R28-6, решения D76–D80:** `plans/backlog.md` (Epic 28). **Дизайн:** `plans/ARCHITECTURE.md` Section 37 (37.1–37.10).

### 📐 Дизайн (Section 37, @Architect, 2026-08-16)

| Блок | Суть |
|---|---|
| **37.1** | 4 проблемы: векторы L3, репосты, алиасы, типографика. **Границы (НЕ трогать):** COMPRESS_PROMPT/EXTRACT_PROMPT, `llm_client.py`, `.replace` (`summary_generator.py:113`), порядок атрибутов `<message>`, `_ensure_shiz_postfix`, `bot.py`, `smart_archive_facts`, `config/settings.py` (EMBEDDING_DIM), `_SCHEMA_SQL` кроме блока smart_messages |
| **37.2 (T-211)** | Миграция smart_messages: +`is_forward INTEGER NOT NULL DEFAULT 0`, +`forward_source TEXT NOT NULL DEFAULT ''` (в КОНЕЦ). Свежие БД — `_SCHEMA_SQL` (database.py:50–59) целиком; прод-БД — 2× `ALTER TABLE ADD COLUMN` в try/except `aiosqlite.OperationalError` в `initialize()` (после блока dead_page_posts 120–125, до PRAGMA foreign_keys 127; прецедент — паттерн dead_page_posts). `save_smart_message` (358): kw `is_forward: bool = False`, `forward_source: str = ""` в КОНЕЦ сигнатуры (позиционные вызовы тестов не ломаются). 3 SELECT'а (get_smart_window:387, get_smart_raw:399, search_messages_fts:470–471) дополнены колонками |
| **37.3 (T-212…T-215)** | Forward-маркировка сквозь пайплайн: observer `origin = getattr(message, "forward_origin", None)` (getattr-защита) → `_extract_forward_source(origin)` (Channel: chat.title/@username + author_signature; User: имя sender_user через `_aliases.resolve`; HiddenUser: sender_user_name; Chat: sender_chat.title/@username; обрезка `_FORWARD_SOURCE_MAX_CHARS=100`; try/except — сбой не роняет сохранение); `is_forward=True` при ЛЮБОМ origin. XML: `is_forward="true"` / `forward_source="..."` В КОНЕЦ тега (порядок id,timestamp,author,reply_to_id,type не менять; экранирование `_escape(quote=True)`). L2: `_format_l2_quote` → «Оля (репост из "Канал X"): текст» / «Оля (репост): текст». L3/GraphRAG: `_build_batch_text` → «[Оля (репост из "Канал X")]: текст» / «[Оля (репост)]: текст»; вложенные `"` → `'`; строки без is_forward — старое поведение байт-в-байт |
| **37.4 (T-213-D/T-214-A/B, D76)** | Ре-резолв алиасов НА ЛЕТУ, ВСЕГДА при `aliases is not None`: `aliases.resolve(int(row["user_id"] or 0), author_name or None, None)` — заданный алиас побеждает устаревший author_name старых строк. Новые хелперы `_resolve_author(row)`, `_format_l2_quote(row)`; `_most_active_author(rows, aliases=None)` (staticmethod, в `_ensure_shiz_postfix` через `getattr(self, "aliases", None)` — self=None → старое поведение); сигнатура `build(self, messages, aliases: AliasResolver | None = None)` НЕ переименовывается |
| **37.5 (T-216, D78/D79)** | Векторное автолечение L3: probe `embed(["probe"])` — ПЕРВИЧНЫЙ источник actual_dim (ровно 1 вызов на старт, только при загруженном vec, в try/except → WARNING + FTS5, старт не ломается); DDL-разбор `sqlite_master` → regex `float\[(\d+)\]` → stored_dim; **DROP smart_archive ТОЛЬКО при stored_dim != actual_dim** + пересоздание `float[{actual_dim}]` (smart_archive_facts НЕ трогается, D78); WARNING при `actual_dim != settings.EMBEDDING_DIM`; `self._vec_dim = actual_dim` (`__init__` дополнен `None`); рантайм-INSERT «dimension/mismatch» → живой DROP НЕТ: `_vec_available=False` (FTS5 до рестарта) + ERROR-лог; пустой KNN → INFO-лог + FTS5-фоллбек (не только при падении) |
| **37.6 (T-218)** | Новый `services/summary_cleanup.py`: `REPLACEMENTS = (("«", '"'), ("»", '"'), ("„", '"'), ("“", '"'), ("—", "-"), ("–", "-"))`; `cleanup_llm_text(text)` — Never raises; вставка в `summary_generator._run` сразу ПОСЛЕ `llm.generate` и лога raw, ДО `_ensure_shiz_postfix` |
| **37.7 (T-217, D76/D77)** | SYSTEM_PROMPT v3: **правило 6** (алиас из атрибута author обязателен дословно, переименовывать нельзя; без алиаса — свобода + креативная интерпретация ника «человек с пейзажем в нике»; финал — имя из author) + **правило 7** (is_forward="true" → содержание принадлежит forward_source, не переславшему); пояснение финала: «реальный ник из контекста» → «имя участника из атрибута author» (D73 сохраняется); 23 строки (v3); эталон backlog **1518–1539** (с Epic 29 v4 — 22 строки), слайс `lines[1517:1539]`; плейсхолдеры {max_symbols} ×1, {username} ×2 БЕЗ изменений (атрибуты в правилах — без фигурных скобок) |
| **37.8 (T-219)** | Тест-план: 939 baseline + новые, 0 регрессий; юнит-тесты на каждую задачу + полный pytest + ревью @Reviewer (безопасность DROP только при фактическом расхождении, факты не трогаются, промпт без конфликтов) |
| **37.9 (T-220, D80)** | Деплой: **прод .env НЕ трогаем** (автолечение чинит само при рестарте); опционально `EMBEDDING_DIM=3072` (бэкап `.env.bak.epic28`) — только для чистых логов; git pull → restart (~95с SIGTERM pre-existing) → верификация: НЕТ «Dimension mismatch», есть «sqlite-vec loaded (dim=3072)» (или WARNING probe → FTS5), 0 traceback. Инструкция пользователю: «Действия не нужны — бот сам починит векторную память при старте» |

### ✅ Реализация (T-211…T-219, @Builder + @Reviewer, 2026-08-16)

- **T-211 (миграция):** `is_forward INTEGER NOT NULL DEFAULT 0` + `forward_source TEXT NOT NULL DEFAULT ''` в конец smart_messages (`_SCHEMA_SQL` + 2× ALTER в try/except `OperationalError`); `save_smart_message` +2 kw в конец сигнатуры; 3 SELECT'а дополнены. Девиация: хелпер `row_get()` (sqlite3.Row без `.get`).
- **T-212 (observer):** `origin = getattr(message, "forward_origin", None)`; `_extract_forward_source` по 4 типам origin (Channel/User/HiddenUser/Chat), алиасы для User, обрезка 100 симв., try/except — сбой не роняет сохранение.
- **T-213 (XML + алиасы):** `is_forward="true"` / `forward_source="…"` В КОНЕЦ тега `<message>` (порядок существующих атрибутов не тронут, `_escape(quote=True)`); ре-резолв алиасов на лету ВСЕГДА при `aliases is not None`.
- **T-214 (генератор):** `_resolve_author(row)`, `_format_l2_quote(row)` («Оля (репост из "Канал X"): текст» / «Оля (репост): текст», вложенные `"` → `'`), `_most_active_author(rows, aliases=None)` через `getattr(self, "aliases", None)`; `cleanup_llm_text` после generate ДО `_ensure_shiz_postfix`. Девиация: `.replace` теперь на строке 115 (сдвиг от импорта) — `str.format` не вызывается.
- **T-215 (_build_batch_text):** «[Оля (репост из "Канал X")]: текст» / «[Оля (репост)]: текст»; строки без is_forward — байт-в-байт; COMPRESS_PROMPT не тронут.
- **T-216 (VecAutoHeal):** probe embed → actual_dim (1 вызов на старт, try/except → WARNING + FTS5); DDL-разбор → stored_dim; **DROP smart_archive только при stored_dim != actual_dim** + пересоздание; smart_archive_facts цел; `self._vec_dim`; рантайм INSERT-mismatch → `_vec_available=False`; пустой KNN → INFO + FTS5; WARNING при непарсируемом DDL (замечание закрыто).
- **T-217 (SYSTEM_PROMPT v3):** правила 6/7; **байт-в-байт == backlog 1518–1539** (инвариант D74; с Epic 29 v4 — 22 строки); хелпер `lines[1517:1539]`; плейсхолдеры `{max_symbols}` ×1, `{username}` ×2 без изменений.
- **T-218 (cleanup):** новый `services/summary_cleanup.py` — REPLACEMENTS из **6 пар** («»→", „“→", —→-, –→-), `cleanup_llm_text` never raises; вставка в `_run` после лога raw.
- **T-219 (тесты):** **995 passed (939 baseline + 56 новых), 0 failed, 0 skipped**; `git diff --check` чист. Ревью PASS; 4 non-blocking замечания закрыты (board.md статусы, ARCHITECTURE «6 пар замен», WARNING непарсируемого DDL, docstring row_get). Девиация: 56 тестов вместо 58.
- **Изменённые файлы (18):** `services/database.py`, `handlers/summary.py`, `services/summary_xml.py`, `services/summary_generator.py`, `services/summary_memory.py`, `services/summary_cleanup.py` (новый), `tests/test_summary_cleanup.py` (новый), `services/summary_prompts.py`, тесты (7 файлов), планы (board.md/backlog.md/ARCHITECTURE.md/MEMORY.md). **Закоммичено в `ac80ce8` и запушено (T-220).**

### 📋 Задачи (финальные статусы, Шаг 8)

- **T-211** @Builder (P0) — миграция smart_messages (37.2) → **DONE**
- **T-212** @Builder (P0, ←T-211) — observer: детекция репостов + `_extract_forward_source` (37.3) → **DONE**
- **T-213** @Builder (P0, ←T-211) — XML-атрибуты репоста + ре-резолв алиасов (37.3/37.4) → **DONE**
- **T-214** @Builder (P0, ←T-212/T-213) — генератор: `_resolve_author`, `_format_l2_quote`, `_most_active_author` (37.3/37.4) → **DONE**
- **T-215** @Builder (P0, ←T-211/T-212) — `_build_batch_text`: маркировка репостов (37.3) → **DONE**
- **T-216** @Builder (P1, ←дизайн) — векторное автолечение L3 (37.5) → **DONE**
- **T-217** @Builder (P0, ←дизайн) — SYSTEM_PROMPT v3: правила 6/7 + эталон + ссылки (37.7) → **DONE**
- **T-218** @Builder (P2, параллельно) — cleanup-модуль (37.6) → **DONE**
- **T-219** @Builder+@Reviewer (P0, ←T-212…T-218) — тесты на всё + полный прогон (37.8) → **DONE** (995 passed, ревью PASS)
- **T-220** @DevOps+@PM (P1, ←T-219) — коммит + деплой + инструкция (37.9, D80) → **DONE** (коммит `ac80ce8`, пуш, деплой ff `1d7bed4..ac80ce8`, PID 936542, автолечение 768→3072 штатно, 0 traceback)

### 🚀 Деплой-дайджест (T-220 DONE, @DevOps + @Memory, 2026-08-16, Шаг 8)

- **Коммит:** `ac80ce8` — `feat(summary): Epic 28 — качество памяти: репосты, алиасы, векторное автолечение и cleanup (v2.26.0)` — запушен в origin/master. **18 файлов**: 2 новых (`services/summary_cleanup.py`, `tests/test_summary_cleanup.py`) + 16 изменённых. Полный pytest 995 passed (939 + 56), `git diff --check` чист.
- **Деплой:** прод 198.46.175.136:/var/www/admin_bot: `git pull` ff `1d7bed4..ac80ce8`; **.env НЕ тронут** (SUMMARY_ALIASES 36 пар остались, WARNING «invalid JSON» отсутствует); `systemctl restart admin_bot` → active (running), **PID 936542** (был 934174); 0 traceback.
- **Автолечение сработало ШТАТНО на первом старте:** «EMBEDDING_DIM=768 != actual API dim=3072 — using actual»; «vec dimension mismatch (stored=768, actual=3072) — dropping smart_archive (facts in smart_archive_facts are kept)»; «sqlite-vec loaded (dim=3072)». **smart_archive_facts сохранён.** «Dimension mismatch» как ошибка отсутствует.
- **Итог:** новые сообщения векторизируются в **3072** корректно, репосты маркируются (`is_forward`/`forward_source`), алиасы резолвятся на лету, ответы LLM чистятся от ёлочек/тире. Прод .env править не потребовалось (D80: «Действия не нужны — бот сам починил векторную память при старте»).

### ✅ Верификация деплоя (T-220 DONE — все предупреждения закрыты, Шаг 8)

- **Хелпер-диапазон `lines[1517:1539]`** — реализован и сверен (v3 байт-в-байт == backlog; с Epic 29 v4 — 1518–1539, 22 строки); в проде до v2.27.0 активен v3. При правках backlog выше блока пересчитывать (формула `1538 + N_вставленных`).
- **SYSTEM_PROMPT v3 — байт-в-байт** == backlog 1518–1539 (инвариант D74; с Epic 29 v4 — 22 строки); перед коммитом `git diff --check` и полный pytest (995 passed) — чисто.
- **COMPRESS_PROMPT / EXTRACT_PROMPT — не тронуты** (байт-в-байт тесты зелёные); `llm_client.py`, `bot.py`, `config/settings.py` (EMBEDDING_DIM) — не тронуты.
- **DROP smart_archive на проде выполнился ОДИН раз** при 768→3072 — ожидаемо (D78/D79); `smart_archive_facts` сохранён; в логах после рестарта НЕТ «Dimension mismatch».
- **Прод .env НЕ тронут** (автолечение починило размерность само); EMBEDDING_DIM=3072 не понадобился (автолечение выдало «using actual» — лог штатный, не WARNING).
- **Коммит на русском**, conventional commits: `feat(summary): Epic 28 — … (v2.26.0)` — выполнен как `ac80ce8`; 18 файлов (2 новых + 16 изменённых); планы (board/backlog/ARCHITECTURE/MEMORY) в состав коммита.

---

## ✅ Epic 27: Новый системный промпт (бот-абьюзер v2) + SUMMARY_ALIASES на прод — v2.25.0 (DEPLOYED, Шаг 8 @Memory, 2026-08-16)

> **Статус:** Шаг 1 (PM) ✅ → Шаг 2 (@Architect, Section 36) ✅ → Шаги 4–5: @Builder (T-207/T-208) ✅ + @Reviewer PASS ✅ → Шаг 6 (@Memory): IMPLEMENTED ✅ → **Шаг 7: @DevOps T-210 (коммит `1d7bed4` + пуш) + T-209 (SUMMARY_ALIASES на прод + git pull + restart + верификация) ✅ → Шаг 8 (@Memory): DEPLOYED ✅. ЭПИК 27 ЗАКРЫТ, цикл воркфлоу (0–8) завершён. Прод v2.25.0, PID 934174, 939 тестов.**
> **Требования R27-1…R27-4, решения D72–D75:** `plans/backlog.md` (Epic 27, эталон промпта R11 v2 на строках 1518–1538; с Epic 29 эталон v4 — 1518–1539). **Дизайн:** `plans/ARCHITECTURE.md` Section 36 (36.1–36.8).

### 📐 Дизайн (Section 36, @Architect, 2026-08-16)

| Блок | Суть |
|---|---|
| **C1** | Единый источник истины — ТОЛЬКО backlog.md (R11 v2, 1518–1538, 21 строка; с Epic 29 v4 — 1518–1539, 22 строки); ARCHITECTURE ссылается, не дублирует (дубль = риск рассинхрона эталонов) |
| **C2** | Подстановка остаётся `SYSTEM_PROMPT.replace("{max_symbols}", …)` (summary_generator.py:113). `str.format` упал бы KeyError на `{username}` (теперь ×2); `.replace` точен и не трогает `{username}` |
| **C3** | Тест-счётчик скобок → проверка НАБОРА: `re.findall(r"\{(\w+)\}", SYSTEM_PROMPT)` → set == `{"max_symbols","username"}` (3 пары скобок: `{max_symbols}` ×1 + `{username}` ×2) |
| **C4** | `COMPRESS_PROMPT` / `EXTRACT_PROMPT` / `llm_client.py` / vec0-логика / GraphRAG-код — НЕ трогать |
| **C5** | Продовый .env: append строки из `.env.example:136` (JSON, 36 пар id-имя) с бэкапом `.env.bak.epic27`; grep-гард от дублей; значение в одинарных кавычках |
| **36.2/36.3** | Промпт v2: ленивая печать (случайный регистр), только короткие дефисы `-` и двойные кавычки `""` (тире `—` и ёлочки `«»` запрещены), запрет маркдауна/списков/эмодзи, абзацы; финал «самым главным шизом объявляется {username}» — маркер `_ensure_shiz_postfix` сохраняется |
| **36.4 Тест-план** | 939 baseline, 0 регрессий. Меняются ТОЛЬКО: хелпер `_backlog_system_prompt` (слайс `lines[1517:1523]` → `lines[1517:1538]`; с Epic 29 v4 → `lines[1517:1539]`) и `test_max_symbols_is_the_only_placeholder` (набор по D72). `test_format_max_symbols` / `test_shiz_marker_present` / `test_system_and_compress_prompts_untouched` — без изменений |
| **36.6 Деплой** | Бэкап `.env.bak.epic27` → SUMMARY_ALIASES (36 пар, одинарные кавычки, grep-гард) → git pull ff → restart (SIGTERM ~95с, pre-existing — не паниковать) → верификация: active (running), новый PID, JSON-валидация, 0 traceback, отчёт пользователю |

### ✅ Реализация (T-207/T-208, @Builder + @Reviewer, 2026-08-16)

- **SYSTEM_PROMPT v2 (T-207):** `services/summary_prompts.py` строки 8–28 (21 строка) — байт-в-байт == эталон `plans/backlog.md` 1518–1538 (с Epic 29 v4 — 1518–1539) (инвариант D74, `git diff --check` чист); плейсхолдеры `{max_symbols}` ×1, `{username}` ×2; подстановка `.replace` в `summary_generator.py:113` НЕ тронута (C2); `COMPRESS_PROMPT`/`EXTRACT_PROMPT` не изменены (C4).
- **Тесты:** хелпер `_backlog_system_prompt` — слайс `lines[1517:1538]` (с Epic 29 v4: `lines[1517:1539]`); `test_max_symbols_is_the_only_placeholder` переписан по D72 (regex `\{(\w+)\}` → set `{max_symbols, username}`); полный pytest **939 passed / 0 failed**; точечно 50 passed.
- **Доки (T-208):** README.md (+ироничный блок «Промпт v2»); plans/MEMORY.md (строки 109/241/258/751 — «SYSTEM_PROMPT обновлён в Epic 27 R11 v2; COMPRESS/EXTRACT заморожены»); ARCHITECTURE.md Section 36 (4298–4360); board/backlog: T-207/T-208 done.
- **Изменённые файлы (ровно 8):** `.env.example` (SUMMARY_ALIASES 36 пар, валидный JSON), `README.md`, `plans/ARCHITECTURE.md`, `plans/MEMORY.md`, `plans/backlog.md`, `plans/board.md`, `services/summary_prompts.py`, `tests/test_summary_prompts.py`. **Закоммичено в `1d7bed4` и запушено (T-210).**

### 📋 Задачи (финальные статусы, Шаг 8)

- **T-207** @Builder (P0) — SYSTEM_PROMPT = v2 дословно (backlog 1518–1538, без хвостовых пробелов; с Epic 29 v4 — 1518–1539) + docstring; тесты 36.4; полный pytest 939 → **DONE**
- **T-208** @Builder (P1, ←T-207) — доки: ARCHITECTURE.md (3332/3342/3514/3670/3676/3732/4198/4221/4242/4257 — правки Architect уже внесены, верифицировать), MEMORY.md (72/204/221/714 — «заморожено»), README.md (217) → **DONE**
- **T-209** @DevOps (P0, ←T-207/T-210) — SUMMARY_ALIASES на прод + git pull + restart + верификация (36.6) → **DONE** (Шаг 7: 36 пар в продовый .env, бэкап .env.bak.epic27, JSON OK, sha1 совпал, restart → PID 934174, 0 traceback, WARNING «invalid JSON» отсутствует)
- **T-210** @DevOps+@PM (P1, ←T-207/T-208) — коммит `feat(summary): Epic 27 — новый системный промпт бота-абьюзера v2 и SUMMARY_ALIASES (v2.25.0)` + пуш → **DONE** (Шаг 7: коммит `1d7bed4`, 8 файлов, пуш в origin/master)

### 🚀 Деплой-дайджест (T-209/T-210 DONE, @DevOps + @Memory, 2026-08-16)

1. **T-210 ✅:** коммит `1d7bed4` «feat(summary): Epic 27 — новый системный промпт бота-абьюзера v2 и SUMMARY_ALIASES (v2.25.0)» (8 файлов) запушен в origin/master (github.com/Henry-Case-dev/adminbot.git).
2. **T-209 ✅:** прод nik@198.46.175.136 (/var/www/admin_bot): git pull fast-forward `7c7c241..1d7bed4`; в .env добавлена `SUMMARY_ALIASES` (36 пар, бэкап `.env.bak.epic27`; верифицировано python3: JSON OK, sha1 совпал с репо); systemctl restart admin_bot → active (running), **новый PID 934174** (был 926618); 0 traceback после рестарта.
3. **Верификация:** WARNING «SUMMARY_ALIASES invalid JSON» в логах ОТСУТСТВУЕТ → AliasResolver распарсил все 36 пар. Тесты: 939 passed. Ревью PASS. SYSTEM_PROMPT v2 байт-в-байт == backlog 1518–1538 (с Epic 29 v4 — 1518–1539); плейсхолдеры {max_symbols} ×1, {username} ×2; подстановка .replace не тронута; COMPRESS/EXTRACT заморожены.
4. **Pre-existing не-блокер (не Epic 27):** WARNING «SmartModule L3: vector search failed — FTS5 fallback» + OperationalError Dimension mismatch 3072 vs 768 (старые эмбеддинги) — FTS5-фоллбек сработал штатно; рекомендован отдельный тикет на миграцию векторов.
5. **Вся цепочка воркфлоу (0–8) завершена. Epic 27 CLOSED.**

### ⚠️ Предупреждения для @Builder

- **SYSTEM_PROMPT больше НЕ заморожен с Epic 27** (R11 v2) — упоминания «дословно заморожены (R11), НЕ менять» обновлены в **T-208-B** (Builder, 2026-08-16; после сдвига строк Шага 3 это строки 109/241/258/751 — в дизайне 36.5 они значились как 72/204/221/714).
- `COMPRESS_PROMPT` / `EXTRACT_PROMPT` — по-прежнему заморожены дословно, НЕ трогать (backlog-риск 6, C4).
- Байт-в-байт инвариант (D74): backlog-блок 1518–1539 (v4 — Epic 29) == константа `SYSTEM_PROMPT`, без хвостовых пробелов; контроль `git diff --check`.
- Диапазон хелпера `1517:1539` хрупкий — при сдвиге строк backlog выше блока обновить (T-217-C).
- `summary_generator.py` НЕ менять — только проверить строку 113 (`.replace`, НЕ `str.format`).
- Файлы Builder: `services/summary_prompts.py`, `tests/test_summary_prompts.py`, README.md (при необходимости), планы; `.env.example` коммитится (D75, не секрет); локальный `.env` НЕ трогать/не коммитить.

---

## ✅ Epic 26: GraphRAG-память — граф знаний поверх SQLite (v2.24.0) — DEPLOYED (Шаг 8, @Memory, финальная синхронизация 2026-08-16)

> **Статус:** Шаг 1/3 (PM) ✅ → Шаг 2 (@Architect, T-199) ✅ → Шаг 3 (@Memory, DESIGN) ✅ → Шаги 4–5: @Builder (T-200–T-204) ✅ + @Reviewer дважды PASS ✅ → Шаг 6 (@Memory): IMPLEMENTED ✅ → **Шаг 7: @DevOps T-205 (README + коммит `7c7c241` + пуш + деплой) ✅ → Шаг 8 (@Memory): DEPLOYED ✅. ЭПИК 26 ЗАКРЫТ, цикл воркфлоу (0–8) завершён. Прод v2.24.0, PID 926618, 939 тестов.**
> **Требования R26-1…R26-7, PM-решения D67–D71, задачи T-199…T-205:** `plans/backlog.md` (Epic 26). **Дизайн:** `plans/ARCHITECTURE.md` Section 35 (35.1–35.11).

### 📐 Дизайн (Section 35, @Architect, 2026-08-16)

| Блок | Суть |
|---|---|
| **35.2 DDL** | `nodes` (id, chat_id, entity_name, entity_type CHECK ∈ user/topic/event, `UNIQUE(chat_id, entity_name)`) + `edges` (id, chat_id, source_id/target_id → nodes.id, relation_type, weight DEFAULT 1, last_updated, `UNIQUE(source_id,target_id,relation_type)`) в `_SCHEMA_SQL`; индексы chat_type / source / target / chat_weight |
| **35.3 EXTRACT_PROMPT** | Захардкожен ДОСЛОВНО в `services/summary_prompts.py` («ты — анализатор взаимосвязей… верни СТРОГО JSON-массив триплетов»); тест байт-в-байт T26.5-A; промпт не логировать целиком |
| **35.4 Extraction** | `_extract_and_save_graph` в `compress_and_purge`: extract (2-й LLM-вызов) → upsert nodes/edges → ТОЛЬКО ПОТОМ delete сырья (D68); кривой JSON → `GraphExtractionError` → пачка остаётся; валидный JSON с 0 годных триплетов — не застревает; `GRAPH_RAG_ENABLED=False` → вызов пропускается |
| **35.5 Traversal** | `get_graph_facts(chat_id, rows, keywords)` — never raises; сущности окна детерминированно БЕЗ доп. LLM-вызова (авторы + топ-2 ключей); SQL `weight DESC LIMIT 5`; фоллбеки chat-wide top; справки «[Историческая справка: …]» в `<historical_graph_facts>` ПЕРВЫМ в user-промпте (D71) |
| **35.6 Config** | `GRAPH_RAG_ENABLED=True`, `GRAPH_EDGE_WEIGHT_INCREMENT=1`, `GRAPH_TOP_EDGES_LIMIT=5`, `GRAPH_EXTRACT_MAX_TRIPLETS=50`; хардкод `_GRAPH_EXTRACT_MAX_CHARS=8000`, капы имён 100 / предикатов 200 |
| **35.7 Контракты** | Новые методы DatabaseService (`upsert_node`/`upsert_edge`/`match_nodes`/`get_top_edges`/`get_top_edges_all`); существующие сигнатуры НЕ меняются (`graph_facts: list[str] = []`); `llm_client.py` / `summary_xml.py` / `bot.py` НЕ трогать |
| **35.8 Тест-план** | 860 baseline + ~50–60 новых; адаптируются ТОЛЬКО 2 фикстуры (FakeLLM.extract_response, FakeMemory.get_graph_facts stub); ассерты не меняются |
| **35.9 Q1–Q10** | Все 10 открытых вопросов закрыты: event-узлы v1 НЕ создаются (DDL форвард-совместим); синонимов предикатов НЕТ; сущности окна без доп. LLM; FK-прагма НЕ включается; пачка та же (100, хвост ≤8000 симв.); prune графа НЕТ; обратная совместимость подтверждена; секция первая; имена = author_name + lower/strip; FakeLLM canned JSON |

### ✅ Реализация (T-200–T-204 + T-206, @Builder + @Reviewer, 2026-08-16)

- **DDL (T-200/T26.1):** таблицы `nodes`/`edges` в `DatabaseService._SCHEMA_SQL` — chat_id, UNIQUE(chat_id, entity_name), UNIQUE(source_id, target_id, relation_type), 4 индекса, upsert weight (ON CONFLICT weight+1). Методы: `upsert_node(chat_id, entity_name, entity_type) -> int`, `upsert_edge(...)`.
- **Extraction (T-201/T26.2):** `EXTRACT_PROMPT` дословно в `services/summary_prompts.py` (тест байт-в-байт T26.5-A PASS); `parse_triplets(raw) -> list[dict]` + `_extract_and_save_graph(chat_id, batch) -> None` в `services/summary_memory.py`; flow extract → graph → delete в `compress_and_purge` (per-batch isolation, D68); кривой JSON → GraphExtractionError → пачка остаётся.
- **Traversal (T-202/T26.3):** `get_graph_facts(chat_id, rows, keywords)` — never raises (try/except → []); fallback chat-wide `get_top_edges_all`; тег `<historical_graph_facts>` ПЕРВЫМ в `_compose_user_content(..., graph_facts: list[str] = [])` (services/summary_generator.py line 194); escape_xml_text.
- **Config (T-203/T26.4):** `GRAPH_RAG_ENABLED` / `GRAPH_EDGE_WEIGHT_INCREMENT` / `GRAPH_TOP_EDGES_LIMIT` / `GRAPH_EXTRACT_MAX_TRIPLETS` в config/settings.py (lines 247–253) + секция в .env.example; хардкод `_GRAPH_EXTRACT_MAX_CHARS=8000` и капы имён/предикатов в summary_memory.py.
- **Тесты (T-204):** 939 passed = 860 baseline + 73 Epic 26 + 6 T-206. Ревью дважды PASS (0 блокеров).
- **T-206 (P1, FIXED):** FTS-DELETE зеркалит условие вставки (`text IS NOT NULL AND text != ''`) в `delete_smart_messages_by_ids` и `delete_smart_messages_older_than`; добавлен chat_id-фильтр в FTS-DELETE by_ids; 6 регрессионных тестов. Pre-existing с Epic 24 (`a68732c`).
- **ARCHITECTURE.md 35.4:** зафиксирована допустимость JSON-объект-обёртки в ответе LLM (parse_triplets снимает её).

### 📋 Задачи (backlog/board)

- **T-199 (T26.0)** @Architect+@PM — Section 35 ✅ спроектирована и одобрена
- **T-200 (T26.1)** @Builder — DDL nodes/edges + 4 индекса + upsert CRUD (INSERT OR IGNORE / ON CONFLICT weight+1) ✅ DONE
- **T-201 (T26.2)** @Builder — extraction: EXTRACT_PROMPT verbatim, parse_triplets, граф ДО удаления сырья, per-batch isolation ✅ DONE
- **T-202 (T26.3)** @Builder — traversal: сущности окна L1, SQL weight DESC LIMIT 5, тег первым, escape_xml_text, fallback без секции ✅ DONE
- **T-203 (T26.4)** @Builder — конфиг GRAPH_* + .env.example ✅ DONE
- **T-204 (T26.5)** @Builder+@Reviewer — тесты (парсер/upsert/traversal/чат-изоляция/кривой JSON/pipeline graph_facts), полный pytest 939, code review дважды PASS ✅ DONE
- **T-206 (P1, добавлена на ревью)** @Builder+@Reviewer — FTS-DELETE зеркалит условие вставки (text IS NOT NULL AND text != '') в delete_smart_messages_by_ids/delete_smart_messages_older_than; chat_id-фильтр в FTS-DELETE by_ids; 6 регрессионных тестов ✅ FIXED
- **T-205 (T26.6)** @Builder+@DevOps — README (ироничный тон) + коммит на русском + пуш + деплой (ssh nik@198.46.175.136, systemctl restart admin_bot) ✅ DONE (Шаг 7) — коммит `7c7c241` запушен в origin/master, деплой на прод (PID 926618), 939 тестов

### 🚀 Деплой-дайджест (T-205 DONE, @DevOps + @Memory, 2026-08-16)

1. **T-205 ✅:** коммит `7c7c241` «feat(graphrag): Epic 26 — граф знаний nodes/edges, entity extraction и гибридный поиск /summary (v2.24.0)» (README с ироничным тоном + весь код Epic 26) запушен в origin/master (github.com/Henry-Case-dev/adminbot.git).
2. **Деплой ✅:** прод nik@198.46.175.136 (/var/www/admin_bot): git pull fast-forward `c364f18..7c7c241`; в .env добавлены `GRAPH_RAG_ENABLED=True`, `GRAPH_EDGE_WEIGHT_INCREMENT=1`, `GRAPH_TOP_EDGES_LIMIT=5`, `GRAPH_EXTRACT_MAX_TRIPLETS=50` (бэкап `.env.bak.epic26`); systemctl restart admin_bot → active (running), **Main PID 926618**; таблицы nodes/edges созданы в продовой БД; 0 traceback после рестарта.
3. **Тесты:** 939 passed (860 baseline + 73 Epic 26 + 6 T-206). T-206 (P1, FTS-удаление медиа без подписи) исправлен в этом же релизе.
4. **Известный не-блокер (pre-existing):** бот не отвечает на SIGTERM (~95с рестарт) — рекомендуется отдельный тикет graceful shutdown.
5. **Вся цепочка воркфлоу (0–8) завершена. Epic 26 CLOSED.**

### ⚠️ Предупреждения для @Builder

- 860 существующих тестов не ломать: правки ТОЛЬКО в фикстурах FakeLLM/FakeMemory (35.8), ассерты не трогать.
- Порядок вызовов extract → graph → delete критичен (D68): сырьё пачки удаляется только после сохранения графа.
- `PRAGMA foreign_keys` НЕ включать; проверка состояния прагмы на прод-БД → DEBUG-лог (T26.1-E).
- Не трогать: `llm_client.py`, `summary_xml.py`, `summary_aliases.py`, `summary_scheduler.py`, `summary_throttling.py`, `handlers/summary.py`, `bot.py`, vec0-логику (`rowid IN` purge).
- `SYSTEM_PROMPT` — обновлён в Epic 27 (R11 v2); `COMPRESS_PROMPT` и `EXTRACT_PROMPT` остаются заморожены (R11).

---

## 🐛 Epic 25: багфикс /summary — DEPLOYED (Шаг 8, @Memory, финальная синхронизация 2026-08-16)

> **Статус:** RCA ПОДТВЕРЖДЁН прод-логами (T-192 ✅) → Section 34 (B1–B9) DESIGN APPROVED (T-193 ✅) → **IMPLEMENTED** (@Builder T-194/T-195 ✅, 860 тестов PASS) → **REVIEW APPROVED** (@Reviewer T-196 ✅, 4 Low-замечания не блокируют) → **DEPLOYED** (@DevOps T-197/T-198 ✅, коммит `c364f18`, прод PID 923954). Прод: v2.23.0-fix.

### 🔬 RCA — подтверждён прод-логами Better Stack (T-192, 2026-08-16)

**Первопричина — асимметрия ThrottlingMiddleware с aiogram Command-фильтром:**

1. **18:02:19** пользователь прислал `/summary@RofloslavBot` (чужая mention) → middleware **сжёг слот троттлинга** (`startswith` без валидации mention) → `Command("summary")` **отклонил** сообщение (aiogram 3.29.1 `validate_mention`) → **тишина**;
2. **18:02:31** повтор `/summary` → **throttled** (12с < 60с) → молчание (by design R8).
3. За весь boot **ни одной строки** `triggered` / `window_size` / `LLM request` в логах — пайплайн не запускался ни разу.

**Опровергнутые гипотезы:** H-A/H-B/H-D/H-E/H-F ❌ — окно 91 msg НЕ пустое (наблюдатель работает); бот active; `ALLOWED_SUMMARY_IDS` не задан; 18:02 UTC не совпадает с cron-тиком (0,6,12,18 Asia/Yekaterinburg).

### 🏗️ Section 34 (ARCHITECTURE.md 34.1–34.10): решения B1–B9 — IMPLEMENTED (T-194/T-195) + REVIEWED (T-196)

| # | Решение | Суть |
|---|---------|------|
| **B1** | Ack до пайплайна | «ща гляну, подожди» — только manual, `send_message` (не reply). **С Epic 29 (38.1/38.2):** ack — `random.choice` из пула `_UX_ACK_VARIANTS` (20 фраз, канон в пуле, D82) |
| **B2** | `generate_and_send(chat_id, manual=False)` | cron — без ack |
| **B3** ⚠️ | Троттлинг | Чужая mention не потребляет слот (`data["bot"].me()`, кэш, case-insensitive); точное сравнение `base == "/summary"` вместо `startswith`; guard `text.strip()`; R8-молчание сохранено; Low-3 жив |
| **B4** | Пустое окно | manual → UX «тут тишина, саммарить нечего»; cron → INFO |
| **B5** | Lock занят | UX «уже делаю саммари, подожди» + очередь |
| **B6** ⚠️ | Страховка `_generator is None` | UX-ошибка; `_safe_send(bot)` принимает bot из DI хендлера (ревью J1 — вместо `setup_summary`) |
| **B7** | `message.delete()` | **С Epic 29 (D81):** ДО ack — сразу после триггера; было (Epic 25): сразу после ack; НЕ finally, try/except → WARNING; только исходная команда; denied — не удаляем. **Отменяет A11** |
| **B8** | Логирование всех состояний | triggered / throttled+remaining / ack / window empty / locked / llm ok/fail / chunk / command deleted; denied DEBUG→INFO |
| **B9** | Наблюдатель | Не пишет `/summary*` в smart_messages |

### ✅ Реализация (T-194/T-195, @Builder, 2026-08-16) — B1–B9 IMPLEMENTED

- `services/summary_throttling.py` (B3): `_parse_command` — валидация mention через `data["bot"].me()` (кэш aiogram, case-insensitive); чужая mention НЕ жжёт слот и пропускается; точное сравнение `base == "/summary"`; guard `text.strip()`; R8-молчание + INFO-лог с remaining (B8).
- `services/summary_generator.py` (B2/B4/B5): `generate_and_send(chat_id, manual=False)`; константы `_UX_EMPTY`/`_UX_BUSY`; пустое окно / занятый lock → UX (manual) + INFO (cron).
- `handlers/summary.py` (B1/B6/B7/B8/B9): ack «ща гляну, подожди» отдельным `send_message` до пайплайна; `_safe_send(bot)` с DI bot (работает при `_generator is None`); `message.delete()` сразу после ack, try/except → WARNING; INFO-логи всех состояний; наблюдатель не пишет `/summary*` в text и caption. **С Epic 29 (D81/D82):** delete ДО ack, ack — `random.choice(_UX_ACK_VARIANTS)` (пул 20 фраз).
- **Тесты: 860 PASS / 0 failed** (835 baseline + 25 новых), 0 регрессий.

### 🔍 Ревью (T-196, @Reviewer, 2026-08-16) — APPROVED ✅

- 860 тестов подтверждены личным прогоном; критичных багов нет. Первопричина T-192 закрыта (чужая mention не жжёт слот и проходит мимо троттлинга; своя/без mention троттлится; `base == "/summary"`; guard на пробельный текст).
- Подтверждены: **J1** (DI bot вместо `setup_summary`), **J2** (нет bot в data → своя mention), **J3** (ассерты DeleteMessage), **J4** (FakeLock), **J5** (B9 и caption). `Bot.me()` кэшируется aiogram — 1 вызов на процесс.
- R8/R9 сохранены: троттлинг молчалив (INFO+remaining), denied — без ack/delete/ответа (INFO).

| # | Low-замечание (не блокирует; кандидаты в backlog) | Статус |
|---|------------------------------------------------|--------|
| L1 | Мидлварь проверяет только `event.text` — команда-капшн может обойти троттлинг | ⚠️ pre-existing (с Epic 24), сериализуется Lock, на будущее |
| L2 | «ack sent» логируется даже при неудачной отправке ack | ⚠️ косметика |
| L3 | `bot.me()` в мидлвари без try/except | ⚠️ на будущее |
| L4 | `_last` растёт без TTL | ⚠️ pre-existing |

### 📋 Статусы задач

- **board.md:** T-192/T-193/T-194/T-195/T-196/T-197/T-198 ✅ Done. **Epic 25 DEPLOYED (v2.23.0-fix, `c364f18`, PID 923954).**
- ⚠️ **B7 (удаление команды) — best-effort:** при отсутствии у бота админ-права `delete_messages` в чате будет WARNING-лог (штатно). Ручное действие пользователя при появлении WARNING: выдать боту админ-права `delete_messages`.

### 🚀 Деплой-дайджест (T-197/T-198 DONE, @DevOps, 2026-08-16)

1. **T-197 ✅:** локально **860 passed** (7.43s) перед коммитом; коммит `c364f18` «fix(summary): починить /summary — валидация mention в троттлинге, ack и удаление команды (Epic 25)» — 11 файлов, +1001/−84; пуш `818e195..c364f18`; docs-коммит `2a45f79` запушен; .env не тронут.
2. **T-198 ✅:** прод 198.46.175.136: git pull ff `a68732c..c364f18`; .env не меняли (дефолты подходят); рестарт (первая попытка stop-timeout → SIGKILL старого процесса ~90с, pre-existing; вторая OK); active (running), **PID 923954**; старт чистый: Database initialized, sqlite-vec loaded (dim=768), cron 0,6,12,18, «SmartModule Summary initialized», все 14 роутеров, ImportError 0.
3. **Ожидание:** живых /summary после рестарта ещё не было — финальная верификация по логам после теста пользователем. Ожидаемая цепочка: `triggered → ack sent → window_size → LLM request → chunk sent → command deleted` (или WARNING при отсутствии прав `delete_messages` — штатно).
4. **Наблюдения (pre-existing, кандидаты в backlog):** (а) L3 dimension mismatch — эмбеддинги 3072 dim vs БД 768 → vector search failed → FTS5 fallback (деградация штатная, cron-саммари успешен); (б) stop-timeout systemd при рестарте (~90с → SIGKILL, сервис поднимается корректно).
5. **Ручные действия пользователя:** живой тест `/summary`; Н1 BotFather `/setprivacy` → Disable; при WARNING удаления — выдать боту админ-права `delete_messages`.

### Журнал Epic 25

| Шаг | Дата | Событие |
|-----|------|---------|
| Шаг 0 | 2026-08-16 | @Memory context sync по баг-репорту («/summary не реагирует» + требование удаления команды) |
| Шаг 1 | 2026-08-16 | @PM: задачи T-192/T-193 |
| Шаг 2 | 2026-08-16 | @Architect: T-192 RCA по прод-логам (первопричина подтверждена) + T-193 Section 34 (B1–B9) |
| Шаг 3 | 2026-08-16 | @Memory: граф знаний + MEMORY.md обновлены (RCA DONE + DESIGN APPROVED) → Builder |
| Шаг 4 | 2026-08-16 | @Builder: T-194/T-195 — B1–B9 реализованы (summary_throttling.py / summary_generator.py / handlers/summary.py), 860 тестов PASS (835+25), 0 регрессий |
| Шаг 5 | 2026-08-16 | @Reviewer: T-196 — APPROVED, 860 тестов подтверждены лично, J1–J5 подтверждены, 4 Low-замечания |
| Шаг 6 | 2026-08-16 | @Memory: граф знаний + MEMORY.md обновлены (IMPLEMENTED + REVIEW PASSED) → @DevOps (T-197/T-198) |
| Шаг 7 | 2026-08-16 | @DevOps: T-197 (коммит `c364f18` + docs `2a45f79`, push OK) + T-198 (деплой ff `a68732c..c364f18`, restart → active PID 923954, старт чистый) |
| Шаг 8 | 2026-08-16 | @Memory: ФИНАЛЬНАЯ синхронизация — граф знаний + MEMORY.md (Epic 25 DEPLOYED, v2.23.0-fix). Цикл завершён ✅ |

---

## ✅ Epic 24: SmartModule — сервис Summary (v2.22.0) — DEPLOYED (2026-08-16)

> **Запрос пользователя (2026-08-16):** спроектировать и реализовать автономный сервис
> **SmartModule** с подсервисом **Summary** для существующего бота. Все требования обязательные.
> **Статус (2026-08-16):** Шаг 1 (PM) ✅ → Шаг 2 (@Architect, T-173) ✅ → Шаг 4 (@Builder, T-174–T-188 A/B/C) ✅ →
> Шаг 5 (@Reviewer, T-188-D: **APPROVE WITH FIXES → Approved**) ✅ → Шаг 7 (@DevOps, T-190/T-191) ✅ → Шаг 8 (@Memory, финал) ✅.
> **Epic 24 DEPLOYED: прод v2.22.0 (PID 920105).**
> **Тесты: 835 PASS / 0 failed** (672 baseline + 163 новых; 830 после ревью + правки T-189).
> **Файлы:** CREATE `services/llm_client.py`, `summary_prompts.py`, `summary_aliases.py`, `summary_xml.py`,
> `summary_memory.py`, `summary_generator.py`, `summary_scheduler.py`, `summary_throttling.py`,
> `handlers/summary.py`; MODIFY `config/settings.py` (+24 поля), `services/database.py` (_SCHEMA_SQL + 11 методов),
> `bot.py` (роутеры 0a/0b + wiring on_startup/on_shutdown), `requirements.txt` (httpx, APScheduler 3.x, sqlite-vec),
> `.env.example`; локальный `.env` с реальным LLM_API_KEY (gitignored — в коммит не попадёт).
> **Ревью-фиксы (T-188-D):** (1) bot.py on_shutdown → `await _summary_service.shutdown()` (была не-awaited корутина, High);
> (2) summary_memory.py `_purge_archive`: DELETE по rowid IN вместо fact_id IN (документированная vec0-форма);
> (3) +1 QA-тест `test_vec_purge_removes_vectors`.
> **Завершение:** T-189 (README/доки + фиксы Low-замечаний) ✅ → T-190 (коммит `a68732c` + пуш) ✅ → T-191 (деплой, PID 920105) ✅.
> **Осталось пользователю (вручную):** Н1 — BotFather `/setprivacy` → Disable; живая проверка `/summary` в чате.
> **Критично (пост-деплой, вручную):** риск **Н1** — BotFather `/setprivacy` → **Disable** обязателен (иначе память L1/L2/L3 пустая). Через SSH невыполнимо.

### Подтверждённые технические решения (реализация + реальные тесты, 2026-08-16)

- **sqlite-vec 0.1.9 работает на Windows/Py3.12** — реальные тесты без skip.
- **vec0 0.1.x не поддерживает WHERE по auxiliary-колонкам в KNN** → фильтр чата в Python.
- **FTS5 unicode61 + свой префиксный поиск** с санитайзом `*` и `"`.
- **APScheduler 3.11 требует tz в CronTrigger**; shutdown(wait=False) + asyncio.sleep(0).
- **Латентный баг дизайна 33.7 ИСПРАВЛЕН:** `{username}` подставляется литералом, `{max_symbols}` — через `.replace()` (str.format не вызывается).
- Наблюдатель через `@router.message()` без фильтра; медиа без caption сохраняются ([фото]/[видео]), чистые сервисные пропускаются; удаление пачки по ids после успешного сжатия; `SUMMARY_CHUNK_DELAY=2.0`.
- Живой smoke apinet.cloud ✅ на проде (T-191-D): curl apinet.cloud/v1/models → валидный список моделей (auth по ключу принята).

### Low-замечания ревьюера (закрыты в T-189)

| # | Замечание | Статус (T-189) |
|---|-----------|----------------|
| L1 | XML-экранирование l2/l3-блоков (`<memory>`/`<facts>`) не реализовано | ✅ FIXED — `escape_xml_text` для `<memory>`/`<facts>` |
| L2 | Троттлинг не ловит `/summary@BotName` (команда с упоминанием бота) | ✅ FIXED — троттлинг ловит `/summary@BotName` + тесты |
| L3 | Нет жёсткого капа чанков по MAX_SUMMARY_PARTS | ⚠️ Задокументирован в README (осознанный лимит) |
| L4 | location/contact/dice классифицируются как `other` и не сохраняются | ⚠️ Задокументирован в README |

### Суть запроса (кратко)

| # | Требование |
|---|-----------|
| R1 | SQLite (aiosqlite): таблица `smart_messages` — id, user_id, chat_id, text, reply_to_id, timestamp, media_type |
| R2 | Трёхуровневая память: L1 окно 6ч (один проход) → L2 полная `FULL_MEMORY_RETENTION_DAYS` (RAG-цитаты) → L3 архив sqlite-vec (суммаризация→векторы, KNN, `ARCHIVE_MEMORY_RETENTION_DAYS`) |
| R3 | Фоллбек: sqlite-vec недоступен ИЛИ эмбеддинги падают → **FTS5**; try-except вокруг всех вызовов эмбеддингов |
| R4/R5 | LLM через **apinet.cloud**: генерация `deepseek-v4-flash`, эмбеддинги `gemini-embedding-001`; .env: LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME |
| R6 | XML-контекст: `<chat_history><message id timestamp author reply_to_id type>…</message></chat_history>` |
| R7 | Алиасы: каскад `alias → nickname → username (без @) → user_id` |
| R8 | APScheduler: TZ Asia/Yekaterinburg, 00:00/06:00/12:00/18:00, ТОЛЬКО MemoryJobStore |
| R9/R10 | Ручной `/summary` (ALLOWED_SUMMARY_IDS пуст = всем) + кастомный ThrottlingMiddleware (in-memory, молчаливый) |
| R11 | Системный промпт — захардкодить ДОСЛОВНО: токсичный «бот-абьюзер» (v4 — Epic 29: правила 6/7 — алиасы из атрибута author обязательны дословно, репосты не приписывать переславшему; пункт 3 (типографика) удалён — её чинит `cleanup_llm_text`; пункт 6 — канон пользователя дословно; ленивая печать, запрет маркдауна/эмодзи, абзацы), приписка «самым главным шизом объявляется {username}» (эталон в backlog.md, строки 1518–1539) |
| R12/R13 | `{max_symbols} = (MAX_SUMMARY_PARTS*4000)-200`; чанкинг по пробелам ≤4096; UX-ошибки на маленькой букве («не смог сделать саммари потому что упал апи», «база данных подавилась») |
| R14–R17 | Better Stack observability (стектрейсы, сырые ответы LLM); тесты + README ироничный; коммит на русском; деплой SSH nik@198.46.175.136 (/var/www/admin_bot, git pull, systemctl restart adminbot); LLM_API_KEY в .env НЕ коммитим |

### Архитектурные решения A1–A15 (Section 33, @Architect, 2026-08-16)

| # | Решение |
|---|---------|
| **A1** | Плоские модули `services/summary_*.py` + `handlers/summary.py` (НЕ подпакет `smartmodule/`) |
| **A2** | Общая `local_database.db` + миграции `_SCHEMA_SQL` (отдельный smartmodule.db отклонён) |
| **A3** | `summary_observer_router` на позиции **0a** (catch-all, всегда `UNHANDLED`) |
| **A4** | `summary_router` на позиции **0b** (ДО admin/catch-all 5/6, никогда не `UNHANDLED`) |
| **A5** | L3-сжатие — шаг пайплайна под общим `asyncio.Lock`, отдельной джобы APScheduler НЕТ |
| **A6** | Каскад памяти vec0 KNN → FTS5; факты архива пишутся в текст ВСЕГДА |
| **A7** | L2-RAG — FTS5 keyword/phrase-поиск из токенов L1 (без доп. LLM-вызова) |
| **A8** | Имена резолвятся в момент сохранения в `author_name` (alias → nickname → username → user_id) |
| **A9** | `SUMMARY_ALIASES` — JSON-строка `{"<user_id>": "<alias>"}` |
| **A10** | Промпты в `services/summary_prompts.py` (SYSTEM_PROMPT дословно, R11 v2 — Epic 27) |
| **A11** | `/summary` из чата НЕ удаляется |
| **A12** | Деплой-нота: BotFather `/setprivacy` → **Disable** (иначе память пустая — риск **Н1**) |
| **A13** | Зависимости: `httpx>=0.27`, `APScheduler>=3.10,<4`, `sqlite-vec>=0.1.2` (graceful fallback) |
| **A14** | Постобработка: чанкинг ≤4096 по пробелам + автодописывание шиз-приписки |
| **A15** | Throttling — router-scoped outer middleware только на `summary_router` (key chat+user, TTL 60s, молчаливый return) |

**Структура файлов (Section 33.2):** `services/llm_client.py`, `summary_memory.py`,
`summary_xml.py`, `summary_aliases.py`, `summary_generator.py`, `summary_scheduler.py`,
`summary_throttling.py`, `summary_prompts.py`, `handlers/summary.py` (+ точечные правки
`config/settings.py` +18 полей, `services/database.py`, `bot.py`, `.env.example`).

**БД (Section 33.3):** `smart_messages` (+author_name), FTS5 `smart_messages_fts`,
`smart_archive_facts` (+FTS5), vec0 `smart_archive` (лениво, только при загруженном sqlite-vec).

**LLM (Section 33.4):** одна httpx-сессия, `/v1/chat/completions` + `/v1/embeddings`,
retry 429/5xx с backoff, иерархия LLMError; `embed()` оборачивается try/except у вызывающего.

**Критичный риск Н1:** BotFather `/setprivacy` → **Disable** обязателен на проде (T-191) —
иначе бот в группе не видит сообщения, память L1/L2/L3 пустая.

### Финальный деплой-дайджест (T-190/T-191 DONE, 2026-08-16)

1. **T-190 ✅:** локальный прогон **835 тестов PASS**; коммит `a68732c` «feat(summary): Epic 24 — SmartModule с трехуровневой памятью и саммари чата (v2.22.0)» — 35 файлов, +4495/−28 (включая медиа leha_greeting_18-21.mp4 и olya_cringe-03.mp4, проверены); пуш master ✅ (c093de7..a68732c); docs-коммит `818e195` (синхронизация board.md) ✅; локальный HEAD = origin/master, дерево чистое; `.env` не коммичен.
2. **T-191 ✅:** прод 198.46.175.136 (/var/www/admin_bot): git pull ff `756d237..a68732c`; prod `.env` +LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME/SUMMARY_TIMEZONE (без дублей); venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1; smoke **T-191-D ✅** — curl apinet.cloud/v1/models → валидный список моделей; рестарт → active (running), PID 920105; логи чистые: «sqlite-vec loaded (dim=768)», «SmartModule Summary (Epic 24) initialized (TZ=Asia/Yekaterinburg)», cron 0,6,12,18, все 14 роутеров, трейсбеков нет.
3. **Наблюдение:** старый процесс v2.21.0 (PID 917681) завис в shutdown ~90с и был SIGKILLнут systemd — поведение старого кода; новый v2.22.0 стартует чисто.
4. **Н1 (критично, ВРУЧНУЮ пользователем — не через SSH):** BotFather `/setprivacy` → **Disable** — иначе бот в группе не видит сообщения, память L1/L2/L3 пустая. Плюс живая проверка `/summary` в чате.
5. **Политика media/** (соблюдена): медиа добавлены сознательно (leha_greeting_18-21.mp4, olya_cringe-03.mp4), закоммичены, НЕ в .gitignore, НЕ удалены.

### Baseline перед стартом Epic 24

- Прод **v2.21.0** (коммит `756d237`), бот active (PID 917681), 0 ошибок.
- **672 теста** локально; 12 роутеров (0:admin → 1:slava_presence → 1b:alan_greeting → 2:kostik → 3:alan → 4:dead_page → 4b:war_alert → 4c:common → 4d:olya → 5:slavik → 6:vasya); 5 таблиц БД.
- requirements.txt: aiogram 3.7+, python-dotenv, aiosqlite, pytest(+asyncio), sentry-sdk 2.64.0, logtail-python 0.4.0 (LLM/sqlite-vec/APScheduler/httpx отсутствуют — будут добавлены).
- Сервер: 198.46.175.136:/var/www/admin_bot, сервис adminbot (systemctl).

---

## 🔍 Context Sync Summary (2026-08-15) — Epic 22 DONE & DEPLOYED, v2.20.0 в продакшене

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-21** | ✅ DEPLOYED | 160+ задач T-001–T-162 + T2/T3/T4 + Epic 18 A/B/C. v2.19.0 (commit c683903) был в продакшене до 2026-08-15. |
| **Epic 22** | ✅ DONE & DEPLOYED | «Гонка функций и точность триггеров» — PM-решения D51–D54, T-163..T-167 (включая D) завершены. 621 тест PASS (+35 новых). Коммит `1dbb6da`, пуш, деплой. Прод v2.20.0. |
| **Review (current)** | ✅ APPROVED | 621 tests pass / 0 failed. 3 раунда ревью, все замечания закрыты (README v2.20.0/621, планы IMPLEMENTED, board «In Review»). |
| **Сервер** | ✅ ACTIVE | 198.46.175.136:/var/www/admin_bot. systemctl: active (running), PID 914116 (был 699945). Логи чистые (Bot started, listening...). HEAD=1dbb6da. |

---

## 📁 Политика media/ (по указанию пользователя, 2026-08-16) — ОБЯЗАТЕЛЬНА К ИСПОЛНЕНИЮ

> **Всё, что добавляется или удаляется в папке `media/` (`media/common/danger`, `media/olya/cringe`, `media/slavik_random` и т.п.), — делается СОЗНАТЕЛЬНО и СПЕЦИАЛЬНО для загрузки на сервер и дальнейшего использования ботом.**

- Media-файлы **НЕ являются случайными артефактами**: их НЕЛЬЗЯ исключать из коммитов как мусор, НЕЛЬЗЯ добавлять в `.gitignore`, НЕЛЬЗЯ удалять без явного указания пользователя.
- ❌ Рекомендация «добавить `danger_drone.mp4` в `.gitignore`» была **ОШИБОЧНОЙ и ОТМЕНЯЕТСЯ**.
- ✅ `media/common/danger/danger_drone.mp4` — **16-й файл danger-пула**, добавлен намеренно: его нужно **закоммитить и задеплоить**. Пул danger-медиа используется сервисом danger-слов (DangerWordFilter → CommonRelay), media_picker выбирает файлы из папки автоматически — дополнительный код не требуется.

---

## 🚧 Epic 22: Гонка функций и точность триггеров — v2.20.0 (DONE & DEPLOYED, 2026-08-15)

> **Цель:** Устранить гонку ответов Славика (приветствие vs dead page vs «пошёл нахуй»),
> сделать триггеры точнее: Olya — только SaveAsBot-видео, mimic — не передразнивать репосты,
> PostPicker — не выбирать пост, отправленный в предыдущий раз.
> **Статус:** DONE & DEPLOYED ✅ — T-163..T-167 (A/B/C/D) завершены, ревью 3 раунда (замечания закрыты), 621 тест PASS, 0 регрессий.
> Коммит `1dbb6da` на master, пуш в origin, деплой на 198.46.175.136:/var/www/admin_bot (git pull c683903..1dbb6da, 21 файл, +1778/-224, systemctl restart OK, PID 914116). Прод v2.20.0.
> **Target (достигнут):** v2.20.0, 621 тест (586 baseline + 35 новых), 0 регрессий.

### PM-решения D51–D54

| # | Решение | Задача | Суть |
|---|---------|--------|------|
| **D51** | Olya SaveAsBot-only | T-163 | Логика **ИЛИ** сохраняется (caption ИЛИ репост из `OLYA_SAVEASBOT_CHANNEL_IDS`=523131145). Дефолт `OLYA_ALWAYS_SEND` True→**False**. ⚠️ prod .env может содержать `OLYA_ALWAYS_SEND=True`. |
| **D52** | Mimic forwards gate | T-164 | Единый параметр **`MIMIC_FORWARDS_ENABLED=False`** для ОБОИХ mimic-механизмов (`handlers/common.py::mimic_handler`, `handlers/slavik.py::_slavik_mimic_should_trigger`). `forward_origin is not None` + off → mimic пропущен. |
| **D53** | Slavik race fix | T-165 | `DEAD_PAGE_POST_ON_JOIN=False` (join → только «ДОЛБОЕБ ВЕРНУЛСЯ»); dead_page_trigger — только репосты Славы (`UserIdFilter`, is_present-гейт убран); catch-all Branch 0 гейт: d_pages-репост → `UNHANDLED`. Приоритет: приветствие > dead page > «пошёл нахуй». |
| **D54** | PostPicker last-sent | T-166 | Ключ `channel_state` **`dead_page_last_sent:{chat_id}`** (≠ `last_known_message_id`). last_sent исключается из forward/sequential/random веток; fallback-повтор при единственном посте; запись primary msg_id после успеха. Фикс бага «почти всегда id 3». |

### Задачи Epic 22

| Task | Название | Компоненты | Статус |
|------|----------|-----------|--------|
| **T-163** | Olya: только SaveAsBot-видео (D51) | config/settings.py, .env.example, tests/test_olya.py | ✅ DONE (APPROVED) |
| **T-164** | Mimic: не передразнивать репосты (D52) | config/settings.py, handlers/common.py, handlers/slavik.py | ✅ DONE (APPROVED) |
| **T-165** | Славик: приоритет приветствия + dead page на репосты Славы (D53) | handlers/dead_page_trigger.py, handlers/slavik.py, tests/test_slavik_priority.py (NEW) | ✅ DONE (APPROVED) |
| **T-166** | PostPicker: не выбирать last-sent пост (D54) | services/database.py, services/dead_page_relay.py | ✅ DONE (APPROVED) |
| **T-167** | README (ироничный тон), полный pytest (621), conventional commit на русском | README/ARCHITECTURE/MEMORY | ✅ A/B/C/D DONE (APPROVED + DEPLOYED, коммит `1dbb6da`) |

### Ключевой API-контекст (Section 30.2)

- aiogram 3.x `message.forward_origin`: **None** для обычных сообщений, `MessageOriginChannel` для репостов из каналов (`origin.chat.id` — канал-источник); legacy `forward_from*` deprecated (Bot API 7.0).
- MagicMock gotcha: атрибуты автогенерируются и truthy — тестовые фабрики должны явно выставлять `msg.forward_origin = None`; гейты mock-safe через `isinstance`.
- `forwardMessage(s)` — `Bad Request: message to forward not found` = штатный признак отсутствующего пробного id → `continue`.

### Риски миграции (Section 30.9)

| # | Риск | Митигация |
|---|------|-----------|
| R1 | Prod `.env` с явными `OLYA_ALWAYS_SEND=True` / `DEAD_PAGE_POST_ON_JOIN=True` | Деплой-чеклист DevOps |
| R2 | Контракт `_try_forward_from_channel: bool → int\|None` | 9 assertion-строк в тестах обновляются в T-166 |
| R5 | Sequential scan «всегда id 3» | skip last_sent; при единственном посте — осознанный повтор |
| R7 | Миграция БД | Не нужна — переиспользуется `channel_state` |

### Результаты ревью — 3 раунда, APPROVED ✅

- 621 тест PASS / 0 failed (+35 новых: `tests/test_slavik_priority.py` NEW, классы `TestMimicForwardsGate`, `TestAntiRepeatLastSent` и др.).
- Флаки-тест `test_sequential_scan_finds_only_post` детерминирован патчем `random.randint` (side_effect [77..86], 25/25 PASS).
- Все замечания закрыты: README v2.20.0/621, статусы планов IMPLEMENTED, board «In Review», нумерация T-167 выровнена.
- Наблюдения ревьюера (не блокеры): README пишет «ДОЛБОЕВ» vs планы «ДОЛБОЕБ»; фактическая ветка — master.
- ✅ Деплой-чеклист DevOps выполнен (2026-08-15): prod `.env` → `DEAD_PAGE_POST_ON_JOIN=False` (True→False, бэкап `.env.bak.2026-08-15`); `OLYA_ALWAYS_SEND` и `MIMIC_FORWARDS_ENABLED` отсутствуют в .env — активны дефолты False.
- ❌→✅ `media/common/danger/danger_drone.mp4` — **ОТМЕНЕНО пользователем (2026-08-16):** рекомендация «добавить в `.gitignore`» была ошибочной. Файл добавлен НАМЕРЕННО (16-й файл danger-пула) → должен быть ЗАКОММИЧЕН и ЗАДЕПЛОЕН.

---

## ✅ Epic 23: Правка danger-словаря — v2.21.0 (DONE & DEPLOYED, 2026-08-16)

> **Цель:** Сократить и уточнить danger-словарь: убрать «шумные» секции, добавить фразовые шаблоны (shelter/атака), сохранить совместимость `{"matched_word"}`.
> **Статус (2026-08-16):** DONE & DEPLOYED ✅ — T-169..T-172 DONE (включая деплойные подзадачи E..G), **672 теста PASS** (621 baseline + 51 новых), ревью 2 раунда APPROVED. Деплой: git pull `0c74220..756d237` (9 файлов) на 198.46.175.136:/var/www/admin_bot; `.env` DANGER_WORDS пустой → дефолты активны; проверка «118 17» совпала; systemctl active (running) PID 917681; логи чистые. **Прод v2.21.0.**

### Факты реализации

| Параметр | Было | Стало |
|----------|------|-------|
| **DANGER_WORDS** | 191 словоформа | **118** (удалены Flight, Shelter, Атака/угроза, Падение/сбитие; добавлены хлопок/хлопки/хлопнуло/хлопнул) |
| **DANGER_PHRASES** | — | **17 фраз**: 10 shelter + 7 атака, longest-first |
| **Итого паттернов** | 191 | **135** (118 слов + 17 фраз) |

### Механика (D55–D58)

- `_build_phrase_patterns` в `DangerWordFilter` (filters/danger_word.py): фразы проверяются **ДО** слов, границы по краям фразы, `re.IGNORECASE`.
- Возврат `{"matched_word": ...}` **совместимый** — Telegram quote API не сломан.
- **Env-независимо:** дефолты в `filters/word_lists.py`; `DANGER_WORDS` env var — только опциональный override. Прод `.env` НЕ трогаем.
- Потребители: `war_alert` (роутер 4b) и `danger_handler` (роутер 4c) — единый словарь.

### Тесты — 672 PASS / 0 failed

- **672** = 621 baseline + 51 новых.
- Переписаны/добавлены: `TestDangerPhrases` (**42 кейса**), контрактный тест (**17 фраз**), негативы.
- Ревью: 2 раунда, APPROVED ✅ (2 фикса тестов выполнены дословно).

### Задачи Epic 23

| Task | Название | Статус |
|------|----------|--------|
| **T-169** | Правка DANGER_WORDS в filters/word_lists.py (191→118) | ✅ DONE + APPROVED |
| **T-170** | DANGER_PHRASES (17 фраз) в filters/word_lists.py | ✅ DONE + APPROVED |
| **T-171** | `_build_phrase_patterns` + тесты (TestDangerPhrases 42 кейса, контракт 17 фраз) | ✅ DONE + APPROVED |
| **T-172** | README/планы + коммит + деплой v2.21.0 | ✅ DONE & DEPLOYED (E..G закрыты, коммит `756d237`, PID 917681) |

---

## 🔍 Context Sync Summary (2026-08-03) — Epic 21 DEPLOYED ✅

| Area | Status | Notes |
|------|--------|-------|
| **Epics 1-20** | ✅ DEPLOYED | 130+ задач T-001–T-148 + T2/T3/T4 + Epic 18 A/B/C + Epic 19 + Epic 20. v2.18.0 в продакшене. |
| **Epic 21** | ✅ DEPLOYED | MIMIC propagation fix + Time-format cooldowns. 14 задач T-149–T-162. D49 + D50. Commit c683903. |
| **Review** | ✅ PASS | 586 tests pass. 0 failures. Zero regressions. |
| **Сервер** | ✅ ACTIVE | nik@198.46.175.136:/var/www/admin_bot. systemctl: active (running), PID 699945, 121.6M. |
| **DevOps (T-162)** | ✅ DEPLOYED | Commit c683903, push origin/master, server pull + restart successful. Zero errors in logs. |

---

## ✅ Epic 21: MIMIC Propagation Fix + Time-Format Cooldowns — v2.19.0 (DEPLOYED, 2026-08-03)

> **Цель:** Исправить propagation-блокировку в `alan_handler` (MIMIC не работал для Alan) и перевести все кулдауны на человекочитаемый time-format (1s/1m/1h/1d).
> **Статус:** DEPLOYED ✅ — все 14 задач T-149–T-162 выполнены и задеплоены в production. 586 тестов проходят.
> **Версия:** v2.19.0 (деплой на сервер выполнен).
> **Коммит:** `c683903` на master, пуш в origin/master.
> **Сервер:** nik@198.46.175.136:/var/www/admin_bot, PID 699945, active (running), 121.6M.

### Root Cause: alan_handler blocks propagation

```
Alan (138811255) пишет сообщение в чат
    ↓
alan_router (pos 3): UserIdFilter matches → alan_handler()
    → считает сообщение, возможно делает reply
    → implicit return None ← БЛОКИРУЕТ propagation
    ↓
common_router (pos 4c): НИКОГДА не получает события
    → mimic_handler НЕ срабатывает (MIMIC сломан для Alan)
    → danger_handler / otboy_handler тоже не получают
```

**SLAVIK_MIMIC НЕ затронут** — он изолирован в `slavik_router` (позиция 5), который получает события независимо от `alan_router`.

### Design Decisions — IMPLEMENTED

| # | Решение | Описание | Статус |
|---|---------|----------|--------|
| **D49** | return UNHANDLED в alan_handler | Добавить `from aiogram.dispatcher.event.bases import UNHANDLED` + `return UNHANDLED` в конце `alan_handler()` И в ранних return (строки 84, 89). 1 файл (`handlers/alan.py`), 3 строки изменения. | ✅ IMPLEMENTED |
| **D50** | Time-format cooldowns | Новые хелперы `_parse_duration()` и `_env_duration()` в `config/settings.py`. Поддерживаемые форматы: `1s`, `30s`, `1m`, `5m`, `1h`, `2h`, `1d`, `0`. Переименование 6 полей: `*_COOLDOWN_SECONDS` → `*_COOLDOWN`. Backward-compat через fallback для plain integer значений. | ✅ IMPLEMENTED |

### Cooldown Renames — COMPLETED

| Старое имя | Новое имя | Новый Default | Было |
|-----------|----------|---------------|------|
| `MIMIC_COOLDOWN_SECONDS` | `MIMIC_COOLDOWN` | `"1h"` (3600s) | `60.0` |
| `SLAVIK_MIMIC_COOLDOWN_SECONDS` | `SLAVIK_MIMIC_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `COMMON_COOLDOWN_SECONDS` | `COMMON_COOLDOWN` | `"0"` (disabled) | `0` |
| `DEAD_PAGE_COOLDOWN_SECONDS` | `DEAD_PAGE_COOLDOWN` | `"10s"` (10s) | `10` |
| `DANGER_COOLDOWN_SECONDS` | `DANGER_COOLDOWN` | `"60s"` (60s) | `60.0` |
| `OLYA_COOLDOWN_SECONDS` | `OLYA_COOLDOWN` | `"60s"` (60s) | `60.0` |

### Tasks Epic 21 — IMPLEMENTED

| Task | Название | Компонент | Статус |
|------|----------|-----------|--------|
| **T-149** | MIMIC propagation fix — `return UNHANDLED` в `alan_handler` (3 места: line 84, 89, end) | `handlers/alan.py` | ✅ IMPLEMENTED |
| **T-150** | Создать `_parse_duration()` и `_env_duration()` хелперы | `config/settings.py` | ✅ IMPLEMENTED |
| **T-151** | Переименовать 6 cooldown полей в Settings dataclass | `config/settings.py` | ✅ IMPLEMENTED |
| **T-152** | Обновить `bot.py` — переименовать вызовы `settings.*_COOLDOWN` | `bot.py` | ✅ IMPLEMENTED |
| **T-153** | Обновить `handlers/slavik.py` — `SLAVIK_MIMIC_COOLDOWN` | `handlers/slavik.py` | ✅ IMPLEMENTED |
| **T-154** | Обновить `services/dead_page_relay.py` — `DEAD_PAGE_COOLDOWN` | `services/dead_page_relay.py` | ✅ IMPLEMENTED |
| **T-155** | Verify mimic_relay + common_relay — без внутренних изменений | `services/*.py` | ✅ IMPLEMENTED (verified, no changes) |
| **T-156** | Добавить тест UNHANDLED в `alan_handler` | `tests/test_alan.py` | ✅ IMPLEMENTED |
| **T-157** | Обновить `.env.example` — time-format defaults | `.env.example` | ✅ IMPLEMENTED |
| **T-158** | Создать `tests/test_duration.py` — 15 test cases | `tests/test_duration.py` (NEW) | ✅ IMPLEMENTED |
| **T-159** | Полный прогон тестов — 586 tests PASS, 0 failures | `pytest` | ✅ IMPLEMENTED |
| **T-160** | Обновить `README.md` — version v2.19.0, config table, 586 tests | `README.md` | ✅ IMPLEMENTED |
| **T-161** | Sync MEMORY.md — Epic 21 completion status | `plans/` | ✅ IMPLEMENTED |
| **T-162** | Commit, push, deploy | DevOps | ✅ DEPLOYED (commit c683903, server: PID 699945) |

### Reviewer Audit — 3 Issues Found, ALL FIXED

| # | Severity | Описание | Файл | Status |
|---|----------|----------|------|--------|
| **1** | HIGH | `.env` line 26: `DEAD_PAGE_COOLDOWN_SECONDS=0` → `DEAD_PAGE_COOLDOWN=0` (старое имя поля) | `.env` | ✅ FIXED |
| **2** | HIGH | `handlers/alan.py` lines 84, 89: Early returns `return` → `return UNHANDLED` (блокировали propagation на ранних выходах) | `handlers/alan.py` | ✅ FIXED |
| **3** | MEDIUM | `.env`: Missing new cooldown variables (COMMON_COOLDOWN, DANGER_COOLDOWN, MIMIC_COOLDOWN, SLAVIK_MIMIC_COOLDOWN, OLYA_COOLDOWN) | `.env` | ✅ FIXED |

### Affected Files — IMPLEMENTED

| Файл | Тип | Изменения |
|------|-----|-----------|
| `config/settings.py` | MODIFY | +2 хелпера (`_parse_duration`, `_env_duration`), 6 переименований полей, тип float→str |
| `handlers/alan.py` | MODIFY | +import UNHANDLED, +return UNHANDLED (3 строки: lines 84, 89, end) |
| `bot.py` | MODIFY | ~6 строк переименований `*_COOLDOWN_SECONDS` → `*_COOLDOWN` |
| `handlers/slavik.py` | MODIFY | 1 строка переименования `SLAVIK_MIMIC_COOLDOWN` |
| `services/dead_page_relay.py` | MODIFY | 2 строки переименования `DEAD_PAGE_COOLDOWN` |
| `services/mimic_relay.py` | VERIFIED | БЕЗ ИЗМЕНЕНИЙ — внутренние параметры `cooldown_seconds` не переименованы |
| `services/common_relay.py` | VERIFIED | БЕЗ ИЗМЕНЕНИЙ — внутренние параметры `cooldown_seconds`/`danger_cooldown_seconds` не переименованы |
| `.env.example` | MODIFY | 6 переменных переименованы с time-format значениями + комментарий |
| `.env` | MODIFY | Reviewer fixes: DEAD_PAGE_COOLDOWN + missing vars |
| `README.md` | MODIFY | v2.19.0, config table sync, 586 tests |
| `tests/test_alan.py` | MODIFY | +1 тест (UNHANDLED return) |
| `tests/test_duration.py` | **CREATE** | 15 тестов `_parse_duration` + `_env_duration` |

### Test Suite (586 total)

| Area | Count | Delta |
|------|-------|-------|
| Baseline (Epic 20 deployed) | 570 | — |
| Epic 21: test_alan.py (UNHANDLED) | +1 | T-156 |
| Epic 21: test_duration.py (NEW) | +15 | T-158 |
| **Total** | **586** | **+16 net** |

### Architectural Decisions Summary

| # | Решение | Описание | Статус |
|---|---------|----------|--------|
| **D49** | return UNHANDLED in alan_handler | 3 return paths updated (end + 2 early returns). Propagation restored. | ✅ IMPLEMENTED |
| **D50** | Time-format cooldowns | `_parse_duration`(s/m/h/d) + `_env_duration` with backward-compat. 6 fields renamed. | ✅ IMPLEMENTED |

---

## 📋 Project Overview

**AdminBot** — юмористический Telegram-бот для личного чата трёх друзей (Слава, Костик, Вася).  
Написан на **Python** с использованием **aiogram 3.x**. Работает через long-polling.

### Стек
| Компонент | Технология | Статус |
|-----------|-----------|--------|
| Рантайм | Python 3.x + asyncio | ✅ |
| Фреймворк | aiogram 3.7+ | ✅ |
| База данных | SQLite (local_database.db) | ✅ 9 таблиц после Epic 24 (было 5), WAL mode |
| Конфигурация | .env + config/settings.py | ✅ Все настройки через env, time-format cooldowns |
| Тесты | pytest + pytest-asyncio | ✅ 860 тестов локально PASS (Epic 25 DEPLOYED; прод v2.23.0-fix) |
| Документация | ARCHITECTURE.md, MEMORY.md | ✅ |
| Мониторинг | ✅ Sentry + Logtail | Error tracking + cloud logging via Better Stack |

### Пользователи чата

| Персона | User ID | Прозвище | Роутер |
|---------|--------|----------|--------|
| **Слава (Slavik)** | `479167456` | «Куча» | `handlers/slavik.py` |
| **Костик (Kostik)** | `350803143` | — | `handlers/kostik.py` |
| **Вася (Vasya)** | no ID | — | `handlers/vasya.py` |
| **@Alan_Z** | `138811255` | — | `handlers/alan.py` (F6 + F7v2) + `handlers/alan_greeting.py` (F7) |
| **Admin** | `5885953495` | — | `handlers/admin_commands.py` (Epic 9) |

---

## 🏗️ Key Architectural Decisions

### 1. Router Priority Order (КРИТИЧНО — v2.22.0)
```
0a. summary_observer_router — Epic 24: catch-all сбор ВСЕХ сообщений в память (всегда UNHANDLED)
0b. summary_router — Epic 24: /summary (ДО admin и catch-all 5/6, никогда UNHANDLED) + ThrottlingMiddleware
0.  admin_commands_router (Command filters) — /deadpage, /alangreet
1.  ChatMemberUpdated (slava_presence_router) — F1
1b. ChatMemberUpdated (alan_greeting_router) — F7: Alan join → greeting video
2.  kostik_router (user_id=350803143)
3.  alan_router (user_id=138811255) + DB counter — F6 + F7v2 silence greeting
    → RETURNS UNHANDLED (D49) — propagation restored for Alan
4.  dead_page_router — Dead Page V2 trigger from @d_pages
4b. war_alert_router — F5v2: war keywords (Slava) + TargetChannelFilter repost detection
4c. common_router — F9/F10: otboy_handler + danger_handler + mimic_handler (ALL users, DUAL cooldown)
4d. olya_router — F11: Olya video trigger (user_id=834424825) + plain send media
5.  slavik_router (user_id=479167456) + middleware F3 + F4 + catch-all + slavik_mimic (F8)
6.  vasya_router (text filters, no user restriction)
```

### 2. Фичи (F1–F11)

| # | Фича | Реализация | Статус |
|---|------|------------|--------|
| **F1** | Детект возвращения Славы → «ДОЛБОЕБ ВЕРНУЛСЯ» | `handlers/slava_presence.py` | ✅ |
| **F2** | Dead Page V2: forwardMessage из @d_pages + fallback | `DeadPageRelay` + `DeadPageTrigger` | ✅ |
| **F3** | GIF каждые 5 сообщений Славы | `MessageCounterMiddleware` | ✅ |
| **F4** | «КУЧА» → «ДАЛБАЕБ» | `handlers/slavik.py` + `KuchaWordFilter` | ✅ |
| **F5v2** | War Words Alert: caption fix, 90+ keywords, TargetChannelFilter, random replies | `handlers/war_alert.py` | ✅ |
| **F6** | @Alan_Z → random reply каждые 10 сообщений | `handlers/alan.py` (returns UNHANDLED) | ✅ |
| **F7** | Alan join → random greeting video | `handlers/alan_greeting.py` | ✅ |
| **F7v2** | Alan silence greeting — "Леха проснулся" | `handlers/alan.py` (inlined, returns UNHANDLED) | ✅ |
| **F8** | slavic_na_litso.jpg — каждый N-й "пошёл нахуй" → фото | `handlers/slavik.py` | ✅ |
| **E9** | Admin test commands: /deadpage, /alangreet | `handlers/admin_commands.py` | ✅ |
| **F9** | Otboy Service — детект "отбой" → common/otboy/ media | `handlers/common.py` (otboy_handler) + `CommonRelay` | ✅ |
| **F10** | Danger Detection — 135+ keywords from word_lists.py | `handlers/common.py` (danger_handler) + `DangerWordFilter` + `CommonRelay` (dual cooldown) | ✅ |
| **F11** | Olya Service — видео от @ole4444444ka → cringe media | `handlers/olya.py` + `OlyaRelay` + `OlyaVideoFilter` | ✅ |

### 3. Database Schema (SQLite, 9 tables после Epic 24)

| Таблица | Назначение | Ключевые колонки |
|---------|-----------|-----------------|
| `user_presence` | Присутствие пользователя (F1, F2) | `user_id`, `chat_id`, `is_present` |
| `message_counters` | Счётчик сообщений (F3, F6) | `chat_id`, `user_id`, `count` |
| `dead_page_posts` | Учёт dead-page постов (F2 V2) | `chat_id`, `slot`, `timestamp` |
| `channel_state` | Ключ-значение (F2 V2, F7v2) | `key` (TEXT PK), `value` (TEXT) |
| `relay_album_map` | Трекинг media_group_id для альбомов (Epic 14) | `message_id` (INTEGER PK), `media_group_id` (TEXT, INDEXED) |
| `smart_messages` | Сырые сообщения чата (Epic 24, L1/L2) | `id`, `chat_id`, `user_id`, `author_name`, `text`, `reply_to_id`, `media_type`, `timestamp` |
| `smart_messages_fts` | FTS5-индекс сообщений (L2-RAG) | `text`, content=`smart_messages` |
| `smart_archive_facts` | Факты L3-сжатия (текстовая ветка, ВСЕГДА) | `id`, `chat_id`, `fact`, `timestamp` |
| `smart_archive_facts_fts` | FTS5-индекс фактов (фоллбек L3) | `fact`, content=`smart_archive_facts` |
| `smart_archive` | vec0-векторная ветка L3 (лениво) | `rowid`, `fact_id`, `chat_id`, `embedding float[768]` |

### 4. Config (env-configurable via settings.py, TIME-FORMAT v2.19.0)

| Переменная | По умолчанию | Назначение |
|-----------|-------------|------------|
| `API_TOKEN` | (required) | Telegram Bot Token |
| `SLAVIK_USER_ID` | `479167456` | Slava's Telegram user ID |
| `KOSTIK_USER_ID` | `350803143` | Kostik's Telegram user ID |
| `ALAN_USER_ID` | `138811255` | Alan's Telegram user ID |
| `ALAN_SILENCE_GREETING_HOURS` | `6.0` | F7v2: hours of silence before greeting (prod=2) |
| `ADMIN_USER_ID` | `5885953495` | Admin user ID (Epic 9) |
| `GIF_INTERVAL` | `5` | Send GIF every N messages |
| `GIF_PATH` | `media/slavic_chlen.mp4` | GIF file path |
| `WAR_CHANNEL_IDS` | `1654872411` | War repost detection channel IDs (F5v2) |
| `WAR_CHANNEL_USERNAMES` | `` | War repost detection channel usernames (F5v2) |
| `WAR_REPLIES` | `` | Custom war reply phrases (F5v2) |
| `SLIVIC_NA_LITSO_INTERVAL` | `10` | F8: каждый N-й "пошёл нахуй" → фото |
| `MIMIC_COOLDOWN` | `1h` | F6: MIMIC cooldown (time-format: 1s/1m/1h/1d) ✅ v2.19.0 |
| `SLAVIK_MIMIC_COOLDOWN` | `60s` | F8: Slavik MIMIC cooldown (time-format) ✅ v2.19.0 |
| `COMMON_COOLDOWN` | `0` | F9/F10: shared cooldown for common sub-services (0=off, time-format) ✅ v2.19.0 |
| `DANGER_COOLDOWN` | `60s` | F10: danger-specific cooldown (dual-layer, time-format) ✅ v2.19.0 |
| `DEAD_PAGE_COOLDOWN` | `10s` | F2 V2: dead page relay cooldown (time-format) ✅ v2.19.0 |
| `OLYA_COOLDOWN` | `60s` | F11: Olya service cooldown (time-format) ✅ v2.19.0 |
| `COMMON_MEDIA_BASE` | `media/common` | F9/F10: base directory for common/otboy/ and common/danger/ |
| `DANGER_WORDS` | `(135+ keywords)` | F10: comma-separated danger keywords (единый источник: filters/word_lists.py) |
| `OLYA_ENABLED` | `True` | F11: enable/disable Olya Service (0=off) |
| `OLYA_USER_ID` | `834424825` | F11: Olya's Telegram user ID (@ole4444444ka) |
| `OLYA_MEDIA_BASE` | `media/olya/cringe` | F11: media directory for Olya cringe files |
| `OLYA_CAPTION_TEXT` | `(SaveAsBot text)` | F11: key caption text for Condition A detection |
| `OLYA_SAVEASBOT_CHANNEL_IDS` | `523131145` | F11: channel IDs for SaveAsBot repost detection |
| `OLYA_ALWAYS_SEND` | `False` | F11: always send media regardless of caption/repost match ✅ v2.20.0 IMPLEMENTED (Epic 22 D51: дефолт True→False) |
| `MIMIC_FORWARDS_ENABLED` | `False` | Epic 22 D52 (NEW) ✅ v2.20.0 IMPLEMENTED: mimic только обычные сообщения; True = включая репосты (forward_origin is not None) |
| `DEAD_PAGE_POST_ON_JOIN` | `False` | Epic 22 D53 ✅ v2.20.0 IMPLEMENTED: при входе только «ДОЛБОЕБ ВЕРНУЛСЯ» (dead page на join выключен) |
| `dead_page_last_sent:{chat_id}` | — (channel_state) | Epic 22 D54 ✅ v2.20.0 IMPLEMENTED: anti-repeat ключ БД — PostPicker не выбирает последний отправленный пост |

---

## Previous Completed Epics

| Version | Date | Epic | Tasks | Tests |
|---------|------|------|-------|-------|
| v1.0.0 | 2026-07-07 | Epic 1-4 | T-001–T-017 | 130 |
| v2.0.0 | 2026-07-12 | Epic 6 (Dead Page V2) | T-018–T-028 | 137 |
| v2.1.0 | 2026-07-12 | Epic 7 (Monitoring) | T-029–T-037 | 146 |
| v2.2.0 | 2026-07-13 | Epic 8 (F7 Alan Greeting) | T-038–T-045 | 164 |
| v2.3.0 | 2026-07-14 | Bugfixes T-046–T-047 | T-046–T-047 | 32 |
| v2.4.0 | 2026-07-14 | Epic 9 (Admin Commands) | T-048–T-051 | 181 |
| v2.5.0 | 2026-07-14 | T-052 (Sequential Scan) | T-052 | 185 |
| v2.6.0 | 2026-07-15 | T-053 (Propagation Fix) | T-053 | 190 |
| v2.7.0 | 2026-07-16 | Epic 10 (F5v2 War Words) | T-054–T-063 | 252 |
| v2.8.0 | 2026-07-18 | Epic 11 (F7v2) | T-064–T-077 | 271 |
| v2.9.2 | 2026-07-26 | Epic 12 (F8) | T-078–T-083 | 280 |
| v2.10.0 | 2026-07-26 | Epic 13 (F9 Otboy) | T-084–T-092 | 305 |
| v2.11.0 | 2026-07-28 | Epic 14 (Album Fix) | T-093–T-099 | 316 |
| v2.12.0 | 2026-07-28 | Epic 15 (Common Service) | T-100–T-107 | 372 |
| v2.12.1 | 2026-07-29 | Epic 16 (Bug Fixes) | T-109–T-115 | 387 |
| v2.13.0 | 2026-07-30 | Epic 17 (Danger Word Fix) | T2–T4 | 399 |
| v2.15.0 | 2026-08-02 | 4 Major Fixes | — | 458 |
| v2.16.0 | 2026-08-02 | Epic 18 (Danger Service Fixes) | A/B/C | 478 |
| v2.17.0 | 2026-08-02 | Epic 19 (Olya Service) | T-131–T-138 | 509 |
| v2.18.0 | 2026-08-02 | Epic 20 (Slavik Random Media) | T-139–T-148 | 570 |
| **v2.19.0** | **2026-08-03** | **Epic 21 (MIMIC fix + Time-format cooldowns)** | **T-149–T-162** | **586** |
| **v2.20.0** | **2026-08-15** | **Epic 22 (Гонка функций и точность триггеров)** | **T-163–T-167 (DEPLOYED, `1dbb6da`)** | **621** |
| **v2.21.0** | **2026-08-16** | **Epic 23 (Правка danger-словаря)** | **T-169–T-172 (DONE & DEPLOYED, `756d237`)** | **672** |
| **v2.22.0** | **2026-08-16** | **Epic 24 (SmartModule: Summary)** | **T-173–T-191 (DONE & DEPLOYED, `a68732c` + `818e195`)** | **835** |
| **v2.23.0-fix** | **2026-08-16** | **Epic 25 (багфикс /summary + удаление команды)** | **T-192–T-198 (7/7 Done & DEPLOYED, `c364f18` + `2a45f79`)** | **860** |
| **v2.24.0** | **2026-08-16** | **Epic 26 (GraphRAG-память)** | **T-199–T-206 (DONE & DEPLOYED, `7c7c241`)** | **939** |
| **v2.25.0** | **2026-08-16** | **Epic 27 (промпт v2 + SUMMARY_ALIASES)** | **T-207–T-210 (DONE & DEPLOYED, `1d7bed4`)** | **939** |
| **v2.26.0** | **2026-08-16** | **Epic 28 (Качество памяти: векторы/репосты/алиасы/очистка)** | **T-211–T-220 (DONE & DEPLOYED, `ac80ce8`)** | **995** |
| **v2.27.0** | **2026-08-16** | **Epic 29 (UX-полировка: удаление команды, ack-вариации, промпт v4)** | **T-221–T-226 (DONE & DEPLOYED, `7160a33`)** | **1002** |

---

### Sprint Status

| Status | Tasks |
|--------|-------|
| **DEPLOYED** | T-001 – T-148 + T2/T3/T4 + v2.15.0 fixes + Epic 18 A/B/C (DEPLOYED across 20 Epics) ✅ |
| **DEPLOYED** | Epic 21: T-149 – T-162 (DEPLOYED, commit c683903, 586 tests pass) ✅ |
| **DEPLOYED** | Epic 22: T-163 – T-167 (DEPLOYED, commit `1dbb6da`, 621 tests pass, прод v2.20.0) ✅ |
| **DEPLOYED** | Chore T-168: danger_drone.mp4 в danger-пул — DONE & DEPLOYED ✅ (коммит `0c74220`, pull 1dbb6da..0c74220, chmod 644, хэш совпал, пул 16 файлов, PID 916795, smoke OK) |
| **DEPLOYED** | Epic 23: T-169 – T-172 (DONE & DEPLOYED ✅, коммит `756d237`, 672 теста, прод v2.21.0, PID 917681) — словарь 118 слов + 17 фраз, .env DANGER_WORDS пустой (дефолты активны), проверка «118 17» совпала, логи чистые |
| **DEPLOYED** | Epic 24: T-173 – T-191 (DONE & DEPLOYED ✅, коммит `a68732c` + docs `818e195`, 835 тестов, прод v2.22.0, PID 920105, smoke apinet.cloud OK) — Н1 BotFather `/setprivacy` → Disable остаётся ручным действием пользователя |
| **DEPLOYED** | Epic 25: T-192 – T-198 (DONE & DEPLOYED ✅, коммит `c364f18` + docs `2a45f79`, 860 тестов, прод v2.23.0-fix, PID 923954) — B1–B9 в проде; живой тест /summary остаётся ручной верификацией пользователя |
| **DEPLOYED** | Epic 27: T-207 – T-210 (DONE & DEPLOYED ✅, коммит `1d7bed4`, 939 тестов, прод v2.25.0, PID 934174) — SYSTEM_PROMPT v2 + SUMMARY_ALIASES 36 пар (бэкап .env.bak.epic27), AliasResolver OK, 0 traceback |
| **DEPLOYED** | Epic 28: T-211 – T-220 (DONE & DEPLOYED ✅, коммит `ac80ce8`, 995 тестов, прод v2.26.0, PID 936542) — репосты/алиасы/векторное автолечение (768→3072 штатно)/cleanup/SYSTEM_PROMPT v3; .env не тронут, 0 traceback |
| **DEPLOYED** | Epic 29: T-221 – T-226 (DONE & DEPLOYED ✅, коммит `7160a33`, 1002 теста, прод v2.27.0, PID 937634) — удаление команды ДО ack (D81), пул 20 ack-фраз (D82), SYSTEM_PROMPT v4 (D83/D84, канон пользователя дословно); .env не тронут, 0 traceback, dim=3072 |

> Epics 1-22 ALL DEPLOYED ✅ (v2.20.0, commit `1dbb6da`, PID 914116). **Epic 22 «Гонка функций и точность триггеров» DONE & DEPLOYED ✅ — реализация (D51–D54) + ревью 3 раунда (APPROVED) + коммит/пуш/деплой (T-167-D).**
> 621 тест. 11 роутеров, 5 таблиц БД, Sentry + Logtail мониторинг.
> MIMIC propagation FIXED. All 6 cooldowns in time-format (1s/1m/1h/1d).
> Epic 22 реализовано и задеплоено: D51 (Olya SaveAsBot-only, OLYA_ALWAYS_SEND=False), D52 (MIMIC_FORWARDS_ENABLED=False), D53 (Slavik race fix, DEAD_PAGE_POST_ON_JOIN=False), D54 (PostPicker last-sent). v2.20.0, 621 тест.

---

## 🚀 Deployment Details

| Параметр | Значение |
|----------|----------|
| **Версия в проде** | **v2.27.0** (Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 — DEPLOYED; dim=3072, 0 traceback) |
| **Текущий коммит** | `7160a33` (feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)); прод HEAD после pull ff `ac80ce8..7160a33` (docs-коммит ccfad99 на проде не было — не критично) |
| **Дата** | 2026-08-17 |
| **Сервер** | 198.46.175.136 |
| **Путь** | /var/www/admin_bot |
| **Статус** | systemctl status adminbot → active (running), PID 937634 (был 936542), 0 traceback после рестарта; «Dimension mismatch» отсутствует (штатный WARNING автолечения «EMBEDDING_DIM=768 != actual API dim=3072 — using actual» остаётся); SUMMARY_ALIASES 36 пар OK, WARNING «invalid JSON» отсутствует; sqlite-vec dim=3072 |
| **Git remote** | origin (github.com/Henry-Case-dev/adminbot.git) — pushed успешно (`ac80ce8..7160a33`), локальный HEAD = origin/master |
| **Тесты** | 1002 PASS (995 baseline + 7 Epic 29; 0 failed, 0 skipped) |
| **Эпики** | 1-29 ALL DEPLOYED ✅ |
| **Epic 25** | T-192–T-198 Done & DEPLOYED (860 тестов, коммит `c364f18`, PID 923954). Финальная живая верификация /summary — по логам после теста пользователем |
| **Epic 26** | GraphRAG-память — **DEPLOYED (Шаг 8 @Memory)**, коммит `7c7c241`, v2.24.0, 939 тестов (860+73+6), T-199–T-206 Done, T-206 (P1) fixed в этом же релизе |
| **Epic 27** | Промпт v2 + SUMMARY_ALIASES — **DEPLOYED (Шаг 8 @Memory)**, коммит `1d7bed4`, v2.25.0, 939 тестов, T-207–T-210 Done, прод PID 934174, 0 traceback, AliasResolver распарсил 36 пар |
| **Epic 28** | Качество памяти — **DEPLOYED (Шаг 8 @Memory)**, коммит `ac80ce8`, v2.26.0, 995 тестов (939+56), T-211–T-220 ALL DONE, прод PID 936542, автолечение 768→3072 штатно (facts kept), 0 traceback |
| **Epic 29** | UX-полировка — **DEPLOYED (Шаг 8 @Memory)**, коммит `7160a33`, v2.27.0, 1002 теста (995+7), T-221–T-226 ALL DONE, прод PID 937634, канон пользователя дословно (D83), зазор-нумерация сохранён (D84; ⚠️ СУПЕРСЕД D90, Epic 30), 0 traceback |
| **Задачи** | T-001 – T-226 ALL DEPLOYED ✅ |
| **.env на проде** | **НЕ тронут при деплое Epic 29** (изменений env в релизе нет) и при деплое Epic 28 (автолечение починило размерность само); +SUMMARY_ALIASES (36 пар id-имя, бэкап `.env.bak.epic27`, JSON OK, sha1 совпал с репо); +GRAPH_RAG_ENABLED=True, GRAPH_EDGE_WEIGHT_INCREMENT=1, GRAPH_TOP_EDGES_LIMIT=5, GRAPH_EXTRACT_MAX_TRIPLETS=50 (бэкап `.env.bak.epic26`); +LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME/SUMMARY_TIMEZONE (с Epic 24); DANGER_WORDS пустой → дефолты; DEAD_PAGE_POST_ON_JOIN=False; OLYA_ALWAYS_SEND и MIMIC_FORWARDS_ENABLED — дефолты False |
| **Ошибки** | 0 errors, 0 трейсбеков, ImportError 0. Все сервисы инициализированы корректно. |
| **Backlog-кандидаты (pre-existing)** | ~~(а) L3 dimension mismatch: эмбеддинги 3072 dim vs БД 768 → vector search failed → FTS5 fallback~~ — **ИСПРАВЛЕНО Epic 28: VecAutoHeal сработал на проде (DROP smart_archive один раз, пересоздание под 3072, smart_archive_facts целы), «Dimension mismatch» отсутствует**; (б) stop-timeout systemd при рестарте (~90-95с → SIGKILL, сервис поднимается корректно); (в) **SIGTERM graceful shutdown** — бот не отвечает на SIGTERM, рекомендуется отдельный тикет; (г) **journalctl требует sudo для nik** (ника в adm/systemd-journal нет) — не блокер |
| **Ручные действия** | Живой тест `/summary` в чате (порядок «command deleted → ack sent» проверится на первом реальном вызове — не блокер); Н1: BotFather `/setprivacy` → Disable (критично); при WARNING удаления — выдать боту админ-права `delete_messages` |

---

*Обновление: 2026-08-17 — EPIC 29 (UX-полировка: удаление команды, ack-вариации, промпт v4, v2.27.0): DEPLOYED ✅ (Шаг 8, @Memory — ФИНАЛЬНАЯ синхронизация, весь цикл воркфлоу 0–8 закрыт). @DevOps: T-226 DONE — коммит `7160a33` «feat(summary): Epic 29 — UX-полировка: удаление команды, ack-вариации, промпт v4 (v2.27.0)» (9 файлов, +541/−125) запушен в origin/master (github.com/Henry-Case-dev/adminbot.git); деплой на прод 198.46.175.136 (/var/www/admin_bot): git pull ff `ac80ce8..7160a33` (прод был на ac80ce8 — docs-коммит ccfad99 на проде не было, не критично); .env НЕ тронут; systemctl restart admin_bot → active (running), PID 937634 (был 936542); 0 traceback; «Dimension mismatch» НЕТ (штатный WARNING автолечения остаётся); «SUMMARY_ALIASES invalid JSON» НЕТ; sqlite-vec dim=3072. Канон-правка пункта 6 пользователя вошла ДОСЛОВНО; Builder восстановил только номера пунктов 4/5/6/7 (зазор D84; ⚠️ СУПЕРСЕД D90, Epic 30 — нумерация станет 1–6) — текст канона НЕ тронут. Ручных /summary за окно наблюдения не было — порядок «command deleted → ack sent» (D81/D82) проверится на первом реальном вызове (не блокер). Тесты: 1002 passed (995 + 7), ревью PASS. T-221…T-226 ALL DONE. Известное неблокирующее: journalctl требует sudo для nik. ЭПИК 29 ЗАКРЫТ: Epics 1–29 ALL DEPLOYED, прод v2.27.0 (7160a33, PID 937634). MEMORY.md обновлён локально — docs-коммит сделает Orchestrator отдельно (@Memory код не трогает и не коммитит).*

*Обновление: 2026-08-16 — EPIC 28 (Качество памяти: векторы, репосты, алиасы, очистка, v2.26.0): DEPLOYED ✅ (Шаг 8, @Memory — ФИНАЛЬНАЯ синхронизация, весь цикл воркфлоу 0–8 закрыт). @DevOps: T-220 DONE — коммит `ac80ce8` «feat(summary): Epic 28 — качество памяти: репосты, алиасы, векторное автолечение и cleanup (v2.26.0)» запушен в origin/master (18 файлов: 2 новых — services/summary_cleanup.py, tests/test_summary_cleanup.py; 16 изменённых). Деплой на прод 198.46.175.136 (/var/www/admin_bot): git pull ff `1d7bed4..ac80ce8`; .env НЕ тронут; systemctl restart admin_bot → active (running), новый PID 936542 (был 934174); 0 traceback. Автолечение сработало ШТАТНО на первом старте: «EMBEDDING_DIM=768 != actual API dim=3072 — using actual»; «vec dimension mismatch (stored=768, actual=3072) — dropping smart_archive (facts in smart_archive_facts are kept)»; «sqlite-vec loaded (dim=3072)». smart_archive_facts сохранён. «Dimension mismatch» как ошибка отсутствует. WARNING «SUMMARY_ALIASES invalid JSON» отсутствует. Тесты: 995 passed (939 + 56). Ревью PASS. Все задачи T-211…T-220 DONE. Теперь новые сообщения векторизируются в 3072 корректно, репосты маркируются, алиасы резолвятся на лету, ответы LLM чистятся от ёлочек/тире. ЭПИК 28 ЗАКРЫТ: Epics 1–28 ALL DEPLOYED, прод v2.26.0. MEMORY.md обновлён локально — docs-коммит решит Orchestrator отдельно (как в прошлых эпиках).*

*Обновление: 2026-08-16 — EPIC 28 (Качество памяти: векторы, репосты, алиасы, очистка, v2.26.0): IMPLEMENTED + REVIEW PASSED ✅ (Шаг 6, @Memory — граф знаний и MEMORY.md синхронизированы, коммита НЕТ). @Builder: T-211…T-219 DONE — миграция smart_messages (+is_forward/forward_source в конец, ALTER в initialize() try/except OperationalError, save_smart_message +2 kw в конец, 3 SELECT дополнены, девиация: хелпер row_get() — sqlite3.Row без .get); observer forward_origin (getattr-защита, _extract_forward_source по 4 типам origin, алиасы для User, обрезка 100, try/except); XML-атрибуты is_forward/forward_source в конец тега + ре-резолв алиасов на лету ВСЕГДА; генератор (_resolve_author/_format_l2_quote/_most_active_author(rows, aliases=None) через getattr + cleanup_llm_text после generate ДО _ensure_shiz_postfix; девиация: .replace на строке 115 из-за сдвига от импорта); _build_batch_text с репост-маркерами «[Оля (репост из "Канал X")]: текст»; векторное автолечение (probe→actual_dim, DDL-разбор→stored_dim, DROP smart_archive ТОЛЬКО при stored≠actual, факты целы, _vec_available=False при INSERT-mismatch, пустой KNN→FTS5, WARNING непарсируемого DDL); SYSTEM_PROMPT v3 (правила 6/7, байт-в-байт == backlog; с Epic 29 v4 — 1518–1539, 22 строки, хелпер lines[1517:1539]); services/summary_cleanup.py (6 пар замен). @Reviewer: PASS, 4 non-blocking закрыты (board.md статусы, ARCHITECTURE «6 пар замен», WARNING непарсируемого DDL, docstring row_get). Тесты: 995 passed (939 baseline + 56 новых; девиация: 56 вместо 58), 0 failed, 0 skipped, git diff --check чист. Остаток: T-220 (@DevOps) — коммит на русском feat(summary): Epic 28 — … (v2.26.0), 12–13 файлов; деплой: git pull → restart (~95с SIGTERM pre-existing) → логи: НЕТ «Dimension mismatch», «sqlite-vec loaded (dim=3072)», алиасы работают, DROP smart_archive выполнится ОДИН раз при 768→3072 (ожидаемо); прод .env править НЕ нужно (опционально EMBEDDING_DIM=3072 с бэкапом .env.bak.epic28).*

*Обновление: 2026-08-16 — EPIC 27 (новый системный промпт бота-абьюзера v2 + SUMMARY_ALIASES, v2.25.0): DEPLOYED ✅ (Шаг 8, @Memory — ФИНАЛЬНАЯ синхронизация, весь цикл воркфлоу 0–8 закрыт). @DevOps: T-210 DONE — коммит `1d7bed4` «feat(summary): Epic 27 — новый системный промпт бота-абьюзера v2 и SUMMARY_ALIASES (v2.25.0)» (8 файлов) запушен в origin/master. T-209 DONE — прод nik@198.46.175.136 (/var/www/admin_bot): git pull ff `7c7c241..1d7bed4`; в .env добавлена SUMMARY_ALIASES (36 пар, бэкап .env.bak.epic27, python3: JSON OK, sha1 совпал с репо); systemctl restart admin_bot → active (running), новый PID 934174 (был 926618); 0 traceback; WARNING «SUMMARY_ALIASES invalid JSON» отсутствует → AliasResolver распарсил 36 пар. Тесты 939 passed, ревью PASS. SYSTEM_PROMPT v2 байт-в-байт == backlog 1518–1538 (с Epic 29 v4 — 1518–1539) ({max_symbols} ×1, {username} ×2, подстановка .replace не тронута, COMPRESS/EXTRACT заморожены). Pre-existing не-блокер (не Epic 27): WARNING «SmartModule L3: vector search failed — FTS5 fallback» + OperationalError Dimension mismatch 3072 vs 768 (старые эмбеддинги) — FTS5-фоллбек штатный; рекомендован отдельный тикет на миграцию векторов. ЭПИК 27 ЗАКРЫТ: T-207–T-210 Done, Epics 1–27 ALL DEPLOYED, прод v2.25.0. MEMORY.md обновлён локально — docs-коммит решит Orchestrator.*

*Обновление: 2026-08-16 — EPIC 26 (GraphRAG-память, v2.24.0): DEPLOYED ✅ (Шаг 8, @Memory — ФИНАЛЬНАЯ синхронизация, весь цикл воркфлоу 0–8 закрыт). @DevOps: T-205 DONE — коммит `7c7c241` «feat(graphrag): Epic 26 — граф знаний nodes/edges, entity extraction и гибридный поиск /summary (v2.24.0)» (README с ироничным тоном + весь код Epic 26) запушен в origin/master (github.com/Henry-Case-dev/adminbot.git); деплой на прод nik@198.46.175.136 (/var/www/admin_bot): git pull fast-forward `c364f18..7c7c241`; в .env добавлены GRAPH_RAG_ENABLED=True, GRAPH_EDGE_WEIGHT_INCREMENT=1, GRAPH_TOP_EDGES_LIMIT=5, GRAPH_EXTRACT_MAX_TRIPLETS=50 (бэкап .env.bak.epic26); systemctl restart admin_bot → active (running), Main PID 926618; таблицы nodes/edges созданы в продовой БД; 0 traceback после рестарта. Тесты: 939 passed (860 baseline + 73 Epic 26 + 6 T-206); T-206 (P1, FTS-удаление медиа без подписи) исправлен в этом же релизе. Известный не-блокер (pre-existing): бот не отвечает на SIGTERM (~95с рестарт) — рекомендуется отдельный тикет graceful shutdown. ЭПИК 26 ЗАКРЫТ: T-199–T-206 Done, Epics 1–26 ALL DEPLOYED, прод v2.24.0. Ручные действия пользователя (не через SSH): живой тест /summary; Н1 BotFather /setprivacy → Disable; при WARNING удаления — админ-права delete_messages.*

*Обновление: 2026-08-16 — EPIC 24 (v2.22.0): DEPLOYED ✅ (Шаг 8, @Memory — финальная синхронизация). ВЕСЬ запрос пользователя выполнен. @DevOps: T-190 DONE (835 тестов PASS локально; коммит a68732c «feat(summary): Epic 24 — SmartModule с трехуровневой памятью и саммари чата (v2.22.0)» — 35 файлов, +4495/−28, включая медиа leha_greeting_18-21.mp4 и olya_cringe-03.mp4, проверены; пуш master c093de7..a68732c; docs-коммит 818e195 (синхронизация board.md), пуш ✅; HEAD = origin/master, дерево чистое; .env не коммичен). T-191 DONE (прод 198.46.175.136: git pull ff 756d237..a68732c; prod .env +LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME/EMBEDDING_MODEL_NAME/SUMMARY_TIMEZONE без дублей; venv +APScheduler 3.11.3/sqlite-vec 0.1.9/httpx 0.28.1; smoke T-191-D ✅ curl apinet.cloud/v1/models → валидный список моделей; restart → active (running) PID 920105; логи: «sqlite-vec loaded (dim=768)», «SmartModule Summary initialized (TZ=Asia/Yekaterinburg)», cron 0,6,12,18, 14 роутеров, трейсбеков нет). Наблюдение: старый процесс v2.21.0 (PID 917681) завис в shutdown ~90с → SIGKILL systemd (поведение старого кода, новый стартует чисто). Открытые ручные действия пользователя (не через SSH): Н1 BotFather /setprivacy → Disable (критично, иначе память L1/L2/L3 пустая); живая проверка /summary в чате. board.md: T-190 ✅ Done, T-191 ✅ Done, Epic 24 ✅ DEPLOYED (v2.22.0).*

*Обновление: 2026-08-16 — EPIC 24 (v2.22.0): IMPLEMENTED + REVIEW PASSED ✅ (Шаг 6, @Memory — граф и MEMORY.md синхронизированы). @Builder: T-174–T-188 A/B/C DONE (9 новых модулей services/summary_*.py + llm_client.py + handlers/summary.py; settings.py +24 поля; database.py _SCHEMA_SQL + 11 методов; bot.py роутеры 0a/0b + wiring; requirements.txt httpx/APScheduler 3.x/sqlite-vec; .env.example). @Reviewer T-188-D: APPROVE WITH FIXES → Approved (фиксы: await shutdown() в on_shutdown; _purge_archive rowid IN; +QA-тест test_vec_purge_removes_vectors). Тесты: 830 PASS / 0 failed (672 + 158: 147 в 9 новых файлах + 11 в test_database.py). Подтверждено: sqlite-vec 0.1.9 на Windows/Py3.12; vec0 KNN без WHERE по auxiliary-колонкам → chat-фильтр в Python; APScheduler 3.11 требует tz в CronTrigger; {username} литералом + {max_symbols} через .replace() (фикс бага 33.7). Low-замечания → T-189: XML-экранирование l2/l3-блоков; /summary@BotName не ловится троттлингом; нет капа чанков по MAX_SUMMARY_PARTS; location/contact/dice не сохраняются. Живой smoke apinet.cloud локально невозможен (ReadTimeout) → T-191-D на проде. Остаток: T-189/T-190/T-191; Н1 (BotFather /setprivacy → Disable) критичен для деплоя.*

*Обновление: 2026-08-16 — ЗАФИКСИРОВАНА ПОЛИТИКА MEDIA-ПАПКИ (указание пользователя): всё, что добавляется/удаляется в media/ (media/common/danger, media/olya/cringe, media/slavik_random и т.п.), делается СОЗНАТЕЛЬНО и СПЕЦИАЛЬНО для загрузки на сервер и использования ботом; media-файлы НЕ исключаются из коммитов как мусор, НЕ добавляются в .gitignore, НЕ удаляются без явного указания. Рекомендация «danger_drone.mp4 → .gitignore» — ОШИБОЧНАЯ, ОТМЕНЕНА. danger_drone.mp4 — 16-й файл danger-пула, добавлен намеренно. Новая chore-задача: коммит + деплой media/common/danger/danger_drone.mp4.*

*Обновление: 2026-08-15 — EPIC 22 STATUS: DONE & DEPLOYED ✅ (v2.20.0, коммит `1dbb6da`). «Гонка функций и точность триггеров» — PM-решения D51–D54 реализованы и задеплоены (Olya SaveAsBot-only / MIMIC_FORWARDS_ENABLED=False / Slavik race fix / PostPicker last-sent). Задачи T-163–T-167 (A/B/C/D) выполнены: ревью 3 раунда APPROVED, 621 тест PASS (586 baseline + 35 новых), 0 регрессий. Деплой: сервер 198.46.175.136:/var/www/admin_bot, git pull c683903..1dbb6da (21 файл, +1778/-224), systemctl restart OK, active (running), PID 914116 (был 699945), логи чистые. Prod .env: DEAD_PAGE_POST_ON_JOIN=True→False (бэкап .env.bak.2026-08-15); OLYA_ALWAYS_SEND и MIMIC_FORWARDS_ENABLED отсутствуют — дефолты False. media/common/danger/danger_drone.mp4 — добавлен намеренно (16-й файл danger-пула), к коммиту и деплою; рекомендация про .gitignore ОТМЕНЕНА пользователем (2026-08-16).*

*Предыдущий статус (2026-08-15): EPIC 22 IMPLEMENTED + APPROVED ✅ (коммит и деплой pending). T-163–T-167-C выполнены @Builder, ревью 3 раунда — APPROVED. 621 тест PASS. НЕ закоммичен/НЕ задеплоен (базовый коммит c683903 v2.19.0 в проде).*

*Предыдущий статус (2026-08-03): EPIC 21 STATUS: DEPLOYED ✅. MIMIC propagation fix (D49: return UNHANDLED in alan_handler, 3 code paths). Time-format cooldowns (D50: _parse_duration с 1s/1m/1h/1d, 6 полей переименовано). 586 тестов пасс. All 14 tasks T-149–T-162 COMPLETE + DEPLOYED. Commit c683903, push origin/master.*

*Обновление: 2026-08-16 — CHORE T-168: IN PROGRESS 🚧. PM добавил T-168 в backlog.md (T-168-A..E + AC) и board.md (In Progress, @Builder): chore — коммит + деплой `media/common/danger/danger_drone.mp4` (16-й файл danger-пула). Architect добавил Section 31 в ARCHITECTURE.md (Конвенция media/ + инвентарь пулов). Код не требуется — media_picker подхватывает файл автоматически. Ожидает @Builder: verify → коммит `chore(media): danger_drone.mp4 в danger-пул` (на русском) → push → деплой (git pull на 198.46.175.136) → verify на сервере → smoke test. Соблюдать политику media/: НЕ в .gitignore, НЕ удалять.*

*Обновление: 2026-08-16 — CHORE T-168: A/B DONE ✅, APPROVED ревьюером. Коммит `0c74220` (chore(media): danger_drone.mp4 в danger-пул) сделан и запушен в master. Состав: 1 медиа-файл + 4 plans-файла, кода нет. danger_drone.mp4 закоммичен (blob `918c9be9…`, 2 574 925 байт, ftyp isom/MP4), working tree clean. C/D/E (деплой на сервер / verify на сервере / smoke test) — PENDING. Прод пока на `1dbb6da` (v2.20.0) до деплоя.*

*Обновление: 2026-08-16 — CHORE T-168: DONE & DEPLOYED ✅. Все подзадачи A..E закрыты. Деплой: git pull на сервере fast-forward 1dbb6da..0c74220 (5 файлов: danger_drone.mp4 + 4 plans). danger_drone.mp4 на месте (2 574 925 байт), права 644, хэш 918c9be9... совпал, danger-пул = 16 файлов. systemctl restart OK: active (running), PID 916795, логи чистые. Smoke test пройден. Прод HEAD = 0c74220 (v2.20.0 + медиа).*

*Обновление: 2026-08-16 — EPIC 23: IMPLEMENTED + APPROVED ✅ (коммит/деплой PENDING). «Правка danger-словаря» — T-169..T-171 DONE: DANGER_WORDS 191→118 (удалены Flight/Shelter/Атака-угроза/Падение-сбитие; добавлены хлопок/хлопки/хлопнуло/хлопнул), новая DANGER_PHRASES=17 (10 shelter + 7 атака, longest-first). Механика: _build_phrase_patterns в DangerWordFilter — фразы→слова, {"matched_word"} совместимо, env-независимо. Тесты: 672 PASS (621+51; TestDangerPhrases 42 кейса, контракт 17 фраз, негативы). Ревью 2 раунда APPROVED (2 фикса тестов выполнены дословно). T-172 (README/доки/коммит/деплой) PENDING. Прод на 0c74220 (v2.20.0 + T-168 media). Целевая версия v2.21.0.*

*Обновление: 2026-08-16 — EPIC 23: T-172-A..D DONE ✅, деплой (E..G) PENDING — DevOps. README: v2.21.0, 672 теста, «187 словоформ» → 118 слов + 17 фраз (135 паттернов), примеры словаря (атака/угроза/прилет → фразы, добавлен хлопок), changelog «Изменено в v2.21.0 (Epic 23)» с D55–D58. backlog: T-169..T-171 [x], T-172-A..D [x], деплой [ ]; статус Epic 23 → IMPLEMENTED (APPROVED, деплой pending). board: Epic 23 → In Review с пометкой «APPROVED, деплой pending», футер синхронизирован. Коммит feat(danger) на master + push в origin. Состав: word_lists.py, danger_word.py, test_filters.py, test_common.py, README.md, ARCHITECTURE.md, MEMORY.md, backlog.md, board.md. Прод на 0c74220 (v2.20.0 + T-168 media).*

*Обновление: 2026-08-16 — EPIC 23: IN PROGRESS 🚧 (СПЛАНИРОВАН, целевая версия v2.21.0). PM и Architect спланировали Epic 23 «Правка danger-словаря»: решения D55–D58, задачи T-169..T-172. DANGER_WORDS: 118 словоформ (было 191) — удалены секции Flight (10), Shelter (26), Атака/угроза (28), Падение/сбитие (13); добавлены хлопок/хлопки/хлопнуло/хлопнул. Новая DANGER_PHRASES (17 фраз: 10 shelter + 7 атака). Механика: _build_phrase_patterns в DangerWordFilter — фразы проверяются до слов, границы по краям фразы, IGNORECASE, возврат {"matched_word": ...} совместимый. Потребители: war_alert (4b) и danger_handler (4c) — единый словарь. Итог 135 паттернов; target ≈646 тестов. Прод .env не трогаем.*

*Обновление: 2026-08-16 — EPIC 23: DONE & DEPLOYED ✅ (v2.21.0, коммит `756d237`). Деплой: git pull 0c74220..756d237 (9 файлов) на 198.46.175.136:/var/www/admin_bot, systemctl restart OK — active (running) PID 917681, логи чистые. .env DANGER_WORDS пустой → активны дефолты word_lists.py (118 слов + 17 фраз, 135 паттернов). Python-проверка «118 17» на сервере совпала. Все 23 Epic'а COMPLETE и DEPLOYED. Прод v2.21.0, бот активен, 0 ошибок.*

*Обновление: 2026-08-16 — EPIC 24 (v2.22.0-in-progress): Шаг 3 (@Memory) — фаза архитектуры (T-173) завершена, граф знаний и MEMORY.md синхронизированы. Дизайн Section 33 (A1–A15, риски 33.14) зафиксирован в ARCHITECTURE.md; RESEARCH.md верифицирован (методология: context7 — Invalid API key / duckduckgo — anomaly → рабочий стек exa + webfetch docs.aiogram.dev). board.md: T-173 → In Review, T-174 → READY FOR BUILDER. Код не писался — передача @Builder после PM-аппрува T-173-E. Предупреждения для @Builder: Н1 BotFather /setprivacy → Disable (T-191); порядок роутеров 0a/0b не менять; 12 существующих роутеров и MessageCounterMiddleware не трогать; sqlite-vec — только graceful fallback (R3).*

*Обновление: 2026-08-16 — EPIC 25 (багфикс /summary): IMPLEMENTED + REVIEW PASSED ✅ (Шаг 6, @Memory — граф знаний и MEMORY.md синхронизированы). @Builder: T-194/T-195 DONE — B1–B9 реализованы (summary_throttling.py B3: _parse_command, me()-валидация mention case-insensitive, чужая mention не жжёт слот и пропускается, base == "/summary", guard text.strip(), R8-молчание + INFO remaining; summary_generator.py B2/B4/B5: generate_and_send(chat_id, manual=False), _UX_EMPTY/_UX_BUSY, пустое окно/lock UX manual + INFO cron; handlers/summary.py B1/B6/B7/B8/B9: ack «ща гляну, подожди» send_message, _safe_send(bot) с DI bot, message.delete() после ack try/except WARNING, INFO-логи всех состояний, наблюдатель не пишет /summary* в text и caption). Тесты: 860 PASS (835+25), 0 регрессий. @Reviewer: T-196 APPROVED — 860 подтверждены личным прогоном, J1–J5 подтверждены, Bot.me() кэшируется (1 вызов на процесс); 4 Low-замечания не блокируют: (1) троттлинг смотрит только event.text — команда-капшн обходит (pre-existing, сериализуется Lock); (2) «ack sent» при неудаче; (3) bot.me() без try/except; (4) _last без TTL. Остаток: T-197 (коммит на русском + push) и T-198 (деплой + верификация /summary живьём через логи) → @DevOps. Деплойный риск B7: админ-права delete_messages у бота в чате (иначе 400 Bad Request → WARNING, best-effort).*

*Обновление: 2026-08-16 — EPIC 25 (багфикс /summary): DEPLOYED ✅ (Шаг 8, @Memory — ФИНАЛЬНАЯ синхронизация, цикл завершён). @DevOps: T-197 DONE (локально 860 passed 7.43s; коммит c364f18 «fix(summary): починить /summary — валидация mention в троттлинге, ack и удаление команды (Epic 25)» — 11 файлов, +1001/−84; пуш 818e195..c364f18; docs-коммит 2a45f79; .env не тронут). T-198 DONE (прод 198.46.175.136: git pull ff a68732c..c364f18; .env не меняли — дефолты подходят; рестарт: первая попытка stop-timeout → SIGKILL старого процесса ~90с (pre-existing), вторая OK; active (running) PID 923954; старт чистый: Database initialized, sqlite-vec dim=768, cron 0,6,12,18, «SmartModule Summary initialized», 14 роутеров, ImportError 0). Прод v2.23.0-fix, Epics 1-25 ALL DEPLOYED. Живой тест /summary после рестарта ещё не выполнялся — финальная верификация по логам после теста пользователем (цепочка: triggered → ack sent → window_size → LLM request → chunk sent → command deleted, или WARNING при отсутствии прав delete_messages — штатно). Наблюдения (pre-existing, кандидаты в backlog): (а) L3 dimension mismatch — эмбеддинги 3072 dim vs БД 768 → FTS5 fallback (cron-саммари успешен); (б) stop-timeout systemd при рестарте (~90с → SIGKILL, сервис поднимается корректно). Ручные действия пользователя: живой тест /summary; Н1 BotFather /setprivacy → Disable; при WARNING удаления — выдать боту админ-права delete_messages. board.md: T-197/T-198 Done, Epic 25 в финальной стадии.*

*Обновление: 2026-08-16 — EPIC 26 (GraphRAG-память, v2.24.0): IMPLEMENTED + REVIEW PASSED ✅ (Шаг 6, @Memory — граф знаний и MEMORY.md синхронизированы). @Builder: T-200–T-204 DONE — DDL nodes/edges в _SCHEMA_SQL (chat_id, UNIQUE, 4 индекса, upsert weight), EXTRACT_PROMPT дословно в summary_prompts.py, parse_triplets/_extract_and_save_graph в summary_memory.py (extract → graph → delete, per-batch isolation), get_graph_facts (never raises, fallback chat-wide), тег <historical_graph_facts> первым в _compose_user_content (graph_facts: list[str] = []), настройки GRAPH_* в settings.py и .env.example. Реальные сигнатуры DatabaseService: upsert_node/upsert_edge/match_nodes/get_top_edges/get_top_edges_all. @Reviewer: дважды PASS (0 блокеров). Тесты: 939 passed (860 baseline + 73 Epic 26 + 6 T-206). T-206 (P1) исправлен: FTS-DELETE зеркалит условие вставки (text IS NOT NULL AND text != '') в delete_smart_messages_by_ids/delete_smart_messages_older_than; chat_id-фильтр в FTS-DELETE by_ids; 6 регрессионных тестов. ARCHITECTURE.md 35.4: допустимость JSON-объект-обёртки зафиксирована. Код в рабочем дереве БЕЗ коммита — впереди T-205: README (ироничный тон) + коммит на русском + пуш + деплой → @Builder+@DevOps.*

*Обновление: 2026-08-16 — EPIC 26 (v2.24.0-in-progress): Шаг 3 (@Memory) — фаза архитектуры (T-199) завершена, граф знаний и MEMORY.md синхронизированы. Section 35 (35.1–35.11) зафиксирована в ARCHITECTURE.md: DDL nodes/edges (chat_id + UNIQUE(chat_id, entity_name) + UNIQUE(source_id, target_id, relation_type), weight, last_updated), upsert ON CONFLICT DO UPDATE weight=weight+1, extraction flow extract→graph→delete в compress_and_purge с per-batch isolation (D68), traversal get_graph_facts (never raises) с сущностями окна детерминированно БЕЗ доп. LLM-вызова и тегом <historical_graph_facts> ПЕРВЫМ в user-промпте (D71), EXTRACT_PROMPT дословно (35.3), настройки GRAPH_RAG_ENABLED/GRAPH_EDGE_WEIGHT_INCREMENT/GRAPH_TOP_EDGES_LIMIT/GRAPH_EXTRACT_MAX_TRIPLETS + хардкод-константы (D69). Все 10 открытых вопросов закрыты (35.9), риски R1–R10 (35.10). board.md: T-199 → In Progress (ждёт PM-аппрув). Код не писался — передача @Builder после PM-аппрува T26.0-D. Предупреждения для @Builder: 860 тестов не сломать (правки только 2 фикстур), порядок extract→graph→delete, PRAGMA foreign_keys не включать, COMPRESS_PROMPT заморожен (SYSTEM_PROMPT обновлён в Epic 27, R11 v2), llm_client.py/bot.py/vec0 не трогать.*
