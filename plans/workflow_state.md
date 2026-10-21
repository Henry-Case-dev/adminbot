# Workflow State

Task: Полная очередь `plans/current_task.md` — SOUL-1 + ASAP8 v6.3 + инцидент + fullscreen + CFG-01…07 + P0×3 + ADD-TR + ADD-EXP + SAMPLES-UX (реестр `plans/progress_scope.json`: 10 задач; 1 VERIFIED)
Task source: current_task.md (+ VERBATIM-снапшоты `plans/features/*/source-*.md`)
Status: in_progress
Primary phase: delivery (2.58.104 deployed VERIFIED) → select_next: хвосты CFG (биндинг 07B/07C/06-RFL) → CFG-03 → CFG-FINAL
Active features: cfg (07A/07D.5/07C-G/06 закрыты; 07B-строки/07C-строки/CFG-03/CFG-FINAL — хвосты) · add-exp/soul (2.58.98 RFL-хвост = владелец, не блокер) · p0-vision RFL-хвосты
Progress sources: карты soul-main/amend, cfg, win-glass, p0 A+B, p0-vision, add-tr, add-exp, samples-ux; реестр plans/progress_scope.json (10 задач; 1 VERIFIED)

Продакшн: **2.58.104 @ `8ea6ed4e`** (T0 2026-10-20T21:00:23Z; PID 29475; healthz 200 `"version":"2.58.104"`; delta runtime 5; ΔDDL=0; ERR=0; кастомы 7/7 целы + effective чистый; telemetry 0 events — наблюдение продолжается; откат lossless). Рубеж отката: **`release/fix-2.58.103`=`2a3e4fc9`** (запушен). Deploy evidence `plans/features/cfg/evidence/cfg-07a/release/` (коммит `a9917abb`). master = origin/master = `a9917abb`.

Хвост CFG-эпика (единственные реальные незакрытые строки карты cfg):
- **CFG-07B: 12 PENDING** — слайс поглощён UNIFIED-CORE (REUSED 10/PARTIAL 1/OPEN 0, evidence `29cc49ba`); строки ждут биндинга к существующим доказательствам (переключатель мата = Expression-режим ADD-EXP, деплой 2.58.98+; PARTIAL 07D.4 span-run закрыт 07C-G).
- **CFG-07C: 11 PENDING** — код доставлен (`7c3a1350` словарь+guards, `f1e31d27` швы, `8cd2ca14` B1-telemetry, `04593c8f` 07D.5 runtime, прод 2.58.103/104); строки 07C.1–.5/07D.6/.7 ждут биндинга (07C.6 уже VERIFIED на проде).
- **CFG-03: 14 PENDING** (5 VERIFIED) — аудит всех параметров MiniApp: R1-манифест покрытия, R2-сводка, runtime-пути фоновых задач; реальная инженерная работа, нужна реконсиляция «что уже покрыто UNIFIED-CORE/F8-582».
- **CFG-FINAL: 17 PENDING** — композитная приёмка ADD-2 №1–8 + процесс-контроль ADD-0; барьер G3 = все слайсы 06+07 VERIFIED.
- RFL-хвосты: CFG-06 ×4 (канарейки 4/4 PASS @ deployed `7142ffcf` — биндинг), CFG-02A ×4 (live), CFG-04 ×1, CFG-07A ×1 (07D.1.OBS owner_optional).

Active lanes:
- (пусто — восстановление состояния; новые лейны запускаются оркестратором)

Join barriers:
- G3: CFG-FINAL стартует только после VERIFIED всех строк 06+07 (биндинг 07B/07C + CFG-03).
- EXP-ACCEPT.CRITERION / живые пункты владельца: `plans/owner_live_checks.md` §2,7,8 — добровольно, не блокер (standing rule 20.10).

Last verified (≤5):
- Прод 2.58.104 @ `8ea6ed4e`, deploy VERIFIED, кастомы 7/7 целы, откат lossless (`a9917abb`).
- Леджер CFG-07A: все 11 инженерных строк VERIFIED @ `d860a529`; гейт CFG-07A EXIT 0 errors=0 (`dd6acf83`).
- REV-07D5-r2 Approved (bounded retry + FA/MB-детекторы; F1–F4 ремонт; 0 ложных на 202 POSITIVE) — `review-07d5-r2.md`.
- REV-REL-258103/258104 Approved (бамп 31 файл, F8 582==REGISTRY, fingerprint 037080375ac8 цел).
- CFG-07C.6 VERIFIED на проде 2.58.103 (wiring по реальным байтам; telemetry 0 events — наблюдение) — `ce77b2c4`.

Next unlocks (≤3):
1. Биндинг строк CFG-07B (UNIFIED-CORE evidence) + CFG-07C (коммиты волн) + CFG-06 канарейки → plan/review-гейты.
2. CFG-03 реконсиляция: что реально покрыто (UNIFIED-CORE param_catalog 582/F8), что доделать (манифест R1, сводка R2, фоновые runtime-пути).
3. CFG-FINAL (композит ADD-2.1–2.8) после G3; release-гейт эпика перегнать на deployed `8ea6ed4e`.

Review: approved (все волны 06/07A/07C-G/07D.5 Approved; хвостовые строки — биндинг без нового кода)
Deployment: verified (2.58.104 @ `8ea6ed4e`; ΔDDL=0; телеметрия наблюдается)
Human gate: none (0 блокирующих; OQ-15 + owner_live_checks §2/7/8 — добровольные, `plans/owner_questions.md`)
Backlog (сжато): nano-gpt баланс (owner); housekeeping asap8/mca-17c; CFG-02B live-хвост; P0B SCEN-B; soul-main 17 RFL; CFG-02A 4 RFL; set_many/провенанс; «Характер»→«Личности»; anti-flood; A/B-helper; fixture-дрейф; VIDEO not_configured; T-1764; l1_unavailable; L1 cold-start; win-glass 7 пинов; vision: retry-альфа, non-JSON тяжёлые кадры; постген-бюджет 20с; ADD-EXP N1–N4, P7, L1-план/few-shot; C7 humor (позже); C15-хвост (ADR-1013-3); app.css HEAD content-length; SSH-паузы ≥90с; git: без reset/amend поверх чужих.
Progress scope: plans/progress_scope.json | fresh (после биндинга хвостов перегнать workflow_progress)
Updated: 2026-10-21 (local, UTC+12)
