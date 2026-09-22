# F7 `permsoc-local-space-round1025` — review.md (Step 5 @Reviewer, T-2956) — итерация 3

**Feature-ID:** permsoc-local-space-round1025
**Status: Approved** (проверено в дереве; код не правился; правки ревьюером не вносились)
**База:** HEAD `551847d` + незакоммиченные изменения. Тег `pre-round1025-f7` → `551847d` (annotated). `APP_VERSION 2.58.15`.

## Checks performed (воспроизведено, итерация 3)
- `node --check web/app.js` = 0; все `tests/js/*.js` — **38/38 OK**; F7-юнит `F7-PERMSOC-LOCAL-UNIT-OK`.
- `pytest -q` → **8374 passed / 0 failed**; `git diff --check` exit 0 (LF/CRLF warning).
- `tools/ui_round1025_matrix.py` → **failures: 0**; raw: chat-scope 6 блоков + **24 подгруппы**; Оля `{hasListBtn:true, hasTextarea:false}`; no-chat (390×844) `ownerCount=0, banner=true, subs=0, master=false`.
- Δ каталога = **0** (459/98/96/21/418; `param_catalog.py` вне диффа). Δ DDL = **0** (миграции/схема не тронуты). R17/R18 (current_task.md ignore/не изменён, `stash@{0}` цел).
- Независимая репродукция H-F7-7: `list-editor.save` → Оля `[-100123,523131145]` (`number,number`), mixed `[523131145,"not-an-id",42]`, Костик `["Привет","Как дела"]` (`string,string`); Python `-100123 in [-100123] === True`, `in ['-100123'] === False`.
- Тест-эмуляция реального `OlyaVideoFilter` (`tests/test_permsoc_f7_round1025.py::test_olya_saveasbot_list_type_comparison`): stored-int → `is_saveasbot=True`; stored-str → `False`.

## Статус находок
| Находка | Статус | Доказательство |
|---|---|---|
| **H-F7-7** (ID-списки Оли строками → SaveAsBot мимо) | **CLOSED** | `list-editor._numericList()/toStoredValue(s)`: чисто-числовые (`/^-?\d+$/` + `Number.isSafeInteger`) → `Number`, нечисловые → строка; `save` через `toStoredValue`; JS round-trip-тест (`includes(-100123)===true`, `includes('-100123')===false`); pytest-эмуляция фильтра int/str; мой прогон подтвердил числа |
| **H-F7-1** подгруппы §62/§64/§66 | **CLOSED** | `permsocRenderItems` + `div.permsoc-subgroup`; матрица 24 подгруппы; JS partition-тест |
| **M-F7-2** списки ID Оли структурированы | **CLOSED** | `PERMSOC_LIST_WIDGET_KEYS` → `widget='list'`, `list-editor variant='ids'`; матрица `hasListBtn=true/hasTextarea=false`; тип сохранён (H-F7-7) |
| **L-F7-3** no-chat E2E | **CLOSED** | Матрица: `/api/access/chats=[]` → `ownerCount=0, banner=true` |
| **L-F7-5** «4→6» | **CLOSED** | `test_all_six_owner_blocks_always_render` |
| **L-F7-8** «Лимит N фраз» в ID-варианте | **CLOSED** | `index.html:4595` → `{{ maxRows }} {{ variant === 'ids' ? 'ID' : 'фраз' }}` |
| **L-F7-9** неверная ссылка на ADR | **CLOSED** | `evidence.md` §5 уточнён: D1 — клиентский guard; серверный denylist = follow-up L-F7S-1 |
| **L-F7-4** (`dead_page_post_on_join` не гейтится) | follow-up (корректно, не блокер) | `evidence.md` §3; Scanner audit |
| **L-F7S-1** (серверный global-путь не отклоняет PERMsoc) | follow-up (корректно, не блокер) | `evidence.md` §5; Scanner audit |
| **L-F7-6** (DM-мастер у global admin → 403) | pre-existing (не F7) | Code-inspection |

## Новые находки
Нет блокирующих. Косметика/наблюдения отсутствуют; новых проблем фикс не внёс (изменения аддитивные, тесты и матрица — 0 failures).

## Неблокирующий долг
- **L-F7-4 / L-F7S-1 / L-F7-6** — открыты как follow-up (см. выше); раскрыты честно, не скрытые дефекты.

## Unavailable checks
- Живой Telegram WebView/TMA (канонический `chat_id`, переключение чата, OFF блока → фон прекращён) — **PENDING OWNER VERIFICATION** (T-2961); Chromium ≠ WebView.
- Интеграция фильтров в хендлерах — код-инспекция + юнит `PermsocBlockGate`; полный прогон хендлеров не выполнялся.

**Итог:** все блокирующие находки итераций 1–2 закрыты и подтверждены воспроизводимыми проверками; инварианты (Δ DDL/каталога = 0, CSP/zero-build, R17/R18) соблюдены; заявленное в `evidence.md` подтверждено. Вердикт — **Approved** (риск release только на живом WebView — PENDING OWNER VERIFICATION).
