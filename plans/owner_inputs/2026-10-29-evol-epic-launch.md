# OI-2026-10-29-EVOL-LAUNCH — Epic EVOL launch order

- **Origin:** root chat prompt, 2026-10-29 (single message).
- **Kind:** new_task (epic launch).
- **Linked authoritative document:** `plans/current_task.md` = `EVOL_Adminbot_Epic_FINAL_2026-10-29.md`, APPROVED FOR EXECUTION.
- **Document sha256:** `54454df5c0d9aadca64b6106bccbcce0188b4f27b4723e80f8b75d445b24b745` (908 lines, UTF-8; read in full by orchestrator at intake).
- **Scope:** EVOL-001 … EVOL-045 (45 mandatory tasks incl. EVOL-014 initiative memes), end-to-end acceptance, staged release.

## Verbatim launch order (owner, 2026-10-29)

> ЗАПУСКАЕМ EPIC `EVOL` НА ПОЛНЫЙ ОБЪЁМ.
>
> Я поместил окончательный документ `EVOL_Adminbot_Epic_FINAL_2026-10-29.md` целиком в `plans/current_task.md` (или указал в нём точный путь к этому файлу). Это утверждённое ТЗ, а не просьба обсудить или переписать его. Прочитай **весь** `current_task` и полный текст EVOL, включая 45 задач `EVOL-001`–`EVOL-045`, сквозную приёмку, запреты и зависимости. Предыдущие черновики v0.x не являются источником правды. Не обрезай задачи и не сокращай scope из-за размера документа. Не создавай `openspec`.
>
> **Режим работы:** автономный непрерывный цикл существующего multi-agent workflow с Архитектором, исполнителями и строгим Reviewer. Включить в работу **все** задачи, распределить по зависимостям и вести до интегрированного DONE и допустимого деплоя. Не завершать цикл после первого фикса, первой PR, успешных тестов или деплоя. Уже активные задачи и незавершённый переезд VPS корректно завершить/учесть, не ломая production. Никаких ритуальных остановок, кругов согласований и фиктивных human gates. Обращаться ко мне только при настоящем непреодолимом архитектурном/продуктовом выборе с конкретными альтернативами. Отсутствие возможности владельца провести живую проверку НЕ блокирует инженерный DONE.
>
> Порядок: 1. Аудит и план. 2. Исправления backend и стандартов. 3. Полный UI/UX. 4. Новая функция EVOL-014. 5. Проверка и релиз.
>
> **Требование к завершению:** все `EVOL-001`–`EVOL-045` должны иметь результат `DONE`/`FAILED`/`NOT_OBSERVED` с доказательствами; `NOT_OBSERVED` допустим только для внешних/боевых событий, которые нельзя безопасно воспроизвести, но инженерные проверки должны быть выполнены. Ошибки — исправлять, не переименовывать и не скрывать. Продолжай текущий workflow до устранения реальных незакрытых инженерных пунктов; не объявляй завершение при частично реализованном epic.
>
> **Отчётность:** короткий человеческий отчёт на русском с фактическим текущим временем, ASCII-прогрессбаром, количеством выполнено/всего (из 45 задач), понятными названиями функций, кто над чем работает, что на очереди, что реально заблокировано. Без бесконечных технических простыней, ложных 100% и просьб проверять живой Telegram ради закрытия задачи.

## Reconciliation notes

- VPS migration: COMPLETE/VERIFIED (final-vps-decommission VERIFIED, old VPS decommissioned) — precondition «подтвердить завершение предыдущего переезда» satisfied.
- Previous embed-defect family (`_LAST_EMBED NameError`) already in backlog — absorbed into EVOL-010 (P0 candidate).
- Stale historical BUILDING rows in progress_scope (soul-1, asap8-v6.3, cfg-01-07, asap-speech-arch, asap2/3, p0-factcheck-*) to be reconciled by PM against EVOL scope absorption, not silently dropped.
