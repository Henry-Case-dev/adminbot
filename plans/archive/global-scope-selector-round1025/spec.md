# F3 `global-scope-selector-round1025` — локальная спецификация (ретро-оформление, Шаг 8 @PM)

> **Раунд:** 10.25, Эпик 1, Волна 1 (F2 ∥ F3). **Задачи:** T-2574…T-2580 (ретро-нумерация Шага 8; продолжает пакет после F2 T-2529…T-2562 и hotfix5 T-2563…T-2573).
> **Мастер-ТЗ:** `plans/current_task.md` §5 (селектор области), §14 (серверные метрики), §42 (stale-ответы), §43 (applied-state), §74 (тесты). Файл untracked — **не коммитить**, секреты не цитировать (R17/R18).
> **Тип:** UI + state (web). **Приоритет:** P0. **Зависит от:** F1 (`ia-shell-navigation-round1025`, ARCHIVED/DEPLOYED).
> **ADR:** `adr-1025-10-global-scope-selector.md`.
> **Статус:** ✅ COMPLETED + MERGED + ARCHIVED (Шаг 8 @PM, 22.09.2026). Финальный код — **`4f31197`** (база `76a6c40`, ревью `fb49f29`, `4f31197`). `APP_VERSION` **2.58.6**. Шаг 7 Merge — `plans/ARCHITECTURE.md` §57.3.
> **Baseline (после F2 + hotfix5):** пакет `f2328fb..4f31197`; Δ DDL = 0, Δ каталога = 0 (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418).
> **⚠️ Waiver (процессный техдолг):** Шаг 2 @Architect (формальное `spec.md` + ADR) при старте F3 **не оформлялся** — реализация шла параллельно с F2 в Волне 1, а доказательная база собрана @Builder/@Reviewer/@Scanner по факту. Настоящие `spec.md` и **ADR-1025-10** — **ретро-артефакты** Шага 8 @PM, восстановленные из кода, тестов и отчётов аудита. Зафиксировано как процессный техдолг (см. ADR-1025-10 «Waiver»).

## Инварианты
1. **Δ DDL = 0**; **Δ каталога = 0** (UI/state + серверный гейт существующего DELETE-эндпоинта; новых ключей нет).
2. **CSP/zero-build** (ADR-1016-2 / ADR-1024-13) — без новых библиотек/CDN.
3. Не ломать F0 save-слой (`persistItems`/`saveState`), F1 shell/safe-area/навигацию, hotfix-фиксы, Эпик 2. `web/app.js`/`index.html`/`app.css` — строго сериализованы (F1 → F2 → **F3**).
4. **Код + эталон + тест — одним коммитом** (project.md). R17/R18: секреты не печатать; бэкапы/теги/`stash@{0}` не удалять.

---

## 1. Контракт §5 — постоянный селектор области
- **Всегда доступный элемент** в закреплённом header (desktop) и под заголовком страницы (mobile, `@media <768`): тип области (**Глобально / Чат / ЛС**), название выбранного чата/ЛС, действие переключения. Реализация: `web/index.html` (разметка селектора), `web/static/app.css` (`.scope-wrap{order:5;flex-basis:100%}`; header имеет `flex-wrap`), `web/app.js` (`scopeKind`/`scopeOptions`).
- **Раскрытый список:** поиск, «Глобально», «Чаты», «Личные сообщения». **Полный `chat_id`** показывается **только** в технических подробностях — `<details class="scope-tech">` (не выносится в публичную часть UI).
- **§14:** при выбранном чате серверные метрики явно помечаются как относящиеся ко всему серверу (блок «Сервер» в `web/index.html`).

## 2. Источник значения §5 (наследование/переопределение)
- **Наследование** — карточка помечается «Источник: глобальная настройка»; **переопределение** — «Источник: настройки чата». Реализация: `web/app.js` `configSourceLabel`/`configSourceTitle`, рендер в карточках обоих шаблонов (в т.ч. «Промпты»).
- **`configItemNotice`** не создаёт шум на параметрах `per_chat=false` (формулировка не должна читаться как «правка не применится»; см. §57.5 Low L-F3-1).

## 3. §42 — переключение области и устойчивость к гонкам/stale
- **Guard несохранённых изменений.** `hasUnsavedEdits()` (`web/app.js:2481-2516`) покрывает: `stickyDirtyCount`/`dirtyItems`/`dirtyKeyItems`/`saving`, **`blockDrafts`** (вкладка «LLM-провайдеры»), API-ключ, `ownKeyDraft`, `personaDraft` (сравнение с baseline `personaMeta.values`), `dossierDraft` (сравнение с `dossierData.manual_traits`, включая очистку до `''`). При наличии правок — `window.confirm` **до** сброса черновиков (`setActiveChat` `:2521-2532`; `this.blockDrafts = {}` идёт на `:2572` только после подтверждения).
- **Отмена устаревших запросов.** `scopeEpoch++` (`web/app.js:2509`) + `_scopeGuard` (`:3379`) отбрасывают запоздавший `loadConfig` — stale-ответ **не применяется** (loading чужого scope не снимается).
- **Черновик не переносится:** при смене scope очищаются `blockDrafts`/`keyDrafts`/`personaDraft`/`configChatUpdatedAt`/`configItems`.
- **§42-тесты:** `tests/js/round1025_scope_selector_test.js` (поведенчески: `blockDrafts`/`ownKeyDraft`/`persona`/`dossier` → confirm; stale-guard) и `tests/test_scope_selector_round1025.py` (маркерный/структурный, часть покрытия — grep, см. §57.5 L-F3-2).

## 4. «Вернуть глобальное значение» = DELETE override, **НЕ** заводской сброс
- **Семантика.** Действие снимает **только per-chat переопределение** выбранного ключа и возвращает наследование глобального значения: `overrides.pop(key)` + merge `meta`; **не** сбрасывает параметр к заводскому дефолту.
- **Клиент:** `web/app.js` `resetChatOverride` (`:3333`) → `DELETE /api/config/chat/{key}` (`encodeURIComponent(item.key)`); кнопка показывается под условием паритета `!(isGlobalAdmin || isDmCtx() || isLocalAdminCtx())` (`web/index.html`, 8 мест).
- **Сервер/RBAC:** `web/api/routes.py:868-876`/`852-904` — `access_for(user.id, chat_id)` скоупит грант по чату (`services/roles.py:180-198`); группа — `is_global_admin or is_local_admin` (local-admin чата A не сбросит override чата B → 403); DM — только `is_dm_owner`. `404`, если override нет. Эскалации нет.
- **Секреты/R17:** лог `routes.py:902-903` пишет только `chat=,key=,by=` (без значений); ответ `{reset, chat_id}` отдаётся только своему пользователю.

## 5. §43 «Ожидает применения» — N/A (обоснование)
- **Статус: не применимо.** Конфигурация — **read-through**: `ConfigCache` (in-memory) + PG/`chat_params`; запись — POST/`set_chat_params` + NOTIFY; `GET /api/config` сразу отдаёт **эффективное** значение (`per_chat override → глобал → дефолт`; `web/api/routes.py:458-465`). Отдельного `applied-state`/асинхронного применения с задержкой сервер **не имеет** → показывать «Ожидает применения» нечего (иначе выдуманное состояние, запрещено §43 «без проверки серверной логики»). «Фактическое состояние» отображается эффективным `value` + пометкой `configItemNotice` при реальном расхождении. Трассируемость §43 закрыта **явным N/A** (ревью Medium).

## 6. Точки изменения (file:line)
| Область | Файлы |
|---|---|
| Селектор области §5 | `web/index.html` (header/`.scope-tech`/«Сервер»/кнопки возврата); `web/static/app.css` (`.scope-wrap`, mobile @media <768); `web/app.js` (`scopeKind`/`scopeOptions`/`configSourceLabel`/`configSourceTitle`) |
| Guard/epoch §42 | `web/app.js` (`hasUnsavedEdits` `:2481-2516`, `setActiveChat` `:2521-2532`, `scopeEpoch++` `:2509`, `_scopeGuard` `:3379`, очистка черновиков `:2572`); `web/static/app.css` (состояния) |
| DELETE override + RBAC | `web/app.js` (`resetChatOverride` `:3333`, `persistItems` `:5656-5690`); `web/api/routes.py` (`:852-904`, `:458-465`); `services/roles.py` (`:180-198`) |
| Тесты/харнесс | `tests/js/round1025_scope_selector_test.js`, `tests/test_scope_selector_round1025.py`, `tools/ui_round1025_matrix.py` |
| Версия | `config/settings.py` (`APP_VERSION` **2.58.6`) |

## 7. Верификация
- **§5:** селектор доступен на всех экранах; полный `chat_id` — только в `.scope-tech`; источник значения отображается корректно в обоих шаблонах.
- **§42:** guard срабатывает на все виды черновиков; stale-ответ при быстрой смене области не применяется; черновик не переносится.
- **DELETE override:** «Вернуть глобальное» возвращает наследование (не заводской сброс); RBAC (групповой local-admin/DM-owner) — без эскалации; 404 при отсутствии override.
- **§43 N/A:** обоснование зафиксировано; «Ожидаемое применение» не выдумывается.
- **Регресс:** pytest **8148/0** (целевые + JS-обёртка — 31 passed), JS `SCOPE-SELECTOR-OK`, `node --check web/app.js` OK, `git diff --check` exit 0; Δ DDL = 0, Δ каталога = 0; F0/F1/P0-fix/hotfix-медиа/hotfix2/hotfix3/hotfix4/Эпик 2 не задеты.
- **Matrix (ограничение):** `tools/ui_round1025_matrix.py` (10 вьюпортов, override-состояние 320/360/390) в среде Шага 8 **не воспроизведена** — `playwright` недоступен; заявленный «matrix 0» принят на доверии (структурно пробы присутствуют).

## 8. Риски и откат
| Риск | Ур. | Снятие |
|---|---|---|
| Перенос черновика/запоздавший ответ меняют «не тот» scope | High | §42 guard + `scopeEpoch`/`_scopeGuard` + очистка черновиков |
| Путаница «вернуть глобальное» vs заводской сброс | Medium | Семантика DELETE override + подпись/иконка; тест поведения |
| RBAC-эскалация при сбросе override | High | Серверный `access_for` (scope по чату) + JS-паритет условий кнопки |
| Устаревший F0-инвариант (`persistItems` снимает epoch после `await`) | Low | **Не этот пакет** — follow-up F0 (S/F0-окно, §57.5 L-F3-4) |

**Откат:** `git revert` коммитов F3 (`76a6c40`/`fb49f29`/`4f31197`) + возврат `APP_VERSION`. Бэкапы/теги/`stash@{0}` не удалять (R18).

## 9. Ссылки
- `plans/features/global-scope-selector-round1025/{tasks.md, adr-1025-10-global-scope-selector.md}` (после Шага 8 — `plans/archive/global-scope-selector-round1025/`).
- `plans/ARCHITECTURE.md` §57.3/§57.4; `plans/round1025-architecture.md`.
- Аудиты: `plans/reports/round1025_f3_scanner_audit.md` (базовый), `plans/reports/round1025_package_scanner_audit.md` (пакетный).
- ТЗ `plans/current_task.md` §5/§14/§42/§43/§74; ADR-1016-2 (CSP); ADR-1024-13 (доставка флагов).
