# -*- coding: utf-8 -*-
"""ADD-SAMPLES-UX §3 (SU-SEED) — заводские наборы: tombstone, идемпотентность,
force-модель, «Изменено владельцем», явное восстановление.

Тест-последовательности контракта (SU-PERSIST.*):
  * edit → seed → persists (+ метка «Изменено владельцем»);
  * delete → seed → remains deleted (постоянный tombstone по seed_key);
  * explicit restore → restored (только confirm=True; один пример не
    трогает остальные);
  * параллельная правка → revision_conflict без потери данных;
  * повторные seed/deploy/restart (повторный вызов сида) не перезаписывают,
    не реактивируют и не переутверждают изменённые/удалённые карточки;
  * force у сида не воскресает tombstone и не перетирает правки;
  * владельческие данные читаются даже при отсутствии набора в коде.

TEST-LIFECYCLE: REGRESSION owner=SAMPLES-UX/SU-PERSIST.* (§3, 20.10.2026)
"""
import pytest
import pytest_asyncio

from services import mca_sample_library as sl
from services.database import DatabaseService

REPO_ROOT = sl.__file__


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "samples-persist.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


async def _seeded_factory_row(db):
    """Заводская юмор-карточка (сеется как черновик)."""
    result = await sl.seed_starter_samples(db)
    assert result["seeded"] == len(sl.STARTER_SAMPLES)
    rows = await sl.list_samples(db, chat_id=None, category="humor")
    assert rows
    return rows[0]


# ═══ edit → seed → persists (+ «Изменено владельцем») ══════════════════════

@pytest.mark.asyncio
async def test_edit_survives_reseed_with_override_mark(db):
    row = await _seeded_factory_row(db)
    edited, reason = await sl.update_sample(
        db, row["id"], fields={"reply_text": "моя редакция ответа"},
        actor="owner", expected_revision=row["revision"])
    assert edited is not None, reason
    assert edited["origin"] == "modified"
    assert edited["owner_modified"] is True
    assert edited["owner_modified_at"]
    # повторный сид (деплой/рестарт) НЕ перетирает правку
    again = await sl.seed_starter_samples(db)
    assert again["seeded"] == 0 and again["skipped"] == \
        len(sl.STARTER_SAMPLES)
    after = await sl.get_sample(db, row["id"])
    assert after["reply_text"] == "моя редакция ответа"
    assert after["owner_modified"] is True
    # даже force-вызов сида не перетирает владельческую правку
    await sl.seed_starter_samples(db, force=True)
    after_force = await sl.get_sample(db, row["id"])
    assert after_force["reply_text"] == "моя редакция ответа"


@pytest.mark.asyncio
async def test_reseed_does_not_reactivate_or_reapprove(db):
    await sl.seed_starter_samples(db)
    rows = await sl.list_samples(db, chat_id=None, category="humor")
    row = rows[0]
    await sl.set_approval(db, row["id"], approved=True, actor="owner")
    await sl.archive_sample(db, row["id"], archived=True, actor="owner")
    before = await sl.get_sample(db, row["id"])
    await sl.seed_starter_samples(db)
    after = await sl.get_sample(db, row["id"])
    assert after["status"] == "archived"
    assert after["owner_approved"] == before["owner_approved"]


# ═══ delete → seed → remains deleted (tombstone) ═══════════════════════════

@pytest.mark.asyncio
async def test_delete_factory_keeps_tombstone_and_seed_never_restores(db):
    row = await _seeded_factory_row(db)
    ok, reason = await sl.delete_sample(db, row["id"])
    assert ok is True, reason
    # исчезла из основных выдач…
    assert await sl.get_sample(db, row["id"]) is None or \
        (await sl.get_sample(db, row["id"]))["tombstone"] is True
    listed = await sl.list_samples(db, chat_id=None)
    assert all(r["id"] != row["id"] for r in listed)
    # …но состояние не молча: tombstone-группа честна
    tomb = await sl.list_tombstoned(db, chat_id=None)
    assert [r["id"] for r in tomb] == [row["id"]]
    assert tomb[0]["seed_key"] == row["seed_key"]
    # повторный сид НЕ пересоздаёт/не воскресает строку
    again = await sl.seed_starter_samples(db)
    assert again["seeded"] == 0
    await sl.seed_starter_samples(db, force=True)
    assert [r["id"] for r in await sl.list_tombstoned(db, chat_id=None)] == \
        [row["id"]]
    assert all(r["id"] != row["id"] for r in
               await sl.list_samples(db, chat_id=None))


@pytest.mark.asyncio
async def test_delete_owner_row_is_hard_delete(db):
    view, _ = await sl.create_sample(db, fields={
        "input_text": "мой вход", "reply_text": "мой ответ",
        "category": "general"}, actor="owner")
    ok, _ = await sl.delete_sample(db, view["id"])
    assert ok is True
    assert await sl.get_sample(db, view["id"]) is None
    assert await sl.list_tombstoned(db, chat_id=None) == []


# ═══ explicit restore → restored (только подтверждение) ════════════════════

@pytest.mark.asyncio
async def test_restore_requires_confirmation_and_restores_single(db):
    row = await _seeded_factory_row(db)
    await sl.update_sample(db, row["id"],
                           fields={"reply_text": "правка владельца"},
                           actor="owner")
    # без confirm — честный отказ, ничего не изменено
    denied, reason = await sl.restore_factory_sample(db, row["id"],
                                                     confirm=False)
    assert denied is None and reason == "needs_confirmation"
    current = await sl.get_sample(db, row["id"])
    assert current["reply_text"] == "правка владельца"
    # подтверждённый restore одного примера
    restored, reason = await sl.restore_factory_sample(db, row["id"],
                                                       confirm=True)
    assert restored is not None, reason
    assert restored["reply_text"] == row["reply_text"]
    assert restored["owner_modified"] is False
    assert restored["owner_approved"] is False      # заводское = черновик
    assert restored["revision"] == current["revision"] + 1
    # остальные карточки не тронуты (выборка стабильна)
    others = await sl.list_samples(db, chat_id=None, category="humor")
    assert any(o["id"] != row["id"] for o in others)


@pytest.mark.asyncio
async def test_restore_tombstoned_row(db):
    row = await _seeded_factory_row(db)
    await sl.delete_sample(db, row["id"])
    restored, reason = await sl.restore_factory_sample(db, row["id"],
                                                       confirm=True)
    assert restored is not None, reason
    assert restored["tombstone"] is False
    assert restored["reply_text"] == row["reply_text"]
    listed = await sl.list_samples(db, chat_id=None)
    assert any(r["id"] == row["id"] for r in listed)
    assert await sl.list_tombstoned(db, chat_id=None) == []


@pytest.mark.asyncio
async def test_restore_when_factory_set_absent_keeps_owner_data(db):
    row = await _seeded_factory_row(db)
    # заводской набор «исчез из кода» (seed_key не из текущих определений)
    await db.db.execute(
        "UPDATE humor_samples SET seed_key = 'removed-legacy-key' "
        "WHERE id = ?", (row["id"],))
    restored, reason = await sl.restore_factory_sample(db, row["id"],
                                                       confirm=True)
    assert restored is None and reason == "factory_seed_absent"
    current = await sl.get_sample(db, row["id"])
    assert current["input_text"] == row["input_text"]   # данные целы


# ═══ preview / массовое восстановление ═════════════════════════════════════

@pytest.mark.asyncio
async def test_restore_preview_lists_only_affected_and_all_needs_confirm(db):
    row = await _seeded_factory_row(db)
    other = (await sl.list_samples(db, chat_id=None, category="humor"))[1]
    await sl.update_sample(db, row["id"],
                           fields={"reply_text": "правка владельца"},
                           actor="owner")
    preview = await sl.restore_factory_preview(db, chat_id=None)
    assert preview["available"] is True
    ids = [i["id"] for i in preview["items"]]
    assert ids == [row["id"]]
    assert any(d["field"] == "reply_text" for d in preview["items"][0]["diffs"])
    # без подтверждения массовое восстановление — no-op
    denied = await sl.restore_factory_all(db, chat_id=None, confirm=False)
    assert denied["ok"] is False
    assert denied["reason"] == "needs_confirmation"
    assert (await sl.get_sample(db, row["id"]))["reply_text"] == \
        "правка владельца"
    result = await sl.restore_factory_all(db, chat_id=None, confirm=True)
    assert result["ok"] is True and result["restored"] == 1
    assert (await sl.get_sample(db, row["id"]))["owner_modified"] is False
    untouched = await sl.get_sample(db, other["id"])
    assert untouched["owner_modified"] is False   # чужие карточки не тронуты


# ═══ параллельная правка → revision_conflict без потери ════════════════════

@pytest.mark.asyncio
async def test_parallel_edit_gets_revision_conflict_no_data_loss(db):
    row = await _seeded_factory_row(db)
    first, _ = await sl.update_sample(
        db, row["id"], fields={"reply_text": "правка A"},
        actor="owner", expected_revision=row["revision"])
    assert first is not None
    stale, reason = await sl.update_sample(
        db, row["id"], fields={"reply_text": "правка B (устаревшая)"},
        actor="owner", expected_revision=row["revision"])
    assert stale is None and reason == "revision_conflict"
    after = await sl.get_sample(db, row["id"])
    assert after["reply_text"] == "правка A"      # данные не потеряны


# ═══ реальные места вызова сида — ровно один ручной эндпоинт ═══════════════

def test_seed_call_sites_are_fixed_and_explicit():
    # SU-PERSIST.TESTS: seed_starter_samples/seed_expression_samples
    # вызываются в прод-коде только из ручного админ-эндпоинта speech.py
    # (сам модуль — определения; tests/tools — прогоны и фикстуры).
    # Автосида на старте/деплое/миграциях/обработчиках нет.
    import os
    import re
    root = os.path.dirname(os.path.dirname(REPO_ROOT))
    prod_hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (
            ".venv", ".git", "node_modules", "__pycache__",
            "OPENCODE_WORKFLOW_SCRATCH", ".playwright-mcp", "plans",
            "tests", "tools")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if re.search(r"seed_(starter|expression)_samples\s*\(", text):
                rel = os.path.relpath(path, root).replace("\\", "/")
                prod_hits.append(rel)
    allowed = {
        "services/mca_sample_library.py",   # определения сидов
        "web/api/speech.py",                # единственный ручной эндпоинт
    }
    unexpected = [h for h in prod_hits if h not in allowed]
    assert not unexpected, (
        "новые места вызова сида вне ручного эндпоинта: %s" % unexpected)


@pytest.mark.asyncio
async def test_owner_modified_mark_ignores_approval_and_archive(db):
    # одобрение/архив — отдельные состояния; «Изменено владельцем» ставит
    # только содержательная правка.
    row = await _seeded_factory_row(db)
    await sl.set_approval(db, row["id"], approved=True, actor="owner")
    after_approve = await sl.get_sample(db, row["id"])
    assert after_approve["owner_modified"] is False
    assert after_approve["origin"] == "factory"
    await sl.archive_sample(db, row["id"], archived=True, actor="owner")
    after_archive = await sl.get_sample(db, row["id"])
    assert after_archive["owner_modified"] is False
    await sl.update_sample(db, row["id"],
                           fields={"reply_text": "правка контента"},
                           actor="owner")
    after_edit = await sl.get_sample(db, row["id"])
    assert after_edit["owner_modified"] is True
    assert after_edit["origin"] == "modified"
