"""ASAP 4.1 волна 2 (эпик `asap-4-1-durable-whole-window-summary`) —
CoverageLedger строгого покрытия SourceWindow в режиме CAPACITY_OVERFLOW
(T-4606, spec §1 A.3; ADR-1028-8 D2.4).

Чистый модуль (0 LLM, 0 БД, 0 сети/часов): детерминирован, вход не
мутируется, двойной прогон байт-идентичен. Сообщения окна никогда не
содержатся внутри Ledger — только их stable ID (R17).

Поля Ledger (ADR-1028-8 D2.4):
  * ``source_message_ids``   — полный набор stable id окна SourceWindow;
  * ``segment_assignments``  — фрагменты (segment_id → отсортированный
                               набор id его строк окна);
  * ``processed_ids``        — id, реально присутствующие в успешных
                               L1-результатах (payload-attributed);
  * ``fallback_ids``         — id фрагмента, который остался непокрытым
                               даже после restore-попытки (честный
                               degraded, не «success»);
  * ``missing_ids``          — вычисляемая непокрытая часть окна
                               (инвариант сводится к 0 перед Writer).

Инвариант XOR-покрытия (ADR-1028-8 D2.4): каждое сообщение окна входит
ровно в ≥1 сегмент (union assignments == source; overlap-дубликат соседних
сегментов не считается потерей — дедуп по stable ID, семантика
существующего merge §121). Перед Writer ``coverage == 100 %``; иначе —
явно честный degraded: восстановление сегмента (re-run только проблемного)
или честный ``degraded``-исход (см. требование spec §1 A.3).

Kill-switch ``SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED`` резолвится в
вызывающем контуре (summary_l1_clusterizer); здесь модуль чистый и флаг
не читает.

Δ DDL = 0; R17: наружу только counts/percent/статусы (без текстов/секретов).
"""
from __future__ import annotations

from dataclasses import dataclass, field


def stable_message_id(row) -> int | None:
    """Stable ID сообщения окна (первоклассная поверхность Ledger).

    Приоритет: TG ``tg_message_id`` (§95-id-space, стабильный во времени);
    fallback — DB ``id``. ``None`` → элемент вне учёта (вызывающий
    контур сам решает; строки SourceWindow всегда имеют целый id)."""
    for key in ("tg_message_id", "id"):
        try:
            value = row[key]
        except (KeyError, IndexError, TypeError):
            value = getattr(row, key, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _int_set(values) -> set:
    result: set = set()
    try:
        for value in (values or ()):
            if value is None:
                continue
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                continue
    except TypeError:                        # pragma: no cover - защитная ветка
        return set()
    return result


@dataclass
class CoverageLedger:
    """Ledger покрытия: source/segments/processed/fallback/missing (D2.4)."""

    source_message_ids: tuple
    segment_assignments: dict = field(default_factory=dict)
    processed_ids: tuple = ()
    fallback_ids: tuple = ()
    missing_ids: tuple = ()

    def __post_init__(self) -> None:
        self.source_message_ids = tuple(sorted(_int_set(self.source_message_ids)))

    # ── builders (цепочечный стиль; мутируют только собственные поля) ──────

    def register_segment(self, segment_id, message_ids) -> "CoverageLedger":
        """Зарегистрировать фрагмент (segment_id → id его строк окна).

        Дедуп по stable ID внутри фрагмента; id вне source (мусор/чужое id-
        пространство) отбрасываются: union assignments обязан покрыть
        source ровно (XOR-инвариант), посторонние id инвариант ломали
        честно — поэтому отсекаются на входе при регистрации."""
        ids = _int_set(message_ids) & set(self.source_message_ids)
        self.segment_assignments[str(segment_id)] = tuple(sorted(ids))
        return self

    def mark_processed(self, message_ids) -> "CoverageLedger":
        """Отметить id, реально вошедшие в успешный L1-результат
        (payload-attributed; вызывается на каждый успешный сегмент)."""
        known = _int_set(self.processed_ids) | _int_set(message_ids)
        self.processed_ids = tuple(sorted(known & set(self.source_message_ids)))
        return self

    def mark_fallback(self, message_ids) -> "CoverageLedger":
        """Отметить id фрагмента, который остался непокрытым после
        restore (осознанная потеря → честный degraded, не «success»)."""
        known = _int_set(self.fallback_ids) | _int_set(message_ids)
        # processed доминирует: пересечение исключаем из fallback.
        self.fallback_ids = tuple(
            sorted(known - _int_set(self.processed_ids)))
        self._recompute_missing()
        return self

    # ── вычисления (инварианты) ──────────────────────────────────────────────

    def _recompute_missing(self) -> None:
        covered = _int_set(self.processed_ids) | _int_set(self.fallback_ids)
        self.missing_ids = tuple(
            sorted(set(self.source_message_ids) - covered))

    def verify(self) -> dict:
        """Снапшот инвариантов (R17-safe counts; вызывается в любой момент)."""
        source = set(self.source_message_ids)
        assigned: set = set()
        for ids in self.segment_assignments.values():
            assigned |= _int_set(ids)
        self._recompute_missing()
        processed = _int_set(self.processed_ids)
        fallback = _int_set(self.fallback_ids)
        covered = processed | fallback
        total = len(source)
        return {
            "segments": len(self.segment_assignments),
            "source": total,
            "assigned": len(assigned),
            "processed": len(processed),
            "fallback": len(fallback),
            "missing": len(self.missing_ids),
            "coverage_percent": round(100.0 * len(covered) / total, 4)
            if total else 100.0,
            # XOR-аргументация lossless: union assignments == source.
            "assignment_lossless": assigned == source,
        }

    def require_full_coverage(self) -> None:
        """Fail-closed gate перед Writer (spec §1 A.3: coverage == 100 %).

        Поднимает ValueError — вызывающий контур обязан перейти в честный
        degraded path (не «success»)."""
        status = self.verify()
        if status["missing"] > 0 or not status["assignment_lossless"]:
            raise ValueError(
                "coverage ledger: incomplete coverage "
                "(processed=%d fallback=%d missing=%d lossless=%s)"
                % (status["processed"], status["fallback"],
                   status["missing"], status["assignment_lossless"]))


def snapshot_dict(ledger: CoverageLedger | None) -> dict | None:
    """R17-safe снапшот Ledger для событий/лога (только counts/статусы)."""
    if ledger is None:
        return None
    return ledger.verify()


__all__ = [
    "CoverageLedger", "stable_message_id", "snapshot_dict",
]
