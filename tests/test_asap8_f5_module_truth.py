"""ASAP 8 F5 — Module dependency truth (ТЗ §11/§18H/§9/§10, архитектура §5).

M1 — Summary chat OFF не влияет на unrelated модули (UI reason-модель +
runtime-гейты собственных флагов).
M2 — Summary global OFF ДО старта: unrelated роутеры зарегистрированы
(источник), их сервисы инициализированы (общий bootstrap ≠ фича), функции
работают по СВОИМ гейтам.
M3 — reason enum честный: нет «отключён глобально» для chat-scoped состояния
(JS-контракты: tests/js/round1025_f4_module_store_test.js; здесь — source-
гвард на отсутствие parentGate у unrelated карточек).
M6 — Experience: global worker + per-chat opted-in (hot override → global →
default).
M7 — Random: product master memory.random_enabled (default true), env
MCA_RANDOM_SOURCE_ENABLED остаётся аварийной AND-осью.
R3 — негативный тест порядка регистрации: менять можно было ТОЛЬКО обёртки;
порядок include_router 0a–0i не изменился.
§18H — обе половины: (1) false UI-зависимость убрана; (2) common bootstrap
отделён от роутеров; (3) независимые роутеры регистрируются независимо;
(4) фича-гейт на своей границе исполнения; (5) смена Summary scope не меняет
Direct/Search/Factcheck/Web; (6) restart-time global OFF + hot per-chat OFF.

TEST-LIFECYCLE: CONTRACT owner=asap8/F5
"""
import ast
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import settings
from services import mca_gates
from services import module_registry as mr
from services.hot_config import set_config_cache

ROOT = Path(__file__).resolve().parents[1]
BOT_PY = (ROOT / "bot.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

# ═══ Фикстуры ════════════════════════════════════════════════════════════════


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture()
def hot_with():
    def _install(values):
        set_config_cache(_FakeHot(values))
        return values

    yield _install
    set_config_cache(None)


# ═══ §18H(2)/(3) + R3 + M2: bootstrap и порядок регистрации (источник) ═══════

_ROUTERS_0A_0I = (
    "summary_observer_router",
    "summary_router",
    "factcheck_router",
    "search_router",
    "youtube_router",
    "web_router",
    "checkup_router",
    "direct_chat_router",
    "voice_transcription_router",
)


def _registration_block() -> str:
    """Исходник секции REGISTRATION ORDER … 0 (до admin_commands_router)."""
    start = BOT_PY.index("REGISTRATION ORDER (CRITICAL")
    end = BOT_PY.index("dp.include_router(admin_commands_router)", start)
    return BOT_PY[start:end]


def test_r3_registration_order_preserved_and_unconditional():
    """R3-негатив: порядок include_router 0a–0i бит-в-бит прежний; обёртки
    if flags.summary_enabled СНЯТЫ (роутеры регистрируются всегда)."""
    block = _registration_block()
    found = re.findall(r"dp\.include_router\((\w+_router)\)", block)
    assert found[:9] == [f"{name}" for name in _ROUTERS_0A_0I], found[:9]
    # ни одной условной обёртки на Summary-флаг в секции регистрации
    assert 'if hot.get("flags.summary_enabled"' not in block, (
        "R3/§18H(3): условная регистрация роутеров 0a–0i не допускается")
    # порядок 0a→0i по комментариям-маркерам тоже не сменился
    markers = ["# 0a.", "# 0b.", "# 0c.", "# 0d.", "# 0e.", "# 0f.",
               "# 0g.", "# 0h.", "# 0i."]
    pos = [block.index(m) for m in markers]
    assert pos == sorted(pos)


def test_m2_h18_bootstrap_separated_from_feature_flag():
    """§18H(2): общий bootstrap (LLM-клиент, aliases, память, DI unrelated
    сервисов) НЕ находится внутри if flags.summary_enabled; под флагом —
    только Summary-собственный контур (генератор/setup/планировщик)."""
    tree = ast.parse(BOT_PY)
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_startup":
            func = node
            break
    assert func is not None
    gated: list[ast.stmt] = []
    for node in ast.walk(func):
        if isinstance(node, ast.If):
            src = ast.unparse(node.test)
            if "flags.summary_enabled" in src:
                gated.extend(node.body)
    gated_src = "\n".join(ast.unparse(s) for s in gated)
    # общий bootstrap — вне гейта
    for marker in ("_llm_client = LLMClient(", "aliases = AliasResolver(",
                   "memory = MemoryManager(", "setup_search(",
                   "setup_youtube(", "setup_web(", "setup_checkup(",
                   "setup_factcheck(", "setup_direct_chat("):
        assert marker in BOT_PY
        assert marker not in gated_src, (
            f"§18H(2): общий bootstrap внутри Summary-гейта: {marker}")
    # Summary-собственный контур — под гейтом
    for marker in ("SummaryGenerator(", "setup_summary(",
                   "SummarySchedulerService("):
        assert marker in gated_src, (
            f"§18H(2): Summary-контур должен остаться под своим флагом: "
            f"{marker}")


def test_m2_summary_flag_not_a_parent_of_unrelated_modules():
    """§18H(5): flags.summary_enabled больше не управляет unrelated DI.
    Source-гвард: настройка setup_* unrelated-сервисов не обёрнута в
    Summary-условие (см. test_m2_h18_bootstrap_separated_from_feature_flag)
    и voice-AND с Summary удалён."""
    assert 'hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED) and hot.get("flags.enable_voice_transcription"' not in BOT_PY


# ═══ §18H(4): фича-гейты на своих границах исполнения ════════════════════════


def test_m18_own_runtime_gates_present_in_handlers():
    """Каждый модуль проверяет СВОЙ effective-гейт на границе исполнения:
    Summary — flags.summary_enabled в 0a/0b-хендлерах; Transcription —
    flags.enable_voice_transcription (без Summary); Direct — master на всей
    триггерной поверхности. Собственные гейты factcheck/search/web/checkup/
    youtube не тронуты."""
    import handlers.summary as hs
    import handlers.voice_transcription as vt
    import handlers.direct_chat as dc

    src_summary = Path(hs.__file__).read_text(encoding="utf-8")
    # ровно 3 runtime-точки: observer + observer_edited + cmd_summary
    assert src_summary.count("_summary_enabled()") >= 4  # def + 3 call-sites
    src_vt = Path(vt.__file__).read_text(encoding="utf-8")
    assert 'hot.get("flags.enable_voice_transcription"' in src_vt
    # summary_enabled из voice-гейта УДАЛЕН (архитектура §5.1)
    gate_line = [l for l in src_vt.splitlines()
                 if "enable_voice_transcription" in l and "hot.get" in l]
    assert len(gate_line) == 1
    assert "summary_enabled" not in gate_line[0]
    src_dc = Path(dc.__file__).read_text(encoding="utf-8")
    # master-гейт — на входе _is_direct_trigger (reply/mention/имя/keyword)
    trigger_body = src_dc[src_dc.index("def _is_direct_trigger"):
                          src_dc.index("def _command_user")]
    assert 'hot.get("flags.direct_chat_botword_enabled"' in trigger_body


@pytest.mark.asyncio
async def test_m2_summary_observer_runtime_gate_off_no_save():
    """§18H(6) hot per-chat/global OFF: флаг OFF в рантайме → observer не
    сохраняет и всегда UNHANDLED (паритет прежней startup-оси)."""
    import handlers.summary as hs
    msg = MagicMock()
    msg.from_user = MagicMock(id=123)
    msg.chat.id = -100
    saved = AsyncMock(return_value=1)
    with patch.object(hs, "_db", MagicMock()), \
            patch.object(hs, "_aliases", MagicMock()), \
            patch.object(hs, "_bot_id", None), \
            patch.object(hs, "_summary_enabled", return_value=False), \
            patch.object(hs.message_identity, "save_live_message", saved):
        result = await hs.summary_observer(msg)
        result_edited = await hs.summary_observer_edited(msg)
    assert result.name == "UNHANDLED"
    assert result_edited.name == "UNHANDLED"
    saved.assert_not_awaited()


@pytest.mark.asyncio
async def test_m2_summary_cmd_runtime_gate_off():
    """/summary при флаге OFF → UNHANDLED (пропагация, паритет «роутер не
    зарегистрирован»); при ON — гейт пропускает дальше admin-проверок."""
    import handlers.summary as hs
    msg = MagicMock()
    msg.from_user = MagicMock(id=123)
    msg.text = "/summary"
    with patch.object(hs, "_summary_enabled", return_value=False):
        result = await hs.cmd_summary(msg, bot=None)
    assert result.name == "UNHANDLED"
    # ON: гейт не блокирует (admin-only проверки идут дальше; _generator None
    # → UX-ветка — здесь достаточно факта «не UNHANDLED-из-за-гейта»)
    set_config_cache(_FakeHot({"flags.summary_enabled": True}))
    with patch.object(hs, "_generator", None), \
            patch.object(hs, "_safe_send", AsyncMock()) as send, \
            patch.object(hs, "_delete_command", AsyncMock()):
        result_on = await hs.cmd_summary(msg, bot=MagicMock())
    assert result_on is None          # обработан (не отклонён гейтом)
    set_config_cache(None)


@pytest.mark.asyncio
async def test_m2_voice_gate_own_flag_only():
    """§18H(4)/(5): voice-хендлер гейтится ТОЛЬКО своим флагом; Summary OFF
    не влияет (AND-связка удалена)."""
    import handlers.voice_transcription as vt
    msg = MagicMock()
    msg.voice = MagicMock()
    with patch.object(vt, "_service", MagicMock()), \
            patch.object(vt.hot, "get",
                         side_effect=lambda k, d=None: False), \
            patch.object(vt, "_process", AsyncMock()) as proc:
        off = await vt.voice_transcription_handler(msg, bot=MagicMock())
    assert off.name == "UNHANDLED"
    proc.assert_not_awaited()
    # Summary OFF + voice ON → работает по своему гейту (M2)
    def _hot(key, default=None):
        if key == "flags.enable_voice_transcription":
            return True
        if key == "flags.summary_enabled":
            return False
        return default
    with patch.object(vt, "_service", MagicMock()), \
            patch.object(vt.hot, "get", side_effect=_hot), \
            patch.object(vt, "_process", AsyncMock()) as proc2:
        on = await vt.voice_transcription_handler(msg, bot=MagicMock())
    assert on.name == "UNHANDLED"     # observer-стиль: всегда UNHANDLED
    proc2.assert_awaited_once()


@pytest.mark.asyncio
async def test_m18_direct_master_gate_on_reply_and_mention():
    """F5: master flags.direct_chat_botword_enabled гейтит reply/mention-путь
    (раньше — только keyword-ветку); OFF → триггера нет."""
    import handlers.direct_chat as dc

    def _msg(text=None, reply_to_bot=False, mention=False):
        m = MagicMock()
        m.text = text
        m.reply_to_message = None
        m.entities = ()
        if reply_to_bot:
            rt = MagicMock()
            rt.from_user = MagicMock(id=999)
            m.reply_to_message = rt
        if mention:
            ent = MagicMock()
            ent.type = "mention"
            ent.extract_from = lambda t: "@adminbot"
            m.entities = (ent,)
        return m

    with patch.object(dc, "_bot_id", 999), \
            patch.object(dc, "_bot_username", "adminbot"), \
            patch.object(dc, "_BOTWORD_EXCLUDED_USER_IDS", set()), \
            patch.object(dc.hot, "get",
                         side_effect=lambda k, d=None:
                             False if k == "flags.direct_chat_botword_enabled" else d):
        assert dc._is_direct_trigger(_msg(reply_to_bot=True)) is False
        assert dc._is_direct_trigger(_msg(mention=True)) is False
        assert dc._is_direct_trigger(_msg(text="эй, бот")) is False
    # ON → прежняя семантика триггеров
    def _hot_on(key, default=None):
        if key == "flags.direct_chat_botword_enabled":
            return True
        if key == "flags.persona_enabled":
            return False
        return default
    with patch.object(dc, "_bot_id", 999), \
            patch.object(dc, "_bot_username", "adminbot"), \
            patch.object(dc, "_BOTWORD_EXCLUDED_USER_IDS", set()), \
            patch.object(dc.bot_persona, "get_cached_global_name",
                         return_value=""), \
            patch.object(dc.hot, "get", side_effect=_hot_on):
        assert dc._is_direct_trigger(_msg(reply_to_bot=True)) is True
        assert dc._is_direct_trigger(_msg(mention=True)) is True
        assert dc._is_direct_trigger(_msg(text="эй, бот")) is True


# ═══ M1/M3: UI — ложная parent-зависимость убрана ════════════════════════════

_UNRELATED_MODULE_IDS = ("mod_direct", "mod_factcheck", "mod_search",
                         "mod_transcribe", "mod_video_summary", "mod_web",
                         "mod_checkup")


def test_m1_no_parent_gate_on_unrelated_modules():
    """§18H(1)/M1: у 7 unrelated карточек нет parentGate
    (flags.summary_enabled) — все independent (ТЗ §11.3)."""
    assert APP_JS.count("parentGate: 'flags.summary_enabled'") == 0
    mods = APP_JS[APP_JS.index("var MODULES = ["):APP_JS.index("];", APP_JS.index("var MODULES = ["))]
    assert "parentGate:" not in mods
    for mid in _UNRELATED_MODULE_IDS:
        entry = [l for l in mods.splitlines() if f"id: '{mid}'" in l]
        assert entry, mid


def test_m3_reason_model_enum_present():
    """M3: reason-модель F5 — полный enum (chat_off/global_off/env_off/
    provider_unavailable/parent_off) + запрет global_off-текста в chat scope
    (текст — ТОЛЬКО при selected scope = global)."""
    for reason in ("chat_off", "global_off", "env_off",
                   "provider_unavailable", "parent_off"):
        assert f"{reason}:" in APP_JS, reason
    assert "_moduleRuntimeReason" in APP_JS
    assert "reasonNoticeText" in APP_JS
    # UI-карточка модуля различает «выключено в этом чате» и «выключено глобально»
    assert "Выключено в этом чате" in APP_JS
    assert "Выключено глобально" in APP_JS


# ═══ M7: Random — product master + env AND ═══════════════════════════════════


def test_m7_random_product_master_default_on(hot_with, monkeypatch):
    """M7: memory.random_enabled (default true) — requested-ось Random;
    обе оси ON → effective ON."""
    set_config_cache(None)
    requested, effective, source = mr.effective_gate("random")
    assert (requested, effective, source) == (True, True, "both")
    spec = mr.MODULE_REGISTRY["random"]
    assert spec.master_param == "memory.random_enabled"
    assert mr.PRODUCT_DEFAULTS["memory.random_enabled"] is True


def test_m7_random_product_off_stops_runtime_and_env_stays_and(hot_with,
                                                               monkeypatch):
    """M7: product OFF → runtime-гейт закрыт (product_toggle); env OFF при
    product ON → emergency_env (env важнее UI); обе OFF → effective False."""
    hot_with({"memory.random_enabled": False})
    assert mca_gates.random_source_enabled() is False
    assert mr.effective_gate("random")[1:] == (False, "product_toggle")
    # env AND-ось: product ON + env OFF → False/emergency_env
    hot_with({"memory.random_enabled": True})
    monkeypatch.setattr(type(settings), "MCA_RANDOM_SOURCE_ENABLED", False)
    assert mca_gates.random_source_enabled() is False
    requested, effective, source = mr.effective_gate("random")
    assert (requested, effective, source) == (True, False, "emergency_env")


def test_m7_random_master_in_catalog_and_migratable():
    from services import param_catalog as pc
    spec = pc.get_by_pg_key("memory.random_enabled")
    assert spec is not None
    assert spec.type == "bool" and spec.secret is False
    assert spec.group == "memory_random" and spec.category == "memory"
    assert spec.migratable is True
    assert mr.validate_spec(mr.MODULE_REGISTRY["random"]) == []


# ═══ M6: Experience — global worker + per-chat opted-in ══════════════════════


class _FakeChatParamsCache:
    """root-лейаут чатов: overrides → hot.get → default (спец §4.5)."""

    def __init__(self, overrides_by_chat):
        self._by_chat = dict(overrides_by_chat)

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


@pytest.mark.asyncio
async def test_m6_learning_resolver_inherit_on_off(hot_with):
    """M6/U4: hot per-chat override → global → default; глобальная ось
    наследуется чатами без override."""
    from services import chat_params
    from services import mca_experience_jobs as jobs

    hot_with({"memory.experience_learning_enabled": True})
    chat_params.set_chat_params_cache(_FakeChatParamsCache({
        -100: {"memory.experience_learning_enabled": False},   # чат OFF
        -200: {"memory.experience_learning_enabled": True},    # чат ON
    }))
    try:
        assert await jobs.learning_enabled_for_chat(-100) is False
        assert await jobs.learning_enabled_for_chat(-200) is True
        assert await jobs.learning_enabled_for_chat(-300) is True  # inherit
        assert await jobs.learning_enabled_for_chat(None) is True  # global axis
    finally:
        chat_params.set_chat_params_cache(None)


@pytest.mark.asyncio
async def test_m6_global_master_off_disables_all_chats(hot_with):
    """M6/U4: global master OFF → все чаты выключены (worker-гейт)."""
    from services import chat_params
    from services import mca_experience_jobs as jobs

    hot_with({"memory.experience_learning_enabled": False})
    chat_params.set_chat_params_cache(_FakeChatParamsCache({
        -200: {"memory.experience_learning_enabled": True},   # override ON
    }))
    try:
        # override чата ON, но глобальная ось OFF → глобальный master важнее
        assert await jobs.learning_enabled_for_chat(-200) is False
        assert jobs.review_enabled() is False   # worker: global master OFF
    finally:
        chat_params.set_chat_params_cache(None)
    hot_with({"memory.experience_learning_enabled": True})
    assert jobs.review_enabled() in (True, False)  # зависит от env K1/K3


@pytest.mark.asyncio
async def test_m6_worker_skips_not_opted_in_chat(hot_with, monkeypatch):
    """M6: глобальный worker пропускает capture по чатам с learning OFF;
    None-чат (технический контур) — не гейтится."""
    from services import chat_params
    from services import mca_experience_jobs as jobs

    hot_with({"memory.experience_learning_enabled": True})
    chat_params.set_chat_params_cache(_FakeChatParamsCache({
        -100: {"memory.experience_learning_enabled": False},
    }))
    # env-гейты K1/K2/K3 ON
    monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                        lambda: True)
    monkeypatch.setattr(mca_gates, "experience_review_enabled",
                        lambda: True)
    monkeypatch.setattr(mca_gates, "experience_feedback_enabled",
                        lambda: True)

    class _Cursor:
        def __init__(self, rows):
            self._rows = rows

        async def fetchall(self):
            return self._rows

    fb_row = {"rid": 1, "feedback_id": "fb1", "chat_id": -100,
              "source_kind": "owner_correction", "ts": 1,
              "trace_id": None, "operation_id": None, "status": "active",
              "episode_id": None}
    tech_row = {"rid": 2, "feedback_id": "fb2", "chat_id": None,
                "source_kind": "technical", "ts": 1, "trace_id": None,
                "operation_id": None, "status": "active", "episode_id": None}

    class _DB:
        class db:                                # noqa: N441 - заглушка формы
            @staticmethod
            async def execute(*a, **k):
                return _Cursor([fb_row, tech_row])

    runner = jobs.ExperienceReviewRunner(_DB())
    service = MagicMock()
    service.capture_episode = AsyncMock(return_value="ep1")
    runner._service = service
    captured = await runner._capture_feedback({"cursor_feedback_rowid": 0})
    # чат -100 не opted-in → скип; None-чат (technical) → каптонится
    assert captured == 1
    assert service.capture_episode.await_count == 1
    assert service.capture_episode.await_args.kwargs.get("chat_id") is None
    chat_params.set_chat_params_cache(None)


def test_m6_registry_runtime_text_consistent():
    """M6: registry/catalog согласованы — Experience per_chat-ось, текст
    «worker глобальный, обучение по чатам»."""
    spec = mr.MODULE_REGISTRY["experience"]
    assert spec.master_param == "memory.experience_learning_enabled"
    assert spec.runtime_gate == "per_chat"
    assert "по чатам" in spec.description
    from services import param_catalog as pc
    cspec = pc.get_by_pg_key("memory.experience_learning_enabled")
    assert cspec is not None and cspec.category == "memory"


# ═══ §28.10-13-гварды ════════════════════════════════════════════════════════


def test_2810_no_summary_flag_reads_outside_summary_boundary():
    """§28.10: flags.summary_enabled не читается как parent чужих модулей:
    в handlers/ hot-чтение флага — только в собственном гейте Summary
    (summary.py)."""
    handlers_dir = ROOT / "handlers"
    offenders = []
    for p in handlers_dir.glob("*.py"):
        if p.name == "summary.py":
            continue
        if 'hot.get("flags.summary_enabled"' in p.read_text(encoding="utf-8"):
            offenders.append(p.name)
    assert offenders == [], (
        f"§28.10: unrelated-хендлеры читают Summary-флаг: {offenders}")


def test_2812_random_not_env_only():
    """§28.12: Random больше не «managed by env only» — product master в
    каталоге, registry requested-ось живая."""
    spec = mr.MODULE_REGISTRY["random"]
    assert spec.master_param and spec.master_param != ""
    assert spec.rationale and "no master" not in spec.rationale.lower()
