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
  * UR-11.2/11.3 — Dynamic по умолчанию и model-aware стадии инициативы.
"""
import pytest

from services import auto_budget as ab
from services import direct_context_composer as comp
from services import mca_retrieval_context as rc
from services import summary_memory as sm
from services.database import DatabaseService
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
            assert bot_frag.speaker_uid is None
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
        assert by_id["msg:302"].priority == comp.P1
        assert corrections and corrections[0]["target"] == "msg:301"

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
