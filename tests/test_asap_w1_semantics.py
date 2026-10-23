# -*- coding: utf-8 -*-
"""ASAP W1 — семантика слоёв (P0-A/B/C/D/E/F/G), §9.1 source-2026-10-22.md.

Доказывается офлайн (0 Telegram, 0 LLM):
  * P0-A: канон Вербализатора = §3.1 (+ единственная разрешённая
    data-reader адаптация P0A-RISK); ключ/канон в каталоге; без личности,
    мата и форматных правил; используется в L2 (composition head intact);
  * P0-B/C: Core full/compact = §3.2/§3.3 байт-в-байт; нет мат-регулирования
    и SOUL-* в model-facing; семантика Full↔Compact сверена деривацией;
  * P0-D: EXPRESSION_HEADER/FOOTER = §3.4; режимы off/occasional/frequent
    побуквенно прежние; в payload ровно эффективная ветка (не все три);
    mode-блоки legacy (verbilizer_mode_*) не подтягиваются при плане;
  * P0-E: альтернативные типографские правила («только дефис», «только ""»,
    «категорически запрещено «»») из Direct-канонов сняты; Style Policy —
    единственный владелец подачи; валидация/нормализация исходящих не
    тронуты (матрица: в effective конфликта не было, очистка превентивная);
  * P0-F: tool phase сохранил tool/context-контракты, не переопределяет
    Core/Expression/Style; identity/анти-бот сняты; factcheck-вербализатор
    без identity (жанровые правила целы);
  * P0-G: L1 — секция «ВЫБОР УЧАСТИЯ» §3.7; JSON-схема не сломана;
    литературного Core в L1 нет; валидатор кода не назначает delivery сам;
  * Factory/active различимы; рестарт не возвращает старые каноны (лестница);
    owner-preserving патч Core (W0-факт: снять только SOUL-16-ремарку).

TEST-LIFECYCLE: CONTRACT owner=ASAP-W1 P0-A..P0-G (§3.1-3.7, §9.1)
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from services import chat_prompts as cp
from services import factcheck_prompts as fp
from services import mca_expression as ex
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services import prompt_style_blocks as psb

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "plans/features/asap-speech-arch/source-2026-10-22.md"

_IDENTITY_MARKERS = ("токсичн", "бот-абьюзер", "двача")
_TYPO_MARKERS = ("ТИПОГРАФИКА (ОБЯЗАТЕЛЬНО)", "только короткие дефисы",
                 "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире")


def _src_text() -> str:
    return SOURCE_PATH.read_text(encoding="utf-8")


def _fence(heading: str) -> str:
    src = _src_text()
    idx = src.index(heading)
    found = re.compile(r"```text\n(.*?)\n```", re.DOTALL).search(src, idx)
    assert found, heading
    return found.group(1)


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


# ═══ P0-A — Direct L2 Verbalizer (§3.1) ═════════════════════════════════════

def test_p0a_verbalizer_is_owner_text_with_documented_adaptation():
    """§3.1 байт-в-байт + ЕДИНСТВЕННАЯ владельцем разрешённая адаптация
    (P0A-RISK): bullet чтения JSON-пакета Stage-2 («если передан» — JSON
    не обещается вызовам со свободным контекстом).
    ASAP 2 (§4.2 asap2 source): поверх канона W1 — вставка абзацев уточнений
    в «КАК ПИСАТЬ» (текст владельца); байты W1 заморожены в
    PREV_CHAT_VERBALIZER_W1_31 (прод 2.58.111, be03964322aa/1982)."""
    s31 = _fence("### 3.1. P0-A")
    anchor = ("- Подтверждённые сведения, выдержки и результаты инструментов, "
              "если переданы.\n")
    adaptation = ("- Если вход передан JSON-пакетом справки, читай "
                  "обязательные поля: user_question - текущий вопрос, "
                  "facts - подтверждённые сведения, answer_outline - план "
                  "ответа, limitations - границы знания.\n")
    expected = s31.replace(anchor, anchor + adaptation)
    # байты канона W1 §3.1 (прод 2.58.111) заморожены как ступень ASAP 2
    assert cp.PREV_CHAT_VERBALIZER_W1_31 == expected
    assert expected.count("Если вход передан JSON-пакетом") == 1
    # активный канон = W1-канон + вставка §4.2 (и R3b-граница) в «КАК ПИСАТЬ»
    assert cp.DIRECT_VERBALIZER_SYSTEM_PROMPT == expected.replace(
        "обычная болтовня не требует длинного текста.",
        "обычная болтовня не требует длинного текста.\n\n"
        + cp._VERBALIZER_CLAR_PARAGRAPHS + "\n\n"
        + cp._VERBALIZER_HISTORY_BOUNDARY_R3B, 1)
    canon = cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    # вставка ровно одна, в разделе «КАК ПИСАТЬ», до «ВЫХОД»
    assert canon.count("Если намерение пользователя понятно") == 1
    assert canon.index("КАК ПИСАТЬ") < canon.index(
        "Если намерение пользователя понятно") < canon.index("ВЫХОД")


def test_p0a_verbalizer_no_identity_no_mat_no_format_rules():
    canon = cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    for marker in _IDENTITY_MARKERS:
        assert marker not in canon, marker
    for marker in _TYPO_MARKERS:
        assert marker not in canon, marker
    assert "СИСТЕМНАЯ РОЛЬ" not in canon
    # обязательные поля JSON-пакета не стёрты (P0A-RISK)
    for field in ("user_question", "facts", "answer_outline", "limitations"):
        assert field in canon, field
    # Writer не выполняет L1-децизию: нет action/delivery-словаря
    assert '"action"' not in canon and "delivery" not in canon


def test_p0a_verbalizer_registered_editable_resettable_and_used_in_l2():
    """Ключ в каталоге, редактируем, ресетится к НОВОЙ фабрике, реально
    используется в L2 (composition head == канон)."""
    block_id = "direct.base.l2_writer"
    spec = pr.block(block_id)
    assert spec is not None and spec.pg_key == \
        "prompts.direct_chat_verbalizer_system_prompt"
    assert spec.ui == "catalog" and spec.speech is True
    assert pr.factory_text(block_id) == \
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    # ASAP 2: метка ревизии бампнута (l2-writer-clar); R3b: граница истории
    assert pr.factory_revision(block_id).startswith("fac:") and \
        "l2-writer-clar-boundary" in pr.factory_revision(block_id)
    # L2-сборка (каналы композера) сохраняет канон головой payload
    composed = psb.compose_verbalizer_system(
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, "", "plain",
        character_block="<Persona>тест</Persona>")
    assert composed.startswith(cp.DIRECT_VERBALIZER_SYSTEM_PROMPT)


# ═══ P0-B/P0-C — Core full/compact (§3.2/§3.3) ══════════════════════════════

def test_p0bc_core_no_mat_regulation_no_soul_meta_full_and_compact():
    for text, name in ((cp.PERSONALITY_CORE_FULL_TEXT, "full"),
                       (cp.PERSONALITY_CORE_COMPACT_TEXT, "compact")):
        assert not re.search(r"\bмат(а|у|е|ом|ов|ами|ах)?\b", text, re.I), name
        assert "SOUL-" not in text, name
        assert "**Важно:**" not in text, name
        for trope in ("ассистент", "помощник", "я не могу"):
            assert trope not in text, (name, trope)
    # токсичность/цинизм/язвительность/абсурд сохранены как личность (ДОП-1)
    for anchor in ("язвительн", "непристойн", "абсурд",
                   "резким, злым, циничным и неприличным"):
        assert anchor in cp.PERSONALITY_CORE_FULL_TEXT, anchor
    for anchor in ("язвительный", "непристойному юмору", "резким и циничным"):
        assert anchor in cp.PERSONALITY_CORE_COMPACT_TEXT, anchor


def test_p0bc_full_compact_semantics_kept():
    """Семантика Full отражена в Compact (деривация: абзац → маркеры).
    P0-CHECKUP/CORE (24.10.2026): добавлен один owner-абзац (6 абзацев)."""
    full_paras = cp.PERSONALITY_CORE_FULL_TEXT.split("\n\n")
    assert len(full_paras) == 6
    for para_no, markers in cp.PERSONALITY_CORE_COMPACT_DERIVATION:
        for marker in markers:
            assert marker in full_paras[para_no - 1], (para_no, marker)
            assert marker in cp.PERSONALITY_CORE_COMPACT_TEXT, marker


# ═══ P0-D — Expression (§3.4) ═══════════════════════════════════════════════

def test_p0d_expression_header_footer_and_modes_byte_exact():
    assert ex.EXPRESSION_HEADER == _fence("Новый `EXPRESSION_HEADER`")
    assert ex.EXPRESSION_FOOTER == _fence("Новый `EXPRESSION_FOOTER`")
    # тексты режимов побуквенно прежние (§3.4: «не менять текст») — сверка
    # по уникальным префиксам фенсов снапшота
    fences = re.findall(r"```text\n(.*?)\n```", _src_text(), re.DOTALL)
    by_prefix = {f[:20]: f for f in fences}
    assert ex.PROFANITY_INSTRUCTIONS["off"] == \
        by_prefix[ex.PROFANITY_INSTRUCTIONS["off"][:20]]
    assert ex.PROFANITY_INSTRUCTIONS["occasional"] == \
        by_prefix[ex.PROFANITY_INSTRUCTIONS["occasional"][:20]]
    assert ex.PROFANITY_INSTRUCTIONS["frequent"] == \
        by_prefix[ex.PROFANITY_INSTRUCTIONS["frequent"][:20]]
    # служебные описания для разработчиков сняты (§1.4)
    assert "Выражение владельца" not in ex.EXPRESSION_HEADER
    assert "ПРАВИЛА МАНЕРЫ РЕЧИ" in ex.EXPRESSION_HEADER


def test_p0d_render_exactly_effective_branch_not_all_three():
    """§9.1: каждый payload содержит ровно эффективную ветку режима;wit/
    sharpness/verbosity с заводскими значениями сохранены; характер Core
    присутствует при любом режиме (негативный тест ADD-EXPR-INTENSITY)."""
    for mode in ("off", "occasional", "frequent"):
        rendered = ex.render_expression_text(
            ex.resolve_effective({"profanity": mode}, None))
        assert rendered.startswith(ex.EXPRESSION_HEADER)
        assert rendered.endswith(ex.EXPRESSION_FOOTER)
        line = f"- Мат: {ex.PROFANITY_INSTRUCTIONS[mode]}"
        assert line in rendered, mode
        for other in ("off", "occasional", "frequent"):
            if other != mode:
                assert ex.PROFANITY_INSTRUCTIONS[other] not in rendered, \
                    (mode, other)
        assert rendered.count("- Мат:") == 1, mode
    # характер Core при любом режиме не подменяется слоем (слои аддитивны:
    # Core рендерится независимо — негативная проверка владельца текста)
    core = cp.PERSONALITY_CORE_FULL_TEXT
    for mode in ("off", "occasional", "frequent"):
        rendered = ex.render_expression_text(
            ex.resolve_effective({"profanity": mode}, None))
        assert core not in rendered  # слой не подменяет Core
        assert "абсурд" in core      # Core неизменен при любом режиме


def test_p0d_wit_sharpness_verbosity_controls_kept():
    """P0D-INVARIANTS: прочие контролы и заводские значения сохранены."""
    assert ex.CONTROL_ORDER == ("wit", "sharpness", "profanity", "verbosity")
    assert ex.EXPRESSION_FACTORY_DEFAULTS == {"profanity": "occasional"}
    assert ex.EXPRESSION_MODES == ("inherit", "off", "occasional", "frequent")
    rendered = ex.render_expression_text(ex.resolve_effective(
        {"profanity": "off", "sharpness": "sharp", "verbosity": "long"}, None))
    assert "Резкость: " in rendered and "Развёрнутость: " in rendered


def test_p0d_legacy_mode_blocks_not_pulled_into_payload():
    """W0-факт: verbilizer_mode_* (PG-кастомы 19.09) не сняты — при плане
    (extent-блок) mode-блоки legacy в payload НЕ подтягиваются; без плана —
    ровно один mode-блок, никогда не все три."""
    composed = psb.compose_verbalizer_system(
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, "casual", "plain",
        extent_block="ОЖИДАЕМАЯ ПОЛНОТА: ПОДРОБНО.")
    assert "ОЖИДАЕМАЯ ПОЛНОТА: ПОДРОБНО." in composed
    for block in (psb.MODE_CASUAL_BLOCK, psb.MODE_SERIOUS_BLOCK,
                  psb.MODE_DEEP_RESEARCH_BLOCK):
        assert block not in composed, "mode-блок легаси подтянулся при плане"
    # без плана — ровно один mode-блок (не все три)
    composed2 = psb.compose_verbalizer_system(
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, "casual", "plain")
    assert psb.MODE_CASUAL_BLOCK in composed2
    assert psb.MODE_SERIOUS_BLOCK not in composed2
    assert psb.MODE_DEEP_RESEARCH_BLOCK not in composed2


# ═══ P0-E — Style Policy: один владелец подачи ══════════════════════════════

def test_p0e_no_alternative_typography_rules_in_direct_canons():
    """Конфликт «запрет кавычек» vs «обязательные ""» устранён на фабрике:
    альтернативные правила типографики из Direct L2 и tool phase сняты.
    W0-факт (матрица): в effective 2.58.110 конфликта не было (cleaned-
    тексты чисты) — очистка фабрик превентивная."""
    for name, canon in (("l2_writer", cp.DIRECT_VERBALIZER_SYSTEM_PROMPT),
                        ("tool_phase", cp.CHAT_SYSTEM_PROMPT)):
        for marker in _TYPO_MARKERS:
            assert marker not in canon, (name, marker)
        assert "кавычки" not in canon.lower(), name
    # Style Policy рендерит свои правила сам (hint — единственный источник)
    from services.style_policy import EffectiveStylePolicy
    policy = EffectiveStylePolicy(
        extent="", rules=(), soft_instructions=(), source="global",
        revision="t", skip_reason="")
    hint = psb.render_style_policy_hint(policy)
    assert hint == ""  # нет активных правил → пусто, без альтернатив


def test_p0e_style_hint_composition_is_policy_only():
    """Собранный hint соответствует typed-значениям (§3.5 — результат
    рендера), не самостоятельный промпт."""
    from services.style_policy import EffectiveStylePolicy
    from services import style_policy as sp_mod
    policy = sp_mod.effective_policy_sync(
        None,
        {"rules": [{"id": "q", "kind": "quotation_marks",
                    "strictness": "hard", "scope": "global", "enabled": True,
                    "params": {}}],
         "soft_instructions": []},
        context="regular")
    hint = psb.render_style_policy_hint(policy)
    assert hint.startswith(psb.STYLE_POLICY_HINT_OPEN)
    assert psb.HINT_QUOTES_HARD in hint
    assert "дословный текст не переписывай" in hint


# ═══ P0-F — Direct tool phase (§3.6) + фактчек-вербализатор ════════════════

def test_p0f_tool_phase_keeps_tool_context_contracts():
    canon = cp.CHAT_SYSTEM_PROMPT
    for contract in ("UserResolutionMap", "Current_Question",
                     "Conversation_Thread", "Conversation_Branch",
                     "Protected_Facts", "chat_lore", "user_relations",
                     "RAG_Memory", "Global_Context",
                     "query_chat_memory", "dig_into_lore",
                     "execute_web_search",
                     "АНТИ-ГАЛЛЮЦИНАЦИИ", "СЛУЖЕБНЫЕ ПОМЕТКИ",
                     "ОТНОШЕНИЯ", "КАК ЧИТАТЬ КОНТЕКСТ"):
        assert contract in canon, contract
    # capability/фактические инструкции вызова tools не сломаны
    assert canon.index("ИНСТРУМЕНТЫ:") < canon.index("ГЛАВНОЕ ОГРАНИЧЕНИЕ")


def test_p0f_tool_phase_does_not_override_core_expression_style():
    canon = cp.CHAT_SYSTEM_PROMPT
    for marker in _IDENTITY_MARKERS + ("АНТИ-БОТ", "АСИММЕТРИЯ",
                                       "торопливое письмо",
                                       "СИСТЕМНАЯ РОЛЬ", "ПРИОРИТЕТЫ:",
                                       "Разрешен мат"):
        assert marker not in canon, marker
    assert ("Этот этап не задаёт личность, лексику, манеру письма или "
            "финальную типографику." in canon)
    assert "ПРАВИЛА МАНЕРЫ РЕЧИ" not in canon  # Expression-слой не повторён
    assert "абсурдн" not in canon.lower()      # Core не переписан


def test_p0f_factcheck_verbalizer_identity_removed_genre_kept():
    fv = fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT
    for marker in _IDENTITY_MARKERS:
        assert marker not in fv, marker
    # жанровые правила сохранены (нормализация точечная, не по шаблону)
    assert "Ты получаешь ТОЛЬКО готовый разбор в формате JSON от аналитика." \
        in fv
    for marker in ("claim, findings, verdict", "Вынеси дерзкий вердикт",
                   "{max_symbols}", "СТИЛЬ" if False else "АНТИ-БОТ"):
        assert marker in fv, marker
    # прежние прод-байты (с identity) — в слепке/ступени
    assert "токсичный" in fp.PREV_FACTCHECK_VERBALIZER_W1
    assert (fp.PREV_FACTCHECK_VERBALIZER_W1,
            fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT) in \
        pm.PROMPT_MIGRATIONS["prompts.factcheck_verbalizer_system_prompt"]


def test_p0f_matrix_other_channels_audit():
    """P0F-MATRIX: активные фабрики остальных пользовательских канонов без
    identity-фраз (вычищены ранее CFG-07A-2/LEGFIX; narrator — вне W1)."""
    from services import search_prompts as sp
    from services import summary_prompts as sm
    from services import web_prompts as wp
    from services import youtube_prompts as yt
    for name, canon in (
            ("search", sp.SEARCH_SYSTEM_PROMPT),
            ("summary", sm.SYSTEM_PROMPT),
            ("web", wp.WEBPAGE_SYSTEM_PROMPT),
            ("youtube", yt.YOUTUBE_SYSTEM_PROMPT),
            ("youtube_video", yt.YOUTUBE_VIDEO_SYSTEM_PROMPT)):
        for marker in ("бот-абьюзер", "завсегдатай двача"):
            assert marker not in canon, (name, marker)
    # narrator: LEGFIX-канон мастера без identity (на прод приедет релизом
    # 2.58.111; слайс вне зоны W1 по решению Оркестратора)
    assert "токсичный" not in sm.SUMMARY_NARRATOR_SYSTEM_PROMPT


# ═══ P0-G — L1 «ВЫБОР УЧАСТИЯ» (§3.7) ═══════════════════════════════════════

def test_p0g_l1_participation_section_byte_exact():
    assert cp._DIRECT_L1_PARTICIPATION_W1 == _fence("### 3.7. P0-G")
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # SPEECH-INIT-FIX R3: активная секция — усиленная семантика доставки;
    # прежние байты W1 остаются замороженными (ступень/откат).
    assert cp._DIRECT_L1_PARTICIPATION_W1 not in canon
    assert cp._DIRECT_L1_PARTICIPATION_R3 in canon
    assert "ФОРМА УЧАСТИЯ" not in canon
    # схема/обязательные поля не сломаны
    for field in ('"action": "reply|react|silent"',
                  '"delivery": "chat|reply|null"',
                  '"target_message_id": null', '"target_user_id": null',
                  '"confidence": 0.0', '"future_intent": null'):
        assert field in canon, field
    # литературный Core в L1 не вставлен; L1 не обязан ругаться.
    # ASAP 2 (§4.1 asap2 source): единственное вхождение «юмор» — фраза
    # владельца в контракте уточнений («юмор и инициативное участие не
    # являются техническим needs_clarification»), не Core-контент.
    assert "абсурд" not in canon
    assert canon.lower().count("юмор") == 1
    assert ("юмор и инициативное участие не являются техническим "
            "needs_clarification" in canon)
    for marker in _IDENTITY_MARKERS:
        assert marker not in canon, marker


def test_p0g_parser_contract_unchanged_and_validator_never_assigns():
    """Контракт парсера под реальными именами: action=reply, delivery=
    chat|reply, target_message_id; reply-привязка = совместная валидность
    всех полей; код не назначает delivery сам (только запрещает
    невозможное); хелпер ТЗ has_explicit_reply_intent не существует —
    фактическое имя reply_binding_requested (сверка PM/Builder)."""
    from services import direct_l1 as l1
    assert l1.L1_DELIVERY_MODES == ("chat", "reply")
    assert not hasattr(l1, "has_explicit_reply_intent")
    plan = l1.normalize_l1_plan({"action": "reply", "delivery": "reply",
                                 "target_message_id": 42})
    assert l1.reply_binding_requested(plan) is True
    # отсутствие любого поля → reply-привязки нет (fail-closed)
    for data in ({"action": "reply", "delivery": "reply"},
                 {"action": "reply", "target_message_id": 42},
                 {"action": "reply", "delivery": "chat",
                  "target_message_id": 42}):
        assert l1.reply_binding_requested(l1.normalize_l1_plan(data)) is False
    # fallback-план кода не назначает доставку
    fb = l1.fallback_plan("вопрос")
    assert fb.delivery == "" and fb.target_message_id is None


# ═══ §9.1: factory vs active, рестарт, кастомы, owner-preserving ═══════════

def test_91_factory_and_active_revisions_distinguishable():
    rev = pr.factory_revision("direct.base.l2_writer")
    assert rev.startswith("fac:") and "l2-writer-clar-boundary" in rev
    eff = pr.effective_prompt("direct.base.l2_writer")
    assert eff.factory_revision.startswith("fac:")
    assert eff.revision.startswith("act:") or eff.revision == ""


def test_91_ladder_prevents_old_canon_return_and_keeps_customs():
    """Рестарт/редеплой не возвращает старый Core/L2 (лестница ведёт
    прод-байты 2.58.110 на новые каноны; reset-to-factory = новая фабрика);
    кастом владельца лестницей не трогается; per-chat не трогаются."""
    # PREV-лестницы на месте (байт-сверка с W0-инвентаризацией — в модуле)
    steps = pm.PROMPT_MIGRATIONS["prompts.direct_chat_verbalizer_system_prompt"]
    assert (cp.PREV_CHAT_VERBALIZER_W1,
            cp.DIRECT_VERBALIZER_SYSTEM_PROMPT) in steps
    # reset-to-factory = новая фабрика (не PREV)
    assert pr.factory_text("direct.base.l2_writer") == \
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    assert pr.factory_text("direct.base.l2_writer") != \
        cp.PREV_CHAT_VERBALIZER_W1
    # Core: PREV-байты (v1/v2) в PG не действуют; кастом не подменяется
    sel = pr.core_selection(
        {"full_text": cp.PREV_PERSONALITY_CORE_FULL_V2_TEXT}, source="global")
    assert sel["superseded_fields"] == ("full_text",)
    assert sel["full_text"] == cp.PERSONALITY_CORE_FULL_TEXT
    selc = pr.core_selection(
        {"full_text": cp.PERSONALITY_CORE_FULL_TEXT + " правка"},
        source="global")
    assert selc["superseded_fields"] == ()


def test_91_owner_preserving_core_patch_removes_only_service_remark():
    """W0-факт: активная правка владельца (rev 6) уже без мата; патч снимает
    ТОЛЬКО SOUL-16-ремарку и (P0-CHECKUP/CORE 24.10.2026) добавляет один
    отсутствующий owner-абзац — остальное байт-в-байт."""
    v2 = cp.PREV_PERSONALITY_CORE_FULL_V2_TEXT
    owner_edit = v2 + " Дополнение владельца."   # синтетика owner-edit
    patched, changes = pm.owner_preserve_core_full_patch(owner_edit)
    assert len(changes) == 2
    assert "Важно" in changes[0]
    assert changes[1] == pm._CORE_REAL_EVENTS_CHANGE
    assert "SOUL-16" not in patched and "**Важно:**" not in patched
    assert cp.CORE_REAL_EVENTS_PARAGRAPH in patched
    assert patched.endswith(" Дополнение владельца.")   # owner-хвост цел
    assert "**Грубость.**" in patched            # владельческий текст цел
    # уже чистый текст → идемпотентный no-op
    clean = cp.PERSONALITY_CORE_FULL_TEXT + " правка"
    assert pm.owner_preserve_core_full_patch(clean) == (clean, [])
    # v1/v2 байты гасит superseded-гвард, а не патч
    p, r = pm.owner_preserve_core_full_patch(cp.PREV_PERSONALITY_CORE_FULL_TEXT)
    assert p == cp.PREV_PERSONALITY_CORE_FULL_TEXT
    assert r == [pm._CORE_SUPERSEDED_NOTE]


def test_91_composer_parity_machine_stages_clean():
    """Внутренние JSON-процессы не загрязняются характером; финальные
    пользовательские тексты получают разрешённые слои."""
    manifest = pc_compose_machine()
    assert manifest.system == "БАЗА"   # Core/Expression не подключены
    from services import prompt_composer as pc
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=1,
        base_prompt=cp.DIRECT_VERBALIZER_SYSTEM_PROMPT,
        core=pc.CoreRef(text=cp.PERSONALITY_CORE_FULL_TEXT, revision="r7"),
        expression=pc.ExpressionSettings(
            text=ex.render_expression_text(
                ex.resolve_effective({"profanity": "off"}, None)),
            revision="e1", mode="off"),
        gates=pc.GateState(unified_composer_enabled=True))
    manifest = pc.compose_prompt(plan)
    assert cp.PERSONALITY_CORE_FULL_TEXT in manifest.system
    assert "Не используй мат в собственной речи." in manifest.system


def pc_compose_machine():
    from services import prompt_composer as pc
    plan = pc.PromptPlan(
        profile="machine_json", writer="factcheck_extract", chat_id=7,
        base_prompt="БАЗА",
        core=pc.CoreRef(text=cp.PERSONALITY_CORE_FULL_TEXT, revision="r7"),
        gates=pc.GateState(unified_composer_enabled=True))
    return pc.compose_prompt(plan)
