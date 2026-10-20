# DEPLOY-258101 — evidence: выкат 2.58.101 (CFG-07A-2 анти-backstage каноны + бамп)

Релиз: **2.58.101** — CFG-07A-2: анти-backstage контракт на 7 не-фактчек
канонах (chat/direct, summary, checkup, search, youtube ×2, webpage) по
ADR-1013-3 (FROZEN-байты + лестницы PREV_*_CFG07A + rollback на
непосредственный канон + OFF-паритет) в составе релизного поезда. Ревью
**Approved** — `review-rel.md` (REV-REL-258101; кандидат кода `211a8c1b`,
поезд `3b83da92` = бамп 31-файл, docs `e3c61445` поверх). Миграций SQLite
нет (ΔDDL=0), v37 остаётся; промпт-миграция — штатно на старте bot.py.

- **Фактический deployed SHA: `e3c61445deabd4cdd4366bc205712f9325c88ac3`**
  (= `origin/master`; verified on prod: fetch `acc285d7..e3c61445 master`,
  checkout -B master, HEAD_POST == e3c61445, TRACKED_MOD=0).
- Прод ДО: `acc285d7` (2.58.100, healthz 2.58.100, MainPID 3989095) → ПОСЛЕ:
  **`e3c61445` (2.58.101, MainPID 4033927, ExecMainStart 15:21:38Z,
  NRestarts=0, active/running)**.
- **DEPLOY_SOURCE:** `origin/master` (иммутабельный коммит); рубеж отката
  `origin/release/fix-2.58.100` == `acc285d7` подтверждён fetch'ем на проде.
  **MUTABLE_WORKTREE_REQUIRED: no** — запись: прод-репо /var/www/admin_bot
  (checkout + разовая починка владения), PG bot_settings (штатная
  промпт-миграция — фактически 0 обновлений, кастомы сохранены), /tmp,
  DevOps-scratch, этот evidence-каталог.
- **T0: 1792509676 (2026-10-20 15:21:16Z)**, RESTART_RC=0; healthz 2.58.101
  через ~23 с (POLL9), стартап быстрый — backup-guard VACUUM не запускался
  (pending=[], см. ниже).

## Гейты перед рестартом (все OK)

- ORIGIN_MASTER == e3c61445; RB_REF == acc285d7; CAND_IS_ANCESTOR=1;
  RB_IS_ANCESTOR=1; NEW_HEAD==ORIGIN_MASTER; TRACKED_MOD_AFTER=0.
- DELTA acc285d7→e3c61445: total 82; **runtime set == ровно 13 файлов**
  (settings + 12 services: chat/checkup/direct_capabilities/nostalgia×2/
  prompt_migrations/prompt_registry/prompt_style_blocks/search/summary/
  web/youtube prompts); **DELTA_DDL=0** (database.py, scripts/ — пусто);
  DELTA_OTHER_NONSTD=0 (остальное — plans/ + tests/ + README).
- sha256_12 на диске прода == кандидату (16/16: 13 runtime + README
  80461d794865 + database.py b7fdd7615a52 (неизменный) + web/app.js
  db8457cafa9b (неизменный контроль, == served на 2.58.100)).
- Маркеры: `APP_VERSION = "2.58.101"` =1; лестницы `PREV_*_CFG07A` в
  prompt_migrations.py = **21** (7 import + 7 миграций + 7 откатов);
  `FACTORY_SET_SHA256_12` = `037080375ac8` (grep 2); F8-meta содержит
  `211a8c1b`; `rollback_prompt_canons` присутствует (def=1) — **откат-механизм
  на месте, НЕ применялся**.
- Служебное (механика деплоя, поведение не меняет): chown nik:developers
  для root-owned артефактов plans/ (22→0, хвост samples-ux/cfg-06-эпохи,
  блокировавшие checkout); удалены 18 untracked-коллизий (evidence-файлы
  07A-2, выложенные ранее вручную, теперь tracked; sha256 залогированы в
  main101-run.txt до удаления); rin-owned `plans/` (2775, group-writable) не
  тронут.

## Здоровье и смоук

- healthz: loopback и внешний (HTTPS admin-bot.duckdns.org, вне SSH)
  `200 {"status":"ok","version":"2.58.101"}`; `/web/` 200; served app.js
  sha `db8457cafa9b` == диск == кандидат.
- `[config_cache] initialized: settings=532 roles=4 admins=3`;
  `[database] migrations: start | current user_version=37 | pending=[]` →
  `complete | total 0.0s` — **ΔDDL=0 подтверждён на проде, v37 остаётся**.
- **Сообщений в чаты не отправлялось** (запрет лейна).

## Промпт-миграция CFG-07A-2 — честная трасса effective-payload (CFG-07A.1)

Журнал с T0: `[prompt_migration]` 16 строк, **ошибок 0**; 11× «кастом юзера —
НЕ трогаем», 5× «уже новый канон», **0× «канон обновлён»**. Все **7 целевых
ключей CFG07A — «кастом юзера — НЕ трогаем»**: лестницы не сработали,
значения в PG **не** заменены (защита кастома по дизайну). Read-only
venv-проба PG (bot_settings, json.loads):

| ключ | sha256_12 | len | vs PREV_*_CFG07A |
|---|---|---|---|
| prompts.direct_chat_system_prompt | cf404931f84c | 5294 | 6 правок |
| prompts.summary_system_prompt | d697b0745b29 | 3558 | 6 правок |
| prompts.checkup_system_prompt | 1e8a3c69cf7b | 2312 | 6 правок |
| prompts.search_system_prompt | ba43fb679db6 | 2622 | 6 правок |
| prompts.youtube_system_prompt | e0a1ffaf18a1 | 2252 | 6 правок |
| prompts.youtube_video_system_prompt | c8bba06ec6a8 | 2248 | 6 правок |
| prompts.webpage_system_prompt | 7801085b6ef5 | 2071 | 6 правок |

Дифф **идентичен у всех 7** — одна систематическая владельческая правка
общего фразового блока (len = PREV − 35): «В болтовне о»→«О», «я»→«й»,
«;»→«,», +«н», удалено «если план требует полного разбора - …», «его»→
«каждый пункт». Т.е. прод-значения — **сознательный кастом владельца** (не
случайный мусор), и анти-backstage чистка 07A-2 **не достигла effective-
пейлоадов**: лестница матчит только канонические байты, кастом защищён.
Ни один из 7 ключей не равен ни новому канону, ни PREV_*_CFG07A. Это
продуктовый факт для Reviewer/Orchestrator (решение: ступени для
custom-вариантов / владельческое уведомление / принятие стат-кво) — **не
дефект деплоя** и не повод перезаписывать кастом. CFG-07A.1 как
постдеплой-трасса **VERIFIED считаться не может** — финальный вердикт за
Reviewer/Orchestrator.

## ERR since T0

**ERR=0** (final 15:31Z, journal 538 строк: ERROR|CRITICAL|Traceback = 0,
RuntimeWarning = 0, prompt_migration errors = 0). Рестарт-транзиентов типа
2.58.100 (vision drain) не зафиксировано.

## Откат (задокументирован, НЕ применялся)

- Cold: `git checkout -f acc285d77d03c7adbf5527dc7f0fa9e9904fed8e`
  (== `origin/release/fix-2.58.100`, verified on prod) +
  `sudo systemctl restart admin_bot` → 2.58.100. Совместимость полная:
  ΔDDL=0, ничего в схеме/данных не менялось; промпт-каноны не переписывались
  (0 обновлений) — откат состояния PG не требуется.
- Soft: `rollback_prompt_canons` (prompt_migrations.py, присутствует) —
  вернуть возможные будущие обновления канонов на PREV_*_CFG07A; сейчас
  no-op (обновлений нет). Повторный выкат 2.58.101 безопасен
  (idемпотентен; лестницы no-op на кастомах).

## Release-гейт

`requirements_gate.py check --map plans/features/cfg/requirements-map.json
--stage release --repo .` (карта — вся фича CFG, 246 инвентарных строк):
- `--candidate e3c61445 --deployed-commit e3c61445` → **EXIT 1, errors=453**
  («candidate mismatch»: карта привязана к 211a8c1b + весь хвост открытых
  волн/исторических биндингов);
- `--candidate 211a8c1b --deployed-commit e3c61445` → **EXIT 1, errors=443**
  (ADD-0.x PENDING, исторические строки со старыми candidate-биндингами,
  волны 07C-G — open-plan по review-rel §2).
Структурно красная карта открытой фичи — прецедент deploy-258100 («поезд не
заявляет DONE фичи»); релиз-вердикт поезда — за Orchestrator/Reviewer на
базе review-rel §3 + этой трассы.

## SSH-бюджет и гигиена

8 коннектов, один логин `nik`, паузы ≥70 с, без параллелей/поллеров;
3 из них — аборт-гейты/два бага финального скрипта (исправлены); рестарт —
один. Пароли только через stdin (sudo -S) и env git-credential, в argv/логе
не печатались. Внешние пробы — HTTPS 443. Инцидентов fail2ban нет.
Инфра-находка: root-owned артефакты plans/ блокировали nik-checkout —
починено chown (см. выше).

## Файлы

- `deploy.md`, `deploy.json` (этот каталог); сырьё —
  `OPENCODE_WORKFLOW_SCRATCH/deploy-258101/`: `recon101.txt`, `main101-run.txt`,
  `journal101-since-T0.raw`, `final101-run.txt`, `own101.txt`, скрипты
  `rc101/dp101/fn101/ow101` (.py), локальные хэши кандидата `canon_hashes.py`.
