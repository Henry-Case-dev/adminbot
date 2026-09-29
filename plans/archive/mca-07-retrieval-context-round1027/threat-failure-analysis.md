# `mca-07-retrieval-context` — threat / failure analysis (R3; вход T-3857)

- **Risk:** **R3** (spec §Risk / ADR-1027-7 D12). Ошибка теряет адресата/ветку/
  ограничения, смешивает несовместимые векторы, переполняет полный запрос или
  отдаёт устаревшую сводку/старый ответный кеш.
- **Область:** retrieval/reranker/evidence-bundle/budget/summary/answer-cache.
- **Статус:** подготовлено @Builder Step 3; финальный вердикт/понижение — @Reviewer.

## 1. Модель угроз (что ломается и как это видно)

| ID | Угроза | Вектор | Парирование (реализовано) | Тест |
|---|---|---|---|---|
| T1 | Потеря адресата/ветки/ограничений между retrieval и формулировкой | постадийная сборка без единого объекта | ЕДИНЫЙ `EvidenceBundle` (§11.2) в живом конвейере: решение→tools→synthesis(System2)→формулировка; System2 после tool loop получает scoped-срез (адресат/ветка/ограничения/`context_version`) | `test_system2_receives_bundle_after_tool_loop`, `test_bundle_scoped_slice_for_system2`, `test_a04_different_branch_different_context_version` |
| T2 | Возврат ВСЕХ кандидатов при пустом/битом ответе reranker | fail-open `errors→original` | типизированный `RerankResult`; valid-empty → пусто; invalid/timeout/error → отдельный статус + bounded fallback | `test_valid_empty_does_not_return_all_candidates`, `test_invalid_bounded_fallback_not_all` |
| T3 | Смешивание векторов при смене модели той же размерности | dim-проверка как доказательство совместимости; стартовая регистрация «затирает» активное поколение | identity-fingerprint + `dim` defense-in-depth + durable поколения v18; **B-MCA07-1:** активное поколение НЕ перезаписывается на старте; обслуживание только при `status='active'` И fingerprint==current, иначе FTS-only | `test_embedding_identity_key_same_dim_different_model`, `test_register_generations_does_not_overwrite_active`, `test_generation_registry_quarantine_building`, `test_generation_registry_no_supersede_on_model_change` |
| T4 | Переполнение полного запроса (не учтены system/tools/reserve) | учёт только user-блоков; external не передавался из живого call-site | **B-MCA07-2:** `_build_user_content` передаёт `external_tokens` (system+personality+tools schemas)/`reserve_tokens`/`estimation_method`; pre-flight `context_overflow` + деградация | `test_live_call_site_passes_external_payload`, `test_live_preflight_overflow_on_mandatory`, `test_estimate_external_payload_tokens_positive` |
| T5 | Обрезка отрицания/ID/даты меняет смысл | keep-end/keep-head без защиты | protected spans переносятся в защищённый хвост при обрезке | `test_protected_spans_preserved_when_truncating` |
| T6 | Поздний старый summary перезаписывает новую версию | слепой UPSERT | HWM/CAS по `(window_end_ts, raw_count)`; singleflight | `test_running_summary_cas_rejects_stale` |
| T7 | Старый ответный кеш отдаёт ответ для иного родителя/ветки | text-replay по нормализованному query/chat/user | ON: text-replay отключён; update-дедуп `(chat_id,tg_message_id)` сохранён | `TestHandleDedup::test_context_policy_on_disables_text_replay` |
| T8 | Регрессия legacy при выкатке | новые политики без отката | 6 env-only kill-switch, default ON, OFF = паритет baseline | `test_mca07_kill_switches_registered_and_default_on` + OFF-тесты |
| T9 | Утечка секретов/сырого контекста в логи/события | диагностика | только id/коды/числа; `sanitize()`/`emit_mca_event` контракт; SourceRef вместо сырья | R17-контракт `mca_events` (регрессии mca-13) |
| T10 | Несовместимая перестройка vec-индекса в hot-path | ALTER/rebuild vec0 | v18 vec-таблицы НЕ трогает; перестройка — `mca-04b` (v19+) | `test_v18_vec_tables_untouched_and_idempotent` |

## 2. Failure-сценарии и деградация

- **Reranker error/timeout/invalid:** отдельно наблюдаемое состояние
  (`reason_code` `rerank_invalid`/`rerank_timeout`) + детерминированный
  pre-rerank-bounded fallback (top_k). НЕ равно valid-empty и НЕ равно «все
  кандидаты».
- **Embedding/БД-ошибка retrieval:** канал пропускается; при пустоте всех —
  `status=empty`/`reason_code=retrieval_empty` (честная деградация, без подмены).
- **Budget overflow:** mandatory-часть не влезает → WARN + `context_overflow`
  (сигнал на доп. retrieval/суммирование/уточнение); pre-flight не «отправляет
  заведомо переполненный запрос» на уровне бюджетного слоя.
- **Summary CAS:** поздняя запись отклоняется (return False) + `summary_stale_dropped`.
- **Kill-switch OFF:** каждый из 6 гейтов даёт точный legacy-путь.

## 3. Остаточные риски (для @Reviewer)

1. **A04 на полном `handle`-e2e** не прогонялся — покрыт на уровне точек
   конвейера (ветка→`context_version`, System2-срез, отсутствие text-replay) +
   зелёный регрессионный набор `direct`; при желании Reviewer может добавить
   `handle`-e2e.
2. **`retrieve()` в живом direct-пути** пока не вызывается (контракт готов;
   решение о retrieval — зона `mca-09`/`mca-10b`/`mca-15`) — **carry-over
   L-MCA07-5**, требует подтверждения @Architect.
2a. **M-MCA07-2 carry-over:** поля §11.2 `ambiguities/local_context/persona/
   interests/unknown/contradictions` живой builder не заполняет (семантика —
   `mca-09`/`mca-16`/`mca-05`; иначе дублирование архива/§11.2) — **требует
   подтверждения @Architect**.
2b. **`_index_generation_ok` при отсутствии записи** возвращает True (fail-open
   для БД без реестра/тест-двойников); на пути инициализации регистрация
   гарантирует `active`/`building`, поэтому legacy-векторы без записи
   карантинятся (`building`).
3. **Стоимость bundle-среза:** добавление ~5 строк в Stage-1 System2 (небольшой
   рост input-токенов; в общем бюджете System2 не учитывается — это отдельная
   стадия после tool loop).
4. **Проверка `EXPLAIN QUERY PLAN`** для 3 индексов v18 на реальном объёме не
   выполнялась (обосновано shape’ом запросов).
5. **PG no-op** подтверждён по коду, не на PG-инстансе.
6. **`identity_fingerprint` при неверном `EMBEDDING_DIM`:** fingerprint строится
   по конфигурируемой размерности; при расхождении факт. длины защищает
   `dim`-проверка (defense-in-depth) и self-heal vec — но конфиг-дрифт остаётся
   операционным риском (наблюдается WARNING `EMBEDDING_DIM != actual`).
7. **Порог protected-span резерва** (48 токенов) — эвристика; при экстремально
   плотных спанах часть может не влезть (append только при вместимости).

## 4. Триггеры понижения до R2 (spec §Risk)

Доказанная изоляция retrieval/бюджета от hot-path записи; A03/A04/A05/A06/A24
на фактическом diff; отсутствие перезаписи/удаления legacy-строк. T-3852
закрыта; A04 доказана на уровне точек конвейера (полный `handle`-e2e — опция
Reviewer). Понижение до R2 возможно, если Reviewer подтвердит A03/A04/A05/A06/A24
на фактическом diff и отсутствие перезаписи legacy-строк.
