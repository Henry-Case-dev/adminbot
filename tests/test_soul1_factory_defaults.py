"""SOUL-1 / W1 — Factory Defaults: заводские редакции, сброс, история (§4).

Доказывается:
  * заводской текст блока = код-канон каталога (никакого скрытого дубля:
    runtime использует эффективную активную конфигурацию, а фабрика — тот же
    объект, что показывает каталог);
  * «Вернуть заводской вариант» сначала показывает diff и только потом
    пишет новую active-ревизию; предыдущие ревизии сохраняются в bounded
    истории; повторный сброс — идемпотентный no-op;
  * «Сбросить переопределение чата» ≠ заводской сброс: глобальный ключ не
    пишется, снимается только override чата;
  * глобальный сброс речевого профиля не удаляет локальные overrides и не
    трогает данные бота (память/SelfModel/биография/ключи/бюджеты);
  * аварийная копия W1 восстанавливается в PG идемпотентно (обратимый
    деплой, §7.2).

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.4.1/4.2/4.3/4.4/4.5 (soul-1, W1)
"""
from __future__ import annotations

import pytest

from services import hot_config as hot
from services import prompt_factory as pf
from services import prompt_registry as pr
from services.param_catalog import CATEGORY_PROMPTS


class FakeConfigCache:
    def __init__(self, values: dict | None = None, updated_at: dict | None = None):
        self.values = dict(values or {})
        self.updated_at = dict(updated_at or {})
        self.writes: list[tuple] = []
        self.batches: list[list[tuple]] = []
        self.pg_available = True

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_updated_at(self, key):
        return self.updated_at.get(key)

    async def set(self, key, value, category):
        self.values[key] = value
        self.writes.append((key, value, category))

    async def set_many(self, items):
        self.batches.append(list(items))
        for key, value, category in items:
            self.values[key] = value


@pytest.fixture(autouse=True)
def _clean_caches():
    hot.set_config_cache(None)
    pr.reset_cache()
    yield
    hot.set_config_cache(None)
    pr.reset_cache()


def test_factory_default_is_the_catalog_code_canon():
    """Заводская редакция не дублирует текст: это код-канон каталога."""
    from services.pg_db import resolve_code_source
    checked = 0
    for spec in pr.all_blocks():
        if not spec.pg_key or not spec.code_source:
            continue
        assert pr.factory_default(spec.block_id) == resolve_code_source(
            spec.code_source), spec.block_id
        checked += 1
    assert checked >= 20, "мало проверенных блоков"


@pytest.mark.asyncio
async def test_plan_factory_reset_shows_diff_and_never_writes():
    block_id = "direct.base.l2_writer"
    key = pr.block(block_id).pg_key
    cache = FakeConfigCache({key: "СТАРЫЙ ТЕКСТ\nстрока два"})
    plan = await pf.plan_factory_reset(block_id, cache=cache)
    assert plan["applies"] is True and plan["changed"] is True
    assert plan["diff"]["removed_lines"] >= 1
    assert plan["diff"]["added_lines"] >= 1
    assert plan["current_sha256_12"] != plan["factory_sha256_12"]
    assert cache.writes == [] and cache.values[key] == "СТАРЫЙ ТЕКСТ\nстрока два"
    # Уже заводское значение → сброс не нужен.
    cache2 = FakeConfigCache({key: pr.factory_default(block_id)})
    plan2 = await pf.plan_factory_reset(block_id, cache=cache2)
    assert plan2["changed"] is False


@pytest.mark.asyncio
async def test_apply_factory_reset_new_active_revision_and_history():
    block_id = "direct.base.l2_writer"
    key = pr.block(block_id).pg_key
    cache = FakeConfigCache({key: "правка владельца"})
    result = await pf.apply_factory_reset(block_id, cache=cache, actor=42,
                                          reason="owner test")
    assert result["applied"] is True
    assert cache.values[key] == pr.factory_default(block_id)
    assert result["previous_revision"].startswith(pr.ACTIVE_PREFIX)
    assert result["revision"].startswith(pr.ACTIVE_PREFIX)
    history = await pf.history_for(block_id, cache=cache)
    assert len(history) == 1
    assert history[0]["text"] == "правка владельца"
    assert history[0]["kind"] == "factory_reset"
    assert history[0]["by"] == "42"
    assert cache.values[pf.FACTORY_HISTORY_KEY]["v"] == pf.HISTORY_VERSION
    assert cache.writes[-1][2] == CATEGORY_PROMPTS
    # Повторный сброс — no-op (идемпотентно).
    again = await pf.apply_factory_reset(block_id, cache=cache)
    assert again["applied"] is False and again["reason"] == "already_factory"


@pytest.mark.asyncio
async def test_factory_reset_conflict_on_stale_token():
    block_id = "factcheck.base.single"
    key = pr.block(block_id).pg_key
    cache = FakeConfigCache({key: "правка"}, updated_at={key: "2026-10-16T10:00:00+00:00"})
    with pytest.raises(pf.FactoryConflict):
        await pf.apply_factory_reset(block_id, cache=cache,
                                     expected_updated_at="2026-10-15T00:00:00+00:00")
    assert cache.writes == []


@pytest.mark.asyncio
async def test_history_is_bounded_per_block():
    block_id = "summary.base.single"
    key = pr.block(block_id).pg_key
    cache = FakeConfigCache({key: "v0"})
    for index in range(pf.HISTORY_MAX_PER_BLOCK + 5):
        cache.values[key] = f"правка-{index}"
        await pf.apply_factory_reset(block_id, cache=cache, actor=index)
    history = await pf.history_for(block_id, cache=cache)
    assert len(history) == pf.HISTORY_MAX_PER_BLOCK
    assert history[-1]["text"] == f"правка-{pf.HISTORY_MAX_PER_BLOCK + 4}"


@pytest.mark.asyncio
async def test_reset_chat_override_is_not_factory_reset():
    block_id = "direct.base.l2_writer"
    key = pr.block(block_id).pg_key
    cache = FakeConfigCache({})           # глобального значения нет
    hot.set_config_cache(cache)
    roots = {777: {"overrides": {key: "чат-версия"}}}
    calls: list[tuple] = []

    async def get_root(chat_id):
        return roots.get(int(chat_id), {})

    async def set_root(chat_id, patch, **kwargs):
        calls.append((chat_id, patch, kwargs))
        roots[int(chat_id)] = {"overrides": dict(patch.get("overrides") or {})}

    result = await pf.reset_chat_override(777, block_id, get_root=get_root,
                                          set_root=set_root)
    assert result["applied"] is True
    assert result["factory_value_written"] is False
    assert result["global_value_written"] is False
    assert roots[777]["overrides"] == {}
    assert cache.writes == [], "сброс override записал глобальный ключ"
    assert result["inherits"]["source"] == "Factory"
    assert result["inherits"]["sha256_12"] == pr.sha12(
        pr.factory_default(block_id))
    # Повторный сброс — no-op с диагностикой.
    again = await pf.reset_chat_override(777, block_id, get_root=get_root,
                                         set_root=set_root)
    assert again["applied"] is False
    assert again["reason"] == "no_chat_override"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_global_reset_never_deletes_chat_overrides(monkeypatch):
    from services import chat_params

    called: list[tuple] = []

    async def _boom(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("глобальный сброс тронул chat_params")

    monkeypatch.setattr(chat_params, "set_chat_params", _boom)
    block_id = "search.base.system"
    key = pr.block(block_id).pg_key
    cache = FakeConfigCache({key: "правка глобального слоя"})
    hot.set_config_cache(cache)
    preview = await pf.plan_speech_profile_reset(cache=cache)
    assert preview["chat_overrides_touched"] is False
    assert preview["data_touched"] is False
    affected = {row["block_id"] for row in preview["affected"]}
    assert block_id in affected
    applied = await pf.apply_speech_profile_reset(cache=cache)
    assert applied["chat_overrides_touched"] is False
    assert cache.values[key] == pr.factory_default(block_id)
    assert called == [], "глобальный сброс вызвал chat_params"
    assert all(row.get("chat_overrides_touched") is False
               for row in applied["applied"])


@pytest.mark.asyncio
async def test_speech_profile_reset_covers_only_speech_blocks():
    cache = FakeConfigCache({})
    preview = await pf.plan_speech_profile_reset(cache=cache)
    assert preview["affected"] == []
    assert set(preview["unchanged"]) <= {
        b.block_id for b in pr.speech_blocks() if b.pg_key}
    # Не-речевые ключи (машинные стадии) в набор не входят.
    assert "direct.base.synthesizer" not in set(preview["unchanged"])
    assert "direct.base.synthesizer" in {
        b.block_id for b in pr.all_blocks() if not b.speech}


@pytest.mark.asyncio
async def test_restore_backup_ignores_factory_only_entries():
    """Снимок без захваченного значения (`text`) ничего не восстанавливает.

    Защита от молчаливого затирания правки владельца заводским текстом:
    factory_text не является источником отката.
    """
    key = "prompts.summary_narrator_system_prompt"
    backup = {"keys": {key: {"factory_text": "заводской текст",
                             "category": "prompts"}}}
    cache = FakeConfigCache({key: "правка владельца"})
    assert await pf.restore_backup(backup, cache=cache) == {
        "apply": False, "planned": [], "changed": 0,
        "history_key": pf.FACTORY_HISTORY_KEY}
    done = await pf.restore_backup(backup, apply=True, cache=cache)
    assert done["applied"] == []
    assert cache.values[key] == "правка владельца"
    assert cache.writes == []


@pytest.mark.asyncio
async def test_restore_backup_roundtrip_is_idempotent():
    key = "prompts.factcheck_system_prompt"
    original = pr.factory_text("factcheck.base.single") + "\n\nowner tail"
    backup = {"keys": {key: {"text": original, "category": "prompts"}}}
    cache = FakeConfigCache({key: "нормализованное значение"})
    plan = await pf.restore_backup(backup, cache=cache)
    assert plan["apply"] is False and plan["changed"] == 1
    assert cache.values[key] == "нормализованное значение"
    done = await pf.restore_backup(backup, apply=True, cache=cache, actor=7)
    assert [row["key"] for row in done["applied"]] == [key]
    assert cache.values[key] == original
    again = await pf.restore_backup(backup, apply=True, cache=cache)
    assert again["applied"] == []          # идемпотентно
    history = await pf.history_for("factcheck.base.single", cache=cache)
    assert history and history[-1]["kind"] == "backup_restore"


@pytest.mark.asyncio
async def test_restore_backup_accepts_pg_value_at_backup_source():
    """SMALL-4/review-w1 SMALL-3: документированный источник `pg_value_at_backup`.

    До фикса: `plan` читал оба поля, а `apply` — только `["text"]` →
    `KeyError('text')`. Теперь оба шага используют одну селекцию источника и
    возвращение значения помечено как ДАННЫЕ (старый канон не становится
    действующим слоем, §4.6).
    """
    key = "prompts.search_system_prompt"
    original = pr.factory_text("search.base.system")
    backup = {"keys": {key: {"pg_value_at_backup": original,
                             "factory_text": "заводской", "category": "prompts",
                             "sha256_12": pr.sha12(original)}}}
    cache = FakeConfigCache({key: "другое значение"})
    plan = await pf.restore_backup(backup, cache=cache)
    row = plan["planned"][0]
    assert row["source_field"] == "pg_value_at_backup"
    assert row["backup_sha256_12"] == pr.sha12(original)
    assert row["withheld_in_runtime"] is True     # legacy-канон: не слой, данные
    done = await pf.restore_backup(backup, apply=True, cache=cache)
    assert [r["key"] for r in done["applied"]] == [key]
    assert done["applied"][0]["effective_layer"] == "withheld_factory_governs"
    assert cache.values[key] == original            # значение возвращено
    again = await pf.restore_backup(backup, apply=True, cache=cache)
    assert again["applied"] == []                  # идемпотентно


@pytest.mark.asyncio
async def test_write_speech_value_is_the_active_layer_path():
    """§1.1/§4.1: правка владельца через API реестра → значение действует."""
    block_id = "direct.base.l2_writer"
    key = pr.block(block_id).pg_key
    factory = pr.factory_default(block_id)
    custom = factory + "\n\nПравка владельца из MiniApp."
    cache = FakeConfigCache({key: factory})
    result = await pf.write_speech_value(block_id, custom, cache=cache,
                                         actor="owner", reason="miniapp")
    assert result["applied"] is True and result["effective"] is True
    assert result["scope"] == "global"
    assert cache.values[key] == custom
    assert cache.writes[-1][0] == key          # последнее действие — значение
    assert cache.writes[-1][2] == CATEGORY_PROMPTS
    entry = pr.attested_revision(block_id, cache=cache)
    assert entry["sha256_12"] == pr.sha12(custom)
    assert entry["kind"] == "owner_edit" and entry["scope"] == "global"
    history = await pf.history_for(block_id, cache=cache)
    assert history[-1]["text"] == factory and history[-1]["kind"] == "owner_edit"
    # Пустое значение не пишется (пустота не «обнуляет» речевой слой).
    empty = await pf.write_speech_value(block_id, "   ", cache=cache)
    assert empty["applied"] is False and empty["reason"] == "empty_value"
    assert cache.values[key] == custom
    # Optimistic-конфликт: чужая правка между чтением и записью.
    with pytest.raises(pf.FactoryConflict):
        await pf.write_speech_value(block_id, "новая правка", cache=cache,
                                    expected_updated_at="2026-10-15T00:00:00Z")


@pytest.mark.asyncio
async def test_write_speech_value_chat_scope_attests_override():
    """Per-chat правка через API реестра: наследование глобала + провенанс."""
    block_id = "direct.base.tool_phase"
    key = pr.block(block_id).pg_key
    cache = FakeConfigCache({})
    hot.set_config_cache(cache)
    roots = {777: {"overrides": {}}}
    calls: list[tuple] = []

    async def get_root(chat_id, *a, **kw):
        return roots.get(int(chat_id), {})

    async def set_root(chat_id, patch, **kw):
        calls.append((chat_id, patch, kw))
        roots[int(chat_id)] = {"overrides": dict(patch.get("overrides") or {})}

    result = await pf.write_speech_value(block_id, "чат-версия базы",
                                         cache=cache, chat_id=777,
                                         get_root=get_root, set_root=set_root,
                                         actor=5)
    assert result["applied"] is True and result["scope"] == "chat"
    assert roots[777]["overrides"][key] == "чат-версия базы"
    entry = pr.attested_revision(block_id, cache=cache)
    assert entry["scope"] == "chat" and entry["chat_id"] == 777
    assert len(calls) == 1
    # Повторная запись того же значения — no-op, но провенанс сохраняется.
    again = await pf.write_speech_value(block_id, "чат-версия базы",
                                        cache=cache, chat_id=777,
                                        get_root=get_root, set_root=set_root)
    assert again["applied"] is False
    assert again["reason"] == "already_that_value"
    assert len(calls) == 1
