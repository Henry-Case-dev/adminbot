import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def _reset_global_persona_name():
    """Изоляция sync-кэша глобального имени персоны (раунд 10.15, F6).

    Префикс функциональных команд и триггер direct_chat читают
    ``bot_persona.get_cached_global_name()`` (sync). Без сброса тесты,
    сохраняющие персону (``test_bot_persona``), оставляют кэш непустым и
    ломают дефолтные «Бот, …»-кейсы ниже по файлам. Сброс до и восстановление
    после каждого теста — изоляция без изменения продового кода."""
    from services import bot_persona
    previous = bot_persona.get_cached_global_name()
    bot_persona.set_global_name_cache("")
    yield
    bot_persona.set_global_name_cache(previous)


@pytest.fixture(autouse=True)
def _system2_flags_off_by_default(request, monkeypatch):
    """Изоляция раунда 10.22 (F3–F6): старые тесты (без маркера ``system2``)
    идут ровно по одиночному пути 10.21 (флаги OFF). Тесты новой функциональности
    помечаются ``@pytest.mark.system2`` и работают с прод-дефолтами (ON).

    Патчим ClassVar на ВСЕХ ``Settings``-классах, на которые ссылаются сервисы
    (часть тестов делает ``importlib.reload(config.settings)`` и создаёт новый
    класс — иначе патч класса не долетел бы до старого инстанса).
    """
    if request.node.get_closest_marker("system2") is not None:
        return
    from config.settings import Settings
    import services.direct_chat_service as _dcs
    import services.factcheck_service as _fs
    import services.negative_constraints as _nc
    import services.summary_generator as _sg
    classes = {Settings, type(_dcs.settings), type(_fs.settings),
               type(_nc.settings), type(_sg.settings)}
    for _cls in classes:
        for _name in (
            "SYSTEM2_FACTCHECK_ENABLED",
            "SYSTEM2_SUMMARY_ENABLED",
            "SYSTEM2_DIRECT_ENABLED",
            "SYSTEM2_VALIDATOR_LOOP_ENABLED",
            "TELEGRAM_SEND_GUARD_ENABLED",
        ):
            if hasattr(_cls, _name):
                monkeypatch.setattr(_cls, _name, False)




@pytest.fixture(autouse=True)
def _asap3_flags_off_by_default(request, monkeypatch):
    """Изоляция ASAP-3 (round 1028, ADR-1028-2 D10): старые тесты (без
    маркера ``asap3``) идут ровно по прежнему контекст-пути и ack-поведению
    (kill-switch'и OFF — байт-в-байт baseline; parity-контракт спеки §3.3).
    Тесты новой функциональности помечаются ``@pytest.mark.asap3`` и работают
    с прод-дефолтами (ON), точечно доопределяя флаги сценарием.

    Патчим ClassVar на ВСЕХ ``Settings``-классах (прецедент
    ``_system2_flags_off_by_default``: часть тестов перезагружает settings)."""
    if (request.node.get_closest_marker("asap3") is not None
            or request.node.get_closest_marker("asap31") is not None
            or request.node.get_closest_marker("asap32") is not None):
        return
    from config.settings import Settings
    import services.direct_chat_service as _dcs
    import services.direct_context_composer as _dcomp
    import services.model_capacity as _mcap
    classes = {Settings, type(_dcs.settings), type(_dcomp.settings),
               type(_mcap.settings)}
    for _cls in classes:
        for _name in (
            "DIRECT_CONTEXT_COMPOSER_ENABLED",
            "DIRECT_SILENT_ACK_ENABLED",
        ):
            if hasattr(_cls, _name):
                monkeypatch.setattr(_cls, _name, False)


@pytest.fixture(autouse=True)
def _asap31_flags_off_by_default(request, monkeypatch):
    """Изоляция ASAP-3.1 (round 1028, ADR-1028-3): старые тесты (без маркера
    ``asap31``) идут по прежним бюджетным путям (kill-switch'и OFF —
    байт-в-байт baseline). Тесты новой функциональности помечаются
    ``@pytest.mark.asap31`` и работают с прод-дефолтами (ON), точечно
    доопределяя флаги сценарием. Прецедент — ``_asap3_flags_off_by_default``."""
    if (request.node.get_closest_marker("asap31") is not None
            or request.node.get_closest_marker("asap3") is not None
            or request.node.get_closest_marker("asap32") is not None):
        return
    from config.settings import Settings
    import services.agentic_events as _ae
    import services.auto_budget as _ab          # noqa: F401 - импорт для клавдж
    import services.config_migrations as _cm
    import services.direct_chat_service as _dcs
    import services.model_capacity as _mcap
    import services.summary_hybrid_budget as _shb
    import services.summary_l1_clusterizer as _sl1
    classes = {Settings, type(_dcs.settings), type(_mcap.settings),
               type(_ae.settings), type(_ab.settings), type(_cm.settings),
               type(_shb.settings), type(_sl1.settings)}
    for _cls in classes:
        for _name in (
            "MODEL_CAPACITY_RESOLVER_ENABLED",
            "AUTO_BUDGET_RESOLVER_ENABLED",
            "SUMMARY_COVERAGE_CHUNKING_ENABLED",
            "DIRECT_LLM_REACTION_ENABLED",
            "UI_BUDGETS_SPLIT_ENABLED",
            "ANALYTICS_CONTEXT_BUDGETS_ENABLED",
            "CONFIG_MIGRATION_INFO_LOGGING_ENABLED",
        ):
            if hasattr(_cls, _name):
                monkeypatch.setattr(_cls, _name, False)


@pytest.fixture(autouse=True)
def _asap32_flags_off_by_default(request, monkeypatch):
    """Изоляция ASAP-3.2 (round 1029, ADR-1028-5): старые тесты (без маркера
    ``asap32``) идут по прежним путям (kill-switch'и новых линий OFF —
    байт-в-байт baseline). Тесты новой функциональности помечаются
    ``@pytest.mark.asap32`` и работают с прод-дефолтами (ON). Прецедент —
    ``_asap31_flags_off_by_default``."""
    if (request.node.get_closest_marker("asap32") is not None
            or request.node.get_closest_marker("asap31") is not None
            or request.node.get_closest_marker("asap3") is not None):
        return
    from config.settings import Settings
    import services.direct_chat_service as _dcs
    import services.summary_fact_package as _sfp
    classes = {Settings, type(_dcs.settings), type(_sfp.settings)}
    for _cls in classes:
        for _name in (
            "DIRECT_LLM_DECISION_ENABLED",
            "SUMMARY_SEMANTIC_REDUCTION_ENABLED",
        ):
            if hasattr(_cls, _name):
                monkeypatch.setattr(_cls, _name, False)


@pytest.fixture(autouse=True)
def _asap4_flags_off_by_default(request, monkeypatch):
    """Изоляция ASAP-4 (round 1029, ADR-1028-7): старые тесты (без маркера
    ``asap4``) идут по прежним embed-путям — Embedding Control Plane OFF
    (бит-в-бит legacy: 21-аттемпный каскад llm_client+summary_memory,
    honest-terminal rebuild, статические batch/sleep). Тесты новой
    функциональности помечаются ``@pytest.mark.asap4`` и работают с
    прод-дефолтами (ON), точечно доопределяя флаги сценарием. Прецедент —
    ``_asap32_flags_off_by_default``.

    Волна D (T-4431/T-4432): review-флаги OFF для ВСЕХ не-asap4 тестов,
    ВКЛЮЧАЯ asap3/asap31/asap32 (их каркас мокает ``run_l2``/LLM-канал —
    bounded review loop с мок-каналом давал бы ложные review_degraded
    пути; прод-дефолт остаётся ON)."""
    asap4 = request.node.get_closest_marker("asap4") is not None
    legacy_asap = (request.node.get_closest_marker("asap32") is not None
                   or request.node.get_closest_marker("asap31") is not None
                   or request.node.get_closest_marker("asap3") is not None)
    if asap4:
        return
    import config.settings as _cs
    from config.settings import Settings
    import services.direct_chat_service as _dcs
    # ВАЖНО (asap-4): test_settings_worker_sync (S10.18-10) после reload
    # восстанавливает `config.settings.settings = orig` — исходный инстанс
    # ПЕРВОНАЧАЛЬНОГО класса, тогда как модульный атрибут `Settings`
    # указывает на пересозданный reload'ом класс. Патчим ОБА класса (плюс
    # класс direct_chat_service), иначе `_flag()` читает непатченный C1.
    classes = {Settings, type(_cs.settings), type(_dcs.settings)}
    for _cls in classes:
        if not legacy_asap:
            for _name in (
                "EMBED_CONTROL_PLANE_ENABLED",
                "EMBED_QUOTA_GROUP_COOLDOWN_ENABLED",
                "EMBED_PRIORITY_SCHEDULER_ENABLED",
                "EMBED_ADAPTIVE_CONCURRENCY_ENABLED",
                # asap-4 волна B (COVER Style production path): старые тесты —
                # бит-в-бит прежний контур (без snapshot/SELECTION/видимых
                # fail-open выходов); ON — только asap4-маркированные тесты.
                "COVER_STYLE_SNAPSHOT_ENABLED",
                # asap-4 волна C (Summary full-window, spec §3/§8.2): старые
                # тесты — бит-в-бит прежние контуры (too_many_facts → invalid;
                # §50.20-матрица quote-валидатора; тихий XML hard stop); ON —
                # только asap4-маркированные тесты.
                "SUMMARY_L1_CAPACITY_GUARD_ENABLED",
                "SUMMARY_QUOTE_REPAIR_ENABLED",
                "SUMMARY_LEGACY_FULL_WINDOW_ENABLED",
                # asap-4 волна E (Pipeline Analytics, spec §5/§8.2): старые
                # тесты — без стадийных событий SUMMARY_* (бит-в-бит прежний
                # контур; ON — только asap4-маркированные тесты).
                "SUMMARY_PIPELINE_EVENTS_ENABLED",
            ):
                if hasattr(_cls, _name):
                    monkeypatch.setattr(_cls, _name, False)
        # asap-4 волна D (Hybrid L2 Writer/Reviewer, spec §4/§8.2): OFF для
        # всех не-asap4 тестов (single-call L2, бит-в-бит).
        for _name in ("SUMMARY_L2_REVIEW_ENABLED",
                      "SUMMARY_REVISION_PATCH_ENABLED"):
            if hasattr(_cls, _name):
                monkeypatch.setattr(_cls, _name, False)



@pytest.fixture
def mock_bot():
    """Mock aiogram Bot instance."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_animation = AsyncMock()
    return bot


@pytest.fixture
def make_message():
    """Factory fixture to create mock Message objects."""
    def _make(from_id: int, text: str | None = None, chat_id: int = -1001234567890,
              username: str | None = None, **kwargs):
        msg = MagicMock()
        msg.text = text
        msg.caption = None
        msg.forward_origin = None  # ordinary message, not a forward (MagicMock-safe)
        msg.media_group_id = None  # Epic 36: not an album by default (MagicMock-safe)
        msg.new_chat_members = None  # T-410: not a service message by default (MagicMock-safe)
        msg.left_chat_member = None  # T-410: not a service message by default (MagicMock-safe)
        msg.message_id = 12345     # Epic 50: observer сохраняет tg_message_id
        msg.chat = MagicMock()
        msg.chat.id = chat_id
        msg.from_user = MagicMock()
        msg.from_user.id = from_id
        msg.from_user.username = username
        msg.reply = AsyncMock()
        msg.answer = AsyncMock()
        msg.answer_animation = AsyncMock()
        # Apply extra kwargs
        for k, v in kwargs.items():
            setattr(msg, k, v)
        return msg
    return _make


@pytest.fixture
def make_chat_member_updated():
    """Factory fixture to create mock ChatMemberUpdated objects."""
    def _make(user_id: int, old_status: str, new_status: str, chat_id: int = -1001234567890):
        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = chat_id
        event.bot = AsyncMock()
        event.bot.send_message = AsyncMock()
        
        event.old_chat_member = MagicMock()
        event.old_chat_member.status = old_status
        event.old_chat_member.user = MagicMock()
        event.old_chat_member.user.id = user_id
        
        event.new_chat_member = MagicMock()
        event.new_chat_member.status = new_status
        event.new_chat_member.user = MagicMock()
        event.new_chat_member.user.id = user_id
        
        return event
    return _make


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for all tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def make_admin_message():
    """Factory for admin_commands test messages with configurable chat.type and user_id."""
    def _make(chat_type: str = "private", user_id: int = 5885953495, chat_id: int = -100123):
        msg = MagicMock()
        msg.chat = MagicMock()
        msg.chat.id = chat_id
        msg.chat.type = chat_type
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
        msg.message_id = 12345
        msg.delete = AsyncMock()
        msg.answer = AsyncMock()
        msg.bot = AsyncMock()
        return msg
    return _make
