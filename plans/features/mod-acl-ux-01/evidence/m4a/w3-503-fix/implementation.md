# W3/F-1 corrective — 503 `unavailable` vs disabled `off` (2.58.222 → fix)

**Строка:** `MAC-S10-16` (M4A), находка `F-1` из
`evidence/m4a/mac-s10-16.md` §3 и `w3-live-2026-11-20.md`.
**Роль:** Builder. Backend/DDL/флаги/промпты/карта/`workflow_state.md`/
`progress_scope.json` не менялись. Деплоя и bump версии нет.
**База:** `26b8880c` (`release/mod-acl-w2c-2.58.222`), блобы `web/app.js` =
`5c89437a…`, `web/index.html` = `ae5ac336…` — совпадают с живыми байтами
2.58.222 по `w3-live-2026-11-20.md` §2.
**Ветка:** `fix/mod-acl-w3-503`, worktree
`WorkspaceData/worktrees/…/mod-acl-ux-01-1e46be007668-fdbca75b`.

---

## 1. Что было не так (F-1)

HTTP 503 от журнала маппился в `'off'` — то же состояние, что у явно
выключенной функции (`parsed.off`, `available:false`, `enabled:false`).
`historyStateText('off')` печатал «журнал недоступен: функция выключена», а
`index.html` — «…функция выключена (503)». Причина 503 называлась неверно,
два обязательных класса пустоты были неразличимы.

## 2. Продуктовый diff

| Файл | Изменение |
|---|---|
| `web/app.js` | `HISTORY_STATES` + `'unavailable'`; в 5 catch-блоках `403 → denied`, `503 → unavailable` (`loadLessons`, `loadTemporalRuns`, `loadModuleRuns`, `loadDreamLog`, `loadNostalgiaLog`); `historyStateText`: отдельный текст `unavailable`; комментарий `_maybeExitHistory` (503 не уводит с журнала) |
| `web/index.html` | Отдельные ветки `data-overview-history-state="unavailable"` и `data-module-history-state="unavailable"`; из текстов `off` убран `(503)` |

Состояния и тексты после фикса:

| Причина | state | Текст (Обзор) | Текст (История) |
|---|---|---|---|
| 0 событий | `empty` | `Записей пока нет.` | `Записей пока нет.` |
| 403 | `denied` | `Журнал недоступен: нет доступа (403).` | `История недоступна: нет доступа к журналу (403).` |
| 503 | `unavailable` | `Журнал временно недоступен (503). Повторите попытку.` | `История временно недоступна (503). Повторите попытку.` |
| disabled | `off` | `Журнал недоступен: функция выключена.` | `История недоступна: функция выключена.` |
| ошибка/сеть | `error` | `История недоступна: ошибка загрузки.` | `История недоступна — не удалось загрузить журнал.` |

Поведение: 503 **не** удаляет pending-память вкладки и **не** уводит deep
link `#/modules/<slug>/history` на bare — панель остаётся с доступным ⟳
(`refreshHistory`). `403`/`empty`/`error` не изменены; `available:false` и
`enabled:false` остаются `off`; «0 событий» нигде не подменяет отказ.

Diff: `4 files changed, 276 insertions(+), 53 deletions(-)` (2 продукта,
2 теста). Кандидатные блобы — checkout/deployed bytes (CRLF): значения
сняты `Get-FileHash -Algorithm SHA256` / `sha256sum` с файлов worktree на
candidate tip, а не с `git show`; product-коммит `0a8571acc`, последующие
коммиты docs-only и `web/` не меняют:
`web/app.js` = `108f440f…`, `web/index.html` = `c3ceb1b5…`.

## 3. Тесты

- `tests/js/mod_acl_ux_m4a_w2b_history_test.js` (+137/−11):
  503 → `unavailable` для всех шести источников H-1; `off` без `503`;
  `denied`/`empty`/`error` без изменений; отдельный блок `(18)` —
  матрица пяти причин, статический контракт обеих поверхностей
  `index.html`, deep-link 503 (остаётся), pending-память на 503 (не
  удаляется), `stale` не является состоянием журнала (неизвестный код →
  `error`, не `ready`/`empty`).
- `tools/ui_mod_acl_m4_catalog_e2e.py` (+109/−32): режимы стаба названы
  честно (`server_503` — HTTP 503; `off` — `available:false`/`enabled:false`);
  503 → DOM `unavailable` + текст с 503; `off` → текст «выключена» без 503;
  403/empty сохранены; deep-link 503 остаётся на `/sleep/history` с
  `panelState=unavailable`; добавлена матрица `MAC-S10-16` (см. §5).

## 4. RED на базе 26b8880c (старый продукт, новые тесты)

Продукт временно возвращён к коммиту базы (`git checkout 26b8880c --
web/app.js web/index.html`); хеши совпали с deployed-блобами
(`5c89437a…`, `ae5ac336…`).

```
node tests/js/mod_acl_ux_m4a_w2b_history_test.js
AssertionError [ERR_ASSERTION]: 503 → unavailable
  actual: 'off'   expected: 'unavailable'   (rc=1)
```

E2E (`tools/ui_mod_acl_m4_catalog_e2e.py`, новые проверки) — **22 failures**,
exit 1; ключевые:

```
W2b 503: state 'off', text 'Журнал недоступен: функция выключена (503).'
W2b available:false: disabled назван 503
W2b 503: deep link увёл с журнала (#/modules/sleep, panel=False)
W2b 503: панель не показала unavailable/503
MAC-S10-16: состояния причин ['empty', 'denied', 'off', 'off']
MAC-S10-16: тексты причин не различаются (unavailable == off)
MAC-S10-16: 503 без честной причины
W2b B2 factcheck 503: state 'off'
W2b B3 summary 503: state 'off'
```

## 5. GREEN на кандидате

| Команда | Результат |
|---|---|
| `node tests/js/mod_acl_ux_m4a_w2b_history_test.js` | `…HISTORY-OK — 397 проверок`, rc=0 |
| 6× `node tests/js/mod_acl_ux_*.js` | 235 + 141 + 397 + 84 + 207 + 64 + 75 проверок, rc=0 |
| `node tests/js/app_methods_dup_keys_guard_test.js` | `duplicate-problems=0`, rc=0 (известный WARN `_prefersReducedMotion` ×2 — pre-existing в HEAD) |
| `pytest … test_mod_acl_ux_01_m4_catalog.py m3_module_routes.py m4_module_params.py m1_acl_false_403.py test_webapp_js_unit.py` | **83 passed**, 1 известный StarletteDeprecationWarning |
| `python tools/ui_mod_acl_m4_catalog_e2e.py` | `M4A-CATALOG-E2E OK`, **failures=0**, rc=0 |

Матрица `MAC-S10-16` из e2e-отчёта (`flows.w2b_s10_16_matrix`):

```json
{"empty":       {"state": "empty",       "text": "Записей пока нет."},
 "denied":      {"state": "denied",      "text": "Журнал недоступен: нет доступа (403)."},
 "unavailable": {"state": "unavailable", "text": "Журнал временно недоступен (503). Повторите попытку."},
 "off":         {"state": "off",         "text": "Журнал недоступен: функция выключена."},
 "stale":       {"state": "stale(409-banner)", "marker": "data-workspace-conflict",
                 "text": "Настройка изменилась в другом окне …"}}
```

Deep-link 503: `hash=#/modules/sleep/history`, `panel=true`,
`panelState=unavailable`, текст `История временно недоступна (503). Повторите
попытку.` — с журнала не выходим.

## 6. Ограничения и separate findings

1. **Локальный e2e ≠ живой TMA.** Прогон — Playwright/Chromium на
   локальном http-стабе, не production и не Telegram-клиент. Живой прогон
   на задеплоенном SHA остаётся W3-условием `MAC-S10-16`.
2. **stale в журнале не смоделирован.** Историческая поверхность не имеет
   состояния `stale`: устаревшие данные приходят строками и не помечаются
   как stale. Для матрицы использован существующий канонический stale-маркер
   design §4.6 (409): `[data-workspace-conflict]` + «Настройка изменилась в
   другом окне» (проверяется в e2e). Добавление stale-as-emptiness в журнал —
   **BACKLOG_ONLY**, отдельный контракт; в этот фикс не входит.
3. **F-2/F-3** из `mac-s10-16.md` (дословный копирайт §7.3, экран 404) не
   трогались — не входят в scope F-1.
4. Живой 403/503/stale/disabled на production не наблюдался (0 сессий и 0
   ошибок в W3); доказательство фикса — source + локальные RED/GREEN.

## 7. Воспроизведение

```bash
cd <worktree>            # fix/mod-acl-w3-503 от 26b8880c
node tests/js/mod_acl_ux_m4a_w2b_history_test.js
py -3.12 -m pytest -q -p no:cacheprovider \
  tests/test_mod_acl_ux_01_m4_catalog.py \
  tests/test_mod_acl_ux_01_m3_module_routes.py \
  tests/test_mod_acl_ux_01_m4_module_params.py \
  tests/test_mod_acl_ux_01_m1_acl_false_403.py tests/test_webapp_js_unit.py
MOD_ACL_M4A_SHOTS=<tmp> py -3.12 tools/ui_mod_acl_m4_catalog_e2e.py
```

RED: `git checkout 26b8880c -- web/app.js web/index.html`, повторить оба
прогона, затем `git restore --source=HEAD --staged --worktree web/app.js
web/index.html`.
**Конфигурация:** Node v24.16.0; Python 3.12.0; pytest 9.1.1; Playwright
1.62.0, Chromium 156.0.8078.4.
