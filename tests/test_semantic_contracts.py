"""VMQ-ONTO-A (O-01, O-02) — typed semantic projection.

Проверяется контракт `services/semantic_contracts.py` на РЕАЛЬНЫХ владельцах:
`entity_resolver.resolve_entity`, `mca_entity_canonical`, `graph_facts`,
`node`-rows, `graphrag_provenance` и `summary_aliases`. Никаких заглушек вместо
subject under test: разрешение идентичности выполняет существующий резолвер,
provenance-классы считает существующий `graphrag_provenance`.
"""
import ast
import asyncio
import json
from pathlib import Path

import pytest

from services import entity_resolver as er
from services import graphrag_provenance as grp
from services import memory_contracts as mc
from services import message_identity
from services import provenance
from services import semantic_contracts as sc
from services.database import DatabaseService

CHAT = -1001555000111
CHAT_B = -1001555000222


# ── инфраструктура (та же схема, что в test_memory_identity) ────────────────

@pytest.fixture
def env():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    db = DatabaseService(":memory:")
    loop.run_until_complete(db.initialize())
    try:
        yield db, loop
    finally:
        loop.run_until_complete(db.close())
        loop.close()


def run(loop, coro):
    return loop.run_until_complete(coro)


def _patch_hot(monkeypatch, *, identity=True, aliases=None):
    import services.hot_config as hot

    real_get = hot.get

    def fake_get(key, default=None):
        if key == "flags.memory_identity_enabled":
            return identity
        if key == "limits.summary_aliases":
            return json.dumps(aliases) if aliases is not None else default
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv("MCA_MEMORY_IDENTITY_ENABLED", "on")
    _patch_hot(monkeypatch, identity=True, aliases={})
    return True


async def _node(db, name, entity_type="user", chat=CHAT):
    return await db.upsert_node(chat, name, entity_type)


async def _message(db, uid, name, chat=CHAT, ts=1700000000):
    await db.save_smart_message(uid, chat, "текст", None, ts, "text", name)


async def _pin_uid(db, node_id, uid, *, chat=CHAT, entity_type="user"):
    """Существующая строка идентичности: узел ↔ Telegram UID (как `B2-0`)."""
    await db.db.execute(
        f"INSERT INTO {er.ENTITY_CANONICAL_TABLE} ("
        "chat_id, entity_type, member_node_id, canonical_node_id, resolution, "
        "stable_kind, stable_value, method, evidence_ref_id, confidence, "
        "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (chat, entity_type, node_id, node_id, er.RESOLUTION_SELF,
         er.STABLE_KIND_TG_USER, str(uid), er.METHOD_ALIAS_MAP, None,
         er.CONFIDENCE_CONFIRMED, er.STATUS_ACTIVE, 1, 1))
    await db.db.commit()


def _scope(chat=CHAT, entity_type="user"):
    return mc.EntityScope(chat_id=chat, entity_type=entity_type)


async def _fact_row(db, **kwargs):
    """Реальная строка `graph_facts` через существующий writer.

    Базовые provenance-колонки пишет `insert_graph_fact`; колонки типированной
    записи (`perspective`/`attribution_method`) ставит существующий
    `save_typed_fact` — здесь они выставляются одним UPDATE значениями из
    реальной схемы (фикстура данных, не подмена subject under test).
    """
    perspective = kwargs.pop("perspective", None)
    attribution_method = kwargs.pop("attribution_method", None)
    fact_id = await db.insert_graph_fact(
        kwargs.pop("chat", CHAT), "тестовый факт",
        kwargs.pop("origin", "chat_history"), None, **kwargs)
    if perspective is not None or attribution_method is not None:
        await db.db.execute(
            "UPDATE graph_facts SET perspective = ?, attribution_method = ? "
            "WHERE id = ?",
            (perspective, attribution_method, int(fact_id)))
        await db.db.commit()
    cursor = await db.db.execute(
        "SELECT * FROM graph_facts WHERE id = ?", (int(fact_id),))
    row = await cursor.fetchone()
    assert row is not None
    return dict(row)


async def _counts(db):
    out = {}
    for table in ("nodes", "graph_facts", er.ENTITY_CANONICAL_TABLE):
        cursor = await db.db.execute(f"SELECT COUNT(*) AS n FROM {table}")
        out[table] = int((await cursor.fetchone())["n"])
    return out


# ── O-01: тип выводится из сигналов, а не из строки ─────────────────────────

def test_entity_type_is_derived_from_signals_not_name():
    # user: только participant identity делает тип типизированным.
    typed = sc.classify_entity_type(
        "user", chat_id=CHAT, has_participant_identity=True)
    assert typed.status == sc.VERIFIED and typed.is_typed
    assert typed.signals == (sc.TYPE_SIGNAL_CHAT_SCOPE,
                             sc.TYPE_SIGNAL_PARTICIPANT_IDENTITY)
    assert typed.missing == ()
    # то же имя без UID — weak hint, а не человек
    weak = sc.classify_entity_type("user", chat_id=CHAT)
    assert weak.status == sc.TENTATIVE
    assert weak.missing == (sc.TYPE_SIGNAL_PARTICIPANT_IDENTITY,)
    # event: тип держится на времени события, не на названии
    assert sc.classify_entity_type(
        "event", chat_id=CHAT, event_time=1700000000).status == sc.VERIFIED
    assert sc.classify_entity_type(
        "event", chat_id=CHAT).missing == (sc.TYPE_SIGNAL_TIME_ANCHOR,)
    # fact: тип держится на statement provenance
    assert sc.classify_entity_type(
        "fact", chat_id=CHAT,
        has_statement_provenance=True).status == sc.VERIFIED
    assert sc.classify_entity_type(
        "fact", chat_id=CHAT).status == sc.TENTATIVE
    # topic: достаточно chat scope (нет person/time/statement требований)
    assert sc.classify_entity_type("topic", chat_id=CHAT).status == sc.VERIFIED


def test_chat_scope_is_required_for_every_type():
    """Без chat scope тип не может быть `verified` ни для одного типа (O-01).

    Бывшая дыра: `event` по одному time anchor и `fact` по одному statement
    provenance получали `verified` без scope. Теперь chat_scope обязателен
    всегда, а неполный набор остаётся честным `tentative`/`unknown`.
    """
    complete = {
        "user": {"has_participant_identity": True},
        "topic": {},
        "event": {"event_time": 1700000000},
        "fact": {"has_statement_provenance": True},
    }
    for entity_type, signals in complete.items():
        typed = sc.classify_entity_type(entity_type, chat_id=CHAT, **signals)
        assert typed.status == sc.VERIFIED, entity_type
        unscoped = sc.classify_entity_type(entity_type, **signals)
        assert unscoped.status != sc.VERIFIED, entity_type
        assert sc.TYPE_SIGNAL_CHAT_SCOPE in unscoped.missing, entity_type
        assert unscoped.as_dict()["status"] in (sc.TENTATIVE, sc.UNKNOWN)
    # целевые кейсы находки Reviewer
    assert sc.classify_entity_type(
        "event", event_time=1700000000).status == sc.TENTATIVE
    assert sc.classify_entity_type(
        "event", event_time=1700000000).missing == (
            sc.TYPE_SIGNAL_CHAT_SCOPE,)
    assert sc.classify_entity_type(
        "fact", has_statement_provenance=True).status == sc.TENTATIVE
    assert sc.classify_entity_type(
        "fact", has_statement_provenance=True).missing == (
            sc.TYPE_SIGNAL_CHAT_SCOPE,)


def test_chat_scope_is_declared_required_for_every_type():
    for entity_type in mc.ENTITY_TYPES_ALLOWED:
        assert sc.TYPE_SIGNAL_CHAT_SCOPE in sc.REQUIRED_TYPE_SIGNALS[entity_type]


def test_verified_type_cannot_skip_chat_scope():
    """Структурный инвариант: verified без chat_scope невозможен."""
    with pytest.raises(ValueError):
        sc.TypedEntityType(entity_type="event", status=sc.VERIFIED,
                           signals=(sc.TYPE_SIGNAL_TIME_ANCHOR,))
    with pytest.raises(ValueError):
        sc.TypedEntityType(entity_type="fact", status=sc.VERIFIED,
                           signals=(sc.TYPE_SIGNAL_STATEMENT_PROVENANCE,))


def test_unknown_and_invalid_types_are_honest():
    assert sc.classify_entity_type(None, chat_id=CHAT).status == sc.UNKNOWN
    assert (sc.classify_entity_type(None, chat_id=CHAT).entity_type is None)
    invalid = sc.classify_entity_type("person", chat_id=CHAT)
    assert invalid.status == sc.REJECTED
    assert invalid.reason_code == sc.REASON_INVALID_ENTITY_TYPE
    assert invalid.entity_type == "person"       # чужой тип не «исправляем»
    cross = sc.classify_entity_type(
        "user", chat_id=CHAT, referent_chat_id=CHAT_B,
        has_participant_identity=True)
    assert cross.status == sc.REJECTED
    assert cross.reason_code == sc.REASON_CROSS_CHAT_SCOPE
    conflict = sc.classify_entity_type(
        "topic", chat_id=CHAT, has_participant_identity=True)
    assert conflict.status == sc.REJECTED
    assert conflict.reason_code == sc.REASON_TYPE_CONFLICT


def test_type_is_not_determined_by_name_string():
    """Структурно: классификатор не принимает имя/упоминание вообще."""
    params = set(sc.classify_entity_type.__code__.co_varnames[
        :sc.classify_entity_type.__code__.co_argcount])
    for forbidden in ("name", "mention", "entity_name", "text"):
        assert forbidden not in params


def test_meaning_times_stay_independent():
    moment = sc.MeaningTime(event_time=1700000000, asserted_at=1700000500,
                            observed_at=1700000900)
    assert (moment.event_time, moment.asserted_at, moment.observed_at) == (
        1700000000, 1700000500, 1700000900)
    assert moment.has_event_time is True and moment.has_assertion_time is True
    # нет утверждения — нет подстановки из event/observed
    bare = sc.MeaningTime(event_time=1700000000, observed_at=1700000900)
    assert bare.asserted_at is None and bare.has_assertion_time is False
    with pytest.raises(ValueError):
        sc.MeaningTime(asserted_at=-5)


def test_identity_invariants_block_false_canonical():
    ref = mc.EntityRef(chat_id=CHAT, node_id=7, entity_type="user",
                       display_name="Иван")
    with pytest.raises(ValueError):
        # alias-hint не может нести participant identity
        sc.SemanticIdentity(chat_id=CHAT, entity_type="user",
                            basis=sc.IDENTITY_BASIS_NAME_HINT,
                            status=sc.TENTATIVE, hint_ref=ref, participant_id=5)
    with pytest.raises(ValueError):
        # canonical допускается только на доказанной базе
        sc.SemanticIdentity(chat_id=CHAT, entity_type="user",
                            basis=sc.IDENTITY_BASIS_NAME_HINT,
                            status=sc.TENTATIVE, canonical=ref, hint_ref=ref)
    with pytest.raises(ValueError):
        # один кандидат — не «неоднозначность» и не повод выбирать canonical
        sc.SemanticIdentity(
            chat_id=CHAT, entity_type="user", basis=sc.IDENTITY_BASIS_NAME_HINT,
            status=sc.UNKNOWN,
            candidates=(mc.ResolutionCandidate(
                ref=ref, reason="r", discriminator="d"),))
    with pytest.raises(ValueError):
        # чужой chat scope в canonical запрещён
        sc.SemanticIdentity(
            chat_id=CHAT, entity_type="user",
            basis=sc.IDENTITY_BASIS_PARTICIPANT, status=sc.VERIFIED,
            participant_id=5,
            canonical=mc.EntityRef(chat_id=CHAT_B, node_id=9,
                                   entity_type="user", display_name="Иван"))


# ── O-02: UID — identity, имя/алиас — hint ─────────────────────────────────

def test_uid_resolution_is_identity_and_name_is_only_hint(env, gate_on):
    db, loop = env

    async def scenario():
        node_id = await _node(db, "Иван")
        await _pin_uid(db, node_id, 5)
        by_uid = await er.resolve_entity(
            db, scope=_scope(), mention="Иван",
            stable_identity={"kind": "tg_user", "value": 5})
        by_name = await er.resolve_entity(db, scope=_scope(), mention="Иван")
        return node_id, by_uid, by_name

    node_id, by_uid, by_name = run(loop, scenario())
    assert by_uid.reason_code == er.REASON_STABLE_IDENTITY
    assert by_name.reason_code == er.REASON_EXACT_NAME

    uid_identity = sc.project_identity(
        chat_id=CHAT, entity_type="user", resolution=by_uid, participant_id=5)
    assert uid_identity.basis == sc.IDENTITY_BASIS_PARTICIPANT
    assert uid_identity.status == sc.VERIFIED
    assert uid_identity.is_person_confirmed is True
    assert uid_identity.canonical is not None
    assert uid_identity.canonical.node_id == node_id

    name_identity = sc.project_identity(
        chat_id=CHAT, entity_type="user", resolution=by_name)
    assert name_identity.basis == sc.IDENTITY_BASIS_NAME_HINT
    assert name_identity.status == sc.TENTATIVE
    assert name_identity.is_hint_only is True
    assert name_identity.canonical is None          # имени ≠ канонический человек
    assert name_identity.hint_ref is not None
    assert name_identity.hint_ref.node_id == node_id


def test_common_noun_does_not_become_person(env, gate_on):
    db, loop = env

    async def scenario():
        node_id = await _node(db, "Папаха")
        resolution = await er.resolve_entity(
            db, scope=_scope(), mention="папаха")
        cursor = await db.db.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = dict(await cursor.fetchone())
        return resolution, sc.project_node_meaning(
            row, identity_resolution=resolution)

    resolution, meaning = run(loop, scenario())
    assert resolution.status is mc.EntityResolutionStatus.RESOLVED
    assert resolution.reason_code == er.REASON_CASEFOLD_UNIQUE
    # нарицательное имя/написание не даёт канонического человека
    assert meaning.identity is not None
    assert meaning.identity.basis == sc.IDENTITY_BASIS_NAME_HINT
    assert meaning.identity.canonical is None
    assert meaning.identity.is_person_confirmed is False
    assert meaning.type.status == sc.TENTATIVE
    assert meaning.verification != sc.VERIFIED
    assert meaning.as_dict()["identity"]["canonical"] is None
    assert sc.DEGRADED_IDENTITY_HINT_ONLY in meaning.degraded


def test_alias_hint_does_not_merge_with_uid_identity(env, gate_on, monkeypatch):
    db, loop = env
    _patch_hot(monkeypatch, identity=True, aliases={"777": "Папаха"})

    async def scenario():
        node_id = await _node(db, "Папаха")
        await _message(db, 777, "Папаха")
        by_alias = await er.resolve_entity(
            db, scope=_scope(), mention="Папаха")
        seeded = await er.seed_self_identity(db, CHAT, 777)
        by_uid = await er.resolve_entity(
            db, scope=_scope(), mention="Папаха",
            stable_identity={"kind": "tg_user", "value": 777})
        return node_id, by_alias, seeded, by_uid

    node_id, by_alias, seeded, by_uid = run(loop, scenario())
    assert by_alias.reason_code == er.REASON_ALIAS_MAP
    assert seeded.status == er.SEED_SEEDED
    assert by_uid.reason_code == er.REASON_STABLE_IDENTITY

    alias_identity = sc.project_identity(
        chat_id=CHAT, entity_type="user", resolution=by_alias)
    assert alias_identity.is_hint_only is True
    assert alias_identity.canonical is None          # alias сам ничего не слил
    uid_identity = sc.project_identity(
        chat_id=CHAT, entity_type="user", resolution=by_uid, participant_id=777)
    assert uid_identity.is_person_confirmed is True
    assert uid_identity.canonical is not None
    assert uid_identity.canonical.node_id == node_id
    # две разные оценки, а не один общий «канонический» объект
    assert alias_identity.as_dict()["canonical"] is None
    assert uid_identity.as_dict()["canonical"]["node_id"] == node_id


def test_same_display_name_stays_distinct_by_scope_and_uid(env, gate_on):
    db, loop = env

    async def scenario():
        first = await _node(db, "Иван", chat=CHAT)
        await _pin_uid(db, first, 11, chat=CHAT)
        second = await _node(db, "Иван", chat=CHAT_B)
        await _pin_uid(db, second, 22, chat=CHAT_B)
        res_first = await er.resolve_entity(
            db, scope=_scope(CHAT), mention="Иван",
            stable_identity={"kind": "tg_user", "value": 11})
        res_second = await er.resolve_entity(
            db, scope=_scope(CHAT_B), mention="Иван",
            stable_identity={"kind": "tg_user", "value": 22})
        return first, second, res_first, res_second

    first, second, res_first, res_second = run(loop, scenario())
    identity_first = sc.project_identity(
        chat_id=CHAT, entity_type="user", resolution=res_first,
        participant_id=11)
    identity_second = sc.project_identity(
        chat_id=CHAT_B, entity_type="user", resolution=res_second,
        participant_id=22)
    assert identity_first.is_person_confirmed is True
    assert identity_second.is_person_confirmed is True
    assert identity_first.canonical.node_id == first
    assert identity_second.canonical.node_id == second
    assert identity_first.chat_id != identity_second.chat_id
    assert identity_first.canonical.node_id != identity_second.canonical.node_id
    # чужой результат в этом scope отвергается, а не «сливается»
    foreign = sc.project_identity(
        chat_id=CHAT, entity_type="user", resolution=res_second)
    assert foreign.status == sc.REJECTED
    assert foreign.reason_code == sc.REASON_CROSS_CHAT_SCOPE
    assert foreign.canonical is None


def test_ambiguous_term_stays_ambiguous(env, gate_on):
    db, loop = env

    async def scenario():
        await _node(db, "Иван")
        await _node(db, "ИВАН")
        return await er.resolve_entity(db, scope=_scope(), mention="ИвАн")

    resolution = run(loop, scenario())
    assert resolution.status is mc.EntityResolutionStatus.AMBIGUOUS
    assert resolution.reason_code == er.REASON_CASEFOLD_MULTIPLE
    identity = sc.project_identity(
        chat_id=CHAT, entity_type="user", resolution=resolution)
    assert identity.status == sc.UNKNOWN
    assert identity.is_ambiguous is True
    assert identity.canonical is None             # автовыбор запрещён
    assert len(identity.candidates) >= 2
    assert identity.as_dict()["ambiguous"] is True
    assert all(candidate.ref.entity_type == "user"
               for candidate in identity.candidates)


def test_mention_without_resolution_is_not_identity():
    identity = sc.project_identity(
        chat_id=CHAT, entity_type="user", mention="Папаха")
    assert identity.status == sc.UNKNOWN
    assert identity.basis == sc.IDENTITY_BASIS_NONE
    assert identity.canonical is None and identity.hint_ref is None
    assert identity.reason_code == sc.REASON_IDENTITY_UNRESOLVED


def test_known_uid_without_node_is_still_person_identity():
    identity = sc.project_identity(
        chat_id=CHAT, entity_type="user", participant_id=99)
    assert identity.is_person_confirmed is True
    assert identity.canonical is None             # адрес узла неизвестен
    assert identity.basis == sc.IDENTITY_BASIS_PARTICIPANT


# ── O-01: speaker ≠ subject, провенанс и время на реальных строках ──────────

def test_fact_meaning_keeps_speaker_and_subject_apart(env, gate_on):
    db, loop = env

    async def scenario():
        row = await _fact_row(
            db, subject_ref_id=11, speaker_author_id=22,
            message_timestamp=1700000100)
        return sc.project_fact_meaning(row)

    meaning = run(loop, scenario())
    assert meaning.speaker.role == sc.ROLE_SPEAKER
    assert meaning.subject.role == sc.ROLE_SUBJECT
    assert meaning.speaker.identity.participant_id == 22
    assert meaning.subject.identity.participant_id == 11
    assert meaning.speaker.identity.is_person_confirmed is True
    assert meaning.subject.identity.is_person_confirmed is True
    # роли не склеены между собой
    assert meaning.speaker.as_dict()["identity"]["participant_id"] == 22
    assert meaning.subject.as_dict()["identity"]["participant_id"] == 11
    # времена: утверждение из message_timestamp, обнаружение — created_at
    assert meaning.time.asserted_at == 1700000100
    assert meaning.time.observed_at is not None
    assert meaning.time.event_time is None
    # speaker/subject атрибутированы, но происхождение основания не установлено
    assert meaning.provenance_class == grp.EDGE_CONFIDENT
    assert meaning.origin_class is mc.OriginClass.LEGACY_UNKNOWN
    assert meaning.origin == "chat_history"
    assert meaning.verification == sc.TENTATIVE


def test_subject_is_never_filled_from_speaker_and_vice_versa(env, gate_on):
    db, loop = env

    async def scenario():
        only_subject = await _fact_row(
            db, subject_ref_id=11, message_timestamp=1700000100)
        only_speaker = await _fact_row(
            db, speaker_author_id=22, message_timestamp=1700000100)
        return sc.project_fact_meaning(only_subject), \
            sc.project_fact_meaning(only_speaker)

    subject_only, speaker_only = run(loop, scenario())
    assert subject_only.subject.identity.participant_id == 11
    assert subject_only.speaker.identity is None
    assert subject_only.speaker.reason_code == sc.REASON_ROLE_UNRESOLVED
    assert speaker_only.speaker.identity.participant_id == 22
    assert speaker_only.subject.identity is None
    assert speaker_only.subject.reason_code == sc.REASON_ROLE_UNRESOLVED
    assert sc.DEGRADED_ROLE_UNRESOLVED in subject_only.degraded
    assert sc.DEGRADED_ROLE_UNRESOLVED in speaker_only.degraded


def test_fact_verification_uses_existing_provenance_owners(env, gate_on):
    db, loop = env

    async def scenario():
        direct = await _fact_row(
            db, subject_ref_id=11, speaker_author_id=11,
            message_timestamp=1700000100, perspective="self",
            attribution_method="self_report")
        bot = await _fact_row(
            db, origin="bot_direct_reply", subject_ref_id=11,
            speaker_author_id=22, message_timestamp=1700000100)
        quoted = await _fact_row(
            db, subject_ref_id=11, speaker_author_id=22,
            forward_from="Канал X", message_timestamp=1700000100)
        bare = await _fact_row(db)
        return [sc.project_fact_meaning(r) for r in (direct, bot, quoted, bare)]

    direct, bot, quoted, bare = run(loop, scenario())
    # классы берутся у существующих владельцев, а не пересчитываются здесь
    assert direct.origin_class is mc.OriginClass.EXPLICIT_DIRECT
    assert direct.verification == sc.VERIFIED
    assert bot.origin_class is mc.OriginClass.DERIVED_WITH_LINEAGE
    assert bot.origin == "bot_direct_reply"
    assert bot.verification == sc.TENTATIVE
    assert quoted.origin_class is mc.OriginClass.QUOTE_FORWARD
    assert quoted.forwarded is True
    assert quoted.verification == sc.TENTATIVE
    assert bare.provenance_class == grp.EDGE_LEGACY_UNVERIFIED
    assert bare.verification == sc.UNKNOWN


def test_conflict_stays_visible(env, gate_on):
    db, loop = env

    async def scenario():
        row = await _fact_row(
            db, subject_ref_id=11, speaker_author_id=11,
            message_timestamp=1700000100, perspective="self",
            attribution_method="self_report")
        return sc.project_fact_meaning(row, conflict_status="conflicting")

    meaning = run(loop, scenario())
    assert meaning.conflict_status == "conflicting"
    assert meaning.verification != sc.VERIFIED


def test_sender_is_not_replaced_by_forward_origin(env, gate_on):
    db, loop = env
    # Существующая роль-модель сообщения: автор ≠ автор пересылки ≠ цитата.
    roles = message_identity.roles({
        "user_id": 22, "reply_to_author_id": 33,
        "quote_author_id": 44, "forward_author_id": 55,
    })
    assert roles[message_identity.ROLE_AUTHOR] == 22
    assert roles[message_identity.ROLE_FORWARD_AUTHOR] == 55
    assert roles[message_identity.ROLE_QUOTED_AUTHOR] == 44
    assert roles[message_identity.ROLE_REPLY_ADDRESSEE] == 33
    assert len({roles[message_identity.ROLE_AUTHOR],
                roles[message_identity.ROLE_FORWARD_AUTHOR],
                roles[message_identity.ROLE_QUOTED_AUTHOR]}) == 3

    async def scenario():
        row = await _fact_row(
            db, subject_ref_id=11, speaker_author_id=22,
            forward_from="Канал X", message_timestamp=1700000100)
        return row, sc.project_fact_meaning(row)

    row, meaning = run(loop, scenario())
    assert row["forward_from"] == "Канал X"
    # speaker остаётся отправителем, а пересылка не становится подтверждением
    assert meaning.speaker.identity.participant_id == 22
    assert meaning.forwarded is True
    assert meaning.verification == sc.TENTATIVE


def test_node_meaning_distinguishes_all_four_types(env, gate_on):
    db, loop = env

    async def scenario():
        user_node = await _node(db, "Иван")
        await _pin_uid(db, user_node, 5)
        topic_node = await _node(db, "рыбалка", entity_type="topic")
        event_node = await _node(db, "поездка", entity_type="event")
        fact_node = await _node(db, "любит чай", entity_type="fact")
        rows = {}
        for key in (user_node, topic_node, event_node, fact_node):
            cursor = await db.db.execute(
                "SELECT * FROM nodes WHERE id = ?", (key,))
            rows[key] = dict(await cursor.fetchone())
        user_res = await er.resolve_entity(
            db, scope=_scope(), mention="Иван",
            stable_identity={"kind": "tg_user", "value": 5})
        speaker = sc.project_identity(
            chat_id=CHAT, entity_type="user", participant_id=5)
        return {
            "user": sc.project_node_meaning(rows[user_node],
                                            identity_resolution=user_res,
                                            participant_id=5),
            "topic": sc.project_node_meaning(rows[topic_node]),
            "event": sc.project_node_meaning(rows[event_node]),
            "event_dated": sc.project_node_meaning(
                rows[event_node],
                time=sc.MeaningTime(event_time=1700000000)),
            "fact": sc.project_node_meaning(rows[fact_node],
                                            speaker_identity=speaker),
        }

    meanings = run(loop, scenario())
    assert meanings["user"].entity_type == "user"
    assert meanings["user"].type.status == sc.VERIFIED
    assert meanings["user"].identity.is_person_confirmed is True
    assert meanings["user"].identity.canonical.node_id is not None
    assert meanings["topic"].entity_type == "topic"
    assert meanings["topic"].type.status == sc.VERIFIED
    assert meanings["topic"].verification == sc.VERIFIED
    assert meanings["event"].entity_type == "event"
    assert meanings["event"].type.status == sc.TENTATIVE   # время неизвестно
    assert meanings["event"].verification != sc.VERIFIED
    assert meanings["event_dated"].type.status == sc.VERIFIED
    assert meanings["event_dated"].time.event_time == 1700000000
    assert meanings["fact"].entity_type == "fact"
    assert meanings["fact"].type.status == sc.VERIFIED     # speaker известен
    assert meanings["fact"].speaker.identity.is_person_confirmed is True


def test_identity_enum_is_the_existing_one():
    assert mc.ENTITY_TYPES_ALLOWED == ("user", "topic", "event", "fact")
    assert sc.VERIFIED in provenance.VERIFICATIONS
    assert sc.TENTATIVE in provenance.VERIFICATIONS
    assert sc.UNKNOWN in provenance.VERIFICATIONS
    assert sc.REJECTED in provenance.VERIFICATIONS


# ── Безопасность границ: read-only, без DDL и второго владельца ────────────

def test_projection_does_not_write(env, gate_on):
    db, loop = env

    async def scenario():
        node_id = await _node(db, "Иван")
        await _pin_uid(db, node_id, 5)
        row = await _fact_row(
            db, subject_ref_id=11, speaker_author_id=22,
            message_timestamp=1700000100, perspective="self",
            attribution_method="self_report")
        resolution = await er.resolve_entity(
            db, scope=_scope(), mention="Иван",
            stable_identity={"kind": "tg_user", "value": 5})
        cursor = await db.db.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,))
        node_row = dict(await cursor.fetchone())
        before = await _counts(db)
        for _ in range(3):
            sc.project_node_meaning(node_row, identity_resolution=resolution,
                                    participant_id=5)
            sc.project_fact_meaning(row)
            sc.project_identity(chat_id=CHAT, entity_type="user",
                                resolution=resolution, participant_id=5)
        after = await _counts(db)
        return before, after

    before, after = run(loop, scenario())
    assert before == after


def test_invalid_row_scope_raises_instead_of_inventing_chat():
    with pytest.raises(ValueError):
        sc.project_node_meaning({"id": 1, "entity_type": "user",
                                 "entity_name": "Иван"})
    with pytest.raises(ValueError):
        sc.project_fact_meaning({"id": 1, "fact": "что-то"})


def test_import_stays_light_and_has_no_db_dependency():
    """Контракт не тянет БД/retrieval: проекция остаётся чистой."""
    import subprocess
    import sys

    code = (
        "import sys; import services.semantic_contracts; "
        "bad = [m for m in ('services.database', 'services.mca_retrieval_context',"
        " 'services.ai_service', 'services.entity_resolver') "
        "if m in sys.modules]; print(','.join(bad))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", result.stdout


def test_module_has_no_sql_ddl_or_second_identity_store():
    path = Path(sc.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    forbidden_calls = {"execute", "executemany", "commit", "write_transaction",
                       "upsert_node", "insert_graph_fact", "resolve_entity",
                       "build_alias_resolver", "emit_mca_event"}
    forbidden_sql = ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ",
                     "DROP ")
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            assert name not in forbidden_calls, f"write/resolve call: {name}"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            for alias in node.names:
                imported.add(f"{module}.{alias.name}".strip("."))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = node.value.upper()
            for token in forbidden_sql:
                assert token not in upper, f"SQL/DDL literal: {token}"
    local_modules = {name for name in imported
                     if name.startswith("services.")}
    assert local_modules <= {
        "services.graphrag_provenance", "services.memory_contracts",
        "services.provenance", "services.entity_resolver",
    }, local_modules
    # второй «владелец» идентичности/поиска не появляется
    assert not (path.parent / "semantic_ontology.py").exists()
