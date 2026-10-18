# Release evidence — CFG-01 → 2.58.88 (REL-CFG-01)

Что это: пакет доказательств релиза **CFG-01** («Direct Chat burst/cooldown:
effective-лимиты, hot-reload, остаток, анти-обход») в составе версии **2.58.88**.
Ветка `release/cfg1-2.58.88`, деплой-коммит **`c37b85779cc41ad716304024ebeea86ad4081071`**,
reviewed candidate **`0282fe4b1eac02c3339586c3abab3952d6c7eae8`** (payload 6 файлов
byte-identical, `equivalence.txt`). Прод до выката: `82e110d6…` = 2.58.87.

## Изоляция

* delta vs прод `82e110d6` = **37 файлов**: 6 CFG-01 payload + 31 bump (2.58.87→2.58.88);
  `UNCLASSIFIED = 0` — `isolation-classification.txt`, `delta-vs-base.txt`, `delta-files-with-stats.txt`.
* SOUL-рантайм byte-equal (единственное намеренное исключение — CFG-01-точка
  `services/direct_chat_service.py`) — `soul-byte-equal.txt`.
* WG-артефакты (fullscreen/glass) byte-equal — `wg-byte-equal.txt`; `web/*`/`handlers/*`
  не тронуты — `equivalence.txt`.
* sha256_12 payload/hash-таблица — `hashes.txt`; секрет-скан delta-файлов — `secret-scan.txt`
  (4 совпадения — литералы-маркеры внутри тестов, не креды).

## Preflight (ветка = tip `c37b8577`)

`preflight-summary.txt` + raw-логи в `preflight/`:

| Проверка | Результат |
|---|---|
| `tests/test_direct_chat.py test_direct_chat_concurrency.py test_persistent_throttling.py` | **204 passed** |
| `-k Cfg01` | **7 passed**, 167 deselected |
| SOUL-набор `test_soul1_*.py` (30 файлов) | **600 passed** |
| parity | **13 passed** |
| registry `--check` | **575 == REGISTRY** |
| node guards | **87/87** |
| refraction e2e | **37/37, WG-REFRACT-E2E-OK** |
| shell e2e | **W2-SHELL-E2E-OK**, console_errors `[]` |
| fs e2e | **12/12 PASS** (скриншоты `fs-e2e/`) |
| frozen-check | **RESULT OK** |
| seam consumers | 202 passed |
| NOTIFY/TTL | 31 passed |

## Деплой

Raw: `deploy-run.txt` (UTF-8), `deploy-console.txt` (тот же прогон, нормализован из UTF-16),
`recon88.txt` (до выката: 2.58.87/`82e110d6`), `final-verification.txt` (read-only J-фаза).

* 2026-10-18 00:29:20–00:30:40Z, T0-hardened `deploy_25888.py` (адаптация ревьюенного
  `deploy_25887.py`, `bb3efc16…`); фазы A–D: HEAD `c37b8577`, `TRACKED_MOD=0`, delta 37,
  sha256_12 **20/20**.
* Graceful restart `RESTART_T0=2026-10-18 00:29:28Z`; PID-anchored ожидание миграций:
  новый MAINPID `3275019`, `migrations: complete | user_version=36 | pending=[]`.
* healthz **2.58.88**; журнал since T0: **ERR=0**, RUNTIMEWARN=0; `NRestarts=0`;
  `.env` оси 5/5 ON; CFG-маркеры в деплой-байтах; app.css (диск+ HTTP) `d700df753d6d`;
  HTTPS_WEB=200. Автотриггер отката не срабатывал.

## CFG-01 пост-проверки (28/28)

`post-check.txt`: **SUMMARY ok=28/28** — effective-лимиты + источник резолва;
global 10→2 hot без рестарта → возврат 10; per-chat override + reset (наследование
восстановлено); прод-БД механика с синтетическими строками (кламп 10→2 после 5,
cooldown=0, refill-инвариант, увеличение без бонуса, cleanup=0); durable-событие
`direct_chat_throttle` + вьюер логов (`events=1/matched=1`). Настройки владельца
восстановлены (ничего не осталось изменённым).

## Речек REL-CFG-01 (продолжение)

`recon-final.txt` (2026-10-18 04:41Z, один read-only коннект): HEAD `c37b8577`,
TRACKED_MOD=0, healthz 2.58.88, MainPID `3275019`, `NRestarts=0`, graceful-стоп
старого процесса (`[shutdown] runtime sqlite closed`, 00:29:29Z; полная
последовательность — `graceful-probe.txt`: polling stop graceful=True, drain
in_flight=0/cancelled=0, `[shutdown] bye` 00:29:34Z). Единственное
ERR-паттерн-совпадение в окне — WARNING-строка `L2_ERROR … legacy fallback`
(01:10:24Z, штатный LEVEL-3 fallback summary; за последние 3 ч повтор 0) —
`err-probe.txt`. Внешне с harness: `https://admin-bot.duckdns.org/healthz` = 2.58.88
(verified TLS), `/web/` 200.

## Остаток

4 live-строки карты остаются **`READY_FOR_LIVE`** (owner/postdeploy, не `VERIFIED`):
`CFG-01.6`, `CFG-01.AC1`, `CFG-01.AC2`, `CFG-01.AC4` → чисто-UX/владельческий E2E
(реальный чат: фраза с остатком; MiniApp: источник) — см. §5
`evidence/cfg-01/README.md` и §4 `release-2.58.88-report.md`.

Rollback: `release/fix-2.58.87` (`54a69f32…`), Δ DDL=0 (user_version=36 не менялся).
