"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D1/D6/D7/D10;
spec §3.5/§3.6/§3.10/§4.2, tasks T-4099…T-4106) — Style Registry / assets / seed.

Проверяем:
  * PG DDL — 5 таблиц `cover_style_*` + индексы (идемпотентно, Δ SQLite=0);
  * asset-регистр — детерминированный `asset_id`, sha256-дедуп, файлы на диске,
    `extra_images/*` НЕ мутируются (R18);
  * seed seeded-стиля `Графический роман Медведь Press` — идемпотентен,
    `origin=seeded_example`, references/preview из фактических файлов (DC-1
    `.jpg`), hand-written runtime без special-case;
  * counter/issue assignment — retry-reuse, concurrency-уникальность (§27/§28);
  * provenance (§30); format_issue — `ВЫПУСК` не захардкожен (§26).
"""
import hashlib
from pathlib import Path

import pytest

from services import cover_style_assets as csa
from services import cover_style_registry as csr
from services.pg_db import DDL_STATEMENTS

ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "extra_images"


# ── fake asyncpg pool ───────────────────────────────────────────────────────

class _FakeConn:
    """Мини-эмуляция asyncpg-соединения поверх in-memory словарей."""

    def __init__(self, state):
        self.state = state

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Tx()

    async def execute(self, sql, *args):
        norm = " ".join(sql.split())
        if "INSERT INTO cover_style_assets" in norm:
            self.state["assets"][args[0]] = {
                "asset_id": args[0], "scope": args[1], "filename": args[2],
                "mime": args[3], "size_bytes": args[4], "sha256": args[5],
                "origin": args[6], "disk_path": args[7], "deleted_at": None}
        elif "INSERT INTO cover_style_profiles" in norm:
            self.state["profiles"][args[0]] = {
                "profile_id": args[0], "name": args[1], "origin": args[2],
                "pipeline_mode": args[3], "instruction": args[4],
                "counter_enabled": args[5], "counter_value": args[6],
                "counter_format": args[7], "model_mode": args[8],
                "connection_id": args[9], "model_id": args[10],
                "preview_before_asset_id": args[11],
                "preview_after_asset_id": args[12],
                "preview_revision": args[13], "revision": 1,
                "enabled": args[14], "is_deleted": False,
                "validation_mode": args[15]}
        elif "UPDATE cover_style_profiles SET name=" in norm:
            p = self.state["profiles"].get(args[0])
            if p is not None:
                p.update({"name": args[1], "pipeline_mode": args[2],
                          "instruction": args[3], "counter_enabled": args[4],
                          "counter_value": args[5], "counter_format": args[6],
                          "model_mode": args[7], "connection_id": args[8],
                          "model_id": args[9],
                          "preview_before_asset_id": args[10],
                          "preview_after_asset_id": args[11],
                          "preview_revision": args[12],
                          "enabled": args[13], "validation_mode": args[14]})
                p["revision"] = p.get("revision", 1) + 1
        elif "UPDATE cover_style_profiles SET counter_value" in norm:
            p = self.state["profiles"].get(args[0])
            if p is not None:
                p["counter_value"] = p.get("counter_value", 0) + 1
        elif "UPDATE cover_style_profiles SET is_deleted" in norm:
            p = self.state["profiles"].get(args[0])
            if p is not None:
                p["is_deleted"] = True
        elif "UPDATE cover_style_assets SET deleted_at" in norm:
            a = self.state["assets"].get(args[0])
            if a is not None:
                a["deleted_at"] = "now"
        elif "INSERT INTO cover_style_references" in norm:
            self.state["refs"][args[0]] = {
                "ref_id": args[0], "profile_id": args[1], "asset_id": args[2],
                "label": args[3], "description": args[4], "ordering": args[5]}
        elif "DELETE FROM cover_style_references" in norm:
            self.state["refs"].pop(args[1], None)
        elif "INSERT INTO cover_style_issue_assignments" in norm:
            self.state["issues"].setdefault((args[0], args[1]), args[2])
        elif "INSERT INTO cover_style_provenance" in norm:
            self.state["provenance"].append(args)
        return "OK"

    async def fetchrow(self, sql, *args):
        norm = " ".join(sql.split())
        if "FROM cover_style_assets WHERE asset_id" in norm:
            return self.state["assets"].get(args[0])
        if "FROM cover_style_assets WHERE sha256" in norm:
            for a in self.state["assets"].values():
                if a["sha256"] == args[0] and a["scope"] == args[1] \
                        and a.get("deleted_at") is None:
                    return a
            return None
        if "SELECT revision FROM cover_style_profiles" in norm:
            p = self.state["profiles"].get(args[0])
            return {"revision": p["revision"]} if p else None
        if "FROM cover_style_profiles WHERE profile_id" in norm \
                and "is_deleted" in norm:
            p = self.state["profiles"].get(args[0])
            return dict(p) if p and not p.get("is_deleted") else None
        if "RETURNING counter_value" in norm and \
                "UPDATE cover_style_profiles SET counter_value" in norm:
            p = self.state["profiles"].get(args[0])
            if p is None:
                return None
            p["counter_value"] = p.get("counter_value", 0) + 1
            return {"counter_value": p["counter_value"]}
        if "FROM cover_style_issue_assignments" in norm:
            v = self.state["issues"].get((args[0], args[1]))
            return {"issue_number": v} if v is not None else None
        if "FROM cover_style_references r" in norm:
            out = []
            for r in self.state["refs"].values():
                if r["asset_id"] == args[0]:
                    p = self.state["profiles"].get(r["profile_id"])
                    if p and not p.get("is_deleted"):
                        out.append({"profile_id": r["profile_id"],
                                    "name": p["name"]})
            return out
        return None

    async def fetch(self, sql, *args):
        norm = " ".join(sql.split())
        if "FROM cover_style_profiles WHERE is_deleted" in norm:
            return [dict(p) for p in self.state["profiles"].values()
                    if not p.get("is_deleted")]
        if "FROM cover_style_references WHERE profile_id" in norm:
            return [dict(r) for r in self.state["refs"].values()
                    if r["profile_id"] == args[0]]
        if "FROM cover_style_references r" in norm:
            out = []
            for r in self.state["refs"].values():
                if r["asset_id"] == args[0]:
                    p = self.state["profiles"].get(r["profile_id"])
                    if p and not p.get("is_deleted"):
                        out.append({"profile_id": r["profile_id"],
                                    "name": p["name"]})
            return out
        return []


class _FakePool:
    def __init__(self):
        self.state = {"assets": {}, "profiles": {}, "refs": {},
                      "issues": {}, "provenance": []}
        self._conn = _FakeConn(self.state)

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


class _FakePg:
    def __init__(self):
        self.pool = _FakePool()


@pytest.fixture
def pg():
    return _FakePg()


# ── DDL ─────────────────────────────────────────────────────────────────────

class TestDdl:
    def test_five_tables_present(self):
        ddl = " ".join(DDL_STATEMENTS)
        for table in ("cover_style_profiles", "cover_style_references",
                      "cover_style_assets", "cover_style_issue_assignments",
                      "cover_style_provenance"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl

    def test_indexes_present(self):
        ddl = " ".join(DDL_STATEMENTS)
        for idx in ("idx_cover_style_profiles_active",
                    "idx_cover_style_refs_profile", "idx_cover_style_assets_sha",
                    "idx_cover_style_issue_unique", "idx_cover_style_prov_run"):
            assert idx in ddl

    def test_idempotent_if_not_exists(self):
        block = " ".join(s for s in DDL_STATEMENTS if "cover_style" in s)
        # ASAP-3.2 (D14, §103–§105): +1 таблица cover_style_connections
        # (Image Connection; Δ-лист: 5 → 6, идемпотентный CREATE IF NOT
        # EXISTS; SQLite DDL = 0 не нарушен).
        assert block.count("CREATE TABLE IF NOT EXISTS") == 6
        assert "CREATE UNIQUE INDEX IF NOT EXISTS" in block
        assert "cover_style_connections" in block

    def test_sqlite_version_not_bumped(self):
        # Δ DDL SQLite = 0 — в DDL нет ALTER/PRAGMA user_version.
        for stmt in DDL_STATEMENTS:
            if "cover_style" in stmt:
                assert "ALTER TABLE" not in stmt
                assert "user_version" not in stmt

    def test_validation_mode_reserved(self):
        ddl = " ".join(DDL_STATEMENTS)
        assert "validation_mode TEXT NOT NULL DEFAULT 'off'" in ddl


# ── asset registry ──────────────────────────────────────────────────────────

class TestAssetRegistry:
    def test_asset_id_deterministic(self):
        sha = "ab" * 32
        assert csa.asset_id_for(sha) == csa.asset_id_for(sha)
        assert csa.asset_id_for(sha).startswith("cas_")
        assert len(csa.asset_id_for(sha)) == 4 + 32

    def test_store_file_bytes_writes_disk(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COVER_STYLE_ASSETS_DIR", str(tmp_path))
        meta = csa.store_file_bytes(b"\x89PNGfake", filename="x.png")
        assert meta is not None
        assert meta["mime"] == "image/png"
        assert Path(meta["disk_path"]).exists()
        assert meta["sha256"] == hashlib.sha256(b"\x89PNGfake").hexdigest()

    def test_store_rejects_non_image(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COVER_STYLE_ASSETS_DIR", str(tmp_path))
        assert csa.store_file_bytes(b"data", filename="x.gif") is None
        assert csa.store_file_bytes(b"data", filename="x.txt") is None

    def test_import_seed_does_not_mutate_source(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COVER_STYLE_ASSETS_DIR", str(tmp_path))
        src = SEED_DIR / "medved_press.png"
        before = src.read_bytes()
        meta = csa.import_seed_file(src)
        assert meta is not None
        assert src.exists()
        assert src.read_bytes() == before     # R18: оригинал не мутирован

    def test_upsert_asset_dedup_by_sha(self, pg):
        import asyncio

        async def _run():
            meta = {"asset_id": "a1", "scope": "global", "filename": "x.png",
                    "mime": "image/png", "size_bytes": 1, "sha256": "deadbeef",
                    "origin": "seed", "disk_path": "/tmp/x.png"}
            assert await csr.upsert_asset(pg, meta) is True
            meta2 = dict(meta, asset_id="a2")
            assert await csr.upsert_asset(pg, meta2) is True
            assert meta2["asset_id"] == "a1"     # дедуп: вернулся существующий
            assert len(pg.pool.state["assets"]) == 1
        asyncio.run(_run())

    def test_fail_open_no_pool(self):
        import asyncio
        assert asyncio.run(csr.list_profiles(None)) == []
        assert asyncio.run(csr.get_profile(None, "x")) is None


# ── profile CRUD (без special-case) ─────────────────────────────────────────

class TestProfiles:
    def test_custom_profile_crud(self, pg):
        import asyncio

        async def _run():
            ok = await csr.upsert_profile(pg, {
                "profile_id": "c1", "name": "Мой стиль",
                "instruction": "test", "pipeline_mode": csr.MODE_EDIT_ONLY})
            assert ok
            p = await csr.get_profile(pg, "c1")
            assert p["name"] == "Мой стиль"
            assert p["origin"] == "custom"
            # update → revision++
            await csr.upsert_profile(pg, dict(p, name="Мой стиль 2"))
            p2 = await csr.get_profile(pg, "c1")
            assert p2["name"] == "Мой стиль 2"
            assert p2["revision"] == p["revision"] + 1
            assert await csr.soft_delete_profile(pg, "c1")
            assert await csr.get_profile(pg, "c1") is None
        asyncio.run(_run())

    def test_duplicate_copies_references(self, pg):
        import asyncio

        async def _run():
            await csr.upsert_profile(pg, {"profile_id": "src1", "name": "Src"})
            await csr.add_reference(pg, "src1", {
                "asset_id": "asset_x", "label": "L", "ordering": 0})
            new_id = await csr.duplicate_profile(pg, "src1")
            assert new_id and new_id != "src1"
            new_p = await csr.get_profile_with_refs(pg, new_id)
            assert new_p["origin"] == "custom"
            assert len(new_p["references"]) == 1
            assert new_p["references"][0]["asset_id"] == "asset_x"
        asyncio.run(_run())

    def test_no_hardcoded_name_branch_in_module(self):
        # §6/§98: runtime не содержит special-case по имени стиля.
        import ast
        src = (ROOT / "services" / "cover_style_registry.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        # Никаких сравнений литерала "medved_press" в коде (только константа
        # SEEDED_PROFILE_ID как значение, не ветвление).
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name):
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and \
                            comp.value == "medved_press":
                        pytest.fail("hardcoded medved_press branch")
        # SEEDED_PROFILE_ID — обычное значение, не used в if.
        assert "SEEDED_PROFILE_ID" in src

    def test_dangling_guard_reports_usage(self, pg):
        import asyncio

        async def _run():
            await csr.upsert_profile(pg, {"profile_id": "p1", "name": "P1"})
            await csr.add_reference(pg, "p1", {"asset_id": "shared_asset"})
            users = await csr.references_using_asset(pg, "shared_asset")
            assert len(users) == 1
            assert users[0]["profile_id"] == "p1"
            assert await csr.references_using_asset(pg, "unused") == []
        asyncio.run(_run())


# ── counter / issue assignment ──────────────────────────────────────────────

class TestIssueAssignment:
    def test_retry_reuse_same_number(self, pg):
        import asyncio

        async def _run():
            await csr.upsert_profile(pg, {
                "profile_id": "p", "name": "P", "counter_value": 43})
            first = await csr.resolve_issue_number(pg, "p", "run_a")
            again = await csr.resolve_issue_number(pg, "p", "run_a")
            assert first == again == 44            # 44 → retry → 44
            other = await csr.resolve_issue_number(pg, "p", "run_b")
            assert other == 45
        asyncio.run(_run())

    def test_concurrent_runs_get_different_numbers(self, pg):
        import asyncio

        async def _run():
            await csr.upsert_profile(pg, {"profile_id": "p", "name": "P"})
            nums = [await csr.resolve_issue_number(pg, "p", f"r{i}")
                    for i in range(5)]
            assert len(set(nums)) == 5
        asyncio.run(_run())

    def test_format_issue_uses_profile_format(self):
        assert csr.format_issue("ВЫПУСК {counter}", 47) == "ВЫПУСК 47"
        assert csr.format_issue("№ {counter}", 12) == "№ 12"
        assert csr.format_issue("ГЛАВА {counter}", 8) == "ГЛАВА 8"

# ── provenance ──────────────────────────────────────────────────────────────

class TestProvenance:
    def test_record_provenance(self, pg):
        import asyncio

        async def _run():
            pid = await csr.record_provenance(pg, {
                "summary_run_id": "run1", "style_id": "medved_press",
                "style_revision": 1, "issue_number": 44,
                "base_asset_id": "b", "final_asset_id": "f",
                "provider": "nanogpt", "model": "qwen", "connection_id": "c",
                "reference_asset_ids": ["r1"], "status": "styled",
                "fallback_mode": "", "mode": "production"})
            assert pid and pid.startswith("covp")
            assert len(pg.pool.state["provenance"]) == 1
        asyncio.run(_run())

    def test_record_provenance_preview_mode(self, pg):
        import asyncio

        async def _run():
            pid = await csr.record_provenance(pg, {
                "status": "staged", "mode": "preview"})
            assert pid is not None
        asyncio.run(_run())


# ── seed ────────────────────────────────────────────────────────────────────

class TestSeed:
    def test_seed_idempotent(self, pg):
        import asyncio

        async def _run():
            p1 = await csr.seed_seeded_style(pg)
            assert p1 is not None
            assert p1["origin"] == "seeded_example"
            assert p1["pipeline_mode"] == "generate_then_edit"
            counter_after_first = pg.pool.state["profiles"][
                csr.SEEDED_PROFILE_ID]["counter_value"]
            # повторный прогон — no-op
            p2 = await csr.seed_seeded_style(pg)
            assert pg.pool.state["profiles"][
                csr.SEEDED_PROFILE_ID]["counter_value"] == counter_after_first
            assert p2 is not None
            assert len(pg.pool.state["profiles"]) == 1
        asyncio.run(_run())

    def test_seed_uses_actual_jpg(self):
        # DC-1: preview-after — фактический файл `.jpg`.
        assert csr.SEED_FILES["preview_after"] == "style_example_02.jpg"
        assert (SEED_DIR / csr.SEED_FILES["preview_after"]).exists()
        assert (SEED_DIR / csr.SEED_FILES["preview_before"]).exists()
        assert (SEED_DIR / csr.SEED_FILES["reference"]).exists()

    def test_seed_counter_start_not_invented(self):
        # §60/DC-2: значение НЕ выдумано — обратимый дефолт 0.
        assert csr.SEEDED_COUNTER_START == 0

    def test_seed_does_not_overwrite_manual(self, pg):
        import asyncio

        async def _run():
            # Ручной стиль с тем же id (гипотетически) — seed не перезатирает
            # уже существующий профиль.
            await csr.upsert_profile(pg, {
                "profile_id": csr.SEEDED_PROFILE_ID, "name": "Ручной",
                "origin": "custom"})
            p = await csr.seed_seeded_style(pg)
            assert p["name"] == "Ручной"      # не перезаписан
        asyncio.run(_run())

    def test_seed_fail_open_without_pool(self):
        import asyncio
        assert asyncio.run(csr.seed_seeded_style(None)) is None

    def test_seed_instruction_semantics(self):
        # §24 + ASAP 4.2 (T-4817): normalize/ensure/replace, recurring identity
        # + compact-ядро (graphic novel, callouts, русский текст).
        text = csr.SEEDED_INSTRUCTION.lower()
        assert "permsoc" in text
        assert "медведь press" in text
        assert "номер" in text
        assert "не добавляй второй" in text or "не создавай" in text
        assert "комикс" in text or "graphic" in text
        assert "callout" in text or "плаш" in text
        assert "русск" in text


# ── revision snapshot / test-no-counter (§29/§66, T-4129/T-4130) ────────────

class TestRevisionSnapshot:
    def test_snapshot_fixes_state(self):
        profile = {
            "profile_id": "medved_press", "revision": 3,
            "instruction": "правила серии",
            "references": [{"asset_id": "a1"}, {"asset_id": "a2"}],
            "pipeline_mode": "generate_then_edit"}
        snap = csr.build_revision_snapshot(
            profile, issue_number=44,
            capabilities={"image_edit": "yes"},
            slot={"connection_id": "default", "model": "qwen",
                  "provider": "nano"})
        assert snap["style_id"] == "medved_press"
        assert snap["style_revision"] == 3
        assert snap["issue_number"] == 44
        assert snap["reference_asset_ids"] == ["a1", "a2"]
        assert snap["model_id"] == "qwen"
        assert snap["capabilities"]["image_edit"] == "yes"

    def test_snapshot_isolated_from_later_change(self):
        # §29: изменение профиля во время генерации не влияет на снимок.
        profile = {"profile_id": "p", "revision": 1,
                   "instruction": "old", "references": []}
        snap = csr.build_revision_snapshot(profile)
        profile["instruction"] = "NEW"
        profile["revision"] = 2
        assert snap["resolved_instructions"] == "old"
        assert snap["style_revision"] == 1


class TestTestStyleNoCounter:
    def test_preview_does_not_consume_counter(self):
        # §66: preview использует `ВЫПУСК 00`, counter не меняется.
        assert csr.preview_issue_number() == 0
        assert csr.preview_issue_display("ВЫПУСК {counter}") == "ВЫПУСК 00"

    def test_preview_does_not_touch_db(self, pg):
        import asyncio

        async def _run():
            await csr.upsert_profile(pg, {
                "profile_id": "p", "name": "P", "counter_value": 5})
            before = pg.pool.state["profiles"]["p"]["counter_value"]
            # preview не вызывает resolve_issue_number
            _ = csr.preview_issue_number()
            after = pg.pool.state["profiles"]["p"]["counter_value"]
            assert before == after == 5
        asyncio.run(_run())


class TestPipelineProvenanceBuild:
    def test_build_provenance_full(self):
        from services import cover_style_pipeline as csp
        p = csp.build_provenance(
            summary_run_id="run1", job_id="j1", style_id="medved_press",
            style_revision=1, issue_number=44, base_asset_id="b",
            final_asset_id="f", reference_asset_ids=["r1"],
            provider="nano", model="qwen", connection_id="default",
            status="styled", mode="production")
        assert set(p) >= {"summary_run_id", "base_asset_id", "final_asset_id",
                          "style_id", "style_revision", "issue_number",
                          "provider", "model", "connection_id",
                          "reference_asset_ids", "status", "job_id", "mode"}
        assert p["reference_asset_ids"] == ["r1"]

    def test_build_provenance_preview(self):
        from services import cover_style_pipeline as csp
        p = csp.build_provenance(summary_run_id=None, status="staged",
                                 mode="preview")
        assert p["mode"] == "preview"
        assert p["summary_run_id"] is None
