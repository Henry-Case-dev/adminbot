"""Раунд 10.8 — UI-маркеры (spec admin-ui-round108).

Покрывается:
  * §1 — переименования разделов (только видимые подписи; route-ключи целы);
  * §2 — emoji в блоках/подсекциях заменены Material-иконками;
  * §3 — регрессия логов на Android (дата, блочная раскладка, toggle-иконка,
    очистка copiedTimer);
  * §4 — «Доступы»: три подраздела отдельными route-driven окнами;
  * §5 — ровно один GLOBAL-бейдж (внутри trigger).

Все проверки — статические grep-маркеры (как остальные test_webapp_*_ui).
"""
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

# Пиктографические emoji из spec §2.2 (спецсимволы §2.3 исключены явно).
PICTOGRAPHIC = (
    "🎭", "🙈", "👁", "🧩", "📊", "🧠", "🛡", "🗑", "🌟", "🛰",
    "👥", "⚙", "💾", "📜", "📝", "🤖", "🚚", "👑", "🔄", "⏹",
    "🖥", "📈", "🔑",
)
# Спецсимволы/глифы, которые НЕ заменяются (spec §2.3).
KEEP_GLYPHS = ("✕", "⛶", "↪", "⟳", "←", "→", "▶")
# F5 (cognition-dashboard-round1013, ТЗ §5/§7): новые бейджи дашборда
# «Осмысление»/«Интеллект и Память» намеренно используют emoji владельца
# (🌙 Сон / 🌌 Глубокий сон / 💾 Лор / 📻 Ностальгия) — точечный allowlist
# поверх запрета 10.8 §2.2.
F5_COGNITION_EMOJI = ("🌙", "🌌", "💾", "📻")


def _rule(selector: str) -> str:
    start = HTML.index(selector)
    end = HTML.index("}", start)
    return HTML[start:end]


class TestRenames108:
    OLD_LABELS = (
        "label: 'Как это работает'", "label: 'Настройки AI'",
        "label: 'Функции PERMsoc'", "label: 'Доступы и Роли'",
        "label: 'Oversight'",
        "«Как это работает»", "«Настройки AI»", "«Функции PERMsoc»",
        "«Доступы и Роли»",
    )
    NEW_LABELS = ("label: 'Справка'", "label: 'ИИ'", "label: 'PERMsoc'",
                  "label: 'Доступы'", "label: 'Сводка'")

    def test_old_labels_gone(self):
        for old in self.OLD_LABELS:
            assert old not in JS, old
            assert old not in HTML, old

    def test_new_labels_present(self):
        for new in self.NEW_LABELS:
            assert new in JS, new

    def test_route_keys_unchanged(self):
        for key in ("'#/how'", "'#/ai'", "'#/permsoc'", "'#/access'",
                    "'#/oversight'"):
            assert key in JS, key
        # hub-заголовки под новыми подписями (route-ключ тот же).
        assert "title: 'ИИ'" in JS
        assert "title: 'Доступы'" in JS
        # «Роли» — карточка/окно вместо «Администраторов».
        assert "title: 'Роли'" in JS
        assert "title: 'Администраторы'" not in JS

    def test_catalog_group_not_renamed(self):
        from services import param_catalog as pc
        by_id = {g.id: g for g in pc.GROUPS}
        assert by_id["flags_permsoc"].title_ru == "Функции PERMsoc: рубильники"


class TestEmojiToIcons108:
    def test_no_pictographic_emoji_in_web(self):
        for glyph in PICTOGRAPHIC:
            if glyph in F5_COGNITION_EMOJI:
                continue   # F5/§5: emoji-бейджи спецификации владельца
            assert glyph not in HTML, ("index.html", glyph)
            assert glyph not in JS, ("app.js", glyph)

    def test_special_glyphs_kept(self):
        for glyph in KEEP_GLYPHS:
            assert glyph in HTML, glyph

    def test_new_icon_names_used(self):
        # F6: `trending_up` больше не рендерится в HTML — линейный график
        # аптайма удалён (заменён SVG-EKG); маппинг в app.js ICONS сохранён.
        for name in ("visibility", "visibility_off", "shield",
                     "delete", "settings", "save", "edit_note", "swap_horiz",
                     "stop", "play_arrow", "dns", "key",
                     "receipt_long", "chevron_right", "expand_more"):
            assert ("'%s'" % name) in HTML, name
            assert (name + ":") in JS, name
        assert "trending_up:" in JS   # маппинг иконки не удалён
        # 10.9: psychology больше не рендерится статикой в HTML (иконка
        # owner-блока «Мимикрия» приходит из PERMSOC_OWNER_BLOCKS в JS).
        assert "psychology:" in JS
        assert "'psychology'" in JS
        assert "iconGlyph(keyReveal[item.key] ? 'visibility_off' : 'visibility')" in HTML

    def test_logs_toggle_uses_material_icon(self):
        assert "iconGlyph(log.expanded ? 'expand_more' : 'chevron_right')" in HTML
        assert "log-toggle-spacer" in HTML


class TestGlobalBadge108:
    def test_single_scope_label(self):
        assert HTML.count("{{ scopeLabel }}") == 1

    def test_outer_badge_removed(self):
        assert 'class="badge badge-muted shrink-0">{{ scopeLabel }}' not in HTML
        # внутренний бейдж и #id-бейдж сохранены
        assert ':class="scopeKind === \'global\' ? \'badge-muted\' : \'badge-info\'"' in HTML
        assert "isChatContext()" in HTML


class TestLogsAndroid108:
    def test_fmt_log_time_has_date(self):
        start = JS.index("fmtLogTime: function")
        body = JS[start:JS.index("fmtTs: function", start)]
        assert "d.getDate()" in body and "d.getMonth()" in body
        assert "pad(d.getDate())" in body

    def test_log_code_block_layout(self):
        assert '<div v-else class="log-code">' in HTML
        assert "<pre" not in HTML.split('class="log-code"')[0][-60:]
        code = _rule(".log-code {")
        assert "break-all" not in code
        assert "pre-wrap" not in code
        assert "word-break: normal" in code

    def test_log_msg_full_width_wraps(self):
        msg = _rule(".log-msg {")
        assert "width: 100%" in msg
        assert "overflow-wrap: anywhere" in msg
        assert "word-break: break-word" in msg

    def test_log_head_wraps(self):
        head = _rule(".log-head {")
        assert "flex-wrap: wrap" in head

    def test_toggle_only_with_exc_text(self):
        assert 'v-if="log.exc_text" class="log-toggle' in HTML
        assert "log-toggle-spacer" in HTML

    def test_copied_timer_cleared_on_tab_switch(self):
        body = JS[JS.index("setTab: function (id)"):]
        body = body[:body.index("prevTab")] if "prevTab" in body else body[:800]
        assert "clearTimeout(this.copiedTimer)" in body
        assert "this.copiedIndex = null" in body

    def test_no_hard_width_columns(self):
        assert "min-width: 4.5rem" not in HTML
        assert "width: 8ch" not in HTML
        assert "max-width: 8rem" not in HTML


class TestAccessWindows108:
    def _access(self) -> str:
        start = HTML.index("activeTab === 'access'")
        end = HTML.index("activeTab === 'relations'", start)
        return HTML[start:end]

    def test_three_windows(self):
        access = self._access()
        assert access.count('class="modal-backdrop"') == 3
        for win in ("roles", "local", "admins"):
            assert ("v-if=\"isAccessOpen('%s')\"" % win) in access, win

    def test_window_methods(self):
        assert "openAccessWindow: function (id)" in JS
        assert "closeAccessWindow: function ()" in JS
        assert "setAccess" not in JS
        for win in ("roles", "local", "admins"):
            assert ("openAccessWindow('%s')" % win) in HTML, win
        assert "closeAccessWindow()" in HTML

    def test_no_accordion(self):
        assert 'class="acc-head"' not in HTML
        assert 'role="tabpanel"' not in HTML
        assert "setAccess(" not in HTML

    def test_section_ids_kept(self):
        for sec in ('id="sec-roles"', 'id="sec-matrix"', 'id="sec-local"',
                    'id="sec-admins"'):
            assert sec in HTML, sec

    def test_inner_admins_renamed_to_roles(self):
        access = self._access()
        assert ">Роли</h2>" in access          # заголовок окна #/access/admins
        assert '<div class="text-sm font-bold mb-2">Роли</div>' in access
        # старого заголовка-подраздела «Администраторы» нет
        assert ">Администраторы</div>" not in access

    def test_always_visible_cards_kept(self):
        access = self._access()
        assert "Мой доступ" in access
        assert "Telegram ID админа" in access

    def test_apply_route_normalizes_access(self):
        body = JS[JS.index("applyRoute: function"):]
        body = body[:body.index("navigateTo: function")]
        assert "this.accessOpen = route.indexOf('#/access/') === 0" in body


class TestCacheBustAndEsc108:
    """R10.8-5 (cache-bust субсета) и R10.8-1 (Esc закрывает окна)."""

    def test_font_url_versioned(self):
        # R10.8-5: .woff2 отдаётся max-age=86400 → URL должен нести ?v=,
        # иначе до 24ч клиент держит старый 10.7-субсет (tofu новых глифов).
        assert ("/static/fonts/material-symbols-rounded.woff2"
                "?v=__APP_VERSION__") in HTML
        assert "app.js?v=__APP_VERSION__" in HTML

    def test_app_version_matches_readme(self):
        # R10.8-5: APP_VERSION и шапка README не разъезжаются.
        from config.settings import APP_VERSION
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert ("v" + APP_VERSION) in readme, APP_VERSION

    def test_global_esc_handles_access_window(self):
        # R10.8-1: глобальный Esc → escClose (модуль приоритетнее, затем access).
        assert "escClose: function ()" in JS
        assert "_appVm.escClose()" in JS
        assert ("if (this.accessOpen != null) { this.closeAccessWindow(); }"
                in JS)
