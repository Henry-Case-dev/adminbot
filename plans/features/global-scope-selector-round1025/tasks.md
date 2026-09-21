# F3 — `global-scope-selector-round1025` (Эпик 1)

> **ТЗ:** `plans/current_task.md` §5, §14, §42, §43, §74. **Тип:** UI + state (web).
> **Приоритет:** P0. **Зависит от:** F1 (shell). **От F3 зависят:** F4, F7.
> **Статус:** 🟦 Step 1 @PM — заготовка. **Детализация на Шаге 1 при старте фичи** (после F1; `spec.md`/ADR — Step 2 @Architect).

## Верхнеуровневые задачи (детализация при старте)
- [x] Селектор области — фундаментальный постоянно доступный элемент §5: тип области (Глобально/Чат/ЛС), название чата/ЛС, действие переключения; desktop — в закреплённом header, mobile — под заголовком страницы. (`web/index.html`, `web/static/app.css` @media <768, `web/app.js` scopeKind/scopeOptions)
- [x] Раскрытый селектор: поиск, Глобально, Чаты, Личные сообщения; полный `chat_id` — только в технических подробностях. (`web/index.html` `.scope-tech` details)
- [x] Источник значения §5: наследование — «Источник: глобальная настройка»; переопределение — «Источник: настройки чата». (`web/app.js` `configSourceLabel`/`configSourceTitle`, рендер в карточках)
- [x] Действие **«Вернуть глобальное значение»** — DELETE override (`/api/config/chat/{key}`), **не** заводской сброс. (`web/app.js` `resetChatOverride`, `web/api/routes.py` `delete_chat_param`)
- [x] Переключение области §5: guard несохранённых изменений (`hasUnsavedEdits` + `window.confirm`), отмена устаревших запросов (`scopeEpoch`/`_scopeGuard`), загрузка значений новой области, **stale-ответ не применяется**, черновик не переносится. (`web/app.js` `setActiveChat`/`loadConfig`)
- [x] При выбранном чате явно помечать, что серверные метрики относятся ко всему серверу §14. (`web/index.html` «Сервер»)
- [x] Тесты §74 (глобальное наследование, локальные значения не исчезают) и §42 (stale-ответы при быстрой смене чата). (`tests/js/round1025_scope_selector_test.js`, `tests/test_scope_selector_round1025.py`)

## §43 «Ожидает применения» — N/A (обоснование)
- **Статус: не применимо.** Конфигурация — read-through: `ConfigCache` (in-memory)
  + PG/`chat_params`; запись идёт через POST/`set_chat_params` и NOTIFY, а
  `GET /api/config` сразу отдаёт **эффективное** значение (`web/api/routes.py:458-465`:
  per_chat override → глобал → дефолт). Отдельного `applied-state`/асинхронного
  применения с задержкой сервер не имеет → показывать «Ожидает применения»
  нечего (иначе выдуманное состояние, запрещено §43 «без проверки серверной
  логики»). «Фактическое состояние» отображается эффективным `value` +
  пометкой `configItemNotice` при реальном расхождении. Трассируемость §43
  закрыта явным N/A (ревью Medium).

## Статус
- 🟩 Реализовано @Builder (21.09.2026). pytest **8148/0**, JS **+1 файл**, matrix **0**, `node --check` OK, `git diff --check` OK. `APP_VERSION` 2.58.6. Δ DDL=0, Δ каталога=0.
- 🟨 Итерация @Reviewer 1 (21.09.2026): закрыты Critical (overflow кнопки возврата на mobile: подпись → «↪ Глобальное» + aria-label + CSS-снятие `shrink-0`), High (матрица теперь с override-состоянием: §43-пометка + кнопка + overflow на 320/360/390; `hasUnsavedEdits` учитывает blockDrafts/API-ключ/ownKeyDraft/persona по baseline/dossier), Medium (§43 applied-state N/A; `configItemNotice` без шума на `per_chat=false`; источник в обоих шаблонах «Промптов»), Low (поиск всегда; local_admin видит возврат к глобальному). Ожидается @Reviewer итерация 2.
- ⏳ Осталось: @Reviewer (итерация 2 QA), @Scanner (аудит), live-приёмка/deploy (@DevOps), синк ARCHITECTURE/архивация (после приёмки).

## Зависимости / ступень
- Ступень web: F1 → F2 → **F3** → F4 → …
- Риск: перенос черновика/запоздавшие ответы меняют «не тот» scope (**High**); путаница «вернуть глобальное значение» vs заводской сброс (**Medium**).
