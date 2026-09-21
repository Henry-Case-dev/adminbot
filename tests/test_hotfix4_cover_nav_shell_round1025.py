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
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import hot_config as hot
from services import param_catalog as pc
from services import summary_generator as sg
from services.config_cache import ConfigCache
from services.prompt_migrations import PROMPT_MIGRATIONS, ROLLBACK_MIGRATIONS
from services.summary_generator import (
    SummaryGenerator,
    cover_style_markers,
    resolve_cover_style,
)
from services.summary_prompts import (
    PREV_SUMMARY_EDITOR_R1025_HOTFIX4,
    SUMMARY_COVER_STYLE_DEFAULT,
    SUMMARY_EDITOR_SYSTEM_PROMPT,
)
from tests.test_hotfix3_summary_fallback_round1025 import (
    _Recorder,
    _env,
    _generator,
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

    @pytest.mark.asyncio
    async def test_configured_style_reaches_compose_and_log(
            self, monkeypatch, caplog):
        gen = SummaryGenerator(MagicMock(), MagicMock(), MagicMock(),
                               MagicMock(), concurrency_pool=MagicMock())
        monkeypatch.setattr(sg.hot, "get",
                            lambda key, default=None: _CUSTOM_STYLE)
        monkeypatch.setattr(
            sg, "generate_image_verbose",
            AsyncMock(return_value=(None, "bad_request")))
        monkeypatch.setattr(SummaryGenerator, "_plain_fallback", AsyncMock())

        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._deliver_rich(-100, "текст", "a lone cat")

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
        await cache.set("prompts.summary_cover_style", _CUSTOM_STYLE, "prompts")
        assert cache.get("prompts.summary_cover_style") == _CUSTOM_STYLE
        hot.set_config_cache(cache)
        try:
            read_back = hot.get("prompts.summary_cover_style", None)
            assert read_back == _CUSTOM_STYLE
            assert resolve_cover_style(read_back) == _CUSTOM_STYLE
        finally:
            hot.set_config_cache(None)

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

    def test_editor_allows_owner_heading(self):
        """T-2511: канон не запрещает короткий заголовок владельца."""
        assert "PERMsoc" in SUMMARY_EDITOR_SYSTEM_PROMPT
        assert "заголов" in SUMMARY_EDITOR_SYSTEM_PROMPT.lower()

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
