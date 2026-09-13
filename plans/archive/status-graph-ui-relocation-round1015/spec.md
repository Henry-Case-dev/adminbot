# Спека F5 — `status-graph-ui-relocation-round1015` (Релокация статистики графа + бейджи Сна/Глубокого сна)

> **Статус:** ✅ COMPLETED (Step 4 @Builder, round1015). Реализованы T-1585…T-1591; гейты T-1584/T-1592 за @Architect/@Reviewer.
> **Утверждено владельцем (UPD §3):** оконная семантика бейджей Сна/Глубокого сна — активность строго по расписанию окна; см. §3а.
> **Раунд:** 10.15. **Тип:** frontend + аддитивное поле API. **Приоритет:** P1. **T-ID:** T-1584…T-1592.
> **ТЗ:** `plans/current_task.md` §4 и §5 + UPD §3. **Зависимости:** F3 (статус сна; аддитивные поля), F1/F2 (граф/статистика).
> **Конфликт файлов:** `web/index.html`/`web/app.js` делит с F2 — вливать после F2 (F2 → F5).
> **Baseline:** HEAD `798e044`; pytest 5589/0; каталог 435/406/411/90/88/19.

## 1. Цель

**(§4)** Перенести «Статистику графа памяти» из «Модулей» в «Сводку», в «Модулях» оставить только управление — **без дублирования** (консолидировать с существующим блоком метрик «Сводки»).
**(§5)** Редизайн бейджей Сна/Глубокого сна (динамика текста + свечение, «через/до»), мобильный столбик, удаление текста «пробуждение ~11:00».

**Текущее состояние:** карточка статистики в «Модулях» `web/index.html:1452-1469`; блок метрик «Сводки» `:1804-1809`; бейджи «Сводки» `:1775-1776`; шапка «Мониторинга Интеллекта» `:2918-2927` (включая «пробуждение ~» `:2923-2924`); `dreamPhaseBadge`/`deepPhaseBadge` `web/app.js:1204-1224`; `fmtClock` `:5086-5093`; API `GET /api/memory/cognition/status` `web/api/memory_agi.py:399-495`.

## 2. Scope

**In scope**
- §4: удалить карточку `index.html:1452-1469`; добавить узлы/рёбра/типы/мемы в существующий flex-wrap `:1804-1809`.
- §5: аддитивные поля `cognition/status` (`active`/`active_until` для обеих фаз), новые тексты/иконки/свечение бейджей, мобильный столбик, удаление «пробуждение ~».
- Синхронизация бейджей «Сводки» `:1775-1776`.
- Маркер/API-тесты.

**Out of scope**
- Изменение существующих полей `cognition/status` (`next_wake_at`/`next_run_at`/`state`/`budget` — S10.13-5, не трогать).
- Новые каталог-ключи, DDL.

## 3. API-контракт (аддитивный)

F5-Q1 RESOLVED: **аддитивные поля** (вычисление на бэке, чтобы избежать рассинхрона/таймзонного дублирования на фронте). Существующие поля не меняются.

### 3а. Оконная семантика бейджей — **УТВЕРЖДЕНО владельцем** (UPD §3)

Активность бейджа — **строго по заданному расписанию окна**, а не по факту ручного запуска:

- `dream.active = in_window(now, dream_window_start_hour, dream_window_end_hour) OR dream_running`.
- `deep_sleep.active = (trigger=fixed: now_h == deep_sleep_hour) OR (trigger=after_sleep: in_window) OR deep_running`.
- `active_until` — epoch конца активной фазы (wrap через полночь учитывается хелпером `_in_hour_window`); вне окна — `null`, а `next_wake_at`/`next_run_at` указывают на **начало следующего** окна.
- Вне активной фазы бейдж не светится `[☀️]/[🌅] … через {next_*}`; в активной — светится `.glow`, `[🌙]/[🌌] … до {active_until}`.
- `dream_running`/`deep_running` — отдельные поля (сохраняются), активность бейджа — их OR с окном.
- **Правки владельца по семантике не требуются.** Реализация — как в §3.

Добавить в `web/api/memory_agi.py:480-489`:
```json
"dream": {
  "...": "...",
  "active": true,              // новое: сейчас окно сна ИЛИ идёт синтез
  "active_until": 1740000000   // новое: epoch конца активной фазы, иначе null
},
"deep_sleep": {
  "...": "...",
  "active": false,             // новое
  "active_until": null         // новое
}
```

**Вычисление (бэкенд, TZ из `limits.summary_timezone`):**
```python
end_h = int(hot.get("memory.dream_window_end_hour",
                    settings.DREAM_WINDOW_END_HOUR) or 6)
now_h = local_hour(now, tz_name)
in_window = _in_hour_window(now_h, start_h, end_h)   # с учётом wrap
dream_active = in_window or dream_running
dream_active_until = _next_hour_epoch(end_h, tz_name, now) if in_window else None

trigger = hot.get("memory.deep_sleep_trigger", ...)
if trigger == "fixed":
    deep_hour = int(hot.get("memory.deep_sleep_hour", ...) or 7)
    deep_in = now_h == deep_hour
    deep_until = _next_hour_epoch((deep_hour + 1) % 24, tz_name, now) if deep_in else None
else:                                  # after_sleep — окно как у обычного сна
    deep_in, deep_until = in_window, dream_active_until
deep_active = deep_in or deep_running
```
- `dream_running`/`deep_running` (`:414-415`) — сохраняются как отдельные поля.
- Fail-open: при `cognition=null`/ошибке фронт показывает нейтральные бейджи.
- `_in_hour_window` — новый чистый хелпер (учёт wrap через полночь), покрыть тестом.

## 4. Бейджи (точные тексты)

F5-Q2 RESOLVED: `enabled=false` и `limit_exhausted` — отдельные нейтральные состояния; иконки дня (`☀️`/`🌅`), без свечения.
F5-Q3 RESOLVED: свечение — существующий класс `.badge.glow` (`web/index.html:729-731`); акцентный цвет обеспечивает `currentColor` бейджа.

**`dreamPhaseBadge` (`web/app.js:1204-1214`):**
| Состояние | Текст | Класс |
|---|---|---|
| `d.active` | `[🌙] Сон до {fmtClock(active_until)}` | `badge-ok glow` |
| `d.active && !active_until` | `[🌙] Сон идёт` | `badge-ok glow` (fallback/manual) |
| `d.enabled === false` | `[☀️] Сон выключен` | `badge-muted` |
| `d.state === 'limit_exhausted'` | `[☀️] Лимит сна исчерпан` | `badge-warn` |
| иначе | `[☀️] Сон через {fmtClock(next_wake_at)}` | `badge-muted` |

**`deepPhaseBadge` (`web/app.js:1215-1224`):**
| Состояние | Текст | Класс |
|---|---|---|
| `d.active` | `[🌌] Глубокий сон до {fmtClock(active_until)}` | `badge-info glow` |
| `d.active && !active_until` | `[🌌] Глубокий сон идёт` | `badge-info glow` |
| `d.enabled === false` | `[🌅] Глубокий сон выключен` | `badge-muted` |
| иначе | `[🌅] Глубокий сон через {fmtClock(next_run_at)}` | `badge-muted` |

- `fmtClock` (`:5086-5093`) — **не менять**.
- «Сводка» `:1775-1776`: убрать добавку `· {{ fmtClock(next_wake_at) }}` (время уже в тексте бейджа → нет дубля).

## 5. §4 — Релокация (без дубля)

- **Удалить целиком** карточку `web/index.html:1452-1469` (в «Модулях»).
- **Добавить** в существующий flex-wrap «Сводки» `:1804-1809` (внутри блока «Интеллект и Память») бейджи:
  ```html
  <span class="badge badge-muted">Узлов: {{ cognitionStats.graph_nodes }}</span>
  <span class="badge badge-muted">Рёбер: {{ cognitionStats.graph_edges }}</span>
  <span class="badge badge-muted">Типов связей: {{ cognitionStats.relation_types }}</span>
  <span class="badge badge-muted">Мемов: {{ cognitionStats.memes }}</span>
  ```
  рядом с существующими Фактов/Убеждений/Защищённых/Парадигм (`:1805-1808`).
- Данные уже загружаются `loadMemoryWidget` (`web/app.js:5185`, `cognitionStats`) — дополнительных запросов не нужно; кнопка `⟳` виджета (`:1768-1769`) остаётся.
- Удалить теперь неиспользуемый `loadCognitionStats` (`web/app.js:5127-5135`), если после удаления карточки нет других вызовов (проверить grep; при наличии — оставить).

## 6. §5 — Мобильный столбик

- Шапке «Мониторинга Интеллекта» (`index.html:2919`) добавить класс `intel-header`.
- CSS (рядом с `:698-699`):
  ```css
  .intel-header { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
  @media (max-width: 640px) {
    .intel-header { flex-direction: column; align-items: flex-start; }
    .intel-header .intel-title { width: 100%; }
  }
  ```
  → мобильно: 1) заголовок, 2) бейдж Сна, 3) бейдж Глубокого сна; десктоп/широкий — горизонтально с растяжением.
- Заголовку добавить `intel-title`.
- **Удалить** `index.html:2923-2924` («пробуждение ~…») полностью.
- Кнопка `⟳` (`:2925-2926`) — переносить в конец столбца на мобильном (flex-wrap сам), не удалять (F5-Q4 RESOLVED: остаётся).

## 7. Точки изменения (file:line, HEAD `798e044`)

| # | Файл:строка | Изменение |
|---|---|---|
| 1 | `web/api/memory_agi.py:480-489` | Аддитивные `active`/`active_until` для `dream` и `deep_sleep`; чтение `dream_window_end_hour`; хелпер `_in_hour_window`. |
| 2 | `web/app.js:1204-1224` | Новые тексты/иконки/классы бейджей (см. §4). |
| 3 | `web/index.html:1452-1469` | Удалить карточку статистики из «Модулей». |
| 4 | `web/index.html:1804-1809` | Добавить узлы/рёбра/типы/мемы в блок «Сводки». |
| 5 | `web/index.html:1775-1776` | Убрать дублирующее время из бейджей «Сводки». |
| 6 | `web/index.html:2918-2927` | Класс `intel-header`/`intel-title`, удалить «пробуждение ~» `:2923-2924`. |
| 7 | `web/index.html:698-699` (CSS) | `.intel-header` + media-столбик. |
| 8 | `web/app.js:5127-5135` | Удалить неиспользуемый `loadCognitionStats` (если нет вызовов). |

**Не менять:** `next_wake_at`/`next_run_at`/`state`/`budget`, `fmtClock`, `_cognitionGraphSig`, polling.

## 8. Feature-флаг / progressive delivery

Не требуется (render + аддитивное API). Rollback = `git revert`. Каталог-Δ=0.

## 9. Тест-план

- `tests/test_webapp_round1015_ui.py` (маркеры): в «Модулях» нет `Статистика графа памяти`/`graph_nodes`; в «Сводке» есть узлы/рёбра/типы/мемы; нет строки `пробуждение ~`; есть `intel-header` и CSS media-столбик; тексты бейджей `[☀️]/[🌙]/[🌅]/[🌌]` и `.glow`.
- `tests/test_webapp_round1013_f5_ui.py`/`round1014_ui.py` — обновить ожидания бейджей (старые `🌙 Сон активен`/`🌙 Спит` → новые).
- API-тест `cognition/status`: `dream.active`/`active_until` и `deep_sleep.active`/`active_until` присутствуют; `next_wake_at`/`next_run_at` не изменились; fail-open при ошибке БД.
- Юнит `_in_hour_window` (окно 4–6, wrap, границы).
- **Гейты:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; полный `pytest` 0 failed; `git diff --check`; каталог Δ=0.

## 10. Открытые вопросы → решения

- **F5-Q1** «до [время]»: аддитивные поля API `active`/`active_until` (оконная семантика; `running` — отдельно).
- **F5-Q2** `limit_exhausted`/`enabled=false`: нейтральные дневные иконки `[☀️]`/`[🌅]`, без свечения.
- **F5-Q3** свечение: существующий `.badge.glow`.
- **F5-Q4** breakpoint 640px (консистентно с `.cognition-ribbons` `:699`); кнопка `⟳` остаётся.
- **F5-Q5** порядок метрик «Сводки»: Фактов → Убеждений → Защищённых → Парадигм → Узлов → Рёбер → Типов связей → Мемов (единый flex-wrap).
- **F5-Q6** оконная семантика бейджей — **УТВЕРЖДЕНА владельцем (UPD §3)**: актив = окно ИЛИ running; `active_until` — конец окна; вне окна — начало следующего (§3а).

## 11. Риски

| Риск | Митигация |
|---|---|
| Дубль времени в бейджах «Сводки» | Убрать `· fmtClock(...)` `:1775`. |
| Таймзона `active_until` | Вычисление на бэке в `limits.summary_timezone`, как `next_wake_at`. |
| Wrap-окно через полночь | Отдельный чистый хелпер + юнит-тест. |
| Слом существующих маркер-тестов UI | Синхронное обновление round1013/1014-тестов в T-1590. |

## 12. Критерии приёмки (DoD)

- [ ] В «Модулях» нет карточки «Статистика графа памяти»; там только управление/настройки.
- [ ] В «Сводке» видны консолидированные метрики (включая узлы/рёбра/типы/мемы) — без дубля.
- [ ] Бейджи: вне активной — `[☀️]`/`[🌅] … через HH:MM` без свечения; в активной — `[🌙]`/`[🌌] … до HH:MM` со свечением.
- [ ] Мобильный столбик: заголовок → бейдж Сна → бейдж Глубокого сна; «пробуждение ~11:00» удалён.
- [ ] `node --check` clean; `JS-UNIT-OK`; полный `pytest` 0 failed; каталог Δ=0.

## 13. Инварианты

Аддитивность API (`next_wake_at`/`next_run_at` сохранены, S10.13-5), R16/R17, без новых CDN/`v-html`, `reducedMotion`/polling не ломать, `media/`/`.env`/порядок роутеров `bot.py` не трогать, каталог 435/406/411/90/88/19.
