# VMQ-Q0 / Инкремент A — пере-ревью R2 (F1/F2)

- **Кандидат:** `0d4191227cb74d13d2444264bd9ade50a60d2e84` (`feat/vmq-q0-2026-11-28`)
- **База:** `731a7e51cdb747fb3c0507ec80b885e4217766b0` (2.58.274, прод)
- **Предыдущий tip:** `9962651521a8849c3b239ac20e6d9ecc0e5618a8`; R1: `1ca485aca`
- **Вердикт: APPROVED_FOR_RELEASE_PREPARATION** — F1 и F2 закрыты; блокирующих findings нет. Остаточное O1 — неблокирующее уточнение формулировки.
- Продукт/тесты не менялись: `git diff --quiet 996265152 HEAD -- tests services` = 0; `git diff --quiet 731a7e51c HEAD -- services` = 0; hash `services/mca_random_source.py` = `c00d4d9507daedd6cc22ffae0af589164272018e` (база). Изменения с `996265152` — только 3 evidence-файла + `review-r1.md`.

## F1 — CLOSED (allowlist legacy-ключей)

Проверено по коду, не по тексту:

- `PROVIDER_KEY_SETTINGS` — ровно **14** записей: `keys.random_quantum_provider` + **8** legacy (`api_key`, `endpoint`, `plan`, `batch_length`, `data_type`, `request_timeout_seconds`, `refill_low_watermark`, `buffer_max_values`) + **5** `keys.random_ibm_*` (`api_key`, `crn`, `instance`, `region`, `channel`). Совпадает с исправленным текстом inventory §4 и JSON Q01-AUDIT-5.
- `SETTING_SOURCE in PROVIDER_KEY_SETTINGS` = **False**; `memory.random_source` — отдельная запись каталога `memory.random_source` (категория memory, группа `memory_random`, per-chat; `param_catalog._MEMORY` → `pg_id=f"memory.{field.lower()}"`), читается `worker_settings.resolve_setting` (chat → global → default). Формулировка «RBAC/видимость задаются каталогом memory, а не key-allowlist» точна.
- Ложное «все 9 ключей / 9 pg-ключей входят» удалено из inventory и JSON; в `implementation.md` оно упомянуто только как исправленное. `review-r1.md` содержит историческую цитату — это ожидаемый артефакт R1.
- Утверждение о потребителях allowlist (`services/access_preview.py:487`, `web/api/routes.py:3392`) подтверждено; тест проверяет именно подмножество 8 key-ключей, членство `SETTING_SOURCE` им не утверждается.

## F2 — CLOSED (кредиты/квоты)

Проверено по коду и прогонам:

- `mca_random_quota_state` DDL — `services/database.py:1111-1123` (`account_key TEXT PRIMARY KEY`, `period`, `success/failed/unknown/manual_checks`, timestamps); `mca_random_state` — `1124-1133` (`scope TEXT PRIMARY KEY`, `key_fingerprint`, `activation_batch_id`, `activated_at`, `last_fallback_reason/at`). Ссылки точные.
- `_plan()` возвращает только `Trial/Paid/Custom` (код-константа `PLANS`), `_account_key() = f"anu:{self._plan().lower()}"` (`mca_random_source.py:4452-4453`). Утверждение о сохранении legacy `keys.random_quantum_plan` → `anu:<plan>` точное.
- Продуктовый diff инкремента A пуст; `services/database.py` и DDL/миграции не менялись, поэтому durable-строки не переписываются и не мигрируются. Это логическое доказательство отсутствия потери в test-only инкременте; evidence честно указывает, что реальные прод-строки не читались и не сравнивались.
- Названные 4 существующих теста существуют и **4 passed** на кандидате:
  - `test_mca10a_random_source_block_b_round1037.py::test_quota_global_estimate_not_per_chat`
  - `...::test_quota_period_rollover_honest_remaining`
  - `test_qrng_f01_activation_batch_scope.py::test_activation_selfcheck_consumes_only_new_anu_batch`
  - `test_qrng_p1_isolation.py::TestDraftKeyIsolation::test_draft_check_zero_rows_deposited_false`
- Разделение «проверено / не проверено» честное: проверены неизменность кода/схемы и зелёные quota/state-тесты; НЕ проверены реальные прод-строки, миграции на копии прод-БД и живые расходы квоты. Заявлений о проверке прод-данных нет.

## Остаточное наблюдение (не блокирует)

- **O1 LOW:** в inventory §5 тест `test_quota_global_estimate_not_per_chat` описан как покрывающий «Paid/Custom». Фактически тест выставляет только `Paid`; `Custom` идёт той же веткой `plan == "Trial" else None`, но отдельно не параметризован. Это не ложное утверждение о поведении (ветка общая, код прочитан), а неточность описания покрытия. При желании уточнить: «Paid; Custom — та же ветка, отдельно не выставлялся». На выводы Q-01/Q-08 не влияет.

## Целостность и прогоны

- Новые/затронутые тесты: **13 passed** (`mapping_property` 4 + `source_audit` 9).
- `mapping-property-tests.json` валиден: 10 cases, 4 commands, `evidence_revision=2`; Q01-AUDIT-6 присутствует, coverage_limits содержит явное «прод-строки не сверялись».
- `review-r1.md` закоммичен без изменений: blob `23e2f13f1dff44940abdebe774569b0f0df798dd` совпадает на `1ca485aca` и `HEAD`; `git diff 1ca485aca HEAD -- review-r1.md` пуст; sha256 файла `bca8d514a6ec6d700e81a5e173237ef43653d4ea8fae509bc6f1d1a0bd4efe15`.
- Продуктовые/тестовые файлы не менялись; `services/**` diff относительно базы пуст.

## Ограничения

- Живые сетевые вызовы ANU/LfDR/IBM, health и реальные прод-значения квот/состояния не проверялись (условие инкремента).
- UI не менялся; Playwright/Browser Use не применимы.
- Деплой не заявляется; версия/прод не проверялись.

## Рекомендация статусов (карту не правил)

- **Q-01 → VERIFIED** — F1/F2 закрыты; остаточное O1 неблокирующее.
- **Q-08 → VERIFIED** — T1–T4 и мутации R1 остаются в силе; новых изменений тестов нет.
- Артефакт ревью — только этот файл; продукт/тесты/ветку не менял.
