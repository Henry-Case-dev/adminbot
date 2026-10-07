# ASAP 5 — Scanner audit (T-5272, safety/R17): «к деплою ДА»

Дата: 07.10.2026. Режим: read-only (писал только этот отчёт).
Кандидат: **working tree поверх `fbdc95c`** (прод 2.58.67 → кандидат 2.58.68 у DevOps, bump — DevOps по D18/CA-11).
Биндинг независимо подтверждён: финальные хеши лейн B1/B2/B3 — бит-в-бит (git hash-object / sha256[:16] по evidence-таблицам);
`t5270_candidate_hashes.json` — **142/143**, единственный drift `plans/workflow_state.md` = чужой WIP вне кандидата (ожидаемо);
routes.py sha256 = `8153b8bd…c7b45` = `ROUTES_SHA256_F11` байт-в-байт.

## Вердикт: к деплою ДА (C=0, H=0)

## Чек-лист — факты (file:line)

1. **Summary (B1)** — gate/таксономия/fingerprint/policy целы:
   - unusable-gate: terminal только при ≥2 HARD с разными кодами И разными paragraph targets, либо deterministic proof (`quote_reason_codes`) — `summary_l2_review.py:415–429`; применение `:1142–1180`; даунгрейд → needs_fixes + трейс-событие `l2_unusable_gate`; 0 findings после даунгрейда → degraded publish (не Legacy). 1 HARD + soft ≠ terminal — обхода нет; после цикла остаточный HARD → Legacy (INV-1, `:1387–1401`).
   - unknown severity/код модели → `dropped` (`:349–351`), никогда не blocking; severity назначает сервер по коду (`finding_severity:225–231`), модельное поле игнорируется; anchor-mode — то же (`_verdict_from_anchor_result:462–478`).
   - таксономия 15/15 ровно один класс, 13 hard / 2 soft (`FINDING_CODE_TAXONOMY:193–216`), demote запрещён.
   - stagnation по fingerprint code+paragraph+sorted(refs) (`:432–441`), break только без прогресса/без изменения документа (`:1203–1228`), burned-revision ограничен MAX_REVISIONS ≤2 — bypassa нет.
   - HYBRID_DEGRADED_PUBLISHED — honest: пишется только при `pipeline_health=degraded` с точной причиной (`summary_generator.py:2375–2389`), в витрине = degraded, не «успех».
2. **Cover (B2)**:
   - CoverPromptManifest fail-closed: `manifest_public(include_prompt=False)` (`cover_prompt_assembly.py:411`), admin-reader `job_manifest(include_prompt=False→True)` (`cover_style_preview.py:206–218`); **веб-экспозиции нет вообще** → не-админ не получает ничего (vacuously 403/скрыто).
   - полный sent prompt в generic логах/R17-событиях отсутствует по построению whitelist: `SAFE_LOG_FIELDS:223–238`, `_INSPECTOR_USAGE_FIELDS:244–252` — только id/числа/enum, текстовых полей нет; персист — payload `task_jobs` (в API не отдаётся).
   - squeeze: `minimal=True` удалён; `retry_core` всегда несёт story floor 160/100% (`cover_style_jobs.py:1180–1217`, `story_floor_text:88–96`) — обойти нельзя; profile floor ≥50% (`:99–111`).
   - limit_source honest: unknown → `resolved_limit=None` (`cover_style_jobs.py:1207–1208`, `cover_prompt_assembly.py:381/545`).
3. **GraphRAG/Embeddings (B3)**:
   - future-resume: `RESUME_TICK_SECONDS=900` ≤15 мин (`graphrag_rebuild.py:109`), идемпотентный тик один на процесс (`:460–495`), `include_failed=False` — failure-класс не переоткрывается; `knn_source_empty` stable terminal.
   - canary fail-safe: недоступность → unknown, никогда не бросает, без writes в active (`embedding_control_plane.py:1964–1981`); cosine 0.98/0.95 (`:1765–1766`); тексты 3 фиксированные non-sensitive (`:1769–1773`).
   - storage generation-isolated: shadow `{index}_g{gen}` + существующий `_activate` (swap, одна транзакция; DROP/ALTER в control-plane отсутствуют — grep 0).
   - bootstrap: `_SYNTHETIC_SECRET_GROUPS={keys_random}` (`config_cache.py:50`), синтетика деривационная, секрет → "" → `_mask_secret` → configured=false (`routes.py:284–293`), строк в БД не создаёт; **pg_db.py:722 цел** (секреты не сидятся); реальные потребители `get_all()` (routes.py:489/941, debug_config) — keys_llm не синтезируется, экспозиции нет.
4. **Random/UI**: gate ≠ last-attempt — раздельные поля `scheduler_gate`/`last_attempt_result`/`last_attempt_retry_class`/`next_auto_attempt_at` (`memory_agi.py:655–718`), структурные причины сохраняют приоритет; bootstrap 2 ч / кап 6/сутки (`mca_gates.py:1542–1590`). Semantic zoom presentation-only: DataSet не режется, `ds.update` меняет только font-опции (`app.js:15375–15445`), канонический label не меняется. Oversight-роуты (mca-17c) и routes.py — не в диффе (0 правок).
5. **R17**: Decision Trace — whitelist-проекция `_trace_event_row`/`_trace_stage_row` (`pipeline_analytics.py:1238–1271`) — коды/числа/status, без story/claim-текста. Мой независимый скан 157 файлов дельты (sk-/xox/ghp/AIza/TG/DB-URL): 8 хитов — все pre-existing (regex-докстринги маскировщика `llm_client.py:64/85`, синтетика тестов); **новых секретов 0**. Живых chat-ID в новых тестах 0 (CHAT_ID=-100 синтетика).
6. **Замеры (импорт, независимо)**: v33 / каталог 529 / KS 85 / reason 280 / тулы 14 / реестр 47 / APP_VERSION 2.58.67 — всё сходится; v34 не появилась; дельта каталога = ровно +6 санкционированных не-секретных ключей `models.embedding_fallback{1,2}_{base_url,model,quota_group}` (group models_embeddings), удалённых ключей 0; reason-словарь не расширялся (0 из допустимых +2 — `l2_unusable_gate`/`l2_stagnation_fingerprint`/`l2_soft_only_needs_fixes` живут в stage-строках/metrics).
7. **Инцидент B3→B2 git checkout**: финальные хеши всех 4 откатанных cover-тестов + manifest-теста = бит-в-бит восстановление B2 (f5491672/796e666d/80022a15/216fc8f2/857d0db8); `test_summary_deploy_round1026` = 9305ce9c — задокументированный финальный AST-pin аменд (Append B2). Дрейфа нет.

## Независимые прогоны

- Фокус: 6 новых тест-файлов + mca01_tx (пин) + mca17c invariants = **114/114 passed**.
- JS: **63/63** (посимвольный прогон всех tests/js, exit-code).
- Барьер-лог: сегменты 12423+4 + `test_104_backend_additions` 11 = 12434/4 = collect 12438 — числа evidence сходятся.

## Findings

**C: 0. H: 0.** Blocking — нет.

- **M (related-nonblocking, feature-completeness): CoverPromptManifest UI не подключён.** T-5252/T-5253 (Settings UI + Analytics), T-5254, T-5266 (visual QA) — открыты; веб/API-читателя манифеста в кандидате нет (только серверный субстрат). Безопасность не страдает (экспозиции нет = fail-closed), регрессий нет, но владелец до закрытия фичи не увидит отправленный prompt в UI (R8/R11/R12 UI-часть). Действие: закрыть T-5252/T-5253/T-5266 до T-5275 (не до деплоя).
- **L:** таксономия 13 hard/2 soft vs 8 примеров в тексте D2 — все 15 классифицированы, направление fail-closed, контракт «ровно один класс» соблюдён.
- **L:** D13 по букве: helper `web/api/config_payload.py` не создан, синтетика — в `config_cache.get_all()`; routes.py байт-цел (пин), результат функционально эквивалентен, честно отражено в evidence.
- **I:** unguarded commit-сайты `database.py:5454` / `embedding_control_plane.py:2022` — субстрат спит (прод-колеров нет, grep 0), advisory в backlog (обернуть в `serialized()` при активации воркера).
- **I:** в `t5270_candidate_hashes.json` drift `plans/workflow_state.md` — чужой WIP, вне кандидата; гигиена коммита: `deploy_commands.txt`, `node_modules/`, `tools/_d2_*/_t5126*/…`, `plans/verification_cache.json` — не включать (прецедент 10.47/10.48).
- **I:** `coverage_matrix.md` из брифа в пакете отсутствует (живёт в archive/…round1047 по cross-lane фиксу 10.47) — не дефект кандидата.

## Binding

Working tree 07.10.2026 поверх `fbdc95c`; контроль: routes sha256 8153b8bd…c7b45; хеши лейн — evidence.md/integration_evidence.md (все перепроверены, 0 drift в продуктовом дереве). Любая позднейшая правка сервисов/tests инвалидирует этот вердикт.

**Следующий шаг Orchestrator:** DevOps — деплой 2.58.68 (bump по D18, миграций нет — DDL 0/v33, smoke не требуется; rollback soft/cold по spec §8; fail2ban-дисциплина AGENTS.md). Параллельно — Review T-5271 и открытые UI-задачи T-5252/T-5253/T-5266 до T-5275.
