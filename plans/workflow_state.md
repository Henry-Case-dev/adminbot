# Workflow State

Task: Полная очередь `plans/current_task.md` — SOUL-1 + ASAP8 v6.3 + инцидент + fullscreen + CFG-01…07 + P0×3 + ADD-TR + ADD-EXP (реестр `plans/progress_scope.json`: 9 задач; 1 VERIFIED)
Task source: current_task.md (+ VERBATIM-снапшоты `plans/features/*/source-*.md`)
Status: in_progress
Primary phase: delivery (2.58.98 deployed; постдеплой-приёмка — владелец) → select_next (CFG-06 build)
Active features: add-exp/soul (2.58.98 deployed; CRITERION READY_FOR_LIVE) · cfg (06 готов к билду; 07B поглощён) · p0-vision (RFL-хвосты)
Progress sources: карты soul-main/amend, cfg, win-glass, p0 A+B, p0-vision, add-tr, add-exp; реестр (9 задач; 1 VERIFIED)

Продакшн: **2.58.98 @ `29cc49ba`** (T0 2026-10-20 02:38:53Z; MainPID 3883387; NRestarts=0; healthz 200 `"version":"2.58.98"`; ERR=0; SKIPS=0; дельта runtime 19/19 set-eq; DDL 36→36; prompt-миграции: 13 owner-кастомов сохранены). Рубеж отката: **`release/fix-2.58.97`=`99f5672c`** (запушен). Deploy evidence `plans/features/cfg/evidence/release-25898/deploy.{md,json}` (деплой-гейт словил 2 бага своего чекера до рестарта — auto-restore, прод не задет). Правило владельца 20.10: живые тесты в чате — сам владелец (`plans/owner_live_checks.md` §2 = F4-матрица 2.58.98), не блокер остальных работ.

Release chain 2.58.98 (весь Approved):
- UNIFIED-CORE `37097f7c` (route coverage 8+4, C14 вычищен ADR-1013-3, F3 директивы) → REVIEW-25898 **Needs Fixes (2 блокера)** → FIX-25898-R1 `1b23d4c9` (18 тестов синхронизированы; FACTORY_SET_SHA256_12 5bca81487001→64ec1c60e278 по контракту; полный pytest 12f/14632p/7err = паритет базы) → ledger cut (CRITERION FAILED→READY_FOR_LIVE честно) → RECHECK-25898-R1 **Approved** (fingerprint пересчитан независимо; гейт review EXIT 0) → PKG-98 `f9e7dd67` (бамп 31 файл SET EQUAL proc-97; guards offline EXIT 0, 868p, 24p, JS 38p+4/4) → REV-REL-25898 **Approved** → push master `29cc49ba` + рубеж отката → DEVOPS-DEPLOY-98 **VERIFIED**.
- Release-гейт add-exp: **rc1 честно** (EXP-ACCEPT.CRITERION ждёт живой F4-матрицы = VERIFIED/FAILED после владельца; прочие ошибки — исторические привязки строк к прежним кандидатам, легаси-леджер). После живой матрицы — статус честно обновить и перегнать `--stage release`.

CFG-очередь: CFG-04/05 DONE+леджер `5e95e96a`; **CFG-06 готов к билду** — бриф `plans/features/cfg/cfg-06-build-plan.md` (W0–W7; plan-гейт EXIT 0; join-barrier = фриз схем; style_note-утечка «unknown» → W5); **CFG-07B поглощён** UNIFIED-CORE (evidence `29cc49ba`: REUSED 10/PARTIAL 1/OPEN 0; PARTIAL 07D.4 span-run → 07C-G); бриф 07A/B/C `plans/features/cfg/cfg-07-build-plan.md` (барьеры G0–G3; Human Gate не требуется).

Active lanes:
- (нет активных; следующая — CFG-06 W0/W1 по брифу после этого отчёта)

Join barriers:
- EXP-ACCEPT.CRITERION: live F4-матрица на 2.58.98 — выполняет ВЛАДЕЛЕЦ (`owner_live_checks.md` §2; пороги §4: frequent >0/≥50%, occasional <frequent, off 0); агенты — только технические (deploy-VERIFIED сделан).
- CFG-06 build: стартуют W0 (аудит deployed) → W1; W3 = фриз схем (join); W4∥W5 после фриза; не ломать швы `speech_owner_block`.
- 07A-2 не merge до релиза CFG-06 (конфликт канонов фактчека); 07C-G после 07A-2.

Last verified (≤5):
- Прод 2.58.98 @ `29cc49ba`, deploy VERIFIED (healthz 200, ERR=0, дельта 19/19, evidence deploy.md).
- RECHECK-25898-R1 Approved (recheck-25898-r1.md; fingerprint 64ec1c60e278; review-гейт EXIT 0).
- REV-REL-25898 Approved (review-rel.md; bump 31 файл byte-discipline 33 пары; guards воспроизведены).
- CFG-07B-V: REUSED 10/PARTIAL 1/OPEN 0 (evidence `29cc49ba`; focused 54p/0f).
- CLEANUP: пользовательские сообщения НЕ удалялись (authorship-audit `c579bf5d`; OQ-13/14 закрыты).

Next unlocks (≤3):
1. Владелец: живая F4-матрица 2.58.98 (§2) → CRITERION VERIFIED/FAILED → перегон release-гейта.
2. CFG-06 build W0→W1→… по брифу (следующая волна оркестратора).
3. Мелкий бэклог: content-length HEAD /static/app.css (низкий, pre-existing); C15-хвост — агентская задача по ADR-1013-3.

Review: approved (RECHECK-25898-R1 + REV-REL-25898; parent не DONE — постдеплой-приёмка за владельцем)
Deployment: verified (2.58.98 @ `29cc49ba`; deploy-scope; release-гейт rc1 честно)
Human gate: none (0 блокирующих; живые пункты — `plans/owner_live_checks.md`, не блокер; очередь `plans/owner_questions.md` пуста)
Backlog (сжато): nano-gpt баланс (owner); housekeeping asap8/mca-17c; F2-типы CFG-03; CFG-02B live-хвост; P0B SCEN-B; soul-main 17 RFL; CFG-02A 4 RFL; set_many/провенанс; «Характер»→«Личности»; anti-flood; A/B-helper; fixture-дрейф; VIDEO not_configured; T-1764; l1_unavailable; L1 cold-start; win-glass 7 пинов; vision: retry-альфа, non-JSON тяжёлые кадры; постген-бюджет 20с; ADD-EXP N1–N4, P7, L1-план/few-shot; C7 humor (позже); C15-хвост (ADR-1013-3, агентская); app.css HEAD content-length; SSH-паузы ≥90с; git: без reset/amend поверх чужих.
Progress scope: plans/progress_scope.json | fresh
Updated: 2026-10-20 12:55 local (2026-10-20 02:55 UTC)
