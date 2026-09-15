"""F1/T-1779 (ADR-1019-1 D6, AMEND ADR-1018-1 D8) — тесты probe-скрипта.

Матрикс проверяет КОНТРАКТ запроса: {US, EU} × {path-token, Bearer};
ожидание — 202 только на (US × Bearer). Сеть НЕ трогаем: probe() вызывается
через мок urllib; main(--dry-run) тоже без сети. Проверяем R17-маскирование
(полный токен/URL в вывод не попадают).
"""
import importlib.util
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_probe():
    path = os.path.join(_ROOT, "scripts", "betterstack_host_token_probe.py")
    spec = importlib.util.spec_from_file_location("bs_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe_mod():
    return _load_probe()


def test_mask_hides_full_value(probe_mod):
    assert probe_mod.mask("ABCDEFGH") == "********"
    assert probe_mod.mask("ABCDEFGH", keep=4) == "ABCD****"
    assert probe_mod.mask("") == "<empty>"
    assert probe_mod.mask(None) == "<empty>"


def test_build_matrix_four_combos(probe_mod):
    token = "T" * 32
    rows = probe_mod.build_matrix("us.example.test", token)
    assert len(rows) == 4
    labels = [r["label"] for r in rows]
    assert labels == ["US × path-token", "US × Bearer",
                      "EU × path-token", "EU × Bearer"]
    assert rows[0]["mode"] == probe_mod.PATH_TOKEN
    assert rows[1]["mode"] == probe_mod.BEARER
    assert rows[0]["token"] == token
    assert rows[3]["host"] == probe_mod.EU_HOST


def test_format_row_masks_secrets(probe_mod):
    row = {"label": "US × Bearer", "host": "us-west-2a.example.test",
           "token": "SECRETTOKEN_VALUE_1234567890", "mode": "bearer"}
    line = probe_mod.format_row(row, 202)
    assert "http=202" in line
    assert "SECRETTOKEN_VALUE_1234567890" not in line
    assert "us-west-2a.example.test" not in line     # хост тоже маскирован
    assert line.startswith("US × Bearer")


def test_main_dry_run_no_network(probe_mod, monkeypatch, capsys):
    monkeypatch.setenv("BETTERSTACK_HOST", "us.example.test")
    monkeypatch.setenv("LOGTAIL_SOURCE_TOKEN", "S" * 32)
    monkeypatch.setattr(sys, "argv", ["probe", "--dry-run"])
    assert probe_mod.main() == 0
    out = capsys.readouterr().out
    assert out.count("http=-3") == 4                 # dry-run, без сети
    assert "S" * 32 not in out


def test_probe_bearer_uses_host_and_auth_header(probe_mod, monkeypatch):
    calls = []

    class _Resp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(request)
        return _Resp()

    monkeypatch.setattr(probe_mod, "_urlopen", fake_urlopen)
    assert probe_mod.probe("us.example.test", "tok", probe_mod.BEARER) == 202
    req = calls[0]
    assert req.full_url == "https://us.example.test"       # токена в path нет
    headers = {k.lower(): v for k, v in req.headers.items()}
    assert headers["authorization"] == "Bearer tok"


def test_probe_path_mode_keeps_token_in_url(probe_mod, monkeypatch):
    calls = []

    class _Resp:
        status = 401

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(request)
        return _Resp()

    monkeypatch.setattr(probe_mod, "_urlopen", fake_urlopen)
    assert probe_mod.probe("us.example.test", "tok", probe_mod.PATH_TOKEN) == 401
    assert calls[0].full_url == "https://us.example.test/tok"


def test_probe_opener_does_not_follow_redirects(probe_mod):
    """D-09 (ревью Батча A): 3xx не фоллоуится — Bearer не уходит на чужой
    Location. Проверяем сам redirect-handler (без сети)."""
    handler = probe_mod._NoRedirectHandler()
    assert handler.redirect_request(
        None, None, 302, "Found", {}, "https://evil.example") is None
