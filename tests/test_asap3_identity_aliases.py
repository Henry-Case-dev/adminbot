"""ASAP 3 Corrective §4–§6 — единый порядок имён и merge алиасов по user_id.

Durable: CONTRACT (A1–A3, A7–A11, A14), REGRESSION (A4–A6, A15),
INTEGRATION (A12/A13/A16 harness). Живые сообщения не отправляются.
TEST-LIFECYCLE: CONTRACT/REGRESSION/INTEGRATION owner=ASAP3-IDENTITY
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from services import chat_params, summary_aliases
from services.direct_chat_service import DirectChatService
from services.summary_aliases import (
    AliasResolver,
    LiveAliasView,
    bind_turn_aliases,
    build_alias_resolver,
)
from services.summary_generator import SummaryGenerator
from services.tool_router import ToolDeps, ToolRouter

CHAT_A = -1001
CHAT_B = -1002
UID = 1001
OTHER = 1002

GLOBAL = {"1001": "Макс", "1002": "Леха", "1003": "Костя"}


class FakeCache:
    """chat_params cache: per-chat root (v-1 layout)."""

    def __init__(self, items=None):
        self.items = dict(items or {})
        self.reads = 0

    async def get_chat_params(self, chat_id):
        self.reads += 1
        return dict(self.items.get(chat_id, {}))

    async def get_chat_params_checked(self, chat_id):
        return dict(self.items.get(chat_id, {})), True


class BrokenCache(FakeCache):
    async def get_chat_params_checked(self, chat_id):
        raise RuntimeError("chat layer unavailable")


def _root(overrides=None):
    return {"v": 1, "overrides": dict(overrides or {}), "gates": {},
            "keys": {}, "perm_overrides": {}, "meta": {}}


@pytest.fixture(autouse=True)
def alias_env(monkeypatch):
    summary_aliases.reset_turn_alias_resolver()
    chat_params.set_chat_params_cache(None)
    monkeypatch.setattr(
        "services.hot_config.get",
        lambda key, default=None: (dict(GLOBAL)
                                   if key == "limits.summary_aliases"
                                   else default))
    yield
    summary_aliases.reset_turn_alias_resolver()
    chat_params.set_chat_params_cache(None)


def _set_global(monkeypatch, value):
    monkeypatch.setattr(
        "services.hot_config.get",
        lambda key, default=None: (value
                                   if key == "limits.summary_aliases"
                                   else default))


def _set_chat(chat_id, aliases):
    cache = chat_params.get_chat_params_cache()
    if cache is None:
        cache = FakeCache()
        chat_params.set_chat_params_cache(cache)
    cache.items[chat_id] = _root({"limits.summary_aliases": dict(aliases)})


class FakeDB:
    def __init__(self, participants=None):
        self.participants = list(participants or [])

    async def get_active_participants(self, chat_id, since, cap):
        return list(self.participants)[:cap]


class FakeMemory:
    async def get_window_messages(self, chat_id):
        return []


def _user(uid=UID, first="Игорь", last=None, username="igor"):
    return SimpleNamespace(id=uid, first_name=first, last_name=last,
                           username=username)


def _row(uid=UID, author="Старое имя", text="сообщение", ts=100):
    return {"user_id": uid, "author_name": author, "text": text,
            "timestamp": ts, "media_type": "text", "reply_to_id": None,
            "tg_message_id": None}


def _service(aliases, db=None):
    return DirectChatService(
        FakeMemory(), db or FakeDB(), object(), aliases,
        bot_id=999, bot_username="bot")


# ── A1–A3, A7, A8: приоритет и наследование по uid ─────────────────────────

@pytest.mark.asyncio
async def test_a1_global_alias_beats_nickname_username_memory():
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.resolve(UID, "Игорь", "igor", memory_name="Старое") == "Макс"


@pytest.mark.asyncio
async def test_a2_chat_alias_wins_only_in_its_chat():
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    a = await build_alias_resolver(CHAT_A)
    b = await build_alias_resolver(CHAT_B)
    assert a.resolve(UID, "Игорь", "igor") == "Гипербореец"
    assert b.resolve(UID, "Игорь", "igor") == "Макс"


@pytest.mark.asyncio
async def test_a3_partial_chat_map_inherits_global_aliases():
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.resolve(UID, "Игорь", None) == "Гипербореец"
    assert resolver.resolve(OTHER, "Лёша", None) == "Леха"
    assert resolver.resolve(1003, "Костя", None) == "Костя"
    report = resolver.scope_report
    assert report["merged"] == 3
    assert report["chat"] == 1
    assert report["inherited"] == 2


@pytest.mark.asyncio
async def test_a7_delete_chat_override_returns_global():
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    assert (await build_alias_resolver(CHAT_A)).resolve(UID) == "Гипербореец"
    chat_params.get_chat_params_cache().items[CHAT_A] = _root({})
    assert (await build_alias_resolver(CHAT_A)).resolve(UID) == "Макс"


@pytest.mark.asyncio
async def test_a8_delete_global_alias_returns_next_source(monkeypatch):
    _set_global(monkeypatch, {})
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.resolve(UID, "Игорь", "igor") == "Игорь"
    assert resolver.resolve(UID, None, "@igor") == "igor"
    assert resolver.resolve(UID, None, None) == str(UID)


@pytest.mark.asyncio
async def test_empty_alias_value_does_not_rename_or_hide_global():
    _set_chat(CHAT_A, {"1001": "", "1002": "  "})
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.resolve(UID, "Игорь", None) == "Макс"
    assert resolver.resolve(OTHER, "Лёша", None) == "Леха"


# ── A4–A6: hot-change без рестарта и после рестарта ────────────────────────

@pytest.mark.asyncio
async def test_a4_global_change_applies_next_turn(monkeypatch):
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    await bind_turn_aliases(CHAT_A)
    assert view.resolve(UID) == "Макс"
    _set_global(monkeypatch, {"1001": "Новый Макс"})
    await bind_turn_aliases(CHAT_A)
    assert view.resolve(UID) == "Новый Макс"


@pytest.mark.asyncio
async def test_a5_chat_change_applies_next_turn_without_restart():
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    _set_chat(CHAT_A, {str(UID): "Первый"})
    await bind_turn_aliases(CHAT_A)
    assert view.resolve(UID) == "Первый"
    _set_chat(CHAT_A, {str(UID): "Второй"})   # имитация save + invalidation
    await bind_turn_aliases(CHAT_A)
    assert view.resolve(UID) == "Второй"


@pytest.mark.asyncio
async def test_a6_after_restart_saved_aliases_apply():
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    # «Рестарт»: новый LiveAliasView со стартовым глобальным снапшотом.
    summary_aliases.reset_turn_alias_resolver()
    startup = LiveAliasView(AliasResolver(dict(GLOBAL)))
    await bind_turn_aliases(CHAT_A)
    assert startup.resolve(UID, "Игорь", None) == "Гипербореец"
    assert startup.canon_name("Макс", UID) == "Гипербореец"


# ── A9–A11, A14: история/граф/цитаты не переопределяют и не ломаются ───────

@pytest.mark.asyncio
async def test_a9_one_uid_many_historical_names_is_one_person():
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    service = _service(view)
    await bind_turn_aliases(CHAT_A)
    roster, _ = service._participant_roster([
        _row(author="Старое имя"), _row(author="Ещё одно имя")])
    assert roster == [(UID, "Макс")]


@pytest.mark.asyncio
async def test_a10_old_author_name_does_not_override_alias():
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    gen = SummaryGenerator(None, None, None, None, aliases=view)
    await bind_turn_aliases(CHAT_A)
    quote = gen._format_l2_quote(_row(author="Имя из Telegram-клиента"))
    assert quote.startswith("Макс:")
    assert "Имя из Telegram-клиента" not in quote


@pytest.mark.asyncio
async def test_a11_old_graphrag_name_does_not_override_in_resolution_map():
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    service = _service(view)
    await bind_turn_aliases(CHAT_A)
    block = service._build_alias_map([_row(author="Старое имя из GraphRAG")])
    assert f"Макс — {UID}" in block
    assert "Старое имя из GraphRAG" not in block


@pytest.mark.asyncio
async def test_a14_quotes_and_history_text_untouched():
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    gen = SummaryGenerator(None, None, None, None, aliases=view)
    await bind_turn_aliases(CHAT_A)
    literal = 'он сказал: «Мистер Служба» — дословно'
    quote = gen._format_l2_quote(_row(author="Старое", text=literal))
    assert literal in quote                       # текст цитаты не изменён
    assert quote.startswith("Макс:")


# ── A12/A13/A16: изоляция и единый порядок всех маршрутов ──────────────────

@pytest.mark.asyncio
async def test_a12_parallel_chats_do_not_leak_overrides():
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    _set_chat(CHAT_B, {str(OTHER): "Лёха Б"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))

    async def _resolve(chat_id):
        await bind_turn_aliases(chat_id)
        await asyncio.sleep(0)          # даём второй задаче вклиниться
        return (view.resolve(UID, "Игорь", None),
                view.resolve(OTHER, "Лёша", None))

    a, b = await asyncio.gather(_resolve(CHAT_A), _resolve(CHAT_B))
    assert a == ("Гипербореец", "Леха")
    assert b == ("Макс", "Лёха Б")


@pytest.mark.asyncio
async def test_a13_direct_summary_tool_and_media_share_one_order():
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    await bind_turn_aliases(CHAT_A)

    direct = _service(view)
    assert f"Гипербореец — {UID}" in direct._build_alias_map([_row()])

    gen = SummaryGenerator(None, None, None, None, aliases=view)
    assert gen._format_l2_quote(_row()).startswith("Гипербореец:")

    router = ToolRouter(ToolDeps(search=None, memory=None, aliases=view))
    assert router._resolve_name(_row()) == "Гипербореец"

    from handlers import media_common
    old = media_common._aliases
    try:
        media_common.set_media_aliases(view)
        assert media_common._resolve_transcript_author(
            SimpleNamespace(forward_origin=None, from_user=_user())) \
            == "Гипербореец"
    finally:
        media_common.set_media_aliases(old)


@pytest.mark.asyncio
async def test_double_encoded_global_json_still_merges(monkeypatch):
    """Диагностика F10 показывала double-encoded bot_settings — merge обязан
    читать и такой исторический формат."""
    _set_global(monkeypatch, json.dumps(json.dumps(GLOBAL)))
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.resolve(UID) == "Гипербореец"
    assert resolver.resolve(OTHER) == "Леха"


class _DiagConn:
    def __init__(self, overrides):
        self._overrides = overrides

    async def fetchrow(self, sql, *args):
        if "bot_settings" in sql:
            return {"key": "limits.summary_aliases",
                    "value": json.dumps(GLOBAL)}
        if "chat_profiles" in sql:
            return {"chat_id": args[0], "chat_params": _root(
                {"limits.summary_aliases": dict(self._overrides)})}
        return None


class _DiagPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


def test_diag_aliases_merged_view_only_with_show_names():
    import manage
    conn = _DiagConn({str(UID): "Гипербореец"})
    pg = SimpleNamespace(pool=_DiagPool(conn))

    plain = asyncio.run(manage._collect_aliases_diag(
        pg, chat_ids=[CHAT_A]))
    assert "merged_view" not in plain["chats"][0]
    assert "Гипербореец" not in json.dumps(plain, ensure_ascii=False)

    shown = asyncio.run(manage._collect_aliases_diag(
        pg, chat_ids=[CHAT_A], include_names=True))
    rows = {row["user_id"]: row for row in shown["chats"][0]["merged_view"]}
    assert rows[UID]["chat_alias"] == "Гипербореец"
    assert rows[UID]["global_alias"] == "Макс"
    assert rows[UID]["effective"] == "Гипербореец"
    assert rows[UID]["source"] == "chat"
    assert rows[OTHER]["source"] == "global"
    assert shown["global_merged"]


@pytest.mark.asyncio
async def test_a15_unavailable_config_is_diagnosed_not_silent():
    chat_params.set_chat_params_cache(BrokenCache())
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.resolve(UID) == "Макс"          # глобальный слой доступен
    assert resolver.scope_report["ok"] is False
    assert "chat_unavailable" in resolver.scope_report["invalid_json"]


@pytest.mark.asyncio
async def test_a15_invalid_json_is_diagnosed():
    cache = FakeCache({CHAT_A: _root(
        {"limits.summary_aliases": "{not valid json"})})
    chat_params.set_chat_params_cache(cache)
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.resolve(UID) == "Макс"
    assert resolver.scope_report["ok"] is False
    assert "chat_invalid_json" in resolver.scope_report["invalid_json"]


@pytest.mark.asyncio
async def test_a16_harness_telegram_id_to_context_and_result():
    """Входной Telegram ID → эффективный алиас → UserResolutionMap → имя."""
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    db = FakeDB([_row(uid=UID, author="Игорь из Telegram"),
                 _row(uid=OTHER, author="Лёша")])
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    service = _service(view, db=db)

    # 1. начало хода: per-chat сборка (live, без стартового снапшота)
    await bind_turn_aliases(CHAT_A)
    # 2. реальный путь контекста: participants из БД → roster → карта
    participants = await service._active_participants(CHAT_A)
    alias_map = service._build_alias_map(participants, participants)
    # 3. результат отображения/обращения
    result = service._resolve_name(_user())

    assert f"Гипербореец — {UID}" in alias_map
    assert f"Леха — {OTHER}" in alias_map
    assert "Игорь из Telegram" not in alias_map
    assert result == "Гипербореец"
