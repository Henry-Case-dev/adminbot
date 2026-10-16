# Verification report — ASAP 8 v6.3 live correction (lane V63-AUDIT)

Независимая read-only проверка, 2026-10-16. Код приложения не менялся, деплоя не было,
прод проверялся только по HTTP с этой машины.

## 0. Привязка вердикта

| Что | Значение |
|---|---|
| Кандидат и actual deploy | `c2775a54258512a3e20c97341d3e8a6738b1a33b` (2.58.79) |
| Кандидат — предок HEAD `a854ad95` | да (`git merge-base --is-ancestor` → True) |
| Карта | `requirements-map.json`: `candidate_commit` = `deployed_commit` = c2775a54 |
| Источник требований | `source-lines-37423-EOF.md` (451 строка), SHA256 `d0b4f611ac5eff7d228a1d2a2d1e283f04b26625f2dac89ab5ad1145f10e686d` = `source_sha256` карты |
| Снапшот | `current_task.snapshot_2026-10-15.md`, SHA256 `91f754e3…` = SNAPSHOT_MANIFEST |
| Прод | `/healthz` → 200 `{"status":"ok","version":"2.58.79"}`; `/web/` → 200, 727145 байт |

Вердикт выдан против снапшота и карты, а не против текущего `plans/current_task.md` (там уже другой эпик).

## 1. Вердикт

**Эпик НЕ завершён.** Релиз 2.58.79 действительно задеплоен и подтверждён по HTTP, но:
1. release-gate падает: `requirements_gate.py check --stage release --candidate c2775a54 --deployed-commit c2775a54` → **exit 1, scoped=200, errors=101** (воспроизведено этой проверкой);
2. три обязательных пункта помечены `VERIFIED` без доказательств (F-1…F-3);
3. 48 пунктов `READY_FOR_LIVE` не закрыты, из них ~25 закрываемы агентом без владельца;
4. заявление «14 owner-гейтов» занижено: фактически 18 (§5).

## 2. Бухгалтерия и gate

- 148 инвентарных + 74 ручных = 222 строки. IT: 112 VERIFIED / 13 READY_FOR_LIVE / 9 PENDING / 14 BLOCKED_REAL_HUMAN_GATE. AD(74): 26 VERIFIED / 35 READY_FOR_LIVE / 13 PENDING.
- Все 222 evidence привязаны к `c2775a54` (0 расхождений); VERIFIED-строк без evidence нет; `source_excerpt` совпадают со своими строками; дублей `req_id` нет; `user_excluded`/backlog нет.
- Разбор 101 ошибки гейта (пересчитан по правилам `requirements_gate.py:144-179`):
  - **62 × `mandatory not ['VERIFIED']`** = 48 READY_FOR_LIVE + 14 BLOCKED_REAL_HUMAN_GATE;
  - **39 × `live requirement lacks evidence for stage release`** — это `live_required=true` со `status=VERIFIED`, но с единственным evidence типа `ui` (U07-SYM-ANDROID, U08-SYM, REQ-B05+B05.1-3, REQ-U01…U06 с подпунктами, REQ-U07-2/U07.2a/U07.2e, группа REQ-U08). Для release-стадии нужен evidence типа `live`/`production` (`:171-174`), поэтому «138 VERIFIED» и зелёный релиз несовместимы.
- Обратное покрытие проверено: 45 неразмеченных строк источника — это code-fence/CSS-каркас, шапки и baseline-заметки; содержательные клаузы покрыты сгруппированными строками (REQ-U07-1 L186, REQ-U08-2/-LAYERS). Пропущенных содержательных требований не найдено.

## 3. Ложные VERIFIED (блокирующие)

**F-1. B12.1 VERIFIED, но 2 из 6 названных артефактов не существуют.**
Требование: `source-lines-37423-EOF.md:409` — «закоммичены: requirements-map.md, **review-ledger.md**, **integration-evidence.md**, ui-acceptance.md, live-canary.md, release-reconciliation.md, скриншоты/видео с маскировкой ПДн; каждый ID B01–B12/U01–U08/V01–V07 имеет собственный resolved status; `__PENDING__` в финальном отчёте отсутствует».
Факт: `review-ledger.md` и `integration-evidence.md` отсутствуют во всём репозитории (`Get-ChildItem -Recurse -Force` пусто) и никогда не коммитились (`git log --all --name-only` пусто). `ui-acceptance.md` лежит не в пакете, а как `w2-evidence-glass/ui-acceptance.md`. Финального отчёта v6.3, к которому относится клауза про `__PENDING__`, в пакете нет вообще.
Evidence строки: `ref = "live-canary.md + release-reconciliation.md + review-w1/w2/w3.md"`, observation — общий deploy-текст. Это не доказательство трекинга артефактов.
Влияние: центральное обещание «пакет доказательств закоммичен и трекнут» не выполнено, а строка зелёная.

**F-2. FINAL.3 VERIFIED, но скриншотов 430/768 нет вообще, а 360 — только кропы.**
Требование: `:441` — «Скриншоты **всего viewport** на 320/360/390/430/768/1440 и landscape»; дубль в §0.3 (`:38` — пробы 320/360/390/430/768/1024/1440 CSS px).
Факт: перепись всех 108 PNG пакета по IHDR: ширины 120/160/270/320/340/360/380/390/392/415/617/640/667/780/1120/1158/1192/1200/1280/1334/1440/2048/2560. **430 и 768 отсутствуют полностью**; 11 файлов шириной 360 — это кропы героя (`u08-5-*hero*.png`, высота 140/141), не полный viewport. Evidence строки — тот же общий deploy-текст.
Влияние: обязательная визуальная приёмка на 430/768 не проводилась, а карта объявляет её выполненной.

**F-3. REQ-0-1 VERIFIED, но датасет §0.1 явно не собран.**
Acceptance требует, чтобы `baseline-inventory.md` содержал «24/48h данные (API/trace/jobs/counters/cursor/LLM errors/UI)». Факт: `baseline-inventory.md:82` — заголовок «## 3. §0.1-данные **для сбора на S0** (не секреты)», т.е. перечень того, что предстоит собрать. Evidence строки — шаблон `tests/ + w*-reports/`. `review-coverage.md` (blocker #3) уже помечал REQ-0-1 как осиротевший (ни одной волны).
Смежное: REQ-0-3 требует UI-проб на 320/360/390/430/768/1024/1440. Проба 430 реально есть (`w2-evidence-shell/w2_shell_e2e.json`, ключи `m430:*`), а **768 не пробовался нигде**: во всех evidence-JSON 768 встречается один раз и только как имя медиа-брейкпоинта (`"u02:dropdown…<768": true`).

## 4. Спот-чек VERIFIED (≥15 строк)

| Строка | Что проверено | Итог |
|---|---|---|
| REQ-B01 + DOD | 13 B01-тестов, включая `test_b01_independent_of_direct_entrypoint_gate`, `test_b01_writer_unavailable_is_explicit_not_silent` | подтверждено |
| REQ-B09-BODY | REV-W1 F1 починен: `services/chat_migration.py:67 _BACKUP_CHUNK=5_000`, `:68 _BACKUP_HARD_CAP=5_000_000`, rowid-чанки L132-134, L170 | подтверждено |
| REQ-B07 | `CATEGORY_TEMPORAL` в `SEED_CATEGORIES` (`services/pg_db.py:578`) | подтверждено |
| REQ-B06 | `summary_effective_enabled` (`services/summary_scheduler.py:58`) | подтверждено |
| REQ-B03 | `_staged_knn_scope` (`services/summary_memory.py:2883`), `_vec_candidates` L4550 | подтверждено |
| REQ-U01 + U01.1-4 | `w2-evidence-shell/w2_shell_e2e.json`: header 225.6 → 116.2 px, `scrollWidth==innerWidth` на 320/360/390/430/667/zoom200 | подтверждено |
| REQ-U03, U04 | `w3-evidence-status/_ui_w3_status.json`: 26/26, включая `analytics_no_logs_tab`; единственный `id="status-logs"` (`web/index.html:8383`) | подтверждено |
| REQ-U05 + подпункты | `web/api/analytics_viz.py`, `web/api/memory_overview.py` зарегистрированы в `web/app.py` | подтверждено |
| REQ-U08-0/-MATERIAL/-DOD | Tier A — реальные числа рефракции (`w2-evidence-glass/bend2-result.json`, `row-y*.json`: край dx −5…−8, центр 0); `ui-acceptance.md` содержит оба вердикта «optical Tier A passed» и «frost Tier B passed» | подтверждено |
| REQ-U07 (fullscreen) | `w2-evidence-fullscreen/_results.json` + 12 PNG (390 inline/float/fullscreen, 320, 1024 tdesktop, 1280 standalone, toast unsupported) | подтверждено как preprod-проба |
| REQ-B05 + B05.1-3 | `w3-evidence-editor/*` before/after + `w3_editor_e2e_after.json` (selected/copy) | подтверждено |
| REQ-B08 / REV-W3PRE | `services/web_stories.py:103/113/149` (`display_title`, `content_status`); `tools/v63_b11_mechanisms_report.py --help` импортируется | подтверждено |
| REQ-B11-SCOPE | `w4-live-probes.md` §2 + B11-факты в `live-canary.md` (ok / never_run / backlog) | подтверждено |
| V03, V05 | `w4-live-probes.md:25,27` — READY_FOR_LIVE с обоснованием | подтверждено, live не выполнен |
| REQ-REL-SHA, REQ-EVIDENCE-SELF | version-пины и HTTP-факты (§7) | подтверждено |
| REQ-B10 | B10-тесты есть, но REQ-B10-PYTEST опирается на deploy-текст, а не на классификацию pytest (владение AUDIT-2) | частично |

Вывод: ядро волн (B01–B09, U01–U08) имеет реальные артефакты и тесты. Проблема не в ядре, а в релизных строках B12/FINAL/REQ-0-* и в незакрытых live-пунктах.

## 5. Классификация 48 READY_FOR_LIVE

- **(a) закрываемо агентом, 25:** B01.4, REQ-B07, REQ-B08, B08.4, REQ-B10, REQ-B11, REQ-B12, B12.4, FINAL.4, REQ-B11-SCOPE, V03, V05, B10-R01, R03, R05, R07, R08, R09, R11, R12, R14, R15, R16, R17, R19.
- **(b) нужен владелец (реальный клиент/чат/24-48h/BotFather), 14:** REQ-B01-DOD, REQ-B02-DOD, REQ-B04-DOD, REQ-U07-HARD, REQ-B09-BODY, B10-R02, R04, R10, R18, V01, V02, V04, V06, V07.
- **(c) заблокировано прод-деградацией вектора, 9:** REQ-B03, B03.4, REQ-B04, REQ-B06, REQ-B03-DOD, REQ-B06-DOD, B10-R06, B10-R13, REQ-B11-E2E (квота эмбеддингов parked → `EMBEDDING_GENERATION_PAUSED … paused_rate_limit` → FTS-only; честная live-проверка сейчас невозможна).

**Противоречие статусов (блокирует учёт):** `w4-live-probes.md:23,24,26,28` помечает **V01, V02, V04, V06** как `BLOCKED_REAL_HUMAN_GATE`, а карта — как `READY_FOR_LIVE`. Реальное число owner-гейтов — 18, а не 14; формулировку из коммита `a854ad95` надо исправить.

## 6. Классификация 22 PENDING

Все 22 — служебная бухгалтерия, а не незавершённая работа: строки без `req_id` (заголовки, разделы, пустые строки фенсов) и строки с disposition `context`/`duplicate`. Проверено вручную, что среди них не спрятано содержательное требование. Незакрытых содержательных PENDING нет.

## 7. Релизные факты (подтверждено)

- `config/settings.py:3286 APP_VERSION = "2.58.79"`; README v2.58.79; исходников, прибитых к 2.58.78, нет.
- Внешние пробы: `/healthz` 200 2.58.79, `/api/health` 200, `/web/` 200 (727145 байт), `/web/static/fullscreen-policy.js`, `glass-probe.js`, `polygon-background.js` — 200.
- Отдаваемый `/web/` HTML побайтово соответствует локальному `web/index.html` на `c2775a54` (9624 строки; различие только `__APP_VERSION__` → 2.58.79: 727257 → 727145 байт).
- Rollback target `b9ea4907ffa52e7b2974e9511113e03350820a6e` существует, это bump 2.58.78 (`live-canary.md:12,66`).
- Ревью волн: `review-w1.md` (NEEDS_FIXES F1 → починено), `review-w2.md` (Approved), `review-w3.md` (Approved), `review-w3-stories-mech.md` (REV-W3PRE, 2 FAILED → починено). Непочиненных Needs Fixes нет; информационные NB-W3-1/NB-W3-2 остались.
- `live-canary.md:75-90`: release coverage gate = FAIL (exit 1), «не признаётся выполненным до приведения версии» — пакет сам не считает эпик закрытым.

## 8. Что означает отсутствие текста v6.3 в `plans/current_task.md`

Требования v6.3 живут только в трёх носителях: `source-lines-37423-EOF.md` (451 строка, SHA совпадает с `source_sha256` карты), `current_task.snapshot_2026-10-15.md` (37873 строки) и сама карта (source_line + source_excerpt).
Воспроизводимость есть: excerpt-файл хеш-подтверждён, evidence привязан к `c2775a54`, задеплоенный фронтенд побайтово сверен с этим коммитом. Но аудит «v6.3 done» возможен теперь только по снапшоту+карте+evidence, и доверять статусам карты целиком нельзя (F-1…F-3). Источник истины — excerpt+карта; `requirements-map.json` требует правки ложных статусов до любых заявлений о завершении.

## 9. Прочие (неблокирующие) наблюдения

- **NB-1.** Рабочее дерево грязнее, чем заявлено: кроме `services/disk_retention.py` (+34 строки) изменены 26 файлов доказательств пакета (`w2-evidence-fullscreen/*.png`, `w2-evidence-shell/*.png`, `w3-evidence-editor/*`, `w3-evidence-analytics/w3a_runs_desktop_1440.png`), перегенерированы 2026-10-16 16:31, различия только в таймингах. Каноничны коммитнутые блобы `c2775a54`; читающий ту же папку в рабочем дереве увидит другие байты. Не перегенерировать evidence post-commit либо явно помечать внекоммитные прогоны.
- **NB-2.** `final-audit-current-task.md` §5 описывает устаревшее состояние карты (`source_sha256 91f754e3`, пустой candidate, 148 PENDING, 202 ошибки) — противоречит текущей карте; документ не перевыпущен.
- **NB-3.** Общая строка-наблюдение «deploy 2.58.79 (c2775a54) verified from server: healthz/api/web 200, journal clean, rollback b9ea4907…» приклеена к десяткам несвязанных строк (B12.1–B12.6, FINAL.1/-3, REQ-B10-PYTEST, B10-R01..R19). Это шаблон, а не доказательство конкретной приёмки.
- **NB-4.** Прод-деградация векторного контура (parked-квота эмбеддингов, FTS-only, `experience` failure от 2026-10-10) — не регрессия v6.3, но она честно блокирует часть live-проверок (§5c) и должна быть в backlog явно.

## 10. Границы проверки

Не перепроверял (владение AUDIT-2): экспозиция `glass-teststand.html`, место списка «14 pending gates», квота/ротация эмбеддингов, сверка missing-artifact/git-evidence, 6 падающих pytest. Live-приёмка владельца (реальные Telegram-клиенты, BotFather Main App, 24-48h окно) агентом не выполнима.

## 11. Что нужно для честного закрытия

1. Исправить 3 ложных статуса: B12.1 — создать `review-ledger.md`/`integration-evidence.md` или снять VERIFIED; FINAL.3 — добрать скриншоты 430/768 и полный viewport 360; REQ-0-1/REQ-0-3 — собрать §0.1 и пробу 768 либо перевести в PENDING с причиной.
2. Свести `w4-live-probes.md` и карту к одному статусу V01/V02/V04/V06 (owner-гейтов 18, не 14).
3. Закрыть 25 агентских READY_FOR_LIVE и вынести 14 owner-гейтов владельцу явным списком.
4. После этого — release-gate без ошибок, и только затем заявление о завершении.
