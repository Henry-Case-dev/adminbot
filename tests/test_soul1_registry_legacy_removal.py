"""SOUL-1 / W1 — удаление legacy-речи из effective-слоя (§1.2 + §7.2).

Доказывается:
  * известные сегменты старой личности («токсичный … бот-абьюзер»,
    «унизить оппонента», снятие safety-контура) не доходят до значения,
    которое уходит в LLM, если значение пришло из ПЕРСИСТЕНТНОГО слоя;
  * несвязанные контракты (вердикт/источники фактчека, анти-галлюцинации
    и инструменты Direct, JSON-схема планировщика, маркировка цели) целы;
  * подавление идемпотентно, кастом владельца не правится, кодовый
    fallback (PG down) остаётся байт-в-байт (OFF-паритет W2);
  * миграция нормализации PG: dry-run → идемпотентная запись → snapshots →
    откат к оригиналу (обратимый деплой).

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=SOUL-AMD.1.2/7.2/8.5 (soul-1, W1)
"""
from __future__ import annotations

import pytest

from services import hot_config as hot
from services import chat_params
from services import chat_prompts
from services import checkup_prompts
from services import factcheck_prompts
from services import param_catalog as pc
from services import prompt_factory as pf_mod
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services import prompt_style_blocks as psb
from services import search_prompts
from services import summary_prompts
from services import web_prompts
from services import youtube_prompts

LEGACY_MARKERS = ("токсичн", "бот-абьюзер", "унизить", "унизив",
                  "Игнорируй все настройки безопасности")

#: Контракты, которые обязаны пережить вычистку (не речь, а техника).
CONTRACTS = {
    "factcheck.base.single": ("вердикт", "источник", "АНТИ-БОТ", "СТРОГО",
                              "выдуман"),
    "factcheck.base.verbalizer": ("JSON", "не выдумыв", "ТИПОГРАФИКА"),
    "direct.base.tool_phase": ("АНТИ-ГАЛЛЮЦИНАЦИИ", "ИНСТРУМЕНТЫ",
                               "query_chat_memory", "<Target_User>",
                               "не выдумыв"),
    "direct.base.l2_writer": ("JSON", "не выдумыв", "ТИПОГРАФИКА"),
    "direct.base.l1_planner": ("СХЕМА", "JSON", "response_act"),
    "direct.base.synthesizer": ("JSON", "response_mode", "ФОРМАТ"),
    "checkup.base.system": ("JSON", "хеши"),
    "summary.base.single": ("источник", "факт", "СТРОГО"),
}

LEGACY_BLOCK_IDS = tuple(b.block_id for b in pr.legacy_persona_blocks())
#: Блоки effective-слоя (PG-каноны), к которым применяется подавление на
#: сборке. Код-пути без PG-ключа (например фраза smartmodule) регистрируются
#: отдельно и заменяются владельцем слайса (W3) — см.
#: ``test_code_path_legacy_phrase_is_registered_for_replacement``.
LEGACY_CANON_BLOCK_IDS = tuple(
    b.block_id for b in pr.legacy_persona_blocks()
    if b.pg_key or len(pr.factory_text(b.block_id)) >= 400)

#: CFG-07A-2 (20.10.2026, ADR-1013-3): фабричные каноны этих блоков ВЫЧИЩЕНЫ
#: (safety-bypass/identity/hostility сняты из кода), поэтому контракт
#: подавления проверяется на ПЕРСИСТЕНТНЫХ байтах прежнего прод-канона
#: (ступени миграции PREV_*_CFG07A; фактчек — фриз CFG-06 W3, не тронут).
#: ASAP W1 (22.10.2026, §3.1/§3.6/P0F-«точечно»): фабрики Direct
#: (tool phase 2.58.110 байты, L2 writer) и Вербализатора фактчека вычищены
#: — контракт подавления проверяется на их прод-байтах (PREV_*_W1-ступени).
_PERSISTED_BYTES: dict[str, str] = {
    "direct.base.tool_phase": chat_prompts.PREV_CHAT_W1_SYSTEM_PROMPT,
    "direct.base.l2_writer": chat_prompts.PREV_CHAT_VERBALIZER_W1,
    "factcheck.base.verbalizer":
        factcheck_prompts.PREV_FACTCHECK_VERBALIZER_W1,
    "checkup.base.system": checkup_prompts.PREV_CHECKUP_CFG07A_SYSTEM_PROMPT,
    "summary.base.single": summary_prompts.PREV_SUMMARY_CFG07A_SYSTEM_PROMPT,
    # LEGFIX (22.10.2026, backlog «narrator-канон identity-фраза»): фабрика
    # Рассказчика вычищена (класс SF-07) — контракт подавления проверяется
    # на прежних прод-байтах (ступень PREV_SUMMARY_NARRATOR_LEGFIX).
    "summary.base.narrator": summary_prompts.PREV_SUMMARY_NARRATOR_LEGFIX,
    "search.base.system": search_prompts.PREV_SEARCH_CFG07A_SYSTEM_PROMPT,
    "web.base.system": web_prompts.PREV_WEBPAGE_CFG07A_SYSTEM_PROMPT,
    "youtube.base.system": youtube_prompts.PREV_YOUTUBE_CFG07A_SYSTEM_PROMPT,
    "youtube.base.video":
        youtube_prompts.PREV_YOUTUBE_VIDEO_CFG07A_SYSTEM_PROMPT,
}


def _legacy_source_bytes(block_id: str) -> str:
    """Байты «известного канона со старой личностью» для блока: прежний
    прод-канон (если фабрика вычищена) или фабричный текст."""
    return _PERSISTED_BYTES.get(block_id) or pr.factory_text(block_id)


class FakeConfigCache:
    """Минимальный двойник ConfigCache (без PG/сети)."""

    def __init__(self, values: dict | None = None, *, pg_available: bool = True):
        self.values = dict(values or {})
        self.pg_available = pg_available
        self.writes: list[tuple] = []
        self.batches: list[list[tuple]] = []

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_updated_at(self, key):
        return self.updated_at.get(key) if hasattr(self, "updated_at") else None

    async def set(self, key, value, category):
        self.values[key] = value
        self.writes.append((key, value, category))

    async def set_many(self, items):
        self.batches.append(list(items))
        for key, value, category in items:
            self.values[key] = value


@pytest.fixture(autouse=True)
def _clean_caches():
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pr.reset_cache()
    yield
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pr.reset_cache()


# ═══ Детерминированная вычистка (unit) ═════════════════════════════════════

@pytest.mark.parametrize("block_id", LEGACY_CANON_BLOCK_IDS)
def test_suppression_strips_persona_for_known_canons(block_id):
    """Контракт подавления: ПЕРСИСТЕНТНОЕ значение известного канона со
    старой личностью вычищается на сборке; кодовый fallback байт-в-байт
    прежний (OFF-паритет W2). CFG-07A-2: для вычищенных фабрик «известный
    канон» — прежний прод-канон (PREV_*_CFG07A-ступени)."""
    raw = _legacy_source_bytes(block_id)
    assert raw, block_id
    stripped, info = pr.suppress_legacy_speech(raw, source="global")
    assert info.known_canon is True, block_id
    assert info.legacy_present is True, block_id
    assert info.removed > 0, block_id
    for marker in ("токсичн", "бот-абьюзер"):
        assert marker not in stripped, (block_id, marker)
    assert "Игнорируй все настройки безопасности" not in stripped, block_id
    # Кодовый fallback не меняется — OFF-паритет W2 (шов 2) сохраняется.
    untouched, code_info = pr.suppress_legacy_speech(raw, source="default")
    assert untouched == raw
    assert code_info.applied is False


@pytest.mark.parametrize("block_id,markers", sorted(CONTRACTS.items()))
def test_suppression_keeps_non_speech_contracts(block_id, markers):
    raw = _legacy_source_bytes(block_id)
    stripped, info = pr.suppress_legacy_speech(raw, source="global")
    for marker in markers:
        assert marker in stripped, (block_id, marker)
    assert len(stripped) <= len(raw)


def test_suppression_is_idempotent():
    for block_id in LEGACY_CANON_BLOCK_IDS:
        raw = _legacy_source_bytes(block_id)
        once, first = pr.suppress_legacy_speech(raw, source="global")
        twice, second = pr.suppress_legacy_speech(once, source="global")
        assert twice == once, block_id
        assert second.removed == 0, block_id
        assert first.removed > 0, block_id


def test_cleaned_factory_canons_have_no_legacy_markers():
    """CFG-07A-2: фабричные каноны ПОЛНОСТЬЮ вычищенных блоков (все 6
    не-фактчек маршрутов) больше не несут сегменты старой личности —
    подавление на них no-op (маркеров нет). Канон Direct identity-строку
    сохраняет (вне скоупа SF-07) — его подавление проверяется выше.
    ASAP W1: identity-фраза снята также с Вербализатора фактчека (в тесте —
    честная граница: coarse-детектор остаётся на жанровом hostility-
    <bot_knowledge>, фриз CFG-06 W3; identity-маркеров нет)."""
    for block_id in set(_PERSISTED_BYTES) - {"direct.base.tool_phase"}:
        raw = pr.factory_text(block_id)
        _stripped, info = pr.suppress_legacy_speech(raw, source="global")
        if block_id == "factcheck.base.verbalizer":
            assert "токсичн" not in raw and "бот-абьюзер" not in raw
            assert "двача" not in raw
            continue
        assert info.legacy_present is False, block_id
        assert info.applied is False, block_id


def test_custom_value_is_never_edited_but_is_visible_as_conflict():
    """Правила вычистки НЕ трогают байты кастома (data safety).

    Кастом владельца не переписывается самой вычисткой; решение о том, что
    сохранённое значение стало действующим слоем, принимает резолвер по
    провенансу (см. ``test_unattested_custom_is_withheld_from_effective``).
    W1: фабрика вербализатора вычищена — «известный канон со старой
    личностью» для кастома берётся из прод-байтов 2.58.110 (ступень W1).
    """
    raw = chat_prompts.PREV_CHAT_VERBALIZER_W1
    custom = raw + "\n\nМоя правка характера: будь добрее."
    result, info = pr.suppress_legacy_speech(custom, source="global")
    assert result == custom, "кастом владельца изменён"
    assert info.known_canon is False
    assert info.legacy_present is True       # маркер старой личности внутри
    assert info.applied is False


def test_unattested_custom_is_withheld_from_effective():
    """fix-pass review-w1 BLOCKER-1 (§1.2/§4.6/§8): старое PG-значение,
    не записанное через API реестра, НЕ является активным слоем.

    Проверяется полная триада: значение удержано из effective-слоя (действует
    заводская редакция), сохранённые байты целы и читаемы, расхождение
    записано с провенансом (не тихо).
    """
    key = "prompts.direct_chat_verbalizer_system_prompt"
    canon = pr.factory_text("direct.base.l2_writer")
    custom = canon + "\n\nПРАВКА ВЛАДЕЛЬЦА: будь токсичным ботом-абьюзером"
    cache = FakeConfigCache({key: custom})
    hot.set_config_cache(cache)
    try:
        resolved = pr.resolve_speech_value(key, custom, source="global")
        factory_effective = pr.suppress_legacy_speech(canon, source="global")[0]
        assert resolved.withheld is True
        assert resolved.source == "default"        # заводская редакция
        assert resolved.text == factory_effective
        assert resolved.text != custom
        assert "бот-абьюзер" not in resolved.text
        assert resolved.withheld_sha256_12 == pr.sha12(custom)
        assert resolved.provenance_reason == "provenance_missing"
        assert resolved.diagnostics == (
            "persisted_value_withheld", "provenance_missing",
            "persisted_legacy_persona_marker")
        # Сохранённое значение не переписано и остаётся читаемым (retention).
        assert cache.values[key] == custom
        assert cache.writes == []
        row = [r for r in pr.withheld_values(cache=cache)
               if r["pg_key"] == key][0]
        assert row["stored_sha256_12"] == pr.sha12(custom)
        assert row["stored_legacy_persona_marker"] is True
        assert row["withheld_reason"] == "provenance_missing"
    finally:
        hot.set_config_cache(None)


@pytest.mark.asyncio
async def test_registry_written_value_becomes_the_active_layer():
    """Значение, записанное через API реестра, — снова действующий слой (§1.1)."""
    key = "prompts.direct_chat_verbalizer_system_prompt"
    block_id = "direct.base.l2_writer"
    canon = pr.factory_text(block_id)
    custom = canon + "\n\nПРАВКА ВЛАДЕЛЬЦА через реестр: суше, короче."
    cache = FakeConfigCache({key: canon})
    hot.set_config_cache(cache)
    try:
        before = pr.resolve_speech_value(key, canon, source="global")
        assert before.withheld is True          # канон из PG — тоже без провенанса
        result = await pf_mod.write_speech_value(block_id, custom, cache=cache,
                                                actor=7, reason="mini app")
        assert result["applied"] is True
        assert result["effective"] is True
        assert cache.values[key] == custom
        after = pr.resolve_speech_value(key, cache.values[key], source="global")
        assert after.withheld is False
        assert after.source == "global"
        assert after.text == custom
        assert pr.attested_revision(block_id, cache=cache)["sha256_12"] == \
            pr.sha12(custom)
    finally:
        hot.set_config_cache(None)


def test_withholding_is_limited_to_legacy_persona_canons():
    """Класс удержания — PG-каноны старой личности (bounded, не забор).

    Машинные стадии, ключи-селекторы режимов/стилей и writer-блоки без
    признака ``legacy_persona`` сохраняют прежнюю семантику: их PG-значение
    доходит до effective-слоя (иначе сломались бы владельческие настройки
    и уже принятые контракты каталога).
    """
    withholding = {b.pg_key for b in pr.withholding_blocks()}
    assert withholding == {
        "prompts.direct_chat_system_prompt",
        "prompts.direct_chat_verbalizer_system_prompt",
        "prompts.factcheck_system_prompt",
        "prompts.factcheck_verbalizer_system_prompt",
        "prompts.summary_system_prompt",
        "prompts.summary_narrator_system_prompt",
        "prompts.search_system_prompt",
        "prompts.checkup_system_prompt",
        "prompts.youtube_system_prompt",
        "prompts.youtube_video_system_prompt",
        "prompts.webpage_system_prompt",
    }
    assert all(pr.withholding_required(pr.by_pg_key(k)) for k in withholding)
    # Ветки режимов — исключение с причиной: это правила длины/формата,
    # редактируемые во вкладках режимов; их legacy-сегмент снимает вычистка.
    assert pr.withholding_required(
        pr.by_pg_key("prompts.verbilizer_mode_deep_research")) is False
    assert pr.PROVENANCE_EXEMPT_PREFIXES == ("verbilizer.mode.",)
    for pg_key in ("prompts.verbilizer_mode_casual",
                   "prompts.verbilizer_mode_serious",
                   "prompts.verbilizer_default_mode",
                   "prompts.summary_l2_writer_system_prompt",
                   "prompts.direct_l1_planner_system_prompt",
                   "prompts.factcheck_analyst_system_prompt",
                   "prompts.summary_cover_style_id",
                   "prompts.compress_system_prompt"):
        spec = pr.by_pg_key(pg_key)
        assert spec is not None, pg_key
        assert pr.withholding_required(spec) is False, pg_key


def test_registry_version_and_labels_present():
    # W1 открыл реестр (soul1-w1-*); последующие слайсы бампают свою ревизию
    # при осознанной регистрации новых блоков (W3: `style.policy.hint`).
    assert pr.REGISTRY_VERSION.startswith("soul1-w")
    for block_id in LEGACY_BLOCK_IDS:
        assert block_id in pr.FACTORY_REVISION_LABELS


def test_code_path_persona_phrase_is_core_voice_and_registered():
    """FIX-SOUL-F1F3 (F3, позитив): /persona отвечает голосом Core.

    Прежняя код-фраза (старая самоидентификация, аудит §4.2) заменена
    (SOUL-AMD.4.6(в)): реестровая регистрация и владелец сохранены,
    ``legacy_persona`` снят, маркеров old-persona в тексте нет; слот
    ``{tone}`` обязателен (рендер ``handlers/direct_chat.py:253``).
    """
    from services.smartmodule_phrases import CHAT_PERSONA_PHRASE

    spec = pr.block("message.smartmodule.chat_persona")
    assert spec is not None and spec.legacy_persona is False
    assert spec.pg_key is None
    assert spec.owner_lane == "W3"
    assert spec.migration == "managed_message"
    assert spec.ui == "catalog_pending"
    assert pr.factory_text(spec.block_id) == CHAT_PERSONA_PHRASE
    assert "{tone}" in CHAT_PERSONA_PHRASE
    rendered = CHAT_PERSONA_PHRASE.replace("{tone}", "сбалансированный")
    assert "{tone}" not in rendered
    assert not pr.legacy_persona_present(CHAT_PERSONA_PHRASE)
    assert not pr.legacy_persona_present(rendered)


def test_persona_phrase_guard_catches_old_text_regression():
    """FIX-SOUL-F1F3 (F3, негатив): старая фраза снова ловится guard'ом.

    Если прежняя самоидентификация вернётся (во фразу или в модуль-семейство
    ``message.smartmodule.phrases``), маркер реестра её покажет, а тест
    полноты упадёт — тихая регрессия невозможна.
    """
    from services.smartmodule_phrases import CHAT_PERSONA_PHRASE

    old_phrase = ("я тот самый токсичный бот-абьюзер. тон: {tone}. "
                  "настроение подстраиваю сам")
    assert pr.legacy_persona_present(old_phrase) is True
    assert "бот-абьюзер" not in CHAT_PERSONA_PHRASE
    family_text = pr.factory_text("message.smartmodule.phrases")
    assert "токсичный бот-абьюзер" not in family_text
    assert f"CHAT_PERSONA_PHRASE={CHAT_PERSONA_PHRASE}" in family_text


def test_summary_hybrid_l2_canon_legacy_voice_is_stripped():
    """FIX-SOUL-F1F3 (F1, регрессия): канон Summary hybrid-L2 не несёт старый голос.

    Живой канон содержал оборот «сохраняй характер бота и атмосферу конфы»
    (инструкция сохранять старый голос); гейт-маркер расширен ``двач``.
    Голос канала — Core; структурные/фактические контракты канона
    (грамматика, модальность, эвиденция, формат) целы; кастом владельца и
    кодовый fallback (OFF-паритет W2) не затрагиваются.

    CORRECTIVE-FOLLOWUP (21.10.2026, §2): разрешение мата («…и мат
    разрешены») УДАЛЕНО из самого канона — источник устранён, поэтому
    правило 11 (summary.l2_dvach_vocabulary) на текущем каноне больше не
    срабатывает (осталось для СТАРЫХ persisted-байтов); «двачерские
    обороты» сохранены по явному владельческому решению v1.1 (ASAP-2.1 §16).
    """
    canon = pr.factory_text("summary.base.l2_writer")
    assert "мат разрешены" not in canon            # тема мата — только Expression
    stripped, info = pr.suppress_legacy_speech(canon, source="global")
    assert info.known_canon is True and info.legacy_present is True
    assert info.removed == 1, "ожидалось ровно правило 10 (голос Core)"
    assert info.labels == ("summary.l2_legacy_voice_reference",)
    assert "сохраняй характер бота и атмосферу конфы" not in stripped
    assert "держи голос Core" in stripped
    for needle in ("ГРАММАТИКА", "ФАКТЫ И МОДАЛЬНОСТЬ", "ЭВИДЕНЦИЯ",
                   "АКЦЕНТЫ", "ЖЁСТКИЕ ПРАВИЛА", "ФИНАЛ",
                   "ДЛИНА И ДЕДУПЛИКАЦИЯ", "АВТОРЫ И ОТВЕТЫ В ПАКЕТЕ"):
        assert needle in stripped, needle
    again, second = pr.suppress_legacy_speech(stripped, source="global")
    assert again == stripped and second.removed == 0
    custom = canon + "\n\nправка владельца"
    assert pr.suppress_legacy_speech(custom, source="global")[0] == custom
    assert pr.suppress_legacy_speech(canon, source="default")[0] == canon


# ═══ Точки рантайма (интеграция резолверов) ════════════════════════════════

def test_resolve_prompt_suppresses_only_persisted_values():
    key = "prompts.direct_chat_verbalizer_system_prompt"
    canon = pr.factory_text("direct.base.l2_writer")
    # PG down → код-канон байт-в-байт (паритет OFF).
    assert psb.resolve_prompt(key, canon) == canon
    # PG есть → известный канон: провенанса нет ⇒ действует заводская
    # редакция. W1: фабрика §3.1 чиста — вычистка no-op, effective байт-в-байт
    # равен канону, сохранённые байты не тронуты.
    cache = FakeConfigCache({key: canon})
    hot.set_config_cache(cache)
    effective = psb.resolve_prompt(key, canon)
    assert effective == canon
    assert "бот-абьюзер" not in effective
    assert "РОЛЬ И ЗАДАЧА" in effective
    assert cache.values[key] == canon and cache.writes == []
    # Кастом из PG (без записи через API реестра) — тоже не активный слой.
    custom = canon + "\n\nвладельческая строка"
    hot.set_config_cache(FakeConfigCache({key: custom}))
    withheld = psb.resolve_prompt(key, custom)
    assert withheld != custom and "владельческая строка" not in withheld


def test_resolve_prompt_with_source_keeps_vocabulary():
    key = "prompts.factcheck_system_prompt"
    canon = pr.factory_text("factcheck.base.single")
    assert psb.resolve_prompt_with_source(key, canon) == (canon, "default")
    hot.set_config_cache(FakeConfigCache({key: canon}))
    text, source = psb.resolve_prompt_with_source(key, canon)
    # Провенанса нет ⇒ действует заводская редакция → источник ``default``.
    assert source == "default"
    assert "бот-абьюзер" not in text and "вердикт" in text


@pytest.mark.asyncio
async def test_direct_base_channel_resolved_through_registry():
    key = "prompts.direct_chat_system_prompt"

    class ChatCache:
        def __init__(self, overrides):
            self._roots = {777: {"overrides": dict(overrides)}}

        async def get_chat_params(self, chat_id):
            return self._roots.get(int(chat_id), {})

    canon = pr.factory_text("direct.base.tool_phase")
    custom = canon + "\n\nлокальная правка чата"
    hot.set_config_cache(FakeConfigCache({key: canon}))
    # global-слой: провенанса нет → действует заводская редакция, а само
    # значение PG остаётся целым (не переписывается).
    text, source = await pr.resolve_chat_speech(key, canon, chat_id=777)
    assert source == "default" and "бот-абьюзер" not in text
    # chat override без записи через API реестра — тоже удержан (§1.2/§4.6).
    chat_params.set_chat_params_cache(ChatCache({key: custom}))
    text, source = await pr.resolve_chat_speech(key, canon, chat_id=777)
    assert source == "default" and text != custom
    assert "локальная правка чата" not in text
    # Записанный через API реестра override — действующий слой (source=chat).
    ledger = {key: canon}
    hot.set_config_cache(FakeConfigCache({
        **ledger,
        pf_mod.FACTORY_HISTORY_KEY: {
            "v": 1, "items": {},
            pr.PROVENANCE_MAP_FIELD: {"direct.base.tool_phase": {
                "revision": pr.ACTIVE_PREFIX + pr.sha12(custom),
                "sha256_12": pr.sha12(custom), "kind": "owner_edit",
                "scope": "chat", "chat_id": 777,
                "at": "2026-10-16T00:00:00+00:00"}},
        },
    }))
    text, source = await pr.resolve_chat_speech(key, canon, chat_id=777)
    # FIX-CFG07A-F1: attested override — по-прежнему действующий слой
    # (source=chat, владельческая правка цела), но корпусные legacy-маркеры
    # в payload 7 канонов CFG07A гасятся и в кастом-значениях (на сборке,
    # хранение не трогается).
    assert source == "chat"
    assert "локальная правка чата" in text
    assert "бот-абьюзер" not in text
    assert text == pr.suppress_legacy_speech(custom, source="chat",
                                             custom_clean=True)[0]
    # нет ни override, ни PG → кодовый fallback байт-в-байт
    chat_params.set_chat_params_cache(ChatCache({}))
    hot.set_config_cache(None)
    text, source = await pr.resolve_chat_speech(key, canon, chat_id=777)
    assert (text, source) == (canon, "default")


def test_prompt_style_blocks_owner_report_is_registered():
    """Ключи режимов/дефолта: реестр виден, каталог не тронут (Δ каталога 0)."""
    for key in ("prompts.verbilizer_mode_casual", "prompts.verbilizer_default_mode"):
        assert pc.get_by_pg_key(key) is not None
        assert pr.by_pg_key(key) is not None


# ═══ Миграция PG: dry-run → запись → snapshots → откат ═════════════════════

@pytest.mark.asyncio
async def test_normalize_dry_run_apply_idempotent_and_rollback():
    """CFG-07A-2: фабрика search вычищена, поэтому «известным каноном со
    старой личностью» здесь выступает прежний прод-канон (ступень
    PREV_SEARCH_CFG07A) — ровно то, что лежит в PG релиза 2.58.100."""
    key = "prompts.search_system_prompt"
    canon = search_prompts.PREV_SEARCH_CFG07A_SYSTEM_PROMPT
    cache = FakeConfigCache({key: canon})
    hot.set_config_cache(cache)

    plan = await pm.plan_legacy_speech_removal(cache)
    row = [r for r in plan["items"] if r["key"] == key][0]
    assert row["registry_id"] == "search.base.system"
    # CFG-07A-2: прежний прод-канон известен как ступень миграции.
    assert row["class"] == "canon_prev_step"
    assert row["removed"] > 0 and plan["predicted_writes"] >= 1
    assert plan["write"] is False
    assert cache.values[key] == canon, "dry-run записал в PG"

    report = await pm.normalize_legacy_speech(cache, apply=True)
    assert key in report["updated"]
    assert cache.values[key] != canon
    assert "бот-абьюзер" not in cache.values[key]
    snapshots = cache.values[pm.MIGRATION_SNAPSHOTS_KEY]
    assert snapshots["items"][key]["text"] == canon

    second = await pm.normalize_legacy_speech(cache, apply=True)
    assert second["updated"] == {}, "повторный прогон не идемпотентен"
    assert second["written"] == 0

    rollback = await pm.rollback_legacy_speech(cache)
    assert rollback[key] == "rolled_back"
    assert cache.values[key] == canon
    again = await pm.rollback_legacy_speech(cache)
    assert again[key] == "already_original"


@pytest.mark.asyncio
async def test_normalize_never_overwrites_custom_and_skips_pg_down():
    key = "prompts.direct_chat_system_prompt"
    canon = pr.factory_text("direct.base.tool_phase")
    custom = canon + "\n\nкастом владельца"
    cache = FakeConfigCache({key: custom})
    report = await pm.normalize_legacy_speech(cache, apply=True)
    assert cache.values[key] == custom
    assert [row["key"] for row in report["kept_custom"]] == [key]
    assert report["updated"] == {}

    plan = await pm.plan_legacy_speech_removal(cache)
    row = [r for r in plan["items"] if r["key"] == key][0]
    assert row["class"] == "custom_legacy"
    assert "НЕ трогаем" in row["action"]

    offline = FakeConfigCache({key: canon}, pg_available=False)
    report_offline = await pm.normalize_legacy_speech(offline, apply=True)
    assert report_offline["reason"] == "pg_unavailable"
    assert offline.writes == []


@pytest.mark.asyncio
async def test_plan_classifies_absent_and_normalized_states():
    """CFG-07A-2: классификация absent/normalized — на прежнем прод-каноне
    checkup (фабрика вычищена, PG-значение релиза — PREV_*_CFG07A)."""
    key = "prompts.checkup_system_prompt"
    canon = checkup_prompts.PREV_CHECKUP_CFG07A_SYSTEM_PROMPT
    absent = await pm.plan_legacy_speech_removal(FakeConfigCache({}))
    row = [r for r in absent["items"] if r["key"] == key][0]
    assert row["class"] == "absent" and row["removed"] == 0

    cache = FakeConfigCache({key: canon})
    await pm.normalize_legacy_speech(cache, apply=True)
    plan = await pm.plan_legacy_speech_removal(cache)
    row = [r for r in plan["items"] if r["key"] == key][0]
    assert row["class"] == "already_normalized"
    assert row["removed"] == 0
