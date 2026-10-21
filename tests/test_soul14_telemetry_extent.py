"""SOUL-14.2 — telemetry key metrics: распределение extent + exact
one_word compliance в СУЩЕСТВУЮЩИЙ контур ``mca_events`` (event
``speech_extent``, компонент ``style_policy``).

Контракт (строка SOUL-14.2 requirements-map, M00195):
  * каждый проход ``apply_style_policy`` с выполненным extent-check
    отдаёт ОДНО R17-safe событие — сырьё распределения extent;
  * ``one_word_exact`` = финальный текст ровно одно лексическое слово
    (pass/repaired); нарушение → честный ``failed`` (WARN), не пропуск;
  * только счётчики/коды (extent/status/words/reason) — НИКАКИХ текстов
    (ни ответа, ни слов ответа) в payload;
  * extent-check не шёл (style OFF / без плана / auto-extent) → события
    нет (честное отсутствие, не ноль) либо ``skipped``/``auto``;
  * исходы только из ``ALL_OUTCOMES`` (урок B1 8cd2ca14: невалидный
    outcome build_event молча роняет событие); ``usage_json`` проходит
    whitelist (доколончатая проверка — ``usage_json`` реально
    персистится в mca_events);
  * OFF ``SPEECH_STYLE_POLICY_ENABLED`` → байт-паритет: ни события,
    ни изменения текста.

Всё на моках/реальном коде локально: сеть, LLM и реальные чаты не
используются; эмиссия перехватывается spy'ем с рантайм-пробой
``build_event`` (проверка словаря контракта §17.1).

TEST-LIFECYCLE: CONTRACT owner=SOUL-14.2
"""
from __future__ import annotations

import json

import pytest

from config.settings import settings
from services import chat_params
from services import hot_config as hot
from services import mca_gates
from services import style_policy as sp
from services.response_extent import ResponsePlan

CHAT = 303


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeChatCache:
    def __init__(self):
        self.overrides = {}

    async def get_chat_params(self, chat_id):
        return {"overrides": {}}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None


@pytest.fixture(autouse=True)
def _clean_state():
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def enable_policy(monkeypatch):
    """Флаг ON + документ с preset-правилом (проходит machine-skip)."""
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    doc = sp.build_document(presets=("no_quotes",), revision=1, owner=1,
                            reason="test")
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: doc}))
    chat_params.set_chat_params_cache(FakeChatCache())
    assert mca_gates.speech_style_policy_enabled() is True


def spy_emitter(monkeypatch):
    """Spy на emit_mca_event c рантайм-пробой build_event (паттерн B1:
    событие, потерянное словарём контракта, падает тестом сразу)."""
    from services import mca_events
    seen: list[dict] = []

    def spy(event_name, *, outcome, level="INFO", **fields):
        seen.append({"event_name": event_name, "outcome": outcome,
                     "level": level, **fields})
        built = mca_events.build_event(event_name, outcome=outcome,
                                       level=level, **fields)
        assert built is not None, (
            f"event dropped by contract: name={event_name!r} "
            f"outcome={outcome!r}")
        return built

    monkeypatch.setattr(mca_events, "emit_mca_event", spy)
    return seen


def extent_events(seen: list[dict]) -> list[dict]:
    return [row for row in seen if row["event_name"] == "speech_extent"]


async def run_pass(text, plan, *, stage="direct_pre_send", context="regular"):
    return await sp.apply_style_policy(
        text, chat_id=CHAT, plan=plan, context=context,
        emit_events=True, stage=stage)


# ═══ 1. Распределение: одно событие на проход с extent-check ═══════════════

@pytest.mark.asyncio
async def test_one_word_pass_emits_success_with_exact_flag(monkeypatch):
    """one_word, ровно одно слово → success, one_word=1, one_word_exact=1."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    outcome = await run_pass("Капитан", ResponsePlan(extent="one_word"))
    rows = extent_events(seen)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["outcome"] == "success"
    assert row["level"] == "INFO"
    assert row["component"] == "style_policy"
    assert row["stage"] == "direct_pre_send"
    assert row["chat_id"] == CHAT
    payload = row["usage_json"]
    assert payload["extent"] == "one_word"
    assert payload["status"] == "pass"
    assert payload["one_word"] == 1
    assert payload["one_word_exact"] == 1      # exact compliance
    assert payload["words"] == 1
    assert payload["context"] == "regular"


@pytest.mark.asyncio
async def test_one_word_violation_emits_failed_not_silent(monkeypatch):
    """one_word нарушен (несколько слов, ремонт невозможен) → честный
    failed/WARN с one_word_exact=0; «styled=true» не объявляется."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    await run_pass("два слова здесь", ResponsePlan(extent="one_word"))
    rows = extent_events(seen)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "failed"
    assert rows[0]["level"] == "WARN"
    payload = rows[0]["usage_json"]
    assert payload["status"] == "failed"
    assert payload["one_word"] == 1
    assert payload["one_word_exact"] == 0
    assert payload["words"] == 3
    assert payload["reason"] == "one_word_multiple_words"


@pytest.mark.asyncio
async def test_one_word_repaired_counts_as_exact_compliance(monkeypatch):
    """«Капитан 😀» → минимальная правка хвоста (repaired) → финальный
    текст ровно одно слово: success + one_word_exact=1 + reason."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    outcome = await run_pass("Капитан 😀", ResponsePlan(extent="one_word"))
    assert outcome.extent.status == "repaired"
    rows = extent_events(seen)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "success"
    payload = rows[0]["usage_json"]
    assert payload["status"] == "repaired"
    assert payload["one_word_exact"] == 1
    assert payload["reason"] == "one_word_extra_tail_removed"


# ═══ 2. Поле распределения по всем extent'ам (не только one_word) ══════════

@pytest.mark.asyncio
async def test_micro_and_compact_extent_in_distribution(monkeypatch):
    """micro/compact попадают в распределение: extent-код, счётчик слов,
    one_word=0 (exact-флаг имеет смысл только для one_word)."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    await run_pass("да, конечно", ResponsePlan(extent="micro"))
    await run_pass("Пара живых предложений. По делу.",
                   ResponsePlan(extent="compact"))
    rows = extent_events(seen)
    assert [r["usage_json"]["extent"] for r in rows] == ["micro", "compact"]
    assert all(r["outcome"] == "success" for r in rows)
    assert all(r["usage_json"]["one_word"] == 0 for r in rows)
    assert all(r["usage_json"]["one_word_exact"] == 0 for r in rows)
    assert rows[0]["usage_json"]["words"] == 2
    assert rows[1]["usage_json"]["status"] == "pass"


@pytest.mark.asyncio
async def test_auto_extent_reported_as_skipped_auto(monkeypatch):
    """План без валидного extent → not_applicable → честный skipped c
    extent=auto (в распределении видно долю сообщений без ограничения)."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    await run_pass("Обычный ответ без явной формы.",
                   ResponsePlan(extent=""))
    rows = extent_events(seen)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "skipped"
    payload = rows[0]["usage_json"]
    assert payload["extent"] == "auto"
    assert payload["status"] == "not_applicable"
    assert "words" not in payload              # счёт не выполнялся
    assert payload["one_word"] == 0


@pytest.mark.asyncio
async def test_initiative_stage_reported_with_context(monkeypatch):
    """Инициативный путь виден в распределении (context/stage)."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    await run_pass("Коротко.", ResponsePlan(extent="micro"),
                   stage="initiative_pre_send", context="initiative")
    rows = extent_events(seen)
    assert len(rows) == 1
    assert rows[0]["stage"] == "initiative_pre_send"
    assert rows[0]["usage_json"]["context"] == "initiative"


# ═══ 3. Честное отсутствие и OFF-паритет ═══════════════════════════════════

@pytest.mark.asyncio
async def test_no_plan_no_extent_event(monkeypatch):
    """Без плана extent-check не шёл → событие НЕ выдумывается."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    await run_pass("Ответ без плана.", None)
    assert extent_events(seen) == []


@pytest.mark.asyncio
async def test_style_policy_off_no_event_byte_parity(monkeypatch):
    """OFF: ни события, ни правки текста (байт-паритет legacy-пути)."""
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "0")
    seen = spy_emitter(monkeypatch)
    text = "Ответ без style-прохода."
    outcome = await run_pass(text, ResponsePlan(extent="one_word"))
    assert outcome.applied is False
    assert outcome.text == text
    assert extent_events(seen) == []


# ═══ 4. Приватность: только счётчики/коды, без текстов ═════════════════════

@pytest.mark.asyncio
async def test_metric_carries_no_text(monkeypatch):
    """R17: в payload нет ни текста ответа, ни его слов — только
    счётчики/коды. Проверяется на всём перехваченном событии."""
    enable_policy(monkeypatch)
    seen = spy_emitter(monkeypatch)
    secret = "абракадабрафимозг"
    await run_pass(secret, ResponsePlan(extent="one_word"))
    await run_pass(f"{secret} и ещё слова", ResponsePlan(extent="one_word"))
    for row in seen:                           # все события, не только extent
        blob = json.dumps(row, ensure_ascii=False, default=str)
        assert secret not in blob


# ═══ 5. Рантайм-проба словаря контракта (B1-паттерн, без spy) ══════════════

def test_build_event_accepts_speech_extent_metric():
    """Реальный build_event: все три исхода метрики валидны, usage_json
    проходит whitelist и реально попадает в событие (персистится в
    mca_events-колонку usage_json)."""
    from services import mca_events
    for outcome, level in (("success", "INFO"), ("failed", "WARN"),
                           ("skipped", "INFO")):
        assert outcome in mca_events.ALL_OUTCOMES
        event = mca_events.build_event(
            "speech_extent", outcome=outcome, level=level,
            component="style_policy", stage="direct_pre_send",
            chat_id=CHAT,
            usage_json={"extent": "one_word", "status": "pass",
                        "one_word": 1, "one_word_exact": 1, "words": 1,
                        "context": "regular"})
        assert event is not None, outcome
        assert event["event_name"] == "speech_extent"
        assert event["outcome"] == outcome
        payload = json.loads(event["usage_json"])
        assert payload["one_word_exact"] == 1
        assert payload["extent"] == "one_word"


def test_metric_gates_default_on():
    """Kill-switches контура в дефолте ON: метрика не глушится молча
    (реальная эмиссия гейтится теми же rubилями, что остальные события)."""
    assert mca_gates.event_contract_enabled() is True
    assert mca_gates.telemetry_store_enabled() is True
    assert getattr(settings, "MCA_EVENT_CONTRACT_ENABLED", True) is True
