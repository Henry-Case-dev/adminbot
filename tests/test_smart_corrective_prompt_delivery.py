"""SMART-CORRECTIVE-01 §8.2/§8.3/§8.4/§8.5 — реальная доставка промпта чекапа.

Доказывается наблюдаемый контракт среза S6-PROMPT:

  * база чекапа на пользовательском маршруте резолвится существующим реестром
    по порядку chat override → global → factory, поэтому сохранённая
    владельцем per-chat редакция реально доходит до своего чата;
  * сохранённое значение НЕ перезаписывается и не «сидируется» сервисом;
  * внутренний tool-loop (без ``chat_id``) сохраняет прежний global-резолв;
  * телеметрия отдаёт ``prompt_source``/``prompt_hash``/``prompt_version_used``/
    ``prompt_chars`` + слой/базу/удержание — без текста промпта;
  * активный контур (жанр + addendum + fallback notice) не содержит
    устаревшего Betterstack, исторические ``PREV_*`` байты не переписаны;
  * addendum согласован с фактическим поведением инструментов и не дублирует
    жанр, не вводит словарей/проверок мата;
  * смешанное смысловое состояние (чистые логи + активный инцидент) задано
    формулировками промпта, а не новым механизмом;
  * «инструкции не обрезаются»: финальный system содержит жанр, Core +
    Expression и addendum целиком;
  * слой речи остаётся один: Core → Expression → Style Policy, без второй
    Personality Core/Expression и скрытого подавления мата;
  * заводская правка не запускает активацию поверх ручной редакции
    (метка ревизии не менялась), печать содержимого и fingerprint согласованы;
  * сохранённая per-chat редакция владельца не заменяется новой заводской
    поставкой даже без явного `baseline_assign` (guard §8.1/AC-19), при этом
    заводская ревизия остаётся в истории, другой чат получает поставку как
    обычно, а явный owner baseline сохраняет приоритет.

TEST-LIFECYCLE: CONTRACT owner=smart-corrective-01 §8.2–§8.5 (S6-PROMPT)
"""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from services import checkup_service as svc_mod
from services import chat_params
from services import hot_config as hot
from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services.checkup_prompts import (
    CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM,
    CHECKUP_FALLBACK_NOTICE,
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT,
    PREV_CHECKUP_SYSTEM_PROMPT,
)
from tests.test_evol016_prompt_activation import FactoryEdition, FakeCache

CHAT_ID = 777
KEY = "prompts.checkup_system_prompt"
OWNER_TEXT = (
    "СИСТЕМНАЯ РОЛЬ И ЗАДАЧА:\n"
    "Владельческая редакция чекапа для этого чата.\n\n"
    "ОБЪЁМ:\n"
    "Не больше {max_symbols} символов.")
GLOBAL_TEXT = (
    "СИСТЕМНАЯ РОЛЬ И ЗАДАЧА:\n"
    "Глобальная редакция чекапа.\n\n"
    "ОБЪЁМ:\n"
    "Не больше {max_symbols} символов.")


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_config_cache(self):
        return self


class FakeChatParams:
    """Read-only двойник кэша чат-параметров: write-путей у него нет."""

    def __init__(self, overrides=None):
        self.roots = {CHAT_ID: {"overrides": dict(overrides or {})}}

    async def get_chat_params(self, chat_id):
        return dict(self.roots.get(int(chat_id), {}) or {})


class FakeLLM:
    def __init__(self, answer="готовый отчёт"):
        self.answer = answer
        self.messages = []

    async def generate(self, messages, **kwargs):
        self.messages.append([dict(m) for m in messages])
        return self.answer


@pytest.fixture()
def registry_active():
    """Production-состояние после EVOL-016 cutover: журнал — источник истины."""
    pr.set_release_policy_active(True)
    yield
    pr.set_release_policy_active(False)


@pytest.fixture()
def service_env(monkeypatch):
    """Изолированный маршрут чекапа: owner-block/outbound-style — двойники."""
    async def _owner_block(chat_id):
        return "OWNER-CORE-EXPRESSION-BLOCK"

    calls = {"style": 0}

    async def _passthrough(text, chat_id):
        calls["style"] += 1
        return text

    monkeypatch.setattr(svc_mod, "speech_owner_block", _owner_block)
    monkeypatch.setattr(svc_mod.CheckupService, "_apply_outbound_style",
                        staticmethod(_passthrough))
    yield calls
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def _checkup(*, chat_id=CHAT_ID, used_fallback=False, tool_runtime=None,
             telemetry=None):
    llm = FakeLLM()
    service = svc_mod.CheckupService(llm, db=None, memory=None,
                                     metrics_enabled=False)
    import asyncio
    asyncio.run(service.checkup(
        "логи", used_fallback, chat_id=chat_id, telemetry=telemetry,
        tool_runtime=tool_runtime))
    return llm.messages[0][0]["content"], telemetry or {}


# ═══ 1. Матрица резолва: chat → global → factory ════════════════════════════

def test_chat_override_applies_on_checkup_route(service_env, registry_active):
    hot.set_config_cache(FakeHot({KEY: GLOBAL_TEXT}))
    cache = FakeChatParams({KEY: OWNER_TEXT})
    chat_params.set_chat_params_cache(cache)
    telemetry: dict = {}

    system, _ = _checkup(telemetry=telemetry)

    assert system.startswith(OWNER_TEXT.replace("{max_symbols}", "3000")[:60])
    assert "Владельческая редакция чекапа для этого чата." in system
    assert "Глобальная редакция чекапа." not in system
    assert telemetry["prompt_source"] == "chat"
    assert telemetry["prompt_layer"] == "chat"
    assert telemetry["prompt_chars"] == len(system)
    assert telemetry["prompt_version_used"].startswith("chat:")
    assert telemetry["prompt_base_chars"] == len(OWNER_TEXT)
    assert telemetry["prompt_base_hash"] == _sha16(OWNER_TEXT)
    assert telemetry["prompt_withheld"] is False


def test_global_layer_applies_without_chat_override(service_env,
                                                    registry_active):
    hot.set_config_cache(FakeHot({KEY: GLOBAL_TEXT}))
    chat_params.set_chat_params_cache(FakeChatParams())
    telemetry: dict = {}

    system, _ = _checkup(telemetry=telemetry)

    assert "Глобальная редакция чекапа." in system
    assert "Владельческая редакция" not in system
    assert telemetry["prompt_source"] == "global"
    assert telemetry["prompt_layer"] == "global"
    assert telemetry["prompt_base_hash"] == _sha16(GLOBAL_TEXT)


def test_factory_fallback_without_persisted_value(service_env,
                                                  registry_active):
    hot.set_config_cache(FakeHot())
    chat_params.set_chat_params_cache(FakeChatParams())
    telemetry: dict = {}

    system, _ = _checkup(telemetry=telemetry)

    assert telemetry["prompt_source"] == "default"
    assert telemetry["prompt_layer"] == "default"
    assert telemetry["prompt_base_chars"] == len(CHECKUP_SYSTEM_PROMPT)
    assert telemetry["prompt_base_hash"] == _sha16(CHECKUP_SYSTEM_PROMPT)
    assert CHECKUP_SYSTEM_PROMPT.split("\n\n")[0] in system


def test_chat_override_is_scoped_to_its_own_chat(service_env, registry_active):
    """Сохранённая редакция одного чата не подменяет другой чат."""
    hot.set_config_cache(FakeHot({KEY: GLOBAL_TEXT}))
    chat_params.set_chat_params_cache(FakeChatParams({KEY: OWNER_TEXT}))
    telemetry: dict = {}

    system, _ = _checkup(chat_id=999, telemetry=telemetry)

    assert "Глобальная редакция чекапа." in system
    assert "Владельческая редакция чекапа для этого чата." not in system
    assert telemetry["prompt_source"] == "global"


def test_internal_route_keeps_global_only_precedence(service_env,
                                                     registry_active):
    """Без chat_id per-chat слой не читается — прежнее поведение сохранено."""
    hot.set_config_cache(FakeHot({KEY: GLOBAL_TEXT}))
    chat_params.set_chat_params_cache(FakeChatParams({KEY: OWNER_TEXT}))
    telemetry: dict = {}

    system, _ = _checkup(chat_id=None, telemetry=telemetry)

    assert "Глобальная редакция чекапа." in system
    assert "Владельческая редакция чекапа для этого чата." not in system
    assert telemetry["prompt_source"] == "global"


# ═══ 2. Сохранённое значение владельца не перезаписывается ══════════════════

def test_owner_saved_value_is_not_rewritten(service_env, registry_active):
    hot.set_config_cache(FakeHot({KEY: GLOBAL_TEXT}))
    cache = FakeChatParams({KEY: OWNER_TEXT})
    chat_params.set_chat_params_cache(cache)

    _checkup()

    assert cache.roots[CHAT_ID]["overrides"][KEY] == OWNER_TEXT
    source = open(svc_mod.__file__, encoding="utf-8").read()
    for writer in ("write_prompt_values", "write_speech_value",
                   "write_versioned_value", "set_chat_params",
                   "apply_factory_reset"):
        assert writer not in source, writer


def test_registry_change_is_observable_and_store_untouched(service_env,
                                                           registry_active):
    """CHECK-04: изменение текста реестром видно в телеметрии, PG цел."""
    hot.set_config_cache(FakeHot({KEY: GLOBAL_TEXT}))
    cache = FakeChatParams({KEY: OWNER_TEXT})
    chat_params.set_chat_params_cache(cache)
    effective = OWNER_TEXT + "\n\n[registry-clean]"

    async def _resolved(pg_key, code_default, *, chat_id):
        from services.prompt_registry import SpeechResolution
        return SpeechResolution(text=effective, source="chat")

    import services.prompt_registry as registry
    original = registry.resolve_chat_speech_ex
    registry.resolve_chat_speech_ex = _resolved
    try:
        telemetry: dict = {}
        system, _ = _checkup(telemetry=telemetry)
    finally:
        registry.resolve_chat_speech_ex = original

    assert "[registry-clean]" in system
    assert telemetry["prompt_base_hash"] == _sha16(effective)
    assert cache.roots[CHAT_ID]["overrides"][KEY] == OWNER_TEXT


def test_telemetry_has_no_prompt_text(service_env, registry_active):
    hot.set_config_cache(FakeHot({KEY: OWNER_TEXT}))
    chat_params.set_chat_params_cache(FakeChatParams())
    telemetry: dict = {}

    _checkup(telemetry=telemetry)

    required = {"prompt_source", "prompt_hash", "prompt_version_used",
                "prompt_chars", "prompt_layer", "prompt_base_hash",
                "prompt_base_chars", "prompt_withheld",
                "prompt_provenance_reason"}
    assert required <= set(telemetry)
    for value in telemetry.values():
        assert not (isinstance(value, str) and "Владельческая редакция" in value)
        assert not (isinstance(value, str) and len(value) > 200)


# ═══ 3. Активный контур: stale Betterstack только в истории ═════════════════

def test_active_contour_has_no_stale_betterstack():
    for name, text in (
            ("genre", CHECKUP_SYSTEM_PROMPT),
            ("addendum", CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM),
            ("fallback", CHECKUP_FALLBACK_NOTICE)):
        lowered = text.casefold()
        assert "betterstack" not in lowered, name
        assert "401" not in text, name


def test_historical_editions_still_contain_old_bytes():
    assert "Betterstack" in PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT
    assert "401" in PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT
    assert "Betterstack" in PREV_CHECKUP_SYSTEM_PROMPT
    assert PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT != CHECKUP_SYSTEM_PROMPT


# ═══ 4. Addendum согласован с поведением инструментов ═══════════════════════

def test_addendum_states_new_tool_behaviour():
    text = CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
    for anchor in (
            "Недостаточность первого результата не является основанием "
            "прекращать исследование",
            "Отсутствие необходимости в исследовании — нормальное завершение",
            "Отказ одного источника или инструмента не равен отказу всех "
            "доступных маршрутов",
            "Существенную непроверенность нельзя скрывать",
            "исчерпания подходящих маршрутов допустим честный частичный "
            "отчёт",
            "cursor для продолжения выдачи",
            "time_window для истории событий и проб"):
        assert anchor in text, anchor


def test_addendum_does_not_duplicate_genre_or_add_mat_machinery():
    text = CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
    # Жанровый промпт не дублируется в служебном addendum.
    assert "СИСТЕМНАЯ РОЛЬ И ЗАДАЧА" not in text
    assert "СУТЬ АНАЛИЗА" not in text
    assert "ЖАНР ОТЧЁТА" not in text
    # Никаких словарей ругательств / проверок количества мата / обязательного
    # перефразирования.
    lowered = text.casefold()
    for forbidden in ("словарь ругательств", "количество мата",
                      "проверка количества", "обязательное перефразирование",
                      "токсичных фраз"):
        assert forbidden not in lowered, forbidden


# ═══ 5. Смешанное смысловое состояние ═══════════════════════════════════════

def test_mixed_state_is_prompt_wording_not_a_new_mechanism():
    genre = CHECKUP_SYSTEM_PROMPT
    assert "могут быть верны одновременно" in genre
    assert "не отменяет уже обнаруженный существенный инженерный косяк" \
        in genre
    assert "не доказывает, что компонент падает прямо сейчас" in genre
    assert "не смягчается тем, что остальная система работает" in genre
    addendum = CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
    assert "Активный ERROR-инцидент и чистое свежее окно журналов" in addendum
    # Никакого отдельного вычислителя состояния в сервисе нет.
    source = open(svc_mod.__file__, encoding="utf-8").read()
    for forbidden in ("mixed_state", "incident_state", "fresh_logs_state"):
        assert forbidden not in source


# ═══ 6. Инструкции не обрезаются; один слой речи ════════════════════════════

def test_full_instructions_reach_the_model(service_env, registry_active):
    # Владельческая редакция масштаба production C2 (12 469 chars): никакой
    # искусственной квоты/обрезки инструкций быть не должно.
    long_owner = OWNER_TEXT + "\n\n" + ("Длинная авторская редакция. " * 500)
    assert len(long_owner) > 12000
    hot.set_config_cache(FakeHot({KEY: long_owner}))
    chat_params.set_chat_params_cache(FakeChatParams())
    tool_runtime = {"schemas": ("inspect_runtime",)}

    system, _ = _checkup(used_fallback=True, tool_runtime=tool_runtime)

    base = long_owner.replace("{max_symbols}", "3000")
    owner = "OWNER-CORE-EXPRESSION-BLOCK"
    expected = (base + "\n\n" + owner + "\n\n"
                + CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM + "\n\n"
                + CHECKUP_FALLBACK_NOTICE)
    assert system == expected
    assert "{max_symbols}" not in system
    # Ровно один раз каждый блок, порядок жанр → Core/Expression → addendum →
    # notice; никакой символьной квоты/обрезки не применялось.
    assert system.count(base) == 1
    assert system.count(owner) == 1
    assert system.endswith(CHECKUP_FALLBACK_NOTICE)
    assert system.index(base) < system.index(owner) \
        < system.index(CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM)


def test_single_speech_layer_no_second_engine(service_env, registry_active):
    hot.set_config_cache(FakeHot())
    chat_params.set_chat_params_cache(FakeChatParams())
    telemetry: dict = {}

    system, _ = _checkup(telemetry=telemetry)

    # Жанр остаётся владельцем формы/выразительности разбора, а не нейтральным
    # голосом технического ассистента.
    assert "язвительный участник чата" in system
    assert "Общий характер берётся из Personality Core" in system
    assert "частота мата и резкость — из Expression" in system
    assert "типографика — из Style Policy" in system
    # Единственный outbound-проход стиля вызван ровно один раз.
    assert service_env["style"] == 1
    # Второго речевого движка/регулятора мата в сервисе нет.
    source = open(svc_mod.__file__, encoding="utf-8").read()
    for forbidden in ("Personality Core:", "PROFANITY_INSTRUCTIONS",
                      "profanity_filter", "expression_engine"):
        assert forbidden not in source, forbidden


# ═══ 7. Реестр: правка заводской редакции не трогает ручную ═════════════════

def test_factory_content_fix_does_not_activate_over_owner_edition():
    block_id = "checkup.base.system"
    label, sealed_sha = pr.FACTORY_REVISION_SEALS[block_id]
    assert pr.seal_integrity() == {}
    assert label == "checkup-p0-24-10"
    assert sealed_sha == pr.sha12(CHECKUP_SYSTEM_PROMPT)
    assert pr.sealed_factory_revision(block_id) == pr.FACTORY_PREFIX + \
        pr.sha12(label)
    # Метка не менялась ⇒ деплой видит ту же применённую заводскую ревизию и
    # не активирует заводской текст поверх сохранённой ручной редакции чата.
    plan = pr.activation_plan(
        code_label=label, sealed_sha=sealed_sha,
        text_sha12=pr.sha12(CHECKUP_SYSTEM_PROMPT),
        applied_factory_revision=pr.sealed_factory_revision(block_id),
        has_import=True)
    assert plan.action == pr.PLAN_NOOP


# ═══ 8. Сохранённая редакция чата не заменяется заводским cutover ═══════════
#
# Owner corrective §8.1 / AC-15 / AC-19 (новее EVOL-012/016): сохранённая
# владельцем per-chat редакция должна оставаться действующей и не заменяться
# заводским текстом при исправлении или деплое. Прежний признак «pinned»
# требовал явного ``baseline_assign``; ручная редакция без назначения
# перетиралась, а chat-override снимался (production 2.58.201, CHAT_C2).
# Guard ниже — то, что не даёт этому повториться на следующем релизе.

GUARD_BLOCK = "summary.base.narrator"
GUARD_KEY = "prompts.summary_narrator_system_prompt"
GUARD_FACTORY_A = "ЗАВОДСКАЯ A: рассказчик саммари (guard-эталон).\n"
GUARD_FACTORY_B = ("ЗАВОДСКАЯ B: новая заводская публикация — не должна "
                   "заменить сохранённую редакцию чата.\n")
GUARD_CHAT = -1009101
GUARD_OTHER_CHAT = -1009102
GUARD_MANUAL = ("СОХРАНЁННАЯ РЕДАКЦИЯ ВЛАДЕЛЬЦА: ручная правка этого чата, "
                "которая должна остаться действующей.\n")


@pytest.fixture()
def guard_edition(monkeypatch):
    """Заводская редакция A тестового блока + сброс глобального состояния."""
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(GUARD_BLOCK, "narrator-a", GUARD_FACTORY_A)
    yield patch
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


@pytest.fixture()
def guard_store():
    return prp.MemoryPromptJournal()


def _guard_run(cache, store, release_id="evol-016-cutover"):
    return asyncio.run(prp.apply_release(cache, release_id=release_id,
                                         store=store, blocks=[GUARD_BLOCK]))


def _guard_row(result, chat_id=GUARD_CHAT):
    for row in result["results"]:
        if (row.block_id, row.scope, row.chat_id) == (GUARD_BLOCK, "chat",
                                                      chat_id):
            return row
    raise AssertionError("результат релиза для чата не найден")


def _manual_chat_revision(store, chat_id=GUARD_CHAT):
    rows = [r for r in store.revisions.values()
            if r.block_id == GUARD_BLOCK and r.origin == "manual"
            and r.scope == "chat" and (r.chat_id or None) == chat_id
            and not r.retired]
    assert len(rows) == 1, rows
    return rows[0]


def test_manual_chat_edition_survives_factory_cutover(guard_edition,
                                                      guard_store):
    """Ручная редакция чата без baseline_assign блокирует заводской cutover."""
    cache, store = FakeCache({GUARD_KEY: GUARD_FACTORY_A}), guard_store
    _guard_run(cache, store)
    asyncio.run(prp.write_versioned_value(
        GUARD_BLOCK, GUARD_MANUAL, scope="chat", chat_id=GUARD_CHAT,
        cache=cache, store=store, actor="owner"))
    manual = _manual_chat_revision(store)
    bytes_before = store.revisions[manual.revision_id].body
    sha_before = manual.content_sha12
    notified_before = len(store.notified_chats)
    revisions_before = len(store.revisions)

    guard_edition.set_edition(GUARD_BLOCK, "narrator-guard-b", GUARD_FACTORY_B)
    release = _guard_run(cache, store, release_id="deploy-guard-b")

    row = _guard_row(release)
    assert (row.outcome, row.detail_code) == ("skipped_same",
                                              "factory_superseded_manual")
    # Действующие байты чата — сохранённая редакция; override не снят.
    assert store.chat_overrides[GUARD_CHAT][GUARD_KEY] == GUARD_MANUAL
    # Байты ручной ревизии не изменились и клонов/снимков не появилось.
    assert store.revisions[manual.revision_id].body == bytes_before
    assert store.revisions[manual.revision_id].content_sha12 == sha_before
    assert store.revisions[manual.revision_id].origin == "manual"
    factory_rows = [r for r in store.revisions.values()
                    if (r.block_id, r.scope, r.chat_id, r.origin) ==
                    (GUARD_BLOCK, "chat", GUARD_CHAT, "factory")
                    and r.content_sha12 == pr.sha12(GUARD_FACTORY_B)]
    assert len(factory_rows) == 1        # поставка не потеряна — она в истории
    # Ровно две новые ревизии: заводская B для global и для этого чата.
    assert len(store.revisions) == revisions_before + 2
    # Значение чата не менялось — уведомления чату не было.
    assert len(store.notified_chats) == notified_before
    # Диагностика записана в журнал активаций.
    event = store.activations[-1]
    assert (event.kind, event.outcome, event.detail_code) == (
        "deploy_activate", "skipped_same", "factory_superseded_manual")
    # Незакреплённый global получил заводской текст как обычно.
    assert cache.values[GUARD_KEY] == GUARD_FACTORY_B

    # Рестарт/повторный релиз той же метки — истинный no-op.
    before = (len(store.activations), len(store.revisions))
    cache.set_calls.clear()
    _guard_run(cache, store, release_id="restart-guard")
    assert (len(store.activations), len(store.revisions)) == before
    assert cache.set_calls == []
    assert store.chat_overrides[GUARD_CHAT][GUARD_KEY] == GUARD_MANUAL
    assert [a for a in store.activations
            if a.detail_code == "activation_drift"] == []


def test_guard_is_isolated_to_the_chat_with_manual_edition(guard_edition,
                                                           guard_store):
    """Другой чат без сохранённой редакции получает заводскую как обычно."""
    cache, store = FakeCache({GUARD_KEY: GUARD_FACTORY_A}), guard_store
    _guard_run(cache, store)
    asyncio.run(prp.write_versioned_value(
        GUARD_BLOCK, GUARD_MANUAL, scope="chat", chat_id=GUARD_CHAT,
        cache=cache, store=store, actor="owner"))
    # У второго чата override есть, а сохранённой ручной ревизии нет.
    store.chat_overrides[GUARD_OTHER_CHAT] = {
        GUARD_KEY: "СТАРЫЙ OVERRIDE БЕЗ РУЧНОЙ РЕВИЗИИ\n"}

    guard_edition.set_edition(GUARD_BLOCK, "narrator-guard-b", GUARD_FACTORY_B)
    release = _guard_run(cache, store, release_id="deploy-guard-b")

    own = _guard_row(release)
    assert (own.outcome, own.detail_code) == ("skipped_same",
                                              "factory_superseded_manual")
    assert store.chat_overrides[GUARD_CHAT][GUARD_KEY] == GUARD_MANUAL
    other = _guard_row(release, GUARD_OTHER_CHAT)
    assert (other.outcome, other.detail_code) == ("applied", "factory_activate")
    assert GUARD_KEY not in store.chat_overrides.get(GUARD_OTHER_CHAT, {})
    # Байты снятого override второго чата сохранены в истории.
    assert pr.sha12("СТАРЫЙ OVERRIDE БЕЗ РУЧНОЙ РЕВИЗИИ\n") in {
        r.content_sha12 for r in store.revisions.values()
        if r.scope == "chat"}


def test_explicit_baseline_assign_still_wins_over_manual_guard(guard_edition,
                                                               guard_store):
    """Явный owner baseline сохраняет приоритет и прежнюю pin-политику."""
    cache, store = FakeCache({GUARD_KEY: GUARD_FACTORY_A}), guard_store
    _guard_run(cache, store)
    asyncio.run(prp.write_versioned_value(
        GUARD_BLOCK, GUARD_MANUAL, scope="chat", chat_id=GUARD_CHAT,
        cache=cache, store=store, actor="owner"))
    manual = _manual_chat_revision(store)
    asyncio.run(prp.assign_baseline(GUARD_BLOCK, manual.revision_id,
                                    scope="chat", chat_id=GUARD_CHAT,
                                    actor="owner", cache=cache, store=store))

    guard_edition.set_edition(GUARD_BLOCK, "narrator-guard-b", GUARD_FACTORY_B)
    release = _guard_run(cache, store, release_id="deploy-guard-b")

    row = _guard_row(release)
    assert row.action == pr.PLAN_ACTIVATE_PINNED
    assert (row.outcome, row.detail_code) == ("skipped_same",
                                              "factory_superseded_pinned")
    assert store.chat_overrides[GUARD_CHAT][GUARD_KEY] == GUARD_MANUAL
    state = asyncio.run(store.read_applied(GUARD_BLOCK, "chat", GUARD_CHAT))
    assert state.revision_id == manual.revision_id
    assert state.factory_revision_applied == pr.FACTORY_PREFIX + \
        pr.sha12("narrator-guard-b")


def test_preserved_manual_edition_without_override_is_not_replaced(
        guard_edition, guard_store):
    """Состояние после 2.58.201: override снят, сохранённая редакция осталась.

    Релиз не выдумывает для этого чата заводской override и не трогает
    сохранённую редакцию; возврат самой редакции на маршрут — отдельное
    data-only действие, которым этот guard не подменяется.
    """
    cache, store = FakeCache({GUARD_KEY: GUARD_FACTORY_A}), guard_store
    _guard_run(cache, store)
    asyncio.run(prp.write_versioned_value(
        GUARD_BLOCK, GUARD_MANUAL, scope="chat", chat_id=GUARD_CHAT,
        cache=cache, store=store, actor="owner"))
    store.chat_overrides[GUARD_CHAT].pop(GUARD_KEY, None)   # как после 2.58.201

    guard_edition.set_edition(GUARD_BLOCK, "narrator-guard-b", GUARD_FACTORY_B)
    release = _guard_run(cache, store, release_id="deploy-guard-b")

    # Без override чат не входит в релиз: заводской override не записан.
    assert [r for r in release["results"] if r.scope == "chat"] == []
    assert GUARD_KEY not in store.chat_overrides.get(GUARD_CHAT, {})
    manual = _manual_chat_revision(store)
    assert store.revisions[manual.revision_id].body == GUARD_MANUAL
    assert store.revisions[manual.revision_id].retired is False
