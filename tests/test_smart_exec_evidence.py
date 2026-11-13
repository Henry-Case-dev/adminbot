"""SMART-EXECUTION-RELIABILITY-01 · C2/C3 — потолки evidence и путь до payload.

Проверяется контракт стадий C2/C3 (owner input 2026-11-14, §C2/§C3):

* SXR-C2-01: аналогичные искусственные потолки сняты там, где они жили в
  границах среза: top-K middle/окно эпизода/фрагменты памяти, output-бюджет
  DiagnosticEvidenceBundle, claims-лимит, stack frames/facts, output ceiling
  longform, число fetch-шагов плана и срез текста запроса. Явная политика
  вызова/env сохраняется; заводская замена «одним числом» не вводится.
* SXR-C2-02: семантический отбор сохранён, первая порция не выдаётся за
  исчерпывающую: страница/курсор/`next_line_start` дают продолжение.
* SXR-C3-01: 7 шагов результата: инструмент → структурированный результат →
  ToolResult/evidence envelope → tool-loop → context composer → LLM payload →
  финальный ответ. Сквозной тест идёт по реальному SourceReader и реальному
  `chat_with_tools` с fake-LLM, который строит ответ ТОЛЬКО из дошедшего
  payload.
* SXR-C3-02: при бюджете 0 секционные/символьные ограничители не уничтожают
  контекст; повторного усечения уже ограниченного результата нет; при явном
  малом бюджете работает существующая упаковка с continuation, а не silent
  `text[:N]`.

RED-proof: тесты падают на базе 36dd6b23 (заводские 60/40/10, лимит 4000,
claims≤10, frames≤120/2000, ceiling 16384, fetch≤3, срез query[:256]).
"""
from __future__ import annotations

import copy
import json
import os
import re
from unittest.mock import MagicMock

import pytest

from services import direct_context_composer as comp
from services import evidence_bundle as eb
from services import response_extent as rext
from services import source_reader as sr
from services import tool_result
from services.llm_client import LLMChatResult, LLMToolCall
from services.tool_loop import chat_with_tools

REPO = "Henry-Case-dev/adminbot"
SHA = "0123456789abcdef0123456789abcdef01234567"

_ENV_KEYS = (
    "CHAT_MIDDLE_MAX_MESSAGES",
    "CHAT_EPISODE_MAX_MESSAGES",
    "CHAT_EPISODE_MAX_COUNT",
    "CHAT_THREAD_WALK_MAX",
    "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS",
    "DIRECT_TOOL_PLAN_MAX_FETCH_STEPS",
    "SOURCE_READ_MAX_FILES",
    "SOURCE_READ_MAX_DEPTH",
    "SOURCE_READ_MAX_REQUESTS",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for name in _ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    # SourceReader: локального snapshot нет, только stub-провайдер.
    monkeypatch.setattr(type(sr.settings), "SOURCE_READ_ENABLED", True)
    monkeypatch.setattr(type(sr.settings), "SOURCE_READ_GITHUB_TOKEN", "")
    monkeypatch.setattr(type(sr.settings), "SELF_DIAG_LOCAL_REPO_ROOT", "")
    # SXR-E добавил второй корень того же процесса (runtime identity), который
    # не управляется SELF_DIAG_LOCAL_REPO_ROOT. Модуль проверяет путь через
    # stub-провайдер, поэтому локальный источник отключается точечно — тот же
    # смысл, что и пустой configured root выше, без ослабления проверок.
    monkeypatch.setattr(
        sr, "resolve_local_source",
        lambda *a, **kw: {"usable": False, "root": None})

    async def _budgets_off(chat_id=None):
        return False

    if hasattr(sr, "budget_limits_enforced"):
        monkeypatch.setattr(sr, "budget_limits_enforced", _budgets_off)
    yield


# ── SourceReader: реальный файл через stub-провайдер (без сети) ─────────────

class _StubGitHub:
    name = sr.PROVIDER_GITHUB
    uses_auth = False
    network_calls = 0

    def __init__(self, files: dict[str, bytes | str]) -> None:
        self.files = {
            path: (data.encode("utf-8") if isinstance(data, str) else data)
            for path, data in files.items()}

    async def search_repos(self, query, *, limit=5):
        return []

    async def resolve_repo(self, owner, repo):
        self.network_calls += 1
        return sr.RepoInfo(owner=owner, name=repo, default_branch="main",
                           language="Python")

    async def resolve_commit(self, repo, ref):
        self.network_calls += 1
        return SHA

    async def list_tree(self, repo, commit):
        self.network_calls += 1
        return sr.TreeListing(
            entries=[sr.TreeEntry(path=path, kind="blob", sha="",
                                  size=len(data))
                     for path, data in sorted(self.files.items())])

    async def read_file(self, repo, commit, path, *, blob_sha=""):
        self.network_calls += 1
        data = self.files.get(path)
        if data is None:
            return None
        return sr.SourceFile(path=path, data=data, sha="", size=len(data),
                             endpoint=sr.ENDPOINT_CONTENTS)


def _big_source(lines: int = 200) -> dict[str, str]:
    body = "\n".join(f"line_{i} = 'evidence-{i}'" for i in range(1, lines + 1))
    return {"services/evidence.py": body + "\n"}


# ── fake-LLM: финальный ответ строится из дошедшего payload ────────────────

class _PipelineLLM:
    """1-й вызов — tool call; 2-й — ответ строго по маркеру из role:tool."""

    def __init__(self, tool_name: str, arguments: dict, marker: str) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.marker = marker
        self.calls = 0
        self.all_messages: list = []
        self.answer = ""

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append(copy.deepcopy(messages))
        if self.calls == 0:
            self.calls += 1
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(id="call_1", name=self.tool_name,
                                        arguments=json.dumps(self.arguments))],
                finish_reason="tool_calls")
        tool_content = "\n".join(
            str(m.get("content") or "") for m in messages
            if m.get("role") == "tool")
        found = re.search(re.escape(self.marker), tool_content)
        self.answer = ("Итог: " + found.group(0)) if found else "Итог: потеряно"
        return LLMChatResult(content=self.answer, tool_calls=None,
                             finish_reason="stop")

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):       # pragma: no cover - fallback не нужен
        self.all_messages.append(copy.deepcopy(messages))
        return "fallback"


class _StaticRouter:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, arguments))
        return self.output


async def _loop_roundtrip(tool_name: str, arguments: dict, output: str,
                          marker: str, *, user_text: str = "вопрос",
                          tools=None):
    llm = _PipelineLLM(tool_name, arguments, marker)
    router = _StaticRouter(output)
    final = await chat_with_tools(
        llm, [{"role": "user", "content": user_text}],
        tools=tools if tools is not None else [{"type": "function"}],
        router=router, ctx=MagicMock())
    return llm, router, final


# ═══════════════════════════════════════════════════════════════════════════
# SXR-C3-01: 7 шагов реального SourceReader до финального ответа
# ═══════════════════════════════════════════════════════════════════════════

class TestSevenStepDeliverySourceReader:
    @pytest.mark.asyncio
    async def test_document_result_reaches_payload_and_final_answer(
            self, tmp_path):
        # ── шаг 1: что реально получил инструмент ─────────────────────────
        body = _big_source()
        reader = sr.SourceReader(provider=_StubGitHub(body), repo_origin=REPO)
        payload = await reader.run(operation=sr.OPERATION_READ, repo=REPO,
                                   ref=SHA, path="services/evidence.py",
                                   follow=False)
        assert payload["status"] == sr.STATUS_OK
        assert payload["verified"] is True
        assert payload["file_total_lines"] == 200
        assert payload["snippet"].endswith("line_200 = 'evidence-200'")

        # ── шаг 2: что вошло в структурированный результат ────────────────
        serialized = json.dumps(payload, ensure_ascii=False)
        assert len(serialized) > 4000        # старый 4k-cap срезал бы хвост
        info = tool_result.classify_output("read_source_code", serialized)
        assert info["status"] == tool_result.STATUS_OK
        assert info["data"]["path"] == "services/evidence.py"
        assert info["truncated"] is False

        # ── шаг 3: что сохранилось в ToolResult/evidence envelope ────────
        envelope = tool_result.make_envelope(
            0, "read_source_code", "fp", info, metered=False,
            duplicate=False, attempt=1, out_chars=len(serialized))
        assert envelope["status"] == tool_result.STATUS_OK
        assert envelope["data"]["line_range"] == [1, 200]
        assert payload["source_id"] in envelope["evidence_refs"]
        assert envelope["out_chars"] == len(serialized)

        # ── шаг 5: что прошло через context composer ─────────────────────
        fragment = comp.ContextFragment(
            kind=comp.KIND_EXTERNAL_EVIDENCE,
            source_id=f"evidence:{payload['source_id']}",
            text=payload["snippet"],
            role=comp.ROLE_MEMORY,
            authority=comp.AUTHORITY_PRIMARY,
            timestamp_utc=1700000000)
        selection = comp.build_context_selection(
            current_text="что в файле evidence.py?",
            memory=(fragment,), budget_tokens=0)
        assert selection.memory and selection.memory[0].text == \
            payload["snippet"]
        assert selection.provenance.dropped == ()
        composed_text = "\n".join(f.text for f in selection.fragments())
        assert "line_200 = 'evidence-200'" in composed_text

        # ── шаги 4/6/7: tool-loop → LLM payload → финальный ответ ─────────
        llm, router, final = await _loop_roundtrip(
            "read_source_code", {"path": "services/evidence.py"}, serialized,
            "evidence-200", user_text=composed_text)
        assert router.calls == [("read_source_code",
                                 {"path": "services/evidence.py"})]
        second = llm.all_messages[1]
        assert [m["role"] for m in second] == ["user", "assistant", "tool"]
        assert second[0]["content"] == composed_text
        tool_msg = second[2]
        assert tool_msg["tool_call_id"] == "call_1"
        # Никакого повторного усечения уже сформированного результата.
        assert tool_msg["content"] == serialized
        assert len(tool_msg["content"]) > 4000
        assert final == "Итог: evidence-200"


# ── шаги 3–6 для остальных типов инструментов (формы их результатов) ──────

_MARKER = "EVIDENCE-MARKER-END"


def _search_output() -> str:
    blocks = [f"Заголовок {i}\nсниппет {i} " + "x" * 180 +
              f"\nhttps://example.org/{i}" for i in range(1, 31)]
    return "\n\n".join(blocks) + f"\n\n{_MARKER}"


def _memory_output() -> str:
    items = [{"ref": f"msg:{i}", "text": f"фрагмент памяти {i} " + "y" * 160}
             for i in range(1, 21)]
    return json.dumps({"status": "ok", "items": items,
                       "tail": _MARKER}, ensure_ascii=False)


def _vision_output() -> str:
    return json.dumps({"status": "ok",
                       "text": "распознанный текст " + "z" * 5000,
                       "tail": _MARKER}, ensure_ascii=False)


def _transcript_output() -> str:
    return "транскрипт " + "w" * 6000 + f"\n{_MARKER}"


def _factcheck_output() -> str:
    return json.dumps({
        "status": "ok",
        "claims": [{"claim": f"утверждение {i}", "verdict": "supported",
                    "note": "n" * 300} for i in range(1, 26)],
        "tail": _MARKER}, ensure_ascii=False)


@pytest.mark.parametrize("tool_name,output", [
    ("execute_web_search", _search_output()),
    ("query_chat_memory", _memory_output()),
    ("recognize_image", _vision_output()),
    ("transcribe_audio", _transcript_output()),
    ("run_factcheck", _factcheck_output()),
])
@pytest.mark.asyncio
async def test_all_tool_types_keep_full_result_in_payload(tool_name, output):
    """Один loop не режет результат даже далеко за старыми 4k/10-потолками."""
    llm, router, final = await _loop_roundtrip(
        tool_name, {"query": "q"}, output, _MARKER)
    tool_msg = [m for m in llm.all_messages[1] if m["role"] == "tool"][0]
    assert tool_msg["content"] == output
    assert len(tool_msg["content"]) > 4000
    assert final == f"Итог: {_MARKER}"
    info = tool_result.classify_output(tool_name, output)
    assert info["status"] == tool_result.STATUS_OK


# ═══════════════════════════════════════════════════════════════════════════
# SXR-C2-01 / SXR-C3-02: снятые caps + границы + негативные сценарии
# ═══════════════════════════════════════════════════════════════════════════

def _row(index: int, ts: int, text: str | None = None) -> dict:
    return {"id": index, "tg_message_id": 1000 + index, "timestamp": ts,
            "text": text if text is not None else f"сообщение {index}",
            "user_id": 1}


class TestComposerCaps:
    def test_middle_top_k_factory_cap_removed(self):
        rows = [_row(i, 1000 + i) for i in range(1, 76)]
        assert comp.middle_max_messages() == 0
        selected = comp.select_middle(rows, query="сообщение",
                                      chain_tg_ids=set(),
                                      participant_ids=set(), top_k=0)
        assert len(selected) == 75        # было бы 60 при заводском top-K
        # Хронологический порядок сохранён, ничего не выдумано.
        assert [r["id"] for r in selected] == list(range(1, 76))

    def test_middle_explicit_policy_still_applies(self, monkeypatch):
        monkeypatch.setenv("CHAT_MIDDLE_MAX_MESSAGES", "5")
        rows = [_row(i, 1000 + i) for i in range(1, 21)]
        assert comp.middle_max_messages() == 5
        selected = comp.select_middle(rows, query="сообщение",
                                      chain_tg_ids=set(),
                                      participant_ids=set(),
                                      top_k=comp.middle_max_messages())
        assert len(selected) == 5

    def test_middle_garbage_policy_is_no_cap_not_default(self, monkeypatch):
        monkeypatch.setenv("CHAT_MIDDLE_MAX_MESSAGES", "abc")
        assert comp.middle_max_messages() == 0
        monkeypatch.setenv("CHAT_MIDDLE_MAX_MESSAGES", "-3")
        assert comp.middle_max_messages() == 0

    def test_episode_window_factory_cap_removed(self):
        rows = [_row(i, 1000 + i) for i in range(1, 51)]
        assert comp.episode_max_messages() == 0
        span = comp.compute_episode_span(rows, 1025, gap_seconds=300,
                                         max_messages=0)
        assert span is not None
        start, end, reason = span
        assert (start, end) == (0, 49)    # было бы окно 40 вокруг хита
        assert "cap_applied" not in reason

    def test_episode_explicit_window_boundary(self, monkeypatch):
        monkeypatch.setenv("CHAT_EPISODE_MAX_MESSAGES", "10")
        rows = [_row(i, 1000 + i) for i in range(1, 51)]
        span = comp.compute_episode_span(
            rows, 1025, gap_seconds=300,
            max_messages=comp.episode_max_messages())
        assert span is not None and "cap_applied" in span[2]

    @pytest.mark.asyncio
    async def test_memory_fragment_cap_removed(self):
        class _Cand:
            entity_type = "graph_fact"
            sent_at = 1700000000
            author_id = 1
            entity_id = ""

            def __init__(self, index):
                self.id = f"fact:{index}"
                self.preview = f"факт {index}"

        candidates = [_Cand(i) for i in range(1, 26)]
        fragments, raw = await comp.collect_memory_fragments(
            None, chat_id=1, candidates=candidates)
        assert raw == 25
        assert len(fragments) == 25       # заводской лимит 10 удалён
        assert fragments[-1].source_id.endswith(":25")

    @pytest.mark.asyncio
    async def test_memory_fragment_explicit_boundary(self):
        class _Cand:
            entity_type = "graph_fact"
            sent_at = 0
            author_id = None
            entity_id = ""

            def __init__(self, index):
                self.id = f"fact:{index}"
                self.preview = f"факт {index}"

        fragments, _ = await comp.collect_memory_fragments(
            None, chat_id=1, candidates=[_Cand(i) for i in range(1, 6)],
            max_fragments=2)
        assert len(fragments) == 2


class TestEvidenceBundleCaps:
    def _source(self, index: int):
        return eb.SourceEvidence(
            kind="logs", status=eb.STATUS_OK,
            observed_at="2026-11-14T00:00:00+00:00",
            source_id=f"probe:{index}", owner="collector",
            scope="instance", latency_ms=1,
            coverage=eb.coverage(("local_logs",), complete=True),
            reason_code=None, declared=True, configured=True,
            probe_succeeded=True, healthy=None,
            facts={"payload": "x" * 300, "index": index},
            not_checked=(), redaction=eb.redaction(0, ()))

    def _bundle(self, sources=40, claims=15):
        srcs = [self._source(i) for i in range(sources)]
        refs = [f"probe:{i}" for i in range(claims)]
        claim_rows = [eb.claim(eb.CLAIM_OBSERVED, f"факт {i}", [ref])
                      for i, ref in enumerate(refs)]
        return eb.build_bundle(
            request_id="req-c2", chat_scope="current_chat",
            scope="current_chat", sources=srcs, claims=claim_rows,
            access={"resource_scope": "current_chat"},
            observed_at="2026-11-14T00:00:00+00:00", latency_ms=1,
            runtime={"service_identity": "unknown"})

    def test_page_default_has_no_artificial_budget(self):
        bundle = self._bundle()
        page, next_offset = eb.render_page(bundle)
        assert next_offset == 40
        assert len(page["sources"]) == 40
        assert len(page["claims"]) == 15      # жёсткий claims≤10 удалён
        assert page["claims_truncated"] is False
        assert "truncated" not in page or page["truncated"] is False
        assert page["coverage"]["output"]["state"] == "complete"

    def test_page_explicit_budget_still_paginates_with_continuation(self):
        bundle = self._bundle()
        page, next_offset = eb.render_page(bundle, max_chars=2500)
        assert 0 < next_offset < 40
        assert page["truncated"] is True
        assert page["page"]["next_offset"] == next_offset
        assert page["page"]["total_sources"] == 40
        omitted = page["page"].get("omitted_source_ids")
        if omitted is not None:
            assert len(omitted) == 40 - next_offset
        page2, next2 = eb.render_page(bundle, max_chars=2500,
                                      offset=next_offset)
        shown = {s["source_id"] for s in page["sources"]}
        shown2 = {s["source_id"] for s in page2["sources"]}
        assert shown and shown2 and not (shown & shown2)
        assert next2 > next_offset

    def test_facts_text_default_is_complete_and_explicit_cap_is_visible(self):
        bundle = self._bundle(sources=3, claims=0)
        full = eb.render_facts_text(bundle)
        assert "[facts_budget_exceeded]" not in full
        assert "probe:2" in full
        cut = eb.render_facts_text(bundle, max_chars=120)
        assert "[facts_budget_exceeded]" in cut

    def test_stack_summary_default_keeps_all_frames(self):
        lines = ["Traceback (most recent call last):"]
        for index in range(150):
            lines.append(f'  File "/app/s{index}.py", line {index + 1}, '
                         f'in fn_{index}')
            lines.append("    return x")
        lines.append("RuntimeError: boom")
        text = "\n".join(lines)
        page = eb.stack_summary(text)
        assert page["frame_count"] == 150
        assert page["shown_frames"] == 150     # было бы ≤120/по бюджету 2000
        assert page["next_cursor"] == ""
        assert page["coverage"]["state"] == eb.COVERAGE_COMPLETE
        bounded = eb.stack_summary(text, budget_chars=700)
        assert 0 < bounded["shown_frames"] < 150
        assert bounded["next_cursor"].startswith("frame:")


class TestResponseExtentCaps:
    def test_fetch_step_factory_cap_removed(self):
        urls = " ".join(f"https://u{i}.example/" for i in range(6))
        plan = rext.build_tool_plan(f"сравни {urls}",
                                    available_tools={"fetch_article"})
        assert [s["arguments"]["url"] for s in plan] == [
            f"https://u{i}.example/" for i in range(6)]

    def test_fetch_step_explicit_policy_boundary(self, monkeypatch):
        urls = " ".join(f"https://u{i}.example/" for i in range(4))
        monkeypatch.setenv("DIRECT_TOOL_PLAN_MAX_FETCH_STEPS", "3")
        assert rext.build_tool_plan(
            f"сравни {urls}", available_tools={"fetch_article"}) == []
        monkeypatch.setenv("DIRECT_TOOL_PLAN_MAX_FETCH_STEPS", "0")
        assert len(rext.build_tool_plan(
            f"сравни {urls}", available_tools={"fetch_article"})) == 4

    def test_web_query_is_not_sliced(self):
        long_tail = "оченьдлинныйпоисковыйзапрос" * 40
        plan = rext.build_tool_plan(
            f"сравни https://a.example/x и https://b.example/y "
            f"и проверь в интернете {long_tail}",
            available_tools={"fetch_article", "execute_web_search"})
        step = [s for s in plan if s["tool"] == "execute_web_search"][0]
        assert len(step["arguments"]["query"]) > 256
        assert step["arguments"]["query"].endswith(long_tail)

    def test_longform_output_no_artificial_ceiling(self, monkeypatch):
        from config import settings as settings_mod
        monkeypatch.setattr(type(settings_mod.settings),
                            "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS",
                            20000, raising=False)
        assert rext.longform_max_output_tokens() == 20000
        monkeypatch.setattr(type(settings_mod.settings),
                            "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS",
                            0, raising=False)
        assert rext.longform_max_output_tokens() is None


class TestNoDoubleTruncationAndPacking:
    @pytest.mark.asyncio
    async def test_paged_result_reaches_payload_byte_identical(self):
        bundle = TestEvidenceBundleCaps()._bundle(sources=30, claims=0)
        page_json, next_offset = eb.render_json(bundle, max_chars=3000)
        assert next_offset < 30
        llm, _router, final = await _loop_roundtrip(
            "inspect_runtime", {"probe": "logs"}, page_json,
            "probe:29" if "probe:29" in page_json else "probe:0")
        tool_msg = [m for m in llm.all_messages[1] if m["role"] == "tool"][0]
        # Уже ограниченный результат не режется ВТОРОЙ раз.
        assert tool_msg["content"] == page_json
        decoded = json.loads(tool_msg["content"])
        assert decoded["page"]["omitted_source_ids"]
        assert final.startswith("Итог: ")

    def test_budget_zero_never_drops_evidence(self):
        rows = [_row(i, 1000 + i, text="фрагмент " * 200)
                for i in range(1, 40)]
        fragments = tuple(comp.row_to_fragment(r, role=comp.ROLE_MEMORY)
                          for r in rows)
        selection = comp.build_context_selection(
            current_text="вопрос", memory=fragments, budget_tokens=0)
        assert len(selection.memory) == 39
        assert selection.provenance.dropped == ()
        assert sum(len(f.text) for f in selection.fragments()) > 60_000

    def test_real_window_uses_existing_packing_with_reference(self):
        huge = "слово " * 20_000
        rows = [_row(1, 1000, text=huge)]
        fragments = tuple(comp.row_to_fragment(r, role=comp.ROLE_THREAD)
                          for r in rows)
        selection = comp.build_context_selection(
            current_text="вопрос", thread=fragments, budget_tokens=2000)
        dropped = selection.provenance.dropped + \
            selection.provenance.overflow_parts
        assert dropped, "физическое окно должно быть видимо в provenance"
        reasons = {entry.get("reason_code") for entry in dropped}
        assert reasons <= {"budget_exceeded", "compressed",
                           "physical_overflow", "low_value_memory"}
        assert "compressed" in reasons
        # Важнейшее evidence сохранено, а не выброшено: сжатая голова + ссылка
        # на полный источник остаются в контексте.
        text = "\n".join(f.text for f in selection.fragments())
        assert "слово" in text
        assert "[сокращено по бюджету" in text
