# PKG-SU pins24 (24 py pin-файла целиком) — 20.10.2026

Команда: `.venv\Scripts\python.exe -m pytest <24 pin-файлов> -q` (полный лог — scratch `pkg-su/pins24-full.txt`).

## Результат

- **Рабочее дерево (bump применён поверх HEAD 532a2d24 + чужие dirty-файлы): 867 passed / 1 failed**, EXIT=1, 64.78s.
- Единственное падение: `tests/test_mca17c_invariants_round1047.py::test_reason_280_single_delta` (строка 36: `assert len(mca_events.REASON_CODES) == 301`).

## Корень падения — FOREIGN (лейн 06G.3, фактчек), НЕ бамп

- `services/mca_events.py` — **незакоммиченная** правка параллельного лейна 06G.3:
  диф +4 строки, добавлен reason-код `attribution_not_found` («расширение CFG-06 06G.3 …»).
- Факт: working tree `REASON_CODES = 302`; HEAD (`git show HEAD:services/mca_events.py`) = **301**; пин ассертит 301.
- Файл `services/mca_events.py` **не входит в 31-файловый бамп-набор** и по брифу PKG-SU не трогается
  (factcheck/06G.3-файлы запрещены; дизъюнктность assert'ится в offline-агрегате — PASS).
- Прецедент PKG-99: идентичная ситуация (тогда foreign-корнем была незакоммиченная samples-ux v37,
  пин 36 оставлен, пересанкцию сделала samples-ux при приземлении). Здесь пересанкция 301→302 —
  обязанность лейна 06G.3 при приземлении его правки. Санкционировать пином чужую незакоммиченную
  правку нельзя: в закоммиченном пакете (без mca_events.py) такой пин стал бы красным.

## Доказательство зелёности на чистой линии кандидата

- `git worktree add` (detach HEAD 532a2d24 = кодовая линия 27b1165a + ledger-docs) →
  `pytest tests/test_mca17c_invariants_round1047.py -q` → **8 passed, EXIT=0** —
  включая `test_reason_280_single_delta` (301) и `test_no_ddl_catalog_ks_tools_delta` (user_version 37).
- Worktree удалён после прогона (параллельный райтер 06G.3 не затронут, stash не использовался).

## Остальные 23 пин-файла

Зелёные в рабочем дереве (входят в 867p): версию 2.58.100 пины подхватили, инвариант
`len(fields(Settings)) == 461` не менялся (config/settings.py кроме версии не правился).
