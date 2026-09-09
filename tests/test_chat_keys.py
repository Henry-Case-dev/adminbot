"""Раунд 10 (F-7, T-860 G3) — тесты BYOK: chat_keys store + llm_client-резолв.

Инварианты: никогда raw по API (только маски {key_name, configured, last4});
whitelist ('keys.llm_api_key'); локальный ключ приоритетнее глобального;
бюджет-исчерпание → NoApiKeyForChat (sandbox); fallback — глобальный путь.
"""
import pytest

from services import chat_keys
from services.llm_client import LLMClient, NoApiKeyForChat


class _FakeConn:
    def __init__(self):
        self.keys = {}
        self.history = []
        self.notifies = []

    async def fetchrow(self, sql, *args):
        if "FROM chat_keys" in sql:
            row = self.keys.get((args[0], args[1]))
            return {"chat_id": row[0], "key_name": row[1],
                    "key_value": row[2], "key_hint": "", "updated_at": None} \
                if row else None
        return None

    async def fetch(self, sql, *args):
        if "FROM chat_keys" in sql:
            chat_id = args[0]
            return [{"key_name": k[1], "key_value": v[2]}
                    for k, v in self.keys.items() if k[0] == chat_id]
        return []

    async def execute(self, sql, *args):
        if "INSERT INTO chat_keys" in sql:
            self.keys[(args[0], args[1])] = (args[0], args[1], args[2])
        if "DELETE FROM chat_keys" in sql:
            existed = (args[0], args[1]) in self.keys
            self.keys.pop((args[0], args[1]), None)
            return "DELETE 1" if existed else "DELETE 0"
        if "INSERT INTO chat_lore_history" in sql:
            self.history.append({"chat_id": args[0], "field": args[1],
                                 "changed_by": args[2],
                                 "old_value": args[3], "new_value": args[4]})
        return "UPDATE 1"

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)


@pytest.fixture
def fake_pg():
    conn = _FakeConn()
    return conn, _FakePg(conn)



@pytest.mark.asyncio
async def test_whitelist_validation(fake_pg):
    conn, pg = fake_pg
    with pytest.raises(ValueError):
        await chat_keys.set_chat_key(pg, -1, "keys.llm_fallback_api_key",
                                     "X", changed_by=1)
    assert not chat_keys.is_whitelisted("keys.embed_api_key")
    assert chat_keys.is_whitelisted("keys.llm_api_key")


@pytest.mark.asyncio
async def test_set_and_mask(fake_pg):
    conn, pg = fake_pg
    mask = await chat_keys.set_chat_key(pg, -10001, "keys.llm_api_key",
                                        "abc12345xyz", changed_by=7)
    assert mask == {"key_name": "keys.llm_api_key", "configured": True,
                    "last4": "5xyz"}
    assert conn.history and conn.history[0]["field"] == "chat_keys"
    assert conn.history[0]["changed_by"] == 7


@pytest.mark.asyncio
async def test_get_raw_for_service_only(fake_pg):
    conn, pg = fake_pg
    await chat_keys.set_chat_key(pg, -10001, "keys.llm_api_key",
                                 "secretvalue", changed_by=1)
    raw = await chat_keys.get_chat_key(pg, -10001, "keys.llm_api_key")
    assert raw == "secretvalue"            # сервис — пуллер (llm_client)
    listed = await chat_keys.list_own_keys(pg, -10001)
    assert listed == [{"key_name": "keys.llm_api_key", "configured": True,
                       "last4": "alue"}]


@pytest.mark.asyncio
async def test_delete_key_history(fake_pg):
    conn, pg = fake_pg
    await chat_keys.set_chat_key(pg, -1, "keys.llm_api_key", "v", changed_by=1)
    removed = await chat_keys.delete_chat_key(pg, -1, "keys.llm_api_key",
                                              changed_by=9)
    assert removed is True
    assert (await chat_keys.get_chat_key(pg, -1, "keys.llm_api_key")) is None
    assert conn.history[-1]["field"] == "chat_keys"
    assert conn.history[-1]["changed_by"] == 9


@pytest.mark.asyncio
async def test_llm_resolve_own_key_priority(fake_pg, monkeypatch):
    """Свой ключ чата → 'chat' источник; глобальный не смотрится вовсе."""
    conn, pg = fake_pg
    await chat_keys.set_chat_key(pg, -10001, "keys.llm_api_key",
                                 "OWNKEY1234", changed_by=1)
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    got = await client._resolve_api_key(-10001)
    assert got == "OWNKEY1234"
    assert client._byok_source == "chat"


@pytest.mark.asyncio
async def test_llm_resolve_global_uses_hot(fake_pg, monkeypatch):
    conn, pg = fake_pg
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    from services import hot_config as hot
    monkeypatch.setattr(hot, "get",
                        lambda key, default=None: "HOTKEY" if key ==
                        "keys.llm_api_key" else default)
    got = await client._resolve_api_key(-10001)
    assert got == "HOTKEY"
    assert client._byok_source == "global"


@pytest.mark.asyncio
async def test_llm_resolve_forbidden(fake_pg, monkeypatch):
    """allow_global=false + нет своего → NoApiKeyForChat('forbidden')."""
    conn, pg = fake_pg
    monkeypatch.setattr(
        "services.chat_params.get_all_chat_params",
        lambda chat_id: _aw({"v": 1, "keys": {"allow_global": False}}))
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    with pytest.raises(NoApiKeyForChat) as exc:
        await client._resolve_api_key(-10001)
    assert exc.value.reason == "forbidden"
    assert exc.value.chat_id == -10001


@pytest.mark.asyncio
async def test_llm_resolve_budget_exceeded(fake_pg, monkeypatch):
    conn, pg = fake_pg
    monkeypatch.setattr(
        "services.chat_params.get_all_chat_params",
        lambda chat_id: _aw({"v": 1, "keys": {"allow_global": True}}))
    monkeypatch.setattr(
        "services.chat_usage.budget_exceeded",
        lambda pg_, chat_id, tokens_estimate=0: _aw(True))
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    with pytest.raises(NoApiKeyForChat) as exc:
        await client._resolve_api_key(-10001)
    assert exc.value.reason == "budget"


@pytest.mark.asyncio
async def test_llm_resolve_failopen_global(monkeypatch):
    """PG down (методы падают) → глобальный ключ (fail-open spec §1.2)."""
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: None)
    got = await client._resolve_api_key(-10001)
    assert got == "GLOBALKEY"


@pytest.mark.asyncio
async def test_parallel_generate_usage_attributed_per_chat(fake_pg, monkeypatch):
    """ФИКС R6 (F-7 §5.2): параллельные вызовы generate() разных чатов —
    usage-счётчик атрибутируется КАЖДОМУ своему chat_id (никаких
    self._byok_chat_id-гонок: источник/чат — per-call)."""
    import asyncio

    conn, pg = fake_pg
    monkeypatch.setattr(
        "services.chat_params.get_all_chat_params",
        lambda chat_id: _aw({"v": 1, "keys": {"allow_global": True}}))
    monkeypatch.setattr(
        "services.chat_usage.budget_exceeded",
        lambda pg_, chat_id, tokens_estimate=0: _aw(False))
    captured = []

    async def fake_report_call(pg_, chat_id, tokens=0):
        captured.append((chat_id, tokens))

    monkeypatch.setattr("services.chat_usage.report_call", fake_report_call)
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    # под-поток per-call: ключ уже решён; _post — медленный с запором
    # (гонка видна до фикса: ещё НЕ решённые чаты перекручивали источник).
    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "привет"}}]}

    async def fake_post(path, payload, api_key=None):
        await asyncio.sleep(0.01)
        return _Resp()

    monkeypatch.setattr(client, "_post", fake_post)
    keys = await asyncio.gather(
        client.generate([{"role": "user", "content": "для чата А"}],
                        chat_id=-1001),
        client.generate([{"role": "user", "content": "для чата Б"}],
                        chat_id=-1002),
    )
    assert keys == ["привет", "привет"]
    # usage: РОВНО по одному вызову на каждый чат и НИКАКИХ чужих
    assert sorted(c[0] for c in captured) == [-1002, -1001]
    assert len(set(c[0] for c in captured)) == 2


@pytest.mark.asyncio
async def test_parallel_resolve_does_not_stomp_source(fake_pg, monkeypatch):
    """ФИКС R6: _resolve_api_key_and_source — гонка двух чатов не отдаёт
    ключ одного чата в usage другого (независимые per-call корутины)."""
    import asyncio

    conn, pg = fake_pg
    await chat_keys.set_chat_key(pg, -201, "keys.llm_api_key", "OWN_A",
                                 changed_by=1)
    await chat_keys.set_chat_key(pg, -202, "keys.llm_api_key", "OWN_B",
                                 changed_by=1)
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    results = await asyncio.gather(
        client._resolve_api_key_and_source(-201),
        client._resolve_api_key_and_source(-202),
        client._resolve_api_key_and_source(-203),
    )
    assert results == [("OWN_A", "chat"), ("OWN_B", "chat"),
                       ("GLOBALKEY", "global")]


def _aw(value):
    import asyncio

    async def _inner(*a, **kw):
        return value

    return _inner()


# ═══ F-15 (T-971, spec §3) — BYOK-фоллбэк и details-снапшот ════════════════


@pytest.mark.asyncio
async def test_llm_resolve_budget_own_key_fallback(fake_pg, monkeypatch):
    """F-15 (§3.2): бюджет исчерпан, но ПОВТОРНОЕ чтение находит СВОЙ ключ
    (гонка/персист между шагом 1 и 3) → source 'chat' (ответ НЕ sandbox,
    глобальный бюджет НЕ тратится)."""
    conn, pg = fake_pg
    monkeypatch.setattr(
        "services.chat_params.get_all_chat_params",
        lambda chat_id: _aw({"v": 1, "keys": {"allow_global": True}}))
    monkeypatch.setattr(
        "services.chat_usage.budget_exceeded",
        lambda pg_, chat_id, tokens_estimate=0: _aw(True))
    calls = {"n": 0}

    async def flaky_get_chat_key(pg_, chat_id, key_name):
        calls["n"] += 1
        # первый вызов (шаг 1) — ключа ещё нет; второй (фоллбэк) — появился
        return "OWNKEY_FALLBACK" if calls["n"] >= 2 else None

    monkeypatch.setattr("services.chat_keys.get_chat_key", flaky_get_chat_key)
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    key, source = await client._resolve_api_key_and_source(-10001)
    assert key == "OWNKEY_FALLBACK"
    assert source == "chat"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_llm_resolve_budget_details_snapshot(fake_pg, monkeypatch):
    """F-15 (§3.1): бюджет + нет ключа → NoApiKeyForChat('budget') с
    details-снапшотом (used/limit/day/resolve_path; БЕЗ секретов)."""
    conn, pg = fake_pg
    monkeypatch.setattr(
        "services.chat_params.get_all_chat_params",
        lambda chat_id: _aw({"v": 1, "keys": {"allow_global": True}}))
    monkeypatch.setattr(
        "services.chat_usage.budget_exceeded",
        lambda pg_, chat_id, tokens_estimate=0: _aw(True))
    monkeypatch.setattr(
        "services.chat_usage.used_today",
        lambda pg_, chat_id: _aw({"llm_calls": 25, "llm_tokens": 99_900}))
    monkeypatch.setattr("services.chat_usage._budget_limit_requests",
                        lambda default=25: 25)
    monkeypatch.setattr("services.chat_usage._budget_limit_tokens",
                        lambda default=100000: 100000)
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    with pytest.raises(NoApiKeyForChat) as exc:
        await client._resolve_api_key(-10001)
    assert exc.value.reason == "budget"
    details = exc.value.details
    assert details is not None
    assert details["resolve_path"] == "budget"
    assert details["used_calls"] == 25
    assert details["limit_calls"] == 25
    assert details["used_tokens"] == 99_900
    assert details["limit_tokens"] == 100_000
    assert details["allow_global"] is True
    assert "day" in details and details["day"]
    # R17: никаких значений ключей в снапшоте
    assert "GLOBALKEY" not in repr(details)
    assert "OWNKEY" not in repr(details)


@pytest.mark.asyncio
async def test_llm_resolve_forbidden_details(fake_pg, monkeypatch):
    """F-15 (§3.1): ветка forbidden несёт {resolve_path, allow_global: False}."""
    conn, pg = fake_pg
    monkeypatch.setattr(
        "services.chat_params.get_all_chat_params",
        lambda chat_id: _aw({"v": 1, "keys": {"allow_global": False}}))
    client = LLMClient("http://x", "GLOBALKEY", "m", "")
    monkeypatch.setattr(client, "_pg", lambda: pg)
    with pytest.raises(NoApiKeyForChat) as exc:
        await client._resolve_api_key(-10001)
    assert exc.value.reason == "forbidden"
    assert exc.value.details == {"resolve_path": "forbidden",
                                 "allow_global": False}


def test_no_api_key_default_message_unchanged():
    """Без details — прежний текст исключения (совместимость)."""
    exc = NoApiKeyForChat(-10001, "budget")
    assert exc.details is None
    assert str(exc) == "no api key for chat: chat_id=-10001 reason=budget"


# ═══ F-15 (T-971, spec §3.1) — формат WARNING sandbox-пути ═════════════════

class TestF15SandboxWarningMarker:
    def test_direct_warning_keeps_anchor_and_has_details(self):
        """Подстрока «no key — sandbox answer» сохранена; формат расширен
        reason + details (снапшот без секретов)."""
        src = open("services/direct_chat_service.py", encoding="utf-8").read()
        assert "[direct] no key — sandbox answer" in src
        assert "reason=%s" in src
        assert "details=%s" in src
        assert 'getattr(exc, "details", None)' in src

    def test_no_api_key_exception_carries_details_attr(self):
        from services.llm_client import NoApiKeyForChat as Exc
        exc = Exc(1, "budget", details={"resolve_path": "budget"})
        assert exc.details == {"resolve_path": "budget"}
        assert "budget" in str(exc)
