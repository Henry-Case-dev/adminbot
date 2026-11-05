"""PVR-REV-01 — 409 на ПУТИ ПРОМПТА не записывает ничего.

Контракт ``plans/features/prompt-versioning-ux/arch/versioning-ux-contract.md``
§3.2 п.7 и §3.3: у профиля чата один optimistic-токен
(``chat_profiles.updated_at``). Два сохранения промпта, стартовавшие с ОДНИМ
токеном, не могут оба стать действующими: второе получает HTTP 409
``conflict`` с актуальным токеном, а значение промпта, журнал ревизий и
события активации остаются ровно от первой правки. «Мягкое» прохождение
второй записи (silent overwrite) — регрессия, которую тест обязан ловить.

Тест УМЕЕТ ПАДАТЬ: если CAS-гвард ``chat_params`` перестанет отсекать вторую
запись (значение изменится, появится ревизия/событие), проверки ниже краснеют.

Стенд — существующий: ``tests.test_meme_pipeline_api._build`` + журнал
``MemoryPromptJournal`` через точку инъекции ``routes._prompt_journal``.
Отличие ровно одно: PG-двойник профиля честно проверяет
``UPDATE ... WHERE updated_at = $3`` (как ``tests/test_chat_params.py`` и
``test_asap8_v63_b10r09_settings_409_race``); общий двойник токен не сверяет,
поэтому 409 на нём невоспроизводим.

TEST-LIFECYCLE: CONTRACT owner=PVR-REV-01
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import tests.test_meme_pipeline_api as meme_api
from services import prompt_release_policy as prp
from services.prompt_release_policy import MemoryPromptJournal
from tests.test_meme_pipeline_api import (
    JOKE_KEY,
    _ProfileConn,
    _build,
)
from tests.test_prompt_versioning_enforcement import (
    JOKE_BLOCK,
    _Env,
    _post_meme,
)
from web.api import routes as routes_mod


class _CasProfileConn(_ProfileConn):
    """PG-двойник профиля чата с ЧЕСТНЫМ optimistic-гвардом ``updated_at``.

    ``UPDATE ... AND updated_at = $3`` при несовпадении токена возвращает
    ``None`` (0 строк) — ровно как PostgreSQL; ``SELECT`` отдаёт актуальный
    токен. Токен сдвигается после каждой успешной записи.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self._seq = 0
        self.updated_at = "2026-11-04T00:00:00+00:00"

    def _next_ts(self) -> str:
        self._seq += 1
        return "2026-11-04T00:00:%02d+00:00" % self._seq

    @staticmethod
    def _row(chat_id, updated_at, params) -> dict:
        return {"chat_id": chat_id, "updated_at": updated_at,
                "chat_params": json.dumps(params), "gates_opt_in": False}

    async def fetchrow(self, sql, *args):
        low = str(sql).lower().lstrip()
        if "chat_profiles" not in low:
            return await super().fetchrow(sql, *args)
        if low.startswith("update chat_profiles") and "chat_params" in low:
            self.queries.append((sql, tuple(args)))
            if "updated_at = $3" in low:
                expected = (args[2].isoformat()
                            if hasattr(args[2], "isoformat") else str(args[2]))
                if expected != self.updated_at:
                    return None            # optimistic-конфликт: 0 строк
            self.params = json.loads(args[1])
            self.writes.append(dict(self.params.get("overrides") or {}))
            self.updated_at = self._next_ts()
            return self._row(args[0], self.updated_at, self.params)
        if low.startswith("select chat_id"):
            self.queries.append((sql, tuple(args)))
            return self._row(args[0], self.updated_at, self.params)
        return await super().fetchrow(sql, *args)


@pytest.fixture
def cas_env(monkeypatch):
    """Стенд ``env`` с честным CAS-двойником профиля (та же инъекция)."""
    monkeypatch.setattr(meme_api, "_ProfileConn", _CasProfileConn)
    conn, cache, app = _build(monkeypatch)
    journal = MemoryPromptJournal()
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: journal)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: journal)
    from services import lore_runtime
    from services import meme_initiative as meme
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
    monkeypatch.setattr(meme, "open_ledger", lambda db: None)

    async def _no_model_capability():
        return None

    monkeypatch.setattr(meme, "model_prompt_chars", _no_model_capability)
    with TestClient(app) as tc:
        yield _Env(tc, conn, cache, journal)


def test_prompt_cas_conflict_writes_nothing(cas_env):
    """Второе сохранение с тем же ``updated_at`` → 409 и НОЛЬ записей.

    Проверяется наблюдаемое: значение промпта в профиле, число ревизий и
    события активации после отказа — такие же, как до него; текст отказавшей
    правки не появляется в журнале. Затем повтор с актуальным токеном из
    ответа 409 проходит — отказ честный, а не «залипший».
    """
    env = cas_env
    first = "Первый текст прикола — он и должен остаться."
    second = "Второй текст: он НЕ должен сохраниться (конфликт токена)."
    stale_token = env.conn.updated_at          # токен, который «видит» UI

    resp = _post_meme(env, prompt_joke=first, updated_at=stale_token)
    assert resp.status_code == 200, resp.text
    stored_after_first = env.stored(JOKE_KEY)
    revisions_before = dict(env.journal.revisions)
    events_before = list(env.journal.activations)
    token_after_first = env.conn.updated_at
    assert stored_after_first == first
    assert len(revisions_before) == 1 and len(events_before) == 1
    assert token_after_first != stale_token

    # Второй писатель стартовал с ТЕМ ЖЕ токеном → его правка отклоняется.
    conflict = _post_meme(env, prompt_joke=second, updated_at=stale_token)
    assert conflict.status_code == 409, conflict.text
    detail = conflict.json()["detail"]
    assert detail["code"] == "conflict"
    assert detail["current_updated_at"] == token_after_first, (
        "409 обязан нести актуальный токен для повторной попытки")
    assert detail["applied"] == []

    # Ничего не записано: значение, ревизии и события — от первой правки.
    assert env.stored(JOKE_KEY) == first, "409 изменил значение промпта"
    assert dict(env.journal.revisions) == revisions_before, (
        "409 добавил ревизию: %s" % sorted(
            set(env.journal.revisions) - set(revisions_before)))
    assert env.journal.activations == events_before, "409 добавил событие"
    assert all(row.body != second
               for row in env.journal.revisions.values()), (
        "отклонённый текст попал в журнал ревизий")
    chat_revs = env.revisions(JOKE_BLOCK)
    chat_events = env.events(JOKE_BLOCK)
    assert len(chat_revs) == 1 and chat_revs[0].body == first
    assert [(e.kind, e.outcome) for e in chat_events] == [
        ("manual_edit", "applied")]

    # Повтор с актуальным токеном из ответа — проходит (409 не «залип»).
    retry = _post_meme(env, prompt_joke=second,
                       updated_at=detail["current_updated_at"])
    assert retry.status_code == 200, retry.text
    assert env.stored(JOKE_KEY) == second
    assert len(env.revisions(JOKE_BLOCK)) == 2
    assert [e.revision_id for e in env.events(JOKE_BLOCK)][-1] == \
        env.revisions(JOKE_BLOCK)[-1].revision_id
