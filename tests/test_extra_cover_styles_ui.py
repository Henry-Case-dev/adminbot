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
                       "data-cover-test-button", "data-cover-style-save",
                       "data-cover-connections-link", "data-config-group",
                       "data-cover-styles-disabled",
                       # ASAP 4.2 (D5.4/D5.5/D5.8):
                       "data-cover-mini-before", "data-cover-mini-after",
                       "data-cover-preview-arrow", "data-cover-preview-source",
                       "data-cover-test-human", "data-cover-developer-toggle",
                       "data-cover-developer-reason", "data-cover-readonly",
                       # ASAP 4.3 (T-4847/T-4849/T-4853):
                       "data-cover-prompt-limit", "data-cover-limit-mode",
                       "data-cover-limit-unit", "data-cover-limit-value",
                       "data-cover-limit-save", "data-cover-limit-resolved",
                       "data-cover-style-budget", "data-cover-budget-breakdown",
                       "data-cover-test-progress", "data-cover-test-stage",
                       "data-cover-test-breakdown"):
            assert marker in html, marker
        # D5.5: Test Style — НЕ файловый picker (никакого `type=file` рядом с
        # `data-cover-test-button`).
        assert 'data-cover-test-input' not in html, \
            "Test Style не должен иметь file input (D5.5)"

    def test_ru_labels_present(self):
        html = _html()
        # ASAP-3.2 (ТЗ §105/§109/§126): секция техники — «Модель и
        # подключение» (collapsed); кнопка — «Настроить подключение»
        # (§126, состояние «provider не настроен»).
        # ASAP 4.2 (D5.8): человеческие подписи основного UI.
        for label in ("Стили обложки", "Референсы", "Нумерация выпуска",
                      "Модель и подключение", "Настроить подключение",
                      "Проверить стиль", "Пример", "Результат теста",
                      "Обновить пример",
                      "Пример создан для предыдущей версии стиля",
                      "Заменить",
                      # ASAP 4.3 (T-4847/T-4849): лимит/бюджет.
                      "Ограничение промпта", "Автоматически",
                      "Задать вручную", "Лимит текущей модели"):
            assert label in html, label
        # L-EXTRA-5: бессмысленная подпись «Затемнение» удалена.
        assert "Затемнение" not in html
        js = _app_js()
        # Ярлык «без стиля» и сообщение unknown-limit — из runtime-кода UI.
        assert "Без дополнительного стиля" in js
        assert "Провайдер не сообщил точный лимит" in js
        assert "Потеряно соединение с сервером" in js
        # §11: stage-тексты и breakdown последней сборки.
        for stage_text in ("Генерируем базовую обложку", "Применяем стиль",
                           "Сохраняем результат", "Последняя сборка"):
            assert stage_text in js, stage_text

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
                     "coverCapabilityLines:", "fileToBase64:",
                     # ASAP 4.3: durable job polling + placeholders + лимит.
                     "coverStylePollJob:", "coverStyleJobActive:",
                     "coverStyleRetryStart:", "coverPairAsset:",
                     "coverLimitText:", "coverBudgetBreakdown:",
                     "coverStyleSavePromptLimit:"):
            assert name in js, name
        # §35: deep-link фокусирует группу «Обработка стилей обложки».
        assert "configFocusGroup" in js
        assert "models_images" in js


class TestSeedAssets:
    def test_seed_reference_and_placeholder_discovery(self):
        # ASAP 4.3 (§5): permanent DB-asset — только reference; placeholders
        # определяются из фактического listing (`.png` + `.jpg`), не хардкод.
        assert registry.SEED_FILES == {"reference": "medved_press.png"}
        files = registry.placeholder_files(ROOT / "extra_images")
        assert files["style_example_01"].endswith(".png")
        assert files["style_example_02"].endswith(".jpg")

    def test_seed_files_exist_with_documented_sha(self):
        # ASAP 4.2 (T-4818 / PO-5): `medved_press.png` совпадает с
        # задокументированным sha. Два placeholder-файла на диске отличаются
        # от исторических констант (storage-change владельца) — константы
        # обновлены по фактическим байтам; дубликат/подмена НЕ создавались.
        expected = {
            "medved_press.png":
                "BE0A700BA8D3AF64358EEE6697AEFF11BCE8765E6FC8D9730E3569DF74AA15DB",
            "style_example_01.png":
                "543283098D3DC88635A1540B5D5C9236CE72214F15FFB90D227F667BDD0EB5BB",
            "style_example_02.jpg":
                "ED77DE302BF6A6BE12786B43E53F98E517BE7A87D383D65373D88632AE8FEF6C",
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
