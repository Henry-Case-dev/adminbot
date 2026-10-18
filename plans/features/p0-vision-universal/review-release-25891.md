# REVIEW-RELEASE-25891 — вердикт (релиз 2.58.91: P0V + ADD-TR + CFG-02B + P0-FU)

Независимый read-only аудит релиз-пакета. Деплой и push НЕ выполнялись; этот
коммит — только данный документ.

Биндинг:
* Кандидат: bump `8bc8e9b59b1d4557b1fa072a437b23ba6fcacae3` (tip master
  `d70f3f92`, последний код-коммит `88593e9a`); прод-база **`3b02366e`**
  (2.58.90); отчёт — `ee78110f`; evidence — 12 файлов
  `evidence/release-25891/**`.
* Скрипты (sha256_12, сверено): `deploy_25891.py` **`caeebf41f201`**,
  `rel91_final.sh` **`c41f1d5d17c9`**; база адаптации — финальный 25890
  (`2d47290eeeb0`, sha сверен).
* Оценка велась на текущем дереве + worktree `3b02366e` (создан/удалён мной);
  чужие лейны не смешивались.

## 1. Bump — подтверждено

31 файл (+33/−33): `config/settings.py` (2.58.90→**2.58.91**), `README.md`,
`plans/docs/param-registry-round1025.meta.md` (HEAD-штамп `88593e9a`),
**24 py-пина** и **4 JS-пина**; пересчёт пофайлово — 3+24+4=31. Все несут
2.58.91 (JS — regex-пины); `2.58.90` вне `plans/**` не осталось (git grep —
0 совпадений).

## 2. Дельта — подтверждено

`3b02366e..8bc8e9b5`: всего **316** файлов = 209 `plans/**` + **107** без
plans = **24 runtime** (config 1 + handlers 1 + services 17, вкл. новый
`postgen_vision.py` + web 5) + 78 `tests/` + 4 `tools/` + README — сходится
с доком. `RUNTIME_WHITELIST` скрипта == дельте (равенство множеств, 24/24;
мой офлайн-прогон `check_deploy_25891.py`: EXIT 0). `EXPECT12`: **29/29**
совпали с деревом (24 payload + README + meta + 3 sanity: telegram_send
`e23bced2fdb8`, fullscreen-policy `96db06425079`, prompt_composer
`fd8a2a70d5d7` — их в дельте нет). **init-arch `620ce2b0`**: включён в док
отдельной строкой с обоснованием — принимаю: его runtime-файлы
(`initiative_observer`/`initiative_diagnostics`) реально входят в дельту,
ревью `aee8e95c` Approved; без него состав релиза был бы неполным.

## 3. Числа — подтверждено (выборочно + логи + прямые прогоны)

* `pytest-full.txt`: **14432 passed / 9 failed** (672.72s) — список 9 = 8
  известных пре-существующих (asap7_direct_settings ×2, mca01_tx ×1,
  t5150 ×5 — те же, что в базовом 25890) + `asap5_paradigms::
  test_bootstrap_cooldown_bypass_then_cap`. mca09-флейк не сработал.
* **9-е падение — пре-существующий clock-window; воспроизвёл сам (окно
  сейчас активно: Екатеринбург 01:0x):** точно на прод-базе `3b02366e`
  (worktree) — **1 failed, тот же assert line 104 `(None is not None)`**;
  на кандидате — **1 failed** (тот же); контроль `WORKER_BUDGET_TZ=UTC` —
  **1 passed** на обоих. Механизм: `mca_gates.deep_bootstrap_cap_ok` считает
  попытки от local-midnight (`dream_worker._day_start_ts` +
  `WORKER_BUDGET_TZ=Asia/Yekaterinburg`), тест пишет «now−3h» — при local
  00:00–03:00 попытки уходят в предыдущий день. Тест-файл дельтой не тронут;
  код гейта (`mca_gates`/`dream_worker`) — не в дельте. → не блокер.
* js-sweep: **88/0** (мой прогон); speech e2e **0/21** (мой + evidence);
  vision e2e **0/26** (мой + evidence); фокусные 5 файлов **168 passed**
  (мой: 47+25+15+44+37); реестр **CHECK OK 579** (мой).

## 4. Деплой-скрипт (офлайн-аудит) — подтверждено

Адаптация от финального 25890 (`2d47290eeeb0`) сохранена:
`checked_out = True` сразу после `CO_RC=0`; вайтлист — **равенство множеств**
(`sorted(rt_files) != sorted(RUNTIME_WHITELIST)`); `_tree_restore` →
`release/fix-2.58.90` (локально = `3b02366e`) с fallback `--detach PROD_REF`
и трёхусловным подтверждением (TR_RC/TR_RUNTIME_DRIFT/TR_TRACKED_MOD) +
WARNING/WARNINGS-SUMMARY; константы `PROD_REF=3b02366e`, `BUMP=8bc8e9b5…`,
`EXPECT_VER=2.58.91`, rollback `release/cfg1-2.58.88`, `PAGE_VER=15`/
`SUBST_CSS=2`; G-шаг `SERVED_EQ_*=SAME/DIFF` + `grep -cF`. Пост-рестарт:
healthz 2.58.91 (loop 150×2s), T0 fail-fast, журнал (ERR/RuntimeWarning),
served-bytes, J `rel91_final.sh` (read-only: NODE/HEALTH/ENV-оси (+
IMAGE_FREQ_LIMIT_ENABLED|IMAGE_POSTGEN_VISION_ENABLED), P0V/ADD-TR/CFG-02B
маркеры, сервед-хеши, PAGE/SUBST, `/api/vision/state` без секретов, миграции/
user_version, journal-счётчики VISION_*, smoke-маршруты). UPLOAD
`/tmp/rel91_final.sh` существует; офлайн-чек: hashes 29/29, вайтлист==дельта,
EXIT 0. Авто-откат ПОСЛЕ рестарта — cfg1-2.58.88; abort до рестарта — restore
к 2.58.90 (downgrade исключён).

## 5. Релиз-док — точный

Состав: 7 линий (P0V core/UI, ENTRY/GRID/TOOLS/POSTGEN, CFG-02B) + P0-FU +
пины/F8 + доки — с коммитами и ревью-ссылками; откат — три рубежа
(`release/fix-2.58.90` / `fix-2.58.89` / штатный `cfg1-2.58.88`) + мягкие
двери (CFG-02B OFF, POSTGEN OFF, Vision env); §4-чеклист: (a) healthz/DDL,
**(b) реальные tool calls + Telegram-доставка** (чек-ап, «что на картинке» с
caption, fact_check, одна генерация, чат-изоляция — мандат владельца),
(c) пост-генерация (bounded 8s/20s, OFF-паритет), (d) grid/Vision-UI на
прод-странице + `?v=2.58.91`, (e) SCEN-B оппортунистически (WAITING_EXTERNAL
— не блокер), (f) экономика (лимиты/квоты/burst); риски — backlog TOOLS
(3 пункта), WebView — postdeploy RFL (PET), пре-сущ. падения/флейки, SCEN-B
ожидание, glass-перф — по фактам.

## Находки (не блокирующие)

* F1: в `pytest-attribution.txt` строка «Тест/сервис дельтой не менялись
  (git diff = 0)» неточна: `services/worker_budget.py` **входит** в дельту
  (CFG-02B, +81/−5), хотя сбойный путь (`mca_gates.deep_bootstrap_cap_ok` →
  `dream_worker._day_start_ts`) дельтой не затронут — что я и доказал
  base-репро. Рекомендация: уточнить формулировку (тест не менялся; сервис
  менялся в другой, не связанной части).
* F2: `check_deploy_25891.py` сейчас печатает `BUMP == HEAD: False` — это
  ожидаемо (после бампа есть доки-коммиты); на сборке было True, B3 проверяет
  ancestry, не равенство. Действий не требует.
* F3: ветка `release/fix-2.58.90` пока не запушена — при выкате tree-restore
  пойдёт fallback-detach'ем на `3b02366e` (безопасно); запушить ветку
  рекомендовано (отмечено в §7 дока).

## Вердикт

**Approved.** Bump/дельта/изоляция/скрипт/док сходятся с проверкой; числа
перепрогнаны выборочно и сходятся; 9-е падение полного pytest доказанно
пре-существенно (base-репро байт-в-байт + UTC-контроль); блокеров нет.
Деплой и push не выполнялись: запуск — после push `master` (B3 fail-closed)
и решения оркестратора; §4-приёмка — после выката (RFL-строки).