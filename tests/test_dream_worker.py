"""Раунд 9 (AGI Memory, spec §3.4, T-824/T-825, G2) — DreamWorker «сон».

Покрытие: кандидаты/watermark-resume, жадная кластеризация (D-4),
пороги повторяемости/Σ-importance, дистилляция (успех/UNCHANGED/ошибка →
watermark не двигается), supersede по якорному токену (D-6), бюджеты в сутки
(дистилляции/токены + day-сброс), окно 4–6 local (window_skip),
protected-гейт, регистрация джоба по флагу (ручной run_once не зависит от
флага — spec §3.6.2). LLM замокан; окно/день — подменой _local_hour/_now_ts.
"""
import asyncio
import json

import pytest

from services import hot_config as hot
from services.database import DatabaseService
from services.dream_prompts import DREAM_DISTILL_PROMPT
from services.dream_worker import (
    DreamWorker,
    greedy_cluster_facts,
    significant_tokens,
)

CHAT_ID = -100


@pytest.fixture
def db():
    """In-memory SQLite (миграции v1..v8) — база для всех кейсов."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _hot_cache(monkeypatch, values: dict | None = None):
    """hot-кэш-заглушка (прецедент test_lore_worker): заданные ключи;
    отсутствующие — settings-дефолты (hot.get(key, default))."""
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeLLM:
    """Мок облачного LLMClient: очередь ответов (строка или исключение)."""

    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []                     # [(messages, temperature), ...]

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return '{"beliefs":[]}'


def _worker(db, llm, *, values=None, monkeypatch=None):
    worker = DreamWorker(db, memory=None, llm=llm)
    if values:
        _hot_cache(monkeypatch, values)
    return worker


async def _add_fact(db, text, *, origin="chat_history", importance=4):
    """Факт чата с явной важностью (свежий created_at)."""
    return await db.insert_graph_fact(CHAT_ID, text, origin, None,
                                      importance=importance)


async def _add_batch(db, n, topic_words, importance=4):
    """n фактов одной темы (общие значимые слова ≥2 между соседями)."""
    ids = []
    for i in range(n):
        ids.append(await _add_fact(
            db, f"{topic_words[0]} {topic_words[1]} в {i + 1} раз "
                f"{topic_words[2]} подряд"))
    return ids


async def _belief_rows(db):
    cursor = await db.db.execute(
        "SELECT id, fact, origin, kind, importance, weight, source_ids, "
        "belief_meta, status, expires_at, supersedes, created_at "
        "FROM graph_facts WHERE kind = 'belief' ORDER BY id")
    return await cursor.fetchall()


_ANS_A = ('{"beliefs":[{"text":"вася всегда платит за всех в баре",'
          '"evidence":[1,2,3]}]}')
_ANS_B = ('{"beliefs":[{"text":"петя перестал приходить по четвергам",'
          '"evidence":[1,2,3]}]}')


class TestClusteringUnits:
    def test_significant_tokens_words_len5_casefold(self):
        assert significant_tokens("Вася переехал в Москву") == \
            ["переехал", "москву"]
        assert significant_tokens("и в на не по") == []

    def test_greedy_clusters_by_overlap(self):
        rows = [
            {"id": 1, "fact": "вася переехал в москву"},
            {"id": 2, "fact": "вася переехал в москву и купил квартиру"},
            {"id": 3, "fact": "петя купил новую машину"},
            {"id": 4, "fact": "петя купил новую машину и продал старую"},
            {"id": 5, "fact": "ольга связала свитер"},
        ]
        clusters = greedy_cluster_facts(rows)
        members = [[r["id"] for r in c] for c in clusters]
        assert members == [[1, 2], [3, 4], [5]]   # первый кластер с совпадением

    def test_participant_name_is_overlap_term(self):
        """D-4: имя участника (extra_terms) — значимый токен для кластера."""
        rows = [
            {"id": 1, "fact": "иван участвовал в марафоне в прошлом году"},
            {"id": 2, "fact": "иван пробежал марафон в этом сезоне"},
        ]
        assert len(greedy_cluster_facts(rows)) == 2          # без имени — рознь
        clusters = greedy_cluster_facts(rows, overlap_tokens=1,
                                        extra_terms=["иван"])
        assert [[r["id"] for r in c] for c in clusters] == [[1, 2]]


class TestTickRegistration:
    @pytest.mark.asyncio
    async def test_job_registered_only_when_flag_on(self, db, monkeypatch):
        _hot_cache(monkeypatch, {"memory.dream_enabled": True})
        worker = DreamWorker(db, llm=_FakeLLM())
        try:
            worker.start()
            assert worker._scheduler.running
            assert worker._scheduler.get_job(DreamWorker.JOB_DREAM_ID) \
                is not None
        finally:
            await worker.stop()

    @pytest.mark.asyncio
    async def test_flag_off_no_job_and_run_once_still_works(self, db,
                                                            monkeypatch):
        """Флаг off → джоб не регистрируется; РУЧНОЙ run_once работает
        (spec §3.6.2: ручной запуск не зависит от flags.dream_enabled)."""
        _hot_cache(monkeypatch, {"memory.dream_enabled": False})
        llm = _FakeLLM(_ANS_A)
        worker = DreamWorker(db, llm=llm)
        worker.start()                       # off → no-op
        assert not worker._scheduler.running
        assert worker._scheduler.get_job(DreamWorker.JOB_DREAM_ID) is None
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert res["distilled"] == 1
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_tick_trigger_is_minute_based(self, db, monkeypatch):
        """Фикс-раунд (major-6/D-20): триггер МИНУТНЫЙ
        (memory.dream_tick_minutes=60) — первый тик внутри окна [4, 6) local
        даёт дистилляцию при старте воркера в любое время суток (водяной
        знак вне окна не двигается, D-5/D-13)."""
        import datetime as _dt
        _hot_cache(monkeypatch, {"memory.dream_enabled": True})
        worker = DreamWorker(db, llm=_FakeLLM())
        try:
            worker.start()
            job = worker._scheduler.get_job(DreamWorker.JOB_DREAM_ID)
            assert job is not None
            assert job.trigger.interval == _dt.timedelta(minutes=60)
        finally:
            await worker.stop()


class TestDistillation:
    @pytest.mark.asyncio
    async def test_cluster_distilled_to_belief(self, db, monkeypatch):
        llm = _FakeLLM(_ANS_A)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        ids = await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert res["distilled"] == 1
        assert len(llm.calls) == 1
        assert llm.calls[0][1] == 0.3        # temperature дистилляции
        beliefs = await _belief_rows(db)
        assert len(beliefs) == 1
        b = beliefs[0]
        assert b["kind"] == "belief"
        assert b["origin"] == "derived_belief"
        assert b["fact"] == "вася всегда платит за всех в баре"
        assert b["importance"] == 10         # min(10, 4+4+4)
        assert b["weight"] == 0.6
        assert b["status"] == "confirmed"
        assert b["expires_at"] is None
        assert b["supersedes"] is None
        assert json.loads(b["source_ids"]) == sorted(ids)
        meta = json.loads(b["belief_meta"])
        assert meta["sources_count"] == 3
        assert meta["cluster_id"] == 1
        # аудит: run + distilled
        cursor = await db.db.execute(
            "SELECT kind, status FROM memory_dream_log ORDER BY id")
        rows = await cursor.fetchall()
        assert [(r["kind"], r["status"]) for r in rows] == \
            [("run", "ok"), ("distilled", "ok")]
        # watermark двинулся до MAX обработанного
        state = await db.get_dream_state(CHAT_ID)
        assert state["last_processed_fact_id"] == max(ids)
        assert state["last_run_at"] > 0

    @pytest.mark.asyncio
    async def test_watermark_resume_no_redistill(self, db, monkeypatch):
        """Watermark-resume: второй тик берёт только новые факты; старые
        не передистиллируются."""
        llm = _FakeLLM(_ANS_A, _ANS_B)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        ids_a = await _add_batch(db, 3, ("вася", "платит", "в баре"))
        await worker.run_once(CHAT_ID)
        assert len(llm.calls) == 1
        ids_b = await _add_batch(db, 3, ("петя", "ходит", "по четвергам"))
        res2 = await worker.run_once(CHAT_ID)
        assert res2["distilled"] == 1
        assert len(llm.calls) == 2           # второй вызов — новая тема
        beliefs = await _belief_rows(db)
        assert len(beliefs) == 2
        state = await db.get_dream_state(CHAT_ID)
        assert state["last_processed_fact_id"] == max(ids_a + ids_b)
        # без новых фактов третий тик — no-op (водяной знак не откатывается)
        res3 = await worker.run_once(CHAT_ID)
        assert res3["distilled"] == 0 and res3["chats"] == 1
        assert len(llm.calls) == 2

    @pytest.mark.asyncio
    async def test_cluster_below_thresholds_not_distilled(self, db,
                                                          monkeypatch):
        """Пороги: членов < repeat ИЛИ Σ importance < порога — кластер не
        идёт в дистилляцию (LLM не вызывается), watermark двигается."""
        llm = _FakeLLM(_ANS_A, _ANS_B)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        # тема X: 3 факта важностью 3 (Σ 9 < 12); тема Y: 2 факта (членов 2 < 3)
        for i in range(3):
            await _add_fact(db, f"петя смотрит футбол в {i + 1} туре",
                            importance=3)
        for i in range(2):
            await _add_fact(db, f"ольга вяжет крючком свитер {i + 1} раз",
                            importance=7)
        res = await worker.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert res["distilled"] == 0
        assert res["clusters"] == 0
        assert llm.calls == []               # ни одного LLM-вызова
        state = await db.get_dream_state(CHAT_ID)
        assert state is not None             # факты «отобраны» — watermark ест
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_unchanged_response_skips_and_moves_watermark(
            self, db, monkeypatch):
        llm = _FakeLLM("UNCHANGED")
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        ids = await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["unchanged"] == 1
        assert res["distilled"] == 0
        beliefs = await _belief_rows(db)
        assert beliefs == []
        cursor = await db.db.execute(
            "SELECT kind, status FROM memory_dream_log ORDER BY id")
        rows = await cursor.fetchall()
        assert [(r["kind"], r["status"]) for r in rows] == \
            [("run", "ok"), ("skipped", "unchanged")]
        state = await db.get_dream_state(CHAT_ID)
        assert state["last_processed_fact_id"] == max(ids)

    @pytest.mark.asyncio
    async def test_llm_error_freezes_watermark_then_recovers(self, db,
                                                             monkeypatch):
        """LLM-ошибка: лог error, watermark НЕ двигается мимо упавшего
        кластера; следующий тик повторяет кластер (fail-open)."""
        llm = _FakeLLM(RuntimeError("llm down"), _ANS_A)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        ids = await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["errors"] == 1
        assert res["distilled"] == 0
        assert len(llm.calls) == 1
        cursor = await db.db.execute(
            "SELECT kind, status FROM memory_dream_log ORDER BY id")
        rows = await cursor.fetchall()
        assert [(r["kind"], r["status"]) for r in rows] == \
            [("run", "ok"), ("error", "error")]
        state = await db.get_dream_state(CHAT_ID)
        # watermark заморожен ДО упавшего кластера (min id - 1)
        assert state["last_processed_fact_id"] == min(ids) - 1
        # повторный прогон (LLM «ожил») — тот же кластер дистиллируется
        res2 = await worker.run_once(CHAT_ID)
        assert res2["distilled"] == 1
        beliefs = await _belief_rows(db)
        assert len(beliefs) == 1
        state = await db.get_dream_state(CHAT_ID)
        assert state["last_processed_fact_id"] == max(ids)

    @pytest.mark.asyncio
    async def test_belief_written_via_fresh_chat_week_window(self, db,
                                                             monkeypatch):
        """Чат без dream_state: кандидаты — только окно прогрева (168ч);
        старый факт (за пределами окна) в тик НЕ попадает."""
        llm = _FakeLLM(_ANS_A)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        old = await _add_fact(db, "вася платит за всех в баре в прошлом году")
        import time as _time
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ? WHERE id = ?",
            (int(_time.time()) - 200 * 3600, old))
        await db.db.commit()
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        assert len(llm.calls) == 1


class TestWindowAndBudgets:
    @pytest.mark.asyncio
    async def test_tick_outside_window_window_skip_no_watermark(
            self, db, monkeypatch):
        """Вне окна 4–6 (D-5): тик делает отбор, дистилляции window_skip,
        watermark НЕ двигается (повтор в след. окне)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 10)
        llm = _FakeLLM(_ANS_A)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        ids = await _add_batch(db, 3, ("вася", "платит", "в баре"))
        stats = await worker._run(manual=False, only_chat=CHAT_ID)
        assert stats["window_skips"] == 1
        assert stats["distilled"] == 0
        assert llm.calls == []               # денег вне окна не тратим
        assert await db.get_dream_state(CHAT_ID) is None   # watermark не тронут
        cursor = await db.db.execute(
            "SELECT kind, status FROM memory_dream_log ORDER BY id")
        rows = await cursor.fetchall()
        assert [(r["kind"], r["status"]) for r in rows] == \
            [("run", "ok"), ("skipped", "window_skip")]

    @pytest.mark.asyncio
    async def test_manual_run_ignores_window(self, db, monkeypatch):
        """Ручной run_once окно 4–6 игнорирует (D-5)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 10)
        llm = _FakeLLM(_ANS_A)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_distillations_budget_per_day_and_reset(self, db,
                                                          monkeypatch):
        """Бюджет дистилляций/сутки (§3.4.4): после «почти у предела»
        (остаток < 5) тик завершается заранее; «новый день» — счётчик
        обнуляется (по run_at >= начало новых суток)."""
        import services.dream_worker as dw
        # лимит 6: near-limit (< 5 остатка) срабатывает после 2 дистилляций
        _hot_cache(monkeypatch,
                   {"memory.dream_distillations_per_day": 6})
        llm = _FakeLLM(_ANS_A, _ANS_B, _ANS_A, _ANS_B)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        # три кластера в одном чате (по 3 факта, importance 4)
        for topic in (("вася", "платит", "в баре"),
                      ("петя", "ходит", "по четвергам"),
                      ("ольга", "вяжет", "свитер")):
            await _add_batch(db, 3, topic)
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 2
        assert res["budget_stop"] is True
        assert len(llm.calls) == 2           # третий кластер не пошёл
        assert await db.get_dream_state(CHAT_ID) is None   # watermark нет
        # «новый день»: счётчик (kind='distilled', run_at>=start суток) сброшен
        # (не сбросься — день2 остановился бы сразу на остатке 4 < 5)
        real_now = dw._now_ts()
        monkeypatch.setattr(dw, "_now_ts", lambda: real_now + 3 * 86400)
        res2 = await worker.run_once(CHAT_ID)
        assert res2["distilled"] == 2
        assert res2["budget_stop"] is True
        assert len(llm.calls) == 4

    @pytest.mark.asyncio
    async def test_tokens_budget_near_limit_stops_after_first_call(
            self, db, monkeypatch):
        """Токенный бюджет: «почти у предела» (<5000 остатка) — тик
        завершается заранее после первого вызова (деньги ограничены)."""
        _hot_cache(monkeypatch, {"memory.dream_tokens_per_day": 5000})
        llm = _FakeLLM(_ANS_A, _ANS_B)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        await _add_batch(db, 3, ("петя", "ходит", "по четвергам"))
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        assert res["budget_stop"] is True
        assert len(llm.calls) == 1
        # оценка токенов записана в лог (>0)
        cursor = await db.db.execute(
            "SELECT tokens FROM memory_dream_log "
            "WHERE kind = 'distilled' LIMIT 1")
        row = await cursor.fetchone()
        assert row["tokens"] > 0


class TestProtectedAndSupersede:
    @pytest.mark.asyncio
    async def test_protected_facts_gate_blocks_candidate(self, db,
                                                         monkeypatch):
        """Гейт protected-семантики (§3.4.3): факт с текстом защищённого не
        кандидат → кластер не набирается → дистилляции нет."""
        llm = _FakeLLM(_ANS_A)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        facts = [("вася платит за всех в баре раз", 1),
                 ("вася платит за всех в баре два", 2),
                 ("вася платит за всех в баре три", 3)]
        for text, _ in facts:
            await _add_fact(db, text)
        # факт №1 — chat-level protected (user_name NULL)
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (?, NULL, ?, ?)", (CHAT_ID, facts[0][0], 1.0))
        await db.db.commit()
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 0
        assert llm.calls == []
        # контрольный чат без protected — кластер проходит
        llm2 = _FakeLLM(_ANS_A)
        worker2 = DreamWorker(db, memory=None, llm=llm2)
        for i in range(3):
            await db.insert_graph_fact(
                -200, f"петя опаздывает на встречи уже {i + 1} раз",
                "chat_history", None, importance=4)
        res2 = await worker2.run_once(-200)
        assert res2["distilled"] == 1

    @pytest.mark.asyncio
    async def test_supersede_by_anchor_token(self, db, monkeypatch):
        """D-6: новый belief той же темы (якорный токен) supersedes старый;
        старый остаётся confirmed, supersedes фиксирует замену."""
        llm = _FakeLLM(_ANS_A)
        worker = _worker(db, llm, monkeypatch=monkeypatch)
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        old = (await _belief_rows(db))[0]
        # вторая тема-волна: тот же якорный токен «платит» в новом тексте
        llm2 = _FakeLLM(
            '{"beliefs":[{"text":"вася платит за всех в баре, даже когда '
            'забывает кошелёк","evidence":[1,2,3]}]}')
        worker2 = _worker(db, llm2, monkeypatch=monkeypatch)
        await _add_batch(db, 3, ("вася", "оплачивает", "счета"))
        res2 = await worker2.run_once(CHAT_ID)
        assert res2["distilled"] == 1
        new = (await _belief_rows(db))[1]
        assert new["fact"] == "вася платит за всех в баре, даже когда " \
                              "забывает кошелёк"
        assert new["supersedes"] is None
        cursor = await db.db.execute(
            "SELECT supersedes, status FROM graph_facts WHERE id = ?",
            (old["id"],))
        row = await cursor.fetchone()
        assert row["supersedes"] == new["id"]
        assert row["status"] == "confirmed"    # старый жив (ранг решает, D-6)
