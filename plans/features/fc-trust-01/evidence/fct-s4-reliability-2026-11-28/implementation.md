# FCT-1001 / FCT-1002 — доказательства надёжности и изоляции (Builder, 28.11.2026)

Роль: Builder. Репозиторий: worktree `fc-trust-s4-reliability-4488c81af065-d034fef8`,
ветка `feat/fct-s4-reliability-2026-11-28`. Изменён только этот worktree.
Продукт в основном checkout (master) не менялся; `search_aggregator.py`,
`temporal_factcheck.py`, `prompt_registry.py` не редактировались (U1-зона).

- База: `fa4ba6292` (`release/2.58.272`; в проде 2.58.272 = `a2195fe3f`).
- Код-кандидат: `dc6703a8f77b11505f3fe8518960fadc9df806de` (4 коммита поверх базы:
  фикс надёжности, тест backoff, evidence, точная метка времени claim).
  Предыдущий кандидат с тем же смыслом: `8d5b383de`.

## 1. Вердикт

| Строка | Было | Предлагается | Почему |
|---|---|---|---|
| FCT-1001 | PENDING | **REVIEW** | Найдены и исправлены два реальных нарушения контракта (single-flight на прод-пути персистентного кулдауна; отмена задачи списывала пользовательский лимит). Остальные пункты подтверждены детерминированными тестами и 10 мутациями. Нужно независимое ревью изменений `claim`/cancel-refund. |
| FCT-1002 | REVIEW | **REVIEW** (доказательства усилены) | Продукт не менялся: поведение уже соответствовало контракту. Добавлены детерминированные тесты на роли/источники/кэш/egress и мутации; существующее service-level доказательство сохранено. Готово к независимому ревью. |

Ни одна строка не помечена VERIFIED: самостоятельной приёмки нет. `live_required=false`,
`live_when=preprod` — деплой/живой прогон не выполнялись (запрещены границами задачи).

## 2. Карта «контракт → функция → тест»

### FCT-1001

| Пункт acceptance | Реальная функция/механизм | Детерминированный тест |
|---|---|---|
| provider fallback: 5xx/timeout одной ноги → следующая независимая нога обслуживает | `services/embedding_control_plane.py: EmbeddingExecutor.embed` (`_pick_credential`, `_mark_transport_failure`) | **новый** `tests/test_fc_trust_s4_reliability.py::TestFCT1001ProviderFallback::test_failed_leg_is_parked_and_serving_leg_is_healthy`; матрица — `tests/test_p0_embed_503_failover.py::test_primary_5xx_does_not_burn_all_attempts`, `test_all_legs_5xx_tries_each_independent_leg_once` |
| неудачный лег паркуется в `credential_health`; успешный — healthy | `_park_transport_credential` → `QuotaGroupRegistry.mark_credential`; `_on_success` | тот же новый тест (cooldown + `credential_cooldown_until > 0`; fallback healthy и обслуживает следующий запрос); `test_primary_recovery_probe_after_cooldown`, `test_recovered_fallback_serves_while_primary_parked` |
| backoff сохранён и ограничен | `embed`: `_TRANSPORT_BACKOFF_BASE * 2**(attempts-1)` c `_TRANSPORT_BACKOFF_CAP`, `_ATTEMPT_BUDGET=4` | **новый** `test_single_leg_transport_backoff_is_bounded` (паузы 1x/2x/4x, ровно 4 попытки) |
| все ноги временно недоступны / 429 spend → парковка с cooldown, повтор не бесконечен | `_quota_parking_seconds` (kind spend/daily), `set_group_state`, `max_defers`, `EmbeddingGroupCoolingDown` | **новый** `test_all_legs_spend_parked_is_bounded_and_honest` (ровно 3 HTTP на 3 ноги, `parked kind=spend`, следующий вызов — 0 HTTP); `test_429_respects_group_cooldown_and_next_group`, `test_group_probe_is_p2_only_and_single_attempt` |
| честный технический исход (не ложный успех) | `EmbeddingGroupCoolingDown` / `EmbeddingRetriesExhausted`; потребитель → text-only/FTS | `tests/test_p0_embed_503_failover.py::test_all_legs_down_saves_text_only_then_recovers_backfill`; `tests/test_fc_trust_verdict.py::TestExecutionStatus::test_provider_down_without_parts_is_technical_unverified` |
| кооперативная отмена прекращает работу и различается с дедлайном | `services/factcheck_planner.py: run_retrieval(is_cancelled=...)` → `STOP_CANCELLED`, `cancelled=True`; `CLAIM_STATUS_CANCELLED` | `tests/test_fc_trust_retrieval.py::test_cancelled_run_is_reported_as_cancelled`; `tests/test_fc_trust_verdict.py::TestExecutionStatus::test_cancelled_run_cause` |
| отмена не списывает пользовательский лимит и не оставляет задач | `handlers/factcheck.py: factcheck_handler` (wrapper) → `_settle_cancelled` → `_refund_cooldown("cancelled")`; `_ACTIVE_SLOT` ContextVar; `finally: permit.release()` | **новый** `TestFCT1001CooperativeCancel::test_cancelled_check_stops_and_refunds_user_limit` (CancelledError пробрасывается, `remaining == 0`, нет незавершённых задач); отрицательный контроль `test_cancel_before_slot_is_claimed_keeps_no_state` |
| single-flight: два одновременных одинаковых запроса не удваивают платный вызов | `PersistentCooldownTracker.claim` (одна write-транзакция) + `CooldownTracker.claim`; `cooldown_claim`; handler | **новый** `TestFCT1001SingleFlight::test_persistent_tracker_does_not_double_provider_call` (прод-путь `THROTTLE_PERSISTENT_ENABLED=True`); in-memory путь — `test_evol_fc_admission.py::TestScenario8CooldownAndSingleFlight::test_single_flight_and_antispam_preserved` |
| cooldown/ранние отказы не расходуют лимит; вердикт — расходует | `_EARLY_OUTCOMES`, `_settle_cooldown`, `_refund_cooldown` | **новый** `TestFCT1001LimitAccounting::test_technical_error_refunds_and_verdict_keeps`; `test_evol_fc_admission.py::...::test_persistent_tracker_refund_deletes_slot`, `test_settle_cooldown_reports_actual_outcome`, `test_retry_after_early_refusal_not_blocked` |
| защита от бесконтрольных расходов | `_ATTEMPT_BUDGET`, `max_defers`, group parking, P2-only bounded probe | новые тесты выше (точные счётчики HTTP), `test_group_probe_5xx_stays_parked_and_throttled`, `test_group_probe_spend_429_stays_parked_without_spam` |

Замечание D8 (s4-design): отдельного фактчек-retry/backoff не добавлялось; LLM-стадия
использует существующий глобальный retry/backoff `llm_client` (существующие тесты
`tests/test_llm_client.py` зелёные, см. raw); новый backoff-тест покрывает транспорт
embedding-провайдера — фактический provider-путь фактчека.

### FCT-1002

| Пункт acceptance | Реальная функция/механизм | Детерминированный тест |
|---|---|---|
| доказательства и роли не смешиваются между чатами | `FactCheckService.check_claim_envelope` → `merge_claim_coverage` (локальные parts/coverage/evidence) | **новый** `TestFCT1002ChatIsolation::test_roles_and_sources_do_not_mix_between_chats` (A = supports/ev-a, B = contradicts/ev-b; роли и ссылки не переворачивают вердикты); существующий `tests/test_fc_trust_verdict.py::TestFCT1002ConcurrentChatsIsolation` |
| источники/ссылки только текущего прогона | `EvidenceMap.links()`, `build_presentation` (egress-whitelist) | тот же новый тест (`evidence_rows` url-наборы); **новый** `test_published_payload_has_no_internal_fields_or_foreign_links` |
| кэш не смешивается | `services/factcheck_context.py: slice_cache_components/slice_cache_key` (chat_id в идентичности), `read_slice_cache` | **новые** `test_slice_cache_key_is_chat_scoped_and_reused_within_chat`, `test_slice_cache_never_serves_another_chat` (запись A не читается B; A читается A) |
| участники не получают закрытые служебные данные | `factcheck_orchestrator.build_presentation` (только whitelist-поля, ссылки из `EvidenceMap`), `factcheck_renderer.visible_text` | **новый** `test_published_payload_has_no_internal_fields_or_foreign_links` (нет `ev-*`, `claim_id`, `execution_cause`, `role`, чужих хостов) |

Вердиктный кэш в продуктовой линии отсутствует по контракту
(P0-FACTCHECK-CORRECTIVE §6, `CheckedVerdict.cache_hit` всегда False), поэтому
«кэш» фактчека — это кэш среза широкого контекста; он проверен выше. `_RUNTIME`
оркестратора — рантайм-привязка (db/service/cache), не хранилище доказательств и не
разделяется между чатами по построению.

## 3. Что изменено в продукте (минимально, в границах)

1. `services/persistent_throttling.py`
   - `PersistentCooldownTracker.claim(chat_id, user_id) -> (acquired, remaining)`:
     чтение `last_ts` и занятие слота — в ОДНОЙ `write_transaction` (single-writer).
     Устранено окно гонки `remaining()`→`touch()`, из-за которого два одновременных
     одинаковых запроса (прод-дефолт `THROTTLE_PERSISTENT_ENABLED=True`) оба проходили
     в платную проверку. Fail-open при ошибке БД — прежний `(True, 0.0)`.
   - `cooldown_claim(tracker, ...)` — helper: `claim`, иначе прежняя пара вызовов
     (совместимость с DI-двойниками/внешними трекерами).
2. `services/smartmodule_throttling.py`
   - `CooldownTracker.claim(...)` — синхронный атомарный шаг (in-memory путь).
3. `handlers/factcheck.py`
   - проверка+занятие слота через `cooldown_claim` (вместо `cooldown_remaining`+`cooldown_touch`);
   - `_ACTIVE_SLOT` (ContextVar на задачу) фиксирует занятый слот; публичный
     `factcheck_handler` — тонкий wrapper: `except asyncio.CancelledError` →
     `_settle_cancelled` (возврат слота `refund:cancelled`) → `raise`;
   - `_settle_cooldown` очищает `_ACTIVE_SLOT` (исход зафиксирован — отмена после
     доставки не возвращает слот).
4. Тестовые швы (не поведение): в 4 существующих файлах патч
   `fh.cooldown_remaining`/`cooldown_touch` заменён на `fh.cooldown_claim`
   (тот же смысл «без троттлинга в тесте»): `test_fc_trust_target.py`,
   `test_factcheck_media_2026_10_25.py`, `test_rc_target_media_evidence.py`,
   `test_mca20_integration_round1045.py`.
5. Новый файл `tests/test_fc_trust_s4_reliability.py` — 11 тестов.

Не менялись: `services/search_aggregator.py`, `services/temporal_factcheck.py`,
`services/prompt_registry.py`, рендер/публикация, флаги, DDL, фоновые сервисы,
инструкции LLM.

## 4. RED → GREEN

- RED на чистой базе `fa4ba6292` (продуктовые файлы временно взяты из базы,
  затем восстановлены): `2 failed, 9 passed` — падают ровно два исправленных
  поведения: отмена списывает лимит; персистентный single-flight удваивает вызов.
  `raw/red-base-fa4ba6292-final.txt`
- GREEN на кандидате `dc6703a8f`: `11 passed`.
  `raw/green-new.txt`
- Восемь остальных тестов зелёные и на базе — это контроль, что тесты не
  «подгонялись» под изменения.

## 5. Мутации (10/10 RED)

`raw/mutations.py`, результаты — `raw/mutations.txt`. Каждая мутация — минимальная
порча реального механизма, после прогона файл восстановлен (`git checkout --`,
дерево чистое).

| ID | Мутация | Тест, ставший RED |
|---|---|---|
| M-FCT1001-PARK | убрана парковка 5xx-ноги | `test_failed_leg_is_parked_and_serving_leg_is_healthy` |
| M-FCT1001-SPEND-PARK | убрана kind-aware парковка spend | `test_all_legs_spend_parked_is_bounded_and_honest` |
| M-FCT1001-BACKOFF | `sleep(0)` вместо 1x/2x/4x | `test_single_leg_transport_backoff_is_bounded` |
| M-FCT1001-CANCEL-REFUND | отмена не возвращает слот | `test_cancelled_check_stops_and_refunds_user_limit` |
| M-FCT1001-SINGLEFLIGHT | `claim` = неатомарные `remaining()`+`touch()` | `test_persistent_tracker_does_not_double_provider_call` |
| M-FCT1001-LIMIT-EARLY | ранний/технический отказ не возвращает слот | `test_technical_error_refunds_and_verdict_keeps` |
| M-FCT1001-PLANNER-CANCEL | `is_cancelled` игнорируется в retrieval | `test_cancelled_run_is_reported_as_cancelled` |
| M-FCT1002-CACHE | `chat_id` убран из ключа кэша среза | `test_slice_cache_never_serves_another_chat` |
| M-FCT1002-EGRESS | `evidence_refs` просочились в публикуемый текст | `test_published_payload_has_no_internal_fields_or_foreign_links` |
| M-FCT1002-MIX | общий глобальный coverage между чатами | `test_roles_and_sources_do_not_mix_between_chats` |

## 6. Команды и результаты (кандидат `dc6703a8f`)

Интерпретатор: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (3.12.0),
cwd — этот worktree, все прогоны с `-p no:cacheprovider`.

| Прогон | Команда (сокращённо) | Результат | raw |
|---|---|---|---|
| новые тесты | `pytest tests/test_fc_trust_s4_reliability.py -q` | **11 passed** | `green-new.txt` |
| база (RED) | те же тесты при продуктовых файлах `fa4ba6292` | **2 failed, 9 passed** | `red-base-fa4ba6292-final.txt` |
| FC-TRUST широкий | `test_fc_trust_*.py test_p0_embed_503_failover.py` и все factcheck-файлы + `test_rc_target_media_evidence.py test_asap8_v63_b07_temporal_factcheck.py` (40 файлов) | **925 passed** | `green-broad-a.txt` |
| embed/failover профиль | `test_p0_embed_503_failover.py test_embed_fallback_slots_routing.py test_embedding_control_plane_asap4.py test_embed_simplify_2026_11_24.py` | **106 passed** | `green-embed.txt` |
| handler/throttle профиль | `test_factcheck_handlers.py test_factcheck_media_2026_10_25.py test_rc_target_media_evidence.py test_mca20_integration_round1045.py test_persistent_throttling.py test_direct_chat.py test_cfg02b_image_freq_limits.py test_cfg02c_image_isolation.py` | **403 passed** | `green-handlers-throttle.txt` |
| embed/persistent/evol/mca20 | `test_embed_*.py test_p0_embed_*.py test_persistent_throttling.py test_smartmodule*.py test_evol_fc_*.py test_mca20_*.py` (20 файлов) | **438 passed, 2 failed (pre-existing, см. §7)** | `green-broad-b.txt` |
| существующий LLM retry/backoff | `test_llm_client.py test_llm_circuit_breaker.py test_p0_llm_transport_258206.py` | **159 passed, 1 failed (pre-existing pin, §7)** | `green-llm-existing.txt` |
| мутации | `python raw/mutations.py` | **10/10 RED, unexpected=0** | `mutations.txt` |

## 7. Предсуществующие падения (доказаны на чистой базе)

Проверены в отдельном чистом worktree `release-2-58-272` на `fa4ba6292`; ни один
затронутый файл кандидата не участвует.

1. `tests/test_evol_fc_admission.py::TestScenario7InsufficientEvidence::test_insufficient_evidence_is_not_no_claim`
   — ожидает «недостаточно данных», получает технический заголовок «поиск недоступен»
   (рендер `technical_unverified`). `raw/pre-existing-base-fa4ba6292.txt`.
2. `tests/test_mca20_rework1_f1_f2.py::TestValidatorStage::test_evidence_injection_stays_data_not_instructions`
   — ожидает `&lt;/evidence&gt;` в payload; на базе тот же провал. Там же.
3. `tests/test_p0_llm_transport_258206.py::TestAdminContract::test_llm_guard_is_visible_policy_group`
   — жёсткий line-pin веб-файла (68272 < 67751); на базе тот же провал.
   `raw/pre-existing-base-llm-pin.txt`.

Кандидат эти падения не добавляет и не обязан исправлять (вне FCT-1001/1002).

## 8. Честные ограничения

- `run_retrieval(is_cancelled=...)` — существующий кооперативный хук; в
  оркестраторе у него нет продового вызывающего (нет реестра отмен — это была бы
  новая функция). Реальная прод-отмена — `asyncio.CancelledError` задачи handler'а;
  она покрыта новым тестом, включая возврат слота. Не выдаём хук за «включённый
  реестр отмен».
- Legacy-ветка при доставленном вердикте не пишет `kept:verdict` в телеметрию
  (слот просто не снимается; поведение верное). Это соседняя телеметрия, не
  требование FCT-1001; не менялась.
- Живой параллельный прогон на реальном Telegram/провайдерах не выполнялся
  (нет деплоя по границам). Детерминизм обеспечен тестовыми двойниками на границах
  (провайдер embed, LLM, БД-соединение) и реальными функциями продукта внутри.
- `test_p0_embed_empty_input.py` при прогоне 60 файлов один раз упёрся в
  pytest-timeout на teardown; отдельно и в разрезе 40+20 файлов проходит
  (925/438 зелёных). Классифицировано как среда/нагрузка, не как регрессия:
  файл не затрагивается кандидатом.
- Строка FCT-1001 в карте ссылается на кандидата `3a78484b9` и run
  `test_evol_fc_admission.py`; это историческое доказательство сохранено, новые
  evidence должны быть привязаны к `dc6703a8f` (или последующему tip с evidence).
