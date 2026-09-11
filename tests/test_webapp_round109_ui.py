"""Раунд 10.9 (admin-ui-round109) — UI-маркеры + каталог-инварианты.

Покрывается:
  * п.1 — PERMsoc: 4 owner-блока, один тумблер в <summary>, SLAVIK_ENABLED;
  * п.3 — скролл: _preserveScroll + большой спиннер только на первой загрузке;
  * п.4 — описания/заголовки без жаргона, непустые, без AI-шаблона;
  * п.5/п.6 — «Тяжёлые фичи» удалены, «Бюджет фона» переехал в «Сводку»;
  * п.7.1 — один блок «Доступность ключей», 4 группы, реальный health
    (в т.ч. STT-проб через /audio/transcriptions);
  * п.7.2 — «Название модели» первым полем + max-w-3xl;
  * п.8 — градиент чуть быстрее.

Все проверки — статические grep-маркеры (как test_webapp_round108_ui).
"""
import re
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CATALOG = (ROOT / "services" / "param_catalog.py").read_text(encoding="utf-8")
PERMSOC = (ROOT / "services" / "permsoc.py").read_text(encoding="utf-8")
STATUS = (ROOT / "services" / "status_service.py").read_text(encoding="utf-8")
PROBE = (ROOT / "services" / "llm_probe.py").read_text(encoding="utf-8")

# §4.2.2: запрещённые подстроки в title_ru/description (нижний регистр).
# MEDIUM-3: правило применяется и к заголовкам, и к описаниям (§4.3).
FORBIDDEN = (
    "rag", "llm", "stt", "tts", "api", "json", "токен", "ttl", "backoff",
    "jitter", "mmr", "wal", "hmac", "ssrf", "ddl", "regex", "cron",
    "semaphore", "url", "cookie", "webhook", "prompt", "embedding", "id8",
    "vector", "graphrag", "дайджест",
)


class TestPermsocOwnerBlocks:
    def test_owner_blocks_constant(self):
        assert "PERMSOC_OWNER_BLOCKS" in JS
        assert "owner-block" in JS
        assert "PERMSOC_TOGGLE_KEYS" in JS
        for toggle in ("flags.slavik_enabled", "flags.olya_enabled",
                       "flags.mimic_enabled", "flags.permsoc_enabled"):
            assert toggle in JS, toggle

    def test_single_toggle_in_summary(self):
        # Ровно один тумблер в <summary> owner-блока (generic-bool исключён).
        assert "<summary v-if=\"grp.owner\"" in HTML
        assert ":checked=\"permsocOwnerOn(grp.owner)\"" in HTML
        assert "@change.stop=\"toggleOwner(grp.owner, $event.target.checked)\"" in HTML
        assert "toggleOwner: async function" in JS
        assert "permsocOwnerOn: function" in JS
        assert "canToggleOwner: function" in JS

    def test_master_map_removed(self):
        # Старая отдельная мастер-карта удалена.
        assert "activeTab === 'permsoc'" not in HTML
        assert "master: {{ permsocMasterOn()" not in HTML

    def test_backend_slavik_sub_flag(self):
        assert "SLAVIK_ENABLED" in CATALOG
        assert "flags.slavik_enabled" in PERMSOC
        assert '"flags.slavik_enabled": True' in PERMSOC
        assert "GroupSpec(\"reactions_persons\"" not in CATALOG

    def test_common_block_module_summary(self):
        # Сводка 5 модулей жила в удалённой мастер-карте — переехала
        # внутрь owner-блока «Общее / Мастер» (spec §1.2/§1.3) и снова
        # использует permsocModuleBadge (не мёртвый код).
        assert "grp.owner.id === 'common'" in HTML
        assert "permsocModuleBadge(module)" in HTML

    def test_all_four_owner_blocks_always_render(self):
        # LOW-6: owner-блоки не фильтруются по items.length — рендерятся ВСЕ
        # 4, даже если тело пустое (единственный тумблер в <summary>).
        assert "grp.owner || basicItems(grp).length || advancedItems(grp).length" in HTML
        assert "PERMSOC_OWNER_BLOCKS.map" in JS
        assert "result.filter(function (r) { return r.items.length > 0; })" not in JS


class TestScrollFix:
    def test_spinner_only_first_load(self):
        assert "v-if=\"configLoading && !configItems.length\"" in HTML

    def test_preserve_scroll_helper(self):
        assert "_preserveScroll: async function" in JS
        assert "_preserveScroll(this.loadConfig)" in JS
        # все save-пути используют helper
        for marker in ("this.toast('Сохранено: ' + b.title",
                       "this.toast('Сохранено: ' + item.title",
                       "this.toast('Ключ обновлён: '"):
            idx = JS.index(marker)
            chunk = JS[idx:idx + 400]
            assert "_preserveScroll(this.loadConfig)" in chunk, marker

    def test_preserve_scroll_covers_area_and_missing_saves(self):
        # MEDIUM-4: TMA-fullscreen скроллит main.scroll-area — helper обязан
        # снимать/восстанавливать и его.
        assert "querySelector('.scroll-area')" in JS
        # kv-editor save и resetChatOverride (обычная + 409-ветка) обёрнуты.
        assert "this.root._preserveScroll(this.root.loadConfig)" in JS
        assert JS.count("_preserveScroll(this.loadConfig)") >= 6


class TestDescriptions:
    def _params(self):
        from services import param_catalog as pc
        return [s for s in pc.REGISTRY.values() if s.category is not None]

    def test_no_forbidden_jargon(self):
        # MEDIUM-3: и title_ru, и description (spec §4.3).
        from services import param_catalog as pc
        def bad(text: str) -> list:
            low = (text or "").lower()
            return [f for f in FORBIDDEN if f in low]
        for g in pc.GROUPS:
            assert not bad(g.title_ru), (g.id, g.title_ru)
            assert not bad(g.description), (g.id, g.description)
        for spec in self._params():
            assert not bad(spec.title_ru), (spec.pg_key, spec.title_ru)
            assert not bad(spec.description), (spec.pg_key, spec.description)

    def test_no_ai_template_pattern(self):
        # HIGH-2: запрещён шаблон «Включает… Выключено — …» (spec §4.2.3/§4.2.4).
        from services import param_catalog as pc
        pattern = re.compile(r"включ\w*.*выключ", re.IGNORECASE | re.DOTALL)
        for spec in self._params():
            assert not pattern.search(spec.description or ""), (
                spec.pg_key, spec.description)

    def test_descriptions_nonempty(self):
        from services import param_catalog as pc
        for g in pc.GROUPS:
            assert g.description.strip(), g.id
            assert g.title_ru.strip(), g.id
        for spec in self._params():
            assert spec.description.strip(), spec.pg_key
            assert spec.title_ru.strip(), spec.pg_key


class TestHeavyAndBudgetMoves:
    def test_heavy_features_removed(self):
        assert "Тяжёлые фичи" not in HTML
        assert "optInCount" not in JS
        assert "whoCanToggle" not in JS

    def test_budget_moved_to_oversight(self):
        assert "Бюджет фона (день)" in HTML
        assert "Сегодня расхода ещё не было" in HTML
        # loadBudgetInfo вызывается из loadOversight, но НЕ из loadModules.
        ov = JS[JS.index("loadOversight: async function"):][:700]
        assert "loadBudgetInfo()" in ov
        mod = JS[JS.index("loadModules: async function"):]
        mod = mod[:mod.index("toggleGate:")]
        assert "loadBudgetInfo" not in mod


class TestKeyAvailabilityBlock:
    def test_one_block_four_groups(self):
        assert "Доступность ключей" in HTML
        assert "llmGroups" in JS
        assert "История доступности ключей" in HTML   # старый заголовок переименован

    def test_real_health_backend(self):
        assert "probe_openai" in PROBE
        assert "_ping_provider" in STATUS
        assert "GROUP_LLM" in STATUS and "GROUP_EMB" in STATUS
        assert "emb_main" in STATUS and "video_openrouter" in STATUS
        # CRITICAL-1: STT-проб идёт на /audio/transcriptions, а не chat.
        assert "audio/transcriptions" in PROBE
        assert '"groq", "stt"' in STATUS       # stt_groq kind="stt"
        assert "POST /audio/transcriptions" in PROBE

    def test_no_hardcoded_provider_names(self):
        start = HTML.index("Доступность ключей")
        block = HTML[start:start + 2500]
        for bad in ("deepseek", "deepseek_fallback"):
            assert bad not in block


class TestProviderForm:
    def test_display_name_first_field(self):
        for block in ("direct_main", "direct_fallback", "transcribe_groq",
                      "transcribe_openrouter", "video_summary_openrouter",
                      "embeddings"):
            i = JS.index("id: '%s'" % block)
            chunk = JS[i:JS.index("] }", i)]
            first = chunk.index("key: 'models.")
            assert "display_name" in chunk[first:first + 60], block

    def test_form_width_constrained(self):
        assert "max-w-3xl mx-auto w-full" in HTML


class TestGradient109:
    def test_faster_gradient(self):
        assert "--grad-speed:14s" in HTML
        assert "animation: grad-drift 18s" in HTML
        # reduced-motion/contrast сохранены
        assert "prefers-reduced-motion" in HTML
        assert "prefers-contrast" in HTML


class TestCatalog109:
    def test_counts(self):
        import dataclasses
        from config.settings import Settings
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 400
        assert len(pc.GROUPS) == 90
        assert len(pc._TAB_BY_GROUP) == 88
        assert len(pc.TAB_RULES) == 19
        assert len({f.name for f in dataclasses.fields(Settings)}) == 372
