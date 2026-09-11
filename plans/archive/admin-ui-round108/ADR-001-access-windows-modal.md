# ADR-001 — «Доступы»: подразделы как route-driven модальные окна

- **Статус:** принято (@Architect, раунд 10.8)
- **Контекст:** подразделы «Матрица ролей», «Локальные админы», «Администраторы» сейчас живут
  в одном экране как аккордеон (`web/index.html:1577-1783`), что владелец считает неверным.
  Требование: каждый открывается в **отдельном окне**; «Администраторы» → «Роли»;
  «Мой доступ» и «Telegram ID админа» — вне окон. Уже есть hash-роуты
  `#/access/roles|local|admins`, `ROUTE_PARENT` → `#/access`, нативный BackButton и
  модальный паттерн `modal-backdrop`/`openModuleWindow`.

## Рассмотренные варианты

1. **Отдельные hash-экраны** (без одновременного рендера). Плюс: «настоящие» экраны.
   Минус: нужно дублировать chrome/back, ломает hub-модель и `sec-*`-якоря; больше риска.
2. **Stateful-модалки** без изменения hash (как `openModuleWindow`). Плюс: просто.
   Минус: deep-link и BackButton пришлось бы реализовывать вручную; существующие роуты
   становятся мёртвыми.
3. **Route-driven модалки** (выбрано): состояние окна — производная от hash.

## Решение (вариант 3)

- `data.accessOpen` = id открытого окна (`null|'roles'|'local'|'admins'`), устанавливается в
  `applyRoute` из `#/access/<id>`; для любого другого маршрута — `null`.
- `openAccessWindow(id)` → `navigateTo('#/access/'+id)`; `closeAccessWindow()` → `navigateTo('#/access')`.
- Разметка: три `modal-backdrop` (паттерн `openModuleWindow`, `index.html:1248-1260`) с
  сохранением id `sec-roles`, `sec-matrix`, `sec-local`, `sec-admins`.
- BackButton/in-app `←`: без изменений — `ROUTE_PARENT` уже ведёт `#/access/*` → `#/access`.
- RBAC: `canViewTab('access')` + существующие `v-if="isGlobalAdmin"`/`disabled` внутри контента.
- «Мой доступ», «Промпты», «Telegram ID админа» — вне окон, всегда доступны.
- «Администраторы» (hub-card, заголовок окна, внутренний заголовок) → «Роли».

## Последствия

- `setAccess` удаляется; `isAccessOpen` сохраняется. Тесты `acc-head`/`role="tabpanel"` обновляются.
- Deep-link и BackButton работают бесплатно (hash — источник истины).
- Feature flag/kill-switch не вводится: единый статический бандл TMA, откат — `git revert`.

## Отклонённые альтернативы

- Вариант 1 и 2 отклонены как более рискованные/требующие ручной реализации deep-link/back.
- Kill-switch `ui.accessSeparateWindows` отклонён (неприменим к статическому TMA-бандлу).
