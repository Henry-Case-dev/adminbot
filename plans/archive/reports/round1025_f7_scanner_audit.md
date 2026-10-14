# Round 10.25 F7 `permsoc-local-space-round1025` — Scanner-аудит (Step 6 @Scanner, T-2957) — **Итерация 3 (финал)** — SCANNED

- **База:** HEAD `551847d` (== `origin/master`); правки **НЕ закоммичены** (worktree). Тег `pre-round1025-f7`, `.env.bak.round1025-f7`, `stash@{0}` целы. @Reviewer итер.3 — **Approved**.
- **Итерации:** 1 — H-F7-1/M-F7-2 (+L-F7-3/L-F7-5); 2 — закрыты; 3 — фикс **H-F7-7** (+L-F7-8/L-F7-9). **Вердикт: к деплою — ДА.** Critical 0 / High 0 / Medium 0 / Low 3 (follow-up, не блокеры) / Info 3.

## Таблица severity

| ID | Severity | Область | Статус |
|---|---|---|---|
| H-F7-7 | High → **0** | Тип ID-списков Оли | **CLOSED** |
| H-F7-1 | High → **0** | Подгруппы §62/§64/§66 | **CLOSED** (итер.2) |
| M-F7-2 | Medium → **0** | Списки ID Оли — list | **CLOSED** (итер.2) |
| L-F7-3 / L-F7-5 / L-F7-8 / L-F7-9 | Low | Матрица no-chat / «4→6» / «Лимит N» / ссылка ADR | **CLOSED** |
| L-F7S-1 / L-F7-4 / L-F7-6 | Low | Follow-up / pre-existing | OPEN (ноты, не блокеры) |
| I-F7S-1/2/3 | Info | Процесс/тесты/док | — |

## H-F7-7 CLOSED — доказательство (независимо, @Scanner)

- **Причина:** `list-editor.save` ранее коэрцировал всё в `String`; сервер (`filters/olya_video.py:101-108`) сравнивает `origin.chat.id`/`sender_user.id` (**int**) через `in hot.get(...)` → строки не находились, SaveAsBot молча не срабатывал.
- **Фикс:** `web/app.js:11207-11216` — `_numericList()` (true только для `PERMSOC_LIST_WIDGET_KEYS`) + `toStoredValue(s)` (`/^-?\d+$/` + `Number.isSafeInteger` → `Number`, иначе строка); `save()` конвертит через `toStoredValue`.
- **Проверка:** JS-раннер H-F7-7: round-trip `[-100123,523131145]` → на сервер числа (`typeof number`; `includes(-100123)===true`, `includes('-100123')===false`); mixed `['523131145','not-an-id',' 42 ','']` → `[523131145,'not-an-id',42]`; **фразы Костика `['привет','42']` остаются строками** (регресс исключён). `tests/test_permsoc_f7_round1025.py::test_olya_saveasbot_list_type_comparison` — эмуляция реального `OlyaVideoFilter`: stored-int → `is_saveasbot=True`, stored-str → `False`.
- **Новых проблем не вносит:** числовой каст строго за ID-ключами Оли (`_numericList` gate); прочие `list`/json-ключи (Костик, `danger_words`, `reactions.*`) не затронуты; `sync()` отдаёт строки для ввода (round-trip-стабильность); overflow-защита `Number.isSafeInteger` → не-безопасные числа остаются строками.

## Закрытие остального (итер.2/3, воспроизведено)

- **H-F7-1 ✔** — `permsocRenderItems`+`__subheader`+`.permsoc-subgroup`; матрица `permsoc_chat.subgroups=24`, titles совпадают.
- **M-F7-2 ✔** — `PERMSOC_LIST_WIDGET_KEYS`+`_normalizeConfigItems`(+`widget='list'`)+`listEditorProps variant='ids'`; матрица `olyaListStructured={hasListBtn:True,hasTextarea:False}` (тип — H-F7-7).
- **L-F7-3 ✔** — `_route_nochat`: `ownerCount=0, hasNoChatBanner=True, hasMaster=False, subgroups=[]`.
- **L-F7-5 ✔** — `test_all_six_owner_blocks_always_render`; **L-F7-8 ✔** — `index.html:4595` «Лимит {{maxRows}} {{variant==='ids'?'ID':'фраз'}}»; **L-F7-9 ✔** — `evidence.md` §5 уточнён (D1 — клиентский; серверный denylist = follow-up L-F7S-1).

## RBAC/security, guard, D3

| Проверка | Итог |
|---|---|
| Guard «PERMsoc не в global» цел | ✔ `PERMSOC_LOCAL_KEYS` в `persistItems`/`saveConfigItem`; `failed{reason:'permsoc-global'}` + toast (JS A2/A3) |
| Серверные гейты D3 целы | ✔ `services/{permsoc,feature_gates,goodmorning_scheduler}.py` дифф неизменен (11/9/57); `gates.py` `startswith("permsoc")`, `who_can_toggle='global'`, PUT/DM → 403 |
| H-F7-7 и серверное сравнение | ✔ int-список совпадает с `origin.*.id`; строковый legacy — задокументированная регрессия тестом |
| XSS/R17 | ✔ только `{{ }}`/`:attr`; новых `v-html` нет; логи/секреты чисты; ID не секрет |
| R18 | ✔ тег `pre-round1025-f7`, `.env.bak.round1025-f7`, `stash@{0}` |

## Инварианты

- **Δ DDL = 0** ✔; **Δ каталога = 0** ✔ — `services/param_catalog.py` не тронут (459/98/96/21/418; оверрайд тип/виджет — клиентский).
- **CSP `script-src 'self'`/zero-build** ✔; **APP_VERSION 2.58.15** ✔; **маркер-тесты усилены, не ослаблены** ✔.
- **§57–§65/F0/F1/F3/F4/F5/F6/ADR-1024-24** не тронуты; фоновые задачи (default ON = baseline) не сломаны; **логика** ✔ — guard не молчит, OFF блока не сбрасывает дочерние, fail-closed OFF, partition 60+5=65; **гигиена** ✔ — `.env`/`current_task.md`/zip/скриншотов нет, `tools/_ui_*` — gitignore.

## Независимые прогоны @Scanner (итер.3)

- `node --check web/app.js` — OK; все `tests/js/*.js` — **38/38 OK**; `tests/test_webapp_js_unit.py` зелёный; `py -3 -m pytest -q` → **8374 passed, 0 failed** (120 c); `git diff --check` → exit 0 (только LF/CRLF).
- `tools/ui_round1025_matrix.py` → **failures: 0** (10 вьюпортов; `#/permsoc` chat/global + no-chat).

## Handoff

**RESULT: SCANNED @Orchestrator** — H-F7-7 закрыт (round-trip типа + эмуляция фильтра) и не вносит новых проблем; H-F7-1/M-F7-2/L-F7-3/L-F7-5/L-F7-8/L-F7-9 закрыты; новых Critical/High/Medium нет; к деплою — ДА. Открыто (ноты, не блокеры): L-F7S-1 (серверный denylist PERMsoc в global-пути), L-F7-4 (`dead_page_post_on_join` gate), L-F7-6 (DM-мастер, pre-existing). Живой WebView/TMA — PENDING OWNER (T-2961). Отчёт: `plans/reports/round1025_f7_scanner_audit.md`.
