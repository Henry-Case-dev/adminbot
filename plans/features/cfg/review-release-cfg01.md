# REVIEW-RELEASE-CFG-01 — независимая сверка финального оформления релиза CFG-01 → 2.58.88

| Поле | Значение |
|---|---|
| Ветка | `release/cfg1-2.58.88` tip **`35789982`** (docs-only: 60 файлов, +2196, все пути `plans/features/cfg/**`); master **`829e39d1`** (леджер) |
| Прод | **2.58.88** (`c37b8577`), выкат не перезапускался; reviewed candidate `0282fe4b` (payload 6 файлов byte-equal — `equivalence.txt`) |
| Вердикт | **Approved** |

## 1. Артефакты релиза — полный комплект, docs-only

- Цепочка ветки: `e25163b7` (port 6 файлов) → `c37b8577` (bump 31) → `35789982` (docs 60). У `35789982` **0 прод-файлов** (фильтр по путям вне `plans/features/cfg/**` пуст).
- `release-2.58.88-report.md`: §1–§7 заполнены — изоляция (delta 37 = 6 payload + 31 bump, UNCLASSIFIED=0, SOUL/WG byte-equal, sha256_12 payload), preflight (204 / **7** / 600 / 13 / 575 / 87/87 / 37/37 / 12/12 / frozen OK / 202 / 31), деплой (фазы A–D+F+G+J: HEAD `c37b8577`, sha 20/20, RESTART_T0, MainPID `3275019`, `user_version=36/pending=[]`, healthz 2.58.88, ERR=0, NRestarts=0), живые посты **28/28** (hot-reload 10→2→10 без рестарта, override+reset, прод-БД кламп/cooldown=0/refill/бонус, durable-событие), §5 rollback (`release/fix-2.58.87`, Δ DDL=0), §6 девиации (в т.ч. прерывание воркера №1 сразу после деплоя/постов — выкат НЕ перезапускался), §7 леджер.
- README-индекс `evidence/release-25888/README.md` существует (5077 B): изоляция/preflight/деплой/посты/остаток/rollback.
- Переносы из scratch **на месте**: `e2e-console.txt`, `deploy-console.txt`, `fs-e2e/**` (19 файлов: S1–S12 скрины + `_results.json`), `wg-e2e/**` (6: 5 PNG + `_results.json`), `recon-final.txt`, `err-probe.txt`, `graceful-probe.txt`.
- Нормализация (3 файла): `e2e-console.txt`, `deploy-console.txt`, `preflight/preflight-console.txt` — в scratch UTF-16LE+BOM (1992/15302/3364 B), в репо — валидный UTF-8 (991/7493/1666 B), кириллица восстановлена и читаема (сверил scratch → repo: «4 проверок» вместо mojibake). Скан всех `*.txt` в `evidence/release-25888/**`: 100% валидный UTF-8, 0 mojibake-файлов.

## 2. Леджер — dual-line и статусы корректны

- `829e39d1`: 1 файл (карта), 1+/1− — `deployed_commit := c37b85779cc4…`; `candidate_commit = 0282fe4b…`; strict+graph.
- 13 строк CFG-01: **9 VERIFIED** + **4 `READY_FOR_LIVE`** (`CFG-01.6/AC1/AC2/AC4`, `live_when=postdeploy`, live_note; **не VERIFIED** — верно).
- Гейты (мой прогон, verbatim): plan → `stage=plan inventory=246 manual=41 scoped=0 errors=0` **EXIT 0**; review `--slice CFG-01 --candidate 0282fe4b…` → `stage=review … scoped=13 errors=0` **EXIT 0**.
- Нит N-R2-1 закрыт: `d4fc3680` добавил sha256 для 2 записей `review-cfg-01.md` (проверил наличие в истории master).
- Для сведения: release-стадия карты — **родительская** (whole-map; даже с `--slice CFG-01` проверяет `scoped=244` — сработает после остальных слайсов и закрытия 4 RFL; текущий EXIT 1 ожидаем и не является дефектом этого релиза).

## 3. Факты прода — независимый HTTPS-чек (мой)

- `https://admin-bot.duckdns.org/healthz` → **200** `{"status":"ok","version":"2.58.88"}`.
- `/web/static/app.css` → **200**, 216171 B, sha256_12 = **`d700df753d6d`** — **совпадает байт-в-байт** с деревом релиза (`wt` @`c37b8577`: те же 216171 B и sha) → SOUL-byte паритет подтверждён напрямую из прода.
- Push: `origin/release/cfg1-2.58.88` = `35789982` (совпадает с локальным tip; ahead/behind **0/0**); `origin/master` = `829e39d1` (ahead/behind **0/0**).
- Девиация «шаг №1 успел деплой+посты» **принята осознанно**: выкат выполнен подготовленным T0-hardened `deploy_25888.py` (адаптация ревьюенного `deploy_25887.py`), фазы A–J зафиксированы в raw-логах; после деплоя НЕ перезапускался; продолжение (речек 04:41Z, graceful/err-probe) в evidence; внешние чеки выше независимо подтверждают состояние прода.

## Рекомендации для остатка (не блокируют)

1. **4 RFL** (`CFG-01.6/AC1/AC2/AC4`): владельческий сценарий `evidence/cfg-01/README.md §5` — реальный чат (фраза с фактическим остатком) и MiniApp (видимость источника); закрытие — при следующем owner-touch (процесс CFG: owner-проверки не блокируют очередь).
2. При следующем SSH-логине — подчистить технические скрипты из `/tmp` (deploy/probe), сервис не трогать (fail2ban-дисциплина: один логин).
