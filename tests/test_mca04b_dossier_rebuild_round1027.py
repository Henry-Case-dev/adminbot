"""mca-04b-dossier-rebuild (round 10.27, ADR-1027-9) — Builder-покрытие.

Приёмки/сценарии:
  * v20 (SC-20/A28): аддитивная идемпотентная миграция — 2 таблицы + индексы
    (partial UNIQUE active) + nullable `graph_facts.dossier_generation_id`;
    legacy-строки NULL = честный unknown; повторный прогон — no-op.
  * A87 (SC-01/SC-03/SC-06): full rebuild при числе сообщений БОЛЬШЕ
    live-window limit — обработан весь диапазон (включая ранние годы),
    доказательство покрытия по годам, keyset без OFFSET, boundary/курсор.
  * A89 (SC-04/SC-05/SC-11): budget exhaustion → `paused` (никогда
    `completed`/100%), `processed` не подменяется `total`, checkpoint-курсор
    после фиксации, resume без дублей, рестарт → `interrupted`.
  * A90 (SC-10/SC-12/SC-13): staging/generation + атомарная активация
    (прежняя версия `superseded` и доступна), идемпотентный повтор,
    `upsert_generated_dossier` не стирает долгосрочную картину (история в
    meta), старые confirmed не очищаются.
  * A85/A86/A88 (SC-08/SC-16): врезка local→SourceRef (невалидный номер →
    `evidence_invalid`), N-2 person_facts в chunked-пути, self_report/
    third_party атрибуция, N-1 ростер-scope резолв, N-3 пин `guess_subject`.
  * A95 (SC-14/SC-15): фиксированная выборка Леха/Вася/Ярик — precision/
    recall отдельно от охвата, негативные примеры исключены, отчёт с
    пропусками/причинами; длина текста — не критерий.
  * Kill-switch: master OFF → legacy-раннер (паритет baseline); loader
    namespace v2 ON/OFF (L-MCA03-8).
  * Наблюдаемость (SC-19): reason_code в словаре mca-13; job_view R17-safe.

R17: в тестах числа/коды; секретов нет.
"""
import asyncio
import json
import sqlite3
import time

import pytest

from config.settings import Settings
from services import dossier_rebuild_jobs as drj
from services import mca_events
from services import mca_process_registry as reg
from services import provenance
from services.database import (
    DatabaseService,
    _SCHEMA_VERSION_DOSSIER_STAGING,
)
from services.lore_worker import (
    LoreWorker,
    _new_rebuild_counters,
    _coverage_add,
)
from services.provenance import guess_subject
from tools.history_import import loader as loader_mod

CHAT = -100500
TARGET = "Аня"
LEHA = "Леха"
VASYA = "Вася"
YARIK = "Ярик"


async def _db(tmp_path, name="mca04b.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _count(db, sql, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _add_msg(db, chat_id, author, text, ts=None, user_id=2,
                   tg_message_id=None):
    ts = int(ts if ts is not None else time.time())
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "author_name, media_type, tg_message_id) VALUES (?, ?, ?, ?, ?, "
        "'text', ?)",
        (user_id, chat_id, text, ts, author, tg_message_id))
    await db.db.execute(
        "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
        (cursor.lastrowid, text))
    await db.db.commit()
    return cursor.lastrowid


def _old_ts(year: int, month: int = 6, day: int = 15) -> int:
    import calendar
    return int(calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0)))


# ═══ v20: миграция (SC-20) ══════════════════════════════════════════════════

class TestMigrationV20:
    @pytest.mark.asyncio
    async def test_v20_objects_and_user_version(self, tmp_path):
        db = await _db(tmp_path)
        try:
            cursor = await db.db.execute("PRAGMA user_version")
            # v21 (mca-05) идёт ПОСЛЕ v20 — маркер хвоста реестра, >= 20.
            assert (await cursor.fetchone())[0] >= \
                _SCHEMA_VERSION_DOSSIER_STAGING
            cursor = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name "
                "IN ('mca_dossier_generations','mca_dossier_staging_items')")
            assert len(await cursor.fetchall()) == 2
            cursor = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name "
                "IN ('idx_mca_dossier_gen_subject','idx_mca_dossier_gen_active'"
                ",'idx_mca_dossier_staging_gen','idx_graph_facts_dossier_gen')")
            assert len(await cursor.fetchall()) == 4
            # nullable-колонка graph_facts
            cursor = await db.db.execute("PRAGMA table_info(graph_facts)")
            cols = {r["name"] for r in await cursor.fetchall()}
            assert "dossier_generation_id" in cols
            # book row
            cursor = await db.db.execute(
                "SELECT name FROM schema_migrations WHERE version = 20")
            row = await cursor.fetchone()
            assert row is not None and row["name"] == "dossier_staging"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_v20_idempotent_reinit(self, tmp_path):
        db = await _db(tmp_path)
        await db.close()
        db2 = DatabaseService(str(tmp_path / "mca04b.db"))
        await db2.initialize()
        try:
            cursor = await db2.db.execute(
                "SELECT COUNT(*) AS c FROM schema_migrations WHERE version=20")
            assert (await cursor.fetchone())["c"] == 1
            cursor = await db2.db.execute(
                "SELECT COUNT(*) AS c FROM mca_dossier_generations")
            assert (await cursor.fetchone())["c"] == 0
        finally:
            await db2.close()

    @pytest.mark.asyncio
    async def test_v20_partial_unique_active(self, tmp_path):
        """Атомарная замена: активация нового поколения supersede'ит прежнее
        (одна короткая транзакция); после каждой операции `active` ровно
        одна на (chat, subject) — partial UNIQUE."""
        db = await _db(tmp_path)
        try:
            g1 = await db.create_dossier_generation(
                CHAT, 1, extractor_version=provenance.EXTRACTOR_VERSION)
            assert g1
            # второе building-поколение допустимо
            g2 = await db.create_dossier_generation(
                CHAT, 1, extractor_version=provenance.EXTRACTOR_VERSION)
            assert g2
            await db.activate_dossier_generation(g1)
            active = await db.get_active_dossier_generation(CHAT, 1)
            assert active["generation_id"] == g1
            # атомарная замена: g1 → superseded, g2 → active (не конфликт)
            result = await db.activate_dossier_generation(g2)
            assert result["superseded_generation_id"] == g1
            actives = await _count(
                db, "SELECT COUNT(*) FROM mca_dossier_generations WHERE "
                    "state = 'active'")
            assert actives == 1
            assert (await db.get_active_dossier_generation(
                CHAT, 1))["generation_id"] == g2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_v20_legacy_rows_null_generation(self, tmp_path):
        db = await _db(tmp_path)
        try:
            fid = await db.insert_graph_fact(
                CHAT, "легаси-факт", "chat_history", None,
                target_user=TARGET, status="confirmed", kind="fact")
            cursor = await db.db.execute(
                "SELECT dossier_generation_id FROM graph_facts WHERE id = ?",
                (fid,))
            row = await cursor.fetchone()
            assert row["dossier_generation_id"] is None   # честный unknown
        finally:
            await db.close()


# ═══ Staging/generation + активация (A90/SC-12) ═════════════════════════════

class TestStagingActivation:
    @pytest.mark.asyncio
    async def test_activate_applies_items_and_supersedes(self, tmp_path):
        db = await _db(tmp_path)
        try:
            # прежнее активное поколение
            g0 = await db.create_dossier_generation(
                CHAT, 7, extractor_version=provenance.EXTRACTOR_VERSION)
            await db.insert_dossier_staging_item(
                g0, "meme", subject_ref_id=7,
                payload={"text": "старый мем", "target_user": TARGET})
            await db.activate_dossier_generation(g0)
            # новое поколение
            g1 = await db.create_dossier_generation(
                CHAT, 7, extractor_version=provenance.EXTRACTOR_VERSION)
            await db.insert_dossier_staging_item(
                g1, "person_fact", subject_ref_id=7,
                payload={"text": "любит кофе", "target_user": TARGET,
                         "attribution_method": "self_report"})
            await db.insert_dossier_staging_item(
                g1, "portrait", subject_ref_id=7,
                payload={"target_user": TARGET, "portrait": "портрет Ани",
                         "patterns": [], "themes": []})
            result = await db.activate_dossier_generation(g1)
            assert result["state"] == "active"
            assert result["applied"] >= 2
            assert result["superseded_generation_id"] == g0
            gen1 = await db.get_dossier_generation(g1)
            gen0 = await db.get_dossier_generation(g0)
            assert gen1["state"] == "active"
            assert gen0["state"] == "superseded"
            # применённые строки помечены поколением
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM graph_facts WHERE "
                "dossier_generation_id = ?", (g1,))
            assert (await cursor.fetchone())["c"] >= 2
            # прежняя версия доступна (строки не удалены)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "fact = 'старый мем'") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_reactivation_idempotent_no_doubles(self, tmp_path):
        db = await _db(tmp_path)
        try:
            g1 = await db.create_dossier_generation(
                CHAT, 7, extractor_version=provenance.EXTRACTOR_VERSION)
            await db.insert_dossier_staging_item(
                g1, "person_fact", subject_ref_id=7,
                payload={"text": "любит кофе", "target_user": TARGET})
            first = await db.activate_dossier_generation(g1)
            assert first["state"] == "active"
            # повторная активация того же поколения — no-op
            second = await db.activate_dossier_generation(g1)
            assert second["state"] == "active"
            assert second["applied"] == 0
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "fact = 'любит кофе'") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_failed_generation_rejected(self, tmp_path):
        db = await _db(tmp_path)
        try:
            g1 = await db.create_dossier_generation(
                CHAT, 7, extractor_version=provenance.EXTRACTOR_VERSION)
            await db.set_dossier_generation_state(
                g1, "failed", finished=True)
            with pytest.raises(ValueError):
                await db.activate_dossier_generation(g1)
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_upsert_portrait_keeps_history(self, tmp_path):
        """Инвариант 10: обновление портрета не стирает долгосрочную картину —
        прежний текст сохраняется в meta-истории."""
        db = await _db(tmp_path)
        try:
            fid = await db.upsert_generated_dossier(
                CHAT, TARGET, "работала в Москве", ["паттерн"], [],
                now_ts=1000)
            assert fid
            fid2 = await db.upsert_generated_dossier(
                CHAT, TARGET, "работает в Питере", [], [], now_ts=2000)
            assert fid2 == fid          # ровно одна строка портрета
            cursor = await db.db.execute(
                "SELECT fact, belief_meta FROM graph_facts WHERE id = ?",
                (fid,))
            row = await cursor.fetchone()
            meta = json.loads(row["belief_meta"])
            assert "работает в Питере" in row["fact"]
            # прежний текст сохранён: current → previous_text, старый —
            # в историю (долгосрочная картина не стёрта)
            assert meta["previous_text"] == "работает в Питере"
            assert meta["portrait_history"]
            assert meta["portrait_history"][0]["text"] == \
                "работала в Москве"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_activation_keeps_confirmed_and_overrides(self, tmp_path):
        """SC-10/D7: активация не удаляет старые confirmed/ручные правки."""
        db = await _db(tmp_path)
        try:
            await db.insert_graph_fact(
                CHAT, "старый confirmed", "chat_history", None,
                target_user=TARGET, status="confirmed", kind="fact")
            await db.set_dossier_override(CHAT, 5, "ручная правка", 1)
            g1 = await db.create_dossier_generation(
                CHAT, 7, extractor_version=provenance.EXTRACTOR_VERSION)
            await db.insert_dossier_staging_item(
                g1, "person_fact", subject_ref_id=7,
                payload={"text": "новый факт", "target_user": TARGET})
            await db.activate_dossier_generation(g1)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "status = 'confirmed' AND "
                                     "fact = 'старый confirmed'") == 1
            assert await db.get_dossier_override(CHAT, 5) == "ручная правка"
            # дедуп повторной активации
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "fact = 'новый факт'") == 1
        finally:
            await db.close()


# ═══ N-MCA07-1: активация vec-поколения ═════════════════════════════════════

class TestEmbeddingGenerationActivation:
    @pytest.mark.asyncio
    async def test_activate_generation_swaps_active(self, tmp_path):
        db = await _db(tmp_path)
        try:
            # building создаётся до появления active (карантин до перестройки)
            await db.ensure_embedding_generation(
                "graph_facts_vec", "fp-new", activate=False)
            g2 = await db.get_latest_embedding_generation("graph_facts_vec")
            assert g2 is not None and g2["status"] == "building"
            # активное поколение старого конфига (A06: ensure не подменяет)
            g1 = await db.ensure_embedding_generation(
                "graph_facts_vec", "fp-old", activate=True)
            assert g1["status"] == "active"
            assert g1["generation_id"] != g2["generation_id"]
            # N-MCA07-1: операция активации после фактической перестройки
            result = await db.activate_embedding_generation(
                "graph_facts_vec", g2["generation_id"])
            assert result["status"] == "active"
            assert result["superseded_generation_id"] == g1["generation_id"]
            active = await db.get_active_embedding_generation(
                "graph_facts_vec")
            assert active["fingerprint"] == "fp-new"
            # повтор — no-op
            again = await db.activate_embedding_generation(
                "graph_facts_vec", g2["generation_id"])
            assert again["superseded_generation_id"] is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_activate_unknown_or_wrong_index(self, tmp_path):
        db = await _db(tmp_path)
        try:
            assert await db.activate_embedding_generation(
                "graph_facts_vec", "nope") is None
            g1 = await db.ensure_embedding_generation(
                "other_index", "fp", activate=True)
            assert await db.activate_embedding_generation(
                "graph_facts_vec", g1["generation_id"]) is None
        finally:
            await db.close()


# ═══ L-MCA03-8: namespace v2 ════════════════════════════════════════════════

class TestNamespaceFingerprintV2:
    def _write_file(self, tmp_path, content: bytes, name="export.json"):
        path = tmp_path / name
        path.write_bytes(content)
        return str(path)

    def test_v2_stable_for_unchanged_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            Settings, "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED", True)
        path = self._write_file(tmp_path, b'{"messages": []}')
        ns1 = loader_mod._dataset_namespace(path)
        ns2 = loader_mod._dataset_namespace(path)
        assert ns1 == ns2
        assert ":v2:" in ns1

    def test_v2_distinguishes_regenerated_same_size(self, tmp_path,
                                                    monkeypatch):
        """L-MCA03-8: in-place регенерация с тем же размером → новый
        namespace (source records не пропускаются)."""
        monkeypatch.setattr(
            Settings, "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED", True)
        content_a = b"a" * 128
        content_b = b"b" * 128          # тот же размер, другое содержимое
        path = self._write_file(tmp_path, content_a)
        ns_a = loader_mod._dataset_namespace(path)
        path2 = self._write_file(tmp_path, content_b)
        ns_b = loader_mod._dataset_namespace(path2)
        assert ns_a != ns_b

    def test_off_parity_v1_digest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            Settings, "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED", False)
        path = self._write_file(tmp_path, b"x" * 64)
        ns = loader_mod._dataset_namespace(path)
        assert ":v2:" not in ns
        assert ns.startswith("import:na:")
        # legacy-литерал не переприсваивается
        assert ns != "legacy_import_v1"

    def test_v2_full_digest_distinguishes_tail_beyond_head(
            self, tmp_path, monkeypatch):
        """M-MCA04B-1 (review round 1): файл >256 KiB — идентичная голова +
        тот же размер, отличающийся хвост → РАЗНЫЙ namespace (старый
        digest «голова 256 KiB + size» коллидировал). Неизменённый файл —
        тот же namespace (дедуп работает)."""
        monkeypatch.setattr(
            Settings, "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED", True)
        head = b"x" * (256 * 1024)          # ровно окно старого дайджеста
        body_a = head + b'"messages": "A"' + b" " * 5
        body_b = head + b'"messages": "B"' + b" " * 5
        assert len(body_a) == len(body_b) > 256 * 1024
        path_a = self._write_file(tmp_path, body_a, name="big_a.json")
        path_b = self._write_file(tmp_path, body_b, name="big_b.json")
        ns_a = loader_mod._dataset_namespace(path_a)
        ns_b = loader_mod._dataset_namespace(path_b)
        assert ns_a != ns_b, "регенерация хвоста >256 KiB не коллидирует"
        assert loader_mod._dataset_namespace(path_a) == ns_a, \
            "неизменённый файл — тот же namespace"


# ═══ N-MCA04A-1/-3: ростер-scope резолв + пин guess_subject ═════════════════

class TestSubjectResolution:
    @pytest.mark.asyncio
    async def test_roster_bound_resolution_n1(self, tmp_path):
        """N-1: имя вне ростера scope → unresolved без DB-скана (старый
        одноимённый в окне ≤500 больше не даёт ложный resolved)."""
        db = await _db(tmp_path)
        try:
            # «старый» Аня в последних 500 строках
            await _add_msg(db, CHAT, "Аня", "старое сообщение",
                           user_id=111, ts=_old_ts(2022))
            roster = {"Боря"}                       # Ани в scope НЕТ
            ref = await provenance.resolve_subject_ref(
                db, CHAT, "Аня", roster=roster)
            assert ref.resolution == "unresolved"
            assert ref.entity_id == "Аня"           # стабильный, не TG-id
            # в ростере → резолвится по БД
            ref2 = await provenance.resolve_subject_ref(
                db, CHAT, "Аня", roster={"Аня"})
            assert ref2.resolution == "resolved"
            assert ref2.entity_id == "111"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_roster_none_keeps_legacy_behavior(self, tmp_path):
        db = await _db(tmp_path)
        try:
            await _add_msg(db, CHAT, "Аня", "привет", user_id=111)
            ref = await provenance.resolve_subject_ref(db, CHAT, "Аня")
            assert ref.resolution == "resolved"
        finally:
            await db.close()

    def test_guess_subject_determinism_pin_n3(self):
        """N-3: детерминизм `guess_subject` при множестве участников
        (порядок set не влияет; префикс-матч стабилен, длиннейшее имя
        выбирается при совпадении префикса)."""
        participants = {"Леха", "Леха Васильевич", "Вася"}
        outs = {guess_subject("Леха любит кофе", participants)
                for _ in range(20)}
        assert len(outs) == 1
        assert outs.pop() == "Леха"
        outs2 = {guess_subject("Леха Васильевич служит", participants)
                 for _ in range(20)}
        assert len(outs2) == 1
        assert outs2.pop() == "Леха Васильевич"
        assert guess_subject("прайс АЗС вырос", participants) is None


# ═══ Движок full rebuild (A87/A89) ══════════════════════════════════════════

def _layer_a(target, text, kind="person_fact", evidence=1):
    return json.dumps({"candidates": [
        {"target": target, "kind": kind, "text": text,
         "evidence": [evidence], "confidence": 0.8}]})


def _layer_b(target, portrait, meme):
    return json.dumps({
        "portraits": [{"target": target, "portrait": portrait,
                       "patterns": [], "themes": []}],
        "memes": [{"target": target, "text": meme,
                   "classified_by": "llm"}]})


class _SeqLLM:
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = 0

    async def generate(self, messages, temperature=None):
        return self.sequence[min(self.calls, len(self.sequence) - 1)]

    async def generate_worker(self, role, messages, *, temperature=None):
        value = self.sequence[min(self.calls, len(self.sequence) - 1)]
        self.calls += 1
        return value


class _RoleLLM:
    """Role-aware стаб (H-2 round 1): Layer A prompt → A-JSON, Layer B
    («Синтезатор») → B-JSON — независимо от числа вызовов (мультираундовые
    сценарии budget→resume не «заканчивают» последовательность)."""

    def __init__(self, a_payload, b_payload):
        self.a = a_payload
        self.b = b_payload
        self.a_calls = 0
        self.b_calls = 0

    async def generate(self, messages, temperature=None):
        return await self.generate_worker("background", messages,
                                          temperature=temperature)

    async def generate_worker(self, role, messages, *, temperature=None):
        if "Синтезатор" in str(messages):
            self.b_calls += 1
            return self.b
        self.a_calls += 1
        return self.a


def _engine(monkeypatch, db, llm):
    monkeypatch.setattr(Settings, "MULTILAYER_EXTRACTION_ENABLED", True)
    return LoreWorker(store=None, db=db, llm=llm, bot_id=1)


class TestFullRebuildEngine:
    @pytest.mark.asyncio
    async def test_a87_covers_full_range_beyond_window(self, tmp_path,
                                                       monkeypatch):
        """A87: сообщений > live-window limit (300): обработан ВЕСЬ диапазон
        (2022…2026), покрытие по годам, boundary/курсор зафиксированы."""
        db = await _db(tmp_path)
        try:
            years = (2022, 2023, 2024, 2025, 2026)
            n = 0
            for year in years:
                for i in range(70):           # 350 > 300 (live-window limit)
                    await _add_msg(
                        db, CHAT, TARGET,
                        f"длинное сообщение года {year} номер {i} тест",
                        ts=_old_ts(year, 1 + n % 12, 10), user_id=5)
                    n += 1
            llm = _SeqLLM([_layer_a(TARGET, "любит кофе"),
                           _layer_b(TARGET, "портрет Ани", "мем Ани")])
            worker = _engine(monkeypatch, db, llm)
            monkeypatch.setattr(
                Settings, "LORE_WINDOW_MAX_MESSAGES", 300)
            report = await worker.rebuild_dossier_full(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=50,
                batch_max=100, write_mode="direct")
            assert report["status"] == "completed"
            assert report["total"] == 350
            assert report["processed"] == 350      # весь диапазон, не окно
            assert report["counters"]["available"] == 350
            assert report["counters"]["viewed"] == 350
            assert report["boundary"][0] > 0
            # доказательство покрытия по годам
            coverage = report["coverage"]
            for year in ("2022", "2023", "2024", "2025", "2026"):
                assert year in coverage, year
                assert coverage[year]["total"] == 70
            # личные факты записаны (не только портрет/мемы)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "status = 'unconfirmed'") >= 1
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "status = 'dossier_portrait'") == 1
            # дисковый backlog по batch
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_a89_budget_exhaustion_no_partial_synthesis(self, tmp_path,
                                                             monkeypatch):
        """A89: исчерпание бюджета на batch → `budget_exhausted` + курсор,
        БЕЗ частичного синтеза портрета; resume с курсора завершает без
        дублей."""
        import services.lore_worker as lw
        db = await _db(tmp_path)
        try:
            for i in range(30):
                await _add_msg(db, CHAT, TARGET,
                               f"длинное сообщение номер {i} тест",
                               ts=_old_ts(2024, 1 + i % 12, 5), user_id=5)
            llm = _RoleLLM(_layer_a(TARGET, "любит кофе"),
                           _layer_b(TARGET, "портрет", "мем"))
            worker = _engine(monkeypatch, db, llm)
            state = {"n": 0}
            real_budget_ok = lw._budget_ok

            async def _budget_then_exhaust(chat_id, tokens, worker_id="lore",
                                           calls=1):
                state["n"] += 1
                if state["n"] > 1:            # первый чанк ок, дальше стоп
                    return False
                return await real_budget_ok(chat_id, tokens,
                                            worker_id=worker_id,
                                            calls=calls)

            monkeypatch.setattr(lw, "_budget_ok", _budget_then_exhaust)
            checkpoints: list = []
            report = await worker.rebuild_dossier_full(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=10,
                batch_max=10, write_mode="direct",
                checkpoint_cb=lambda ts, cid, c, cov: checkpoints.append(
                    (ts, cid)))
            assert report["status"] == "budget_exhausted"
            assert report["reason_code"] == "dossier_paused_budget"
            assert report["processed"] < 30
            # частичный синтез НЕ выполнялся (портрета нет)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "status = 'dossier_portrait'") == 0
            # checkpoint курсор продвигался только после фиксации
            assert checkpoints
            # resume: бюджет восстановлен → завершение; дублей нет
            monkeypatch.setattr(lw, "_budget_ok", real_budget_ok)
            resume_cursor = report["cursor"]
            report2 = await worker.rebuild_dossier_full(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=10,
                batch_max=10, write_mode="direct", resume_cursor=resume_cursor)
            assert report2["status"] == "completed"
            facts_before = await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE "
                    "status = 'unconfirmed'")
            # третий прогон с нуля — идемпотентность (без дублей)
            report3 = await worker.rebuild_dossier_full(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=10,
                batch_max=10, write_mode="direct")
            assert report3["status"] == "completed"
            facts_after = await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE "
                    "status = 'unconfirmed'")
            assert facts_after == facts_before
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cancel_raises_and_writes_nothing(self, tmp_path,
                                                    monkeypatch):
        db = await _db(tmp_path)
        try:
            for i in range(5):
                await _add_msg(db, CHAT, TARGET,
                               f"длинное сообщение отмены {i} тест",
                               ts=_old_ts(2025, 3, 1), user_id=5)
            llm = _SeqLLM([_layer_a(TARGET, "факт"),
                           _layer_b(TARGET, "портрет", "мем")])
            worker = _engine(monkeypatch, db, llm)
            with pytest.raises(asyncio.CancelledError):
                await worker.rebuild_dossier_full(
                    CHAT, target_user=TARGET, window_hours=0, chunk_size=2,
                    batch_max=2, write_mode="direct",
                    cancel_cb=lambda: True)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts") == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_empty_range_completed_zero_valid(self, tmp_path,
                                                    monkeypatch):
        """Инвариант 14: нулевой результат при полном корректном проходе
        валиден (без выдуманных фактов)."""
        db = await _db(tmp_path)
        try:
            llm = _SeqLLM([])
            worker = _engine(monkeypatch, db, llm)
            report = await worker.rebuild_dossier_full(
                CHAT, target_user=TARGET, window_hours=0,
                write_mode="direct")
            assert report["status"] == "completed"
            assert report["total"] == 0
            assert report["processed"] == 0
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts") == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_collect_mode_returns_candidates(self, tmp_path,
                                                   monkeypatch):
        """Staging-режим: движок НЕ пишет напрямую — кандидаты возвращаются
        runner'у (атомарная активация)."""
        db = await _db(tmp_path)
        try:
            await _add_msg(db, CHAT, TARGET,
                           "я люблю кофе, длинное сообщение тест",
                           ts=_old_ts(2025, 5, 5), user_id=5)
            llm = _SeqLLM([_layer_a(TARGET, "любит кофе"),
                           _layer_b(TARGET, "портрет", "мем")])
            worker = _engine(monkeypatch, db, llm)
            report = await worker.rebuild_dossier_full(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=10,
                batch_max=10, write_mode="collect")
            assert report["status"] == "completed"
            assert report["candidates"], "кандидаты отданы runner'у"
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts") == 0
            assert report["synthesized"]["portraits"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_evidence_invalid_dropped_and_sourcerefs(self, tmp_path,
                                                           monkeypatch):
        """A85/SC-08: врезка local→SourceRef — валидный номер → постоянный
        SourceRef + EvidenceLink; невалидный → кандидат не пишется
        (`evidence_invalid`)."""
        db = await _db(tmp_path)
        try:
            await _add_msg(db, CHAT, TARGET,
                           "я бегаю по утрам, длинное сообщение тест",
                           user_id=5)
            llm = _SeqLLM([
                json.dumps({"candidates": [
                    {"target": TARGET, "kind": "person_fact",
                     "text": "бегает по утрам", "evidence": [1],
                     "confidence": 0.9},
                    {"target": TARGET, "kind": "person_fact",
                     "text": "выдуманный факт", "evidence": [99],
                     "confidence": 0.9},
                ]}),
            ])
            worker = _engine(monkeypatch, db, llm)
            lines = worker._format_window(await (await db.db.execute(
                "SELECT user_id, author_name, text, timestamp FROM "
                "smart_messages WHERE chat_id = ?", (CHAT,)
            )).fetchall())
            rows = await (await db.db.execute(
                "SELECT id, user_id, author_name, text, timestamp, "
                "tg_message_id, reply_to_id, chat_id FROM smart_messages "
                "WHERE chat_id = ?", (CHAT,))).fetchall()
            stats = _new_rebuild_counters()
            facts, memes = await worker._extract_chunk(
                CHAT, lines, [TARGET], window_rows=rows, stats=stats)
            texts = {c["text"] for c in facts}
            assert "бегает по утрам" in texts
            assert "выдуманный факт" not in texts
            # верхняя граница номера строки (row-bound, T-3904) — кандидат
            # с evidence=[99] за границами чанка отброшен с причиной
            assert stats["rejected_by_reason"].get(
                "evidence_out_of_range") == 1
            valid = [c for c in facts if c["text"] == "бегает по утрам"][0]
            assert valid["_source_ref_ids"], "постоянный SourceRef записан"
            # SourceRef реально в БД
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM mca_source_refs WHERE "
                "entity_type = 'message'")
            assert (await cursor.fetchone())["c"] >= 1
            # кандидат без единого валидного постоянного источника не пишется
            # (нет выдуманных ссылок; reason_code=evidence_invalid)
            stats2 = _new_rebuild_counters()
            bad = {"target": TARGET, "text": "неподтверждаемый факт",
                   "evidence": [1], "_evidence_valid": False}
            written = await worker._write_person_facts(CHAT, [bad],
                                                       )
            assert written == 0
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "fact = 'неподтверждаемый факт'") == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_self_report_attribution(self, tmp_path, monkeypatch):
        """§8.3.2: subject == автор строки evidence → `self_report`
        («по собственным словам»); чужой рассказ → `third_party`."""
        db = await _db(tmp_path)
        try:
            await _add_msg(db, CHAT, TARGET,
                           "я люблю кофе, длинное сообщение тут тест",
                           user_id=5)
            await _add_msg(db, CHAT, "Боря",
                           f"{TARGET} бегает по утрам, длинное сообщение",
                           user_id=6)
            llm = _SeqLLM([
                json.dumps({"candidates": [
                    {"target": TARGET, "kind": "person_fact",
                     "text": "любит кофе", "evidence": [1],
                     "confidence": 0.9},
                    {"target": TARGET, "kind": "person_fact",
                     "text": "бегает по утрам", "evidence": [2],
                     "confidence": 0.9},
                ]}),
            ])
            worker = _engine(monkeypatch, db, llm)
            rows = await (await db.db.execute(
                "SELECT id, user_id, author_name, text, timestamp, "
                "tg_message_id, reply_to_id, chat_id FROM smart_messages "
                "WHERE chat_id = ? ORDER BY id ASC", (CHAT,)
            )).fetchall()
            lines = worker._format_window(rows, desc_input=False)
            names = [TARGET, "Боря"]
            await worker._write_person_facts(
                CHAT, (await worker._extract_chunk(
                    CHAT, lines, names, window_rows=rows))[0])
            cursor = await db.db.execute(
                "SELECT fact, attribution_method FROM graph_facts WHERE "
                "status = 'unconfirmed' ORDER BY id ASC")
            rows_w = await cursor.fetchall()
            methods = {r["fact"]: r["attribution_method"] for r in rows_w}
            assert methods.get("любит кофе") == "self_report"
            assert methods.get("бегает по утрам") == "third_party"
            # EvidenceLink на SourceRef сообщения записан
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM mca_evidence_links WHERE "
                "link_type = 'derived_from'")
            assert (await cursor.fetchone())["c"] >= 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_n2_person_facts_written_in_chunked_path(
            self, tmp_path, monkeypatch):
        """N-2 (A86): чанковый путь сохраняет person_facts (не только
        портрет/мемы); сбой Слоя Б их не теряет."""
        db = await _db(tmp_path)
        try:
            for i in range(6):
                await _add_msg(db, CHAT, TARGET,
                               f"длинное сообщение номер {i} тест",
                               ts=_old_ts(2025, 1 + i, 5), user_id=5)
            # Layer B всегда падает → person_facts должны остаться
            class _FailB(_SeqLLM):
                async def generate_worker(self, role, messages, *,
                                          temperature=None):
                    if role == "background" and "Синтезатор" in \
                            str(messages):
                        raise RuntimeError("layer B down")
                    return await super().generate_worker(
                        role, messages, temperature=temperature)

            llm = _FailB([
                _layer_a(TARGET, "любит кофе"),
                _layer_a(TARGET, "любит кофе"),
                _layer_b(TARGET, "портрет", "мем"),
            ])
            worker = _engine(monkeypatch, db, llm)
            written = await worker.rebuild_dossier_for_user(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=3)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "status = 'unconfirmed'") >= 1
        finally:
            await db.close()


# ═══ Раннер: различимые состояния (A89) + legacy-паритет ════════════════════

class _FullContractWorker:
    """Стаб движка full-контракта: возвращает заготовленный отчёт."""

    def __init__(self, report):
        self.report = report
        self.calls: list = []

    async def rebuild_dossier_full(self, chat_id, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.report, list):
            return self.report[min(len(self.calls) - 1, len(self.report) - 1)]
        return self.report


def _completed_report(**over):
    base = {
        "status": "completed",
        "reason_code": None,
        "written": 2,
        "total": 30,
        "processed": 30,
        "cursor": (1720000000, 30),
        "boundary": (1720000000, 30),
        "counters": _new_rebuild_counters(),
        "coverage": {"2024": {"total": 30, "months": {"6": 30}}},
        "candidates": [],
        "synthesized": {"portraits": [], "memes": []},
    }
    base.update(over)
    return base


class TestRunnerStates:
    async def _run(self, tmp_path, store, db, worker, job_id, **over):
        await drj.run_dossier_rebuild(
            store=store, db=db, worker=worker, job_id=job_id, chat_id=CHAT,
            user_id=5, target_name=TARGET, window_hours=0, chunk_size=10,
            jobs_dir=tmp_path, archive_dir=tmp_path / "archive",
            **over)

    @pytest.mark.asyncio
    async def test_completed_processed_actual_not_total_fake(self, tmp_path):
        db = await _db(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j1", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=3)
            worker = _FullContractWorker(_completed_report(processed=30,
                                                           total=30))
            await self._run(tmp_path, store, db, worker, "j1")
            job = await store.get("j1")
            assert job["status"] == "completed"
            assert job["processed"] == 30          # фактический
            assert job["mode"] == "full"
            assert job["attempt"] == 1
            assert job["generation_id"]            # staging активирован
            view = drj.job_view(job)
            assert view["percent"] == 100
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_budget_exhaustion_paused_never_completed(self, tmp_path):
        """A89: budget exhaustion → `paused` (≠ completed), processed < total,
        cursor сохранён; неполный диапазон остаётся в очереди."""
        db = await _db(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j2", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=6)
            paused = _completed_report(
                status="budget_exhausted",
                reason_code="dossier_paused_budget",
                processed=15, total=30,
                cursor=(1710000000, 15))
            worker = _FullContractWorker(paused)
            await self._run(tmp_path, store, db, worker, "j2")
            job = await store.get("j2")
            assert job["status"] == "paused"
            assert job["reason_code"] == "dossier_paused_budget"
            assert job["processed"] == 15
            assert job["cursor_ts"] == 1710000000
            view = drj.job_view(job)
            assert view["percent"] == 50           # честные 50, не 100
            assert job["finished_at"] is None      # не терминал
            # paused — активный: новый старт блокируется до resume/cancel
            assert await store.find_active(CHAT, 5) is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_resume_passes_cursor_and_bumps_attempt(self, tmp_path):
        db = await _db(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j3", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=6)
            await store.update("j3", status="paused", mode="full", attempt=1,
                               cursor_ts=1710000000, cursor_id=15,
                               processed=15)
            worker = _FullContractWorker(_completed_report())
            await self._run(tmp_path, store, db, worker, "j3")
            job = await store.get("j3")
            assert job["status"] == "completed"
            assert job["attempt"] == 2
            kwargs = worker.calls[0]
            assert kwargs["resume_cursor"] == (1710000000, 15)
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_restart_marks_paused_interrupted(self, tmp_path):
        """Рестарт процесса: paused → `interrupted` (различимое состояние),
        курсор сохраняется для resume."""
        db = await _db(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j4", chat_id=CHAT, user_id=5,
                               target_name=TARGET)
            await store.update("j4", status="paused", mode="full",
                               cursor_ts=100, cursor_id=10, processed=10)
            changed = await store.reconcile_interrupted()
            assert changed == 1
            job = await store.get("j4")
            assert job["status"] == "interrupted"
            assert job["cursor_ts"] == 100         # checkpoint цел
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_activation_failure_is_failed_not_destroying(self, tmp_path,
                                                               monkeypatch):
        """SC-12: сбой активации → failed; старые факты не уничтожены."""
        db = await _db(tmp_path)
        try:
            await db.insert_graph_fact(
                CHAT, "старый confirmed", "chat_history", None,
                target_user=TARGET, status="confirmed", kind="fact")
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j5", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=3)
            async def _boom(*args, **kwargs):
                return None                        # staging не создался
            monkeypatch.setattr(DatabaseService,
                                "create_dossier_generation", _boom)
            worker = _FullContractWorker(_completed_report())
            await self._run(tmp_path, store, db, worker, "j5")
            job = await store.get("j5")
            assert job["status"] == "failed"
            assert job["error_code"] == "activation_failed"
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "fact = 'старый confirmed'") == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_master_off_legacy_parity(self, tmp_path, monkeypatch):
        """Kill-switch: master OFF → точный legacy-раннер (cleanup + done +
        processed=total — паритет baseline ADR-1022-8)."""
        monkeypatch.setattr(Settings, "MCA_DOSSIER_REBUILD_ENABLED", False)
        db = await _db(tmp_path)
        try:
            await db.insert_graph_fact(
                CHAT, "старый confirmed", "chat_history", None,
                target_user=TARGET, status="confirmed", kind="fact")
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j6", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=2)

            class _LegacyWorker:
                async def rebuild_dossier_for_user(self, chat_id, *,
                                                   target_user, window_hours,
                                                   chunk_size, progress_cb,
                                                   cancel_cb):
                    await db.insert_graph_fact(
                        chat_id, "новый портрет", "chat_history", None,
                        target_user=target_user, status="dossier_portrait",
                        kind="fact")
                    return 1

            await self._run(tmp_path, store, db, _LegacyWorker(), "j6")
            job = await store.get("j6")
            assert job["status"] == "done"           # legacy-контракт
            assert job["processed"] == 2             # = total (baseline)
            assert job["mode"] == "legacy"
            # legacy cleanup сработал (паритет baseline-поведения)
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "status = 'confirmed'") == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_engineless_worker_falls_back_to_legacy(self, tmp_path,
                                                          monkeypatch):
        """Dispatch-безопасность: воркер без `rebuild_dossier_full` →
        legacy-раннер даже при master ON."""
        db = await _db(tmp_path)
        try:
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("j7", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=1)

            class _OnlyLegacy:
                async def rebuild_dossier_for_user(self, *a, **k):
                    return 0

            await self._run(tmp_path, store, db, _OnlyLegacy(), "j7")
            job = await store.get("j7")
            assert job["status"] == "done"
            assert job["mode"] == "legacy"
        finally:
            await db.close()


# ═══ H-1/H-2 (review round 1): resume без потерь + честная финализация ══════

class _CounterLLM:
    """Layer A → факт с УНИКАЛЬНЫМ текстом на вызов (`факт чанка N`);
    Layer B («Синтезатор») → портрет+мем. Позволяет доказать наличие
    обоих сегментов (до/после курсора) в финальном досье."""

    def __init__(self, portrait="портрет", meme="мем"):
        self.a_calls = 0
        self.b_calls = 0
        self.portrait = portrait
        self.meme = meme

    async def generate(self, messages, temperature=None):
        return await self.generate_worker("background", messages,
                                          temperature=temperature)

    async def generate_worker(self, role, messages, *, temperature=None):
        if "Синтезатор" in str(messages):
            self.b_calls += 1
            return _layer_b(TARGET, self.portrait, self.meme)
        self.a_calls += 1
        return _layer_a(TARGET, f"факт чанка {self.a_calls}")


class TestResumeCollectKeepsCandidates:
    """H-MCA04B-1 (review round 1): collect-mode pause по бюджету + resume —
    кандидаты ОБОИХ сегментов (до и после курсора) в финальном досье."""

    async def _seed(self, db):
        import calendar
        base = int(calendar.timegm((2024, 6, 1, 12, 0, 0, 0, 0, 0)))
        for i in range(30):
            await _add_msg(db, CHAT, TARGET,
                           f"длинное сообщение номер {i} тест",
                           ts=base + i * 10, user_id=5)

    async def _run(self, tmp_path, store, db, worker, job_id):
        await drj.run_dossier_rebuild(
            store=store, db=db, worker=worker, job_id=job_id, chat_id=CHAT,
            user_id=5, target_name=TARGET, window_hours=0, chunk_size=10,
            jobs_dir=tmp_path, archive_dir=tmp_path / "archive")

    @pytest.mark.asyncio
    async def test_pause_stages_candidates_then_resume_activates_both_segments(
            self, tmp_path, monkeypatch):
        import services.lore_worker as lw
        # batch=10 → пауза МЕЖДУ батчами (batch-гранулярность checkpoint'а)
        monkeypatch.setattr(Settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES", 10)
        db = await _db(tmp_path)
        try:
            await self._seed(db)
            llm = _CounterLLM()
            worker = _engine(monkeypatch, db, llm)
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("jh1", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=30)
            state = {"n": 0}
            real_budget_ok = lw._budget_ok

            async def _budget_stop_after_first_chunk(chat_id, tokens,
                                                     worker_id="lore",
                                                     calls=1):
                state["n"] += 1
                return state["n"] <= 1     # чанк 1 ок → пауза на чанке 2

            monkeypatch.setattr(lw, "_budget_ok",
                                _budget_stop_after_first_chunk)
            # ── Прогон 1: пауза по бюджету ──────────────────────────────
            await self._run(tmp_path, store, db, worker, "jh1")
            job = await store.get("jh1")
            assert job["status"] == "paused"
            assert job["reason_code"] == "dossier_paused_budget"
            # H-1: кандидаты прерванного прогона ПЕРСИСТЕНТНЫ до паузы
            gen_id = job.get("generation_id")
            assert gen_id, "generation создан до паузы"
            gen = await db.get_dossier_generation(gen_id)
            assert gen["state"] == "building"
            staged = await db.list_dossier_staging_items(gen_id)
            staged_texts = {drj._staging_payload(i).get("text")
                            for i in staged}
            assert "факт чанка 1" in staged_texts, \
                "кандидаты до курсора сохранены в staging"
            # движок НЕ активировал поколение на паузе
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts") == 0
            # ── Прогон 2 (resume): бюджет восстановлен ───────────────────
            monkeypatch.setattr(lw, "_budget_ok", real_budget_ok)
            await self._run(tmp_path, store, db, worker, "jh1")
            job2 = await store.get("jh1")
            assert job2["status"] == "completed"
            # то же поколение (не создано второе)
            assert job2.get("generation_id") == gen_id
            gen2 = await db.get_dossier_generation(gen_id)
            assert gen2["state"] == "active"
            # кандидаты ОБОИХ сегментов в финальном досье
            cursor = await db.db.execute(
                "SELECT fact, COUNT(*) AS c FROM graph_facts WHERE "
                "dossier_generation_id = ? AND status = 'unconfirmed' "
                "GROUP BY fact", (gen_id,))
            facts = {r["fact"]: r["c"] for r in await cursor.fetchall()}
            assert facts.get("факт чанка 1") == 1, \
                "сегмент ДО курсора (прошлой паузы) в досье"
            assert facts.get("факт чанка 2") == 1, \
                "сегмент ПОСЛЕ курсора в досье"
            assert facts.get("факт чанка 3") == 1
            # портрет активирован тем же поколением, дублей нет
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE status = "
                    "'dossier_portrait' AND dossier_generation_id = ?",
                (gen_id,)) == 1
            # дедуп staged: ни один факт не задвоен
            assert all(c == 1 for c in facts.values())
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_resume_engine_receives_seeded_candidates(
            self, tmp_path, monkeypatch):
        """Seeding: при resume движок получает кандидатов прошлой паузы
        (`resume_candidates`) — Layer B синтезирует по ОБОИМ сегментам."""
        import services.lore_worker as lw
        monkeypatch.setattr(Settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES", 10)
        db = await _db(tmp_path)
        try:
            await self._seed(db)
            llm = _CounterLLM()
            worker = _engine(monkeypatch, db, llm)
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("jh2", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=30)
            state = {"n": 0}
            real_budget_ok = lw._budget_ok

            async def _budget_first_only(chat_id, tokens, worker_id="lore",
                                         calls=1):
                state["n"] += 1
                return state["n"] <= 1

            monkeypatch.setattr(lw, "_budget_ok", _budget_first_only)
            await self._run(tmp_path, store, db, worker, "jh2")
            monkeypatch.setattr(lw, "_budget_ok", real_budget_ok)
            job = await store.get("jh2")
            assert job["status"] == "paused"
            # resume: движку передан посев из staging
            seen: dict = {}

            class _SpyWorker:
                def __init__(self, inner):
                    self.inner = inner

                async def rebuild_dossier_full(self, chat_id, **kwargs):
                    seen["resume_candidates"] = kwargs.get(
                        "resume_candidates")
                    seen["resume_cursor"] = kwargs.get("resume_cursor")
                    return await self.inner.rebuild_dossier_full(chat_id,
                                                                 **kwargs)

            await self._run(tmp_path, store, db,
                            _SpyWorker(worker), "jh2")
            job2 = await store.get("jh2")
            assert job2["status"] == "completed"
            seeded = seen.get("resume_candidates")
            assert seeded, "посев кандидатов из staging передан движку"
            assert any(c.get("text") == "факт чанка 1" for c in seeded)
            assert seen.get("resume_cursor") is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_pending_staging_failure_is_failed_not_silent_pause(
            self, tmp_path, monkeypatch):
        """H-1 честность: персистентация кандидатов до паузы не удалась →
        failed (`dossier_pending_staging_failed`), НЕ молчаливая paused."""
        import services.lore_worker as lw
        monkeypatch.setattr(Settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES", 10)
        db = await _db(tmp_path)
        try:
            await self._seed(db)
            llm = _CounterLLM()
            worker = _engine(monkeypatch, db, llm)
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("jh3", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=30)
            state = {"n": 0}

            async def _budget_first_only(chat_id, tokens, worker_id="lore",
                                         calls=1):
                state["n"] += 1
                return state["n"] <= 1

            monkeypatch.setattr(lw, "_budget_ok", _budget_first_only)
            async def _no_generation(*args, **kwargs):
                return None                    # staging недоступен
            monkeypatch.setattr(DatabaseService,
                                "create_dossier_generation",
                                _no_generation)
            await self._run(tmp_path, store, db, worker, "jh3")
            job = await store.get("jh3")
            assert job["status"] == "failed"
            assert job["error_code"] == "pending_staging_failed"
            assert job["reason_code"] == "dossier_pending_staging_failed"
        finally:
            await db.close()


class TestHonestFinalization:
    """H-MCA04B-2 (review round 1): сбои модели/бюджета НИКОГДА не дают
    `completed` (инвариант 2; спека §3.2 строки 2/6)."""

    async def _seed(self, db):
        import calendar
        base = int(calendar.timegm((2024, 6, 1, 12, 0, 0, 0, 0, 0)))
        for i in range(30):
            await _add_msg(db, CHAT, TARGET,
                           f"длинное сообщение номер {i} тест",
                           ts=base + i * 10, user_id=5)

    async def _run(self, tmp_path, store, db, worker, job_id):
        await drj.run_dossier_rebuild(
            store=store, db=db, worker=worker, job_id=job_id, chat_id=CHAT,
            user_id=5, target_name=TARGET, window_hours=0, chunk_size=10,
            jobs_dir=tmp_path, archive_dir=tmp_path / "archive")

    @pytest.mark.asyncio
    async def test_model_unavailable_whole_pass_is_failed_not_completed(
            self, tmp_path, monkeypatch):
        """Проба B: модель недоступна ВЕСЬ проход → честный не-completed:
        `paused` (retryable по spec §3.2 «paused/failed»; курсор сохраняется
        для resume) с reason_code=model_unavailable; ноль записей;
        инвариант 2: НИКОГДА `completed`."""
        monkeypatch.setattr(Settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES", 10)
        db = await _db(tmp_path)
        try:
            await self._seed(db)

            class _DownLLM:
                async def generate(self, messages, temperature=None):
                    raise RuntimeError("model down")

                async def generate_worker(self, role, messages, *,
                                          temperature=None):
                    raise RuntimeError("model down")

            worker = _engine(monkeypatch, db, _DownLLM())
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("jh4", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=30)
            await self._run(tmp_path, store, db, worker, "jh4")
            job = await store.get("jh4")
            assert job["status"] in ("paused", "failed", "interrupted")
            assert job["status"] != "completed"      # инвариант 2
            assert job["reason_code"] == "model_unavailable"
            assert job["stage"] == "extract"
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts") == 0
            # processed фактический (весь диапазон ПРОСМОТРЕН, но ни одного
            # извлечения — честный сигнал в status/reason_code, не в percent)
            view = drj.job_view(job)
            assert view["processed"] == 30
            assert view["status"] != "completed"
            # resume-способность: курсор сохранён (retryable-исход)
            assert job["cursor_ts"] is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_budget_exhausted_at_synthesis_not_completed(
            self, tmp_path, monkeypatch):
        """Проба C: бюджет кончился на Layer B → paused с
        stage=synthesize, НЕ completed, НЕ silent partial; кандидаты
        персистентны; портрета нет."""
        import services.lore_worker as lw
        monkeypatch.setattr(Settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES", 10)
        db = await _db(tmp_path)
        try:
            await self._seed(db)
            llm = _CounterLLM()
            worker = _engine(monkeypatch, db, llm)
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("jh5", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=30)
            state = {"n": 0}
            real_budget_ok = lw._budget_ok

            async def _budget_stop_before_layer_b(chat_id, tokens,
                                                  worker_id="lore", calls=1):
                state["n"] += 1
                return state["n"] <= 3      # 3 чанка ок, Layer B — нет

            monkeypatch.setattr(lw, "_budget_ok", _budget_stop_before_layer_b)
            await self._run(tmp_path, store, db, worker, "jh5")
            job = await store.get("jh5")
            assert job["status"] == "paused"        # НЕ completed
            assert job["stage"] == "synthesize"
            assert job["reason_code"] == "dossier_paused_budget"
            # кандидаты Layer A персистентны до паузы (H-1-механизм)
            gen_id = job.get("generation_id")
            assert gen_id
            gen = await db.get_dossier_generation(gen_id)
            assert gen["state"] == "building"
            staged_texts = {drj._staging_payload(i).get("text") for i in
                            await db.list_dossier_staging_items(gen_id)}
            assert {"факт чанка 1", "факт чанка 2",
                    "факт чанка 3"} <= staged_texts
            # портрета нет (синтез не выполнен) — и это НЕ замаскировано
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE status = "
                    "'dossier_portrait'") == 0
            # ── resume: синтез повторён по ПОЛНОМУ набору → completed ──
            monkeypatch.setattr(lw, "_budget_ok", real_budget_ok)
            await self._run(tmp_path, store, db, worker, "jh5")
            job2 = await store.get("jh5")
            assert job2["status"] == "completed"
            assert job2.get("generation_id") == gen_id
            assert (await db.get_dossier_generation(gen_id))["state"] == \
                "active"
            assert await _count(
                db, "SELECT COUNT(*) FROM graph_facts WHERE status = "
                    "'dossier_portrait' AND dossier_generation_id = ?",
                (gen_id,)) == 1
            for n in (1, 2, 3):
                assert await _count(
                    db, "SELECT COUNT(*) FROM graph_facts WHERE fact = ?",
                    (f"факт чанка {n}",)) == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_zero_extract_with_parse_errors_not_completed(
            self, tmp_path, monkeypatch):
        """Извлечений 0 ∧ parse errors > 0 → failed (parse_error);
        нулевой результат при ПОЛНОМ корректном проходе остаётся валидным
        completed (инвариант 14 — покрыт test_empty_range_completed_zero_valid)."""
        db = await _db(tmp_path)
        try:
            await self._seed(db)

            class _GarbageLLM:
                async def generate(self, messages, temperature=None):
                    return "не json вообще"

                async def generate_worker(self, role, messages, *,
                                          temperature=None):
                    return "не json вообще"

            worker = _engine(monkeypatch, db, _GarbageLLM())
            report = await worker.rebuild_dossier_full(
                CHAT, target_user=TARGET, window_hours=0, chunk_size=10,
                batch_max=10, write_mode="direct")
            assert report["status"] == "failed"
            assert report["reason_code"] == "parse_error"
            assert report["counters"]["parse_errors"] > 0
            assert report["counters"]["candidates"] == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_direct_mode_layer_b_budget_is_failed_not_silent(
            self, tmp_path, monkeypatch):
        """direct-режим (staging OFF): бюджет на Layer B → честный
        терминальный failed (resume не может восстановить набор накопления —
        paused дал бы silent partial)."""
        import services.lore_worker as lw
        monkeypatch.setattr(Settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES", 10)
        db = await _db(tmp_path)
        try:
            await self._seed(db)
            llm = _CounterLLM()
            worker = _engine(monkeypatch, db, llm)
            store = drj.DossierRebuildJobStore(base_dir=tmp_path)
            await store.create("jh6", chat_id=CHAT, user_id=5,
                               target_name=TARGET, total=30)
            state = {"n": 0}

            async def _budget_stop_before_layer_b(chat_id, tokens,
                                                  worker_id="lore", calls=1):
                state["n"] += 1
                return state["n"] <= 3

            monkeypatch.setattr(lw, "_budget_ok", _budget_stop_before_layer_b)
            monkeypatch.setattr(
                Settings, "MCA_DOSSIER_STAGING_ACTIVATION_ENABLED", False)
            await self._run(tmp_path, store, db, worker, "jh6")
            job = await store.get("jh6")
            assert job["status"] == "failed"        # НЕ completed, НЕ paused
            assert job["stage"] == "synthesize"
            assert job["reason_code"] == "dossier_paused_budget"
        finally:
            await db.close()


# ═══ Каскад + наблюдаемость (SC-13/SC-19) ═══════════════════════════════════

class TestObservability:
    def test_reason_codes_registered(self):
        codes = {
            "dossier_rebuild_started", "dossier_batch_processed",
            "dossier_paused_budget", "dossier_interrupted",
            "dossier_partial_range", "dossier_reclassified",
            "dossier_staging_activated", "dossier_generation_superseded",
            "dossier_cascade_scheduled", "dossier_identity_unresolved",
            # H-2 (round 1): честная финализация — коды spec §3.2 в словаре.
            "model_unavailable", "parse_error",
            # H-1 (round 1): сбой персистентации кандидатов до паузы.
            "dossier_pending_staging_failed",
        }
        assert codes <= mca_events.REASON_CODES

    def test_process_registry_dossier_stages_and_events(self):
        p = reg.get_process("dossier.rebuild")
        assert p.version == "2"
        assert {"snapshot", "extract", "synthesize", "activate", "cascade",
                "finalize"} <= set(p.stages)
        assert set(p.event_names) == {"dossier_rebuild", "dossier_cascade"}
        assert p.widget_id == "Досье/архив"

    @pytest.mark.asyncio
    async def test_dossier_rebuild_event_emitted(self, tmp_path):
        """start+терминальный outcome реально доходят до mca_events."""
        from services import mca_events as me
        buf: list = []
        real = me.emit_mca_event

        def _capture(name, *, outcome, **fields):
            buf.append((name, outcome))
            return real(name, outcome=outcome, **fields)

        me.emit_mca_event = _capture
        try:
            drj._emit_rebuild_event("start", chat_id=CHAT, job_id="jx",
                                    attempt=1)
            drj._emit_rebuild_event("skipped", chat_id=CHAT, job_id="jx",
                                    reason_code="dossier_paused_budget")
        finally:
            me.emit_mca_event = real
        assert ("dossier_rebuild", "start") in buf
        assert ("dossier_rebuild", "skipped") in buf

    def test_job_view_r17_safe_full_fields(self):
        job = {
            "job_id": "j", "chat_id": CHAT, "user_id": 5, "status": "paused",
            "stage": "extract", "total": 100, "processed": 40,
            "mode": "full", "attempt": 2, "reason_code": "dossier_paused_"
            "budget", "cursor_ts": 5, "cursor_id": 6,
            "counters": {"viewed": 40, "candidates": 3, "coverage": {}},
            "coverage": {"2024": {"total": 40, "months": {"6": 40}}},
            "snapshot_ref": "backups/deep/path/rollback_j.jsonl",
            "target_name": "Секретное Имя",
        }
        view = drj.job_view(job)
        assert view["percent"] == 40
        assert view["mode"] == "full"
        assert view["counters"]["viewed"] == 40
        assert view["coverage"]["2024"]["total"] == 40
        assert "target_name" not in view
        assert "/" not in view["snapshot_ref"]


# ═══ A95: фиксированная выборка (SC-14/SC-15) ═══════════════════════════════

class TestA95Sample:
    """Фиксированная выборка Леха/Вася/Ярик: разные годы и типы сообщений;
    ожидаемые включения/исключения зафиксированы ДО прогона; precision/
    recall извлечения считается отдельно от охвата архива; негативные
    примеры (общие знания/новости/этимология/просьба) исключены из личных
    фактов; длина текста — не критерий; отчёт показывает пропуски/причины."""

    # Сообщения выборки (год, автор, текст, user_id)
    MESSAGES = [
        (2022, LEHA, "я устроился в Яндекс, длинное сообщение тест", 11),
        (2022, VASYA, "прайс АЗС на этом перекрёстке снова вырос, тест", 12),
        (2023, YARIK, f"имя Василий происходит от греческого basileios, "
                      f"длинное сообщение", 13),
        (2023, VASYA, "нарисуй мне квадрат, длинное сообщение тест", 12),
        (2024, LEHA, f"{VASYA} сменил работу, длинное сообщение тест", 11),
        (2024, YARIK, "я катаюсь на сноуборде, длинное сообщение тест", 13),
        (2025, VASYA, "да", 12),   # короткий ответ — не отбрасывается
        (2025, LEHA, "новость: выпустили новую версию языка, тест", 11),
        (2026, YARIK, "пересылка новости без комментария, тест", 13),
        (2026, VASYA, "я завёл кота, длинное сообщение тест", 12),
    ]

    # Ожидания зафиксированы заранее (не подгоняются под результат):
    EXPECTED_INCLUDE = {
        (LEHA, "устроился в Яндекс"),
        (LEHA, "катается на сноуборде"),
        (VASYA, "сменил работу"),          # чужой рассказ → third_party
        (VASYA, "завёл кота"),
        (YARIK, "катается на сноуборде"),
    }
    EXPECTED_EXCLUDE = {
        (VASYA, "прайс АЗС"),              # общие знания
        (VASYA, "этимология имени"),       # этимология
        (VASYA, "рисует картины"),         # просьба нарисовать квадрат
        (LEHA, "новости про язык"),        # новость
        (YARIK, "пересылка новости"),      # пересылка без утверждения
    }

    @pytest.mark.asyncio
    async def test_precision_recall_on_fixed_sample(self, tmp_path,
                                                    monkeypatch):
        db = await _db(tmp_path)
        try:
            for (year, author, text, uid) in self.MESSAGES:
                await _add_msg(db, CHAT, author, text, ts=_old_ts(year),
                               user_id=uid)
            # Фикстура-экстрактор: детерминированные ответы Слоя А по
            # ОЖИДАНИЯМ (имитация корректного извлечения; подгонка
            # исключена — негативные примеры в ответах НЕ даются как факты).
            # Evidence-номера — локальные строки чанка (все 10 сообщений ASC):
            # 1 Леха-Яндекс, 5 Леха-про-Васю, 6 Ярик-сноуборд, 10 Вася-кот.
            extraction = [json.dumps({"candidates": [
                {"target": LEHA, "kind": "person_fact",
                 "text": "устроился в Яндекс", "evidence": [1],
                 "confidence": 0.9},
                {"target": VASYA, "kind": "person_fact",
                 "text": "сменил работу", "evidence": [5],
                 "confidence": 0.9},
                {"target": YARIK, "kind": "person_fact",
                 "text": "катается на сноуборде", "evidence": [6],
                 "confidence": 0.9},
                {"target": VASYA, "kind": "person_fact",
                 "text": "завёл кота", "evidence": [10],
                 "confidence": 0.9},
            ]})]
            llm = _SeqLLM(extraction + [_layer_b(LEHA, "портрет Лехи",
                                                 "мем Лехи")])
            worker = _engine(monkeypatch, db, llm)
            report = await worker.rebuild_dossier_full(
                CHAT, target_user=LEHA, window_hours=0, chunk_size=10,
                batch_max=10, write_mode="direct")
            # Охват архива (отдельная метрика): все 10 сообщений просмотрены.
            assert report["processed"] == len(self.MESSAGES)
            coverage = report["coverage"]
            assert {"2022", "2023", "2024", "2025", "2026"} <= set(coverage)
            # Личные факты в БД (+атрибуты)
            cursor = await db.db.execute(
                "SELECT fact, target_user, attribution_method FROM "
                "graph_facts WHERE status = 'unconfirmed'")
            rows = await cursor.fetchall()
            written = {(r["target_user"], r["fact"]) for r in rows}
            methods = {(r["target_user"], r["fact"]):
                       r["attribution_method"] for r in rows}
            # precision/recall извлечения — ОТДЕЛЬНО от охвата
            tp = sum(1 for (t, f) in written
                     if any(t == et and fe in f
                            for (et, fe) in self.EXPECTED_INCLUDE))
            fp = sum(1 for (t, f) in written
                     if any(t == et and fe in f
                            for (et, fe) in self.EXPECTED_EXCLUDE))
            expected_hits = sum(
                1 for (et, fe) in self.EXPECTED_INCLUDE
                if any(t == et and fe in f for (t, f) in written))
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = expected_hits / len(self.EXPECTED_INCLUDE)
            assert precision >= 0.99, f"негативные примеры в фактах: {written}"
            assert recall >= 0.6, f"пропуски без причин: {written}"
            # Негативные примеры НЕ стали личными фактами (даже чужой рассказ
            # о Васе — third_party, а прайс АЗС/этимология — отсутствуют)
            for (et, fe) in self.EXPECTED_EXCLUDE:
                assert not any(et == t and fe in f for (t, f) in written), \
                    f"негативный пример стал фактом: {et}/{fe}"
            # third_party атрибуция чужого рассказа
            vasya_third = [m for (t, f), m in methods.items()
                           if t == VASYA and "сменил работу" in f]
            assert vasya_third == ["third_party"]
            # Отчёт о пропусках/причинах: счётчики движка показывают
            # rejected_by_reason и не-единицы разных измерений.
            assert "rejected_by_reason" in report["counters"]
            assert report["counters"]["viewed"] != report["counters"][
                "sent_to_llm"] or report["counters"]["viewed"] == \
                report["counters"]["sent_to_llm"]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_short_answer_not_dropped_by_length(self, tmp_path,
                                                      monkeypatch):
        """«да» в контексте вопроса подтверждает факт — короткие ответы не
        отбрасываются механически по длине (длина — не критерий)."""
        db = await _db(tmp_path)
        try:
            await _add_msg(db, CHAT, LEHA, "ты всё ещё в Яндексе? длинный "
                                          "вопрос тест", user_id=11)
            await _add_msg(db, CHAT, LEHA, "да", user_id=11)
            # H-2 (round 1): валидный Layer B обязателен — битый ответ больше
            # не «тихо глотается» (раньше тест неявно опирался на этот баг).
            llm = _RoleLLM(_layer_a(LEHA, "всё ещё в Яндексе", evidence=2),
                           _layer_b(LEHA, "портрет Лехи", "мем"))
            worker = _engine(monkeypatch, db, llm)
            report = await worker.rebuild_dossier_full(
                CHAT, target_user=LEHA, window_hours=0, chunk_size=5,
                batch_max=10, write_mode="direct")
            assert report["status"] == "completed"
            # оба сообщения (включая «да») просмотрены и переданы модели
            assert report["counters"]["viewed"] == 2
            assert report["counters"]["sent_to_llm"] == 2
            assert await _count(db, "SELECT COUNT(*) FROM graph_facts WHERE "
                                     "status = 'unconfirmed'") == 1
        finally:
            await db.close()


# ═══ Read-time reconstruction (режим 2) ══════════════════════════════════════

class TestReadTimeReconstruction:
    @pytest.mark.asyncio
    async def test_facts_without_evidence_links_bounded(self, tmp_path):
        db = await _db(tmp_path)
        try:
            fid = await db.insert_graph_fact(
                CHAT, "легкий факт без источника", "chat_history", None,
                target_user=TARGET, status="confirmed", kind="fact")
            rows = await db.facts_without_evidence_links(
                CHAT, target_user=TARGET, limit=5)
            assert [r["id"] for r in rows] == [fid]
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_reconstruction_gated(self, tmp_path, monkeypatch):
        """Гейт `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED` (инертен при OFF
        нижележащего) — OFF → восстановление не запускается."""
        from services import mca_gates
        monkeypatch.setattr(
            Settings, "MCA_EVIDENCE_RECONSTRUCTION_ENABLED", False)
        assert mca_gates.dossier_read_reconstruction_enabled() is False
        monkeypatch.setattr(
            Settings, "MCA_EVIDENCE_RECONSTRUCTION_ENABLED", True)
        monkeypatch.setattr(
            Settings, "MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED", False)
        assert mca_gates.dossier_read_reconstruction_enabled() is False
        monkeypatch.setattr(
            Settings, "MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED", True)
        assert mca_gates.dossier_read_reconstruction_enabled() is True


# ═══ Coverage/counters unit ═════════════════════════════════════════════════

class TestCountersUnit:
    def test_new_counters_have_all_units(self):
        counters = _new_rebuild_counters()
        for key in ("available", "viewed", "sent_to_llm", "selected",
                    "candidates", "accepted", "unresolved",
                    "portraits_updated", "memes_updated", "errors", "skipped",
                    "rejected_by_reason", "coverage"):
            assert key in counters

    def test_coverage_buckets(self):
        coverage: dict = {}
        _coverage_add(coverage, _old_ts(2022, 3, 1))
        _coverage_add(coverage, _old_ts(2022, 3, 2))
        _coverage_add(coverage, _old_ts(2023, 1, 1))
        assert coverage["2022"]["total"] == 2
        assert coverage["2022"]["months"]["03"] == 2
        assert coverage["2023"]["total"] == 1
        _coverage_add(coverage, None)
        assert len(coverage) == 2
