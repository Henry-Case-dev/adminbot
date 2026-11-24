"""QRNG P5 — IBM Quantum Platform adapter (QAN-REC-IBM-01…03).

Проверяется фактический контракт, без сети и без реального IBM:
  * провайдер `ibm_quantum_platform` + auto-QPU из backend'ов instance;
  * read-only «Проверить доступ» (key/CRN/instance/region/backends/queue/
    usage) НЕ создаёт Sampler и не отправляет job;
  * отдельный hardware smoke получает настоящие measurement bitstrings;
  * из сырых битов — детерминированный von Neumann debias, физическое
    смещение измеряется и попадает в provenance;
  * provenance: job/backend/shots/bit count/usage, `is_simulator=false`;
  * simulator/quasi_dists/фиктивные counts отвергаются;
  * durable lifecycle в существующих `task_jobs`, повторный submit при
    активном job запрещён, рестарт = poll/attach по job ID;
  * дневные лимиты и fallback ANU/LfDR; секреты не утекают.
"""
import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from services import mca_random_source as mrs
from services.database import DatabaseService
from services.task_supervisor import (TaskJobStore, TaskSupervisor,
                                      reset_task_supervisor)



# ── фейковые qiskit-объекты (никакой сети) ─────────────────────────────────
class FakeBackend:
    def __init__(self, name="ibm_hw_1", qubits=16, simulator=False,
                 operational=True, pending=0):
        self.name = name
        self.num_qubits = qubits
        self._simulator = simulator
        self._operational = operational
        self._pending = pending

    def status(self):
        return SimpleNamespace(operational=self._operational,
                               pending_jobs=self._pending)

    def configuration(self):
        return SimpleNamespace(simulator=self._simulator,
                               n_qubits=self.num_qubits)


class FakeMeasure:
    def __init__(self, bitstrings):
        self._bitstrings = list(bitstrings)

    def get_bitstrings(self):
        return list(self._bitstrings)


class FakeResult:
    def __init__(self, bitstrings=None, *, data=None):
        if data is None:
            data = SimpleNamespace(meas=FakeMeasure(bitstrings or []))
        self._pub = SimpleNamespace(data=data)

    def __getitem__(self, index):
        if index != 0:
            raise IndexError(index)
        return self._pub


class FakeJob:
    def __init__(self, *, job_id="ibm-job-1", states=("DONE",),
                 bitstrings=None, backend=None, usage=1.25,
                 result=None, status_error=None, result_errors=None):
        self._job_id = job_id
        self._states = list(states)
        self._bitstrings = bitstrings or []
        self._backend = backend or FakeBackend()
        self._usage = usage
        self._result = result
        self._status_error = status_error
        self._result_errors = list(result_errors or [])

    def job_id(self):
        return self._job_id

    def status(self):
        if self._status_error:
            raise self._status_error
        if len(self._states) > 1:
            return self._states.pop(0)
        return self._states[0]

    def result(self):
        if self._result_errors:
            raise self._result_errors.pop(0)
        if self._result is not None:
            return self._result
        return FakeResult(self._bitstrings)

    def backend(self):
        return self._backend

    def usage(self):
        return self._usage


class FakeSampler:
    def __init__(self, job):
        self.job = job
        self.calls = []

    def run(self, circuits, shots):
        self.calls.append({"circuits": circuits, "shots": shots})
        return self.job


class FakeService:
    def __init__(self, backends=None, *, instances=None, usage=None,
                 jobs=None, error=None, listed_jobs=None):
        self._backends = list(backends or [])
        self._instances = list(instances or [])
        self._usage = usage
        self._jobs = dict(jobs or {})
        self._listed_jobs = list(listed_jobs or [])
        self.error = error
        self.backend_calls = 0
        self.instance_calls = 0
        self.usage_calls = 0
        self.job_calls = 0

    def backends(self, instance=None):
        self.backend_calls += 1
        if self.error is not None:
            raise self.error
        return list(self._backends)

    def instances(self):
        self.instance_calls += 1
        return list(self._instances)

    def usage(self):
        self.usage_calls += 1
        return self._usage

    def job(self, job_id):
        self.job_calls += 1
        if job_id not in self._jobs:
            raise LookupError(job_id)
        return self._jobs[job_id]

    def jobs(self, **kwargs):
        return list(self._listed_jobs)


def make_bitstrings(shots=256):
    # Разные соседние shots нужны для cross-shot von Neumann debias.
    return [("0110" * 4 if index % 2 == 0 else "1010" * 4)
            for index in range(shots)]


def make_client(service, job, *, poll_interval=0.0, job_max_age=60.0,
                sleeper=None):
    async def _sleep(_seconds):
        return None

    sampler = FakeSampler(job)
    client = mrs.IbmQuantumRuntimeClient(
        service_factory=lambda **kwargs: service,
        sampler_factory=lambda **kwargs: sampler,
        circuit_factory=lambda num_qubits: SimpleNamespace(
            num_qubits=num_qubits),
        transpiler=lambda circuit, backend: circuit,
        poll_interval=poll_interval, job_max_age=job_max_age,
        sleeper=sleeper or _sleep)
    return client, sampler


def cfg(monkeypatch, values):
    def fake(key, default):
        return values.get(key, default)
    monkeypatch.setattr(mrs, "_hot_setting", fake)
    return values


@pytest.fixture(autouse=True)
def _reset_supervisor():
    reset_task_supervisor()
    yield
    reset_task_supervisor()


async def _fresh_db(tmp_path, name="qrng_p5.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _insert_task_row(db, *, kind=mrs.IBM_JOB_KIND, status="running",
                           cursor=None, coalesce="random.ibm.active.0",
                           created_at=None, result_ref=None,
                           reason_code=None, stale=False,
                           heartbeat_at=None, deadline_at=None):
    store = TaskJobStore(db)
    job_id = await store.enqueue(
        owner=mrs.IBM_JOB_OWNER, kind=kind, coalesce_key=coalesce,
        payload=json.dumps({"probe": True}), max_attempts=1,
        deadline_at=deadline_at)
    await store.mark_running(job_id)
    if cursor is not None:
        await store.save_checkpoint(
            job_id, cursor_token=json.dumps(cursor), processed=0)
    if status != "running":
        await store.finish(job_id, status=status, result_ref=result_ref,
                           reason_code=reason_code, recovery=True)
    if stale:
        hb = (int(heartbeat_at) if heartbeat_at is not None
              else int(time.time()) - 3600)

        async def _body(conn):
            await conn.execute(
                "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
                (hb, job_id))
            return True

        await db.write_transaction(_body, op_name="test_stale_heartbeat")
    if created_at is not None:

        async def _created(conn):
            await conn.execute(
                "UPDATE task_jobs SET created_at = ? WHERE job_id = ?",
                (int(created_at), job_id))
            return True

        await db.write_transaction(_created, op_name="test_created_at")
    return job_id, store


# ── реестр/настройки/секреты ───────────────────────────────────────────────
class TestRegistryAndConfig:
    def test_ibm_registered_with_real_hooks(self):
        spec = mrs.PROVIDERS[mrs.PROVIDER_ID_IBM]
        assert spec.id == "ibm_quantum"
        assert spec.entropy_class == mrs.ENTROPY_CLASS_HARDWARE
        assert spec.requires_key is True
        assert spec.key_setting == mrs.SETTING_IBM_KEY
        assert spec.fetch is mrs.ibm_fetch
        assert spec.check is mrs.ibm_check
        assert mrs.IBM_CHANNEL == "ibm_quantum_platform"
        assert mrs.IBM_INSTANCE_DEFAULT == "open-instance"
        assert mrs.IBM_REGION_DEFAULT == "us-east"

    def test_settings_and_catalog_fields(self):
        from config.settings import Settings
        from services import param_catalog as pc
        s = Settings()
        assert s.RANDOM_IBM_API_KEY == ""
        assert s.RANDOM_IBM_CRN == ""
        assert s.RANDOM_IBM_INSTANCE == "open-instance"
        assert s.RANDOM_IBM_REGION == "us-east"
        assert s.RANDOM_IBM_CHANNEL == "ibm_quantum_platform"
        for key in ("keys.random_ibm_api_key", "keys.random_ibm_crn"):
            spec = pc.get_by_pg_key(key)
            assert spec is not None and spec.secret is True
            assert spec.per_chat is False
        for key in ("keys.random_ibm_instance", "keys.random_ibm_region",
                    "keys.random_ibm_channel"):
            spec = pc.get_by_pg_key(key)
            assert spec is not None and spec.secret is False
            assert spec.per_chat is False
        for key in ("random.ibm.http_timeout_seconds",
                    "random.ibm.poll_interval_seconds",
                    "random.ibm.job_max_age_seconds",
                    "random.ibm.max_inflight",
                    "random.ibm.max_jobs_per_day",
                    "random.ibm.max_qpu_seconds_per_day"):
            spec = pc.get_by_pg_key(key)
            assert spec is not None and spec.global_only is True
            assert spec.group == "memory_random"

    def test_credentials_registered_for_redaction(self):
        from services import output_projection as projection
        fields = {f.settings_field for f in projection.CREDENTIAL_FIELDS}
        assert {"RANDOM_IBM_API_KEY", "RANDOM_IBM_CRN"} <= fields

    def test_default_service_uses_official_platform_channel(self,
                                                           monkeypatch):
        captured = {}

        class FakeRuntimeService:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import sys
        monkeypatch.setitem(
            sys.modules, "qiskit_ibm_runtime",
            SimpleNamespace(QiskitRuntimeService=FakeRuntimeService))
        service = mrs._default_qiskit_service(
            api_key="key", crn="crn:full", instance="open-instance",
            region="us-east", channel="ibm_quantum_platform")
        assert isinstance(service, FakeRuntimeService)
        assert captured == {
            "channel": "ibm_quantum_platform", "token": "key",
            "instance": "crn:full", "region": "us-east"}

    @pytest.mark.asyncio
    async def test_no_key_is_unconfigured_without_network(self, monkeypatch):
        async def boom(**kwargs):
            raise AssertionError("network must not be touched")

        service = mrs.RandomSourceService(None, auto_refill=False)
        result = await service.test_connection(provider=mrs.PROVIDER_ID_IBM)
        assert result["healthy"] is False
        assert result["blocker"] == "provider_unconfigured"
        assert result["stage"] == "key"
        assert result["deposited"] is False
        monkeypatch.setattr(mrs, "_default_qiskit_service", boom)


# ── read-only vs hardware smoke ────────────────────────────────────────────
class TestReadOnlyAndSmoke:
    @pytest.mark.asyncio
    async def test_check_access_is_read_only_and_selects_hardware(self):
        busy = FakeBackend("ibm_busy", pending=9)
        idle = FakeBackend("ibm_idle", pending=1)
        sim = FakeBackend("ibm_sim", simulator=True)
        service = FakeService([sim, busy, idle],
                              instances=[{"name": "open-instance",
                                          "plan": "Open"}],
                              usage={"usage": 12.0, "limit": 600})
        job = FakeJob(bitstrings=make_bitstrings())
        client, sampler = make_client(service, job)
        result = await client.check_access(
            api_key="key", crn="", instance="open-instance",
            region="us-east", channel="ibm_quantum_platform")
        assert result["healthy"] is True
        assert result["stage"] is None
        assert result["selected_backend"] == "ibm_idle"
        assert result["plan"] == "Open"
        assert result["is_simulator"] is False
        assert any(b["simulator"] is True for b in result["backends"])
        assert sampler.calls == []           # Sampler не создавался
        assert service.job_calls == 0

    @pytest.mark.asyncio
    async def test_check_access_reports_stage(self):
        client, sampler = make_client(FakeService(), FakeJob())
        bad_channel = await client.check_access(
            api_key="k", channel="ibm_cloud")
        assert bad_channel["blocker"] == "invalid_channel"
        assert bad_channel["stage"] == "channel"
        bad_region = await client.check_access(
            api_key="k", region="bad region!")
        assert bad_region["blocker"] == "invalid_region"
        assert bad_region["stage"] == "region"
        only_sim = await make_client(
            FakeService([FakeBackend("sim", simulator=True)]),
            FakeJob())[0].check_access(api_key="k")
        assert only_sim["blocker"] == "no_backend"
        assert only_sim["stage"] == "no_backend"
        wrong_region = await client.check_access(
            api_key="k",
            crn="crn:v1:bluemix:public:quantum-compute:eu-de:a/x:y::",
            region="us-east")
        assert wrong_region["blocker"] == "invalid_region"
        assert wrong_region["stage"] == "region"
        assert sampler.calls == []

    @pytest.mark.asyncio
    async def test_dependency_missing_is_honest(self, monkeypatch):
        monkeypatch.setattr(mrs, "_qiskit_runtime_available", lambda: False)
        client = mrs.IbmQuantumRuntimeClient()
        result = await client.check_access(api_key="key")
        assert result["healthy"] is False
        assert result["blocker"] == "dependency_missing"
        assert result["stage"] == "dependency"

    @pytest.mark.asyncio
    async def test_blocking_sdk_call_does_not_stall_event_loop(self):
        class SlowService(FakeService):
            def backends(self, instance=None):
                time.sleep(0.35)
                return super().backends(instance=instance)

        service = SlowService([FakeBackend("ibm_hw")])
        job = FakeJob(bitstrings=make_bitstrings())
        client, _sampler = make_client(service, job)
        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0.02)

        task = asyncio.create_task(ticker())
        try:
            batch = await client.fetch(api_key="key", length=1)
            assert batch.length > 0
        finally:
            stop = True
            await task
        # 0.35 c блокирующего SDK при тике 20 мс: event loop обязан жить.
        assert ticks >= 8

    @pytest.mark.asyncio
    async def test_usage_real_0_52_schema_visible(self, monkeypatch):
        cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                          mrs.SETTING_IBM_INSTANCE: "open-instance"})
        service = FakeService(
            [FakeBackend("ibm_hw")],
            instances=[{"name": "open-instance", "plan": "Open"}],
            usage={"usage_limit_seconds": 600,
                   "usage_consumed_seconds": 12,
                   "usage_remaining_seconds": 588,
                   "usage_limit_ru": 600,
                   "usage_consumed_ru": 10,
                   "usage_remaining_ru": 590,
                   "usage_limit_reached": False})
        client, _sampler = make_client(service, FakeJob())
        result = await client.check_access(api_key="key")
        assert result["healthy"] is True
        assert result["usage"]["usage_remaining_ru"] == 590
        assert result["usage"]["usage_remaining_seconds"] == 588
        assert result["usage"]["usage_limit_reached"] is False
        svc = mrs.RandomSourceService(None, auto_refill=False)
        svc.set_ibm_client(client)
        await svc.ibm_check_access()
        assert svc._ibm_health["usage"]["usage_remaining_ru"] == 590
        # P5A-R2-N01: частичный usage после refill/smoke не стирает RU.
        svc._note_ibm_success(usage={"usage_seconds": 1.0})
        assert svc._ibm_health["usage"]["usage_remaining_ru"] == 590
        assert svc._ibm_health["usage"]["usage_seconds"] == 1.0

    @pytest.mark.asyncio
    async def test_service_smoke_does_not_deposit(self, tmp_path,
                                                  monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            client, sampler = make_client(
                FakeService([backend]), FakeJob(bitstrings=make_bitstrings(),
                                                backend=backend))
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            result = await svc.ibm_hardware_smoke(shots=256)
            assert result["healthy"] is True
            assert result["deposited"] is False
            assert len(sampler.calls) == 1
            assert await _batch_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_smoke_uses_durable_job_and_no_batch(self, tmp_path,
                                                       monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 1})
            backend = FakeBackend("ibm_hw")
            client, sampler = make_client(
                FakeService([backend]),
                FakeJob(job_id="SMOKE1", bitstrings=make_bitstrings(),
                        backend=backend, usage=0.5))
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            result = await svc.ibm_hardware_smoke(shots=256)
            assert result["healthy"] is True
            assert result["job_id"] == "SMOKE1"
            assert result["deposited"] is False
            assert len(sampler.calls) == 1
            rows = await _task_rows(db)
            assert len(rows) == 1
            assert rows[0]["status"] == "completed"
            assert mrs.RandomSourceService._ibm_cursor(rows[0])[
                "purpose"] == "smoke"
            assert await _batch_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_smoke_daily_cap_blocks_paid_job(self, tmp_path,
                                                   monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 0})
            client, sampler = make_client(
                FakeService([FakeBackend("ibm_hw")]), FakeJob())
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            result = await svc.ibm_hardware_smoke()
            assert result["healthy"] is False
            assert result["blocker"] == "daily_job_limit"
            assert result["deposited"] is False
            assert sampler.calls == []
            assert await _task_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_smoke_singleflight_and_cooldown(self, tmp_path,
                                                   monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="SMOKE2",
                          bitstrings=make_bitstrings(), backend=backend)
            client, sampler = make_client(
                FakeService([backend]), job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            first, second = await asyncio.gather(
                svc.ibm_hardware_smoke(), svc.ibm_hardware_smoke())
            assert first["healthy"] is True
            assert second["healthy"] is True
            assert len(sampler.calls) == 1
            third = await svc.ibm_hardware_smoke()
            assert third["cooldown"] is True
            assert len(sampler.calls) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_auth_failure_names_permission_stage(self):
        exc = RuntimeError("401 unauthorized")
        exc.status_code = 401
        service = FakeService(error=exc)
        client, sampler = make_client(service, FakeJob())
        result = await client.check_access(api_key="key")
        assert result["healthy"] is False
        assert result["blocker"] == "auth_failed"
        assert result["stage"] == "permission"
        assert sampler.calls == []

    @pytest.mark.asyncio
    async def test_hardware_smoke_gets_real_bits_without_deposit(self):
        backend = FakeBackend("ibm_hw")
        service = FakeService([backend],
                              instances=[{"name": "open-instance",
                                          "plan": "Open"}])
        job = FakeJob(job_id="smoke-1", bitstrings=make_bitstrings(),
                      backend=backend, usage=0.75)
        client, sampler = make_client(service, job)
        result = await client.hardware_smoke(
            api_key="key", instance="open-instance", shots=256)
        assert result["healthy"] is True
        assert result["job_id"] == "smoke-1"
        assert result["backend"] == "ibm_hw"
        assert result["shots"] == 256
        assert result["bits"] and result["bits"] > 0
        assert result["usage_seconds"] == 0.75
        assert result["is_simulator"] is False
        assert len(sampler.calls) == 1
        assert sampler.calls[0]["shots"] == 256


# ── извлечение/валидация/PRNG ──────────────────────────────────────────────
class TestExtraction:
    @pytest.mark.asyncio
    async def test_debias_and_provenance(self):
        backend = FakeBackend("ibm_hw")
        service = FakeService([backend],
                              instances=[{"name": "open-instance",
                                          "plan": "Open"}])
        # 75% единиц в сырых битах, но пары 01/10 сбалансированы:
        # физическое смещение не превращается в смещение значений.
        bitstrings = ["0111" * 4 if i % 2 == 0 else "1011" * 4
                      for i in range(256)]
        job = FakeJob(job_id="bits-1", bitstrings=bitstrings,
                      backend=backend, usage=2.5)
        client, _sampler = make_client(service, job)
        batch = await client.fetch(
            api_key="key", crn="", instance="open-instance", length=8)
        prov = batch.provenance
        assert batch.provider == mrs.PROVIDER_ID_IBM
        assert batch.data_type == "uint16"
        assert batch.length == len(batch.values) == 8
        assert prov["job_id"] == "bits-1"
        assert prov["backend"] == "ibm_hw"
        assert prov["shots"] == 256
        assert prov["num_qubits"] == 16
        assert prov["raw_bits"] == 256 * 16
        assert prov["bias"] == pytest.approx(0.75)
        assert prov["accepted_bits"] > 0
        assert prov["usage_seconds"] == 2.5
        assert prov["usage_source"] == "job.usage"
        assert prov["is_simulator"] is False
        assert prov["instance"] == "open-instance"
        assert prov["channel"] == "ibm_quantum_platform"

    def test_debias_removes_constant_physical_bias(self):
        # 75% единиц, но пары 01/10 сбалансированы: von Neumann даёт
        # одинаковое число нулей и единиц (нулевое смещение).
        raw = ["0111" * 4, "1011" * 4] * 128
        bits, stats = mrs._ibm_debias_bitstrings(raw)
        assert stats["bias"] == pytest.approx(0.75)
        assert stats["unbiased_bits"] == 1024
        assert abs(bits.count(0) - bits.count(1)) <= 1

    @pytest.mark.asyncio
    async def test_no_prng_in_tract(self, monkeypatch):
        class Boom:
            def __init__(self, *args, **kwargs):
                raise AssertionError("PRNG must not be used")

        monkeypatch.setattr(mrs.random, "Random", Boom)
        service = FakeService([FakeBackend("ibm_hw")])
        job = FakeJob(bitstrings=make_bitstrings())
        client, _sampler = make_client(service, job)
        batch = await client.fetch(api_key="key", length=2)
        assert batch.length > 0

    @pytest.mark.asyncio
    async def test_simulator_backend_rejected(self):
        backend = FakeBackend("sim", simulator=True)
        # В instance есть и аппаратный backend (для auto-QPU), но результат
        # пришёл с simulator backend — такой job не засчитывается.
        service = FakeService([FakeBackend("ibm_hw"), backend])
        job = FakeJob(bitstrings=make_bitstrings(), backend=backend)
        client, _sampler = make_client(service, job)
        with pytest.raises(mrs.IbmError) as exc:
            await client.fetch(api_key="key", length=2)
        assert exc.value.code == "validation_failed"
        assert exc.value.stage == "backend"

    @pytest.mark.asyncio
    async def test_quasi_dists_and_bad_shape_rejected(self):
        service = FakeService([FakeBackend("ibm_hw")])
        bad = FakeResult(data=SimpleNamespace(
            quasi_dists=[{"0": 1024}]))
        job = FakeJob(result=bad)
        client, _sampler = make_client(service, job)
        with pytest.raises(mrs.IbmError) as exc:
            await client.fetch(api_key="key", length=1)
        assert exc.value.code == "validation_failed"

        short = FakeJob(bitstrings=["01"] * 256)
        client2, _sampler2 = make_client(service, short)
        with pytest.raises(mrs.IbmError) as exc2:
            await client2.fetch(api_key="key", length=1)
        assert exc2.value.code == "validation_failed"

        wrong_shots = FakeJob(bitstrings=make_bitstrings(255))
        client4, _sampler4 = make_client(service, wrong_shots)
        with pytest.raises(mrs.IbmError) as exc4:
            await client4.fetch(api_key="key", length=1)
        assert exc4.value.code == "validation_failed"
        assert "shot" in exc4.value.reason.lower()

        nonbinary = FakeJob(bitstrings=["01x" + "0" * 13] * 256)
        client3, _sampler3 = make_client(service, nonbinary)
        with pytest.raises(mrs.IbmError):
            await client3.fetch(api_key="key", length=1)


# ── durable lifecycle/идемпотентность/рестарт ──────────────────────────────
class TestDurableLifecycle:
    @pytest.mark.asyncio
    async def test_pending_to_completed_and_deposit_once(self, tmp_path,
                                                         monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            backend = FakeBackend("ibm_hw")
            service = FakeService(
                [backend], instances=[{"name": "open-instance",
                                       "plan": "Open"}])
            job = FakeJob(job_id="J1", states=("QUEUED", "RUNNING", "DONE"),
                          bitstrings=make_bitstrings(), backend=backend,
                          usage=1.5)
            client, sampler = make_client(service, job)
            store = TaskJobStore(db)
            random_store = mrs.RandomStore(db)
            inserted = []

            async def deposit(batch):
                inserted.append(batch)
                return await random_store.insert_batch(
                    batch, config_fingerprint="fp",
                    external_ref=mrs._ibm_external_ref(batch.provenance))

            supervisor = TaskSupervisor(max_concurrent=2)
            batch = await client.fetch(
                api_key="key", crn="", instance="open-instance",
                length=8, job_store=store, supervisor=supervisor,
                deposit=deposit, account_key="ibm:open-instance",
                config_fp="fp")
            assert batch.length == 8
            assert len(inserted) == 1
            assert len(sampler.calls) == 1
            rows = await _task_rows(db)
            assert len(rows) == 1
            row = rows[0]
            assert row["status"] == "completed"
            cursor = mrs.RandomSourceService._ibm_cursor(row)
            assert cursor["job"] == "J1"
            assert cursor["state"] == "completed"
            ref = json.loads(row["result_ref"])
            assert ref["job"] == "J1"
            assert ref["batch"] == inserted[0].provenance["batch_id"]
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_active_job_blocks_second_submit(self, tmp_path,
                                                   monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            service = FakeService([FakeBackend("ibm_hw")])
            job = FakeJob(bitstrings=make_bitstrings())
            client, sampler = make_client(service, job)
            store = TaskJobStore(db)
            await _insert_task_row(
                db, status="running",
                cursor={"job": "existing", "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()),
                        "values": 8, "config_fp": "fp"})
            with pytest.raises(mrs.IbmError) as exc:
                await client.fetch(
                    api_key="key", instance="open-instance", length=8,
                    job_store=store, supervisor=TaskSupervisor(),
                    account_key="ibm:open-instance", config_fp="fp")
            assert exc.value.code == "job_in_progress"
            assert sampler.calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_restart_recovery_polls_not_resubmits(self, tmp_path,
                                                        monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_CRN: "crn:full:value",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_REGION: "us-east",
                              mrs.SETTING_IBM_CHANNEL: "ibm_quantum_platform"})
            backend = FakeBackend("ibm_hw")
            existing = FakeJob(job_id="J9", states=("RUNNING", "DONE"),
                               bitstrings=make_bitstrings(), backend=backend,
                               usage=2.0)
            service = FakeService([backend], jobs={"J9": existing})
            client, sampler = make_client(service, existing)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="running", stale=True,
                cursor={"job": "J9", "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 5,
                        "values": 8, "plan": "Open", "config_fp": ""})
            started = await svc._recover_ibm_jobs()
            assert started == 1
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []          # никакого resubmit
            assert service.job_calls == 1       # attach по job ID
            rows = await _task_rows(db)
            assert rows[0]["status"] == "completed"
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_expired_row_recovers_late_done_result_once(self, tmp_path,
                                                              monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            existing = FakeJob(job_id="LATE1", states=("DONE",),
                               bitstrings=make_bitstrings(), backend=backend,
                               usage=1.0)
            service = FakeService([backend], jobs={"LATE1": existing})
            client, sampler = make_client(service, existing)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "LATE1", "state": "expired",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 10,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            started = await svc._recover_ibm_jobs()
            assert started == 1
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []       # никакого повторного submit
            rows = await _task_rows(db)
            assert rows[0]["status"] == "completed"
            batches = await _batch_rows(db)
            assert len(batches) == 1
            # Повторный recovery не создаёт второй batch.
            await svc._recover_ibm_jobs()
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_live_timeout_then_done_recovers_once(self, tmp_path,
                                                        monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="LIVE1", states=("RUNNING",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"LIVE1": job})
            client, sampler = make_client(service, job)
            client._job_max_age = 0.2
            store = TaskJobStore(db)
            inserted = []

            async def deposit(batch):
                inserted.append(batch)
                return await mrs.RandomStore(db).insert_batch(
                    batch, config_fingerprint="fp",
                    external_ref=mrs._ibm_external_ref(batch.provenance))

            with pytest.raises(mrs.IbmError) as exc:
                await client.fetch(
                    api_key="key", instance="open-instance", length=1,
                    job_store=store, supervisor=TaskSupervisor(),
                    deposit=deposit, account_key="ibm:open-instance",
                    config_fp="fp")
            assert exc.value.code == "timeout"
            rows = await _task_rows(db)
            assert rows[0]["status"] == "failed"
            assert mrs.RandomSourceService._ibm_cursor(rows[0])[
                "state"] == mrs.IBM_JOB_EXPIRED
            # Поздний IBM DONE: recovery зачисляет ровно один batch.
            job._states = ["DONE"]
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert len(await _batch_rows(db)) == 1
            assert len(sampler.calls) == 1     # только исходный submit
            assert (await _task_rows(db))[0]["status"] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_atomic_claim_two_fetches_one_sampler(self, tmp_path):
        db = await _fresh_db(tmp_path)
        try:
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="ATOMIC1", states=("RUNNING",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"ATOMIC1": job})
            client, sampler = make_client(
                service, job, poll_interval=0.01, job_max_age=5.0,
                sleeper=asyncio.sleep)
            store = TaskJobStore(db)
            inserted = []

            async def deposit(batch):
                inserted.append(batch)
                return await mrs.RandomStore(db).insert_batch(
                    batch, config_fingerprint="fp",
                    external_ref=mrs._ibm_external_ref(batch.provenance))

            async def fetch(account):
                return await client.fetch(
                    api_key="key", instance="open-instance", length=1,
                    job_store=store, supervisor=TaskSupervisor(),
                    deposit=deposit, account_key=account,
                    config_fp=f"fp-{account}")

            first = asyncio.create_task(fetch("a"))
            while not sampler.calls:
                await asyncio.sleep(0)
            second = asyncio.create_task(fetch("b"))
            await asyncio.sleep(0.02)
            job._states = ["DONE"]
            results = await asyncio.gather(first, second,
                                          return_exceptions=True)
            assert len(sampler.calls) == 1
            assert sum(isinstance(r, mrs.AnuBatch) for r in results) == 1
            errors = [r for r in results if isinstance(r, mrs.IbmError)]
            assert len(errors) == 1 and errors[0].code == "job_in_progress"
            rows = await _task_rows(db)
            assert len(rows) == 1 and rows[0]["status"] == "completed"
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_concurrent_refill_and_smoke_one_sampler(self, tmp_path,
                                                           monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_BATCH_LENGTH: 8,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="MIX1", states=("RUNNING",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"MIX1": job})
            client, sampler = make_client(
                service, job, poll_interval=0.01, job_max_age=5.0,
                sleeper=asyncio.sleep)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            refill = asyncio.create_task(svc.refill_if_needed(force=True))
            smoke = asyncio.create_task(svc.ibm_hardware_smoke())
            while not sampler.calls:
                await asyncio.sleep(0)
            await asyncio.sleep(0.02)
            job._states = ["DONE"]
            await asyncio.gather(refill, smoke, return_exceptions=True)
            assert len(sampler.calls) == 1
            assert len(await _task_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_terminal_completed_cursor_deposits_once(self, tmp_path,
                                                           monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_BATCH_LENGTH: 8})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="TERM1", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"TERM1": job})
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            # Crash после checkpoint completed, до deposit/finish: row running,
            # heartbeat потерян (процесс-владелец умер).
            await _insert_task_row(
                db, status="running", stale=True,
                cursor={"job": "TERM1", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
            # Повторный recovery не создаёт второй batch и не опрашивает job.
            await svc._recover_ibm_jobs()
            assert len(await _batch_rows(db)) == 1
            assert sampler.calls == []
            # Слот освобождён: следующий refill может оплатить новый job.
            new_job = FakeJob(job_id="TERM1NEXT", states=("DONE",),
                              bitstrings=make_bitstrings(), backend=backend)
            service._jobs["TERM1NEXT"] = new_job
            sampler.job = new_job
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "completed"
            assert len(sampler.calls) == 1
            assert len(await _batch_rows(db)) == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_failed_row_terminal_completed_cursor_deposits(self,
                                                                 tmp_path,
                                                                 monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="TERM2", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"TERM2": job})
            client, _sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="task_failed",
                cursor={"job": "TERM2", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_terminal_completed_with_batch_releases_without_duplicate(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            store = mrs.RandomStore(db)
            await store.insert_batch(
                mrs.AnuBatch(values=[1, 2, 3], data_type="uint16",
                             length=3, provider=mrs.PROVIDER_ID_IBM),
                config_fingerprint="", external_ref='{"job":"TERM3"}')
            client, sampler = make_client(
                FakeService([FakeBackend("ibm_hw")]), FakeJob())
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="running", stale=True,
                cursor={"job": "TERM3", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
            assert sampler.calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_tag_lookup_transient_keeps_unresolved(self, tmp_path,
                                                         monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_BATCH_LENGTH: 8,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="TAGX", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"TAGX": job})
            service.jobs = lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("tag lookup network"))
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="submit_uncertain",
                cursor={"state": "pending", "job_tag": "qrng-p5-X",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "blocked"
            assert result["reason"] == "job_in_progress"
            assert sampler.calls == []
            row = (await _task_rows(db))[0]
            assert row["status"] == "interrupted"
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "state"] == "pending"
            assert await _batch_rows(db) == []
            # Transient прошёл: tag резолвится, job attach/deposit без submit.
            del service.jobs
            service._listed_jobs = [job]
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_batch_lookup_unknown_is_unresolved_not_completed(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="DUNNO", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"DUNNO": job})
            client, _sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="running", stale=True,
                cursor={"job": "DUNNO", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            original = svc._ibm_batch_exists

            async def unknown(_job_id):
                return mrs.IBM_BATCH_UNKNOWN

            monkeypatch.setattr(svc, "_ibm_batch_exists", unknown)
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            row = (await _task_rows(db))[0]
            assert row["status"] == "interrupted"
            assert await _batch_rows(db) == []
            # DB снова доступна: batch absent → deposit/release.
            monkeypatch.setattr(svc, "_ibm_batch_exists", original)
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_result_timeout_keeps_slot_and_recovers_later(self,
                                                                tmp_path,
                                                                monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_BATCH_LENGTH: 8,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="RETRY1", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend,
                          result_errors=[TimeoutError(), TimeoutError()])
            service = FakeService([backend], jobs={"RETRY1": job})
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "RETRY1", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            # Result read timeout: row/cursor остаются unresolved, не terminal.
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            rows = await _task_rows(db)
            assert rows[0]["status"] == "interrupted"
            assert mrs.RandomSourceService._ibm_cursor(rows[0])[
                "state"] == mrs.IBM_JOB_COMPLETED
            assert await _batch_rows(db) == []
            # Refill видит fence и не делает новый sampler.run.
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "blocked"
            assert result["reason"] == "job_in_progress"
            assert sampler.calls == []
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            # Следующий recovery получает result и зачисляет ровно один batch.
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
            assert sampler.calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_terminal_ibm_failure_releases_slot(self, tmp_path,
                                                       monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_BATCH_LENGTH: 8,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            failed_job = FakeJob(job_id="FAIL1", states=("ERROR",),
                                 bitstrings=make_bitstrings(),
                                 backend=backend)
            next_job = FakeJob(job_id="FAILNEXT", states=("DONE",),
                               bitstrings=make_bitstrings(), backend=backend)
            service = FakeService(
                [backend], jobs={"FAIL1": failed_job,
                                 "FAILNEXT": next_job})
            client, sampler = make_client(service, failed_job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "FAIL1", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "state"] == mrs.IBM_JOB_FAILED
            assert await _batch_rows(db) == []
            sampler.job = next_job
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "completed"
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_exactly_once_deposit_by_ibm_job_id(self, tmp_path,
                                                      monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            svc = mrs.RandomSourceService(db, auto_refill=False)
            batch = mrs.AnuBatch(
                values=[1, 2, 3], data_type="uint16", length=3,
                provider=mrs.PROVIDER_ID_IBM,
                provenance={"job_id": "SAMEJOB", "backend": "ibm_hw"})
            first, second = await asyncio.gather(
                svc._ibm_deposit_batch(batch, "fp"),
                svc._ibm_deposit_batch(batch, "fp"))
            assert first == second
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_stale_checkpoint_and_finish_rejected(self, tmp_path,
                                                        monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            svc = mrs.RandomSourceService(db, auto_refill=False)
            job_id, store = await _insert_task_row(
                db, status="running",
                cursor={"job": "STALE1", "state": "submitted",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            row = await store.get(job_id)
            old_token = int(row["fencing_token"])
            await svc._bump_ibm_fencing(job_id)
            ok = await svc._settle_ibm_row(
                row, {"job": "STALE1", "state": "submitted"},
                action="completed", result_ref='{"job":"STALE1"}',
                fencing_token=old_token)
            assert ok is False
            await store.save_checkpoint(
                job_id, cursor_token=json.dumps(
                    {"job": "STALE1", "state": "completed"}),
                processed=0, fencing_token=old_token)
            current = await store.get(job_id)
            assert current["status"] == "running"
            assert mrs.RandomSourceService._ibm_cursor(current)[
                "state"] == "submitted"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rotation_guard_config_token_quarantine(self, tmp_path,
                                                          monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            values = {mrs.SETTING_IBM_KEY: "key",
                      mrs.SETTING_IBM_INSTANCE: "open-instance"}
            cfg(monkeypatch, values)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            cursor = {"job": "GUARD1", "state": "submitted",
                      "shots": 256, "qubits": 16,
                      "submitted_at": int(time.time()) - 1,
                      "values": 8, "purpose": "refill",
                      "config_fp": svc._ibm_config_fingerprint()}
            job_id, store = await _insert_task_row(
                db, status="interrupted", reason_code="worker_lost",
                cursor=cursor)
            row = await store.get(job_id)
            assert await svc._ibm_recovery_guard(
                row, cursor, int(row["fencing_token"])) is True
            values[mrs.SETTING_IBM_KEY] = "new-key"
            assert await svc._ibm_recovery_guard(
                row, cursor, int(row["fencing_token"])) is False
            values[mrs.SETTING_IBM_KEY] = "key"
            await svc._bump_ibm_fencing(job_id)
            assert await svc._ibm_recovery_guard(
                row, cursor, int(row["fencing_token"])) is False
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_config_rotation_quarantines_old_allows_new(self,
                                                              tmp_path,
                                                              monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "new-key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_BATCH_LENGTH: 8,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            new_job = FakeJob(job_id="NEWJOB", states=("DONE",),
                              bitstrings=make_bitstrings(), backend=backend,
                              usage=1.5)
            service = FakeService([backend], jobs={"NEWJOB": new_job})
            client, sampler = make_client(service, new_job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "OLDJOB", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": "old-config"})
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "completed"
            assert result["provider"] == mrs.PROVIDER_ID_IBM
            assert len(sampler.calls) == 1
            rows = await _task_rows(db)
            old = next(
                r for r in rows
                if mrs.RandomSourceService._ibm_cursor(r).get("job")
                == "OLDJOB")
            assert old["status"] == "failed"
            cursor = mrs.RandomSourceService._ibm_cursor(old)
            assert cursor["state"] == mrs.IBM_JOB_FAILED
            assert cursor["quarantined"] is True
            new_rows = [r for r in rows if r["status"] == "completed"]
            assert len(new_rows) == 1
            assert mrs.RandomSourceService._ibm_cursor(
                new_rows[0])["job"] == "NEWJOB"
            batches = await _batch_rows(db)
            assert len(batches) == 1
            assert '"job":"NEWJOB"' in batches[0]["external_ref"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rotation_during_recovery_does_not_mix_old_result(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            values = {mrs.SETTING_IBM_KEY: "old-key",
                      mrs.SETTING_IBM_INSTANCE: "open-instance",
                      mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                      mrs.SETTING_BATCH_LENGTH: 8,
                      mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False}
            cfg(monkeypatch, values)
            backend = FakeBackend("ibm_hw")

            class GatedResultJob(FakeJob):
                def __init__(self, **kwargs):
                    super().__init__(**kwargs)
                    self.started = threading.Event()
                    self.release = threading.Event()

                def result(self):
                    self.started.set()
                    self.release.wait(timeout=3)
                    return super().result()

            old_job = GatedResultJob(
                job_id="OLDGATE", states=("DONE",),
                bitstrings=make_bitstrings(), backend=backend)
            new_job = FakeJob(job_id="NEWGATE", states=("DONE",),
                              bitstrings=make_bitstrings(), backend=backend)
            service = FakeService(
                [backend], jobs={"OLDGATE": old_job, "NEWGATE": new_job})
            client, sampler = make_client(service, old_job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            old_fp = svc._ibm_config_fingerprint()
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "OLDGATE", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": old_fp})
            await svc._recover_ibm_jobs()
            for _ in range(100):
                if old_job.started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert old_job.started.is_set()
            # Key/CRN меняется, пока старый recovery ждёт result.
            values[mrs.SETTING_IBM_KEY] = "new-key"
            await svc._recover_ibm_jobs()      # quarantine old row + token bump
            old_job.release.set()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            rows = await _task_rows(db)
            old = next(
                r for r in rows
                if mrs.RandomSourceService._ibm_cursor(r).get("job")
                == "OLDGATE")
            assert old["status"] == "failed"
            old_cursor = mrs.RandomSourceService._ibm_cursor(old)
            assert old_cursor["quarantined"] is True
            assert await _batch_rows(db) == []
            # Новый key может submit; старый результат не зачислен.
            sampler.job = new_job
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "completed"
            assert len(sampler.calls) == 1
            batches = await _batch_rows(db)
            assert len(batches) == 1
            assert '"job":"NEWGATE"' in batches[0]["external_ref"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_refill_kicks_recovery_and_fences_new_submit(self, tmp_path,
                                                               monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="LATE1", states=("RUNNING",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"LATE1": job})
            client, sampler = make_client(
                service, job, poll_interval=0.01, job_max_age=5.0,
                sleeper=asyncio.sleep)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "LATE1", "state": "expired",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "blocked"
            assert result["reason"] == "job_in_progress"
            assert sampler.calls == []
            assert "LATE1" in svc._ibm_recovering
            assert await _batch_rows(db) == []
            # Поздний IBM DONE: recovery завершает ровно один batch.
            job._states = ["DONE"]
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_submit_uncertain_fences_new_submit(self, tmp_path,
                                                      monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="UNC2", states=("RUNNING",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"UNC2": job})
            client, sampler = make_client(
                service, job, poll_interval=0.01, job_max_age=5.0,
                sleeper=asyncio.sleep)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="submit_uncertain",
                cursor={"job": "UNC2", "state": "submitted",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "blocked"
            assert result["reason"] == "job_in_progress"
            assert sampler.calls == []
            job._states = ["DONE"]
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_submit_uncertain_with_job_id_resolves(self, tmp_path,
                                                          monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            existing = FakeJob(job_id="UNC1", states=("DONE",),
                               bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"UNC1": existing})
            client, sampler = make_client(service, existing)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="submit_uncertain",
                cursor={"job": "UNC1", "state": "submitted",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 10,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            started = await svc._recover_ibm_jobs()
            assert started == 1
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []
            assert len(await _batch_rows(db)) == 1
            assert (await _task_rows(db))[0]["status"] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_submit_uncertain_without_id_resolves_by_tag(self,
                                                               tmp_path,
                                                               monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            existing = FakeJob(job_id="TAGJOB", states=("DONE",),
                               bitstrings=make_bitstrings(), backend=backend)
            service = FakeService(
                [backend], jobs={"TAGJOB": existing},
                listed_jobs=[existing])
            client, sampler = make_client(service, existing)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="failed", reason_code="submit_uncertain",
                cursor={"state": "pending",
                        "job_tag": "qrng-p5-TAGJOB",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 10,
                        "values": 8, "purpose": "refill",
                        "config_fp": ""})
            started = await svc._recover_ibm_jobs()
            assert started == 1
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []
            assert len(await _batch_rows(db)) == 1
            rows = await _task_rows(db)
            assert rows[0]["status"] == "completed"
            assert mrs.RandomSourceService._ibm_cursor(rows[0])[
                "job"] == "TAGJOB"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_recovery_without_job_id_is_submit_uncertain(self,
                                                               tmp_path,
                                                               monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            client, sampler = make_client(
                FakeService([FakeBackend("ibm_hw")]), FakeJob())
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="running", cursor=None, stale=True,
                created_at=int(time.time()) - 7200)
            started = await svc._recover_ibm_jobs()
            assert started == 0
            rows = await _task_rows(db)
            assert rows[0]["status"] == "failed"
            assert rows[0]["reason_code"] == "submit_uncertain"
            assert sampler.calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_s1_prepared_barrier_aborts_before_submit(self, tmp_path,
                                                            monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="S1FAIL", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            client, sampler = make_client(
                FakeService([backend], jobs={"S1FAIL": job}), job)
            original = client._checkpoint

            async def checkpoint(job_store, job_id, *, fencing_token=None,
                                 **fields):
                if fields.get("state") == mrs.IBM_JOB_PREPARED:
                    return False
                return await original(job_store, job_id,
                                      fencing_token=fencing_token, **fields)

            monkeypatch.setattr(client, "_checkpoint", checkpoint)
            with pytest.raises(mrs.IbmError) as exc:
                await client.fetch(
                    api_key="key", instance="open-instance", length=8,
                    job_store=TaskJobStore(db),
                    supervisor=TaskSupervisor(), deposit=None,
                    account_key="ibm:open-instance", config_fp="fp")
            assert exc.value.code == "provider_unavailable"
            assert sampler.calls == []
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            assert row["reason_code"] == "abandoned_before_submit"
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "state"] == mrs.IBM_JOB_FAILED
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_s2_submit_barrier_aborts_before_sampler_run(self, tmp_path,
                                                                monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="S2FAIL", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            client, sampler = make_client(
                FakeService([backend], jobs={"S2FAIL": job}), job)
            original = client._checkpoint

            async def checkpoint(job_store, job_id, *, fencing_token=None,
                                 **fields):
                if fields.get("state") == mrs.IBM_JOB_SUBMITTING:
                    return False
                return await original(job_store, job_id,
                                      fencing_token=fencing_token, **fields)

            monkeypatch.setattr(client, "_checkpoint", checkpoint)
            with pytest.raises(mrs.IbmError) as exc:
                await client.fetch(
                    api_key="key", instance="open-instance", length=8,
                    job_store=TaskJobStore(db),
                    supervisor=TaskSupervisor(), deposit=None,
                    account_key="ibm:open-instance", config_fp="fp")
            assert exc.value.code == "abandoned_before_submit"
            assert sampler.calls == []
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            assert row["reason_code"] == "abandoned_before_submit"
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "state"] == mrs.IBM_JOB_FAILED
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_takeover_between_s2_and_submit_blocks_sampler(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="S2RACE", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            client, sampler = make_client(
                FakeService([backend], jobs={"S2RACE": job}), job)
            original = client._checkpoint

            async def checkpoint(job_store, job_id, *, fencing_token=None,
                                 **fields):
                result = await original(job_store, job_id,
                                        fencing_token=fencing_token,
                                        **fields)
                if result and fields.get("state") == mrs.IBM_JOB_SUBMITTING:
                    async def _take(conn):
                        await conn.execute(
                            "UPDATE task_jobs SET status = ?, "
                            "reason_code = ?, fencing_token = "
                            "fencing_token + 1 WHERE job_id = ?",
                            ("interrupted", "worker_lost", job_id))
                        return True

                    await db.write_transaction(
                        _take, op_name="test_takeover_after_s2")
                return result

            monkeypatch.setattr(client, "_checkpoint", checkpoint)
            with pytest.raises(mrs.IbmError) as exc:
                await client.fetch(
                    api_key="key", instance="open-instance", length=8,
                    job_store=TaskJobStore(db),
                    supervisor=TaskSupervisor(), deposit=None,
                    account_key="ibm:open-instance", config_fp="fp")
            assert exc.value.code == "claim_revoked"
            assert sampler.calls == []
            row = (await _task_rows(db))[0]
            assert row["status"] == "interrupted"
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "state"] == mrs.IBM_JOB_SUBMITTING
            assert await _batch_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_positive_absent_tag_waits_until_submit_bound(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10,
                              mrs.SETTING_BATCH_LENGTH: 8,
                              mrs.SETTING_PROVIDER_FALLBACK_ENABLED: False})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="ABSENT", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={}, listed_jobs=[])
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            cursor = {"state": mrs.IBM_JOB_SUBMITTING,
                      "job_tag": "qrng-p5-ABSENT",
                      "submit_started_at": int(time.time()),
                      "shots": 256, "qubits": 16, "values": 8,
                      "purpose": "refill",
                      "config_fp": svc._ibm_config_fingerprint()}
            job_id, store = await _insert_task_row(
                db, status="failed", reason_code="submit_uncertain",
                cursor=cursor)
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            row = (await _task_rows(db))[0]
            assert row["status"] == "interrupted"
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "state"] == mrs.IBM_JOB_SUBMITTING
            assert await _batch_rows(db) == []
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "blocked"
            assert result["reason"] == "job_in_progress"
            assert sampler.calls == []
            current = await store.get(job_id)
            aged = dict(cursor)
            aged["submit_started_at"] = int(time.time()) - 7200
            assert await store.save_checkpoint(
                job_id, cursor_token=json.dumps(aged), processed=0,
                fencing_token=int(current["fencing_token"]))

            async def _age(conn):
                await conn.execute(
                    "UPDATE task_jobs SET created_at = ? WHERE job_id = ?",
                    (int(time.time()) - 7200, job_id))
                return True

            await db.write_transaction(_age, op_name="test_age_row")
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            assert row["reason_code"] == "submit_uncertain"
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "state"] == mrs.IBM_JOB_FAILED
            assert sampler.calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_recovery_skips_live_owner_with_fresh_heartbeat(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="LIVE2", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"LIVE2": job})
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="running",
                cursor={"job": "LIVE2", "state": "submitted",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill", "config_fp": ""})
            started = await svc._recover_ibm_jobs()
            assert started == 0
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert service.job_calls == 0
            assert sampler.calls == []
            assert (await _task_rows(db))[0]["status"] == "running"
            assert await _batch_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_restart_s2_resolves_by_tag_and_attaches(self, tmp_path,
                                                           monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="S2JOB", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"S2JOB": job},
                                  listed_jobs=[job])
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            job_id, store = await _insert_task_row(
                db, status="running", stale=True,
                cursor={"state": mrs.IBM_JOB_SUBMITTING,
                        "job_tag": "qrng-p5-S2",
                        "submit_started_at": int(time.time()) - 5,
                        "shots": 256, "qubits": 16, "values": 8,
                        "purpose": "refill", "config_fp": ""})
            old_token = int((await store.get(job_id))["fencing_token"])
            started = await svc._recover_ibm_jobs()
            assert started == 1
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert sampler.calls == []
            assert service.job_calls == 1
            row = (await _task_rows(db))[0]
            assert row["status"] == "completed"
            assert int(row["fencing_token"]) == old_token + 1
            assert mrs.RandomSourceService._ibm_cursor(row)[
                "job"] == "S2JOB"
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rotation_before_resume_quarantines_without_attach(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "new-key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="OLDRES", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"OLDRES": job})
            client, _sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            old_fp = mrs.key_fingerprint("|".join(
                ("old-key", "", "open-instance", "us-east",
                 "ibm_quantum_platform")))
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "OLDRES", "state": "submitted",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": old_fp})
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert service.job_calls == 0
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            cursor = mrs.RandomSourceService._ibm_cursor(row)
            assert cursor["quarantined"] is True
            assert cursor["state"] == mrs.IBM_JOB_FAILED
            assert await _batch_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rotation_during_result_blocks_deposit(self, tmp_path,
                                                         monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            values = {mrs.SETTING_IBM_KEY: "old-key",
                      mrs.SETTING_IBM_INSTANCE: "open-instance"}
            cfg(monkeypatch, values)
            backend = FakeBackend("ibm_hw")

            class RotatingJob(FakeJob):
                def result(self):
                    values[mrs.SETTING_IBM_KEY] = "new-key"
                    return super().result()

            job = RotatingJob(job_id="ROTDEP", states=("DONE",),
                              bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"ROTDEP": job})
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            old_fp = svc._ibm_config_fingerprint()
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                cursor={"job": "ROTDEP", "state": "submitted",
                        "shots": 256, "qubits": 16,
                        "submitted_at": int(time.time()) - 1,
                        "values": 8, "purpose": "refill",
                        "config_fp": old_fp})
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert await _batch_rows(db) == []
            assert sampler.calls == []
            # Старый late result не смешан с новым key; строка карантин.
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            cursor = mrs.RandomSourceService._ibm_cursor(row)
            assert cursor["quarantined"] is True
            assert await _batch_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_takeover_revokes_old_token_before_settlement(self, tmp_path,
                                                                monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            svc = mrs.RandomSourceService(db, auto_refill=False)
            cursor = {"job": "TAKE1", "state": "submitted",
                      "shots": 256, "qubits": 16,
                      "submitted_at": int(time.time()) - 1,
                      "values": 8, "purpose": "refill",
                      "config_fp": svc._ibm_config_fingerprint()}
            job_id, store = await _insert_task_row(
                db, status="running", stale=True, cursor=cursor)
            row = await store.get(job_id)
            old_token = int(row["fencing_token"])
            taken = await svc._takeover_ibm_row(row)
            assert taken is not None
            assert taken["status"] == "interrupted"
            assert int(taken["fencing_token"]) == old_token + 1
            assert await svc._settle_ibm_row(
                row, cursor, action="completed",
                fencing_token=old_token) is False
            assert await svc._ibm_save_cursor(
                job_id, {"job": "TAKE1", "state": "completed"},
                fencing_token=old_token) is False
            current = await store.get(job_id)
            assert current["status"] == "interrupted"
            assert mrs.RandomSourceService._ibm_cursor(current)[
                "state"] == "submitted"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_ancient_job_not_polled_after_horizon(self, tmp_path,
                                                        monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            backend = FakeBackend("ibm_hw")
            job = FakeJob(job_id="ANCIENT", states=("DONE",),
                          bitstrings=make_bitstrings(), backend=backend)
            service = FakeService([backend], jobs={"ANCIENT": job})
            client, sampler = make_client(service, job)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            old = int(time.time()) - 8000
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                created_at=old,
                cursor={"job": "ANCIENT", "state": "submitted",
                        "shots": 256, "qubits": 16,
                        "submitted_at": old, "values": 8,
                        "purpose": "refill",
                        "config_fp": svc._ibm_config_fingerprint()})
            started = await svc._recover_ibm_jobs()
            assert started == 0
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert service.job_calls == 0
            assert sampler.calls == []
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            assert row["reason_code"] == "timeout"
            assert row["error_code"] == "job_horizon_exceeded"
            assert await _batch_rows(db) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_ancient_queued_is_submit_uncertain(self, tmp_path,
                                                      monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            client, sampler = make_client(
                FakeService([FakeBackend("ibm_hw")]), FakeJob())
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="queued", cursor=None,
                created_at=int(time.time()) - 7200)
            started = await svc._recover_ibm_jobs()
            assert started == 0
            row = (await _task_rows(db))[0]
            assert row["status"] == "failed"
            assert row["reason_code"] == "submit_uncertain"
            assert row["error_code"] == "delivery_unknown"
            assert sampler.calls == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_batch_lookup_tristate(self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            svc = mrs.RandomSourceService(db, auto_refill=False)
            assert await svc._ibm_batch_exists("") == mrs.IBM_BATCH_ABSENT
            assert await svc._ibm_batch_exists(
                "NOT-PRESENT") == mrs.IBM_BATCH_ABSENT
            original = svc.db
            svc.db = None
            try:
                assert await svc._ibm_batch_exists(
                    "SOMEJOB") == mrs.IBM_BATCH_UNKNOWN
            finally:
                svc.db = original
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_ancient_completed_batch_still_settles_completed(
            self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            await mrs.RandomStore(db).insert_batch(
                mrs.AnuBatch(values=[1, 2, 3], data_type="uint16",
                             length=3, provider=mrs.PROVIDER_ID_IBM),
                config_fingerprint="", external_ref='{"job":"ANCIENTB"}')
            backend = FakeBackend("ibm_hw")
            service = FakeService([backend], jobs={})
            client, sampler = make_client(service, FakeJob())
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            old = int(time.time()) - 8000
            await _insert_task_row(
                db, status="failed", reason_code="expired",
                created_at=old,
                cursor={"job": "ANCIENTB", "state": "completed",
                        "shots": 256, "qubits": 16,
                        "submitted_at": old, "values": 8,
                        "purpose": "refill",
                        "config_fp": svc._ibm_config_fingerprint()})
            await svc._recover_ibm_jobs()
            await asyncio.gather(*list(svc._ibm_recovery_tasks),
                                 return_exceptions=True)
            assert service.job_calls == 0
            assert sampler.calls == []
            row = (await _task_rows(db))[0]
            assert row["status"] == "completed"
            assert row["reason_code"] == "recovered_pool"
            assert len(await _batch_rows(db)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_auth_blocker_clears_on_config_change(self, tmp_path,
                                                        monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            values = {mrs.SETTING_IBM_KEY: "key-A",
                      mrs.SETTING_IBM_INSTANCE: "open-instance",
                      mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 10}
            cfg(monkeypatch, values)
            client, _sampler = make_client(
                FakeService([FakeBackend("ibm_hw")]), FakeJob())
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            svc._note_ibm_failure("auth_failed", stage="permission")
            assert await svc._ibm_skip_reason() == "auth_failed"
            values[mrs.SETTING_IBM_KEY] = "key-B"
            assert await svc._ibm_skip_reason() is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_daily_limits_stop_new_jobs(self, tmp_path, monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            values = {mrs.SETTING_IBM_KEY: "key",
                      mrs.SETTING_IBM_INSTANCE: "open-instance",
                      mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 1,
                      mrs.SETTING_IBM_MAX_QPU_SECONDS_PER_DAY: 10}
            cfg(monkeypatch, values)
            client, _sampler = make_client(
                FakeService([FakeBackend("ibm_hw")]), FakeJob())
            svc = mrs.RandomSourceService(db, auto_refill=False)
            svc.set_ibm_client(client)
            await _insert_task_row(
                db, status="completed", created_at=int(time.time()),
                result_ref=json.dumps({"job": "old", "usage": 4.0}))
            assert await svc._ibm_skip_reason() == "daily_job_limit"
            values[mrs.SETTING_IBM_MAX_JOBS_PER_DAY] = 10
            values[mrs.SETTING_IBM_MAX_QPU_SECONDS_PER_DAY] = 1
            assert await svc._ibm_skip_reason() == "daily_usage_limit"
        finally:
            await db.close()


# ── статус/изоляция/секреты ────────────────────────────────────────────────
class TestStatusAndIsolation:
    @pytest.mark.asyncio
    async def test_ibm_daily_cap_falls_back_to_anu(self, tmp_path,
                                                   monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_KEY: "anu-key",
                              mrs.SETTING_IBM_KEY: "ibm-key",
                              mrs.SETTING_IBM_INSTANCE: "open-instance",
                              mrs.SETTING_IBM_MAX_JOBS_PER_DAY: 0,
                              mrs.SETTING_BATCH_LENGTH: 4})
            svc = mrs.RandomSourceService(db, auto_refill=False)
            ibm_client, _sampler = make_client(
                FakeService([FakeBackend("ibm_hw")]), FakeJob())
            svc.set_ibm_client(ibm_client)

            async def http_get(url, headers, params, timeout):
                return mrs._HttpResponse(
                    200, {}, json.dumps({
                        "success": True, "type": "uint16", "length": 4,
                        "data": [1, 2, 3, 4]}))

            svc.set_client(mrs.AnuClient(http_get=http_get,
                                         min_interval=0.0))
            result = await svc.refill_if_needed(force=True)
            assert result["status"] == "completed"
            assert result["provider"] == mrs.PROVIDER_ID_ANU
            rows = await db.db.execute(
                "SELECT provider FROM mca_random_batches "
                "ORDER BY created_at DESC LIMIT 1")
            last = await rows.fetchone()
            assert last is not None and last["provider"] == mrs.PROVIDER_ID_ANU
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_per_provider_fingerprint_isolation(self, tmp_path,
                                                      monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            values = {mrs.SETTING_KEY: "anu-key-A",
                      mrs.SETTING_IBM_KEY: "ibm-key-A",
                      mrs.SETTING_IBM_CRN: "crn-A",
                      mrs.SETTING_IBM_INSTANCE: "open-instance"}
            cfg(monkeypatch, values)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            store = mrs.RandomStore(db)
            await store.insert_batch(
                mrs.AnuBatch(values=[1, 2, 3], data_type="uint16", length=3),
                config_fingerprint=svc._current_fingerprint())
            await store.insert_batch(
                mrs.AnuBatch(values=[4, 5], data_type="uint16", length=2,
                             provider=mrs.PROVIDER_ID_IBM),
                config_fingerprint=svc._ibm_config_fingerprint())
            assert await svc.provider_reserve() == {
                mrs.PROVIDER_ID_ANU: 3, mrs.PROVIDER_ID_IBM: 2}
            values[mrs.SETTING_IBM_KEY] = "ibm-key-B"
            assert await svc.provider_reserve() == {mrs.PROVIDER_ID_ANU: 3}
            snap = await svc.status_snapshot()
            assert snap["provider_quarantined"][mrs.PROVIDER_ID_IBM] == 2
            assert snap["provider_reserve"][mrs.PROVIDER_ID_ANU] == 3
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_status_snapshot_has_no_secrets(self, tmp_path,
                                                  monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            cfg(monkeypatch, {mrs.SETTING_IBM_KEY: "super-secret-key-987",
                              mrs.SETTING_IBM_CRN: "crn:secret:value",
                              mrs.SETTING_IBM_INSTANCE: "open-instance"})
            svc = mrs.RandomSourceService(db, auto_refill=False)
            snap = await svc.status_snapshot()
            text = json.dumps(snap, ensure_ascii=False)
            assert "super-secret-key-987" not in text
            assert "crn:secret:value" not in text
            assert snap["ibm_key_present"] is True
            assert snap["ibm_crn_present"] is True
            assert "ibm_state" in snap
            assert "ibm_jobs" in snap
        finally:
            await db.close()


async def _task_rows(db):
    cursor = await db.db.execute(
        "SELECT * FROM task_jobs WHERE kind = ? ORDER BY created_at",
        (mrs.IBM_JOB_KIND,))
    return [dict(row) for row in await cursor.fetchall()]


async def _batch_rows(db):
    cursor = await db.db.execute(
        "SELECT * FROM mca_random_batches WHERE provider = ?",
        (mrs.PROVIDER_ID_IBM,))
    return [dict(row) for row in await cursor.fetchall()]
