"""F3 `sleep-badge-countdown-round1017` — бейджи Сна: «через остаток»
(вне фазы, в т.ч. enabled=false) и «до HH:MM» (.glow, активная фаза).

Покрытие (spec §4):
  * статический контракт `web/app.js`: хелпер `fmtCountdown`, тексты бейджей,
    отсутствие ветки «выключен», эмодзи `☀️/🌙/🌅/🌌` не изменены;
  * `fmtCountdown`/бейджи (границы, кламп, `—`, `enabled=false`, `active`,
    `limit_exhausted`) — JS-юнитами в `tests/js/routing_test.js` (гейт
    `node tests/js/routing_test.js` → `JS-UNIT-OK`);
  * API `cognition/status` не изменён: используются существующие поля;
  * маркер-тест 10.15 обновлён (нет «выключен»).
"""
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
MEMORY_AGI = (ROOT / "web" / "api" / "memory_agi.py").read_text(encoding="utf-8")
ROUTING_TEST = (ROOT / "tests" / "js" / "routing_test.js").read_text(
    encoding="utf-8")
ROUND1015 = (ROOT / "tests" / "test_webapp_round1015_ui.py").read_text(
    encoding="utf-8")


def _badge_block(name: str) -> str:
    start = JS.index(name + ": function")
    end = JS.index("},", start) + 2
    return JS[start:end]


# ── fmtCountdown (статический контракт) ─────────────────────────────────────

class TestFmtCountdownMarker:
    def test_helper_present(self):
        assert "fmtCountdown: function" in JS

    def test_helper_semantics(self):
        block = JS[JS.index("fmtCountdown: function"):]
        block = block[:block.index("fmtClock: function")]
        assert "seconds == null" in block
        assert "isNaN(s)" in block
        assert "if (s < 0) s = 0;" in block          # кламп ≥ 0
        assert "Math.floor(s / 60)" in block          # округление вниз
        assert "'—'" in block                         # фоллбэк

    def test_fmt_clock_preserved(self):
        assert "fmtClock: function" in JS


# ── Бейджи: тексты/классы ───────────────────────────────────────────────────

class TestDreamBadge:
    def test_out_of_phase_countdown(self):
        block = _badge_block("dreamPhaseBadge")
        assert "'☀️ Сон через '" in block
        assert "fmtCountdown(Number(d.next_wake_at) - now)" in block
        assert "cls: 'badge-muted'" in block

    def test_active_phase_glow(self):
        block = _badge_block("dreamPhaseBadge")
        assert "'🌙 Сон до ' + this.fmtClock(d.active_until)" in block
        assert "'badge-ok glow'" in block
        assert "'🌙 Сон идёт'" in block

    def test_limit_exhausted_preserved(self):
        block = _badge_block("dreamPhaseBadge")
        assert "d.state === 'limit_exhausted'" in block
        assert "'☀️ Лимит сна исчерпан'" in block
        assert "'badge-warn'" in block

    def test_no_disabled_branch(self):
        block = _badge_block("dreamPhaseBadge")
        assert "enabled" not in block
        assert "выключен" not in block


class TestDeepBadge:
    def test_out_of_phase_countdown(self):
        block = _badge_block("deepPhaseBadge")
        assert "'🌅 Глубокий сон через '" in block
        assert "fmtCountdown(Number(d.next_run_at) - now)" in block
        assert "cls: 'badge-muted'" in block

    def test_active_phase_glow(self):
        block = _badge_block("deepPhaseBadge")
        assert "'🌌 Глубокий сон до '" in block
        assert "'badge-info glow'" in block
        assert "'🌌 Глубокий сон идёт'" in block

    def test_no_disabled_branch(self):
        block = _badge_block("deepPhaseBadge")
        assert "enabled" not in block
        assert "выключен" not in block


class TestNowSource:
    def test_server_generated_at(self):
        assert "Number(c.generated_at) || Math.floor(Date.now() / 1000)" in JS

    def test_both_badges_use_server_now(self):
        assert _badge_block("dreamPhaseBadge").count(
            "Number(c.generated_at)") == 1
        assert _badge_block("deepPhaseBadge").count(
            "Number(c.generated_at)") == 1


# ── Эмодзи не тронуты ───────────────────────────────────────────────────────

class TestEmojiUnchanged:
    def test_all_phase_emoji_present(self):
        for emoji in ("☀️", "🌙", "🌅", "🌌"):
            assert emoji in JS, emoji

    def test_disabled_texts_removed(self):
        assert "Сон выключен" not in JS
        assert "Глубокий сон выключен" not in JS


# ── API не изменён: используются существующие поля ──────────────────────────

class TestApiUnchanged:
    def test_generated_at_present(self):
        assert '"generated_at": int(now)' in MEMORY_AGI

    def test_required_fields_present(self):
        for field in ('"next_wake_at"', '"next_run_at"', '"active_until"',
                      '"active"'):
            assert field in MEMORY_AGI, field


# ── JS-юниты покрывают F3 (гейт node tests/js/routing_test.js) ──────────────

class TestJsUnitCoverage:
    def test_routing_test_covers_f3(self):
        assert "sleep-badge-countdown-round1017" in ROUTING_TEST
        assert "fmtCountdown" in ROUTING_TEST
        assert "dreamPhaseBadge" in ROUTING_TEST
        assert "deepPhaseBadge" in ROUTING_TEST

    def test_routing_test_has_countdown_cases(self):
        assert "fmtCountdown(8100)" in ROUTING_TEST
        assert "'2ч 15м'" in ROUTING_TEST
        assert "'0м'" in ROUTING_TEST


# ── Обновлённый маркер 10.15 ────────────────────────────────────────────────

class TestRound1015MarkerUpdated:
    def test_old_marker_removed(self):
        assert '"☀️ Сон выключен" in JS' not in ROUND1015
        assert '"🌅 Глубокий сон выключен" in JS' not in ROUND1015

    def test_countdown_marker_present(self):
        assert '"fmtCountdown: function" in JS' in ROUND1015
        assert '"Сон выключен" not in JS' in ROUND1015
