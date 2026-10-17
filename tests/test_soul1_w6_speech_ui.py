"""SOUL-1 / W6 — «Речь и характер»: UI-контракт и путь записи.

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/W6 (SOUL-AMD.6.1–6.6, SOUL-AMD.8.3,
SOUL-10.0–10.5, SOUL-16.5.0).

Проверяет ровно то, за что отвечает слайс:

* единственная точка входа раздела и её маршрут (без переделки навигации, без
  шестой страницы хаба «ИИ»);
* все правки речи идут ТОЛЬКО через реестр (``write_speech_value``/фабрику),
  чат-скоуп не трогает глобальное значение (SOUL-AMD.1.1/4.1/4.3);
* заводской сброс, история и откат работают через тот же путь записи;
* витрины «Стиль письма»/«Выражение»/«Возможности бота»/Inspector отдают
  документированные поля, а отсутствующие контуры (W4) честно объявлены, а не
  подменены вторым стором.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
APP_PY = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
SPEECH_PY = (ROOT / "web" / "api" / "speech.py").read_text(encoding="utf-8")

from services import prompt_factory as pf  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from web.api import speech as S  # noqa: E402


class _AwaitResult:
    """Результат, который можно и await'ить, и игнорировать (смешанные вызовы:
    prompt_factory делает ``await cache.set(...)``, style_policy — нет)."""

    def __await__(self):
        if False:               # pragma: no cover — генератор-обёртка
            yield None
        return None


class _Cache:
    """Минимальный двойник ConfigCache (get/set/get_updated_at) для round-trip."""

    def __init__(self):
        self.data = {}
        self.updated = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def get_updated_at(self, key):
        return self.updated.get(key)

    def set(self, key, value, category=None):
        self.data[key] = value
        self.updated[key] = "in-memory"
        return _AwaitResult()

    async def set_many(self, items):
        for key, value, category in items:
            self.set(key, value, category)


@pytest.fixture()
def api_env(monkeypatch):
    """Изолированный скоуп: фейковый cache + in-memory chat_params."""
    cache = _Cache()
    chat_store: dict = {}

    async def get_root(chat_id, pg=None):
        store = chat_store.get(int(chat_id)) or {}
        return {"overrides": dict(store.get("overrides") or {})}

    async def set_root(chat_id, patch, **kwargs):
        # Контракт chat_params.set_chat_params: namespace ЗАМЕНЯЕТСЯ целиком
        # (services/chat_params.py:447-450) — иначе «сброс переопределения»
        # (pop ключа) не был бы наблюдаем.
        store = chat_store.setdefault(int(chat_id), {})
        for ns in ("overrides", "gates", "keys", "perm_overrides", "meta"):
            if ns in patch and isinstance(patch[ns], dict):
                store[ns] = dict(patch[ns])

    monkeypatch.setattr("services.chat_params.get_all_chat_params", get_root)
    monkeypatch.setattr("services.chat_params.set_chat_params", set_root)

    ctx = SimpleNamespace(is_global_admin=True, effective_permissions=None)
    user = SimpleNamespace(id=4242)

    async def access(request, _user, x_chat_id):
        chat_id = int(x_chat_id) if x_chat_id else None
        return cache, chat_id, ctx

    monkeypatch.setattr(S, "_access", access)
    return SimpleNamespace(cache=cache, chat=chat_store, user=user,
                          ctx=ctx, chat_id=-100500)


# ── Навигация и состав экрана (SOUL-AMD.6.1/6.3, SOUL-10.0) ─────────────────

def test_entry_lives_inside_ai_without_reworking_navigation():
    # Маршрут специального экрана внутри «ИИ» + родитель «ИИ» для «Назад».
    assert "'#/ai/speech': 'speech'," in APP_JS
    assert "speech: '#/ai/speech'," in APP_JS
    assert "'#/ai/speech': '#/ai'," in APP_JS
    assert "if (tabId === 'speech')" in APP_JS
    # Человекочитаемая подпись (не сырой hash) для пути назад.
    assert "if (route === '#/ai/speech') return 'Речь и характер';" in APP_JS
    # Вход — карточка на существующем экране «Личность и стиль» внутри «ИИ»;
    # ровно 5 страниц хаба сохранены (переделки навигации нет).
    assert 'data-speech-entry' in INDEX
    hub = APP_JS[APP_JS.index("var HUBS_V2 = {"):APP_JS.index("'#/memory': {")]
    assert hub.count("route: '#/ai/") == 5
    assert "Речь и характер" in hub  # подпись карточки «Личность и стиль»


def test_screen_has_required_sections_and_single_screen_mode():
    for anchor in ("data-speech-card", "data-speech-entry", "data-speech-diff",
                   "data-speech-style-preview", "data-speech-block-detail",
                   "data-speech-preview-payload", "data-speech-sent-system"):
        assert anchor in INDEX, anchor
    for section in ("core", "style", "expression", "humor", "examples", "try",
                    "learning", "all", "inspector", "capabilities"):
        assert "speechSection === '%s'" % section in INDEX, section
    # Один экран за раз: «Назад» есть, витрина скрывается при открытом разделе.
    assert "speechBack()" in INDEX and "← Назад" in INDEX
    assert 'v-else-if="!speechSection"' in INDEX


def test_long_lines_scroll_inside_components_and_oauth_targets():
    assert ".speech-pre" in CSS and "overflow: auto" in CSS
    assert "overflow-wrap: anywhere" in CSS
    # Тач-цели ≥44px у действий/карточек/полей раздела.
    assert ".speech-actions .btn-accent" in CSS and "min-height: 44px" in CSS
    assert ".speech-back" in CSS and ".speech-editor" in CSS
    # Одна колонка ≤599px; две колонки только на ≥1024px (редактор+предпросмотр).
    assert "@media (max-width: 599px)" in CSS
    assert "@media (min-width: 1024px)" in CSS
    assert "grid-template-columns: minmax(0, 1fr);" in CSS
    # Полигональный фон/линза/токены не затронуты новым CSS-блоком.
    w6 = CSS[CSS.index("SOUL-1 W6 — «Речь и характер»"):]
    for forbidden in ("polygon-background", "#lg-lens", "--lg-tint-hero:",
                      "backdrop-filter: none"):
        assert forbidden not in w6, forbidden


def test_drafts_never_lost_by_refresh_or_navigation():
    """Черновик владельца важнее серверного снапшота (SOUL-10.P3)."""
    assert ("speechDirty: { core: false, style: false, expression: false }"
            in APP_JS)
    assert "if (!this.speechDirty.core)" in APP_JS
    assert "if (!this.speechDirty.style)" in APP_JS
    assert "if (!this.speechDirty.expression)" in APP_JS
    for marker in ("this.speechDirty.style = true;",
                   "this.speechDirty.expression = true;",
                   "this.speechDirty.core = true;",
                   "this.speechDirty.style = false;",
                   "this.speechDirty.expression = false;",
                   "this.speechDirty.core = false;"):
        assert marker in APP_JS, marker
    # «Назад» лишь переключает раздел — черновики живут в состоянии экрана.
    assert "speechBack: function () {" in APP_JS
    assert "this.speechSection = '';" in APP_JS


def test_router_is_mounted_with_single_prefix():
    assert "from web.api.speech import speech_router" in APP_PY
    assert "app.include_router(speech_router, prefix=\"/api\")" in APP_PY


def test_endpoints_are_actually_mounted_behind_auth():
    """Реальное монтирование: известные маршруты → 401 (auth), чужой → 404."""
    from starlette.testclient import TestClient

    from services.config_cache import ConfigCache
    from web.app import create_app

    class _StubPG:
        pool = None

    app = create_app(ConfigCache(pg=_StubPG()))
    client = TestClient(app)
    for path in ("/api/speech/overview", "/api/speech/blocks",
                 "/api/speech/inspector", "/api/speech/capabilities"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/speech/no-such-endpoint").status_code == 404


# ── Путь записи (SOUL-AMD.1.1/4.1/6.2) ─────────────────────────────────────

def test_writes_go_through_registry_api_only():
    # Никаких прямых записей речевых ключей из UI-слоя.
    assert "write_speech_value" in SPEECH_PY
    assert "apply_factory_reset" in SPEECH_PY
    assert "reset_chat_override" in SPEECH_PY
    assert "cache.set(spec.pg_key" not in SPEECH_PY
    assert not re.search(r"cache\.set\(\s*\"prompts\.", SPEECH_PY)
    # Статический отбор ловит только литеральные формы; единственные прямые
    # записи UI-слоя — документы новых сущностей на существующем контуре.
    # W4: единый хелпер `_write_document(cache, chat, key, …)` пишет документы
    # сущностей; его ключи обязаны быть из ЗАКРЫТОГО набора (никаких prompts.*).
    direct = re.findall(r"cache\.set\(\s*([A-Za-z_][A-Za-z0-9_.]*)", SPEECH_PY)
    assert sorted(set(direct)) == ["EXPRESSION_DOC_KEY", "key",
                                   "pr.CORE_DOC_KEY"], direct
    docs = set(re.findall(
        r"_write_document\(\s*\n?\s*[^,]+,\s*[^,]+,\s*([A-Za-z_][A-Za-z0-9_.]*)",
        SPEECH_PY))
    docs.discard("key")           # само определение хелпера (сигнатура)
    assert docs == {"humor_craft.HUMOR_CRAFT_DOC_KEY",
                    "samples_lib.SELECTION_DOC_KEY"}, docs
    assert "prompts." not in " ".join(sorted(docs))
    # Документы новых сущностей живут на существующем контуре.
    assert S.EXPRESSION_DOC_KEY == "character.expression"
    assert "chat_params.set_chat_params" in SPEECH_PY


def test_write_path_is_guarded_at_runtime_not_only_statically(api_env, monkeypatch):
    """Динамический сторож (review-w6 minor): запись мимо реестра ловится.

    Статический тест фальсифицируем для записи через переменную, поэтому все
    реальные записи round-trip'а идут через сторож: любой ``prompts.*``-ключ
    пишет ТОЛЬКО фабрика/реестр (``services.prompt_factory``), а прямые записи
    документов из UI-слоя не меняют ТЕКСТ (только метаданные). Ключ, собранный
    в переменной, сторожем ловится так же, как литеральный.
    """
    import sys as _sys

    env = api_env
    calls: list = []
    factory_writes = {"n": 0}

    class _Guarded(_Cache):
        def _check(self, key, value):
            name = str(key or "")
            caller = _sys._getframe(2).f_globals.get("__name__", "?")
            calls.append((name, caller))
            if name.startswith("prompts.") and caller != "services.prompt_factory":
                raise AssertionError("запись %s мимо реестра из %s"
                                     % (name, caller))
            if name == pr.CORE_DOC_KEY:
                if caller == "services.prompt_factory":
                    factory_writes["n"] += 1
                else:
                    before = self.data.get(name)
                    before = before if isinstance(before, dict) else {}
                    after = value if isinstance(value, dict) else {}
                    for field in ("full_text", "compact_text"):
                        if after.get(field) != before.get(field):
                            raise AssertionError(
                                "текст Core записан из %s мимо реестра" % caller)

        def set(self, key, value, category=None):
            self._check(key, value)
            return super().set(key, value, category)

        async def set_many(self, items):
            # Без super(): он вызывает self.set → кадр вызывателя подменяется.
            for key, value, _category in items:
                self._check(key, value)
                self.data[key] = value
                self.updated[key] = "in-memory"

    guard = _Guarded()

    async def access(request, _user, x_chat_id):
        return guard, (int(x_chat_id) if x_chat_id else None), env.ctx

    monkeypatch.setattr(S, "_access", access)
    monkeypatch.setattr(pf, "_default_cache", lambda: guard)

    factory_full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    _run(S.post_block(pr.CORE_FULL_BLOCK_ID, None, env.user,
                      S.BlockWrite(text=factory_full + "\n\nПроверка сторожа."),
                      None))
    _run(S.post_core_meta(None, env.user, S.CoreMeta(detail_level="full"), None))
    _run(S.post_block_reset(pr.CORE_FULL_BLOCK_ID, None, env.user,
                            S.BlockReset(mode="factory", apply=True), None))
    # Сторож не вакуумный: текст писал реестр, метаданные — UI-слой.
    assert factory_writes["n"] > 0, "реестр не писал текст Core"
    assert any(name == pr.CORE_DOC_KEY and caller == "web.api.speech"
               for name, caller in calls), "метаданные Core писались не UI-слоем"


def test_core_roundtrip_global_then_chat_isolation(api_env, monkeypatch):
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    asyncio_run = _run

    # 1. Заводское состояние.
    core = asyncio_run(S.get_core(None, env.user, None))
    assert core["editions"]["full"]["source"] in ("default", "code")
    factory_full = core["factory"]["full_text"]
    assert factory_full.strip()

    # 2. Правка ВЛАДЕЛЬЦА полной редакции (глобально) через API реестра.
    new_text = factory_full + "\n\nПроверка владельца: держим тон."
    res = asyncio_run(S.post_block(pr.CORE_FULL_BLOCK_ID, None, env.user,
                                   S.BlockWrite(text=new_text), None))
    assert res["ok"] and res["result"]["applied"] is True
    assert res["result"]["revision"].startswith("act:")
    assert res["result"]["provenance"]["kind"] == "owner_edit"

    core = asyncio_run(S.get_core(None, env.user, None))
    assert core["editions"]["full"]["text"] == new_text
    assert core["editions"]["full"]["source"] == "global"
    assert core["editions"]["full"]["differs_from_factory"] is True
    assert core["editions"]["full"]["revision"].startswith("act:")

    # 3. Правка ЧАТА не трогает глобальное значение.
    chat_text = "локальный вариант для этого чата"
    res = asyncio_run(S.post_block(pr.CORE_FULL_BLOCK_ID, None, env.user,
                                   S.BlockWrite(text=chat_text, scope="chat"),
                                   str(env.chat_id)))
    assert res["result"]["applied"] is True
    assert res["result"]["scope"] == "chat"
    global_after = env.cache.get(pr.CORE_DOC_KEY)
    assert global_after["full_text"] == new_text, "глобальный Core изменён чатом"

    chat_core = asyncio_run(S.get_core(None, env.user, str(env.chat_id)))
    assert chat_core["editions"]["full"]["text"] == chat_text
    assert chat_core["editions"]["full"]["source"] == "chat"
    assert chat_core["inheritance"] == "chat"

    # 4. Сброс переопределения чата: наследование, НЕ заводской сброс.
    res = asyncio_run(S.post_block_reset(
        pr.CORE_FULL_BLOCK_ID, None, env.user, S.BlockReset(mode="chat"),
        str(env.chat_id)))
    assert res["inherits"] == "global"
    chat_core = asyncio_run(S.get_core(None, env.user, str(env.chat_id)))
    assert chat_core["editions"]["full"]["text"] == new_text
    assert chat_core["editions"]["full"]["source"] == "global"

    # 5. Заводской сброс (с предпросмотром) + откат к предыдущей ревизии.
    plan = asyncio_run(S.post_block_reset(
        pr.CORE_FULL_BLOCK_ID, None, env.user,
        S.BlockReset(mode="factory", apply=False), None))
    assert plan["applied"] is False and plan["plan"]["applies"] is True
    assert plan["plan"]["changed"] is True

    applied = asyncio_run(S.post_block_reset(
        pr.CORE_FULL_BLOCK_ID, None, env.user,
        S.BlockReset(mode="factory", apply=True), None))
    assert applied["ok"] is True
    core = asyncio_run(S.get_core(None, env.user, None))
    assert core["editions"]["full"]["differs_from_factory"] is False
    assert core["editions"]["full"]["text"] == factory_full
    assert core["history"], "предыдущая ревизия обязана остаться в истории"

    history = asyncio_run(pf.history_for(pr.CORE_FULL_BLOCK_ID,
                                         cache=env.cache))
    target = history[0]
    rolled = asyncio_run(S.post_block_rollback(
        pr.CORE_FULL_BLOCK_ID, None, env.user,
        S.BlockRollback(sha256_12=target["sha256_12"]), None))
    assert rolled["ok"] is True
    core = asyncio_run(S.get_core(None, env.user, None))
    assert core["editions"]["full"]["text"] == new_text


def test_core_compact_edition_and_level_are_separate(api_env, monkeypatch):
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    core = _run(S.get_core(None, env.user, None))
    factory_compact = core["factory"]["compact_text"]
    assert factory_compact.strip()

    res = _run(S.post_block(pr.CORE_COMPACT_BLOCK_ID, None, env.user,
                            S.BlockWrite(text="Коротко: язвительно, по делу."),
                            None))
    assert res["ok"] is True
    core = _run(S.get_core(None, env.user, None))
    # Обе редакции независимы: правка компактной не обнуляет полную.
    assert core["editions"]["compact"]["text"] == "Коротко: язвительно, по делу."
    assert core["editions"]["full"]["text"].strip()

    # Режим по умолчанию — отдельное документное поле.
    meta = _run(S.post_core_meta(None, env.user, S.CoreMeta(detail_level="full"),
                                 None))
    assert meta["ok"] is True
    core = _run(S.get_core(None, env.user, None))
    assert core["document"]["detail_level"] == "full"
    assert core["selection"]["level"] == "full"


def test_style_policy_save_and_chat_reset(api_env, monkeypatch):
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    view = _run(S.get_style(None, env.user, None, "regular"))
    assert view["rule_kinds"], "каталог kind обязателен для редактора"
    assert view["preset_documents"], "состав шаблонов отдаёт сервер"
    preset = view["preset_documents"]["no_trailing_period"]
    assert preset["rules"], "у шаблона есть реальные правила"

    doc = {"rules": preset["rules"], "soft_instructions": []}
    saved = _run(S.post_style(None, env.user, S.StyleWrite(document=doc), None))
    assert saved["ok"] is True
    assert saved["result"]["revision"] >= 1
    view = _run(S.get_style(None, env.user, None, "regular"))
    assert any(r["kind"] == "trailing_period" for r in view["rules"])
    assert view["document"]["inheritance"] == "global"

    # Чат-скоуп: тот же документ как override + сброс к наследованию.
    saved = _run(S.post_style(None, env.user,
                              S.StyleWrite(document=doc, scope="chat"),
                              str(env.chat_id)))
    assert saved["result"]["scope"] == "chat"
    chat_view = _run(S.get_style(None, env.user, str(env.chat_id), "regular"))
    assert chat_view["document"]["inheritance"] == "chat"
    reset = _run(S.post_style_reset_chat(None, env.user, str(env.chat_id)))
    assert reset["ok"] is True
    chat_view = _run(S.get_style(None, env.user, str(env.chat_id), "regular"))
    assert chat_view["document"]["inheritance"] == "global"
    # Глобальный документ не пострадал от сброса чата.
    assert env.cache.get("style.policy"), "глобальная политика потеряна"


def test_style_preview_is_deterministic_and_shows_before_after(api_env,
                                                              monkeypatch):
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    preview = _run(S.post_style_preview(None, env.user, S.StylePreview(
        document={"rules": [{"id": "trailing_period.hard.strip",
                             "kind": "trailing_period", "strictness": "hard",
                             "scope": "global", "enabled": True,
                             "params": {"ellipsis": "strip"}}],
                  "soft_instructions": []}), None))
    rows = {row["id"]: row for row in preview["rows"]}
    assert rows["trailing_period"]["before_text"].endswith(".")
    assert not rows["trailing_period"]["after_text"].endswith(".")
    # Защищённые данные не портятся предпросмотром.
    assert "https://example.org/other." in rows["trailing_protected"]["after_text"]
    assert "1.2.3" in rows["trailing_protected"]["after_text"]
    assert '{"note": "ok"}' in rows["machine_json"]["after_text"]


def test_expression_values_render_layer_text_and_reset(api_env, monkeypatch):
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    base = _run(S.get_expression(None, env.user, None))
    assert base["rendered_text"] == ""
    assert {c["id"] for c in base["controls"]} == {"wit", "sharpness",
                                                  "profanity", "verbosity"}

    saved = _run(S.post_expression(None, env.user, S.ExpressionWrite(
        values={"wit": "high", "profanity": "off"}), None))
    assert saved["ok"] is True
    view = _run(S.get_expression(None, env.user, None))
    assert "Остроумие" in view["rendered_text"]
    assert view["rendered_text"].startswith("<Expression_Settings>")
    assert "часто" not in view["rendered_text"].lower().replace(
        "чаще искать повод", ""), "никаких обещаний частоты"
    assert view["runtime_wired"] is False and view["runtime_note"]

    # Чат-скоуп пишет только chat-слой; сброс возвращает inherited.
    _run(S.post_expression(None, env.user, S.ExpressionWrite(
        values={"sharpness": "soft"}, scope="chat"), str(env.chat_id)))
    chat_view = _run(S.get_expression(None, env.user, str(env.chat_id)))
    assert chat_view["inheritance"] == "chat"
    global_doc = env.cache.get(S.EXPRESSION_DOC_KEY)
    assert global_doc["sharpness"] == "inherit", "чат переписал глобальное"
    reset = _run(S.post_expression_reset_chat(None, env.user, str(env.chat_id)))
    assert reset["ok"] is True
    chat_view = _run(S.get_expression(None, env.user, str(env.chat_id)))
    assert chat_view["inheritance"] == "global"


def test_humor_and_examples_report_real_state_honestly(api_env):
    """W4: приёмы и библиотека показывают фактическое состояние, а не каркас."""
    humor = _run(S.get_humor(None, api_env.user, None))
    assert len(humor["techniques"]) == 6
    assert humor["craft"]["gate"] is False        # ось ремесла OFF по умолчанию
    assert humor["craft"]["enabled"] is True      # документ владельца: не трогали
    assert humor["policy_version"].startswith("soul1-w4-craft")
    legacy = next(t for t in humor["techniques"] if t["id"] == "other")
    assert legacy["enabled"] is False and legacy["reason"]
    # Библиотеки нет по честной причине (БД/схема), а не «not_implemented_w4».
    assert humor["library"]["available"] is False
    assert humor["library"]["reason"] in ("db_unavailable", "schema_absent",
                                          "read_error")
    examples = _run(S.get_examples(None, api_env.user, None))
    assert examples["available"] is False
    assert examples["status"] == "unavailable"
    assert examples["items"] == [] and examples["count"] == 0
    assert examples["starter"]["expected"] == len(
        S.samples_lib.STARTER_SAMPLES)
    assert any(f["id"] == "owner_approved" for f in examples["entity_fields"])
    assert examples["policy"]["max_items"] >= 1
    # «Почему выбраны» и тест приёма доступны всегда (0 LLM).
    why = _run(S.post_examples_why(None, api_env.user,
                                   S.SampleWhyRequest(), None))
    assert why["ok"] is False and why["reason"] == "db_unavailable"
    probe = _run(S.post_humor_technique_test(
        None, api_env.user, S.HumorTechniqueTest(technique="deadpan"), None))
    assert probe["ok"] is True and probe["extra_llm_calls"] == 0
    assert probe["layer_revision"] and probe["layer_tokens"] > 0


def test_capabilities_and_inspector_shapes(api_env):
    caps = _run(S.get_capabilities(None, api_env.user, None))
    assert isinstance(caps["capabilities"], list)
    for state in caps["capabilities"]:
        assert "capability_id" in state and "status" in state
        assert "reason_code" in state
    assert "trace" in caps

    insp = _run(S.get_inspector(None, api_env.user, None))
    assert insp["preview"]["layers"], "предпросмотр собирается композером"
    assert insp["preview"]["manifest_id"]
    # Собранный шаблон НЕ выдаётся за доказательство реального вызова.
    assert insp["last_run_present"] in (True, False)
    if not insp["last_run_present"]:
        assert insp["sent"] == {} and insp["last_run_note"]
    assert insp["masked"] is True


def test_inspector_never_claims_preview_as_sent(api_env, monkeypatch):
    """SOUL-AMD.6.4: собранный шаблон не выдаётся за доказательство вызова."""
    from services import prompt_composer as composer
    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()
    # 1. Только предпросмотр в памяти → снимка хода нет, ветка «sent» пуста.
    insp = _run(S.get_inspector(None, env.user, None))
    assert insp["last_run_present"] is False
    assert insp["sent"] == {}
    assert "только предпросмотр" in insp["last_run_note"]
    assert composer.get_manifest(0, writer=S.PREVIEW_WRITER) is not None

    # 2. Манифест реального хода (writer Direct L2) → снимок показывается,
    #    с явной пометкой, что это payload хода, а не подтверждение доставки.
    manifest, run_id = _seed_real_turn(writer="l2_writer")
    insp = _run(S.get_inspector(None, env.user, None))
    assert insp["last_run_present"] is True
    assert insp["sent"]["writer"] == "l2_writer"
    assert insp["sent"]["manifest_id"] == manifest.manifest_id
    assert insp["sent"]["run_id"] == run_id
    assert "не подтверждение доставки" in insp["sent_note"]
    assert insp["sent"]["system_masked"]
    assert insp["sent"]["user_parts_masked"] is not None
    assert insp["sent_writers"] == list(S.REAL_TURN_WRITERS)
    composer.reset_state()


def test_inspector_finds_runtime_shaped_turn_snapshot(api_env, monkeypatch):
    """review-w6 F1: рантайм пишет run_id=correlation_id (uuid).

    Ключ манифеста в рантайме — ``(chat, uuid, writer)``, поэтому поиск по
    ключу без run_id его не находит. Снимок обязан находиться и НЕ подменяться
    предпросмотром UI, а чужой чат его видеть не должен.
    """
    from services import prompt_composer as composer

    env = api_env
    monkeypatch.setattr(pf, "_default_cache", lambda: env.cache)
    composer.reset_state()
    # Рантайм-форма: один ход = один uuid (direct_chat_service:4267).
    first, run_id = _seed_real_turn(writer="l2_writer", chat_id=0)
    assert composer.get_manifest(0, writer="l2_writer") is None, \
        "сид обязан быть рантайм-формы (без ключа run_id='-')"
    insp = _run(S.get_inspector(None, env.user, None))
    assert insp["last_run_present"] is True
    assert insp["sent"]["run_id"] == run_id
    assert insp["sent"]["manifest_id"] == first.manifest_id

    # Предпросмотр ПОСЛЕ хода (в т.ч. новый) не вытесняет снимок хода.
    insp = _run(S.get_inspector(None, env.user, None))
    assert insp["last_run_present"] is True
    assert insp["sent"]["writer"] == "l2_writer"

    # Следующий ход (новый uuid) — показывается самый свежий.
    second, run_id2 = _seed_real_turn(writer="tool_phase", chat_id=0)
    insp = _run(S.get_inspector(None, env.user, None))
    assert insp["sent"]["writer"] == "tool_phase"
    assert insp["sent"]["run_id"] == run_id2
    assert insp["sent"]["manifest_id"] == second.manifest_id

    # Чужой чат снимка не видит (изоляция по чату), предпросмотр не выдаётся.
    other = _run(S.get_inspector(None, env.user, str(env.chat_id)))
    assert other["last_run_present"] is False
    assert other["sent"] == {} and other["last_run_note"]
    composer.reset_state()


def test_style_editor_renders_from_draft_and_mutations_are_visible():
    """review-w6 F2: список/счётчик/привычки рендерятся ИЗ ЧЕРНОВИКА.

    Список правится в ``speechStyleDraft``, поэтому рендер серверного
    ``speechStyle.rules`` показывал владельцу не то, что сохранит Save.
    """
    style = INDEX[INDEX.index("speechSection === 'style'"):]
    style = style[:style.index("speechSection === 'expression'")]
    assert "speechStyleViewRules()" in style
    assert "speechStyleViewSoft()" in style
    assert "speechStyle.rules" not in style, "редактор снова рендерит сервер"
    assert "speechStyle.soft_instructions" not in style
    # Несохранённый черновик виден в разделе (и после возврата в него).
    assert "data-speech-style-dirty" in style
    assert "data-speech-style-dirty-note" in style
    # Мёртвое поле, которое нигде не рендерилось, удалено.
    assert "speechStyleViewRules = style.rules" not in APP_JS
    assert "speechStyleStaleAction" in APP_JS
    assert "this.speechDirty.style = (added + softAdded) > 0;" not in APP_JS


def test_factory_reset_plan_reads_real_response_shape():
    """review-w6 F3: реальный /reset отдаёт changed + current/factory_chars."""
    code = re.sub(r"//[^\n]*", "", APP_JS)
    assert "speechFactoryPlanText" in code
    assert "diff.before_chars" not in code
    assert "diff.after_chars" not in code
    assert "p.current_chars" in code and "p.factory_chars" in code
    assert "factory_plan.diff.before_chars" not in INDEX
    assert "diff.after_chars" not in INDEX
    assert "speechFactoryPlanText(speechBlockDetail.factory_plan)" in INDEX
    # Кнопка «Вернуть заводской» на «Характере» обязана знать свой блок.
    assert "speechFactoryPlan(blockIdFor(speechCoreEdition))" in INDEX
    assert "speechFactoryPlan()" not in INDEX


def _seed_real_turn(*, writer, chat_id=0):
    """Манифест РЕАЛЬНОГО хода в рантайм-форме: run_id=correlation_id (uuid).

    Рантайм (`direct_chat_service._compose_speech_system`) всегда пишет
    ``run_id=correlation_id``, поэтому ключ манифеста — ``(chat, uuid, writer)``:
    сид без run_id не воспроизводит рантайм (review-w6 F1).
    """
    import uuid as _uuid
    from services import prompt_composer as composer
    base_block = pr.by_pg_key(S.BASE_BLOCK_PG_KEY)
    run_id = _uuid.uuid4().hex
    plan = composer.PromptPlan(
        profile=composer.PROFILE_SPEECH_PLAIN, writer=str(writer),
        chat_id=int(chat_id), run_id=run_id,
        base_prompt=pr.factory_text(base_block.block_id),
        gates=composer.gates_from_config())
    return composer.compose_prompt(plan), run_id


def test_payload_masking_hides_secrets_and_ids():
    """§6.4: секреты/приватные ID маскируются перед показом в Inspector."""
    masked = S._mask_text(
        "key sk-live-ABC123456789 token=secret-value user 5885953495 "
        "chat -1001234567890 link tg://user?id=4242 Bearer abcdefghijklmn")
    assert "sk-live-ABC123456789" not in masked
    assert "secret-value" not in masked
    assert "5885953495" not in masked
    assert "-1001234567890" not in masked
    assert "abcdefghijklmn" not in masked
    assert "[id]" in masked and "tg://" not in masked
    # обычный текст не портится
    plain = "Ну да, логично. Смотри https://example.org/a и версию 1.2.3"
    assert S._mask_text(plain) == plain


def test_learning_binds_existing_lessons_and_reports_humor_state(api_env):
    """W4: раздел «Обучение» показывает реальный контур реакций на шутки."""
    learn = _run(S.get_learning(None, api_env.user, None))
    feedback = learn["humor_feedback"]
    assert feedback["enabled"] is False          # ось по умолчанию OFF
    assert feedback["available"] is False
    assert feedback["reason"] == "humor_feedback_disabled"
    assert feedback["signals"] == {} and feedback["sends"] == 0
    assert len(feedback["scenarios"]) == 7        # обязательные сценарии SOUL-08
    assert set(feedback["controls"]) == {"pause", "approve", "reject", "reset"}
    assert learn["lessons"]["state"] in ("implemented", "not_run", "no_db",
                                         "disabled", "error")
    assert "не провал" in feedback["note"]


def test_access_control_is_delegated_to_existing_permissions(monkeypatch):
    denied = SimpleNamespace(is_global_admin=False,
                             effective_permissions=None)
    user = SimpleNamespace(id=1)

    async def access(request, _user, x_chat_id):
        return None, None, denied

    monkeypatch.setattr(S, "_access", access)
    with pytest.raises(Exception) as exc:
        _run(S.get_core(None, user, None))
    assert getattr(exc.value, "status_code", None) == 403
    with pytest.raises(Exception) as exc2:
        _run(S.get_inspector(None, user, None))
    assert getattr(exc2.value, "status_code", None) == 403


def _run(coro):
    import asyncio
    return asyncio.run(coro)
