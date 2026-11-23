"""VMQ-MEM RC4 (A2+D4): retrieval-only short stem and year-token filtering."""
import datetime

import pytest

from services.mca_retrieval_context import (
    PERIOD_MIN_SHARED_STEMS,
    PERIOD_SOFT_FALLBACK_MIN_ROWS,
    _period_fts_keywords,
    _tokenize,
    period_subject_shared,
    period_subject_stems,
    resolve_period_intent,
    select_period_rows,
)
from services.summary_memory import build_fts_query
from services.text_morphology import short_stem_word, stem_word

CHAT = -1002661910336
YEAR_TS = int(datetime.datetime(
    2024, 6, 1, tzinfo=datetime.timezone.utc).timestamp())


def _fact(fid, text, year=2024, status="confirmed"):
    ts = int(datetime.datetime(
        year, 6, 1, tzinfo=datetime.timezone.utc).timestamp())
    return {
        "id": fid, "fact": text, "status": status,
        "message_timestamp": ts, "created_at": ts, "rag_ts": ts,
        "expires_at": None, "origin": "chat_history",
    }


def test_short_stem_is_additive_and_blocks_generic_noise():
    # Global stem_word is not changed.
    assert stem_word("шизах") == "шизах"
    assert short_stem_word("шизах") == "шиз"
    assert short_stem_word("шизы") == "шиз"
    assert short_stem_word("шиз") == "шиз"
    # E-control: year/chat variants are forbidden.
    assert short_stem_word("годы") == ""
    assert short_stem_word("годах") == ""
    assert short_stem_word("чата") == ""
    assert short_stem_word("2025") == ""


def test_period_fts_adds_short_variant_only_in_additive_mode():
    additive = build_fts_query(["шизах"], mode="prefix_or_stem_short")
    assert '"шизах"*' in additive
    assert '"шиз"*' in additive
    # Default and existing stem mode remain byte-identical for the short case.
    assert '"шиз"*' not in build_fts_query(["шизах"], mode="prefix_or")
    assert '"шиз"*' not in build_fts_query(["шизах"], mode="prefix_or_stem")


def test_period_stems_share_short_variant_and_threshold_unchanged():
    assert PERIOD_MIN_SHARED_STEMS == 2
    assert PERIOD_SOFT_FALLBACK_MIN_ROWS == 2
    # Short stem is an ALTERNATIVE, not a second stem: one word cannot count
    # as two shared subjects.
    assert period_subject_stems("шизах") == {"шиз"}
    assert period_subject_stems("шизы") == {"шиз"}
    new_stems = period_subject_stems("шизах конфы")
    assert "шиз" in new_stems
    # Old len>=4-only normalization would see only {шизах, конф}; new sees {шиз}.
    assert period_subject_shared({"шизах", "конф"}, "шиз конфы") == 1
    assert period_subject_shared(new_stems, "шиз конфы") == 2

    intent = resolve_period_intent("шизах конфы", memory_scope="historical")
    accepted, stats = select_period_rows(
        [_fact(1, "шиз конфы")], query="шизах конфы", intent=intent,
        policy="historical", slots=2)
    assert [row["id"] for row in accepted] == [1]
    assert stats["lexical_strict_passed"] == 1
    assert stats["dropped_subject"] == 0


def test_stopword_short_stem_does_not_bypass_threshold():
    # RC4-R1-01: служебные `что/для/меня` не должны получать short stem и
    # делать unrelated `тебя`-факт «тем же предметом». Normal len>=4 stems
    # (меня/было) остаются для различения, short — только для content.
    query = "что было для меня?"
    fact_match = _fact(1, "что было для меня и работа", year=2024)
    unrelated = _fact(2, "что было для тебя", year=2024)
    stems = period_subject_stems(query)
    assert "мен" not in stems
    assert "меня" in stems and "был" in stems
    intent = resolve_period_intent(query, memory_scope="historical")
    accepted, stats = select_period_rows(
        [fact_match, unrelated], query=query, intent=intent,
        policy="historical", slots=2)
    assert [row["id"] for row in accepted] == [1]
    assert stats["lexical_strict_passed"] == 1
    assert stats["dropped_subject"] == 1


def test_explicit_year_removes_year_and_preposition_tokens():
    tokens = _tokenize("что известно о конфликте Корсара с Олей в 2025 году?")
    old = _period_fts_keywords(tokens, explicit_year=False)
    new = _period_fts_keywords(tokens, explicit_year=True)
    assert "2025" in old and "году" in old
    assert "2025" not in new and "году" not in new
    assert {"известно", "конфликте", "корсара", "олей"} <= set(new)
    match = build_fts_query(new, mode="prefix_or_stem_short")
    assert '"2025"*' not in match
    assert '"году"*' not in match

    # Year words are not query stems when explicit; non-explicit keeps them.
    explicit_stems = period_subject_stems(
        "конфликт 2025 году", explicit_year=True)
    default_stems = period_subject_stems("конфликт 2025 году")
    assert "2025" not in explicit_stems and "году" not in explicit_stems
    assert "2025" in default_stems and "году" in default_stems
    # E-control: `годы`/`чата` do not gain `год`/`чат` noise.
    e_stems = period_subject_stems("как менялось отношение чата к Диане за годы?")
    assert "год" not in e_stems and "чат" not in e_stems
    assert "годы" in e_stems and "чата" in e_stems


@pytest.mark.asyncio
async def test_short_stem_does_not_replace_old_year_in_pool():
    # A2 is selection/normalization only; explicit-year filter remains the
    # authority for year. Old 2023/2024 facts must be reachable alongside 2026.
    old = _fact(10, "шиз конфы", year=2023)
    new = _fact(11, "шизах 2026", year=2026)
    intent = resolve_period_intent("шизах конфы", memory_scope="historical")
    accepted, _ = select_period_rows(
        [old, new], query="шизах конфы", intent=intent,
        policy="historical", slots=2)
    ids = {row["id"] for row in accepted}
    assert 10 in ids
