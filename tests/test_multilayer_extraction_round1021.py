"""F1 (multilayer-memory-extraction-round1021, T-1943…T-1952) — тесты
двухслойной экстракции памяти.

Покрытие (spec §8):
1. парсеры Слоя А/Б (валид, code-fence, битый JSON → ValueError, отброс
   кандидатов без evidence и с kind=noise);
2. двухслойность (ровно 2 LLM-вызова A+B, в graph_facts только мемы, портрет
   без цитат);
3. кейсы ТЗ (копипаста/«Кирилл»/«инструкция»/шутливый титул);
4. fallback Слоя А → путь 10.20 (память цела); Слой Б упал → мемы Слоя А целы;
5. kill-switch OFF → байт-совместимость 10.20 (промпт/вызовы);
6. бюджет: прогноз A+B (2 вызова), при превышении — skip;
7. детерминизм чистых парсеров/фильтра;
8. Д3: ручные persona_dossier_overrides неприкосновенны.
"""
import asyncio
import json
import time

import pytest

from config.settings import Settings
from services import hot_config as hot
from services import worker_budget
from services.database import DatabaseService
from services.dossier_prompts import (
    DOSSIER_SYSTEM_PROMPT,
    build_layer_a_user,
    build_layer_b_user,
    find_verbatim_quote,
    filter_layer_a_candidates,
    parse_layer_a,
    parse_layer_b,
    validate_layer_b,
)
from services.lore_worker import LoreWorker

CHAT_ID = -1001234567890


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


@pytest.fixture(autouse=True)
def _budget_open(monkeypatch):
    """Дефолт: бюджет воркера открыт (PG down → fail-open True). Отдельный
    тест §6 переопределяет consume."""
    async def _allow(*args, **kwargs):
        return True
    monkeypatch.setattr(worker_budget, "global_degradation_allows", _allow)
    monkeypatch.setattr(worker_budget, "consume", _allow)
    yield


class FakeStore:
    @property
    def pg(self):
        return None


class FakeLLM:
    """LLM-мок: последовательность ответов generate_worker (роль background)
    + опциональные первые N исключений."""

    def __init__(self, sequence=None, text=None, raise_times=0):
        self.sequence = list(sequence or [])
        self.text = text
        self.raise_times = raise_times
        self.worker_calls = 0
        self.worker_roles: list[str] = []
        self.calls: list[list[dict]] = []

    async def generate(self, messages, temperature=None):
        return self.text if self.text is not None else "lore"

    async def generate_worker(self, role, messages, *, temperature=None):
        self.worker_calls += 1
        self.worker_roles.append(role)
        self.calls.append(messages)
        if self.worker_calls <= self.raise_times:
            from services.llm_client import LLMError
            raise LLMError("boom")
        if self.sequence:
            return self.sequence.pop(0)
        return self.text if self.text is not None else "{}"


def _flag(monkeypatch, enabled: bool = True,
          multilayer: bool = True) -> None:
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: enabled
        if key == "flags.irony_filter_enabled" else default)
    monkeypatch.setattr(Settings, "MULTILAYER_EXTRACTION_ENABLED", multilayer)


def _worker(db, llm, aliases=None) -> LoreWorker:
    return LoreWorker(store=FakeStore(), db=db, llm=llm, bot_id=1,
                      aliases=aliases)


def _rows(*names) -> list[dict]:
    return [{"author_name": n} for n in names]


async def _memes(db, chat_id=CHAT_ID):
    cursor = await db.db.execute(
        "SELECT fact, target_user, status, belief_meta FROM graph_facts "
        "WHERE chat_id = ? AND status = 'chat_meme' ORDER BY id", (chat_id,))
    return [dict(r) for r in await cursor.fetchall()]


_LAYER_A_OK = json.dumps({
    "candidates": [
        {"target": "Никита", "kind": "person_fact",
         "text": "живёт в Питере, работает в IT", "evidence": [1, 2],
         "confidence": 0.8, "reason": "устойчивый факт"},
        {"target": "Вася", "kind": "meme", "text": "повелитель грибов",
         "evidence": [], "confidence": 0.6, "reason": "шутливый титул"},
        {"target": "Кирилл", "kind": "other_person",
         "text": "Кирилл из другого чата", "evidence": [3],
         "confidence": 0.5, "reason": "не участник"},
    ],
    "discarded": [
        {"text": "площадь Тяньаньмэнь и танки", "kind": "copypasta",
         "reason": "энциклопедическая копипаста"},
        {"text": "инструкция по сокрытию трупа", "kind": "joke",
         "reason": "шуточная инструкция"},
    ],
}, ensure_ascii=False)

_LAYER_B_OK = json.dumps({
    "portrait": "Никита - житель северной столицы, занят в сфере технологий",
    "patterns": ["возвращается к теме работы"],
    "themes": ["технологии"],
    "memes": [{"target": "Вася", "text": "повелитель грибов"}],
}, ensure_ascii=False)


# ── §8.1 парсеры ──────────────────────────────────────────────────────────

class TestParseLayerA:
    def test_valid(self):
        out = parse_layer_a(_LAYER_A_OK)
        assert len(out["candidates"]) == 3
        assert out["candidates"][0]["evidence"] == [1, 2]
        assert len(out["discarded"]) == 2
        assert out["discarded"][0]["kind"] == "copypasta"

    def test_code_fence(self):
        raw = "```json\n" + _LAYER_A_OK + "\n```"
        assert len(parse_layer_a(raw)["candidates"]) == 3

    def test_broken_json_raises(self):
        for raw in ("не json", "", None, "[1,2,3]", '{"no_keys":1}'):
            with pytest.raises(ValueError):
                parse_layer_a(raw)

    def test_person_fact_without_evidence_dropped(self):
        raw = json.dumps({"candidates": [
            {"target": "Вася", "kind": "person_fact", "text": "без улик",
             "evidence": []},
            {"target": "Вася", "kind": "person_fact", "text": "с уликой",
             "evidence": [1]},
        ], "discarded": []})
        out = parse_layer_a(raw)
        assert [c["text"] for c in out["candidates"]] == ["с уликой"]

    def test_noise_kind_dropped(self):
        raw = json.dumps({"candidates": [
            {"target": "-", "kind": "noise", "text": "спам", "evidence": [1]},
            {"target": "Вася", "kind": "meme", "text": "мем"},
        ], "discarded": []})
        out = parse_layer_a(raw)
        assert [c["kind"] for c in out["candidates"]] == ["meme"]

    def test_canon_applied(self):
        raw = json.dumps({"candidates": [
            {"target": "Вася", "kind": "meme", "text": "мем"}],
            "discarded": []})
        out = parse_layer_a(raw, canon=lambda n: n.lower())
        assert out["candidates"][0]["target"] == "вася"


class TestParseLayerB:
    def test_valid(self):
        out = parse_layer_b(_LAYER_B_OK)
        assert out["portrait"].startswith("Никита")
        assert out["patterns"] == ["возвращается к теме работы"]
        assert out["memes"][0]["text"] == "повелитель грибов"

    def test_code_fence(self):
        raw = "```json\n" + _LAYER_B_OK + "\n```"
        assert parse_layer_b(raw)["themes"] == ["технологии"]

    def test_broken_json_raises(self):
        for raw in ("не json", "", None, '{"no_keys":1}'):
            with pytest.raises(ValueError):
                parse_layer_b(raw)

    def test_wrong_types_raise(self):
        with pytest.raises(ValueError):
            parse_layer_b('{"patterns":"нет"}')


class TestFilterLayerA:
    def test_roster_entity_resolution(self):
        parsed = parse_layer_a(_LAYER_A_OK)
        out = filter_layer_a_candidates(parsed, ["Никита", "Вася"])
        assert [c["target"] for c in out["person_facts"]] == ["Никита"]
        assert [c["text"] for c in out["memes"]] == ["повелитель грибов"]
        reasons = {d["reason"] for d in out["dropped"]}
        assert "kind_other_person" in reasons       # «Кирилл» — не участник
        assert any(d["kind"] == "other_person" for d in out["dropped"])

    def test_unknown_person_fact_dropped(self):
        parsed = {"candidates": [
            {"target": "Кирилл", "kind": "person_fact", "text": "х",
             "evidence": [1], "confidence": 0.5, "reason": ""}],
            "discarded": []}
        out = filter_layer_a_candidates(parsed, ["Никита"])
        assert out["person_facts"] == []
        assert out["dropped"][0]["reason"] == "unknown_entity"


class TestVerbatimValidator:
    def test_seven_word_quote_detected(self):
        window = ["[ts] Вася: я люблю ходить в горы каждое воскресенье утром"]
        assert find_verbatim_quote(
            "история: люблю ходить в горы каждое воскресенье утром давно",
            window) is not None

    def test_six_word_overlap_allowed(self):
        window = ["[ts] Вася: люблю ходить в горы каждое воскресенье утром"]
        # пересечение ровно 6 слов (порог > 6) не отклоняется
        assert find_verbatim_quote(
            "он говорит что любит ходить в горы каждое воскресенье",
            window) is None

    def test_validate_drops_portrait_keeps_memes(self):
        window = ["[ts] Вася: я люблю ходить в горы каждое воскресенье утром"]
        layer_b = {
            "portrait": "люблю ходить в горы каждое воскресенье утром",
            "patterns": ["любит горы"],
            "themes": [],
            "memes": [{"target": "Вася", "text": "горный"}],
        }
        out = validate_layer_b(layer_b, window)
        assert out["portrait"] == ""
        assert out["memes"][0]["text"] == "горный"
        assert out["rejected"][0]["field"] == "portrait"


# ── §8.2/8.3 двухслойность и кейсы ТЗ ──────────────────────────────────────

class TestMultilayerPipeline:
    @pytest.mark.asyncio
    async def test_two_calls_only_filtered_memes_written(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_OK])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера",
                      "[ts] Вася: я повелитель грибов"],
            _rows("Никита", "Вася"))

        assert llm.worker_calls == 2
        assert llm.worker_roles == ["background", "background"]
        memes = await _memes(db)
        assert [m["fact"] for m in memes] == ["повелитель грибов"]
        # person_fact и копипаста/шутка/чужое имя в досье НЕ пишутся
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE chat_id = ? "
            "AND fact LIKE '%Питере%'", (CHAT_ID,))
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_layer_b_sees_only_filtered_input(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_OK])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера"], _rows("Никита", "Вася"))
        layer_b_prompt = llm.calls[1][1]["content"]
        assert "Никита: живёт в Питере" in layer_b_prompt
        assert "повелитель грибов" in layer_b_prompt
        # мусор/чужое имя в Слой Б не попадают
        assert "Тяньаньмэнь" not in layer_b_prompt
        assert "Кирилл" not in layer_b_prompt

    @pytest.mark.asyncio
    async def test_joke_title_becomes_chat_meme(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        a = json.dumps({"candidates": [
            {"target": "Вася", "kind": "meme", "text": "повелитель грибов"}],
            "discarded": []})
        b = json.dumps({"portrait": "", "patterns": [], "themes": [],
                        "memes": [{"target": "Вася",
                                   "text": "повелитель грибов"}]})
        llm = FakeLLM(sequence=[a, b])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        assert [m["fact"] for m in await _memes(db)] == ["повелитель грибов"]


# ── §8.4 fallback ─────────────────────────────────────────────────────────

class TestFallback:
    @pytest.mark.asyncio
    async def test_layer_a_garbage_falls_back_to_1020(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        legacy = json.dumps({"chat_memes": [
            {"target": "Вася", "text": "мегачмо"}]}, ensure_ascii=False)
        llm = FakeLLM(sequence=["не json", "снова не json", legacy])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["[ts] Вася: x"],
                                            _rows("Вася"))
        assert llm.worker_calls == 3                    # A + retryA + legacy
        assert [m["fact"] for m in await _memes(db)] == ["мегачмо"]

    @pytest.mark.asyncio
    async def test_layer_a_raise_falls_back_to_1020(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        legacy = json.dumps({"chat_memes": [
            {"target": "Вася", "text": "мегачмо"}]}, ensure_ascii=False)
        llm = FakeLLM(sequence=[legacy], raise_times=1)
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        assert [m["fact"] for m in await _memes(db)] == ["мегачмо"]

    @pytest.mark.asyncio
    async def test_layer_b_garbage_keeps_layer_a_memes(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        a = json.dumps({"candidates": [
            {"target": "Вася", "kind": "meme", "text": "мегачмо"}],
            "discarded": []})
        llm = FakeLLM(sequence=[a, "не json", "снова не json"])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        assert [m["fact"] for m in await _memes(db)] == ["мегачмо"]

    @pytest.mark.asyncio
    async def test_portrait_verbatim_rejected_memes_written(
            self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        window = ["[ts] Вася: ты знаешь я люблю ходить в горы каждое "
                  "воскресенье утром"]
        a = json.dumps({"candidates": [
            {"target": "Вася", "kind": "person_fact", "text": "любит горы",
             "evidence": [1]},
            {"target": "Вася", "kind": "meme", "text": "горный"}],
            "discarded": []})
        b = json.dumps({"portrait": "люблю ходить в горы каждое воскресенье "
                                    "утром",
                        "patterns": [], "themes": [],
                        "memes": [{"target": "Вася", "text": "горный"}]},
                       ensure_ascii=False)
        llm = FakeLLM(sequence=[a, b])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, window, _rows("Вася"))
        assert [m["fact"] for m in await _memes(db)] == ["горный"]


# ── §8.5 kill-switch OFF ──────────────────────────────────────────────────

class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_off_is_1020_byte_compatible(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=False)
        legacy = json.dumps({"chat_memes": [
            {"target": "Вася", "text": "мегачмо"}]}, ensure_ascii=False)
        llm = FakeLLM(sequence=[legacy])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["[ts] Вася: x"],
                                            _rows("Вася"))
        assert llm.worker_calls == 1                    # ровно single-pass
        assert llm.calls[0][0]["content"] == DOSSIER_SYSTEM_PROMPT
        assert [m["fact"] for m in await _memes(db)] == ["мегачмо"]

    @pytest.mark.asyncio
    async def test_off_retry_semantics(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=False)
        llm = FakeLLM(sequence=["не json", "снова не json"])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        assert llm.worker_calls == 2
        assert await _memes(db) == []

    @pytest.mark.asyncio
    async def test_irony_off_multilayer_on_still_writes(self, db, monkeypatch):
        """F1 fix-round 2: пайплайн и персистенция НЕ гейтятся историческим
        irony-флагом (IRONY_FILTER_ENABLED=False), управляет только
        MULTILAYER_EXTRACTION_ENABLED (default ON)."""
        _flag(monkeypatch, enabled=False, multilayer=True)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_MULTI])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера"], _rows("Никита", "Вася"))
        assert llm.worker_calls == 2
        assert [m["fact"] for m in await _memes(db)] == ["повелитель грибов"]
        assert [r["target_user"] for r in await _portrait_rows(db)] == ["Никита"]

    @pytest.mark.asyncio
    async def test_killswitch_off_irony_off_writes_nothing(self, db, monkeypatch):
        """Kill-switch OFF возвращает путь 10.20, который по-прежнему гейтится
        irony-флагом: при обоих OFF классификации нет."""
        _flag(monkeypatch, enabled=False, multilayer=False)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_MULTI])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера"], _rows("Никита", "Вася"))
        assert llm.worker_calls == 0
        assert await _memes(db) == []
        assert await _portrait_rows(db) == []

    def test_default_setting_is_on(self):
        assert Settings.MULTILAYER_EXTRACTION_ENABLED is True


# ── §8.6 бюджет ───────────────────────────────────────────────────────────

class TestBudget:
    @pytest.mark.asyncio
    async def test_a_plus_b_forecast_two_calls(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        seen: list[dict] = []

        async def _consume(pg, scope, metric, amount=1):
            seen.append({"scope": scope, "metric": metric, "amount": amount})
            return True
        monkeypatch.setattr(worker_budget, "consume", _consume)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_OK])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"],
                                            _rows("Никита", "Вася"))
        calls = [s for s in seen if s["metric"] == "llm_calls"]
        assert calls and all(s["amount"] == 2 for s in calls)

    @pytest.mark.asyncio
    async def test_budget_exhausted_skips(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)

        async def _deny(*args, **kwargs):
            return False
        monkeypatch.setattr(worker_budget, "consume", _deny)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_OK])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"],
                                            _rows("Никита", "Вася"))
        assert llm.worker_calls == 0
        assert await _memes(db) == []


# ── §8.7/8.8 детерминизм и Д3 ─────────────────────────────────────────────

class TestDeterminismAndOverrides:
    def test_parsers_deterministic(self):
        assert parse_layer_a(_LAYER_A_OK) == parse_layer_a(_LAYER_A_OK)
        assert parse_layer_b(_LAYER_B_OK) == parse_layer_b(_LAYER_B_OK)

    def test_filter_deterministic(self):
        parsed = parse_layer_a(_LAYER_A_OK)
        first = filter_layer_a_candidates(parsed, ["Никита", "Вася"])
        second = filter_layer_a_candidates(parsed, ["Никита", "Вася"])
        assert first == second

    @pytest.mark.asyncio
    async def test_manual_overrides_untouched(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        await db.set_dossier_override(CHAT_ID, 10, "ручная правка: не трогать",
                                      1700000000)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_OK])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера"], _rows("Никита", "Вася"))
        assert await db.get_dossier_override(CHAT_ID, 10) == \
            "ручная правка: не трогать"


class TestBuilders:
    def test_layer_a_user_numbered(self):
        text = build_layer_a_user(["[ts] Вася: привет"], ["Вася"])
        assert "1. [ts] Вася: привет" in text
        assert "target только из этого списка" in text

    def test_layer_b_user_only_filtered(self):
        text = build_layer_b_user(
            [{"target": "Никита", "text": "живёт в Питере",
              "evidence": [1, 2]}],
            [{"target": "Вася", "text": "повелитель грибов"}], ["Никита"])
        assert "Никита: живёт в Питере (evidence: 1,2)" in text
        assert "Вася: повелитель грибов" in text

    def test_layer_b_user_empty(self):
        text = build_layer_b_user([], [])
        assert "(нет)" in text


# ── fix-round 10.21 (Issue 1): per-target персистенция портрета ─────────────

from services import memory_rebuild as _mr                    # noqa: E402
from services.dossier_prompts import (                          # noqa: E402
    render_generated_portrait,
)
from web.api.chat_lore import _dossier_payload                   # noqa: E402

_LAYER_B_MULTI = json.dumps({
    "portraits": [
        {"target": "Никита",
         "portrait": "житель северной столицы, занят в сфере технологий",
         "patterns": ["возвращается к теме работы"],
         "themes": ["технологии"]},
    ],
    "memes": [{"target": "Вася", "text": "повелитель грибов"}],
}, ensure_ascii=False)


async def _portrait_rows(db, chat_id=CHAT_ID):
    cursor = await db.db.execute(
        "SELECT id, fact, target_user, weight, status, belief_meta "
        "FROM graph_facts WHERE chat_id = ? AND status = 'dossier_portrait' "
        "ORDER BY id", (chat_id,))
    return [dict(r) for r in await cursor.fetchall()]


async def _schema_objects(db):
    cursor = await db.db.execute(
        "SELECT type, name FROM sqlite_master ORDER BY type, name")
    return [tuple(r) for r in await cursor.fetchall()]


class TestLayerBPerTarget:
    def test_parse_per_target(self):
        out = parse_layer_b(_LAYER_B_MULTI)
        assert len(out["portraits"]) == 1
        assert out["portraits"][0]["target"] == "Никита"
        assert out["portraits"][0]["patterns"] == ["возвращается к теме работы"]
        assert out["portraits"][0]["themes"] == ["технологии"]
        assert out["legacy_fields_present"] is False

    def test_legacy_fields_accepted_but_not_persistable(self):
        out = parse_layer_b(_LAYER_B_OK)
        assert out["portraits"] == []
        assert out["legacy_fields_present"] is True
        assert out["portrait"].startswith("Никита")   # читается для совместимости

    def test_validate_per_target_verbatim(self):
        window = ["[ts] Вася: я люблю ходить в горы каждое воскресенье утром"]
        layer_b = {
            "portraits": [
                {"target": "Вася",
                 "portrait": "люблю ходить в горы каждое воскресенье утром",
                 "patterns": ["любит горы"], "themes": []}],
            "memes": [{"target": "Вася", "text": "горный"}],
        }
        out = validate_layer_b(layer_b, window)
        assert out["portraits"][0]["portrait"] == ""
        assert out["portraits"][0]["patterns"] == ["любит горы"]
        assert any(r["field"] == "portrait[0]" for r in out["rejected"])
        assert out["memes"][0]["text"] == "горный"

    def test_render_portrait_from_patterns(self):
        assert render_generated_portrait("", ["а"], ["б"]) == \
            "Паттерны: а Темы: б"
        assert render_generated_portrait("", [], []) == ""


class TestPortraitPersistence:
    @pytest.mark.asyncio
    async def test_pipeline_writes_and_consumer_reads(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_MULTI])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера"], _rows("Никита", "Вася"))
        rows = await _portrait_rows(db)
        assert [r["target_user"] for r in rows] == ["Никита"]
        assert rows[0]["weight"] == 0.3
        meta = json.loads(rows[0]["belief_meta"])
        assert meta["generated"] is True
        assert meta["generator"] == "layer_b"
        assert meta["contract_version"] == 1
        got = await db.get_generated_dossier(CHAT_ID, "Никита")
        assert got is not None
        assert got["patterns"] == ["возвращается к теме работы"]
        assert got["themes"] == ["технологии"]
        assert got["generated"] is True

    @pytest.mark.asyncio
    async def test_upsert_one_row_and_update(self, db):
        first = await db.upsert_generated_dossier(
            CHAT_ID, "Никита", "п1", ["a"], ["t"], 100)
        second = await db.upsert_generated_dossier(
            CHAT_ID, "Никита", "п2", ["b"], ["u"], 200)
        rows = await _portrait_rows(db)
        assert len(rows) == 1
        assert first == second
        assert rows[0]["fact"] == "п2"
        got = await db.get_generated_dossier(CHAT_ID, "Никита")
        assert got["portrait"] == "п2" and got["updated_at"] == 200

    @pytest.mark.asyncio
    async def test_repeated_pipeline_idempotent(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        llm = FakeLLM(sequence=[_LAYER_A_OK, _LAYER_B_MULTI,
                                _LAYER_A_OK, _LAYER_B_MULTI])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера"], _rows("Никита", "Вася"))
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Никита: я из Питера"], _rows("Никита", "Вася"))
        rows = await _portrait_rows(db)
        assert len(rows) == 1
        assert [m["fact"] for m in await _memes(db)] == ["повелитель грибов"]

    @pytest.mark.asyncio
    async def test_verbatim_portrait_not_persisted(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        window = ["[ts] Вася: ты знаешь я люблю ходить в горы каждое "
                  "воскресенье утром"]
        a = json.dumps({"candidates": [
            {"target": "Вася", "kind": "person_fact", "text": "любит горы",
             "evidence": [1]}], "discarded": []})
        b = json.dumps({"portraits": [
            {"target": "Вася",
             "portrait": "люблю ходить в горы каждое воскресенье утром",
             "patterns": [], "themes": []}], "memes": []}, ensure_ascii=False)
        worker = _worker(db, FakeLLM(sequence=[a, b]))
        await worker._classify_dossier_safe(CHAT_ID, window, _rows("Вася"))
        assert await _portrait_rows(db) == []

    @pytest.mark.asyncio
    async def test_zero_ddl_user_version_and_schema(self, db):
        before = await _schema_objects(db)
        await db.upsert_generated_dossier(CHAT_ID, "Никита", "п", ["a"], ["t"])
        after = await _schema_objects(db)
        assert before == after
        cursor = await db.db.execute("PRAGMA user_version")
        assert int((await cursor.fetchone())[0]) == 12

    @pytest.mark.asyncio
    async def test_manual_override_priority_in_payload(self, db):
        await db.set_dossier_override(CHAT_ID, 10, "ручная правка", 1)
        await db.upsert_generated_dossier(
            CHAT_ID, "Никита", "авто-портрет", ["p"], ["t"], 100)
        payload = await _dossier_payload(db, CHAT_ID, 10, "Никита")
        assert payload["portrait_source"] == "manual"
        assert payload["portrait"] == "ручная правка"
        assert payload["generated_portrait"] == "авто-портрет"
        assert payload["patterns"] == ["p"]
        assert payload["themes"] == ["t"]

    @pytest.mark.asyncio
    async def test_payload_generated_when_no_manual(self, db):
        await db.upsert_generated_dossier(
            CHAT_ID, "Никита", "авто-портрет", [], [], 100)
        payload = await _dossier_payload(db, CHAT_ID, 10, "Никита")
        assert payload["portrait_source"] == "generated"
        assert payload["portrait"] == "авто-портрет"
        assert payload["generated_updated_at"] == 100

    @pytest.mark.asyncio
    async def test_payload_none_without_portrait(self, db):
        payload = await _dossier_payload(db, CHAT_ID, 10, "Никита")
        assert payload["portrait_source"] == "none"
        assert payload["portrait"] == ""
        assert payload["generated_updated_at"] is None


class TestPortraitIsolation:
    @pytest.mark.asyncio
    async def test_row_hidden_from_all_confirmed_readers(self, db):
        now = int(time.time())
        fid = await db.upsert_generated_dossier(
            CHAT_ID, "Никита", "секретный портрет", ["p"], ["t"], now)
        assert fid > 0
        card = await db.get_persona_card(CHAT_ID, "Никита", 10, now)
        assert "секретный портрет" not in card["facts"]
        names = {name for name, _c in await db.get_persona_names(CHAT_ID, now)}
        assert "Никита" not in names
        assert await db.list_chat_memes(CHAT_ID) == []
        hits = await db.search_graph_facts_fts(CHAT_ID, "секретный", 10, now)
        assert [dict(h)["fact"] for h in hits] == []
        dream = await db.get_dream_candidates(
            CHAT_ID, now, origins=("chat_history",), since_ts=0)
        assert dream == []
        orphans = await _mr._list_orphan_facts(db, CHAT_ID, 50)
        assert all(r["id"] != fid for r in orphans)


class TestBudgetActualConsume:
    @pytest.mark.asyncio
    async def test_retry_consumed_on_spot(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        seen: list[int] = []

        async def _consume(pg, scope, metric, amount=1):
            if metric == "llm_calls":
                seen.append(int(amount))
            return True
        monkeypatch.setattr(worker_budget, "consume", _consume)
        llm = FakeLLM(sequence=["не json", _LAYER_A_OK, _LAYER_B_OK])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"],
                                            _rows("Никита", "Вася"))
        assert seen == [2, 2, 1, 1]               # прогноз A+B (global+chat) + retry A

    @pytest.mark.asyncio
    async def test_fallback_consumed_on_spot(self, db, monkeypatch):
        _flag(monkeypatch, multilayer=True)
        seen: list[int] = []

        async def _consume(pg, scope, metric, amount=1):
            if metric == "llm_calls":
                seen.append(int(amount))
            return True
        monkeypatch.setattr(worker_budget, "consume", _consume)
        legacy = json.dumps({"chat_memes": [
            {"target": "Вася", "text": "мегачмо"}]}, ensure_ascii=False)
        llm = FakeLLM(sequence=["не json", "снова не json", legacy])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        assert seen == [2, 2, 1, 1, 1, 1]         # A+B + retry A + fallback
        assert [m["fact"] for m in await _memes(db)] == ["мегачмо"]

    @pytest.mark.asyncio
    async def test_legacy_retry_consumed_on_spot(self, db, monkeypatch):
        """F1 fix-round 2: retry запасного пути 10.20 (второй `_dossier_llm`)
        тоже добирает фактический consume сверх прогноза/fallback."""
        _flag(monkeypatch, multilayer=True)
        seen: list[int] = []

        async def _consume(pg, scope, metric, amount=1):
            if metric == "llm_calls":
                seen.append(int(amount))
            return True
        monkeypatch.setattr(worker_budget, "consume", _consume)
        llm = FakeLLM(sequence=["не json", "снова не json",
                                "не json", "снова не json"])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        # прогноз A+B (2) + retry A + fallback legacy + retry legacy
        assert seen == [2, 2, 1, 1, 1, 1, 1, 1]
        assert llm.worker_calls == 4
        assert await _memes(db) == []

