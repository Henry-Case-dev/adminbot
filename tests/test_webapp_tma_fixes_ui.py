"""Раунд 10 (F-8, T-877 D1) — фронт-аудит UI-фиксов (маркеры).

Маркеры: 'main-header' (flex-шапка), pre code / log-panel (логи), chip-auto,
relations-резолв (resolveRelationName/avatarUrl/avatarInitial), поле
«Telegram ID админа» в access-ветке + отсутствие в reactions-ветке.
"""


def _js() -> str:
    return open("web/app.js", encoding="utf-8").read()


def _html() -> str:
    return open("web/index.html", encoding="utf-8").read()


class TestHeaderAndLogs:
    def test_main_header_flex_marker(self):
        html = _html()
        assert 'class="main-header ' in html
        assert "flex items-center gap-2" in html

    def test_logs_pre_code_mono(self):
        html = _html()
        assert "log-panel" in html
        assert '<pre v-else class="log-code break-all"><code>' in html
        assert "ui-monospace" in html          # шрифт-маркер в CSS
        assert "pre-wrap" in html
        assert "break-all" in html
        assert "max-height: 320px" in html

    def test_log_row_click_copies(self):
        """Hotfix-R10: клик по строке лога = копировать
        (@click="copyText(logText(log))"); per-line-кнопки «Скопировать»
        больше нет (осталась одна «Копировать всё»)."""
        html = _html()
        assert '@click="copyText(logText(log))"' in html
        assert ">Скопировать</button>" not in html
        assert "Копировать всё" in html
        assert "log-row" in html

    def test_log_row_expander_separate(self):
        """Hotfix-R10: разворачивание exc-трейса — отдельный компактный
        глиф (log-toggle, @click.stop) — не конфликтует с copy-кликом."""
        html = _html()
        assert "log-toggle" in html
        assert '@click.stop="log.expanded = !log.expanded"' in html
        assert "log.exc_text" in html

    def test_logs_autoscroll_to_top(self):
        """Hotfix-R10: сервер отдаёт НОВЫЕ СВЕРХУ (entries[-limit:][::-1]);
        автоскролл — panel.scrollTop = 0 (не scrollHeight к старым)."""
        js = _js()
        # «panel.scrollHeight» остался только в комментарии — сам вызов
        # scrollBottom отсутствует
        assert "panel.scrollTop = 0;" in js
        assert "panel.scrollTop = panel.scrollHeight;" not in js

    def test_copy_fallback_offscreen(self):
        """Hotfix-R10: fallback-копирования (execCommand) — textarea
        off-screen (fixed, left:-9999px, opacity:0, без размеров), чтобы
        в Telegram WebView не ломался layout."""
        js = _js()
        assert "style.left" in js
        assert "'-9999px'" in js
        assert "style.opacity = '0'" in js
        assert "style.pointerEvents = 'none'" in js


class TestRelations:
    def test_resolve_relation_name(self):
        js = _js()
        assert "resolveRelationName" in js
        assert "summaryAliasesMap" in js
        assert "avatarInitial" in js

    def test_avatar_proxy_and_initial_fallback(self):
        html = _html()
        assert "avatarInitial(u)" in html
        assert "avatarUrl" in html            # существующий прокси bdd5e89

    def test_user_id_small_in_relations(self):
        html = _html()
        assert "opacity-60" in html

    def test_chip_auto_present(self):
        html = _html()
        assert "chip-auto" in html

    def test_stage_dropdown_compact_and_note(self):
        html = _html()
        assert 'field w-32 text-xs' in html or 'w-32' in html
        assert "resize:vertical" in html
        assert "min-height:60px" in html


class TestChatTitles:
    def test_chat_profile_title_method(self):
        js = _js()
        assert "chatProfileTitle" in js

    def test_title_with_small_id(self):
        html = _html()
        assert "chatProfileTitle()" in html


class TestAdminIdMove:
    def test_hidden_in_reactions(self):
        js = _js()
        assert "isAdminIdHidden" in js
        assert "reactions.admin_user_id" in js

    def test_not_rendered_in_reactions_item(self):
        js = _js()
        assert "isAdminIdHidden" in js
        assert "!self.isAdminIdHidden" in js
        html = _html()
        assert "!isAdminIdHidden(item)" not in html

    def test_rendered_in_access(self):
        html = _html()
        assert "Telegram ID админа" in html
        assert "adminIdItem()" in html
