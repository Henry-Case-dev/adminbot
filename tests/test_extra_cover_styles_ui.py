"""EXTRA Pass 2 (ADR-1028-4 D10/D11/D12; spec §3.6/§3.12/§75/§77/§93/§98) —
UI-маркеры, seed-ассеты, invariants.

Статические проверки (не grep-замена): реальные маркеры Style Editor в
`web/index.html`/`web/app.js`, фактические seed-файлы и их sha256 (§77/DC-1),
резерв `validation_mode` (§93) и first-class Base Cover (§98).
"""
import hashlib
from pathlib import Path

from services import cover_style_registry as registry
from services import cover_style_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[1]


def _html() -> str:
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _app_js() -> str:
    return (ROOT / "web" / "app.js").read_text(encoding="utf-8")


class TestStyleEditorMarkers:
    def test_html_has_style_editor_block(self):
        html = _html()
        for marker in ("data-cover-styles", "data-cover-style-list",
                       "data-cover-style-editor", "data-cover-style-select",
                       "data-cover-style-new", "data-cover-style-name",
                       "data-cover-style-instruction",
                       "data-cover-style-instruction",
                       "data-cover-reference-input",
                       "data-cover-replace-input",
                       "data-cover-preview-stale", "data-cover-preview-update",
                       "data-cover-test-input", "data-cover-style-save",
                       "data-cover-connections-link", "data-config-group",
                       "data-cover-styles-disabled"):
            assert marker in html, marker

    def test_ru_labels_present(self):
        html = _html()
        for label in ("Стили обложки", "Референсы", "Нумерация выпуска",
                      "Модель обработки", "Настроить подключения",
                      "Протестировать стиль", "Пример", "Обновить пример",
                      "Пример создан для предыдущей версии стиля",
                      "Время обработки", "Заменить"):
            assert label in html, label
        # L-EXTRA-5: бессмысленная подпись «Затемнение» удалена.
        assert "Затемнение" not in html
        js = _app_js()
        # Ярлык «без стиля» и сообщение unknown-limit — из runtime-кода UI.
        assert "Без дополнительного стиля" in js
        assert "Провайдер не публикует точный лимит" in js

    def test_app_js_tab_and_label(self):
        js = _app_js()
        assert "styles: 'Стили обложки'" in js
        assert "'testing', 'styles'" in js

    def test_editor_methods_present(self):
        js = _app_js()
        for name in ("loadCoverStyles:", "coverStyleSave:",
                     "coverStyleDuplicate:", "coverStyleDelete:",
                     "coverStyleUploadReference:", "coverStyleRemoveReference:",
                     "coverStyleReplaceReference:", "coverStylePreview:",
                     "coverStyleSetSelection:",
                     "openCoverConnections:", "_applyConfigFocus:",
                     "coverStyleRefreshExample:", "coverBudgetText:",
                     "coverCapabilityLines:", "fileToBase64:"):
            assert name in js, name
        # §35: deep-link фокусирует группу «Обработка стилей обложки».
        assert "configFocusGroup" in js
        assert "models_images" in js


class TestSeedAssets:
    def test_actual_seed_names_jpg(self):
        # DC-1: фактический After — `.jpg`, не `.png`.
        assert registry.SEED_FILES["reference"] == "medved_press.png"
        assert registry.SEED_FILES["preview_before"] == "style_example_01.png"
        assert registry.SEED_FILES["preview_after"] == "style_example_02.jpg"

    def test_seed_files_exist_with_documented_sha(self):
        expected = {
            "medved_press.png":
                "BE0A700BA8D3AF64358EEE6697AEFF11BCE8765E6FC8D9730E3569DF74AA15DB",
            "style_example_01.png":
                "88A3D6BF5852A65C7167253C5DC730F50F9884AF4C7C8A5E397448F84B161006",
            "style_example_02.jpg":
                "B3C337A68197B5974E93CAAA75C45D2CBB78955436838868ABE01CED4E88878E",
        }
        base = ROOT / "extra_images"
        for name, sha in expected.items():
            path = base / name
            assert path.exists(), name
            digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            assert digest == sha, name


class TestInvariants:
    def test_first_class_base_cover_and_degraded_path(self):
        gen = (ROOT / "services" / "summary_generator.py").read_text(
            encoding="utf-8")
        assert "_publish_rich_without_cover" in gen
        assert "_degrade_without_cover" in gen
        # Base Cover Generation — first-class: путь обложки сохранён.
        assert "compose_cover_image_prompt" in gen

    def test_no_edit_message_ru(self):
        assert "не умеет редактировать готовые изображения" \
            in pipeline.NO_EDIT_MESSAGE

    def test_kill_switch_env_only(self):
        # Δ каталога = 0 для kill-switch: не датакласс-поле, env ClassVar.
        import dataclasses
        from config.settings import settings as cfg
        names = {f.name for f in dataclasses.fields(cfg.__class__)}
        assert "COVER_STYLES_ENABLED" not in names
        assert isinstance(pipeline.cover_styles_enabled(), bool)

    def test_validation_mode_reserved(self):
        """§93: архитектурный резерв `validation_mode` в DDL (off|basic|strict)."""
        pg = (ROOT / "services" / "pg_db.py").read_text(encoding="utf-8")
        assert "validation_mode" in pg
        assert "cover_style_profiles" in pg

    def test_no_third_mandatory_call(self):
        """§93: третий обязательный LLM/image call не добавлен.

        Style-стадия делает РОВНО один image-edit вызов и **не** перегенерирует
        base (нет `generate_image_verbose` в оркестраторе cover-джобы).
        """
        import re
        jobs = (ROOT / "services" / "cover_style_jobs.py").read_text(
            encoding="utf-8")
        assert "generate_image_verbose" not in jobs
        assert not re.search(r"\bvision\b", jobs, re.IGNORECASE)
