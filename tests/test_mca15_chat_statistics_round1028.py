"""MCA-15 `mca-15-chat-statistics` — focused-тесты блоков A–D (T-4919…T-4936).

Покрытие:
* T-4919: адаптированный probe §26 на текущем HEAD (AST-функции заменены
  реальными вызовами `build_fts_query`/`search_messages_fts_count_by_author`/
  `_dig_json_payload`; 7 синтетических сообщений; truth set: фраза 1 /
  prefix-OR 5 / +«петя» 6 / prefix «шиз» 4; truncation больше не оставляет
  голый `total_mentions`).
* T-4920/T-4921 (A42): intent `social_banter`/`historical_evidence`/
  `chat_statistics`/`mixed`; подкол без просьбы не получает отчёт;
  инструменты не блокируются; нет жёсткой реплики на конкретный пример.
* T-4923/T-4924 (A38/A39): StatsQuery — разные единицы/значения; фильтры
  count/examples из одной спеки до LIMIT; канонический user_id, имя — подпись.
* T-4925: dedup/partial, watermark, скан-кап occurrences, ошибка ≠ 0.
* T-4926: FIX `build_fts_query`/счётчика dig/`_dig_json_payload`/lore-агрегатов.
* T-4927: expansion-кандидаты — через `retrieve()` (L-MCA07-5), измерение не
  меняется; второй retrieval-контур не создаётся.
* T-4929 (D4): MetricResult/NumericClaim — честные статусы, привязка к
  query_spec_hash/data_as_of, пересчёт после импорта, claims ok/partial.
* T-4930/T-4931 (D5, A41): `check_numeric_claims`/`NumericContract` в
  существующем контуре; ≤1 коррекция; все пути отправки (System2, fallback,
  lore-story в обход verbalizer, постпроцессор, финальная сборка handle).
* T-4932: stats-режим инструмента, урезание (mandatory сохраняются),
  `insufficient_output_budget`, lore UPD `unchanged` → recheck (lore не
  удаляется).
* T-4934: диагностика §24.5 (R17-safe, links, без SQL/сырого текста).
* T-4935: процесс `chat.statistics` v1 + AMEND `direct.reply` (claim_check);
  OFF → честный disabled; reason-коды ровно +11.
* T-4936: полный регрессионный список §24.5 — каждый пункт к тесту
  (`REGRESSION_245_TESTS`).
* K1/K2/K3 OFF-паритет + реестр kill-switch'ей/reason-кодов.

R17: тесты оперируют кодами/числами/ID; сырой текст — только фикстуры.
"""
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services import chat_statistics as cs
from services import mca_events, mca_gates
from services import negative_constraints as nc
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.lore_compiler_service import LoreCompilerService
from services.summary_memory import build_fts_query
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolRouter,
    _dig_json_payload,
    _stats_json_payload,
)
from tests.test_direct_two_call_round1022 import _SYNTH_JSON, _tool_raw

CHAT_ID = -100777


# ── §26 probe: 7 синтетических сообщений (T-4919) ───────────────────────────

PROBE_ROWS = [
    (1, 10, "Олег", 100, "Вася шиз"),
    (2, 20, "Вася", 101, "Вася пришел"),
    (3, 10, "Олег", 102, "шиз шиз шиз"),
    (4, 30, "Петя", 103, "Петя дома"),
    (5, 999, "Бот", 104, "Шиз, Вася"),
    (6, 10, "Олег", 105, "ничего"),
    (7, 30, "Петя", 106, "шизофрения"),
]


async def _insert_rows(db, rows, chat_id=CHAT_ID):
    for row_id, uid, name, ts, text in rows:
        await db.db.execute(
            "INSERT INTO smart_messages(id,user_id,chat_id,text,timestamp,"
            "author_name,is_forward,forward_source) VALUES(?,?,?,?,?,?,0,'')",
            (row_id, uid, chat_id, text, ts, name))
    await db.db.executemany(
        "INSERT INTO smart_messages_fts(rowid,text) VALUES(?,?)",
        [(row[0], row[4]) for row in rows])
    await db.db.commit()


async def _probe_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    await _insert_rows(db, PROBE_ROWS)
    return db


# ── A+B truth set: 12 строк (два одинаковых имени, unknown, quote/forward,
#    import, смена написания имени одного user_id) ───────────────────────────

TRUTH_ROWS = [
    # (id, uid, text, ts, author_name, is_forward, forward_source, quote_text,
    #  import_key)
    (1, 10, "Вася шиз", 1000, "Вася", 0, "", None, None),
    (2, 20, "Вася пришел", 2000, "Вася", 0, "", None, None),
    (3, 10, "шиз шиз шиз", 3000, "Вася", 0, "", None, None),
    (4, 30, "Петя дома", 4000, "Петя", 0, "", None, None),
    (5, 999, "Шиз, Вася", 5000, "Бот", 0, "", None, None),
    (6, 10, "ничего", 6000, "Вася", 0, "", None, None),
    (7, 30, "шизофрения", 7000, "Петя", 0, "", None, None),
    (8, None, "шиз без автора", 8000, "", 0, "", None, None),
    (9, 10, "форвард шиз", 9000, "Вася", 1, "Канал", None, None),
    (10, 20, "цитата шиз", 10000, "Вася", 0, "", "кто-то сказал шиз", None),
    (11, 10, "импорт шиз", 11000, "Вася", 0, "", None, "imp-1"),
    (12, 10, "Василий шиз", 12000, "Василий", 0, "", None, None),
]


async def _truth_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    for (row_id, uid, text, ts, name, fwd, src, quote, import_key) in TRUTH_ROWS:
        await db.db.execute(
            "INSERT INTO smart_messages(id,user_id,chat_id,text,timestamp,"
            "author_name,is_forward,forward_source,quote_text,import_key) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row_id, uid, CHAT_ID, text, ts, name, fwd, src, quote, import_key))
    await db.db.executemany(
        "INSERT INTO smart_messages_fts(rowid,text) VALUES(?,?)",
        [(row[0], row[2]) for row in TRUTH_ROWS])
    await db.db.commit()
    return db


def _prefix_query(**kw) -> cs.StatsQuery:
    base = dict(chat_id=CHAT_ID, match_mode=cs.MATCH_PREFIX, terms=("шиз",))
    base.update(kw)
    return cs.StatsQuery(**base)


async def _measure(db, **kw) -> dict:
    return await cs.measure(db, _prefix_query(**kw))


# ── T-4919: repro/аудит §24.1 на текущем HEAD ───────────────────────────────

class TestReproProbe:
    """§26-probe адаптирован: реальные функции текущего дерева + SQLite FTS5."""

    @pytest.mark.asyncio
    async def test_truth_set_prefix_or_phrase_prefix(self):
        db = await _probe_db()
        try:
            broad = await db.search_messages_fts_count_by_author(
                CHAT_ID, build_fts_query(["вася", "шиз"]))
            expanded = await db.search_messages_fts_count_by_author(
                CHAT_ID, build_fts_query(["вася", "шиз", "петя"]))
            literal = await db.search_messages_fts_count_by_author(
                CHAT_ID, '"вася шиз"')
            prefix = await db.search_messages_fts_count_by_author(
                CHAT_ID, build_fts_query(["шиз"]))
            assert (broad["count"], expanded["count"], literal["count"],
                    prefix["count"]) == (5, 6, 1, 4)
            # prefix включает «шизофрения» — это префикс, не корень.
            assert build_fts_query(["вася", "шиз"]) == '"вася"* OR "шиз"*'
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_expanded_query_documents_measurement_drift(self):
        """§24.1 п.2: добавление имени в OR-запрос меняет счёт (5→6) —
        RED-механизм, который закрыт разделением измерения и expansion."""
        db = await _probe_db()
        try:
            broad = await db.search_messages_fts_count_by_author(
                CHAT_ID, build_fts_query(["вася", "шиз"]))
            expanded = await db.search_messages_fts_count_by_author(
                CHAT_ID, build_fts_query(["вася", "шиз", "петя"]))
            assert expanded["count"] - broad["count"] == 1
        finally:
            await db.close()

    def test_truncation_red_off_and_fixed_on(self, monkeypatch):
        """§24.1 п.8: K1 OFF — остаётся голый total_mentions (RED);
        K1 ON — структурированный отказ без голого числа."""
        legacy_result = {"total_mentions": 5, "mentions_by_authors": {},
                         "first_seen": 100, "last_seen": 106,
                         "snippets": ["test"], "facts": []}
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled",
                            lambda: False)
        legacy = json.loads(_dig_json_payload(legacy_result, 30))
        assert legacy == {"truncated": True, "total_mentions": 5}
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled", lambda: True)
        fixed_result = {
            "status": "ok",
            "stats": {"status": "ok", "value": 5, "unit": "messages",
                      "method": "fts_prefix_or_messages_v1",
                      "scope": {"chat_id": CHAT_ID}},
            "snippets": ["test"], "facts": []}
        fixed = json.loads(_dig_json_payload(fixed_result, 30))
        assert "total_mentions" not in fixed
        assert fixed["status"] == "insufficient_output_budget"
        assert fixed.get("value") is None


# ── T-4920/T-4921: intent (A42) ─────────────────────────────────────────────

class TestStatsIntent:
    def test_banter_without_request_no_report(self):
        intent = cs.classify_stats_intent(
            "Я настолько охуевший что бот меня ещё ни разу шизом не объявлял")
        assert intent.intent == cs.INTENT_SOCIAL_BANTER
        assert intent.stats_hint is False
        assert intent.reason_code == cs.REASON_SOCIAL_BANTER_INTENT
        assert intent.notable is True   # ассертив о прошлом — видимая цель

    def test_explicit_count_request(self):
        intent = cs.classify_stats_intent(
            "Сколько сообщений Васи содержат слово шиз")
        assert intent.intent == cs.INTENT_CHAT_STATISTICS
        assert intent.stats_hint is True
        assert intent.reason_code == cs.REASON_CHAT_STATS_INTENT

    def test_imperative_count_request(self):
        intent = cs.classify_stats_intent("Посчитай, сколько раз это писали")
        assert intent.intent == cs.INTENT_CHAT_STATISTICS
        assert intent.stats_hint is True

    def test_historical_evidence_request(self):
        intent = cs.classify_stats_intent("Найди, когда ты меня так называл")
        assert intent.intent == cs.INTENT_HISTORICAL_EVIDENCE
        assert intent.stats_hint is False
        assert intent.reason_code == cs.REASON_HISTORICAL_EVIDENCE_INTENT

    def test_mixed_two_goals(self):
        intent = cs.classify_stats_intent(
            "Посчитай, сколько раз я это писал. Хотя ты, конечно, опять "
            "всё забудешь")
        assert intent.intent == cs.INTENT_MIXED
        assert intent.stats_hint is True

    def test_plain_talk_is_banter_without_hint(self):
        intent = cs.classify_stats_intent("привет, как дела?")
        assert intent.intent == cs.INTENT_SOCIAL_BANTER
        assert intent.stats_hint is False
        assert intent.notable is False

    def test_reply_context_followup(self):
        intent = cs.classify_stats_intent(
            "а сколько?", reply_parent="Найдено 5 сообщений «шиз» за всё время")
        assert intent.intent == cs.INTENT_CHAT_STATISTICS
        assert intent.stats_hint is True

    def test_not_addressed_no_hint(self):
        intent = cs.classify_stats_intent(
            "сколько сообщений Васи содержат слово шиз", addressed=False)
        assert intent.intent == cs.INTENT_CHAT_STATISTICS
        assert intent.stats_hint is False

    def test_no_hardcoded_reaction_to_specific_example(self):
        """T-4921: в сервисе нет жёсткой реплики/слов конкретного примера."""
        source = Path("services/chat_statistics.py").read_text(
            encoding="utf-8").casefold()
        for token in ("шиз", "вася", "петя", "охуевш"):
            assert token not in source

    def test_stats_hint_only_for_measurable_intents(self):
        assert "stats" in cs.stats_hint_block().casefold()
        banter = cs.classify_stats_intent(
            "ты меня никогда не называл так")
        assert banter.stats_hint is False

    @pytest.mark.asyncio
    async def test_direct_block_banter_emits_no_hint(self, monkeypatch):
        from services.direct_chat_service import DirectChatService
        events: list = []
        monkeypatch.setattr(
            mca_events, "emit_mca_event",
            lambda name, **kw: events.append({"event_name": name, **kw}))
        svc = DirectChatService.__new__(DirectChatService)
        block, intent = svc._stats_intent_block(
            CHAT_ID, "ты меня никогда не называл так", "", True)
        assert block == "" and intent.intent == cs.INTENT_SOCIAL_BANTER
        assert all(e["event_name"] != "stats_intent" or
                   e["reason_code"] != cs.REASON_CHAT_STATS_INTENT
                   for e in events)
        block2, intent2 = svc._stats_intent_block(
            CHAT_ID, "Сколько раз я это писал?", "", True)
        assert block2 and intent2.stats_hint is True
        assert any(e.get("reason_code") == cs.REASON_CHAT_STATS_INTENT
                   for e in events)

    def test_k3_off_parity(self, monkeypatch):
        from services.direct_chat_service import DirectChatService
        monkeypatch.setattr(mca_gates, "stats_intent_enabled", lambda: False)
        svc = DirectChatService.__new__(DirectChatService)
        block, intent = svc._stats_intent_block(
            CHAT_ID, "Сколько раз я это писал?", "", True)
        assert block == "" and intent is None

    def test_canon_twelve_unchanged(self):
        from services.tool_schemas import TOOL_CALLING_TOOLS
        assert len(TOOL_CALLING_TOOLS) == 12
        names = {t["function"]["name"] for t in TOOL_CALLING_TOOLS}
        assert "query_chat_memory" in names
        assert "stats" not in names

    def test_hint_inserted_before_target_user(self):
        from services.direct_chat_service import DirectChatService
        blocks = ["<RAG_Memory>x</RAG_Memory>",
                  "<Target_User>Вася</Target_User>"]
        out = DirectChatService._insert_dig_result(
            blocks, cs.stats_hint_block())
        assert out[-1].startswith("<Target_User>")
        assert "<Stats_Hint>" in out[-2]


# ── T-4923/T-4924: StatsQuery (A38/A39) ─────────────────────────────────────

class TestStatsQueryContract:
    @pytest.mark.asyncio
    async def test_a38_different_units_and_values(self):
        db = await _truth_db()
        try:
            phrase = await cs.measure(db, cs.StatsQuery(
                chat_id=CHAT_ID, match_mode=cs.MATCH_EXACT_PHRASE,
                text="вася шиз"))
            token = await _measure(db, match_mode=cs.MATCH_TOKEN,
                                   terms=("шиз",))
            prefix = await _measure(db)
            any_terms = await cs.measure(db, cs.StatsQuery(
                chat_id=CHAT_ID, match_mode=cs.MATCH_ANY_TERMS,
                terms=("вася", "шиз")))
            all_terms = await cs.measure(db, cs.StatsQuery(
                chat_id=CHAT_ID, match_mode=cs.MATCH_ALL_TERMS,
                terms=("вася", "шиз")))
            occ = await _measure(db, metric=cs.METRIC_OCCURRENCES)
            authors = await _measure(db,
                                     metric=cs.METRIC_DISTINCT_AUTHORS)
            # фраза / token / prefix — разные значения и единицы
            assert phrase["value"] == 1 and phrase["unit"] == "messages"
            assert token["value"] == 8
            assert prefix["value"] == 9
            assert any_terms["value"] == 9
            assert all_terms["value"] == 2
            assert occ["value"] == 11 and occ["unit"] == "occurrences"
            assert occ["method"] == cs.OCCURRENCE_METHOD
            assert authors["value"] == 4 and authors["unit"] == "authors"
            assert authors["unknown_count"] == 1   # строка без user_id
            # prefix явно не назван морфологией
            assert "морфолог" in prefix["method_label"]
            assert prefix["method"] == cs.FTS_PREFIX_OR_METHOD
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_a39_author_filter_before_limit(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "chat_stats_examples_max", lambda: 2)
        db = await _truth_db()
        try:
            r = await _measure(db, author_ids=(10,))
            assert r["value"] == 5          # только user_id=10
            assert len(r["examples"]) == 2  # LIMIT после фильтра
            assert all(e["author_id"] == 10 for e in r["examples"])
            assert r["authors"] == [{"user_id": 10, "label": "Вася",
                                     "count": 5}]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_a39_time_and_quote_filters_identical(self):
        db = await _truth_db()
        try:
            windowed = await _measure(db, interval_from=2000,
                                      interval_to=8000, examples_limit=50)
            assert windowed["value"] == 4   # id 3,5,7,8
            assert all(2000 <= e["timestamp"] <= 8000
                       for e in windowed["examples"])
            excluded = await _measure(db, quote_forward=cs.QUOTE_EXCLUDE,
                                      examples_limit=50)
            assert excluded["value"] == 7   # 1,3,5,7,8,11,12
            only = await _measure(db, quote_forward=cs.QUOTE_ONLY,
                                  examples_limit=50)
            assert only["value"] == 2       # 9,10
            assert len(only["examples"]) == 2
            source_live = await _measure(db, source_kinds=cs.SOURCE_LIVE,
                                         examples_limit=50)
            source_import = await _measure(db, source_kinds=cs.SOURCE_IMPORT,
                                           examples_limit=50)
            assert source_live["value"] == 8 and source_import["value"] == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_two_same_names_do_not_merge_and_alias_keeps_id(self):
        db = await _truth_db()
        try:
            r = await _measure(db, examples_limit=1)
            by_id = {a["user_id"]: a for a in r["authors"]}
            # два «Вася» (10 и 20) — две отдельные записи, не слияние по имени
            assert by_id[10]["label"] == "Вася"
            assert by_id[20]["label"] == "Вася"
            assert by_id[10]["count"] == 5
            # смена написания (Василий, id 12) не дробит user_id=10
            assert by_id[10]["count"] == 5
            assert set(by_id) == {10, 20, 30, 999}
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_and_examples_one_spec(self):
        db = await _truth_db()
        try:
            r = await _measure(db, examples_limit=50)
            assert r["value"] == 9
            ids = {e["item_id"] for e in r["examples"]}
            assert ids == {f"msg:{i}" for i in (1, 3, 5, 7, 8, 9, 10, 11, 12)}
            assert r["watermark"]["max_id"] == 12
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_time_bounds_timezone_dates(self):
        """Регрессия §24.5 «год/часовой пояс»: человекочитаемые даты — в tz
        чата; unix-границы — сырые."""
        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            # 1_700_000_000 = 2023-11-14 22:13:20 UTC = 2023-11-15 01:13 MSK.
            await _insert_rows(db, [(1, 10, "Вася", 1_700_000_000,
                                     "шиз ночью")])
            msk = await _measure(db, timezone="Europe/Moscow")
            assert msk["time_bounds"]["first_seen"] == 1_700_000_000
            assert msk["time_bounds"]["first_date"] == "2023-11-15"
            utc = await _measure(db)
            assert utc["time_bounds"]["first_date"] == "2023-11-14"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_unsupported_paths_not_guessed(self):
        db = await _truth_db()
        try:
            subject = await _measure(db, subject_ids=(10,))
            assert subject["status"] == "unsupported"
            assert subject["value"] is None
            assert subject["reason"] == cs.REASON_STATS_UNSUPPORTED
            sender = await _measure(db, sender_kinds=cs.SENDER_BOT)
            assert sender["status"] == "unsupported"
            corpus = await cs.measure(db, cs.StatsQuery(
                chat_id=CHAT_ID, match_mode=cs.MATCH_PREFIX,
                terms=("шиз",), corpus_scope="sqlite+pg"))
            assert corpus["status"] == "unsupported"
            norm = await cs.measure(db, cs.StatsQuery(
                chat_id=CHAT_ID, match_mode=cs.MATCH_PREFIX,
                terms=("шиз",), normalization_version="other"))
            assert norm["status"] == "unsupported"
        finally:
            await db.close()


# ── T-4925: dedup / watermark / bounded ─────────────────────────────────────

class TestDedupWatermarkBounded:
    @pytest.mark.asyncio
    async def test_duplicate_import_partial_not_silent_double_count(self):
        db = await _truth_db()
        try:
            # Снимаем partial UNIQUE, чтобы смоделировать legacy-дубли
            # live-строк (та самая ситуация, ради которой существует
            # duplicate pre-check; v16 не создаёт UNIQUE при дублях).
            await db.db.execute(
                "DROP INDEX IF EXISTS idx_smart_messages_chat_tg_live_unique")
            await db.db.commit()
            for row_id, ts in ((13, 13000), (14, 13001)):
                await db.db.execute(
                    "INSERT INTO smart_messages(id,user_id,chat_id,text,"
                    "timestamp,author_name,tg_message_id) "
                    "VALUES(?,?,?,?,?,?,777)",
                    (row_id, 10, CHAT_ID, "дубль", ts, "Вася"))
            await db.db.commit()
            r = await _measure(db)
            assert r["status"] == "partial"
            assert r["reason"] == cs.REASON_STATS_PARTIAL_CORPUS
            assert r["excluded_count"] == 1
            assert r["value"] == 9          # счёт не «молчит» о дублях
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_occurrence_cap_partial_value_null(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "chat_stats_occurrence_max_rows",
                            lambda: 2)
        db = await _truth_db()
        try:
            r = await _measure(db, metric=cs.METRIC_OCCURRENCES)
            assert r["status"] == "partial"
            assert r["value"] is None       # частичное число за полное не выдаём
            assert r["reason"] == cs.REASON_STATS_PARTIAL_CORPUS
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_counter_error_is_not_zero(self):
        db = await _truth_db()
        try:
            db.search_messages_fts_count_by_author = AsyncMock(
                side_effect=RuntimeError("db down"))
            r = await _measure(db)
            assert r["status"] == "error"
            assert r["value"] is None
            assert r["reason"] == cs.REASON_STATS_COUNT_ERROR
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_zero_ok_only_after_successful_scope(self):
        db = await _truth_db()
        try:
            r = await cs.measure(db, cs.StatsQuery(
                chat_id=CHAT_ID, match_mode=cs.MATCH_TOKEN,
                text="неслово"))
            assert r["status"] == "ok" and r["value"] == 0
            assert r["coverage"] == "known_complete"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_watermark_snapshot_same_version(self):
        db = await _truth_db()
        try:
            r = await _measure(db, examples_limit=50)
            assert r["watermark"]["max_id"] is not None
            assert all(int(e["item_id"].split(":")[1]) <=
                       r["watermark"]["max_id"] for e in r["examples"])
        finally:
            await db.close()


# ── T-4926: FIX измерительных путей ─────────────────────────────────────────

class TestFixMeasurementPaths:
    def test_build_fts_query_modes(self):
        # default — байт-паритет старой prefix-OR-формулы
        assert build_fts_query(["вася", "шиз"]) == '"вася"* OR "шиз"*'
        assert build_fts_query(["вася", "шиз"], mode="prefix_or") == \
            '"вася"* OR "шиз"*'
        assert build_fts_query(["вася", "шиз"], mode="prefix") == \
            '"вася"* OR "шиз"*'
        assert build_fts_query(["вася", "шиз"], mode="any_terms") == \
            '"вася" OR "шиз"'
        assert build_fts_query(["вася", "шиз"], mode="all_terms") == \
            '"вася" AND "шиз"'
        assert build_fts_query(["вася", "шиз"], mode="token") == \
            '"вася" OR "шиз"'
        assert build_fts_query(["вася", "шиз"], mode="exact_phrase") == \
            '"вася шиз"'
        assert build_fts_query([]) == ""

    def test_dig_json_payload_on_no_bare_number(self):
        result = {
            "status": "ok",
            "stats": {"status": "ok", "value": 3, "unit": "messages",
                      "method": "fts_prefix_or_messages_v1",
                      "scope": {"chat_id": CHAT_ID}},
            "authors": [{"user_id": 10, "label": "Вася", "count": 3}],
            "first_seen": "2024-01-01", "last_seen": "2024-02-01",
            "snippets": ["сниппет " * 200], "facts": [],
        }
        out = _dig_json_payload(result, 200)
        payload = json.loads(out)
        assert "total_mentions" not in payload
        assert payload["stats"]["value"] == 3
        assert payload["stats"]["unit"] == "messages"
        assert payload["stats"]["method"]
        tiny = json.loads(_dig_json_payload(result, 60))
        assert tiny.get("status") == "insufficient_output_budget"
        assert tiny.get("value") is None

    def test_dig_json_payload_off_parity(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled",
                            lambda: False)
        result = {"total_mentions": 7, "mentions_by_authors": {},
                  "snippets": [], "facts": []}
        out = json.loads(_dig_json_payload(result, 50))
        assert out["truncated"] is True and out["total_mentions"] == 7

    @pytest.mark.asyncio
    async def test_dig_expansion_does_not_change_measurement(self, monkeypatch):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"id": 1, "user_id": 7, "author_name": "антон",
             "text": "антон был на море", "timestamp": int(time.time()),
             "tg_message_id": None}])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=["антон", "марина"])
        db.search_messages_fts_count_by_author = AsyncMock(return_value={
            "count": 1, "first_seen": int(time.time()),
            "last_seen": int(time.time()), "max_id": 1, "unknown_count": 0,
            "by_author": [{"author_name": "антон", "user_id": 7, "count": 1}]})
        memory.db = db
        candidate = MagicMock()
        candidate.entity_type = "message"
        candidate.preview = "антон был на море"
        candidate.sent_at = int(time.time())
        candidate.author_id = 7
        candidate.id = "msg:1"
        expansion = MagicMock()
        expansion.candidates = (candidate,)
        collect = AsyncMock(return_value=expansion)
        monkeypatch.setattr(cs, "collect_candidates", collect)
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "поездка на море", "mode": "messages"},
            ToolContext(CHAT_ID, "поездка на море"))
        payload = json.loads(out)
        # измерение — только по токенам запроса, без имён графа
        args, kwargs = db.search_messages_fts_count_by_author.await_args
        assert args[1] == build_fts_query(["поездка", "на", "море"])
        assert "антон" not in args[1]
        # snippets — без расширения именами графа
        s_args, _ = memory.search_long_term.await_args
        assert "антон" not in s_args[1]
        # expansion-кандидаты — через retrieve()
        collect.assert_awaited_once()
        assert payload["stats"]["value"] == 1
        assert "total_mentions" not in payload
        assert payload["authors"] == [{"user_id": 7, "label": "антон",
                                       "count": 1}]
        assert any("антон был на море" in s for s in payload["snippets"])

    @pytest.mark.asyncio
    async def test_dig_counter_error_separate_status(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[
            {"id": 1, "user_id": 7, "author_name": "антон",
             "text": "нашлось", "timestamp": int(time.time()),
             "tg_message_id": None}])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.search_messages_fts_count_by_author = AsyncMock(
            side_effect=RuntimeError("db down"))
        memory.db = db
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "нашлось", "mode": "messages"},
            ToolContext(CHAT_ID, "нашлось"))
        payload = json.loads(out)
        assert payload["status"] == "partial"
        assert payload["stats"]["status"] == "error"
        assert payload["stats"]["value"] is None
        assert payload["stats"]["reason"] == "stats_count_error"
        assert "total_mentions" not in payload

    @pytest.mark.asyncio
    async def test_dig_counter_error_without_material_not_not_found(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.search_messages_fts_count_by_author = AsyncMock(
            side_effect=RuntimeError("db down"))
        memory.db = db
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "нашлось", "mode": "messages"},
            ToolContext(CHAT_ID, "нашлось"))
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["stats"]["value"] is None
        assert "ничего не нашёл" not in json.dumps(payload, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_dig_counter_gets_person_filter(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.search_messages_fts_count_by_author = AsyncMock(return_value={
            "count": 0, "first_seen": None, "last_seen": None,
            "max_id": None, "unknown_count": 0, "by_author": []})
        memory.db = db
        aliases = MagicMock()
        aliases._aliases = {"10": "Вася"}
        aliases.resolve = lambda uid, name, nick: "Вася"
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory,
                                     aliases=aliases))
        await router.dispatch(
            "dig_into_lore", {"query": "рыбалка", "person": "Вася",
                              "mode": "messages"},
            ToolContext(CHAT_ID, "рыбалка"))
        _, kwargs = db.search_messages_fts_count_by_author.await_args
        assert kwargs.get("author_ids") == (10,)

    @pytest.mark.asyncio
    async def test_dig_facts_mode_measurement_unsupported(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.search_graph_facts_fts = AsyncMock(return_value=[])
        memory.db = db
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "машина", "mode": "facts"},
            ToolContext(CHAT_ID, "машина"))
        payload = json.loads(out)
        assert payload["stats"]["status"] == "unsupported"
        assert payload["stats"]["value"] is None

    @pytest.mark.asyncio
    async def test_query_chat_memory_off_parity(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled",
                            lambda: False)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")
        memory.count_mentions = AsyncMock(return_value={
            "count": 5, "first_seen": None, "last_seen": None})
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        out = await router.dispatch(
            "query_chat_memory", {"query": "шиз", "time_range": "all"},
            ToolContext(CHAT_ID, "шиз"))
        assert "Найдено 5 упоминаний «шиз»" in out

    @pytest.mark.asyncio
    async def test_dig_off_parity_payload(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled",
                            lambda: False)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.search_messages_fts_count_by_author = AsyncMock(return_value={
            "count": 42, "first_seen": 1, "last_seen": 2,
            "by_author": [{"author_name": "Ваня", "user_id": 2, "count": 42}]})
        memory.db = db
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "машина"}, ToolContext(CHAT_ID,
                                                              "машина"))
        payload = json.loads(out)
        assert payload["total_mentions"] == 42
        assert payload["mentions_by_authors"] == {"Ваня": 42}
        assert "stats" not in payload

    @pytest.mark.asyncio
    async def test_lore_aggregates_typed_and_id_keyed(self, monkeypatch):
        from services import lore_compiler_service as lcs
        captured: dict = {}

        def fake_build(**kwargs):
            captured.update(kwargs)
            return "prompt"

        monkeypatch.setattr(lcs, "build_lore_story_user", fake_build)
        monkeypatch.setattr(cs, "measure", AsyncMock(return_value={
            "status": "ok", "value": 3, "unit": "messages",
            "method": cs.FTS_PREFIX_OR_METHOD,
            "method_label": cs.method_label(cs.MATCH_PREFIX),
            "coverage": "known_complete",
            "time_bounds": {"first_seen": 1000, "last_seen": 2000},
            "authors": [{"user_id": 10, "label": "Вася", "count": 2},
                        {"user_id": 20, "label": "Вася", "count": 1}],
        }))
        db = MagicMock()
        db.get_lore_story = AsyncMock(return_value=None)
        db.lore_graph_slice = AsyncMock(return_value={"facts": [], "edges": []})
        db.lore_dense_dialogs = AsyncMock(return_value={
            "dialogs": [[{"id": 1, "user_id": 10, "author_name": "Вася",
                          "text": "привет", "timestamp": 1500,
                          "tg_message_id": 1}]],
            "total": 1, "earliest": 1500, "latest": 1500})
        db.upsert_lore_story = AsyncMock()
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="история")
        svc = LoreCompilerService(db, llm, aliases=None, tz_name="")
        result = await svc.compile(CHAT_ID, "шиз тема")
        assert result["status"] == "ok"
        assert captured["total_mentions"] == 3
        assert captured["mentions_by_authors"] is None
        assert captured["stats_label"] == "сообщений с совпадением"
        assert captured["stats_method"]
        assert captured["authors"] == [
            {"user_id": 10, "label": "Вася", "count": 2},
            {"user_id": 20, "label": "Вася", "count": 1}]

    def test_lore_prompt_labeled_not_bare(self):
        from services.lore_prompts import build_lore_story_user
        text = build_lore_story_user(
            topic="т", total_mentions=5,
            stats_label="сообщений с совпадением",
            stats_method="fts_prefix_or_messages_v1",
            authors=[{"user_id": 10, "label": "Вася", "count": 3},
                     {"user_id": 20, "label": "Вася", "count": 2}])
        assert "сообщений с совпадением: 5 (метод: fts_prefix_or_messages_v1)" \
            in text
        assert "по авторам: Вася - 3, Вася - 2" in text
        legacy = build_lore_story_user(topic="т", total_mentions=5)
        assert "упоминаний: 5" in legacy
        assert "метод:" not in legacy

    def test_measure_stats_for_prompt_honest_statuses(self):
        f = LoreCompilerService._measure_stats_for_prompt
        assert f(None) == (0, None, "", "")
        assert f({"status": "error", "value": None}) == (0, None, "", "")
        assert f({"status": "unsupported", "value": None}) == (0, None, "", "")
        value, authors, label, method = f({
            "status": "partial", "value": 2,
            "method_label": "точный токен", "authors": []})
        assert value == 2 and "частично" in label and method == "точный токен"


# ── T-4927: retrieval через retrieve() (L-MCA07-5) ──────────────────────────

class TestRetrieveRouting:
    @pytest.mark.asyncio
    async def test_collect_candidates_goes_through_retrieve(self, monkeypatch):
        from services import mca_retrieval_context as rc
        captured: dict = {}

        async def fake_retrieve(db, memory, request):
            captured["request"] = request
            return rc.RetrievalResult(status="ok")

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        result = await cs.collect_candidates(
            None, None, chat_id=CHAT_ID, query="когда это было",
            top_k=5, time_from=100, time_to=200, participants=(10,))
        assert result.status == "ok"
        request = captured["request"]
        assert isinstance(request, rc.RetrievalRequest)
        assert request.chat_id == CHAT_ID
        assert request.mode == "history"
        assert request.top_k == 5
        assert request.time_from == 100 and request.time_to == 200
        assert request.participants == (10,)

    def test_no_second_retrieval_engine(self):
        """Второй комбинированный retrieval не создаётся: сервис не вызывает
        retrieval-каналы напрямую — только retrieve() (L-MCA07-5)."""
        source = Path("services/chat_statistics.py").read_text(
            encoding="utf-8")
        assert "retrieve(" in source
        for forbidden in ("retrieve_fact_candidates", "search_graph_facts_fts",
                          "search_long_term", "thread_chain", "lore_stories"):
            assert forbidden not in source


# ── K1/K2/K3 + reason codes (санкции §9) ────────────────────────────────────

class TestGatesAndSanctions:
    def test_kill_switches_registered(self):
        from services import mca_process_registry as reg
        expected = {
            "MCA_CHAT_STATISTICS_ENABLED": "chat_statistics_enabled",
            "MCA_NUMERIC_CLAIM_GUARD_ENABLED": "numeric_claim_guard_enabled",
            "MCA_STATS_INTENT_ENABLED": "stats_intent_enabled",
        }
        for name, resolver in expected.items():
            default, parity = mca_gates.KILL_SWITCHES[name]
            assert default is True and parity
            assert reg._GATE_RESOLVERS[name] == resolver
            assert callable(getattr(mca_gates, resolver))
            assert getattr(settings, name) is True
        assert mca_gates.chat_stats_occurrence_max_rows() == 20000
        assert mca_gates.chat_stats_examples_max() == 20

    def test_reason_codes_registered(self):
        assert {"chat_stats_intent", "historical_evidence_intent",
                "social_banter_intent", "stats_count_error",
                "stats_partial_corpus", "stats_unsupported",
                "insufficient_output_budget"} <= mca_events.REASON_CODES

    def test_catalog_delta_zero(self):
        try:
            from services.param_catalog import PARAM_DEFS
        except Exception:
            from services import param_catalog
            names = {str(getattr(v, "key", ""))
                     for v in getattr(param_catalog, "_PARAMS", [])}
        else:
            names = {d.key for d in PARAM_DEFS}
        assert not ({"MCA_CHAT_STATISTICS_ENABLED",
                     "MCA_NUMERIC_CLAIM_GUARD_ENABLED",
                     "MCA_STATS_INTENT_ENABLED",
                     "MCA_CHAT_STATS_OCCURRENCE_MAX_ROWS",
                     "MCA_CHAT_STATS_EXAMPLES_MAX"} & names)

    def test_spec_hash_stable_and_no_raw_leak(self):
        q1 = _prefix_query()
        q2 = _prefix_query()
        assert cs.query_spec_hash(q1) == cs.query_spec_hash(q2)
        q3 = _prefix_query(interval_from=1000)
        assert cs.query_spec_hash(q1) != cs.query_spec_hash(q3)
        h = cs.query_spec_hash(q1)
        assert len(h) == 64 and "шиз" not in h


# ═══════════════════════════════════════════════════════════════════════════
# Блок C — MetricResult/NumericClaim и контроль чисел (T-4929…T-4933)
# ═══════════════════════════════════════════════════════════════════════════


def _measure_dict(**over) -> dict:
    base = {
        "status": "ok", "value": 9, "unit": "messages",
        "metric": "messages", "method": cs.FTS_PREFIX_OR_METHOD,
        "method_label": cs.method_label(cs.MATCH_PREFIX),
        "query_spec_hash": "a" * 64,
        "scope": {"chat_id": CHAT_ID, "corpus": "smart_messages",
                  "author_ids": []},
        "coverage": "known_complete",
        "time_bounds": {"first_seen": 1000, "last_seen": 2000,
                        "first_date": "2024-01-01", "last_date": "2024-02-01"},
        "watermark": {"max_id": 12, "max_timestamp": 2000},
        "data_as_of": 1234, "excluded_count": 0, "unknown_count": 0,
        "sender_unknown_count": 0, "examples": [], "authors": [],
        "duration_ms": 3, "reason": None,
    }
    base.update(over)
    return base


def _claim(unit="messages", value=9, mid="cs:abc123"):
    return cs.NumericClaim(metric_id=mid, unit=unit, value=value,
                           scope_key="chat:-100777")


def _contract(claims=(), phrase="", expected=False):
    return nc.NumericContract(claims=tuple(claims), verified_phrase=phrase,
                              stats_expected=expected)


# ── T-4929: MetricResult-контракт (D4) ──────────────────────────────────────

class TestMetricResultContract:
    @pytest.mark.asyncio
    async def test_error_value_null_status_error(self):
        """Ошибка/timeout счётчика → value=null/status=error (не ноль)."""
        db = await _truth_db()
        try:
            db.search_messages_fts_count_by_author = AsyncMock(
                side_effect=RuntimeError("db down"))
            r = await _measure(db)
            mr = cs.build_metric_result(r, _prefix_query())
            assert mr.status == "error" and mr.value is None
            assert cs.claim_for_result(mr) is None
            assert mr.verified_phrase == ""
            assert mr.metric_id.startswith("cs:") and len(mr.metric_id) == 15
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_partial_coverage_zero_not_never(self):
        """Ноль в частичном корпусе ≠ «никогда»: coverage partial виден."""
        db = await _truth_db()
        try:
            await db.db.execute(
                "DROP INDEX IF EXISTS idx_smart_messages_chat_tg_live_unique")
            await db.db.commit()
            for row_id, ts in ((13, 13000), (14, 13001)):
                await db.db.execute(
                    "INSERT INTO smart_messages(id,user_id,chat_id,text,"
                    "timestamp,author_name,tg_message_id) "
                    "VALUES(?,?,?,?,?,?,777)",
                    (row_id, 10, CHAT_ID, "дубль", ts, "Вася"))
            await db.db.commit()
            q = cs.StatsQuery(chat_id=CHAT_ID, match_mode=cs.MATCH_TOKEN,
                              text="неслово")
            r = await cs.measure(db, q)
            assert r["status"] == "partial" and r["value"] == 0
            assert r["coverage"] == "partial"
            mr = cs.build_metric_result(r, q)
            assert "частично" in mr.human_label
            assert "никогда" not in mr.human_label
            claim = cs.claim_for_result(mr)
            assert claim is not None and claim.value == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_repeat_after_import_recompute_no_cache(self):
        """Повторный запрос после импорта — пересчёт (durable-кеша нет)."""
        db = await _truth_db()
        try:
            first = await _measure(db)
            await _insert_rows(db, [(13, 10, "Вася", 13000, "шиз ещё")])
            second = await _measure(db)
            assert first["value"] == 9 and second["value"] == 10
            mr1 = cs.build_metric_result(first, _prefix_query())
            mr2 = cs.build_metric_result(second, _prefix_query())
            assert mr1.metric_id == mr2.metric_id   # запрос один и тот же
            assert mr1.value != mr2.value           # число — пересчёт
            assert mr1.data_as_of <= mr2.data_as_of
        finally:
            await db.close()

    def test_fields_bound_to_spec_version_date(self):
        mr = cs.build_metric_result(_measure_dict(), _prefix_query())
        assert mr.metric_id == cs.metric_id_for("a" * 64)
        assert mr.unit == "messages" and mr.value == 9
        assert mr.scope["chat_id"] == CHAT_ID
        assert mr.coverage == "known_complete"
        assert mr.watermark["max_id"] == 12
        assert mr.data_as_of == 1234 and mr.duration_ms == 3
        assert mr.verified_phrase and "9" in mr.verified_phrase
        other = cs.build_metric_result(
            _measure_dict(query_spec_hash="b" * 64),
            _prefix_query(interval_from=5))
        assert other.metric_id != mr.metric_id

    def test_claims_include_author_breakdown(self):
        mr = cs.build_metric_result(_measure_dict(authors=[
            {"user_id": 10, "label": "Вася", "count": 5},
            {"user_id": 20, "label": "Вася", "count": 4}]),
            _prefix_query())
        claims = cs.claims_for_result(mr)
        assert (claims[0].unit, claims[0].value) == ("messages", 9)
        assert {(c.unit, c.value) for c in claims[1:]} == {
            ("messages", 5), ("messages", 4)}
        assert claims[1].scope_key.startswith("author:")

    def test_error_or_unsupported_no_claim(self):
        for status in ("error", "unsupported"):
            mr = cs.build_metric_result(
                _measure_dict(status=status, value=None), _prefix_query())
            assert cs.claim_for_result(mr) is None
            assert mr.verified_phrase == ""


# ── T-4930: NumericClaim и проверенная формулировка ─────────────────────────

class TestNumericClaimsCheck:
    def test_number_must_match_claim_value(self):
        c = _contract(claims=(_claim(),))
        assert nc.check_numeric_claims("он писал 9 сообщений", c) is None
        assert nc.check_numeric_claims(
            "он писал 7 сообщений", c) == nc.NUMERIC_CLAIM_MISMATCH

    def test_unit_compatibility(self):
        c = _contract(claims=(_claim(unit="messages", value=9),))
        # число из другого metric (occurrences=11) не подтверждает messages
        assert nc.check_numeric_claims(
            "11 вхождений", c) == nc.NUMERIC_CLAIM_MISMATCH
        assert nc.check_numeric_claims(
            "9 вхождений", c) == nc.NUMERIC_CLAIM_MISMATCH
        c_occ = _contract(claims=(_claim(unit="occurrences", value=11),))
        assert nc.check_numeric_claims("11 вхождений", c_occ) is None
        c_auth = _contract(claims=(_claim(unit="authors", value=4),))
        assert nc.check_numeric_claims(
            "4 сообщения", c_auth) == nc.NUMERIC_CLAIM_MISMATCH

    def test_other_query_number_not_confirmation(self):
        """A41: число из tool output/другого запроса — не подтверждение."""
        c = _contract(claims=(_claim(value=9),))
        assert nc.check_numeric_claims(
            "5 сообщений", c) == nc.NUMERIC_CLAIM_MISMATCH
        assert nc.check_numeric_claims(
            "5 сообщений", c,
            source_text="найдено 5 сообщений") == nc.NUMERIC_CLAIM_MISMATCH

    def test_dates_age_quotes_free(self):
        c = _contract(claims=(_claim(value=9),))
        assert nc.check_numeric_claims("В 2024 году было 9 сообщений",
                                       c) is None
        assert nc.check_numeric_claims("Тебе 30 лет, и было 9 сообщений",
                                       c) is None
        assert nc.check_numeric_claims("Он сказал «7 сообщений»", c) is None
        assert nc.check_numeric_claims("обычная речь без чисел", c) is None

    def test_no_claims_ungrounded_blocked(self):
        assert nc.check_numeric_claims(
            "он писал 5 сообщений", _contract()) == nc.NUMERIC_CLAIM_MISMATCH
        assert nc.check_numeric_claims("просто привет", _contract()) is None

    def test_correction_replaces_with_verified_phrase(self):
        c = _contract(claims=(_claim(),), phrase="сообщений с совпадением: 9",
                      expected=True)
        text, stats = nc.apply_numeric_guard("Ну он писал 7 сообщений.", c)
        assert text == "сообщений с совпадением: 9"
        assert stats["corrected"] is True
        assert stats["reason"] == nc.NUMERIC_CLAIM_CORRECTED

    def test_correction_removes_unverified_part(self):
        text, stats = nc.apply_numeric_guard(
            "Да он тебе 5 раз это говорил.", _contract())
        assert text == "" and stats["fallback"] is True
        # обычная реплика без чисел не трогается (байт-паритет)
        text2, stats2 = nc.apply_numeric_guard("привет, как дела?",
                                               _contract())
        assert text2 == "привет, как дела?" and stats2 == {}

    def test_caveat_when_stats_expected_but_unverified(self):
        text, stats = nc.apply_numeric_guard(
            "он писал 7 сообщений", _contract(expected=True))
        assert text == nc.NUMERIC_CLAIM_CAVEAT and stats["fallback"] is True


# ── T-4931: контроль на всех путях отправки ─────────────────────────────────

class TestNumericGuardVerbalize:
    @pytest.mark.system2
    @pytest.mark.asyncio
    async def test_retry_once_then_corrected(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "postprocess_form_guard_enabled",
                            lambda: False)
        c = _contract(claims=(_claim(),), phrase="сообщений с совпадением: 9",
                      expected=True)
        seen: list = []

        async def gen(messages):
            seen.append(messages[-1]["content"])
            return ("он писал 7 сообщений" if len(seen) == 1
                    else "он писал 9 сообщений")

        text, stats = await nc.verbalize_validated(
            gen, [{"role": "user", "content": "x"}], numeric_contract=c)
        assert text == "он писал 9 сообщений"
        assert stats["numeric_claim_mismatch"] == 1
        assert stats["numeric_claim_retry"] is True
        assert stats["numeric_claim_reason"] == nc.NUMERIC_CLAIM_CORRECTED
        assert "9" in seen[1]          # повтор несёт verified_phrase

    @pytest.mark.system2
    @pytest.mark.asyncio
    async def test_retry_exhausted_deterministic_fallback(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "postprocess_form_guard_enabled",
                            lambda: False)
        c = _contract(claims=(_claim(),), phrase="сообщений с совпадением: 9",
                      expected=True)

        async def gen(messages):
            return "он писал 7 сообщений"

        text, stats = await nc.verbalize_validated(
            gen, [{"role": "user", "content": "x"}], numeric_contract=c)
        assert text == "сообщений с совпадением: 9"     # verified_phrase
        assert stats["numeric_claim_fallback"] is True
        assert stats["numeric_claim_reason"] == nc.NUMERIC_CLAIM_FALLBACK
        assert stats["attempts"] == 2                   # ≤1 коррекция

    @pytest.mark.system2
    @pytest.mark.asyncio
    async def test_no_claims_caveat(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "postprocess_form_guard_enabled",
                            lambda: False)

        async def gen(messages):
            return "он писал 7 сообщений"

        text, stats = await nc.verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            numeric_contract=_contract(expected=True))
        assert text == nc.NUMERIC_CLAIM_CAVEAT
        assert stats["numeric_claim_fallback"] is True

    @pytest.mark.system2
    @pytest.mark.asyncio
    async def test_k2_off_parity(self, monkeypatch):
        """K2 OFF: numeric-контракт игнорируется, один вызов, без новых
        ключей stats (байт-паритет 2.58.55)."""
        monkeypatch.setattr(mca_gates, "numeric_claim_guard_enabled",
                            lambda: False)
        calls = 0

        async def gen(messages):
            nonlocal calls
            calls += 1
            return "он писал 7 сообщений"

        text, stats = await nc.verbalize_validated(
            gen, [{"role": "user", "content": "x"}],
            numeric_contract=_contract(claims=(_claim(),)))
        assert text == "он писал 7 сообщений" and calls == 1
        assert "numeric_claim_mismatch" not in stats

    def test_apply_guard_none_and_off_parity(self, monkeypatch):
        assert nc.apply_numeric_guard("текст 5 сообщений", None) == (
            "текст 5 сообщений", {})
        monkeypatch.setattr(mca_gates, "numeric_claim_guard_enabled",
                            lambda: False)
        text, stats = nc.apply_numeric_guard("текст 5 сообщений",
                                             _contract())
        assert text == "текст 5 сообщений" and stats == {}

    def test_no_second_paraphraser_module(self):
        """T-4931: гард — в существующем контуре, второго парафразера нет."""
        assert not any("paraphrase" in name for name in dir(nc))
        assert callable(nc.check_numeric_claims)


class TestNumericGuardSendPaths:
    """Пять путей отправки: обычный/System2, fallback, lore-story (обход
    verbalizer), постпроцессор, финальная сборка — один и тот же гард."""

    @pytest.mark.system2
    @pytest.mark.asyncio
    async def test_system2_uses_contract_and_emits_event(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "postprocess_form_guard_enabled",
                            lambda: False)
        events: list = []
        monkeypatch.setattr(
            mca_events, "emit_mca_event",
            lambda name, **kw: events.append({"event_name": name, **kw}))
        svc = DirectChatService.__new__(DirectChatService)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[
            _SYNTH_JSON, "он писал 7 сообщений", "он писал 9 сообщений"])
        contract = _contract(claims=(_claim(),),
                             phrase="сообщений с совпадением: 9",
                             expected=True)
        text, _mode = await svc._synthesize_direct_answer(
            1, "q", _tool_raw(), None, numeric_contract=contract)
        assert text == "он писал 9 сообщений"
        guard = [e for e in events if e["event_name"] == "numeric_claim_guard"]
        assert guard and guard[0]["reason_code"] == "numeric_claim_corrected"

    @pytest.mark.asyncio
    async def test_fallback_lore_bypass_and_plain_covered(self):
        """Финальный гард покрывает fallback/прямой текст и lore-story в
        обход verbalizer (A41: число не публикуется)."""
        svc = DirectChatService.__new__(DirectChatService)
        ctx = ToolContext(CHAT_ID, "q")
        ctx.metric_results.append(
            cs.build_metric_result(_measure_dict(), _prefix_query()))
        contract = svc._numeric_contract_from_ctx(ctx)
        # прямой/fallback текст
        text, stats = nc.apply_numeric_guard("он писал 7 сообщений", contract)
        assert stats["corrected"] is True and "9" in text
        # lore-story (HTML, в обход verbalizer)
        story = "<b>он писал 7 сообщений</b> за всё время."
        text2, stats2 = nc.apply_numeric_guard(story, contract)
        assert "он писал" not in text2 and stats2["corrected"] is True
        assert "9" in text2

    def test_contract_from_ctx_claims_and_expected(self):
        svc = DirectChatService.__new__(DirectChatService)
        ctx = ToolContext(CHAT_ID, "q")
        assert svc._numeric_contract_from_ctx(ctx) is not None  # K2 ON
        ctx.stats_intent = cs.INTENT_CHAT_STATISTICS
        c = svc._numeric_contract_from_ctx(ctx)
        assert c.stats_expected is True and c.claims == ()
        ctx.metric_results.append(
            cs.build_metric_result(_measure_dict(), _prefix_query()))
        c2 = svc._numeric_contract_from_ctx(ctx)
        assert c2.claims and c2.verified_phrase

    def test_k2_off_contract_none(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "numeric_claim_guard_enabled",
                            lambda: False)
        svc = DirectChatService.__new__(DirectChatService)
        ctx = ToolContext(CHAT_ID, "q")
        assert svc._numeric_contract_from_ctx(ctx) is None

    def test_all_three_off_full_parity(self, monkeypatch):
        """K1+K2+K3 OFF: ни классификатора, ни контракта, ни stats-режима,
        ни FIX-контракта truncation (байт-паритет 2.58.55)."""
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled",
                            lambda: False)
        monkeypatch.setattr(mca_gates, "numeric_claim_guard_enabled",
                            lambda: False)
        monkeypatch.setattr(mca_gates, "stats_intent_enabled",
                            lambda: False)
        svc = DirectChatService.__new__(DirectChatService)
        ctx = ToolContext(CHAT_ID, "q")
        assert svc._numeric_contract_from_ctx(ctx) is None
        block, intent = svc._stats_intent_block(
            CHAT_ID, "Сколько раз я это писал?", "", True)
        assert block == "" and intent is None
        legacy = json.loads(_dig_json_payload(
            {"total_mentions": 5, "mentions_by_authors": {},
             "snippets": ["t"], "facts": []}, 30))
        assert legacy == {"truncated": True, "total_mentions": 5}

    @pytest.mark.asyncio
    async def test_handle_final_guard_blocks_ungrounded_number(
            self, monkeypatch):
        """Реальный `handle` (K2 ON): незаземлённое число не публикуется
        (финальная сборка — та же функция `apply_numeric_guard`)."""
        from tests.test_direct_chat import (
            FakeLLM, FakeMemory, _bot, _force_self_awareness, _make_service,
            _message)
        _force_self_awareness(monkeypatch, False)
        llm = FakeLLM(text="Да я тебе 5 раз это говорил. Ну и что?")
        service = _make_service(memory=FakeMemory(window=[]), llm=llm)
        bot = _bot()
        msg = _message(text="ты меня никогда не называл шизом",
                       message_id=77)
        await service.handle(bot, msg, msg.from_user)
        sent = bot.send_message.await_args.args[1]
        assert "5 раз" not in sent
        assert "Ну и что" in sent


# ── T-4929/T-4932: stats-режим инструмента и урезание ───────────────────────

class TestStatsToolMode:
    @pytest.mark.asyncio
    async def test_stats_mode_typed_payload_and_registry(self):
        db = await _truth_db()
        try:
            router = ToolRouter(ToolDeps(search=MagicMock(),
                                         memory=MagicMock(), db=db))
            ctx = ToolContext(CHAT_ID, "шиз")
            out = await router.dispatch("query_chat_memory", {
                "query": "шиз", "time_range": "all",
                "stats": {"metric": "messages", "match_mode": "prefix",
                          "phrase": "шиз"}}, ctx)
            payload = json.loads(out)
            assert payload["status"] == "ok" and payload["value"] == 9
            assert payload["unit"] == "messages"
            assert payload["method"] == cs.FTS_PREFIX_OR_METHOD
            assert "total_mentions" not in payload
            assert payload["verified_phrase"]
            assert payload["metric_id"].startswith("cs:")
            assert ctx.metric_results and ctx.metric_results[0].value == 9
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_stats_mode_author_resolved_by_id(self):
        db = await _truth_db()
        try:
            aliases = MagicMock()
            aliases._aliases = {"10": "Вася"}
            router = ToolRouter(ToolDeps(search=MagicMock(),
                                         memory=MagicMock(), db=db,
                                         aliases=aliases))
            ctx = ToolContext(CHAT_ID, "q")
            out = await router.dispatch("query_chat_memory", {
                "query": "шиз", "stats": {
                    "metric": "messages", "match_mode": "prefix",
                    "phrase": "шиз", "author": "Вася"}}, ctx)
            payload = json.loads(out)
            assert payload["value"] == 5
            assert payload["scope"]["author_ids"] == [10]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_stats_mode_ambiguous_author_unsupported(self):
        db = await _truth_db()
        try:
            aliases = MagicMock()
            aliases._aliases = {"10": "Вася", "20": "Вася"}
            router = ToolRouter(ToolDeps(search=MagicMock(),
                                         memory=MagicMock(), db=db,
                                         aliases=aliases))
            ctx = ToolContext(CHAT_ID, "q")
            out = await router.dispatch("query_chat_memory", {
                "query": "шиз", "stats": {
                    "metric": "messages", "match_mode": "prefix",
                    "phrase": "шиз", "author": "Вася"}}, ctx)
            payload = json.loads(out)
            assert payload["status"] == "unsupported"
            assert payload["value"] is None
            assert payload["reason"] == "ambiguous_identity"
            assert ctx.metric_results == []       # не угадываем
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_stats_mode_off_parity(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled",
                            lambda: False)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.count_mentions = AsyncMock(return_value={
            "count": 5, "first_seen": None, "last_seen": None})
        memory.vector_search = AsyncMock(return_value=[])
        memory.get_rag_context = AsyncMock(return_value="")
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        ctx = ToolContext(CHAT_ID, "шиз")
        out = await router.dispatch("query_chat_memory", {
            "query": "шиз", "stats": {"metric": "messages",
                                      "match_mode": "prefix",
                                      "phrase": "шиз"}}, ctx)
        assert "Найдено 5 упоминаний «шиз»" in out
        assert ctx.metric_results == []

    def test_payload_trim_keeps_mandatory_no_bare_number(self):
        payload = cs.metric_result_payload(_measure_dict(examples=[
            {"item_id": f"msg:{i}", "text": "x" * 100}
            for i in range(20)]), _prefix_query())
        out = json.loads(_stats_json_payload(payload, 800))
        for key in ("metric_id", "status", "value", "unit", "method",
                    "method_label", "scope", "coverage"):
            assert key in out
        assert len(out.get("examples") or []) < 20
        tiny = json.loads(_stats_json_payload(payload, 60))
        assert tiny["status"] == "insufficient_output_budget"
        assert tiny.get("value") is None
        assert "total_mentions" not in json.dumps(tiny)

    def test_schema_stats_additive_canon_twelve(self):
        from services.tool_schemas import (
            TOOL_CALLING_TOOLS, TOOL_QUERY_CHAT_MEMORY)
        props = TOOL_QUERY_CHAT_MEMORY["function"]["parameters"]["properties"]
        assert "stats" in props
        assert props["stats"]["properties"]["metric"]["enum"] == [
            "messages", "occurrences", "distinct_authors"]
        assert len(TOOL_CALLING_TOOLS) == 12

    @pytest.mark.asyncio
    async def test_dig_measurement_registers_claim(self):
        """dig-измерение тоже даёт NumericClaim хода (число 5 проверяемо),
        при этом ошибка счётчика claim не создаёт (value=None)."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.search_messages_fts_count_by_author = AsyncMock(return_value={
            "count": 5, "first_seen": None, "last_seen": None, "max_id": 3,
            "unknown_count": 0, "by_author": []})
        memory.db = db
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        ctx = ToolContext(CHAT_ID, "шиз")
        await router.dispatch("dig_into_lore",
                              {"query": "шиз", "mode": "messages"}, ctx)
        assert ctx.metric_results and ctx.metric_results[0].value == 5
        svc = DirectChatService.__new__(DirectChatService)
        contract = svc._numeric_contract_from_ctx(ctx)
        assert nc.check_numeric_claims("он писал 5 сообщений",
                                       contract) is None
        assert nc.check_numeric_claims("он писал 7 сообщений",
                                       contract) == nc.NUMERIC_CLAIM_MISMATCH


# ── T-4932: lore UPD-ветка unchanged → перепроверка ─────────────────────────

class TestLoreStatsRecheck:
    @pytest.mark.asyncio
    async def test_unchanged_branch_flags_recheck_not_deletes(
            self, monkeypatch):
        monkeypatch.setattr(cs, "measure",
                            AsyncMock(return_value=_measure_dict()))
        db = MagicMock()
        db.get_lore_story = AsyncMock(return_value={
            "story": "<b>упоминаний: 5</b>", "last_ts": 100,
            "updated_at": 1})
        db.lore_graph_slice = AsyncMock(
            return_value={"facts": [], "edges": []})
        db.lore_dense_dialogs = AsyncMock(return_value={
            "dialogs": [], "total": 0, "earliest": None, "latest": None})
        svc = LoreCompilerService(db, MagicMock(), aliases=None, tz_name="")
        result = await svc.compile(CHAT_ID, "шиз тема")
        assert result["status"] == "ok" and result["unchanged"] is True
        assert result["stats_recheck"] is True
        assert result["metric_result"] is None
        # lore НЕ удаляется и не перезаписывается
        assert result["story"] == "<b>упоминаний: 5</b>"
        db.upsert_lore_story.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_flags_and_registers_fresh_metric(self, monkeypatch):
        from services import lore_compiler_service as lcs
        from services import tool_router as tr
        metric = cs.build_metric_result(_measure_dict(), _prefix_query())

        class FakeLore:
            def __init__(self, *args, **kwargs):
                pass

            async def compile(self, chat_id, topic):
                return {"status": "ok", "is_update": False,
                        "story": "свежая история", "stats_recheck": False,
                        "metric_result": metric}

        monkeypatch.setattr(lcs, "LoreCompilerService", FakeLore)
        monkeypatch.setattr(tr, "resolve_lore_compiler_flag",
                            AsyncMock(return_value=True))
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     db=MagicMock(), llm=MagicMock()))
        ctx = ToolContext(CHAT_ID, "q")
        out = await router.dispatch("compile_lore_story", {"topic": "шиз"},
                                    ctx)
        assert ctx.lore_compiled is True
        assert ctx.metric_results == [metric]
        assert ctx.lore_stats_recheck is False
        assert '"stats_recheck": false' in out

    @pytest.mark.asyncio
    async def test_tool_flags_unchanged_recheck_event(self, monkeypatch):
        from services import lore_compiler_service as lcs
        from services import tool_router as tr

        class FakeLore:
            def __init__(self, *args, **kwargs):
                pass

            async def compile(self, chat_id, topic):
                return {"status": "ok", "is_update": True, "unchanged": True,
                        "story": "старая история", "stats_recheck": True,
                        "metric_result": None}

        monkeypatch.setattr(lcs, "LoreCompilerService", FakeLore)
        monkeypatch.setattr(tr, "resolve_lore_compiler_flag",
                            AsyncMock(return_value=True))
        events: list = []
        monkeypatch.setattr(
            mca_events, "emit_mca_event",
            lambda name, **kw: events.append({"event_name": name, **kw}))
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     db=MagicMock(), llm=MagicMock()))
        ctx = ToolContext(CHAT_ID, "q")
        out = await router.dispatch("compile_lore_story", {"topic": "шиз"},
                                    ctx)
        assert ctx.lore_stats_recheck is True
        assert any(e.get("reason_code") == "lore_stats_recheck_flagged"
                   for e in events)
        assert '"stats_recheck": true' in out


# ── T-4934: диагностический журнал §24.5 ────────────────────────────────────

class TestDiagnosticJournal:
    def test_diagnostic_r17_safe_links_no_sql(self):
        mr = cs.build_metric_result(_measure_dict(examples=[
            {"item_id": "msg:1", "text": "шиз"}]), _prefix_query())
        diag = cs.build_measurement_diagnostic(mr,
                                               intent="chat_statistics")
        blob = json.dumps(diag, ensure_ascii=False).casefold()
        assert "шиз" not in blob
        assert "select " not in blob and "sql" not in blob
        assert diag["metric_id"] == mr.metric_id
        assert diag["query_spec_hash"] == mr.query_spec_hash
        assert diag["example_source_refs"] == ["msg:1"]
        assert diag["claims"] and diag["claims"][0]["unit"] == "messages"
        assert diag["method"] and diag["unit"] and diag["coverage"]
        assert diag["intent"] == "chat_statistics"

    def test_emit_measurement_event_status_and_error_separately(
            self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            mca_events, "emit_mca_event",
            lambda name, **kw: calls.append({"event_name": name, **kw}))
        mr = cs.build_metric_result(_measure_dict(), _prefix_query())
        cs.emit_measurement_event(mr, chat_id=CHAT_ID,
                                  intent="chat_statistics")
        assert calls[0]["event_name"] == "chat_statistics"
        assert calls[0]["chat_id"] == CHAT_ID and calls[0]["status"] == "ok"
        assert "reason_code" not in calls[0]
        err = cs.build_metric_result(
            _measure_dict(status="error", value=None,
                          reason="stats_count_error"), _prefix_query())
        cs.emit_measurement_event(err, chat_id=CHAT_ID)
        assert calls[1]["status"] == "error"
        assert calls[1]["reason_code"] == "stats_count_error"


# ── T-4935: процесс/стадии в реестре mca-17a ────────────────────────────────

class TestProcessRegistry:
    def test_chat_statistics_process_v1(self):
        from services import mca_process_registry as reg
        proc = reg.get_process("chat.statistics")
        assert proc is not None and proc.version == "1"
        assert proc.stages == ("intent", "measurement", "claim_check",
                               "delivery")
        assert proc.enabled_gate == "MCA_CHAT_STATISTICS_ENABLED"
        assert proc.widget_id == "Измерения, проверки и отказы"
        assert proc.stages_to_events["measurement"] == "chat_statistics"
        assert proc.stages_to_events["claim_check"] == "numeric_claim_guard"
        ids = {p.process_id for p in reg.PROCESS_REGISTRY}
        assert "episodes.timeline" not in ids

    def test_direct_reply_claim_check_amended(self):
        from services import mca_process_registry as reg
        proc = reg.get_process("direct.reply")
        assert "claim_check" in proc.stages
        assert proc.stages_to_events["claim_check"] == "numeric_claim_guard"
        assert "numeric_claim_guard" in proc.event_names
        assert "claim_check" in proc.instrumentation

    def test_off_honest_status(self, monkeypatch):
        from services import mca_process_registry as reg
        proc = reg.get_process("chat.statistics")
        assert reg.runtime_status(
            proc, event_names_present=frozenset({"chat_statistics"})) == \
            reg.STATUS_IMPLEMENTED
        assert reg.runtime_status(
            proc, event_names_present=frozenset()) == reg.STATUS_NOT_RUN
        monkeypatch.setattr(mca_gates, "chat_statistics_enabled",
                            lambda: False)
        assert reg.runtime_status(proc) == reg.STATUS_DISABLED

    def test_reason_codes_eleven_sanctioned(self):
        sanctioned = {
            "chat_stats_intent", "historical_evidence_intent",
            "social_banter_intent", "stats_count_error",
            "stats_partial_corpus", "stats_unsupported",
            "insufficient_output_budget", "numeric_claim_mismatch",
            "numeric_claim_corrected", "numeric_claim_fallback",
            "lore_stats_recheck_flagged"}
        assert sanctioned <= mca_events.REASON_CODES
        assert len(sanctioned) == 11


# ── T-4936: полный регрессионный список §24.5 — каждый пункт к тесту ────────

REGRESSION_245_TESTS = {
    "or_vs_phrase": "TestStatsQueryContract.test_a38_different_units_and_values",
    "three_occurrences_one_message":
        "TestStatsQueryContract.test_a38_different_units_and_values",
    "two_same_names":
        "TestStatsQueryContract.test_two_same_names_do_not_merge_and_alias_keeps_id",
    "alias_change_keeps_id":
        "TestStatsQueryContract.test_two_same_names_do_not_merge_and_alias_keeps_id",
    "author_filter_before_limit":
        "TestStatsQueryContract.test_a39_author_filter_before_limit",
    "year_timezone":
        "TestStatsQueryContract.test_time_bounds_timezone_dates",
    "quote_forward_unknown":
        "TestStatsQueryContract.test_a39_time_and_quote_filters_identical",
    "bot_messages":
        "TestStatsQueryContract.test_unsupported_paths_not_guessed",
    "duplicate_import":
        "TestDedupWatermarkBounded.test_duplicate_import_partial_not_silent_double_count",
    "counter_error":
        "TestDedupWatermarkBounded.test_counter_error_is_not_zero",
    "payload_truncation":
        "TestStatsToolMode.test_payload_trim_keeps_mandatory_no_bare_number",
    "number_from_other_metric":
        "TestNumericClaimsCheck.test_unit_compatibility",
    "zero_in_partial_corpus":
        "TestMetricResultContract.test_partial_coverage_zero_not_never",
    "stale_cache_after_import":
        "TestMetricResultContract.test_repeat_after_import_recompute_no_cache",
    "lore_story_bypass":
        "TestNumericGuardSendPaths.test_fallback_lore_bypass_and_plain_covered",
    "banter_vs_request":
        "TestStatsIntent.test_banter_without_request_no_report",
}


class TestRegressionList245:
    def test_each_item_bound_to_existing_test(self):
        """§24.5 (:1171): каждый пункт привязан к реально существующему тесту."""
        import sys
        module = sys.modules[__name__]
        assert len(REGRESSION_245_TESTS) == 16
        for item, dotted in REGRESSION_245_TESTS.items():
            cls_name, test_name = dotted.split(".", 1)
            cls = getattr(module, cls_name, None)
            assert cls is not None, item
            assert callable(getattr(cls, test_name, None)), item
