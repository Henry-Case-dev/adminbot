"""MEME-PIPELINE-REFACTOR-01 / P9 `MEME-INIT-DIAG` — диагностика ПО КАЖДОМУ
механизму в сервисном слое (без web): два отдельных блока, честное «нет
данных», единственная правда о конфликте публикаций, свой кулдаун механизма.

TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-03-INITIATIVE-INDEPENDENCE
(строки карты MEME-IIC-DIAG-TIMES/RANDOM/COOLDOWN-CONFLICT/NO-MIX).

Правила набора: время передаётся параметром (`now`/`now_ts`), без `sleep`;
внешние швы (`sender`/`image_provider`/`random_source`/`summarizer`) — штатные
DI-аргументы, предмет проверки (источники payload/журнала/брони и сборщик
диагностики) не подменяется.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from services import initiative_diagnostics as diag
from services import initiative_observer as obs
from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import publication_coordination as pub
from services.database import DatabaseService

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())
CHAT = -100
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}

#: Допустимые ключи ответа (R17-гигиена: наружу идут коды/числа/ID).
#: Собирается ИЗ контракта сервиса: тест падает, если появился ключ вне
#: объявленной формы (и если ключ из формы исчез — см. тест формы блока).
ALLOWED_KEYS = frozenset(
    {"schema_version", "generated_at", "chat_id", "text_initiative", "meme",
     "degraded",
     # вложенные объекты ворот (`blocking`)
     "blocked", "warned", "gate", "status", "reason_code", "state"}
    | set(diag.MECHANISM_BLOCK_FIELDS)
    | set(diag.DRAW_FIELDS)
    | set(diag.PUBLICATION_FIELDS)
    | set(diag.COOLDOWN_FIELDS)
    | set(diag.QUOTA_FIELDS)
    | set(diag.SKIP_FIELDS)
)

#: Поля с ОТКРЫТЫМ набором ключей (имена ворот/счётчиков механизма: коды, а
#: не текст). Значения в них — только скаляры.
_OPEN_KEY_FIELDS = frozenset({"conditions", "stages"})

#: Подстроки, которых в диагностике быть не должно (тексты и секреты).
BANNED_KEYS = frozenset({"joke", "summary", "prompt", "text", "content_text",
                         "api_key", "token", "secret", "password"})


# ── стенд ───────────────────────────────────────────────────────────────────

async def _db(tmp_path, name="diag.db") -> DatabaseService:
    svc = DatabaseService(str(tmp_path / name))
    await svc.initialize()
    return svc


async def _schema(svc) -> None:
    """Журнал квоты + бронь публикации (одна точка, как в поставке)."""
    meme.SqliteQuotaLedger(str(svc.db_path)).apply_schema()


async def _drop_claim_table(svc) -> None:
    await svc.db.execute("DROP TABLE %s" % pub.CLAIM_TABLE)
    await svc.db.commit()


async def _seed_observe_payload(svc, payload: dict, *, now: int = NOW_TS):
    """Payload durable-задачи наблюдателя (как его пишет `_checkpoint`).

    Прошлые записи того же вида удаляются: сценарий «два разных состояния»
    должен читать ровно последнее, как в бою.
    """
    await svc.db.execute("DELETE FROM task_jobs WHERE kind = ?",
                         (obs.OBSERVE_JOB_KIND,))
    await svc.db.execute(
        "INSERT INTO task_jobs (job_id, owner, kind, coalesce_key, payload, "
        "status, reason_code, error_code, attempt, max_attempts, "
        "deadline_at, heartbeat_at, generation, fencing_token, created_at, "
        "updated_at, finished_at) VALUES (?, 'test', ?, NULL, ?, 'running', "
        "NULL, NULL, 1, 3, NULL, ?, 0, 0, ?, ?, NULL)",
        (f"job-observe-{now}", obs.OBSERVE_JOB_KIND,
         json.dumps(payload, ensure_ascii=False), now - 60, now - 60,
         now - 60))
    await svc.db.commit()


def _text_payload(**kwargs) -> dict:
    """Payload с решением текстовой инициативы (боевой `_note_decision`)."""
    now_override = kwargs.pop("now_override", NOW_TS)
    eval_ts = kwargs.pop("eval_ts", now_override - 600)
    runner = obs.InitiativeObserverRunner.__new__(obs.InitiativeObserverRunner)
    runner._publication = None
    payload = {"chats": {str(CHAT): {"last_eval_ts": eval_ts}}}
    runner._note_decision(payload, CHAT, now=now_override, **kwargs)
    return payload


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _rows(chat_id: int, n: int = 3) -> list[dict]:
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


class _Hit:
    async def draw_probability(self, **kwargs):
        return mrs.DrawResult(value=0.0, source="pseudorandom",
                              selected_source="quantum", provider=None,
                              draw_id="draw-p9")


class _Provider:
    async def __call__(self, prompt, chat_id, job_id):
        return SimpleNamespace(ok=True, called=True, reason="", content=b"png")


class _Sender:
    def __init__(self, message_id: int = 900):
        self.calls: list[tuple] = []
        self.message_id = message_id

    async def __call__(self, chat_id, content, prompt):
        self.calls.append((chat_id, content, prompt))
        return SimpleNamespace(message_id=self.message_id)


async def _meme_pass(state: dict, *, ledger, settings=None, sender=None,
                     summary="хук", joke="прикол", chat_enabled=None):
    """Один проход мема на реальном журнале (payload через `_note_state`).

    ``chat_enabled`` — тот же шов, что у боевого прохода
    (`InitiativeObserverRunner._meme_phase` передаёт
    `initiative_observer.chat_observer_enabled`).
    """
    async def summarizer(_cid, _rows_arg, _system):
        return summary

    async def joke_generator(_cid, _summary, _instruction):
        return joke

    async def gate(_cid):
        return True, "ok"

    return await meme.on_initiative_cycle(
        None, [CHAT], state=state,
        settings=settings if settings is not None else _settings(),
        ledger=ledger, now=NOW, now_ts=NOW_TS, tz_name="UTC",
        tz_source="utc_fallback", initiative_enabled=lambda: True,
        chat_enabled=chat_enabled,
        image_status=IMAGE_OK, random_source=_Hit(), messages=_rows(CHAT),
        model_chars=200, claim_store=None, summarizer=summarizer,
        joke_generator=joke_generator, image_provider=_Provider(),
        sender=sender if sender is not None else _Sender(), publish_gate=gate)


def _image_ok(monkeypatch):
    async def _image(_chat_id, health=None):
        return dict(IMAGE_OK)

    monkeypatch.setattr(meme, "image_dependency", _image)


def _gates_on(monkeypatch):
    """Мастер-флаг и тумблер чата ВКЛЮЧЕНЫ (сценарии без этих гейтов).

    Это внешние швы (`initiative_observer`), а не предмет проверки: тест про
    отсутствие таблицы брони или про кулдаун не должен зависеть от глобального
    hot-конфига, оставленного соседним тестом.
    """
    monkeypatch.setattr(obs, "observer_enabled", lambda: True)

    async def _chat_on(_chat_id):
        return True

    monkeypatch.setattr(obs, "chat_observer_enabled", _chat_on)


def _keys_of(value, out: set | None = None, *,
             skip: frozenset = frozenset()) -> set:
    """Ключи словарей на любой глубине (для гигиены ответа)."""
    out = set() if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key)
            out.add(name)
            if name in skip:
                continue
            _keys_of(item, out, skip=skip)
    elif isinstance(value, list):
        for item in value:
            _keys_of(item, out, skip=skip)
    return out


# ═══ 1. два блока, независимые источники ════════════════════════════════════

def test_two_blocks_are_present_and_independent(tmp_path, monkeypatch):
    """Мем проверялся, текст — ни разу: блоки не подменяют друг друга."""
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path)
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            await _meme_pass(state, ledger=ledger,
                             settings=_settings(cooldown_seconds=120))
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True,
                         "chats": state}})
            return await diag.collect_mechanism_diagnostics(svc, CHAT,
                                                            now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    text = result["text_initiative"]
    meme_block = result["meme"]

    assert result["schema_version"] == diag.DIAG_SCHEMA_VERSION
    assert result["generated_at"] == NOW_TS
    assert result["chat_id"] == CHAT
    assert text["mechanism"] == diag.MECHANISM_TEXT
    assert meme_block["mechanism"] == diag.MECHANISM_MEME
    assert text is not meme_block
    assert text["output_kind"] == "initiative_reply"
    assert meme_block["output_kind"] == meme.OUTPUT_KIND

    # Мем реально проверялся — у него есть время проверки и draw.
    assert meme_block["available"] is True
    assert meme_block["data_state"] == diag.DATA_OK
    assert meme_block["last_check_ts"] == NOW_TS
    assert meme_block["random"]["purpose"] == mrs.PURPOSE_MEME_TRIGGER
    assert meme_block["stages"]["considered"] == 1

    # Текстовая инициатива в этом payload не наблюдалась: «нет данных»,
    # а не нули и не значения мема.
    assert text["available"] is False
    assert text["data_state"] == diag.DATA_NO_DATA
    assert text["last_check_ts"] is None
    assert text["random"] is None
    assert text["stages"] is None
    assert diag.NO_DATA_NEVER_CHECKED in text["no_data_reasons"]


# ═══ 2. «никогда» отличимо от нулевого кулдауна ═════════════════════════════

def test_never_checked_is_distinguishable_from_zero_cooldown(tmp_path,
                                                             monkeypatch):
    """`last_check_ts = 0` в журнале — это «никогда», а не 01.01.1970."""
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="never.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=6 * 3600))
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    for block in (result["text_initiative"], result["meme"]):
        # «Никогда» — явное None в поле времени проверки.
        assert block["last_check_ts"] is None
        assert block["available"] is False
        assert diag.NO_DATA_NEVER_CHECKED in block["no_data_reasons"]
        # Законный ноль кулдауна — ДРУГОЕ поле со своей причиной.
        cooldown = block["cooldown"]
        assert cooldown["remaining_seconds"] == 0
        assert cooldown["basis"] in ("no_prior_publication",
                                     "no_prior_provider_call")
        assert cooldown["scope"] == diag.COOLDOWN_SCOPE
        assert cooldown["basis_ts"] is None

    assert result["meme"]["cooldown"]["own_seconds"] == 6 * 3600
    assert result["meme"]["next_check_ts"] is None
    assert result["text_initiative"]["next_check_ts"] is None
    assert result["text_initiative"]["next_check_basis"] == \
        diag.NO_DATA_NEVER_CHECKED


# ═══ 3. degraded — деградация, а не успех ═══════════════════════════════════

def test_degraded_coordination_is_reported_as_degradation(tmp_path,
                                                          monkeypatch):
    """Нет таблицы брони: конфликт НЕИЗВЕСТЕН, а не «конфликта нет»."""
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="degraded.db")
        try:
            await _schema(svc)
            await _drop_claim_table(svc)
            return await diag.collect_mechanism_diagnostics(svc, CHAT,
                                                            now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    for name in ("text_initiative", "meme"):
        publication = result[name]["publication"]
        assert publication["coordination"] == "degraded"
        assert publication["degraded"] is True
        assert publication["available"] is False
        assert publication["degraded_reason"] == "claim_table_absent"
        # Деградация НЕ выдаётся за «конфликта нет» и не за «всё хорошо».
        assert publication["conflict"] is None
        assert publication["conflict_state"] == diag.CONFLICT_UNKNOWN
        assert publication["ok"] is None
    assert result["degraded"] == [diag.MECHANISM_TEXT, diag.MECHANISM_MEME]


# ═══ 4. конфликт — только из `publication` ══════════════════════════════════

def test_conflict_marker_comes_only_from_publication(tmp_path, monkeypatch):
    """Записанный `publication_conflict` не делает конфликт текущим."""
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="conflict.db")
        try:
            await _schema(svc)
            await _seed_observe_payload(
                svc, _text_payload(skip_reason=obs.SKIP_PUBLICATION_CONFLICT))
            coordinator = pub.PublicationCoordinator(svc)
            before = await diag.collect_mechanism_diagnostics(svc, CHAT,
                                                              now=NOW_TS)
            # Другой механизм реально опубликовался минуту назад.
            decision = await coordinator.acquire(
                CHAT, pub.KIND_MEME_INITIATIVE, now=NOW_TS - 60,
                interval_seconds=1800)
            assert decision.granted is True
            await coordinator.release(
                CHAT, decision.claim_id, published=True,
                holder_kind=pub.KIND_MEME_INITIATIVE, now=NOW_TS - 60)
            after = await diag.collect_mechanism_diagnostics(svc, CHAT,
                                                            now=NOW_TS)
            return before, after
        finally:
            await svc.close()

    before, after = asyncio.run(scenario())
    text_before = before["text_initiative"]
    # Запись прошлого прохода есть, но бронь чиста → конфликта НЕТ.
    assert text_before["skip_recorded"]["code"] == \
        obs.SKIP_PUBLICATION_CONFLICT
    assert text_before["skip_recorded"]["origin"] == "payload_state"
    assert text_before["publication"]["conflict"] is False
    assert text_before["publication"]["conflict_state"] == diag.CONFLICT_CLEAR

    text_after = after["text_initiative"]
    # Тот же маркер появляется только потому, что так сказала бронь.
    assert text_after["publication"]["conflict"] is True
    assert text_after["publication"]["other_kind"] == pub.KIND_MEME_INITIATIVE
    assert text_after["publication"]["other_age_seconds"] == 60
    assert text_after["publication"]["interval_seconds"] == 1800
    # Мем видит свою публикацию как свою — конфликта у него нет.
    assert after["meme"]["publication"]["conflict"] is False


# ═══ 5. `probability_one` = draw не выполнялся ══════════════════════════════

def test_probability_one_is_reported_as_no_draw(tmp_path, monkeypatch):
    """p=1.0 (паритет прежнего поведения) — не выигранный случай."""
    _image_ok(monkeypatch)
    trace = obs.build_draw_trace(None, purpose=obs.PURPOSE_INITIATIVE_TRIGGER,
                                 probability=1.0, hit=True,
                                 reason=obs.DRAW_PROBABILITY_ONE)

    async def scenario():
        svc = await _db(tmp_path, name="probone.db")
        try:
            await _schema(svc)
            await _seed_observe_payload(
                svc, _text_payload(random_trace=trace))
            return await diag.collect_mechanism_diagnostics(svc, CHAT,
                                                            now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    draw = result["text_initiative"]["random"]
    assert draw is not None
    assert draw["performed"] is False
    assert draw["outcome"] == "no_draw"
    assert draw["no_draw_reason"] == obs.DRAW_PROBABILITY_ONE
    assert draw["hit"] is None            # «выигрыша» не было
    assert draw["value"] is None
    assert draw["draw_id"] is None
    assert draw["probability"] == 1.0
    assert draw["source"] is None         # источник не выдумывается


# ═══ 6. остаток кулдауна — свой, TTL брони не участвует ═════════════════════

def test_cooldown_remaining_uses_mechanism_cooldown_not_claim_ttl(
        tmp_path, monkeypatch):
    """6 часов своего кулдауна остаются 6 часами, а не 90/120/600 с."""
    _image_ok(monkeypatch)
    own = 6 * 3600

    async def scenario():
        svc = await _db(tmp_path, name="cooldown.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            # Последний фактический вызов провайдера мема — час назад.
            await svc.db.execute(
                "INSERT INTO meme_initiative_reservation (job_id, chat_id, "
                "day_bucket, timezone_name, timezone_source, status, "
                "error_code, created_at) VALUES (?,?,?,?,?,?,?,?)",
                ("job-p9", CHAT, "2026-11-03", "UTC", "utc_fallback",
                 "provider_called", "", NOW_TS - 3600))
            await svc.db.commit()
            coordinator = pub.PublicationCoordinator(svc)
            # Живая аренда отправки: 90 с + приоритет ручного 600 с.
            await coordinator.acquire(CHAT, pub.KIND_TEXT_INITIATIVE,
                                      now=NOW_TS - 5)
            await coordinator.claim_manual_priority(CHAT, now=NOW_TS)
            # Своя текстовая публикация 10 минут назад.
            await svc.record_bot_output(
                chat_id=CHAT, tg_message_id=900, sent_at=NOW_TS - 600,
                output_kind="initiative_reply")
            first = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=own), ledger=ledger)
            second = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=own), ledger=ledger)
            return first, second
        finally:
            await svc.close()

    first, second = asyncio.run(scenario())
    meme_block = first["meme"]
    assert meme_block["cooldown"]["own_seconds"] == own
    assert meme_block["cooldown"]["remaining_seconds"] == own - 3600
    # Ни TTL брони, ни приоритет ручного запроса не подменяют кулдаун.
    for ttl in (pub.CLAIM_TTL_SECONDS, pub.SENDING_TTL_SECONDS,
                pub.MANUAL_PRIORITY_SECONDS):
        assert meme_block["cooldown"]["remaining_seconds"] != ttl
    assert meme_block["publication"]["manual_priority_until"] == \
        NOW_TS + pub.MANUAL_PRIORITY_SECONDS

    text_block = first["text_initiative"]
    text_own = text_block["cooldown"]["own_seconds"]
    assert text_own is not None
    assert text_block["cooldown"]["remaining_seconds"] == \
        max(0, text_own - 600)
    # Приоритет ручного `/meme` (600 с) на кулдаун текста не влияет.
    assert second["text_initiative"]["cooldown"]["remaining_seconds"] == \
        text_block["cooldown"]["remaining_seconds"]


# ═══ 7. ни текстов прикола/выжимки, ни секретов ═════════════════════════════

def test_no_joke_summary_or_secret_leaks(tmp_path, monkeypatch):
    """Живой проход с «секретным» текстом: в диагностику он не попадает."""
    _image_ok(monkeypatch)
    joke_text = "СЕКРЕТ-ПРИКОЛ-777"
    summary_text = "СЕКРЕТ-ВЫЖИМКА-777"

    async def scenario():
        svc = await _db(tmp_path, name="leak.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            await _meme_pass(state, ledger=ledger, summary=summary_text,
                             joke=joke_text,
                             settings=_settings(cooldown_seconds=60))
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True,
                         "chats": state}})
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    blob = json.dumps(result, ensure_ascii=False)
    assert joke_text not in blob
    assert summary_text not in blob

    keys = _keys_of(result, skip=_OPEN_KEY_FIELDS)
    assert keys <= ALLOWED_KEYS, sorted(keys - ALLOWED_KEYS)
    assert not (keys & BANNED_KEYS), sorted(keys & BANNED_KEYS)

    # Те же правила для вложенных условий: только скаляры, строки — короткие
    # коды без пробелов (свободный текст сюда не проходит по построению).
    for name in ("text_initiative", "meme"):
        for field in ("conditions", "stages"):
            value = result[name][field]
            if not value:
                continue
            for key, item in value.items():
                assert item is None or isinstance(
                    item, (bool, int, float, str))
                if isinstance(item, str):
                    assert len(item) <= 32 and " " not in item, (key, item)


# ═══ 8. аддитивность: аналитика мемов не меняется ═══════════════════════════

def test_diagnostics_is_additive_and_does_not_mix_meme_analytics(
        tmp_path, monkeypatch):
    """Существующая аналитика цела, payload не переписывается."""
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="additive.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            await _meme_pass(state, ledger=ledger,
                             settings=_settings(cooldown_seconds=60))
            payload = {"meme": {"output_kind": meme.OUTPUT_KIND,
                                "separate_from_initiative": True,
                                "chats": state}}
            await _seed_observe_payload(svc, payload)
            analytic_before = meme.analytics_snapshot(ledger, chat_id=CHAT)
            cursor = await svc.db.execute(
                "SELECT payload FROM task_jobs WHERE kind = ?", (
                    obs.OBSERVE_JOB_KIND,))
            stored_before = (await cursor.fetchone())["payload"]
            result = await diag.collect_mechanism_diagnostics(svc, CHAT,
                                                              now=NOW_TS)
            analytic_after = meme.analytics_snapshot(ledger, chat_id=CHAT)
            cursor = await svc.db.execute(
                "SELECT payload FROM task_jobs WHERE kind = ?", (
                    obs.OBSERVE_JOB_KIND,))
            stored_after = (await cursor.fetchone())["payload"]
            return (result, analytic_before, analytic_after, stored_before,
                    stored_after)
        finally:
            await svc.close()

    result, before, after, stored_before, stored_after = asyncio.run(
        scenario())
    assert before["separate_from_initiative"] is True
    assert after["separate_from_initiative"] is True
    assert set(before.keys()) == set(after.keys())
    for key in before:
        assert type(before[key]) is type(after[key]), key
    # Диагностика — чтение: durable payload не переписывается.
    assert stored_before == stored_after
    # Блок мема не подмешивает показатели текстовой инициативы.
    assert result["meme"]["output_kind"] == meme.OUTPUT_KIND
    assert result["meme"]["output_kind"] not in obs.INITIATIVE_OUTPUT_KINDS


# ═══ 9. сборщик не бросает на сломанном источнике ═══════════════════════════

def test_collector_never_raises_on_broken_source(tmp_path):
    """Сбой чтения → честный no_data-блок, а не исключение в админку."""
    class _Broken:
        db_path = str(tmp_path / "broken.db")

        @property
        def db(self):
            raise RuntimeError("db unavailable")

        async def list_recent_bot_outputs(self, *_a, **_k):
            raise RuntimeError("db unavailable")

    result = asyncio.run(diag.collect_mechanism_diagnostics(
        _Broken(), CHAT, now=NOW_TS))
    assert result["schema_version"] == diag.DIAG_SCHEMA_VERSION
    for name in ("text_initiative", "meme"):
        block = result[name]
        assert block["available"] is False
        assert block["data_state"] == diag.DATA_NO_DATA
        assert block["last_check_ts"] is None
        assert block["no_data_reasons"]


# ═══ 10. форма блока = объявленный контракт P4 ══════════════════════════════

def test_blocks_match_documented_contract_shape(tmp_path, monkeypatch):
    """Ключи блока — ровно `MECHANISM_BLOCK_FIELDS` (P4 не угадывает поля)."""
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="shape.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            await _meme_pass(state, ledger=ledger)
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True,
                         "chats": state}})
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    for name in ("text_initiative", "meme"):
        block = result[name]
        assert set(block) == set(diag.MECHANISM_BLOCK_FIELDS), name
        assert set(block["cooldown"]) == set(diag.COOLDOWN_FIELDS), name
        assert set(block["quota"]) == set(diag.QUOTA_FIELDS), name
        publication = block["publication"]
        if publication is not None:
            assert set(publication) == set(diag.PUBLICATION_FIELDS), name
        skip = block["skip"]
        if skip is not None:
            assert set(skip) == set(diag.SKIP_FIELDS), name
            assert skip["origin"]
            assert skip["code"] in obs.REASON_LABELS, skip["code"]
    draw = result["meme"]["random"]
    assert set(draw) == set(diag.DRAW_FIELDS)


# ═══ 11. два РАЗНЫХ состояния дают разные значения (не константы) ════════════

def test_two_states_change_times_conditions_and_recorded_skip(
        tmp_path, monkeypatch):
    """Время/условия/записанная причина берутся из состояния, а не из кода."""
    _image_ok(monkeypatch)
    first_ts = NOW_TS - 3600
    second_ts = NOW_TS - 60

    async def scenario():
        svc = await _db(tmp_path, name="two_states.db")
        try:
            await _schema(svc)
            await _seed_observe_payload(svc, _text_payload(
                skip_reason="eval_not_due", conditions={"evaluated": True},
                now_override=first_ts, eval_ts=first_ts))
            first = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            await _seed_observe_payload(svc, _text_payload(
                skip_reason="not_enough_messages",
                conditions={"evaluated": False, "pending": 3},
                now_override=second_ts, eval_ts=second_ts))
            second = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return first["text_initiative"], second["text_initiative"]
        finally:
            await svc.close()

    text_first, text_second = asyncio.run(scenario())
    assert text_first["last_check_ts"] == first_ts
    assert text_second["last_check_ts"] == second_ts
    assert text_first["last_check_ts"] != text_second["last_check_ts"]
    assert text_first["conditions"] != text_second["conditions"]
    assert text_first["skip_recorded"]["code"] == "eval_not_due"
    assert text_second["skip_recorded"]["code"] == "not_enough_messages"
    # Следующая проверка считается из состояния: та же пауза профиля, сдвиг
    # ровно на разницу состояний (не константа и не «сейчас»).
    assert text_first["next_check_ts"] is not None
    assert text_second["next_check_ts"] is not None
    assert (text_second["next_check_ts"] - text_first["next_check_ts"]
            == second_ts - first_ts)


# ═══ 12. причина пропуска включает СВОЙ кулдаун и квоту механизма ══════════

def test_current_skip_reports_own_cooldown_and_quota(tmp_path, monkeypatch):
    """Мем в паузе/на квоте: причина видна сразу, без ожидания прохода."""
    _image_ok(monkeypatch)
    own = 6 * 3600

    async def scenario():
        svc = await _db(tmp_path, name="skip_now.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            await svc.db.execute(
                "INSERT INTO meme_initiative_reservation (job_id, chat_id, "
                "day_bucket, timezone_name, timezone_source, status, "
                "error_code, created_at) VALUES (?,?,?,?,?,?,?,?)",
                ("job-skip", CHAT, "2026-11-03", "UTC", "utc_fallback",
                 "provider_called", "", NOW_TS - 600))
            await svc.db.commit()
            cooling = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=own, daily_limit=5),
                ledger=ledger)
            # Тот же чат, но лимит суток уже исчерпан (лимит 1, потрачено 1).
            quota_hit = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=0, daily_limit=1),
                ledger=ledger)
            return cooling["meme"], quota_hit["meme"]
        finally:
            await svc.close()

    cooling, quota_hit = asyncio.run(scenario())
    # Свой кулдаун: причина — существующий код механизма, а не TTL брони.
    assert cooling["skip"]["code"] == meme.SKIP_COOLDOWN
    assert cooling["skip"]["label"] == obs.reason_label(meme.SKIP_COOLDOWN)
    assert cooling["skip"]["origin"] == "cooldown"
    assert cooling["cooldown"]["remaining_seconds"] == own - 600
    # Квота суток исчерпана — своя причина, кулдаун при этом нулевой.
    assert quota_hit["quota"]["limit_reached"] is True
    assert quota_hit["skip"]["code"] == meme.SKIP_QUOTA
    assert quota_hit["skip"]["origin"] == "quota"
    assert quota_hit["cooldown"]["remaining_seconds"] == 0
    # Оба кода — из общего словаря причин (новых кодов не вводим).
    for block in (cooling, quota_hit):
        assert block["skip"]["code"] in obs.REASON_LABELS


# ═══ 13. нулевой лимит: у мема предел, у текста «без капа» ══════════════════

def test_zero_limit_semantics_differ_per_mechanism(tmp_path, monkeypatch):
    """`daily_limit=0` у мемов — стоп, `day_cap<=0` у текста — без капа."""
    _image_ok(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="zero_limit.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=0, daily_limit=0))
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    meme_quota = result["meme"]["quota"]
    assert meme_quota["limit"] == 0
    assert meme_quota["limit_reached"] is True
    assert meme_quota["unlimited"] is False
    assert result["meme"]["skip"]["code"] == meme.SKIP_QUOTA
    # Текстовая инициатива: cap<=0 — «без дневного капа» (паритет гейта
    # `day_cap <= 0 or sent < day_cap`), поэтому та же функция даёт другое.
    text_quota = diag.quota_block(limit=0, used=2, zero_means_unlimited=True)
    assert text_quota["unlimited"] is True
    assert text_quota["limit_reached"] is False
    assert text_quota["remaining"] == 0
    # И наоборот: для мемов тот же вход — предел.
    meme_zero = diag.quota_block(limit=0, used=2, zero_means_unlimited=False)
    assert meme_zero["unlimited"] is False
    assert meme_zero["limit_reached"] is True


# ═══ 14. без выбранного чата — «нет данных», а не исключение ════════════════

def test_missing_chat_yields_no_data_blocks(tmp_path):
    """chat_id=None: обе части честно пустые, сборщик не бросает."""

    async def scenario():
        svc = await _db(tmp_path, name="nochat.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(svc, None,
                                                            now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    assert result["chat_id"] is None
    assert result["degraded"] == []
    for name in ("text_initiative", "meme"):
        block = result[name]
        assert block["available"] is False
        assert block["data_state"] == diag.DATA_NO_DATA
        assert block["no_data_reasons"] == [diag.NO_DATA_CHAT_REQUIRED]
        assert block["last_check_ts"] is None
        assert block["random"] is None
        assert block["cooldown"]["remaining_seconds"] is None
        assert block["quota"]["limit"] is None
    assert result["text_initiative"]["output_kind"] != \
        result["meme"]["output_kind"]


# ═══ 15. F1(a): тумблер инициативы в чате выключен ═════════════════════════

def test_chat_toggle_off_is_reported_as_initiative_disabled(tmp_path,
                                                           monkeypatch):
    """Живой проход отказывает `initiative_disabled` — блок говорит то же.

    Гейт спрашивается через ТОТ ЖЕ шов, что у боевого прохода
    (`InitiativeObserverRunner._meme_phase` передаёт
    `initiative_observer.chat_observer_enabled`), поэтому обе стороны видят
    одно состояние чата.
    """
    _image_ok(monkeypatch)

    async def chat_off(_chat_id):
        return False

    monkeypatch.setattr(obs, "chat_observer_enabled", chat_off)

    async def scenario():
        svc = await _db(tmp_path, name="chat_off.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            live = (await _meme_pass(
                state, ledger=ledger,
                chat_enabled=obs.chat_observer_enabled))[0]
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True,
                         "chats": state}})
            return live, await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS, meme_settings=_settings())
        finally:
            await svc.close()

    live, result = asyncio.run(scenario())
    # Живой путь: публикации нет, причина — выключенная инициатива.
    assert live.stage == meme.STAGE_SKIPPED
    assert live.reason == meme.SKIP_INITIATIVE_DISABLED

    meme_block = result["meme"]
    # Диагностика в ТОМ ЖЕ состоянии не выдаёт «готов».
    assert meme_block["ready"] is False
    assert meme_block["skip"]["code"] == meme.SKIP_INITIATIVE_DISABLED
    assert meme_block["skip"]["code"] == live.reason
    assert meme_block["skip"]["origin"] == "availability"
    assert meme_block["conditions"]["initiative_enabled"] is False
    assert meme_block["ready_reason"] == meme.SKIP_INITIATIVE_DISABLED
    # Записанная причина прошедшего прохода — тот же код, что и текущая.
    assert meme_block["skip_recorded"]["code"] == meme.SKIP_INITIATIVE_DISABLED
    # Текстовая инициатива в этом же чате тоже не готова (оба блока честны).
    assert result["text_initiative"]["ready"] is False
    assert result["text_initiative"]["skip"] is not None


# ═══ 16. F1(b): таблицы брони нет — боевой `schema_absent` ══════════════════

def test_missing_claim_table_is_reported_as_schema_absent(tmp_path,
                                                         monkeypatch):
    """Нет таблицы брони: мем физически не публикуется — блок не пишет «готов»."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="no_claim.db")
        try:
            await _schema(svc)
            await _drop_claim_table(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            live = (await _meme_pass(state, ledger=ledger,
                                     settings=_settings()))[0]
            return live, await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS, meme_settings=_settings())
        finally:
            await svc.close()

    live, result = asyncio.run(scenario())
    # Живой проход останавливается на отсутствии брони (не «на удачу»).
    assert live.stage == meme.STAGE_SKIPPED
    assert live.reason == meme.SKIP_SCHEMA
    assert live.detail == "publish_claim_absent"

    meme_block = result["meme"]
    assert meme_block["ready"] is False
    assert meme_block["skip"]["code"] == meme.SKIP_SCHEMA
    assert meme_block["skip"]["code"] == live.reason
    assert meme_block["skip"]["origin"] == "publication"
    # Деградация остаётся деградацией: конфликт НЕИЗВЕСТЕН, а не «нет».
    assert meme_block["publication"]["degraded"] is True
    assert meme_block["publication"]["conflict"] is None
    assert meme_block["publication"]["conflict_state"] == diag.CONFLICT_UNKNOWN
    # И ни один блок не заявляет готовность рядом с причиной пропуска.
    for name in ("text_initiative", "meme"):
        assert not (result[name]["ready"] is True
                    and result[name]["skip"] is not None), name


# ═══ 17. F1(c): кулдаун — `ready=false`, а не «готов И причина пропуска» ═══

def test_cooldown_state_never_claims_ready_and_skip_together(tmp_path,
                                                             monkeypatch):
    """Два поля одного блока не противоречат: `ready` считается ПОСЛЕ `skip`."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    own = 3600

    async def scenario():
        svc = await _db(tmp_path, name="cooldown_only.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            # Свободный чат: ни кулдауна, ни квоты — механизм реально готов.
            free = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=own), ledger=ledger)
            # Тот же чат, но вызов провайдера был минуту назад → своя пауза.
            await svc.db.execute(
                "INSERT INTO meme_initiative_reservation (job_id, chat_id, "
                "day_bucket, timezone_name, timezone_source, status, "
                "error_code, created_at) VALUES (?,?,?,?,?,?,?,?)",
                ("job-ready", CHAT, "2026-11-03", "UTC", "utc_fallback",
                 "provider_called", "", NOW_TS - 60))
            await svc.db.commit()
            cooling = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS,
                meme_settings=_settings(cooldown_seconds=own), ledger=ledger)
            return free["meme"], cooling["meme"]
        finally:
            await svc.close()

    free, cooling = asyncio.run(scenario())
    # Свободное состояние: готовность правда, причины пропуска нет.
    assert free["ready"] is True
    assert free["skip"] is None
    assert free["ready_reason"] == ""
    # Кулдаун: причина есть — и «готов» рядом с ней уже не появится.
    assert cooling["skip"]["code"] == meme.SKIP_COOLDOWN
    assert cooling["skip"]["origin"] == "cooldown"
    assert cooling["cooldown"]["remaining_seconds"] == own - 60
    assert cooling["ready"] is False
    assert cooling["ready_reason"] == meme.SKIP_COOLDOWN
    assert not (cooling["ready"] is True and cooling["skip"] is not None)


# ═══ 18. F2: «следующая проверка» не может быть раньше «последней» ═════════

def test_next_check_is_never_before_last_check(tmp_path, monkeypatch):
    """Один базис времени: решение записано «сейчас», оценка была 2 ч назад."""
    _image_ok(monkeypatch)
    stale_eval = NOW_TS - 7200

    async def scenario():
        svc = await _db(tmp_path, name="next_check.db")
        try:
            await _schema(svc)
            # Так пишет сам наблюдатель на гейтах и на промахе draw: решение
            # фиксируется на КАЖДОМ проходе, `last_eval_ts` — только оценки.
            await _seed_observe_payload(svc, _text_payload(
                eval_ts=stale_eval, now_override=NOW_TS,
                skip_reason="eval_not_due", conditions={"evaluated": False}))
            stale = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            # Обычное состояние: оценка и решение — один и тот же проход.
            await _seed_observe_payload(svc, _text_payload(
                eval_ts=NOW_TS - 3600, now_override=NOW_TS - 3600,
                skip_reason="not_enough_messages"))
            normal = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return stale["text_initiative"], normal["text_initiative"]
        finally:
            await svc.close()

    stale, normal = asyncio.run(scenario())
    # Последняя проверка — время записанного решения (каждый проход).
    assert stale["last_check_ts"] == NOW_TS
    # Расчётная дата оценки (last_eval + интервал) уже в прошлом к моменту
    # последней проверки → дата не выдаётся; честно «на ближайшем проходе».
    assert stale["next_check_ts"] is None
    assert stale["next_check_basis"] == "every_pass"

    # Обычное состояние: дата есть, она ПОЗЖЕ последней проверки.
    assert normal["next_check_ts"] is not None
    assert normal["next_check_basis"] == "eval_interval"
    assert normal["next_check_ts"] > normal["last_check_ts"]

    # Инвариант для любого состояния и любого механизма: `next` не раньше
    # `last` (иначе в админке была бы «следующая проверка: прошедшая дата»).
    for block in (stale, normal):
        if block["next_check_ts"] is not None:
            assert block["last_check_ts"] is not None, block["mechanism"]
            assert block["next_check_ts"] >= block["last_check_ts"], \
                block["mechanism"]

