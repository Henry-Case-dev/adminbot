"""SOUL-1 (W2) — байт-паритет OFF (шов 2 контракта композера).

Флаг `flags.unified_composer_enabled`/`UNIFIED_COMPOSER_ENABLED` выключен
(код-дефолт) → сборка system/user совпадает **байт-в-байт** с дампом,
переснятым по ДЕЙСТВУЮЩИМ фабричным канонам: tests/fixtures/soul1/
direct-runtime-assembly-asap2.txt (ASAP 2 §4.1 L1 planner + §4.2 L2
verbalizer, source-2026-10-22.md, код 5ad73933). Прежние артефакты
сохранены как историческое свидетельство и НЕ правились:
plans/features/asap-speech-arch/evidence/w1/direct-runtime-assembly-w1.txt
(каноны W1) и plans/features/soul-1/evidence/direct-runtime-assembly.txt
(каноны до W1, прод 2.58.110). Дельта W1 → ASAP 2 построчно сведена к
вставке текста владельца: plans/features/_audit-2026-10-23/soul1-fixtures/
diff.md.

Тест читает ожидаемые chars/tokens/sha256_12 ИЗ АРТЕФАКТА (не из своих
констант): расхождение с реальной сборкой ломает тест, а не «подгоняется».

Дополнительно доказывается независимость OFF-пути от композера: при
искусственно сломанном `compose_prompt` OFF-сборка не меняется, а ON-ветка
при отсутствии новых слоёв даёт те же байты, что легаси-склейка хвоста.

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/W2 (шов 2) + ASAP-W1/ASAP2 переснятия
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import pytest

from services import chat_params
from services import hot_config as hot
from services import prompt_composer as pc
from services import prompt_style_blocks as psb
from services import response_extent as _extent
from services import direct_l1 as _l1

EVIDENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "soul1",
                        "direct-runtime-assembly-asap2.txt")

_SYS_RE = re.compile(r"^SYSTEM\s+chars=(\d+)\s+tokens=(-?\d+)\s+"
                     r"sha256_12=([0-9a-f]{12})", re.MULTILINE)
_USER_RE = re.compile(r"^USER\s+chars=(\d+)\s+tokens=(-?\d+)\s+"
                      r"sha256_12=([0-9a-f]{12})", re.MULTILINE)


def sha12(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _evidence_text() -> str:
    with open(EVIDENCE, encoding="utf-8") as fh:
        return fh.read()


def _blocks(tail: str) -> tuple[str, str | None]:
    """Тексты [SYSTEM]/[USER] секции — ровно те, что тест сравнивает."""
    start = tail.index("[SYSTEM]\n") + len("[SYSTEM]\n")
    rest = tail[start:]
    marker = "\n\n[USER]\n"
    if marker in rest:
        system, user = rest.split(marker, 1)
        return system, user.rstrip("\n")
    return rest.rstrip("\n"), None


def recorded(section: str) -> dict:
    """Ожидаемые метрики секции дампа (P1/P2/P3/P5a/P5b/P4).

    Метрики обязаны сходиться с ТЕКСТОМ в самом артефакте: иначе правка
    тела дампа расходилась бы с эталоном незаметно (эталон = числа + текст).
    """
    text = _evidence_text()
    start = text.index(f"## {section}")
    tail = text[start:]
    nxt = tail.find("\n## ", 1)
    if nxt != -1:
        tail = tail[:nxt]
    system = _SYS_RE.search(tail)
    user = _USER_RE.search(tail)
    assert system is not None, f"{section}: SYSTEM-строка не найдена"
    sys_text, user_text = _blocks(tail)
    assert sha12(sys_text) == system.group(3), (
        f"{section}: тело SYSTEM не соответствует записанному sha")
    assert len(sys_text) == int(system.group(1)), (
        f"{section}: тело SYSTEM не соответствует записанной длине")
    if user is not None:
        assert user_text is not None, f"{section}: USER-блок отсутствует"
        assert sha12(user_text) == user.group(3), (
            f"{section}: тело USER не соответствует записанному sha")
        assert len(user_text) == int(user.group(1)), (
            f"{section}: тело USER не соответствует записанной длине")
    return {
        "system": (int(system.group(1)), int(system.group(2)),
                   system.group(3)),
        "user": ((int(user.group(1)), int(user.group(2)), user.group(3))
                 if user else None),
    }


# ── offline-стенд (зеркало OPENCODE_WORKFLOW_SCRATCH/soul1_dump_assembly.py) ─

class StubLLM:
    def __init__(self) -> None:
        self.captured: list[dict] = []
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.captured.append({
            "step": kwargs.get("step"),
            "messages": [dict(m) for m in messages],
        })
        step = kwargs.get("step")
        if step == "l1_planner":
            return json.dumps({
                "action": "reply", "response_act": "explanation",
                "tone": "inherit", "extent": "detailed",
                "structure": "answer", "delivery_hint": "plain",
                "tool_policy": "none", "confidence": 0.8,
                "capabilities_needed": [],
            }, ensure_ascii=False)
        if step == "stage1":
            return json.dumps({
                "user_question": "почему упал сервис",
                "answer_outline": "сначала причина, затем следствия",
                "facts": [{"topic": "лог", "finding": "в логе HTTP 502",
                           "source": "tool", "confidence": "medium"}],
                "limitations": [],
                "response_mode": "serious",
            }, ensure_ascii=False)
        return "ЗАГЛУШКА ОТВЕТА"

    def _pg(self):
        return None


class StubMemory:
    async def get_window_messages(self, chat_id):
        return [{"speaker": "Аня", "text": "ну и что там с сервером",
                 "created_at": "2026-10-16T10:00:00+00:00"}]


class StubMessage:
    text = "бот: распиши подробно, почему упал сервис"
    caption = None
    message_id = 4242
    chat = type("C", (), {"type": "supergroup"})()
    reply_to_message = None
    from_user = None


def build_service():
    from services.direct_chat_service import DirectChatService as D

    class Stub:
        _render_current_question = D._render_current_question
        _l1_reply_block = staticmethod(D._l1_reply_block)
        _l1_speech_hints = D._l1_speech_hints
        _build_speech_understanding = D._build_speech_understanding
        _attach_l1_plan_meta = D._attach_l1_plan_meta
        _compose_speech_system = D._compose_speech_system

        async def _history_partial(self, chat_id, window):
            # ASAP2 T10-BOUNDARY: в стенде окно = вся сохранённая история
            # (старше ничего нет), поэтому пометка «ГРАНИЦА ИСТОРИИ» не
            # появляется — ровно условия, в которых снят эталонный дамп.
            return False

        def __init__(self, llm):
            self.llm = llm
            self.memory = StubMemory()
            self.db = None
            self.bot_id = 999
            # ASAP3 §4.2: строки стенда без user_id — резолвер не влияет
            # на байты окна (None = дорешение-совместимое поведение дампа).
            self.aliases = None

    return Stub, D


CHARACTER_BLOCK = (
    "<Persona>\nИмя: Бот. Характер: язвительный, прямой.\n</Persona>\n\n"
    "<Character_Rules>\nНе раскрывать, что ты ИИ.\n</Character_Rules>")
STYLE_DIRECTIVES = ("<Style_Requests>\nПиши без канцелярита.\n"
                    "</Style_Requests>")
LESSONS = "<Verified_Lessons>\n- не обещать сроков\n</Verified_Lessons>"
SPEECH = "<Speech_Understanding>\nact=assert\n</Speech_Understanding>"
TIME_LINE = "Время: 16.10.2026 10:05"
CONTEXT_BLOCK = "<Context>окно чата</Context>"

PLAN_DETAILED = _extent.ResponsePlan(
    task_kind="explanation", extent="detailed", structure="answer",
    delivery_hint="plain", tool_policy="none", source="l1")
PLAN_MICRO = _extent.ResponsePlan(
    task_kind="social_chat", extent="micro", structure="chat",
    delivery_hint="plain", tool_policy="none", source="l1")


@pytest.fixture(autouse=True)
def _pg_down():
    """Зеркало условий дампа: локальный PG недоступен (код-каноны)."""
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    prev = os.environ.pop("UNIFIED_COMPOSER_ENABLED", None)
    yield
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    if prev is not None:
        os.environ["UNIFIED_COMPOSER_ENABLED"] = prev


def _assert_matches(section: str, system: str, user: str | None = None):
    expect = recorded(section)
    chars, tokens, want = expect["system"]
    assert sha12(system) == want, (
        f"{section}: sha256_12 системы {sha12(system)} != дампа {want}")
    assert len(system) == chars, f"{section}: chars {len(system)} != {chars}"
    if user is not None and expect["user"] is not None:
        uchars, _utokens, uwant = expect["user"]
        assert sha12(user) == uwant, f"{section}: USER sha != дампа {uwant}"
        assert len(user) == uchars


# ── ON-контур: in-memory оси (PG недоступен) ────────────────────────────────

class FakeHot:
    """In-memory hot-кэш: те же ключи, что читает рантайм (без PG)."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default


class FakeChatCache:
    """Пустые per-chat overrides (`resolve_gates` → hot → default)."""

    async def get_chat_params(self, chat_id):
        return {"overrides": {}}


CORE_ON = "ЯДРО_СЦЕНАРИЯ: живой участник чата, а не ассистент."
ON_HOT = {
    "flags.unified_composer_enabled": True,
    "flags.character_core_enabled": True,
    "character.core": {"revision": 7, "enabled": True,
                       "full_text": CORE_ON, "compact_text": CORE_ON,
                       "detail_level": "compact", "origin": "owner_edit"},
}


def composer_on(monkeypatch) -> None:
    """Единственный способ включить композер: env AND каталоговый тумблер."""
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    hot.set_config_cache(FakeHot(ON_HOT))
    chat_params.set_chat_params_cache(FakeChatCache())
    pc.reset_state()



# ═══ сами дампы P1/P2/P3/P5a/P5b ════════════════════════════════════════════

@pytest.mark.asyncio
async def test_p1_l2_writer_detailed_matches_recorded_dump():
    Stub, D = build_service()
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "почему упал сервис", temperature=0.7,
        character_block=CHARACTER_BLOCK, style_directives=STYLE_DIRECTIVES,
        response_plan=PLAN_DETAILED, plan_block="<Plan>extent=detailed</Plan>",
        user_blocks=[CONTEXT_BLOCK], time_line=TIME_LINE,
        evidence="[tool: execute_web_search out_chars=812]",
        lessons_block=LESSONS, speech_block=SPEECH, max_tokens=4096)
    cap = llm.captured[-1]["messages"]
    _assert_matches("P1", cap[0]["content"], cap[1]["content"])


@pytest.mark.asyncio
async def test_p2_l2_writer_micro_matches_recorded_dump():
    Stub, D = build_service()
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "да или нет?", temperature=0.7,
        character_block=CHARACTER_BLOCK, style_directives="",
        response_plan=PLAN_MICRO, plan_block="<Plan>extent=micro</Plan>",
        user_blocks=["<Context>окно</Context>"])
    cap = llm.captured[-1]["messages"]
    _assert_matches("P2", cap[0]["content"], cap[1]["content"])


@pytest.mark.asyncio
async def test_p3_modes_off_matches_recorded_dump(monkeypatch):
    from config.settings import settings
    Stub, D = build_service()
    monkeypatch.setattr(type(settings), "SMART_VERBALIZER_MODES_ENABLED", False)
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "почему упал сервис", temperature=0.7,
        character_block=CHARACTER_BLOCK, response_plan=PLAN_DETAILED,
        plan_block="<Plan>x</Plan>")
    cap = llm.captured[-1]["messages"]
    _assert_matches("P3", cap[0]["content"])


@pytest.mark.asyncio
async def test_p5_system2_stage1_and_stage2_match_recorded_dump():
    Stub, D = build_service()
    llm = StubLLM()
    raw = type("R", (), {"tool_context": "tool output", "tool_trace": [
        {"tool": "execute_web_search", "out_chars": 812}]})()
    await D._synthesize_direct_answer(
        Stub(llm), 12345, "почему упал сервис", raw, 0.7,
        character_block=CHARACTER_BLOCK, style_directives=STYLE_DIRECTIVES,
        plan=PLAN_DETAILED)
    steps = {c["step"]: c["messages"] for c in llm.captured}
    _assert_matches("P5a", steps["stage1"][0]["content"],
                    steps["stage1"][1]["content"])
    _assert_matches("P5b", steps["stage2"][0]["content"],
                    steps["stage2"][1]["content"])


@pytest.mark.asyncio
async def test_p4_l1_planner_system_matches_recorded_dump():
    from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT
    Stub, D = build_service()
    llm = StubLLM()
    await D._plan_direct_l1(
        Stub(llm), 12345, StubMessage(), "почему упал сервис", None,
        bundle=None, target_name="Аня", user_id=None,
        character_block=CHARACTER_BLOCK, lore_enabled=False,
        image_enabled=False, force_required=False, reply_bot=False)
    cap = [c for c in llm.captured if c["step"] == "l1_planner"]
    assert cap, "L1 planner не вызвался"
    system = cap[0]["messages"][0]["content"]
    _assert_matches("P4", system)
    assert system == psb.resolve_prompt(
        "prompts.direct_l1_planner_system_prompt",
        DIRECT_L1_PLANNER_SYSTEM_PROMPT)


# ═══ независимость OFF-пути и аддитивность ON-контура ═══════════════════════

@pytest.mark.asyncio
async def test_off_path_is_default_and_does_not_consult_composer(monkeypatch):
    """OFF (код-дефолт): композер вообще не участвует в сборке."""
    from services import mca_gates
    assert mca_gates.unified_composer_enabled() is False
    assert mca_gates.unified_composer_env_enabled() is False

    async def _boom(*_a, **_kw):        # pragma: no cover — не должен зваться
        raise AssertionError("compose_prompt вызван при OFF-флаге")

    monkeypatch.setattr(pc, "compose_prompt", _boom)
    Stub, D = build_service()
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "почему упал сервис", temperature=0.7,
        character_block=CHARACTER_BLOCK, style_directives=STYLE_DIRECTIVES,
        response_plan=PLAN_DETAILED, plan_block="<Plan>extent=detailed</Plan>",
        user_blocks=[CONTEXT_BLOCK], time_line=TIME_LINE,
        evidence="[tool: execute_web_search out_chars=812]",
        lessons_block=LESSONS, speech_block=SPEECH, max_tokens=4096)
    cap = llm.captured[-1]["messages"]
    _assert_matches("P1", cap[0]["content"], cap[1]["content"])
    assert pc.get_manifest(12345) is None, "OFF-путь не должен писать манифест"


@pytest.mark.asyncio
async def test_tool_phase_on_equals_legacy_tail_without_new_layers():
    """ON без новых слоёв == легаси-склейка хвоста (аддитивность W2 §4 п.1).

    Порядок tool-phase: база → личность → scoped-просьбы → уроки → сигнал
    речи → план. Он совпадает с порядком слоёв контракта, поэтому Core
    вставляется, ничего не переставляя.
    """
    Stub, D = build_service()
    svc = Stub(StubLLM())
    manifest_system, manifest = await D._compose_speech_system(
        svc, chat_id=12345, writer="tool_phase", run_id="run-1",
        base_prompt="КАНАЛ", base_key="prompts.direct_chat_system_prompt",
        base_default="КАНАЛ", gates=pc.GateState(unified_composer_enabled=True),
        include_mode_block=False, response_plan=PLAN_DETAILED,
        extent_block=_extent.render_extent_block(PLAN_DETAILED),
        identity_text=CHARACTER_BLOCK, style_block=STYLE_DIRECTIVES,
        lessons_block=LESSONS, speech_block=SPEECH)
    legacy = "\n\n".join(p for p in (
        "КАНАЛ", CHARACTER_BLOCK, STYLE_DIRECTIVES, LESSONS, SPEECH,
        _extent.render_extent_block(PLAN_DETAILED),
        psb.speech_base_block()) if p)
    assert manifest_system == legacy
    layers = [t.layer for t in manifest.layers]
    assert list(dict.fromkeys(layers)) == list(pc.LAYER_ORDER)
    # Блоки одного слоя идут подряд (никакого перемешивания уровней).
    for layer in pc.LAYER_ORDER:
        if layer not in layers:
            continue
        first, last = layers.index(layer), len(layers) - layers[::-1].index(layer)
        assert set(layers[first:last]) == {layer}
    rendered = pc.render_effective_layers(manifest)
    assert rendered["order_matches_canonical"] is True
    assert rendered["rendered_layers"][:2] == ["channel_contract", "identity"]


@pytest.mark.asyncio
async def test_tool_phase_on_and_off_scrub_identically_on_longform():
    """W2 §4 (tool-phase): единый проход нормализации применяется к ФИНАЛЬНОЙ
    сборке (ON) — cap-текст вычищен так же, как на OFF-пути.

    Регресс-тест порядка: композер заменяет system целиком, поэтому скраб
    обязан идти ПОСЛЕ сборки, а не по промежуточной строке.
    """
    Stub, D = build_service()
    cap = "Максимум пара язвительных фраз."
    base = f"КАНАЛ.\n\n{cap}\n\nДальше по канону."
    longform = _extent.ResponsePlan(task_kind="explanation",
                                    extent="longform", structure="answer",
                                    delivery_hint="rich")

    svc = Stub(StubLLM())
    composed, manifest = await D._compose_speech_system(
        svc, chat_id=12345, writer="tool_phase", run_id="run-cap",
        base_prompt=base, base_key="prompts.direct_chat_system_prompt",
        base_default=base, gates=pc.GateState(unified_composer_enabled=True),
        include_mode_block=False, response_plan=longform,
        extent_block=_extent.render_extent_block(longform),
        identity_text=CHARACTER_BLOCK)
    assert cap in composed, "подготовка теста: cap-текст должен быть в сборке"
    scrubbed, removed = _extent.scrub_for_plan(composed, longform)
    assert removed >= 1
    assert _extent.scrub_for_plan(scrubbed, longform)[1] == 0  # идемпотентно
    # Тот же (единственный) владелец нормализации и тот же результат на OFF-пути.
    legacy = "\n\n".join(p for p in (
        base, CHARACTER_BLOCK, _extent.render_extent_block(longform),
        psb.speech_base_block()) if p)
    assert _extent.scrub_for_plan(legacy, longform)[1] == removed
    assert scrubbed == _extent.scrub_for_plan(legacy, longform)[0]
    assert pc.get_manifest(12345, run_id="run-cap",
                           writer="tool_phase").manifest_id == \
        manifest.manifest_id


@pytest.mark.asyncio
async def test_l2_on_keeps_block_set_and_applies_designed_order():
    """ON меняет только ПОРЯДОК блоков на L2-пути (порядок = приоритет §3).

    Ни один блок не теряется и не дублируется (включая lessons/speech — пробел,
    из-за которого review-w2 не поймал F2 в этом тесте); extent/plan переезжает
    на своё место после личности и lessons (OFF-порядок — легаси).
    """
    Stub, D = build_service()
    svc = Stub(StubLLM())
    extent = _extent.render_extent_block(PLAN_DETAILED)
    composed, manifest = await D._compose_speech_system(
        svc, chat_id=12345, writer="l2_writer", run_id="run-order",
        base_prompt="КАНАЛ", base_key="prompts.direct_chat_verbalizer_system_prompt",
        base_default="КАНАЛ", include_mode_block=True,
        response_mode=_l1.plan_response_mode(PLAN_DETAILED),
        response_plan=PLAN_DETAILED, extent_block=extent,
        identity_text=CHARACTER_BLOCK, style_block=STYLE_DIRECTIVES,
        lessons_block=LESSONS, speech_block=SPEECH,
        gates=pc.GateState(unified_composer_enabled=True))
    legacy = psb.compose_verbalizer_system(
        "КАНАЛ", _l1.plan_response_mode(PLAN_DETAILED), "plain",
        html_safe=True, character_block=CHARACTER_BLOCK,
        style_directives=STYLE_DIRECTIVES, extent_block=extent)
    assert sorted(composed.split("\n\n")) == sorted(
        (legacy + "\n\n" + LESSONS + "\n\n" + SPEECH + "\n\n"
         + psb.speech_base_block()).split("\n\n"))
    for block in (CHARACTER_BLOCK, STYLE_DIRECTIVES, LESSONS, SPEECH, extent):
        assert composed.count(block) == 1, block
    assert composed.index(CHARACTER_BLOCK) < composed.index(extent)
    assert composed.index(STYLE_DIRECTIVES) < composed.index(extent)
    assert [t.layer for t in manifest.layers
            if t.rendered][:3] == ["channel_contract", "identity",
                                   "context_lessons"]



@pytest.mark.asyncio
async def test_l2_on_without_plan_keeps_mode_block():
    """ON + plan=None: legacy MODE-блок НЕ теряется (блок в блок как на OFF).

    Самая частая legacy-ветка (нет ResponsePlan) обязана собираться ровно
    так же, как `compose_verbalizer_system`, — с точностью до отсутствия
    новых слоёв.
    """
    Stub, D = build_service()
    svc = Stub(StubLLM())
    composed, manifest = await D._compose_speech_system(
        svc, chat_id=12345, writer="l2_writer", run_id="run-mode",
        base_prompt="КАНАЛ",
        base_key="prompts.direct_chat_verbalizer_system_prompt",
        base_default="КАНАЛ", include_mode_block=True, response_mode="casual",
        response_plan=None, extent_block="", identity_text=CHARACTER_BLOCK,
        gates=pc.GateState(unified_composer_enabled=True))
    legacy = psb.compose_verbalizer_system(
        "КАНАЛ", "casual", "plain", html_safe=True,
        character_block=CHARACTER_BLOCK)
    assert composed == legacy + "\n\n" + psb.speech_base_block()
    mode_trace = [t for t in manifest.layers
                  if t.block_id == "mode_block"][0]
    assert mode_trace.rendered is True
    assert mode_trace.owner == "legacy_canon"
    assert mode_trace.layer == "channel_contract"


@pytest.mark.asyncio
async def test_p3_modes_off_parity_when_stage2_scrub_unified(monkeypatch):
    """W2 §4 «доп.»: Stage-2 больше не гейтит scrub режимами (единое решение).

    Реальный путь: `_synthesize_direct_answer` при выключенном
    `SMART_VERBALIZER_MODES_ENABLED` (композер OFF, код-дефолт). База — PREV-
    канон 10.23 с legacy cap-текстом; скраб владельца (`response_extent`)
    вычищает его из ФИНАЛЬНОЙ сборки, счётчик — точный (не `>= 0`).
    """
    from config.settings import settings
    from services.chat_prompts import PREV_CHAT_VERBALIZER_R1023
    monkeypatch.setattr(type(settings), "SMART_VERBALIZER_MODES_ENABLED", False)
    Stub, D = build_service()
    llm = StubLLM()
    raw = type("R", (), {"tool_context": "tool output", "tool_trace": [
        {"tool": "execute_web_search", "out_chars": 812}]})()
    await D._synthesize_direct_answer(
        Stub(llm), 12345, "почему упал сервис", raw, 0.7,
        character_block=CHARACTER_BLOCK, style_directives=STYLE_DIRECTIVES,
        plan=PLAN_DETAILED)
    steps = {c["step"]: c["messages"] for c in llm.captured}
    assert "stage1" in steps and "stage2" in steps, "Stage-2 не вызвался"
    cap_phrase = "Коротко: одно-два предложения"
    assert cap_phrase in PREV_CHAT_VERBALIZER_R1023, \
        "подготовка теста: PREV-канон обязан нести legacy cap-текст"
    expected, removed = _extent.scrub_for_plan(PREV_CHAT_VERBALIZER_R1023,
                                               PLAN_DETAILED)
    assert removed == 1, "владелец скраба убрал не ровно одну cap-фразу"
    assert steps["stage2"][0]["content"] == expected
    assert cap_phrase not in steps["stage2"][0]["content"]
    # Режимы OFF, композер OFF → композер в этом кейсе не участвует вовсе.
    assert pc.get_manifest(12345) is None


@pytest.mark.asyncio
async def test_stage2_modes_off_with_composer_on_single_scrub_pass(monkeypatch):
    """Интеграционный кейс review-w2 F3: Stage-2 при режимах OFF и ON-композере.

    ON → базу (PREV-канон, всё ещё содержащий cap-текст) рендерит композер
    слоем `channel_contract`; нормализация остаётся ОДНИМ проходом владельца
    (`response_extent`) на финальной сборке — ни второго владельца, ни
    потерянной причины `verbilizer_modes_disabled`.
    """
    from config.settings import settings
    from services.chat_prompts import PREV_CHAT_VERBALIZER_R1023
    composer_on(monkeypatch)
    monkeypatch.setattr(type(settings), "SMART_VERBALIZER_MODES_ENABLED", False)
    Stub, D = build_service()
    llm = StubLLM()
    raw = type("R", (), {"tool_context": "tool output", "tool_trace": [
        {"tool": "execute_web_search", "out_chars": 812}]})()
    await D._synthesize_direct_answer(
        Stub(llm), 12345, "почему упал сервис", raw, 0.7,
        correlation_id="run-s2-on", character_block=CHARACTER_BLOCK,
        plan=PLAN_DETAILED)
    steps = {c["step"]: c["messages"] for c in llm.captured}
    system = steps["stage2"][0]["content"]
    manifest = pc.get_manifest(12345, run_id="run-s2-on",
                               writer="system2_stage2")
    assert manifest is not None, "ON-композер не собрал Stage-2"
    # Композер отдал сборку с cap-текстом; скраб — ровно один проход после неё.
    expected, removed = _extent.scrub_for_plan(manifest.system, PLAN_DETAILED)
    assert removed == 1
    assert system == expected and system != manifest.system
    assert _extent.scrub_for_plan(system, PLAN_DETAILED)[1] == 0
    base_trace = [t for t in manifest.layers
                  if t.layer == "channel_contract"][0]
    assert base_trace.rendered is True
    assert base_trace.source == "legacy_mode"
    assert base_trace.chars == len(PREV_CHAT_VERBALIZER_R1023)
    assert manifest.flags["smart_verbalizer_modes_enabled"] is False
    assert CORE_ON in system          # Core инъектируется и на этом пути


@pytest.mark.asyncio
async def test_l2_on_has_single_copy_of_speech_and_lessons_in_payload(
        monkeypatch):
    """F2 (review-w2): speech/lessons — РОВНО одна копия на payload (ON).

    Реальный `_l2_write_answer` с композером ON: блоки рендерит композер
    (слой `context_lessons`, system), в user-часть они не дублируются.
    Проверяется ВЕСЬ payload (system + user): до фикса маркеры встречались
    дважды (×1 system + ×1 user) на одном ходу.
    """
    composer_on(monkeypatch)
    Stub, D = build_service()
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "почему упал сервис", temperature=0.7,
        correlation_id="run-dup", character_block=CHARACTER_BLOCK,
        style_directives=STYLE_DIRECTIVES, response_plan=PLAN_DETAILED,
        plan_block="<Plan>extent=detailed</Plan>",
        user_blocks=[CONTEXT_BLOCK], time_line=TIME_LINE,
        evidence="[tool: execute_web_search out_chars=812]",
        lessons_block=LESSONS, speech_block=SPEECH, max_tokens=4096)
    cap = llm.captured[-1]["messages"]
    system, user = cap[0]["content"], cap[1]["content"]
    payload = system + "\n\n" + user
    for marker in (SPEECH, LESSONS):
        assert payload.count(marker) == 1, (
            f"{marker}: в payload {payload.count(marker)} копий")
        assert system.count(marker) == 1, "владелец блока — композер (system)"
        assert marker not in user, "user-часть не дублирует слой композера"
    manifest = pc.get_manifest(12345, run_id="run-dup", writer="l2_writer")
    assert manifest is not None
    rendered_ids = {t.block_id for t in manifest.layers if t.rendered}
    assert {"speech_understanding", "verified_lessons"} <= rendered_ids
    assert manifest.system.count(SPEECH) == 1
    assert manifest.system.count(LESSONS) == 1
    # Защищённая user-часть хода (инструкция/контекст/evidence) не потеряна.
    for kept in (TIME_LINE, "<Plan>extent=detailed</Plan>", CONTEXT_BLOCK):
        assert user.count(kept) == 1, kept
    assert user.count("<Tool_Evidence>") == 1
    # Ход без прочих user-блоков не теряет вопрос: единственная копия
    # speech/lessons живёт в system, вопрос едет как раньше.
    llm2 = StubLLM()
    await D._l2_write_answer(
        Stub(llm2), 12346, "второй вопрос", temperature=0.7,
        correlation_id="run-dup-2", lessons_block=LESSONS,
        speech_block=SPEECH)
    cap2 = llm2.captured[-1]["messages"]
    assert cap2[1]["content"] == "второй вопрос"
    assert cap2[0]["content"].count(SPEECH) == 1
    assert cap2[0]["content"].count(LESSONS) == 1

