"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-02 (часть B) — писатели и дубли.

Проверяются реальные контрактные пункты `plans/features/memory-cognitive-02/
contracts.md` (rev3) и требования источника MEM-02.6/02.7/02.8:

* §1.4.1 — все писатели узлов идут через `resolve_or_create_node`; OFF-гейт
  байт-в-байт прежний (фикстура снята на базовой линии `828d1dd1` и
  сравнивается с текущим прогоном на файловой БД);
* §1.2.3 — конфликт типа на одном слоте имени: ON → факт без ребра (честно),
  OFF → прежнее ребро в существующий узел (паритет);
* §1.4/§1.4.2 — слияние = одна аддитивная строка, глубина 1, цикл отвергается,
  автоматического «выпрямления» нет;
* §2.5 — агрегат ребра после слияния: минимальный `edge_id`, все `fact_id`;
* §5.3 B1/B2 — dry-run (ноль записей), безопасные слияния только с доказанной
  устойчивой идентичностью, чекпоинт/resume, откат `revoked`;
* MEM-02.8 — одинаковое имя у двух uid, пара только по сходству/источнику,
  повторный прогон не множит узлы/рёбра.

TEST-LIFECYCLE: CONTRACT owner=MEMORY-02 (MEM-02.6/02.7/02.8)
"""
from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from services import entity_merge as em
from services import entity_resolver as er
from services.database import DatabaseService
from tests import mem02b_off_baseline as baseline

CHAT = baseline.CHAT
UID_A = baseline.UID_A
UID_B = baseline.UID_B

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mem02b" / "off_baseline_828d1dd1.json"


# ── инфраструктура ─────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path):
    """Реальная файловая БД (не `:memory:`): паритет и миграция проверяемы."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    db = DatabaseService(str(tmp_path / "mem02b.db"))
    loop.run_until_complete(db.initialize())
    try:
        yield db, loop
    finally:
        loop.run_until_complete(db.close())
        loop.close()


def run(loop, coro):
    return loop.run_until_complete(coro)


def _patch_hot(monkeypatch, *, identity):
    import services.hot_config as hot

    real_get = hot.get

    def fake_get(key, default=None):
        if key == "flags.memory_identity_enabled":
            return identity
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv("MCA_MEMORY_IDENTITY_ENABLED", "on")
    _patch_hot(monkeypatch, identity=True)


@pytest.fixture
def gate_off(monkeypatch):
    monkeypatch.setenv("MCA_MEMORY_IDENTITY_ENABLED", "off")
    _patch_hot(monkeypatch, identity=False)


async def _count(db, table: str, where: str = "", params=()) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    cursor = await db.db.execute(sql, tuple(params))
    return int((await cursor.fetchone())["n"])


async def _rows(db, sql: str, params=()) -> list[list]:
    cursor = await db.db.execute(sql, tuple(params))
    return [list(row) for row in await cursor.fetchall()]


async def _node_id(db, name: str) -> int:
    cursor = await db.db.execute(
        "SELECT id FROM nodes WHERE chat_id = ? AND entity_name = ?",
        (CHAT, name))
    row = await cursor.fetchone()
    return int(row["id"])


async def _author_messages(db, mapping) -> None:
    """`{(uid, author_name)}` → строки `smart_messages` (источник §1.2.1)."""
    cursor = await db.db.execute(
        "SELECT COALESCE(MAX(tg_message_id), 0) AS n FROM smart_messages "
        "WHERE chat_id = ?", (CHAT,))
    base = int((await cursor.fetchone())["n"])
    rows = []
    for index, (uid, name) in enumerate(mapping, start=1):
        rows.append((uid, CHAT, f"msg {index}", index, "text", name, 0, "",
                     base + index, 0))
    await db.db.executemany(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, is_forward, forward_source, tg_message_id, "
        "history_processed) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    await db.db.commit()


async def _seed_same_person(db, entity_type: str = "user") -> tuple[int, int]:
    """Два написания одного человека (uid A): `Папаха`(1) и `папаха`(2)."""
    canonical = await db.upsert_node(CHAT, "Папаха", entity_type)
    member = await db.upsert_node(CHAT, "папаха", entity_type)
    await _author_messages(db, [(UID_A, "Папаха"), (UID_A, "папаха")])
    return canonical, member


async def _freeze(db) -> dict:
    return await baseline.snapshot(db)


# ═══ 1. OFF-паритет писателей (§1.4.1: байт-в-байт) ═══════════════════════

def test_off_write_paths_are_byte_identical_to_base_fixture(env, gate_off):
    """Фикстура снята на `828d1dd1` и переснята после MEMORY-07 §14.1.

    Сценарий (`tests/mem02b_off_baseline.py`) содержит ОБЕ ветки конфликта типа
    (W2-триплет в занятый слот `озон`, факт W1 в занятый слот `папаха`), поэтому
    паритет проверяется не на «удобных» данных.

    Что изменилось в фикстуре и почему это НЕ регрессия identity-паритета:
    * §14.1(A) cron-путь создаёт факт для триплета и передаёт `fact_id` ребру
      (раньше — осознанный NULL): два ребра W2 получили `fact_id` 1/2, две
      факт-строки созданы;
    * §14.1(B) `subject_ref_id` резолвится для любого факта с резолвимым
      субъектом: у факта «папаха работает на заводе» появился ref (uid
      единственный), у «дима живёт в перми» — нет (субъект не резолвится,
      идентичность не выдумана);
    * `nodes`/`identity` — байт-в-байт прежние: паритет OFF-гейта по
      идентичности сохранён.
    """
    db, loop = env
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run(loop, baseline.build_scenario(db))
    assert run(loop, baseline.snapshot(db)) == expected


def test_off_type_slot_conflict_keeps_legacy_edge(env, gate_off):
    """OFF: ребро пишется в существующий узел чужого типа — как было."""
    db, loop = env
    run(loop, db.upsert_node(CHAT, "озон", "fact"))
    memory = _bare_memory(db)
    run(loop, memory._write_graph_triplets(CHAT, [baseline.TRIPLETS[1]]))
    edges = run(loop, _rows(db, "SELECT source_id, target_id FROM edges"))
    assert edges == [[run(loop, _node_id(db, "озон")),
                      run(loop, _node_id(db, "доставка"))]]


def test_on_type_slot_conflict_writes_fact_without_edge(env, gate_on):
    """ON (§1.2.3): чужой тип не подменяется — факт есть, ребра нет."""
    db, loop = env
    run(loop, db.upsert_node(CHAT, "папаха", "topic"))
    memory = _bare_memory(db, response=json.dumps([{
        "subject": "Папаха", "subject_type": "user",
        "predicate": "работает", "object": "на заводе",
        "object_type": "topic", "kind": "durable_fact",
        "source_message_ids": [11]}], ensure_ascii=False))
    run(loop, memory.memorize_facts(CHAT, "Папаха работает на заводе",
                                    "chat_history", tg_message_id=11,
                                    forward_from=""))
    assert run(loop, _count(db, "graph_facts")) == 1
    assert run(loop, _count(db, "edges")) == 0
    assert run(loop, _count(db, "nodes")) == 2      # topic-слот + объект факта


def _bare_memory(db, response: str | None = None):
    from services import summary_memory as sm

    payload = response or baseline.FACT_RESPONSE

    class _LLM:
        async def generate(self, messages):
            return payload

        async def embed(self, texts):
            return [[0.0] * 8 for _ in texts]

    memory = sm.MemoryManager(db, _LLM())
    memory._vec_available = False
    return memory


# ═══ 2. ON: писатели идут в канонический узел (§1.4.1 ID-10) ═══════════════

def _merge_same_person(db, loop, entity_type: str = "user") -> tuple[int, int]:
    canonical, member = run(loop, _seed_same_person(db, entity_type))
    report = run(loop, em.find_duplicate_candidates(db, CHAT, entity_type))
    pair = report.safe_pairs()[0]
    result = run(loop, em.apply_merge(
        db, CHAT, entity_type, pair.member_node_id, pair.canonical_node_id,
        stable_identity=pair.stable_identity))
    assert result.status == em.REASON_MERGED
    return canonical, member


def test_w2_writes_canonical_node_after_merge(env, gate_on):
    db, loop = env
    canonical, member = _merge_same_person(db, loop)
    memory = _bare_memory(db)
    run(loop, memory._write_graph_triplets(CHAT, [
        {"subject": "папаха", "subject_type": "user",
         "predicate": "любит", "object": "ира", "object_type": "user"}]))
    edges = run(loop, _rows(
        db, "SELECT source_id, target_id FROM edges"))
    assert edges == [[canonical, run(loop, _node_id(db, "ира"))]]
    assert run(loop, _count(db, "nodes")) == 3      # новых узлов не появилось


def test_w1_writes_canonical_node_after_merge(env, gate_on):
    """W1: факт-узел со старым написанием сведён — новое ребро на каноническом."""
    db, loop = env
    canonical, member = _merge_same_person(db, loop, "fact")
    memory = _bare_memory(db, response=json.dumps([{
        "subject": "Папаха", "subject_type": "user",
        "predicate": "работает", "object": "на заводе",
        "object_type": "topic", "kind": "durable_fact",
        "source_message_ids": [11]}], ensure_ascii=False))
    run(loop, memory.memorize_facts(CHAT, "Папаха работает на заводе",
                                    "chat_history", tg_message_id=11,
                                    forward_from=""))
    edges = run(loop, _rows(
        db, "SELECT source_id, target_id, fact_id FROM edges"))
    assert len(edges) == 1 and edges[0][0] == canonical
    assert edges[0][2] is not None                  # fact_id доехал до ребра
    assert run(loop, _count(db, "nodes")) == 3      # 2 исходных + объект факта


def test_rerun_does_not_multiply_nodes(env, gate_on):
    """MEM-02.7: повторный прогон писателя не множит узлы/рёбра."""
    db, loop = env
    _merge_same_person(db, loop)
    memory = _bare_memory(db)
    triplets = [{"subject": "папаха", "subject_type": "user",
                 "predicate": "любит", "object": "ира", "object_type": "user"}]
    run(loop, memory._write_graph_triplets(CHAT, triplets))
    nodes_after_first = run(loop, _count(db, "nodes"))
    edges_after_first = run(loop, _count(db, "edges"))
    run(loop, memory._write_graph_triplets(CHAT, triplets))
    assert run(loop, _count(db, "nodes")) == nodes_after_first
    assert run(loop, _count(db, "edges")) == edges_after_first


def test_fact_only_writer_creates_no_nodes(env, gate_on):
    """W5 (`user_memory`): пишет факт, узлов/рёбер не создаёт и идемпотентен."""
    from services.chat_lore import ensure_chat_lore

    db, loop = env
    first = run(loop, ensure_chat_lore(db))
    second = run(loop, ensure_chat_lore(db))
    assert first["inserted"] >= 1 and second["inserted"] == 0
    assert run(loop, _count(db, "nodes")) == 0
    assert run(loop, _count(db, "edges")) == 0
    assert run(loop, _count(db, "graph_facts", "origin = 'user_memory'")) == 1


def test_fact_only_writer_is_gate_invariant(tmp_path, monkeypatch):
    """W5 (`user_memory`): гейт не меняет результат — путь не резолвит сущности."""
    from services.chat_lore import ensure_chat_lore

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    snapshots = {}
    try:
        for mode in ("on", "off"):
            monkeypatch.setenv("MCA_MEMORY_IDENTITY_ENABLED", mode)
            _patch_hot(monkeypatch, identity=(mode == "on"))
            db = DatabaseService(str(tmp_path / f"lore_{mode}.db"))
            loop.run_until_complete(db.initialize())
            try:
                loop.run_until_complete(ensure_chat_lore(db))
                snapshots[mode] = loop.run_until_complete(_freeze(db))
            finally:
                loop.run_until_complete(db.close())
    finally:
        loop.close()
    assert snapshots["on"] == snapshots["off"]
    assert snapshots["on"]["nodes"] == []


def test_no_direct_upsert_node_in_any_writer():
    """§1.4.1: единственная точка создания узла — резолвер.

    Часть B снимает исключение для `summary_memory` (W1/W2 переведены), поэтому
    разрешены только владелец таблицы `database.py` и сам резолвер.
    """
    allowed = {"services/database.py", "services/entity_resolver.py"}
    offenders: list[str] = []
    for path in sorted(REPO_ROOT.glob("services/*.py")) + \
            sorted(REPO_ROOT.glob("web/*.py")) + \
            sorted(REPO_ROOT.glob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "upsert_node"):
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == []


# ═══ 3. B1: dry-run ничего не пишет (§5.3) ════════════════════════════════

def test_dry_run_writes_nothing(env, gate_on, monkeypatch):
    db, loop = env
    run(loop, _seed_same_person(db))
    run(loop, _author_messages(db, [(UID_B, "ира")]))
    before = run(loop, _freeze(db))

    async def _no_write(*args, **kwargs):       # любая запись — провал теста
        raise AssertionError("dry-run попытался писать")

    monkeypatch.setattr(db, "write_transaction", _no_write)
    monkeypatch.setattr(db, "upsert_node", _no_write)
    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    summary = run(loop, em.run_merge_backfill(
        db, chat_id=CHAT, dry_run=True, checkpoint=em.InMemoryCheckpoint()))

    assert report.totals["candidate_pairs"] >= 1
    assert summary["dry_run"] is True and summary["applied"] == 0
    assert run(loop, _freeze(db)) == before
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 0


def test_dry_run_reports_counts_and_reference_impact(env, gate_on):
    db, loop = env
    canonical, member = run(loop, _seed_same_person(db))
    # Одинаковое написание у ДВУХ uid — дефект данных, не слияние (EVAL-04).
    await_rows = [(UID_A, "Саша"), (UID_B, "Саша"), (UID_A, "саша")]
    run(loop, _author_messages(db, await_rows))
    sasha_a = run(loop, db.upsert_node(CHAT, "Саша", "user"))
    sasha_b = run(loop, db.upsert_node(CHAT, "саша", "user"))
    run(loop, db.upsert_edge(canonical, member, "знает"))

    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    by_member = {pair.member_node_id: pair for pair in report.pairs}
    assert report.totals["candidate_pairs"] == 2
    assert report.totals["safe"] == 1
    assert report.totals["ambiguous"] == 1
    assert report.totals["edges_affected"] >= 1
    safe_pair = report.safe_pairs()[0]
    assert set(safe_pair.reasons) >= {em.REASON_SAME_FOLDED_NAME,
                                     em.REASON_STABLE_IDENTITY}
    ambiguous = [pair for pair in report.pairs
                 if pair.verdict == em.PAIR_AMBIGUOUS][0]
    assert ambiguous.reason_code in (em.REASON_IDENTITY_AMBIGUOUS,
                                     em.REASON_IDENTITY_PINNED_ELSEWHERE)
    assert sasha_b in by_member or sasha_a in by_member
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 0


def test_dry_run_report_is_deterministic(env, gate_on):
    db, loop = env
    run(loop, _seed_same_person(db))
    first = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    second = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    assert first.as_dict() == second.as_dict()


# ═══ 4. B2: безопасное слияние и откат ════════════════════════════════════

def test_apply_safe_merge_preserves_every_reference_and_is_reversible(
        env, gate_on):
    db, loop = env
    canonical, member = run(loop, _seed_same_person(db))
    topic = run(loop, db.upsert_node(CHAT, "завод", "topic"))
    fact_id = run(loop, db.insert_graph_fact(
        CHAT, "папаха работает на заводе", "chat_history", None,
        subject="папаха", object="завод", subject_ref_id=member,
        status="unconfirmed", weight=0.7))
    run(loop, db.upsert_edge(member, topic, "работает", fact_id=fact_id))
    run(loop, db.upsert_edge(canonical, topic, "работает", fact_id=None))
    before = {
        "nodes": run(loop, _count(db, "nodes")),
        "edges": run(loop, _count(db, "edges")),
        "facts": run(loop, _count(db, "graph_facts")),
        "fts": run(loop, _count(db, "graph_facts_fts")),
    }
    edge_rows_before = run(loop, _rows(
        db, "SELECT id, source_id, target_id, weight, fact_id FROM edges "
            "ORDER BY id"))

    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    pair = report.safe_pairs()[0]
    result = run(loop, em.apply_merge(
        db, CHAT, "user", pair.member_node_id, pair.canonical_node_id,
        stable_identity=pair.stable_identity))
    assert result.status == em.REASON_MERGED
    assert result.legacy_id == pair.member_node_id
    assert result.canonical_id == pair.canonical_node_id

    # Ни одна строка не удалена и не переписана.
    assert {
        "nodes": run(loop, _count(db, "nodes")),
        "edges": run(loop, _count(db, "edges")),
        "facts": run(loop, _count(db, "graph_facts")),
        "fts": run(loop, _count(db, "graph_facts_fts")),
    } == before
    assert run(loop, _rows(
        db, "SELECT id, source_id, target_id, weight, fact_id FROM edges "
            "ORDER BY id")) == edge_rows_before

    # Аудит: member → canonical сохранён в самой строке.
    row = run(loop, _rows(
        db, "SELECT member_node_id, canonical_node_id, resolution, status, "
            "stable_value, method FROM mca_entity_canonical"))
    assert row == [[member, canonical, er.RESOLUTION_MERGED, er.STATUS_ACTIVE,
                    str(UID_A), er.METHOD_EXPLICIT_EVIDENCE]]

    # §2.5: агрегат схлопывает member и canonical, ни один fact_id не потерян.
    aggregated = run(loop, em.aggregate_edges(db, CHAT))
    fact_ids = {fid for item in aggregated for fid in item.fact_ids}
    assert fact_id in fact_ids
    assert all(item.edge_id == min([item.edge_id, *item.legacy_edge_ids])
               for item in aggregated)
    hit = [item for item in aggregated if item.target_id == topic][0]
    assert hit.source_id == canonical
    assert hit.fact_ids == (fact_id,)

    # Чтение после слияния: member резолвится в canonical (§1.4).
    resolved = run(loop, er.resolve_entity(
        db, scope={"chat_id": CHAT, "entity_type": "user"},
        mention="папаха"))
    assert resolved.canonical.node_id == canonical

    # Откат: `revoked`, данные и аудит остаются, member снова сам себе.
    assert run(loop, em.revoke_merge(db, CHAT, "user", member)) is True
    assert run(loop, _rows(
        db, "SELECT member_node_id, canonical_node_id, status "
            "FROM mca_entity_canonical")) == [[member, canonical,
                                               er.STATUS_REVOKED]]
    again = run(loop, er.resolve_entity(
        db, scope={"chat_id": CHAT, "entity_type": "user"},
        mention="папаха"))
    assert again.canonical.node_id == member
    assert run(loop, _count(db, "nodes")) == before["nodes"]


def test_apply_refuses_pair_without_stable_identity(env, gate_on):
    """MEM-02.8: тождество не доказано → слияния нет (никогда)."""
    db, loop = env
    first = run(loop, db.upsert_node(CHAT, "Папаха", "user"))
    second = run(loop, db.upsert_node(CHAT, "папаха", "user"))
    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    pair = report.pairs[0]
    assert pair.verdict == em.PAIR_REFUSED
    assert pair.reason_code == em.REASON_IDENTITY_NOT_PROVEN
    assert pair.stable_identity is None

    refused = run(loop, em.apply_merge(db, CHAT, "user", second, first))
    assert refused.status == em.PAIR_REFUSED
    assert refused.reason_code == em.REASON_IDENTITY_NOT_PROVEN

    forged = run(loop, em.apply_merge(
        db, CHAT, "user", second, first,
        stable_identity={"kind": "tg_user", "value": UID_B}))
    assert forged.status == em.PAIR_REFUSED
    assert forged.reason_code == em.REASON_IDENTITY_NOT_PROVEN
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 0


def test_same_name_two_uids_stay_separate(env, gate_on):
    """MEM-02.8: «Саша» у двух людей — два узла, `ambiguous`, ноль слияний."""
    db, loop = env
    run(loop, _author_messages(db, [(UID_A, "Саша"), (UID_B, "Саша"),
                                   (UID_A, "саша")]))
    first = run(loop, db.upsert_node(CHAT, "Саша", "user"))
    second = run(loop, db.upsert_node(CHAT, "саша", "user"))
    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    pair = report.pairs[0]
    assert pair.verdict == em.PAIR_AMBIGUOUS
    assert pair.reason_code == em.REASON_IDENTITY_AMBIGUOUS
    refused = run(loop, em.apply_merge(
        db, CHAT, "user", second, first,
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert refused.status == em.PAIR_REFUSED
    assert refused.reason_code == em.REASON_IDENTITY_AMBIGUOUS
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 0


def test_similarity_and_shared_source_never_prove_identity(env, gate_on):
    """MEM-02.8: сходство/общий источник — не доказательство тождества.

    Сходство эмбеддингов в решениях не участвует вообще: модуль не читает
    `*_vec`/`embedding` и не считает cosine (проверяется статически), а пара с
    общим исходным сообщением и без общего uid остаётся `refused`.
    """
    source = (REPO_ROOT / "services" / "entity_merge.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    forbidden_attrs = {"embed", "embedding", "cosine", "similarity",
                       "_vec_available"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attrs, node.attr
        if isinstance(node, ast.Name):
            lowered = node.id.lower()
            assert "embed" not in lowered and "cosine" not in lowered, node.id
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            module = getattr(node, "module", "") or ""
            for name in names + [module]:
                assert "embedding" not in name and "vec" not in name, name

    db, loop = env
    first = run(loop, db.upsert_node(CHAT, "Папаха", "user"))
    second = run(loop, db.upsert_node(CHAT, "папаха", "user"))
    run(loop, _author_messages(db, [(UID_A, "Папаха"), (UID_B, "папаха")]))
    run(loop, db.insert_graph_fact(
        CHAT, "папаха и папаха в одном сообщении", "chat_history", None,
        subject="Папаха", object="папаха", tg_message_id=777,
        subject_ref_id=first))
    run(loop, db.insert_graph_fact(
        CHAT, "и ещё раз", "chat_history", None, subject="папаха",
        object="завод", tg_message_id=777, subject_ref_id=second))

    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    pair = report.pairs[0]
    assert em.REASON_SOURCE_OVERLAP in pair.reasons
    assert pair.verdict == em.PAIR_REFUSED
    assert pair.reason_code == em.REASON_IDENTITY_NOT_PROVEN


def test_redirect_depth_one_and_cycle_are_refused(env, gate_on):
    """§1.4.2: глубина 1 терминальна, цепочка/цикл — отказ, не «выпрямление»."""
    db, loop = env
    canonical, member = _merge_same_person(db, loop)
    third = run(loop, db.upsert_node(CHAT, "папаха2", "user"))

    chain_reason, _ = run(loop, em.validate_merge(
        db, CHAT, "user", canonical, third,
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert chain_reason == em.REASON_REDIRECT_CHAIN

    cycle_reason, _ = run(loop, em.validate_merge(
        db, CHAT, "user", canonical, member,
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert cycle_reason == em.REASON_REDIRECT_CYCLE
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 1


def test_seeded_canonical_absorbs_duplicate_spelling(env, gate_on):
    """Реальный сценарий: засеянная self-строка + второе написание того же uid.

    `seed_self_identity` закрепляет uid за узлом `Папаха`; позже извлечение
    создаёт узел `папаха`. Self-строка НЕ является redirect'ом, поэтому слияние
    обязано проходить (§1.4.2: глубина 1 — про редиректы, не про засев), uid не
    дублируется (частичный UNIQUE цел), обе формы сходятся в один узел, откат
    возвращает member к самому себе. Регрессия F1 ревью MEMORY-02B.
    """
    db, loop = env
    canonical = run(loop, db.upsert_node(CHAT, "Папаха", "user"))
    run(loop, _author_messages(db, [(UID_A, "Папаха"), (UID_A, "папаха")]))
    seeded = run(loop, er.seed_self_identity(db, CHAT, UID_A))
    assert seeded.status == er.SEED_SEEDED and seeded.node_id == canonical

    member = run(loop, db.upsert_node(CHAT, "папаха", "user"))
    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    assert report.totals["candidate_pairs"] == 1
    pair = report.safe_pairs()[0]
    assert (pair.member_node_id, pair.canonical_node_id) == (member, canonical)
    assert pair.reason_code == em.REASON_STABLE_IDENTITY

    result = run(loop, em.apply_merge(
        db, CHAT, "user", pair.member_node_id, pair.canonical_node_id,
        stable_identity=pair.stable_identity))
    assert result.status == em.REASON_MERGED, result.as_dict()

    # Обе формы сходятся в канонический узел.
    for spelling in ("Папаха", "папаха"):
        resolved = run(loop, er.resolve_entity(
            db, scope={"chat_id": CHAT, "entity_type": "user"},
            mention=spelling))
        assert resolved.canonical.node_id == canonical, spelling

    # Частичный UNIQUE цел: ровно одна АКТИВНАЯ строка с этим uid.
    active_uid_rows = run(loop, _rows(
        db, "SELECT member_node_id, canonical_node_id, resolution, status "
            "FROM mca_entity_canonical WHERE status = 'active' "
            "AND stable_kind = 'tg_user' AND stable_value = ?",
        (str(UID_A),)))
    assert len(active_uid_rows) == 1
    assert active_uid_rows[0][1] == canonical
    merged_row = run(loop, _rows(
        db, "SELECT stable_kind, stable_value FROM mca_entity_canonical "
            "WHERE member_node_id = ?", (member,)))
    assert merged_row == [[None, None]]

    # Откат: member снова сам себе, канонический узел не тронут.
    assert run(loop, em.revoke_merge(db, CHAT, "user", member)) is True
    reverted = run(loop, er.resolve_entity(
        db, scope={"chat_id": CHAT, "entity_type": "user"},
        mention="папаха"))
    assert reverted.canonical.node_id == member
    still = run(loop, er.resolve_entity(
        db, scope={"chat_id": CHAT, "entity_type": "user"},
        mention="Папаха"))
    assert still.canonical.node_id == canonical


def test_self_row_is_not_a_redirect_but_foreign_uid_still_refused(env, gate_on):
    """Self-строка не «цепочка», но чужой uid по-прежнему блокирует слияние."""
    db, loop = env
    first = run(loop, db.upsert_node(CHAT, "Ира", "user"))
    second = run(loop, db.upsert_node(CHAT, "ира", "user"))
    # Данные-дефект: узел закреплён за uid A, а наблюдается только у uid B.
    run(loop, db.db.execute(
        "INSERT INTO mca_entity_canonical (chat_id, entity_type, "
        "member_node_id, canonical_node_id, resolution, stable_kind, "
        "stable_value, method, confidence, status, created_at, updated_at) "
        "VALUES (?, 'user', ?, ?, 'self', 'tg_user', ?, 'alias_map', "
        "'confirmed', 'active', 1, 1)",
        (CHAT, first, first, str(UID_A))))
    run(loop, _author_messages(db, [(UID_B, "Ира"), (UID_B, "ира")]))

    reason, detail = run(loop, em.validate_merge(
        db, CHAT, "user", second, first,
        stable_identity={"kind": "tg_user", "value": UID_B}))
    assert reason == em.REASON_IDENTITY_PINNED_ELSEWHERE, detail

    refused = run(loop, em.apply_merge(
        db, CHAT, "user", second, first,
        stable_identity={"kind": "tg_user", "value": UID_B}))
    assert refused.status == em.PAIR_REFUSED
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 1


def test_backfill_merges_seeded_person_with_second_spelling(env, gate_on):
    """Бэкфилл B2 больше не «тихий no-op» для засеянного человека (F1 ревью)."""
    db, loop = env
    canonical = run(loop, db.upsert_node(CHAT, "Папаха", "user"))
    run(loop, _author_messages(db, [(UID_A, "Папаха"), (UID_A, "папаха")]))
    assert run(loop, er.seed_self_identity(
        db, CHAT, UID_A)).status == er.SEED_SEEDED
    member = run(loop, db.upsert_node(CHAT, "папаха", "user"))

    summary = run(loop, em.run_merge_backfill(
        db, chat_id=CHAT, dry_run=False, checkpoint=em.InMemoryCheckpoint()))
    assert summary["candidate_pairs"] == 1
    assert summary["safe_pairs"] == 1
    assert summary["attempted_pairs"] == 1
    assert summary["applied"] == 1 and summary["errors"] == 0

    for spelling in ("Папаха", "папаха"):
        resolved = run(loop, er.resolve_entity(
            db, scope={"chat_id": CHAT, "entity_type": "user"},
            mention=spelling))
        assert resolved.canonical.node_id == canonical
    rows = run(loop, _rows(
        db, "SELECT member_node_id, canonical_node_id, status "
            "FROM mca_entity_canonical WHERE status = 'active' "
            "AND stable_value = ?", (str(UID_A),)))
    assert rows == [[canonical, canonical, er.STATUS_ACTIVE]]
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 2


# ═══ 5. Чекпоинт / resume / идемпотентность (§5.3 B2) ══════════════════════
async def _two_safe_pairs(db) -> None:
    await _seed_same_person(db)
    await _author_messages(db, [(UID_B, "Ира"), (UID_B, "ира")])
    await db.upsert_node(CHAT, "Ира", "user")
    await db.upsert_node(CHAT, "ира", "user")


def test_backfill_applies_safe_pairs_and_resumes(env, gate_on):
    """Чекпоинт делает прогон возобновляемым: откат админа не воскресает."""
    db, loop = env
    run(loop, _two_safe_pairs(db))
    checkpoint = em.InMemoryCheckpoint()
    first = run(loop, em.run_merge_backfill(
        db, chat_id=CHAT, dry_run=False, checkpoint=checkpoint))
    assert first["applied"] == 2 and first["attempted_pairs"] == 2

    member, canonical = run(loop, _rows(
        db, "SELECT member_node_id, canonical_node_id "
            "FROM mca_entity_canonical ORDER BY member_node_id"))[0]
    assert run(loop, em.revoke_merge(db, CHAT, "user", member)) is True
    # Отозванная пара снова видна детектору (данные не тронуты).
    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    assert report.totals["candidate_pairs"] == 1

    resumed = run(loop, em.run_merge_backfill(
        db, chat_id=CHAT, dry_run=False, checkpoint=checkpoint))
    assert resumed["resumed_skips"] == 1     # уже обработанная пара не переприменяется
    assert resumed["attempted_pairs"] == 0
    assert resumed["applied"] == 0
    statuses = run(loop, _rows(
        db, "SELECT member_node_id, status FROM mca_entity_canonical "
            "ORDER BY member_node_id"))
    assert statuses == [[2, er.STATUS_REVOKED], [4, er.STATUS_ACTIVE]]

    # Без чекпоинта прогон полный: явное/повторное применение оживляет пару
    # (§1.4.2 — ремонт возможен только новым слиянием, не автоматически).
    fresh = run(loop, em.run_merge_backfill(
        db, chat_id=CHAT, dry_run=False, checkpoint=em.InMemoryCheckpoint()))
    assert fresh["attempted_pairs"] == 1 and fresh["applied"] == 1
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 2


def test_backfill_without_checkpoint_is_idempotent(env, gate_on):
    db, loop = env
    run(loop, _two_safe_pairs(db))
    first = run(loop, em.run_merge_backfill(db, chat_id=CHAT, dry_run=False))
    assert first["applied"] == 2
    report = run(loop, em.find_duplicate_candidates(db, CHAT, "user"))
    assert report.totals["candidate_pairs"] == 0     # дублей больше не видно
    second = run(loop, em.run_merge_backfill(db, chat_id=CHAT, dry_run=False))
    assert second["applied"] == 0
    # Прямой повтор того же слияния — no-op (PK), второй строки нет.
    member, canonical = run(loop, _rows(
        db, "SELECT member_node_id, canonical_node_id "
            "FROM mca_entity_canonical ORDER BY member_node_id"))[0]
    again = run(loop, em.apply_merge(
        db, CHAT, "user", member, canonical,
        stable_identity={"kind": "tg_user", "value": UID_A}))
    assert again.status == em.REASON_ALREADY_MERGED
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 2


def test_backfill_apply_requires_identity_gate(env, gate_off):
    db, loop = env
    run(loop, _two_safe_pairs(db))
    summary = run(loop, em.run_merge_backfill(
        db, chat_id=CHAT, dry_run=False, checkpoint=em.InMemoryCheckpoint()))
    assert summary["gate_off"] == 1 and summary["applied"] == 0
    assert run(loop, _count(db, er.ENTITY_CANONICAL_TABLE)) == 0


def test_task_jobs_checkpoint_roundtrip(env):
    db, loop = env
    store = em.TaskJobsCheckpoint(db)
    assert run(loop, store.load()) == {}
    run(loop, store.save({"version": 1, "processed": ["a"], "applied": 3}))
    assert run(loop, store.load())["processed"] == ["a"]
    run(loop, store.save({"version": 1, "processed": ["a", "b"], "applied": 4}))
    loaded = run(loop, store.load())
    assert loaded["processed"] == ["a", "b"] and loaded["applied"] == 4
