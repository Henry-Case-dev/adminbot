# Workflow State

Task: Полная очередь `plans/current_task.md` — SOUL-1 + ASAP8 v6.3 + инцидент + fullscreen + CFG-01…07 + P0×3 + ADD-TR + ADD-EXP + SAMPLES-UX (реестр `plans/progress_scope.json`: 10 задач; 1 VERIFIED)
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
- REV-06G3 | Reviewer | read-only | cfg | bg:ses_ea70ce5edffex5XZRRpB8G5SV7 | точечное ревью 06G.3 (factcheck_attribution fat1: детекция без LLM, локальная резолюция дословной цитаты, privacy _strip_privacy, честный отказ, OFF-паритет; гейт CFG-06 уже EXIT 0) → Approved → коммит атрибуции + релизный поезд samples
- PKG-SU | Builder | DONE | release | bg:ses_ea715341fffeHnBIgK27Ky4PZI | бамп 2.58.99→**2.58.100** применён (штатный скрипт = численный инкремент, rollover нет; 31 файл SET EQUAL proc-99, F8-meta HEAD=27b1165a); guards зелёные кроме pins24-1f = foreign 06G.3 (reason 301→302 пересанкционирует 06G.3 при коммите); ΔDDL v36→37 ожидаемо задокументировано (миграция в кандидате 29b91004, 12p реальный путь); evidence samples-ux/evidence/release/
- FIX-SAMPLESUX-R1 | Builder | DONE | samples-ux | bg:ses_ea7305e60ffeuRbWU5wgpC8Rvf | 3 неблокера закрыты: restore_preview include_tombstoned (+1 REGRESSION-тест), бейдж nowrap (probe 360/320px lines:1), why-endpoint category=; 12+8+68+e2e зелёные; закоммичено `27b1165a`
- REV-SAMPLES-UX | Reviewer | DONE | samples-ux | bg:ses_ea744d16effeEN335EohW3meH9 | вердикт **Approved, блокеров нет**: 130 pytest passed + e2e 0 failures; §3 persist/tombstone подтверждены независимо (+эмпирическая проба), §2 байт-сверка спека==runtime==пины, fingerprint 64ec1c60e278, §1 миграция v37 честная, §5 блоки/0 LLM, §4 DOM-e2e+скриншоты 360/390/667/1280, §7 zero-live; ledger-долг закрыт LEDGER-SAMPLES-UX; живые пункты §7 владельцу (не гейты)
- LEDGER-SAMPLES-UX | Builder | DONE | samples-ux | bg:ses_ea72305c4ffeu8TWUnLmO3BkTS | 77 строк: 64 VERIFIED (candidate-bound, реальные sha) + 1 owner_optional (SU-7.OWNER-OBS) + 12 context; 5 слайс-гейтов review EXIT 0; свежесть на HEAD 27b1165a (130p + e2e); честные оговорки (PG N/A by design); закоммичено `532a2d24`
- CFG-06-CANARY | Builder | DONE | cfg | bg:ses_ea744d16dffeBSJA3qvmxgoIgX | **4/4 PASS → VERIFIED @ deployed 7142ffcf**: 06G.1 Saccharomyces (биномен сохранён, Tavily ok, вердикт отделил корректное/ошибочное), 06G.4 (3 интента поиска, честный published_at=None, оговорка ООН), 06E.4 (чанки/теги/Unicode/escape, TelegramBadRequest → только сломанный чанк в plain), 06F.1 (полные stage-trace, admin-детали вне user-payload); 5 LLM + 4 поиска + 4 fetch (2 честных too_many_bytes); ноль сообщений в чаты; related: усечение URL агрегатором (Epic 33) → backlog; закоммичено `cc7ac8d7`; гейт review: 1 честная ошибка (06G.3)
- DEVOPS-DEPLOY-99 | DevOps | DONE | release | bg:ses_ea75c4098ffeYLuKAL0Vs3gEKe | **VERIFIED_DEPLOY**: push `7142ffcf` + рубеж release/fix-2.58.98=29cc49ba; прод 2.58.99 @ `7142ffcf` (T0 09:40:53Z PID 3965603, healthz 2.58.99, ERR=0, дельта 12/12, ΔDDL=0, фактчек-байты == 8f220b60); флаг false→true (hot-механика потребовала плановый рестарт T1 09:44:07Z PID 3966377 — прецедент soul-release-prep, отклонение задокументировано); смоук чистый (прогонов с флагом ещё не было — наблюдение продолжается); откат готов (upsert false + рестарт / checkout 29cc49ba); SSH 3 коннекта, fail2ban чист; deployed_commit карты → 7142ffcf
- REV-REL-25899 | Reviewer | DONE | release | bg:ses_ea77178d9ffepCMX1Ce7EZ6gj6 | **Approved**: состав 100 файлов без лишнего, runtime-дельта фактчека пуста, 115p/0f + агрегат 16/16 + F8 582 + round109 21p; 2 ненакладных внесены в docs-хвост `7142ffcf`
- FIX-PKG99-CATALOG | Builder | DONE | release | bg:ses_ea7970eeeffemVzSBlP7IuIk6w | param_catalog +47 (3 ParamSpec flags.factcheck_* default False); REGISTRY 579→582, F8 --check OK; ~70 тестов перепиновано; UI-копирайт round109 фикс; вошло в `46303ecd`
- PKG-99 | Builder | DONE | release | bg:ses_ea7c9ce97ffeYT9glpp0ceJUa1 | бамп применён (31 файл SET EQUAL процедуры, дизъюнктность samples-ux assert); evidence release-25899/; вошло в `46303ecd`
- FIX-PKG99-PINS | Builder | DONE | release | bg:ses_ea7b8f72cffeMJN2r6gtSfWZOg | 2 корня: 15× Settings 458→461 (ресанкция 34 сайта с провенансом; grep ==458=0) + 1× mca17c v37==36 = чужая samples-ux миграция в дереве (на чистом чекауте релиза зелёный; samples-ux пересанкционирует при своём коммите); агрегат EXIT 0 (13 проверок); эскалации: +19 не-пиновых файлов в релизный коммит, param_catalog ×2 → CATALOG-лейн, L1-publish flake → backlog
- PKG-99 | Builder | DONE | release | bg:ses_ea7c9ce97ffeYT9glpp0ceJUa1 | бамп 2.58.98→2.58.99 применён (31 файл SET EQUAL процедуры, F8-meta HEAD=8f220b60, samples-ux исключена — дизъюнктность assert); guards: 9 зелёных, pins24 красный → FIX-PKG99-PINS; evidence release-25899/ (README+11)
- RECHECK-CFG06-R2 | Reviewer | DONE | cfg | bg:ses_ea7d466efffeY94Hq4iPS0mpPu | вердикт **Approved** (деплой OFF → hot-включение): дельта строго 2 файла, isolation worktree 8f220b60; F3 закрыт по существу (даты в period); леджер: 2 записи sha сверены, отклонение 83c7abae честное; итог 224p/0f; гейт EXIT 1 = 5 честных (06E.4/06F.1/06G.1/06G.4 канарейки + 06G.3 post-release)
- SAMPLES-UX-BUILD | Builder | DONE | samples-ux | bg:ses_ea7f4d7e6ffeAyPrI45UdszTpw | все 5 волн DONE: категории+mode (DDL v37 аддитивно, миграция legacy-честная), tombstone/override/restore-confirm (edit→seed→persist, delete→seed→remains), few-shot блоки по категориям (0 доп. LLM), UI §4 отдельным экраном (browser e2e 6 сценариев, 0 failures), §2 тексты байт-в-байт (пины обновлены; FACTORY_SET не изменился — 64ec1c60e278), SU-ACCEPT 8 интеграционных (403/422/409/428); композит 144p + e2e; ноль live-отправок; кандидат в дереве (коммит после REV-SAMPLES-UX); incidental: ui_soul1_w6_speech_e2e 2 FAIL pre-existing (воспроизведён на чистом HEAD) → backlog
- OWNER-OBS-RECON | PM | DONE | all | bg:ses_ea7eaa61fffeM6iYFlT6lhI2bT | сверка DONE: 1 конвертация (EXP-ACCEPT.CRITERION → owner_optional, F4=владелец §2) + 8 новых owner_optional-строк; чистота доказана (0 новых ошибок гейтов vs HEAD); оркестратор дозаполнил cfg: CFG-04D.4 + CFG-06G.8 → owner_optional (связи на инженерные VERIFIED); сводка plans/features/owner-obs-recon.md
- FIX-CFG06-F3 | Builder | DONE | cfg | bg:ses_ea7e1bce8ffe1M74uGXpePUTRI | mca20 L113-120: temporal_status (RED KeyError) → verdict/freshness/period с датами (суть MCA-20 сохранена); tool_route тест привязан к 06B.1/06H.2; 28p + 137p/0f; закоммичено `8f220b60`
- PM-SAMPLES-UX | PM | DONE | samples-ux | bg:ses_ea80dbbe6ffexacL9kXFTfnDee | карта 76 строк (64 required), plan-гейт EXIT 0, strict_evidence; REUSED/NEW/конфликты F3 задокументированы в reconciliation.md
- FIX-CFG06-F1 | Builder | DONE | cfg | bg:ses_ea8082362ffejdCg5wYs2sG9Cl | блокер F1: tool_router за v2-флагом, OFF байт-паритет; 7 CONTRACT, 94p/0f; закоммичено `83c7abae`
- LEDGER-CFG-06 | Builder | DONE | cfg | bg:ses_ea8127638ffeimAXJKDo32tJQj | 93 строки: 84 VERIFIED / 8 READY_FOR_LIVE / 1 честный PENDING (06G.3 tool «кто сказал» — post-release работа); 9 агрегатов исправлены (path/hash swap — баг оркестратора); CFG-06.CON → VERIFIED; гейт EXIT 1 честно (4 канарейки + 06G.3); Saccharomyces микро-тест закрыл 06G.1; ledger-cut.md
- CFG-06-W0–W7 + REV-CFG-06 + CFG-07A-1 | done | cfg | разные | сборка/аудит/первое ревью (Needs Fixes→F1) — всё в кандидатах `5af56d8b`→`83c7abae`

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
2. CFG-06: deploy 2.58.99 VERIFIED + канарейки 4/4 → слайс закрыт (гейт review = 1 честная ошибка 06G.3 post-release; release-гейт эпики честно rc1 до 07+). Далее: samples-ux FIX-R1 → коммит → леджер 77 строк → гейт → деплой; затем 07A-2 (корпус готов) → 07C-G → CFG-FINAL; 06G.3 «кто сказал» — в ближайшей очереди.
3. SAMPLES-UX build идёт (bg) → ревью → отдельный релизный слот после 2.58.99.
3. Мелкий бэклог: content-length HEAD /static/app.css (низкий, pre-existing); C15-хвост — агентская задача по ADR-1013-3.

Review: needs_fixes (REV-CFG-06: блокер F1 — фикс идёт; леджер-долг закрывается параллельной полосой)
Deployment: verified (2.58.98 @ `29cc49ba`; deploy-scope; release-гейт rc1 честно)
Human gate: none (0 блокирующих; живые пункты — `plans/owner_live_checks.md`, не блокер; очередь `plans/owner_questions.md` пуста)
Backlog (сжато): nano-gpt баланс (owner); housekeeping asap8/mca-17c; F2-типы CFG-03; CFG-02B live-хвост; P0B SCEN-B; soul-main 17 RFL; CFG-02A 4 RFL; set_many/провенанс; «Характер»→«Личности»; anti-flood; A/B-helper; fixture-дрейф; VIDEO not_configured; T-1764; l1_unavailable; L1 cold-start; win-glass 7 пинов; vision: retry-альфа, non-JSON тяжёлые кадры; постген-бюджет 20с; ADD-EXP N1–N4, P7, L1-план/few-shot; C7 humor (позже); C15-хвост (ADR-1013-3, агентская); app.css HEAD content-length; SSH-паузы ≥90с; git: без reset/amend поверх чужих.
Progress scope: plans/progress_scope.json | fresh
Updated: 2026-10-20 20:10 local (2026-10-20 10:10 UTC)
