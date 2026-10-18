"""SOUL-1 / W4 — SOUL-08: Humor Feedback Loop внутри существующего Experience.

Покрытие (requirements-map.json W4):
  * SOUL-08.0/08.1 — отдельного контура самообучения нет: эпизоды/feedback/
    уроки/применения — те же таблицы `mca_*` (v28) и тот же review-джоб;
  * SOUL-08.2 — bounded-метаданные отправки (без сырых текстов/секретов);
  * SOUL-08.3–08.7 — классы сигналов, семантическая классификация, unknown
    вместо failure, отсутствие связи ≠ успех;
  * SOUL-08.8 — классификация семантическая, evidence links, confidence,
    bounded batch; недоступность оценщика НЕ блокирует беседу;
  * SOUL-08.9 — консервативные обновления: малый N, один пользователь,
    бригандинг, обратная причинность, engagement-gaming; per-chat изоляция;
  * SOUL-08.10/08.11 — измеримый эффект на СЛЕДУЮЩИЙ ответ, decay, pause/
    reset/rollback, никакой автопереписи Core;
  * SOUL-08.12 — семь обязательных сценариев (детерминированные симуляции с
    честным live-маркером).

TEST-LIFECYCLE: CONTRACT owner=soul-1/W4
"""
import json
import time

import pytest
import pytest_asyncio

from services import mca_humor_feedback as hf
from services import mca_gates
from services.database import DatabaseService

#: Сценарии окна живут в реальном времени: отправка «сейчас», ответы — внутри
#: окна (иначе bounded-lookback отсечёт отправку как устаревшую).
NOW = int(time.time())


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "w4-feedback.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _feedback_gate(monkeypatch):
    """Прямые вызовы контура: ось ON (паритет OFF проверяется отдельно)."""
    monkeypatch.setenv("HUMOR_FEEDBACK_ENABLED", "1")
    yield


class _Catalog:
    def get(self, key, default=None):
        return True


async def _enable_catalog(monkeypatch, hot_config):
    monkeypatch.setenv("HUMOR_FEEDBACK_ENABLED", "1")
    hot_config.set_config_cache(_Catalog())


def _obs(**overrides) -> hf.Observation:
    base = dict(chat_id=-100, technique="deadpan", signal="explicit_approval",
                ts=200, send_ts=100, send_message_id=11, user_id=1,
                topic="topic_a", confidence="medium", episode_id="ep-1",
                authority_is_owner=False, reactions_distinct=1)
    base.update(overrides)
    return hf.Observation(**base)


async def _msg(db, *, chat_id=-100, user_id=1, text="ага", ts=NOW + 20,
               reply_to_id=11, msg_id=None) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, 'text', 'u', 0, ?)",
        (user_id, chat_id, text, reply_to_id, int(ts), msg_id))
    await db.db.commit()
    return 1


async def _send(db, *, chat_id=-100, message_id=11, ts=NOW,
                technique="deadpan", trace_id="run-s1") -> dict:
    return await hf.capture_send(
        db, chat_id=chat_id, message_id=message_id, reply_to_message_id=99,
        trace_id=trace_id, strategy=technique, technique=technique,
        core_revision="abc123def456", model="test-model", channel="plain",
        delivered=True, ts=ts)


class _VerdictLLM:
    """Заглушка оценщика: отдаёт заданный JSON (bounded, один вызов)."""

    def __init__(self, verdicts):
        self.calls = 0
        self.verdicts = verdicts

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return json.dumps(self.verdicts, ensure_ascii=False)


# ═══ SOUL-08.2: bounded-метаданные ═════════════════════════════════════════

def test_send_metadata_is_bounded_and_typed():
    # FIX-W4 (REVIEW-W4 §6.1, мутация M11): состав закрытого набора
    # ЗАПИНОВАН — расширение SEND_FIELDS не должно проходить незамеченным
    # (прежняя проверка была самоссылочной: `<= set(hf.SEND_FIELDS)`).
    assert hf.SEND_FIELDS == (
        "chat_id", "message_id", "reply_to_message_id", "thread_id",
        "core_revision", "model", "strategy", "technique", "few_shot_refs",
        "channel", "delivered", "trace_id", "ts")
    meta = hf.bounded_send_metadata(
        chat_id=-100, message_id=55, reply_to_message_id=54,
        strategy="deadpan", technique="deadpan", channel="plain",
        delivered=True, model="m", core_revision="rev123",
        few_shot_refs=["sample:1", "sample:2", "sample:3", "sample:4"],
        trace_id="run-1",
        # мусор/секреты не попадают вовсе
        system_prompt="СЕКРЕТНЫЙ ПРОМПТ", user_text="сырой текст")
    assert set(meta) <= set(hf.SEND_FIELDS)
    assert set(meta) == {
        "chat_id", "message_id", "reply_to_message_id", "strategy",
        "technique", "channel", "delivered", "model", "core_revision",
        "few_shot_refs", "trace_id"}
    assert meta["message_id"] == 55 and meta["delivered"] is True
    assert len(meta["few_shot_refs"]) == 3
    assert "system_prompt" not in meta and "user_text" not in meta
    # значения — только безопасные токены; НЕИЗВЕСТНЫЕ секрето-подобные имена
    # отбрасываются даже с безопасным значением (C1 / M11 ревьюера: итератор
    # полей расширен секрето-именами; значение выбрано так, чтобы прошло бы
    # `_SAFE_TOKEN`, иначе утечка маскируется самим фильтром)
    dirty = hf.bounded_send_metadata(chat_id=-100, message_id=1,
                                     strategy="bad value с пробелом; drop=1",
                                     api_key="sk_live_abcdef",
                                     secret_prompt="sk_live_abcdef",
                                     raw_text="sk_live_abcdef")
    assert "strategy" not in dirty
    assert "api_key" not in dirty
    assert "secret_prompt" not in dirty and "raw_text" not in dirty


@pytest.mark.asyncio
async def test_capture_send_writes_bounded_episode(db, monkeypatch):
    from services import hot_config
    monkeypatch.delenv("HUMOR_FEEDBACK_ENABLED", raising=False)
    off = await _send(db)
    assert off["captured"] is False
    assert off["reason"] == "humor_feedback_disabled"
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_experience_episodes")
    assert int((await cursor.fetchone())["c"]) == 0

    await _enable_catalog(monkeypatch, hot_config)
    try:
        captured = await _send(db)
        assert captured["captured"] is True, captured
        cursor = await db.db.execute(
            "SELECT task_type, decision_json, output_ref, chat_id "
            "FROM mca_experience_episodes")
        row = await cursor.fetchone()
        decision = json.loads(row["decision_json"])
        assert row["task_type"] == hf.SEND_TASK_TYPE
        assert decision["technique"] == "deadpan"
        assert decision["msg"] == 11
        assert decision["core_revision"] == "abc123def456"
        assert "текст" not in json.dumps(decision)
        assert row["output_ref"].startswith("tgmsg_")
    finally:
        hot_config.set_config_cache(None)


# ═══ SOUL-08.3–08.7: окно и классы сигналов ═══════════════════════════════

def test_window_candidates_enforce_time_and_linkage():
    send = {"chat_id": -100, "message_id": 11, "ts": 100,
            "technique": "deadpan"}
    rows = [
        {"id": 1, "chat_id": -100, "user_id": 1, "text": "ахах",
         "timestamp": 50, "reply_to_id": 11},          # до отправки
        {"id": 2, "chat_id": -100, "user_id": 1, "text": "ахах",
         "timestamp": 100 + hf.WINDOW_SECONDS + 5, "reply_to_id": 11},
        {"id": 3, "chat_id": -100, "user_id": 1, "text": "о чём вообще",
         "timestamp": 150, "reply_to_id": 77},          # не на бота
        {"id": 4, "chat_id": -100, "user_id": 2,
         "text": "перестань это писать, задолбал", "timestamp": 160,
         "reply_to_id": 11},
        {"id": 5, "chat_id": -999, "user_id": 3, "text": "ахах",
         "timestamp": 160, "reply_to_id": 11},          # другой чат
    ]
    candidates, excluded = hf.window_candidates(send=send, rows=rows,
                                                now_ts=300)
    assert [c.message_row_id for c in candidates] == [4]
    reasons = {e.get("row"): e["reason"] for e in excluded}
    assert reasons[1] == "reverse_causality"
    assert reasons[2] == "out_of_window"
    assert reasons[3] == "no_linkage"
    assert reasons[5] == "cross_chat"
    assert candidates[0].markers == ("marker_stop_request",
                                     "marker_irritation")


def test_positive_signal_requires_semantics_or_owner():
    """SOUL-08.8: детерминированных фраз для «успеха» недостаточно."""
    for markers in ((), ("marker_approval",), ("marker_irritation",),
                    ("marker_approval", "marker_irritation")):
        signal = hf.resolve_signal(semantic="unknown", markers=markers,
                                   confidence="low",
                                   authority_is_owner=False)
        assert signal not in hf.POSITIVE_SIGNALS, markers
    assert hf.resolve_signal(semantic="explicit_approval", markers=(),
                             confidence="medium",
                             authority_is_owner=False) == "explicit_approval"
    assert hf.resolve_signal(semantic="unknown",
                             markers=("marker_stop_request",),
                             confidence="low",
                             authority_is_owner=True) == "stop_request"


def test_parse_classification_is_strict():
    observations = [{"text": "a"}, {"text": "b"}]
    assert hf.parse_classification("не json", observations) == []
    parsed = hf.parse_classification(json.dumps([
        {"i": 0, "signal": "metaphor_continuation", "confidence": "high",
         "subject_user_id": 7, "evidence": "развил образ"},
        {"i": 1, "signal": "выдуманный_класс", "confidence": "??"},
    ]), observations)
    assert parsed[0]["signal"] == "metaphor_continuation"
    assert parsed[1]["signal"] == "unknown"
    assert parsed[1]["confidence"] == "low"


# ═══ SOUL-08.9: консервативные обновления и защиты ════════════════════════

def test_small_n_single_user_and_topic_are_guarded():
    one = hf.evaluate_observations([_obs()])
    assert one[0].confirmed is False
    assert "guard_small_n" in one[0].guards
    assert "guard_single_topic" in one[0].guards
    assert "guard_single_user" in one[0].guards
    # один пользователь, разные эпизоды и темы — всё равно не подтверждаем
    same_user = hf.evaluate_observations([
        _obs(episode_id=f"ep-{i}", topic=f"topic_{i}") for i in range(1, 4)])
    assert same_user[0].confirmed is False
    assert "guard_single_user" in same_user[0].guards


def test_brigading_and_engagement_gaming_are_guarded():
    brigading = hf.evaluate_observations([
        _obs(episode_id=f"ep-{i}", topic=f"topic_{i}",
             user_id=10 + i, reactions_distinct=9) for i in range(1, 4)])
    assert brigading[0].confirmed is False
    assert "guard_brigading" in brigading[0].guards
    # вес не растёт от «объёма»: 10 наблюдений в одном эпизоде ≤ 1.0
    gaming = hf.evaluate_observations([
        _obs(episode_id="ep-x", topic=f"topic_{i}", user_id=100 + i)
        for i in range(1, 11)])
    assert gaming[0].weight <= hf.MAX_WEIGHT_PER_SEND


def test_reverse_causality_and_window_are_guarded():
    early = hf.evaluate_observations([
        _obs(ts=50, send_ts=100, episode_id=f"e{i}", topic=f"t{i}",
             user_id=i) for i in range(1, 4)])
    assert early[0].confirmed is False
    assert "guard_reverse_causality" in early[0].guards
    late = hf.evaluate_observations([
        _obs(ts=100 + hf.WINDOW_SECONDS + 10, send_ts=100,
             episode_id=f"l{i}", topic=f"t{i}", user_id=i)
        for i in range(1, 4)])
    assert "guard_out_of_window" in late[0].guards


def test_low_confidence_participant_signals_stay_hypotheses():
    rows = [_obs(episode_id=f"e{i}", topic=f"t{i}", user_id=i,
                 confidence="low") for i in range(1, 4)]
    result = hf.evaluate_observations(rows)
    assert result[0].confirmed is False
    assert "guard_low_confidence" in result[0].guards
    owner = hf.evaluate_observations([
        _obs(signal="stop_request", confidence="low",
             authority_is_owner=True, episode_id="own-1", user_id=1)])
    assert owner[0].confirmed is True and owner[0].direction == "weaken"


def test_unknown_window_is_not_failure():
    assert hf.evaluate_observations([_obs(signal="unknown")]) == []
    assert hf.evaluate_observations([]) == []


def test_decay_fades_preferences():
    assert hf.decay_factor(1000, now_ts=1000) == 1.0
    assert hf.decay_factor(1000, now_ts=1000 + hf.DECAY_DAYS * 86400) == 0.0
    half = hf.decay_factor(1000, now_ts=1000 + (hf.DECAY_DAYS // 2) * 86400)
    assert 0.4 <= half <= 0.6


# ═══ SOUL-08.10/08.11: уроки, эффект на следующий ответ, управление ════════

@pytest.mark.asyncio
async def test_single_explicit_request_applies_immediately(db, monkeypatch):
    """Явная просьба владельца — инструкция: применяется с одного наблюдения.

    Статистика (малый N, один пользователь) касается ВЫВОДОВ по реакциям, а
    не прямого указания; урок всё равно контекстный, обратимый и не трогает
    Core (SOUL-08.10/08.11).
    """
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        single = hf.evaluate_observations([
            _obs(signal="stop_request", authority_is_owner=True,
                 confidence="high", episode_id="one-1", topic="t-one",
                 user_id=1)])
        assert single[0].confirmed is True
        assert single[0].explicit is True
        assert single[0].reason == "explicit_instruction"
        applied = await hf.apply_hypothesis(db, single[0],
                                            episode_ids=single[0].evidence)
        assert applied["applied"] is True, applied
        assert await hf.strategy_weight(db, -100, "deadpan") <= 0.2
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_weaken_lesson_changes_next_answer_selection(db, monkeypatch):
    """Измеримый эффект: ослабленный приём НЕ попадает в следующую сборку."""
    from services import hot_config
    from services import prompt_composer as pc
    from services import mca_humor_craft as hc

    await _enable_catalog(monkeypatch, hot_config)
    try:
        owner_obs = [
            _obs(signal="stop_request", authority_is_owner=True,
                 confidence="high", episode_id=f"own-{i}", topic=f"t{i}",
                 user_id=1, technique="bureaucratic_logic")
            for i in range(1, 4)]
        hypothesis = hf.evaluate_observations(owner_obs)[0]
        assert hypothesis.confirmed is True
        applied = await hf.apply_hypothesis(db, hypothesis,
                                            episode_ids=hypothesis.evidence)
        assert applied["applied"] is True, applied

        weight = await hf.strategy_weight(db, -100, "bureaucratic_logic")
        assert weight <= hf.WEAKEN_WEIGHT + 0.05, weight
        other = await hf.strategy_weight(db, -100, "deadpan")
        assert other == 1.0
        # другой чат не затронут (per-chat изоляция)
        assert await hf.strategy_weight(db, -200, "bureaucratic_logic") == 1.0

        decision = hc.select_technique(comic_strategy="bureaucratic_logic",
                                       context_weight=weight)
        assert decision.technique == "" and decision.reason == \
            "humor_context_penalty"
        manifest = pc.compose_prompt(pc.PromptPlan(
            profile="speech_plain", writer="l2_writer", chat_id=-100,
            base_prompt="БАЗА", response_plan=pc.PlanRef(
                extent="detailed", structure="answer",
                comic_strategy="bureaucratic_logic"),
            humor=hc.HumorStrategy(skip_reason=decision.reason,
                                   enabled=False),
            gates=pc.GateState(unified_composer_enabled=True,
                               humor_craft_enabled=True)))
        layer = [t for t in manifest.layers if t.layer == "humor_craft"][0]
        assert layer.rendered is False
        assert layer.skip_reason == "humor_context_penalty"
        # штраф для отбора примеров тоже виден
        penalties = await hf.sample_penalties(db, -100)
        assert penalties.get("technique:bureaucratic_logic", 0) > 0
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_lessons_never_rewrite_core(db, monkeypatch):
    """Никакой автоматической переписи Core (SOUL-08.9/§7.1 уточнения)."""
    from services import hot_config

    class _DocCache(_Catalog):
        def __init__(self):
            self.docs = {"character.core": {
                "revision": 1, "enabled": True,
                "full_text": "ИСХОДНЫЙ ХАРАКТЕР ВЛАДЕЛЬЦА"}}
            self.writes: list = []

        def get(self, key, default=None):
            if str(key).startswith("flags."):
                return True        # оси фич включены; документ Core — отдельно
            return self.docs.get(key, default)

        def set(self, key, value, **kwargs):
            self.writes.append(key)

        def set_many(self, items):
            self.writes.append("set_many")

    cache = _DocCache()
    monkeypatch.setenv("HUMOR_FEEDBACK_ENABLED", "1")
    hot_config.set_config_cache(cache)
    try:
        hypothesis = hf.evaluate_observations([
            _obs(signal="stop_request", authority_is_owner=True,
                 confidence="high", episode_id=f"core-{i}", topic=f"t{i}",
                 user_id=1) for i in range(1, 4)])[0]
        result = await hf.apply_hypothesis(db, hypothesis,
                                           episode_ids=hypothesis.evidence)
        assert result["applied"] is True
        assert cache.writes == []                       # Core не тронут
        assert cache.docs["character.core"]["full_text"] == \
            "ИСХОДНЫЙ ХАРАКТЕР ВЛАДЕЛЬЦА"
        assert cache.docs["character.core"]["revision"] == 1
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_owner_controls_pause_and_reset_keep_data(db, monkeypatch):
    import sqlite3
    import sys
    from pathlib import Path

    from services import chat_params, hot_config

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_p0_persistfix_speech_chat_scope import (  # noqa: E402
        SqlitePg,
        create_schema,
        seed_profile,
        stored_overrides,
    )

    await _enable_catalog(monkeypatch, hot_config)
    # P0 PERSIST-FIX: раньше запись документа глушилась (pg не передан),
    # а reset_learning отвечал ok:true — тест проходил поверх дефекта.
    # Теперь тот же путь исполняется на temp-SQLite (реальный chat_params).
    raw = sqlite3.connect(":memory:", isolation_level=None,
                          check_same_thread=False)
    create_schema(raw)
    seed_profile(raw, -100)
    pg = SqlitePg(raw)
    chat_params.set_chat_params_cache(chat_params.ChatParamsCache(pg))
    try:
        hypothesis = hf.evaluate_observations([
            _obs(signal="stop_request", authority_is_owner=True,
                 confidence="high", episode_id=f"ctl-{i}", topic=f"t{i}",
                 user_id=1) for i in range(1, 4)])[0]
        applied = await hf.apply_hypothesis(db, hypothesis,
                                            episode_ids=hypothesis.evidence)
        assert applied["applied"] is True
        reset = await hf.reset_learning(db, -100, pg=pg)
        assert reset["ok"] is True and reset["suspended"] >= 1
        assert stored_overrides(raw, -100)["humor.feedback"]["reset_at"]
        assert await hf.strategy_weight(db, -100, "deadpan") == 1.0
        telemetry = await hf.telemetry(db, chat_id=-100)
        assert telemetry["available"] is True
        assert telemetry["no_data_note"]
    finally:
        hot_config.set_config_cache(None)
        chat_params.set_chat_params_cache(None)
        raw.close()


@pytest.mark.asyncio
async def test_telemetry_is_honest_without_data(db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        telemetry = await hf.telemetry(db, chat_id=-100)
        assert telemetry["available"] is True
        assert telemetry["sends"] == 0
        assert telemetry["signals"] == {}
        assert telemetry["unknown_windows"] == 0
        assert telemetry["hypotheses"] == []
    finally:
        hot_config.set_config_cache(None)


# ═══ SOUL-08.8: недоступность оценщика не блокирует беседу ═════════════════

@pytest.mark.asyncio
async def test_window_pass_survives_evaluator_outage(db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        await _send(db, ts=NOW)
        await _msg(db, text="ну не знаю", ts=NOW + 50, reply_to_id=11)
        counters = await hf.run_window_pass(db, llm=None)
        assert counters["humor_evaluator_unavailable"] == 1
        assert counters["humor_signals"] == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_feedback")
        assert int((await cursor.fetchone())["c"]) == 0
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_window_pass_off_is_zero_work(db, monkeypatch):
    from services import hot_config
    monkeypatch.delenv("HUMOR_FEEDBACK_ENABLED", raising=False)
    hot_config.set_config_cache(None)
    counters = await hf.run_window_pass(db, llm=None)
    assert counters["humor_skipped_disabled"] == 1
    assert counters["humor_sends_scanned"] == 0


# ═══ SOUL-08.12: семь обязательных сценариев (детерминированные) ══════════

async def _run_scenario(db, *, replies, verdicts, technique="deadpan",
                        users=None, send_ts=NOW, chat_id=-100):
    await _send(db, ts=send_ts, technique=technique, chat_id=chat_id)
    users = users or [100 + i for i in range(len(replies))]
    for index, text in enumerate(replies):
        await _msg(db, chat_id=chat_id, user_id=users[index], text=text,
                   ts=send_ts + 20 + index * 5, reply_to_id=11)
    llm = _VerdictLLM(verdicts) if verdicts is not None else None
    return await hf.run_window_pass(db, llm=llm)


def test_scenario_live_markers_are_honest():
    markers = hf.scenario_summary()
    assert len(markers) == 7
    for entry in markers:
        assert entry["id"] in hf.SCENARIO_LIVE_MARKERS
        assert "Live:" in entry["live_marker"]
        assert len(entry["live_marker"].splitlines()) >= 3


@pytest.mark.asyncio
async def test_scenario_1_metaphor_picked_up(db, monkeypatch):
    """Собеседник подхватил бюрократическую метафору → приём подтверждён."""
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        counters = await _run_scenario(
            db, technique="bureaucratic_logic",
            replies=["тогда подъезд подаёт заявку в двух экземплярах"],
            verdicts=[{"i": 0, "signal": "metaphor_continuation",
                       "confidence": "high", "subject_user_id": 100,
                       "evidence": "развил образ", "metaphor_continued": True}])
        assert counters["humor_signals"] == 1
        cursor = await db.db.execute(
            "SELECT source_kind, signal_json FROM mca_experience_feedback")
        row = await cursor.fetchone()
        signal = json.loads(row["signal_json"])
        assert signal["signal"] == "metaphor_continuation"
        assert signal["technique"] == "bureaucratic_logic"
        assert signal["domain"] == "humor"
        # одно наблюдение — только гипотеза, вес не поднят
        assert await hf.strategy_weight(db, -100,
                                        "bureaucratic_logic") == 1.0
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_scenario_2_stop_request_weakens_only_in_context(db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        counters = await _run_scenario(
            db, replies=["перестань это писать, достало уже"],
            verdicts=[{"i": 0, "signal": "stop_request",
                       "confidence": "high",
                       "evidence": "просьба прекратить"}],
            users=None, send_ts=NOW, chat_id=-101)
        assert counters["humor_signals"] == 1
        cursor = await db.db.execute(
            "SELECT source_kind, authority, signal_json "
            "FROM mca_experience_feedback")
        row = await cursor.fetchone()
        assert row["source_kind"] == "participant_correction"
        assert json.loads(row["signal_json"])["signal"] == "stop_request"
        # явная просьба ослабила приём сразу И только в этом чате
        assert await hf.strategy_weight(db, -101, "deadpan") <= 0.2
        assert await hf.strategy_weight(db, -100, "deadpan") == 1.0
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_scenario_3_dramatic_reaction_without_joke_is_not_success(
        db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        counters = await _run_scenario(
            db, replies=["ты вообще не в теме, спор ни о чём"],
            verdicts=[{"i": 0, "signal": "unrelated", "confidence": "high"}])
        assert counters["humor_signals"] == 1     # зафиксировано как связь
        assert counters["humor_hypotheses"] == 0  # но это не успех шутки
        assert counters["humor_lessons_applied"] == 0
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_scenario_4_nobody_comments_is_unknown_not_failure(
        db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        # Окно уже закрылось: сообщений после ответа не было вовсе.
        await _send(db, ts=NOW - hf.WINDOW_SECONDS - 5)
        counters = await hf.run_window_pass(db, llm=None)
        assert counters["humor_windows_closed"] == 1
        assert counters["humor_unknown"] == 1
        cursor = await db.db.execute(
            "SELECT outcome_kind FROM mca_experience_episodes")
        assert (await cursor.fetchone())["outcome_kind"] == "unknown"
        assert counters["humor_lessons_applied"] == 0
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_scenario_5_group_talks_elsewhere_is_not_success(db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        await _send(db, ts=NOW)
        await _msg(db, text="совсем другая тема про машины", ts=NOW + 40,
                   reply_to_id=777)
        counters = await hf.run_window_pass(
            db, llm=_VerdictLLM([{"i": 0, "signal": "explicit_approval",
                                  "confidence": "high"}]))
        assert counters["humor_signals"] == 0
        assert counters["humor_unknown"] == 0
        assert counters["humor_lessons_applied"] == 0
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_scenario_6_two_chats_evaluate_differently(db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        hypothesis_a = hf.evaluate_observations([
            _obs(chat_id=-100, signal="stop_request",
                 authority_is_owner=True, confidence="high",
                 episode_id=f"a-{i}", topic=f"ta{i}", user_id=1)
            for i in range(1, 3)])
        applied = await hf.apply_hypothesis(db, hypothesis_a[0],
                                            episode_ids=hypothesis_a[0].evidence)
        assert applied["applied"] is True
        hypothesis_b = hf.evaluate_observations([
            _obs(chat_id=-200, signal="explicit_approval",
                 confidence="high", episode_id=f"b-{i}", topic=f"tb{i}",
                 user_id=200 + i) for i in range(1, 4)])
        assert hypothesis_b[0].direction == "strengthen"
        assert await hf.strategy_weight(db, -100, "deadpan") <= 0.2
        assert await hf.strategy_weight(db, -200, "deadpan") == 1.0
        lessons = await hf._humor_lessons(db, -200)
        assert lessons == []                      # чужой чат ничего не получил
    finally:
        hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_scenario_7_one_person_reactions_do_not_inflate_success(
        db, monkeypatch):
    from services import hot_config
    await _enable_catalog(monkeypatch, hot_config)
    try:
        rows = [_obs(signal="explicit_approval", user_id=42,
                     reactions_distinct=5, episode_id="same-episode",
                     topic="topic_a")]
        result = hf.evaluate_observations(rows)
        assert result[0].confirmed is False
        assert {"guard_small_n", "guard_single_topic", "guard_single_user",
                "guard_brigading"} <= set(result[0].guards)
        assert result[0].weight <= hf.MAX_WEIGHT_PER_SEND
    finally:
        hot_config.set_config_cache(None)


# ═══ SOUL-08.0: контур не дублирует Experience ════════════════════════════

def test_no_second_learning_contour_is_created():
    from services import mca_experience as me
    from services import mca_experience_jobs as mj
    import inspect as _inspect

    module_source = _inspect.getsource(hf)
    # никаких своих таблиц/миграций: контур пишет в существующие mca_*
    assert "CREATE TABLE" not in module_source
    # реакции на шутку — новый тип evidence внутри существующих классов
    # feedback (v28 CHECK не пересобирается), вид сигнала — в signal_json
    assert "humor_signal" not in me.FEEDBACK_SOURCE_KINDS
    assert hf.source_kind_for("metaphor_continuation",
                              authority_is_owner=False) in \
        me.FEEDBACK_SOURCE_KINDS
    assert hf.source_kind_for("stop_request",
                              authority_is_owner=False) == \
        "participant_correction"
    assert hf.source_kind_for("stop_request",
                              authority_is_owner=True) == "owner_correction"
    assert "humor_fit" in me.MEASUREMENTS
    assert "humor_instruction" in me.VALIDATION_KINDS
    assert ("social_preference", "humor_weaken_deadpan") in \
        me.CANONICAL_RECOMMENDATIONS
    # единственный джоб опыта сам вызывает проход окна (второго джоба нет)
    runner_source = _inspect.getsource(mj.ExperienceReviewRunner.run)
    assert "mca_humor_feedback" in runner_source
    assert "run_window_pass" in runner_source
    assert mj.default_counters()["humor_signals"] == 0
