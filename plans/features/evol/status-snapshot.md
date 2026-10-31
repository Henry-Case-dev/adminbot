# EVOL — статус по требованиям (снимок 01.11.2026, 00:45 +12:00)

Карта: `plans/features/evol/requirements-map.json` (schema `openworkflow-coverage-v1`, 832 строки инвентаря + 343 ручных записи,
**439 обязательных строк**, 89 различных `req_id`). Граф: `plans/features/evol/slice-graph.json` (49 узлов).

**Деплой выполнен:** прод **2.58.143** @ `273be95c8ff4f70e08dceef1daccbdd3082fc909` (ветка `release/2.58.143` = `evol/impl`),
отчёт `plans/features/evol/audit/deploy-2.58.143.md`. Предыдущий прод `5346ee76` (2.58.141), неудачная попытка
`06283422` (2.58.142, PG jsonb crash-loop) откатана и исправлена коммитом `2e48bfed`.

## Как записан статус

| Статус | Значение в этой карте | Строк |
|---|---|---|
| `VERIFIED` | ревью-принятое поведение **присутствует в задеплоенном кандидате** `273be95c`; `evidence[]` содержит минимум одну запись с `candidate_commit = 273be95c8ff4…` и ссылкой на существующий артефакт | **301** |
| `PENDING` | пункт не начат либо у него отсутствует часть обязательной приёмки (перечень ниже — с точной причиной) | 133 |
| `BUILDING` | правка идёт прямо сейчас в worktree `evol/impl` и в прод не попала | 3 |
| `READY_FOR_LIVE` | код в проде, но acceptance требует отдельного postdeploy-поведенческого доказательства | 2 |

Словарь `requirements_gate.py` строгий, `strict_evidence` остаётся **false** (карта никогда не опт-инилась в strict; включение —
отдельное решение с миграцией доказательств). Артефакты доказательств всё равно привязаны реальными путями и `artifact_sha256`,
взятым **из дерева задеплоенного кандидата** (`git show 273be95c:<path>`), кроме отчёта о деплое — он создан после выката
и помечен `artifact_scope`.

## Кандидат и источник

| Параметр | Значение |
|---|---|
| `candidate_commit` = `deployed_commit` | `273be95c8ff4f70e08dceef1daccbdd3082fc909` (DEPLOY_SOURCE, он же release-бамп 2.58.142→2.58.143) |
| Ревью-кандидаты слайсов | исторические (`432c7593`, `4fcbf684`, `98d16b94`, `a02aca0c`, `3d52e487`, `18baa36b` …) — сохранены в `evidence[].candidate_commit` как история приёмки |
| `source_path` | `plans/current_task.md` — принадлежит владельцу, **git-ignored и в worktree отсутствует**; читается из `C:\Code\Python\adminbot` |
| `source_sha256` | `04cbfe32cf0e3abd61aff3aafb27f9a5aa5e505638b6976df23b961ed0d6e330` (**2004 строки**, на 01.11.2026) |
| Предыдущий снимок источника | `7e7f0b49…` (1614 строк) — владелец дописал 1615-2004, дельта размечена в этом проходе |

Источник вырос на 390 строк **после** сборки карты: добавлены `ASAP-FC-EVIDENCE-STYLE-02` (1617-1748) и `ASAP-UI-02` (1751-2004).
Обе секции размечены сейчас (92 + 168 строк инвентаря и 8 + 12 прозаических обязательств, записи `delta_addenda`), иначе план-гейт
показывал 217 «source item not mapped».

## Что задеплоено и чем это доказано

| Группа | Кол-во строк | Доказательство | Статус |
|---|---|---|---|
| EVOL-001…022, 031, 032 | 24 | `w4-evol001-005`, `w4-evol006`, `w4-evol019-021`, `w1-evol010/011-013/015/031`, `w2a/2b/2c`, `w3-ui-foundation` + ревью-вердикты `APPROVED` | 22 VERIFIED, 010/031 READY_FOR_LIVE |
| EVOL-023, 024 (навигация/топбар/чистка) | 2 | `w7-nav-cleanup`, `cf628f97`, review-fix `31a8f2ed` (ghost-⛶, Esc→trigger, 114 ячеек) | VERIFIED |
| EVOL-025 (адаптивность) | 1 | `w9-responsive`, `0316d62b`, review-fix `1e0ad895` (heatmap/TMA/touch) | VERIFIED |
| EVOL-026…030 (разделы) | 5 | `w10-sections`, `d7eef0f9`, review-fix `1e0ad895`, `db890035` (модалка записи), `test_webapp_evol_w10_sections.py` | VERIFIED |
| EVOL-GLASS-SEAM (§6 EVOL-032) | 1 | `w6-glass-seam`, `3a0f89d2` (feImage subregion −6%/112%), sharpness 2.81→0.61 | VERIFIED |
| EVOL-SOCIAL-FRAME | 1 | `w5-social`, `0d36b235` (0-LLM frame, 15 тестов/10 сценариев) | VERIFIED |
| EVOL-VIDEO-INTENT | 1 | `w5-video`, `9dc6fba9` + review-fix `14b67272`/`fcdc69a8` | VERIFIED |
| EVOL-FACTCHECK-CRITICAL | 1 | `w5-factcheck`, `d036707a` + review blockers `3f62150f` (PG-директива, каталог, пины) | VERIFIED |
| ASAP-FC-ADMISSION-01 | 20 | `w7-fc-admission`, `432c7593`, review-fix `d561d68a` (cooldown_outcome) | VERIFIED |
| ASAP-VISION-SYNC-01 (89 из 93) | 89 | `w8-vision-sync-core`, `w8-vision-sync-wave2`, review-fix/wave2 `390cacaf`, `b6403881`, `ca15a2f6`, `e9cbd050`, `8d68960d`, `7131897b`, `a4be717c` | VERIFIED |
| ASAP-FC-EVIDENCE-STYLE-02 (§1-§5, §7-§9) | 7 `req` | `w10-fc-evidence-style`, `303e18e8`, review-fix `2033a2c0`, review-fix2 `54f44f05` (24 теста, 12/12 сценариев) | VERIFIED |
| ASAP-UI-02 (навигация/топбар/иконки, карточки, ленты, порядок, health) | 14 `req` | `asap-ui-02-matrix.md` (59 пунктов), `64204306`, review-fix `30f9920f`/`a6d28750`, `test_webapp_evol_w7_nav.py` (30), `test_webapp_evol_w9_responsive.py` (31), 114 + 152 ячейки без дефектов | VERIFIED |

Итог: **57 из 89** `req_id` закрыты и задеплоены (301 обязательная строка).

## Что осталось открытым (138 обязательных строк, все — «не VERIFIED»)

| Группа | Строк | Статус | Причина / где доказательство пробела |
|---|---|---|---|
| EVOL-SRC-READER | 27 | PENDING | конец очереди владельца, не начато |
| EVOL-COG-MAP | 41 | PENDING | конец очереди владельца, не начато (блокирует и `ASAP-UI-02-14`) |
| EVOL-033 | 1 | PENDING | интеграционный UI-гейт, не начат |
| EVOL-034…045 | 12 | PENDING | не начато (`037` — глобальный поиск, из-за него `ASAP-UI-02-03S/15` не закрыты) |
| EVOL-DoD | 1 | PENDING | требует закрытия EVOL-033 + релиза всего эпика |
| EVOL-010, EVOL-031 | 2 | READY_FOR_LIVE | код в проде; acceptance требует postdeploy-поведения (индексация/backfill; отсутствие replay-пути Smart Cache) — нужна одна агентская проверка на проде, участия владельца не требуется |
| ASAP-VISION-SYNC-ADMIN-01 | 4 | PENDING | стадийная кнопка «Проверить» не подключена к `services/media_readiness.run_admin_check` (в `web/api/routes.py` и `web/app.js` ссылок нет) — UI-часть отложена в UI-лейн (`w8-vision-sync-wave2` §8.1) |
| ASAP-FC-ES-TELEMETRY | 1 | PENDING | серверные счётчики `claim_coverage`/`claims_*` есть, UI-итога охвата проверки в web нет |
| ASAP-UI-02-11 | 3 | **BUILDING** | перегруппировка лент в один 4-секционный виджет идёт в worktree **незакоммиченной** (`web/index.html`, `web/app.js`, `web/static/app.css`, новый `tests/js/asap_ui02_status_ribbons_test.js`, F11-пины); в 2.58.143 этого нет; карта взамен «Графа связей» — за EVOL-COG |
| ASAP-UI-02-18 / -DOD | 18 | PENDING | 17-сценарный контракт: 12 PASS, №10 заблокирован разбиением лент, №11/№14 MISSING (COG, 037), №6/8/12/13/17 частичные |
| ASAP-UI-02-08 / -14 / -15 | 22 | PENDING | единый modal/sheet + слои overlay (z-index 40/35 против `--overlay-z: 50`); когнитивная карта (COG); глобальный поиск (037) |
| ASAP-UI-02-03S / -06N / -09S / -12W / -16T / -17B | 6 | PENDING | точка поиска в «⋯» без самого поиска; локальные плотности `app.css:1403/1469/4194/4549`; select/combobox; контрактный токен `warning`; сквозной motion-токен; per-layer Back-stack |

## ASAP-UI-02 — покомпонентный статус (из `audit/asap-ui-02-matrix.md`)

| `req_id` (срез) | Статус | Что фактически проверено |
|---|---|---|
| `-00` матрица состояний | VERIFIED | 59 пунктов: 46 DONE, 9 PARTIAL, 1 MISSING, 2 CONFLICTS, 1 N/A |
| `-01` отменённые альтернативы | VERIFIED | нижнего навбара и рейла нет, `mobile-topnav` удалён, логотип убран, второй шапки нет |
| `-02` структура навигации §2.1 | VERIFIED | drawer <1200 / sidebar ≥1200, 114 ячеек без второго навбара, раздел и scope не теряются |
| `-03` топбар §2.2 | VERIFIED | `title_once` = 1 на 4 маршрутах × 320/390, бейдж роли виден, имя чата с ellipsis + полный `title` |
| `-03S` точка входа второстепенных действий | PENDING | «⋯» и ghost-⛶ есть, application-wide поиска нет (037) |
| `-04` иконки §2.3 | VERIFIED | `[data-more-trigger]` троеточие, `[data-drawer-trigger]` menu-глиф 20px, hit 44×44, «⋯» только служебное |
| `-05` прокрутка/Telegram §2.4 | VERIFIED | нет hide-on-scroll, одна строка на 667×375, focus-trap 10 Tab, `--kb-offset` |
| `-06` визуальная система §3 | VERIFIED | один набор токенов, одна hairline, glass/polygon/refraction zero diff, контраст и disabled/loading |
| `-06N` одна роль = один компонент | PENDING | остаточные локальные плотности в `app.css` |
| `-07` карточки §4.1 | VERIFIED | system/record card, `openStatusRecord()` по `record_id`, диагностика по адресу сущности |
| `-08` единый детальный просмотр §4.2 | PENDING | модалка записи сведена (`db890035`), но z-index/portal/focus/backdrop частичны |
| `-09` / `-09S` контролы §4.3 | VERIFIED / PENDING | toggle с master/pending/revert, per-chat override, редактор промптов; select/combobox не сведён |
| `-10` разделы §5 (Аналитика/Модули/ИИ/Память/Доступы) | VERIFIED | `d7eef0f9`, `1e0ad895`, 35 тестов `test_webapp_evol_w10_sections.py` |
| `-11` канонический Статус (карта + 4 ленты) | BUILDING | незакоммиченная перегруппировка лент + legacy vis-network карта |
| `-12` / `-12W` health-семантика §6 | VERIFIED / PENDING | пять состояний, `unknown/disabled` нейтральны; контрактного `warning`-токена нет |
| `-13` ленты §7 | VERIFIED | субпиксельный движок, пауза/возобновление с текущей позиции, reduced-motion |
| `-14` когнитивная карта §8 | PENDING | NOT_APPLICABLE до EVOL-COG |
| `-15` глобальный поиск §9 | PENDING | MISSING до EVOL-037 |
| `-16` / `-16T` motion/прогресс §10 | VERIFIED / PENDING | реальные величины вместо 100%, reduced-motion; сквозного motion-токена нет |
| `-17` / `-17B` §11 | VERIFIED / PENDING | 152 ячейки (hScroll/offscreen/clipped = 0), zoom 200%; per-layer Back частичен |
| `-18` 17 сценариев §12 | PENDING | 12 PASS, 2 MISSING, 3 частичных, 1 заблокирован |
| `-DOD` | PENDING | зависит от `-11`, `-14`, `-15`, `-18` |

## Гейты

**План-гейт (из корня основного репозитория):**
`py <OPENCODE_CONFIG>\tools\requirements_gate.py check --map <worktree>\plans\features\evol\requirements-map.json --stage plan --repo C:\Code\Python\adminbot`
→ **EXIT 0**, `stage=plan inventory=832 manual=343 scoped=0 errors=0`.
Граф: 49 узлов, циклов нет; два новых узла (`ASAP-FC-EVIDENCE-STYLE-02`, `ASAP-UI-02`) добавлены с зависимостями от уже
существующих слайсов и включены в `EVOL-RELEASE.depends_on`; для `ASAP-UI-02` `write_scope` намеренно ограничен матрицей
(`actual_write_scope` перечисляет реально изменённые `web/**` и тесты, которые принадлежат EVOL-UI-NAV/CLEANUP/RESPONSIVE/
SECTIONS-MOVE/HEALTHGLASS — второй независимый писатель не объявлен).

**Релиз-гейт (полный эпик):**
`check --stage release --candidate 273be95c8ff4… --deployed-commit 273be95c8ff4… --repo C:\Code\Python\adminbot`
→ **EXIT 1**, `stage=release inventory=832 manual=343 scoped=439 errors=138`.
Состав ошибок — **однородный**: 133 × `mandatory not ['VERIFIED'] (got PENDING)`, 3 × `(got BUILDING)`, 2 × `(got READY_FOR_LIVE)`.
Ни одной ошибки инвентаря, sha источника, кандидата, `deployed_commit`, графа, отсутствующих артефактов или live-доказательств.
То есть гейт красный **ровно на незакрытом объёме эпика**, а не на бухгалтерии.

**Слотовый (scoped) релиз сейчас не зелёный ни для одного слайса:** замыкание зависимостей UI-цепочки указывает на ещё открытые
`EVOL-UI-CONTROLS/KEYBOARD/MOTION` и `EVOL-034…045`, поэтому `--slice EVOL-UI-STATUS-WIDGETS` даёт 5 ошибок вида
«required dependency … is not evidenced VERIFIED» + `EVOL-W0-AUDIT: no mandatory rows`. Фактический выкат был полным
кандидатом ветки, поэтому доказанность берётся из полного релиз-гейта, а не из слотового.

## Честные оговорки

1. **Нет файла вердикта ревью.** Независимая приёмка зафиксирована коммитами `review-fix`/`review blockers` ветки `evol/impl`
   и handoff'ом оркестратора; отдельного артефакта-вердикта в репозитории не существует — это записано в `evidence_convention`,
   а не заменено ссылкой на выдуманный файл. Для 014/019/020/021 UI-часть закрывалась волнами 023-030, отдельного вердикта по
   `18baa36b` в репозитории нет.
2. **`master` (3193b657) не содержит релизных коммитов** `2e48bfed`/`273be95c`: DEPLOY_SOURCE жил на `release/2.58.143` = `evol/impl`.
   Слияние релиза в `master` — отдельное действие оркестратора; на доказанность выката не влияет, но должно быть выполнено.
3. **Worktree грязный не по моей вине:** незакоммичены `web/app.js`, `web/index.html`, `web/static/app.css`,
   `tests/js/evol032_health_glass_test.js`, `tests/js/round1025_f11_status_grid_test.js`, `tests/test_evol001_005_status_widgets.py`,
   `tests/test_webapp_f11_round1025.py` и новый `tests/js/asap_ui02_status_ribbons_test.js` — это активный лейн перегруппировки лент
   (`ASAP-UI-02-11` = BUILDING). Ничего из этого не входит в 2.58.143.
4. **`ASAP-FC-EVIDENCE-STYLE-02` §6** закрыт только серверно: UI-итог охвата проверки отсутствует, поэтому `ASAP-FC-ES-TELEMETRY` = PENDING.
5. **`EVOL-010/031`** не переведены в VERIFIED: деплой подтверждает код и здоровье сервиса, но не поведение; это не Human Gate,
   а одна агентская проверка на проде.
6. Отчёт `deploy-2.58.143.md` создан после выката, поэтому его нет в дереве кандидата — помечено `artifact_scope`.
7. `strict_evidence` не включался: карта legacy, а включение strict — отдельное решение с миграцией всех доказательств.

## Что дальше (по приоритету)

1. Orchestrator: `reconciled: true` для `OI-2026-10-31-ASAP-FC-EVIDENCE-STYLE` и `OI-2026-10-31-ASAP-UI-02` в `plans/progress_scope.json`
   (обе секции размечены, план-гейт EXIT 0); знаменатель прогресса — 439 обязательных строк / 89 `req_id`.
2. DevOps/Builder: одна адресная проверка прода по `EVOL-010` (индексация/backfill) и `EVOL-031` (отсутствие replay-пути) → READY_FOR_LIVE → VERIFIED.
3. UI-лейн: довести незакоммиченную перегруппировку лент (`ASAP-UI-02-11`) и подключить стадийную кнопку «Проверить»
   к `run_admin_check` (`ASAP-VISION-SYNC-ADMIN-01` + `EVOL-UI-VISION-CHECK`), затем `ASAP-UI-02-18`.
4. Orchestrator: влить `release/2.58.143` в `master`, чтобы деплой-источник и основная ветка совпали.
5. Затем очереди владельца: `EVOL-037` (поиск) и `EVOL-COG-MAP` (карта) → снимают `ASAP-UI-02-03S/14/15/18/-DOD`,
   после них — `EVOL-SRC-READER`, `EVOL-034…045`, `EVOL-033`, `EVOL-DoD`.
