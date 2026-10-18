# INIT-ARCH-FIX — сводка реализации (на независимое ревью)

Лейн: **INIT-ARCH-FIX** (writer). Прод не трогался, SSH не использовался.
Изменения лейна закоммичены отдельным коммитом без пуша (SHA — в отчёте
лейна); чужие незакоммиченные файлы не трогались.

Код-база: HEAD `0ef8201b` (в ходе работы HEAD сдвинулся другим лейном;
целевые файлы не менялись: `git diff --name-only ce9d17ea..HEAD --
services/initiative_observer.py services/initiative_diagnostics.py` — пусто).

Строки карты (`requirements-map-followup.json`, slice `P0B-INIT-ARCH`):
`P0B-INIT-BACKFILL` (L00026), `P0B-INIT-CONTEXT` (L00023),
`P0B-INIT-CATCHUP` (L00022), `P0B-INIT-SIGNALS` (L00024),
`P0B-INIT-SMALL` (L00025). Смежные TAIL/DURABLE/DIRECT не изменялись —
защищены регрессионными швами ниже.

## Файлы и sha256¹⁶

| Файл | было | стало |
|---|---|---|
| `services/initiative_observer.py` | `eef7feec36aca94f` | `210c7516ed53c7fa` |
| `services/initiative_diagnostics.py` | `0391fc582f602398` | `3d7d0d6a31d318b4` |
| `tests/test_p0_init_arch_fix_observer.py` (новый) | — | `c6bc32cc27af9f2e` |

`git status` до коммита: `M services/initiative_observer.py`, `M
services/initiative_diagnostics.py`, `?? tests/test_p0_init_arch_fix_observer.py`
и evidence-каталог; в коммит лейна входят ровно эти пути
(+ `evidence/init-arch-gap.md` от gap-лейна).

## RED → GREEN (тест-файл `tests/test_p0_init_arch_fix_observer.py`)

* **RED (pre-fix): 12 failed / 5 passed** на ФИНАЛЬНОМ 17-тестовом файле —
  `red-prefix.txt` (чистый worktree от HEAD `473b4a2a`, pre-fix
  `initiative_observer.py` `eef7feec36aca94f`; worktree удалён после прогона).
  Свидетели по пунктам: BACKFILL — `test_imported_history_is_invisible_for_observer`,
  `test_live_readers_ignore_imported_rows`; CONTEXT — `test_adaptive_window_resolver_has_base_and_explicit_cap`,
  `test_eval_window_is_adaptive_by_volume[60-60]`, `[300-200]`;
  CATCHUP — `test_large_watermark_gap_is_digested_not_sequentially_evaluated`,
  `test_digest_failure_is_fail_open_to_actual_window`;
  SIGNALS — `test_reply_links_and_addressee_reach_prompt_and_context`,
  `test_opportunity_row_parity_without_new_signals`;
  SMALL — `test_new_small_chat_normal_profile_reaches_full_opportunity[6]`,
  `test_required_messages_never_below_quality_floor`,
  `test_block_state_pending_gate_uses_same_threshold` (панель показывала
  «0 из 8» вместо floor 4 — свидетель «8 vs 4»).
  (5 прошедших до фикса — осознанные паритет-контроли: 12/20 сообщений,
  малый разрыв без дайджеста, устоявшийся чат, окно 10 ≤ старых 14.)
* **GREEN (post-fix): новый файл — 17 passed; объединённый набор 9 файлов —
  135 passed / 0 failed** — `green-postfix.txt` (UTF-8, полный вывод).

## Пункты 1–5: что сделано (диффы кратко)

1. **BACKFILL (gap, L00026).** `LIVE_ONLY_SQL = "import_key IS NULL"` во всех
   11 чтениях `smart_messages`: `_fresh_anchor_id` (MAX/MIN), `_scan_phase`,
   `_window_rows`, `_live_backlog`, digest probe/sample, `recent_message_rate`,
   `live_messages`, `_cursor_lag`, `required_messages_for_chat`.
   Тест: 300 импортированных «многолетних» реплик → `observed=0`, `evals=0`,
   `llm.calls=0`, `pending=0`, архив цел (306 строк); живые новые сообщения —
   работают (`llm.calls=1`, окно содержит живые реплики, импорт — нет).
2. **CONTEXT (gap, L00023).** Удалена жёсткая `EVAL_WINDOW_MESSAGES=14`;
   `EVAL_WINDOW_BASE_MESSAGES=10`, `EVAL_WINDOW_MAX_MESSAGES=200`,
   `resolve_window_messages(backlog)` + `InitiativeObserverRunner._window_messages`.
   Диагностика dry-run использует тот же резолвер (`limit` в trace).
   Тесты: 10/60/300 сообщений → окно 10/60/200 (кап); unit-кейсы резолвера.
3. **CATCHUP (partial, L00022).** `_catchup_digest(...)`: bounded-probe
   (≤1000), выборка ≤200, ОДИН LLM-стрим (step `skipped_digest`), статистика
   (пропущено/участники/период UTC) + резюме, блок `<Skipped_Chat_Digest>` ≤800
   симв. в промпте оценки; fail-open при недоступности LLM; триггер только
   при watermark>0 и разрыве ≥50. Тесты: 1000 пропущенных → ровно 2 LLM-стрима
   (дайджест+оценка), выборка bounded (ранняя часть за капом не в дайджесте);
   падение дайджеста → оценка не сломана; малый разрыв → дайджеста нет.
   Реализация признана соразмерной — альтернатива из брифа («задокументировать
   bounded-окно вместо дайджеста») не выбиралась; обоснование —
   `design-decisions.md` §2.
4. **SIGNALS (partial, L00024).** Промпт окна размечен `[msg:ID]` и
   `(ответ на msg:N)` (reply-связи) + пояснение разметки в system-промпте;
   `addressee_user_id` и `rationale` вердикта едут в `opportunity_row` (к
   Writer/L1), паритет без них сохранён; dry-run диагностики передаёт те же
   поля. Тест: reply-цепочка видна в промпте; writer-строка содержит адресата
   и rationale; контракт «без полей — строка не меняется».
5. **SMALL (partial, L00025).** `required_messages_for_chat(db, chat_id, need)`
   = `min(need, max(floor 4, depth))`; применён в `_evaluate_phase` (оба порога)
   и в воротах `chat_block_state` (панель показывает тот же порог).
   Тесты: 6/12/20 сообщений на заводском `normal` → полноценная цепочка
   (eval → Writer → sent=1, `not_enough=0`); 3 реплики → floor 4;
   устоявшийся чат ждёт порог профиля (паритет качества); панель 4/8.

## Регрессионные швы (post-fix)

`green-postfix.txt`: 9 файлов, **135 passed / 0 failed** (exit=0, после
гигиены сессии): новый файл 17, p0-initfix 10, **b01 13**, W5-gates 17,
**vitality 18**, f6-initiative 23, webapp memory-overview 7, b11-report 17,
memory_maintenance 13. Набор прогонялся 3× после правки — стабильно 135 passed.

Сессионный флейк (найден и устранён вклад лейна): в одном из объединённых
прогонов упал предсуществующий `p0-initfix`-тест — модульный singleton
`mca_random_source` оставался связанным с закрытой БД предыдущего файла и
probability-draw откладывал инициативу (`random_fallback`). Механизм, проба
RED→GREEN и минимальная правка (reset singleton в фикстуре нового файла) —
`flake-p0-random-source.md`; вклад других файлов/сервиса — предсуществующий,
вне объёма лейна.

Предсуществующее наблюдение: файл b01 печатает `closed 1 leaked aiosqlite
connection(s)` — проверено на HEAD-базлайне в отдельном worktree
(`git worktree`, удалён), утечка есть и без правок лейна → `unrelated/pre-existing`.

## Остатки / честные границы

* Дайджест покрывает ≤200 свежих реплик разрыва; более ранняя часть при
  разрыве > капа остаётся за границей сжатия (осознанный кап; см.
  design-decisions §2).
* Порог дайджеста 50 реплик: разрыв 1–49 при `backlog > 200` не сжимается
  (окно-кап остаётся формой сжатия для малого остатка).
* Живые/продуктовые проверки прод-поведения (реальные чаты, воронки) —
  следующий деплой-цикл (вне объёма лейна: прод не трогался).
* Перф: при массовых импортах фильтр `import_key IS NULL` без выделенного
  частичного индекса (DDL вне объёма; зафиксировано в design-decisions §4).
* `candidate.source_refs` в ephemeral-ветке не добавлен: refs уже в
  `opportunity_row.source_refs`; изменение формы decision-кандидата не
  требовалось брифом (incidental, `related-nonblocking`).
* Предсуществующая сессионная особенность `mca_random_source` внутри самого
  p0-файла (его первый send-тест привязывает singleton, следующий работает с
  закрытой БД; собственные ассерты этого не замечают) — вне объёма
  INIT-ARCH-FIX, задокументировано в `flake-p0-random-source.md`.

## Воспроизводимость

```
py -3 -m pytest tests/test_p0_init_arch_fix_observer.py -q
py -3 -m pytest tests/test_p0_initfix_initiative_observer.py \
  tests/test_asap8_v63_b01_initiative_observer.py \
  tests/test_soul1_w5_observer_gates.py tests/test_soul1_w5_initiative_vitality.py \
  tests/test_asap8_f6_initiative.py tests/test_webapp_memory_overview_api.py \
  tests/test_asap8_v63_b11_report.py tests/test_memory_maintenance.py -q
```

## Таймлайн (UTC, факты лейна)

Прод не изменялся; локальные прогоны и хэши — 2026-10-19 (локальное время
сессии), HEAD на старте лейна `0ef8201b`; RED-прогон — worktree `473b4a2a`.
