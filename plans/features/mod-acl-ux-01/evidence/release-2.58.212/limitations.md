# 2.58.212 — ограничения и что осталось

## Границы релиза
- В релизе только **W2b B1**: вкладка «История» для `mod_sleep` и
  `mod_nostalgia` на существующих журналах `memory.dream.log` /
  `memory.nostalgia.log`, состояния, deep link, компактный Обзор, фильтр и
  восстановление после смены чата.
- **B2 не входит**: `factcheck.temporal.runs`, `memory.lessons` и
  `mod_experience → loadLessons()`.
- **B3 не входит**: `oversight:summary.window` / `oversight:random.uses`,
  `loadModuleRuns`, ссылки на `#/oversight?view=runs&run_id=`.
  `MAC-S5-TAB-01/02/03/04/05/07` остаются открытыми до B3.
- **W2c не входит**: NAV-01/LAY-01/WF-01 (IA, сетка 8/12+4/12, wireframe,
  полировка «Расширенных»).
- **W3 не входит**: живые 403/503/stale/disabled/permissions на production
  (`MAC-S10-16`); строка не переводится в VERIFIED.
- Backend/ACL/storage/composer/prompt registry не менялись; новых API, таблиц,
  полей и миграций нет.

## Browser Use / CDP
Browser Use недоступен в этой сессии:
- `Test-NetConnection 127.0.0.1:9222` → **False**;
- `Test-NetConnection 127.0.0.1:19988` → **False**.

Визуальная проверка выполнена только Playwright на локальном стенде
(5 viewport, 63 flows, failures=0). Живой TMA и Browser Use **не заявляются**;
после появления CDP/relay нужен тот же стенд, скриншоты — отдельным evidence.

## 320 px
Playwright-прогон включает viewport 320×568 для общего каталога/W2a-сетки, но
целевые computed-assertions W2b (`12px` строка, `14px` заголовок, `12px`
фильтр) зафиксированы на **1280×800 и 390×844**; отдельно для 320 px размеры
строки Истории не измерялись и здесь не заявляются.

## Pre-existing (не относится к 2.58.212)
- **33** падения в полном `tests/test_webapp_*.py` при **1455 passed** — тот же
  набор, что на `18ced316` / `fae3eab2`; новых падений нет. Два F1 guard-теста
  W11/W12, наоборот, исправлены этим релизом.
- **4** pytest epic-scope guard: `test_tool_coordinator_round1026.py` ×2,
  `test_unified_image_request_round1026.py` ×2 (устаревшие canon/forbidden-path
  baseline; 856 passed в bumped-pins batch).
- **4** node-файла: `asap6_wave2_ux_tabs`, `evol_cog_scene`,
  `round1025_ia_routing`, `ur_ui_settings` — те же падения на базе.

## Поведенческие границы B1
- Вкладка `history` видна только при `ready && rows > 0`; пустой/403/503 журнал
  даёт компактный блок «Последние события» либо честную причину в Обзоре.
- `history` никогда не выбирается дефолтом; pending не удаляет запомненный
  выбор, удаление — только при `empty/denied/off`.
- Журнал — client-side/in-memory представление существующих read-API; серверных
  данных релиз не добавляет.
- Deep link при `empty/denied/off` однократно уводит на bare-адрес; это
  UX-переход, а не изменение ACL.

## Проверки после выката (агентами, не владельцем)
- effective-state на проде: версия 2.58.212, manifest identity, `/healthz`,
  schema 47 / pending=[], сохранность настроек.
- Живой TMA: вкладка/панель Истории, deep link, фильтр, смена чата, computed
  размеры. Локальный Playwright-прогон **не заменяет** живой TMA.
