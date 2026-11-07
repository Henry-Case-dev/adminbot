"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-02 (слайс A) — каноническая идентичность.

Проверяются реальные контрактные пункты `plans/features/memory-cognitive-02/
contracts.md`:

* §1.2 — порядок разрешения (uid → alias → точное имя → casefold → redirect →
  new), `rejected`-условия; резолвер ничего не пишет (ID-1);
* §1.2.1 — засев `B2-0`: 0/1/>1 кандидатов, узел уже закреплён за другим uid,
  идемпотентность, отсутствие `INSERT OR REPLACE`;
* §1.2.2 — ограниченная генерация casefold-кандидатов: диапазон
  `[C, C+1 codepoint)`, `LIMIT`, диапазон находит `ПАПАХА`/`Папаха`/`папаха`
  и не находит `Бабаха`, `EXPLAIN QUERY PLAN` не даёт `SCAN nodes`;
* §1.2.3 — один слот имени на чат: чужой тип → `rejected`
  `type_conflict_single_slot`, второй узел не создаётся;
* §1.4.1 — единственная точка создания (`resolve_or_create_node`) и AST-запрет
  новых прямых `upsert_node` вне резолвера/`database.py`;
* §5.1 — миграция `v43` аддитивна и идемпотентна, существующие таблицы не
  меняются;
* §1.7 — OFF-гейт = паритет baseline (новые таблицы не читаются).
"""
import ast
import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from services import entity_resolver as er
from services import mca_gates
from services import memory_contracts as mc
from services.database import DatabaseService

CHAT = -1001777000123
OTHER_CHAT = -1001777000456
UID_A = 428494
UID_B = 777

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Замороженные наборы колонок существующих таблиц: слайс не имеет права их
#: менять (`§0.5`: никаких новых колонок в `nodes`/`edges`/`graph_facts`).
NODES_COLUMNS = ("id", "chat_id", "entity_name", "entity_type", "origin",
                 "expires_at")
EDGES_COLUMNS = ("id", "chat_id", "source_id", "target_id", "relation_type",
                 "weight", "last_updated", "origin", "expires_at", "fact_id",
                 "created_at")
GRAPH_FACTS_COLUMNS = (
    "id", "chat_id", "fact", "origin", "expires_at", "created_at",
    "target_user", "weight", "status", "last_confirmed_at", "supersedes",
    "message_timestamp", "importance", "source_ids", "kind", "belief_meta",
    "tg_message_id", "forward_from", "subject_ref_id", "attribution_method",
    "assertion_kind", "speaker_author_id", "extractor_version",
    "provenance_channel", "dossier_generation_id", "subject_entity_id",
    "speaker_entity_id", "perspective", "memory_kind", "scope", "valid_from",
    "valid_to", "confidence_basis", "revision",
)

#: Прямые писатели узлов, существующие ДО этого слайса (W1: real-time
#: извлечение факта). Часть B переводит их на `resolve_or_create_node`;
#: до этого они остаются единственным исключением AST-теста.
LEGACY_UPSERT_NODE_FILES = {
    "services/summary_memory.py",
}


# ── инфраструктура ─────────────────────────────────────────────────────────

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


def _patch_hot(monkeypatch, *, identity, aliases=None):
    """Каталоговый слой: `flags.memory_identity_enabled` + alias-карта."""
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
    _patch_hot(monkeypatch, identity=True)
    return True


@pytest.fixture
def gate_off(monkeypatch):
    monkeypatch.delenv("MCA_MEMORY_IDENTITY_ENABLED", raising=False)
    _patch_hot(monkeypatch, identity=False)
    return False


async def _node(db, name, entity_type="user", chat=CHAT):
    return await db.upsert_node(chat, name, entity_type)


async def _message(db, uid, name, chat=CHAT, ts=1700000000):
    await db.save_smart_message(uid, chat, "текст", None, ts, "text", name)


async def _canonical(db, member_id, canonical_id, *, chat=CHAT,
                     entity_type="user", resolution=er.RESOLUTION_MERGED,
                     stable_kind=None, stable_value=None,
                     status=er.STATUS_ACTIVE,
                     method=er.METHOD_EXPLICIT_EVIDENCE,
                     confidence=er.CONFIDENCE_CONFIRMED):
    await db.db.execute(
        f"INSERT INTO {er.ENTITY_CANONICAL_TABLE} ("
        "chat_id, entity_type, member_node_id, canonical_node_id, resolution, "
        "stable_kind, stable_value, method, evidence_ref_id, confidence, "
        "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (chat, entity_type, member_id, canonical_id, resolution, stable_kind,
         stable_value, method, None, confidence, status, 1, 1))
    await db.db.commit()


async def _canonical_rows(db, chat=CHAT):
    cursor = await db.db.execute(
        f"SELECT * FROM {er.ENTITY_CANONICAL_TABLE} WHERE chat_id = ? "
        "ORDER BY member_node_id", (chat,))
    return list(await cursor.fetchall())


async def _node_count(db, chat=CHAT):
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS n FROM nodes WHERE chat_id = ?", (chat,))
    return int((await cursor.fetchone())["n"])


def _scope(entity_type="user", chat=CHAT):
    return mc.EntityScope(chat_id=chat, entity_type=entity_type)


# ── §5.1: миграция v43 ─────────────────────────────────────────────────────

def test_migration_v43_is_additive_and_idempotent(env):
    db, loop = env
    cursor = run(loop, db.db.execute("PRAGMA user_version"))
    assert int(run(loop, cursor.fetchone())[0]) == 43

    cursor = run(loop, db.db.execute(
        "SELECT name, type, sql FROM sqlite_master WHERE "
        "tbl_name='mca_entity_canonical' ORDER BY type, name"))
    objects = {row["name"]: row for row in run(loop, cursor.fetchall())}
    assert er.ENTITY_CANONICAL_TABLE in objects
    assert objects[er.ENTITY_CANONICAL_TABLE]["type"] == "table"
    unique_sql = objects["uq_mca_entity_canonical_stable"]["sql"]
    assert "UNIQUE" in unique_sql.upper()
    assert "status='active'" in unique_sql
    assert "stable_kind IS NOT NULL" in unique_sql
    assert "idx_mca_entity_canonical_canonical" in objects

    cursor = run(loop, db.db.execute(
        f"PRAGMA table_info({er.ENTITY_CANONICAL_TABLE})"))
    columns = [row["name"] for row in run(loop, cursor.fetchall())]
    assert columns == [
        "chat_id", "entity_type", "member_node_id", "canonical_node_id",
        "resolution", "stable_kind", "stable_value", "method",
        "evidence_ref_id", "confidence", "status", "created_at", "updated_at",
    ]

    # Существующие таблицы не менялись (§0.5).
    for table, expected in (("nodes", NODES_COLUMNS),
                            ("edges", EDGES_COLUMNS),
                            ("graph_facts", GRAPH_FACTS_COLUMNS)):
        cursor = run(loop, db.db.execute(f"PRAGMA table_info({table})"))
        assert tuple(row["name"] for row in run(loop, cursor.fetchall())) == \
            expected

    # Данные и повторный прогон шага: no-op, строки не теряются.
    node_id = run(loop, _node(db, "Папаха"))
    before = run(loop, _node_count(db))
    run(loop, db._migrate_entity_canonical_v43())
    run(loop, db._migrate_entity_canonical_v43())
    assert run(loop, _node_count(db)) == before
    cursor = run(loop, db.db.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE "
        "tbl_name='mca_entity_canonical' AND type='table'"))
    assert int(run(loop, cursor.fetchone())["n"]) == 1
    assert node_id >= 1


# ── гейт ───────────────────────────────────────────────────────────────────

def test_gate_is_registered_and_off_by_default(env, monkeypatch):
    db, loop = env
    assert mca_gates.MEMORY_GATES["MCA_MEMORY_IDENTITY_ENABLED"][0] is False
    assert mca_gates.MEMORY_GATE_CATALOG_KEYS[
        "MCA_MEMORY_IDENTITY_ENABLED"] == "flags.memory_identity_enabled"
    monkeypatch.delenv("MCA_MEMORY_IDENTITY_ENABLED", raising=False)
    _patch_hot(monkeypatch, identity=True)
    assert run(loop, mca_gates.memory_identity_enabled(CHAT)) is False
    monkeypatch.setenv("MCA_MEMORY_IDENTITY_ENABLED", "on")
    _patch_hot(monkeypatch, identity=False)
    assert run(loop, mca_gates.memory_identity_enabled(CHAT)) is False
    _patch_hot(monkeypatch, identity=True)
    assert run(loop, mca_gates.memory_identity_enabled(CHAT)) is True
    assert run(loop, mca_gates.memory_identity_enabled(None)) is True


# ── §1.7: OFF-паритет ──────────────────────────────────────────────────────

def test_off_gate_parity_ignores_identity_table(env, gate_off):
    db, loop = env
    papa = run(loop, _node(db, "Папаха"))
    other = run(loop, _node(db, "Александр"))
    # Активный redirect существует, но OFF-ветка его не читает.
    run(loop, _canonical(db, papa, other))

    exact = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Папаха"))
    assert exact.status is mc.EntityResolutionStatus.RESOLVED
    assert exact.canonical.node_id == papa          # без redirect
    assert exact.reason_code == er.REASON_EXACT_NAME

    folded = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="папаха"))
    assert folded.status is mc.EntityResolutionStatus.NEW  # casefold не работает

    created = run(loop, er.resolve_or_create_node(db, CHAT, "Новый", "user"))
    assert created.created is True and created.node_id
    again = run(loop, er.resolve_or_create_node(db, CHAT, "Новый", "user"))
    assert again.created is False and again.node_id == created.node_id
    assert run(loop, _node_count(db)) == 3

    off_rows = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Папаха", stable_identity={
            "kind": "tg_user", "value": UID_A}))
    assert off_rows.reason_code == er.REASON_EXACT_NAME  # rule 1 не включается


# ── §1.2: матрица разрешения ───────────────────────────────────────────────

def test_rule1_stable_identity_wins_over_name(env, gate_on):
    db, loop = env
    papa = run(loop, _node(db, "Папаха"))
    run(loop, _canonical(db, papa, papa, resolution=er.RESOLUTION_SELF,
                         stable_kind=er.STABLE_KIND_TG_USER,
                         stable_value=str(UID_A),
                         method=er.METHOD_ALIAS_MAP))

    res = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="совсем другое имя",
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert res.status is mc.EntityResolutionStatus.RESOLVED
    assert res.canonical.node_id == papa
    assert res.reason_code == er.REASON_STABLE_IDENTITY
    assert res.degraded == ()


def test_rule1_not_seeded_degrades_and_never_claims_identity(env, gate_on):
    db, loop = env
    run(loop, _node(db, "Папаха"))
    res = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Папаха",
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert res.status is mc.EntityResolutionStatus.RESOLVED
    assert res.reason_code == er.REASON_EXACT_NAME
    assert "identity_not_seeded" in res.degraded


def test_rule2_alias_cascade_before_exact_name(env, gate_on, monkeypatch):
    db, loop = env
    _patch_hot(monkeypatch, identity=True, aliases={str(UID_A): "Папаха"})
    node = run(loop, _node(db, "Папаха"))
    res = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Папаха"))
    assert res.status is mc.EntityResolutionStatus.RESOLVED
    assert res.canonical.node_id == node
    # Правило 2 срабатывает раньше правила 3 (точное имя тоже существует).
    assert res.reason_code == er.REASON_ALIAS_MAP

    # Без alias-карты то же написание резолвится точным именем.
    monkeypatch.undo()
    monkeypatch.setenv("MCA_MEMORY_IDENTITY_ENABLED", "on")
    _patch_hot(monkeypatch, identity=True)
    plain = run(loop, er.resolve_entity(db, scope=_scope(), mention="Папаха"))
    assert plain.reason_code == er.REASON_EXACT_NAME


def test_rule3_exact_name_is_byte_for_byte(env, gate_on):
    db, loop = env
    upper = run(loop, _node(db, "ПАПАХА"))
    mixed = run(loop, _node(db, "Папаха"))
    lower = run(loop, _node(db, "папаха"))

    for mention, expected in (("ПАПАХА", upper), ("Папаха", mixed),
                              ("папаха", lower)):
        res = run(loop, er.resolve_entity(
            db, scope=_scope(), mention=mention))
        assert res.status is mc.EntityResolutionStatus.RESOLVED
        assert res.canonical.node_id == expected
        assert res.reason_code == er.REASON_EXACT_NAME


def test_rule4_casefold_covers_all_spellings_and_misses_other_letter(
        env, gate_on):
    db, loop = env
    upper = run(loop, _node(db, "ПАПАХА"))
    mixed = run(loop, _node(db, "Папаха"))
    lower = run(loop, _node(db, "папаха"))
    stranger = run(loop, _node(db, "Бабаха"))

    res = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="пАпАхА"))
    assert res.status is mc.EntityResolutionStatus.AMBIGUOUS
    assert res.reason_code == er.REASON_CASEFOLD_MULTIPLE
    assert {c.ref.node_id for c in res.candidates} == {upper, mixed, lower}
    assert stranger not in {c.ref.node_id for c in res.candidates}

    miss = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Бабаха2"))
    assert miss.status is mc.EntityResolutionStatus.NEW


def test_rule4_unique_casefold_candidate_resolves_tentatively(env, gate_on):
    db, loop = env
    node = run(loop, _node(db, "ПАПАХА"))
    res = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="папаха"))
    assert res.status is mc.EntityResolutionStatus.RESOLVED
    assert res.canonical.node_id == node
    assert res.reason_code == er.REASON_CASEFOLD_UNIQUE


def test_rule4_scan_is_bounded_uses_index_and_reports_overflow(
        env, gate_on, monkeypatch):
    db, loop = env
    for index in range(40):
        run(loop, _node(db, f"Персона{index:02d}"))
    run(loop, _node(db, "Папаха"))

    executed: list[str] = []
    real_fetchall = er._fetchall

    async def spy(db_service, sql, params=()):
        executed.append(sql)
        return await real_fetchall(db_service, sql, params)

    monkeypatch.setattr(er, "_fetchall", spy)
    res = run(loop, er.resolve_entity(db, scope=_scope(), mention="папаха"))
    monkeypatch.undo()

    assert res.status is mc.EntityResolutionStatus.AMBIGUOUS
    assert res.reason_code == er.REASON_CASEFOLD_OVERFLOW
    assert "casefold_prefix_overflow" in res.degraded
    assert 2 <= len(res.candidates) <= 8        # «дочитать всё» запрещено

    scan_sql = [sql for sql in executed if "FROM nodes" in sql]
    assert scan_sql, "правило 4 не выполнило диапазонный запрос"
    for sql in scan_sql:
        assert "entity_name >= ?" in sql and "entity_name < ?" in sql
        assert "LIMIT" in sql

    cursor = run(loop, db.db.execute(
        "EXPLAIN QUERY PLAN " + er.CASEFOLD_SCAN_SQL,
        (CHAT, "П", "Р", "user", er.ENTITY_CASEFOLD_SCAN_LIMIT)))
    plan = " | ".join(str(row["detail"]) for row in run(loop, cursor.fetchall()))
    assert "SEARCH nodes USING INDEX" in plan
    assert "SCAN nodes" not in plan


def test_rule3_type_conflict_rejects_and_creates_nothing(env, gate_on):
    db, loop = env
    topic = run(loop, _node(db, "Папаха", entity_type="topic"))
    before = run(loop, _node_count(db))

    res = run(loop, er.resolve_entity(db, scope=_scope(), mention="Папаха"))
    assert res.status is mc.EntityResolutionStatus.REJECTED
    assert res.reason_code == er.REASON_TYPE_CONFLICT
    assert res.canonical is None
    assert res.candidates[0].ref.entity_type == "topic"
    assert res.candidates[0].ref.node_id == topic

    created = run(loop, er.resolve_or_create_node(db, CHAT, "Папаха", "user"))
    assert created.node_id is None and created.created is False
    assert created.reason_code == er.REASON_TYPE_CONFLICT
    assert run(loop, _node_count(db)) == before


def test_rejected_mentions(env, gate_on):
    db, loop = env
    empty = run(loop, er.resolve_entity(db, scope=_scope(), mention="   "))
    assert empty.status is mc.EntityResolutionStatus.REJECTED
    assert empty.reason_code == er.REASON_EMPTY_MENTION
    long = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="П" * 201))
    assert long.status is mc.EntityResolutionStatus.REJECTED
    assert long.reason_code == er.REASON_MENTION_TOO_LONG


def test_resolver_is_read_only(env, gate_on):
    db, loop = env
    run(loop, _node(db, "Папаха"))
    before_nodes = run(loop, _node_count(db))
    before_rows = len(run(loop, _canonical_rows(db)))
    for mention in ("Папаха", "папаха", "Новый", "Ещё один"):
        run(loop, er.resolve_entity(db, scope=_scope(), mention=mention))
    assert run(loop, _node_count(db)) == before_nodes
    assert len(run(loop, _canonical_rows(db))) == before_rows


def test_resolution_is_chat_qualified(env, gate_on):
    db, loop = env
    run(loop, _node(db, "Папаха", chat=OTHER_CHAT))
    res = run(loop, er.resolve_entity(db, scope=_scope(chat=CHAT),
                                      mention="Папаха"))
    assert res.status is mc.EntityResolutionStatus.NEW


def test_redirect_depth_one_and_chain_flattening(env, gate_on):
    db, loop = env
    sasha = run(loop, _node(db, "Саша"))
    alexander = run(loop, _node(db, "Александр"))
    sashka = run(loop, _node(db, "Сашка"))
    run(loop, _canonical(db, sasha, alexander))
    run(loop, _canonical(db, sashka, sasha))

    res = run(loop, er.resolve_entity(db, scope=_scope(), mention="Саша"))
    assert res.status is mc.EntityResolutionStatus.RESOLVED
    assert res.canonical.node_id == alexander
    assert sasha in res.canonical.legacy_ids

    chained = run(loop, er.resolve_entity(db, scope=_scope(), mention="Сашка"))
    assert chained.canonical.node_id == alexander
    assert chained.reason_code == er.REASON_REDIRECT_FLATTENED
    assert "redirect_chain_flattened" in chained.degraded


# ── §1.2.1 / §5.3: засев B2-0 ──────────────────────────────────────────────

def test_seed_single_candidate_creates_one_self_row(env, gate_on, monkeypatch):
    db, loop = env
    _patch_hot(monkeypatch, identity=True, aliases={str(UID_A): "Папаха"})
    node = run(loop, _node(db, "Папаха"))

    first = run(loop, er.seed_self_identity(db, CHAT, UID_A))
    assert first.status == er.SEED_SEEDED and first.node_id == node
    rows = run(loop, _canonical_rows(db))
    assert len(rows) == 1
    assert rows[0]["resolution"] == er.RESOLUTION_SELF
    assert rows[0]["stable_kind"] == er.STABLE_KIND_TG_USER
    assert rows[0]["stable_value"] == str(UID_A)
    assert rows[0]["member_node_id"] == rows[0]["canonical_node_id"] == node

    second = run(loop, er.seed_self_identity(db, CHAT, UID_A))
    assert second.status == er.SEED_ALREADY_PINNED
    assert len(run(loop, _canonical_rows(db))) == 1

    res = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="кто угодно",
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert res.canonical.node_id == node
    assert res.reason_code == er.REASON_STABLE_IDENTITY


def test_seed_without_candidates_is_honest_degradation(env, gate_on):
    db, loop = env
    run(loop, _node(db, "Совсем другой"))
    res = run(loop, er.seed_self_identity(db, CHAT, UID_A))
    assert res.status == er.SEED_MISSING
    assert "identity_not_seeded" in res.degraded
    assert run(loop, _canonical_rows(db)) == []
    resolved = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Совсем другой",
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert "identity_not_seeded" in resolved.degraded


def test_seed_with_multiple_candidates_does_not_guess(env, gate_on):
    db, loop = env
    run(loop, _message(db, UID_A, "Саша"))
    run(loop, _message(db, UID_A, "Александр", ts=1700000001))
    first = run(loop, _node(db, "Саша"))
    second = run(loop, _node(db, "Александр"))

    res = run(loop, er.seed_self_identity(db, CHAT, UID_A))
    assert res.status == er.SEED_AMBIGUOUS
    assert set(res.candidate_node_ids) == {first, second}
    assert run(loop, _canonical_rows(db)) == []
    resolved = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Саша",
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert "identity_not_seeded" in resolved.degraded


def test_two_uids_with_same_display_name_never_merge(env, gate_on, monkeypatch):
    """T3b/EVAL-04: ноль ложных слияний двух Telegram-личностей."""
    db, loop = env
    _patch_hot(monkeypatch, identity=True,
               aliases={str(UID_A): "Саша", str(UID_B): "Саша"})
    node = run(loop, _node(db, "Саша"))

    first = run(loop, er.seed_self_identity(db, CHAT, UID_A))
    assert first.status == er.SEED_SEEDED and first.node_id == node

    second = run(loop, er.seed_self_identity(db, CHAT, UID_B))
    assert second.status == er.SEED_NODE_CONFLICT
    assert second.node_id == node
    rows = run(loop, _canonical_rows(db))
    assert len(rows) == 1
    assert rows[0]["stable_value"] == str(UID_A)      # ничего не перезаписано

    conflict = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Саша",
        stable_identity={"kind": "tg_user", "value": UID_B}))
    assert conflict.status is mc.EntityResolutionStatus.AMBIGUOUS
    assert conflict.canonical is None
    discriminators = {c.discriminator for c in conflict.candidates}
    assert f"uid: {UID_A}" in discriminators
    assert f"uid: {UID_B}" in discriminators

    # Первый uid не потерял свою идентичность.
    owner = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Саша",
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert owner.canonical.node_id == node

    # Схемный инвариант ID-11: второй активной self-строки быть не может.
    with pytest.raises(sqlite3.IntegrityError):
        run(loop, _canonical(db, node, node, resolution=er.RESOLUTION_SELF,
                             stable_kind=er.STABLE_KIND_TG_USER,
                             stable_value=str(UID_B)))
    other = run(loop, _node(db, "Другой"))
    with pytest.raises(sqlite3.IntegrityError):
        run(loop, _canonical(db, other, other,
                             resolution=er.RESOLUTION_SELF,
                             stable_kind=er.STABLE_KIND_TG_USER,
                             stable_value=str(UID_A)))


def test_reseed_after_nick_change_keeps_stable_value(env, gate_on, monkeypatch):
    """T5/T5b: смена ника не переписывает `stable_value` и не плодит строк."""
    db, loop = env
    _patch_hot(monkeypatch, identity=True, aliases={str(UID_A): "Саша"})
    sasha = run(loop, _node(db, "Саша"))
    run(loop, er.seed_self_identity(db, CHAT, UID_A))

    _patch_hot(monkeypatch, identity=True, aliases={str(UID_A): "Александр"})
    alexander = run(loop, _node(db, "Александр"))
    again = run(loop, er.seed_self_identity(db, CHAT, UID_A))

    assert again.status == er.SEED_ALREADY_PINNED
    rows = run(loop, _canonical_rows(db))
    assert len(rows) == 1
    assert rows[0]["stable_value"] == str(UID_A)
    assert rows[0]["member_node_id"] == sasha
    assert alexander != sasha and run(loop, _node_count(db)) == 2
    res = run(loop, er.resolve_entity(
        db, scope=_scope(), mention="Саша",
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert res.canonical.node_id == sasha


# ── §1.4.1: единственная точка создания ────────────────────────────────────

def test_resolve_or_create_node_is_idempotent(env, gate_on):
    db, loop = env
    created = run(loop, er.resolve_or_create_node(db, CHAT, "Новый", "user"))
    assert created.created is True and created.status == "new"
    again = run(loop, er.resolve_or_create_node(db, CHAT, "Новый", "user"))
    assert again.created is False and again.node_id == created.node_id
    assert run(loop, _node_count(db)) == 1

    existing = run(loop, _node(db, "ПАПАХА"))
    folded = run(loop, er.resolve_or_create_node(db, CHAT, "папаха", "user"))
    assert folded.node_id == existing and folded.created is False
    assert run(loop, _node_count(db)) == 2

    new_only = run(loop, er.resolve_or_create_node(
        db, CHAT, "Ещё", "user", allow_create=False))
    assert new_only.node_id is None and new_only.status == "new"
    assert run(loop, _node_count(db)) == 2


def test_no_direct_upsert_node_outside_resolver():
    """§1.4.1: прямых `upsert_node` вне резолвера/`database.py` не появляется."""
    allowed = {"services/database.py", "services/entity_resolver.py"}
    allowed |= LEGACY_UPSERT_NODE_FILES
    offenders: list[str] = []

    for path in sorted(REPO_ROOT.glob("services/*.py")) + \
            sorted(REPO_ROOT.glob("web/*.py")) + \
            sorted(REPO_ROOT.glob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "upsert_node"
                    and relative not in allowed):
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == [], (
        "§1.4.1: узлы создаются только через resolve_or_create_node; "
        f"прямые вызовы: {offenders}")


def test_resolver_module_has_no_second_identity_store():
    """Границы слайса: один резолвер, нет второго словаря/таблицы сущностей."""
    source = (REPO_ROOT / "services" / "entity_resolver.py").read_text(
        encoding="utf-8")
    assert source.count("CREATE TABLE IF NOT EXISTS") == 1  # одна таблица
    tree = ast.parse(source)
    # Импорт каскада имён — ленивый (REUSE существующего владельца), на
    # уровне модуля второго словаря алиасов нет.
    module_level_modules = {node.module for node in tree.body
                            if isinstance(node, ast.ImportFrom) and node.module}
    module_level_names = {alias.name for node in tree.body
                          if isinstance(node, (ast.Import, ast.ImportFrom))
                          for alias in node.names}
    assert "services.summary_aliases" not in module_level_modules
    assert "memory_contracts" in module_level_names
