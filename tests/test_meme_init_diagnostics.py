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
    # P0 corrective §1: пять независимых осей и их вложенные формы.
    | set(diag.CONFIGURATION_FIELDS)
    | set(diag.HEALTH_FIELDS)
    | set(diag.DEPENDENCY_FIELDS)
    | set(diag.READINESS_FIELDS)
    | set(diag.LAST_ATTEMPT_FIELDS)
    | set(diag.LAST_DELIVERY_FIELDS)
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
                     summary="хук", joke="прикол", chat_enabled=None,
                     random_source=None, db=None):
    """Один проход мема на реальном журнале (payload через `_note_state`).

    ``chat_enabled`` — тот же шов, что у боевого прохода
    (`InitiativeObserverRunner._meme_phase` передаёт
    `initiative_observer.chat_observer_enabled`). ``db`` — реальная БД: нужна
    там, где проверяется запись доставки в `mca_bot_outputs`/`task_jobs`.
    """
    async def summarizer(_cid, _rows_arg, _system):
        return summary

    async def joke_generator(_cid, _summary, _instruction):
        return joke

    async def gate(_cid):
        return True, "ok"

    return await meme.on_initiative_cycle(
        db, [CHAT], state=state,
        settings=settings if settings is not None else _settings(),
        ledger=ledger, now=NOW, now_ts=NOW_TS, tz_name="UTC",
        tz_source="utc_fallback", initiative_enabled=lambda: True,
        chat_enabled=chat_enabled,
        image_status=IMAGE_OK,
        random_source=random_source if random_source is not None else _Hit(),
        messages=_rows(CHAT),
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


# ═════════════════════════════════════════════════════════════════════════════
# P0-INIT-MEME-UX-DIAG §1 — пять НЕЗАВИСИМЫХ осей
# ═════════════════════════════════════════════════════════════════════════════
# TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-11-P0-INIT-MEME-UX-DIAG
# (§1/§2: оси, запрет ready=false→enabled=false, запрет выдуманного ETA).


def _chat_capability(monkeypatch, *, on=True, source="global"):
    """Тумблер чата через ЕДИНЫЙ резолвер (тот же шов, что у боевого пути).

    Подменяется внешняя граница `chat_params` (PG-профиль), а не предмет
    проверки: ось configuration обязана читать `source`/`effective_runtime`
    этого резолвера, а не угадывать по косвенным флагам.
    """
    state = SimpleNamespace(
        capability="initiative", key="initiative.enabled", domain="override",
        chat_id=CHAT, chat_state="on" if source == "chat" else "inherit",
        desired=on, source=source, global_value=True, global_source="hot",
        emergency_block=False, effective_runtime=on, ready=None, reason_code=None)

    async def _state(chat_id, *, fresh=False):
        return state

    monkeypatch.setattr(obs, "chat_capability_state", _state)
    return state


def _axes(block: dict) -> dict:
    """Пять осей блока механизма (форма контракта, не пересчёт)."""
    return {name: block[name] for name in diag.AXIS_FIELDS}


def _meme_settings_on(monkeypatch, **overrides):
    """Настройки мемов для витрины через ТОТ ЖЕ `load_settings`.

    Подменяется внешняя граница (PG/hot-конфиг), а не предмет проверки:
    диагностика обязана читать те же `MemeSettings`, что и боевой путь.
    """
    cfg = _settings(**overrides)

    async def _load(_chat_id=None):
        return cfg

    monkeypatch.setattr(meme, "load_settings", _load)
    return cfg


async def _meme_pass_db(svc, state, *, ledger, sender=None, settings=None):
    """Проход мема с РЕАЛЬНОЙ БД: нужен для записи доставки в ledger выводов."""
    return await _meme_pass(state, ledger=ledger, db=svc, sender=sender,
                            settings=settings)


# ── configuration ──────────────────────────────────────────────────────────

def test_axis_configuration_stays_on_while_cooldown_blocks(
        tmp_path, monkeypatch):
    """Кулдаун НЕ выключает механизм: enabled=true + readiness=waiting.

    Это главный запрет §2: «сейчас нельзя» ≠ «выключено».
    """
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch, cooldown_seconds=600)

    async def scenario():
        svc = await _db(tmp_path, name="axis_cooldown.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            first = (await _meme_pass(
                state, ledger=ledger,
                settings=_settings(cooldown_seconds=600)))[0]
            second = (await _meme_pass(
                state, ledger=ledger,
                settings=_settings(cooldown_seconds=600)))[0]
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            return first, second, await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    first, second, result = asyncio.run(scenario())
    assert first.published is True              # первый проход отправил
    assert second.reason == meme.SKIP_COOLDOWN  # второй отказал по кулдауну
    block = result["meme"]
    # Источник — явное разрешение настройками, и оно НЕ выключено кулдауном.
    assert block["configuration"]["enabled"] is True, block["configuration"]
    assert block["configuration"]["reason"] == ""
    # Разрешающий слой — чат (настройки мема), а не «global»: иначе два чата с
    # разными настройками выглядели бы одинаково.
    assert block["configuration"]["source"] == "meme_settings"
    assert block["configuration"]["scope"] == "mixed"
    assert block["readiness"]["state"] == "waiting", block["readiness"]
    assert block["readiness"]["reason"] == meme.SKIP_COOLDOWN
    assert block["readiness"]["reason_class"] == "cooldown"
    # Время — из уже посчитанного факта: last_provider_ts + cooldown_seconds.
    assert block["readiness"]["next_eligible_at"] == NOW_TS + 600
    assert block["readiness"]["next_basis"] == "cooldown"
    # Старая ось не перегружена: `ready` по-прежнему про «можно сейчас».
    assert block["ready"] is False


def test_axis_configuration_false_only_from_explicit_setting(
        tmp_path, monkeypatch):
    """Явный OFF настройки мема — единственный путь к enabled=false."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch, enabled=False)

    async def scenario():
        svc = await _db(tmp_path, name="axis_off.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            await _meme_pass(state, ledger=ledger,
                             settings=_settings(enabled=False))
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    block = asyncio.run(scenario())["meme"]
    assert block["configuration"]["enabled"] is False
    assert block["configuration"]["source"] == "meme_settings"
    assert block["configuration"]["scope"] == "chat"
    assert block["configuration"]["reason"] == meme.SKIP_DISABLED
    assert block["readiness"]["state"] == "blocked"
    assert block["readiness"]["reason_class"] == "disabled"


def test_axis_configuration_is_null_when_gate_is_unreadable(
        tmp_path, monkeypatch):
    """Сбой чтения оси — «неизвестно», а НЕ «выключено» (§1/§2)."""
    _image_ok(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    def _boom():
        raise RuntimeError("hot config unavailable")

    monkeypatch.setattr(obs, "observer_enabled", _boom)

    async def scenario():
        svc = await _db(tmp_path, name="axis_unknown.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            await _meme_pass(state, ledger=ledger)
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    block = asyncio.run(scenario())["meme"]
    assert block["configuration"]["enabled"] is None
    assert block["configuration"]["source"] == "read_failed"
    assert block["configuration"]["reason"]
    assert block["readiness"]["state"] != "blocked"


# ── health ─────────────────────────────────────────────────────────────────

def test_axis_health_degraded_coordination_is_not_ok(tmp_path, monkeypatch):
    """Нет таблицы брони: health=degraded, а не «конфликта нет»."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_health.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            await _meme_pass(state, ledger=ledger)
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            healthy = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            await _drop_claim_table(svc)
            degraded = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return healthy["meme"], degraded["meme"]
        finally:
            await svc.close()

    healthy, degraded = asyncio.run(scenario())
    assert healthy["health"]["state"] == diag.HEALTH_OK
    deps = {item["name"]: item for item in healthy["health"]["dependencies"]}
    assert deps["attempt_journal"]["state"] == diag.HEALTH_OK
    assert deps["publication_precheck"]["state"] == diag.HEALTH_OK
    assert deps["image"]["state"] == diag.HEALTH_OK
    assert deps["image"]["source"] == "meme_initiative.image_dependency"

    assert degraded["health"]["state"] == diag.HEALTH_DEGRADED
    deps = {item["name"]: item for item in degraded["health"]["dependencies"]}
    assert deps["publication_precheck"]["state"] == diag.HEALTH_DEGRADED
    assert deps["publication_precheck"]["source"] == \
        "PublicationCoordinator.precheck"


def test_axis_health_error_when_attempt_journal_is_absent(tmp_path, monkeypatch):
    """Нет журнала попыток: health=error (жёсткая неисправность, не ожидание)."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_journal.db")
        try:
            await _schema(svc)
            state: dict = {}
            await _meme_pass(state, ledger=_ledger_at(tmp_path, "meme.db"))
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            # Журнал другой (пустой) БД: таблицы попыток в нём нет.
            empty = meme.SqliteQuotaLedger(str(tmp_path / "empty.db"))
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS, ledger=empty)
        finally:
            await svc.close()

    block = asyncio.run(scenario())["meme"]
    assert block["health"]["state"] == diag.HEALTH_ERROR
    deps = {item["name"]: item for item in block["health"]["dependencies"]}
    assert deps["attempt_journal"]["state"] == diag.HEALTH_ERROR
    assert block["readiness"]["state"] == "blocked"
    assert block["readiness"]["reason_class"] == "schema"


def _ledger_at(tmp_path, name: str):
    led = meme.SqliteQuotaLedger(str(tmp_path / name))
    led.apply_schema()
    return led


# ── readiness: доказанное время, busy, просроченный маркер ─────────────────

def test_axis_readiness_has_no_invented_eta_after_lottery_miss(
        tmp_path, monkeypatch):
    """Промах жребия: время следующей попытки НЕ выдумывается (null)."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    class _Miss:
        async def draw_probability(self, **_kwargs):
            return mrs.DrawResult(value=0.99, source="pseudorandom",
                                  selected_source="quantum", provider=None,
                                  draw_id="draw-miss")

    async def scenario():
        svc = await _db(tmp_path, name="axis_lottery.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            result = (await _meme_pass(
                state, ledger=ledger,
                settings=_settings(trigger_probability=0.01),
                random_source=_Miss()))[0]
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            return result, await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    result, result_diag = asyncio.run(scenario())
    assert result.reason == meme.SKIP_RANDOM_MISS
    block = result_diag["meme"]
    assert block["configuration"]["enabled"] is True
    # Промах жребия — исход ПОПЫТКИ, а не текущий запрет: механизм можно
    # рассматривать на следующем проходе, «выключенным» он не становится.
    assert block["readiness"]["state"] == "ready", block["readiness"]
    assert block["readiness"]["state"] != "blocked"
    # Никакого «последняя проверка + период»: базиса нет — времени нет.
    assert block["readiness"]["next_eligible_at"] is None
    assert block["readiness"]["next_basis"] == "none"
    # Причина промаха честно видна как РЕЗУЛЬТАТ попытки/запись прохода.
    assert block["last_attempt"]["outcome"] == "skipped"
    assert block["last_attempt"]["stop_stage"] == meme.STAGE_SKIPPED
    assert block["skip_recorded"]["code"] == meme.SKIP_RANDOM_MISS


def test_axis_readiness_busy_on_live_claim_and_not_busy_when_expired(
        tmp_path, monkeypatch):
    """Живая бронь = busy; просроченная — не ожидание (§1/§2)."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_busy.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            store = pub.SqliteClaimStore(str(svc.db_path))
            decision = store.acquire(chat_id=CHAT,
                                     holder_kind=pub.KIND_TEXT_INITIATIVE,
                                     now=NOW_TS)
            assert decision.granted
            live = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            expired = await diag.collect_mechanism_diagnostics(
                svc, CHAT,
                now=NOW_TS + int(pub.CLAIM_TTL_SECONDS) + 60)
            _ = ledger
            return live["meme"], expired["meme"]
        finally:
            await svc.close()

    live, expired = asyncio.run(scenario())
    assert live["readiness"]["state"] == "busy", live["readiness"]
    assert live["readiness"]["reason_class"] == "busy"
    assert expired["readiness"]["state"] != "busy", expired["readiness"]
    assert expired["configuration"]["enabled"] is not False


def test_axis_expired_manual_priority_is_not_a_current_block(
        tmp_path, monkeypatch):
    """Истёкший `manual_priority_until` — «истёк», а не текущий блок."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_manual.db")
        try:
            await _schema(svc)
            store = pub.SqliteClaimStore(str(svc.db_path))
            # Маркер поставлен 1000 с назад с TTL 600 с → он уже истёк.
            store.claim_manual_priority(chat_id=CHAT, now=NOW_TS - 1000,
                                        ttl=600)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    block = asyncio.run(scenario())["meme"]
    publication = block["publication"]
    assert publication["manual_priority_until"] == NOW_TS - 400
    assert publication["manual_priority_active"] is False
    assert publication["manual_priority_expired"] is True
    # Просроченный маркер не превращается в причину ожидания или блокировки.
    assert block["readiness"]["state"] != "blocked"
    assert block["readiness"]["reason_class"] != "manual_priority"
    assert block["readiness"]["next_basis"] != "manual_priority_until"


def test_axis_live_manual_priority_waits_with_proven_basis(tmp_path, monkeypatch):
    """Живой маркер — waiting/manual_priority с временем ИЗ САМОГО маркера."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_manual_live.db")
        try:
            await _schema(svc)
            store = pub.SqliteClaimStore(str(svc.db_path))
            store.claim_manual_priority(chat_id=CHAT, now=NOW_TS - 10,
                                        ttl=600)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    block = asyncio.run(scenario())["meme"]
    assert block["publication"]["manual_priority_active"] is True
    assert block["publication"]["manual_priority_expired"] is False
    assert block["readiness"]["state"] == "waiting"
    assert block["readiness"]["reason_class"] == "manual_priority"
    assert block["readiness"]["next_eligible_at"] == NOW_TS + 590
    assert block["readiness"]["next_basis"] == "manual_priority_until"


# ── last_attempt / last_delivery ───────────────────────────────────────────

def test_axis_last_attempt_is_one_attempt_with_mode_and_stage(
        tmp_path, monkeypatch):
    """`last_attempt` — одна ПОПЫТКА: run_id, режим, исход, место остановки."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_attempt.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            result = (await _meme_pass(
                state, ledger=ledger,
                settings=_settings(cooldown_seconds=600)))[0]
            # Второй проход — ранний отказ по квоте (daily_limit=0), тоже попытка.
            second = (await _meme_pass(
                state, ledger=ledger,
                settings=_settings(cooldown_seconds=600,
                                   daily_limit=0)))[0]
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            rows = ledger.attempts(CHAT, limit=100)
            return result, second, rows, await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    first, second, rows, result = asyncio.run(scenario())
    assert first.published is True
    assert second.reason == meme.SKIP_QUOTA
    block = result["meme"]
    attempt = block["last_attempt"]
    assert set(attempt) == set(diag.LAST_ATTEMPT_FIELDS)
    # Ранний отказ по квоте — ОДНА попытка со своим непустым run_id и режимом.
    assert attempt["run_id"] == second.job_id
    assert attempt["run_id"]
    assert attempt["mode"] == diag.MODE_AUTO
    assert attempt["outcome"] == "skipped"
    assert attempt["stop_stage"] == meme.STAGE_SKIPPED
    assert attempt["incomplete_historical"] is False
    # Один job_id — одна группа строк журнала (§3: не две «попытки»).
    group = [row for row in rows if str(row.get("job_id")) == attempt["run_id"]]
    assert group, [row.get("job_id") for row in rows]
    assert {str(row.get("job_id")) for row in rows} == {
        attempt["run_id"], first.job_id} - {""}


def test_axis_last_delivery_confirmed_only_with_message_id(
        tmp_path, monkeypatch):
    """Доставка подтверждается ТОЛЬКО записью с `message_id`."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_delivery.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            state: dict = {}
            empty = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            await _meme_pass_db(svc, state, ledger=ledger,
                                sender=_Sender(message_id=None))
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            unknown = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            await _meme_pass_db(svc, state, ledger=ledger,
                                sender=_Sender(message_id=4242))
            await _seed_observe_payload(svc, {
                "meme": {"output_kind": meme.OUTPUT_KIND,
                         "separate_from_initiative": True, "chats": state}})
            confirmed = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return (empty["meme"], unknown["meme"], confirmed["meme"])
        finally:
            await svc.close()

    empty, unknown, confirmed = asyncio.run(scenario())
    assert empty["last_delivery"]["status"] == diag.DELIVERY_NEVER
    assert empty["last_delivery"]["message_id"] is None
    # Отправка без id — «неизвестно», а не «доставлено».
    assert unknown["last_delivery"]["status"] == diag.DELIVERY_UNKNOWN
    assert unknown["last_delivery"]["message_id"] is None
    assert confirmed["last_delivery"]["status"] == diag.DELIVERY_CONFIRMED
    assert confirmed["last_delivery"]["message_id"] == 4242
    assert confirmed["last_delivery"]["destination"] == CHAT
    assert confirmed["last_delivery"]["at"] == NOW_TS


def test_axes_never_mix_mechanisms_and_payload_carries_chat(
        tmp_path, monkeypatch):
    """Ответ адресован ОДНОМУ чату; оси механизмов не смешиваются."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="axis_scope.db")
        try:
            await _schema(svc)
            ledger = meme.SqliteQuotaLedger(str(svc.db_path))
            meme_state: dict = {}
            await _meme_pass(meme_state, ledger=ledger)
            await _seed_observe_payload(svc, _text_payload(
                skip_reason="not_enough_messages"))
            # Тексту нужен свой entry в payload: тот же `chats`, другой механизм.
            payload = _text_payload(skip_reason="not_enough_messages")
            payload["meme"] = {"output_kind": meme.OUTPUT_KIND,
                               "separate_from_initiative": True,
                               "chats": meme_state}
            await _seed_observe_payload(svc, payload)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    assert result["chat_id"] == CHAT
    text_block, meme_block = result["text_initiative"], result["meme"]
    assert set(_axes(text_block)) == set(diag.AXIS_FIELDS)
    assert set(_axes(meme_block)) == set(diag.AXIS_FIELDS)
    assert text_block["output_kind"] != meme_block["output_kind"]
    # Оси выведены из СВОИХ источников: у мема есть журнал, у текста нет.
    assert {item["name"] for item in meme_block["health"]["dependencies"]} == {
        "attempt_journal", "publication_precheck", "image"}
    assert {item["name"] for item in text_block["health"]["dependencies"]} == {
        "event_log", "publication_precheck"}


# ═════════════════════════════════════════════════════════════════════════════
# Ревью 400021cc — шесть блокеров (каждый = реальная ложь витрины)
# ═════════════════════════════════════════════════════════════════════════════
# TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-11-P0-INIT-MEME-UX-DIAG


def _insert_output(svc, *, chat_id, message_id, sent_at, kind="meme_initiative",
                   correlation=""):
    """Строка существующего журнала выводов (без новых таблиц)."""
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(str(svc.db_path))
    try:
        conn.execute(
            "INSERT INTO mca_bot_outputs (chat_id, tg_message_id, sent_at,"
            " output_kind, correlation_id, delivery_status, created_at)"
            " VALUES (?,?,?,?,?,'delivered',?)",
            (int(chat_id), message_id, int(sent_at), kind, correlation,
             int(sent_at)))
        conn.commit()
    finally:
        conn.close()


# ── блокер 1: подтверждённая доставка не теряется ──────────────────────────

def test_confirmed_delivery_is_not_erased_by_a_newer_idless_row(
        tmp_path, monkeypatch):
    """Строка с `tg_message_id` остаётся подтверждением даже под новой без id."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="delivery_lost.db")
        try:
            await _schema(svc)
            empty = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            _insert_output(svc, chat_id=CHAT, message_id=777,
                           sent_at=NOW_TS - 100, correlation="run-777")
            with_id = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            # Более НОВАЯ запись без id (send без message_id) — как в бою.
            _insert_output(svc, chat_id=CHAT, message_id=None,
                           sent_at=NOW_TS - 10, correlation="run-noid")
            after = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return (empty["meme"]["last_delivery"],
                    with_id["meme"]["last_delivery"],
                    after["meme"]["last_delivery"])
        finally:
            await svc.close()

    empty, with_id, after = asyncio.run(scenario())
    # «Ни одной записи» — never.
    assert empty["status"] == diag.DELIVERY_NEVER
    assert with_id["status"] == diag.DELIVERY_CONFIRMED
    assert with_id["message_id"] == 777
    # Подтверждённая доставка НЕ стирается новой записью без id.
    assert after["status"] == diag.DELIVERY_CONFIRMED, after
    assert after["message_id"] == 777
    assert after["at"] == NOW_TS - 100
    assert after["run_id"] == "run-777"


def test_only_idless_sends_are_unknown_not_never(tmp_path, monkeypatch):
    """Журнал есть, id нет ни у одной строки — `unknown`, а не `never`."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="delivery_noid.db")
        try:
            await _schema(svc)
            _insert_output(svc, chat_id=CHAT, message_id=None,
                           sent_at=NOW_TS - 5)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    delivery = asyncio.run(scenario())["meme"]["last_delivery"]
    assert delivery["status"] == diag.DELIVERY_UNKNOWN
    assert delivery["message_id"] is None


# ── блокер 2: исключение precheck ≠ отсутствие таблицы ─────────────────────

def test_precheck_exception_is_unknown_not_missing_schema(tmp_path, monkeypatch):
    """Сбой чтения брони: health/readiness = unknown, БЕЗ выдуманной причины."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)
    _meme_settings_on(monkeypatch)

    async def boom(*_a, **_k):
        raise RuntimeError("claim store exploded")

    monkeypatch.setattr(diag, "_meme_precheck", boom)

    async def scenario():
        svc = await _db(tmp_path, name="precheck_boom.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    block = result["meme"]
    publication = block["publication"]
    assert publication["coordination"] == diag.COORDINATION_UNKNOWN
    assert publication["degraded"] is False
    assert publication["degraded_reason"] == ""
    assert publication["available"] is False
    assert publication["conflict"] is None
    deps = {item["name"]: item for item in block["health"]["dependencies"]}
    assert deps["publication_precheck"]["state"] == diag.HEALTH_UNKNOWN
    # Главное: НЕ schema_absent и НЕ blocked по выдуманной причине.
    assert block["skip"] is None or block["skip"]["code"] != "schema_absent"
    assert block["readiness"]["state"] == "unknown", block["readiness"]
    assert block["readiness"]["reason"] != "schema_absent"
    # Механизм при этом не объявлен выключенным.
    assert block["configuration"]["enabled"] is True
    assert result["degraded"] == []


# ── блокер 3: чатовый слой разрешения назван честно ────────────────────────

def test_configuration_names_chat_layer_instead_of_global(tmp_path, monkeypatch):
    """Разные чатовые настройки различимы: source/scope указывают на чат."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _chat_capability(monkeypatch)

    async def scenario():
        svc = await _db(tmp_path, name="config_chat.db")
        try:
            await _schema(svc)
            sourced = []
            for enabled in (True, False):
                cfg = _settings(enabled=enabled)

                async def _load(_chat_id=None, _cfg=cfg):
                    return _cfg

                monkeypatch.setattr(meme, "load_settings", _load)
                block = (await diag.collect_mechanism_diagnostics(
                    svc, CHAT, now=NOW_TS))["meme"]
                sourced.append(block["configuration"])
            return sourced
        finally:
            await svc.close()

    on, off = asyncio.run(scenario())
    # Разрешено: разрешающий слой — ЧАТ (настройки мема), не «global».
    assert on["enabled"] is True
    assert on["source"] == "meme_settings"
    assert on["scope"] == "mixed"
    # Явный OFF в чате — тоже чатовый слой и причина.
    assert off["enabled"] is False
    assert off["source"] == "meme_settings"
    assert off["scope"] == "chat"
    assert off["reason"] == meme.SKIP_DISABLED


def test_configuration_chat_override_is_named_as_chat(tmp_path, monkeypatch):
    """Явный выбор чата (тумблер) — source=chat, а не «global»."""
    _image_ok(monkeypatch)
    _gates_on(monkeypatch)
    _meme_settings_on(monkeypatch)
    _chat_capability(monkeypatch, on=True, source="chat")

    async def scenario():
        svc = await _db(tmp_path, name="config_override.db")
        try:
            await _schema(svc)
            return await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
        finally:
            await svc.close()

    configuration = asyncio.run(scenario())["meme"]["configuration"]
    assert configuration["enabled"] is True
    assert configuration["source"] == "chat"
    assert configuration["scope"] == "mixed"


# ── блокер 5: идентичность ТЕКСТОВОЙ попытки (ранний отказ) ────────────────

def _text_runner(svc):
    """Реальный раннер с DI-полями (как в соседних тестах наблюдения)."""
    runner = obs.InitiativeObserverRunner.__new__(obs.InitiativeObserverRunner)
    runner._db = svc
    runner._bot = None
    runner._llm = None
    runner._writer = None
    runner._aliases = None
    runner._publication = None
    runner._trigger = "schedule"
    return runner


def test_text_early_refusal_has_per_chat_run_id(tmp_path, monkeypatch):
    """Отказ на ПЕРВОМ гейте текста несёт родителя попытки ЧАТА (§3)."""
    _image_ok(monkeypatch)
    monkeypatch.setattr(obs, "observer_enabled", lambda: True)

    async def chat_off(_chat_id):
        return False

    monkeypatch.setattr(obs, "chat_observer_enabled", chat_off)

    async def scenario():
        svc = await _db(tmp_path, name="text_run.db")
        try:
            await _schema(svc)
            payload = {"chats": {str(CHAT): {"pending": 5, "last_eval_ts": 0}},
                       "counters": obs.default_counters(), "day": {}}
            runner = _text_runner(svc)
            await runner._evaluate_phase(payload, "cycle-job-id")
            entry = payload["chats"][str(CHAT)]
            await _seed_observe_payload(svc, payload)
            read_model = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return (entry.get("last_run_id"),
                    dict(entry.get("last_decision") or {}),
                    read_model["text_initiative"]["last_attempt"])
        finally:
            await svc.close()

    run_id, decision, attempt = asyncio.run(scenario())
    # Родитель mint'ится ДО гейта: он есть у отказа, и это НЕ цикловой job_id.
    assert run_id and run_id.startswith("init:%d:" % CHAT), run_id
    assert run_id != "cycle-job-id"
    assert decision["run_id"] == run_id
    assert decision["skip_reason"] == obs.SKIP_CHAT_DISABLED
    # Витрина видит ту же попытку и того же родителя.
    assert attempt["run_id"] == run_id
    assert attempt["mode"] == diag.MODE_AUTO
    assert attempt["outcome"] == "skipped"
    assert attempt["stop_stage"] == obs.SKIP_CHAT_DISABLED
    assert attempt["incomplete_historical"] is False


def test_text_events_carry_per_chat_run_id(monkeypatch):
    """Любое событие чата получает trace_id=run_id; чужой чат — свой."""
    from services import mca_events as mca

    captured: list[dict] = []

    def _capture(event_name, **fields):
        captured.append({"event_name": event_name, **fields})
        return {}

    monkeypatch.setattr(mca, "emit_mca_event", _capture)
    runner = _text_runner(None)
    runner._remember_run_id(CHAT, "init:%d:20261111:aaa" % CHAT)
    runner._remember_run_id(CHAT + 1, "init:%d:20261111:bbb" % (CHAT + 1))
    runner._emit("initiative_opportunity", outcome="success", chat_id=CHAT)
    runner._emit("initiative_publication_claim", outcome="success",
                 chat_id=CHAT, entity_id="claim-77")
    runner._emit("initiative_observer_scan", outcome="success", chat_id=CHAT + 1)
    runner._emit("initiative_observer_diagnostic", outcome="failed")

    assert captured[0]["trace_id"] == "init:%d:20261111:aaa" % CHAT
    # Код брони остаётся в entity_id, родитель — в trace_id (не подменяются).
    assert captured[1]["trace_id"] == "init:%d:20261111:aaa" % CHAT
    assert captured[1]["entity_id"] == "claim-77"
    assert captured[2]["trace_id"] == "init:%d:20261111:bbb" % (CHAT + 1)
    # Вне чатового контекста родителя нет: не выдумываем.
    assert "trace_id" not in captured[3]


def test_text_child_llm_calls_are_namespaced(tmp_path, monkeypatch):
    """Дочерние шаги текста: `{run_id}#eval` и `{run_id}#digest`."""
    _image_ok(monkeypatch)
    seen: list[str] = []

    class _LLM:
        async def generate(self, messages, *, temperature=0.0, chat_id=None,
                           module="", step="", correlation_id="", **_kw):
            seen.append(str(correlation_id))
            return "{\"opportunity\": false, \"veto_reason\": \"semantic_none\"}"

    async def scenario():
        svc = await _db(tmp_path, name="text_child.db")
        try:
            await _schema(svc)
            runner = _text_runner(svc)
            runner._llm = _LLM()
            runner._remember_run_id(CHAT, "init:%d:20261111:ccc" % CHAT)
            await runner._evaluate_window(
                CHAT, _rows(CHAT), since_id=0)
            return list(seen)
        finally:
            await svc.close()

    sent = asyncio.run(scenario())
    assert sent == ["init:%d:20261111:ccc#eval" % CHAT], sent
    # digest — тот же родитель, свой шаг.
    runner = _text_runner(None)
    runner._remember_run_id(CHAT, "init:%d:20261111:ccc" % CHAT)
    assert runner._child_run_id(CHAT, "digest") == \
        "init:%d:20261111:ccc#digest" % CHAT


