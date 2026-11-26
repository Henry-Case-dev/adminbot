# MAC-S4-172 (egress) — независимое ревью среза (r1)

**Ревьюер:** `ses_dea861824ffeu1NBvspR5ZtCb4`.
**Кандидат:** `9b0448db06919d195228c70f69543836fb205c73`, ветка `feat/mod-acl-s4-172-egress` (запушена), 1 коммит над deployed `54546ab5b` (2.58.253).
**Изменено:** `services/telegram_send.py` (одна точка), новый `tests/test_mod_acl_ux_01_s4_172_egress.py`, evidence `plans/features/mod-acl-ux-01/evidence/m1/s4-172-egress/`. Вне этого — ничего.

## Вердикт: NEEDS_FIXES

Исправление четырёх обёрток корректно и воспроизводимо (RED 8/10 на базе, GREEN 18/18 на
кандидате; мутации убивают 7 и 2 теста; телеметрия `mca_events` маскирует значения, controls
не перередактируют обычный текст). Но заявленный «единый chokepoint, через который идут все
ответы» **неполон**: `DirectChatService.resume_deferred_evidence` отправляет текст короткого
LLM-ответа (`persona_short_reply`) **прямым** `bot.send_message`, минуя новый chokepoint.
Воспроизведено: подставленный ответ модели с посаженным секретом уходит в Bot API дословно,
тогда как тот же текст через `telegram_send.send_text` маскируется в `***`. Это реальный
egress-путь чата (worker-sweep через `media_readiness.set_resume_handler`) с
модель-сгенерированным текстом, поэтому строка MAC-S4-172 в этом срезе не закрыта.

```json
{
  "artifact": "plans/features/mod-acl-ux-01/evidence/m1/s4-172-egress/review-r1.md",
  "verdict": "NEEDS_FIXES",
  "candidate": "9b0448db06919d195228c70f69543836fb205c73",
  "base": "54546ab5b201a5d8bd169bad613e730d371fc3b9",
  "base_version": "2.58.253",
  "branch": "feat/mod-acl-s4-172-egress",
  "changed_files": ["services/telegram_send.py", "tests/test_mod_acl_ux_01_s4_172_egress.py", "plans/features/mod-acl-ux-01/evidence/m1/s4-172-egress/ (9 files)"],
  "chokepoint_coverage": {
    "reach_chokepoint": [
      "telegram_send.send_text", "telegram_send.edit_text_safe",
      "telegram_send.send_rich_message (auto/markdown/html)",
      "telegram_send.build_cover_article_html",
      "smartmodule_utils._send_once/_reply/send_chunked_reply (-> send_text)",
      "summary_generator wrappers (migrated SEND_POINTS)",
      "handlers/youtube.py provider-error path (log_ring.sanitize before _reply)"
    ],
    "bypass_nonsecret_or_static": [
      "SEND_ALLOWLIST points: static UX/persona phrases, media bytes, ASR text (html.escape), admin canon, relay/user content",
      "handlers/debug_config.py (secret rendered only as configured••••last4)",
      "handlers/prompt_readback.py (prompt text, RBAC/audit; unregistered -> F02)",
      "handlers/meme_command.py (static failure/interrupted phrases; unregistered -> F02)"
    ],
    "bypass_model_text_blocking": [
      "services/direct_chat_service.py:15816 (resume_deferred_evidence) -> bare bot.send_message of persona_short_reply output"
    ]
  },
  "per_path_verdicts": {
    "send_text": "PASS — log_ring.sanitize then sanitize_outgoing; secret masked, ordinary byte-identical",
    "edit_text_safe": "PASS",
    "send_rich_message": "PASS (all three content formats; html/markdown body checked)",
    "build_cover_article_html": "PASS (sanitized before html.escape)",
    "send_chunked_reply/_reply/_send_once": "PASS — delegate to send_text",
    "send_photo/media": "N/A — bytes only, no text",
    "youtube provider error": "PASS — log_ring.sanitize before delivery (source proof; pre-existing)",
    "debug_config": "PASS — no secret value rendered",
    "meme_command / prompt_readback": "UNREGISTERED but no settings-secret source (static phrases / prompt text) — backlog F02",
    "resume_deferred_evidence": "FAIL — model text sent raw, bypasses chokepoint",
    "mca_events.build_event": "PASS — code fields sanitized, JSON fields sanitized; long identifier-like value dropped whole",
    "agentic_events in-memory store": "LATENT — identifier-shaped secret persists raw; no current caller passes settings/env values; console/journald masked by SecretMaskFilter (backlog F03)"
  },
  "controls": {
    "must_mask": ["sk- prefixed key", "Authorization: Bearer <token>", "URI user:pass@"],
    "must_survive": ["64-hex commit id", "40-hex sha1", "public URL with ?token=publicvalue", "file path", "chat id/user id/timezone", "sk-abc near miss", "bearer word", "key= without value", "user:pass@ without scheme"],
    "result": "all 12 controls behaved as expected; chat ordinary message byte-identical"
  },
  "telemetry_verification": {
    "mca_events_code_field": "stage/status with a planted secret -> '***'; JSON usage_json/error_json masked before serialization (probe)",
    "mca_events_long_value": "146-char non-identifier value in code fields -> field dropped, no prefix persisted (test)",
    "agentic_events_probe": "emit_agentic_event('L1_PLAN', run_id=..., reason='123456:PROBE...') stored the raw identifier-shaped value in the in-memory execution graph (get_agentic_events); no own mask in the sink. No current caller passes settings/env values (scan of emitters: codes/enums/model names); console/journald has SecretMaskFilter.",
    "external_log/betterstack": "source proof: safe_text/sanitize"
  },
  "residual_classification": {
    "F01": "BLOCKER (IN_SCOPE): resume_deferred_evidence model-text bypass",
    "F02": "BACKLOG: unregistered send modules meme_command (static phrases) and prompt_readback (prompt text) — the coverage test stops at the first one; registry bookkeeping, no settings-secret source",
    "F03": "BACKLOG: agentic_events store has no own sanitiser; latent for future callers",
    "F04": "BACKLOG (documented limit): log_ring.sanitize literal set = settings/env secrets + POSTGRES_DSN password; DB-stored secret values are covered only by pattern masks; arbitrary non-pattern tokens are not caught (same class as the log channel)"
  },
  "findings": {
    "blocking": [
      {
        "id": "SD172-R1-F01",
        "class": "IN_SCOPE",
        "severity": "high",
        "title": "Model-generated text is delivered raw by DirectChatService.resume_deferred_evidence",
        "expected": "Every user-visible chat send carrying model-generated text passes the shared egress chokepoint (log_ring.sanitize before sanitize_outgoing).",
        "actual": "services/direct_chat_service.py:15816 sends persona_short_reply(...) text with a bare bot.send_message; no sanitizer on this path. The module is in SEND_ALLOWLIST with a justification claiming plain/safe-HTML go through existing wrappers, so the coverage test does not detect it.",
        "repro": "Stub services.factcheck_orchestrator.persona_short_reply to return text containing a planted catalogue secret; call DirectChatService.resume_deferred_evidence({'chat_id': 10, 'trigger_message_id': 5}, [], bot=fake) — bot.send_message receives the secret verbatim. The same text through telegram_send.send_text is masked to '***'.",
        "path_reachability": "media_readiness.set_resume_handler(self.resume_deferred_evidence) at direct_chat_service.py:5383; worker sweep invokes handler(intent, states, bot) with the real bot.",
        "disposition": "Route this send through telegram_send.send_text (or apply telegram_send._maybe_sanitize before bot.send_message), add a regression test for the resume path with a planted secret, and update the direct_chat_service allowlist justification / registry so the path cannot regress silently."
      }
    ],
    "backlog": [
      {"id": "SD172-R1-F02", "class": "BACKLOG_ONLY", "title": "Two modules with send primitives are not registered/allowlisted", "impact": "handlers/meme_command.py (2 static failure texts) and handlers/prompt_readback.py (prompt text to chat, RBAC/audit) fail the coverage registry; the test reports only the first. Neither carries settings/env secret values.", "disposition": "register/allowlist with justified reasons in a small follow-up"},
      {"id": "SD172-R1-F03", "class": "BACKLOG_ONLY", "title": "agentic_events in-memory store has no sanitiser of its own", "impact": "identifier-shaped secret values (<=64 chars) are accepted by the shared whitelist and stored raw; no current caller passes settings/env values; journald path masked; potential future risk (already disclosed by the builder)", "disposition": "add sanitize at the sink or document the caller contract"},
      {"id": "SD172-R1-F04", "class": "BACKLOG_ONLY", "title": "Literal-secret coverage limited to settings/env (and DSN password)", "impact": "DB-stored secret values are caught only by pattern masks; an arbitrary token absent from the catalogue and unlike known patterns is not masked (same class as the accepted log channel)", "disposition": "documented limit; extend only with an owner-approved mechanism"}
    ]
  },
  "tests": {
    "new_test": "18 passed on the candidate; RED on base 8 failed / 10 passed (exactly the chat paths)",
    "guard_registry": "test_outgoing_guard_round1022: 1 failed / 24 passed on both candidate and base (first unregistered module meme_command; prompt_readback also unregistered per the scan)",
    "adjacent": "test_log_ring + test_mca13_event_contract_round1027 + test_prompt_readback + test_checkup_contract: 155 passed",
    "skip_check": "no skips/xfails added; existing tests unchanged",
    "scope_check": "git diff --name-status base..HEAD = 11 files (1 code, 1 test, 9 evidence)"
  },
  "base_red": {
    "failures": [
      "test_send_text_masks_planted_secret",
      "test_send_text_masks_provider_error_shapes",
      "test_edit_text_safe_masks_planted_secret",
      "test_send_rich_message_masks_planted_secret[auto|markdown|html]",
      "test_build_cover_article_html_masks_planted_secret",
      "test_chat_egress_reuses_log_channel_sanitizer"
    ],
    "counts": "8 failed / 10 passed on 54546ab5b; candidate 18 passed"
  },
  "mutations": {
    "chat_mask_removed": "7 failed / 11 passed (all chat masking tests); restore sha256 telegram_send.py = d317eb28…baba92 exact",
    "telemetry_mask_removed": "2 failed / 16 passed (code field + JSON field); restore sha256 mca_events.py = 8a6f67b6…66361f exact"
  },
  "deployability": {
    "status": "BLOCKED by F01 — not approved for release preparation while a model-text chat send bypasses the chokepoint",
    "after_fix": "small release from 54546ab5b (version bump + release branch/assembly + manifest with previous 54546ab5b/2.58.253), rollback code-only to 54546ab5b"
  },
  "required_postdeploy": [
    "Manifest on the deployed checkout: deployed_sha == actual, previous 54546ab5b/2.58.253, version == new, dirty false.",
    "Read-only check (no message is sent): on the deployed checkout run `python -c` importing services.telegram_send and verify _maybe_sanitize('ск-подобный sk-probe-… token') masks the token, while an ordinary sentence with chat id/URL/path is returned byte-identical; confirm TELEGRAM_SEND_GUARD_ENABLED is effectively ON.",
    "Served blob hash of services/telegram_send.py (and, after the fix, services/direct_chat_service.py) matches the built release; healthz 200; version/schema; disk audit/cleanup keep policy.",
    "Targeted live smoke: one ordinary bot message is delivered unchanged; no planted secret is ever sent to a real chat by the check."
  ],
  "reviewer_session": "ses_dea861824ffeu1NBvspR5ZtCb4"
}
```

## 1. Что проверено

* Diff: одна правка `_maybe_sanitize` (маска `log_ring.sanitize` до `sanitize_outgoing`), новый тест,
  evidence. Других изменений нет.
* Тесты используют фактический payload Bot API (`bot.send_message.await_args.args[1]`,
  `send_rich_message.await_args.args[1]`), а не возврат helper'а.
* RED на чистом архиве `54546ab5b`: 8 failed / 10 passed — ровно чат-пути. GREEN на кандидате:
  18 passed. Мутации: 7 и 2 падения, восстановление байт-в-байт.
* Контроли (мои значения): 64-hex и 40-hex id, публичный URL с `?token=`, путь, chat/user/timezone
  не меняются; `sk-…`, `Bearer …`, `user:pass@host` маскируются; near-miss (`sk-abc`, `bearer`,
  `key=`, `user:pass@` без схемы) не трогаются.
* Телеметрия: `build_event` маскирует code- и JSON-поля, длинное неидентификаторное значение
  отбрасывает целиком. `agentic_events` хранит идентификатороподобные значения без собственной
  маски — проверено probe (в store попал `reason` с секретом); текущие вызывающие передают только
  коды/enum, journald закрыт `SecretMaskFilter` — потенциальный риск, не текущий дефект.

## 2. Chokepoint и обходы

Все основные модельные ответы идут через обёртки: `send_chunked_reply`/`_reply`/`_send_once`
делегируют в `send_text`; youtube-ошибка уже проходит `log_ring.sanitize`. Allowlist-точки —
статические UX/персоны/медиа/ASR/админ-канон/рел-контент, `/debug_config` рендерит только
`configured••••last4`. Единственный найденный обход с модель-текстом —
`DirectChatService.resume_deferred_evidence` (строка 15816): прямой `bot.send_message` текста
`persona_short_reply`, без маски. Путь реально подключён через
`media_readiness.set_resume_handler(...)` и worker-sweep.

Воспроизведение (stub LLM): текст с посаженным секретом доходит до `bot.send_message` дословно;
тот же текст через `telegram_send.send_text` → `***`. Это конкретный воспроизводимый обход
канала «чат», поэтому F01 блокирует закрытие MAC-S4-172 в этом срезе.

## 3. Остаточные пункты (не блокируют)

* F02: `handlers/meme_command.py` (статические фразы) и `handlers/prompt_readback.py` (текст
  промпта, RBAC/аудит) не в реестре/allowlist; тест падает на первом из них. Секретов
  settings/env там нет — bookkeeping.
* F03: у `agentic_events` нет собственной маски; store принимает идентификатороподобные
  значения. Сейчас никто из вызывающих не передаёт туда значения настроек.
* F04: `log_ring.sanitize` знает литеральные значения каталога из settings/env (+ пароль DSN);
  значения секретов, сохранённые в BotSettings, ловятся только форменными паттернами. Это тот же
  класс, что и у лог-канала; произвольный не-паттерновый токен не детектируется (честный предел
  билдера).

## 4. Deployability

Срез сам по себе мал (1 файл кода + тест + evidence) и безопасен по механике, но при
NEEDS_FIXES он **не передаётся** в release preparation: сначала нужно закрыть F01 (маршрутизация
resume-доставки через `telegram_send.send_text`/`_maybe_sanitize` + регрессионный тест). После
правки — обычный малый релиз от `54546ab5b`: bump версии, release branch/assembly, manifest с
previous `54546ab5b`/2.58.253; откат code-only на `54546ab5b`.

## 5. Ограничения ревью

Живая Telegram-доставка не выполнялась (fake bot на границе Bot API), как и у билдера; LLM
подменялся stub'ом для воспроизведения обхода. `handlers/prompt_readback` и `meme_command`
проверены чтением кода; их секрет-источник отсутствует. Production не затрагивался.

## 6. Гигиена

Ревью read-only: продуктовые файлы/тесты не правились. Мутации выполнялись только в temp-архиве
кандидата и восстановлены по sha256; временный каталог `%TEMP%\opencode\s4172` удалён.
