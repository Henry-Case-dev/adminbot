# -*- coding: utf-8 -*-
"""ADD-SAMPLES-UX §2+§5 (SU-FEWSHOT) — дословные режимы, категорийные блоки,
MAT-изоляция, bounded-отбор, «Почему…».

Покрытие:
  * SU-TXT.EPISODIC/FREQUENT/OFFINHERIT — канонические тексты байт-в-байт;
    прежние F3-формулировки отсутствуют; off/inherit не менялись;
  * SU-TXT.REPLACE — тексты рендерятся в слое, без квот/счётчиков/пост-
    процессора; UI-метки «Эпизодически/Часто» не входят в канон инструкций;
  * SU-FS.BLOCKS — различимые блоки General_Examples / `<Examples>` (юмор) /
    `<Expression_Examples mode=…>`; mat-пример не попадает в юмор-блок по
    совпадению слов, humor-пример не становится регистром из-за обсценного
    слова; MAT — только approved примеры effective-режима;
  * SU-FS.BOUNDED — 1–3 / ноль допустим, PII/cross-chat защита, 0 LLM;
  * SU-FS.WHY — человеческие причины из существующего отбора, честное
    «Нет данных о последнем выборе»;
  * SU-6.WISHES — «Пожелания своими словами» остаются в слое Expression.

TEST-LIFECYCLE: CONTRACT owner=SAMPLES-UX/SU-FS.*, SU-TXT.* (§2/§5)
"""
import pytest
import pytest_asyncio

from services import mca_expression as ex
from services import mca_sample_library as sl
from services.database import DatabaseService

#: ADD-SAMPLES-UX §2 — точные тексты владельца (байт-в-байт).
EPISODIC_TEXT = ("Пиши разговорным языком с примесью мата. Нецензурные "
                 "выражения используй как обычные эмоциональные оценки и "
                 "междометия, без необходимости специально обосновывать их "
                 "появление. Мат не должен доминировать в речи.")
FREQUENT_TEXT = ("Пиши на живом разговорном языке с выраженным "
                 "использованием мата. Нецензурная лексика — привычная "
                 "часть твоего словаря: оценки, междометия, усиления и "
                 "разговорные связки. Не заменяй её цензурными эвфемизмами.")
OFF_TEXT = "Не используй мат в собственной речи."

#: Прежние F3-формулировки не должны остаться нигде в каноне.
F3_LEGACY_TEXTS = (
    "Иногда используй мат в обычной разговорной речи",
    "Не жди особого повода",
    "не матерись постоянно",
    "Матерись свободно и регулярно",
    "Используй его в большинстве неформальных реплик",
    "но не вставляй насильно",
)


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPRESSION_EXAMPLES_ENABLED", "1")
    service = DatabaseService(str(tmp_path / "samples-fewshot.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


# ═══ SU-TXT: дословные режимы ══════════════════════════════════════════════

def test_section2_texts_are_byte_exact():
    assert ex.PROFANITY_INSTRUCTIONS["occasional"] == EPISODIC_TEXT
    assert ex.PROFANITY_INSTRUCTIONS["frequent"] == FREQUENT_TEXT
    assert ex.PROFANITY_INSTRUCTIONS["off"] == OFF_TEXT


def test_legacy_f3_texts_absent_from_canon_module():
    import pathlib
    src = pathlib.Path("services/mca_expression.py").read_text(
        encoding="utf-8")
    body = "\n".join(ex.PROFANITY_INSTRUCTIONS.values())
    for legacy in F3_LEGACY_TEXTS:
        assert legacy not in body, legacy
        assert legacy not in src.split("PROFANITY_INSTRUCTIONS")[1].split(
            "CONTROL_INSTRUCTIONS")[0], legacy


def test_off_and_inherit_unchanged():
    # off — прежний текст; inherit — механизм наследования, не интенсивность.
    assert ex.normalize_mode("inherit") == "inherit"
    assert "inherit" not in ex.PROFANITY_INSTRUCTIONS
    eff = ex.resolve_effective({"profanity": "inherit"},
                               {"profanity": "occasional"})
    assert ex.effective_mode(eff) == "occasional"   # GLOBAL → CHAT наследование
    empty = ex.resolve_effective(None, None)
    assert empty["controls"]["profanity"]["value"] == "occasional"


def test_rendered_layer_uses_section2_texts():
    occ = ex.render_expression_text(ex.resolve_effective(
        {"profanity": "occasional"}, None))
    freq = ex.render_expression_text(ex.resolve_effective(
        {"profanity": "frequent"}, None))
    assert ("- Мат: " + EPISODIC_TEXT) in occ.splitlines()
    assert ("- Мат: " + FREQUENT_TEXT) in freq.splitlines()
    # «Пожелания своими словами» остаются внутри Expression (SU-6.WISHES)
    wish = ex.render_expression_text(
        {"enabled": True, "profanity": "off", "note": "помягче"})
    assert "- Пожелание владельца: помягче" in wish.splitlines()


def test_factory_set_fingerprint_unaffected_by_directives():
    # §2-тексты НЕ входят в factory-set реестра (проверено штатной
    # factory_set_fingerprint): F8-bump не требуется, константа стабильна.
    from services import prompt_registry as pr
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12
    assert "occasional" not in pr.factory_texts()
    factory_texts = pr.factory_texts().values()
    joined = "\n".join(factory_texts)
    for legacy in F3_LEGACY_TEXTS:
        assert legacy not in joined, legacy


# ═══ SU-FS.BLOCKS: категорийные блоки без смешивания ═══════════════════════

def _row(idx, category, *, approved=1, technique="other", inp="", reply="",
         mode=None, chat_id=None, scope="global", sensitive=False):
    return {
        "id": idx, "input_text": inp, "reply_text": reply,
        "technique": technique, "context_note": "", "language": "ru",
        "tags": [], "rudeness_level": 0, "source_kind": "owner_manual",
        "scope": scope, "chat_id": chat_id,
        "owner_approved": approved, "status": "active",
        "library_version": "v1", "revision": 1, "uses_count": 0,
        "last_used_at": None,
        "sensitivity_flags": ["phone"] if sensitive else [],
        "category": category, "expression_mode": mode,
        "owner_modified": 0,
    }


def test_blocks_are_separately_labeled_by_category():
    general = [_row(1, "general", inp="вход", reply="ответ")]
    humor = [_row(2, "humor", technique="deadpan", inp="шутка",
                  reply="смешно")]
    g_block = sl.render_general_block(general)
    h_block = sl.render_block(humor)
    assert g_block.startswith("<General_Examples>")
    assert g_block.endswith("</General_Examples>")
    assert h_block.startswith("<Examples>")
    assert "Вход: шутка" in h_block
    # без смешивания без метки: general-строка не рендерится в humor-блоке
    assert "Вход: вход" not in h_block
    expr_block = ex.render_expression_examples_block(
        "occasional", [{"context_note": "тема", "input_text": "вход",
                        "reply_text": "ответ"}])
    assert expr_block.startswith('<Expression_Examples mode="occasional">')


def test_mat_example_never_enters_humor_block_by_word_match():
    # §5: mat-пример не становится юмором по совпадению слов.
    rows = [
        _row(1, "mat", approved=1, technique="expression_register",
             inp="шутка про чайник", reply="хохма", mode="off"),
        _row(2, "humor", approved=1, technique="deadpan",
             inp="шутка про чайник", reply="юмор-ответ"),
    ]
    selection = sl.select_samples(rows, chat_id=1, category="humor",
                                  context="шутка про чайник")
    assert [r["id"] for r in selection.samples] == [2]
    assert any(e["id"] == 1 and e["reason"] == "expression_register"
               for e in selection.excluded)


def test_humor_example_with_obscene_word_stays_humor():
    # §5: humor-пример не назначается речевым регистром из-за обсценного слова.
    rows = [
        _row(1, "humor", approved=1, technique="deadpan",
             inp="история с пиздецом", reply="смешно же"),
        _row(2, "mat", approved=1, technique="expression_register",
             inp="вход", reply="ответ", mode="occasional"),
    ]
    selection = sl.select_samples(rows, chat_id=1, category="humor",
                                  context="история")
    assert [r["id"] for r in selection.samples] == [1]
    # и наоборот: в регистр идут только mat-строки
    expr_rows, reason = None, None  # resolve тестируется ниже на живой БД


@pytest.mark.asyncio
async def test_expression_selection_reads_field_not_tags(db):
    await sl.seed_expression_samples(db)
    rows = await sl.list_samples(db, chat_id=None, category="mat")
    target = next(r for r in rows if r["expression_mode"] == "occasional")
    # утверждаем владельцем
    approved, _ = await sl.set_approval(db, target["id"], approved=True,
                                        actor="owner")
    assert approved["owner_approved"] is True
    # поле говорит occasional, тег говорит mode:occasional — совпадают;
    # теперь подменим поле при теге frequent-карточки: поле решает.
    frequent_rows = [r for r in rows if r["expression_mode"] == "frequent"]
    frequent_ids = [r["id"] for r in frequent_rows]
    for rid in frequent_ids:
        # ставим полю 'occasional' при теге mode:frequent — строка должна
        # отобраться как occasional (поле), а не как frequent (тег).
        await db.db.execute(
            "UPDATE humor_samples SET expression_mode = 'occasional' "
            "WHERE id = ?", (rid,))
        await sl.set_approval(db, rid, approved=True, actor="owner")
    selected, reason = await sl.resolve_expression_examples_ex(
        777, "occasional", db=db)
    assert reason == ""
    got_ids = {r["id"] for r in selected}
    assert target["id"] in got_ids
    assert frequent_ids and frequent_ids[0] in got_ids  # по полю, не по тегу
    frequent_selection, _ = await sl.resolve_expression_examples_ex(
        777, "frequent", db=db)
    assert frequent_selection == ()      # полей frequent больше нет
    # неутверждённые — честная причина, не «absent»
    draft_only, reason = await sl.resolve_expression_examples_ex(
        778, "frequent", db=db)
    assert draft_only == () and reason in ("expression_examples_absent",
                                           "not_owner_approved")


@pytest.mark.asyncio
async def test_mat_only_approved_examples_of_effective_mode(db):
    await sl.seed_expression_samples(db)
    # ни одна не утверждена → честная причина not_owner_approved (BLOCK-1)
    rows, reason = await sl.resolve_expression_examples_ex(777, "off", db=db)
    assert rows == () and reason == "not_owner_approved"
    # утверждаем off-строку — она и только она попадает в off-выдачу
    rows_all = await sl.list_samples(db, chat_id=None, category="mat")
    off_rows = [r for r in rows_all if r["expression_mode"] == "off"]
    for r in off_rows:
        await sl.set_approval(db, r["id"], approved=True, actor="owner")
    selected, reason = await sl.resolve_expression_examples_ex(777, "off",
                                                               db=db)
    assert reason == "" and selected
    assert all(r["expression_mode"] == "off" for r in selected)
    assert all(r["owner_approved"] for r in selected)


# ═══ SU-FS.BOUNDED: ограничения, изоляция, 0 LLM ═══════════════════════════

def test_bounded_selection_one_to_three_or_zero_with_reasons():
    rows = [_row(i, "humor", approved=1, technique="deadpan",
                 inp=f"вход {i}", reply=f"ответ {i}") for i in range(1, 8)]
    selection = sl.select_samples(rows, chat_id=1, category="humor")
    assert 0 <= len(selection.samples) <= 3
    assert selection.reason_code in ("samples_selected", "samples_absent")
    assert selection.excluded, "причины пропуска отдаляются честно"
    # ноль допустим: пустая библиотека
    empty = sl.select_samples([], chat_id=1, category="humor")
    assert empty.samples == () and empty.reason_code == "samples_absent"
    # PII-защита
    sensitive = [_row(99, "humor", approved=1, inp="вход",
                      reply="звоните +7 999 123 45 67", sensitive=False)]
    guarded = sl.select_samples(sensitive, chat_id=1, category="humor")
    assert guarded.samples == ()
    # cross-chat изоляция
    chat_row = [_row(98, "humor", approved=1, inp="в", reply="о",
                     scope="chat", chat_id=4242)]
    guarded = sl.select_samples(chat_row, chat_id=1, category="humor")
    assert guarded.samples == ()
    assert any(e["reason"] == "cross_chat_guard" for e in guarded.excluded)


def test_general_selection_bounded_and_separate_from_humor():
    rows = [_row(i, "general", approved=1, inp=f"вход {i}", reply=f"ответ {i}")
            for i in range(1, 6)]
    rows += [_row(50, "humor", approved=1, technique="deadpan",
                  inp="шутка", reply="смешно")]
    selection = sl.select_samples(rows, chat_id=1, category="general")
    assert 0 <= len(selection.samples) <= 3
    assert all(r["category"] == "general" for r in selection.samples)
    assert any(e["id"] == 50 and e["reason"] == "category_mismatch"
               for e in selection.excluded)


@pytest.mark.asyncio
async def test_resolve_refs_emits_both_labeled_blocks(db, monkeypatch):
    from services import mca_gates
    monkeypatch.setenv("HUMOR_LIBRARY_ENABLED", "1")
    monkeypatch.setattr(mca_gates, "humor_library_enabled", lambda: True)
    general_view, _ = await sl.create_sample(db, fields={
        "input_text": "обычный вход", "reply_text": "обычный ответ",
        "category": "general"}, actor="owner")
    humor_view, _ = await sl.create_sample(db, fields={
        "input_text": "шутка вход", "reply_text": "шутка ответ",
        "category": "humor", "technique": "deadpan"}, actor="owner")
    # создание всегда даёт черновик (SOUL-07.1); эталон ставит владелец.
    await sl.set_approval(db, general_view["id"], approved=True, actor="owner")
    await sl.set_approval(db, humor_view["id"], approved=True, actor="owner")
    refs, selection = await sl.resolve_refs(db=db, chat_id=777)
    block_ids = [r.block_id for r in refs]
    assert "general_few_shot" in block_ids and "few_shot" in block_ids
    general_ref = next(r for r in refs if r.block_id == "general_few_shot")
    humor_ref = next(r for r in refs if r.block_id == "few_shot")
    assert general_ref.text.startswith("<General_Examples>")
    # humor-refs — построчные (существующий контракт few_shot-слоя)
    assert "Вход: шутка вход" in humor_ref.text
    assert "обычный вход" not in humor_ref.text
    assert "шутка вход" not in general_ref.text
    assert selection.reason_code == "samples_selected"


# ═══ SU-FS.WHY: честные причины ════════════════════════════════════════════

@pytest.mark.asyncio
async def test_why_for_draft_and_selected_cards(db):
    view, _ = await sl.create_sample(db, fields={
        "input_text": "вход черновика", "reply_text": "ответ",
        "category": "humor", "technique": "deadpan"}, actor="owner")
    result = await sl.why_for_sample(db, chat_id=777, sample_id=view["id"])
    assert result["ok"] is True and result["selected"] is False
    assert result["why"] == "Черновик — ещё не утверждён"
    await sl.set_approval(db, view["id"], approved=True, actor="owner")
    result = await sl.why_for_sample(db, chat_id=777, sample_id=view["id"])
    assert result["selected"] is True
    assert "Выбран" in result["why"] and "Юмор" in result["why"]


@pytest.mark.asyncio
async def test_why_mode_mismatch_is_human_readable(db):
    await sl.seed_expression_samples(db)
    rows = await sl.list_samples(db, chat_id=None, category="mat")
    target = next(r for r in rows if r["expression_mode"] == "off")
    result = await sl.why_for_sample(db, chat_id=777, sample_id=target["id"],
                                     effective_mode="frequent")
    assert result["selected"] is False
    assert "режиму «Без мата»" in result["why"]
    assert "«Часто»" in result["why"]


@pytest.mark.asyncio
async def test_why_honest_no_data(db, monkeypatch):
    view, _ = await sl.create_sample(db, fields={
        "input_text": "вход", "reply_text": "ответ",
        "category": "general", "owner_approved": True}, actor="owner")
    # политика отбора выключена → данных последнего выбора нет,
    # причина не симулируется
    async def _disabled_policy(chat_id):
        return {"enabled": False}, "test"
    monkeypatch.setattr(sl, "resolve_policy", _disabled_policy)
    result = await sl.why_for_sample(db, chat_id=777, sample_id=view["id"])
    assert result["selected"] is False
    assert result["why"] == "Отбор примеров выключен политикой"
    assert result["reason_code"] == "samples_disabled"
