# P5B — IBM Quantum admin fields, checks, background refill (QAN-REC-IBM-01…03)

- **Роль:** Builder. **Дата:** 2026-11-24 (локально 24.11.2026).
- **База:** `fix/qrng-p5a-2026-11-24` tip `d4771476109df0f5cd932242f49c24a6d2c12b19` (r8 `APPROVED_FOR_LIVE_PREP`).
- **Ветка:** `feat/qrng-ibm-p5b-2026-11-24`, worktree `…/qngen-p5b-2026-11-24-f09839761e22-e3506f8b`.
- **Подготовка базы:** merge `26aadf208` (UI-06/07, уже VERIFIED и deployed 2.58.239) — только `web/app.js`, `web/index.html`, JS-тесты и evidence UI-06/07; продуктовый P5B-дифф считается от merge-коммита.
- **Статус:** IMPLEMENTED / PENDING REVIEW. Строки `QAN-REC-IBM-01/02/03` остаются **REVIEW**; VERIFIED — только live на deployed SHA.
- **Границы:** без deploy, SSH, реальных IBM credentials/QPU, DDL, миграций, новых флагов, `task_supervisor` и Unified Reply. Секреты в evidence/логах отсутствуют.

## 1. Требования владельца (§4 owner input 2026-11-24)

| # | Требование | Что сделано | Статус |
|---|---|---|---|
| 1 | Рабочий IBM Quantum Runtime adapter: instance (`open-instance`), region `us-east`, Open plan, авторизация, backends/QPU, реальный Sampler, provenance, честные стадии отказа | P5A-адаптер сохранён и усилен: строгая форма admin-полей, CRN-маскирование в ошибках, `reserve_remaining` в резолюции; `check_access`/`hardware_smoke`/`fetch` без изменений семантики. Mocked-контракт + fake SDK; live — открыт. | REVIEW |
| 2 | Защищённые поля API key + CRN в админке; write-only/маска, только global admin; проверка формы; «Проверить доступ» без секрета | `keys.random_ibm_*` добавлены в `PROVIDER_KEY_SETTINGS`; `POST /api/config` валидирует форму; `POST /api/random/test provider=ibm_quantum` (read-only), карточка IBM с `secret-field` key/CRN, instance/region/channel, кнопками и статусами. | REVIEW |
| 3 | Фоновая работа QPU jobs, очередь/лимиты, существующий durable reserve; не блокировать запросы; уважать floor; fallback на настроенные не-IBM источники; без скрытого PRNG | Существующий `TaskSupervisor`/`task_jobs`/`max_inflight`/дневные лимиты сохранены. Добавлен неблокирующий draw-триггер (`_maybe_schedule_refill`) при пустом/низком запасе IBM, throttle 5 c; `refill_if_needed` уже идёт по действующему порядку ANU/LfDR; PRNG остаётся только явным fallback-режимом. | REVIEW |
| 4 | Автоматическое резервирование/refill при недоступности IBM, честные reason codes | Триггер вызывает тот же `refill_if_needed`; quota/auth/instance/no_backend/daily_* классифицируются и видны в статусе/UI; при провале IBM очередь идёт к ANU/LfDr; `deferred`, если fallback выключен. | REVIEW |

## 2. Изменения (продукт)

### `services/mca_random_source.py` (+133/−20)

- `ibm_key_shape_error`/`ibm_crn_shape_error`/`ibm_instance_shape_error` — консервативная проверка формы защищённых admin-полей (пустой CRN допустим; CRN обязан быть `quantum-compute` с регионом). Точную валидность подтверждает IBM.
- `PROVIDER_KEY_SETTINGS` теперь включает `keys.random_ibm_{api_key,crn,instance,region,channel}`: запись — только global admin, как существующие provider-ключи.
- `_clean_error_text(raw, key, crn)` маскирует и ключ, и полный CRN во всех IBM-путях (service/check/smoke/fetch/attach/tag/result), чтобы ошибка не эхо-ила CRN.
- `_validated` отсекает только испорченную вставку ключа (whitespace/control); строгая форма — на сохранении. Это сохраняет совместимость уже сохранённых/тестовых значений и даёт IBM честно ответить на runtime.
- `ProviderResolution.reserve_remaining` — аддитивная диагностика суммы расходуемого запаса (не меняет выбор/reserve).
- `_maybe_schedule_refill(selection)` вызывается в `draw_index`/`draw_probability`: только при реально сконфигурированном IBM, `auto_refill=True`, и либо `mode != quantum`, либо запас ниже `low_watermark`. Сам refill — существующая задача `TaskSupervisor`; draw не ждёт QPU.
- `_schedule_refill` получил throttle `IBM_REFILL_MIN_INTERVAL_SECONDS = 5`: один watermark не создаёт задачу на каждый draw. Второго планировщика/флага нет.
- `_ibm_stage_for_code` знает `invalid_key_shape`/`invalid_crn_shape`.

### `web/api/routes.py` (+95/−5)

- `RandomTestRequest`: `provider`, `crn` (только body). `POST /api/random/test` с `provider=ibm_quantum` → существующий `ibm_check_access` (read-only, без Sampler/job); пустой provider сохраняет прежний ANU-контракт; неизвестный — 422.
- `RandomIbmSmokeRequest` + `POST /api/random/ibm/smoke`: отдельное платное действие, обязательно `confirm=true`, shots 64…4096; вызывает `ibm_hardware_smoke` (тот же durable job/лимиты/`max_inflight`, `deposited=false`).
- `_post_config_global`: для `keys.random_ibm_api_key/crn/instance/region/channel` проверяется форма до записи (422 с причиной); секреты не логируются и не возвращаются.
- Оба маршрута — `requires_global_admin()`.

### `web/app.js` (+315/−28) и `web/index.html` (+108/−14)

- Карточка IBM больше не заглушка `adapter_not_implemented`: реальные состояния `не настроен` / `сохранён, не проверен` / `проверка выполняется` / `измерение выполняется` / `доступ подтверждён` / `получение подтверждено` / `ошибка стадии`.
- Поля: `secret-field` для API key и CRN (маска `{configured,last4}`, пустой input, «Заменить/Удалить»), `qrng-field` для instance/region/channel; кнопки «Сохранить ключ/CRN», «Проверить доступ», «Проверить получение измерений» с предупреждением о QPU job/квоте.
- Результаты показывают instance/region/QPU/plan/queue/usage для доступа и job id/backend/shots/bits/usage для измерения; сырые key/CRN не рендерятся.
- Лимиты `random.ibm.*` вынесены в существующий advanced-блок (те же ParamSpec, не второй механизм настроек).
- Старые UI-07/UI-06/P4 контракты сохранены; обновлены их проверки состояния IBM (вместо заглушки — фактическое `не настроен`).

## 3. Тесты (локально, Windows, Python 3.12)

| Команда | Результат |
|---|---|
| `py -m pytest tests/test_qrng_p5_ibm_adapter.py -q` | **77 passed** (68 базовых + 9 P5B: форма, CRN-redaction, instance/permission/quota, fallback, floor, draw-триггер, non-blocking) |
| `py -m pytest tests/test_qrng_p5b_ibm_admin.py -q` | **11 passed** (RBAC, read-only, confirm, маски, форма, логи) |
| Комбинированный QRNG/F8/UI-mirror/route набор (P5, P5B, P1/P2/P3, param_catalog, round1025, f01, asap5, webapp_js_unit, mca10a C/D/JS, mca10b D, mca19 E) | **408 passed** |
| `node tests/js/qrng_p5b_ibm_fields_test.js` | `QRNG-P5B-OK` |
| `node tests/js/qrng_ui07_provider_block_test.js` / `qrng_ui_state_test.js` / `qrng_p4_random_ui_test.js` | `QRNG-UI07-OK` / `QRNG-UI06-OK` / `QRNG-P4-UI-OK` |
| `node tests/js/round1037_random_source_test.js` / `round1025_f5_workspace_route_test.js` | `MCA10A-RANDOM-OK` / `MODULE-WORKSPACE-OK` |
| `py -m py_compile` изменённых файлов | rc 0 |
| `git diff --check` | rc 0 |
| `py tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 659 == REGISTRY…` |

Новые тесты проверяют реальное поведение, а не тавтологии: состояние адаптера и стадии отказа, отсутствие сети/ключа в ответе/логах, ровно один платный sampler-вызов у smoke, `confirm`, маску вместо raw, fallback IBM→ANU при quota, границу floor (`>= low_watermark` не триггерит), non-blocking/throttle refill.

### RED (тот же worktree, продуктовые файлы временно заменены на base `d47714761`; после проверки восстановлены по hash)

```
tests/test_qrng_p5_ibm_adapter.py::TestP5BAdminHardening ... 4 failed
tests/test_qrng_p5b_ibm_admin.py ... 7 failed
=> 11 failed, 8 passed
node tests/js/qrng_p5b_ibm_fields_test.js
=> TypeError: c.randomIbmStateInfo is not a function
```

После восстановления: P5 77, P5B 11, JS `QRNG-P5B-OK`.

### Известные несвязанные падения

`tests/test_webapp_key_availability_ui.py::TestRoleRenameDeleteUi` (2 теста) падает **и на base `d47714761`** (проверено подменой base `web/index.html`); это не следствие P5B и не входит в scope.

## 4. Визуальный гейт (обязательный для изменённой карточки)

Реальные `web/index.html` + `web/app.js` отдавались локальным static-сервером; `/api/*` — детерминированные моки публичных DTO (не живой IBM, не production). Секреты в мок-конфиге — только `{configured,last4}`.

| Viewport | Инструмент | overflow | pageerrors / console | raw key/CRN | key/CRN поля | действия |
|---|---|---|---|---|---|---|
| 1440×900 | Playwright + Browser Use | 0 / 1425=1425 | `[]` / `[]` | нет | 2 password, masks | check + smoke |
| 1280×800 | Playwright + Browser Use | 0 / 1265=1265 | `[]` / `[]` | нет | 2 password, masks | check + smoke |
| 390×844 | Playwright + Browser Use | 0 / 390=390 | `[]` / `[]` | нет | 2 password, masks | check + smoke |
| 320×700 | Playwright + Browser Use | 0 / 320=320 | `[]` / `[]` | нет | 2 password, masks | check + smoke |

Наблюдаемый текст после действий: «Доступ подтверждён · instance open-instance · регион us-east · QPU ibm_hw · план Open · очередь 2», «Получение подтверждено · QPU ibm_hw · job job-7 · shots 256 · бит 128 · QPU 0.5 с». Артефакты: `p5b-visual/playwright.json`, `p5b-visual/browseruse.json`, 4 скриншота Browser Use.

## 5. Effective config / границы live

- Действующие значения: channel `ibm_quantum_platform`, instance `open-instance`, region `us-east`; plan не заявляется — читается из ответа IBM (`None`, если IBM его не вернул).
- Лимиты: `max_inflight=1`, `max_jobs_per_day=4`, `max_qpu_seconds_per_day=120`, poll 30 c, job_max_age 3600 c, HTTP timeout 10 c; draw-триггер throttle 5 c (константа, не пользовательский флаг).
- Новых флагов/DDL/миграций нет; `random_source_enabled`/`random_quantum_enabled`/`random_refill_enabled` и пользовательские настройки не менялись.
- **Не проверено live:** установка `qiskit-ibm-runtime==0.52.1` в production venv, реальный key/CRN, IAM, instance, QPU, read-only access, hardware smoke, refill→batch→draw, restart attach, rotation, fallback, `max_inflight=1` на реальном аккаунте. Локально пакет не установлен: IBM честно `dependency_missing`, остальной контур работает.

### Точный шаг владельца (когда будет готов ввести реквизиты)

1. Открыть админку → **Модули → Случайность** → раскрыть **«Подробности, ключи и проверка»** → карточка **IBM Quantum**.
2. Вставить **API key IBM Cloud** и **полный CRN Quantum Compute** в защищённые поля; нажать **«Сохранить ключ/CRN»** (значения уходят только в POST-body, обратно показывается маска `••••last4`).
3. Нажать **«Проверить доступ»** — это строго read-only проверка key/CRN/instance/region/бэкендов/очереди/usage, без QPU job. Владелец увидит фактические `plan`, QPU, очередь или стадию ошибки.
4. При желании нажать **«Проверить получение измерений»** — отдельное подтверждаемое действие, ровно один ограниченный QPU job, значения **не** зачисляются в рабочий запас.

После ввода реквизитов агенты (не владелец) на deployed SHA проверят: установку/import пакета; `POST /api/random/test provider=ibm_quantum`; `POST /api/random/ibm/smoke confirm=true`; `task_jobs`/`mca_random_batches` (job id, backend, shots, bits, usage, `deposited=false`); затем живой refill→pool→draw, restart attach без resubmit, rotation, fallback IBM→ANU, `max_inflight=1`. Только это даёт VERIFIED.

## 6. Остатки / RFL

- Живой QPU-вызов и `qiskit-ibm-runtime==0.52.1` — внешний шаг; строки REVIEW, не VERIFIED.
- Форма key/CRN консервативна: реальную валидность/членство подтверждает IBM; пустой CRN допустим (instance name).
- `check_access` опирается на `service.instances()`; если IBM вернёт пустой список, распознавание неверного instance ограничено (дальше `no_backend`).
- Визуальный гейт — mocked-DTO preprod (production `/api/status` требует Telegram initData); live production UI не заявляется.
- `test_webapp_key_availability_ui` 2 предсуществующих падения (base) — вне scope.
- Deploy/SSH/LLM/owner QA не выполнялись.
