# Review fix B02 — fresh-lane backoff/row_limit durable между job'ами

Стабильный ID ревью: **B02** (blocking). Scope не расширялся:
`services/mca_experience_jobs.py` + тесты + evidence. DDL/ACL/UI/embedding,
`progress_scope.json`, `workflow_state.md` не изменялись.

- RED candidate: `1df6fff1668882af187e0564c64d159498b56235`
- Fix commit: `161a1705973bf6b5f31001b57a9a2728300f5945`
- Branch: `fix/exp-e-trunc-lag`
- Diff fix: `services/mca_experience_jobs.py` **+48/−1**;
  `tests/test_exp_e_trunc_lag_amendment.py` **+137** (2 теста).

## Причина

`_defer_semantic_fresh_lane` писал в `semantic_fresh[chat]`
`attempts/retry_at/row_limit/reason`, но новый job наследовал только
`boundary`/`cursor`. Дополнительно `_normalize_semantic_state` отбрасывал
`attempts`/`reason`. Fresh-батч исполняется один раз за job, поэтому при
устойчивой обрезке каждый job снова читал полное окно (50, в catch-up 120)
и снова обрезался; `row_limit=25/13` никогда не применялся.

## Исправление

- `_inherit_cursor` для fresh-полосы:
  - `boundary`/`cursor` — прежний max-merge (не теряются);
  - `attempts = max(current, prev)`;
  - `retry_at = max(current, prev)`;
  - `row_limit = min(положительных current/prev)`;
  - `reason` сохраняется (current, иначе prev);
  - это отдельное состояние; tail `semantic_retry` не смешивается и
    наследуется как раньше.
- `_normalize_semantic_state` сохраняет `attempts` и `reason` fresh-полосы
  (раньше молча отбрасывал).
- Успешная обработка по-прежнему снимает только fresh-backoff
  (`_book_semantic_fresh_window`); tail-состояние не затрагивается.

## RED (`1df6fff16`)

1. Прямое наследование: свежий job после payload с
   `row_limit=5,attempts=4,retry_at=12345` получает lane без этих полей:

```
assert lane["row_limit"] == 5
E   KeyError: 'row_limit'
```

2. Три последовательных job с устойчивой обрезкой fresh:

```
job 2: ожидалось окно 25, получено [50, 50, 50]
assert {50} == {25}
```

То есть уменьшенное окно не наследовалось, каждый job снова читал 50.

## GREEN (`161a17059`)

- Прямое наследование: `boundary=6000`, `cursor=6010`,
  `row_limit=5`, `attempts=4`, `retry_at=12345`,
  `reason=truncated_reasoning`; tail `row_limit=25,attempts=2,retry_at=999`
  не изменён.
- Три последовательных job + restart:
  - fresh окна `50 → 25 → 13 → 7`;
  - `attempts 1 → 2 → 3`, затем снимаются успехом;
  - cursor fresh стоит на отказах (6000) и двигается только валидным
    контентом (6007);
  - после успеха следующий job продолжает с cursor=6007 и **не**
    переотправляет успешно обработанные 6001–6007;
  - `retry_at` и `row_limit` сохраняются между job'ами, backoff
    учитывается.
- Merge/durability: fresh boundary/cursor не теряются; существующий
  `test_fresh_lane_merges_without_loss_or_duplicates` проходит.

Тесты:
`test_inherit_cursor_preserves_fresh_lane_backoff`,
`test_fresh_truncation_window_persists_across_jobs`.

## Проверки

- `tests/test_exp_e_trunc_lag_amendment.py`: **13 passed** (+2).
- 18 релевантных Experience/смежных файлов:
  **292 passed, 1 deselected**.
- RED `1df6fff16`: **2 failed**; GREEN `161a17059`: **13 passed**.
- `py_compile` — 0; `git diff --check` — 0;
  plan gate — `inventory=15 manual=2 scoped=0 errors=0`.
- Pre-existing `test_deep_sleep_not_mixed_with_lessons` не трогался:
  падает идентично на base `56e2450d2`.

## Осталось / RFL

Без изменений: production-спад lag/throughput не измерялся (нет деплоя),
реакция реальной модели на 8192/уменьшенные окна не проверялась,
archive re-anchor намеренно не выполнялся. Статус — `REVIEW / RFL`, не
`VERIFIED`.
