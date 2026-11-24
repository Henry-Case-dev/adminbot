"""SIMPLIFY 2026-11-24 (§1 owner corrective): упрощение embedding compat.

Каждый тест привязан к строке `SIMPL-01..07` карты
`plans/features/embed-identity-compat/requirements-map.json`:

* SIMPL-01 — смена провайдера/endpoint/ключа/alias/PCI/quota не является
  сменой embedding-space; `auth_failed` привязан к значению ключа.
* SIMPL-02 — совместимая резервная нога пригодна для записи И поиска;
  кэш не гейтится провайдерным endpoint.
* SIMPL-03 — несовместимость только по наблюдаемым свойствам
  (модель/размерность/числа), а не по отсутствию допуска/записи.
* SIMPL-04 — проба лёгкая: `insufficient` не останавливает память и не
  паузит уже идущую сборку.
* SIMPL-05 — аудит уже принят входом (`audit-2026-11-24.md`); здесь только
  регрессии снятых механизмов.
* SIMPL-06 — техническая валидация ответа сохранена и усилена (count/длина/
  конечные числа), реальный `incompatible` по-прежнему закрывает запись.
* SIMPL-07 — новых identity-форматов/таблиц нет: MSI/admission прежние.

Harness переиспользуется из `test_embed_identity_compat` (реальная SQLite +
sqlite-vec + подменяемый hot-конфиг), без моков проверяемого поведения.
"""
import re
import time

import pytest

from services import embedding_control_plane as ecp
from services import graphrag_rebuild as gr
from services.llm_client import LLMBadResponseError, LLMClient
from tests import test_embed_identity_compat as contract
from tests import test_embed_identity_compat_restart_legacy as restart
# Реюз существующего fixture-окружения (реальная БД/sqlite-vec/hot-config).
from tests.test_embed_identity_compat import ctx  # noqa: F401

DIMS = contract.DIMS
INDEX = contract.INDEX
MODEL = contract.MODEL


def _credential(alias: str, key: str) -> ecp.EmbeddingCredential:
    return ecp.EmbeddingCredential(
        alias=alias, api_key=key, base_url=contract.NEW_HOST, model=MODEL,
        provider="nano.test", quota_group_id=alias, quota_group_known=True)


async def _legacy_active(ctx) -> dict:
    """ACTIVE-строка без выводимого MSI: модель/preprocessing неизвестны,
    fingerprint не воспроизводится. Размерность живая (равная)."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp = ctx.mm._identity_fingerprint()
    row = await contract._register_generation(
        ctx, old_fp, status="active")
    await restart._legacy_row(
        ctx, row["generation_id"], model=None, preprocessing_version=None,
        fingerprint="0" * 64)
    return row


# ── SIMPL-01 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simpl01_provider_endpoint_change_keeps_index_serviceable(ctx):
    """Только API-провайдер/endpoint сменился при той же модели: запись и
    поиск идут на существующем индексе, проба не вызывается, REINDEX/pending
    не выставляются, нового поколения нет, старый провайдер не ожидается."""
    await contract._seed(ctx, contract._docs())
    old_fp = ctx.mm._identity_fingerprint()
    await contract._register_generation(ctx, old_fp, status="active")

    ctx.hot.base_url = contract.NEW_HOST
    new_fp = ctx.mm._identity_fingerprint()
    assert new_fp != old_fp, "endpoint действительно изменился"

    probed: list = []

    async def probe_must_not_run(texts):
        probed.append(list(texts))
        raise AssertionError("probe must not run for provider-only change")

    compat = await ecp.resolve_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS)
    assert compat["state"] == ecp.STATE_COMPATIBLE
    assert compat["class"] == ecp.COMPAT_INSTANT
    assert compat["action"] == "none"
    assert compat["serviceable"] is True
    assert compat["needs_probe"] is False

    ensured = await ecp.ensure_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS,
        embed_fn=probe_must_not_run, force_probe=True)
    assert ensured["state"] == ecp.STATE_COMPATIBLE
    assert probed == [], "пересертификация не требуется"

    rows = await contract._generation_rows(ctx.db)
    assert len(rows) == 1, "новое поколение не регистрируется"
    assert rows[0]["status"] == "active" and rows[0]["fingerprint"] == old_fp
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []
    assert await ctx.mm._index_generation_ok(INDEX) is True
    assert await ctx.mm._vec_write_allowed(INDEX) is True

    health = await gr.generation_status(
        ctx.db, current_fp=new_fp, current_dims=DIMS)
    graph = {i["index"]: i for i in health["indexes"]}[INDEX]
    assert graph["state"] == "active"
    assert graph["reindex_required"] is False, \
        "провайдерный endpoint не повод показывать перестройку"

    # alias/quota/host меняют PCI (провенанс), но не вердикт совместимости.
    primary = ecp.EmbeddingProfile(
        alias="primary", base_url=contract.OLD_HOST, model=MODEL,
        quota_group="qg-a")
    fallback = ecp.EmbeddingProfile(
        alias="fallback_1", base_url=contract.NEW_HOST, model=MODEL,
        quota_group="qg-b")
    assert ecp.connection_identity(primary) != ecp.connection_identity(fallback)
    with_pci = await ecp.resolve_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS,
        conn_now=ecp.connection_identity(fallback))
    assert with_pci["state"] == ecp.STATE_COMPATIBLE


def test_simpl01_msi_ignores_provider_namespace():
    """Провайдерный namespace/префикс `models/` — не другое пространство;
    реально другая модель остаётся другой."""
    base = ecp.model_space_identity(
        model="gemini-embedding-001", dimension=DIMS)
    assert base == ecp.model_space_identity(
        model="google/gemini-embedding-001", dimension=DIMS)
    assert base == ecp.model_space_identity(
        model="models/gemini-embedding-001", dimension=DIMS)
    assert base != ecp.model_space_identity(
        model="text-embedding-004", dimension=DIMS)
    # Размерность по-прежнему часть пространства.
    assert base != ecp.model_space_identity(
        model="gemini-embedding-001", dimension=DIMS + 4)


def test_simpl01_auth_failed_is_per_key_and_expires():
    """`auth_failed` не перманентен для alias: заменённый ключ обслуживается
    сразу (без рестарта); тот же ключ повторяется после TTL."""
    registry = ecp.QuotaGroupRegistry()
    old = _credential("primary", "old-secret")
    rotated = _credential("primary", "rotated-secret")
    old_fp = ecp.credential_key_fingerprint(old.api_key)
    assert old_fp and old_fp != ecp.credential_key_fingerprint(rotated.api_key)

    registry.mark_credential("primary", ecp.HEALTH_AUTH_FAILED, key_fp=old_fp)
    assert registry.credential_health("primary", old_fp) == \
        ecp.HEALTH_AUTH_FAILED
    assert registry.usable_credentials([old], "primary") == []
    assert registry.usable_credentials([rotated], "primary") == [rotated]
    executor = ecp.EmbeddingExecutor(None, registry)
    assert executor._pick_credential([old, rotated]) is rotated, \
        "ротация ключа обслуживается в этом же процессе"

    # Протухший auth_failed больше не блокирует тот же (не заменённый) ключ.
    registry._cred_health[("primary", old_fp)] = (
        ecp.HEALTH_AUTH_FAILED, time.time() - 1.0)
    assert registry.credential_health("primary", old_fp) == \
        ecp.HEALTH_HEALTHY

    # Alias-level запись (панель/старые вызовы) продолжает действовать.
    registry.mark_credential("fallback_1", ecp.HEALTH_AUTH_FAILED)
    assert registry.credential_health("fallback_1") == ecp.HEALTH_AUTH_FAILED
    assert registry.credential_health("fallback_1", "ffffffff") == \
        ecp.HEALTH_AUTH_FAILED
    registry.mark_credential("fallback_1", ecp.HEALTH_HEALTHY)
    assert registry.credential_health("fallback_1") == ecp.HEALTH_HEALTHY


# ── SIMPL-02 / SIMPL-04 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simpl02_insufficient_active_equal_dims_serves_reads(ctx):
    """`insufficient` + ACTIVE + равная размерность: чтение открыто, запись
    закрыта (text-only). Равная размерность — обязательное условие: при
    доказанном расхождении читать чужой индекс нельзя."""
    row = await _legacy_active(ctx)
    assert await ctx.mm._index_generation_ok(INDEX) is True, \
        "ожидание допуска не делает всю память FTS-only"
    assert await ctx.mm._index_generation_writable(INDEX) is False
    assert await ctx.mm._vec_write_allowed(INDEX) is False, \
        "в ACTIVE без вердикта новые векторы не кладутся"

    await restart._legacy_row(ctx, row["generation_id"], dims=DIMS + 4)
    assert await ctx.mm._index_generation_ok(INDEX) is False, \
        "доказанная другая размерность закрывает чтение"


def test_simpl02_cache_gate_uses_model_space_not_provider(ctx, monkeypatch):
    """Кэш гейтится MSI (модельное пространство), а не host/alias: вектор
    совместимой резервной ноги кэшируется; чужая модель — нет."""
    primary = ecp.EmbeddingProfile(
        alias="primary", base_url=contract.OLD_HOST, model=MODEL,
        quota_group="qg")
    fallback = ecp.EmbeddingProfile(
        alias="fallback_1", base_url=contract.NEW_HOST, model=MODEL,
        quota_group="qg")
    monkeypatch.setattr(ecp, "last_served_credential", lambda: {
        "alias": "fallback_1", "base_url": contract.NEW_HOST, "model": MODEL})
    monkeypatch.setattr(ecp, "resolve_embedding_profiles", lambda: {
        "primary": primary, "fallback_1": fallback})
    assert ctx.mm._serving_route_space_matches() is True, \
        "совместимая fallback-нога того же пространства"

    other = ecp.EmbeddingProfile(
        alias="fallback_1", base_url=contract.NEW_HOST,
        model=contract.OTHER_MODEL, quota_group="qg")
    monkeypatch.setattr(ecp, "resolve_embedding_profiles", lambda: {
        "primary": primary, "fallback_1": other})
    assert ctx.mm._serving_route_space_matches() is False, \
        "вектор другой модели в кэш не кладём"


# ── SIMPL-03 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simpl03_missing_provenance_is_not_incompatible(ctx):
    """Отсутствие служебной записи/допуска — не доказательство чужого
    пространства (`insufficient`); доказанная другая размерность — да
    (`incompatible` → controlled migration)."""
    row = await _legacy_active(ctx)
    ctx.hot.base_url = contract.NEW_HOST
    new_fp = ctx.mm._identity_fingerprint()

    compat = await ecp.resolve_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS)
    assert compat["state"] == ecp.STATE_INSUFFICIENT
    assert compat["action"] != "controlled_migration"
    assert compat["serviceable"] is False, \
        "допуск не выдумывается, но и не превращается в incompatible"

    await restart._legacy_row(ctx, row["generation_id"], dims=DIMS + 4)
    proven = await ecp.resolve_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS)
    assert proven["state"] == ecp.STATE_INCOMPATIBLE
    assert proven["reason_code"] == "dimension_changed"
    assert proven["action"] == "controlled_migration"


# ── SIMPL-06 ────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _client_with(monkeypatch, payload: dict) -> LLMClient:
    client = LLMClient("https://nano.test/v1", "k", "chat", MODEL)

    async def fake_post(*args, **kwargs):
        return _Resp(payload)

    monkeypatch.setattr(client, "_post", fake_post)
    return client


@pytest.mark.asyncio
async def test_simpl06_control_plane_rejects_malformed_vectors(monkeypatch):
    """Техническая валидация ответа: count, непустые/равные размерности,
    только конечные числа; нарушение — существующий LLMBadResponseError."""
    good = [{"embedding": [0.1] * DIMS}, {"embedding": [0.2] * DIMS}]
    client = _client_with(monkeypatch, {"data": good})
    assert await client.embed_once(["a", "b"], api_key="k") == [
        [0.1] * DIMS, [0.2] * DIMS]

    bad_payloads = {
        "count": {"data": good[:1]},
        "empty": {"data": [{"embedding": []}] * 1},
        "ragged": {"data": [{"embedding": [0.1] * DIMS},
                            {"embedding": [0.1] * (DIMS + 1)}]},
        "nan": {"data": [{"embedding": [float("nan")] * DIMS},
                         {"embedding": [0.1] * DIMS}]},
        "inf": {"data": [{"embedding": [float("inf")] * DIMS},
                         {"embedding": [0.1] * DIMS}]},
        "text": {"data": [{"embedding": ["0.1"] * DIMS},
                          {"embedding": [0.1] * DIMS}]},
    }
    for label, payload in bad_payloads.items():
        client = _client_with(monkeypatch, payload)
        expected = 2 if label != "empty" else 1
        with pytest.raises(LLMBadResponseError):
            await client.embed_once(["a", "b"][:expected], api_key="k")

    # Legacy `embed()` (EMBED_CONTROL_PLANE_ENABLED=false) — тот же guard.
    legacy = _client_with(monkeypatch, {
        "data": [{"embedding": [float("nan")] * DIMS}]})
    with pytest.raises(LLMBadResponseError):
        await legacy.embed(["a"])


@pytest.mark.asyncio
async def test_simpl06_real_incompatibility_still_blocks_write(ctx):
    """Упрощение не ослабляет защиту: доказанная другая модель/размерность
    по-прежнему закрывает запись и ведёт в controlled migration."""
    row = await _legacy_active(ctx)
    await restart._legacy_row(ctx, row["generation_id"], dims=DIMS + 4)
    assert await ctx.mm._vec_write_allowed(INDEX) is False
    compat = await ecp.resolve_index_compat(
        ctx.db, INDEX, current_fp=ctx.mm._identity_fingerprint(),
        current_dims=DIMS)
    assert compat["state"] == ecp.STATE_INCOMPATIBLE
    assert compat["action"] == "controlled_migration"


# ── SIMPL-07 ────────────────────────────────────────────────────────────────

def test_simpl07_msi_and_admission_formats_unchanged():
    """Новых identity-форматов нет: тот же MSI-хеш и тот же `admit1:`
    (совместимо с record'ами, записанными до упрощения)."""
    space = ecp.model_space_identity(model=MODEL, dimension=DIMS)
    assert re.fullmatch(r"[0-9a-f]{16}", space)
    conn = ecp.connection_identity(ecp.EmbeddingProfile(
        alias="primary", base_url=contract.OLD_HOST, model=MODEL,
        quota_group="qg"))
    assert re.fullmatch(r"[0-9a-f]{16}", conn)
    admission = ecp.format_admission(
        space, conn, 8, 0.99, 0.95, 0.9, 1_700_000_000)
    parsed = ecp.parse_admission(admission)
    assert parsed is not None
    assert parsed["space"] == space and parsed["conn"] == conn
    assert ecp.admission_valid(parsed, space_now=space, conn_now=conn)
