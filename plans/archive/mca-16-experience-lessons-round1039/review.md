# MCA-16 `mca-16-experience-lessons` — Review (T-5013, независимый Reviewer)

## Verdict: **Approved**

Reviewed state: HEAD `92252d1` + uncommitted working tree (2 Builder-сессии, ничего не staged/committed).
Binding: манифест `plans/reports/mca16_wth_manifest_review.txt` —
`MANIFEST_SHA256 = 59ad278b70c1f817395b212c7309c2711f74ca2c8631dde30835c41d8296f1fc`, FILES=90.
Exclusions (записаны в шапке манифеста): `plans/workflow_state.md` (process journal),
`plans/docs/mca-round1027-arch-frames.md` (foreign WIP), untracked debris
(`.playwright-mcp/`, `node_modules/`, `package*.json`, `tools/_ui_asap43_*`, `plans/verification_cache.json`), сам манифест, `plans/features/mca-16-experience-lessons/review.md` (review excluded from own binding, self-referential).

## Findings

| # | Severity | Location | Evidence | Blocking |
|---|---|---|---|---|
| 1 | Info | tests/ (~30 файлов) | CRLF-ренормализация почти пустых по содержанию диффов; `git diff --ignore-cr-at-eol` даёт 89 реальных строк (счётчики/пины). Шум в WTH-манифесте, поведение не затронуто, все раны зелёные. | no |
| 2 | Info | `services/mca_experience.py:374-399` | Комментарий relevance: «префикс ≥4 символов», код использует `len>=5` / `stem=token[:5]`. Код консистентен и протестирован, неточен только docstring. | no |
| 3 | Info (позитив) | `services/mca_events.py:60-70` | REASON_CODES — дифф подтверждает ровно **+10** (`experience_recorded, lesson_proposed, validation_passed, activated, retrieved, applied, feedback_linked, utility_updated, suspended, superseded`); второго словаря нет; per-turn `retrieved/applied` ≤1 | no |

Блокирующих findings нет.

## Ответы по обязательным пунктам (независимые проверки, не пересказ evidence.md)

1. **R2/R5 банк и отбор (`services/mca_experience.py`).** Урок создаётся только из канона: `propose` отвергает любой `rule_key` вне `CANONICAL_RECOMMENDATIONS` и любой свободный текст ≠ канона (:943-949) ⇒ injection-текст не может стать уроком. `validate` fail-closed: `explicit_preference` → только `social_preference`/`user_in_chat` + `permission_granted` + `conflict_free` + `identity_resolved` (:1021-1031); `technical_fix` → `error_reproduced` + `control_example_succeeded` (:1032-1038); generalization ≥ `min_independent_episodes` (:1039-1047); historical требует `fresh_context_verified` (:1050) — массовый backfill успеха невозможен. Global — двойной gate `anonymity_violations` (propose :950, validate :1013). `_forbidden_effects` — уроки не меняют system prompt/секреты/права/инструменты/бюджет. Отбор `select_for_context` (:1336-1405): gates → scope/active → compat → relevance (min 0.34) → utility; bounded ≤items/≤tokens с честным `excluded`; suspended/stale исключены. Utility Beta(1,1) `(s+1)/(s+f+2)`, ESS s+f+2, нейтраль 0.5 (:360-371). Идемпотентность после рестарта — тест `test_episode_idempotency_and_restart` (passed).
2. **R5 single bundle.** Lessons — отдельный тип в едином EvidenceBundle (`LessonRef` + `bundle.lessons`; `direct_chat_service.py:4204-4245` — один отбор, второго bundle нет). Рендер — bounded-блок данных (не инструкций) в хвост системного промпта, не вытесняет вопрос/источники (:2018-2043); применения пишутся outcome=unknown, fail-open. Тесты `test_bundle_lessons_additive_separate_type`, `test_build_evidence_bundle_carries_lessons`, `test_k4_off_no_lessons_but_capture_continues` (passed).
3. **R3 feedback/anti-self-confirmation.** Блок B, 13 passed: техн/outcome ≠ истина, owner vs participant, silence=unknown (:113), late feedback по trace + dedup (:134), cancel/correct с сохранением истории (:173), injection-текст не становится уроком (:211), feedback сам не активирует урок (:249), priority-блок = данные не инструкции (:271), social majority ≠ ground truth (:295), LLM-гипотеза ≠ self-confirmation (:318), ненадёжные числа/косты/квоты ≠ reward (:339).
4. **R4 цикл/активация.** См. п.1 (типы валидации, канон, anonymity, historical). Активация validated → active без Human Gate — по санкции ADR; delta/lineage/supersede в schema (`supersedes_lesson_id`, `merged_from_json`); suspend по verified-contradiction (`_has_verified_contradiction`); compat-stale → excluded/recheck (`compat_is_current`).
5. **R6 очередь/sleep/randomness.** `mca_experience_jobs.py`: job kind `experience.review` в существующей очереди (TaskJobStore, coalesce `experience.review:global`, singleflight); per-message LLM-рефлексии нет — propose детерминированный, без LLM. Deep sleep не смешивает lessons с парадигмами (отдельный kind-job; `dream_worker`/`graph_facts` не тронуты). `mca_random_draws` — read-only наблюдение (`recent_draw_observations` :251-260); второго RandomSource/процента нет.
6. **R7 UI/observability.** `GET /api/memory/lessons` + `POST /api/memory/lessons/action` (admin, отмена/исправление/suspend-activate, trace — только своя область, no-op-ы не выполняются); «Статус» — опыт из реальных counters (`experience_snapshot` в `status_service.py`), disabled/not_run при OFF честно; suspended виден и НЕ применяется; «Память» — таблица/карточка уроков. `self_learning.run` v1, 10 этапов. JS-тесты — см. ниже.
7. **Catalog/F8.** Я пересчитал сам: REGISTRY **504**, GROUPS **108**, `_TAB_BY_GROUP` **106**, Settings **441**, categorized 479, delta **93**; `ROUTES_SHA256_F11 = efcbc457dae345d03bf304fdc86c8f5074937185ff1bc3b7cd635b568dea90f2` — без изменений. `python tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 504`. ТСV/meta/fixtures обновлены reissue-скриптом; screen-map/widget-map +2.
8. **Δ DDL v28.** 4 таблицы + 9 idx; `test_v28_fresh_schema_book_and_idempotent_reinit` и `test_v28_upgrade_from_v27_simulated` — passed; schema_migrations book (28, experience_bank) ×1; backup-guard путь через mca-14 runner (самRunner не изменён except v28-header); PG — no-op by construction (`pg_db.py` не изменён).
9. **OFF parity (K1/K2 — сам).** Внешние env `MCA_EXPERIENCE_LESSONS_ENABLED=false` / `MCA_EXPERIENCE_FEEDBACK_ENABLED=false`: `test_k1_off_inert` + `test_k2_off_feedback_closed` → **2 passed**. Побочный полевой признак: при env=false тест `test_sanctioned_registries` падает по строгому «default True» — ок (env-override работает, default ОН). K3/K4 (по evidence-тестам A/D/E: статус замораживается, активные уроки при K3 OFF продолжают работать) не реранились независимо — учтено как reused (same файл, тот же ран 91 passed).
10. **Scope.** `plans/current_task.md` не изменён (git status). Вторых механизмов (bank/queue/bundle/dictionary/RandomSource/координатор) нет; зоны mca-09/10b/10c/12/17c/18 не затронуты.
11. **Holdout honesty.** Блок F, 13 passed: `test_temporal_holdout_lessons_from_past_only`, `test_temporal_holdout_off_parity_is_real`, `test_unknown_outcome_never_becomes_success_or_failure`, `test_source_change_propagates_status`, `test_tool_model_update_invalidates_lesson`; `improvement_measured=False`, replay не трактуется как человеческая реакция.

### Пины/guard (проверка легитимности test-only правок)

- 6 release-pin `2.58.57 → 2.58.58` — prod уже на 2.58.58, T-5014 позже поднимет 2.58.59; это актуализация под реальность, не ослабление.
- `react_moai` census 2→3 — реальный код-чендж mca-15 (silent-path numeric guard); тест фиксирует актуальное поведение.
- Прочие (мелкие catalog-guards, stitch-скрипт `tools/_mca16_reissue_f8.py`) — счётная актуализация, охрана расхождений с fixtures сохранена.

## Что я запустил (точные счётчики)

| Что | Результат |
|---|---|
| `pytest tests/test_mca16_experience_block_{a..f}_round1039.py` (6 файлов) | **91 passed** |
| Репрезентативный slice интеграции: `test_round1025_f8_registry + test_param_catalog + test_frontend_tab_mapping + test_webapp_f11_round1025 + test_mca01_tx_task_supervisor + test_mca05_episodes_stories` | **230 passed** |
| `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 504` |
| `node tests/js/*.js` — все 59 файлов | **59/59 OK**, в т.ч. новый `round1039_experience_lessons_test.js` → `MCA16-EXP-OK` |
| RED: temp `git worktree` на HEAD + копия block_a/c/f тестов → pytest | **collection errors** (`ImportError: cannot import name 'mca_experience'`) — тесты красные без feature-кода ⇒ RED воспроизведён |
| OFF K1/K2 через внешние env | `test_k1_off_inert` + `test_k2_off_feedback_closed` → **2 passed** |
| Дифф-ревизия: REASON_CODES (+10), release-pins (×6), census `react_moai` (2→3), catalog-счётчики | ровно по спецификации, guard не ослаблен |

## Residual notes

- Полная suite (1960) и PG-runtime не реранились — требуются release-policy гейты T-5012/прод-контур; существенное покрыто (91 + 230 + 59 + RED + OFF + `--check`).
- Кросс-домен: `direct_chat_service.py` / `memory_maintenance.py` / `status_service.py` — узкие вставки с fail-open гейтами; риск некомпатибилизации низкий.
- APP_VERSION bump 2.58.59 — T-5014 (DevOps, post-review); live T-5015 — **[PENDING OWNER]** (реальный чат, post-deploy; до этого live-поведение уроков не подтверждено — не блокирует гейт по политике).
- R17: секретов/raw-текста/CoT в диффе и review нет; канонические рекомендации — процедурные формулировки без имён/цитат/chat-ID.
