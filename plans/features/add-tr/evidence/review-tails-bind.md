# Review REV-TAILS-BIND — tails-binding ledger commits (2026-10-22)

Вердикт: **Needs Fixes** (1 блокер, механический).

Кандидат: f88b64ce (add-tr), 14118f40 (p0-vision), 8bb0dbe5 (win-glass); база b67df7bc; HEAD = 8bb0dbe5.

## Реверификация (машинная + контентная)
- add-tr: 13 изменённых строк == prep-REUSE (8 additional_requirements + 5 items); 25/25 evidence-хэшей OK; контент: mid 1165613, vision_disabled, deadline_exceeded, mids 1165620/22, 939495B, failures:[] (S5/S6/S10/S13/REG-DELTA); current_task ADD-TR.0–5 на месте, append-only.
- p0v: 4 строки == prep-REUSE; P0V-PIPE-CONTEXT не тронут (RFL); 8/8 хэшей по существующим путям; review-vision-core Approved; mock-matrix честно мок.
- wg: 7 REUSE + WG-P0-03 (деклар. хэш-рефреш); 23/24 хэшей OK; контент: 200/2.58.85, TRACKED_MOD/95526863, no_window_geometry, fullscreen-policy [SAME], corr -26, FS 12×PASS checks=166/166 failures=0.
- REAL_WORK (12 add-tr, 1 p0v: P0V-PIPE-CONTEXT) / CONTEXT / owner_optional — не тронуты (построчное JSON-сравнение both arrays).

## Гейты (воспроизведены)
- plan ×3 EXIT 0 (32/37, 24/14, 14/18 = prep).
- wg review WG-VERIFY/WG-WIN/WG-ANDROID ×3 EXIT 0.
- wg release rc=1, errors=1 ровно «deployed≠candidate».
- add-tr review rc=1: REG errors=5 (ровно свои 5), VERIFY errors=20 (=11+9, incl. REAL_WORK чужого лейна) — как заявлено.
- p0v review rc=1 errors=2 — ровно 2 чужих исторических (P0V-SYMPTOMS, P0V-DOD); свои 4 строки чисты.

## Release-gate residual: СТРУКТУРНЫЙ, не блокер
Задеплоенные байты тождественны кандидату семантически: git diff 95526863..3a178c6c по web/static/glass-refraction.js/fullscreen-policy.js/glass-probe.js пуст; 7/7 хэшей отданных артефактов в deploy-run. Прецедент пер-волновых биндингов (add-tr 948c2004→3a178c6c, accept-95). Residual честно записан в reason/prep/commit; rc=1 не замаскирован. Финальное закрытие — через REL-258107.

## Сноска add-tr deployed_commit=3a178c6c: КОРЕКТНА
direct_chat.py/mca_vision.py — 0 коммитов 113f3a62..3a178c6c; tool_router.py — ровно 4 чужие волны (83c7abae, c849dbf4, f1e31d27, 8cd2ca14, CFG-06/07).

## type=production + MAN-WG-04: КОРЕКТНО
type=production проставлен ровно на release-артефакты 4 live-строк (WG-WIN-02/03/05, WG-ANDROID-02, каталог evidence/release/ = задеплоенные байты). AGENTS.md HEAD sha=62d638cc (PET_PROJECT-поправки из 176abdde; diff b67df7bc..HEAD=0); review-wg.md HEAD sha=e1f5cbe3; append-only доказана (блоб 94cdfc03 — байт-префикс HEAD, +16035 B R2–R4), §6 сохранён.

## Блокер (1)
- [BLOCKER→RELATED_SMALL] p0-vision-universal/requirements-map.json: 6 artifact_path не резолвятся (лишний сегмент evidence/) в VERIFIED-строках P0V-TEST-MATRIX, P0V-TEST-MOCKS, P0V-WF-STANDARD: `evidence/evidence/fix-core/mock-matrix-2026-10-19.md` (×2), `evidence/evidence/fix-core/green-2026-10-19.txt` (×1), `evidence/review-vision-core.md`, `evidence/review-vision-ui.md`, `evidence/review-accept-95.md`. Реальные файлы существуют (fix-core/…, review-… в корне фичи), sha256 всех шести совпадают с заявленными — чисто механическая опечатка пути, не фабрикация.
- Минимальная коррекция: исправить 6 путей в одном файле. Речек: повторный hash-probe 6 записей + `check --map p0-vision-universal --stage plan` EXIT 0.

## Неблокирующее
- WG-P0-05 несёт review-wg.md @sha 94cdfc03 (валиден на его candidate 0ca661fe) — консистентно, но рядом с обновлённой MAN-WG-04 записью; ок.
- Обновлённые записи MAN-WG-04 несут candidate 0ca661fe с хэшами HEAD-байтов — задокументированный drift-refresh (observation честно объясняет); предложить в дальнем бэклоге единую конвенцию.

## Честность
Ни одной VERIFIED без реального evidence (кроме 6 битых путей выше — содержимое реально). owner_optional (WG-OBS-*, P0V-OWNER-VISUAL, M-ADTR-GRID-DEVICE-OBS) не сконвертированы ни в одну сторону; live-строки VERIFIED только на инженерных половинах с production-артефактами, «полный успех на нативном клиенте» нигде не заявлен.

Незакрепленное чужое не тронуто; режим read-only соблюдён (этот файл — единственный новый).
