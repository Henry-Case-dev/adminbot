# VMQ-Q0 / Инкремент A — независимое ревью R1

- **Кандидат:** `9962651521a8849c3b239ac20e6d9ecc0e5618a8` (`feat/vmq-q0-2026-11-28`)
- **База:** `731a7e51cdb747fb3c0507ec80b885e4217766b0` (2.58.274, прод)
- **Вердикт: NEEDS_FIXES** — только по evidence (документальная точность/полнота Q-01). Продукт и тесты корректны; продуктовый diff пуст.
- Продуктовый diff: `git diff --name-status 731a7e51c HEAD` = 5 добавленных файлов (2 теста + 3 evidence); `services/mca_random_source.py` hash `c00d4d9507daedd6cc22ffae0af589164272018e` совпадает с базой. Ветка/коммит соответствуют заявленным.

## Что проверено независимо

| Проверка | Результат |
|---|---|
| Новые тесты | **13 passed** (`mapping_property` 4 + `source_audit` 9), collect-only = 13 |
| Смежные Q0/QM | **139 passed, 1 deselected** (совпало с evidence) |
| QRNG/Q07/random | **252 passed, 3 deselected** (совпало) |
| Предсуществующие падения на чистой базе `731a7e51c` (отдельный worktree) | те же 4: 10 IBM reason_codes; `user_version 50 == 48` ×2; blanket `fingerprint` — не приписаны кандидату |
| Мутации (свои, не Builder) | M1 rejection→`value % n`: T1 RED (`assert (0 is None)`); M2 `provider_ids=None`: T2 RED (`'lfdr' == 'anu'`); M3 chat_id→None: T4 RED (`'quantum' == 'pseudorandom'`); M4 удалён legacy-алиас: audit RED (`'' == 'anu'`). После каждой — `git checkout --`, hash базы восстановлен |
| Q-08 acceptance | T1 точная равномерность 85/85/85 на 256 значениях + наивный контроль 86/85/85; T2 один провайдер на draw, ANU→LfDR, честный PRNG (`provider_id=None`, `entropy_class=None`); T3 `n==1` без store/journal; T4 chat override до расхода, только свой chat_id |
| Q-01 audit | реестр ровно `ibm_quantum/anu/lfdr`, `lizaonair`/`ibm_qiskit` не подменяются; один класс/синглтон сервиса; dispatch трёх адаптеров через один сервис; legacy-ключи и легаси-подпись `ANU Quantum Numbers` |
| `ProviderSpec.fetch` у `anu` | подтверждено: `None`, но **не функциональный дефект** — в продукте нет потребителей `spec.fetch` (grep: только тесты P2/P5 и внутренние `replace`); статус-витрина отдаёт `id/title/entropy_class/...`, не adapter; ANU достижим через `_get_client().fetch` в `_fetch_batch` (dispatch-тест). Остаточная несогласованность метаданных, раскрыта в inventory §6 |

## Findings

### F1 — LOW, IN_SCOPE: evidence неверно описывает allowlist legacy-ключей

- **Ожидалось:** `PROVIDER_KEY_SETTINGS` содержит 8 ключей `keys.random_quantum_*`; `memory.random_source` — отдельная memory-настройка, читается через `worker_settings`, в этот allowlist **не входит**.
- **Фактически:** `random-source-inventory.md:76-77` — «Все девять ключей входят в `PROVIDER_KEY_SETTINGS`»; `mapping-property-tests.json:90` (Q01-AUDIT-5) — «9 pg-ключей … входят в `PROVIDER_KEY_SETTINGS`». Проверено: `SETTING_SOURCE in PROVIDER_KEY_SETTINGS == False`, всего 14 записей; сам тест проверяет только 8 `legacy_keys` как подмножество.
- **Влияние:** ложное представление о RBAC/allowlist для `memory.random_source`; на функциональный результат Q-01/Q-08 не влияет, но evidence должно быть точным до VERIFIED.
- **Исправление:** заменить на «8 legacy `keys.random_quantum_*` входят в `PROVIDER_KEY_SETTINGS`; `memory.random_source` проверяется отдельно как memory-настройка» (в обоих файлах).

### F2 — LOW/MEDIUM, IN_SCOPE: клауза Q-01 о существующих кредитах/квотах не адресована

- **Ожидалось:** acceptance Q-01 включает «существующие кредиты/квоты … mapping/миграцию без потери значений». Inventory/JSON должны явно подтвердить сохранность `mca_random_quota_state`/`mca_random_state` (продукт/схема не менялись) либо сослаться на существующую проверку (`test_qrng_p1_isolation.py::TestDraftKeyIsolation…`, входит в прогон 252).
- **Фактически:** в `random-source-inventory.md` и `mapping-property-tests.json` нет ни раздела, ни ссылки про кредиты/квоты (grep `кредит|credit|quota|квот` = 0). Косвенно 252-прогон проходит, но к этой клаузе не привязан.
- **Влияние:** evidence Q-01 неполно для одной явной клаузы owner-приёмки; потери значений нет (продукт не менялся), но доказательство отсутствует.
- **Исправление:** добавить в inventory короткий раздел/строку со ссылкой на существующий quota-тест либо на неизменность `mca_random_quota_state`/`mca_random_state` в инкременте A.

## Наблюдения (не блокируют)

- **T4 restricted:** значение в ветке `ok=False` равно и глобальному (quantum), и `DEFAULT_SOURCE` (quantum), поэтому тест не различает «global» и «default» по значению; доказаны `source=error` и отсутствие чтения чужих строк, а фактический путь `_global_with_source` подтверждён чтением кода. Для усиления в будущем можно задать глобальное значение, отличное от default.
- **Единственность сервиса:** аудит проверяет один класс и модульный синглтон; потребители не сканируются. `mca_experience_jobs` создаёт отдельный экземпляр того же `RandomSourceService` для archive-purpose — это не второй источник/реестр, но фразу «один экземпляр на процесс» не следует распространять на все call-sites.
- **ANU `ProviderSpec.fetch=None`** — подтверждено как metadata-only, не маскирует отсутствие адаптера (см. таблицу).

## Ограничения

- Живые сетевые вызовы ANU/LfDR/IBM, health и квоты провайдеров не выполнялись (условие инкремента).
- UI не менялся; Playwright/Browser Use не применимы.
- Деплой не заявляется; версия/прод не проверялись.

## Рекомендация статусов (карту не правил)

- **Q-08 → REVIEW** до исправления F1 в `mapping-property-tests.json`; по существу тесты Q-08 достаточны (T1–T4 + мутации RED), после правки evidence — VERIFIED-кандидат.
- **Q-01 → REVIEW** до исправления F1 и F2; после — VERIFIED-кандидат.
- Продукт/тесты/ветку не менял; артефакт — только этот файл.
