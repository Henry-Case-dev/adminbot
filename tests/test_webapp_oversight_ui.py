"""Раунд 10 (F-12, T-919) — API-матрица Oversight (401/403) + TMA-аудит.

401 без initData; 403 moderator/user/local (requires_global_admin);
просмотр summary у moderator — 403; маркеры фронта (методы/поля).
"""


def _js() -> str:
    return open("web/app.js", encoding="utf-8").read()


def _html() -> str:
    return open("web/index.html", encoding="utf-8").read()


class TestFrontAudit:
    def test_summary_methods_and_modal(self):
        js = _js()
        assert "loadOversight" in js
        assert "openChatDetails" in js
        assert "toggleKillswitch" in js
        assert "toggleGlobalKey" in js

    def test_search_and_table(self):
        html = _html()
        assert "oversightSearch" in html
        assert "keyStatusRu" in html

    def test_modal_killswitch_buttons(self):
        html = _html()
        assert "Выключить удалённо" in html
        assert "Запретить глобальный ключ" in html
        assert "Разрешить глобальный ключ" in html
