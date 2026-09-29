# `mca-07-retrieval-context` — независимый Reviewer gate (T-3857, round 10.27, Wave 1)

- **Feature-ID:** `mca-07-retrieval-context`
- **Risk-Level:** **R2** (понижен с R3 — см. «Решение по риску»; триггеры понижения spec §Risk выполнены на фактическом diff).
- **Status:** **Approved** (повторный gate после rework; оба High закрыты, M-1 закрыта, M-2/L-5 санкционированы как carry-over).
- **Deploy:** `DEFERRED_TO_RELEASE` (подтверждено; пер-фичевого тега/bump нет).
- **Роль сессии:** @Reviewer (независимая; код/тесты не менялись, изменён только этот файл `review.md`).
- **Дата:** 27.09.2026.

## Binding

| Что | Значение |
|---|---|
| Reviewed-Commit (HEAD) | `05bc8704c2de5e7de1d5d04ac34df763d35219aa` |
| Git base / inspected scope | baseline `05bc870`; коммитов не создавалось — весь объём **в рабочем дереве**. Staged/cached пусто. Инспектированы tracked-диф `services/`+`config/`+`tests/` (mca-07 и волны 0/1/04a/13/14) и untracked-артефакты mca-07. |
| Working-Tree-Hash | `75D55F538D6E816CC2CC3568D091B2CC28B6E894F84B4DF5FCF7ED7BAD0D4118` |
| Tracked-Diff-SHA256 (unstaged) | `7DF1BDEB91B693E30E6B249F446671E303492F9462EA7C4DA76F0B6421760E1F` |
| Cached-Diff-SHA256 | `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` (пусто) |
| Spec-Hash (SHA-256 `spec.md`) | `943DFE679698FB32C5797C8DDBE9FDBDC43D52AF92899B7494B159C60D6E32D1` ✅ совпал с заявленным AMEND `943DFE67…` |
| Tasks-Hash (`tasks.md`) | `E7C44435788AD0041A78253C54A971E75785877C7FB7AEE1F3897A23D442A171` |
| ADR-Hash (`adr-1027-7-retrieval-context.md`) | `EB7EF5D9F0E29C5C48CB43ADBB657EAD8B210120E2236249B767714CEA93BBB2` ✅ совпал с заявленным AMEND `EB7EF5D9…` |
| Threat-Hash (`threat-failure-analysis.md`) | `4801BAACF6A77DDD2198508D2D94229A8128C270F240DB781DA1D0847E0DE0E0` |
| Evidence-Hash (`evidence.md`) | `DF50702D0B7D7BCB50D195F5D6339A61951A46ABAFA97BE2C155B23AE76EEB59` |
| New code (untracked) | `services/mca_retrieval_context.py` `2623D81E…`; `tests/test_mca07_retrieval_context_round1027.py` `C292E50F…` |

> **Definition Working-Tree-Hash:** SHA-256 UTF-8-манифеста из строк `TRACKED_DIFF_SHA256 <h>`, `CACHED_DIFF_SHA256 <h>` и `UNTRACKED <path>\t<sha256(content)>` (64 untracked-файла после `git ls-files --others --exclude-standard`, отсортированы; исключены `node_modules/**`, `package.json`, `package-lock.json`; **исключён сам `review.md`** как выходной артефакт gate, чтобы запись отчёта не инвалидировала binding). Манифест воспроизводим скриптом из этого ревью.
>
> **Устаревание:** состояние привязано к хэшам выше. Любое изменение кода/тестов/spec/ADR/evidence → binding устаревает. `Spec-Hash`/`ADR-Hash` прошлого ревью (`ACE242D0…`/`7420FBE9…`) заменены.

## Проверки, выполненные независимо

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest (`.venv`) | `.venv\Scripts\python.exe -m pytest -q` | **9758 passed / 1 warning / 0 failed** (215.06 s) — совпало с ожиданием 9758/0 |
| Focused mca-07 | `pytest tests/test_mca07_retrieval_context_round1027.py -q` | **43 passed** (3.49 s) |
| JS vm-харнесс | `node <каждый из tests/js/*.js>` (47) | **47/47 exit 0** |
| Whitespace | `git diff --check` / `git diff --cached --check` | **exit 0** (только LF→CRLF warnings git; cached пусто) |
| B-MCA07-1 repro (мой, не из suite) | скрипт: активное поколение `smart_archive` old-fp → `ensure_embedding_generation(new_fp, activate=True)` | active **не заменён** (gen1 old, `active`); `_index_generation_ok(new_fp)` = **False** → FTS-only ✅ |
| A05 reranker | инспекция + `TestChatRagRerankF4` | `ok\|empty\|invalid\|timeout\|error`; valid-empty → `[]`; invalid/timeout/error → bounded pre-rerank; порядок = оценке; OFF = legacy ✅ |
| Витрина/UI | — | **N/A** — backend/LLM/data-фича; spec не помечен `Browser-Verification: REQUIRED`; UI/виджеты — `mca-17a` вне scope. Playwright/Browser Use не вызывались намеренно. |
| OpenViking/память | — | не требовалась: актуальные ограничения/дефекты связаны авторитетными артефактами (spec §4.4/§8.1, ADR AMEND, ARCHITECTURE §96/§98). |

## Статус прошлых findings (независимая перепроверка на diff)

### B-MCA07-1 (High) — A06/mismatch-политика поколений → **CLOSED**
- **Код:** `database.ensure_embedding_generation(..., activate=)` **никогда не подменяет существующее активное поколение** — при наличии `active` возвращает его как есть; новое создаётся `active` (при `activate=True`, векторы построены текущим конфигом) либо `building` (карантин) только если активного нет (`services/database.py:1890-1894`). `summary_memory._register_index_generations(activate=)` (`:1451-1486`) активирует только для свежих/пересозданных таблиц (dim/schema-rebuild), иначе карантин; `_index_generation_ok` (`:1488-1523`) обслуживает vec **только** если последнее поколение `status='active'` **и** его fingerprint == текущего конфига, иначе FTS-only + событие `embedding_generation_changed`. `_vec_tables_preexisting` / `_rebuild_vec_tables_if_needed` различают «свежие» и «персистентные неизвестные» векторы.
- **Мой repro:** после `ensure(new_fp, activate=True)` при существующем `active` со старым fp durable-реестр остаётся `gen1/active/old`; guard = `False`. Смешивание старой/новой модели при той же размерности невозможно.
- **Тесты (прошли):** `test_generation_registry_no_supersede_on_model_change`, `test_generation_registry_quarantine_building`, `test_register_generations_does_not_overwrite_active` (точный repro предыдущего ревью: смена конфига/рестарт → False; повтор без изменений → True), `test_index_generation_mismatch_forces_fts_only`, `test_fingerprint_lookup_and_idempotent_quarantine`, `test_embedding_identity_key_same_dim_different_model`.
- Вердикт: **закрыт.** Незакрытый остаток — отсутствие API активации нового поколения после фактической перестройки (`mca-04b`) — вынесен в non-blocking debt.

### B-MCA07-2 (High) — полный учёт payload (A24) в живом пути → **CLOSED**
- **Код:** `_build_user_content` при `budgets_enabled AND MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` вызывает `_estimate_external_payload_tokens(chat_id, budget_tokens)` (system/developer-промпт + persona-блок + tools schemas JSON; reserve = `CHAT_BUDGET_RESERVE_RATIO`) и передаёт `external_tokens`/`reserve_tokens`/`estimation_method` в `_apply_context_budget` (`direct_chat_service.py:2093-2104`). Pre-flight `context_overflow` (событие + WARN) + деградация (сброс остаточных cuttable-блоков) + лог `full payload` (`:2837-2848`, `:2947-2976`). Fail-open: ошибка оценки → `(0,0,None)` → legacy-числовая база (паритет).
- **Тесты (прошли):** `test_live_call_site_passes_external_payload` (production-точка реально передаёт external/reserve/method), `test_estimate_external_payload_tokens_positive` (>0 при реальном system-промпте, reserve == ratio×budget, метод из tokenizer), `test_live_preflight_overflow_on_mandatory` (реальный `_build_user_content` → WARN `context overflow`), `test_budget_full_payload_accounting`, `test_budget_off_gate_ignores_external`, `test_protected_spans_preserved_when_truncating`.
- Вердикт: **закрыт.** Остаток (pre-flight = сигнал+деградация, без жёсткого отказа; tool results в учёт не входят — только schemas) — non-blocking observation, не нарушение принятого spec (spec §4.6 допускает «сокращать/суммировать/уточнять», §5 — «честная деградация»).

### M-MCA07-1 (Medium) — `context_version` → **CLOSED**
- Live-builder кладёт `current_revision = current_ref`, включает `current_ref` в `selected_refs` и добавляет `summary_revision` (derived `window_end_ts:raw_count` из `get_running_summary`, fail-open) (`direct_chat_service.py:2106-2188`).
- Тест `test_context_version_includes_current_and_summary` (разные current-ходы → разная версия; summary-ревизия меняет версию) — **прошёл**.

### M-MCA07-2 (Medium) — полнота полей §11.2 живого bundle → **санкционированный carry-over**
- Контракт `EvidenceBundle` **полон** (все поля §11.2 присутствуют, `services/mca_retrieval_context.py:181-208`). Живой builder дополнительно наполняет `mentioned`/`relations`/`recent_actions` (`:2171-2178`). Незаполненные `ambiguities`/`local_context`/`persona`/`interests`/`unknown`/`contradictions` — по spec AMEND §8.1/ADR AMEND `D5` назначены владельцам `mca-09`/`mca-05`/`mca-18`; инвариант пустого = `not_available`, не «отсутствие»; второй bundle запрещён. Санкция @Architect подтверждена (spec §8.1 п.1, ADR AMEND).
- **Проверка условий carry-over:** контракт полон ✓; `not_available`-инвариант зафиксирован в spec ✓; второго bundle нет (grep `class EvidenceBundle`/`class RetrievalRequest`/`def retrieve(` вне `mca_retrieval_context.py` — пусто) ✓.

### L-MCA07-5 — `retrieve()` без живого caller → **санкционированный carry-over**
- `retrieve()` реализована как единая точка (контракт + каналы + focused unit + real-DB smoke), живой caller отсутствует осознанно; spec AMEND §8.1 п.2 закрепляет обязательство потребителей `mca-09`/`mca-10b`/`mca-15` и запрет второго комбинированного retrieval (GEN-R19). Проверено: второго retrieval/bundle нет. ✓

### Прочие Lows — закрыты/зарегистрированы
- **L-MCA07-1 CLOSED:** `idx_mca_eig_fingerprint` используется `get_generation_by_fingerprint` (guard/идемпотентность карантина).
- **L-MCA07-2 регистрировано:** `search_service._rerank_results` — задокументированный адаптер (текст-компрессия), соответствует spec §4.2.
- **L-MCA07-3 CLOSED:** `retrieve()` эмитит `exact_match_used` при exact-канале (тест `test_retrieve_emits_exact_match_used`).
- **L-MCA07-4 CLOSED:** `answer_cache_disabled` эмитится со стадией `answer_cache` (была `summary`).
- **L-MCA07-6 регистрировано:** update-дедуп `(chat_id, tg_message_id)` — контракт `mca-03`; отдельный processing-gate в mca-07 не создаётся.
- **L-MCA07-7 WATCH:** в моём полном прогоне timeout teardown не воспроизвёлся (9758/0, ровный).

## Новые findings (не блокирующие; зарегистрированы как debt)

- **[N-MCA07-1] Low — нет пути активации/замены активного поколения (`mca-04b`).** `ensure_embedding_generation` никогда не помечает активное `superseded`/не переводит новое в `active`, если активное уже есть, — `activate=True` фактически no-op при существующем `active`. Это **безопасно для A06**, но означает: после смены модели/размерности или апгрейда legacy-БД vec-канал остаётся FTS-only до тех пор, пока `mca-04b` не добавит собственный path активации. **Рекомендация `mca-04b`:** добавить явную операцию «построено текущим конфигом → активировать» (single-writer, в том же реестре), иначе перестройка не включит vec. Не блокирует mca-07: spec §1/§4.3 прямо выносит перестройку в `mca-04b`, а FTS-only = санкционированная деградация.
- **[N-MCA07-2] Low — семантика бюджета изменилась (намеренно).** `_apply_context_budget` при ON вычитает `external + reserve` из `CHAT_CONTEXT_BUDGET_TOKENS` (default 16000; reserve 10%), поэтому доступный user-контекст уменьшается (~на external+1600 токенов). Это прямое следствие A24 (полный учёт payload), но для операторов это видимое изменение поведения — стоит зафиксировать в release-manifest/эффективном состоянии.
- **[N-MCA07-3] Low — pre-flight не «останавливает» отправку.** При переполнении обязательной части код сигналит (`context_overflow` + WARN) и сбрасывает cuttable-блоки, но обязательную часть не отправку не отменяет. Tool results в оценку `external` не входят (учитываются tools schemas; tool results — стадия System2). Соответствует spec §4.6/§5, но остаётся residual.
- **[N-MCA07-4] Low — `author == addressee == target_name` в живом bundle** (`direct_chat_service.py:2192`). Контракт различает адресата и автора; для сценария A04/SC-07 автор текущего сообщения не восстанавливается. Тонкость живого наполнения, не блокирует; кандидат на донаполнение в `mca-09`.

## Requirement / evidence coverage

| REQ / SC | Покрытие | Вердикт |
|---|---|---|
| REQ-MCA07-01 / SC-01, SC-02 (retrieval-комбинация, эпизоды-первыми) | unit + real-DB smoke; живой caller — carry-over (L-MCA07-5, санкция) | ✅ (carry-over) |
| REQ-MCA07-02 / SC-03, SC-04 (typed reranker, A05) | focused + `TestChatRagRerankF4` | ✅ |
| REQ-MCA07-03 / SC-05, SC-06 (identity; A06) | key+identity ✅; mismatch → FTS-only ✅; стартовое перетирание устранено ✅ | ✅ **B-1 closed** |
| REQ-MCA07-04 / SC-07, SC-08, SC-10 (bundle) | контракт полный ✅; живой builder тоньше — санкц. carry-over; `context_version` полный ✅ | ✅ |
| REQ-MCA07-05 / SC-09, SC-11 (один bundle; System2; A04) | scoped-срез/`tool_ctx` ✅; A04 на точках конвейера | ✅ |
| REQ-MCA07-06 / SC-12, SC-13 (полный бюджет; A24) | live call-site + pre-flight + деградация + лог ✅ | ✅ **B-2 closed** |
| REQ-MCA07-07 / SC-14, SC-15 (CAS/revision; answer-cache) | ✅ | ✅ |
| GEN-R19 (REUSE) / SC-16 | второго retrieval/bundle/reranker/бюджета нет | ✅ |
| MCA13-R1/R2 + GEN-R17/R14 / SC-17 | 10 reason_code, стадии, R17-safe | ✅ |
| MCA14-R1/R2/R5 / SC-18 | v18 аддитивно/идемпотентно; 6 kill-switch env-only default ON | ✅ |

## Focused audit coverage (изменённые/критичные файлы и рёбра)

- `services/mca_retrieval_context.py` — retrieval/reranker/bundle/`context_version` (контрактный слой, не второй движок).
- `services/database.py` — v18 (partial-UNIQUE `idx_mca_eig_active`), `ensure/get_active/get_latest/get_by_fingerprint` поколений, `upsert_running_summary` CAS (HWM `(window_end_ts, raw_count)`).
- `services/summary_memory.py` — identity cache key/lookup, generation-gate vec, `_vec_tables_preexisting`/`_rebuild_vec_tables_if_needed`, typed `rerank_rag_facts`, singleflight `_schedule_running_summary`.
- `services/direct_chat_service.py` — `_estimate_external_payload_tokens`, бюджет pre-flight/деградация, answer-cache политика, bundle wiring (`tool_ctx`/System2), `_summary_revision`.
- `services/token_counter.py` — protected spans/`estimation_method`; `services/search_service.py` — адаптер reranker; `services/mca_gates.py`/`config/settings.py`/`services/mca_events.py` — гейты/коды.
- **Кросс-модульные рёбра:** `serialized()` reentrancy (single-writer, вложенные вызовы не дедлочат, `database.py:977-1011`); `tool_ctx.evidence_bundle` (dynamic attr); `TaskSupervisor.run(coalesce_key=…)`; CAS `_serialized_write` без вложенности.

## Counterexamples / негативные проверки (воспроизведено)

1. **A06 через `activate=True`** — мой repro: активное old-fp + `ensure(new_fp, activate=True)` → active не подменён, guard = False (FTS-only). ✅
2. **A06 mismatch/карантин** — `building`/`superseded`/`failed` → guard False (`test_generation_registry_quarantine_building`, `test_index_generation_mismatch_forces_fts_only`). ✅
3. **A05 valid-empty** — `""`/`"[]"`/`"  "` → `[]`, не все кандидаты (`test_valid_empty_does_not_return_all_candidates`). ✅
4. **A24 живой pre-flight** — реальный `_build_user_content` при `external>>cap` → WARN `context overflow` (`test_live_preflight_overflow_on_mandatory`). ✅
5. **A03 CAS** — поздняя старая сводка отклонена (rowcount 0), tie-break `raw_count`; OFF = слепой upsert. ✅
6. **A04/кеш** — разные ветки → разный `context_version`; ON → text-replay отключён (2-й `handle` реально вызывает LLM), update-дедуп mca-03 не тронут; OFF = legacy-паритет. ✅
7. **OFF-паритет 6 гейтов** — default ON, имена в `KILL_SWITCHES`; OFF-пути (reranker/CAS/budget/external/protected/text-replay). ✅
8. **v18** — fresh 18, повторный `initialize()` no-op, legacy v17→18 сохраняет provenance, vec-таблицы не создаются/не ALTER-ятся. ✅

## Решение по риску (R3 → R2)

Триггеры понижения spec §Risk **выполнены на фактическом diff**:
1. **Изоляция retrieval/бюджета от hot-path записи** — `retrieve()` в живом direct-пути не вызывается (carry-over L-MCA07-5, санкц.); бюджет — чистая read-only-функция сборки контекста; bundle in-memory (не persistence).
2. **A03/A04/A05/A06/A24 доказаны на diff** — каждая приёмка подтверждена focused/интеграционными тестами на обновлённых путях (пп. 1-6 выше). A04 — на уровне точек конвейера (полный `handle`-e2e не гонялся; см. Unavailable).
3. **Отсутствие перезаписи/удаления legacy-строк** — v18 аддитивна (`CREATE/ALTER` под guard, vec-таблицы не трогаются); CAS **усиливает** (а не ослабляет) защиту `chat_running_summary`; legacy-векторы не удаляются, а карантинятся.
4. Дополнительно: «что может поднять риск» (несовместимая перестройка vec в hot-path; недостижимость полноты бюджета без блокирующего tokenizer) — **не наступило** (перестройка — `mca-04b`; оценка консервативная без блокирующего вызова).

**Решение: Risk-Level = R2.** Основание — выполненные санкционированные spec-триггеры; глубина ревью сохранена на R3-уровне (threat-failure-analysis, негативные сценарии, кросс-модульные рёбра). Если @Architect/PM потребует полный `handle`-e2e для A04 как условие релиза — R3 остаётся правомерным (оговорка зафиксирована в Unavailable).

## Blocking findings

**Нет.** B-MCA07-1 и B-MCA07-2 — закрыты; M-MCA07-1 — закрыта; M-MCA07-2/L-MCA07-5 — санкционированный carry-over (@Architect, spec AMEND §8.1 / ADR AMEND). Открытых Critical/High/requirement-blocking Medium нет.

## Non-blocking debt (регистрируется)

- **N-MCA07-1** (Low) — API активации нового поколения отсутствует; обязательство `mca-04b`.
- **N-MCA07-2** (Low) — поведенческое изменение доступного user-бюджета (external+reserve вычитаются) — отразить в manifest/effective-state `mca-release`.
- **N-MCA07-3** (Low) — pre-flight = сигнал+деградация без жёсткой отмены; tool results не учитываются в `external`.
- **N-MCA07-4** (Low) — `author == addressee` в живом bundle.
- **L-MCA07-2/6** — регистрировано (адаптер reranker; update-дедуп = контракт mca-03); **L-MCA07-7** — watch.

## Unavailable checks

- **A04 на полном `handle`-e2e** не гонялся (тяжёлый скелет handler'а); покрыт на точках конвейера + зелёный регрессионный набор `direct`.
- `EXPLAIN QUERY PLAN` для 3 индексов v18 на прод-объёме не выполнялся (форма запросов обоснована; index `idx_mca_eig_active` и `idx_mca_eig_fingerprint` используются).
- PG no-op подтверждён по коду (SQLite-механизм, `pg_db.py` вне diff); на реальном PG-инстансе не проверялся.
- Live-смена embedding-модели на реальном endpoint не выполнялась (эмулирована на уровне реестра; A06 воспроизведена).
- Browser-проверка — N/A (нет browser-facing критериев; `Browser-Verification` не REQUIRED).

## Handoff

- **@Architect / @Orchestrator:** вердикт **Approved**, Risk **R2**. Разрешить **Merge в `plans/ARCHITECTURE.md` §99+** и перевод **ADR-1027-7 → Accepted** (после Merge). Санкционированные carry-over M-MCA07-2 (владельцы `mca-09`/`mca-05`/`mca-18`) и L-MCA07-5 (потребители `mca-09`/`mca-10b`/`mca-15`) занести в `tasks.md` фич-потребителей (обязательство: маршрутизация через `retrieve()`, запрет второго retrieval/bundle).
- **@Builder (follow-up, non-blocking):** N-MCA07-1 — API активации поколения для `mca-04b`; N-MCA07-2 — запись в release-manifest/effective-state.
- **@Orchestrator:** маршрут `review → delivery`. Binding: Reviewed-Commit `05bc870…`, Working-Tree-Hash `75D55F53…`, Spec-Hash `943DFE67…`. Checkpoint — за @Orchestrator (Reviewer его не пишет). Записи в `plans/reports/full_audit_results.md` Reviewer **не** вносил: scope шага ограничен `review.md`; при необходимости Orchestrator перенесёт findings туда.
- **MEMORY_DELTA:** подтверждён durable-факт: (1) B-MCA07-1 закрыт — `ensure_embedding_generation` не подменяет активное поколение, `_index_generation_ok` гейтит по `(status='active', fingerprint==current)` → mismatch = FTS-only; остаток — нет API активации после перестройки (owner `mca-04b`). (2) B-MCA07-2 закрыт — production `_build_user_content` передаёт external/reserve/method, pre-flight `context_overflow` срабатывает; остаток — сигнал+деградация без жёсткой отмены. (3) M-MCA07-2/L-MCA07-5 — принятый carry-over (spec §8.1, ADR AMEND); spec-hash `943DFE67…`, ADR-hash `EB7EF5D9…`.

_Конец. Независимый единый Reviewer gate (обе линзы + focused change audit). Код/тесты не изменялись; обновлён только `review.md`._
