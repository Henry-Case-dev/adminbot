# A2 `tool-chains-round1026` — Threat / Failure analysis (R3, ADR-1026-15 D10)

- **Epic-ID:** Эпик 3 «Agentic Intelligence» (Wave 2). **Feature-ID:** `tool-chains-round1026`.
- **Risk-Level:** **R3** (не понижен). Усиленные требования D10: (1) threat/failure-анализ
  с тестом на каждую угрозу; (2) rollback-доказательства; (3) расширенная
  adversarial-приёмка + diff-аудит.
- **Baseline:** HEAD `e8646af` == tag `pre-round1026-a2`; `APP_VERSION` 2.58.30.
- **Статус:** реализовано @Builder (T-3528…T-3544); ожидает независимого @Reviewer.
  **Deploy — `DEFERRED_TO_EPIC` (EPIC_ONLY).**

## 1. Угрозы → механизм защиты → тест

| # | Угроза (KG/§10.1) | Механизм (код) | Тест |
|---|---|---|---|
| T1 | **Infinite call loop** (`Risk-a2-infinite-call-loop`, Critical) | `TOOL_MAX_ROUNDS=4` (сохранён) + `TOOL_MAX_TOTAL_CALLS=6` (новый): перед каждым диспетчем cap → `skipped` + деградация `chain_call_limit`; цикл всегда завершается | `test_total_call_cap_six`; `test_adversarial_duplicate_storm` |
| T2 | **Дубликат-шторм** одинаковых вызовов | `_TOOL_MAX_SAME_CALL=2` по отпечатку `имя + json.dumps(sort_keys=True)`; сверх лимита — не диспетчится, возвращается прежний результат (`duplicate=true`, `attempt`), модель-видимый content прежний | `test_dedup_same_call_max_two`; `test_adversarial_duplicate_storm` |
| T3 | **Зависание тяжёлого вызова** | мягкий wall-clock `TOOL_CHAIN_TIMEOUT_SECONDS=360.0`; проверка на границах раундов и перед каждым диспетчем; **in-flight не отменяется** (`asyncio.wait_for` на цикл не навешивается) → тяжёлый одиночный вызов (300 c) не режется | `test_soft_timeout_does_not_cancel_inflight`; `test_timeout_skips_new_calls` (`MONKEY`) |
| T4 | **Взрыв расходов** | `TOOL_CHAIN_MAX_METERED_CALLS=4` для metered-набора (search/article/summarize/download/lore/image/transcribe); free/local не считаются; `worker_budget.image_calls` внутри `generate_image` не дублируется | `test_metered_call_limit_four`; `test_free_calls_not_cost_limited` |
| T5 | **Ложная деградация / регресс вне лимитов** | все §17-контроли внутри `if limits_on`; envelope — out-of-band (не меняет строки); OFF → путь baseline; при ON ниже лимитов деградации нет | `test_limits_off_no_cap`; `test_limits_off_does_not_change_model_visible`; весь baseline-набор `test_tool_loop.py`/`test_agentic_ai_round1020.py` |
| T6 | **Per-phrase / per-combination костыль** (`Risk-a2-phrase-hack-per-combination`, High) | нет обработчиков под фразу/пару: зависимости исполняет существующий многораундовый `tool_loop` (`tool_choice='auto'`); handoff A→B — общий `ctx.result_for(name)`; резолв ссылки — общий | `test_no_per_phrase_handler`; grep по `tool_loop.py`/`tool_router.py` (нет per-combination) |
| T7 | **Неструктурированный handoff** (`Risk-a2-unstructured-handoff`, High) | envelope на каждый вызов в `ToolLoopResult.tool_results` + `ctx.tool_results` (`status/data/error_code/error_type/truncated/metered/duplicate/attempt/args_fingerprint/out_chars`); модельно-видимый канал сохранён (гибрид D1) | `TestEnvelope::*`; `test_dependent_chain_a_then_b_sequential` |
| T8 | **Ошибка инструмента → общий отказ LLM** (D2) | исключение/`status:error` → envelope `error` + прежний «ОШИБКА …»/JSON для модели; цикл продолжается, fail-safe/деградация сохранены | `test_structured_error_does_not_kill_llm`; `test_structured_error_from_json_status`; `test_adversarial_mixed_errors` |
| T9 | **R17-утечка** (аддитивные логи) | в логи — только числа/коды/`error_type`/имена/длины/`source`; аргументы, URL, тексты, envelope не логируются; отпечаток — хэш | `test_no_payload_in_logs`; `test_degraded_log_r17_safe`; `test_fetch_article_url_not_logged` |
| T10 | **Регресс живого direct-чата** (`Risk-a2-live-chat-regression`, Critical) | OFF-путь байт-в-байт; 2-вызовность `await_count==2` не тронута (условие System 2 по `tool_trace` сохранено); `lore_compiled`-условия не менялись; `bot.py` — только DI-строка | `test_limits_off_does_not_change_model_visible`; `test_off_legacy_effective_canon_ten`; `tests/test_direct_two_call_round1022.py`; `test_two_call_condition_preserved` |
| T11 | **Дубль сервиса/extractor** | `fetch_article` reuse `WebContentExtractor.extract` через `ToolDeps.extractor` (инжект `_web_extractor` в `bot.py`), второй extractor/сервис не создаётся; `None` → структурный `service_unavailable` | `TestFetchArticle::test_service_unavailable_when_extractor_none`; diff-аудит (нет `WebContentExtractor()` вне `bot.py`) |
| T12 | **Неоднозначная ссылка** | `resolve_context_url`: 0 URL → `None`; ровно 1 уникальный → он; ≥2 разных в источнике → `None` (честный `no_url`), без угадывания | `test_resolve_context_url_ambiguous_returns_none`; `TestFetchArticle::test_no_url_is_honest_error` |
| T13 | **Битый URL / недоступный источник** | `extract_urls` (валидация/нормализация) + `_is_http_url`-семантика; пусто → `no_url`; каскад упал → `extract_failed`; таймаут → `timeout` — всё JSON, не исключение | `TestFetchArticle::test_extraction_failure_structured`, `test_fetch_article_timeout` |
| T14 | **Гигантский вывод** | усечение существующее (`_truncate`/`_dig_json_payload`) + `_ARTICLE_MAX_SYMBOLS=8000`; envelope честно несёт `truncated`/`out_chars` | `test_adversarial_huge_output_truncation_flag`; `test_truncated_flag_when_capped` |

## 2. Adversarial-приёмка (результаты, негативные сценарии)

Набор выполнен в `tests/test_tool_chains_round1026.py` (43 теста) + базовые файлы
`test_tool_loop.py` / `test_agentic_ai_round1020.py`.

| Сценарий | Ожидание | Тест | Результат |
|---|---|---|---|
| Шторм одинаковых вызовов (2/раунд × 4) | исполнено ровно 2, остальные `duplicate` | `test_adversarial_duplicate_storm` | PASS |
| Превышение суммарного cap | 6 исполнено, 7-й `skipped` → `chain_call_limit` | `test_total_call_cap_six` | PASS |
| Превышение платных вызовов | 4 исполнено, 5-й `skipped` → `chain_cost_limit` | `test_metered_call_limit_four` | PASS |
| Тайм-аут при in-flight тяжёлом вызове | вызов не отменён, результат сохранён, деградация мягкая `chain_timeout` | `test_soft_timeout_does_not_cancel_inflight` | PASS |
| Добор новых после дедлайна | 0 диспетчей, `skipped` → `chain_timeout` | `test_timeout_skips_new_calls` | PASS |
| Смешанные ошибки (один упал — второй жив) | оба envelope (`error`,`ok`), финал есть | `test_adversarial_mixed_errors` | PASS |
| Гигантский вывод + усечение | `truncated=true`, `out_chars` точны | `test_adversarial_huge_output_truncation_flag` | PASS |
| Битый/недоступный источник | JSON `error` (`no_url`/`extract_failed`/`timeout`), без исключения | `TestFetchArticle::*` | PASS |
| Неоднозначная ссылка | честный `no_url` | `test_resolve_context_url_ambiguous_returns_none`, `test_no_url_is_honest_error` | PASS |
| OFF/legacy | эффективный канон 10; ON/OFF модельно-видимые равны | `test_off_legacy_effective_canon_ten`, `test_limits_off_does_not_change_model_visible` | PASS |
| 2-вызовность | `await_count==2` сохранён | `tests/test_direct_two_call_round1022.py` | PASS |
| Инфинити-луп | цикл гарантированно завершается | `test_total_call_cap_six`, `test_adversarial_duplicate_storm` | PASS |

## 3. Rollback-доказательство (воспроизводимая проба)

**Hot-OFF:** env-only `TOOL_CHAIN_LIMITS_ENABLED=false` (+ `ARTICLE_TOOL_ENABLED=false`).
**Cold:** annotated-тег `pre-round1026-a2` → `e8646af` + `git revert`.

Воспроизводимая проба (модельно-видимая эквивалентность/эффективный канон):

```
.venv\Scripts\python.exe -m pytest \
  tests/test_tool_chains_round1026.py -k "off or legacy" -q
```

Покрывает:
- `test_limits_off_no_cap` — при OFF cap/тайм-аут/дедуп/расходы не применяются;
  причина деградации — прежняя `round_limit`; все envelope `ok`;
- `test_limits_off_does_not_change_model_visible` — ON vs OFF при неистощённых
  лимитах: `str(on)==str(off)`, `tool_context`/`tool_trace`/role:`tool`-content равны;
- `test_off_legacy_effective_canon_ten` — при `ARTICLE_TOOL_ENABLED=false`
  `active_tools(...)` возвращает ровно до-A2 канон **10** (байт-в-байт список
  baseline `e8646af`).

**Честная оговорка:** «байт-в-байт» доказано между OFF- и ON-ветвями одного и того
же кода (envelope out-of-band, строки не трансформируются). Отдельный прогон
baseline-кода в этой сессии не выполнялся; при OFF модельно-видимый список
инструментов и все строки совпадают с baseline, а новых LLM-вызовов не добавлено
(0 LLM в цепочке).

## 4. Diff-аудит (границы)

```
git diff --name-only pre-round1026-a2
```

Вне diff подтверждены: `services/image_generation.py` (§104), `services/summary_prompts.py`,
`services/prompt_migrations.py`, `services/param_catalog.py`, `db/**`, `web/**`,
`web/api/routes.py`, публикационные/`summary_*`-модули. Изменён `bot.py` — только
аддитивная DI-строка `extractor=_web_extractor` (санкционировано ADR-1026-15 D5,
проверено `git diff pre-round1026-a2 -- bot.py`: 5 insertions, 1 deletion).

`Δ DDL=0` (нет `CREATE/ALTER/DROP TABLE` в A2-источниках),
`Δ каталога=0` (469/426/444/100/98/21; `param_catalog.py` вне diff),
`APP_VERSION` не бампался (2.58.30 по D8).
