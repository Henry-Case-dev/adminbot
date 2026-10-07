"""MCA-23 (§22/§24/§25, фаза 2) — ResponseDocument: смысл отделён от доставки.

Writer/Stage-2 производит СМЫСЛ; каналы Delivery Router (plain / rich / media)
рендерят ОДИН и тот же typed artifact. Rich fail → Plain ТОГО ЖЕ документа
без регенерации (§24 «НЕ новый LLM-call», §O Golden). Микро-ответ — один
text block (совместимость с текущим plain-путём).

Closed-set блоков фазы 2: только ``text`` (структурные блоки — при появлении
структурного Writer'а, аддитивно; существующий rich-сборщик строит статью из
текста сам). ``sources`` — R17-safe refs из EvidenceBundle (attribution
теряется при переходе между каналами — §31). ``plain_fallback`` — фиксиро-
ванный plain-рендер; для документа, собранного из финального текста Writer'а,
он равен исходному тексту → доставка байт-в-байт (паритет с 2.58.70).

Чистые данные + детерминированные рендеры: 0 I/O, 0 LLM, никогда не бросают.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextBlock:
    """Один текстовый блок документа (closed-set фазы 2)."""
    text: str


@dataclass(frozen=True)
class ResponseDocument:
    """Typed artifact ответа (§22): title? / blocks[] / sources[] /
    plain_fallback. Пользователь структуру не видит — это внутренний
    носитель смысла между Writer и Delivery Router."""

    title: str = ""
    blocks: tuple[TextBlock, ...] = ()
    sources: tuple[str, ...] = ()
    plain_fallback: str = ""

    def plain_text(self) -> str:
        """Единый plain-рендер (§25): fallback без регенерации; порядок
        блоков сохраняется; tail не отрезается (чанкинг — транспорт)."""
        if self.plain_fallback:
            return self.plain_fallback
        return "\n\n".join(block.text for block in self.blocks
                           if block.text)

    def rich_text(self) -> str:
        """Контент для rich-сборщика (§24): ТОТ ЖЕ смысл, другой канал."""
        return self.plain_text()

    @property
    def is_micro(self) -> bool:
        """Микро-ответ = один text block без заголовка (совместимость)."""
        return len(self.blocks) <= 1 and not self.title


def document_from_answer(text, *, title: str = "", sources=()) \
        -> ResponseDocument:
    """Артефакт из финального текста Writer'а (совместимость фазы 2).

    Один text block, ``plain_fallback`` = исходный текст → round-trip
    ``plain_text()`` байт-в-байт (существующая доставка не меняется).
    Никогда не бросает."""
    clean = str(text or "")
    return ResponseDocument(
        title=str(title or ""),
        blocks=(TextBlock(clean),),
        sources=tuple(str(source) for source in (sources or ())),
        plain_fallback=clean)


def documents_equal_content(first: ResponseDocument,
                            second: ResponseDocument) -> bool:
    """Один и тот же смысл в двух каналах (инвариант §O для тестов/гардов)."""
    return first.plain_text() == second.plain_text()


__all__ = [
    "ResponseDocument",
    "TextBlock",
    "document_from_answer",
    "documents_equal_content",
]
