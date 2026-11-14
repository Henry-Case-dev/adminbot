# FC live-canary — 2.58.203

Харнесс: `fc_live_canary` **v1.4.0**, sha256
`afcd6ee00ffe332cf64503e7ec05e9845483f73e7745627fe910763a7776e3f1`
(закреплённый; preflight внутри каждого прогона `requested=true, ok=true`).
Код прода: `c97c06e4` / 2.58.203 (`deployed_sha` в binding совпадает,
`version_provenance consistent=true`, `dirty=false`).
Все прогоны — свежие, без переиспользования прежних доказательств; каждый
пишет собственный JSON в `raw/`.

Безопасность: `telegram_bot_is_stub=true`,
`real_telegram_bot_constructed=false`, `real_chat_history_written=false`,
синтетический чат; в чаты владельца ничего не отправлялось
(`outbound_delivered_to_telegram=0`).

## 1. Прогон A — `original_production_scenario`, cap 20 (закреплённый)

```
started/finished   2026-11-14T19:00:23Z / 19:01:02Z (36.2 s)
status             not_observed
evidence_class     unavailable
summary            provider_cap_reached (harness measurement budget exhausted:
                   cap=20, total=20, denied_charges=3, kinds=llm,llm,llm; the
                   pipeline could not reach the answer stage — this is NOT a
                   product verdict)
call_budget        llm=1, search=8, page_fetch=11, total=20, remaining=0,
                   cap_reached_this_run=true, cap_denied_calls_this_run=3
```

Это не вердикт о продукте: бюджет харнесса израсходован на поиск/фетчи до
стадии ответа (в этом прогоне 11 попыток `safe_fetch`, из них часть —
`too_many_bytes`/`safe_fetch_timeout`). Кап 20 после FC-анкера стал
маргинальным (см. §4).

## 2. Прогон B — `original_production_scenario`, свежий, cap 40

```
started/finished   2026-11-14T19:03:02Z / 19:04:53Z (109.1 s)
status             observed
evidence_class     production
production_evidence true
summary            Исходный production-сценарий воспроизведён: вопрос о странах
                   исследован (материальный анкер в поиске), стадия ответа
                   выполнена, дан ответ по evidence (честный отрицательный
                   ответ допустим)
call_budget        llm=4, search=6, page_fetch=6, total=16, remaining=24,
                   cap_reached_this_run=false, cap_denied_calls_this_run=0
```

Ключевые предикаты (все `true`):

```
material_kept                     true
user_question_identified          true
search_built_from_question        true
relevant_sources_researched       true
no_old_budget_early_stop          true
answer_stage_completed            true
direct_answer_on_question         true
answer_not_a_harness_echo         true
ambiguity_acknowledged            true
bundle.answer_stage.fallback_used false
bundle.answer_is_fallback_template false
bundle.material_anchor_usage.anchor_used true
bundle.no_prebaked_country_list.prebaked_list_used false
run.retrieval.budgets_enabled     false        (бюджеты OFF, ранней остановки нет)
run.cap_reached                   false
run.budget_blocked                false
```

То есть SFC-12-09 воспроизведён на 2.58.203: поиск строится из вопроса
пользователя с материальным анкером, стадия ответа доходит до конца, ответ —
по evidence, не шаблон-fallback, без предзаготовленного списка стран.

## 3. `production_smoke`, свежий, cap 12

```
started/finished   2026-11-14T19:05:59Z / 19:06:45Z (43.9 s)
status             observed
evidence_class     production
production_evidence true
summary            Production smoke: identity/health сходятся, короткий фактчек
                   дошёл до ответа
call_budget        llm=3, search=2, page_fetch=2, total=7, remaining=5,
                   cap_reached_this_run=false
```

Все identity- и run-утверждения `true`: `git_head_present`,
`manifest_present`, `manifest_sha_matches_head`, `deployed_sha_matches_head`,
`app_version_matches_manifest`, `health_200`, `health_version_matches`,
`v2_pipeline_effective`, `answer_delivered`, `route_recorded`,
`not_timeout_answer`, `provider_cap_reached=false`,
`provider_budget_insufficient=false`, `safety.real_chat_history_written=false`.
Переиспользование прогона при cap 24 не потребовалось
(`SMOKE_RERUN_NEEDED=n`).

## 4. Находка: закреплённый cap 20 для `original_production_scenario`

Прогон A честно упал в `provider_cap_reached` при `cap=20`: после FC-анкера
запрос стал шире, и стоимость поиска/фетчей в этом сценарии достигла 19
не-LLM вызовов до стадии ответа. Внутренняя таблица харнесса
(`check_call_costs.original_production_scenario=14`,
`min_calls_per_check=17`) это больше не покрывает при неудачных фетчах.

Что сделано: получен чистый вердикт свежим прогоном с cap 40 (§2), cap не
исчерпан (16/40). Что НЕ сделано и не должно считаться закрытым: пин «20» в
принятом контракте канарейки остаётся недостаточным — это вопрос
конфигурации измерения (не продукта), его должен подтвердить Reviewer/PM
(предложение: cap ≥ 40 для этого сценария, либо пересчёт `check_call_costs`
с учётом анкера).

## 5. Прочие наблюдения прогонов

- `identity_code=local_unverified` в JSON харнесса — контекст вызова
  (`collect_identity` без `process_started_at`), а не дефект прода: штатная
  проверка identity даёт `verified_deployed` (см. `identity.txt`).
- В stdout прогонов видны `[humor-feedback] lessons read failed`
  (`AttributeError: 'NoneType' object has no attribute 'db'`) — это отсутствие
  БД в синтетическом контексте харнесса, не прод-ошибка.
- Провайдер `nano-gpt.com` давал `ReadTimeout` (2 retry за окно) и в прогоне A
  часть `safe_fetch` не удалась (`too_many_bytes`/timeout) — внешняя
  изменчивость, зафиксирована как наблюдение, не как дефект релиза.

Сырые JSON: `raw/fc_original_203.json` (A), `raw/fc_original_b_203.json` (B),
`raw/fc_smoke_203.json`, `raw/fc_dry_203.json` (dry-run).
