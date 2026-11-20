"""HC-TIME (B) payload proof capture — synthetic, anonymized, reproducible.

Runs the real Direct Writer boundary (`DirectChatService._l2_write_answer`) on
an isolated in-memory SQLite fixture and stores the ACTUAL `messages` payload
(not DTO). No production access, no real names/texts/URLs: the fixture uses
`A`/`B`, `message-1`, `fact-1`.

Run from the worktree root:
    .venv/Scripts/python.exe plans/features/p0-history-coverage-temporal-egress/
        evidence/time/payloads/capture_payloads.py
"""
import asyncio
import hashlib
import json
import os

from services import summary_memory as sm
from services.database import DatabaseService
from tests.test_direct_chat import FakeLLM, _make_service
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver
from services.tool_router import ToolDeps, ToolRouter

CHAT = -1000000000001
TS = 1704067200          # 2024-01-01 00:00 UTC
EDITED = 1704067500      # 2024-01-01 00:05 UTC
RECORDED = 1704153600    # 2024-01-02 00:00 UTC
UTC_LEGEND = "Метки времени сообщений в контексте — UTC."
CLOCK = (
    '<Chat_Time_Context source="server" phase="answer">\n'
    "local: 01.01.2024 03:00, Понедельник (Europe/Moscow, UTC+03:00)\n"
    "as_of_utc: 2024-01-01T00:00:00+00:00\n"
    "</Chat_Time_Context>"
)


async def _fixture():
    db = DatabaseService(":memory:")
    await db.initialize()
    await db.save_smart_message(
        7, CHAT, "message-0", None, TS - 10, "text", "A", message_id=11)
    row_id = await db.save_smart_message(
        8, CHAT, "message-1", 11, TS, "text", "B", message_id=12)
    await db.db.execute(
        "UPDATE smart_messages SET sent_at = ?, edited_at = ?, "
        "reply_to_author_id = ? WHERE id = ?", (TS, EDITED, 7, row_id))
    await db.db.commit()
    return db


async def main():
    db = await _fixture()
    router = ToolRouter(ToolDeps(search=None, memory=None, aliases=None,
                                 db=db))
    svc = DirectChatService(FakeLLM("ok"), db, FakeLLM("ok"),
                            AliasResolver("{}"), tool_router=router)

    window = await db.get_smart_window(CHAT, 0, 10)
    row = next(r for r in window if r["tg_message_id"] == 12)
    global_line = svc._context_row_line(row, {}, trigger_message_id=12)
    page_line = next(
        ln for ln in svc.tool_router._history_lines(
            await db.get_recent_messages(CHAT, 10), with_user_id=True)
        if "tg:12" in ln)
    rag_line = sm._format_origin_labeled_line(
        ("chat_history", "fact-1", RECORDED, "B", "fact:5", "", False,
         "recorded"))
    chain = await svc._collect_thread_chain(CHAT, 12)
    thread = svc._render_thread(chain, {}, trigger_message_id=12)
    branch = svc._render_branch(chain, {}, trigger_message_id=12)

    llm = FakeLLM("ok")
    writer = _make_service(llm=llm)
    result = await writer._l2_write_answer(
        CHAT, "query-1", temperature=0.5, time_line=CLOCK,
        user_blocks=[
            "<Global_Context>\n" + global_line + "\n</Global_Context>",
            thread,
            branch,
            "<RAG_Memory>\n" + rag_line + "\n</RAG_Memory>",
            "<Tool_Evidence>\n" + page_line + "\n</Tool_Evidence>",
        ])
    assert result is not None and llm.messages
    messages = llm.messages
    user = messages[1]["content"]
    payload = {
        "schema": "p0-hc-time-payload-v1",
        "source": "isolated synthetic SQLite fixture; no production access",
        "anonymized": True,
        "writer": "l2_writer",
        "tasks": ["HC-TIME-PAYLOAD-PROOF", "HC-ACC-CHANNELS",
                  "HC-TIME-SMART-CONTEXT", "HC-B-F1"],
        "time_line": CLOCK,
        "messages": [
            {"role": messages[0]["role"],
             "system_sha256": hashlib.sha256(
                 str(messages[0]["content"]).encode("utf-8")).hexdigest()},
            {"role": messages[1]["role"],
             "content": user},
        ],
        "observed": {
            "reply_edge_in_user": "ответ на tg:11 (uid 7)" in user,
            "edit_stamp_in_user": "ред. 01.01.2024 00:05 UTC" in user,
            "recorded_fact_label_in_user": "| дата записи |" in user,
            "utc_legend_count": user.count(UTC_LEGEND),
            "clock_blocks": user.count("<Chat_Time_Context"),
            "thread_block_in_user": "<Conversation_Thread>" in user,
            "branch_block_in_user": "<Conversation_Branch>" in user,
            "thread_has_reply": "ответ на tg:11 (uid 7)" in thread,
            "thread_has_edit": "ред. 01.01.2024 00:05 UTC" in thread,
            "branch_has_reply": "ответ на tg:11 (uid 7)" in branch,
            "branch_has_edit": "ред. 01.01.2024 00:05 UTC" in branch,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    out = os.path.join(os.path.dirname(__file__), "writer-payload.json")
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(raw + "\n")
    digest = hashlib.sha256((raw + "\n").encode("utf-8")).hexdigest()
    with open(os.path.join(os.path.dirname(__file__),
                           "writer-payload.sha256"), "w",
              encoding="utf-8", newline="\n") as handle:
        handle.write(digest + "  writer-payload.json\n")
    print(json.dumps(payload["observed"], ensure_ascii=False))
    print("sha256", digest)
    await db.close()


asyncio.run(main())
