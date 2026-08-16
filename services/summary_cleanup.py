"""Epic 28 — cleanup of raw LLM summary text before postprocessing (R28-3).

The model occasionally breaks SYSTEM_PROMPT rule 3: long dashes and «ёлочки»
slip into the answer. This module normalizes the raw generate() output BEFORE
_ensure_shiz_postfix. Adding a rule = adding one (old, new) pair to REPLACEMENTS.
"""

REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("«", '"'),
    ("»", '"'),
    ("„", '"'),
    ("“", '"'),
    ("—", "-"),
    ("–", "-"),
)


def cleanup_llm_text(text: str) -> str:
    """Replace forbidden typography in the raw LLM answer. Never raises."""
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text
