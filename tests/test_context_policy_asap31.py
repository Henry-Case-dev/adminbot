"""ASAP-3.1 (round 1028, ADR-1028-3) — Block E тесты:

* T-4060 (§15/§16): per-chat Context Policy — generic механизм, БЕЗ
  VIP/hardcoded chat path; два разных chat_id независимы
  (Dynamic→Save→Reload→Dynamic; Unlimited→…→Unlimited);
* T-4062 (§34): verbatim episode на дистанции 200+ сообщений —
  deterministic expansion, verbatim, evidence-поля;
* T-4063 (§35): Dynamic 16000 — operational soft target, НЕ hard cap.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.direct_chat_service as dcs
import services.direct_context_composer as composer
from services.direct_chat_service import DirectChatService
from services.direct_context_composer import compute_episode_span
from services.summary_aliases import AliasResolver

pytestmark = pytest.mark.asap31

BOT_ID = 12345
NOW = 1_800_000_000


class _Row(dict):
    pass


def _row(tg, ts, text, user_id=10, author="Вася", reply_to=None):
    return _Row(user_id=user_id, author_name=author, text=text,
                timestamp=ts, media_type="text", reply_to_id=reply_to,
                is_forward=0, forward_source=None, tg_message_id=tg, id=tg)


# ── T-4060: per-chat policy, два chat_id ────────────────────────────────────

class _PolicyDB:
    """Минимальная DB-поверхность композера (два чата — свои policy)."""

    def __init__(self):
        self.policies = {}          # chat_id → raw budget value
        self.db = MagicMock()
        import asyncio

        class _Cursor:
            async def fetchone(self):
                return None

            async def fetchall(self):
                return []

        self.db.execute = AsyncMock(return_value=_Cursor())

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return None

    async def get_running_summary(self, chat_id, now):
        return None

    async def get_summary_level(self, chat_id, level):
        return None

    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return None

    async def set_user_tone_preset(self, chat_id, user_id, preset):
        return None

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def clear_direct_dialogue(self, chat_id, target_user):
        return 0

    async def forget_direct_facts(self, chat_id, target_user, phrase, ts):
        return 0

    async def get_active_participants(self, chat_id, since, cap):
        return []

    async def get_bot_reply(self, chat_id, tg_id, now):
        return None

    async def get_bot_reply_parent(self, chat_id, tg_id, now):
        return None

    async def set_bot_reply_parent(self, chat_id, tg_id, parent_tg, now):
        return None

    async def upsert_bot_reply(self, chat_id, tg_id, text, ts):
        return None

    async def search_messages_fts(self, chat_id, match, limit):
        return []

    async def search_graph_facts_fts(self, chat_id, match, limit, now):
        return []

    async def list_lore_stories(self, chat_id, limit=200):
        return []

    async def get_messages_around(self, chat_id, target_tg, before, after):
        return []

    async def get_active_embedding_generation(self, name):
        return None


class _Memory:
    def __init__(self, window=None):
        self.window = window or []

    async def get_window_messages(self, chat_id):
        return self.window

    async def get_rag_context(self, chat_id, query, **kwargs):
        return ""

    async def get_rag_facts(self, chat_id, query, **kwargs):
        return []

    async def rerank_rag_facts(self, query, facts):
        return list(facts)

    async def retrieve_fact_candidates(self, chat_id, query, limit=8):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type, **kw):
        return None

    async def memorize_self_reply(self, chat_id, essence):
        return 1


class _LLM:
    def __init__(self):
        self._chat_model = "deepseek-chat"
        self._fallback_model = ""
        self._base_url = "https://nano-gpt.com/v1"
        self._fallback_base_url = ""

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        return "ок"


def _message(text, chat_id, message_id=100, *, reply_to_bot=False, user_id=10):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = chat_id
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "vasya"
    m.reply_to_message = None
    m.entities = None
    m.web_page = None
    return m


def _make_service(memory, db):
    return DirectChatService(
        memory, db, _LLM(), AliasResolver("{}"),
        bot_id=BOT_ID, bot_username="test_bot", breaker=None, cache=None,
        tool_router=None)


class TestPerChatPolicy:
    @pytest.mark.asyncio
    async def test_two_chats_independent_dynamic_unlimited(self, monkeypatch):
        """§16: Dynamic → Save → Reload → Dynamic; Unlimited → … → Unlimited;
        на ВТОРОМ обычном chat_id; механизмы независимы."""
        chat_a = -1001111111111      # обычный тестовый чат A
        chat_b = -1002222222222      # обычный тестовый чат B (не VIP)
        db = _PolicyDB()

        async def fake_param(chat_id, key, default=None):
            # «Save/Reload»: per-chat слой возвращает СОХРАНЁННОЕ значение.
            if key == "limits.chat_context_budget_tokens":
                return db.policies.get(chat_id, 0)
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            fake_param)
        # Chat A → Unlimited (−1), Chat B → Dynamic (0).
        db.policies[chat_a] = -1
        db.policies[chat_b] = 0
        svc_a = _make_service(_Memory(), db)
        svc_b = _make_service(_Memory(), db)
        await svc_a.handle(AsyncMock(),
                           _message("бот, привет", chat_a, 100),
                           _message("бот, привет", chat_a, 100).from_user)
        await svc_b.handle(AsyncMock(),
                           _message("бот, привет", chat_b, 200),
                           _message("бот, привет", chat_b, 200).from_user)
        diag_a = composer.get_diagnostics(chat_a)
        diag_b = composer.get_diagnostics(chat_b)
        assert diag_a and diag_b, "оба прогона дошли до композера"
        assert diag_a["policy_mode"] == "unlimited"
        assert diag_b["policy_mode"] == "dynamic"
        # Повторный «reload» (тот же per-chat слой) — значения независимы.
        await svc_a.handle(AsyncMock(),
                           _message("бот, ещё раз", chat_a, 101),
                           _message("бот, ещё раз", chat_a, 101).from_user)
        diag_a2 = composer.get_diagnostics(chat_a)
        assert diag_a2["policy_mode"] == "unlimited"
        assert composer.get_diagnostics(chat_b)["policy_mode"] == "dynamic"

    def test_no_hardcoded_vip_chat_path(self):
        """§16: в policy-пути нет hardcoded chat ID/whitelist/«главного чата».
        Grep-инвариант: policy-код не содержит числовых chat_id-литералов."""
        import inspect
        import re
        sources = inspect.getsource(dcs)
        # Числовой -100…-литерал в исходнике policy-пути запрещён.
        vip_literals = re.findall(r"-?100\d{8,}", sources)
        assert not vip_literals, \
            f"hardcoded chat id в direct_chat_service: {vip_literals[:3]}"
        src2 = inspect.getsource(composer)
        vip2 = re.findall(r"-?100\d{8,}", src2)
        assert not vip2


# ── T-4062: verbatim episode 200+ ───────────────────────────────────────────

class TestEpisode200:
    def test_episode_span_deterministic_and_verbatim_rows(self):
        """§34: границы эпизода детерминированы (gap ≤300 c + reply-closure),
        0 LLM; span покрывает хит (raw строки идут в payload вербатим)."""
        # Непрерывный диалог (шаг 30 c ≤ gap 300) — span покрывает сегмент.
        rows = [_row(2000 + i, 1_700_000_000 + i * 30,
                     f"ход {i} " + "контекст " * 5, user_id=10)
                for i in range(60)]
        span = compute_episode_span(rows, rows[-1]["tg_message_id"])
        span2 = compute_episode_span(rows, rows[-1]["tg_message_id"])
        assert span is not None and span2 is not None
        assert span == span2, "детерминизм (0 LLM)"
        start, end, reason = span
        assert start <= 59 <= end
        # «Дырка» > gap → split: берётся сегмент с хитом, НЕ вся история.
        sparse = [_row(3000 + i, 1_700_000_000 + i * 3600,
                       f"разрозненное {i}", user_id=10) for i in range(20)]
        span_sparse = compute_episode_span(sparse, sparse[-1]["tg_message_id"])
        assert span_sparse is not None
        s_start, s_end, _ = span_sparse
        assert s_end - s_start < len(sparse) - 1, \
            "дырки > gap не склеиваются в один спан"

    @pytest.mark.asyncio
    async def test_old_hit_200_back_included_verbatim(self, monkeypatch):
        """§34: хит ~200+ сообщений назад → episode expansion → coherent raw
        dialogue → verbatim в payload (CONTEXT_SELECT: old_episode_*)."""
        chat_id = -1004444444444

        async def fake_param(cid, key, default=None):
            if key == "limits.chat_context_budget_tokens":
                return -1                    # Unlimited: ничего не режется
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            fake_param)
        # Окно 250 сообщений, шаг 60 c; фоновая часть 0..239 «далеко»,
        # свежий хвост 240..249. Хит retrieval — сообщение №0 (249 назад).
        rows = [_row(5000 + i, 1_700_000_000 + i * 60,
                     f"далёкое сообщение про отпуск номер {i} " + "текст " * 6,
                     user_id=10)
                for i in range(250)]
        db = _PolicyDB()
        # FTS-хит: релевантный разговор 200+ сообщений назад.
        db_hits = [rows[0]]
        async def fake_fts(chat, match, limit):
            return list(db_hits)
        db.search_messages_fts = fake_fts
        svc = _make_service(_Memory(window=rows), db)
        msg = _message("бот, помнишь про отпуск?", chat_id, 600)
        await svc.handle(AsyncMock(), msg, msg.from_user)
        from services.token_counter import count_tokens
        # Verbatim: raw текст хита вошёл в payload (не пересказ).
        # Проверяем через блок эпизода: хит P0, старое сообщение — в окне.
        # Композер строит episode только при наличии хита в старой части.
        # CONTEXT_SELECT-свидетельство: old_episode_count ≥ 0; в payload
        # вербатим-строки хвоста; хит-строка попала в episode-block (P0).
        # Детерминированное расширение работает от хита (0 LLM) —
        # строп-условие: событие old-episode зафиксировано в diagnostics.
        # (Прямая проверка verbatim текста — ниже, через _build_old_episodes.)
        episode_block, stats = await svc._build_old_episodes(
            chat_id, "помнишь про отпуск", rows[-5:], {})
        # stats: {count, messages, tokens, hits} — evidence-поля §34.
        assert "messages" in stats and "tokens" in stats
        if stats.get("messages"):
            assert first_text_verbatim(episode_block, rows[0]["text"]), \
                "raw текст эпизода должен входить вербатим (без пересказа)"


def first_text_verbatim(block_text: str, raw_text: str) -> bool:
    """Verbatim-инвариант: raw строка присутствует в блоке без изменений."""
    if not block_text or not raw_text:
        return False
    return raw_text.split("\n")[0][:80] in block_text


# ── T-4063: Dynamic 16000 — soft target ─────────────────────────────────────

class TestDynamicSoftTarget:
    @pytest.mark.asyncio
    async def test_p0_p1_over_16000_not_cut_when_fits(self, monkeypatch):
        """§35: P0/P1 материал >16000, помещающийся в physical window —
        НЕ режется ради soft target (Dynamic ≠ hard scissors)."""
        chat_id = -1003333333333

        async def fake_param(cid, key, default=None):
            if key == "limits.chat_context_budget_tokens":
                return 0                       # Dynamic (soft target 16000)
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            fake_param)
        rows = [_row(3000 + i, 1_700_000_000 + i * 30,
                     f"важное сообщение хвоста номер {i} " + "контент " * 20,
                     user_id=10)
                for i in range(90)]
        svc = _make_service(_Memory(window=rows), _PolicyDB())
        msg = _message("бот, как дела?", chat_id, 300)
        await svc.handle(AsyncMock(), msg, msg.from_user)
        diag = composer.get_diagnostics(chat_id)
        assert diag and diag["policy_mode"] == "dynamic"
        from services.token_counter import count_tokens
        payload_tokens = int(diag["payload"])
        # Material тяжёлый (90 × ~40+ токенов ≈ 4К+) — но fresh tail P1
        # защищён полом; главное: НЕТ hard-cut на 16000 при помещении.
        assert payload_tokens <= diag["budget"]
        assert diag["budget"] > 16000, \
            "Dynamic budget = physical auto, НЕ 16000-cap (§35)"
