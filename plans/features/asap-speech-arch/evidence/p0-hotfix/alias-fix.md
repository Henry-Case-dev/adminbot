# P0 corrective 25.10.2026 — алиасы во всём runtime (LANE ALIAS-RUNTIME-FINISH)

- Worktree: `C:\Code\Python\adminbot-wt-speech-p0`, ветка `task/speech-p0-hotfix`.
- База среза: `d1a44592` (`fix(p0): one alias cascade across
  reply/observer/background/protected paths`) — предыдущий незавершённый срез
  алиасов, зафиксированный параллельной сессией.
- Родитель коммита-кандидата: `52061e3f` (docs/evidence-коммиты после
  `d1a44592`; код алиасов не меняли).
- Коммит-кандидат: коммит ветки `task/speech-p0-hotfix` с родителем
  `52061e3f`, содержащий этот файл и перечисленные в §7 файлы (только они;
  незакоммиченные изменения других линий в worktree не включены).
- Источник требований: `plans/features/asap-speech-arch/source-owner-p0-corrective-2026-10-25.md`
  §2.1–§2.3; аудит `plans/features/asap-speech-arch/evidence/p0-hotfix/alias-audit.md`
  (D1–D8, F1–F7, §6).
- Границы: только локальный код/тесты/БД во временных каталогах pytest.
  **Не было**: SSH/прод-команд, отправок в Telegram, вызовов LLM API, записей в
  прод-БД, новых зависимостей, новых квот инструкций, массовой переписи памяти.

## 1. Что уже содержал `d1a44592` и что добавлено этим срезом

`d1a44592` закрывал F1, F2, F3, F4, F5, F6 и часть D7. Этим срезом:

1. **F7** реализован в `web/api/routes.py` + `services/summary_aliases.py`
   (R17-safe слой имени по uid в существующем `/direct/context-diagnostics`).
2. **D7** доведён: `_collision_suffix` получает Telegram username там, где ход
   его реально знает (`_turn_usernames`), fallback `#хвост` сохранён.
3. Добавлены обязательные проверки §6 аудита в `tests/test_asap3_identity_aliases.py`
   (a17–a25 + F5/F7); черновой дубль `tests/test_p0_alias_runtime_2026_10_25.py`
   удалён после переноса покрытия (дублирование тестов не нужно).
4. Осознанно переутверждён byte-freeze `ROUTES_SHA256_F11` (L-F11S-1) — новая
   диагностика аддитивная, новых endpoint'ов нет (Δ routes = 0).

## 2. F1–F7 + D7: точки и проверка

| # | Файл:строка | Что сделано | Чем проверено |
|---|---|---|---|
| F1 | `services/direct_chat_service.py:4150` (`_l1_reply_block`), вызов `:4326` | метод инстанса: имя автора цитаты = `self.aliases.resolve(uid, nickname, username)` + `[user:<id>]`; кап 400 символов сохранён | `test_a17`, `test_a25` (RED на базе) |
| F2 | `services/initiative_observer.py:658` (`_row_author`), `:681`/`:721` (eval/digest), `:823` (`observe_tick`), `:920` (runner) | optional `alias_resolver`; без резолвера вывод байт-в-байт прежний | `test_a18`, `test_a18_observer_without_resolver_keeps_author_name_bytes` |
| F3 | `services/lore_worker.py:489/494`, `:934`; `services/dream_worker.py:886`; `services/user_relations.py:352`; `services/initiative_observer.py:1365` | перед обработкой чата — `bind_turn_aliases(chat_id)` (chat override/инвалидация без рестарта); `bot.py:467-472` LiveAliasView остаётся только fallback | `test_a19`, `test_a20_startup_snapshot_not_used_for_chat_bound_paths` (RED на базе) |
| F4 | `services/direct_chat_service.py:8375/8388` (`_alias_map_block`) | одна строка-инструкция внутри существующего `<UserResolutionMap>`: актуальное имя — по user_id; нового тега нет | `test_a20_old_name_in_rag_does_not_replace_map_name` (RED на базе), `tests/test_direct_chat.py` (обновлён ожидаемый размер блока) |
| F5 | `services/database.py:3520` (миграция), `:6513` (initialize), `:10687` (`get_protected_facts(..., user_id=)`), `:10719` (`_user_source_ref_id`), `:10742` (`clear_direct_dialogue(..., target_user_id=)`), `:10787` (`forget_direct_facts(..., target_user_id=)`); `services/direct_chat_service.py:5465/7994/8104/8121` | аддитивная идемпотентная колонка `protected_facts.subject_ref_id`, `user_version` не поднимается; чтение — по `subject_ref_id` c fallback на имя; `/clear`/`/forget` принимают `target_user_id`; запрос к `mca_source_refs` совпадает со схемой (`store/entity_type/entity_id/chat_id`, как в `_person_scope_clause`) | `test_f5_*` (3 теста, RED на базе) |
| F6 | `services/summary_aliases.py:13-18`, `:175-180` | docstring/контракт больше не обещает runtime-шаг «имя из памяти»; параметр оставлен только для вызывающего с уже проверенной привязкой к uid | `test_a1_global_alias_beats_nickname_username_memory` (поведение сохранено) |
| F7 | `services/summary_aliases.py:395` (`scope_report["by_uid"]`), `web/api/routes.py:758` (`_alias_diagnostics_payload`), `:822` (использование в существующем endpoint) | R17-safe `per_uid[]` = `{user_id, alias_source: chat|global, name_present}`; значения алиасов не выходят в API/логи; новых endpoint'ов нет | `test_f7_alias_source_is_r17_safe` (RED на базе) |
| D7 | `services/direct_chat_service.py:8360/8417/8463/8469` (`usernames` → `_collision_suffix`), `:8994` (`_turn_usernames`) | при известном username суффикс `(username)`, иначе прежний `#хвост`; два одинаковых display не сливаются | `test_a21` (RED на базе), стабы в `tests/test_budget_global_toggle_round1024.py:446` и `tests/test_mca07_retrieval_context_round1027.py:808` обновлены под новый optional-параметр |

## 3. RED: новые тесты падают на коде ДО среза

Один и тот же файл `tests/test_asap3_identity_aliases.py` прогнан в отдельном
worktree на базовом коммите `272170e3` (до `d1a44592`):

```
py -3 -m pytest tests/test_asap3_identity_aliases.py -q \
  -k "a17 or a18 or a19 or a20 or a21 or a22 or a25 or f5 or f7"
```

Результат: **12 failed, 1 passed, 22 deselected**.

- Падают (RED, то есть проверка ловит именно дефект): `test_a17_...`,
  `test_a18_observer_eval_...`, `test_a19_...`,
  `test_a20_startup_snapshot_...`, `test_a20_old_name_in_rag_...`,
  `test_a21_...`, `test_a22_...`, `test_a25_...`, `test_f5_*` (3),
  `test_f7_...`.
- Единственный «зелёный» на базе — `test_a18_observer_without_resolver_keeps_author_name_bytes`:
  это parity-guard (F2 требует, чтобы без резолвера вывод оставался прежним),
  он обязан проходить до и после.

## 4. Проверки (фактические команды и результат)

1. Целевой набор:
   ```
   py -3 -m pytest tests/test_asap3_identity_aliases.py tests/test_summary_aliases.py \
     tests/test_p0_initfix_initiative_observer.py tests/test_p0_init_arch_fix_observer.py -q
   ```
   → **73 passed** (2 warnings: `pytest-timeout` не установлен — это
   предупреждения конфигурации, не ошибки).

2. Расширенный P0-набор:
   ```
   py -3 -m pytest tests -k "speech_p0 or direct_l1 or asap3_identity or summary_alias or protected or clear_forget or observer" -q
   ```
   → **285 passed**, 15465 deselected.

3. Широкий прогон (канон репозитория — `testpaths = tests` в `pytest.ini`;
   `scripts/run_offline_aggregate` в дереве отсутствует):
   ```
   py -3 -m pytest tests -q
   ```
   → **44 failed, 15697 passed, 1 skipped, 8 errors** (766 c).

   Контроль на базовом коммите `272170e3` (тот же `py -3 -m pytest tests -q`):
   **42 failed, 15664 passed, 1 skipped, 8 errors**. Пересечение множеств
   падений — 50 узлов; все они пре-существующие (prompt-dump/soul1-пины,
   summary-двойные вызовы, миграционные lock-тесты, UI e2e без браузера).

   Разница после среза: два узла, которые проходят изолированно и в составе
   своих файлов, но в полном прогоне зависят от порядка:
   `tests/test_asap_speech_i_matrix.py::test_i01_i04_i03_i09_plan_drives_form[plan_kwargs0-sent-True]`
   и
   `tests/test_mca09_intents_block_e_round1040.py::test_handle_initiative_sent_single_transport_chunks`.
   Оба проверены изолированно и вместе с новым тест-файлом — **PASS**.
   Повторный полный прогон кандидата: см. §4a.

4. Компиляция изменённых файлов:
   ```
   py -3 -m py_compile services/summary_aliases.py web/api/routes.py \
     services/direct_chat_service.py services/lore_worker.py tests/test_asap3_identity_aliases.py
   ```
   → **PY_COMPILE OK**.

5. Harness:
   ```
   py -3 probes_full/harness_probe_full.py --self-check
   ```
   → `"self_check": "PASS"`.

### 4a. Повторный полный прогон (кандидат)

Полный прогон кандидата (44 failed / 15697 passed) выполнен на чистом дереве
этого среза. Во время повторного прогона в тот же worktree начала писать
параллельная сессия (файлы `services/chat_prompts.py`, `services/direct_l1.py`,
`services/prompt_*.py`, `probes_full/harness_probe_full.py`, speech-тесты,
17:26–17:30), поэтому второй полный прогон **не атрибутируется** этому срезу и
в качестве доказательства не используется. После вмешательства повторены
целевые наборы (§4 п.1–2, п.4–5) — они остались зелёными.

## 5. Byte-freeze re-pin (осознанно, L-F11S-1)

F7 меняет `web/api/routes.py` (аддитивное поле ответа существующего endpoint,
новых endpoint'ов нет). По принятой в репозитории процедуре byte-freeze
переутверждён:

- канон: `tests/test_round1025_f8_registry.py` → `ROUTES_SHA256_F11 =
  a75a3333a2be82f0f5ac0f4cad3dd799d43cd6e6a456cd2a47add8fef9e8bf06`;
- синхронная копия: `tests/test_mca23_planned_vs_actual.py`;
- инвентарь маршрутов `f8_baseline` не менялся (Δ routes = 0), RBAC и маскировка
  секретов не менялись.

После re-pin: `tests/test_round1025_f8_registry.py::TestFrozenInvariants`,
`test_mca17c_invariants_round1047.py`, `test_mca12_stories_round1046.py`,
`test_mca23_planned_vs_actual.py`, `test_asap7_cover_preview.py`,
`test_mca10b_random_applications_block_d_round1041.py` → **71 passed**.

## 6. Честные остаточные пробелы

1. **Живой прод-payload не проверялся** в этой линии (нет SSH/прод-доступа по
   условиям задачи). Проверено: offline-юнит/интеграция, полный pytest,
   offline-harness self-check.
2. **`protected_facts.subject_ref_id`**: в репозитории нет writer'а
   per-user protected-фактов (оба существующих INSERT пишут chat-level
   `user_name IS NULL`). Колонка аддитивная и forward-compatible: строки,
   записанные с ID (импорт/будущие writer'ы), читаются после переименования;
   legacy-строки без ID честно читаются по имени. Chat-level лор не затронут.
3. **F7**: HTTP-вызов endpoint'а не поднимался; проверен чистый построитель
   payload (`_alias_diagnostics_payload`) + `scope_report` — именно там
   гарантируется R17 (отсутствие значений) и корректный слой по uid.
4. **Полный suite не зелёный**: 42 падения существуют и на базовом коммите
   (см. §4); они не относятся к алиасам и не исправлялись в этом срезе.
5. Замечено при работе: `d1a44592` зафиксирован параллельной сессией в этом же
   worktree; данный срез продолжает его, не переписывая и не откатывая.
   После фиксации среза параллельная линия продолжила писать в этот же worktree
   (`services/prompt_*`, `services/chat_prompts.py`, `services/direct_l1.py`,
   speech-тесты) — эти изменения в коммит не входят и не оценивались здесь.

## 7. Изменённые файлы этого среза

- `services/summary_aliases.py` — `scope_report["by_uid"]` (F7).
- `web/api/routes.py` — R17-safe payload + подключение в существующем endpoint (F7).
- `services/direct_chat_service.py` — `usernames` → `_collision_suffix`,
  `_turn_usernames` (D7; базовая реализация F1–F6 из `d1a44592` сохранена).
- `tests/test_asap3_identity_aliases.py` — 13 новых тестов (§6 аудита).
- `tests/test_p0_alias_runtime_2026_10_25.py` — удалён (дубль после переноса).
- `tests/test_round1025_f8_registry.py`, `tests/test_mca23_planned_vs_actual.py` —
  осознанный re-pin `ROUTES_SHA256_F11`.
- `tests/test_budget_global_toggle_round1024.py`,
  `tests/test_mca07_retrieval_context_round1027.py` — стабы под optional
  `usernames` (следствие D7).
