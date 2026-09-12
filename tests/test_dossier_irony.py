"""F8 (cognition-irony-dossier-round1013) — интеграционные тесты иронии/досье.

Покрытие (spec §5/§6/§10): классификация под флагом (мемы → chat_meme,
real_facts не дублируются), keyword fail-safe, retry/skip на кривом JSON,
идемпотентность (meme_exists), изоляция мемов от RAG/get_persona_card/
get_persona_names, двухблочный рендер досье и байт-совместимость при OFF.
"""
import asyncio
import json
import time

import pytest

from config.settings import settings
from services import hot_config as hot
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.lore_cache import LoreProfile
from services.lore_worker import LoreWorker
from services.summary_aliases import AliasResolver

CHAT_ID = -1001234567890
ALLOWED_STATUS = "chat_meme"


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class FakeStore:
    @property
    def pg(self):
        return None


class FakeLLM:
    """LLM-мок: lore-текст для generate и dossier-JSON для generate_worker."""

    def __init__(self, lore_text="новый авто-лор",
                 dossier_raw='{"real_facts":[],"chat_memes":[]}',
                 dossier_sequence=None):
        self.lore_text = lore_text
        self.dossier_raw = dossier_raw
        self.dossier_sequence = list(dossier_sequence or [])
        self.generate_calls = 0
        self.worker_calls = 0
        self.worker_roles: list[str] = []

    async def generate(self, messages, temperature=None):
        self.generate_calls += 1
        return self.lore_text

    async def generate_worker(self, role, messages, *, temperature=None):
        self.worker_calls += 1
        self.worker_roles.append(role)
        if self.dossier_sequence:
            return self.dossier_sequence.pop(0)
        return self.dossier_raw


def _flag(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: enabled
        if key == "flags.irony_filter_enabled" else default)


def _worker(db, llm, aliases=None) -> LoreWorker:
    return LoreWorker(store=FakeStore(), db=db, llm=llm, bot_id=1,
                      aliases=aliases)


def _rows(*names) -> list[dict]:
    return [{"author_name": n} for n in names]


async def _memes(db, chat_id=CHAT_ID):
    cursor = await db.db.execute(
        "SELECT id, fact, target_user, status, weight, belief_meta "
        "FROM graph_facts WHERE chat_id = ? AND status = 'chat_meme' "
        "ORDER BY id", (chat_id,))
    return [dict(r) for r in await cursor.fetchall()]


class TestClassification:
    @pytest.mark.asyncio
    async def test_flag_off_skips(self, db, monkeypatch):
        _flag(monkeypatch, False)
        llm = FakeLLM(dossier_raw='{"chat_memes":[{"target":"Вася",'
                                  '"text":"мегачмо"}]}')
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["[ts] Вася: мегачмо"],
                                            _rows("Вася"))
        assert llm.worker_calls == 0
        assert await _memes(db) == []

    @pytest.mark.asyncio
    async def test_memes_written_facts_not_duplicated(self, db, monkeypatch):
        _flag(monkeypatch, True)
        llm = FakeLLM(dossier_raw=json.dumps({
            "real_facts": [{"target": "Вася", "text": "Вася живёт в Москве"}],
            "chat_memes": [{"target": "Вася", "text": "наш король"}],
        }, ensure_ascii=False))
        worker = _worker(db, llm, aliases=AliasResolver('{"10":"вася"}'))
        await worker._classify_dossier_safe(
            CHAT_ID, ["[ts] Вася: я король"], _rows("Вася"))

        memes = await _memes(db)
        assert [m["fact"] for m in memes] == ["наш король"]
        assert memes[0]["target_user"] == "вася"          # канон-алиас
        assert memes[0]["status"] == ALLOWED_STATUS
        assert memes[0]["weight"] == pytest.approx(0.4)
        # real_facts НЕ дублируем — их пишет обычный GraphRAG
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE chat_id = ? "
            "AND fact = 'Вася живёт в Москве'", (CHAT_ID,))
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_keyword_failsafe_persists_meme(self, db, monkeypatch):
        _flag(monkeypatch, True)
        # LLM ошибочно кладёт титул в real_facts — fail-safe обязан спасти.
        llm = FakeLLM(dossier_raw=json.dumps({
            "real_facts": [{"target": "Вася", "text": "повелитель грибов"}],
            "chat_memes": [],
        }, ensure_ascii=False))
        worker = _worker(db, llm, aliases=AliasResolver('{"10":"вася"}'))
        await worker._classify_dossier_safe(CHAT_ID, ["[ts] Вася: ..."],
                                            _rows("Вася"))
        memes = await _memes(db)
        assert [m["fact"] for m in memes] == ["повелитель грибов"]
        assert json.loads(memes[0]["belief_meta"])["classified_by"] == "keyword"

    @pytest.mark.asyncio
    async def test_invalid_json_retry_then_skip(self, db, monkeypatch):
        _flag(monkeypatch, True)
        llm = FakeLLM(dossier_sequence=["не json", "снова не json"])
        worker = _worker(db, llm)
        await worker._classify_dossier_safe(CHAT_ID, ["[ts] Вася: x"],
                                            _rows("Вася"))
        assert llm.worker_calls == 2
        assert llm.worker_roles == ["background", "background"]
        assert await _memes(db) == []

    @pytest.mark.asyncio
    async def test_idempotent_second_run(self, db, monkeypatch):
        _flag(monkeypatch, True)
        llm = FakeLLM(dossier_raw=json.dumps({
            "chat_memes": [{"target": "Вася", "text": "мегачмо"}]},
            ensure_ascii=False))
        worker = _worker(db, llm, aliases=AliasResolver('{"10":"вася"}'))
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        assert len(await _memes(db)) == 1

    @pytest.mark.asyncio
    async def test_items_without_target_or_text_skipped(self, db, monkeypatch):
        _flag(monkeypatch, True)
        llm = FakeLLM(dossier_raw=json.dumps({
            "chat_memes": [{"target": "", "text": "мегачмо"},
                           {"target": "Вася", "text": ""}]},
            ensure_ascii=False))
        worker = _worker(db, llm, aliases=AliasResolver('{"10":"вася"}'))
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        assert await _memes(db) == []


class TestIsolation:
    @pytest.mark.asyncio
    async def test_memes_hidden_from_readers(self, db, monkeypatch):
        _flag(monkeypatch, True)
        llm = FakeLLM(dossier_raw=json.dumps({
            "chat_memes": [{"target": "Вася", "text": "мегачмо"}]},
            ensure_ascii=False))
        worker = _worker(db, llm, aliases=AliasResolver('{"10":"вася"}'))
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))
        now = int(time.time())

        card = await db.get_persona_card(CHAT_ID, "вася", 10, now)
        assert card["facts"] == []
        assert await db.get_persona_names(CHAT_ID, now) == []
        assert await db.search_graph_facts_fts(
            CHAT_ID, '"мегачмо"*', 10, now) == []
        # memes читаются отдельным путём
        memes = await db.list_chat_memes(CHAT_ID, "вася")
        assert [m["fact"] for m in memes] == ["мегачмо"]

    @pytest.mark.asyncio
    async def test_list_chat_memes_all_and_filter(self, db, monkeypatch):
        _flag(monkeypatch, True)
        llm = FakeLLM(dossier_raw=json.dumps({
            "chat_memes": [{"target": "Вася", "text": "мегачмо"},
                           {"target": "Петя", "text": "повелитель грибов"}]},
            ensure_ascii=False))
        worker = _worker(db, llm)          # без алиасов — target как есть
        await worker._classify_dossier_safe(CHAT_ID, ["x"],
                                            _rows("Вася", "Петя"))
        assert len(await db.list_chat_memes(CHAT_ID)) == 2
        assert [m["fact"] for m in await db.list_chat_memes(CHAT_ID, "Вася")] \
            == ["мегачмо"]


class TestPersonaCardRender:
    def _service(self, db):
        return DirectChatService(memory=object(), db=db, llm=object(),
                                 aliases=AliasResolver('{"10":"вася"}'))

    @pytest.mark.asyncio
    async def test_flag_on_two_blocks(self, db, monkeypatch):
        await db.insert_graph_fact(CHAT_ID, "вася живёт в москве",
                                   "bot_direct_reply", None,
                                   target_user="вася", weight=0.7)
        _flag(monkeypatch, True)
        llm = FakeLLM(dossier_raw=json.dumps({
            "chat_memes": [{"target": "Вася", "text": "мегачмо"}]},
            ensure_ascii=False))
        worker = _worker(db, llm, aliases=AliasResolver('{"10":"вася"}'))
        await worker._classify_dossier_safe(CHAT_ID, ["x"], _rows("Вася"))

        card = await self._service(db).build_persona_card(CHAT_ID, "Вася")
        assert card.startswith("карточка: вася")
        assert "[Факты]" in card
        assert "вася живёт в москве" in card
        assert "[Локальные мемы/Ярлыки]" in card
        assert "мегачмо" in card

    @pytest.mark.asyncio
    async def test_flag_on_old_dossier_only_facts(self, db, monkeypatch):
        await db.insert_graph_fact(CHAT_ID, "вася живёт в москве",
                                   "bot_direct_reply", None,
                                   target_user="вася", weight=0.7)
        _flag(monkeypatch, True)
        card = await self._service(db).build_persona_card(CHAT_ID, "вася")
        assert "[Факты]" in card
        assert "[Локальные мемы/Ярлыки]" not in card

    @pytest.mark.asyncio
    async def test_flag_off_byte_identical_flat(self, db, monkeypatch):
        await db.insert_graph_fact(CHAT_ID, "вася живёт в москве",
                                   "bot_direct_reply", None,
                                   target_user="вася", weight=0.7)
        _flag(monkeypatch, False)
        card = await self._service(db).build_persona_card(CHAT_ID, "вася")
        assert card == ("карточка: вася\nзнаю о тебе: 1 фактов, 0 связей\n"
                        "1. вася живёт в москве")
        assert "[Факты]" not in card

    def test_default_setting_is_off(self):
        assert settings.IRONY_FILTER_ENABLED is False


class TestProfileDataclassUnchanged:
    def test_lore_profile_still_constructible(self):
        profile = LoreProfile(
            chat_id=CHAT_ID, manual_lore="", auto_lore="", auto_enabled=True,
            auto_period_hours=24, auto_window_hours=24, is_active=True,
            last_auto_at=None, updated_at="2026-09-13T00:00:00+00:00")
        assert profile.chat_id == CHAT_ID
