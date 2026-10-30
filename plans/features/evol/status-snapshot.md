# EVOL — статус по требованиям (снимок 31.10.2026)

Карта: `plans/features/evol/requirements-map.json` (54 обязательных требования: EVOL-001..045 + EVOL-DoD + 4 дельты аддендума 31.10
`EVOL-SOCIAL-FRAME`, `EVOL-VIDEO-INTENT`, `EVOL-FACTCHECK-CRITICAL`, `EVOL-GLASS-SEAM` + три поставленных в очередь поручения 31.10
`EVOL-SRC-READER`, `EVOL-COG-MAP`, `ASAP-FC-ADMISSION-01` + P0 corrective `ASAP-VISION-SYNC-01`).
Ветка реализации: `evol/impl`, вершина `fcdc69a8`; ASAP-FC-ADMISSION-01 реализован и принят по поведению на `432c7593`. Деплой не выполнялся.

## Как записан статус

Словарь `requirements_gate.py` строгий: `PENDING | BUILDING | REVIEW | VERIFIED | FAILED | BLOCKED_REAL_HUMAN_GATE | READY_FOR_LIVE`.
Поэтому ревью-принятые, но **не задеплоенные** требования держат `status: PENDING` + `review_verdict` (`APPROVED` — вердикт по коду/UI;
`APPROVED_BEHAVIOR` — поведение принято при открытой незначительной правке, кандидат один),
`review_candidate`, `review_scope`, `review_note` и привязку доказательств (`evidence[]`: `ref`, `observation`, `type`,
`artifact_path`, `artifact_branch`, `artifact_sha256`, `candidate_commit`). `VERIFIED` сознательно не выставлен.
Поле `candidate_commit` карты одно на карту и сейчас указывает на `432c7593` (кандидат ASAP-FC-ADMISSION-01): при ревью другого слайса
`--candidate` должен совпадать с его собственным ревью-кандидатом, и расхождение не является дефектом покрытия.
Артефакты-отчёты лежат в ветке `evol/impl` (`plans/features/evol/audit/w*.md`) и в `master` ещё не влиты.

## Таблица

| Задача | Backend | UI | Ревью | Деплой |
|---|---|---|---|---|
| EVOL-001 | PASS (`4fcbf684`+`98d16b94`) | PASS (живой рендер Playwright) | APPROVED | не задеплоено |
| EVOL-002 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-003 | PASS (`98d16b94`) | PASS (focus trap в review-fix) | APPROVED | не задеплоено |
| EVOL-004 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-005 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-006 | PASS (`4fcbf684`+`98d16b94`) | n/a (промпт/данные) | APPROVED | не задеплоено |
| EVOL-007 | PASS (`3d52e487`) | n/a (виджет закрыт в 001..005) | APPROVED | не задеплоено |
| EVOL-008 | PASS (`3d52e487`) | n/a | APPROVED | не задеплоено |
| EVOL-009 | PASS (`a02aca0c`) | n/a (данные, не экран) | APPROVED | не задеплоено |
| EVOL-010 | PASS (`0e853f7f`) | n/a | APPROVED | не задеплоено; live-проверка после релиза |
| EVOL-011 | PASS (`dc1fdba6`) | n/a | APPROVED | не задеплоено |
| EVOL-012 | PASS (`44437903`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-013 | PASS (`dc1fdba6`) | n/a | APPROVED | не задеплоено |
| EVOL-014 | PASS (`9eeb3532`+`a02aca0c`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-015 | PASS (`e7443fad`) | n/a | APPROVED | не задеплоено |
| EVOL-016 | PASS (`44437903`+`011fe8ff`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-017 | PASS (`be5ad652`) | PASS (`be5ad652`) | APPROVED | не задеплоено |
| EVOL-018 | PASS (док-контракт `95b8d275`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-019 | PASS (`4fcbf684`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-020 | PASS (`98d16b94`; F1/F2 в `18baa36b`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-021 | PASS (`4fcbf684`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-022 | n/a (фундамент) | PASS (слой токенов, `33a14034`) | APPROVED | не задеплоено |
| EVOL-031 | PASS (`28d55bd1`…`7492d325`) | n/a (UI-карточка удалена) | APPROVED | не задеплоено; live-проверка после релиза |
| EVOL-032 | n/a (фундамент) | PASS (`33a14034`) | APPROVED | не задеплоено |
| EVOL-023..030 | не начато | не начато | — | — |
| EVOL-033 | не начато | не начато — **интеграционный гейт** | — | — |
| EVOL-034..045 | не начато | не начато | — | — |
| EVOL-DoD | не достигнуто (нужен релиз + EVOL-033) | — | — | — |

Итого привязано доказательств: **24 требования** (001..022, 031, 032). Не начато: 23 требования (023..030, 033..045) + DoD.
Дополнительно из аддендума 31.10: 3 требования в работе (`BUILDING`), 1 не начато (`PENDING`) — доказательств пока нет.
Дополнительно из поручений 31.10: 1 требование с привязанным ревью-доказательством (`ASAP-FC-ADMISSION-01`, `PENDING` +
`APPROVED_BEHAVIOR`), 2 в очереди без доказательств (`EVOL-SRC-READER`, `EVOL-COG-MAP`), 1 P0 corrective в работе
(`ASAP-VISION-SYNC-01`). Итоговый знаменатель обязательных требований: **54**, из них с привязанными доказательствами — **25**.

## Аддендум 31.10.2026 — четыре дельты активного эпика (OI-2026-10-31-EVOL-ADDENDUM)

Источник: `plans/current_task.md` строки **911-1155** (социальный контекст §§1-3, видео §4, критический фактчек §5,
стеклянный шов EVOL-032 §6). Разложено в карте: 145 строк (4 `required` + 125 `duplicate` + 16 `context`),
все строки диапазона классифицированы. Новые слайсы добавлены в `slice-graph.json` (волна W5) — это дельты, а не новый эпик.

| Слайс | Что закрывает | Зависит от (уже поставлено) | Статус |
|---|---|---|---|
| `EVOL-SOCIAL-FRAME` | SocialTurnFrameBuilder (0 LLM) из message_identity/quote_resolver/canonical_context → существующие L1/Decision/Writer; 10 сценариев §3 | `EVOL-B-QUOTE`, `EVOL-B-SMARTCACHE`, `EVOL-B-PROMPTREG`, `EVOL-B-PROMPTCONV`, `EVOL-W0-AUDIT` | `BUILDING` (реализация+тесты в рабочей копии, не закоммичено) |
| `EVOL-VIDEO-INTENT` | единый VideoIntent, связка «просьба → отдельный репост», pending TTL, single-flight, summary ≠ download; 8 сценариев §4.5 | `EVOL-B-QUOTE`, `EVOL-W0-AUDIT` | `BUILDING` |
| `EVOL-FACTCHECK-CRITICAL` | отдельная секция «Критический разнос» из того же checked verdict, директива в реестре версий промптов, настройка в модуле «Фактчек», семантический guard; 8 кейсов §5.4 | `EVOL-B-PROMPTREG`, `EVOL-B-PROMPTCONV`, `EVOL-W0-AUDIT` | `BUILDING` (реализация закоммичена `d036707a`, независимого вердикта ревью в карте нет) |
| `EVOL-GLASS-SEAM` | первопричина прямого шва в общем стеклянном слое + before/after в движении (normal/alert, desktop/mobile), внутри приёмки EVOL-032 | `EVOL-UI-HEALTHGLASS` | `PENDING` (не начато) |

Рёбра графа: все четыре добавлены в `EVOL-RELEASE.depends_on`; `EVOL-GLASS-SEAM` дополнительно в `EVOL-UI-FULLDOD.depends_on`
(финальный UI-DoD обязан включать устранение шва). Доказательств (`evidence[]`) у новых требований нет — коммита кандидата ещё нет,
поэтому `BUILDING`/`PENDING`, без `VERIFIED` и без `review_verdict`.
Оговорка по §5.3: UI-часть настройки живёт в `web/app.js` — этот файл остаётся за UI-цепочкой, отдельного параллельного писателя нет
(зафиксировано в `depends_note` узла).

## Поручения 31.10.2026 — SRC/COG в очереди, ASAP-FC-ADMISSION-01 принят по поведению

Два отдельных более поздних поручения владельца, не входящих в аддендум 911-1155. Обе записи зарегистрированы в
`plans/progress_scope.json` как `OI-2026-10-31-EVOL-SRC-COG` и `OI-2026-10-31-ASAP-FC-ADMISSION` (обе `reconciled: false` —
глобальный индекс обновляет Orchestrator; здесь только карта/граф/снимок).

| Слайс (req_id) | Строки источника | Что закрывает | Зависит от (уже поставлено) | Волна | Статус |
|---|---|---|---|---|---|
| `EVOL-SRC-READER` | 1158-1235 (§1) | Source Code Reader: discovery → locator → verified fetch → bounded follow-up → Evidence Contract, безопасность (§1.2), поведение при неоднозначности (§1.3), правила доказательности §1.4, 7 конечных сценариев §1.5 | `EVOL-W0-AUDIT`, `EVOL-B-QUOTE`, `EVOL-B-TELEMETRY`, `EVOL-B-PROMPTREG`, `EVOL-SOCIAL-FRAME`, `EVOL-VIDEO-INTENT` | W6 | `PENDING` (конец очереди) |
| `EVOL-COG-MAP` | 1238-1348 (§2) | Когнитивная карта вместо «Графа связей»: адаптер данных §2.3, визуальная система §2.4, легенда/LOD §2.4, drilldown к источнику §2.5, паритет старого графа §2.6, mobile-first embedded+fullscreen §2.7, производительность §2.8, проверки §2.9; `/api/memory/graph` и `/api/memory/stats` сохраняются | `EVOL-UI-FULLDOD`, `EVOL-UI-HEALTHGLASS` (EVOL-032), `EVOL-UI-STORIES` (EVOL-021), `EVOL-UI-DESIGN` (EVOL-022), `EVOL-B-EXP`, `EVOL-B-FACTS`, `EVOL-B-MEMCYCLES`, `EVOL-B-TELEMETRY`, `EVOL-SRC-READER` | W7 | `PENDING` (конец очереди) |
| `ASAP-FC-ADMISSION-01` | 1363-1426 (§1-§5) | Механизм допуска фактчека (явное намерение важнее «ерундовости», три различаемых исхода, §2) + cooldown после ложного отказа (§3 этапы A-E), 8 детерминированных сценариев §5 | `EVOL-W0-AUDIT`, `EVOL-FACTCHECK-CRITICAL`, `EVOL-B-QUOTE`, `EVOL-B-PROMPTREG`, `EVOL-SOCIAL-FRAME`, `EVOL-VIDEO-INTENT` | W5-ADMISSION | `PENDING` + `review_verdict=APPROVED_BEHAVIOR` на `432c7593` (18 тестов, 8/8 сценариев); правка телеметрии в полёте |

Порядок по указанию владельца: **ASAP-FC-ADMISSION-01** берётся сразу после завершения фактических правок фактчека и Reviewer-приёмки
`EVOL-FACTCHECK-CRITICAL` (не параллельно, без повторного большого аудита). **EVOL-SRC-READER** и **EVOL-COG-MAP** — строго в конец
очереди, после текущих UI-волн; оба добавлены в `EVOL-RELEASE.depends_on`, чтобы релиз не опережал поручение. У `EVOL-SRC-READER`/`EVOL-COG-MAP`
доказательств нет (`PENDING`). У `ASAP-FC-ADMISSION-01` доказательства привязаны к кандидату `432c7593`, но статус остаётся `PENDING`:
`VERIFIED` не выставляется до деплоя.

Классификация строк 1158-1430: **124** записи (88 `required` + 23 `duplicate` + 13 `context`); непокрытых строк нет.
Прозаические абзацы (1225, 1242/1244/1246/1248, 1302, 1339-1347, 1395/1397/1399/1401/1403, 1360) не входят в построчный инвентарь
гейта, поэтому их обязательства закреплены в `acceptance` соответствующих req и в `reason` ближайших строк — проверять их нужно по
тексту acceptance, а не по числу строк.

## ASAP-FC-ADMISSION-01 — поведение принято, телеметрия в полёте, деплоя нет

Кандидат: **`432c7593`** (ветка `evol/impl`, база `14b67272`). Отчёт: `plans/features/evol/audit/w7-fc-admission.md`
(23 КБ), тесты `tests/test_evol_fc_admission.py`.

| Что проверено | Результат |
|---|---|
| 8 детерминированных сценариев §5 | 8/8 PASS, 18 тестов, все офлайновые (LLM/сеть/Telegram не вызываются) |
| Регрессия | `-k factcheck` 582 passed; широкий срез 2209 passed / 3 failed — те же 3 падения воспроизводятся на базовом `14b67272`; импорт-зависимые 1388 passed |
| Независимое ревью | `review_verdict = APPROVED_BEHAVIOR`: поведение принято; открыта только небольшая правка телеметрии допуска, кандидат тот же |
| Первопричина | не фразы и не «плохой» текст, а семантика допуска: узкий `_has_predicate` + отсутствие учёта явного запроса; второй дефект — cooldown ставился до разрешения цели |
| Живой Telegram | не использовался (DoD запрещает живые публикации) — остаточная проверка идёт по новой телеметрии `[factcheck_admission]` после релиза |

В карте обновлены 25 строк (20 `required` + 5 `duplicate`): у всех `review_verdict=APPROVED_BEHAVIOR`, `review_candidate=432c7593`,
у 20 обязательных привязаны доказательства (`evidence[]`: отчёт `artifact_sha256`, файл тестов `artifact_sha256`, `candidate_commit`).
`status` сознательно остаётся `PENDING`: `VERIFIED` выставляется после деплоя этого кандидата. Пути `write_scope` в `slice-graph.json`
исправлены на фактические (`tests/test_evol_fc_admission.py`, `plans/features/evol/audit/w7-fc-admission.md`); ранее там были
несуществующие `tests/test_evol_factcheck_admission.py` и `audit/w5-factcheck-admission.md`.

## ASAP-VISION-SYNC-01 — P0 corrective, волна W8, в работе

Источник: `plans/current_task.md` строки **1433-1614** (поручение `OI-2026-10-31-ASAP-VISION-SYNC`), зарегистрировано после того,
как карта была построена, поэтому sha источника и инвентарь пересобраны в этом проходе.

| Слайс (req_id) | Строки | Что закрывает | Зависит от | Волна | Статус |
|---|---|---|---|---|---|
| `ASAP-VISION-SYNC-01` | 1433-1614 | MediaReadinessBarrier/`prepare_media_evidence` поверх существующих `mca_vision`/`recognize_target`/`render_media_context_async`/`chat_context`/durable jobs; разрешение целевого изображения (own_caption/reply/quote/adjacent/album/ожидающее намерение, `ambiguous` вместо случайного фото); стадийная синхронизация L1/FactCheck/Writer и актуальная ревизия перед отправкой; одна логика допуска с `ASAP-FC-ADMISSION-01`; выходной контракт Vision без магического `max_tokens=1024`; end-to-end «Проверить» и цепочка телеметрии; 20 сценариев §8 | `EVOL-W0-AUDIT`, `EVOL-B-VISION-ADAPT`, `EVOL-B-TELEMETRY`, `EVOL-B-QUOTE`, `EVOL-B-SMARTCACHE`, `EVOL-SOCIAL-FRAME`, `EVOL-VIDEO-INTENT`, `EVOL-FACTCHECK-CRITICAL`, `EVOL-SRC-READER`, `ASAP-FC-ADMISSION-01`, `EVOL-UI-VISION-CHECK` | W8 | `BUILDING` (ядро Vision и консьюмеры в работе в отдельном лейне; в карте `PENDING`, доказательств нет) |

Классификация строк 1433-1614: **125** записей — 86 строк построчного инвентаря гейта (`items`) + 39 прозаических абзацев
(`additional_requirements`, id вида `ASAP-VISION-MAN-<строка>`), итого 93 `required` + 14 `duplicate` + 18 `context`; непокрытых
строк нет. Обязательства размечены групповой меткой `group`: `INVARIANT` (7), `CONTRACT` (9), `ASSOC` (11), `PENDING-INTENT` (1),
`SYNC` (10), `FC-GATE` (9), `DURABLE` (2), `OUTPUT` (10), `ADMIN` (4), `BOUNDS` (7), `ACCEPT20` (22), `DOD` (1).

Границы, зафиксированные в графе:
- `web/index.html`, `web/app.js`, `web/static/app.css` и `web/api/vision_check.py` **не** входят в `write_scope` этого слайса: это
  деливераблы UI-волны (`EVOL-UI-VISION-CHECK`), поэтому группа `ADMIN` сдаётся совместно — слайс поставляет backend-контракт, стадии
  диагностики и телеметрию, UI-часть кнопки «Проверить» и индикаторов стадий реализует тот же единственный UI-писатель; второго
  параллельного UI-писателя нет.
- `handlers/youtube.py` (видео-лейн) не трогать; карта и граф правились только чтением кода.
- Ребро `ASAP-FC-ADMISSION-01` — это требование «одна логика допуска», а не второй приватный фильтр и не вторые правила cooldown.
- Релиз не может опережать corrective: `ASAP-VISION-SYNC-01` добавлен в `EVOL-RELEASE.depends_on` (17 зависимостей).

## Гейт плана

`py C:\Users\main\.config\opencode\tools\requirements_gate.py check --map <worktree>\plans\features\evol\requirements-map.json --stage plan --repo C:\Code\Python\adminbot`
→ **EXIT 0**, `stage=plan inventory=616 manual=318 scoped=0 errors=0`.
Запускать **из корня основного репозитория** (`C:\Code\Python\adminbot`): `plans/current_task.md` в `.gitignore` и в worktree отсутствует,
иначе гейт даёт `source not present` и лавину ложных «gone or edited». Карта живёт в worktree, поэтому `--map` указывает на неё, а CWD —
корень основного репозитория (иначе `source_path` не разрешается).

Состав ошибок сейчас — **0**. Ранее падавшие 124 ошибки `source item not mapped` для строк **1166-1428** закрыты проходом SRC/COG+ASAP-FC.
В этом проходе sha источника пересобран под добавление владельца (1614 строк): ранее `source_sha256` соответствовал снимку 1430 строк,
из-за чего ревью-гейт падал с `authoritative source changed` + ~124 `source item not mapped` на 1433-1614. Сейчас расхождений sha — **0**,
непокрытых строк — **0**, ошибок графа (циклы, пересечение `write_scope`, отсутствующие узлы) — **0**.

Ревью-гейт по принятому поведению фактчека:
`check --stage review --slice ASAP-FC-ADMISSION-01 --candidate 432c7593 --repo C:\Code\Python\adminbot`
→ `stage=review inventory=616 manual=318 scoped=20 errors=20`. Все 20 ошибок — **только** `mandatory not ['VERIFIED'] (got PENDING)`,
то есть честное следствие правила «нет `VERIFIED` до деплоя»; кандидат совпал с `candidate_commit` карты, ни одного
`evidence missing` / `no evidence bound to reviewed candidate` нет. Зелёным этот гейт станет после деплоя `432c7593` (или кандидата
с телеметрической правкой) и перевода строк в `VERIFIED`.

## Что дальше

1. Orchestrator: перенести обновлённую карту в ветку `evol/impl` (в `master` каталог `plans/features/evol/` сейчас **untracked**, правка живёт только в рабочей копии).
2. Orchestrator: выставить `reconciled: true` для `OI-2026-10-31-EVOL-SRC-COG`, `OI-2026-10-31-ASAP-FC-ADMISSION` и
   `OI-2026-10-31-ASAP-VISION-SYNC` в `plans/progress_scope.json` (карта/граф/снимок покрывают все три; непокрытых строк нет,
   план-гейт EXIT 0) и учесть в знаменателе прогресса 54 обязательных требования.
3. ASAP-FC-ADMISSION-01: принять телеметрическую правку в тот же кандидат, выполнить релиз и только потом перевести 20 строк в `VERIFIED`
   (ревью-гейт станет зелёным). Живой Telegram не требуется.
4. ASAP-VISION-SYNC-01 (W8): довести ядро (barrier/resolver + консьюмеры + output contract Vision + админ-проверка), прогнать 20 сценариев §8
   и релевантные регрессии, затем независимое ревью; UI-часть согласуется с писателем `EVOL-UI-VISION-CHECK`.
5. Ревью `18baa36b` → снять `ui_review: pending` у 014/019/020/021 и привязать UI-доказательства.
6. Затем EVOL-033 как интеграционный гейт, после него — релиз и `VERIFIED` (для 010/031 плюс live-проверка на проде).
7. Порядок очереди после текущих волн: `ASAP-FC-ADMISSION-01` (релиз принятого поведения) → `ASAP-VISION-SYNC-01` (W8) → `EVOL-SRC-READER` (W6) →
   `EVOL-COG-MAP` (W7) → `EVOL-RELEASE`. Параллельно эти слайсы с текущими писателями не запускать: у SRC/COG пересечение по `handlers/**`,
   `web/**`, у ASAP-FC — по `services/factcheck_*`, у VISION — по `services/mca_vision.py`, `handlers/**`, `services/direct_chat_service.py`,
   `web/api/vision_check.py`.

