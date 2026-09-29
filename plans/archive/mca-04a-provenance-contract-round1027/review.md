# `mca-04a-provenance-contract` — независимое ревью (единый Reviewer gate, T-3835 → rework re-review T-3836)

- **Feature-ID:** `mca-04a-provenance-contract` (round 10.27 MCA, Wave 1, ADR-1027-6 D1–D13).
- **Risk-Level:** **R3** (ратифицировано; `threat-failure-analysis.md` — 12 угроз / 7 режимов отказа, обновлён под rework).
- **Status:** **Approved** — блокирующий High **B-MCA04A-1 закрыт**; обе обязательные линзы (requirements/correctness + focused change-audit) подтверждены независимо.
- **Итерация:** 2 (rework после итер.1 `Needs Fixes`). Итер.1: B-MCA04A-1 High + debt D-MCA04A-1…-7.
- **Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa` (origin/master; feature-коммитов нет — правки в рабочем дереве).
- **Working-Tree-Hash:** `0501ea9b006ddeb9a47ad5c22c3dcc09b3dca670a93d2ba08d8b1f4d4aa57e0a`
  - `Tracked-Diff-SHA256 = efe626a3cf0f48b9e12fb0609d0f46039c473334caa76835a128e3d32edbeaf7` (SHA-256 от `git -c core.autocrlf=false diff HEAD`);
  - `Untracked-Manifest-SHA256 = 3aa25317338dcde1f0535cf2c06b7a46a89c4968eab5a662cace8e3016497c62` (58 untracked-файлов; исключены `node_modules/` и сам артефакт `review.md`);
  - `Working-Tree-Hash = SHA256("tracked=<h>\nuntracked=<h>\n")`.
  - **Рецепт:** untracked-манифест — `git ls-files --others --exclude-standard` (без `node_modules/`, без `review.md`/`audit.md`) → строки `"<path>\t<sha256(content)>"` (сортировка по path, LF-joined); tracked-diff включает и audit-запись этой итерации. Запись `review.md` на хэш не влияет (исключена).
- **Spec-Hash:** `3d8b29928918dbddaa2b4f2c0bd7850326a6be85286a8bd19f6d4dba0bac877e` (не менялся между итерациями).
- **ADR-1027-6-Hash:** `3f19813595fe32cb7ed1312f93fd90f0dd2879d690217979bade18cc2dba54b6` (статус ADR — **Proposed**; `Accepted` только фактом Merge §98+).
- **Tasks-Hash:** `63f1c1433351d909bc4e3a42427cc15b13c25a4f6d15c129f48395091cbfd38f` (обновлён — раздел rework/carry-over).
- **Evidence-Hash:** `56d6d53ce1319f4272a376434a7ce4dc4d39ce58e6eb15a8c3b43f99123988f9` (обновлён — честное покрытие A86/A95).
- **Threat-Hash:** `04bcf696dac38cc89b0d3fe3aeb6f27d8bbfd3593f8ab2c9bfb07bd4a800203a` (обновлён — T4/T9/F5 под rework).
- **Deploy:** `DEFERRED_TO_RELEASE`; изменения не закоммичены. Секреты источника не цитировались (R17/R18); `plans/current_task.md` не изменялся.
- **Прошлый binding `ef008a83…` — stale** (итер.1, до rework); не переиспользуется.

## 0. Git-база и объём просмотренного изменения

- База — `HEAD=05bc870`; feature-коммитов нет; рабочее дерево содержит изменения нескольких MCA-фич (волна 0/1 + `mca-04a`). Проверены **именно** файлы `mca-04a` и их интеграционные края:
  - **NEW** `services/provenance.py`, `tests/test_mca04a_provenance_round1027.py`;
  - **AMEND** `services/database.py` (v17 + backfill, `insert_graph_fact` +6 колонок, subject-scope читатели, `person_fact_exists`);
  - **AMEND (FIX)** `services/direct_chat_service.py` (`_apply_fact_attribution`), `services/summary_memory.py` (`_attach_fact_provenance`), `services/lore_worker.py` (`_write_person_facts`, row-bound), `services/dossier_prompts.py` (`filter_layer_a_candidates` + `row_count`/`message_lookup`), `services/dream_worker.py` (`record_source_ids_provenance`);
  - `services/mca_gates.py` (+3 рубильника), `config/settings.py` (+3 `ClassVar`), `services/mca_events.py` (+5 `reason_code`);
  - обновления тест-файлов (v16→v17), `test_mca01` allowlist, `test_multilayer_extraction_round1021` (приведён к новому FIX п.3/п.5).
- `services/pg_db.py`, `tools/gen_param_registry_*/param_catalog.py` — **вне diff**.

## 1. Выполненные независимые проверки (итер.2)

| Проверка | Результат |
|---|---|
| Полный pytest `.venv -m pytest -q` | **9712 passed / 0 failed** (212.3 s; warning — только StarletteDeprecation) |
| Focused `tests/test_mca04a_provenance_round1027.py` | **34 passed** |
| JS vm-харнесс `node tests/js/*.js` | **47/47** (exit 0) |
| `git diff --check` | exit **0** (только LF→CRLF warnings git) |
| OFF-паритет kill-switch (`test_kill_switch_off_parity`) | зелёный |
| Код-инспекция B-MCA04A-1 / D-1 / D-4 / D-5 / D-6 | подтверждена по коду (см. §2/§3) |

## 2. Покрытие требований / evidence (фокус rework)

| Проверка | Вердикт | Основание |
|---|---|---|
| **B-MCA04A-1:** ≥2 различных `user_id` по имени → `unresolved`, стабильное канон-имя, без выдуманного TG ID | ✅ **closed** | `provenance.py:533–588` (`_lookup_user_ids_by_names` собирает **все** id, `resolve_subject_ref` при ≥2 и при 0 → `unresolved` с `entity_id=canon_name`) |
| **B-MCA04A-1:** self-report — субъект = `user_id` говорящего (не резолв по имени) | ✅ **closed** | `direct_chat_service.py:2297–2336` (`asker_user_id` → `user_source_ref`, ветка `self_report` берёт `speaker_ref`); проброс `user_id` из апдейта — `:1559` |
| **B-MCA04A-1:** усиленный `test_same_name_not_merged` реально ловит регресс | ✅ | `tests/...:377–408` — ассерты `resolution=='unresolved'`, `entity_id=='Макс'`, `not isdigit`, стабильность `dedup_key`, изоляция `get_user_context_facts(..., user_id=1/2)`. При возврате прежнего (сливающего) поведения `resolution` стал бы `resolved` с digit-id → тест падает |
| **B-MCA04A-1:** новый `test_self_report_uses_speaker_user_id` осмыслен | ✅ | `tests/...:411–441` — факт `bot_direct_reply` + 2 одноимённых; `subject_ref_id == sref2` (говорящий #2), `speaker_author_id==2`, читательский скоуп изолирован |
| **D-1:** row-bound `filter_layer_a_candidates` подключён (multilayer + `_extract_chunk`) | ✅ **closed** | `lore_worker.py:677–679` (`row_count=len(window)`), `:913–914` (`row_count=len(lines)`); контракт — `dossier_prompts.py:335–381` → `provenance.validate_layer_a_row_bounds` |
| **D-1:** тест осмыслен | ✅ | `test_fix_p5_extract_chunk_row_bound_wired` (evidence [5] вне окна из 2 строк отброшен, [2] сохранён), `test_fix_p5_filter_row_bounds` (out_of_range/missing/ok) |
| **D-4:** повторная запись `origin_status` сохраняет conflict/freshness/coverage | ✅ **closed** | `provenance.py:350–377` — read-modify-write в `write_transaction` (lock на всю транзакцию, атомарно); `_keep` (`None` = сохранить ранее записанное) |
| **D-5:** `local_evidence_to_source_refs` принимает `sqlite3.Row` | ✅ **closed** | `provenance.py:800–815` (`_row_field`: dict → `.get`, иначе `row[key]`); `test_fix_p5_local_evidence_accepts_sqlite_row` |
| **D-6:** детерминизм матча субъекта | ✅ **closed** | `provenance.py:604–606` — `sorted(..., key=(-len, casefold))`; by construction (dedicated-теста нет — non-blocking, см. §5) |
| **D-2/-3/-7:** зарегистрированы как входы `mca-04b` | ✅ | `tasks.md` «Carry-over — обязательные входы mca-04b» (D-MCA04A-2/-3/-1-врезка/-7); `threat-failure-analysis.md` §4 |
| **evidence.md не завышает покрытие** | ✅ | A86 — helper-level (полный Layer-B-e2e — 04b); A95 — synthetic `claim_key` (выборка досье — 04b) |
| Регрессии в `direct_chat_service`/`lore_worker`/`dossier_prompts` | ✅ | полный pytest 9712/0; `row_count` дефолт `None` сохраняет прежнее поведение прочих вызовов (единственные вызовы — в `lore_worker`, оба обновлены) |
| OFF-паритет kill-switch | ✅ | `mca_gates.fact_attribution_enabled`/`evidence_reconstruction_enabled` инертны при `MCA_PROVENANCE_ENABLED=OFF`; `_write_person_facts`/`_apply_fact_attribution`/`_attach_fact_provenance` — no-op при OFF |

## 3. Фокусная проверка изменений (focused change-audit lens)

- **B-MCA04A-1 — корневая причина устранена на уровне контракта, а не теста.** Резолвер теперь различает «ровно один» и «≥2/0»; выбор произвольного ID невозможен. Читатели (`get_user_context_facts`/`get_persona_card`) изолируют по `subject_ref_id` устойчивого ID (проверено тестом и кодом `database.py:6145–6216`).
- **D-4 — целостность полей статуса.** SELECT+`INSERT OR REPLACE` под single-writer (`write_transaction` держит lock на всю транзакцию) → гонки read-modify-write нет. `coverage_covered=0` сохраняется корректно (`is not None`, не truthiness).
- **D-5 — типы строк.** `_row_field` покрывает dict и `sqlite3.Row`; пустой `entity_id` → `valid=False` (без `ValueError`/выдуманного адреса).
- **D-1 — границы окон.** Мультистрочное окно и чанк используют разные границы (`len(window)` vs `len(lines)`) — одинаковый локальный номер в разных чанках не склеивается (A88).
- **Интеграционные края.** `_attach_fact_provenance` пропускает `bot_direct_reply` (обрабатывается FIX п.1 — нет двойной записи); `_write_person_facts` пишет `unconfirmed` + subject/attribution/channel, идемпотентно (`person_fact_exists`), fail-open на факт; `dream_worker` belief/paradigm — fail-open `derived_from`.
- **Безопасность/R17.** Параметризованные запросы; единственный f-string — фиксированные имена колонок; `basis`≤160 без CoT; `checks_json` — коды/enum; события — только id/коды/`error_type`.
- **Совместимость/аддитивность.** v17 — только `CREATE IF NOT EXISTS`/`ALTER ADD COLUMN`; `origin` CHECK не расширялся; PG no-op; `Δ каталога = 0`; старые ID/FTS сохранены (проверено тестами v17).

## 4. Контрпримеры / негативные сценарии

- Два одноимённых `user_id` → `unresolved` (итер.1 сливал) — покрыто.
- Self-report одноимённого → субъект строго говорящего, второй не получает факт — покрыто.
- Evidence вне окна чанка → отброшен; валидный — сохранён — покрыто.
- Повторная запись `origin_status` → conflict/freshness/coverage не сброшены — покрыто.
- `sqlite3.Row` без `.get` → не падает, адрес создаётся — покрыто.
- OFF kill-switch → SourceRef/links/статусы не создаются, читатели legacy — покрыто.
- A09: похожий текст не даёт ложный `original`; recon не переименовывает `original` — покрыто.

## 5. Non-blocking debt / carry-over (регистрируется, не блокирует)

- **D-MCA04A-2 (Medium):** прод-вызов `reconstruct_fact_provenance` (read-time/фон) — обязательный вход `mca-04b`. `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` в 04a инертен.
- **D-MCA04A-3 (Medium):** A95 — реальная выборка досье (Леха/Вася/Ярик, периоды, precision/recall) вместо synthetic `claim_key` — вход `mca-04b`. `evidence.md` покрытие не завышает (честно).
- **D-MCA04A-1-врезка (Medium):** фактическая врезка local→SourceRef в chunk-пайплайн (`message_lookup` existence) — `mca-04b`; в 04a — валидатор + конвертер + row-bound.
- **D-MCA04A-7 (Low, perf):** оценка стоимости provenance-записи на объёме батча (до нескольких `write_transaction` на факт, bounded-скан ≤500 строк) — вход `mca-04b`/`mca-release`.
- **N-MCA04A-1 (Low, residual, новое):** `_lookup_user_ids_by_names` — bounded-скан последних ≤500 `smart_messages`. В чате >500 сообщений при «старом» одноимённом участнике homonym может не попасть в окно → резолв может ошибочно дать `resolved`. Остаточный риск того же класса, что B-MCA04A-1, но ограниченный конфигурацией; читатели с явным `user_id` изолированы и не затронуты. Рекомендация: для name-резолва ограничивать набор ростером участников/окном досье либо расширять источник в `mca-04b`.
- **N-MCA04A-2 (Low, boundary):** `_classify_chunked_user` (F8) пока не вызывает `_write_person_facts` — A86 в chunked-пути не реализован независимо от портрета. Согласовано с санкционированной границей «врезка в chunk-пайплайн — 04b»; зафиксировать входом 04b.
- **N-MCA04A-3 (Low, evidence):** детерминизм `guess_subject` (D-6) обеспечен построением (`sorted`), но отдельного теста нет. Не блокирует; желателен пин в `mca-04b`.
- **L-MCA03-8** (не в 04a) — обязательный вход `mca-04b` (версионирование namespace-отпечатка).

## 6. Недоступные проверки

- Реальная прод/рабочая БД (заполненность ID, пересечения импорт↔live) — GEN-R20, вход `mca-release`/@Memory.
- PG e2e — no-op по дизайну (кода нет).
- DreamWorker e2e со «сном» и typed-линками — LLM-мок; helper покрыт unit-тестом.
- Browser-verification — N/A (backend/data; `Browser-Verification` не REQUIRED).

## 7. Вердикт

**Status: Approved.** Блокирующий **B-MCA04A-1 (High) закрыт** и подтверждён независимо (код + усиленный/новый тесты + изоляция subject-scope читателей). Debt **D-MCA04A-1/-4/-5/-6 закрыт**; **D-MCA04A-2/-3/-7 + врезка п.5** и новые Low-residual (N-MCA04A-1/-2/-3) зарегистрированы как входы `mca-04b`/`mca-release` и не блокируют. Обе обязательные линзы (requirements/correctness + focused change-audit) поддержаны; регрессий нет (pytest 9712/0, JS 47/47, `git diff --check`=0).

**Рекомендация:** @Orchestrator → фаза `delivery`; @Architect — **Merge §98+** с переводом **ADR-1027-6 (D1–D13) → Accepted** (фактом Merge; сейчас статус `Proposed`). Секретов/`current_task.md`-изменений нет; deploy — `DEFERRED_TO_RELEASE` (единый `mca-release`).

Binding действителен только для указанного состояния рабочего дерева; любое изменение кода/спеки/untracked-артефактов (кроме записанного `review.md`) делает его устаревшим.
