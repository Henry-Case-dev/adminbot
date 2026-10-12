# Runtime Task — ASAP 8

Feature: `asap8-reliability-truthfulness-cleanup`
Task source: user-owned `plans/current_task.md`, раздел «ASAP 8 — Reliability / Truthfulness / Module Runtime Cleanup» (конец файла, ~строки 33792–35215). Этот файл — recovery-указатель.
Status: in_progress — Phase A/B DONE (аудиты + architecture.md в plans/features/asap8-reliability-truthfulness/); Phase C build: F1 в работе (bg:ses_ecf35a45fffeSS3N41pdTKv3en). Порядок: spine F1→F2→F3→F4→F5→F7→F10 serial; F6/F8/F9 параллельно после F1. Каждый slice: focused tests → Reviewer → commit/deploy when safe → prod evidence.

Baseline: HEAD 0c4f3a5 (release 2.58.74 = ASAP 7 финал). Известный шум дерева не трогать (disk_retention, plans/MEMORY, backlog, archive, reports, _ui_mca12). §1.2: plans/current_task.md owner-owned вне master-трекинга — так и оставить, НЕ коммитить; plans state синхронизировать с HEAD.

## 8 P0/P1 симптомов (repro обязателен до фикса, §31.3)
1. Summary: L1 OK → L2 `invalid_paragraph` (PARAGRAPH_MAX=900 в summary_l2_writer.py топит документ) → Legacy; UI «L2 не выполнено» = ложь; coverage 0/865.
2. Summary Test: run_l1 без source_window (summary_test_run.py) → raw message_id → unknown_message_id; prod — anchors. Нужен единый build_summary_execution_input().
3. Style Edit style-first (compile_style_prompt: P0/P1 style до story brief) съедает сюжет Base (A/B: OFF = сюжет есть).
4. Run Inspector latest: include_prompt только при pipelineSelectedRunId → блок скрыт; missing manifest → silent hide; Prompt editor (ИИ→Промпты) raw textarea без server preview.
5. parentGate flags.summary_enabled ложно блокирует Direct/Factcheck/Search/Transcription/Video/Web/Diagnostics; «отключён глобально» при chat scope.
6. Initiative: heartbeat по существующим intents; producers отсутствуют (audit create_intent call-sites); handle_initiative без prepared_text → вечный defer; нужен producer→decision→L2 Writer(trigger=initiative)→SendRecheck→send, без третьего Writer и без endless candidate_ready.
7. Embeddings: group=unknown без EMBEDDING_QUOTA_GROUP_LABELS → cooldown замораживает весь пул; text-only факты без auto-backfill; WARN-спам.
8. YouTube: 407 ProxyAuth = transient (_is_transient) → retry storm; нужен proxy_auth_failed permanent, no retry; proxy health UI.

+ Module Contract v2 re-audit (§8): rationale ≠ blanket exemption; повторный audit список §8. Experience scope (§9): catalog per-chat vs runtime global. Random (§10): product master или честная infrastructure. Stories humanize (§14). Truthful Status audit (§17). Аудит коммитов e6670b0/71b3b69/3e52b96/a1b3279/0c4f3a5 (§18).

## Слайсы (§27C, исполнять последовательно по §31)
F1 Summary validator reliability + granular diagnostics; F2 Summary Test parity/anchors; F3 Cover Style scene preservation; F4 Cover exact-prompt UX; F5 Module dependency truth + scope; F6 Initiative producer→writer→send; F7 Stories/Experience/Random UX; F8 Embedding quota-group recovery; F9 YouTube proxy classification; F10 plans/help/status reconciliation. Каждый: review → focused tests → deploy when safe → prod evidence.

## Тесты: S1–S7, C1–C7, M1–M7, I1–I9, E1–E5, Y1–Y5 (§19–24). Лог-гигиена §26. Запрещённые shortcuts §28 (24 позиции). DoD §29. Отчёт §30.

## Owner-contracts §0 (не ломать): SQLite+PG; L1→tools→L2; force/🗿; модульность; full prompt не в generic logs; styled cover сохраняет сюжет; Summary Test = production contract; live acceptance не прячется в backlog при «COMPLETED».

Финал невозможен без production proof для P0 и при stale plans-state.
