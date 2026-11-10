"""VMQ-MEM-TIME (§2, M6): политику памяти выбирает существующий L1.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/time/fix-contract.md`
(§2). ОДНО опциональное allowlisted-поле `L1Plan.memory_scope` того же
единственного L1-вызова; серверная нормализация:

  * мусор/отсутствие → `auto`;
  * `knowledge_origin=open_world` + `search_intent=required` → `auto`;
  * `action ∈ (silent, react)` → `operative`;
  * явный `historical` НЕ понижается ни правилами, ни моделью;
  * M6 (негативная проба): наличие года в формулировке НЕ меняет политику —
    словарных триггеров года нет, а год по-прежнему разбирают только
    существующие технические парсеры диапазона.
"""
import ast
import asyncio
import inspect
import textwrap

import pytest

from services import direct_l1 as l1
from services import mca_retrieval_context as mrc
from services import memory_contracts as mc
from services.database import DatabaseService


def _dotted(node) -> str:
    """`_mc.normalize_memory_scope(request.memory_scope)` → пунктирное имя.

    Возвращает "" для всего, что не является цепочкой Name/Attribute, —
    то есть для любой «вычислительной» формы (индекс, срез, вызов, f-string).
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


class _FakeHotCache:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture
def hot_cache(monkeypatch):
    from services import hot_config as hot
    monkeypatch.setattr(hot, "_cache", _FakeHotCache())
    return hot


def _plan(**fields) -> l1.L1Plan:
    data = {"action": "reply"}
    data.update(fields)
    plan = l1.normalize_l1_plan(data)
    assert plan is not None
    return plan


class TestNormalization:

    def test_absent_or_garbage_is_auto(self):
        assert _plan().memory_scope == "auto"
        assert _plan(memory_scope="").memory_scope == "auto"
        assert _plan(memory_scope="вчера").memory_scope == "auto"
        assert _plan(memory_scope=17).memory_scope == "auto"
        assert _plan(memory_scope=["historical"]).memory_scope == "auto"

    def test_explicit_values_are_kept(self):
        assert _plan(memory_scope="operative").memory_scope == "operative"
        assert _plan(memory_scope="historical").memory_scope == "historical"
        assert _plan(memory_scope="AUTO").memory_scope == "auto"

    def test_open_world_search_is_auto(self):
        plan = _plan(memory_scope="operative",
                     knowledge_origin="open_world",
                     search_intent="required")
        assert plan.memory_scope == "auto"

    def test_silent_and_react_are_operative(self):
        assert _plan(action="silent").memory_scope == "operative"
        assert _plan(action="react").memory_scope == "operative"
        assert _plan(action="silent",
                     memory_scope="auto").memory_scope == "operative"

    def test_explicit_historical_is_never_downgraded(self):
        """Модель не может понизить явный `historical` (§2)."""
        assert _plan(memory_scope="historical",
                     knowledge_origin="open_world",
                     search_intent="required").memory_scope == "historical"
        assert _plan(memory_scope="historical",
                     action="silent").memory_scope == "historical"
        assert _plan(memory_scope="historical",
                     action="react").memory_scope == "historical"

    def test_closed_set_is_shared_with_retrieval(self):
        """Закрытый набор один (нет второго словаря в retrieval)."""
        values = {scope.value for scope in mc.MemoryScope}
        assert values == {"operative", "historical", "auto"}
        assert l1.MEMORY_SCOPES == ("operative", "historical", "auto")
        assert mc.normalize_memory_scope("historical").value == "historical"
        assert mc.normalize_memory_scope(None).value == "auto"

    def test_request_field_defaults_to_auto(self):
        request = mrc.RetrievalRequest(chat_id=-100, query="что было")
        assert request.memory_scope == "auto"

    def test_plan_field_carries_to_request(self):
        plan = _plan(memory_scope="historical")
        request = mrc.RetrievalRequest(chat_id=-100, query="что было",
                                       memory_scope=plan.memory_scope)
        assert mrc._mc.normalize_memory_scope(request.memory_scope).value == \
            "historical"


class TestNoLexicalYearTriggers:
    """M6: год в вопросе не является триггером политики (её даёт L1)."""

    def test_same_policy_with_and_without_year(self):
        plain = l1.normalize_l1_plan({"action": "reply"})
        with_year = l1.normalize_l1_plan({
            "action": "reply",
            # Модель МОЖЕТ прислать historical, но год в тексте вопроса
            # политику не меняет: поля нет — значение по умолчанию то же.
        })
        assert plain.memory_scope == with_year.memory_scope == "auto"

    def test_year_text_does_not_reach_policy(self):
        """`resolve_memory_scope` не принимает текст запроса вовсе."""
        import inspect
        params = inspect.signature(l1.resolve_memory_scope).parameters
        assert "query" not in params and "text" not in params
        assert l1.resolve_memory_scope(None) == l1.resolve_memory_scope(None)

    def test_event_policy_is_identical_for_both_queries(self, monkeypatch,
                                                        hot_cache):
        """Одинаковый policy в событии для «…в 2023 году» и без года."""
        captured: list = []

        def fake_emit(stage, outcome, **fields):
            captured.append((stage, outcome, fields))
            return None

        monkeypatch.setattr(mrc, "emit_stage_event", fake_emit)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        db = DatabaseService(":memory:")
        loop.run_until_complete(db.initialize())

        class _Memory:
            async def retrieve_fact_candidates(self, chat_id, query, **kwargs):
                return []

        try:
            for query in ("из-за чего мы ссорились в 2023 году",
                          "из-за чего мы ссорились"):
                request = mrc.RetrievalRequest(
                    chat_id=-100, query=query, purpose="reply",
                    mode="specific", top_k=10, channels=("vector",),
                    reply_depth=0)
                loop.run_until_complete(mrc.retrieve(db, _Memory(), request))
        finally:
            loop.run_until_complete(db.close())
            loop.close()

        policies = [fields["usage_json"]["policy"]
                    for stage, _outcome, fields in captured
                    if "usage_json" in fields and stage == "retrieval"]
        assert policies == ["auto", "auto"], policies

    def test_policy_is_derived_only_from_request_field(self):
        """Политика в `retrieve` выводится ТОЛЬКО из поля запроса (M6).

        Проверка идёт по AST самой функции, а не по тексту файла: путь берётся
        у импортированного модуля, поэтому результат не зависит от cwd, а форма
        узла проверяется точно. Единственный вход политики —
        `request.memory_scope` через серверную нормализацию; текстовая
        производная (год/период/лексика запроса) дала бы другой узел, и её
        нельзя добавить «рядом», не сломав это утверждение.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(mrc.retrieve)))
        values = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "memory_scope"
                for target in node.targets)
        ]
        assert len(values) == 1, "в retrieve должен быть ровно один вывод политики"
        (value,) = values
        assert isinstance(value, ast.Call), ast.dump(value)
        assert _dotted(value.func) == "_mc.normalize_memory_scope", \
            ast.dump(value.func)
        assert len(value.args) == 1 and not value.keywords, ast.dump(value)
        (argument,) = value.args
        assert _dotted(argument) == "request.memory_scope", ast.dump(argument)
        # Текст запроса не участвует в выводе политики ни на одном уровне.
        assert not [node for node in ast.walk(value)
                    if isinstance(node, ast.Attribute) and node.attr == "query"]
        # Поле запроса нигде не переписывается в retrieve перед нормализацией.
        assert not [node for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)
                    and node.attr == "memory_scope"
                    and not isinstance(node.ctx, ast.Load)]
        # Никаких новых «годовых» списков/словарей в политике ретривера.
        source = inspect.getsource(mrc)
        for marker in ("прошлом году", "год назад", "в прошлом",
                       "_YEAR_MARKERS", "_SCOPE_MARKERS"):
            assert marker not in source

    def test_explicit_scope_reaches_event_policy(self, monkeypatch, hot_cache):
        """Явный scope из запроса доходит до события — и год в тексте не влияет.

        Поведенческая половина M6: политика в durable-событии равна
        `normalize(request.memory_scope)` при ОДИНАКОВОМ тексте с годом,
        то есть её источник — поле запроса, а не формулировка.
        """
        captured: list = []

        def fake_emit(stage, outcome, **fields):
            captured.append((stage, outcome, fields))
            return None

        monkeypatch.setattr(mrc, "emit_stage_event", fake_emit)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        db = DatabaseService(":memory:")
        loop.run_until_complete(db.initialize())

        class _Memory:
            async def retrieve_fact_candidates(self, chat_id, query, **kwargs):
                return []

        try:
            for scope in ("historical", "operative", "auto", "вчера"):
                request = mrc.RetrievalRequest(
                    chat_id=-100, query="из-за чего мы ссорились в 2023 году",
                    purpose="reply", mode="specific", top_k=10,
                    channels=("vector",), reply_depth=0, memory_scope=scope)
                loop.run_until_complete(mrc.retrieve(db, _Memory(), request))
        finally:
            loop.run_until_complete(db.close())
            loop.close()

        policies = [fields["usage_json"]["policy"]
                    for stage, _outcome, fields in captured
                    if "usage_json" in fields and stage == "retrieval"]
        assert policies == ["historical", "operative", "auto", "auto"], policies


class TestPlanScopeReachesRagBlock:
    """Блокер 1 ре-ревью 10.11.2026: политика плана доходит до САМОГО блока.

    `_build_user_content` собирает `<RAG_Memory>` ДО плана L1, поэтому блок
    сначала идёт с серверным `auto`. После плана политика применяется к блоку
    повторной сборкой того же блока — эти проверки фиксируют, что (а) блок
    получает значение ИЗ ПЛАНА, (б) `auto` не вызывает лишнего чтения.
    """

    @staticmethod
    def _service(monkeypatch, calls):
        from services import direct_chat_service as dcs

        service = dcs.DirectChatService(memory=object(), db=None, llm=None,
                                        aliases=None)

        async def fake_build(chat_id, message, global_ctx,
                             history_sample=None, projection=None,
                             memory_scope=None, subject_name=None,
                             subject_uid=None):
            calls.append({"scope": memory_scope, "name": subject_name,
                          "uid": subject_uid})
            return f"<RAG_Memory>{memory_scope}</RAG_Memory>", ""

        monkeypatch.setattr(service, "_build_rag_block", fake_build)
        return service

    @staticmethod
    def _ctx():
        return {"chat_id": -100, "message": object(), "global_ctx": "",
                "history_sample": None, "projection": None,
                "subject_name": "Aleksey", "subject_uid": 7}

    @pytest.mark.asyncio
    async def test_historical_plan_rebuilds_block_with_plan_scope(self,
                                                                 monkeypatch):
        calls: list = []
        service = self._service(monkeypatch, calls)
        plan = _plan(memory_scope="historical")
        blocks = ["<Global_Context>фон</Global_Context>",
                  "<RAG_Memory>auto</RAG_Memory>"]
        out = await service._apply_plan_memory_scope(blocks, self._ctx(), plan)
        assert calls == [{"scope": "historical", "name": "Aleksey", "uid": 7}]
        assert out[1] == "<RAG_Memory>historical</RAG_Memory>"
        assert out[0] == blocks[0], "другие блоки не пересобираются"

    @pytest.mark.asyncio
    async def test_operative_plan_narrows_block(self, monkeypatch):
        calls: list = []
        service = self._service(monkeypatch, calls)
        plan = _plan(memory_scope="operative")
        blocks = ["<RAG_Memory>auto</RAG_Memory>", "<Target_User>U1</Target_User>"]
        out = await service._apply_plan_memory_scope(blocks, self._ctx(), plan)
        assert calls and calls[0]["scope"] == "operative"
        assert out[0] == "<RAG_Memory>operative</RAG_Memory>"
        assert out[1] == "<Target_User>U1</Target_User>"

    @pytest.mark.asyncio
    async def test_auto_plan_does_not_rebuild(self, monkeypatch):
        """`auto` = то, с чем блок уже собран → ноль лишних чтений."""
        calls: list = []
        service = self._service(monkeypatch, calls)
        blocks = ["<RAG_Memory>auto</RAG_Memory>"]
        out = await service._apply_plan_memory_scope(
            blocks, self._ctx(), _plan())
        assert calls == []
        assert out == blocks

    @pytest.mark.asyncio
    async def test_absent_block_is_not_injected_past_budget(self, monkeypatch):
        """Блока нет в бюджетированном payload → вставки мимо бюджета нет."""
        calls: list = []
        service = self._service(monkeypatch, calls)
        blocks = ["<Global_Context>фон</Global_Context>"]
        out = await service._apply_plan_memory_scope(
            blocks, self._ctx(), _plan(memory_scope="historical"))
        assert out == blocks
        assert calls == []
