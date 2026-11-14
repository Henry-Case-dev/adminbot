"""EPIC-PROMPT-VERSIONING-UX-01 / PVR-S6 — аудит полей промптов и версионного UI.

Проверяет постоянное правило ``docs/prompt-versioning-contract.md`` §1:
любой промпт, отображаемый для редактирования, обязан иметь реестр, журнал,
одинаковую панель версий (история, diff, активация, baseline, восстановление)
и не иметь обходного пути записи. Тест ОБЯЗАН уметь падать.

Слой 1 — реестр ↔ доступная поверхность редактирования:
  * каждый PG-блок реестра либо виден в каталоге параметров (не ``hidden``),
    либо покрыт спец-карточкой модуля, названным экраном или слотом-выбором;
  * скрытый в каталоге промпт без названной альтернативы = поле, которое
    нельзя править в админке (архитектурная регрессия, а не «мелочь»);
  * исключения не «загнивают»: ключ обязан существовать, а поверхность —
    действительно существовать (маршрут есть в приложении).

Согласованность ``pg_key`` / ``block_id``:
  * ``block_id`` уникальны, ``pg_key`` разрешается обратно в тот же блок;
  * несколько блоков на одном ``pg_key`` — только документ из блоков-полей;
  * ``ui='code_only'`` ⟺ нет ``pg_key``;
  * ``scope='code'`` при наличии ``pg_key`` — только названный список с
    причиной (текущий остаток, см. контракт §8 п.4), иначе падение.

Слой 3 — рантайм-страж ``PromptJournalBypass``: прямой
``ConfigCache.set/set_many`` и ``chat_params.set_chat_params`` для КАЖДОГО
редактируемого ключа реестра отвергаются, значение не пишется.

Поведенческая матрица каждой точки записи (слой 2) и негативные мутации
живут в ``tests/test_prompt_versioning_enforcement.py``; списки поверхностей
импортируются оттуда, чтобы не было второго источника правды.

Запуск: ``pytest tests/test_prompt_field_audit.py``.

TEST-LIFECYCLE: CONTRACT owner=EPIC-PROMPT-VERSIONING-UX-01
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

import pytest

from services import chat_params
from services import param_catalog as pc
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services.config_cache import ConfigCache
from tests.test_meme_pipeline_api import CHAT_A, _ProfileConn
from tests.test_prompt_versioning_enforcement import (
    NON_CATALOG_SURFACES,
    SPECIALIZED_CARDS,
)
from tests.test_webapp_api import _FakePg
from web.app import create_app

#: Ключ-слот выбора (стиль обложки): значение — идентификатор, не текст
#: промпта. Правится выбором в разделе Summary, в текстовом каталоге скрыт.
#: Источник правды — ``prompt_release_policy.NON_TEXT_VALUE_KEYS``; маршрут
#: выбора обязан существовать.
VALUE_SLOT_ROUTES = {"prompts.summary_cover_style_id": "/api/cover/select"}

#: Поверхности спец-карточек: ключ → маршрут редактирования модуля.
SPECIALIZED_ROUTES = {
    "prompts.meme_joke": "/api/initiative/meme-settings",
    "prompts.meme_image": "/api/initiative/meme-settings",
}

#: ``scope='code'`` при наличии ``pg_key`` — противоречие §4 контракта
#: (code = блок без ``pg_key``). Текущий остаток объявлен поимённо с причиной;
#: новый такой блок обязан провалить тест, а не «потеряться».
SCOPE_CODE_WITH_PG_KEY: dict[str, str] = {
    "initiative.meme.joke":
        "метаданные до MEME-P0: значение живёт в global/chat, текст в журнале",
    "initiative.meme.image":
        "метаданные до MEME-P0: значение живёт в global/chat, текст в журнале",
    "factcheck.subject":
        "S13: служебная машинная стадия, заводской текст — код-канон, правка "
        "идёт ключом каталога prompts.factcheck_subject_system_prompt",
    "factcheck.critique.directive":
        "речевая директива публикуется как текст блока, правится через speech",
}

#: Маршруты «одинаковой панели версий»: без них правило §1 не выполнено.
VERSION_UI_ROUTES = (
    "/api/prompts/catalog",
    "/api/prompts/{prompt_key}/versions",
    "/api/prompts/revisions/{revision_id}/source",
    "/api/prompts/revisions/diff",
    "/api/prompts/{prompt_key}/activate",
    "/api/prompts/{prompt_key}/baseline",
    "/api/prompts/{prompt_key}/baseline/restore",
    "/api/prompts/{prompt_key}/factory/restore",
)

#: Базовые маршруты записи/каталога, на которые опирается аудит поверхностей.
EDIT_ROUTES = (
    "/api/config",
    "/api/config/params-meta",
    "/api/speech/core",
)


@pytest.fixture(scope="module")
def app_paths() -> set[str]:
    """Реальные пути приложения: поверхность «есть» = маршрут существует."""
    conn = _ProfileConn(role_rows=[], admin_rows=[])
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    return set(create_app(cache).openapi()["paths"])


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


def _pg_blocks():
    """Блоки реестра с управляемым значением (``pg_key``) — редактируемые."""
    return tuple(b for b in pr.all_blocks() if b.pg_key)


def _editable_blocks():
    """Блоки, чьё значение владелец правит (``code_only`` — read-only)."""
    return tuple(b for b in _pg_blocks() if b.ui != "code_only")


def _new_cache() -> ConfigCache:
    conn = _ProfileConn(role_rows=[], admin_rows=[])
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    asyncio.run(cache.reload())
    return cache


def _doc_grants(spec) -> list:
    """Журнальные права на все блоки-поля одного документа."""
    return [prp.JournalWriteGrant(b.block_id, "global", None)
            for b in pr.all_blocks() if b.pg_key == spec.pg_key]


def _catalog_visible(pg_key: str) -> bool:
    entry = pc.get_by_pg_key(pg_key)
    return entry is not None and not getattr(entry, "hidden", False)


# ═══════════════════════════════════════════════════════════════════════════
# Слой 1 — у каждого редактируемого промпта есть достижимая поверхность
# ═══════════════════════════════════════════════════════════════════════════

def test_every_editable_prompt_has_reachable_surface(app_paths):
    """PG-блок без видимой поверхности редактирования — регрессия (§1)."""
    uncovered: list[str] = []
    for spec in _editable_blocks():
        key = spec.pg_key
        if _catalog_visible(key):
            continue
        if key in SPECIALIZED_ROUTES or key in NON_CATALOG_SURFACES \
                or key in VALUE_SLOT_ROUTES:
            continue
        uncovered.append(f"{spec.block_id} ({key}, ui={spec.ui})")
    assert uncovered == [], (
        "промпты, которые нельзя отредактировать в админке: %s" % uncovered)


def test_specialized_card_routes_exist_and_cover_real_blocks(app_paths):
    """Спец-карточка — это маршрут в приложении и настоящий блок реестра."""
    assert set(SPECIALIZED_ROUTES) <= set(SPECIALIZED_CARDS), (
        "спец-маршрут объявлен для ключа вне SPECIALIZED_CARDS")
    for key, route in sorted(SPECIALIZED_ROUTES.items()):
        assert route in app_paths, f"{key}: маршрута {route} нет в приложении"
        spec = pr.by_pg_key(key)
        assert spec is not None and spec.pg_key == key, key
        assert spec.ui != "code_only", key


def test_named_screens_are_reachable(app_paths):
    """Названный экран существует, а его ключи не висят в пустоте."""
    assert "/api/speech/core" in app_paths, "экрана «Характер» нет"
    for key, surface in sorted(NON_CATALOG_SURFACES.items()):
        spec = pr.by_pg_key(key)
        assert spec is not None, f"{key}: нет блока реестра (устаревшая запись)"
        assert surface.strip(), key
        assert not _catalog_visible(key), (
            f"{key}: уже виден в каталоге — запись {surface!r} устарела")


def test_value_slot_blocks_are_declared_non_text(app_paths):
    """Слот-выбор: скрыт в каталоге, объявлен нетекстовым, маршрут есть."""
    for key, route in sorted(VALUE_SLOT_ROUTES.items()):
        assert route in app_paths, f"{key}: маршрута выбора {route} нет"
        assert key in prp.NON_TEXT_VALUE_KEYS, (
            f"{key}: не объявлен в NON_TEXT_VALUE_KEYS — страж будет считать "
            "его текстом промпта")
        entry = pc.get_by_pg_key(key)
        assert entry is not None and entry.hidden, (
            f"{key}: слот-значение не должно попадать в текстовый каталог")
    stale = sorted(set(VALUE_SLOT_ROUTES) - set(prp.NON_TEXT_VALUE_KEYS))
    assert stale == [], f"устаревшие слоты: {stale}"


def test_code_only_blocks_are_read_only_not_editable(app_paths):
    """``code_only`` — история и сравнение есть, поля редактирования нет."""
    code_only = [b for b in pr.all_blocks() if b.ui == "code_only"]
    assert code_only, "нет code-only блоков — проверять нечего"
    for spec in code_only:
        assert not spec.pg_key, f"{spec.block_id}: code_only с pg_key"
    assert "/api/prompts/{prompt_key}/versions" in app_paths
    # Включение/запись для блока без значения — отказ с причиной, не «успех».
    result = asyncio.run(prp.write_prompt_values(
        [prp.PromptWriteItem(block_id=code_only[0].block_id, text="x")],
        store=prp.MemoryPromptJournal(), actor="owner"))
    assert result["applied"] == []
    assert result["rejected"] and \
        result["rejected"][0]["reason"] == "block_not_pg_managed"


# ═══════════════════════════════════════════════════════════════════════════
# ``pg_key`` ↔ ``block_id``: согласованность адреса значения
# ═══════════════════════════════════════════════════════════════════════════

def test_block_ids_are_unique():
    seen: dict[str, str] = {}
    for spec in pr.all_blocks():
        assert spec.block_id not in seen, (
            f"block_id {spec.block_id!r} объявлен дважды под ключами "
            f"{seen.get(spec.block_id)!r} и {spec.pg_key!r}")
        seen[spec.block_id] = spec.pg_key


def test_pg_key_resolves_back_to_same_block():
    """Адрес значения однозначен: ``by_pg_key`` возвращает блок этого ключа."""
    for spec in _pg_blocks():
        found = pr.by_pg_key(spec.pg_key)
        assert found is not None, f"{spec.block_id}: pg_key {spec.pg_key} не резолвится"
        assert found.pg_key == spec.pg_key, spec.block_id
        assert pr.block(spec.block_id) is not None, spec.block_id


def test_shared_pg_key_is_an_explicit_document():
    """Один ``pg_key`` на несколько блоков — только документ блоков-полей."""
    by_key: dict[str, list] = defaultdict(list)
    for spec in _pg_blocks():
        by_key[spec.pg_key].append(spec)
    for key, specs in sorted(by_key.items()):
        if len(specs) == 1:
            continue
        for spec in specs:
            assert getattr(spec, "pg_doc_field", ""), (
                f"{key}: {spec.block_id} делит pg_key без pg_doc_field — "
                "адрес значения неоднозначен")
        fields = {spec.pg_doc_field for spec in specs}
        assert len(fields) == len(specs), (
            f"{key}: два блока документа с одним полем {fields}")


def test_ui_classification_matches_pg_key():
    """``ui``-классификация не противоречит наличию адреса значения.

    Правила: ``code_only`` ⟺ нет ``pg_key``; ``catalog`` ⟹ есть ``pg_key``;
    ``catalog_pending`` ⟹ блок НЕ виден в каталоге параметров (иначе метка
    «ожидает каталога» лжёт, а поле остаётся без честно названной поверхности).
    """
    for spec in pr.all_blocks():
        if spec.ui == "code_only":
            assert not spec.pg_key, (
                f"{spec.block_id}: ui=code_only при pg_key {spec.pg_key}")
        elif spec.ui == "catalog":
            assert spec.pg_key, (
                f"{spec.block_id}: ui=catalog без pg_key — в каталоге нет поля")
        elif spec.ui == "catalog_pending":
            assert not _catalog_visible(spec.pg_key or ""), (
                f"{spec.block_id}: ui=catalog_pending, но ключ уже виден "
                "в каталоге — метка устарела")
        else:                                   # неизвестная классификация
            raise AssertionError(
                f"{spec.block_id}: неизвестный ui={spec.ui!r}")


def test_scope_code_conflicts_are_named_and_current():
    """``scope='code'`` с ``pg_key`` — только названный остаток, с причиной."""
    conflicts = {spec.block_id for spec in _pg_blocks()
                 if spec.scope == "code"}
    assert conflicts == set(SCOPE_CODE_WITH_PG_KEY), (
        "новый блок с scope='code' и pg_key (контракт §4: code = без pg_key): "
        f"{sorted(conflicts - set(SCOPE_CODE_WITH_PG_KEY))}; "
        f"устаревшие записи: {sorted(set(SCOPE_CODE_WITH_PG_KEY) - conflicts)}")
    for block_id, reason in sorted(SCOPE_CODE_WITH_PG_KEY.items()):
        assert reason.strip(), block_id


def test_registry_snapshot_counts_are_stable():
    """Счётчики реестра меняются только осознанно (документ §2 цитирует их).

    Это «канарейка» изменения состава реестра: если блок добавлен/снят, число
    здесь и в ``docs/prompt-versioning-contract.md`` §2 обновляется в том же
    коммите — иначе документ снова начнёт врать (прежний дрейф §7).
    """
    blocks = pr.all_blocks()
    with_text = [b for b in blocks if pr.factory_text(b.block_id)]
    # SMART-EXECUTION-RELIABILITY-01 §S13 (14.11.2026): +1 блок
    # `factcheck.subject` (+1 печать/метка/`pg_key`) и §G — блок
    # `direct.tool_finalize` уже учтён предыдущей полосой; оба идут одной
    # релизной линией, поэтому пин и §2 контракта обновлены вместе.
    assert len(blocks) == 114, (
        f"блоков {len(blocks)}: обновите §2 контракта и этот пин")
    assert len(with_text) == 113, len(with_text)
    assert len(pr.FACTORY_REVISION_SEALS) == 113
    assert len(pr.FACTORY_REVISION_LABELS) == 104, (
        len(pr.FACTORY_REVISION_LABELS))
    assert len(_pg_blocks()) == 40
    assert len([b for b in blocks if not b.pg_key]) == 74


# ═══════════════════════════════════════════════════════════════════════════
# Версионный UI: панель одна и та же для всех промптов
# ═══════════════════════════════════════════════════════════════════════════

def test_version_ui_routes_exist_for_every_prompt(app_paths):
    """История, тело, diff, активация, baseline, восстановление — есть в API."""
    missing = [route for route in VERSION_UI_ROUTES if route not in app_paths]
    assert missing == [], f"нет маршрутов панели версий: {missing}"
    missing_edit = [route for route in EDIT_ROUTES if route not in app_paths]
    assert missing_edit == [], f"нет маршрутов редактирования: {missing_edit}"


# ═══════════════════════════════════════════════════════════════════════════
# Слой 3 — прямой обход журнала отвергается для КАЖДОГО ключа реестра
# ═══════════════════════════════════════════════════════════════════════════

def _bypass_value(spec):
    """Значение-мутация: текст или документ блоков-полей Core."""
    if getattr(spec, "pg_doc_field", ""):
        field = spec.pg_doc_field
        return {field: "чужой текст мимо журнала"}
    return "чужой текст мимо журнала"


def test_guard_rejects_direct_cache_write_for_every_prompt():
    """``cache.set_many``/``cache.set`` текста промпта без журнала — отказ."""
    checked = 0
    for spec in _editable_blocks():
        if spec.pg_key in prp.NON_TEXT_VALUE_KEYS:
            continue        # слот-значение, не текст промпта (§3.4)
        cache = _new_cache()
        if getattr(spec, "pg_doc_field", ""):
            # Документ Core: мутируем поле текста внутри документа.
            doc = {spec.pg_doc_field: "прежний текст"}
            with prp.journal_write_scope(_doc_grants(spec)):
                asyncio.run(cache.set(spec.pg_key, doc, "content"))
            with pytest.raises(prp.PromptJournalBypass):
                asyncio.run(cache.set(spec.pg_key, _bypass_value(spec),
                                      "content"))
            assert cache.get(spec.pg_key)[spec.pg_doc_field] == \
                "прежний текст", f"{spec.block_id}: обход записал текст"
        else:
            with pytest.raises(prp.PromptJournalBypass):
                asyncio.run(cache.set_many(
                    [(spec.pg_key, _bypass_value(spec), "prompts")]))
            assert cache.get(spec.pg_key) is None, (
                f"{spec.block_id}: обход записал значение")
            with pytest.raises(prp.PromptJournalBypass):
                asyncio.run(cache.set(spec.pg_key, _bypass_value(spec),
                                      "prompts"))
            assert cache.get(spec.pg_key) is None
        checked += 1
    assert checked >= 35, f"проверено слишком мало ключей: {checked}"


def test_guard_rejects_direct_chat_override_write_for_every_prompt():
    """``chat_params.set_chat_params`` текста промпта без журнала — отказ."""
    checked = 0
    for spec in _editable_blocks():
        if spec.pg_key in prp.NON_TEXT_VALUE_KEYS:
            continue
        cache = _new_cache()
        with pytest.raises(prp.PromptJournalBypass):
            asyncio.run(chat_params.set_chat_params(
                CHAT_A, {"overrides": {spec.pg_key: _bypass_value(spec)}},
                pg=cache.pg))
        stored = asyncio.run(chat_params.get_all_chat_params(CHAT_A,
                                                            pg=cache.pg))
        assert (stored.get("overrides") or {}).get(spec.pg_key) is None, (
            f"{spec.block_id}: обход записал чатовый override")
        checked += 1
    assert checked >= 35, f"проверено слишком мало ключей: {checked}"


def test_guard_is_not_vacuous_for_a_journalled_write():
    """Тот же ключ внутри журнального токена пишется (страж не «всё запрещает»)."""
    spec = pr.by_pg_key("prompts.meme_joke")
    assert spec is not None
    cache = _new_cache()
    with prp.journal_write_scope([prp.JournalWriteGrant(spec.block_id, "global",
                                                       None)]):
        asyncio.run(cache.set(spec.pg_key, "запись через журнал", "prompts"))
    assert cache.get(spec.pg_key) == "запись через журнал"
