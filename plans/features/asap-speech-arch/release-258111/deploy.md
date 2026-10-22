# REL-258111 deploy + W2 — прод 2.58.111 @ fbf9013d (23.10.2026, канонная эволюция W1)

**Статус: деплой завершён, W2-верификация пройдена (FINAL_VERIFY_OK).** Epic asap-speech-arch остаётся открытым (W3/живые строки — отдельно).

## Релиз

- **DEPLOY_SOURCE:** git master `fbf9013d89b03e38473ce6824a460fdbb736fff8` (поезд 2.58.111, Approved REV-REL-258111); прод: `git pull --ff-only` a8d2a45a → fbf9013d.
- **Версия:** healthz `{"status":"ok","version":"2.58.111"}`, HTTP 200 (проверено 13:15 и 13:2x UTC).
- **Процесс:** systemd admin_bot, PID 516119, старт 13:14:31 UTC, NRestarts=0 (стабильно), active. Пуш: master 804f4963..fbf9013d + rollback-ветка `release/fix-2.58.110` = a8d2a45a (origin).
- **Рестарт:** один плановый (13:14:31) — W2-записи (§5.5) выполнены ДО него, поэтому лестница на старте отработала уже поверх новых значений (для W2-ключей — идемпотентный «уже новый канон»), а активный слой+провенанс загружены в RAM рестартом. Второй рестарт не потребовался.
- **ΔDDL=0**: `[database] migrations: user_version=37, pending=[]`.

## W2 — канонная лестница и миграция активных значений (таблица §5.5)

| block_id | factory old→new SHA | active old→new SHA | scope | provenance | runtime payload SHA | migration result |
|---|---|---|---|---|---|---|
| core.personality (full) | d98e72ec7926→2ab417d11404 | f59ba0f42a48→**3de4884f29ce** (2327→1995c) | global | owner_edit, persisted, history (write_speech_value) | 3de4884f29ce | **owner_preserve_core_full_patch**: удалена ровно 1 фрагмент — служебная ремарка «**Важно:**…см. SOUL-16» (фабричные байты); независимая реконструкция: owner_bytes_preserved=true; superseded-гвард v1/v2 владельца не касался |
| core.personality.compact | e0529832ba7c→9e6a4ec8b1ea | пусто→пусто | global | — | 9e6a4ec8b1ea (фабрика) | поле пустое → действует фабрика §3.3 (W0-ожидание) |
| direct.base.l2_writer (verbalizer §3.1) | d0ef0d376fc3→be03964322aa | 091115cadc28→**be03964322aa** (1676→1982c) | global | owner_edit, persisted, history | be03964322aa | W2-запись §5.5: unprovenanced-кастом погашен, прежние байты → history |
| direct.base.tool_phase (§3.6) | 0fe9680ba280→f30c6d73da82 | cf404931f84c→**f30c6d73da82** (5294→4999c) | global | owner_edit, persisted, history | f30c6d73da82 | W2-запись §5.5 |
| summary.base.narrator | f02b6ca755a4→5086ba935081 (LEGFIX) | 43160d5f9c2c→**5086ba935081** (1850→1788c) | global | owner_edit, persisted, history | 5086ba935081 | W2-запись §5.5 на LEGFIX-канон |
| direct.base.l1_planner (§3.7) | ace6246bd360→f8ab20121c02 | ace6246bd360→**f8ab20121c02** (4264→4641c) | global | prompts-лестница (известный канон) | f8ab20121c02 | **ступень на старте**: journal 13:14:52 `[prompt_migration] канон обновлён` (первый SELECT верификации прочитал значение до записи лестницы — гонка, финальная сверка PASS) |
| factcheck.base.verbalizer | c9b0f431e849→c090b6956c70 | 5fbf61cea310 (1712c, НЕ изменился) | global | нет (кастом) | 83b4fb75500f (cleaned default, withheld) | лестница честно skip («кастом юзера»); ВНЕ скоупа W2 §5.5 — см. Находки |

**Журнал лестницы (13:14:52, новый процесс):** `уже новый канон` × 4 (tool_phase, verbalizer, narrator + compress/analyst/l1_clusterizer), `канон обновлён` × 1 (l1_planner), `кастом юзера — НЕ трогаем` × 10 (summary_system 3558c, checkup, factcheck_system 4666c, search, youtube, youtube_video, webpage, summary_editor 2023c, factcheck_verbalizer 1712c, summary_l2_writer 8388c).

## Верификация (final read-only, FINAL_VERIFY_OK 14/14)

- **Fingerprint:** runtime `factory_set_fingerprint()` == константа == **fd4e88754749** (89 канон-блоков).
- **SELECT == новые фабрики:** verbalizer be03964322aa/1982c ✓, tool_phase f30c6d73da82/4999c ✓, narrator 5086ba935081/1788c ✓, l1_planner f8ab20121c02/4641c ✓, core full 3de4884f29ce/1995c ✓, compact пусто ✓.
- **RUNTIME-слой:** l2_writer/tool_phase/narrator — `attested`, payload_sha12 == значению (withheld=False); l1_planner — known canon, играет как есть.
- **Кастомы владельца целы:** 7 CFG07A — tool_phase погашен осознанно (см. таблицу), остальные 6 байт-в-байт неизменны (d697b0745b29/1e8a3c69cf7b/ba43fb679db6/e0a1ffaf18a1/c8bba06ec6a8/7801085b6ef5); per-chat overrides -1002661910336 (26) и -1004482340693 (3) == пре-деплой снимку (expression frequent/sharp/wit, summary-кастом 141016a95b95, mode-блоки — не тронуты).
- **Blob-сверка:** 9/9 файлов сервера == candidate fbf9013d (chat_prompts, factcheck_prompts, mca_expression, param_catalog, prompt_migrations, prompt_registry, summary_prompts, web/app.py, web/static/app.css — sha256 в deploy.json).
- **Журнал:** новый процесс с 13:14:52 — 0 CRITICAL/0 Traceback, 0 «database is locked». 1 Traceback при ОСТАНОВКЕ старого процесса (13:14:20, см. Находки).

## P0-A/B live-половины (postdeploy, observed)

- **P0-A (verbalizer §3.1):** активная запись PG == фабрике §3.1 (be03964322aa) с провенансом, runtime payload == канону, unprovenanced-кастом 091115cadc28 → history. Постдеплой-эвиденс добавлен в карту (REQ-P0A).
- **P0-B (core §3.2 + owner-preserve):** фабрика v3 = 2ab417d11404; активная правка владельца rev6 f59ba0f42a48 → 3de4884f29ce патчем «только SOUL-16-ремарка» (owner_bytes_preserved=true, diff-итог в таблице), запись через реестр с провенансом owner_edit + history. Постдеплой-эвиденс добавлен в карту (REQ-P0B).

## Биндинг

- asap-speech-arch `deployed_commit` = fbf9013d89b03e38473ce6824a460fdbb736fff8 (+ постдеплой-эвиденс REQ-P0A/REQ-P0B).
- asap8-v6-3-live-correction `deployed_commit` = a8d2a45a → fbf9013d89b03e38473ce6824a460fdbb736fff8.

## Откат

`release/fix-2.58.110` = a8d2a45a (origin). Код: checkout + рестарт. Каноны: ROLLBACK_MIGRATIONS ведёт 4 скалярных ключа на непосредственные прежние прод-каноны 2.58.110 (байт-в-байт, стек ступеней цел); W2-значения в history (character.prompt_history) — обратимы через реестр; core-правка владельца — байты 3de4884f29ce → история хранит f59ba0f42a48. Секретов в evidence нет (только sha12/длины).

## Находки (incidental, вне поезда)

1. **factcheck_verbalizer — активное значение 5fbf61cea310/1712c не равно ожидаемому прежнему канону c9b0f431e849/1725c** (review-rel.md предполагал «PREV==прод»): это подлинный кастом (без провенанса), лестница его честно пропустила, LLM играет cleaned-фабрику (withheld). W2-скопа не касался (factcheck W3-freeze класс). Требует решения владельца в W2-волне: гасить на фабрику §3.1-factcheck (c090b6956c70) с провенансом или осознанно оставить.
2. **Summary-прогон 18:00+05 чата -1002661910336 (13:00–13:14 UTC, ещё на 2.58.110):** SUMMARY_COMPLETE status=ok, но health=degraded, coverage=0.0, source_considered=0; фолбэк-тик `_legacy_fallback("l2_unusable")` бросил Traceback при остановке процесса рестартом. Проблема домена summary, началась до деплоя — маршрутизировать в summary-лейн.
3. Запись DNS/healthz по домену с самого сервера работает; SSH-коннекты: 5 одиночных логинов nik с паузами ≥90 с (recon→deploy→recovery→diag→final), без поллеров; fail2ban не спровоцирован.

Гейт релиза: `requirements_gate.py check --stage release --candidate fbf9013d --deployed-commit fbf9013d` — результат и классификация PENDING-строк в deploy.json.
