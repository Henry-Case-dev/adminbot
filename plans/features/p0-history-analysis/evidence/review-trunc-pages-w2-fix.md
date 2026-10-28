# Ревью фикса TRUNC-PAGES (волна 2)

Вердикт: **Approved**

Поведение среза на кандидате доказано. Карта ещё не привязана: `APPROVED_BEHAVIOR / MAP_SYNC_REQUIRED`. Это книжная работа PM, не возврат Builder.

Кандидат: `6b705293b331db143c9f16679180915b088afdcc` (HEAD). Предок отклонённого среза: `2aaa2ee57a5f7c7a7b51d4ee09f6f767c836ce2a`. Волна 1: `9da314e7`. Карта: `plans/features/p0-history-analysis/requirements-map.json` (`candidate_commit` всё ещё `9da314e7`). Контракт правки: прошлое ревью `evidence/review-trunc-pages-w2.md` (блокер H14) и source-2026-10-29.md, строки 156, 177, 201, проверки H7 и H14.

Сводка привязки: verified 9 / failed 0 / unverified 0 / N/A 0. Семь строк слайса TRUNC-PAGES и две поглощённые строки DEPTH, которые прошлое ревью отклонило. Статусы ниже — по поведению. В JSON они ещё PENDING.

Линзы: лично, без листовых субагентов. Один механизм: курсор и учёт дыры. Визуального изменения нет, Playwright и Browser Use не применялись. Внешние источники не нужны.

## Проверка заявлений фикса

| Заявление | Статус | Наблюдение |
|---|---|---|
| Курсор v2, 13 полей, тот же hmac-sha256 ключ процесса, TTL 360 | VERIFIED | Живая первая страница: префикс `v2.`, payload из 13 полей `v2`, chat, anchor_ts, anchor_id, oldest_ts, oldest_id, requested, available, processed, after_ts, after_id, exp, sample_id. Текста сообщений в payload нет. `exp - now` = 359.8 с. `TOOL_CHAIN_TIMEOUT_SECONDS` и `_history_cursor_ttl()` = 360. |
| v1 и кривые счётчики v2 — fail-closed, без чтения по ужатому окну | VERIFIED | Подписанный текущим ключом v1 (11 полей) через dispatch с depth=50 и query: ровно `ОШИБКА get_recent_history: unknown_cursor`, без головы и без тел. Подписанный v2 с processed больше available, processed меньше 0, available меньше 1: decode и dispatch дают тот же код. Лог: `reason=unknown_cursor`, без курсора и без текста. Удаление якоря по-прежнему `anchor_missing`, не тихая страница. |
| Дыра между страницами названа, выжившие отданы, инвариант счёта | VERIFIED | Сценарий (a): 85 сообщений, после страницы удалены id 41-84, якорь 85 жив. Продолжение: available=85, processed=41, remaining=44, has_next=0, incomplete=1, reason=tail_missing, в теле только выживший. Сценарий (b): 100, удалены id 50-90. Финал: processed=59, remaining=41, сумма 100, incomplete=1, tail_missing; m60 нет, m49/m91/m100 есть. Середина обхода (200, удалены 50-150): вторая страница has_next=1 и incomplete=1, финал processed=99 remaining=101. Отката на depth=50 нет: cursor вместе с depth=50 и query не открывает новую выборку. |
| H7 не сломан | VERIFIED | 30 сообщений, depth=2000: requested=2000, available=30, processed=30, remaining=0, has_next=0, incomplete=0, reason пустой, курсора нет. Тест `test_available_short_of_requested` зелёный и в диффе не менялся. |

Обычная цепочка без удалений (85): 40+40+5, на каждой странице processed+remaining=available, incomplete=0, 85 уникальных строк, без перекрытий. Та же дыра при общем timestamp=1000: тот же честный счёт и доставка m85. Инвариант держится на проверенных цепочках с удалениями и без них.

## Привязка строк

| Строка | Статус | Доказательство |
|---|---|---|
| REQ-HA-P02-NO-3500-REPLACE | VERIFIED | Дифф фикса обрезку не возвращает. Наследие H9/H10 в прогоне 81 зелёное. Прежнее доказательство на предке остаётся в силе: предок — прямой ancestor. |
| REQ-HA-TRUNC-NO-SLICE | VERIFIED | В диффе нет среза text[:N] и нет `_truncate` на пути истории. |
| REQ-HA-CONTRACT-REWORK | VERIFIED | Дыра больше не объявляется полной выборкой. Голова несёт захваченный available и причину. |
| REQ-HA-TRUNC-REMOVE | VERIFIED | Старый срез 3500 не восстановлен. |
| REQ-HA-PAGES-CONTINUATION | VERIFIED | Курсор самодостаточный (v2), тела между вызовами не хранятся. Цепочка 85 сходится. |
| REQ-HA-PAGE-WHOLE-MESSAGES | VERIFIED | Страницы целых строк. Стык без перекрытий подтверждён тестом и зондом 85 уникальных строк. Равный timestamp не ломает доставку выжившего. |
| REQ-HA-NO-SUMMARIZE-SUBSTITUTE | VERIFIED | Дифф суммаризатор не добавляет. |
| REQ-HA-PAGES-NOT-FULL | VERIFIED | После дыры страница не приходит как полная: incomplete=1, при живом хвосте длиннее страницы has_next остаётся 1. |
| REQ-HA-INCOMPLETENESS-REPORTING | VERIFIED | Хвост, исчезнувший между страницами, получает incomplete=1 и reason=tail_missing. Выжившие строки отдаются. H7 без удаления остаётся incomplete=0. |

## Гейт

`requirements_gate.py check --stage review --slice TRUNC-PAGES --candidate 6b705293 --repo .` вернул FAIL, 8 ошибок. Все канцелярские, до привязки: candidate mismatch (карта на `9da314e7`) и 7 строк TRUNC-PAGES в PENDING. Это не дефект поведения. Две строки DEPTH в фильтр слайса не входят; их статус выше получен зондом.

## Регрессия

`pytest tests/test_history_pages.py tests/test_p0_history_depth_round1029.py tests/test_recent_history_tool_round1015.py -q -o timeout=600` — 81 passed, 0 failed, 6.41 с. Из них `test_history_pages.py` — 35. Падений нет.

Дифф `2aaa2ee5..6b705293`: только `services/tool_router.py` и `tests/test_history_pages.py`. Схема, reader БД и путь B не тронуты.

RED на предке: worktree на `2aaa2ee5`, тот же сценарий (a). Наблюдение: available ужался до 41, processed=41, remaining=0, has_next=0, incomplete=0, reason пустой. Честный контракт на предке не выполняется. Worktree после проверки снят.

## Неблокирующее

- Тест `test_inconsistent_counter_cursor_fail_closed` подписывает v2-payload, но внешний префикс всегда `v1.`. Отказ случается раньше проверки счётчиков. Поведение с настоящим префиксом `v2.` проверено зондом и корректно. Тест дырявый как страж, контракт не ломает.
- `architecture-contract.md` раздел 1 всё ещё описывает payload v1 без available/processed и не перечисляет `tail_missing`. Рантайм следует обязательной правке прошлого ревью, не старому эскизу payload. Документ стоит поправить отдельно, поведение не блокирует.
- Ветка гонки между COUNT и чтением страницы может поставить `anchor_missing`, если COUNT ещё видел полный хвост, а чтение уже пустое. Без гонки ветка недостижима: пустой хвост ловится сравнением и получает `tail_missing`. На обычном retention не проявляется.
- Прежние заметки первого ревью (пол evidence 300 не вмещает сырой cursor; `ctx.history_sample` с чужим chat_id) этим фиксом не закрыты и не ухудшены. В активный срез не входят.

## Следующий шаг

Orchestrator не возвращает срез Builder. PM привязывает карту к `6b705293` и переводит девять строк выше в VERIFIED со ссылкой на этот файл. Родитель эпика не DONE: волны SEGMENTS и дальше открыты.