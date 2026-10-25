# Workflow State

Task: P0 очередь 25.10 — speech corrective (L1/Core/aliases/lore) + Fact-check медиа
Task source: root chat 25.10 (две коррективы); snapshots `plans/features/asap-speech-arch/source-owner-p0-corrective-2026-10-25.md`, `plans/features/p0-factcheck-media/source-2026-10-25.md`
Status: in_progress
Primary phase: build
Active feature: asap-speech-arch (P0 corrective) + p0-factcheck-media
Progress sources: 8 карт; 1972/2311 required VERIFIED (85%), этапы 113/157, поручения 7/17; 11 FAILED, 13 postdeploy, 21 owner_optional вне знаменателя
Production: **2.58.130 @ `534ac7dd`**, health 200, unit active, NRestarts 0. Деплоя не было.

Active lanes (не прерывать):
- ALIAS-RUNTIME: коммит `f42e2257` (F1–F7 + a17–a25), идёт независимое ревью.
- CORE/HARNESS: Builder в `adminbot-wt-speech-p0` — полный Core, миграция канона L1, арм-ы стенда.
- FACTCHECK-MEDIA: Builder в `adminbot-wt-fc1` (base `534ac7dd`) — фото/альбомы/пересылка.
- FC-PROD-RECON: завершён, `plans/features/p0-factcheck-media/evidence/prod-recon.md`.
- PM-MAP-FACTCHECK: завершён, `a0cafb38` (137 required, plan-gate EXIT 0).

Root cause Fact-check (доказан production-данными): альбом 10 фото, подпись 2846 симв. только на 1-м элементе; reply на 9-й элемент; между записью буфера и вызовом 84.1 с при TTL 60 с → буфер отдал None → ветка 5.3 «пустота»; подпись уже была в `smart_messages`, vision не вызывался.

Verified / evidence:
- L1 `47fba465`, lore `272170e3`, prod-worktree `dd10de9d` + `prod-worktree-alias.md`, alias `f42e2257` (ревью идёт).
- Fact-check recon: чат `-1002661910336`, альбом `14343246299290082`, target `1175411`, trigger `1175414`, 25.10 05:24:35 UTC.
- Карты синхронизированы с последними коммитами веток (asap3 → 2.58.129 `79ec3726`); прогресс считается.

Not closed:
- Core: 5 вырезаемых абзацев — доказать дубль/конфликт или вернуть в payload.
- Harness: канон-миграция, алиасы в L1, кейс C, FREQUENT-арм; серверный прогон на точном SHA.
- Fact-check: fix + 15 кейсов + 5/10 failed vision + расхождение `flags.vision_enabled` vs env-мастер.
- 11 FAILED (FREQUENT/EX-*, probes) — реальные дефекты.
- Reviewer по всем срезам, сборка единого кандидата, map binding, deploy.

Next unlocks:
1. Принять/отклонить alias review; устранить Needs Fixes.
2. Собрать кандидат (speech + factcheck), один серверный прогон на SHA.
3. Reviewer полного scope → deploy → version/health/errors.

Review: in_progress (alias slice)
Deployment: pending
Human gate: none
Updated: 2026-10-25T17:55+12:00
