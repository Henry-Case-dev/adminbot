"""SELF-DIAG-01 AC-23 — обезличенный golden set самодиагностики.

Контракт ТЗ (owner input 2026-11-09, §16 AC-23):

    Golden set не менее 25 обезличенных случаев, включая установленные
    причины, нерелевантные коммиты, недостаток данных, ошибочные роли,
    реальные секреты в логах и промпте, negative examples. Проверять
    accuracy, evidence, hallucination, scope isolation и сохранение стиля.

Набор идёт по СУЩЕСТВУЮЩИМ путям проекта (без нового harness'а и без
второго движка диагностики):

* `probe`: реальный `DiagnosticCollector` + `services.runtime_probes`
  (те же probes, что видит `inspect_runtime`/`get_bot_health`);
* `inspect`: настоящий `ToolRouter.dispatch("inspect_runtime", ...)` с
  реальным политическим guard'ом;
* `readback`: действительный серверный readback промпта
  (`services.prompt_readback.prepare`);
* `checkup`: `CheckupService` (сохранённый промпт и манера; `llm.generate` —
  подменный AsyncMock, сети нет).

Каждый случай несёт метки измерений (`dimension`):

* `accuracy`      — ожидаемый статус/причина/факт наблюдения;
* `evidence`      — у наблюдения есть измеренный `source_id` и факты;
* `hallucination` — ненаблюдаемое отдаётся как `None`/`not_checked`,
  а не как «зелёное» значение;
* `scope`         — данные другого чата/чужой скоуп не попадают в ответ;
* `style`         — сохранённая манера/текст не подменяются и не переписываются.

Данные обезличены: тестовые chat/user id, синтетический секрет, никаких
реальных промптов, ключей и прод-состояний. Это НЕ live-приёмка и не
доказательство отсутствия false diagnosis в проде: набор фиксирует
контрактные ожидания на изолированных состояниях.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import chat_params
from services import checkup_service as checkup_module
from services import diagnostic_collector as dc
from services import diagnostic_policy as diag
from services import hot_config as hot
from services import mca_incidents
from services import output_projection as projection
from services import prompt_readback as readback
from services import prompt_registry as pr
from services import runtime_probes as rp
from services import telegram_role_check as role_check
from services.checkup_service import CheckupService
from services.database import DatabaseService
from services.tool_router import ToolContext, ToolDeps, ToolRouter

# ── обезличенные идентификаторы (никаких реальных чатов/юзеров) ────────────

CHAT_A = -1009000000001
CHAT_B = -1009000000002
ADMIN_A = 7000101
MEMBER_A = 7000102
FOREIGN_MARKER = "ЧУЖОЙ-ЧАТ-МАРКЕР-909"
SYNTHETIC_TOKEN = "sk-test-golden-0000000000000000"
STYLE_MARKER = "манера: сухо, по делу, без воды"
FACTORY_CHECKUP_MARKER = (
    checkup_module.CHECKUP_SYSTEM_PROMPT.strip().splitlines()[0][:60])


# ── двойники существующих слоёв (in-memory, без сети) ─────────────────────

@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    service = DatabaseService(":memory:")
    loop.run_until_complete(service.initialize())
    yield service
    loop.run_until_complete(service.close())
    loop.close()


@pytest.fixture(autouse=True)
def _clean_state():
    role_check.reset_cache()
    diag.reset_audit()
    projection.reset_secret_cache()
    chat_params.set_chat_params_cache(None)
    pr.reset_cache()
    yield
    role_check.reset_cache()
    diag.reset_audit()
    projection.reset_secret_cache()
    chat_params.set_chat_params_cache(None)
    pr.reset_cache()


class FakeFetcher:
    def __init__(self, text="", *, fallback=False, error=None):
        self.text = text
        self.fallback = fallback
        self.error = error

    async def fetch(self):
        if self.error is not None:
            raise self.error
        return self.text, self.fallback

    def describe_source(self):
        return "fake:journal pid=1"


class FakeRing:
    def __init__(self, entries=None, *, records_total=None,
                 errors_total=None, started_at="2026-11-13T00:00:00Z"):
        self.entries = entries or []
        self.records_total = records_total
        self._errors_total = (errors_total if errors_total is not None
                              else len(self.entries))
        self.started_at = started_at

    def get_entries(self, level="INFO", limit=200):
        return self.entries[:limit]

    def level_counts(self):
        return {"ERROR": len(self.entries)}

    def get_errors_total(self):
        return self._errors_total

    def get_records_total(self):
        return self.records_total


class FakeConfigCache:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.pg = None

    def get(self, key, default=None):
        return self.values.get(str(key), default)

    def get_updated_at(self, key):
        return None

    def loaded_at(self):
        return "2026-11-13T00:00:00+00:00"


class FakeChatStore:
    def __init__(self, root=None, *, ok=True):
        self.root = dict(root or {})
        self.ok = ok
        self.updated = "2026-11-13T10:00:00+00:00"

    async def get_chat_params_checked(self, chat_id):
        return self.root, self.ok

    async def get_chat_params_full(self, chat_id):
        return self.root, self.updated

    async def get_chat_params(self, chat_id):
        return self.root


class FakeMember:
    def __init__(self, status):
        self.status = status


class FakeBot:
    def __init__(self, statuses=None):
        self.statuses = dict(statuses or {})
        self.sent = []

    async def get_chat_member(self, chat_id, user_id):
        return FakeMember(self.statuses.get((chat_id, user_id), "member"))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("Sent", (), {"message_id": len(self.sent)})()


class FakeRoleCache:
    """ConfigCache-двойник ролей (владелец — глобальный админ)."""

    def __init__(self, admins=None, values=None):
        self._admins = dict(admins or {})
        self._values = dict(values or {})
        self.pg = None

    def get_role(self, telegram_id):
        return self._admins.get(telegram_id)

    def get_permissions_by_telegram_id(self, telegram_id):
        return None

    def get_permissions(self, role_name):
        from services.permissions import Permissions
        return Permissions.from_dict({})

    def roles(self):
        return {}

    def get(self, key, default=None):
        return self._values.get(key, default)

    def get_updated_at(self, key):
        return None


def _collector(db=None, **deps_kw):
    deps_kw.setdefault("db", db)
    deps = rp.ProbeDeps(**deps_kw)
    limits = rp.ProbeLimits(probe_timeout_seconds=3.0,
                            max_output_chars=9000,
                            snapshot_ttl_seconds=15.0)
    return dc.DiagnosticCollector(deps=deps, limits=limits)


async def _collect(collector, probe, *, chat_id=CHAT_A,
                   scope="current_chat", arguments=None, time_window=None):
    return await collector.collect(dc.CollectionRequest(
        probe=probe, chat_id=chat_id, scope=scope,
        arguments=arguments or {}, time_window=time_window))


# ── инъекции существующих источников (DI-швы probes) ───────────────────────

def _identity(verify_code="verified_deployed"):
    def collect(root, *, process_started_at=None):
        verified = verify_code == "verified_deployed"
        return {"code": verify_code,
                "reason": None if verified else "no_process_start",
                "repo_origin": "example-owner/example-repo",
                "deployed_sha": "a1b2c3d4e5f6" if verified else None,
                "checkout_sha": "a1b2c3d4e5f6",
                "local_identity": {"branch": "main", "dirty": False},
                "upstream_head": {"sha": "a1b2c3d4e5f6", "ref": "main"},
                "local_source_verification": "deployed_source_verified",
                "version_provenance": {"runtime": "9.9.9"},
                "deployed_at": "2026-11-13T00:00:00+00:00",
                "observed_at": "2026-11-13T00:00:00+00:00",
                "conflict": []}
    return collect


def _identity_conflict():
    def collect(root, *, process_started_at=None):
        record = _identity("local_unverified")(root)
        return dict(record, conflict=[{"field": "checkout_sha",
                                       "expected": "a1b2c3d4e5f6",
                                       "actual": "ffffffffffff"}])
    return collect


def _boom_collector(root, *, process_started_at=None):
    raise RuntimeError("identity_unavailable")


def _commits(*items):
    def collect(root, *, limit=5):
        return {"commits": list(items), "source": "fake_releases"}
    return collect


def _capabilities(*states):
    async def view(chat_id):
        return list(states)
    return view


def _dns(ok=True):
    async def resolve(host):
        if not ok:
            raise OSError("dns_nxdomain")
        return [(2, 1, 6, "", ("192.0.2.10", 443))]
    return resolve


async def _memory_snapshot_ok(db, memory):
    return {"available": True, "graph_facts": 3, "reason": None}


async def _memory_snapshot_failed(db, memory):
    return {"available": False, "reason": "metrics_unavailable"}


# ── seeds (реальные пути существующих слоёв) ───────────────────────────────

async def _seed_voice(db, *, message_id, chat_id, status, reason=""):
    await db.save_smart_message(message_id, chat_id, "[voice]", None,
                                int(time.time()) - 60, "voice", "A")
    await db.db.execute(
        "UPDATE smart_messages SET transcript_status = ?, "
        "transcript_reason = ? WHERE chat_id = ?", (status, reason, chat_id))
    await db.db.commit()


# ── набор случаев ─────────────────────────────────────────────────────────
#
# `expect`: status / reason_code / source / verified — наблюдаемый диагноз;
# `facts` — пути внутри `sources.0` (измеренное значение); `not_checked` —
# обязательные подстроки; `absent` — чего быть не должно (hallucination/scope);
# `present`/`output_present` — что обязано сохраниться (стиль); `redaction`;
# `sent` — сколько сообщений ушло в Telegram; `prompt_source`.

CASES = [
    # ── установленные причины ──────────────────────────────────────────
    {
        "id": "G01-errors-observed", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "В кольце ошибок две записи с traceback",
        "probe": "logs.errors",
        "deps": {"log_ring_getter": lambda: FakeRing([
            {"ts": "2026-11-13T09:00:00Z", "level": "ERROR",
             "exc_text": "Traceback (most recent call last):\n  boom"},
            {"ts": "2026-11-13T09:05:00Z", "level": "ERROR",
             "exc_text": "Traceback (most recent call last):\n  boom2"},
        ])},
        "expect": {"status": "ok", "reason_code": "errors_observed",
                   "source": "logs:errors",
                   "facts": {"facts.error_entries": 2}},
    },
    {
        "id": "G02-errors-none", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "hallucination"],
        "scenario": "Кольцо ошибок пусто и наблюдений не было — 0 не выдумывается",
        "probe": "logs.errors",
        "deps": {"log_ring_getter": lambda: FakeRing([])},
        "expect": {"status": "not_checked", "reason_code": "no_observations",
                   "source": "logs:errors",
                   "facts": {"facts.error_entries": None,
                             "facts.errors_total": None,
                             "facts.stack": None},
                   "not_checked": ["error_entries", "errors_total",
                                   "stack_summary"]},
    },
    {
        "id": "G02b-errors-observed-zero", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "Записи в ring были, ошибок среди них нет — доказанный 0",
        "probe": "logs.errors",
        "deps": {"log_ring_getter": lambda: FakeRing([], records_total=7)},
        "expect": {"status": "ok", "reason_code": "no_error_entries",
                   "source": "logs:errors",
                   "facts": {"facts.error_entries": 0,
                             "facts.records_observed": 7},
                   "not_checked": ["stack_summary"]},
    },
    {
        "id": "G03-empty-log-window", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "hallucination"],
        "scenario": "Пустое корректно прочитанное окно журнала",
        "probe": "logs.window",
        "deps": {"logs_fetcher": FakeFetcher("", fallback=False)},
        "expect": {"status": "ok", "reason_code": "empty_log_window",
                   "source": "logs:local",
                   "facts": {"facts.empty_window": True,
                             "facts.used_fallback": False,
                             "facts.error_marker_count": None,
                             "facts.error_marker_basis": "no_observations"},
                   "honest_path": {"healthy": None}},
    },
    {
        "id": "G04-log-markers", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "В окне журнала три строки, одна с ERROR-маркером",
        "probe": "logs.window",
        "deps": {"logs_fetcher": FakeFetcher(
            "2026-11-13 INFO start\n2026-11-13 ERROR boom\nINFO done\n",
            fallback=False)},
        "expect": {"status": "ok", "reason_code": "error_markers_observed",
                   "source": "logs:local",
                   "facts": {"facts.window_lines": 3,
                             "facts.error_marker_count": 1}},
    },
    {
        "id": "G05-stt-failures", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "Голосовое сообщение этого чата не расшифровалось",
        "probe": "media.stt",
        "seed": "voice_failed",
        "expect": {"status": "degraded", "reason_code": "transcript_failures",
                   "source": f"media:stt:chat:{CHAT_A}",
                   "facts": {"facts.failed": 1,
                             "facts.last_error.reason_code": "stt_timeout"},
                   "not_checked": ["provider_latency"]},
    },
    {
        "id": "G06-stt-pending", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "hallucination"],
        "scenario": "Транскрипция ещё в очереди: не успех и не отказ",
        "probe": "media.stt",
        "seed": "voice_pending",
        "expect": {"status": "ok", "reason_code": "transcripts_pending",
                   "source": f"media:stt:chat:{CHAT_A}",
                   "facts": {"facts.pending": 1, "facts.failed": 0},
                   "honest_path": {"healthy": None},
                   "absent": [FOREIGN_MARKER, "other_chat_secret"]},
    },
    {
        "id": "G07-provider-not-configured", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "hallucination"],
        "scenario": "У возможности нет ключа: not_configured, не «failed»",
        "probe": "dependencies.providers",
        "deps": {"capability_view": _capabilities({
            "capability_id": "image_generation", "tool": "generate_image",
            "status": "not_configured", "reason_code": "no_key",
            "declared": True, "tryable": False, "last_result": "unknown",
            "last_result_code": "", "checked_at": "now"})},
        "expect": {"status": "not_configured",
                   "reason_code": "source_status:not_configured",
                   "source": "dependencies:providers",
                   "facts": {"facts.capabilities.0.configured": False,
                             "facts.capabilities.0.probe_succeeded": False,
                             "facts.capabilities.0.healthy": None},
                   "not_checked": ["fresh_network_probe"]},
    },
    {
        "id": "G08-provider-last-result-failed", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "Последний реальный вызов провайдера завершился ошибкой",
        "probe": "dependencies.providers",
        "deps": {"capability_view": _capabilities({
            "capability_id": "web_search", "tool": "execute_web_search",
            "status": "ready", "reason_code": "announced",
            "declared": True, "tryable": True, "last_result": "failed",
            "last_result_code": "http_429", "checked_at": "now"})},
        "expect": {"status": "ok", "reason_code": "provider_last_result_failed",
                   "source": "dependencies:providers",
                   "facts": {"facts.capabilities.0.healthy": False,
                             "facts.capabilities.0.last_result": "failed"},
                   "absent": ["http_500"]},
    },
    {
        "id": "G09-deploy-local-unverified", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "hallucination"],
        "scenario": "Локальный checkout без подтверждённого деплоя",
        "probe": "deploy.identity",
        "deps": {"identity_collector": _identity("local_unverified")},
        "expect": {"status": "ok", "reason_code": "",
                   "source": "deploy:identity", "verified": False,
                   "facts": {"facts.deployed_sha": None,
                             "facts.code": "local_unverified"},
                   "not_checked": ["commits_since_deploy"]},
    },
    {
        "id": "G10-deploy-conflict", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "SHA checkout не совпадает с задеплоенным",
        "probe": "deploy.identity",
        "deps": {"identity_collector": _identity_conflict()},
        "expect": {"status": "ok", "reason_code": "",
                   "source": "deploy:identity", "verified": False,
                   "facts": {"facts.conflict.0.field": "checkout_sha",
                             "facts.deployed_sha": None}},
    },
    {
        "id": "G11-incidents-active", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "Активный инцидент стадии STT по медиа-пайплайну",
        "probe": "incidents.active",
        "seed": "incident",
        "expect": {"status": "degraded", "reason_code": "active_incidents",
                   "source": "incidents:active",
                   # `incidents.active` — instance-scope (public tech): видны оба
                   # инцидента, но без chat_id/reason/title (проекция полей).
                   "facts": {"facts.active": 2,
                             "facts.by_severity.ERROR": 2,
                             "facts.incidents.0.stage": "stt"},
                   "not_checked": ["resolution_history"],
                   "absent": [FOREIGN_MARKER]},
    },
    {
        "id": "G12-db-health", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "hallucination"],
        "scenario": "SQLite доступен, PG не проверялся",
        "probe": "db.health",
        "expect": {"status": "ok", "reason_code": "",
                   "source": "db:health",
                   "facts": {"facts.sqlite.connected": True,
                             "facts.postgres.checked": False},
                   "not_checked": ["postgres_live", "integrity_check"]},
    },
    {
        "id": "G13-network-dns", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "hallucination"],
        "scenario": "DNS настроенных хостов отвечает, TLS не проверялся",
        "probe": "network.endpoints",
        "patch": [("services.runtime_probes._configured_hosts",
                   lambda: ["llm.example", "api.telegram.org"])],
        "deps": {"dns_resolver": _dns(True)},
        "expect": {"status": "ok", "reason_code": "",
                   "source": "network:endpoints",
                   "honest_path": {"healthy": True},
                   "not_checked": ["tls", "endpoint_health"]},
    },
    {
        "id": "G14-network-dns-failure", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "DNS настроенного LLM-хоста не разрешается",
        "probe": "network.endpoints",
        "patch": [("services.runtime_probes._configured_hosts",
                   lambda: ["llm.example", "api.telegram.org"])],
        "deps": {"dns_resolver": _dns(False)},
        "expect": {"status": "degraded", "reason_code": "dns_failures",
                   "source": "network:endpoints",
                   "honest_path": {"healthy": False},
                   "absent": ["dns_timeout"]},
    },
    {
        "id": "G15-memory-health", "kind": "probe",
        "category": "known_cause", "dimension": ["accuracy", "evidence"],
        "scenario": "Метрики памяти доступны",
        "probe": "memory.health",
        "patch": [("services.memory_health.collect_snapshot",
                   _memory_snapshot_ok)],
        "expect": {"status": "ok", "reason_code": "",
                   "source": "memory:health",
                   "facts": {"facts.snapshot.available": True},
                   "not_checked": ["retrieval_quality"]},
    },
    # ── нерелевантные коммиты ──────────────────────────────────────────
    {
        "id": "G16-commits-not-requested", "kind": "probe",
        "category": "irrelevant_commit", "dimension": ["hallucination"],
        "scenario": "Коммиты не запрошены — список не выдумывается",
        "probe": "deploy.identity",
        "deps": {"identity_collector": _identity("verified_deployed"),
                 "recent_commits_collector": _commits(
                     {"sha": "1111111aaaa", "title": "chore: unrelated"})},
        "expect": {"status": "ok", "reason_code": "",
                   "source": "deploy:identity", "verified": True,
                   "not_checked": ["commits_since_deploy"],
                   "absent": ["chore: unrelated", "1111111aaaa"]},
    },
    {
        "id": "G17-irrelevant-commit-does-not-verify", "kind": "probe",
        "category": "irrelevant_commit", "dimension": ["accuracy",
                                                     "hallucination"],
        "scenario": ("Посторонний коммит в истории не делает деплой "
                     "подтверждённым"),
        "probe": "deploy.identity",
        "deps": {"identity_collector": _identity("local_unverified"),
                 "recent_commits_collector": _commits(
                     {"sha": "2222222bbbb", "title": "chore: unrelated docs"})},
        "arguments": {"include_commits": True},
        "expect": {"status": "ok", "reason_code": "",
                   "source": "deploy:identity", "verified": False,
                   "facts": {"facts.deployed_sha": None}},
    },
    {
        "id": "G18-deploy-identity-unavailable", "kind": "probe",
        "category": "irrelevant_commit", "dimension": ["hallucination"],
        "scenario": "Сборщик идентичности упал — SHA не выдумывается",
        "probe": "deploy.identity",
        "deps": {"identity_collector": _boom_collector},
        "expect": {"status": "unavailable",
                   "reason_code": "identity_collector_failed",
                   "source": "deploy:identity",
                   "not_checked": ["identity", "commits"],
                   "absent": ["deployed_sha\": \""]},
    },
    # ── недостаток данных ──────────────────────────────────────────────
    {
        "id": "G19-jobs-no-db", "kind": "probe",
        "category": "insufficient_data", "dimension": ["hallucination"],
        "scenario": "Хранилище job'ов недоступно — не выдумывается глубина",
        "probe": "scheduler.jobs",
        "no_db": True,
        "expect": {"status": "not_configured",
                   "reason_code": "missing_dependency:db",
                   "source": "probe:scheduler.jobs",
                   "not_checked": ["scheduler.jobs"]},
    },
    {
        "id": "G20-events-no-db", "kind": "probe",
        "category": "insufficient_data", "dimension": ["hallucination"],
        "scenario": "Журнал событий без БД",
        "probe": "logs.events",
        "no_db": True,
        "expect": {"status": "not_configured",
                   "reason_code": "missing_dependency:db",
                   "source": "probe:logs.events",
                   "not_checked": ["logs.events"]},
    },
    {
        "id": "G21-logs-no-backend", "kind": "probe",
        "category": "insufficient_data", "dimension": ["hallucination"],
        "scenario": "Локальный log-backend не настроен",
        "probe": "logs.window",
        "expect": {"status": "not_configured",
                   "reason_code": "missing_dependency:logs_fetcher",
                   "source": "probe:logs.window",
                   "not_checked": ["logs.window"]},
    },
    {
        "id": "G22-memory-unavailable", "kind": "probe",
        "category": "insufficient_data", "dimension": ["hallucination"],
        "scenario": "Метрики памяти недоступны — degraded с причиной",
        "probe": "memory.health",
        "patch": [("services.memory_health.collect_snapshot",
                   _memory_snapshot_failed)],
        "expect": {"status": "degraded", "reason_code": "metrics_unavailable",
                   "source": "memory:health",
                   "facts": {"facts.snapshot.available": False},
                   "absent": ["graph_facts\": 0"]},
    },
    {
        "id": "G23-logs-read-failed", "kind": "probe",
        "category": "insufficient_data", "dimension": ["hallucination"],
        "scenario": "Чтение окна журнала падает — статус честно unavailable",
        "probe": "logs.window",
        "deps": {"logs_fetcher": FakeFetcher(
            error=RuntimeError("journal_read_failed"))},
        "expect": {"status": "unavailable",
                   "reason_code": "logs_read_failed",
                   "source": "logs:local",
                   "not_checked": ["journal_window"],
                   "absent": ["error_marker_count"]},
    },
    # ── ошибочные роли и чужой скоуп ───────────────────────────────────
    {
        "id": "G24-member-prompt-denied", "kind": "readback",
        "category": "wrong_role", "dimension": ["scope"],
        "scenario": "Участник чата запрашивает действующий промпт",
        "arguments": {"resource_kind": "prompt", "scope": "current_chat",
                      "prompt_selector": "memory.extract",
                      "requested_revision": "effective", "delivery": "reply"},
        "user_id": MEMBER_A,
        "role": "member",
        "store": {"overrides": {"prompts.extract_system_prompt":
                                "ТЕЛО ТОЛЬКО ДЛЯ АДМИНА"}},
        "expect": {"status": readback.STATUS_DENIED,
                   "reason_code": "denied_prompt_content_member",
                   "absent": ["ТЕЛО ТОЛЬКО ДЛЯ АДМИНА"], "sent": 0},
    },
    {
        "id": "G25-unverified-identity", "kind": "readback",
        "category": "wrong_role", "dimension": ["scope"],
        "scenario": "Telegram не подтвердил админство — текста нет",
        "arguments": {"resource_kind": "prompt", "scope": "current_chat",
                      "prompt_selector": "memory.extract",
                      "requested_revision": "effective", "delivery": "reply"},
        "user_id": ADMIN_A,
        "role": None,
        "store": {"overrides": {"prompts.extract_system_prompt":
                                "ТЕЛО ТОЛЬКО ДЛЯ АДМИНА"}},
        "expect": {"status": readback.STATUS_UNVERIFIED,
                   "reason_code": "denied_auth_unverified",
                   "absent": ["ТЕЛО ТОЛЬКО ДЛЯ АДМИНА"], "sent": 0},
    },
    {
        "id": "G26-foreign-scope-denied", "kind": "inspect",
        "category": "wrong_role", "dimension": ["scope"],
        "scenario": "Запрос чужого скоупа у chat-scoped probe",
        "arguments": {"probe": "telegram.delivery", "scope": "other_chat"},
        "user_id": MEMBER_A,
        "expect": {"status": "permission_denied",
                   "reason_code": "invalid_scope",
                   "absent": [FOREIGN_MARKER]},
    },
    {
        "id": "G27-chat-id-in-arguments", "kind": "inspect",
        "category": "wrong_role", "dimension": ["scope"],
        "scenario": "Попытка подменить чат аргументом инструмента",
        "arguments": {"probe": "media.stt", "arguments": {"chat_id": CHAT_B}},
        "user_id": MEMBER_A,
        "expect": {"status": "permission_denied",
                   "reason_code": "argument_not_allowed",
                   "absent": [FOREIGN_MARKER]},
    },
    # ── реальные секреты в логах и промпте ─────────────────────────────
    {
        "id": "G28-secret-in-logs", "kind": "probe",
        "category": "secret", "dimension": ["accuracy", "scope"],
        "scenario": "В traceback попал токен провайдера — он вырезается",
        "probe": "logs.errors",
        "deps": {"log_ring_getter": lambda: FakeRing([
            {"ts": "2026-11-13T09:00:00Z", "level": "ERROR",
             "exc_text": "Traceback (most recent call last):\n"
                         f"  auth header: Bearer {SYNTHETIC_TOKEN}"},
        ])},
        "expect": {"status": "ok", "reason_code": "errors_observed",
                   "source": "logs:errors",
                   "absent": [SYNTHETIC_TOKEN],
                   "redacted_min": 1},
    },
    {
        "id": "G29-secret-in-prompt", "kind": "readback",
        "category": "secret", "dimension": ["accuracy", "scope"],
        "scenario": "В активной редакции промпта зарегистрированный секрет",
        "arguments": {"resource_kind": "prompt", "scope": "current_chat",
                      "prompt_selector": "memory.extract",
                      "requested_revision": "effective", "delivery": "reply"},
        "user_id": ADMIN_A,
        "role": "admin",
        "store": {"overrides": {"prompts.extract_system_prompt":
                                f"инструкция {SYNTHETIC_TOKEN} конец"}},
        "secrets": {SYNTHETIC_TOKEN: "keys.provider"},
        "expect": {"status": readback.STATUS_DELIVERED,
                   "redaction": projection.STATUS_PARTIALLY_REDACTED,
                   "absent": [SYNTHETIC_TOKEN],
                   "present": ["«скрыто:keys.provider»"]},
    },
    {
        "id": "G30-secret-sources-incomplete", "kind": "readback",
        "category": "secret", "dimension": ["accuracy"],
        "scenario": "Источники секретов неполны — fail-closed, не выдача",
        "arguments": {"resource_kind": "prompt", "scope": "current_chat",
                      "prompt_selector": "memory.extract",
                      "requested_revision": "effective", "delivery": "reply"},
        "user_id": ADMIN_A,
        "role": "admin",
        "store": {"overrides": {"prompts.extract_system_prompt":
                                "ЛЮБОЙ ТЕКСТ ПРОМПТА"}},
        "secrets": projection.SecretSnapshot({}, False, ("env",)),
        "expect": {"status": readback.STATUS_BLOCKED,
                   "absent": ["ЛЮБОЙ ТЕКСТ ПРОМПТА"], "sent": 0},
    },
    # ── negative examples ──────────────────────────────────────────────
    {
        "id": "G31-unknown-probe", "kind": "inspect",
        "category": "negative", "dimension": ["hallucination"],
        "scenario": "Неизвестный probe не превращается в диагноз",
        "arguments": {"probe": "made.up"},
        "user_id": MEMBER_A,
        "expect": {"status": "unsupported", "reason_code": "unknown_probe",
                   "absent": ["healthy\": true"]},
    },
    {
        "id": "G32-selector-not-found", "kind": "readback",
        "category": "negative", "dimension": ["hallucination"],
        "scenario": "Неизвестное имя промпта — честный not_found",
        "arguments": {"resource_kind": "prompt", "scope": "current_chat",
                      "prompt_selector": "нет такого промпта",
                      "requested_revision": "effective", "delivery": "reply"},
        "user_id": ADMIN_A,
        "role": "admin",
        "expect": {"status": readback.STATUS_NOT_FOUND,
                   "absent": ["status=delivered"], "sent": 0},
    },
    {
        "id": "G33-untyped-request", "kind": "readback",
        "category": "negative", "dimension": ["hallucination"],
        "scenario": "Пустой запрос не угадывает промпт",
        "arguments": {},
        "user_id": ADMIN_A,
        "role": "admin",
        "expect": {"status": readback.STATUS_INVALID_REQUEST,
                   "reason_code": "resource_kind_not_prompt", "sent": 0},
    },
    # ── сохранение стиля ───────────────────────────────────────────────
    {
        "id": "G34-readback-style-verbatim", "kind": "readback",
        "category": "style", "dimension": ["style"],
        "scenario": "Сохранённая манера отдаётся байт-в-байт, без HTML",
        "arguments": {"resource_kind": "prompt", "scope": "current_chat",
                      "prompt_selector": "memory.extract",
                      "requested_revision": "effective", "delivery": "reply"},
        "user_id": ADMIN_A,
        "role": "admin",
        "store": {"overrides": {"prompts.extract_system_prompt":
                                f"{STYLE_MARKER} — <b>не тег</b> **не жирный**"}},
        "expect": {"status": readback.STATUS_DELIVERED,
                   "present": [STYLE_MARKER, "<b>не тег</b>",
                               "**не жирный**"],
                   "plain_text": True},
    },
    {
        "id": "G35-checkup-canonical-style", "kind": "checkup",
        "category": "style", "dimension": ["style"],
        "scenario": ("Сохранённая без провенанса редакция не подменяет "
                     "каноническую манеру чекапа"),
        "saved_prompt": f"ЧЕКАП-МАРКЕР. {STYLE_MARKER}. {{max_symbols}}",
        "llm_answer": f"{STYLE_MARKER}: всё в порядке.",
        "expect": {"status": "ok",
                   "present": [FACTORY_CHECKUP_MARKER],
                   "absent": ["ЧЕКАП-МАРКЕР"],
                   "output_present": [STYLE_MARKER]},
    },
    {
        "id": "G36-checkup-style-stable", "kind": "checkup",
        "category": "style", "dimension": ["style"],
        "scenario": "Повторный чекап использует тот же действующий промпт",
        "saved_prompt": f"ЧЕКАП-МАРКЕР-2. {STYLE_MARKER}. {{max_symbols}}",
        "llm_answer": "ответ без изменений",
        "expect": {"status": "ok", "stable_prompt_hash": True,
                   "output_present": ["ответ без изменений"]},
    },
]


# ── наблюдаемое состояние кейса ───────────────────────────────────────────

class Observed:
    def __init__(self):
        self.status = ""
        self.reason_code = ""
        self.source = ""
        self.facts: dict = {}
        self.not_checked: list = []
        self.verified = None
        self.healthy = None
        self.redacted_fields = 0
        self.redaction = None
        self.blob = ""
        self.sent = 0
        self.prompt_source = ""
        self.prompt_hash = ""
        self.output = ""
        self.plain_text = False
        self.stable_hash = False

    def _node(self):
        return {"sources": [{"source_id": self.source,
                             "facts": self.facts,
                             "healthy": self.healthy,
                             "verified": self.verified}],
                "not_checked": self.not_checked}

    def path(self, dotted: str):
        node = self._node()
        parts = dotted.split(".")
        if not dotted.startswith("sources."):
            node = node["sources"][0]
        for part in parts:
            if isinstance(node, list):
                try:
                    node = node[int(part)]
                except (ValueError, IndexError):
                    return None
            elif isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        return node


def _apply_patches(monkeypatch, patches):
    for dotted, replacement in patches or ():
        module_name, _, attr = dotted.rpartition(".")
        module = __import__(module_name, fromlist=["*"])
        monkeypatch.setattr(module, attr, replacement)


async def _run_case(case, db, monkeypatch):
    _apply_patches(monkeypatch, case.get("patch"))
    kind = case["kind"]
    if kind == "probe":
        return await _run_probe(case, db)
    if kind == "inspect":
        return await _run_inspect(case, db, monkeypatch)
    if kind == "readback":
        return await _run_readback(case)
    if kind == "checkup":
        return await _run_checkup(case, monkeypatch)
    raise AssertionError(f"unknown case kind: {kind}")


async def _run_probe(case, db):
    observed = Observed()
    deps = dict(case.get("deps") or {})
    await _seed(case, db)
    collector = _collector(None if case.get("no_db") else deps.pop("db", db),
                           **deps)
    _bundle, page = await _collect(
        collector, case["probe"], chat_id=case.get("chat_id", CHAT_A),
        scope=case.get("scope", "current_chat"),
        arguments=case.get("arguments"))
    source = (page.get("sources") or [{}])[0]
    redaction = source.get("redaction") or {}
    observed.status = page.get("status") or ""
    observed.reason_code = page.get("reason_code") or source.get("reason_code") \
        or ""
    observed.source = source.get("source_id") or ""
    observed.facts = source.get("facts") or {}
    observed.not_checked = list(page.get("not_checked") or [])
    observed.verified = source.get("verified")
    observed.healthy = source.get("healthy")
    observed.redacted_fields = int(redaction.get("redacted_fields") or 0)
    observed.blob = json.dumps(page, ensure_ascii=False)
    return observed


async def _seed(case, db):
    seed = case.get("seed")
    if seed == "voice_failed":
        await _seed_voice(db, message_id=1, chat_id=CHAT_A, status="failed",
                          reason="stt_timeout")
        await _seed_voice(db, message_id=2, chat_id=CHAT_B, status="ready")
    elif seed == "voice_pending":
        await _seed_voice(db, message_id=3, chat_id=CHAT_A, status="pending")
        await _seed_voice(db, message_id=4, chat_id=CHAT_B, status="failed",
                          reason="other_chat_secret")
    elif seed == "incident":
        await mca_incidents.open_or_update(
            db, process_id="media", pipeline_type="voice", stage="stt",
            reason_code="stt_timeout", chat_id=CHAT_A)
        await mca_incidents.open_or_update(
            db, process_id="media", pipeline_type="voice", stage="tts",
            reason_code=FOREIGN_MARKER, chat_id=CHAT_B)


async def _run_inspect(case, db, monkeypatch):
    observed = Observed()
    collector = _collector(db)
    router = ToolRouter(ToolDeps(None, None, diagnostics=collector))
    ctx = ToolContext(CHAT_A, query="", bot=None, user_id=case["user_id"])
    raw = await router.dispatch("inspect_runtime", dict(case["arguments"]),
                                ctx)
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    observed.status = str(payload.get("status") or "")
    observed.reason_code = str(payload.get("reason_code") or "")
    observed.not_checked = list(payload.get("not_checked") or [])
    observed.blob = raw
    return observed


async def _run_readback(case):
    observed = Observed()
    role = case.get("role")
    bot = None
    if role == "admin":
        bot = FakeBot({(CHAT_A, ADMIN_A): "administrator"})
    elif role == "member":
        bot = FakeBot({(CHAT_A, MEMBER_A): "member"})
    chat_params.set_chat_params_cache(FakeChatStore(case.get("store")))
    outcome = await readback.prepare(
        case["arguments"], telegram_id=case["user_id"], chat_id=CHAT_A,
        cache=FakeRoleCache({ADMIN_A: "global_admin"}), bot=bot,
        secrets=case.get("secrets"))
    observed.status = outcome.status
    observed.reason_code = outcome.reason
    observed.redaction = outcome.metadata.get("redaction")
    observed.sent = len(bot.sent) if bot is not None else 0
    observed.plain_text = bool(bot is not None and all(
        message.get("parse_mode") is None for message in bot.sent))
    observed.blob = outcome.machine + "\n" + "\n".join(outcome.messages)
    if bot is not None:
        observed.blob += "\n" + "\n".join(
            message["text"] for message in bot.sent)
    return observed


async def _run_checkup(case, monkeypatch):
    observed = Observed()
    cache = FakeConfigCache({"prompts.checkup_system_prompt":
                             case["saved_prompt"]})
    monkeypatch.setattr(hot, "get_config_cache", lambda: cache)
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=case["llm_answer"])
    telemetry: dict = {}
    output = await CheckupService(llm).checkup(
        "пример логов", used_fallback=False, chat_id=CHAT_A,
        telemetry=telemetry)
    system = llm.generate.await_args.args[0][0]["content"]
    observed.status = "ok"
    observed.prompt_source = str(telemetry.get("prompt_source") or "")
    observed.prompt_hash = str(telemetry.get("prompt_hash") or "")
    observed.output = output
    observed.blob = system + "\n" + output
    llm2 = MagicMock()
    llm2.generate = AsyncMock(return_value=case["llm_answer"])
    second: dict = {}
    await CheckupService(llm2).checkup("другие логи", used_fallback=False,
                                       chat_id=CHAT_A, telemetry=second)
    observed.stable_hash = (second.get("prompt_hash") == observed.prompt_hash)
    return observed


# ── проверки ──────────────────────────────────────────────────────────────

def _check(case, observed):
    expect = case["expect"]
    cid = case["id"]
    if "status" in expect:
        assert observed.status == expect["status"], (
            f"{cid}: статус {observed.status!r} != {expect['status']!r}")
    if "reason_code" in expect:
        assert observed.reason_code == expect["reason_code"], (
            f"{cid}: причина {observed.reason_code!r} != "
            f"{expect['reason_code']!r}")
    if "source" in expect:
        assert observed.source == expect["source"], (
            f"{cid}: источник {observed.source!r} != {expect['source']!r}")
    if "verified" in expect:
        assert observed.verified is expect["verified"], (
            f"{cid}: verified={observed.verified!r}")
    for dotted, value in (expect.get("facts") or {}).items():
        assert observed.path(dotted) == value, (
            f"{cid}: {dotted}={observed.path(dotted)!r} != {value!r}")
    for dotted, value in (expect.get("honest_path") or {}).items():
        assert observed.path(dotted) == value, (
            f"{cid}: honest {dotted}={observed.path(dotted)!r} != {value!r}")
    for needle in expect.get("not_checked") or ():
        assert any(needle in str(item) for item in observed.not_checked), (
            f"{cid}: not_checked не содержит {needle!r}: "
            f"{observed.not_checked}")
    for needle in expect.get("absent") or ():
        assert needle not in observed.blob, (
            f"{cid}: в наблюдаемом ответе есть {needle!r}")
    for needle in expect.get("present") or ():
        assert needle in observed.blob, f"{cid}: нет {needle!r}"
    for needle in expect.get("required") or ():
        assert needle in observed.blob, f"{cid}: нет данных {needle!r}"
    for needle in expect.get("output_present") or ():
        assert needle in observed.output, f"{cid}: в выводе нет {needle!r}"
    if "redaction" in expect:
        assert observed.redaction == expect["redaction"], (
            f"{cid}: редакция {observed.redaction!r} != "
            f"{expect['redaction']!r}")
    if "redacted_min" in expect:
        assert observed.redacted_fields >= expect["redacted_min"], (
            f"{cid}: вырезано {observed.redacted_fields} < "
            f"{expect['redacted_min']}")
    if "sent" in expect:
        assert observed.sent == expect["sent"], (
            f"{cid}: отправлено {observed.sent} сообщений")
    if expect.get("stable_prompt_hash"):
        assert observed.stable_hash, f"{cid}: хеш промпта изменился"
    if expect.get("plain_text"):
        assert observed.plain_text, f"{cid}: доставка не plain text"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
@pytest.mark.asyncio
async def test_golden_case(case, db, monkeypatch):
    observed = await _run_case(case, db, monkeypatch)
    _check(case, observed)


def test_golden_dataset_shape_and_coverage():
    """≥25 случаев и покрытие всех пяти измерений AC-23."""
    assert len(CASES) >= 25, f"golden set: {len(CASES)} < 25"
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids)), "дубли id в golden set"
    categories = {case["category"] for case in CASES}
    assert {"known_cause", "irrelevant_commit", "insufficient_data",
            "wrong_role", "secret", "negative", "style"} <= categories
    dimensions: dict[str, int] = {}
    for case in CASES:
        for dimension in case["dimension"]:
            dimensions[dimension] = dimensions.get(dimension, 0) + 1
    for required in ("accuracy", "evidence", "hallucination", "scope",
                     "style"):
        assert dimensions.get(required, 0) >= 3, (
            f"измерение {required} покрыто {dimensions.get(required, 0)} раз")
    for case in CASES:
        expect = case["expect"]
        assert any(key in expect for key in
                   ("status", "reason_code", "facts", "present", "absent",
                    "output_present", "redacted_min")), case["id"]


def test_golden_dataset_is_anonymized():
    """В наборе нет реальных идентификаторов, ключей и прод-адресов."""
    blob = json.dumps(CASES, ensure_ascii=False, default=str)
    forbidden = (
        "5885953495",              # реальный owner id проекта
        "Henry-Case-dev",          # реальный repo origin
        "198.46.175.136",          # старый прод-VPS
        "192.255.209.205",         # действующий прод-VPS
        "SUPER-SECRET",            # маркер другого среза
        "1712345678:AA",           # форма реального bot token
    )
    for needle in forbidden:
        assert needle not in blob, f"в golden set реальное значение: {needle}"
    assert -1009000000002 <= CHAT_A <= -1009000000001
    assert -1009000000002 <= CHAT_B <= -1009000000001
    assert 7000000 <= ADMIN_A <= 7999999
    assert 7000000 <= MEMBER_A <= 7999999
    assert SYNTHETIC_TOKEN.startswith("sk-test-golden-")
