"""Epic 28 — cleanup of raw LLM summary text before postprocessing (R28-3).

The model occasionally breaks SYSTEM_PROMPT rule 3: long dashes and «ёлочки»
slip into the answer. This module normalizes the raw generate() output BEFORE
_ensure_shiz_postfix. Adding a rule = adding one (old, new) pair to REPLACEMENTS.
"""

from services.reply_postprocess import strip_reasoning_tags

REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("«", '"'),
    ("»", '"'),
    ("„", '"'),
    ("“", '"'),
    ("—", "-"),
    ("–", "-"),
)


def cleanup_llm_text(text: str) -> str:
    """Replace forbidden typography in the raw LLM answer. Never raises.

    Раунд 10.20 (БЛОК 7.2b, ADR-1020-7 §2, T-1921): сначала вырезаются
    reasoning-теги-черновики (`strip_reasoning_tags`) — factcheck/summary
    получают срез автоматически; затем — типографские замены Epic 28.
    """
    text = strip_reasoning_tags(text)
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text
