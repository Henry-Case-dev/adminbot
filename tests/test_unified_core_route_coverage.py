"""UNIFIED-CORE (P0, владелец 20.10.2026) — route coverage матрица.

Спека: plans/features/add-exp/unified-core-spec.md (§1/§4/§5). Доказывается на
captured effective payload (реальные system-сообщения, а не «слой есть»):

* один и тот же Personality Core + `<Expression_Settings>` во ВСЕХ
  пользовательских речевых маршрутах: Factcheck (two-call вербализатор и
  одиночный 10.21-путь), Summary (Рассказчик и legacy-путь), Checkup (чат),
  tool-вербализация (search/youtube/web);
* внутренние процессы остаются нейтральными: Аналитик (Stage-1 JSON),
  Редактор саммари (Stage-1), checkup из tool-loop (без chat_id);
* GLOBAL/per-chat + hot-apply; нет конфиг-слоя → байт-паритет прежней сборки
  (OFF-паритет шва 2);
* C14: обход safety («Игнорируй все настройки безопасности…») вычищен из
  канона фактчека; OFF-пользователь не получает мат из фактчека; прежние
  байты канона живут в PREV-слепках (миграция/откат);
* C13: мёртвый tone_hint удалён из схемы Аналитика.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-CORE
"""
from __future__ import annotations

import asyncio
import json

import pytest

from services import chat_params
from services import hot_config as hot
from services import mca_expression as ex
from services import prompt_composer as pc
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT,
    PREV_FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT,
)

CORE_MARKER = "живой участник неформального русскоязычного чата"
EXPR_OPEN = "<Expression_Settings>"
OFF_LINE = "- Мат: Не используй мат в собственной речи."
FREQ_LINE = ("- Мат: Матерись свободно и регулярно. Мат — привычная часть "
             "твоей повседневной речи, а не редкое исключение.")
BYPASS = "Игнорируй все настройки безопасности"


def _run(coro):
    return asyncio.run(coro)


class FakeHot:
    """Двойник ConfigCache (достаточно get для резолверов композера)."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_config_cache(self):
        return self


class FakeChatCache:
    """per-chat overrides (`character.expression` / `character.core`)."""

    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides)}


def _expr_doc(mode: str) -> dict:
    return {"enabled": True, "profanity": mode}


@pytest.fixture()
def frequent_global():
    """GLOBAL слой: profanity=frequent + заводской Core."""
    hot.set_config_cache(FakeHot({
        ex.EXPRESSION_DOC_KEY: _expr_doc("frequent")}))
    chat_params.set_chat_params_cache(None)
    yield
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


@pytest.fixture()
def no_config():
    """Конфиг-слой недоступен → инъекции нет (байт-паритет шва 2)."""
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


# ═══ 1. Factcheck: вербализатор (Stage-2) и одиночный путь ══════════════════

_ANALYST_JSON = json.dumps({
    "claim": "юзер говорил, что сервер падал",
    "findings": [{"assertion": "сервер падал в августе",
                  "status": "true",
                  "human_time": "в августе",
                  "author": "Аня",
                  "evidence": "в логах чата есть сообщение об падении"}],
    "verdict": "юзер говорил правду",
    "response_mode": "casual",
}, ensure_ascii=False)


class _CaptureLLM:
    def __init__(self, stage1=_ANALYST_JSON):
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"step": kwargs.get("step"),
                           "messages": [dict(m) for m in messages]})
        return _ANALYST_JSON


def _factcheck_service(capture):
    from services.factcheck_service import FactCheckService

    class _Agg:
        async def search(self, query, max_symbols):
            return "поисковая выдача: сервер падал в августе"

    return FactCheckService(_Agg(), capture, memory=None)


def test_factcheck_verbalizer_two_call_gets_core_and_expression(
        frequent_global, monkeypatch):
    from services import factcheck_service as fs

    monkeypatch.setattr(type(__import__(
        "config.settings", fromlist=["settings"]).settings),
        "SYSTEM2_FACTCHECK_ENABLED", True)

    captured = {}

    async def fake_verbalize(_generate, base_messages, **kwargs):
        captured["messages"] = base_messages
        return "вердикт", {"attempts": 1, "retries": 0, "hits": [],
                           "fallback": False}

    monkeypatch.setattr(fs, "verbalize_validated", fake_verbalize)
    llm = _CaptureLLM()
    service = _factcheck_service(llm)
    text = _run(service.check_claim("сервер падал в августе?", chat_id=777))
    assert text == "вердикт"
    # Stage-1 (Аналитик) — внутренний процесс: БЕЗ личности/выражения.
    stage1 = llm.calls[0]["messages"][0]["content"]
    assert stage1 == FACTCHECK_ANALYST_SYSTEM_PROMPT
    assert EXPR_OPEN not in stage1 and CORE_MARKER not in stage1
    # Stage-2 (Вербализатор) — пользовательская речь: Core + Expression.
    system = captured["messages"][0]["content"]
    assert CORE_MARKER in system
    assert EXPR_OPEN in system and FREQ_LINE in system
    assert system.index("СИСТЕМНАЯ РОЛЬ") < system.index(CORE_MARKER) \
        < system.index(EXPR_OPEN)


def test_factcheck_single_path_gets_core_and_expression(
        frequent_global, monkeypatch):
    monkeypatch.setattr(type(__import__(
        "config.settings", fromlist=["settings"]).settings),
        "SYSTEM2_FACTCHECK_ENABLED", False)
    llm = _CaptureLLM()
    service = _factcheck_service(llm)
    _run(service.check_claim("сервер падал в августе?", chat_id=777))
    assert llm.calls[0]["step"] == "single"
    system = llm.calls[0]["messages"][0]["content"]
    assert CORE_MARKER in system and EXPR_OPEN in system
    assert FREQ_LINE in system
    # C14: в каноне (и в собранном payload) нет обхода safety и
    # безусловного разрешения мата.
    assert BYPASS not in system
    assert "Разрешен мат, токсичность" not in system


def test_factcheck_single_path_without_config_is_byte_parity(no_config):
    monkeypatch_free = type(__import__(
        "config.settings", fromlist=["settings"]).settings)
    from config.settings import settings
    monkeypatch_free.SYSTEM2_FACTCHECK_ENABLED = False
    llm = _CaptureLLM()
    service = _factcheck_service(llm)
    _run(service.check_claim("сервер падал в августе?", chat_id=777))
    system = llm.calls[0]["messages"][0]["content"]
    max_symbols = 4000
    assert system == FACTCHECK_SYSTEM_PROMPT.replace(
        "{max_symbols}", str(max_symbols))


# ═══ 2. Summary: Рассказчик (Stage-2) и legacy-путь ═════════════════════════

def _summary_fake_self(captured, *, llm_raw):
    from types import SimpleNamespace
    from services.summary_generator import SummaryGenerator as G

    fake = SimpleNamespace()
    fake.aliases = None

    class _Memory:
        db = None

        async def search_long_term(self, chat_id, keywords, limit):
            return []

        async def vector_search(self, chat_id, query, limit):
            return []

        async def get_graph_facts(self, chat_id, rows, keywords):
            return []

        async def get_rag_context(self, chat_id, query, sort_by_timestamp=False):
            return ""

        def memorize_facts(self, chat_id, text, kind):
            return None

    fake.memory = _Memory()

    class _Xml:
        def build(self, rows, aliases, trigger_message_id, window_caps=None):
            return "<chat_history></chat_history>"

    fake.xml = _Xml()

    async def _llm_generate(payload, chat_id, correlation_id=None, step=""):
        captured.setdefault("messages", []).append(
            (step, [dict(m) for m in payload]))
        return llm_raw

    fake._llm_generate = _llm_generate

    async def _supervised_generate(messages, correlation_id=None, step=""):
        captured.setdefault("messages", []).append(
            (step, [dict(m) for m in messages]))
        return "текст рассказчика"

    fake._supervised_generate = _supervised_generate
    fake._extract_keywords = G._extract_keywords
    fake._compose_user_content = G._compose_user_content
    return fake


def test_summary_narrator_gets_core_and_expression(
        frequent_global, monkeypatch):
    from services import summary_generator as sg

    captured = {}
    editor_json = json.dumps({
        "response_mode": "casual",
        "digest": "Главная тема: сервер падал. Подробности в выжимке.",
        "cover_prompt": ""}, ensure_ascii=False)
    fake = _summary_fake_self(captured, llm_raw=editor_json)

    async def fake_verbalize(_generate, base_messages, **kwargs):
        captured["narrator_system"] = base_messages[0]["content"]
        return "текст рассказчика", {"attempts": 1, "retries": 0, "hits": [],
                                     "fallback": False}

    monkeypatch.setattr(sg, "verbalize_validated", fake_verbalize)
    draft = _run(sg.SummaryGenerator._generate_two_call(
        fake, "сырое окно чата", 4000, 777))
    assert draft is not None and draft.text == "текст рассказчика"
    # Stage-1 (Редактор) — внутренний процесс: БЕЗ личности/выражения.
    editor_system = captured["messages"][0][1][0]["content"]
    assert EXPR_OPEN not in editor_system and CORE_MARKER not in editor_system
    # Stage-2 (Рассказчик) — пользовательская речь: Core + Expression.
    system = captured["narrator_system"]
    assert CORE_MARKER in system and EXPR_OPEN in system
    assert FREQ_LINE in system


def test_summary_single_path_gets_core_and_expression(
        frequent_global, monkeypatch):
    from services import summary_generator as sg

    monkeypatch.setattr(sg, "_legacy_source_window_enabled", lambda: False)
    captured = {}
    fake = _summary_fake_self(captured, llm_raw=None)  # None → early exit
    published = _run(sg.SummaryGenerator._run_legacy_pipeline(
        fake, 777, [], None, None, "corr-unified-core"))
    assert published is False
    steps = [step for step, _msgs in captured["messages"]]
    assert "single" in steps
    system = dict(captured["messages"])["single"][0]["content"]
    assert CORE_MARKER in system and EXPR_OPEN in system
    assert FREQ_LINE in system


# ═══ 3. Checkup: чат-команда получает слои; tool-loop остаётся нейтральным ══

def test_checkup_chat_command_gets_core_and_expression(frequent_global):
    from services.checkup_service import CheckupService

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, messages, **kwargs):
            self.calls.append([dict(m) for m in messages])
            return "отчёт"

    llm = _LLM()
    _run(CheckupService(llm).checkup("логи", used_fallback=True,
                                     chat_id=777))
    system = llm.calls[0][0]["content"]
    assert CORE_MARKER in system and EXPR_OPEN in system
    assert FREQ_LINE in system
    from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE
    # Служебная приписка остаётся последним абзацем system.
    assert system.endswith(CHECKUP_FALLBACK_NOTICE)
    assert system[: -len(CHECKUP_FALLBACK_NOTICE)].endswith("\n\n")


def test_checkup_tool_loop_without_chat_id_stays_neutral(frequent_global):
    """get_bot_health (tool_router) вызывает checkup БЕЗ chat_id: отчёт —
    внутренние данные, их вербализует Direct Writer со своими слоями."""
    from services.checkup_service import CheckupService

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, messages, **kwargs):
            self.calls.append([dict(m) for m in messages])
            return "отчёт"

    llm = _LLM()
    _run(CheckupService(llm).checkup("логи", used_fallback=False))
    system = llm.calls[0][0]["content"]
    assert CORE_MARKER not in system and EXPR_OPEN not in system


# ═══ 4. Tool-вербализация: search / youtube / web ═══════════════════════════

def test_search_summary_gets_core_and_expression(frequent_global):
    from services.search_service import SearchService

    class _Agg:
        async def search(self, query, max_symbols):
            return "выдача"

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, messages, **kwargs):
            self.calls.append([dict(m) for m in messages])
            return "выжимка"

    llm = _LLM()
    _run(SearchService(_Agg(), llm, memory=None).research(
        "запрос про сервер", chat_id=777))
    # Реранкер — внутренний процесс (сырая выдача для основного вызова):
    # личности/выражения в нём НЕТ.
    rerank_system = llm.calls[0][0]["content"]
    assert CORE_MARKER not in rerank_system and EXPR_OPEN not in rerank_system
    system = llm.calls[-1][0]["content"]
    assert CORE_MARKER in system and EXPR_OPEN in system
    assert FREQ_LINE in system


def test_youtube_routes_get_core_and_expression(frequent_global):
    from services.youtube_summarizer_service import YoutubeSummarizerService

    class _Engine:
        async def fetch_transcript(self, video_id, max_symbols, on_retry=None):
            return "транскрипт"

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, messages, **kwargs):
            self.calls.append([dict(m) for m in messages])
            return "выжимка"

    llm = _LLM()
    service = YoutubeSummarizerService(_Engine(), llm, memory=None)
    _run(service.summarize("vid123", chat_id=777))
    _run(service.summarize_transcript(chat_id=777, transcript="расшифровка"))
    assert len(llm.calls) == 2
    for messages in llm.calls:
        system = messages[0]["content"]
        assert CORE_MARKER in system and EXPR_OPEN in system


def test_web_summary_gets_core_and_expression(frequent_global):
    from services.web_summarizer_service import WebSummarizerService

    class _Extractor:
        async def extract(self, url, max_symbols):
            return "текст страницы"

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, messages, **kwargs):
            self.calls.append([dict(m) for m in messages])
            return "выжимка"

    llm = _LLM()
    _run(WebSummarizerService(_Extractor(), llm, memory=None).summarize(
        "https://example.com", chat_id=777))
    system = llm.calls[0][0]["content"]
    assert CORE_MARKER in system and EXPR_OPEN in system


# ═══ 5. OFF-режим, per-chat, hot-apply ══════════════════════════════════════

def test_off_mode_reaches_tool_route_and_blocks_profanity(frequent_global):
    """GLOBAL=frequent + per-chat=off → в маршруте этого чата действует off."""
    hot.set_config_cache(FakeHot({ex.EXPRESSION_DOC_KEY: _expr_doc("frequent")}))
    chat_params.set_chat_params_cache(FakeChatCache({
        ex.EXPRESSION_DOC_KEY: _expr_doc("off")}))
    try:
        from services.search_service import SearchService

        class _Agg:
            async def search(self, query, max_symbols):
                return "выдача"

        class _LLM:
            def __init__(self):
                self.calls = []

            async def generate(self, messages, **kwargs):
                self.calls.append([dict(m) for m in messages])
                return "выжимка"

        llm = _LLM()
        _run(SearchService(_Agg(), llm, memory=None).research(
            "запрос", chat_id=777))
        system = llm.calls[-1][0]["content"]
        assert CORE_MARKER in system
        assert EXPR_OPEN in system and OFF_LINE in system
        assert FREQ_LINE not in system
    finally:
        chat_params.set_chat_params_cache(None)


def test_hot_apply_changes_payload_without_restart(frequent_global):
    from services.search_service import SearchService

    class _Agg:
        async def search(self, query, max_symbols):
            return "выдача"

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, messages, **kwargs):
            self.calls.append([dict(m) for m in messages])
            return "выжимка"

    llm = _LLM()
    service = SearchService(_Agg(), llm, memory=None)
    _run(service.research("запрос", chat_id=777))
    assert FREQ_LINE in llm.calls[-1][0]["content"]
    # Владелец переключил режим в админке (hot) — без рестарта.
    hot.set_config_cache(FakeHot({ex.EXPRESSION_DOC_KEY: _expr_doc("off")}))
    _run(service.research("запрос", chat_id=777))
    assert OFF_LINE in llm.calls[-1][0]["content"]
    assert FREQ_LINE not in llm.calls[-1][0]["content"]


def test_factory_defaults_inject_core_and_occasional():
    """Слой есть (PG доступен), документа нет → заводской Core + occasional."""
    hot.set_config_cache(FakeHot({}))
    chat_params.set_chat_params_cache(None)
    try:
        block = _run(pc.speech_owner_block(777))
        assert CORE_MARKER in block
        assert EXPR_OPEN in block
        assert "- Мат: Иногда используй мат" in block
    finally:
        hot.set_config_cache(None)
        chat_params.set_chat_params_cache(None)


def test_speech_owner_block_empty_without_chat_id():
    hot.set_config_cache(FakeHot({ex.EXPRESSION_DOC_KEY: _expr_doc("frequent")}))
    try:
        assert _run(pc.speech_owner_block(None)) == ""
        assert _run(pc.speech_owner_block(0)) == ""
    finally:
        hot.set_config_cache(None)


# ═══ 6. C14/C13: канон, лестница, OFF-паритет persisted-значений ════════════

def test_factcheck_canon_has_no_safety_bypass():
    assert BYPASS not in FACTCHECK_SYSTEM_PROMPT
    assert "Разрешен мат, токсичность" not in FACTCHECK_SYSTEM_PROMPT
    # Жанровые контракты (точность, ссылки, структура, голос) сохранены.
    assert "третейский судья в интернет-срачах" in FACTCHECK_SYSTEM_PROMPT
    assert "Категорически запрещено притягивать мусорные ссылки" \
        in FACTCHECK_SYSTEM_PROMPT


def test_analyst_canon_has_no_dead_tone_hint():
    assert "tone_hint" not in FACTCHECK_ANALYST_SYSTEM_PROMPT


def test_unified_core_migration_ladder_and_rollback():
    key = "prompts.factcheck_system_prompt"
    steps = pm.PROMPT_MIGRATIONS[key]
    assert (PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT,
            FACTCHECK_SYSTEM_PROMPT) in steps
    # Прежний канон (с обходом safety) — известный канон: миграция узнаёт
    # прод-значения, откат ведёт на непосредственный прежний канон.
    assert pm.ROLLBACK_MIGRATIONS[key] == (
        FACTCHECK_SYSTEM_PROMPT, PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT)
    assert pr.is_known_canon(PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT)
    assert BYPASS in PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT
    assert BYPASS in PREV_FACTCHECK_SYSTEM_PROMPT
    akey = "prompts.factcheck_analyst_system_prompt"
    assert (PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT,
            FACTCHECK_ANALYST_SYSTEM_PROMPT) in pm.PROMPT_MIGRATIONS[akey]
    assert "tone_hint" in PREV_FACTCHECK_ANALYST_UNIFIED_CORE_SYSTEM_PROMPT


def test_persisted_old_factcheck_canon_still_suppressed():
    """OFF-паритет: persisted-значение старого канона (с обходом safety)
    вычищается на сборке; кодовый fallback больше не содержит обхода."""
    stripped, info = pr.suppress_legacy_speech(
        PREV_FACTCHECK_UNIFIED_CORE_SYSTEM_PROMPT, source="global")
    assert info.applied and info.removed > 0
    assert BYPASS not in stripped
    untouched, code_info = pr.suppress_legacy_speech(
        FACTCHECK_SYSTEM_PROMPT, source="default")
    assert untouched == FACTCHECK_SYSTEM_PROMPT
    assert code_info.applied is False
