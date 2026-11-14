# VMQ — проверка сохранности M1 и NEXT2 в выкаченном коде 2.58.203

Дата проверки: 2026-11-15.
Тип: **read-only аудит выкаченного дерева** (код не менялся, деплой не выполнялся,
доступа к production не было).
Срез: `vmq-onto-01` — M1 (M-01..M-03) и NEXT2 (NEXT-02/NEXT-05).
Статус: **аудит пройден, регрессии не найдено**.
Привязка требований (`VERIFIED`) — **не здесь**, её выполняет PM по своим картам.

## 1. Идентичность и родство коммитов

| Роль | Commit | Сообщение |
|---|---|---|
| Выкачено (production) | `c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5` (2.58.203) | `docs(release): 2.58.203 label test-isolation correction note` |
| Кандидат M1 | `cfec9a1a5ef5f78599529e9ee9394d28355b34eb` | `fix(vmq-m1): recheck assembly failure is not a completed rebuild (M-03)` |
| Кандидат NEXT2 | `96c8bc7279c5a83afedeb9f38724006e83eaceab` | `fix(vmq): period-only FTS section-2 alignment + NEXT-05 timings (NEXT-02 final, no pool/priority)` |
| База M1 (2.58.198) | `234776589c934024ed0e8dceba189fb9d70d3215` | — |

Подтверждение (все три — предки выкаченного коммита):

```
git merge-base --is-ancestor cfec9a1a5ef5f78599529e9ee9394d28355b34eb c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5   # YES (exit 0)
git merge-base --is-ancestor 96c8bc7279c5a83afedeb9f38724006e83eaceab c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5   # YES (exit 0)
git merge-base --is-ancestor 234776589c934024ed0e8dceba189fb9d70d3215 c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5   # YES (exit 0)
```

Код и тесты M1/NEXT2 присутствуют в дереве `c97c06e4`:
`services/mca_episodes.py`, `services/mca_episode_jobs.py`,
`services/mca_episode_prompts.py`, `services/mca_retrieval_context.py`,
`tests/test_vmq_m1_episode_contract.py`, `tests/test_memory_period_vector_leg.py`,
`tests/test_mca07_retrieval_context_round1027.py`.

## 2. Поздние SMART-дельты поверх кандидатов (точный объём)

### 2.1 M1: `git diff cfec9a1a..c97c06e4`

| Файл | Объём | Суть |
|---|---|---|
| `services/mca_episode_jobs.py` | **18 строк, 3 хунка** | S5A/W-07: `_finish` добавляет `fencing_token` к терминальной записи (только при ненулевом токене); `run()` обнуляет `self._fence` на входе и снимает токен владения после успешного `mark_running`; ветка `CancelledError` пишет `interrupted` тоже с токеном |
| `services/mca_episodes.py` | **0** | побайтно идентичен кандидату (`git diff --quiet` → identical) |
| `services/mca_episode_prompts.py` | **0** | идентичен |
| `tests/test_vmq_m1_episode_contract.py` | **0** | идентичен (тесты контракта не переписывались) |

Логика курсора/watermark, `rebuild_range`, `process_rechecks_with_status`,
`assemble_stories`, дедуп `segment_key` — **не тронуты**.

### 2.2 NEXT2: `git diff 96c8bc72..c97c06e4`

| Файл | Объём | Суть |
|---|---|---|
| `services/mca_retrieval_context.py` | **23 строки** | SXR-C2 (`9b64f2c3`): удалён локальный `_truncate_preview`; 7 конструкторов кандидатов (`_message_candidate`, `_fact_candidate`, `_fact_meta_candidate`, `_chain_candidate`, `_entity_candidate`, `_community_candidate`, `_episode_candidates`) отдают полный текст источника; `_PREVIEW_MAX_CHARS = 400` **сохранён** и документирован как граница UI-сниппета |
| `tests/test_caps_tool_results.py` | +57 (коммит `9b64f2c3`) | собственные тесты SXR-C2 (полные фрагменты в `get_user_context`) |
| `tests/test_memory_period_vector_leg.py` | **0** | не менялся после кандидата |
| `tests/test_mca07_retrieval_context_round1027.py` | **0** | не менялся |

Символы NEXT-02/NEXT-05 (period-only FTS section-2, тайминги) в дельте
отсутствуют: `_period_fts_keywords`, `_period_marked`, `_period_add_ms`,
`_period_ms_of`, поля `fts_ms`/`knn_ms` — не затронуты.

## 3. Прогоны на точном дереве `c97c06e4`

Условия: cwd = worktree на `c97c06e4`
(`…\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-6fc68e04`),
интерпретатор `C:\Code\Python\adminbot\.venv\Scripts\python.exe`,
`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider` (байткод и pytest-кэш в дерево не пишутся).

| № | Команда | Итог |
|---|---|---|
| 1 | `pytest tests/test_vmq_m1_episode_contract.py -q` | **34 passed** (11.32 c) |
| 2 | `pytest tests/test_memory_period_vector_leg.py -q` | **30 passed** (8.91 c) |
| 3 | `pytest tests/test_mca05_episodes_stories_round1027.py tests/test_evol021_episode_semantics.py tests/test_asap8_f7_stories.py tests/test_asap8_v63_b08_stories.py tests/test_mca12_stories_round1046.py tests/test_vmq_m1_episode_contract.py -q` | **161 passed** (38.62 c) |
| 4 | `pytest tests/test_memory_contracts.py tests/test_graphrag_memory.py tests/test_mca17_sleep_memory_workers_round1050.py tests/test_memory_health.py -q` | **295 passed** (29.26 c) |
| 5 | `pytest tests/test_memory_period_vector_leg.py tests/test_mem_time_policy.py tests/test_memory_unified_retrieval_06.py tests/test_mca07_retrieval_context_round1027.py tests/test_memory_core_round1020.py tests/test_asap8_v63_b03_memory.py tests/test_graphrag_memory.py tests/test_memory_lookup_round1026.py -q` | **447 passed** (36.75 c) |
| 6 | `pytest tests/test_caps_tool_results.py -q` | **20 passed** (5.86 c) |
| K | `pytest tests/test_direct_fallback_recompose_asap32.py -q` (контроль) | **5 failed / 3 passed** (18.97 c) |

Все утверждённые ранее суммы воспроизведены ровно: 34 / 30 / 161 / 295 / 447 и 20.

Контрольные падения — **известные pre-existing**, не связанные с VMQ:
те же 5 имён присутствуют в записанном списке мастера
`plans/features/smart-execution-reliability-01/evidence/fc-evidence/raw/pytest-pre-existing-master.txt`;
причина `TypeError: …fb_retries() got an unexpected keyword argument 'sent'`
в `services/llm_client.py`.

Проверено, что импортировался именно выкаченный код: `services.mca_retrieval_context.__file__`
указывает в worktree `c97c06e4`, `_truncate_preview` отсутствует, `_PREVIEW_MAX_CHARS == 400`.

## 4. Взаимодействие поздних дельт с контрактами VMQ

### 4.1 Fencing в `mca_episode_jobs` не ломает M1 (pause/watermark/терминал)

- `TaskJobStore.finish` принимает `fencing_token` — несовместимости сигнатуры нет.
- Страж терминальной записи: без токена запись разрешена только из активного
  состояния (`queued`/`running`); строка с `fencing_token > 0` и
  `reason_code ∈ {worker_lost, deadline_exceeded}` не переписывается; с токеном
  запись обусловлена совпадением токена.
- Продвижение курсора не изменено: `payload["cursor_ts"]`/`["cursor_id"]`
  обновляются только после успешной порции; при `errors > 0` пишется `paused`
  **до** сдвига, поэтому watermark не перепрыгивает незавершённую порцию (M-03).
- Итог: W-07 усиливает честность терминального статуса (устаревший владелец
  после takeover не публикует `completed`) и **не меняет** семантику M1.

### 4.2 Перенос preview-cap не усекает данные для Writer/LongitudinalView

- Кандидат retrieval несёт **полный** фрагмент источника (проверено зондом:
  `full_len=933`).
- UI остаётся ограниченным 400 символами: `memory_search._snippet` →
  `memory_contracts.preview_max_chars()`; `SearchItem.snippet` валидируется тем же
  лимитом. То есть кап стал UI-границей, а не капом данных.
- Writer-путь: `direct_context_composer` для сообщений берёт сырой текст строки
  (`row_to_fragment`, `ContextFragment.text`), а `candidate.preview` использует
  только для `graph_fact`/`episode` как низкодоверенный `summary_inference` —
  там значение стало полным вместо молча срезанного 400.
- `LongitudinalView` (`mca_episodes`) `candidate.preview` не потребляет вообще.
- NEXT-02/NEXT-05 не затронуты (см. §2.2) и подтверждены прогонами 2 и 5.

## 5. Адверсариальный зонд (не pytest, отдельный скрипт)

Каталог: `C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\vmq-onto-01-3689dd92710d\probe-bc9c1876f7`
(сохранён для Reviewer; **не закрыт**).
Файлы: `probe_deployed_interaction.py`, `probe-output.txt`.
Запуск: cwd = worktree `c97c06e4`, `PYTHONPATH` = этот же worktree, temp-БД в памяти,
production не затрагивался. Итог: `ALL PROBES PASSED`, exit 0.

| Метка | Что проверялось | Наблюдение |
|---|---|---|
| A | кандидат несёт полный фрагмент, UI ограничен | `entity=message full_len=933 ui_snippet_len=400 cap=400` |
| B1 | обычный прогон backfill | `status=completed`, `fence=0` |
| B2a | takeover при ненулевом токене владения | терминальная запись устаревшего владельца подавлена: `row_status=queued`, `owner_return=completed`, `fence=3` |
| B2b | takeover у задачи, ещё не отбиравшейся takeover'ом (токен 0) | тоже подавлена (страж по `reason_code=worker_lost`): `row_status=queued`, `fence=2` |
| B3 | сбой модели после успешной порции | `status=paused`, `reason_code=model_unavailable`, курсор на конце успешной порции, `batches=1` |

## 6. Честные ограничения (что НЕ проверено)

- **Effective production-флаги не проверялись**: доступа к production в этой
  задаче не было. Вне проверки остались, в частности, `episodes_enabled`,
  `retrieval_context_enabled`, `episodes_compiler_facade_enabled`,
  `episodes_continuation_enabled`, `episodes_direct_priority_enabled` и их
  фактическая приоритетность в проде. Значения по умолчанию в исходниках не
  являются доказательством эффективного значения на сервере.
- Прогоны **локальные**; живых production-событий, реального архива и epizodов
  из прода не наблюдалось.
- Зонд использует **тестовые override**: `retrieval_context_enabled=True`,
  `episodes_compiler_facade_enabled=False`, `episodes_continuation_enabled=False`,
  `episodes_direct_priority_enabled=False` (детерминированность скрипта); это не
  претензия на production-конфигурацию.
- Набор из §3 покрывает перечисленные файлы, но **не является** полным прогоном
  репозитория.
- Паритет incremental/bounded rebuild проверен только для одинакового окна
  порций (сегмент через границу порции не склеивается — свойство существующего
  сегментатора); реальное качество/полнота production-архива не измерялись.
- `coverage["complete"]` по контракту M1 всегда `False`, поэтому «полнота
  покрытия» здесь не доказывается.
- Работа велась в worktree на `c97c06e4`; **tracked-файлы не изменялись**
  (`git status` содержал только уже существовавший до проверки untracked-файл
  `plans/features/smart-corrective-01/evidence/release-train/integration-review.md`).

## 7. Вывод

Выкаченный `c97c06e4` / 2.58.203 **сохраняет** поведение M1 (M-01..M-03) и
NEXT2 (NEXT-02/NEXT-05): поздние SMART-дельты касаются только терминального
fencing в job-раннере и переноса preview-cap в UI, не меняя контрактных свойств
VMQ. Блокирующих дефектов и регрессий не обнаружено.

Привязка `VERIFIED` по строкам требований остаётся за PM.
