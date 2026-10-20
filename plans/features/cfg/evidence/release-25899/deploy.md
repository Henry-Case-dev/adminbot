# DEPLOY-25899 — evidence: выкат 2.58.99 + горячее включение фактчек-конвейера v2

Релиз: **2.58.99** — CFG-06 фактчек v2-конвейер (кандидат ревью `46303ecd`,
Approved — `plans/features/cfg/evidence/release-25899/review-rel.md`; финальный
HEAD с docs-хвостом `7142ffcf`). Ревью-кандидат == прод-байты (см. Дельта).

- **Фактический deployed SHA: `7142ffcf47ce4667cf22113c56881d3f1abb29a2`**
  (= `origin/master`; `CAND_TO_OM_NONPLANS=0` — над `46303ecd` только
  plans/evidence, 3 файла → runtime-байты == ревью-кандидату).
- Прод ДО: `29cc49ba` (2.58.98, healthz 2.58.98, MainPID 3883387) → ПОСЛЕ:
  **`7142ffcf` (2.58.99)**.
- **DEPLOY_SOURCE:** `origin/master` (иммутабельный коммит; fetch
  `29cc49ba..7142ffcf` + `release/fix-2.58.98` — рубеж отката, запушен этим же
  лейном: master `9f37c15a..7142ffcf`, ветка = `29cc49ba`).
  **MUTABLE_WORKTREE_REQUIRED: no** — запись: прод-репо (checkout -B master),
  одна строка прод-PG (`bot_settings.flags.factcheck_pipeline_v2`), /tmp,
  DevOps-scratch и этот evidence-каталог.

## Дельта-изоляция (vs 2.58.98 `29cc49ba`)

- `DELTA_TOTAL=167`; **`DELTA_RUNTIME` 12/12 set-eq** вайтлисту:
  `config/settings.py`, `handlers/factcheck.py`, 8× `services/factcheck_*`,
  `services/param_catalog.py`, `services/smart_cache.py`,
  `services/smartmodule_phrases.py`, `services/tool_router.py`.
  `DELTA_OTHER_NONSTD=0` (всё остальное — `plans/ | tests/ | README.md`).
- **Хэши 17/17 sha256_12 == локальным git-блобам `7142ffcf`** (включая
  неизменные web/app.js `885094459700`, index.html, app.css, README,
  F8-meta `3e6f7f581cb1`).
- **Фактчек runtime == `8f220b60`-байтов**: все `factcheck*`,
  `tool_router`, `smart_cache`, `smartmodule_phrases` — blob-равны базе
  `8f220b60`; отличаются только `settings.py`/`param_catalog.py` — ровно
  bump `2.58.99` + каталог (+3 `flags.factcheck_*`, pg_id-литералов 40→43).
- Маркеры: `APP_VERSION = "2.58.99"` ×1; `FACTCHECK_PIPELINE_V2_ENABLED",
  False` ×1 (default OFF в коде); `flags.factcheck_pipeline_v2` в каталоге ×1;
  F8-meta штамп `8f220b60` ×1.
- `TRACKED_MOD=0` до и после; `UNTRACKED=13` — pre-existing (как в 95–98).

## Рестарты и здоровье (оба плановые)

- **Фаза 1 (код, флаг OFF):** T0 **09:40:53Z** (epoch 1792489253),
  RESTART_RC=0; **MainPID 3965603**, NRestarts=0, ExecMainStart 09:41:07 UTC,
  ExecMainStatus=0, active/running. healthz loopback `2.58.99` к 09:41:30Z.
- **Фаза 2 (флаг):** PG-upsert 09:44:06Z → T1 **09:44:07Z**
  (epoch 1792489447), RESTART_RC=0; **MainPID 3966377**, NRestarts=0,
  ExecMainStart 09:44:12 UTC, active/running. healthz `2.58.99` к 09:44:38Z.
- Внешне (HTTPS, `admin-bot.duckdns.org`, машина DevOps): `/healthz` 200
  `{"status":"ok","version":"2.58.99"}`, `/web/` 200, `/static/app.css` 200.
  (По голому IP TLS-handshake не проходит — SNI-хостинг Caddy; не дефект.)
- Served: `/web/app.js` sha12 `885094459700` == диск (не менялся с 98).

## Журнал

- Фаза 1 (213 строк since T0, сырёжка в scratch): **ERR=0, ERR_402=0,
  SKIPS=0, RUNTIMEWARN=0**, CancelledError нет, GRACEFUL=2 (штатный drain
  старого PID), `[local-bot-api]` ×1. `[config_cache] initialized:
  settings=532 roles=4 admins=3`.
- **DDL: `user_version=36 → 36`, `pending=[]` — ΔDDL=0** (v37 samples-ux в
  релизе НЕТ; прямой import-проб системным python3 пуст как в 98 — не влияет,
  журнал приложения авторитетен).
- Prompt/config-миграции: новых нет; 13 owner-кастомов сохранены («кастом
  юзера — НЕ трогаем»), остальное «уже новый канон».
- Фаза 2 (210 строк since T1): ERR=0, ERR_402=0, SKIPS=0, RUNTIMEWARN=0;
  `[config_cache] initialized: settings=532` (строк не прибавилось — ключ уже
  существовал, значение `true` загружено init'ом).

## Включение флага — способ и отклонение от буквы брифа

- `flags.factcheck_pipeline_v2`: до — `false` (ключ сидирован каталогом при
  первом старте 2.58.99 в фазе 1; на recon 09:38Z ключа ещё не было), после —
  **`true`** (jsonb-bool, category `flags`, updated_at 09:44:06.723Z).
- Механика: PG-upsert через прод-venv+asyncpg (DSN из `.env`, не печатался) +
  **один плановый рестарт**. Прецедент — soul-release-prep.md шаг 1.
- **Отклонение от брифа «hot, без рестарта», обосновано кодом:**
  `services/hot_config` читает только RAM-кэш ConfigCache; у `bot_settings`
  НЕТ ни TTL-перечитки, ни LISTEN/NOTIFY-канала; единственный in-process
  сеттер — TMA-авторизованный `POST /api/config`, недоступный DevOps (и
  сообщения в чаты запрещены). Внешняя SQL-запись подхватывается только при
  init (`config_cache.py init → _load_all`). Оба рестарта плановые,
  NRestarts=0.

## Смоук (без сообщений в чаты)

- healthz 200 `2.58.99` (loopback ×2 фазы + внешний HTTPS), маршруты
  web/css 200, ERR=0 в обеих фазах, NRestarts=0 после включения.
- Сообщений в чаты не отправлялось (запрет лейна); органического трафика с
  включённым флагом в журнале нет → **прогонов конвейера v2 ещё не было,
  наблюдение продолжается** (ошибок gate/retrieval/deliver нет — их и не было).
- Видимость флага рантайму: PG=`true` + ConfigCache init загрузил все
  `bot_settings` при рестарте фазы 2 (документированный кодовый путь). Прямой
  рантайм-проб ключа без TMA недоступен — зафиксировано честно.

## Откат (не потребовался)

- **Soft:** PG-upsert `flags.factcheck_pipeline_v2` → `'false'::jsonb`
  (category `flags`) + `sudo systemctl restart admin_bot` (рестарт нужен по
  той же механике, что и включение). wide_context/suitability_gate под v2
  подразумеваются — отдельно не трогались.
- **Cold:** `git checkout -f 29cc49baa4c4a2e25ac5907470dbc18f62ed69bc`
  (= `origin/release/fix-2.58.98`, проверен на проде после fetch: RB_REF ==
  29cc49ba) + рестарт → 2.58.98.

## Попутные находки (не блокеры)

- Info: внешний HTTPS по голому IP не проходит TLS-handshake (SNI) — пробы по
  домену; поведение Caddy, вне репо.
- Info: `flags.factcheck_pipeline_v2=false` появился в PG между recon и
  фазой 2 — каталог-сид новых ParamSpec при старте 2.58.99; ожидаемо.

## Release-гейт и остаток (вне этой полосы)

- `requirements_gate.py check --map plans/features/cfg/requirements-map.json
  --stage release --candidate 7142ffcf… --deployed-commit 7142ffcf…` →
  **EXIT 1** (442 ошибки по полной 246-строчной карте CFG; в т.ч. незакрытые
  post-release строки CFG-06: 06G.1/06G.4 — канарейки на тестовом контуре,
  06G.3 — post-release). `deployed_commit` карты обновлён на `7142ffcf…`.
- Родитель **не DONE**: финальный зелёный `--stage release` — после закрытия
  канареек тестового контура (обязательства ревью, п.3–4 «Постдеплой»).

## Файлы

- `deploy.md`, `deploy.json` (этот каталог); сырые логи —
  `OPENCODE_WORKFLOW_SCRATCH/deploy99/`: `recon99.txt`, `deploy99-run.txt`
  (гейты/journal/served/final фазы 1), `flag99-run.txt` (фаза 2),
  `journal99-since-T0.raw`, `journal99-since-T1.raw`, `expect99.txt`
  (локальные эталоны), скрипты `recon99.py`/`main99.py`/`flag99.py`.
- Времена (server UTC): recon 09:38:15Z; main 09:40:50–09:41:35Z (T0
  09:40:53Z); flag 09:44:04–09:44:41Z (T1 09:44:07Z); внешние HTTPS-пробы
  ~09:47Z (машина DevOps UTC+12).
- SSH-бюджет: **3 коннекта**, один логин `nik`, паузы >1 мин, без
  параллелей/поллеров; пароли — только через stdin; инцидентов fail2ban нет.
