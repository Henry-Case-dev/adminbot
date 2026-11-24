"""UNIFIED-REPLY UR-C — ContextSelection, единый allocator, память, конспект.

Покрывает обязательные строки карты UR-C:
  * UR-09.3/UR-10.1 — полный текущий текст (>800 символов) доступен модели,
    середина и конец не теряются; overflow — дробление со ссылкой, не `[:800]`;
  * UR-09.4/UR-09.5 — reply-ветка >3 ходов, авторы различаются, собственный
    ответ бота — обычный факт диалога;
  * UR-09.6/UR-13.2/13.3 — запрос памяти из темы+адресата+reply-parent,
    исходные сообщения с идентификаторами через существующий retrieval;
  * UR-09.8/UR-11.5 — allocator снимает нерелевантное раньше релевантного,
    «всё влезает — не режем», сжатие только со ссылкой на оригинал;
  * UR-13.5 — поздняя правка пользователя приоритетнее, конфликт помечен;
  * UR-13.7 — при отсутствии памяти «не помню», без выдуманного recall;
  * UR-12 — условие конспекта по watermark/вытеснению, а не по числу строк;
  * UR-11.2/11.3 — Dynamic по умолчанию и model-aware стадии инициативы;
  * UR-C-2a (A2 core) — offline producers/materializer: роли branch/thread,
    memory tiers 2/3/4, correction P0, parity с существующими рендерерами.
"""
import inspect
from types import SimpleNamespace

import pytest

from services import auto_budget as ab
from services import direct_chat_service as dcs
from services import direct_context_composer as comp
from services import direct_l1 as l1
from services import mca_retrieval_context as rc
from services import summary_memory as sm
from services import thread_chain as tchain
from services.database import DatabaseService
from services.summary_xml import escape_xml_text
from services.token_counter import count_tokens

CHAT = -100777
BOT_UID = 999000


async def _db(tmp_path, name="urc.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add_msg(db, chat_id, user_id, text, ts, tg, reply_to=None,
                   author_name=""):
    return await db.save_smart_message(
        user_id=user_id, chat_id=chat_id, text=text, reply_to_id=reply_to,
        timestamp=ts, media_type="text", author_name=author_name,
        message_id=tg)


def _frag(kind, source_id, text, *, role, ts=100, uid=1, authority=None,
          reply_to=None, superseded_by=None, tg=None):
    return comp.ContextFragment(
        kind=kind, source_id=source_id, timestamp_utc=ts, speaker_uid=uid,
        author_label=f"u{uid}", text=text, reply_to=reply_to,
        authority=authority or comp.authority_for_kind(kind), role=role,
        tg_message_id=tg, superseded_by=superseded_by, time_known=bool(ts))


def _long_question() -> tuple:
    head = "Начало: " + ("предисловие " * 40)
    middle = "СЕРЕДИНА_ВАЖНАЯ: бюджет 348 тысяч рублей"
    tail = "и КОНЕЦ_ВАЖНЫЙ: подтверди конкретной суммой"
    text = head + middle + (" подробности " * 60) + tail
    return text, middle, tail


# ═══ UR-09.3 / UR-10.1: полный текущий текст и явный overflow ═══════════════

class TestCurrentQuestionFullText:
    def test_long_question_keeps_middle_and_end(self):
        text, middle, tail = _long_question()
        assert len(text) > 800
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text=text, reply_to_tg=500,
            timestamp_utc=1000, budget_tokens=10 ** 6)
        got = selection.current_question.text
        assert got == text
        assert middle in got and tail in got
        # UI-выдержка отделена от входа модели (UR-10.1).
        preview = comp.preview_text(text, 800)
        assert len(preview) <= 801 and preview != text

    def test_overflow_splits_with_source_instead_of_tail_loss(self):
        text, middle, tail = _long_question()
        question = comp.ContextFragment(
            kind=comp.KIND_USER_STATEMENT, source_id="msg:500",
            timestamp_utc=1000, speaker_uid=1, author_label="Вася",
            text=text, role=comp.ROLE_CURRENT_QUESTION, tg_message_id=500,
            authority=comp.AUTHORITY_PRIMARY)
        parts = comp.split_overflow_fragments(question, 40)
        assert len(parts) > 3
        assert all(part.source_id == "msg:500" for part in parts)
        assert [part.part_index for part in parts] == list(
            range(1, len(parts) + 1))
        assert all(part.part_total == len(parts) for part in parts)
        # Ни одного потерянного слова: конкатенация частей = исходник.
        rebuilt = " ".join(p.text for p in parts)
        assert rebuilt.split() == text.split()
        assert " ".join(middle.split()) in " ".join(rebuilt.split())
        assert " ".join(tail.split()) in " ".join(rebuilt.split())

    def test_p0_overflow_is_explicit_and_keeps_full_text_available(self):
        text, _middle, _tail = _long_question()
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text=text, reply_to_tg=500,
            timestamp_utc=1000, budget_tokens=60)
        assert selection.provenance.overflow is True
        assert selection.provenance.overflow_parts
        assert selection.provenance.included_tokens <= 60
        # Текст вопроса не «переписан»: он разложен на части, хвост известен
        # потребителю через overflow_parts, а не выброшен молча.
        assert selection.current_question.part_total > 1
        # Ни одна часть не потеряна бесследно: вошедшие части + ссылки на
        # остальные покрывают ровно столько частей, сколько их всего.
        in_selection = 1 + len(selection.current_parts)
        referenced = len(selection.provenance.overflow_parts)
        assert in_selection + referenced == \
            selection.current_question.part_total
        for item in selection.provenance.overflow_parts:
            assert item["source_id"] == selection.current_question.source_id
            assert item["reason_code"] == "physical_overflow"
            assert item["part"]


# ═══ UR-09/UR-11.5: единственный allocator и порядок вытеснения ════════════

class TestAllocatorOrder:
    def _selection(self, budget):
        background = [
            _frag(comp.KIND_CHAT_EVENT, f"msg:{900 + i}",
                  "нерелевантный фон " * 20, role=comp.ROLE_BACKGROUND,
                  ts=100 + i)
            for i in range(3)
        ]
        memory = [
            _frag(comp.KIND_USER_STATEMENT, "msg:701",
                  "релевантная память о кредите", role=comp.ROLE_MEMORY,
                  ts=500),
        ]
        thread = [
            _frag(comp.KIND_USER_STATEMENT, "msg:601", "свежая реплика темы",
                  role=comp.ROLE_THREAD, ts=900),
        ]
        summary = comp.summary_map_ref(
            {"summary": "широкий фон: спорили о деньгах", "window_end_ts": 400,
             "raw_count": 12}, level=1, newest_ts=900)
        return comp.build_context_selection(
            chat_id=CHAT, current_text="сколько я платил по кредиту?",
            reply_to_tg=950, timestamp_utc=1000, thread=thread,
            memory=memory, background=background, summary_map=summary,
            budget_tokens=budget)

    def test_no_trim_when_everything_fits(self):
        selection = self._selection(10 ** 6)
        assert selection.provenance.dropped == ()
        assert not selection.provenance.overflow
        assert len(selection.background) == 3

    def test_drops_irrelevant_before_relevant(self):
        full = self._selection(10 ** 6)
        # Бюджет: вопрос + ветка + память, без фона и конспекта.
        budget = sum(
            frag.tokens() for frag in
            (full.current_question, *full.thread, *full.memory)) + 8
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text=full.current_question.text,
            reply_to_tg=950, timestamp_utc=1000, thread=full.thread,
            memory=full.memory, background=full.background,
            summary_map=full.summary_map, budget_tokens=budget)
        dropped_roles = {item.get("role") for item in
                         selection.provenance.dropped}
        assert comp.ROLE_BACKGROUND in dropped_roles
        assert selection.background == ()
        # Релевантная память и ветка уцелели.
        assert selection.memory and selection.thread
        kinds = {item["kind"] for item in selection.provenance.dropped}
        assert comp.KIND_SUMMARY_INFERENCE in kinds
        assert selection.provenance.included_tokens <= budget

    def test_compression_keeps_source_reference(self):
        big = _frag(comp.KIND_USER_STATEMENT, "msg:801", "очень длинный факт " * 400,
                    role=comp.ROLE_THREAD, ts=900)
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text="вопрос", reply_to_tg=960,
            timestamp_utc=1000, thread=[big], budget_tokens=80)
        texts = [f.text for f in selection.fragments()]
        joined = "\n".join(texts)
        assert "полный текст: msg:801" in joined
        assert all(item.get("reason_code") for item in
                   selection.provenance.dropped)

    def test_budget_is_actually_respected_after_compression(self):
        """UR-11: allocator — ЕДИНСТВЕННЫЙ владелец усечения.

        После сжатия он обязан реально влезть в бюджет, иначе потребитель
        резал бы повторно по своей политике. Каждый снятый фрагмент назван в
        `dropped` с причиной; никакой тихой потери.
        """
        neighbours = [
            _frag(comp.KIND_USER_STATEMENT, f"msg:{900 + i}",
                  "средняя реплика про бюджет поездки и расходы семьи",
                  role=comp.ROLE_FRESH_NEIGHBOUR, ts=1000 + i, uid=20 + i,
                  tg=900 + i)
            for i in range(12)
        ]
        budget = 80
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text="и что дальше?", timestamp_utc=2000,
            fresh_neighbours=neighbours, budget_tokens=budget)
        prov = selection.provenance
        assert prov.included_tokens <= budget
        assert sum(f.tokens() for f in selection.fragments()) <= budget
        dropped_ids = {item["source_id"] for item in prov.dropped
                       if item.get("reason_code") == "budget_exceeded"}
        kept_ids = {f.source_id for f in selection.fragments()}
        assert dropped_ids and kept_ids.isdisjoint(dropped_ids)
        assert {"msg:current"} <= kept_ids
        # Каждый фрагмент либо в payload, либо назван с причиной — 13 из 13.
        assert kept_ids | dropped_ids == (
            {"msg:current"} | {f"msg:{900 + i}" for i in range(12)})
        # Снимаются старые соседи; уцелевшие — самые свежие (непрерывный хвост).
        kept_numbers = sorted(int(sid.split(":")[1])
                              for sid in kept_ids - {"msg:current"})
        assert kept_numbers and kept_numbers == list(
            range(900 + (12 - len(kept_numbers)), 912))

    def test_provenance_counts_are_truthful(self):
        selection = self._selection(10 ** 6)
        prov = selection.provenance
        assert prov.raw_counts
        for kind, raw in prov.raw_counts.items():
            assert prov.selected_counts.get(kind, 0) <= raw
            assert prov.included_counts.get(kind, 0) <= \
                prov.selected_counts.get(kind, 0)
        assert sum(prov.included_counts.values()) == len(
            selection.fragments())
        assert prov.included_tokens == sum(f.tokens() for f in
                                           selection.fragments())
        assert prov.raw_tokens >= prov.included_tokens
        assert prov.as_dict()["policy_version"] == comp.SELECTION_POLICY_VERSION


# ═══ UR-09.4/09.5/23.3: reply-ветка, авторы, собственный ответ (реальная БД) ═

class TestReplyBranchAndSelfOutput:
    @pytest.mark.asyncio
    async def test_reply_branch_more_than_three_hops_keeps_authors(self, tmp_path):
        db = await _db(tmp_path, "branch.db")
        try:
            await _add_msg(db, CHAT, 11, "кто брал кредит?", 1000, 10,
                           author_name="Вася")
            await _add_msg(db, CHAT, 12, "я брал, на машину", 1010, 11,
                           reply_to=10, author_name="Петя")
            await _add_msg(db, CHAT, 13, "на какую сумму?", 1020, 12,
                           reply_to=11, author_name="Вася")
            await _add_msg(db, CHAT, 12, "на 348 тысяч", 1030, 13,
                           reply_to=12, author_name="Петя")
            await _add_msg(db, CHAT, 11, "а вернул уже?", 1040, 14,
                           reply_to=13, author_name="Вася")
            # Собственный ответ бота на старую реплику — в durable ledger.
            await db.record_bot_output(
                chat_id=CHAT, bot_user_id=BOT_UID, tg_message_id=15,
                revision_no=1, sent_at=1050, parent_message_ref="tg:14",
                output_kind="direct_reply",
                content_text="вернул половину, осталось 174 тысячи",
                correlation_id="turn-1")
            from services.thread_chain import collect_thread_chain
            chain = await collect_thread_chain(db, CHAT, 15, depth=10)
            assert len(chain) >= 5
            items = list(reversed(chain))          # корень → текущий ход
            authors = [item.name for item in items if not item.is_bot]
            assert {"Вася", "Петя"} <= set(authors)
            uids = {item.uid for item in items if not item.is_bot}
            assert {11, 12} <= uids
            bot_items = [item for item in items if item.is_bot]
            assert bot_items and bot_items[-1].ts == 1050
            assert bot_items[-1].reply_to_item_id == "tg:14"
            assert bot_items[-1].source_kind == "bot_output"
            # Фрагменты ветки: бот — обычный bot_statement, не style-anchor.
            fragments = [comp.chain_item_to_fragment(item,
                                                    role=comp.ROLE_THREAD)
                         for item in items]
            bot_frag = [f for f in fragments
                        if f.kind == comp.KIND_BOT_STATEMENT][-1]
            assert bot_frag.authority == comp.AUTHORITY_SUPPORTING
            assert bot_frag.timestamp_utc == 1050
            assert bot_frag.tg_message_id == 15
            assert bot_frag.reply_to_tg_id == 14
            assert bot_frag.correlation_id == "turn-1"
            speaker_uids = {f.speaker_uid for f in fragments
                            if f.kind == comp.KIND_USER_STATEMENT}
            assert {11, 12} <= speaker_uids
            # UR-23: автор бот-хода известен (реальный uid бота), а не
            # «неизвестно»: `ChainItem` для бота uid не несёт.
            bot_with_author = comp.chain_item_to_fragment(
                bot_items[-1], role=comp.ROLE_THREAD, bot_user_id=BOT_UID)
            assert bot_with_author.speaker_uid == BOT_UID
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_bot_turn_author_survives_dedup_with_ledger(self, tmp_path):
        """UR-23: `speaker_uid` бот-хода задаётся из `bot_user_id`, а дедуп
        возвращает его выжившему фрагменту (ветка без uid + ledger-дубль)."""
        db = await _db(tmp_path, "botuid.db")
        try:
            await _add_msg(db, CHAT, 11, "кто брал кредит?", 1000, 10,
                           author_name="Вася")
            await db.record_bot_output(
                chat_id=CHAT, bot_user_id=BOT_UID, tg_message_id=15,
                revision_no=1, sent_at=1050, parent_message_ref="tg:10",
                output_kind="direct_reply", content_text="я брал, на машину",
                correlation_id="turn-1")
            from services.thread_chain import collect_thread_chain
            chain = await collect_thread_chain(db, CHAT, 15, depth=10)
            bot_item = [item for item in reversed(chain) if item.is_bot][-1]
            assert bot_item.uid is None            # ChainItem: uid не заполнен
            bot_frag = comp.chain_item_to_fragment(
                bot_item, role=comp.ROLE_THREAD, bot_user_id=BOT_UID)
            assert bot_frag.speaker_uid == BOT_UID
            # Тот же ход, собранный без `bot_user_id`, и дубль из ledger:
            # выживший фрагмент обязан получить идентичность автора.
            bare = comp.chain_item_to_fragment(bot_item,
                                               role=comp.ROLE_THREAD)
            assert bare.speaker_uid is None        # uid не выдумывается
            ledger = comp.ledger_record_to_fragment(
                {"tg_message_id": 15, "output_id": 1, "sent_at": 1050,
                 "content_text": "", "bot_user_id": BOT_UID,
                 "parent_message_ref": "tg:10"},
                role=comp.ROLE_SELF_OUTPUT, bot_user_id=BOT_UID)
            selection = comp.build_context_selection(
                chat_id=CHAT, current_text="что ты сказал про кредит?",
                reply_to_tg=15, timestamp_utc=2000, thread=[bare],
                self_outputs=[ledger], budget_tokens=10 ** 6)
            bots = [f for f in selection.fragments()
                    if f.kind == comp.KIND_BOT_STATEMENT
                    and f.tg_message_id == 15]
            assert len(bots) == 1                  # дедуп сработал
            assert bots[0].speaker_uid == BOT_UID
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_old_episode_reachable_with_real_messages(self, tmp_path):
        db = await _db(tmp_path, "episode.db")
        try:
            old_ts = 1000
            await _add_msg(db, CHAT, 21, "вчера оформил кредит на машину",
                           old_ts, 100, author_name="Петя")
            await _add_msg(db, CHAT, 22, "на какую сумму кредит?", old_ts + 5,
                           101, reply_to=100, author_name="Вася")
            await _add_msg(db, CHAT, 21, "кредит на 348 тысяч", old_ts + 10,
                           102, reply_to=101, author_name="Петя")
            # Свежее окно другой темы — старый эпизод вне него.
            for step in range(5):
                await _add_msg(db, CHAT, 30 + step, f"свежая болтовня {step}",
                               5000 + step, 200 + step)
            request = rc.build_memory_request(
                chat_id=CHAT, topic="напомни про кредит",
                addressee_uid=21, reply_parent_uid=22,
                reply_parent_text="на какую сумму кредит?")
            result = await rc.retrieve(db, None, request)
            assert result.status == rc.RETRIEVAL_OK
            fragments, raw = await comp.collect_memory_fragments(
                db, chat_id=CHAT, candidates=result.candidates,
                max_fragments=6)
            assert raw >= 1 and fragments
            texts = "\n".join(f.text for f in fragments)
            assert "348" in texts
            # Реальные источники и соседи эпизода с идентификаторами.
            ids = {f.source_id for f in fragments}
            assert any(i.startswith("msg:") for i in ids)
            assert all(f.kind in comp.FRAGMENT_KINDS for f in fragments)
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_bot_output_survives_ttl_with_date_and_parent(self, tmp_path):
        db = await _db(tmp_path, "ttl.db")
        try:
            # TTL-кеш пуст: бот-реплика живёт только в ledger (UR-23).
            await db.record_bot_output(
                chat_id=CHAT, bot_user_id=BOT_UID, tg_message_id=777,
                sent_at=1700000000, parent_message_ref="tg:700",
                output_kind="direct_reply", content_text="я обещал вернуть",
                correlation_id="corr-9")
            fragments = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=BOT_UID)
            assert len(fragments) == 1
            frag = fragments[0]
            assert frag.kind == comp.KIND_BOT_STATEMENT
            assert frag.timestamp_utc == 1700000000 and frag.time_known
            assert frag.reply_to_tg_id == 700
            assert frag.tg_message_id == 777
            assert frag.correlation_id == "corr-9"
            assert frag.authority == comp.AUTHORITY_SUPPORTING
            assert frag.source_id.startswith("bot_output:")
            # Другой чат историю не видит (scope по chat_id).
            other = await comp.collect_self_output_fragments(
                db, chat_id=CHAT + 1, bot_user_id=BOT_UID)
            assert other == ()
        finally:
            await db.close()


# ═══ UR-13.5: правка приоритетнее, конфликт помечен ════════════════════════

class TestCorrectionsAndConflicts:
    def test_later_user_correction_beats_older_fact(self):
        older = _frag(comp.KIND_USER_STATEMENT, "msg:301",
                      "зарплата у меня 60 тысяч", role=comp.ROLE_MEMORY,
                      ts=1000, uid=11)
        newer = _frag(comp.KIND_USER_STATEMENT, "msg:302",
                      "я же сказал: зарплата 90 тысяч, не 60, ошибся",
                      role=comp.ROLE_THREAD, ts=2000, uid=11)
        fragments, corrections = comp.detect_corrections([older, newer])
        by_id = {f.source_id: f for f in fragments}
        assert by_id["msg:301"].superseded_by == "msg:302"
        assert by_id["msg:301"].priority == comp.P3
        # UR-C-2a/UR-11.6: актуальная правка — P0, а не обычная реплика P1.
        assert by_id["msg:302"].priority == comp.P0
        assert by_id["msg:302"].correction is True
        assert by_id["msg:302"].compressible is False
        assert corrections and corrections[0]["target"] == "msg:301"

    @pytest.mark.parametrize("block", ["memory", "fresh_neighbours"])
    def test_late_correction_supersedes_older_fact_in_any_block(self, block):
        """UR-13.5: правка ищет устаревшую версию и вне ветки.

        Большой бюджет — чтобы тест не мог пройти за счёт вытеснения: обе
        версии остаются в payload, но старая помечена `superseded_by` (P3),
        а не подаётся как равнозначный факт.
        """
        role = (comp.ROLE_MEMORY if block == "memory"
                else comp.ROLE_FRESH_NEIGHBOUR)
        older = _frag(comp.KIND_USER_STATEMENT, "msg:311",
                      "зарплата у меня 60 тысяч рублей", role=role,
                      ts=1000, uid=11, tg=311)
        newer = _frag(comp.KIND_USER_STATEMENT, "msg:312",
                      "да нет же, зарплата 90 тысяч, я ошибся",
                      role=comp.ROLE_THREAD, ts=2000, uid=11, tg=312)
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text="напомни, сколько я получаю?",
            timestamp_utc=3000, thread=[newer], budget_tokens=10 ** 6,
            **{block: [older]})
        assert selection.provenance.dropped == ()     # ничего не вытеснено
        by_id = {f.source_id: f for f in selection.fragments()}
        assert {"msg:311", "msg:312"} <= set(by_id)
        assert by_id["msg:311"].superseded_by == "msg:312"
        assert by_id["msg:311"].priority == comp.P3
        assert by_id["msg:311"].authority == comp.AUTHORITY_BACKGROUND
        assert by_id["msg:311"].role == role          # блок не переписан
        # UR-C-2a/UR-11.6: правка сохраняется как P0.
        assert by_id["msg:312"].priority == comp.P0
        assert by_id["msg:312"].correction is True
        assert any(item["target"] == "msg:311"
                   for item in selection.provenance.corrections)

    def test_corrected_older_version_dropped_first_under_pressure(self):
        older = _frag(comp.KIND_USER_STATEMENT, "msg:301",
                      "зарплата 60 тысяч " * 20, role=comp.ROLE_MEMORY,
                      ts=1000, uid=11)
        newer = _frag(comp.KIND_USER_STATEMENT, "msg:302",
                      "поправка: зарплата 90 тысяч, не 60",
                      role=comp.ROLE_THREAD, ts=2000, uid=11)
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text="сколько я получаю?", budget_tokens=120,
            thread=[newer], memory=[older])
        survivors = {f.source_id for f in selection.fragments()}
        assert "msg:302" in survivors
        assert "msg:301" not in survivors
        assert any(item["source_id"] == "msg:301"
                   for item in selection.provenance.dropped)

    def test_contradictory_source_flagged_for_l2(self):
        frag = _frag(comp.KIND_USER_STATEMENT, "msg:401", "кредит 348 тысяч",
                     role=comp.ROLE_MEMORY, ts=1000, uid=11)

        class _Cand:
            id = "tg:401"
            contradiction_status = "conflicting"
            verification = "contradicts"

        fragments, conflicts = comp.mark_source_conflicts([frag], [_Cand()])
        assert fragments[0].authority == comp.AUTHORITY_BACKGROUND
        assert "conflicting" in fragments[0].note
        assert conflicts and conflicts[0]["source_id"] == "msg:401"

    def test_no_memory_no_invention(self):
        selection = comp.build_context_selection(
            chat_id=CHAT, current_text="а что я говорил про кредит?",
            budget_tokens=10 ** 6, memory=[], summary_map=None)
        assert selection.memory == ()
        assert selection.summary_map is None
        assert selection.provenance.memory_found is False
        assert "кредит" not in " ".join(
            f.text for f in selection.fragments()
            if f.role not in (comp.ROLE_CURRENT_QUESTION,))


# ═══ UR-12: конспект по watermark, а не по числу строк ═════════════════════

class TestSummaryConditions:
    def _rows(self, count, start_ts=1000):
        return [{"text": f"строка {i}", "timestamp": start_ts + i}
                for i in range(count)]

    def test_current_watermark_no_refresh(self):
        decision = sm.running_summary_decision(
            self._rows(100), watermark_ts=2000, working_window_messages=20)
        assert decision["refresh"] is False
        assert decision["reason_code"] == "watermark_current"

    def test_uncovered_within_working_window_no_refresh(self):
        decision = sm.running_summary_decision(
            self._rows(30), watermark_ts=900, working_window_messages=40)
        assert decision["refresh"] is False
        assert decision["reason_code"] == "fits_working_window"
        assert decision["uncovered_messages"] == 30

    def test_displaced_messages_trigger_refresh(self):
        decision = sm.running_summary_decision(
            self._rows(40), watermark_ts=1000, working_window_messages=20)
        assert decision["refresh"] is True
        assert decision["reason_code"] == "displaced_by_new_messages"

    def test_fill_ratio_is_not_a_trigger(self):
        # `CHAT_CONTEXT_FILL_RATIO` больше не участвует: решение зависит только
        # от watermark и живого окна (любое значение доли — тот же результат).
        rows = self._rows(40)
        first = sm.running_summary_decision(
            rows, watermark_ts=1000, working_window_messages=20)

        class _Hot:
            def get(self, key, default=None):
                if key == "limits.chat_context_fill_ratio":
                    return 0.01        # экстремальная «доля» — игнорируется
                return sm.hot.get(key, default)

        original = sm.hot
        try:
            sm.hot = _Hot()
            second = sm.running_summary_decision(
                rows, watermark_ts=1000, working_window_messages=20)
            third = sm.running_summary_decision(
                self._rows(10), watermark_ts=1000, working_window_messages=20)
        finally:
            sm.hot = original
        assert first == second
        assert third["refresh"] is False

    @pytest.mark.asyncio
    async def test_coverage_reports_watermark_not_forgetting(self, tmp_path):
        db = await _db(tmp_path, "coverage.db")
        try:
            await db.upsert_running_summary(
                CHAT, "конспект темы", 1000, 2000, 42, 3000.0, 3000.0 + 60)
            status = await sm.summary_coverage(
                db, CHAT, now_ts=3000.0 + 3600, newest_ts=2600)
            assert status["present"] is True
            assert status["covered_to_ts"] == 2000
            assert status["raw_count"] == 42
            assert status["new_since_ts"] == 600
            assert status["stale_by_watermark"] is True
        finally:
            await db.close()


# ═══ UR-13.2: запрос памяти из темы + адресата + reply-parent ══════════════

class TestMemoryQuery:
    def test_query_uses_topic_addressee_and_reply_parent(self):
        query = rc.build_memory_query(
            topic="дай цифры", addressee_name="Петя",
            reply_parent_text="сколько я платил по кредиту?",
            quote_text="кредит на машину")
        assert "дай цифры" in query
        assert "Петя" in query
        assert "кредит" in query
        assert "машину" in query
        assert query.index("дай цифры") < query.index("Петя")

    def test_identity_prior_carries_real_uids(self):
        request = rc.build_memory_request(
            chat_id=CHAT, topic="дай цифры", addressee_uid=11,
            reply_parent_uid=12, reply_parent_text="сколько?",
            participants=(13,))
        assert request.subject_entity_ids == (11, 12)
        assert 11 in request.participants and 12 in request.participants
        assert 13 in request.participants
        assert request.reply_target_entity_id == 12


# ═══ UR-11.2/11.3: Dynamic по умолчанию и model-aware стадии инициативы ════

class TestStageBudgetPolicy:
    def test_dynamic_is_default_mode(self):
        assert ab.DEFAULT_DIRECT_POLICY_MODE == "dynamic"
        assert ab.resolve_policy_mode(None) == "dynamic"
        assert ab.resolve_policy_mode(0) == "dynamic"
        assert ab.resolve_policy_mode(-1) == "unlimited"
        assert ab.resolve_policy_mode(12000) == "cap"

    def test_initiative_stages_are_model_aware(self):
        for slot in ("initiative.l1", "initiative.l2", "direct.l1"):
            policy = ab.stage_policy(slot)
            assert policy is not None, slot
            assert policy.arithmetic == "direct"
            assert policy.overflow_strategy == ab.OVERFLOW_PRIORITY_REDUCE
        # Ни одна стадия не «всем блокам 16000» как жёсткий дефолт.
        for policy in ab.STAGE_POLICIES.values():
            assert "16000" not in str(policy.output_reserve_env or "")

    @pytest.mark.asyncio
    async def test_stage_budget_never_exceeds_physical_window(self):
        result = await ab.resolve_stage_budget(
            "initiative.l2", base_url="", model="unknown-model-xyz")
        assert result.policy_mode == "dynamic"
        assert 0 < result.effective_input_budget <= \
            max(1, result.auto_input_budget)
        assert result.effective_input_budget <= result.context_window or \
            result.context_window == 0


# ── UR-C-1 (UR-10/10.2/10.5): selected L1 window, no 20×200 re-cut ─────────

def _urc_row(index: int, text: str, *, reply_to=None) -> dict:
    return {
        "id": index, "tg_message_id": index, "user_id": 10,
        "author_name": "Вася", "text": text, "timestamp": 100 + index,
        "media_type": "text", "reply_to_id": reply_to,
    }


class TestL1SelectedWindow:
    def test_allocator_keeps_full_p0_reply_and_trigger(self):
        long_reply = "ответ-родитель " + ("R" * 2000)
        long_trigger = "текущий вопрос " + ("T" * 2000)
        rows = [
            _urc_row(1, "фон " + ("B" * 2000)),
            _urc_row(2, long_reply),
            _urc_row(3, long_trigger, reply_to=2),
            _urc_row(4, "свежая реплика " + ("F" * 500)),
        ]
        selected = l1.select_l1_window(
            rows, budget_tokens=120, trigger_message_id=3, reply_to_id=2)
        by_id = {row["tg_message_id"]: row for row in selected}
        assert by_id[2]["text"] == long_reply
        assert by_id[3]["text"] == long_trigger
        assert "B" * 2000 not in "".join(
            row["text"] for row in selected if row["tg_message_id"] == 1)

    def test_build_l1_context_uses_selected_rows_without_20x200(self):
        rows = [_urc_row(i, f"сообщение-{i} " + ("X" * 400))
                for i in range(1, 26)]
        rows[5]["reply_to_id"] = 2
        ctx = l1.build_l1_context(
            query="q", window=rows, window_limit=len(rows), line_chars=0,
            with_ids=True, budget_tokens=1_000_000)
        assert ctx.count("[msg:") == 25
        assert "X" * 400 in ctx
        assert "(ответ на msg:2)" in ctx
        assert "[ГРАНИЦА ИСТОРИИ]" not in ctx

    def test_tight_budget_preserves_p0_and_reports_overflow(self):
        reply = "R" * 2000
        trigger = "T" * 2000
        rows = [
            _urc_row(2, reply),
            _urc_row(3, trigger, reply_to=2),
        ]
        status: dict = {}
        ctx = l1.build_l1_context(
            query="q", current_question=trigger, reply_block=reply,
            window=rows, line_chars=0, with_ids=True, budget_tokens=1600,
            trigger_message_id=3, reply_to_message_id=2,
            preallocated=True, out_status=status)
        assert reply in ctx
        assert trigger in ctx
        assert status["window_preserved"] is True
        assert status["overflow"] is True
        assert status["used_tokens"] > status["budget_tokens"]
        # P0 не конкурирует с окном: fixed уже больше бюджета, окно пустое,
        # trigger/reply исключены из candidate window (они в fixed-секциях).
        assert status["fixed_tokens"] >= status["budget_tokens"]
        assert status["window_budget"] == 1
        assert status["window_rows_selected"] == 0
        assert status["window_rows_excluded_p0"] == 2
        assert "[ПОСЛЕДНИЕ СООБЩЕНИЯ]" not in ctx
        assert status["overflow_sections"]

    @pytest.mark.asyncio
    async def test_tight_budget_both_live_sites_preserve_selected_window(
            self, monkeypatch):
        from tests.test_ur_turn_engine import (
            _patch_fixed_tool_flags, _plan as _ur_plan, _run_direct,
            _run_initiative, _svc)

        _patch_fixed_tool_flags(monkeypatch)
        long_rows = [
            _urc_row(2, "R" * 2000),
            _urc_row(3, "T" * 2000, reply_to=2),
        ]
        monkeypatch.setattr(
            l1, "select_l1_window",
            lambda window, **kwargs: [dict(r) for r in long_rows])
        captures = []
        real_build = l1.build_l1_context

        def _build_spy(**kwargs):
            result = real_build(**kwargs)
            captures.append((kwargs, result, kwargs.get("out_status")))
            return result

        monkeypatch.setattr(l1, "build_l1_context", _build_spy)
        service = _svc(_ur_plan(), window=long_rows)

        await _run_direct(service)
        await _run_initiative(service)

        assert len(captures) == 2
        for kwargs, result, status in captures:
            assert kwargs["preallocated"] is True
            assert kwargs["line_chars"] == 0
            assert "R" * 2000 in result
            assert "T" * 2000 in result
            assert "[ПОСЛЕДНИЕ СООБЩЕНИЯ]" in result
            assert status is not None
            assert status["window_preserved"] is True
            assert "overflow" in status
            assert status["used_tokens"] > 0

    @pytest.mark.asyncio
    async def test_both_live_call_sites_pass_raw_window_and_zero_line_cap(
            self, monkeypatch):
        from tests.test_ur_turn_engine import (
            _patch_fixed_tool_flags, _plan as _ur_plan, _run_direct,
            _run_initiative, _svc)

        _patch_fixed_tool_flags(monkeypatch)
        calls = []
        real_select = l1.select_l1_window
        real_build = l1.build_l1_context
        select_calls = {"n": 0}

        def _select_spy(window, **kwargs):
            select_calls["n"] += 1
            return real_select(window, **kwargs)

        def _build_spy(**kwargs):
            status = kwargs.get("out_status")
            result = real_build(**kwargs)
            calls.append((kwargs, status))
            return result

        monkeypatch.setattr(l1, "select_l1_window", _select_spy)
        monkeypatch.setattr(l1, "build_l1_context", _build_spy)
        window = [_urc_row(i, f"строка-{i} " + ("Y" * 400))
                  for i in range(1, 6)]
        service = _svc(_ur_plan(), window=window)

        await _run_direct(service)
        await _run_initiative(service)

        # Live L1 больше не вызывает legacy select_l1_window: окно выбирает
        # `build_l1_context` через единый allocator.
        assert select_calls["n"] == 0
        assert len(calls) == 2
        for kwargs, status in calls:
            assert kwargs["preallocated"] is True
            assert kwargs["line_chars"] == 0
            assert kwargs["window"] == window
            assert "window_limit" not in kwargs or kwargs["window_limit"] is None
            # T8: оба live-сайта отдают честный status единственного
            # allocator'а (fixed/window/selected/overflow).
            assert status is not None
            assert status["fixed_tokens"] >= 0
            assert status["window_budget"] >= 1
            assert status["window_rows_selected"] <= status["window_rows_raw"]
            assert "overflow" in status


# ═══ UR-C-2a (A2 core, offline): producers, tiers, correction P0, parity ════

class _Aliases:
    def resolve(self, uid, name, username):
        return name or f"u{uid}"


def _dcs():
    """Минимальный сервис: только существующие рендереры формата L2."""
    return dcs.DirectChatService(None, None, None, _Aliases(), bot_id=BOT_UID)


def _chain(count=4, uid=10, name="Вася"):
    return [tchain.ChainItem(uid=uid, name=name, text=f"ход {i + 1}",
                             is_bot=False, ts=100 + i,
                             item_id=f"tg:{i + 1}")
            for i in range(count)]


class TestURC2aProducers:
    def test_branch_is_p0_projection_without_duplicating_thread(self):
        chronological = _chain(5)                    # root → current
        service_chain = list(reversed(chronological))  # current → root (реальный)
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", chain_items=service_chain, branch_hops=2,
            working_window_messages=0)
        branch_ids = [f.source_id for f in selection.reply_branch]
        thread_ids = [f.source_id for f in selection.thread]
        assert branch_ids == ["msg:4", "msg:5"]
        assert thread_ids == ["msg:1", "msg:2", "msg:3"]
        assert set(branch_ids).isdisjoint(thread_ids)
        assert all(f.priority == comp.P0 for f in selection.reply_branch)
        assert all(f.priority == comp.P1 for f in selection.thread)
        assert all(not f.compressible for f in selection.reply_branch)
        assert selection.current_question.priority == comp.P0
        # Правок нет — correction-флаг не выдуман.
        assert not any(f.correction for f in selection.fragments())
        # Граница hops=0: вся цепочка — thread, P0-ветки нет.
        no_branch = dcs._build_l2_selection_candidates(
            current_text="вопрос", chain_items=service_chain, branch_hops=0,
            working_window_messages=0)
        assert no_branch.reply_branch == ()
        assert len(no_branch.thread) == len(chronological)

    def test_fact_episode_self_output_and_summary_tiers(self):
        fact = {"id": 7, "text": "кредит на 348 тысяч",
                "timestamp_utc": 1000, "author_id": 21}
        episode = _urc_row(41, "дословная старая реплика")
        summary = {"summary": "спорили о кредите", "window_end_ts": 900,
                   "raw_count": 12}
        selection = dcs._build_l2_selection_candidates(
            current_text="напомни про кредит", timestamp_utc=2000,
            fact_rows=[fact], episode_rows=[episode],
            self_output_records=[{
                "output_id": 3, "tg_message_id": 55, "sent_at": 1500,
                "content_text": "я говорил про 348 тысяч",
                "bot_user_id": BOT_UID, "parent_message_ref": "tg:41",
                "correlation_id": "turn-9"}],
            summary_row=summary, working_window_messages=0)
        by_id = {f.source_id: f for f in selection.fragments()}
        fact_frag = by_id["fact:7"]
        assert fact_frag.role == comp.ROLE_MEMORY
        assert fact_frag.memory_tier == 3
        assert fact_frag.authority == comp.AUTHORITY_BACKGROUND
        assert "не дословная реплика" in fact_frag.note
        episode_frag = by_id["msg:41"]
        assert episode_frag.role == comp.ROLE_MEMORY
        assert episode_frag.memory_tier == 4
        assert episode_frag.authority == comp.AUTHORITY_PRIMARY
        self_frag = by_id["bot_output:3"]
        assert self_frag.role == comp.ROLE_SELF_OUTPUT
        assert self_frag.authority == comp.AUTHORITY_SUPPORTING
        assert self_frag.speaker_uid == BOT_UID
        assert selection.summary and \
            selection.summary[0].authority == comp.AUTHORITY_BACKGROUND
        assert selection.provenance.memory_found is True
        # R17-safe срез знает новые аддитивные поля.
        summary_dict = selection.as_dict()
        assert summary_dict["reply_branch"] == []
        assert summary_dict["memory"][0]["memory_tier"] == 3
        assert "correction" in summary_dict["memory"][0]
        assert "compressible" in summary_dict["memory"][0]

    def test_window_split_and_middle_lines_are_background(self):
        rows = [_urc_row(i, f"строка {i}") for i in range(1, 9)]
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", window_rows=rows,
            working_window_messages=5,
            middle_lines=["middle-строка о деньгах"])
        fresh_ids = [f.source_id for f in selection.fresh_neighbours]
        assert fresh_ids == [f"msg:{i}" for i in range(4, 9)]
        assert all(f.role == comp.ROLE_FRESH_NEIGHBOUR
                   and f.priority == comp.P1
                   for f in selection.fresh_neighbours)
        background_ids = [f.source_id for f in selection.background]
        assert background_ids[:3] == ["msg:1", "msg:2", "msg:3"]
        assert background_ids[-1] == "middle:0"
        assert all(f.priority == comp.P3 for f in selection.background)
        assert selection.background[-1].text == "middle-строка о деньгах"

    def test_same_source_from_window_and_episode_deduped_once(self):
        row = _urc_row(77, "одна и та же реплика")
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", window_rows=[row],
            episode_rows=[row], working_window_messages=5)
        matches = [f for f in selection.fragments()
                   if f.source_id == "msg:77"]
        assert len(matches) == 1
        assert matches[0].role == comp.ROLE_FRESH_NEIGHBOUR
        assert any(item.get("reason_code") == "duplicate_source"
                   for item in selection.provenance.dropped)
        # Даже когда allocator режет бюджет, dedup-запись не стирается.
        tight = dcs._build_l2_selection_candidates(
            current_text="вопрос", window_rows=[row],
            episode_rows=[row], working_window_messages=5,
            budget_tokens=1)
        assert any(item.get("reason_code") == "duplicate_source"
                   for item in tight.provenance.dropped)

    def test_missing_fact_source_is_marked_as_model_output(self):
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос",
            fact_rows=[{"id": 8, "text": "предположение модели"}],
            working_window_messages=0)
        blocks = dict(dcs._materialize_selection(
            selection,
            render_chain_line=lambda frag, source: "",
            render_row_line=lambda frag, source: ""))
        assert "rag" in blocks
        assert "[вывод модели]" in blocks["rag"]
        assert "предположение модели" in blocks["rag"]
        # Не выдаётся за дословную реплику.
        assert "<Old_Episode>" not in blocks.get("episode", "")

    def test_memory_tiers_drop_episode_then_graph_then_exact(self):
        def _tier(tier: int, sid: str):
            return comp.ContextFragment(
                kind=comp.KIND_SUMMARY_INFERENCE, source_id=sid,
                timestamp_utc=100 + tier, text="факт о кредите " * 10,
                role=comp.ROLE_MEMORY, authority=comp.AUTHORITY_BACKGROUND,
                time_known=True, memory_tier=tier)

        full = comp.build_context_selection(
            chat_id=CHAT, current_text="вопрос", timestamp_utc=2000,
            memory=[_tier(4, "episode:4"), _tier(3, "fact:3"),
                    _tier(2, "msg:2")], budget_tokens=0)
        current = full.current_question
        tier2 = [f for f in full.memory if f.memory_tier == 2][0]
        budget = current.tokens() + tier2.tokens() + 1
        tight = comp.build_context_selection(
            chat_id=CHAT, current_text="вопрос", timestamp_utc=2000,
            memory=full.memory, budget_tokens=budget)
        reasons = [item["reason_code"] for item in tight.provenance.dropped
                   if item["source_id"].startswith(("episode:", "fact:"))]
        assert reasons == ["memory_tier_4", "memory_tier_3"]
        survivors = {f.source_id for f in tight.memory}
        assert survivors == {"msg:2"}

    def test_self_outputs_merge_with_window_tail_by_time(self):
        rows = [_urc_row(1, "раньше"), _urc_row(3, "позже")]
        rows[0]["timestamp"] = 100
        rows[1]["timestamp"] = 300
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", window_rows=rows,
            working_window_messages=5,
            self_output_records=[{
                "output_id": 2, "tg_message_id": 2, "sent_at": 200,
                "content_text": "ответ бота", "bot_user_id": BOT_UID,
                "parent_message_ref": "tg:1"}])
        index = {f"msg:{row['tg_message_id']}": row for row in rows}
        index["bot_output:2"] = {
            "tg_message_id": 2, "timestamp": 200, "user_id": BOT_UID,
            "author_name": "бот", "text": "ответ бота", "reply_to_id": 1}
        blocks = dict(dcs._materialize_selection(
            selection,
            render_chain_line=lambda frag, source: "",
            render_row_line=lambda frag, source: source["text"],
            source_index=index))
        body = blocks["global"].split("\n")[1:-1]
        assert body == ["раньше", "ответ бота", "позже"]
        # Собственный ответ — факт диалога, не style-anchor/подражание.
        assert "style_anchors" not in blocks["global"]
        assert "подражай" not in blocks["global"]


class TestURC2aConvergence:
    """RED/GREEN для URC2A-R1-01…R1-04 (реальные chain/tuple/pressure)."""

    def test_p0_correction_in_memory_tier4_survives_pressure(self):
        old = comp.ContextFragment(
            kind=comp.KIND_USER_STATEMENT, source_id="msg:1",
            text="зарплата у меня 60 тысяч", timestamp_utc=1000,
            speaker_uid=11, author_label="u11", role=comp.ROLE_MEMORY,
            tg_message_id=1, authority=comp.AUTHORITY_PRIMARY,
            time_known=True, memory_tier=4)
        new = comp.ContextFragment(
            kind=comp.KIND_USER_STATEMENT, source_id="msg:2",
            text="поправка: зарплата 90 тысяч, не 60", timestamp_utc=2000,
            speaker_uid=11, author_label="u11", role=comp.ROLE_MEMORY,
            tg_message_id=2, authority=comp.AUTHORITY_PRIMARY,
            time_known=True, memory_tier=4)
        full = comp.build_context_selection(
            chat_id=CHAT, current_text="сколько я получаю?",
            timestamp_utc=3000, memory=[old, new], budget_tokens=0)
        correction = [f for f in full.memory if f.source_id == "msg:2"][0]
        assert correction.correction is True
        assert correction.priority == comp.P0
        budget = full.current_question.tokens() + 1
        tight = comp.build_context_selection(
            chat_id=CHAT, current_text="сколько я получаю?",
            timestamp_utc=3000, memory=full.memory, budget_tokens=budget)
        survivors = {f.source_id for f in tight.fragments()}
        assert "msg:2" in survivors
        assert all(item.get("source_id") != "msg:2"
                   for item in tight.provenance.dropped)
        # P0 физически не влезает — честный overflow, но не потеря.
        assert tight.provenance.overflow is True
        assert tight.provenance.included_tokens > budget

    def test_fact_row_accepts_real_kept_tuple(self):
        row = ("chat_history", "кредит на 348 тысяч", 1000, "Петя",
               "msg:900", "", False, "")
        frag = comp.fragment_from_fact_row(row)
        assert frag is not None
        assert frag.text == "кредит на 348 тысяч"
        assert frag.source_id == "msg:900"
        assert frag.tg_message_id == 900
        assert frag.timestamp_utc == 1000
        assert frag.author_label == "Петя"
        assert frag.role == comp.ROLE_MEMORY
        assert frag.memory_tier == 3
        assert frag.authority == comp.AUTHORITY_BACKGROUND
        # Прежний dict-контракт не сломан.
        dict_frag = comp.fragment_from_fact_row(
            {"id": 7, "text": "кредит", "timestamp_utc": 1000})
        assert dict_frag is not None
        assert dict_frag.source_id == "fact:7"

    def test_exact_memory_outranks_supporting_self_output(self):
        exact = comp.ContextFragment(
            kind=comp.KIND_USER_STATEMENT, source_id="msg:701",
            text="точный факт о кредите " * 10, timestamp_utc=500,
            speaker_uid=11, author_label="u11", role=comp.ROLE_MEMORY,
            tg_message_id=701, authority=comp.AUTHORITY_PRIMARY,
            time_known=True, memory_tier=2)
        self_out = comp.ContextFragment(
            kind=comp.KIND_BOT_STATEMENT, source_id="bot_output:3",
            text="бот когда-то сказал " * 20, timestamp_utc=600,
            speaker_uid=BOT_UID, author_label="бот",
            role=comp.ROLE_SELF_OUTPUT,
            authority=comp.AUTHORITY_SUPPORTING, time_known=True)
        full = comp.build_context_selection(
            chat_id=CHAT, current_text="сколько я платил?",
            timestamp_utc=1000, memory=[exact], self_outputs=[self_out],
            budget_tokens=0)
        budget = full.current_question.tokens() + exact.tokens() + 1
        tight = comp.build_context_selection(
            chat_id=CHAT, current_text="сколько я платил?",
            timestamp_utc=1000, memory=[exact], self_outputs=[self_out],
            budget_tokens=budget)
        survivors = {f.source_id for f in tight.fragments()}
        assert "msg:701" in survivors
        assert "bot_output:3" not in survivors
        reasons = {item["source_id"]: item["reason_code"]
                   for item in tight.provenance.dropped}
        assert reasons["bot_output:3"] == "low_value_memory"


class TestURC2aMaterializerParity:
    def test_branch_and_thread_match_existing_renderers(self):
        service = _dcs()
        chronological = _chain(4)                       # root → current
        service_chain = list(reversed(chronological))    # реальный порядок
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", chain_items=service_chain, branch_hops=3,
            working_window_messages=0)
        assert [f.source_id for f in selection.reply_branch] == [
            "msg:2", "msg:3", "msg:4"]
        assert [f.source_id for f in selection.thread] == ["msg:1"]
        index = {f"msg:{i + 1}": item
                 for i, item in enumerate(chronological)}
        chain_order = {f"msg:{i + 1}": i
                       for i, _item in enumerate(chronological)}
        blocks = dict(dcs._materialize_selection(
            selection,
            render_chain_line=lambda frag, item: service._chain_line(
                item, {}, None),
            render_row_line=lambda frag, row: "",
            source_index=index, chain_order=chain_order))
        assert blocks["branch"] == service._render_branch(service_chain, {},
                                                          None)
        assert blocks["thread"] == service._render_thread(
            service_chain, {}, truncate=False)
        assert "<Conversation_Branch>" in blocks["branch"]
        assert "<Conversation_Thread>" in blocks["thread"]
        # Branch — проекция хвоста цепочки, не второй набор строк.
        branch_body = blocks["branch"].split("\n")[1:-1]
        thread_body = blocks["thread"].split("\n")[1:-1]
        assert set(branch_body) <= set(thread_body)

    def test_global_window_tail_matches_existing_row_renderer(self):
        service = _dcs()
        rows = [_urc_row(i, f"строка {i}") for i in range(1, 6)]
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", window_rows=rows,
            working_window_messages=len(rows))
        index = {f"msg:{row['tg_message_id']}": row for row in rows}
        blocks = dict(dcs._materialize_selection(
            selection,
            render_chain_line=lambda frag, source: "",
            render_row_line=lambda frag, row: service._context_row_line(
                row, {}, None),
            source_index=index))
        expected_body = "\n".join(
            service._context_row_line(row, {}, None) for row in rows)
        assert blocks["global"] == (
            f"<Global_Context>\n{escape_xml_text(expected_body)}\n"
            f"</Global_Context>")

    def test_global_summary_middle_tail_order_and_bytes(self):
        service = _dcs()
        rows = [_urc_row(i, f"строка {i}") for i in range(1, 6)]
        summary = {"summary": "конспект темы", "window_end_ts": 0,
                   "raw_count": 5}
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", window_rows=rows,
            working_window_messages=2, summary_row=summary,
            middle_lines=["middle-строка"])
        index = {f"msg:{row['tg_message_id']}": row for row in rows}
        blocks = dict(dcs._materialize_selection(
            selection,
            render_chain_line=lambda frag, source: "",
            render_row_line=lambda frag, row: service._context_row_line(
                row, {}, None),
            source_index=index))
        head = ["конспект темы"]
        middle = [service._context_row_line(row, {}, None)
                  for row in rows[:3]] + ["middle-строка"]
        tail = [service._context_row_line(row, {}, None)
                for row in rows[3:]]
        expected = "\n".join(head + middle + tail)
        assert blocks["global"] == (
            f"<Global_Context>\n{escape_xml_text(expected)}\n"
            f"</Global_Context>")

    def test_rag_and_episode_match_existing_renderers(self):
        service = _dcs()
        fact = ("chat_history", "кредит на 348 тысяч", 1000, "Петя",
                "msg:900")
        episode_rows = [_urc_row(41, "дословная старая реплика"),
                        _urc_row(42, "и ещё одна")]
        selection = dcs._build_l2_selection_candidates(
            current_text="вопрос", fact_rows=[fact],
            episode_rows=episode_rows, working_window_messages=0)
        index = {"msg:900": fact}
        index.update({f"msg:{row['tg_message_id']}": row
                      for row in episode_rows})
        blocks = dict(dcs._materialize_selection(
            selection,
            render_chain_line=lambda frag, source: "",
            render_row_line=lambda frag, row: service._context_row_line(
                row, {}, None),
            source_index=index))
        from services.summary_memory import build_rag_context
        assert blocks["rag"] == (
            "<RAG_Memory>\n"
            + build_rag_context([fact], origin_labels=True)
            + "\n</RAG_Memory>")
        expected_episode = "\n".join(
            service._context_row_line(row, {}, None) for row in episode_rows)
        assert blocks["episode"] == (
            f"<Old_Episode>\n{escape_xml_text(expected_episode)}\n"
            f"</Old_Episode>")
        # CANONICAL_ORDER: episode раньше rag, current — в конце.
        assert list(blocks) == ["episode", "rag", "current"]

    def test_current_question_uses_existing_renderer(self):
        service = _dcs()
        message = SimpleNamespace(text="полный текущий вопрос",
                                  message_id=99, reply_to_message=None)
        selection = dcs._build_l2_selection_candidates(
            current_text="полный текущий вопрос", message_tg_id=99,
            working_window_messages=0)
        blocks = dict(dcs._materialize_selection(
            selection,
            render_chain_line=lambda frag, source: "",
            render_row_line=lambda frag, source: "",
            render_current=lambda frag, source: service._render_current_question(
                message)))
        assert blocks["current"] == \
            service._render_current_question(message)
        assert "полный текущий вопрос" in blocks["current"]


class TestURC2aLivePathUnchanged:
    def test_live_compose_wires_selection_and_keeps_legacy_fail_open(self):
        source = inspect.getsource(dcs.DirectChatService._compose_user_content)
        # UR-C-2b: live-путь использует selection и единственный allocator.
        assert "_build_l2_selection_candidates(" in source
        assert "allocate_selection(" in source
        # Старый блочный allocator остаётся ТОЛЬКО как fail-open ветка.
        assert "allocate_budget(" in source
        assert source.index("_run_live_selection") < \
            source.index("allocate_budget(")
        # Helper'ы существуют и доступны live-пути.
        assert callable(dcs._build_l2_selection_candidates)
        assert callable(dcs._materialize_selection)
