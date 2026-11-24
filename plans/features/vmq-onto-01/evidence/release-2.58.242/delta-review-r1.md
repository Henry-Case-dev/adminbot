# Релиз 2.58.242 — независимое delta-ревью (QRNG IBM P5A+P5B)

- **Роль:** Reviewer (independent). **Дата:** 2026-11-25.
- **Режим:** read-only product/tests; без deploy/SSH/реального QPU; без LLM.
  Единственный записанный файл — этот артефакт (не закоммичен).
- **Кандидат:** branch `release/qrng-ibm-p5b-2.58.242`, tip/origin
  `ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e`; fast-forward от base.
- **Production base / rollback:** `3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c`
  (2.58.241), tree `853dd3b471034fb297753604d98367ed208dbf6f`.
- **Product tip:** `dfa5118fd294c565e906ff6b78c75bf83427b4fc` (2.58.242), tree
  `703e0651802b80a5d9da0929d8b6be6d0a830a8e`; content tip `10b34b03c…`, tree
  `01ce2726357e06bce91dfe2ee89abb7c7bb49396`.
- **Review basis:** P5A r8 `review-p5a-r8.md` sha256
  `cf0dbe2b7b45f6f4415ed2d391ea18e415bcfa4340bda610a1bf5cabdcde5fa`;
  P5B r3 `p5b-review-r1.md` sha256
  `a37b5a94122c9b88f5a355c66eae4d2c67fc4b1caa70a6683b42a8af6a3fe79b`
  (кандидат `8ac5b927a`); `assembly.md`, `deploy-checklist-2.58.242.md`.
- **Строки:** `QAN-REC-IBM-01/02/03` — **REVIEW** (`live_required=true`,
  `live_when=postdeploy`). Hardware VERIFIED не заявляется.

## JSON verdict

```json
{
  "verdict": "APPROVED_FOR_DEPLOY",
  "candidate": {
    "branch": "release/qrng-ibm-p5b-2.58.242",
    "tip": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
    "origin_matches": true,
    "deploy_sha": "ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e",
    "product_tree_sha": "dfa5118fd294c565e906ff6b78c75bf83427b4fc",
    "base": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
    "version": "2.58.242"
  },
  "lineage": {
    "commits": 35, "merges": 0, "replayed_non_merge": 33,
    "source_range": "26aadf208..8ac5b927a (34 commits, 1 merge)",
    "merge_dropped": "fa9e8b3f6 (redundant: 26aadf208 is ancestor of base)",
    "patch_id_identical_commits": 32,
    "patch_id_differing_commit": "03bdf9ad6->efbc276c7 (only F8 meta HEAD line + PARAM_CATALOG pin; all other changed lines identical in 71/71 files)",
    "content_equivalent_to_reviewed_candidate": true
  },
  "pins": {
    "PARAM_CATALOG_SHA256_FOLLOWUP": {"pin": "c7cb2bdb…0fb6ae", "actual": "match", "status": "correct"},
    "ROUTES_SHA256_F11": {"pin": "9413f303…a4bfb8", "actual": "match", "status": "correct"},
    "PG_DB_SHA256_B07": {"pin": "469775c2…7dc9dcd", "actual": "match", "status": "correct"},
    "counters": "REGISTRY 659 / GROUPS 121 / TAB_BY_GROUP 119 / TAB_RULES 23 / delta 258",
    "catalog_check": "CHECK OK: реестр 659 == REGISTRY",
    "stale_catalog_risk": false
  },
  "bump": {"files": 32, "insertions": 35, "deletions": 35,
           "version_only": true, "eol_bom_churn": false},
  "content_delta": {"files": 90, "insertions": 8626, "deletions": 259,
                    "file_set_equals_source_delta": true},
  "bump_delta": {"files": 100, "insertions": 8661, "deletions": 294},
  "tests": {
    "p5_adapter": "77 passed",
    "p5b_admin": "14 passed",
    "combined_regression_set": "412 passed (411 + F8 subprocess guard, run together)",
    "js_suites": "6/6 OK",
    "version_pin_guard": "20 passed, 1 failed (pre-existing README v2.57.0)",
    "py_compile": "rc 0",
    "git_diff_check": "rc 0",
    "preexisting_failures_reproduced_on_base": "3 failed (2 graphrag + README), files unchanged"
  },
  "independent_probes": [
    {"id": "PR-A", "what": "IBM unavailable -> ANU fallback, no PRNG",
     "result": "PASS: ibm attempt provider_unavailable, ANU batch deposited, mode quantum, draws quantum, sampler.calls=1, second forced refill did not submit again"},
    {"id": "PR-B", "what": "reserve floor respected",
     "result": "PASS: no refill above/at low_watermark; exactly one refill after reserve dropped below floor"},
    {"id": "PR-C", "what": "transient live result error, no double-paid job",
     "result": "PASS: row interrupted with job evidence, slot held, recovery deposits exactly one batch, sampler.calls=1, second recovery no duplicate"},
    {"id": "PR-D", "what": "admin credential revoke/clear",
     "result": "PASS: save 200 masked {configured,last4}; clear key 200 {configured:false,last4:null}; whitespace resets instance; no raw key/CRN echoed"}
  ],
  "mutations": [
    {"id": "M1", "mutation": "reserve floor guard removed in _maybe_schedule_refill",
     "expected": "test_refill_trigger_respects_watermark FAILS",
     "observed": "FAILED (1 failed)", "restored": "1 passed, blob identical"},
    {"id": "M2", "mutation": "CRN redaction removed in _clean_error_text",
     "expected": "test_crn_not_echoed_in_error_reason FAILS",
     "observed": "FAILED (1 failed)", "restored": "1 passed, blob identical"}
  ],
  "tree_after_mutations": "blob 62f28bfcc66272313be689a797ec85bec98a8620 == HEAD; git status empty",
  "rows": {"QAN-REC-IBM-01": "REVIEW", "QAN-REC-IBM-02": "REVIEW",
           "QAN-REC-IBM-03": "REVIEW"},
  "hardware_verified_claim": false,
  "blocking_findings": [],
  "nonblocking_findings": ["DR-242-N01", "DR-242-N02", "DR-242-N03", "DR-242-N04"],
  "carried_backlog": ["P5B-R1-04", "P5B-R1-06", "P5A-R8-N01", "P5A-R7-N01",
                      "P5A-R4-N01", "P5B-R3-01", "README v2.57.0 pin",
                      "SIMPL-R1-F2"],
  "deploy_condition": "Deploy ff226ca0a onto 3f42cfdd1 (code-only) with the postdeploy gate in section 6; rows stay REVIEW; no hardware VERIFIED claim.",
  "rollback": {"to": "3f42cfdd1f7ed26393ba7b793e86efe7b6f73a4c",
               "code_only": true, "ddl": 0, "migrations": 0, "flags": 0}
}
```

## 1. Линия и эквивалентность reviewed-кандидату

Проверено на фактических объектах Git, не по сообщениям коммитов.

| Проверка | Результат |
|---|---|
| Коммиты `3f42cfdd1..ff226ca0a` | **35**, merge **0**, first-parent **35** |
| Источник `26aadf208..8ac5b927a` | 34 коммита, 1 merge (`fa9e8b3f6`) |
| Replay | **33** non-merge, линейно |
| `git merge-base --is-ancestor 26aadf208 3f42cfdd1` | **0 (ancestor)** — UI-06/07 уже в базе |
| Patch-id 33 replayed vs 33 source | **32/33 идентичны** |
| Отличие одного коммита | `03bdf9ad6`→`efbc276c7`: только строка `HEAD (short)` в F8 meta и `PARAM_CATALOG_SHA256_FOLLOWUP`; в остальных **71/71** файлах наборы добавленных/удалённых строк совпадают |
| `services/mca_random_source.py`, `web/api/routes.py`, оба P5-теста: diff релиза vs исходной дельты | **blob-идентичны** |
| `web/app.js`: добавленные/удалённые строки | **407/407 и 37/37 — совпадают** |
| `web/index.html`: добавленные/удалённые строки | **117/117 и 17/17 — совпадают** |
| `diff(8ac5b927a..10b34b03c)` vs `diff(26aadf208..3f42cfdd1)` | Совпадают на **109/111** файлах; отличаются только 2 pin-файла (раздел 2) |
| Набор файлов | **90/90 идентичен** исходной дельте |
| Объём | исходная **+8627/−260**, релиз **+8626/−259** (разница ровно 1 строка = снятая строка HEAD в F8 meta) |
| Запрещённые пути | `migrations/`, `services/database.py`, `services/pg_db.py`, `services/mca_gates.py` — **не менялись**, DDL 0 |

Снятый merge не потерял содержимого: `26aadf208` — предок базы; все 7 путей
merge-диффа присутствуют, UI-06/07 JS-тесты в базе не менялись и проходят на
tip (`QRNG-UI06-OK`, `QRNG-UI07-OK`). `randomProviderSummary` и guard'ы
`p.lastSuccess && …` на месте.

## 2. Разрешённые pin-конфликты — корректны

Активные byte-freeze пины проверены против фактических байтов tip:

| Пин | Значение | Факт | Итог |
|---|---|---|---|
| `PARAM_CATALOG_SHA256_FOLLOWUP` | `c7cb2bdb…0fb6ae` | sha256(`services/param_catalog.py`) = `c7cb2bdb…0fb6ae` | **match** |
| `ROUTES_SHA256_F11` | `9413f303…a4bfb8` | sha256(`web/api/routes.py`) = `9413f303…a4bfb8` | **match** |
| `PG_DB_SHA256_B07` | `469775c2…7dc9dcd` | sha256(`services/pg_db.py`) = `469775c2…7dc9dcd` | **match** |

- В исходной ветке `PARAM_CATALOG`-пин был `2272c584…` и совпадал с её
  каталогом; после rebase каталог объединён с базовым, и пин
  пересчитан в `c7cb2bdb…` — **правильная реакция, а не подмена**.
- `ROUTES`-пин переутверждён осознанно в P5B-R2 (whitespace-нормализация
  key/CRN/instance) и совпадает с фактическим файлом.
- Счётчики F8: REGISTRY **659**, delta **258**, GROUPS 121,
  `_TAB_BY_GROUP` 119, TAB_RULES 23; `gen_param_registry --check` →
  `CHECK OK: реестр 659 == REGISTRY`; meta на bumped tip содержит
  `APP_VERSION 2.58.242`. **Устаревший каталог как «текущий» не помечен.**

## 3. Bump `10b34b03c → dfa5118fd` — только версия

- 32 файла, **+35/−35**, ровно как bump 2.58.241.
- 27 файлов байт-идентичны после замены `2.58.241`→`2.58.242`; 4 JS-файла —
  только escaped-regex `2\.58\.24X`; `config/settings.py` — строка
  `APP_VERSION` с release-комментарием (numstat 1/1).
- **0 файлов** с изменением CRLF/BOM; маркеров `\ No newline` нет;
  `git diff --check` rc 0; `--ignore-all-space` даёт те же 32/35/35.
- Остатки `2.58.241` на tip: исторический комментарий в `config/settings.py`
  и evidence предыдущего релиза 2.58.241 — ожидаемо.

## 4. Тесты на точном tip (`ff226ca0a`)

Product-дерево tip идентично `dfa5118fd` (evidence-коммит меняет только 3 docs).

| Команда | Результат |
|---|---|
| `pytest tests/test_qrng_p5_ibm_adapter.py -q` | **77 passed** |
| `pytest tests/test_qrng_p5b_ibm_admin.py -q` | **14 passed** |
| Комбинированный QRNG/F8/param/P1/P2/P3/f01/webapp_js/mca10a C/D/JS/mca10b D/mca19 E/asap5 набор | **412 passed** = 411 + F8 subprocess-guard (в отчёте он deselected и прогнан отдельно: `1 passed`) |
| 6 JS-наборов | `QRNG-P5B-OK`, `QRNG-UI07-OK`, `QRNG-UI06-OK`, `QRNG-P4-UI-OK`, `MCA10A-RANDOM-OK`, `MODULE-WORKSPACE-OK` |
| Version-pin guard (21 тест-кейс в 20 файлах, `-k app_version`) | **20 passed, 1 failed** — только pre-existing README (`v2.57.0`) |
| `py_compile` 6 затронутых/связанных файлов | rc 0 |
| `git diff --check` (worktree и range) | rc 0 |
| `gen_param_registry_round1025.py --check` | CHECK OK (659) |
| 3 pre-existing failures на базе `3f42cfdd1` | **воспроизведены**: 2 graphrag + README; их файлы в релизе не менялись |
| `SIMPL-R1-F2` | файл `tests/test_p0_embed_admission_msi.py` не менялся (backlog) |

## 5. Независимые пробы и мутации

Пробы запускались на фактическом tip с собственными fake-IBM/sampler и
временной SQLite вне репозитория; это проверка seam-поведения, **не live QPU**.

- **PR-A (IBM недоступен → fallback):** sampler бросает
  `RuntimeError("connection reset by peer")`; `refill_if_needed(force=True)` →
  IBM attempt `provider_unavailable`, партия зачислена через **ANU**; режим
  `quantum`, три draw вернули квантовые значения при `random.Random`→Boom
  (PRNG не вызван); повторный force-refill **не сделал второй submit**
  (`sampler.calls == 1`).
- **PR-B (floor):** low_watermark=2; при запасе 3 и 2 фон не запускается,
  после падения до 1 — **ровно один** refill; выше floor — ноль.
- **PR-C (transient live result error):** DONE + первый `result()` падает →
  строка `interrupted` с сохранённым job/cursor, слот удержан, батч не
  зачислен; recovery зачисляет **ровно один** батч, `sampler.calls == 1`,
  повторный recovery дубля не создаёт.
- **PR-D (отзыв credential):** save → маска `{configured:true,last4:"6789"}`;
  clear key → **200**, `{configured:false,last4:null}`; whitespace-only
  instance → `""`; raw key/CRN отсутствуют в ответах.

Мутации (обе **убиты**, дерево восстановлено):

| # | Мутация | Ожидание | Факт |
|---|---|---|---|
| M1 | снят floor-guard в `_maybe_schedule_refill` | `test_refill_trigger_respects_watermark` падает | **FAILED**, после restore **PASS** |
| M2 | снято маскирование CRN в `_clean_error_text` | `test_crn_not_echoed_in_error_reason` падает | **FAILED**, после restore **PASS** |

Финально: `git hash-object services/mca_random_source.py` =
`62f28bfcc66272313be689a797ec85bec98a8620` == blob HEAD; `git status` пуст.

## 6. Условия деплоя и проверки после него

**Что деплоить:** точный `ff226ca0ae187e8f41fa6cbb3de5317bdcce8f6e`
(tip ветки/origin; product-дерево идентично `dfa5118fd`). Base
`3f42cfdd1…`, fast-forward, без merge/rebase на хосте. `.deploy/release.json`
— на фактически выкаченный SHA, `previous_sha=3f42cfdd1…`.
**Rollback:** code-only `3f42cfdd1…`, DDL/миграций/флагов/данных нет.

После деплоя обязательно проверить (агенты, не владелец):

1. `/healthz` 200, версия `2.58.242`, identity `verified_deployed` = точный
   deployed SHA, schema **48**, DDL 0, настройки/ключи/промпты не сброшены.
2. **Секреты:** `GET /api/config` и `/api/status.random` отдают IBM key/CRN
   только `{configured,last4}`; raw key/CRN отсутствуют в DOM, network,
   логах, 422 и текстах ошибок; оба поля в UI — `type=password` с маской.
3. **Состояния IBM:** unconfigured → saved/unverified → stale при правке
   черновика → read-only «Проверить доступ»; «сохранён» не выдаётся за
   «проверен»; hardware smoke не запускается автоматически и требует confirm.
4. **Резерв/fallback:** `/api/status.random` — `provider_reserve`,
   `reserve_remaining`, `low_watermark`, `fallback_order`, `effective_provider`,
   `ibm_state`, `ibm_jobs`; `max_inflight=1`, дневные лимиты
   (`max_jobs_per_day=4`, `max_qpu_seconds_per_day=120`); фактические переходы
   IBM→ANU/LfDr; скрытого PRNG нет (`prng_active=false` при quantum).
5. **Effective config:** env-fallback `RANDOM_IBM_*` и bot_settings; отсутствие
   пакета `qiskit-ibm-runtime` даёт честный `dependency_missing`, IBM не
   показывается рабочим; установленный пакет — проверить import.
6. `journalctl` за окно деплоя: без новых ERROR/Traceback и без секретов;
   disk audit/cleanup по правилу проекта; backup keep=2; свободное место
   после `pip install` (пакет тянет numpy/scipy/ibm-platform-services).
7. **Hardware VERIFIED не заявлять.** `QAN-REC-IBM-01..03` остаются
   **REVIEW** до реального авторизованного QPU-вызова на deployed SHA
   (key+CRN вводит владелец; read-only check и ограниченный smoke с
   `confirm` — шаги агентов). Если smoke/HTTP завис на очереди — смотреть
   `task_jobs`/recovery и **не переотправлять** платный job вручную.

**Точные rollback-триггеры:**

- любой raw key/CRN в HTTP/DOM/log/422/status → немедленный rollback;
- пустая/неживая админка при save/clear/edit IBM-полей (класс P5B-R2-01);
- >1 платного submit на один логический job или дубль batch для одного
  job (проверка `sampler.calls`/`task_jobs`/`mca_random_batches`);
- устойчивая деградация QRNG (draw failed/deferred при сконфигурированных
  ANU/LfDr и включённом fallback), цикл restart или падение `/healthz`;
- schema/identity mismatch (schema ≠ 48 или неожиданный DDL);
- повторяющиеся новые ERROR/Traceback, затрагивающие QRNG или безопасность.

Отказ установки qiskit сам по себе — **не** rollback-триггер (честный
`dependency_missing`), но IBM нельзя выдавать за работающий.

## 7. Findings

- **DR-242-N01 — P3, evidence correction, не блокирует.**
  `assembly.md` §2: «Рост `mca_random_source.py` +3381 строк». Факт:
  3689→6994 строк = **+3305** (numstat **+3343/−38**); 3381 = сумма
  добавленных и удалённых строк. Только текст evidence.
- **DR-242-N02 — P3, BACKLOG_ONLY (семейство P5A-R1-N01).**
  F8 meta сохраняет HEAD-штамп `61d54788f`, а не коммит релиза/каталога;
  штамп не проверяется тестами (`test_app_version_recorded` смотрит только
  APP_VERSION) и не влияет на рантайм. Осознанно задокументировано в
  assembly; исправить при следующем reissue.
- **DR-242-N03 — P3, BACKLOG_ONLY.**
  `tests/fixtures/round1025/f8_baseline.json` `sha256` = `2272c584…`
  (каталог исходной ветки), тогда как отгружается `c7cb2bdb…`; поле **не
  используется** тестами (0 ссылок), активный guard — константа — корректен.
  Базовая фикстура тоже была исторической (`f840f68a…`), т.е. это не новый
  регресс; обновить при следующем F8 reissue.
- **DR-242-N04 — P2, BACKLOG_ONLY, live-watch (не дефект).**
  Неоднозначный сбой submit (сеть/обрыв после отправки) удерживает IBM-слот
  до `job_max_age` (default 3600 с): ANU-fallback продолжает работать, второй
  платный submit блокируется (проверено PR-A). На postdeploy отличать
  «слот занят» от «провайдер недоступен» и не переотправлять вручную.
- **Перенесённый backlog (не новые, не блокируют):** P5B-R1-04
  (region/instance помечены SECRET_VALUE → over-masking), P5B-R1-06
  (result-error маскирует CRN, но не key), P5A-R8-N01 (два write в
  settlement/quarantine), P5A-R7-N01 (young queued takeover), P5A-R4-N01
  (smoke не будит recovery), P5B-R3-01 (формулировка stale после save),
  README-пин `v2.57.0`, `SIMPL-R1-F2`.

## 8. Ограничения доказательств

- Нет deploy/SSH/prod-проверок: фактический base на хосте, effective config,
  restart-attach с реальными job и identity проверяет DevOps по checklist.
- Нет реального IBM: IAM/instance/QPU/queue/usage/RU, реальные measurement
  bits, `qiskit-ibm-runtime` в прод-venv и live fallback не проверялись;
  пробы — fake-клиент + локальная SQLite.
- **Визуальный гейт повторно не исполнялся на rebased-дереве.** Переиспользовано
  доказательство P5B r3 (Playwright + Browser Use на `8ac5b927a`): добавленные
  UI-строки релиза **идентичны** (407/407, 37/37, 117/117, 17/17), а изменения
  `web/app.js`/`web/index.html` базы — это уже выкаченный и отдельно принятый
  код 2.58.240/2.58.241. Это ограничение, а не доказательство нового рендера.
- UI-06/07 подтверждены функционально JS-наборами на tip, не новым браузерным
  прогоном.
- Артефакт не закоммичен; продуктовые файлы и тесты не редактировались.