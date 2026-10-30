"""EVOL-006 — качество фактов памяти: класс/долговечность/атрибуция.

Постоянные проверки проекта (``plans/current_task.md`` EVOL-006,
``plans/features/evol/audit/context-ui-audit.md`` §2):

  1. промпт-экстрактор содержит КОНТРАКТ классификации (durable_fact,
     one_off_request, world_news, quote, hypothetical_character,
     temporary_event, communication_pattern), правила атрибуции
     (world/topic/character vs user), опору (basis) и provenance
     (source_message_ids) — и НЕ содержит лексических black/whitelist;
  2. разбор/атрибуция читают класс структурно (`_validate_fact`,
     `fact_durability_decision`) — без дополнительных вызовов LLM;
  3. разовая просьба не попадает в пул долговременных фактов; репост/новость
     не приписывается человеку; персонаж запроса не становится биографией;
     временное событие получает ограниченный срок; обобщение о манере общения
     без опоры отклоняется;
  4. мусорный/дрейфовый ответ модели отклоняется честно (не «пустой факт ради
     KPI»); сырые сообщения и эпизоды не удаляются;
  5. provenance (tg_message_id/forward_from) сохраняется у записанного факта;
  6. путь восстановления после сбоя первичной экстракции (LLMError/timeout →
     один retry `_FACT_RETRY_SYSTEM_PROMPT`) несёт тот же контракт класса и
     атрибуции: классификация выживает при восстановлении, а не сбрасывается
     в «обычный факт».

TEST-LIFECYCLE: CONTRACT owner=EVOL-006 (W4)
"""
from __future__ import annotations

import json
import re

import pytest
import pytest_asyncio

from config.settings import settings
from services.database import DatabaseService
from services.llm_client import LLMError
from services.summary_memory import (
    FACT_KIND_DURABLE,
    FACT_KINDS,
    FACT_EXTRACT_PROMPT,
    PREV_FACT_EXTRACT_PROMPT,
    MemoryManager,
    _FACT_RETRY_SYSTEM_PROMPT,
    fact_durability_decision,
    parse_fact_list_ex,
)

CHAT_ID = -1001234567890
USER = "Вася"

#: Примеры классов, которые вернула модель (структура ответа, не текст).
DURABLE = {
    "subject": "Вася", "subject_type": "user",
    "predicate": "работает", "object": "на заводе", "object_type": "topic",
    "kind": "durable_fact", "source_message_ids": [11],
}
ONE_OFF = {
    "subject": "Вася", "subject_type": "user",
    "predicate": "попросил нарисовать", "object": "кота",
    "object_type": "topic", "kind": "one_off_request",
    "source_message_ids": [12],
}
WORLD_NEWS = {
    "subject": "минфин", "subject_type": "world",
    "predicate": "повысил", "object": "ключевую ставку",
    "object_type": "topic", "kind": "world_news", "source_message_ids": [13],
}
WORLD_NEWS_ON_PERSON = {
    "subject": "Вася", "subject_type": "user",
    "predicate": "сообщил новость", "object": "про ставку",
    "object_type": "topic", "kind": "world_news", "source_message_ids": [13],
}
CHARACTER = {
    "subject": "персонаж запроса", "subject_type": "character",
    "predicate": "является", "object": "качком", "object_type": "topic",
    "kind": "hypothetical_character", "source_message_ids": [14],
}
TEMPORARY = {
    "subject": "Вася", "subject_type": "user",
    "predicate": "ездил", "object": "в москву", "object_type": "topic",
    "kind": "temporary_event", "context": "3 ноября",
    "source_message_ids": [15],
}
PATTERN_NO_BASIS = {
    "subject": "Вася", "subject_type": "user",
    "predicate": "часто использует", "object": "сарказм",
    "object_type": "topic", "kind": "communication_pattern",
}
PATTERN_WITH_BASIS = dict(PATTERN_NO_BASIS, basis=[11, 12])


class FactsLLM:
    """Заглушка LLM: отдаёт заранее заданный ответ экстрактора.

    ``retry_response`` позволяет смоделировать путь восстановления: ответ на
    ретрай-промпт отличается от ответа первичной экстракции.
    """

    def __init__(self, response: str, retry_response: str | None = None,
                 primary_error: Exception | None = None):
        self.response = response
        self.retry_response = retry_response
        self.primary_error = primary_error
        self.system_prompts: list[str] = []

    async def generate(self, messages):
        system = messages[0]["content"]
        self.system_prompts.append(system)
        if system == _FACT_RETRY_SYSTEM_PROMPT:
            if self.retry_response is not None:
                return self.retry_response
            return self.response
        if self.primary_error is not None:
            raise self.primary_error
        return self.response

    async def embed(self, texts):  # pragma: no cover — vec в :memory: выключен
        return [[0.1] * settings.EMBEDDING_DIM for _ in texts]


@pytest_asyncio.fixture
async def db():
    service = DatabaseService(":memory:")
    await service.initialize()
    yield service
    await service.close()


def _llm(*items) -> FactsLLM:
    return FactsLLM(json.dumps(list(items), ensure_ascii=False))


async def _graph_facts(db) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT fact, target_user, attribution_method, assertion_kind, "
        "tg_message_id, forward_from, expires_at, origin FROM graph_facts")
    return [dict(row) for row in await cursor.fetchall()]


def _prompt_block(prompt: str, header: str) -> str:
    """Абзац контракта из текста промпта (до следующего пустого блока)."""
    start = prompt.index(header)
    tail = prompt[start:]
    end = tail.find("\n\n", len(header))
    return tail if end == -1 else tail[:end]


class TestPromptContract:
    """Промпт несёт смысловой контракт, а не лексический фильтр."""

    def test_prompt_lists_every_fact_class(self):
        for kind in FACT_KINDS:
            assert kind in FACT_EXTRACT_PROMPT, kind

    def test_prompt_keeps_f5_paragraph_and_prev_snapshot(self):
        assert FACT_EXTRACT_PROMPT.startswith(PREV_FACT_EXTRACT_PROMPT)
        assert "ФОКУС НА СОДЕРЖАНИИ:" in FACT_EXTRACT_PROMPT

    def test_classification_block_states_attribution_rules(self):
        block = _prompt_block(FACT_EXTRACT_PROMPT,
                             "КЛАССИФИКАЦИЯ И АТРИБУЦИЯ")
        # типы сущностей и запрет приписывать публичное человеку
        for token in ("subject_type", "object_type", "user", "world", "topic",
                      "character"):
            assert token in block, token
        assert "не становится личным фактом" in block
        assert "не становится биографией" in block
        # provenance и опора для обобщений
        assert "source_message_ids" in block
        assert "basis" in block
        # запрет писать ради количества
        assert "Лучше пустой список" in block

    def test_prompt_has_no_lexical_blacklist(self):
        """Никаких стоп-слов/регексов на имена и фразы (правило проекта)."""
        low = FACT_EXTRACT_PROMPT.casefold()
        for forbidden in ("blacklist", "whitelist", "стоп-слов", "стопслов",
                          "запрещённые слова", "regex", "регекс", "регулярн"):
            assert forbidden not in low, forbidden
        # Прод-примеры из наблюдения владельца не являются нормой промпта.
        assert not re.search(r"нарисуй кота|рисует кота|бренд товара|"
                             r"выведен из url", low)

    def test_classification_is_semantic_not_lexical(self):
        """Контракт строится на классах, а не на перечислении фраз."""
        block = _prompt_block(FACT_EXTRACT_PROMPT,
                             "КЛАССИФИКАЦИЯ И АТРИБУЦИЯ")
        enum_line = next(line for line in block.splitlines()
                         if "\"kind\"" in line)
        assert all(kind in enum_line for kind in FACT_KINDS)

    def test_retry_prompt_carries_same_class_contract(self):
        """Ретрай — обычный путь восстановления, а не «бесклассовая» форма.

        Иначе восстановленный ответ дефолтится в durable_fact и разовая просьба
        снова занимает личный пул (репро ревью: «попросил нарисовать кота» →
        target_user).
        """
        for kind in FACT_KINDS:
            assert kind in _FACT_RETRY_SYSTEM_PROMPT, kind
        for token in ("\"kind\"", "subject_type", "object_type", "basis",
                      "user", "world", "topic", "character"):
            assert token in _FACT_RETRY_SYSTEM_PROMPT, token
        # Форма ответа остаётся машинной: JSON-массив, ничего вокруг.
        assert "JSON-массив" in _FACT_RETRY_SYSTEM_PROMPT
        assert "верни []" in _FACT_RETRY_SYSTEM_PROMPT

    def test_retry_prompt_has_no_lexical_blacklist(self):
        low = _FACT_RETRY_SYSTEM_PROMPT.casefold()
        for forbidden in ("blacklist", "whitelist", "стоп-слов", "стопслов",
                          "запрещённые слова", "regex", "регекс", "регулярн"):
            assert forbidden not in low, forbidden
        assert not re.search(r"нарисуй кота|рисует кота|бренд товара|"
                             r"выведен из url", low)


class TestParsingAndAttribution:
    """Разбор читает класс/атрибуцию структурно (без новых вызовов LLM)."""

    def test_parser_keeps_class_and_attribution_fields(self):
        raw = json.dumps([DURABLE, WORLD_NEWS, PATTERN_WITH_BASIS],
                         ensure_ascii=False)
        facts, status = parse_fact_list_ex(raw)
        assert status == "ok"
        by_kind = {fact["kind"]: fact for fact in facts}
        assert by_kind["durable_fact"]["subject_type"] == "user"
        assert by_kind["world_news"]["subject_type"] == "world"
        assert by_kind["communication_pattern"]["basis"] == (11, 12)
        assert by_kind["durable_fact"]["source_message_ids"] == (11,)

    def test_unknown_class_is_not_silently_durable(self):
        raw = json.dumps([dict(DURABLE, kind="some_new_class")],
                         ensure_ascii=False)
        facts, status = parse_fact_list_ex(raw, warn=False)
        assert (facts, status) == ([], "invalid")

    def test_legacy_shape_defaults_to_durable(self):
        """Старый формат (без kind) — прежнее поведение, а не отказ."""
        raw = json.dumps([{"subject": "Ozon", "predicate": "быстрее чем",
                           "object": "Wildberries"}], ensure_ascii=False)
        facts, status = parse_fact_list_ex(raw)
        assert status == "ok"
        assert facts[0]["kind"] == FACT_KIND_DURABLE
        assert fact_durability_decision(facts[0])["personal"] is True

    def test_decision_matrix(self):
        cases = {
            "durable_fact": (True, True),
            "one_off_request": (False, False),
            "hypothetical_character": (False, False),
            "world_news": (True, False),
            "quote": (True, False),
            "temporary_event": (True, True),
            "communication_pattern": (False, False),   # без basis
        }
        payloads = {
            "durable_fact": DURABLE, "one_off_request": ONE_OFF,
            "hypothetical_character": CHARACTER, "world_news": WORLD_NEWS,
            "quote": {"subject": "автор канала", "subject_type": "world",
                      "predicate": "сказал", "object": "ставка вырастет",
                      "object_type": "topic", "kind": "quote"},
            "temporary_event": TEMPORARY,
            "communication_pattern": PATTERN_NO_BASIS,
        }
        for kind, (store, personal) in cases.items():
            facts, _ = parse_fact_list_ex(json.dumps([payloads[kind]]),
                                          warn=False)
            decision = fact_durability_decision(facts[0])
            assert (decision["store"], decision["personal"]) == (store, personal), kind

    def test_pattern_with_basis_is_allowed(self):
        facts, _ = parse_fact_list_ex(json.dumps([PATTERN_WITH_BASIS]),
                                      warn=False)
        decision = fact_durability_decision(facts[0])
        assert decision["store"] is True and decision["personal"] is True


class TestStorageConsequences:
    """Класс факта меняет запись, а не только текст промпта."""

    @pytest.mark.asyncio
    async def test_durable_fact_stored_with_provenance(self, db):
        memory = MemoryManager(db, _llm(DURABLE))
        await memory.memorize_facts(CHAT_ID, "Вася работает на заводе",
                                    "chat_history", tg_message_id=11,
                                    forward_from="")
        rows = await _graph_facts(db)
        assert len(rows) == 1
        assert rows[0]["fact"] == "вася работает на заводе"
        assert rows[0]["tg_message_id"] == 11
        assert memory.llm.system_prompts[0] == FACT_EXTRACT_PROMPT

    @pytest.mark.asyncio
    async def test_one_off_request_not_in_long_term_pool(self, db):
        memory = MemoryManager(db, _llm(DURABLE, ONE_OFF))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "Вася попросил нарисовать кота", "bot_direct_reply",
            USER)
        rows = await _graph_facts(db)
        assert [row["fact"] for row in rows] == ["вася работает на заводе"]
        assert result["episodic_skipped"] == 1
        assert result["saved"] == 1

    @pytest.mark.asyncio
    async def test_only_one_off_candidates_give_no_new_facts(self, db):
        memory = MemoryManager(db, _llm(ONE_OFF))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "нарисуй кота", "bot_direct_reply", USER)
        assert await _graph_facts(db) == []
        assert result["status"] == "no_new_facts"
        assert result["episodic_skipped"] == 1

    @pytest.mark.asyncio
    async def test_news_repost_not_attributed_to_user(self, db):
        memory = MemoryManager(db, _llm(WORLD_NEWS))
        await memory.memorize_facts(CHAT_ID, "переслал новость про ставку",
                                    "bot_direct_reply", USER,
                                    tg_message_id=13)
        rows = await _graph_facts(db)
        assert len(rows) == 1
        assert rows[0]["target_user"] is None          # не личный пул
        assert rows[0]["attribution_method"] == "world_knowledge"
        assert rows[0]["assertion_kind"] == "world_knowledge"

    @pytest.mark.asyncio
    async def test_public_news_claimed_as_person_fact_is_rejected(self, db):
        memory = MemoryManager(db, _llm(WORLD_NEWS_ON_PERSON))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "новость", "bot_direct_reply", USER)
        assert await _graph_facts(db) == []
        assert result["world_attributed_to_person"] == 1
        assert result["status"] == "no_new_facts"

    @pytest.mark.asyncio
    async def test_query_character_is_not_biography_and_raw_kept(self, db):
        await db.save_smart_message(
            4242, CHAT_ID, "нарисуй качка", None, 1_700_000_000, "text",
            "Вася", message_id=14)
        memory = MemoryManager(db, _llm(CHARACTER))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "нарисуй качка", "bot_direct_reply", USER)
        assert await _graph_facts(db) == []
        assert result["episodic_skipped"] == 1
        cursor = await db.db.execute("SELECT text FROM smart_messages WHERE chat_id = ?",
                                     (CHAT_ID,))
        assert [row["text"] for row in await cursor.fetchall()] == ["нарисуй качка"]

    @pytest.mark.asyncio
    async def test_temporary_event_gets_bounded_expiry(self, db):
        memory = MemoryManager(db, _llm(TEMPORARY))
        await memory.memorize_facts(CHAT_ID, "Вася ездил в Москву 3 ноября",
                                    "chat_history")
        rows = await _graph_facts(db)
        assert len(rows) == 1
        # chat_history иначе «вечно»; временное событие — с ограниченным TTL.
        assert rows[0]["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_pattern_requires_basis(self, db):
        memory = MemoryManager(db, _llm(PATTERN_NO_BASIS, PATTERN_WITH_BASIS))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "Вася шутит сарказмом", "bot_direct_reply", USER)
        rows = await _graph_facts(db)
        assert len(rows) == 1                     # сохранено только с опорой
        assert rows[0]["target_user"] == USER
        assert result["pattern_without_basis"] == 1
        assert result["saved"] == 1


class TestRecoveryPathKeepsClassification:
    """Путь восстановления (LLMError/timeout → retry) не теряет класс факта.

    Ретрай — не аварийная экзотика: при таймауте провайдера это обычный путь
    записи фактов. Поэтому классификация обязана выживать при восстановлении,
    иначе разовая просьба снова попадает в личный пул (репро ревью).
    """

    @pytest.mark.asyncio
    async def test_retry_one_off_request_not_in_long_term_pool(self, db):
        retry = json.dumps([ONE_OFF], ensure_ascii=False)
        memory = MemoryManager(
            db, FactsLLM("[]", retry_response=retry,
                         primary_error=LLMError("nano-gpt timeout")))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "Вася попросил нарисовать кота", "bot_direct_reply", USER)
        assert memory.llm.system_prompts[0] == FACT_EXTRACT_PROMPT
        # Первичная экстракция исчерпала bounded-повторы (LLMError), затем
        # ровно один вызов ретрай-промпта.
        assert memory.llm.system_prompts.count(_FACT_RETRY_SYSTEM_PROMPT) == 1
        assert memory.llm.system_prompts[-1] == _FACT_RETRY_SYSTEM_PROMPT
        assert await _graph_facts(db) == []            # ни записи, ни target_user
        assert result["episodic_skipped"] == 1
        assert result["saved"] == 0
        assert result["status"] == "no_new_facts"

    @pytest.mark.asyncio
    async def test_drift_then_retry_keeps_classification(self, db):
        drifted = json.dumps([dict(DURABLE, kind="almost_durable")],
                             ensure_ascii=False)
        retry = json.dumps([DURABLE, ONE_OFF], ensure_ascii=False)
        memory = MemoryManager(db, FactsLLM(drifted, retry_response=retry))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "Вася работает на заводе, попросил нарисовать кота",
            "bot_direct_reply", USER)
        assert memory.llm.system_prompts == [FACT_EXTRACT_PROMPT,
                                             _FACT_RETRY_SYSTEM_PROMPT]
        rows = await _graph_facts(db)
        assert [row["fact"] for row in rows] == ["вася работает на заводе"]
        assert rows[0]["target_user"] == USER
        assert result["episodic_skipped"] == 1
        assert result["saved"] == 1

    @pytest.mark.asyncio
    async def test_retry_news_not_attributed_to_person(self, db):
        retry = json.dumps([WORLD_NEWS], ensure_ascii=False)
        memory = MemoryManager(
            db, FactsLLM("[]", retry_response=retry,
                         primary_error=LLMError("nano-gpt timeout")))
        await memory._memorize_facts_inner(
            CHAT_ID, "переслал новость про ставку", "bot_direct_reply", USER)
        assert memory.llm.system_prompts[-1] == _FACT_RETRY_SYSTEM_PROMPT
        rows = await _graph_facts(db)
        assert len(rows) == 1
        assert rows[0]["target_user"] is None          # не личный пул
        assert rows[0]["attribution_method"] == "world_knowledge"


class TestHonestRejection:
    """Мусор модели → честный отказ, а не «успешная пустота»."""

    @pytest.mark.asyncio
    async def test_malformed_answer_is_rejected(self, db, caplog):
        memory = MemoryManager(db, FactsLLM("это не json вообще"))
        with caplog.at_level("WARNING"):
            result = await memory._memorize_facts_inner(
                CHAT_ID, "текст", "chat_history")
        assert await _graph_facts(db) == []
        assert result["status"] == "skipped"
        assert result["reason"] == "parse_error"
        assert any("facts lost" in r.message and "reason=not_json" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_valid_empty_list_is_empty_valid(self, db):
        memory = MemoryManager(db, FactsLLM("[]"))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "ничего важного", "chat_history")
        assert await _graph_facts(db) == []
        assert result["status"] == "no_new_facts"

    @pytest.mark.asyncio
    async def test_drifted_class_does_not_become_fact(self, db):
        drifted = dict(DURABLE, kind="almost_durable")
        memory = MemoryManager(db, _llm(drifted))
        result = await memory._memorize_facts_inner(
            CHAT_ID, "текст", "chat_history")
        assert await _graph_facts(db) == []
        assert result["status"] == "skipped"
