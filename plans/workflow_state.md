# Workflow State

Task: Полная очередь `plans/current_task.md` — SOUL-1 + ASAP8 v6.3 + инцидент + fullscreen + CFG-01…07 + P0×3 + ADD-TR + ADD-EXP (реестр `plans/progress_scope.json`: 9 задач; 1 VERIFIED)
Task source: current_task.md (+ VERBATIM-снапшоты `plans/features/*/source-*.md`)
Status: in_progress
Primary phase: build
Active features: add-exp/soul (UNIFIED-CORE, кандидат 2.58.98) · cfg (04/05 DONE; 06→07A/B/C ждут) · p0-vision (RFL-хвосты)
Progress sources: карты soul-main/amend, cfg, win-glass, p0 A+B, p0-vision, add-tr, add-exp; реестр (9 задач; 1 VERIFIED)

Продакшн: **2.58.97 @ `99f5672c`** (T0 2026-10-19 19:13:31Z; PID 3791730; NRestarts=0; SKIPS=0; дельта 5/5). Рубежи отката: 96=`95d11472`, 95=`113f3a62`, 94=`9072347b`. Правило владельца 20.10: живые тесты в чате — сам владелец (`plans/owner_live_checks.md`, не блокер); агенты — только технические проверки, случайно отправленное удалять сразу.

Active lanes:
- UNIFIED-CORE-FINISH | Builder | writer | add-exp/soul | bg:ses_ea99634d2ffeLVrLPGqAcHSvfu | чек-лист `plans/features/add-exp/unified-core-spec.md` п.13 route-coverage (Factcheck/Summary/tool/подписи/checkup/fallback) + п.14 C14-вычистить + п.16 тесты + п.17 дизайн + п.18 payload-traces; пункты 1–11/C5 + F3-директивы уже в дереве (uncommitted); БЕЗ коммита
- CLEANUP-ALL-CHATS | Builder | DONE | closure | bg:ses_ea99634d2ffdcbLaBtkGmOrn0S | реестровый residual 0 подтверждён живой ownership-пробой 221 mid (0 owned; 194 уже удалены; 27 не бота); 14 органических сообщений бота намеренно сохранены; 7 защищённых не тронуты; evidence `plans/features/cfg/evidence/release-25897/cleanup/closure-all-chats.{json,md}`; инцидент 21:11Z (9 органических удалены ошибочно) → OQ-13 в `plans/owner_questions.md`, restore не применён
- DELETED-AUTHORSHIP-AUDIT | Builder | DONE | closure | bg:ses_ea97fa783ffeWz1PCiSJ0YWBuc | вердикт: пользовательские сообщения НЕ удалялись (0 из 175 удалённых mid; все — бот; пересечение с 278 пользовательскими mid пусто); «27 not_owned» живы; метод 21:11Z пользовательские затронуть не мог; evidence authorship-audit.{md,json}; SSH 0 коннектов; OQ-14 VERIFIED

Join barriers:
- Кандидат 2.58.98 = F3-директивы (в дереве) + UNIFIED-CORE → Reviewer → release-гейт → push (рубеж `release/fix-2.58.97`=`99f5672c`) → deploy → owner live-checks. Один райтер на factcheck-файлы: CFG-06 стартует только после закрытия UNIFIED-CORE (скоуп-оверлап).
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
1. UNIFIED-CORE-FINISH → ревью кандидата 2.58.98 → release-гейт → push/deploy → owner live-checks.
2. После закрытия UNIFIED-CORE: CFG-06 → 07A/B/C → CFG-FINAL.
3. OQ-13 закрыт владельцем (бот-сообщения НЕ восстанавливать); OQ-14 — аудит авторства удалённых сообщений идёт; CFG-06 после UNIFIED-CORE.

Review: pending (кандидат 2.58.98 после UNIFIED-CORE-FINISH)
Deployment: verified (2.58.97 @ `99f5672c`; следующий кандидат 2.58.98 — pending)
Human gate: none (0 блокирующих; живые пункты — `plans/owner_live_checks.md`, не блокер; device-чек-листы отменены)
Backlog (сжато): nano-gpt баланс (owner); master push доков (ahead); housekeeping asap8/mca-17c; F2-типы CFG-03; CFG-02B.2/.2.3/.8 live-хвост; P0B SCEN-B/LIVE-SCENARIOS; soul-main 17 RFL; CFG-02A 4 RFL; set_many/провенанс; «Характер»→«Личности»; ARCHITECTURE §2c; anti-flood; A/B-helper; fixture-дрейф; VIDEO not_configured; AMD.8.3; T-1764; W6-нит; l1_unavailable; L1 cold-start; 1.58МБ sendPhoto; win-glass 7 битых пинов; media_base env (owner); vision: retry-альфа, non-JSON на тяжёлых кадрах (free-модель); постген-бюджет 20с; CFG-03 ledger-debt 14 PENDING; ADD-EXP: L1-план/few-shot/модель, N1–N4, checksums, P7 не реализован, каркас-повторы; C7 humor/comic_strategy (позже); cleanup: Bot API не даёт историю → инкрементальные регистры + немедленное удаление (`cleanup_now.py`); SSH-паузы ≥90с; git-дисциплина: без reset/amend поверх чужих коммитов.
Progress scope: plans/progress_scope.json | fresh
Updated: 2026-10-20 11:33 local (2026-10-20 01:33 UTC)
