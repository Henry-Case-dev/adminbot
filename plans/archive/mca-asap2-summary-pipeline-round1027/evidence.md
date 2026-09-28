# mca-asap2-summary-pipeline — evidence.md (Builder)

- **Baseline:** HEAD `e882d58` (прод-база 2.58.32 = `270c277`), рабочее дерево
  = baseline + незакоммиченная MCA-волна round1027 + uncommitted partial
  same-prompt L1 retry (`services/summary_l1_clusterizer.py`, `config/settings.py`
  SUMMARY_L1_RETRY_ENABLED + пин APP_VERSION 2.58.33, untracked
  `tests/test_summary_asap2_l1_retry_round1027.py`).
- **Binding-хэши перепроверены на входе в Build (Get-FileHash):**
  `spec.md` SHA256 = `C30AABC49CC3E996C7CBF072A154FCD7EA7E8C0963974F9ACEE34B30F67C12DC` — СОВПАЛ;
  `adr-1027-10-...md` SHA256 (`5542CCBE…0DD3`) — сверен Orchestr/PM при PLANNING_CONSISTENT.
- **Коммитов нет** (ревью до коммита по приказу); деплой T-3963 вне Builder.

## Чек-лист задач

(обновляется по мере закрытия; [x] только при наличии кода И evidence проверки)

## Контракт (i) — матрица «отказ стадии → действие» (T-3951, единый источник spec)

| # | Отказ | Действие | Доп. LLM-вызовы |
|---|---|---|---|
| 1 | Hybrid kill-switch OFF | Legacy-пайплайн сразу (существующий OFF-путь) | ≤2 (legacy) |
| 2 | Окно пустое (0 rows) | `_UX_EMPTY`, SUMMARY_COMPLETE empty — НЕ failure | 0 |
| 3 | L1 invalid после repair (+retry)/error/timeout/empty/useless/too_many_* | LEVEL-2: fallback-пакет → L2 | ≤1 (L1 retry) +1 (L2) |
| 4 | L1 slot не резолвится (L1SlotError) | то же, что 3 (LEVEL-2) | +1 (L2) |
| 5 | FactPackage not deliverable при usable L1 | LEVEL-2: пересборка fallback-пакета → L2 | +1 (L2) |
| 6 | L2 unusable (обычный или fallback-пакет) | LEVEL-3 Legacy (L2-retry НЕ вводится) | ≤2 (legacy) |
| 7 | Cover-генерация упала/недоступна | plain-публикация hybrid-текста (`_plain_fallback reason=cover_*`) — НЕ legacy | 0 |
| 8 | sendRichMessage fail / rich-лимиты не влезают | plain sendMessage полного текста | 0 |
| 9 | plain-доставка hybrid-текста fail (HTML и text-даунгрейд) | LEVEL-3 Legacy | ≤2 (legacy) |
| 10 | Непредвиденное исключение в hybrid-ветке, ничего не опубликовано | LEVEL-3 Legacy (best-effort, own try) | ≤2 (legacy) |
| 11 | Legacy тоже провалился | SUMMARY_FAILED + UX, code=`SUMMARY_GENERATION_FAILED` | — |

Worst case ≤5 генераций: 1 L1 + ≤1 correction retry + ≤1 L2 (fallback-пакет) +
≤2 Legacy (System2 two-call). Guard двойной публикации: флаг `published` —
LEVEL-3 только если ничего не отправлено.

## Заметки по задачам

### Group A — вывод MAX_SUMMARY_PARTS из Hybrid + демонтаж trim

- **T-3935 [x]** `services/summary_l2_writer.py`: удалены `resolve_l2_max_paragraphs`,
  `MAX_PARAGRAPHS_DEFAULT`, параметр `max_paragraphs` из `run_l2` (grep: потребителей
  нет — `summary_test_run.py` его не передавал). Остался только `MAX_PARAGRAPHS_HARD=498`.
  rg-инвариант (обновлённый spec §9-1): `max_summary_parts`/`MAX_SUMMARY_PARTS`
  встречается только в legacy-контурах `services/summary_generator.py`
  (промпт-бюджет `_run_legacy_pipeline` + send-кап `_deliver_plain/_deliver_rich`),
  `config/settings.py` (комментарий+поле), `services/param_catalog.py`
  (группа `limits_summary_legacy`), `services/summary_article_formatter.py`
  (docstring-отрицание), и в тестах legacy-семантики — проверено `rg`.
- **T-3936 [x]** удалены: `_trim_document_for_publication`, trim-ветка `run_l2`,
  `REASON_TRIMMED_FOR_PUBLICATION`, метрики `trimmed_for_publication/paragraphs_before/
  paragraphs_dropped_count`, WARN `L2 trimmed_for_publication`, `trimmed=` в L2_COMPLETE;
  ClassVar `SUMMARY_L2_TRIM_ENABLED` из `config/settings.py`; NOTE в
  `tests/test_tool_coordinator_round1026.py` заменён на ASAP-2 NOTE.
  `rg "SUMMARY_L2_TRIM_ENABLED|_trim_document_for_publication" services/ config/` = 0.
- **T-3937 [x]** переписаны тесты trim: `tests/test_summary_asap_hotfix_round1027.py`
  (сценарии (а)/(б) → инварианты «полная статья при parts=1 / не режем не бракуем»,
  инвариант «костыль удалён полностью»; граф-сценарии (в) сохранены без изменений
  — T-3957); `tests/test_summary_l2_writer.py::test_full_article_not_trimmed_by_soft_targets`
  + `test_hard_cap_498_scenario` (вместо trim ON/OFF);
  `tests/test_summary_publish_integration_round1026.py::TestSpec103Statements` →
  legacy-семантика assertion; `test_plain_600_paragraphs_delivered_no_loss` →
  hybrid-полнота + новый `test_legacy_plain_capped_at_max_summary_parts_with_warn`.
- **T-3938 [x]** `config/settings.py:937` комментарий MAX_SUMMARY_PARTS → «макс. число
  Telegram sendMessage частей legacy-саммари (~4000 симв./часть)»; прод-значение hot-ключа
  6 не менялось. Send-time кап: `resolve_legacy_max_parts()` + `_cap_legacy_chunks()`
  (WARN `LEGACY_CHUNKS_CAPPED | run_id | chat_id | chunks_total= | chunks_sent=`);
  параметр `max_chunks: int | None` пронесён по `max_chunks=None`
  (hybrid `_deliver_l2_plain/_deliver_l2_rich/_plain_fallback` из hybrid rich-ядра);
  legacy (`_deliver_plain`, `_deliver_rich` → plain-даунгрейд, `_send_streaming`
  остаток = parts−1, `_send_chunked`) получают резолв parts; rich-путь НЕ каппуется.
  Доставка-ядро возвращает `published: bool` (для LEVEL-3 guard). Docstring
  `services/summary_article_formatter.py:30–31` исправлен.
  Тест: `test_legacy_plain_capped_at_max_summary_parts_with_warn` (parts=1 → 1 часть +
  WARN chunks_total=11/chunks_sent=1) — PASS.
- **T-3939 [x]** hard-лимиты §99 fail-closed сохранены (200/900/498/32000;
  `too_long` = граница аномального ответа → LEVEL-3); WARN-полоса
  `24000<chars≤32000` → `L2_OVER_SOFT_CEILING | chars= | max_chars=` публикуем без
  обрезки (`run_l2`); max_chars в промпт не передаётся (assert в acceptance).
  Тесты: `test_t3958_soft_ceiling_warn_and_publish`, `test_t3958_above_rich_hard_limit_rejected`.

### Group C — L1 §95-v2, repair, correction retry, флаги

- **T-3944 [x]** `services/summary_l1_contract.py`: `SCHEMA_VERSION=2`;
  `REASON_MESSAGE_IN_MULTIPLE_THREADS` УДАЛЁН (валидатор и FactPackage);
  `REASON_EVIDENCE_NOT_IN_THREAD`/`REASON_UNASSIGNED_CONFLICT` из валидатора
  сняты (константы — defense-коды FactPackage/repair); исчерпывающий список
  проверок п.1–7 контракта (a) с ≥1 evidence; `REASON_L1_USELESS_AFTER_REPAIR`
  добавлен. docstring-канон обновлён. `unassigned_message_ids` обязателен
  (bad_type при отсутствии — как раньше), auto_unassigned сохранён.
- **T-3945 [x]** НОВЫЙ `services/summary_l1_repair.py` (чистый: 0 LLM/БД/сети/часов):
  шаги 1–7 строгого порядка; `RepairReport` (все int/bool + useless_reason);
  формула Q3 `topics_after==0 ∨ facts_after==0 ∨ unknown_ids_removed(occurrences)/
  max(ids_referenced_before distinct,1) > 0.5`; вход не мутируется; kill-switch
  проверяет вызывающий. Юниты: `tests/test_summary_l1_repair_round1027.py` — 15 PASS
  (unknown-in-thread, membership expansion, fact/topic removal, unassigned conflict,
  overlapping, три useless-кода, граница ровно 0.5 = НЕ useless, чистота,
  детерминизм, R17-типы).
- **T-3946 [x]** `services/summary_prompts.py`: `_SUMMARY_L1_CLUSTERIZER_R1027_BASE`
  (роль «понять, что происходило», расширенная ЗАДАЧА §7, блок РАЗРЕШЕНО И НОРМАЛЬНО
  many-to-many, schema_version:2 в примере; жёсткие правила сохранены),
  `PREV_SUMMARY_L1_CLUSTERIZER_R1027` = байт-в-байт прежний канон (база R1026+блок);
  ступень `PROMPT_MIGRATIONS` + `ROLLBACK_MIGRATIONS` → `services/prompt_migrations.py`;
  эталон `plans/docs/canon/architecture.md` перегенерирован байт-идентично;
  тесты: `test_canon_v2_allows_many_to_many`, PREV-цепочка, byte-identical — PASS.
- **T-3947 [x]** `run_l1` переработан: цикл `call → L1_PARSE → [repair → L1_REPAIR →
  validate]`; retryable-набор post-repair из 10 кодов (`_RETRYABLE_REASONS`, точный
  assert `test_retryable_set_matches_contract_c`); correction-блок контракта (c)
  (`_correction_block`: «ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: <код>», unknown-id список ≤20
  + «Do not invent message ids», useless_reason, schema_version: 2; append к
  исходному user, system не дублируется — `_build_correction_messages`);
  WARN `L1_CORRECTION_RETRY | attempt=1/2 | reason=<код>` (id в лог не пишутся);
  сохранено из partial: цикл attempts, plumbing `attempts=` в L1_COMPLETE,
  kill-switch-паттерн, без ретрая на транспорт/too_many_*.
  `tests/test_summary_asap2_l1_retry_round1027.py` переписан (16 тестов, PASS):
  инверсия overlap→VALID без retry, unknown→repair без retry, useless→correction,
  kill-switch'ы через hot-ключи, correction-текст, no-cascade.
- **T-3948 [x]** env-слой в `config/settings.py`: `SUMMARY_L1_REPAIR_ENABLED` (новый,
  ON), `SUMMARY_L1_RETRY_ENABLED` (env-слой hot-ключа), `SUMMARY_LEGACY_FALLBACK_ENABLED`
  (новый, ON), `SUMMARY_HYBRID_L2_ENABLED` (сохранён); резолв hot-first
  `_hot_flag()` в clusterizer (`flags.summary_hybrid_l1_repair_enabled`/
  `flags.summary_hybrid_l1_retry_enabled`) и `_legacy_fallback_enabled`
  per-chat→hot→env в генераторе. «Fallback to Legacy» — ЕДИНСТВЕННЫЙ ключ в
  LEGACY-секции (в HYBRID Recovery описание retry даёт ссылку, см. каталог ниже).

### Group B — Hybrid-настройки длины, бюджеты, FactPackage v2

- **T-3940 [x]** ключи `limits.summary_hybrid_response_mode|_target_chars|
  _target_paragraphs|_max_chars` (PG-only реестра, env ClassVar-слой);
  `HYBRID_PRESETS` casual 4000/5, serious 6500/8, deep_research 11000/14,
  max_chars 24000 (WARN-порог, НЕ обрезка; >32000 = too_long → Legacy);
  `resolve_hybrid_length()` (per-chat→hot→env→пресет, >0 побеждает пресет);
  конфиг-режим пользователя побеждает L1 `response_mode` (тот = observability/обложка).
  Тест пресетов: `test_t3958_presets_values_locked`.
- **T-3941 [x]** НОВЫЙ `services/summary_hybrid_budget.py`:
  `resolve_hybrid_context_budget()` (`limits.summary_hybrid_context_tokens`
  default None→30000 / `_chars` 120000 — hot-first+per-chat-слой вызывающего),
  `hybrid_input_budget()` = Q5-формула (safe_budget=TOKEN_SAFETY_MULTIPLIER ~1.15,
  − system prompt, − marker overhead, − output reserve env ClassVar L1 4000 /
  L2 6000; chars-режим ×4), `hybrid_output_reserve_tokens()`.
  `resolve_l1_budget`/`resolve_fact_package_budget` переведены на единую точку;
  Legacy (`_run_legacy_pipeline`, `_apply_filter` off-ветка) читает только старые
  ключи (тест `test_budget_resolver_ignores_legacy_keys`,
  `test_hybrid_mode_uses_hybrid_context_keys`).
  (а) serialized-учёт: `pack_l1_input` считает `count_tokens(json.dumps(item))`
  по §92-элементу (`_serialized_len`/`_payload_item`); тест
  `test_t3958_serialized_budget_counts_fields`.
  (в) democratic eviction: ключ ASC `(reply_protected, −weight_S1(score_message
  из summary_filter — переиспользован), timestamp, db_id)`, последнее сообщение
  неприкосновенно, вытеснение → truncated+skipped_ids+WARN (существующий лог).
- **T-3942 [x]** канон L2 R1027: блок «ДЛИНА И ДЕДУПЛИКАЦИЯ» + «АВТОРЫ И ОТВЕТЫ
  В ПАКЕТЕ» (числа НЕ в каноне); length-блок = детерминированный append к
  user-контенту `build_l2_input(length=…)` («ЗАДАНИЕ ПО ДЛИНЕ И ДЕТАЛИЗАЦИИ:
  response_mode=…; цель ≈ N символов (мягкий ориентир); абзацев ≈ M …не обрывай
  события»); L2_START += response_mode/target_chars/target_paragraphs
  (paragraphs_hint сохранён); max_chars в промпт не передаётся.
  Тесты: `test_canon_v2_length_dedup_authors`, `test_content_included`,
  `test_no_length_block_without_length`.
- **T-3943 [x]** `services/summary_fact_package.py` v2: `SCHEMA_VERSION=2`;
  fragments `{message_id, author_id, display_name, timestamp, reply_to_id, text}`
  из §92-payload (без chat_id/DB-id/message_type/mentions/весов);
  chronology += `topic_ids[]` many-to-many карта; `message_in_multiple_threads`
  fail-closed УДАЛЁН (пересечение рвёт сборку НЕ); unassigned_conflict =
  defense-only; build_l2_input пробрасывает новые поля verbatim; метрики
  `topics_count`/`messages_count` (§18). Тесты:
  `test_fragments_v2_carry_author_and_reply`,
  `test_message_in_multiple_threads_is_valid`, `test_chronology_asc_pair`.

### Group D — fail-soft LEVEL-1/2/3 + цепочка доставки

- **T-3949 [x]** `build_fallback_package(payload_items, *, budget, correlation_id,
  chat_id, reason)` в `services/summary_fact_package.py`: один thread_001
  «Общий ход обсуждения», description='', facts=[], chronology ВСЕ source ASC с
  topic_ids, fragments v2 (author+reply), капы/бюджет общие, статус ok/truncated
  (проходит deliverability-гейт run_l2); пустой payload → None (не failure —
  empty-семантика матрица стр.2); WARN `L1_FALLBACK_PACKAGE | run_id | chat_id |
  reason | fragments | chronology`. Обложка деградированного пути —
  `_derive_fallback_cover_prompt` (DoD-14; гейт SUMMARY_COVER_FALLBACK_ENABLED)
  в `_run_hybrid_l2`. Тесты: `test_t3959_10_…`, `test_t3959_10b_empty_payload_not_failure`.
- **T-3950 [x]** `_run_legacy_pipeline(chat_id, rows, xml_rows, focus,
  trigger_message_id, correlation_id, ctx, *, max_parts=None, skip_memorize=False)`
  — тело OFF-ветки извлечено дословно (System2 two-call/single по
  SYSTEM2_SUMMARY_ENABLED, XML+RAG+graph-facts, cover, rich/plain с legacy
  send-капом); OFF-режим вызывает как раньше; LEVEL-3 — те же строки,
  skip_memorize=True (memorize уже сделан в hybrid-ветке — дубля нет).
  Цепочка доставки hybrid: article→sendRichMessage→fail→plain(полный текст,
  max_chunks=None)→fail→LEVEL-3 Legacy (матрица стр.7/8/9); guard `published`
  (доставка возвращает bool; LEVEL-3 только при неопубликованном; rich-успех +
  позднее исключение → НЕ fallback — `test_t3959_guard_published_no_double_publication`);
  worst case ≤5 — `test_t3959_11b_worst_case_five_generations`;
  снятие промежуточного degraded при успехе Legacy (`fallback=legacy, status=ok`).
  `L2-провал → без legacy-фолбэка` (ADR-1026-7 D5) отменён согласно ADR-1027-10 D3.
- **T-3951 [x]** матрица 11 строк скопирована в начало этого файла (единый
  источник T-3950/T-3951/T-3952); каждая строка имеет тест-привязку:
  1 (OFF-путь — существующие test_summary_generator/deploy OFF-кейсы),
  2 (10b empty), 3/4 (10: L1 invalid→L1_FALLBACK_PACKAGE→L2), 5 (package_unusable
  ветка в `_run_hybrid_l2`), 6 (11: l2_unusable→legacy; l2_llm_error_http_details),
  7 (scenario_09 cover→plain), 8 (12: rich fail→plain полного текста),
  9 (13: plain fail→delivery_failed→legacy), 10 (package_raise→
  hybrid_exception:RuntimeError legacy best-effort; guard-тест),
  11 (07b: оба контура мертвы → SUMMARY_GENERATION_FAILED + legacy-мок False).
- **T-3952 [x]** §106-коды: `SUMMARY_GENERATION_FAILED` только когда и Legacy
  срабатывает (или fallback OFF — осознанный аварийный режим); `L2_SKIPPED
  l1_not_usable` терминальный снят (переход LEVEL-2; событие L1_FALLBACK_PACKAGE);
  `TEXT_FALLBACK_FAILED` в hybrid не терминален (за ним LEVEL-3);
  `RICH_MESSAGE_SEND_FAILED` — промежуточный пролёт rich→plain;
  `_send_ux` при промежуточных кодах не вызывается (тест
  `test_t3959_no_ux_spam_on_recovery_path`); обновлены:
  `tests/test_summary_publish_integration_round1026.py` (3 fail-closed теста →
  LEVEL-2/3-семантика + bound NOTE), `tests/test_summary_logging_runid.py`
  (l1_not_usable→level2, l2_error→legacy-disabled/published, package_raise),
  `tests/test_summary_deploy_round1026.py` (scenario_07 → fail-soft + новый
  07b терминальный; bound-гейты: исключены санкционированные файлы; AST-пин
  перенесён на неизменяемые Legacy-функции + состав `_run_legacy_pipeline`),
  `tests/test_summary_l2_integration.py` (l1_not_usable → fallback-пакет;
  L2 failure → LEVEL-3 mock).

### Group E — каталог + miniapp

- **T-3953 [x]** `services/param_catalog.py`: +5 GroupSpec (`flags_summary_hybrid`
  order 24, `flags_summary_legacy` 25, `models_summary_hybrid` (models) 10,
  `limits_summary_hybrid` (limits) 34, `limits_summary_legacy` 35);
  +16 ParamSpec (`_SUMMARY_HYBRID_PG_ONLY`: 4 flags + 4 models + 2 keys(secret=True)
  + 6 limits — состав ПО spec (j)); перенос (не дельта) 3 ключей:
  `limits.max_summary_parts`, `limits.summary_max_context_tokens/_chars` →
  `limits_summary_legacy` с ретитлом «Legacy: …» и описанием «не влияет на
  Hybrid»; общие ключи (throttle/timezone/chunk_delay/stream-интервалы/
  max_message_chars/filter) остались в `limits_summary`/`flags_summary` ВНЕ
  секций; legacy-модельный слот НЕ создавался (описание группы объясняет
  наследование). TAB_RULES mod_summary правил in-place (21 без роста),
  `_TAB_BY_GROUP` 100→105. `web/app.js`: WORKSPACE_TABS mod_summary +=
  'hybrid','legacy'; WORKSPACE_TAB_LABELS: 'HYBRID SUMMARY'/'LEGACY SUMMARY
  FALLBACK'; `workspaceGroupTab` — id-маппинг (hybrid: flags/models/limits_
  summary_hybrid; legacy: flags/limits_summary_legacy) ДО категорийных
  правил → keys-записи группы models_summary_hybrid рендерятся в hybrid;
  `currentTabGroups`/`workspaceTabHasContent` += обе вкладки; зеркало
  TAB_RULES в `TABS[].sources` (mod_summary) обновлено. Cross-isolation на
  уровне групп каталога + тестах (см. T-3960).
- **T-3954 [x]** подпись MAX_SUMMARY_PARTS в каталоге — VERBATIM §13:2445–2449:
  «Максимальное число обычных Telegram-сообщений, на которые может быть разбит
  Legacy Summary. Не влияет на Hybrid Article.» (проверена точным равенством в
  `test_t3960_16_max_summary_parts_signature_verbatim` и в браузере — S3).
- **T-3955 [x]** Инвентаризация summary-ключей (все 34 categorized + 6 legacy-
  фильтровые; имена объясняют принадлежность; hot-резолв не перетекает):

  | pg_key | env-слой | контур | где резолвится |
  |---|---|---|---|
  | limits.max_summary_parts | MAX_SUMMARY_PARTS(1; прод 6) | Legacy | summary_generator prompt-budget+send-cap |
  | limits.summary_max_context_tokens/_chars | SUMMARY_MAX_CONTEXT_* | Legacy | `_run_legacy_pipeline`, `_apply_filter(hybrid=False)` |
  | limits.summary_hybrid_context_tokens/_chars | SUMMARY_HYBRID_CONTEXT_* (None→30000/120000) | Hybrid | `resolve_hybrid_context_budget` |
  | limits.summary_hybrid_response_mode | SUMMARY_HYBRID_RESPONSE_MODE(serious) | Hybrid | `resolve_hybrid_length` |
  | limits.summary_hybrid_target_chars/_paragraphs | =0 (по пресету) | Hybrid | `resolve_hybrid_length` |
  | limits.summary_hybrid_max_chars | 24000 | Hybrid | WARN L2_OVER_SOFT_CEILING |
  | flags.summary_hybrid_l2_enabled | SUMMARY_HYBRID_L2_ENABLED(True) | Hybrid kill-switch | `_hybrid_l2_enabled` (без изменений байт-в-байт) |
  | flags.summary_hybrid_l1_repair_enabled | SUMMARY_L1_REPAIR_ENABLED(True) | Hybrid Recovery | `_repair_enabled` |
  | flags.summary_hybrid_l1_retry_enabled | SUMMARY_L1_RETRY_ENABLED(True) | Hybrid Recovery | `_retry_enabled` |
  | flags.summary_legacy_fallback_enabled | SUMMARY_LEGACY_FALLBACK_ENABLED(True) | LEVEL-3 гейт | `_legacy_fallback_enabled` |
  | models/keys.summary_l1_* / summary_l2_* | SUMMARY_L1_*/SUMMARY_L2_* | Hybrid слоты | `resolve_l1_slot`/`resolve_l2_slot` (без изменений) |
  | prompts.summary_l1_clusterizer_system_prompt / l2 | — | Hybrid | resolve_prompt (канон R1027) |
  | limits.summary_filter_* / flags.summary_filter_* | … | общие | `_apply_filter` (вне секций, S1/S2) |
  | limits.summary_throttle/timezone/chunk_delay/retry_once_pause/stream_* | … | общие | `_run`/доставка (вне секций) |

  Legacy-класс-резолверы старые hybrid-ключи не читают и наоборот
  (`test_budget_resolver_ignores_legacy_keys`,
  `test_hybrid_mode_uses_hybrid_context_keys`).

### Group F — observability + graph memory

- **T-3956 [x]** 7 новых событий (все аддитивны, имена существующих не
  переименованы — таблица маппинга §18→фактические события в spec (k)):
  `L1_PARSE` (attempt/parse_status/raw_chars), `L1_REPAIR` (все поля
  RepairReport + attempt), `L1_CORRECTION_RETRY` (WARN attempt/reason — коды),
  `L1_FALLBACK_PACKAGE` (WARN reason/fragments/chronology), `LEGACY_FALLBACK`
  (WARN reason/calls_so_far — включая строку «ВЫКЛЮЧЕН» при kill-switch OFF),
  `LEGACY_CHUNKS_CAPPED` (chunks_total/chunks_sent), `L2_OVER_SOFT_CEILING`
  (chars/max_chars). Поля §18: FILTER_COMPLETE += messages_before/messages_after/
  serialized_chars/serialized_tokens (serialized-оценка Q5); L2_START +=
  response_mode/target_chars/target_paragraphs; L2_COMPLETE += chars (`trimmed=`
  удалён); FACT_PACKAGE_COMPLETE += topics=/messages=; L1_COMPLETE += attempts
  (из partial); SUMMARY_COMPLETE += fallback=none/legacy + publication_status.
  R17: списки unknown-id — только в correction-промпт, в логи — счётчики
  (`test_unknown_id_correction_lists_ids_in_prompt_only`,
  `test_t3956_l1_pipeline_events_and_fields` с secret-assert).
  §110-фильтр «Саммари»: новые события попадают существующими префиксами
  `L1_`/`L2_`/`run_id=` (L1_PARSE/L1_REPAIR/L1_CORRECTION_RETRY/
  L1_FALLBACK_PACKAGE/L2_OVER_SOFT_CEILING) и `run_id=`/`LEGACY_*` —
  L1_FALLBACK_PACKAGE содержит run_id=, LEGACY_FALLBACK/LEGACY_CHUNKS_CAPPED
  — run_id=; правка JS-списка НЕ потребовалась (проверено чтением
  `logSummaryMarkers`); `SUMMARY_FAILED` в `L2_ERROR`-сценариях не дублируется.
  Тесты: `tests/test_summary_asap2_observability_round1027.py` (5, PASS) +
  обновлённый `tests/test_summary_logging_runid.py` (36, PASS).
- **T-3957 [x] (verification-only)** граф НЕ переписывался: (1)
  `GraphExtractionError`/`LLMTimeoutError` по-прежнему ловится в
  `_compress_purge_extract_only` (graph-сценарии
  `tests/test_summary_asap_hotfix_round1027.py` перенесены без изменений — PASS);
  (2) hybrid-цепочка не интерпретирует граф-ошибки как SUMMARY failure:
  граф-ветка `_run` (compress_and_purge/memorize fire-and-forget) вне
  try-блоков публикации; `_run_legacy_pipeline` graph_facts lookup — fail-open
  `graph_facts = []` (AST-пин `test_run_logic_ast_identical_to_baseline`
  сохраняет `_generate_two_call`/`_llm_generate` байт-в-байт); (3) граф-сценарии
  сохранены при переписывании trim-тестов.

### Group G — приёмка §17 и прогоны

- **T-3958 [x]** §17 тесты 1–9 + failure-case 5 + пресеты + serialized-бюджет:
  `tests/test_summary_asap2_acceptance_round1027.py` — 13 PASS
  (1 parts=1→8 абзацев полная; 2 send-кап (unit cap-helper + интеграционный
  warn-тест в publish-integration); 3 id в двух темах VALID + topic_ids;
  4 reply-в-одной-смыслово-в-другой VALID; 5 unknown id → repair без retry;
  6 overlapping → FactPackage строится; 7 дедуп-инструкция в каноне + mock-статья
  без дублей; 8 умеренный over-target не режется; 9 under-target не ошибка;
  30000 симв. → WARN+публикация; 33000 → too_long; пресеты 4000/5,6500/8,
  11000/14, 24000/32000; serialized > text-only, граница бюджета).
- **T-3959 [x]** §17 тесты 10–13 + worst-case≤5 + guard + no-UX-spam:
  `tests/test_summary_asap2_failsoft_round1027.py` — 8 PASS (mock-транспорт
  QueueLLM/AsyncMock, 0 реальных LLM/Telegram).
- **T-3960 [x]** §17 тесты 14–16 + browser S1–S7:
  `tests/test_summary_asap2_miniapp_round1027.py` — 8 PASS (состав секций по
  каталогу, human-readable описания, общие вне, verbatim-подпись,
  cross-isolation ключей, JS-маркеры, TAB_RULES/счётчики).
  **Browser-verification (Playwright MCP, REQUIRED) — S1–S7 зелёные**:
  стенд = ТОТ ЖЕ webapp `web.app.create_app` на тестовом ConfigCache-стабе из
  `tests/test_webapp_api.py` (механизм тестовой админ-сессии проекта;
  loopback 127.0.0.1:8137; без prod-credentials/Telegram Bot API; серверный
  скрипт временный, удалён после прогонов; entry `#/modules/summary`):
  - S1 ✓ две отдельные вкладки «HYBRID SUMMARY»/«LEGACY SUMMARY FALLBACK»,
    общие (Обзор/Основные настройки/Подготовка/Кластеризатор/Писатель/Модели/
    Тестирование) вне секций — скриншоты
    `tools/asap2_s1_hybrid_desktop.png`, `tools/asap2_s3_legacy_desktop.png`.
  - S2 ✓ структура hybrid-вкладки = 15 гибрид-параметров точно по составу (j):
    enabled/repair (basic) + retry (под «Расширенные системные» — существующая
    F-11 progressive-механика, не регресс), L1/L2 model/base_url (+secret key),
    context tokens/chars, селектор режима ровно 3 опции (casual,serious,
    deep_research — проверено DOM `<option>`), target chars/paragraphs,
    max_chars; человеческие описания.
  - S3 ✓ legacy-вкладка: «Legacy fallback включён», MAX_SUMMARY_PARTS=6,
    описание ДОСЛОВНО содержит «Не влияет на Hybrid Article» (DOM-подтверждено).
  - S4 ✓ cross-isolation: на legacy-вкладке нет ни одного hybrid-параметра,
    на hybrid — нет legacy (`legacyAbsentInBody`/`hybridAbsentInBody`, id-маппинг
    `workspaceGroupTab` + групповой состав каталога + JS-харнесс
    `tests/js/round1027_asap2_summary_sections_test.js` → ASAP2-SUMMARY-SECTIONS-OK).
  - S5 ✓ toggle → ровно 1 POST /api/config (200) → reload → значение сохранено
    (и обратно); mode-switch покрыт select-значением (Serious default).
  - S6 ✓ mobile 390×844: обе секции без горизонтального overflow
    (scrollWidth==clientWidth), скриншоты
    `tools/asap2_s6_legacy_mobile.png`/`tools/asap2_s6_hybrid_mobile.png`;
    тач-цели = существующий дизайн-системный виджет (10 мелких элементов —
    те же, что на прежних вкладках, не регресс ASAP-2).
  - S7 ✓ console: 3 ошибки за всю сессию — favicon 404, avatar 404,
    chat_lore 503 (pre-existing env-ресурсы, НЕ конфигурация/ASAP-2); ошибок
    app.js/Vue нет; api_key рендерятся masked-виджетом (badge «скрыт» +
    `••••alue`, существующая механика adr-1025-22 — видно на S1-скриншоте).
- **T-3961 [x]** полные прогоны (см. «Прогоны» ниже): полный pytest зелёный;
  JS-харнесс 49/49 exit 0; `git diff --check` в scope чист (2whitespace-флага
  в plans/features/mca-asap-summary-hotfix/ — НЕ мои файлы, из baseline
  рабочего дерева); R17-скан диффа: raw-текстов/secret в добавленных строках
  нет (только коды/числа/id; id-списки только в correction-промпт).
  Новый baseline: 9913 passed / 0 failed (было 9851/9859; +34 новых
  ASAP-2-теста, 0 удалённых кроме переписанных trim).

### Group H — релизная механика

- **T-3962 [x] (без финального коммита)** APP_VERSION 2.58.33 (механика 270c277:
  комментарий-провенанс bump 2.58.32→2.58.33; версия-пины во всех 23+
  py-пиннах и 4 JS-харнессах уже были переведены на 2.58.33 partial-коммитом и
  сверены — `test_app_version_*` PASS); README «Версия»-строка переписана под
  ASAP-2; F8-ПЕРЕИЗДАНИЕ: `tools/gen_param_registry_round1025.py` перегенерировал
  `param-registry-round1025.tsv` (489 строк, дельта 411→489=78),
  `param-registry-round1025.meta.md` (счётчики 489/107/105/21, APP_VERSION
  2.58.33), fixtures `f8_baseline.json`/`catalog_baseline.json` (counts,
  registry_keys, group_ids, group_tab, sha256 param_catalog), скрин-карта;
  счётчик-пины обновлены (473→489, 102→107, 100→105, 448→464, secrets 28→30,
  categorized 464, NON_PREFIXED += 2 keys.summary_l*_api_key → models_summary_hybrid
  с санкцией). Δ каталога +16/+5 — намеренный (spec (j)/(n)); Δ DDL=0;
  `test_routes_file_unchanged` не трогался (routes.py вне диффа — sha256
  пин PASS); финальный релизный коммит/номер — Orchestrator+Reviewer.
- **T-3963** — НЕ Builder (деплой после Reviewer Approved; план деплоя/отката
  в spec §8; прод-проверка hot-ключей и DoD-13…16 по §18-логам).

## Прогоны (команды и фактические результаты)

- `.venv\Scripts\python.exe -m pytest tests/ -q` → **9913 passed, 0 failed**
  (3m29s; финальный прогон после всех правок; warning — предсуществующий
  Starlette testclient deprecation).
- ASAP-2 срез: `pytest tests/test_summary_asap2_acceptance_round1027.py
  tests/test_summary_asap2_failsoft_round1027.py
  tests/test_summary_asap2_miniapp_round1027.py
  tests/test_summary_asap2_observability_round1027.py
  tests/test_summary_l1_repair_round1027.py
  tests/test_summary_asap2_l1_retry_round1027.py` → 57 passed.
- Summary-контур: `pytest tests/ -q -k "summary or round1026 or round1027 or asap"`
  (на моменте после групп A–D, до re-pin'ов) → 1946/1946 после починки.
- JS-харнессы: все `tests/js/*.js` node-прогоном → **49 файлов, 0 failed**,
  включая новый `tests/js/round1027_asap2_summary_sections_test.js`
  (ASAP2-SUMMARY-SECTIONS-OK) и обновлённый `round1025_f5_workspace_route_test.js`
  (MODULE-WORKSPACE-OK с hybrid/legacy в карте).
- F8: `python tools/gen_param_registry_round1025.py --check` → OK (exit 0).
- `git diff --check` (scope services/ config/ web/ tests/) → чисто.
- rg-инварианты: `SUMMARY_L2_TRIM_ENABLED|_trim_document_for_publication|
  trimmed_for_publication|REASON_MESSAGE_IN_MULTIPLE_THREADS` в services/config → 0;
  `max_summary_parts` — только разрешённые legacy-места (см. T-3935).

## Отклонения от spec

1. **Единицы useless-формулы** (spec Q3 букв.: `unknown_ids_removed /
   ids_referenced_before > 0.5`): числитель — **вхождения** (шаг 1 контракта
   (b) «за вхождение»), знаменатель — **distinct** (определение
   `ids_referenced_before` в Q3). Реализовано ровно так; пример владельца
   (1 из 4 = 25%) и §17-тест 5 (1 unknown при 2 distinct → 0.5 НЕ > 0.5 →
   продолжаем) зелёные. Отклонений нет — зафиксировано трактовкой spec.
2. **PG-only форма 16 новых ключей** (вместо dataclass-полей): все hybrid-
   резолверы читают `hot_get(key, env ClassVar)`; env-имена зафиксированы
   Q6/(f)/(g) и НЕ совпадают с pg-именами для repair/retry — pg_idoverride
   (прецедент `_MODELS_PG_ONLY`); dataclass-поле count остаётся 430
   (тест-пины `== 430` не тронуты). Покрытие coverage-аудита не сломано.
3. **retry/context-ключи скрыты под «Расширенные системные»** во вкладке —
   существующая progressive-механика F-11 (маркеры `retr`/`context` в
   `_ADVANCED_KEY_MARKERS`); значения доступны и сохраняются (S5 прошёл на
   repair-флаге basic). Если владелец захочет basic — одна явная
   `progressive_level` правка, вне spec-контракта (не делал).
4. **legacy-mode resolution в `_apply_filter`**: `_run` передаёт уже
   резолвнутый `hybrid`; dry-run (`build_test_rows`) передаёт `hybrid=True`
   явно (инвариант S9 «глобальный флаг не читается» сохранён).

## Что осталось Reviewer/DevOps

- Independent review диффа (оба линза: requirements/correctness + change audit);
  binding к текущему рабочему дереву (HEAD e882d58 + uncommitted ASAP-2 files).
- Playwright-отчёт S1–S7 — Builder-скриншоты/ассерты выше; Reviewer должен
  независимо повторить (критерий гейта T-3963).
- Prod-деплой T-3963: feat-коммит (код+тесты+пины) → docs-коммит → reconcile
  (merge ADR-1027-10 в ARCHITECTURE) → DevOps `git pull --ff-only` + рестарт
  `admin_bot`; после деплоя — проверка `limits.summary_hybrid_*`,
  `flags.summary_legacy_fallback_enabled`, legacy `limits.max_summary_parts=6`,
  прод-логи §18 (цепочка читается как pipeline, `fallback=`) на реальном
  саммари `-1002661910336`.
- Partial same-prompt retry (`git diff` clusterizer/settings до правки) полностью
  переработан в correction-семантику — отдельного коммита partial нет и не будет.

## Rework review-раунда 1 (2026-09-28, findings review.md)

Выполнены только finding-правки, механика/тесты/config-значения НЕ менялись:

- **H1 [x]** `config/settings.py` — changelog-хунка `APP_VERSION = "2.58.33"`
  переписана под ФАКТИЧЕСКУЮ реализацию ASAP-2 (correction retry ≤1 после
  deterministic repair `summary_l1_repair.py` между parse/validate с формулой
  uselessness и reason `l1_useless_after_repair`; threads-v2 `schema_version: 2`
  many-to-many, `message_in_multiple_threads` УДАЛЁН из фатальных и из
  retryable-набора; trim 2.58.32 УДАЛЁН §16; `limits.max_summary_parts`
  строго Legacy (prompt-бюджет + send-кап ≤parts, WARN `LEGACY_CHUNKS_CAPPED`);
  presets 4000/6500/11000 soft-target, 24000=WARN без обрезки, >32000=too_long→
  Legacy; fail-soft LEVEL-1/2/3, общий `_run_legacy_pipeline`, published-guard,
  worst-case ≤5; Δ каталога +16 (F8 489/107/105/21), каноны L1/L2 R1027
  PREV_*/ROLLBACK — «промпты изменены»; hot-ключи Recovery + env-слой; откат
  `SUMMARY_HYBRID_L2_ENABLED=false`; Δ DDL=0; R17-safe). Прежняя хунка 2.58.32
  сохранена в истории с пометкой «ИСТОРИЧ: SUPERSEDED в 2.58.33, trim-костыль
  удалён §16» (только вставка маркера).
- **L1 [x]** `services/summary_l1_contract.py:361` — комментарий «== 1» →
  «== SCHEMA_VERSION (v2: ровно 2)».
- **L2 [x]** `services/summary_l1_clusterizer.py` — докстрока бюджета
  (константный блок ~:89) и run_l1-докстрока `budget=None` (~:686–691):
  stale-ссылки на `limits.summary_max_context_*` заменены на фактический
  гибрид-резолв (`resolve_hybrid_context_budget`); константы
  `L1_CONTEXT_TOKEN_DEFAULT/CHARS_ENV` помечены историческими (не удалялись —
  механика не трогается).
- **L3 [x]** `config/settings.py` ASAP-2-блок (:1098–1102) — формулировка про
  `limits.max_summary_parts` согласована с H1 (не наследуется Hybrid; строго
  Legacy-контур).
- **M1 [x] (коррекция записи)** Ранее в handoff я заявил «нормализованы
  BOM/CRLF в ~50 чужих файлах». По результатам byte-level скана Reviewer'а
  (review.md, «Вердикт по BOM/CRLF-выборке») это **неверно как описано**:
  EOL/BOM-only tracked-файлов в дереве — **0**; все изменённые файлы имеют
  содержательные диффы. Фактическая атрибуция: содержательные диффы чужих
  файлов (включая `handlers/summary.py`, `web/index.html`, `services/
  summary_memory.py`, `database.py`, `bot.py`, `tools/*`, ~80 tests/js и
  прочих из git status) принадлежат **параллельной незакоммиченной MCA-волне
  round1027** и к ASAP-2 отношения не имеют. Правки ASAP-2 в чужих файлах —
  только санкционированные scope-файлы (полный список — ниже). Это
  корректирующий запись фикс; дерево в этом раунде не перенормализовывалось.
- **M2 [x] (запрет стейджинга)** `handlers/summary.py` и `web/index.html`
  из прежнего scope-перечня handoff содержат **только MCA-правки** (MCA-03 /
  MCA-17a/shell-волна): в ASAP-2 feat-коммит (T-3963/Q8) НЕ включать;
  не включать также MCA-волну (`services/mca_*`, `services/database.py`,
  `summary_memory.py`, `bot.py`, `tools/history_import/*` и др. из git
  status). Staging — строго по списку scope-файлов ниже + собственные
  ASAP-2 untracked.

### Scope-файлы ASAP-2 (трекинг для feat-коммита и binding-хэша)

Тот же перечень, по которому Builder считает scope tracked-diff SHA-256
(35 файлов; README/plans — docs-коммит отдельно, Q8):

services/summary_l1_contract.py, services/summary_l1_clusterizer.py,
services/summary_l2_writer.py, services/summary_fact_package.py,
services/summary_generator.py, services/summary_prompts.py,
services/prompt_migrations.py, services/summary_run_log.py,
services/param_catalog.py, services/summary_article_formatter.py,
config/settings.py, web/app.js, plans/docs/canon/architecture.md,
plans/docs/param-registry-round1025.tsv,
plans/docs/param-registry-round1025.meta.md,
plans/docs/screen-map-round1025.md, tests/fixtures/round1025/f8_baseline.json,
tests/fixtures/round1025/catalog_baseline.json,
tests/js/round1025_f5_workspace_route_test.js,
tests/test_summary_asap_hotfix_round1027.py, tests/test_summary_l1_clusterizer.py,
tests/test_summary_l2_writer.py, tests/test_summary_fact_package.py,
tests/test_summary_publish_integration_round1026.py,
tests/test_summary_deploy_round1026.py, tests/test_summary_logging_runid.py,
tests/test_summary_l2_integration.py, tests/test_summary_filter_integration.py,
tests/test_summary_test_run.py, tests/test_summary_test_api.py,
tests/test_tool_coordinator_round1026.py, tests/test_frontend_tab_mapping.py,
tests/test_param_catalog.py, tests/test_prompt_migrations.py,
tests/test_round1025_f8_registry.py.

> Примечание: точный список 35 scope-файлов review-хэша
> `60E8ED87…BD5468E7` (452 047 bytes) в review.md **не перечислен** (в
> заголовке только счётчик «35» и таблица untracked). Построенный Builder'ом
> выше перечень даёт 35 файлов / 457 110 bytes на том же дереве — на 5 063
> байта больше, т.е. список Reviewer'а отличался составом (байтовые
> совпадения не сходятся ни с одной однозаменающей комбинацией). Новый
> binding-хэш Builder возвращается **по этому зафиксированному списку**;
> Reviewer'у в раунде 2 — пересчитать по нему же (или объявить точный
> список в review.md). Untracked-файлы (9 из таблицы review.md) в этом
> rework-раунде НЕ изменялись — их sha256 совпадают (проверено прогоном
> ниже).

### Прогоны после rework-раунда 1

- `python -m pytest -k "summary" -q` → **1168 passed / 0 failed / 8745 deselected** (81.16 s; подтверждено независимым прогоном Reviewer, round2)
- 6 ASAP-2-файлов + repair + hotfix → **73 passed / 0 failed** (5.14 s; подтверждено прогоном Reviewer, round2; `node tests/js/round1027_asap2_summary_sections_test.js` — exit 0 `ASAP2-SUMMARY-SECTIONS-OK`)
- `node tests/js/round1027_asap2_summary_sections_test.js` → OK


