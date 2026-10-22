"""EMBED-FALLBACK-FIX (аудит 23.10.2026, находка F2) — per-slot connection.

Дефект на проде: `build_credential_pool()` подставлял ОДИН base_url (primary,
apinet.cloud) всем ключам. Два запасных Google-слота, которые владелец явно
настроил (`models.embedding_fallback1/2_base_url` + свои ключи), уходили на
apinet, получали 401 и помечались `auth_failed` — запасные слоты фактически
не работали.

Контракт после фикса:
  * каждый named slot (primary/fallback_1/fallback_2) несёт СВОЙ base_url и
    модель из существующего резолвера профилей (`resolve_embedding_profiles`:
    hot → env → общий/легаси → primary) — dispatch = панель = identity;
  * per-slot адрес не задан → прежнее поведение (общий/легаси адрес, затем
    primary), без исключений; extra_N — соединение primary (как раньше);
  * provider-identity слота — по фактическому host его адреса (adapter
    выбирается по адресу слота, ключи Google идут на Gemini-endpoint);
  * квоты/группы и ротация не меняются: группы по-прежнему из
    `EMBEDDING_QUOTA_GROUP_LABELS`/auto-alias, 429 одной группы не трогает
    другие, 401 слота не ломает остальные.

TEST-LIFECYCLE: REGRESSION owner=EMBED-FALLBACK-FIX/F2 (дефект: все слоты на
primary-адресе → 401 Google-ключей); CONTRACT owner=EMBED-FALLBACK-FIX/F2
(dispatch = resolve_embedding_profiles).
"""
import pytest

from services import embedding_control_plane as ecp
from services.embedding_control_plane import (
    AdaptiveController, EmbeddingExecutor, Priority, QuotaGroupRegistry,
    build_credential_pool, resolve_embedding_profiles,
)
from services.llm_client import LLMAuthError, LLMRateLimitError

pytestmark = pytest.mark.asap4

PRIMARY_BASE = "https://apinet.test/v1"
PRIMARY_MODEL = "primary-model"
FB1_BASE = "https://generativelanguage.test/v1beta/openai"
FB1_MODEL = "google-embed-1"
FB2_BASE = "https://google-second.test/v1beta/openai"
FB2_MODEL = "google-embed-2"


@pytest.fixture(autouse=True)
def fresh_ecp(monkeypatch):
    """Чистые singleton'ы контрол-плейна + нулевой transport backoff."""
    ecp.REGISTRY = QuotaGroupRegistry()
    ecp.CONTROLLER = AdaptiveController()
    ecp.SCHEDULER = ecp.PriorityScheduler()
    ecp.EXECUTOR = None
    ecp._last_rotation_warn = 0.0
    ecp._last_primary_warn = 0.0
    monkeypatch.setattr(ecp, "_TRANSPORT_BACKOFF_BASE", 0.0)
    yield ecp


def _isolate(monkeypatch, values):
    """hot-слой = только заданные ключи; env-слой EMBEDDING_* погашен в "".

    Патчатся оба семейства резолверов: пул (`_hot_get`/`_settings_value`) и
    профили (`_profile_hot`/`_settings_default`) — иначе тест читал бы
    реальный `.env` машины.
    """
    def _fake_setting(name, default=""):
        if str(name).startswith("EMBEDDING_"):
            return ""
        return default

    monkeypatch.setattr(ecp, "_hot_get",
                        lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(ecp, "_settings_value", _fake_setting)
    monkeypatch.setattr(
        ecp, "_profile_hot",
        lambda key, default="": str(values.get(key, default) or "").strip())
    monkeypatch.setattr(ecp, "_settings_default", _fake_setting)


def _three_slots(monkeypatch, extra=None):
    values = {
        "keys.embedding_api_key": "k-primary",
        "keys.embedding_fallback_api_key": "k-fb1",
        "keys.embedding_fallback_api_key_2": "k-fb2",
        "models.embedding_base_url": PRIMARY_BASE,
        "models.embedding_model_name": PRIMARY_MODEL,
        "models.embedding_fallback1_base_url": FB1_BASE,
        "models.embedding_fallback1_model": FB1_MODEL,
        "models.embedding_fallback2_base_url": FB2_BASE,
        "models.embedding_fallback2_model": FB2_MODEL,
        "keys.embedding_quota_group_labels": "",
    }
    if extra:
        values.update(extra)
    _isolate(monkeypatch, values)
    return values


class RecordingLLM:
    """embed_once-контракт адаптера: фиксирует ФАКТИЧЕСКИЙ endpoint вызова."""

    def __init__(self, script: list | None = None, dim: int = 4):
        self._embed_model = PRIMARY_MODEL
        self.script = list(script or [])
        self.calls: list[dict] = []
        self.legacy_calls = 0
        self.dim = dim

    async def embed_once(self, texts, *, api_key, base_url=None, model=None,
                         max_retries=0, retry_statuses=()):
        self.calls.append({"key": api_key, "base_url": base_url,
                           "model": model, "texts": list(texts)})
        behavior = self.script.pop(0) if self.script else "ok"
        if behavior == "rate_limit":
            exc = LLMRateLimitError("LLM rate limited (429)")
            exc.headers = {"Retry-After": "5"}
            exc.body = ""
            raise exc
        if behavior == "auth":
            raise LLMAuthError("LLM auth failed (401)")
        return [[0.1 + i * 0.01 for i in range(self.dim)] for _ in texts]

    async def embed(self, texts):
        self.legacy_calls += 1
        return [[0.1] * self.dim for _ in texts]


# ── 1. Каждый слот несёт собственный адрес/модель ───────────────────────────

def test_pool_slots_carry_their_own_base_url_and_model(monkeypatch):
    _three_slots(monkeypatch)
    pool = {c.alias: c for c in build_credential_pool()}
    assert (pool["primary"].base_url, pool["primary"].model) == (
        PRIMARY_BASE, PRIMARY_MODEL)
    assert (pool["fallback_1"].base_url, pool["fallback_1"].model) == (
        FB1_BASE, FB1_MODEL)
    assert (pool["fallback_2"].base_url, pool["fallback_2"].model) == (
        FB2_BASE, FB2_MODEL)
    # provider-identity — фактический host слота (диагностика/панель).
    assert pool["primary"].provider == "apinet.test"
    assert pool["fallback_1"].provider == "generativelanguage.test"
    assert pool["fallback_2"].provider == "google-second.test"
    # ключи/группы не подменены: свой ключ + прежняя auto-группа alias'а.
    assert [pool[a].api_key for a in ("primary", "fallback_1",
                                      "fallback_2")] == [
        "k-primary", "k-fb1", "k-fb2"]
    assert [pool[a].quota_group_id for a in ("primary", "fallback_1",
                                             "fallback_2")] == [
        "primary", "fallback_1", "fallback_2"]


def test_pool_connection_matches_resolved_profiles(monkeypatch):
    """CONTRACT: dispatch-адрес слота = адрес профиля (панель/identity)."""
    _three_slots(monkeypatch)
    profiles = resolve_embedding_profiles()
    for credential in build_credential_pool():
        profile = profiles[credential.alias]
        assert credential.base_url == profile.base_url, credential.alias
        assert credential.model == profile.model, credential.alias


# ── 2. Обратная совместимость: незаданный адрес → общий/primary ─────────────

def test_unset_slot_address_falls_back_to_primary(monkeypatch):
    """Прежнее поведение: ничего лишнего не настроено → все слоты на primary."""
    _isolate(monkeypatch, {
        "keys.embedding_api_key": "k-primary",
        "keys.embedding_fallback_api_key": "k-fb1",
        "keys.embedding_fallback_api_key_2": "k-fb2",
        "models.embedding_base_url": PRIMARY_BASE,
        "models.embedding_model_name": PRIMARY_MODEL,
    })
    pool = build_credential_pool()
    assert len(pool) == 3
    assert {c.base_url for c in pool} == {PRIMARY_BASE}
    assert {c.model for c in pool} == {PRIMARY_MODEL}


def test_legacy_common_fallback_address_is_used(monkeypatch):
    """Легаси-общий адрес (models.embedding_fallback_*) → адрес Fallback 1,
    Fallback 2 наследует его (документированный режим миграции)."""
    _isolate(monkeypatch, {
        "keys.embedding_api_key": "k-primary",
        "keys.embedding_fallback_api_key": "k-fb1",
        "keys.embedding_fallback_api_key_2": "k-fb2",
        "models.embedding_base_url": PRIMARY_BASE,
        "models.embedding_model_name": PRIMARY_MODEL,
        "models.embedding_fallback_base_url": "https://legacy-fb.test/v1",
        "models.embedding_fallback_model": "legacy-fb-model",
    })
    pool = {c.alias: c for c in build_credential_pool()}
    assert pool["primary"].base_url == PRIMARY_BASE
    assert pool["fallback_1"].base_url == "https://legacy-fb.test/v1"
    assert pool["fallback_1"].model == "legacy-fb-model"
    assert pool["fallback_2"].base_url == "https://legacy-fb.test/v1"
    assert pool["fallback_2"].model == "legacy-fb-model"


def test_extra_slots_keep_primary_connection(monkeypatch):
    """extra_N не имеет своих каталог-настроек → соединение primary."""
    _three_slots(monkeypatch, extra={"keys.embedding_extra_api_keys":
                                     "k-extra-1;k-extra-2"})
    pool = {c.alias: c for c in build_credential_pool()}
    assert pool["extra_1"].base_url == PRIMARY_BASE
    assert pool["extra_1"].model == PRIMARY_MODEL
    assert pool["extra_2"].base_url == PRIMARY_BASE


# ── 3. Executor: сбой primary → следующий слот идёт на СВОЙ адрес ───────────

@pytest.mark.asyncio
async def test_executor_failover_uses_slot_endpoint(monkeypatch):
    """RED до фикса: второй вызов уходил на primary-адрес (apinet) и получал
    401 от Google-ключа."""
    _three_slots(monkeypatch)
    llm = RecordingLLM(script=["rate_limit", "ok"])
    executor = EmbeddingExecutor(llm)
    vectors = await executor.embed(["текст"], priority=Priority.P1_WRITE)
    assert len(vectors) == 1 and len(vectors[0]) == llm.dim
    assert [c["key"] for c in llm.calls] == ["k-primary", "k-fb1"]
    assert llm.calls[0]["base_url"] == PRIMARY_BASE
    assert llm.calls[0]["model"] == PRIMARY_MODEL
    assert llm.calls[1]["base_url"] == FB1_BASE          # ← собственный адрес
    assert llm.calls[1]["model"] == FB1_MODEL
    # adapter выбирается по host'у слота: Google-слот = Gemini-контракт.
    assert executor.adapter_for(FB1_BASE).name == "gemini"
    assert executor.adapter_for(PRIMARY_BASE).name == "openai-compatible"


@pytest.mark.asyncio
async def test_executor_auth_failed_slot_does_not_break_others(monkeypatch):
    """401 одного слота = auth_failed ЭТОГО credential'а; следующая
    логическая попытка идёт на другой слот и на его собственный адрес."""
    _three_slots(monkeypatch)
    llm = RecordingLLM(script=["auth", "ok"])
    executor = EmbeddingExecutor(llm)
    with pytest.raises(LLMAuthError):
        await executor.embed(["a"], priority=Priority.P1_WRITE)
    assert ecp.REGISTRY.credential_health("primary") == "auth_failed"
    assert ecp.REGISTRY.credential_health("fallback_1") == "healthy"

    vectors = await executor.embed(["b"], priority=Priority.P1_WRITE)
    assert len(vectors) == 1
    assert llm.calls[-1]["key"] == "k-fb1"
    assert llm.calls[-1]["base_url"] == FB1_BASE
    # слот, доказавший работоспособность, остаётся healthy; изоляция цела.
    assert ecp.REGISTRY.credential_health("fallback_1") == "healthy"
    assert ecp.REGISTRY.credential_health("primary") == "auth_failed"


@pytest.mark.asyncio
async def test_primary_and_chat_providers_stay_independent(monkeypatch):
    """Primary-эмбеддинги могут жить у другого провайдера, чем чат, а
    fallback-слоты — у третьего: маршрутизация чисто по адресу слота."""
    _three_slots(monkeypatch)
    llm = RecordingLLM()
    llm._chat_base_url = "https://chat-provider.test/api/v1"   # чат — иной
    executor = EmbeddingExecutor(llm)
    await executor.embed(["x"], priority=Priority.P0_QUERY)
    assert llm.calls[0]["base_url"] == PRIMARY_BASE != llm._chat_base_url
