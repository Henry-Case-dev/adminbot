# P0 Corrective Factcheck/Speech — финальная приёмка (REPORT + ACCEPT)

**Лейн:** PM-FINAL-ACCEPTANCE. **Дата:** 2026-10-25 (системное локальное время).
**candidate = deployed =** `f0e6a0cd68b8a1f93fc8ad242834d44a383b7f9b` (APP_VERSION 2.58.125).
**Карта:** `plans/features/p0-corrective-factcheck-speech/requirements-map.json` (strict_evidence=true, slice_graph_path=slice-graph.json).

## 1. Сводка

| Показатель | Значение |
|---|---|
| required-строк в карте | 584 |
| уникальных req_id | 449 |
| VERIFIED (строк) | 554 |
| PENDING | 21 |
| READY_FOR_LIVE (postdeploy) | 5 |
| FAILED | 4 |
| не-VERIFIED уникальных req_id | 22 |

Release-gate (полный SHA): `check --stage release --candidate f0e6a0cd…b7f9b --deployed-commit f0e6a0cd…b7f9b` → **EXIT 1, errors=30** (только статусные строки).
Plan-gate: `check --stage plan` → **EXIT 0** (inventory=401, manual=306, errors=0).

Вызов с укороченным `--candidate f0e6a0cd` даёт EXIT 1 / 1170 ошибок **искусственно**: гейт сравнивает `--candidate` со строкой точного равенства, а в карте и evidence хранится полный 40-символьный SHA, поэтому все 554 VERIFIED-строки выглядят «unbound». Это дефект вызова, не карты.

## 2. FAILED (4 строк)

| req_id | источник | почему FAILED / что нужно |
|---|---|---|
| `REQ-EX-STABLE-EFFECT` | M00461-REQ-EX-STABLE-EFFECT | FAILED: влияние режима нестабильно (срабатывание ~раз в десятки реплик). Нужна серия проб с устойчивым результатом. |
| `REQ-EX-PROVE-REAL-PATH` | M00471-REQ-EX-PROVE-REAL-PATH | FAILED: закрытие доказано только на тестах сборки промптов, не на реальном модельном пути. |
| `EX-01` | M00566-EX-01 | FAILED: живой канареечный замер 2.58.122 — 1 совпадение из 8 ответов; кандидатский v2 (3/6 и 1/4) не задеплоен. Нужен новый живой замер после исправления. |
| `EX-02` | M00568-EX-02 | FAILED: различия видны в промпте, но не в результатах реальных LLM-проб (1/8). Нужен новый замер после исправления. |

## 3. READY_FOR_LIVE / postdeploy (5 строк)

| req_id | источник | что осталось |
|---|---|---|
| `REQ-EX-DIAG-CHAIN` | M00442-REQ-EX-DIAG-CHAIN | READY_FOR_LIVE (postdeploy): нужен срез цепочки effective config → LLM payload → raw → postprocessed → outbound по каждому звену на живом пути. |
| `REQ-EX-PROBE-MATRIX` | M00467-REQ-EX-PROBE-MATRIX | READY_FOR_LIVE (postdeploy): нужна матрица прогонов по разным ситуациям и режимам Expression; сейчас различий нет. |
| `FC-05` | M00538-FC-05 | READY_FOR_LIVE (postdeploy): нужен живой сценарий истечения бюджета поиска (техническое ограничение, не «нет доказательств»). |
| `FC-08` | M00544-FC-08 | READY_FOR_LIVE (postdeploy): нужен живой сценарий «тезис и в подписи, и на изображении». |

## 4. PENDING (21 строк) — блокеры

| req_id | источник | строк | блокер |
|---|---|---|---|
| `REQ-ADD3-EX-FREQ-CHECKS` | L01160 | 6 | PENDING: проверка FREQUENT (выбор режима, конкуренция с Core, вытеснение квотами, влияние на результат) не дала положительного исхода — живой результат 1/8. |
| `REQ-ADD3-EX-FREQ-WHY` | L01166 | 1 | PENDING: объяснение, почему прежние реальные пробы не показали устойчивых различий, не оформлено отдельным артефактом. |
| `REQ-ADD3-EX-ACC-DIFF` | L01245 | 1 | PENDING: OFF/OCCASIONAL/FREQUENT фактически не различаются устойчиво. |
| `REQ-ADD3-EX-ACC-EFFECT` | L01246 | 1 | PENDING: заметного влияния FREQUENT на собственную речь нет (1/8). |
| `REQ-ADD3-EX-ACC-NO-INSERT` | L01247 | 1 | PENDING: отсутствие механической вставки не подтверждено живым артефактом на текущем кандидате. |
| `REQ-ADD3-EX-ACC-POSTPROC` | L01248 | 1 | PENDING: не проверено, что постобработка не подавляет результат FREQUENT. |
| `REQ-ADD3-EX-ACC-CORE` | L01249 | 1 | PENDING: технически Core сохранён (Core rev 8, FACTORY_SET 47f0d1eb8de4 неизменен — binding-258125), но строка закрывается в составе приёмки Expression после исправления FREQUENT; отдельного артефакта приёмки нет. |
| `REQ-ADD3-EX-ACC-PROBES` | L01250 | 1 | PENDING: офлайн-LLM-пробы OFF/OCCASIONAL/FREQUENT на действующем провайдере не дали устойчивого различия; нужен новый прогон. |
| `REQ-DONE-MAIN-CRITERION` | M00635-REQ-DONE-MAIN-CRITERION | 1 | PENDING: главный критерий не выполнен — FREQUENT фактически не соответствует настройке владельца. Закрывается только после исправления Expression и нового живого замера. |
| `REQ-ADD3-EX-INSPECTOR-PRESENT` | M01150-REQ-ADD3-EX-INSPECTOR-PRESENT | 2 | PENDING: нужен явный артефакт сборки с блоком <Expression_Settings> на текущем кандидате (наличие в Inspector не снято как доказательство). |
| `REQ-ADD3-EX-FULL-PATH` | M01154-REQ-ADD3-EX-FULL-PATH | 2 | PENDING: полный путь global/chat setting → effective → LLM payload → raw → Style Policy → Telegram не снят целиком на текущем кандидате. |
| `REQ-ADD3-EX-FREQ-SEMANTICS` | M01170-REQ-ADD3-EX-FREQ-SEMANTICS | 1 | PENDING: семантика FREQUENT (привычная заметная нецензурная лексика в собственной речи) фактически не реализована. |
| `REQ-ADD3-EX-REAL-PROBES` | M01174-REQ-ADD3-EX-REAL-PROBES | 1 | PENDING: реальные офлайн-пробы на действующем провайдере в требуемом объёме не выполнены/неубедительны. |
| `REQ-ADD3-EX-COMPARE-ARTIFACTS` | M01176-REQ-ADD3-EX-COMPARE-ARTIFACTS | 1 | PENDING: нет артефакта сравнения payload / сырых ответов модели / постобработки. |

## 5. Что закрыто этим артефактом (REPORT / ACCEPT)

Закрыто **35 required-строк** (10 req_id) на существующих артефактах, без новых замеров и без изменения кода:

| req_id | строк | основание |
|---|---|---|
| `REQ-ADD3-ACC-REPORT` | 11 | Отчёт §6 (10 пунктов) существует в виде артефактов: arch-quota-audit.md §1/§2 (пути, квоты и адреса, B-лимиты), quota-removal.md (что устранено/сохранено, fallback/retry, worker_budget), canary/report.md §3/§5/§6 (FACTCHECK/CORE/FREQUENT), binding-258125.md (деплой 2.58.125 и состояние прода, неустранённые проблемы). |
| `REQ-ADD3-ACC-REPORT-COVERAGE` | 1 | arch-quota-audit.md §7 «Покрытие и непроверенное» — что найдено, что проверено, что осталось непроверенным (runtime payload, рестарт, провайдерские различия, C2/C4/C6). |
| `REQ-ADD3-ACC-REPORT-NO-FULL-CLAIM` | 1 | arch-quota-audit.md §7 прямо запрещает заявлять «полную очистку проекта» до runtime-подтверждения; итоговые документы такого заявления не содержат. |
| `REQ-ADD3-ACC-REVIEW-CHECKS` | 1 | review-quota-quotes.md: независимый Reviewer нашёл F1 (остаточная квота), F2, C1/C6 и расхождения карты — проверялась полнота охвата, не только корректность правок. |
| `REQ-ADD3-ACC-REVIEW-CLASS-A-PROOF` | 1 | arch-quota-audit.md §2A: по каждому A1–A6 приведено доказательство искусственности квоты (file:line, отсутствие ключа в settings, тип возврата, докстринг↔код); B/C отделены. |
| `REQ-ADD3-ACC-REVIEW-NO-REFACTOR` | 1 | quota-removal.md (точечные правки бюджета + тесты) и дельта 2.58.125 (один fix style_policy.py + bump) — общего рефакторинга нет. |
| `REQ-ADD3-ACC-CONSTRAINTS` | 7 | quota-removal.md + binding-258125.md: без нового эпика/сервисов/слоёв, без новых LLM-вызовов в pipeline, функции не отключались, B-лимиты/retry/fallback/worker_budget сохранены, ΔDDL=0, FACTORY_SET и Core rev неизменны. |
| `REQ-ADD3-ACC-WORKFLOW` | 1 | review-quota-quotes.md / review-factcheck.md / review-factcheck-r2.md / review-prompts.md (независимые ревью с Needs Fixes) + production deployment 2.58.125 (release-258125/README.md, binding-258125.md). |
| `REQ-ADD3-ACC-NO-DONE` | 1 | binding-258125.md и canary/report.md: живая проверка после выката выполнена и дала отрицательный результат; задача не закрыта, MAIN-CRITERION остаётся PENDING. |
| `REQ-ADD3-ACC-REVIEW-REJECT` | 10 | review-quota-quotes.md (Needs Fixes, F1/F2) и binding-258125.md (Expression FAILED): Reviewer не принял результат при сработавших условиях §5; audit §1/§2C показывает, что проверка не сведена к Composer и поиску имён. |

Каждая закрытая строка получила candidate-bound evidence (`candidate_commit = f0e6a0cd…`), `ref`, `observation`, `type` и реальный `artifact_path` с `artifact_sha256`.

**Чего эти закрытия не доказывают:** они подтверждают *наличие и содержание* отчётных/ревью-обязательств и дисциплину отказа от приёмки, а **не** работоспособность FREQUENT. `REQ-DONE-MAIN-CRITERION` остаётся PENDING, EX-01/EX-02/STABLE-EFFECT/PROVE-REAL-PATH — FAILED.

Особо: `REQ-ADD3-ACC-REVIEW-REJECT` закрыт как «механизм отказа сработал» (Reviewer не принял результат при сработавших условиях §5: F1 остаточная квота, F2 кавычки, незакрытые payload-проверки). Это требует подтверждения Reviewer, что каждая из 10 перечисленных строк действительно была проверена, а не выведена из общего вердикта.

## 6. Полная матрица по 584 required-строкам

Одна строка таблицы = один `req_id`; `строк` — сколько source-строк карты указывают на него; `live` — требуется ли производственная проверка.

| req_id | статус | слайс | строк | live | доказательство (артефакты) | остаток |
|---|---|---|---|---|---|---|
| `REQ-GOV-NO-NEW-LLM` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-NO-HARDCODE` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-NO-RETRY-INSTEAD-CAUSE` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-KEEP-GUARDS` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-NO-FORCED-PROFANITY` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-KEEP-CORE` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-NO-CHECKUP-COPY` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-SINGLE-SOURCE` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-NO-TESTS-AS-PROOF` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-NO-NEEDLESS-COMPLEXITY` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-PR-DIAG-WHY` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-DIAG-HOW` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-DIAG-MIGRATION` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-DIAG-CLASS` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-DIAG-ACTUAL-TEXT` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-PR-DIAG-OTHERS` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-PR-KEEP-HISTORY` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-COMPARE-REVISIONS` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-PR-RESTORE-LINK` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-PR-KEEP-USER-EDIT` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-LEGACY-SPLIT` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-CONFIRM-ACTIVE` | VERIFIED | PROMPTS | 1 | да/postdeploy | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-UI-SAVED` | VERIFIED | PROMPTS | 1 | да/preprod | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-UI-EFFECTIVE` | VERIFIED | PROMPTS | 1 | да/preprod | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-UI-REASON` | VERIFIED | PROMPTS | 1 | да/preprod | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-UI-SOURCE-REV` | VERIFIED | PROMPTS | 1 | да/preprod | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-UI-RESOLVE` | VERIFIED | PROMPTS | 1 | да/preprod | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-FC-STEP-INPUT` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-STEP-DECISIONS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-STEP-DROPPED` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-STEP-CONFIG` | VERIFIED | FORENSIC | 1 | да/preprod | `evidence/forensic.md` |  |
| `REQ-FC-STEP-ERRORS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-CAPTION` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-IMAGE` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-CLAIMS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-META` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-DATE` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-IDENTIFIERS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-NO-DICTIONARIES` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-NO-NEW-CLASSIFIER` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-FC-NO-PRODUCT-HARDCODE` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-NO-QUERY-INFLATION` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-NO-REPEAT-FAILED` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-CLASS-CONFIRMED` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-CLASS-REFUTED` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-CLASS-UNCONFIRMED` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-CLASS-FORECAST` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-CLASS-OPINION` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RENDER-TRUTH` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RENDER-PARTS` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RENDER-LINKS` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RENDER-SECONDARY` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RENDER-NO-FACT` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RENDER-NO-FAKE-CLAIM` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-CK-SCOPE-LOGS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-SCOPE-ERRORS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-SCOPE-CAUSES` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-SCOPE-FAULTS-WARNINGS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-SCOPE-CLEAR-STORY` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-SCOPE-IRONY` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-SCOPE-REPORT-LIMITS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-KEEP-DIALOGUE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-KEEP-SHARP` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-KEEP-IRONY` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-KEEP-METAPHOR` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-KEEP-TRANSITIONS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-KEEP-SIMPLE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CORE-READ-ACTIVE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-READ-FACTORY` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CORE-FIND-EXISTING` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-DEDUP-ONLY` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-INTEGRATE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-KEEP-VOICE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-UPDATE-FACTORY` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-FULL-COMPACT` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-EX-DIAG-EFFECTIVE` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-DIAG-PAYLOAD` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-DIAG-BUDGET` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-DIAG-GENRE` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-DIAG-HIDDEN` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-DIAG-POSTPROC` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-DIAG-MODEL` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-DIAG-UI` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-NO-EVERY-MESSAGE` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-NO-QUOTAS` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-NO-POSTPROC-SWAP` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-NO-HIDDEN-TOXICITY` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-NO-SEPARATE-PERSONA` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-NO-QUOTE-EDIT` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-OPS-VISION-PHASE` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-OPS-VISION-SQLITE` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-OPS-VISION-BACKGROUND` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-OPS-VISION-BLOCK` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-OPS-VISION-ERRORS` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-DONE-NO-FALSE-PROMPT` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-DONE-NO-FALSE-CORE` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-DONE-NO-FALSE-PROFANITY` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-DONE-NO-FALSE-FACTCHECK` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-DONE-NO-FALSE-SEARCH` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-DONE-NO-FALSE-CHECKUP` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-CAUSES` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-CONFIG` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-CHANGES` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-PROMPTS` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-CHECKS` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-LIVE` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-UNCONFIRMED` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-SUT-KEEP-GENRE-CORE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-VOICE-METHOD-NOT-ROLE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-LAYER-OWNERSHIP` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-CAPITAL-NORMAL` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-FULL-NOT-SIMPLIFIED` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-NO-ARTIFICIAL-DEPENDENCY` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-SUT-FROZEN-REF` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-CHECKUP-TARGET-EDITION` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-SUT-ERRORS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-SUT-WARNINGS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-SUT-CLEAN` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-SUT-NO-RAW` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-CORE-ONLY-MISSING` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-EXPR-NO-GENRE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-EXPR-NO-GENRE-LIST` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-EXPR-KEEP-FREQUENT` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-EXPR-REAL-CAUSE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-EXPR-OFF-FREQUENT-SEMANTICS` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-STYLE-SINGLE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-STYLE-CAPITAL-NO-GLOBAL-REGEX` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-STYLE-PLAIN-GENRE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-STYLE-OUTBOUND-PATH` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-STYLE-ACTUAL-OUTBOUND` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-PR-DIAGNOSE` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-A4-PR-REGISTER-RELIABLE` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-PR-UI-TRIPLE` | VERIFIED | PROMPTS | 1 | да/preprod | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-PR-CHECKUP-MIGRATION` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-PR-KEEP-PREV` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-PR-PERSIST-DEPLOY` | VERIFIED | PROMPTS | 1 | да/postdeploy | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-REVIEW-CHECKS` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REPORT` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-ADD3-Q-REPLACE` | VERIFIED | QUOTES | 5 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-REMOVE` | VERIFIED | QUOTES | 3 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-KEEP-MODULE` | VERIFIED | QUOTA-AUDIT | 3 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-KEEP-GLOBAL` | VERIFIED | QUOTA-AUDIT | 2 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-KEEP-USER-SETTINGS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-KEEP-MAIN-OFF` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-KEEP-NEW-OFF` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-TARGETS` | VERIFIED | QUOTA-AUDIT | 6 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-MECHANISMS` | VERIFIED | QUOTA-AUDIT | 4 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-AUDIT-NEW-ARCH` | VERIFIED | QUOTA-AUDIT | 9 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-AUDIT-SMART` | VERIFIED | QUOTA-AUDIT | 15 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-AUDIT-LEGACY` | VERIFIED | QUOTA-AUDIT | 11 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-METHOD-SURFACES` | VERIFIED | QUOTA-AUDIT | 9 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-KEEP-SAFETY` | VERIFIED | QUOTA-AUDIT | 7 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-KEEP-LIMITS` | VERIFIED | QUOTA-AUDIT | 14 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-CQ-POINTS` | VERIFIED | COMPOSER-QUOTA | 3 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-CQ-ZERO-NONE` | VERIFIED | COMPOSER-QUOTA | 2 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-CQ-STYLE-EXEMPT` | VERIFIED | COMPOSER-QUOTA | 1 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-CQ-NO-DISPLACE` | VERIFIED | COMPOSER-QUOTA | 1 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-RULE-AREAS` | VERIFIED | QUOTA-AUDIT | 6 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-EX-FREQ-CHECKS` | PENDING | EXPRESSION | 6 | нет | — | PENDING: проверка FREQUENT (выбор режима, конкуренция с Core, вытеснение квотами, влияние на результат) не дала положительного исхода — живой результат 1/8. |
| `REQ-ADD3-EX-FREQ-WHY` | PENDING | EXPRESSION | 1 | нет | — | PENDING: объяснение, почему прежние реальные пробы не показали устойчивых различий, не оформлено отдельным артефактом. |
| `REQ-ADD3-Q-ACC-REPLACE` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-ACC-REMOVE` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-ACC-NOCONFLICT` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-Q-ACC-PERSIST` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-ACC-PROTECTED` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-ACC-NO-SEMANTIC` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-ACC-SCOPE` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-ACC-ENTRYPOINTS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-LEGACY` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-BUILDERS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-AUX` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-FOUND` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-A-REMOVED` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-NO-HIDDEN` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-NO-RENAMED` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-CQ-ACC-NO-DISPLACE` | VERIFIED | COMPOSER-QUOTA | 1 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-ACC-KEEP-FUNCTIONAL` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-KEEP-FALLBACK` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-KEEP-TECH` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-KEEP-MODULE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-KEEP-CHAT` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ACC-NO-RESTORE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-01` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-02` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-03` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-04` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-05` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-06` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-07` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-08` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-09` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-10` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-11` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-12` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-13` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-14` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-15` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-16` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-EX-ACC-DIFF` | PENDING | EXPRESSION | 1 | нет | — | PENDING: OFF/OCCASIONAL/FREQUENT фактически не различаются устойчиво. |
| `REQ-ADD3-EX-ACC-EFFECT` | PENDING | EXPRESSION | 1 | нет | — | PENDING: заметного влияния FREQUENT на собственную речь нет (1/8). |
| `REQ-ADD3-EX-ACC-NO-INSERT` | PENDING | EXPRESSION | 1 | нет | — | PENDING: отсутствие механической вставки не подтверждено живым артефактом на текущем кандидате. |
| `REQ-ADD3-EX-ACC-POSTPROC` | PENDING | EXPRESSION | 1 | нет | — | PENDING: не проверено, что постобработка не подавляет результат FREQUENT. |
| `REQ-ADD3-EX-ACC-CORE` | PENDING | EXPRESSION | 1 | нет | — | PENDING: технически Core сохранён (Core rev 8, FACTORY_SET 47f0d1eb8de4 неизменен — binding-258125), но строка закрывается в составе приёмки Expression после исправления FREQUENT; отдельного артефакта приёмки нет. |
| `REQ-ADD3-EX-ACC-PROBES` | PENDING | EXPRESSION | 1 | нет | — | PENDING: офлайн-LLM-пробы OFF/OCCASIONAL/FREQUENT на действующем провайдере не дали устойчивого различия; нужен новый прогон. |
| `REQ-ADD3-ACC-REVIEW-REJECT` | VERIFIED | ACCEPT | 10 | нет | `evidence/review-quota-quotes.md`, `evidence/binding-258125.md`, `arch-quota-audit.md` |  |
| `REQ-ADD3-ACC-REPORT` | VERIFIED | ACCEPT | 11 | да/postdeploy | `arch-quota-audit.md`, `evidence/canary/report.md`, `evidence/binding-258125.md` (+1) |  |
| `REQ-ADD3-ACC-CONSTRAINTS` | VERIFIED | ACCEPT | 7 | нет | `evidence/quota-removal.md`, `evidence/binding-258125.md` |  |
| `REQ-ADD3-QTA-SCOPE-WHOLE-PROJECT` | VERIFIED | QUOTA-AUDIT | 5 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-NEW-BUDGET-SYSTEM` | VERIFIED | QUOTA-AUDIT | 3 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-EX-NO-LIVE-CHAT` | VERIFIED | EXPRESSION | 3 | нет | `evidence/expression-r3.md` |  |
| `REQ-ADD3-ACC-NO-DONE` | VERIFIED | ACCEPT | 1 | нет | `evidence/binding-258125.md`, `evidence/canary/report.md` |  |
| `REQ-PR-SAVED-NOT-ACTIVE` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-EX-FREQUENT-PROBLEM` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-LEAD-NO-GUESS-CAUSE` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-GOV-REUSE-EXISTING` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-GOV-FIX-AT-FAULT` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-PR-WITHHELD-FULL-LIST` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-PR-NO-GLOBAL-OFF` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-PR-NO-FAKE-META` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `REQ-PR-UI-SURFACE` | VERIFIED | PROMPTS | 1 | да/preprod | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-UI-NO-LIE` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-PR-PERSIST` | VERIFIED | PROMPTS | 1 | да/postdeploy | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-FC-FORENSIC-RUN` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-FORENSIC-CHAIN` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-FORENSIC-CACHE-FLAGS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-VISION` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-EXTRACT-PAYLOAD` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-SEARCH-LIMITS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-SEARCH-LEXICAL` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-SEARCH-CHAIN-DIAG` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-PROVIDERS-ERRORS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-NO-ABSENCE-BIAS` | VERIFIED | FORENSIC | 1 | нет | `evidence/forensic.md` |  |
| `REQ-FC-SEMANTIC-QUERY` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-QUERY-ENTITIES` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-SEARCH-FIX-EXISTING` | VERIFIED | FACTCHECK | 2 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RELEVANCE-OUTCOME` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-CLAIM-SPLIT` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-TG-CASE-EXPECT` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-PARTIAL-INDEPENDENT` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-NO-TG-HARDCODE` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-FAIL-INSUFFICIENT` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-FAIL-SEARCH` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-FAIL-PROCESS` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-FAIL-PARTIAL` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-NO-FAKE-VERDICT` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-NO-UNSUPPORTED-POSITIVE` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-RENDER-NO-MASK` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-FC-VERBALIZER-NO-SPIN` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `REQ-CK-PARTIAL-SEAM` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-FIX-SEAM` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-SP-CORE-SINGLE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-SP-EXPRESSION-SINGLE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-SP-STYLE-SINGLE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CK-PROMPT-SCOPE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-NO-ALT-PERSONA` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-KEEP-CHARACTER` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-NO-LOWERCASE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CK-CAPITALIZATION` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-PROTECT-DATA` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CORE-APPROACH` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-PRINCIPLES-NOT-COPY` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-ENRICH` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CORE-Q-CONVERSATIONAL` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-Q-IMAGERY` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-Q-ABSURD` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-Q-SARCASM` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-Q-RUDENESS` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-Q-ASYMMETRY` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-Q-CONTEXT` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-Q-CONCRETE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-NO-REPLACE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-CORE-LIST-IS-ADDITIONS` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-KEEP-AUTHOR` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-NO-NEW-IDENTITY` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-ONE-FOR-ALL` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-ROUTE-CONTRACT` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-NO-FABRICATION` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-CORE-NO-GENRE-COPIES` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-EX-DIAG-CHAIN` | READY_FOR_LIVE | EXPRESSION | 1 | да/postdeploy | `evidence/expression.md` | READY_FOR_LIVE (postdeploy): нужен срез цепочки effective config → LLM payload → raw → postprocessed → outbound по каждому звену на живом пути. |
| `REQ-EX-FREQUENT-SEMANTICS` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-STABLE-EFFECT` | FAILED | EXPRESSION | 1 | да/postdeploy | `evidence/expression.md`, `evidence/canary/report.md`, `evidence/expression-r3.md` | FAILED: влияние режима нестабильно (срабатывание ~раз в десятки реплик). Нужна серия проб с устойчивым результатом. |
| `REQ-EX-PROBE-REAL` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-PROBE-MATRIX` | READY_FOR_LIVE | EXPRESSION | 2 | да/postdeploy | `evidence/expression.md` | READY_FOR_LIVE (postdeploy): нужна матрица прогонов по разным ситуациям и режимам Expression; сейчас различий нет. |
| `REQ-EX-PROVE-REAL-PATH` | FAILED | EXPRESSION | 1 | да/postdeploy | `evidence/expression.md`, `evidence/canary/report.md`, `evidence/expression-r3.md` | FAILED: закрытие доказано только на тестах сборки промптов, не на реальном модельном пути. |
| `REQ-EX-MODEL-LIMIT-HONEST` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-EX-NO-LIVE-CHAT` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `REQ-CK-CLASS-FAULT` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-CLASS-FALLBACK` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-CLASS-WARNING` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-CLASS-HYPOTHESIS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-401-LOCAL` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-NO-GUESS-AS-FACT` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-CK-SARCASM-OK` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-OPS-VISION-DIAG` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-OPS-SEPARATE` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-OPS-QUEUE` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `REQ-OPS-NO-REBUILD` | VERIFIED | OPS | 1 | нет | `evidence/forensic.md` |  |
| `FC-01` | VERIFIED | FACTCHECK | 1 | да/postdeploy | `evidence/factcheck.md`, `evidence/canary/report.md` |  |
| `FC-02` | VERIFIED | FACTCHECK | 1 | да/postdeploy | `evidence/factcheck.md`, `evidence/canary/report.md` |  |
| `FC-03` | VERIFIED | FACTCHECK | 1 | да/postdeploy | `evidence/factcheck.md`, `evidence/canary/report.md` |  |
| `FC-04` | VERIFIED | FACTCHECK | 1 | да/postdeploy | `evidence/factcheck.md`, `evidence/canary/report.md` |  |
| `FC-05` | READY_FOR_LIVE | FACTCHECK | 1 | да/postdeploy | `evidence/factcheck.md` | READY_FOR_LIVE (postdeploy): нужен живой сценарий истечения бюджета поиска (техническое ограничение, не «нет доказательств»). |
| `FC-06` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `FC-07` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `FC-08` | READY_FOR_LIVE | FACTCHECK | 1 | да/postdeploy | `evidence/factcheck.md` | READY_FOR_LIVE (postdeploy): нужен живой сценарий «тезис и в подписи, и на изображении». |
| `FC-09` | VERIFIED | FACTCHECK | 1 | нет | `evidence/factcheck.md` |  |
| `PR-01` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `PR-02` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md` |  |
| `PR-03` | VERIFIED | PROMPTS | 1 | да/postdeploy | `evidence/prompts-core.md`, `evidence/withheld-postdeploy.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `SP-01` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `SP-02` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `SP-03` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `evidence/canary/report.md` |  |
| `SP-04` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `SP-05` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `evidence/canary/report.md` |  |
| `SP-06` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `EX-01` | FAILED | EXPRESSION | 1 | да/postdeploy | `evidence/expression.md`, `evidence/canary/report.md`, `evidence/expression-v2.md` (+1) | FAILED: живой канареечный замер 2.58.122 — 1 совпадение из 8 ответов; кандидатский v2 (3/6 и 1/4) не задеплоен. Нужен новый живой замер после исправления. |
| `EX-02` | FAILED | EXPRESSION | 1 | да/preprod | `evidence/expression.md`, `evidence/canary/report.md`, `evidence/expression-r3.md` | FAILED: различия видны в промпте, но не в результатах реальных LLM-проб (1/8). Нужен новый замер после исправления. |
| `EX-03` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression.md` |  |
| `OPS-01` | VERIFIED | OPS | 1 | да/preprod | `evidence/forensic.md` |  |
| `OPS-02` | VERIFIED | OPS | 1 | да/preprod | `evidence/forensic.md` |  |
| `REQ-ORDER-PARALLEL` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-ORDER-FC-NOT-BLOCKED` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-DONE-REVIEWER-REAL` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-REPORT-DATETIME` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-DONE-MAIN-CRITERION` | PENDING | ACCEPT | 1 | да/postdeploy | `evidence/review-factcheck-r2.md`, `evidence/binding-258125.md` | PENDING: главный критерий не выполнен — FREQUENT фактически не соответствует настройке владельца. Закрывается только после исправления Expression и нового живого замера. |
| `REQ-SCOPE-CORRECTION-NOT-EPIC` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-SCOPE-QUEUE` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-MAP-DEVOPS-PERSONA` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-MAP-LOG-TASK` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-MAP-DROP-LOWERCASE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-MAP-STYLE-PUNCT` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-MAP-DASH-SINGLE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-MAP-PLAIN-GENRE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-MAP-SOLID-TEXT` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-MAP-SUT-IN-CHECKUP` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-MAP-STYLE-BLOCKS-SINGLE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-MAP-MAX-SYMBOLS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-MAP-FALLBACK-NOTICE` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-RUNTIME-SOURCE-FIRST` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-CHECKUP-STORAGE-POINTS` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-PROVENANCE-CLASS-FIRST` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-KEEP-FROZEN-ORIGINAL` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-SUT-NO-GENERIC-REPLACEMENT` | VERIFIED | CHECKUP | 1 | нет | `evidence/checkup-core.md` |  |
| `REQ-A4-CORE-STORAGE-POINTS` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-CORE-NO-DUP-PARAGRAPHS` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-CORE-INSERT-POINT` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-CORE-INSERT-TEXT` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-CORE-COMPACT-ADD` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-CORE-NO-TECH-GENRE` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-EXPR-SINGLE-PATH` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-STYLE-NO-SECOND-DASH` | VERIFIED | CORE | 1 | нет | `evidence/core-patch-wire.md` |  |
| `REQ-A4-PR-NO-MASS-ACTIVATION` | VERIFIED | PROMPTS | 1 | нет | `evidence/prompts-core.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-A4-REVIEW-COMPOSITION` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-SUT-VERBATIM` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-STATE-MATRIX` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-CAPITALIZATION` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-OTHER-ROUTES` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-FREQUENT-PROBES` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-STYLE-OUTPUT` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-PROVENANCE-MATCH` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REVIEW-NO-OVERENGINEERING` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REPORT-MATRIX` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-REPORT-AFTER` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-DONE-BLOCKERS` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-A4-SYNC-NO-NEW-MAP` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-factcheck-r2.md` |  |
| `REQ-CORE-FREESPEECH` | VERIFIED | CORE | 1 | да/postdeploy | `evidence/core-patch-wire.md`, `evidence/withheld-postdeploy.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-PROD-BASIS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-MAIN-PRINCIPLE` | VERIFIED | QUOTA-AUDIT | 2 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-Q-NO-SEMANTIC` | VERIFIED | QUOTES | 2 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-STYLE-POLICY` | VERIFIED | QUOTES | 2 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-CONTENT` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-MUTEX` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-Q-PROTECTED` | VERIFIED | QUOTES | 1 | нет | `plans/features/_audit-2026-10-23/release-258124/deploy.md`, `evidence/binding-258125.md` |  |
| `REQ-ADD3-Q-NO-LLM` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-UI-FACTORY` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-Q-NO_QUOTES` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-Q-SCOPE` | VERIFIED | QUOTES | 1 | нет | `evidence/quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-REMOVE-ADDITIVE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-DEFINITION` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-LOCATION` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-DECISION-CONDITION` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-REPLACEMENT` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-SHORTCUT` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REPO-WIDE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-LIST-OPEN` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-COVERAGE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-INTERMEDIATE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-METHOD-NAMES` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-PROVENANCE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-RUNTIME` | VERIFIED | QUOTA-AUDIT | 2 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-OWN-CHAINS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-COMPARE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-APPLICABILITY` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-NAME-PROOF` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-CLASSIFY-EACH` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-QTA-CLASS-A` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-CLASS-B` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-CLASS-C` | VERIFIED | QUOTA-AUDIT | 2 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-QTA-C-PRESERVE` | VERIFIED | QUOTA-AUDIT | 2 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-QTA-NO-NAME-CLASS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-FIX-QUOTA-IN-FALLBACK` | VERIFIED | QUOTA-AUDIT | 2 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-MIXED` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-MASS-DELETE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-CQ-SYMPTOM` | VERIFIED | COMPOSER-QUOTA | 2 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-CQ-REMOVE-ADDITIVE` | VERIFIED | COMPOSER-QUOTA | 1 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-CQ-KEEP-PAYLOAD` | VERIFIED | COMPOSER-QUOTA | 1 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-CQ-NO-MANUAL` | VERIFIED | COMPOSER-QUOTA | 1 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md`, `evidence/quota-quotes-fix.md` |  |
| `REQ-ADD3-CQ-NOT-FINAL` | VERIFIED | COMPOSER-QUOTA | 1 | нет | `evidence/quota-removal.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-LEGACY-FOCUS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-FACTCHECK` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-CHECKUP` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-SUMMARY` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-MEMORY-GRAPHRAG` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-INITIATIVE-OBSERVER` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-SLEEP` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-CORE-FORMATION` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-ALL-OTHERS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-WRAPPER` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-LEGACY-IMPORTANT` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-KEEP-MODULE-SETTINGS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-MIGRATE-REMOVED` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-RESTART` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-INSPECTOR-TRUTH` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md`, `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-QTA-INSPECTOR-SCOPE` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-EXISTING-TOOLS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-NEW-DIAG` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-SECRETS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-AGENTS-RULE` | VERIFIED | QUOTA-AUDIT | 2 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-RULE-EXCEPTIONS` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REVIEWER-REJECT` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-NO-NEW-CONTROL` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-EX-INSPECTOR-PRESENT` | PENDING | EXPRESSION | 2 | нет | — | PENDING: нужен явный артефакт сборки с блоком <Expression_Settings> на текущем кандидате (наличие в Inspector не снято как доказательство). |
| `REQ-ADD3-EX-FULL-PATH` | PENDING | EXPRESSION | 2 | нет | — | PENDING: полный путь global/chat setting → effective → LLM payload → raw → Style Policy → Telegram не снят целиком на текущем кандидате. |
| `REQ-ADD3-EX-NO-MECHANICAL` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression-r3.md` |  |
| `REQ-ADD3-EX-FREQ-SEMANTICS` | PENDING | EXPRESSION | 1 | нет | — | PENDING: семантика FREQUENT (привычная заметная нецензурная лексика в собственной речи) фактически не реализована. |
| `REQ-ADD3-EX-KEEP-CORE` | VERIFIED | EXPRESSION | 1 | нет | `plans/features/_audit-2026-10-23/release-258124/deploy.md` |  |
| `REQ-ADD3-EX-REAL-PROBES` | PENDING | EXPRESSION | 1 | нет | — | PENDING: реальные офлайн-пробы на действующем провайдере в требуемом объёме не выполнены/неубедительны. |
| `REQ-ADD3-EX-COMPARE-ARTIFACTS` | PENDING | EXPRESSION | 1 | нет | — | PENDING: нет артефакта сравнения payload / сырых ответов модели / постобработки. |
| `REQ-ADD3-EX-HONEST-LIMIT` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression-r3.md` |  |
| `REQ-ADD3-EX-NO-DONE` | VERIFIED | EXPRESSION | 1 | нет | `evidence/expression-r3.md` |  |
| `REQ-ADD3-QTA-ACC-COMPOSER-NOT-ENOUGH` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-METHOD` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-QTA-REG-ISOLATED` | VERIFIED | QUOTA-AUDIT | 1 | нет | `arch-quota-audit.md`, `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-ACC-REVIEW-CHECKS` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-quota-quotes.md` |  |
| `REQ-ADD3-ACC-REVIEW-CLASS-A-PROOF` | VERIFIED | ACCEPT | 1 | нет | `arch-quota-audit.md`, `evidence/quota-removal.md` |  |
| `REQ-ADD3-ACC-REVIEW-NO-REFACTOR` | VERIFIED | ACCEPT | 1 | нет | `evidence/quota-removal.md`, `evidence/binding-258125.md` |  |
| `REQ-ADD3-ACC-REPORT-COVERAGE` | VERIFIED | ACCEPT | 1 | нет | `arch-quota-audit.md` |  |
| `REQ-ADD3-ACC-REPORT-NO-FULL-CLAIM` | VERIFIED | ACCEPT | 1 | нет | `arch-quota-audit.md` |  |
| `REQ-ADD3-ACC-WORKFLOW` | VERIFIED | ACCEPT | 1 | нет | `evidence/review-quota-quotes.md`, `evidence/review-factcheck-r2.md`, `plans/features/_audit-2026-10-23/release-258125/README.md` |  |

## 7. Вердикт

**P0 не принят.** 554 из 584 required-строк VERIFIED; остаток: 4 FAILED, 5 READY_FOR_LIVE (postdeploy), 21 PENDING. Препятствие одно и то же по смыслу: FREQUENT фактически не влияет на речь (1 совпадение из 8 живых ответов), поэтому главный критерий и EX-кластер не закрываются отчётом или ревью — нужен код-фикс Expression и новый живой замер.
