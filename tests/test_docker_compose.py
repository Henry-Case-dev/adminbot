"""Tests for Epic 72 (Section 74.A/D271): docker-compose cobalt через прокси.

Строковые ассерты по docker-compose.yml/.env.example (парсинг yaml не нужен —
контракт фиксирован каноном Section 74): env HTTP(S)_PROXY из COBALT_HTTP_PROXY,
NO_PROXY для healthcheck, extra_hosts host-gateway; секрет только в прод .env.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _compose_text() -> str:
    return (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


class TestCobaltProxyEnv:
    def test_http_and_https_proxy_from_cobalt_env(self):
        text = _compose_text()
        assert 'HTTP_PROXY: "${COBALT_HTTP_PROXY:-}"' in text
        assert 'HTTPS_PROXY: "${COBALT_HTTP_PROXY:-}"' in text

    def test_no_proxy_excludes_local_healthcheck(self):
        text = _compose_text()
        assert 'NO_PROXY: "localhost,127.0.0.1"' in text

    def test_extra_hosts_host_gateway(self):
        text = _compose_text()
        assert "extra_hosts:" in text
        assert '"host.docker.internal:host-gateway"' in text


class TestEnvExample:
    def test_cobalt_proxy_placeholder_documented(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "COBALT_HTTP_PROXY=" in text
        assert "Epic 72" in text or "Section 74.A" in text

    def test_no_secret_in_compose(self):
        """R17/D148: креды прокси НЕ в git — compose несёт только плейсхолдер
        из прод .env; формат-пример живёт в .env.example (комментарий)."""
        import re
        text = _compose_text()
        assert re.search(r"https?://\S+@", text) is None
