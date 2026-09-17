"""F3 (T-1963…T-1967, ADR-1021-3) — де-роботизация и канон-миграция.

Покрытие:
  * блоки A «АНТИ-БОТ» / B «АСИММЕТРИЯ» стоят во всех отвечающих канонах;
  * в актуальных константах НЕТ конфликтующей инструкции «уже проверял …
    повторять дважды» и ИИ-тропов (как положительных предписаний);
  * PREV_*_R1021 слепки сохраняют исторический канон (не переписаны);
  * канон-доки (`plans/docs/canon/**`) синхронны с кодом;
  * обратный runbook отката (Д9) на месте.
"""
from pathlib import Path

import pytest

from services.chat_prompts import CHAT_SYSTEM_PROMPT, PREV_CHAT_R1021_SYSTEM_PROMPT
from services.checkup_prompts import (
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_R1021_SYSTEM_PROMPT,
)
from services.factcheck_prompts import (
    FACTCHECK_SYSTEM_PROMPT,
    PREV_FACTCHECK_R1021_SYSTEM_PROMPT,
)
from services.prompt_style_blocks import (
    ANTI_BOT_BLOCK,
    ASYMMETRY_BLOCK,
    BOT_KNOWLEDGE_INSTRUCTION,
    LEGACY_BOT_KNOWLEDGE_INSTRUCTION,
    STYLE_BLOCKS_SUFFIX,
)
from services.search_prompts import (
    PREV_SEARCH_R1021_SYSTEM_PROMPT,
    SEARCH_SYSTEM_PROMPT,
)
from services.summary_prompts import (
    PREV_R1021_SUMMARY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
from services.web_prompts import (
    PREV_WEBPAGE_R1021_SYSTEM_PROMPT,
    WEBPAGE_SYSTEM_PROMPT,
)
from services.youtube_prompts import (
    PREV_YOUTUBE_R1021_SYSTEM_PROMPT,
    PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT,
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)

# key -> (актуальная константа, слепок прод-канона R1021)
ACTUALS: dict[str, tuple[str, str]] = {
    "chat": (CHAT_SYSTEM_PROMPT, PREV_CHAT_R1021_SYSTEM_PROMPT),
    "checkup": (CHECKUP_SYSTEM_PROMPT, PREV_CHECKUP_R1021_SYSTEM_PROMPT),
    "factcheck": (FACTCHECK_SYSTEM_PROMPT, PREV_FACTCHECK_R1021_SYSTEM_PROMPT),
    "search": (SEARCH_SYSTEM_PROMPT, PREV_SEARCH_R1021_SYSTEM_PROMPT),
    "summary": (SYSTEM_PROMPT, PREV_R1021_SUMMARY_SYSTEM_PROMPT),
    "webpage": (WEBPAGE_SYSTEM_PROMPT, PREV_WEBPAGE_R1021_SYSTEM_PROMPT),
    "youtube": (YOUTUBE_SYSTEM_PROMPT, PREV_YOUTUBE_R1021_SYSTEM_PROMPT),
    "youtube_video": (YOUTUBE_VIDEO_SYSTEM_PROMPT,
                      PREV_YOUTUBE_VIDEO_R1021_SYSTEM_PROMPT),
}

# Конфликтующая инструкция старого канона (ТЗ её запрещает).
_CONFLICT_MARKERS = (
    "уже проверял эту инфу ранее",
    "повторять дважды",
    "не нужно повторять",
    "смотрел ролик на эту тему",
)
# ИИ-тропы: в актуальных канонах — только как запрет (блок A их НЕ цитирует).
_TROPE_MARKERS = (
    "как ИИ",
    "надеюсь, помог",
    "нет, ты",
    "ты уже спрашивал",
)


class TestStyleBlocksPresent:
    @pytest.mark.parametrize("name", list(ACTUALS))
    def test_antibot_and_asymmetry_in_every_actual(self, name):
        prompt, _prev = ACTUALS[name]
        assert ANTI_BOT_BLOCK in prompt, name
        assert ASYMMETRY_BLOCK in prompt, name
        if "<bot_knowledge>" in prompt:
            assert prompt.rstrip().endswith(BOT_KNOWLEDGE_INSTRUCTION), name
        else:
            assert prompt.rstrip().endswith("нравоучением."), name

    @pytest.mark.parametrize("name", list(ACTUALS))
    def test_style_suffix_is_shared(self, name):
        prompt, _prev = ACTUALS[name]
        assert STYLE_BLOCKS_SUFFIX in prompt, name


class TestNoForbiddenInstructions:
    @pytest.mark.parametrize("name", list(ACTUALS))
    def test_no_prior_check_instruction(self, name):
        prompt, _prev = ACTUALS[name]
        for marker in _CONFLICT_MARKERS:
            assert marker not in prompt, f"{name}: {marker}"

    @pytest.mark.parametrize("name", list(ACTUALS))
    def test_no_ai_tropes(self, name):
        prompt, _prev = ACTUALS[name]
        for marker in _TROPE_MARKERS:
            assert marker not in prompt, f"{name}: {marker}"

    @pytest.mark.parametrize("name", list(ACTUALS))
    def test_new_bot_knowledge_instruction_kept(self, name):
        prompt, _prev = ACTUALS[name]
        if "<bot_knowledge>" in prompt:
            assert BOT_KNOWLEDGE_INSTRUCTION in prompt
            assert prompt.rstrip().endswith(BOT_KNOWLEDGE_INSTRUCTION)


class TestPrevSnapshotsPreserveHistory:
    @pytest.mark.parametrize("name", list(ACTUALS))
    def test_prev_snapshot_differs_and_keeps_legacy(self, name):
        prompt, prev = ACTUALS[name]
        assert prev != prompt
        assert ANTI_BOT_BLOCK not in prev
        assert ASYMMETRY_BLOCK not in prev
        if "<bot_knowledge>" in prev:
            assert LEGACY_BOT_KNOWLEDGE_INSTRUCTION in prev
            assert prev.rstrip().endswith(LEGACY_BOT_KNOWLEDGE_INSTRUCTION)


class TestCanonDocsSync:
    def _docs(self) -> str:
        return (
            Path("plans/docs/canon/architecture.md").read_text(encoding="utf-8")
            + "\n"
            + Path("plans/docs/canon/backlog.md").read_text(encoding="utf-8")
        )

    def test_docs_have_no_conflicting_instruction(self):
        docs = self._docs()
        assert "уже проверял эту инфу ранее" not in docs
        assert "повторять дважды" not in docs

    def test_docs_have_style_blocks(self):
        docs = self._docs()
        assert "АНТИ-БОТ (СТРОГО ЗАПРЕЩЕНО):" in docs
        assert "АСИММЕТРИЯ:" in docs

    def test_docs_antibot_does_not_quote_tropes(self):
        assert "как ИИ" not in ANTI_BOT_BLOCK
        assert "надеюсь, помог" not in ANTI_BOT_BLOCK
        assert "нет, ты" not in ANTI_BOT_BLOCK
        assert "ты уже спрашивал" not in ANTI_BOT_BLOCK


class TestRollbackRunbook:
    def test_runbook_exists_and_documents_function(self):
        # 10.21: фича заархивирована @PM → артефакты лежат в plans/archive/.
        root = Path(__file__).resolve().parents[1] / "plans"
        path = (root / "features" / "de-robotization-negative-constraints-round1021"
                / "ROLLBACK.md")
        if not path.exists():                # fallback на архив (актуальный)
            path = (root / "archive"
                    / "de-robotization-negative-constraints-round1021"
                    / "ROLLBACK.md")
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "rollback_prompt_canons" in text
        assert "PREV_*_R1021" in text
        for key in (
            "prompts.direct_chat_system_prompt",
            "prompts.factcheck_system_prompt",
            "prompts.search_system_prompt",
            "prompts.summary_system_prompt",
            "prompts.webpage_system_prompt",
            "prompts.youtube_system_prompt",
            "prompts.youtube_video_system_prompt",
            "prompts.checkup_system_prompt",
        ):
            assert key in text
