# Фича F4 — `persona-traits-ribbon-round1014` (Лента «Эволюция характера» + метрики Личности)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 13.09.2026). T-1505…T-1509 закрыты;
> гейт T-1510 (@Reviewer/@PM) — открыт. `pytest` 5508 passed, `node --check` clean.
> **Раунд:** 10.14. **Нумерация:** T-1505…T-1510 (продолжает T-1504).
> **Тип:** frontend. **Приоритет:** P1.
> **Зависимости:** **F2** (`dynamic_traits` + `/api/persona/health`), **F1** (статус экстрактора).
> **ТЗ:** `plans/current_task.md` §3.1 + **UPD п.4**. **Эпик:** Self-Awareness / Persona round1014. **Baseline:** HEAD `2edc65b`.

## 0. Цель

1. В «Статусе», в блоке «Мониторинг Интеллекта», третья бегущая лента **«Эволюция характера»** (`dynamic_traits`).
2. В дашборде **«Сводка»** (`#/oversight`) — панель метрик здоровья Личности (UPD п.4): счётчик traits, время последнего
   пересмотра характера, статус экстрактора самосознания.

**Фундамент:** 2 ленты + `_ribbonLoop`/`ribbonItemClass` (`web/app.js:4749-4776`); Oversight-экран `web/index.html:1697+`.

## 1. Требования (ТЗ §3.1 + UPD п.4)

- [x] Третья лента «Эволюция характера» со скроллом записей traits.
- [x] Метрики в «Сводке»: traits count, время последнего пересмотра, статус экстрактора.
- [x] Наблюдение в реальном времени; аккуратные пустые состояния.

## 2. Целевые модули (`file:line` на HEAD `2edc65b`)

- `web/index.html`: `.cognition-ribbons` `:677`; ленты `:2916-2943`; Oversight `:1697+` (панель «Личность»).
- `web/app.js`: computed `:1178,1181`; `_ribbonLoop` `:4749`; `loadCognition` `:4818-4844`; Oversight-loader.
- `web/api/routes.py`: `GET /api/persona/health` (F2); `GET /api/persona` (traits).
- Тесты: `tests/test_webapp_round1014_ui.py`, JS-юниты.

## 3. Инварианты

- ✅ PG-DDL разрешён; F4 ключей/DDL не вводит.
- ⛔ Порядок блока «Мониторинг Интеллекта» меняет F7 — F4 только добавляет ленту/панель.
- ⛔ `media/`/`.env`, порядок роутеров `bot.py`, R17/R16.
- Новых `v-html`/CDN нет; анимация — существующая CSS; `prefers-reduced-motion` учитывается.
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, R17-скан, русские commits.

## 4. Зависимости

- **Вверх:** **F2** (traits + health), **F1** (extractor status). **Вниз:** нет.
- **Конфликт файлов:** F3/F4/F6/F7 делят `web/app.js`/`index.html` — F3→F4→F7, F6 аккуратно; согласовать с @Orchestrator.

## 5. Definition of Done

- [x] В блоке три ленты; третья — «Эволюция характера»; пустой массив — заглушка.
- [x] В «Сводке» — панель метрик Личности (traits/last_trait_at/extractor_status).
- [x] `_ribbonLoop`/`ribbonItemClass` переиспользованы; grid responsive (3→1).
- [x] Полный `pytest` 0 failed; `node --check` clean; `git diff --check` чист.

## 6. Чек-лист задач

- [x] **T-1505 (@Builder, API):** `GET /api/persona/health` (traits_count/last_trait_at/last_trait_status/
  extractor_status/extractor_last_at); `dynamic_traits` в `GET /api/persona`; fail-open. *(Поставлено F2
  (`web/api/routes.py:1345,1448`, `services/bot_persona.py:258,291`); покрыто `tests/test_persona_api.py`/
  `tests/test_bot_persona.py`. F4-Δ по API = 0.)*
- [x] **T-1506 (@Builder, app.js):** `cognitionTraits`+`personaHealth`, computed `cognitionTraitsLoop`,
  `fmtDayMonth`, адаптер, `loadPersonaHealth`; переиспользовать `_ribbonLoop`.
- [x] **T-1507 (@Builder, index.html):** третья `.ribbon` «Эволюция характера»; grid 3 колонки; панель метрик
  Личности в Oversight.
- [x] **T-1508 (@Builder, tests):** маркеры UI (лента, панель метрик), пустые состояния, JS-юниты;
  `tests/test_webapp_round1014_ui.py`.
- [x] **T-1509 (@Builder):** `node --check web/app.js`, полный `pytest` (0 failed), `git diff --check`; пересчёт инвариантов.
- [ ] **T-1510 (@PM/@Reviewer, гейт):** сверка DoD, live-чеклист (скролл ленты + метрики на Android).

## 7. Открытые вопросы (закрыты)

- **F4-Q1:** «ДД.ММ: текст». **F4-Q2:** 12 записей, polling 15с. **F4-Q3:** заглушка.
- **UPD п.4:** «Сводка» = дашборд `#/oversight`; источник — `/api/persona/health`.

## 8. Feature flag / progressive delivery

- Render-only + read-only метрики. Rollback = `git revert`.
