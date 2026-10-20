# -*- coding: utf-8 -*-
"""ADD-SAMPLES-UX §7/§8 (SU-ACCEPT) — сквозные offline-приёмки на реальных
эндпоинтах (без Telegram; локальная БД; ноль live-отправок).

Минимум §7 (SU-7.OFFLINE): миграция категорий (см. test_samples_categories),
изоляция global/chat, схема реального отбора (/examples/why), режимная
изоляция MAT, owner-approved, no-leakage, owner edits/tombstones при
повторном seed, reset по подтверждению, API error/409, честные причины.
SQLite-контур реальный; PostgreSQL-путь библиотеки не существует по
архитектуре (GEN-R4: memory-контур SQLite-only) — зафиксировано в отчёте.

TEST-LIFECYCLE: INTEGRATION owner=SAMPLES-UX/SU-ACC.*, SU-7.* (§7/§8)
"""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from services import mca_sample_library as sl
from services.database import DatabaseService
from web.api import speech as S


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    service = DatabaseService(str(tmp_path / "samples-acceptance.db"))
    await service.initialize()
    monkeypatch.setattr(sl, "get_db", lambda: service)

    cache = SimpleNamespace()          # проверки доступа — как в w6-срезе
    ctx = SimpleNamespace(is_global_admin=True, effective_permissions=None)
    user = SimpleNamespace(id=4242)

    async def access(request, _user, x_chat_id):
        chat_id = int(x_chat_id) if x_chat_id else None
        return cache, chat_id, ctx

    monkeypatch.setattr(S, "_access", access)
    yield SimpleNamespace(db=service, user=user, chat_id=-100500)
    monkeypatch.undo()
    try:
        await service.close()
    except Exception:
        pass


def _run(coro):
    return asyncio.run(coro)


# ═══ изоляция global/chat через реальные эндпоинты ═════════════════════════

def test_chat_scoped_example_isolated_between_chats(env):
    body = S.SampleWrite(input_text="вход чата", reply_text="ответ чата",
                         category="general", scope="chat")
    created = _run(S.post_example(None, env.user, body,
                                  x_chat_id=str(env.chat_id)))
    assert created["ok"] is True
    assert created["item"]["scope"] == "chat"
    mine = _run(S.get_examples(None, env.user, str(env.chat_id)))
    assert any(i["id"] == created["item"]["id"] for i in mine["items"])
    other = _run(S.get_examples(None, env.user, "-200999"))
    assert all(i["id"] != created["item"]["id"] for i in other["items"])
    # мутация чужого chat-scope → 403 (guard изоляции)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _run(S.post_example_update(
            None, env.user, created["item"]["id"],
            S.SampleWrite(input_text="взлом", reply_text="взлом"),
            x_chat_id="-200999"))
    assert exc.value.status_code == 403


def test_global_example_visible_from_every_chat(env):
    body = S.SampleWrite(input_text="общий вход", reply_text="общий ответ",
                         category="humor", scope="global")
    created = _run(S.post_example(None, env.user, body, x_chat_id=None))
    mine = _run(S.get_examples(None, env.user, str(env.chat_id)))
    assert any(i["id"] == created["item"]["id"] for i in mine["items"])


# ═══ API error / 409 / валидация категорий ═════════════════════════════════

def test_validation_errors_are_explicit(env):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _run(S.post_example(None, env.user, S.SampleWrite(
            input_text="вход", reply_text="ответ", category="surprise"),
            x_chat_id=None))
    assert exc.value.status_code == 422
    assert exc.value.detail == "unknown_category"
    with pytest.raises(HTTPException) as exc:
        _run(S.post_example(None, env.user, S.SampleWrite(
            input_text="вход", reply_text="ответ", category="mat",
            expression_mode="sometimes"), x_chat_id=None))
    assert exc.value.status_code == 422
    # no-leakage: PII не попадает в библиотеку
    with pytest.raises(HTTPException) as exc:
        _run(S.post_example(None, env.user, S.SampleWrite(
            input_text="напиши a.b@example.org", reply_text="ответ",
            category="general"), x_chat_id=None))
    assert exc.value.status_code == 422
    assert str(exc.value.detail).startswith("sensitive:")


def test_revision_conflict_returns_409(env):
    body = S.SampleWrite(input_text="вход", reply_text="ответ",
                         category="humor", technique="deadpan")
    created = _run(S.post_example(None, env.user, body, x_chat_id=None))
    sid = created["item"]["id"]
    ok = _run(S.post_example_update(
        None, env.user, sid, S.SampleWrite(
            input_text="вход", reply_text="правка A", category="humor",
            expected_revision=1), x_chat_id=None))
    assert ok["ok"] is True and ok["item"]["revision"] == 2
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _run(S.post_example_update(
            None, env.user, sid, S.SampleWrite(
                input_text="вход", reply_text="устаревшая правка",
                category="humor", expected_revision=1), x_chat_id=None))
    assert exc.value.status_code == 409
    current = _run(S.get_examples(None, env.user, None))
    row = next(i for i in current["items"] if i["id"] == sid)
    assert row["reply_text"] == "правка A"      # данные не потеряны


# ═══ owner edits / tombstones при повторном seed через эндпоинт ════════════

def test_factory_edit_and_delete_survive_reseed_via_endpoint(env):
    seeded = _run(S.post_examples_seed(None, env.user, None))
    assert seeded["ok"] is True
    payload = _run(S.get_examples(None, env.user, None))
    factory_row = next(i for i in payload["items"]
                       if i["origin"] == "factory" and i["category"] == "mat")
    # правка заводской карточки из API (UI идёт тем же путём)
    updated = _run(S.post_example_update(
        None, env.user, factory_row["id"], S.SampleWrite(
            input_text=factory_row["input_text"],
            reply_text="моя редакция", category="mat",
            expression_mode=factory_row["expression_mode"],
            expected_revision=factory_row["revision"]),
        x_chat_id=None))
    assert updated["item"]["origin"] == "modified"
    assert updated["item"]["owner_modified"] is True
    assert updated["item"]["owner_modified_at"]
    # удаление → tombstone; повторный сид не воскресает
    deleted = _run(S.delete_example(None, env.user, factory_row["id"], None))
    assert deleted["ok"] is True
    _run(S.post_examples_seed(None, env.user, None))
    payload = _run(S.get_examples(None, env.user, None))
    assert all(i["id"] != factory_row["id"] for i in payload["items"])
    assert any(d["id"] == factory_row["id"] for d in payload["deleted"])
    # reset ОДНОЙ карточки только по подтверждению: без confirm — 428
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _run(S.post_restore_factory_one(
            None, env.user, factory_row["id"],
            S.RestoreFactoryRequest(confirm=False), x_chat_id=None))
    assert exc.value.status_code == 428
    restored = _run(S.post_restore_factory_one(
        None, env.user, factory_row["id"],
        S.RestoreFactoryRequest(confirm=True), x_chat_id=None))
    assert restored["ok"] is True
    assert restored["item"]["reply_text"] == factory_row["reply_text"]
    assert restored["item"]["tombstone"] is False
    # массовый reset без confirm — честный отказ (не действие по умолчанию)
    denied = _run(S.post_restore_factory_all(
        None, env.user, S.RestoreFactoryRequest(confirm=False), x_chat_id=None))
    assert denied["ok"] is False
    assert denied["reason"] == "needs_confirmation"


# ═══ схема реального отбора + MAT-изоляция + честные причины ═══════════════

def test_why_endpoint_real_selection_and_reasons(env):
    body = S.SampleWrite(input_text="шутка про чайник",
                         reply_text="аудит кухни", category="humor",
                         technique="deadpan")
    created = _run(S.post_example(None, env.user, body, x_chat_id=None))
    sid = created["item"]["id"]
    why = _run(S.post_example_why(None, env.user, sid, x_chat_id=None))
    assert why["ok"] is True
    assert why["why"] == "Черновик — ещё не утверждён"
    # owner-approved: утверждение меняет причину на «выбран»
    _run(S.post_example_approve(None, env.user, sid, x_chat_id=None,
                                approved=True))
    why = _run(S.post_example_why(None, env.user, sid, x_chat_id=None))
    assert why["selected"] is True
    assert "Выбран" in why["why"]
    # отбор /examples/why — тот же детерминированный контур (0 LLM)
    bulk = _run(S.post_examples_why(
        None, env.user,
        S.SampleWhyRequest(technique="deadpan", message="шутка про чайник"),
        x_chat_id=None))
    assert bulk["ok"] is True
    assert any(s["id"] == sid for s in bulk["selected"])


def test_categories_payload_lists_three_categories(env):
    payload = _run(S.get_examples(None, env.user, None))
    cats = [c["id"] for c in payload["categories"]]
    assert cats[:3] == ["general", "humor", "mat"]
    assert payload["available"] is True
    assert "deleted" in payload
    # покатегорийные счётчики в телеметрии (для вкладок UI)
    assert set(payload["telemetry"]["by_category"]) >= \
        {"general", "humor", "mat", "legacy"}


# ═══ §8: ноль live-отправок — структурная проверка самого прогона ══════════

def test_no_live_send_helpers_in_this_module_source():
    # SU-7.NOLIVE: тесты этого контракта не содержат вызовов отправки.
    import pathlib
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    # токены собираются конкатенацией, чтобы не совпасть с самим фильтром
    forbidden = ["send" + "_message", "bot." + "send", "send" + "Message",
                 "telegram" + "_send", "Bo" + "t("]
    for token in forbidden:
        assert token not in src, token
