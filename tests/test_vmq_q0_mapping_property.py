"""VMQ-ONTO-01 Q-08 — property-тесты поля случайности (`mca_random_source`).

Инкремент A (`vmq-q0`): закрываем НЕДОСТАЮЩИЙ evidence строки Q-08
(«one field/one effective provider, unbiased mapping, scoped focus»),
не меняя продукт. Код контура уже в 2.58.274; тесты проверяют наблюдаемое
поведение через реальные входы (`RandomSourceService.draw_index`,
`resolve_selection`, durable-журнал/партии) и НЕ подменяют целевое поведение
моками.

T1. Rejection sampling без modulo bias на детерминированном fake
    quantum-клиенте: 8-битный диапазон (256 значений), n=3 → ровно 85/85/85
    выданных индексов; значение 255 (>= limit=255) отвергнуто и честно
    журналировано. Контрольная наивная формула `value % 3` на том же фикстуре
    даёт 86/85/85 — тест действительно чувствителен к отсутствию rejection.
T2. Ровно один effective provider на draw, без смешивания источников:
    ANU-партия расходуется только пока она есть, затем LfDR; каждая запись
    журнала принадлежит одному провайдеру; PRNG-откат честно подписан
    (`pseudorandom` / `python-random`, `provider_id=None`,
    `entropy_class=None`).
T3. `n == 1` → index=0 без расхода партии и без записи в журнал.
T4. Scoped focus `chat → global → restricted(default)`: чатовый override
    выбирает источник ДО генерации, глобальное значение применяется при
    отсутствии override, недоступный чатовый слой (`source=error`) не читает
    чужие строки и падает на глобальный слой/дефолт.

Границы: без сети/провайдеров/записи в прод; только tmp SQLite, существующие
`DatabaseService`/`RandomStore`.
"""
from __future__ import annotations

import json
from collections import Counter

import pytest

from services import mca_events
from services import mca_random_source as mrs
from services.database import DatabaseService


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    """Не оставлять события в bounded-буфере mca-13 между тестами."""
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now


async def _fresh_db(tmp_path, name="vmq_q0_property.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


def _ok_uint8(values):
    """Валидный ответ ANU-контракта `uint8` с точным списком значений."""
    return (200, {},
            json.dumps({"success": True, "type": "uint8",
                        "length": len(values), "data": list(values)}))


def _anu_client(payload):
    """Детерминированный fake quantum-клиент поверх РЕАЛЬНОГО `AnuClient`."""
    calls: list = []

    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "params": dict(params),
                      "headers": dict(headers)})
        status, hdrs, text = payload
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           clock=FakeClock())
    return client, calls


async def _batch_from_fake_quantum(values):
    """Батч, полученный через реальный адаптер `AnuClient.fetch` (без сети)."""
    client, calls = _anu_client(_ok_uint8(values))
    batch = await client.fetch(key="vmq-q0-test-key", length=len(values),
                               data_type="uint8")
    return batch, calls


async def _insert_batch(store, values, *, provider=mrs.PROVIDER_ID_ANU,
                        data_type="uint8", created_at=None):
    return await store.insert_batch(
        mrs.AnuBatch(values=list(values), data_type=data_type,
                     length=len(values), provider=provider),
        created_at=created_at)


@pytest.fixture
def mem(monkeypatch):
    """Управляемый слой `memory.*`-настроек (chat → global → default)."""
    values: dict = {}

    async def fake(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_read_memory_setting", fake)
    return values


@pytest.fixture
def cfg(monkeypatch):
    """Управляемый глобальный слой `keys.random_quantum_*` / селектора."""
    values: dict = {}

    def fake(key, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_hot_setting", fake)
    return values


async def _row_provider(db, batch_id):
    cursor = await db.db.execute(
        "SELECT provider FROM mca_random_batches WHERE batch_id = ?",
        (batch_id,))
    row = await cursor.fetchone()
    assert row is not None
    return mrs.canonical_provider_id(row["provider"])


# ── T1: rejection sampling без modulo bias; отказы журналируются ────────────
@pytest.mark.asyncio
async def test_rejection_sampling_unbiased_on_8bit_range(tmp_path, mem, cfg):
    """256 значений, n=3: limit=(256//3)*3=255 → 85/85/85, 255 отвергнуто."""
    db = await _fresh_db(tmp_path, "vmq_q0_t1.db")
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False,
                                      clock=FakeClock())
        batch, calls = await _batch_from_fake_quantum(list(range(256)))
        assert calls and calls[0]["params"] == {"length": 256, "type": "uint8"}
        assert batch.values == list(range(256))
        await svc._store.insert_batch(batch)

        counts = [0, 0, 0]
        for _ in range(255):
            result = await svc.draw_index(3, chat_id=1, purpose="vmq_q0")
            assert result.source == mrs.MODE_QUANTUM
            assert result.provider_id == mrs.PROVIDER_ID_ANU
            assert result.index in (0, 1, 2)
            counts[result.index] += 1

        # 255 допустимых значений (0..254) дают ровно 85 на индекс.
        assert counts == [85, 85, 85]

        # Тот же фикстур под наивной формулой действительно смещён:
        # 0..255 % 3 → 86/85/85. Значит тест не тавтологичен.
        naive = Counter(value % 3 for value in range(256))
        assert [naive[0], naive[1], naive[2]] == [86, 85, 85]

        # 256-е значение (255) отвергнуто, остаток партии исчерпан.
        tail = await svc.draw_index(3, chat_id=1, purpose="vmq_q0")
        assert tail.index is None and tail.deferred is True
        assert await svc._store.reserve_remaining() == 0

        rows = [dict(row) for row in await (
            await db.db.execute(
                "SELECT draw_id, value, source, provider, batch_id, "
                "selected_id FROM mca_random_draws")).fetchall()]
        assert len(rows) == 256
        rejected = [row for row in rows if row["selected_id"] is None]
        selected = [row for row in rows if row["selected_id"] is not None]
        assert len(rejected) == 1
        assert rejected[0]["value"] == 255.0
        assert rejected[0]["source"] == mrs.MODE_QUANTUM
        assert rejected[0]["provider"] == mrs.PROVIDER_ID_ANU
        assert len(selected) == 255
        assert Counter(row["selected_id"] for row in selected) == {
            "0": 85, "1": 85, "2": 85}
        # Закон отображения: index = value % n для value < limit.
        for row in selected:
            assert int(row["selected_id"]) == int(row["value"]) % 3
    finally:
        await db.close()


# ── T2: один effective provider на draw, без смешивания источников ──────────
@pytest.mark.asyncio
async def test_one_effective_provider_per_draw_and_no_mixing(tmp_path, mem,
                                                            cfg):
    """ANU-запас расходуется только ANU; затем LfDR; PRNG — отдельная ось."""
    db = await _fresh_db(tmp_path, "vmq_q0_t2.db")
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False,
                                      clock=FakeClock())
        lfdr_batch = await _insert_batch(
            svc._store, [10, 11],
            provider=mrs.PROVIDER_ID_LFDR, created_at=1000)
        anu_batch = await _insert_batch(
            svc._store, [0, 1, 2, 3], created_at=2000)
        mem[mrs.SETTING_FALLBACK] = False

        selection = await svc.resolve_selection(chat_id=1)
        assert selection.mode == mrs.MODE_QUANTUM
        assert selection.effective_provider == mrs.PROVIDER_ID_ANU
        assert selection.effective_provider in mrs.PROVIDER_IDS
        assert selection.effective_order == (
            mrs.PROVIDER_ID_IBM, mrs.PROVIDER_ID_ANU, mrs.PROVIDER_ID_LFDR)

        quantum_rows = []
        for expected in [mrs.PROVIDER_ID_ANU] * 4 + [mrs.PROVIDER_ID_LFDR] * 2:
            result = await svc.draw_index(3, chat_id=1, purpose="vmq_q0")
            assert result.source == mrs.MODE_QUANTUM
            assert result.provider_id == expected
            assert result.entropy_class == mrs.ENTROPY_CLASS_HARDWARE
            assert result.source_impl == f"{expected}-quantum"
            assert result.index in (0, 1, 2)
            # Единственный источник draw подтверждается самой партией.
            assert await _row_provider(db, result.batch_id) == expected
            quantum_rows.append(result)

        # Партии не смешались: ANU израсходована ровно на 4, LfDR — на 2.
        cursor = await db.db.execute(
            "SELECT batch_id, provider, reserved_upto FROM "
            "mca_random_batches ORDER BY created_at")
        batches = [dict(row) for row in await cursor.fetchall()]
        by_id = {row["batch_id"]: row for row in batches}
        assert by_id[anu_batch]["reserved_upto"] == 4
        assert by_id[lfdr_batch]["reserved_upto"] == 2
        # ANU-партия не тронута, пока у ANU был запас.
        assert quantum_rows[0].batch_id == anu_batch
        assert quantum_rows[3].batch_id == anu_batch
        assert quantum_rows[4].batch_id == lfdr_batch

        # Оба квантовых запаса исчерпаны → честный PRNG-откат.
        mem[mrs.SETTING_FALLBACK] = True
        prng = await svc.draw_index(3, chat_id=1, purpose="vmq_q0")
        assert prng.source == mrs.MODE_PSEUDORANDOM
        assert prng.provider == mrs.PROVIDER_PRNG
        assert prng.provider_id is None
        assert prng.entropy_class is None
        assert prng.source_impl == mrs.SOURCE_IMPL_PRNG
        assert prng.batch_id is None
        assert prng.index in (0, 1, 2)

        rows = await svc.recent_draws(limit=50)
        assert len(rows) == 7
        for row in rows:
            if row["source"] == mrs.MODE_QUANTUM:
                assert mrs.canonical_provider_id(row["provider"]) in (
                    mrs.PROVIDER_ID_ANU, mrs.PROVIDER_ID_LFDR)
                assert row["provider"] != mrs.PROVIDER_PRNG
                assert row["batch_id"] is not None
            else:
                assert row["source"] == mrs.MODE_PSEUDORANDOM
                assert row["provider"] == mrs.PROVIDER_PRNG
                assert row["batch_id"] is None
        stats = await svc._store.journal_stats()
        assert stats[mrs.MODE_QUANTUM] == 6
        assert stats[mrs.MODE_PSEUDORANDOM] == 1
    finally:
        await db.close()


# ── T3: n == 1 — индекс 0 без расхода и без записи ──────────────────────────
@pytest.mark.asyncio
async def test_n_equals_one_costs_nothing_and_journals_nothing(tmp_path,
                                                               monkeypatch,
                                                               mem, cfg):
    db = await _fresh_db(tmp_path, "vmq_q0_t3.db")
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False,
                                      clock=FakeClock())
        await _insert_batch(svc._store, [0, 1, 2, 3])
        before = await svc._store.reserve_remaining()

        async def boom(*args, **kwargs):
            raise AssertionError("resolve_selection must not run for n=1")

        monkeypatch.setattr(svc, "resolve_selection", boom)
        result = await svc.draw_index(1, chat_id=9, purpose="vmq_q0")
        assert result.index == 0
        assert result.deferred is False
        assert await svc._store.reserve_remaining() == before
        assert await svc.recent_draws(limit=10) == []

        # Без БД — тот же контракт (никакого источника не требуется).
        bare = mrs.RandomSourceService(None, auto_refill=False)
        assert (await bare.draw_index(1, chat_id=9)).index == 0
    finally:
        await db.close()


# ── T4: scoped focus chat → global → restricted(default) ────────────────────
class _FakeChatCache:
    def __init__(self, roots: dict) -> None:
        self._roots = roots
        self.calls: list[int] = []

    async def get_chat_params_checked(self, chat_id):
        self.calls.append(int(chat_id))
        root = self._roots.get(int(chat_id))
        if root is False:          # чатовый слой недоступен
            return {}, False
        return dict(root or {}), True


@pytest.mark.asyncio
async def test_scoped_focus_chat_global_restricted(tmp_path, monkeypatch):
    """Override чата применяется ДО генерации; чужие строки не читаются."""
    from services import chat_params as cp
    from services import hot_config as hot
    from services import worker_settings as ws

    chat_a, chat_b, chat_c, chat_d = 101, 102, 103, 104
    global_values = {mrs.SETTING_SOURCE: "quantum"}

    def fake_hot(key, default=None):
        return global_values.get(key, default)

    monkeypatch.setattr(hot, "get", fake_hot)

    cache = _FakeChatCache({
        chat_a: {"overrides": {mrs.SETTING_SOURCE: "pseudorandom"}},
        chat_c: False,               # chat-слой «restricted»: недоступен
    })
    monkeypatch.setattr(cp, "get_chat_params_cache", lambda: cache)

    db = await _fresh_db(tmp_path, "vmq_q0_t4.db")
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False,
                                      clock=FakeClock())
        batch_id = await _insert_batch(svc._store, [0, 1, 2, 3])

        # (1) chat: явный override чата A побеждает глобальный quantum.
        cache.calls.clear()
        chat_draw = await svc.draw_index(3, chat_id=chat_a,
                                         purpose="vmq_q0")
        assert chat_draw.source == mrs.MODE_PSEUDORANDOM
        assert chat_draw.provider == mrs.PROVIDER_PRNG
        assert set(cache.calls) == {chat_a}
        cursor = await db.db.execute(
            "SELECT reserved_upto FROM mca_random_batches WHERE batch_id = ?",
            (batch_id,))
        assert int((await cursor.fetchone())["reserved_upto"]) == 0

        # (2) global: у чата B override нет → действует глобальный quantum.
        cache.calls.clear()
        global_draw = await svc.draw_index(3, chat_id=chat_b,
                                           purpose="vmq_q0")
        assert global_draw.source == mrs.MODE_QUANTUM
        assert global_draw.provider_id == mrs.PROVIDER_ID_ANU
        assert set(cache.calls) == {chat_b}
        assert chat_a not in cache.calls

        # (3) restricted: чатовый слой C недоступен → глобальный слой,
        #     source честно 'error', читается только C.
        cache.calls.clear()
        restricted = await svc.draw_index(3, chat_id=chat_c,
                                          purpose="vmq_q0")
        assert restricted.source == mrs.MODE_QUANTUM
        assert restricted.provider_id == mrs.PROVIDER_ID_ANU
        assert set(cache.calls) == {chat_c}

        # Источники слоёв различимы (без I/O-подмены значения).
        assert (await ws.resolve_setting_with_source(
            mrs.SETTING_SOURCE, chat_id=chat_a))[1] == "chat"
        assert (await ws.resolve_setting_with_source(
            mrs.SETTING_SOURCE, chat_id=chat_b))[1] == "global"
        assert (await ws.resolve_setting_with_source(
            mrs.SETTING_SOURCE, chat_id=chat_c))[1] == "error"

        # (4) default: ни chat-override, ни глобального значения нет →
        #     заводской DEFAULT_SOURCE; чужие строки не читаются.
        global_values.clear()
        cache.calls.clear()
        default_draw = await svc.draw_index(3, chat_id=chat_d,
                                            purpose="vmq_q0")
        assert (await ws.resolve_setting_with_source(
            mrs.SETTING_SOURCE, chat_id=chat_d))[1] == "default"
        assert mrs.DEFAULT_SOURCE == mrs.MODE_QUANTUM
        assert default_draw.source == mrs.MODE_QUANTUM
        assert default_draw.provider_id == mrs.PROVIDER_ID_ANU
        assert set(cache.calls) == {chat_d}
    finally:
        await db.close()
