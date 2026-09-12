# Spec F6 — `cognition-ekg-logs-bugfix-round1013` (EKG-«Сердцебиение» + багфикс «Логи»)

> Статус: **✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; спека Step 2 @Architect, 13.09.2026). База: HEAD `ce25dc7`.
> ТЗ: `plans/current_task.md` §8 + §9. Tasks: T-1459…T-1464. Frontend + контракт `/api/status/logs`. P2.
> Пересечение с F5 (страница «Статус») — исполнять последовательно.

## 0. Цель

Убрать бесполезный линейный график аптайма → живой SVG-EKG, привязанный к
здоровью сервера. Починить рассинхрон селектора/списка логов; добавить
`ERROR+WARNING`; дефолт фильтра при открытии — `ERROR+WARNING`.

## 1. Объём

### In scope
- Удаление линейного аптайм-графика (`renderUptimeChart`/`uptimeCanvas`/state).
- SVG-EKG + CSS-анимация, скорость/цвет ↔ Load/CPU/RAM; `prefers-reduced-motion`.
- Фикс бага `logLevel='INFO'` vs фактический `ALL` (единый источник истины).
- Новый серверный тег `ERROR+WARNING` + дефолт при первичном открытии.

### Out of scope
- Удаление полей `uptime` из `/api/status` (обратная совместимость — §3.3).
- Новые каталог-параметры (пороги — фронт-константы).

## 2. Схема данных

Ноль DDL. `/api/status/logs` читает `services/log_ring.py` (in-memory ring).

## 3. Изменения контрактов

### 3.1. `GET /api/status/logs?level=` (F6-Q1 — РЕШЕНО: серверный тег)
Новое допустимое значение `level=ERROR+WARNING`. Семантика: **только** записи
уровня `WARNING` ∪ `ERROR` ∪ `CRITICAL` (не ниже ERROR-порога, но включая
WARNING). Существующие теги (`DEBUG/INFO/WARNING/ERROR/CRITICAL/ALL`) не меняются.
Docstring `routes.py:1132` обновляется.

Реализация в `log_ring.get_entries` (`log_ring.py:139`):
```python
lvl = str(level or "INFO").upper().strip()
if lvl == "ERROR+WARNING":
    entries = [e for e in entries
               if logging.getLevelName(e["level"]) >= logging.WARNING]
else:  # прежняя ветка threshold
    ...
```

### 3.2. Дефолт уровня
- `logLevel` initial state = `'ERROR+WARNING'` (`app.js:860`).
- Селектор (index.html:2766-2768) += опция `ERROR+WARNING`.
- **F6-Q4 РЕШЕНО:** дефолт применяется при каждом первичном открытии приложения
  (initial state), а НЕ при каждом переключении на вкладку «Статус». В рамках
  сессии выбор пользователя сохраняется. Без `localStorage` (сессионно).

### 3.3. `uptime` в `/api/status` (F6-Q3 — РЕШЕНО)
Поля `bot/server/llm/uptime/permsoc` **сохраняются** (обратная совместимость,
key-history/другие потребители). Убирается только **рендер** линейного графика.
Никаких удалений из контракта; в ARCHITECTURE — пометка «deprecated-render».

## 4. EKG-алгоритм

Источник пульса (F6-Q2 — РЕШЕНО): `server.loadavg[0]` (Linux), иначе
`max(server.cpu_percent, server.memory.percent)` (Windows dev, loadavg=None).
Недостающие/`None` метрики → CPU/RAM фолбэк; всё `None` → «спокойный зелёный»
(нейтраль).

Пороги (фронт-константы, F6-Q5 — РЕШЕНО: не каталог):
```
ratio = (loadavg0 / max(1, cpu_count)) or max(cpu%, mem%)
calm   : ratio < 0.5   → зелёный,  период ~2.4s
elev   : 0.5..0.8      → оранжевый, период ~1.4s
high   : ratio > 0.8   → красный,   период ~0.8s
```
Реализация: **свой** inline-SVG (polyline ЭКГ) + CSS `animation` (`@keyframes
dash`/scaleX). Не использовать Chart.js (не мешать key-history).
`prefers-reduced-motion: reduce` → анимация выключена, цвет меняется статически.

## 5. Файлы и точки изменения

| Файл | Что |
|---|---|
| `web/app.js` | `logLevel` :860 → `'ERROR+WARNING'`; удалить `renderUptimeChart` :3575 + вызов :3524 + `uptimeCanvas`-ref; новый `renderHeartbeat`/data; `loadLogs` :3786 |
| `web/index.html` | удалить `<canvas ref="uptimeCanvas">` :2718; вставить SVG-EKG; `+ERROR+WARNING` :2767 |
| `web/api/routes.py` | `get_status_logs` docstring :1132 (тег) |
| `services/log_ring.py` | `get_entries` :139 — комбинированный тег |
| `tests/test_log_ring*.py`, `tests/test_webapp_*log*.py`, `tests/test_webapp_round1013_ui.py`, `tests/js/routing_test.js` | тесты |

## 6. Каталог-Δ

**+0** (пороги EKG — фронт-константы, presentational). GROUPS/mapped/TAB_RULES без изменений.

## 7. Feature flags / progressive delivery

- Не требуется (render-only + расширение контракта логов). Rollback — `git revert`.

## 8. План миграций промптов

Не применимо.

## 9. Тест-план

1. `log_ring.get_entries("ERROR+WARNING")` = WARNING ∪ ERROR ∪ CRITICAL; не
   включает INFO/DEBUG; порядок newest-first; `ALL`/`INFO` — регресс.
2. `/api/status/logs?level=ERROR+WARNING` — 200, фильтр; docstring/маркер обновлены.
3. Статика UI: нет `uptimeCanvas`/`renderUptimeChart`; есть EKG-маркеры; опция
   `ERROR+WARNING`; `logLevel` default = `ERROR+WARNING`.
4. JS-юниты: model уровня логов (селектор == запрос == рендер — единый источник),
   EKG-класс/период по метрике, reduced-motion ветка.
5. `prefers-reduced-motion` — анимация выключена.
6. `pytest` 0 failed; `node --check` clean; `JS-UNIT-OK`; `git diff --check`.

## 10. Риски

| Риск | Митигация |
|---|---|
| Рассинхрон селектор/рендер | Единый источник истины `logLevel`; тест «селектор==запрос==список» |
| `loadavg=None` на Windows dev | CPU/RAM фолбэк; всё None → нейтраль |
| Ломаем key-history Chart.js | EKG свой SVG/CSS, Chart.js не трогаем |
| Конфликт с F5 в одном файле | Последовательное исполнение F5→F6 |

## 11. Критерии приёмки

- [ ] Старый линейный аптайм-график удалён; SVG-EKG живой, привязан к Load/CPU/RAM.
- [ ] Рассинхрон устранён (единый `logLevel`).
- [ ] `ERROR+WARNING` в селекторе и на сервере; дефолт при открытии — он.
- [ ] Маркерные тесты контракта обновлены; `uptime`-поля сохранены.
- [ ] `node --check` clean, `JS-UNIT-OK`, `pytest` 0 failed, `git diff --check`.
- [ ] R17 не ослаблен; `prefers-reduced-motion` учтён.

## 12. Разрешение open questions (F6)

- **F6-Q1** — серверный тег `ERROR+WARNING` (не клиентская фильтрация).
- **F6-Q2** — пульс: loadavg[0] → CPU/RAM фолбэк; всё None → нейтраль.
- **F6-Q3** — поля `uptime` в `/api/status` **сохраняются** (убираем только рендер).
- **F6-Q4** — дефолт `ERROR+WARNING` при каждом первичном открытии приложения (сессионно).
- **F6-Q5** — пороги — фронт-константы (каталог-Δ = 0).
