"""F4 round 10.25 — структурные/маркерные инварианты (ADR-1025-14).

Покрытие:
  * контракт §37–§39: `ModuleConfigurationStore` (get/set/refresh/subscribe),
    ключ `scope_type/scope_id/module_id`, отсутствие новых библиотек/API;
  * §40–§42: одна точка мутации (`persistItems`), overlay НЕ мутирует
    `configItems` до подтверждения, применение по key+epoch;
  * §43: `moduleRuntimeNotice` — отдельный helper; `configItemNotice` (F3)
    НЕ изменён (формулировка сохранена);
  * §44/D5: `keywords` в JS `MODULES` (Δ каталога = 0);
  * D3: `runtimeGate`/`parentGate` заданы для всех 13 модулей;
  * D6: `openModuleWorkspace` → `openModuleWindow` (модалка сохранена);
  * D8/инварианты: Δ каталога = 0, нет новых state-библиотек/эндпоинтов/CDN.
"""
import dataclasses
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")


def _block(start_marker: str, end_marker: str) -> str:
    start = APP_JS.index(start_marker)
    end = APP_JS.index(end_marker, start)
    return APP_JS[start:end]


# ── §39: контракт store ─────────────────────────────────────────────────────
def test_store_api_present():
    for method in (
        "storeScope: function",
        "storeKey: function",
        "getModuleState: function",
        "setModuleState: async function",
        "refreshModuleState: async function",
        "subscribeModuleState: function",
    ):
        assert method in APP_JS, method


def test_store_key_format():
    block = _block("storeKey: function", "_moduleById: function")
    assert "type + '/' + idPart + '/' + moduleId" in block, block


def test_store_invariants_documented():
    # §38: логический ключ — scope_type + scope_id + module_id.
    assert "scope_type/scope_id/module_id" in APP_JS
    assert "_isActiveScope" in APP_JS


# ── §40/§41: одна мутация, overlay не мутирует configItems ──────────────────
def test_single_write_path():
    block = _block("setModuleState: async function", "refreshModuleState: async function")
    assert "this.persistItems(" in block, "store обязан идти через persistItems (F0)"
    assert "saveConfigItem" not in block, "не должно быть второго write-path"
    # Ровно один вызов persistItems на действие (§40).
    assert block.count("await this.persistItems(") == 1, block.count(
        "await this.persistItems(")
    # Никаких авто-повторов (§41): нет циклов retry.
    assert "retry" not in block.lower()


def test_overlay_does_not_mutate_configitems_before_save():
    block = _block("setModuleState: async function", "await this.persistItems(")
    # до await разрешена запись только в overlay/pending/error-карты
    assert "moduleOptimistic[key] = { value:" in block
    assert re.search(r"\bitem\.value\s*=", block) is None, \
        "оптимистичная мутация configItems запрещена (§D2)"


def test_apply_by_key_and_epoch():
    block = _block("setModuleState: async function", "refreshModuleState: async function")
    assert "var epoch = this.scopeEpoch;" in block, "epoch фиксируется до await"
    assert "var sameScope = (epoch === this.scopeEpoch);" in block
    assert "epoch === this.scopeEpoch" in block
    # «текущий чат на момент ответа» не читается в обработке результата
    assert "this.activeChatId" not in block.split("await this.persistItems(", 1)[1]


def test_structural_rollback_and_error_key():
    block = _block("setModuleState: async function", "refreshModuleState: async function")
    assert "moduleSaveError[key]" in block
    assert "prevValue" in block
    assert "delete this.moduleOptimistic[key]" in block


def test_inflight_guard_by_key():
    block = _block("setModuleState: async function", "refreshModuleState: async function")
    assert "this.modulePending[key]" in block
    assert "skipped: true" in block


# ── §43: moduleRuntimeNotice — отдельный helper; configItemNotice цел ───────
def test_module_runtime_notice_separate_helper():
    assert "moduleRuntimeNotice: function" in APP_JS
    notice = _block("moduleRuntimeNotice: function", "moduleStateText: function")
    assert "Не работает: отключён глобально" in notice
    assert "runtimeGate" in notice
    assert "Включено для этой области (глобально выключено)" in notice


def test_config_item_notice_unchanged():
    block = _block("configItemNotice: function", "resetChatOverride: async function")
    assert "Локально включено, хотя глобально выключено" in block
    assert "runtimeGate" not in block, "configItemNotice F3 не должен знать о модулях"


# ── D3: runtimeGate/parentGate для всех 13 модулей ─────────────────────────
def test_runtime_gate_metadata_complete():
    modules = _block("var MODULES = [", "  ];")
    assert modules.count("runtimeGate:") == 13, modules.count("runtimeGate:")
    assert modules.count("keywords:") == 13, modules.count("keywords:")
    # 9 модулей глобальные, 4 — по-чатово (аудит ADR §D3)
    assert modules.count("runtimeGate: 'per_chat'") == 4
    assert modules.count("runtimeGate: 'global'") == 9
    # родительский гейт 0a–0i — у 7 модулей (сам summary — источник гейта)
    assert modules.count("parentGate: 'flags.summary_enabled'") == 7


def test_module_titles_renamed_only_in_watch_case():
    modules = _block("var MODULES = [", "  ];")
    assert "title: 'Сводки чатов'" in modules
    assert "title: 'Ответы в чате'" in modules
    # старые названия остаются в TABS (маркеры/разделы не сломаны)
    assert "label: 'Саммаризация'" in APP_JS
    assert "label: 'Прямые ответы'" in APP_JS


# ── D4: избранное — localStorage, не конфиг ─────────────────────────────────
def test_quickpicks_localstorage():
    assert "adminbot.modules_quickpicks.v1" in APP_JS
    assert "initQuickpicks" in APP_JS
    assert "toggleQuickpick" in APP_JS
    # Избранное не ходит в /api/config (представление, §36).
    block = _block("toggleQuickpick: function", "openModuleWorkspace: function")
    assert "/api/config" not in block


# ── D6: «Настроить» → шов, модалка сохранена ────────────────────────────────
def test_open_module_workspace_seam():
    assert "openModuleWorkspace: function (m) {" in APP_JS
    assert "return this.openModuleWindow(m);" in APP_JS
    assert "openModuleWindow: function (m) {" in APP_JS
    assert "openModuleWorkspace(m)" in INDEX
    assert "openModuleWindow(m)" not in INDEX


# ── §45: счётчики и «неизвестное ≠ выключено» ───────────────────────────────
def test_counters_present():
    block = _block("moduleCounters: function", "quickpickCandidates: function")
    assert "runtime === 'on'" in block
    assert "runtime === 'off'" in block
    assert "runtime === 'unknown'" in block
    assert "noToggle" in block


# ── §44: поиск по названию/описанию/тех.имени/синонимам ─────────────────────
def test_search_haystack_fields():
    block = _block("_moduleSearchHaystack: function", "moduleEnabled: function")
    for field in ("m.title", "m.subtitle", "m.toggleKey", "m.id", "m.keywords"):
        assert field in block, field


# ── D8: инварианты окружения ────────────────────────────────────────────────
def test_catalog_delta_zero():
    import services.param_catalog as pc
    from config.settings import Settings
    assert len(pc.REGISTRY) == 469
    assert len(pc.GROUPS) == 100
    assert len(pc._TAB_BY_GROUP) == 98
    assert len(pc.TAB_RULES) == 21
    assert len({f.name for f in dataclasses.fields(Settings)}) == 426


def test_no_new_state_libraries():
    lowered = APP_JS.lower()
    for lib in ("pinia", "zustand", "redux", "@vue/reactivity", "mobx"):
        assert lib not in lowered, lib
    # CSP/zero-build: без import/require/новых CDN
    assert "require(" not in APP_JS
    assert re.search(r"^\s*import\s", APP_JS, flags=re.M) is None


def test_no_new_endpoints_and_no_cdn():
    for endpoint in ("/api/modules", "/api/module/"):
        assert endpoint not in APP_JS, endpoint
    assert "cdn." not in INDEX.lower()
    assert re.search(r'<script[^>]+src="https?://', INDEX) is None, \
        "внешний CDN-скрипт запрещён (zero-build)"


def test_grid_and_touch_css():
    assert ".module-catalog" in CSS
    assert "min-width: 44px" in CSS and "min-height: 44px" in CSS
    assert "@container (max-width: 1023px)" in CSS
