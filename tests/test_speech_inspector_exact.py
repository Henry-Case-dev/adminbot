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
import sys
from pathlib import Path

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


class _TraceClient(llm_client.LLMClient):
    """Клиент без сети: транспорт подменён, всё остальное — реальный код."""

    def __init__(self, captured):
        self._chat_model = "trace-model-1"
        self._fallback_model = "trace-fallback-1"
        self._fallback_active = False
        self._base_url = "https://provider.example/v1"
        self._fallback_base_url = "https://fallback.example/v1"
        self.captured = captured

    async def _resolve_api_key_and_source(self, chat_id=None):
        return "test-key", "global"

    async def _post_with_key(self, path, payload, chat_id=None, key=None):
        self.captured.append(json.loads(json.dumps(payload)))
        return _FakeResponse()

    async def _record_global_usage(self, *args, **kwargs):
        return None

    async def _record_analytics(self, *args, **kwargs):
        return None


def _generate(captured, messages, *, correlation_id="cid-exact-1",
              chat_id=-100500):
    client = _TraceClient(captured)
    out = asyncio.run(client.generate(
        messages, temperature=0.3, chat_id=chat_id, module="direct_chat",
        step="single", correlation_id=correlation_id))
    return out


def test_trace_checksum_matches_actually_sent_payload():
    """INS-EXACT/INS-TRACE: checksum в Inspector == тело запроса в транспорте."""
    composer.reset_state()
    captured: list = []
    messages = [
        {"role": "system", "content": "СИСТЕМНАЯ РОЛЬ: контракт канала\n\nCore"},
        {"role": "user", "content": "Вопрос пользователя"},
        {"role": "user", "content": "<dig_result>факт</dig_result>"},
    ]
    assert _generate(captured, messages) == "готовый ответ"
    assert len(captured) == 1
    sent = captured[0]

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
    captured2: list = []
    _generate(captured2, messages[:2], correlation_id="cid-exact-2")
    other = composer.last_provider_call(chat_id=-100500)
    assert other["manifest_checksum"] != call["manifest_checksum"]
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
    assert exact["checksum"] == composer.payload_checksum(captured[0])
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
