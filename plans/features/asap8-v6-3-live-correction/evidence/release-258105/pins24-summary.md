# PKG-105 pins24 (24 py pin-файла релиза) — 21.10.2026

Команда: `.venv\Scripts\python.exe -m pytest <24 pin-файлов> -q`
(полный лог — scratch `pkg-105/pins24-full.txt`).

## Результат

- **868 passed / 0 failed, EXIT=0**, 65.79s — идентично базлайнам 101/102/103/104.
- Состав = procedure-104 SET EQUAL (24 файла; `test_webapp_round1026_polygon.py` — 2 пина).
- Пины до бампа `2.58.104`, после бампа `2.58.105`; факт зафиксирован офлайн-агрегатом
  (changed-line-pairs == 33, только version/HEAD-токены) и каждым pin-тестом.

## Заметка о JS-наборе (бриф PKG-105)

Новый тест `tests/js/asap8_u084d_mini_lens_binding_test.js` (6c1dea40) НЕ подхватывался
раннером `tests/test_webapp_js_unit.py` (было 38 тестов). По брифу добавлен в набор
(правка самого теста запрещена и не выполнялась): `test_js_unit_asap8_u084d_mini_lens_binding`
→ `MINI-LENS-BINDING-OK`. JS-unit sweep теперь **39 passed, EXIT=0**. Отдельно
тест также прогнан нативно: `node tests/js/asap8_u084d_mini_lens_binding_test.js` →
MINI-LENS-BINDING-OK (EXIT=0). JS-syntax sweep: files=107 bad=0
(106 в proc-104 + 1 новый тест-файл из 6c1dea40).
