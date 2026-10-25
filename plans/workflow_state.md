# Workflow State

Task: P0 очередь 26.10 — релиз Speech + Fact-check, далее P0 DELTA
Task source: root chat 25–26.10; snapshots `plans/owner_inputs/2026-10-26-p0-delta-analysis.md`, `2026-10-26-no-meta-scope.md`
Status: in_progress
Primary phase: release
Active feature: asap-speech-arch + p0-factcheck-media → release/p0-2026-10-26
Progress sources: 9 карт; 2023/2459 required (82%), этапы 115/172, поручения 7/18; 11 FAILED (FREQUENT residual), 13 postdeploy
Production: **2.58.130 @ `534ac7dd`**, health 200, unit active, NRestarts 0. Деплоя не было.

Active lanes (не прерывать):
- SPEECH-INT (в `adminbot-wt-speech-int`): NO_META без «сразу вывод», аудит скрытых шаблонов; правки в работе, коммита ещё нет.
- P0-DELTA-AUDIT (read-only): исследование L1/памяти/субъекта/lore по `plans/features/p0-delta-analysis/`.
- FACTCHECK-MEDIA: ревью Approved (266b0e6b), влит в `release/p0-2026-10-26`.
- ALIAS: `f42e2257` Approved.

Release plan:
1. Коммит speech → merge в `release/p0-2026-10-26`; 4 пересечения (database.py, param_catalog.py, registry.tsv, test_round1025_f8_registry.py) разрешить вручную.
2. Один контрольный live-прогон на точном SHA (A/B/C + forced), без повторных кругов.
3. Привязка доказательств (fact-check 151 + speech) к финальному SHA; review/release gate.
4. Финальный Reviewer → version bump → deploy → health/version/errors → продолжить P0 DELTA и остатки.

FREQUENT decision: `plans/features/asap-speech-arch/evidence/p0-hotfix/frequent-decision.md` — причины (исторический budget_excluded исправлен; остаток — вариативность модели), условия приёмки, влияния на релиз нет.

Not closed:
- speech commit + merge + live probe.
- Map binding (factcheck/speech) к финальному SHA.
- P0 DELTA (133 required) — после релиза.
- Мелкие остатки: soul-1 2, asap8 1, asap3 2, asap2 3, win-glass 2, vision 1, add-tr 1, samples 1, p0-factcheck-speech 18+4.
- p0-followup-nostalgia: WAITING_EXTERNAL (сценарий B).

Review: pending (final candidate)
Deployment: pending
Human gate: none
Updated: 2026-10-26T01:25+12:00
