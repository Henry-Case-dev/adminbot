"""ASAP-speech-arch / INSPECTOR — INS-TRACE, INS-EXACT, INS-SKIPREASON.

TEST-LIFECYCLE: CONTRACT owner=ASAP-SPEECH/INSPECTOR (source-2026-10-22 §6).

Что доказывается здесь:

* **INS-EXACT**: `exact` в Inspector — это РЕАЛЬНЫЙ запрос провайдера
  (system+user, порядок, тот же payload после adapt/fallback), не превью
  настройки; checksum считается по фактически отправленному телу и
  пересчитывается независимо в тесте;
* **INS-TRACE**: журнал вызова содержит correlation_id, модель/провайдера,
  этап, структуру сообщений и хэши, а chat_id отдаётся с privacy-redaction;
  секреты в журнал не попадают;
* **INS-SKIPREASON**: пропущенный слой объясняется по-русски, машинный код
  остаётся отдельным полем (диагностика), а не основным текстом;
* **INS-HIERARCHY/INS-CONFLICT**: иерархия отдаёт текст/источник/редакцию
  блока, конфликты классифицируются по реальным данным сборки.

Прод/SSH/сеть не используются: транспорт провайдера подменён на месте.
"""
import asyncio
import json
import json as json_lib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

# Фикстура/хелперы W6 переиспользуются, а не дублируются: тот же реальный
# chat-слой (temp-SQLite) и та же рантайм-форма манифеста хода.
from test_soul1_w6_speech_ui import _run, _seed_real_turn, api_env  # noqa: F401,E402

import web.api.speech as S  # noqa: E402
from services import llm_client, prompt_composer as composer  # noqa: E402


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "готовый ответ"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3}}


class _FakeHTTPResponse:
    def __init__(self, status=200, body=None, invalid_json=False):
        self.status_code = status
        self._invalid = bool(invalid_json)
        self._body = body if body is not None else {
            "choices": [{"message": {"content": "готовый ответ"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }
        self.content = json_lib.dumps(self._body).encode("utf-8")
        self.text = self.content.decode("utf-8")
        self.headers = {}

    def json(self):
        if self._invalid:
            raise ValueError("not json")
        return self._body


class _FakeHTTP:
    """Транспорт-двойник: фиксирует РОВНО тот json=, что ушёл бы в HTTP."""

    def __init__(self, owner, status=200, body=None, invalid_json=False):
        self.owner = owner
        self.status = status
        self.body = body
        self.invalid_json = invalid_json

    async def post(self, url, json=None, **kwargs):
        # Глубокая копия как снимок тела на проводе (httpx сериализует json).
        self.owner.bodies.append(
            {"url": url, "body": json_lib.loads(json_lib.dumps(json))})
        return _FakeHTTPResponse(self.status, self.body, self.invalid_json)


class _TraceClient(llm_client.LLMClient):
    """Клиент без сети: подменён ТОЛЬКО транспорт, весь путь отправки реальный.

    ``_post``/``_post_with_key``/``_post_fallback``/``_fallback_with_retries``
    исполняются как в проде — поэтому тест видит фактическое HTTP-тело
    (включая подмену ``model`` на fallback), а не аргумент ``generate``.
    """

    def __init__(self, bodies, *, primary_status=200, fallback_active=False,
                 primary_retries=0, fallback_retries=0, fallback_status=200,
                 primary_body=None, invalid_json=False):
        self._chat_model = "trace-model-1"
        self._fallback_model = "trace-fallback-1"
        self._api_key = "test-key"
        self._fallback_active = fallback_active
        self._base_url = "https://provider.example/v1"
        self._fallback_base_url = "https://fallback.example/v1"
        self._budget = 5.0
        self._max_retries = primary_retries
        self._timeout = 5.0
        self._fallback_max_retries = fallback_retries
        self._fallback_timeout = 5.0
        self.backoff_base = 0
        self._backoff_cap = 0
        self.bodies = bodies
        self._primary_http = _FakeHTTP(
            self, status=primary_status, body=primary_body,
            invalid_json=invalid_json)
        self._fallback_http = _FakeHTTP(self, status=fallback_status)

    def _get_client(self, key=None):
        return self._primary_http

    def _get_fallback_client(self):
        return self._fallback_http

    async def _resolve_api_key_and_source(self, chat_id=None):
        return "test-key", "global"

    async def _record_global_usage(self, *args, **kwargs):
        return None

    async def _record_analytics(self, *args, **kwargs):
        return None


def _generate(bodies, messages, *, correlation_id="cid-exact-1",
              chat_id=-100500, client=None):
    client = client or _TraceClient(bodies)
    return asyncio.run(client.generate(
        messages, temperature=0.3, chat_id=chat_id, module="direct_chat",
        step="single", correlation_id=correlation_id))


def _last_body(bodies):
    return bodies[-1]["body"]


def test_trace_checksum_matches_actually_sent_payload():
    """INS-EXACT/INS-TRACE: checksum в Inspector == тело запроса в транспорте."""
    composer.reset_state()
    bodies: list = []
    messages = [
        {"role": "system", "content": "СИСТЕМНАЯ РОЛЬ: контракт канала\n\nCore"},
        {"role": "user", "content": "Вопрос пользователя"},
        {"role": "user", "content": "<dig_result>факт</dig_result>"},
    ]
    assert _generate(bodies, messages) == "готовый ответ"
    assert len(bodies) == 1
    sent = _last_body(bodies)
    assert sent["messages"] == messages      # ровно тело запроса

    call = composer.last_provider_call(chat_id=-100500)
    assert call is not None, "реальный вызов обязан попасть в журнал"
    # Проверка считается независимо от продакшн-функции.
    import hashlib
    expected = hashlib.sha256(
        json.dumps(sent, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
    assert call["manifest_checksum"] == expected
    assert call["manifest_checksum"] == composer.payload_checksum(sent)
    # Точный payload: тот же порядок ролей и то же содержимое.
    assert call["roles"] == ["system", "user", "user"]
    assert call["message_count"] == 3
    assert call["model"] == "trace-model-1"
    assert call["channel"] == "primary"
    assert call["provider"] == "provider.example"
    assert call["correlation_id"] == "cid-exact-1"
    assert call["module"] == "direct_chat" and call["step"] == "single"
    assert call["status"] == "ok"
    assert call["messages"][0]["text"] == messages[0]["content"]
    assert call["messages"][1]["text"] == messages[1]["content"]

    # Другой payload → другой checksum (хеш не «пустой» и не константа).
    composer.reset_state()
    bodies2: list = []
    _generate(bodies2, messages[:2], correlation_id="cid-exact-2")
    other = composer.last_provider_call(chat_id=-100500)
    assert other["manifest_checksum"] != call["manifest_checksum"]
    composer.reset_state()


def test_fallback_trace_is_the_body_that_went_on_the_wire():
    """INS-EXACT (review F1): при fallback журнал == HTTP-тело, не payload до
    подмены model и не исходные messages.

    Репро ревью: primary 500 → адаптер сокращает user-блок; фактическое тело
    `model=fallback-model`, `user="Q-cut"`. До фикса журнал показывал
    `user="Q"` и другой checksum.
    """
    composer.reset_state()
    bodies: list = []
    client = _TraceClient(bodies, primary_status=500, fallback_active=True)

    def _adapter(payload):
        adapted = dict(payload)
        adapted["messages"] = [
            {"role": "system", "content": payload["messages"][0]["content"]},
            {"role": "user", "content": "Q-cut"},
        ]
        return adapted

    out = asyncio.run(client.generate(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}],
        temperature=0.2, chat_id=-100500, module="direct_chat", step="single",
        correlation_id="cid-fallback-1", fallback_payload_adapter=_adapter))
    assert out == "готовый ответ"
    assert len(bodies) == 2, "primary-попытка и fallback-попытка"

    wire = _last_body(bodies)
    assert wire["model"] == "trace-fallback-1"
    assert wire["messages"][-1]["content"] == "Q-cut"

    call = composer.last_provider_call(chat_id=-100500)
    assert call is not None
    assert call["channel"] == "fallback"
    assert call["model"] == "trace-fallback-1"
    # Главное: checksum и сообщения описывают ИМЕННО отправленное тело.
    assert call["manifest_checksum"] == composer.payload_checksum(wire)
    assert call["messages"][-1]["text"] == "Q-cut"
    assert call["provider"] == "fallback.example"
    assert call["status"] == "ok"
    # Неудачная primary-попытка не подменяет финальный снимок.
    assert all(m["text"] != "Q-cut" for m in call["messages"][:-1])
    composer.reset_state()


def test_generate_chat_is_traced_with_tools():
    """INS-TRACE (review F3): реальный tool-calling вызов тоже в журнале."""
    composer.reset_state()
    bodies: list = []
    client = _TraceClient(bodies)
    tools = [{"type": "function",
              "function": {"name": "search", "parameters": {}}}]
    result = asyncio.run(client.generate_chat(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}],
        tools=tools, chat_id=-100500, module="direct_chat", step="stage1",
        correlation_id="cid-chat-1"))
    assert result.content == "готовый ответ"
    wire = _last_body(bodies)
    assert wire["tools"] == tools

    call = composer.last_provider_call(chat_id=-100500)
    assert call is not None
    assert call["module"] == "direct_chat" and call["step"] == "stage1"
    assert call["correlation_id"] == "cid-chat-1"
    assert call["manifest_checksum"] == composer.payload_checksum(wire)
    assert call["roles"] == ["system", "user"]
    composer.reset_state()


def test_trace_is_r17_safe_and_redacts_chat_id():
    """INS-TRACE (R17): секретов и сырых chat_id в журнале нет."""
    composer.reset_state()
    secret = "sk-live-0123456789abcdef"
    captured: list = []
    _generate(captured, [
        {"role": "system", "content": "ключ api_key=%s" % secret},
        {"role": "user", "content": "Bearer %s" % secret},
    ])
    call = composer.last_provider_call(chat_id=-100500)
    blob = json.dumps(call, ensure_ascii=False)
    assert secret not in blob, "секрет не должен попадать в журнал"
    assert "***" in call["messages"][0]["text"]
    assert "-100500" not in blob, "сырой chat_id не отдаётся"
    assert call["chat_id_redacted"] and call["chat_sha12"]
    # Хеш по-прежнему доказывает фактическое содержимое (до маскировки).
    assert call["messages_checksum"]
    composer.reset_state()


def test_total_fallback_failure_logs_every_attempt():
    """review r2 F2: primary 500 + fallback 500 → в журнале ВСЕ попытки.

    Реально было 4 HTTP-запроса (2 primary + 2 fallback) и одна запись. Теперь
    каждая попытка пишется со `status=error`; `last actual request` — последняя
    fallback-попытка (её тело и checksum).
    """
    composer.reset_state()
    bodies: list = []
    client = _TraceClient(bodies, primary_status=500, fallback_active=True,
                          primary_retries=1, fallback_retries=1,
                          fallback_status=500)
    with pytest.raises(llm_client.LLMError):
        asyncio.run(client.generate(
            [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}],
            chat_id=-100500, module="direct_chat", step="single",
            correlation_id="cid-both-fail"))
    assert len(bodies) == 4, "2 primary + 2 fallback HTTP-попытки"

    calls = composer.provider_calls(chat_id=-100500, limit=10)
    assert len(calls) == 4, "каждая фактическая попытка в журнале"
    assert [c["channel"] for c in reversed(calls)] == \
        ["primary", "primary", "fallback", "fallback"]
    assert all(c["status"] == "error" for c in calls)
    last = composer.last_provider_call(chat_id=-100500)
    assert last["channel"] == "fallback"
    assert last["manifest_checksum"] == composer.payload_checksum(
        _last_body(bodies))
    assert last["error"] == "LLMServerError"
    composer.reset_state()


def test_generate_chat_total_failure_logs_every_attempt():
    """review r3: tool-calling fallback-провал — журнал фиксирует ВСЕ попытки."""
    composer.reset_state()
    bodies: list = []
    client = _TraceClient(bodies, primary_status=500, fallback_active=True,
                          primary_retries=1, fallback_retries=1,
                          fallback_status=500)
    with pytest.raises(llm_client.LLMError):
        asyncio.run(client.generate_chat(
            [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}],
            tools=[{"type": "function", "function": {"name": "search"}}],
            chat_id=-100500, module="direct_chat", step="stage1",
            correlation_id="cid-chat-fail"))
    assert len(bodies) == 4, "2 primary + 2 fallback HTTP-попытки"
    calls = composer.provider_calls(chat_id=-100500, limit=10)
    assert len(calls) == 4, "каждая фактическая попытка в журнале"
    assert [c["channel"] for c in reversed(calls)] == \
        ["primary", "primary", "fallback", "fallback"]
    assert all(c["status"] == "error" for c in calls)
    last = composer.last_provider_call(chat_id=-100500)
    assert last["channel"] == "fallback"
    assert last["manifest_checksum"] == composer.payload_checksum(
        _last_body(bodies))
    composer.reset_state()


def test_generate_chat_empty_content_is_logged_as_error():
    """review r2 F3: 200 + content=null — попытка не теряется, статус error."""
    composer.reset_state()
    bodies: list = []
    client = _TraceClient(bodies, primary_body={"choices": [{"message": {}}]})
    with pytest.raises(llm_client.LLMBadResponseError):
        asyncio.run(client.generate_chat(
            [{"role": "user", "content": "Q"}], chat_id=-100500,
            module="direct_chat", step="stage1", correlation_id="cid-empty"))
    assert len(bodies) == 1
    call = composer.last_provider_call(chat_id=-100500)
    assert call is not None
    assert call["status"] == "error"
    assert call["error"] == "LLMBadResponseError"
    assert call["manifest_checksum"] == composer.payload_checksum(
        _last_body(bodies))
    composer.reset_state()


def test_background_invalid_json_is_not_logged_as_ok():
    """review r2 F4: невалидный JSON фонового канала — status=error, не ok."""
    composer.reset_state()
    bodies: list = []
    client = _TraceClient(bodies, invalid_json=True)
    with pytest.raises(llm_client.LLMBadResponseError):
        asyncio.run(client.generate_background(
            [{"role": "user", "content": "Q"}], purpose="summary_batch",
            deadline=5.0, max_attempts=1))
    assert len(bodies) == 1
    call = composer.last_provider_call()
    assert call is not None
    assert call["module"] == "background"
    assert call["status"] == "error"
    assert call["error"] == "LLMBadResponseError"
    composer.reset_state()
def test_inspector_masks_style_hint_text(api_env, monkeypatch):
    """review r2 F1: hint_text/исключённые инструкции маскируются на границе."""
    from services import prompt_factory as pf
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()
    secret = "sk-live-styletest0123456789"
    long_id = "555666777888"
    env.cache.set("style.policy", {
        "revision": 1,
        "rules": [],
        "soft_instructions": [
            {"text": "Пиши короче. ключ api_key=%s, id %s" % (secret, long_id),
             "scope": "global"},
        ],
    })
    try:
        insp = _run(S.get_inspector(None, env.user, None))
        blob = json.dumps(insp, ensure_ascii=False)
        assert secret not in blob, "секрет в style.hint_text утёк в Inspector"
        assert long_id not in blob, "длинный ID в style-слое утёк"
        assert "***" in blob and "[id]" in blob
        style = insp["preview"]["style"]
        assert style["hint_text"] == S._mask_text(style["hint_text"])
        for row in style.get("excluded") or ():
            assert secret not in str(row.get("text") or "")
        # Структура среза сохраняется: счётчики и лимиты не обнулены.
        assert "hint_chars" in style and "excluded" in style
    finally:
        env.cache.data.pop("style.policy", None)
        composer.reset_state()


def test_inspector_exact_is_the_actual_request(api_env, monkeypatch):
    """INS-EXACT: exact = last actual request, а не превью отдельной настройки."""
    from services import prompt_factory as pf
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()

    # 1. Журнала нет → exact подписан `preview` (не выдаётся за реальный запрос).
    insp = _run(S.get_inspector(None, env.user, None))
    assert insp["exact"]["label"] == "preview"
    assert insp["exact"]["is_actual"] is False
    assert insp["exact"]["system"]
    assert insp["last_call"] == {}

    # 2. Реальный вызов хода → exact берётся из журнала по correlation_id.
    manifest, run_id = _seed_real_turn(writer="l2_writer")
    captured: list = []
    sent_messages = [{"role": "system", "content": manifest.system},
                     {"role": "user", "content": "Вопрос из чата"}]
    _generate(captured, sent_messages, correlation_id=run_id, chat_id=0)

    insp = _run(S.get_inspector(None, env.user, None))
    exact = insp["exact"]
    assert exact["label"] == "last actual request"
    assert exact["is_actual"] is True
    assert exact["correlation_id"] == run_id
    assert exact["checksum"] == composer.payload_checksum(_last_body(captured))
    assert exact["roles"] == ["system", "user"]
    assert exact["system"] == manifest.system      # точный system, не masked
    assert exact["messages"][0]["role"] == "system"
    assert exact["model"] == "trace-model-1"
    assert insp["last_call"]["checksum"] == exact["checksum"]
    composer.reset_state()


def test_inspector_skip_reasons_are_human(api_env, monkeypatch):
    """INS-SKIPREASON: русская причина, машинный код — отдельным полем."""
    from services import prompt_factory as pf
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()
    insp = _run(S.get_inspector(None, env.user, None))

    rows = insp["skip_reasons"]
    assert rows, "в предпросмотре есть пропущенные слои"
    for row in rows:
        assert row["text"] and row["text"].endswith(".")
        assert row["text"] != row["code"]
        assert row["label"] and not row["label"].startswith("_")
    # Конкретные требования источника §6: few_shot/channel_output объяснимы.
    samples = composer.skip_reason_label("samples_absent")
    assert "Примеры не выбраны" in samples
    assert "форматный блок" in composer.skip_reason_label(
        "channel_output_not_required")
    # Каждый слой в таблице тоже несёт человеческую причину.
    for layer in insp["preview"]["layers"]:
        assert layer["label"]
        if not layer["rendered"]:
            assert layer["skip_reason_human"]
        else:
            assert layer["skip_reason_human"] == ""
    composer.reset_state()


def test_inspector_hierarchy_has_text_source_revision(api_env, monkeypatch):
    """INS-HIERARCHY: клик по элементу даёт текст, источник и редакцию."""
    env = api_env
    from services import prompt_factory as pf
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()
    manifest, _run_id = _seed_real_turn(writer="l2_writer")

    insp = _run(S.get_inspector(None, env.user, None))
    groups = insp["sent"]["hierarchy"]
    assert [g["group"] for g in groups][:2] == ["contract", "core"]
    items = [i for g in groups for i in g["items"]]
    assert items
    rendered = [i for i in items if i["rendered"]]
    assert rendered, "в сборке есть включённые блоки"
    for item in rendered:
        assert item["text"], "включённый блок отдаёт свой точный текст"
        assert item["source"] and item["revision"] and item["label"]
    core = next(i for i in items if i["layer"] == "core")
    assert core["rendered"] is False           # сид без CoreRef — честно
    assert core["skip_reason_human"]
    # Текст включённого блока == текст из манифеста (не пересказ).
    channel = next(i for i in items if i["layer"] == "channel_contract")
    assert channel["text"] == next(t.text for t in manifest.layers
                                   if t.layer == "channel_contract" and t.text)
    # Причина пропуска не остаётся пустой ни в одном пропущенном узле.
    for item in items:
        if not item["rendered"]:
            assert item["skip_reason_human"]
    composer.reset_state()


def test_conflict_classes_come_from_real_data():
    """INS-CONFLICT: классы конфликтов — из реальных правил, без выдумки."""
    exact = {"revision": 1, "rules": [
        {"id": "dash-1", "kind": "dash", "params": {"mode": "em"},
         "strictness": "hard", "scope": "global", "enabled": True}]}
    same = {"revision": 2, "rules": [
        {"id": "dash-1", "kind": "dash", "params": {"mode": "em"},
         "strictness": "hard", "scope": "chat", "enabled": True}]}
    clash = {"revision": 3, "rules": [
        {"id": "dash-2", "kind": "dash", "params": {"mode": "hyphen"},
         "strictness": "hard", "scope": "chat", "enabled": True}]}

    inherited = S._style_rule_conflicts(exact, same)
    assert inherited == [], "одинаковое правило — наследование, не конфликт"

    detected = S._style_rule_conflicts(exact, clash)
    assert len(detected) == 1
    assert detected[0]["class"] == "typography"
    assert detected[0]["conflict_id"] == "chat_global_rule_override"
    assert "dash" in detected[0]["detail"]

    # Классы собираются с явным счётом; пустой класс не «найден».
    detail = S._inspector_conflicts([], [], exact, clash)
    typography = next(c for c in detail["classes"]
                      if c["class"] == "typography")
    assert typography["detected"] == 1 and typography["items"]
    unknown = next(c for c in detail["classes"]
                   if c["class"] == "profanity_case")
    assert unknown["detected"] == 0 and unknown["items"] == []
    assert detail["coverage_note"]


def test_composer_reports_soul_legacy_label_as_conflict():
    """INS-CONFLICT: устаревшая метка SOUL-* в payload — реальный конфликт."""
    composer.reset_state()
    manifest = composer.compose_prompt(composer.PromptPlan(
        profile=composer.PROFILE_SPEECH_PLAIN, writer="l2_writer",
        chat_id=0, base_prompt="РОЛЬ: контракт",
        identity=composer.IdentityRef(text="Ты участник чата. SOUL-16.5.0",
                                      source="global"),
        gates=composer.gates_from_config()))
    ids = [c.conflict_id for c in manifest.conflicts]
    assert "soul_legacy_label_in_payload" in ids
    record = next(c for c in manifest.conflicts
                  if c.conflict_id == "soul_legacy_label_in_payload")
    assert "SOUL-16.5.0" in record.detail
    composer.reset_state()


def test_inspector_hierarchy_is_masked_but_keeps_provenance(api_env,
                                                            monkeypatch):
    """INS-PRIVACY (review F2): иерархия отдаёт МАСКИРОВАННЫЙ текст.

    Секрет и длинный Telegram-ID не должны попадать ни в JSON ответа, ни в DOM
    (проверяется здесь на уровне API; DOM — e2e). Структура и редакции
    сохраняются: маскировка не ломает клик-сквозную диагностику.
    """
    from services import prompt_factory as pf
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()
    secret = "sk-live-abcdef0123456789"
    long_id = "123456789012"
    manifest = composer.compose_prompt(composer.PromptPlan(
        profile=composer.PROFILE_SPEECH_PLAIN, writer="l2_writer",
        chat_id=0, run_id="cid-mask-1", base_prompt="РОЛЬ: контракт",
        identity=composer.IdentityRef(
            text="Правило личности. api_key=%s; участник %s" % (secret,
                                                                 long_id),
            source="global"),
        gates=composer.gates_from_config()))

    insp = _run(S.get_inspector(None, env.user, None))
    blob = json.dumps(insp, ensure_ascii=False)
    assert secret not in blob, "секрет попал в JSON/DOM Inspector"
    assert long_id not in blob, "полный Telegram-ID попал в JSON/DOM"
    assert "***" in blob and "[id]" in blob

    items = [i for g in insp["hierarchy"] for i in g["items"]]
    identity = next(i for i in items if i["layer"] == "identity")
    assert identity["rendered"] is True
    assert identity["revision"] and identity["source"] == "global"
    assert "Правило личности" in identity["text"]     # структура сохранена
    assert identity["text"] != next(t.text for t in manifest.layers
                                    if t.layer == "identity")
    composer.reset_state()


def test_inspector_declares_trace_coverage(api_env, monkeypatch):
    """INS-TRACE (review F3): покрытие каналов объявлено, а не молчит."""
    from services import prompt_factory as pf
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()
    insp = _run(S.get_inspector(None, env.user, None))
    coverage = {row["channel"]: row for row in insp["trace_coverage"]}
    for channel in ("generate", "generate_chat", "generate_background",
                    "generate_worker"):
        assert coverage[channel]["covered"] is True, channel
        assert coverage[channel]["reason"]
    assert coverage["embed"]["covered"] is False
    assert "эмбеддинг" in coverage["embed"]["reason"]
    composer.reset_state()


def test_inspector_ui_surfaces_exact_and_skip_reason():
    """UI не прячет точный промпт и причину пропуска (INS-EXACT/SKIPREASON)."""
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    for anchor in ("data-speech-exact", "data-speech-exact-checksum",
                   "data-speech-skip-reasons", "data-speech-hierarchy"):
        assert anchor in index, anchor
    assert "speechExactLabel" in app_js
    assert "speechInspectorSkipText" in app_js
    # Имя не перекрывает существующий словарь причин прохода формы (TJ-7/16).
    assert app_js.count("speechSkipReasonText: function") == 1


# ═══════════════════════════════════════════════════════════════════════════
# P0IM-PB-ACCESS: существующий Inspector как ЕДИНСТВЕННАЯ точка полного
# текста. Отбор аддитивный (`correlation_id`), RBAC/маскировка — прежние;
# промах кольца — honest not_recorded, а НЕ превью текущих настроек.
# ═══════════════════════════════════════════════════════════════════════════

def _record_meme_call(api_env, *, correlation_id: str, chat_id: int,
                      text: str = "Текст проверки") -> None:
    composer.record_provider_call(
        payload={"model": "unit/model-x", "messages": []},
        messages=[{"role": "system",
                   "content": "Системная инструкция; key sk-live-ABC123456789"},
                  {"role": "user", "content": text}],
        model="unit/model-x", provider="provider.example",
        module="initiative", step="meme_joke",
        correlation_id=correlation_id, chat_id=chat_id)


#: §P0IM-PB-ACCESS (Reviewer blocker 1): в режиме correlation_id в ответе
#: НЕТ текущей сборки — только exact-запись кольца или honest not_recorded.
CORRELATION_FORBIDDEN_KEYS = (
    "preview", "sent", "core", "layers", "style", "hierarchy",
    "skip_reasons", "conflicts_detail", "sent_note", "trace_coverage",
)


def _current_build_marker(api_env) -> str:
    """Кусок ТЕКУЩЕЙ сборки: его присутствие в ответе = утечка превью."""
    preview = _run(S._preview_manifest(
        api_env.cache, api_env.chat_id,
        text="(предпросмотр без сообщения)"))
    candidates = [preview.get("system_masked")]
    candidates += [row.get("text") for row in (preview.get("layer_texts") or [])]
    for value in candidates:
        text = str(value or "").strip()
        if len(text) >= 20:
            return text[:40]
    return ""


def _assert_no_current_build(api_env, payload: dict) -> None:
    for key in CORRELATION_FORBIDDEN_KEYS:
        assert key not in payload, (
            "в ответе correlation_id осталась текущая сборка: %s" % key)
    marker = _current_build_marker(api_env)
    assert marker, "текущая сборка пуста — проверка утечки невозможна"
    dumped = json.dumps(payload, ensure_ascii=False)
    assert marker not in dumped, (
        "в ответ correlation_id утёк текст текущей сборки: %r" % marker)
    # Кольцо общее на процесс, а не «на чат» (Reviewer blocker 2).
    retention = str(payload.get("retention") or "")
    note = str(payload.get("last_run_note") or "")
    for value in (retention, note):
        assert "процесс" in value, "политика хранения не названа: " + value
        assert "на чат" not in value, "ложное «на чат» в политике: " + value


def test_inspector_correlation_filter_returns_the_exact_meme_call(api_env):
    """Точный correlation_id находит СВОЙ вызов; секреты маскируются."""
    composer.reset_state()
    try:
        _record_meme_call(api_env, correlation_id="JOB#meme_joke",
                          chat_id=api_env.chat_id)
        # Чужой чат и чужая корреляция: не должны подставиться.
        _record_meme_call(api_env, correlation_id="OTHER#meme_joke",
                          chat_id=-100999, text="ЧУЖОЙ-ЧАТ-ТЕКСТ")
        payload = _run(S._inspector_payload(
            api_env.cache, api_env.user, api_env.ctx, api_env.chat_id,
            correlation_id="JOB#meme_joke"))
        assert payload["requested_correlation_id"] == "JOB#meme_joke"
        assert payload["requested_correlation_recorded"] is True, payload
        assert payload["last_run_present"] is True, payload
        assert payload["ring_limit"] == 24, payload
        # Reviewer blocker 1: только exact, без текущей сборки/превью.
        _assert_no_current_build(api_env, payload)
        exact = payload["exact"]
        assert exact["is_actual"] is True, exact
        assert exact["correlation_id"] == "JOB#meme_joke", exact
        assert exact["module"] == "initiative" and exact["step"] == "meme_joke"
        text = json.dumps(exact, ensure_ascii=False)
        assert "sk-live-ABC123456789" not in text, "секрет не маскирован"
        assert "ЧУЖОЙ-ЧАТ-ТЕКСТ" not in text, "чужой чат не изолирован"
        assert "Текст проверки" in text, "текст своего вызова не показан"
    finally:
        composer.reset_state()


def test_inspector_correlation_miss_is_not_a_preview(api_env):
    """Промах кольца: not_recorded БЕЗ текущей сборки, а не превью."""
    composer.reset_state()
    try:
        payload = _run(S._inspector_payload(
            api_env.cache, api_env.user, api_env.ctx, api_env.chat_id,
            correlation_id="JOB#meme_summary"))
        assert payload["requested_correlation_id"] == "JOB#meme_summary"
        assert payload["requested_correlation_recorded"] is False, payload
        assert payload["last_run_present"] is False, payload
        assert "not_recorded" in payload["last_run_note"], payload["last_run_note"]
        assert "предпросмотр" not in str(payload["last_run_note"]).lower(), (
            "промах кольца подписан как превью: " + payload["last_run_note"])
        _assert_no_current_build(api_env, payload)
        exact = payload["exact"]
        assert exact["is_actual"] is False, exact
        assert exact["status"] == "not_recorded", exact
        assert exact["messages"] == [] and exact["system"] == "", exact
        assert exact["correlation_id"] == "JOB#meme_summary", exact
    finally:
        composer.reset_state()


def test_inspector_correlation_foreign_chat_returns_no_text(api_env):
    """Чужая корреляция/чужой чат: not_recorded, ни текста, ни текущей сборки."""
    composer.reset_state()
    try:
        _record_meme_call(api_env, correlation_id="FOREIGN#meme_joke",
                          chat_id=-100999, text="ЧУЖОЙ-ЧАТ-ТЕКСТ")
        payload = _run(S._inspector_payload(
            api_env.cache, api_env.user, api_env.ctx, api_env.chat_id,
            correlation_id="FOREIGN#meme_joke"))
        assert payload["requested_correlation_recorded"] is False, payload
        assert payload["exact"]["status"] == "not_recorded", payload["exact"]
        _assert_no_current_build(api_env, payload)
        dumped = json.dumps(payload, ensure_ascii=False)
        assert "ЧУЖОЙ-ЧАТ-ТЕКСТ" not in dumped, "чужой чат утёк"
    finally:
        composer.reset_state()


def test_ring_is_process_wide_not_per_chat(api_env):
    """Reviewer blocker 2: 24 записи ОДНОГО процесса, чужие вызовы вытесняют."""
    composer.reset_state()
    try:
        _record_meme_call(api_env, correlation_id="OWN#meme_joke",
                          chat_id=api_env.chat_id, text="СВОЙ-ТЕКСТ-ПОПЫТКИ")
        own = composer.provider_calls(chat_id=api_env.chat_id,
                                      limit=S.FULL_RING_LIMIT)
        assert [c["correlation_id"] for c in own] == ["OWN#meme_joke"], own
        for index in range(25):
            _record_meme_call(api_env,
                              correlation_id="OTHER-%d#meme_joke" % index,
                              chat_id=-100999, text="ЧУЖОЙ-%d" % index)
        # 25 вызовов другого чата вытеснили запись этого: кольцо процесса.
        own_after = composer.provider_calls(chat_id=api_env.chat_id,
                                            limit=S.FULL_RING_LIMIT)
        assert own_after == [], own_after
        payload = _run(S._inspector_payload(
            api_env.cache, api_env.user, api_env.ctx, api_env.chat_id,
            correlation_id="OWN#meme_joke"))
        assert payload["requested_correlation_recorded"] is False, payload
        _assert_no_current_build(api_env, payload)
        assert "СВОЙ-ТЕКСТ-ПОПЫТКИ" not in json.dumps(payload,
                                                      ensure_ascii=False)
        assert payload["ring_limit"] == S.FULL_RING_LIMIT
    finally:
        composer.reset_state()


def test_inspector_correlation_path_keeps_rbac(monkeypatch):
    """Аддитивный отбор не обходит `_can_edit_inspector` (403)."""
    denied = SimpleNamespace(is_global_admin=False,
                             effective_permissions=None)
    user = SimpleNamespace(id=1)

    async def access(request, _user, x_chat_id):
        return None, -100500, denied

    monkeypatch.setattr(S, "_access", access)
    with pytest.raises(Exception) as exc:
        _run(S.get_inspector(None, user, None, "JOB#meme_summary"))
    assert getattr(exc.value, "status_code", None) == 403


def test_inspector_endpoint_passes_the_correlation_query(api_env):
    """`GET /speech/inspector?correlation_id=` доводит отбор до payload."""
    composer.reset_state()
    try:
        _record_meme_call(api_env, correlation_id="JOB#meme_summary",
                          chat_id=api_env.chat_id)
        payload = _run(S.get_inspector(
            None, api_env.user, str(api_env.chat_id), "JOB#meme_summary"))
        assert payload["requested_correlation_id"] == "JOB#meme_summary"
        assert payload["requested_correlation_recorded"] is True, payload
        assert payload["exact"]["correlation_id"] == "JOB#meme_summary"
        # Без параметра — прежнее поведение (последний ход чата), не пусто.
        legacy = _run(S.get_inspector(None, api_env.user,
                                      str(api_env.chat_id), ""))
        assert legacy["requested_correlation_id"] == ""
        assert legacy["requested_correlation_recorded"] is False
    finally:
        composer.reset_state()
