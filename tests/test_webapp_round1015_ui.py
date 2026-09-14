"""F5 `status-graph-ui-relocation-round1015` — релокация статистики графа
(ТЗ §4) + редизайн бейджей Сна/Глубокого сна (ТЗ §5 + UPD §3, оконная
семантика).

Покрытие (spec §9):
  * UI-маркеры index.html: карточка ушла из «Модулей», метрики графа — в
    консолидированном блоке «Сводки», нет «пробуждение ~», `.intel-header`
    + CSS media-столбик;
  * UI-маркеры app.js: новые тексты/иконки бейджей, `.glow` только в фазе,
    удалён неиспользуемый `loadCognitionStats`;
  * API `cognition/status`: аддитивные `active`/`active_until` для `dream`
    и `deep_sleep`; старые поля (`next_wake_at`/`next_run_at`) сохранены;
  * юнит `_in_hour_window` (окно 4–6, wrap через полночь, границы).
"""
import datetime
import types
from pathlib import Path

import pytest

ROOT = Path(".")
# F4 10.16: CSS-канон вынесен в app.css — static-маркеры читают разметку+стили.
HTML = ((ROOT / "web" / "index.html").read_text(encoding="utf-8")
        + (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8"))
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


# ── юнит: оконная семантика (чистый хелпер) ────────────────────────────────

class TestInHourWindow:
    def test_window_4_6(self):
        from web.api import memory_agi as ma
        assert ma._in_hour_window(3, 4, 6) is False
        assert ma._in_hour_window(4, 4, 6) is True       # start включён
        assert ma._in_hour_window(5, 4, 6) is True
        assert ma._in_hour_window(6, 4, 6) is False      # end исключён
        assert ma._in_hour_window(7, 4, 6) is False

    def test_wrap_midnight(self):
        from web.api import memory_agi as ma
        assert ma._in_hour_window(23, 22, 6) is True
        assert ma._in_hour_window(0, 22, 6) is True
        assert ma._in_hour_window(5, 22, 6) is True
        assert ma._in_hour_window(6, 22, 6) is False
        assert ma._in_hour_window(21, 22, 6) is False

    def test_empty_window(self):
        from web.api import memory_agi as ma
        assert ma._in_hour_window(5, 5, 5) is False

    def test_local_hour(self):
        from web.api import memory_agi as ma
        base = datetime.datetime(2026, 9, 14, 5, 30,
                                 tzinfo=datetime.timezone.utc).timestamp()
        assert ma._local_hour(base, "UTC") == 5


# ── API: аддитивные поля активной фазы ─────────────────────────────────────

class _FakeDb:
    async def last_run_at(self, kinds):
        return None

    async def last_deep_run(self):
        return None

    async def count_dream_log(self, today, kind=None):
        return 0

    async def sum_dream_tokens(self, today):
        return 0


async def _status(monkeypatch, fake_now: float, extra_hot: dict | None = None):
    from web.api import memory_agi as ma
    monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(ma, "_db_or_503", lambda: _FakeDb())
    # TZ фиксируем UTC, иначе дефолт Asia/Yekaterinburg смещает час.
    hotmap = {"limits.summary_timezone": "UTC"}
    hotmap.update(extra_hot or {})
    monkeypatch.setattr(ma.hot, "get",
                        lambda key, default=None: hotmap.get(key, default))
    monkeypatch.setattr(ma, "time",
                        types.SimpleNamespace(time=lambda: fake_now))
    return await ma.cognition_status(request=None, user=None, chat_id=None)


class TestCognitionStatusAdditive:
    @pytest.mark.asyncio
    async def test_fields_present_and_additive(self, monkeypatch):
        # 05:00 UTC — внутри дефолтного окна сна 4–6.
        fixed = datetime.datetime(2026, 9, 14, 5, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        data = await _status(monkeypatch, fixed)
        d, de = data["dream"], data["deep_sleep"]
        for field in ("active", "active_until"):
            assert field in d, field
            assert field in de, field
        # аддитивность: существующие поля не тронуты (S10.13-5).
        assert isinstance(d["next_wake_at"], int)
        assert isinstance(de["next_run_at"], int)
        assert isinstance(d["running"], bool)
        assert isinstance(de["running"], bool)
        assert d["state"] in ("sleep", "synthesizing", "limit_exhausted")

    @pytest.mark.asyncio
    async def test_active_in_window(self, monkeypatch):
        fixed = datetime.datetime(2026, 9, 14, 5, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        data = await _status(monkeypatch, fixed, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True})
        d, de = data["dream"], data["deep_sleep"]
        assert d["enabled"] is True
        assert d["active"] is True
        assert d["active_until"] == ma_end(6, fixed)
        # after_sleep-триггер: глубокая фаза живёт в том же окне.
        assert de["active"] is True
        assert de["active_until"] == d["active_until"]

    @pytest.mark.asyncio
    async def test_disabled_dream_not_active_in_window(self, monkeypatch):
        """Review-fix H1: модуль выключен + мы внутри окна → active=false."""
        fixed = datetime.datetime(2026, 9, 14, 5, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        data = await _status(monkeypatch, fixed, {"memory.dream_enabled": False})
        d = data["dream"]
        assert d["enabled"] is False
        assert d["active"] is False
        assert d["active_until"] is None

    @pytest.mark.asyncio
    async def test_disabled_deep_not_active_in_window(self, monkeypatch):
        """Review-fix H1: выключенный глубокий сон в окне → active=false."""
        fixed = datetime.datetime(2026, 9, 14, 5, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        data = await _status(monkeypatch, fixed,
                             {"flags.deep_sleep_enabled": False})
        de = data["deep_sleep"]
        assert de["enabled"] is False
        assert de["active"] is False
        assert de["active_until"] is None

    @pytest.mark.asyncio
    async def test_disabled_fixed_deep_not_active(self, monkeypatch):
        """Review-fix H1: fixed-триггер выключен в свой час → active=false."""
        fixed = datetime.datetime(2026, 9, 14, 7, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        data = await _status(
            monkeypatch, fixed,
            {"memory.deep_sleep_trigger": "fixed",
             "flags.deep_sleep_enabled": False})
        de = data["deep_sleep"]
        assert de["enabled"] is False
        assert de["active"] is False
        assert de["active_until"] is None

    @pytest.mark.asyncio
    async def test_inactive_outside_window(self, monkeypatch):
        fixed = datetime.datetime(2026, 9, 14, 8, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        data = await _status(monkeypatch, fixed)
        d, de = data["dream"], data["deep_sleep"]
        assert d["active"] is False
        assert d["active_until"] is None
        assert de["active"] is False
        assert de["active_until"] is None

    @pytest.mark.asyncio
    async def test_running_outside_window_still_active(self, monkeypatch):
        """Ручной запуск вне окна → active=True, но active_until=null
        (fallback «Сон идёт» — spec §4)."""
        from web.api import memory_agi as ma

        class _W:
            dream_running = True
            deep_running = False

        fixed = datetime.datetime(2026, 9, 14, 8, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        monkeypatch.setattr(ma.lore_runtime, "get_dream_worker",
                            lambda: _W())
        data = await _status(monkeypatch, fixed)
        assert data["dream"]["active"] is True
        assert data["dream"]["active_until"] is None
        assert data["deep_sleep"]["active"] is False

    @pytest.mark.asyncio
    async def test_fixed_deep_trigger(self, monkeypatch):
        fixed = datetime.datetime(2026, 9, 14, 7, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        data = await _status(
            monkeypatch, fixed,
            {"memory.deep_sleep_trigger": "fixed",
             "flags.deep_sleep_enabled": True})
        de = data["deep_sleep"]
        assert de["active"] is True
        assert de["active_until"] == ma_end(8, fixed)


def ma_end(hour: int, now: float) -> int:
    """Ожидаемый epoch HH:00 UTC (позитивный день фиксированной даты)."""
    from web.api import memory_agi as ma
    return ma._next_hour_epoch(hour, "UTC", now)


# ── UI-маркеры ─────────────────────────────────────────────────────────────

class TestUiMarkersRelocation:
    def test_modules_card_removed(self):
        # §4: карточка ушла из «Модулей», у карточки больше нет загрузчика.
        assert "Статистика графа памяти" not in HTML
        assert "loadCognitionStats" not in JS
        assert "loadCognitionStats()" not in HTML

    def test_summary_consolidated_metrics(self):
        block = _block(HTML, "Интеллект и Память", "timeline-list")
        for marker in ("cognitionStats.facts", "cognitionStats.beliefs",
                       "cognitionStats.protected_facts",
                       "cognitionStats.paradigms", "cognitionStats.graph_nodes",
                       "cognitionStats.graph_edges",
                       "cognitionStats.relation_types", "cognitionStats.memes"):
            assert marker in block, marker
        # без дубля карточки: каждая метрика ровно один раз.
        assert block.count("Узлов:") == 1
        assert block.count("Типов связей:") == 1
        assert block.count("Мемов:") == 1

    def test_no_wakeup_free_text(self):
        assert "пробуждение ~" not in HTML


class TestUiMarkersBadges:
    def test_badge_texts_and_glow(self):
        assert "🌙 Сон до " in JS
        assert "🌙 Сон идёт" in JS
        assert "☀️ Сон через " in JS
        assert "☀️ Лимит сна исчерпан" in JS
        assert "🌅 Глубокий сон через " in JS
        assert "🌌 Глубокий сон до " in JS
        assert "🌌 Глубокий сон идёт" in JS
        # round1017 (F3): ветка «выключен» устранена, вне фазы — остаток.
        assert "Сон выключен" not in JS
        assert "Глубокий сон выключен" not in JS
        assert "fmtCountdown: function" in JS
        assert "fmtCountdown(Number(d.next_wake_at) - now)" in JS
        assert "fmtCountdown(Number(d.next_run_at) - now)" in JS
        assert "'badge-ok glow'" in JS
        assert "'badge-info glow'" in JS

    def test_summary_badge_no_duplicate_time(self):
        block = _block(HTML, "Интеллект и Память", "timeline-list")
        assert "· {{ fmtClock(cognition.dream.next_wake_at) }}" not in block


class TestUiMarkersMobileColumn:
    def test_intel_header_markup(self):
        assert 'class="intel-header mb-2"' in HTML
        assert 'class="intel-title text-sm font-bold"' in HTML

    def test_intel_header_css(self):
        assert ".intel-header { display: flex; flex-wrap: wrap; " \
               "gap: .5rem; align-items: center; }" in HTML
        assert ("@media (max-width: 640px) {\n      .intel-header "
                "{ flex-direction: column; align-items: flex-start; }"
                ) in HTML
        assert ".intel-header .intel-title { width: 100%; }" in HTML

    def test_mobile_order(self):
        # в шапке порядок: заголовок → бейдж Сна → бейдж Глубокого сна.
        block = _block(HTML, 'class="intel-header mb-2"', "cognition-ribbons")
        assert block.index("intel-title") < block.index("dreamPhaseBadge")
        assert block.index("dreamPhaseBadge") < block.index("deepPhaseBadge")
