# Workflow State

Task: Полная очередь `plans/current_task.md` — SOUL-1 + ASAP8 v6.3 + инцидент + fullscreen + CFG-01…07 + P0×3 + ADD-TR + ADD-EXP (реестр `plans/progress_scope.json`: 9 задач; 1 VERIFIED)
Task source: current_task.md (+ VERBATIM-снапшоты `plans/features/*/source-*.md`)
Status: in_progress
Primary phase: build
Active features: add-exp/soul (UNIFIED-CORE, кандидат 2.58.98) · cfg (04/05 DONE; 06→07A/B/C ждут) · p0-vision (RFL-хвосты)
Progress sources: карты soul-main/amend, cfg, win-glass, p0 A+B, p0-vision, add-tr, add-exp; реестр (9 задач; 1 VERIFIED)

Продакшн: **2.58.97 @ `99f5672c`** (T0 2026-10-19 19:13:31Z; PID 3791730; NRestarts=0; SKIPS=0; дельта 5/5). Рубежи отката: 96=`95d11472`, 95=`113f3a62`, 94=`9072347b`. Правило владельца 20.10: живые тесты в чате — сам владелец (`plans/owner_live_checks.md`, не блокер); агенты — только технические проверки, случайно отправленное удалять сразу.

Active lanes:
- FIX-25898-R1 | Builder | writer | add-exp/soul | bg:ses_ea9245de7ffesDo3IrmvhvcpDl | Блокер 1 ревью: 18 тестов (checkup chat_id ×11, style_anchors C6, humor ×2, registry fingerprint ×4 + бамп FACTORY_SET_SHA256_12 по контракту) + EXPRESSION_NOTES без жанровой оговорки; полный pytest до паритета с базой (12f/7err); БЕЗ коммита
- REVIEW-25898 | Reviewer | DONE | add-exp/soul | bg:ses_ea96f3426ffeIFIkVOgjW2Y1dA | вердикт **NEEDS FIXES (2 блокера)**: (1) 18 новых failures — сознательные владельческие изменения без синхронизации тестов/отпечатка; (2) гейт EXIT 1 — карта не перерезана на `37097f7c`, CRITERION должен стать READY_FOR_LIVE с predeploy-доказательствами и postdeploy F4-матрицей; код по существу подтверждён (route coverage полон, F3 байт-точно, C14/C13 корректны, запреты целы); evidence review-25898.md
- CFG-07-PREP | PM | read-only+план | cfg | bg:ses_ea915a303ffeN3GzJ4eI3ko2ph | разбор ТЗ 07A/B/C → CFG-FINAL: что уже покрыто UNIFIED-CORE `37097f7c` (REUSED_EXISTING с доказательствами), слайсы/скоупы/зависимости от W-этапов 06, критерии приёмки; код читать через git show фиксированного SHA, дерево не трогать; выход plans/features/cfg/cfg-07-build-plan.md
- UNIFIED-CORE-FINISH | Builder | DONE | add-exp/soul | bg:ses_ea99634d2ffeLVrLPGqAcHSvfu | чек-лист спеки закрыт (кроме C7 — отложен): route coverage 8 user + 4 нейтральных, C14 вычищен (ADR-1013-3), 18/18 CONTRACT, фокус 471 passed; кандидат закоммичен оркестратором `37097f7c`
- DELETED-AUTHORSHIP-AUDIT | Builder | DONE | closure | bg:ses_ea97fa783ffeWz1PCiSJ0YWBuc | вердикт: пользовательские сообщения НЕ удалялись (0 из 175 удалённых mid; все — бот; пересечение с 278 пользовательскими mid пусто); «27 not_owned» живы; метод 21:11Z пользовательские затронуть не мог; evidence authorship-audit.{md,json}; SSH 0 коннектов; OQ-14 VERIFIED

Join barriers:
- Кандидат 2.58.98 закоммичен `37097f7c` (F3-директивы + UNIFIED-CORE) → REVIEW-25898 идёт → при Approved: bump 2.58.98 → release-гейт → push (рубеж `release/fix-2.58.97`=`99f5672c`) → deploy → owner live-checks. Остаток: C15-хвост (legacy-абзац в checkup/search/youtube/web/summary-single канонах — перекрыт приоритетом шапки; отдельное решение владельца с бамп+слепок) → backlog. Один райтер на factcheck-файлы: CFG-06 стартует после вердикта ревью (бриф уже готовится CFG-06-PREP).
- CFG-очередь: CFG-04 DONE (commit `2428768`; REV `e27216d3`; live tech PASS 7/7 прод-байтов) → CFG-05-VERIFY DONE `90cfc471` → LEDGER-04/05 DONE `5e95e96a` (review EXIT 0 ×2; release rc1 = очередь не завершена — честно) → далее CFG-06 (Temporal+Factcheck реконструкция) → 07A/B/C → CFG-FINAL; `c48fe4cf` verify-only.
- ADD-EXP: F1 `5b86517e`; F3-директивы (точные тексты владельца, без счётчиков/постпроцессора) в дереве; CRITERION остаётся FAILED (advisory frequent 1/6, occasional 0/10); F4 → `plans/owner_live_checks.md`; F2 few-shot = owner optional; ACCEPTANCE-97 отменена владельцем 20.10.
- P0-правило owner 20.10 (архитектурное): Core+Expression+Style на ВСЮ пользовательскую речь; жанровые исключения отменены; внутренние процессы (JSON/tools/search/OCR/logs) нейтральны; цитаты/OCR/JSON целы; приёмка — фактические effective payload; GLOBAL/per-chat + hot-apply. Аудит `a7d42450` (C1–C6/C8/C16 в дереве; C14 → вычистить; C7 — позже).
- Уборка: CLEANUP-97-NOW DONE (23/23, residual 0; real-people не тронуты); CLEANUP-ALL-CHATS closure-проход идёт (bg); helper `cleanup_now.py` готов.
- SCEN-B ностальгии: WAITING_EXTERNAL (естественное затишье; авто-детект при следующей волне).

Last verified (≤5):
- Прод 2.58.97 @ `99f5672c`, deploy VERIFIED (evidence `19a235ea`; дельта 5/5; маркеры CFG-04 10/10 + F1 7/7).
- LEDGER-04/05 `5e95e96a`: CFG-04 8V + 11 live tech V; CFG-05 8V reuse; гейты EXIT 0 ×2.
- CFG-05-VERIFY `90cfc471`: product-diff 0, 178≡base, пиксели 0.
- Аудит промпт-конфликтов `a7d42450` (17 ranked; основа UNIFIED-CORE).
- ADD-EXP леджер `3a49d545`: 28V + 1 FAILED (CRITERION — честно).

Next unlocks (≤3):
1. FIX-25898-R1 (bg) → оркестратор коммитит фикс → кандидат v2 → леджер-привязка v2 (EXP-ACCEPT.*/EXP-REG + CRITERION→READY_FOR_LIVE с postdeploy F4-матрицей; держать честный off-prod eval false) → гейт EXIT 0 → ревью речек v2 → Approved → PKG bump 2.58.98 → release-гейт → push (рубеж `release/fix-2.58.97`=`99f5672c`) → deploy → F4-матрица на проде → VERIFIED/FAILED честно → --stage release.
2. CFG-06 build W0→W1…W7 по брифу `plans/features/cfg/cfg-06-build-plan.md` (plan-гейт EXIT 0; старт после вердикта ревью).
3. OQ-13/OQ-14 закрыты; очередь `plans/owner_questions.md` — 0 обязательных. C15-хвост (bypass-строка в code-канонах checkup/search/youtube/web/summary-legacy; на проде нейтрализована suppress_legacy_speech, активна только при PG down) — тот же смысл «вычистить», что решение владельца по C14; оформить как агентскую задачу по протоколу ADR-1013-3 (бамп+слепок на канон), НЕ новый вопрос владельцу.

Review: needs_fixes (REVIEW-25898: 2 блокера; фикс 1 идёт bg, леджер — после коммита фикса)
Deployment: verified (2.58.97 @ `99f5672c`; следующий кандидат 2.58.98 — pending)
Human gate: none (0 блокирующих; живые пункты — `plans/owner_live_checks.md`, не блокер; device-чек-листы отменены)
Backlog (сжато): nano-gpt баланс (owner); master push доков (ahead); housekeeping asap8/mca-17c; F2-типы CFG-03; CFG-02B.2/.2.3/.8 live-хвост; P0B SCEN-B/LIVE-SCENARIOS; soul-main 17 RFL; CFG-02A 4 RFL; set_many/провенанс; «Характер»→«Личности»; ARCHITECTURE §2c; anti-flood; A/B-helper; fixture-дрейф; VIDEO not_configured; AMD.8.3; T-1764; W6-нит; l1_unavailable; L1 cold-start; 1.58МБ sendPhoto; win-glass 7 битых пинов; media_base env (owner); vision: retry-альфа, non-JSON на тяжёлых кадрах (free-модель); постген-бюджет 20с; CFG-03 ledger-debt 14 PENDING; ADD-EXP: L1-план/few-shot/модель, N1–N4, checksums, P7 не реализован, каркас-повторы; C7 humor/comic_strategy (позже); cleanup: Bot API не даёт историю → инкрементальные регистры + немедленное удаление (`cleanup_now.py`); SSH-паузы ≥90с; git-дисциплина: без reset/amend поверх чужих коммитов.
Progress scope: plans/progress_scope.json | fresh
Updated: 2026-10-20 12:22 local (2026-10-20 02:22 UTC)
