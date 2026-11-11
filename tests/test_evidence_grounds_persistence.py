"""Основания решений: сохранение, повторное чтение, независимость.

Дефект 12.11.2026 (планы `plans/owner_inputs/2026-11-12-evidence-grounds-persistence.md`):
основания присутствовали в текстовом отчёте, но отсутствовали в
машиночитаемом JSON. Здесь закреплены ТРИ механизма потери и их отсутствие:

1. `experience_diagnostics._learning_analytics` отдавал только агрегаты
   (`confirmed`/`stale`/`by_origin`) — ни id уроков, ни первичных источников;
2. `ExperienceService.lesson.validate` ЗАМЕНЯЛ сохранённый список
   `independent_sources` более узким (для preference-уроков — пустым), т.е.
   подтверждённый урок терял основания, а число подтверждений оставалось;
3. `turn_trace._sel_block` собирал блок из закрытого набора ключей, поэтому
   любое новое поле продюсера (основание с происхождением) молча выпадало.

Отдельно проверяется РАЗДЕЛЕНИЕ двух метрик:

* `stems_shared` — ЛЕКСИЧЕСКАЯ релевантность «вопрос ↔ строка» (число общих
  основ, порог §2 дизайна `vmq-mem/next-stage-design.md`), считается
  существующим `_rag_subject_shared` и переносится как есть;
* `independent_grounds` — ПРОИСХОЖДЕНИЕ источников (`provenance`), и
  совпадение слов в него не входит.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from services import experience_diagnostics as diag
from services import hot_config
from services import mca_events
from services import mca_experience as me
from services import provenance as prov
from services import turn_trace
from services.database import DatabaseService
from services.direct_chat_service import (
    DirectChatService, _rag_subject_shared, _rag_subject_stems)

CHAT = -100


class _FakeHot:
    def get(self, key, default=None):
        return default


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name: str = "grounds.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


# ═══ 1. Две метрики не смешиваются ═════════════════════════════════════════

def test_stems_shared_is_lexical_and_independence_is_provenance():
    """Порог §2 — число общих основ; независимость — по происхождению.

    Три строки одного источника делят с вопросом все основы, но дают ОДИН
    корень происхождения: совпадение слов не делает их тремя
    подтверждениями."""
    query_stems = _rag_subject_stems(
        "куда поехал сергей в отпуск")
    shared = _rag_subject_shared(
        query_stems, "сергей поехал в отпуск на море")
    assert shared >= 2                        # лексическая релевантность

    grounds = [
        prov.ground_record(entity_type="message", entity_id="501", chat_id=CHAT,
                           tg_message_id=501, origin="chat_history",
                           resolution="resolved", verification="verified"),
        prov.ground_record(entity_type="message", entity_id="501", chat_id=CHAT,
                           tg_message_id=501, origin="chat_history",
                           resolution="resolved", verification="verified"),
        prov.ground_record(entity_type="message", entity_id="502", chat_id=CHAT,
                           tg_message_id=502,
                           origin="bot_direct_reply", resolution="resolved",
                           verification="verified"),
    ]
    assert prov.distinct_ground_roots(grounds) == 2
    # Дубль одного источника + собственный ответ бота независимыми не считаются.
    assert prov.independent_grounds_count(grounds) == 1
    # Лексическая метрика в запись основания переносится, но на счёт не влияет.
    with_stems = [dict(grounds[0], stems_shared=shared,
                       stems_shared_reason="lexical_threshold_applied")]
    assert prov.independent_grounds_count(with_stems) == 1


def test_unmeasured_stems_is_null_with_reason_not_zero():
    ground = prov.ground_record(
        entity_type="graph_fact", entity_id="77", chat_id=CHAT,
        stems_shared=None, stems_shared_reason="vector_leg_no_threshold")
    assert ground["stems_shared"] is None
    assert ground["stems_shared_reason"] == "vector_leg_no_threshold"


def test_period_filter_records_stems_shared_on_the_row_it_judged():
    """Значение считается ОДИН раз — в существующем фильтре §2.

    Строка, прошедшая порог, несёт число общих основ; векторная строка под
    `historical` порогом не судится → `None` + причина (а не 0)."""
    rows = [
        {"item_id": "fact:1", "fact": "сергей поехал в отпуск",
         "subject_proxy": "stems", "period_fill": True},
        {"item_id": "fact:2", "fact": "совсем другая тема про погоду",
         "subject_proxy": "stems", "period_fill": True},
        {"item_id": "fact:3", "fact": "векторный сосед без общих слов",
         "subject_proxy": "knn", "period_fill": True},
    ]
    accepted, rejected = DirectChatService._rag_period_subject_filter(
        "куда поехал сергей в отпуск", rows, "historical")
    by_id = {row["item_id"]: row for row in rows}
    assert by_id["fact:1"]["stems_shared"] >= 2
    assert by_id["fact:1"]["stems_shared_reason"] == \
        "lexical_threshold_applied"
    assert by_id["fact:3"]["stems_shared"] is None
    assert by_id["fact:3"]["stems_shared_reason"] == \
        "vector_leg_no_threshold"
    assert "fact:3" in [row["item_id"] for row in accepted]
    assert "fact:2" not in [row["item_id"] for row in accepted]
    assert rejected >= 1


def test_selection_projection_keeps_grounds_and_stems_with_reason():
    """Allowlist-проектор больше не выбрасывает основания из durable JSON."""
    ground = prov.ground_record(
        entity_type="graph_fact", entity_id="fact:9", chat_id=CHAT,
        tg_message_id=902, author_id=42, origin="chat_history",
        resolution="resolved", verification="tentative",
        supports_kind="rag_fact", supports_id="fact:9",
        period_fill=True, stems_shared=3,
        stems_shared_reason="lexical_threshold_applied")
    unmeasured = prov.ground_record(
        entity_type="graph_fact", entity_id="fact:10", chat_id=CHAT,
        origin="chat_history", resolution="resolved",
        supports_kind="rag_fact", supports_id="fact:10",
        stems_shared=None, stems_shared_reason="vector_leg_no_threshold")
    payload = turn_trace._selection_payload({
        "blocks": [{"kind": "rag", "rendered": True,
                    "source_ids": ["fact:9", "fact:10"],
                    "grounds": [ground, unmeasured]}],
        "counts": {"available_messages": 3, "included_messages": 2},
    })
    block = payload["blocks"][0]
    grounds = payload["memory_grounds"]
    assert [g["entity_id"] for g in grounds] == ["fact:9", "fact:10"]
    assert grounds[0]["stems_shared"] == 3
    assert "stems_shared_reason" not in grounds[0]
    assert grounds[1]["stems_shared"] is None
    assert grounds[1]["stems_shared_reason"] == "vector_leg_no_threshold"
    # Блоки описывают только состав («что видел ответ») — основания вынесены.
    assert "grounds" not in block
    summary = payload["grounds_summary"]
    assert summary["total"] == 2
    assert summary["roots"] == 2              # происхождение, не лексика
    assert summary["self_referential"] == 0
    assert summary["stems_shared_measured"] == 1
    assert summary["stems_shared_unmeasured"] == 1
    # Никакой «подтверждённости» из совпадения слов не следует.
    assert prov.independent_grounds_count(grounds) == 0


def test_self_referential_ground_never_counts_as_independent():
    ground = prov.ground_record(
        entity_type="graph_fact", entity_id="fact:11", chat_id=CHAT,
        origin="bot_direct_reply", resolution="resolved",
        verification="verified")
    assert ground["self_referential"] is True
    assert prov.independent_grounds_count([ground]) == 0


# ═══ 2. Валидация урока не сужает сохранённые основания ═══════════════════

@pytest.mark.asyncio
async def test_validate_keeps_stored_grounds_for_preference_lesson(
        tmp_path, monkeypatch):
    """Регресс: подтверждение preference-урока обнуляло его основания."""
    monkeypatch.setattr(hot_config, "get", _FakeHot().get)
    db = await _db(tmp_path, "pref.db")
    try:
        svc = me.get_service(db)
        lid, ver = await svc.lesson.propose(
            type="social_preference", scope="user_in_chat",
            rule_key="address_form", scope_chat_id=CHAT, scope_user_id=42,
            applicability="user:42 pref:address_form",
            origin_kind="explicit", independent_sources=("message:12",))
        assert lid
        assert await svc.lesson.validate(
            lid, ver, evidence=me.ValidationEvidence(
                kind="explicit_preference", permission_granted=True,
                conflict_free=True)) is True
        row = await svc.store.get_lesson(lid, ver)
        assert json.loads(row["independent_sources"]) == ["message:12"]
        assert int(row["confirmation_count"]) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_validate_unions_new_episode_evidence_with_stored_sources(
        tmp_path, monkeypatch):
    monkeypatch.setattr(hot_config, "get", _FakeHot().get)
    db = await _db(tmp_path, "union.db")
    try:
        svc = me.get_service(db)
        lid, ver = await svc.lesson.propose(
            type="context", scope="chat", rule_key="bounded_block",
            scope_chat_id=CHAT, origin_kind="explicit",
            independent_sources=("message:21",))
        assert await svc.lesson.validate(
            lid, ver, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=("ep:a",))) is True
        row = await svc.store.get_lesson(lid, ver)
        assert json.loads(row["independent_sources"]) == ["ep:a", "message:21"]
    finally:
        await db.close()


# ═══ 3. JSON диагностики содержит основания, отчёт — те же записи ══════════

@pytest.mark.asyncio
async def test_diagnostics_json_carries_lesson_grounds(tmp_path, monkeypatch):
    monkeypatch.setattr(hot_config, "get", _FakeHot().get)
    db = await _db(tmp_path, "diag.db")
    try:
        svc = me.get_service(db)
        lid, ver = await svc.lesson.propose(
            type="context", scope="chat", rule_key="bounded_block",
            scope_chat_id=CHAT, origin_kind="explicit",
            independent_sources=("message:12", "message:13"))
        snapshot = await diag.experience_pipeline_snapshot(db)
        lessons = snapshot["learning_analytics"]["lessons"]
        item = next(i for i in lessons["items"]
                    if i["lesson_id"] == lid)
        assert item["version"] == ver
        assert item["grounds_state"] == "complete"
        assert [g["entity_id"] for g in item["grounds"]] == ["12", "13"]
        assert all(g["chat_id"] == CHAT for g in item["grounds"])
        assert all(g["supports_id"] == lid for g in item["grounds"])
        assert item["independent_grounds"] == 2
        # Текст и JSON — один источник данных.
        assert diag.grounds_consistency_violations(lessons) == []
        line = next(x for x in lessons["lines"] if x["lesson_id"] == lid)
        assert "message:12" in line["refs"]
        assert "message:12" in line["text"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_report_cannot_name_ground_absent_from_json(tmp_path,
                                                          monkeypatch):
    """Мутация: если проектор выбросил `grounds`, инвариант обязан сломаться.

    Это и есть защита от повторения дефекта: строка отчёта и JSON строятся из
    одних записей, поэтому потеря основания в payload видна сразу."""
    monkeypatch.setattr(hot_config, "get", _FakeHot().get)
    db = await _db(tmp_path, "mutation.db")
    try:
        svc = me.get_service(db)
        lid, ver = await svc.lesson.propose(
            type="context", scope="chat", rule_key="bounded_block",
            scope_chat_id=CHAT, origin_kind="explicit",
            independent_sources=("message:31",))
        snapshot = await diag.experience_pipeline_snapshot(db)
        lessons = snapshot["learning_analytics"]["lessons"]
        assert diag.grounds_consistency_violations(lessons) == []
        broken = json.loads(json.dumps(lessons))
        for item in broken["items"]:
            if item["lesson_id"] == lid:
                item["grounds"] = []      # эмуляция allowlist-проектора
        violations = diag.grounds_consistency_violations(broken)
        assert any("ref_not_in_json" in v and "message:31" in v
                   for v in violations), violations
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_lesson_without_grounds_is_honest_no_data(tmp_path,
                                                        monkeypatch):
    """Нет оснований и нет подтверждений — «нет данных», а не выдумка."""
    monkeypatch.setattr(hot_config, "get", _FakeHot().get)
    db = await _db(tmp_path, "nodata.db")
    try:
        svc = me.get_service(db)
        lid, _ver = await svc.lesson.propose(
            type="context", scope="chat", rule_key="bounded_block",
            scope_chat_id=CHAT, origin_kind="explicit")
        snapshot = await diag.experience_pipeline_snapshot(db)
        item = next(i for i in snapshot["learning_analytics"]["lessons"]["items"]
                    if i["lesson_id"] == lid)
        assert item["grounds"] == []
        assert item["grounds_state"] == "no_data"
        assert item["confirmation_count_mismatch"] is False
    finally:
        await db.close()


# ═══ 4. Полный цикл: построение → запись → перечитывание → перезапуск ═════

@pytest.mark.asyncio
async def test_grounds_survive_serialize_reload_and_restart(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(hot_config, "get", _FakeHot().get)
    path = str(tmp_path / "restart.db")
    dump = tmp_path / "snapshot.json"
    db = DatabaseService(path)
    await db.initialize()
    lid = None
    try:
        svc = me.get_service(db)
        lid, ver = await svc.lesson.propose(
            type="context", scope="chat", rule_key="bounded_block",
            scope_chat_id=CHAT, origin_kind="explicit",
            independent_sources=("message:12", "message:12", "message:13"))
        await svc.lesson.validate(
            lid, ver, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=("message:12", "message:13")))
        first = await diag.experience_pipeline_snapshot(db)
        dump.write_text(json.dumps(first["learning_analytics"],
                                   ensure_ascii=False), encoding="utf-8")
        first_item = next(i for i in first["learning_analytics"]["lessons"]
                          ["items"] if i["lesson_id"] == lid)
        assert first_item["independent_grounds"] == 2
        assert prov.ground_gaps(first_item["grounds"])
    finally:
        await db.close()

    # «Перезапуск»: новый экземпляр сервиса на том же хранилище.
    reloaded = json.loads(dump.read_text(encoding="utf-8"))
    db2 = DatabaseService(path)
    await db2.initialize()
    try:
        second = await diag.experience_pipeline_snapshot(db2)
        second_item = next(i for i in second["learning_analytics"]["lessons"]
                           ["items"] if i["lesson_id"] == lid)
        assert second_item["grounds"] == first_item["grounds"]
        assert second_item["independent_grounds"] == \
            first_item["independent_grounds"] == 2
        assert diag.grounds_consistency_violations(
            second["learning_analytics"]["lessons"]) == []
        # Значение, прочитанное из файла, совпадает с новым чтением из БД.
        stored_item = next(i for i in reloaded["lessons"]["items"]
                           if i["lesson_id"] == lid)
        assert stored_item["grounds"] == second_item["grounds"]
    finally:
        await db2.close()


# ═══ 5. Восстановление потерянных оснований из сохранённых связей ══════════

@pytest.mark.asyncio
async def test_recover_lesson_grounds_from_links_is_idempotent(
        tmp_path, monkeypatch):
    """Основания восстанавливаются ТОЛЬКО из сохранённых связей; повтор — no-op.

    Урок без связей честно попадает в `refused`, а не получает выдуманный
    источник."""
    monkeypatch.setattr(hot_config, "get", _FakeHot().get)
    db = await _db(tmp_path, "recover.db")
    try:
        svc = me.get_service(db)
        recoverable, _v1 = await svc.lesson.propose(
            type="context", scope="chat", rule_key="bounded_block",
            scope_chat_id=CHAT, origin_kind="explicit",
            independent_sources=("message:12",))
        lost, _v2 = await svc.lesson.propose(
            type="context", scope="chat", rule_key="compact_block",
            scope_chat_id=CHAT, origin_kind="explicit")
        # Эмуляция дефекта: основания пропали из сохранённой строки.
        await db.db.execute(
            "UPDATE mca_lessons SET independent_sources = '[]' "
            "WHERE lesson_id = ?", (recoverable,))
        await db.db.commit()
        lesson = await svc.store.get_lesson(recoverable)
        if lesson.get("source_ref_id") is None:
            pytest.skip("урок без subject-ref: связь не создаётся")
        from services import provenance as _prov
        src = _prov.SourceRef(store="sqlite", entity_type="message",
                              entity_id="12", chat_id=CHAT,
                              resolution="resolved")
        src_id = await _prov.resolve_source_ref(db, src)
        await _prov.add_evidence_link(db, _prov.EvidenceLink(
            subject_ref_id=int(lesson["source_ref_id"]),
            source_ref_id=int(src_id), link_type="derived_from",
            method="direct_reference", verification="verified",
            independence="independent"))

        report = await svc.store.recover_lesson_grounds()
        assert recoverable in [row["lesson_id"] for row in report["repaired"]]
        assert lost in [row["lesson_id"] for row in report["refused"]]
        row = await svc.store.get_lesson(recoverable)
        assert json.loads(row["independent_sources"]) == ["message:12"]
        # Идемпотентность: второй прогон ничего не пишет.
        again = await svc.store.recover_lesson_grounds()
        assert again["repaired"] == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_recover_grounds_on_schema_without_v46_is_honest(tmp_path):
    """Старая БД (без колонок v46) → честный отказ, без падения и выдумки."""
    db = DatabaseService(str(tmp_path / "old.db"))
    await db.initialize()
    try:
        await db.db.execute(
            "ALTER TABLE mca_lessons RENAME TO mca_lessons_old")
        await db.db.execute(
            "CREATE TABLE mca_lessons (lesson_id TEXT NOT NULL, "
            "version INTEGER NOT NULL, status TEXT NOT NULL, "
            "updated_at INTEGER NOT NULL)")
        await db.db.commit()
        report = await me.get_service(db).store.recover_lesson_grounds()
        assert report["scanned"] == 0
        assert report["repaired"] == []
        assert report["refused"] == [{"reason": "schema_without_v46_columns"}]
    finally:
        await db.close()
