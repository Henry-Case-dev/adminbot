# Изолированный релиз **CFG-01** как **2.58.88** — REL-CFG-01

Дата: 2026-10-18 (UTC). Лейн: release (writer).
Статус: **в работе** — заполняется по мере деплоя (live-часть ниже).

## 1. Состав (изоляция)

| Роль | Значение |
|---|---|
| База (прод до релиза) | `82e110d67120b86373fb23a81c8612ec5143a589` = 2.58.87, все оси ON |
| Кандидат (Approved) | `0282fe4b1eac02c3339586c3abab3952d6c7eae8` (bind `912c79b8`, R2 `22d571b6`) |
| Порт-коммит (6 файлов) | `e25163b7b51bfd5911ac2cbd6a82b26a0aed0a8e` |
| Bump-коммит (31 файл) | `c37b85779cc41ad716304024ebeea86ad4081071` — **деплой-тип** |
| Delta vs прод | **37 файлов** = payload 6 + bump 31 |
| UNCLASSIFIED | **0** (`isolation-classification.txt`) |
| Payload == кандидату | byte-equal (`equivalence.txt`: `git diff 0282fe4b HEAD -- <6 файлов>` пуст) |
| WG byte-equal | fullscreen-policy / glass-refraction / glass-probe / тесты / e2e-инструмент — байт-в-байт проду |
| SOUL-набор | byte-equal проду, кроме `services/direct_chat_service.py` (намеренная CFG-01-дельта) |
| web/* и handlers/* | 0 изменений (frozen-check §1) |
| Секрет-скан delta | 4 хита — русские плейсхолдер-литералы в py-пин-тестах (bump), не креды |

sha256_12 payload-файлов: `persistent_throttling.py 1a222e926aeb` ·
`chat_params.py f480530b6c12` · `direct_chat_service.py 7a613dc9b406` ·
`test_direct_chat.py 0a9d87735e8d` · `test_direct_chat_concurrency.py b1e1e3b1cff9` ·
`test_persistent_throttling.py 9f3f96afff27`.

## 2. Preflight (точное дерево ветки; `preflight/**`, `preflight-summary.txt`)

| Проверка | Результат |
|---|---|
| `tests/test_direct_chat.py test_direct_chat_concurrency.py test_persistent_throttling.py` | **204 passed** |
| `-k Cfg01` (2 файла) | **7 passed, 167 deselected** |
| `tests/test_soul1_style_policy.py` | 61 passed |
| SOUL-набор `test_soul1_*.py` (30 файлов) | **600 passed** |
| parity | **13 passed** |
| registry `--check` | **CHECK OK: 575 == REGISTRY** |
| node guards | **87/87** |
| refraction e2e | **37/37, WG-REFRACT-E2E-OK** |
| shell e2e | **W2-SHELL-E2E-OK**, console_errors `[]` |
| fs e2e | **12/12 PASS** |
| frozen-check | **RESULT OK** (web/handlers/tools не тронуты, CFG-маркеры на месте, anti-bypass вход byte-equal) |
| seam consumers (config-слой + direct-consumers) | 202 passed |
| NOTIFY/TTL (`test_settings_worker_sync_round1018.py`) | 31 passed |

Девиация тулчейна: первичный прогон e2e через глобальный `py -3` упал
(`ModuleNotFoundError: playwright`), трио перезапущено repo-venv
(playwright 1.62.0) и прошло — см. `preflight-summary.txt`.

## 3. Деплой

Выкат: 2026-10-18 00:29:20–00:30:40Z, T0-hardened `deploy_25888.py` (адаптация ревьюенного
`deploy_25887.py`, `bb3efc16…`); один основной SSH-прогон + лёгкий recon (00:29:13Z, до выката
прод `82e110d6`/2.58.87). fail2ban-дисциплина соблюдена: без ретраев/поллеров, секреты
заскраблены. Raw: `deploy-run.txt`, `deploy-console.txt`, `final-verification.txt`.

| Фаза | Результат |
|---|---|
| A pre-state | OLD_HEAD=`82e110d6`, branch `release/fix-2.58.87`, healthz 2.58.87, TRACKED_MOD=0, service active, MAINPID `3254462`, ENV_AXES=5, index.lock отсутствует |
| B fetch | `origin/release/cfg1-2.58.88` = `c37b8577…` (ветка уже на origin) |
| C checkout | `release/cfg1-2.58.88`; NEW_HEAD=`c37b8577…`; TRACKED_MOD_AFTER=0; DELTA_FILES=37 |
| D bind | sha256_12 **20/20** == ожидаемых (6 payload + 3 bump + 11 SOUL-sanity); маркеры APP_VER=2.58.88 / CFG_RESOLVER=2 / CFG_SOURCED=1 / CFG_EVENT=1; CSS=d700df753d6d |
| F restart | RESTART_T0=`2026-10-18 00:29:28Z`; graceful stop старого PID (`[shutdown] runtime sqlite closed`, 00:29:29Z); PID-anchored F3: новый MAINPID `3275019`; `migrations: complete \| user_version=36 \| pending=[]`; healthz **2.58.88**; журнал since T0: 0 |
| G posts | `cfg01_post.py` — 28/28 (§4) |
| J final | HEAD=`c37b8577`, TRACKED_MOD=0; MainPID `3275019`, **NRestarts=0**, ExecMainStart 00:29:45Z; ERR=0/RUNTIMEWARN=0; оси .env 5/5 ON; CFG-маркеры в деплой-байтах; app.css (диск/HTTP) d700df753d6d; HTTPS_HZ 2.58.88, HTTPS_WEB=200 |

Автотриггер отката не срабатывал (healthz 2.58.88 наблюдался). T0 подтверждён сверкой
до/после: PID, время старта, journal-окно.

## 4. Живые пост-проверки

`cfg01_post.py` (raw: `post-check.txt`; событийная строка — в хвосте `deploy-run.txt`):
**SUMMARY ok=28/28**.

* A1/A2: healthz 2.58.88; админ-доступ; SOUL-оси 10/10 ON.
* B1–B6: эффективные лимиты Direct (глобально 10 / 300 s, per_chat=true) и источник резолва.
* C1–C5: глобальный burst 10→2 **без рестарта** виден в hot-readback и в эффективном
  значении Direct; возврат 10 (readback-окно 0.3 s).
* D1–D5: per-chat override (burst=2) виден c `source='chat'`, соседний чат не затронут;
  reset вернул наследование (10/'' при global=10).
* E1–E6 (прод-БД, синтетические строки, затем cleanup=0): кламп 10→2 после 5 израсходованных —
  допуски 6/7 = 0.0, 8-е — отказ 300 s; изоляция по user; cooldown=0 открывает окно;
  refill-инвариант; увеличение лимита без «бонусных» зарядов.
* F1–F3: plumbing события `direct_chat_throttle` — durable-строка (mca_events) + вьюер логов
  (`events=1 / matched=1`).

Настройки владельца восстановлены (C4/C5, D4/D5; E6 leftover=0) — ничего не оставлено изменённым.

Внешний речек с harness REL-CFG-01: `https://admin-bot.duckdns.org/healthz` →
`{"status":"ok","version":"2.58.88"}` (verified TLS), `/web/` 200.

Речек 04:41Z (`recon-final.txt`): HEAD=`c37b8577`, TRACKED_MOD=0, healthz 2.58.88,
MainPID `3275019`, NRestarts=0; graceful-стоп старого процесса подтверждён полностью —
`graceful-probe.txt` (polling stop graceful=True, drain in_flight=0/cancelled=0,
runtime sqlite closed 00:29:29.703Z, `[shutdown] bye` 00:29:34.909Z, betterstack flush).
Окно с 00:29:25Z — 7980 строк, единственное ERR-паттерн-совпадение: WARNING `L2_ERROR …
legacy fallback` (01:10:24Z; штатный LEVEL-3 fallback summary), за последние 3 ч — 0
(`err-probe.txt`). Реальный дрейф ERR/CRIT = 0.

OWNER_E2E_PENDING (чисто-UX/владелец; агентски недоступного не осталось):
1. реальный чат: 3-е сообщение подряд на лимите 2 — фраза с фактическим остатком
   («через N мин …»), без ложного «технически не могу» (README §5 п.1/3);
2. MiniApp: видимость источника (чат/глобально/заводской) по ключу (README §5 п.3);
3. сверка usage-окна отказа владельцем при желании (движковый факт «отказ до LLM»
   подтверждён E1+F2: событие `skipped/cooldown` до дорогого вызова) — README §5 п.4.

## 5. Rollback

* Код: `release/fix-2.58.87` (`54a69f32…`) — прежние байты 2.58.87; оси `.env` не менялись
  (5/5 ON до и после).
* Триггер в скрипте: healthz != 2.58.88 после рестарта → checkout rollback-ветки + graceful
  restart. Не потребовался.
* Данные: DDL-миграций нет (Δ=0, `user_version=36` до и после) — откат кода безопасен.
* Пост-откат: healthz 2.58.87 + `NRestarts=0` (процедура релиза 2.58.87).

## 6. Девиации

* `deploy_25888.py` — адаптация ревьюенного T0-hardened `deploy_25887.py` (`bb3efc16…`):
  обновлены EXPECT_TIP/EXPECT12/UPLOADS/branch; структура фаз та же.
* Preflight e2e-трио: первый заход — не тот интерпретатор (global `py -3`,
  `ModuleNotFoundError: playwright`); честно перепрогнан repo-venv (playwright 1.62.0),
  оба raw-лога сохранены (`preflight-summary.txt`, NOTE).
* Воркер №1 REL-CFG-01 прервался на лимите провайдера сразу после деплоя/постов — до
  финализации отчёта и push. Продолжение (речек/артефакты/леджер) — `recon-final.txt`,
  `err-probe.txt`; деплой НЕ перезапускался.
* 2 RED в `tests/test_asap7_direct_settings.py` — PRE-EXISTING (воспроизводятся на базе
  `43f86ef2` без правок CFG-01), вне скоупа.

## 7. Ledger

* `plans/features/cfg/requirements-map.json`: `deployed_commit` :=
  `c37b85779cc41ad716304024ebeea86ad4081071`; `candidate_commit` =
  `0282fe4b1eac02c3339586c3abab3952d6c7eae8` (dual-line «reviewed candidate ↔ deployed commit»).
* 4 live-строки остаются `READY_FOR_LIVE` (не `VERIFIED`): `CFG-01.6`, `CFG-01.AC1`,
  `CFG-01.AC2`, `CFG-01.AC4` (owner/postdeploy).
* Гейты после re-anchor (verbatim):
  * `check --stage plan` → `stage=plan inventory=246 manual=41 scoped=0 errors=0` (EXIT 0);
  * `check --stage review --slice CFG-01 --candidate 0282fe4b…` →
    `stage=review inventory=246 manual=41 scoped=13 errors=0` (EXIT 0);
  * release-стадия не запускается (ждёт 4 RFL).
