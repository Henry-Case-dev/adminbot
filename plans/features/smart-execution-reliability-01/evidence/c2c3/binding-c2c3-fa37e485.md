# SMART-EXECUTION-RELIABILITY-01 · C2/C3 — binding (candidate `fa37e485`)

- Ветка: `smart/c-source`
- Base (утверждённая линия C1): `36dd6b232bf2705cc470764a7ab71451c5c49fdf`
- Кандидат: `fa37e48522ce3522943442a6e378cc2dc36eb139`
- Evidence HEAD: `26d258b3` (binding + логи; код-кандидат не менялся)
- Worktree: `...\WorkspaceData\worktrees\...\SMART-EXECUTION-RELIABILITY-01-92d1db8aefb1-1754cefe`
- Требования: SXR-C2-01, SXR-C2-02, SXR-C3-01, SXR-C3-02 (C1 не регрессирован).
- Статус: реализация + собственные проверки. **Не** Reviewer approval и **не** DONE эпика.

## 1. Что изменено

### `services/direct_context_composer.py`
| Потолок до | Где | Что теперь |
|---|---|---|
| `middle_max_messages()` = 60 (factory) | :179 | env-политика `CHAT_MIDDLE_MAX_MESSAGES`; не задана/мусор/≤0 → `0` = потолка нет. Замена другим числом не введена. |
| `select_middle(top_k=0)` → `[]` | :584 | `top_k<=0` → ВСЕ кандидаты (входной семантический порядок, хронологический ASC). |
| `compute_episode_span(max_messages=40)` | :431 | `max_messages=0` = coherent-эпизод целиком; положительное значение — явная политика окна (3:1 вокруг хита). |
| `episode_max_messages()` = 40 (factory) | :206 | env-политика `CHAT_EPISODE_MAX_MESSAGES`; не задана → `0`. |
| `collect_memory_fragments(max_fragments=10)` | :1964 | `0` = все кандидаты retrieval; явный `max_fragments` работает как раньше; соседи каждого сообщения не теряются. |

Семантический отбор сохранён: `select_middle`/retrieval по-прежнему ранжируют, а объём ограничивает только реальное окно модели в единственном аллокаторе (`allocate_selection`, `budget_tokens`). `budget_tokens=0` не режет ничего; при реальном окне работает существующее lossless-дробление/сжатие со ссылкой (`split_overflow_fragments`, `compress_fragment_with_ref`).

### `services/evidence_bundle.py`
| Потолок до | Где | Что теперь |
|---|---|---|
| `stack_summary(budget_chars=2000, max_frames=120)` | :314 | defaults `0/0` = все кадры + валидный exception; явные значения сохраняют continuation-курсор `frame:<offset>`. |
| `render_page(max_chars=4000)` + жёсткий claims ≤ 10 | :584 | default `0` = без искусственного output-бюджета: все источники, все claims, facts не срезаются. Явный `max_chars` работает как раньше с `next_offset`/`omitted_source_ids`; скрытая константа 10 удалена. |
| `render_json(max_chars=6000)` | :709 | default `0`. |
| `render_facts_text(max_chars=3000)` без continuation | :716 | default `0` = полный текст; явный лимит оставляет видимый маркер `[facts_budget_exceeded]`. |
| Bookkeeping мог выбить единственный источник из страницы | :674-692 | при явном бюджете сначала сохраняется показанный источник (без facts), затем — continuation по `next_offset`; минимальный конверт — только если сам конверт не влезает. |

### `services/response_extent.py`
| Потолок до | Где | Что теперь |
|---|---|---|
| `PLAN_MAX_FETCH_STEPS=3` (4+ ссылки → плана нет) | :730 | заводского потолка нет; явная env-политика `DIRECT_TOOL_PLAN_MAX_FETCH_STEPS` (не задана/0 → шаг каждой ссылке; N>0 → прежнее «>N → []»). |
| `search_query[:256]` | :804-810 | текст поискового шага не срезается; provider обрабатывает сам. |
| `longform_max_output_tokens` min(value, 16384) | :197 | искусственный ceiling 16384 удалён; явная операторская политика возвращается как задана. Реальный `max_output`/остаток окна остаётся за `writer_max_output_tokens`. |

### Тесты
- Новый durable-файл `tests/test_smart_exec_evidence.py` (24 теста: контракт + границы + негативы + сквозной путь).
- Обновлены два теста, которые фиксировали обратное контракту поведение:
  - `tests/test_mca23_phase2.py::test_many_urls_all_get_steps` (было «4 ссылки → плана нет»);
  - `tests/test_mca23_response_plan.py::test_env_override_not_clamped_by_artificial_ceiling` (было `== 16384`).
  Оба изменения обоснованы owner-контрактом C2/C3; ослабления проверок нет — добавлены явные границы (`max_fetch_steps=3`).

## 2. SXR-C3-01: семь шагов до финального ответа

Сквозной исполняемый тест: `tests/test_smart_exec_evidence.py::TestSevenStepDeliverySourceReader::test_document_result_reaches_payload_and_final_answer` (реальный `SourceReader` на локальном stub-провайдере + реальный `chat_with_tools`; fake-LLM строит финальный ответ **только** из дошедшего `role:tool`).

| Шаг | Код (кандидат) | Проверка |
|---|---|---|
| 1. Что получил инструмент | `services/source_reader.py:1877 run` → `:2656 _read_payload` | 200 строк, `file_total_lines=200`, `snippet` заканчивается `line_200 = 'evidence-200'`, `verified=True` |
| 2. Структурированный результат | `source_reader._payload:2785` (JSON: path/line_range/provenance/truncation) | `classify_output` → `ok`, `data.path`, `truncated=False`; сериализация > 4000 символов |
| 3. ToolResult/evidence | `services/tool_result.py:484 classify_output`, `:596 make_envelope` | envelope `status=ok`, `data.line_range=[1,200]`, `evidence_refs` содержит `source_id`, `out_chars == len(serialized)` |
| 4. tool-loop | `services/tool_loop.py:545 chat_with_tools`, `:947/:980 role:"tool"` + `tool_context_parts` | router вызван ровно один раз; сообщение `tool_call_id="call_1"` |
| 5. context composer | `services/direct_context_composer.py:1829 build_context_selection`, `:1585 allocate_selection` | фрагмент `evidence:<source_id>` сохранён целиком (`selection.memory[0].text == snippet`), `dropped==()`, composed text содержит хвостовую строку |
| 6. LLM payload | `tool_loop` payload_messages; fake-LLM `all_messages[1]` | роли `["user","assistant","tool"]`; `tool.content == serialized` байт-в-байт, длина > 4000 — повторного усечения нет |
| 7. Финальный ответ | `tool_loop` возвращает `result.content` | ответ `Итог: evidence-200` — маркер взят из `role:tool`, не из тестовой константы |

Для остальных типов инструментов (search, memory, OCR/Vision, transcript, factcheck) исполняемо проверены шаги 2–6 на их реальных формах результата: `test_all_tool_types_keep_full_result_in_payload` (5 параметров): полный результат, > 4000 символов, доходит до `role:tool` без изменений, финальный ответ использует хвостовой маркер. Шаг 1 у них — провайдерский слой (сеть/OCR/аудио) и в этом срезе не исполнялся; это честно указано ниже.

## 3. SXR-C2-02: продолжение, а не «исчерпывающая первая порция»

- SourceReader: `truncation.next_line_start`/`range_beyond_eof` (C1, не регрессировано); страницы собираются до EOF (`test_smart_c1_source_reader_limits.py::TestRangeContinuation`, зелёные).
- Evidence bundle: `page.next_offset` + `omitted_source_ids`/`truncated`; вторая страница не пересекается с первой и двигает offset (`test_page_explicit_budget_still_paginates_with_continuation`).
- Tool plan: все ссылки запроса получают шаг; первая ссылка не выдаётся за весь план (`test_fetch_step_factory_cap_removed`).
- Provenance: `SelectionProvenance` сохраняет `source_id`, `dropped/overflow_parts`, `budget_tokens`; при реальном окне — `compressed` со ссылкой на полный источник (`test_real_window_uses_existing_packing_with_reference`).
- Никакого нового LLM-этапа/перефразирования не добавлено: изменены только границы и сериализация; все проверки — существующие функции.

## 4. SXR-C3-02: повторное усечение и OFF-бюджеты

- `test_paged_result_reaches_payload_byte_identical`: уже ограниченный `render_json(max_chars=3000)` доходит до `role:tool` **байт-в-байт**, без второй политики усечения.
- `test_budget_zero_never_drops_evidence`: 39 фрагментов × ~1600 символов при `budget_tokens=0` → все сохранены, `dropped==()`.
- `test_real_window_uses_existing_packing_with_reference`: при `budget_tokens=2000` потеря видима в provenance, важный фрагмент сжат головой + `[…сокращено по бюджету; полный текст: <source_id>]`, а не выброшен молча.
- `budgets OFF` в тестах SourceReader: предикат `budget_limits_enforced` принудительно `False` (fixture) — искусственные лимиты не применяются, safety-тесты C1 остаются зелёными.
- `render_page/render_facts_text/stack_summary` при `0` не режут; при явном значении — прежняя политика с continuation/маркером.

## 5. Команды и точные результаты

```
# focused (кандидат fa37e485)
python -m pytest tests/test_smart_exec_evidence.py -q
24 passed in 3.07s                         # evidence/c2c3/pytest-focused-fa37e485.txt

# combined (кандидат fa37e485; 26 файлов, включая C1 и потребителей)
python -m pytest tests/test_smart_exec_evidence.py tests/test_smart_c1_source_reader_limits.py \
  tests/test_evidence_bundle.py tests/test_direct_context_composer_asap3.py \
  tests/test_context_policy_asap31.py tests/test_ur_context_selection.py \
  tests/test_ur_f_inspector_step1.py tests/test_mca23_phase2.py \
  tests/test_mca23_response_plan.py tests/test_direct_context_scenarios_asap3.py \
  tests/test_direct_decision_matrix_asap3.py tests/test_mca05_episodes_stories_round1027.py \
  tests/test_mca07_retrieval_context_round1027.py tests/test_asap8_f6_initiative.py \
  tests/test_asap3_hidden_limits.py tests/test_context_limits_round1019.py \
  tests/test_er08_limits_context.py tests/test_direct_chat.py \
  tests/test_rlr_length_continuation.py tests/test_ur_turn_engine.py \
  tests/test_soul1_composer_layers.py tests/test_soul1_composer_parity_off.py \
  tests/test_soul1_core_composer_integration.py tests/test_evol_source_reader.py \
  tests/test_evol_evidence_routing.py tests/test_evol_rc_accept_fixes.py -q
957 passed in 98.41s                       # evidence/c2c3/pytest-combined-fa37e485.txt
# exit 0; в stderr предупреждение pytest «closed 22 leaked aiosqlite connections» (pre-existing, тесты не падают)
```

### RED на базе `36dd6b23`
Тот же новый тест-файл в отдельном worktree на базе (`...-ec574703`):
```
12 failed, 12 passed in 5.13s              # evidence/c2c3/red-base-36dd6b23.txt
```
Падают именно снятые потолки: middle 60, episode 40, memory 10, page/claims/stack defaults, fetch ≤3, query[:256], ceiling 16384. 12 прошедших — сквозной путь и явные политики (на базе они не нарушены; C1 уже был на 36dd6b23).

### Мутация
В кандидате временно возвращён заводской top-K 60 (`mid = _env_int(..., 60, 1)`):
```
1 failed  (assert 60 == 0)                 # evidence/c2c3/mutation-middle-red.txt
git checkout -- services/direct_context_composer.py
1 passed                                   # evidence/c2c3/mutation-middle-green.txt
```
Diff мутации: `evidence/c2c3/mutation-middle.diff`.

## 6. Effective configuration (для приёмки)

| Настройка | Заводское после кандидата | Наблюдалось в тестах | Примечание |
|---|---|---|---|
| `CHAT_MIDDLE_MAX_MESSAGES` | не задана → 0 (нет потолка) | не задана: 75/75 middle; `5`: 5; `abc`/`-3`: 0 | env-only политика; settings-default 60 больше не применяется |
| `CHAT_EPISODE_MAX_MESSAGES` | не задана → 0 | не задана: весь span 50; `10`: `cap_applied` | env-only |
| `CHAT_EPISODE_MAX_COUNT` | 2 (не менялся) | — | residual cross-slice, см. §7 |
| `DIRECT_TOOL_PLAN_MAX_FETCH_STEPS` | не задана → 0 | 6 ссылок → 6 шагов; `3` → `[]` при 4 ссылках | env-only |
| `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS` | 4096 (не менялся) | `20000` → 20000; `0` → `None` | provider max_output по-прежнему в `writer_max_output_tokens` |
| `flags.budgets_enabled` (SourceReader predicate) | default ON | в тестах принудительно OFF | production effective state — после деплоя (см. §7) |

Тестовые override: `CHAT_MIDDLE_MAX_MESSAGES`, `CHAT_EPISODE_MAX_MESSAGES`, `DIRECT_TOOL_PLAN_MAX_FETCH_STEPS`, `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS` — только через `monkeypatch`; SourceReader predicate подменён на OFF фикстурой. Секретов/прод-записей нет.

## 7. Честные остатки (НЕ выданы за выполненные)

### 7.0 Сводка по требованиям — S3 сам по себе НЕ закрывает C2-01/C3-02 полностью

| Требование | Что реально сделано в этом срезе | Что осталось вне write_scope |
|---|---|---|
| SXR-C2-01 | сняты caps в 5 файлах среза (composer/evidence/response/SourceReader-линия) + проверено, что tool-loop не теряет результат | «все инструменты» требуют S2/S4/S8/S11/S13–S16: список ниже |
| SXR-C2-02 | semantic selection сохранён; continuation (line range, page next_offset, все URL плана) проверен | ничего блокирующего в срезе |
| SXR-C3-01 | исполнимый 7-шаговый тест SourceReader; шаги 2–6 для search/memory/OCR/transcript/factcheck | шаг 1 (реальный внешний вызов) для 5 типов — провайдерские тесты соответствующих срезов |
| SXR-C3-02 | символьные caps/JSON/повторное усечение/OFF-бюджет/real-window packing в 5 файлах | L1/Writer/fallback/reserves в `direct_chat_service`/`tool_loop` — S2/S4/S7/S11 |

**Вывод для PM/Reviewer:** строки карты C2-01 и части C3-02 нельзя помечать `VERIFIED` только по этому binding; нужен join с перечисленными срезами.

### 7.1 Покрытие категорий C2-01 (явно, без «всё проверено»)

| Категория owner-требования | В этом срезе | Остаток / владелец |
|---|---|---|
| результаты поиска | tool-loop отдаёт полный результат (тест `execute_web_search`, >4000 символов) | `tool_router._compact_search_candidates`/`_truncate` — S2; `source_reader:2133 max_symbols=4000` для discovery — S2/S6 |
| документы/страницы | C1: 6/2/16 и 3/1/8 удалены; line-range/paging, oversized >2 МБ, continuation | — |
| фрагменты памяти | `middle 60`, `episode 40`, `memory 10` заводские сняты в composer; порядок/соседи сохранены | `mca_retrieval` candidate caps, `direct_chat_service._MEMORY_FACT_MAX_CHARS` — S11/S4 |
| OCR/Vision | доставка структурированного результата до payload (шаги 2–6) | `mca_vision` `max_tokens=16/8`, `vision_max_bytes/pixels` — S13/владелец vision; физические пределы остаются законно |
| транскрипты | доставка до payload (шаги 2–6) | `voice_transcripts._MAX_ITEMS=3`, `youtube_transcript_engine.max_symbols` — S13/S14 |
| фактчек | доставка до payload (шаги 2–6) | `factcheck_*` `max_symbols`, `_VERBATIM_MAX_MESSAGES=40`, `_DIGEST/VERBATIM_BUDGET_CHARS`, `image ... max_chars=2000` — S13–S16 |
| длина исходных сообщений | снят срез `search_query[:256]` | `limits.chat_current_question_max_chars` (default 800), `_CORRECTION_OWN_TEXT_CAP` — `direct_chat_service`, S4/S11 |
| размер tool result | `evidence_bundle` defaults/claims/facts/stack caps сняты; повторного усечения нет | `tool_router.Truncation/_truncate` — S2 |
| суммарный объём для модели | `budget_tokens=0` не режет; при реальном окне — существующая упаковка + provenance | stage budgets/reserves в `direct_chat_service`/`auto_budget` — S4 |

### 7.2 Cross-slice (нужна правка вне write_scope S3-EVIDENCE)
1. `thread_walk_max()` = 40 (`direct_context_composer.py:189`): потребитель `DirectChatService._collect_thread_chain` → `thread_chain.collect_thread_chain` трактует `depth<=0` как «1 hop», поэтому снятие 40 требует правки этих файлов (S4/S11). В коде оставлен честный docstring-residual.
2. `episode_max_count()` = 2 (`direct_context_composer.py:216`): потребитель `direct_chat_service.py:10391` делает `stats["count"] >= max_count`; `0` = «без потолка» сломал бы отбор. Нужна правка вызова (S4/S11).
3. `services/tool_router.py`: `Truncation`/`_truncate`/`_compact_search_candidates`, счётчики результатов поиска — S2-TOOL-LOOP write scope; здесь только проверено, что tool-loop не режет пришедший результат.
4. `services/source_reader.py:2133`: discovery-каскад передаёт `search.search(..., max_symbols=4000)`; `search_aggregator._truncate` — жёсткий `text[:max_symbols]` (файл вне S3). Это остаточный искусственный срез **индекса URL** при discovery; требует S2/S6 или отдельного среза.
5. `services/search_service.py` `max_symbols`/`checkup_service` `CHECKUP_MAX_INPUT_SYMBOLS`, factcheck `max_symbols`, OCR/Vision `max_tokens`, `voice_transcripts._MAX_ITEMS=3`, `youtube_transcript_engine.max_symbols`, `image_context_memory` caps, `mca_vision` caps — принадлежат S13–S16/S8 и не менялись; в этом срезе для них исполняемо проверено только сквозное отсутствие потерь в tool-loop/payload (шаги 2–6).
6. `direct_chat_service` message-length caps, L1/Writer, section reserves и fallback-сокращения — S4/S7/S11; здесь не менялись.

### 7.3 Postdeploy-only
- Реальное effective-состояние `flags.budgets_enabled` (чатовые override/global) и фактическое отсутствие env-политик в production можно подтвердить только на деплое; локально проверен только дефолт и явные значения.
- Сквозной live-LLM payload с провайдером не выполнялся (нет права/сети в этом срезе): шаг 6 проверен на реальном `chat_with_tools` с fake-LLM, который принимает ровно тот payload, что был бы отправлен. Это не доказывает поведение конкретного провайдерского API.
- Для OCR/транскриптов/фактчека шаг 1 (реальный внешний вызов) не исполнялся; проверены их структурированные результаты на входе tool-loop.

## 8. Затронутые контракты и отсутствие регрессий C1

- C1 (`36dd6b23`) не регрессирован: `tests/test_smart_c1_source_reader_limits.py` — все тесты в combined-прогоне зелёные (26 тестов C1 + потребители).
- Safety не ослаблена: размер порции файла/бинарь/пути (`source_reader`), SSRF/секреты, DB-запросы, redaction (`evidence_bundle`) не менялись.
- Новых зависимостей/схем/таблиц/обязательных LLM-этапов нет. Инструкции LLM не квотировались.

## 9. Housekeeping
- Одноразовые probe-файлы и RED-логи: `WorkspaceData/runs/.../probe-8e73910483`; нужные артефакты скопированы в `evidence/c2c3/`, после чего run будет закрыт `run-close`.
- RED-worktree `...-ec574703` создан через `workflow_housekeeping worktree-path` и зарегистрирован `unit c2c3-evidence`; после снятия RED-лога он больше не нужен и будет закрыт `git worktree remove` (без force) + `unit-close`/`worktree`-учёт.
- Ветка не вмержена в master; деплой не выполнялся.

`C2C3_READY_FOR_REVIEW`
