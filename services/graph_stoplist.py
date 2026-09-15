"""Единый источник STOP_LIST графа памяти (F3 `graph-density-scoring-stoplist`).

Два списка РАЗНЫЕ по назначению (ADR-1018-3 §D3 / ADR-1018-5 §D-stoplists):

  * ``GRAPH_CENTER_STOPLIST`` — слова-форматы, которые НЕ могут становиться
    ЦЕНТРАМИ кластеров (seed-выборка ``graph_snapshot``): есть «сообщение»,
    нет «стикер». Как периферия в графе остаются (ТЗ §3.1).
  * ``METAFACT_PENALTY_STOPLIST`` — мета-факты, которым срезается importance
    на записи (F5 `metafact-penalty-extractor-prompt`): есть «стикер», нет
    «сообщение». F5 переиспользует ``is_metafact_stopword`` — без дублирования.

Нормализация ``normalize_token`` — casefold + strip + срез пунктуации по краям
+ ё→е. SQLite-функция ``lower()`` умеет только ASCII и НЕ понижает кириллицу,
поэтому матчинг STOP_LIST-центров делается в Python (``is_center_stopword``).
"""
import re

GRAPH_CENTER_STOPLIST: frozenset[str] = frozenset({
    "видеосообщение", "голосовое", "сообщение", "фото", "кружочек", "ссылка"})

METAFACT_PENALTY_STOPLIST: frozenset[str] = frozenset({
    "видеосообщение", "голосовое", "фото", "кружочек", "ссылка", "стикер"})

# F5 (ADR-1018-5 D3): значение среза importance для мета-фактов — 1 (не 2, не 0).
# Гарантированно ниже гейтов Сна (importance_sum_threshold 8/12) и внизу
# RAG-ранга; факты СОХРАНЯЮТСЯ (не удаляются) — для статистики/узких шуток.
METAFACT_PENALTY_IMPORTANCE = 1

# Срез пунктуации/пробелов по краям токена (внутренние дефисы/пробелы — часть
# составного имени и сохраняются).
_EDGE_PUNCT_RE = re.compile(r"^[\s\W_]+|[\s\W_]+$", re.UNICODE)


def normalize_token(value) -> str:
    """Канон-форма токена для сравнения со STOP_LIST (fail-safe на None)."""
    if value is None:
        return ""
    text = str(value).strip().casefold().replace("ё", "е")
    return _EDGE_PUNCT_RE.sub("", text)


def is_center_stopword(value) -> bool:
    """True, если токен не имеет права быть ЦЕНТРОМ кластера (STOP_LIST центров)."""
    return normalize_token(value) in GRAPH_CENTER_STOPLIST


def is_metafact_stopword(value) -> bool:
    """True, если токен — мета-факт-формат (penalty-список F5, importance→min)."""
    return normalize_token(value) in METAFACT_PENALTY_STOPLIST
