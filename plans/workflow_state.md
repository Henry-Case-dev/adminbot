# Workflow State

Task: Полная очередь `plans/current_task.md` — SOUL-1 + ASAP8 v6.3 + инцидент + fullscreen + CFG-01…07 + P0×3 + ADD-TR + ADD-EXP + SAMPLES-UX (реестр `plans/progress_scope.json`: 10 задач; 1 VERIFIED)
Task source: current_task.md (+ снапшоты `plans/features/*/source-*.md`; КОРРЕКТИВЫ владельца 21.10: `plans/features/owner-corrective-2026-10-21.md` + `owner-corrective-followup-2026-10-21.md` — исполнены, прод 2.58.107)
Status: in_progress — КВОТА ПРОВАЙДЕРА: субагенты (Builder/Reviewer/DevOps) недоступны до 2026-10-26 14:05 (недельный лимит); механические хвосты доделаны оркестратором-fallback, независимое ревью/поезда/пробы — в очереди на восстановление
Primary phase: select_next → (квота) PKG-112 (FactView fix 138330c0+10f3a2a0, review-условие B-1 выполнено) → REV-REL-112 → deploy → REV ASAP2 (5ad73933) → поезд 2.58.113 → W4 UI (asap-speech-arch) 
Active features: asap2-direct-chat (код+tests готовы 5ad73933; семантика PENDING quota) · asap-speech-arch (W3 done e5774789; остались W4 UI U-01..U-09, full-matrix/48h PENDING_LIVE) · summary found-fix (готов к поезду 2.58.112)
Progress sources: карты soul-main/amend, cfg, win-glass, p0 A+B, p0-vision, add-tr, add-exp, samples-ux, asap-speech-arch, asap2-direct-chat; реестр plans/progress_scope.json (12 задач)

Продакшн: **2.58.110 @ `a8d2a45a`** (T0 07:26:20Z UTC; PID 447331 NRestarts=0; healthz 200; journal 0 CRIT/0 ERR; ΔDDL=0; канонная лестница L1-планера прошла — PG-канон == новому байт-в-байт, 7 кастомов EQ_BASELINE, fingerprint runtime==3507bd6f92eb). Рубеж отката: **`release/fix-2.58.109`=`a1d8bd62`** (запушен). master=origin/master=`553400bc` (docs-хвост; прод на a8d2a45a). Живое: первый L1D-реакт (💀 → Telegram REACTION_INVALID → fail-soft unavailable, INC-258110 low — в наблюдение/бэклог).

CORRECTIVE-ЦИКЛ (21–22.10, закрыт): три первопричины → три минимальных фикса → офлайн-верификация → ревью 3/3 Approved → прод 2.58.107.
- DIRECT-L1: правила 2–3 без позитивных критериев молчания + L1 не видел ответов бота (bot_replies) → правила переписаны (смысловые критерии, без списков слов), секция «ОТВЕТЫ БОТА» + allowed-реакции в существующем контексте. Офлайн: тривиальные 4/4 react, содержательные reply.
- EXPRESSION: шапка-«настройки» нейтрализовала директиву + разбавление огромным system; модель НЕ виновата (минимал 4/4) → Core очищен от мат-темы полностью (full+compact+гвард superseded-core против воскрешения из PG), Expression = единственный регулятор, директивы OFF/EPISODIC/FREQUENT дословно владельца; мат-разрешения вычищены из 9 активных канонов. Офлайн: OFF 4/4 чисто, EPISODIC 3/4, FREQUENT 3/4, контроль 0/4.
- NOSTALGIA: дата вместо ценности + императивы промпта → право отказа в обоих канонах (отказ — норма), сняты императивы, полный пул в лог, target_user; БЕЗ фильтра длины (запрещён владельцем). Офлайн-реплей: слабый класс 4/4 → UNCHANGED.
- FACTCHECK (вейпинг-кейс): временная ветка не использовала смысловой планировщик (дословный слайс 200 символов) + all-or-nothing вердикт + snippet-only → envelope подключён к единому VERIFIED retrieval, запросы из claim-parts, overlap-релевантность + SafeFetcher, per-claim mixed-вердикт, рендерер привязывает ссылки. Replay: «Недостаточно данных» → «Подтверждается частично» с CDC-первоисточником. 22 CONTRACT, 502 регресс green.
- NOSTALGIA-no-candidates-efficiency: закрыт как проверенная (пустые проходы дешёвые, доказано аудитом).
Живое подтверждение: 48ч наблюдение L1_PLAN/expression_diag/factcheck по существующей телеметрии (не гейт); 14.2 — первое реальное сообщение.

Active lanes:
- SOUL1-FINAL-RECON | Builder | writer(биндинг) | soul-1 | bg:ses_e9e29dce9ffeCQd2LK531uftWn | построчная реконсиляция 48+12 инженерных строк (EXEC/BOUND/03/04/05/08/09/10/11/12/15/16/19/21/AMD); REAL_WORK фиксировать, не реализовывать
- TAILS-ASAP8-CFG-P0B | Builder | writer+harness | asap8/cfg/p0b | bg:ses_e9e29dce8ffe4NvKe8DiVOc1MY | 27+4+2 строк: bind/context + harness (V02/V03/B02/B03/R12/R14/R15/R19, CFG-02A квоты, P0B сценарии); ≤18 платных вызовов
- FIX-INITIATIVE-L1D | Builder | writer(код) | asap8/initiative | bg:ses_e9e2377d9ffea8z519sT2V1Kdd | CORRECTIVE 22.10: выбор формы участия (say/react/silent × chat/reply) переносится в L1 Decision; хардкод-резолвер 2.58.109 устраняется; транспорт — только исполнение + техпроверки; 8 тест-кейсов §8 + офлайн-пробы L1

Join barriers:
- 48ч наблюдение 2.58.107–109 (L1_PLAN/expression_diag/factcheck/strip-fence/init-reply) — read-only сверка при следующем заходе; не гейт.
- Живые проверки боевого потока (asap8 13 RFL, CFG-02A 4 RFL, P0B SCEN-B, 14.2 first real message) — owner_optional/WAITING_EXTERNAL.

Last verified (≤5):
- DEVOPS-DEPLOY-258109 VERIFIED: 2.58.109 @ a1d8bd62 (reply-биндинг инициатив активен с выката; journal 0 CRIT/0 ERR; blob == кандидату; откат release/fix-2.58.108; хвост `0e55d830` запушен).
- REV-REL-258109 + REV-INITREPLY Approved (последний подтверждённый инженерный дефект закрыт).
- DEVOPS-DEPLOY-258108 VERIFIED (12/12 postdeploy-позитивов; strip-fence ready, heavy GT 3/3; ADD-TR/Vision закрыты).
- Реестр обновлён 22.10: 5/10 задач VERIFIED (add-tr, p0-vision, win-glass, samples-ux присоединились к p0-save-init-ux); `a7702559` запушен.
- NOSTALGIA-no-candidates-efficiency закрыт как проверенная (пустые проходы дешёвые — nostalgia-audit).

Next unlocks (≤3):
1. Следующий заход: read-only сверка 48ч телеметрии 2.58.107–109 (L1_PLAN react/silent доля, expression_diag, factcheck traces, init-reply) — по факту реального использования.
2. Backlog-селекция с владельцем: мелкие улучшения (F2-типы, narrator-фраза, app.css, «Характер»→«Личности», anti-flood, C7, C15, ADD-EXP N1–N4/P7) — не мандатные, по приоритету владельца.
3. WAITING_EXTERNAL: VIDEO not_configured; P0B SCEN-B (затишье); живые просмотры — добровольно.

Review: approved (corrective, factcheck, harness/fence, initreply, поезда 105–109)
Deployment: verified (**2.58.109 @ `a1d8bd62`**, ΔDDL=0, откат `release/fix-2.58.108`)
Human gate: none (0 блокирующих; owner_live_checks §2/7/8/9 + OQ-15 — добровольные)
Backlog (сжато): DIRECT-L1/EXPRESSION/NOSTALGIA-SEMANTICS/FACTCHECK-UNIFY — ИСПРАВЛЕНЫ (2.58.107); ADD-TR/Vision хвосты + non-JSON heavy frames — ИСПРАВЛЕНЫ (2.58.108); INITIATIVE-REPLY — фикс идёт (2.58.109); NOSTALGIA-no-candidates-efficiency — закрыт проверенной; asap8 PROBE-остатки (13 RFL, боевой поток); F2-типы CFG-03; «Характер»→«Личности»; anti-flood; fixture-дрейф; VIDEO not_configured (WAITING_EXTERNAL); T-1764; l1_unavailable; L1 cold-start; постген-бюджет 20с; ADD-EXP N1–N4, P7; C7 humor; C15-хвост; narrator-канон identity-фраза; app.css content-length; nano-gpt баланс (owner); SSH-паузы ≥90с; git: без reset/amend поверх чужих.
Progress scope: plans/progress_scope.json | fresh (91% — 896/975; поручения 5/10 @08:05 22.10)
Updated: 2026-10-22 08:10 local (UTC+12)
