# SELF-DIAG-01 D5 — привязка доказательств

- Срез: **D5** (типизированный ресурс `prompt_readback`, серверная выдача).
- Кодовый кандидат: `c7b90b2652700dc36a9a7b27b6a8ff17fdad21a1`.
- База: `722ccfc522ba00a18dc74881913020151ac250aa` (принятый D4-B), ветка `self-diag/d5`.
- Worktree: `WorkspaceData/worktrees/c742e4de9e92c489/self-diag-01-0ccfa8fbf52b-405ff680`.
- Статус: **REVIEW** (решение — за независимым Reviewer). D5/self-diag не объявляются DONE.
- Выкат: не выполнялся. Прод, master, settings, prompts, tool_router/tool_schemas, tool_loop, UI не менялись.

## 1. Контракт среза

| Источник | Что нормирует |
|---|---|
| `plans/owner_inputs/2026-11-09-self-diag-01.md:236-261` (§8) | ресурс `prompt_readback`: typed request, разрешение запроса, логика прав на чтение, effective/versioning, серверная выдача, chunked-доставка |
| `plans/owner_inputs/2026-11-09-self-diag-01.md:227-234` (§7.4) | principal только из Telegram-update, решение принимает policy, не LLM |
| `plans/owner_inputs/2026-11-09-self-diag-01.md:276-289` (§9.2-§9.3) | изоляция выхода, секреты, риск промпта внутри контекста LLM |
| `plans/current_task.md:9569-9571` | «prompt readback — отдельный авторизованный артефакт, не сырые данные в общем контексте модели» |
| `plans/current_task.md:9581-9593` (§2.1.6, §3.1) | промпт-readback не в общем evidence-буфере; нет hardcoded триггера |
| `plans/features/self-diag-01/requirements-map.json` (D5) | 21 строка: D5-01..12, AMX-03/04, AC-12/13, SEM-02/10, D2-08/11/16 |
| `plans/features/self-diag-01/d0-discovery.md:36-40` (§5), `:70` (§9) | эффективное значение — существующий resolver; отправитель — существующий sender; tool_router/tool_schemas/tool_loop — write_scope D6 |
| `plans/features/self-diag-01/slice-graph.json` | D5 write_scope = 3 файла; `prompt_versioning` и `tool_calling` инварианты |

## 2. Что изменено (диффа против `722ccfc5` — только новые файлы)

| Файл | Строк | sha256 |
|---|---|---|
| `services/prompt_readback.py` | 761 | `786db6c26974b1f3df974ee04c6968585b106e7afd05d6b53521d4f54e842f34` |
| `handlers/prompt_readback.py` | 228 | `8e3cfc6c5b560d71b28da8bfb52209e16f385ccf7ca81ba80099625a7d87f056` |
| `tests/test_prompt_readback.py` | 902 | `5541d5cb7648fa47a0d71cfbac46885825549186963e3ec9932eb6ee20bdc5f9` |

`git diff --stat 722ccfc5 HEAD` → 3 files changed, 1891 insertions(+), 0 deletions.
Существующие файлы не тронуты: DDL 0, миграций 0, новых флагов/настроек 0
(`tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 644`).

Устройство:

- `services/prompt_readback.py` — контракт и решение: типизированный запрос,
  поиск по существующей библиотеке, effective-значение из
  `prompt_registry.effective_prompt` + `chat_params`/конфиг-кэш, метаданные
  (source/version_id/effective_at/classification), сборка сообщений, lossless
  chunking, машинный ack без тела промпта, вызов `diagnostic_policy`
  (`open_gate` → `publish(kind="prompt")`). Без aiogram, без LLM, без записи.
- `handlers/prompt_readback.py` — транспорт и регистрационный контракт:
  `TOOL_NAME`, `TOOL_DEFINITION` (typed schema), `(arguments, ctx) -> str`,
  plain-text отправка чанков с одним повтором на `TelegramRetryAfter`, аудит
  раскрытия после фактической отправки, честный `partial`.
- `tests/test_prompt_readback.py` — 50 тестов; двойники Bot API/ConfigCache/
  ChatParamsCache в памяти, ни сети, ни PG, ни реальных промптов.

## 3. Покрытие строк карты (Builder-оценка; статусы ставит Reviewer/PM)

| Строка | Состояние | Доказательство |
|---|---|---|
| SD1-D5-01 | покрыто | `test_readback_uses_the_single_registry`, `test_module_has_no_write_path`, `test_selector_from_existing_library_is_not_a_second_index` |
| SD1-D5-02 | **частично** | typed-запрос, валидация и серверный enforcement покрыты (`test_request_*`, `test_tool_schema_is_typed`, `test_tool_entry_point_matches_existing_dispatch_shape`). Регистрация инструмента в активном наборе — write_scope D6 (см. §6, Q1) |
| SD1-D5-03 | покрыто | `test_selector_exact_by_block_id_and_pg_key`, `test_selector_unique_plain_name_resolves`, `test_selector_ambiguous_asks_one_question_without_content`, `test_no_selector_asks_and_does_not_guess`, `test_selector_not_found_is_honest` |
| SD1-D5-04 | покрыто | `test_global_inherited_metadata` (`source=global_inherited`, `version_id`, `effective_at`), `test_chat_override_wins_with_effective_at`, `test_other_chat_scope_is_impossible` |
| SD1-D5-05 | покрыто на unit-уровне | `test_body_is_delivered_verbatim_by_server`, `test_ack_contains_no_prompt_body`, `test_delivery_is_plain_text_not_a_document` |
| SD1-D5-06 | покрыто | `test_long_prompt_is_chunked_without_truncation`, `test_chunks_splitter_is_lossless`, `test_partial_delivery_is_reported` |
| SD1-D5-07 | покрыто | `test_member_is_denied_before_content_read` (контент-читатель подменён на «упади, если вызван»), `test_known_prompt_text_does_not_grant_access` |
| SD1-D5-08 | покрыто | `test_chat_admin_gets_prompt_in_group`, `test_owner_gets_prompt_by_numeric_id`, `test_other_chat_scope_is_impossible` |
| SD1-D5-09 | покрыто | `test_unverified_when_telegram_cannot_confirm` (текст предлагает повторить позже/админку) |
| SD1-D5-10 | покрыто | `test_no_override_shows_factory_and_creates_no_revision` (запись ревизии запрещена подменой `set_chat_params`), `test_withheld_saved_edition_is_reported_honestly` |
| SD1-D5-11 | частично | `test_known_prompt_text_does_not_grant_access`, `test_ack_contains_no_prompt_body`, `test_logs_and_audit_contain_no_prompt_body`, `test_revocation_between_check_and_publication` |
| SD1-D5-12 | частично | нет публичного канала реестра версий и утечки тела в ack/логи/аудит; role spoofing в аргументах отвергается. Цитирование/пересказ промпта, уже лежащего в контексте модели, этим срезом не устраняется — «100% защищён» не заявляется |
| SD1-AMX-03 | покрыто (политическая часть) | `test_prompts_capability_separates_read_and_edit`, `test_matrix_override_cannot_open_prompts_to_member` |
| SD1-AMX-04 | частично | `test_chat_admin_gets_prompt_in_group` (доставка в группу без DM-перенаправления). «Применяется к реальным tool calls» — та же регистрация, Q1 |
| SD1-AC-12 | частично (live) | unit-эквивалент: точный текст, редактирование секрета, чанки, группа. Реальный Telegram-ход не выполнялся |
| SD1-AC-13 | частично (live) | unit: группа A не читает группу B, анонимный/unverified отказ, владелец по numeric ID. Реальный Telegram-ход не выполнялся |
| SD1-SEM-02 | покрыто | `test_no_hardcoded_trigger_or_text_matching` (нет `message.text`/`re.compile`, фраз-литералов), `test_request_is_not_a_free_text_entry_point` |
| SD1-SEM-10 | покрыто | `test_request_rejects_unknown_identity_fields`, `test_claims_of_ownership_in_arguments_do_not_help`, `test_tool_entry_point_matches_existing_dispatch_shape` |
| SD1-D2-08 | покрыто | `test_audit_disclosure_fields` (disclosure_actor/chat_id/prompt_id/revision/destination=group), `test_audit_is_not_written_when_nothing_was_sent` |
| SD1-D2-11 | покрыто | `test_owner_gets_prompt_by_numeric_id`, `test_claims_of_ownership_in_arguments_do_not_help` |
| SD1-D2-16 | покрыто | `test_factory_public_classification`, `test_active_value_classification`, `test_member_is_denied_before_content_read` (заводской промпт участнику тоже не выдаётся — защита строже) |

## 4. Тесты (реальные прогоны, exact counts)

```
pytest tests/test_prompt_readback.py -q
50 passed

pytest tests/test_diagnostic_policy.py tests/test_tool_router.py \
      tests/test_tool_schemas.py tests/test_chat_params.py \
      tests/test_prompt_baseline.py tests/test_evol016_prompt_activation.py \
      tests/test_soul1_direct_prompt_reads.py -q
207 passed, 1 skipped
```

Точечные мутации (доказательство, что тесты падают на сломанном контракте;
файл восстанавливался из копии после каждой, финальный прогон — 50 passed):

| Мутация | Наблюдение |
|---|---|
| hard-deny → `if False` в `prepare` | `test_member_is_denied_before_content_read`, `test_known_prompt_text_does_not_grant_access` → failed |
| `publish(kind="prompt")` → `kind="text"` | `test_blocked_when_secret_sources_incomplete` → failed |
| `TELEGRAM_TEXT_LIMIT = 4096` → `10**9` | `test_long_prompt_is_chunked_without_truncation` → failed |

## 5. Честные границы

- **Live Telegram не выполнялся.** Сообщений в рабочие чаты не отправлялось;
  фактическая отправка/ограничения Bot API, живые `getChatMember` для реальной
  группы и реальный numeric ID владельца остаются postdeploy-проверкой
  (строки AC-12, AC-13, а также live-часть D5-05).
- `effective_at` отсутствует для заводской редакции (`null`) и для слоя, у
  которого нет метки: время активации не выдумывается. Для chat override
  используется `updated_at` профиля чата (не per-key).
- `requested_revision=specific` обслуживает активную и заводскую ревизию;
  полная история версий через readback не выдаётся
  (`version_history_not_exposed`) — второй реестр версий не создаётся.
- При недоступном chat-слое выдаётся `unavailable`, а не global-значение:
  «нет override» и «слой не читается» различаются.
- Если сохранённая редакция удержана провенансом реестра (release-policy не
  активна), выдаётся действующий заводской текст, а удержание показывается
  в метаданных и заголовке — тихой подмены нет.
- Доставка — plain text без parse_mode; документов и имён файлов нет вообще,
  поэтому риск «имя файла раскрывает секрет» отсутствует по конструкции.
- Проверялось только на Windows-хосте, без `PG`/сети; `pg`-ветка чтения
  chat-слоя (`get_all_chat_params(pg=...)`) юнит-тестами не исполнялась.

## 6. Открытый вопрос к Orchestrator/Architect (шов регистрации)

D5 по плану и `slice-graph.write_scope` ограничен тремя файлами, а
`d0-discovery.md:70` отдаёт `services/tool_router.py` и
`services/tool_schemas.py` срезу **D6**. Поэтому D5 не регистрирует инструмент
в активном tool-пути — иначе пришлось бы:
1. добавить 17-й инструмент в `TOOL_CALLING_TOOLS` и обновить канон-тесты
   `tests/test_tool_schemas.py` (сейчас строго 16);
2. добавить `prompt_readback` в `diagnostic_policy` (`prompts.tool_names`) —
   выложенный и заверенный файл D2;
3. вписать обработчик в реестр `ToolRouter.dispatch`.

Контракт для этой регистрации готов и проверен тестами:
`handlers.prompt_readback.prompt_readback(arguments, ctx)`,
`handlers.prompt_readback.TOOL_DEFINITION`, `CAPABILITY="prompts"`,
`ACTION="view"`.

**Вопрос Q1:** выполняет ли эту регистрацию D6 (как записано в
`d0-discovery.md:70`), или D5 получает расширение write_scope на
`services/tool_schemas.py`, `services/tool_router.py`,
`services/diagnostic_policy.py` и `tests/test_tool_schemas.py`? До решения
строки D5-02 и «применяется к реальным tool calls» (AMX-04) остаются
частичными; ничего другого в D5 от регистрации не зависит.

Наблюдаемое состояние шва на кандидате (не «предположение»):

```
ToolRouter.dispatch("prompt_readback", {...}, ToolContext(...))
→ "ОШИБКА: неизвестный инструмент prompt_readback"
```

Запрос без chat-скоупа не падает и не выдаёт текст:
`prepare(..., chat_id=None)` → `unverified` (бот/чат неизвестны).

## 7. Что остаётся вне D5

- **D6:** регистрация инструмента в существующем tool-пути (Q1), отрисовка
  Access/Self-Diagnosis, `tool_loop`-интеграция, HTML/Markdown preview
  (`SD1-D2-29b`), UI-часть `SD1-AMX-01`/`SD1-D2-32`.
- **D7:** живая приёмка AC-12/AC-13, golden set, решение о выпуске, default-ON.
- **D3/D4:** не запускались, их файлы не изменялись.

## 8. Найденное попутно (классификация)

- `IN_SCOPE` — открытых нет: все дефекты, найденные в собственной работе
  (поиск селектора, обработка ревизий, `chunks=0`, отзыв прав между проверкой
  и отправкой), исправлены и покрыты тестами до коммита.
- `CRITICAL_OUT_OF_SCOPE` — не обнаружено.
- `BACKLOG_ONLY`:
  1. `services/smartmodule_utils.send_chunked_reply` режет только по пробелам
     (`SummaryGenerator._chunk_by_whitespace`): слово длиннее 4096 всё равно
     уходит одним сообщением (только WARNING). Предсуществующее поведение
     общих сообщений; D5 использует собственный lossless-сплиттер и этот путь
     не меняет.
  2. `web/api/speech.py::_chat_overrides` считает недоступный chat-слой как
     «override нет» (fail-open), тогда как readback в этом случае честно
     отказывает. Расхождение предсуществующее, вне D5.

## 9. Воспроизведение

```
git -C <worktree> rev-parse HEAD          # c7b90b26...
python -m pytest tests/test_prompt_readback.py -q
python -m pytest tests/test_diagnostic_policy.py tests/test_tool_router.py \
    tests/test_tool_schemas.py tests/test_chat_params.py \
    tests/test_prompt_baseline.py tests/test_evol016_prompt_activation.py \
    tests/test_soul1_direct_prompt_reads.py -q
```
