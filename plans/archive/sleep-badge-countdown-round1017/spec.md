# Спека F3 — `sleep-badge-countdown-round1017` (Бейджи Сна: «через остаток» / «до времени»)

> **Статус:** ✅ COMPLETED (14.09.2026; @Reviewer **APPROVED**, итерация 2). Реализовано T-1686…T-1690; гейт T-1691 (@Reviewer/@PM) закрыт.
> **Раунд:** 10.17. **Тип:** frontend (web/app.js). **Приоритет:** P1.
> **T-ID:** T-1685…T-1691. **ADR:** [`adr-1017-3-sleep-badge-countdown.md`](adr-1017-3-sleep-badge-countdown.md).
> **Baseline:** HEAD `772f192`; pytest 5936/0; каталог 435/406/411/90/88/19 (Δ=0); SQLite v9.
> **ТЗ:** `plans/current_task.md` UPD3 (стр. 158) + `plans/archive/status-graph-ui-relocation-round1015/spec.md` §3а (оконная семантика 10.15 — сохраняется).

## 0. Цель

В «Мониторинге интеллекта» бейджи фаз показывают **целевой час** (`«Сон через 11:00»`, где 11:00 — время начала) вместо **остатка**, а выключенное состояние — `«… выключен»` вместо остатка.

**Требуется:**
- Вне фазы: `[☀️] Сон через {остаток}`; `[🌅] Глубокий сон через {остаток}` (в т.ч. при `enabled === false` — нейтральный текст без свечения).
- В фазе: `.glow`, `[🌙] Сон до {HH:MM окончания}`; `[🌌] Глубокий сон до {HH:MM окончания}`.
- **Эмодзи `☀️`/`🌙`/`🌅`/`🌌` не менять.**
- Оконная семантика 10.15 (`active` = окно расписания ИЛИ running; `enabled=false` гасит окно) — сохраняется.
- «Лимит сна исчерпан» (dream, `state==='limit_exhausted'`) — сохраняется.

## 1. Scope

**In scope (`web/app.js`):**
- Новый хелпер `fmtCountdown(seconds)`.
- Переработка `dreamPhaseBadge()` и `deepPhaseBadge()`.
- `now` — из серверного `cognition.generated_at`.

**Out of scope:**
- API `/api/memory/cognition/status` — **не менять** (`generated_at` уже отдаётся, `:545`).
- `fmtClock` — не менять (нужен для «до HH:MM»).
- Оконная семантика/`_in_hour_window`/`_next_hour_epoch` — не менять.
- Эмодзи, классы цветов, `limit_exhausted`, порядок бейджей, адаптив.
- Живой tick-таймер (см. §3.4).

## 2. Точки изменения (`file:line` на `772f192`)

| Файл | Строки | Что |
|---|---|---|
| `web/app.js` | 1214-1231 | `dreamPhaseBadge()` — остаток/до/лимит |
| `web/app.js` | 1232-1246 | `deepPhaseBadge()` — остаток/до |
| `web/app.js` | 5112-5119 | рядом добавить `fmtCountdown(seconds)` (рядом с `fmtClock`) |
| `web/app.js` | 5153-5205 | `loadCognition*` — `this.cognition.generated_at` используется как `now` |
| `tests/test_webapp_round1015_ui.py` | 243-249 | обновить маркер: убрать `"🌅 Глубокий сон выключен"`, добавить countdown-маркеры |
| `tests/test_webapp_round1013_f5_ui.py` | 394-397 | сверить маркеры «Сон через …» (строка остаётся, меняется аргумент) |
| `tests/test_webapp_round1017_sleep.py` | новый | unit-тесты `fmtCountdown`/бейджей |

## 3. Контракт UI

### 3.1. `fmtCountdown(seconds) -> str`
- Валидация: не число/`null`/`NaN` → `"—"`.
- Кламп `>= 0` (просрочка/`active_until` в прошлом → `0`).
- Округление **вниз** до минут.
- Формат (ADR-1017-3):
  | Условие | Пример |
  |---|---|
  | `seconds >= 3600` | `2ч 15м` |
  | `seconds < 3600` | `15м` |
  | `0 <= seconds < 60` | `0м` |

### 3.2. `dreamPhaseBadge()`
```
now = Number(cognition.generated_at) || Math.floor(Date.now()/1000)
d = cognition.dream || {}
if d.active:
    if d.active_until: return { text: '🌙 Сон до ' + fmtClock(d.active_until), cls: 'badge-ok glow' }
    return { text: '🌙 Сон идёт', cls: 'badge-ok glow' }
if d.state === 'limit_exhausted':
    return { text: '☀️ Лимит сна исчерпан', cls: 'badge-warn' }
return { text: '☀️ Сон через ' + fmtCountdown(Number(d.next_wake_at) - now), cls: 'badge-muted' }
```
- Ветки `d.enabled === false → «выключен»` **больше нет** (UPD3): при `enabled=false` и не-`active` показывается остаток, но класс остаётся `badge-muted` (без свечения).
- Эмодзи `☀️`/`🌙` — без изменений.

### 3.3. `deepPhaseBadge()`
```
now = ... (как выше)
d = cognition.deep_sleep || {}
if d.active:
    if d.active_until: return { text: '🌌 Глубокий сон до ' + fmtClock(d.active_until), cls: 'badge-info glow' }
    return { text: '🌌 Глубокий сон идёт', cls: 'badge-info glow' }
return { text: '🌅 Глубокий сон через ' + fmtCountdown(Number(d.next_run_at) - now), cls: 'badge-muted' }
```
- Эмодзи `🌅`/`🌌` — без изменений.

### 3.4. Границы/таймер
- `active_until` в прошлом → `fmtClock` покажет время как есть (в фазе); вне фазы `next_*` в прошлом → `fmtCountdown` вернёт `0м`.
- Отсутствие данных (`cognition==null`, поля `null`) → `"—"`, класс `badge-muted`.
- **Живого tick-таймера нет**: остаток пересчитывается на каждом рендере от серверного `generated_at`; актуальность — по существующему polling `cognition/status` (`loadCognition`, `:5153-5205`). Это осознанный минимализм (ADR-1017-3 §3).

## 4. Тест-план (`tests/test_webapp_round1017_sleep.py` + JS-маркеры)

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | `fmtCountdown(8100)` | `"2ч 15м"` |
| 2 | `fmtCountdown(900)` | `"15м"` |
| 3 | `fmtCountdown(0)` / `fmtCountdown(-30)` | `"0м"` |
| 4 | `fmtCountdown(null)`/`"abc"`/`NaN` | `"—"` |
| 5 | dream: `enabled=false`, `active=false`, `next_wake_at=now+3600` | `text=='☀️ Сон через 1ч 0м'`, `cls=='badge-muted'` (нет «выключен», нет glow) |
| 6 | dream: `active=true`, `active_until` | `text` начинается `'🌙 Сон до '`, `cls` содержит `glow` |
| 7 | dream: `active=false`, `state='limit_exhausted'` | `'☀️ Лимит сна исчерпан'`, `badge-warn` |
| 8 | deep: `enabled=false`, `active=false` | `'🌅 Глубокий сон через <остаток>'`, `badge-muted` (нет «выключен») |
| 9 | deep: `active=true`, `active_until` | `'🌌 Глубокий сон до '`, `badge-info glow` |
| 10 | `cognition==null` | оба бейджа `"—"`, `badge-muted` |
| 11 | отсутствие `generated_at` | используется `Date.now()/1000`, без `NaN` |
| 12 | diff эмодзи | `☀️ 🌙 🌅 🌌` присутствуют, состав не изменён |
| 13 | обновлённый маркер 10.15 | `"🌅 Глубокий сон выключен"` отсутствует |
| 14 | `node --check web/app.js`, `tests/js/routing_test.js` | clean / `JS-UNIT-OK` |

## 5. Риски

| Риск | Мера |
|---|---|
| Стейл остатка между poll-ами | пересчёт от `generated_at`; при желании владельца — добавить tick отдельной задачей (не в скоупе) |
| Клиентские часы разъехались с сервером | `now` = `generated_at` (серверное время), не `Device` |
| `enabled=false` снова начнёт показывать «выключен» | тест (5)/(8) + маркер-гейт |
| Сломан эмодзи/классы 10.15 | тест (6)/(9)/(12), диф-ревью |
| Wrap через полночь | не затрагиваем: бейджи читают `active`/`active_until`/`next_*` как есть (оконная семантика на бэке) |

## 6. Критерии приёмки (DoD)

- [x] Вне фазы: `Сон через 2ч 15м` / `Глубокий сон через 15м` (не `HH:MM`, не «выключен»).
- [x] В фазе: бейджи светятся и показывают `до HH:MM` (`active_until`).
- [x] Эмодзи не тронуты (тест/диф).
- [x] Границы устойчивы (полночь, прошлое → `0м`, нет данных → `—`).
- [x] Оконная семантика и «Лимит сна исчерпан» сохранены.
- [x] JS-гейты чистые; полный pytest 0 failed (6007 passed); каталог Δ=0; R17.

## 7. Feature flag / progressive delivery

- **Feature flag:** не требуется (UI-фикс). Rollback = `git revert`.
- **Progressive delivery:** неприменим; визуальная проверка десктоп + мобильный (адаптив бейджей сохраняется).

## 8. Handoff

`@Orchestrator` — спецификация F3 готова. Реализация — T-1686…T-1690 (@Builder), гейт T-1691 (@Reviewer/@PM).
