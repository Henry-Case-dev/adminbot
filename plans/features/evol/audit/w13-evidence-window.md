# W13 — Dynamic Evidence Window, source fetch/chunking, claim-bound reuse (P0)

**Фича:** `ASAP-EVIDENCE-ROUTING-01` v3 (§3 Retrieve/Preserve/Observe, §4.5 Reuse, §2 аудит лимитов P0).
**Ветка:** `evol/impl` @ `57081925`; worktree `…/evol-71536a366a11-c63f6f44` (изменения не закоммичены — lane-отчёт).
**Полоса (exclusive):** `services/tool_router.py`, `services/web_content_extractor.py`, новый `services/source_reuse.py`,
`services/model_capacity.py` + `services/auto_budget.py` (только расширение), `tests/test_evol_evidence_window.py`.
Не тронуто: `direct_chat_service.py`, `direct_execution.py`, `evidence_policy.py` (другая полоса), `factcheck_*`, `mca_vision`,
`media_readiness`, `web/**`.

Цель пункта: убрать 4000/8000 как «потолок качества», сделать окно evidence динамическим от реального окна модели,
дать честный section-aware fetch с достижимым остатком и claim-bound reuse источника (не Smart Cache ответов).

---

## 1. Лимиты: что снято/переведено в динамику (класс E → dynamic)

| # | Файл:строка (до) | Было | Стало | Класс |
|---|---|---|---|---|
| 1 | `tool_router.py:91` | `_SEARCH_MAX_SYMBOLS = 4000` как потолок выдачи **и** повторный `_truncate(text, 4000)` | одна содержательная упаковка по индексу кандидатов; лимит = `auto_budget.resolve_evidence_tool_window("search")` → `max(SEARCH_RESULT_SOFT_FLOOR, budget×1.25)`; 4000 остался **нижним полом** и legacy-дефолтом (`LEGACY_SEARCH_MAX_SYMBOLS`) | **E → dynamic** (floor 4000, C-ceiling 200 000) |
| 2 | `tool_router.py:131` | `_ARTICLE_MAX_SYMBOLS = 8000` как потолок документа | извлечение до `article_extract_ceiling()` (дефолт 120 000, hot `limits.article_extract_ceiling_chars`), затем **section selection** по терминам claim в бюджет окна; 8000 — только legacy-дефолт | **E → dynamic** (C-ceiling 120 000 добыча, доставка — по окну) |
| 3 | `tool_router.py:715–720` | `_truncate` = `text[:limit].rstrip()+"…"` (слепой срез) | граница слова/токена (`clip_at_boundary`), валидный JSON не режется, URL не разрывается; наблюдаемый конверт `Truncation` (`effective_limit/source/used/total/truncated/why/retrievable_remainder/unit/candidates_*`) | **E → structural** |
| 4 | `web_content_extractor.py:114,243–246` | `extract()` режет документ до `max_symbols` | reader отдаёт ДОКУМЕНТ (`extract_document`) без среза доставки; технический ceiling помечается `truncated_at_extraction`; старый `extract(url, max_symbols)` сохранён как preview-обёртка (D-класс, `web_summarizer_service`) | **E → dynamic** |
| 5 | `web_content_extractor.py:185` | `include_links=False` → ссылки первоисточника исчезали | ссылки берутся из того же HTML отдельным безопасным списком (`_extract_links`: только http(s), без credentials, dedupe, ≤40); `links_source="html"`/`"unavailable"` честно | **E → fixed** |
| 6 | `web_content_extractor.py:35` | `_MIN_CONTENT_CHARS=150` = «отказ уровня» → ложный «источник недоступен» на коротком changelog | порог решает только «пробовать следующий уровень»; короткая валидная страница → `status=ok, short_content=true` | **D/E → honest status** |
| 7 | `tool_router.py` (новое) | — | суммарные tool-результаты одного хода ≤ `TOOL_EVIDENCE_TURN_SHARE` (0.40 окна), `turn_capped` наблюдаем | **C (новый предохранитель)** |

Сохранено без изменений (класс A/B/C): `safe_fetch` SSRF/размеры/redirect, `_SEARCH_TOOL_TIMEOUT=25`, `_ARTICLE_TOOL_TIMEOUT=45`,
лимиты памяти/истории/медиа, `TOOL_RESULT_HARD_CEILING` (используется как страховка от лавины), финансовые/суточные бюджеты.

### 1.1 Измеренные effective-значения (этот worktree)

| Источник лимита | Окно | `search` | `article` | `source` |
|---|---|---|---|---|
| активная модель (`deepseek-v4-flash` → `model_map`) | 131 072 ток. | 104 857 симв. | 104 857 симв. | `window` (`window_source=model_map`) |
| неизвестная модель (`unknown_fallback`) | 16 384 ток. | 13 107 симв. | 13 107 симв. | `window` (`window_source=unknown_fallback`) |
| per-call бюджет композера = 1 000 | — | 4 000 (soft floor) | 1 250 | `call_budget` |
| per-call бюджет = 4 000 | — | 5 000 | 5 000 | `call_budget` |
| per-call бюджет = 20 000 | — | 25 000 | 25 000 | `call_budget` |
| динамика OFF (`EVIDENCE_WINDOW_DYNAMIC_ENABLED=false`) | — | 4 000 | 8 000 | `legacy` (байт-в-байт прежнее) |

Доли: `limits.evidence_tool_window_share` = 0.20 (на вызов), `limits.evidence_tool_turn_share` = 0.40 (на ход),
`limits.tool_result_hard_ceiling_chars` = 200 000, `limits.article_extract_ceiling_chars` = 120 000.
Символы считаются как `tokens × 4` (существующая оценка проекта), ровно **один** резерв вывода (C4, см. §5).

---

## 2. Что реализовано (по файлам)

### `services/model_capacity.py` (расширение)
`EVIDENCE_WINDOW_SHARE_DEFAULT`, `chars_for_tokens`, `evidence_window_share`, `evidence_window_for_tokens`,
`resolve_evidence_window_tokens` (sync, registry/env/fallback уровня D1), `evidence_window_dynamic_enabled`.
Ничего существующего не менялось: discovery/`resolve_capacity` (async) остаётся источником для композера.

### `services/auto_budget.py` (расширение)
`EvidenceToolWindow` + `resolve_evidence_tool_window(kind, call_budget_chars, input_budget_tokens, model, hard_ceiling,
turn_spent_chars)`; `article_extract_ceiling()`; константы `SEARCH_RESULT_SOFT_FLOOR=4000`,
`TOOL_RESULT_HARD_CEILING_DEFAULT=200000`, `ARTICLE_EXTRACT_CEILING_DEFAULT=120000`, `EVIDENCE_TOOL_BUDGET_GROW=1.25`,
`TOOL_EVIDENCE_TURN_SHARE_DEFAULT=0.40`, `LEGACY_*`. Формула ровно из контракта §4.3; `output_reserve_tokens` в подписи
**отсутствует намеренно** (C4).

### `services/web_content_extractor.py`
`ExtractedDocument` (text/short_content/links/links_source/published_at/published_at_source/total_chars/ceiling/
truncated_at_extraction/levels_tried), `extract_document(url, ceiling=…)`; `Excerpt`, `split_sections`,
`select_excerpt(text, budget_chars, terms, section, offset)`, `build_source_pointer`, `clip_at_boundary`,
`content_terms`, `_extract_links`, `_extract_published_at`.
Каскад trafilatura → tavily → exa сохранён (один fetch-контур, `safe_fetch` первым), облачные уровни честно отдают
`links_source="unavailable"`. Compatibility: `extract(url, max_symbols)` работает как раньше (preview), подменённые
уровни-функции, возвращающие только текст, поддержаны.

### `services/source_reuse.py` (новый, без сети/БД/LLM)
`ClaimKey`/`claim_key` (единый канон: **делегирует** `evidence_policy.ClaimKey`, если он есть; иначе локальный с тем же
дайджестом `sha1(entity|relation|version|date|metric)[:16]`), `claim_key_from_mapping`, `claim_class_for`,
`ttl_seconds` (live_market 900 c / release_news 6 ч / spec 7 сут / docs 14 сут / historical 30 сут, hot-override),
`SourceRecord`, in-memory LRU (`limits.evidence_reuse_max_entries`, дефолт 256), `store/lookup/mark_contested/
record_delivery/clear/stats/reset_stats`, `reuse_line`, `read_level_from_payload`, `link_claim_source`,
`build_coverage`, `delivery_state`. Kill-switch `EVIDENCE_REUSE_ENABLED` (OFF → lookup всегда miss, записи не создаются).
Уровни чтения: `discovered|snippet|fetched|parsed|selected`; reuse засчитывается только для прочитанных и **только после
реальной доставки** (`delivered_chars>0`). Честное ограничение: после рестарта процесса кеш пуст → обычный fetch.

### `services/tool_router.py`
`ToolContext.evidence_budget_chars` (per-call бюджет композера) и `ToolContext.evidence_limits` (out-of-band журнал
лимитов); `Truncation`, `_truncate` (структурная, без разрыва URL/JSON) и `_compact_search_candidates` (индекс
кандидатов: все URL сохраняются, сжимаются только сниппеты; если не влезают даже `title+url` — остаток уходит
списком URL), `_evidence_window`, `_record_limit`, `_claim_keys`, `_reuse_bypass`, `_reuse_search`, `_article_terms`.
`execute_web_search`: агрегатору отдаётся **технический** ceiling (не 4000), поэтому ровно один содержательный лимит —
структурный; повторный claim → возврат без сети (`0 network_calls`).
`fetch_article`: `extract_document(ceiling)` → `select_excerpt` (terms/section/offset) → payload с прежними ключами
(`status,url,source_id,chars,truncated,markdown[,title]`) + `excerpt_chars,line_range,selected_by,sections,
sections_total,remainder_chars,budget_chars,budget_source,effective_limit,window_source,capacity_source,
full_source_pointer,read_level,total_chars,extraction_ceiling,extraction_ceiling_source,truncated_at_extraction,
short_content,provider,source_kind,published_at,published_at_source,links,links_source,latency_ms`; при ошибке —
`reason` (`no_url|service_unavailable|deadline_exceeded|source_unavailable|destination_blocked|no_relevant_results`)
и `retryable`. Существующий `full_source_pointer.call` подсказывает следующий вызов (`offset`).

Пример конверта (реальный прогон, 30 кандидатов, per-call бюджет 1200):
```
effective_limit=4000 limit_source=call_budget used=3994 total=10448 truncated=True
why=over_window_snippets_compacted retrievable_remainder=6454 unit=blocks
candidates_total=30 candidates_kept=30 source_read_level=snippet
```
Пример статьи (документ 45 101 симв., нужный раздел на 25 045, per-call бюджет 2000):
```
chars=excerpt_chars=111 total_chars=45101 remainder_chars=19998 selected_by=terms
line_range=[3,9] full_source_pointer{tool=fetch_article, offset=25103, total_chars=45101}
read_level=selected budget_source=call_budget effective_limit=2500
→ повторный вызов с offset=25103: selected_by=offset chars=2495
  full_source_pointer.offset=27598 remainder_chars=17503
```

---

## 3. Сценарии §10 ТЗ (подмножество этой полосы) → тесты

| Сценарий | Что доказывает | Тест (`tests/test_evol_evidence_window.py`) |
|---|---|---|
| **36** URL после 4k | цель на позиции 25 присутствует, все 30 URL целы, конверт наблюдаем | `test_url_after_old_4k_cut_is_reachable`, `test_compacted_index_keeps_all_urls_and_marks_truncation`, `test_small_window_keeps_all_urls` |
| **37** раздел после 8k | `selected_by=terms`, `line_range`, `full_source_pointer`, `remainder_chars>0`; остаток догружается тем же инструментом (`offset`) и указатель движется вперёд | `test_section_after_8k_is_delivered_with_provenance`, `test_remainder_retrievable_by_same_tool`, `test_sections_listed_with_line_ranges` |
| **38** большое окно | лимит > 4k, полный текст доставлен; C4 (нет двойного резерва); лимит не «16k/32k» | `test_big_window_allows_more_than_legacy_ceiling`, `test_no_double_output_reserve`, `test_search_large_window_derived_from_model_not_fixed_16k_or_32k` |
| **39** малое/unknown окно | claim→source сохранён, JSON/URL не разрезаны, overflow → retrieval, причины наблюдаемы, unknown помечен | `test_small_window_keeps_claim_source_and_urls`, `test_json_payload_never_sliced`, `test_clip_at_boundary_keeps_url_whole`, `test_unknown_window_is_marked_and_conservative`, `test_window_honours_hard_ceiling`, `test_turn_level_avalanche_guard` |
| **30** reuse того же claim | 0 новых сетевых вызовов (и в search, и в fetch), Writer получает ту же выдержку | `test_same_claim_reuses_source_without_new_call`, `test_search_skips_network_when_claim_reused` |
| **31** смена версии/даты/метрики, контрдоказательство, TTL, scope | новый ключ → новый fetch; `contested` не отдаётся; TTL истёк → miss; bypass; изоляция чатов; LRU-bounded; рестарт | `test_changed_version_does_new_fetch`, `test_metric_and_date_are_part_of_key`, `test_counter_evidence_blocks_reuse`, `test_ttl_expiry_and_bypass`, `test_reuse_ttl_by_claim_class`, `test_chat_isolation`, `test_lru_is_bounded`, `test_restart_limitation_is_explicit`, `test_reuse_kill_switch` |
| **8** только snippets | `source_read_level=snippet`, `source_fetched` ≠ delivered ≠ verified | `test_search_is_snippet_not_fetched`, `test_fetched_is_not_verified_reuse_until_delivered`, `test_snippet_candidate_is_not_read_source` |
| **9** 403/404/timeout/короткая страница | честная причина + `retryable`, без «не существует»/фантомного URL; короткая страница = ok | `test_fetch_failure_is_honest`, `test_short_valid_page_is_not_unavailable`, `test_short_valid_page_is_document_not_failure`, `test_extraction_ceiling_is_honest` |
| **10** два источника расходятся | обе даты публикации сохранены и различимы (`meta`/`time`), разные `source_id` | `test_two_sources_keep_distinct_publication_dates` |
| **40** медленный/зависший поиск | bounded terminal status (< 3 c при таймауте 0.15), без «вечных» конвертов | `test_hung_search_returns_terminal_status` |
| **44** reuse существующих сервисов | тот же `SearchAggregator`/`WebContentExtractor` (инъекция), в `source_reuse` нет сети/БД, один fetch-контур | `test_router_uses_injected_search_and_extractor`, `test_source_reuse_has_no_network_or_db_imports`, `test_web_content_extractor_has_single_fetch_contour` |
| **46** числовые оси | `lookups/hits/misses/stored/entries/expired/contested_hits/delivered`, coverage-ratio | `test_stats_have_numeric_axes`, `test_coverage_reports_missing_claims` |
| §3.2 единый канон claim-key | ключ совпадает с `evidence_policy.ClaimKey`, чужой ключ принимается кешем | `TestSingleClaimKeyCanon` (3 теста) |

---

## 4. Прогоны (этот worktree, `python -m pytest`)

```
tests/test_evol_evidence_window.py                                    48 passed
tool/search/reader/capacity-набор (26 файлов, см. ниже)                666 passed
  = test_tool_router, test_tool_chains_round1026, test_tool_schemas, test_tool_loop,
    test_tool_calling_round1015, test_tool_coordinator_round1026, test_web_content_extractor,
    test_web_handlers, test_web_summarizer_service, test_search_aggregator,
    test_smartsearch_{service,handlers,prompts}, test_auto_budget_asap31,
    test_capacity_resolver_asap31, test_capacity_nanogpt_asap32, test_l2_budget_asap31,
    test_direct_context_{capacity,composer,scenarios}_asap3, test_mca02_safe_fetch_round1027,
    test_soul13_ssrf_guard_order, test_mca11_tool_result_round1028,
    test_recent_history_tool_round1015, test_factcheck_tools_round1020
factcheck/temporal/mca15-границы                                       197 + 147 passed
asap8 direct d03/d04/matrix + evol_fc_evidence_style                   82 passed
asap8 direct d03/d04/matrix, mca20, mca23                               176 passed, 2 failed (см. §6)
```

**Обновлены тесты, чьё утверждение противоречило новому контракту** (не ослаблены, а переписаны под него):
- `tests/test_tool_router.py`: `test_result_truncated_to_4000` → `test_result_not_capped_at_legacy_4000` (+ `test_small_window_bounded_and_observed`);
  `test_success_formats_result` / `test_query_falls_back_to_ctx_query` больше не требуют `max_symbols=4000` (это была проверка самого дефекта).
- `tests/test_tool_chains_round1026.py`: `test_url_argument_and_json_contract` (извлечение до 120k, `read_level`),
  `test_no_url_is_honest_error` (+`reason/retryable`), `test_truncated_flag_when_capped` (truncated = достижимый остаток,
  `full_source_pointer.offset`), новый `test_article_not_capped_at_legacy_8000`.

---

## 5. C4 (двойной резерв) — что проверено в этой полосе и что нет

- В моих файлах резерв вывода **не вычитается вообще**: `resolve_evidence_tool_window` не принимает
  `output_reserve_tokens`; лимит выводится только из окна/бюджета (`test_no_double_output_reserve` фиксирует
  `budget×1.25` без `-512`).
- Дефолт `l2_evidence_budget_chars(..., output_reserve_tokens=512)` живёт в `services/direct_execution.py` — **файл другой
  полосы** (правка C4 по контракту §0.2 там же). Patch note: интегратору нужно `output_reserve_tokens=0` по умолчанию;
  иначе evidence дважды урезается (композер + эта функция). Мой слой это не компенсирует и не маскирует.

---

## 6. Пред-существующие/чужие красные (не мои файлы, не маскирую)

| Тест | Причина | Класс |
|---|---|---|
| `test_mca23_planned_vs_actual.py::test_routes_pin_untouched` | пин SHA `web/api/routes.py` не совпадает с файлом при `git status` = clean (файл не менялся) | **pre-existing** в этой ветке |
| `test_mca20_integration_round1045.py::test_reason_codes_279` | `mca_events.REASON_CODES` = 314 (policy-полоса добавила 3 кода §1.4), пин теста не обновлён | **другая полоса** (`services/mca_events.py` изменён ими) |
| `test_summary_publish_integration_round1026::test_on_l1_not_usable_level2_l2_publishes_article` | известный пред-существующий красный (контракт §6.3) | **pre-existing** |

Проверка, что это не мои изменения: `git status -- web/api` пуст; `mca_events.py` изменён другой полосой (в моём scope его нет).

---

## 7. Seams / patch notes для других владельцев (честно)

1. **Проводка в Direct (нужна интегратору полосы B).** Reuse и per-call бюджет включаются двумя аддитивными полями
   `ToolContext`: `ctx.claim_keys = decision.claims` (policy уже отдаёт `EvidenceDecision.claims`, §1.6) и
   `ctx.evidence_budget_chars = <бюджет evidence композера>`. Без них: `claim_keys` пуст → reuse не срабатывает
   (обычный fetch), `evidence_budget_chars=0` → лимит инструмента выводится из окна модели (`source="window"`).
   Это не деградация контракта, но и не «verified reuse» — так и помечено в отчёте.
2. **`config/settings.py`.** `EVIDENCE_WINDOW_DYNAMIC_ENABLED` и `EVIDENCE_REUSE_ENABLED` читаются через
   `getattr(settings, …, True)` (паттерн `mca_gates`), но env-ClassVar в `config/settings.py` — вне моего scope.
   До его добавления kill-switch включается только присваиванием атрибута (тесты так и делают).
3. **`services/tool_schemas.py` (схема `TOOL_FETCH_ARTICLE`).** Обработчик принимает `offset|section|terms`, но схема
   всё ещё `additionalProperties: false` с единственным `url`: модель не может легально запросить остаток через
   function-calling, пока владелец схемы не опубликует эти поля. Это осознанно не правил (канон инструментов и его
   канонический тест `len(TOOL_CALLING_TOOLS)==15` — чужая зона). До этого остаток достижим в тестах/вызовах,
   но не «самостоятельно моделью».
4. **`services/direct_l1.py:788 L1_WINDOW_LINE_CHARS=200`** (корень «L1 не видит claim в длинной реплике»,
   `limits-audit.md` №13) — файл другой полосы, не правил. Требуется динамическая длина строки по окну L1;
   без этого сценарии 4/5/15 всё ещё могут терять claim на входе планировщика.
5. **`services/search_service.py` + `settings.SEARCH_MAX_SYMBOLS = 4000` / hot `limits.search_max_symbols`**
   (третий независимый 4000-потолок smartmodule-пути, `limits-audit.md` №79) — файл вне моего scope. Tool-путь больше
   не использует эту настройку, поэтому два пути дают разные пределы; свести к одному источнику — владельцу
   search_service. Также `SearchAggregator.search(..., max_symbols)` по-прежнему режет слепо: tool-путь обходит это,
   передавая технический ceiling, но `SearchService.research`/ФЧ-вызовы остаются с прежним слепым срезом.
6. **Payload-дубль `excerpt`.** Контракт §4.3 перечисляет `excerpt` и `markdown`; я держу **одну** копию текста
   (`markdown`) + `excerpt_chars/line_range/selected_by`, потому что дубль удваивал бы tool-payload в окне модели.
   Информация эквивалентна; если Reviewer требует буквальный ключ `excerpt`, это одна строка, но плата — 2× символы.
7. **События §4.5 (`EVIDENCE_DELIVERY` и др.)** эмитятся policy/композером другой полосы; мой слой отдаёт числа
   через `ctx.evidence_limits` (out-of-band, R17-safe) и `source_reuse.stats()` — их и надо прокинуть в события.
8. **`published_at`** берётся только с trafilatura-уровня (тот же HTML, без второго запроса). Облачные фолбеки (Tavily/
   Exa) даты не отдают → `published_at=""`, `published_at_source=""` (честно, не выдумываем).
9. **Reuse и приватность.** Namespace = `public` только для публичного http(s)-источника; всё непубличное живёт под
   `@chat:<id>`. В поисковик по-прежнему уходит `query` из существующего пути (privacy §7 — вне моей полосы).

---

## 8. Честные остаточные ограничения

- **Reuse не подключён к Direct-пайплайну** (см. §7.1): в текущем HEAD `ctx.claim_keys` никто не ставит, поэтому
  сквозной сценарий 30 в живом ответе пока даёт обычный fetch (тестами доказан механизм, не проводка).
- **Тестовая база:** живой провайдер не использовался (offline fixtures), `NOT_OBSERVED` для реальной сети/латентности.
- **«Раздел после 8k»** доказывается на offline-документе; реальная trafilatura-разметка страниц может отличаться
  (тогда работает прежний каскад и честный `truncated/remainder`, но не идеальный section pick).
- **`_SEARCH_MAX_SYMBOLS`/`_ARTICLE_MAX_SYMBOLS` остались в коде** как legacy-константы (на них ссылаются тесты и
  kill-switch-путь). Это не потолок качества: при динамике ON они не используются в решении о размере.

---

## 9. Итог (обязательные три строки)

Убраны жёсткие 4000/8000 как потолки evidence: лимит одного tool-вызова теперь выводится из реального окна модели/бюджета композера (20 % окна, ≤200k, защита от лавины 40 % на ход), а поиск отдаёт индекс кандидатов без потери URL и статья — секционную выдержку с `line_range` и достижимым остатком.

Добавлен чистый in-memory reuse прочитанного источника по claim-key (единый канон с policy, TTL по классу claim, инвалидация версией/контрдоказательством/TTL, изоляция чатов, `fetched ≠ delivered ≠ verified`), поиск и чтение пропускаются без сети при свежем покрытии.

Прогоны: 48 новых тестов + 666 в наборе tool/search/reader/capacity — зелёные; два красных теста относятся к чужим файлам (`web/api/routes.py` пин, `mca_events.REASON_CODES` из policy-полосы); честно зафиксированы несделанные швы: проводка `ctx.claim_keys`/`evidence_budget_chars`, публикация `offset/section/terms` в схеме инструмента, C4-дефолт в `direct_execution.py`, `L1_WINDOW_LINE_CHARS` и сведение `SEARCH_MAX_SYMBOLS` в `search_service`.
