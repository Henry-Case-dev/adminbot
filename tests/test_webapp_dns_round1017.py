"""F1 10.17 (miniapp-mobile-dns-round1017, ADR-1017-1) — регресс-гейт DNS.

Android: `net::ERR_NAME_NOT_RESOLVED` (сбой резолва ТОП-домена у клиента,
вне репо). В репо — детерминированные диагностические роуты и regression-
гейты (spec §3, §6):

  * `HEAD /web/` + `/web/index.html` → 200 (+ CSP, no-store) — отличить
    маршрутизацию от сбоя DNS;
  * unauth `GET`/`HEAD /healthz` → 200, `{"status":"ok","version":...}`,
    `no-store` — точка для `curl -I` из мобильной сети (@DevOps);
  * стартовый лог host/scheme/path — host-only (R17, без полного URL);
  * статический скан `web/**` — внешних CDN нет (ADR-1016-2 в силе);
  * absolute-URL настроек консистентны (scheme https, host непуст, /web/).
"""
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from config.settings import APP_VERSION, settings
from web.app import _CSP_HTML, create_app

ROOT = Path(".")

# Внешние хосты-«маркеры» CDN (прецедент test_smoke_round1016_miniapp_selfhost).
EXTERNAL_HOSTS = (
    "cdn.tailwindcss.com", "unpkg.com", "cdn.jsdelivr.net",
    "fonts.googleapis.com", "fonts.gstatic.com", "telegram.org/js",
)

SCANNED = (
    "web/index.html",
    "web/app.js",
    "web/static/app.css",
    "web/static/telegram-init.js",
)

# L2 (ревью-итер.1): self-host vendor — тоже сканируется на CDN-баннеры.
VENDOR_SCANNED = (
    "web/static/vendor/chart.umd.min.js",
    "web/static/vendor/dompurify-3.4.15.min.js",
    "web/static/vendor/tailwind.css",
    "web/static/vendor/telegram-web-app.js",
    "web/static/vendor/vue.global.prod.min.js",
    "web/static/vendor/vis-network/vis-network.min.js",
)


class _StubCache:
    """Минимальный ConfigCache-стаб: create_app без PG (spec §6)."""

    def __init__(self):
        self.is_initialized = True
        self.pg_available = False

    async def init(self):  # pragma: no cover - вызывается только если не init
        self.is_initialized = True


@pytest.fixture
def client():
    app = create_app(_StubCache())
    with TestClient(app) as test_client:
        yield test_client


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


class TestHeadAndHealthz:
    def test_head_web_index(self, client):
        resp = client.head("/web/")
        assert resp.status_code == 200
        assert resp.headers["Content-Security-Policy"] == _CSP_HTML
        assert "no-store" in resp.headers["Cache-Control"]

    def test_head_web_index_html(self, client):
        resp = client.head("/web/index.html")
        assert resp.status_code == 200
        assert resp.headers["Content-Security-Policy"] == _CSP_HTML
        assert "no-store" in resp.headers["Cache-Control"]

    def test_healthz_get(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok", "version": APP_VERSION}
        assert resp.headers["Cache-Control"] == "no-store"

    def test_healthz_head(self, client):
        resp = client.head("/healthz")
        assert resp.status_code == 200
        assert resp.headers["Cache-Control"] == "no-store"

    def test_healthz_head_matches_get_headers(self, client):
        """L4 (ревью-итер.1): HEAD повторяет заголовки GET (в т.ч. content-type)."""
        get_resp = client.get("/healthz")
        head_resp = client.head("/healthz")
        assert head_resp.status_code == 200
        assert (head_resp.headers.get("content-type")
                == get_resp.headers.get("content-type"))

    def test_healthz_unauth(self, client):
        """Точка доступна БЕЗ Telegram initData (баг наступает до auth)."""
        assert client.get("/healthz").status_code == 200
        assert client.head("/healthz").status_code == 200


class TestNoExternalCdn:
    @pytest.mark.parametrize("rel", SCANNED)
    def test_no_external_hosts(self, rel):
        text = _read(rel)
        for host in EXTERNAL_HOSTS:
            assert host not in text, "%s: внешний CDN %s" % (rel, host)
        assert not re.search(r"https?://cdn\.", text), rel

    def test_index_has_no_absolute_external_url(self):
        text = _read("web/index.html")
        assert "https://" not in text
        assert "http://" not in text

    @pytest.mark.parametrize("rel", VENDOR_SCANNED)
    def test_no_external_hosts_in_vendor(self, rel):
        """L2 (ревью-итер.1): vendor-бандлы self-host — без внешних CDN."""
        text = _read(rel)
        for host in EXTERNAL_HOSTS:
            assert host not in text, "%s: внешний CDN %s" % (rel, host)
        assert not re.search(r"https?://cdn\.", text), rel


class TestAbsoluteUrlConsistency:
    def test_webapp_url(self):
        parts = urlsplit(settings.WEBAPP_URL)
        assert parts.scheme == "https"
        assert parts.hostname
        assert parts.path == "/web/"

    def test_media_public_base_url(self):
        parts = urlsplit(settings.MEDIA_PUBLIC_BASE_URL)
        assert parts.scheme == "https"
        assert parts.hostname

    def test_hosts_consistent(self):
        assert (urlsplit(settings.WEBAPP_URL).hostname
                == urlsplit(settings.MEDIA_PUBLIC_BASE_URL).hostname)


class TestStartupDiag:
    def test_logs_host_only(self, caplog):
        caplog.set_level(logging.INFO, logger="web.app")
        create_app(_StubCache())
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "[webapp] WEBAPP_URL" in text
        assert "[webapp] MEDIA_PUBLIC_BASE_URL" in text
        assert "scheme=https" in text
        assert "path=/web/" in text
        assert "host=%s" % urlsplit(settings.WEBAPP_URL).hostname in text
        # R17: полный URL/секреты в лог НЕ попадают.
        full = settings.WEBAPP_URL.strip()
        assert full not in text
        assert full.rstrip("/") not in text
