# REV-FACTVIEW-B1 — речек блокера B-1, кандидат 10f3a2a0 (поверх 138330c0)

Дата: 2026-10-23. Лейн REV-FACTVIEW-B1 (read-only). Предмет: **только** блокер B-1 из
`review-factview.md`; остальные доказательства лейна FIND-2 переиспользованы (дифф их не касается).

## Вердикт: Approved (B-1 закрыт)

## 1. Дифф-скоуп — в границах

`git show --numstat 10f3a2a0`:

| файл | + | - |
|---|---|---|
| `services/summary_generator.py` | 7 | 3 |
| `tests/test_summary_fact_view_v2_anchors.py` | 39 | 0 |
| `plans/features/asap-speech-arch/evidence/summary-factview-fix/fix-evidence.md` | 17 | 0 |

В генераторе изменён ровно блок `except asyncio.CancelledError` в `_run` (расширено условие,
комментарий); `raise` не тронут. Чужой код, карты, прод/SSH не затронуты.

## 2. Механика фикса подтверждена по коду

- `publish_status="ok"` ставится **только после успешной отправки**: summary_generator.py:3085,
  3124, 3652, 3974 — и до `await _record_published_output` (3090/3130/3669) и `_final_policy`
  (2204). Окно «отмена после публикации» реально существует.
- `RunContext.status` default `STATUS_OK`, `publish_status` default `None`
  (summary_run_log.py:158,180) — прежнее условие `ctx.status != STATUS_FAILED` ложно
  переписывало опубликованный ран в failed.
- Новое условие: `ctx.status != STATUS_FAILED and publish_status != "ok"`; отмена всегда
  пробрасывается (`raise` сохраняется) — CancelledError не глотается.
- Влияние на терминал в БД: `_durable_run_finish` → `terminal_state_for_run(status, health,
  published)`; при `status="failed"` → `FAILED` + `fail_publication` (перезапись
  publication_status), при `ok`+published → `DONE` (summary_run_store.py:431-442). То есть фикс
  меняет не только in-memory поле, а фактический durable-терминал и не портит
  publication_status.
- `abort_in_flight` (summary_generator.py:591) уже имел такой же guard — паритет соблюдён.

## 3. RED → GREEN воспроизведён независимо

База: `git worktree add C:\Users\main\AppData\Local\Temp\opencode\b1-red-138330c0 138330c0 --detach`,
в неё скопирован **только** новый тест.

```
.venv\Scripts\python.exe -m pytest tests/test_summary_fact_view_v2_anchors.py -q -k published_run_cancel
-> 1 failed, 8 deselected
   E  AssertionError: assert 'failed' != 'failed'
   W  SUMMARY_INTERRUPTED ... терминал failed
   W  SUMMARY_FAILED ... stage=run ... reason=interrupted
```

Кандидат (worktree 10f3a2a0), тот же файл:

```
-> 9 passed in 4.49s
```

Совпадает с заявленным в evidence RED (`assert 'failed' != 'failed'`). Оба worktree удалены
(`git worktree remove --force` + `git worktree prune`); рабочее дерево репозитория не менялось.

## 4. Прогоны (venv py3.12, `-p no:cacheprovider`, cwd = worktree 10f3a2a0)

| прогон | результат |
|---|---|
| `tests/test_summary_fact_view_v2_anchors.py` | **9 passed** |
| `tests/test_summary_inc01_shutdown.py` | **14 passed** |
| `tests/test_summary_asap2_failsoft_round1027.py` | **8 passed** |
| `tests/test_summary_publish_integration_round1026.py` | **72 passed** |
| все 4 файла вместе | **103 passed, 0 failed** (56.47s) |
| `fact_view_v2_anchors` + `inc01_shutdown` вместе | **23 passed** (8.05s) |
| `py_compile services/summary_generator.py` | exit 0 |

Файлы `failsoft_round1027` и `publish_integration_round1026`, помеченные в evidence как
«pre-existing падающие», на кандидате зелёные изолированно и в общем прогоне — классификация
`unrelated` не мешает.

## 5. Контрпримеры (одноразовый probe вне репозитория, копия сетапа теста)

| сценарий | статус | reason | durable_terminal |
|---|---|---|---|
| published (`publish_status="ok"`) + cancel | ok | None | **DONE** (требование B-1) |
| `publish_status="failed"` + cancel | failed | interrupted | FAILED |
| без публикации + cancel | failed | interrupted | FAILED |
| published, но ран уже был помечен failed до отмены | failed | earlier_failure | FAILED |

Итог: опубликованный ран больше не переписывается в failed; для непубликованных/неуспешных
ранов терминал остаётся честным failed/interrupted, отмена пробрасывается. Ложноположительных
«ok» нет (publish_status="ok" ставится только после реальной отправки). Сценарий «published +
ранее уже failed» — сознательный приоритет уже-терминального контекста; в проде недостижим:
`ctx.fail` в hybrid-пути встречается только в `_legacy_fallback` после недоставки (2242/2249).

## 6. Замечание ревьюера про «428 passed» — НЕ исправлено (non-blocking)

- fix-evidence.md:65 по-прежнему утверждает «целевой набор 18 файлов … **428 passed, 0 failed**»,
  состав задан именами без точных путей; независимо этот набор я не воспроизводил (вне скоупа
  B-1), зафиксированный факт ревьюера — 423 на его составе 18 файлов.
- fix-evidence.md:99-100 «inc01_shutdown — **22 passed вместе с новым сьютом**» устарело: с 9-м
  тестом фактически **23** (проверено прогоном выше).
- Обе неточности документарные, поведение не затрагивают → non-blocking; поправить при
  следующей правке evidence.

## 7. Биндинг

- Кандидат: git `10f3a2a0` (родитель `138330c0`), ancestor master.
- `git diff 10f3a2a0 HEAD -- services/summary_generator.py services/summary_fact_view.py
  services/summary_run_log.py tests/test_summary_fact_view_v2_anchors.py .../fix-evidence.md` —
  **пусто**: содержимое затронутых файлов на master (f7156fee) идентично кандидату.
- Одобрение действительно для поезда 2.58.112 при условии, что поверх не появятся изменения
  этих файлов; иначе повторить: новый тест + факт-view сьют + `test_summary_inc01_shutdown.py`.

## Блокеры

Нет.