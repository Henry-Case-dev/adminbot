"""F1/T-1704 (ADR-1018-1 D8) — тесты диагностического probe-скрипта.

Сеть НЕ трогаем: probe() вызывается через мок urllib; main(--dry-run) тоже
без сети. Проверяем R17-маскирование (полный токен/DSN в вывод не попадают).
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
    dsn = f"https://{'P' * 20}@o1.ingest.sentry.io/2"
    rows = probe_mod.build_matrix("us.example.test", token, dsn)
    assert len(rows) == 4
    kinds = [r["label"] for r in rows]
    assert kinds == ["US × Source Token", "US × Sentry public key",
                     "EU × Source Token", "EU × Sentry public key"]
    assert rows[1]["token"] == "P" * 20
    assert rows[3]["host"] == probe_mod.EU_HOST


def test_format_row_masks_secrets(probe_mod):
    row = {"label": "US × Source Token", "host": "us-west-2a.example.test",
           "token": "SECRETTOKEN_VALUE_1234567890"}
    line = probe_mod.format_row(row, 401)
    assert "http=401" in line
    assert "SECRETTOKEN_VALUE_1234567890" not in line
    assert "us-west-2a.example.test" not in line     # хост тоже маскирован
    assert line.startswith("US × Source Token")


def test_main_dry_run_no_network(probe_mod, monkeypatch, capsys):
    monkeypatch.setenv("BETTERSTACK_HOST", "us.example.test")
    monkeypatch.setenv("LOGTAIL_SOURCE_TOKEN", "S" * 32)
    monkeypatch.setenv("SENTRY_DSN", f"https://{'P' * 20}@o1.ingest.sentry.io/2")
    monkeypatch.setattr(sys, "argv", ["probe", "--dry-run"])
    assert probe_mod.main() == 0
    out = capsys.readouterr().out
    assert out.count("http=-3") == 4                 # dry-run, без сети
    assert "S" * 32 not in out
    assert "P" * 20 not in out


def test_probe_uses_mock_urlopen(probe_mod, monkeypatch):
    calls = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert probe_mod.probe("https://us.example.test/tok") == 200
    assert calls == ["https://us.example.test/tok"]
