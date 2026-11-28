# P0T-REPLY-01 — implementation (смысловая цель reply в Direct)

- Роль: Builder. Дата: 2026-11-28.
- База: `74ef57ef4` (2.58.273, прод), ветка `feat/p0t-reply-01-2026-11-28`.
- Кандидат: см. `tip.txt` (коммит этой ветки; деплой/push не выполнялись).
- Архитектурная памятка: `../architecture.md` (эта же папка).

## 1. Decision → файлы

| Решение памятки | Файл | Что сделано |
|---|---|---|
| §1 R4: две замены в секции участия, инструкции не сокращаются | `services/chat_prompts.py` | `_DIRECT_L1_PARTICIPATION_R4 = _R3.replace(…)` ровно с двумя заменами: снято «этот вызов относится к инициативе»; «из текущего окна» → «из предоставленного контекста (окно или сообщение текущего хода)». `_R3`, `_W1`, `BASE_R3` заморожены. |
| §2 слепок + пересборка активного канона | `services/chat_prompts.py` | `PREV_DIRECT_L1_PLANNER_P0GM = DIRECT_L1_PLANNER_SYSTEM_PROMPT` (байты прода 2.58.273, sha12 `ce6931304b24`); активный канон = `PREV…P0GM.replace(_R3, _R4)`. Проверено: это ровно одна замена секции, дельта +12 символов, `sha12 = 64a80fb8c4ff`. |
| §2 лестница forward + rollback | `services/prompt_migrations.py` | верхняя forward-ступень `(P0GM → active)`; вторая ступень исправлена на `(P0GM → EVR6)`; верхняя rollback-ступень `(active → P0GM)`. Старые ступени не переписаны; новых PG-ключей нет. |
| §2 метка/печать/FACTORY_SET в одном коммите | `services/prompt_registry.py` | метка `l1-planner-delivery-scope`, печать `64a80fb8c4ff`, `FACTORY_SET_SHA256_12 = 1c03efc3e98b` (вычислено `factory_set_fingerprint()`, не угадано), история «changed = 1». `seal_integrity() == {}`. |
| §3 предикат «план — решение модели» | `services/direct_l1.py` | `plan_delivery_is_semantic(plan)`: `source in ("llm","repair")`; пустой/неизвестный/None → `False` (консервативный паритет). Рядом с `reply_binding_requested`, экспортирован в `__all__`. |
| §3 seam доставки | `services/direct_chat_service.py` | `_reply_target = message.message_id` (паритет); для `l1_plan` с source llm/repair `_reply_target=None`, при `reply_binding_requested` — существующий `_validate_plan_target(mode="reply")`. Цель недоступна → plain send, причина `code` в INFO-лог, **без** перепривязки к триггеру и **без** отмены. `_send_direct_answer(..., _reply_target, …)`. |
| §1 следствие: id в Direct-L1 контексте | `services/direct_l1.py`, `services/direct_chat_service.py` | `_plan_direct_l1` → `with_ids=True` (тот же формат, что инициатива). `build_l1_context` bounded-сканом уже загруженного окна ставит `[msg:<smart_messages.id>] ` перед секциями `СООБЩЕНИЕ`/`ОТВЕТ НА` (P0-сообщения исключены из окна); не найден → без префикса (fail-open, второго запроса в БД нет). |

Чего нет: новых флагов, таблиц/DDL, событий, второго LLM-вызова, новых резолверов,
изменений `reply_binding_requested`/`_validate_plan_target`/инициативного пути,
изменений `services/search_aggregator.py`/`temporal_factcheck.py`/`factcheck_service.py`/
throttling S4/рендера.

**Осознанно не меняется** (как в §3 памятки): `remember_bot_reply(parent_tg_message_id=…)`
и `ledger.parent_message_ref` остаются на триггере (память о причине хода), а также
deferred-media шов `resume_deferred_evidence` (C3 диагноза).

## 2. Тесты

### Обновлённые пины (осознанно; часть уже была красной на базе)

- `test_direct_l1_l1d_contract.py` — реконструкция активного канона через R3→R4; контракт
  «доставка только для инициативы» заменён на новый + позитивные проверки формулировок;
  rollback-голова с P0GM.
- `test_asap_w1_semantics.py` — активная секция R4, R3 больше не в каноне.
- `test_asap_speech_r3b_canon.py` — метка, реконструкция канона, rollback-цепочка.
- `test_p0_prompts_core.py` — литерал набора `1c03efc3e98b` (пин фактический; поглотил и
  более раннюю U1-дельту, baseline уже расходился: 10efa51a8dae vs bd06a8a1a782).
- `test_asap2_clar_contract.py` — метка L1, R4, rollback-цепочки L1/L2 (последние были
  устаревшими уже на базе), проверка сохранности delivery-контракта.
- `test_prompt_migrations.py` — верхняя rollback-цель L1 = P0GM; активные байты L1.
- `test_rlr_acceptance_rows.py:902` — план без `delivery` больше не даёт привязки:
  проверяется «ни один чанк без reply» (смысл теста — чанкинг/типографика — сохранён;
  привязка с целью покрыта новым файлом).
- `test_evol_evidence_routing.py`, `test_p0_goal_media_2026_11_25.py`,
  `test_post_asap5_w1_writer_core.py`, `test_post_asap5_w2_tech_reasoning.py`,
  `test_speech_p0_corrective_l1_route.py`, `test_asap_fc_voice_l1_decision_profile.py`,
  `test_evol_w17_small_canon_reqs.py`, `test_expression_isolation_followup.py` —
  метки/sha12/rollback-голова/`FACTORY_SET_SHA256_12`.
- `test_soul1_composer_parity_off.py` — stub `_l1_reply_block` получил keyword-only
  `preserve` (сигнатура прода); это была причина baseline-падения P4, не правка эталона.
  Дамп-фикстура НЕ перезаписана: `_canon_patch` детерминированно заменяет исторический
  EVR0 на активный канон, поэтому P4 сравнивает именно новые байты (R4) и после починки
  stub'а GREEN. Перезапись дампа удалила бы исторический пин, ничего не усиливая.

### Новый детерминированный файл `tests/test_p0t_reply_target.py` (15 тестов)

Реальный `DatabaseService` (`smart_messages` с `tg_message_id`), fake LLM (`l1_planner` →
подставленный план), fake bot, реальный `_send_direct_answer`:

1. окно «аудио (триггер) + фото другого автора + обложка»: цель плана = фото → первый
   send имеет `reply_to_message_id == tg(фото)`;
2. тот же кейс длинным ответом: reply только у первого чанка;
3. `delivery=chat` → без привязки;
4. `delivery` отсутствует → без привязки;
5. цели нет в БД → plain send (не триггер), `target_missing` в логе;
6. цель в чужом чате → plain send;
7. цель устарела (10 суток при окне `limits.summary_window_hours`) → plain send;
8. `target_user_id` не совпадает с автором цели → plain send;
9. план указывает row-id триггера → привязка к tg-id триггера;
10. `source=fallback` (LLMError) → reply на триггер;
11. L1 OFF (`l1_plan is None`) → reply на триггер;
12. контекст: `[msg:id]` окна + `[msg:id]` у `СООБЩЕНИЕ` и `ОТВЕТ НА`;
13. `with_ids=False` → прежний формат без `[msg:]`;
14. инициатива (нет P0-id) → секция `СООБЩЕНИЕ` байт-паритетна;
15. предикат: llm/repair → True, fallback/""/garbage/None → False.

## 3. Команды и результаты

Все прогоны — локально, venv проекта, из корня worktree; provider-вызовы не выполнялись,
реальные сообщения не отправлялись. Артефакты — только строки `FAILED/ERROR` + итог;
машинная сверка наборов падений к базе — `raw/regression-set-compare.txt`.

| Прогон | Кандидат | База 74ef57ef4 |
|---|---|---|
| новый файл `tests/test_p0t_reply_target.py` | **15 passed** (`raw/candidate-new-suite.txt`) | **10 failed / 5 passed** (`raw/baseline-new-suite-red.txt`) — контрактные кейсы красные на базе |
| пины (16 файлов: canon/sha12/метки/rollback/fixture/expression) | **354 passed, 5 failed** (`raw/candidate-pins.txt`) | **350 passed, 9 failed** (`raw/baseline-pytest.txt`); candidate-only падений = 0, 4 baseline-падения закрыты осознанным обновлением пинов |
| Direct/OK-батч (22 файла: asap7/8, decision, p0b, epic33/37, direct_chat*, mca23, bgs02, rlr…) | **920 passed, 16 failed** (`raw/candidate-batch-direct.txt`) | **16 failed / 4 passed**, набор идентичен (`raw/baseline-batch-direct-pair.txt`) |
| reply-батч (24 файла: addtr, image, tool_calling, ur_f, asap5_w3, native_reply, ur/unified…) | **651 passed, 15 failed** (`raw/candidate-batch-reply.txt`) | **15 failed** тем же набором (`raw/baseline-batch-reply-pair.txt` + `…-others.txt`) |
| контекст/бюджеты L1 (11 файлов: er08, ur_context, ur_10, caps…) | **289 passed, 1 failed** (`raw/candidate-batch-context.txt`) | **1 failed** тот же (`raw/baseline-batch-context.txt`, `Asap3FakeDB`) |

Оставшиеся 5 падений пинового набора — предсуществующие и не связаны с правкой:
`asap2_clar_contract::test_33/test_24` (FakeDB/записанный дамп), `asap_fc_voice…
::test_direct_service_l1_payload_gets_profile_from_turn_frame` (stub без `preserve`),
`soul1_composer_parity_off::test_p1/test_off_path` (записанный дамп L2).
Отдельно: `test_evol018_prompt_audit::test_grep_audit_counts_are_stable` (331 vs 323
файла) и `test_soul1_registry_completeness::test_registry_consumer_pointers…`
(`lore_worker.py:709`) — оба воспроизведены на базе, к этой задаче не относятся.

Шесть сверяемых sha12 цепочки L1 (все пины обновлены; `raw/verify-canon.txt`):
active `64a80fb8c4ff`, P0GM `ce6931304b24`, EVR6 `619290834387`,
EVR5 `2354a5cc57c4`, EVR4 `8d172f40241d`, EVR3 `ef61a9dd6798`;
далее неизменные EVR2 `09f3d533d173`, EVR1 `eb496e938c49`, EVR0 `14743d288ea3`.

Baseline на 74ef57ef4 (до правок) для пинового набора: 9 падений, в т.ч. устаревший
`FACTORY_SET` (10efa51a8dae vs фактический bd06a8a1a782) и stale-метки L2.

## 4. Мутации (каждая обязана упасть)

`raw/mutations.py` (бэкап → замена → прогон → восстановление в `finally`; не тест),
вывод `raw/mutations.txt`:

| Мутация | Результат |
|---|---|
| M1: убрать гейт `plan_delivery_is_semantic` (всегда триггер) | **RED** — падают кейсы 1-4 |
| M2: выбирать последнее сообщение окна вместо цели плана | **RED** — цель = обложка 504 вместо фото 502 |
| M3: убрать фильтр `chat_id` в проверке цели | **RED** — чужая цель проходит |
| M4: не ставить `[msg:id]` у P0-сообщений | **RED** — кейс контекста |
| M5: убрать fail-soft (вернуть триггер при неудаче) | **RED** — кейсы 5/7/8 |
| M6 (бонус, канон): не применять R3→R4 в активном каноне | **RED** — пины канона |
| восстановление после мутаций | GREEN: 15 passed |

## 5. Байт-паритет (проверки)

- `l1_plan is None` / L1 OFF → reply на триггер (тест 11); `source=fallback` → reply на
  триггер (тест 10). Диф кода: изменён только аргумент единственного вызова
  `_send_direct_answer`; для `l1_plan=None` значение то же (`message.message_id`).
- Clarify-ветки (`:7163`, `:7806` до правки) не тронуты — там прежний
  `send_chunked_reply(..., message.message_id)`.
- Инициатива не тронута: `build_l1_context` получает те же параметры (без P0-id) →
  префиксы не добавляются (тест 14); `reply_binding_requested`/`_validate_plan_target`
  байт-в-байт.
- Deferred-media шов `resume_deferred_evidence` не входит в диф (`raw/product.diff`).
- lore/rich/deep_research: логика ветки и транспорт не менялись — меняется только
  входной `reply_to` (единое правило доставки, §3 памятки).
- `remember_bot_reply(parent_tg_message_id=message.message_id)` не менялся.
- Канон: `seal_integrity() == {}`; `factory_set_fingerprint() == 1c03efc3e98b`;
  `is_known_canon(active)` и `is_known_canon(P0GM)` — True; откат снимает только R4
  (`raw/verify-canon.txt`).

## 6. Что осталось непроверенным (честно)

1. **Фактический выбор модели** (называет ли она `delivery=reply` и какую цель в живом
   много-медиа ходе) — недетерминирован; детерминированные тесты проверяют исполнение
   подставленных решений. Это соответствует BOUNDED ACCEPTANCE, но live-наблюдение
   остаётся за агентом после выката.
2. Effective-канон в проде (PG-значение прода `ce6931304b24` уедет на `64a80fb8c4ff`
   первой ступенью) не проверялся — деплой не выполнялся.
3. Полный прогон 265 файлов Direct-связанного среза не завершён: срез упирается в
   медленный/зависающий участок окружения (~12% за 40 минут, pytest-timeout срабатывает
   на постороннем тесте). Вместо него прогнаны батчи, покрывающие все изменённые точки
   (см. §3), с побайтовым сравнением наборов падений к базе.
4. `lore`/`rich`/`deep_research` проверены рассуждением по дифу и общими тестами
   транспорта, отдельного нового теста на каждый рендер-путь не добавлялось (входной
   `reply_to` один и тот же).
5. Хвост `[msg:id]` при экстремальном усечении секции: `clip_body` сохраняет голову,
   поэтому префикс переживает кап; отдельный стресс-тест не добавлялся.
