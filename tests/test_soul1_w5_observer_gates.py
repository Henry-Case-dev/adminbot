"""SOUL-1 / W5 — ворота инициативы: не задушены, но и не спамят.

Покрытие (SOUL-18.1/18.3 + SOUL-05.8):

* **состояние окна (контрактная защита):** `not_enough_messages`/
  `eval_not_due` не должны сбрасывать накопленное `pending` и штамп
  `last_eval_ts`. RED→GREEN-свидетели фиксируют именно СОСТОЯНИЕ окна; при
  этом поведенческая формулировка «тихий чат не накопит порог никогда» не
  верна: тик пересоздаёт durable-задачу с чистым payload, поэтому база тоже
  оценивала тихие чаты (репро REVIEW-W5), а отсутствие инициатив объясняет
  устаревшее окно оценки (см. `test_window_is_the_freshest_and_watermark_
  catches_up`);
* **свежесть окна:** оценивается САМОЕ СВЕЖЕЕ окно, отставание наблюдателя
  от живого чата не накапливается (watermark);
* **негативы сохраняются:** дедуп контекста, пауза после реплики бота,
  дневной лимит, scope OFF, «не та» строка (не текст/форвард/команда/
  без автора/не группа), недоступный оценщик — всё это видно как причина,
  и ни одна защита не отключается;
* **мягкие цели (SOUL-18.4):** 0/0 → байт-паритет профиля; заданные цели
  могут только участить проверки и сократить паузу — дневной лимит,
  дедуп, бюджет и лимит темы остаются жёсткими;
* **SOUL-05.8:** инициатива использует тот же Core/Composer/Writer, что
  Direct (одна ревизия Core/Style и тот же кадр личности), SILENT легален,
  а проход формы идёт тем же единственным путём (контекст `initiative`).

TEST-LIFECYCLE: CONTRACT owner=SOUL-18.3/SOUL-18.4/SOUL-05.8 (soul-1, W5)
"""
from __future__ import annotations

import json
import time

import pytest

from services import chat_params
from services import hot_config
from services import mca_events
from services import initiative_observer as obs
from services import prompt_composer as pc
from services.database import DatabaseService

CHAT = -2026
CHAT_OFF = -2099
BOT_ID = 999


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


def _caches(by_chat=None, hot=None):
    hot_config.set_config_cache(_FakeHot(hot or {}))
    chat_params.set_chat_params_cache(_FakeChatParams(by_chat or {}))


def _reset_caches():
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


class _FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), str(text)))

        class _Msg:
            message_id = 7000 + len(self.sent)

        return _Msg()


class _FakeWriter:
    def __init__(self, action="reply", text="Реплика инициативы."):
        self.action = action
        self.text = text
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        from services.direct_l1 import L1Plan
        return L1Plan(action=self.action, confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return self.text


class _FakeLLM:
    def __init__(self, verdicts=()):
        self.verdicts = list(verdicts)
        self.calls = 0
        self.prompts: list = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.prompts.append([dict(m) for m in messages])
        if self.verdicts:
            return self.verdicts.pop(0)
        return json.dumps({"opportunity": False})


def _verdict(**kw) -> str:
    base = {"opportunity": True, "kind": "development", "action": "say",
            "horizon": "now", "addressee_user_id": None,
            "topic_key": "tema", "goal": "участники обсуждают тему",
            "rationale": "есть что добавить"}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


async def _db(tmp_path, name) -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db, *, chat_id=CHAT, user_id=42, text="реплика", ts=None,
               media_type="text", is_forward=0) -> int:
    ts = int(time.time()) if ts is None else int(ts)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, ?, 'u', ?, NULL)",
        (user_id, chat_id, text, ts, media_type, is_forward))
    await db.db.commit()
    return cursor.lastrowid


async def _payload(db) -> dict:
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY COALESCE(finished_at, updated_at) DESC, rowid DESC LIMIT 1",
        (obs.OBSERVE_JOB_KIND,))
    row = await cursor.fetchone()
    return json.loads((row["payload"] if row else "{}") or "{}")


def _entry(payload, chat_id=CHAT) -> dict:
    return dict((payload.get("chats") or {}).get(str(chat_id)) or {})


@pytest.fixture(autouse=True)
def _clean():
    mca_events.reset_pending()
    _reset_caches()
    yield
    mca_events.reset_pending()
    _reset_caches()


# ═══ 1. Состояние окна: накопление не сбрасывается промежуточными тиками ════

@pytest.mark.asyncio
async def test_quiet_chat_accumulates_pending_until_threshold(tmp_path):
    """GREEN и до, и после W5 — фиксирует КОНТРАКТ накопления окна.

    Чат присылает по 3 реплики за тик при пороге 8, и оценка обязана
    состояться. Этот тест НЕ является RED-свидетелем дефекта «сброс
    pending»: тик пересоздаёт durable-задачу с чистым payload, поэтому и
    база доходила до оценки (репро REVIEW-W5: ×4 по 3 и ×10 по 1 → evals=1).
    Дефект состояния окна убивают точечные свидетели
    (`test_not_enough_keeps_pending_and_interval_stamp`,
    `test_eval_not_due_keeps_pending_for_later`); главную причину тишины
    проверяет `test_window_is_the_freshest_and_watermark_catches_up`.
    """
    db = await _db(tmp_path, "w5_quiet.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 8,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "initiative.max_replies_per_day": 10,
                    "initiative.eval_llm_budget_per_day": 10}})
    llm = _FakeLLM()
    base = int(time.time()) - 600
    try:
        for tick in range(4):
            for i in range(3):
                await _msg(db, text="обсуждаем поездку %d" % (tick * 3 + i),
                           ts=base + tick * 10 + i)
            assert await obs.observe_tick(db, bot=_FakeBot(),
                                          writer_service=_FakeWriter(),
                                          llm=llm) == "completed"
        counters = (await _payload(db))["counters"]
        # 12 реплик > порога 8 → оценка обязана состояться
        assert counters["evals"] >= 1, counters
        assert llm.calls >= 1
        # и накопление не «съедалось» промежуточными тиками
        assert counters["observed"] == 12
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_not_enough_keeps_pending_and_interval_stamp(tmp_path):
    """`not_enough` не трогает ни накопление, ни штамп интервала."""
    db = await _db(tmp_path, "w5_pending.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 8,
                    "initiative.eval_min_interval_seconds": 3600,
                    "initiative.min_gap_seconds": 0,
                    "initiative.eval_llm_budget_per_day": 10}})
    try:
        for i in range(3):
            await _msg(db, text="редкая реплика %d" % i,
                       ts=int(time.time()) - 100 + i)
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=_FakeLLM()) == "completed"
        entry = _entry(await _payload(db))
        assert entry["pending"] == 3
        assert int(entry.get("last_eval_ts") or 0) == 0
        skips = (await _payload(db))["counters"]["eval_skips"]
        assert skips.get("not_enough_messages", 0) >= 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_eval_not_due_keeps_pending_for_later(tmp_path):
    """Интервал проверок не должен «обнулять» накопленное окно."""
    db = await _db(tmp_path, "w5_interval.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 7200,
                    "initiative.min_gap_seconds": 0,
                    "initiative.eval_llm_budget_per_day": 10}})
    llm = _FakeLLM()
    base = int(time.time()) - 300
    try:
        for i in range(4):
            await _msg(db, text="первое окно %d" % i, ts=base + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        assert llm.calls == 1
        for i in range(4):
            await _msg(db, text="второе окно %d" % i, ts=base + 100 + i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        entry = _entry(payload)
        # интервал не прошёл: причины записаны, накопление сохранено
        assert payload["counters"]["eval_skips"].get("eval_not_due", 0) >= 1
        assert entry["pending"] >= 4
    finally:
        await db.close()


# ═══ 2. Свежесть окна и watermark ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_window_is_the_freshest_and_watermark_catches_up(tmp_path):
    """Оценивается живой конец разговора, а не «хвост старой пачки»."""
    db = await _db(tmp_path, "w5_fresh.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "initiative.max_replies_per_day": 10,
                    "initiative.eval_llm_budget_per_day": 10}})
    llm = _FakeLLM()
    base = int(time.time()) - 3600
    try:
        newest_id = 0
        for i in range(60):
            newest_id = await _msg(db, text="поток %d" % i, ts=base + i)
        await _msg(db, text="самый-свежий-маркер-разговора",
                   ts=base + 61)
        assert await obs.observe_tick(db, bot=_FakeBot(),
                                      writer_service=_FakeWriter(),
                                      llm=llm) == "completed"
        prompt = llm.prompts[0][1]["content"]
        assert "самый-свежий-маркер-разговора" in prompt
        entry = _entry(await _payload(db))
        assert int(entry.get("last_eval_msg_id") or 0) >= newest_id
        assert int(entry.get("last_seen_msg_id") or 0) >= newest_id
    finally:
        await db.close()


# ═══ 3. Негативы: защиты на месте ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_context_duplicate_still_blocks_repeat_evaluation(tmp_path):
    """Уже оценённое окно не переоценивается (дедуп контекста жив)."""
    db = await _db(tmp_path, "w5_dup.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "max_replies_per_day": 10,
                    "initiative.max_replies_per_day": 10,
                    "initiative.eval_llm_budget_per_day": 10}})
    llm = _FakeLLM()
    base = int(time.time()) - 300
    try:
        for i in range(5):
            await _msg(db, text="одно и то же окно %d" % i, ts=base + i)
        runner = obs.InitiativeObserverRunner(db)
        rows = await runner._window_rows(CHAT, 0)      # noqa: SLF001
        assert rows
        ctx_hash = runner._context_hash(CHAT, rows)    # noqa: SLF001
        # состояние: окно уже оценено, но накопление снова выше порога
        seeded = {
            obs.CURSOR_KEY: 0,
            "counters": obs.default_counters(),
            "chats": {str(CHAT): {"pending": 10, "last_eval_ts": 0,
                                  "recent_hashes": [[ctx_hash, int(time.time())]],
                                  "topics": {}, "eval_day": 0,
                                  "eval_day_count": 0}},
            "day": {"stamp": 0, "observed": 0, "opportunities": 0},
            "last_diag_ts": 0,
        }
        active = await obs.get_active_observe(db)
        if active is None:
            await obs.enqueue_observe(db)
            active = await obs.get_active_observe(db)
        assert active is not None
        await db.db.execute("UPDATE task_jobs SET payload = ? WHERE job_id = ?",
                            (json.dumps(seeded, ensure_ascii=True),
                             str(active["job_id"])))
        await db.db.commit()
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get("context_duplicate", 0) \
            >= 1
        assert llm.calls == 0, "дубль контекста не должен тратить LLM"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_min_gap_after_bot_reply_still_blocks(tmp_path, monkeypatch):
    db = await _db(tmp_path, "w5_gap.db")
    _caches({CHAT: {"initiative.frequency_profile": "normal"}})
    llm = _FakeLLM()
    base = int(time.time()) - 300
    try:
        for i in range(10):
            await _msg(db, text="живой разговор %d" % i, ts=base + i)

        async def _recent(self, chat_id):
            return 60          # бот отвечал минуту назад

        monkeypatch.setattr(obs.InitiativeObserverRunner,
                            "_last_bot_output_age", _recent)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get("min_gap", 0) >= 1
        assert llm.calls == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_day_cap_still_hard_with_soft_target(tmp_path):
    """Мягкая цель НЕ поднимает жёсткий дневной лимит."""
    db = await _db(tmp_path, "w5_cap.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "initiative.max_replies_per_day": 1,
                    "initiative.eval_llm_budget_per_day": 10,
                    "initiative.soft_target_replies_per_day": 12}})
    bot, writer = _FakeBot(), _FakeWriter()
    base = int(time.time()) - 300
    try:
        for i in range(5):
            await _msg(db, text="повод номер %d" % i, ts=base + i)
        llm = _FakeLLM([_verdict(topic_key="t1"), _verdict(topic_key="t2"),
                        _verdict(topic_key="t3")])
        await obs.observe_tick(db, bot=bot, writer_service=writer, llm=llm)
        assert len(bot.sent) == 1
        for i in range(5):
            await _msg(db, text="новый повод %d" % i, ts=base + 200 + i)
        llm2 = _FakeLLM([_verdict(topic_key="t9"), _verdict(topic_key="t10")])
        await obs.observe_tick(db, bot=bot, writer_service=writer, llm=llm2)
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get("day_cap", 0) >= 1
        assert len(bot.sent) == 1, "дневной лимит не поднялся мягкой целью"
        profile = await obs.frequency_profile(CHAT)
        assert profile["max_replies_per_day"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_chat_scope_off_blocks_any_evaluation(tmp_path):
    db = await _db(tmp_path, "w5_scope.db")
    _caches({CHAT_OFF: {"initiative.enabled": False},
             CHAT: {}})
    llm = _FakeLLM()
    try:
        for i in range(10):
            await _msg(db, chat_id=CHAT_OFF, text="чат выключен %d" % i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=llm)
        payload = await _payload(db)
        assert payload["counters"]["eval_skips"].get("chat_disabled", 0) >= 1
        assert payload["counters"]["evals"] == 0
        assert llm.calls == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ineligible_rows_are_skipped_with_reasons(tmp_path):
    db = await _db(tmp_path, "w5_skips.db")
    _caches({CHAT: {}})
    try:
        await _msg(db, text="", ts=int(time.time()) - 10)
        await _msg(db, text="медиа", ts=int(time.time()) - 9,
                   media_type="video")
        await _msg(db, text="форвард", ts=int(time.time()) - 8, is_forward=1)
        await _msg(db, text="/start", ts=int(time.time()) - 7)
        await _msg(db, text="без автора", user_id=None,
                   ts=int(time.time()) - 6)
        await _msg(db, chat_id=777, text="личка", ts=int(time.time()) - 5)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=_FakeLLM())
        payload = await _payload(db)
        counters = payload["counters"]
        assert counters["observed"] == 0
        assert counters["scan_skipped"] == 6
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_llm_unavailable_is_visible_not_silent(tmp_path):
    db = await _db(tmp_path, "w5_nollm.db")
    _caches({CHAT: {"initiative.frequency_profile": "active",
                    "initiative.eval_min_messages": 4,
                    "initiative.eval_min_interval_seconds": 0,
                    "initiative.min_gap_seconds": 0,
                    "initiative.eval_llm_budget_per_day": 10}})
    try:
        for i in range(6):
            await _msg(db, text="повод при мёртвом оценщике %d" % i)
        await obs.observe_tick(db, bot=_FakeBot(), writer_service=_FakeWriter(),
                               llm=None)
        payload = await _payload(db)
        assert payload["counters"]["eval_unavailable"] >= 1
        await mca_events.flush_events(db)
        cursor = await db.db.execute(
            "SELECT stage, outcome FROM mca_events WHERE event_name = ?",
            ("initiative_observer_diagnostic",))
        stages = [str(r["stage"] or "") for r in await cursor.fetchall()]
        assert any("semantic_eval_unavailable" in s for s in stages), stages
    finally:
        await db.close()


# ═══ 4. Мягкие цели: паритет при 0 и границы при заданной цели ═════════════

@pytest.mark.asyncio
async def test_soft_targets_zero_keep_profile_parity(tmp_path):
    db = await _db(tmp_path, "w5_parity.db")
    _caches({CHAT: {}})
    try:
        profile = await obs.frequency_profile(CHAT)
        normal = obs.FREQUENCY_PROFILES["normal"]
        for key, value in normal.items():
            assert profile[key] == value, key
        assert profile["soft_target_replies_per_day"] == 0
        assert profile["soft_target_observation_interval_seconds"] == 0
        effective = await obs.effective_limits(db, CHAT)
        assert effective["eval_min_messages"] == normal["eval_min_messages"]
        assert effective["eval_min_interval_seconds"] == \
            normal["eval_min_interval_seconds"]
        assert effective["min_gap_seconds"] == normal["min_gap_seconds"]
        assert effective["max_replies_per_day"] == \
            normal["max_replies_per_day"]
        assert effective["easing"] == {"observation": False, "min_gap": False}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_soft_targets_only_ease_within_documented_bounds(tmp_path):
    db = await _db(tmp_path, "w5_soft.db")
    _caches({CHAT: {"initiative.soft_target_replies_per_day": 12,
                    "initiative.observation_target_interval_seconds": 1800}})
    try:
        profile = await obs.frequency_profile(CHAT)
        assert profile["soft_target_replies_per_day"] == 12
        assert profile["soft_target_observation_interval_seconds"] == 1800
        effective = await obs.effective_limits(db, CHAT)
        normal = obs.FREQUENCY_PROFILES["normal"]
        # проверки участились, но не ниже границ
        assert effective["easing"]["observation"] is True
        assert effective["eval_min_interval_seconds"] == 1800
        assert obs.MIN_OBSERVATION_INTERVAL_FLOOR <= \
            effective["eval_min_interval_seconds"] <= \
            normal["eval_min_interval_seconds"]
        assert obs.MIN_EVAL_MESSAGES_FLOOR <= \
            effective["eval_min_messages"] <= normal["eval_min_messages"]
        # пауза сократилась, но не ниже floor
        assert effective["min_gap_seconds"] >= obs.MIN_GAP_FLOOR_SECONDS
        assert effective["min_gap_seconds"] <= normal["min_gap_seconds"]
        # жёсткие защиты не тронуты
        assert effective["max_replies_per_day"] == \
            normal["max_replies_per_day"]
        assert effective["max_replies_per_topic"] == 1
        assert effective["eval_llm_budget_per_day"] == \
            normal["eval_llm_budget_per_day"]
        assert effective["soft_targets"]["active"] is True
        assert effective["soft_targets"]["bounds"] == \
            obs.SOFT_TARGET_BOUNDS_TEXT
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_observation_target_below_floor_clamps(tmp_path):
    db = await _db(tmp_path, "w5_floor.db")
    _caches({CHAT: {"initiative.observation_target_interval_seconds": 60}})
    try:
        effective = await obs.effective_limits(db, CHAT)
        assert effective["eval_min_interval_seconds"] == \
            obs.MIN_OBSERVATION_INTERVAL_FLOOR
        assert effective["eval_min_messages"] >= obs.MIN_EVAL_MESSAGES_FLOOR
    finally:
        await db.close()


# ═══ 5. SOUL-05.8: тот же Core/Composer/Writer + SILENT легален ════════════

CORE_TEXT = "ЯДРО_ИНИЦИАТИВЫ_И_DIRECT"
PERSONA = "<Persona>\nИмя: Бот. Характер: язвительный наблюдатель.\n</Persona>"


class _StubLLM:
    def __init__(self, reply="Короткая инициативная реплика"):
        self.reply = reply
        self.calls = 0
        self.messages: list = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.messages.append([dict(m) for m in messages])
        return self.reply


class _StubService:
    """Duck-typed DirectChatService: реальные методы сборки/Writer."""

    def __init__(self, llm):
        self.llm = llm
        self.db = None

    async def _l2_write_answer(self, *args, **kwargs):
        from services.direct_chat_service import DirectChatService as D
        return await D._l2_write_answer(self, *args, **kwargs)

    async def _compose_speech_system(self, *args, **kwargs):
        from services.direct_chat_service import DirectChatService as D
        return await D._compose_speech_system(self, *args, **kwargs)

    async def _initiative_persona_block(self, chat_id):
        return PERSONA


@pytest.mark.asyncio
async def test_initiative_writer_shares_core_style_and_persona(tmp_path,
                                                              monkeypatch):
    """Один и тот же Core/Policy/личность у Direct и Initiative (05.8)."""
    from services import style_policy as sp
    from services.direct_chat_service import DirectChatService as D
    from services import bot_persona
    db = await _db(tmp_path, "w5_voice.db")
    monkeypatch.setenv("UNIFIED_COMPOSER_ENABLED", "1")
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    hot_config.set_config_cache(_FakeHot({
        "flags.unified_composer_enabled": True,
        "flags.speech_style_policy_enabled": True,
        "flags.persona_enabled": True,
        "character.core": {"revision": 7, "enabled": True,
                           "full_text": CORE_TEXT, "compact_text": CORE_TEXT},
        sp.DOC_KEY: sp.build_document(presets=("no_quotes",),
                                      revision=3, owner=1, reason="test"),
    }))
    chat_params.set_chat_params_cache(_FakeChatParams({CHAT: {}}))
    pc.reset_state()

    async def _persona(chat_id, *args, **kwargs):
        return PERSONA

    monkeypatch.setattr(bot_persona, "resolve_bot_persona", _persona)
    monkeypatch.setattr(bot_persona, "build_persona_prompt_block",
                        lambda *a, **kw: PERSONA)
    try:
        llm = _StubLLM()
        service = _StubService(llm)
        from services.direct_l1 import L1Plan
        plan = L1Plan(action="reply", confidence=0.9,
                      confidence_bucket="high", source="llm")
        text = await D.generate_initiative_reply(
            service, CHAT, {"goal": "повод", "kind": "development",
                            "origin": "unfinished_topic"},
            l1_plan=plan, correlation_id="w5-voice-1")
        assert text.strip()
        initiative_manifest = pc.get_manifest(CHAT, run_id="w5-voice-1",
                                              writer="initiative_writer")
        assert initiative_manifest is not None
        # тот же Core и та же Style Policy, что у Direct-писателя этого чата
        direct_manifest = pc.get_manifest(CHAT, run_id="w5-voice-direct",
                                          writer="l2_writer")
        assert direct_manifest is None      # ещё не собирали Direct
        direct_result = await service._l2_write_answer(
            CHAT, "прямой вопрос", temperature=0.7,
            correlation_id="w5-voice-2", character_block=PERSONA,
            writer="l2_writer", response_plan=None)
        assert direct_result and direct_result[0]
        direct_manifest = pc.get_manifest(CHAT, run_id="w5-voice-2",
                                          writer="l2_writer")
        assert direct_manifest is not None
        assert initiative_manifest.versions["core"] == \
            direct_manifest.versions["core"]
        assert initiative_manifest.versions["style_policy"] == \
            direct_manifest.versions["style_policy"]
        assert initiative_manifest.versions["identity"] == \
            direct_manifest.versions["identity"]
        assert initiative_manifest.versions["core"]
        # кадр личности инициативы — владельческая персона того же чата
        pinned = pc.recall_turn_refs(CHAT, "w5-voice-1")
        assert pinned is not None and pinned.core is not None
        assert pinned.core.revision == initiative_manifest.versions["core"]
    finally:
        pc.reset_state()
        await db.close()


@pytest.mark.asyncio
async def test_silent_decision_never_calls_writer(tmp_path):
    """SILENT — легальный исход: Writer не вызывается (05.8)."""
    from services import mca_intents as mi
    from services.direct_chat_service import handle_initiative
    db = await _db(tmp_path, "w5_silent.db")
    _caches({CHAT: {}})
    writer = _FakeWriter(action="silent")
    try:
        candidate = mi.candidate_from_trigger(
            trigger_kind="new_message", chat_id=CHAT, kind="topic_interest",
            source="memory", goal="повод", priority=1, reason_code="observer")
        situation = mi.InitiativeSituation(
            trigger_kind="new_message", chat_id=CHAT, direct_pending=False,
            same_event_pending=False, sensitive_moment=False, relations_ok=True,
            bot_replied_recently=False, reply_needed=False, topic_open=True,
            open_intent_ids=None, requested_source="observer")
        result = await handle_initiative(
            bot=_FakeBot(), chat_id=CHAT, situation=situation,
            candidates=[candidate], db=db, writer_service=writer,
            correlation_id="w5-silent")
        assert result["status"] == "silent"
        assert writer.generate_calls == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_initiative_text_goes_through_single_style_pass(tmp_path,
                                                              monkeypatch):
    """Жёсткие правила формы применяются к инициативе тем же проходом."""
    from services import style_policy as sp
    from services.direct_chat_service import _style_initiative_text
    db = await _db(tmp_path, "w5_style.db")
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    hot_config.set_config_cache(_FakeHot({
        "flags.speech_style_policy_enabled": True,
        sp.DOC_KEY: sp.build_document(presets=("no_quotes",
                                               "no_trailing_period"),
                                      revision=5, owner=1, reason="test"),
    }))
    chat_params.set_chat_params_cache(_FakeChatParams({CHAT: {}}))
    try:
        text, outcome = await _style_initiative_text(
            "Ну это «гениальная» идея.", CHAT)
        assert "«" not in text and "»" not in text
        assert not text.rstrip().endswith(".")
        assert outcome is not None and outcome.applied is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_initiative_style_pass_receives_l1_extent(tmp_path, monkeypatch):
    """План L1 (в т.ч. one_word/micro) доходит до прохода формы инициативы.

    Требование §19 п.5: инициативу отдельно проверяем с hard no-quotes/
    no-trailing-period и с `one_word`/`micro` там, где план уместен — значит
    extent L1 обязан попадать в тот же единственный проход формы, а не
    теряться на инициативном пути.
    """
    from services import style_policy as sp
    from services.direct_chat_service import _style_initiative_text
    from services.direct_l1 import L1Plan
    db = await _db(tmp_path, "w5_extent.db")
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    hot_config.set_config_cache(_FakeHot({
        "flags.speech_style_policy_enabled": True,
        sp.DOC_KEY: sp.build_document(presets=("no_trailing_period",),
                                      revision=6, owner=1, reason="test"),
    }))
    chat_params.set_chat_params_cache(_FakeChatParams({CHAT: {}}))
    seen = {}
    original = sp.apply_style_policy

    async def _spy(text, **kwargs):
        plan = kwargs.get("plan")
        seen["context"] = kwargs.get("context")
        seen["stage"] = kwargs.get("stage")
        seen["extent"] = getattr(plan, "extent", None)
        return await original(text, **kwargs)

    monkeypatch.setattr(sp, "apply_style_policy", _spy)
    try:
        for extent in ("one_word", "micro"):
            plan = L1Plan(action="reply", confidence=0.9,
                          confidence_bucket="high", source="llm",
                          extent=extent)
            text, _outcome = await _style_initiative_text(
                "Ок.", CHAT, plan)
            assert seen["context"] == "initiative"
            assert seen["stage"] == "initiative_pre_send"
            assert seen["extent"] == extent, (extent, seen)
            assert text
    finally:
        await db.close()
