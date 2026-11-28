# VMQ-Q0 / Инкремент A — Q-01 + Q-08 (missing evidence)

- Дата: 2026-11-28
- Ветка: `feat/vmq-q0-2026-11-28`
- База (продукт): `731a7e51cdb747fb3c0507ec80b885e4217766b0` — 2.58.274 (в проде)
- Worktree: `...\WorkspaceData\worktrees\c742e4de9e92c489\vmq-q0-e1b0c072a860-079545c9`
- Карта: `plans/features/vmq-onto-01/requirements-map.json` (`additional_requirements`, `req_id` Q-01/Q-08) — не правилась.
- Новые тесты — единственное изменение продукт-дерева; `services/mca_random_source.py` не изменён (после мутаций восстановлен байт-в-байт).

## Что закрыто

| Строка | Expected evidence (карта) | Артефакт |
|---|---|---|
| **Q-01** | `plans/features/vmq-onto-01/evidence/vmq-q0/random-source-inventory.md` | этот каталог, `random-source-inventory.md` |
| **Q-08** | `plans/features/vmq-onto-01/evidence/vmq-q0/mapping-property-tests.json` | этот каталог, `mapping-property-tests.json` |

Тесты (новые файлы, существующие не редактировались):

- `tests/test_vmq_q0_mapping_property.py` — T1 rejection sampling без bias
  (детерминированный fake quantum-клиент, 8-битный диапазон, n=3,
  журнал отказов), T2 один effective provider на draw + PRNG честно
  подписан, T3 `n==1` без расхода/записи, T4 scoped focus
  chat → global → restricted(default) без чтения чужих строк.
- `tests/test_vmq_q0_source_audit.py` — закрытый реестр
  `ibm_quantum/anu/lfdr`, отсутствие Lizaonair/`ibm_qiskit`/свободного
  текста, адаптер у каждого провайдера и dispatch через один
  `RandomSourceService`, PRNG не провайдер, legacy-mapping
  `memory.random_source`/`keys.random_quantum_*` без потери, легаси-подпись
  партии `ANU Quantum Numbers`.

## Продукт: почему без изменений

Тесты не вскрыли функционального дефекта Q-08: rejection sampling
(`limit=(range//n)*n`), `n==1` fast-path без store-операций,
единственный effective provider на draw, честная маркировка PRNG
(`pseudorandom`/`python-random`, `entropy_class=None`) и scoped-резолв
настроек реализованы в 2.58.274 и подтверждены наблюдаемо.

Единственное аудит-наблюдение по Q-01: `ProviderSpec.fetch` для `anu`
остаётся `None` (адаптер `AnuClient` привязан к сервису, реестровые слоты
заполнялись для LfDR/IBM). Потребители `spec.fetch` в продукте отсутствуют
(проверено grep: только тесты P2/P5), витрина `providers` не выводит
`adapter` из этого поля, ANU достижим через `_fetch_batch` (доказано
dispatch-тестом). Это остаточная несогласованность метаданных, не нарушение
Q-01; фиксируется в inventory для Reviewer, продукт в scope A не менялся.

## Мутации (RED/GREEN)

Каждая мутация применялась к `services/mca_random_source.py`, прогонялся
целевой тест, файл восстанавливался `git checkout --`:

| # | Мутация | RED-тест | Наблюдение |
|---|---|---|---|
| M1 | отключён rejection sampling (`value % n` без limit) | Q08-T1 | `assert (0 is None)` — 256-е значение принято (bias) |
| M2 | `reserve_draw(provider_ids=None)` — смешивание источников | Q08-T2 | `assert 'lfdr' == 'anu'` — draw взял чужой провайдер |
| M3 | `resolve_setting(chat_id=None)` — chat scope игнорируется | Q08-T4 | `assert 'quantum' == 'pseudorandom'` |
| M4 | удалён legacy-алиас `ANU Quantum Numbers` и storage-id | Q01-AUDIT-5 | `assert '' == 'anu'` — легаси-партия не маппится |

После M4 дерево чистое: только новые test-файлы и evidence; продукт-файл
совпадает с `731a7e51c`.

## Прогоны

Новые тесты: **13 passed**.

Смежные random/Q0/QM наборы: **139 passed, 1 deselected** (предсуществующее
падение). QRNG/Q07/random-bootstrap: **252 passed, 3 deselected**
(предсуществующие падения).

Предсуществующие падения на базе (проверены отдельно на чистом дереве через
`git stash -u`, продукт не менялся):

1. `test_mca10a_random_source_block_e_round1037.py::test_reason_codes_additive_only` —
   расхождение P5: эмитируемые IBM job-lifecycle литералы не внесены в
   `mca_events.REASON_CODES` (`abandoned_before_submit`, `cancelled`,
   `config_changed`, `expired`, `job_in_progress`, `no_result`, `recovered`,
   `recovered_pool`, `submit_uncertain`, `task_failed`). Тест ожидает
   регистрацию всех эмитируемых кодов; вне scope A, не исправлялось.
2. `test_qrng_p1_isolation.py::TestRandomBatchProvenanceMigration::*
   test_columns_and_step_registry` / `test_idempotent_and_legacy_rows_preserved` —
   жёсткий пин `PRAGMA user_version == 48`, фактическая схема 50.
3. `test_qrng_p1_isolation.py::TestProviderOperationRbac::test_api_status_has_no_key_fingerprint` —
   blanket-подстрока `"fingerprint"` ломается новыми полями статуса.
4. Вне выборки Q0: 4 падения `test_initiative_coordination.py`
   (`publication_conflict`/publish-guard), также на базе.

Ни одно из этих падений не исправлялось (вне scope A; карта и продукт не
трогаются).

## Что осталось непокрытым

- Живые сетевые вызовы/health ANU/LfDR/IBM — по условию A без
  сети/провайдеров; существующие P2/P5 наборы покрывают адаптеры с fake
  транспортом.
- Durable IBM job lifecycle — существующие p5-наборы, не эти тесты.
- UI/RBAC запись снятого `random.primary_provider` — существующие P3-тесты;
  здесь только read-семантика.

## Корректировка evidence по независимому ревью R1 (F1/F2)

Тесты/продукт не менялись; правка только в evidence-документах.

- **F1 (allowlist):** исправлено ложное обобщение «все 9 ключей в
  `PROVIDER_KEY_SETTINGS`». Точно: 8 legacy `keys.random_quantum_*` входят в
  allowlist (14 записей: `keys.random_quantum_provider` + 8 legacy + 5
  `keys.random_ibm_*`); `memory.random_source` — отдельная memory-настройка,
  в `PROVIDER_KEY_SETTINGS` **не входит**, читается `worker_settings`
  (chat → global → default). См. `random-source-inventory.md` §4 и
  `mapping-property-tests.json` Q01-AUDIT-5.
- **F2 (кредиты/квоты):** добавлен раздел §5 в inventory и case Q01-AUDIT-6 в
  JSON: `mca_random_quota_state`/`mca_random_state` не переписываются и не
  мигрируются (продукт-диф пуст), legacy `keys.random_quantum_plan` →
  `_account_key()` сохранён; приложены существующие зелёные проверки из
  прогонов 139/252 и явно перечислено, что не проверялось (реальные
  прод-строки/миграции на копии не сверялись).
- `plans/features/vmq-onto-01/evidence/vmq-q0/review-r1.md` добавлен в
  репозиторий без изменений (артефакт Reviewer).

## Рекомендация статусов

- **Q-08 → REVIEW** (evidence полный для независимой проверки; VERIFIED —
  прерогатива Reviewer).
- **Q-01 → REVIEW** (evidence полный; Reviewer учитывает аудит-наблюдение
  `ProviderSpec.fetch=anu`, продукт не менялся).
