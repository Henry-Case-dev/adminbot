"""F6 `help-guide-integration-round1014` — гайд в БД + Markdown-редактор.

Покрытие (spec §2/§5/§6):
  * каталог-инвариант: +1 PG-only ключ content.intelligence_guide
    (REGISTRY 436 / categorized 411; +1 env-only BETTERSTACK_HOST
    (ADR-1018-1 D3); Settings/GROUPS/mapped/TAB_RULES = const);
  * идемпотентный сид: ключа нет → из файла; ключ есть (в т.ч. правленый) → НЕ
    перезатирается;
  * InfoService.get_guide() — fail-open (PG down → код-канон/пусто);
    save_guide() — единственная точка записи;
  * GET/POST /api/info/guide: 200 / 403 / 422 / 503;
  * фронтенд: второй блок «Справки», Markdown-редактор, sanitize (DOMPurify
    self-host), никаких v-html без санитайза; JS-юниты в routing_test.js;
  * стиль гайда: запрещённый жаргон отсутствует (grep = 0).
"""
import asyncio
import dataclasses
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.app import create_app
from web.api import deps as deps_mod

ROOT = Path(".")
DOCS = ROOT / "plans" / "docs" / "intelligence_user_guide.md"
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_ID = 999999999

GUIDE_KEY = "content.intelligence_guide"
SEED_MARKDOWN = "# Гайд из сид-файла\n\nПривет.\n"
DB_MARKDOWN = "# Гайд из БД\n\nРучная правка.\n"


# ── helpers (мини-копия фейков test_config_cache/test_webapp_api) ──────────

class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self.queries = []
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return None

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


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

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


def _rows(guide_value=None):
    settings = [
        {"key": "limits.search_max_symbols", "value": 8000,
         "category": "limits", "updated_at": None},
        {"key": "content.info_how_it_works",
         "value": {"html": "<h1>Как это работает</h1>",
                   "updated_at": "2026-08-30T00:00:00+00:00",
                   "updated_by": ADMIN_ID},
         "category": "content", "updated_at": None},
    ]
    if guide_value is not None:
        settings.append({
            "key": GUIDE_KEY, "value": guide_value, "category": "content",
            "updated_at": None})
    roles = [
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False},
        {"role_name": "moderator", "permissions": {}, "is_custom": False},
        {"role_name": "user", "permissions": {}, "is_custom": False},
    ]
    admins = [
        {"telegram_id": ADMIN_ID, "role_name": "admin",
         "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
        {"telegram_id": MODERATOR_ID, "role_name": "moderator",
         "added_by": ADMIN_ID, "created_at": "2026-08-30T00:00:01+00:00"},
    ]
    return settings, roles, admins


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from services import hot_config as hot

    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(
            INFO_TEXT_FILE=str(tmp_path / "info_text.md"),
            ADMIN_USER_ID=ADMIN_ID))
    guide_value = {"markdown": DB_MARKDOWN,
                   "guide_version": 2,
                   "guide_delivered_version": 2,
                   "updated_at": "2026-09-13T00:00:00+00:00",
                   "updated_by": ADMIN_ID}
    conn = _FakeConn(*_rows(guide_value))
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    old_hot = hot.get_config_cache()
    with TestClient(app) as test_client:
        hot.set_config_cache(cache)          # реальный путь: hot → ConfigCache
        test_client.cache = cache
        yield test_client
    hot.set_config_cache(old_hot)


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


# ═══ каталог-Δ ═══════════════════════════════════════════════════════════════

class TestCatalogDelta:
    def test_counts(self):
        from services import param_catalog as pc
        from config.settings import Settings
        # 10.19 (F3/ADR-1019-3 D3, санкция UPD3 п.5): каталог-Δ →
        # +1 REGISTRY/Settings/categorized (IMPORT_HISTORY_RETENTION_DAYS),
        # +2 GROUPS (limits_chat_key/limits_chat_context), +2 mapped,
        # +1 TAB_RULES/TAB_NAV (mod_budgets): 437/92/407/412/90/20.
        # 10.23 (F5/ADR-1023-5 D5): +5 REGISTRY/Settings/categorized,
        # +3 GROUPS/mapped → 446/95/93/20/416/421.
        assert len(pc.REGISTRY) == 458
        assert len(pc.GROUPS) == 97
        assert len(pc._TAB_BY_GROUP) == 95
        assert len(pc.TAB_RULES) == 20
        assert len({f.name for f in dataclasses.fields(Settings)}) == 417
        categorized = [s for s in pc.REGISTRY.values()
                       if s.category is not None]
        assert len(categorized) == 433

    def test_guide_spec(self):
        from services import param_catalog as pc
        spec = pc.REGISTRY[GUIDE_KEY]
        assert spec.pg_key == GUIDE_KEY
        assert spec.category == "content"
        assert spec.type == "json"
        assert spec.group == "content_info"
        assert spec.description
        assert spec.title_ru


# ═══ идемпотентный сид ═══════════════════════════════════════════════════════

class TestGuideSeed:
    @pytest.mark.asyncio
    async def test_seed_from_file_when_missing(self, tmp_path, monkeypatch):
        seed = tmp_path / "guide.md"
        seed.write_text(SEED_MARKDOWN, encoding="utf-8")
        monkeypatch.setattr("services.config_cache._GUIDE_SEED_FILE", str(seed))
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID))
        cache = ConfigCache(pg=_FakePg(_FakeConn(*_rows())),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        value = cache.get(GUIDE_KEY)
        assert isinstance(value, dict)
        assert value["markdown"] == SEED_MARKDOWN
        assert value["updated_by"] == ADMIN_ID
        assert value["updated_at"]

    @pytest.mark.asyncio
    async def test_existing_value_not_overwritten(self, tmp_path, monkeypatch):
        seed = tmp_path / "guide.md"
        seed.write_text(SEED_MARKDOWN, encoding="utf-8")
        monkeypatch.setattr("services.config_cache._GUIDE_SEED_FILE", str(seed))
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID))
        # F9 10.23 (ADR-1023-9): значение уже доставлено и правилось вручную —
        # маркер guide_delivered_version защищает его от перезаписи миграцией.
        value_in_db = {"markdown": "# Правка админа",
                       "guide_version": 2, "guide_delivered_version": 2,
                       "updated_at": "t", "updated_by": 7}
        cache = ConfigCache(pg=_FakePg(_FakeConn(*_rows(value_in_db))),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        assert cache.get(GUIDE_KEY)["markdown"] == "# Правка админа"

    @pytest.mark.asyncio
    async def test_seed_skipped_on_file_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("services.config_cache._GUIDE_SEED_FILE",
                            str(tmp_path / "nope.md"))
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID))
        cache = ConfigCache(pg=_FakePg(_FakeConn(*_rows())),
                            retry_attempts=1, retry_delay=0)
        await cache.init()
        assert cache.get(GUIDE_KEY) is None


# ═══ InfoService ═════════════════════════════════════════════════════════════

class TestInfoServiceGuide:
    def test_get_guide_from_cache(self, monkeypatch):
        from services import hot_config as hot
        from services.info_service import InfoService

        monkeypatch.setattr(hot, "get", lambda key, default=None: {
            "markdown": DB_MARKDOWN,
            "updated_at": "t", "updated_by": 5,
        })
        guide = InfoService().get_guide()
        assert guide["markdown"] == DB_MARKDOWN
        assert guide["updated_by"] == 5

    def test_get_guide_fail_open_to_seed_file(self, tmp_path, monkeypatch):
        from services import hot_config as hot
        from services import info_service
        from services.info_service import InfoService

        seed = tmp_path / "guide.md"
        seed.write_text(SEED_MARKDOWN, encoding="utf-8")
        monkeypatch.setattr(hot, "get", lambda key, default=None: None)
        monkeypatch.setattr(info_service, "GUIDE_SEED_FILE", str(seed))
        guide = InfoService().get_guide()
        assert guide["markdown"] == SEED_MARKDOWN
        assert guide["updated_at"] is None

    def test_get_guide_fail_open_empty(self, tmp_path, monkeypatch):
        from services import hot_config as hot
        from services import info_service
        from services.info_service import InfoService

        monkeypatch.setattr(hot, "get", lambda key, default=None: None)
        monkeypatch.setattr(info_service, "GUIDE_SEED_FILE",
                            str(tmp_path / "missing.md"))
        guide = InfoService().get_guide()
        assert guide["markdown"] == ""

    def test_guide_seed_file_is_absolute(self):
        """M2: путь сид-файла не зависит от CWD (systemd/docker)."""
        from services import info_service
        assert Path(info_service.GUIDE_SEED_FILE).is_absolute()

    def test_get_guide_seed_independent_of_cwd(self, tmp_path, monkeypatch):
        """M2: при не-корневом CWD гайд всё равно наполняется сидом."""
        from services import hot_config as hot
        from services.info_service import InfoService

        monkeypatch.setattr(hot, "get", lambda key, default=None: None)
        monkeypatch.chdir(tmp_path)              # CWD ≠ корень проекта
        guide = InfoService().get_guide()
        assert guide["markdown"].strip(), \
            "M2: сид гайда должен читаться независимо от CWD"

    @pytest.mark.asyncio
    async def test_save_guide_single_write_point(self, monkeypatch):
        from services import hot_config as hot
        from services.info_service import InfoService

        calls = []

        class _Cache:
            pg_available = True

            async def set(self, key, value, category):
                calls.append((key, value, category))

        old = hot.get_config_cache()
        hot.set_config_cache(_Cache())
        try:
            value = await InfoService().save_guide(DB_MARKDOWN, updated_by=42)
        finally:
            hot.set_config_cache(old)
        assert calls and calls[0][0] == GUIDE_KEY
        assert calls[0][1]["markdown"] == DB_MARKDOWN
        assert calls[0][1]["updated_by"] == 42
        assert calls[0][2] == "content"
        assert value["markdown"] == DB_MARKDOWN

    @pytest.mark.asyncio
    async def test_save_guide_without_pg_raises(self, monkeypatch):
        from services import hot_config as hot
        from services.config_cache import ConfigCacheUnavailableError
        from services.info_service import InfoService

        class _Cache:
            pg_available = False

            async def set(self, *a, **k):
                raise AssertionError("set не должен вызываться")

        old = hot.get_config_cache()
        hot.set_config_cache(_Cache())
        try:
            with pytest.raises(ConfigCacheUnavailableError):
                await InfoService().save_guide("x")
        finally:
            hot.set_config_cache(old)


# ═══ API ═════════════════════════════════════════════════════════════════════

class TestGuideApi:
    def test_get_requires_tma_auth(self, client):
        assert client.get("/api/info/guide").status_code == 401

    def test_get_public_any_role(self, client):
        for uid in (ADMIN_ID, MODERATOR_ID, USER_ID):
            resp = client.get("/api/info/guide", headers=_hdr(uid))
            assert resp.status_code == 200, uid
            body = resp.json()
            assert body["key"] == GUIDE_KEY
            assert body["markdown"] == DB_MARKDOWN
            assert body["updated_by"] == ADMIN_ID

    def test_get_fail_open_when_key_missing(self, client):
        client.cache._settings.pop(GUIDE_KEY, None)
        resp = client.get("/api/info/guide", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        # код-канон из сид-файла (не пусто)
        assert "#" in resp.json()["markdown"]

    def test_post_admin_ok_persists(self, client):
        resp = client.post("/api/info/guide",
                           json={"markdown": "# Новый гайд"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["updated_by"] == ADMIN_ID
        assert client.cache.get(GUIDE_KEY)["markdown"] == "# Новый гайд"
        again = client.get("/api/info/guide", headers=_hdr(ADMIN_ID))
        assert again.json()["markdown"] == "# Новый гайд"

    def test_post_non_admin_403(self, client):
        resp = client.post("/api/info/guide",
                           json={"markdown": "# x"},
                           headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_post_empty_422(self, client):
        resp = client.post("/api/info/guide",
                           json={"markdown": "   "},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_post_too_large_422(self, client):
        resp = client.post("/api/info/guide",
                           json={"markdown": "a" * 65537},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_post_pg_down_503(self, client):
        client.cache._pg_available = False
        resp = client.post("/api/info/guide",
                           json={"markdown": "# x"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 503

    def test_reset_admin_ok_returns_canon_and_backup(self, client):
        # F9 10.23 (ADR-1023-9 Decision 6): откат гайда к код-канону из сид-файла.
        resp = client.post("/api/info/guide/reset", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["guide_version"] == 2
        # reset-ответ (RBAC edit_info) содержит бэкап прежней правки.
        assert resp.json()["prev_markdown"] == DB_MARKDOWN
        again = client.get("/api/info/guide", headers=_hdr(ADMIN_ID))
        body = again.json()
        # markdown == код-канон (сид-файл).
        assert "## 11. Как бот думает (System 2)" in body["markdown"]
        # публичный GET бэкап НЕ отдаёт (least privilege, review iter2).
        assert "prev_markdown" not in body
        # бэкап доступен отдельным роутом под edit_info.
        backup = client.get("/api/info/guide/backup", headers=_hdr(ADMIN_ID))
        assert backup.status_code == 200
        assert backup.json()["prev_markdown"] == DB_MARKDOWN

    def test_guide_backup_requires_edit_info(self, client):
        assert client.get("/api/info/guide/backup").status_code == 401
        resp = client.get("/api/info/guide/backup", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_public_guide_has_no_backup_fields(self, client):
        body = client.get("/api/info/guide", headers=_hdr(USER_ID)).json()
        assert "prev_markdown" not in body
        assert "prev_updated_at" not in body

    def test_reset_non_admin_403(self, client):
        resp = client.post("/api/info/guide/reset", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_reset_pg_down_503(self, client):
        client.cache._pg_available = False
        resp = client.post("/api/info/guide/reset", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 503


# ═══ фронтенд-маркеры ════════════════════════════════════════════════════════

class TestFrontend:
    def test_second_block_under_first(self):
        block = _block(HTML, "activeTab === 'info'", "</main>")
        # ровно два блока-карточки: «Справка» + «Гайд по возможностям»
        assert block.count('class="card p-5') >= 2
        assert "Гайд по возможностям" in block
        assert block.index("Гайд по возможностям") > block.index("Справка")

    def test_markdown_editor_markup(self):
        block = _block(HTML, "activeTab === 'info'", "</main>")
        assert "guideDraft" in block
        assert 'v-model="guideDraft"' in block
        assert "saveGuide()" in block
        assert "toggleGuideEditor()" in block
        assert "Предпросмотр" in block
        assert "65536" in block

    def test_no_unsanitized_v_html(self):
        block = _block(HTML, "activeTab === 'info'", "</main>")
        # все v-html идут через санитайз (sanitizeHtml / sanitized*)
        assert 'v-html="sanitizedInfoHtml"' in block
        assert 'v-html="sanitizedGuideHtml"' in block
        assert 'v-html="sanitizedGuidePreviewHtml"' in block
        for bad in ('v-html="guideHtml"', 'v-html="guideDraft"',
                    'v-html="infoDraft"'):
            assert bad not in block, bad

    def test_dompurify_self_hosted_pinned(self):
        assert "/static/vendor/dompurify-3.4.15.min.js" in HTML
        assert "dompurify@3/dist" not in HTML
        assert (ROOT / "web" / "static" / "vendor"
                / "dompurify-3.4.15.min.js").exists()

    def test_js_methods_and_computed(self):
        for marker in ("loadGuide: async function",
                       "saveGuide: async function",
                       "toggleGuideEditor: function",
                       "renderGuideMarkdown: function"):
            assert marker in JS, marker
        for marker in ("sanitizedGuideHtml: function",
                       "sanitizedGuidePreviewHtml: function"):
            assert marker in JS, marker

    def test_generated_html_is_sanitized(self):
        # computed рендера гайда обязательно оборачивают в sanitizeHtml
        block = _block(JS, "sanitizedGuideHtml: function",
                       "confirmText: function")
        assert "this.sanitizeHtml(this.renderGuideMarkdown(this.guideHtml))" \
            in block
        assert "this.sanitizeHtml(this.renderGuideMarkdown(this.guideDraft))" \
            in block

    def test_set_tab_loads_guide(self):
        block = _block(JS, "if (id === 'info')", "id === 'persona'")
        assert "this.loadInfo()" in block
        assert "this.loadGuide()" in block

    def test_guide_markdown_escapes_first(self):
        block = _block(JS, "renderGuideMarkdown: function",
                       "saveGuide: async function")
        assert "&amp;" in block and "&lt;" in block and "&gt;" in block


# ═══ JS-юниты (routing_test.js) ══════════════════════════════════════════════

class TestJsUnit:
    def test_routing_test_covers_guide(self):
        test = (ROOT / "tests" / "js" / "routing_test.js").read_text(
            encoding="utf-8")
        assert "help-guide-integration-round1014" in test
        assert "renderGuideMarkdown" in test
        assert "sanitizedGuideHtml" in test


# ═══ стиль гайда ═════════════════════════════════════════════════════════════

class TestGuideStyle:
    def test_forbidden_jargon(self):
        text = DOCS.read_text(encoding="utf-8")
        low = text.lower()
        forbidden = ("rag", "llm", "токен", "эндпоинт", "endpoint", "json",
                     "sqlite", " pg ", "postgres", "векторн", "эмбеддинг",
                     "промпт", "воркер", " api ")
        hits = [w for w in forbidden if w in low]
        assert hits == [], f"запрещённый жаргон: {hits}"

    def test_new_sections_present(self):
        text = DOCS.read_text(encoding="utf-8")
        assert "Бот помнит свои слова" in text
        assert "Личность бота" in text
        assert "Эволюция характера" in text
        assert "Осознаёт себя ИИ" in text
        # H 10.20 (БЛОК 8): Летописец + безлимиты в гайде.
        assert "Летописец" in text
        assert "Лимиты и безлимиты" in text
        # F7 10.22 (ADR-1022-7): блок «Как бот думает (System 2)».
        assert "Как бот думает" in text
        assert "System 2" in text

    def test_guide_not_empty_and_markdown(self):
        text = DOCS.read_text(encoding="utf-8")
        assert len(text) > 3000
        assert text.startswith("# ")
        assert "## 12. Словарик" in text
