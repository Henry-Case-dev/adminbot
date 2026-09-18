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
