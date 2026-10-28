# REVIEW-FCPOST-W1 — независимое ревью W1 (architecture core)

Ревьюер: Reviewer (лейн REVIEW-FCPOST-W1), 28.10.2026.
Кандидат: `98a4254f` (ветка `task/fcpost-w1`), база `c987a825` (release/p0-2026-10-26, линия 2.58.138).
Ревью-worktree: `C:\Code\Python\adminbot-wt-fcp-rev` (detached 98a4254f).
Production: 2.58.138 — кандидат НЕ задеплоен.
Скоуп диффа: services/{factcheck_service,factcheck_orchestrator,factcheck_planner,factcheck_renderer,search_aggregator,temporal_factcheck}.py, handlers/factcheck.py, tests/* (11 файлов), plans/features/p0-factcheck-post-release/* (source/map/evidence). Параметры каталога/pg_db/routes НЕ менялись.

## 1. Обязательные проверки владельца (все пройдены)

| # | Guard | Результат | Доказательство |
|---|---|---|---|
| 1 | No fake positives §2.4/§2.5 | OK | Ветка «нет evidence → серверный insufficient» удалена; analyst вызывается всегда; `_downgrade_unbacked_positive` понижает supported/refuted/mixed и положительные parts без внешнего evidence и без `uncertainty.basis*` → `insufficient_evidence` + честная оговорка `unbacked_positive`; `allowed_refs=set()` при пустом evidence (было None) — выдуманные ev-N отбрасываются на top и parts (`verdict_from_payload` фильтр `is not None`); `<analysis_context>` — серверный текст (escape_xml_text), запрет выдуманных источников/характеристик, рамка происхождения вывода. Независимый probe (на кандидате): invented ev-99/ev-77 отфильтрованы; supported без basis → insufficient_evidence+маркер; supported с basis «расчёт» стоит; mixed → parts понижены. |
| 2 | Нет параллельного набора вердиктов §2.6 | OK | FACTUAL_VERDICTS/TEMPORAL_STATUSES/REASON_CODES без диффа; `RETRIEVAL_NO_RESULTS="no_usable_results"` — внутренний класс, в reason маппится на существующий `insufficient_evidence`; `unbacked_positive`/`basis` — ключи свободного dict uncertainty, не enum. |
| 3 | §2.2 не тронут | OK | Дифф-инспекция: при наличии evidence flow идентичен базе — analyst-вызов с теми же аргументами, `allowed_refs` тот же dict-comprehension, payload байт-идентичен (analysis_context="" → секция не добавляется), guard/reason-clear — no-op при evidence, validator не менялся. Изменения renderer/verbalizer для with-evidence — прямо предписаны §7.3/§7.4 (dedup, снятие принудительной композиции). |
| 4 | §4 guards | OK | Обязательные контракты не менялись (auth/изоляция/egress/attribution-сьюты зелёные); новых блокирующих стадий нет (удалена одна — серверный отказ при пустом evidence); fallback'и сохранены (каскад провайдеров, fallback-промпт LLM, детерминированный текст вербализатора, plain-renderer, доставка); частичные доказательства сохраняются при сбое следующего запроса (planner: continue + blocks, F5 PASS). |
| 5 | §6 кеш удалён полностью | OK | handlers: temporal read/write + early return + cache-hit run record удалены; legacy `cache.get/cache.set` slug `factcheck` + ранний return удалены. orchestrator: envelope read/write + cached-CheckedVerdict return удалены; legacy `cache.get` + возврат кешированного вердикта удалены; `write_legacy_cache`/`_v2_cache_input` удалены. temporal_factcheck: cache_components/build_temporal_cache_key/freshness_bucket_for/freshness_ttl_seconds/temporal_cache_key_with_bucket/read/write_temporal_cache удалены. grep-аудит кандидата: `build_key("factcheck"` = 0; `get_update_marker` в фактчек-контуре = 0; `cached` в фактчек-файлах = 0; `cache_hit=True` в проде только postgen_vision (идемпотентность другой подсистемы, §6.2). Границы сохранены: SmartCache suitability/context (handlers:272,482), исторические record_temporal_run + миграция v33 + web routes runs, already_delivered + кулдаун, кеши других подсистем. |
| 6 | §5 таксономия | OK | Причины машинно различимы: `AllSearchEnginesFailedException.reason` (provider_error/timeout/empty_results/irrelevant_results/budget), `level_failure_reason`, `_most_informative_reason` (irrelevant>empty>timeout>provider_error); planner: пустая выдача → `empty_results` (не provider_failures), причина в логе `cause=`; `classify_retrieval`: empties/irrelevant>0 → RETRIEVAL_NO_RESULTS («ответили, но отфильтровано» ≠ «недоступны»), search_failed — только чистая недоступность. Relevance-фикс: floor=1 только при len(seen)==2 (≥3 терминов — прежний floor=2, ≥20% порог сохранён) — ложные отрицания снимаются; мусор не открывается: фильтр грубый лексический, окончательное решение за аналитиком. Словарей синонимов/доменных хардкодов нет (дифф-инспекция). |
| 7 | §7 вербализация | OK | Содержательный ответ проходит целиком (renderer: принудительный список 2–4 пунктов удалён, body passthrough); пустой анализ → короткий `limit_note` (без универсального правила длины — условие `not _verdict_is_substantive`); dedup: при техзаголовке концовка `_TECHNICAL_NOTICE` не добавляется (`not technical`); FREQUENT/Core-шов `speech_owner_block` не тронут (service:1759); обязательной композиции нет; fallback-текст сохраняет разбор частей при отказе вербализатора. |

## 2. Прогоны (на кандидате, локально, без сети/LLM/Telegram)

| Прогон | Результат |
|---|---|
| `tests/test_factcheck_post_release_w1.py` (новый F-матрикс) | 37 passed |
| `pytest tests -k "factcheck"` | 559 passed, 0 failed |
| `tests/test_factcheck_media_2026_10_25.py` | 53 passed |
| `test_mca20_temporal_round1044.py + round1045 + test_smart_cache.py` | 86 passed |
| `py -3 -m compileall services handlers` | EXIT 0 |
| `py -3 tools/gen_param_registry_round1025.py --check` | EXIT 0 («реестр 588 == REGISTRY») |
| `tests/test_mca20_rework1_f1_f2.py` | 18 passed, 1 failed — `test_evidence_injection_stays_data_not_instructions` (pre-existing: файл идентичен базе, diffstat пуст; anti-injection контракт выполняется, устаревший ассерт экранирования) |
| `tests/test_param_catalog.py` | 2 failed — stale-пины (466 vs 467 Settings; counts) из-за +1 NOSTALGIA_HISTORY_DEPTH_YEARS параллельной лейки NOST-REWORK-W2; test_param_catalog.py/param_catalog.py/fixtures идентичны базе (diffstat пуст) → pre-existing, домен NOST-REWORK-W2 |

## 3. Находки

Блокирующих нет. Отложенные/несвязанные:

1. `deferred-coordinated` (§6.3): гейт `mca_gates.temporal_factcheck_cache_enabled` оставлен (0 вызовов в проде — инертен) + stale docstring K1/K3, stale note `mca_process_registry.py:1299-1301`, флаг-ось `module_registry.py:603`, мёртвые TTL-настройки, slug `factcheck_temporal` в smart_cache.py:53, stale-комментарий handlers/factcheck.py:693. Очистка — один micro-лейн после NOST-REWORK-W2 (домен param_catalog), явно записана в evidence билдера §5. До закрытия родителя обязательно.
2. `pre-existing` (домен NOST-REWORK-W2): пины каталога 587 vs 588 — см. §2; финализация той лейки обязана обновить артефакты/пины.
3. `pre-existing` флейк `test_asap8_initreply_binding.py` (несидированный pseudorandom fallback) — вне фактчека, в backlog.
4. `LIVE_UNVERIFIED` (честно помечено билдером): реальная частота ложных отрицаний relevance-фильтра и фактическое поведение LLM с `<analysis_context>` — проверяемы только на живых прогонах (домен §11 owner-report/postdeploy, моки доказательством не являются).
5. `cross-lane`: дословная директива §8 (FC-08) — своя лейка; правило (1)/(7) TEMPORAL_ANALYST_SYSTEM уже согласовано минимальной правкой, конфликтов нет.

## 4. Вердикт

**Approved** — W1 (architecture core) кандидат `98a4254f` проходит независимое ревью: все обязательные guard-проверки владельца подтверждены, деградаций и скрытых кеш-путей не найдено, обязательные контракты §4.2 сохранены, честные LIVE_UNVERIFIED-маркеры не подменены статическими.

Родитель NOT DONE: остаются волны S8 (директива §8), §6.3-очистка (после NOST-REWORK-W2), релизный деплой + postdeploy-проверки и FC-11 (отчёт владельцу). Binding: любое изменение кода/конфига кандидата инвалидирует это ревью — повторная проверка по изменённым швам.
