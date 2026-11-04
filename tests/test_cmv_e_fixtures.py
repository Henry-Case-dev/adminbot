"""Фикстуры приёмки CMV-E (EPIC-CM-VISUAL-01, §10.2) — контракт данных.

Тест держит ровно одно обещание: коммитнутые `cog_map_10/100/702.json` — это
выход `cog_map_fixtures.payload()` без расхождений, и в них ровно те размеры,
которые требует спека §10.2 (10 / 100 / 702 узла с 2400 рёбрами). Если кто-то
правит фикстуру руками или меняет генератор, не пересоздав файлы, приёмка
FPS/визуала начнёт мерить не тот набор — тест это ловит.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "cmv"
sys.path.insert(0, str(FIX))

import cog_map_fixtures as F  # noqa: E402


def test_committed_fixtures_match_generator():
    for n in F.SIZES:
        with open(F.path_for(n), encoding="utf-8") as fh:
            text = fh.read().rstrip("\n")
        assert text == F.canonical(F.payload(n)), (
            "фикстура cog_map_%d.json разошлась с генератором — "
            "пересоздайте: python tests/fixtures/cmv/cog_map_fixtures.py" % n)


def test_sizes_are_exactly_the_spec_sizes():
    for n in F.SIZES:
        data = F.load(n)
        assert len(data["nodes"]) == n
        assert len(data["edges"]) == F.EDGES == 2400
        assert data["shown_of"]["nodes"] == n
        assert data["shown_of"]["edges"] == 2400


def test_ids_are_unique_and_edges_reference_real_nodes():
    for n in F.SIZES:
        data = F.load(n)
        ids = [node["id"] for node in data["nodes"]]
        assert len(ids) == len(set(ids)), n
        edge_ids = [edge["id"] for edge in data["edges"]]
        assert len(edge_ids) == len(set(edge_ids)), n
        known = set(ids)
        for edge in data["edges"]:
            assert edge["from"] in known and edge["to"] in known


def test_fixtures_carry_spec_edge_cases():
    """§11: одинаковые имена, длинная подпись, изолированный узел, мультирёбра."""
    for n in F.SIZES:
        data = F.load(n)
        titles = [node["title"] for node in data["nodes"]]
        if n > 15:
            # §11: несколько разных записей с ОДИНАКОВЫМ именем.
            assert sum(1 for t in titles if t.startswith("same name")) >= 3
        if n >= 13:
            assert any(len(title) > 100 for title in titles), "длинная подпись"
        pairs = {(e["from"], e["to"]) for e in data["edges"]}
        if n == 10:
            # 2400 рёбер на 10 узлов — это и есть «несколько связей между
            # одной парой» (§11), а не 2400 разных пар.
            assert len(pairs) < 2400
    small = F.load(10)
    isolated = [node for node in small["nodes"] if node["isolated"]]
    assert isolated, "изолированный узел нужен для §11"
    isolated_id = isolated[0]["id"]
    assert not any(e["from"] == isolated_id or e["to"] == isolated_id
                   for e in small["edges"])
    assert small["shown_of"]["distinct_pairs"] == len(
        {(e["from"], e["to"]) for e in small["edges"]})


def test_fixture_is_deterministic_across_calls():
    a = json.dumps(F.payload(100), sort_keys=True)
    b = json.dumps(F.payload(100), sort_keys=True)
    assert a == b
    assert F.sha256(F.payload(100)) == F.sha256(F.load(100))
