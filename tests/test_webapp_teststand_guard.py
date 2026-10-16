"""SOUL-13.2 / v6.3 §14 (REV-W2-N3, CORR-1): тестовый стенд Liquid Glass
(`glass-teststand.html`) не должен быть публично достижим в проде.

Контракт:
  * анонимный GET страницы/её ассетов → 401/403/404: страница вынесена из
    публично смонтированных деревьев `/web` → `web/` и `/static` →
    `web/static/` (web/app.py:338,344-347, без auth). Повторное появление
    `glass-teststand.*` в `web/` снова валит эти проверки;
  * положительная проверка разрешённой test-среды: fixture живёт в
    `tests/glass-teststand/` и самодостаточен (локальные ссылки резолвятся;
    боевые ассеты подключаются относительными путями `../../web/static/...`,
    а не серверными монтами `/static/` — в тест-среде приложения нет);
  * боевые ассеты контура (glass-probe.js, glass.js, lg-lens-map.png) и
    прод-навигация (`/web/`) не затронуты.

TEST-LIFECYCLE: CONTRACT owner=SOUL-13.2; REGRESSION owner=REV-W2-N3
(анонимный 200 на /static/glass-teststand.html до фикса 2026-10-16)
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
_TESTSTAND_DIR = ROOT / "tests" / "glass-teststand"

# Публично смонтированные (без auth) пути — оба монета одного дерева:
# /web → web/ и /static → web/static.
_ANON_PATHS = (
    "/static/glass-teststand.html",
    "/static/glass-teststand.css",
    "/static/glass-teststand.js",
    "/web/static/glass-teststand.html",
    "/web/static/glass-teststand.css",
    "/web/static/glass-teststand.js",
    "/web/glass-teststand.html",
)


class _StubCache:
    """Минимальный ConfigCache-стаб: create_app без PG (spec §6)."""

    def __init__(self):
        self.is_initialized = True
        self.pg_available = False

    async def init(self):
        self.is_initialized = True


@pytest.fixture
def client():
    with TestClient(create_app(_StubCache())) as test_client:
        yield test_client


def test_anonymous_access_to_stand_denied(client):
    for path in _ANON_PATHS:
        resp = client.get(path)
        assert resp.status_code in (401, 403, 404), (path, resp.status_code)
        assert resp.status_code != 200, path


def test_production_assets_still_served(client):
    # Санити: гард не ломает боевые ассеты того же контура.
    for path in ("/static/glass-probe.js", "/static/glass.js",
                 "/static/vendor/lg-lens-map.png", "/web/"):
        assert client.get(path).status_code == 200, path


def test_stand_absent_from_public_static_tree():
    # Любой glass-teststand.* под web/ был бы отдан анонимно монтами
    # /web и /static — в дереве его быть не должно.
    hits = [str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / "web").rglob("*glass-teststand*")]
    assert hits == []


def test_prod_ui_does_not_reference_stand():
    for rel in ("web/index.html", "web/app.js", "web/static/app.css"):
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        assert "glass-teststand" not in text, rel


def test_test_env_fixture_is_self_contained():
    html = _TESTSTAND_DIR / "glass-teststand.html"
    assert html.exists()
    assert (_TESTSTAND_DIR / "glass-teststand.css").exists()
    assert (_TESTSTAND_DIR / "glass-teststand.js").exists()
    text = html.read_text(encoding="utf-8")
    # Никаких абсолютных серверных монтов (/static/ в тест-среде не отдаётся).
    assert not re.search(r'(?:href|src)="/static/', text)
    refs = re.findall(r'(?:href|src)="([^"]+)"', text)
    local = [r for r in refs
             if not r.startswith(("data:", "http:", "https:", "#"))]
    assert local, "стенд должен ссылаться на свои ассеты"
    for ref in local:
        target = (_TESTSTAND_DIR / ref.split("?", 1)[0]).resolve()
        assert target.exists(), ref
    # Боевые ассеты подключаются ровно относительными путями на web/static.
    for ref in local:
        if ref.startswith("../"):
            assert ref.startswith("../../web/static/"), ref
