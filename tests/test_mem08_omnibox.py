"""EPIC-MEMORY-COGNITIVE-02 / MEM-08-S3 — единое поле поиска (omnibox UI).

Контракт: `plans/features/memory-cognitive-02/contracts.md` §4.9/§4.10, §5.2,
§10 (Visual Preservation Map), MEM-08.14/08.23/08.25 и артефакт S1
`search-read-model.md` §1/§3.

Проверяется:

* гейт `MCA_MEMORY_SEARCH_ENABLED` зарегистрирован в СУЩЕСТВУЮЩЕМ реестре
  (`mca_gates.MEMORY_GATES`) и каталоге (`flags.memory_search_enabled`),
  заводской дефолт — ON (правило проекта), env-аварийный OFF важнее каталога,
  chat-override важнее global, `chat_id=None` chat-слой не читает;
* payload карты отдаёт аддитивное поле `search` ТОЛЬКО при включённом гейте;
  OFF — байт-в-байт паритет S2 (никакого «выключено, но поле есть»);
* ручка `/api/memory/search` при OFF отвечает честным disabled (409, до
  любого поиска), а не пустой выдачей;
* пользовательские состояния `no_matches` / `no_rights` / `error` /
  `cursor_stale` РАЗЛИЧНЫ на реальных ответах адаптера — проверяется настоящим
  клиентским маппером (`web/static/cognitive-map.js`), а не его копией;
* блок `communities` карты рендерится честно: три состояния, «Неизвестно»
  вместо нуля, нейтральная подпись не выдаётся за категорию.

TEST-LIFECYCLE: CONTRACT owner=MEM-08-S3 (contracts §4.9/§4.10/§5.2/§10)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

from services import mca_gates
from services import memory_contracts as mc
from services import memory_search as ms
from services import mca_retrieval_context as rc
from services.database import DatabaseService
from web.api import cognitive_map as cm

ROOT = Path(__file__).resolve().parent.parent
CHAT = -1009103
OTHER_CHAT = -1009104
FLAG_KEY = "flags.memory_search_enabled"
ENV_KEY = "MCA_MEMORY_SEARCH_ENABLED"
ADAPTER = ROOT / "web" / "static" / "cognitive-map.js"


@pytest_asyncio.fixture
async def db():
    service = DatabaseService(":memory:")
    await service.initialize()
    yield service
    await service.close()


def _gate(monkeypatch, *, on: bool) -> None:
    """Реальный резолвер: патчится источник значения (`hot.get`) и env-ось."""
    import services.hot_config as hot

    if on:
        monkeypatch.setenv(ENV_KEY, "on")
    else:
        # Заводской дефолт — ON, значит OFF задаётся каталоговым слоем (как у
        # владельца, снявшего флаг), без аварийного env.
        monkeypatch.delenv(ENV_KEY, raising=False)
    real_get = hot.get

    def fake_get(key, default=None):
        if key == FLAG_KEY:
            return on
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


def _candidate(**kwargs):
    base = dict(id=f"ent:{CHAT}:1", entity_type="entity", entity_id="1",
                chat_id=CHAT, score=10.0, channel="entity", preview="Кирилл",
                provenance_backed=True)
    base.update(kwargs)
    return rc.RetrievalCandidate(**base)


def _result(candidates=(), *, status=rc.RETRIEVAL_OK, reason=None,
            channels=("entity",)):
    return rc.RetrievalResult(
        status=status, candidates=tuple(candidates),
        channels_used=tuple(channels), reason_code=reason,
        mode="auto", purpose="ui_search", chat_ids=(CHAT,),
        ambiguity=())


class _StubMemory:
    async def retrieve_fact_candidates(self, chat_id, query, limit=None,
                                       **kwargs):
        return []


STUB_MEMORY = _StubMemory()


# ── 1. гейт: реестр, каталог, заводской дефолт ─────────────────────────────
class TestGateRegistration:
    def test_gate_is_registered_in_existing_registries(self):
        from services import config_cache
        from services import param_catalog as pc

        assert "MCA_MEMORY_SEARCH_ENABLED" in mca_gates.MEMORY_GATES
        default, off_parity = mca_gates.MEMORY_GATES[
            "MCA_MEMORY_SEARCH_ENABLED"]
        assert default is True, "заводской дефолт — ON (правило проекта)"
        assert isinstance(off_parity, str) and "OFF" in off_parity
        assert mca_gates.MEMORY_GATE_CATALOG_KEYS[
            "MCA_MEMORY_SEARCH_ENABLED"] == FLAG_KEY

        spec = pc.get_by_pg_key(FLAG_KEY)
        assert spec is not None, "флаг обязан быть в существующем каталоге"
        assert spec.type == "bool"
        assert spec.category == "flags"
        assert spec.group == "flags_memory"
        assert spec.per_chat is True
        assert spec.title_ru.strip() and spec.description.strip()
        assert config_cache._PG_ONLY_BOOL_DEFAULTS[FLAG_KEY] is True

    @pytest.mark.asyncio
    async def test_resolver_default_on_and_env_half(self, monkeypatch):
        monkeypatch.delenv(ENV_KEY, raising=False)
        assert mca_gates.memory_search_env_enabled() is True
        assert await mca_gates.memory_search_enabled(CHAT) is True
        assert await mca_gates.memory_search_enabled(None) is True

        # Аварийный env важнее каталога и заводского дефолта.
        monkeypatch.setenv(ENV_KEY, "off")
        assert mca_gates.memory_search_env_enabled() is False
        assert await mca_gates.memory_search_enabled(CHAT) is False
        assert await mca_gates.memory_search_enabled(None) is False

    @pytest.mark.asyncio
    async def test_chat_override_beats_global_and_none_ignores_chat(
            self, monkeypatch):
        """chat побеждает global; `chat_id=None` chat-слой не читает (§5.2.1)."""
        from services import chat_params

        monkeypatch.delenv(ENV_KEY, raising=False)

        async def fake_param(chat_id, key, default=None):
            if key == FLAG_KEY:
                return False          # явный per-chat OFF
            return default

        monkeypatch.setattr(chat_params, "get_chat_param", fake_param)
        import services.hot_config as hot
        real_get = hot.get
        monkeypatch.setattr(hot, "get", lambda key, default=None: (
            True if key == FLAG_KEY else real_get(key, default)))

        assert await mca_gates.memory_search_enabled(CHAT) is False, \
            "chat OFF важнее global ON"
        assert await mca_gates.memory_search_enabled(None) is True, \
            "chat_id=None читает только global, исключения нет"


# ── 2. payload карты: аддитивное поле только при ON ────────────────────────
class TestMapPayloadGate:
    @pytest.mark.asyncio
    async def test_field_present_only_when_gate_on(self, db, monkeypatch):
        _gate(monkeypatch, on=True)
        on_payload = await cm.build_cognitive_map(db, CHAT, now=1760000000)
        assert on_payload["search"] == {"enabled": True}

        _gate(monkeypatch, on=False)
        off_payload = await cm.build_cognitive_map(db, CHAT, now=1760000000)
        assert "search" not in off_payload, \
            "OFF обязан совпадать с payload S2 (нет поля)"

        # OFF-паритет: всё остальное — байт-в-байт то же самое.
        on_payload.pop("search")
        assert on_payload == off_payload

    @pytest.mark.asyncio
    async def test_global_scope_uses_global_half(self, db, monkeypatch):
        _gate(monkeypatch, on=True)
        payload = await cm.build_cognitive_map(db, None, now=1760000000)
        assert payload["search"] == {"enabled": True}
        assert payload["scope"]["mode"] == "global"


# ── 3. ручка поиска: OFF — честный disabled до любого поиска ───────────────
class TestSearchEndpointGate:
    @pytest.mark.asyncio
    async def test_gate_off_is_disabled_not_empty(self, db, monkeypatch):
        from fastapi import HTTPException

        _gate(monkeypatch, on=False)
        monkeypatch.setattr(cm, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(cm, "_db_or_503", lambda: db)

        called = []
        real_retrieve = rc.retrieve

        async def spy(*args, **kwargs):
            called.append(1)
            return await real_retrieve(*args, **kwargs)

        monkeypatch.setattr(rc, "retrieve", spy)
        with pytest.raises(HTTPException) as excinfo:
            await cm.memory_search_endpoint(
                request=None, user=None, q="Кирилл", chat_id=CHAT,
                limit=None, cursor=None)
        assert excinfo.value.status_code == 409
        assert excinfo.value.detail == cm.SEARCH_DISABLED_REASON
        assert called == [], "OFF не запускает поиск вообще"

    @pytest.mark.asyncio
    async def test_gate_on_keeps_existing_contract(self, db, monkeypatch):
        _gate(monkeypatch, on=True)

        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate()])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        monkeypatch.setattr(cm, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(cm, "_db_or_503", lambda: db)
        body = await cm.memory_search_endpoint(
            request=None, user=None, q="Кирилл", chat_id=CHAT, limit=5,
            cursor=None)
        assert body["status"] == "ok"
        assert body["query_state"] == "candidates"


# ── 4. UI-состояния из РЕАЛЬНЫХ ответов (клиентский маппер) ────────────────
_NODE_PROBE = r"""
const path = require('path');
const CM = require(path.join(process.argv[2], 'web', 'static',
  'cognitive-map.js'));
const data = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const out = {};
for (const name of Object.keys(data.responses)) {
  const view = CM.searchStateFromResponse(data.responses[name]);
  out[name] = {
    state: view.state,
    text: view.text,
    retryFirstPage: view.retryFirstPage,
    canRetry: view.canRetry,
    items: view.items.map(function (row) {
      return { title: row.title, meta: row.metaLine };
    }),
  };
}
const communities = CM.communitiesView(data.communities);
out.communities = {
  state: communities.state,
  text: communities.text,
  labels: communities.items.map(function (row) {
    return [row.label, row.labelKind, row.memberText];
  }),
};
process.stdout.write(JSON.stringify(out));
"""


def _run_probe(tmp_path, payload: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — проверка клиента пропущена")
    script = tmp_path / "mem08_omnibox_probe.js"
    data = tmp_path / "mem08_omnibox_probe.json"
    script.write_text(_NODE_PROBE, encoding="utf-8")
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    res = subprocess.run([node, str(script), str(ROOT), str(data)],
                         capture_output=True, text=True, timeout=120,
                         cwd=str(ROOT), env=dict(os.environ))
    assert res.returncode == 0, res.stderr[-2000:]
    return json.loads(res.stdout)


class TestUiStateMapping:
    @pytest.mark.asyncio
    async def test_four_outcomes_are_distinct_in_ui(self, db, monkeypatch,
                                                    tmp_path):
        """Реальные ответы адаптера → клиентский маппер → разные состояния."""
        responses = {}

        async def empty_retrieve(db_arg, memory, request):
            return _result([], status=rc.RETRIEVAL_EMPTY,
                           reason="retrieval_empty")

        monkeypatch.setattr(rc, "retrieve", empty_retrieve)
        responses["no_matches"] = (
            await ms.search_memory(db, STUB_MEMORY, query="ничего",
                                   chat_id=CHAT)).as_dict()

        responses["no_rights"] = (
            await ms.search_memory(db, None, query="Кирилл", chat_id=CHAT,
                                   allowed_chat_ids=(OTHER_CHAT,))).as_dict()

        async def error_retrieve(db_arg, memory, request):
            return _result([], status=rc.RETRIEVAL_ERROR,
                           reason="retrieval_error")

        monkeypatch.setattr(rc, "retrieve", error_retrieve)
        responses["error"] = (
            await ms.search_memory(db, None, query="сбой",
                                   chat_id=CHAT)).as_dict()

        async def page_retrieve(db_arg, memory, request):
            return _result([_candidate(id=f"ent:{CHAT}:{n}", entity_id=str(n),
                                       preview=f"Узел {n}")
                            for n in range(1, 4)])

        monkeypatch.setattr(rc, "retrieve", page_retrieve)
        first = await ms.search_memory(db, None, query="узел", chat_id=CHAT,
                                       limit=2)
        assert first.next_cursor
        # Ревизия графа изменилась между страницами → устаревший курсор.
        await db.upsert_node(CHAT, "Новый узел", "user")
        responses["cursor_stale"] = (
            await ms.search_memory(db, None, query="узел", chat_id=CHAT,
                                   limit=2,
                                   cursor=first.next_cursor)).as_dict()
        assert responses["cursor_stale"]["status"] == "cursor_stale"

        communities = await ms.read_active_communities(db, CHAT)
        out = _run_probe(tmp_path, {"responses": responses,
                                    "communities": communities})

        states = {name: out[name]["state"] for name in responses}
        assert states["no_matches"] == mc.QueryState.NO_MATCHES.value
        assert states["no_rights"] == mc.QueryState.NO_RIGHTS.value
        assert states["error"] == mc.QueryState.ERROR.value
        assert states["cursor_stale"] == "cursor_stale"
        assert len(set(states.values())) == 4, states

        # Разные слова: ошибка никогда не звучит как «ничего не найдено».
        assert out["error"]["text"] != out["no_matches"]["text"]
        assert "Ничего не найдено" not in out["error"]["text"]
        assert out["no_rights"]["text"] != out["no_matches"]["text"]
        # cursor_stale — тихий перезапуск, без пустого экрана и без повтора.
        assert out["cursor_stale"]["retryFirstPage"] is True
        assert out["cursor_stale"]["text"] == ""
        assert out["cursor_stale"]["canRetry"] is False
        assert out["error"]["canRetry"] is True

    @pytest.mark.asyncio
    async def test_communities_block_renders_honestly(self, db, tmp_path):
        """Нет сборки — «ещё не собраны»; нет таблиц — «н/д»; без выдумок."""
        no_build = await ms.read_active_communities(db, CHAT)
        assert no_build["state"] in ("no_active_build", "unavailable")
        out = _run_probe(tmp_path, {"responses": {},
                                    "communities": no_build})
        assert out["communities"]["labels"] == []
        assert out["communities"]["state"] in ("no_active_build",
                                              "unavailable")
        assert out["communities"]["text"] != ""

        fake = {"state": "ok", "items": [{
            "community_id": "c-9", "member_count": None,
            "label": "Сообщество 9", "label_kind": "neutral",
            "label_basis": "нет семантической подписи",
            "metrics": {}, "metrics_basis": "unknown",
        }], "total": 1, "shown": 1, "truncated": False}
        out2 = _run_probe(tmp_path, {"responses": {}, "communities": fake})
        label, label_kind, member_text = out2["communities"]["labels"][0]
        assert label == "Сообщество 9"
        assert label_kind == "neutral", \
            "нейтральная подпись не выдаётся за категорию"
        assert member_text == "Неизвестно", \
            "отсутствующая метрика — «Неизвестно», а не 0"


def test_js_omnibox_suite_runs():
    """Поведение omnibox (debounce/гонка/клавиатура) — настоящий node-прогон."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    res = subprocess.run(
        [node, os.path.join("tests", "js", "mem08_omnibox_test.js")],
        capture_output=True, text=True, timeout=180, cwd=str(ROOT))
    assert res.returncode == 0, res.stderr[-2000:]
    assert "MEM-08-S3-OK" in res.stdout, res.stdout[-2000:]
