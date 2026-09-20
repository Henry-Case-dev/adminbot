"""F0.1 round1025 (ревью, item 9) — per-key optimistic глобального пути
(`POST /api/config` без X-Chat-Id): D-409-3.

* совпавший per-key токен → обычная запись;
* устаревший токен + совпадающее значение → `revalidated` без записи;
* устаревший токен + отличающееся значение → 409 `conflicting` (без записи).
"""
import types

import json

import pytest
from fastapi import HTTPException

from web.api import routes

_KEY = "models.llm_timeout"


class _Cache:
    pg_available = True

    def __init__(self):
        self.store = {_KEY: 42}
        self.updated = {_KEY: "t1"}
        self.written = []

    def get(self, key):
        return self.store.get(key)

    def get_updated_at(self, key):
        return self.updated.get(key)

    async def set_many(self, items):
        for key, value, _category in items:
            self.written.append((key, value))
            self.store[key] = value
            self.updated[key] = None

    async def set(self, key, value, category):
        self.written.append((key, value))
        self.store[key] = value
        self.updated[key] = None


def _payload(value, token):
    return types.SimpleNamespace(
        items=[types.SimpleNamespace(key=_KEY, value=value,
                                     updated_at=token)],
        updated_at=None)


@pytest.fixture
def cache(monkeypatch):
    c = _Cache()
    monkeypatch.setattr(routes, "get_cache", lambda request: c)
    monkeypatch.setattr(routes, "can_edit_param", lambda c2, uid, key: True)
    monkeypatch.setattr(routes, "can_view_key_value",
                        lambda c2, uid, key: True)
    return c


@pytest.mark.asyncio
async def test_matching_token_writes(cache):
    out = await routes._post_config_global(
        object(), _payload(43, "t1"), types.SimpleNamespace(id=1))
    assert out["updated"] == [_KEY]
    assert cache.store[_KEY] == 43
    assert cache.written == [(_KEY, 43)]


@pytest.mark.asyncio
async def test_stale_token_same_value_revalidated(cache):
    out = await routes._post_config_global(
        object(), _payload(42, "old-token"), types.SimpleNamespace(id=1))
    assert out.get("revalidated") is True
    assert cache.written == []                       # записи не было
    assert out["updated"] == [_KEY]


@pytest.mark.asyncio
async def test_stale_token_diff_value_conflict(cache):
    with pytest.raises(HTTPException) as exc:
        await routes._post_config_global(
            object(), _payload(99, "old-token"), types.SimpleNamespace(id=1))
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["code"] == "conflict"
    assert detail["conflicting"] == [
        {"key": _KEY, "your_value": 99, "server_value": 42}]
    assert cache.written == []


@pytest.mark.asyncio
async def test_no_token_keeps_legacy_shape(cache):
    out = await routes._post_config_global(
        object(), _payload(44, None), types.SimpleNamespace(id=1))
    assert out == {"updated": [_KEY]}                # форма ответа не менялась
    assert cache.store[_KEY] == 44


@pytest.mark.asyncio
async def test_secret_conflict_does_not_leak_server_value(cache):
    """M-3 (ревью, R17): 409 по секретному ключу НЕ отдаёт сырое значение."""
    secret_key = "keys.llm_api_key"
    cache.store[secret_key] = "SECRET-OLD-VALUE"
    cache.updated[secret_key] = "t1"
    payload = types.SimpleNamespace(
        items=[types.SimpleNamespace(key=secret_key,
                                     value="SECRET-NEW-VALUE",
                                     updated_at="stale-token")],
        updated_at=None)
    with pytest.raises(HTTPException) as exc:
        await routes._post_config_global(
            object(), payload, types.SimpleNamespace(id=1))
    assert exc.value.status_code == 409
    item = exc.value.detail["conflicting"][0]
    assert item["key"] == secret_key
    assert item["server_value"] is None
    assert item.get("secret") is True
    dumped = json.dumps(exc.value.detail)
    assert "SECRET-OLD-VALUE" not in dumped, "серверное значение не утекло"
