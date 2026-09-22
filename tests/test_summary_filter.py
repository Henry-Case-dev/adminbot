"""S1 round1026 (ADR-1026-1) — unit-матрица алгоритмического префильтра
Саммари (``services/summary_filter.py``): критерии §88, порог §87, всплеск по
плотности §89, фрагменты §93, детерминизм, fail-open.

Чистый модуль: без LLM/БД/сети/системных часов (D4). Строки окна — простые
dict-строки (поля как у ``get_window_messages``).
"""
import dataclasses

from services.summary_filter import (
    FilterParams,
    Fragment,
    estimate_and_split,
    filter_window,
    score_message,
)


def mk(rid, tg, user, text="", reply=None, ts=1000):
    return {"id": rid, "tg_message_id": tg, "user_id": user, "text": text,
            "reply_to_id": reply, "timestamp": ts}


# ── Критерии §88: ровно 1 балл за критерий ─────────────────────────────────

class TestScoreCriteria:
    def test_empty_message_scores_zero(self):
        row = mk(1, 101, 5, "ok")
        assert score_message(row, children_by_tg={}, burst_ids=set(),
                             params=FilterParams(), bot_id=None) == 0

    def test_reply_or_mention_gives_one(self):
        params = FilterParams()
        reply = mk(1, 101, 5, "ok", reply=99)
        mention = mk(2, 102, 5, "privet @vasya")
        assert score_message(reply, children_by_tg={}, burst_ids=set(),
                             params=params, bot_id=None) == 1
        assert score_message(mention, children_by_tg={}, burst_ids=set(),
                             params=params, bot_id=None) == 1

    def test_many_mentions_still_one_point(self):
        row = mk(1, 101, 5, "@vasya @petya @kolya hi")
        assert score_message(row, children_by_tg={}, burst_ids=set(),
                             params=FilterParams(), bot_id=None) == 1

    def test_answered_in_window(self):
        row = mk(1, 101, 5, "ok")
        assert score_message(row, children_by_tg={101: 2}, burst_ids=set(),
                             params=FilterParams(), bot_id=None) == 1

    def test_reply_context_disabled_removes_criterion(self):
        row = mk(1, 101, 5, "ok")
        params = FilterParams(reply_context_enabled=False)
        assert score_message(row, children_by_tg={101: 2}, burst_ids=set(),
                             params=params, bot_id=None) == 0

    def test_burst_and_long_criteria(self):
        params = FilterParams(min_words_for_bonus=5)
        row = mk(1, 101, 5, "a b c d e f g")     # 7 слов > 5
        assert score_message(row, children_by_tg={}, burst_ids={1},
                             params=params, bot_id=None) == 2

    def test_long_strictly_greater(self):
        params = FilterParams(min_words_for_bonus=5)
        exactly = mk(1, 101, 5, "a b c d e")     # ровно 5 — бонуса нет
        over = mk(2, 102, 5, "a b c d e f")      # 6 — бонус
        assert score_message(exactly, children_by_tg={}, burst_ids=set(),
                             params=params, bot_id=None) == 0
        assert score_message(over, children_by_tg={}, burst_ids=set(),
                             params=params, bot_id=None) == 1

    def test_all_four_criteria_capped_at_four(self):
        row = mk(1, 101, 5, "@vasya a b c d e f", reply=99)
        score = score_message(row, children_by_tg={101: 1}, burst_ids={1},
                              params=FilterParams(), bot_id=None)
        assert score == 4

    def test_bot_message_scores_zero(self):
        row = mk(1, 101, 42, "@vasya a b c d e f", reply=99)
        assert score_message(row, children_by_tg={101: 1}, burst_ids={1},
                             params=FilterParams(), bot_id=42) == 0


# ── Индекс ответов и всплеск по плотности ──────────────────────────────────

class TestIndices:
    def test_answered_indexed_by_tg_message_id(self):
        # reply_to_id хранит Telegram-id (tg_message_id родителя), не DB-id.
        parent = mk(1, 500, 5, "root")
        child = mk(2, 501, 6, "re", reply=500)
        res = filter_window([parent, child], FilterParams(), bot_id=None)
        assert res.counts["answered"] == 1
        assert res.scores[1] == 1          # на parent ответили

    def test_two_neighbours_not_burst(self):
        rows = [mk(1, 1, 5, "a", ts=1000), mk(2, 2, 5, "b", ts=1001)]
        res = filter_window(rows, FilterParams(min_burst_density=4), bot_id=None)
        assert res.counts["burst"] == 0

    def test_density_burst(self):
        rows = [mk(i, 100 + i, 5, "x", ts=1000 + i) for i in range(1, 5)]
        res = filter_window(rows, FilterParams(min_burst_density=4), bot_id=None)
        # Четвёртое сообщение замыкает окно из 4 → всплеск (== порога).
        assert res.scores[4] == 1
        assert res.scores[1] == 0

    def test_burst_window_expires(self):
        rows = [mk(1, 1, 5, "a", ts=1000),
                mk(2, 2, 5, "b", ts=1001),
                mk(3, 3, 5, "c", ts=1002),
                mk(4, 4, 5, "d", ts=5000)]   # далеко за окном
        res = filter_window(rows, FilterParams(min_burst_density=4,
                                               burst_window_seconds=120),
                            bot_id=None)
        assert res.counts["burst"] == 0


# ── Порог отбора §87 и гарантии «не терять важное» ─────────────────────────

class TestThreshold:
    def test_threshold_boundary_keeps(self):
        # Ровно на пороге → сохранить (score == min_weight).
        rows = [mk(1, 1, 5, "a", reply=9)]     # score 1
        res = filter_window(rows, FilterParams(min_weight=1), bot_id=None)
        assert [r["id"] for r in res.kept] == [1]
        assert res.dropped == []

    def test_zero_weight_keeps_all(self):
        rows = [mk(1, 1, 5, "a"), mk(2, 2, 5, "b")]
        res = filter_window(rows, FilterParams(min_weight=0), bot_id=None)
        assert [r["id"] for r in res.kept] == [1, 2]

    def test_over_four_weight_clamps(self):
        # min_weight > 4 → кламп до 4 (не «удалить всё молча»): сообщение с
        # полным баллом 4 (reply/mention + ответ + всплеск + длина) сохраняется.
        rows = [
            mk(1, 500, 5, "root", ts=1000),
            mk(2, 600, 5, "z", ts=1000),
            mk(3, 700, 5, "z", ts=1000),
            mk(4, 501, 6, "@vasya a b c d e f", reply=500, ts=1001),
            mk(5, 502, 7, "z", reply=501, ts=1002),
        ]
        res = filter_window(rows, FilterParams(min_weight=99,
                                               min_burst_density=4),
                            bot_id=None)
        assert res.scores[4] == 4
        assert [r["id"] for r in res.kept] == [4]

    def test_short_important_thread_kept(self):
        # Короткий важный тред: ответ + родитель, оба без длины/всплеска.
        parent = mk(1, 500, 5, "vopros")
        child = mk(2, 501, 6, "otvet", reply=500)
        res = filter_window([parent, child], FilterParams(), bot_id=None)
        assert set(r["id"] for r in res.kept) == {1, 2}
        assert res.status == "ok"

    def test_garbage_dropped(self):
        rows = [mk(1, 1, 5, "ok"), mk(2, 2, 6, "spam")]
        res = filter_window(rows, FilterParams(), bot_id=None)
        # Мусор отсеян → kept пуст → fail-open возвращает всё окно.
        assert res.status == "empty_fallback"
        assert [r["id"] for r in res.kept] == [1, 2]
        assert res.dropped == []

    def test_empty_window(self):
        res = filter_window([], FilterParams(), bot_id=None)
        assert res.kept == [] and res.dropped == []
        assert res.source_count == 0 and res.drop_percent == 0.0
        assert res.status == "ok"

    def test_single_message(self):
        res = filter_window([mk(1, 1, 5, "hello")], FilterParams(), bot_id=None)
        assert res.status == "empty_fallback"       # одно «мусорное» → fallback

    def test_parallel_conversations(self):
        rows = [
            mk(1, 1, 5, "a", reply=500),           # тред 1
            mk(2, 2, 6, "b"),                      # мусор
            mk(3, 3, 7, "@vasya privet"),          # упоминание
            mk(4, 4, 8, "c c c c c c c"),          # длинное
        ]
        res = filter_window(rows, FilterParams(), bot_id=None)
        assert set(r["id"] for r in res.kept) == {1, 3, 4}
        assert [r["id"] for r in res.dropped] == [2]

    def test_trigger_forced_keep(self):
        rows = [mk(1, 1, 5, "x"), mk(2, 42, 5, "y")]
        res = filter_window(rows, FilterParams(), bot_id=None,
                            trigger_message_id=42)
        assert [r["id"] for r in res.kept] == [2]
        assert res.status == "ok"

    def test_drop_percent(self):
        rows = [mk(1, 1, 5, "x", reply=9, ts=1000),
                mk(2, 2, 5, "x", ts=1400),
                mk(3, 3, 5, "x", ts=1800),
                mk(4, 4, 5, "x", ts=2200)]
        res = filter_window(rows, FilterParams(), bot_id=None)
        assert res.source_count == 4
        assert res.saved_count == 1
        assert res.drop_percent == 75.0


# ── Детерминизм и fail-open ────────────────────────────────────────────────

class TestDeterminism:
    def test_double_run_identical(self):
        import random
        rnd = random.Random(1026)
        rows = [mk(i, i, rnd.choice([5, 6, 7]),
                   rnd.choice(["hi", "@vasya a b c d e", "x y"]),
                   reply=(i - 1 if i % 3 == 0 else None),
                   ts=1000 + rnd.randint(0, 300)) for i in range(1, 60)]
        params = FilterParams()
        a = filter_window(rows, params, bot_id=7)
        b = filter_window(rows, params, bot_id=7)
        assert [r["id"] for r in a.kept] == [r["id"] for r in b.kept]
        assert [r["id"] for r in a.dropped] == [r["id"] for r in b.dropped]
        assert a.scores == b.scores

    def test_input_order_is_normalised(self):
        rows = [mk(2, 2, 5, "b", ts=2000), mk(1, 1, 5, "a", ts=1000)]
        res = filter_window(rows, FilterParams(min_weight=0), bot_id=None)
        assert [r["id"] for r in res.kept] == [1, 2]

    def test_fail_open_on_bad_row(self):
        class Boom(dict):
            def __getitem__(self, key):
                raise RuntimeError("boom")
        res = filter_window([Boom()], FilterParams(), bot_id=None)
        assert res.status == "error"
        assert len(res.kept) == 1


# ── §93: фрагменты и оценка объёма ─────────────────────────────────────────

class TestFragments:
    def test_fits_no_fragments(self):
        rows = [mk(1, 1, 5, "short"), mk(2, 2, 5, "text")]
        fragments, budget = estimate_and_split(rows, token_limit=1000)
        assert fragments is None
        assert budget["fits"] is True

    def test_split_overlapping_and_last_preserved(self):
        rows = [mk(i, i, 5, "word " * 10) for i in range(1, 7)]
        fragments, budget = estimate_and_split(rows, char_limit=60)
        assert budget["fits"] is False
        assert isinstance(fragments[0], Fragment)
        assert fragments[-1].message_ids[-1] == 6          # последний сохранён
        # Перекрытие: первый id 2-го фрагмента — повтор хвоста первого.
        assert fragments[1].overlap_message_ids == (1,)
        assert fragments[1].message_ids[0] == 1
        assert 2 in fragments[1].message_ids
        # Без потери сообщений (объединение id покрывает всё).
        seen = set()
        for f in fragments:
            seen.update(f.message_ids)
        assert seen == {1, 2, 3, 4, 5, 6}

    def test_oversized_single_message_kept(self):
        rows = [mk(1, 1, 5, "x" * 500), mk(2, 2, 5, "y")]
        fragments, budget = estimate_and_split(rows, char_limit=10)
        assert fragments[-1].message_ids[-1] == 2

    def test_filter_window_populates_fragments(self):
        rows = [mk(i, i, 5, "@vasya " + "w " * 20) for i in range(1, 6)]
        res = filter_window(rows, FilterParams(), bot_id=None, char_limit=40)
        assert res.fragments is not None
        assert res.budget["fits"] is False


class TestParamsFrozen:
    def test_defaults(self):
        p = FilterParams()
        assert (p.min_weight, p.min_words_for_bonus, p.burst_window_seconds,
                p.min_burst_density, p.reply_context_enabled) == \
            (1, 5, 120, 4, True)
        assert dataclasses.is_dataclass(p)
