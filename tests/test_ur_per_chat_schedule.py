"""UNIFIED-REPLY UR-C-SCHED / UR-28.4 — ручной /summary и следующий запуск.

Покрывает открытую строку карты UR-28.4:

  * ручной `/summary` (``generate_and_send(..., manual=True)``) получает
    время стадии из ЧАТОВОЙ зоны через ChatClock, а не из глобального
    env/legacy-пояса и не из UTC контейнера;
  * read-only payload ``GET /api/config/time`` (``_build_time_state``)
    отдаёт следующий плановый запуск саммари в ЛОКАЛЬНОМ времени чата
    (``next_run_local`` + ``next_run_utc`` + ``timezone``), не создавая
    второй настройки пояса для саммари;
  * у блока ``summary_schedule`` ровно один пояс (эффективный чатовый) —
    нет дублированного tz-поля и нет нового ключа в каталоге.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-C-SCHED (UR-28.4)
"""
import datetime
import re
from types import SimpleNamespace

import pytest

from services import chat_clock as cc
import services.chat_params as chat_params

#: Read-only endpoint проверяется через общий TMA-клиент UR-F (та же
#: тестовая инфраструктура, без нового сервера/заглушек API).
from tests.test_ur_ui_effective_config import _hdr, client  # noqa: F401

pytestmark = [pytest.mark.system2]

#: Групповой чат (положительные id — ЛС, периодических сводок там нет).
CHAT = -1001234567890

#: 12:00 UTC = 15:00 Europe/Moscow (UTC+3, без DST).
SUMMER = datetime.datetime(2026, 7, 15, 12, 0,
                           tzinfo=datetime.timezone.utc)


class FakeCache:
    """chat_params-кэш с per-chat overrides (root-лейаут, как в проде)."""

    def __init__(self, roots_by_chat):
        self._roots = dict(roots_by_chat or {})
        self.updated_at = "2026-11-25T10:00:00Z"
        self._items = {int(cid): (0.0, root, self.updated_at)
                       for cid, root in self._roots.items()}

    async def get_chat_params(self, chat_id):
        return self._roots.get(int(chat_id), {})

    async def get_chat_params_full(self, chat_id):
        root = self._roots.get(int(chat_id), {})
        return root, self.updated_at


_MISSING = object()


@pytest.fixture()
def frozen_settings():
    from config.settings import settings

    patched: list[tuple[str, object]] = []

    def _patch(name: str, value: object) -> None:
        patched.append((name, getattr(settings, name, _MISSING)))
        object.__setattr__(settings, name, value)

    yield _patch
    for name, orig in reversed(patched):
        if orig is _MISSING:
            continue
        object.__setattr__(settings, name, orig)


_ROOTS_BY_CHAT: dict[int, dict] = {}


def _set_chat_override(chat_id, overrides: dict):
    _ROOTS_BY_CHAT[int(chat_id)] = {"overrides": dict(overrides)}
    chat_params._chat_params_cache = FakeCache(_ROOTS_BY_CHAT)


@pytest.fixture()
def tz_env(monkeypatch, frozen_settings):
    """Изолированные слои пояса: пустой канон/legacy по умолчанию."""
    import services.hot_config as hot_config

    controlled: dict[str, str] = {}
    original_get = hot_config.get

    def _fake_get(key, default=None):
        if key in controlled:
            return controlled[key]
        return original_get(key, default)

    monkeypatch.setattr(hot_config, "get", _fake_get)
    monkeypatch.delenv("GOODMORNING_TZ", raising=False)
    chat_params._chat_params_cache = None
    _ROOTS_BY_CHAT.clear()

    def _set_global(key: str, value: str) -> None:
        controlled[key] = value

    def _set_factory(value: str) -> None:
        frozen_settings("SUMMARY_TIMEZONE", value)

    holder = SimpleNamespace(set_global=_set_global, set_factory=_set_factory,
                             setenv=monkeypatch.setenv,
                             delenv=monkeypatch.delenv)
    yield holder
    chat_params._chat_params_cache = None
    _ROOTS_BY_CHAT.clear()


# ── UR-28.4(a): ручной /summary использует чатовую зону ─────────────────────


@pytest.mark.asyncio
async def test_manual_summary_prompt_uses_chat_zone_not_global(tz_env):
    """manual=True идёт тем же швом генератора: answer-блок с зоной ЧАТА.

    Дискриминирующий контраст: чат — Asia/Almaty (+05:00), глобальный
    legacy-пояс — Europe/Berlin (+02:00 летом), заводской — UTC. Если бы
    ручной путь брал env/глобальную зону (или UTC контейнера), в payload
    оказался бы Berlin/UTC, а не Almaty.
    """
    from unittest.mock import AsyncMock

    from tests.test_summary_generator import FakeLLM, FakeMemory, _make_generator

    class RecordingLLM(FakeLLM):
        """Пишет ВСЕ вызовы: у пайплайна есть финальные/служебные стадии."""

        def __init__(self, text="саммари"):
            super().__init__(text=text)
            self.calls = []

        async def generate(self, messages, **kwargs):
            self.calls.append(messages)
            return await super().generate(messages, **kwargs)

    tz_env.set_global("limits.summary_timezone", "Europe/Berlin")
    tz_env.set_factory("UTC")
    _set_chat_override(CHAT, {"limits.chat_timezone": "Asia/Almaty"})
    # Без явного per-chat canonical чат наследовал бы глобальный legacy-пояс.
    assert (await cc.resolve_chat_timezone(CHAT))[0] == "Asia/Almaty"

    memory = FakeMemory(rows=[{
        "id": 1, "user_id": 10, "timestamp": 1_700_000_000,
        "author_name": "вася", "text": "сообщение для ручного саммари",
        "reply_to_id": None, "media_type": "text"}])
    llm = RecordingLLM(text="саммари")
    generator = _make_generator(memory, llm, AsyncMock())

    await generator.generate_and_send(CHAT, manual=True)

    assert llm.calls, "ручной /summary обязан дойти до LLM-вызова"
    clock_calls = [
        call for call in llm.calls
        if any("<Chat_Time_Context" in str(m.get("content", ""))
               for m in call)
    ]
    assert clock_calls, "ни один вызов не получил блок времени чата"
    joined = "\n".join(str(m.get("content", ""))
                       for call in clock_calls for m in call)
    assert joined.count("<Chat_Time_Context") >= 1
    assert 'phase="answer"' in joined
    # Чатовая зона, а не глобальная/env/UTC.
    assert "Asia/Almaty" in joined
    assert "+05:00" in joined
    assert "Europe/Berlin" not in joined
    assert "UTC+05:00" in joined


# ── UR-28.4(b): следующий запуск — в локальном времени чата ──────────────────


async def _time_state(now_utc):
    from web.api import routes as routes_mod

    cache = SimpleNamespace(get=lambda key, default=None: None)
    state = await routes_mod._build_time_state(
        CHAT, cache, now_utc=now_utc)
    return state


@pytest.mark.asyncio
async def test_time_payload_summary_next_run_in_chat_local_time(tz_env):
    """GET /api/config/time: next_run_local — в поясе ЧАТА, не UTC.

    При 12:00 UTC в Europe/Moscow (15:00) ближайший слот 18:00 локального
    времени = 15:00 UTC. Ошибка «показать UTC» дала бы 18:00 UTC и была бы
    поймана; второй пояс для саммари тоже не нужен.
    """
    _set_chat_override(CHAT, {"limits.chat_timezone": "Europe/Moscow"})

    state = await _time_state(SUMMER)
    schedule = state.get("summary_schedule")
    assert schedule is not None, "payload обязан нести summary_schedule"
    assert schedule["timezone"] == "Europe/Moscow"
    assert schedule["timezone"] == state["iana"]
    assert schedule["next_run_utc"] == "2026-07-15T15:00:00+00:00"
    assert schedule["next_run_local"] == "15.07.2026 18:00"
    assert schedule["slots"] == ["00:00", "06:00", "12:00", "18:00"]
    # Явно не создаёт второй пояс: единственное tz-поле — эффективный чатовый.
    assert set(schedule) == {
        "available", "timezone", "timezone_source", "slots",
        "next_run_utc", "next_run_local", "enabled", "enabled_source",
    }
    assert "summary_timezone" not in schedule
    assert schedule["timezone_source"] == "chat"


@pytest.mark.asyncio
async def test_time_payload_global_scope_has_no_fake_chat_schedule(tz_env):
    """Глобальный скоуп не выдумывает «следующий запуск» без чата."""
    from web.api import routes as routes_mod

    cache = SimpleNamespace(get=lambda key, default=None: None)
    state = await routes_mod._build_time_state(
        None, cache, now_utc=SUMMER)
    assert state.get("summary_schedule") is None


def test_get_config_time_endpoint_carries_summary_schedule(client):
    """Реальный read-only endpoint отдаёт блок, а не только внутренний билдер."""
    resp = client.get("/api/config/time?chat_id=-1001234567890",
                      headers=_hdr())
    assert resp.status_code == 200, resp.text
    state = resp.json()
    schedule = state.get("summary_schedule")
    assert schedule is not None
    assert schedule["available"] is True
    assert schedule["timezone"] == state["iana"]
    assert schedule["slots"] == ["00:00", "06:00", "12:00", "18:00"]
    assert re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$",
                    schedule["next_run_local"] or "")
    assert schedule["next_run_utc"] and schedule["next_run_utc"].endswith(
        "+00:00")


def test_no_second_summary_timezone_setting():
    """UR-28.4: для расписания саммари нет отдельного ключа пояса.

    ``limits.summary_timezone`` — существующий legacy-слой канонической
    цепочки ChatClock (UR-24.3), а не настройка расписания саммари; нового
    ключа/переменной для «пояса саммари» не появляется.
    """
    from services import param_catalog

    keys = {spec.pg_key for spec in param_catalog.REGISTRY.values()
            if spec.pg_key}
    summary_tz_keys = {k for k in keys
                       if "summary" in k.lower() and "timezone" in k.lower()}
    assert summary_tz_keys == {"limits.summary_timezone"}

    from services import chat_clock

    assert chat_clock.CANON_TZ_KEY == "limits.chat_timezone"
    assert chat_clock.LEGACY_SUMMARY_TZ_KEY == "limits.summary_timezone"
