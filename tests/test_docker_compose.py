"""Tests for Epic 72 (Section 74.A/D271) + hotfix v2.47.2: cobalt через прокси.

Строковые ассерты по docker-compose.yml/.env.example (парсинг yaml не нужен —
контракт фиксирован каноном Section 74 + hotfix): env HTTP(S)_PROXY из
COBALT_HTTP_PROXY, NO_PROXY для healthcheck, network_mode host (xray слушает
только 127.0.0.1 на хосте), БЕЗ ports/extra_hosts у cobalt; секрет только в
прод .env.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _compose_text() -> str:
    return (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def _cobalt_block() -> str:
    """Текст сервиса cobalt до конца файла (он последний в compose)."""
    text = _compose_text()
    start = text.index("  cobalt:")
    return text[start:]


class TestCobaltProxyEnv:
    def test_http_and_https_proxy_from_cobalt_env(self):
        text = _compose_text()
        assert 'HTTP_PROXY: "${COBALT_HTTP_PROXY:-}"' in text
        assert 'HTTPS_PROXY: "${COBALT_HTTP_PROXY:-}"' in text

    def test_no_proxy_excludes_local_healthcheck(self):
        text = _compose_text()
        assert 'NO_PROXY: "localhost,127.0.0.1"' in text


class TestCobaltHostNetwork:
    """Hotfix v2.47.2: xray слушает только 127.0.0.1:10808 на хосте — cobalt
    переводится в host network; bridge-gateway 172.17.0.1 давал PORT_CLOSED."""

    def test_network_mode_host(self):
        block = _cobalt_block()
        assert 'network_mode: "host"' in block

    def test_cobalt_has_no_ports_publishing(self):
        # с host-сетью публикация портов невозможна; API_PORT=9000 слушает на хосте
        block = _cobalt_block()
        assert "ports:" not in block
        assert '9000:9000' not in block

    def test_cobalt_has_no_extra_hosts(self):
        block = _cobalt_block()
        assert "extra_hosts:" not in block
        assert "host.docker.internal" not in block

    def test_api_listen_address_active_loopback(self):
        # митигация host-сети ПРИМЕНЕНА: bind строго на loopback —
        # 9000 недоступен с внешних интерфейсов хоста
        block = _cobalt_block()
        assert 'API_LISTEN_ADDRESS: "127.0.0.1"' in block

    def test_telegram_bot_api_untouched(self):
        text = _compose_text()
        assert 'image: aiogram/telegram-bot-api:latest' in text
        assert '- "127.0.0.1:8081:8081"' in text


class TestEnvExample:
    def test_cobalt_proxy_placeholder_documented(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "COBALT_HTTP_PROXY=" in text
        assert "Epic 72" in text or "Section 74.A" in text

    def test_proxy_host_is_loopback_again(self):
        # hotfix v2.47.2: cobalt в host-сети → хост прокси снова 127.0.0.1
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        assert "http://user:pass@127.0.0.1:10808" in text
        assert "host.docker.internal" not in text

    def test_no_secret_in_compose(self):
        """R17/D148: креды прокси НЕ в git — compose несёт только плейсхолдер
        из прод .env; формат-пример живёт в .env.example (комментарий)."""
        text = _compose_text()
        assert re.search(r"https?://\S+@", text) is None
