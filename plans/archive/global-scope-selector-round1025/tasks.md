# F3 — `global-scope-selector-round1025` (Эпик 1)

> **ТЗ:** `plans/current_task.md` §5, §14, §42, §43, §74. **Тип:** UI + state (web).
> **Приоритет:** P0. **Зависит от:** F1 (shell). **От F3 зависят:** F4, F7.
> **Задачи:** T-2574…T-2580 (ретро-нумерация Шага 8; продолжает пакет после F2 T-2529…T-2562 и hotfix5 T-2563…T-2573). **ADR:** `adr-1025-10-global-scope-selector.md` (ретро; Шаг 2 @Architect формально не оформлялся — см. waiver-пометку в ADR). **Spec:** `spec.md` (ретро, Шаг 8 @PM).
> **Статус:** ✅ **COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026).** Финальный код — **`4f31197`** (база `76a6c40`, ревью `fb49f29`, `4f31197`); `APP_VERSION` **2.58.6**; Δ DDL = 0, Δ каталога = 0. Шаг 7 @Architect Merge — `plans/ARCHITECTURE.md` §57.3. Папка — `plans/archive/global-scope-selector-round1025/`. **⏳ deploy (Шаг 9 @DevOps) и live-гейт владельца — НЕ выполнены.**

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
- ✅ Реализовано @Builder (21.09.2026). pytest **8148/0**, JS **+1 файл** (`tests/js/round1025_scope_selector_test.js` → `SCOPE-SELECTOR-OK`), `node --check` OK, `git diff --check` OK. Финальный код — `4f31197` (база `76a6c40`, ревью `fb49f29`, `4f31197`). `APP_VERSION` **2.58.6**. Δ DDL=0, Δ каталога=0.
- ✅ **@Reviewer — итерации 1 и 2 закрыты (Approved).** Итер.1: закрыты Critical (overflow кнопки возврата на mobile: подпись → «↪ Глобальное» + aria-label + CSS-снятие `shrink-0`), High (матрица с override-состоянием: §43-пометка + кнопка + overflow на 320/360/390; `hasUnsavedEdits` учитывает blockDrafts/API-ключ/ownKeyDraft/persona по baseline/dossier), Medium (§43 applied-state N/A; `configItemNotice` без шума на `per_chat=false`; источник в обоих шаблонах «Промптов»), Low (поиск всегда; local_admin видит возврат к глобальному). Итер.2 (`4f31197`): local_admin, очистка досье, стабильный CSS-класс.
- ✅ **@Scanner — Critical 0 / High 0.** Базовый — `plans/reports/round1025_f3_scanner_audit.md` (Medium **M-F3-1** «guard не видит `blockDrafts`» — **закрыт** ревью-фиксом `fb49f29`; Low L-F3-1…L-F3-4, Info I-F3-1…I-F3-3 — техдолг/не блокеры). **Пакетный (повторный)** — `plans/reports/round1025_package_scanner_audit.md` (диапазон `f2328fb..HEAD`, C0/H0, «к деплою ДА»). RBAC/DELETE-override, stale-epoch, секреты/R17 — чисто.
- ✅ **Шаг 7 @Architect Merge** — `plans/ARCHITECTURE.md` **§57.3** (F3 — постоянный селектор области §5), SUPERSEDE/AMEND-карта §57.4.
- ✅ **Архивация (Шаг 8 @PM, 22.09.2026)** — папка перенесена → `plans/archive/global-scope-selector-round1025/`; ретро-оформлены `spec.md` + **ADR-1025-10**.
- ⏳ **Осталось:** deploy (Шаг 9 @DevOps; `APP_VERSION` 2.58.6) и live-приёмка владельца (переключение области §5, возврат к глобальному, отсутствие stale-состояния, mobile-вёрстка).

## Зависимости / ступень
- Ступень web: F1 → F2 → **F3** → F4 → …
- Риск: перенос черновика/запоздавшие ответы меняют «не тот» scope (**High**); путаница «вернуть глобальное значение» vs заводской сброс (**Medium**).
