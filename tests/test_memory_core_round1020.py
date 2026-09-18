"""Раунд 10.20 (Фаза B, БЛОК 0/2/5) — тесты «Ядра памяти» (T-1884).

Покрытие:
* `format_context_item` — все kind, R16-опускание пустых полей, схлопывание
  пробелов, stale-суффикс, ID-политика, inventory 14 точек;
* `order_rag_facts_asc` — ASC-хронология (состав не меняется);
* `dig_into_lore` — JSON-контракт + `mentions_by_authors` + db-метод
  `search_messages_fts_count_by_author` (GROUP BY, R16);
* Time Injection — строка времени ПЕРВЫМ user-блоком, system байт-стабилен;
  каталог-ключ `limits.chat_timezone` (select, человеческие названия);
* `/summary` — маркировка архива;
* «Сводка» — `-1` → «Безлимит (∞)» + реактивность/один запрос.
"""
import json
import re

import pytest

from services import canonical_context as cc
from services.payload_builder import build_messages

SETTINGS_TZ = "Asia/Yekaterinburg"


# ── T-1873/T-1874: канонический форматтер ───────────────────────────────────

class TestFormatContextItem:
    def test_msg_full_format(self):
        line = cc.format_context_item(
            ts=1714500000, author="Толян", item_id="tg:4123",
            forward_source="канал X", text="текст", kind="msg")
        assert re.fullmatch(
            r"\[\d{2}\.\d{2}\.\d{4} \d{2}:\d{2} \| Толян \| tg:4123 "
            r"\| Переслано: канал X\]: текст", line)

    def test_fact_month_year(self):
        line = cc.format_context_item(
            ts=1714500000, author="Ваня", item_id="fact:991",
            text="факт", kind="fact")
        assert re.fullmatch(r"\[\d{2}\.\d{4} \| Ваня \| fact:991\]: факт", line)

    def test_archive_marker(self):
        line = cc.format_context_item(
            ts=1714500000, author="Ваня", item_id="tg:1", text="архив",
            kind="archive")
        assert line.startswith("[Архивная справка: ")
        assert re.fullmatch(
            r"\[Архивная справка: \d{2}\.\d{4} \| Ваня \| tg:1\]: архив", line)

    def test_archive_without_metadata_keeps_marker(self):
        assert cc.format_context_item(text="архив", kind="archive") == \
            "[Архивная справка]: архив"

    def test_missing_fields_omitted_with_separator(self):
        """R16: пустые метаданные не выводятся заглушками."""
        assert cc.format_context_item(ts=None, author=None, item_id=None,
                                      text="голый", kind="msg") == "голый"
        assert cc.format_context_item(ts=1714500000, text="x") == \
            "[30.04.2024 18:00]: x"

    def test_whitespace_squashed(self):
        line = cc.format_context_item(
            ts=1714500000, author="вася\n\tпетя", item_id="msg:1",
            text="a\nb\tc", kind="msg")
        assert "\n" not in line and "\t" not in line
        assert "вася петя" in line
        assert line.endswith("]: a b c")

    def test_stale_suffix(self):
        line = cc.format_context_item(
            ts=1714500000, item_id="fact:1", text="старо", kind="fact",
            stale=True)
        assert line.endswith("старо (Внимание: возможно устарело)")

    def test_unknown_kind_falls_back_to_msg(self):
        line = cc.format_context_item(ts=1714500000, text="x", kind="bogus")
        assert line == "[30.04.2024 18:00]: x"

    def test_broken_ts_is_safe(self):
        assert cc.format_context_item(ts="not-a-ts", text="x") == "x"
        assert cc.format_context_item(ts=0, text="x") == "x"

    def test_resolve_item_id_policy(self):
        assert cc.resolve_item_id(tg_message_id=5, message_id=9,
                                  fact_id=1) == "tg:5"
        assert cc.resolve_item_id(message_id=9, fact_id=1) == "msg:9"
        assert cc.resolve_item_id(fact_id=1) == "fact:1"
        assert cc.resolve_item_id() == ""

    def test_inventory_14_points(self):
        """T-1873/T-1874: реестр из 14 точек подачи контекста (spec §2.3)."""
        assert len(cc.CONTEXT_POINTS) == 14
        ids = [p.pid for p in cc.CONTEXT_POINTS]
        assert len(ids) == len(set(ids))
        for point in cc.CONTEXT_POINTS:
            assert point.path.endswith(".py") or point.path == "web/app.js"
            assert point.kind in cc.VALID_KINDS
            # Ред. 3 (ADR-1020-1): per-point ярус представления + pattern
            assert point.representation in cc.VALID_REPRESENTATIONS
            if point.representation != cc.REPRESENTATION_LABEL_EXEMPT:
                assert point.pattern, point.pid


# ── T-1874: инвентарный тест «нет голого текста» ИЗ РЕЕСТРА ─────────────────
# Тест генерируется из `CONTEXT_POINTS` (per-point pattern). `_SAMPLES` даёт
# РЕАЛЬНЫЕ строки-элементы данных каждой точки (получены её рендерером);
# ручного «списка проверок» нет — добавили точку в реестр → обязан появиться
# сэмпл (test_registry_samples_cover_all_points).

def _sample_chat_history():
    from services.summary_xml import XmlGroundingBuilder
    row = {"id": 1, "timestamp": 1714500000, "author_name": "вася",
           "user_id": 10, "text": "привет", "reply_to_id": None,
           "media_type": "text"}
    return XmlGroundingBuilder().build([row]).splitlines()[1:2]


def _sample_global():
    from tests.test_direct_chat import _make_service
    svc = _make_service()
    row = {"user_id": 10, "author_name": "вася", "text": "привет",
           "timestamp": 1714500000, "tg_message_id": 5, "id": 9,
           "is_forward": 1, "forward_source": "канал X"}
    return [svc._context_row_line(row, {})]


def _sample_thread():
    from tests.test_direct_chat import _make_service
    from services.direct_chat_service import _ChainItem
    svc = _make_service()
    return [
        svc._chain_line(_ChainItem(10, "вася", "привет", False,
                                   1714500000, "tg:5", None), {}),
        svc._chain_line(_ChainItem(None, "test_bot", "ответ", True,
                                   None, "tg:6", None), {}),
    ]


def _sample_direct_rag():
    from services.summary_memory import _format_origin_labeled_line
    return [
        _format_origin_labeled_line(
            ("chat_history", "факт", 1714500000, "Толян")),
        # S10.20-9: обогащённый 6-кортеж (ID-политика + «Переслано»).
        _format_origin_labeled_line(
            ("chat_history", "факт", 1714500000, "Толян", "fact:1",
             "канал X")),
    ]


def _sample_legacy_rag():
    from services.summary_memory import _fact_prefix
    from services.canonical_context import format_context_item
    return [
        _fact_prefix(1714500000, "Толян") + "факт",
        # S10.20-9: legacy <context> с 6-кортежем → канонический header факта.
        format_context_item(
            ts=1714500000, author="Толян", item_id="fact:1",
            forward_source="канал X", text="факт", kind="fact"),
    ]


def _sample_video_web():
    from services.summary_memory import _fact_prefix
    return [_fact_prefix(1714500000, "Толян") + "выжимка"]


def _sample_dig():
    return [cc.format_context_item(
        ts=1714500000, author="Толян", item_id="tg:5", text="факт",
        kind="msg")]


def _sample_query_memory():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from tests.test_tool_router import _ctx, _deps
    from services.tool_router import ToolRouter
    memory = MagicMock()
    memory.search_long_term = AsyncMock(return_value=[{
        "user_id": 10, "author_name": "вася", "text": "нашлось",
        "timestamp": 1714500000}])
    memory.count_mentions = AsyncMock(return_value={"count": 1})
    router = ToolRouter(_deps(memory=memory))
    out = asyncio.run(router._query_chat_memory(
        {"query": "x", "time_range": "all"}, _ctx()))
    return [ln for ln in out.splitlines() if ln.startswith("[")]


def _sample_history():
    from tests.test_tool_router import _deps
    from services.tool_router import ToolRouter
    router = ToolRouter(_deps())
    return router._history_lines([{
        "user_id": 10, "author_name": "вася", "text": "привет",
        "timestamp": 1714500000, "tg_message_id": 5, "id": 9,
        "is_forward": 1, "forward_source": "канал X"}])


def _sample_archive():
    return [cc.format_context_item(
        ts=1714500000, author="вася", text="архив", kind="archive")]


def _sample_dream():
    from services.dream_prompts import build_dream_user
    out = build_dream_user([{"id": 1, "fact": "факт",
                             "message_timestamp": 1714500000}])
    return [ln for ln in out.splitlines() if ln[:1].isdigit()]


def _sample_lore():
    from services.lore_worker import LoreWorker
    rows = [{"user_id": 10, "author_name": "вася", "text": "текст",
             "timestamp": 1714500000}]
    return LoreWorker._format_window(None, rows)


def _sample_nostalgia():
    from services.nostalgia_prompts import (
        _render_meme, format_golden_line, format_year_back_line)
    return [
        format_year_back_line({"text": "текст", "timestamp": 1714500000,
                               "author_name": "вася", "user_id": 10}),
        format_golden_line({"fact": "факт", "rag_ts": 1714500000}),
        _render_meme({"fact": "мем", "target_user": "вася"}),
    ]


def _sample_factcheck():
    from services.chat_context import format_chat_context
    from services.thread_chain import ChainItem, render_reply_chains
    row = {"user_id": 10, "author_name": "вася", "text": "привет",
           "timestamp": 1714500000, "tg_message_id": 5, "id": 9}
    # 10.23 (F2, R1023F2-07): под-блок цепочек — структурная обёртка
    # (label_exempt), внутренние строки — канонические.
    chains = render_reply_chains([
        ChainItem(10, "вася", "вопрос", False, 1714500000, "tg:5", None),
        ChainItem(None, "бот", "ответ", True, None, "tg:6", None),
    ])
    return [ln for ln in format_chat_context(
        [row], reply_chains=chains).splitlines()
        if ln.startswith("[") or ln.startswith("<reply_chains")
        or ln.startswith("</reply_chains>")]


_SAMPLES = {
    "chat_history": _sample_chat_history,
    "direct_global_verbatim": _sample_global,
    "direct_thread": _sample_thread,
    "direct_rag": _sample_direct_rag,
    "legacy_rag": _sample_legacy_rag,
    "dig_into_lore": _sample_dig,
    "query_chat_memory": _sample_query_memory,
    "get_recent_history": _sample_history,
    "summary_archive": _sample_archive,
    "dream": _sample_dream,
    "lore_worker": _sample_lore,
    "nostalgia": _sample_nostalgia,
    "factcheck_context": _sample_factcheck,
    "video_web_summary": _sample_video_web,
}


@pytest.mark.parametrize("point", cc.CONTEXT_POINTS, ids=lambda p: p.pid)
def test_no_bare_text_generated_from_registry(point):
    """Инвентарный «нет голого текста» из реестра: строки-элементы данных
    каждой точки несут метаданные (per-point pattern); служебные метки —
    allowlist (Р2)."""
    samples = _SAMPLES[point.pid]()
    assert samples, f"нет сэмпла строк для точки {point.pid}"
    check = re.compile(point.pattern)
    for line in samples:
        assert cc.is_label_exempt(line) or check.match(line), \
            f"{point.pid}: голая строка без метаданных: {line!r}"


def test_registry_samples_cover_all_points():
    assert set(_SAMPLES) == {p.pid for p in cc.CONTEXT_POINTS}


def test_self_echo_instruction_is_label_exempt():
    """Allowlist Р2: `_SELF_ECHO_INSTRUCTION` не подлежит форматированию."""
    from services.summary_memory import _SELF_ECHO_INSTRUCTION
    assert cc.is_label_exempt(_SELF_ECHO_INSTRUCTION)
    assert cc.is_label_exempt("фон: дословно последние 3 сообщений")
    assert cc.is_label_exempt("широкий фон: конспект")
    assert not cc.is_label_exempt("[01.01.1970 00:01 | вася]: привет")


# ── T-1874: обязательные сопутствующие фиксы (R23) + точки 2/3/8/13 ─────────

class TestStripContextHeader:
    def test_strips_canonical_header_with_nested_brackets(self):
        line = ("[30.04.2024 18:00 | вася [10] | msg:9 | Переслано: канал X]: "
                "привет: как дела")
        assert cc.strip_context_header(line) == "привет: как дела"

    def test_no_header_unchanged(self):
        assert cc.strip_context_header("петя: вася принёс торт") == \
            "петя: вася принёс торт"
        assert cc.strip_context_header("") == ""

    def test_line_markers_e1_canonical_header(self):
        """R23/E1: заголовок с `msg:<id>` не ломает маркеры важности."""
        from services.direct_chat_service import _line_markers
        names = frozenset(("вася",))
        canon = ("[30.04.2024 18:00 | вася [10] | msg:5]: "
                 "завтра в 12 идём смотреть дроны")
        assert _line_markers(canon, names) == {"number", "long"}
        # легаси-форма (без заголовка) — прежнее поведение сохраняется
        assert _line_markers("петя: вася принёс торт", names) == \
            {"name", "long"}

    def test_fact_tokens_f2_ignores_header(self):
        """R23/F2: дата-ID заголовка не добавляет токенов в дедуп."""
        from services.summary_memory import _fact_tokens
        line = ("[30.04.2024 18:00 | вася [10] | msg:5]: "
                "дроны летают высоко")
        assert _fact_tokens(line) == {"дроны", "летают", "высоко"}


class TestTierAPoints:
    """Точки 2/3/8/13 (ярус A) рендерятся каноническим `format_context_item`."""

    def test_point2_global_verbatim_canonical(self):
        from tests.test_direct_chat import _make_service
        svc = _make_service()
        row = {"user_id": 10, "author_name": "вася", "text": "привет",
               "timestamp": 1714500000, "tg_message_id": 5, "id": 9,
               "is_forward": 1, "forward_source": "канал X"}
        line = svc._context_row_line(row, {})
        assert line == ("[30.04.2024 18:00 | вася [10] | tg:5 | "
                        "Переслано: канал X]: привет")

    def test_point3_thread_user_ts_bot_no_ts(self):
        from tests.test_direct_chat import _make_service
        from services.direct_chat_service import _ChainItem
        svc = _make_service()
        user = svc._chain_line(_ChainItem(10, "вася", "вопрос", False,
                                          1714500000, "tg:5", None), {})
        bot = svc._chain_line(_ChainItem(None, "test_bot", "ответ", True,
                                         None, "tg:6", None), {})
        assert user == "[30.04.2024 18:00 | вася [10] | tg:5]: вопрос"
        # бот: ts ОПУЩЕН (в bot_replies времени сообщения нет — R16),
        # ID = tg:<current_id>, автор присутствует
        assert bot == "[test_bot [bot] | tg:6]: ответ"

    def test_point8_history_canonical(self):
        from tests.test_tool_router import _deps
        from services.tool_router import ToolRouter
        router = ToolRouter(_deps())
        lines = router._history_lines([{
            "user_id": 10, "author_name": "вася", "text": "привет",
            "timestamp": 1714500000, "tg_message_id": 5, "id": 9,
            "is_forward": 0, "forward_source": "x"}])
        assert lines == ["[30.04.2024 18:00 | вася | tg:5]: привет"]

    def test_point13_factcheck_context_canonical(self):
        from services.chat_context import format_chat_context
        row = {"user_id": 10, "author_name": "вася", "text": "привет",
               "timestamp": 1714500000, "tg_message_id": 5, "id": 9}
        out = format_chat_context([row])
        assert "[30.04.2024 18:00 | вася | tg:5]: привет" in out


# ── T-1876: ASC-хронология ───────────────────────────────────────────────────

class TestOrderRagFactsAsc:
    def test_stable_asc_and_same_composition(self):
        from services.summary_memory import order_rag_facts_asc
        facts = [("chat_history", "b", 300), ("chat_history", "a", 100),
                 ("search_fact", "c", 200)]
        ordered = order_rag_facts_asc(facts)
        assert [f[2] for f in ordered] == [100, 200, 300]
        assert set(map(tuple, ordered)) == set(map(tuple, facts))

    def test_missing_ts_first_and_2tuples_safe(self):
        from services.summary_memory import order_rag_facts_asc
        facts = [("chat_history", "x", 50), ("chat_history", "no-ts"),
                 ("chat_history", "y", None)]
        ordered = order_rag_facts_asc(facts)
        assert ordered[-1][1] == "x"
        assert order_rag_facts_asc([]) == []


# ── T-1878: dig_into_lore JSON + GROUP BY authors ───────────────────────────

class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, rows):
        self.rows = list(rows)
        self.sql = None
        self.params = None

    async def execute(self, sql, params):
        self.sql = sql
        self.params = params
        return _FakeCursor(self.rows)


class TestCountByAuthor:
    @pytest.mark.asyncio
    async def test_group_by_author_aggregates(self):
        from services.database import DatabaseService as Database
        db = Database.__new__(Database)
        conn = _FakeConn([
            {"cnt": 2, "first_ts": 100, "last_ts": 500, "author_name": "Толян",
             "user_id": 1},
            {"cnt": 5, "first_ts": 50, "last_ts": 900, "author_name": "Ваня",
             "user_id": 2},
        ])
        db.db = conn
        out = await db.search_messages_fts_count_by_author(
            -100, "матч", since_ts=10, until_ts=1000)
        assert out["count"] == 7
        assert out["first_seen"] == 50 and out["last_seen"] == 900
        # сортировка по убыванию count
        assert [a["author_name"] for a in out["by_author"]] == ["Ваня", "Толян"]
        assert "GROUP BY" in conn.sql
        assert conn.params == (-100, "матч", 10, 1000)

    @pytest.mark.asyncio
    async def test_empty_rows(self):
        from services.database import DatabaseService as Database
        db = Database.__new__(Database)
        db.db = _FakeConn([])
        out = await db.search_messages_fts_count_by_author(-100, "x")
        assert out == {"count": 0, "first_seen": None, "last_seen": None,
                       "by_author": []}


class TestDigJsonContract:
    @pytest.mark.asyncio
    async def test_json_contract_with_mentions_by_authors(self):
        from tests.test_tool_router import _ctx, _deps
        from services.summary_aliases import AliasResolver
        from unittest.mock import AsyncMock, MagicMock
        from services.tool_router import ToolRouter

        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        db = MagicMock()
        db.search_graph_facts_fts = AsyncMock(return_value=[])
        db.dig_graph_related_names = AsyncMock(return_value=[])
        db.dig_fallback_target_names = AsyncMock(return_value=[])
        db.search_messages_fts_count_by_author = AsyncMock(return_value={
            "count": 42, "first_seen": 1714500000, "last_seen": 1754000000,
            "by_author": [
                {"author_name": "Ваня", "user_id": 2, "count": 40},
                {"author_name": "Толян", "user_id": 1, "count": 2},
            ],
        })
        memory.db = db
        aliases = AliasResolver('{"2": "Ваня", "1": "Толян"}')
        router = ToolRouter(_deps(memory=memory, aliases=aliases))
        out = await router.dispatch("dig_into_lore", {"query": "машина"}, _ctx())
        payload = json.loads(out)
        assert payload["total_mentions"] == 42
        assert payload["mentions_by_authors"] == {"Ваня": 40, "Толян": 2}
        assert payload["first_seen"]
        assert payload["last_seen"]
        assert payload["snippets"] == [] and payload["facts"] == []

    @pytest.mark.asyncio
    async def test_not_found_is_json_with_zero_count(self):
        from tests.test_tool_router import _ctx, _deps
        from unittest.mock import AsyncMock, MagicMock
        from services.tool_router import ToolRouter

        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        memory.db = None
        router = ToolRouter(_deps(memory=memory))
        out = await router.dispatch("dig_into_lore", {"query": "нет"}, _ctx())
        payload = json.loads(out)
        assert payload["total_mentions"] == 0
        assert payload["status"] == "not_found"
        assert "ничего не нашёл" in payload["message"]


# ── T-1879: Time Injection + limits.chat_timezone ───────────────────────────

class TestTimeInjection:
    def test_time_line_first_user_block(self):
        msgs = build_messages("sys", ["блок1", "блок2"],
                              time_line="[Текущее время в чате: X]")
        assert msgs[0] == {"role": "system", "content": "sys"}
        assert msgs[1]["content"] == \
            "[Текущее время в чате: X]\n\nблок1\n\nблок2"

    def test_system_static_between_calls(self):
        """Prompt Caching (О2): system байт-в-байт между запросами."""
        first = build_messages("SYS", ["a"], time_line="[T1]")
        second = build_messages("SYS", ["a"], time_line="[T2]")
        assert first[0] == second[0] == {"role": "system", "content": "SYS"}
        assert first[1]["content"] != second[1]["content"]

    def test_no_time_line_backward_compatible(self):
        msgs = build_messages("sys", ["a", "b"])
        assert msgs[1]["content"] == "a\n\nb"

    def test_format_chat_time_shape_and_tz(self):
        line = cc.format_chat_time(now=1714500000, tz_name="Europe/Moscow")
        assert re.fullmatch(
            r"\[Текущее время в чате: \d{2}\.\d{2}\.\d{4}, \d{2}:\d{2}, "
            r"(Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|"
            r"Воскресенье)\]", line)

    def test_invalid_tz_falls_back(self):
        line = cc.format_chat_time(now=1714500000, tz_name="Mars/Olympus",
                                   fallback_tz=SETTINGS_TZ)
        assert "Текущее время в чате" in line

    def test_catalog_has_chat_timezone_select(self):
        from services import param_catalog as pc
        spec = pc.get("CHAT_TIMEZONE")
        assert spec is not None
        assert spec.pg_key == "limits.chat_timezone"
        assert spec.widget == "select"
        assert spec.select_options and spec.select_labels
        assert len(spec.select_options) == len(spec.select_labels)
        assert "UTC+3 (Москва)" in spec.select_labels
        assert "Europe/Moscow" in spec.select_options


# ── T-1877: /summary — архив ≠ свежее ───────────────────────────────────────

class TestSummaryArchiveMarking:
    def test_archive_blocks_marked(self):
        from services.summary_generator import SummaryGenerator
        result = SummaryGenerator._compose_user_content(
            "<chat_history/>", ["цитата"], ["факт"], ["граф-факт"])
        assert "<memory>\n[Архивная справка]: цитата\n</memory>" in result
        assert "<facts>\n[Архивная справка]: факт\n</facts>" in result
        assert ("<historical_graph_facts>\n[Архивная справка]: граф-факт\n"
                "</historical_graph_facts>") in result
        assert result.index("<historical_graph_facts>") < \
            result.index("<chat_history/")

    def test_summary_canon_has_archive_rule(self):
        from services.summary_prompts import SYSTEM_PROMPT
        assert "РАЗДЕЛЕНИЕ СВЕЖЕГО И АРХИВА:" in SYSTEM_PROMPT
        assert "Архивная справка" in SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ не выдавай архивное за сегодняшние новости." \
            in SYSTEM_PROMPT


# ── T-1882: «Безлимит (∞)» + реактивность ───────────────────────────────────

class TestUnlimitedWidgets:
    def test_backend_uses_single_key_status_per_chat(self):
        import inspect
        from services import oversight
        src = inspect.getsource(oversight._limits_block)
        # S10.19-15: ровно один вызов key_status в блоке лимитов
        assert src.count("key_status(") == 1

    def test_frontend_has_unlimited_and_reactivity(self):
        from pathlib import Path
        js = Path("web/app.js").read_text(encoding="utf-8")
        assert "'Безлимит (∞)'" in js
        # T-1882: смена чата перечитывает «Сводку» (status + oversight) —
        # блок помечен комментарием 10.20 и содержит оба вызова.
        marker = js.index("10.20 (БЛОК 5.4, S10.19-15)")
        block = js[marker:marker + 600]
        assert "this.loadStatus()" in block
        assert "this.loadOversight()" in block
        html = Path("web/index.html").read_text(encoding="utf-8")
        assert "Безлимит (∞)" in html
