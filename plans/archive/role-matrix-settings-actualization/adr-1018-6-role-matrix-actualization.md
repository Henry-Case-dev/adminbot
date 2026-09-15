# ADR-1018-6 — Актуализация Матрицы ролей под фактическую структуру разделов мини-аппа

- **Статус:** Proposed
- **Дата:** 2026-09-15
- **Раунд:** 10.18, фича F6 `role-matrix-settings-actualization` (T-1750)
- **База:** HEAD `118a03c`.
- **AMEND:** уточняет RBAC-контракт раунда 10.5 (OD10/OD15, §26) — `param_permissions_list` получает аддитивные `nav/nav_title/nav_order`; форма прав (`view_roles`/`edit_roles`/`default`) не меняется. **Итерация 2 (после human-gate):** эталон = фактическая карта миниаппа подтверждён владельцем (UPD п.4); Δ каталога пересчитан с учётом отказа F2 от фича-флагов (UPD п.2) — см. D6.
- **Связано:** ADR-1018-1 (Δ каталога `REGISTRY +1`), ADR-1018-5 (F5 — флаг не вводится, Δ=0), ADR-1018-2 (F2 — **без** флагов, Δ=0), ADR-1018-3 (DDL, **не** каталог), ADR-1018-7 (F7 — Δ=0).

## Context

1. **ТЗ §5 неоднозначно** («согласно тому как они реально распределены в разделах миниапп»). За эталон принят **факт из кода** (`web/app.js`: `NAV_ITEMS`/`HUBS`/`MODULES`/`TABS`), а не догадка.
2. Матрица (`GET /api/access/param_permissions`, `web/api/access.py:319-360`) выдаёт `tab/tab_title` (19 config-вкладок), а фронт (`web/app.js:3617-3662`) группирует «плоско» по `TAB_SECTION_ORDER` — **без** фактической иерархии navbar→hub.
3. **Конкретный дрейф:** `CONFIG_TAB_TITLES[TAB_PERMSOC] = "Функции PERMsoc"` (`services/param_catalog.py:1770`), а фактическая подпись раздела в мини-аппе — `"PERMsoc"` (`web/app.js:145,261`).
4. **Каталог-инвариант** завязан жёстко: `TAB_RULES 19 / GROUPS 90 / mapped 88 / REGISTRY 435` (пин-тесты). F1 даёт санкционированный `REGISTRY +1`.
5. Фактическая структура (сверено): настройки несут **3** navbar-пункта из 6: `modules` (11 модулей), `ai` (7 карточек + persona special), `permsoc`; `access` параметров каталога не имеет.

## Decision

### D1. Единый источник nav-разметки — `services/param_catalog.py`
Ввести метаданные `NAV_TITLES = {modules:"Модули", ai:"ИИ", permsoc:"PERMsoc"}`, `NAV_ORDER = ("modules","ai","permsoc")`, `TAB_NAV` (все 19 tab_id → nav). Это Python-метаданные, **не** ParamSpec/GroupSpec → счётчики каталога **не растут**. Функция `tab_nav(tab_id) -> str | None`.

### D2. Аддитивные поля API
`param_permissions_list` добавляет `nav`, `nav_title`, `nav_order`. Форма прав/статус 403/409 не меняются; контракт аддитивен (R16).

### D3. Исправление подписи `permsoc`
`CONFIG_TAB_TITLES[TAB_PERMSOC]`: `"Функции PERMsoc"` → `"PERMsoc"` (паритет с `TABS[].label`/`NAV_ITEMS`). Ввести инвариант-тест «`CONFIG_TAB_TITLES` ↔ `web/app.js` TABS label» для 19 секций (предотвращает будущий дрейф).

### D4. Фронт: группировка по nav
`matrixSections` (`web/app.js:3617-3662`) строит nav-группы (`nav_order`) → секции (`TAB_SECTION_ORDER`) → группы (`group_order`) → параметры. `TAB_SECTION_ORDER` остаётся fallback внутри nav. Поиск/адаптив/аккордеоны — без регресса.

**B4-info(a) (итерация 4):** фактически фронт рендерит **4** nav-группы, а не 3. Три — из backend `NAV_ORDER` (`modules`/`ai`/`permsoc`), четвёртая — «Прочее» (`web/app.js:3653,3659`: `it.nav || 'other'`, fallback-заголовок `'Прочее'`) для **5** категоризированных content-параметров без config-вкладки (`tab=None`): `content.media_share_dir`, `content.media_public_base_url`, `content.info_how_it_works`, `content.intelligence_guide`, `content.no_key_reply` (`group_tab(group) is None`). Это осознанное поведение (content-параметры не привязаны к nav мини-аппа), а не «мёртвая» группа. JS-зеркало `NAV_GROUP_ORDER`/`NAV_GROUP_TITLES` (3 записи) закреплено parity-тестом с `NAV_ORDER`/`NAV_TITLES` (B4-4).

### D5. RBAC-политика — без новых секций
`known_sections()` не меняется; новых RBAC-секций/категорий не вводится; матрица — только global admin (как раньше). Недостижимые права исключаются проверкой «каждый tab_id имеет ≥1 группу». `#/access`-карточки (Матрица/Локальные админы/Роли) и special `#/ai/persona` — **не** per-param секции матрицы.

### D6. Санкционированный Δ каталога (свод раунда, итерация 3 — реализация)
`REGISTRY 435 → 436` (только F1 `BETTERSTACK_HOST` +1); `Settings 406`, `GROUPS 90`, `mapped 88`, `TAB_RULES`/`CONFIG_TAB_TITLES` 19 — **без изменений**; `categorized` (`param_permissions`) = **411**. **F5 Δ = 0** — фича-флаг `flags.metafact_penalty_enabled` **не вводится** (решение владельца UPD п.2 «без фича-флагов, базовая логика»; ADR-1018-5 D6 — обновлён). **F2 Δ = 0** (флаги исключены — UPD п.2); **F3 Δ = 0** (DDL `edges.fact_id` — схема); **F7 Δ = 0**. F6 Δ записей = 0 (только текст подписи + Python-метаданные). Итог раунда: **436 / 406 / 411 / 90 / 88 / 19**.

## Consequences

**Positive**
- Матрица отражает фактическую навигацию мини-аппа; устаревший «Функции PERMsoc» устранён.
- Настройки сгруппированы предсказуемо (Модули/ИИ/PERMsoc) — проще искать права.
- Единый источник разметки (backend ↔ frontend), инвариант-тест против дрейфа подписей.
- Δ каталога минимален (+1 только от F1).

**Negative**
- Дополнительные поля в ответе API (аддитивно — риск низкий).
- Небольшая правка фронта (`matrixSections`) — риск регресса UI (JS-гейты).
- Если продуктовая модель владельца не совпадает с фактом из кода — потребуется переделка (human-gate Q1).
- `access`-карточки/`persona` остаются вне матрицы (осознанно).

## Alternatives

- **A1. Оставить плоские 19 секций.** Отклонено: не решает ТЗ «как реально распределены».
- **A2. Полностью перестроить каталог под nav (nav как TAB_RULES-секции).** Отклонено: крупный Δ/ломает `TAB_RULES`-инвариант и RBAC-дерево; риск регресса.
- **A3. Хардкодить nav-маппинг во фронте.** Отклонено: два источника правды → дрейф (прецедент R10.6-1).
- **A4. Угадать «эталон» без кода.** Отклонено: ADR опирается на факт (`web/app.js`).
- **A5. Включить `#/access`/`persona` как секции матрицы.** Отклонено: нет per-param параметров; RBAC через действия.

## References

- `web/api/access.py:319-360`; `services/param_catalog.py:1751-1771,1773-1881,1883-1925`
- `web/app.js:18-180` (TABS), `:256-265` (NAV_ITEMS), `:270-318` (HUBS), `:323-357` (MODULES), `:188-194` (TAB_SECTION_ORDER), `:3617-3662` (matrixSections)
- `web/index.html:1263-1347` (UI матрицы)
- `tests/test_frontend_tab_mapping.py:44-85,176-257`
- ADR-1018-1 (Δ REGISTRY); §26 (RBAC OD10/OD15); §22 (RBAC v2/param_permissions)
- Задачи: T-1750 (ADR/spec), T-1751 (аудит), T-1752 (структура), T-1753 (RBAC/табы), T-1754 (пин-тесты), T-1755 (UI), T-1756 (гейты/свод Δ), T-1757 (@Reviewer/@PM).
