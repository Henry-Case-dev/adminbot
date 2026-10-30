# -*- coding: utf-8 -*-
"""ADD-SAMPLES-UX §1 (SU-MIGR) — три реальные категории + явный режим мата.

Покрытие:
  * SU-CAT.ENTRY/GENERAL/HUMOR/MAT — ровно три категории записи; запись
    «Общие» без приёма/режима; «Юмор» несёт приём; «Мат» — явное серверное
    поле режима, читается валидацией/выдачей/отбором, а не теги;
  * SU-CAT.REAL — категория сквозная: list/фильтр/отбор по явному полю;
  * SU-CAT.MIGRATE — миграция v37: expression_register/режимные теги → «Мат»
    с явным режимом, приёмы Humor Craft → «Юмор», legacy `other` остаётся
    legacy (не угадываем); ID/ревизии/approved/содержимое/история сохранены;
    идемпотентность (повтор — no-op);
  * SU-REG.NOSPRAWL — ни одной новой таблицы: категории живут в
    humor_samples (структурная проверка + отсутствие новых DDL-таблиц).

TEST-LIFECYCLE: CONTRACT owner=SAMPLES-UX/SU-CAT.* (§1, 20.10.2026)
"""
import sqlite3

import pytest
import pytest_asyncio

from services import mca_sample_library as sl
from services.database import DatabaseService


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(str(tmp_path / "samples-categories.db"))
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


@pytest_asyncio.fixture
async def legacy_db(tmp_path):
    """БД с ДО-миграционной v36-схемой и legacy-данными (реальный путь
    обновления: user_version=36, старые колонки)."""
    path = str(tmp_path / "legacy-v36.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        PRAGMA user_version = 36;
        CREATE TABLE humor_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seed_key TEXT, input_text TEXT NOT NULL, reply_text TEXT NOT NULL,
            technique TEXT, context_note TEXT,
            language TEXT NOT NULL DEFAULT 'ru', tags TEXT,
            rudeness_level INTEGER, author_user_id INTEGER,
            source_kind TEXT NOT NULL, scope TEXT NOT NULL, chat_id INTEGER,
            owner_approved INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            library_version TEXT NOT NULL DEFAULT 'v1',
            revision INTEGER NOT NULL DEFAULT 1, sensitivity_flags TEXT,
            uses_count INTEGER NOT NULL DEFAULT 0, last_used_at INTEGER,
            approved_at INTEGER, created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL, created_by TEXT, updated_by TEXT);
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT, applied_at INTEGER,
            checksum TEXT);
        INSERT INTO schema_migrations (version, name) VALUES (36,
            'humor_samples_v36');
    """)
    rows = [
        # id 1: регистр речи с режимным тегом → «Мат», режим из тега
        (1, "expr-off-banter", "вход мата", "ответ мата",
         "expression_register", '["mode:off", "expression"]', 0, 3, 55),
        # id 2: юмористическая техника → «Юмор»
        (2, "starter-04", "вход юмора", "ответ юмора", "deadpan",
         '["сухо"]', 1, 5, 77),
        # id 3: неоднозначный other → legacy (не угадываем)
        (3, None, "вход other", "ответ other", "other", '[]', 1, 9, 31),
    ]
    for (rid, seed, inp, reply, tech, tags, approved, revision, updated) in rows:
        conn.execute(
            "INSERT INTO humor_samples (id, seed_key, input_text, reply_text,"
            " technique, tags, owner_approved, revision, created_at,"
            " updated_at, created_by, updated_by, source_kind, scope)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1000, ?, 'owner', 'owner',"
            " 'owner_manual', 'global')",
            (rid, seed, inp, reply, tech, tags, approved, revision, updated))
    conn.commit()
    conn.close()
    service = DatabaseService(path)
    await service.initialize()
    yield service
    try:
        await service.close()
    except Exception:
        pass


# ═══ SU-CAT.ENTRY / GENERAL / HUMOR / MAT: категории записи ════════════════

def test_exactly_three_write_categories_and_legacy_is_migration_only():
    assert sl.SAMPLE_CATEGORIES == ("general", "humor", "mat")
    assert "legacy" not in sl.SAMPLE_CATEGORIES
    assert set(sl.SAMPLE_CATEGORY_STORAGE) == \
        {"general", "humor", "mat", "legacy"}


@pytest.mark.asyncio
async def test_general_category_record_crud_without_technique_or_mode(db):
    view, reason = await sl.create_sample(db, fields={
        "input_text": "Как дела?", "reply_text": "Обычно, работаю",
        "category": "general", "technique": "other", "scope": "global"},
        actor="owner")
    assert view is not None, reason
    assert view["category"] == "general"
    assert view["expression_mode"] is None
    # «Общие»: ни приём юмора, ни режим мата не требуются и не навязываются.
    fetched = await sl.get_sample(db, view["id"])
    assert fetched["category"] == "general"
    assert not fetched["technique"] in sl.HUMOR_CRAFT_TECHNIQUES


@pytest.mark.asyncio
async def test_humor_category_carries_technique_metadata(db):
    view, reason = await sl.create_sample(db, fields={
        "input_text": "чайник поставил", "reply_text": "аудит кухни",
        "category": "humor", "technique": "absurd_escalation"}, actor="owner")
    assert view is not None, reason
    assert view["category"] == "humor"
    assert view["technique"] == "absurd_escalation"


@pytest.mark.asyncio
async def test_mat_mode_is_explicit_field_not_tags(db):
    # SU-CAT.MAT: режим — ЯВНОЕ серверное поле; тег режима его не создаёт.
    view, reason = await sl.create_sample(db, fields={
        "input_text": "спор", "reply_text": "ответ с матом",
        "category": "mat", "technique": "expression_register",
        "expression_mode": "frequent", "tags": ["mode:occasional"]},
        actor="owner")
    assert view is not None, reason
    assert view["category"] == "mat"
    assert view["expression_mode"] == "frequent"      # поле, не тег
    fetched = await sl.get_sample(db, view["id"])
    assert fetched["expression_mode"] == "frequent"
    # тег не создаёт режим
    no_mode, reason = await sl.create_sample(db, fields={
        "input_text": "вход", "reply_text": "ответ", "category": "mat",
        "technique": "expression_register", "tags": ["mode:off"]},
        actor="owner")
    assert no_mode is not None, reason
    assert no_mode["expression_mode"] is None
    # mat-карточка без тега сохраняет режим (см. выше) и валидация читает поле
    bad, reason = await sl.update_sample(
        db, view["id"], fields={"expression_mode": "sometimes"}, actor="owner")
    assert bad is None and reason == "unknown_expression_mode"
    bad, reason = await sl.update_sample(
        db, view["id"], fields={"category": "surprise"}, actor="owner")
    assert bad is None and reason == "unknown_category"


# ═══ SU-CAT.REAL: категория сквозная (выдача/фильтр/отбор) ═════════════════

@pytest.mark.asyncio
async def test_category_filter_reads_explicit_field(db):
    for category, technique in (("general", "other"), ("humor", "deadpan"),
                                ("mat", "expression_register")):
        fields = {"input_text": f"вход {category}",
                  "reply_text": f"ответ {category}",
                  "category": category, "technique": technique,
                  "owner_approved": True}
        if category == "mat":
            fields["expression_mode"] = "off"
        view, reason = await sl.create_sample(db, fields=fields, actor="owner")
        assert view is not None, reason
    for category in ("general", "humor", "mat"):
        rows = await sl.list_samples(db, chat_id=None, category=category)
        assert rows, category
        assert all(r["category"] == category for r in rows)
    # фильтр не подменяет категоризацию записи
    humor_rows = await sl.list_samples(db, chat_id=None, category="humor")
    assert humor_rows[0]["category"] == "humor"


@pytest.mark.asyncio
async def test_selection_reads_category_not_word_match(db):
    # mat-пример с «безобидным» текстом не идёт в юмор-путь по категории;
    # humor-пример с обсценным словом не становится регистром.
    rows = [
        sl._to_row({"id": 1, "input_text": "спокойный вход",
                    "reply_text": "спокойный ответ", "technique": "other",
                    "category": "mat", "expression_mode": "off",
                    "owner_approved": 1, "status": "active",
                    "scope": "global", "chat_id": None, "tags": [],
                    "library_version": "v1", "revision": 1, "uses_count": 0,
                    "last_used_at": None, "sensitivity_flags": [],
                    "source_kind": "owner_manual"}),
        sl._to_row({"id": 2, "input_text": "шутка с пиздецом",
                    "reply_text": "смешной ответ", "technique": "deadpan",
                    "category": "humor", "owner_approved": 1,
                    "status": "active", "scope": "global", "chat_id": None,
                    "tags": [], "library_version": "v1", "revision": 1,
                    "uses_count": 0, "last_used_at": None,
                    "sensitivity_flags": [], "source_kind": "owner_manual"}),
    ]
    humor_selection = sl.select_samples(
        rows, chat_id=1, category="humor", context="спокойный вход")
    assert [r["id"] for r in humor_selection.samples] == [2]
    assert any(e["id"] == 1 and e["reason"] == "expression_register"
               for e in humor_selection.excluded)


@pytest.mark.asyncio
async def test_legacy_rows_are_excluded_from_selection_until_classified(db):
    rows = [sl._to_row({"id": 9, "input_text": "вход", "reply_text": "ответ",
                        "technique": "other", "category": "legacy",
                        "owner_approved": 1, "status": "active",
                        "scope": "global", "chat_id": None, "tags": [],
                        "library_version": "v1", "revision": 1,
                        "uses_count": 0, "last_used_at": None,
                        "sensitivity_flags": [],
                        "source_kind": "owner_manual"})]
    selection = sl.select_samples(rows, chat_id=1, category="general")
    assert selection.samples == ()
    assert selection.excluded[0]["reason"] == "category_unassigned"


# ═══ SU-CAT.MIGRATE: миграция v37 на реальном пути обновления ══════════════

@pytest.mark.asyncio
async def test_v37_migration_maps_categories_and_preserves_data(legacy_db):
    cursor = await legacy_db.db.execute("PRAGMA user_version")
    # Пин на фактический хвост реестра, а не на v37: после v37
    # (humor_samples_v37) реестр продолжили EVOL-015 (v38 quote_metadata) и
    # EVOL-016 (v39 prompt_revision_journal).
    assert (await cursor.fetchone())[0] == max(
        s.version for s in DatabaseService.migration_steps())
    for cat in ("mat", "humor", "legacy"):
        rows = await sl.list_samples(legacy_db, chat_id=None, category=cat)
        assert rows, cat
    mat = (await sl.list_samples(legacy_db, chat_id=None, category="mat"))[0]
    assert mat["id"] == 1 and mat["seed_key"] == "expr-off-banter"
    assert mat["expression_mode"] == "off"       # режим из режимного тега
    assert mat["technique"] == "expression_register"   # содержимое сохранено
    assert mat["revision"] == 3 and mat["updated_at"] == 55
    humor = (await sl.list_samples(legacy_db, chat_id=None,
                                   category="humor"))[0]
    assert humor["id"] == 2 and humor["owner_approved"] is True
    legacy = (await sl.list_samples(legacy_db, chat_id=None,
                                    category="legacy"))[0]
    assert legacy["id"] == 3        # `other` НЕ переклассифицирован наугад
    # владелец может сменить категорию legacy-строки
    updated, reason = await sl.update_sample(
        legacy_db, 3, fields={"category": "general"}, actor="owner")
    assert updated is not None and updated["category"] == "general", reason


@pytest.mark.asyncio
async def test_v37_migration_is_idempotent(legacy_db):
    # Миграция уже применилась в initialize(); повтор бэкфила — no-op,
    # данные не меняются второй раз.
    first = await sl.backfill_categories_v37(legacy_db)
    again = await sl.backfill_categories_v37(legacy_db)
    assert again == first
    assert again.get("mat") == 0 and again.get("humor") == 0 \
        and again.get("mode_from_tag") == 0
    rows = await sl.list_samples(legacy_db, chat_id=None, status=None,
                                 limit=500)
    cats = sorted(r["category"] for r in rows)
    assert cats == ["humor", "legacy", "mat"]
    # режим mat-строки уже заполнен миграцией (из тега) и стабилен
    mat = (await sl.list_samples(legacy_db, chat_id=None, category="mat"))[0]
    assert mat["expression_mode"] == "off"


def test_v37_additive_columns_no_new_tables():
    # SU-REG.NOSPRAWL: категории/режим/tombstone/override — колонки
    # СУЩЕСТВУЮЩЕЙ таблицы, новых таблиц/сервисов нет.
    for _, ddl in sl.SAMPLES_V37_ADD_COLUMNS:
        assert ddl.strip().lower().startswith("alter table humor_samples")
    assert "CREATE TABLE" not in " ".join(
        ddl for _, ddl in sl.SAMPLES_V37_ADD_COLUMNS)
    assert "humor_samples" in sl.SAMPLES_DDL


@pytest.mark.asyncio
async def test_schema_version_matches_database_constant():
    from services import database as dbmod
    assert sl.SCHEMA_VERSION_HUMOR_SAMPLES == 37
    assert sl.SCHEMA_VERSION_HUMOR_SAMPLES == \
        dbmod._SCHEMA_VERSION_HUMOR_SAMPLES
    assert dbmod._SCHEMA_VERSION_HUMOR_SAMPLES_V36 == 36


@pytest.mark.asyncio
async def test_telemetry_counts_by_category(db):
    await sl.create_sample(db, fields={
        "input_text": "a", "reply_text": "b", "category": "general"},
        actor="owner")
    await sl.seed_expression_samples(db)
    counts = await sl.telemetry(db, chat_id=None)
    assert counts["by_category"]["general"] >= 1
    assert counts["by_category"]["mat"] >= 12
    assert counts["approved_by_category"]["mat"] == 0  # сиды — черновики
