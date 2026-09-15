"""Раунд 10.19 — F4 `direct-context-limit-expansion` (T-1861/T-1862) +
High S10.19-13 («мина контекста»: `-1`/`0` → срез «в 1 токен») +
Medium S10.19-14 (пустой день фон-контура → ложное «Запрещено»).

Покрытие:
  * sentinel-семантика контекста: `<0` → потолок, `0`/None → дефолт, `>0` → cap;
  * `safe_budget` не даёт 1 токен для безлимитного чата (`-1`) — `_build_global_context`
    не режет контекст до 1;
  * общий бюджет `-1` → агрегатное усечение не применяется;
  * chars-fallback — аварийный (debug, не WARNING);
  * идемпотентная миграция дефолтов контекста (1000/500/4000 → 5000/3000/16000);
  * S10.19-14: пустой день фон-контура → лимит из настроек;
  * каталог — человекочитаемые единицы («кусочки текста») + sentinel; сид настроек
    держит `-1`.

R17: только ключи/числа, без секретов и промптов.
"""
import json
import logging
from pathlib import Path

import pytest

from config.settings import settings
from services import budget_limits as bl
from services import config_migrations as cm
from services import token_counter as tc

CHAT_ID = -1001234567890
TARGET_CHAT_ID = -1002661910336
CEIL = settings.CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS

CONTEXT_KEYS = (
    "limits.chat_global_context_max_tokens",
    "limits.chat_thread_max_tokens",
    "limits.chat_context_budget_tokens",
)


# ── sentinel-семантика контекста ─────────────────────────────────────────────

class TestContextSentinelSemantics:
    def test_negative_unlimited_resolves_to_ceiling(self):
        """S10.19-13: `-1` НЕ уходит в safe_budget(-1)=1, а → потолок."""
        assert tc.resolve_chat_limit(-1, 1000, "X", 1, "L") == ("tokens", CEIL)
        assert tc.resolve_context_tokens(-1, 5000) == CEIL
        assert tc.resolve_context_tokens(-99, 3000) == CEIL
        assert tc.safe_budget(CEIL) > 1

    def test_zero_and_none_unset_global_default(self):
        assert tc.resolve_chat_limit(0, 5000, "X", 1, "L") == ("tokens", 5000)
        assert tc.resolve_chat_limit(None, 3000, "X", 1, "L") == ("tokens", 3000)
        assert tc.resolve_context_tokens(0, 5000) == 5000
        assert tc.resolve_context_tokens(None, 3000) == 3000

    def test_positive_cap(self):
        assert tc.resolve_chat_limit(2500, 5000, "X", 1, "L") == ("tokens", 2500)
        assert tc.resolve_context_tokens(2500, 5000) == 2500

    def test_negative_default_is_clamped(self, monkeypatch):
        """D-8: отрицательный env-дефолт (`-1` при незаданном токен-значении)
        не превращается в `-1` → `safe_budget(-1)=1` («мина» S10.19-13)."""
        monkeypatch.delenv("UNSET_CTX_CHARS_1019", raising=False)
        assert tc.resolve_context_tokens(None, -1) == 1
        assert tc.resolve_context_tokens(None, -5000) == 1
        assert tc.resolve_chat_limit(
            None, -1, "UNSET_CTX_CHARS_1019", 1, "L") == ("tokens", 1)
        assert tc.safe_budget(tc.resolve_context_tokens(None, -1)) >= 1

    def test_budget_families_stay_distinct(self):
        # контекст: 0 = не задано; бюджет: 0 = запрет (не смешивать).
        assert bl.context_state(0) == "unset"
        assert bl.budget_state(0) == "forbidden"


# ── chars-fallback — аварийный путь ─────────────────────────────────────────

class TestCharsFallbackEmergency:
    def test_debug_not_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("CTX_CHARS_KEY", "4000")
        with caplog.at_level(logging.DEBUG):
            result = tc.resolve_chat_limit(None, 5000, "CTX_CHARS_KEY", 4000,
                                           "CTX")
        assert result == ("chars", 4000)
        records = [r for r in caplog.records if "chars-fallback" in r.message]
        assert records
        assert all(r.levelno < logging.WARNING for r in records)

    def test_configured_token_bypasses_chars(self, monkeypatch):
        monkeypatch.setenv("CTX_CHARS_KEY2", "4000")
        assert tc.resolve_chat_limit(5000, 5000, "CTX_CHARS_KEY2", 4000,
                                     "CTX") == ("tokens", 5000)


# ── доказательство: контекст целевого чата не режется до 1 ─────────────────────────────

class _FakeMemory:
    def __init__(self, window):
        self.window = window

    async def get_window_messages(self, chat_id):
        return self.window


class _FakeDB:
    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return None

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def get_active_participants(self, chat_id, since, cap):
        return []


class _Aliases:
    def resolve(self, uid, name, username):
        return name or f"u{uid}"


class TestGlobalContextNotStarved:
    @staticmethod
    def _row(uid, name, text, ts):
        return {"user_id": uid, "author_name": name, "text": text,
                "timestamp": ts, "media_type": "text", "reply_to_id": None,
                "tg_message_id": None}

    @pytest.mark.asyncio
    async def test_unlimited_keeps_context(self, monkeypatch):
        """S10.19-13: целевой чат (`-1`) получает контекст, а не «1 токен»."""
        from services import direct_chat_service as dcs

        window = [self._row(10 + i, "вася", f"важное сообщение номер {i} " * 4,
                            100 + i) for i in range(20)]

        async def fake_cp(chat_id, key, default=None):
            if key in CONTEXT_KEYS:
                return -1
            return default

        monkeypatch.setattr(dcs, "_cp_g", fake_cp)
        svc = dcs.DirectChatService(
            _FakeMemory(window), _FakeDB(), None, _Aliases())
        block = await svc._build_global_context(CHAT_ID, window)
        assert "важное сообщение номер 19" in block
        assert "важное сообщение номер 0" in block
        assert tc.count_tokens(block) > 100          # не срезан до 1 токена

    @pytest.mark.asyncio
    async def test_zero_unset_uses_global_default(self, monkeypatch):
        """`0` = не задано → дефолт (контекст не пустой)."""
        from services import direct_chat_service as dcs

        window = [self._row(10, "вася", "привет мир", 100)]

        async def fake_cp(chat_id, key, default=None):
            if key in CONTEXT_KEYS:
                return 0
            return default

        monkeypatch.setattr(dcs, "_cp_g", fake_cp)
        svc = dcs.DirectChatService(
            _FakeMemory(window), _FakeDB(), None, _Aliases())
        block = await svc._build_global_context(CHAT_ID, window)
        assert "привет мир" in block


class TestAggregateBudgetUnlimited:
    def _svc(self):
        from services import direct_chat_service as dcs
        return dcs.DirectChatService(
            _FakeMemory([]), _FakeDB(), None, _Aliases())

    def test_minus_one_skips_aggregate_truncation(self):
        svc = self._svc()
        big = "текстовыйнаполнитель " * 5000
        blocks = [("rag", f"<RAG_Memory>\n{big}\n</RAG_Memory>"),
                  ("global", f"<Global_Context>\n{big}\n</Global_Context>")]
        result = svc._apply_context_budget(blocks, True, -1)
        assert result == [text for _, text in blocks]

    def test_zero_uses_global_default(self):
        svc = self._svc()
        result = svc._apply_context_budget(
            [("rag", "<RAG_Memory>\nкоротко\n</RAG_Memory>")], True, 0)
        assert result[0].startswith("<RAG_Memory>")

    def test_budget_does_not_double_cut_global_below_cap(self):
        """F4/ADR-1019-4 D1 (D-1/D-2): при бюджете 16000 global не режется
        ниже своего per-block потолка `safe_budget(5000)=4347` даже при
        неприкосновенном блоке ~3000. Доля `0.30×(16000−3000)=3900 < 4347` —
        раньше это давало двойную обрезку (4452→3953 < cap). Блок заведомо
        ≥ cap, чтобы тест не был тривиальным."""
        svc = self._svc()

        def _big(tokens: int) -> str:
            unit = "текст наполнитель "
            text = ""
            while tc.count_tokens(text) < tokens:
                text += unit
            return text

        global_block = f"<Global_Context>\n{_big(4400)}\n</Global_Context>"
        before = tc.count_tokens(global_block)
        assert before >= tc.safe_budget(5000)          # ≥ 4347 — не тривиален
        protected = f"<protected_facts>\n{_big(3000)}\n</protected_facts>"
        result = svc._apply_context_budget(
            [("global", global_block),
             ("protected", protected)], True, 16000)
        global_out = next(t for t in result if t.startswith("<Global_Context>"))
        assert tc.count_tokens(global_out) == before     # без усечения
        assert f"<protected_facts>\n{_big(3000)}\n</protected_facts>" in result

    def test_minus_one_records_unlimited_without_fake_limit(self):
        """D-7: безлимит (`-1`) → `limit=None` + `unlimited=True` (виджет
        показывает «Безлимит (∞)», а не 100% used/used)."""
        from services import direct_chat_service as dcs
        svc = self._svc()
        svc._apply_context_budget(
            [("rag", "<RAG_Memory>\nтекст\n</RAG_Memory>")], True, -1)
        acct = dcs.get_process_accounting()
        assert acct["context_unlimited"] is True
        assert acct["context_limit"] is None

    @pytest.mark.asyncio
    async def test_invariant_warns_when_budget_below_caps(self, monkeypatch,
                                                          caplog):
        from services import direct_chat_service as dcs

        async def fake_cp(chat_id, key, default=None):
            if key == "limits.chat_global_context_max_tokens":
                return 5000
            if key == "limits.chat_thread_max_tokens":
                return 3000
            return default

        monkeypatch.setattr(dcs, "_cp_g", fake_cp)
        svc = dcs.DirectChatService(_FakeMemory([]), _FakeDB(), None, _Aliases())
        with caplog.at_level(logging.WARNING):
            await svc._check_context_config_invariant(CHAT_ID, 1000)
        assert any("context config inconsistent" in r.message
                   for r in caplog.records)
        # достаточно большой бюджет → без предупреждения
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            await svc._check_context_config_invariant(
                CHAT_ID + 1, 16000)
        assert not any("context config inconsistent" in r.message
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_invariant_accounts_for_fixed_tokens(self, monkeypatch,
                                                       caplog):
        """D-1: при budget=16000 и неприкосновенном блоке ~3000 реальная доля
        `0.30×(16000−3000)=3900 < safe_budget(5000)=4347` → WARNING. Раньше
        проверка `budget < global_cap + thread_cap` (16000 < 8000) молчала."""
        from services import direct_chat_service as dcs

        async def fake_cp(chat_id, key, default=None):
            if key == "limits.chat_global_context_max_tokens":
                return 5000
            if key == "limits.chat_thread_max_tokens":
                return 3000
            return default

        monkeypatch.setattr(dcs, "_cp_g", fake_cp)
        svc = dcs.DirectChatService(_FakeMemory([]), _FakeDB(), None, _Aliases())
        with caplog.at_level(logging.WARNING):
            await svc._check_context_config_invariant(CHAT_ID, 16000, 3000)
        assert any("context config inconsistent" in r.message
                   for r in caplog.records)
        # без fixed та же конфигурация согласована (доля 4800 ≥ 4347)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            await svc._check_context_config_invariant(
                CHAT_ID + 1, 16000, 0)
        assert not any("context config inconsistent" in r.message
                       for r in caplog.records)


# ── идемпотентная миграция дефолтов контекста ───────────────────────────────

class TestContextDefaultMigration:
    class _Cache:
        def __init__(self, values):
            self.values = dict(values)
            self.pg_available = True

        def get(self, key, default=None):
            return self.values.get(key, default)

        async def set(self, key, value, category):
            self.values[key] = value

    @pytest.mark.asyncio
    async def test_migrates_only_prev_defaults_and_is_idempotent(self):
        cache = self._Cache({
            "limits.chat_global_context_max_tokens": 1000,   # прежний эффективный
            "limits.chat_thread_max_tokens": 500,            # прежний
            "limits.chat_context_budget_tokens": 4000,       # прежний
        })
        report = await cm.migrate_context_limit_defaults(cache)
        assert report == {
            "limits.chat_global_context_max_tokens": "updated",
            "limits.chat_thread_max_tokens": "updated",
            "limits.chat_context_budget_tokens": "updated",
        }
        assert cache.values["limits.chat_global_context_max_tokens"] == 5000
        assert cache.values["limits.chat_thread_max_tokens"] == 3000
        assert cache.values["limits.chat_context_budget_tokens"] == 16000
        # повторный прогон — no-op
        assert await cm.migrate_context_limit_defaults(cache) == {}

    @pytest.mark.asyncio
    async def test_keeps_custom_and_missing(self):
        cache = self._Cache({
            "limits.chat_global_context_max_tokens": 7777,   # кастом владельца
        })
        assert await cm.migrate_context_limit_defaults(cache) == {}
        assert cache.values["limits.chat_global_context_max_tokens"] == 7777

    @pytest.mark.asyncio
    async def test_no_pg_skip(self):
        cache = self._Cache({})
        cache.pg_available = False
        assert await cm.migrate_context_limit_defaults(cache) == {}


# ── S10.19-14: пустой день фон-контура ──────────────────────────────────────

class TestWorkerQuietChatLimit:
    @pytest.mark.asyncio
    async def test_no_rows_reports_configured_limit(self, monkeypatch):
        from services import chat_usage, oversight

        async def _key_status(pg, chat_id):
            return {}

        async def _resolve(key, *, chat_id=None, default=None):
            return default, "default"

        monkeypatch.setattr(chat_usage, "key_status", _key_status)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        metric = await oversight._limits_metric(
            object(), -100, contour="worker", used_key="calls",
            day_rows=[], metric="llm_calls")
        assert metric["used"] == 0
        assert metric["limit"] == settings.WORKER_DAILY_LLM_CALLS_PER_CHAT
        assert metric["forbidden"] is False
        assert metric["unlimited"] is False


# ── каталог / сид настроек ────────────────────────────────────────────────────────

class TestCatalogAndSeed:
    def test_catalog_units_and_sentinel(self):
        """F4/T-1813 + round-10.9 jargon-гейт: единицы — «кусочки текста»
        (слово «токен» в UI запрещено), sentinel описан человекочитаемо."""
        from services import param_catalog as pc
        specs = {s.pg_key: s for s in pc.REGISTRY.values()}
        for key in CONTEXT_KEYS:
            spec = specs[key]
            assert "кусоч" in spec.title_ru.lower(), key
            assert "токен" not in spec.title_ru.lower(), key
            assert "токен" not in spec.description.lower(), key
            assert "−1" in spec.description or "-1" in spec.description, key
            assert "0" in spec.description, key

    def test_chat_settings_keeps_context_unlimited(self):
        root = Path("config/chat_settings_seed.json")
        data = json.loads(root.read_text(encoding="utf-8"))
        entry = next(c for c in data["chats"] if c["chat_id"] == TARGET_CHAT_ID)
        for key in CONTEXT_KEYS:
            assert entry["overrides"][key] == -1, key
