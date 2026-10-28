# Deploy 2.58.141 — release/p0-2026-10-26 (DEPLOY-258141, p0-history-analysis → OLD VPS, phases B–C release-then-migrate)

**Дата:** 28.10.2026 (server UTC; рестарт ActiveEnter 22:35:17). **Ветка:** `release/p0-2026-10-26`.
**DEPLOY_SOURCE:** commit `5346ee765e83ee859596b60437811b21db1e4564` (detached checkout на сервере; mutable worktree НЕ требуется).
**Review-кандидат (ACCEPT):** `0b8dfe6af297aaa65caa1a216d584ef43f6b1d73` (local master HEAD).
**Merge-коммит:** `0ef8477b` (`merge(p0-history-analysis)` — 986779cb × 0b8dfe6a).
**Bump-коммит = deployed SHA:** `5346ee76` (`chore(release-258141): bump 2.58.140 -> 2.58.141 …` [P0-HISTORY-ANALYSIS,REL-258141]).
**Pre-state:** `5c8bf35d` (2.58.140, healthz 200, active, NRestarts 0, dirty 13) — прошлая проверенная база.
**APP_VERSION:** `2.58.141` (healthz подтверждает).

## PART 0 — merge master → release (конвенция деплой-линии)

Трёхсторонний merge `986779cb + 0b8dfe6a` (расхождение от базовой точки 924b3b51): на deploy-линию перенесена
полнота кандидата 0b8dfe6a (волны DEPTH / TRUNC-PAGES / SEGMENTS / QUALITY / ISOLATION / RELEVANCE p0-history-analysis
+ сопровождающие closure-доки), при этом **все задеплоенные фиксы deploy-линии сохранены**.

Политика разрешения конфликтов (симметричные линии, точечный дрейф):
- **ours (release, deployed state)** — фактчек (factcheck-media/fcpost/correctives §5.1/§7.3), embedding_control_plane
  (EMBED-META-WIRE — задеплоенная генерация canary-03; master-вариант 60789cff не деплоился, его тест взят release-версией),
  expression/mca_expression (P0-HOTFIX канон 25.10 + лестница), prompt_registry/prompt_migrations/prompt_composer
  (канон-миграции, simplify_core_for_prompt, humor dedup), summary_aliases (F6/F7), search_aggregator (§5.1/§5.2),
  тесты пинов канона;
- **theirs (master)** — p0-HA контент (HISTORY_*_QUALITY blocks, usage-penalty), checkup суффикс именования, AGENTS.md
  (секция workspace hygiene 28.10), plans/* closure-состояния;
- **union/точечно** — импорты prompt_style_blocks в direct_chat_service (NO_META + оба HISTORY-блока), alias_resolver —
  release fail-open вариант; test-стаб `_participant_roster` доведён до задеплоенного контракта (usernames=None).
- **repaired seam:** `tests/test_history_w4_fixes.py` стаб 2-arg → 3-arg под задеплоенную сигнатуру (иначе TypeError на стабе).

Результат: deltaDDL = **0** (0 схемных файлов в диффе; database.py — 0 CREATE/ALTER/user_version), зависимости не менялись
(pip-фаза пропущена), AST/compile чисто.

## Guards (локально на merged/bump дереве)

| Guard | Результат |
|---|---|
| `compileall services web tests config tools bot.py manage.py` | **OK** (rc=0) |
| `tools/gen_param_registry_round1025.py --check` | **OK** (586 == REGISTRY, карта полна) |
| deltaDDL vs 986779cb | **0** |
| p0-HA suite (9 файлов history-тестов) | **254 passed, 0 failed** (после починки стаба) |
| Reconciled-подсистемы (13 файлов: embed/factcheck/expression/aliases/checkup/prompts/migrations/samples/routes) | **281 passed** + после checkup-флипа 73/75 (2 фейла — pre-existing, см. ниже) |
| Bump proc set | **31 файл / 33 строки, SET EQUAL proc-258140** (README, APP_VERSION, F8-meta HEAD=`0ef8477b`, 24 py-пина, 4 JS escaped-regex, polygon 2 строки) |
| Pin-суит (24 файла) на deployed SHA | delta-фейлов vs чистый 986779cb = **0** (18 stale catalog-пинов «587» падают И на чистом deploy-tip — pre-existing, не от merge/bump) |

**Pre-existing на deploy-линии (задокументировано, не блокер релиза):** 18 catalog-pin фейлов (пин 587 при факте 586 —
stale с прошлых волн, `git`-проверено на чистом 986779cb), 2 фейла test_samples_fewshot (byte-pins против канона 25.10 —
падают и на 986779cb). Рекомендация в backlog: синхронизировать каталоговые пины deploy-линии с фактом 586.

## PART 1 — push

`986779cb..5346ee76 release/p0-2026-10-26 -> origin` (fast-forward). Fetch на сервере: `5c8bf35d..5346ee76`, FETCH_HEAD == deployed SHA.

## PART 2 — deploy (SSH, fail2ban-safe)

`nik@198.46.175.136`, `/var/www/admin_bot`, unit `admin_bot` (venv python 3.12.3, ExecStart venv/bin/python bot.py),
Ubuntu 24.04.4 LTS, healthz loopback :8000 + внешний `https://admin-bot.duckdns.org/healthz`.

| Шаг | Результат |
|---|---|
| Pre-state | HEAD `5c8bf35d`, active, NRestarts 0, dirty 13, healthz **200 2.58.140** |
| `git fetch origin release/p0-2026-10-26` | rc 0, FETCH_HEAD == `5346ee76…` (mismatch-guard пройден) |
| `git checkout --detach 5346ee76` | rc 0, HEAD = deployed SHA, **dirty 13 сохранены** |
| Blob-пины deployed vs candidate | **10/10 OK** (settings `55d829d5…`, direct_chat_service `7ab9e89b…`, database `d83ec089…`, tool_schemas `976218e3…`, tool_router `eec78ad2…`, mca_expression `b2be1b68…`, prompt_style_blocks `aae32599…`, checkup_prompts `a14bb660…`, summary_memory `0aec5dda…`, factcheck_service `5490f59e…`) |
| AST-check services на deployed tree | **253 файла, 0 syntax errors** |
| `sudo -n systemctl restart admin_bot` | RESTART_RC=0, новый MainPID 959071, ActiveEnter 22:35:17 UTC |
| healthz | **200 `{"status":"ok","version":"2.58.141"}`** (try 3 внутри одного сеанса) |
| Внешний контур | `https://admin-bot.duckdns.org/healthz` **200 2.58.141**; админка `/` **200** (HTML 930 КБ) |
| Unit | `active`, **NRestarts = 0** |

**SSH-бюджет:** 5 соединений (recon → основной прогон → tail-верификация через 15 мин → 2 микросеанса классификации
единственного journal-совпадения), между всеми ≥60 c, без повторов auth. Отклонение от прецедента (4): обязательная
классификация traceback-совпадения в журнале для честного postcheck (см. ниже).

## PART 3 — postdeploy live acceptance (REQ-HA-DEPLOY-POSTCHECK, live_when=postdeploy)

Старт нового кода чистый: shutdown handlers → polling запущен → webapp lifespan `pg_available=True` →
scheduler тикает (VisionMediaWorker 5-сек интервал — реальная фоновая работа на новой версии, выполняется успешно).

| Проверка | Результат |
|---|---|
| systemd 15 мин после рестарта | `active`, NRestarts **0**, тот же MainPID 959071 (без crash-loop) |
| Journal (окно рестарта, 377 строк) | **0 ошибок релизной природы**; 0 строк уровня warning+ |
| Единственный traceback в окне | **anticliche_worker → en.wikipedia.org HTTP 403 (robot policy)**, pipeline fail-open (status=error, count=0, next_run +7 дней) — **тот же внешний инцидент, что задокументирован в deploy-258140**; код anticliche этим релизом не трогался, наблюдался и на 2.58.140. Не от релиза; остаётся в backlog (retry/альтернативный источник/UA) |
| Честная history-строка `fetched=… count=… out_chars=…` | **not_observed** — в окне наблюдения (22:35–22:52 UTC) естественных history-анализов не было (0 совпадений); НЕ симулируется, ждёт штатного трафика |
| Публикации саммари/события | естественных публикаций в окне не было — отмечено **not_observed** (штатные расписания вне окна наблюдения); фоновые тики и polling подтверждены |
| Blob-идентичность | deployed дерево == кандидат по 10 ключевым файлам (см. PART 2) |

## Live-verified vs not_observed (DEPLOY-строки карты)

- **VERIFIED (live, на deployed SHA):** REQ-HA-DEPLOY-SAFE (штатный деплой, изоляция/откат сохранены, версия
  зафиксирована), REQ-HA-DEPLOY-POSTCHECK (реальное поведение/логи/ошибки проверены, тестовых сообщений в рабочие
  чаты нет), REQ-HA-DONE-01..13 — код идентичен ревью-кандидату (blob-пины/merge до 0b8dfe6a), ревью-факты не
  переопределяются.
- **not_observed (естественное событие не наступило, не симулировалось):** `fetched=`-строка честного подсчёта
  истории на живом трафике; естественная публикация саммари в окне наблюдения. Проверка возобновляется штатным
  трафиком без действий DevOps.
- **REQ-HA-DEPLOY-QUEUE / REQ-HA-OWNER-REPORT / REQ-HA-DONE-NO-OWNER-BLOCKS** — организационные (очередь/отчёт
  владельцу/неблокирование owner-чеками) — вне DevOps-зачёта, материал передан Orchestrator/PM.

## Rollback

`git checkout 5c8bf35db07e49d1dae4ca5a543911bf6b56ed54 && sudo systemctl restart admin_bot` → healthz 2.58.140.
Схема БД не менялась (deltaDDL=0), rollback бинарно безопасен; dirty 13 серверных локальных файлов переживают
checkout (проверено переходом 5c8bf35d→5346ee76; обратный — по тому же механизму).

## Артефакты

- Скрипты и raw-выводы: WorkspaceData runs `c742e4de9e92c489/p0-history-analysis-24c1789f4d07/temp-550e06aa18/`
  (recon_258141.py, deploy_258141.py, tail_258141.py, classify_258141.py, dump/resolve-инструменты merge).
- Merge worktree: `WorkspaceData/worktrees/c742e4de9e92c489/p0-history-analysis-24c1789f4d07-b07c9075`
  (release-branch checkout, по завершении — чистый, под epic-close housekeeping).

## Итог

**VERIFIED (фазы B–C):** точный ревью-кандидат `0b8dfe6a` (через merge `0ef8477b` + bump) задеплоен на СТАРЫЙ
production как `5346ee76` / **2.58.141**, все доступные обязательные проверки PASS, откат готов, блокеров нет.

**MIGRATION_SOURCE_SHA = `5346ee765e83ee859596b60437811b21db1e4564`** (build 2.58.141, ветка release/p0-2026-10-26,
detached HEAD на старом VPS) — неизменяемая база для фаз D–E (миграция на новый VPS). Любые новые кодовые деплои
до cutover требуют повторной сверки release gate.
