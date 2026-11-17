# 2.58.213 — ограничения и что осталось

## Границы релиза
- В релизе только **W2b B2**: вкладка «История» для `mod_factcheck`
  (`factcheck.temporal.runs`, существующий `GET /api/factcheck/temporal/runs`)
  и `mod_experience` (`memory.lessons`, конверт `{enabled,state,count}`),
  состояния, deep link, «Обзор» без дублей, фильтр и детали прогона по
  `run_id`; плюс B1 из 2.58.212 без изменений поведения.
- **B3 не входит**: `oversight:summary.window` / `oversight:random.uses`,
  `loadModuleRuns`, ссылки на `#/oversight?view=runs&run_id=`.
  `MAC-S5-TAB-01`, `MAC-S5-TAB-06`, `MAC-S5-EMPTY-01`, `MAC-AC-07`
  закрываются только после B3; ни одна строка не переводится в VERIFIED.
- **W2c не входит**: NAV-01/LAY-01/WF-01 (IA, сетка 8/12+4/12, wireframe,
  полировка «Расширенных»).
- **W3 не входит**: живые 403/503/stale/disabled/permissions на production
  (`MAC-S10-16`).
- **M4B/M4C не входят**: «Статус», «Роли и права», `#/access/roles`.
- Backend/ACL/storage/composer/prompt registry не менялись; новых API, таблиц,
  полей и миграций нет.

## Browser Use / CDP
Browser Use недоступен в этой сессии:
- `Test-NetConnection 127.0.0.1:9222` → **False**;
- `Test-NetConnection 127.0.0.1:19988` → **False**.

Визуальная проверка выполнена только Playwright на локальном стенде
(5 viewport, 83 flows, 20 B2, failures=0). Живой TMA и Browser Use **не
заявляются**; после появления CDP/relay нужен тот же стенд, скриншоты —
отдельным evidence.

## LOW (non-blocking, presentation/UX)
1. **`memory.lessons` не помечен `adminOnly` в presentation-map.** У
   не-владельца нет отдельной role-подсказки «Опыта»: вкладка не появляется
   (loader не вызывается из `_ensureModuleData`), а 403 «Памяти» даёт
   честный `denied`. Доступа это не расширяет (API — global admin), это
   полировка подсказки.
2. **Чатовая область уроков сохраняет `?chat_id=…` без `limit=50`**
   (сервер default 100), поэтому История чата может показать до 100 строк;
   глобальная область запрашивает `limit=50`. Адрес сохранён ради
   существующего контракта «Памяти» (round1039), не ошибка.
3. **`factual_verdict: null`.** Фильтр падает обратно на `temporal_status`,
   но подпись опции берётся из verdict-словаря → «неизвестно». Строка
   остаётся честной, подпись обобщённая.
4. **Detail без `run_id` — no-op** без объяснения: кнопка «Детали» не
   рендерится, если id нет; программный вызов молча ничего не делает.

## BACKLOG (вне 2.58.213)
1. **`tools/ui_asap8_w3_modules_e2e.py` (MCA-20).** Ожидания «проверок пока
   нет» при 403 и блока `data-factcheck-temporal` на bare
   `#/modules/factcheck` устарели уже после W2a (bare = settings), а H-3
   заменяет fail-open текст на честный `denied`. Обновить в W2c/W3; в этом
   релизе инструмент не менялся.
2. **503 re-fetch (pre-existing).** Неуспешный ответ источника не
   кэшируется как `off`; повторный вход после 30-с кэш-окна снова
   запрашивает. Это поведение существующего лоадера, нового поллера нет;
   кандидат на отдельный BACKLOG (кэшировать отказ или нет — продуктовое
   решение).

## Поведенческие границы B2
- Холодный старт фактчека допускает **2** запроса: bootstrap глобальной
  области до разрешения чата + повтор для фактической области (путь H-4/F2);
  после разрешения scope — 0, вкладка и простой не добавляют запросов
  (e2e: 2→2→2; experience 1→1).
- Вкладка `history` видна только при `ready && rows > 0`; пустой/403/503/
  `available:false`/`enabled:false` дают компактный блок/честную причину в
  Обзоре, без «0 событий».
- `history` никогда не выбирается дефолтом; pending не удаляет запомненный
  выбор, удаление — только при `empty/denied/off`.
- Журнал — client-side/in-memory представление существующих read-API;
  серверных данных релиз не добавляет.
- Deep link при `empty/denied/off` однократно уводит на bare-адрес; это
  UX-переход, а не изменение ACL.
- 320 px: общий каталог/сетка проверяются в 5 viewport, но целевые
  computed-размеры Истории фактчека/опыта зафиксированы на **1280×800 и
  390×844**; отдельно 320 px для этих строк не измерялся.

## Pre-existing (не относится к 2.58.213)
- **33** падения в полном `tests/test_webapp_*.py` при **1455 passed** — тот
  же полный список воспроизведён на `e070c229`; новых падений нет.
- **4** pytest epic-scope guard: `test_tool_coordinator_round1026.py` ×2,
  `test_unified_image_request_round1026.py` ×2 (устаревшие canon/forbidden-path
  baseline; 856 passed в bumped-pins batch).
- **4** node-файла: `asap6_wave2_ux_tabs`, `evol_cog_scene`,
  `round1025_ia_routing`, `ur_ui_settings` — те же падения на базе.

## Проверки после выката (агентами, не владельцем)
- effective-state на проде: версия 2.58.213, manifest identity, `/healthz`,
  schema 47 / pending=[], сохранность настроек.
- Живой TMA: вкладка/панель Истории фактчека и «Опыта», detail по run_id,
  конверт уроков, deep link, фильтр, смена чата. Локальный Playwright-прогон
  **не заменяет** живой TMA.
