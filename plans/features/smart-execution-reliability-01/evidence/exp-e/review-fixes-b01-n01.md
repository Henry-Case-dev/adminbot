# Review fixes B01 / N01 (candidate `ece1e1ca9` → `a5049c842`)

Стабильные ID ревью: **B01** (blocking), **N01**. Scope не расширялся:
`services/mca_experience_jobs.py` + тесты + evidence. DDL/ACL/UI/embedding,
`progress_scope.json`, `workflow_state.md` не изменялись.

- RED candidate: `ece1e1ca9f6de046b2c0c4f5211e17663be88947`
- Fix commit: `a5049c8428dc0ac4aca519b10789027c8a4d5bb6`
- Branch: `fix/exp-e-trunc-lag`
- Diff fix: `services/mca_experience_jobs.py` **+21/−6**;
  `tests/test_exp_e_trunc_lag_amendment.py` **+173** (2 теста).

## B01 — tail retry state стирался успехом fresh

### Причина

`_consume_semantic_batch` вызывал `_clear_semantic_retry(payload, cid)`
безусловно для любой полосы. `semantic_retry[chat]` хранит tail
`row_limit`/`attempts`/`retry_at`; успешный fresh-батч (2–3 новых
сообщения) удалял уменьшенное окно хвоста, и следующий tail-батч снова
читал 50 строк, обрезался и заново ставил `row_limit=25, attempts=1`.
При постоянном притоке окно 25/13 никогда не применялось.

### Исправление

- fresh-успех: `_clear_semantic_retry` **не вызывается**; собственный
  fresh-backoff снимает только `_book_semantic_fresh_window` в
  `semantic_fresh[chat]`.
- tail-успех: `_clear_semantic_retry` вызывается только в tail-ветке и
  очищает только tail-состояние.
- durable `semantic_truncation`/`attempts`/`row_limit`/`next_retry_at`
  не теряются.

### RED (`ece1e1ca9`)

Детерминированный сценарий: 6000 строк, fresh-полоса, tail обрезан
(`attempts=1,row_limit=25`), далее 3 прохода с притоком по 2 сообщения и
истёкшим tail `retry_at`:

```
AssertionError: [50, 50, 50]
assert {50} == {25}
```

То есть tail снова читал 50, `attempts` не рос, уменьшенное окно
стиралось.

### GREEN (`a5049c842`)

```
tail windows: [25] -> [13] -> [7]
attempts:     1 -> 2 -> 3 -> cleared on successful 7-row batch
tail cursor:  1000 (truncated runs) -> 1007 (successful 7-row run)
fresh:        каждая порция 2 сообщений обработана в своём проходе
```

Тест: `test_fresh_success_does_not_reset_tail_truncation_state`.

## N01 — fresh ждал tail backoff

### Причина

`_semantic_fresh_batch` строил порядок через `_semantic_chat_order(...)`,
а тот пропускал чат при `semantic_retry[chat].retry_at > now`. Поэтому
новые события ждали tail backoff (до 4–6 ч), хотя fresh-полоса имеет
собственный `semantic_fresh[chat].retry_at`.

### Исправление

`_semantic_chat_order(..., respect_retry=False)` для fresh-полосы:
tail `retry_at` не фильтрует fresh; готовность fresh определяется только
`semantic_fresh[chat].retry_at`. Tail продолжает ждать свой backoff.

### RED (`ece1e1ca9`)

После restart, при `tail retry_at` в будущем и 2 новых сообщениях:

```
AssertionError: fresh-полоса ошибочно ждёт tail backoff
assert False
```

Fresh-батч не исполнялся (0 новых событий), tail тоже был отложен.

### GREEN (`a5049c842`)

- после restart fresh обрабатывает 2 новых сообщения;
- tail-батчей в этом проходе нет, tail `attempts=1,row_limit=25,retry_at`
  не изменился;
- после истечения tail backoff хвост повторяет **25** (не 50), затем
  `attempts=2,row_limit=13`;
- fresh-события не потеряны и не обработаны дважды.

Тест: `test_fresh_lane_ignores_tail_backoff_across_restart`.

## Проверки

- `tests/test_exp_e_trunc_lag_amendment.py`: **11 passed** (было 9; +2).
- 18 релевантных Experience/смежных файлов:
  **290 passed, 1 deselected**.
- RED на `ece1e1ca9`: **2 failed** (оба новых теста), GREEN на
  `a5049c842`: **11 passed**.
- `py_compile` — 0; `git diff --check` — 0;
  plan gate — `inventory=15 manual=2 scoped=0 errors=0`.
- Pre-existing `test_deep_sleep_not_mixed_with_lessons` не трогался:
  падает идентично на base `56e2450d2`.

## Осталось / RFL

Без изменений: production-спад lag/throughput не измерялся (нет деплоя),
реакция реальной модели на 8192/уменьшенные окна не проверялась,
archive re-anchor намеренно не выполнялся. Статус — `REVIEW / RFL`, не
`VERIFIED`.
