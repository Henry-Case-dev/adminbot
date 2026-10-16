#map-reconciliation 2026-10-16 — бухгалтерская починка карты покрытия ASAP 8 v6.3

Лейн `V63-MAPFIX` (writer, только 2 файла). Код приложения, деплой, SSH и Telegram не
трогались; git-коммита нет. Источник требований не менялся:
`source-lines-37423-EOF.md` SHA256 `d0b4f611ac5eff7d228a1d2a2d1e283f04b26625f2dac89ab5ad1145f10e686d`
(пересчитан: байт-идентичен строкам 1–450 `plans/current_task.md` + финальный `\n`),
`candidate_commit` = `deployed_commit` = `c2775a54258512a3e20c97341d3e8a6738b1a33b`.

## 1. Итоговые счётчики статусов (222 строки: 148 inventory + 74 manual; required=200)

| | было | стало |
|---|---|---|
| VERIFIED | 138 | **129** |
| READY_FOR_LIVE | 48 | **44** |
| PENDING | 22 (все non-required) | **31** (22 non-required + 9 required) |
| BLOCKED_REAL_HUMAN_GATE | 14 | **18** |
| Всего | 222 | 222 |

`required` по статусам после правки: VERIFIED 129 / READY_FOR_LIVE 44 / PENDING 9 / BLOCKED 18 = 200.

## 2. Row-by-row изменения

| id | поле | было → стало | причина |
|---|---|---|---|
| B12.1 | status | VERIFIED → **PENDING** | F-1 аудита: `review-ledger.md` и `integration-evidence.md` отсутствуют в репо и в `git log --all --name-only`; финального отчёта v6.3 (клауза `__PENDING__`) нет; `ui-acceptance.md` лежит вне пакета (`w2-evidence-glass/`). Evidence была общим deploy-текстом |
| B12.1 | evidence | deploy-текст → `verification-report-2026-10-16.md §3 F-1 + git log --all --name-only` | честная фиксация отсутствующих артефактов |
| FINAL.1 | status | VERIFIED → **PENDING** | финальной таблицы coverage «проблема→RCA→исходники→RED→GREEN/Review→deployed SHA→outcome→статус» в пакете нет; `requirements-map.md` — инвентарь, не RCA-таблица |
| FINAL.3 | status | VERIFIED → **PENDING** | evidence была общим deploy-текстом; whole-viewport скриншоты не закоммичены и не покрывают все маршруты (см. §5) |
| REQ-0-1 | status | VERIFIED → **PENDING** | F-3 аудита: `baseline-inventory.md:82` — «§0.1-данные **для сбора на S0**»; 24/48h датасет не собран; `review-coverage.md` blocker #3 — строка без волны |
| PRIN-OUTCOME | status | VERIFIED → **PENDING** | принцип нарушен: B12.1 / FINAL.3 / REQ-0-1 закрыты без наблюдаемого outcome; финальной coverage-таблицы нет |
| PRIN-PIPELINE-FIRST | status | VERIFIED → **PENDING** | цепочка source→event→processing→decision→output→feedback подтверждена отчётом только для B11 (`tools/v63_b11_mechanisms_report.py`) |
| PRIN-ONE-WORKFLOW | status | VERIFIED → **PENDING** | артефакта-доказательства «нет новой очереди/БД, один workflow» нет: `git diff f58a644..c2775a54 --stat` = 630 файлов, нужна семантическая проверка кода |
| PRIN-PRESERVE | status | VERIFIED → **PENDING** | rollback-цель `b9ea4907` и тесты B03/B09 есть, но деплой-план с backup/feature-gate и сводка зелёных негативных тестов сохранности не оформлены |
| B12.6 | status | VERIFIED → **PENDING** | снапшот снят и хеш сходится, но «side effects измеримы» и «GraphRAG hallucinated stats негативными тестами» артефактом не подтверждены |
| V01 | status | READY_FOR_LIVE → **BLOCKED_REAL_HUMAN_GATE** | артефакт `w4-live-probes.md:23`; owner-гейт |
| V02 | status | READY_FOR_LIVE → **BLOCKED_REAL_HUMAN_GATE** | артефакт `w4-live-probes.md:24`; owner-гейт |
| V04 | status | READY_FOR_LIVE → **BLOCKED_REAL_HUMAN_GATE** | артефакт `w4-live-probes.md:26`; owner-гейт |
| V06 | status | READY_FOR_LIVE → **BLOCKED_REAL_HUMAN_GATE** | артефакт `w4-live-probes.md:28`; owner-гейт |
| V01/V02/V04/V06 | reason | «» → цитата `w4-live-probes.md §2` + «owner-гейтов 18, не 14» | устранено противоречие карта↔артефакт |
| PRIN-VERIFY-HEAD | evidence.ref | `live-canary.md + release-reconciliation.md + review-w1/w2/w3.md` → `verification-report-2026-10-16.md §0 + release-reconciliation.md §2 + live-canary.md` | NB-3: deploy-текст заменён на реальную сверку HEAD/кандидата |
| B12.2 | evidence.ref | deploy-текст → `release-reconciliation.md §2 + live-canary.md:75-83` | фактический RED validator'а (exit 1) + воспроизведение аудитом (scoped=200, errors=101) |
| B12.3 | evidence.ref | deploy-текст → `requirements-map.json + release-reconciliation.md §3 + w4-live-probes.md §2` | линейка статусов по 222 строкам, 18 owner-гейтов |
| B12.5 | evidence.ref | deploy-текст → `release-reconciliation.md §1-§2` | документ целиком про B12.5 (f10 `__PENDING__` → фактический `b9ea4907`) |
| REQ-REL-SHA | evidence.ref | deploy-текст → `verification-report-2026-10-16.md §0 + release-reconciliation.md §2` | привязка всех 222 evidence к `c2775a54`, 0 расхождений |
| REQ-0-SNAPSHOT | evidence.ref | `tests/ + .../w*-reports/` (не резолвится) → `source-lines-37423-EOF.md + SNAPSHOT_MANIFEST.md + current_task.snapshot_2026-10-15.md` | SHA пересчитаны: `d0b4f611…` = `source_sha256`, `91f754e3993477e8…` = манифест |
| REQ-0-BASESHA | evidence.ref | `tests/ + .../w*-reports/` → `baseline-inventory.md §1-§2 + release-reconciliation.md §1 + live-canary.md` | HEAD `f58a644` / 2.58.78 и фактический pre-deploy SHA `b9ea4907` |
| REQ-0-2 | evidence.ref | `tests/ + .../w*-reports/` → `requirements-map.json + requirements-map.md + source-reconciliation.md` | все три файла в git |
| REQ-0-3 | evidence.ref | `tests/ + .../w*-reports/` → `evidence/v63-frontend/_v63fe_measurements.json + w2-evidence-shell/w2_shell_e2e.json + w3-evidence-editor/w3_editor_e2e_after.json` | реальные пробы 320/360/390/**430/768**/1024/1440 + 667×375 (см. §5) |
| REQ-0-4 | evidence.ref | deploy-текст → `plans/current_task.md + SNAPSHOT_MANIFEST.md + verification-report-2026-10-16.md §8` | user-owned файл не перетирался; COMPLETE не объявлен |
| REQ-EVIDENCE-SELF | evidence.ref | `tests/ + .../w*-reports/` → `w2-evidence-glass/ui-acceptance.md + tests/test_asap8_v63_b04_edit_contract.py` | оба вердикта ui-acceptance + B04-тесты сохранности изображений профилей |
| REQ-B10-PYTEST | evidence.ref | deploy-текст → `baseline-pytest-b10.md` | 3 failed pytest классифицированы независимо (1 реальный RCA, 2 passed/68 passed) |
| REQ-B09-BODY | evidence.ref | `tests/test_chat_migration*.py` (не существует) → `tests/test_asap8_v63_b09_migration.py + w1-reports/W1-MEMORY-MIG.md` | нерезолвящийся glob |
| REQ-B09 | evidence.ref | `tests/test_chat_migration*.py` → `tests/test_asap8_v63_b09_migration.py + w1-reports/W1-MEMORY-MIG.md` | нерезолвящийся glob |
| B04.1/2/3/4/6, REQ-B04, B04.5 | evidence.ref | `tests/test_asap8_v63_b04_cover*.py` (не существует) → `tests/test_asap8_v63_b04_edit_contract.py + tests/test_asap8_v63_b04_scene_delivery.py + w3-evidence-editor/` | нерезолвящийся glob |
| 22 evidence-строки | evidence.ref | `.../w*-reports/` → `w1-reports/ + w2-reports/ + w3-reports/`; `backlog.md (v6.3 Wave 4 live checklist)` → `plans/backlog.md (§ «v6.3 W2 non-blocking (REV-W2) + Wave 4 checklist»)` | нерезолвящиеся пути; claims не менялись |

Тексты требований, `req_id`, `source_excerpt`, `source_line`, `source_text_sha256`,
`disposition`, `slice`, `acceptance`, `live_required`, `live_when` — не изменялись.
Поле `reason` заполнено только у 9 demoted-строк и 4 переключенных V-строк.

## 3. 18 owner-гейтов (что обязан сделать владелец)

Было заявлено 14 — это занижение: 14 строк карты уже были `BLOCKED_REAL_HUMAN_GATE`,
плюс `w4-live-probes.md:23,24,26,28` помечал `BLOCKED_REAL_HUMAN_GATE` ещё V01/V02/V04/V06,
которые карта держала `READY_FOR_LIVE`. **Итого 18.**

1. **U07-SYM-DESKTOP** (L14) — открыть MiniApp в настоящем Windows Telegram Desktop и воспроизвести «web-кнопка fullscreen → маленькое неудобное окно» до/после.
2. **U07-LAUNCHMODE** (L16) — в BotFather Main App с `Launch Mode = Fullscreen` проверить, что второй `requestFullscreen()` не отправляется и сразу видна кнопка выхода.
3. **REQ-B01** (L44) — дать естественный повод в обычном групповом чате и окно canary 24–48 ч: нужен ≥1 живой SEND/REACT/SILENT с reply binding.
4. **REQ-B02** (L62) — дать естественный поток сообщений, чтобы семантическое извлечение Experience сработало в бою (не фикстурами).
5. **B02.3** (L71) — предоставить 24–48 ч прод-нагрузки 2k–5k сообщений/сутки для измерения cursor lag, покрытия и fair batches.
6. **B04.5** (L103) — реальная публикация styled-обложки в чат (зависит от `InputRichMessageMedia` в прод-aiogram, 2 предсуществующих фейла).
7. **REQ-U07** (L178) — приёмка fullscreen на настоящих клиентах Windows/Android, mock-матрица не принимается.
8. **U07.1a** (L200) — на верифицированном `platform === 'tdesktop'` подтвердить, что проблемный fullscreen-контрол не предлагается.
9. **U07.1e** (L204) — на BotFather `Launch Mode=Fullscreen` подтвердить отсутствие второго запроса fullscreen и наличие рабочей кнопки выхода.
10. **REQ-U07-3** (L227) — desktop-адаптив и проверки Windows 10/11 в реальном клиенте.
11. **U07.3b** (L230) — записать platform/version, источник открытия, `isFullscreen` before/after и `fullscreenChanged/fullscreenFailed` из настоящего клиента.
12. **U07.3c** (L231) — прогнать Windows 10/11 Telegram Desktop, Android portrait/landscape и (при доступности) iOS/macOS/Web A/K.
13. **REQ-B09** (L367) — перенести реальную supergroup и доказать end-to-end сохранность memory/FTS/GraphRAG/episodes/summary/override (либо идемпотентный alias) без порчи истории.
14. **FINAL.2** (L440) — prod-подтверждение каждого функционального кейса + 24/48h наблюдаемость Initiative/Experience с sample reason codes.
15. **V01** (L420) — естественный разговор без упоминания бота: model/observer находит повод, решение уместное, реплика с подтверждённым reply binding; окно canary 24–48 ч.
16. **V02** (L422) — русская корректировка без regex-фраз доходит до validated lesson и применяется при повторе с outcome; шутка/спор отбракованы; счётчики от persisted-событий.
17. **V04** (L426) — реальная Base с людьми + Logo → компактный Style Edit prompt ≤800 → styled применён без сюжетной подмены → публикация в Telegram.
18. **V06** (L431) — открыть Main App из BotFather в Windows Telegram Desktop с Launch Mode=Fullscreen и на Android portrait/landscape; подтвердить отсутствие «ловушки» и непосредственность кнопки у native controls.

## 4. Ожидаемый результат gate (RED — не регрессия)

До лейна: `--stage release --candidate c2775a54 --deployed-commit c2775a54` → exit 1,
scoped=200, errors=**101** (аудит). После лейна — **тот же красный**, errors=**110**
(+9 = ровно 9 demoted-строк): 71 × `mandatory not ['VERIFIED']` (200 required − 129 VERIFIED)
+ 39 × `live requirement lacks evidence for stage release` (VERIFIED с `live_required=true`
и единственным evidence типа `ui`). `--stage plan` → **exit 0, errors=0**.

Красный release-gate — штатное состояние: 18 owner-гейтов + 44 READY_FOR_LIVE + 9 PENDING.
Любой будущий прогон с scoped=200 и errors=110 — это baseline, а не новая поломка.

## 5. Что осталось открытым

1. **44 READY_FOR_LIVE** — из них 25 закрываемы агентом (B01.4, REQ-B07/B08, B08.4, REQ-B10/B11/B12, B12.4, FINAL.4, REQ-B11-SCOPE, V03, V05, B10-R01/R03/R05/R07/R08/R09/R11/R12/R14/R15/R16/R17/R19), 9 заблокированы прод-деградацией векторного контура (квота эмбеддингов parked → FTS-only; не регрессия v6.3).
2. **9 required PENDING** (§2) — чтобы закрыть, нужны: `review-ledger.md` + `integration-evidence.md` + финальный отчёт v6.3 (B12.1), финальная coverage-таблица (FINAL.1), коммит скриншотов + покрытие cover_editor/fullscreen (FINAL.3), §0.1 24/48h датасет (REQ-0-1), цепочка evidence по каждому B (PRIN-PIPELINE-FIRST), сверка «единый workflow» (PRIN-ONE-WORKFLOW), деплой-план сохранности (PRIN-PRESERVE), измеримость side effects + негативные тесты GraphRAG (B12.6).
3. **Папка `evidence/v63-frontend/` не в git** (untracked, NB-1) — 43 кадра и 2 JSON с измерениями, снятые 2026-10-16 на порту 8861. Пока не закоммичены, на них нельзя ссылаться как на зафиксированное доказательство.
4. **Внешняя проверка домена** `admin-bot.duckdns.org` с этой машины невозможна (локальный DNS) — за владельцем.
5. **6 падающих pytest репозитория** не перепроверялись (владение AUDIT-2); `baseline-pytest-b10.md` классифицирует 3 failed из B10.
6. **`requirements-map.md`** (человекочитаемая карта) не перевыпускалась — расходится с новыми статусами §1; её публикация вне WRITE_SCOPE этого лейна.

## 6. Где аудит фактически неточен (нашлось при верификации)

- **F-2, «430 и 768 отсутствуют полностью» — неверно.** В пакете 157 PNG (аудит пересчитал 108 и
  пропустил всю untracked-папку `evidence/v63-frontend/`): 5 файлов ширины **430** (`status/analytics_overview/
  analytics_processes/modules/style_editor_430x932.png`) и 5 файлов ширины **768** (`…_768x1024.png`).
- **F-2, «11 файлов ширины 360 — только кропы героя» — неполно.** Ширины 360: 16 файлов; 11 — кропы героя
  (h=140/141), но 5 — полноценные viewport-кадры `…_360x780.png` для тех же 5 маршрутов.
- **F-3 (смежно), «768 не пробовался нигде» — неверно.** `_v63fe_measurements.json` содержит ключи
  `status/768x1024`, `analytics_overview/768x1024`, `analytics_processes/768x1024`, `modules/768x1024`,
  `style_editor/768x1024` (vw=768, vh=1024, scrollWidth=768, hOverflow=false, headerH 116.2, console_errors=[]).
- **Суть F-2/F-3 при этом сохраняется:** evidence у FINAL.3 была шаблонным deploy-текстом; кадры
  не закоммичены; `status_768x1024.png` — полностраничный кадр 768×4780, а не viewport; `cover_editor`
  и `fullscreen` не имеют 360/430/768; общего отчёта приёмки FINAL.3 нет → демоушен обоснован, но
  причина в документе записана по фактическому состоянию, а не по формулировке аудита.
- **§5(b) «нужен владелец, 14»** пересекается с 14 строками карты, уже помеченными
  `BLOCKED_REAL_HUMAN_GATE`, и включает V07, который `w4-live-probes.md:29` держит `READY_FOR_LIVE`.
  Согласованное с артефактом число — **18** (14 + V01/V02/V04/V06). Если владелец согласится, что
  V07 («физический FPS/визуал стекла») тоже owner-гейт, число станет 19 — решение за владельцем,
  лейн зафиксировал 18.

## 7. PM-APPLY (2026-10-16) — применение закрытий V63-CLOSE к карте

Лейн PM-APPLY (writer, только `requirements-map.json` + этот раздел; без коммита, деплоя, SSH).
Все предложенные закрытия проверены по репо-артефактам и повторным прогонам на точном дереве
`c2775a54` (scratch worktree --detach): 97 pytest (b01 13, b06 17, b07 12, b08 24, f7 9,
b11-report 17, analytics-viz 5) — все зелёные; asap8-js 11/11; js-RED hotfix7 воспроизведён (exit 1).

Применено:
* 6 строк §3 V63-CLOSE → **VERIFIED** с привязкой к `c2775a54`: REQ-B07, REQ-B08,
  REQ-B11-SCOPE, V05, B12.4, B10-R05.
* 5 required-PENDING → **VERIFIED** по фактически созданным документам (wording этих строк
  git-трекинга не требует): FINAL.1, PRIN-OUTCOME, PRIN-PIPELINE-FIRST, PRIN-ONE-WORKFLOW,
  PRIN-PRESERVE. Трекинг документов остаётся клаузой **B12.1**.
* **B12.1** — остаётся PENDING: артефакты созданы, но клауза «закоммичены» не выполнена
  (untracked: review-ledger.md, integration-evidence.md, финальный отчёт, evidence/); причина
  обновлена («осталось: коммит»). **FINAL.3/B12.6/REQ-0-1** — PENDING с обновлёнными причинами;
  **REQ-B12/FINAL.4** — READY_FOR_LIVE (коммит пакета / 4 js-RED).
* Fingerprint-нота зафиксирована явно: прогоны и кадры V63-FE-2 принадлежат
  `a854ad95 + незакоммиченный web/` — НЕ `c2775a54`; для FINAL.3/B10-R17 это записано в reason,
  строка FE-2 в evidence V05 помечена как cross-check (не binding).
* Строки, оставшиеся открытыми, получили `reason` с точной незакрытой клаузой (§4 V63-CLOSE,
  включая B10-R02/R04/R06/R10/R13/R18 и REQ-B11-E2E). Из REQ-B11/REQ-B11-SCOPE убрано спорное
  «с PG DSN» (live-canary: `pg_dsn_not_provided`).

Счётчики (222 строки; required=200):

| | было (R6) | стало (PM-APPLY) |
|---|---|---|
| VERIFIED | 129 | **140** |
| READY_FOR_LIVE | 44 | **38** |
| PENDING | 31 | **26** (required 9→4: B12.1, FINAL.3, B12.6, REQ-0-1) |
| BLOCKED_REAL_HUMAN_GATE | 18 | **18** |
| required | 200 | 200 (=140+38+4+18) |

Gate:
* `--stage plan` → **exit 0, errors=0** (`stage=plan inventory=148 manual=74 scoped=0 errors=0`).
* `--stage release --candidate c2775a54 --deployed-commit c2775a54` → **exit 1, scoped=200,
  errors=99** (было 110: −11 снятых mandatory-ошибок закрытых строк; 60 mandatory + 39 live-evidence).
  Красный release-gate — штатное состояние (18 owner-гейтов + 38 READY_FOR_LIVE + 4 required PENDING).

Замечание (вне мандата этого лейна): в `v63-frontend-verification-2026-10-16.md` §4 зафиксирован
FAILED-пункт U07.2 (горизонтальные safeAreaInset игнорируются); строки карты U07.2a/U07.2e/
REQ-U07-2 («без перекрытия нативных зон») с ним расходятся и остаются VERIFIED — решение о
корректировке за Orchestrator/владельцем.
