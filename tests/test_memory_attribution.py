"""MEMORY-05 (C-8 §8) — социальная, эпизодическая и мультимодальная атрибуция.

Контракт: `plans/features/memory-cognitive-02/contracts.md` §8 (MEM-05.1…05.7),
§3.3.1 (модальность только из сигналов), §2.2.1 (авторство), R-9.

Проверяется не форма питона, а невозможность нечестных состояний:

* адресат, выдуманный при нескольких кандидатах (или при полном отсутствии
  сигнала);
* содержание пересылки, приписанное переславшему;
* цитата, склеенная с автором сообщения;
* собственный вывод бота, «подтверждающий» внешний факт;
* `not_processed`/`unavailable` медиа, прочитанное как понимание;
* постоянное правило поведения из одной неудачи;
* модальность из кавычек/смайлика/длины, а не из сигнала;
* второй durable-store на слой памяти и запись из слоя атрибуции.
"""
from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path

import pytest

from services import memory_attribution as ma
from services import memory_contracts as mc
from services import mca_vision, provenance
from services import summary_memory
from services.database import DatabaseService

CHAT = -1007000000001
SERVICES_DIR = Path(__file__).resolve().parents[1] / "services"
#: Ростер участников читается окном «последние N часов», поэтому сообщения
#: теста датируются текущим временем (иначе это архив, а не активные люди).
NOW = int(time.time())


# ── инфраструктура ─────────────────────────────────────────────────────────

async def _fresh(tmp_path, name="memory05.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


def _enable_attribution(monkeypatch) -> None:
    """Гейт C-8 ON через реальный резолвер: env + каталоговый слой (`hot.get`)."""
    import services.hot_config as hot

    real_get = hot.get

    def fake_get(key, default=None):
        if key == "flags.memory_attribution_enabled":
            return True
        return real_get(key, default)

    monkeypatch.setenv("MCA_MEMORY_ATTRIBUTION_ENABLED", "on")
    monkeypatch.setattr(hot, "get", fake_get)


async def _msg(d, *, user_id, author_name, text, tg, chat_id=CHAT,
               ts=NOW, reply_to=None, reply_author=None,
               is_forward=False, forward_source="", forward_author=None,
               quote_author=None, quote_text=None, media_type="text"):
    cur = await d.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, tg_message_id, reply_to_id, "
        "reply_to_author_id, is_forward, forward_source, forward_author_id, "
        "quote_author_id, quote_text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, chat_id, text, ts, media_type, author_name, tg, reply_to,
         reply_author, 1 if is_forward else 0, forward_source,
         forward_author, quote_author, quote_text))
    await d.db.commit()
    return cur.lastrowid


class _NullLLM:
    """LLM не участвует в атрибуции: вызов был бы нарушением (INV-10)."""

    generate_calls = 0

    async def generate(self, *args, **kwargs):        # pragma: no cover
        type(self).generate_calls += 1
        raise AssertionError("attribution must not call an LLM")


# ── MEM-05.2: адресат ──────────────────────────────────────────────────────

def test_reply_target_wins_over_semantic_guess():
    """§8.2: точный reply target важнее «ближайшего» семантического контекста."""
    resolved = ma.resolve_addressee(reply_target="user:7",
                                    semantic_candidates=("Маша",))
    assert resolved.status is mc.AddresseeStatus.RESOLVED
    assert resolved.addressee == "user:7"
    assert resolved.basis is mc.AddresseeBasis.REPLY_TARGET


def test_thread_target_is_second_priority():
    """§8.2: без reply — target существующей reply-цепи, и только потом alias."""
    resolved = ma.resolve_addressee(thread_target="user:9",
                                    chat_candidates=("Маша",))
    assert resolved.status is mc.AddresseeStatus.RESOLVED
    assert resolved.basis is mc.AddresseeBasis.THREAD_TARGET
    assert resolved.addressee == "user:9"


def test_unresolved_addressee_is_ambiguous_without_invented_recipient():
    """MEM-05.2: несколько кандидатов → `ambiguous`, получатель не выдуман."""
    resolved = ma.resolve_addressee(chat_candidates=("Аня", "Борис"))
    assert resolved.status is mc.AddresseeStatus.AMBIGUOUS
    assert resolved.addressee is None
    assert resolved.candidates == ("Аня", "Борис")
    with pytest.raises(ValueError):
        mc.AddresseeResolution(status=mc.AddresseeStatus.AMBIGUOUS,
                               addressee="Аня", candidates=("Аня", "Борис"))
    # «Резолв» с двумя кандидатами — запрещённое состояние (MEM-05.2).
    with pytest.raises(ValueError):
        mc.AddresseeResolution(
            status=mc.AddresseeStatus.RESOLVED, addressee="Аня",
            basis=mc.AddresseeBasis.CHAT_IDENTITY,
            candidates=("Аня", "Борис"))
    with pytest.raises(ValueError):
        mc.StatementAttribution(
            chat_id=CHAT, speaker="Маша", addressee="Аня",
            addressee_status=mc.AddresseeStatus.RESOLVED,
            addressee_basis=mc.AddresseeBasis.CHAT_IDENTITY,
            addressee_candidates=("Аня", "Борис"))


def test_factories_never_resolve_with_several_candidates():
    """Фабрики не могут выдать `resolved` при нескольких кандидатах (§8.2)."""
    cases = (
        {"chat_candidates": ("Аня", "Борис")},
        {"semantic_candidates": ("Аня", "Борис")},
        {"reply_target": "user:7", "chat_candidates": ("Аня", "Борис")},
        {"thread_target": "user:9", "semantic_candidates": ("Аня", "Петя")},
        {"chat_candidates": ("Аня", "Аня")},          # один человек — не двое
    )
    for kwargs in cases:
        resolution = ma.resolve_addressee(**kwargs)
        if resolution.status is mc.AddresseeStatus.RESOLVED:
            assert len(resolution.candidates) <= 1, kwargs
    statement = ma.attribute_statement(
        chat_id=CHAT, speaker="Маша",
        chat_candidates=("Аня", "Борис"))
    assert statement.addressee_status is mc.AddresseeStatus.AMBIGUOUS
    assert statement.addressee is None


def test_no_signal_keeps_addressee_unknown():
    """§8.2: в бессвязном чате новый адресат не появляется."""
    resolved = ma.resolve_addressee()
    assert resolved.status is mc.AddresseeStatus.UNKNOWN
    assert resolved.addressee is None
    assert resolved.basis is mc.AddresseeBasis.NONE
    with pytest.raises(ValueError):
        mc.AddresseeResolution(status=mc.AddresseeStatus.UNKNOWN,
                               addressee="Аня")
    with pytest.raises(ValueError):
        mc.AddresseeResolution(status=mc.AddresseeStatus.RESOLVED,
                               addressee="Аня")          # без сигнала


@pytest.mark.asyncio
async def test_reply_chain_addressee_from_saved_messages(tmp_path, monkeypatch):
    """Реальная цепочка: ответ на сообщение Пети → адресат Петя (по автору цели).

    `reply_to_author_id` в БД пуст (импорт/старый путь) — автор цели reply
    дочитывается из сохранённого сообщения, а не угадывается."""
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "reply.db")
    try:
        await _msg(d, user_id=7, author_name="Петя", text="я против", tg=100)
        await _msg(d, user_id=5, author_name="Маша", text="согласен",
                   tg=101, reply_to=100)
        attribution = await ma.message_attribution(d, CHAT, 101)
        assert attribution is not None
        assert attribution.speaker == "Маша"
        assert attribution.addressee_status is mc.AddresseeStatus.RESOLVED
        assert attribution.addressee == "user:7"
        assert attribution.addressee_basis is mc.AddresseeBasis.REPLY_TARGET
        addressee = await ma.addressee_for_message(d, chat_id=CHAT,
                                                  tg_message_id=101)
        assert addressee.addressee == "user:7"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_two_mentioned_participants_stay_ambiguous(tmp_path, monkeypatch):
    """MEM-05.2: два упомянутых участника без reply → `ambiguous`, без выбора.

    Кандидаты — различимые личности (`user:<uid>`), а не имена: имя не
    идентифицирует человека (одноимённые существуют), поэтому слой атрибуции
    не смешивает имена и uid в одном списке."""
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "ambig.db")
    try:
        await _msg(d, user_id=7, author_name="Аня", text="привет", tg=200)
        await _msg(d, user_id=9, author_name="Борис", text="привет", tg=201)
        await _msg(d, user_id=5, author_name="Маша",
                   text="Аня и Борис, вы где?", tg=202)
        addressee = await ma.addressee_for_message(d, chat_id=CHAT,
                                                  tg_message_id=202)
        assert addressee.status is mc.AddresseeStatus.AMBIGUOUS
        assert addressee.addressee is None
        assert set(addressee.candidates) == {"user:7", "user:9"}
        assert all(c.startswith("user:") for c in addressee.candidates)
        # своё имя адресатом не считается
        assert "user:5" not in addressee.candidates
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_same_name_duo_is_not_a_resolved_addressee(tmp_path, monkeypatch):
    """MEM-05.2: два человека с одним именем — «адресат» не выбирается.

    Ростер ревьюера: 7:"Аня", 8:"Аня", 5:"Петя", 9:"Борис"; Петя пишет
    «Аня, посмотри видео». Дедупликация по имени выдала бы одного адресата,
    поэтому кандидаты различаются личностями (`user:7`/`user:8`) и сигнал
    остаётся `ambiguous` без получателя. Одиночное имя по-прежнему резолвится,
    а точный reply target остаётся выше этого пути."""
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "same_name.db")
    try:
        await _msg(d, user_id=7, author_name="Аня", text="привет", tg=1000)
        await _msg(d, user_id=8, author_name="Аня", text="привет", tg=1001)
        await _msg(d, user_id=9, author_name="Борис", text="привет", tg=1002)
        await _msg(d, user_id=5, author_name="Петя",
                   text="Аня, посмотри видео", tg=1003)
        duo = await ma.addressee_for_message(d, chat_id=CHAT, tg_message_id=1003)
        assert duo.status is mc.AddresseeStatus.AMBIGUOUS
        assert duo.addressee is None
        assert set(duo.candidates) == {"user:7", "user:8"}
        assert len(set(duo.candidates)) == 2

        # кандидаты видны и в плоской атрибуции утверждения
        attribution = await ma.message_attribution(d, CHAT, 1003)
        assert attribution is not None
        assert attribution.addressee_status is mc.AddresseeStatus.AMBIGUOUS
        assert attribution.addressee is None
        assert set(attribution.addressee_candidates) == {"user:7", "user:8"}

        # одиночное имя остаётся резолвом в личность
        await _msg(d, user_id=5, author_name="Петя", text="Борис, глянь",
                   tg=1004)
        single = await ma.addressee_for_message(d, chat_id=CHAT,
                                               tg_message_id=1004)
        assert single.status is mc.AddresseeStatus.RESOLVED
        assert single.addressee == "user:9"
        assert single.basis is mc.AddresseeBasis.CHAT_IDENTITY

        # точный reply target по-прежнему главнее chat-scope
        await _msg(d, user_id=5, author_name="Петя",
                   text="Аня, посмотри видео", tg=1005, reply_to=1001,
                   reply_author=8)
        reply = await ma.addressee_for_message(d, chat_id=CHAT,
                                              tg_message_id=1005)
        assert reply.status is mc.AddresseeStatus.RESOLVED
        assert reply.addressee == "user:8"
        assert reply.basis is mc.AddresseeBasis.REPLY_TARGET
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_same_name_outside_roster_window_stays_ambiguous(tmp_path,
                                                              monkeypatch):
    """Корень: C-1 — единственный авторитет идентичности в этом слое.

    Ростер (24 ч) видит только uid 7, поэтому собственные догадки слоя
    объявили бы «Аня» одним адресатом. Но C-1 по сохранённым сообщениям видит
    двоих (uid 7 и uid 8, написавший 30 ч назад) и отказывается их сливать —
    значит адресат `ambiguous` с двумя различными личностями, и на карточке,
    и на пути записи (`message_attribution`).
    """
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "same_name_window.db")
    try:
        await _msg(d, user_id=8, author_name="Аня", text="давно", tg=1100,
                   ts=NOW - 30 * 3600)          # вне окна ростера (24 ч)
        await _msg(d, user_id=7, author_name="Аня", text="сейчас", tg=1101)
        await _msg(d, user_id=5, author_name="Петя",
                   text="Аня, посмотри видео", tg=1102)

        roster = await ma.chat_identity_candidates(
            d, chat_id=CHAT, text="Аня, посмотри видео", exclude_user_id=5)
        c1_uids = await provenance.lookup_identity_user_ids(
            d, CHAT, ("Аня",))
        # C-1 видит двоих, и кандидаты совпадают ровно с его вердиктом
        assert c1_uids == {7, 8}
        assert set(roster) == {f"user:{uid}" for uid in c1_uids}
        ref = await provenance.resolve_subject_ref(d, CHAT, "Аня")
        assert ref.resolution == "unresolved"        # C-1 не сливает

        card = await ma.addressee_for_message(d, chat_id=CHAT,
                                             tg_message_id=1102)
        assert card.status is mc.AddresseeStatus.AMBIGUOUS
        assert card.addressee is None
        assert set(card.candidates) == {"user:7", "user:8"}
        assert all(c.startswith("user:") for c in card.candidates)

        attribution = await ma.message_attribution(d, CHAT, 1102)
        assert attribution is not None
        assert attribution.addressee_status is mc.AddresseeStatus.AMBIGUOUS
        assert attribution.addressee is None
        assert set(attribution.addressee_candidates) == {"user:7", "user:8"}
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_addressee_identity_agrees_with_c1(tmp_path, monkeypatch):
    """Один авторитет: вывод адресата = вердикт C-1 по тому же имени.

    `resolved` ⟺ ровно один uid у C-1; `unresolved` у C-1 (0 или ≥2 uid) →
    никогда `resolved` с именем вместо личности.
    """
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "c1_agreement.db")
    try:
        await _msg(d, user_id=9, author_name="Борис", text="привет", tg=1200)
        await _msg(d, user_id=5, author_name="Петя", text="Борис, глянь",
                   tg=1201)
        await _msg(d, user_id=5, author_name="Петя", text="Никто, глянь",
                   tg=1202)
        for name in ("Борис", "Никто"):
            roster = await ma.chat_identity_candidates(
                d, chat_id=CHAT, text=f"{name}, глянь", exclude_user_id=5)
            uids = await provenance.lookup_identity_user_ids(d, CHAT, (name,))
            ref = await provenance.resolve_subject_ref(d, CHAT, name)
            assert (ref.resolution == "resolved") == (len(uids) == 1), name
            assert set(roster) == {f"user:{uid}" for uid in uids}, name
        # имя, которого нет в сохранённых сообщениях, адресатом не становится
        unknown = await ma.addressee_for_message(d, chat_id=CHAT,
                                                tg_message_id=1202)
        assert unknown.addressee is None
        assert unknown.status is not mc.AddresseeStatus.RESOLVED
        # а подтверждённое единственное имя — резолвится
        single = await ma.addressee_for_message(d, chat_id=CHAT,
                                               tg_message_id=1201)
        assert single.status is mc.AddresseeStatus.RESOLVED
        assert single.addressee == "user:9"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_single_mention_resolves_via_chat_identity(tmp_path, monkeypatch):
    """§8.2: один упомянутый участник → адресат по достоверному alias/uid."""
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "ident.db")
    try:
        await _msg(d, user_id=7, author_name="Аня", text="привет", tg=300)
        await _msg(d, user_id=5, author_name="Маша",
                   text="Аня, ты придёшь?", tg=301)
        addressee = await ma.addressee_for_message(d, chat_id=CHAT,
                                                  tg_message_id=301)
        assert addressee.status is mc.AddresseeStatus.RESOLVED
        assert addressee.basis is mc.AddresseeBasis.CHAT_IDENTITY
        assert addressee.addressee == "user:7"
    finally:
        await d.close()


# ── MEM-05.2/R-9: пересылка и цитата ───────────────────────────────────────

def test_forward_content_belongs_to_original_author():
    """R-9: содержание пересылки — первоисточнику, не переславшему."""
    statement = ma.attribute_statement(
        chat_id=CHAT, speaker="Петя", speaker_user_id=5, subject="Маша",
        is_forward=True, forward_source="Канал X", forward_author=777)
    assert statement.speaker == "Петя"                 # отправитель
    assert statement.content_author == "user:777"      # чьи это слова
    assert statement.attributed_author == "user:777"
    assert statement.attributed_author != statement.speaker
    assert statement.modality is mc.AssertionMode.QUOTED


def test_forward_without_author_is_unknown_not_forwarder():
    """Пересылка без известного первоисточника: автор `unknown`, не переславший."""
    statement = ma.attribute_statement(
        chat_id=CHAT, speaker="Петя", speaker_user_id=5, is_forward=True)
    assert statement.content_author is None
    assert statement.attributed_author is None
    assert statement.attributed_author != "Петя"


def test_quote_keeps_both_speaker_and_quoted_author():
    """§8.2: цитата внутри сообщения не склеивает говорящего и автора цитаты."""
    statement = ma.attribute_statement(
        chat_id=CHAT, speaker="Петя", speaker_user_id=5, quoted_author=777,
        quoted=True)
    assert statement.speaker == "Петя"
    assert statement.quoted_author == "user:777"
    assert statement.quoted_author != statement.speaker
    assert statement.modality is mc.AssertionMode.QUOTED


@pytest.mark.asyncio
async def test_forward_row_and_edge_card_use_original_author(tmp_path,
                                                             monkeypatch):
    """Строка `smart_messages` и карточка ребра: автор — первоисточник.

    Переславший остаётся отдельным слотом `sender`, поэтому «кто принёс» и
    «чьи слова» различимы (R-9), а не склеены в одно поле."""
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "fwd.db")
    try:
        await _msg(d, user_id=5, author_name="Петя", text="Маша любит кофе",
                   tg=400, is_forward=True, forward_source="Канал X",
                   forward_author=777)
        attribution = await ma.message_attribution(d, CHAT, 400)
        assert attribution.speaker == "Петя"
        assert attribution.content_author == "user:777"
        assert attribution.attributed_author == "user:777"

        from services import relation_evidence
        edge_id = await _seed_edge(d)
        await _attach_message_source(d, edge_id, 400)
        evidence = await relation_evidence.edge_evidence(
            d, chat_id=CHAT, edge_id=edge_id)
        source = evidence["sources"][0]
        assert source["speaker"] == "user:777"          # чьи слова
        assert source["sender"] == "Петя"               # кто принёс
    finally:
        await d.close()


async def _seed_edge(d):
    """Узлы + ребро чата (без оснований) — общая заготовка карточки."""
    sid = await d.upsert_node(CHAT, "Петя", "fact", origin="chat_history")
    oid = await d.upsert_node(CHAT, "Маша", "fact", origin="chat_history")
    await d.upsert_edge(sid, oid, "знает", origin="chat_history")
    cursor = await d.db.execute(
        "SELECT id FROM edges WHERE chat_id = ? AND source_id = ? "
        "AND target_id = ?", (CHAT, sid, oid))
    return int((await cursor.fetchone())["id"])


async def _attach_message_source(d, edge_id: int, tg: int) -> None:
    """Привязать сохранённое сообщение как проверенное основание ребра."""
    from services import relation_evidence
    cursor = await d.db.execute(
        "SELECT id FROM smart_messages WHERE chat_id = ? AND tg_message_id = ?",
        (CHAT, tg))
    row_id = int((await cursor.fetchone())["id"])
    ref = await provenance.resolve_source_ref(
        d, provenance.message_source_ref(chat_id=CHAT, entity_id=str(row_id),
                                         tg_message_id=tg))
    await relation_evidence.attach_edge_evidence(
        d, chat_id=CHAT, edge_id=edge_id, source_ref_id=ref,
        link_type="supports", method="direct_reference",
        verification="verified", independence="independent",
        basis="direct reference", established_at=1000)


@pytest.mark.asyncio
async def test_edge_card_surfaces_ambiguous_addressee(tmp_path, monkeypatch):
    """§8.2: неоднозначный адресат виден В КАРТОЧКЕ и не заменяется выбором."""
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "card_ambig.db")
    try:
        await _msg(d, user_id=7, author_name="Аня", text="привет", tg=250)
        await _msg(d, user_id=9, author_name="Борис", text="привет", tg=251)
        await _msg(d, user_id=5, author_name="Маша",
                   text="Аня и Борис, вы где?", tg=252)
        edge_id = await _seed_edge(d)
        await _attach_message_source(d, edge_id, 252)
        from services import relation_evidence
        evidence = await relation_evidence.edge_evidence(
            d, chat_id=CHAT, edge_id=edge_id)
        source = evidence["sources"][0]
        assert source["addressee_status"] == "ambiguous"
        assert source["addressee"] is None
        assert set(source["addressee_candidates"]) == {"user:7", "user:9"}
        assert all(c.startswith("user:")
                   for c in source["addressee_candidates"])
    finally:
        await d.close()


# ── MEM-05.4: собственные сообщения бота ───────────────────────────────────

def test_bot_self_statement_never_corroborates():
    """§8.4/R-3: «что я обещал» помним, внешний факт этим не подтверждается."""
    statement = ma.attribute_statement(
        chat_id=CHAT, speaker="Бот", speaker_kind=mc.SpeakerKind.BOT,
        origin="bot_direct_reply")
    assert statement.speaker_kind is mc.SpeakerKind.BOT
    assert statement.corroborates is False
    assert ma.independence_for(statement) == "self_referential"
    assert statement.attributed_author == "Бот"       # его собственные слова
    with pytest.raises(ValueError):
        mc.StatementAttribution(chat_id=CHAT,
                                speaker_kind=mc.SpeakerKind.BOT,
                                corroborates=True)


# ── §3.3.1/MEM-05.3: модальность и тон только из сигналов ──────────────────

def test_unknown_modality_never_becomes_asserted():
    """§3.3.1: без сигнала модальность `unknown` (не `asserted`)."""
    statement = ma.attribute_statement(chat_id=CHAT, speaker="Петя")
    assert statement.modality is mc.AssertionMode.UNKNOWN


def test_modality_comes_from_real_signals_only():
    """§3.3.1: модальность выводят реальные поля, а не текст/пунктуация."""
    assert ma.attribute_statement(
        chat_id=CHAT, speaker="Петя", denied=True
    ).modality is mc.AssertionMode.DENIED
    assert ma.attribute_statement(
        chat_id=CHAT, speaker="Петя", perspective="third_party"
    ).modality is mc.AssertionMode.REPORTED
    assert ma.attribute_statement(
        chat_id=CHAT, speaker="Петя", hypothetical=True
    ).modality is mc.AssertionMode.HYPOTHETICAL
    assert ma.attribute_statement(
        chat_id=CHAT, speaker="Петя", joking=True
    ).modality is mc.AssertionMode.JOKING


def test_attribution_takes_no_text_itself():
    """MEM-05.3/INV-13: у атрибуции нет текстового параметра — тон не может
    выводиться из «грубого слова» или словаря стоп-слов."""
    params = set(inspect.signature(ma.attribute_statement).parameters)
    assert not params & {"text", "message_text", "content", "keywords",
                         "tone", "tone_words", "markers"}


# ── MEM-05.1: слои — представления существующих хранилищ ───────────────────

@pytest.mark.asyncio
async def test_layers_point_to_existing_tables(tmp_path):
    """MEM-05.1: каждый слой — существующая таблица, второго стора нет."""
    d = await _fresh(tmp_path, "layers.db")
    try:
        layers = ma.layer_sources()
        assert set(layers) == {"operational_context", "episodes",
                               "stable_knowledge", "social_context",
                               "bot_self_history", "experience"}
        for layer, tables in layers.items():
            assert tables, layer
            for table in tables:
                cursor = await d.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND "
                    "name = ?", (table,))
                assert await cursor.fetchone() is not None, (layer, table)
    finally:
        await d.close()


def test_attribution_layer_is_read_only():
    """MEM-05.1: слой атрибуции ничего не пишет (нет INSERT/UPDATE/DDL)."""
    source = (SERVICES_DIR / "memory_attribution.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    sql_write = ("INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "DROP TABLE",
                 "ALTER TABLE")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = node.value.upper()
            for marker in sql_write:
                assert marker not in upper, (marker, node.value[:60])


# ── MEM-05.5/05.6: медиа ───────────────────────────────────────────────────

def test_media_not_processed_is_not_understanding():
    """§8.5: `not_processed`/`unavailable` не читаются как понимание."""
    media = mc.MediaMemoryAttribution(
        chat_id=CHAT, media_asset_id="asset-1",
        vision_status=mc.MediaVisionStatus.NOT_PROCESSED,
        timestamp=1_700_000_000, tg_message_id=500, access_scope="chat")
    assert media.understood is False
    assert media.as_evidence() is None
    with pytest.raises(ValueError):
        mc.MediaMemoryAttribution(
            chat_id=CHAT, media_asset_id="asset-1",
            vision_status=mc.MediaVisionStatus.UNAVAILABLE,
            description="на фото кот")                 # понимание без анализа

    processed = mc.MediaMemoryAttribution(
        chat_id=CHAT, media_asset_id="asset-1",
        vision_status=mc.MediaVisionStatus.PROCESSED, description="на фото кот",
        timestamp=1_700_000_000, tg_message_id=500, access_scope="chat",
        reason_code="analysis_ready")
    assert processed.understood is True
    assert processed.as_evidence()["description"] == "на фото кот"


def test_analysis_status_mapping_is_honest():
    """`ready`/`no_text` — выполненный анализ; отсутствие строки — нет."""
    assert ma.media_vision_status("ready")[0] is mc.MediaVisionStatus.PROCESSED
    assert ma.media_vision_status("no_text")[0] is \
        mc.MediaVisionStatus.PROCESSED
    assert ma.media_vision_status("failed")[0] is \
        mc.MediaVisionStatus.UNAVAILABLE
    assert ma.media_vision_status(None)[0] is \
        mc.MediaVisionStatus.NOT_PROCESSED
    assert ma.media_vision_status("")[1] == "analysis_missing"


@pytest.mark.asyncio
async def test_media_memory_does_not_rerun_vision(tmp_path, monkeypatch):
    """MEM-05.5: чтение памяти медиа не запускает тяжёлый vision (0 вызовов)."""
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "media.db")
    calls = {"provider": 0}

    def _boom(*args, **kwargs):
        calls["provider"] += 1
        raise AssertionError("vision must not run on a memory read")

    monkeypatch.setattr(mca_vision, "analyze_image_bytes", _boom)
    monkeypatch.setattr(mca_vision, "analyze_adaptive", _boom)
    # MEM-05.6: чтение памяти не дублирует ingest/action медиа.
    import services.media_readiness as media_readiness
    monkeypatch.setattr(media_readiness, "ensure_asset_analysis", _boom)
    monkeypatch.setattr(media_readiness, "prepare_images_ready", _boom)
    try:
        await _msg(d, user_id=7, author_name="Аня", text="", tg=600,
                   media_type="photo")
        await d.upsert_media_asset({
            "asset_id": "asset-600", "chat_id": CHAT, "tg_message_id": 600,
            "asset_kind": "photo", "size_variant": "default"})
        scope = mca_vision.access_scope_for(CHAT)
        await d.db.execute(
            "INSERT INTO mca_media_analyses (asset_id, access_scope, "
            "analysis_schema_version, quality_profile, status, revision, "
            "visual_description, ocr_blocks, uncertainty, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("asset-600", scope, mca_vision.ANALYSIS_SCHEMA_VERSION,
             mca_vision.QUALITY_PROFILE_DEFAULT, "ready", 1,
             "на фото кот", "[]", "[]", 1_700_000_000, 1_700_000_000))
        await d.db.commit()
        media = await mca_vision.memory_media_attributions(
            d, chat_id=CHAT, tg_message_id=600,
            timestamp=1_700_000_000, media_type="photo")
        assert len(media) == 1
        assert media[0].vision_status is mc.MediaVisionStatus.PROCESSED
        assert "кот" in str(media[0].description)
        assert media[0].media_asset_id == "asset-600"
        assert media[0].tg_message_id == 600
        assert media[0].timestamp == 1_700_000_000
        assert calls["provider"] == 0

        # второй актив без строки анализа — честно `not_processed`
        await d.upsert_media_asset({
            "asset_id": "asset-601", "chat_id": CHAT, "tg_message_id": 600,
            "asset_kind": "photo", "size_variant": "large"})
        media = await mca_vision.memory_media_attributions(
            d, chat_id=CHAT, tg_message_id=600)
        by_id = {item.media_asset_id: item for item in media}
        assert by_id["asset-601"].understood is False
        assert by_id["asset-601"].reason_code == "analysis_missing"
        assert by_id["asset-601"].transcription_status is \
            mc.MediaVisionStatus.NOT_PROCESSED
        assert calls["provider"] == 0
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_media_memory_off_gate_returns_nothing(tmp_path):
    """§5.2: гейт OFF → прежнее поведение (пустой список), не полу-статус."""
    d = await _fresh(tmp_path, "media_off.db")
    try:
        await _msg(d, user_id=7, author_name="Аня", text="", tg=700,
                   media_type="photo")
        await d.upsert_media_asset({
            "asset_id": "asset-700", "chat_id": CHAT, "tg_message_id": 700,
            "asset_kind": "photo", "size_variant": "default"})
        media = await mca_vision.memory_media_attributions(
            d, chat_id=CHAT, tg_message_id=700)
        assert media == []
    finally:
        await d.close()


# ── MEM-05.7: опыт ─────────────────────────────────────────────────────────

def test_single_failure_is_not_a_stable_rule():
    """§8.6: одна неудача не создаёт постоянного правила поведения."""
    verdict = ma.experience_stability(
        lesson_type="failure_pattern", status="active",
        validation_kind="generalization", independent_outcomes=1)
    assert verdict.stability is mc.ExperienceStability.EXPERIMENTAL
    assert verdict.is_stable is False

    enough = ma.experience_stability(
        lesson_type="failure_pattern", status="active",
        validation_kind="generalization", independent_outcomes=3)
    assert enough.stability is mc.ExperienceStability.STABLE


def test_experience_verdict_rejects_unbacked_stable():
    """`STABLE` нельзя сконструировать без доказанной базы (§8.6)."""
    with pytest.raises(ValueError):
        mc.ExperienceVerdict(stability=mc.ExperienceStability.STABLE,
                             reason_code="manual", required_outcomes=0)
    with pytest.raises(ValueError):
        mc.ExperienceVerdict(stability=mc.ExperienceStability.STABLE,
                             reason_code="manual", required_outcomes=3,
                             independent_outcomes=1)
    ok = mc.ExperienceVerdict(stability=mc.ExperienceStability.STABLE,
                              reason_code="explicit_instruction",
                              basis="explicit_instruction",
                              required_outcomes=3)
    assert ok.is_stable is True


@pytest.mark.asyncio
async def test_candidate_lesson_is_experimental_in_real_pipeline(tmp_path):
    """Реальный `LessonService`: один исход не делает урок правилом."""
    from services import mca_experience

    d = await _fresh(tmp_path, "exp.db")
    try:
        service = mca_experience.get_service(d)
        created = await service.lesson.propose(
            type="failure_pattern", scope="chat", rule_key="reproduce_before_fix",
            applicability="", scope_chat_id=CHAT,
            episode_ids=("ep-1",))
        assert created is not None
        lesson_id, version = created
        verdict = await service.lesson.stability(lesson_id, version)
        assert verdict is not None
        assert verdict.stability is mc.ExperienceStability.EXPERIMENTAL

        evidence = mca_experience.ValidationEvidence(
            kind="generalization", independent_episode_ids=("ep-1",))
        assert await service.lesson.validate(lesson_id, version,
                                             evidence=evidence) is False
        verdict = await service.lesson.stability(lesson_id, version,
                                                 evidence=evidence)
        assert verdict.stability is mc.ExperienceStability.EXPERIMENTAL
        assert verdict.reason_code == "status_candidate"
    finally:
        await d.close()


# ── MEM-05.2/05.4 на записи: кто РЕАЛЬНО сказал ────────────────────────────

@pytest.mark.asyncio
async def test_fact_provenance_uses_message_author_not_subject(tmp_path,
                                                               monkeypatch):
    """§2.2.1(д): пересказ чужого мнения не выдаётся за `self_report`.

    Гейт ON: говорящий — автор сохранённого сообщения; OFF — прежний расчёт
    (паритет baseline), поэтому старые тесты не меняются."""
    monkeypatch.setenv("MCA_PROVENANCE_ENABLED", "on")
    d = await _fresh(tmp_path, "write.db")
    try:
        await _msg(d, user_id=5, author_name="Петя", text="Маша любит кофе",
                   tg=800)
        memory = summary_memory.MemoryManager(d, _NullLLM())
        fact_id = await d.insert_graph_fact(
            CHAT, "Маша любит кофе", "chat_history", None,
            target_user="Маша", subject="Маша", object="кофе",
            tg_message_id=800)

        # OFF (гейт C-8 по умолчанию): паритет baseline
        await memory._attach_fact_provenance(
            CHAT, fact_id, "chat_history", "Маша", "Маша", 800, {})
        cursor = await d.db.execute(
            "SELECT attribution_method, speaker_author_id FROM graph_facts "
            "WHERE id = ?", (fact_id,))
        baseline = dict(await cursor.fetchone())
        assert baseline["attribution_method"] == "self_report"
        assert baseline["speaker_author_id"] is None

        # ON: автор сообщения (Петя), а не субъект факта (Маша)
        _enable_attribution(monkeypatch)
        await d.db.execute(
            "UPDATE graph_facts SET attribution_method = NULL WHERE id = ?",
            (fact_id,))
        await d.db.commit()
        await memory._attach_fact_provenance(
            CHAT, fact_id, "chat_history", "Маша", "Маша", 800, {})
        cursor = await d.db.execute(
            "SELECT attribution_method, speaker_author_id FROM graph_facts "
            "WHERE id = ?", (fact_id,))
        gated = dict(await cursor.fetchone())
        assert gated["attribution_method"] == "third_party"
        assert gated["speaker_author_id"] == 5
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_forward_fact_provenance_credits_original_author(tmp_path,
                                                              monkeypatch):
    """R-9: при пересылке говорящим записан первоисточник, не переславший."""
    monkeypatch.setenv("MCA_PROVENANCE_ENABLED", "on")
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "write_fwd.db")
    try:
        await _msg(d, user_id=5, author_name="Петя", text="Маша любит кофе",
                   tg=900, is_forward=True, forward_source="Канал X",
                   forward_author=777)
        memory = summary_memory.MemoryManager(d, _NullLLM())
        fact_id = await d.insert_graph_fact(
            CHAT, "Маша любит кофе", "chat_history", None,
            target_user="Маша", subject="Маша", object="кофе",
            tg_message_id=900)
        await memory._attach_fact_provenance(
            CHAT, fact_id, "chat_history", "Маша", "Маша", 900, {})
        cursor = await d.db.execute(
            "SELECT attribution_method, speaker_author_id FROM graph_facts "
            "WHERE id = ?", (fact_id,))
        row = dict(await cursor.fetchone())
        assert row["speaker_author_id"] == 777          # первоисточник
        assert row["speaker_author_id"] != 5            # не переславший
        assert row["attribution_method"] == "third_party"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_bot_origin_fact_records_bot_self_reply(tmp_path, monkeypatch):
    """§8.4/R-3: origin бота фиксируется как `bot_self_reply` ДО субъект-атрибуции.

    Субъект-атрибуция не может записать за ботом `self_report`/`third_party`
    даже если вызывающий однажды расширит whitelist источников; поэтому
    `attribution_method` для bot-origin не зависит ни от автора сообщения,
    ни от заявленного извлечением метода."""
    monkeypatch.setenv("MCA_PROVENANCE_ENABLED", "on")
    _enable_attribution(monkeypatch)
    d = await _fresh(tmp_path, "write_bot.db")
    try:
        await _msg(d, user_id=5, author_name="Петя", text="Маша любит кофе",
                   tg=950)
        memory = summary_memory.MemoryManager(d, _NullLLM())
        for index, declared in enumerate((None, "self_report", "third_party")):
            fact_id = await d.insert_graph_fact(
                CHAT, f"Маша любит кофе вариант {index}", "bot_direct_reply",
                None, target_user="Маша", subject="Маша", object="кофе",
                tg_message_id=950)
            await memory._attach_fact_provenance(
                CHAT, fact_id, "bot_self_reply", "Маша", "Маша", 950, {},
                declared_method=declared)
            cursor = await d.db.execute(
                "SELECT attribution_method FROM graph_facts WHERE id = ?",
                (fact_id,))
            row = dict(await cursor.fetchone())
            assert row["attribution_method"] == "bot_self_reply", declared
        # origin вне BOT_ORIGINS не затронут: обычная субъект-атрибуция работает
        fact_id = await d.insert_graph_fact(
            CHAT, "Маша любит кофе вариант human", "chat_history", None,
            target_user="Маша", subject="Маша", object="кофе",
            tg_message_id=950)
        await memory._attach_fact_provenance(
            CHAT, fact_id, "chat_history", "Маша", "Маша", 950, {})
        cursor = await d.db.execute(
            "SELECT attribution_method FROM graph_facts WHERE id = ?",
            (fact_id,))
        assert dict(await cursor.fetchone())["attribution_method"] == \
            "third_party"
    finally:
        await d.close()
