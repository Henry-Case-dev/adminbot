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

## Ledger re-bind to 2.58.80 (31c16555)

Лейн PM-LEDGER-25880 (writer: `requirements-map.json` + этот раздел; без кода, деплоя, SSH, коммитов;
`deploy-25880-report.md`, `recap-25880.md`, `evidence/**`, `review-*.md`, `decision-*`, `plans/features/soul-1/**`,
`plans/current_task.md`, `plans/workflow_state.md` не трогались).

Прод 2.58.80 = `31c165556dbe8c289606bd6bee1af49bb72d5794` (release commit; родитель `d9b7f389`; previous prod
`c2775a54` — rollback target). `candidate_commit` = `deployed_commit` = `31c16555`. История evidence сохранена
(новые элементы только добавлялись).

### Что сделано

- **95 VERIFIED-строк + FINAL.3** получили по одному новому evidence-элементу с `candidate_commit=31c16555`:
  - форма (a) «re-verified at 31c16555» — где механизм реально перепрогонялся/проверялся на деплой-коммите:
    recap-сьюты (shell 129/129; fullscreen 7/7 = 70 чеков; editor 40/40; modules W3-MODULES-E2E-OK; analytics 74/74;
    status 26/26; логи `evidence/recap-25880/_31c16555_suite_*.log`), капчур-матрица 48 whole-viewport кадров
    (`png_index.json`, `verify_summary.json`, `fingerprint.json all_match=true`), U07.2-геометрия (`_31c16555_rowa_*`,
    `css.served_right_formula_x3`, `rowa.inset_geometry_ok`), deploy-протокол 2.58.80 (`deploy-25880-report.md`,
    `evidence/deploy-25880/ev01+ev03`), validator-прогоны этого лейна, машинные сверки документов
    (`git ls-files`; `git log --diff-filter=M` пуст после добавления) и SHA снапшотов (d0b4f611… / 91f754e3…);
  - форма (b) «implementation unchanged since c2775a54» — B02/B03/B04/B08/B11-строки, B10-R05, REQ-B10-PYTEST:
    несущие файлы вне дельты (`git diff --name-only c2775a54..31c16555 -- <files>` пусто: mca_experience*,
    summary_memory, cover_style_edit/jobs, mca_episodes*, web_stories, tools/v63_b11_mechanisms_report.py,
    baseline-pytest-b10.md, тесты `tests/test_asap8_v63_b0*.py`, `test_asap8_f7_stories.py`).
- **FINAL.3 закрыта** (PENDING→VERIFIED): recap закрывает все три прежних гэпа — единичные whole-viewport кадры status
  768/1024/1440; cover_editor/fullscreen 360/430/768 + landscape 667×375; fingerprint-привязка к деплой-коммиту;
  плюс реальные header-размеры (116.2/93.8/113.4/109.4) и selected/copy 40/40.
- **B10-R17 не закрыта**; reason сужен: mobile-UI клауза закрыта на 31c16555 (скриншоты всех размеров), остаётся
  клауза «7 отложенных визуализаций на реальных данных» (owner/прод; U05.3 data part — OWNER-ONLY по
  `v63-frontend-verification-2026-10-16.md` §4; recap §«НЕ проверяется»: real-data визуализации — прод-проверка).
- **45 строк переведены в PENDING с причиной** (форма (c), строгий ре-бинд невозможен; см. ниже). Правило задачи
  запрещает форму (b) для строк, указывающих на файл из дельта-набора; для этих групп дополнительно зафиксированы
  hunk-уровневые факты (стекло-строк в diff `web/*` — 0; hunk `param_catalog.py` = +18 запись L1-planner в `_PROMPTS`;
  hooks `direct_chat_service.py` — за default-OFF флагами).

### Счётчики (222 строки; required=200)

| | было | стало |
|---|---|---|
| VERIFIED | 140 | **96** |
| READY_FOR_LIVE | 38 | 38 |
| PENDING | 26 | **70** (required 48: B12.1, B12.6, REQ-0-1 + 45 демоушенов) |
| BLOCKED_REAL_HUMAN_GATE | 18 | 18 |

required: 96 VERIFIED / 38 READY_FOR_LIVE / 48 PENDING / 18 BLOCKED = 200.

### Оставлено открытым в этом проходе (45)

| Группа | Строк | Почему | Needed |
|---|---|---|---|
| U08 (FE-GLASS) | 31 | recap glass не прогонял; несущие файлы (app.css/app.js/index.html) в file-list дельты — чужие hunks, но форма (b) запрещена guard'ом; glass.js/glass-probe.js вне дельты | glass-прогон (tier map/scanline) на дереве 31c16555 ЛИБО hunk-приёмка Оркестратора/владельца |
| B01* | 6 | `services/direct_chat_service.py` в дельте (4116c48a: hooks в initiative-L1/writer-путях за default-OFF флагами) | перепрогон `tests/test_asap8_v63_b01_initiative_observer.py` на 31c16555 ЛИБО приёмка parity gates-OFF |
| B06/B07 | 8 | тестируемая матрица читает `services/param_catalog.py` (в дельте; hunk +18 — вне per-chat/temporal-логики) | перепрогон b06+b07 на 31c16555 ЛИБО hunk-приёмка |

Не трогались (как были): 18 owner-гейтов, 38 READY_FOR_LIVE (вкл. B10-R17 с суженным reason), B12.1/B12.6/REQ-0-1,
22 non-required PENDING.

Наблюдение вне мандата лейна: клауза B12.1 «закоммичены» в диапазоне выполнена — `review-ledger.md`,
`integration-evidence.md`, `v63-final-coverage-report-2026-10-16.md`, `ui-acceptance.md`, `live-canary.md`,
`release-reconciliation.md` tracked на HEAD (коммиты 50a7e689/225c3c2b/4ca40730/8c960df6); перевод B12.1 —
решение Оркестратора.

### Gate outputs (verbatim)

`py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --map plans/features/asap8-v6-3-live-correction/requirements-map.json --stage plan` → exit 0:

```
stage=plan inventory=148 manual=74 scoped=0 errors=0
```

`... --stage release --candidate 31c165556dbe8c289606bd6bee1af49bb72d5794 --deployed-commit 31c165556dbe8c289606bd6bee1af49bb72d5794` → exit 1:

```
FAIL: U07-SYM-DESKTOP: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U07-SYM-ANDROID: live requirement lacks evidence for stage release
FAIL: U07-LAUNCHMODE: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U08-SYM: mandatory not ['VERIFIED'] (got PENDING)
FAIL: REQ-B01: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: B01.1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: B01.2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: B01.3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: B01.4: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
FAIL: B01.5: mandatory not ['VERIFIED'] (got PENDING)
FAIL: B01.6: mandatory not ['VERIFIED'] (got PENDING)
FAIL: REQ-B02: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: B02.3: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: REQ-B03: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
FAIL: B03.4: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
FAIL: REQ-B04: mandatory not ['VERIFIED'] (got READY_FOR_LIVE)
FAIL: B04.5: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: REQ-B05: live requirement lacks evidence for stage release
FAIL: B05.1: live requirement lacks evidence for stage release
FAIL: B05.2: live requirement lacks evidence for stage release
FAIL: B05.3: live requirement lacks evidence for stage release
FAIL: REQ-U01: live requirement lacks evidence for stage release
FAIL: U01.1: live requirement lacks evidence for stage release
FAIL: U01.2: live requirement lacks evidence for stage release
FAIL: U01.3: live requirement lacks evidence for stage release
FAIL: U01.4: live requirement lacks evidence for stage release
FAIL: REQ-U02: live requirement lacks evidence for stage release
FAIL: U02.2: live requirement lacks evidence for stage release
FAIL: REQ-U03: live requirement lacks evidence for stage release
FAIL: REQ-U04: live requirement lacks evidence for stage release
FAIL: REQ-U05: live requirement lacks evidence for stage release
FAIL: U05.3: live requirement lacks evidence for stage release
FAIL: U05.4: live requirement lacks evidence for stage release
FAIL: REQ-U06: live requirement lacks evidence for stage release
FAIL: U06.2: live requirement lacks evidence for stage release
FAIL: REQ-U07: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U07.1a: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U07.1e: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: REQ-U07-2: live requirement lacks evidence for stage release
FAIL: U07.2a: live requirement lacks evidence for stage release
FAIL: U07.2e: live requirement lacks evidence for stage release
FAIL: REQ-U07-3: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U07.3b: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U07.3c: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: REQ-U08: mandatory not ['VERIFIED'] (got PENDING)
FAIL: REQ-U08-0: mandatory not ['VERIFIED'] (got PENDING)
FAIL: REQ-U08-1: mandatory not ['VERIFIED'] (got PENDING)
FAIL: REQ-U08-2: mandatory not ['VERIFIED'] (got PENDING)
FAIL: REQ-U08-3: mandatory not ['VERIFIED'] (got PENDING)
FAIL: U08.3a: mandatory not ['VERIFIED'] (got PENDING)
... and 84 more
stage=release inventory=148 manual=74 scoped=200 errors=134
```

Группировка всех 134 ошибок (полная энумерация read-only репликой логики гейта):

- **104 × «mandatory not ['VERIFIED']»** = 48 PENDING (45 демоушенов этого прохода: U08×31, B01×6, B06/B07×8;
  плюс B12.1, B12.6, REQ-0-1) + 38 READY_FOR_LIVE + 18 BLOCKED_REAL_HUMAN_GATE;
- **30 × «live requirement lacks evidence for stage release»** — VERIFIED-строки с live_required без live/production-наблюдения
  на 31c16555 (привязка есть; recap-артефакты локальные = type ui; deploy-наблюдение только у B12.4):
  U07-SYM-ANDROID, REQ-B05, B05.1-3, REQ-U01, U01.1-4, REQ-U02, U02.2, REQ-U03, REQ-U04, REQ-U05, U05.3, U05.4,
  REQ-U06, U06.2, REQ-U07-2, U07.2a, U07.2e, REQ-B08, FINAL.3, REQ-EVIDENCE-SELF, REQ-B05-DOD, REQ-U01-TESTS,
  B10-R05, REQ-B11-SCOPE, V05;
- **0** × candidate/deployed mismatch; **0** × «no evidence bound to reviewed candidate» (все 96 VERIFIED-строк привязаны к 31c16555).

Красный release-гейт — штатное состояние: 45 демоушенов этого прохода + 59 ранее открытые required-строки (38 READY_FOR_LIVE +
18 BLOCKED + B12.1/B12.6/REQ-0-1) + 30 live-клауз без live/prod-наблюдения на деплой-коммите. Ни одна строка не «озеленена» принудительно.

## Re-verify open rows at 31c16555

Лейн **V63-REBIND-45** (verify + bounded binding; touched: `requirements-map.json` — только перечисленные строки,
этот раздел, `evidence/rebind-31c16555/**`; без кода, деплоя, SSH, коммитов). Работа — в **detached worktree**
деплой-коммита, удалённом по завершении.

### Fingerprint (дерево == деплой)

`git rev-parse HEAD` = `31c165556dbe8c289606bd6bee1af49bb72d5794`; sha256: `web/static/app.css` =
`70975eb2eac08f01beaecc1bf5be6ff005de75efada145f96785c0973c887be2`, `web/app.js` =
`9774da6a4e932287123cc49f8c84337a77f2bdef63385b3e76a9d47d5f9cb8ac`, `web/index.html` =
`e209d5faf7e8e54a907a35c570aba9f574cbfa9fbae2ae1fc8c95e53be26b3e0`, `services/param_catalog.py` =
`1981d3382e2ee81222107027ead5e7e61ef438cbdc91afcd1c13e668d0d15ba7` — совпадают с
`evidence/deploy-25880/ev03-verification-summary.md` (серверные файлы байт-в-байт = релизному коммиту, вкл.
отданный `/web/static/app.css`).

### Что перепрогнано на 31c16555 (артефакты — `evidence/rebind-31c16555/`)

1. **Node glass-сьют** (в worktree): `glass_probe`, `design_tokens`, `hotfix6/7/9/10` — 6/6 `exit=0`
   (`node_glass_suite.log`: `JS-UNIT-OK glass-probe`, `JS-UNIT-OK`, `HOTFIX6-LENS-HEARTBEAT-SHELL-OK`,
   `HOTFIX10-GLASS-GEOMETRY-BG-OK`, `HOTFIX7-SHELL-GLASS-HEARTBEAT-OK`, `HOTFIX9-SHELL-FLEX-GLASS-AURORA-OK`).
2. **pytest B01+B06+B07** (в worktree, тот же venv): `42 passed in 5.10s` (`TRIO_EXIT=0`,
   `b01_b06_b07_suite.log`); B08 сверх — `24 passed` (`b08_suite.log`).
3. **Стенд + реальный Chrome 155** (`glass_rebind_check2.py`): probe `tierA=true/probe-chromium/svg=true`
   (28ms); A/B-замер поля смещения (панель видна/скрыта, dpr=3, subpixel peak-метод): крайние линии
   ±3..7.25px, ряд y+112 центр 2.03px, **контроль вне панели — ровно 0.00**; карта линзы расшифрована из
   data-URI `index.html`: max|disp|=8.00px, центр |u|,|v|≤0.62 = **0.031px**, odd-симметрия — поле
   согласовано с картой (dev median 1.56 / max 2.58px); контраст 14.8:1 (волна 16.3:1); rim top>bottom,
   left>right; specular top-left (0.025/0.040); hit `#hero-btn` — inside, клик ok; Tier B: `url()` нет,
   blur(~5px) есть, направленного сдвига нет (медиана 1.61px ≈ шум метода; линии видны, modulation 0.24).
4. **Реальные страницы** (мок-API `ui_round1025_matrix`): tier map — статус 1×a+3×b+2×c (hero a probe-chromium
   + inline `url("#lg-lens-…")`, cognition-graph c), oversight 5×b+1×c, modules 15 × `.module-card` b,
   hover-specular none→`radial-gradient(120% 90% at 18% 0%)`; hit-тест центра hero — внутри; декор
   pointer-events=none; консоль 0; overflow ok; **url()-фильтров в редакторе/oversight/modules — 0**;
   390: header tier=b, popover «Ещё» tier=c, sceneSeed 424242→424242 (тот же canvas); prefers-reduced-motion →
   hero tier=b reason=reduced-motion, low-end (mem=2/cores=2) → tier=b reason=low-end.
   Примечания: (а) в мок-стубе `UI_LIQUID_GLASS_LIB=True` (прод-default False — `config/settings.py:1306`),
   поэтому `ps-glass__surface` url()-frost на статусе — индуцирован стубом; (б) шум поля ~1.6px (blur-фон);
   (в) WebKit в среде отсутствует (WebKit-ветка — unit-матрица decide()); (г) физические устройства/
   mid-range Android — вне среды проверки.
5. **FPS-прокси** (headless, 390): 60fps avg, p95 17.1ms, 0 дропов>25ms.

### Применено к карте (46 строк: 39 → VERIFIED, 4 → READY_FOR_LIVE, 3 PENDING с суженной причиной; у каждой строки — 1 новый evidence с `candidate_commit=31c16555`, старые сохранены)

* **VERIFIED (39).** U08 (24): U08-SYM, REQ-U08-0, REQ-U08-1, REQ-U08-2, REQ-U08-3, U08.3a/b/c/d,
  U08.4a/b/c/e/f, REQ-U08-5, U08.5.2/5.3/5.5, REQ-U08-0-MATERIAL, REQ-U08-0-PALETTE, REQ-U08-1-AUDIT,
  REQ-U08-1-PROBE, REQ-U08-2-LAYERS, REQ-U08-2-PARAMS. B01 (6): B01.1/2/3/5/6, REQ-B01-CLARIFY (13/13 b01 на
  31c16555). B06/B07 (8): B06.1–3 (17/17), B07.1–3 + REQ-B07-BODY (12/12); **REQ-B07** — production-биндинг
  (прод=31c16555, серверные файлы = коммит; temporal-код вне дельты c2775a54..31c16555). **B12.1** —
  клауза «закоммичены» выполнена: review-ledger/integration-evidence/v63-final-coverage (50a7e689),
  live-canary (4ca40730), release-reconciliation (8c960df6), ui-acceptance (c0535280 @w2-evidence-glass),
  requirements-map (bc91b902) — tracked, все ancestors 31c16555; скриншоты в git (41/49/58/12 PNG);
  `__PENDING__` = 0; журнал — `b12_1_tracking.txt`.
* **READY_FOR_LIVE (4).** REQ-U08, U08.3e, U08.5.4, REQ-U08-DOD — UI/стенд-часть перепроверена на 31c16555,
  остаётся клауза живого клиента (Android/WebKit fallback, физический mid-range FPS/responsiveness) — owner/V07.
* **Остались PENDING (3).** REQ-U08-4, U08.4d, U08.5.1 — клауза «fullscreen-контрол ⛶ = круглая мини-линза»
  не реализована на 31c16555: `.lg-mini-lens` — только CSS-класс (`app.css:3527`), кнопка `.header-fs-btn`
  его не получает (Playwright 390: `has_mini_lens=false`, `bf=none`, borderRadius 50%, 49×44) —
  **REV-W2-N1** (open, non-blocking → W4-hardening); close-up отсутствует — **REV-W2-N4**. Остальные клаузы
  этих строк перепроверены (шапка b, popover c).

### Gate (verbatim)

`check --stage plan` → exit 0:

```
stage=plan inventory=148 manual=74 scoped=0 errors=0
```

`check --stage release --candidate 31c165556dbe8c289606bd6bee1af49bb72d5794 --deployed-commit 31c165556dbe8c289606bd6bee1af49bb72d5794` → **exit 1**:

```
FAIL: U07-SYM-DESKTOP: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U07-SYM-ANDROID: live requirement lacks evidence for stage release
FAIL: U07-LAUNCHMODE: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
FAIL: U08-SYM: live requirement lacks evidence for stage release
FAIL: REQ-B01: mandatory not ['VERIFIED'] (got BLOCKED_REAL_HUMAN_GATE)
... and 53 more
stage=release inventory=148 manual=74 scoped=200 errors=103
```

Классификация всех 103: **65** × mandatory-not-VERIFIED (42 READY_FOR_LIVE + 18 BLOCKED_REAL_HUMAN_GATE +
5 PENDING = U08.4d/REQ-U08-4/U08.5.1, B12.6, REQ-0-1) + **38** × live-lacks-evidence (VERIFIED с
`live_required` без live/production-наблюдения; 8 из них — строки U08 этого прохода, ранее дававшие ту же
одну ошибку в mandatory-классе). Было 134 → стало **103** (−39 снятых mandatory + 8 перешедших в live-класс).
Красный release-гейт — штатное состояние; «озеленения»/force-green нет.

Счётчики (222 строки; required=200): **VERIFIED 135 / READY_FOR_LIVE 42 / PENDING 27 / BLOCKED 18**.
