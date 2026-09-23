# Review — S4 `summary-fact-package-round1026` (Эпик 2, «Пакет фактов §96»)

- **Feature-ID:** `summary-fact-package-round1026`
- **Status: Approved** (автономный контур: оба обязательных ленза — требования/корректность и focused change-audit — пройдены; **live-приёмка — PENDING OWNER VERIFICATION**)
- **Роль:** Step 5 @Reviewer (T-3300), 23.09.2026.
- **Git base и inspected change scope:** annotated-тег **`pre-round1026-s4` → `59f592147f2ae5b316a56361e03e4b7a1d9a7c7c`** (`git rev-list -n1 pre-round1026-s4`). Правки **НЕ закоммичены** — аудит дерева относительно `59f5921` (`git diff` + untracked). Новые: `services/summary_fact_package.py` (694 стр.), `tests/test_summary_fact_package.py` (52 теста), `plans/features/summary-fact-package-round1026/**`. Изменённые: `config/settings.py` (bump 2.58.23), `README.md`, `plans/docs/param-registry-round1025.meta.md`, plans-доки (Step 0–3 @Memory) + 13 Py/4 JS тестов (только version-пины).

## Checks performed (воспроизведено лично)

| Проверка | Команда | Результат |
|---|---|---|
| Новый файл тестов | `.venv\Scripts\python.exe -m pytest tests/test_summary_fact_package.py -q` | **52 passed / 0 failed** (2.49 s) |
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **8737 passed / 0 failed / 1 warning** (109.79 s) = baseline 8685 + 52 |
| JS-тесты (все, node) | `node tests/js/<file>.js` × 43 | **43/43 OK, 0 fail** |
| `git diff --check` | `git diff --check` | exit **0** (только CRLF-предупреждения Git) |
| Каталог (импорт) | `param_catalog` + `Settings` | REGISTRY **468** / Settings **426** / categorized **443** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21** → **Δ=0** |
| F8 `--check` | `.venv\Scripts\python.exe tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 468 == REGISTRY…` exit **0** |
| Δ DDL | `git diff --name-only` по DB/миграциям | пусто (`database.py`/`pg_db.py`/SQL вне diff) — **Δ DDL=0** |
| Живой путь вне diff | `git diff --name-only` ↔ forbidden | `summary_generator.py`/`summary_xml.py`/`telegram_send.py`/`image_generation.py`/`web/**`/`param_catalog.py` — **NONE** |
| 0 LLM (AST) | разбор импортов модуля | `['__future__','config','dataclasses','json','logging','re','services','time']`; `llm_client` отсутствует; `async def` отсутствует |
| R18 | `git rev-parse`/файловая система | `pre-round1026-s4` — annotated (`cat-file -t`=tag) → `59f5921`; `var/backups/s4-round1026-20260923-202326/`; `.env.bak.round1026-s4`; `stash@{0}` на месте |

## Requirement/evidence coverage (§96 / SC-01…SC-10 / REQ-S4-01…-13)

- **SC-01 §96-полнота:** `TOP_LEVEL_FIELDS`/`THREAD_FIELDS` — ровно ожидаемые ключи; `name`=topic verbatim; `chronology` из §92; `facts`/`evidence_ids` verbatim+union; `fragments` evidence-first. ✅
- **SC-02/REQ-S4-09 (0 LLM):** модуль не импортирует `llm_client`, синхронный; `test_two_calls_stage1_stage2` нетривиален (`llm.generate` — `AsyncMock(side_effect=[...2])`, падение при 3-м вызове; `await_count==2`, `steps==["stage1","stage2"]`). Живой путь вне diff. ✅
- **SC-03/REQ-S4-05 (fail-closed, §95/§106):** `ok→ok`; `truncated→truncated`; `empty/invalid/error → threads=[]`, `deliverable=False`; нет `usable`/`payload`/неизвестный статус → `not_built`, `package=None`. Пустое в L2 не передаётся. ✅
- **SC-04/REQ-S4-06 (ID TG/DB):** DB `id` (1/2) → `invalid`/`missing_source`; висячие/фабрикованные id, evidence вне темы, дубль между темами, конфликт с unassigned → `invalid`; `evidence_ids ⊆ message_ids` (defense-in-depth). ✅
- **SC-05/REQ-S4-02/-03 (компактность):** `fragments` ⊆ `message_ids`/`evidence_ids` темы; `test_does_not_duplicate_raw_log` — тексты прочих сообщений отсутствуют; лимиты `FRAGMENT_MAX_CHARS=1000`, `MAX_FRAGMENTS_PER_THREAD=30`, `MAX_FRAGMENTS_TOTAL=500`. ✅
- **SC-06/REQ-S4-07 (явное усечение):** приоритет fragments(старые первыми)→description→целые темы; `truncated`+`skipped_ids`/`skipped_threads`+WARN `FACT_PACKAGE_TRUNCATED`; последние фрагменты сохраняются; 0 тем → `empty`/`budget_empty`. ✅
- **SC-07 (детерминизм):** двойной прогон байт-идентичен (`serialize_package`), вход не мутируется (deepcopy-сверка); фикс-порядок ключей, ASC `(timestamp,message_id)`. ✅
- **SC-08/REQ-S4-04 (описание/хронология):** `description` — дедуп (casefold+схлопывание пробелов) `facts[].text`, `" · "`, кап 500 по границе слова, флаг `description_truncated` в `metrics`; нет фактов → `""`; никакой LLM/прозы. ✅
- **SC-09/D3 (транзит `service`):** `cover_prompt`/`response_mode` (L1→payload-fallback) в секции `service`, вне контента тем; §104/обложка не тронуты. ✅
- **SC-10 (инварианты):** Δ DDL=0, Δ каталога=0, F8 N/A (не переиздавался, `--check` OK), CSP/zero-build, R17/R18, §57–§74/F0–F11/S1–S3 — не сломаны; маркер-тесты только version-пины. ✅
- **REQ-S4-11/-13 (врезка GATED / §113→S9):** врезки нет — `summary_fact_package` нигде не импортируется (grep по `services/**` — только определение); T-3299 остаётся `[ ]`. ✅

## Focused audit coverage (critical files/deps)

- **`services/summary_fact_package.py`:** критичных дефектов безопасности/целостности не выявлено. Атака-поверхность минимальна (чистый, без БД/сети/eval/SQL; `json.dumps`). R17: логи `FACT_PACKAGE_START/COMPLETE/ERROR/TRUNCATED` — только числа/коды/id/host; секрет-тест `test_logs_r17_safe` зелёный. Исключения обёрнуты → fail-closed `error`/`internal_error`.
- **Критичные зависимости:** `summary_l1_contract.build_id_space`/`L1Result` (S3) — корректно переиспользованы; `token_counter.resolve_chat_limit`/`count_tokens` — штатная семантика; `resolve_l1_budget`-паритет подтверждён. Новых внешних зависимостей нет.
- **Интеграционные края:** модуль не врезан; S5 получит `build_fact_package(l1_result, payload_items, *, budget=None, correlation_id=None)` (канонический вызов S5 не затронут — `correlation_id` аддитивен).
- **DDL/миграции/откат:** изменений нет; откат `pre-round1026-s4` (annotated) / `git revert`; hot-OFF не требуется (живой путь не тронут).

## Blocking findings

**Нет.** Critical 0 / High 0 / requirement-blocking Medium 0.

## Non-blocking debt (owned follow-up → S5)

| ID | Sev | Место | Суть | Доказательство |
|---|---|---|---|---|
| L-R1026S4-1 | Low | `summary_fact_package.py:251-253` | Обрезка фрагмента >`FRAGMENT_MAX_CHARS` не отражается в `truncated`/WARN, только `metrics.fragment_char_truncated_count` (наблюдаемо, не «молча»). Спек §4.5 санкционирует сам лимит; §6 «вытеснение» ≠ char-обрезка. | Моя проба: text 1500 → `status=ok`, `truncated_count=0`, `char_trunc=1`, fragment len=1000 |
| L-R1026S4-2 | Low | `summary_fact_package.py:382-412` | `_enforce_budget` — O(n²) пересчёт JSON+токенов на каждое вытеснение. | Проба @Scanner: 341 вытеснение, 0.29 s CPU (не блокирует) |
| L-R1026S4-3 (Reviewer) | Low | `summary_fact_package.py` (L1-passthrough) | §9/ADR D5 «проброс `skipped_ids`/`skipped_tg_ids`» выполнен как **счётчики** (`l1_skipped_count`, `l1_chunk_count`); сами id-списки и `skipped_tg_ids` не переносятся в `FactPackageResult`. §10 трактует `skipped_ids` «счётно», данные остаются на `L1Result` (S5 получает его напрямую) → функциональной потери нет; уточнить формулировку §9/*ADR* либо донести ids в S5. | grep: `skipped_tg_ids` в модуле отсутствует |
| I-R1026S4-1 | Info | `summary_fact_package.py:382-412` | `unassigned_message_ids` не усекаются бюджетом (они — транзит §5); `cut` не используется → при перевесе только unassigned `status=empty`/`fits=False`. | Чтение кода |
| I-R1026S4-2 | Info | `summary_fact_package.py:639-645`/`_fail_result` | `invalid`/`error` без `invalid_reason` → `result.reason=None`, а `metrics.reason`/лог = `ok` (вводит в заблуждение диагностику). | Моя проба: `invalid_result(None)` → `status=invalid`, `reason=None`, `metrics.reason='ok'` |

**Scanner L-R1026S4-1/-2 подтверждены лично** (оба Low, не блокируют). Process gate **M-R1026S4-1** (отсутствие `review.md`) — **снят этим документом**.

## Unavailable checks

- **Live-приёмка на проде** — PENDING OWNER VERIFICATION (deploy — T-3305 @DevOps).
- **Врезка `L1Result → пакет → L2`** — GATED (S5/S6, ADR-1025-24 D4): намеренно вне diff, подтверждено grep/тестами.

## Handoff

**RESULT: APPROVED @Orchestrator** — T-3300 @Reviewer закрыт; оба ленза зелёные, C0/H0/блокирующих Medium 0; Δ DDL=0, Δ каталога=0 (468/426/443/100/98/21), F8 `--check` OK, 0 LLM-вызовов, живой путь/публикация/обложка/`web/**` вне diff, R17/R18, `APP_VERSION` 2.58.23. Открытые Low/Info (L-R1026S4-1/-2/-3, I-R1026S4-1/-2) — owned follow-up S5 (не блокеры). Live — PENDING OWNER VERIFICATION. Далее — T-3302 (при необходимости) → T-3303 @Architect → T-3304 @PM → T-3305 @DevOps.
