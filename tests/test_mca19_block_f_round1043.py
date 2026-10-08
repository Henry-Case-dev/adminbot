"""MCA-19 Wave 1, блок F (`mca-19-image-understanding`, round 10.43) —
санкции каталога/гейтов/событий (ADR-1028-19 D13/D16/D17; spec §8.2–§8.5).

Покрытие: Δ каталога +9 → 519 с F8-переизданием (группы/вкладки/секрет),
kill-switches +4 → 80 (env-only default ON; OFF-инертности), reason_code
+12 → 269, env-only лимиты (потолки клампят каталог), вкладка mod_vision +
JS-зеркало карточки/подключения, requested-тумблер владельца.
"""
import dataclasses
import re
from pathlib import Path

import pytest

from config.settings import Settings, settings
from services import mca_events, mca_gates, param_catalog as pc

ROOT = Path(__file__).resolve().parent.parent

VISION_PG_KEYS = {
    "flags.vision_enabled",
    "models.vision_api_base_url",
    "models.vision_api_type",
    "models.vision_model",
    "keys.vision_api_key",
    "limits.vision_image_max_dimension",
    "limits.vision_queue_capacity",
    "limits.vision_user_rate",
    "limits.vision_chat_rate",
}
VISION_REASON_CODES = {
    "vision_disabled", "main_model_no_vision", "capability_check_pending",
    "vision_unsupported", "vision_unreadable", "vision_unavailable",
    "vision_failed", "vision_deferred", "vision_skipped_expired",
    "vision_rate_limited", "vision_stale_discarded", "vision_missing_source",
}
VISION_KILL_SWITCHES = {"MCA_VISION_ENABLED", "MCA_VISION_AUTO_ENABLED",
                        "MCA_VISION_BACKFILL_ENABLED",
                        "MCA_VISION_TOOL_ENABLED"}


# ── Δ каталога +9 (F8-переиздание) ──────────────────────────────────────────

def test_catalog_counts_sanctioned():
    assert len(pc.REGISTRY) == 538          # 510 → 519 (+9)
    assert len(pc.GROUPS) == 115            # 108 → 112 (+4 группы)
    assert len(pc._TAB_BY_GROUP) == 113     # 106 → 110
    assert len(pc.TAB_RULES) == 23          # 21 → 22 (mod_vision)
    # ASAP 7 (F3, §3.2): +mod_initiative (TAB_NAV/CONFIG_TAB_TITLES 22→23).
    assert len(pc.TAB_NAV) == 23
    assert len(pc.CONFIG_TAB_TITLES) == 23


def test_vision_keys_registered():
    by_key = {s.pg_key: s for s in pc.REGISTRY.values()}
    assert VISION_PG_KEYS <= set(by_key)
    # Группы и категории — ровно по санкции §8.2.
    assert by_key["flags.vision_enabled"].group == "flags_module_vision"
    assert by_key["flags.vision_enabled"].type == "bool"
    for key in ("models.vision_api_base_url", "models.vision_api_type",
                "models.vision_model"):
        assert by_key[key].group == "models_vision"
        assert by_key[key].category == "models"
    key_spec = by_key["keys.vision_api_key"]
    assert key_spec.group == "keys_vision" and key_spec.secret is True
    for key in ("limits.vision_image_max_dimension",
                "limits.vision_queue_capacity", "limits.vision_user_rate",
                "limits.vision_chat_rate"):
        assert by_key[key].group == "limits_vision"
        assert by_key[key].category == "limits"
    # flags/limits — per-chat (существующий контракт наследования), keys/models —
    # строго глобальные (секреты/маршрутизация).
    assert by_key["flags.vision_enabled"].per_chat is True
    assert key_spec.per_chat is False


def test_vision_settings_fields_exist():
    fields = {f.name for f in dataclasses.fields(Settings)}
    for name in ("VISION_ENABLED", "VISION_API_BASE_URL", "VISION_API_TYPE",
                 "VISION_MODEL", "VISION_API_KEY",
                 "VISION_IMAGE_MAX_DIMENSION", "VISION_QUEUE_CAPACITY",
                 "VISION_USER_RATE", "VISION_CHAT_RATE"):
        assert name in fields, name
    # Requested-тумблер владельца — default OFF (без согласия владельца
    # модуль не тратит vision-токены); emergency-рубильники — отдельно.
    assert settings.VISION_ENABLED is False
    # Секрет дефолтно пуст и не коммитится.
    assert settings.VISION_API_KEY == ""


def test_new_groups_on_tabs():
    assert pc.group_tab("flags_module_vision") == "mod_vision"
    assert pc.group_tab("limits_vision") == "mod_vision"
    # Подключение — «один дом» в llm_providers (прецедент models_images).
    assert pc.group_tab("models_vision") == "llm_providers"
    assert pc.group_tab("keys_vision") == "llm_providers"
    assert pc.tab_nav("mod_vision") == "modules"
    assert pc.CONFIG_TAB_TITLES["mod_vision"] == "Распознавание изображений"
    # Каждая НОВАЯ группа ровно на одной вкладке (инвариант mca-03-эры).
    vision_groups = {"flags_module_vision", "limits_vision", "models_vision",
                     "keys_vision"}
    for gid in vision_groups:
        tabs = [t for t, _ in pc.TAB_RULES if gid in pc.tab_group_ids(t)]
        assert tabs and len(set(tabs)) == 1, gid


def test_screen_map_and_registry_artifacts_regenerated():
    tsv = (ROOT / "plans/docs/param-registry-round1025.tsv").read_text(
        encoding="utf-8").splitlines()
    # ASAP 5 (asap5-final-fixes, T-5256, санкция §5): 523→529 (+6 PG-only
    # профилей embeddings) → header + 529 = 530 строк.
    assert len(tsv) == 539  # ASAP 7 F3: 529+9 → 538
    assert "flags.vision_enabled" in "\t".join(tsv)
    meta = (ROOT / "plans/docs/param-registry-round1025.meta.md").read_text(
        encoding="utf-8")
    assert "538" in meta and "411" in meta and "127" in meta


# ── Kill-switches +4 (76→80; env-only default ON; OFF-инертности) ───────────

def test_kill_switches_registry_80():
    # MCA-20 (round 10.44): 80 → 83 (+3 temporal factcheck).
    # MCA-12 (round 10.46, ADR-1028-21 §8.3): 83 → 85 (+2 MCA_STORIES_*) —
    # санкционированный bump по конвенции.
    assert len(mca_gates.KILL_SWITCHES) == 85      # 80 → 83 → 85
    assert VISION_KILL_SWITCHES <= set(mca_gates.KILL_SWITCHES)
    for name in VISION_KILL_SWITCHES:
        default, off_parity = mca_gates.KILL_SWITCHES[name]
        assert default is True and isinstance(off_parity, str) and off_parity
    # ClassVar env-only: в dataclass-поля Settings НЕ входят (Δ каталога = 0
    # для рубильников).
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert not (VISION_KILL_SWITCHES & fields)


def test_kill_switch_inertness():
    # K2/K3/K4 инертны при K1 OFF (мастер гасит под-рубильники).
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mca_gates, "vision_enabled", lambda: False)
        assert mca_gates.vision_auto_enabled() is False
        assert mca_gates.vision_backfill_enabled() is False
        assert mca_gates.vision_tool_enabled() is False
    assert mca_gates.vision_enabled() is True
    assert mca_gates.vision_auto_enabled() is True
    assert mca_gates.vision_backfill_enabled() is True
    assert mca_gates.vision_tool_enabled() is True


# ── reason_code +12 (257→269) ───────────────────────────────────────────────

def test_reason_codes_269():
    # MCA-20 (round 10.44): 269 → 279 (+10 temporal factcheck);
    # mca-17c (round 10.47): 279 → 280 (+1 oversight_job_action).
    assert len(mca_events.REASON_CODES) == 280       # 279 → 280
    assert VISION_REASON_CODES <= mca_events.REASON_CODES
    # `no_text`/`pending`/`ready` — статусы MediaAnalysis, НЕ reason-коды
    # (spec §8.5).
    assert not ({"no_text", "pending", "ready"} & mca_events.REASON_CODES)


# ── Env-only аварийные потолки (spec §8.4) ──────────────────────────────────

def test_env_limits_defaults_and_clamps():
    assert mca_gates.vision_max_bytes() == 20 * 1024 * 1024
    assert mca_gates.vision_max_pixels() == 25_000_000
    assert mca_gates.vision_download_concurrency() == 4
    assert mca_gates.vision_deferred_ttl_hours() == 24
    assert mca_gates.vision_capability_ttl_hours() == 6
    assert mca_gates.vision_reocr_budget() == 2
    with pytest.MonkeyPatch.context() as mp:
        # frozen Settings: патчим КЛАСС (прецедент summary_cover_helpers).
        mp.setattr(Settings, "MCA_VISION_MAX_BYTES", 1024)
        mp.setattr(Settings, "MCA_VISION_REOCR_BUDGET", 0)
        assert mca_gates.vision_max_bytes() == 1024
        assert mca_gates.vision_reocr_budget() == 0


# ── UI-размещение (D16): JS-зеркало карточки/вкладки/подключения ────────────

def test_js_mirrors_mod_vision():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    # Config-вкладка (паритет с CONFIG_TAB_TITLES — тест-аудит маппинга).
    assert "{ id: 'mod_vision', icon: 'visibility', label: " \
        "'Распознавание изображений'" in js
    # Карточка в существующем списке модулей + тумблер владельца.
    assert "id: 'mod_vision'" in js
    assert "toggleKey: 'flags.vision_enabled'" in js
    assert "tab: 'mod_vision'" in js
    # Блок подключения по образцу настроек моделей (адрес/тип/модель/ключ).
    assert "models.vision_api_base_url" in js
    assert "models.vision_api_type" in js
    assert "models.vision_model" in js
    assert "keys.vision_api_key" in js
    # Секрет не возвращается открытым текстом — secret:true в блоке.
    vision_block = js[js.index("id: 'vision'"):js.index("id: 'vision'") + 800]
    assert "secret: true" in vision_block
    # Канонический маршрут (симметрично images/budgets).
    assert "'#/modules/vision': 'mod_vision'" in js
    assert "mod_vision: '#/modules/vision'" in js
