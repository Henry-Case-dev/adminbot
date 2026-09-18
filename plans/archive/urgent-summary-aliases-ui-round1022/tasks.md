# Задачи: urgent-summary-aliases-ui-round1022

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 1 @PM · Тип: диагностика + frontend `web/**`
> **UPD3-дельта (Д-4):** данные в БД есть → фикс рендера JSON-объекта на фронте обязателен; restore запрещён.
> **ТЗ:** `plans/current_task.md`, «Проблема 2: Пропал словарь алиасов» (строки 180–185). Файл untracked, SSH-креды — не цитировать, не коммитить (R17/R18).
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a923310`.

## Цель
Вернуть рендер поля «Словарь алиасов имён» (`limits.summary_aliases`) в модалке настроек. Сначала доказать, что данные в БД **целы**, затем починить frontend-binding (object-value widget / stale JS-кэш) и проверить в TMA.

## ТЗ (кратко)
Поле пустое. ТЗ предлагает вариант «восстановить из бэкапа, если затёрты миграцией». Проверка показала: данные целы → проблема во frontend.

## Решение (Шаг 0)
**Что уже есть (данные — ЦЕЛЫ):**
- PG `bot_settings` (глобально) = JSON-объект из **38 ключей** (обновлён 04.09); per-chat override для `SUMMARY_ALIASES` нет.
- `GET /api/config` отдаёт все 38 ключей всем ролям; `SUMMARY_ALIASES` сериализуется с полем `widget` (`web/api/routes.py:365`).
- Каталог: `SUMMARY_ALIASES` — type `json`, widget `keyvalue` (`services/param_catalog.py:1163-1166`).
- Фронт: `web/app.js:3544-3551` (json с непустым `widget` **не** строкифаймится — остаётся объектом), `web/app.js:6331-6350` (`kv-editor.sync` читает только объект), `web/index.html:528-533` и `:794-798` (`v-else-if="item.widget === 'keyvalue'"` → `<kv-editor>`).

**Что новое:**
- READ-ONLY фиксация фактического shape ответа API (object/string) — без предположений.
- Диагноз binding-цепочки и живое воспроизведение рендера (headless Playwright — выполнен).
- Фикс binding/кэша + регресс-тест + приёмка в TMA.
- **Restore из бэкапа запрещён** — перезапишет свежие 38 ключей.

**Конфликт:**
- ТЗ требует «восстановить из резервной копии» — противоречит факту «данные целы»; действие отменяется, вместо него frontend-фикс.
- ТЗ упоминает «React/Vue-компонент» — в проекте React нет; есть Vue-рендер в `web/index.html` + `web/app.js`.

## Задачи
- [x] **T-2028** [@Builder] READ-ONLY shape: `type=json`, `widget=keyvalue` (`param_catalog.py:1164`), data целы (spec §0: PG 38 ключей, объект); root-cause H1 — строка-JSON из-за двойного кодирования. Локальная БД пуста (фикстуры).
- [x] **T-2029** [@Builder] Диагноз цепочки: catalog → `/api/config` (`routes.py`) → `app.js` loadConfig → `kv-editor.sync()` → `index.html` keyvalue-шаблон. Живое браузерное воспроизведение **выполнено** (headless Playwright присутствует в окружении и отрендерил пары; Reviewer подтвердил); поведение дополнительно покрыто node-тестом.
- [x] **T-2030** [@Builder] Фикс binding: `kv-editor.sync()` принимает object **или** строку-JSON (JSON.parse, 2 уровня); backend `_ensure_keyvalue_object` для `widget='keyvalue'` (defense-in-depth, WARNING + пустой объект при неудаче). Cache-bust подтверждён: `/web/app.js?v=APP_VERSION` + `Cache-Control: no-store` для `.js`.
- [x] **T-2031** [@Builder] Другие `json`/`list`-виджеты не затронуты (правка только в keyvalue-ветке + `kv-editor.sync`); полный pytest зелёный.
- [x] **T-2032** [@Builder] JS-UNIT `tests/js/round1022_aliases_test.js` → `ALIASES-UNIT-OK`: object/строка-JSON/double-encoded/пустой/не-JSON/массив/null; pytest-обёртка в `test_webapp_js_unit.py`.
- [x] **T-2033** [@Builder] `node --check web/app.js` OK, `ALIASES-UNIT-OK`, `VUE-MOUNT-OK`; **Δ каталога = 0** (`param_catalog.py` не менялся).
- [ ] **T-2034** [@DevOps] Деплой + ОСТАТОК приёмки: живой рендер пар в реальном TMA WebView (headless уже подтверждён на T-2029), cache bust; отчёт.

## Риски
- **R1 (Critical):** выполнить по ТЗ «restore из бэкапа» и затереть свежие данные → диагноз «данные целы» (38 ключей) доказан, restore **запрещён** (T-2028).
- **R2 (High):** фикс ломает остальные `json`/`list`-виджеты → регресс JS-UNIT + ручной чек виджетов (T-2031/T-2033).
- **R3 (Medium):** headless ≠ реальный TMA WebView (прецедент 10.21/WebView) → живая приёмка владельцем (⏸) как ОСТАТОК (T-2034); headless-рендер выполнен на T-2029.
- **R4 (Medium):** stale JS-кэш маскирует истинную причину → проверка served-файла + `no-store` (T-2030).
- **R5 (R17/R18):** секреты в скриншотах/отчётах → маскировать, не логировать.

## Зависимости / ступени вливания
- Зависит только от диагностики (T-2028/T-2029); стартует параллельно `F1 ∥ F2 ∥ F6`.
- Эксклюзивные по фиче файлы: `web/app.js` (KV-редактор, config-загрузка), `web/index.html` (`keyvalue`-шаблон).
- Общие с раундом `web/index.html`/`web/app.js` — **ступень F2 → F7** (help-ui-system2); правки F2 вливаются первыми.
- `services/param_catalog.py` — **read-only** (причина не в каталоге, Δ=0).
- Флага нет. **Δ каталога = 0**; откат — `git revert`.
