# REL-258106 pins24 — все 24 py пин-теста

**868 passed / 0 failed, EXIT 0** — идентично релизам 101/102/103/104/105.

Команда: `.venv/Scripts/python.exe -m pytest <24 py-пин-файла> -q -p no:cacheprovider`
(полный вывод — scratch `pkg-106/pins24-full.txt`).

Набор = PY_PINS из `OPENCODE_WORKFLOW_SCRATCH/pkg-106/bump_258106.py`
(SET EQUAL proc-105, офлайн-агрегат `delta-vs-105.txt`: ref(105) 31 == bump(106) 31).
