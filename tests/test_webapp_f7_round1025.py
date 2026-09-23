"""F7 round 10.25 — UI/инвариант-маркеры PERMsoc (ADR-1025-20 D1–D7, §60–§67).

Поведение (6 блоков, guard, round-trip единиц) реально прогоняется в
`tests/js/round1025_f7_permsoc_local_test.js`; серверные гейты — в
`tests/test_permsoc_f7_round1025.py`. Здесь — статические инварианты:
Δ каталога = 0, kill-switch, доставка ui_flags, bump, scope-заголовок.
"""
import dataclasses
import re
from pathlib import Path

from config.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = ((ROOT / "web" / "index.html").read_text(encoding="utf-8")
        + (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8"))
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")


class TestScopeAndGuard:
    def test_scope_header(self):
        assert "PERMsoc · Только этот чат" in HTML
        # полный chat_id — в конвенции .scope-tech (не вместо названия).
        assert "scope-tech" in HTML

    def test_defect_text_removed(self):
        assert "Без чата меняются только общие значения ниже" not in HTML
        assert "PERMsoc работает только для конкретного чата" in HTML

    def test_guard_local_only(self):
        assert "PERMSOC_LOCAL_KEYS" in JS
        assert "permsoc-global" in JS
        # guard применяется и в persistItems, и в saveConfigItem.
        assert JS.count("PERMSOC_LOCAL_KEYS[") >= 2

    def test_no_second_selector(self):
        # Скоп берётся из F3 (activeChatId), второго селектора нет.
        assert "activeChatId" in JS
        assert "scopeEpoch" in JS


class TestSixBlocks:
    def test_six_blocks_no_common(self):
        assert "PERMSOC_OWNER_BLOCKS" in JS
        assert "PERMSOC_BLOCK_SUBGROUPS" in JS
        # «Общее» больше не owner-блок.
        assert "id: 'common', title:" not in JS
        assert "gate: 'permsoc_reactions'" in JS
        assert "gate: 'permsoc_schedule'" in JS

    def test_master_separate_level(self):
        assert "canToggleMaster: function" in JS
        assert "permsocMasterOn()" in HTML
        assert "permsocModuleBadge(module)" in HTML

    def test_off_preserves_children(self):
        # тумблер пишет только toggleKey/gate (одна мутация).
        assert "it.value = !!checked;" in JS


class TestBlockSubgroupsRendered:
    """H-F7-1 (fix): подгруппы §62/§64/§66 — не мёртвый код, а рендер."""

    def test_render_helper_wired(self):
        assert "permsocRenderItems: function" in JS
        assert "permsocRenderItems(grp)" in HTML
        assert "__subheader" in JS and "__subheader" in HTML
        assert "permsoc-subgroup" in HTML

    def test_russian_subgroup_titles(self):
        for title in ("'Основное'", "'Контент'", "'Мимикрия'", "'Ограничения'",
                      "'Дополнительно'", "'Источники'", "'Ответы'",
                      "'Приветствия'", "'Оповещения'", "'Триггеры'",
                      "'Медиа'", "'Рассылка'", "'Доп. ограничения'"):
            assert title in JS, title


class TestOlyaIdLists:
    """M-F7-2 (§64): списки ID Оли — структурированный list-editor."""

    def test_list_widget_presentation_override(self):
        assert "PERMSOC_LIST_WIDGET_KEYS" in JS
        assert "'reactions.olya_saveasbot_channel_ids'" in JS
        assert "'reactions.olya_saveasbot_user_ids'" in JS
        assert "item.widget = 'list'" in JS
        # Δ каталога=0: правка catalog не требуется — оверрайд клиентский.
        assert "listEditorProps" in JS and "listEditorProps(item)" in HTML
        # list-editor поддерживает «ID»-подписи (variant='ids'), дефолт
        # Костика («фразы») сохранён в шаблоне.
        assert "variant: 'ids'" in JS
        assert "+ Добавить фразу" in HTML and "+ Добавить ID" in HTML
        # L-F7-8: текст лимита тоже variant-зависимый («ID», а не «фраз»).
        assert "{{ variant === 'ids' ? 'ID' : 'фраз' }}" in HTML
        # H-F7-7: сохранение ID-списков возвращает ЧИСЛОВОЙ тип (сервер
        # сравнивает `origin.chat.id` int), а не String-регрессию.
        assert "toStoredValue: function" in JS
        assert "Number.isSafeInteger" in JS


class TestKillSwitch:
    def test_env_classvar_default_on(self):
        assert ('PERMSOC_BLOCK_GATES_ENABLED: ClassVar[bool] = _env_bool('
                in SETTINGS)
        assert '"PERMSOC_BLOCK_GATES_ENABLED", True)' in SETTINGS

    def test_ui_flags_delivery_bool_only(self):
        assert ('"PERMSOC_BLOCK_GATES_ENABLED":' in ROUTES
                and "bool(settings.PERMSOC_BLOCK_GATES_ENABLED)" in ROUTES)


class TestInvariants:
    def test_catalog_delta_zero(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 469
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426

    def test_app_version_bump(self):
        m = re.search(r'APP_VERSION = "([\d.]+)"', SETTINGS)
        assert m and m.group(1) == "2.58.24", m and m.group(1)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "v2.58.24" in readme

    def test_no_second_store_or_write_path(self):
        assert JS.count("persistItems: async function") == 1
        assert JS.count("_permsocOwnerGroups: function") == 1
