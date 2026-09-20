"""F24 (раунд 10.24, ADR-1024-24) — fullscreen-sync + реактивный аккордеон.

Боевой дефект: в «Провайдерах» аккордеон «Расширенные системные» схлопывался
при переходе TMA в fullscreen (нереактивный `:open` + рассинхрон с TMA).

Покрытие (T-2385):
  * `:open` больше НЕ вызывает expandOpen(...) — завязан на реактивные
    computed advancedOpen/provAdvancedOpen/chatLoreAdvancedOpen (5 зон);
  * `@toggle` передаёт $event (C2: синхронизация с DOM, а не инверсия);
  * в app.js есть initExpandState/initFullscreen/setFullscreenFromTma/
    teardownFullscreen, подписки fullscreenChanged/viewportChanged и offEvent;
  * expandOpen читает реактивный `this.expand` (localStorage — только персист);
  * `.fullscreen-mode` (:class isFullscreen) сохранён;
  * `node --check web/app.js`.

Все проверки — статические маркеры + один node --check (как round106 smoke).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


class TestReactiveAccordionBindings:
    """`web/index.html` — 5 биндинг-сайтов переведены на реактивный контракт."""

    def test_open_bound_to_reactive_computed(self):
        assert ':open="advancedOpen"' in HTML
        assert ":open=\"activeTab === 'llm_providers' ? provAdvancedOpen : null\"" \
            in HTML
        assert ':open="chatLoreAdvancedOpen"' in HTML

    def test_no_expandopen_call_in_open_binding(self):
        # В шаблоне `:open` НЕ вызывает state-функцию.
        assert ':open="expandOpen(' not in HTML
        assert ":open=\"activeTab === 'llm_providers' ? expandOpen(" not in HTML

    def test_toggle_passes_event(self):
        assert "toggleExpand(activeTab, null, $event)" in HTML
        assert "toggleExpand(activeTab, 'prov-advanced', $event)" in HTML
        assert "toggleExpand('chat_lore', null, $event)" in HTML

    def test_computed_accessors_present(self):
        assert "advancedOpen: function" in JS
        assert "chatLoreAdvancedOpen: function" in JS
        assert "provAdvancedOpen: function" in JS


class TestReactiveAccordionState:
    """`web/app.js` — реактивный стейт аккордеона (C1/C2)."""

    def test_expand_is_reactive_source(self):
        # data.expand — реактивный стейт; expandOpen читает this.expand.
        assert "expand: {}," in JS
        assert "return !!this.expand[_expandKey(tabId, scope)];" in JS
        # Легаси-чтение localStorage в expandOpen удалено.
        assert "localStorage.getItem(_expandKey(tabId, scope))" not in JS

    def test_init_expand_state(self):
        assert "initExpandState: function" in JS
        assert "this.initExpandState();" in JS
        assert "adminbot.expand:" in JS

    def test_toggle_signature_with_event(self):
        assert "toggleExpand: function (tabId, scope, ev)" in JS
        assert "typeof ev.target.open === 'boolean'" in JS


class TestFullscreenSync:
    """`web/app.js` — синхронизация fullscreen с TMA (C3/C4)."""

    def test_methods_present(self):
        for token in ("initFullscreen: function", "setFullscreenFromTma: function",
                      "teardownFullscreen: function"):
            assert token in JS, token
        assert "Telegram.WebApp.isFullscreen" in JS

    def test_subscriptions_and_off(self):
        assert "onEvent('fullscreenChanged'" in JS
        assert "onEvent('viewportChanged'" in JS
        assert "offEvent('fullscreenChanged'" in JS
        assert "offEvent('viewportChanged'" in JS

    def test_lifecycle_hooks(self):
        assert "this.initFullscreen();" in JS      # mounted
        assert "self.initFullscreen();" in JS      # ready-обработчик
        assert "this.teardownFullscreen();" in JS  # beforeUnmount

    def test_fullscreen_mode_class_preserved(self):
        assert "'fullscreen-mode': isFullscreen" in HTML


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    return node


def test_node_check_app_js():
    node = _node()
    res = subprocess.run(
        [node, "--check", os.path.join("web", "app.js")],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert res.returncode == 0, res.stderr
