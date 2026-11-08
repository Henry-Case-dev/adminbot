"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-07 — волна 3: регистрация job сборки.

Контракт `plans/features/memory-cognitive-02/contracts.md` §5.2 (реестр гейтов,
`MCA_MEMORY_COMMUNITIES_ENABLED` — заводской default ON после приёмки) и §6
(запуск сборки — только существующий `memory_maintenance`, никогда на горячем
пути).

Проверяется:

* job зарегистрирован всегда (независимо от гейта) в СУЩЕСТВУЮЩЕМ
  планировщике обслуживания, с `max_instances=1` и `coalesce=True`
  (иначе два прохода одного чата теряют linkage `prev_build_id`);
* гейт резолвится тиком на КАЖДОМ заходе: OFF → тик инертен (ни одного SQL,
  ни одной сборки), ON-hot → сборка запускается без рестарта;
* сборщик достижим ТОЛЬКО из обслуживания памяти (структурная проверка
  исходников: ни ответ, ни retrieval, ни карта, ни `/status` его не зовут);
* ключ гейта зарегистрирован в существующем реестре/каталоге с дефолтом ON;
* явный сохранённый выбор владельца (global/override чата) важнее заводского
  дефолта и сменой дефолта НЕ перетирается.

TEST-LIFECYCLE: CONTRACT owner=MEMORY-07 (contracts §5.2, §6)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services import mca_gates
from services import memory_maintenance as mm
from services.database import DatabaseService

ROOT = Path(__file__).resolve().parent.parent
CHAT = -1001777000777
FLAG_KEY = "flags.memory_communities_enabled"


def _flag_on(monkeypatch) -> None:
    """Каталоговый слой гейта ON: патчится источник значения (`hot.get`),
    а не приватный резолвер — проверяется реальный `mca_gates`."""
    import services.hot_config as hot

    monkeypatch.setenv("MCA_MEMORY_COMMUNITIES_ENABLED", "on")
    real_get = hot.get

    def fake_get(key, default=None):
        if key == FLAG_KEY:
            return True
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


def _flag_off(monkeypatch) -> None:
    import services.hot_config as hot

    monkeypatch.delenv("MCA_MEMORY_COMMUNITIES_ENABLED", raising=False)
    real_get = hot.get

    def fake_get(key, default=None):
        if key == FLAG_KEY:
            return False
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


async def _db(tmp_path, name: str = "communities_job.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _seed_graph(db) -> list[int]:
    """Две связанные сущности — минимальный настоящий граф для сборки."""
    hub = await db.upsert_node(CHAT, "Папаха", "user")
    leaf = await db.upsert_node(CHAT, "Александр", "user")
    await db.upsert_edge(hub, leaf, "знает")
    return [hub, leaf]


async def _builds(db) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT * FROM mca_community_builds ORDER BY started_at, build_id")
    return [dict(row) for row in await cursor.fetchall()]


# ── регистрация job (§6) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_job_registered_always_with_single_instance_and_coalesce(
        tmp_path, monkeypatch):
    """Гейт OFF при старте → job всё равно есть, ровно один инстанс,
    пропуски схлопываются (прецедент intent_heartbeat)."""
    _flag_off(monkeypatch)
    db = await _db(tmp_path, "job_registered.db")
    svc = mm.MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        svc.start()
        job = svc._scheduler.get_job(
            mm.MemoryMaintenanceService.JOB_COMMUNITIES_ID)
        assert job is not None, ("MEMORY-07: job сборки сообществ обязан быть "
                                 "зарегистрирован независимо от гейта")
        assert job.id == "memory_communities_build"
        assert job.max_instances == 1
        assert job.coalesce is True
        interval = job.trigger.interval.total_seconds()
        assert interval == mm._COMMUNITIES_TICK_SECONDS
        # Не горячий путь: период — не секунды запроса, а восстановление drift.
        assert interval >= 600
    finally:
        await svc.shutdown()
        await db.close()


# ── гейт читается каждым тиком (§5.2/§6) ──────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_env_off_tick_makes_no_sql_at_all(
        tmp_path, monkeypatch):
    """Аварийный env OFF → тик выходит ДО любого чтения БД (ноль SQL).

    После активации MEMORY-07 заводской дефолт оси — ON, поэтому нулевой SQL
    гарантирует именно аварийный env-рубильник (`=off`): он резолвится
    раньше scope-скана. Каталоговый OFF остаётся рабочим и проверяется
    отдельно (`test_catalog_off_tick_builds_nothing`): он требует per-chat
    резолва (override чата важнее global), поэтому scope-скан там законен.
    """
    import services.hot_config as hot
    monkeypatch.setenv("MCA_MEMORY_COMMUNITIES_ENABLED", "off")
    real_get = hot.get

    def fake_get(key, default=None):
        if key == FLAG_KEY:
            return True                 # каталог ON — важнее только env
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)
    db = await _db(tmp_path, "gate_off.db")
    svc = mm.MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    builds_calls: list[int] = []
    sql_calls: list[int] = []

    async def spy_chat_ids():
        # Тик обязан выйти ДО любого чтения БД (env-половина гейта).
        sql_calls.append(1)
        return [CHAT]

    from services import memory_communities as communities

    async def fake_build(db_, chat_id, **kwargs):
        builds_calls.append(int(chat_id))
        raise AssertionError("OFF-тик не должен запускать сборку")

    monkeypatch.setattr(svc, "_community_chat_ids", spy_chat_ids)
    monkeypatch.setattr(communities, "build_chat_communities", fake_build)
    try:
        await _seed_graph(db)          # граф есть, но гейт OFF
        await svc._tick_communities()
        assert sql_calls == []         # ни одного запроса scope-скана
        assert builds_calls == []
        assert await _builds(db) == []
        # И прямой резолвер тоже честно OFF (env-аварийный важнее каталога).
        assert await mca_gates.memory_communities_enabled(CHAT) is False
    finally:
        await svc.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_catalog_off_tick_builds_nothing(tmp_path, monkeypatch):
    """Каталоговый OFF (владелец снял флаг) → ни одной сборки и ни строки.

    Per-chat резолв требует списка чатов, поэтому scope-скан допустим; но
    сборщик не вызывается и реестр сборок остаётся пустым.
    """
    _flag_off(monkeypatch)
    db = await _db(tmp_path, "catalog_off.db")
    svc = mm.MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    builds_calls: list[int] = []

    from services import memory_communities as communities

    async def fake_build(db_, chat_id, **kwargs):
        builds_calls.append(int(chat_id))
        raise AssertionError("OFF-тик не должен запускать сборку")

    monkeypatch.setattr(communities, "build_chat_communities", fake_build)
    try:
        await _seed_graph(db)          # граф есть, каталоговый гейт OFF
        await svc._tick_communities()
        assert builds_calls == []
        assert await _builds(db) == []
        assert await mca_gates.memory_communities_enabled(CHAT) is False
    finally:
        await svc.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_gate_hot_toggle_applies_without_restart(tmp_path, monkeypatch):
    """OFF при старте → ON-hot (тот же сервис) → сборка и active-строка;
    OFF-hot → следующий тик новых сборок не создаёт."""
    _flag_off(monkeypatch)
    db = await _db(tmp_path, "hot_toggle.db")
    svc = mm.MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        await _seed_graph(db)
        svc.start()
        job = svc._scheduler.get_job(
            mm.MemoryMaintenanceService.JOB_COMMUNITIES_ID)
        assert job is not None            # регистрация не зависела от гейта

        await svc._tick_communities()     # OFF
        assert await _builds(db) == []

        _flag_on(monkeypatch)             # хозяин включил тумблер, рестарта нет
        assert await mca_gates.memory_communities_enabled(CHAT) is True
        await svc._tick_communities()
        first = await _builds(db)
        assert len(first) == 1
        assert first[0]["status"] == "active"

        _flag_off(monkeypatch)            # выключили снова — тик инертен
        await svc._tick_communities()
        assert len(await _builds(db)) == 1
    finally:
        await svc.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_tick_survives_build_failure(tmp_path, monkeypatch):
    """Ошибка сборки не рвёт планировщик (fail-open обслуживания)."""
    _flag_on(monkeypatch)
    db = await _db(tmp_path, "tick_failure.db")
    svc = mm.MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    from services import memory_communities as communities

    async def boom(db_, chat_id, **kwargs):
        raise RuntimeError("сборка упала")

    monkeypatch.setattr(communities, "build_chat_communities", boom)
    try:
        await _seed_graph(db)
        await svc._tick_communities()     # не бросает
    finally:
        await svc.shutdown()
        await db.close()


# ── структурная недостижимость на горячем пути (§6) ───────────────────────

def _imports_module(tree: ast.AST, module: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module or alias.name.startswith(
                        module + "."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") == module:
                return True
            if node.module == module.rsplit(".", 1)[0]:
                for alias in node.names:
                    if alias.name == module.rsplit(".", 1)[1]:
                        return True
    return False


def test_builder_reachable_only_from_memory_maintenance():
    """`build_chat_communities` зовётся ТОЛЬКО из обслуживания памяти.

    Горячие пути (ответ, retrieval, карта, `/status`) не импортируют модуль
    сборщика и не вызывают его — сборка физически не может попасть в запрос.
    """
    hot_paths = (
        "services/direct_chat_service.py",
        "services/mca_retrieval_context.py",
        "web/api/memory_agi.py",
        "web/api/cognitive_map.py",
        "handlers/menu.py",
    )
    for relative in hot_paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "build_chat_communities" not in text, relative
        tree = ast.parse(text)
        assert not _imports_module(tree, "services.memory_communities"), \
            relative

    callers: set[str] = set()
    for path in sorted((ROOT / "services").glob("*.py")) + sorted(
            (ROOT / "handlers").glob("*.py")) + sorted(
            (ROOT / "web").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "build_chat_communities" in text:
            callers.add(path.relative_to(ROOT).as_posix())
    assert callers == {"services/memory_communities.py",
                       "services/memory_maintenance.py"}, callers


def test_maintenance_module_uses_existing_scheduler_only():
    """Второго воркера/планировщика нет: job добавляется существующим
    `AsyncIOScheduler` обслуживания с обязательными `max_instances/coalesce`."""
    source = (ROOT / "services" / "memory_maintenance.py").read_text(
        encoding="utf-8")
    assert 'JOB_COMMUNITIES_ID = "memory_communities_build"' in source
    block = source.split("id=self.JOB_COMMUNITIES_ID", 1)
    assert len(block) == 2
    assert "max_instances=1, coalesce=True" in block[1][:120]
    # Новых scheduler-классов не появляется.
    assert "BackgroundScheduler(" not in source
    assert source.count("AsyncIOScheduler(") == 1


# ── реестр флага (§5.2) ───────────────────────────────────────────────────

def test_flag_registered_default_on_through_existing_mechanism():
    from services import config_cache
    from services import param_catalog as pc

    assert "MCA_MEMORY_COMMUNITIES_ENABLED" in mca_gates.MEMORY_GATES
    default, off_parity = mca_gates.MEMORY_GATES[
        "MCA_MEMORY_COMMUNITIES_ENABLED"]
    assert default is True            # готовая функция включена при выкате
    assert isinstance(off_parity, str) and "OFF" in off_parity
    assert mca_gates.MEMORY_GATE_CATALOG_KEYS[
        "MCA_MEMORY_COMMUNITIES_ENABLED"] == FLAG_KEY

    spec = pc.get_by_pg_key(FLAG_KEY)
    assert spec is not None, "флаг обязан быть в существующем каталоге"
    assert spec.type == "bool"
    assert spec.category == "flags"
    assert spec.group == "flags_memory"
    assert spec.per_chat is True
    assert spec.title_ru.strip()
    assert spec.description.strip()
    # Заводской дефолт ON и в синтетике конфига (не «не задано»).
    assert config_cache._PG_ONLY_BOOL_DEFAULTS[FLAG_KEY] is True


@pytest.mark.asyncio
async def test_flag_resolver_default_on_and_env_half_is_separate(monkeypatch):
    """Резолвер по умолчанию ON; env-аварийный OFF читается без каталога."""
    monkeypatch.delenv("MCA_MEMORY_COMMUNITIES_ENABLED", raising=False)
    assert mca_gates.memory_communities_env_enabled() is True
    assert await mca_gates.memory_communities_enabled(CHAT) is True
    assert await mca_gates.memory_communities_enabled(None) is True

    # env-аварийный OFF важнее каталога (и заводского дефолта).
    monkeypatch.setenv("MCA_MEMORY_COMMUNITIES_ENABLED", "off")
    assert mca_gates.memory_communities_env_enabled() is False
    assert await mca_gates.memory_communities_enabled(CHAT) is False

    _flag_on(monkeypatch)
    assert mca_gates.memory_communities_env_enabled() is True
    assert await mca_gates.memory_communities_enabled(CHAT) is True
    assert await mca_gates.memory_communities_enabled(None) is True


@pytest.mark.asyncio
async def test_explicit_off_override_survives_factory_default_change(
        monkeypatch):
    """Смена заводского дефолта OFF→ON не сбрасывает выбор владельца.

    Проверяются ОБА слоя существующего резолва (второго механизма нет):
    сохранённый global (`hot.get` ← строка bot_settings) и сохранённый
    per-chat override (`chat_params.overrides`). Явный OFF важнее нового
    заводского ON и переживает включение по умолчанию; заводской дефолт при
    этом остаётся ON для чата без override.
    """
    from services import chat_params

    assert mca_gates.MEMORY_GATES[
        "MCA_MEMORY_COMMUNITIES_ENABLED"][0] is True     # новый заводской старт
    monkeypatch.delenv("MCA_MEMORY_COMMUNITIES_ENABLED", raising=False)
    OTHER_CHAT = CHAT + 1

    # 1) Global: владелец уже сохранил OFF до смены дефолта.
    import services.hot_config as hot
    real_get = hot.get

    def fake_get(key, default=None):
        if key == FLAG_KEY:
            return False                 # существующая строка bot_settings
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)
    assert await mca_gates.memory_communities_enabled(None) is False

    # 2) Per-chat: у чата CHAT сохранён OFF, у OTHER_CHAT override нет.
    class _Cache:
        async def get_chat_params(self, chat_id):
            if int(chat_id) == CHAT:
                return {"overrides": {FLAG_KEY: False}}
            return {"overrides": {}}

    saved = chat_params.get_chat_params_cache()
    chat_params.set_chat_params_cache(_Cache())
    try:
        assert await mca_gates.memory_communities_enabled(CHAT) is False
        assert await mca_gates.memory_communities_enabled(OTHER_CHAT) is False
    finally:
        chat_params.set_chat_params_cache(saved)

    # 3) Тот же чат, но global-значение уже новое (заводской ON): explicit
    #    per-chat OFF продолжает побеждать и не «схлопывается» к дефолту.
    monkeypatch.setattr(hot, "get", real_get)
    chat_params.set_chat_params_cache(_Cache())
    try:
        assert await mca_gates.memory_communities_enabled(OTHER_CHAT) is True
        assert await mca_gates.memory_communities_enabled(CHAT) is False
    finally:
        chat_params.set_chat_params_cache(saved)
