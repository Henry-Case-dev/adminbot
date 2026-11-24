# P5B — независимое ревью r1: IBM admin-поля, проверки, фоновый refill (QAN-REC-IBM-01…03)

- **Роль:** Reviewer (independent). **Дата:** 2026-11-24.
- **Кандидат:** `feat/qrng-ibm-p5b-2026-11-24` tip `968eec6c07f874b132490763746bc715140706e8`.
- **База нового объёма:** `fa9e8b3f6` (P5A `d47714761` + merge UI-06/07 `26aadf208`).
- **Worktree:** `…/WorkspaceData/worktrees/c742e4de9e92c489/qngen-p5b-2026-11-24-f09839761e22-e3506f8b`.
- **Контракт:** owner input `plans/owner_inputs/2026-11-24-embedding-vmq-ibm-qrng-ux.md` §4; строки `QAN-REC-IBM-01..03` в `plans/features/vmq-onto-01/requirements-map-qrng-recovery-2026-11-17.json` (все **REVIEW**, `live_required=true`, `live_when=postdeploy`); P5A-архитектура `arch-ibm-live-lease-2026-11-24.md`, `arch-ibm-state-machine-2026-11-24.md`; builder evidence `p5b-implementation-2026-11-24.md`.
- **Статус строк:** НЕ менялся — `QAN-REC-IBM-01/02/03` остаются **REVIEW**. VERIFIED не заявляется.

## 0. Вердикт (machine-readable)

```json
{
  "verdict": "NEEDS_FIXES",
  "candidate": "968eec6c07f874b132490763746bc715140706e8",
  "new_work_base": "fa9e8b3f6",
  "deployed_sha_checked": null,
  "rows": {
    "QAN-REC-IBM-01": "REVIEW",
    "QAN-REC-IBM-02": "REVIEW",
    "QAN-REC-IBM-03": "REVIEW"
  },
  "hardware_verified_claim": false,
  "blocking_findings": ["P5B-R1-01", "P5B-R1-02", "P5B-R1-03"],
  "backlog_findings": ["P5B-R1-04", "P5B-R1-06"],
  "evidence_corrections": ["P5B-R1-05"],
  "next": "repair clear/reset for IBM key+instance, invalidate stale IBM check/smoke on draft change, harden secret-assertions; re-review the delta"
}
```

**Коротко.** Инженерная часть P5B в основном соответствует §4 и строкам: адаптер P5A переиспользован без дублирования lease/settlement, второго планировщика нет, read-only проверка отделена от платного smoke, fallback на ANU/LfDR и floor запаса работают, скрытого PRNG нет, DDL/флагов/credentials/QPU нет. Но **новые admin-поля нельзя очистить**: «Удалить» на IBM API key (и сброс instance) возвращает 422, ключ остаётся настроенным; плюс после ввода нового ключа карточка продолжает показывать старый «доступ подтверждён». Это дефекты самого поставляемого P5B-контрола, поэтому кандидат не готов к release preparation до исправления.

## 1. Что проверено (Pillars)

1. **Код и вызывающие пути:** весь дифф `968eec6c` от `fa9e8b3f6` (`services/mca_random_source.py` +153/−20, `web/api/routes.py` +100/−5, `web/app.js` +343/−28, `web/index.html` +122/−14, тесты/evidence) прочитан построчно; сверены реальные маршруты, RBAC-гейты, DTO `/api/status.random`, существующие `TaskJobStore`/`TaskSupervisor` и вызовы `draw_index`/`draw_probability`.
2. **Тесты и ассерты:** прочитаны все новые/изменённые проверки; 408 комбинированный набор, 88 P5/P5B и 6 JS-наборов прогнаны самостоятельно; RED воспроизведён подменой продуктовых файлов на базу.
3. **Независимые контратаки:** 6 мутаций (2 пережили — это доказанные пробелы тестов), runtime-проба очистки ключа, живой рендер Playwright + Browser Use на реальном `web/index.html`/`web/app.js` с mock-DTO.

Дерево после каждой мутации/подмены восстановлено: `git status --porcelain` пуст, `git diff HEAD` пуст (проверено после каждой операции; финально — после RED-прогона).

## 2. Покрытие §4 и строк

### 2.1 QAN-REC-IBM-01 — рабочий адаптер, instance/region/plan, auto-QPU, provenance

**Вердикт: REVIEW (инженерно покрыто, live отсутствует).**

- Адаптер P5A сохранён и не переписан: `IbmQuantumRuntimeClient` (`services/mca_random_source.py:2039` `_validated`, `2140` `_check_success`, `2835` `_extract_bitstrings`). Диф P5B не добавляет второго адаптера/таблиц.
- Channel/instance/region/channel по умолчанию — `ibm_quantum_platform` / `open-instance` / `us-east` (`mca_random_source.py:199`, `IBM_CHANNEL`); plan не заявляется, читается из ответа (`_ibm_plan_from_instances`, результат `plan` в `_check_success`).
- Auto-QPU из реально доступных backend'ов: `_pick_from_infos` (P5A) + тест `tests/test_qrng_p5_ibm_adapter.py:319` (`test_check_access_is_read_only_and_selects_hardware`). Имя QPU не хардкодится.
- Противо-симуляторные гарантии: `tests/test_qrng_p5_ibm_adapter.py:812` (`simulator` backend → `validation_failed`), `:823` (`quasi_dists`/`counts`/`statevector` отвергаются), `:782-790` (provenance: `submitted_at`/`completed_at`, `is_simulator=false`, instance/channel).
- Отсутствие PRNG в тракте: `:799` (`test_no_prng_in_tract`) — убивает мою мутацию M5.
- Secured fields (часть строки): `PROVIDER_KEY_SETTINGS` +5 ключей (`mca_random_source.py:315-323`), запись только global admin (`web/api/routes.py:3277-3284`), маска `{configured,last4}` в `GET /api/config` (`tests/test_qrng_p5b_ibm_admin.py:285-307`).
- **Не проверено (live-only):** реальный IAM/instance/backends/QPU, `qiskit-ibm-runtime` в прод-venv, реальные measurement bits, provenance живого job. `qiskit_ibm_runtime` локально **не установлен** (`ModuleNotFoundError`), пин в `requirements.txt` не добавлялся — адаптер честно отдаёт `dependency_missing`.

### 2.2 QAN-REC-IBM-02 — read-only «Проверить доступ» отдельно от платного измерения; честные состояния

**Вердикт: REVIEW, с блокирующими дефектами admin-полей (P5B-R1-01, P5B-R1-02).**

- Разделение действий: `POST /api/random/test` с `provider=ibm_quantum` → `ibm_check_access` (без Sampler/job), `web/api/routes.py:5071-5097`; `POST /api/random/ibm/smoke` → `ibm_hardware_smoke`, требует `confirm`, shots 64…4096, `deposited=false` (`routes.py:214-222`, `5099-5119`). Тесты: `tests/test_qrng_p5b_ibm_admin.py:196-236` (read-only + нет эха), `:240-281` (confirm, RBAC, deposit false).
- Read-only реально не создаёт job: `tests/test_qrng_p5_ibm_adapter.py:319` (`sampler.calls == []`), `:568-583` (invalid instance/permission/quota → `sampler.calls == []`).
- Стадии ошибок: `_ibm_stage_for_code` (`mca_random_source.py:1445`) + новые `invalid_key_shape`/`invalid_crn_shape`; UI-подписи (`web/app.js:148-160`).
- Состояния `не настроен` / `сохранён, не проверен` / `проверка выполняется` / `доступ подтверждён` / `получение подтверждено` / `ошибка стадии`: JS-тест `tests/js/qrng_p5b_ibm_fields_test.js:101-143`; независимо подтверждено в живом рендере (см. §5).
- Сохранение полей не запускает probe/job: `saveRandomIbmSecrets` (`web/app.js:33068-33085`) только POST `/api/config`; открытие карточки пассивно.
- **Дефекты:** P5B-R1-01 (нельзя очистить key/instance → состояние «не настроен» недостижимо из UI), P5B-R1-02 (старый «доступ подтверждён» остаётся после ввода нового ключа).

### 2.3 QAN-REC-IBM-03 — durable QPU jobs, идемпотентность, лимиты, резерв, fallback

**Вердикт: REVIEW (инженерно покрыто, live отсутствует).**

- Задание ставится в существующий durable `task_jobs`: `_run_ibm_smoke` передаёт `TaskJobStore(self.db)` и `get_task_supervisor()` в `client.hardware_smoke` (`mca_random_source.py:5425-5437`); refill идёт тем же путём (P5A `_run_durable`). Второго планировщика/фоновой подсистемы нет: единственный refill-task — существующий `self._refill_task` (`:6949`), smoke-task — P5A `_ibm_smoke_task` (`:5367`).
- Защита от повторного платного job: `claim_slot`-гарды (`mca_random_source.py:2457-2469`), тесты `test_active_job_blocks_second_submit` (`:903`), `test_atomic_claim_two_fetches_one_sampler`, `test_concurrent_refill_and_smoke_one_sampler` (`:1392`); моя мутация M4 (снятие обоих гардов) убита.
- Восстановление после рестарта по job ID, без resubmit: `test_restart_recovery_polls_not_resubmits` (`:926`), `test_expired_row_recovers_late_done_result_once`, `test_result_timeout_keeps_slot_and_recovers_later` и др.
- Лимиты/квота: `max_inflight=1`, `max_jobs_per_day=4`, `max_qpu_seconds_per_day=120` (`mca_random_source.py:4206-4219`), smoke блокируется лимитами (`:5411-5422`; `test_smoke_daily_cap_blocks_paid_job` `:486`, `test_smoke_singleflight_and_cooldown` `:507`), fallback на ANU при дневном лимите (`TestStatusAndIsolation::test_ibm_daily_cap_falls_back_to_anu`).
- Фон/неблокирующий draw: `_maybe_schedule_refill` вызывается из `draw_index`/`draw_probability` (`:4716`, `:4756`), сам триггер синхронный и не ждёт QPU (`:6901-6919`); throttle 5 c (`:232`, `:6930-6937`); тесты `:722-758`, `:692-720`.
- Существующий запас/floor: триггер уважает `low_watermark` (`:6915-6918`; тест `:665`), ниже floor запускает существующий `refill_if_needed`; PRNG — только явный fallback-режим (прежняя семантика `resolve_selection` не менялась, добавлено лишь аддитивное `reserve_remaining`, `:4564-4596`).
- **Не проверено (live-only):** реальный queue/restart/attach на QPU, фактический расход RU, rotation на живом аккаунте.

## 3. Аудит секретов

| Проверка | Результат | Доказательство |
|---|---|---|
| key/CRN не возвращаются в GET `/api/config` (только маска) | OK | `tests/test_qrng_p5b_ibm_admin.py:285-307`; независимый прогон |
| Секреты не эхо-ятся в успешных ответах check/smoke | OK | `:208-236`, `:255-275` |
| Секреты не попадают в логи check-пути | OK (узко) | `:331-347` (`caplog`), fake client без текста исключения |
| Маскирование key/CRN в тексте ошибок реального клиента | Код корректен, **тест не различает** | `_clean_error_text` (`mca_random_source.py:699`), вызовы `:2083`, `:2248`, `:2349`, `:2713`, `:2908`, `:2957`, `:3017`, `:3054`, `:5377`; мутация M1 пережила тест `:615` |
| Отказная валидация 422 не эхо-ит значение | Код корректен, **теста нет** | `routes.py:3300-3333` (только `{shape}`); мутация M6 пережила все 11 P5B admin-тестов |
| Frontend не рендерит raw key/CRN | OK | `web/index.html:7591,7609` (secret-field, type=password), `web/app.js:33068-33087`; в рендере — только `••••••••AB12/WXYZ`; sentinel-строки в mock-DTO в DOM отсутствуют |
| Chat-scope не даёт писать provider-ключи | OK | `routes.py:1017-1025` (CATEGORY_KEYS/`not per_chat` → 422) |
| Секреты не в логах новых маршрутов | OK | в диффе нет `logger` с key/crn; ошибки формы содержат только код |

Вывод: **утечки в текущем коде не найдено**, но доказательная база частично ложноположительная (P5B-R1-03): тест CRN проходит и при отключённом маскировании, а отказная 422-ветка вообще не проверяется на отсутствие значения.

## 4. Мутации (независимые контратаки)

| # | Мутация | Ожидание | Результат |
|---|---|---|---|
| M1 | `_clean_error_text`: не маскировать CRN (`(key, crn)` → `(key, 0)`) | тест CRN-redaction падает | **SURVIVED** — `test_crn_not_echoed_in_error_reason` зелёный: `log_ring.sanitize` маскирует литерал `us-east`, поэтому полный CRN в строке не находится |
| M2 | Нет fallback после IBM (`break` после первой очереди) | fallback-тест падает | KILLED — `test_quota_failure_falls_back_to_anu` |
| M3 | Снят floor запаса в `_maybe_schedule_refill` | floor-тест падает | KILLED — `test_refill_trigger_respects_watermark` |
| M4 | Сняты оба claim-гарда (второй in-flight job) | тест дубля падает | KILLED — `test_active_job_blocks_second_submit` (первый вариант M4a, только service-level `job_in_progress`, пережил: второй слой — durable claim — законно блокирует дубль) |
| M5 | `random.Random` внутри `_extract_bitstrings` | PRNG-тест падает | KILLED — `test_no_prng_in_tract` |
| M6 | Эхо отклонённого значения в 422 (`shape` → `"too_short"+text`) | тест не должен видеть raw | **SURVIVED** — 11/11 P5B admin-тестов зелёные |

RED-проверка: продуктовые файлы на базе `fa9e8b3f6` → **11 failed, 77 passed** (в P5B-подмножестве — 4 в `TestP5BAdminHardening` + 7 в `test_qrng_p5b_ibm_admin.py`), JS падает на `c.randomIbmStateInfo is not a function`. Заявленные builder'ом «11 failed / 8 passed» по числу падений совпадают; «8 passed» относится к запускавшемуся подмножеству, а не ко всему P5-файлу (77 P5A-тестов на базе проходят). После восстановления — 88/88.

## 5. Визуальный гейт (обязателен: изменена карточка админки)

Гарнесс: реальные `web/index.html` + `web/app.js` кандидата, отдаваемые локальным static-сервером; `/api/*` — детерминированные mock-DTO (config из реального param_catalog, `/api/status.random` с записью `ibm_quantum`, `/api/random/test`, `/api/random/ibm/smoke`); Telegram SDK — заглушка; **не production и не живой IBM**. Секретов в mock нет (только `{configured,last4}` + sentinel-строки, которых не должно быть в DOM).

**Playwright (детерминированно, 6 прогонов):**

| Viewport | overflow | console/page errors | password inputs | raw secret в DOM | Состояния |
|---|---|---|---|---|---|
| 1440×900 | 0 | 0 / 0 | 2 | нет | сохранён, не проверен → доступ подтверждён → получение подтверждено |
| 1280×800 | 0 | 0 / 0 | 2 | нет | то же |
| 390×844 | 0 | 0 / 0 | 2 | нет | то же |
| 320×700 | 0 | 0 / 0 | 2 | нет | то же |
| 1440×900 (error) | 0 | 0 / 0 | 2 | нет | недоступен → «Ошибка стадии «instance/CRN»» |
| 390×844 (error) | 0 | 0 / 0 | 2 | нет | то же |

Во всех прогонах `card.scrollWidth == card.clientWidth` (внутреннего обрезания нет), карточка целиком во вьюпорте.

**Browser Use (независимый человеко-подобный осмотр, реальный Chrome 157, отдельный временный профиль):** 390×844 и 1440×900. Карточка читаема, иерархия «заголовок + бейдж → состояние → последняя проверка → шаги → поля с масками → кнопки → предупреждение о квоте → Дополнительно → документация»; контролы достижимы, обрезания нет, горизонтального скролла нет; клики «Проверить доступ» и «Проверить получение измерений» переводят бейдж в «доступ подтверждён»/«получение подтверждено» с ожидаемыми строками результата. Цвет не единственный сигнал (текстовые подписи состояний). После перезагрузки бейдж снова «сохранён, не проверен» — проверка не выдаётся за постоянную.

Замечания по evidence builder'а: приложенные `browseruse-*.png` показывают верх страницы/сводку, а детальная IBM-карточка с полями и кнопками ниже сгиба — сами PNG её не доказывают; это покрыто моим независимым прогоном (артефакты не коммитил). Mock-DTO не доказывают реальный backend.

## 6. Findings

### P5B-R1-01 — BLOCKING (IN_SCOPE): нельзя очистить IBM API key и instance; «Удалить» в карточке всегда 422

- **Источник:** §4 owner input («защищённые поля API key и CRN»), `QAN-REC-IBM-02` (состояние «не настроен», различение состояний); униформная семантика provider-ключей проекта.
- **Ожидаемо:** пустое значение = сброс/удаление (как для ANU-ключа); после удаления state «не настроен», `key_present=false`.
- **Фактически:** `POST /api/config` с `{"key":"keys.random_ibm_api_key","value":""}` → **422** `keys.random_ibm_api_key: форма ключа IBM не распознана (empty)`; ключ остаётся `{configured:true,last4:"6789"}`. `keys.random_ibm_instance` с `""` → также 422. CRN и region очищаются (200).
- **Причина:** `_post_config_global` вызывает `ibm_key_shape_error(value)` до записи (`web/api/routes.py:3300-3306`), функция возвращает `"empty"` (`services/mca_random_source.py:1462-1475`); UI-кнопка «Удалить» (`web/index.html:7591` secret-field) идёт в `deleteKeyItem` (`web/app.js:33646`), а для `keys.random_ibm_api_key` (нет в `GLOBAL_SECRET_KEYS`: `web/app.js:82`, `services/chat_keys.py:25`) это empty-write через `persistItems` → тот же 422. Комментарий в коде («Пустое значение допустимо (удаление/сброс)») противоречит поведению.
- **Репро (runtime, TestClient с admin-initData):** см. вывод: CLEAR key → 422; SAVE → 200; CLEAR_AFTER_SAVE → 422, `STILL_CONFIGURED {'configured': True, 'last4': '6789'}`.
- **Влияние:** администратор не может отозвать/удалить IBM credential из UI; состояние «не настроен» недостижимо; компрометированный ключ можно только перезаписать. Дефект нового P5B-контрола, не P5A.
- **Fix:** разрешить пустое значение для `SETTING_IBM_KEY`/`SETTING_IBM_INSTANCE` (или добавить их в существующий allowlist глобальных секретов и использовать safe-endpoint), покрыть тестом очистки (200, `configured=false`).

### P5B-R1-02 — IN_SCOPE (same correction): старый «доступ подтверждён» остаётся после ввода нового ключа

- **Источник:** `QAN-REC-IBM-02` («наличие сохранённого ключа никогда не показывается как успешная проверка»; состояния должны относиться к действующим реквизитам).
- **Ожидаемо:** изменение черновика key/CRN сбрасывает прошлый результат IBM, как это уже сделано для ANU (`onKeyDraft` → `randomCheck = null`, `web/app.js:32375-32380`).
- **Фактически (живой рендер):** после успешной проверки ввод нового непроверенного ключа в поле оставляет бейдж «доступ подтверждён» и прежнюю строку «Доступ подтверждён · instance open-instance…» без признака устаревания. `onKeyDraft` для `keys.random_ibm_*` ничего не сбрасывает.
- **Fix:** сбрасывать `randomIbmCheck`/`randomIbmSmoke` при изменении IBM-черновика (и после сохранения ключа), добавить JS-тест.

### P5B-R1-03 — BLOCKING для доказательной базы (тесты, не продукт): redaction-тесты не различают регрессию

- (a) `tests/test_qrng_p5_ibm_adapter.py:615` `test_crn_not_echoed_in_error_reason` зелёный при полностью отключённом маскировании CRN (M1): `log_ring.sanitize` маскирует литерал `us-east` (он попадает в `_collect_secrets`, т.к. `keys.random_ibm_region` зарегистрирован как `SENSITIVITY_SECRET`, `services/param_catalog.py:3981`), поэтому `crn not in reason` выполняется даже когда остальная часть CRN осталась.
- (b) Ни один из 11 P5B admin-тестов не проверяет отсутствие значения в 422-body: мутация M6 (эхо значения в `detail`) оставляет 11/11 зелёными.
- **Fix:** в (a) использовать CRN с не-секретным регионом (например `eu-de`) и/или проверять отсутствие полного CRN и его account/instance-сегментов; в (b) для каждого 422-кейса добавить `assert value not in resp.text` (и `GOOD_KEY/GOOD_CRN not in text` для отказов). После фикса повторить M1/M6 — должны падать.

### P5B-R1-04 — BACKLOG_ONLY (pre-existing P5A): region/instance IBM классифицированы как SECRET_VALUE

- `keys.random_ibm_region` и `keys.random_ibm_instance` имеют `sensitivity=SENSITIVITY_SECRET` (`services/param_catalog.py:3972,3981`), хотя не являются секретами (`secret=False` в тех же спеках). Следствия: `sanitize` маскирует литералы `us-east`/`open-instance` во всех логах; `debug_config`/`output_projection` считают их credential; это же даёт ложноположительный тест P5B-R1-03(a). Внесено P5A (`03bdf9ad6`), не P5B; на текущий релиз не блокирует.

### P5B-R1-05 — evidence correction (не блокирует продукт): «usage» в результате проверки не отображается

- `p5b-implementation-2026-11-24.md:43` утверждает, что результаты показывают «instance/region/QPU/plan/queue/usage» для доступа. В реальном рендере (4 viewport'а) показаны instance/region/QPU/plan/queue; `usage` (`usage_remaining_ru`) в `randomIbmResultView` есть, но в шаблоне не выводится. Серверная проверка usage получает (`ibm_check_access` → `_check_success`), т.е. read-only проверка покрывает «остаток RU», но UI его не показывает. Исправить формулировку evidence или добавить строку остатка RU (желательно — второе, это полезно владельцу).

### P5B-R1-06 — BACKLOG_ONLY (hardening): result-error путь маскирует CRN, но не key

- `_wait_job` (`services/mca_random_source.py:2713`) вызывает `_clean_error_text(str(exc), crn=crn)`; `api_key` в этой области видимости нет. Сохранённый ключ дополнительно маскируется `sanitize`, черновой — нет; текст ошибки `job.result()` крайне редко содержит токен, но симметрию стоит восстановить (передать `api_key`). Не блокирует.

## 7. Границы и что осталось live-only

- `qiskit-ibm-runtime` **не установлен** (`ModuleNotFoundError`); пин/requirements не менялись; `dependency_missing` — честный путь.
- **Нигде нет hardware-VERIFIED**: `QAN-REC-IBM-01/02/03` — REVIEW; evidence сам говорит «VERIFIED — только live на deployed SHA».
- Нет DDL/миграций/новых флагов: диф не трогает `services/database.py`, `config/`, миграции, `mca_gates`; `random.ibm.*` ParamSpec'и — существующие (P5A), переиспользованы в advanced-блоке.
- Lease/settlement P5A переиспользован: новых классов/таблиц/состояний нет; P5B добавил только `_clean_error_text`-параметр, маскирование в `_wait_job`, shape-валидацию, draw-триггер и UI/маршруты. Второго планировщика нет.
- **Live-only (не проверено и не может быть VERIFIED сейчас):** установка пакета в прод-venv; реальный API key/CRN; IAM; instance/region; список QPU; read-only проверка; ограниченный hardware smoke с настоящими measurement bits; refill→pool→draw; restart attach без resubmit; rotation; fallback IBM→ANU на живом аккаунте; `max_inflight=1` на реальном аккаунте; фактический расход RU/QPU time.
- **Риск live (не доказанный дефект):** smoke-маршрут ждёт завершения job (`_run_ibm_smoke` → `await hardware_smoke`), на Open plan очередь может быть длинной; поведение HTTP/прокси на живом шаге нужно проверить (UI имеет busy-состояние). Проверять на postdeploy, не блокирует инженерную готовность.
- **Владелец — не QA:** шаг владельца описан корректно (ввести key+CRN в админке → «Проверить доступ» read-only → при желании «Проверить получение измерений» с подтверждением; значения не зачисляются). Дальнейшие проверки выполняют агенты на deployed SHA.
- Визуальный гейт — mock-DTO preprod (не production, не живой IBM); production `/api/status` требует Telegram initData. Скриншоты не коммитил; временный гарнесс удалён, порты 8931/9222 закрыты.
- Расхождение с builder evidence: 2 падения `tests/test_webapp_key_availability_ui.py::TestRoleRenameDeleteUi` воспроизведены и на базовом `web/index.html` (`fa9e8b3f6`) — предсуществующие, вне scope (роли/UI, не IBM).

## 8. Итог

- **QAN-REC-IBM-01:** REVIEW — адаптер/auto-QPU/provenance/no-PRNG покрыты, live QPU отсутствует.
- **QAN-REC-IBM-02:** REVIEW — read-only/платный split и состояния реализованы, но admin-поля нельзя очистить (P5B-R1-01) и состояние «проверено» переживает смену ключа (P5B-R1-02).
- **QAN-REC-IBM-03:** REVIEW — durable jobs/идемпотентность/лимиты/floor/fallback покрыты, live restart/attach отсутствует.
- **Вердикт: NEEDS_FIXES** по `968eec6c`; после исправления P5B-R1-01/02/03 повторно ревьюится только дельта + затронутые инварианты. Строки остаются REVIEW до реального авторизованного QPU-вызова.

---

# r2 — повторное ревью корректировки R1 (2026-11-25)

- **Роль:** Reviewer (independent). **Дата:** 2026-11-25.
- **Кандидат:** `feat/qrng-ibm-p5b-2026-11-24` tip `4f5ad27c4fed37264f1c6a0589ab6852b149467f` (один корректирующий коммит на `968eec6c`).
- **Дельта:** `968eec6c..4f5ad27c4` — ровно 8 файлов, **+301/−40** (совпадает с заявленным): `services/mca_random_source.py` **не менялся**; изменения только в `web/api/routes.py`, `web/app.js`, `web/index.html`, тестах/evidence.
- **Контракт:** без изменений (owner input §4; `QAN-REC-IBM-01..03` = REVIEW, `live_required=true`).

## r2.0 Вердикт

```json
{
  "verdict": "NEEDS_FIXES",
  "candidate": "4f5ad27c4fed37264f1c6a0589ab6852b149467f",
  "delta_from": "968eec6c07f874b132490763746bc715140706e8",
  "rows": {"QAN-REC-IBM-01": "REVIEW", "QAN-REC-IBM-02": "REVIEW", "QAN-REC-IBM-03": "REVIEW"},
  "hardware_verified_claim": false,
  "r1_findings": {
    "P5B-R1-01": "fixed_at_api_level_ui_blocked_by_R2-01",
    "P5B-R1-02": "logic_fixed_end_to_end_blocked_by_R2-01",
    "P5B-R1-03a_M1": "killed",
    "P5B-R1-03b_M6": "killed_for_generic_echo_residual_M6b",
    "P5B-R1-04": "backlog",
    "P5B-R1-05": "fixed",
    "P5B-R1-06": "backlog"
  },
  "new_blocking": ["P5B-R2-01"],
  "residuals": ["P5B-R2-02", "P5B-R2-03"],
  "next": "fix randomProviderSummary stale shape (restore full summary object); add render/shape test; re-review delta"
}
```

**Коротко.** Оба исходных блокера на уровне семантики исправлены: пустой key/CRN/instance — легальный clear (200, `{configured:false,last4:null}`, instance → `""` + runtime default), а правка key/CRN сбрасывает check/smoke и отбрасывает ответ старого in-flight запроса по seq. Но корректировка внесла **новый блокирующий UI-регресс**: при `randomIbmStale=true` `randomProviderSummary('ibm_quantum')` возвращает неполный объект (`emptySuccess` вместо summary), шаблон читает `p.lastSuccess.kind` и падает; **вся админка становится пустой при вводе/сохранении/удалении IBM key/CRN** (Playwright + Browser Use). До исправления релиз P5B не готов.

## r2.1 Статус findings R1

| ID | Статус r2 | Доказательство |
|---|---|---|
| P5B-R1-01 — clear key/instance | **Fix подтверждён на API/данных; UI-путь заблокирован R2-01** | runtime-проба: CLEAR key → 200, GET `{configured:False,last4:None}`; CRN → 200/`configured:false`; instance → 200, GET `""`; секрет не сохраняется. Код: `web/api/routes.py:3297-3330` (пустое значение не валидируется как форма); UI-reset: `web/app.js:32892-32896` (`saveRandomField`), `33132-33136` (`saveRandomIbmSecrets`), `33765-33769` (`deleteKeyItem`). Python-тест `test_clear_key_crn_and_reset_instance`. |
| P5B-R1-02 — сброс verify при смене key/CRN | **Логика исправлена; end-to-end наблюдение заблокировано R2-01** | `onKeyDraft` (`web/app.js:32381-32393`) инкрементирует `randomIbmProbeSeq`, обнуляет check/smoke, ставит `randomIbmStale=true`; ответ старого запроса отбрасывается (`33156`, `33198`); успешная проверка снимает stale (`33158`, `33200`). Unit: JS-тест (сброс, stale-текст, discard, delete) зелёный. В реальном браузере то же действие валит рендер (R2-01), поэтому видимое поведение проверить нельзя. |
| P5B-R1-03(a) M1 | **KILLED** | CRN-тест использует sentinel в account/instance (`tests/test_qrng_p5_ibm_adapter.py:615-632`); моя мутация `(key, crn)` → `(key,)` даёт **FAIL** (`test_crn_not_echoed_in_error_reason`), восстановленный код — PASS. |
| P5B-R1-03(b) M6 | **KILLED для «эха значения»; узкий M6b переживает** | `test_422_never_echoes_submitted_secret` (`tests/test_qrng_p5b_ibm_admin.py:342-369`) ловит эхо значения в key-ветке (invalid_chars): мутация shape→`invalid_chars+text` даёт **FAIL**. Остаточный M6b: эхо только в `too_short` (`return "too_short" + text`) переживает все 13 тестов, т.к. absence-кейс для key использует значение с пробелами (invalid_chars), а не too_short. |
| P5B-R1-04 — region/instance как SECRET_VALUE | backlog, не расширяли scope | `services/param_catalog.py:3972,3981` без изменений; заявлено в evidence §3a. |
| P5B-R1-05 — «usage» в результате | **Fixed** | `web/index.html:7649-7656` рендерит `usage_remaining_ru` / `usage_remaining_seconds` / `usage_limit_reached`; в рендере после check: «… · очередь 2 · **RU осталось 590**». |
| P5B-R1-06 — result-error маскирует CRN, не key | backlog | `services/mca_random_source.py` в r2 не менялся. |

## r2.2 Новый блокирующий finding

### P5B-R2-01 — BLOCKING (IN_SCOPE regression): ввод/сохранение/удаление IBM key/CRN делает всю админку пустой

- **Ожидаемо:** после правки key/CRN карточка показывает «сохранён, не проверен» + stale-текст; остальная страница остаётся рабочей (это цель R1-02).
- **Фактически:** при `randomIbmStale=true` `randomProviderSummary('ibm_quantum')` (`web/app.js:33475-33486`) делает `return emptySuccess` — возвращает **вложенный** объект вместо полного summary. Шаблон `web/index.html:7532` читает `p.lastSuccess.kind` → `TypeError: Cannot read properties of undefined (reading 'kind')`; Vue прерывает рендер корня, и **вся страница пустая** (нет header, нет карточек, `document.body.innerText` пуст).
- **Воспроизведение:**
  - Playwright 1440×900 и 390×844: открыть `…/web/index.html#/modules/random` (mock-DTO), клик «Проверить доступ» (успех, RU-строка), ввести новый key в поле → карточка/шапка исчезают, console: `TypeError … reading 'kind'`, скриншот полностью пустой.
  - Browser Use (независимо, 390×844): после того же ввода `{"appTextLen":0,"card":false,"shell":false}` — пустая страница.
  - JS-уровень без браузера: `randomProviderSummary('ibm_quantum')` при stale возвращает ключи `available,kind,at,timeLabel,length,sourceId,sourceLabel,configMatches,label`; `lastSuccess === undefined`; `s1.lastSuccess.kind` → тот же TypeError.
- **Триггеры:** любой путь, ставящий `randomIbmStale=true`: `onKeyDraft` (ввод в поле), `saveRandomIbmSecrets` (после сохранения), `saveRandomField` (instance/region/channel), `deleteKeyItem` (удаление key/CRN). То есть нормальные действия владельца с новыми полями.
- **Причина в тестах:** JS-тест проверяет `randomIbmStateInfo` и helper-методы (`randomProviderLastSuccess/LastSwitch`), но **не** форму `randomProviderSummary` и не рендер; при этом его ассерты `last_success/last_error скрыты` тавтологичны — в фикстуре `last_success_at:null/last_error:null`, а фактическая stale-маска живёт именно в сломанном `randomProviderSummary`. Поэтому 6/6 JS-наборов зелёные при полностью нерабочем UI.
- **Fix:** в stale-ветке вернуть полный объект summary: `id`, `label`, `type`, `stateKey/stateLabel/stateCls/stateText`, `configured/keyPresent`, `reserve/reserveText`, `consumable/consumableText`, `quarantined`, `lastSuccess: emptySuccess`, `lastSwitch: emptySwitch`, `adapterNotImplemented:false` (либо убрать early-return и применять маску к вложенным полям). Добавить unit-проверку формы summary + рендер-проверку stale-состояния.

## r2.3 Остаточные (не блокируют при исправлении R2-01)

### P5B-R2-02 — whitespace-only значение сохраняется как «configured»

- `POST /api/config` с `keys.random_ibm_api_key = "   "` → 200, GET `{configured:true,last4:"   "}`; instance `"  "` → GET `"  "`. Runtime `_ibm_api_key()/_ibm_instance()` делают `.strip()` → фактически пусто/дефолт, т.е. UI-состояние «configured» ложно. Появилось из-за `if text:` (после strip) в `routes.py:3300-3319` при сохранении сырого значения. Через UI не воспроизводится (`saveKeyItem`/`deleteKeyItem` тримят), только прямым API. Fix: писать `text` (stripped) либо 422 на whitespace-only. Minor.

### P5B-R2-03 — остаточные пробелы тестов

- M6b (эхо значения только в `too_short`) переживает 13/13: в `test_422_never_echoes_submitted_secret` добавить too_short-кейс с sentinel.
- Нет рендер-теста/проверки формы `randomProviderSummary` для stale (см. R2-01); ассерты `randomProviderLastSuccess/LastSwitch` в JS-тесте тавтологичны.
- `randomIbmStale` после успешного сохранения показывает текст «Черновик key/CRN изменён… Сохраните и проверьте заново» — после save это уже не черновик; формулировку стоит уточнить (косметика).

## r2.4 Счётчики, RED, мутации

- `py -m pytest tests/test_qrng_p5_ibm_adapter.py tests/test_qrng_p5b_ibm_admin.py` → **90 passed** (77 P5 + 13 P5B admin) — совпадает с заявленным.
- Комбинированный QRNG/F8/UI-mirror/route набор → **410 passed** (было 408; +2 новых admin-теста).
- JS: **6/6** (`QRNG-P5B-OK`, `QRNG-UI07-OK`, `QRNG-UI06-OK`, `QRNG-P4-UI-OK`, `MCA10A-RANDOM-OK`, `MODULE-WORKSPACE-OK`).
- `py_compile` rc 0, `git diff --check` rc 0, `gen_param_registry --check` → `CHECK OK` (659).
- RED на base `fa9e8b3f6` (продуктовые файлы заменены, затем восстановлены): **13 failed / 9 passed** — точное совпадение с заявленным; JS — `randomIbmStateInfo is not a function`. После восстановления 22/22 и дерево чистое.
- Мутации r2: **M1 killed**, **M6a killed**, **M6b survived** (см. выше). Дерево после каждой мутации восстановлено (`git status --porcelain` пуст, `git diff HEAD` пуст).

## r2.5 Визуальный гейт r2 (обязателен: менялись текст/состояния)

Гарнесс тот же: реальные `web/index.html` + `web/app.js` кандидата, локальный static-сервер, stateful mock `/api/*` (config/status/check/smoke), Telegram SDK-заглушка; **не production и не живой IBM**. Отличие r2: mock умеет очищать конфиг по POST и задерживать `/api/random/test` (для in-flight).

- **Playwright:** 1440×900 и 390×844. Нормальные состояния рендерятся: badge «сохранён, не проверен» → после check «доступ подтверждён», результат содержит `· RU осталось 590`; overflow 0, console/page errors 0 до правки. После ввода нового key — **страница пустая**, `TypeError … 'kind'` (см. R2-01). Сценарий B (задержка 1500 мс, правка во время in-flight) тоже упирается в пустую страницу; сам discard проверен unit-тестом и чтением кода, end-to-end — нет.
- **Browser Use (независимо):** 390×844, до правки badge «сохранён, не проверен»; после ввода — `appTextLen=0`, `card=false`, `shell=false` (пустая страница).
- **Вывод:** визуальная регрессия введена самим r2; нормальная сетка/текст (включая RU-строку) не изменились, но stale-состояние ломает рендер. Builder evidence §4 честно указывает, что visual re-run R1-дельты не выполнялся — именно там и обнаружен дефект.

## r2.6 Что осталось до релиза P5B

1. Исправить P5B-R2-01 (форма `randomProviderSummary` в stale) + добавить рендер/форм-тест stale-состояния; перепроверить ввод/сохранение/удаление key/CRN в браузере (1440/390) — страница не должна пустеть.
2. После фикса — повторное ревью только дельты: R2-01 + затронутый summary/шаблон; R1-01/R1-02 перепроверить end-to-end (clear → «не настроен», редактирование → stale, discard).
3. Остаточное (можно отдельным мелким corrective/backlog): P5B-R2-02 (strip/422 для whitespace), P5B-R2-03 (too_short sentinel, форма summary), P5B-R1-04, P5B-R1-06.
4. **Live boundary без изменений:** `QAN-REC-IBM-01..03` остаются **REVIEW**; hardware VERIFIED требует реальных key/CRN, `qiskit-ibm-runtime==0.52.1`, IAM/instance/QPU, read-only check, ограниченного smoke и deployed SHA. В r2 live-вызовов не было (пакет не установлен, `ModuleNotFoundError`).
5. DDL/флагов/миграций по-прежнему нет; `services/mca_random_source.py` в r2 не менялся; второй планировщик/lease-дубль не появились.

**Ограничения доказательств r2:** браузерный гарнесс — mock-DTO (не production, не живой IBM); Browser Use запускался в отдельном временном headless-Chrome-профиле; временные артефакты удалены, порты 8941/9222 закрыты; скриншоты не коммитились. Секция r1 выше не изменялась; продуктовые файлы не редактировались; артефакт не коммитился.
---

# r3 — повторное ревью корректировки R2 (2026-11-25)

- **Роль:** Reviewer (independent). **Дата:** 2026-11-25.
- **Кандидат:** `feat/qrng-ibm-p5b-2026-11-24` tip `8ac5b927a16515f5d34779528ed2f2ae2c2905d8` (один коммит на `4f5ad27c4`).
- **Дельта:** `4f5ad27c4..8ac5b927a` — 10 файлов, **+181/−20** (совпадает): `web/app.js`, `web/index.html`, `web/api/routes.py`, тесты/evidence, 2 PNG + browser.json. `services/mca_random_source.py` **не менялся**.
- **Контракт/строки:** без изменений; `QAN-REC-IBM-01..03` — **REVIEW**, `live_required=true`.

## r3.0 Вердикт

```json
{
  "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
  "candidate": "8ac5b927a16515f5d34779528ed2f2ae2c2905d8",
  "delta_from": "4f5ad27c4fed37264f1c6a0589ab6852b149467f",
  "rows": {"QAN-REC-IBM-01": "REVIEW", "QAN-REC-IBM-02": "REVIEW", "QAN-REC-IBM-03": "REVIEW"},
  "hardware_verified_claim": false,
  "r2_findings": {"P5B-R2-01": "fixed", "P5B-R2-02": "fixed", "P5B-R2-03_M6b": "killed"},
  "r1_findings": {"P5B-R1-01": "fixed_end_to_end", "P5B-R1-02": "fixed_end_to_end", "P5B-R1-04": "backlog", "P5B-R1-06": "backlog"},
  "new_blocking": [],
  "residuals_not_blocking": ["P5B-R3-01 (wording)"],
  "release_condition": "release preparation/deploy разрешены для admin-полей/проверок/summary; QAN-REC-IBM-01..03 остаются REVIEW, hardware VERIFIED — только после реальных key/CRN + qiskit-ibm-runtime + QPU + deployed SHA"
}
```

**Коротко.** Shape-фикс тотальный: `randomProviderSummary` больше не имеет частичных возвратов, stale-маска перенесена в `randomProviderLastSuccess` (полный empty), `lastSuccess/lastSwitch` имеют fallback на полные объекты, шаблон дополнительно guard'ит оба поля. A/B-воспроизведение на одном гарнессе: старый `4f5ad27c4` при вводе key → **0 символов** (пустая страница, TypeError `'kind'`), новый `8ac5b927a` → **5676 символов**, карточка/шапка живы, ошибок нет. Whitespace-only теперь нормализуется в пустое значение; M1/M6a/M6b убиты. Блокеров нет; остаётся косметическая формулировка stale-текста после сохранения.

## r3.1 Статус findings

| ID | Статус r3 | Доказательство |
|---|---|---|
| P5B-R2-01 — blank page на stale | **FIXED** | `randomProviderSummary` (`web/app.js:33478-33549`) всегда возвращает полную строку: оба return-пути содержат `id/label/type/state*/configured/.../lastSuccess/lastSwitch`; `lastSuccess = this.randomProviderLastSuccess(id) || emptySuccess` (`33526`), `lastSwitch = ... \|\| emptySwitch` (`33527`). Stale-маска: `randomProviderLastSuccess` возвращает полный `empty` (`33334-33348`). Шаблон: `p.lastSuccess && p.lastSuccess.kind` (`web/index.html:7532`), `p.lastSuccess && p.lastSuccess.available` (`7535`), `p.lastSwitch && p.lastSwitch.code` (`7549`). A/B и JS-shape тест ниже. |
| P5B-R2-02 — whitespace-only как configured | **FIXED** | `web/api/routes.py:3297-3302`: для key/CRN/instance `value = str(value or "").strip()` до записи; whitespace-only → `""` → clear/reset. Тест `test_whitespace_only_is_empty_and_values_are_trimmed` (`tests/test_qrng_p5b_ibm_admin.py`): тримминг `"  key  "` → `last4` без пробелов; `"   \t  "` → `{configured:false}`; instance `" \t "` → `""`. На старом `routes.py` тест **FAIL**, на новом PASS. |
| P5B-R2-03 / M6b | **KILLED** | В `test_422_never_echoes_submitted_secret` добавлен `(IBM_KEY, "P5BSECRET", "P5BSECRET")` (too_short). Мутация `too_short` → `"too_short"+text` даёт **FAIL**; M6a (`invalid_chars`+text) и M1 (`(key,crn)→(key,)`) тоже **FAIL**. Дерево после каждой мутации чистое. |
| P5B-R1-01 — clear key/instance | **FIXED end-to-end** | API-проба: clear key/CRN → 200/`{configured:false,last4:null}`; instance → 200/`""`. В браузере: ввод → save → **delete** → badge «не настроен», маска «Не настроен», DOM непустой (5691 симв.), errors 0. |
| P5B-R1-02 — смена key/CRN сбрасывает проверку | **FIXED end-to-end** | В браузере: check → «доступ подтверждён»; ввод нового key → «сохранён, не проверен» + stale-текст + «Последняя проверка: не проверялось»; instance reset → снова stale. Unit-тест discard in-flight оставлен; end-to-end discard теперь не блокируется рендером (страница жива), но отдельно в браузере не форсировал задержку — проверено unit-тестом + чтением кода. |
| P5B-R1-05 — usage в результате | **FIXED** | `web/index.html:7649-7656`; в рендере после check «… · очередь 2 · RU осталось 590». |
| P5B-R1-04 / R1-06 | backlog (честно) | `services/param_catalog.py` и `services/mca_random_source.py` в r2/r3 не менялись; evidence §3a/§3b фиксирует backlog. |

### Аудит всех чтений (shape totality)

| Чтение | Форма | Безопасно |
|---|---|---|
| `p.lastSuccess.kind/available/sourceLabel/timeLabel/length/configMatches` (`index.html:7532-7540`) | `randomProviderSummary.lastSuccess` = `randomProviderLastSuccess(id) \|\| emptySuccess`; stale → полный `empty`; method всегда возвращает объект (`33334-33389`) | да: полный объект + template guard |
| `p.lastSwitch.code/label/timeLabel` (`7549-7553`) | `randomProviderLastSwitch(id)` всегда объект (`empty`/`pack`), + `\|\| emptySwitch` | да: полный объект + template guard |
| `randomLastSuccess.kind/label/tone/text` (`17655-17659`) | отдельный computed (`app.js:12764-12793`), все ветки возвращают полный объект | да (pre-existing) |
| `randomLastSwitchView().code/label/timeLabel` (`7501-7505`) | отдельный computed (`app.js:33457-33477`), все ветки полные | да (pre-existing) |
| `randomIbmStateInfo()/randomIbmCheckView()/randomIbmSmokeView()` | возвращают полные объекты, читаются через метод, не через частичный summary | да |

## r3.2 A/B-воспроизведение blank-page (мой гарнесс)

Гарнесс: реальные `web/index.html` + `web/app.js` из worktree, локальный static-сервер, stateful mock `/api/*` (config/status/check/smoke, очистка по POST), Telegram SDK-заглушка; **не production, не живой IBM**. Один и тот же сценарий на одном сервере: открыть `#/modules/random` → раскрыть «Подробности, ключи и проверка» → ввести новый key в поле (input event).

- **OLD `4f5ad27c4`** (checkout только `web/app.js`+`web/index.html`): до ввода `chars=5606, shell=true, card=true`; после ввода **`chars=0, shell=false, card=false`**, console `TypeError: Cannot read properties of undefined (reading 'kind')`, pageerrors `[]`.
- **NEW `8ac5b927a`** (восстановленный HEAD): до ввода `chars=5606`; после ввода **`chars=5676, shell=true, card=true`**, console `[]`, pageerrors `[]`, badge «сохранён, не проверен», stale-текст.
- **JS-shape тест на OLD `app.js`**: `AssertionError: stale: summary shape incomplete` (строка 201 теста); на NEW — `QRNG-P5B-OK`. То есть новый тест действительно ловит регрессию, а не тавтологичен.

Дерево после каждого checkout восстановлено (`git status --porcelain` пуст, `git diff HEAD` пуст).

## r3.3 Полный браузерный сценарий NEW (1440) и мобильный (390)

| Шаг | chars | shell/card | badge | overflow | console/pageerrors |
|---|---|---|---|---|---|
| initial | 5606 | ✓/✓ | сохранён, не проверен | 0 | 0/0 |
| typed (stale) | 5676 | ✓/✓ | сохранён, не проверен | 0 | 0/0 |
| saved | 5666 | ✓/✓ | сохранён, не проверен | 0 | 0/0 |
| checked | 5743 | ✓/✓ | доступ подтверждён (в строке «RU осталось 590») | 0 | 0/0 |
| instance reset | 5712 | ✓/✓ | сохранён, не проверен | 0 | 0/0 |
| deleted | 5691 | ✓/✓ | не настроен (маска «Не настроен») | 0 | 0/0 |

390×844: initial `5490` → typed `5560`, shell/card живы, overflow 0. Raw key/CRN в DOM нет; оба секретных поля — `type=password`, значения пустые, маски `••••AB12`/`••••WXYZ`. **Browser Use (независимо, 390)**: до ввода `chars=5490`, после — `5560`, shell/card true, stale-текст, overflow 0; скриншот подтверждает читаемость карточки.

Числа builder'а (`browser.json`: min 5896/5738) отличаются от моих из-за состава гарнесса, но поведение совпадает: DOM непустой на каждом шаге, `page_errors=[]`, TypeError отсутствует.

## r3.4 Счётчики и мутации

- `pytest tests/test_qrng_p5_ibm_adapter.py tests/test_qrng_p5b_ibm_admin.py` → **91 passed** (77 P5 + 14 P5B admin) — совпадает.
- Комбинированный набор → **411 passed** — совпадает.
- JS: **6/6** (`QRNG-P5B-OK`, `QRNG-UI07-OK`, `QRNG-UI06-OK`, `QRNG-P4-UI-OK`, `MCA10A-RANDOM-OK`, `MODULE-WORKSPACE-OK`).
- `py_compile` rc 0, `git diff --check` rc 0, `gen_param_registry --check` → `CHECK OK` (659).
- Мутации r3: **M1 killed** (`test_crn_not_echoed_in_error_reason`), **M6a killed**, **M6b killed** (`test_422_never_echoes_submitted_secret`, кейс `P5BSECRET`). Новый whitespace-тест на старом `routes.py` падает, на новом проходит.

## r3.5 Остатки и условие релиза

- **P5B-R3-01 (косметика, не блокирует):** после нажатия «Сохранить ключ/CRN» stale-текст остаётся «Черновик key/CRN изменён… Сохраните и проверьте заново» (хотя значение уже сохранено). То же для instance/region/channel. Рекомендация: отдельная формулировка «Сохранено; проверьте заново» или сброс stale-текста после успешного сохранения. Не влияет на состояния/безопасность.
- **Live boundary:** hardware VERIFIED по-прежнему требует реальных key/CRN, `qiskit-ibm-runtime==0.52.1`, IAM/instance/QPU, read-only check, ограниченного smoke и deployed SHA. Локально пакет **не установлен** (`ModuleNotFoundError`); `requirements.txt` не менялся; live-вызовов не было.
- **Backlog:** P5B-R1-04 (region/instance `SENSITIVITY_SECRET` → over-masking), P5B-R1-06 (result-error маскирует CRN, но не key).
- **DDL/флаги/миграции:** отсутствуют; `services/mca_random_source.py` в r2/r3 не менялся; второго планировщика/lease-дубля нет.
- **Write scope:** 10 файлов, +181/−20; `services/*` не затронут.

**Условие релиза:** `8ac5b927a` можно готовить к релизу (admin-поля, read-only проверка, платный smoke, фон/fallback) при сохранении строк `QAN-REC-IBM-01..03` в **REVIEW**; VERIFIED и любые hardware-утверждения — только после реального авторизованного QPU-вызова на deployed SHA. После релиза — обычные postdeploy-проверки агентами, не владельцем.

**Ограничения доказательств r3:** браузерный гарнесс — mock-DTO (не production, не живой IBM); Browser Use — отдельный временный headless-Chrome; временные артефакты удалены, порты 8951/9222 закрыты; скриншоты не коммитились. Секции r1/r2 не изменялись; продуктовые файлы не редактировались (все checkout'ы восстановлены); артефакт не коммитился.