# P0-HC C1 — Telegram markup egress (implementation candidate)

- Feature: `p0-history-coverage-temporal-egress`, slice `HC-EGRESS-C1`.
- Branch: `p0/hc-c1` (from deployed release `2.58.225`,
  base `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d`).
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\p0-hc-c1-7595d2e53439-58af96e4`.
- Status: implementation + self-checks complete; **REVIEW**, not VERIFIED,
  not deployed. No version bump, no call-site, no prompt/config change.

## Contract

Owner input §4 / arch contract §4.1, rows:

- `HC-EGRESS-CHANNEL-CHOICE` — channel is chosen by content: structural
  answer → supported markup; casual chatter → plain; intentionally literal
  stars/code → plain/literal; no forced headings or lists.
- `HC-EGRESS-SAFE-CHUNKING` — highlighting, paragraphs, lists, links and
  special characters survive; long text is split without broken markup or
  open entities; delivered chunks are not re-sent; no new LLM generation.
- Supporting `HC-EGRESS-STRUCTURED` is **not claimed** here: the
  `_send_direct_answer` call-site and `ResponseDocument` integration remain
  C2 after B, exactly as the slice graph requires.

## Product

`services/telegram_markup.py` (new, no third-party parser, no network):

| API | Behavior |
|---|---|
| `decide_markup(text) -> (mode, reason)` | `plain` / `telegram_html`; reasons `plain_empty`, `plain_no_markup`, `markup_tier1`, `markup_tier2`. |
| `render_telegram_html(text)` / `to_telegram_html(text)` | Closed Markdown subset → Telegram HTML; all unsupported `<...>` is escaped. |
| `render_plain(text)` / `to_plain(text)` | Same content without markup markers; links become `label (url)`. |
| `split_telegram_html(html, limit=4096)` | UTF-16 chunking, tags closed/reopened, `<a>` reopened with the same `href`, no split inside tags/entities. |
| `send_structured(bot, chat_id, text, reply_to, *, document=None)` | Plain path delegates to the existing `send_chunked_reply`; HTML path uses `send_text(parse_mode="HTML")`; per-chunk plain fallback on `TelegramBadRequest`; `TelegramRetryAfter` = sleep + one retry; returns first delivered `message_id`. |

Parser rules:

- Tier 1: paired `**`/`__`, inline code, safe `[text](url)`.
- Tier 2: heading `#`, list `-/*/1.`, quote `>`, fence, pseudo-heading
  (`**...**` on its own line), strike `~~...~~`; italic `*`/`_` is enabled
  only at tier 2. Lists render as `• ` / preserved `N. ` text because
  Telegram HTML has no `ul`/`ol`.
- Single `*`/`_`, escaped `\*`, unclosed markers, and intraword `_` remain
  literal. Escaped markers are unescaped by `render_plain`.
- Links only `http://`, `https://`, `tg://`; anything else remains text.
- Raw HTML never passes through: `<`, `>`, `&`, `"` are escaped with only
  the entities Telegram supports (`&lt;`, `&gt;`, `&amp;`, `&quot;`).
- Unclosed fence renders as a code block (no visible ``` markers); unclosed
  inline code stays literal.
- `same source → same output`: no time, randomness or external state.

Chunking:

- Limit source is the existing `services.smartmodule_utils._CHUNK_LIMIT`
  (`4096`); `DEFAULT_CHUNK_LIMIT` is asserted equal in tests.
- Length is counted in UTF-16 code units: astral characters count 2,
  combining marks/ZWJ clusters stay intact, lone surrogates are handled
  without raising.
- Tags/entities are atomic; preferred break after whitespace, otherwise a
  forced code-point/cluster break. Open tags are closed at chunk end and
  reopened at the next chunk.
- `send_structured` sends `parse_mode="HTML"` only for this path, replies
  only to the first chunk, uses the existing hot `limits.summary_chunk_delay`
  / `settings.SUMMARY_CHUNK_DELAY`, and applies `sanitize_outgoing` before
  parsing so `<thought>`-family text cannot become escaped visible text.
- On `TelegramBadRequest` for chunk *k* only that chunk is retried as plain
  (`html_to_plain`, link target preserved); chunks `1..k-1` are never
  re-sent. A second failure logs and stops, returning the first delivered id.
- No LLM/network call exists in the module; tests use a fake Bot API.

## Checks (actual)

Environment: Python `3.12.0`, pytest `9.1.1`, candidate worktree above.
All commands were run from the C1 worktree with
`C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest`.

| Check | Result | Evidence |
|---|---|---|
| RED on base `1b7d43333` (base has no `services/telegram_markup.py`; `git cat-file` confirmed absent) | collection `ImportError` | `red-base.txt` |
| New C1 suite | **78 passed, 0 failed** | `tests-green.txt` |
| Mandatory 24-file regression (`386` tests, same command as `2.58.225`) | **386 passed, 0 failed** | `mandatory-386.txt` |
| Mutations (5) | all **KILLED**: no HTML escape; no tag close/reopen; wrong UTF-16 count; plain renders HTML; unsafe link scheme allowed | `mutations.txt` |
| Pre-existing unrelated failure | `test_outgoing_guard_round1022::test_every_send_point_is_registered_or_allowlisted` fails identically on base (`handlers/meme_command.py`); not caused by C1 | `preexisting-send-points.txt` |
| Browser/Playwright | not applicable: C1 has no call-site/UI and does not change existing delivery | — |

The new suite covers: tier decisions, casual plain parity, escaped/single/
unclosed markers, raw-HTML escape, bold/italic/underline-bold/code/fence/
link/heading/list/quote/strike, unsafe schemes, UTF-16 limits, long words,
emoji/zero-width/combining clusters, entity/tag atomicity, close/reopen of
`<b>`, `<a>` and `<pre><code>`, realistic 4096 output, deterministic output,
fake-Bot plain/HTML paths, reply-only-first, per-chunk fallback, fallback
stop without resend, `RetryAfter`, `document`, empty input and
`sanitize_outgoing`.

## Configuration and scope

- No flag, prompt, factory canon, `parse_mode` default or `/summary` change.
- No edits to `services/direct_chat_service.py`, `services/telegram_send.py`,
  `services/smartmodule_utils.py`, `services/response_document.py`,
  `services/chat_prompts.py`, handlers, migrations or prompts.
- Existing plain delivery remains the default until C2 explicitly branches
  on `decide_markup`; `send_chunked_reply` defaults are untouched.
- New files only: `services/telegram_markup.py`,
  `tests/test_p0_hc_telegram_egress.py`, this evidence subtree.

## Limitations / review notes

- A single tag/entity atom larger than `limit` cannot be split; likewise,
  when nested structural overhead alone exceeds a very small artificial
  limit, a chunk may exceed it. Normal Telegram limit `4096` and normal
  URLs are unaffected; the C1 tests use limits above the structural
  overhead. This is inherent to "no split inside tags".
- Link label ≤300 chars and URL ≤2048 chars are deliberate closed-parser
  bounds; longer constructs stay literal.
- `__init__` in prose is parsed as bold (dunder mention); users should put
  code in backticks. This is deterministic Markdown semantics, not an
  intent classifier.
- No nested lists, tables, images, spoilers or raw HTML whitelist; those
  are outside the C1 subset and are escaped as text.
- The intent heuristic is deliberately conservative: a single paired `*`
  without a tier-2 block stays literal, so casual text is not restyled.

## Handoff to C2

C2 should, in `_send_direct_answer` only:

1. Verify style once as today.
2. `mode, _ = telegram_markup.decide_markup(text)`.
3. `plain` → call the existing `send_chunked_reply` byte-for-byte (do not
   change its defaults).
4. `telegram_html` → `await telegram_markup.send_structured(...)`.
5. Do not touch Rich, lore/deep_research, `/summary`, special report sends,
   generation or prompts.

## Cleanup

The temporary read-only base checkout used to confirm the pre-existing
send-point failure was removed with `git worktree remove` (clean, no force).
No production host, SSH, deploy or backup was accessed; the mutation helper
lives outside the repository. The C1 worktree remains for review/C2.
