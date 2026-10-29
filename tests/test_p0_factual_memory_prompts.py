"""SPEECH-P0-B2 (§4 P0 hotfix 25.10.2026) — L2/lore не заказывают
выдуманную историю; факты, JSON/evidence и юмор сохранены.

Контракт владельца: source-owner-p0-hotfix-2026-10-25.md §4 +
evidence/p0-hotfix/memory-provenance.md (M1/M3/M4).

TEST-LIFECYCLE: CONTRACT owner=SPEECH-P0-B2/MEMORY-NO-UNSUPPORTED-CAUSAL-STORY
"""
import pytest

from services import prompt_migrations as pm
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services import summary_prompts as sp
from services.lore_prompts import (
    LORE_INIT_SYSTEM_PROMPT,
    LORE_MERGE_SYSTEM_PROMPT,
    LORE_STORY_SYSTEM_PROMPT,
)

_L2_KEY = "prompts.summary_l2_writer_system_prompt"

@pytest.fixture()
def journal(monkeypatch):
    store = prp.MemoryPromptJournal()
    monkeypatch.setattr(prp, "default_journal", lambda cache=None: store)
    yield store
    pr.set_release_policy_active(False)
    from services import prompt_factory as _pf
    _pf._HISTORY_FROZEN = False
    pr.reset_cache()



class FakeCache:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.pg_available = True
        self.set_calls = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))
        self.values[key] = value


class TestL2FactualCanon:
    def test_no_mandatory_causal_chain(self):
        canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "предысторией, развитием и последствиями" not in canon
        assert "событие → реакция участников → развитие" not in canon
        assert "не достраивай историю ради связности" in canon
        assert "Причинные связи, мотивы и последствия" in canon

    def test_no_data_no_fantasy(self):
        canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "не заполняй пробел фантазией" in canon
        assert "не сочиняй связки ради красоты" in canon

    def test_authorial_comment_is_style_not_new_fact(self):
        canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "только стилистическая авторская оценка" in canon
        assert "а не новый факт и не вывод о людях" in canon

    def test_finale_is_joke_not_verdict(self):
        canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "необязательная шутка в конце, а не фактический вердикт" in canon
        assert "не характеристика человека" in canon
        assert "Кандидат обязан быть участником пакета" in canon

    def test_published_article_json_evidence_preserved(self):
        canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert '"schema_version": 1' in canon
        assert '"paragraphs"' in canon
        assert '"evidence_message_ids": [123, 127]' in canon
        assert "выдуманный ID - ошибка валидации" in canon
        assert "Имена участников бери ТОЛЬКО из пакета" in canon
        assert "Конкретное число" in canon
        assert "ФАКТЫ И МОДАЛЬНОСТЬ" in canon
        assert "ИСТОЧНИК (оригинал — истина)" in canon
        assert '"finale"' in canon


class TestL2PgStageAndRollback:
    def test_prev_snapshot_is_byte_frozen_prod_canon(self):
        prev = sp.PREV_SUMMARY_L2_WRITER_R1030_P0
        assert prev != sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        # Слепок = прод-байты 2.58.130: старая драматургия в нём сохранена,
        # иначе откат не вернёт прежний канон.
        assert "предысторией, развитием и последствиями" in prev
        assert "ИСТОЧНИК (оригинал — истина)" in prev

    def test_stage_declared(self):
        assert (sp.PREV_SUMMARY_L2_WRITER_R1030_P0,
                sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT) in \
            pm.PROMPT_MIGRATIONS[_L2_KEY]
        assert pm.ROLLBACK_MIGRATIONS[_L2_KEY] == [
            (sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT,
             sp.PREV_SUMMARY_L2_WRITER_R1030_P0),
            (sp.PREV_SUMMARY_L2_WRITER_R1030_P0,
             sp.PREV_SUMMARY_L2_WRITER_R1029_ASAP41)]

    @pytest.mark.asyncio
    async def test_dry_run_migrates_prod_canon_and_is_idempotent(
            self, journal):
        """EVOL-016/012: прежний канон → снимок legacy + активная заводская
        редакция; повторный старт — no-op."""
        cache = FakeCache({_L2_KEY: sp.PREV_SUMMARY_L2_WRITER_R1030_P0})
        report = await pm.migrate_prompt_canons(cache)
        assert report.get(_L2_KEY) == "updated"
        assert cache.values[_L2_KEY] == sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        again = await pm.migrate_prompt_canons(cache)
        assert again.get(_L2_KEY) == "same"
        assert cache.values[_L2_KEY] == sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_owner_custom_value_not_touched(self, journal):
        """EVOL-012: кастом владельца — ревизия legacy; заводская активна."""
        custom = "МОЙ КАНОН L2: " + "x" * 120
        cache = FakeCache({_L2_KEY: custom})
        report = await pm.migrate_prompt_canons(cache)
        assert report.get(_L2_KEY) == "updated"
        assert cache.values[_L2_KEY] == sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
        legacy = [r for r in journal.revisions.values()
                  if r.pg_key == _L2_KEY and r.origin == "legacy"
                  and r.content_sha12 == pr.sha12(custom)]
        assert len(legacy) == 1


class TestLoreFactualCanon:
    def test_no_epic_or_inflation_triggers(self):
        for canon in (LORE_MERGE_SYSTEM_PROMPT, LORE_INIT_SYSTEM_PROMPT,
                      LORE_STORY_SYSTEM_PROMPT):
            assert '"эпичную"' not in canon
            assert "эпичной" not in canon
            assert "раздуй" not in canon
            assert "сымпровизируй" not in canon
            assert "из мухи слона" not in canon

    def test_merge_no_strengthening_without_source(self):
        canon = LORE_MERGE_SYSTEM_PROMPT
        assert "уточни/усиль" not in canon
        assert "не переписывай её без нового сообщения" in canon
        assert "Не добавляй причин, мотивов, дат и подробностей" in canon
        assert "Шутка, сарказм и прозвище - не факт" in canon
        assert "ИРОНИЧЕСКИЙ ФИЛЬТР" in canon
        assert "Максимум {max_words} слов" in canon
        assert "UNCHANGED" in canon

    def test_init_facts_only(self):
        canon = LORE_INIT_SYSTEM_PROMPT
        assert "ФАКТЫ: только то, что есть в сообщениях" in canon
        assert "не достраивай историю" in canon
        assert "Шутка, сарказм и прозвище - не факт" in canon
        assert "{max_words}" in canon

    def test_story_honest_scarcity_and_keeps_format(self):
        canon = LORE_STORY_SYSTEM_PROMPT
        assert "честно скажи, что известно" in canon
        assert "не придумывай события, мотивы, подробности и причинные связи" \
            in canon
        assert "Шутка - не факт" in canon
        assert "Сарказм и шутки - в комментариях, а не в фактах" in canon
        # Формат публикации не сломан.
        assert "3-6 абзацев" in canon
        assert "<b>" in canon and "<i>" in canon
        assert "UPD (Свежак)" in canon
        assert "{topic}" in canon


class TestRegistryPin:
    def test_lore_story_factory_is_new_canon(self):
        from services import prompt_registry as pr
        assert pr.factory_text("internal.lore.story") == \
            LORE_STORY_SYSTEM_PROMPT
        assert pr.factory_text("internal.lore.merge") == \
            LORE_MERGE_SYSTEM_PROMPT
        assert pr.factory_text("internal.lore.init") == \
            LORE_INIT_SYSTEM_PROMPT
        assert pr.factory_text("summary.base.l2_writer") == \
            sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
