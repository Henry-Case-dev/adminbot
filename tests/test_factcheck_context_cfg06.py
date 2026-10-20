"""CFG-06 W1 — широкий чат-контекст фактчека (06I.1–06I.9).

TEST-LIFECYCLE: CONTRACT owner=CFG-06

Контракты:
  * гейт `flags.factcheck_wide_context`/`FACTCHECK_WIDE_CONTEXT_ENABLED`
    default OFF → `_fetch_chat_context` байт-в-байт прежнего поведения
    (откат W3);
  * широкое окно: тезис за пределами кап-40 находится; якоря
    message_id/author/timestamp в каждой строке (канон);
  * двухуровневый фид (компакт-хронология + дословные фрагменты), дедуп,
    потолок 500, бюджеты;
  * деградация: пустой срез → '' (прежнее поведение);
  * кеш среза: версия/диапазон/newest_id в ключе, новые сообщения → miss;
  * чужие чаты не читаются (scoping по chat_id).

Оффлайн: моки БД/кеша, сети нет, чаты не затрагиваются.
"""
import asyncio

import pytest

from config.settings import settings
from handlers import factcheck as hfc
from services import factcheck_context as fcx
from services import hot_config as hot
from services import smart_cache as sc
from services.chat_context import build_chat_context

CHAT_ID = -100777
OTHER_CHAT_ID = -100888
TARGET_TG = 9000
TRIGGER_TG = 9001


# ── Фикстуры ─────────────────────────────────────────────────────────────────

def _row(i, text, *, tg=None, reply_to=None, chat_id=CHAT_ID,
         author="Вася"):
    return {"id": 100 + i, "user_id": 1, "chat_id": chat_id, "text": text,
            "reply_to_id": reply_to, "timestamp": 1000 + i,
            "media_type": "text", "author_name": author, "is_forward": False,
            "forward_source": None, "tg_message_id": tg}


class FakeDB:
    """Скриптованный DB: только существующие доступы, лог запросов."""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    async def get_messages_around(self, chat_id, target_tg_message_id,
                                  before, after):
        self.queries.append(("around", chat_id, target_tg_message_id,
                             before, after))
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        self.queries.append(("recent", chat_id, limit))
        return list(self._rows[-limit:]) if limit else []


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.store.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store[key] = payload


def _dispute_rows(count=320, target_index=None):
    """Спор: болтовня + тезис ровно 50 сообщений РАНЬШЕ цели (реальное окно
    before=255 его покрывает; кап-40 — нет)."""
    rows = []
    target_index = count - 2 if target_index is None else target_index
    thesis_index = target_index - 50
    for i in range(count):
        if i == thesis_index:
            text = ("килякетские дожди были кислотными и погубили урожай "
                    "на всей низменности")
            rows.append(_row(i, text, tg=100 + i))
        elif i == target_index:
            rows.append(_row(i, "целевое сообщение спора", tg=TARGET_TG))
        elif i == target_index + 1:
            rows.append(_row(i, "фактчек это", tg=TRIGGER_TG))
        else:
            rows.append(_row(i, f"реплика болтовни номер {i}", tg=100 + i))
    return rows


@pytest.fixture
def wide_on():
    old = getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", old)


@pytest.fixture
def restore_handler_db():
    old_db, old_service = hfc._db, hfc._service
    yield
    hfc._db, hfc._service = old_db, old_service


# ── Гейт отката: OFF → байт-паритет ──────────────────────────────────────────

class TestWideGateOffParity:
    @pytest.mark.asyncio
    async def test_flag_default_off_and_hot_prio(self, monkeypatch):
        # default OFF (env-поле не задано в тестовом Settings);
        # Settings — frozen dataclass → патч инстанса через object.__setattr__
        old = getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False)
        object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False)
        try:
            assert fcx.wide_context_enabled() is False
            # hot-ключ перекрывает env без рестарта (паттерн CFG-01)
            monkeypatch.setattr(
                hot, "get",
                lambda key, default=None: True
                if key == "flags.factcheck_wide_context" else default)
            assert fcx.wide_context_enabled() is True
        finally:
            object.__setattr__(settings,
                               "FACTCHECK_WIDE_CONTEXT_ENABLED", old)

    @pytest.mark.asyncio
    async def test_flag_off_byte_parity_with_old_path(self,
                                                      restore_handler_db):
        rows = _dispute_rows()
        db = FakeDB(rows)
        hfc._db = db
        before, after = 6, 6
        actual = await hfc._fetch_chat_context(
            CHAT_ID, before, after, target_tg_message_id=TARGET_TG,
            trigger_message_id=TRIGGER_TG, claim_text="целевое сообщение")
        # прежний путь, развёрнутый вручную (код до W1)
        b, a = hfc._clamp_window(before, after)
        old_rows = await db.get_messages_around(CHAT_ID, TARGET_TG, b, a)
        chains = await hfc._build_reply_chains(CHAT_ID, TARGET_TG)
        expected = await build_chat_context(
            db, old_rows, chat_id=CHAT_ID, trigger_message_id=TRIGGER_TG,
            reply_chains=chains, anchor_message_id=TARGET_TG)
        assert actual == expected
        assert "фон: сжатая хронология" not in actual

    @pytest.mark.asyncio
    async def test_flag_on_uses_wide_feed(self, wide_on, restore_handler_db,
                                          monkeypatch):
        db = FakeDB(_dispute_rows())
        hfc._db = db
        monkeypatch.setattr(sc, "get_smart_cache", lambda: FakeCache())
        feed = await hfc._fetch_chat_context(
            CHAT_ID, 6, 6, target_tg_message_id=TARGET_TG,
            trigger_message_id=TRIGGER_TG, claim_text="килякетские дожди")
        assert feed.startswith("<chat_context ")
        assert "фон: сжатая хронология" in feed
        # широкий срез запрошен по chat_id, БЕЗ узкого капа 6+6
        around = [q for q in db.queries if q[0] == "around"]
        assert around and (around[0][3] > 40 or around[0][4] > 0)


# ── Широкий сбор: окно/якоря/тезис ───────────────────────────────────────────

class TestWideCollection:
    @pytest.mark.asyncio
    async def test_window_defaults_and_cap(self):
        before, after = await fcx.resolve_window(CHAT_ID)
        assert before + after == 300
        assert after < before                       # спор до цели
        assert before + after <= fcx._WIDE_WINDOW_MAX

    @pytest.mark.asyncio
    async def test_older_claim_found_and_anchors_kept(self):
        db = FakeDB(_dispute_rows())
        ctx = await fcx.build_wide_context(
            db, CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG,
            claim_text="правда ли, что килякетские дожди кислотные",
            cache=FakeCache())
        assert ctx is not None
        assert len(ctx.messages) == 320             # кап-40 не режет окно
        # стабильные опоры (06I.5)
        m = ctx.messages[0]
        assert m.message_id is not None and m.tg_message_id is not None
        assert m.author is not None and m.timestamp is not None
        # тезис 50 сообщений раньше найден (06I.2)
        feed = ctx.render_feed()
        assert "килякетские дожди" in feed
        assert f"tg:{TARGET_TG}" in feed            # якорь целевого

    @pytest.mark.asyncio
    async def test_dedup_and_total_cap(self):
        rows = _dispute_rows(count=60)
        rows.append(dict(rows[10]))                 # дубль tg-ключа
        rows.append(_row(70, "чужой чат", tg=777,
                         chat_id=OTHER_CHAT_ID))    # чужой чат
        db = FakeDB(rows)
        ctx = await fcx.build_wide_context(
            db, CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, claim_text=None,
            cache=FakeCache())
        keys = [m.dedup_key for m in ctx.messages]
        assert len(keys) == len(set(keys))          # дедуп
        assert all(m.chat_id == CHAT_ID for m in ctx.messages)
        # защитный потолок 500 (06I.9)
        big = FakeDB(_dispute_rows(count=600))
        ctx_big = await fcx.build_wide_context(
            big, CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, claim_text=None,
            cache=FakeCache())
        assert len(ctx_big.messages) <= fcx._WIDE_WINDOW_MAX
        assert any(_fcx_is_anchor(m, ctx_big) for m in ctx_big.messages)

    @pytest.mark.asyncio
    async def test_foreign_chat_never_queried_beyond_scope(self):
        db = FakeDB(_dispute_rows(count=10))
        await fcx.build_wide_context(
            db, CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, claim_text=None,
            cache=FakeCache())
        for q in db.queries:
            assert q[1] == CHAT_ID                  # только свой чат


def _fcx_is_anchor(m, ctx):
    return fcx._is_anchor(m, ctx)


# ── Двухуровневая подача (06I.3) ─────────────────────────────────────────────

class TestTwoLevelFeed:
    @pytest.mark.asyncio
    async def test_digest_truncated_verbatim_full(self):
        long_text = "килякетские дожди кислотные " * 40   # ~1120 символов
        rows = [
            _row(0, long_text, tg=100),
            _row(1, "болтовня", tg=101),
            _row(2, "целевое сообщение спора", tg=TARGET_TG),
        ]
        db = FakeDB(rows)
        ctx = await fcx.build_wide_context(
            db, CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG,
            claim_text="килякетские дожди кислотные", cache=FakeCache())
        feed = ctx.render_feed()
        assert "фон: сжатая хронология" in feed
        assert "фон: дословные фрагменты" in feed
        # компакт-строка обрезана, дословный сегмент почти полон (кап 600)
        digest_part = feed.split("фон: сжатая хронология")[1].split(
            "фон: дословные")[0]
        verbatim_part = feed.split("фон: дословные фрагменты")[1]
        assert "…" in digest_part
        assert long_text.strip()[:590] in verbatim_part
        assert "…" in verbatim_part          # 1120 > 600 → честная обрезка
        # обычная болтовня — только в хронологии, не в дословных
        assert "болтовня" not in verbatim_part

    @pytest.mark.asyncio
    async def test_reply_to_anchor_is_verbatim(self):
        rows = [
            _row(0, "болтовня", tg=100),
            _row(1, "целевое сообщение спора", tg=TARGET_TG),
            _row(2, "ответ на цель", tg=102, reply_to=TARGET_TG),
        ]
        db = FakeDB(rows)
        ctx = await fcx.build_wide_context(
            db, CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, claim_text=None,
            cache=FakeCache())
        by_tg = {m.tg_message_id: m for m in ctx.messages}
        assert by_tg[TARGET_TG].verbatim is True
        assert by_tg[102].verbatim is True          # явная связь 06I.4
        assert by_tg[100].verbatim is False


# ── Деградация (06I.8) и кеш среза (06I.9) ──────────────────────────────────

class TestDegradationAndCache:
    @pytest.mark.asyncio
    async def test_empty_context_degrades_to_empty_string(self, wide_on,
                                                          restore_handler_db,
                                                          monkeypatch):
        db = FakeDB([])
        hfc._db = db
        monkeypatch.setattr(sc, "get_smart_cache", lambda: FakeCache())
        out = await hfc._fetch_chat_context(
            CHAT_ID, 6, 6, target_tg_message_id=TARGET_TG,
            trigger_message_id=TRIGGER_TG, claim_text="что угодно")
        assert out == ""                            # прежнее поведение

    @pytest.mark.asyncio
    async def test_slice_cache_hit_and_invalidation(self):
        cache = FakeCache()
        db = FakeDB(_dispute_rows(count=20))
        kwargs = dict(target_tg_message_id=TARGET_TG,
                      trigger_tg_message_id=TRIGGER_TG,
                      claim_text="килякетские дожди", cache=cache)
        first = await fcx.build_wide_context(db, CHAT_ID, **kwargs)
        assert first is not None
        assert len(cache.store) == 1
        second = await fcx.build_wide_context(db, CHAT_ID, **kwargs)
        assert second is not None
        # hit: второй сбор НЕ ходил в get_messages_around повторно
        around_calls = [q for q in db.queries if q[0] == "around"]
        assert len(around_calls) == 1
        # новые сообщения → другой newest → miss (06I.9)
        db2 = FakeDB(_dispute_rows(count=21))
        third = await fcx.build_wide_context(db2, CHAT_ID, **kwargs)
        assert third is not None
        assert any(q[0] == "around" for q in db2.queries)
        # чужая версия схемы → miss
        import json as _json
        key = next(iter(cache.store))
        payload = _json.loads(cache.store[key])
        payload["version"] = "fcx0"
        cache.store[key] = _json.dumps(payload, ensure_ascii=False)
        db3 = FakeDB(_dispute_rows(count=20))
        fourth = await fcx.build_wide_context(db3, CHAT_ID, **kwargs)
        assert fourth is not None
        assert any(q[0] == "around" for q in db3.queries)
