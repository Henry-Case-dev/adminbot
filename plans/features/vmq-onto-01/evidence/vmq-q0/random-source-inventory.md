# VMQ-Q0 / Q-01 — source audit контура `mca_random_source`

- Дата: 2026-11-28
- Инкремент: A (`vmq-q0`), строка карты **Q-01** (`tests/test_vmq_q0_source_audit.py`)
- База/кандидат: `731a7e51c` (2.58.274, прод), ветка `feat/vmq-q0-2026-11-28`
- Продукт НЕ изменён: код контура уже в 2.58.274; аудит подтвердил контракт.

## 1. Реестр провайдеров (`PROVIDERS`, `PROVIDER_IDS`)

| id | title | entropy_class | requires_key | key_setting | docs |
|---|---|---|---|---|---|
| `ibm_quantum` | IBM Quantum | `hardware_quantum` | True | `keys.random_ibm_api_key` | https://quantum.cloud.ibm.com |
| `anu` | ANU Quantum Numbers | `hardware_quantum` | True | `keys.random_quantum_api_key` | https://quantumnumbers.anu.edu.au |
| `lfdr` | LfDR QRNG | `hardware_quantum` | False | — | https://lfdr.de/QRNG/ |

`set(PROVIDERS) == {"ibm_quantum", "anu", "lfdr"}`; порядок
`PROVIDER_IDS == ("ibm_quantum", "anu", "lfdr")`; id — код-идентификаторы
(`^[a-z0-9_]+$`), не свободный текст. UI-селектор
`random.primary_provider.select_options` совпадает с `PROVIDER_IDS`.

Снятые владельцем (owner exclusion 2026-11-17, `QAN-REC-EXC-01…05`) имена
отсутствуют и **не подменяются молча**:
`canonical_provider_id("lizaonair" | "ibm_qiskit" | "ibm" | "") == ""`,
`primary_setting_state("lizaonair") == "requires_resolution"`,
`normalize_fallback_order(["lizaonair", "anu", "anu", "", 42]) == ["anu"]`,
`entropy_class_for("lizaonair") is None`.
Формулировка Q-01 «4 провайдера (anu, lfdr, lizaonair, ibm_qiskit)» в карте
уже помечена как superseded (`status_note` 2026-11-27); действующий реестр —
три id выше.

## 2. Адаптеры (у каждого провайдера, под ОДНИМ сервисом)

| id | адаптер | реестровая точка входа | сервисный путь |
|---|---|---|---|
| `anu` | `AnuClient` (`fetch`, origin-guard, breaker, schema/range валидация) | адаптер предшествует реестру; слот `ProviderSpec.fetch` = `None` (см. §6) | `RandomSourceService._fetch_batch(provider="anu")` → `self._get_client().fetch(...)` |
| `lfdr` | `LfdrClient` (без ключа) | `PROVIDERS["lfdr"].fetch is lfdr_fetch`, `.check is lfdr_check` | `_fetch_batch(provider="lfdr")` → `lfdr_fetch(client=self._get_lfdr_client(), ...)` |
| `ibm_quantum` | `IbmQuantumRuntimeClient` (QPU Sampler, durable job) | `PROVIDERS["ibm_quantum"].fetch is ibm_fetch`, `.check is ibm_check` | `_fetch_batch(provider="ibm_quantum")` → `self._get_ibm_client().fetch(...)` |

Проверено наблюдаемо (`tests/test_vmq_q0_source_audit.py::
test_single_service_dispatches_every_provider_to_its_adapter`): один экземпляр
`RandomSourceService` с тремя fake-клиентами (`set_client`,
`set_lfdr_client`, `set_ibm_client`) реально получает батч от каждого
адаптера; `_get_client()/_get_lfdr_client()/_get_ibm_client()` возвращают
инжектированные объекты (бреker/min-interval — один клиент на провайдера, не
второй контур).

## 3. Единственный сервис случайности

- В модуле ровно один класс-сервис: `[n for n in vars(mrs) if n.endswith("Service")] == ["RandomSourceService"]`.
- Модульный синглтон `get_service()` / `bind_db()` / `reset_service()` —
  один экземпляр на процесс (`get_service() is get_service()`).
- `CoreDreamRandomSource`, `ExplorationPolicy`, `RandomStore`, `AnuClient`,
  `LfdrClient`, `IbmQuantumRuntimeClient` — части того же контура (адаптеры/
  хранилище/политика), а не второй сервис/источник.
- PRNG — **не** провайдер и не ступень fallback:
  `PROVIDER_PRNG ("python-random") not in PROVIDER_IDS/PROVIDERS/
  DEFAULT_FALLBACK_ORDER/CANONICAL_PROVIDER_ORDER`;
  `MODES == ("quantum", "pseudorandom")`; `SOURCE_IMPL_PRNG == "python-random-mt19937"`.

## 4. Legacy-mapping без потери

Константы `services.mca_random_source` (pg-ключи не менялись):

| константа | pg-ключ |
|---|---|
| `SETTING_SOURCE` | `memory.random_source` |
| `SETTING_KEY` | `keys.random_quantum_api_key` |
| `SETTING_ENDPOINT` | `keys.random_quantum_endpoint` |
| `SETTING_PLAN` | `keys.random_quantum_plan` |
| `SETTING_BATCH_LENGTH` | `keys.random_quantum_batch_length` |
| `SETTING_DATA_TYPE` | `keys.random_quantum_data_type` |
| `SETTING_TIMEOUT` | `keys.random_quantum_request_timeout_seconds` |
| `SETTING_LOW_WATERMARK` | `keys.random_quantum_refill_low_watermark` |
| `SETTING_BUFFER_MAX` | `keys.random_quantum_buffer_max_values` |

Все девять ключей входят в `PROVIDER_KEY_SETTINGS` (allowlist операций
global admin) — legacy-ключи не потеряны. Значения читаются тем же
read-path и возвращаются без искажения:
`_resolve_key() == "legacy-anu-key-abc123"`, `_endpoint()`,
`_plan() == "Trial"`, `_batch_length() == 64`, `_data_type() == "uint16"`,
`_timeout_seconds() == 7.0`, `_low_watermark() == 128`,
`_buffer_max() == 1024`, `provider_configured("anu") is True`.
`memory.random_source` читается с приоритетом chat → global → default:
`selected_mode == "pseudorandom"` для сохранённого значения и
`DEFAULT_SOURCE ("quantum")` при отсутствии; фолбэк-переключатель сохранён
(`fallback_enabled() is True`).

Легаси-подпись партии `ANU Quantum Numbers` (история 2.58.x) расходуется и
канонизируется без перезаписи истории: `AnuBatch(provider="ANU Quantum
Numbers")` → `draw_index` возвращает `provider == "ANU Quantum Numbers"`,
`provider_id == "anu"`, `entropy_class == hardware_quantum`; строка партии в
БД остаётся с прежним `provider`; `PROVIDER_STORAGE_IDS["anu"]` содержит оба
написания.

## 5. Тесты / прогоны

```
# новые (Q-01 + Q-08)
python -m pytest tests/test_vmq_q0_source_audit.py tests/test_vmq_q0_mapping_property.py -q
# 13 passed

# смежные random/Q0/QM
python -m pytest tests/test_mca10a_random_source_block_{a..e}_round1037.py \
  tests/test_mca10a_random_source_js_round1037.py \
  tests/test_mca10b_random_applications_block_{a..d}_round1041.py -q
# 139 passed, 1 deselected (предсуществующее падение, см. §7)

# QRNG/Q07/random-bootstrap
python -m pytest tests/test_qrng_*.py tests/test_q07_field_stats.py \
  tests/test_asap5_random_bootstrap_config.py -q
# 252 passed, 3 deselected (предсуществующие падения, см. §7)
```

Окружение: Windows, Python 3.12.0, pytest 9.1.1, `ADMINBOT_SKIP_DOTENV=1`
(корневой conftest), tmp SQLite. Без сети, без прод-БД, без записи в
прод/схемы/флаги.

## 6. Аудит-наблюдение (не дефект, продукт не менялся)

`ProviderSpec.fetch` для `anu` остаётся `None`: ANU-адаптер (`AnuClient`)
существует с 2.58.57 и привязан к сервису (`_get_client()`), а реестровые
слоты `fetch/check` заполнялись только новыми адаптерами P2/P5 (LfDR, IBM).
Проверка `grep` по репозиторию: ни один потребитель не читает
`PROVIDERS[...].fetch` (использования только в тестах P2/P5 и в
`entropy_class`/статусе); витрина `providers` не отдаёт `adapter` из
`spec.fetch`. Функционально ANU достижим через единственный сервис
(доказано dispatch-тестом), поэтому это остаточная метаданные-несогласованность,
а не нарушение Q-01. Рекомендация Reviewer: либо принять как есть с этой
фиксацией, либо отдельной микроправкой связать ANU в реестре (вне scope
инкремента A).

## 7. Предсуществующие падения на базе `731a7e51c` (не связаны с Q-01)

Проверено отдельно на чистом дереве (`git stash -u`, продукт-файл не изменён):

1. `tests/test_mca10a_random_source_block_e_round1037.py::test_reason_codes_additive_only`
   — расхождение P5: эмитируемые IBM job-lifecycle литералы не внесены в
   `mca_events.REASON_CODES` (10 кодов: `abandoned_before_submit`,
   `cancelled`, `config_changed`, `expired`, `job_in_progress`, `no_result`,
   `recovered`, `recovered_pool`, `submit_uncertain`, `task_failed`).
   Тест ожидает регистрацию всех эмитируемых кодов; к Q-01/Q-08 не относится,
   в scope инкремента A не исправлялось.
2. `tests/test_qrng_p1_isolation.py::TestRandomBatchProvenanceMigration::
   test_columns_and_step_registry` и `...::test_idempotent_and_legacy_rows_preserved`
   — жёсткий пин `PRAGMA user_version == 48`, фактическая схема 50.
3. `tests/test_qrng_p1_isolation.py::TestProviderOperationRbac::
   test_api_status_has_no_key_fingerprint` — blanket-подстрока
   `"fingerprint"` в JSON статуса; новые поля (`map_fingerprint` и др.)
   ломают устаревшую проверку.
4. (вне выборки Q0) `tests/test_initiative_coordination.py` — 4 падения по
   `publication_conflict`/publish-guard, также на базе.

Эти падения не исправлялись (вне scope инкремента A; карта/продукт не
трогаются).

## 8. Что осталось непокрытым

- Реальные сетевые вызовы ANU/LfDR/IBM и живой health провайдеров — по
  условию инкремента без сети/провайдеров; покрыто существующими
  P2/P5-наборами с fake-транспортом.
- Полный durable IBM job lifecycle (submit/poll/recover) — существующие
  `test_qrng_p5_ibm_adapter.py`/`test_qrng_p5b_ibm_admin.py` (252 passed).
- Снятое значение `random.primary_provider` в UI/RBAC — существующие
  P3-тесты; в Q-01 аудите проверена только read-семантика
  `requires_resolution`.
