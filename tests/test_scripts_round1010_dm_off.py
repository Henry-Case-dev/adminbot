"""Раунд 10.10 (п.4, ADR-1010-1) — тесты
scripts/disable_dm_heavy_modules.py.

Проверки: чистый патч-планировщик (идемпотентность), dry-run без записи,
apply пишет merged overrides/gates + снапшот, повторный прогон = 0
изменений, `--chat-id` фильтрует, abort без записи при сбое снапшота,
`--restore` возвращает overrides/gates.
"""
import json

import pytest

from scripts import disable_dm_heavy_modules as dm


def _row(chat_id, overrides=None, gates=None, is_active=True):
    return {
        "chat_id": chat_id,
        "chat_params": {"v": 1, "overrides": overrides or {},
                        "gates": gates or {}},
        "gates_opt_in": False,
    }


def test_build_dm_patch_only_non_false():
    """True/отсутствие → патч false; уже false → no-op."""
    patch_o, patch_g = dm.build_dm_patch(
        {"memory.dream_enabled": True, "flags.summary_enabled": False},
        {"dream": True})
    # уже false → НЕ патчим (идемпотентность); отсутствующие → патчим.
    assert patch_o == {
        "memory.dream_enabled": False,
        "memory.nostalgia_enabled": False,
        "flags.chat_running_summary_enabled": False,
    }
    assert patch_g == {"dream": False, "nostalgia": False}
    # всё уже false → пустые патчи (идемпотентность).
    full_o = {k: False for k in dm._DM_DISABLED_OVERRIDES}
    full_g = {k: False for k in dm._DM_DISABLED_GATES}
    assert dm.build_dm_patch(full_o, full_g) == ({}, {})


def test_collect_plan_and_chat_id_filter():
    rows = [_row(1, {"memory.dream_enabled": True}, {"dream": True}),
            _row(2)]
    plan = dm.collect_plan(rows)
    assert [e["chat_id"] for e in plan] == [1, 2]
    only = dm.collect_plan(rows, chat_ids=[2])
    assert [e["chat_id"] for e in only] == [2]
    # уже выключенный чат (все false) — no-op.
    closed = _row(3, {k: False for k in dm._DM_DISABLED_OVERRIDES},
                  {k: False for k in dm._DM_DISABLED_GATES})
    assert dm.collect_plan([closed]) == []


def _patch_run(monkeypatch, rows, calls):
    async def fake_fetch(pg):
        return rows

    async def fake_set(chat_id, patch, **kwargs):
        calls.append((chat_id, patch))
        # эмулируем запись merged-словарей в стор.
        for row in rows:
            if row["chat_id"] == chat_id:
                row["chat_params"] = {"v": 1,
                                      "overrides": patch["overrides"],
                                      "gates": patch["gates"]}
        return patch

    monkeypatch.setattr(dm, "fetch_dm_profiles", fake_fetch)
    monkeypatch.setattr(
        "services.chat_params.set_chat_params", fake_set)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(monkeypatch, capsys, tmp_path):
    rows = [_row(1, {"memory.dream_enabled": True}, {"dream": True})]
    calls = []
    _patch_run(monkeypatch, rows, calls)
    rc = await dm.run(["--snapshot-out", str(tmp_path / "s.json")],
                      pg=object())
    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "планируется 1 изменений" in out
    assert not (tmp_path / "s.json").exists()


@pytest.mark.asyncio
async def test_apply_writes_and_snapshot(monkeypatch, tmp_path):
    rows = [_row(1, {"memory.dream_enabled": True}, {"dream": True})]
    calls = []
    _patch_run(monkeypatch, rows, calls)
    snap = tmp_path / "snap.json"
    rc = await dm.run(["--apply", "--snapshot-out", str(snap)], pg=object())
    assert rc == 0
    assert len(calls) == 1
    chat_id, patch = calls[0]
    assert chat_id == 1
    # merged: старый True перекрыт false, остальные DM-ключи добавлены.
    assert patch["overrides"]["memory.dream_enabled"] is False
    assert patch["gates"]["dream"] is False
    assert patch["gates"]["nostalgia"] is False
    # snapshot — ДО записи, overrides/gates/meta (без секретов).
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["chats"][0]["chat_id"] == 1
    assert data["chats"][0]["overrides"]["memory.dream_enabled"] is True
    assert data["chats"][0]["gates"]["dream"] is True
    assert data["chats"][0]["meta"] == {}
    assert "keys" not in data["chats"][0]


@pytest.mark.asyncio
async def test_apply_snapshot_preserves_meta(monkeypatch, tmp_path):
    """Scanner: снапшот хранит прежний meta (чтобы --restore не терял note)."""
    rows = [_row(1, {"memory.dream_enabled": True}, {"dream": True})]
    rows[0]["chat_params"]["meta"] = {"updated_by": 42, "note": "old note"}
    calls = []
    _patch_run(monkeypatch, rows, calls)
    snap = tmp_path / "snap.json"
    await dm.run(["--apply", "--snapshot-out", str(snap)], pg=object())
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["chats"][0]["meta"] == {"updated_by": 42, "note": "old note"}


@pytest.mark.asyncio
async def test_apply_idempotent_rerun_zero(monkeypatch, capsys, tmp_path):
    rows = [_row(1, {"memory.dream_enabled": True}, {"dream": True})]
    calls = []
    _patch_run(monkeypatch, rows, calls)
    await dm.run(["--apply", "--snapshot-out", str(tmp_path / "s.json")],
                 pg=object())
    assert len(calls) == 1
    # повторный (dry-run) — 0 изменений (патч пуст).
    calls.clear()
    rc = await dm.run([], pg=object())
    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "планируется 0 изменений" in out


@pytest.mark.asyncio
async def test_apply_aborts_when_snapshot_fails(monkeypatch, tmp_path):
    rows = [_row(1, {"memory.dream_enabled": True}, {"dream": True})]
    calls = []
    _patch_run(monkeypatch, rows, calls)

    def boom(path, plan):
        raise OSError("disk full")

    monkeypatch.setattr(dm, "write_snapshot", boom)
    rc = await dm.run(["--apply", "--snapshot-out", str(tmp_path / "s.json")],
                      pg=object())
    assert rc == 1
    assert calls == []      # записи не было


@pytest.mark.asyncio
async def test_restore_from_snapshot(monkeypatch, tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "version": 1,
        "chats": [{"chat_id": 5,
                   "overrides": {"memory.dream_enabled": True},
                   "gates": {"dream": True}}],
    }), encoding="utf-8")
    calls = []
    _patch_run(monkeypatch, [], calls)
    rc = await dm.run(["--restore", str(snap)], pg=object())
    assert rc == 0
    assert calls[0][0] == 5
    assert calls[0][1]["overrides"]["memory.dream_enabled"] is True
    assert calls[0][1]["gates"]["dream"] is True


@pytest.mark.asyncio
async def test_restore_returns_meta_faithfully(monkeypatch, tmp_path):
    """Scanner: restore возвращает meta из снапшота (прежний note)."""
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "version": 1,
        "chats": [{"chat_id": 5, "overrides": {}, "gates": {},
                   "meta": {"updated_by": 42, "note": "old note"}}],
    }), encoding="utf-8")
    calls = []
    _patch_run(monkeypatch, [], calls)
    rc = await dm.run(["--restore", str(snap)], pg=object())
    assert rc == 0
    patch = calls[0][1]
    assert patch["meta"] == {"updated_by": 42, "note": "old note"}
    assert set(patch) == {"overrides", "gates", "meta"}


@pytest.mark.asyncio
async def test_restore_legacy_snapshot_without_meta_not_wiped(
        monkeypatch, tmp_path):
    """Legacy-снапшот (нет ключа meta) → namespace meta не трогаем вовсе."""
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "version": 1,
        "chats": [{"chat_id": 5, "overrides": {}, "gates": {}}],
    }), encoding="utf-8")
    calls = []
    _patch_run(monkeypatch, [], calls)
    await dm.run(["--restore", str(snap)], pg=object())
    patch = calls[0][1]
    assert "meta" not in patch, "legacy restore не должен трогать meta"
    assert set(patch) == {"overrides", "gates"}


@pytest.mark.asyncio
async def test_dry_run_scope_respects_chat_id(monkeypatch, capsys, tmp_path):
    """Scanner: dry-run-отчёт считает noop/total по выбранному --chat-id."""
    rows = [
        _row(1, {"memory.dream_enabled": True}, {"dream": True}),
        _row(2, {k: False for k in dm._DM_DISABLED_OVERRIDES},
              {k: False for k in dm._DM_DISABLED_GATES}),
        _row(3, {"memory.dream_enabled": True}, {"dream": True}),
    ]
    calls = []
    _patch_run(monkeypatch, rows, calls)
    rc = await dm.run(["--chat-id", "2"], pg=object())
    assert rc == 0
    out = capsys.readouterr().out
    assert "планируется 0 изменений из 1 ЛС" in out


@pytest.mark.asyncio
async def test_apply_report_scope_respects_chat_id(monkeypatch, capsys,
                                                   tmp_path):
    """Scanner: apply-отчёт (noop/total) — по выбранному scope --chat-id."""
    rows = [
        _row(1, {"memory.dream_enabled": True}, {"dream": True}),
        _row(2, {k: False for k in dm._DM_DISABLED_OVERRIDES},
              {k: False for k in dm._DM_DISABLED_GATES}),
    ]
    calls = []
    _patch_run(monkeypatch, rows, calls)
    rc = await dm.run(["--apply", "--chat-id", "2",
                       "--snapshot-out", str(tmp_path / "s.json")],
                      pg=object())
    assert rc == 0
    out = capsys.readouterr().out
    assert "changed=0 noop=1 total=1" in out


@pytest.mark.asyncio
async def test_restore_partial_failure_nonzero_exit(monkeypatch, capsys,
                                                    tmp_path):
    """LOW-RESTORE: частичный сбой restore → exit 1 + restored=<n>/<total>
    + errors=<k>; успешные чаты всё равно восстановлены."""
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "version": 1,
        "chats": [
            {"chat_id": 5, "overrides": {"memory.dream_enabled": True},
             "gates": {"dream": True}},
            {"chat_id": 6, "overrides": {}, "gates": {}},
        ],
    }), encoding="utf-8")
    calls = []

    async def fake_fetch(pg):
        return []

    async def fake_set(chat_id, patch, **kwargs):
        if chat_id == 6:
            raise RuntimeError("pg down")
        calls.append((chat_id, patch))
        return patch

    monkeypatch.setattr(dm, "fetch_dm_profiles", fake_fetch)
    monkeypatch.setattr("services.chat_params.set_chat_params", fake_set)
    rc = await dm.run(["--restore", str(snap)], pg=object())
    assert rc == 1, "LOW-RESTORE: частичный сбой restore → exit 1"
    out = capsys.readouterr().out
    assert "restored=1/2" in out, "LOW-RESTORE: отчёт restored=<n>/<total>"
    assert "errors=1" in out, "LOW-RESTORE: отчёт errors=<k>"
    assert [c[0] for c in calls] == [5], "успешный чат восстановлен"


@pytest.mark.asyncio
async def test_restore_all_success_exit_zero(monkeypatch, capsys, tmp_path):
    """LOW-RESTORE: полный успех → restored=<total>/<total>, exit 0."""
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "version": 1,
        "chats": [{"chat_id": 5, "overrides": {}, "gates": {}}],
    }), encoding="utf-8")
    calls = []
    _patch_run(monkeypatch, [], calls)
    rc = await dm.run(["--restore", str(snap)], pg=object())
    assert rc == 0
    out = capsys.readouterr().out
    assert "restored=1/1" in out
    assert "errors=0" in out


@pytest.mark.asyncio
async def test_apply_partial_failure_nonzero_exit(monkeypatch, capsys,
                                                  tmp_path):
    """LOW-3: частичный сбой → ненулевой код возврата + errors=<k>."""
    rows = [_row(1, {"memory.dream_enabled": True}, {"dream": True}),
            _row(2, {"memory.dream_enabled": True}, {"dream": True})]
    calls = []

    async def fake_fetch(pg):
        return rows

    async def fake_set(chat_id, patch, **kwargs):
        if chat_id == 2:
            raise RuntimeError("pg down")
        calls.append((chat_id, patch))
        return patch

    monkeypatch.setattr(dm, "fetch_dm_profiles", fake_fetch)
    monkeypatch.setattr("services.chat_params.set_chat_params", fake_set)
    rc = await dm.run(["--apply", "--snapshot-out", str(tmp_path / "s.json")],
                      pg=object())
    assert rc == 1, "LOW-3: частичный сбой → exit 1"
    out = capsys.readouterr().out
    assert "errors=1" in out, "LOW-3: отчёт печатает errors=<k>"
    assert [c[0] for c in calls] == [1], "LOW-3: успешный чат записан"
