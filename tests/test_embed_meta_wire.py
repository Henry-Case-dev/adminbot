"""EMBED-META-WIRE (CANARY-03): фактические метаданные embed-ответа.

`LLMClient.embed()`/`embed_once()` возвращают ровно `list[list[float]]`
(публичный контракт не меняется), но дополнительно сохраняют метаданные
ТЕЛА ответа в `client.last_embed_meta` — их читает проба совместимости
(`embedding_control_plane`). Нет поля в ответе → `None` (неизвестность),
без исключений.

TEST-LIFECYCLE: INTEGRATION owner=EMBED-IDENTITY-COMPAT/CANARY-03
"""
import httpx
import pytest

from services.llm_client import LLMClient


def _make_client(handler, monkeypatch):
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    client = LLMClient("https://api.test/v1", "test-key", "chat-model",
                       "embed-model", fallback_base_url="",
                       fallback_model="", fallback_api_key="",
                       embed_fallback_base_url="",
                       embed_fallback_api_key="",
                       embed_fallback_model="",
                       embed_fallback_api_key_2="")
    client.backoff_base = 0
    return client


def _handler(payload: dict):
    def handler(request):
        return httpx.Response(200, json=payload, request=request)

    return handler


_VECTORS = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@pytest.mark.asyncio
async def test_embed_records_actual_model_from_response_body(monkeypatch):
    """`model` берётся из ТЕЛА ответа, а не из конфига клиента."""
    client = _make_client(_handler({
        "object": "list", "model": " models/gemini-embedding-001 ",
        "revision": "2026-09-01",
        "params": {"task": "retrieval"},
        "data": [{"embedding": v} for v in _VECTORS],
    }), monkeypatch)

    out = await client.embed(["a", "b"])

    assert out == _VECTORS, "возвращаемый тип/значение не изменились"
    assert client.last_embed_meta["model"] == "models/gemini-embedding-001"
    assert client.last_embed_meta["revision"] == "2026-09-01"
    assert client.last_embed_meta["params"] == {"task": "retrieval"}
    assert client.last_embed_meta["dims"] == 3


@pytest.mark.asyncio
async def test_embed_without_model_keeps_metadata_unknown(monkeypatch):
    """Ответ без `model` — прежнее поведение: метаданные unknown, не ошибка."""
    client = _make_client(_handler({
        "object": "list",
        "data": [{"embedding": v} for v in _VECTORS],
    }), monkeypatch)

    out = await client.embed(["a", "b"])

    assert out == _VECTORS
    assert client.last_embed_meta["model"] is None
    assert client.last_embed_meta["revision"] is None
    assert client.last_embed_meta["params"] is None
    assert client.last_embed_meta["dims"] == 3


@pytest.mark.asyncio
async def test_embed_once_records_metadata_without_changing_contract(monkeypatch):
    """`embed_once` (путь EmbeddingExecutor) отдаёт те же векторы и мету."""
    client = _make_client(_handler({
        "model": "text-embedding-004",
        "revision": "2026-10-01",
        "data": [{"embedding": v} for v in _VECTORS],
    }), monkeypatch)

    out = await client.embed_once(["a", "b"], api_key="k")

    assert out == _VECTORS
    assert client.last_embed_meta["model"] == "text-embedding-004"
    assert client.last_embed_meta["revision"] == "2026-10-01"
    assert client.last_embed_meta["params"] is None
    assert client.last_embed_meta["dims"] == 3


def test_client_starts_with_empty_metadata():
    """До первого ответа атрибут существует и пуст — проба не падает."""
    client = LLMClient("https://api.test/v1", "test-key", "chat-model",
                       "embed-model", fallback_base_url="", fallback_model="",
                       fallback_api_key="", embed_fallback_base_url="",
                       embed_fallback_api_key="", embed_fallback_model="",
                       embed_fallback_api_key_2="")
    assert client.last_embed_meta == {"model": None, "revision": None,
                                      "params": None, "dims": None}
