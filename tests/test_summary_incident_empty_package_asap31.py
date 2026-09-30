"""ASAP-3.1 incident fix 29.09.2026 — EMPTY-PACKAGE GUARD + fallback-бюджет.

Прод-инцидент (2.58.37, regular cron 19:00, msg 1120810): окно 1089 сообщений
→ L1 unknown_field → correction retry timeout (оба провайдера) → ветка
«L1 непригоден» вызывала ``build_fallback_package`` БЕЗ бюджета → статический
потолок 18661 (hot ``summary_hybrid_context_tokens=30000``) → ``_enforce_budget``
вытолкнул единственную тему ЦЕЛИКОМ вместе с хронологией → пустой пакет прошёл
delivery-гейт → L2 опубликовал мета-текст «пакет пуст».

Фикс — 3 части:
  1. ``summary_generator`` L1-unusable call-site: ``budget=l2_budget``
     (как в defensive-ветке).
  2. ``summary_fact_package._enforce_budget``: EMPTY-PACKAGE GUARD —
     последняя/единственная тема НИКОГДА не вытесняется; её содержимое
     обрезается (fragments → chronology); near-empty при непустом входе →
     ``SUMMARY_COVERAGE_DEGRADED`` reason=``near_empty_package``.
  3. ``summary_generator._run``: пустой по материалу fallback-пакет НЕ идёт
     в L2 как обычный саммари → LEVEL-3 Legacy (published-guard).

Тесты — на ФАКТ передачи бюджета и на то, что класс «пустой пакет → мета-текст»
закрыт (L2 получает реальный материал; guard не вытесняет последнюю тему).
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.model_capacity as mc
import services.summary_budget_auto as sba
import services.summary_fact_package as sfp

pytestmark = pytest.mark.asap31

CHAT_ID = -100777
_INCIDENT_WINDOW = 1089


# ── Хелперы ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean():
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()


def _slot(monkeypatch, base_url, model):
    monkeypatch.setattr(type(sba.settings), "SUMMARY_L2_BASE_URL", base_url,
                        raising=False)
    monkeypatch.setattr(type(sba.settings), "SUMMARY_L2_MODEL_NAME", model,
                        raising=False)


def _resolver(*value):
    async def _fn():
        return value
    return _fn


def _items(n):
    """§92-payload-элементы (окно инцидента): n сообщений, короткий текст."""
    items = []
    for i in range(n):
        mid = 1000 + i
        items.append({
            "message_id": mid, "chat_id": -100,
            "timestamp": 1_700_000_000 + i, "author_id": 10,
            "display_name": "Вася",
            "text": f"сообщение {i} про ремонт и соседей",
            "reply_to_id": None, "message_type": "text",
        })
    return items


def _rows(n):
    """Строки окна для генератора (tg_message_id → message_id §92)."""
    rows = []
    for i in range(n):
        rows.append({
            "id": i + 1, "tg_message_id": 1000 + i, "user_id": 10,
            "author_name": "Вася", "timestamp": 1_700_000_000 + i,
            "text": f"сообщение {i} про ремонт и соседей",
            "reply_to_id": None, "media_type": "text",
        })
    return rows


def _thread_for_budget(thread_id, mids):
    return {
        "thread_id": thread_id,
        "name": f"тема {thread_id}",
        "description": "описание темы",
        "chronology": [{"message_id": m, "timestamp": m} for m in mids],
        "facts": [],
        "evidence_ids": [],
        "fragments": [{"message_id": m, "timestamp": m, "text": "ф" * 120}
                      for m in mids],
    }


class _L2Usable:
    """Минимальный usable L2-результат (документ без мета-текста о пустоте)."""

    usable = True
    invalid_reason = None
    document = {
        "schema_version": 1,
        "title": "Итог обсуждения",
        "paragraphs": [{"text": "Реальный материал обсуждения.",
                        "emphasis": None}],
    }


# ── Часть 3 (generator): инцидент 1089 сообщений — L1 unusable, L2 получает
#    реальный материал, публикация состоялась, Legacy не задействован ────────

@pytest.mark.asyncio
async def test_incident_1089_fallback_package_not_empty(monkeypatch, caplog):
    """Главная регрессия инцидента: L1 непригоден (timeout) при окне 1089 →
    fallback-пакет НЕ пуст (fragments>0 ∧ chronology>0), L2 получает реальный
    материал; бюджет — резолверный (не статика)."""
    from services.summary_generator import SummaryGenerator
    from services.summary_l1_contract import error_result
    import services.summary_l1_clusterizer as sl1
    import services.summary_l2_writer as l2w

    captured: dict = {}

    async def fake_run_l1(**_kwargs):
        # Симуляция инцидента: L1 непригоден (unknown_field → retry timeout).
        return error_result("l1_timeout")

    async def fake_run_l2(llm, package, **_kwargs):
        captured["package"] = package
        return _L2Usable()

    monkeypatch.setattr(sl1, "run_l1", fake_run_l1)
    monkeypatch.setattr(l2w, "run_l2", fake_run_l2)
    # Детерминированный Auto-бюджет слота summary.l2 (как на проде: >> 18661).
    monkeypatch.setattr(sba, "resolve_l2_package_budget",
                        _resolver("tokens", 200000, "auto"))

    llm = MagicMock()
    llm.generate = AsyncMock()
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                           bot=None)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    gen._deliver_l2_rich = AsyncMock(return_value=True)
    gen._run_legacy_pipeline = AsyncMock(return_value=False)

    with caplog.at_level("INFO"):
        await gen._run_hybrid_l2(-100, _rows(_INCIDENT_WINDOW), None,
                                 "run-incident")

    package = captured.get("package")
    assert package is not None, "L2 не получил пакет — публикации не было"
    threads = package["threads"]
    total_chronology = sum(len(t["chronology"]) for t in threads)
    total_fragments = sum(len(t["fragments"]) for t in threads)
    assert total_chronology > 0, "fallback-пакет пуст по хронологии"
    assert total_fragments > 0, "fallback-пакет пуст по fragments"
    # Часть 1: резолверный бюджет реально дошёл до fallback-пакета.
    assert package["budget"]["limit"] == 200000
    # Публикация состоялась; в Legacy не уходили; пустого события нет.
    assert (gen._deliver_l2_plain.await_count
            + gen._deliver_l2_rich.await_count) == 1
    gen._run_legacy_pipeline.assert_not_awaited()
    assert "PACKAGE_NEAR_EMPTY" not in caplog.text
    assert "L1_FALLBACK_PACKAGE_EMPTY" not in caplog.text


# ── Часть 2 (guard): последняя тема не вытесняется ─────────────────────────

def test_enforce_budget_never_pops_last_thread():
    """Unit-доказательство guard'а: при минимальном бюджете вытесняется только
    старая тема; последняя остаётся в структуре (содержимое обрезано)."""
    threads = [_thread_for_budget("a", [101, 102]),
               _thread_for_budget("b", [201, 202])]
    skipped_ids, skipped_threads, cleared, skipped_chronology, cut = \
        sfp._enforce_budget(threads, [], "tokens", 1)

    assert cut is True
    assert len(threads) == 1, "guard: последняя тема вытеснена целиком"
    assert threads[0]["thread_id"] == "b"
    assert skipped_threads == ["a"], "вытеснена ровно самая старая тема"
    assert len(skipped_ids) == 4, "сначала вытесняются fragments"
    assert sorted(skipped_chronology) == [201, 202], "затем chronology"
    assert threads[0]["chronology"] == [], "chronology последней темы обрезана"
    assert threads[0]["fragments"] == [], "fragments последней темы обрезаны"


def test_fallback_package_single_topic_never_empty(caplog):
    """Fallback-пакет с минимальным бюджетом: единственная тема НЕ исчезает —
    пустого пакета (threads=[]) не бывает; эмитится near_empty_package."""
    items = _items(5)
    with caplog.at_level("INFO"):
        result = sfp.build_fallback_package(
            items, budget=("tokens", 1), correlation_id="r-incident",
            chat_id=CHAT_ID)
    assert result is not None
    assert len(result.package["threads"]) == 1, (
        "единственная тема вытеснена — пустой пакет прошёл бы гейт")
    assert result.metrics["fragments_count"] == 0
    assert result.metrics["messages_count"] == 0
    # Громкое событие (не тихий успех).
    assert "PACKAGE_NEAR_EMPTY" in caplog.text
    assert "near_empty_package" in caplog.text
    assert result.metrics["skipped_chronology_count"] > 0


# ── Часть 3 (generator gate): пустой по материалу fallback → Legacy, не L2 ──

@pytest.mark.asyncio
async def test_empty_fallback_package_goes_legacy_not_l2(monkeypatch, caplog):
    """Если fallback-пакет всё же пуст по материалу — он НЕ публикуется через
    L2 мета-текстом, а уходит в LEVEL-3 Legacy."""
    from services.summary_generator import SummaryGenerator
    from services.summary_l1_contract import error_result
    import services.summary_l1_clusterizer as sl1
    import services.summary_l2_writer as l2w

    l2_called = {"n": 0}

    async def fake_run_l1(**_kwargs):
        return error_result("l1_timeout")

    async def fake_run_l2(llm, package, **_kwargs):
        l2_called["n"] += 1
        return _L2Usable()

    monkeypatch.setattr(sl1, "run_l1", fake_run_l1)
    monkeypatch.setattr(l2w, "run_l2", fake_run_l2)
    # Бюджет настолько мал, что пакет пуст по материалу.
    monkeypatch.setattr(sba, "resolve_l2_package_budget",
                        _resolver("tokens", 1, "auto"))

    llm = MagicMock()
    llm.generate = AsyncMock()
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=llm,
                           bot=None)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    gen._legacy_fallback_enabled = AsyncMock(return_value=True)
    gen._run_legacy_pipeline = AsyncMock(return_value=True)

    with caplog.at_level("INFO"):
        await gen._run_hybrid_l2(-100, _rows(50), None, "run-empty")

    assert l2_called["n"] == 0, "пустой пакет ушёл в L2 (мета-текст)"
    gen._run_legacy_pipeline.assert_awaited_once()
    assert "L1_FALLBACK_PACKAGE_EMPTY" in caplog.text


# ── Часть 1+2 (package-level): 1089 сообщений — статика и Auto ─────────────

def test_fallback_1089_static_budget_keeps_chronology():
    """Даже на статическом потолке инцидента (18661) guard сохраняет тему и
    часть chronology — пустого пакета нет."""
    result = sfp.build_fallback_package(
        _items(_INCIDENT_WINDOW), budget=("tokens", 18661),
        correlation_id="r-static", chat_id=CHAT_ID)
    assert result is not None
    assert len(result.package["threads"]) == 1
    assert result.metrics["limit"] == 18661
    assert result.metrics["messages_count"] > 0


@pytest.mark.asyncio
async def test_fallback_1089_auto_budget_keeps_fragments(monkeypatch):
    """Auto-бюджет слота summary.l2 на окне 1089 вмещает материал целиком:
    fragments>0 ∧ chronology>0, усечения нет."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    kind, limit, mode = await sba.resolve_l2_package_budget()
    assert mode == sba.BUDGET_MODE_AUTO
    assert limit > 100000

    result = sfp.build_fallback_package(
        _items(_INCIDENT_WINDOW), budget=(kind, limit, mode),
        correlation_id="r-auto", chat_id=CHAT_ID)
    assert result is not None
    assert result.metrics["limit"] == limit, "статика подменена на Auto"
    assert result.metrics["fragments_count"] > 0
    assert result.metrics["messages_count"] == _INCIDENT_WINDOW, (
        "chronology окна сохранена целиком (бюджетного усечения нет)")
    assert result.metrics["skipped_chronology_count"] == 0


def test_serialize_still_deterministic_after_guard():
    """Guard не ломает каноническую сериализацию пакета."""
    result = sfp.build_fallback_package(
        _items(20), budget=("tokens", 10**6), correlation_id="r-det")
    first = sfp.serialize_package(result.package)
    second = sfp.serialize_package(result.package)
    assert first == second
    assert json.loads(first)["schema_version"] == sfp.SCHEMA_VERSION
