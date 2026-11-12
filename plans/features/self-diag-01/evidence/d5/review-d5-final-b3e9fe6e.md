# D5-11/D5-12 security adjacency - независимое ревью

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code `b3e9fe6e5ee7a696cc5e385532cea10317a5d437`, docs `e617bc8e49b2fb5b96c9ad8d8e4d801803527751`.
База: `16fa04e7`; worktree `...-7e2768e9`; production code не менялся.

**Вердикт: Approved для SD1-D5-11 / SD1-D5-12.** Реальный tool-путь,
authorization/scope, отсутствие body в tool-result/логах/telemetry, version
registry, encoding/selector oracle и multi-turn сценарии проверены.
D5/self-diag DONE не объявляется; live Telegram/PG остаются D7.

## 1. Что проверено

- `ToolRouter.dispatch("prompt_readback")` -> policy -> handler: participant
  denied до чтения/отправки (`chat_store.read_chats=[]`, `bot.sent=[]`); admin
  получает exact body только в GROUP, tool-result - машинный ack без body.
- Утёкшее старое значение в логе не подменяет endpoint: отдаётся новая
  редакция; знание текста участником не даёт доступа.
- `inspect_runtime`/`config.effective` не читают `prompts.*`; в probe
  catalog/AREAS нет prompt/version источника; source_reader/collector
  структурно не ходят в prompt layer.
- `prompt_readback` - единственный prompt tool; version registry не выдан;
  selector по body/фрагменту/base64/hex/rot13 -> not_found; unknown argument
  fields/role/destination spoofing -> invalid_request; multi-turn member
  получает denied/invalid, без байт/кандидатов/audit disclosure.
- Body отсутствует в tool-result, caplog, `mca_events` и audit; доставка -
  plain text, не документ.

## 2. Независимое воспроизведение

Уникальное тело `REVIEW-UNIQUE-PROMPT-BODY-4321`:

```text
MEMBER denied, messages=(), store.read_chats=[]
ADMIN delivered, body=REVIEW-UNIQUE-PROMPT-BODY-4321
VERSION revision_unavailable, metadata={prompt_id}
ENCODING not_found, messages=()
SPOOF invalid_request, messages=()
```

## 3. Тесты и mutation

- `tests/test_prompt_readback.py` -> **62 passed**.
- 355 focused set -> **355 passed**, 1 warning.
- `test_prompt_baseline` + `test_evol016_prompt_activation` +
  `test_soul1_direct_prompt_reads` -> **56 passed, 1 skipped**.
- **Independent mutation:** в отдельном worktree @ `b3e9fe6e` в
  `_ALLOWED_FIELDS` добавлен `role`; `test_role_and_destination_spoofing_is_rejected`
  -> **1 failed** (`delivered` вместо `invalid_request`); restore -> **62 passed**.
- Builder mutations (body in ack, content oracle, prompts in config keys)
  соответствуют заявленным; production code не менялся.

## 4. Строки и residual

- `SD1-D5-11`, `SD1-D5-12`: **REVIEW**-кандидат; серверная граница
  подтверждена.
- Не заявляется «100% защищён»: prompt уже в LLM-контексте может быть
  процитирован/пересказан моделью; доставленный prompt виден в requesting
  chat; live Telegram/PG не проверялись. Это честные границы, не скрытый
  дефект.
- Остальные D5-строки не пересматривались; D5/self-diag DONE не объявляется.
- Backlog D3/D4: `_probe_deploy_identity` теряет `include_commits`; `conflict`
  не меняет status. Не D5/AC-23-блокеры.

## 5. Три опоры

- **Implementation:** прочитаны security tests, handler/router/policy path,
  source checks; проверены real dispatch, scope, ack/telemetry.
- **Test validity:** 62/355/56+1 запусканы; assertions 12 новых тестов
  прочитаны; mutation role red/restore green.
- **Independent challenge:** unique body denied/current, version, encoding and
  spoof attempts observed; no body in observable outputs.

## 6. Итог

**Approved** для D5-11/D5-12 на `b3e9fe6e` / `e617bc8e`. Карта/
progress_scope не менялись; production code/settings/prod не менялись;
деплоя не было; mutation worktree и probe-run закрыты.

