"""F9 round 10.25 — секрет-поле (display-маска) + визуальный добор SaveBar.

ADR-1025-22 (D1–D7), §50/§51/§69/§78, R17/R18.

Поведение (маска не в API, «Заменить»/«Удалить», keyboard/safe-area)
реально прогоняется в:
  * `tests/js/round1025_f9_secret_field_test.js`  (F9-SECRET-OK);
  * `tests/js/round1025_f9_savebar_visual_test.js` (F9-SAVEBAR-OK).
Здесь — статические инварианты: Δ каталога=0, Δ DDL=0, bump, R17, CSP,
единственный write-path F0, единый компонент.
"""
import dataclasses
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from config.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
CATALOG = (ROOT / "services" / "param_catalog.py").read_text(encoding="utf-8")


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    return node


def _run_js(script: str, ok_marker: str):
    node = _node()
    res = subprocess.run(
        [node, os.path.join(*script.split("/"))],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert res.returncode == 0, (
        "JS-UNIT не прошёл (%s):\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (script, res.stdout, res.stderr))
    assert ok_marker in res.stdout


class TestSecretFieldBehaviour:
    """Поведенческие JS-тесты секрет-поля (реальный node, не grep)."""

    def test_secret_field_js(self):
        _run_js("tests/js/round1025_f9_secret_field_test.js", "F9-SECRET-OK")

    def test_savebar_visual_js(self):
        _run_js("tests/js/round1025_f9_savebar_visual_test.js", "F9-SAVEBAR-OK")


class TestD1MaskIsDisplay:
    def test_secret_display_helper(self):
        assert "secretDisplay: function" in JS
        assert "secretDisplayOf" in JS
        assert "Ключ установлен" in JS
        assert "Не настроен" in JS

    def test_no_seed_of_mask(self):
        # D1: маска НЕ засеивается в keyDrafts/значение.
        assert not re.search(r"keyDrafts\[[^\]]+\]\s*=\s*SECRET_MASK", JS)
        assert not re.search(r"value\s*:\s*SECRET_MASK", JS)
        # Guard'ы (defense-in-depth) сохранены.
        assert "isSecretMask" in JS and "hasSecretMask" in JS
        assert "SECRET_MASK_HINT" in JS

    def test_block_field_value_empty_for_secret(self):
        assert "blockFieldValue: function" in JS
        assert "if (isSecret) return '';" in JS


class TestD2Delete:
    def test_delete_uses_existing_surfaces(self):
        assert "deleteKeyItem: async function" in JS
        # image-ключ → существующий safe-эндпоинт (R16: без нового endpoint).
        assert "/api/config/keys/own/" in JS
        # прочие → F0 empty-write через persistItems (value:'').
        assert "deleteKeyItem" in JS and "persistItems" in JS
        # ЗАПРЕЩЕНО: удаление через сброс override.
        assert "DELETE" in JS
        assert "/api/config/chat/" not in JS.split("deleteKeyItem: async function")[1][:1600]

    def test_confirm_gate(self):
        seg = JS.split("deleteKeyItem: async function")[1][:900]
        assert "window.confirm(" in seg


class TestD4SingleComponent:
    def test_component_registered(self):
        assert "component('secret-field'" in JS
        assert "template: '#secret-field-tpl'" in JS
        assert 'id="secret-field-tpl"' in INDEX

    def test_templates_migrated(self):
        # прямых привязок keyDrafts в index.html больше нет (компонент).
        assert len(re.findall(r'v-model="keyDrafts\[item\.key\]"', INDEX)) == 0
        assert "update:draft=\"keyDrafts[item.key] = $event\"" in INDEX
        # BYOK остаётся chat-scope.
        assert 'scope="chat"' in INDEX

    def test_css(self):
        for cls in (".secret-field {", ".secret-field__mask",
                    ".secret-field__actions"):
            assert cls in CSS, cls


class TestD5SaveBarVisual:
    def test_keyboard_offset(self):
        assert "_syncKeyboardOffset: function" in JS
        assert "--kb-offset" in JS
        assert "visualViewport" in JS
        assert "scrollIntoView({ block: 'nearest' })" in JS

    def test_safe_area_once(self):
        actions = re.search(r"\.modal-actions\s*\{([^}]*)\}", CSS).group(1)
        assert "env(safe-area-inset-bottom" not in actions
        sticky = re.search(r"\.sticky-save\s*\{([^}]*)\}", CSS).group(1)
        assert sticky.count("env(safe-area-inset-bottom") == 1

    def test_last_field(self):
        assert "scroll-padding-bottom" in CSS
        assert ".sticky-spacer" in CSS
        assert "scroll-margin-bottom" in CSS

    def test_savebar_outside_modal_body(self):
        idx = INDEX.index('<footer class="modal-actions')
        before = INDEX[:idx]
        assert before.rindex('<div class="modal-body">') < \
            before.rindex('</div>')


class TestD6NoF0Duplication:
    def test_single_write_path(self):
        assert JS.count("persistItems: async function") == 1
        assert JS.count("notify: function (operationId") == 1
        assert "_opNotified[operationId]" in JS

    def test_one_notification_and_more(self):
        assert 'class="toast-more"' in INDEX
        assert ".toast-text--long" in CSS
        assert ".toast-more" in CSS

    def test_states_displayed(self):
        assert "data-save-state" in JS
        assert "Загрузка…" in JS and "Сохранено" in JS and "Конфликт версии" in JS


class TestInvariants:
    def test_catalog_delta_zero(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 469
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426

    def test_secrets_count_28(self):
        # 20 category=keys (UI) + 8 env-only infra — состав НЕ изменён.
        assert len(pc_secret_names()) == 28

    def test_app_version_bump(self):
        m = re.search(r'APP_VERSION = "([\d.]+)"', SETTINGS)
        assert m and m.group(1) == "2.58.30", m and m.group(1)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "v2.58.30" in readme

    def test_no_ddl_change(self):
        # F9 — UI-only: миграции/схема не трогаются.
        for sub in ("services", "web"):
            for p in (ROOT / sub).rglob("*.py"):
                txt = p.read_text(encoding="utf-8", errors="ignore")
                assert "secret_field" not in txt.lower(), p

    def test_csp_zero_build(self):
        for host in ("unpkg.com", "cdn.jsdelivr.net", "cdn.tailwindcss.com",
                     "http://", "https://"):
            assert host not in INDEX, host


def pc_secret_names():
    from services import param_catalog as pc
    names = set()
    for key, spec in pc.REGISTRY.items():
        if getattr(spec, "secret", False):
            names.add(key)
    return names
