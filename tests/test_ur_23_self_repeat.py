"""UNIFIED-REPLY UR-23 — самоповтор по контексту и umbrella-история (23.6/23.8).

Покрывает незакрытые строки карты UR-C:
  * UR-23.6 — повтор допустим на новом ходе (наблюдение, не запрет);
    зацикливание на старой шутке снимается локально; цитата собственных слов
    по прямой просьбе не вырезается; директивы «подражай прошлым ответам»
    (style anchors) в активных промптах нет;
  * UR-23.8 — собственный ответ после TTL извлекается из ledger с реальной
    датой и адресатом; Summary/Initiative остаются в истории; старый
    самообман остаётся supporting-фактом диалога, а не истиной о мире;
    новых style-anchor циклов не появляется.

TEST-LIFECYCLE: CONTRACT owner=UR-23.6/23.8 (UR-C, слайс UR-23)
"""
from __future__ import annotations

import inspect

import pytest

from services import bot_output_ledger as ledger
from services import chat_params
from services import direct_context_composer as comp
from services import hot_config as hot
from services import prompt_registry as pr
from services import response_freshness as fresh
from services import style_policy as sp
from services.database import DatabaseService
from services.thread_chain import collect_thread_chain

CHAT = -100555
BOT_UID = 998000
HUMAN_UID = 11
YESTERDAY = 1_699_000_000 - 86_400
NOW = 1_699_000_000


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeChatCache:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}


@pytest.fixture(autouse=True)
def _clean_repeat_state():
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


def _enable_style(monkeypatch):
    monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
    hot.set_config_cache(FakeHot({
        "flags.speech_style_policy_enabled": True,
        sp.DOC_KEY: sp.build_document(presets=["casual_concise"], owner=1),
    }))
    chat_params.set_chat_params_cache(FakeChatCache())


async def _db(tmp_path, name="ur23_self_repeat.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _human(db, *, message_id=700, text="верни деньги", ts=YESTERDAY):
    await db.save_smart_message(
        user_id=HUMAN_UID, chat_id=CHAT, text=text, reply_to_id=None,
        timestamp=ts, media_type="text", author_name="Вася",
        message_id=message_id)


async def _bot_output(db, *, tg=701, text="ответ", sent_at=YESTERDAY,
                      parent=None, kind="direct_reply", correlation=None,
                      source_feature=None):
    return await db.record_bot_output(
        chat_id=CHAT, bot_user_id=BOT_UID, tg_message_id=tg, revision_no=1,
        sent_at=sent_at, parent_message_ref=parent, output_kind=kind,
        content_text=text, correlation_id=correlation,
        source_feature=source_feature)


# ═══ UR-23.6: повтор/цитата/старая шутка ════════════════════════════════════

class TestSelfRepeatContext:
    @pytest.mark.asyncio
    async def test_repeat_on_new_turn_is_delivered_as_written(self,
                                                              monkeypatch):
        """Новый ход (другой tg_message_id) не запрещает тот же ответ.

        RLR-04: exact duplicate — наблюдение, а не reroll; стилевой проход
        целую повторённую реплику не переписывает (critical ≠ sticky).
        """
        answer = "Ну и снова шутка про бухгалтера и отчёт"
        verdict = fresh.evaluate_duplicate(
            answer, answer, new_tg_message_id=5002)
        assert verdict.duplicate is True and verdict.exempt is False
        # Reroll/перефразирование API отсутствуют: готовый текст не подменяется.
        assert not hasattr(verdict, "regeneration_allowed")
        assert not hasattr(fresh, "paraphrase")
        assert "regeneration_already_used" not in \
            inspect.signature(fresh.evaluate_duplicate).parameters

        _enable_style(monkeypatch)
        sp.record_bot_output(CHAT, answer)
        outcome = await sp.apply_style_policy(answer, chat_id=CHAT)
        assert outcome.text == answer, "повтор допустимого ответа переписан"
        assert outcome.repetition
        assert outcome.repetition[0]["severity"] == "critical"
        assert not any(row.get("repaired") for row in outcome.repetition)

    @pytest.mark.asyncio
    async def test_old_joke_loop_is_trimmed_not_regenerated(self, monkeypatch):
        """Зацикливание на старой шутке снимается локально, суть остаётся."""
        _enable_style(monkeypatch)
        joke = "Ну и снова шутка про бухгалтера и отчёт"
        sp.record_bot_output(CHAT, joke)
        calls = {"n": 0}

        async def repair(text, instruction):
            calls["n"] += 1
            return "переписано"

        outcome = await sp.apply_style_policy(
            "Смотри, что вышло. " + joke, chat_id=CHAT,
            repair=repair, repair_allowed=True)
        assert outcome.text == "Смотри, что вышло."
        assert "шутка про бухгалтера" not in outcome.text
        assert any(row.get("repaired") for row in outcome.repetition)
        assert calls["n"] == 0 and outcome.repair_used == 0

    @pytest.mark.asyncio
    async def test_requested_quote_of_own_words_is_not_trimmed(self,
                                                               monkeypatch):
        """Прямая просьба повторить: цитата своих слов остаётся в ответе."""
        _enable_style(monkeypatch)
        joke = "Ну и снова шутка про бухгалтера и отчёт"
        sp.record_bot_output(CHAT, joke)
        outcome = await sp.apply_style_policy(
            "Ты просил повторить: «" + joke + "»", chat_id=CHAT)
        assert joke in outcome.text, "цитата собственных слов вырезана"
        assert not any(row.get("repaired") for row in outcome.repetition)


# ═══ UR-23.6/23.8: директивы подражания и style-anchor циклы ════════════════

class TestNoImitationDirective:
    def test_active_prompt_blocks_have_no_imitate_anchor(self):
        """Активные промпты не просят подражать прошлым ответам бота."""
        hits: list[tuple[str, str]] = []
        for block in pr.all_blocks():
            try:
                text = str(pr.factory_text(block.block_id) or "")
            except Exception:      # pragma: no cover - защитная ветка
                text = ""
            folded = text.casefold()
            if "<style_anchors>" in folded or "подражай общей интонации" in folded:
                hits.append((block.block_id, folded[:120]))
        assert hits == [], f"директива подражания в активных блоках: {hits}"

    def test_direct_assembly_has_no_style_anchor_cycle(self):
        """В активной сборке Direct нет секции/метода style_anchors.

        Runtime-payload с непустыми прошлыми ответами уже проверяется
        существующим `test_direct_chat.py::test_no_style_anchors_even_with_replies`;
        здесь — источник сборки, чтобы директива не вернулась новым циклом.
        """
        import services.direct_chat_service as dcs

        assert not hasattr(dcs.DirectChatService, "_build_style_anchors")
        source = inspect.getsource(dcs)
        assert 'blocks.append(("anchors"' not in source
        assert "подражай общей интонации" not in source

    @pytest.mark.asyncio
    async def test_ledger_self_output_is_dialog_fact_not_style_anchor(
            self, tmp_path):
        db = await _db(tmp_path, "anchor.db")
        try:
            await _bot_output(db, text="я всегда так шучу")
            fragments = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=BOT_UID)
            assert len(fragments) == 1
            frag = fragments[0]
            assert frag.kind == comp.KIND_BOT_STATEMENT
            assert frag.role == comp.ROLE_SELF_OUTPUT
            assert frag.authority == comp.AUTHORITY_SUPPORTING
            assert "подраж" not in frag.note.casefold()
            selection = comp.build_context_selection(
                chat_id=CHAT, current_text="повтори, что ты говорил?",
                timestamp_utc=NOW + 60, self_outputs=fragments,
                budget_tokens=10 ** 6)
            dump = selection.as_dict()
            assert "style_anchors" not in dump
            assert dump["self_outputs"][0]["kind"] == \
                comp.KIND_BOT_STATEMENT
            assert "text" not in dump["self_outputs"][0]
        finally:
            await db.close()


# ═══ UR-23.8: ledger после TTL, дата/адресат, Summary/Initiative ═══════════

class TestLedgerUmbrella:
    @pytest.mark.asyncio
    async def test_ttl_expired_answer_recovers_date_and_addressee(
            self, tmp_path):
        """TTL-кеш пуст: дата и адресат берутся из ledger/цепочки, не «сейчас»."""
        db = await _db(tmp_path, "ttl.db")
        try:
            await _human(db, message_id=700, text="верни деньги",
                         ts=YESTERDAY - 60)
            # bot_replies (TTL-кеш) намеренно не заполняется: истории там нет.
            assert await db.get_bot_reply(CHAT, 701, now=NOW) is None
            await _bot_output(db, tg=701, sent_at=YESTERDAY,
                              parent="tg:700", correlation="turn-42",
                              text="я обещал вернуть 174 тысячи")
            fragments = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=BOT_UID)
            assert len(fragments) == 1
            frag = fragments[0]
            assert frag.timestamp_utc == YESTERDAY
            assert frag.time_known is True
            assert frag.tg_message_id == 701
            assert frag.reply_to_tg_id == 700
            assert frag.correlation_id == "turn-42"
            assert frag.source_id.startswith("bot_output:")

            chain = await collect_thread_chain(db, CHAT, 701, depth=4)
            by_id = {item.item_id: item for item in chain}
            assert by_id["tg:700"].uid == HUMAN_UID
            assert by_id["tg:700"].text == "верни деньги"
            assert by_id["tg:701"].is_bot is True
            assert by_id["tg:701"].ts == YESTERDAY

            selection = comp.build_context_selection(
                chat_id=CHAT,
                current_text="что ты вчера обещал Васе?",
                timestamp_utc=NOW, thread=[
                    comp.chain_item_to_fragment(
                        item, role=comp.ROLE_THREAD,
                        bot_user_id=BOT_UID)
                    for item in reversed(chain)],
                self_outputs=fragments, budget_tokens=10 ** 6)
            selected = [f for f in selection.fragments()
                        if f.kind == comp.KIND_BOT_STATEMENT
                        and f.tg_message_id == 701]
            assert len(selected) == 1
            assert selected[0].timestamp_utc == YESTERDAY
            assert selected[0].reply_to_tg_id == 700
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_summary_and_initiative_stay_in_own_history(self, tmp_path):
        """Summary/Initiative outputs не выпадают из ledger-истории."""
        db = await _db(tmp_path, "kinds.db")
        try:
            await _bot_output(
                db, tg=801, text="Итог дня: всё спокойно",
                sent_at=YESTERDAY + 100, kind="rich_message",
                source_feature="summary")
            await _bot_output(
                db, tg=802, text="Заметил, что вы давно не спорили",
                sent_at=YESTERDAY + 200, kind="initiative_reply",
                source_feature="initiative")
            rows = await ledger.list_bot_output_history(db, CHAT)
            assert [row["tg_message_id"] for row in rows] == [801, 802]
            assert [row["output_kind"] for row in rows] == [
                "rich_message", "initiative_reply"]
            assert [row["source_feature"] for row in rows] == [
                "summary", "initiative"]
            assert [row["text"] for row in rows] == [
                "Итог дня: всё спокойно",
                "Заметил, что вы давно не спорили"]
            fragments = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=BOT_UID)
            assert [frag.tg_message_id for frag in fragments] == [801, 802]
            assert all(frag.timestamp_utc in (YESTERDAY + 100,
                                              YESTERDAY + 200)
                       for frag in fragments)
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_old_self_claim_stays_supporting_not_world_fact(
            self, tmp_path):
        """Старый самообман бота не становится primary-истиной о мире."""
        db = await _db(tmp_path, "authority.db")
        try:
            await _bot_output(db, tg=901, sent_at=YESTERDAY,
                              text="я владею заводом")
            rows = await ledger.list_bot_output_history(db, CHAT)
            assert rows[0]["self_referential"] is True
            fragments = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=BOT_UID)
            assert fragments[0].authority == comp.AUTHORITY_SUPPORTING
            assert comp.authority_for_kind(comp.KIND_BOT_STATEMENT) == \
                comp.AUTHORITY_SUPPORTING
            selection = comp.build_context_selection(
                chat_id=CHAT, current_text="правда, что ты владеешь заводом?",
                timestamp_utc=NOW,
                thread=[comp.ContextFragment(
                    kind=comp.KIND_USER_STATEMENT, source_id="msg:900",
                    timestamp_utc=NOW, speaker_uid=HUMAN_UID,
                    text="он сказал, что владеет заводом",
                    role=comp.ROLE_THREAD,
                    authority=comp.AUTHORITY_PRIMARY)],
                self_outputs=fragments, budget_tokens=10 ** 6)
            by_kind = {frag.kind: frag for frag in selection.fragments()}
            assert by_kind[comp.KIND_USER_STATEMENT].authority == \
                comp.AUTHORITY_PRIMARY
            assert by_kind[comp.KIND_BOT_STATEMENT].authority == \
                comp.AUTHORITY_SUPPORTING
        finally:
            await db.close()
