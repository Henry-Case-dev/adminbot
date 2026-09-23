"""S10 round1026 (`summary-deploy-round1026`, ADR-1026-12 D2/D3/D6/D8) —
§114-предполётный harness (11 сценариев, **0 реальных отправок**) + инварианты
активации Hybrid-пайплайна (§107) + границы/§116/§117.

Покрытие: REQ-S10-01/-03/-04/-06/-07/-08/-11/-12/-13; SC-01…SC-13.

Сценарии §114 (все 11): (1) несколько параллельных разговоров; (2) короткие
важные ответы; (3) длинные сообщения; (4) `reply_to`; (5) упоминания; (6) почти
пустой лог; (7) невалидный JSON L1; (8) ошибка LLM; (9) ошибка генерации
обложки; (10) Rich Message с H1; (11) обычный текстовый fallback.

Жёсткие инварианты harness: **0 публикаций тестовых результатов** в основной чат
(шпионы `telegram_send.send_text`/`send_rich_message` + guard, который бросает при
обходе), ровно **2** LLM-вызова на успешном ON-пути (L1+L2), fail-closed §106 без
публикации, R17 (сырой текст/секреты не в логах).

Автор: @Builder (S10, Step 4). Дизайн — ADR-1026-12 D2/D3; reuse S9/Harness-
паттернов S6.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import APP_VERSION, Settings, settings
from services import execution_graph_source as egs
from services import param_catalog as pc
from services import summary_generator as sg
from services.llm_client import LLMError
from services.summary_generator import SummaryDraft, SummaryGenerator
from services.summary_run_log import (
    CODE_SUMMARY_GENERATION_FAILED,
    STATUS_DEGRADED,
)
from services.summary_xml import XmlGroundingBuilder

from tests.test_summary_generator import FakeMemory, _row

ROOT = Path(__file__).resolve().parents[1]

CHAT = -1001
CHAT_B = -1002
CHAT_C = -1003
_HYBRID_FLAG = "flags.summary_hybrid_l2_enabled"
_FILTER_FLAG = "flags.summary_filter_enabled"
_S2_FLAG = "flags.summary_filter_reply_context_enabled"
_SECRET = "СЕКРЕТ_R17_НЕ_ДОЛЖЕН_БЫТЬ_В_ЛОГАХ"

# ── §114: детерминированные L1/L2-ответы (реальные S3/S4/S5-модули) ─────────

L1_JSON = json.dumps({
    "schema_version": 1,
    "threads": [{
        "thread_id": "t1", "topic": "Тема", "message_ids": [101, 102],
        "facts": [{"text": "Важный факт", "evidence_message_ids": [101]}],
    }],
    "unassigned_message_ids": [],
}, ensure_ascii=False)

L1_JSON_ONE = json.dumps({
    "schema_version": 1,
    "threads": [{
        "thread_id": "t1", "topic": "Тема", "message_ids": [101],
        "facts": [{"text": "Важный факт", "evidence_message_ids": [101]}],
    }],
    "unassigned_message_ids": [],
}, ensure_ascii=False)

L1_JSON_RICH = json.dumps({
    "schema_version": 1,
    "cover_prompt": "rain",
    "threads": [{
        "thread_id": "t1", "topic": "Тема", "message_ids": [101, 102],
        "facts": [{"text": "Важный факт", "evidence_message_ids": [101]}],
    }],
    "unassigned_message_ids": [],
}, ensure_ascii=False)

L2_JSON = json.dumps({
    "schema_version": 1,
    "title": "Тестовая статья",
    "paragraphs": [{"text": "Первый абзац статьи.", "emphasis": "Первый"}],
}, ensure_ascii=False)

L2_JSON_SECRET = json.dumps({
    "schema_version": 1,
    "title": _SECRET,
    "paragraphs": [{"text": "Абзац.", "emphasis": None}],
}, ensure_ascii=False)


# ── helpers ────────────────────────────────────────────────────────────────

def _rows(*specs):
    """`_row`-строки с разумными дефолтами (tg 101/102)."""
    if not specs:
        return [_row(id=1, tg_message_id=101, text="Первое", timestamp=1000),
                _row(id=2, tg_message_id=102, text="Второе", timestamp=1001,
                     user_id=2, author_name="B")]
    out = []
    for i, spec in enumerate(specs, start=1):
        out.append(_row(id=i, tg_message_id=100 + i, timestamp=1000 + i,
                        **spec))
    return out


def _make_gen(rows, side_effect):
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=side_effect)
    gen = SummaryGenerator(FakeMemory(rows=rows), XmlGroundingBuilder(), llm,
                           AsyncMock())
    return gen, llm


def _limits(monkeypatch, *, hybrid=None, filter_on=False, extra=None):
    """Стаб per-chat резолва.

    ``hybrid=None`` → переданный default (code-default True — активация без
    ручного действия); ``filter_on`` — мастер-тумблер S1 (по умолчанию OFF,
    чтобы harness был детерминирован; S1 имеет собственные тесты).
    """
    extra = dict(extra or {})

    async def _limit(chat_id, key, default=None):
        if key == _HYBRID_FLAG:
            return hybrid if hybrid is not None else default
        if key in (_FILTER_FLAG, _S2_FLAG):
            return extra.get(key, filter_on)
        return extra.get(key, default)

    monkeypatch.setattr(sg, "_chat_limit", _limit)


class Spy:
    def __init__(self):
        self.plain = []
        self.rich = []
        self.rich_kwargs = []
        self.images = []


@pytest.fixture
def spy(monkeypatch):
    """Шпионы выхода: 0 реальных отправок Telegram/обложек (жёсткий инвариант)."""
    s = Spy()

    async def _plain(bot, chat_id, text, **kw):
        s.plain.append(text)
        return SimpleNamespace(message_id=1000 + len(s.plain))

    async def _rich(bot, chat_id, text, **kw):
        s.rich.append(text)
        s.rich_kwargs.append(kw)
        return SimpleNamespace(message_id=2000 + len(s.rich))

    async def _img(prompt, *, chat_id=None, correlation_id=None):
        s.images.append(prompt)
        return ("", "error")

    monkeypatch.setattr(sg, "send_text", _plain)
    monkeypatch.setattr(sg, "send_rich_message", _rich)
    monkeypatch.setattr(sg, "generate_image_verbose", _img)

    def _forbid(*a, **k):
        raise AssertionError("REAL telegram/image call forbidden (§114 harness)")

    monkeypatch.setattr("services.telegram_send.send_text", _forbid)
    monkeypatch.setattr("services.telegram_send.send_rich_message", _forbid)
    monkeypatch.setattr(
        "services.image_generation.generate_image_verbose", _forbid)
    return s


@pytest.fixture(autouse=True)
def _base_env(monkeypatch):
    _limits(monkeypatch)
    monkeypatch.setattr(sg, "fire_and_forget", lambda coro, tag: coro.close())
    egs.reset()
    yield
    egs.reset()


async def _run(gen, chat=CHAT):
    await gen._run(chat, False)


# ═══════════════════════════════════════════════════════════════════════════
# Блок 1. §114 — 11 минимальных сценариев (0 публикаций в основной чат)
# ═══════════════════════════════════════════════════════════════════════════

class TestSec114Scenarios:
    @pytest.mark.asyncio
    async def test_scenario_01_parallel_conversations(self, spy):
        """(1) Несколько параллельных разговоров: 3 чата, каждый — 2 вызова."""
        gens = []
        for _ in range(3):
            gen, llm = _make_gen(_rows(), [L1_JSON, L2_JSON])
            gens.append((gen, llm))
        await asyncio.gather(*(_run(g, CHAT - i) for i, (g, _) in enumerate(gens)))
        for _gen, llm in gens:
            assert llm.generate.await_count == 2
        assert len(spy.plain) == 3            # по одной публикации на чат
        assert spy.rich == []

    @pytest.mark.asyncio
    async def test_scenario_02_short_important_answers(self, spy):
        """(2) Короткие важные ответы («да»/«нет») не теряются."""
        rows = _rows({"text": "да"}, {"text": "нет"})
        gen, llm = _make_gen(rows, [L1_JSON, L2_JSON])
        await _run(gen)
        assert llm.generate.await_count == 2
        assert spy.plain and "Тестовая статья" in spy.plain[0]

    @pytest.mark.asyncio
    async def test_scenario_03_long_messages(self, spy):
        """(3) Длинные сообщения (cap входа) не ломают пайплайн."""
        rows = _rows({"text": "длинное сообщение " * 1500})
        gen, llm = _make_gen(rows, [L1_JSON_ONE, L2_JSON])
        await _run(gen)
        assert llm.generate.await_count == 2
        assert spy.plain

    @pytest.mark.asyncio
    async def test_scenario_04_reply_to(self, spy):
        """(4) `reply_to` — цепочка передаётся, саммари строится."""
        rows = _rows({"text": "родитель"}, {"text": "ответ", "reply_to_id": 101})
        gen, llm = _make_gen(rows, [L1_JSON, L2_JSON])
        await _run(gen)
        assert llm.generate.await_count == 2
        assert spy.plain

    @pytest.mark.asyncio
    async def test_scenario_05_mentions(self, spy):
        """(5) Упоминания (@user) проходят штатно."""
        rows = _rows({"text": "@vasya важный вопрос"}, {"text": "ответ"})
        gen, llm = _make_gen(rows, [L1_JSON, L2_JSON])
        await _run(gen)
        assert llm.generate.await_count == 2
        assert spy.plain

    @pytest.mark.asyncio
    async def test_scenario_06_almost_empty_log(self, spy):
        """(6) Почти пустой лог (1 короткое сообщение) — без падения."""
        rows = _rows({"text": "ок"})
        gen, llm = _make_gen(rows, [L1_JSON_ONE, L2_JSON])
        await _run(gen)
        assert llm.generate.await_count == 2
        assert spy.plain

    @pytest.mark.asyncio
    async def test_scenario_07_invalid_json_l1_fail_closed(self, spy, caplog):
        """(7) Невалидный JSON L1 → fail-closed, L2 не вызывается, 0 публикаций."""
        gen, llm = _make_gen(_rows(), ["это не JSON"])
        with caplog.at_level(logging.INFO):
            await _run(gen)
        assert llm.generate.await_count == 1          # L2 не вызывался
        assert spy.plain == [] and spy.rich == []      # публикации нет
        assert "PUBLISH_" not in caplog.text
        complete = [r.getMessage() for r in caplog.records
                    if r.getMessage().startswith("SUMMARY_COMPLETE |")]
        assert complete and f"code={CODE_SUMMARY_GENERATION_FAILED}" in complete[0]

    @pytest.mark.asyncio
    async def test_scenario_08_llm_error_no_publication(self, spy, caplog):
        """(8) Ошибка LLM → публикации нет (fail-closed §106)."""
        gen, llm = _make_gen(_rows(), LLMError("boom"))
        with caplog.at_level(logging.INFO):
            await _run(gen)
        assert spy.plain == [] and spy.rich == []
        text = caplog.text
        assert "SUMMARY_FAILED" in text or "status=degraded" in text

    @pytest.mark.asyncio
    async def test_scenario_09_cover_error_plain_fallback(self, spy, monkeypatch):
        """(9) Ошибка генерации обложки → публикуется текст (plain §105)."""
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        gen, llm = _make_gen(_rows(), [L1_JSON_RICH, L2_JSON])
        gen._resolve_cover_style_text = AsyncMock(return_value="style")

        async def _boom(*a, **k):
            raise RuntimeError("cover exploded")

        monkeypatch.setattr(sg, "generate_image_verbose", _boom)
        await _run(gen)

        assert llm.generate.await_count == 2
        assert spy.rich == []                      # rich не отправлялся
        assert spy.plain                           # текст публикуется
        assert "Тестовая статья" in "".join(spy.plain)

    @pytest.mark.asyncio
    async def test_scenario_10_rich_message_h1(self, spy, monkeypatch, tmp_path):
        """(10) Rich Message: `<img>` → настоящий `<h1>` → `<p>` (обложка ok)."""
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
        monkeypatch.setattr(sg, "build_cover_media",
                            MagicMock(return_value="MEDIA"))
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        gen, llm = _make_gen(_rows(), [L1_JSON_RICH, L2_JSON])
        gen._resolve_cover_style_text = AsyncMock(return_value="style")

        await _run(gen)

        assert llm.generate.await_count == 2
        assert spy.plain == []
        assert len(spy.rich) == 1
        html = spy.rich[0]
        assert html.startswith('<img src="tg://photo?id=summary_cover">')
        assert html.index("<img") < html.index("<h1>") < html.index("<p>")
        assert "<h1>Тестовая статья</h1>" in html
        assert spy.rich_kwargs[0].get("content_format") == "html"

    @pytest.mark.asyncio
    async def test_scenario_11_plain_text_fallback(self, spy, monkeypatch):
        """(11) Rich недоступен → обычный текст: `<b>title</b>` + абзацы."""
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
        monkeypatch.setattr(sg, "_rich_media_supported", lambda: False)
        gen, llm = _make_gen(_rows(), [L1_JSON_RICH, L2_JSON])
        await _run(gen)
        assert llm.generate.await_count == 2
        assert spy.rich == []
        joined = "".join(spy.plain)
        assert "<b>Тестовая статья</b>" in joined
        assert "<h1>" not in joined                # H1 — только rich-канал


# ═══════════════════════════════════════════════════════════════════════════
# Блок 2. Активация §107 (D2): default ON без ручного действия; OFF kill-switch
# ═══════════════════════════════════════════════════════════════════════════

class TestActivation:
    def test_code_default_is_on(self):
        # SC-01/SC-03: активация = code-default; ручное ON-действие не нужно.
        assert settings.SUMMARY_HYBRID_L2_ENABLED is True

    def test_filter_default_on(self):
        # SC-04: алгоритмический фильтр ON по умолчанию (не менялся).
        assert settings.SUMMARY_FILTER_ENABLED is True

    @pytest.mark.asyncio
    async def test_run_reaches_hybrid_without_manual_action(self, spy,
                                                           monkeypatch):
        """SC-01: при default-резолве `_run` уходит в `_run_hybrid_l2` сам."""
        gen, llm = _make_gen(_rows(), [L1_JSON, L2_JSON])
        seen = {"hybrid": 0, "legacy": 0}
        real_hybrid = gen._run_hybrid_l2

        async def _wrap(*a, **k):
            seen["hybrid"] += 1
            return await real_hybrid(*a, **k)

        monkeypatch.setattr(gen, "_run_hybrid_l2", _wrap)
        monkeypatch.setattr(gen, "_generate_two_call", AsyncMock(
            side_effect=lambda *a, **k: seen.__setitem__(
                "legacy", seen["legacy"] + 1)))
        await _run(gen)
        assert seen["hybrid"] == 1 and seen["legacy"] == 0
        assert llm.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_explicit_false_is_kill_switch(self, spy, monkeypatch):
        """SC-03: явный `false` → аварийный OFF → legacy `_generate_two_call`."""
        _limits(monkeypatch, hybrid=False)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
        gen, _llm = _make_gen(_rows(), [])
        legacy = AsyncMock(return_value=SummaryDraft(
            text="legacy", cover_prompt="", response_mode="serious"))
        monkeypatch.setattr(gen, "_generate_two_call", legacy)
        hybrid = AsyncMock()
        monkeypatch.setattr(gen, "_run_hybrid_l2", hybrid)

        await _run(gen)

        legacy.assert_awaited_once()
        hybrid.assert_not_awaited()
        assert spy.plain                          # legacy-доставка состоялась

    @pytest.mark.asyncio
    async def test_per_chat_override_respected(self, monkeypatch):
        """SC-03: per-chat `flags.summary_hybrid_l2_enabled` побеждает default."""
        gen, _ = _make_gen(_rows(), [])
        _limits(monkeypatch, hybrid=True)
        assert await gen._hybrid_l2_enabled(CHAT) is True
        _limits(monkeypatch, hybrid=False)
        assert await gen._hybrid_l2_enabled(CHAT) is False

    def test_no_catalog_key_and_classvar(self):
        """Δ каталога=0: флаг — env-only ClassVar, не каталожный/датакласс-ключ."""
        import dataclasses
        names = {f.name for f in dataclasses.fields(settings.__class__)}
        assert "SUMMARY_HYBRID_L2_ENABLED" not in names
        assert "SUMMARY_HYBRID_L2_ENABLED" not in pc.REGISTRY


# ═══════════════════════════════════════════════════════════════════════════
# Блок 3. Фильтр в живом пути (S1 врезан; default ON) + роутинг L1/L2
# ═══════════════════════════════════════════════════════════════════════════

class TestFilterAndRouting:
    @pytest.mark.asyncio
    async def test_filter_default_on_is_applied(self, monkeypatch, spy):
        """SC-04: при default-резолве фильтр (S1) вызывается в `_run`."""
        _limits(monkeypatch, filter_on=True)
        called = {"n": 0}
        from services.summary_filter import FilterResult
        from services.summary_context_restore import RestoreResult

        def _filter_window(rows, params, **kw):
            called["n"] += 1
            return FilterResult(kept=list(rows), dropped=[], fragments=None,
                                source_count=len(rows), saved_count=len(rows),
                                restored_count=0, drop_percent=0.0, counts={},
                                scores={}, budget={}, status="ok",
                                duration_ms=0.1)

        def _restore(kept, dropped, window, params, **kw):
            return RestoreResult(kept=list(kept), restored=[], restored_count=0,
                                 parent_count=0, neighbor_count=0,
                                 restored_tg_ids=(), skipped_ids=(),
                                 budget={"fits": True}, status="ok",
                                 duration_ms=0.1)

        monkeypatch.setattr(sg, "filter_window", _filter_window)
        monkeypatch.setattr(sg, "restore_context", _restore)
        gen, llm = _make_gen(_rows(), [L1_JSON, L2_JSON])
        await _run(gen)
        assert called["n"] == 1                    # S1 отработал
        assert llm.generate.await_count == 2
        assert spy.plain

    def test_independent_l1_l2_slots(self):
        """SC-05: слоты L1/L2 — независимые env-only ClassVar; пусто → глобал."""
        import dataclasses
        names = {f.name for f in dataclasses.fields(settings.__class__)}
        for key in ("SUMMARY_L1_BASE_URL", "SUMMARY_L1_MODEL_NAME",
                    "SUMMARY_L1_API_KEY", "SUMMARY_L2_BASE_URL",
                    "SUMMARY_L2_MODEL_NAME", "SUMMARY_L2_API_KEY"):
            assert key not in names               # env-only, вне каталога
            assert getattr(settings, key) == ""   # «не выбрано» → глобальная модель
        # Раздельные слоты не связаны общим резолвером (независимость by design).
        from services.summary_l1_clusterizer import provider_host as l1_host
        from services.summary_l2_writer import provider_host as l2_host
        assert l1_host("https://a.example") != l2_host("https://b.example")


# ═══════════════════════════════════════════════════════════════════════════
# Блок 4. R17 + границы diff + Δ DDL=0/Δ каталога=0 + регресс-санкции
# ═══════════════════════════════════════════════════════════════════════════

class TestBounds:
    @pytest.mark.asyncio
    async def test_r17_no_raw_text_in_logs(self, spy, caplog):
        """R17: публикуемый секрет не попадает в логи (только числа/коды)."""
        gen, llm = _make_gen(_rows(), [L1_JSON, L2_JSON_SECRET])
        with caplog.at_level(logging.DEBUG):
            await _run(gen)
        assert _SECRET not in caplog.text
        # Текст реально доставлен (не потерян — R17 про логи, не про доставку).
        assert spy.plain and _SECRET in "".join(spy.plain)

    def test_catalog_delta_zero(self):
        assert len(pc.REGISTRY) == 469
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21

    def test_app_version_bumped(self):
        assert APP_VERSION == "2.58.29"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "v2.58.29" in readme

    def test_no_ddl_in_touched_sources(self):
        """Δ DDL=0: в изменённых модулях нет DDL-операторов."""
        for rel in ("config/settings.py", "services/summary_generator.py",
                    "services/summary_l2_writer.py"):
            text = (ROOT / rel).read_text(encoding="utf-8").upper()
            assert "CREATE TABLE" not in text
            assert "ALTER TABLE" not in text
            assert "DROP TABLE" not in text

    def test_forbidden_paths_unchanged(self):
        """D1: §104/telegram_send/каноны/логика-модули/routes/db/каталог — вне diff."""
        forbidden = [
            "services/image_generation.py", "services/telegram_send.py",
            "services/summary_prompts.py", "services/prompt_migrations.py",
            "services/summary_filter.py", "services/summary_context_restore.py",
            "services/summary_l1_clusterizer.py", "services/summary_fact_package.py",
            "services/summary_article_formatter.py", "services/summary_test_run.py",
            "web/api/routes.py", "web", "db", "services/param_catalog.py", "bot.py",
        ]
        proc = subprocess.run(
            ["git", "diff", "--name-only", "pre-round1026-s10", "--", *forbidden],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            pytest.skip("baseline tag pre-round1026-s10 недоступен")
        assert proc.stdout.strip() == "", proc.stdout

    def test_run_logic_ast_identical_to_baseline(self):
        """D1: логика `_run`/`_run_hybrid_l2`/резолва не менялась (только docstrings)."""
        proc = subprocess.run(
            ["git", "show", "pre-round1026-s10:services/summary_generator.py"],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            pytest.skip("baseline tag pre-round1026-s10 недоступен")
        current = (ROOT / "services/summary_generator.py").read_text(
            encoding="utf-8")

        def _func_dump(src, name):
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if (isinstance(node, ast.AsyncFunctionDef)
                        and node.name == name):
                    body = node.body
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        node.body = body[1:]
                    return ast.dump(node)
            raise AssertionError(f"{name} не найден")

        for name in ("_run", "_run_hybrid_l2", "_hybrid_l2_enabled"):
            assert _func_dump(current, name) == _func_dump(proc.stdout, name), \
                f"логика {name} изменилась (D1 запрещает)"
