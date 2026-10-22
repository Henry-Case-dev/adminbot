# FIX-SUMMARY-FACTVIEW — diag FIND-2 fix (v2 anchor-map FactView)

Дата: 2026-10-23. Лейн: FIX-SUMMARY-FACTVIEW (mode writer).
Диагноз-источник: `plans/features/asap-speech-arch/evidence/summary-degraded-diag.md`
(run 718e9ea6, прод-сигнатура `coverage=0.0 / considered=0` в 4/5 прогонов 2.58.110/111).

## Суть фикса (маршрут diag §6: 1 + 2 + 3-related)

1. **v2-понимание FactView** (`services/summary_fact_view.py`):
   `build_fact_view_from_map` получил kwarg `anchor_map`; карта v2
   (AnchorSpace: `source_anchors` в темах, `unassigned_anchors` top-level)
   материализуется через `anchor_map.to_real_ids` (checksum-валидный
   биекция-маппинг прогона — тот же `SourceAnchorMap`, что у L1/L2).
   Генератор передаёт `exec_input.anchor_map` (единый preparation path с
   prod-каноном `summary_execution_input`).
2. **Fail-closed пустого view**: v2-карта без `anchor_map` →
   `not_built/anchor_map_unavailable`; 0 материализованных id из непустой
   карты (любая версия) → `not_built/no_materialized_ids` + лог
   `FACT_VIEW_EMPTY`. Никогда больше «ok» с пустым пакетом → генератор
   уходит в существующую defensive-ветку fallback-пакета (полный материал
   окна), Writer работает от полного окна как раньше.
3. **Coverage-гвард** (`services/summary_generator.py::_apply_package_coverage`,
   до этого — inline-блок): при `writer_source` пакет с нулевым материалом
   (considered==0) НЕ перезаписывает честные writer_source-100% (T-4608);
   пишется `L2_PACKAGE_COVERAGE_SKIP_EMPTY`. Перезапись пакетом с
   материалом — без изменений (честные потери окна видны как раньше).
4. **Честный статус прерванного прогона** (related): `except
   asyncio.CancelledError` в `_run` → ctx.fail (SUMMARY_FAILED вместо
   SUMMARY_COMPLETE status=ok при публикации «-»); отмена пробрасывается.
   Причина уже-failed контекста НЕ затирается: штатный shutdown-дренаж
   (INC-SUMMARY-01 `abort_in_flight`, reason=shutdown) сохраняет свой
   reason_code в терминале — контракт-тест shutdown зелёный.

Δ-файлы: `services/summary_fact_view.py`, `services/summary_generator.py`
(карты requirements не тронуты — W3-лейн; биндинг потом). Прод 2.58.111
не менялся; фикс едет поездом 2.58.112 после ревью.

## Тесты: RED → GREEN

Новый REGRESSION-сьют `tests/test_summary_fact_view_v2_anchors.py`
(TEST-LIFECYCLE: REGRESSION owner=FIND-2/summary-factview; моки, 0 платных):

| # | Тест | RED на HEAD | GREEN с фиксом |
|---|------|-------------|----------------|
| 1 | v2-anchor map → непустой view, fragments materialized, coverage 100 | FAILED | PASSED |
| 2 | v2-карта, unassigned_anchors → materialize + coverage 100 | FAILED | PASSED |
| 3 | v2 без anchor_map → not_built/anchor_map_unavailable | FAILED | PASSED |
| 4 | непустая карта без материализованных id → not_built/no_materialized_ids | FAILED | PASSED |
| 5 | coverage-гвард: пустой пакет не трогает writer_source-100 | FAILED | PASSED |
| 6 | coverage-гвард: пакет с материалом честно перезаписывает (20.0) | FAILED | PASSED |
| 7 | offline-replay сигнатуры 718e9ea6 (anchor_mode=true, WHOLE_WINDOW, writer_source): **RED = точная прод-сигнатура `assert 0.0 == 100.0`** | FAILED (0.0) | PASSED (100.0, L1_STAGE anchor_mode=true, package_grade=semantic, публикация состоялась) |
| 8 | прерванный отменой прогон → ctx failed / reason=interrupted (не ok) | FAILED | PASSED |

RED-прогон: `py -3 -m pytest tests/test_summary_fact_view_v2_anchors.py`
на HEAD (правки сервисов в stash) — 8 failed; ключевой вывод replay:
`AssertionError: assert 0.0 == 100.0 … source_coverage` — прод-дефект
воспроизведён офлайн. GREEN после возврата фикса — 8 passed.

## Существующие сьюты (venv, py -3, все зелёные с фиксом)

- Целевой набор (18 файлов summary-домена: writer_source, semantic_map,
  source_anchors_asap42, wave8_golden/ladder/off_parity, fact_package,
  incident_empty_package, l1_clusterizer, l2_integration, reviewer_source,
  execution_input, logging_runid, inc01_shutdown, source_window, legacy
  source_window, test_run): **428 passed, 0 failed**.
- py_compile обоих файлов — OK.

## Pre-existing фейлы вне диффа (stash-верифицированы на HEAD, байт-в-байт)

- `tests/test_summary_asap2_failsoft_round1027.py::test_t3959_10_…` —
  rich-delivery мок (падает и без фикса; unrelated/pre-existing).
- `tests/test_summary_publish_integration_round1026.py::…::
  test_on_l1_not_usable_level2_l2_publishes_article` — падает и без фикса
  (unrelated/pre-existing).

Классификация: `unrelated/pre-existing`, фиксацию — владельцу соответствующих
леинов; настоящий дифф их не трогает.

## Контракты, сохранённые сознательно

- shutdown-дренаж INC-SUMMARY-01: терминальный `reason_code=shutdown` не
  затирается (тесты `test_summary_inc01_shutdown.py` — 22 passed вместе с
  новым сьютом).
- v1-путь FactView байт-совместим для валидных карт (все фикстуры
  `test_summary_writer_source_asap41.py` зелёные).
- R17: новые лог-коды — counts/enum (`FACT_VIEW_EMPTY`, `L2_PACKAGE_COVERAGE_
  SKIP_EMPTY`, `SUMMARY_INTERRUPTED`), без контента.
