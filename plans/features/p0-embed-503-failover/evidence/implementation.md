# P0-EMBED-503-FAILOVER — реализация failover (2026-11-22)

Ветка: `fix/embed-503-failover` от deployed `374dc60609986a9250170a34a48c93bf2ba85e29`
(2.58.228). Кандидат: `4ace0a3ae52c321edfd2ef425d933198b6d08377`.
Owner input: `plans/owner_inputs/2026-11-22-p0-embed-503-failover.md`,
sha256 `d23bf6f96c69e8ddd1537a07f8f203fbf434b0022f693e5368a64c8731828f09`
(по `plan.md`; intake-карта `requirements-map.json`).

Покрываемые требования: `E503-FAILOVER-01`, `E503-IDENTITY-01`,
`E503-RECOVERY-01`, `E503-DIAG-01`. `E503-ROUTE-01` выполнен DevOps на
master (`f2540ac60`, `evidence/live-route-2026-11-22.md/.json`) — здесь не
дублируется и не переизмеряется.

## 1. Подтверждённый дефект (RED)

На deployed `374dc6060`:

- `EmbeddingExecutor._pick_credential()` брал первый `healthy` credential;
- `_on_error()` для 5xx/timeout возвращал `transport` и **намеренно не**
  менял credential/group health;
- цикл `embed()` после transport-ошибки снова звал `_pick_credential()`, а
  поскольку primary оставался healthy, все ≤4 попытки уходили в primary.

RED-тест `test_primary_5xx_does_not_burn_all_attempts` на базе:
`['k-primary', 'k-primary'] == ['k-primary', 'k-fb1']` — ожидаемый fallback
не вызывался. Полный RED-лог: `tests-red-base-2026-11-22.txt`
(6 failed, 4 passed; в т.ч. все три ноги, recovery/probe и реальный
route-admission кейс).

Live-подтверждение (внешнее evidence DevOps): 503 приходил от
`primary → https://apinet.cloud/v1/embeddings`, model
`gemini-embedding-001`, quota group `apinet_paid`; journal 24 h: 844
`embed transport error`, 973 `LLMServerError`, 219
`EmbeddingRetriesExhausted`, 43 apinet+503, 0×429/401. Fallback_1/2 в тот же
момент отвечали 200, vector 3072, MSI `e540d4ad890e121d`,
cosine fallback_1~fallback_2 = 1.0.

## 2. Фикс

`services/embedding_control_plane.py`:

1. **Per-operation exclusion.** `embed()` ведёт `excluded: set[alias]` и
   `_pick_credential(pool, excluded)`; 5xx/timeout-нога не повторяется в
   текущей logical operation. `_mark_transport_failure()`:
   - если после исключения есть другая пригодная нога — failover сразу;
   - если в операции уже отказала другая нога — последняя тоже исключается;
   - единственная живая нога (single-credential пул) сохраняет прежний
     bounded retry/backoff и `_ATTEMPT_BUDGET=4` (тест
     `test_single_credential_keeps_bounded_retry`).
2. **Короткая парковка, не второй breaker.** Отказавшая нога паркуется в
   **существующем** `QuotaGroupRegistry.credential_health`
   (`HEALTH_COOLDOWN`, `_PROVIDER_UNAVAILABLE_COOLDOWN_S=60 c`). Пока park
   активен, запросы не бьют шлюз; после истечения следующий logical request
   снова пробует ногу (probe-recovery) — `test_primary_recovery_probe_after_cooldown`.
   Новый retry-менеджер/breaker/очередь не создавались.
3. **Диагностика.** Логи различают:
   `embed transport error | alias=... | provider=... | error=...`,
   `embed leg unavailable | alias=... | provider=... | cooldown_s=60.0`,
   coalesced `embed fallback served | alias=...`, и route-admission
   `SmartModule: fallback embed route not admitted — fact stays text-only`.
   Ключи не логируются (R17).
4. **Фактическая нога для write-path.** `_LAST_SERVED_CREDENTIAL`
   (contextvar, только alias/provider/model/base_url/quota_group) +
   `last_served_credential()`; `summary_memory._embed` сбрасывает provenance
   перед logical embed, чтобы cache-hit/legacy не наследовали чужой маршрут.
5. **Route-aware допуск существующим гейтом.** В
   `resolve_index_compat()` добавлены опциональные
   `space_now/conn_now/model_now` overrides (default — прежний configured
   primary identity). `MemoryManager._serving_route_write_allowed()`
   перепроверяет фактическую connection через тот же
   `resolve_index_compat`: писать в ACTIVE можно только при
   `serviceable && state=compatible`; иначе `COMPATIBILITY_UNKNOWN/
   INSUFFICIENT/INCOMPATIBLE` → `text-only + FTS`. Это применяется к
   `_save_graph_fact_embedding`, `_save_archive_embedding` и обоим
   backfill'ам. Вектор fallback-ноги **не кладётся в `embedding_cache`** под
   configured identity, иначе последующий cache-hit обошёл бы гейт.
6. **421/429/401 не изменены.** 429 по-прежнему уважает group cooldown
   (`test_429_respects_group_cooldown_and_next_group`); 401/403 помечает
   только свой credential и не выводит независимые слоты
   (`test_auth_error_does_not_park_independent_slots`); отсутствие всех
   ключей — один legacy-вызов и понятная ошибка
   (`test_all_keys_absent_is_single_legacy_refusal`).

Почему затронут `summary_memory.py`: только write-path знает индекс и имеет
БД для существующего admission-резолвера; control plane не может проверить
допуск per-index. Изменение не вводит новый гейт/DDL/флаг — используется
существующий `resolve_index_compat` и текущие generation/admission/MSI/
canary-поля.

## 3. Identity и реальный Google-кейс

Live evidence: Google-слоты функционально отдают vector 3072, MSI
`e540d4ad890e121d`, но formal admission для Google PCI (`6b7e…`/`6348…`)
= false; admission привязан к apinet PCI (`a934…`), gate даёт
`COMPATIBILITY_UNKNOWN`. Кандидат **не объявляет** Google admitted по имени
модели.

Тест `test_5xx_fallback_write_blocked_until_existing_admission`:
primary (group `apinet_paid`) 503 → fallback_1 (group `google_free_1`) 200;
`_vec_write_allowed` для configured primary проходит, но route-aware гейт
даёт `insufficient / COMPATIBILITY_UNKNOWN / serviceable=false` →
факт сохранён в `graph_facts` + FTS, `graph_facts_vec=0`, fallback-вектор не
закэширован. После записи durable-допуска **для фактической Google
connection** тот же гейт возвращает `compatible` и запись проходит (тест
доводит до `graph_facts_vec=1`). Это существующий admission-контракт, не
новый.

Совместимость/incompatibility доказывается существующими
`test_scenario_03_same_name_different_space_is_incompatible`,
`test_scenario_04_dimension_mismatch_never_mixes`,
`test_new_write_after_adopt_is_searchable` (все passed); при
несовместимости `_vec_write_allowed` остаётся false → text-only. Мутация
«отключить identity-гейт» ломает scenario_03 (см. `mutations-2026-11-22.txt`).

## 4. Recovery

Действующие `embed_recovery_tick`, `backfill_archive_vectors`,
`backfill_graph_fact_vectors` не переписаны; добавлен только route-admission
перед INSERT. E2E
`test_all_legs_down_saves_text_only_then_recovers_backfill`: все три ноги
503 → факты в FTS без векторов; после восстановления primary backfill
пишет 2 вектора, повторный backfill возвращает 0 и не дублирует строки.
Существующие recovery/backfill тесты passed:
`test_e4_backfill_probe_without_read_traffic`,
`test_e4_reprobe_recovers_vec_without_reads`,
`test_20_all_facts_saved_text_only`,
`test_embed_fail_fact_saved_text_only`.

Прод-backlog из live evidence (graph missing eligible **4 463**, recent 24 h
**1 187**, `facts_text_only=143`) этим кандидатом не пересчитывался и не
объявляется восстановленным; после деплоя его должен подхватить штатный
`embed_recovery_tick` при восстановлении admitted-провайдера.

## 5. Тесты и мутации

Команда (585 passed, 0 failed/errors/skipped):
`tests/test_p0_embed_503_failover.py`, `test_embedding_control_plane_asap4`,
`test_embed_fallback_slots_routing`, `test_asap8_f8_embeddings`,
`test_embed_identity_compat`, `test_embed_identity_compat_restart_legacy`,
`test_asap5_embedding_identity`, `test_asap6_embedding_generations`,
`test_soul1_w7_embedding_primary_slot`, `test_summary_memory`,
`test_llm_client`, `test_asap44_graphrag_batch_breaker`,
`test_graphrag_memory`, `test_mca17_summary_instrumentation`,
`test_asap8_v6_p1_d09_memory` с `--timeout=180`.

Машинный отчёт: `tests-final-2026-11-22.json` (585 testcases, полный список
outcomes). Сырой вывод: `tests-final-2026-11-22.txt`.

Ключевые GREEN-ассерты:

- primary 5xx **и** timeout → `[k-primary, k-fb1]`, адреса/модели слотов
  собственные;
- все три ноги 503 → каждый независимый alias по одному разу, затем
  `EmbeddingRetriesExhausted`; все три в cooldown; немедленный повторный
  запрос не делает HTTP-вызовов;
- cooldown истёк → следующий запрос снова пробует primary и succeeds;
- single credential → 4 bounded попытки (budget не изменён);
- 401 → `auth_failed` только primary, fallback_1 остаётся healthy и
  обслуживает следующий запрос; 429 → group `cooling_down`, следующий
  независимый слот;
- реальный кейс: failover на Google + `COMPATIBILITY_UNKNOWN` → text-only,
  FTS-hit есть, fallback-вектор не в кэше; durable admission фактической
  Google connection → запись допускается;
- all three down → backfill после recovery + идемпотентность.

Мутации (файл `mutations-2026-11-22.txt`):

- отключить per-operation exclusion → `test_primary_5xx...` падает:
  `['k-primary','k-primary'] != ['k-primary','k-fb1']`;
- отключить `_vec_write_allowed` (identity-гейт) →
  `test_scenario_03...` падает `assert True is False`;
- отключить route-admission → реальный кейс падает
  `assert 1 == 0` для `graph_facts_vec` (недоказанный Google-вектор
  записан).

## 6. Diff / ограничения

Кодовый diff (`git diff --name-only 374dc6060..4ace0a3ae`) = ровно 3 файла:

- `services/embedding_control_plane.py` (failover, provenance, resolver
  override);
- `services/summary_memory.py` (route-aware write admission; обосновано выше);
- `tests/test_p0_embed_503_failover.py` (10 тестов, включая e2e).

Evidence-файлы лежат отдельно в этом каталоге (`plans/features/
p0-embed-503-failover/evidence/`).

Не изменены: `config/**`, `handlers/**`, `web/**`, DDL/схема, `APP_VERSION`,
модель `gemini-embedding-001`, существующие эмбеддинги/индексы, настройки и
ключи владельца, `plans/progress_scope.json`, `plans/workflow_state.md`.

Ограничения / внешнее:

- Деплой и live embed smoke этим lane не выполнялись (запрещены SSH/LLM/
  production). `E503-ROUTE-01` покрыт внешним DevOps evidence на master
  `f2540ac60`.
- apinet 503 остаётся внешним отказом; «apinet починен» не заявляется.
- Formal admission Google PCI остаётся недоказанным; кандидат не фабрикует
  его и не объявляет по имени модели. Пока `resolve_index_compat` для
  фактической Google connection не вернёт compatible, fallback-векторы
  остаются text-only + FTS. Доказательство (canary/probe/admission) — задача
  существующего identity-контура, не этого P0.
- `_serving_route_cache` TTL 60 c: новый durable admission подхватывается с
  задержкой до 60 c (bounded, не блокирует восстановление).
- `smart_archive source_empty/superseded` — отдельная проблема, не
  HTTP 503, в этом кандидате не лечится.
- При одном промежуточном комбинированном прогоне без pytest-timeout
  наблюдался hang в teardown `test_graphrag_memory`; изолированный файл
  (181 passed) и повторный полный прогон с `--timeout=180` (585 passed)
  проблемы не воспроизвели; к продуктовому коду не отнесено.
