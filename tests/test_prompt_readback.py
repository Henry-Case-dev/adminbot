"""SELF-DIAG-01 D5 — типизированный `prompt_readback`.

Проверяется наблюдаемый контракт, а не число вызовов моков:

* запрос типизирован (`resource_kind=prompt`, `scope=current_chat`,
  `prompt_selector`, `requested_revision`, `delivery`) и аргументы модели не
  повышают права (`SD1-D5-02`, `SD1-SEM-10`);
* нет hardcoded триггера «покажи промпт»: точке входа не передаётся текст
  пользователя, поиск идёт по существующей библиотеке (`SD1-SEM-02`,
  `SD1-D5-03`);
* участник получает `denied` ДО чтения содержимого; админ чата и владелец —
  действующий промпт своего чата; неверифицируемая личность — `unverified`
  (`SD1-D5-07`, `SD1-D5-08`, `SD1-D5-09`);
* действующее значение собирает существующий реестр: chat override /
  global inherited / factory, без второй копии и без новой ревизии
  (`SD1-D5-01`, `SD1-D5-04`, `SD1-D5-10`);
* заводская редакция классифицируется как публичная, активная правка — как
  защищённая (`SD1-D2-16`);
* сервер отдаёт текст сам, plain text, чанками без усечения; модели
  возвращается только машинный статус (`SD1-D5-05`, `SD1-D5-06`,
  `SD1-D5-12`);
* аудит раскрытия содержит disclosure_actor/chat_id/prompt_id/revision/
  destination и не содержит текста (`SD1-D2-08`);
* секретные значения вырезаются, при неполных источниках — fail-closed
  (`SD1-D5-12`, ТЗ §9.2).
"""
import inspect
import json
from pathlib import Path

import pytest

from handlers import prompt_readback as handler
from services import chat_params
from services import diagnostic_policy as diag
from services import hot_config as hot
from services import output_projection as projection
from services import prompt_readback as readback
from services import prompt_registry as pr
from services import telegram_role_check as role_check
from services.tool_router import ToolContext, ToolRouter

OWNER_ID = 5885953495
ADMIN_ID = 7000001
MEMBER_ID = 7000002
GROUP = -1001000000001
GROUP_B = -1002000000002

#: PG-ключ и блок, которые тесты НЕ меняют в реальном хранилище: значения
#: подставляются через фейковый слой (temp fixtures only).
TEST_BLOCK = "memory.extract"
TEST_KEY = "prompts.extract_system_prompt"
#: Блок, для которого провенанс удерживает сохранённую редакцию.
WITHHELD_BLOCK = "checkup.base.system"
WITHHELD_KEY = "prompts.checkup_system_prompt"

SENTINEL_SECRET = "SUPER-SECRET-VALUE-9988"


# ── Двойники существующих слоёв (без сети, без PG) ─────────────────────────

class FakeCache:
    """ConfigCache-двойник: роли, значения конфига и их updated_at."""

    def __init__(self, admins=None, values=None, updated=None):
        self._admins = dict(admins or {})
        self._values = dict(values or {})
        self._updated = dict(updated or {})
        self.pg = None
        self.role_calls = []

    def get_role(self, telegram_id):
        return self._admins.get(telegram_id)

    def get_permissions_by_telegram_id(self, telegram_id):
        return None

    def get_permissions(self, role_name):
        from services.permissions import Permissions
        if role_name == "global_admin":
            return Permissions.from_dict({"wildcard": True})
        return Permissions.from_dict({})

    def roles(self):
        return {
            "global_admin": {"permissions": {"wildcard": True},
                             "role_type": "global_admin"},
            "user": {"permissions": {}, "role_type": "user"},
        }
    def get(self, key, default=None):
        return self._values.get(key, default)

    def get_updated_at(self, key):
        return self._updated.get(key)


class FakeChatStore:
    """ChatParamsCache-двойник: overrides + честный флаг доступности."""

    def __init__(self, root=None, *, updated="2026-11-13T10:00:00+00:00",
                 ok=True):
        self.root = dict(root or {})
        self.updated = updated
        self.ok = ok
        self.read_chats: list[int] = []

    async def get_chat_params_checked(self, chat_id):
        self.read_chats.append(int(chat_id))
        return self.root, self.ok

    async def get_chat_params_full(self, chat_id):
        return self.root, self.updated

    async def get_chat_params(self, chat_id):
        return self.root


class FakeMember:
    def __init__(self, status):
        self.status = status


class FakeBot:
    """Bot API-двойник: статус + отправки (текст сохраняется как есть)."""

    def __init__(self, statuses=None, *, fail_after=999, status_sequence=None):
        self.statuses = dict(statuses or {})
        self.status_sequence = list(status_sequence or [])
        self.sent: list[dict] = []
        self.fail_after = fail_after

    async def get_chat_member(self, chat_id, user_id):
        if self.status_sequence:
            return FakeMember(self.status_sequence.pop(0))
        return FakeMember(self.statuses.get((chat_id, user_id), "member"))

    async def send_message(self, chat_id, text, **kwargs):
        if len(self.sent) >= self.fail_after:
            raise RuntimeError("telegram_send_failed")
        self.sent.append({"chat_id": chat_id, "text": text, **kwargs})
        return type("SentMessage", (), {"message_id": len(self.sent)})()


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


@pytest.fixture
def admin_cache():
    # Админ чата проверяется Telegram'ом (getChatMember), а не кэшем ролей:
    # глобальная роль в кэше сделала бы его владельцем.
    return FakeCache({})


@pytest.fixture
def owner_cache():
    return FakeCache({OWNER_ID: "global_admin"})


@pytest.fixture
def member_cache():
    return FakeCache({})


@pytest.fixture
def chat_store():
    return FakeChatStore()


@pytest.fixture
def admin_bot():
    return _admin_bot()


@pytest.fixture
def member_bot():
    return _member_bot()


def _member_bot():
    return FakeBot({(GROUP, ADMIN_ID): "member",
                    (GROUP, MEMBER_ID): "member"})


def _admin_bot():
    return FakeBot({(GROUP, ADMIN_ID): "administrator"})


def _ctx(*, user_id=ADMIN_ID, chat_id=GROUP, bot=None, reply_to=101):
    return ToolContext(chat_id, query="", bot=bot, user_id=user_id,
                       reply_to_message_id=reply_to)


def _request(**overrides):
    payload = {"resource_kind": "prompt", "scope": "current_chat",
               "prompt_selector": TEST_BLOCK,
               "requested_revision": "effective", "delivery": "reply"}
    payload.update(overrides)
    return payload


async def _prepare(cache, store, arguments, *, user_id=ADMIN_ID,
                   chat_id=GROUP, bot=None, secrets=None, pg=None):
    chat_params.set_chat_params_cache(store)
    return await readback.prepare(arguments, telegram_id=user_id,
                                  chat_id=chat_id, cache=cache, bot=bot,
                                  pg=pg, secrets=secrets)


async def _dispatch(monkeypatch, cache, store, arguments, *, user_id=ADMIN_ID,
                    chat_id=GROUP, bot=None):
    """Реальный вход инструмента (та же сигнатура, что ждёт tool-путь)."""
    chat_params.set_chat_params_cache(store)
    monkeypatch.setattr(hot, "get_config_cache", lambda: cache)
    return await handler.prompt_readback(arguments,
                                         _ctx(user_id=user_id, chat_id=chat_id,
                                              bot=bot))


def _paths_of(messages):
    return "".join(messages)


# ── 1. Типизированный запрос (SD1-D5-02, SD1-SEM-10) ───────────────────────

def test_request_accepts_contract_fields_and_defaults():
    request, error = readback.parse_request(
        {"resource_kind": "prompt", "prompt_selector": TEST_BLOCK})
    assert error == ""
    assert request.scope == readback.SCOPE_CURRENT_CHAT
    assert request.delivery == readback.DELIVERY_REPLY
    assert request.requested_revision == readback.REVISION_EFFECTIVE
    assert request.selector == TEST_BLOCK


def test_request_rejects_unknown_identity_fields():
    for field in ("user_id", "chat_id", "role", "is_admin", "actor"):
        request, error = readback.parse_request(
            {"resource_kind": "prompt", field: 1})
        assert request is None
        assert error.startswith("unknown_field:"), (field, error)


def test_request_rejects_wrong_resource_kind():
    request, error = readback.parse_request(
        {"resource_kind": "file", "prompt_selector": TEST_BLOCK})
    assert request is None and error == "resource_kind_not_prompt"


def test_request_rejects_foreign_scope_and_delivery():
    request, error = readback.parse_request(
        {"resource_kind": "prompt", "scope": "other_chat"})
    assert request is None and error == "scope_not_current_chat"
    request, error = readback.parse_request(
        {"resource_kind": "prompt", "delivery": "dm"})
    assert request is None and error == "delivery_not_reply"


def test_request_requires_revision_for_specific():
    request, error = readback.parse_request(
        {"resource_kind": "prompt", "requested_revision": "specific",
         "prompt_selector": TEST_BLOCK})
    assert request is None and error == "revision_required"
    request, error = readback.parse_request(
        {"resource_kind": "prompt", "requested_revision": "latest"})
    assert request is None and error == "requested_revision_invalid"


def test_request_is_not_a_free_text_entry_point():
    """Текст пользователя сюда не попадает: аргументы — только typed-поля."""
    request, error = readback.parse_request("покажи промпт")
    assert request is None and error == "arguments_not_an_object"


def test_tool_schema_is_typed():
    schema = handler.tool_definition()
    function = schema["function"]
    assert function["name"] == "prompt_readback"
    params = function["parameters"]
    assert params["additionalProperties"] is False
    assert params["required"] == ["resource_kind"]
    assert params["properties"]["resource_kind"]["enum"] == ["prompt"]
    assert params["properties"]["scope"]["enum"] == ["current_chat"]
    assert params["properties"]["delivery"]["enum"] == ["reply"]
    assert sorted(params["properties"]["requested_revision"]["enum"]) == [
        "effective", "specific"]
    # Схема — копия: регистрация не может испортить канон в рантайме.
    params["properties"]["scope"]["enum"].append("other_chat")
    assert handler.tool_definition()["function"]["parameters"][
        "properties"]["scope"]["enum"] == ["current_chat"]


def test_tool_entry_point_matches_existing_dispatch_shape():
    ours = list(inspect.signature(handler.prompt_readback).parameters)
    assert ours == ["arguments", "ctx"]
    router_method = inspect.signature(ToolRouter._get_bot_health)
    assert list(router_method.parameters)[1:] == ["arguments", "ctx"]
    assert inspect.iscoroutinefunction(handler.prompt_readback)


# ── 2. Поиск по существующей библиотеке (SD1-D5-03) ────────────────────────

def test_selector_exact_by_block_id_and_pg_key():
    state, candidates = readback.search_library(TEST_BLOCK)
    assert state == "exact" and candidates[0].block_id == TEST_BLOCK
    state, candidates = readback.search_library(TEST_KEY)
    assert state == "exact" and candidates[0].block_id == TEST_BLOCK


def test_selector_unique_plain_name_resolves():
    state, candidates = readback.search_library("youtube video")
    assert state == "match"
    assert [candidate.block_id for candidate in candidates] == [
        "youtube.base.video"]


def test_selector_from_existing_library_is_not_a_second_index():
    rows = readback.library_rows()
    assert rows == [row for row in pr.registry_view()
                    if not row.get("retired")]
    retired = [row["block_id"] for row in pr.registry_view() if row["retired"]]
    visible = {row["block_id"] for row in rows}
    assert not (visible & set(retired))


@pytest.mark.asyncio
async def test_selector_ambiguous_asks_one_question_without_content(
        monkeypatch, admin_cache, chat_store, admin_bot):
    async def _must_not_read(*args, **kwargs):
        raise AssertionError("контент не должен читаться при ambiguous")

    monkeypatch.setattr(readback, "load_artifact", _must_not_read)
    outcome = await _prepare(admin_cache, chat_store,
                             _request(prompt_selector="checkup"),
                             bot=admin_bot)
    assert outcome.status == readback.STATUS_AMBIGUOUS
    assert "status=ambiguous" in outcome.machine
    assert "next=ask_one_question" in outcome.machine
    assert "checkup.base.system" in outcome.machine
    assert outcome.messages == ()


@pytest.mark.asyncio
async def test_no_selector_asks_and_does_not_guess(monkeypatch, admin_cache,
                                                  chat_store, admin_bot):
    async def _must_not_read(*args, **kwargs):
        raise AssertionError("контент не должен читаться без селектора")

    monkeypatch.setattr(readback, "load_artifact", _must_not_read)
    outcome = await _prepare(admin_cache, chat_store,
                             {"resource_kind": "prompt"}, bot=admin_bot)
    assert outcome.status == readback.STATUS_AMBIGUOUS
    lines = [line for line in outcome.machine.splitlines() if line.strip()]
    # строка статуса + не больше MAX_QUESTION_CANDIDATES кандидатов
    assert len(lines) <= 1 + readback.MAX_QUESTION_CANDIDATES


@pytest.mark.asyncio
async def test_selector_not_found_is_honest(admin_cache, chat_store, admin_bot):
    outcome = await _prepare(admin_cache, chat_store,
                             _request(prompt_selector="zzz-no-such-prompt"),
                             bot=admin_bot)
    assert outcome.status == readback.STATUS_NOT_FOUND
    assert "status=not_found" in outcome.machine
    assert outcome.messages == ()


# ── 3. Права (SD1-D5-07/08/09, SD1-AMX-03/04, SD1-AC-13) ───────────────────

@pytest.mark.asyncio
async def test_member_is_denied_before_content_read(monkeypatch, member_cache,
                                                    chat_store):
    async def _must_not_read(*args, **kwargs):
        raise AssertionError("содержимое промпта не читается до allow")

    monkeypatch.setattr(readback, "load_artifact", _must_not_read)
    bot = _member_bot()
    outcome = await _prepare(member_cache, chat_store, _request(), user_id=MEMBER_ID,
                             bot=bot)
    assert outcome.status == readback.STATUS_DENIED
    assert outcome.metadata["reason_code"] == diag.R_DENY_PROMPT_MEMBER
    assert outcome.messages == ()
    assert bot.sent == []


@pytest.mark.asyncio
async def test_known_prompt_text_does_not_grant_access(monkeypatch,
                                                       member_cache, chat_store):
    """Знание точного текста/имени не заменяет права (SD1-D5-11)."""
    async def _must_not_read(*args, **kwargs):
        raise AssertionError("знание текста не открывает доступ")

    monkeypatch.setattr(readback, "load_artifact", _must_not_read)
    outcome = await _prepare(
        member_cache, chat_store,
        _request(prompt_selector=TEST_KEY), user_id=MEMBER_ID,
        bot=_member_bot())
    assert outcome.status == readback.STATUS_DENIED
    assert TEST_KEY not in outcome.machine


@pytest.mark.asyncio
async def test_claims_of_ownership_in_arguments_do_not_help(member_cache,
                                                            chat_store):
    outcome = await _prepare(
        member_cache, chat_store,
        _request(role="project_owner", user_id=OWNER_ID), user_id=MEMBER_ID,
        bot=_member_bot())
    assert outcome.status == readback.STATUS_INVALID_REQUEST
    assert "unknown_field" in outcome.reason


@pytest.mark.asyncio
async def test_chat_admin_gets_prompt_in_group(monkeypatch, admin_cache,
                                               chat_store):
    bot = _admin_bot()
    ack = await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                          user_id=ADMIN_ID, bot=bot)
    assert "status=delivered" in ack
    assert "destination=group" in ack
    assert len(bot.sent) >= 1
    assert {message["chat_id"] for message in bot.sent} == {GROUP}


@pytest.mark.asyncio
async def test_owner_gets_prompt_by_numeric_id(monkeypatch, owner_cache,
                                               chat_store):
    bot = FakeBot({})                       # статус участника не нужен
    ack = await _dispatch(monkeypatch, owner_cache, chat_store, _request(),
                          user_id=OWNER_ID, bot=bot)
    assert "status=delivered" in ack
    assert bot.sent and bot.sent[0]["chat_id"] == GROUP


@pytest.mark.asyncio
async def test_unverified_when_telegram_cannot_confirm(admin_cache, chat_store):
    outcome = await _prepare(admin_cache, chat_store, _request(), bot=None)
    assert outcome.status == readback.STATUS_UNVERIFIED
    assert diag.R_DENY_AUTH_UNVERIFIED in outcome.reason
    assert "позже" in outcome.machine
    assert "админк" in outcome.machine
    assert outcome.messages == ()


@pytest.mark.asyncio
async def test_revocation_between_check_and_publication(monkeypatch,
                                                        admin_cache,
                                                        chat_store):
    """Отзыв админства во время запроса: текст не уходит, аудит фиксирует."""
    bot = FakeBot(status_sequence=["administrator", "member"])
    ack = await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                          bot=bot)
    assert "denied_prompt_content_member" in ack
    assert "status=delivered" not in ack
    assert bot.sent == []
    events = [record["event"] for record in diag.audit_snapshot()]
    assert "revocation_detected" in events


@pytest.mark.asyncio
async def test_other_chat_scope_is_impossible(monkeypatch, admin_cache,
                                              chat_store, admin_bot):
    # 1. Другой скоуп отвергается типом запроса.
    outcome = await _prepare(admin_cache, chat_store,
                             _request(scope="other_chat"), bot=admin_bot)
    assert outcome.status == readback.STATUS_INVALID_REQUEST
    # 2. Чужой chat_id в аргументах — неизвестное поле, а не адрес чтения.
    outcome = await _prepare(admin_cache, chat_store,
                             _request(chat_id=GROUP_B), bot=admin_bot)
    assert outcome.status == readback.STATUS_INVALID_REQUEST
    # 3. Реальное чтение идёт только по чату актора.
    chat_store.root = {"overrides": {TEST_KEY: "текст своего чата"}}
    await _prepare(admin_cache, chat_store, _request(), chat_id=GROUP,
                   bot=admin_bot)
    assert chat_store.read_chats and set(chat_store.read_chats) == {GROUP}


@pytest.mark.asyncio
async def test_prompts_capability_separates_read_and_edit():
    capability = diag.CAPABILITY_MAP["prompts"]
    assert capability.data_class == diag.PROMPT_CONTENT
    assert capability.actions == ("view", "edit")
    snapshot = await diag.matrix_snapshot()
    item = snapshot["items"]["prompts"]
    assert item["configurable"] is True
    assert item["default"]["view_roles"] == ["local_admin"]
    rules = {rule["rule"] for rule in item["hard_rules"]}
    assert diag.R_DENY_PROMPT_MEMBER in rules


@pytest.mark.asyncio
async def test_matrix_override_cannot_open_prompts_to_member(
        monkeypatch, member_cache, chat_store):
    from services import access as access_srv

    async def _global(_pg):
        return {"prompts": {"view_roles": ["user", "local_admin"]}}

    async def _chat(_chat_id, *, pg=None):
        return {"prompts": {"view_roles": ["user", "local_admin"]}}

    monkeypatch.setattr(access_srv, "diag_global_overrides", _global)
    monkeypatch.setattr(access_srv, "diag_chat_overrides", _chat)
    outcome = await _prepare(member_cache, chat_store, _request(),
                             user_id=MEMBER_ID, bot=_member_bot(),
                             pg=object())
    assert outcome.status == readback.STATUS_DENIED
    assert outcome.metadata["reason_code"] == diag.R_DENY_PROMPT_MEMBER


# ── 4. Действующее значение (SD1-D5-01/04/10, SD1-D2-16) ──────────────────

@pytest.mark.asyncio
async def test_global_inherited_metadata(admin_cache, chat_store, admin_bot):
    admin_cache._values[TEST_KEY] = "ГЛОБАЛЬНАЯ ВЕРСИЯ"
    admin_cache._updated[TEST_KEY] = "2026-11-10T09:00:00+00:00"
    outcome = await _prepare(admin_cache, chat_store, _request(),
                             bot=admin_bot)
    assert outcome.status == readback.STATUS_DELIVERED
    metadata = outcome.metadata
    assert metadata["source"] == readback.SOURCE_GLOBAL_INHERITED
    assert metadata["registry_source"] == "global"
    assert metadata["revision"].startswith("act:")
    assert metadata["version_id"] == metadata["revision"]
    assert metadata["effective_at"] == "2026-11-10T09:00:00+00:00"
    payload = _paths_of(outcome.messages)
    assert "Источник: global_inherited" in payload
    assert readback.payload_body(payload) == "ГЛОБАЛЬНАЯ ВЕРСИЯ"


@pytest.mark.asyncio
async def test_factory_value_has_no_invented_effective_at(admin_cache,
                                                          chat_store,
                                                          admin_bot):
    outcome = await _prepare(admin_cache, chat_store, _request(), bot=admin_bot)
    assert outcome.metadata["source"] == readback.SOURCE_FACTORY
    assert outcome.metadata["effective_at"] is None
    assert "нет метки у источника" in _paths_of(outcome.messages)


@pytest.mark.asyncio
async def test_chat_override_wins_with_effective_at(admin_cache, chat_store,
                                                    admin_bot):
    admin_cache._values[TEST_KEY] = "ГЛОБАЛЬНАЯ ВЕРСИЯ"
    chat_store.root = {"overrides": {TEST_KEY: "ПРАВКА ЭТОГО ЧАТА"}}
    outcome = await _prepare(admin_cache, chat_store, _request(),
                             bot=admin_bot)
    assert outcome.metadata["source"] == readback.SOURCE_CHAT_OVERRIDE
    assert outcome.metadata["effective_at"] == chat_store.updated
    assert readback.payload_body(_paths_of(outcome.messages)) == \
        "ПРАВКА ЭТОГО ЧАТА"


@pytest.mark.asyncio
async def test_no_override_shows_factory_and_creates_no_revision(
        monkeypatch, admin_cache, chat_store, admin_bot):
    async def _must_not_write(*args, **kwargs):
        raise AssertionError("чтение не создаёт ревизию")

    monkeypatch.setattr(chat_params, "set_chat_params", _must_not_write)
    first = await _prepare(admin_cache, chat_store, _request(), bot=admin_bot)
    second = await _prepare(admin_cache, chat_store, _request(), bot=admin_bot)
    assert first.status == readback.STATUS_DELIVERED
    assert first.metadata["source"] == readback.SOURCE_FACTORY
    assert first.metadata["revision"] == second.metadata["revision"]
    expected = pr.effective_prompt(TEST_BLOCK)
    assert first.metadata["revision"] == expected.revision
    assert readback.payload_body(_paths_of(first.messages)) == expected.text


@pytest.mark.asyncio
async def test_readback_uses_the_single_registry(admin_cache, chat_store):
    chat_params.set_chat_params_cache(chat_store)
    chat_store.root = {"overrides": {TEST_KEY: "ТЕКСТ ЧЕРЕЗ РЕЕСТР"}}
    artifact = await readback.load_artifact(TEST_BLOCK, GROUP,
                                            cache=admin_cache)
    expected = pr.effective_prompt(TEST_BLOCK,
                                   chat_value="ТЕКСТ ЧЕРЕЗ РЕЕСТР")
    assert artifact.text == expected.text
    assert artifact.revision == expected.revision
    blocks = [row for row in pr.registry_view() if row["block_id"] == TEST_BLOCK]
    assert len(blocks) == 1


@pytest.mark.asyncio
async def test_factory_public_classification(admin_cache, chat_store,
                                             admin_bot):
    outcome = await _prepare(admin_cache, chat_store, _request(), bot=admin_bot)
    assert outcome.metadata["classification"] == readback.CLASS_FACTORY_PUBLIC
    assert "factory_public" in _paths_of(outcome.messages)


@pytest.mark.asyncio
async def test_active_value_classification(admin_cache, chat_store, admin_bot):
    chat_store.root = {"overrides": {TEST_KEY: "АКТИВНАЯ ПРАВКА"}}
    outcome = await _prepare(admin_cache, chat_store, _request(), bot=admin_bot)
    assert outcome.metadata["classification"] == readback.CLASS_ACTIVE_VALUE


@pytest.mark.asyncio
async def test_withheld_saved_edition_is_reported_honestly(admin_cache,
                                                          chat_store,
                                                          admin_bot):
    chat_store.root = {"overrides": {WITHHELD_KEY: "СОХРАНЁННАЯ РЕДАКЦИЯ"}}
    outcome = await _prepare(admin_cache, chat_store,
                             _request(prompt_selector=WITHHELD_BLOCK),
                             bot=admin_bot)
    assert outcome.status == readback.STATUS_DELIVERED
    assert outcome.metadata["withheld"] is True
    payload = _paths_of(outcome.messages)
    assert "удержана" in payload
    # Действует заводская редакция; сохранённый текст не выдаётся как текущий.
    assert readback.payload_body(payload) != "СОХРАНЁННАЯ РЕДАКЦИЯ"
    assert readback.payload_body(payload) == pr.factory_text(WITHHELD_BLOCK)


@pytest.mark.asyncio
async def test_specific_factory_revision(admin_cache, chat_store, admin_bot):
    factory_revision = pr.effective_prompt(TEST_BLOCK).factory_revision
    chat_store.root = {"overrides": {TEST_KEY: "ДРУГОЙ ТЕКСТ"}}
    outcome = await _prepare(
        admin_cache, chat_store,
        _request(requested_revision="specific", revision=factory_revision),
        bot=admin_bot)
    assert outcome.status == readback.STATUS_DELIVERED
    assert readback.payload_body(_paths_of(outcome.messages)) == \
        pr.factory_text(TEST_BLOCK)


@pytest.mark.asyncio
async def test_unknown_revision_is_unavailable(admin_cache, chat_store,
                                               admin_bot):
    outcome = await _prepare(
        admin_cache, chat_store,
        _request(requested_revision="specific", revision="fac:deadbeef0000"),
        bot=admin_bot)
    assert outcome.status == readback.STATUS_REVISION_UNAVAILABLE
    assert "version_history_not_exposed" in outcome.machine
    assert outcome.messages == ()


@pytest.mark.asyncio
async def test_unreadable_chat_layer_is_unavailable(admin_cache, chat_store,
                                                    admin_bot):
    chat_store.ok = False
    outcome = await _prepare(admin_cache, chat_store, _request(),
                             bot=admin_bot)
    assert outcome.status == readback.STATUS_UNAVAILABLE
    assert outcome.reason == "effective_value_unavailable"
    assert outcome.messages == ()


# ── 5. Доставка сервером (SD1-D5-05/06, SD1-AC-12) ────────────────────────

@pytest.mark.asyncio
async def test_body_is_delivered_verbatim_by_server(monkeypatch, admin_cache,
                                                    chat_store):
    exact = "СТРОКА 1\nСТРОКА 2 с  двойным  пробелом\n\tтаб"
    chat_store.root = {"overrides": {TEST_KEY: exact}}
    bot = _admin_bot()
    ack = await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                          bot=bot)
    assert "status=delivered" in ack
    payload = "".join(message["text"] for message in bot.sent)
    assert readback.payload_body(payload) == exact
    assert all(message.get("parse_mode") is None for message in bot.sent)


@pytest.mark.asyncio
async def test_long_prompt_is_chunked_without_truncation(monkeypatch,
                                                         admin_cache,
                                                         chat_store):
    long_text = " ".join(["абвгд"] * 2200)          # ~13k символов
    chat_store.root = {"overrides": {TEST_KEY: long_text}}
    bot = _admin_bot()
    ack = await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                          bot=bot)
    assert "status=delivered" in ack
    chunks = [message["text"] for message in bot.sent]
    assert len(chunks) > 1
    assert all(len(chunk) <= readback.TELEGRAM_TEXT_LIMIT for chunk in chunks)
    assert readback.payload_body("".join(chunks)) == long_text
    assert f"chunks={len(chunks)}" in ack


def test_chunks_splitter_is_lossless():
    for text in ("", "а", "a" * 9000, "слово " * 1500,
                 "\n\n" * 5000, "хвост"):
        chunks = readback.split_chunks(text)
        assert "".join(chunks) == text
        assert all(len(chunk) <= readback.TELEGRAM_TEXT_LIMIT
                   for chunk in chunks)


@pytest.mark.asyncio
async def test_ack_contains_no_prompt_body(monkeypatch, admin_cache,
                                           chat_store):
    body = "УНИКАЛЬНЫЙ МАРКЕР ТЕЛА ПРОМПТА " * 6
    chat_store.root = {"overrides": {TEST_KEY: body}}
    ack = await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                          bot=_admin_bot())
    assert "status=delivered" in ack
    assert "УНИКАЛЬНЫЙ МАРКЕР" not in ack
    assert body[:40] not in ack


@pytest.mark.asyncio
async def test_delivery_is_plain_text_not_a_document(monkeypatch, admin_cache,
                                                     chat_store):
    bot = _admin_bot()
    await _dispatch(monkeypatch, admin_cache, chat_store, _request(), bot=bot)
    assert bot.sent
    for message in bot.sent:
        assert "parse_mode" in message and message["parse_mode"] is None
    source = _module_source(handler)
    assert "send_document" not in source
    assert "InputFile" not in source
    assert "filename" not in source


def test_handler_constants_match_existing_policy():
    capability = diag.CAPABILITY_MAP[handler.CAPABILITY]
    assert capability.data_class == diag.PROMPT_CONTENT
    assert handler.ACTION in capability.actions
    assert handler.CAPABILITY == "prompts"
    assert handler.TOOL_NAME == "prompt_readback"


@pytest.mark.asyncio
async def test_partial_delivery_is_reported(monkeypatch, admin_cache,
                                            chat_store):
    long_text = " ".join(["абвгд"] * 2000)
    chat_store.root = {"overrides": {TEST_KEY: long_text}}
    bot = _admin_bot()
    bot.fail_after = 1
    ack = await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                          bot=bot)
    assert "status=partial" in ack
    assert "reason=delivery_failed" in ack
    assert f"chunks={len(bot.sent)}" in ack
    # Частичная выдача не выдаётся за успех, но и не называется отказом прав.
    assert "status=delivered" not in ack


# ── 6. Секреты, журналы, аудит (SD1-D5-12, SD1-D2-08) ─────────────────────

@pytest.mark.asyncio
async def test_secret_fragment_is_redacted_inline(admin_cache, chat_store,
                                                  admin_bot):
    chat_store.root = {"overrides": {
        TEST_KEY: f"инструкция {SENTINEL_SECRET} конец"}}
    outcome = await _prepare(
        admin_cache, chat_store, _request(), bot=admin_bot,
        secrets={SENTINEL_SECRET: "keys.test_secret"})
    assert outcome.status == readback.STATUS_DELIVERED
    payload = _paths_of(outcome.messages)
    assert SENTINEL_SECRET not in payload
    assert "«скрыто:keys.test_secret»" in payload
    assert outcome.metadata["redaction"] == projection.STATUS_PARTIALLY_REDACTED


@pytest.mark.asyncio
async def test_blocked_when_secret_sources_incomplete(admin_cache, chat_store,
                                                      admin_bot):
    incomplete = projection.SecretSnapshot({}, False, ("env",))
    outcome = await _prepare(admin_cache, chat_store, _request(),
                             bot=admin_bot, secrets=incomplete)
    assert outcome.status == readback.STATUS_BLOCKED
    assert outcome.messages == ()
    assert "secret_sources" in outcome.reason


@pytest.mark.asyncio
async def test_logs_and_audit_contain_no_prompt_body(caplog, monkeypatch,
                                                     admin_cache, chat_store):
    body = "СЕКРЕТНЫЙ ФРАГМЕНТ ТЕЛА ДЛЯ ЖУРНАЛА " * 4
    chat_store.root = {"overrides": {TEST_KEY: body}}
    with caplog.at_level("DEBUG"):
        await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                        bot=_admin_bot())
    records = " ".join(record.getMessage() for record in caplog.records)
    assert "СЕКРЕТНЫЙ ФРАГМЕНТ ТЕЛА" not in records
    audit = json.dumps(diag.audit_snapshot(), ensure_ascii=False)
    assert "СЕКРЕТНЫЙ ФРАГМЕНТ ТЕЛА" not in audit
    assert "prompt_disclosure" in audit


@pytest.mark.asyncio
async def test_audit_disclosure_fields(monkeypatch, admin_cache, chat_store):
    await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                    user_id=ADMIN_ID, bot=_admin_bot())
    records = [record for record in diag.audit_snapshot()
               if record.get("event") == "prompt_disclosure"]
    assert len(records) == 1
    record = records[0]
    assert record["disclosure_actor"] == ADMIN_ID
    assert record["chat_id"] == GROUP
    assert record["prompt_id"] == TEST_BLOCK
    assert str(record["prompt_revision"]).startswith("act:")
    assert record["destination"] == "group"


@pytest.mark.asyncio
async def test_audit_is_not_written_when_nothing_was_sent(monkeypatch,
                                                          admin_cache,
                                                          chat_store):
    long_text = " ".join(["абвгд"] * 2000)
    chat_store.root = {"overrides": {TEST_KEY: long_text}}
    bot = _admin_bot()
    bot.fail_after = 0
    ack = await _dispatch(monkeypatch, admin_cache, chat_store, _request(),
                          bot=bot)
    assert "status=partial" in ack and "chunks=0" in ack
    assert not [record for record in diag.audit_snapshot()
                if record.get("event") == "prompt_disclosure"]


# ── 7. Структурные инварианты (SD1-SEM-02, no second agent/store) ─────────

def _module_source(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _imported_modules(module) -> set[str]:
    import ast

    tree = ast.parse(_module_source(module))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _data_string_literals(module) -> list[str]:
    """Строковые ЛИТЕРАЛЫ кода без докстрингов (то, что реально исполняется)."""
    import ast

    tree = ast.parse(_module_source(module))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings]


def test_no_hardcoded_trigger_or_text_matching():
    """Нет перехвата фраз пользователя: вход — только typed-аргументы."""
    for module in (readback, handler):
        source = _module_source(module)
        assert "message.text" not in source
        assert "message.caption" not in source
        assert "re.compile(" not in source
        literals = " ".join(_data_string_literals(module)).lower()
        assert "покажи промпт" not in literals
        assert "show prompt" not in literals


def test_no_llm_call_and_no_second_loop():
    service_imports = _imported_modules(readback)
    assert not any(name.startswith(("services.llm_client", "services.tool_loop",
                                    "services.prompt_composer",
                                    "services.direct_chat_service", "openai"))
                   for name in service_imports)
    handler_imports = _imported_modules(handler)
    assert not any(name.startswith(("services.llm_client", "services.tool_loop",
                                    "services.prompt_composer",
                                    "services.direct_chat_service", "openai"))
                   for name in handler_imports)
    # Никаких новых LLM-вызовов: в коде нет обращения к чат-клиенту.
    for module in (readback, handler):
        source = _module_source(module)
        assert "chat_with_tools(" not in source
        assert "generate_chat(" not in source


def test_module_has_no_write_path():
    source = _module_source(readback)
    for needle in ("INSERT ", "UPDATE ", "DELETE ", "set_chat_params(",
                   "cache.set(", ".upsert(", "send_document"):
        assert needle not in source
    assert "prompt_registry" in source
