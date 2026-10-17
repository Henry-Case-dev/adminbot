"""SOUL-1 / W4 — SOUL-07: Few-Shot библиотека, отбор, A/B, изоляция.

Покрытие (requirements-map.json W4):
  * SOUL-07.0/07.1 — таблица `humor_samples` (единственная новая таблица
    слайса), стартовая подборка 15–30 ОРИГИНАЛЬНЫХ и разных по композиции
    примеров как НЕодобренные черновики; полный CRUD/архив/ревизия;
  * SOUL-07.2 — 1–3 уместных и различных примера либо ни одного; семантика,
    diversity, recency/penalty, пригодность к extent; жёсткая cross-chat/PII
    изоляция (двойная защита: запись + отбор);
  * SOUL-07.3 — A/B версий библиотеки, «почему выбраны именно эти примеры»,
    различение owner/bot/verified, импорт ≠ владельческое одобрение.

TEST-LIFECYCLE: CONTRACT owner=soul-1/W4
"""
import dataclasses

import pytest
import pytest_asyncio

from services import mca_sample_library as sl
from services.database import DatabaseService


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "w4-samples.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


def _row(**overrides) -> dict:
    base = {
        "id": 1, "input_text": "вход", "reply_text": "ответ про чайник",
        "technique": "deadpan", "context_note": "", "language": "ru",
        "tags": [], "rudeness_level": 1, "source_kind": "owner_manual",
        "scope": "global", "chat_id": None, "owner_approved": 1,
        "status": "active", "library_version": "v1", "revision": 1,
        "uses_count": 0, "last_used_at": None, "sensitivity_flags": [],
    }
    base.update(overrides)
    return base


# ═══ SOUL-07.0/07.1: схема, стартовая подборка, CRUD ═══════════════════════

def test_schema_version_matches_database_constant():
    from services import database as dbmod
    assert (sl.SCHEMA_VERSION_HUMOR_SAMPLES
            == dbmod._SCHEMA_VERSION_HUMOR_SAMPLES)


@pytest.mark.asyncio
async def test_migration_creates_table_and_indexes(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='humor_samples'")
    assert await cursor.fetchone() is not None
    assert await sl.table_ready(db) is True
    cols = {row[1] for row in await (await db.db.execute(
        "PRAGMA table_info(humor_samples)")).fetchall()}
    for required in ("input_text", "reply_text", "technique", "context_note",
                     "language", "tags", "rudeness_level", "author_user_id",
                     "source_kind", "scope", "chat_id", "owner_approved",
                     "status", "library_version", "revision"):
        assert required in cols, required


def test_starter_set_is_original_diverse_and_unapproved():
    rows = sl.STARTER_SAMPLES
    assert 15 <= len(rows) <= 30, len(rows)
    seeds = [r["seed_key"] for r in rows]
    assert len(set(seeds)) == len(seeds)
    techniques = {r["technique"] for r in rows}
    assert len(techniques) >= 4
    assert "other" in techniques            # серьёзные ответы тоже в наборе
    inputs = {r["input_text"] for r in rows}
    assert len(inputs) == len(rows)         # без копий одного мема
    for row in rows:
        assert str(row["input_text"]).strip()
        assert str(row["reply_text"]).strip()
        assert row["technique"] in sl.SAMPLE_TECHNIQUES
        assert 0 <= int(row.get("rudeness_level", 0)) <= sl.MAX_RUDENESS
        assert "owner_approved" not in row   # одобрение ставит только владелец
        assert not sl.scan_sensitivity(row["input_text"], row["reply_text"])


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_drafts_stay_unapproved(db):
    first = await sl.seed_starter_samples(db)
    assert first["seeded"] == len(sl.STARTER_SAMPLES)
    second = await sl.seed_starter_samples(db)
    assert second["seeded"] == 0
    assert second["skipped"] == len(sl.STARTER_SAMPLES)
    rows = await sl.list_samples(db, chat_id=None, status=None, limit=500)
    assert len(rows) == len(sl.STARTER_SAMPLES)
    for row in rows:
        assert row["owner_approved"] is False
        assert row["approval"] == "proposed"
        assert row["source_kind"] == "bot_suggested"
        assert row["library_version"] == sl.STARTER_LIBRARY_VERSION


@pytest.mark.asyncio
async def test_crud_roundtrip_with_revision_guard(db):
    view, reason = await sl.create_sample(db, fields={
        "input_text": "Ну и погода", "reply_text": "Климат подал иск",
        "technique": "absurd_escalation", "tags": "погода, быт",
        "rudeness_level": 2, "source_kind": "owner_manual",
        "scope": "global"}, actor="owner")
    assert view is not None, reason
    assert view["revision"] == 1 and view["owner_approved"] is False
    assert view["tags"] == ["погода", "быт"]

    updated, reason = await sl.update_sample(
        db, view["id"], fields={"reply_text": "Климат подал иск в суд"},
        actor="owner", expected_revision=1)
    assert updated is not None and updated["revision"] == 2, reason
    stale, reason = await sl.update_sample(
        db, view["id"], fields={"reply_text": "нет"}, actor="owner",
        expected_revision=1)
    assert stale is None and reason == "revision_conflict"

    approved, reason = await sl.set_approval(db, view["id"], approved=True,
                                             actor="owner")
    assert approved["owner_approved"] is True and approved["approval"] == \
        "approved", reason
    archived, _ = await sl.archive_sample(db, view["id"], archived=True,
                                          actor="owner")
    assert archived["status"] == "archived"
    ok, reason = await sl.delete_sample(db, view["id"])
    assert ok is True and await sl.get_sample(db, view["id"]) is None


@pytest.mark.asyncio
async def test_write_rejects_pii_and_missing_fields(db):
    bad, reason = await sl.create_sample(db, fields={
        "input_text": "привет @nickname", "reply_text": "ответ"})
    assert bad is None and reason.startswith("sensitive:")
    bad, reason = await sl.create_sample(db, fields={
        "input_text": "почта a.b@example.org", "reply_text": "ответ"})
    assert bad is None and reason.startswith("sensitive:")
    bad, reason = await sl.create_sample(db, fields={"input_text": "",
                                                     "reply_text": "x"})
    assert bad is None and reason == "empty_input_text"
    bad, reason = await sl.create_sample(db, fields={
        "input_text": "x", "reply_text": "y", "scope": "chat"})
    assert bad is None and reason == "chat_scope_without_chat"


# ═══ SOUL-07.2: отбор ═════════════════════════════════════════════════════

def test_selection_returns_only_owner_approved_globals():
    rows = [
        _row(id=1, owner_approved=1),
        _row(id=2, owner_approved=0, technique="literalism"),
        _row(id=3, owner_approved=1, status="archived", technique="deadpan"),
    ]
    selection = sl.select_samples(rows, chat_id=7, technique="deadpan",
                                  extent="normal", policy=sl.DEFAULT_POLICY)
    picked = {int(r["id"]) for r in selection.samples}
    assert picked == {1}
    reasons = {e["id"]: e["reason"] for e in selection.excluded}
    assert reasons[2] == "not_owner_approved"
    assert reasons[3] == "archived"


def test_cross_chat_isolation_is_hard():
    rows = [
        _row(id=1, technique="deadpan"),
        _row(id=2, scope="chat", chat_id=999, technique="deadpan",
             input_text="чужой чат"),
        _row(id=3, scope="chat", chat_id=7, technique="literalism",
             input_text="свой чат", reply_text="другая реплика для этого чата"),
    ]
    selection = sl.select_samples(rows, chat_id=7, policy=sl.DEFAULT_POLICY)
    picked = {int(r["id"]) for r in selection.samples}
    assert 2 not in picked
    assert 3 in picked and 1 in picked
    assert {"id": 2, "reason": "cross_chat_guard"} in [
        dict(e) for e in selection.excluded]


def test_global_chat_scope_is_not_returned_to_other_chats():
    rows = [_row(id=1, scope="chat", chat_id=7)]
    selection = sl.select_samples(rows, chat_id=8, policy=sl.DEFAULT_POLICY)
    assert selection.samples == ()
    assert selection.reason_code == "samples_absent"


def test_leakage_guard_double_defence_on_selection():
    rows = [
        _row(id=1),
        _row(id=2, technique="literalism", reply_text="иной ответ",
             input_text="звони 8 916 123 45 67"),
        _row(id=3, technique="unexpected_analogy", reply_text="третий ответ",
             input_text="почта a.b@example.org"),
        _row(id=4, technique="absurd_escalation", reply_text="четвёртый",
             sensitivity_flags=["mention"], input_text="уже помечен"),
    ]
    selection = sl.select_samples(rows, chat_id=7, policy=sl.DEFAULT_POLICY)
    picked = {int(r["id"]) for r in selection.samples}
    assert picked == {1}
    reasons = {int(e["id"]): e["reason"] for e in selection.excluded}
    assert reasons[2] == "leakage_guard"      # скан на отборе
    assert reasons[3] == "leakage_guard"
    assert reasons[4] == "leakage_guard"      # запись уже помечена


def test_selection_respects_extent_fit_and_budget():
    long_reply = " ".join(["слово"] * 60)
    rows = [_row(id=1, reply_text=long_reply, technique="deadpan")]
    for extent in ("micro", "compact"):
        selection = sl.select_samples(rows, chat_id=7, extent=extent,
                                      policy=sl.DEFAULT_POLICY)
        assert selection.samples == ()
        assert {"id": 1, "reason": "extent_fit"} in [
            dict(e) for e in selection.excluded]
    one_word = sl.select_samples(rows, chat_id=7, extent="one_word",
                                 policy=sl.DEFAULT_POLICY)
    assert one_word.reason_code == "samples_extent_fit"


def test_selection_is_diverse_and_bounded():
    rows = []
    for idx in range(1, 7):
        rows.append(_row(id=idx, technique="deadpan" if idx <= 3 else
                         "literalism",
                         reply_text=f"ответ номер {idx} про разные вещи",
                         input_text=f"вход {idx}"))
    policy = dict(sl.DEFAULT_POLICY, max_items=3, max_per_technique=1)
    selection = sl.select_samples(rows, chat_id=7, policy=policy)
    assert 1 <= len(selection.samples) <= 3
    techniques = [r["technique"] for r in selection.samples]
    assert len(set(techniques)) == len(techniques)
    assert all(r["why"] for r in selection.reasons)
    assert all(r["estimated_tokens"] > 0 for r in selection.reasons)


def test_policy_is_clamped_and_disabled_means_no_layer():
    normalized = sl.normalize_policy({"max_items": 99, "max_tokens": 5,
                                      "diversity_min_distance": 5,
                                      "recency_penalty": -3,
                                      "ab_versions": ["a"]})
    assert normalized["max_items"] == 3
    assert normalized["max_tokens"] == 40
    assert normalized["diversity_min_distance"] == 0.9
    assert normalized["recency_penalty"] == 0.0
    assert normalized["ab_versions"] == list(sl.DEFAULT_POLICY["ab_versions"])
    off = sl.select_samples([_row()], chat_id=7,
                            policy=dict(sl.DEFAULT_POLICY, enabled=False))
    assert off.reason_code == "samples_disabled"


def test_recency_penalty_prefers_less_recently_used():
    rows = [
        _row(id=1, last_used_at=1000, uses_count=5),
        _row(id=2, technique="literalism", reply_text="другой ответ"),
    ]
    policy = dict(sl.DEFAULT_POLICY, max_items=1, recency_penalty=0.5,
                  max_per_technique=1)
    selection = sl.select_samples(rows, chat_id=7, policy=policy,
                                  now_ts=1000)
    assert [int(r["id"]) for r in selection.samples] == [2]
    reasons = {int(e["id"]): e["reason"] for e in selection.excluded}
    assert reasons.get(1) in ("below_min_score", "max_items", "same_technique")


def test_technique_bonus_follows_l1_advice():
    rows = [_row(id=1, technique="deadpan"),
            _row(id=2, technique="literalism", reply_text="иной ответ")]
    policy = dict(sl.DEFAULT_POLICY, max_items=1, max_per_technique=2)
    selection = sl.select_samples(rows, chat_id=7, technique="literalism",
                                  policy=policy)
    assert [int(r["id"]) for r in selection.samples] == [2]


# ═══ SOUL-07.3: A/B и «почему выбраны» ════════════════════════════════════

def test_ab_assignment_is_deterministic_and_pins_a_version():
    policy = dict(sl.DEFAULT_POLICY, ab_enabled=True,
                  ab_versions=["v1", "v2"], ab_weight=0.5)
    first = sl.ab_version_for(4242, policy)
    assert first in ("v1", "v2")
    assert first == sl.ab_version_for(4242, policy)
    rows = [_row(id=1, library_version="v1"),
            _row(id=2, library_version="v2", technique="literalism")]
    selection = sl.select_samples(rows, chat_id=4242, policy=policy)
    assert selection.library_version == first
    for row in selection.samples:
        assert row["library_version"] == first
    assert sl.ab_version_for(7, sl.DEFAULT_POLICY) == ""   # A/B выключен


def test_render_block_is_bounded_and_has_no_real_names():
    rows = [_row(id=1), _row(id=2, technique="literalism")]
    block = sl.render_block(rows)
    assert block.startswith("<Examples>") and block.endswith("</Examples>")
    assert "механизм мышления" in block
    assert "Вход:" in block and "Ответ:" in block
    assert len(block) <= sl.MAX_TOTAL_CHARS
    assert sl.render_block([]) == ""


def test_registry_block_is_registered_with_factory_text():
    from services import prompt_registry as pr
    spec = pr.block("humor.few_shot.block")
    assert spec is not None and spec.owner_lane == "W4"
    assert pr.factory_text("humor.few_shot.block") == sl.HUMOR_FEW_SHOT_TEMPLATE
    assert "механизм мышления" in pr.factory_text("humor.few_shot.block")


# ═══ интеграция с БД: отбор из реальной таблицы + телеметрия ══════════════

@pytest.mark.asyncio
async def test_runtime_selection_from_db_marks_usage_and_reports_telemetry(
        db, monkeypatch):
    from services import hot_config

    class _Catalog:
        def get(self, key, default=None):
            return True

    monkeypatch.setenv("HUMOR_LIBRARY_ENABLED", "1")
    hot_config.set_config_cache(_Catalog())
    await sl.seed_starter_samples(db)
    empty = await sl.telemetry(db, chat_id=7)
    assert empty["available"] is True
    assert empty["approved"] == 0 and empty["proposed"] == len(
        sl.STARTER_SAMPLES)
    assert empty["starter_seeded"] == len(sl.STARTER_SAMPLES)

    rows = await sl.list_samples(db, chat_id=7, status="active", limit=500)
    assert rows and all(row["approval"] == "proposed" for row in rows)
    # черновики в runtime не идут
    refs, selection = await sl.resolve_refs(chat_id=7, technique="deadpan",
                                            extent="normal", db=db)
    assert refs == () and selection.reason_code == "samples_absent"

    target = rows[0]
    await sl.set_approval(db, target["id"], approved=True, actor="owner")
    refs, selection = await sl.resolve_refs(chat_id=7,
                                            technique=target["technique"],
                                            extent="normal", db=db)
    assert refs, selection.reason_code
    assert all(r.library_version for r in refs)
    after = await sl.get_sample(db, target["id"])
    assert after["uses_count"] == 1 and after["last_used_at"]
    telemetry = await sl.telemetry(db, chat_id=7)
    assert telemetry["approved"] == 1 and telemetry["uses_total"] == 1
    hot_config.set_config_cache(None)


@pytest.mark.asyncio
async def test_policy_chat_override_does_not_leak_to_other_chat(monkeypatch):
    from services import chat_params, hot_config

    class _Cache:
        def __init__(self, values):
            self.values = values

        async def get_chat_params(self, chat_id):
            return {"overrides": self.values.get(int(chat_id), {})}

        async def get_chat_params_full(self, chat_id):
            return await self.get_chat_params(chat_id), None

    class _Hot:
        def get(self, key, default=None):
            return default

    hot_config.set_config_cache(_Hot())
    chat_params.set_chat_params_cache(_Cache({7: {
        sl.SELECTION_DOC_KEY: {"max_items": 1, "ab_enabled": True,
                               "ab_versions": ["v1", "v2"]}}}))
    try:
        policy_a, source_a = await sl.resolve_policy(7)
        policy_b, source_b = await sl.resolve_policy(8)
        assert source_a == "chat" and policy_a["max_items"] == 1
        assert source_b == "default" and policy_b["max_items"] == 3
        assert policy_b["ab_enabled"] is False
    finally:
        hot_config.set_config_cache(None)
        chat_params.set_chat_params_cache(None)
