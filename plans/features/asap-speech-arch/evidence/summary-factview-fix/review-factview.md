# REVIEW-SUMMARY-FACTVIEW — кандидат 138330c0 (поверх ec359bb3; прод 2.58.111 не тронут)

Дата: 2026-10-23. Лейн: REV-SUMMARY-FACTVIEW (read-only). Режим: независимое ревью фикса FIND-2
(diag: plans/features/asap-speech-arch/evidence/summary-degraded-diag.md).

## Вердикт: Needs Fixes (1 блокер, однострочный)

## Проверено (независимо, на кандидате 138330c0)

1. **Дифф-скоуп** — ровно 5 файлов: summary_fact_view.py, summary_generator.py, новый
   REGRESSION-тест, evidence, backlog. Чужой домен не задет. Рабочее дерево = кандидат
   (модификации только в plans/*.md, вне кода).
2. **Корень** — `build_fact_view_from_map` реально читает v2 (`source_anchors`/
   `unassigned_anchors`) через `anchor_map.to_real_ids` (parse → membership → re-checksum,
   тот же self-validating SourceAnchorMap, что L1/L2; валидация НЕ ослаблена — доп. фильтр
   `mid in items` по окну сохранён). Генератор передаёт `exec_input.anchor_map` (тот же
   preparation-path, `resolve_anchor_map(window, run_id)` — резолв прогона).
3. **Fail-closed** — v2 без anchor_map → not_built/anchor_map_unavailable; 0 материализованных
   id из непустой карты (v1 и v2) → not_built/no_materialized_ids + FACT_VIEW_EMPTY; «ok» с
   пустым пакетом более невозможен. Генератор: неделиверабельный view → build_fallback_package
   (полный материал окна, fallback_used=True). Coverage-гвард `_apply_package_coverage`:
   considered==0 при writer_source не перезаписывает 100% (L2_PACKAGE_COVERAGE_SKIP_EMPTY),
   непустой пакет перезаписывает честно — оба направления протестированы.
4. **Тесты** — RED подтверждён независимо: временный worktree ec359bb3 + новый тест-файл →
   8 failed, replay падает РОВНО прод-сигнатурой `assert 0.0 == 100.0`, zero-material карта
   давала `'ok'`; worktree удалён. GREEN: 8 passed. Целевой набор 18 summary-файлов:
   423 passed / 0 failed (в evidence 428 — разница состава набора, не падения).
5. **Риски** — v1-путь байт-совместим (writer_source-сьют зелёный); чужие id непротащимы
   (checksum + оконный фильтр); to_real_ids — O(n) dict-lookup'ов, для 566 сообщений
   незначимо; py_compile/импорт — OK. Privacy: R17-коды без контента, секретов в диффе 0.

## Блокер (RELATED_SMALL, один файл, одна строка + тест)

**B-1: опубликованный ран, отменённый после публикации, переписывается в SUMMARY_FAILED.**
`abort_in_flight` (summary_generator.py:591) сознательно НЕ метит опубликованные раны
(инвариант INC-SUMMARY-01 «опубликованный ран в FAILED не переписываем»), но новый blanket-
обработчик `except asyncio.CancelledError` в `_run` (:977) проверяет только
`ctx.status != STATUS_FAILED`, а `RunContext.status` по умолчанию STATUS_OK (summary_run_log.py:180)
— после `publish_status="ok"` в задаче остаются await'ы (`_record_published_output` :3086,
`_final_policy` :2730) → cancel в этом окне даёт ctx.fail(reason="interrupted") → честная
публикация получает лживый failed-терминал (зеркало того дефекта честности, что чинит лейн).
Минимальный фикс: в условие добавить `and str(getattr(ctx, "publish_status", "") or "") != "ok"`.
Речек: один тест (published-ран + cancel → терминал ok, publish_status не тронут) + inc01_shutdown.

## Замечания non-blocking

- «2 пре-существующих падения» (failsoft_round1027, publish_integration_round1026) на
  кандидате в скоуп-прогонах НЕ воспроизводятся (80 и 88 passed изолированно и вместе с новым
  сьютом) — вероятно, full-suite order-pollution; классификация unrelated корректна (файлы
  вне диффа, зелёные).
- Счётчик «428 passed» в fix-evidence.md не байт-в-байт с моим составом 18 файлов (423) —
  зафиксировать фактический состав при ре-речеке.

## Биндинг

Кандидат: git 138330c0 (HEAD рабочего дерева). Речек после фикса: новый коммит поверх →
повторить тест B-1 + 8 тестов сьюта + inc01_shutdown; остальные доказательства (RED/GREEN,
423, fail-closed, гвард) остаются в силе, если diff фикса ограничен `_run`-обработчиком и тестом.
