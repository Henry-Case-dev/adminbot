# VERIFY-LEDGER-P0-ACCEPT — вердикт (сверка леджера приёмки P0A)

Независимая проверка коммита `bf328c54` (`plans/features/p0-save-init-ux/requirements-map.json`, +222/−50). Read-only; этот коммит — только данный документ.

## 1. Состав/дифф — подтверждено
Дельта `bf328c54^ → bf328c54` (структурное сравнение всех строк): изменены ровно **16 строк**, статус сменился у всех 16:
- RFL→VERIFIED ×4: `P0A-PERSIST-APPLY`, `P0A-PERSIST-PAYLOADS`, `P0A-INIT-PROOF`, `P0A-INIT-DIAG`;
- PENDING→VERIFIED ×12: `P0A-ACCEPT-PERSIST`, `P0A-ACCEPT-PERSIST-EDGE`, `P0A-UX-{HIER,TECHJUNK,COMPACT,SAVE,SCOPE,KEEP}`, `P0A-OPS-{CONTINUE,REVIEW,NODUP,NOFAKE}`.
Строк добавлено/удалено: 0; иных изменённых строк нет — `P0A-OPS-REPORT`, `P0A-DONE`, `P0A-ACCEPT-UX`, `P0A-ACCEPT-INITIATIVE` остались PENDING, `P0A-PERSIST-SECTIONS`/`-TRUTH` — READY_FOR_LIVE (без правок). Top-level: `candidate_commit = deployed_commit = 3b02366e63022eb4c760892aa1bcb4f26516e789` (коммит существует, ancestor HEAD).

## 2. Привязки — подтверждено (24/24 пинов пересчитаны)
Каждая закрытая строка ссылается на СВОЙ кандидат: UX×6 → `01e1cc8d` (коммит «speech & character section rework [P0A-UX]»); `P0A-INIT-DIAG` → `2af51eb6` (коммит диагностика-фикс) + `f0bd29e2` (прод-дамп); PERSIST/INIT → `29a95173` (persist-фикс) / `f0bd29e2` (init-фикс); acceptance-JSON (`acceptance-25890`, `-recheck`, `-payload`, `-edges`, `-bc-read`, `journal-25890-phase1`) → `3b02366e`. Все 5 коммитов существуют.
Пины: **24 записи artifact_sha256 пересчитаны по файлам — 24/24 match, 0 missing** (все файлы трекнуты; acceptance-JSON: `failures=[]` для full/payload/edges/recheck, `mode`/`prod` заполнены).

## 3. Счётчики — пересчитаны
35 строк → **{VERIFIED 23, READY_FOR_LIVE 2, PENDING 10}** — совпадает. (6 строк-заголовков без req_id — `disposition=context`, они и дают разницу между 35 строками и `scoped=29` релизного гейта; в PENDING-10 входят 6 этих + `OPS-REPORT`, `ACCEPT-UX`, `ACCEPT-INITIATIVE`, `DONE`.)

## 4. Гейты (мой прогон verbatim)
- plan: `stage=plan inventory=22 manual=13 scoped=0 errors=0` **EXIT 0** (ожидание `22/13/0` — совпало).
- release `--candidate 3b02366e… --deployed-commit 3b02366e…`: `stage=release inventory=22 manual=13 scoped=29 errors=27` **EXIT 1**; 27 FAIL ровно такой структуры: **13** «no evidence bound to reviewed candidate» (строки ранних кандидатов: INIT×4, PERSIST-AUDIT/CAUSE/CENTRAL, UX×6 — проверено, у каждой evidence только от `f0bd29e2`/`29a95173`/`01e1cc8d`), **8** «live requirement lacks evidence» (INIT-CURSOR/STATUS + UX×6 — совпадает с `live_required=True`), **6** mandatory ≠ VERIFIED (`OPS-REPORT`, `PERSIST-SECTIONS`, `PERSIST-TRUTH`, `ACCEPT-UX`, `ACCEPT-INITIATIVE`, `DONE`). 13+8+6=27.
- Это **ожидаемое промежуточное** состояние, не подгонка: карта не выглядит «всё закрыто» (2 RFL + 10 PENDING, включая обязательные REPORT/DONE/ACCEPT-*), релиз-стадия честно EXIT 1.

## 5. Девиация леджера — подтверждена по контенту
UX-записи указывают `01e1cc8d`, НЕ `3b02366e` (все 6 строк; проверено по evidence каждой строки). У `P0A-INIT-DIAG` присутствует запись `2af51eb6` (мини-фикс диагностики). Т.е. упомянутая ошибка первого прохода исправлена до коммита — в дереве только корректные привязки.

## Замечания
Блокирующих нет. Примечание для будущего прохода: 13+8 FAIL'ов релиз-стадии снимутся привязкой эвиденса ранних кандидатов к reviewed/deployed candidate (или по правилам per-row binding), а 6 mandatory — закрытием REPORT/DONE/ACCEPT-*/RFL-строк; сейчас это честно отражено и не маскируется.

## Вердикт
**Approved.**
