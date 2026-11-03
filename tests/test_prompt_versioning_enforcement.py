"""EPIC-PROMPT-VERSIONING-UX-01 — принудительный аудит единого слоя записи.

Контракт: ``plans/features/prompt-versioning-ux/arch/versioning-ux-contract.md``
§5 (три слоя) и §3 (единая атомарная запись). Тест обязан УМЕТЬ ПАДАТЬ:

  * слой 1 — реестр ↔ доступность в UI: каждый PG-блок реестра либо в каталоге
    конфигурации, либо в явно объявленном маленьком множестве спец-карточек;
    блок ``ui='code_only'`` в каталоге истории — read-only с причиной;
  * слой 2 — поведенческая матрица по КАЖДОЙ точке записи (§3.4): ревизия с
    ожидаемым origin/scope/chat, событие активации, значение в хранилище,
    повтор тех же байтов → ``skipped_same`` без дубля ревизии, недоступный
    журнал → HTTP 503 и значение НЕ изменилось;
  * слой 3 — рантайм-страж: ``PromptJournalBypass`` на записи текста промпта
    без журнального токена (две мутации: спец-эндпоинт мемов и
    ``POST /api/config`` через ``cache.set_many``).

TEST-LIFECYCLE: CONTRACT owner=EPIC-PROMPT-VERSIONING-UX-01
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from services import chat_params
from services import param_catalog as pc
from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services.config_cache import ConfigCache
from services.prompt_release_policy import MemoryPromptJournal
from tests.test_meme_pipeline_api import (
    CHAT_A,
    ENDPOINT,
    IMAGE_KEY,
    JOKE_KEY,
    _ProfileConn,
    _build,
    _headers,
)
from tests.test_webapp_api import ADMIN_ID, _FakePg, _hdr
from web.api import routes as routes_mod
from web.app import create_app

JOKE_BLOCK = "initiative.meme.joke"
IMAGE_BLOCK = "initiative.meme.image"

#: Маленькое явное множество «спец-карточек»: ключи реестра, которые не
#: обязаны появляться в общем каталоге «Промпты» (у них своя карточка), но
#: каждый покрыт поведенческим тестом слоя 2.
SPECIALIZED_CARDS = frozenset({
    "prompts.meme_joke",
    "prompts.meme_image",
})

#: PG-блоки, чья точка редактирования — НЕ общий каталог «Промптов». Каждая
#: запись названа с причиной; новый PG-блок без поверхности редактирования
#: обязан провалить тест ниже, а не «потеряться» в молчаливом списке.
NON_CATALOG_SURFACES: dict[str, str] = {
    # документ из двух блоков-полей: экран «Характер» (/speech/core)
    "character.core": "speech/core",
    # управляемые сообщения пользователю (не промпты): правятся как текст
    # возможностей; в истории версий доступны read-only
    **{f"content.image_failure.{code}": "managed_message" for code in (
        "delivery_failed", "disabled", "freq_limited", "not_configured",
        "quota_exhausted", "temporarily_unavailable", "unknown", "unsupported")},
    "content.image_request_clarify": "managed_message",
}

#: ui-маркеры, при которых блок обязан быть виден в общей карточке промптов.
_CATALOG_UI = "catalog"


# ═══════════════════════════════════════════════════════════════════════════
# Слой 1 — реестр ↔ UI-доступность
# ═══════════════════════════════════════════════════════════════════════════

def _editable_keys() -> set[str]:
    return {b.pg_key for b in pr.all_blocks() if b.pg_key
            and b.ui != "code_only"}


def test_every_editable_block_is_reachable_in_ui():
    """Каждый PG-блок имеет названную поверхность редактирования (§5.1).

    Три допустимых поверхности: каталог «Промпты», спец-карточка модуля или
    явно названный экран/тип из :data:`NON_CATALOG_SURFACES` с причиной.
    Блок, для которого нет ни одной, — провал теста (архитектурная
    регрессия, а не «мелочь»).
    """
    uncovered = sorted(
        key for key in _editable_keys()
        if pc.get_by_pg_key(key) is None
        and key not in SPECIALIZED_CARDS
        and key not in NON_CATALOG_SURFACES)
    assert uncovered == [], (
        "PG-блоки реестра без поверхности редактирования: %s" % uncovered)


def test_non_catalog_inventory_has_no_stale_entries():
    """Названные исключения не «залипают»: исчезнувший ключ — тоже регрессия."""
    stale = sorted(key for key in NON_CATALOG_SURFACES
                   if pr.by_pg_key(key) is None
                   or pc.get_by_pg_key(key) is not None)
    assert stale == [], "устаревшие записи NON_CATALOG_SURFACES: %s" % stale
    for key, surface in sorted(NON_CATALOG_SURFACES.items()):
        assert surface, key


def test_catalog_ui_blocks_are_declared_in_param_catalog():
    """``ui='catalog'`` — блок обязан быть настоящим ключом каталога."""
    missing = sorted(b.pg_key for b in pr.all_blocks()
                     if b.pg_key and b.ui == _CATALOG_UI
                     and pc.get_by_pg_key(b.pg_key) is None)
    assert missing == [], "ui=catalog без ключа в каталоге: %s" % missing


def test_specialized_cards_are_real_registry_blocks():
    """Множество спец-карточек не «разрешает» несуществующие ключи."""
    for key in sorted(SPECIALIZED_CARDS):
        spec = pr.by_pg_key(key)
        assert spec is not None, key
        assert spec.pg_key == key
        assert spec.ui != "code_only", key


def test_code_only_blocks_are_read_only_in_history():
    """``ui='code_only'`` — блок в истории есть, активации нет (§5.1)."""
    editable = _editable_keys()
    code_only = [b for b in pr.all_blocks() if not b.pg_key]
    assert code_only, "нет code-only блоков — проверять нечего"
    for spec in code_only[:12]:
        assert not spec.pg_key
        assert spec.pg_key not in editable
        view = asyncio.run(prp.list_versions(spec.block_id,
                                             store=MemoryPromptJournal(),
                                             actor="owner"))
        # read-only: значение не переключается, история остаётся доступной
        result = asyncio.run(prp.write_prompt_values(
            [prp.PromptWriteItem(block_id=spec.block_id, text="x")],
            store=MemoryPromptJournal(), actor="owner"))
        assert result["applied"] == [] and result["skipped_same"] == []
        assert result["rejected"] == [
            {"key": spec.block_id, "reason": "block_not_pg_managed"}]
        assert view["known"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Стенд HTTP-слоя: профиль чата + тестовый журнал через _prompt_journal
# ═══════════════════════════════════════════════════════════════════════════

class _Env:
    def __init__(self, client, conn, cache, journal):
        self.client = client
        self.conn = conn
        self.cache = cache
        self.journal = journal

    # — чтение фактического значения из «PG» (не из журнала) —
    def stored(self, key: str) -> object:
        return (self.conn.params.get("overrides") or {}).get(key)

    def global_value(self, key: str) -> object:
        return self.cache.get(key, None)

    def revisions(self, block_id: str, scope: str = "chat"):
        return [row for row in self.journal.revisions.values()
                if row.block_id == block_id and row.scope == scope]

    def events(self, block_id: str, scope: str = "chat"):
        return [row for row in self.journal.activations
                if row.block_id == block_id and row.scope == scope]


@pytest.fixture
def env(monkeypatch):
    """Приложение с РЕАЛЬНЫМ chat_params поверх PG-двойника и журналом."""
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


def _post_meme(env: _Env, **payload):
    return env.client.post(ENDPOINT, json=payload, headers=_headers())


def _assert_revision(table, block_id, *, scope, chat_id, origin, body):
    rows = [row for row in table.revisions.values()
            if row.block_id == block_id and row.scope == scope
            and row.chat_id == chat_id and row.origin == origin
            and row.body == body]
    assert len(rows) == 1, (
        "нет ровно одной ревизии %s/%s/%s/%s" % (block_id, scope, chat_id,
                                                 origin))


# ═══════════════════════════════════════════════════════════════════════════
# Слой 2 — поведенческая матрица по точкам записи §3.4
# ═══════════════════════════════════════════════════════════════════════════

def test_meme_settings_write_revision_event_and_value(env):
    """Спец-эндпоинт мемов: ревизия + событие + значение в хранилище."""
    text = "Придумай прикол про кота из этой выжимки."
    resp = _post_meme(env, prompt_joke=text)
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert env.stored(JOKE_KEY) == text
    _assert_revision(env.journal, JOKE_BLOCK, scope="chat", chat_id=CHAT_A,
                     origin="manual", body=text)
    events = env.events(JOKE_BLOCK)
    assert [(e.kind, e.outcome) for e in events] == [("manual_edit", "applied")]
    assert events[0].actor == str(ADMIN_ID)
    assert events[0].revision_id == payload["prompt_snapshots"][0][
        "revision_id"]
    assert [row["key"] for row in payload["prompt_snapshots"]] == [JOKE_KEY]

    # История чата показывает новую ревизию активной (тот же журнал).
    listed = asyncio.run(prp.list_versions(
        JOKE_BLOCK, scope="chat", chat_id=CHAT_A,
        store=env.journal, actor="owner"))
    ids = {row["revision_id"] for row in listed["revisions"]}
    assert payload["prompt_snapshots"][0]["revision_id"] in ids
    assert listed["active"]["revision_id"] == payload["prompt_snapshots"][0][
        "revision_id"]


def test_meme_settings_same_bytes_make_no_duplicate_revision(env):
    """Повтор тех же байтов → skipped_same, число ревизий не растёт."""
    text = "Прикол без изменений."
    assert _post_meme(env, prompt_joke=text).status_code == 200
    before = set(env.journal.revisions)

    resp = _post_meme(env, prompt_joke=text)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["skipped_same"] == [JOKE_KEY]
    assert set(env.journal.revisions) == before, "текстовая ревизия дублирована"
    assert env.events(JOKE_BLOCK)[-1].outcome == "skipped_same"
    assert env.stored(JOKE_KEY) == text


def test_meme_settings_journal_unavailable_is_503_without_write(env,
                                                               monkeypatch):
    """Журнал недоступен → 503 и значение в хранилище НЕ изменилось."""
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: None)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: None)
    resp = _post_meme(env, prompt_joke="Этот текст не должен сохраниться.")
    assert resp.status_code == 503, resp.text
    assert env.stored(JOKE_KEY) is None
    assert env.journal.revisions == {}


def test_meme_settings_empty_prompt_removes_override_with_snapshot(env):
    """Пустая строка = снять override, но текста история не теряет (§3.6)."""
    text = "Чатовый прикол перед снятием."
    assert _post_meme(env, prompt_joke=text).status_code == 200
    resp = _post_meme(env, prompt_joke="")
    assert resp.status_code == 200, resp.text
    assert env.stored(JOKE_KEY) is None
    events = env.events(JOKE_BLOCK)
    assert (events[-1].kind, events[-1].outcome) == (
        "chat_inherit_reset", "recorded")
    assert events[-1].revision_id in env.journal.revisions
    assert env.journal.revisions[events[-1].revision_id].body == text


def test_config_global_write_goes_through_journal(env):
    """``POST /api/config`` (global): ревизия global + событие + значение."""
    text = "Глобальный текст из общего редактора."
    resp = env.client.post("/api/config",
                           json={"items": [{"key": JOKE_KEY, "value": text}]},
                           headers=_hdr())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == [JOKE_KEY]
    assert [row["key"] for row in body["prompt_snapshots"]] == [JOKE_KEY]
    _assert_revision(env.journal, JOKE_BLOCK, scope="global", chat_id=None,
                     origin="manual", body=text)
    events = env.events(JOKE_BLOCK, scope="global")
    assert [(e.kind, e.outcome) for e in events] == [("manual_edit", "applied")]
    assert env.global_value(JOKE_KEY) == text

    # Повтор тех же байтов — событие без дубля ревизии.
    before = set(env.journal.revisions)
    again = env.client.post("/api/config",
                            json={"items": [{"key": JOKE_KEY, "value": text}]},
                            headers=_hdr())
    assert again.status_code == 200, again.text
    assert again.json()["skipped_same"] == [JOKE_KEY]
    assert set(env.journal.revisions) == before


def test_config_global_journal_unavailable_is_503_without_write(env,
                                                                monkeypatch):
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: None)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: None)
    resp = env.client.post(
        "/api/config",
        json={"items": [{"key": JOKE_KEY, "value": "Не должно сохраниться."}]},
        headers=_hdr())
    assert resp.status_code == 503, resp.text
    assert env.global_value(JOKE_KEY) is None
    assert env.journal.revisions == {}


def test_config_chat_write_goes_through_journal(env):
    """``POST /api/config`` (chat) — тот же единый слой, scope=chat."""
    text = "Чатовый текст из общего редактора."
    resp = env.client.post(
        "/api/config",
        json={"items": [{"key": JOKE_KEY, "value": text}]},
        headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == [JOKE_KEY]
    assert env.stored(JOKE_KEY) == text
    _assert_revision(env.journal, JOKE_BLOCK, scope="chat", chat_id=CHAT_A,
                     origin="manual", body=text)
    assert [row["key"] for row in body["prompt_snapshots"]] == [JOKE_KEY]


def test_delete_config_chat_prompt_key_snapshots_text(env):
    """``DELETE /api/config/chat/{key}`` промпта — снимок + событие снятия."""
    text = "Удаляемый чатовый текст."
    assert _post_meme(env, prompt_joke=text).status_code == 200
    resp = env.client.delete(f"/api/config/chat/{JOKE_KEY}",
                             headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 200, resp.text
    assert env.stored(JOKE_KEY) is None
    events = env.events(JOKE_BLOCK)
    assert (events[-1].kind, events[-1].outcome) == (
        "chat_inherit_reset", "recorded")
    assert env.journal.revisions[events[-1].revision_id].body == text


def test_speech_block_write_and_reset_go_through_journal(env):
    """Speech-блок: запись и ``reset?mode=chat`` — журнальные операции."""
    block_id = "direct.base.l2_writer"
    key = pr.block(block_id).pg_key
    text = pr.factory_text(block_id) + "\n\nПравка владельца из речи."
    resp = env.client.post(f"/api/speech/block/{block_id}",
                           json={"text": text, "scope": "chat"},
                           headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert resp.status_code == 200, resp.text
    assert env.stored(key) == text
    _assert_revision(env.journal, block_id, scope="chat", chat_id=CHAT_A,
                     origin="manual", body=text)

    reset = env.client.post(f"/api/speech/block/{block_id}/reset",
                            json={"mode": "chat", "apply": True},
                            headers={**_hdr(), "X-Chat-Id": str(CHAT_A)})
    assert reset.status_code == 200, reset.text
    assert env.stored(key) is None
    events = env.events(block_id)
    assert (events[-1].kind, events[-1].outcome) == (
        "chat_inherit_reset", "recorded")
    assert env.journal.revisions[events[-1].revision_id].body == text


def test_factory_reset_goes_through_journal(env):
    """``apply_factory_reset`` (mode=factory) — журнальная запись значения."""
    block_id = "direct.base.l2_writer"
    key = pr.block(block_id).pg_key
    custom = pr.factory_text(block_id) + "\n\nРучная правка перед сбросом."
    assert env.client.post(f"/api/speech/block/{block_id}",
                           json={"text": custom, "scope": "global"},
                           headers=_hdr()).status_code == 200

    resp = env.client.post(f"/api/speech/block/{block_id}/reset",
                           json={"mode": "factory", "apply": True,
                                 "reason": "owner test"},
                           headers=_hdr())
    assert resp.status_code == 200, resp.text
    factory_text = pr.factory_text(block_id)
    assert env.global_value(key) == factory_text
    _assert_revision(env.journal, block_id, scope="global", chat_id=None,
                     origin="manual", body=factory_text)
    assert env.events(block_id, scope="global")[-1].kind == "manual_rollback"


def test_restore_backup_refuses_without_journal(monkeypatch):
    """Аварийное восстановление без журнала — отказ, значения не пишутся."""
    class _Cache:
        def __init__(self):
            self.values = {"prompts.direct_chat_verbalizer_system_prompt":
                           "текущее"}
            self.pg_available = True

        def get(self, key, default=None):
            return self.values.get(key, default)

        async def set(self, key, value, category):
            self.values[key] = value

    monkeypatch.setattr(prp, "default_journal", lambda cache: None)
    cache = _Cache()
    backup = {"keys": {"prompts.direct_chat_verbalizer_system_prompt": {
        "text": "восстановленное", "category": "prompts"}}}
    with pytest.raises(prp.JournalUnavailable):
        asyncio.run(pf.restore_backup(backup, apply=True, cache=cache))
    # Значение промпта не изменилось (bounded-книга истории — не значение).
    assert cache.values["prompts.direct_chat_verbalizer_system_prompt"] == \
        "текущее"


# ═══════════════════════════════════════════════════════════════════════════
# Слой 3 — рантайм-страж обхода + две мутации, доказывающие, что он падает
# ═══════════════════════════════════════════════════════════════════════════

def test_guard_blocks_direct_cache_write_of_prompt_text():
    """``cache.set_many`` текста промпта без журнального токена — исключение."""
    conn = _ProfileConn(role_rows=[], admin_rows=[])
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    asyncio.run(cache.reload())
    with pytest.raises(prp.PromptJournalBypass):
        asyncio.run(cache.set_many([(JOKE_KEY, "обход журнала", "prompts")]))
    assert cache.get(JOKE_KEY) is None
    with pytest.raises(prp.PromptJournalBypass):
        asyncio.run(cache.set(JOKE_KEY, "обход журнала", "prompts"))
    assert cache.get(JOKE_KEY) is None
    # Непромптный ключ и слот выбора стиля пишутся как раньше.
    asyncio.run(cache.set("limits.search_max_symbols", 100, "limits"))
    asyncio.run(cache.set("prompts.summary_cover_style_id", "s1", "prompts"))


def test_guard_allows_write_inside_journal_scope():
    """Тот же ключ внутри журнального токена пишется (страж не вакуумный)."""
    conn = _ProfileConn(role_rows=[], admin_rows=[])
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    asyncio.run(cache.reload())
    with prp.journal_write_scope([prp.JournalWriteGrant(JOKE_BLOCK, "global",
                                                       None)]):
        asyncio.run(cache.set(JOKE_KEY, "запись через журнал", "prompts"))
    assert cache.get(JOKE_KEY) == "запись через журнал"


def test_guard_blocks_direct_chat_params_write_of_prompt_text():
    """``chat_params.set_chat_params`` без ``conn`` и токена — исключение."""
    conn = _ProfileConn(role_rows=[], admin_rows=[])
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    with pytest.raises(prp.PromptJournalBypass):
        asyncio.run(chat_params.set_chat_params(
            CHAT_A, {"overrides": {JOKE_KEY: "обход журнала"}}, pg=cache.pg))
    assert (conn.params.get("overrides") or {}).get(JOKE_KEY) is None
    # Непромптные настройки чата пишутся прежним путём.
    asyncio.run(chat_params.set_chat_params(
        CHAT_A, {"overrides": {"limits.search_max_symbols": 10}},
        pg=cache.pg))
    assert conn.params["overrides"]["limits.search_max_symbols"] == 10


def test_guard_catches_bypass_mutation_meme_handler(env, monkeypatch):
    """МУТАЦИЯ 1: спец-эндпоинт мемов пишет прямо в ``set_chat_params``.

    Ровно прежнее поведение (``routes.py:4245``): значение уходит в
    ``chat_params`` без журнальной транзакции. Ожидание: ``PromptJournalBypass``
    в момент записи, значение в PG не изменилось, ревизий не появилось.
    """
    sentinel = "мутация: обход журнала мемов"

    async def _bypassing_write(cache, items, **kwargs):
        key = pr.block(items[0].block_id).pg_key
        await chat_params.set_chat_params(
            int(kwargs["chat_id"]), {"overrides": {key: items[0].text}},
            pg=cache.pg)

    monkeypatch.setattr(routes_mod, "_write_prompt_items", _bypassing_write)
    with pytest.raises(prp.PromptJournalBypass):
        _post_meme(env, prompt_joke=sentinel)
    assert env.stored(JOKE_KEY) is None, "обход записал значение в PG"
    assert env.journal.revisions == {}, "обход не должен давать ревизий"

    # Та же мутация напрямую через точку записи профиля.
    with pytest.raises(prp.PromptJournalBypass):
        asyncio.run(chat_params.set_chat_params(
            CHAT_A, {"overrides": {JOKE_KEY: sentinel}}, pg=env.cache.pg))
    assert env.stored(JOKE_KEY) is None
    assert env.journal.revisions == {}


def test_guard_catches_bypass_mutation_config_global(env, monkeypatch):
    """МУТАЦИЯ 2: ``POST /api/config`` (global) пишет через ``cache.set``.

    Прежнее поведение: значение в ``bot_settings``, журнал — отдельным
    best-effort вызовом после. Ожидание: ``PromptJournalBypass``, значение не
    записано, ревизий нет.
    """
    sentinel = "мутация: обход журнала глобального каталога"

    async def _bypassing_write(cache, items, **kwargs):
        for item in items:
            spec = pr.block(item.block_id)
            await cache.set_many([(spec.pg_key, item.text, "prompts")])

    monkeypatch.setattr(routes_mod, "_write_prompt_items", _bypassing_write)
    with pytest.raises(prp.PromptJournalBypass):
        env.client.post("/api/config",
                        json={"items": [{"key": JOKE_KEY, "value": sentinel}]},
                        headers=_hdr())
    assert env.global_value(JOKE_KEY) is None, "обход записал значение"
    assert env.journal.revisions == {}

    # Прямая запись мимо токена — тоже отказ.
    with pytest.raises(prp.PromptJournalBypass):
        asyncio.run(env.cache.set_many([(JOKE_KEY, sentinel, "prompts")]))
    assert env.global_value(JOKE_KEY) is None


def test_guard_allows_unchanged_document_metadata_write():
    """Правка только ``detail_level``/``enabled`` Core не требует журнала."""
    conn = _ProfileConn(role_rows=[], admin_rows=[])
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    asyncio.run(cache.reload())
    doc = {"full_text": "полный текст", "compact_text": "короткий",
           "detail_level": "full", "revision": 1}
    with prp.journal_write_scope([
            prp.JournalWriteGrant("core.personality", "global", None),
            prp.JournalWriteGrant("core.personality.compact", "global", None)]):
        asyncio.run(cache.set(pr.CORE_DOC_KEY, doc, "content"))
    updated = dict(doc, detail_level="compact", revision=2)
    asyncio.run(cache.set(pr.CORE_DOC_KEY, updated, "content"))   # без токена
    assert cache.get(pr.CORE_DOC_KEY)["detail_level"] == "compact"
    for field_name in ("full_text", "compact_text"):
        with pytest.raises(prp.PromptJournalBypass):
            asyncio.run(cache.set(pr.CORE_DOC_KEY,
                                  dict(updated, **{field_name: "чужой текст"}),
                                  "content"))


# ═══════════════════════════════════════════════════════════════════════════
# §3.2/§3.3: значение, CAS и честный отказ при сбое журнала
# ═══════════════════════════════════════════════════════════════════════════

def test_failed_revision_insert_leaves_value_untouched(env, monkeypatch):
    """Сбой вставки ревизии: значение в PG не изменилось, ответ 503."""
    orig = MemoryPromptJournal.insert_revision

    async def _boom(self, row, created_at=None):
        if row.block_id == JOKE_BLOCK:
            raise prp.PromptJournalError("injected failure: insert_revision")
        return await orig(self, row, created_at=created_at)

    monkeypatch.setattr(MemoryPromptJournal, "insert_revision", _boom)
    resp = _post_meme(env, prompt_joke="Сбой посреди транзакции.")
    assert resp.status_code == 503, resp.text
    assert env.stored(JOKE_KEY) is None


def test_chat_cas_token_reaches_set_chat_params(env, monkeypatch):
    """CAS-токен ``updated_at`` уходит в тот же ``set_chat_params`` (§3.2 п.7).

    ``ChatParamsConflict``→409 остаётся семантикой ``set_chat_params`` и здесь
    не переизобретается: проверяется, что запись промпта идёт ИМ через
    журнальный слой, с токеном клиента и ``meta.updated_by``.
    """
    captured: dict = {}
    orig = chat_params.set_chat_params

    async def _spy(chat_id, patch, **kwargs):
        captured["chat_id"] = chat_id
        captured["patch"] = patch
        captured.update(kwargs)
        return await orig(chat_id, patch, **kwargs)

    monkeypatch.setattr(chat_params, "set_chat_params", _spy)
    resp = env.client.post(
        ENDPOINT,
        json={"prompt_joke": "Текст с оптимистичным токеном.",
              "updated_at": "2026-11-03T00:00:00+00:00"},
        headers=_headers())
    assert resp.status_code == 200, resp.text
    assert captured["chat_id"] == CHAT_A
    assert captured["expected_updated_at"] == "2026-11-03T00:00:00+00:00"
    assert (captured["patch"]["overrides"] or {}).get(JOKE_KEY) == \
        "Текст с оптимистичным токеном."
    assert (captured["patch"]["meta"] or {}).get("updated_by") == ADMIN_ID
    assert env.stored(JOKE_KEY) == "Текст с оптимистичным токеном."


def test_pg_store_writes_chat_state_on_journal_connection(monkeypatch):
    """PG-стор пишет профиль на КОННЕКТЕ транзакции (одна транзакция §3.2)."""
    from services.prompt_release_policy import PgPromptJournal

    sentinel_conn = object()
    captured: dict = {}

    async def _spy(chat_id, patch, **kwargs):
        captured["chat_id"] = chat_id
        captured["conn"] = kwargs.get("conn")
        captured["expected_updated_at"] = kwargs.get("expected_updated_at")
        return chat_params.ChatParamsResult({"overrides": {}}, updated_at="t")

    monkeypatch.setattr(chat_params, "set_chat_params", _spy)
    store = PgPromptJournal(pool=None)
    store._tx_conn = sentinel_conn
    asyncio.run(store.write_chat_state(
        777, {"prompts.meme_joke": "x"}, {"updated_by": 5},
        expected_updated_at="2026-11-03T00:00:00+00:00", changed_by=5))
    assert captured["conn"] is sentinel_conn
    assert captured["expected_updated_at"] == "2026-11-03T00:00:00+00:00"
    assert captured["chat_id"] == 777
    # Вне транзакции журнала запись профиля невозможна (нет «своего» пути).
    store._tx_conn = None
    with pytest.raises(prp.PromptJournalError):
        asyncio.run(store.write_chat_state(777, {}, {}))


def test_activation_of_foreign_chat_revision_is_refused(env):
    """Активация чужой чатовой ревизии — отказ, активный указатель цел."""
    from services.prompt_release_policy import ActivationRow, RevisionRow

    foreign = RevisionRow(
        revision_id="rev:foreign", block_id=JOKE_BLOCK, scope="chat",
        origin="manual", content_sha12="foreign00000", body="ЧУЖОЙ ЧАТ",
        pg_key=JOKE_KEY, chat_id=-100999, reason="owner_edit")
    env.journal.revisions[foreign.revision_id] = foreign
    env.journal.activations.append(ActivationRow(
        block_id=JOKE_BLOCK, scope="chat", chat_id=-100999,
        revision_id="rev:foreign", kind="manual_edit", outcome="applied"))
    before = list(env.journal.activations)

    result = asyncio.run(prp.activate_revision(
        JOKE_BLOCK, "rev:foreign", scope="chat", chat_id=CHAT_A,
        actor="owner", store=env.journal))
    assert result["applied"] is False
    assert result["reason"] == "revision_foreign_scope"
    assert env.journal.activations == before
    assert env.stored(JOKE_KEY) is None


def test_body_sha_of_meme_prompts_matches_package_baseline():
    """Байты мемных промптов не изменились этим пакетом (§0.1 ТЗ).

    Эталон снят ДО правок:
    ``plans/features/prompt-versioning-ux/evidence/pvr-s1/prompt-bytes-baseline.json``.
    """
    import hashlib

    expected = {
        "initiative.meme.joke":
            "2f30ca1f9a6b6e0fb93ffaaf4946b49e300e0846a80afdc255a6086375452d58",
        "initiative.meme.image":
            "f81fe7e4b5052635297b4270a7d15fecab0adea8ad6fa27e96e957fdb086276c",
    }
    for block_id, sha in sorted(expected.items()):
        body = pr.factory_text(block_id).encode("utf-8")
        assert hashlib.sha256(body).hexdigest() == sha, block_id
    # Тот же агрегат, что в артефакте-эталоне.
    aggregate = hashlib.sha256(json.dumps(
        {b: hashlib.sha256(pr.factory_text(b).encode()).hexdigest()
         for b in sorted(expected)}, sort_keys=True).encode()).hexdigest()
    assert aggregate == hashlib.sha256(json.dumps(
        {"initiative.meme.image": expected["initiative.meme.image"],
         "initiative.meme.joke": expected["initiative.meme.joke"]},
        sort_keys=True).encode()).hexdigest()
