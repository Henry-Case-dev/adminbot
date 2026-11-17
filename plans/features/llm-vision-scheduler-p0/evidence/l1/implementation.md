# L1 — смена модели не должна ломать планировщик (implementation)

Задача: `llm-vision-scheduler-p0`, слайс **L1** (52 строки карты; код-слайс касается
LVS-L1-02/03/04/05/12/13/14/15/16/17/19/20/23/24/26/27/28/29/34/35/37).
База: **production 2.58.214 @ `ea9f760f`** (`release/mod-acl-w2b3-2.58.214`), rollback `34c25d09`.
Ветка: `fix/p0-l1-model-switch`. Статус: **implementation + локальные проверки; независимое ревью и деплой — отдельные гейты (не VERIFIED)**.

## Доказанная причина (recon `d6888161`, аудит `772dcf36`) и что изменено

| Факт на прод-логе | Причина в коде `ea9f760f` | Изменение |
|---|---|---|
| 09:27:43Z: HTTP 200, `finish_reason=length`, `in=6157 out=512`, content пуст → `LLMBadResponseError: empty content` → deterministic fallback, одна попытка | L1 всегда отправлял `max_tokens=512` (`l1_max_output_tokens()` код-дефолт) и парсил ответ тремя независимыми местами; обрезка/пустой content не различались и не исправлялись | общий нормализатор ответа + матрица исхода: `length`/reasoning-only → повтор с увеличенным бюджетом (не тот же payload); бюджет выводится из контракта JSON-плана + резерв reasoning |
| 09:44:03Z: `TimeoutError`, latency 15007 ms | внешний `asyncio.wait_for(15)` вокруг `llm.generate` (`direct_chat_service`) | внешний микролимит снят; дедлайн — действующая транспортная политика (180/360) как управляемая верхняя граница хода |
| «Effective L1: 15 s / 512 / context 1600 — code default» | `l1_timeout_seconds()`/`l1_max_output_tokens()` возвращали код-дефолты как «аварийный fallback» во всех ветвях | код-дефолты больше не применяются автоматически: только явный owner-override (PG/env), иначе наследование политики/контракта |
| 1M выдавался как `model_window` | `resolve_l1_context_budget` помечал окно `model_window` независимо от источника (`estimated_unknown`) | 1M остаётся **estimate**: `source=model_window_estimate`, `window_estimated=true`, `window_confidence=estimated`; проверенный предел (`proven_limit`) сильнее |
| dedicated-ключ мог уйти на чужой endpoint | `resolve_l1_model`: `api_key=key or main_key` при `base_url=base or main_base` | ключ принадлежит endpoint'у: чужой адрес без своего ключа → `key_slot='none'`, попытка не выполняется; тот же endpoint — наследование легитимно |

## Изменения по файлам

### `services/model_capacity.py`
- `CapacityResult` расширен аддитивно: `supports_reasoning` / `supports_tool_calling` /
  `supports_json_mode` (tri-state, `None` = не подтверждено), `output_token_field`
  (`max_tokens` | `max_completion_tokens`) и `output_field_source`; в `as_window_meta`
  добавлены `window_verified` / `window_estimated` и capability-поля.
- `catalog_capability_fields(item)` — единственный разбор capability из каталога
  (список строк, список объектов, словарь флагов, документированные поля output-лимита).
  Никаких списков имён моделей: только то, что объявил провайдер; отсутствие сигнала → `None`.
- `WINDOW_VERIFIED_SOURCES` + `window_is_verified(source)` — один предикат «окно
  подтверждено, а не оценено»; `CapacityResult.window_verified` / `.estimated`.
- `ModelCapability` + `model_capability(result)` + `resolve_model_capability(base_url, model)` —
  capability-снимок через **существующий** `resolve_capacity` (второго резолвера нет).
- `_adapter_nanogpt_entry` / `_adapter_openrouter_entry` отдают catalog item (нужен для
  capability), прежние обёртки сохранены.

### `services/llm_client.py`
- `classify_chat_response(data)` — **единый** чистый нормализатор: `text` / `tool_calls` /
  `reasoning_only` / `truncated_reasoning` / `empty` / `invalid_content` / `no_choices` /
  `provider_error` (ошибка внутри HTTP 200) / `invalid_payload`; content-строка, `null`,
  пустая строка и content-parts; `finish_reason` нормализован; reasoning **никогда** не
  становится `content` (только `reasoning_chars` в событиях).
- `classify_llm_failure(exc)` — классы отказа: `rate_limit` / `auth` /
  `incompatible_request` / `bad_request` / `context_overflow` / `server_error` /
  `timeout` / `deadline_exceeded` / `cancelled` / `bad_response` / `transport` / `no_key`.
- `incompatible_parameter(exc)` — какой request-параметр отверг провайдер (только при
  реальном 4xx и явном маркере «unsupported/unknown parameter», без угадываний).
- `usage_output_tokens(usage)` — `(completion_tokens, reasoning_tokens)` без выдуманных нулей.
- Переведены все три потребителя: `generate_with_metadata` (ошибка несёт
  `response_kind`/`llm_finish_reason`/`reasoning_chars`), `generate_chat`
  (`LLMChatResult.response_kind`, reasoning отдельно), `direct_l1.dedicated_generate`.
  `LLMCompletion` получил `response_kind`/`reasoning_chars` (аддитивно, defaults).

### `services/direct_l1.py`
- `l1_timeout_seconds()` / `l1_max_output_tokens()` → `int | None`: только **явно
  сохранённое** значение (PG-ключ или env-переменная). 15 s / 512 удалены как
  универсальный аварийный fallback во всех ветвях (main/dedicated/retry/repair/unknown).
- `L1RouteSnapshot` (frozen) + `resolve_l1_route(slot, llm)` — один immutable снимок
  маршрута на ногу хода: model / provider / endpoint(host) / key_slot / dedicated /
  per-attempt timeout / общий deadline / output field / output limit / reserve /
  источник каждого значения / окно и его уверенность / `supports_reasoning` / `usable`.
  `with_attempt()` и `with_output_field()` возвращают НОВЫЙ снимок (immutability).
- `l1_plan_output_budget()`: owner-override → иначе контракт JSON-плана
  (`L1_PLAN_OUTPUT_TOKENS=2048` + 25 % запас) + резерв reasoning
  (`L1_REASONING_RESERVE_TOKENS=2048`, если поддержка подтверждена **или неизвестна**),
  потолок — `max_output` модели из каталога, абсолютный предохранитель
  `L1_OUTPUT_CEILING_TOKENS=8192`; повтор — `attempt` увеличивает бюджет, не «тот же payload».
- `L1_MAX_CALLS_PER_LEG = 3` — не больше первичной попытки + двух РАЗНЫХ коррекций на ногу.
- `resolve_l1_model`: ключ не пересекает endpoint (`_same_endpoint`).
- `dedicated_generate`: `output_field` + `timeout_seconds` + общий нормализатор;
  результат — `L1Generation` (распаковывается как `(content, usage)`, несёт
  `response_kind`/`finish_reason`), поэтому существующие двойники/вызовы не ломаются.
- `next_l1_correction(...)` — матрица исхода (budget / output_field / drop_temperature /
  json-repair) с явным «не повторять» для 429/5xx/timeout/auth/context/cancel/provider-error.
- `build_repair_messages(..., reason=)` — своя аннотация для reasoning-only/truncation;
  reasoning в prompt НЕ переносится (прежний `invalid_json` — байт-в-байт).
- `resolve_failure_mode(...)` + `FAILURE_MODE_*`: ровно одна категория
  (success / compatibility_repaired / retry_success / provider_fallback /
  deterministic_fallback / failed); deterministic fallback не считается успехом.
- `emit_l1_plan_event`: те же события дополнены `failure_mode`, `finish_reason`,
  `output_limit`, `output_field`, `timeout_seconds`, `deadline_seconds`, `attempts`,
  `model`, `correlation_id`, `window_source`, `window_estimated` (R17: коды/числа).
- `record_l1_diagnostics` накапливает оси последнего прогона (адаптер хода дописывает
  свои оси ПОСЛЕ исполнителя; замена словаря теряла исход попытки — наблюдалось тестом).
- `resolve_l1_context_budget`: явный owner-override вместо 512; окно честно помечается
  `model_window_estimate`, когда источник — оценка.

### `services/direct_chat_service.py`
- `_execute_turn`: один резолв снимков на ход (`l1_slot` + `main`), ноги ladder'а как
  раньше; main-нога строится из ключей основной модели, а не из dedicated-слота.
- Внутри ноги: первичный вызов + до двух коррекций; причины переводятся в действия;
  каждая успешная попытка учитывается (`record_l1_usage`), отмена — управляемая
  (`CancelledError` → `l1_aborted`, проброс).
- Внешний `wait_for(15)` заменён верхней границей хода `route.deadline_seconds`
  (действующий транспортный бюджет) — одинаково для main- и dedicated-ноги;
  per-attempt HTTP-окно (180) применяет сам `_post` из действующей политики,
  поэтому разведение «per-attempt vs общий deadline» сохраняется.
- Метаданные хода: `l1_transport_timeout/deadline/source`, `l1_output_field/limit/reserve/source`,
  `l1_window_source/confidence/estimated`, `l1_supports_reasoning`, `l1_key_slot`,
  `l1_provider/endpoint/route_model`, `l1_failure_mode/attempts/finish_reason/failure_reason`.
- `l1_model` сохранил прежний смысл (модель dedicated-слота; main — модель клиента);
  резолв маршрута пишется отдельной осью `l1_route_model`.
- `_l1_usage_plan_meta` + `_TURN_DIAGNOSTIC_KEYS`: новые оси исхода доезжают до
  durable plan_meta/Inspector (существующие каналы; новых систем нет).

### `services/agentic_events.py`, `services/usage_events.py`
- `L1_PLAN` whitelist получил новые R17-safe поля; `PLAN_META_FIELDS` — durable-оси
  (`l1_failure_mode`, `l1_finish_reason`, `l1_failure_reason`, `l1_output_limit`,
  `l1_output_reserve`, `l1_output_field`, `l1_output_source`, `l1_attempts`,
  `l1_window_source`, `l1_window_confidence`, `l1_window_estimated`, `l1_timeout_source`).
  Числовые поля — в `_PLAN_META_NUM_FIELDS`. Вторая система наблюдаемости не создана.

### `services/param_catalog.py` (+ F8-артефакты)
- Только **описания** двух существующих ключей: `limits.direct_l1_timeout_seconds` и
  `limits.direct_l1_max_output_tokens` больше не утверждают 15 s/512 как норму
  (пусто = наследовать транспорт/контракт, значение = явный override). Δ каталога = 0:
  REGISTRY 645 / GROUPS 121 / TAB_BY_GROUP 119 / TAB_RULES 22 / delta 244.
- Прецедент CFG-03/SMART transport: TSV/meta переэмитированы генератором (`--check` OK),
  хэш переутверждён осознанно в `tests/test_round1025_f8_registry.py` (комментарий-запись)
  и `tests/fixtures/round1025/f8_baseline.json`; инструмент переиздания —
  `tools/_p0_l1_reissue_catalog.py`.

## Явные границы

- Выбор модели, промпты, флаги, Vision, scheduler, QRNG и UI-код не менялись
  (в админке — только честная подпись источника у существующих полей, без новых endpoint'ов).
- Реальный provider-вызов GLM 5.3 Uncensored **не выполнялся**: LVS-L1-31/32/37 —
  live_required, контролируемый live-check после деплоя (`real_provider_call.performed=false`).
- Аллокация L1-контекста для unknown-модели по-прежнему считается от 1M-оценки; изменена
  только честность её маркировки (изменение арифметики — строка LVS-L1-08 вне scope слайса).
- 54 предсуществующих падения affected-набора воспроизводятся на `ea9f760f` и не исправлялись.

## Review r1 (Needs Fixes на `ff2d11c4`) — точечные исправления

| # | Находка | Изменение | Доказательство |
|---|---|---|---|
| **D1** | `generate_chat` индексировал сырой `choices` после классификатора: `{"0": …}`/`5`/`{}`/`None` давали `KeyError`/`TypeError` мимо `LLMError`, и tool-раунд выходил из штатной деградации | сырой `choices` больше не индексируется; `finish_reason` берётся из классификатора (`finish_reason_raw`) | `TestRawChoicesShapes` (5 форм + текстовый путь): штатный `LLMBadResponseError`, `tool_loop` деградирует |
| **D2** | main-нога не передавала `route.output_field`; клиент всегда писал `max_tokens` — повтор мог 3× слать несовместимый payload | аддитивный `output_field` в `generate`/`generate_with_metadata`; main-нога передаёт поле маршрута; неизвестное поле → `max_tokens`; `max_output_tokens_sent` читает фактическое поле | `TestOutputFieldContract` (3 теста): payload, ход, повтор при 4xx «max_tokens не поддерживается» |
| **N1** | успешная main-попытка не имела finish_reason | main-нога идёт metadata-путём клиента, когда он доступен (узкие двойники — прежний `generate`); finish_reason/usage попадают в `L1_PLAN` и диагностику; `unknown` не затирает известную причину | `test_successful_main_reports_real_finish_reason` (`stop` в диагностике и событии) |
| **N2** | пропуск dedicated-ноги без ключа помечался `provider_fallback` | `provider_fallback` только после РЕАЛЬНОЙ неудачной попытки предыдущей ноги; пропуск = `success` + `l1_skipped_leg` (ось всегда свежая, по умолчанию `none`) | оба теста: skip→`success`, failed dedicated→`provider_fallback` |
| **N4** | provider/endpoint/key slot были только в Inspector | те же R17-safe поля добавлены в существующее событие `L1_PLAN` (`endpoint_host` — только host) | `test_event_fields_survive_whitelist` (+ отсутствие URL/ключа) |
| **N8** | тавтологичный `messages != []` | проверка payload-контракта: бюджет повтора = `min(ceiling, first*2)` и то же поле лимита | `test_length_truncated_empty_content_retried_with_budget` |
| **N7** | `affected-run.txt` chunk 240–280 без результатов | полный повторный прогон 324 файлов (30/chunk, без таймаутов) + сверка того же набора node-id с базой | `affected-run-r2.txt`, `affected-r2.json`, `affected-r2-base-compare.json` |

Дополнительно: главный путь `generate` теперь принимает `output_field` только
как additive kwarg; все прежние потребители (`tool_loop`, Summary, Factcheck,
Initiative) вызывают его без изменений. Двойники с узкой сигнатурой не ломаются:
`_supported_kwargs` передаёт лишь объявленные параметры.

Итог повторных проверок: 49 новых тестов, mandatory 386, focused 487/488
(1 предсуществующий), consumers 374, affected-набор 324 файла без таймаутов,
сверка node-id с базой `ea9f760f` — 58/58 и 0 candidate-only падений;
8/8 мутаций убиты (включая возврат сырой индексации `choices` и игнор `output_field`).
