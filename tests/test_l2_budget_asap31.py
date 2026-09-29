"""ASAP-3.1 rework (H-ASAP31-1) — L2 Stage Auto Budget применяется end-to-end.

Регрессия тихой интеграции 3-tuple → 2-tuple: авто-бюджет слота summary.l2
вычислялся, но ``_resolve_budget`` понимал только ``(kind, limit)``/int и
молча отбрасывал тройку → L2-пакет резался старым статическим потолком
(~19–21K). Фикс: единая форма (kind, limit[, budget_mode]) — расширенная
тройка принимается; ``build_fact_package`` И ``build_fallback_package``
получают один и тот же бюджет от генератора.

Ассерты — на ФАКТИЧЕСКОЕ использование бюджета в L2-входе
(``metrics["limit"]``) и на поведение усечения (payload между статикой и
авто — НЕ режется на ON-пути; manual cap режет по своему значению).
"""
import json
from dataclasses import replace

import pytest

import services.model_capacity as mc
import services.summary_budget_auto as sba
import services.summary_fact_package as sfp
from services.summary_l1_contract import L1Result, STATUS_OK

pytestmark = pytest.mark.asap31

CHAT_ID = -100777


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


def _l1_result(threads):
    payload = {"schema_version": 2, "threads": threads,
               "unassigned_message_ids": []}
    return L1Result(
        status=STATUS_OK, payload=payload, invalid_reason=None,
        threads_count=len(threads),
        facts_count=sum(len(t.get("facts") or []) for t in threads),
        auto_unassigned_count=0, skipped_ids=(), skipped_tg_ids=(),
        response_mode="serious", cover_prompt="", duration_ms=1.0)


def _payload_items(message_ids, text):
    items = []
    for mid in message_ids:
        items.append({"id": mid, "tg_message_id": mid, "message_id": mid,
                      "user_id": 10, "author_name": "Вася", "text": text,
                      "timestamp": 1_700_000_000 + mid,
                      "media_type": "text", "reply_to_id": None,
                      "is_forward": 0, "forward_source": None})
    return items


def _threads_sized(target_tokens: int):
    """Две темы с фактами, суммарный serialized-объём ≈ target_tokens
    (та же метрика, что `_estimate` в fact-package)."""
    base = ("обсуждение ремонта в квартире и соседи сверху шумят " * 4)
    per_thread = target_tokens // 2
    threads = []
    for index in range(2):
        fact_text = base
        while sfp.count_tokens(json.dumps(
                {"t": fact_text}, ensure_ascii=False,
                separators=(",", ":"))) < per_thread:
            fact_text += base
        threads.append({
            "thread_id": f"T{index + 1}",
            "topic": f"тема {index}",
            "message_ids": [101 + index, 201 + index],
            "facts": [{"text": fact_text,
                       "evidence_message_ids": [101 + index, 201 + index]}],
        })
    return threads


# ── Единая форма бюджета (strict-совместимость) ────────────────────────────

def test_resolve_budget_accepts_extended_triple():
    assert sfp._resolve_budget(("tokens", 12345, "auto")) == ("tokens", 12345)
    assert sfp._resolve_budget(["tokens", 12345, "manual_cap"]) == \
        ("tokens", 12345)
    assert sfp._resolve_budget(("chars", 5000)) == ("chars", 5000)
    assert sfp._resolve_budget(7000) == ("tokens", 7000)


# ── Auto: resolver-бюджет ДОХОДИТ до L2-пакета ─────────────────────────────

@pytest.mark.asyncio
async def test_auto_l2_budget_applied_end_to_end(monkeypatch):
    """§131/§37/DoD-76: limit пакета == effective_input_budget резолвера
    слота summary.l2; payload между статикой и авто НЕ режется (старый
    статический потолок на ON-пути не срабатывает)."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    kind, limit, mode = await sba.resolve_l2_package_budget()
    assert mode == sba.BUDGET_MODE_AUTO
    assert kind == "tokens"
    # Auto = от окна 131072: int(131072/1.15) − system − 6000 (>> статика).
    assert limit > 100000, f"auto L2 limit неожиданно мал: {limit}"

    static_kind, static_limit = sfp.resolve_fact_package_budget()
    assert static_limit < limit, "тест осмыслен, только если авто > статики"

    # Payload между статикой и авто: старое поведение (тихий сброс тройки)
    # резало бы по static_limit; новое — не режет вовсе.
    threads = _threads_sized(static_limit + 3000)
    assert sfp._estimate(threads, [], "tokens") > static_limit
    assert sfp._estimate(threads, [], "tokens") < limit

    result = sfp.build_fact_package(
        _l1_result(threads),
        _payload_items([101, 102, 201, 202], "исходный текст сообщений"),
        budget=(kind, limit, mode), correlation_id="test-l2-auto")
    assert result.deliverable
    # ФАКТИЧЕСКОЕ использование: в L2-входе применён РЕЗОЛВЕРНЫЙ limit.
    assert result.metrics.get("limit") == limit, (
        f"L2-бюджет не дошёл до пакета: metrics.limit="
        f"{result.metrics.get('limit')} != resolver {limit}")
    assert result.metrics.get("kind") == "tokens"
    # Обе темы сохранились — усечения по статике НЕТ.
    assert result.metrics.get("skipped_threads") == ()
    assert len((result.package or {}).get("threads") or []) == 2
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_auto_budget_matches_resolver_value_exactly(monkeypatch):
    """Прямой контракт: ``(kind, limit)`` из резолвера == то, что использует
    пакет (без повторного расчёта и без подмены статикой)."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    kind, limit, mode = await sba.resolve_l2_package_budget()
    threads = _threads_sized(2000)          # малый payload — без усечения
    result = sfp.build_fact_package(
        _l1_result(threads), _payload_items([101, 102, 201, 202], "т"),
        budget=(kind, limit, mode))
    assert result.metrics.get("limit") == limit
    assert result.metrics.get("kind") == kind


# ── Manual cap: применяется к L2-входу ─────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_cap_l2_budget_applied(monkeypatch):
    """Кастом владельца (>0) → manual cap: L2-пакет режется ПО капу
    (размер L2-входа), а не по статике/авто."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    monkeypatch.setattr(type(sba.settings), "SUMMARY_HYBRID_CONTEXT_TOKENS",
                        8000, raising=False)
    kind, limit, mode = await sba.resolve_l2_package_budget()
    assert mode == sba.BUDGET_MODE_MANUAL_CAP
    assert limit < 4000, f"manual cap L2 limit неожиданно велик: {limit}"

    threads = _threads_sized(limit + 5000)
    result = sfp.build_fact_package(
        _l1_result(threads),
        _payload_items([101, 102, 201, 202], "текст"),
        budget=(kind, limit, mode))
    assert result.metrics.get("limit") == limit
    # Payload > капа → усечение ПО КАПУ (темы вытесняются, пакет остаётся
    # deliverable — §96 fail-closed усечение допустимо при ручном потолке).
    assert (result.metrics.get("skipped_threads")
            or result.metrics.get("skipped_ids")
            or result.status == "truncated"), (
        "manual cap должен реально ограничивать L2-вход")


# ── Fallback-пакет получает тот же бюджет ──────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_package_receives_same_budget(monkeypatch):
    """Генератор передаёт ОДИН И ТОТ ЖЕ бюджет и в build_fallback_package
    (ветка «package_unusable») — fallback не возвращается на статику."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    kind, limit, mode = await sba.resolve_l2_package_budget()
    items = _payload_items([1, 2, 3], "фрагмент хроники " * 3)
    result = sfp.build_fallback_package(
        items, correlation_id="test-l2-fb", chat_id=CHAT_ID,
        reason="package_unusable", budget=(kind, limit, mode))
    assert result is not None and result.deliverable
    assert result.metrics.get("limit") == limit, (
        "fallback-пакет должен использовать resolver-бюджет, а не статику")


# ── OFF-паритет: None → прежняя статическая точка ──────────────────────────

def test_none_budget_keeps_legacy_static_path(monkeypatch):
    monkeypatch.setattr(type(sba.settings), "SUMMARY_HYBRID_CONTEXT_TOKENS",
                        None, raising=False)
    kind, limit = sfp._resolve_budget(None)
    static_kind, static_limit = sfp.resolve_fact_package_budget()
    assert (kind, limit) == (static_kind, static_limit)
