"""SAC-S1 / SAC-CORE — применимость речи и единый редактор личности.

TEST-LIFECYCLE: CONTRACT owner=SAC-01/02 (28.11.2026), slice S-SPEECH/S-CORE.

Доказывает ровно заявленный контракт:

* temperature — техническая характеристика генеративного API: её пометка
  относится только к float-значениям температуры и НЕ делает «неприменимыми»
  селектор «Свобода формулировок», личность и речь (SAC-S1-TEMP-KEY-ONLY /
  SAC-S1-CARD-STATE / SAC-S1-TEMP-INDEPENDENT);
* при reasoning-модели собранный промпт всё равно содержит Core, Identity и
  речевой слой (SAC-ACC-01 / SAC-ACC-02; ограничение было только индикацией);
* Personality Core — первый блок вкладки «Личность», отдельной страницы
  `speechSection === 'core'` нет; прежние ссылки ведут к тому же редактору;
* отдельного поля «Характер» (`system_prompt_overrides`) в основном UI нет, а
  сохранение идентичности без этого ключа не затирает legacy-значение
  (SAC-CORE-NO-MERGE / SAC-ACC-05).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from services import bot_persona, param_catalog, prompt_composer as pc

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Реальный /api/config на том же фейковом PG, что и профильный набор UR-F.
from test_ur_ui_effective_config import _hdr, client  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")

TEMPERATURE_VALUE_KEYS = (
    "limits.chat_temperature_precise",
    "limits.chat_temperature_balanced",
    "limits.chat_temperature_chatty",
)
SPEECH_PRESET_KEY = "limits.chat_temperature_preset_default"


def _config_items(test_client) -> dict:
    resp = test_client.get("/api/config", headers=_hdr())
    assert resp.status_code == 200, resp.text
    return {it["key"]: it for it in resp.json()["items"]}


def _seed_temperature_rows(test_client) -> None:
    """Как в проде: float-ключи температуры есть в сохранённых настройках.

    Фейковый PG профильного набора сидирует только пресет, поэтому значения
    температуры подаём в кэш явно — проверяется решение route-слоя, а не
    наличие строки в БД.
    """
    for key, value in zip(TEMPERATURE_VALUE_KEYS, (0.4, 0.7, 0.95)):
        test_client.cache._settings[key] = value


# ── Часть 1: temperature ↔ речь/личность ────────────────────────────────────

class TestTemperatureApplicability:
    def test_catalog_split_is_real(self):
        """Фактические pg-key: 3 float-значения температуры + str-селектор."""
        for key in TEMPERATURE_VALUE_KEYS:
            spec = param_catalog.get_by_pg_key(key)
            assert spec is not None and spec.group == "limits_temperature"
            assert spec.type == "float", key
        preset = param_catalog.get_by_pg_key(SPEECH_PRESET_KEY)
        assert preset is not None and preset.group == "limits_temperature"
        assert preset.type == "str", "селектор режима — не temperature-значение"

    def test_reasoning_model_marks_only_temperature_values(self, monkeypatch,
                                                           client):
        """RED на базе: пресет получал inactive целиком по группе."""
        _seed_temperature_rows(client)
        monkeypatch.setattr("web.api.routes._primary_model_name",
                            lambda: "o3-mini")
        items = _config_items(client)
        preset = items[SPEECH_PRESET_KEY]
        assert preset["eff"]["status"] == "active", \
            "SAC-S1-TEMP-KEY-ONLY: селектор речи не «неприменяем» из-за temperature"
        assert preset["eff"]["reason_inactive"] == ""
        for key in TEMPERATURE_VALUE_KEYS:
            eff = items[key]["eff"]
            assert eff["status"] == "inactive", key
            assert "temperature" in eff["reason_inactive"], key
            # Пометка не распространяется на личность/речь.
            assert "Personality Core" not in eff["reason_inactive"]
            assert "инструкции личности и речи" in eff["reason_inactive"]

    def test_normal_model_keeps_everything_active(self, monkeypatch, client):
        _seed_temperature_rows(client)
        monkeypatch.setattr("web.api.routes._primary_model_name",
                            lambda: "gpt-4o")
        items = _config_items(client)
        for key in (SPEECH_PRESET_KEY,) + TEMPERATURE_VALUE_KEYS:
            assert items[key]["eff"]["status"] == "active", key
            assert items[key]["eff"]["reason_inactive"] == ""

    def test_saved_values_are_not_touched(self, monkeypatch, client):
        """SAC-S1-NO-VALUE-CHANGE: значения/источники не подменяются меткой."""
        monkeypatch.setattr("web.api.routes._primary_model_name",
                            lambda: "o3-mini")
        items = _config_items(client)
        preset = items[SPEECH_PRESET_KEY]
        assert preset["value"] == "balanced"
        assert preset["source"] == "global"
        assert preset["effective_value"] == "balanced"


# ── Часть 2: payload/инспектор — инструкции реально в промпте ───────────────

class TestPromptPayload:
    def test_core_identity_and_speech_rendered_for_reasoning_model(self):
        """SAC-ACC-01/02: семейство/reasoning/temperature не вытесняют слои."""
        from test_soul1_composer_layers import DUPLICATED, IDENTITY, full_plan
        plan = full_plan()
        # Модель — reasoning-семейство и «игнорирует temperature»...
        assert param_catalog.provider_ignores_temperature("o3-mini") is True
        # ...но сборка промпта от модели не зависит: все текстовые слои на месте.
        manifest = pc.compose_prompt(plan)
        by_layer = {t.layer: t for t in manifest.layers}
        core = by_layer[pc.LAYER_CORE]
        identity = by_layer[pc.LAYER_IDENTITY]
        assert core.rendered is True and core.text
        assert identity.rendered is True and identity.text
        system = manifest.system
        assert plan.core.text in system
        assert "ХАРАКТЕР_МАРКЕР_ЯДРА" in system
        # Речевой слой (L1) тоже в payload независимо от модели ответов.
        assert plan.speech.text in system
        assert any(t.block_id == plan.speech.block_id and t.rendered
                   for t in manifest.layers)
        # Имя/биография (Identity) тоже доходят до модели.
        assert "Имя: Бот" in system
        # Дублирующийся owner-характер по-прежнему снимается один раз
        # (существующий контракт SOUL-03.6 не сломан переносом UI).
        assert system.count(DUPLICATED) == 0
        assert by_layer[pc.LAYER_IDENTITY].conflict == "duplicate_owner_character"
        # Текст identity в манифесте — без снятой дублирующей строки.
        assert IDENTITY != identity.text


# ── Часть 3: единый редактор Core на вкладке «Личность» ─────────────────────

def _persona_section() -> str:
    start = INDEX.index('id="speech-persona"')
    end = INDEX.index("</section>", start)
    return INDEX[start:end]


class TestCoreOnPersonaTab:
    def test_core_block_is_first_and_inside_persona(self):
        section = _persona_section()
        assert 'id="speech-core-editor"' in section
        # Core — ДО идентичности (первый основной блок).
        assert section.index('id="speech-core-editor"') < \
            section.index("data-speech-identity-editor")
        assert "data-speech-core-versions" in section
        assert "speechCoreDraft()" in section
        assert "saveSpeechCore()" in section
        # Отдельной страницы Core с собственным состоянием больше нет.
        assert "speechSection === 'core'" not in INDEX

    def test_legacy_entry_points_target_the_same_editor(self):
        # openSpeechSection('core') → та же вкладка «Личность» + фокус блока.
        block = APP_JS[APP_JS.index("openSpeechSection: function (id)"):]
        block = block[:block.index("_focusSpeechCore: function")]
        assert "var focusCore = id === 'core';" in block
        assert "if (focusCore) id = 'persona';" in block
        assert "this._focusSpeechCore(load);" in block
        # Ссылки «Редактор Core» в «Правилах и источниках» не удалены.
        assert 'data-speech-rules-link="core"' in INDEX
        assert "openSpeechSection('core')" in INDEX

    def test_core_data_loads_with_persona_tab(self):
        assert "_loadSpeechCore: async function" in APP_JS
        assert "if (id === 'persona' && (force || !this.speechLoaded.core))" \
            in APP_JS
        assert "await this._loadSpeechCore();" in APP_JS
        # Deep-link #/ai/persona тоже идёт через канонический загрузчик
        # (прямые присваивания speechSection обходили бы Core).
        deeplink = APP_JS[APP_JS.index("route === '#/ai/persona'"):]
        deeplink = deeplink[:deeplink.index("focusPersona")]
        assert "this.openSpeechSection('persona');" in deeplink
        # Те же endpoint/сохранение/история — второго источника нет.
        assert "this.api('/api/speech/core')" in APP_JS
        assert "saveSpeechCore: async function" in APP_JS

    def test_editor_height_and_mobile_without_global_redesign(self):
        assert ".speech-editor.speech-editor-core" in CSS
        block = CSS[CSS.index(".speech-editor.speech-editor-core"):]
        block = block[:block.index("}", block.index("{")) + 1]
        assert "min-height: 300px" in block
        assert re.search(
            r"@media \(max-width: 599px\) \{\s*"
            r"\.speech-editor\.speech-editor-core \{ min-height: 220px; \}",
            CSS)
        # Core-блок — на всю ширину контентной области (без max-width).
        core_css = CSS[CSS.index(".speech-core-block"):]
        core_css = core_css[:core_css.index("}")]
        assert "max-width: none" in core_css
        # Адаптив существующей разметки: одиночная колонка ≤599px.
        assert "@media (max-width: 599px)" in CSS


# ── Часть 4: отдельного поля «Характер» нет; legacy не затирается ───────────

class TestLegacyCharacterField:
    def test_character_field_removed_from_main_ui(self):
        section = _persona_section()
        assert "personaDraft.system_prompt_overrides" not in section
        assert "personaSetField('system_prompt_overrides'" not in section
        # Никакой замены «вторым полем характера».
        for forbidden in ("Дополнительный характер", "Расширенный Core",
                          "Переопределение личности"):
            assert forbidden not in section, forbidden
        # Legacy показывается только при фактическом наличии значения.
        assert "personaLegacyCharacterText()" in section
        assert "data-speech-legacy-character" in section
        assert "personaLegacyCharacterText: function" in APP_JS

    def test_identity_save_does_not_send_or_erase_legacy_value(self):
        js = APP_JS[APP_JS.index("savePersona: async function"):]
        js = js[:js.index("resetPersona: async function")]
        assert "system_prompt_overrides:" not in js, \
            "частичный PUT должен сохранять legacy (ключ не отправляется)"
        assert "name: this.personaDraft.name" in js
        assert "biography: this.personaDraft.biography" in js

    def test_backend_partial_patch_preserves_legacy_text(self, monkeypatch):
        """Реальный bot_persona.save_persona: нет ключа → значение не меняется."""
        existing = {
            "name": "Старое", "biography": "", "is_aware_ai": True,
            "system_prompt_overrides": "LEGACY_ХАРАКТЕР_ТЕКСТ",
            "updated_at": "2026-11-01T00:00:00+00:00",
        }
        seen = {}

        class _Conn:
            async def fetchrow(self, sql, *args):
                if sql.strip().upper().startswith("SELECT"):
                    return dict(existing)
                seen["args"] = args
                return {
                    "name": args[0], "biography": args[1],
                    "is_aware_ai": args[3], "system_prompt_overrides": args[2],
                    "updated_at": "2026-11-02T00:00:00+00:00",
                }

        class _Pool:
            def acquire(self):
                conn = _Conn()

                class _CM:
                    async def __aenter__(self):
                        return conn

                    async def __aexit__(self, *exc):
                        return False
                return _CM()

        monkeypatch.setattr(bot_persona, "_persona_pool", lambda: _Pool())
        monkeypatch.setattr(bot_persona, "set_global_name_cache",
                            lambda name: None)
        saved = __import__("asyncio").run(
            bot_persona.save_persona(None, {"name": "Новое"}))
        assert saved.name == "Новое"
        assert seen["args"][2] == "LEGACY_ХАРАКТЕР_ТЕКСТ", \
            "partial-PUT без ключа обязан сохранить legacy-значение"
        assert saved.overrides == "LEGACY_ХАРАКТЕР_ТЕКСТ"


# ── Часть 5: речь/личность без ложной «неприменимости» в карточке ───────────

def test_direct_modes_card_ignores_temperature_metadata():
    js = APP_JS[APP_JS.index("speechModeStatus: function (item)"):]
    js = js[:js.index("directModesView: function")]
    assert "status === 'no_op'" in js and "status === 'legacy'" in js
    # temperature-inactive больше не превращается в «не применяется».
    assert "eff.status === 'inactive'" not in js
    modes = APP_JS[APP_JS.index("speech: {"):]
    modes = modes[:modes.index("initiative: {")]
    assert "reason_inactive" not in modes, \
        "техническая пометка temperature не дублируется в строке карточки"
