# MAC-S4-172 (egress) — delta-ревью r2: закрытие SD172-R1-F01

**Ревьюер:** `ses_dea861824ffeu1NBvspR5ZtCb4`.
**Кандидат:** `443a1eb764fcd3ce21d12545691f5ad8f812b6c5` (ветка `feat/mod-acl-s4-172-egress`, запушена), предыдущий tip `9b0448db0` (NEEDS_FIXES r1), база `54546ab5b` (2.58.253).
**R1-артефакт:** `review-r1.md` sha256 `bbd222ef39cf5012bc4d32fe1257291dd629411cb7195efda8e5042b477ec461` (закоммичен байт-в-байт).
**Delta:** 4 файла (2 кода + 2 теста) + evidence; вне них изменений нет.

## Вердикт: APPROVED_FOR_RELEASE_PREPARATION

F01 закрыт: `resume_deferred_evidence` теперь отправляет модель-текст через
`_tg_send.send_text` (один send, тот же chat_id/reply_to_message_id, тот же возврат/исключения);
на фактическом payload Bot API секрет маскируется, обычный ответ байт-идентичен, без evidence
отправки нет. Страж allowlist-модуля ловит обычные регрессии (голый `bot.send_message`,
`self.bot.send_message`, локальный алиас, вызов внутри helper) и добавлен как отдельный
строгий набор; динамические формы (`functools.partial(bot.send_message, …)`, `getattr`) он не
ловит — это остаточное ограничение эвристики (backlog), не текущая утечка.

```json
{
  "artifact": "plans/features/mod-acl-ux-01/evidence/m1/s4-172-egress/review-r2.md",
  "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
  "candidate": "443a1eb764fcd3ce21d12545691f5ad8f812b6c5",
  "previous_tip": "9b0448db06919d195228c70f69543836fb205c73",
  "base": "54546ab5b201a5d8bd169bad613e730d371fc3b9",
  "base_version": "2.58.253",
  "branch": "feat/mod-acl-s4-172-egress",
  "changed_files": ["services/direct_chat_service.py", "services/telegram_send.py", "tests/test_mod_acl_ux_01_s4_172_egress.py", "tests/test_outgoing_guard_round1022.py", "plans/features/mod-acl-ux-01/evidence/m1/s4-172-egress/ (evidence)"],
  "f01_closure": {
    "status": "CLOSED",
    "change": "await bot.send_message(...) -> await _tg_send.send_text(bot, chat_id, text, reply_to_message_id=trigger_id or None)",
    "payload_probe": "old 9b0448db0: secret present=True, args[0]=10, kwargs={'reply_to_message_id': 5}; new 443a1eb76: secret present=False (***), same args/kwargs",
    "no_evidence": "resume with empty states -> False, zero send calls (unchanged)",
    "no_double_send": "one bot.send_message occurrence; send_text does no chunking",
    "error_handling": "same outer try/except -> False; send_text does not swallow exceptions; return value still unused",
    "cleanup_side_effect": "only the documented chokepoint cleanups (<thought>, fact:/msg:) apply, as on all other model replies"
  },
  "guard_judgement": {
    "verdict": "ADEQUATE_FOR_NATURAL_REGRESSION; dynamic dispatch is a residual",
    "catches": ["plain bot.send_message", "self.bot.send_message", "local alias b=bot; b.send_message", "bare send inside a helper function", "wrapper calls via _tg_send/telegram_send are not flagged"],
    "does_not_catch": ["functools.partial(bot.send_message, …)", "getattr(bot, 'send_message')", "f = bot.send_message; await f(…)", "_tg_send.<helper>.send_message (first-component alias heuristic)"],
    "false_positive": "self._tg_send.send_text would be flagged as bare (forces a direct alias name); harmless",
    "strict_set": "SEND_ALLOWLIST_NO_BARE_SENDS = {services/direct_chat_service.py}; subset of allowlist, disjoint from SEND_POINTS (pinned by test)",
    "injection_probe": "added bare bot.send_message to direct_chat_service -> strict test FAILED; added _tg_send.send_text -> passed; added functools.partial -> passed (escape)"
  },
  "regression_check": {
    "module_inventory": "services/direct_chat_service.py: 4 send primitives, all wrappers (_tg_send.send_rich_message x1, _tg_send.send_text x3); 0 bare send_message/send_photo/send_document/edit_message_text/reply/answer",
    "ordinary_text": "resume ordinary reply byte-identical, kwargs exactly {'reply_to_message_id': 5}",
    "prior_behaviour": "chat mask, telemetry masking, controls and non-over-redaction from r1 unchanged (delta does not touch _maybe_sanitize or mca_events)",
    "scope": "git diff --name-status 54546ab5b..HEAD = 4 code/test files + evidence only",
    "main_checkout": "git status --porcelain --untracked-files=no is empty (no tracked builder edits); leftover untracked tmp_* files are older and unrelated"
  },
  "findings": {
    "blocking": [],
    "backlog": [
      {"id": "SD172-R2-F01", "class": "BACKLOG_ONLY", "title": "Strict bare-send guard cannot see dynamic dispatch", "impact": "functools.partial(bot.send_message), getattr(bot, 'send_message') and attribute refs bypass _bare_sites; a future regression using them would not be flagged. No current leak; any static regex guard has this limit.", "disposition": "optional hardening: AST-based scan (ast.Attribute on send primitives) or forbid storing/calling send primitives indirectly; keep the message-text tests as the real behavioural lock"},
      {"id": "SD172-R2-F02", "class": "BACKLOG_ONLY", "title": "Unregistered send modules (carried from r1 F02)", "impact": "handlers/meme_command.py (static phrases) and handlers/prompt_readback.py (prompt text, RBAC/audit) still fail the registry test; no settings/env secret source", "disposition": "register/allowlist with justification in a follow-up"},
      {"id": "SD172-R2-F03", "class": "BACKLOG_ONLY", "title": "README precision: 'zero bare primitives' is pinned only for the _SEND_RE set", "impact": "the strict test covers send_message/edit_text/reply/answer/send_rich_message; send_photo/send_document are verified by the module scan (0) but not enforced by the guard. No current issue.", "disposition": "extend the scanner or word the invariant as the covered primitive set"}
    ]
  },
  "tests": {
    "new_test": "22 passed on candidate; base 54546ab5b 10 failed / 12 passed; old tip 9b0448db0 2 failed / 20 passed (only resume)",
    "guard": "candidate 27 passed / 1 failed; base 24 passed / 1 failed (same meme_command registry gap)",
    "known_red_set": "7 files: 9 failed / 143 passed on candidate and on base, same names",
    "adjacent": "test_log_ring + test_mca13_event_contract_round1027 + test_prompt_readback + test_checkup_contract: 155 passed",
    "py_compile": "4 changed .py files ok", "diff_check": "rc 0", "skips": "none added"
  },
  "base_red": {
    "new_test_failures": [
      "chat: send_text x2, edit_text_safe, send_rich_message x3, build_cover_article_html, sanitizer identity",
      "resume: planted secret, provider error shape"
    ],
    "counts": "base 10 failed / 12 passed; candidate 22 passed",
    "known_red": "9 environment/pre-existing failures identical on both sides (mca23 stale pin, prompt_field_audit, m4_module_params, status_section_ui_merge, tool_coordinator x2, unified_image x2, webapp_f9 secrets count)"
  },
  "mutations": {
    "bare_send_restored_in_resume": "3 caused failures (2 resume masks + strict no-bare-sends) plus the pre-existing meme registry failure; restore sha256 direct_chat_service.py = 35f04dc2…63b211 exact",
    "chat_mask_removed": "unchanged from r1: 7 failed (delta does not touch _maybe_sanitize); current file hash after restore 81b4cbfe…96aeb",
    "telemetry_mask_removed": "unchanged from r1: 2 failed; mca_events hash 8a6f67b6…66361f",
    "restores": "all byte-exact (verified by sha256; temp archive only)"
  },
  "probes": {
    "resume_payload_old": "secret raw, chat 10, reply 5",
    "resume_payload_new": "secret masked, chat 10, reply 5",
    "guard_injection": "bare caught; wrapper passed; partial escaped",
    "module_inventory": "0 bare primitives in direct_chat_service (4 wrapper sends)",
    "evidence_hashes": "review-r1.md = bbd222ef…c461; guard-base 24/1, guard-candidate 27/1; green 22 passed; red 10/12"
  },
  "deployability": {
    "status": "APPROVED_FOR_RELEASE_PREPARATION (small release from 54546ab5b; bump 2.58.254 + release branch/assembly + manifest with previous 54546ab5b/2.58.253; rollback code-only)",
    "postdeploy_readonly": "on the deployed checkout, `python -c` (no network): _maybe_sanitize('... sk-probe-... token') masks the token while an ordinary sentence with chat id/URL/path is byte-identical; a fake-bot resume probe with stubbed persona_short_reply shows the secret masked and one send to chat 10/reply 5; _bare_sites(direct_chat_service) == [] and SEND_ALLOWLIST_NO_BARE_SENDS contains the module",
    "served_blobs": "services/telegram_send.py 81b4cbfe…, services/direct_chat_service.py 35f04dc2…; healthz 200; version/schema; disk keep=2"
  },
  "reviewer_session": "ses_dea861824ffeu1NBvspR5ZtCb4"
}
```

## 1. Что именно изменилось

Delta над `9b0448db0`: `resume_deferred_evidence` переведён на
`_tg_send.send_text`; в `telegram_send` добавлены `WRAPPER_ALIASES` и
`SEND_ALLOWLIST_NO_BARE_SENDS`, обновлено обоснование `direct_chat_service`; в тестах — 4 теста
resume-пути и 3 теста стража. `_maybe_sanitize` не менялся.

## 2. F01 — воспроизведение и закрытие

На старом tip `9b0448db0` probe (fake bot, stub LLM, реальные states/readiness) доставляет
посаженный секрет дословно. На `443a1eb76` тот же probe даёт `вот твой токен ***, держи`, тот же
`chat_id=10` и `kwargs={"reply_to_message_id": 5}`; путь без evidence не отправляет ничего.
Новый тест: 22 passed; на базе 10 failed/12 passed; на старом tip — только 2 resume-падения.

## 3. Страж allowlist-модуля

`_bare_sites` разбирает приёмник вызова: голый `bot.send_message`, `self.bot.send_message`,
локальный алиас и вызов внутри helper — ловятся; вызовы через `_tg_send`/`telegram_send` — нет
(это обёртки). Инъекция в temp-копии: голый `bot.send_message` → строгий тест падает; обёртка →
проходит; `functools.partial(bot.send_message, …)` → **проходит** (не ловится). `getattr` и
`f = bot.send_message` — тоже не ловятся. Это ограничение статической эвристики, а не текущая
утечка: фактический F01-путь закрыт, а естественные регрессии (прямой вызов, helper, self.bot)
ловятся. Рекомендация — AST-скан, если нужен жёсткий инвариант.

## 4. Регрессии и границы

Инвентарь `direct_chat_service`: 4 отправки, все через обёртки; голых примитивов 0. Обычный
resume-ответ байт-идентичен, reply/чат сохранены, без evidence — без отправки. Чат-маска и
телеметрия не менялись (их r1-пробы и мутации остаются в силе). Scope: только 4 файла кода/тестов
+ evidence. Основной checkout: tracked-изменений нет; старые untracked `tmp_*` — не из этой работы.

## 5. Postdeploy

Read-only на выложенном checkout: `_maybe_sanitize` маскирует `sk-…`, обычную строку с
chat id/URL/путём возвращает байт-в-байт; fake-bot probe resume-пути (stub LLM, без сети) даёт
маску и один send в chat 10/reply 5; `_bare_sites(direct_chat_service)` пуст, модуль в
`SEND_ALLOWLIST_NO_BARE_SENDS`. Плюс манифест с фактическим SHA (previous 54546ab5b/2.58.253),
served blobs `telegram_send.py 81b4cbfe…`/`direct_chat_service.py 35f04dc2…`, healthz/version/
schema/disk.

## 6. Ограничения

Живой Telegram не проверялся (fake bot на границе Bot API); LLM подменялся stub'ом. Пределы
r1 (log_ring маскирует каталог/env + паттерны; agentic_events без собственной маски) не менялись.
Страж — regex-эвристика (dynamic dispatch не ловится).

## 7. Гигиена

Ревью read-only: продуктовые файлы/тесты не правились. Инъекции/мутации — только в temp-архивах,
восстановлены по sha256. Временный каталог `%TEMP%\opencode\s4172r2` удалён.
