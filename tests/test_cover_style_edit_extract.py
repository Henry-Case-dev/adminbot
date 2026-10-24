"""Cover Style Edit: разбор 2xx-ответов провайдера (issue 90).

Провайдер может вернуть бинарный image/*, OpenAI-подобный b64/url,
NanoGPT-подобный output/images/result. Раньше всё кроме data[0].b64_json/url
падало в bad_json; вторая попытка после prompt-limit теряла готовую картинку.
"""
from __future__ import annotations

import base64

import pytest

from services.cover_style_edit import (
    ROUTE_IMAGE_API,
    _extract,
    edit_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"test-image-bytes"
B64 = base64.b64encode(PNG).decode("ascii")


class _Resp:
    def __init__(self, *, status=200, content=b"", headers=None, body=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def test_extract_binary_image_by_content_type():
    resp = _Resp(content=PNG, headers={"content-type": "image/png"})
    data, reason = _extract(resp)
    assert reason == "ok"
    assert data == PNG


def test_extract_binary_image_by_magic_without_content_type():
    resp = _Resp(content=PNG, headers={"content-type": "application/octet-stream"})
    data, reason = _extract(resp)
    assert reason == "ok"
    assert data == PNG


def test_extract_openai_b64_json():
    resp = _Resp(body={"data": [{"b64_json": B64}]})
    data, reason = _extract(resp)
    assert reason == "ok"
    assert data == PNG


def test_extract_url_json():
    resp = _Resp(body={"data": [{"url": "https://cdn.example/a.png"}]})
    data, reason = _extract(resp)
    assert data is None
    assert reason == "url"


def test_extract_alternate_output_envelope():
    resp = _Resp(body={"output": [{"image": "https://cdn.example/a.png"}]})
    data, reason = _extract(resp)
    assert data is None
    assert reason == "url"


def test_extract_images_list_envelope():
    resp = _Resp(body={"images": ["https://cdn.example/a.png"]})
    data, reason = _extract(resp)
    assert data is None
    assert reason == "url"


def test_extract_empty_data_is_bad_json():
    resp = _Resp(body={"data": []})
    data, reason = _extract(resp)
    assert data is None
    assert reason == "bad_json"


@pytest.mark.asyncio
async def test_edit_image_accepts_binary_2xx(tmp_path):
    base = tmp_path / "base.png"
    base.write_bytes(PNG)

    async def transport(url, payload, headers, timeout):
        return _Resp(content=PNG, headers={"content-type": "image/png"})

    result = await edit_image(
        "edit prompt", base_image_path=str(base), reference_paths=None,
        base_url="https://provider.example", model="qwen-image-3-pro",
        route=ROUTE_IMAGE_API, transport=transport,
    )
    assert result.ok is True
    assert result.content == PNG


@pytest.mark.asyncio
async def test_edit_image_bad_json_keeps_safe_diagnostics(tmp_path):
    base = tmp_path / "base.png"
    base.write_bytes(PNG)

    async def transport(url, payload, headers, timeout):
        return _Resp(body={"data": []}, headers={"content-type": "application/json"})

    result = await edit_image(
        "edit prompt", base_image_path=str(base), reference_paths=None,
        base_url="https://provider.example", model="qwen-image-3-pro",
        route=ROUTE_IMAGE_API, transport=transport,
    )
    assert result.ok is False
    assert result.reason == "bad_json"
    diag = result.meta.get("response_diag") or {}
    assert diag.get("status") == 200
    assert diag.get("content_type") == "application/json"
    assert diag.get("json_keys") == ["data"]
    assert "test-image-bytes" not in str(diag)
