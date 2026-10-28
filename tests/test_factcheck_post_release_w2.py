"""P0-FACTCHECK-CORRECTIVE W2 (owner 28.10.2026) — FC-08 директива аналитика
+ §6.3 deferred cleanup (конфигурация/UI-остатки кеша готовых вердиктов).

Источник: plans/features/p0-factcheck-post-release/source-2026-10-28.md.

* §8 (FC-08) — дословная смысловая директива вставлена в СУЩЕСТВУЮЩИЙ
  Analyst System Prompt (`TEMPORAL_ANALYST_SYSTEM`, verdict-вызов аналитика —
  тот же payload-путь, куда W1 добавил <analysis_context>) ровно ОДИН раз:
  байт-в-байт с якорем source, и при evidence, и при пустом evidence;
  в fallback/validator/вербализатор не дублируется (§8: без дублирования
  одной и той же инструкции во всех слоях), без нового слоя/LLM-вызова;
* §6.3 (FC-06C) — отложенная W1 чистка: гейт `temporal_factcheck_cache_
  enabled` (K3), env `MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED`, мёртвые
  `TEMPORAL_FRESHNESS_*` (Settings + каталог) и slug-регистрация
  `factcheck_temporal` в SmartCache удалены; читателей в production-коде
  нет; сохранённые PG-значения удалённых настроек игнорируются безопасно
  (админка их не показывает, строка БД не трогается, POST — 422).

TEST-LIFECYCLE: CONTRACT owner=FC-08 (директива дословно, один носитель)
TEST-LIFECYCLE: REGRESSION owner=FC-06C (удалённые переключатели не
возвращаются; устаревшие сохранённые значения игнорируются безопасно)
"""
import asyncio
import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.factcheck_orchestrator as orch
import services.factcheck_planner as fsp
import services.temporal_factcheck as tf
from services.factcheck_service import FactCheckService

SOURCE = ROOT / "plans" / "features" / "p0-factcheck-post-release" / \
    "source-2026-10-28.md"
_ANCHOR_LINE = 600          # «Требуемая смысловая директива» (текст ниже)

CHAT_ID = -100777
TARGET_TG = 7700
TRIGGER_TG = 7701

CLAIM = ("⚡️ В чипе 96 линий PCIe: 40 от процессора и 56 от чипсета. "
         "Итого 96 линий у устройства.")


# ── Фейки (без сети/БД/LLM; паттерн W1) ─────────────────────────────────────

def _origin_row(text=CLAIM):
    return {"text": text, "caption": None, "origin_type": "channel",
            "origin_sent_at": None, "sent_at": 1792200000,
            "current_revision": None, "content_hash": None,
            "origin_sender_user_id": None, "origin_chat_id": -777,
            "origin_display_name": "Канал", "author_name": None,
            "forward_source": None}


class FakeDB:
    def __init__(self, origin_row=None):
        self._origin = origin_row or _origin_row()

    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(self._origin)

    async def get_media_assets_for_message(self, chat_id, tg):
        return []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return self._origin


class _JournalLLM:
    """LLM-фейк: журнал ВСЕХ сообщений (system+user) по шагам — для
    exactly-once-проверки директивы по всему payload вызова."""

    def __init__(self, verdict=None, text="Краткий вывод."):
        self.verdict = verdict or {"factual_verdict": "insufficient_evidence",
                                   "temporal_status": "unknown"}
        self.text = text
        self.steps: list[str] = []
        self.calls: list[tuple[str, list[dict]]] = []

    async def generate(self, messages, **kw):
        step = str(kw.get("step"))
        self.steps.append(step)
        self.calls.append((step, [dict(m) for m in messages]))
        if step in ("temporal_verdict", "temporal_fallback"):
            return json.dumps(self.verdict, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps({"agree": True}, ensure_ascii=False)
        return self.text

    def messages_of(self, step):
        for s, msgs in self.calls:
            if s == step:
                return msgs
        return None

    def directive_occurrences(self, directive: str) -> int:
        """Сколько раз директива встречается во ВСЕХ сообщениях прогона."""
        return sum(str(m.get("content") or "").count(directive)
                   for _s, msgs in self.calls for m in msgs)


class DownAggregator:
    """Все провайдеры недоступны (транспортная ошибка каскада)."""

    async def search(self, q, max_symbols):
        from services.search_aggregator import AllSearchEnginesFailedException
        raise AllSearchEnginesFailedException(
            "all search engines failed (tavily → exa → ddg)",
            reason="provider_error")

    async def search_relevant(self, q, max_symbols, **kw):
        await self.search(q, max_symbols)


async def _envelope(text=CLAIM):
    env, _ = await tf.build_envelope(
        FakeDB(), tf.InputRef(kind="reply", chat_id=CHAT_ID,
                              target_tg_message_id=TARGET_TG,
                              trigger_tg_message_id=TRIGGER_TG))
    return env


def _outcome(**kw):
    base = dict(evidence_map=None, search_text="", queries_attempted=1,
                queries_used=0, refs_collected=0, fetch_errors=0,
                budget_exhausted=False, provider_failures=0,
                empty_results=0, irrelevant_results=0)
    base.update(kw)
    return fsp.RetrievalOutcome(**base)


def _evidence_map(*refs):
    return orch.EvidenceMap(
        refs=tuple(refs), allowlist=tuple(r.evidence_id for r in refs))


def _ref(eid="ev-1", url="https://example.org/a",
         support="Публикация подтверждает утверждение"):
    return orch.EvidenceRef(eid, url, support)


def _source_directive() -> str:
    """Текст директивы байт-в-байт из якоря source (строка 600, в кавычках)."""
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    line = lines[_ANCHOR_LINE - 1].strip()
    assert line.startswith('"') and line.endswith('"'), "якорь сместился"
    return line[1:-1]


# ── §8 (FC-08): дословная директива, ровно один носитель ────────────────────

class TestFC08AnalystDirective:
    def test_byte_identity_to_source_anchor(self):
        """Директива в коде байт-в-байт равна тексту из source §8."""
        assert tf.ANALYST_DIRECTIVE == _source_directive()
        assert len(tf.ANALYST_DIRECTIVE) > 0

    def test_exactly_once_in_analyst_system_prompt(self):
        """Единственный носитель — TEMPORAL_ANALYST_SYSTEM; в fallback/
        validator-промптах директивы нет (§8: без дублирования по слоям)."""
        assert tf.TEMPORAL_ANALYST_SYSTEM.count(
            tf.ANALYST_DIRECTIVE) == 1
        assert tf.ANALYST_DIRECTIVE not in tf._TEMPORAL_FALLBACK_SYSTEM
        assert tf.ANALYST_DIRECTIVE not in tf.TEMPORAL_VALIDATOR_SYSTEM

    @pytest.mark.asyncio
    async def test_directive_in_payload_with_evidence(self):
        """Путь С доказательствами: analyst-вызов получает директиву ровно
        один раз (system), user-payload её не дублирует; ни validator, ни
        вербализатор её не содержат."""
        outcome = _outcome(
            queries_attempted=1, queries_used=1, refs_collected=1,
            search_text="выдача", evidence_map=_evidence_map(_ref()))
        llm = _JournalLLM()
        run = await FactCheckService(aggregator=None,
                                     llm=llm).check_claim_envelope(
            await _envelope(), retrieval=outcome)
        assert run.verdict is not None
        msgs = llm.messages_of("temporal_verdict")
        assert msgs is not None and msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[0]["content"].count(tf.ANALYST_DIRECTIVE) == 1
        assert msgs[1]["content"].count(tf.ANALYST_DIRECTIVE) == 0
        assert "<evidence>" in msgs[1]["content"]
        assert llm.directive_occurrences(tf.ANALYST_DIRECTIVE) == 1

    @pytest.mark.asyncio
    async def test_directive_in_payload_empty_evidence(self):
        """Путь БЕЗ доказательств (W1: анализ продолжается) — та же директива
        в том же system-payload, ровно один раз; <analysis_context> не
        вытесняет её."""
        llm = _JournalLLM()
        run = await FactCheckService(aggregator=DownAggregator(),
                                     llm=llm).check_claim_envelope(
            await _envelope())
        assert llm.steps.count("temporal_verdict") == 1
        msgs = llm.messages_of("temporal_verdict")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"].count(tf.ANALYST_DIRECTIVE) == 1
        assert "<analysis_context>" in msgs[1]["content"]
        assert msgs[1]["content"].count(tf.ANALYST_DIRECTIVE) == 0
        # вся полезная нагрузка прогона (включая validator/verbalize) —
        # директива ровно один раз, дублей по слоям нет
        assert llm.directive_occurrences(tf.ANALYST_DIRECTIVE) == 1

    @pytest.mark.asyncio
    async def test_no_extra_llm_call_added(self):
        """Директива не создаёт нового слоя/вызова: профиль шагов тот же,
        что до неё (analyst → validator → verbalize; fallback только при
        невалидном JSON)."""
        outcome = _outcome(
            queries_attempted=1, queries_used=1, refs_collected=1,
            search_text="выдача", evidence_map=_evidence_map(_ref()))
        llm = _JournalLLM()
        await FactCheckService(aggregator=None, llm=llm).check_claim_envelope(
            await _envelope(), retrieval=outcome)
        assert llm.steps == ["temporal_verdict", "temporal_validator",
                             "temporal_verbalize"]


# ── §6.3 (FC-06C): deferred cleanup ─────────────────────────────────────────

class TestFC06CCacheCleanup:
    def test_cache_gate_function_removed(self):
        """Гейт K3 удалён: ни функции, ни записи в реестре kill-switch."""
        from services import mca_gates
        assert not hasattr(mca_gates, "temporal_factcheck_cache_enabled")
        assert "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED" \
            not in mca_gates.KILL_SWITCHES

    def test_env_setting_removed(self):
        """Env-переменная больше не регистрируется в Settings."""
        from config.settings import Settings
        names = {f.name for f in dataclasses.fields(Settings)}
        assert "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED" not in names
        assert "TEMPORAL_FRESHNESS_CURRENT_TTL_HOURS" not in names
        assert "TEMPORAL_FRESHNESS_HISTORICAL_TTL_HOURS" not in names

    def test_ttl_params_removed_from_catalog(self):
        """Мёртвые TTL-ключи удалены из каталога (UI-тумблеров больше нет)."""
        from services import param_catalog as pc
        assert "TEMPORAL_FRESHNESS_CURRENT_TTL_HOURS" not in pc.REGISTRY
        assert "TEMPORAL_FRESHNESS_HISTORICAL_TTL_HOURS" not in pc.REGISTRY
        temporal = {s.pg_key for s in pc.REGISTRY.values()
                    if s.category == pc.CATEGORY_TEMPORAL}
        assert "temporal.freshness_current_ttl_hours" not in temporal
        assert "temporal.freshness_historical_ttl_hours" not in temporal

    def test_smart_cache_slug_removed(self):
        """Slug-регистрация `factcheck_temporal` снята; SmartCache жив для
        остальных слагов (нового механизма кеша взамен не введено)."""
        from services.smart_cache import _NORMALIZERS, build_key
        assert "factcheck_temporal" not in _NORMALIZERS
        build_key("factcheck", "ok")
        build_key("search", "ok")

    def test_process_registry_no_dead_cache_refs(self):
        """Реестр процессов не ссылается на удалённые настройки и не
        объявляет мёртвые cache-ветки."""
        from services import mca_process_registry as pr
        proc = pr.get_process("temporal.factcheck")
        assert proc is not None
        assert "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED" not in proc.settings_ref
        assert not any(s.startswith("TEMPORAL_FRESHNESS")
                       for s in proc.settings_ref)
        assert "cache_hit" not in proc.branches
        assert "cache_bypass" not in proc.recovery_ops

    def test_module_registry_axis_dropped(self):
        """Ось удалённого гейта убрана из MODULE_ENV_GATES (покрытие M2
        остаётся полным в обе стороны)."""
        from services import mca_gates, module_registry as mr
        axis = mr.MODULE_ENV_GATES["factcheck_temporal"]
        assert "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED" not in axis
        owned = set(mr.MODULE_ENV_GATES.get("factcheck_temporal", ()))
        assert owned <= set(mca_gates.KILL_SWITCHES)


class _SettingsConn:
    """Мини-PG-conn с семантикой bot_settings (паттерн B07-теста)."""

    def __init__(self, rows=()):
        self.rows = {r["key"]: dict(r) for r in rows}

    async def execute(self, sql, *args):
        raise AssertionError("тест не должен писать в bot_settings")

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return list(self.rows.values())
        return []


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        outer = self

        class _CM:
            async def __aenter__(self):
                return outer._conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _Pg:
    def __init__(self, conn):
        self.pool = _Pool(conn)


class TestFC06CDeprecatedStoredValues:
    """§6.3: «Устаревшие настройки и данные должны обрабатываться безопасно
    при обновлении» — сохранённая PG-строка удалённой настройки (сид
    round 10.44) игнорируется, БД не трогается."""

    def test_stored_removed_setting_ignored_db_untouched(self):
        from services.config_cache import ConfigCache, _REMOVED_SETTING_KEYS
        assert _REMOVED_SETTING_KEYS == frozenset((
            "temporal.freshness_current_ttl_hours",
            "temporal.freshness_historical_ttl_hours"))
        conn = _SettingsConn(rows=[
            {"key": "temporal.freshness_current_ttl_hours", "value": 6,
             "category": "temporal", "updated_at": "2026-01-01"},
            {"key": "temporal.freshness_historical_ttl_hours", "value": 720,
             "category": "temporal", "updated_at": "2026-01-01"},
            {"key": "temporal.tool_enabled", "value": True,
             "category": "temporal", "updated_at": "2026-01-02"},
        ])
        cache = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
        asyncio.run(cache._load_all())
        snapshot = cache.get_all()
        # удалённые настройки не отдаются (админка не показывает мёртвые
        # тумблеры), живой ключ рядом — работает
        assert "temporal.freshness_current_ttl_hours" not in snapshot
        assert "temporal.freshness_historical_ttl_hours" not in snapshot
        assert snapshot["temporal.tool_enabled"] is True
        # sync-чтение тоже игнорирует удалённые ключи
        assert cache.get("temporal.freshness_current_ttl_hours",
                         "MISSING") == "MISSING"
        assert cache.get("temporal.tool_enabled") is True
        # строка БД НЕ удалена (обработка безопасна/обратима)
        assert "temporal.freshness_current_ttl_hours" in conn.rows
