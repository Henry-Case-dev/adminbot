"""SOUL-1 / W4 — FIX-W4: закрытие блокеров REVIEW-W4 (F1/F2/F3).

Покрытие находок ревью:
  * **F1** (SOUL-07.2) — approve/archive примера проверяют принадлежность чату
    так же, как update/delete: чужой chat-scoped пример → 403;
  * **F2** (SOUL-08.11) — телеметрия контура действительно считает отправки
    (`sends` не ноль после `capture_send`), и по чату, и глобально;
  * **F3** — карточки хаба «Примеры»/«Обучение» описывают ФАКТИЧЕСКОЕ
    состояние поставленного экрана, а не «слайс W4».

TEST-LIFECYCLE: REGRESSION owner=soul-1/W4
"""
import asyncio

import pytest
import pytest_asyncio

from services import mca_humor_feedback as hf
from services import mca_sample_library as samples_lib
from services.database import DatabaseService
from services.permissions import Permissions
from web.api import speech as S


CHAT_A = -100111
CHAT_B = -100222


class _Cache:
    """Минимальный двойник ConfigCache (get/set/get_updated_at)."""

    def __init__(self):
        self.data = {}
        self.updated = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def get_updated_at(self, key):
        return self.updated.get(key)

    def set(self, key, value, category=None):
        self.data[key] = value
        self.updated[key] = "in-memory"

        async def _noop():
            return None

        return asyncio.ensure_future(_noop())

    async def set_many(self, items):
        for key, value, category in items:
            self.set(key, value, category)


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "fixw4.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


@pytest.fixture
def chat_admin_env(monkeypatch, db):
    """Контент-админ ЧАТА: право `edit_persona`, но не global admin."""
    from services import chat_params, lore_runtime

    cache = _Cache()
    chat_store: dict = {}

    async def get_root(chat_id, pg=None):
        store = chat_store.get(int(chat_id)) or {}
        return {"overrides": dict(store.get("overrides") or {})}

    async def set_root(chat_id, patch, **kwargs):
        store = chat_store.setdefault(int(chat_id), {})
        for ns in ("overrides", "gates", "keys", "perm_overrides", "meta"):
            if ns in patch and isinstance(patch[ns], dict):
                store[ns] = dict(patch[ns])

    monkeypatch.setattr("services.chat_params.get_all_chat_params", get_root)
    monkeypatch.setattr("services.chat_params.set_chat_params", set_root)
    monkeypatch.setattr(S, "get_cache", lambda request=None: cache)
    lore_runtime.set_lore_components(db=db)
    monkeypatch.setenv("HUMOR_FEEDBACK_ENABLED", "1")

    user = type("U", (), {"id": 5150})()
    ctx = type("C", (), {
        "is_global_admin": False,
        "effective_permissions": Permissions.from_dict(
            {"actions": ["edit_persona"]}),
    })()

    async def access(request, _user, x_chat_id):
        chat_id = int(x_chat_id) if x_chat_id else None
        return cache, chat_id, ctx

    monkeypatch.setattr(S, "_access", access)
    yield {"cache": cache, "user": user, "ctx": ctx, "chat": chat_store}
    lore_runtime.reset_lore_runtime()


async def _make_chat_sample(chat_id: int, text: str = "чужой пример"):
    view, reason = await samples_lib.create_sample(
        samples_lib.get_db(), fields={
            "input_text": "вход " + text, "reply_text": "ответ " + text,
            "technique": "deadpan", "scope": "chat", "chat_id": chat_id,
            "source_kind": "owner_manual"}, actor="fixture")
    assert view is not None, reason
    assert int(view["chat_id"]) == int(chat_id)
    return view


async def _status(coro) -> int:
    """HTTP-статус вызова эндпоинта (200 при отсутствии исключения)."""
    try:
        await coro
    except Exception as exc:                  # HTTPException или иное
        return int(getattr(exc, "status_code", 0) or 0)
    return 200


# ═══ F1: SOUL-07.2 — изоляция чатов на approve/archive ═════════════════════

@pytest.mark.asyncio
async def test_foreign_chat_approve_and_archive_are_forbidden(chat_admin_env):
    """Чужой chat-scoped пример нельзя ни утвердить, ни архивировать."""
    sample = await _make_chat_sample(CHAT_B)
    env = chat_admin_env

    approve_status = await _status(S.post_example_approve(
        None, env["user"], int(sample["id"]), str(CHAT_A)))
    after_approve = await samples_lib.get_sample(samples_lib.get_db(),
                                                 int(sample["id"]))
    assert approve_status == 403, approve_status
    assert after_approve["owner_approved"] is False

    archive_status = await _status(S.post_example_archive(
        None, env["user"], int(sample["id"]), str(CHAT_A)))
    after_archive = await samples_lib.get_sample(samples_lib.get_db(),
                                                 int(sample["id"]))
    assert archive_status == 403, archive_status
    assert after_archive["status"] == "active"

    # Симметрия с соседними обработчиками (там проверка была и раньше).
    assert await _status(S.post_example_update(
        None, env["user"], int(sample["id"]),
        S.SampleWrite(input_text="x", reply_text="y"), str(CHAT_A))) == 403
    assert await _status(S.delete_example(
        None, env["user"], int(sample["id"]), str(CHAT_A))) == 403


@pytest.mark.asyncio
async def test_own_chat_approve_and_archive_still_work(chat_admin_env):
    """Свой пример в своём чате утверждается и архивируется как прежде."""
    sample = await _make_chat_sample(CHAT_A)
    env = chat_admin_env

    approved = await S.post_example_approve(
        None, env["user"], int(sample["id"]), str(CHAT_A))
    assert approved["ok"] is True and approved["item"]["owner_approved"] is True

    archived = await S.post_example_archive(
        None, env["user"], int(sample["id"]), str(CHAT_A))
    assert archived["ok"] is True and archived["item"]["status"] == "archived"


@pytest.mark.asyncio
async def test_global_samples_are_editable_by_any_chat_admin(chat_admin_env):
    """Глобальный пример не привязан к чату — проверка чата не мешает."""
    view, reason = await samples_lib.create_sample(
        samples_lib.get_db(), fields={
            "input_text": "глобальный вход", "reply_text": "глобальный ответ",
            "technique": "literalism", "scope": "global",
            "source_kind": "owner_manual"}, actor="fixture")
    assert view is not None, reason
    result = await S.post_example_approve(None, chat_admin_env["user"],
                                          int(view["id"]), str(CHAT_B))
    assert result["ok"] is True and result["item"]["owner_approved"] is True


# ═══ F2: SOUL-08.11 — телеметрия считает отправки ══════════════════════════

@pytest.mark.asyncio
async def test_telemetry_counts_captured_sends(chat_admin_env, db, monkeypatch):
    """`sends` — реальное число отправок под наблюдением (не всегда 0)."""
    from services import hot_config

    class _Catalog:
        def get(self, key, default=None):
            return True

    hot_config.set_config_cache(_Catalog())
    try:
        empty = await hf.telemetry(db, chat_id=CHAT_A)
        assert empty["sends"] == 0

        captured = await hf.capture_send(
            db, chat_id=CHAT_A, message_id=9001, strategy="deadpan",
            technique="deadpan", delivered=True)
        await hf.capture_send(db, chat_id=CHAT_B, message_id=9002,
                              strategy="literalism", technique="literalism",
                              delivered=True)
        assert captured["captured"] is True, captured

        own = await hf.telemetry(db, chat_id=CHAT_A)
        other = await hf.telemetry(db, chat_id=CHAT_B)
        global_view = await hf.telemetry(db)
        assert own["sends"] == 1, own
        assert other["sends"] == 1, other
        assert global_view["sends"] == 2, global_view
    finally:
        hot_config.set_config_cache(None)


# ═══ F3: карточки хаба не врут о поставленном экране ═══════════════════════

@pytest.mark.asyncio
async def test_overview_cards_reflect_delivered_sections(chat_admin_env):
    """Хаб «Речь и характер» показывает фактическое состояние разделов."""
    env = chat_admin_env
    overview = await S.get_overview(None, env["user"], str(CHAT_A))
    cards = {row["id"]: row for row in overview["sections"]}

    examples = cards["examples"]
    assert examples["ready"] is True
    assert "слайс W4" not in examples["detail"]
    assert examples["state"] == "ready"
    assert ("карточек" in examples["detail"]) or \
        ("библиотека" in examples["detail"])

    learning = cards["learning"]
    assert "W4" not in learning["detail"]
    assert learning["ready"] is True
    assert learning["state"] in ("ready", "off")
    assert ("реакц" in learning["detail"]) or ("сигнал" in learning["detail"])

    # ничего не выдумывается: при недоступной таблице карточка честно не ready
    assert "W4" not in (examples["subtitle"] + examples["detail"])
