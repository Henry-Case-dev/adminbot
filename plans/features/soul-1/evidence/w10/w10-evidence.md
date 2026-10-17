# SOUL-1 / W10 — Capability Awareness & Tool Grounding: evidence

**Slice:** W10 (SOUL-AMD.0.4, 5.1–5.18, 7.5, 8.6–8.11)
**Baseline:** рабочее дерево поверх `4c8405e7` (соседняя полоса позже закоммитила incident-fix `e4bb51d8`; изменения W10 не закоммичены)
**Owner §5 source:** `plans/features/soul-1/source-architectural-clarification.md`
**Scope:** `services/{direct_capabilities,direct_chat_service,image_generation,tool_router,chat_prompts,prompt_registry,capability_registry}.py`, `tests/test_soul1_capability_*.py`, this directory.

## 1. Что реализовано (карта)

| Требование | Реализация | Тест |
|---|---|---|
| 5.1 semantic intent → capability | `direct_capabilities.detect_action_intent` (`:245`), `ActionIntent` (`:222`), `intent_blockers` (`:336`) | `test_soul1_capability_intent.py` (30) |
| 5.2 runtime capability registry | `capability_registry.CapabilityState` (`:82`), `resolve` (`:519`), `invalidate` (`:146`), `record_outcome` (`:173`), `capability_view` (`:604`) | `test_soul1_capability_registry.py` (19) |
| 5.3 truthful self-knowledge | `capability_registry.status_message` (`:737`), `notice_block` (`:766`); детерминированный гейт `DirectChatService._image_capability_gate` (`direct_chat_service.py:6264`) | `test_soul1_capability_fallbacks.py` (40) |
| 5.15 fallback phrase removal | `image_generation._image_error_block` (`:1891`), `_record_image_outcome` (`:1870`), `tool_router._generate_image` (`:3005`), шаблоны `chat_prompts.IMAGE_FAILURE_*` (`:502–546`), регистрация `message.image_failure.*` + `message.image_request.clarify` (`prompt_registry.py:500+`) | guard-тесты + mutation |
| 5.10 L1 consistency check | `DirectChatService._l1_capability_consistency` (`:6326`), вызов `:2806`; блокер `REASON_NOT_READY` (`direct_capabilities.py:51`) через `_l1_tool_subset(denied=…)` (`:4055`) | `test_six_phrases_call_tool_exactly_once`, `test_semantic_phrase_routes_after_l1_plain_text` |
| 5.17 single chain / delivery | существующие `run_image_request`/`generate_and_send` (переиспользованы), replay-ветка `delivery="already"` (`image_generation.py:1836`), `last_result=delivery_failed` | `test_success_but_send_failure_never_claims_sent`, `test_budget_lifecycle_once_per_intent`, `test_tool_skips_when_intent_already_handled` |

## 2. §8 сценарии — результаты (call counts)

Команда: `.venv\Scripts\python.exe -m pytest tests/test_soul1_capability_intent.py tests/test_soul1_capability_registry.py tests/test_soul1_capability_fallbacks.py -q` → **102 passed**
(37 intent + 24 registry + 41 fallbacks).

| Сценарий §8 | Что проверено | Результат |
|---|---|---|
| 8.6 «Бот, нарисуй …» (regex fast-path) | 1 вызов генерации, блок `status="ok" delivery="sent"`, image-инструмент на ход не анонсируется | PASS (`test_regex_fast_path_generates_and_confirms_delivery`) |
| 8.6 остальные 5 формулировок §5.1 | 1 вызов генерации каждая, 0 второго LLM-вызова, инструмент не дублируется | PASS (6× `test_six_phrases_call_tool_exactly_once`) |
| 8.7 «придумай концепт/текст мема, не рисуй» | 0 генераций, обычный ход | PASS (2× pipeline + 3× detector) |
| ложные срабатывания | «давай обсудим мемы», «расскажи про мемы», «сделай кратко» и др. генерацию не запускают (ложный вызов дороже пропуска) | PASS (6× `test_non_creation_requests_do_not_trigger_generation`) |
| 8.7 неоднозначное («Бот, сделай это») | ровно 1 вопрос из `message.image_request.clarify`, 0 генераций, 0 LLM-вызовов | PASS |
| 8.8 OFF / нет ключа / провайдер / квота | 4 разных текста из `message.image_failure.*`, 0 генераций, 0 LLM; `temporarily_unavailable` — по наблюдаемому `timeout` | PASS |
| 8.9 успех + сбой send | `reason=send_failed`, текст про доставку, «отправлено» не заявляется, `last_result=delivery_failed` | PASS |
| 8.9 дубли | pre-gate+L1+tool-loop → 1 вызов; `image_request_handled` → `skipped`, 0 вызовов; один commit квоты | PASS |
| 8.10 модуль / override / провайдер | статусы + `capability_view` + L1 `available_capabilities` следуют за runtime; чаты изолированы | PASS |
| 8.11 не-image (поиск) | недоступная capability не обещается: `<capability_notice>` в промпте Writer'а + событие trace | PASS |

## 3. Статусы (реальные источники, `w10-dump.json`)

| Сценарий | status | reason_code | detail |
|---|---|---|---|
| гейты пройдены | `ready` | — | `image_limit_ok` |
| модуль OFF | `disabled` | `module_disabled` | `image_module_off` |
| нет ключа | `not_configured` | `image_provider_unconfigured` | `key_absent` |
| лимит выбран | `quota_exhausted` | `financial_limit_reached` | `image_daily_limit` |
| наблюдаемый `timeout` | `temporarily_unavailable` | `provider_unavailable` | `timeout` |
| схема инструмента отсутствует | `unsupported` | `tool_absent` | `schema_absent` |
| неизвестное имя | `unknown` | `unknown_capability` | `not_in_registry` |

Различение «объявлен / можно попробовать / вызов завершён»: `declared` / `tryable` / `last_result` (+`RESULT_DELIVERY_FAILED` при сбое отправки).

## 4. Удаление захардкоженной фразы (SOUL-AMD.5.15) — доказательство

* `IMAGE_GENERATION_FALLBACK_PHRASE` больше не встречается в `services/tool_router.py` и `services/direct_chat_service.py` (тест `test_user_path_files_do_not_reference_legacy_constant`);
* исходник пользовательских функций `maybe_handle_keyword` / `_generate_image` / `_image_error_block` не содержит константу (`test_hardcoded_phrase_is_out_of_user_path`);
* поведенческий щит: ни один код отказа не выдаёт фразу (`test_legacy_phrase_never_reaches_the_user`, `test_pre_gate_block_uses_template_by_code`, 12 кодов);
* константа остаётся только заводской редакцией исторического слепка (реестр `message.image_generation_fallback`, не рендерится).

### Мутации (проверка, что тесты ловят возврат дефекта)

| Мутация | Падение |
|---|---|
| убран routing-fix после L1 | `test_six_phrases_call_tool_exactly_once[Бот, сделай мем …]` FAILED |
| фраза возвращена в пре-гейт | 4 guard-теста FAILED (в т.ч. `test_hardcoded_phrase_is_out_of_user_path`) |
| убран детерминированный отказ по статусу | `test_module_off_replies_disabled_template` FAILED |
| сбой доставки помечен успехом | `test_success_but_send_failure_never_claims_sent` FAILED |

## 5. Стоимость и parity

* **0 дополнительных LLM-вызовов**: отказ по состоянию capability отправляется детерминированно (тесты требуют `llm.calls == []`); routing-fix не добавляет вызов (`l1_planner` ровно 1).
* **0 сетевых probes**: `capability_registry` не делает I/O; кеш TTL 60 c + `invalidate` при смене конфигурации + автоматический сброс при подмене слоёв конфигурации (тесты `test_cache_hit_does_not_touch_sources`, `test_config_change_invalidates`, `test_config_cache_swap_invalidates_without_waiting_ttl`, `test_ttl_expiry_rechecks`).
* **Parity**: обычные сообщения (без поручения действия) не получают ни новых блоков, ни иных решений — `user_blocks` дополняются только при распознанном поручении; OFF-ветки композера/флагов не менялись (`test_soul1_composer_parity_off.py` зелёный). Изменение ТЕКСТА ошибки генерации — санкционированное SOUL-AMD.5.15 (обе ветки kill-switch `UNIFIED_IMAGE_REQUEST_ENABLED`); путь генерации/бюджета/доставки не изменён.

## 6. Trace (реальные строки, R17-safe, без секретов)

```
[direct] capability not ready | chat=-100500 | cap=image_generation | status=temporarily_unavailable | reason=provider_unavailable | template=message.image_failure.temporarily_unavailable
mca_event=capability_check | outcome=failed | component=capability_registry | status=temporarily_unavailable | entity_id=image_generation | reason_code=provider_unavailable
mca_event=capability_message | outcome=failed | component=capability_registry | entity_id=message.image_failure.temporarily_unavailable | status=temporarily_unavailable
[direct] capability routing fixed | chat=-100500 | cap=image_generation | l1_capabilities= | reason=create_image_command | blockers=-
mca_event=capability_check | outcome=success | component=capability_registry | status=ready | entity_id=image_generation | trace_id=9a9b3911…
agentic_event=L1_CAPABILITY_REJECTED | capability=image_generation | reason=available_action_not_chosen | run_id=9a9b3911…
```

Цепочка «намерение → capability → check → call → result → delivery» видна в trace; случаи «доступное действие не выбрано L1» помечены явно (§6.5).

## 7. Полный прогон и известная флейки-семья

| Прогон | Результат |
|---|---|
| `pytest tests/ -v -p no:randomly` (фиксированный порядок, все файлы W10) | **13923 passed, 1 failed** (11:51) — `test_handle_initiative_cancelled_by_recheck` |
| `pytest tests/ -q -p no:randomly --ignore=tests/test_soul1_capability_*.py` (контроль без W10) | **13822 passed, 0 failed** (11:47) |
| `pytest tests/ -q` (случайный порядок, все файлы W10) | **13923 passed, 1 failed** (11:28) — ДРУГОЙ тест того же файла (`test_handle_initiative_sent_single_transport_chunks`) |
| `pytest tests/test_soul1_capability_*.py tests/test_mca09_...py` (W10-файлы ПЕРЕД mca09) | **117 passed** |
| `pytest tests/test_mca09_...py` изолированно | **15 passed** |

Падения в полных прогонах — только в `tests/test_mca09_intents_block_e_round1040.py`
(каждый раз РАЗНЫЙ тест того же файла), **известная timing-flake** проекта
(`plans/backlog.md:239`: «1 срыв из 3 полных прогонов на идентичном дереве
(изолированно зелёный); pollution-семья §121, related-nonblocking»; ср.
`plans/archive/asap5-final-fixes-round1049/integration_evidence.md:119`,
`plans/archive/asap-4-...-round1030/review.md:413`).

Механизм (установлен по коду и логу): `services/mca_random_source.py:2246`
держит ПРОЦЕССНЫЙ синглтон `_service`, который биндится к первому реальному
`DatabaseService` за прогон; после закрытия его tmp-БД (teardown того теста)
любой поздний потребитель получает `aiosqlite: no active connection` →
`handle_initiative` fail-open → ассерт падает. Порядок прогона решает, кто
«свяжет» синглтон.

Причастность W10 проверена отдельно: ни один файл
`tests/test_soul1_capability_*.py` не использует `DatabaseService`,
`mca_random_source`, `get_service` или `tmp_path` (grep — пусто), а прогон
«W10-файлы ПЕРЕД mca09» зелёный (117 passed).

**Решающая проверка:** тот же периметровый прогон (`-k "…mca…"`) с ИСКЛЮЧЁННЫМИ
файлами W10 (`and not capability_intent and not capability_registry and not
capability_fallbacks`) → **5445 passed, 1 failed** — снова mca09, но ТРЕТИЙ
разный тест (`test_candidate_ready_defers_intent_backoff`). То есть флейк
воспроизводится БЕЗ файлов W10 и каждый раз в другом тесте того же файла →
к W10 не относится. Классификация: `related-nonblocking` / `pre-existing`
(документировано в backlog как timing-flake mca-09, pollution-семья §121).

**Независимое подтверждение:** соседняя полоса (incident-fix `e4bb51d8`, другое
подмножество файлов) в своём полном прогоне тоже наблюдала «13910 passed/1 failed
(order-dependent flake, reproduced with a changing victim; unrelated to the
incident)» — та же флейка, другая жертва.

Тот же класс нестабильности объясняет единственный срыв прогона с
`--timeout=120 --timeout-method=thread` (известное зависание ~72–77%, ср.
L-ASAP4-9): контрольный `-v`-прогон без timeout завершился полностью.

Сводка полного прогона сохранена: `w10-full-suite-summary.txt`.

## 8. Известные границы (честно)
1. **MiniApp-редактирование** шаблонов доступно через API реестра (`prompt_factory.write_speech_value`/`apply_factory_reset`/история, PG-ключи `content.image_failure.*`, `content.image_request_clarify`); ключи каталога `content.*` и UI-редактор — слайс W6 (Δ каталога = 0, см. отчёт).
2. **UI-витрина «Возможности бота»** — данные готовы (`capability_view`), рендер — W6 (`web/**` вне scope).
3. **Live/preprod** проверки §8.6–8.11 (реальный провайдер, реальный Telegram) в этом слайсе не выполнялись: провайдер и Telegram замоканы по заданию. Пункты помечены `READY_FOR_LIVE`, не `DONE`.
