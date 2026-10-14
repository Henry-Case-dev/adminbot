# round1026 S1 — UI/E2E отчёт (T-3138/T-3151)

> Фича: `summary-filter-round1026` (Эпик 2, S1). Роль: @Builder. Дата: 2026-09-23.
> Решение UI: ADR-1026-1 **D6** (§87/§85).

## 1. Маршрут и витрина

- **Маршрут:** Модули → «Сводки чатов» (`mod_summary`) → вкладка **«Подготовка сообщений»** (`prep`).
- Группы каталога `flags_summary_filter` («Предфильтрация») и
  `limits_summary_filter` («Предфильтрация: тонкая настройка») добавлены в
  `TAB_RULES[TAB_MOD_SUMMARY]` (`services/param_catalog.py`) и в витрину
  `TABS[mod_summary].sources` (`web/app.js`) — зеркало, **Δ каталога JS = 0**.
- `workspaceGroupTab` направляет обе группы на `prep`; `currentTabGroups`
  рендерит их существующей generic-сеткой; `workspaceCoverage` учитывает `prep`
  (инвариант покрытия §9.3 сохранён — `missing = []`).
- `web/index.html`: placeholder Эпика 2 (`data-workspace-stage`) оставлен для
  `clusterizer`/`writer`; `prep` теперь несёт реальные параметры.
- Главный тумблер «Алгоритмическая предфильтрация» — **default ON** (§107);
  сохранение — существующим F0 `persistItems`/`saveConfigItem` (одна серверная
  мутация, per-chat через `X-Chat-Id`), без новых API.

## 2. Что проверено (статика, автоматически)

| Проверка | Инструмент | Результат |
|---|---|---|
| `node --check web/app.js` | node | OK |
| JS-набор (в т.ч. `round1025_f5_workspace_route_test.js`, `..._prompts_single_source_test.js`) | node (42 файла) | **42/42** |
| Python-инварианты витрины (`test_webapp_f5_round1025`, `test_frontend_tab_mapping`, `test_ia_inventory_round1025`) | pytest | passed |
| Полный pytest | pytest | **8494/0** |

Покрыто: состав вкладки `mod_summary`, покрытие групп workspace, единство
источника промптов, доступность вкладок. **Не дублировались** тесты F0/F5.

## 3. Что НЕ выполнено (ограничение)

- **Браузерный E2E (Playwright/сетевые перехваты)** не запускался: в задаче
  Builder нет поднятого стенда/браузера. Требуемые T-3151 «перехваты сети +
  прогон» — на этапе приёмки (@Reviewer/@DevOps, T-3151/T-3157).
- per-chat изоляция и reload-сохранение подтверждены существующим контуром F0
  (одна мутация, 409-контракт) и тестами каталога; живой сценарий — на приёмке.

## 4. Файлы

- `services/param_catalog.py` (2 группы, 8 записей, TAB_RULES)
- `web/app.js` (`TABS[mod_summary].sources`, `workspaceGroupTab`, `currentTabGroups`, `workspaceCoverage`)
- `web/index.html` (placeholder prep → только clusterizer/writer)
