# CFG-02C §Ф6 — live-приёмка на 2.58.94 (ACCEPTANCE-94)

Ссылка-владелец: полный отчёт и evidence —
`plans/features/p0-vision-universal/evidence/release-25894/acceptance/`
(README.md + JSON). Здесь — копии фактов §Ф6 для линии CFG-02C/2.58.93.

Прод: **2.58.94 @ `9072347b986b91f05d580a11c1aae6646b250e29`** (выкат
2.58.93→2.58.94 19.10.2026 08:18:20Z; CFG-02C-код в 2.58.94 не менялся).
Волна: 19.10.2026 09:08:45→09:26:19 UTC. Чат `-1002661910336`, админ-сессия
5885953495.

| Пункт §Ф6 | Факт | Статус |
|---|---|---|
| (b) витрина §02C.5 | served `app.js` содержит «Обложки сводок здесь не учитываются»; served==disk; `/api/workers/budget` отдаёт `cover_used` и разбивку `cover{requests,success}` | **VERIFIED** |
| (c) изоляция live: обложка | budgets ON + user daily=**0** + freq ON → 1 базовая обложка (summary test-run) сгенерирована; журнал `image_reservation.source='summary_cover:base'` **committed**; per-chat `image_calls` **не вырос** (15→15); shared +1 (18→19); `cover_used` +1 (1→2); freq-заряды не тронуты | **VERIFIED** |
| (c) изоляция live: мем | при daily=0 — честный отказ (0 платных вызовов, строк журнала нет, cover-агрегат не тронут); при daily=20 — 1 мем → строка `source='direct'` committed, chat +1 (14→15), cover-агрегат без изменений | **VERIFIED** |
| (d) shared-источник | без добивания потолка (unit-доказательства TestSharedCeilingHonesty; в live-окне `SHARED_BUDGET_DENY=0` — отказов по shared не было) | **VERIFIED (по состоянию)** |
| (e) экономика/журнал | Δ budget = ровно ген+мем+обложка; ERR/CRIT=2 (traceback vision-фоновой задачи + INCIDENT авто-восстановления — см. Finding 3 полного README), 402=0, SKIPS=0; `user_version=36` | **VERIFIED (наблюдения)** |
| (f) уборка | 9/9 тестовых сообщений удалено, остаток 0 | **VERIFIED** |
| restore | настройки восстановлены точно дважды (C4 и C5): `budgets_enabled=false` (chat), daily=5 (global), freq=false; reserve `legacy/budgets_off` | **VERIFIED** |

Файлы (копии): `c1-showcase.json`, `c2-cover-isolation.json` (первичный
прогон; актуальный результат — `c5-cover-fix.json`), `c3-meme-isolation.json`,
`c4-restore.json`, `c5-cover-fix.json`.
