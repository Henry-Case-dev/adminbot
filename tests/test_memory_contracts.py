"""MEMORY-01 — контрактные тесты логического слоя памяти.

Срез EPIC-MEMORY-COGNITIVE-02 / MEMORY-01. Контракт:
`plans/features/memory-cognitive-02/contracts.md` (rev3) §1…§4, §7, §8;
минимальный touch-set: `plans/features/memory-cognitive-02/audit-a0.md` §7.

Проверяется не «форма питона», а невозможность нечестных состояний:
* подтверждённое ребро без проверенного независимого основания;
* `mentions`, выданное за независимую поддержку;
* legacy-основание, «понижающее» ребро с проверенным корнем;
* неоднозначность, превращённая в резолв (слияние);
* время «по умолчанию»;
* «пустой» ответ вместо «нет прав»/«ошибка»/«устаревший курсор»;
* превью без границы и с внутренними id.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from services import graphrag_provenance, mca_retrieval_context, provenance
from services import memory_contracts as mc

CHAT = -1004000000001


# ── фабрики тестовых данных ────────────────────────────────────────────────

def _entity(node_id: int = 7, *, entity_type: str = "user",
            chat_id: int = CHAT, name: str = "Аня",
            legacy: tuple[int, ...] = (), aliases: tuple[str, ...] = (),
            ) -> mc.EntityRef:
    return mc.EntityRef(
        chat_id=chat_id, node_id=node_id, entity_type=entity_type,
        display_name=name, legacy_ids=legacy, aliases=aliases)


def _support(*, ref_id: int = 501, fact_id: int | None = None,
             link_type: str = "supports",
             origin_class: mc.OriginClass = mc.OriginClass.EXPLICIT_DIRECT,
             verification: str = "verified",
             independence: str = "independent",
             mode: mc.AssertionMode = mc.AssertionMode.ASSERTED,
             speaker: str | None = "Аня", subject: str | None = "Борис",
             asserted_ts: int | None = None,
             event_ts: int | None = None,
             observed_ts: int | None = None,
             ) -> mc.RelationSourceView:
    return mc.RelationSourceView(
        link_type=link_type, origin_class=origin_class,
        verification=verification, independence=independence,
        established_at=1_760_000_000, method="direct_reference",
        kind="message", assertion_mode=mode, source_ref_id=ref_id,
        fact_id=fact_id, speaker=speaker, subject=subject,
        asserted_ts=asserted_ts, event_ts=event_ts, observed_ts=observed_ts)


def _legacy_source(ref_id: int = 900) -> mc.RelationSourceView:
    return _support(
        ref_id=ref_id, link_type="derived_from",
        origin_class=mc.OriginClass.LEGACY_UNKNOWN,
        verification="unknown", independence="unknown",
        mode=mc.AssertionMode.UNKNOWN)


def _relation(*, status: mc.RelationStatus = mc.RelationStatus.CONFIRMED,
              sources: tuple[mc.RelationSourceView, ...] = (),
              frequency: int = 1, explanation: str = "Аня сказала о связи",
              **kwargs) -> mc.RelationView:
    return mc.RelationView(
        edge_id=kwargs.pop("edge_id", 11), chat_id=CHAT,
        source_entity_id=kwargs.pop("source_entity_id", 7),
        target_entity_id=kwargs.pop("target_entity_id", 9),
        relation_type="знает", relation_label="Знает",
        status=status, sources=sources, frequency=frequency,
        explanation=explanation, **kwargs)


def _revision() -> mc.SearchRevision:
    return mc.SearchRevision(graph="g1", alias="a1", index_fingerprint="i1")


def _item(*, ref_kind: str = "entity", canonical_id: str = f"ent:{CHAT}:7",
          title: str = "Аня", category: str = "Человек",
          evidence: str = "confirmed", snippet: str | None = None,
          focus: mc.SearchFocus | None = None,
          ambiguity: mc.SearchAmbiguity | None = None) -> mc.SearchItem:
    return mc.SearchItem(
        ref_kind=ref_kind, canonical_id=canonical_id, title=title,
        category=category, match_cause="exact_name", evidence_status=evidence,
        snippet=snippet, focus=focus, ambiguity=ambiguity)


# ── 1. Подтверждённое ребро невозможно без проверенного основания ─────────

def test_confirmed_relation_without_sources_is_rejected():
    with pytest.raises(ValueError, match="verified independent"):
        _relation(status=mc.RelationStatus.CONFIRMED, sources=())


def test_confirmed_relation_with_only_mentions_is_rejected():
    mentions = _support(link_type="mentions",
                        origin_class=mc.OriginClass.COOCCURRENCE,
                        verification="verified", independence="independent")
    with pytest.raises(ValueError, match="verified independent"):
        _relation(status=mc.RelationStatus.CONFIRMED, sources=(mentions,))


def test_confirmed_relation_with_unverified_support_is_rejected():
    weak = _support(verification="tentative")
    with pytest.raises(ValueError, match="verified independent"):
        _relation(status=mc.RelationStatus.CONFIRMED, sources=(weak,))


def test_verified_support_requires_resolvable_source():
    with pytest.raises(ValueError, match="resolvable source"):
        mc.RelationSourceView(
            link_type="supports",
            origin_class=mc.OriginClass.EXPLICIT_DIRECT,
            verification="verified", independence="independent",
            established_at=1_760_000_000, source_ref_id=None, fact_id=None)


def test_legacy_origin_cannot_be_verified_support():
    with pytest.raises(ValueError, match="supporting origin class"):
        _support(origin_class=mc.OriginClass.LEGACY_UNKNOWN)


# ── 2. mentions/совстречаемость не подтверждают ───────────────────────────

def test_mentions_never_counts_as_independent_support():
    relation = _relation(
        status=mc.RelationStatus.TENTATIVE,
        sources=(_support(ref_id=1, link_type="mentions",
                          origin_class=mc.OriginClass.COOCCURRENCE,
                          verification="verified",
                          independence="independent"),),
        explanation="Аня упомянула Бориса")
    assert relation.independent_support == 0
    assert relation.has_unsupported_sources is True
    assert relation.origin_class is mc.OriginClass.COOCCURRENCE


def test_mentions_only_relation_never_confirmed_by_frequency():
    """R-2/R-11: частота не делает ребро подтверждённым."""
    mentions = (_support(link_type="mentions",
                         origin_class=mc.OriginClass.COOCCURRENCE,
                         verification="verified", independence="independent"),)
    with pytest.raises(ValueError, match="verified independent"):
        _relation(status=mc.RelationStatus.CONFIRMED, sources=mentions,
                  frequency=mc.edge_weight_cap())


def test_same_root_twice_counts_once():
    sources = (_support(ref_id=500), _support(ref_id=500,
                                              link_type="derived_from"))
    relation = _relation(sources=sources)
    assert relation.independent_support == 1


def test_three_distinct_roots_count_three():
    sources = (
        _support(ref_id=500),
        _support(ref_id=501, link_type="derived_from",
                 origin_class=mc.OriginClass.DERIVED_WITH_LINEAGE),
        _support(ref_id=502, fact_id=77),
    )
    relation = _relation(sources=sources)
    assert relation.independent_support == 3
    assert relation.verification_summary["sources_total"] == 3


# ── 3. Сильнейший проверенный корень, legacy отдельно ─────────────────────

def test_legacy_sources_reported_separately_without_demotion():
    sources = (
        _support(ref_id=500),
        _legacy_source(901),
        _legacy_source(902),
    )
    relation = _relation(status=mc.RelationStatus.CONFIRMED, sources=sources)
    assert relation.status is mc.RelationStatus.CONFIRMED
    assert relation.origin_class is mc.OriginClass.EXPLICIT_DIRECT
    assert relation.independent_support == 1
    assert relation.legacy_sources_count == 2
    assert relation.has_unsupported_sources is True


def test_strongest_verified_root_wins_over_weaker_verified_root():
    sources = (
        _support(ref_id=500, link_type="derived_from",
                 origin_class=mc.OriginClass.QUOTE_FORWARD),
        _support(ref_id=501, origin_class=mc.OriginClass.EXPLICIT_DIRECT),
    )
    assert _relation(sources=sources).origin_class is (
        mc.OriginClass.EXPLICIT_DIRECT)


def test_legacy_relation_is_explicit_and_not_confirmed():
    relation = mc.RelationView.legacy(
        edge_id=5, chat_id=CHAT, source_entity_id=7, target_entity_id=9,
        relation_type="знает", relation_label="Знает")
    assert relation.status is mc.RelationStatus.UNVERIFIED
    assert relation.origin_class is mc.OriginClass.LEGACY_UNKNOWN
    assert relation.has_unsupported_sources is True
    assert relation.independent_support == 0
    assert relation.explanation == mc.LEGACY_EXPLANATION
    assert relation.frequency <= mc.edge_weight_cap()
    with pytest.raises(ValueError):
        mc.RelationView(
            edge_id=5, chat_id=CHAT, source_entity_id=7, target_entity_id=9,
            relation_type="знает", relation_label="Знает",
            status=mc.RelationStatus.CONFIRMED)


def test_edge_legacy_weight_cap_is_below_confirmed():
    """R-7: cap legacy-ребра 0.55 берётся из своего дома, не дублируется."""
    assert mc.legacy_edge_weight_cap() == (
        graphrag_provenance._BARE_EDGE_WEIGHT_CAP)
    assert mc.legacy_edge_weight_cap() < 1.0


# ── 4. Неоднозначность не конвертируется в резолв/слияние ─────────────────

def _ambiguous() -> mc.EntityResolution:
    scope = mc.EntityScope(chat_id=CHAT, entity_type="user")
    return mc.EntityResolution(
        status="ambiguous", scope=scope, normalized_mention="саша",
        candidates=(
            mc.ResolutionCandidate(ref=_entity(1, name="Саша"),
                                  reason="casefold", discriminator="чат 1"),
            mc.ResolutionCandidate(ref=_entity(2, name="Саша"),
                                  reason="casefold", discriminator="чат 2"),
        ),
        reason_code="casefold_ambiguous")


def test_ambiguous_cannot_carry_canonical():
    scope = mc.EntityScope(chat_id=CHAT, entity_type="user")
    with pytest.raises(ValueError, match="must not pick a canonical"):
        mc.EntityResolution(
            status="ambiguous", scope=scope, normalized_mention="саша",
            canonical=_entity(1),
            candidates=_ambiguous().candidates)


def test_ambiguous_requires_two_variants_with_discriminator():
    scope = mc.EntityScope(chat_id=CHAT, entity_type="user")
    with pytest.raises(ValueError, match=">= 2 candidates"):
        mc.EntityResolution(status="ambiguous", scope=scope,
                            normalized_mention="саша",
                            candidates=_ambiguous().candidates[:1])
    with pytest.raises(ValueError, match="discriminator"):
        mc.ResolutionCandidate(ref=_entity(1), reason="casefold",
                               discriminator="  ")


def test_resolved_rejects_candidate_list_and_wrong_chat():
    scope = mc.EntityScope(chat_id=CHAT, entity_type="user")
    with pytest.raises(ValueError, match="must not carry candidates"):
        mc.EntityResolution(
            status="resolved", scope=scope, normalized_mention="аня",
            canonical=_entity(7), candidates=_ambiguous().candidates)
    with pytest.raises(ValueError, match="same chat"):
        mc.EntityResolution(
            status="resolved", scope=scope, normalized_mention="аня",
            canonical=_entity(7, chat_id=CHAT + 1))


def test_resolution_exposes_no_merge_operation():
    statuses = {s.value for s in mc.EntityResolutionStatus}
    assert statuses == {"resolved", "ambiguous", "new", "rejected"}
    assert not any("merge" in name.lower() for name in dir(mc.EntityResolution))
    assert not any("merge" in name.lower() for name in dir(mc.EntityRef))
    # слияние не выражается и через неизменяемость типов
    with pytest.raises(Exception):
        _ambiguous().status = mc.EntityResolutionStatus.RESOLVED


def test_rejected_resolution_requires_reason():
    scope = mc.EntityScope(chat_id=CHAT, entity_type="user")
    with pytest.raises(ValueError, match="reason_code"):
        mc.EntityResolution(status="rejected", scope=scope,
                            normalized_mention="папаха")
    rejected = mc.EntityResolution(
        status="rejected", scope=scope, normalized_mention="Папаха",
        reason_code="type_conflict_single_slot",
        candidates=(mc.ResolutionCandidate(
            ref=_entity(3, entity_type="topic"),
            reason="type_conflict", discriminator="другой тип: topic"),))
    assert rejected.canonical is None


def test_entity_ref_identity_rules():
    with pytest.raises(ValueError, match="entity_type"):
        _entity(entity_type="community")
    with pytest.raises(ValueError, match="display_name"):
        _entity(name="   ")
    with pytest.raises(ValueError, match="canonical node_id"):
        _entity(node_id=7, legacy=(7,))
    with pytest.raises(ValueError, match="degraded"):
        mc.EntityResolution(
            status="new", scope=mc.EntityScope(chat_id=CHAT,
                                               entity_type="user"),
            normalized_mention="x", degraded=("invented_reason",))


# ── 5. Модальность: отсутствующий сигнал = unknown ────────────────────────

def test_assertion_mode_defaults_to_unknown():
    assert mc.resolve_assertion_mode() is mc.AssertionMode.UNKNOWN
    assert mc.AssertionMode.UNKNOWN.value == "unknown"
    assert _support().assertion_mode is mc.AssertionMode.ASSERTED
    unknown = mc.RelationSourceView(
        link_type="supports", origin_class=mc.OriginClass.EXPLICIT_DIRECT,
        verification="tentative", independence="unknown",
        established_at=1_760_000_000, source_ref_id=1)
    assert unknown.assertion_mode is mc.AssertionMode.UNKNOWN


@pytest.mark.parametrize("signals,expected", [
    ({"forwarded": True}, mc.AssertionMode.QUOTED),
    ({"forward_from": "канал"}, mc.AssertionMode.QUOTED),
    ({"perspective": "quoted"}, mc.AssertionMode.QUOTED),
    ({"perspective": "third_party"}, mc.AssertionMode.REPORTED),
    ({"attribution_method": "third_party"}, mc.AssertionMode.REPORTED),
    ({"provenance_channel": "dream"}, mc.AssertionMode.INFERRED),
    ({"origin": "derived_belief"}, mc.AssertionMode.INFERRED),
    ({"denied": True}, mc.AssertionMode.DENIED),
    ({"perspective": "self",
      "attribution_method": "self_report"}, mc.AssertionMode.ASSERTED),
    ({"perspective": "self"}, mc.AssertionMode.UNKNOWN),
    ({"hypothetical": True}, mc.AssertionMode.HYPOTHETICAL),
    ({"joking": True}, mc.AssertionMode.JOKING),
])
def test_assertion_mode_from_real_signals_only(signals, expected):
    assert mc.resolve_assertion_mode(**signals) is expected


# ── 6. Время: три мгновения раздельны, «сейчас» не подставляется ──────────

def test_temporal_fields_are_not_defaulted():
    source = _support()
    assert source.asserted_ts is None
    assert source.event_ts is None
    assert source.observed_ts is None
    relation = _relation(sources=(source,))
    assert relation.valid_from is None
    assert relation.valid_to is None
    assert relation.last_confirmed is None


def test_temporal_fields_kept_when_supplied_and_validated():
    source = _support(asserted_ts=1_700_000_000, event_ts=1_600_000_000,
                      observed_ts=1_760_000_000)
    relation = _relation(sources=(source,), valid_from=1_500_000_000)
    assert relation.sources[0].asserted_ts == 1_700_000_000
    assert relation.sources[0].event_ts == 1_600_000_000
    assert relation.sources[0].observed_ts == 1_760_000_000
    assert relation.valid_from == 1_500_000_000
    assert relation.valid_to is None
    with pytest.raises(ValueError, match="valid_from"):
        _relation(sources=(source,), valid_from=10, valid_to=5)


# ── 7. Исходы ответа поиска взаимоисключающие ─────────────────────────────

def test_outcome_values_are_distinct_and_complete():
    statuses = {s.value for s in mc.SearchStatus}
    states = {s.value for s in mc.QueryState}
    assert statuses == {"ok", "ambiguous", "empty", "legacy_only", "partial",
                        "forbidden", "error", "cursor_stale"}
    assert states == {"local_matches", "server_searching", "candidates",
                      "no_matches", "weak_legacy_only", "partial", "error",
                      "no_rights"}
    assert len(statuses) == 8 and len(states) == 8


@pytest.mark.parametrize("kwargs", [
    # «пусто» не подменяет «нет прав»
    dict(status="empty", query_state="no_rights"),
    # ошибка не подменяется «нет совпадений»
    dict(status="error", query_state="no_matches"),
    # устаревший курсор не «пустой результат»
    dict(status="cursor_stale", query_state="no_matches"),
    # отсутствие прав не «кандидаты»
    dict(status="forbidden", query_state="candidates"),
    # legacy-only не подтверждённая выдача
    dict(status="legacy_only", query_state="candidates"),
])
def test_outcome_matrix_rejects_mixed_states(kwargs):
    base = dict(revision=_revision(), generation=1, scope=mc.SearchScope(
        mode="chat", chat_id=CHAT))
    base.update(kwargs)
    with pytest.raises(ValueError, match="not a valid outcome"):
        mc.SearchResponse(**base)


@pytest.mark.parametrize("status,state", [
    ("ok", "local_matches"), ("ok", "server_searching"),
    ("ok", "candidates"), ("ambiguous", "candidates"),
    ("empty", "no_matches"), ("legacy_only", "weak_legacy_only"),
    ("partial", "partial"), ("forbidden", "no_rights"),
    ("error", "error"), ("cursor_stale", "local_matches"),
])
def test_outcome_matrix_accepts_own_state(status, state):
    scope = mc.SearchScope(mode="chat", chat_id=CHAT,
                           partial=(status == "partial"))
    kwargs = {}
    if status in ("ok", "ambiguous", "legacy_only", "partial"):
        item = _item(evidence="tentative" if status == "legacy_only"
                     else "confirmed")
        if status == "ambiguous":
            item = _item(ambiguity=mc.SearchAmbiguity(
                reason="одно имя у двух людей",
                variants=(mc.SearchVariant(
                    canonical_id=f"ent:{CHAT}:1", title="Саша",
                    discriminator="чат 1"),
                    mc.SearchVariant(
                        canonical_id=f"ent:{CHAT}:2", title="Саша",
                        discriminator="чат 2"))))
        kwargs["items"] = (item,)
    if status == "cursor_stale":
        kwargs["reason_code"] = "cursor_revision_mismatch"
    response = mc.SearchResponse(
        status=status, query_state=state, revision=_revision(), generation=3,
        scope=scope, **kwargs)
    assert response.status == status and response.query_state == state


def test_cursor_stale_is_not_empty_and_carries_reason():
    common = dict(query_state="local_matches", revision=_revision(),
                  generation=2, scope=mc.SearchScope(mode="chat",
                                                     chat_id=CHAT))
    with pytest.raises(ValueError, match="reason_code"):
        mc.SearchResponse(status="cursor_stale", **common)
    stale = mc.SearchResponse(status="cursor_stale",
                              reason_code="cursor_revision_mismatch", **common)
    assert stale.items == () and stale.next_cursor is None
    assert not stale.has_more
    empty = mc.SearchResponse(status="empty", query_state="no_matches",
                              revision=_revision(), generation=2,
                              scope=mc.SearchScope(mode="chat",
                                                   chat_id=CHAT))
    assert stale.as_dict()["status"] != empty.as_dict()["status"]


def test_pagination_flags_and_scope_partial_consistency():
    item = _item()
    with pytest.raises(ValueError, match="has_more=True requires next_cursor"):
        mc.SearchResponse(status="ok", query_state="candidates",
                          revision=_revision(), generation=1,
                          scope=mc.SearchScope(mode="chat", chat_id=CHAT),
                          items=(item,), has_more=True)
    with pytest.raises(ValueError, match="next_cursor requires has_more"):
        mc.SearchResponse(status="ok", query_state="candidates",
                          revision=_revision(), generation=1,
                          scope=mc.SearchScope(mode="chat", chat_id=CHAT),
                          items=(item,), next_cursor="abc")
    with pytest.raises(ValueError, match="scope.partial=True"):
        mc.SearchResponse(status="partial", query_state="partial",
                          revision=_revision(), generation=1,
                          scope=mc.SearchScope(mode="chat", chat_id=CHAT),
                          items=(item,))
    page = mc.SearchResponse(status="ok", query_state="candidates",
                             revision=_revision(), generation=1,
                             scope=mc.SearchScope(mode="chat", chat_id=CHAT),
                             items=(item,), next_cursor="abc", has_more=True)
    assert page.has_more and page.next_cursor == "abc"


def test_legacy_only_response_cannot_carry_confirmed_items():
    with pytest.raises(ValueError, match="must not carry confirmed"):
        mc.SearchResponse(status="legacy_only",
                          query_state="weak_legacy_only",
                          revision=_revision(), generation=1,
                          scope=mc.SearchScope(mode="chat", chat_id=CHAT),
                          items=(_item(evidence="confirmed"),))


# ── 8. Превью ограничено и без внутренних id ──────────────────────────────

def test_preview_uses_shared_constant_and_bounds_snippet():
    limit = mca_retrieval_context._PREVIEW_MAX_CHARS
    assert mc.preview_max_chars() == limit
    assert mc.PREVIEW_MAX_CHARS == limit
    assert _item(snippet="а" * limit).as_dict()["snippet"]
    with pytest.raises(ValueError, match="longer than"):
        _item(snippet="а" * (limit + 1))


def test_human_texts_reject_internal_ids():
    with pytest.raises(ValueError, match="internal ids"):
        _item(title="Аня (node_id 7)")
    with pytest.raises(ValueError, match="internal ids"):
        _item(snippet="источник source_ref_id=501")
    with pytest.raises(ValueError, match="internal ids"):
        _relation(explanation="связь edge:11 cosine=0.93")


# ── 9. Сериализация: стабильный круг и никаких лишних id ──────────────────

def _response() -> mc.SearchResponse:
    item = _item(
        snippet="Аня говорила о Борисе в октябре",
        focus=mc.SearchFocus(chat_id=CHAT, node_id=7))
    fact = mc.SearchItem(
        ref_kind="fact", canonical_id="fact:42", title="Переезд в октябре",
        category="Событие", match_cause="fts", evidence_status="tentative",
        event_ts=1_700_000_000, observed_ts=1_760_000_000)
    return mc.SearchResponse(
        status="ok", query_state="candidates", revision=_revision(),
        generation=4, scope=mc.SearchScope(mode="chat", chat_id=CHAT),
        items=(item, fact), next_cursor="cursor-1", has_more=True,
        debug={"channels": [{"channel": "exact", "hits": 1}]})


def test_serialization_roundtrip_is_stable():
    response = _response()
    payload = response.as_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    restored = mc.SearchResponse.from_dict(payload)
    assert restored == response
    assert restored.as_dict() == payload
    # повторный круг не меняет формы
    assert mc.SearchResponse.from_dict(restored.as_dict()).as_dict() == payload


def test_serialization_has_no_internal_ids_beyond_canonical_refs():
    payload = _response().as_dict()

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                yield path, key
                yield from walk(value, path + (key,))
        elif isinstance(node, list):
            for value in node:
                yield from walk(value, path)

    allowed_chat_id = {("focus",), ("scope",)}
    allowed_node_id = {("focus",)}
    for path, key in walk(payload, ()):
        if key == "chat_id":
            assert path[-1:] in allowed_chat_id, f"chat_id at {path}"
        if key == "node_id":
            assert path[-1:] in allowed_node_id, f"node_id at {path}"
        assert key not in {"edge_id", "source_ref_id", "fact_id"}, path
    # канонические ссылки — единственный адрес во выдаче
    assert payload["items"][0]["canonical_id"].startswith("ent:")
    assert payload["items"][1]["canonical_id"].startswith("fact:")


def test_relation_serialization_reports_derived_values():
    payload = _relation(sources=(_support(ref_id=500),
                                 _legacy_source(901))).as_dict()
    assert payload["independent_support"] == 1
    assert payload["legacy_sources_count"] == 1
    assert payload["has_unsupported_sources"] is True
    assert payload["origin_class"] == "explicit_direct"
    assert payload["revision"] == {"graph": "", "edge_updated_at": None}
    assert mc.RelationView.from_dict(payload).as_dict() == payload


# ── 10. Константы и чистота модуля ────────────────────────────────────────

def test_shared_constants_come_from_real_homes():
    from services import database
    assert mc.EDGE_WEIGHT_CAP == database._EDGE_WEIGHT_CAP == 5
    assert mc.edge_weight_cap() == database._EDGE_WEIGHT_CAP
    assert mc.LEGACY_EDGE_WEIGHT_CAP == (
        graphrag_provenance._BARE_EDGE_WEIGHT_CAP)
    assert mc.PREVIEW_MAX_CHARS == mca_retrieval_context._PREVIEW_MAX_CHARS
    assert mc.LINK_TYPES is provenance.LINK_TYPES
    assert mc.VERIFICATIONS is provenance.VERIFICATIONS
    assert mc.INDEPENDENCES is provenance.INDEPENDENCES
    assert mc.SEARCH_LIMIT_MAX == 20
    assert mc.ENTITY_TYPES_ALLOWED == ("user", "topic", "event", "fact")
    assert "mentions" in mc.LINK_TYPES and "supports" in mc.LINK_TYPES


def test_module_is_pure_types_no_sql_no_db_imports():
    path = Path(mc.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_modules = {
        "sqlite3", "aiosqlite", "services.database", "services.summary_memory",
        "services.mca_retrieval_context", "services.graphrag_provenance",
    }
    sql_markers = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "PRAGMA ",
                   "CREATE TABLE", "DROP TABLE", "ALTER TABLE")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = ([a.name for a in node.names]
                     if isinstance(node, ast.Import)
                     else [node.module or ""])
            for name in names:
                assert not any(name == m or name.startswith(m + ".")
                               for m in forbidden_modules), name
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = node.value.upper()
            for marker in sql_markers:
                assert marker not in upper, f"SQL marker in {path.name}"
    source = path.read_text(encoding="utf-8")
    assert "def save(" not in source and "def insert(" not in source


# ── 11. Интент поиска и краткоживущая выборка ─────────────────────────────

def test_search_intent_validation():
    scope = mc.SearchScope(mode="chat", chat_id=CHAT)
    intent = mc.SearchIntent(
        q="кто такая Аня", scope=scope, mode="specific",
        intents=(mc.IntentHint(kind="person", weight=0.8),),
        subjects=(_entity(7),),
        ambiguous_subjects=(_ambiguous(),),
        terms=("аня",), quoted=("аня",),
        time_hint=mc.TimeHint(tz_source="chat",
                              time_from=1_700_000_000,
                              time_to=1_700_100_000))
    assert intent.as_dict()["mode"] == "specific"
    assert mc.SearchIntent.from_dict(intent.as_dict()).as_dict() == (
        intent.as_dict())
    with pytest.raises(ValueError, match="q longer"):
        mc.SearchIntent(q="я" * 201, scope=scope, mode="specific")
    with pytest.raises(ValueError, match="weight"):
        mc.IntentHint(kind="person", weight=1.5)
    with pytest.raises(ValueError, match="only 'ambiguous' resolutions"):
        mc.SearchIntent(q="аня", scope=scope, mode="specific",
                        ambiguous_subjects=(mc.EntityResolution(
                            status="resolved",
                            scope=mc.EntityScope(chat_id=CHAT,
                                                 entity_type="user"),
                            normalized_mention="аня",
                            canonical=_entity(7)),))
    with pytest.raises(ValueError, match="must not be after"):
        mc.TimeHint(tz_source="chat", time_from=10, time_to=5)


def test_scope_all_requires_no_single_chat():
    assert mc.SearchScope(mode="scope_all").chat_id is None
    with pytest.raises(ValueError, match="must not pin"):
        mc.SearchScope(mode="scope_all", chat_id=CHAT)
    with pytest.raises(ValueError, match="requires chat_id"):
        mc.SearchScope(mode="chat")


def test_memory_view_is_ordered_selection_not_storage():
    refs = (mc.MemoryViewRef(canonical_id=f"ent:{CHAT}:7", ref_kind="entity",
                             rank=1, selection_reason="прямое упоминание"),
            mc.MemoryViewRef(canonical_id="fact:42", ref_kind="fact", rank=2,
                             selection_reason="подтверждающий факт",
                             evidence_status="tentative"))
    view = mc.MemoryView(purpose="reply", refs=refs)
    assert [r.rank for r in view.refs] == [1, 2]
    assert mc.MemoryView.from_dict(view.as_dict()).as_dict() == view.as_dict()
    with pytest.raises(ValueError, match="ranks must be 1..N"):
        mc.MemoryView(purpose="reply", refs=(refs[1], refs[0]))
    with pytest.raises(ValueError, match="canonical_id must start"):
        mc.MemoryViewRef(canonical_id="fact:42", ref_kind="entity", rank=1,
                         selection_reason="x")


def test_canonical_ids_of_each_kind_are_accepted():
    cases = {
        "entity": f"ent:{CHAT}:7",
        "fact": "fact:42",
        "episode": "episode:abc",
        "community": "comm:build-1:12",
        "relation": "edge:11",
    }
    for ref_kind, canonical_id in cases.items():
        item = mc.SearchItem(
            ref_kind=ref_kind, canonical_id=canonical_id, title="Название",
            category="Тема", match_cause="fts", evidence_status="unknown")
        assert item.as_dict()["canonical_id"] == canonical_id
    with pytest.raises(ValueError, match="must start with 'ent:'"):
        _item(ref_kind="entity", canonical_id="fact:42")
