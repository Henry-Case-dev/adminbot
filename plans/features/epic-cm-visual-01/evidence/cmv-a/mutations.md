# CMV-A — доказательство чувствительности тестов (мутации)

Каждая строка — реальная мутация рабочего кода (не теста), прогон
соответствующего набора и полученный отказ. Мутация вносилась точечной
заменой, после прогона файл восстанавливался (`git checkout --`).
Скрипт: `plans/features/epic-cm-visual-01/evidence/cmv-a/mutations.py`
(локальный, не входит в набор приёмки — воспроизводимость важнее файла).

| № | Мутация (что сломано) | Файл | Набор | Отказ |
|---|---|---|---|---|
| M1 | снят single-flight guard `if (!scene || scene.raf != null) return false;` | `web/app.js` | `tests/js/evol_cog_scene_test.js` | `AssertionError: RAF: второй кадр не дублируется` |
| M2 | `destroyCognitionGraph` не отключает `ResizeObserver` (`scene.ro.disconnect()` удалён) | `web/app.js` | `tests/js/evol_cog_scene_test.js` | `AssertionError: цикл 0: один ResizeObserver на карту` |
| M3 | `_cogApplyFit` использует `net.fit(anim)` вместо `moveTo` по формуле | `web/app.js` | `tests/js/evol_cog_scene_test.js` | `AssertionError: resize: первый кадр — один moveTo` |
| M4 | `nodeRow` пишет в исходный узел (`node.title = ''`) | `web/static/cog-visual.js` | `tests/js/evol_cog_visual_test.js` | `TypeError: Cannot assign to read only property 'title'` (модель заморожена тестом) |
| M5 | `_cogApplyData` не пересчитывает `fitScaleRef` после смены набора | `web/app.js` | `tests/js/evol_cog_scene_test.js` | `AssertionError: данные: fitScaleRef известен после обновления` |
| M6 | `_cogCameraOf` зажимает масштаб обзора к `0.15` (старое поведение адаптера) | `web/app.js` | `tests/js/evol_cog_scene_test.js` | `AssertionError: камера: масштаб обзора не зажимается к 0.15` |

Итог: `MUTATION-HOLES=0` — ни одна мутация не прошла незамеченной.

Отдельно: живой счётчик (§10.2) дискриминирует не «зелёность», а числа —
`cmv-a-scene-counters.json` (CMV-A) и `cmv-a-scene-counters-before.json`
(`9e238d06`) сняты одним и тем же инструментом на одном и том же стенде.
