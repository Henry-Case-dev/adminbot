"""B08 (asap8-v6.3, REQ-B08/B08.1–B08.4) — Stories backend: истории с
содержанием, временем и участниками.

Приёмка (ТЗ B08):
  * 10 настоящих эпизодов fixtures → готовые истории (детерминированно,
    без LLM): человеческий заголовок, честная выжимка, утверждения с refs;
  * 2 независимые темы не склеены (A12);
  * merged/continuation — только по LLM-подтверждению;
  * архив: даты оригинальных событий / обнаружения / пересборки — РАЗНЫЕ
    поля; фальшивого 1970 нет (None/0/ms-нормализация, U03.2-принцип);
  * unknown outcome → «исход неизвестен»/uncertain (финал не выдуман);
  * ссылки (clickable refs по правам) + provenance не теряется;
  * участники: ключевые 3–5 + раскрытие остальных (primary/others_count);
  * пустые техэпизоды — честный insufficient_sources, НЕ готовые истории;
    safe bounded backfill/re-extract; нет источников → честное сообщение,
    оригиналы не удаляются.

TEST-LIFECYCLE: REGRESSION owner=REQ-B08/B08.1–B08.4
"""
import json

import pytest

from services import mca_gates
from services.database import DatabaseService, EPISODE_UNKNOWN_OUTCOME
from services.mca_episode_jobs import EpisodesBackfillRunner
from services.mca_episodes import (
    CONTENT_INSUFFICIENT,
    CONTENT_READY,
    NO_SOURCES_MESSAGE,
    EpisodeRepository,
    EpisodeService,
    deterministic_episode_card,
    episodes_needing_backfill,
)
from services.web_stories import (
    _episode_row,
    _norm_ts,
    _story_dto,
    _table_row,
    build_original,
    story_card,
    story_timeline,
)

CHAT = -100500          # супергруппа (t.me/c ссылки)
CHAT_DM = 42            # ЛС (archive_only — универсальной ссылки нет)
T_OLD = 1650000000      # 2022-04-15 — «архивное» событие
_NOW = 1790000000

TOPICS = [
    ("сервер переезжает в новую дата-центровую зону в пятницу", 2),
    ("квартальный отчёт собран и отправлен финансистам", 3),
    ("новый макет лендинга согласован с дизайнером", 4),
    ("бот перестал отвечать после обновления библиотеки", 5),
    ("отпуск администратора перенесён на следующую неделю", 6),
    ("настройка резервного копирования завершена успешно", 7),
    ("обсудили переезд на новый тариф хостинга", 8),
    ("починили форму обратной связи на сайте", 9),
    ("подготовили презентацию для клиента из логистики", 10),
    ("выбрали дату командного созвона в четверг", 11),
]


async def _db(tmp_path, name="b08.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add_msg(db, chat_id, user_id, text, ts, tg_message_id=None,
                   reply_to_id=None) -> int:
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, 'text', '', ?)",
        (user_id, chat_id, text, reply_to_id, ts, tg_message_id))
    await db.db.commit()
    return cursor.lastrowid


async def _count(db, sql, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


def _msg(chat_id, tg, user_id, text, ts, db_id=None, reply_to_tg=None):
    return {"chat_id": chat_id, "id": db_id, "tg_message_id": tg,
            "user_id": user_id, "text": text, "timestamp": ts,
            "reply_to_tg_message_id": reply_to_tg}


class _FakeLLM:
    """Скриптовый LLM (интерфейс `generate`); маршрутизация по канону:
    extract («экстрактор эпизодов») vs confirm («верификатор связи»)."""

    def __init__(self, extract_answers=None, confirm_answers=None):
        self.extract_answers = list(extract_answers or [])
        self.confirm_answers = list(confirm_answers or [])
        self.calls: list = []

    async def generate(self, messages, *, temperature=0.0, chat_id=None):
        self.calls.append(messages)
        system = str((messages or [{}])[0].get("content") or "")
        if "верификатор связи" in system:
            if self.confirm_answers:
                return self.confirm_answers.pop(0)
        else:
            if self.extract_answers:
                return self.extract_answers.pop(0)
        raise RuntimeError("no scripted answer")


def _confirm(related: bool, confidence: float = 0.9) -> str:
    return json.dumps({"related": related, "confidence": confidence,
                       "rationale": "test", "shared": ["сущность"]},
                      ensure_ascii=False)


# ═══ B08.1/B08.4: 10 настоящих эпизодов → готовые истории ════════════════════

class TestTenReadyStories:
    @pytest.mark.asyncio
    async def test_ten_episodes_deterministic_ready(self, tmp_path):
        """10 отдельных тем (по 3 сообщения, гэпы > 30 мин) → 10 эпизодов
        и 10 готовых историй БЕЗ LLM: заголовок — человеческий (не
        «Эпизод N»), выжимка непустая, утверждения с refs на источники."""
        db = await _db(tmp_path)
        msgs = []
        for i, (topic, author) in enumerate(TOPICS):
            base = T_OLD + i * 6 * 3600
            for j in range(3):
                msgs.append(_msg(CHAT, i * 100 + j, author if j == 0
                                 else author + 1,
                                 f"{topic} — часть {j + 1}", base + j * 60))
        svc = EpisodeService(db, llm=None, now=_NOW)
        counters = await svc.process_batch(CHAT, msgs)
        assert counters["extracted"] == 10
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 10
        await svc.assemble_stories(CHAT, _NOW)
        repo = EpisodeRepository(db)
        stories = await repo.list_stories(CHAT, limit=50)
        assert len(stories) == 10      # 10 независимых тем → 10 историй
        for row in stories:
            dto = _story_dto(row)
            assert dto["content_status"] == CONTENT_READY
            assert dto["display_title"]
            assert not dto["display_title"].startswith("Эпизод ")
            assert dto["summary"], "готовая история без пустой выжимки"
            assert dto["claims"], "детерминированные факты обязаны быть"
            for claim in dto["claims"]:
                assert claim["refs"], "утверждение без источника запрещено"
        await db.close()

    @pytest.mark.asyncio
    async def test_deterministic_card_no_invention(self, tmp_path):
        """Детерминированная карточка: заголовок из ключевого сообщения,
        факты = сами сообщения, никаких выдуманных финалов/имён."""
        seg = [_msg(CHAT, 1, 7, "переезжаем на новый сервер в пятницу",
                    T_OLD),
               _msg(CHAT, 2, 9, "ок, я подготовлю бэкап заранее", T_OLD + 60),
               _msg(CHAT, 3, 7, "ок", T_OLD + 120)]   # <12 симв. — не факт
        card = deterministic_episode_card(seg)
        assert "сервер" in card["title"]
        assert not card["title"].startswith("Эпизод")
        assert len(card["claims"]) == 2      # «ок» короткое — не утверждение
        assert card["claims"][0]["refs"] == [f"{CHAT}:tg:1"]


def _extract(title: str, summary: str, refs, participants=("7",),
             outcome_known: bool = False, outcome=None) -> str:
    return json.dumps({
        "title": title, "summary": summary,
        "participants": list(participants),
        "claims": [{"text": f"факт: {title}", "refs": list(refs)}],
        "outcome_known": outcome_known, "outcome": outcome,
        "open_questions": [], "unknown": [], "multi_topic": False,
    }, ensure_ascii=False)


# ═══ B08.2/A12: 2 независимые темы не склеены ═══════════════════════════════

class TestIndependentTopics:
    @pytest.mark.asyncio
    async def test_two_topics_two_stories_no_time_merge(self, tmp_path):
        """Две темы параллельно (разные авторы, гэп > soft, без reply) —
        НЕ склеиваются в одну историю ни по времени, ни по participants."""
        db = await _db(tmp_path)
        msgs = [
            _msg(CHAT, 1, 7, "проект альфа: созвон в пятницу переносится",
                 T_OLD),
            _msg(CHAT, 2, 7, "проект альфа: готовлю повестку заранее",
                 T_OLD + 60),
            _msg(CHAT, 3, 9, "коты и усы: фотоконкурс стартовал в чате",
                 T_OLD + 700),
            _msg(CHAT, 4, 9, "коты и усы: голосование до конца недели",
                 T_OLD + 760),
        ]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        await svc.assemble_stories(CHAT, _NOW)
        repo = EpisodeRepository(db)
        stories = await repo.list_stories(CHAT, limit=50)
        assert len(stories) == 2       # независимые темы — отдельные истории
        titles = {_story_dto(s)["display_title"] for s in stories}
        assert any("альфа" in t for t in titles)
        assert any("коты" in t for t in titles)
        await db.close()

    @pytest.mark.asyncio
    async def test_continuation_requires_llm_confirmation(self, tmp_path):
        """Похожая тема через неделю — БЕЗ LLM-подтверждения связь не
        склеивается (fail-closed, ложная склейка запрещена)."""
        db = await _db(tmp_path)
        msgs = [
            _msg(CHAT, 1, 7, "переезжаем на новый сервер в пятницу", T_OLD),
            _msg(CHAT, 2, 7, "сервер переезд: всё прошло по плану",
                 T_OLD + 7 * 86400),
        ]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        await svc.assemble_stories(CHAT, _NOW)
        repo = EpisodeRepository(db)
        assert len(await repo.list_stories(CHAT, limit=50)) == 2
        await db.close()

    @pytest.mark.asyncio
    async def test_merged_continuation_confirmed(self, tmp_path):
        """merged/continuation: LLM-подтверждение → одна история из двух
        эпизодов, обе даты событий сохранены."""
        db = await _db(tmp_path)
        msgs = [
            _msg(CHAT, 1, 7, "переезжаем на новый сервер в пятницу", T_OLD),
            _msg(CHAT, 2, 7, "сервер переезжает: завершено без потерь",
                 T_OLD + 2 * 86400),
        ]
        llm = _FakeLLM(
            extract_answers=[
                _extract("Переезд сервера: старт",
                         "Начали переезд сервера", [f"{CHAT}:tg:1"]),
                _extract("Переезд сервера: завершение",
                         "Сервер успешно переехал", [f"{CHAT}:tg:2"]),
            ],
            confirm_answers=[_confirm(True)])
        svc = EpisodeService(db, llm=llm, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        await svc.assemble_stories(CHAT, _NOW)
        repo = EpisodeRepository(db)
        stories = await repo.list_stories(CHAT, limit=50)
        assert len(stories) == 1
        eps = await repo.story_episode_ids(stories[0]["story_id"])
        assert len(eps) == 2
        dto = _story_dto(stories[0])
        assert dto["event_start_ts"] == T_OLD
        assert dto["event_end_ts"] == T_OLD + 2 * 86400
        await db.close()


# ═══ B08.1: три РАЗНЫЕ даты; архив; U03.2-принцип (без 1970) ═════════════════

class TestArchiveDates:
    @pytest.mark.asyncio
    async def test_event_vs_discovery_vs_rebuild_separate(self, tmp_path):
        """Архив: событие 2022 года, обнаружение и пересборка — сейчас;
        три разных поля в карточке."""
        db = await _db(tmp_path)
        msgs = [_msg(CHAT, 1, 7, "архивное событие: старый чат переехал",
                     T_OLD)]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        repo = EpisodeRepository(db)
        await svc.assemble_stories(CHAT, _NOW)
        story = (await repo.list_stories(CHAT, limit=5))[0]
        dto = _story_dto(story)
        assert dto["event_start_ts"] == T_OLD       # оригинальное событие
        assert dto["discovered_at"] == _NOW          # обнаружение
        assert dto["rebuilt_at"] == _NOW             # пересборка (обновление)
        # повторная сборка двигает rebuilt_at, но не event/discovered
        await svc.assemble_stories(CHAT, _NOW + 100)
        fresh = await repo.get_story(story["story_id"])
        dto2 = _story_dto(fresh)
        assert dto2["event_start_ts"] == T_OLD
        assert dto2["discovered_at"] == _NOW
        assert dto2["rebuilt_at"] == _NOW            # unchanged → версия та же
        await db.close()

    def test_norm_ts_no_fake_1970(self):
        """0/мусор → None (честное «нет данных», не 22.01.1970);
        миллисекунды → секунды."""
        assert _norm_ts(0) is None
        assert _norm_ts(None) is None
        assert _norm_ts(-5) is None
        assert _norm_ts("мусор") is None
        assert _norm_ts(1650000000000) == 1650000000      # ms → sec
        assert _norm_ts(1650000000) == 1650000000

    @pytest.mark.asyncio
    async def test_episode_without_ts_not_1970(self, tmp_path):
        """Эпизод с нулевыми таймстампами источников → карточка без
        фальшивой даты 1970 (event_* = None)."""
        db = await _db(tmp_path)
        repo = EpisodeRepository(db)
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Обсуждение (2 сообщ.)", summary="выжимка",
            participants=["7"], claims=[], event_start=None, event_end=None,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=[f"{CHAT}:tg:1"], seg_key="s1",
            extraction_version="x", now=_NOW)
        assert episode_id
        row = await repo.get_episode(episode_id)
        dto = _episode_row(row)
        assert dto["event_start_ts"] is None
        assert dto["event_end_ts"] is None
        assert dto["discovered_at"] == _NOW
        await db.close()


# ═══ B08.1: unknown outcome — финал не выдумывается ══════════════════════════

class TestUnknownOutcome:
    @pytest.mark.asyncio
    async def test_unknown_outcome_is_honest(self, tmp_path):
        db = await _db(tmp_path)
        msgs = [_msg(CHAT, 1, 7, "ждём ответа провайдера по инциденту",
                     T_OLD)]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        await svc.assemble_stories(CHAT, _NOW)
        repo = EpisodeRepository(db)
        story = (await repo.list_stories(CHAT, limit=5))[0]
        dto = _story_dto(story)
        assert dto["outcome"] == EPISODE_UNKNOWN_OUTCOME
        assert dto["state"] == "uncertain"
        # честный статус не красится в success (V05): ready ≠ закрытый финал
        assert dto["content_status"] == CONTENT_READY
        assert dto["display_summary"]
        await db.close()


# ═══ B08.1/B08.4: ссылки по правам + provenance не теряется ══════════════════

class TestRefsAndProvenance:
    @pytest.mark.asyncio
    async def test_timeline_refs_supergroup_links(self, tmp_path):
        """Супергруппа: утверждения хронологии имеют refs с t.me/c
        ссылками (clickable refs); ЛС-чат — archive_only без ссылки."""
        db = await _db(tmp_path)
        await _add_msg(db, CHAT, 7, "переезжаем на новый сервер в пятницу",
                       T_OLD, tg_message_id=10)
        await _add_msg(db, CHAT_DM, 7, "личное: готовлю бэкап к переезду",
                       T_OLD, tg_message_id=11)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 10, 7,
                                            "переезжаем на новый сервер "
                                            "в пятницу", T_OLD)])
        await svc.process_batch(CHAT_DM, [_msg(CHAT_DM, 11, 7,
                                               "личное: готовлю бэкап к "
                                               "переезду", T_OLD)])
        repo = EpisodeRepository(db)
        await svc.assemble_stories(CHAT, _NOW)
        await svc.assemble_stories(CHAT_DM, _NOW)
        story = (await repo.list_stories(CHAT, limit=5))[0]
        card = await story_card(db, CHAT, story["story_id"])
        timeline = card["timeline"]
        assert timeline, "хронология карточки пуста"
        entry = timeline[0]
        assert entry["text"]
        ref = entry["refs"][0]
        assert ref["message_key"] == f"{CHAT}:tg:10"
        assert ref["url"] and ref["url"].startswith("https://t.me/c/")
        story_dm = (await repo.list_stories(CHAT_DM, limit=5))[0]
        card_dm = await story_card(db, CHAT_DM, story_dm["story_id"])
        ref_dm = card_dm["timeline"][0]["refs"][0]
        assert ref_dm["url"] is None          # ЛС — archive_only, не выдумываем
        assert card_dm["original"]["state"] == "archive_only"
        await db.close()

    @pytest.mark.asyncio
    async def test_provenance_not_lost(self, tmp_path):
        """Детерминированный путь сохраняет provenance: SourceRef эпизода
        + EvidenceLink на сообщение; refs утверждений = ключи источников."""
        db = await _db(tmp_path)
        await _add_msg(db, CHAT, 7, "переезжаем на новый сервер в пятницу",
                       T_OLD, tg_message_id=10)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, [_msg(CHAT, 10, 7,
                                            "переезжаем на новый сервер "
                                            "в пятницу", T_OLD)])
        repo = EpisodeRepository(db)
        episode = (await repo.list_episodes(CHAT, limit=5))[0]
        claims = json.loads(episode["claims_json"])
        assert claims and claims[0]["refs"] == [f"{CHAT}:tg:10"]
        refs = await _count(
            db, "SELECT COUNT(*) FROM mca_source_refs WHERE entity_type = "
                "'episode'")
        links = await _count(
            db, "SELECT COUNT(*) FROM mca_evidence_links")
        assert refs >= 1 and links >= 1
        keys = json.loads(episode["message_keys_json"])
        original = build_original(CHAT, keys)
        assert original["state"] == "available"
        assert original["links"][0]["tg_message_id"] == 10
        await db.close()

    @pytest.mark.asyncio
    async def test_timeline_chronological_order(self, tmp_path):
        db = await _db(tmp_path)
        msgs = [
            _msg(CHAT, 1, 7, "первый факт: начало переезда сервера", T_OLD),
            _msg(CHAT, 2, 9, "второй факт: бэкапы сняты полностью",
                 T_OLD + 600),
        ]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        repo = EpisodeRepository(db)
        episodes = await repo.list_episodes(CHAT, limit=10)
        entries = story_timeline(CHAT, episodes)
        assert len(entries) == 2
        assert entries[0]["ts"] <= entries[1]["ts"]
        await db.close()


# ═══ B08.2: участники — ключевые 3–5 + раскрытие остальных ═══════════════════

class TestParticipants:
    @pytest.mark.asyncio
    async def test_seven_participants_primary_five_plus_others(self,
                                                               tmp_path):
        db = await _db(tmp_path)
        msgs = [
            _msg(CHAT, 1, 2, "планируем переезд серверного оборудования",
                 T_OLD),
            _msg(CHAT, 2, 3, "сеть готова к переезду, порты открыты",
                 T_OLD + 30),
            _msg(CHAT, 3, 4, "бэкапы проверены, целостность подтверждена",
                 T_OLD + 60),
            _msg(CHAT, 4, 5, "мониторинг переведён на новый стенд",
                 T_OLD + 90),
            _msg(CHAT, 5, 6, "доступы для дежурных выданы заранее",
                 T_OLD + 120),
            _msg(CHAT, 6, 7, "документация обновлена по итогам проверки",
                 T_OLD + 150),
            _msg(CHAT, 7, 8, "ок", T_OLD + 180),
        ]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        await svc.assemble_stories(CHAT, _NOW)
        repo = EpisodeRepository(db)
        story = (await repo.list_stories(CHAT, limit=5))[0]
        dto = _story_dto(story)
        assert len(dto["primary_participants"]) == 5
        assert dto["others_count"] == 2
        assert len(dto["participants"]) == 7      # раскрытие остальных
        row = await repo.get_story(story["story_id"])
        table = _table_row(row)
        assert table["primary_participants"] == dto["primary_participants"]
        assert table["others_count"] == 2
        await db.close()

    @pytest.mark.asyncio
    async def test_few_participants_all_primary(self, tmp_path):
        db = await _db(tmp_path)
        msgs = [
            _msg(CHAT, 1, 2, "обсуждаем дату командного созвона", T_OLD),
            _msg(CHAT, 2, 3, "четверг в три часа всем подходит", T_OLD + 30),
        ]
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.process_batch(CHAT, msgs)
        repo = EpisodeRepository(db)
        episode = (await repo.list_episodes(CHAT, limit=5))[0]
        dto = _episode_row(episode)
        assert len(dto["primary_participants"]) == 2
        assert dto["others_count"] == 0
        await db.close()

    @pytest.mark.asyncio
    async def test_participant_order_by_involvement(self, tmp_path):
        from services.mca_episodes import participants_by_involvement
        seg = [_msg(CHAT, 1, 2, "a", T_OLD), _msg(CHAT, 2, 2, "b", T_OLD + 1),
               _msg(CHAT, 3, 3, "c", T_OLD + 2), _msg(CHAT, 4, 2, "d",
                                                      T_OLD + 3)]
        assert participants_by_involvement(seg) == ["2", "3"]


# ═══ B08.2/B08.3: пустые техэпизоды + safe bounded backfill ══════════════════

class TestInsufficientSourcesAndBackfill:
    async def _seed_empty_episode(self, db, *, with_sources: bool):
        repo = EpisodeRepository(db)
        keys = [f"{CHAT}:tg:10", f"{CHAT}:tg:11"] if with_sources else []
        episode_id = await repo.insert_episode(
            chat_id=CHAT, title="Эпизод 1780000000", summary="",
            participants=["7"], claims=[], event_start=T_OLD, event_end=T_OLD,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=keys, seg_key="legacy-s1",
            extraction_version="episodes_extract-1", now=_NOW)
        return episode_id

    @pytest.mark.asyncio
    async def test_empty_episode_is_not_ready_story(self, tmp_path):
        """Пустая техзапись (pending/unresolved) НЕ готовая история:
        честный insufficient_sources + честное отображение, заглушка
        «Эпизод 1780…» не показывается как факт."""
        db = await _db(tmp_path)
        episode_id = await self._seed_empty_episode(db, with_sources=True)
        repo = EpisodeRepository(db)
        row = await repo.get_episode(episode_id)
        dto = _episode_row(row)
        assert dto["content_status"] == CONTENT_INSUFFICIENT
        assert dto["display_title"] == "Не удалось восстановить сюжет"
        assert dto["display_summary"] != "Краткое содержание: неизвестно"
        assert dto["display_summary"]
        await db.close()

    @pytest.mark.asyncio
    async def test_no_sources_message(self, tmp_path):
        """Совсем без ключей → «Не удалось восстановить сюжет: нет
        источников» (не «история №17800000»)."""
        db = await _db(tmp_path)
        episode_id = await self._seed_empty_episode(db, with_sources=False)
        repo = EpisodeRepository(db)
        row = await repo.get_episode(episode_id)
        dto = _episode_row(row)
        assert dto["content_status"] == CONTENT_INSUFFICIENT
        await db.close()
        from services.web_stories import _display_fields
        fields = _display_fields(row, has_sources=False)
        assert fields["display_summary"] == NO_SOURCES_MESSAGE

    @pytest.mark.asyncio
    async def test_bounded_backfill_restores_content(self, tmp_path):
        """Safe bounded backfill: пустой эпизод с живыми источниками
        детерминированно пересобирается (LLM нет — факты из сообщений),
        история обновляется; оригиналы не удаляются."""
        db = await _db(tmp_path)
        await _add_msg(db, CHAT, 7, "переезжаем на новый сервер в пятницу",
                       T_OLD, tg_message_id=10)
        await _add_msg(db, CHAT, 7, "бэкапы сняты и проверены полностью",
                       T_OLD + 60, tg_message_id=11)
        episode_id = await self._seed_empty_episode(db, with_sources=True)
        msgs_total_before = await _count(
            db, "SELECT COUNT(*) FROM smart_messages")
        candidates = await episodes_needing_backfill(db, CHAT)
        assert [str(e["episode_id"]) for e in candidates] == [episode_id]
        runner = EpisodesBackfillRunner(db, llm=None)
        counters = await runner.process_content_backfill(CHAT)
        assert counters["candidates"] == 1
        assert counters["reextracted"] == 1
        assert counters["no_sources"] == 0
        repo = EpisodeRepository(db)
        row = await repo.get_episode(episode_id)
        dto = _episode_row(row)
        assert dto["content_status"] == CONTENT_READY
        assert dto["summary"]
        assert dto["claims"]
        assert msgs_total_before == await _count(
            db, "SELECT COUNT(*) FROM smart_messages")
        await db.close()

    @pytest.mark.asyncio
    async def test_backfill_without_sources_keeps_honest(self, tmp_path):
        """Источников нет → честный no_sources: запись НЕ удаляется, НЕ
        выдумывается; candidates=0 для эпизодов без ключей."""
        db = await _db(tmp_path)
        episode_id = await self._seed_empty_episode(db, with_sources=False)
        candidates = await episodes_needing_backfill(db, CHAT)
        assert candidates == []      # без ключей re-extract невозможен
        repo = EpisodeRepository(db)
        runner = EpisodesBackfillRunner(db, llm=None)
        counters = await runner.process_content_backfill(CHAT)
        assert counters["candidates"] == 0
        assert await repo.get_episode(episode_id) is not None
        await db.close()

    @pytest.mark.asyncio
    async def test_backfill_sources_deleted_honest_skip(self, tmp_path):
        """Ключи есть, но сообщения удалены → no_sources, эпизод остаётся
        честным insufficient_sources (не удаляется, не выдумывается)."""
        db = await _db(tmp_path)
        episode_id = await self._seed_empty_episode(db, with_sources=True)
        runner = EpisodesBackfillRunner(db, llm=None)
        counters = await runner.process_content_backfill(CHAT)
        assert counters["no_sources"] == 1
        assert counters["reextracted"] == 0
        repo = EpisodeRepository(db)
        row = await repo.get_episode(episode_id)
        assert row is not None
        assert _episode_row(row)["content_status"] == CONTENT_INSUFFICIENT
        await db.close()

    @pytest.mark.asyncio
    async def test_backfill_disabled_gate(self, tmp_path, monkeypatch):
        """Kill-switch OFF → backfill не пишет ничего (паритет baseline)."""
        monkeypatch.setattr(mca_gates, "episodes_enabled", lambda: False)
        db = await _db(tmp_path)
        runner = EpisodesBackfillRunner(db, llm=None)
        counters = await runner.process_content_backfill(CHAT)
        assert counters.get("disabled") is True
        assert await _count(db, "SELECT COUNT(*) FROM mca_episodes") == 0
        await db.close()

    @pytest.mark.asyncio
    async def test_story_from_empty_episode_not_ready(self, tmp_path):
        """История из одного пустого эпизода — тоже не готовая: сборка
        даёт insufficient_sources (не «успешно составленная история»)."""
        db = await _db(tmp_path)
        episode_id = await self._seed_empty_episode(db, with_sources=False)
        svc = EpisodeService(db, llm=None, now=_NOW)
        await svc.assemble_stories(CHAT, _NOW)
        repo = EpisodeRepository(db)
        stories = await repo.list_stories(CHAT, limit=5)
        assert len(stories) == 1
        dto = _story_dto(stories[0])
        assert dto["content_status"] == CONTENT_INSUFFICIENT
        assert dto["display_title"] == "Не удалось восстановить сюжет"
        await db.close()
