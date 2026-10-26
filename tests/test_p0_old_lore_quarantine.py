"""P0 corrective 25.10.2026 (§3) — обезвреживание старых `lore_stories`.

Контракт (owner §3, без массовой чистки и без новых квот):

* аддитивные nullable-колонки `origin`/`status`/`excluded_from_retrieval`/
  `provenance_note`, идемпотентно, БЕЗ бампа `user_version`;
* baseline (`DatabaseService.list_lore_stories`) и legacy-ветка фасада
  (`mca_episodes.list_stories_for_retrieval`) фильтруют ОДИНАКОВО;
* точечная метка только доказанных bot-answer строк: строка остаётся в БД
  (история/поиск сохранены), но уходит из извлечения;
* `lore_graph_slice` не берёт self-origin/tentative факты в «Факты графа»;
* PG-блок `<chat_lore>` помечен «летопись/пересказ, не источник», текст
  лора не перегенерируется.

L2-метка «пересказ, не источник» в direct-payload уже закрыта A2 —
`tests/test_speech_p0_a2_memory.py` / `tests/test_direct_chat.py`
(SPEECH-P0-A2), здесь не дублируется.

TEST-LIFECYCLE: CONTRACT owner=P0-corrective-2026-10-25/
MEMORY-SELF-ECHO-REPEAT, MEMORY-PROVENANCE-ACTUAL-PATH
TEST-LIFECYCLE: REGRESSION owner=P0-corrective-2026-10-25/baseline-facade-parity
"""
import pytest

from services import lore_prompts
from services.database import (
    _LORE_SELF_ECHO_ORIGIN,
    DatabaseService,
)

CHAT_ID = -1002661910336


async def _new_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _insert_lore(db, *, story_id, story, created_at=1792873555,
                       topic_key="кв", chat_id=CHAT_ID):
    await db.db.execute(
        "INSERT INTO lore_stories (id, chat_id, topic_key, topic, story, "
        "last_ts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (int(story_id), int(chat_id), topic_key, "тема", story, 1670765170,
         int(created_at), int(created_at)))
    await db.db.commit()


async def _insert_bot_output(db, text, chat_id=CHAT_ID, sent_at=1792873555):
    await db.db.execute(
        "INSERT INTO mca_bot_outputs (bot_user_id, chat_id, tg_message_id, "
        "revision_no, sent_at, output_kind, content_text, delivery_status, "
        "created_at) VALUES (?, ?, ?, 1, ?, 'reply', ?, 'delivered', ?)",
        (1, int(chat_id), 1175257, int(sent_at), text,
         int(sent_at)))
    await db.db.commit()


def _story_of_audit_length() -> str:
    """1660 символов — длина текста id=4 из аудита P0 (identity-гард)."""
    base = ("рассказ про мемы и участников чата, мобилизацию и вагнеровцев. ")
    return (base * 40)[:1660]


class TestAdditiveProvenance:
    @pytest.mark.asyncio
    async def test_columns_added_idempotent_without_user_version_bump(self):
        db = await _new_db()
        try:
            cursor = await db.db.execute("PRAGMA user_version")
            version_before = int((await cursor.fetchone())[0])
            await _insert_lore(db, story_id=1, story="живая история чата")
            added = await db._ensure_lore_stories_provenance()
            again = await db._ensure_lore_stories_provenance()
            cols = await db._table_columns("lore_stories")
            cursor = await db.db.execute("PRAGMA user_version")
            version_after = int((await cursor.fetchone())[0])
            cursor = await db.db.execute(
                "SELECT story FROM lore_stories WHERE id = 1")
            story_after = (await cursor.fetchone())["story"]
        finally:
            await db.close()
        assert added == 0                      # свежая :memory: уже с DDL
        assert again == 0
        assert {"origin", "status", "excluded_from_retrieval",
                "provenance_note"}.issubset(cols)
        assert version_after == version_before  # аддитивно, без бампа
        assert story_after == "живая история чата"   # текст не переписан

    @pytest.mark.asyncio
    async def test_new_compile_records_origin(self):
        db = await _new_db()
        try:
            await db.upsert_lore_story(CHAT_ID, "мем", "мем", "новый рассказ",
                                       1000)
            row = await db.get_lore_story(CHAT_ID, "мем")
        finally:
            await db.close()
        assert row["origin"] == "lore_compiler"
        assert row["status"] is None
        assert int(row["excluded_from_retrieval"] or 0) == 0


class TestRetrievalFilterParity:
    @pytest.mark.asyncio
    async def test_baseline_and_facade_hide_marked_row_but_keep_it(self):
        from services.mca_episodes import list_stories_for_retrieval

        db = await _new_db()
        try:
            await _insert_lore(db, story_id=7, story="шуточная летопись",
                               created_at=1700000000)
            await db.db.execute(
                "UPDATE lore_stories SET origin = ?, status = 'rejected', "
                "excluded_from_retrieval = 1, provenance_note = 'self-echo' "
                "WHERE id = 7", (_LORE_SELF_ECHO_ORIGIN,))
            await db.db.commit()
            baseline = await db.list_lore_stories(CHAT_ID)
            facade = await list_stories_for_retrieval(db, CHAT_ID)
            raw = await db.get_lore_story(CHAT_ID, "кв")
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM lore_stories WHERE id = 7")
            count = int((await cursor.fetchone())["c"])
        finally:
            await db.close()
        assert [int(r["id"]) for r in baseline] == []
        assert [int(r["id"]) for r in facade] == []
        assert count == 1                       # строка НЕ удалена
        assert raw["story"] == "шуточная летопись"   # старый текст доступен

    @pytest.mark.asyncio
    async def test_unmarked_legacy_row_still_retrievable(self):
        from services.mca_episodes import list_stories_for_retrieval

        db = await _new_db()
        try:
            await _insert_lore(db, story_id=8, story="честная старая история",
                               created_at=1700000001, topic_key="ист")
            baseline = await db.list_lore_stories(CHAT_ID)
            facade = await list_stories_for_retrieval(db, CHAT_ID)
        finally:
            await db.close()
        assert [int(r["id"]) for r in baseline] == [8]
        assert [int(r["id"]) for r in facade] == [8]


class TestTargetedQuarantine:
    @pytest.mark.asyncio
    async def test_audited_row_marked_once_and_text_preserved(self):
        db = await _new_db()
        try:
            story = _story_of_audit_length()
            await _insert_lore(db, story_id=4, story=story)
            first = await db._quarantine_known_self_echo_lore_stories()
            cursor = await db.db.execute(
                "SELECT story, origin, status, excluded_from_retrieval, "
                "provenance_note FROM lore_stories WHERE id = 4")
            row = dict(await cursor.fetchone())
            second = await db._quarantine_known_self_echo_lore_stories()
            cursor = await db.db.execute(
                "SELECT provenance_note FROM lore_stories WHERE id = 4")
            note_after = (await cursor.fetchone())["provenance_note"]
            listed = await db.list_lore_stories(CHAT_ID)
        finally:
            await db.close()
        assert first == 1
        assert row["story"] == story            # текст не переписан
        assert row["origin"] == _LORE_SELF_ECHO_ORIGIN
        assert row["status"] == "rejected"
        assert int(row["excluded_from_retrieval"]) == 1
        assert "bot_self_echo" in row["provenance_note"]
        assert second == 0                      # идемпотентно
        assert note_after == row["provenance_note"]
        assert listed == []

    @pytest.mark.asyncio
    async def test_lcp_guard_marks_only_verified_candidate(self):
        db = await _new_db()
        try:
            story = ("бот однажды сказал: " + "мем про чат и участников " * 40)
            story = story[:900]
            await _insert_lore(db, story_id=3, story=story,
                               created_at=1700000100, topic_key="кандидат")
            await _insert_bot_output(db, story[:700],   # 700 >= 400 и >=25%
                                     sent_at=1700000100)
            marked = await db._quarantine_known_self_echo_lore_stories()
            cursor = await db.db.execute(
                "SELECT status FROM lore_stories WHERE id = 3")
            status = (await cursor.fetchone())["status"]
        finally:
            await db.close()
        assert marked == 1
        assert status == "rejected"

    @pytest.mark.asyncio
    async def test_no_false_positive_on_unrelated_or_unlisted_rows(self):
        db = await _new_db()
        try:
            # id=3 из списка, но ни один доставленный ответ не совпадает
            await _insert_lore(db, story_id=3, story="совсем другой рассказ "
                               "про рыбалку и погоду", created_at=1700000200,
                               topic_key="другое")
            await _insert_bot_output(db, "ответ бота про политику и спорт",
                                     sent_at=1700000200)
            # id=5 НЕ в списке, хотя текст дословно совпадает с ответом бота
            await _insert_lore(db, story_id=5,
                               story="ответ бота про политику и спорт",
                               created_at=1700000300, topic_key="третье")
            await _insert_bot_output(db, "ответ бота про политику и спорт",
                                     sent_at=1700000300)
            marked = await db._quarantine_known_self_echo_lore_stories()
            cursor = await db.db.execute(
                "SELECT id, status, excluded_from_retrieval FROM lore_stories "
                "ORDER BY id")
            rows = [dict(r) for r in await cursor.fetchall()]
        finally:
            await db.close()
        assert marked == 0
        assert all(r["status"] is None for r in rows)
        assert all(int(r["excluded_from_retrieval"] or 0) == 0 for r in rows)

    @pytest.mark.asyncio
    async def test_rewrite_clears_stale_selfecho_provenance(self):
        db = await _new_db()
        try:
            await _insert_lore(db, story_id=4, story=_story_of_audit_length())
            assert await db._quarantine_known_self_echo_lore_stories() == 1
            await db.upsert_lore_story(CHAT_ID, "кв", "тема",
                                       "новый честный рассказ", 1700000400)
            row = await db.get_lore_story(CHAT_ID, "кв")
            listed = await db.list_lore_stories(CHAT_ID)
        finally:
            await db.close()
        assert row["story"] == "новый честный рассказ"
        assert row["status"] is None
        assert int(row["excluded_from_retrieval"] or 0) == 0
        assert [int(r["id"]) for r in listed] == [4]


class TestGraphSliceProvenance:
    @pytest.mark.asyncio
    async def test_self_origin_and_tentative_facts_excluded(self):
        db = await _new_db()
        try:
            topic = await db.upsert_node(CHAT_ID, "Мем", "topic")
            user = await db.upsert_node(CHAT_ID, "Толян", "user")
            clean = await db.insert_graph_fact(
                CHAT_ID, "Толян родил мем", "chat_history", None,
                target_user="Толян", message_timestamp=900)
            await db.upsert_edge(topic, user, "автор", fact_id=clean)
            self_reply = await db.insert_graph_fact(
                CHAT_ID, "[Бот] заявил: Толян — клоун", "bot_self_reply",
                None, target_user="Толян", message_timestamp=910)
            await db.upsert_edge(topic, user, "связь", fact_id=self_reply)
            tentative = await db.insert_graph_fact(
                CHAT_ID, "Толян, возможно, уехал", "user_memory", None,
                target_user="Толян", message_timestamp=920)
            await db.db.execute(
                "UPDATE graph_facts SET status = 'tentative' WHERE id = ?",
                (tentative,))
            await db.db.commit()
            await db.upsert_edge(topic, user, "слух", fact_id=tentative)
            graph = await db.lore_graph_slice(CHAT_ID, "Мем")
        finally:
            await db.close()
        fact_ids = {int(f["id"]) for f in graph["facts"]}
        assert clean in fact_ids
        assert self_reply not in fact_ids      # self-echo не «факт графа»
        assert tentative not in fact_ids       # tentative не доказательство


class TestPgLoreMarker:
    def test_marker_present_and_lore_text_not_rewritten(self):
        manual = "конфа с нулевых, переезд из ВК"
        auto = "в декабре 2022-го чат обсуждал мобилизацию"
        block = lore_prompts.format_lore_block(manual, auto, 3000)
        assert block.startswith("<chat_lore>\n")
        assert lore_prompts._LORE_PROVENANCE_MARKER in block
        assert manual in block and auto in block     # текст НЕ перегенерирован
        assert block.endswith("\n</chat_lore>")
        assert len(block) <= 3000

    def test_marker_counts_against_cap(self):
        block = lore_prompts.format_lore_block("а" * 500, "", 120)
        assert len(block) <= 120
        assert lore_prompts._LORE_PROVENANCE_MARKER in block

    def test_too_small_cap_renders_no_block(self):
        assert lore_prompts.format_lore_block("текст", "авто", 10) == ""


class TestCompilerSelfEchoGuard:
    @pytest.mark.asyncio
    async def test_quarantined_story_not_fed_back_as_known_base(self):
        from services.lore_compiler_service import LoreCompilerService

        class _LLM:
            def __init__(self):
                self.calls = []

            async def generate(self, messages, temperature=0.7, chat_id=None):
                self.calls.append(messages)
                return "новый рассказ по свежему материалу"

        db = await _new_db()
        llm = _LLM()
        try:
            await _insert_lore(db, story_id=4, story=_story_of_audit_length(),
                               topic_key="мем")
            await db._quarantine_known_self_echo_lore_stories()
            await db.save_smart_message(
                1, CHAT_ID, "мем про рыбалку", None, 1800000000, "text",
                "Толян")
            result = await LoreCompilerService(db, llm).compile(CHAT_ID, "мем")
            user_payload = llm.calls[-1][-1]["content"]
        finally:
            await db.close()
        assert result["status"] == "ok"
        # помеченная «база» не подаётся модели: выдумка не пересказывается
        assert "Известная база" not in user_payload
        assert "мобилизацию и вагнеровцев" not in user_payload
        assert "мем про рыбалку" in user_payload

    @pytest.mark.asyncio
    async def test_quarantined_story_without_new_material_not_served(self):
        from services.lore_compiler_service import LoreCompilerService

        class _LLM:
            async def generate(self, messages, temperature=0.7, chat_id=None):
                raise AssertionError("LLM не должен вызываться")

        db = await _new_db()
        try:
            await _insert_lore(db, story_id=4, story=_story_of_audit_length(),
                               topic_key="мем")
            await db._quarantine_known_self_echo_lore_stories()
            result = await LoreCompilerService(db, _LLM()).compile(
                CHAT_ID, "мем")
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM lore_stories WHERE id = 4")
            still_there = int((await cursor.fetchone())["c"])
        finally:
            await db.close()
        assert result["status"] == "not_found"
        assert "исключена" in result["message"]
        assert still_there == 1        # история сохранена, не удалена
