"""ASAP-3.2 (ADR-1028-5 D8/D9, §37–§43, §72) — hierarchical semantic
reduction FactPackage: никакого позиционного выбрасывания уникального
контента на нормальном пути; дубликаты сжимаются, уникальность сохраняется;
если редуцированный пакет не влезает в бюджет ОДНОГО L2-вызова — paged L2
(каждая страница ≤ budget), НИКОГДА silent drop.

§72 acceptance: large window + large L1 result → source coverage 100% /
unique topic coverage 100% / no destructive skipped_fragments=354 /
hierarchical reduction invoked / L2 input under effective budget (по
страницам).
"""
import json

import pytest

import services.summary_fact_package as sfp
import services.summary_semantic_reduction as ssr

pytestmark = pytest.mark.asap32


def _fact(text, evidence):
    return {"text": text, "evidence_message_ids": list(evidence)}


def _frag(mid, text, ts=1700000000):
    return {"message_id": mid, "author_id": 10, "display_name": "Вася",
            "timestamp": ts, "reply_to_id": None, "text": text}


def _thread(tid, name, facts, fragments, chronology):
    mids = [entry["message_id"] for entry in chronology]
    return {"thread_id": tid, "name": name, "description": "",
            "message_ids": mids,
            "chronology": chronology, "facts": facts,
            "evidence_ids": sorted({e for f in facts
                                    for e in f["evidence_message_ids"]}),
            "fragments": fragments}


class L1:
    def __init__(self, threads):
        self.status = "ok"
        self.payload = {"threads": threads, "unassigned_message_ids": []}
        self.truncated = False
        self.threads_count = len(threads)
        self.skipped_ids = ()
        self.chunk_count = 1
        self.invalid_reason = None


def _items(ids, text="текст сообщения"):
    return [{"message_id": mid, "author_id": 10, "display_name": "Вася",
             "timestamp": 1700000000 + i, "reply_to_id": None,
             "text": text} for i, mid in enumerate(ids)]


# ── §40/§39: редукция сжимает дубликаты, не теряя уникальность ──────────────

class TestSemanticReduction:
    def test_duplicate_facts_merged_with_evidence_union(self):
        threads = [
            _thread("T1", "Ремонт",
                    [_fact("Соседи шумят по ночам", [101, 102])],
                    [_frag(101, "соседи шумят")],
                    [{"message_id": 101, "timestamp": 1,
                      "topic_ids": ["T1"]}]),
            _thread("T2", "Ремонт",     # та же тема из другого chunk
                    [_fact("Соседи шумят по ночам", [102, 103]),
                     _fact("Ремонт лифта начался в мае", [104])],
                    [_frag(101, "соседи шумят"), _frag(104, "лифт")],
                    [{"message_id": 103, "timestamp": 3,
                      "topic_ids": ["T2"]}]),
        ]
        merged, stats = ssr.reduce_threads(threads)
        assert len(merged) == 1, "темы с одинаковым названием → одна"
        texts = [_norm(f["text"]) for f in merged[0]["facts"]]
        assert len(texts) == len(set(texts)), "факты без дубликатов"
        assert any("лифта" in t for t in texts), "уникальный факт сохранён"
        noise = [f for f in merged[0]["facts"]
                 if "шумят" in f["text"]]
        assert noise and sorted(noise[0]["evidence_message_ids"]) == \
            [101, 102, 103], "evidence union при merge"
        mids = [f["message_id"] for f in merged[0]["fragments"]]
        assert len(mids) == len(set(mids)), "fragments без дубликатов"
        assert stats.unique_dropped == 0, "§41: unique_dropped=0 — норма"
        assert stats.merged_duplicates >= 2
        assert stats.passes >= 1

    def test_cross_thread_fragment_dedupe_keeps_chronology(self):
        threads = [
            _thread("T1", "Тема А", [_fact("факт А", [1])],
                    [_frag(1, "общее сообщение")],
                    [{"message_id": 1, "timestamp": 1,
                      "topic_ids": ["T1"]}]),
            _thread("T2", "Тема Б", [_fact("факт Б", [1])],
                    [_frag(1, "общее сообщение")],
                    [{"message_id": 1, "timestamp": 1,
                      "topic_ids": ["T1", "T2"]}]),
        ]
        merged, stats = ssr.reduce_threads(threads)
        all_frag_mids = [f["message_id"] for t in merged
                         for f in t["fragments"]]
        assert all_frag_mids.count(1) == 1, \
            "один message_id — один fragment (дубликат текста убран)"
        # many-to-many знание в chronology сохранено
        assert any(len(t.get("chronology") or []) >= 1 for t in merged)
        assert stats.unique_dropped == 0

    def test_unique_content_never_dropped(self):
        """§40: уникальный факт/фрагмент/тема не выбрасывается редукцией."""
        threads = [
            _thread("T1", f"Тема {i}", [_fact(f"уникальный факт {i}", [i])],
                    [_frag(i, f"текст {i}")],
                    [{"message_id": i, "timestamp": i, "topic_ids": [f"T{i}"]}])
            for i in range(1, 8)
        ]
        merged, stats = ssr.reduce_threads(merged_check := threads)
        assert len(merged) == 7
        fact_texts = {f["text"] for t in merged for f in t["facts"]}
        assert fact_texts == {f"уникальный факт {i}" for i in range(1, 8)}
        assert stats.unique_dropped == 0
        assert stats.merged_duplicates == 0


def _norm(text):
    return " ".join(str(text or "").split()).casefold()


# ── §72: FactPackage end-to-end — бюджет через редукцию+pages ───────────────

class TestFactPackageNoDestructiveTruncation:
    def test_large_window_no_skipped_fragments_reduction_invoked(self):
        """§72: большой L1-результат → редукция вызвана, skipped_fragments=0,
        coverage metrics заполнены, unique_dropped=0."""
        threads = []
        for i in range(1, 41):
            threads.append(_thread(
                f"T{i}", "Обсуждение релиза",     # одна тема во всех chunks
                [_fact(f"уникальный факт релиза {i}", [100 + i])],
                [_frag(100 + i, f"текст {i} ")],
                [{"message_id": 100 + i, "timestamp": i,
                  "topic_ids": [f"T{i}"]}]))
        result = sfp.build_fact_package(
            L1(threads), _items(range(101, 141), "текст"),
            budget=("tokens", 3000))
        assert result.deliverable
        m = result.metrics
        assert m.get("semantic_reduction_passes", 0) >= 1, \
            "hierarchical reduction invoked"
        assert m.get("semantic_unique_dropped") == 0, "норма §41"
        assert m.get("skipped_fragments_count", 0) == 0, \
            "нет destructive skipped_fragments (прод-инцидент 267/354)"
        assert m.get("semantic_merged_duplicates", 0) >= 1
        # уникальные факты сохранены (unique topic coverage)
        kept_texts = {f["text"] for t in (result.package or {})["threads"]
                      for f in t["facts"]}
        for i in range(1, 41):
            assert f"уникальный факт релиза {i}" in kept_texts

    def test_paged_l2_when_reduction_cannot_fit(self):
        """§39/D8: после редукции не влезает в один бюджет → pages, каждая
        ≤ budget; НИКАКОГО silent drop (все уникальные элементы где-то есть)."""
        threads = []
        for i in range(1, 13):
            threads.append(_thread(
                f"T{i}", f"Отдельная тема {i}",
                [_fact(f"совершенно уникальный контент темы {i} " * 8,
                       [200 + i])],
                [_frag(200 + i, "наполненный текст фрагмента " * 30)],
                [{"message_id": 200 + i, "timestamp": i,
                  "topic_ids": [f"T{i}"]}]))
        result = sfp.build_fact_package(
            L1(threads), _items(range(201, 213), "наполненный текст"),
            budget=("tokens", 900))
        assert result.deliverable
        assert result.pages, "paged L2 задействован"
        m = result.metrics
        assert m.get("paged") is True and m.get("pages_count") == len(
            result.pages)
        assert m.get("skipped_fragments_count", 0) == 0
        total_facts: set = set()
        total_frags: set = set()
        for page in result.pages:
            assert page["budget"]["estimated"] <= 900, "страница ≤ budget"
            assert page["budget"]["fits"] is True
            for t in page["threads"]:
                for f in t["facts"]:
                    total_facts.add(_norm(f["text"]))
                for fr in t["fragments"]:
                    total_frags.add(fr["message_id"])
        for i in range(1, 13):
            assert any(f"темы {i}" in t for t in total_facts), \
                "уникальный контент темы сохранён хотя бы на одной странице"
            assert 200 + i in total_frags, "fragment сохранён"

    def test_kill_switch_off_positional_cascade_visible(self, monkeypatch):
        """§80 OFF-паритет: kill-switch OFF → прежний позиционный каскад;
        каждое срабатывание — видимое degraded-событие (§41/D8)."""
        monkeypatch.setattr(type(sfp.settings),
                            "SUMMARY_SEMANTIC_REDUCTION_ENABLED", False,
                            raising=False)
        threads = [_thread(
            f"T{i}", f"Тема {i}",
            [_fact(f"факт номер {i} с содержанием", [300 + i])],
            [_frag(300 + i, "достаточно длинный текст фрагмента " * 12)],
            [{"message_id": 300 + i, "timestamp": i, "topic_ids": [f"T{i}"]}])
            for i in range(1, 8)]
        result = sfp.build_fact_package(
            L1(threads), _items(range(301, 308),
                                "достаточно длинный текст фрагмента "),
            budget=("tokens", 400))
        assert result.deliverable, "частичное усечение остаётся deliverable"
        assert result.pages == ()
        assert result.metrics.get("semantic_reduction_passes") is None
        assert result.metrics.get("skipped_threads_count", 0) >= 1 or \
            result.metrics.get("skipped_fragments_count", 0) >= 1

    def test_positional_failsoft_degraded_event_emitted(self, monkeypatch,
                                                        caplog):
        monkeypatch.setattr(type(sfp.settings),
                            "SUMMARY_SEMANTIC_REDUCTION_ENABLED", False,
                            raising=False)
        import logging
        with caplog.at_level(logging.WARNING,
                             logger="services.summary_fact_package"):
            threads = [_thread(
                f"T{i}", f"Тема {i}",
                [_fact(f"факт номер {i} с содержанием", [400 + i])],
                [_frag(400 + i, "достаточно длинный текст фрагмента " * 12)],
                [{"message_id": 400 + i, "timestamp": i,
                  "topic_ids": [f"T{i}"]}]) for i in range(1, 6)]
            result = sfp.build_fact_package(
                L1(threads),
                _items(range(401, 406),
                       "достаточно длинный текст фрагмента "),
                budget=("tokens", 300))
        assert result.deliverable
        assert any("FACT_PACKAGE_POSITIONAL_FAILSOFT" in r.message
                   for r in caplog.records), \
            "позиционный каскад = видимый degraded, не тихая норма"


# ── §42: oversized single message — lossless segmentation ───────────────────

class TestOversizedSegmentation:
    def test_segmentation_lossless_with_parts(self):
        big_text = "подробное сообщение про ремонт и соседей " * 80
        assert len(big_text) > sfp.FRAGMENT_MAX_CHARS
        threads = [_thread(
            "T1", "Гигантское сообщение",
            [_fact("упомянулся гигантский пост", [501])],
            [_frag(501, big_text)],
            [{"message_id": 501, "timestamp": 1, "topic_ids": ["T1"]}])]
        result = sfp.build_fact_package(L1(threads), _items([501], big_text))
        assert result.deliverable
        frags = result.package["threads"][0]["fragments"]
        parts = [f for f in frags if f["message_id"] == 501]
        assert len(parts) >= 2, "сегментация вместо обрезки"
        assert all(f.get("part") and f.get("part_total") == len(parts)
                   for f in parts)
        assert [f["part"] for f in parts] == list(range(1, len(parts) + 1))
        # lossless: конкатенация частей == исходный текст
        assert "".join(f["text"] for f in parts) == big_text
        # author/timestamp/reply сохранены в каждой части
        assert all(f["author_id"] == 10 and f["timestamp"] == 1700000000
                   and f["reply_to_id"] is None for f in parts)
        assert result.metrics.get("fragment_segmented_count", 0) == 1

    def test_short_fragment_unchanged_schema(self):
        threads = [_thread(
            "T1", "Обычное",
            [_fact("факт", [601])], [_frag(601, "короткий текст")],
            [{"message_id": 601, "timestamp": 1, "topic_ids": ["T1"]}])]
        result = sfp.build_fact_package(L1(threads), _items([601], "короткий"))
        frag = result.package["threads"][0]["fragments"][0]
        assert "part" not in frag and "part_total" not in frag, \
            "схема v2 обычных fragments без изменений"


# ── §43: empty-summary guard сохранён ───────────────────────────────────────

class TestEmptyGuardPreserved:
    def test_empty_guard_on_legacy_path_intact(self, monkeypatch, caplog):
        """§43 (legacy/OFF-путь): source>0 ∧ каскад опустошил пакет →
        fail-closed EMPTY (не deliverable) + громкое near_empty событие.
        Empty-summary guard ASAP-3.1 не откатан."""
        monkeypatch.setattr(type(sfp.settings),
                            "SUMMARY_SEMANTIC_REDUCTION_ENABLED", False,
                            raising=False)
        import logging
        with caplog.at_level(logging.WARNING,
                             logger="services.summary_fact_package"):
            threads = [_thread(
                "T1", "Тема",
                [_fact("факт", [701])],
                [_frag(701, "текст")],
                [{"message_id": 701, "timestamp": 1, "topic_ids": ["T1"]}])]
            result = sfp.build_fact_package(
                L1(threads), _items([701], "текст"),
                budget=("tokens", 1))
        assert not result.deliverable, "пустой по материалу → fail-closed"
        assert result.status == sfp.STATUS_EMPTY
        assert any("PACKAGE_NEAR_EMPTY" in r.message for r in caplog.records)

    def test_empty_l1_not_deliverable(self):
        """§43: L1 empty → пакет fail-closed (существующая семантика)."""
        class L1Empty:
            status = "empty"
            payload = None
            truncated = False
            threads_count = 0
            skipped_ids = ()
            chunk_count = 0
            invalid_reason = None

        result = sfp.build_fact_package(L1Empty(), _items([1], "текст"))
        assert not result.deliverable
        assert result.status == sfp.STATUS_EMPTY

    def test_unlimited_budget_no_paging(self):
        threads = [_thread(
            f"T{i}", f"Тема {i}", [_fact(f"факт {i} " * 20, [800 + i])],
            [_frag(800 + i, "текст " * 50)],
            [{"message_id": 800 + i, "timestamp": i, "topic_ids": [f"T{i}"]}])
            for i in range(1, 6)]
        result = sfp.build_fact_package(
            L1(threads), _items(range(801, 806), "текст"),
            budget=("tokens", 0))          # unlimited
        assert result.deliverable
        assert result.pages == (), "unlimited → без paging"
        assert result.metrics.get("skipped_fragments_count", 0) == 0


# ── Детерминизм ──────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_double_run_identical(self):
        threads = [
            _thread("T1", "Тема", [_fact("факт 1", [1]), _fact("факт 1", [2])],
                    [_frag(1, "т"), _frag(1, "т")],
                    [{"message_id": 1, "timestamp": 1, "topic_ids": ["T1"]}]),
            _thread("T2", "Тема", [_fact("факт 2", [3])],
                    [_frag(3, "т")],
                    [{"message_id": 3, "timestamp": 3, "topic_ids": ["T2"]}]),
        ]
        items = _items([1, 2, 3], "т")
        r1 = sfp.build_fact_package(L1(json.loads(json.dumps(
            [t for t in threads]))), items, budget=("tokens", 100000))
        r2 = sfp.build_fact_package(L1(json.loads(json.dumps(
            [t for t in threads]))), items, budget=("tokens", 100000))
        assert sfp.serialize_package(r1.package) == \
            sfp.serialize_package(r2.package)

