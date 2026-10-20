# DEPLOY-258102 — evidence: выкат 2.58.102 (CFG-07A F1 custom-clean + бамп)

Релиз: **2.58.102** — CFG-07A F1: payload-уровневое подавление корпусных
legacy-маркеров (SF-семейство + правила 12/13) из effective-пейлоадов
владельческих кастомов 7 не-фактчек канонов (`CFG07A_PAYLOAD_CLEAN_KEYS`),
**БД не мутируется** (0 set-calls, идемпотентно) + релизный бамп. Ревью
**Approved** — `review-rel.md` (REV-REL-258102; кандидат кода `6388899d`,
поезд `a3535b68` = бамп 31 файл + docs поверх). Миграций SQLite нет
(ΔDDL=0), v37 остаётся; промпт-миграция — штатно на старте bot.py.

- **Фактический deployed SHA: `a3535b68a3220f5a239ed7df3eb1a24f1e1d0873`**
  (= `origin/master`; verified on prod: fetch `e3c61445..a3535b68 master`,
  checkout -B master, HEAD_POST == a3535b68, TRACKED_MOD=0).
- Прод ДО: `e3c61445` (2.58.101, healthz 2.58.101, MainPID 4033927) → ПОСЛЕ:
  **`a3535b68` (2.58.102, MainPID 4053994, ExecMainStart 17:00:57Z,
  NRestarts=0, active/running)**.
- **DEPLOY_SOURCE:** `origin/master` (иммутабельный коммит). Рубеж отката
  `origin/release/fix-2.58.101` == `e3c61445` подтверждён fetch'ем на проде
  (новая ветка пришла тем же fetch'ем). **MUTABLE_WORKTREE_REQUIRED: no** —
  запись: прод-репо /var/www/admin_bot (checkout), /tmp, DevOps-scratch,
  этот evidence-каталог. **PG — только read-only пробы (0 записей).**
- **T0: 1792515630 (2026-10-20 17:00:30Z)**, RESTART_RC=0; healthz 2.58.102
  через ~27 с (POLL9), стартап быстрый — backup-guard VACUUM не запускался.

## Гейты перед рестартом (все OK; 1 ложный аборт до них — см. SSH-бюджет)

- ORIGIN_MASTER == a3535b68; RB_REF == e3c61445; CAND_IS_ANCESTOR=1;
  RB_IS_ANCESTOR=1; CAND→OM: nonplans=30/plans=1 (ровно бамп 31 файл);
  NEW_HEAD==ORIGIN_MASTER; TRACKED_MOD_AFTER=0; COLLIDE_COUNT=0;
  OWN_BAD_BEFORE=0 (root-owned plans/ — починены ещё в 258101, не рецидив).
- DELTA e3c61445→a3535b68: total 37; **runtime set == ровно 3 файла**
  (config/settings.py + services/prompt_factory.py + services/prompt_registry.py);
  **DELTA_DDL=0** (database.py, scripts/ — пусто); DELTA_OTHER_NONSTD=0
  (остальное — plans/ + tests/ пины 24py+4js + meta + 2 docs-evidence).
- sha256_12 на диске прода == кандидату (6/6): settings `9f92ac34a0f1`,
  prompt_factory `46cbcc0c0c8a` == review-f1, prompt_registry `b28459d008a1`
  == review-f1, README `18b711d98af5`, database.py `b7fdd7615a52` (неизменный),
  web/app.js `db8457cafa9b` (неизменный контроль).
- Маркеры: `APP_VERSION = "2.58.102"` =1; `CFG07A_PAYLOAD_CLEAN_KEYS` =5;
  `FACTORY_SET_SHA256_12` = `037080375ac8` (grep 2 — отпечаток не тронут);
  F8-meta содержит `6388899d` =1; лестницы `PREV_*_CFG07A` = 21 (не тронуты);
  `rollback_prompt_canons` def=1 — **откат-механизм на месте, НЕ применялся**.

## Здоровье и смоук

- healthz: loopback и внешний (HTTPS admin-bot.duckdns.org, вне SSH)
  `200 {"status":"ok","version":"2.58.102"}`; `/web/` 200; served app.js
  sha `db8457cafa9b` == диск == кандидат.
- `[config_cache] initialized: settings=532 roles=4 admins=3`;
  `[database] migrations: start | current user_version=37 | pending=[]` →
  `complete | user_version=37 | total 0.0s` — **ΔDDL=0 подтверждён на проде,
  v37 остаётся**. (Отдельная sqlite-pragma проба не выполнена: ImportError
  `DB_PATH` в одношотовом скрипте fn102 — v37 подтверждён журналом сервиса.)
- Промпт-миграция: `[prompt_migration]` 16 строк, **ошибок 0**, **0× «канон
  обновлён»**; все **7 целевых ключей — «кастом юзера — НЕ трогаем»** с
  chars 5294/3558/2312/2622/2252/2248/2071 (ровно прежние длины), 5× «уже
  новый канон».
- **Сообщений в чаты не отправлялось** (запрет лейна).

## Постдеплой payload-речек (CFG-07A.1) — read-only, штатный механизм

Метод (1 SSH-коннект, без записей): read-only asyncpg SELECT bot_settings
(7 ключей + `character.prompt_history`) → deployed
`resolve_speech_value(key, stored, source="global", cache=RO-shim)`, где
RO-shim отдаёт реальный провенанс-док из PG, а `cache.set` бросает
исключение (доказательство 0 записей через путь резолва). Это тот же
единый резолв, что в рантайме (`direct_chat_service:2651 resolve_chat_speech`
→ `resolve_speech_value`). Рантайм-отличий нет: live-ConfigCache держит тот
же док (settings=532, ключ не менялся с T0; записей в него не было).

- **(a) БАЙТЫ: 7/7 UNCHANGED.** sha256_12/len каждого ключа байт-в-байт равны
  пре-деплой-снимку (recon102, перед рестартом) и evidence deploy-258101:
  direct_chat `cf404931f84c`/5294, summary `d697b0745b29`/3558, checkup
  `1e8a3c69cf7b`/2312, search `ba43fb679db6`/2622, youtube `e0a1ffaf18a1`/2252,
  youtube_video `c8bba06ec6a8`/2248, webpage `7801085b6ef5`/2071.
  `SET_CALLS=0` через весь путь резолва. **PG не мутирован.**
- **(b) EFFECTIVE: 7/7 `withheld=True, reason=provenance_missing`** →
  effective = **заводской канон** (source=default). SF-маркеры на effective:
  **0** по всем 7 (sf_hits=0; `_legacy_persona_marker_re` 0; 
  `_corpus_extra_marker_re` 0). Диагностика ключей:
  `persisted_value_withheld, provenance_missing,
  persisted_legacy_persona_marker` — витрина конфликта W6, тихой подмены нет.
- **F1-ветка на реальных байтах работоспособна**: `suppress_legacy_speech(
  stored, custom_clean=True)` → applied=True 7/7, ожидаемые labels:
  identity_sentence везде; direct +`direct_style_label`+`honest_concession_
  invented_causes`; summary +`safety_circumvention`+`tone_label`+
  `bot_knowledge_hostility`+`archive_data_label`; checkup +`safety`+`tone`+
  `checkup_humiliation`+`checkup_language`; search +`safety`+`tone`+
  `hostility`+`search_sneer`; youtube/youtube_video/webpage +`safety`+`tone`+
  `hostility`. Removed 3–5 сегментов на ключ.
- **(c) ПРАВКИ ВЛАДЕЛЬЦА: в ХРАНИЛИЩЕ целы байт-в-байт** (см. (a)); **в
  EFFECTive отсутствуют — кастом не активен вовсе**: провенанс-гейт
  SOUL-AMD (до F1) удерживает значения, не записанные через API реестра.
  Это **не регрессия этого деплоя** — код удержания вне диффа F1, состояние
  идентично 2.58.101.

### Материальный факт (коррекция посылки находки F1)

Находка deploy-258101 F1 («чистка 07A-2 не достигла effective-пейлоадов»)
верна только для слоя ХРАНЕНИЯ: effective-пейлоады этих 7 ключей **и до F1
не содержали ни кастома, ни SF-маркеров** — кастомы удержаны провенанс-гейтом
(`provenance_missing` → заводской канон). F1 — корректная гарантия для
будущего attested-кастома (владелец правит через API → значение активно →
F1 чистит его на сборке; проверено на реальных прод-байтах), на текущий
effective не влияет. Формула закрытия review-rel §6(b) («маркеры
отсутствуют в effective» = да; «правки владельца целы [в effective]» = нет —
целы в PG). **Статус CFG-07A.1 в карте НЕ менял**; финальный вердикт —
Reviewer/Orchestrator (прецедент deploy-258101).

## ERR since T0

ERROR-level строк: **1** — 17:02:18 `mca_event=INCIDENT |
pipeline_type=vision.media | stage=takeover | reason_code=incident_opened |
outcome=success` (entity `inc_c16332769f7648179ffeb44f57bf3ab3`), перед ним
`WATCHDOG_TAKEOVER … reason_code=takeover_recovered outcome=success` и на
старте `[vision] drain timeout | inflight=1`. Классификация: рестарт-транзиент
vision-пайплайна (in-flight задача пережила рестарт → watchdog её восстановил,
инцидент-леджер записал событие уровнем ERROR). Известное семейство транзиентов
рестартов (наблюдалось на 2.58.100; на 2.58.101 не встречалось). Traceback=0,
PROMPT_MIG_ERR=0, RuntimeWarning=0; ingestion/worker/scheduler живут
(ingestion_live success, VisionMediaWorker tick OK). Не связано с F1-дельтой;
откат не требуется.

## Откат (задокументирован, НЕ применялся)

- Cold: `git -C /var/www/admin_bot checkout -f e3c61445deabd4cdd4366bc205712f9325c88ac3`
  (== `origin/release/fix-2.58.101`, verified on prod) +
  `sudo systemctl restart admin_bot` → 2.58.101. Потерь нет: ΔDDL=0,
  схема/данные не менялись, промпт-каноны не переписывались (0 обновлений,
  F1 0 set-calls) — откат состояния PG не требуется.
- Повторный выкат 2.58.102 безопасен (идемпотентен; лестницы no-op на кастомах).

## Release-гейт

`requirements_gate.py check --map plans/features/cfg/requirements-map.json
--stage release --repo .` (карта — вся фича CFG, 246 инвентарных строк):
- `--candidate a3535b68 --deployed-commit a3535b68` → **EXIT 1, errors=453**
  («candidate mismatch»: карта привязана к 211a8c1b + открытые волны/ADD-0.x
  PENDING/исторические биндинги);
- `--candidate 6388899d --deployed-commit a3535b68` → **EXIT 1, errors=454**
  (то же + review-stage биндинг кандидата F1).
Структурно красная открытая карта — прецедент deploy-258100/258101: поезд не
заявляет DONE фичи; релиз-вердикт поезда — Orchestrator/Reviewer на базе
review-rel §3 + этой трассы.

## SSH-бюджет и гигиена

4 коннекта, один логин `nik`, паузы ≥70–85 с, без параллелей/поллеров:
recon (16:56:07Z) → основной №1 (16:58:01Z, **аборт по дефектному гейту
CAND_TO_OM_NONPLANS=0**: бамп поверх кандидата легитимно несёт 30 non-plans
пинов; в прецеденте dp101 это INFO, не гейт; дерево автоматически восстановлено
в e3c61445, рестарта не было, сервис не затронут) → основной №2 (17:00:25Z,
успешный) → финал (17:04:17Z). Пароли только через stdin (sudo -S) и env
git-credential, в argv/логе не печатались. Внешние пробы — HTTPS 443.
Инцидентов fail2ban нет.

## Файлы

- `deploy.md`, `deploy.json` (этот каталог); сырьё —
  `OPENCODE_WORKFLOW_SCRATCH/deploy-258102/`: `recon102.txt` (включая
  PRE-байт-снимок 7 ключей + провенанс-док), `main102-run.txt`,
  `journal102-since-T0.raw`, `journal102-final.raw`, `final102-run.txt`,
  `t0_102.txt`, скрипты `rc102/dp102/fn102` (.py).
