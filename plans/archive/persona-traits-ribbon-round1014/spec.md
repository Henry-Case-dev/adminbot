# Spec F4 — `persona-traits-ribbon-round1014` (Лента «Эволюция характера» + метрики Личности в «Сводке»)

> **Статус: ✅ COMPLETED** (Step 2 @Architect, **итерация 2**, 13.09.2026).
> **Раунд:** 10.14. **T-ID:** T-1505…T-1510. **ТЗ:** `plans/current_task.md` §3.1 + **UPD п.4 (метрики)**.
> **Зависимости:** **F2** (`dynamic_traits` + `GET /api/persona/health`), **F1** (статус экстрактора). **Baseline:** HEAD `2edc65b`.
> **Конфликт файлов:** `web/index.html` делят F3/F4/F6/F7 — вливать согласованно (F4 до F7).

---

## §0. Решения Architect (кратко)

| Вопрос | Решение |
|---|---|
| **F4-Q1** формат записи ленты | **«ДД.ММ: текст»** (`fmtDayMonth(ts) + ': ' + text`); cap 200 (F2). |
| **F4-Q2** объём/частота | Последние **12** черт (как `_ribbonLoop` `:4750`); обновление — polling 15с `loadCognition` (пауза `document.hidden`). |
| **F4-Q3** пусто | Заглушка «Пул черт пуст.» (по образцу beliefs/paradigms `:2920`). |
| **UPD п.4 — метрики в «Сводке»** | Панель «Личность» на дашборде **`#/oversight`** (Сводка): счётчик сгенерированных traits, время последнего пересмотра характера (`last_trait_at`), статус работы экстрактора самосознания (`extractor_status`/`extractor_last_at`). Источник — `GET /api/persona/health` (F2/F1). |
| Источник ленты | `GET /api/persona` → `dynamic_traits` (global). Отдельного read-роут не вводим. |
| Переиспользование | `_ribbonLoop`/`ribbonItemClass` (`:4749-4776`) — без дублирования. |
| Grid | 2 → **3 колонки** (`.cognition-ribbons` `:677`), responsive `3→1`. |

---

## §1. Цель и scope

1. В «Статусе», в блоке «Мониторинг Интеллекта» — третья бегущая лента **«Эволюция характера»** со скроллом `dynamic_traits` (`13.09: Стал более циничным...`).
2. В дашборде **«Сводка»** (`#/oversight`) — компактная панель метрик здоровья Личности (UPD п.4).

**In scope:** третья лента; 3-колоночная сетка; загрузка `cognitionTraits`; панель метрик Личности в Oversight; формат/пустые состояния.

**Out of scope:** генерация traits (F2); порядок блока «Мониторинг Интеллекта» (F7); форма «Личность» (F3).

---

## §2. Изменения (`file:line` на HEAD `2edc65b`)

### `web/index.html`
| Точка | Изменение |
|---|---|
| `.cognition-ribbons` CSS `:677` | `grid-template-columns: 1fr 1fr` → `1fr 1fr 1fr`; media-query `:678` → `1fr` |
| разметка лент `:2916-2943` | + третья `.ribbon`: заголовок «Эволюция характера», `v-for="it in cognitionTraitsLoop"`, пусто → «Пул черт пуст.»; метка `fmtDayMonth(it.created_at)` |
| CSS `:679-728` | не трогать; `@media (prefers-reduced-motion)` сохранить |
| Oversight `:1697+` | новая панель «Личность» над таблицей чатов: 3 показателя (`personaHealth.traits_count`, `personaHealth.last_trait_at`, `personaHealth.extractor_status`) + бейдж статуса; `v-if="isGlobalAdmin"` |

### `web/app.js`
| Точка | Изменение |
|---|---|
| data `:866-867` | +`cognitionTraits: []`, +`personaHealth: null` |
| computed `:1177-1181` | +`cognitionTraitsLoop: function(){ return this._ribbonLoop(this.cognitionTraits); }` |
| `loadCognition` `:4818-4844` | + `var p = await this.api('/api/persona' + this._cidQuery(true)); this.cognitionTraits = ...` (адаптер `{ts,text}→{id,fact,created_at}`) **и** `this.personaHealth = await this.api('/api/persona/health')` (oversight-контекст) |
| `fmtDayMonth(ts)` | новый чистый хелпер → `'ДД.ММ'` (образец `fmtClock` `:4778`), юнит-тестируемый |
| Oversight-загрузка | `loadOversight()` дополнить чтением `personaHealth`; fail-open → `null` + заглушка «—» |

**Нормализация для `_ribbonLoop`:** `dynamic_traits` — `{ts, text, source}`; адаптер → `{id: ts||i, fact: text||'', created_at: ts||0}`. `_ribbonLoop`/`ribbonItemClass` не трогаем.

### `web/api/routes.py` / `web/api/oversight.py`
- `dynamic_traits` отдаётся в `GET /api/persona` (F2). Метрики — `GET /api/persona/health` (F1/F2): `{traits_count, last_trait_at, last_trait_status, extractor_status, extractor_last_at}`.
- **Не** дублировать данные в `/api/oversight/summary` (один дом — persona-API). Frontend запрашивает health отдельным вызовом на экране Oversight.

## §3. Алгоритм загрузки

```js
loadCognition: async function () {
  ...
  var p = await this.api('/api/persona' + this._cidQuery(true));
  this.cognitionTraits = Array.isArray(p.dynamic_traits) ? p.dynamic_traits : [];
  ...
}
// Oversight:
loadPersonaHealth: async function () {
  try { this.personaHealth = await this.api('/api/persona/health'); }
  catch (e) { this.personaHealth = null; }
}
```
- Лента показывает **глобальные** traits (личность бота). Fail-open: ошибка → `cognitionTraits=[]` (заглушка).

## §4. Конфиг-ключи и дефолты

Нет новых ключей. Отображение/период — фронт-константы (`:4749-4776`). Метрики — read-only.

## §5. Feature flag / progressive delivery

Лента/панель рендерятся только если `isGlobalAdmin` (как Cognition/Oversight) и `flags.persona_enabled` ON (иначе пустой пул/«—»). Rollback = `git revert`.

## §6. Тест-план

1. Маркеры UI (`tests/test_webapp_round1014_ui.py`): третья `.ribbon`, заголовок «Эволюция характера», `cognitionTraitsLoop`, адаптер `{ts,text}→{id,fact,created_at}`, `fmtDayMonth`, пустое состояние.
2. Метрики: панель «Личность» в Oversight; маркеры `traits_count`/`last_trait_at`/`extractor_status`; `loadPersonaHealth`; заглушка при ошибке.
3. CSS-маркер: `.cognition-ribbons` — 3 колонки; media-query `1fr`.
4. JS-юнит: `fmtDayMonth(1757750400)` → `'13.09'`; пустой массив → `[]`; `ribbonItemClass` не изменён.
5. `_ribbonLoop` переиспользован (grep-маркер, нет дубля).
6. `node --check web/app.js`, полный pytest 0 failed, `git diff --check`.

## §7. Критерии приёмки (DoD)

- [ ] В блоке «Мониторинг Интеллекта» три ленты; третья — «Эволюция характера», скроллит реальные traits «ДД.ММ».
- [ ] В «Сводке» (`#/oversight`) видна панель метрик Личности: traits count, время пересмотра, статус экстрактора.
- [ ] `_ribbonLoop`/`ribbonItemClass` переиспользованы; grid responsive (3→1); `prefers-reduced-motion` работает.
- [ ] Пустые состояния аккуратны; ошибки API не ломают экраны (fail-open).
- [ ] Полный `pytest` 0 failed; `node --check` clean; `git diff --check` чист.
