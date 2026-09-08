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
        """BUG-7 (невидимое поле копирования): fallback-execCommand —
        ОДИН кэшированный textarea (window.__adminbotClipGhost) с классом
        .clipboard-ghost (CSS fixed left:-9999px, opacity:0) — не ломает
        раскладку Telegram WebView и не пересоздаётся на каждый клик."""
        js, html = _js(), _html()
        assert ".clipboard-ghost" in html
        assert "position: fixed" in html
        assert "left: -9999px" in html
        assert "background: transparent !important" in html
        assert "window.__adminbotClipGhost" in js
        assert "className = 'clipboard-ghost'" in js
        assert "document.createElement('textarea')" in js


class TestRelations:
    def test_resolve_relation_name(self):
        js = _js()
        assert "resolveRelationName" in js
        assert "summaryAliasesMap" in js
        assert "avatarInitial" in js

    def test_resolve_name_format_without_at(self):
        """BUG-4 (рекон раунда 10): resolveRelationName возвращает username
        БЕЗ «@» (сервер уже снимает @; префикс — дубль с подписью); подпись
        в карточке — bare-username и только когда имя не равно username.
        Раунд 10.2: user_id как имя — НЕВОЗМОЖНО (фолбэк — пустая строка:
        id в карточке и так мелким рядом)."""
        js, html = _js(), _html()
        assert "if (u.username) return String(u.username);" in js
        assert "@' + String(u.username)" not in js
        assert "@{{ u.username }}" not in html
        assert "resolveRelationName(u) !== String(u.username)" in html
        # 10.2: без ID-фолбэка — пустая строка; имя-спан прячется при пустом
        assert "return String(u.user_id);" not in js
        assert "return '';" in js
        assert 'v-if="resolveRelationName(u)"' in html

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
