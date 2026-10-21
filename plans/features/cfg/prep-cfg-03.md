# PREP-CFG-03 — реконсиляция слайса «Полный аудит работоспособности ВСЕХ параметров MiniApp»

**Лейн:** PM-CFG03-RECON (read-only; единственная запись — этот документ; карта, код, `current_task.md`, прод и чужой evidence не менялись; SSH не использовался). Заменяет бриф от 19.10.2026: тот писался **до** выполнения волны, этот — после билда, двух релизов и UNIFIED-CORE.
**Дата:** 21.10.2026, 16:51 (UTC+12) · HEAD master `e0c11306` · прод 2.58.104 (VERIFIED, workflow_state) · каталог **582 записи** (F8 `582==REGISTRY`).
**Вопрос лейна:** какие из 14 PENDING-строк CFG-03 уже фактически покрыты существующими VERIFIED-механизмами (REUSE), а какие требуют реальной работы (REAL_WORK).

---

## 1. Что изменилось со старого брифа (факты этого лейна)

1. **Волна билда выполнена и в master:** `df078406` «feat(cfg-03): full MiniApp param audit (579x chain, UI_missing=0) + honest descriptions for 5 dead handles; inventory tools/tests/evidence» — машинный инвентарь, 16 CONTRACT-тестов, e2e, evidence `cfg-03/**`. Независимое ревью **`review-cfg-03.md` = Approved** (спот 14 записей, бласт 3652 passed, атрибуция pre-existing подтверждена на чистом worktree).
2. **Live-половина закрыта ACCEPTANCE-95** (2.58.95 @ `113f3a62`): строки CFG-03.4/.6/.11/.12/R4 уже **VERIFIED** в карте — не трогать, не перепрогонять.
3. **Каталог вырос 579→582:** `46303ecd` (REL-25899) добавил `flags.factcheck_pipeline_v2`, `flags.factcheck_suitability_gate`, `flags.factcheck_wide_context` (килл-свитчи CFG-06 v2), переэмитировал F8/meta (`582==REGISTRY`). Аудит-тест `tests/test_cfg03_param_audit.py` **обновлен под 582 и зелёный на HEAD** (прогон лейна 21.10: **16 passed, 5.6 s**) — контракт аудита жив, включая `UI_missing=0`, consumer-покрытие, честные описания, type-family (2 задокументированных исключения) и пины.
4. **F8-машина на HEAD:** `plans/docs/param-registry-round1025.tsv` = 582 строк, meta.md (APP_VERSION 2.58.104, HEAD d860a529) — актуальна; экранная карта/места — под тестом `test_all_params_have_a_place` (зелёная в составе пинов).
5. **Устарело только evidence-снапшоты CFG-03:** `evidence/cfg-03/{inventory.tsv, inventory.json, audit-summary.json}` — снимок 19.10 на **579**; `owner-summary.md` оперирует 579 и не знает о +3 флагах. Проверено диффом ключей: ADDED = ровно 3 factcheck-флага, REMOVED = ∅.
6. **F2 (2 type-mismatch `image_freq_limit_cooldown_seconds`/`youtube_transcript_proxy_retries`) не исправлен** — `TYPE_FAMILY_EXCEPTIONS` всё ещё содержит оба ключа; статус backlog с готовым рецептом (review-cfg-03 §6) подтверждён.

---

## 2. Reuse-map: вердикты по 14 PENDING-строкам (биндинг-лейн исполняет, этот лейн карту не менял)

Общий пул доказательств для всех REUSE-строк: коммит `df078406` (билд в master) + `review-cfg-03.md` (Approved) + `evidence/cfg-03/**` + `tests/test_cfg03_param_audit.py` (16 passed на HEAD `e0c11306`) + алиасы P0/B06/SOUL-1 из notes карты (не перепрогонять) + `46303ecd` (провенанс 579→582) + route-coverage 18 CONTRACT (потребители +3 флагов, CFG-06).

| # | req_id | Вердикт | Обоснование / evidence |
|---|--------|---------|------------------------|
| 1 | **ADD-1.T3** (контейнер) | **REUSE** | «Расширение до ВСЕХ параметров, не повтор B06/SOUL» выполнено инвентарём (579, сейчас 582); B06-часть (B06.1–B06.3, Playwright 42/42) и SOUL-часть (§5 18/18 V) — owner-verified алиасы из note строки; биндинг к `df078406` + review-cfg-03 §Леджер. |
| 2 | **CFG-03.F** (сквозная инвентаризация) | **REUSE** | Инвентарь «настройка→потребитель» по всем записям + спот ревьюера; алиас P0A-PERSIST-TRUTH (VERIFIED); `UI_missing=0`. |
| 3 | **CFG-03.M** (цепочка на каждый параметр) | **REUSE** | 19-колоночный `inventory.tsv` покрывает все звенья цепочки (ui_place→registry→scope→API→storage→consumer→classification→test_refs); 456 строк с test_refs; неприменимые звенья — «—» (design в evidence README). |
| 4 | **CFG-03.1** (все параметры + UI_missing) | **REUSE** (подкрепить Wave A) | Инвентарь 579, UI_missing=0; на HEAD тест зелёный при 582 — +3 флага имеют места (synthetic/секции фактчека); снапшот обновит Wave A. |
| 5 | **CFG-03.2** (классификация, 13 классов) | **REUSE** (подкрепить Wave A) | Матрица применена: working 565 / runtime_not_consumed 14; отклонения — карточки F1–F5 в failures.md; +3 factcheck-флага классифицируются при переэмиссии (ожидаемо `working`, потребители — CFG-06 v2, route-coverage 18 CONTRACT). |
| 6 | **CFG-03.3** (read/write/reload, 409, rollback, наследование, factory reset) | **REUSE** | Класс-покрытие: P0 real-DB цикл 17/17 по типам настроек (прод 2.58.90) + read-after-write; 409/422 live (ACCEPTANCE-95 p5b: stale_updated_at→409); наследование/override/hot — CFG-01 live + `test_chat_params`; отмена/сеть/edges — P0 acceptance-edges-25890; рестарт/мультипроцесс — песочница (design, README §Design). |
| 7 | **CFG-03.5** (UI-описания = семантика) | **REUSE** | 5 нечестных описаний исправлены RED→GREEN; e2e описаний PASS (`ui_cfg03_descriptions_e2e`); type-family тест зелёный (2 исключения — задокументированный backlog F2, не «сохранилось-но-игнорируется»: `300.5` не теряется, `retries` мёртвая с честным описанием). |
| 8 | **CFG-03.7** (runtime-пути, env-потолки) | **REUSE** | Скан runtime-скоупа (bot/handlers/services/web+JS/SmartModule/filters/scripts); 13 env-only потолков в `audit-summary.json` (api-only, диагностируемы, без секретов); docker-compose-потребители — тест `test_docker_env_consumed_by_compose` (F4). |
| 9 | **CFG-03.8** (изоляция, безопасные фикстуры) | **REUSE** | Метод зафиксирован и соблюдён: in-memory PG, без боевых ключей/квот, live — только ACCEPTANCE-95-окна; бласт-атрибуция на чистом worktree (review §4). |
| 10 | **CFG-03.9** (устойчивые автотесты) | **REUSE** | `test_cfg03_param_audit.py` 16 CONTRACT — зелёный на HEAD (прогон лейна); f8-пара 582==REGISTRY; JS-sweep 88/0; e2e PASS; mock/live разделение честное (live-половины — отдельные VERIFIED-строки). Алиас P0V-TEST-MOCKS (принцип) не блокирует. |
| 11 | **CFG-03.10** (независимый Reviewer + регресс, без ложных 100%) | **REUSE** | `review-cfg-03.md` Approved с собственным спотом; регресс 3652 passed / 3 pre-existing задокументированы; 100% не объявляется: 14 `runtime_not_consumed` честны, F2 — backlog, R4/manual-checks отделяет непроверяемое. Финальную сверку делает биндинг-ревью. |
| 12 | **CFG-03.R1** (машинный coverage-манифест) | **REAL_WORK (малая)** | Механизм есть и жив (тест-пины на 582), но снапшоты в evidence — 579 от 19.10. Нужна переэмиссия на HEAD + классификация +3 флагов (см. §4 Wave A). |
| 13 | **CFG-03.R2** (сводка владельцу) | **REAL_WORK (малая)** | `owner-summary.md` оперирует 579 и не упоминает +3 factcheck-флага; обновить числа (582, working/no-consumer, «что осталось»: F2, media_base, live-остатки по manual-checks). |
| 14 | **CFG-03.R3** (реестр сбоев) | **REUSE** | `failures.md` полный формат P0A-PERSIST-AUDIT: F1 FIXED, F2 DEFERRED (backlog с рецептом), F3/F4 DOCUMENTED, F5 PRE-EXISTING. При переэмиссии новых девиаций не ожидается; если появятся — строка F6 (Wave A). |

**Итого:** **11 REUSE + 3 REAL_WORK**, причём все три REAL_WORK — одна малая evidence-работа без продуктового кода (переэмиссия снапшотов на 582 + сводка). Новых кодовых правок CFG-03 не требуется; F2 остаётся backlog'ом вне слайса.

---

## 3. Уже VERIFIED (5 строк — не трогать)

CFG-03.4 (hot-ручки, ACCEPTANCE-95 p2/p4b), CFG-03.6 (честность 5 мёртвых ручек live, p6b + ui-live-check95), CFG-03.11 (негативы 422/409 live, p5b), CFG-03.12 (OFF/ON по маршрутам, p2/p3b), CFG-03.R4 (manual-checks.md). Полный hot/restart-охват — build-evidence, повторный live-прогон не нужен (note строки .4).

---

## 4. Wave A — единственная реальная работа (рекомендация биндинг-лейну)

**Wave A «evidence-refresh 582»** — один писатель, только evidence, без кода:
- Write scope: `plans/features/cfg/evidence/cfg-03/**` (inventory.tsv, inventory.json, audit-summary.json, owner-summary.md, опционально failures.md F6) + опционально косметика docstring `tests/test_cfg03_param_audit.py` (в шапке остались «579 записей» при пинах 582 — не блокер, править в этом же лейне или не править вовсе).
- Шаги: `py -3 tools/cfg03_param_inventory.py` на HEAD → сверить: строки==582==REGISTRY, GROUPS 120, UI_missing=0, +3 factcheck-флага классифицированы `working` с потребителями (factcheck_service, FACTCHECK_*_ENABLED) и местами; `py -3 -m pytest tests/test_cfg03_param_audit.py tests/test_round1025_f8_registry.py -q` — зелёные; обновить `owner-summary.md` (числа 582; честный остаток: F2 backlog, media_base, live-остатки manual-checks); при новых девиациях — F6 в failures.md (не ожидается).
- Acceptance: переэмитированные артефакты в evidence-коммите, счётчики сходятся с F8, тест-пара зелёная, сводка называет 582.
- Оценка: ≤1 ч. Зависимости: нет. `CAN_PARALLEL_WITH`: биндинг 11 чистых REUSE-строк (разные write-scope: карта vs evidence) — но проще A→B последовательно, т.к. строки .1/.2/R1/R2 в карте должны сослаться на свежие артефакты.

**Wave B «биндинг»** (отдельный лейн, как и планировалось): связать все 14 строк в `requirements-map.json` candidate-bound evidence (REUSE → существующие артефакты + `df078406`/`46303ecd`/ACCEPTANCE-95; R1/R2/.1/.2 → артефакты Wave A), обновить в notes устаревшие «579»→582 и ссылки «prep-cfg-03 §2» (этот §2 — reuse-map), прогнать `requirements_gate.py check --stage review --slice CFG-03 --candidate <sha>`. Статусы PREP-документом не меняются.

**Статус волн (факт 21.10.2026, лейн CFG03-WAVE-B):**

- **Wave A выполнена** (`3022e6e8`): inventory.tsv/json, audit-summary.json, owner-summary.md, README — переэмиссия 579→582 @HEAD `e0c11306`; счётчики проверены биндинг-лейном по файлам: registry=582==REGISTRY (F8 OK), ui_missing=0, working 568 / runtime_not_consumed 14, no_consumer=7, dynamic=13, with_test_refs=459, inconsistencies=3 (F3 + 2×F2); фактчек-флаги — visible/working с потребителями (`factcheck_context.py`, `factcheck_suitability.py`, `factcheck_planner.py`+`factcheck_orchestrator.py`). Уточнение к брифу: «7 env-only» — реестровые env-only параметры; отдельно `env_only_ceilings` содержит 19 диагностических записей env/file/line из кода — оба числа честные, знаменатели разные.
- **Wave B выполнена (этот коммит):** 14 PENDING-строк → VERIFIED с candidate-bound evidence (Wave A-артефакты @`3022e6e8`; билд-волна @`df078406`/`46303ecd`; ревью @`f8bb638d`); 5 уже-VERIFIED live-строк (.4/.6/.11/.12/R4) не тронуты; диф карты — ровно 14 строк (проверено сравнением с HEAD~).
- **Гейты:** `--stage plan` → EXIT 0 (inventory=246 manual=42 errors=0). `--stage review --slice CFG-03 --candidate 3022e6e8` → exit 1, errors=15, **все — чужие остатки, не биндинга**: 1 × map-level `candidate_commit=d860a529` ≠ `--candidate` (конвенция dd6acf83/fff68d76, вне write-scope лейна) + 14 ошибок на 5 замороженных live-строках, чей evidence привязан к ACCEPTANCE-95 `113f3a62` (2.58.95) — гейт с одним кандидатом не видит их биндинг; перенавеска их артефактов на `3022e6e8` исказила бы провенанс и запрещена брифом. Мои 14 строк: 0 ошибок (strict-артефакты существуют, sha совпадают).
- **Тест-контракт на HEAD:** `py -3 -m pytest tests/test_cfg03_param_audit.py` → **16 passed** (прогон биндинг-лейна 21.10).

---

## 5. Риски и дубли

| ID | Риск/дубль | Митигация |
|---|---|---|
| R1 | Забиндить R1/R2 на устаревшие снапшоты 579 (истина уже 582) | Wave A обязателен ДО биндинга строк .1/.2/R1/R2; Reviewer сверяет счётчики с F8 |
| R2 | REUSE прочтён как «уже VERIFIED» | Строки PENDING до биндинга+гейта; вердикт — рекомендация, карту меняет только биндинг-лейн |
| R3 | Повторный прогон P0/B06/SOUL-1/ACCEPTANCE-95 | Алиасы в notes карты; не перепрогонять, только ссылаться |
| R4 | F2 «дочинить по пути» | Запрещено внутри CFG-03: тип-пины живут в тестах чужих слайсов (`test_cfg02b_image_freq_limits.py:266`, `test_hot_migration.py:225`); отдельный санкционированный мини-коммит (review-cfg-03 §6) |
| R5 | Расползание на новые аудиты (env-файлы, экраны вне реестра) | Знаменатель фиксирован: 582 REGISTRY; env-only вне реестра — уже классифицированы (13, F4); не расширять |
| R6 | Расхождение «582» в notes карты (M00005/M00016: «579 записей») | Биндинг-лейн обновляет формулировки notes при связывании |
| R7 | Косметический stale-docstring теста (579 в шапке) | Не блокер; правка опциональна в Wave A с минимальным диффом |

---

## 6. Guardrails

- Не менять `requirements-map.json`, `current_task.md`, код, чужой evidence — это лейн реконсиляции.
- Не объявлять CFG-03 завершённым: закрытие — после Wave A + Wave B + гейта `--stage review` (и релизного гейта, если появится новый кандидат), по фактам, без ложных 100% (03.10).
- Прод-дисциплина не затронута: этот лейн ничего не запускал на проде; единственный прогон — локальный pytest (16 passed, read-only).

*Источники лейна: карта (строки L00127–L00145, M00005/M00016/M00017), `review-cfg-03.md`, `evidence/cfg-03/**`, `df078406`, `46303ecd`, `tests/test_cfg03_param_audit.py` (прогон 21.10), `tests/test_round1025_f8_registry.py` (пины 582), `plans/docs/param-registry-round1025.{tsv,meta.md}`, workflow_state (2.58.104).*
