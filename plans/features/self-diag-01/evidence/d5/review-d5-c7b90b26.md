# D5 - независимое ревью typed prompt_readback

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code c7b90b2652700dc36a9a7b27b6a8ff17fdad21a1, docs 8eac7e71aef1f2022269e24621f3ce93d301a1fb.
База: approved D4-B 722ccfc522ba00a18dc74881913020151ac250aa.
Worktree: self-diag/d5, ...-405ff680.

**Вердикт: Approved для D5 на unit/preprod.** D5/self-diag DONE не
объявляются: D5-02/AMX-04 остаются partial (D6 registration), D5-11/12
partial (quoting/model-context), AC-12/13 live, D5-05 live part.
Карта/progress_scope не менялись; продуктовый код/настройки/прод не менялись;
деплоя нет.

## 1. Состав кандидата

- Diff vs D4-B base: 3 новых файла + binding: services/prompt_readback.py (761),
  handlers/prompt_readback.py (228), tests/test_prompt_readback.py (902),
  evidence binding (187). Существующие файлы не тронуты: DDL 0, миграций 0,
  flags/settings 0, tool_router/tool_schemas/tool_loop/UI не менялись.
- F8: tools/gen_param_registry_round1025.py --check -> CHECK OK: реестр 644.
- `ToolRouter.dispatch("prompt_readback", ...)` фактически возвращает
  `ОШИБКА: неизвестный инструмент prompt_readback`; это ожидаемый seam D6.

## 2. Implementation audit

- Typed request: resource_kind=prompt, scope=current_chat, prompt_selector,
  requested_revision=effective|specific, delivery=reply; unknown поля
  (user_id/chat_id/role/actor/is_admin) отвергаются; free text не вход.
- Selector: поиск по существующему prompt_registry (block_id/pg_key/plain
  name), ambiguous -> ровно один вопрос с candidates, content не читается;
  no selector -> вопрос, не угадывание; not found honest.
- Effective: prompt_registry.effective_prompt + chat_params/cache; source
  global_inherited/chat_override/factory_default; revision/version_id,
  effective_at (chat updated_at / global updated_at / factory null),
  classification factory_public/active_value, withheld metadata; no revision
  write; unreadable chat layer -> unavailable (not global substitution).
- Authorization: D2 open_gate before content; publish(kind="prompt") after;
  member/unverified/revocation handled; fail-closed on incomplete secret
  sources (test mutation kind=prompt->text red); group destination; owner by
  numeric Telegram id; no args identity.
- Delivery: server plain-text messages, no LLM/document; lossless splitter
  4096; ack contains no body; full/partial audit after actual send; no prompt
  body in logs/context/audit; no hardcoded trigger/regex; no second prompt/
  registry/LLM/write path.
- Handler signature `(arguments, ctx) -> str`, TOOL_DEFINITION typed,
  CAPABILITY=prompts/ACTION=view; not registered in D5 (D6 write scope).


## 3. Тесты и mutation

- pytest tests/test_prompt_readback.py -q -> **50 passed**.
- Focused set: diagnostic_policy, tool_router, tool_schemas, chat_params,
  prompt_baseline, evol016_prompt_activation, soul1_direct_prompt_reads ->
  **207 passed, 1 skipped** (warning fastapi/httpx only).
- Assertions прочитаны: typed request/identity, selector/ambiguous/no guess,
  member denied before content, owner numeric, group, unverified, revocation,
  other chat impossible, matrix prompts read/edit, global/chat/factory metadata,
  classification, withheld, specific/factory revision, unreadable chat,
  verbatim/chunk/ack/plain text/partial, secret redaction/incomplete, logs/audit,
  no hardcoded/no LLM/no write.
- **Mutation (independent):** в disposable worktree @ 8eac7e71
  `kind="prompt"` -> `kind="text"` в prepare;
  pytest -k blocked_when_secret -> **1 failed, 49 deselected**
  (status delivered instead of blocked). Restore -> **50 passed**; worktree
  удалён.
- F8 check OK 644; no full suite (bounded focused).

## 4. Independent counterexamples

- Chunk boundary: split_chunks("x"*4095) -> [4095]; 4096 -> [4096];
  4097 -> [4096,1]; 8192 -> [4096,4096]; join exact, no truncation.
- Cache-read failure: fake ConfigCache.get raises; prepare returns
  `unavailable/effective_value_unavailable`, not silent factory; observed.
- Tool seam: ToolRouter.dispatch(prompt_readback) -> unknown tool; observed.
- Secret incomplete: direct prepare with SecretSnapshot incomplete -> blocked;
  mutation kind prompt->text turns it delivered; red observed.
- `SELF_DIAG...` not relevant; no live Telegram.

## 5. Строки D5

**REVIEW (candidate-approved, actual evidence):**
- SD1-D5-01: single registry/no second store (test_readback_uses_the_single_
  registry, module tests).
- SD1-D5-03: selector exact/unique/ambiguous/no-guess/not-found.
- SD1-D5-04: effective current chat + source/version/effective_at; global/chat.
- SD1-D5-06: lossless chunks/partial; boundary independent.
- SD1-D5-07: member denied before content read.
- SD1-D5-08: chat_admin group, owner numeric, only current chat.
- SD1-D5-09: unverified text with retry/ admin hint.
- SD1-D5-10: no override -> factory/effective, no revision write.
- SD1-AMX-03 (political part): prompts read/edit separate; member override no.
- SD1-SEM-02: no hardcoded trigger/regex; typed inputs.
- SD1-SEM-10: unknown identity fields rejected; args cannot raise role.
- SD1-D2-08: disclosure_actor/chat_id/prompt_id/revision/destination=group audit.
- SD1-D2-11: owner numeric; claims in args rejected.
- SD1-D2-16: factory_public vs active_value classification; member denied.

**Partial/PENDING:**
- SD1-D5-02: typed request/validation/server enforcement covered, but tool not
  registered in active TOOL_CALLING_TOOLS/ToolRouter.dispatch; D6 owns.
- SD1-AMX-04: group delivery unit covered, but "real tool calls" needs D6.
- SD1-D5-11: no public channel/leak in ack/logs/audit; prompt already in model
  context quoting/paraphrase not eliminated.
- SD1-D5-12: same; role spoofing rejected, but multi-turn quoting/coding/context
  exfiltration not fully eliminated; no "100% safe" claim.
- SD1-AC-12/AC-13: unit-equivalent only; real Telegram getChatMember/send,
  exact text, group A/B isolation, live admin/unverified remain D7/live.
- SD1-D5-05: unit REVIEW for server/plain text; live delivery part remains
  READY_FOR_LIVE/AC-12 (live_required true).
- D5-05 live, AC live; D6 UI/tool registration; D7 live/default-ON; D5/self-diag
  DONE not declared.


## 6. D6 registration dependency

D5 code is ready but inactive. D6 owns exactly:

1. services/tool_schemas.py: TOOL_CALLING_TOOLS append handlers.prompt_readback.TOOL_DEFINITION.
2. services/tool_router.py: dispatch registry "prompt_readback": handlers.prompt_readback.prompt_readback.
3. services/diagnostic_policy.py: "prompts".tool_names += ("prompt_readback",).

No D6 files were changed in this candidate; `ToolRouter.dispatch` unknown is
expected. D5-02/AMX-04 cannot be REVIEW until registration; D6 also owns UI/
trace and tool_loop integration.

## 7. Backlog

- BACKLOG_ONLY: services/smartmodule_utils.send_chunked_reply splits only on
  whitespace; a word >4096 still goes as one message (warning). D5 uses its own
  lossless splitter; no D5 change. Pre-existing common sender behavior.
- BACKLOG_ONLY: web/api/speech.py::_chat_overrides treats unreadable chat layer
  as "no override" (fail-open), unlike readback unavailable; pre-existing,
  outside D5; D5 does not use this path.
- CRITICAL_OUT_OF_SCOPE: none found. No new page/store/DB/flags/settings.

## 8. Три опоры

- **Implementation:** read services/prompt_readback.py, handlers/prompt_readback.py,
  tests/test_prompt_readback.py, diagnostic_policy/output_projection, prompt_registry
  effective_prompt, ToolRouter.dispatch/TOOL_CALLING_TOOLS boundary; confirmed
  typed fields, policy gate/publish, body-free ack, chunking, audit, no write/LLM.
- **Test validity:** 50/207 passed; assertions are behavioral; mutation
  prompt->text turns secret-incomplete from blocked to delivered (red), restore
  50; chunk boundary independent; F8 644. Tests do not rely on mocks for the
  policy/secret boundary (real D2/output_projection).
- **Independent challenge:** chunk 4095/4096/4097/8192 exact join; cache-read
  failure -> unavailable; ToolRouter unknown; secret-incomplete blocked; mutation
  observed. No Builder prose accepted as proof.

## 9. Residual / live

- Live Telegram not executed: actual send/getChatMember, real numeric owner,
  group A/B isolation, exact live text and long-message limits remain AC-12/13
  D7; no owner QA assignment.
- D5-11/12: prompt text already in the model context can still be quoted or
  rephrased; this slice does not claim 100% protection. No public version
  history/ack/log/audit body.
- effective_at for chat override is chat profile updated_at, not per-key;
  factory has no invented timestamp; version history not exposed.
- PG branch of get_all_chat_params(pg=...) not executed in unit tests (fake
  cache); production must verify effective global/chat values after integration.
- Tool registration is D6; D5 rows D5-02/AMX-04 stay partial. D6 UI/trace,
  D7 live/default-ON remain.
- requirements_gate review on D5 returns candidate mismatch + all PENDING;
  map/evidence reconciliation is PM, not a D5 code defect. Map/progress_scope
  not edited by Reviewer.

## 10. Итог

**Approved для D5 на unit/preprod.** Exact REVIEW rows above; D5-02/AMX-04,
D5-11/12, AC-12/13 remain PENDING/partial, D5-05 live READY_FOR_LIVE. D6
registration is the only blocker to real tool calls; D5/self-diag DONE not
declared. Reviewer did not change code/settings/prod; mutation worktree removed;
provided worktree clean except review artifact; no deploy.

