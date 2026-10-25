"""P0 corrective 25.10.2026 §2 — единый runtime-путь алиасов (F1–F7).

Durable: CONTRACT/REGRESSION (README §2.3), без прода/Telegram/LLM.
TEST-LIFECYCLE: CONTRACT/REGRESSION owner=SPEECH-P0-ALIAS-2026-10-25
"""
import time
from types import SimpleNamespace

import pytest

from services import chat_params, summary_aliases
from services.direct_chat_service import DirectChatService
from services.direct_l1 import build_l1_context, render_window_lines
from services.initiative_observer import (
    build_digest_user_prompt,
    build_eval_user_prompt,
)
from services.summary_aliases import (
    AliasResolver,
    LiveAliasView,
    bind_turn_aliases,
    build_alias_resolver,
)

CHAT = -100777
UID = 42115912          # живой Telegram ID из §2.3 (Макс, не «Гипербореец»)
OTHER = 1002
GLOBAL = {"42115912": "Макс", "1002": "Леха"}


class FakeCache:
    def __init__(self, items=None):
        self.items = dict(items or {})

    async def get_chat_params(self, chat_id):
        return dict(self.items.get(chat_id, {}))

    async def get_chat_params_checked(self, chat_id):
        return dict(self.items.get(chat_id, {})), True


def _root(overrides=None):
    return {"v": 1, "overrides": dict(overrides or {}), "gates": {},
            "keys": {}, "perm_overrides": {}, "meta": {}}


class _EmptyCursor:
    async def fetchall(self):
        return []


class FakeDB:
    def __init__(self):
        self.db = self

    async def execute(self, *args, **kwargs):
        return _EmptyCursor()

    async def get_active_participants(self, chat_id, since, cap):
        return []


class FakeMemory:
    async def get_window_messages(self, chat_id):
        return []


@pytest.fixture(autouse=True)
def alias_env(monkeypatch):
    summary_aliases.reset_turn_alias_resolver()
    chat_params.set_chat_params_cache(FakeCache())
    monkeypatch.setattr(
        "services.hot_config.get",
        lambda key, default=None: (dict(GLOBAL)
                                   if key == "limits.summary_aliases"
                                   else default))
    yield
    summary_aliases.reset_turn_alias_resolver()
    chat_params.set_chat_params_cache(None)


def _set_chat(aliases):
    cache = chat_params.get_chat_params_cache()
    cache.items[CHAT] = _root({"limits.summary_aliases": dict(aliases)})


def _view():
    return LiveAliasView(AliasResolver(dict(GLOBAL)))


def _service(view):
    return DirectChatService(FakeMemory(), FakeDB(), object(), view,
                             bot_id=999, bot_username="bot")


def _row(uid=UID, author="Гипербореец", text="сообщение", msg_id=1):
    return {"id": msg_id, "user_id": uid, "author_name": author,
            "text": text, "timestamp": 100, "media_type": "text",
            "reply_to_id": None, "tg_message_id": None}


def _reply_message(uid=UID, first="Гипербореец", username="hyper",
                   text="цитируемый текст"):
    reply = SimpleNamespace(from_user=SimpleNamespace(
        id=uid, first_name=first, last_name=None, username=username),
        text=text, caption=None)
    return SimpleNamespace(reply_to_message=reply)


# ── F1: reply-блок — alias + uid, а не first_name ──────────────────────────

@pytest.mark.asyncio
async def test_reply_block_uses_alias_and_uid():
    _set_chat({})
    await bind_turn_aliases(CHAT)
    block = _service(_view())._l1_reply_block(_reply_message())
    assert f"автор: Макс [user:{UID}]" in block
    assert "Гипербореец" not in block
    assert block.endswith("цитируемый текст")


@pytest.mark.asyncio
async def test_reply_block_prefers_chat_alias_without_restart():
    view = _view()
    _set_chat({str(UID): "Первый"})
    await bind_turn_aliases(CHAT)
    service = _service(view)
    assert "Первый" in service._l1_reply_block(_reply_message())
    _set_chat({str(UID): "Второй"})
    await bind_turn_aliases(CHAT)
    block = service._l1_reply_block(_reply_message())
    assert "Второй" in block and "Первый" not in block


# ── F2: Observer — optional resolver, иначе байт-паритет ────────────────────

@pytest.mark.asyncio
async def test_observer_eval_uses_alias_not_author_name():
    _set_chat({})
    await bind_turn_aliases(CHAT)
    prompt = build_eval_user_prompt([_row()], alias_resolver=_view())
    assert f"[user:{UID}] Макс: сообщение" in prompt
    assert "Гипербореец" not in prompt


def test_observer_without_resolver_is_byte_parity():
    row = _row()
    assert build_eval_user_prompt([row]) == (
        f"<Fresh_Chat_Window>\n- [msg:1] [user:{UID}] "
        "Гипербореец: сообщение\n</Fresh_Chat_Window>")
    assert build_digest_user_prompt([row]) == (
        f"<Skipped_Interval>\n- [msg:1] [user:{UID}] "
        "Гипербореец: сообщение\n</Skipped_Interval>")


@pytest.mark.asyncio
async def test_observer_digest_uses_alias():
    _set_chat({})
    await bind_turn_aliases(CHAT)
    text = build_digest_user_prompt([_row()], alias_resolver=_view())
    assert f"[user:{UID}] Макс: сообщение" in text
    assert "Гипербореец" not in text


# ── F3: фоновые тики — chat override, не стартовый снапшот ─────────────────

@pytest.mark.asyncio
async def test_background_tick_binds_chat_override_not_startup_snapshot():
    from services.lore_worker import LoreWorker

    _set_chat({str(UID): "Фоновый"})
    view = _view()                       # fallback = стартовый глобальный снапшот
    seen = {}

    class Store:
        async def list_active_chats(self):
            return [CHAT]

    worker = LoreWorker(Store(), aliases=view)

    async def _impl(chat_id, *, manual=False):
        seen["name"] = view.resolve(UID, "Гипербореец", None)
        return {"status": "ok"}

    worker._generate_for_chat_impl = _impl
    await worker.generate_for_chat(CHAT)
    assert seen["name"] == "Фоновый"


@pytest.mark.asyncio
async def test_startup_snapshot_not_used_for_chat_bound_paths():
    _set_chat({str(UID): "Свежий"})
    view = _view()
    await bind_turn_aliases(CHAT)
    assert view.resolve(UID) == "Свежий"
    # без привязки live-view обязан показывать снапшот — контроль контраста
    summary_aliases.reset_turn_alias_resolver()
    assert view.resolve(UID) == "Макс"


# ── F4/F3: RAG/история не вытесняют карту; два uid не сливаются ─────────────

@pytest.mark.asyncio
async def test_old_name_in_rag_does_not_override_map_name():
    _set_chat({})
    await bind_turn_aliases(CHAT)
    service = _service(_view())
    block = service._build_alias_map([_row(author="Гипербореец из RAG")])
    assert f"Макс — {UID}" in block
    assert "Гипербореец" not in block
    assert "актуальное имя участника — по user_id" in block


@pytest.mark.asyncio
async def test_two_uids_same_display_not_merged():
    global_two = {str(UID): "Макс", str(OTHER): "Макс"}
    cache = chat_params.get_chat_params_cache()
    cache.items[CHAT] = _root({})
    resolver = AliasResolver(global_two)
    service = DirectChatService(FakeMemory(), FakeDB(), object(),
                                LiveAliasView(resolver), bot_id=999)
    summary_aliases.set_turn_alias_resolver(resolver)
    block = service._build_alias_map([
        _row(uid=UID, text="a", msg_id=1),
        _row(uid=OTHER, text="b", msg_id=2)])
    rows = [ln for ln in block.splitlines() if ln.startswith("Макс")]
    assert len(rows) == 2                      # два человека, не один
    assert any(str(UID) in ln for ln in rows)
    assert any(str(OTHER) in ln for ln in rows)
    for ln in rows:
        assert not (str(UID) in ln and str(OTHER) in ln)
    assert resolver.canon_name("Макс", UID) == "Макс"
    assert resolver.canon_name("Макс", OTHER) == "Макс"


# ── адресат vs третье лицо; все пути — один порядок ─────────────────────────

@pytest.mark.asyncio
async def test_third_party_mention_keeps_addressee():
    _set_chat({str(OTHER): "Леха"})
    await bind_turn_aliases(CHAT)
    service = _service(_view())
    target = SimpleNamespace(id=UID, first_name="Гипербореец",
                             last_name=None, username="hyper")
    reply_block = service._l1_reply_block(_reply_message(uid=OTHER,
                                                          first="Гость"))
    assert f"Леха [user:{OTHER}]" in reply_block
    assert f"[user:{UID}]" not in reply_block
    assert service._resolve_name(target) == "Макс"


@pytest.mark.asyncio
async def test_all_paths_share_one_order():
    _set_chat({})
    await bind_turn_aliases(CHAT)
    view = _view()
    service = _service(view)
    row = _row()
    assert service._build_alias_map([row]).count("Макс —") == 1
    line = render_window_lines([row], 12, with_ids=True,
                               alias_resolver=view)[0]
    assert f"[user:{UID}] Макс:" in line
    assert f"Макс: сообщение" in build_eval_user_prompt(
        [row], alias_resolver=view)
    assert f"[user:{UID}]" in service._l1_reply_block(_reply_message())


# ── F5: protected/clear/forget по Telegram ID ───────────────────────────────

@pytest.mark.asyncio
async def test_protected_facts_read_by_subject_ref_id(tmp_path):
    from services.database import DatabaseService

    db = DatabaseService(str(tmp_path / "alias-protected.db"))
    await db.initialize()
    try:
        await db.db.execute(
            "INSERT INTO protected_facts "
            "(chat_id, user_name, fact, created_at, subject_ref_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (CHAT, "Новое имя", "секрет про кофе", time.time(), UID))
        await db.db.commit()
        found = await db.get_protected_facts(
            CHAT, "Старое имя", include_chat_level=False, user_id=UID)
        assert found == ["секрет про кофе"]
        lost = await db.get_protected_facts(
            CHAT, "Старое имя", include_chat_level=False)
        assert lost == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_clear_and_forget_scope_by_subject_ref_id(tmp_path):
    from services import provenance
    from services.database import DatabaseService

    db = DatabaseService(str(tmp_path / "alias-clear.db"))
    await db.initialize()
    try:
        ref = await provenance.resolve_source_ref(
            db, provenance.user_source_ref(CHAT, UID))
        assert ref is not None
        await db.insert_graph_fact(
            CHAT, "Макс любит кофе", "bot_direct_reply", None,
            target_user="Новое имя", subject_ref_id=int(ref))
        removed = await db.forget_direct_facts(
            CHAT, "Новое имя", "кофе", int(time.time()) + 1,
            target_user_id=UID)
        assert removed == 1
        await db.insert_graph_fact(
            CHAT, "Макс любит чай", "bot_direct_reply", None,
            target_user="Новое имя", subject_ref_id=int(ref))
        cleared = await db.clear_direct_dialogue(
            CHAT, "Новое имя", target_user_id=UID)
        assert cleared >= 1
    finally:
        await db.close()


# ── фактический payload L1 содержит актуальное имя ─────────────────────────

@pytest.mark.asyncio
async def test_actual_l1_payload_carries_resolved_name():
    _set_chat({})
    await bind_turn_aliases(CHAT)
    view = _view()
    service = _service(view)
    payload = build_l1_context(
        query="что нового?",
        current_question="что нового?",
        reply_block=service._l1_reply_block(_reply_message()),
        window=[_row()], speaker="Макс", addressee="чат",
        with_ids=True, alias_resolver=view)
    assert f"Макс [user:{UID}]" in payload
    assert f"[user:{UID}] Макс:" in payload
    assert "Гипербореец" not in payload
