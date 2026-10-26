"""ASAP 3 Corrective §4–§6 — единый порядок имён и merge алиасов по user_id.

Durable: CONTRACT (A1–A3, A7–A11, A14), REGRESSION (A4–A6, A15),
INTEGRATION (A12/A13/A16 harness). Живые сообщения не отправляются.
TEST-LIFECYCLE: CONTRACT/REGRESSION/INTEGRATION owner=ASAP3-IDENTITY
"""
import asyncio
import json
import time
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
        self.db = self

    async def execute(self, *args, **kwargs):
        return _EmptyCursor()

    async def get_active_participants(self, chat_id, since, cap):
        return list(self.participants)[:cap]


class _EmptyCursor:
    async def fetchall(self):
        return []


class FakeMemory:
    def __init__(self, window=None):
        self.window = list(window or [])

    async def get_window_messages(self, chat_id):
        return list(self.window)


class CaptureLLM:
    """L1 fake: запоминает payload, возвращает пустой план."""

    def __init__(self):
        self.messages = None

    async def generate(self, messages, **kwargs):
        self.messages = messages
        return "{}"


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
async def test_a13_initiative_l1_and_l2_use_alias_not_author_name():
    """A13 (инициатива): адресат + L1-контекст + L2-окно — одно имя по uid."""
    from services import direct_l1 as _l1

    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    llm = CaptureLLM()
    row = dict(_row(author="Игорь (имя из клиента)"), id=5, reply_to_id=None)
    service = DirectChatService(
        FakeMemory([row]), FakeDB(), llm, view,
        bot_id=999, bot_username="bot")
    await bind_turn_aliases(CHAT_A)

    await service.plan_initiative_decision(
        CHAT_A,
        {"addressee_user_id": UID, "kind": "reply", "origin": "observer",
         "goal": "ответить на свежую реплику"},
        correlation_id="a13-init")

    user_text = llm.messages[1]["content"]
    assert "[user:1001] Гипербореец:" in user_text
    assert "участник Гипербореец [user:1001]" in user_text
    assert "Игорь (имя из клиента)" not in user_text

    # L2 Writer получает то же окно тем же рендером.
    l2_lines = _l1.render_window_lines(
        [row], 12, with_ids=True, alias_resolver=view)
    assert l2_lines and "Гипербореец:" in l2_lines[0]
    assert "Игорь (имя из клиента)" not in "\n".join(l2_lines)


@pytest.mark.asyncio
async def test_dossier_keeps_fact_with_stable_uid_after_rename(tmp_path):
    """BLOCKER-2: /dossier читает факты по subject_ref_id, а не только по
    старому target_user; legacy-строки без uid автоматически не привязываются."""
    from services.database import DatabaseService
    from services import provenance
    from web.api import chat_lore

    db = DatabaseService(str(tmp_path / "dossier.db"))
    await db.initialize()
    try:
        ref = await provenance.resolve_source_ref(
            db, provenance.user_source_ref(CHAT_A, UID))
        assert ref is not None
        await db.insert_graph_fact(
            CHAT_A, "Игорь любит кофе", "user_memory", None,
            target_user="Игорь", subject_ref_id=int(ref),
            attribution_method="self_report", assertion_kind="personal")
        # Legacy-строка без uid: не должна привязаться к uid по имени.
        await db.insert_graph_fact(
            CHAT_A, "Легаси без uid", "user_memory", None,
            target_user="Игорь")

        payload = await chat_lore._dossier_payload(
            db, CHAT_A, UID, "Гипербореец")
        facts = list(payload.get("facts") or [])
        assert "Игорь любит кофе" in facts
        assert "Легаси без uid" not in facts

        # RED-контракт: без user_id (старый web-путь) факт с устойчивым
        # subject_ref_id не находится по новому имени.
        name_only = await db.get_persona_card(
            CHAT_A, "Гипербореец", 10, int(time.time()))
        assert "Игорь любит кофе" not in (name_only.get("facts") or [])
    finally:
        await db.close()


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


# ── A17–A25: P0 corrective 25.10.2026 — reply/observer/фон/RAG/коллизии ────

def _reply(user, text="цитируемая реплика"):
    return SimpleNamespace(
        reply_to_message=SimpleNamespace(from_user=user, text=text,
                                         caption=None))


@pytest.mark.asyncio
async def test_a17_reply_block_uses_alias_and_uid():
    """§2.3-7 (F1): автор цитаты — тот же каскад по uid + [user:<id>];
    first_name клиента как источник имени не используется, а смена алиаса
    применяется без рестарта."""
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    service = _service(view)
    await bind_turn_aliases(CHAT_A)
    block = service._l1_reply_block(_reply(_user(first="Игорь из клиента")))
    assert f"автор: Гипербореец [user:{UID}]" in block
    assert "Игорь из клиента" not in block
    assert block.endswith("цитируемая реплика")
    # §2.3-4: тот же экземпляр сервиса видит новый алиас на следующем ходе.
    _set_chat(CHAT_A, {str(UID): "Новое Имя"})
    await bind_turn_aliases(CHAT_A)
    updated = service._l1_reply_block(_reply(_user(first="Игорь из клиента")))
    assert f"автор: Новое Имя [user:{UID}]" in updated
    assert "Гипербореец" not in updated


@pytest.mark.asyncio
async def test_a18_observer_eval_uses_alias_not_author_name():
    """§2.3-11 (F2): Observer-промпт берёт актуальное имя по uid, а не
    замороженный author_name; окно и дайджест — один рендер."""
    from services.initiative_observer import (
        build_digest_user_prompt,
        build_eval_user_prompt,
    )

    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    await bind_turn_aliases(CHAT_A)
    row = _row(author="Игорь (имя из клиента)")
    prompt = build_eval_user_prompt([row], alias_resolver=view)
    assert f"[user:{UID}] Гипербореец: сообщение" in prompt
    assert "Игорь (имя из клиента)" not in prompt
    digest = build_digest_user_prompt([row], alias_resolver=view)
    assert f"[user:{UID}] Гипербореец: сообщение" in digest
    assert "Игорь (имя из клиента)" not in digest


def test_a18_observer_without_resolver_keeps_author_name_bytes():
    """F2-контракт: без резолвера вывод байт-в-байт прежний."""
    from services.initiative_observer import (
        build_digest_user_prompt,
        build_eval_user_prompt,
    )

    row = _row(author="Старое имя")
    assert f"[user:{UID}] Старое имя: сообщение" in build_eval_user_prompt(
        [row])
    assert f"[user:{UID}] Старое имя: сообщение" in build_digest_user_prompt(
        [row])


class _LoreStore:
    """Минимальный list_active_chats для фонового тика (без PG)."""

    def __init__(self, chats):
        self._chats = list(chats)

    async def list_active_chats(self):
        return list(self._chats)


@pytest.mark.asyncio
async def test_a19_background_job_sees_chat_override_without_restart():
    """§2.3-4/5 (F3/D3): фоновый тик видит chat override и смену настройки
    без рестарта; стартовый снапшот не является источником имени."""
    from services.lore_worker import LoreWorker

    _set_chat(CHAT_A, {str(UID): "Первый"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    seen: dict = {}
    worker = LoreWorker(_LoreStore([CHAT_A]), aliases=view)

    async def _impl(chat_id, *, manual=False):
        seen["name"] = view.resolve(UID, "Игорь", None)
        return {"status": "ok"}

    worker._generate_for_chat_impl = _impl
    await worker.tick()
    assert seen["name"] == "Первый"
    _set_chat(CHAT_A, {str(UID): "Второй"})
    await worker.tick()
    assert seen["name"] == "Второй"


@pytest.mark.asyncio
async def test_a20_startup_snapshot_not_used_for_chat_bound_paths():
    """§2.3-5 (F3): chat-bound путь получает резолвер чата, а стартовый
    снапшот остаётся fallback'ом и не мутируется."""
    from services.lore_worker import LoreWorker

    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    startup = AliasResolver(dict(GLOBAL))
    view = LiveAliasView(startup)
    seen: dict = {}
    worker = LoreWorker(_LoreStore([CHAT_A]), aliases=view)

    async def _impl(chat_id, *, manual=False):
        current = summary_aliases.current_alias_resolver()
        seen["bound"] = current.resolve(UID) if current is not None else None
        seen["fallback"] = startup.resolve(UID)
        return {"status": "ok"}

    worker._generate_for_chat_impl = _impl
    await worker.tick()
    assert seen["bound"] == "Гипербореец"   # chat override, без рестарта
    assert seen["fallback"] == "Макс"       # стартовый снапшот не тронут


@pytest.mark.asyncio
async def test_a20_old_name_in_rag_does_not_replace_map_name():
    """§2.3-10 (F4): старое имя из RAG не вытесняет карту; в блоке есть
    инструкция брать актуальное имя по user_id."""
    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    service = _service(view)
    await bind_turn_aliases(CHAT_A)
    block = service._build_alias_map([_row(author="Игорь из RAG")])
    assert f"Гипербореец — {UID}" in block
    assert "Игорь из RAG" not in block
    assert "актуальное имя участника — по user_id" in block


@pytest.mark.asyncio
async def test_a21_two_uids_same_display_not_merged():
    """§2.3-9 (D7): одинаковый display у двух uid — две личности и
    различимый суффикс; при известном username — ник, иначе «#хвост»."""
    resolver = AliasResolver({str(UID): "Лёха", str(OTHER): "Лёха"})
    summary_aliases.set_turn_alias_resolver(resolver)
    service = _service(LiveAliasView(resolver))
    rows = [_row(uid=UID, author="Лёха"), _row(uid=OTHER, author="Лёха")]
    block = service._build_alias_map(rows, usernames={OTHER: "leha_two"})
    assert f"Лёха — {UID}" in block
    assert f"Лёха (leha_two) — {OTHER}" in block
    assert resolver.canon_name("Лёха", UID) == "Лёха"
    assert resolver.canon_name("Лёха", OTHER) == "Лёха"
    # D7 fallback: username неизвестен — прежний «#хвост», без слияния.
    block_plain = service._build_alias_map(rows)
    assert f"Лёха (#{str(OTHER)[-4:]}) — {OTHER}" in block_plain


@pytest.mark.asyncio
async def test_a22_history_searchable_by_old_name(tmp_path):
    """§2.3-6/10: старый текст остаётся в FTS/истории, но текущее имя —
    канонический алиас по uid, а карта требует предпочитать её."""
    from services.database import DatabaseService

    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    db = DatabaseService(str(tmp_path / "alias-fts.db"))
    await db.initialize()
    try:
        await db.save_smart_message(
            UID, CHAT_A, "Гипербореец вчера обещал разобраться", None,
            1000, "text", "Гипербореец")
        rows = await db.search_messages_fts(CHAT_A, "Гипербореец", 5)
        assert rows, "историческое упоминание должно находиться поиском"
        row = rows[0]
        assert "Гипербореец вчера" in str(row["text"])   # текст не переписан
        view = LiveAliasView(AliasResolver(dict(GLOBAL)))
        await bind_turn_aliases(CHAT_A)
        assert view.resolve(UID, "Игорь", "igor") == "Гипербореец"
        alias_map = _service(view)._build_alias_map([{
            "user_id": row["user_id"], "author_name": row["author_name"]}])
        assert f"Гипербореец — {UID}" in alias_map
        assert "актуальное имя участника — по user_id" in alias_map
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a25_third_party_mention_keeps_addressee():
    """§2.3-8 (F1): автор цитаты (третье лицо) не подменяет адресата."""
    from services.direct_l1 import build_l1_context

    _set_chat(CHAT_A, {str(OTHER): "Леха-другой"})
    view = LiveAliasView(AliasResolver(dict(GLOBAL)))
    service = _service(view)
    await bind_turn_aliases(CHAT_A)
    target = _user(uid=UID, first="Игорь", username="igor")
    reply_block = service._l1_reply_block(
        _reply(_user(uid=OTHER, first="Лёша", username="leha")))
    assert f"автор: Леха-другой [user:{OTHER}]" in reply_block
    assert f"[user:{UID}]" not in reply_block
    payload = build_l1_context(
        query="что он сказал?", current_question="что он сказал?",
        reply_block=reply_block,
        window=[_row(uid=OTHER, author="Лёша")],
        speaker="Макс", addressee=service._resolve_name(target),
        with_ids=True, alias_resolver=view)
    assert f"автор: Леха-другой [user:{OTHER}]" in payload
    assert "Адресат: Макс" in payload
    assert f"[user:{OTHER}] Леха-другой:" in payload


# ── F5/F7: protected/clear/forget по устойчивому id + R17-safe диагностика ──

@pytest.mark.asyncio
async def test_f5_protected_facts_read_by_subject_ref_id(tmp_path):
    from services.database import DatabaseService

    db = DatabaseService(str(tmp_path / "alias-protected.db"))
    await db.initialize()
    try:
        await db.db.execute(
            "INSERT INTO protected_facts "
            "(chat_id, user_name, fact, created_at, subject_ref_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (CHAT_A, "Игорь Старый", "любит кофе", time.time(), UID))
        await db.db.commit()
        found = await db.get_protected_facts(
            CHAT_A, "Игорь Новый", include_chat_level=False, user_id=UID)
        assert found == ["любит кофе"]
        # Legacy-контракт без uid: строка с привязкой по id не находится по
        # чужому имени (и не выдаётся за факт другого человека).
        assert await db.get_protected_facts(
            CHAT_A, "Игорь Новый", include_chat_level=False) == []
        # Чат-уровневые (user_name IS NULL) остаются доступны всем.
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, "
            "created_at) VALUES (?, NULL, ?, ?)",
            (CHAT_A, "лор чата", time.time()))
        await db.db.commit()
        both = await db.get_protected_facts(
            CHAT_A, "Игорь Новый", include_chat_level=True, user_id=UID)
        assert both[0] == "лор чата" and "любит кофе" in both
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_f5_protected_subject_ref_migration_is_idempotent(tmp_path):
    from services.database import DatabaseService

    db = DatabaseService(str(tmp_path / "alias-migrate.db"))
    await db.initialize()
    try:
        cols = await db._table_columns("protected_facts")
        assert "subject_ref_id" in cols          # аддитивная колонка есть
        cursor = await db.db.execute("PRAGMA user_version")
        version = (await cursor.fetchone())[0]
        assert await db._ensure_protected_facts_subject_ref() == 0
        assert await db._ensure_protected_facts_subject_ref() == 0
        cursor = await db.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == version   # user_version цел
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_f5_clear_and_forget_scope_by_subject_ref_id(tmp_path):
    from services import provenance
    from services.database import DatabaseService

    db = DatabaseService(str(tmp_path / "alias-clear.db"))
    await db.initialize()
    try:
        ref = await provenance.resolve_source_ref(
            db, provenance.user_source_ref(CHAT_A, UID))
        assert ref is not None
        now = int(time.time())
        await db.insert_graph_fact(
            CHAT_A, "Игорь любит кофе", "bot_direct_reply", None,
            target_user="Игорь Старый", subject_ref_id=int(ref))
        removed = await db.forget_direct_facts(
            CHAT_A, "Игорь Старый", "кофе", now + 1, target_user_id=UID)
        assert removed == 1
        await db.insert_graph_fact(
            CHAT_A, "Игорь любит чай", "bot_direct_reply", None,
            target_user="Игорь Старый", subject_ref_id=int(ref))
        cleared = await db.clear_direct_dialogue(
            CHAT_A, "Игорь Старый", target_user_id=UID)
        assert cleared >= 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_f7_alias_source_is_r17_safe():
    """F7: диагностика отдаёт слой имени по uid, но не значения алиасов."""
    from services.database import DatabaseService  # noqa: F401  (импорт-сеть)
    from web.api.routes import _alias_diagnostics_payload

    _set_chat(CHAT_A, {str(UID): "Гипербореец"})
    resolver = await build_alias_resolver(CHAT_A)
    assert resolver.scope_report["by_uid"] == {
        UID: "chat", OTHER: "global", 1003: "global"}
    payload = _alias_diagnostics_payload(
        resolver.scope_report, resolver.aliases)
    assert payload["scope"] == "merged"
    assert payload["per_uid"] == [
        {"user_id": UID, "alias_source": "chat", "name_present": True},
        {"user_id": OTHER, "alias_source": "global", "name_present": True},
        {"user_id": 1003, "alias_source": "global", "name_present": True},
    ]
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "Гипербореец" not in dumped          # R17: без значений имён
    assert "Макс" not in dumped
