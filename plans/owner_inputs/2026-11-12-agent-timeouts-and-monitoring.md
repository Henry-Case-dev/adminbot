# Owner input — таймеры для агентов и контроль «висящих» больше часа (2026-11-12)

- Origin: root chat, 2026-11-12 00:15 (+12:00). Owner message: «я закрыл двух агентов ревьюеров, потому что очевидно что они зависли, пусть ставят таймеры на свои скрипты и следи что именно делают агенты которые висят больше часа».
- Kind: decision (binding operational rule; changes how work is executed, not product behaviour).
- Scope of effect: every delegated lane (Builder, Reviewer, DevOps, PM) and every command they run, plus coordinator monitoring.

## Verbatim instruction

> я закрыл двух агентов ревьюеров, потому что очевидно что они зависли, пусть ставят таймеры на свои скрипты и следи что именно делают агенты которые висят больше часа

## What it obliges

1. **Timeouts on scripts.** Every agent must bound any command it runs: test runners, harnesses, servers, browser runs, subprocess calls. No unbounded `pytest`, no server started without a lifetime, no wait without a deadline. On expiry the agent stops the process, preserves what it got, and reports a partial result explicitly rather than continuing silently.
2. **Server/harness hygiene.** A local server or visual harness is started with an explicit port and a hard lifetime, and is always stopped by the agent that started it, in the same run.
3. **Coordinator monitoring.** The coordinator must inspect what a lane is actually doing once it exceeds about an hour — the real OS processes (command line, CPU, listening ports), the files it writes, and the git state of its worktree — instead of only waiting for a completion event. A lane whose command is idle with no output and no file change is treated as hung, not as "still working".
4. **Recovery rule.** A hung or closed reviewer session is not evidence of approval. Its partial artifacts may be reused as inputs, but the verdict must come from a live, bounded pass.

## Observed justification (same day)

Two inspector review sessions produced no verdict; one was closed by the owner. Inspection of the live processes showed the review had in fact produced screenshots and mutation probes by 22:53–22:58, then started `serve_inspector.py` on `127.0.0.1:8877` and sat there for 1 h 17 min with the process idle. The orphaned server was stopped and the partial artifacts were kept as inputs for a bounded replacement pass.
