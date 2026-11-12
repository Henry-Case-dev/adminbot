# SELF-DIAG-01 D5 — финальные security-строки `SD1-D5-11` / `SD1-D5-12`

- Срез: **D5** (защищённый `prompt_readback`) — только последние test/evidence-строки.
- Кодовый кандидат: `b3e9fe6e5ee7a696cc5e385532cea10317a5d437`.
- База: `16fa04e77c56db44c23cb5c8a9386f6cfd756628` (D6-трейн, принятый `review-d6-final`).
- Ветка/worktree: `self-diag/d5-final`,
  `WorkspaceData/worktrees/c742e4de9e92c489/self-diag-01-0ccfa8fbf52b-7e2768e9`.
- Статус: **REVIEW** (решение — за независимым Reviewer). D5/self-diag **не** объявляются DONE.
- Выкат: не выполнялся. Прод, `master`, settings, prompts, `tool_router`/`tool_schemas`,
  `tool_loop`, UI не менялись. Новых LLM/агентов/pipeline/хранилищ/DDL — 0.

## 1. Контракт строк

| Источник | Что нормирует |
|---|---|
| `plans/owner_inputs/2026-11-09-self-diag-01.md:261` (§8.2) | промпт, уже попавший в логи/вывод модели, **не** считается защищённым: тестируется действительный endpoint readback и эксфильтрация через соседние инструменты |
| `plans/owner_inputs/2026-11-09-self-diag-01.md:285-289` (§9.3) | промпт уже в контексте LLM: не включать редактируемые админские промпты в публичные инструменты и журналы; не давать LLM читать полный реестр версий; отдельно тестировать цитирование, пересказ, кодирование, role spoofing, многоходовость, эксфильтрацию через внешние tools; «100% защищён» не записывать |
| `plans/current_task.md:9569-9571, 9581-9593` | prompt readback — отдельный авторизованный артефакт, не сырые данные в общем контексте модели; нет hardcoded триггера |
| `plans/features/self-diag-01/slice-graph.json` (D5) | write_scope D5: `services/prompt_readback.py`, `handlers/prompt_readback.py`, `tests/test_prompt_readback.py` |

## 2. Что изменено (диффа против `16fa04e7`)

| Файл | Строк | sha256 |
|---|---|---|
| `tests/test_prompt_readback.py` | 1209 | `0a00f9d597c39ff80a0fe658620d8505039e774c1f5caaa9946b05c58461f01c` |
| `tests/test_self_diag_golden.py` | 1055 | `112b7b3b3dc68687f4f32bba0757f431a5a4a33b993fc00ad2ce62947a9730db` |

`git diff --stat 16fa04e7 HEAD` → 2 files changed, 1363 insertions(+), 1 deletion(-).
**Продакшн-код не менялся**: ни одного найденного реального пробоя, требующего фикса, нет
(см. §5), поэтому срез — только тесты. Второй security-подсистемы, нового harness'а,
новых флагов/настроек/DDL нет.

`tests/test_prompt_readback.py` расширен разделом «8. Безопасность: действительный endpoint
и соседние tools» (12 новых тестов, 50 → 62 в файле). `tests/test_self_diag_golden.py` —
новый файл по write_scope D7 (AC-23, см. `evidence/d7/golden-ac23-b3e9fe6e.md`).

## 3. Покрытие строк (Builder-оценка; статусы ставит Reviewer/PM)

| Строка | Пункт контракта | Тест (наблюдаемое поведение) |
|---|---|---|
| SD1-D5-11 | действительный endpoint, а не «текст уже в логах» | `test_real_tool_path_denies_member_before_any_send` (реальный `ToolRouter.dispatch` → политика → handler: участник denied, `chat_store.read_chats == []`), `test_real_tool_path_delivers_exact_body_only_to_chat` (админ: тело байт-в-байт только в чат, в tool-result тела нет), `test_readback_reads_current_value_not_a_previously_leaked_one` (утёкшее старое значение в логе не подменяет endpoint: отдаётся новая редакция; участнику знание текста не помогает) |
| SD1-D5-11 | эксфильтрация через СОСЕДНИЕ инструменты | `test_adjacent_inspect_runtime_cannot_read_prompt_keys` (`inspect_runtime`+`config.effective` с `prompts.*` в конфиг-кэше: значения не отдаются, `key` отвергнут валидатором, `_CONFIG_KEYS` без `prompts.*`), `test_adjacent_inspect_runtime_has_no_prompt_probe` (каталог probes без prompt/version), `test_adjacent_diagnostic_sources_never_read_edited_prompts` (структурно: `runtime_probes`/`diagnostic_collector`/`source_reader` не читают `prompt_registry`/`chat_params`/`prompt_versions`), `test_tool_delivery_leaves_no_prompt_body_in_logs_or_events` (реальный dispatch: тела нет в tool-result, логах, `mca_events`-телеметрии и audit) |
| SD1-D5-12 | редактируемые админские промпты не попадают в публичные tools/журналы | те же adjacency-тесты; плюс `test_real_tool_path_delivers_exact_body_only_to_chat` (в контекст модели уходит только машинный ack) |
| SD1-D5-12 | полный реестр версий недоступен неавторизованной LLM | `test_version_registry_is_not_exposed_by_any_tool` (`revision_unavailable` + `version_history_not_exposed`; metadata без `versions/history/revisions`; единственный prompt-инструмент — `prompt_readback`; в каталоге probes нет источника версий) |
| SD1-D5-12 | цитирование/пересказ/кодирование | `test_selector_is_not_a_content_oracle_for_known_text` (селектор = текст/фрагмент/base64/hex/rot13 → `not_found`, тело не возвращается; поиск только по имени/метаданным), `test_quoting_and_encoding_in_arguments_cannot_send_text` (`content/message/text/body/payload/reply` и `delivery=dm` → `invalid_request`, отправок 0) |
| SD1-D5-12 | role spoofing | `test_role_and_destination_spoofing_is_rejected` (`role/user_id/telegram_id/destination/principal/is_admin/chat_id/permissions` → `invalid_request`; реальный dispatch участника с подменой → не delivered, 0 отправок) |
| SD1-D5-12 | многоходовая эксфильтрация | `test_multi_turn_exfiltration_gets_no_bytes_or_candidates` (7 разных ходов участника: denied/invalid, `search_library`/`library_rows` не вызываются — кандидаты не перечисляются, 0 отправок, audit без `prompt_disclosure`) |
| SD1-D5-12 | «100% защищён» не заявляется | см. §5: остаточный риск прямо назван, тестом не «закрывается» |

## 4. Реальные прогоны (exact counts)

```
pytest tests/test_prompt_readback.py -q
62 passed

pytest tests/test_prompt_readback.py tests/test_diagnostic_policy.py \
       tests/test_tool_router.py tests/test_tool_schemas.py \
       tests/test_diagnostic_probes.py tests/test_checkup_contract.py \
       tests/test_checkup_service.py tests/test_self_diag_golden.py -q
355 passed

pytest tests/test_prompt_baseline.py tests/test_evol016_prompt_activation.py \
       tests/test_soul1_direct_prompt_reads.py -q
56 passed, 1 skipped
```

Хост: Windows, Python 3.12, без PG/сети; `:memory:`-двойники существующих слоёв.

### Мутации (доказательство, что тесты падают на сломанном контракте)

Каждая мутация откатывалась `git checkout --`; финальные прогоны — зелёные.

| Мутация | Наблюдение |
|---|---|
| `_ALLOWED_FIELDS` += `role` (role spoofing принимается) | `test_role_and_destination_spoofing_is_rejected` → FAILED (`delivered` вместо `invalid_request`) |
| handler добавляет тело в ack (`+ messages[0]`) | `test_tool_delivery_leaves_no_prompt_body_in_logs_or_events` и `test_ack_contains_no_prompt_body` → FAILED |
| `search_library` при промахе возвращает первый блок (content-oracle) | `test_selector_is_not_a_content_oracle_for_known_text` → FAILED (`delivered` вместо `not_found`) |
| `_CONFIG_KEYS` += `prompts.checkup_system_prompt` (соседний probe читает промпт) | `test_adjacent_inspect_runtime_cannot_read_prompt_keys` → FAILED |

## 5. Честные границы («100% защищён» не заявляется)

1. **Промпт уже в контексте LLM.** Активные system/developer/персонализационные инструкции
   передаются модели для генерации ответа. Сервер не отдаёт тело через инструмент, но сама
   модель может **процитировать/пересказать/продолжить** его в ответе. Тесты проверяют только
   контролируемую серверную границу (что тело не возвращается в tool-result/логи/телеметрию,
   роль и скоуп нельзя подменить, реестр версий не выдаётся). Никакой тест не доказывает
   невозможность цитирования моделью из её контекста; криптографическая конфиденциальность
   такого текста не обещается (ТЗ §9.3).
2. **Доставленный промпт виден в чате.** После авторизованной выдачи текст — обычное
   сообщение в этом чате: он виден участникам группы и может быть перечитан историей этого
   же чата. Это следствие санкционированной доставки (ТЗ §8.2), а не эксфильтрация:
   межчатовое чтение по-прежнему отсекается политикой/скоупом (проверяется в D2/D3-тестах).
3. **Реальный Telegram не выполнялся.** Живые `getChatMember`, реальные лимиты Bot API и
   фактическая отправка остаются postdeploy-проверкой; здесь — детерминированные unit/e2e-двойники.
4. **Проверено только на Windows-хосте**, без PG; `pg`-ветка чтения chat-слоя не исполнялась.
5. Остаточные риски по кодированию/сокрытию: сервер отдаёт текст plain-text без `parse_mode`,
   поэтому HTML/Markdown-инъекция через тело промпта невозможна; но это не ограничивает
   смысловое цитирование моделью (п.1).

## 6. Классификация находок

- `IN_SCOPE` — нет: все проверенные атаки (подмена роли/скоупа/адресата, content-oracle,
  цитирование/кодирование в аргументах, многоходовость, соседние диагностические tools,
  телеметрия/логи/аудит) блокируются существующим кодом; минимальный фикс не потребовался.
- `CRITICAL_OUT_OF_SCOPE` — не обнаружено.
- `BACKLOG_ONLY` (предсуществующее, вне строк D5-11/D5-12, не блокирует срез):
  1. `services/runtime_probes.py::_probe_deploy_identity`: при `include_commits=True`
     коллектор коммитов вызывается, `not_checked` очищается, но полученные коммиты
     **не попадают в `facts`** (переменная `commits` нигде не используется) — запрошенные
     метаданные молча теряются. Воспроизведение: golden `G17-irrelevant-commit-does-not-verify`
     (`facts` без `commits`, `bundle.commits_since_deploy` жёстко `None`). Владелец строки — D3/D4.
  2. `services/runtime_probes.py::_probe_deploy_identity`: непустой `conflict` (несовпадение
     SHA) не меняет статус источника (`code=local_unverified` → `status=ok`); конфликт виден
     только в `facts.conflict`. Golden `G10-deploy-conflict` фиксирует фактическое поведение,
     `verified=false` не даёт ложного «задеплоено».

## 7. Воспроизведение

```
git -C <worktree> rev-parse HEAD          # b3e9fe6e...
python -m pytest tests/test_prompt_readback.py -q
python -m pytest tests/test_diagnostic_policy.py tests/test_tool_router.py \
    tests/test_tool_schemas.py tests/test_diagnostic_probes.py \
    tests/test_checkup_contract.py tests/test_checkup_service.py -q
python -m pytest tests/test_prompt_baseline.py tests/test_evol016_prompt_activation.py \
    tests/test_soul1_direct_prompt_reads.py -q
```
