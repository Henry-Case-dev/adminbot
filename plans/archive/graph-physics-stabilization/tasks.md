# Фича F4 — `graph-physics-stabilization` (vis-network: 150 итераций стабилизации + отключение физики по `stabilizationIterationsDone`)

> **Статус: ⏳ PLANNED** (Step 1 @PM, 15.09.2026). Реализация — T-1737…T-1739 (@Builder), гейты T-1736 (@Architect) / T-1740 (@Reviewer/@PM).
> **Spec:** `spec.md` — ⏳ создаёт @Architect (Step 2). **ADR:** ⏳ рекомендуется (изменение физики графа; AMEND §F2 10.15).
> **Раунд:** 10.18. **Нумерация:** T-1736…T-1741 (продолжает T-1735).
> **Тип:** frontend (`web/app.js`, vis-network). **Приоритет:** **P1** (перф при 500–800 узлах).
> **Зависимости:** **F3** (плотность 500–800 узлов) — физика оптимизируется под новый размер. **Конфликт файлов:** `web/app.js` (делится с F2 T-1720/T-1721 — вливать ступенями).
> **Эпик:** `Epic: BetterStack-Sleep-Graph round1018` (@Memory, Step 0).
> **ТЗ:** `plans/current_task.md` **§3.3** (строки 72–74).
> **Baseline:** HEAD `118a03c`; pytest **6007 passed / 0 failed**; каталог **435/406/411/90/88/19**; SQLite **v9**; APP_VERSION 2.57.0.

## 0. Цель

Обеспечить плавный старт и идеальные 60 FPS при 500–800 узлах: короткая стабилизация (`iterations: 150`) и **автоотключение физики** по событию `stabilizationIterationsDone` (или `stabilized`), после чего пользователь свободно зумит/двигает граф.

**Требуется (ТЗ §3.3):**
- `physics: { stabilization: { iterations: 150 } }`.
- Слушатель `stabilizationIterationsDone`/`stabilized` → `physics.enabled = false` после первичной расстановки.
- Сохранить текущие возможности (зум/перетаскивание/поиск/подсветка), не сломать `reducedMotion`.

## 1. Контекст и доказательства (@Memory Step 0)

- **Конфликт с F2 раунда 10.15:** сейчас физика **включена всегда**, `iterations: 250`. ТЗ §3.3 требует **150** + отключение по `stabilizationIterationsDone`.
- Правка в `renderCognitionGraph` (`web/app.js`, опции vis-network); `reducedMotion` и `_cognitionGraphSig`/`destroy` должны сохраниться.
- vis-network self-host (ADR-1013-2) — внешние CDN не вводить.
- F3 увеличивает граф до 500–800 узлов → без отключения физики браузер может тормозить.

## 2. Требования

- [x] `stabilization.iterations = 150`.
- [x] Обработчик `stabilizationIterationsDone` (и/или `stabilized`) выключает физику (`physics.enabled = false`).
- [x] Повторный рендер/`destroy` корректно пересоздаёт сеть (не «залипает» отключённая физика).
- [x] `reducedMotion` и текущие опции (barnesHut/интерактив) сохранены.
- [x] Поиск/подсветка (F2 10.15) и countdown/бейджи не затронуты.

## 3. Constraints (инварианты раунда)

- **R17** (без секретов), **R16** (не относится к UI-контракту).
- Внешних CDN не вводить (self-host vis-network, ADR-1013-2).
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **Каталог Δ=0** (только код-константы UI); SQL/DDL не требуется.
- **Ревью-гейты:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; полный `pytest` 0 регрессий; `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** F3 (ёмкость графа) — физика калибруется под 500–800 узлов.
- **Вниз:** —.
- **Порядок:** после F3. `web/app.js` делится с F2 — вливать ступенями (F2 → F4).

## 5. Definition of Done

- [x] Опции физики соответствуют §3.3 (150 + отключение по событию).
- [ ] На 500–800 узлах граф стабилизируется и далее взаимодействует без тормозов (визуальная проверка десктоп + мобильный — @DevOps/@PM).
- [x] `reducedMotion`, поиск, подсветка, бейджи сохранены; JS-гейты чистые; полный `pytest` **0 failed**.

## 6. Чек-лист задач

- [x] **T-1736 (@Architect, гейт):** `spec.md` (+ ADR-запись) — контракт опций vis-network: `iterations=150`, событие отключения физики, совместимость с `reducedMotion`/поиском/`destroy`/повторным рендером; фиксация изменения относительно F2 10.15 (`iterations:250`, физика всегда on).
- [x] **T-1737 (@Builder):** установить `physics: { stabilization: { iterations: 150 } }` в `renderCognitionGraph`.
- [x] **T-1738 (@Builder):** добавить слушатель `stabilizationIterationsDone`/`stabilized` → `physics.enabled = false`; корректная пересборка на повторном рендере/`destroy`.
- [x] **T-1739 (@Builder):** JS-тесты/маркеры (наличие `iterations: 150`, обработчика отключения физики, сохранение `reducedMotion`), `node --check`.
- [ ] **T-1740 (@Reviewer + @PM, гейт):** сверка DoD, отсутствие регресса поиска/подсветки/бейджей, JS-гейты.
- [x] **T-1741 (@Builder):** гейты — полный `pytest` 0 failed (**6100 passed**), `git diff --check` clean, `JS-UNIT-OK`/`VUE-MOUNT-OK`. Коммит (атомарно с F3) — отдельным шагом @Orchestrator/@DevOps.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | **Конфликт с F2 10.15** (физика всегда вкл, `iterations:250`) | T-1736 фиксирует новое поведение; тест T-1739 |
| R2 | 500–800 узлов + отключение физики → «застывший» неоптимальный layout | `iterations:150` + визуальная проверка; при необходимости — фикс-режим drag |
| R3 | Повторный рендер оставит физику выключенной навсегда | T-1738 обработка `destroy`/пересоздания |
| R4 | Сломан `reducedMotion`/поиск/подсветка | T-1739 маркеры + T-1740 ревью |
| R5 | `web/app.js` делится с F2 | Ступенчатое вливание F2 → F4 |

**Требуется новый ADR:** рекомендуется — AMEND/запись в ADR-1018 (физика графа) в рамках T-1736.

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (UI-опция). Rollback = `git revert`.
- **Progressive delivery:** неприменим; визуальная проверка на десктопе + мобильном (адаптив сохраняется).

## 9. Handoff / деплой

`@Orchestrator` — план F4 готов. Спека — T-1736 (@Architect). Реализация — T-1737…T-1739 (@Builder). **Деплой (SSH pull + `systemctl restart admin_bot` + live-проверка графа) — отдельный шаг @DevOps. Пароль сервера в репозитории НЕ хранится.**
