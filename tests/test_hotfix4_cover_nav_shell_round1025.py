"""Хотфикс-4 (round10.25, T-2507…T-2528, ADR-1025-8 D1–D3) — регресс-гейт.

Покрывает три P0-направления:
  * **A** (обложка саммари): настроенный `prompts.summary_cover_style` доходит
    до `compose_cover_image_prompt` (round-trip save→re-read), R17-маркеры
    `has_comic`/`has_heading`/`style_is_default`, фолбэк при пустом
    `draft.cover_prompt`, смягчённый канон Редактора (разрешён короткий
    заголовок владельца) + ступень канон-миграции/откат.
  * **B** (mobile-панель): `--tg-viewport-bottom-offset` (JS) + CSS-фолбэк
    `100dvh − stable-height`, `viewport-fit=cover`, вертикальный матричный
    контроль, сохранённые тач-цель/safe-area.
  * **C** (нижняя навигация): Статус+Справка — первые два для всех ролей,
    «Ещё» без дубля «Справки» (поведение — в
    `tests/js/round1025_ia_routing_test.js`).

Тесты A/B/C падают на старом коде (доказывают фикс).
"""
import json
import logging
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import hot_config as hot
from services import param_catalog as pc
from services import summary_generator as sg
from services import chat_params
from services.config_cache import ConfigCache
from services.prompt_migrations import PROMPT_MIGRATIONS, ROLLBACK_MIGRATIONS
from services.summary_generator import (
    SummaryGenerator,
    cover_style_markers,
    resolve_cover_style,
)
from services.summary_generator import compose_cover_image_prompt
from services.summary_prompts import (
    PREV_SUMMARY_EDITOR_R1025_HOTFIX4,
    SUMMARY_COVER_STYLE_DEFAULT,
    SUMMARY_EDITOR_COVER_PROMPT_BLOCK,
    SUMMARY_EDITOR_SYSTEM_PROMPT,
)
from tests.summary_cover_helpers import (
    Recorder as _Recorder,
    env as _env,
    generator as _generator,
)

pytestmark = pytest.mark.system2

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
TG_INIT = (ROOT / "web" / "static" / "telegram-init.js").read_text(
    encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
MATRIX = (ROOT / "tools" / "ui_round1025_matrix.py").read_text(
    encoding="utf-8")
PG_DB = (ROOT / "services" / "pg_db.py").read_text(encoding="utf-8")

_VALID_DIGEST = "# Тема\n- Вася спорил с Петей"
_CUSTOM_STYLE = "in comic style, with a large PERMsoc heading"
_STYLE_KEY = "prompts.summary_cover_style"


# ── Мини-PG стенд для РЕАЛЬНОГО пути ConfigCache (без мока hot.get) ───────

class _FakeConn:
    """Мини-соединение: `execute` пишет JSON-строку (как jsonb), `fetch` —
    набор строк bot_settings (декодирует JSON, как кодеки jsonb)."""

    def __init__(self, store):
        self.store = store

    async def execute(self, sql, *args):
        key, value_json, category = args[0], args[1], args[2]
        self.store[key] = {"value": value_json, "category": category}

    async def fetch(self, sql):
        if "from bot_settings" in sql.lower():
            return [{"key": k, "value": json.loads(v["value"]),
                     "category": v["category"], "updated_at": None}
                    for k, v in self.store.items()]
        return []


class _FakePool:
    """asyncpg-подобный пул: `acquire()` → контекстный менеджер соединения."""

    def __init__(self):
        self.store = {}
        self._conn = _FakeConn(self.store)

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


class _FakeChatParams:
    """ChatParamsCache-подобный: root-лейаут чата (overrides)."""

    def __init__(self, overrides):
        self._overrides = overrides

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._overrides), "perm_overrides": {}}


# ── A. Стиль обложки: применение, маркеры, фолбэк, канон ─────────────────

class TestCoverStyleApplied:
    def test_default_only_when_absent_or_blank(self):
        """T-2509: дефолт — ТОЛЬКО при реальном отсутствии/пустоте значения."""
        for blank in (None, "", "   ", "\n\t"):
            assert resolve_cover_style(blank) == SUMMARY_COVER_STYLE_DEFAULT
        assert resolve_cover_style(_CUSTOM_STYLE) == _CUSTOM_STYLE
        assert resolve_cover_style("  " + _CUSTOM_STYLE + "  ") == _CUSTOM_STYLE

    def test_markers_r17_safe(self):
        """T-2508: маркеры содержимого — без самого текста."""
        m = cover_style_markers(_CUSTOM_STYLE)
        assert m["has_comic"] is True
        assert m["has_heading"] is True
        assert m["style_is_default"] is False
        default = cover_style_markers(SUMMARY_COVER_STYLE_DEFAULT)
        assert default["style_is_default"] is True
        assert default["has_comic"] is False
        assert default["has_heading"] is False

    def test_has_heading_word_boundaries(self):
        """Review L10.25H4-3: не ловим `permanent`/`permission`/`entitled`."""
        for false_style in ("permanent marker", "permission granted",
                            "entitled to win", "pre-titled"):
            assert cover_style_markers(false_style)["has_heading"] is False, \
                false_style
        for true_style in ("PERMsoc heading", "title card", "крупный заголовок",
                           "with heading"):
            assert cover_style_markers(true_style)["has_heading"] is True, \
                true_style

    @pytest.mark.asyncio
    async def test_configured_style_reaches_compose_and_log(
            self, monkeypatch, caplog):
        gen = SummaryGenerator(MagicMock(), MagicMock(), MagicMock(),
                               MagicMock(), concurrency_pool=MagicMock())
        monkeypatch.setattr(sg.hot, "get",
                            lambda key, default=None: _CUSTOM_STYLE)
        image_mock = AsyncMock(return_value=(None, "bad_request"))
        monkeypatch.setattr(sg, "generate_image_verbose", image_mock)
        monkeypatch.setattr(SummaryGenerator, "_plain_fallback", AsyncMock())

        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._deliver_rich(-100, "текст", "a lone cat")

        # Настроенный стиль РЕАЛЬНО доходит до image-API (первым в промпте).
        final_prompt = image_mock.await_args.args[0]
        assert final_prompt.startswith(_CUSTOM_STYLE)
        assert final_prompt.endswith("a lone cat")
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "style_is_default=False" in joined
        assert "has_comic=True" in joined
        assert "has_heading=True" in joined
        # R17: текст стиля/промпта в лог не попадает.
        assert "large PERMsoc heading" not in joined

    @pytest.mark.asyncio
    async def test_absent_style_logs_default(
            self, monkeypatch, caplog):
        gen = SummaryGenerator(MagicMock(), MagicMock(), MagicMock(),
                               MagicMock(), concurrency_pool=MagicMock())
        monkeypatch.setattr(sg.hot, "get", lambda key, default=None: None)
        monkeypatch.setattr(
            sg, "generate_image_verbose",
            AsyncMock(return_value=(None, "bad_request")))
        monkeypatch.setattr(SummaryGenerator, "_plain_fallback", AsyncMock())

        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._deliver_rich(-100, "текст", "a lone cat")

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "style_is_default=True" in joined

    @pytest.mark.asyncio
    async def test_round_trip_save_reread(self):
        """T-2509: load→edit→save→re-read даёт настроенный стиль (не дефолт)."""
        cache = ConfigCache()
        await cache.set(_STYLE_KEY, _CUSTOM_STYLE, "prompts")
        assert cache.get(_STYLE_KEY) == _CUSTOM_STYLE
        hot.set_config_cache(cache)
        try:
            read_back = hot.get(_STYLE_KEY, None)
            assert read_back == _CUSTOM_STYLE
            assert resolve_cover_style(read_back) == _CUSTOM_STYLE
        finally:
            hot.set_config_cache(None)

    @pytest.mark.asyncio
    async def test_pg_backed_save_reload_reread_compose(self):
        """[High] РЕАЛЬНЫЙ путь (PG-backed ConfigCache, без мока hot.get):
        `set` → PG-upsert → `reload()` → `hot.get` → `resolve_cover_style` →
        `compose_cover_image_prompt`. Доказывает, что сохранённое значение
        переживает save→re-read и даёт настроенный промпт."""
        pool = _FakePool()
        cache = ConfigCache(pg=types.SimpleNamespace(pool=pool))
        cache._pg_available = True
        await cache.set(_STYLE_KEY, _CUSTOM_STYLE, "prompts")
        # Значение ушло в «PG» под верным ключом/категорией.
        assert pool.store[_STYLE_KEY]["category"] == "prompts"
        # reload() перечитывает из «PG» (память очищается нагрузкой заново).
        await cache.reload()
        hot.set_config_cache(cache)
        try:
            read_back = hot.get(_STYLE_KEY, None)
            assert read_back == _CUSTOM_STYLE
            style = resolve_cover_style(read_back)
            assert style == _CUSTOM_STYLE
            final = compose_cover_image_prompt(style, "a lone cat")
            assert final == _CUSTOM_STYLE + " a lone cat"
            assert cover_style_markers(style)["style_is_default"] is False
        finally:
            hot.set_config_cache(None)

    @pytest.mark.asyncio
    async def test_saved_value_survives_migrations(self):
        """[High] Сохранённое значение НЕ перезаписывается канон-миграциями и
        не зависит от seed по умолчанию (idempotent `ON CONFLICT DO NOTHING`)."""
        # Ключ стиля вообще не входит в канон-миграции промптов.
        assert _STYLE_KEY not in PROMPT_MIGRATIONS
        assert _STYLE_KEY not in ROLLBACK_MIGRATIONS
        # ConfigCache-апсерт (global write) — DO UPDATE (значение владельца
        # действительно перезаписывает прежнее, не «тихо» теряется).
        from services.config_cache import _UPSERT_SETTING_SQL
        assert "ON CONFLICT (key) DO UPDATE" in _UPSERT_SETTING_SQL
        # Сид стартовых настроек — DO NOTHING (дефолт не затирает значение).
        assert "ON CONFLICT (key) DO NOTHING" in PG_DB
        # Прогон миграций на реальном кэше с сохранённым стилем — no-op для него.
        pool = _FakePool()
        cache = ConfigCache(pg=types.SimpleNamespace(pool=pool))
        cache._pg_available = True
        await cache.set(_STYLE_KEY, _CUSTOM_STYLE, "prompts")
        from services.prompt_migrations import migrate_prompt_canons
        report = await migrate_prompt_canons(cache)
        assert _STYLE_KEY not in report
        assert cache.get(_STYLE_KEY) == _CUSTOM_STYLE

    def test_key_is_per_chat_capable(self):
        """[High] Root-cause scope: `prompts.*` per-chat-переносимы — Mini App в
        контексте чата пишет в `chat_params.overrides`, а саммари читает
        scope-корректно (override чата → глобал → дефолт)."""
        spec = pc.get_by_pg_key(_STYLE_KEY)
        assert spec is not None and spec.per_chat is True

    @pytest.mark.asyncio
    async def test_chat_override_wins_over_global(self):
        """[High] per-chat override реально резолвится (scope-фикс)."""
        hot.set_config_cache(None)
        chat_params.set_chat_params_cache(
            _FakeChatParams({_STYLE_KEY: _CUSTOM_STYLE}))
        try:
            resolved = await chat_params.get_chat_param(-100, _STYLE_KEY, None)
            assert resolved == _CUSTOM_STYLE
        finally:
            chat_params.set_chat_params_cache(None)

    @pytest.mark.asyncio
    async def test_deliver_rich_uses_chat_override(self, monkeypatch):
        """[High] End-to-end: chat-scoped сохранение доходит до image-API."""
        chat_params.set_chat_params_cache(
            _FakeChatParams({_STYLE_KEY: _CUSTOM_STYLE}))
        try:
            gen = SummaryGenerator(MagicMock(), MagicMock(), MagicMock(),
                                   MagicMock(), concurrency_pool=MagicMock())
            image_mock = AsyncMock(return_value=(None, "bad_request"))
            monkeypatch.setattr(sg, "generate_image_verbose", image_mock)
            monkeypatch.setattr(SummaryGenerator, "_plain_fallback", AsyncMock())
            await gen._deliver_rich(-100, "текст", "a lone cat")
            assert image_mock.await_args.args[0].startswith(_CUSTOM_STYLE)
            assert image_mock.await_args.args[0].endswith("a lone cat")
        finally:
            chat_params.set_chat_params_cache(None)

    def test_seed_does_not_overwrite_saved(self):
        """T-2509(c): сид — INSERT ... ON CONFLICT (key) DO NOTHING."""
        assert "ON CONFLICT (key) DO NOTHING" in PG_DB
        assert "INSERT_SETTING_SQL" in PG_DB


class TestCoverCatalogEditable:
    def test_key_visible_and_textarea_in_prompts_tab(self):
        """T-2510: ключ виден/редактируем в Mini App (Δ каталога = 0)."""
        spec = pc.get_by_pg_key("prompts.summary_cover_style")
        assert spec is not None
        assert spec.hidden is False
        assert spec.widget == "textarea"
        assert spec.category == "prompts"
        assert spec.group == "prompts_summary"
        assert spec.group in pc.tab_group_ids("prompts")

    def test_prompts_v2_renders_advanced_items(self):
        """V2-раскладка отдаёт advanced-элементы в общий grid (не прячет)."""
        assert "promptVisibleItems: function (sec)" in APP_JS
        assert ("return (sec.basic || []).concat(sec.advanced || []);"
                in APP_JS)


class TestCoverCanonHotfix4:
    def test_prev_snapshot_differs(self):
        assert PREV_SUMMARY_EDITOR_R1025_HOTFIX4 != SUMMARY_EDITOR_SYSTEM_PROMPT
        assert PREV_SUMMARY_EDITOR_R1025_HOTFIX4.endswith(
            "Одна фраза, без кавычек и переносов строк.")

    def test_editor_block_self_contained_no_contradiction(self):
        """Review [Medium]: блок Редактора self-contained — Редактор НЕ видит
        «Стиль обложки» (он идёт отдельно в image-промпт), поэтому нет ссылки
        на невидимый стиль и нет противоречия «без надписей, НО включи
        заголовок»."""
        block = SUMMARY_EDITOR_COVER_PROMPT_BLOCK
        assert "PERMsoc" not in block
        assert "heading" not in block.lower()
        # Свои надписи не добавляем, заголовок задаёт авторский стиль отдельно.
        assert "надпис" in block.lower()
        assert "«Стиль обложки»" in block

    def test_migration_step_and_rollback(self):
        key = "prompts.summary_editor_system_prompt"
        assert (PREV_SUMMARY_EDITOR_R1025_HOTFIX4,
                SUMMARY_EDITOR_SYSTEM_PROMPT) in PROMPT_MIGRATIONS[key]
        assert ROLLBACK_MIGRATIONS[key] == (
            SUMMARY_EDITOR_SYSTEM_PROMPT, PREV_SUMMARY_EDITOR_R1025_HOTFIX4)


class TestCoverFallbackEmptyDraft:
    @pytest.mark.asyncio
    async def test_draft_with_empty_cover_prompt_keeps_cover(
            self, monkeypatch, tmp_path, caplog):
        """T-2512: draft есть, cover_prompt пуст → rich с обложкой (не plain)."""
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _env(monkeypatch, rec, cover_path=str(img))
        editor = json.dumps({"response_mode": "casual",
                             "digest": _VALID_DIGEST,
                             "cover_prompt": ""})
        gen, _llm = _generator([editor, "готовый дерзкий текст"])

        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._run(-100, False)

        assert rec.plain == []                     # тихой потери обложки нет
        assert len(rec.rich) == 1
        assert rec.image_prompts                   # фолбэк-промпт получен
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason=draft_cover_empty" in joined

    @pytest.mark.asyncio
    async def test_draft_with_cover_prompt_unchanged(
            self, monkeypatch, tmp_path):
        """Рабочий rich-путь не изменён: непустой cover_prompt — как раньше."""
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _env(monkeypatch, rec, cover_path=str(img))
        editor = json.dumps({"response_mode": "casual",
                             "digest": _VALID_DIGEST,
                             "cover_prompt": "a lone cat"})
        gen, _llm = _generator([editor, "готовый текст"])

        await gen._run(-100, False)

        assert len(rec.rich) == 1
        assert rec.image_prompts
        assert rec.image_prompts[0].endswith("a lone cat")


# ── B. Панель mobile: offset + CSS-фолбэк + viewport-fit + матрица ────────

class TestBottomPanelInViewport:
    def test_bottom_nav_offset_var_with_fallback(self):
        assert "--tg-viewport-bottom-offset" in CSS
        assert "bottom: var(--tg-viewport-bottom-offset," in CSS
        assert "100dvh - var(--tg-viewport-stable-height" in CSS

    def test_more_sheet_uses_same_offset(self):
        seg = CSS[CSS.index(".more-sheet {"):]
        assert "--tg-viewport-bottom-offset" in seg[:700]

    def test_telegram_init_computes_and_updates(self):
        assert "--tg-viewport-bottom-offset" in TG_INIT
        assert "window.innerHeight" in TG_INIT
        assert "viewportStableHeight" in TG_INIT
        for ev in ("viewportChanged", "safeAreaChanged",
                   "contentSafeAreaChanged"):
            assert ev in TG_INIT

    def test_viewport_fit_cover(self):
        assert "viewport-fit=cover" in INDEX

    def test_touch_and_safe_area_preserved(self):
        assert "min-height: 44px" in CSS
        assert "env(safe-area-inset-bottom" in CSS

    def test_matrix_vertical_check(self):
        assert "_vertical_failures" in MATRIX
        assert "innerHeight" in MATRIX and "stableHeight" in MATRIX
        assert "bottom" in MATRIX
        # «Ещё» проверяется при открытии шторки.
        assert "more-sheet(open)" in MATRIX


# ── C. Нижняя навигация: Статус+Справка первыми, без дубля ────────────────

class TestBottomNavOrder:
    def test_bottom_nav_starts_status_how_and_priority_admin(self):
        seg = APP_JS[APP_JS.index("bottomNavItems: function"):
                     APP_JS.index("mobileMoreItems: function")]
        assert "byId['status']" in seg
        assert "byId['how']" in seg
        assert "byId['modules'] || byId['ai']" in seg
        # ≤4 пункта: status, how, (modules|ai), more.
        assert "hiddenCount" in seg

    def test_more_items_no_duplicate_how(self):
        seg = APP_JS[APP_JS.index("mobileMoreItems: function"):
                     APP_JS.index("isMobileShell: function")]
        assert "n.group !== 'public'" in seg
        assert "n.id !== inlineId" in seg
        assert "'how'" not in seg


# ── Совместимость: системный флаг System 2 не задет ──────────────────────

def test_system2_flag_still_classvar(monkeypatch):
    monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
    assert Settings.SYSTEM2_SUMMARY_ENABLED is True
