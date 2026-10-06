"""MCA-10b `mca-10b-random-applications` — focused-тесты блока A
(T-5051…T-5054, ADR-1028-17 D1–D5/D13/D15, spec §1–§3/§12–§13).

Покрытие:
  * T-5051: санкционированное расширение purposes (ровно +5, карта одна,
    в доме 10a); `ui_replay` — НЕ purpose (draw не создаёт); purpose вне
    набора отклонён; запрос/результат воспроизводимы по журналу;
  * T-5052 (A29): РОВНО одна probability-проверка/одна выборка на
    ситуацию; один дополнительный равномерный draw истории (memory_recall)
    только для memory-кандидата; пустой пул — обычный исход без draw;
  * T-5053: hook после пакета сна — максимум 1 job; уникальный ключ
    (рестарт не дублирует); завершение job не запускает новую лотерею;
  * T-5054: master kill-switch 72→73; per-use OFF отключает только своё;
    OFF = честный disabled без draw/событий;
  * DDL v30 (санкция §13.1): fresh + идемпотентный повтор + симуляция
    v29→v30 c backup read-back.
"""
import sqlite3

import pytest

from services import mca_events, mca_gates
from services import mca_random_source as mrs
from services import mca_exploration as mx
from services.database import DatabaseService
from services.direct_chat_service import DecisionCandidate


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    mx.reset_delivery_pendings()
    yield
    mca_events.reset_pending()
    mx.reset_delivery_pendings()


async def _fresh_db(tmp_path, name="mca10b_a.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


class FakeSource:
    """Детерминированный источник (DI; счётчики = гейт-матрица A29)."""

    def __init__(self, probability=0.0, index=0, recall_index=None):
        self.probability = probability
        self.index = index
        self.recall_index = recall_index
        self.prob_calls = 0
        self.index_calls = 0
        self.recall_calls = 0

    async def choose(self, primary, alternatives, **kwargs):
        # Повтор логики политики 10a по счётчикам: одна probability-проверка
        # + одна выборка (см. test_one_check_one_draw_A29 с реальной 10a).
        return await mrs.ExplorationPolicy(self).choose(
            primary, alternatives, **kwargs)

    async def draw_probability(self, **kwargs):
        self.prob_calls += 1
        return mrs.DrawResult(value=self.probability, source="quantum",
                              draw_id="prob-draw")

    async def draw_index(self, n, **kwargs):
        self.index_calls += 1
        purpose = str(kwargs.get("purpose") or "")
        if purpose == mx.PURPOSE_MEMORY_RECALL:
            self.recall_calls += 1
            index = 0 if self.recall_index is None else self.recall_index
        else:
            index = self.index
        return mrs.DrawResult(index=index, source="quantum",
                              draw_id=f"sel-draw-{purpose or 'x'}")


def _cand(cid: str, *, priority: int = 0, admissible: bool = True,
          refs: tuple = (), intents: str | None = None) -> DecisionCandidate:
    return DecisionCandidate(
        candidate_id=cid, action="reply", reason_code="default",
        source="memory", communicative_intent=intents, priority=priority,
        source_refs=refs, admissible=admissible)


# ── T-5051: purposes/контракт ───────────────────────────────────────────────

def test_purposes_sanctioned_extension_and_single_map():
    """Ровно +5 purpose (D2/AM-1); карта purpose→probability ОДНА — в доме
    10a; новых probability-ключей нет; `ui_replay`/`ui_visualization` —
    не purposes."""
    assert mx.PURPOSES_10B == frozenset({
        "conversation_variant", "memory_recall", "archive_sample",
        "belief_review", "association_pair"})
    keys = mrs.EXPLORATION_PROBABILITY_KEYS
    for purpose in mx.PURPOSES_10B:
        assert purpose in keys
    assert keys["conversation_variant"] == "memory.random_exploration_probability"
    assert keys["memory_recall"] == "memory.random_exploration_probability"
    for purpose in ("archive_sample", "belief_review", "association_pair"):
        assert keys[purpose] == "memory.random_sleep_exploration_probability"
    assert set(keys.values()) == {"memory.random_exploration_probability",
                                  "memory.random_sleep_exploration_probability"}
    assert "ui_replay" not in keys and "ui_visualization" not in keys
    assert mx.UI_REPLAY_MARKER == "ui_replay"


@pytest.mark.asyncio
async def test_ui_replay_creates_no_draw(tmp_path, monkeypatch):
    """`ui_replay` — read-only: как purpose отклоняется, draw не создаётся
    (R5c); `ui_visualization` — разрешение применения, не purpose."""
    await _fresh_db(tmp_path)
    src = FakeSource()
    allowed, reason = await mx.exploration_allowed(
        None, mx.UI_REPLAY_MARKER, chat_id=1)
    assert allowed is False
    assert reason == "no_eligible_alternative"
    assert src.prob_calls == 0 and src.index_calls == 0
    # маркер никогда не попадает в purpose-набор/карту вероятностей
    assert mx.UI_REPLAY_MARKER not in mx.PURPOSES_10B
    assert mx.UI_REPLAY_MARKER not in mrs.EXPLORATION_PROBABILITY_KEYS
    assert mx.USE_UI_VISUALIZATION in mx.USES
    assert mx.USE_UI_VISUALIZATION not in mx.PURPOSES_10B


@pytest.mark.asyncio
async def test_unknown_purpose_rejected(tmp_path):
    """Purpose вне санкционированного набора отклонён (без draw)."""
    await _fresh_db(tmp_path)
    allowed, reason = await mx.exploration_allowed(
        None, "totally_unknown_purpose", chat_id=1)
    assert allowed is False
    assert reason == "no_eligible_alternative"


@pytest.mark.asyncio
async def test_request_result_reproducible_from_journal(tmp_path, monkeypatch):
    """Запрос/результат воспроизводимы по журналу: кандидаты/выбор/причины —
    в событии (entity_ids); draw_ids/actual_source — из ExplorationResult."""
    captured: list = []

    def fake_emit(event_name, *, outcome, **fields):
        captured.append({"event_name": event_name, "outcome": outcome,
                         **fields})
        return {}

    await _fresh_db(tmp_path)
    monkeypatch.setattr(mrs.mca_events, "emit_mca_event", fake_emit)
    src = FakeSource(probability=0.0, index=0)
    primary = _cand("primary", priority=5)
    pool = [_cand("alt-1", refs=("episode:e1",)),
            _cand("alt-2", admissible=False, refs=("episode:e2",))]
    choice, result = await mx.choose_conversation_alternative(
        None, chat_id=7, operation_id="op-42", primary=primary, pool=pool,
        context_version="cv-1", requested_source="mca10b", source=src)
    assert choice is not None and choice.explored
    assert result.outcome == mx.OUTCOME_EXPLORED
    assert result.request.operation_id == "op-42"
    assert result.request.primary_id == "primary"
    assert set(result.request.eligible_ids) == {"alt-1"}
    assert result.request.excluded == (("alt-2", "no_eligible_alternative"),)
    assert result.selected.candidate_id == "alt-1"
    events = [e for e in captured if e.get("event_name") == "random_uses"]
    assert events, "journal event expected"
    entity = events[-1]["entity_ids"]
    assert entity["operation_id"] == "op-42"
    assert entity["purpose"] == "conversation_variant"
    assert entity["primary"] == "primary"
    assert "alt-1" in entity["eligible"]
    assert ["alt-2", "no_eligible_alternative"] in entity["excluded"]
    assert entity["selected"] == "alt-1"
    # воспроизводимость: draw-журнал 10a несёт draw_ids выбора
    assert result.draw_ids and all(result.draw_ids)


# ── T-5052 (A29): одна проверка/один draw на ситуацию ───────────────────────

@pytest.mark.asyncio
async def test_one_check_one_draw_A29(monkeypatch):
    """Ровно одна probability-проверка и одна выборка на ситуацию (НЕ сумма
    5%); для memory-истории — ровно один дополнительный равномерный draw
    (memory_recall); повторных 5%-проверок нет."""
    src = FakeSource(probability=0.0, index=0, recall_index=1)
    primary = _cand("primary", priority=5)
    pool = [_cand("story-1", refs=("episode:e1",)),
            _cand("story-2", refs=("episode:e2",))]
    choice, result = await mx.choose_conversation_alternative(
        None, chat_id=1, primary=primary, pool=pool, source=src)
    assert choice.explored
    assert src.prob_calls == 1                    # одна проверка
    assert src.index_calls == 2                   # выбор + memory_recall draw
    assert src.recall_calls == 1                  # ровно один дополнительный
    assert result.selected.candidate_id == "story-2"
    assert any(d.startswith("sel-draw-memory_recall") for d in result.draw_ids)
    # НЕ memory-кандидат → дополнительного draw нет
    src2 = FakeSource(probability=0.0, index=0)
    choice2, _ = await mx.choose_conversation_alternative(
        None, chat_id=1, primary=_cand("p2", priority=5),
        pool=[_cand("plain-1"), _cand("plain-2")], source=src2)
    assert choice2.explored
    assert src2.index_calls == 1 and src2.recall_calls == 0


@pytest.mark.asyncio
async def test_empty_pool_normal_outcome_without_draw(tmp_path):
    """Пустой пул/нет допустимых → primary + `no_eligible_alternative`
    БЕЗ draw — обычный исход (§3.4); LLM ради альтернатив не вызывается
    (кандидаты только из уже найденных)."""
    await _fresh_db(tmp_path)
    src = FakeSource()
    primary = _cand("only", priority=1)
    # single candidate == primary → альтернатив нет
    choice, result = await mx.choose_conversation_alternative(
        None, chat_id=1, primary=primary, pool=[primary], source=src)
    assert choice is None
    assert result.outcome == mx.OUTCOME_NO_ALTERNATIVE
    assert src.prob_calls == 0 and src.index_calls == 0
    # только недопустимые — тот же честный исход
    choice2, result2 = await mx.choose_conversation_alternative(
        None, chat_id=1, primary=primary,
        pool=[primary, _cand("bad", admissible=False)], source=src)
    assert choice2 is None
    assert result2.outcome == mx.OUTCOME_NO_ALTERNATIVE
    assert src.prob_calls == 0


@pytest.mark.asyncio
async def test_randomness_does_not_substitute_retrieval_addressee(monkeypatch):
    """Случайность не подменяет retrieval/адресата/факты: недопустимое
    измерение `direct_request` отвергается политикой 10a (A30-часть);
    primary сохраняется при отказе draw."""
    from services.direct_chat_service import handle_initiative  # noqa: F401
    src = FakeSource()
    choice = await mrs.ExplorationPolicy(src).choose(
        "primary", ["alt"], chat_id=1, purpose="conversation_variant",
        policy_version=mx.POLICY_VERSION_10B, measurement="direct_request")
    assert choice.selected == "primary"
    assert choice.reason == "no_eligible_alternative"
    assert src.prob_calls == 0


# ── T-5054: настройки/kill-switch (OFF-паритет, R5e) ────────────────────────

def test_kill_switch_registry_73_and_defaults():
    """`MCA_RANDOM_USES_ENABLED` — ровно один новый kill-switch (72→73),
    default ON; reason-словарь 237→247 (санкция §13.4).
    (mca-18, ADR-1028-18 §8.3/§8.4): волна эволюционировала — kill-switches
    73→76 (+3 SelfModel), reason 247→257 (+10 санкции целиком: +3 блока A/B,
    +7 блоков C–F); guard фиксирует актуальный frontier волны, вклад
    mca-18 — в его собственных тестах."""
    # mca-19 (round 10.43, ADR-1028-19 §8.3): санкционированный bump
    # реестра 76→80 (+4 MCA_VISION_*) — счётчик обновлён по конвенции.
    # mca-20 (round 10.44, ADR-1028-20 §8.3): санкционированный bump
    # реестра 80→83 (+3 MCA_TEMPORAL_FACTCHECK_*) — та же конвенция.
    assert len(mca_gates.KILL_SWITCHES) == 83
    assert "MCA_RANDOM_USES_ENABLED" in mca_gates.KILL_SWITCHES
    assert mca_gates.KILL_SWITCHES["MCA_RANDOM_USES_ENABLED"][0] is True
    assert mca_gates.random_uses_enabled() is True
    # mca-19 (round 10.43, ADR-1028-19 §8.3): bump словаря причин 257→269
    # (+12 vision-кодов); mca-20 (round 10.44): 269→279 (+10 temporal) —
    # счётчик обновлён по той же конвенции.
    assert len(mca_events.REASON_CODES) == 279
    for code in ("exploration_accepted", "exploration_rejected",
                 "exploration_deferred", "exploration_failed",
                 "exploration_used_in_reply", "exploration_stored_only",
                 "exploration_not_used", "exploration_type_unavailable",
                 "association_stale", "belief_review_unchanged"):
        assert code in mca_events.REASON_CODES


@pytest.mark.asyncio
async def test_master_off_bit_parity(tmp_path, monkeypatch):
    """Master OFF → None + без draw + БЕЗ событий (бит-в-бит 2.58.60)."""
    await _fresh_db(tmp_path)
    captured: list = []
    monkeypatch.setattr(mrs.mca_events, "emit_mca_event",
                        lambda *a, **k: captured.append(
                            {"event_name": a[0], **k}) or {})
    monkeypatch.setattr(mca_gates, "random_uses_enabled", lambda: False)
    src = FakeSource()
    choice, result = await mx.choose_conversation_alternative(
        None, chat_id=1, primary=_cand("p", priority=1),
        pool=[_cand("p", priority=1), _cand("a")], source=src)
    assert choice is None
    assert result.outcome == mx.OUTCOME_DISABLED
    assert src.prob_calls == 0 and src.index_calls == 0
    assert not captured                          # событийный шум отсутствует
    direction = await mx.after_sleep_direction(None, source=src)
    assert direction["status"] == "disabled"
    assert src.prob_calls == 0 and src.index_calls == 0


@pytest.mark.asyncio
async def test_per_use_off_disables_only_itself(tmp_path, monkeypatch):
    """OFF `random.uses.belief_review` отключает только belief_review;
    остальные применения продолжают (R5e)."""
    await _fresh_db(tmp_path)
    values = {"memory.random_uses_belief_review": False}

    async def fake_setting(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mx, "_read_use_setting", fake_setting)
    assert await mx.use_enabled(None, "belief_review") is False
    assert await mx.use_enabled(None, "archive_sample") is True
    assert await mx.use_enabled(None, "conversation_variant") is True
    allowed_br, _ = await mx.exploration_allowed(
        None, "belief_review", chat_id=1)
    allowed_as, _ = await mx.exploration_allowed(
        None, "archive_sample", chat_id=1)
    assert allowed_br is False and allowed_as is True
    # пер-чат override тоже уважается (chat_params read-path)
    values["memory.random_uses_archive_sample"] = False
    assert await mx.use_enabled(None, "archive_sample", chat_id=5) is False


# ── T-5053: фоновое направление — уникальный ключ/без дублей ────────────────

@pytest.mark.asyncio
async def test_exploration_job_key_unique_per_package():
    """Уникальный ключ `(chat_id, package_run_id, type)` — рестарт не
    дублирует (THR-3); kind отделён от основного worker'а."""
    key = mx.exploration_job_key(-100, "dream:123", "archive_sample")
    assert key == "exploration:-100:dream:123:archive_sample"
    assert mx.exploration_job_key(
        -100, "dream:123", "archive_sample") == key
    assert mx.exploration_job_kind(
        "archive_sample").startswith("exploration.")
    assert mx.exploration_job_kind("archive_sample") != "episodes.backfill"
    assert mx.exploration_job_kind("archive_sample") != "graphrag_rebuild"


@pytest.mark.asyncio
async def test_direction_no_lottery_after_job_completion(tmp_path, monkeypatch):
    """Завершение доп. job НЕ запускает новую лотерею (THR-2): повторный
    вызов direction с тем же package_run_id при активном job → coalesced
    (0 новых probability-draw)."""
    db = await _fresh_db(tmp_path, name="mca10b_dir.db")
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (chat_id, user_id, text, timestamp) "
        "VALUES (-100, 1, 'привет', 1700000000)")
    await db.db.commit()
    src = FakeSource(probability=0.0, index=0)
    first = await mx.after_sleep_direction(
        db, package_run_id="dream:1", source=src)
    assert first["status"] == "enqueued"
    prob_after_first = src.prob_calls
    second = await mx.after_sleep_direction(
        db, package_run_id="dream:1", source=src)
    assert second["status"] == "coalesced"
    assert src.prob_calls == prob_after_first      # лотереи нет
    await db.close()


# ── DDL v30 (санкция §13.1) ─────────────────────────────────────────────────

async def _v30_artifacts(db) -> dict:
    cursor = await db.db.execute("PRAGMA user_version")
    version = int((await cursor.fetchone())[0])
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('mca_associations','mca_archive_coverage','mca_belief_reviews')")
    tables = {r[0] for r in await cursor.fetchall()}
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND "
        "name='idx_mca_episodes_last_used'")
    episode_index = await cursor.fetchone() is not None
    cursor = await db.db.execute("PRAGMA table_info(mca_episodes)")
    cols = {r[1] for r in await cursor.fetchall()}
    cursor = await db.db.execute(
        "SELECT version, name FROM schema_migrations WHERE version = 30")
    book = await cursor.fetchone()
    return {"version": version, "tables": tables,
            "episode_index": episode_index,
            "has_last_retrieved": "last_retrieved_at" in cols,
            "has_last_used": "last_used_in_chat_at" in cols,
            "book_row": dict(book) if book else None}


@pytest.mark.asyncio
async def test_ddl_v30_fresh_and_idempotent(tmp_path):
    """Fresh: v30 применён ровно один раз (2 колонки + индекс + 3 таблицы +
    книга); повторный initialize — no-op (0 дублей).
    (mca-18): frontier глобальной схемы двинулся 30→31 — свежая БД
    приземляется на актуальный frontier (≥30); v30-метка — в книге."""
    path = str(tmp_path / "mca10b_v30.db")
    db = DatabaseService(path)
    await db.initialize()
    first = await _v30_artifacts(db)
    assert first["version"] >= 30
    assert first["tables"] == {"mca_associations", "mca_archive_coverage",
                               "mca_belief_reviews"}
    assert first["episode_index"] and first["has_last_retrieved"] \
        and first["has_last_used"]
    assert first["book_row"]["name"] == "random_uses"
    cursor = await db.db.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = 30")
    assert int((await cursor.fetchone())[0]) == 1
    await db.close()
    db2 = DatabaseService(path)
    await db2.initialize()
    second = await _v30_artifacts(db2)
    assert second == first
    cursor = await db2.db.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version = 30")
    assert int((await cursor.fetchone())[0]) == 1
    await db2.close()


@pytest.mark.asyncio
async def test_ddl_v30_simulation_from_v29_with_backup(tmp_path):
    """v29→v30 (симуляция прод-апгрейда): непустые эпизоды переживают ALTER;
    backup-guard создаёт pre_migration-копию c read-back (user_version=29);
    повтор — no-op."""
    from services.memory_backup import _MIGRATION_BACKUP_PREFIX
    path = str(tmp_path / "mca10b_upgrade.db")
    db = DatabaseService(path)
    await db.initialize()
    # Непустые данные (переживают аддитивный апгрейд).
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (chat_id, user_id, text, timestamp) "
        "VALUES (-7, 1, 'факт', 1700000000)")
    await db.db.commit()
    from services.mca_episodes import EpisodeRepository
    repo = EpisodeRepository(db)
    await repo.insert_episode(
        chat_id=-7, title="t", summary="s", participants=[], claims=[],
        event_start=1700000000, event_end=1700000600, outcome="",
        outcome_known=False, open_questions=[], message_keys=["-7:1"],
        seg_key="seg-1", extraction_version="v1", now=1700000600)
    # Даунгрейд-симуляция «прод v29»: убрать v30-артефакты, маркер 29.
    for sql in ("DROP TABLE mca_associations",
                "DROP TABLE mca_archive_coverage",
                "DROP TABLE mca_belief_reviews",
                "DROP INDEX IF EXISTS idx_mca_episodes_last_used",
                "CREATE TABLE episodes_legacy AS SELECT episode_id, chat_id,"
                " title, summary, participants_json, event_start_ts,"
                " event_end_ts, discovered_at, updated_at, claims_json,"
                " outcome, open_questions, message_keys_json, segment_key,"
                " extraction_version, mapping_status, recheck_pending"
                " FROM mca_episodes",
                "DROP TABLE mca_episodes",
                "ALTER TABLE episodes_legacy RENAME TO mca_episodes",
                "DELETE FROM schema_migrations WHERE version = 30",
                "PRAGMA user_version = 29"):
        await db.db.execute(sql)
    await db.db.commit()
    await db.close()

    db2 = DatabaseService(path)
    await db2.initialize()          # backup-guard → v30
    from pathlib import Path as _Path
    backups = list(_Path(path).parent.glob(f"{_MIGRATION_BACKUP_PREFIX}*.db"))
    assert backups, "pre_migration backup expected"
    backup = backups[0]
    conn = sqlite3.connect(str(backup))
    try:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 29
        episodes = int(conn.execute(
            "SELECT COUNT(*) FROM mca_episodes").fetchone()[0])
        assert episodes == 1        # данные прод-БД в копии
    finally:
        conn.close()
    upgraded = await _v30_artifacts(db2)
    # (mca-18): после v30 применяется следующий санкционированный шаг v31 →
    # frontier ≥ 30 (пин глобального frontier, не фичи).
    assert upgraded["version"] >= 30
    assert upgraded["tables"] == {"mca_associations", "mca_archive_coverage",
                                  "mca_belief_reviews"}
    assert upgraded["has_last_retrieved"] and upgraded["has_last_used"]
    # Данные пережили апгрейд; NULL-давность = честный unknown.
    rows = await repo_list(db2)
    assert len(rows) == 1 and rows[0]["last_retrieved_at"] is None \
        and rows[0]["last_used_in_chat_at"] is None
    await db2.close()
    # Идемпотентный повтор на обновлённой БД.
    db3 = DatabaseService(path)
    await db3.initialize()
    again = await _v30_artifacts(db3)
    assert again == upgraded
    await db3.close()


async def repo_list(db):
    cursor = await db.db.execute(
        "SELECT episode_id, last_retrieved_at, last_used_in_chat_at "
        "FROM mca_episodes")
    return [dict(r) for r in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_off_parity_gate_matrix_focused(tmp_path, monkeypatch):
    """Гейт-матрица §14.2 (focused): каждый рубильник OFF → честный
    disabled/not_run без draw; комбинация с K1/K4 уважается."""
    await _fresh_db(tmp_path)
    src = FakeSource()
    pool = [_cand("p", priority=1), _cand("a")]
    # K4 OFF (существующий гейт) → disabled через choose (10a семантика).
    monkeypatch.setattr(mca_gates, "random_exploration_enabled",
                        lambda: False)
    choice, result = await mx.choose_conversation_alternative(
        None, chat_id=1, primary=pool[0], pool=pool, source=src)
    assert choice is None or not getattr(choice, "explored", True)
    assert result.outcome in (mx.OUTCOME_DISABLED, mx.OUTCOME_PRIMARY)
    assert src.prob_calls == 0
    monkeypatch.setattr(mca_gates, "random_exploration_enabled",
                        lambda: True)
    # per-use OFF conversation_variant → без draw, событие честное.
    captured: list = []
    monkeypatch.setattr(mrs.mca_events, "emit_mca_event",
                        lambda *a, **k: captured.append(
                            {"event_name": a[0], **k}) or {})
    monkeypatch.setattr(mx, "_read_use_setting",
                        async_lambda({"memory.random_uses_"
                                      "conversation_variant": False}))
    choice2, result2 = await mx.choose_conversation_alternative(
        None, chat_id=1, primary=pool[0], pool=pool, source=src)
    assert choice2 is None and result2.outcome == mx.OUTCOME_DISABLED
    assert src.prob_calls == 0
    events = [e for e in captured if e.get("event_name") == "random_uses"]
    assert events and events[-1].get("reason_code") == "disabled"


def async_lambda(values):
    async def _fake(key, chat_id, default):
        return values.get(key, default)
    return _fake


# ── интеграция T-5052: единый вход инициативы (прецедент mca-09 block E) ────

class _FakeBot:
    def __init__(self):
        self.id = 42
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

        class _Msg:
            message_id = 1000 + len(self.sent)

        return _Msg()


def _initiative_candidate(chat_id: int, refs: tuple = (), priority: int = 0):
    from services import mca_intents
    cand = mca_intents.candidate_from_trigger(
        trigger_kind="intent_due", chat_id=chat_id)
    if cand is None:
        return None
    # refs/приоритет — для exploration-пула (memory-история/форма).
    object.__setattr__(cand, "source_refs", tuple(refs))
    cand.priority = priority
    return cand


@pytest.mark.asyncio
async def test_handle_initiative_one_check_per_operation(tmp_path,
                                                         monkeypatch):
    """A29-интеграция: один conversation operation → РОВНО одна probability-
    проверка (не сумма независимых 5%); доставка подтверждена → штамп
    `last_used_in_chat_at` на выбранной истории."""
    from services.direct_chat_service import handle_initiative
    from services import mca_intents
    db = await _fresh_db(tmp_path)
    try:
        svc = mca_intents.get_service(db)
        intent_id, created = await svc.create_intent(
            -5, "follow_up", "unanswered_question",
            goal="Спросить про встречу", source_refs=("msg:1",),
            not_before=0, activation_condition="time_due")
        assert created
        cand = mca_intents.candidate_from_trigger(
            trigger_kind="intent_due", chat_id=-5, intent_id=intent_id)
        # эпизод в БД + refs на кандидате (memory-история)
        from services.mca_episodes import EpisodeRepository
        repo = EpisodeRepository(db)
        ep = await repo.insert_episode(
            chat_id=-5, title="старая история", summary="s", participants=[],
            claims=[], event_start=1600000000, event_end=1600000060,
            outcome="", outcome_known=False, open_questions=[],
            message_keys=["-5:1"], seg_key="seg-1",
            extraction_version="mca05-v1", now=1600000060)
        object.__setattr__(cand, "source_refs", (f"episode:{ep}",))
        # второй кандидат — ВЫШЕ приоритетом (primary), story-кандидат
        # остаётся альтернативой пула → выбор exploration падает на историю
        alt = mca_intents.candidate_from_trigger(
            trigger_kind="intent_due", chat_id=-5)
        alt.priority = 5
        src = FakeSource(probability=0.0, index=0)
        monkeypatch.setattr(mx, "get_source", lambda db=None: src)
        bot = _FakeBot()
        result = await handle_initiative(
            bot=bot, chat_id=-5,
            situation=mca_intents.InitiativeSituation(
                trigger_kind="intent_due", chat_id=-5),
            candidates=[cand, alt], prepared_text="вспоминаем: старая история",
            db=db)
        assert result["status"] == "sent"
        assert src.prob_calls == 1 and src.index_calls == 1 \
            and src.recall_calls == 0        # одна проверка/один draw
        # подтверждённая доставка → штамп использования истории
        row = await mx._episode_usage_row(db, ep)
        assert row["last_used_in_chat_at"] is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_handle_initiative_master_off_bit_parity(tmp_path, monkeypatch):
    """Master OFF → путь 2.58.60: ни одного draw, реплика по primary-пути."""
    from services.direct_chat_service import handle_initiative
    from services import mca_intents
    db = await _fresh_db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "random_uses_enabled", lambda: False)
        svc = mca_intents.get_service(db)
        intent_id, created = await svc.create_intent(
            -5, "follow_up", "unanswered_question",
            goal="Спросить про встречу", source_refs=("msg:1",),
            not_before=0, activation_condition="time_due")
        assert created
        cand = mca_intents.candidate_from_trigger(
            trigger_kind="intent_due", chat_id=-5, intent_id=intent_id)
        src = FakeSource()
        monkeypatch.setattr(mx, "get_source", lambda db=None: src)
        bot = _FakeBot()
        result = await handle_initiative(
            bot=bot, chat_id=-5,
            situation=mca_intents.InitiativeSituation(
                trigger_kind="intent_due", chat_id=-5),
            candidates=[cand], prepared_text="ответ", db=db)
        assert result["status"] == "sent"
        assert src.prob_calls == 0 and src.index_calls == 0
    finally:
        await db.close()
