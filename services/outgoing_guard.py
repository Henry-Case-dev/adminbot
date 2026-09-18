"""F6 (T-2064, ADR-1022-6 §2) — единый egress-предохранитель.

``sanitize_outgoing`` — единственная чистая функция (без I/O и БД), через
которую проходит любой текст перед отправкой в Telegram. Порядок:

1) ``strip_reasoning_tags`` (reuse ``services/reply_postprocess``) — срезает
   ``<thought>``-семейство черновиков;
2) вырезает технические ID-маркеры ``\\bfact:\\d+\\b`` / ``\\bmsg:\\d+\\b``;
3) вырезает технический маркер целевой команды (``services/target_marking``,
   раунд 10.23 F1) — defense-in-depth: служебный указатель LLM не должен
   попадать пользователю, даже если Stage-1 проэхоил его в выжимку;
4) no-op, если паттернов нет — исходная строка байт-в-байт;
5) нормализация пробелов ТОЛЬКО вокруг вырезанного фрагмента (одиночный
   разделитель, без двойных пробелов).

Клише (ИИ/канцелярит) кодом **НЕ** вырезаются — вето владельца (UPD3 Д-10):
за них отвечает Validator Loop (``services/negative_constraints``).

Fail-closed: неожиданная ошибка → пустая строка (сырьё не уходит) + WARNING
с длинами (R17: без содержимого).
"""
from __future__ import annotations

import logging
import re

from services.reply_postprocess import strip_reasoning_tags
from services.target_marking import TARGET_MARKER_CORE

logger = logging.getLogger(__name__)

# Технические ID-маркеры канона 4D-памяти (латиница, якорные границы слов).
# Захватываем пробелы по краям, чтобы на стыке оставался один разделитель:
# ``(\s*)token(\s*)`` → ``" "`` если пробел был с ОБЕИХ сторон, иначе ``""``.
_ID_RE = re.compile(
    r"(\s*)\b(?:fact|msg)\s*:\s*\d+\b(\s*)",
    re.IGNORECASE,
)

# Раунд 10.23 (F1, ADR-1023-1): технический указатель целевой команды
# (``<<< [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]`` и/или его ядро) — режем как технический
# токен; пробелы по краям нормализуются (одиночный разделитель).
_TARGET_MARKER_RE = re.compile(
    r"(\s*)(?:<<<)?\s*" + re.escape(TARGET_MARKER_CORE) + r"(\s*)",
)

# Точка расширения: дополнительные компилированные паттерны (сегодня пусто).
EXTRA_PATTERNS: tuple[re.Pattern[str], ...] = ()

# Двойные горизонтальные пробелы на стыке вырезанного тега-черновика.
_WS_JUNCTION_RE = re.compile(r"[ \t]{2,}")


def _repl_id(match: re.Match[str]) -> str:
    return " " if (match.group(1) and match.group(2)) else ""


def _repl_marker(match: re.Match[str]) -> str:
    return " " if (match.group(1) and match.group(2)) else ""


def sanitize_outgoing(text: str, *, parse_mode: str | None = None) -> str:
    """Очистить текст перед отправкой. Никогда не бросает.

    * без технических паттернов — исходная строка (no-op, байт-в-байт);
    * ``parse_mode`` зарезервирован (HTML/Markdown guard не трогает);
    * ошибка → ``""`` (fail-closed) + WARNING с длинами.
    """
    try:
        source = str(text or "")
        if not source:
            return ""
        out = strip_reasoning_tags(source)
        if out != source:
            # Нормализация стыка ПОСЛЕ вырезания тега-черновика (двойные
            # горизонтальные пробелы → один).
            out = _WS_JUNCTION_RE.sub(" ", out)
        out = _ID_RE.sub(_repl_id, out)
        out = _TARGET_MARKER_RE.sub(_repl_marker, out)
        for pattern in EXTRA_PATTERNS:
            out = pattern.sub("", out)
        return out
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "[egress] sanitize failed — outgoing suppressed | in_chars=%d",
            len(str(text or "")))
        return ""
