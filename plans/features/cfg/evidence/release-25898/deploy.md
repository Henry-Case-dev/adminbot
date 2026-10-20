# DEPLOY-25898 — evidence: выкат 2.58.98 (UNIFIED-CORE + R1-fixes + bump)

Релиз: **2.58.98** — поезд: **UNIFIED-CORE** (`37097f7c`; единый Personality
Core+Expression+Style на всех user-facing маршрутах, директивы владельца
off/occasional/frequent, C-фиксы) + **R1-fixes** (`1b23d4c9`; RECHECK-25898-R1
Approved) + **bump** `f9e7dd67` (31 файл: settings/README/F8-meta/28 пинов) +
docs (`29cc49ba`). Ревью-кандидат: **REV-REL-25898 Approved**
(`plans/features/cfg/evidence/release-25898/review-rel.md`; шаги 1–2 ревью —
push и рубеж отката — выполнены до лейна).

- **Фактический deployed SHA: `29cc49baa4c4a2e25ac5907470dbc18f62ed69bc`**
  (= `origin/master`; runtime-байты идентичны релизному `f9e7dd67`:
  `CAND_TO_OM_NONPLANS=0`, т.е. после `f9e7dd67` только plans-docs).
- Прод ДО: `99f5672c` (2.58.97, healthz 2.58.97, MainPID 3791730) →
  ПОСЛЕ: **`29cc49ba` (2.58.98)**.
- **DEPLOY_SOURCE:** `origin/master` (иммутабельный коммит; fetch
  `99f5672c..29cc49ba`). **MUTABLE_WORKTREE_REQUIRED: no** — запись только в
  прод-репо (`checkout -B master origin/master`, `/tmp`) и DevOps-scratch;
  репо DevOps-машины не менялось, кроме этого evidence-каталога.

## Дельта-изоляция (vs 2.58.97 `99f5672c`)

- `DELTA_TOTAL=250`; **`DELTA_RUNTIME` 19/19 set-eq** вайтлисту:
  `config/settings.py`, `handlers/checkup.py`, 16× `services/*`
  (checkup/direct_chat/factcheck_prompts/factcheck_service/mca_expression/
  mca_humor_craft/nostalgia_prompts/prompt_composer/prompt_migrations/
  prompt_registry/prompt_style_blocks/response_extent/search_service/
  summary_generator/web_summarizer/youtube_summarizer), `web/api/speech.py`.
- `DELTA_OTHER_NONSTD=0` — всё остальное строго `plans/ | tests/ | README.md`.
- Примечание: бриф лейна описывал дельту как «только версии/пины/леджер-docs»;
  фактическая runtime-дельта = UNIFIED-CORE + R1 + bump — ровно как
  зафиксировано в review-rel.md §4. Верифицировано по git и PKG.
- **Хэши 24/24 sha256_12 == кандидату** (`29cc49ba` ≡ `f9e7dd67` по runtime):
  settings `d8f56d928859` (=PKG frozen-fingerprint), README `bb3de3547148`,
  F8-meta `69c5248d05a5` (=PKG), 19 runtime-файлов + web/app.js
  `885094459700`, web/index.html `528f358a6589`, web/static/app.css
  `6b5ca0cc1d47` (последние три не менялись с 97).
- Маркеры: `APP_VERSION = "2.58.98"` ×1; F8-meta HEAD-штамп `1b23d4c` ×1;
  UNIFIED-CORE: `CORE_` speech 26 / registry 25, `occasional` mca 15 /
  composer 1 (== локальным эталонам `29cc49ba`); kill-switch
  `EXPRESSION_EXAMPLES_ENABLED` в `services/mca_gates.py` на месте (=2).
- `TRACKED_MOD=0` до и после; `UNTRACKED=13` — pre-existing (как в 95–97).

## Рестарт и здоровье

- T0 (рестарт, server UTC): **2026-10-20 02:38:53Z** (epoch 1792463933),
  RESTART_RC=0; новый **MainPID 3883387**, **NRestarts=0**, ExecMainStart
  02:39:10 UTC, ExecMainStatus=0, active/running. Цепочка 25896→25897→25898
  непрерывна (PID 3791730 работал с 19.10 19:13:43Z).
- healthz loopback = `2.58.98` к 02:39:36Z; внешне (HTTPS, машина DevOps,
  02:47Z): `/healthz` 200 `2.58.98`, `/web/` 200, `/static/app.css` 200.
- Served-байты: `/web/app.js` == диск байт-в-байт (`SAME`, 1283831B,
  `885094459700`); served index `bb9099d77e17` со штампами `v=2.58.98`,
  неиссённых `__APP_VERSION__` 0; `/static/app.css` served `db73d73a80bc`
  **точно воспроизведён** из проверенных байтов диска + штатных
  преобразований неизменённого кода раздачи (`web/app.py:_render_app_css`:
  universal newlines 6×CRLF→LF + подстановка версии; 234959B) — см.
  scratch `_css_subst_check3.py`. В 97 сверка served-CSS была иной
  (SAME на сырой диск); поведение раздачи в поезде 98 не менялось.

## Журнал since T0 (212 строк, сырой лог в scratch)

- **ERR=0, ERR_402=0, SKIPS=0** («maximum number of running instances»),
  RUNTIMEWARN=0, **[local-bot-api]** стартовый маркер =1.
- Ожидаемого shutdown-шума (CancelledError старого процесса) **не возникло**
  (рестарт без in-flight генерации); GRACEFUL=2 — drain-строки остановки
  старого PID 3791730, штатные. Новый процесс — ни одного ERR/CRITICAL.
- DDL: `[database] migrations: start | user_version=36 | pending=[]` →
  `complete | user_version=36` — **ΔDDL=0**; прямой ro-запрос
  `pragma user_version` = 36.
- Prompt-миграции (стартовые, дизайн UNIFIED-CORE): канон обновлён у 1 ключа
  (`prompts.factcheck_analyst_system_prompt`), **13 owner-кастомов сохранены**
  («кастом юзера — НЕ трогаем»), остальные «уже новый канон»;
  config-миграции: owner-кастомы preserved, skip по выключенной ветке.

## Честные девиации

1. **Первый main-прогон прерван гейтом до рестарта** — два бага МОЕГО
   чекера (инвертированный словарь хэшей; NONSTD-фильтр не исключал сами
   runtime-файлы). Auto-restore сработал: дерево → `release/fix-2.58.97`,
   сервис не перезапускался (PID 3791730 сохранён), прод-эффект нулевой.
   Второй прогон — все гейты зелёные. Хэши из обоих прогонов идентичны.
2. SSH-коннекты лейна: **4** (recon 02:27:27Z; main-abort 02:37:15Z;
   main-ok 02:38:48Z — пауза ~1 мин; probe 02:43:48Z) — один логин `nik`,
   без параллелей/ретрай-спама, fail2ban не задет. Пароли — только через
   stdin (`sudo -S`, credential-helper stdin-скрипта), в логи/argv не
   попали. Статус сервиса до/после дублирован по HTTPS 443 (не ограничен).
3. `DB_PATH`-проба системным python3 пуста (импорту settings нужен venv) —
   заменена журналом приложения и прямым ro-чтением sqlite; на прод не
   влияет.
4. Served-проба №1 в main-прогоне била по неверному URL (`/static/app.js`
   вместо `/web/app.js`) — исправлено read-only probe-коннектом; выводы
   выше сделаны по корректным URL.

## Попутные находки (не блокеры)

- **Low, pre-existing, код вне дельты:** HEAD `/static/app.css` отдаёт
  content-length сырого файла (234981), а GET-тело — 234959 (после
  подстановки версии). Косметика раздачи (маршрут `web/app.py`, не менялся
  в 98-поезде); браузеры используют GET-тело. В отдельный фикс-бэклог.
- Served-index отличается от 97 (`bb9099d77e17` vs `1dda147e41d6`) —
  ожидаемо: штампы версии 2.58.97→2.58.98.

## Откат (не потребовался)

- Рубеж: `origin/release/fix-2.58.97` = `99f5672c` (на проде, локальная
  ветка создана при restore); abort-механика проверена в деле (девиация 1).
- Post-restart откат: `git checkout -f release/fix-2.58.97 && sudo
  systemctl restart admin_bot` (2.58.97).
- Soft-откат: PREV-лестница ADR-1013-3 + env-kill-switch
  `EXPRESSION_EXAMPLES_ENABLED` (default ON, в `.env` отсутствует — как в
  96/97); директивы речи — owner-config, env-флага не требуют.

## Остаток (вне этого лейна)

- Постдеплой-обязательство ревью (шаг 4): **F4-матрица на живом 2.58.98**
  (off/occasional/frequent, пороги §4) → VERIFIED/FAILED →
  `requirements_gate.py check --stage release --candidate f9e7dd67
  --deployed-commit 29cc49ba…`. До этого EXP-ACCEPT.CRITERION =
  READY_FOR_LIVE (live_when=postdeploy), родитель не DONE.

## Файлы

- `deploy.md`, `deploy.json` (этот каталог); сырые логи —
  `OPENCODE_WORKFLOW_SCRATCH/deploy98/`: `recon98.txt`, `deploy98-run.txt`
  (гейты/journal/served/final), `journal98-since-T0.raw` (212 строк),
  `probe98-served.txt`, `https-before.txt`, `https-after.txt`,
  `expected-hashes-29cc49ba.txt`, скрипты `recon98.py`/`main98.py`/
  `probe98.py`, `_css_subst_check3.py` (воспроизведение served-CSS).
- Времена (server UTC): recon 02:27:27Z; main-abort 02:37:15–02:37:45Z;
  main-ok 02:38:48–02:39:41Z (T0 02:38:53Z, старт нового PID 02:39:10Z);
  probe 02:43:48Z; внешние HTTPS-пробы 02:47:20Z (локаль машины UTC+12).
