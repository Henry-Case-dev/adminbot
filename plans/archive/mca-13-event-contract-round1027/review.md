# `mca-13-event-contract` — ревью (повторный единый gate волны 0 MCA, round 10.27)

> **Feature-ID:** `mca-13-event-contract`. **Risk-Level:** **R2** (ратифицирован @Architect, AMEND-3; триггеры R3 не сработали).
> **Status: Approved.**
> **Дата / агент:** 26.09.2026, @Reviewer (обе линзы в одном gate; Scanner отсутствует).
> **Deploy:** `DEFERRED_TO_RELEASE` (§20; коммитов НЕТ; `APP_VERSION` 2.58.31 без bump).
> **Цикл:** итер.1 — `Needs Fixes` (B-MCA13-1 High, B-MCA13-2 Medium) → rework @Builder + санкция @Architect (carry-over) → **итер.2 — Approved** (binding новый).

## Binding (точное ревьюируемое состояние)

- **Git base:** HEAD `05bc8704c2de5e7de1d5d04ac34df763d35219aa`. Все изменения — **не закоммичены**; ревью рабочего дерева.
- **Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa`.
- **Diff-SHA256 (`git diff --binary HEAD`):** `fbf2eea45be890fb32925b3de67d9039a92430971efb4ae4618c54ae64058299`.
- **Working-Tree-Hash (59 записей; исключены 7 артефактов ревью/workflow: 4 `review.md`, `full_audit_results.md`, `global_map.md`, `workflow_state.md`):** `9cd581e4549e2fc0fd53599ade14b507b42f87e8a864899c3486e8d78b144a97`.
- **Product-Code-Hash (доп.):** `9d9254187b50c71b6067aa1ad52c4a3cdaad7c1579ee7ed780752a23fab64827`.
- **Spec-Hash:** `c93dcbf827b88dd54565a355bf8d27f2f444a481a31d2425d2d634f79ed1fcbb` (обновлён санкцией @Architect: §1.1 carry-over register; SC-16 `retención`→`retention`).
- **ADR-1027-2-Hash:** `496e90ed237f765be6405078c0a0fb0463e16d7f571b58d876339d4d028f7e3a` (AMEND-1/2/3).
- **tasks-Hash:** `8b796c0c5a51c8ce7abd937299418ae4e9c6524cbcca047c885979615bd31c5c` (T-3773 → `[~]`).

> Хэш рабочего дерева зафиксирован **до** записи этого `review.md`; любая правка кода/спеки после фиксации делает вердикт stale.

## 1. Объём проверки

- **Requirements-линза:** REQ-MCA13-01…10 и SC-01…SC-16 (spec §2/§6), A27/A53, обработка R2-триггеров, совместимость с ExecutionGraph §82–§92 (REUSE, вторая аналитика запрещена).
- **Focused change-audit:** `services/mca_events.py` (контракт §17, `build_event`/`emit_mca_event`/`flush_events`/`prune_events`/`query_events`/`metrics`/`build_error_metadata`), `services/database.py` (v15 `mca_events`/`mca_event_aggregates` + 4 индекса), `services/mca_gates.py`, `config/settings.py`, `services/task_supervisor.py` (эмиссия событий задач).

## 2. Независимый прогон (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9588 passed, 0 failed** (1 FastAPI-deprecation warning) |
| mca-13 suite | `pytest tests/test_mca13_event_contract_round1027.py` | **25 passed** |
| JS vm-харнесс | `node` по всем 47 `tests/js/*.js` | **47/47 ok** |
| Git hygiene | `git diff --check` | чисто (exit 0) |

Совпадает с evidence (`9588/0`, `47/47`, mca-13 `25`).

## 3. Coverage REQ/SC → evidence

| REQ | SC | Evidence | Итог |
|---|---|---|---|
| REQ-01 JSON-событие §17.1 | SC-01, SC-02 | `test_build_event_contract_fields`, `test_build_event_drops_unsafe_fields` | ✅ |
| REQ-02 start/terminal/`interrupted`, нет `except: pass` | SC-03, SC-04 | `test_emit_start_and_terminal`, `recover_stale`→interrupted | ✅ |
| REQ-03 поля по типам, без CoT | SC-05 | `test_per_type_fields_present`, `test_per_type_fields_decision_context_archive_dream` | ✅ |
| REQ-04 словарь `reason_code` | SC-06, SC-07 | `test_reason_dictionary_has_minimum`, `test_unknown_reason_code_dropped_not_skip` | ✅ (SC-07 влияние/fallback — см. L-MCA13-5) |
| REQ-05 ошибки/агрегация | SC-08, SC-09 | `test_error_aggregate_keeps_count_and_first_trace`, `test_error_metadata_has_cause_and_masked_stack` | ✅ |
| REQ-06 маскирование R17 | SC-10 | `test_masking_of_secrets_in_event_and_log` (caplog+eвент), `test_masking_persisted_durable_mca_events` (durable-строка) | ✅ |
| REQ-07 ретенция 14/90, bounded буфер | SC-11, SC-12 | `test_retention_prune`, `test_buffer_bounded_with_visible_gap` | ✅ |
| REQ-08 метрики §17.4, `UNKNOWN`≠0, фильтры | SC-13, SC-14 | `test_metrics_covers_17_4_groups_with_unknown`, `test_metrics_computes_real_groups_from_store`, `test_metrics_unknown_not_zero_when_unavailable`, `test_query_events_reason_filter_and_limit` | ✅ backend; UI — санкц. carry-over (§1.1/AMEND-1) |
| REQ-09 совместимость ExecutionGraph §82–§92 | SC-15 | `web/**`/routes вне diff; вторая аналитика не создана | ✅ |
| REQ-10 deploy/R17 e2e | SC-16 | kill-switch-тесты + e2e-маскирование | ✅ |

**tasks.md статусы:** T-3767…T-3772, T-3774 правдивы; **T-3773 → `[~]`** (санкц. перенос); T-3775 `[~]`.

## 4. Проверка закрытия B-MCA13-1 (High, итер.1) — R17/SC-10

- **Локация фикса:** `services/mca_events.py:156-188` (`build_event`) и `:194-212` (`_emit_log`).
- **Механизм:** (i) `_JSON_FIELDS` → `sanitize(json.dumps(value))[:2000]`; (ii) `_SHORT_FIELDS`/`_ID_FIELDS`/несекретные `_CODE_FIELDS` → `_safe_value` **+** `_sanitize_str`; (iii) `_emit_log` применяет `sanitize()` к итоговой строке (defense-in-depth).
- **Независимая проверка:** `sanitize` (`services/log_ring.py:65-84`) маскирует `sk-/gsk-/or-/tvly-`-префиксы, bearer, URI-креды и литеральные секреты каталога (`***`). Воспроизведение итер.1 (`component="sk-abcdefghijklmnop123456"`, `source_ref_json` с токеном) теперь даёт `sk-***` в событии, в логе (`caplog`) и в durable-строке `mca_events`. Оба e2e-теста проверяют **отсутствие исходного значения** и наличие `***`; прежний фиктивный тест заменён. **Закрыто.**
- **R2 (ратификация):** триггер «утечка в durable-store» не сработал (маскирование до записи); «конкуренция на hot-path» — не сработал (durable не на hot-path); «неограниченный рост» — не сработал (bounded deque + retention/row-cap). **R2 сохранён** (AMEND-3). ⚠️ При подключении `flush_events` к worker-loop в `mca-17a` — обязательный reassessment триггера конкуренции (кандидат R2→R3) — зафиксировано в spec §1.1 п.5/AMEND-2.

## 5. Проверка закрытия B-MCA13-2 (Medium, итер.1) — SC-13/SC-14

- **Backend реализован:** `metrics(db, runtime=)` отдаёт все 14 групп §17.4 (`tasks` active/pending/queue/age/archive, `lock` exhausted/retry, `providers` latency/errors, `degradations`, `initiatives`/silence, `delivery`, `random`, `cost`, `provenance`/`memory`/`cache`/`downloads`/`runtime`); поле без продюсера → `available=False`/`None`; `degraded_share` при 0 событий = `None` (UNKNOWN≠0). `query_events` фильтрует trace/chat/component/reason с bounded LIMIT (1…1000). Тесты подтверждают реальные группы из `mca_events`/`task_jobs` и runtime-контур.
- **Санкция @Architect (не молчаливое сужение):** UI-часть SC-13/SC-14 (метрики на витрине, переходы из карточек, логи в существующем viewer) перенесена в `mca-17a` — **spec §1.1 carry-over register**, **ADR-1027-2 AMEND-1/2**, T-3773 → `[~]`. Обоснование: D8 запрещает новые endpoint/панели (только REUSE viewer). **Сверено: register/AMEND/T-3773 присутствуют и согласованы.** Закрыто в санкционированной границе.

## 6. Focused audit coverage / counterexamples checked

- **Полнота маскирования:** перечислены все ветки `build_event` (`_JSON/_SHORT/_NUMERIC/_CODE/_ID`) — ни одна строковая ветка не обходит `sanitize`. ✅
- **flush/буфер:** bounded `deque(maxlen=256)`; переполнение инкрементирует `dropped_total` (видимый gap), тест `_PENDING_MAX+5 → dropped==5`. ✅
- **flush-очистка:** `batch=list(_pending)` + popleft только при успехе; при ошибке БД буфер сохраняется; `emit` синхронный → новые события не смещаются. ✅
- **metrics fail-open:** отсутствие `task_jobs`/`mca_events` → группы `unknown`, исключения не пробрасываются. ✅
- **R17:** `flush_events`-ошибка логирует `exc_info` (маскируется фильтрами console/ring); durable-значения уже маскированы. ✅
- **Discovery-замечание (doc):** spec D5 говорит «28 кодов», а §17.2 ТЗ и `REASON_CODES` содержат **27** базовых (§17.2 verbatim) + 5 расширений; требование «минимум §17.2» выполнено, «28» — неточность spec (L-MCA13-6).

## 7. Blocking findings

**Нет.** B-MCA13-1 (High) и B-MCA13-2 (Medium) закрыты; новых блокеров нет.

## 8. Non-blocking (Low / debt)

- **L-MCA13-1 [Low]:** wiring `flush_events`/`prune_events` в worker-loop/shutdown — санкционированный перенос в `mca-17a` (AMEND-2). Зарегистрировано.
- **L-MCA13-2 [Low]:** исправлено — `_emit_log` отражает уровень (WARN/ERROR не как INFO); тест `test_emit_log_reflects_level`. ✅
- **L-MCA13-3 [Low]:** исправлено — добавлен `test_per_type_fields_decision_context_archive_dream`. ✅
- **L-MCA13-4 [Low]:** исправлено — `test_event_kill_switches_env_default_on` (env-чтение `Settings.MCA_EVENT_*`). ✅
- **L-MCA13-5 [Low]:** SC-07 «у WARN/ERROR обязательны влияние/fallback» контрактом не форсируется (нет поля); покрывается `error_json.recovery`/`reason_code` для ERROR; для WARN — слабо. Не блокирует (как и в итер.1).
- **L-MCA13-6 [Low, doc]:** spec D5 «28 кодов» vs фактических 27 (§17.2) — редакционная неточность (зона @Architect/@PM).
- **Ниты @PM:** `retención`→`retention` (SC-16) исправлено; ссылка «Блок C» (tasks:17) — при случае сократить до «B».

## 9. Вывод

R17-маскирование применяется ко всем строковым/JSON-полям до буфера, лога и durable-строки (e2e-тесты подтверждают отсутствие секрета); backend §17.4 реализован и покрыт; UI-перенос санкционирован register'ом/AMEND и отражён в tasks. R2 сохранён. **Approved** на binding выше.
