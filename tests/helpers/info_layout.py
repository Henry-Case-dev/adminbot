"""Общий util для гейтов вёрстки Справки (F9 10.23, review iter1 п.6).

Единая реализация регламентного правила «между соседними примерами-цитатами
(``<blockquote>``) нет точек/запятых/союза „или“» — используется тестами
``test_help_ui_round1022`` и ``test_help_ui_round1023`` (устранён копипаст).
"""
import re


def between_adjacent_blockquotes(text: str) -> list[str]:
    """Тексты-разделители, стоящие непосредственно между соседними
    ``</blockquote>`` и ``<blockquote>`` (без block-level прозы: если между ними
    начинается ``<p>``/``<h1>``/``<h2>`` — это разные смысловые группы, а не
    соседние примеры). Пустой/whitespace-разделитель = «примеры подряд»."""
    gaps = []
    for close in re.finditer(r"</blockquote>", text):
        nxt = text.find("<blockquote>", close.end())
        if nxt == -1:
            continue
        gap = text[close.end():nxt]
        if "<p>" in gap or "<h1>" in gap or "<h2>" in gap:
            continue
        gaps.append(gap)
    return gaps
