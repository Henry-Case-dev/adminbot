# Задачи: aliases-render-real-fix-round1024

> **Раунд 10.24 (UPD2)** · Приоритет **P1** · Шаг 1 @PM · Тип: frontend `web/**` (data binding), backend читает как есть
> **ТЗ:** `plans/current_task.md`, UPD2, п.8 (строки 209–213). Файл untracked; секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`.
> **Конфликт:** **RE-OPEN/AMEND** F2 10.22 («Починили рендер JSON-словаря» — подтверждено ложным отчётом).

## Цель
Реально починить рендер поля `Словарь алиасов имён` (вкладка «ИИ» → «Имена»). Если данные в БД есть — поле обязано отрисовать текущий JSON при загрузке. Прошлый фикс признан ложным.

## Что уже есть (координаты)
- Каталог: `services/param_catalog.py:1262-1266` (`SUMMARY_ALIASES`, type `json`, widget `keyvalue`, group `limits_user_aliases`).
- Backend: `web/api/routes.py:219-239, 380-383` (чтение/запись значений конфига).
- Frontend: `web/app.js:6863-6886` (обработка widget `keyvalue`), шаблон `web/index.html:707-712`.
- Ранее (10.22) диагностика: global `bot_settings` = объект ключей; per-chat override нет; `GET /api/config` отдаёт всем ролям. Подозрение — рендер object-value виджета `keyvalue` / stale JS-кэш / TMA.

## Задачи
- [ ] **T-2264** [@Architect] ADR: контракт виджета `keyvalue` для **object-value** (`{"id":"Имя"}`) — источник данных, форма, синхронизация; исключить повтор «ложного» закрытия (обязательный живой чек).
- [x] **T-2265** [@Builder] Live-диагностика (read-only): реализована CLI `manage.py diag aliases` (только SELECT; global `bot_settings` + per-chat override `chat_profiles.chat_params` + API-форма `value/global_value/widget/chat_source`; R17 — форма/число ключей). Прогон на прод-БД — @DevOps (env доступа нет).
- [x] **T-2266** [@Builder] Frontend: реальный data-binding KV-редактора — `watch(item,{deep:true,immediate:true})` + `:key="item.key+':'+configVersion"` (re-mount при reload); исправлен unqualified `iconGlyph('delete')` → `root.iconGlyph` (TypeError рендера при наличии пар — вторая фактическая причина пустоты).
- [x] **T-2267** [@Builder] Per-chat override: показывается эффективное значение (chat override иначе global) + бейдж источника `sourceLabel` («значение чата»/«глобально»).
- [x] **T-2268** [@Builder] Тесты: реальный render-тест `tests/js/round1024_aliases_render_test.js` (монтирование + DOM, deep-watch, reload/:key, массив пар, Empty State, индикатор, kill-switch); `tests/test_aliases_render_round1024.py` (API-контракт, override, ui_flags, read-only diag); JS-гейт `node --check web/app.js`.
- [ ] **T-2269** [@Reviewer] Ревью: воспроизведён исходный баг, фикс подтверждён тестом + скриншотом/логами; нет restore из бэкапа (запрещён — перезапишет свежие данные).
- [ ] **T-2270** [@DevOps] Деплой (cache-bust) + **живая приёмка в TMA** владельцем: поле показывает текущий JSON; отчёт с фактическим значением (обезличенным). Также: прогон `python manage.py diag aliases --chat-id <target>` на прод-БД и выгрузка фактов в отчёт.

## Критерии приёмки
- При наличии данных поле показывает JSON сразу при загрузке, без ручных действий.
- Фикс подтверждён живьём в TMA (не только тестом).
- Данные не перезаписываются/не восстанавливаются из бэкапа.
- JS-гейт зелёный.

## Риски
- **R1 (High):** повторный ложный отчёт → обязательный live-чек (T-2270) как критерий приёмки.
- **R2 (Medium):** per-chat override маскирует глобальные данные → показать эффективное значение (T-2267).
- **R3 (Medium):** stale JS-кэш в TMA → cache-bust при деплое.
- **R4 (Low):** формат object-value может различаться (строка JSON vs объект) → нормализация на фронте.
- **R5 (R17/R18):** ID/имена — персональные данные, в отчёт обезличенно.

## Зависимости / ступени
- Зависит от: 10.22-диагностики (данные целы).
- Ступень `web/index.html`/`web/app.js`: F3 → F5 → F6 → F11 → F4 → **F10** (последняя, чтобы не конфликтовать).
- Feature flag: `ALIASES_KEYSVALUE_RENDER_ENABLED` (env-only `ClassVar`, **default ON**).
- Откат: флаг OFF / `git revert`; Δ DDL = 0, Δ каталога = 0.
