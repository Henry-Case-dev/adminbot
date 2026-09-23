"""S2 round1026 (ADR-1026-4) — unit-матрица чистого восстановления контекста
Саммари (``services/summary_context_restore.py``): reply-родители §90,
ограниченный соседний контекст §90/§89, хронология/дубли/ID §90/§92,
спец-случаи §91, бюджет §93 «не резать молча», fail-open, структурированный
вход L1 §92.

Модуль чистый: без LLM/БД/сети/системных часов. Строки окна — простые
dict-строки (поля как у ``get_smart_window``).
"""
from services.summary_context_restore import (
    RESTORE_CHAIN_DEPTH,
    RestoreParams,
    build_l1_payload,
    restore_context,
)


def mk(rid, tg, user, text="", reply=None, ts=1000, media="text",
       author="вася", chat=-100):
    return {"id": rid, "tg_message_id": tg, "user_id": user, "text": text,
            "reply_to_id": reply, "timestamp": ts, "media_type": media,
            "author_name": author, "chat_id": chat, "is_forward": 0,
            "forward_source": None}


def ids(rows):
    return [r["id"] for r in rows]


def run(kept, dropped, window, params=None, **kw):
    return restore_context(kept, dropped, window, params, **kw)


# ── §90: reply-родители (транзитивно, пример 100→101→102) ──────────────────

class TestReplyParents:
    def test_chain_100_101_102(self):
        r100 = mk(100, 100, 5, "начало", ts=1000)
        r101 = mk(101, 101, 6, "ответ", reply=100, ts=1001)
        r102 = mk(102, 102, 7, "ответ на ответ", reply=101, ts=1002)
        window = [r100, r101, r102]
        res = run([r102], [r100, r101], window)
        assert ids(res.kept) == [100, 101, 102]
        assert ids(res.restored) == [100, 101]
        assert res.restored_count == 2
        assert res.parent_count == 2
        assert res.neighbor_count == 0
        assert res.restored_tg_ids == (100, 101)
        assert res.status == "ok"

    def test_parent_outside_window_via_extra_parents(self):
        child = mk(102, 102, 7, "ответ", reply=101, ts=1002)
        p101 = mk(101, 101, 6, "родитель", reply=100, ts=1001)
        p100 = mk(100, 100, 5, "корень", ts=1000)
        res = run([child], [], [child], extra_parents=[p101, p100])
        assert ids(res.kept) == [100, 101, 102]
        assert ids(res.restored) == [100, 101]
        assert res.parent_count == 2

    def test_pass_through_bot_row_not_restored(self):
        child = mk(102, 102, 7, "ответ боту", reply=500, ts=1002)
        bot = mk(500, 500, 42, "ответ бота", reply=100, ts=1001)
        root = mk(100, 100, 5, "корень", ts=1000)
        res = run([child], [bot, root], [child, bot, root], bot_id=42)
        assert ids(res.kept) == [100, 102]
        assert ids(res.restored) == [100]
        assert res.parent_count == 1

    def test_bot_parent_without_grandparent_not_restored(self):
        child = mk(102, 102, 7, "ответ", reply=500, ts=1002)
        bot = mk(500, 500, 42, "ответ бота", ts=1001)
        res = run([child], [bot], [child, bot], bot_id=42)
        assert ids(res.kept) == [102]
        assert res.restored_count == 0
        assert res.status == "no_candidates"

    def test_parent_already_kept_not_duplicated(self):
        parent = mk(101, 101, 6, "родитель", ts=1001)
        child = mk(102, 102, 7, "ответ", reply=101, ts=1002)
        res = run([parent, child], [], [parent, child])
        assert ids(res.kept) == [101, 102]
        assert res.restored_count == 0

    def test_reply_to_missing_parent_is_noop(self):
        child = mk(102, 102, 7, "ответ в пустоту", reply=999, ts=1002)
        res = run([child], [], [child])
        assert ids(res.kept) == [102]
        assert res.status == "no_candidates"


# ── §90/§89: ограниченный ближайший контекст ───────────────────────────────

class TestNeighbors:
    def test_neighbors_from_dropped_only(self):
        rows = [mk(100 + i, 100 + i, 5, "x", ts=1000 + i) for i in range(5)]
        kept = [rows[2]]
        dropped = [rows[0], rows[1], rows[3], rows[4]]
        res = run(kept, dropped, rows, RestoreParams(context_neighbors=1))
        assert ids(res.restored) == [101, 103]
        assert res.neighbor_count == 2

    def test_neighbors_zero_disables(self):
        rows = [mk(100 + i, 100 + i, 5, "x", ts=1000 + i) for i in range(5)]
        res = run([rows[2]], [rows[0], rows[1], rows[3], rows[4]], rows,
                  RestoreParams(context_neighbors=0))
        assert res.restored_count == 0

    def test_neighbors_n_both_sides(self):
        rows = [mk(100 + i, 100 + i, 5, "x", ts=1000 + i) for i in range(7)]
        kept = [rows[3]]
        dropped = [r for r in rows if r is not kept[0]]
        res = run(kept, dropped, rows, RestoreParams(context_neighbors=2))
        assert ids(res.restored) == [101, 102, 104, 105]

    def test_burst_only_nearest_not_whole_log(self):
        """Всплеск: восстановлены ближайшие, а не весь 6-часовой лог."""
        rows = [mk(100 + i, 100 + i, 5, "x", ts=1000 + i) for i in range(20)]
        kept = [rows[10]]
        dropped = [r for r in rows if r is not kept[0]]
        res = run(kept, dropped, rows, RestoreParams(context_neighbors=1))
        assert res.restored_count == 2
        assert ids(res.restored) == [109, 111]

    def test_neighbors_skip_bot_rows(self):
        rows = [mk(100, 100, 5, "a", ts=1000),
                mk(101, 101, 42, "бот", ts=1001),
                mk(102, 102, 5, "b", ts=1002)]
        res = run([rows[2]], [rows[0], rows[1]], rows,
                  RestoreParams(context_neighbors=2), bot_id=42)
        # сосед слева — бот (исключён); дальний 100 добирается со offset=2.
        assert ids(res.restored) == [100]

    def test_parallel_threads_not_merged(self):
        a1 = mk(1, 101, 5, "a1", ts=1000)
        a2 = mk(2, 102, 5, "a2", reply=101, ts=1001)
        b1 = mk(3, 201, 6, "b1", ts=1002)
        b2 = mk(4, 202, 6, "b2", reply=201, ts=1003)
        window = [a1, a2, b1, b2]
        res = run([a2, b2], [a1, b1], window,
                  RestoreParams(context_neighbors=0))
        assert ids(res.restored) == [1, 3]           # только свои родители
        assert res.restored_count == 2


# ── §90/§92: хронология, дубли, идентичность ID ────────────────────────────

class TestChronologyDedupIds:
    def test_double_run_is_identical(self):
        rows = [mk(100 + i, 100 + i, 5, "x", ts=1000 + i) for i in range(6)]
        kept = [rows[3], rows[1]]
        dropped = [r for r in rows if r not in kept]
        a = run(kept, dropped, rows, RestoreParams(context_neighbors=1))
        b = run(kept, dropped, rows, RestoreParams(context_neighbors=1))
        assert ids(a.kept) == ids(b.kept)
        assert ids(a.restored) == ids(b.restored)
        assert a.restored_tg_ids == b.restored_tg_ids
        assert a.status == b.status
        assert a.restored_count == b.restored_count

    def test_asc_order_and_parent_not_duplicated_as_neighbor(self):
        parent = mk(101, 101, 6, "родитель", ts=1001)
        child = mk(102, 102, 7, "ответ", reply=101, ts=1002)
        res = run([child], [parent], [parent, child],
                  RestoreParams(context_neighbors=1))
        assert ids(res.kept) == [101, 102]
        assert ids(res.restored) == [101]            # один раз (родитель+сосед)
        assert res.restored_count == 1
        assert res.parent_count == 1

    def test_ids_and_reply_preserved(self):
        parent = mk(101, 501, 6, "родитель", ts=1001)
        child = mk(102, 502, 7, "ответ", reply=501, ts=1002)
        res = run([child], [parent], [parent, child],
                  RestoreParams(context_neighbors=1))
        by_id = {r["id"]: r for r in res.kept}
        assert by_id[101]["tg_message_id"] == 501
        assert by_id[102]["tg_message_id"] == 502
        assert by_id[102]["reply_to_id"] == 501
        assert by_id[101] is parent and by_id[102] is child   # те же объекты

    def test_inputs_not_mutated(self):
        rows = [mk(100 + i, 100 + i, 5, "x", ts=1000 + i) for i in range(4)]
        kept = [rows[1]]
        dropped = [rows[0], rows[2], rows[3]]
        snap_kept, snap_dropped = list(kept), list(dropped)
        run(kept, dropped, rows, RestoreParams(context_neighbors=1))
        assert kept == snap_kept and dropped == snap_dropped


# ── §91: спец-случаи ───────────────────────────────────────────────────────

class TestSpecialCases:
    def test_short_thread_fully_restored(self):
        q = mk(1, 101, 5, "вопрос?", ts=1000)
        a = mk(2, 102, 6, "ответ!", reply=101, ts=1001)
        res = run([a], [q], [q, a], RestoreParams(context_neighbors=1))
        assert ids(res.kept) == [1, 2]

    def test_media_parent_without_text_restored(self):
        media = mk(1, 101, 5, "", ts=1000, media="photo")
        child = mk(2, 102, 6, "смотри фото", reply=101, ts=1001)
        res = run([child], [media], [media, child],
                  RestoreParams(context_neighbors=1))
        assert ids(res.restored) == [1]
        assert res.restored[0]["media_type"] == "photo"

    def test_caption_and_transcript_preserved(self):
        caption = mk(1, 101, 5, "подпись к фото", ts=1000, media="photo")
        voice = mk(2, 102, 6, "транскрипт голосового", ts=1001, media="voice")
        kept = [mk(3, 103, 7, "ответ", reply=101, ts=1002)]
        res = run(kept, [caption, voice], [caption, voice] + kept,
                  RestoreParams(context_neighbors=1))
        got = {r["id"]: r for r in res.kept}
        assert got[1]["text"] == "подпись к фото"
        assert got[2]["text"] == "транскрипт голосового"

    def test_previous_summary_bot_not_restored(self):
        bot = mk(1, 101, 42, "прошлое Саммари", ts=1000)
        child = mk(2, 102, 6, "ответ", reply=101, ts=1001)
        res = run([child], [bot], [bot, child],
                  RestoreParams(context_neighbors=1), bot_id=42)
        assert ids(res.kept) == [2]
        assert res.status == "no_candidates"


# ── §89/§93: cap и бюджет «не резать молча» ────────────────────────────────

class TestCapAndBudget:
    def test_cap_50_with_200_candidates(self):
        rows = [mk(1000 + i, 1000 + i, 5, "x", ts=1000 + i)
                for i in range(201)]
        kept = [rows[100]]
        dropped = [r for r in rows if r is not kept[0]]
        res = run(kept, dropped, rows,
                  RestoreParams(context_neighbors=200,
                                context_max_messages=50))
        assert res.restored_count == 50
        assert len(res.skipped_ids) == 150
        assert res.status == "truncated"
        assert len(res.kept) == 51                    # 50 добавлений + kept

    def test_budget_truncates_additions_not_kept(self):
        from services.token_counter import count_tokens
        rows = [mk(100 + i, 100 + i, 5, "длинное сообщение тут", ts=1000 + i)
                for i in range(5)]
        kept = [rows[2]]
        dropped = [r for r in rows if r is not kept[0]]
        kept_tokens = count_tokens(kept[0]["text"])
        one = count_tokens(rows[0]["text"])
        res = run(kept, dropped, rows,
                  RestoreParams(context_neighbors=2),
                  token_limit=kept_tokens + one)
        assert res.budget["kind"] == "tokens"
        assert res.restored_count == 1
        assert res.status == "truncated"
        assert len(res.skipped_ids) >= 1
        assert kept[0]["id"] in ids(res.kept)

    def test_char_budget_exact_fit_and_plus_one(self):
        rows = [mk(100 + i, 100 + i, 5, "abcd", ts=1000 + i)
                for i in range(4)]
        kept = [rows[1]]
        dropped = [rows[0], rows[2], rows[3]]
        # kept(4) + 2 ближайших соседа (4+4) = 12 символов.
        total = sum(len(r["text"]) for r in (kept[0], rows[0], rows[2]))
        exact = run(kept, dropped, rows, RestoreParams(context_neighbors=1),
                    char_limit=total)
        assert exact.status == "ok"
        assert exact.budget["fits"] is True
        assert exact.restored_count == 2
        tight = run(kept, dropped, rows, RestoreParams(context_neighbors=1),
                    char_limit=total - 1)
        assert tight.status == "truncated"
        assert tight.restored_count == 1

    def test_tiny_budget_keeps_all_kept(self):
        rows = [mk(100 + i, 100 + i, 5, "abcd", ts=1000 + i)
                for i in range(4)]
        kept = [rows[1], rows[2]]
        dropped = [rows[0], rows[3]]
        res = run(kept, dropped, rows, RestoreParams(context_neighbors=1),
                  char_limit=1)
        assert res.restored_count == 0
        assert ids(res.kept) == [101, 102]            # kept не потерян
        assert res.status == "truncated"

    def test_no_budget_fits_true(self):
        rows = [mk(100, 100, 5, "x", ts=1000), mk(101, 101, 5, "y", ts=1001)]
        res = run([rows[1]], [rows[0]], rows, RestoreParams(context_neighbors=1))
        assert res.budget["fits"] is True


# ── Fail-open и граничные входы ────────────────────────────────────────────

class _BadIterable:
    def __iter__(self):
        raise RuntimeError("boom")


class TestFailOpen:
    def test_internal_error_returns_s1_kept(self):
        kept = [mk(1, 101, 5, "x")]
        res = restore_context(kept, [], _BadIterable(), RestoreParams())
        assert res.status == "error"
        assert res.kept == kept
        assert res.restored_count == 0
        assert res.budget["fits"] is True

    def test_empty_inputs(self):
        res = run([], [], [])
        assert res.kept == []
        assert res.status == "no_candidates"

    def test_kept_only_window(self):
        row = mk(1, 101, 5, "x")
        res = run([row], [], [row])
        assert res.status == "no_candidates"
        assert ids(res.kept) == [1]


# ── §92: структурированный вход L1 ─────────────────────────────────────────

class TestL1Payload:
    def test_field_mapping(self):
        row = mk(1, 501, 10, "привет", reply=500, ts=1234, media="photo",
                 author="Вася")
        payload = build_l1_payload([row], chat_id=-100)
        assert payload == [{
            "message_id": 501,
            "chat_id": -100,
            "timestamp": 1234,
            "author_id": 10,
            "display_name": "Вася",
            "text": "привет",
            "reply_to_id": 500,
            "message_type": "photo",
        }]

    def test_mentions_not_invented(self):
        payload = build_l1_payload([mk(1, 501, 10, "x")], chat_id=-100)
        assert "mentions" not in payload[0]

    def test_mentions_preserved_when_present(self):
        row = mk(1, 501, 10, "x")
        row["mentions"] = [10, 11]
        payload = build_l1_payload([row], chat_id=-100)
        assert payload[0]["mentions"] == [10, 11]

    def test_authors_not_substituted(self):
        rows = [mk(1, 501, 10, "a", author="Вася"),
                mk(2, 502, 11, "b", author="Петя")]
        payload = build_l1_payload(rows, chat_id=-100)
        assert [p["author_id"] for p in payload] == [10, 11]
        assert [p["display_name"] for p in payload] == ["Вася", "Петя"]

    def test_missing_fields_not_fabricated(self):
        payload = build_l1_payload([{"id": 1}], chat_id=-100)
        assert payload[0]["message_id"] is None
        assert payload[0]["timestamp"] is None
        assert payload[0]["author_id"] is None
        assert payload[0]["display_name"] is None
        assert payload[0]["message_type"] is None
        assert "mentions" not in payload[0]


def test_chain_depth_constant():
    assert RESTORE_CHAIN_DEPTH == 10
