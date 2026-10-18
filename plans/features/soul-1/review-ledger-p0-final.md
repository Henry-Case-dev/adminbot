# VERIFY-LEDGER-FINAL — вердикт (финальный леджер P0)

Независимая проверка коммита `4ecd2595` (2 карты, +225/−27). Read-only; этот коммит — только данный документ.

## 1. Карта A (`requirements-map.json`) — подтверждено
Счётчики: **V23/RFL2/P10 → V27/RFL0/P8**. Статусные изменения — ровно 4: `P0A-PERSIST-SECTIONS`/`-TRUTH` (RFL→V), `P0A-ACCEPT-INITIATIVE`/`P0A-ACCEPT-UX` (P→V). `P0A-OPS-REPORT`, `P0A-DONE` и 6 context-строк не тронуты (PENDING-8 = 6 context + REPORT + DONE).
**Rebind:** 13 строк (`INIT-CURSOR/DIRECT/COOLDOWN/STATUS`, `PERSIST-AUDIT/CAUSE/CENTRAL`, `UX×6`) получили **по +1 production-записи @`3b02366e`** (journal-25890.json, acceptance-bc-read, acceptance-25890/payload/edges, final-verification) — при 0 удалённых и 0 изменённых прежних записях (сохранены). `INIT-DIAG`/`INIT-PROOF`: пин `acceptance-bc-25890-read.json` обновлён `8cc9914d… → 9fbafd2f…` (файл перегенерирован phase-2); старый хеш в картах не встречается (0). `scan=280` присутствует в observations (`scan=280/opportunity=6/decided=4/writer_generated=2/sent=2`).

## 2. Карта B (`requirements-map-followup.json`) — подтверждено
Счётчики: **V3/RFL3/P35 → V6/RFL1/P34**. Закрыто: `NOST-DIAG` (pre+post-деплой диагностика; `nostalgia_log` #217 `no_candidates`/#218 skipped/unchanged, PET=10), `NOST-SCEN-A` (live `scenario=A` 18.10 14:40:03Z, silence 13 мин → гейты не применяются, честные skip-причины `no_candidates`), `LIVE-FUNNEL` (воронка **scan=280 → opportunity=6 → decided=4 → writer_generated=2 → sent=2**; планировщик как доказательство не использовался). `NOST-SCEN-B` остаётся RFL с честным note («ждёт естественного затишья; механизм подтверждён кодом+тестами+A-строки живые; не блокирует»). `GOAL`/`LIVE-SCENARIOS` — **НЕ закрыты консервативно и честно**: notes явно перечисляют непонаблюдённое (GOAL: «не наблюдалось доставленное воспоминание после T0 — главный критерий не закрываю»; LIVE-SCENARIOS: «миллион сообщений+новая беседа, новый чат 5–20, сотни/тысячи пропущенных, рестарт/импорт — строка остаётся открытой»).

## 3. Счётчики и пины — пересчитаны
Обе карты пересчитаны мной (сходится п.1–2). Свежие пины на диске: 8/8 OK (`9fbafd2f…`, `70f9ffa4…`, `d0fc9ee8…`, `611093c9…`, `3fce7193…`, `d3278c13…`, `ada8b2bc…`, `f72f051c…`). Полный аудит: **69 записей, 32 уникальных пути — 32/32 match, 0 stale, 0 missing**, конфликтов sha по одному пути нет.

## 4. Гейты (мой прогон verbatim)
- A plan: `stage=plan inventory=22 manual=13 scoped=0 errors=0` **EXIT 0**.
- B plan: `stage=plan inventory=26 manual=15 scoped=0 errors=0` **EXIT 0**.
- A release `--candidate 3b02366e… --deployed-commit 3b02366e…`: **ровно 2 ошибки** — `P0A-OPS-REPORT` и `P0A-DONE` (`mandatory not ['VERIFIED'] (got PENDING)`), `errors=2` EXIT 1; ничего сверх (13+8 прежних FAIL'ов сняты rebind'ом).

## 5. Замечания
Блокирующих нет. Открытыми честно остаются: A — `OPS-REPORT`/`DONE` (pending, для них и держится EXIT 1 релиз-стадии); B — `SCEN-B` (естественное затишье), `GOAL`, `LIVE-SCENARIOS`. Маскировки закрытия нет: незакрытое явно и обосновано.

## Вердикт
**Approved.**
