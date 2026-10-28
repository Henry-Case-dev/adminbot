"""P0-HA TRUNC-PAGES (волна 2, снапшот 2026-10-29 §4 + архконтракт §1) —
get_recent_history без символьной обрезки: структурные страницы целых
сообщений с честной головой @@HISTORY_SAMPLE (sample_id, границы,
requested/available/processed/remaining, has_next, подписанный cursor).

Покрытие: H9 (>3500 симв. не режется), H10 (>100k симв. — страницы),
H12 (свежайшие — в конце последней страницы), H13 (нет неявной text[:N]),
H14-adjacent (битый/чужой/протухший cursor → структурированная ошибка,
никакого тихого фолбэка на depth=50), H16 (событие на стыке страниц не
теряет части), H8 (новые сообщения не сдвигают зафиксированную выборку),
счётчики, границы страниц по целым сообщениям. SQLite in-memory, без сети.
"""
import asyncio
import base64
import hashlib
import hmac
import inspect
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.database import DatabaseService
from services.tool_router import (
    _HISTORY_CURSOR_KEY,
    _HISTORY_PAGE_ROWS,
    _HISTORY_SAMPLE_END,
    _HISTORY_SAMPLE_HEADER,
    ToolContext,
    ToolDeps,
    ToolRouter,
    _history_cursor_decode,
    _history_cursor_encode,
    _history_depth,
    _history_sample_id,
    capture_history_sample,
    extract_history_depth,
    parse_history_sample,
)
from services.canonical_context import format_context_item, resolve_item_id

CHAT_ID = -1001234567890
OTHER_CHAT = -1009999999999
_EMPTY_PHRASE = "За последние сообщения ничего не нашлось"


def _deps(db=None, memory=None) -> ToolDeps:
    return ToolDeps(search=MagicMock(), memory=memory or MagicMock(),
                    aliases=None, db=db)


def _ctx(query="", chat_id=CHAT_ID) -> ToolContext:
    return ToolContext(chat_id, query)


async def _make_db(count=0, *, text_len=0, chat_id=CHAT_ID,
                   texts=None) -> DatabaseService:
    """Реальная DatabaseService на SQLite in-memory; ids 1..count (ts = id)."""
    db = DatabaseService(":memory:")
    await db.initialize()
    for i in range(1, count + 1):
        text = (texts[i - 1] if texts else f"м{i}")
        if text_len:
            text = f"{text} " + "x" * text_len
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name) "
            "VALUES (1, ?, ?, ?, 'text', 'автор')",
            (chat_id, text, i))
    await db.db.commit()
    return db


def _header(out: str) -> dict:
    fields = parse_history_sample(out)
    assert fields is not None, f"нет головы @@HISTORY_SAMPLE: {out[:120]!r}"
    return fields


def _body_lines(out: str) -> list[str]:
    """Строки сообщений страницы: между @@END_HEADER и хвостовым сентинелом."""
    start = out.find("@@END_HEADER")
    assert start >= 0
    start += len("@@END_HEADER")
    end = out.rfind(_HISTORY_SAMPLE_END)
    assert end >= start
    chunk = out[start:end].strip("\n")
    return chunk.splitlines() if chunk else []


def _expected_line(row) -> str:
    item = dict(row)
    text = str(item.get("text") or "").strip()
    # P0-HA волна 4 (блокер 2 review-w4): строки выборки несут Telegram
    # user_id тем же приёмом, что `_speaker_tag` («Имя [uid]»).
    uid = item.get("user_id")
    author = str(item.get("author_name") or "")
    if uid not in (None, "", 0):
        author = f"{author} [{uid}]"
    return format_context_item(
        ts=item.get("timestamp"), author=author,
        item_id=resolve_item_id(tg_message_id=item.get("tg_message_id"),
                                message_id=item.get("id")),
        forward_source=None, text=text, kind="msg")


async def _all_expected_lines(db, chat_id=CHAT_ID) -> list[str]:
    rows = await db.get_recent_messages(chat_id, 10 ** 9)
    return [_expected_line(r) for r in rows]


async def _walk_pages(router, ctx, out: str, limit=50) -> list[dict]:
    """Обход цепочки cursor'ов → список (header, body_lines) по страницам."""
    pages = []
    for _ in range(limit):
        header = _header(out)
        pages.append((header, _body_lines(out)))
        cursor = header.get("cursor") or ""
        if header.get("has_next") != 1:
            break
        assert cursor, "has_next=1 без cursor"
        out = await router.dispatch("get_recent_history",
                                    {"cursor": cursor}, ctx)
    return pages


# ── 1. Разбиение страниц: только целые сообщения ─────────────────────────


class TestPageSplitting:
    @pytest.mark.asyncio
    async def test_pages_contain_whole_messages(self):
        """REQ-HA-PAGE-WHOLE-MESSAGES: страница = целые сообщения, границы
        страниц совпадают с границами сообщений (никаких половин строк)."""
        db = await _make_db(count=95)
        try:
            router = ToolRouter(_deps(db=db))
            out = await router.dispatch("get_recent_history",
                                        {"depth": 95}, _ctx())
            header = _header(out)
            body = _body_lines(out)
            assert header["has_next"] == 1
            assert len(body) == _HISTORY_PAGE_ROWS
            expected_all = await _all_expected_lines(db)
            assert body == expected_all[:_HISTORY_PAGE_ROWS]
            # Ни одна строка не оборвана: каждая строка страницы — точная
            # каноническая строка целого сообщения.
            assert all(line in expected_all for line in body)
            assert out.endswith(_HISTORY_SAMPLE_END)
            assert not out.rstrip().endswith("…")
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_continuation_no_overlap_no_loss(self):
        """H16-adjacent: событие на стыке страниц (тема А в хвосте стр.1,
        тема Б пересекает границу) — обе части на месте; страница 2
        продолжается ровно после страницы 1: ноль перекрытий, ноль потерь."""
        texts = [f"тема-{i} сообщение {i}" for i in range(1, 96)]
        texts[37] = "тема-А часть1 (стык до границы)"
        texts[38] = "тема-А часть2 (стык до границы)"
        texts[39] = "тема-Б часть1 (стык после границы)"
        texts[40] = "тема-Б часть2 (стык после границы)"
        db = await _make_db(count=95, texts=texts)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 95}, ctx)
            pages = await _walk_pages(router, ctx, out)
            seen: list[str] = []
            for header, body in pages:
                assert body, "пустая страница в середине цепочки"
                for line in body:
                    assert line not in seen, "перекрытие страниц"
                    seen.append(line)
            expected_all = await _all_expected_lines(db)
            assert seen == expected_all            # ноль потерь, порядок ASC
            # Стык: обе части темы А и обе части темы Б дошли.
            joined = "\n".join(seen)
            for marker in ("тема-А часть1", "тема-А часть2",
                           "тема-Б часть1", "тема-Б часть2"):
                assert marker in joined
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_newest_at_end_of_last_page(self):
        """H12: при ASC-чтении свежайшие сообщения — в конце последней
        страницы, не теряются."""
        db = await _make_db(count=120)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 120}, ctx)
            pages = await _walk_pages(router, ctx, out)
            assert len(pages) == 3                 # 40+40+40... 120 = 3x40
            last_header, last_body = pages[-1]
            assert last_header["has_next"] == 0
            assert last_header["remaining"] == 0
            assert "м120" in last_body[-1]
            assert "м120" not in "\n".join(
                line for _, body in pages[:-1] for line in body)
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_sample_fixed_while_new_messages_arrive(self):
        """H8: новые сообщения после захвата не входят в выборку и не
        сдвигают её (ctx.history_sample от capture_history_sample)."""
        db = await _make_db(count=60)
        try:
            bound = await capture_history_sample(db, CHAT_ID, 60)
            assert bound is not None and bound["available"] == 60
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            ctx.history_sample = dict(bound)
            await db.db.execute(
                "INSERT INTO smart_messages "
                "(user_id, chat_id, text, timestamp, media_type, author_name) "
                "VALUES (1, ?, 'СВЕЖЕЕ ПОСЛЕ ЗАХВАТА', 99999, 'text', 'новый')",
                (CHAT_ID,))
            await db.db.commit()
            out = await router.dispatch("get_recent_history", {}, ctx)
            header = _header(out)
            assert header["available"] == 60
            assert header["boundary_to"] == "60:60"
            full = _body_lines(out)
            assert all("СВЕЖЕЕ" not in line for line in full)
            # Страница 1 зафиксированной выборки не сместилась (id 1..40).
            expected = await _all_expected_lines(db, CHAT_ID)
            assert full == expected[:len(full)]
            # Свежий вызов БЕЗ зафиксированной выборки видит новое сообщение
            # (в хвосте последней страницы — ASC).
            out2 = await router.dispatch("get_recent_history",
                                         {"depth": 61}, _ctx())
            pages2 = await _walk_pages(router, _ctx(), out2)
            assert pages2[-1][0]["has_next"] == 0
            assert any("СВЕЖЕЕ ПОСЛЕ ЗАХВАТА" in line
                       for line in pages2[-1][1])
        finally:
            await db.db.close()


# ── 2. Счётчики: requested/available/processed/remaining/has_next ────────


class TestCounters:
    @pytest.mark.asyncio
    async def test_counters_exact_chain(self):
        db = await _make_db(count=85)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 85}, ctx)
            pages = await _walk_pages(router, ctx, out)
            assert len(pages) == 3                 # 40 + 40 + 5
            h1, h2, h3 = (p[0] for p in pages)
            assert (h1["requested"], h1["available"],
                    h1["processed"], h1["remaining"],
                    h1["has_next"]) == (85, 85, 40, 45, 1)
            assert (h2["processed"], h2["remaining"], h2["has_next"]) == \
                (80, 5, 1)
            assert (h3["processed"], h3["remaining"], h3["has_next"],
                    h3["incomplete"]) == (85, 0, 0, 0)
            assert not (h3.get("cursor") or "")
            # sample_id стабилен вдоль цепочки; границы выборки неизменны.
            assert h1["sample_id"] == h2["sample_id"] == h3["sample_id"]
            assert h1["sample_id"].startswith("hs_")
            assert h1["boundary_to"] == "85:85"
            assert h1["boundary_from"] == "1:1"
            # page 2 продолжается ровно после page 1 (keyset, без перекрытий).
            assert int(h2["page_from"].split(":")[1]) == \
                int(h1["page_to"].split(":")[1]) + 1
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_available_short_of_requested(self):
        """H7: истории меньше, чем запрошено → фактическое available честно."""
        db = await _make_db(count=30)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 2000}, ctx)
            header = _header(out)
            assert header["requested"] == 2000
            assert header["available"] == 30
            assert header["processed"] == 30       # 30 ≤ 40 → вся в стр. 1
            assert header["remaining"] == 0
            assert header["has_next"] == 0
            assert header["incomplete"] == 0       # полнота = вся доступная
            body = _body_lines(out)
            assert len(body) == 30
            assert header["boundary_from"] == "1:1"
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_default_depth_50_is_not_cap(self):
        """Дефолт 50 без параметров: страница 40 + честное продолжение;
        дефолт не потолок (стр.1 не выдаётся за полную выборку)."""
        db = await _make_db(count=60)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx("")
            out = await router.dispatch("get_recent_history", {}, ctx)
            header = _header(out)
            assert header["requested"] == 50
            assert header["available"] == 50       # не 60: выборка = последние 50
            assert (header["processed"], header["remaining"],
                    header["has_next"]) == (40, 10, 1)
            cursor = header["cursor"]
            out2 = await router.dispatch("get_recent_history",
                                         {"cursor": cursor}, ctx)
            h2 = _header(out2)
            assert (h2["processed"], h2["remaining"],
                    h2["has_next"]) == (50, 0, 0)
            assert "м60" in "\n".join(_body_lines(out2))
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_vanished_tail_reports_incompleteness(self):
        """H14: хвост выборки удалён из БД между страницами. Cursor хранит
        захваченные available/processed → обещанный остаток известен; живых
        строк меньше обещанных → incomplete=1 + reason=tail_missing, а
        выжившие строки всё равно доходят (потеря названа, не скрыта).
        Отдельно: устаревший captured available (ctx.history_sample), окно
        опустело целиком → явная неполнота incomplete=1 + reason, а не тихий
        «успех» (REQ-HA-INCOMPLETENESS-REPORTING)."""
        db = await _make_db(count=85)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 85}, ctx)
            header = _header(out)
            assert header["has_next"] == 1
            # Хвост удалён (retention), якорь (id 85) жив.
            await db.db.execute(
                "DELETE FROM smart_messages WHERE id > 40 AND id < 85")
            await db.db.commit()
            out2 = await router.dispatch(
                "get_recent_history", {"cursor": header["cursor"]}, ctx)
            h2 = _header(out2)
            assert h2["has_next"] == 0
            assert h2["incomplete"] == 1               # потеря объявлена
            assert h2["reason"] == "tail_missing"
            assert h2["available"] == 85               # захваченный, не живой
            assert h2["processed"] == 41               # 40 + выживший m85
            assert h2["remaining"] == 44               # 44 удаления названы
            body = _body_lines(out2)
            assert len(body) == 1 and "м85" in body[0]  # выживший хвост дошёл

            # Устаревший captured available: окно опустело полностью →
            # неполнота объявлена явно.
            bound = {"sample_id": _history_sample_id(CHAT_ID, 999, 7, 10),
                     "chat_id": CHAT_ID, "anchor_ts": 999, "anchor_id": 7,
                     "oldest_ts": 990, "oldest_id": 1, "requested": 10,
                     "available": 10}
            ctx2 = _ctx()
            ctx2.history_sample = dict(bound)
            out3 = await router.dispatch("get_recent_history", {}, ctx2)
            h3 = _header(out3)
            assert h3["has_next"] == 0
            assert h3["incomplete"] == 1
            assert h3["reason"] == "anchor_missing"
            assert _body_lines(out3) == []
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_deletion_inside_sample_gap_accounted(self):
        """H14 (зонд ревью, сценарий b): удаление ВНУТРИ недочитанного
        участка выборки. Финальная страница сводит счёт без дыр: ни одно
        сообщение выборки не исчезает молча — каждое либо доставлено
        (processed), либо названо потерянным (remaining + tail_missing)."""
        db = await _make_db(count=100)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 100}, ctx)
            pages = [( _header(out), _body_lines(out))]
            header = pages[0][0]
            assert header["has_next"] == 1
            await db.db.execute(
                "DELETE FROM smart_messages WHERE id >= 50 AND id <= 90")
            await db.db.commit()
            out2 = await router.dispatch(
                "get_recent_history", {"cursor": header["cursor"]}, ctx)
            h2 = _header(out2)
            pages.append((h2, _body_lines(out2)))
            # Финал обхода: счёт самосогласован, дыра названа.
            assert h2["has_next"] == 0
            assert h2["incomplete"] == 1 and h2["reason"] == "tail_missing"
            assert h2["available"] == 100              # захваченный
            assert h2["processed"] == 59               # 100 - 41 удалённых
            assert h2["remaining"] == 41               # 41 удалений названо
            assert h2["processed"] + h2["remaining"] == h2["available"]
            # Все выжившие дошли (ASC, без перекрытий и молчаливых дыр).
            seen = [line for _, body in pages for line in body]
            expected_survivors = await _all_expected_lines(db)
            assert seen == expected_survivors
            assert len(seen) == 59
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_loss_detected_midwalk_survivors_still_delivered(self):
        """H14: потеря обнаружена в середине обхода (выживших больше
        страницы) — страница честно помечена incomplete=1/tail_missing,
        has_next=1 продолжает дочитывать выживших, финал сходится без
        молчаливых дыр и без отката на depth=50."""
        db = await _make_db(count=200)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 200}, ctx)
            h1 = _header(out)
            assert (h1["processed"], h1["remaining"], h1["has_next"]) == \
                (40, 160, 1)
            await db.db.execute(
                "DELETE FROM smart_messages WHERE id >= 50 AND id <= 150")
            await db.db.commit()
            cursor = h1["cursor"]
            out2 = await router.dispatch(
                "get_recent_history", {"cursor": cursor}, ctx)
            h2 = _header(out2)
            # Выживших после точки курсора 59 > страницы 40 → неполнота
            # названа сразу, дочитывание продолжается.
            assert h2["incomplete"] == 1 and h2["reason"] == "tail_missing"
            assert h2["has_next"] == 1
            assert h2["processed"] == 80 and h2["remaining"] == 120
            out3 = await router.dispatch(
                "get_recent_history", {"cursor": h2["cursor"]}, ctx)
            h3 = _header(out3)
            assert h3["has_next"] == 0
            assert h3["incomplete"] == 1 and h3["reason"] == "tail_missing"
            assert h3["processed"] == 99               # 200 - 101 удалённых
            assert h3["remaining"] == 101
            assert h3["processed"] + h3["remaining"] == h3["available"] == 200
            seen = [line for _, body in
                    ((h1, _body_lines(out)), (h2, _body_lines(out2)),
                     (h3, _body_lines(out3))) for line in body]
            expected_survivors = await _all_expected_lines(db)
            assert seen == expected_survivors
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_empty_chat_parity_no_header(self):
        db = await _make_db()
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"depth": 50}, _ctx())
            assert out == _EMPTY_PHRASE
            assert parse_history_sample(out) is None
        finally:
            await db.db.close()


# ── 3. Без символьной обрезки: >3500 в одной странице, >100k по страницам ─


class TestNoSymbolTruncation:
    @pytest.mark.asyncio
    async def test_over_3500_chars_single_page_intact(self):
        """H9: >3500 символов — не режется по старому правилу; полная выборка
        помещается в одну страницу → возвращается целиком (§4.2)."""
        db = await _make_db(count=25, text_len=180)
        try:
            router = ToolRouter(_deps(db=db))
            out = await router.dispatch("get_recent_history",
                                        {"depth": 25}, _ctx())
            header = _header(out)
            assert header["has_next"] == 0
            body = _body_lines(out)
            assert len(body) == 25
            total = sum(len(line) for line in body)
            assert total > 3500
            expected_all = await _all_expected_lines(db)
            assert body == expected_all
            assert not out.rstrip().endswith("…")
            assert out.endswith(_HISTORY_SAMPLE_END)
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_over_100k_chars_via_pages(self):
        """H10: >100 000 символов — обработка продолжается через страницы."""
        db = await _make_db(count=300, text_len=400)
        try:
            router = ToolRouter(_deps(db=db))
            ctx = _ctx()
            out = await router.dispatch("get_recent_history",
                                        {"depth": 300}, ctx)
            pages = await _walk_pages(router, ctx, out)
            assert len(pages) == 8                 # 300 = 7x40 + 20
            total = sum(len(line) for _, body in pages for line in body)
            assert total > 100_000
            seen = [line for _, body in pages for line in body]
            expected_all = await _all_expected_lines(db)
            assert seen == expected_all
            assert pages[-1][0]["has_next"] == 0
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_single_huge_message_not_cut(self):
        """Одно сообщение любого размера занимает страницу целиком —
        text[:N] на пути истории нет, счётчик не теряет сообщение."""
        huge = "я" * 50_000
        texts = [f"обычное {i}" for i in range(1, 10)] + [huge] \
            + [f"после {i}" for i in range(11, 16)]
        db = await _make_db(count=15, texts=texts)
        try:
            router = ToolRouter(_deps(db=db))
            out = await router.dispatch("get_recent_history",
                                        {"depth": 15}, _ctx())
            assert huge in out
            header = _header(out)
            assert header["processed"] == 15 and header["remaining"] == 0
        finally:
            await db.db.close()

    def test_no_symbol_cap_on_history_path(self):
        """H13/H31 (структурная проверка): _HISTORY_MAX_SYMBOLS удалён; в
        функциях пути истории нет text[:N]/_truncate — символьный лимит как
        способ определения доступной истории исчез (3500 не стала 5000/100000)."""
        import services.tool_router as tr
        assert not hasattr(tr, "_HISTORY_MAX_SYMBOLS")
        src = inspect.getsource(tr)
        assert "_HISTORY_MAX_SYMBOLS" not in src
        for fn_name in ("_get_recent_history", "_format_history_page",
                        "_history_read_page", "_history_continue"):
            fn_src = inspect.getsource(getattr(tr.ToolRouter, fn_name))
            assert "_truncate(" not in fn_src
            assert "text[:" not in fn_src and "out[:" not in fn_src
        # Технический предел одной операции — в целых сообщениях, не символах.
        assert isinstance(_HISTORY_PAGE_ROWS, int) and _HISTORY_PAGE_ROWS >= 1


# ── 4. Cursor: fail closed ────────────────────────────────────────────────


class TestCursorFailClosed:
    async def _page1_cursor(self, db, depth=80):
        router = ToolRouter(_deps(db=db))
        out = await router.dispatch("get_recent_history",
                                    {"depth": depth}, _ctx())
        return router, _header(out)["cursor"]

    @pytest.mark.asyncio
    async def test_tampered_cursor_structured_error(self):
        """H14-adjacent: битая подпись → ОШИБКА unknown_cursor; НИКАКОЙ тихой
        подмены на новую выборку depth=50 или путь B."""
        db = await _make_db(count=80)
        try:
            router, cursor = await self._page1_cursor(db)
            bad = cursor[:-3] + ("aaa" if not cursor.endswith("aaa") else "bbb")
            out = await router.dispatch("get_recent_history",
                                        {"cursor": bad}, _ctx())
            assert out == "ОШИБКА get_recent_history: unknown_cursor"
            assert parse_history_sample(out) is None
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_foreign_chat_cursor_rejected(self):
        """Cursor чужого chat_id → unknown_cursor (параллельные ходы не делят
        состояние)."""
        db = await _make_db(count=80)
        db_other = await _make_db(count=5, chat_id=OTHER_CHAT)
        try:
            _, cursor = await self._page1_cursor(db)
            router = ToolRouter(_deps(db=db_other))
            out = await router.dispatch("get_recent_history",
                                        {"cursor": cursor},
                                        _ctx(chat_id=OTHER_CHAT))
            assert out == "ОШИБКА get_recent_history: unknown_cursor"
        finally:
            await db.db.close()
            await db_other.db.close()

    @pytest.mark.asyncio
    async def test_expired_cursor_structured_error(self):
        """Протухший cursor (exp в прошлом) → stale_cursor, не новая выборка."""
        db = await _make_db(count=80)
        try:
            bound = await capture_history_sample(db, CHAT_ID, 80)
            stale = dict(bound)
            stale["exp"] = int(time.time()) - 10
            cursor = _history_cursor_encode(stale, 5, 5)
            router = ToolRouter(_deps(db=db))
            out = await router.dispatch("get_recent_history",
                                        {"cursor": cursor}, _ctx())
            assert out == "ОШИБКА get_recent_history: stale_cursor"
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_deleted_anchor_structured_error(self):
        """Якорь удалён из БД → anchor_missing (fail closed)."""
        db = await _make_db(count=80)
        try:
            router, cursor = await self._page1_cursor(db)
            fields, reason = _history_cursor_decode(cursor, CHAT_ID)
            assert fields is not None and reason == ""
            await db.db.execute("DELETE FROM smart_messages WHERE id = ?",
                                (fields["anchor_id"],))
            await db.db.commit()
            out = await router.dispatch("get_recent_history",
                                        {"cursor": cursor}, _ctx())
            assert out == "ОШИБКА get_recent_history: anchor_missing"
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_cursor_beats_query_and_depth(self):
        """Непустой cursor → ТОЛЬКО продолжение: query/depth игнорируются."""
        db = await _make_db(count=80)
        try:
            router, cursor = await self._page1_cursor(db)
            out = await router.dispatch(
                "get_recent_history",
                {"cursor": cursor, "query": "м75", "depth": 3}, _ctx())
            header = _header(out)
            assert header["processed"] == 80 and header["has_next"] == 0
            assert "м75" in "\n".join(_body_lines(out))
        finally:
            await db.db.close()

    def test_cursor_codec_roundtrip_and_rejects(self):
        bound = {"sample_id": _history_sample_id(CHAT_ID, 100, 5, 50),
                 "chat_id": CHAT_ID, "anchor_ts": 100, "anchor_id": 5,
                 "oldest_ts": 1, "oldest_id": 1, "requested": 50,
                 "available": 50, "exp": int(time.time()) + 300}
        cursor = _history_cursor_encode(bound, 3, 4, processed=7)
        assert cursor.startswith("v2.")
        fields, reason = _history_cursor_decode(cursor, CHAT_ID)
        assert reason == "" and fields is not None
        assert fields["after_ts"] == 3 and fields["after_id"] == 4
        assert fields["sample_id"] == bound["sample_id"]
        assert fields["available"] == 50 and fields["processed"] == 7
        # чужой чат / битая подпись / мусор → unknown_cursor
        assert _history_cursor_decode(cursor, OTHER_CHAT)[1] == "unknown_cursor"
        assert _history_cursor_decode(cursor[:-2] + "xx", CHAT_ID)[1] == \
            "unknown_cursor"
        assert _history_cursor_decode("garbage", CHAT_ID)[1] == "unknown_cursor"
        stale = dict(bound, exp=int(time.time()) - 1)
        assert _history_cursor_decode(
            _history_cursor_encode(stale, 0, 0), CHAT_ID)[1] == "stale_cursor"
        # подпись привязана к payload: подмена after-точки ловится
        other_after = _history_cursor_encode(bound, 9, 9)
        assert other_after != cursor

    def _signed_cursor(self, payload: str) -> str:
        """Правильно подписанный (текущим ключом процесса) payload любой
        версии — для fail-closed проверок НЕизвестных форматов."""
        token = base64.urlsafe_b64encode(
            payload.encode("ascii")).decode("ascii").rstrip("=")
        sig = hmac.new(_HISTORY_CURSOR_KEY, payload.encode("ascii"),
                       hashlib.sha256).hexdigest()[:16]
        return f"v1.{token}.{sig}"

    @pytest.mark.asyncio
    async def test_old_format_cursor_fail_closed(self):
        """H14 (ревью): cursor прежней сборки (v1, 11 полей, без захваченных
        available/processed) — структурированный отказ unknown_cursor, НИКАКОГО
        молчаливого чтения по ужатому живому COUNT. TTL 360 с делает
        совместимость с pre-fix payload'ами бессмысленной."""
        v1_payload = "|".join(str(v) for v in (
            "v1", CHAT_ID, 100, 5, 1, 1, 50, 3, 4,
            int(time.time()) + 300, _history_sample_id(CHAT_ID, 100, 5, 50)))
        cursor = self._signed_cursor(v1_payload)
        assert _history_cursor_decode(cursor, CHAT_ID)[1] == "unknown_cursor"
        # И через dispatch: та же структурная ошибка, без тел и без выборки.
        db = await _make_db(count=80)
        try:
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"cursor": cursor}, _ctx())
        finally:
            await db.db.close()
        assert out == "ОШИБКА get_recent_history: unknown_cursor"
        assert parse_history_sample(out) is None

    def test_inconsistent_counter_cursor_fail_closed(self):
        """Правильно подписанный v2 с несогласованными счётчиками выборки
        (processed > available / available < 1) → unknown_cursor, не
        «лучшая догадка»."""
        base = {"chat_id": CHAT_ID, "anchor_ts": 100, "anchor_id": 5,
                "oldest_ts": 1, "oldest_id": 1, "requested": 50,
                "available": 50, "after_ts": 3, "after_id": 4,
                "exp": int(time.time()) + 300,
                "sample_id": _history_sample_id(CHAT_ID, 100, 5, 50)}
        for processed in (51, -1):
            payload = "|".join(str(v) for v in (
                "v2", base["chat_id"], base["anchor_ts"], base["anchor_id"],
                base["oldest_ts"], base["oldest_id"], base["requested"],
                base["available"], processed, base["after_ts"],
                base["after_id"], base["exp"], base["sample_id"]))
            assert _history_cursor_decode(
                self._signed_cursor(payload), CHAT_ID)[1] == "unknown_cursor"
        payload = "|".join(str(v) for v in (
            "v2", base["chat_id"], base["anchor_ts"], base["anchor_id"],
            base["oldest_ts"], base["oldest_id"], base["requested"],
            0, 0, base["after_ts"], base["after_id"], base["exp"],
            base["sample_id"]))
        assert _history_cursor_decode(
            self._signed_cursor(payload), CHAT_ID)[1] == "unknown_cursor"


# ── 5. Маршрутизация §1 ───────────────────────────────────────────────────


class TestRouting:
    @pytest.mark.asyncio
    async def test_explicit_depth_beats_query(self):
        """Архконтракт §1: приоритет «query всегда побеждает» заменён —
        явный depth сильнее query (квантификативная граница первична)."""
        db = await _make_db(count=10)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        try:
            out = await ToolRouter(_deps(db=db, memory=memory)).dispatch(
                "get_recent_history", {"depth": 5, "query": "тема"}, _ctx())
            header = _header(out)
            assert header["requested"] == 5 and header["available"] == 5
            memory.search_long_term.assert_not_awaited()
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_extracted_n_from_plain_query(self):
        """Simple-путь шлёт только query: «…за последние 400 сообщений» →
        путь A с N=400 (FTS не запускается), 400 не особое число."""
        db = await _make_db(count=25)
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        try:
            out = await ToolRouter(_deps(db=db, memory=memory)).dispatch(
                "get_recent_history", {},
                _ctx("оцени, что происходило за последние 400 сообщений"))
            header = _header(out)
            assert header["requested"] == 400
            assert header["available"] == 25       # H7: честный охват
            memory.search_long_term.assert_not_awaited()
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_query_without_number_stays_fts(self):
        """Без числа+единицы+недавности → путь B, как сейчас (паритет)."""
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        out = await ToolRouter(_deps(memory=memory)).dispatch(
            "get_recent_history", {}, _ctx("что обсуждали 10 минут назад"))
        memory.search_long_term.assert_awaited_once()
        assert parse_history_sample(out) is None

    def test_extract_history_depth_pure(self):
        assert extract_history_depth(
            "что происходило за последние 400 сообщений") == 400
        assert extract_history_depth(
            "проанализируй последние 2 000 сообщений") == 2000
        assert extract_history_depth("last 2,000 messages") == 2000
        assert extract_history_depth("последние 200 реплик") == 200
        assert extract_history_depth("последние 10 минут") is None
        assert extract_history_depth("обсудим 400 сюжетов") is None
        assert extract_history_depth("вернись к теме Внуково") is None
        assert extract_history_depth("") is None

    @pytest.mark.asyncio
    async def test_history_sample_beats_explicit_depth(self):
        """ctx.history_sample задан → страница этой выборки (волна SEGMENTS
        ставит её до сборки контекста); явный depth её не перекрывает."""
        db = await _make_db(count=30)
        try:
            bound = await capture_history_sample(db, CHAT_ID, 20)
            ctx = _ctx()
            ctx.history_sample = dict(bound)
            out = await ToolRouter(_deps(db=db)).dispatch(
                "get_recent_history", {"depth": 5}, ctx)
            header = _header(out)
            assert header["requested"] == 20
            assert header["available"] == 20
            assert header["boundary_to"] == "30:30"
        finally:
            await db.db.close()

    @pytest.mark.asyncio
    async def test_timeout_and_cancel_semantics_kept(self, monkeypatch):
        """Существующие таймаут/отмена сохранены (стр. путь — тот же
        wait_for 10с; CancelledError пробрасывается)."""
        db = MagicMock()

        async def slow(chat_id, limit, **kwargs):
            await asyncio.sleep(1.0)
            return []

        db.get_recent_messages = AsyncMock(side_effect=slow)
        monkeypatch.setattr(
            "services.tool_router._HISTORY_TOOL_TIMEOUT", 0.05)
        out = await ToolRouter(_deps(db=db)).dispatch(
            "get_recent_history", {"depth": 5000}, _ctx())
        assert out == "ОШИБКА get_recent_history: timeout"

        db2 = MagicMock()

        async def cancelling(chat_id, limit, **kwargs):
            raise asyncio.CancelledError

        db2.get_recent_messages = AsyncMock(side_effect=cancelling)
        with pytest.raises(asyncio.CancelledError):
            await ToolRouter(_deps(db=db2)).dispatch(
                "get_recent_history", {"depth": 5}, _ctx())

    def test_depth_passthrough_unchanged(self):
        """Волна 1 не сломана: _history_depth без потолка."""
        assert _history_depth(9999) == 9999
        assert _history_depth(2000) == 2000
        assert _history_depth(0) == 1
        assert _history_depth(None) == 50


# ── 6. Путь B: без символьной обрезки, семантика прежняя ─────────────────


class TestQueryPathNoTruncation:
    @pytest.mark.asyncio
    async def test_query_result_whole_no_ellipsis(self):
        """Путь B больше не проходит через _truncate: результат целиком
        (ограничен собственным FTS-лимитом _HISTORY_SEARCH_LIMIT)."""
        now = int(time.time())
        memory = MagicMock()
        long_text = "д" * 6000
        memory.search_long_term = AsyncMock(return_value=[
            {"user_id": 1, "author_name": "вася", "text": long_text,
             "timestamp": now - 60, "media_type": "text", "chat_id": CHAT_ID}])
        out = await ToolRouter(_deps(memory=memory)).dispatch(
            "get_recent_history", {"query": "ссылка"}, _ctx())
        assert long_text in out
        assert not out.rstrip().endswith("…")

    @pytest.mark.asyncio
    async def test_query_empty_honest_phrase(self):
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[])
        out = await ToolRouter(_deps(memory=memory)).dispatch(
            "get_recent_history", {"query": "несуществующее"}, _ctx())
        assert out == _EMPTY_PHRASE


# ── 7. Логи: счётчики и sample_id, без текстов (R17) ─────────────────────


class TestLogs:
    @pytest.mark.asyncio
    async def test_page_logs_have_counters_no_text(self, caplog):
        import logging
        secret = "СЕКРЕТНЫЙ-ТЕКСТ https://secret.example.com/x"
        db = await _make_db(count=5,
                            texts=[secret if i == 2 else f"м{i}"
                                   for i in range(1, 6)])
        try:
            with caplog.at_level(logging.INFO):
                out = await ToolRouter(_deps(db=db)).dispatch(
                    "get_recent_history", {"depth": 5}, _ctx())
        finally:
            await db.db.close()
        record = next(r for r in caplog.records
                      if "get_recent_history |" in r.message)
        assert "sample=hs_" in record.message
        assert "processed=5" in record.message
        assert "remaining=0" in record.message
        assert "has_next=0" in record.message
        assert "СЕКРЕТНЫЙ-ТЕКСТ" not in caplog.text
        assert "secret.example.com" not in caplog.text

    @pytest.mark.asyncio
    async def test_cursor_rejection_logged_without_data(self, caplog):
        import logging
        db = await _make_db(count=5)
        try:
            with caplog.at_level(logging.WARNING):
                out = await ToolRouter(_deps(db=db)).dispatch(
                    "get_recent_history", {"cursor": "v1.broken.sig"},
                    _ctx())
        finally:
            await db.db.close()
        assert out == "ОШИБКА get_recent_history: unknown_cursor"
        assert any("cursor rejected" in r.message and "reason=unknown_cursor"
                   in r.message for r in caplog.records)


# ── 8. Схема: опциональный cursor ─────────────────────────────────────────


class TestSchema:
    def test_cursor_param_optional_taught(self):
        from services.tool_schemas import TOOL_GET_RECENT_HISTORY
        fn = TOOL_GET_RECENT_HISTORY["function"]
        props = fn["parameters"]["properties"]
        cursor = props["cursor"]
        assert cursor["type"] == "string"
        params = fn["parameters"]
        assert params.get("required") is None or \
            "cursor" not in (params.get("required") or [])
        # L1 учится продолжать по has_next=1 (без тематических хардкодов).
        desc = (fn["description"] + " " + cursor["description"]).lower()
        assert "has_next" in desc
        assert "cursor" in desc
        assert "no cap" in props["depth"]["description"].lower()
