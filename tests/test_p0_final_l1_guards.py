"""SPEECH-P0-CORRECTIVE (25.10.2026, §1.1/§3) — финальные L1/L2-фиксы.

Покрытие (CONTRACT):
* L1 Planner — детерминированная температура 0.0 (hot-ключ переопределяет,
  явный default уважается), 0.0 реально уходит в payload dedicated-слота;
* direct-L2 guard: ведущий filler + ОДИН анонс процесса, без потери текста;
* direct-L2 guard: кавычки только для exact-фрагментов переданных источников
  (текст сохраняется, снимается только пунктуация);
* alias hot-reload: in-process payload-ход до/после set_chat_params.
"""
import inspect
import json

import pytest

from services import chat_params
from services import direct_chat_service as dcs
from services import direct_l1 as l1
from services import prompt_style_blocks as psb
from services import response_extent as extent
from services import summary_aliases as sa


# ── L1 Planner: детерминированная температура ────────────────────────────────

def _hot(value):
    def _get(key, default=None):
        if key == "limits.direct_l1_temperature":
            return value
        return default
    return _get


def test_l1_temperature_default_is_deterministic_zero(monkeypatch):
    monkeypatch.setattr("services.hot_config.get", _hot(None))
    assert l1.l1_temperature(None) == 0.0
    assert l1.l1_temperature() == 0.0


def test_l1_temperature_hot_key_overrides(monkeypatch):
    monkeypatch.setattr("services.hot_config.get", _hot(0.4))
    assert l1.l1_temperature(None) == 0.4
    monkeypatch.setattr("services.hot_config.get", _hot(0))
    assert l1.l1_temperature(None) == 0.0


def test_l1_temperature_explicit_default_respected(monkeypatch):
    monkeypatch.setattr("services.hot_config.get", _hot(None))
    assert l1.l1_temperature(0.2) == 0.2


class _FakeResponse:
    def __init__(self, content):
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}],
                "usage": {"total_tokens": 1}}


class _CapturingLLM:
    def __init__(self):
        self.payload = None

    async def _post(self, path, payload, **kwargs):
        self.payload = payload
        return _FakeResponse('{"response_act": "research"}')


@pytest.mark.asyncio
async def test_l1_zero_temperature_reaches_payload(monkeypatch):
    """0.0 — валидное значение: ключ `temperature` присутствует (не falsy-пропуск)."""
    monkeypatch.setattr("services.hot_config.get", _hot(None))
    llm = _CapturingLLM()
    slot = l1.L1ModelSlot(base_url="http://x", model="m", api_key="k",
                          dedicated=True, source="l1")
    content, _usage = await l1.dedicated_generate(
        llm, [{"role": "user", "content": "q"}], slot,
        temperature=l1.l1_temperature(None))
    assert content.startswith("{")
    assert llm.payload["temperature"] == 0.0


# ── L1: дет. fallback смыслового акта (P0 §1.1, probes_final5 A) ─────────────

# Дословный запрос A и план, который L1 вернул на final5 (`answer/compact`).
QUERY_A = "Бот проанализируй мои сообщения в чате и скажи, я злобный?"
PLAN_A = {"action": "reply", "response_act": "answer", "extent": "compact",
          "structure": "answer", "tone": "neutral",
          "delivery_hint": "plain", "confidence": 0.85}


def test_research_fallback_upgrades_act_and_keeps_extent():
    plan = l1.normalize_l1_plan(dict(PLAN_A))
    out, applied = l1.apply_research_fallback(plan, QUERY_A)
    assert applied is True
    assert out is plan
    assert out.response_act == "research"
    # Выбранные Planner'ом форма/длина не подменяются (§1.1).
    assert out.extent == "compact"
    assert out.structure == "answer"
    assert out.delivery_hint == "plain"


def test_research_fallback_payload_gets_analysis_once():
    plan = l1.normalize_l1_plan(dict(PLAN_A))
    l1.apply_research_fallback(plan, QUERY_A)
    assert l1.plan_response_mode(plan) == "serious"
    assert l1.analysis_directive_needed(plan) is True
    block = l1.build_l2_plan_block(plan, include_analysis=True)
    assert block.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert block.count(psb.ANALYSIS_WRITER_TEXT) == 1
    assert block.count(psb.QUOTE_FIDELITY_TEXT) == 1
    assert block.count(psb.NO_META_STRUCTURE_TEXT) == 1
    # Тот же путь сборки, что в `_run`: отрезок serious/compact не дублирует
    # analysis/NO_META (итог ровно 1× на payload, extent остаётся compact).
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", l1.plan_response_mode(plan), "plain",
        html_safe=True,
        extent_block=extent.render_extent_block(plan.to_response_plan()))
    payload = system + "\n\n" + block
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert payload.count(psb.ANALYSIS_WRITER_TEXT) == 1
    assert payload.count(psb.QUOTE_FIDELITY_TEXT) == 1
    assert payload.count(psb.NO_META_STRUCTURE_TEXT) == 1


@pytest.mark.parametrize("query", [
    # casual / opinion без маркеров материала — research НЕ форсируется.
    "Бот, ты дождь любишь или тебя от него ломает?",
    "Бот, я тебе уже сильно надоел?",
    "Как думаешь, я злобный?",
])
def test_research_fallback_leaves_casual_and_opinion(query):
    plan = l1.normalize_l1_plan(dict(PLAN_A))
    out, applied = l1.apply_research_fallback(plan, query)
    assert applied is False
    assert out.response_act == "answer"
    assert l1.analysis_directive_needed(out) is False


def test_research_fallback_is_noop_for_research_and_non_reply():
    already = l1.normalize_l1_plan({"action": "reply",
                                    "response_act": "research",
                                    "extent": "normal"})
    assert l1.apply_research_fallback(already, QUERY_A) == (already, False)

    silent = l1.normalize_l1_plan({"action": "silent", "extent": "auto"})
    out, applied = l1.apply_research_fallback(silent, QUERY_A)
    assert applied is False and out.response_act != "research"

    clarify = l1.normalize_l1_plan({"action": "reply", "extent": "auto",
                                    "needs_clarification": True,
                                    "clarification_target": "какие сообщения"})
    out, applied = l1.apply_research_fallback(clarify, QUERY_A)
    assert applied is False and out.response_act != "research"


def test_research_fallback_wired_into_l1_planner():
    src = inspect.getsource(dcs.DirectChatService._plan_direct_l1)
    assert "apply_research_fallback(" in src


# ── direct-L2: meta guard ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_prefix", [
    ("Ну, ты не злобный, просто устал. Но норм.",
     "Ты не злобный, просто устал. Но норм."),
    ("Ок, держи факт. Он в логе.",
     "Держи факт. Он в логе."),
    ("Давай без лишних церемоний.\n\n**Костя** — главный поставщик контента.",
     "**Костя** — главный поставщик контента."),
    ("Окей, глянул твою простыню. Если отбросить лирику, картина такая.",
     "Если отбросить лирику, картина такая."),
    ("Сейчас разберу. Конфликта в логе не было.",
     "Конфликта в логе не было."),
    ("Ну, давай без лишних церемоний.\n\n**Костя** — главный поставщик.",
     "**Костя** — главный поставщик."),
    # P0-FINAL-E2 (probes_final5): «ладно + давай» без глагола из списка.
    ("Ладно, давай по фактам. Ты не злобный, просто устал.",
     "Ты не злобный, просто устал."),
    ("Ладно, давай по фактам.\n\n**Костя** — главный поставщик контента.",
     "**Костя** — главный поставщик контента."),
    ("Ладно, давай по существу. Конфликта в логе не было.",
     "Конфликта в логе не было."),
    # P0-FINAL-META-E1 (25.10.2026): запятая после «давай» + «разложу».
    ("Ну давай, разложу по полочкам, раз уж попросил. "
     "Конфликта в логе не было.",
     "Конфликта в логе не было."),
    ("Ну давай, разберу по фактам. Конфликта в логе не было.",
     "Конфликта в логе не было."),
    # P0-FINAL-META-LAST (25.10.2026): чистые live-преамбулы без содержания.
    ("Ладно, смотри. Конфликта в логе не было.",
     "Конфликта в логе не было."),
    ("Ладно, смотри-ка. Конфликта в логе не было.",
     "Конфликта в логе не было."),
    ("Ладно, смотри.\n\n**Костя** — главный поставщик контента.",
     "**Костя** — главный поставщик контента."),
    ("Макс, ну давай, раз уж попросил. Конфликта в логе не было.",
     "Конфликта в логе не было."),
    ("Макс, ну давай, раз уж попросил.\n\n**Костя** — главный поставщик.",
     "**Костя** — главный поставщик."),
    ("Ну давай, раз уж попросил. Конфликта в логе не было.",
     "Конфликта в логе не было."),
    # P0-GENERAL-META (25.10.2026): общий класс ведущих анонсов процесса —
    # live-форма «Ну ок, давай разложу по полочкам, раз уж попросили.» и та
    # же форма с обращением/другими ведущими частицами (не перечисление фраз).
    ("Ну ок, давай разложу по полочкам, раз уж попросили. "
     "Конфликта в логе не было.",
     "Конфликта в логе не было."),
    ("Оля, разложу по полочкам. Конфликта в логе не было.",
     "Конфликта в логе не было."),
])
def test_meta_guard_removes_filler_and_single_announce(raw, expected_prefix):
    out, stats = dcs.strip_l2_meta_lead(raw)
    assert out == expected_prefix
    assert stats["filler_removed"] or stats["announce_removed"]


@pytest.mark.parametrize("raw", [
    # Ответ/факт в первом предложении — не трогаем.
    "Смотрю в логе — конфликта нет. Ты спокоен.",
    "Смотрю, конфликта нет. Ты спокоен.",
    "Глянул лог, всё чисто. Никаких ссор.",
    "Давай сразу в субботу. Я свободен после шести.",
    "Давай разберёмся: конфликта не было.",
    "Конфликта не было. Костя просто ныл.",
    # Анонс без содержательного продолжения — не режем (нечего оставить).
    "Давай без лишних церемоний.",
    # P0-FINAL-E2: содержательное «ладно, давай ...» не является анонсом.
    "Ладно, давай в субботу. Я свободен после шести.",
    "Ладно, давай по фактам: конфликта не было.",
    "Ладно, давай по фактам.",
    # P0-FINAL-META-E1: содержательное «Ну давай …» не является анонсом.
    "Ну давай в субботу. Я свободен после шести.",
    "Ну давай по фактам: конфликта не было.",
    "Ну давай, по фактам: конфликта не было.",
    # P0-FINAL-META-LAST: обращение без преамбулы — обычная реплика.
    "Макс, ты не злобный. Просто устал.",
    # Содержательный хвост в том же предложении — ветки не якорятся.
    "Ладно, смотри, конфликта в логе не было.",
    "Ладно, смотри: конфликта в логе не было.",
    "Макс, ну давай, раз уж попросил, по фактам.",
    # P0-GENERAL-META (25.10.2026): «:» после мета-глагола — уже пояснение/
    # ответ по существу, а не анонс процесса.
    "Разберу твой вопрос: конфликта в логе не было.",
    "Давай разложу факты: конфликта в логе не было.",
    # Преамбула без содержательного продолжения — нечего оставить.
    "Ладно, смотри.",
    "Макс, ну давай, раз уж попросил.",
])
def test_meta_guard_keeps_answer_and_lone_announce(raw):
    out, stats = dcs.strip_l2_meta_lead(raw)
    assert out == raw
    assert not stats["filler_removed"] and not stats["announce_removed"]


def test_meta_guard_removes_only_one_announce_and_keeps_body():
    raw = ("Окей, глянул твою простыню. Сейчас разберу по пунктам. "
           "Первый факт: Костя ноет про хейт.")
    out, stats = dcs.strip_l2_meta_lead(raw)
    assert stats["announce_removed"] is True
    # Второй анонс остаётся: guard снимает РОВНО одно предложение.
    assert out == ("Сейчас разберу по пунктам. "
                   "Первый факт: Костя ноет про хейт.")


def test_meta_guard_e2_removes_exactly_one_sentence():
    """P0-FINAL-E2: снимается ровно одно ведущее «Ладно, давай по фактам.»,
    остальной текст — байт-в-байт (включая абзацы и второй анонс)."""
    raw = ("Ладно, давай по фактам. Сейчас разберу по пунктам.\n\n"
           "Первый факт: Костя ноет про хейт.")
    out, stats = dcs.strip_l2_meta_lead(raw)
    assert stats["announce_removed"] is True
    assert out == ("Сейчас разберу по пунктам.\n\n"
                   "Первый факт: Костя ноет про хейт.")


def test_meta_guard_e1_removes_exactly_one_sentence():
    """P0-FINAL-META-E1: «Ну давай, разложу по полочкам, раз уж попросил.»
    снимается как ровно одно предложение, тело — байт-в-байт."""
    raw = ("Ну давай, разложу по полочкам, раз уж попросил. "
           "Сейчас разберу по пунктам.\n\n"
           "Первый факт: Костя ноет про хейт.")
    out, stats = dcs.strip_l2_meta_lead(raw)
    assert stats["announce_removed"] is True
    assert out == ("Сейчас разберу по пунктам.\n\n"
                   "Первый факт: Костя ноет про хейт.")


def test_meta_guard_general_live_form_removes_exactly_one_sentence():
    """P0-GENERAL-META live-форма 25.10.2026: «Ну ок, давай разложу по
    полочкам, раз уж попросили.» — снимается ровно одно предложение,
    остальной текст байт-в-байт (включая абзацы и второй анонс)."""
    raw = ("Ну ок, давай разложу по полочкам, раз уж попросили. "
           "Сейчас разберу по пунктам.\n\n"
           "Первый факт: Костя ноет про хейт.")
    out, stats = dcs.strip_l2_meta_lead(raw)
    assert stats["announce_removed"] is True
    assert out == ("Сейчас разберу по пунктам.\n\n"
                   "Первый факт: Костя ноет про хейт.")


@pytest.mark.parametrize("lead,verb", [
    ("Ну ок, давай", "разложу"),
    ("Ладно,", "разберу"),
    ("Ок,", "гляну"),
    ("Так,", "посмотрю"),
    ("Сейчас", "проверю"),
    ("Смотри,", "расскажу"),
    ("Ну,", "объясню"),
])
def test_meta_guard_covers_general_announce_class(lead, verb):
    """P0-GENERAL-META: guard держит КЛАСС ведущих анонсов (частицы ×
    мета-глагол 1-го лица), а не отдельную live-фразу."""
    raw = f"{lead} {verb} по порядку. Конфликта в логе не было."
    out, stats = dcs.strip_l2_meta_lead(raw)
    assert stats["announce_removed"] is True
    assert out == "Конфликта в логе не было."


def test_meta_guard_does_not_touch_later_paragraphs():
    raw = ("Давай без лишних церемоний.\n\nПервый абзац по делу.\n\n"
           "Второй абзац тоже по делу и не меняется.")
    out, _ = dcs.strip_l2_meta_lead(raw)
    assert out == "Первый абзац по делу.\n\nВторой абзац тоже по делу и не меняется."


def test_meta_guard_wired_into_direct_l2_writer():
    src = inspect.getsource(dcs.DirectChatService._l2_write_answer)
    assert "strip_l2_meta_lead(" in src
    assert "strip_unverified_l2_quotes(" in src


# ── direct-L2: quote guard ──────────────────────────────────────────────────

POOL_BLOCKS = [
    "<RAG_Memory>\n[чат] Костя: ой бля о5 старьё какоето\n"
    "[чат] Славик: одеяло мягкое и чувствуется на коже\n</RAG_Memory>",
]


def test_quote_guard_keeps_exact_quote():
    raw = "Костя писал «ой бля о5 старьё какоето» и это его типичное."
    out, stats = dcs.strip_unverified_l2_quotes(
        raw, query="что там?", blocks=POOL_BLOCKS)
    assert out == raw
    assert stats == {"quotes_total": 1, "quotes_kept": 1,
                     "quotes_unquoted": 0}


def test_quote_guard_unquotes_changed_words_but_keeps_text():
    raw = "Он про «супермега хейтом» и «не нравитса» писал."
    out, stats = dcs.strip_unverified_l2_quotes(
        raw, query="q", blocks=POOL_BLOCKS)
    assert out == "Он про супермега хейтом и не нравитса писал."
    assert stats["quotes_unquoted"] == 2
    assert stats["quotes_kept"] == 0


def test_quote_guard_unquotes_ellipsis_join_and_hallucination():
    raw = ("Костя: «как же приятно звучит незапиканный 163...»; "
           "потом «главный хулитель и музыкальный диктор».")
    out, stats = dcs.strip_unverified_l2_quotes(
        raw, query="q", blocks=POOL_BLOCKS)
    assert "«" not in out and "»" not in out
    assert "как же приятно звучит незапиканный 163" in out
    assert "главный хулитель и музыкальный диктор" in out
    assert stats["quotes_unquoted"] == 2


def test_quote_guard_uses_query_and_evidence_as_sources():
    raw = "Ты сам сказал «проверь мои сообщения в чате», а в выводе «tool: 12»."
    out, stats = dcs.strip_unverified_l2_quotes(
        raw, query="проверь мои сообщения в чате", evidence="tool: 12")
    assert out == raw
    assert stats["quotes_kept"] == 2


def test_quote_guard_no_sources_is_noop():
    raw = "Он сказал «что-то» и ушёл."
    out, stats = dcs.strip_unverified_l2_quotes(raw)
    assert out == raw
    assert stats["quotes_total"] == 0


def test_quote_guard_skips_html_attributes_and_no_letter_fragments():
    raw = 'Ссылка <a href="https://x">тут</a> и «...» — служебные.'
    out, stats = dcs.strip_unverified_l2_quotes(
        raw, query="q", blocks=["совсем другой текст"])
    # Кавычки HTML-атрибута и безбуквенный фрагмент не трогаются.
    assert '<a href="https://x">' in out and "«...»" in out
    assert stats["quotes_total"] == 0


# ── Alias hot-reload (in-process turn capture) ──────────────────────────────

CHAT_ID = -1007770001
UID = 42115912
OLD = "Гипербореец"
NEW = "Макс-новый"
GLOBAL = {"42115912": "Макс"}


class _FakeConn:
    def __init__(self, root):
        self.profiles = {
            CHAT_ID: {"chat_id": CHAT_ID,
                      "updated_at": "2026-10-25T00:00:01+00:00",
                      "chat_params": root, "gates_opt_in": False}}
        self._seq = 1

    def _row(self, chat_id):
        return self.profiles.get(chat_id)

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT"):
            return self._row(args[0])
        if "UPDATE chat_profiles" in sql:
            row = self._row(args[0])
            if row is None:
                return None
            row["chat_params"] = args[1]
            self._seq += 1
            row["updated_at"] = f"2026-10-25T00:00:{self._seq:02d}+00:00"
            return dict(row)
        return None

    async def execute(self, sql, *args):
        return "UPDATE 1"

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Tx()


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)


def _root(alias):
    return {"v": 1, "overrides": {"limits.summary_aliases":
                                  {str(UID): alias}},
            "gates": {}, "keys": {}, "perm_overrides": {}, "meta": {}}


@pytest.mark.asyncio
async def test_alias_change_applies_next_turn_without_restart(monkeypatch):
    """Один процесс, один LiveAliasView: смена алиаса через set_chat_params
    видна уже в payload СЛЕДУЮЩЕГО хода (без рестарта/пересборки сервиса)."""
    monkeypatch.setattr(
        "services.hot_config.get",
        lambda key, default=None: (dict(GLOBAL)
                                   if key == "limits.summary_aliases"
                                   else default))
    conn = _FakeConn(_root(OLD))
    pg = _FakePg(conn)
    cache = chat_params.ChatParamsCache(pg)
    monkeypatch.setattr(chat_params, "_chat_params_cache", cache)
    sa.reset_turn_alias_resolver()
    live = sa.LiveAliasView()
    window = [{"user_id": UID, "author_name": "tg_ник", "text": "привет"}]

    # Ход 1: действует старый чатовый алиас.
    await sa.bind_turn_aliases(CHAT_ID)
    speaker_1 = live.resolve(UID, "tg_ник", "tg_user")
    ctx_1 = l1.build_l1_context(
        query="что там?", window=window, speaker=speaker_1, addressee="чат",
        alias_resolver=live)
    assert speaker_1 == OLD
    assert f"{OLD}: привет" in ctx_1
    old_resolver = sa.current_alias_resolver()
    assert old_resolver.resolve(UID, "tg_ник", "tg_user") == OLD

    # Смена алиаса штатной записью (она же инвалидирует кэш chat_params).
    await chat_params.set_chat_params(
        CHAT_ID, {"overrides": {"limits.summary_aliases": {str(UID): NEW}}},
        pg=pg)
    saved = conn.profiles[CHAT_ID]["chat_params"]
    saved = json.loads(saved) if isinstance(saved, str) else saved
    assert saved["overrides"]["limits.summary_aliases"][str(UID)] == NEW
    assert CHAT_ID not in cache._items      # инвалидация кэша произошла

    # Ход 2 (тот же процесс, тот же объект live): новое имя в payload.
    await sa.bind_turn_aliases(CHAT_ID)
    speaker_2 = live.resolve(UID, "tg_ник", "tg_user")
    ctx_2 = l1.build_l1_context(
        query="что там?", window=window, speaker=speaker_2, addressee="чат",
        alias_resolver=live)
    assert speaker_2 == NEW
    assert f"{NEW}: привет" in ctx_2
    assert OLD not in ctx_2
    # Старый per-turn резолвер не переписан задним числом (изоляция ходов).
    assert old_resolver.resolve(UID, "tg_ник", "tg_user") == OLD
    sa.reset_turn_alias_resolver()
