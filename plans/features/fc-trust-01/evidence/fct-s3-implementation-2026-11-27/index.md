# FCT-S3-RETRIEVAL — реализация retrieval-контракта S3 (Builder, 27.11.2026)

База: production `9516c912554bb1062f62a63b6689f418c1cb5425` = 2.58.257.
Ветка: `feat/fct-s3-retrieval`. Кандидат: **`2eb9f9b617a21428606436aacffb1119932f8f13`**.
Контракт: `evidence/fct-s3-s4-contract-2026-11-27.md`, sha256
`adb3bc325c4c4048d79d16b62f5b47c941a356ab4ee1c7b7953a5f3050630190` (13 обязательных строк;
`FCT-202` не существует — см. §9 P-S3-8).

## 1. Что изменено (ровно 5 путей контракта)

| Файл | Изменение |
|---|---|
| `services/factcheck_planner.py` | recall-кандидаты (`Candidate`/`search_candidates`), evidence-профиль (`_relevance_for` → `require_anchor=True`), claim-specific passage + провенанс (`_claim_passage_from_html`, `fetch_primary_evidence(claim=…, meta=…)`), `basis`/`assertion_type`/`material_role`/`independence_group`/`evidence_version`, даты провайдера, закрытый словарь `stop_reason`/`status_detail`, per-claim проекция `search_text`, распределение открытий, журнал запросов, `is_cancelled`, `coverage_summary` |
| `services/search_aggregator.py` | `claim_relevance(..., require_anchor=)` + `basis`/`anchor`/`timeframe`, якорь-время и имена-аббревиатуры (через planner `_entities`), `rate_limit` в `level_failure_reason`/`_REASON_PRECEDENCE`, мягкий recall (low-overlap пак не выбрасывается), `extract_publication_date` (переиспользование `PUBLISHED_LABEL`/`normalise_publication_date`/`_parse_date_value`) |
| `services/safe_fetch.py` | **0 изменений** (как и ожидалось контрактом; SSRF/лимиты/санитизация не тронуты) |
| `services/factcheck_attribution.py` | **0 изменений** (как и ожидалось контрактом) |
| `tests/test_fc_trust_retrieval.py` | новый модуль, 45 тестов, все фикстуры внутри модуля |

Совместимость: `services/evidence_refs_from_search` сохранена как обёртка (тот же публичный shape),
`RetrievalOutcome`/`ClaimCoverage`/`ClaimEvidence` расширены только аддитивными полями с дефолтами,
`claim_relevance` без `require_anchor` сохраняет прежнее поведение для
`direct_execution`/`evidence_policy` (проверено их наборами).

## 2. RED на базе / GREEN на кандидате

Один и тот же модуль `tests/test_fc_trust_retrieval.py`:

| Прогон | Команда | Результат |
|---|---|---|
| RED (база `9516c9125`, отдельный detached worktree, только новый тест-файл) | `python -m pytest tests/test_fc_trust_retrieval.py -q` | **37 failed, 8 passed** (`raw/red_base.txt`) |
| GREEN (кандидат `2eb9f9b6`) | то же | **45 passed** (`raw/green_slice.txt`) |

8 «зелёных на базе» — это сознательные негативные/совместимые контроли: all-providers-failed всё ещё
бросает, короткая композиция запроса не меняется, `evidence_refs_from_search` сохраняет форму,
`run_retrieval` не бросает на сломанном агрегаторе, stale-дата и т.п. Они не доказывают новые строки.

## 3. Обязательные наборы (GREEN)

| Набор | Результат | Лог |
|---|---|---|
| `test_factcheck_planner_cfg06`, `test_factcheck_p0_fc`, `test_factcheck_resources`, `test_evol_fc_evidence_style` | 95 passed | `raw/green_acceptance_1.txt` |
| `test_search_aggregator`, `test_search_short_tokens`, `test_search_source_dates` | 71 passed | `raw/green_acceptance_2.txt` |
| `test_unified_reply_ur_b_search_first`, `test_ur_search_first`, `test_evol_evidence_routing` | 184 passed | `raw/green_acceptance_3.txt` |
| `test_fc_backend_corrective`, `test_factcheck_service` | 41 passed | `raw/green_acceptance_4.txt` |
| широкий набор S3-потребителей (40 файлов: handlers, temporal, mca20, safe_fetch, cfg07, evidence delivery, fc_r1, w6/w7, subject contract, target) | **1227 passed** | `raw/green_broad.txt` |
| потребляющие контуры (mem_time_policy, unified-reply no_topic/review, self-diag golden/samples, direct_chat) | **310 passed** | `raw/green_consumers.txt` |

**Предсуществующих red-ов нет** в прогнанных наборах (все перечисленные прогоны на базе до правок были
зелёными: 318 passed в аудите). Полный `tests/` не запускался — см. §8.

## 4. Мутации M-S3-01..18 (все убиты)

Каждая мутация применялась текстовым патчем в отдельном одноразовом worktree на SHA кандидата, затем
запускался предназначенный тест; файл восстанавливался. Полный вывод — `raw/mutations.txt` (18/18
`KILLED`, 0 `SURVIVED`, 0 `PATCH_NOT_FOUND`).

| ID | Мутация | Убийца |
|---|---|---|
| M-S3-01 | `require_anchor=False` в planner | `test_word_overlap_only_pack_is_not_evidence_end_to_end` |
| M-S3-02 | жёсткий отброс low-overlap в `search_relevant` | `test_low_overlap_pack_returns_instead_of_hard_failure` |
| M-S3-03 | отсеянные кандидаты снова в модельный раздел | `test_rejected_candidate_absent_when_others_accepted` |
| M-S3-04 | без разбора `PUBLISHED_LABEL` | `test_provider_date_is_structured_and_not_in_support` |
| M-S3-05 | подстановка фиксированной даты вместо unknown | `test_missing_date_is_unknown_and_never_invented` |
| M-S3-06 | `rate_limit` → `provider_error` | `test_level_failure_reason_rate_limit_is_distinct` |
| M-S3-07 | `global_deadline` → `no_progress` | `test_global_deadline_is_distinct_and_honest` |
| M-S3-08 | часть без попытки → `no_relevant_sources` | `test_resource_limit_is_not_claim_not_searched` |
| M-S3-09 | первый абзац вместо claim-specific фрагмента | `test_claim_specific_passage_not_first_paragraph` |
| M-S3-10 | `gov`-домен → `original` | `test_gov_press_digest_is_not_original` |
| M-S3-11 | копии считаются независимыми | `test_one_quality_primary_suffices_and_copies_are_not_independent` |
| M-S3-12 | повтор идентичного текста запроса | `test_identical_query_text_is_not_repeated` |
| M-S3-13 | без `stop_reason` в диагностике | `test_query_journal_has_claim_intent_purpose_and_outcome` |
| M-S3-14 | фиксированные 200 символов с обрезкой якоря | `test_query_length_keeps_anchor_and_period_on_word_boundary` |
| M-S3-15 | хардкод лимита в обход PG/hot | `test_limits_resolve_existing_keys_with_provenance` |
| M-S3-16 | `outcome` части из run-level бюджета | `test_claim_with_evidence_keeps_status_under_run_limit` |
| M-S3-17 | повышение роли вне claim-aware профиля | `test_word_overlap_only_pack_is_not_evidence_end_to_end` |
| M-S3-18 | `assertion_type` из claim вместо passage | `test_assertion_type_from_passage_in_pipeline` |

## 5. Изменения существующих тестов (поимённо, без ослабления)

Все пять правок кодировали отменённое контрактом поведение; каждая замена сохраняет или усиливает
различающую силу.

1. `tests/test_factcheck_resources.py`
   * `_anchored_plan/_anchored_block/_AnchoredSupportAgg` добавлены; `_SupportAgg` и `_multi_url_chunk`
     удалены — они подавали материал без специфического якоря (совпадение слов = «подтверждение»),
     что отменено FCT-401/M-S3-01.
   * `test_on_page_size_20…`, `test_on_fetch_policy…`, `test_stop_reason_sufficient_evidence…`:
     фикстуры переведены на материал с якорем (метрика/имя/период); проверяемое свойство (страница 20,
     cap открытий, остановка по содержанию) сохранено.
   * `test_on_search_text_is_a_100k_portion…` и `test_off_removes_deadline_query_and_char_caps`:
     сверяют порционность **проекции** `search_text` (FCT-406), а не сырого пака; добавлено
     `"".join(portions) == search_text` и сохранение хвоста.
   * `test_on_deadline_and_query_budget_are_applied`: «непроверенных из-за бюджета» частей больше нет
     (все 40 получили базовую попытку) — вместо этого проверяется run-level `stop_reason=resource_limit`,
     `refine_calls=24` и отсутствие подмены статуса части.
   * `test_technical_provider_budget_is_not_product_budget`: транспортный предел вызова — теперь
     `provider_timeout` (M-S3-06/§3.1), а не `technical_limit`; добавлено `claims_unchecked_due_to_deadline==0`.
2. `tests/test_factcheck_fc_r1_fix.py`
   * `test_all_irrelevant_is_honest_failure` → `test_all_low_overlap_returns_pack_not_failure`: жёсткий
     отброс отменён (M-S3-02); проверяются возврат пака, трасса `low_overlap_fallback` и опрос всех уровней.
   * `test_run_retrieval_ranks_and_fetches_primary`: вместо «reference первым по алфавиту» проверяется
     порядок по покрытию (`len(refs[0].claims) == max`) и наличие обоих типов источников.
3. `tests/test_factcheck_post_release_w1.py`
   * `test_irrelevant_results_distinguished` → `test_low_overlap_pack_is_not_a_hard_failure` (то же
     отменённое поведение, M-S3-02).
4. `tests/test_factcheck_w7_acceptance_cfg06.py`
   * `test_s2_meaningful_without_sources_honest_limit`: URL-less пак больше не уходит в модель
     (FCT-406) — проверяется, что `search_results` пуст, ссылок нет, а ответ честно ограничивает вывод.
5. `tests/test_evol_fc_evidence_style.py`, `tests/test_fc_backend_corrective.py`
   * `test_sc8_provider_and_deadline_are_technical`: таймаут конкретного вызова — `provider_timeout`
     (§3.2), список допустимых исходов расширен, счётчик дедлайнов считается по тому же определению,
     что и `coverage_summary`.
   * `test_fc05_budget_deadline_is_technical_status`: истёкший бюджет — `outcome=technical` и один из
     `deadline/provider_timeout/provider_error` (усиление: раньше проверялся только `status_detail`).

## 6. Поведение по строкам (что теперь наблюдаемо)

| Строка | Наблюдаемый результат | Тесты |
|---|---|---|
| FCT-201 | `supports/contradicts` только при якоре (сущность/тикер S&P, число+единица, цитата, совпавший период); `word_overlap_only` → `background_only` с basis | `test_word_overlap_only_*`, `test_timeframe_anchor_allows_support`, `test_ticker_abbreviation_is_an_anchor`, `test_word_overlap_only_pack_is_not_evidence_end_to_end` |
| FCT-203 | журнал запросов части: `claim_id/intent/purpose/provider/outcome/latency`; `stop_reason` в `coverage_summary`; событие без текстов/URL | `test_query_journal_has_claim_intent_purpose_and_outcome` |
| FCT-301 | различимы `resource_limit`, `global_deadline`, `provider_timeout`, `rate_limit`, `cancelled`, `claim_not_searched`, `no_relevant_result`, `source_unreadable`; новые `reason_code` — только существующие | `test_provider_timeout_*`, `test_rate_limit_*`, `test_provider_error_stays_*`, `test_resource_limit_*`, `test_global_deadline_*`, `test_cancelled_*`, `test_source_unreadable_code_is_reachable`, `test_new_status_details_map_only_to_existing_reason_codes` |
| FCT-302 | открытия распределяются по частям (`cap=2` при 3 частях → 2 разные части, `fetch_skipped_budget=1`); длина запроса ≤320, режется по слову, якорь/метрика/период сохранены | `test_fetch_cap_is_shared_*`, `test_query_length_keeps_anchor_*`, `test_short_query_composition_is_unchanged` |
| FCT-303 | только 9 существующих `limits.factcheck_*`, провенанс `chat/global/default` в `limit_sources`/`coverage_summary`, новых ключей нет | `test_limits_resolve_existing_keys_with_provenance` |
| FCT-306 | идентичный текст запроса не повторяется; частичный результат с `stop_reason` | `test_identical_query_text_is_not_repeated` |
| FCT-402 | у displayable-роли всегда есть `basis`; `assertion_type` — из passage (quote/legal/opinion/statistic/unknown); `background_only` ≠ `irrelevant` | `test_assertion_type_*`, `test_displayable_relation_always_has_basis`, `test_background_and_unrelated_are_distinct` |
| FCT-403 | `material_role` отделён от домена: gov+атрибуция ≠ original, gov без атрибуции = original, secondary без маркеров = unknown, fetch не повышает роль | `test_gov_press_digest_*`, `test_gov_own_statement_*`, `test_secondary_without_markers_*`, `test_successful_fetch_does_not_upgrade_material_role` |
| FCT-404 | claim-specific фрагмент, `matched=False` при отсутствии якоря, `full_text_available`/`published_at_source=page`, стабильный `evidence_version`, `snippet_only`+непрямая сила без открытия | `test_claim_specific_passage_*`, `test_unmatched_document_*`, `test_fetched_page_reports_*`, `test_evidence_version_*`, `test_unreadable_source_is_counted_*` |
| FCT-405 | копии одной публикации — одна `independence_group`, вторая `independent=False`; одного качественного источника достаточно | `test_copies_share_independence_group`, `test_one_quality_primary_suffices_*` |
| FCT-406 | отсеянное отсутствует и в EvidenceMap, и в `search_text`; `search_text` — проекция с типизированной шапкой; пустая карта при непустом разделе даёт `refs_collected=0`, `citation_ids=()` | `test_off_topic_candidates_*`, `test_rejected_candidate_absent_*`, `test_low_overlap_candidate_is_typed_non_evidence_section` |
| FCT-502 | дата провайдера → `published_at` + `published_at_source=provider`, метка не в support; без даты — unknown, без подстановок; stale снимается | `test_provider_date_is_structured_*`, `test_missing_date_*`, `test_stale_provider_date_drops_candidate` |

## 7. Честные пробелы и парки (не выдаются за сделанное)

* **P-S3-3 (S4):** run-level публичные формулировки для `rate_limit`/`provider_timeout` остаются в
  `factcheck_service._RETRIEVAL_*` (файл S4). S3 отдаёт коды и per-claim `gap_note`; рендер
  `_TECHNICAL_PART_LABELS` (S5) новых значений пока не знает — подпись части остаётся текстом
  `gap_note` (не «данных недостаточно»-подмена только там, где рендер нашёл старый код).
* **P-S3-4 (S4):** «пустая EvidenceMap + непустой кандидатский раздел не даёт уверенного вердикта» —
  держит существующий `positive_without_direct_support`; S3 гарантирует отсутствие evidence,
  `refs_collected=0` и `citation_ids=()`.
* **P-S3-1/P-S3-2:** смысловая (LLM) оценка отношения — S4; показ `limits.factcheck_*` в админке —
  S6/FCT-906 (`services/param_catalog.py` не тронут).
* **FCT-301 `cancelled`:** реализован явный путь отмены (`run_retrieval(is_cancelled=…)`), потому что
  в планировщике не было сигнала отмены; `asyncio.CancelledError` не подавляется (семантика asyncio
  сохранена) — это зафиксировано в docstring.
* **Активация:** новых флагов нет; при `flags.factcheck_pipeline_v2=false` planner-слой не исполняется
  (S1/аудит §1.4). Приёмка выполнена на детерминированных фикстурах обоих режимов бюджета
  (`budgets_enabled` ON/OFF) и обоих состояний флага в тестах (`planner_on`); effective-значение флага
  на проде фиксирует S0/релиз (P-S3-7). Live-выдача провайдеров — необязательное наблюдение (P-S3-6).
* **FCT-301 `source_unreadable`:** в реальном pipeline достижим только когда после неудачного
  чтения у части не остаётся displayable-evidence; покрыт и модульным тестом кода, и счётчиком
  `source_unreadable` E2E (P-S3-3: подпись — S4/S5).

## 8. Ограничения прогона

* Полный `tests/` не запускался: прогон пропорционален — 40 файлов потребителей S3 + 6 файлов
  соседних контуров (1672 теста суммарно во всех строках §3), плюс обязательные наборы контракта.
* Тесты не ходят в сеть: внешние границы (`SearchAggregator` уровни, `fetch_text`, LLM) подменены
  двойниками; production-путь `run_retrieval`/`claim_relevance`/`fetch_primary_evidence` исполняется
  реально.
* Боевые провайдеры/прод-БД/Telegram не затрагивались; деплой не выполнялся.

## 9. Артефакты

* `raw/red_base.txt` — RED на `9516c9125` (37 failed, 8 passed).
* `raw/green_slice.txt`, `raw/green_acceptance_1..4.txt`, `raw/green_broad.txt`,
  `raw/green_consumers.txt` — GREEN-прогоны.
* `raw/mutations.txt` — 18 мутаций (все KILLED) + JSON-сводка.

Машиночитаемая сводка — §10.

## 10. Машиночитаемый блок

```json
{
  "slice": "FCT-S3-RETRIEVAL",
  "contract": "FCT-S3-S4-CONTRACT",
  "contract_sha256": "adb3bc325c4c4048d79d16b62f5b47c941a356ab4ee1c7b7953a5f3050630190",
  "base_sha": "9516c912554bb1062f62a63b6689f418c1cb5425",
  "base_version": "2.58.257",
  "candidate_sha": "2eb9f9b617a21428606436aacffb1119932f8f13",
  "branch": "feat/fct-s3-retrieval",
  "changed_files": [
    "services/factcheck_planner.py",
    "services/search_aggregator.py",
    "tests/test_fc_trust_retrieval.py",
    "tests/test_factcheck_resources.py",
    "tests/test_factcheck_fc_r1_fix.py",
    "tests/test_factcheck_post_release_w1.py",
    "tests/test_factcheck_w7_acceptance_cfg06.py",
    "tests/test_evol_fc_evidence_style.py",
    "tests/test_fc_backend_corrective.py"
  ],
  "zero_change_files": ["services/safe_fetch.py", "services/factcheck_attribution.py"],
  "red": {"tests": 45, "failed": 37, "passed": 8, "log": "raw/red_base.txt"},
  "green": {
    "slice": 45,
    "acceptance_1": 95,
    "acceptance_2": 71,
    "acceptance_3": 184,
    "acceptance_4": 41,
    "broad_consumers": 1227,
    "adjacent_consumers": 310,
    "preexisting_reds": []
  },
  "mutations": {"total": 18, "killed": 18, "survived": 0, "log": "raw/mutations.txt"},
  "rows": ["FCT-201", "FCT-203", "FCT-301", "FCT-302", "FCT-303", "FCT-306", "FCT-401", "FCT-402", "FCT-403", "FCT-404", "FCT-405", "FCT-406", "FCT-502"],
  "duplicate_rows": ["L00123", "L00124", "L00125"],
  "parks": ["P-S3-1", "P-S3-2", "P-S3-3", "P-S3-4", "P-S3-5", "P-S3-6", "P-S3-7", "P-S3-8"],
  "deploy": false,
  "telegram_messages": false
}
```
