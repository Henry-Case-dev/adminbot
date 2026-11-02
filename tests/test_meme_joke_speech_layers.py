"""MEME-JOKE-SPEECH — этап B мемов как авторская речь одного композера.

Контракт (`plans/features/meme-pipeline-refactor-01/arch/joke-speech-layers.md`
§3–§6, дословный источник `plans/owner_inputs/2026-11-03-meme-joke-speech-layers.md`):

* system этапа B собирает ЕДИНЫЙ владелец речи
  (`prompt_composer.compose_speech_system`); редактируемый промпт прикола +
  J-директива — задание (`channel_contract`), а не замена личности;
* наследуются Personality Core, Identity/SelfModel, Expression («Речь и
  характер»), `Speech_Base` (базовая речь + HUMOR_TEXT), Humor Craft (при
  включённой оси), few-shot и Style Policy;
* ровно один LLM-вызов на этап B (всего два на попытку: выжимка + прикол) и
  ноль вызовов внутри композера;
* приём Humor Craft — детерминированная ротация по `job_id` среди техник,
  включённых ВЛАДЕЛЬЦЕМ (`humor.craft`), а не один захардкоженный;
* выжимка остаётся аналитической: она едет только user-сообщением;
* диагностика журнала (`facts.joke.speech`) описывает ФАКТИЧЕСКИЙ payload:
  тот же `system_sha12`, что у сообщений, отданных в `generate`, и тот же
  набор слоёв/ревизий, что в манифесте.

TEST-LIFECYCLE: CONTRACT owner=MEME-JOKE-SPEECH (meme-pipeline-refactor-01)
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import bot_persona
from services import chat_params
from services import hot_config
from services import mca_expression
from services import mca_humor_craft as craft
from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import prompt_composer as pc
from services import prompt_registry as pr
from services import style_policy as sp

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
CHAT = -4242
JOB_ID = "meme-job-speech-1"
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}

CORE_TEXT = "ЯДРО_ХАРАКТЕРА_МЕМА: язвительный наблюдатель чата."
PERSONA = "<Persona>\nИмя: Бот. Характер: язвительный наблюдатель.\n</Persona>"
EXPRESSION_NOTE = "ЗАМЕТКА_ВЫРАЖЕНИЯ_МЕМА"
STYLE_PRESET = ("no_quotes",)
SUMMARY_TEXT = "ВЫЖИМКА-МАРКЕР: чат спорит про чайник"
JOKE_TEXT = "прикол-маркер"


# ── фикстуры и фейки (сеть, БД и Telegram не используются) ──────────────────

@pytest.fixture(autouse=True)
def _clean_state():
    meme.reset_process_attempts()
    pr.reset_cache()
    pc.reset_state()
    yield
    meme.reset_process_attempts()
    pr.reset_cache()
    pc.reset_state()
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParams:
    def __init__(self, by_chat=None):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


async def _persona_ctx(chat_id):
    return SimpleNamespace(persona=object(), traits=())


def _configure(monkeypatch, *, core_enabled=True, humor_enabled=True,
               expression_enabled=True, disabled_techniques=(),
               joke_prompt=None):
    """Живые оси владельца для этапа B (те же ключи, что в проде)."""
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    if humor_enabled:
        monkeypatch.setenv("HUMOR_CRAFT_ENABLED", "1")
    values = {
        "flags.unified_composer_enabled": True,
        "flags.character_core_enabled": core_enabled,
        "flags.speech_style_policy_enabled": True,
        "flags.humor_craft_enabled": humor_enabled,
        "flags.persona_enabled": True,
        "character.core": {"revision": 21, "enabled": True,
                           "full_text": CORE_TEXT, "compact_text": CORE_TEXT},
        "character.expression": {"enabled": expression_enabled,
                                 "note": EXPRESSION_NOTE},
        "style.policy": sp.build_document(presets=STYLE_PRESET, revision=5,
                                          owner=1, reason="test"),
        "humor.craft": {"enabled": True, "revision": 7,
                        "disabled_techniques": list(disabled_techniques)},
    }
    if joke_prompt is not None:
        values[meme.prompt_setting_key(meme.JOKE_PROMPT_BLOCK_ID)] = joke_prompt
    hot_config.set_config_cache(_FakeHot(values))
    chat_params.set_chat_params_cache(_FakeChatParams({CHAT: {}}))
    # Личность берётся тем же резолвом, что у Direct-хода: подменяем только
    # источники персоны (БД в тесте нет) — сам блок собирается штатно.
    monkeypatch.setattr(bot_persona, "resolve_character_context", _persona_ctx)
    monkeypatch.setattr(bot_persona, "build_persona_prompt_block",
                        lambda *a, **kw: PERSONA)


class _SpeechLLM:
    """Считает ВСЕ вызовы модели: (kwargs, messages) на каждый."""

    def __init__(self, *, summary=SUMMARY_TEXT, joke=JOKE_TEXT):
        self.summary = summary
        self.joke = joke
        self.calls: list[tuple] = []

    async def generate(self, messages, **kwargs):
        self.calls.append((dict(kwargs), [dict(m) for m in messages]))
        return self.joke if kwargs.get("step") == "meme_joke" else self.summary

    def steps(self) -> list[str]:
        return [str(kwargs.get("step") or "") for kwargs, _m in self.calls]

    def messages_for(self, step: str) -> list[dict]:
        for kwargs, messages in self.calls:
            if kwargs.get("step") == step:
                return messages
        raise AssertionError(f"нет LLM-вызова step={step}: {self.steps()}")


class _Hit:
    async def draw_probability(self, **kwargs):
        return mrs.DrawResult(value=0.0, deferred=False, fallback_reason=None,
                              source="pseudorandom", selected_source="quantum",
                              draw_id="draw-1")


class _Provider:
    def __init__(self):
        self.calls: list[tuple] = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=True, called=True, reason="", content=b"png")


async def _ok_gate(_chat_id):
    return True, "ok"


async def _sender(_chat_id, _content, _prompt):
    return None


def _settings() -> meme.MemeSettings:
    return meme.MemeSettings(enabled=True, window_messages=50, daily_limit=3,
                             cooldown_seconds=0, min_messages=1,
                             trigger_probability=1.0)


def _rows(chat_id: int, n: int = 5) -> list[dict]:
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


def _ledger(tmp_path):
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme_joke_speech.db"))
    led.apply_schema()
    return led


def _run(tmp_path, *, job_id=JOB_ID, llm=None):
    """Боевой путь этапов A и B: ни суммаризатор, ни `joke_generator` не
    инжектируются — оба шага идут через клиент модели (счётчик вызовов)."""
    llm = llm if llm is not None else _SpeechLLM()
    led = _ledger(tmp_path)

    result = asyncio.run(meme.consider_chat(
        None, CHAT, settings=_settings(), ledger=led, now=NOW,
        tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=lambda: True, image_status=IMAGE_OK,
        random_source=_Hit(), messages=_rows(CHAT), llm=llm,
        image_provider=_Provider(), publish_gate=_ok_gate, sender=_sender,
        model_chars=400, job_id=job_id))
    return result, llm, led


def _joke_facts(led) -> dict:
    """Факты прикола из САМОГО свежего `joke`-ряда журнала (как витрина)."""
    for row in led.attempts(CHAT):
        if str(row.get("stage") or "") != meme.STAGE_JOKE:
            continue
        facts = meme.parse_attempt_facts(row)
        assert facts, "журнал этапа B пуст"
        return facts
    raise AssertionError("в журнале нет строки этапа joke")


def _payload(llm: _SpeechLLM) -> tuple[str, str]:
    messages = llm.messages_for("meme_joke")
    return messages[0]["content"], messages[1]["content"]


# ── 1. Реальный payload этапа B: наследованные слои и ревизии ────────────────

def test_joke_payload_inherits_speech_layers(tmp_path, monkeypatch):
    """System прикола = задание + Core/Identity/Expression/речь/юмор/стиль.

    Мутация: вернуть `messages=[{"system": instruction}]` (прежний этап B) или
    собрать второй композер — тест падает на отсутствии слоёв/ревизий.
    """
    _configure(monkeypatch)
    _result, llm, led = _run(tmp_path)
    facts = _joke_facts(led)
    speech = facts["speech"]

    assert llm.steps() == ["meme_summary", "meme_joke"]
    system, user = _payload(llm)

    # 1) задание и J-директива на месте (не вытеснены речевыми слоями)
    assert system.startswith(meme.MEME_JOKE_PROMPT)
    assert f"не более {facts['limit']} символов" in system
    assert facts["limit"] == 400 - facts["template_chars"]
    assert facts["template_chars"] >= len(meme.MEME_IMAGE_PROMPT)
    # 2) личность, характер, «Речь и характер», базовая речь, юмор и стиль
    assert CORE_TEXT in system
    assert PERSONA in system
    assert EXPRESSION_NOTE in system
    assert "<Speech_Base>" in system
    assert mca_expression.HUMOR_TEXT in system
    policy = asyncio.run(sp.resolve_style_policy_ref(CHAT))
    assert policy.hint and policy.hint in system
    # 3) выжимка — только user-сообщение (аналитическая часть не в system)
    assert user == SUMMARY_TEXT
    assert SUMMARY_TEXT not in system
    assert CORE_TEXT not in user and mca_expression.HUMOR_TEXT not in user

    assert speech["composer"] == "on"
    assert facts["chars"] == len(JOKE_TEXT)          # прежние ключи целы

    # 4) приём Humor Craft рендерится и совпадает с журналом
    technique = speech["technique"]
    assert technique in craft.TECHNIQUES
    assert speech["humor_status"] == "rendered"
    assert craft.technique_text(technique) in system
    assert speech["humor"] == pc.sha12(craft.render_layer(technique))

    # 5) диагностика = фактически использованные ревизии
    expected_core = pc.get_manifest(CHAT, run_id=JOB_ID, writer="meme_joke")
    assert expected_core is not None
    assert speech["manifest"] == expected_core.manifest_id
    assert speech["core"] == expected_core.versions["core"]
    assert speech["core"].startswith("r21.")          # чатовая редакция Core
    assert speech["identity"] == expected_core.versions["identity"]
    assert speech["expression"] == expected_core.versions["expression"]
    assert speech["style_policy"] == expected_core.versions["style_policy"]
    assert speech["core_detail"].startswith("compact:")
    assert speech["off_axes"] == [
        name for name, value in sorted(expected_core.flags.items())
        if not value]

    # 6) слои/пропуски журнала = манифест композера, причины из SKIP_REASONS
    assert speech["layers"] == [
        {"layer": t.layer, "block": t.block_id, "revision": t.revision,
         "chars": t.chars, "rendered": t.rendered, "skip": t.skip_reason}
        for t in expected_core.layers]
    assert speech["skipped"] and "humor_craft" not in speech["skipped"]
    skipped_traces = [t for t in expected_core.layers
                      if t.skip_reason and not t.rendered]
    assert set(speech["skipped"]) == {t.layer for t in skipped_traces}
    for trace in skipped_traces:
        # у слоя может быть несколько блоков: причины перечислены через "|"
        assert trace.skip_reason in speech["skipped"][trace.layer].split("|")
    for reason_codes in speech["skipped"].values():
        for reason in reason_codes.split("|"):
            assert reason in pc.SKIP_REASONS
    blocks = {(row["layer"], row["block"]) for row in speech["layers"]}
    assert ("channel_contract", "channel_canon") in blocks
    assert ("channel_contract", "speech_base") in blocks
    assert ("core", "core") in blocks
    assert ("identity", "identity") in blocks
    assert ("expression", "expression") in blocks
    assert ("humor_craft", "humor_craft") in blocks
    assert ("style_policy_hint", "style_policy_hint") in blocks

    # 7) связь журнала с РЕАЛЬНЫМ payload (не с пересборкой)
    assert speech["system_sha12"] == hashlib.sha256(
        system.encode("utf-8")).hexdigest()[:12]
    rendered = {t.layer for t in expected_core.layers if t.rendered}
    assert {"core", "identity", "expression", "humor_craft",
            "style_policy_hint"} <= rendered


def test_analytics_snapshot_exposes_last_joke(tmp_path, monkeypatch):
    """Витрина видит тот же `speech` (аддитивный `last_joke`, без текстов)."""
    _configure(monkeypatch)
    _result, llm, led = _run(tmp_path)
    snapshot = meme.analytics_snapshot(led, chat_id=CHAT, day=None)
    last = snapshot["last_joke"]
    assert last["speech"]["system_sha12"] == _joke_facts(led)["speech"][
        "system_sha12"]
    assert last["speech"]["layers"]
    assert JOKE_TEXT not in str(snapshot)            # текста прикола наружу нет


# ── 2. Ровно один вызов на этап B; композер LLM не вызывает ─────────────────

def test_joke_step_is_one_call_and_composer_calls_no_llm(tmp_path,
                                                         monkeypatch):
    _configure(monkeypatch)
    _result, llm, led = _run(tmp_path)
    assert llm.steps() == ["meme_summary", "meme_joke"]
    assert llm.steps().count("meme_joke") == 1
    assert len(llm.calls) == 2

    facts = _joke_facts(led)
    technique = facts["speech"]["technique"]
    # Контракт ремесла: слой приёма не тратит LLM-вызовов вовсе.
    assert craft.layer_calls(technique) == 0

    # Прямая проверка композера: тот же вход, счётчик вызовов не растёт.
    before = len(llm.calls)

    async def _compose():
        gates = await pc.resolve_gates(CHAT)
        return await pc.compose_speech_system(
            chat_id=CHAT, writer=meme.JOKE_SPEECH_WRITER, run_id="probe-run",
            channel="plain", html_safe=False,
            base_prompt=meme.joke_instruction(meme.MEME_JOKE_PROMPT, 400),
            base_source="default", include_mode_block=False,
            profile=pc.PROFILE_SPEECH_PLAIN, gates=gates,
            include_speech_base=True, extent_block="",
            plan_skip=meme.JOKE_PLAN_SKIP,
            response_plan=meme.JokeAdvice(comic_strategy=technique),
            identity_text=PERSONA, identity_source="chat",
            identity_skipped="", style_skip="style_requests_absent",
            lessons_skip="lessons_absent", speech_skip="speech_absent",
            context_text=SUMMARY_TEXT, user_parts=(SUMMARY_TEXT,))

    system, manifest = asyncio.run(_compose())
    assert manifest is not None and system
    assert len(llm.calls) == before


# ── 3. Humor Craft: ротация среди ВКЛЮЧЁННЫХ владельцем техник ──────────────

def _rotation(job_ids) -> list[str]:
    async def _inner():
        gates = await pc.resolve_gates(CHAT)
        return [await meme.joke_technique(CHAT, job_id, gates=gates)
                for job_id in job_ids]

    return asyncio.run(_inner())


def test_technique_rotation_stays_within_owner_enabled(monkeypatch):
    """Выключенные техники не выбираются; разные `job_id` дают разные приёмы.

    Мутация: захардкодить один приём (прямой запрет владельца) — падает на
    «больше одной техники»; игнорировать `humor.craft` — падает на выключенных.
    """
    disabled = ("deadpan", "literalism")
    _configure(monkeypatch, disabled_techniques=disabled)
    enabled = [name for name in craft.TECHNIQUES if name not in disabled]
    job_ids = [f"meme:{CHAT}:2026-11-03:{index:03d}" for index in range(60)]
    chosen = _rotation(job_ids)
    assert all(name in enabled for name in chosen)
    assert not (set(chosen) & set(disabled))
    assert len(set(chosen)) > 1                       # не один приём
    # Детерминизм: тот же job_id → тот же приём (нет случайности/LLM).
    assert _rotation(job_ids[:5]) == chosen[:5]

    # Владелец оставил одну технику — ротируется только она.
    _configure(monkeypatch, disabled_techniques=("absurd_escalation",
                                                 "deadpan", "literalism",
                                                 "unexpected_analogy"))
    assert set(_rotation(job_ids)) == {"bureaucratic_logic"}


def test_journalled_technique_matches_rotation_and_payload(tmp_path,
                                                           monkeypatch):
    """Журнал/манифест/приём — из одной ротации, а не из второй копии."""
    _configure(monkeypatch, disabled_techniques=("deadpan",))
    _result, llm, led = _run(tmp_path, job_id="meme:fixed-job-7")
    system, _user = _payload(llm)
    speech = _joke_facts(led)["speech"]
    expected = _rotation(["meme:fixed-job-7"])[0]
    assert speech["technique"] == expected
    assert expected != "deadpan"
    assert craft.technique_text(expected) in system


# ── 4. Выключенная ось = слоя нет, причина видна в `speech.skipped` ────────

@pytest.mark.parametrize("axis", ["core", "expression", "humor"])
def test_disabled_axis_removes_layer_and_names_reason(tmp_path, monkeypatch,
                                                      axis):
    if axis == "core":
        _configure(monkeypatch, core_enabled=False)
    elif axis == "expression":
        _configure(monkeypatch, expression_enabled=False)
    else:
        _configure(monkeypatch, humor_enabled=False)
    _result, llm, led = _run(tmp_path)
    system, _user = _payload(llm)
    speech = _joke_facts(led)["speech"]
    assert speech["composer"] == "on"

    if axis == "core":
        assert speech["skipped"]["core"] == "core_disabled"
        assert CORE_TEXT not in system
        assert PERSONA in system                     # личность не задета
    elif axis == "expression":
        assert speech["skipped"]["expression"] == "expression_disabled"
        assert EXPRESSION_NOTE not in system
        assert CORE_TEXT in system
    else:
        assert speech["skipped"]["humor_craft"] == "humor_disabled"
        assert speech["technique"] == ""
        assert speech["humor_status"] == "skip:humor_disabled"
        for name in craft.TECHNIQUES:
            assert craft.technique_text(name) not in system
        assert CORE_TEXT in system                   # Core живёт без ремесла
    # задание и базовые речевые слои остаются во всех трёх случаях
    assert system.startswith(meme.MEME_JOKE_PROMPT)
    assert "<Speech_Base>" in system


# ── 5. Редактируемый промпт = задание, а не замена личности ────────────────

def test_edited_joke_prompt_is_task_not_persona(tmp_path, monkeypatch):
    edited = "СОЧИНИ_ПРИКОЛ_ПО_РЕДАКТИРУЕМОМУ_ШАБЛОНУ"
    _configure(monkeypatch, joke_prompt=edited)
    _result, llm, led = _run(tmp_path)
    system, user = _payload(llm)
    facts = _joke_facts(led)
    assert facts["source"] == "global"                # правка из админки
    assert system.startswith(edited)
    assert f"не более {facts['limit']} символов" in system
    # Личность/характер/выражение/юмор заданием не вытеснены.
    assert CORE_TEXT in system and PERSONA in system
    assert EXPRESSION_NOTE in system and mca_expression.HUMOR_TEXT in system
    assert facts["speech"]["humor_status"] == "rendered"
    assert user == SUMMARY_TEXT
