"""ASAP 4.2 D1 (AM-1; spec §1) — self-validating source anchors +
``SourceAnchorMap``.

Проблема (BL-1/BL-2): LLM обязана перепечатывать длинные TG ``message_id``;
одна опечатка/выдуманный id валит весь L1/L2. Решение — короткие
self-validating anchors, которые создаёт **только код** поверх immutable
``SummarySourceWindow``; LLM anchor'ы использует, но не изобретает.

Формат anchor (§1): ``m`` + 4-char base36 ordinal (0-padded, ``0-9A-Z``) +
``-`` + 2-char base36 checksum, напр. ``m00BD-K7``.
  * ordinal — 0-based индекс сообщения в ``SummarySourceWindow.messages``;
  * checksum = ``base36(sha256(run_fingerprint + ":" + real_message_id + ":"
    + ordinal)[:8] % 36**2)``;
  * ``run_fingerprint`` = короткий хэш ``(run_id, chat_id, window_from,
    window_to)``;
  * ``real_message_id`` = TG ``message_id``; при отсутствии — stable ``db_id``
    окна.

Инварианты (§1, R8-A-002):
  1. mapping создаёт только код; LLM anchor'ы не изобретает;
  2. immutable на время run (frozen, строится один раз из immutable окна);
  3. биекция: один anchor ↔ ровно один source message;
  4. checksum валидируется кодом: parse → ordinal → реальный id из окна →
     пересчёт checksum → сравнение;
  5. битый anchor не может тихо стать другим валидным source (checksum +
     ordinal не совпадут при опечатке вида ``m0012``→``m0021``);
  6. после validation код переводит anchors обратно в реальные IDs;
  7. mapping не попадает в публичный текст (R17).

Collision handling: ordinal уникален ⇒ полные строки уникальны; build
**asserts** ``len(anchor→msg) == len(messages)`` и отсутствие дублей; при
нарушении — fail-open (``build_anchor_map`` → ``None``; anchor считается
unknown, local repair).

Kill-switches (env-only, default ON; OFF = прежний контур 2.58.47):
``SUMMARY_SOURCE_ANCHORS_ENABLED``, ``SUMMARY_L1_ANCHOR_REPAIR_ENABLED``,
``SUMMARY_L2_EVIDENCE_REPAIR_ENABLED``, ``SUMMARY_L2_TARGETED_REVISION_ENABLED``.
Резолв per-call, никогда не бросает.

Модуль **чистый** (0 LLM/0 БД/0 сети/0 системных часов), детерминирован.
"""
from __future__ import annotations

import dataclasses
import hashlib
import logging
import re
from typing import Iterable

from config.settings import settings

logger = logging.getLogger(__name__)

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ORDINAL_WIDTH = 4
CHECKSUM_WIDTH = 2
ORDINAL_MOD = 36 ** ORDINAL_WIDTH          # 1_679_616
CHECKSUM_MOD = 36 ** CHECKSUM_WIDTH        # 1_296

ANCHOR_RE = re.compile(r"^m([0-9A-Z]{4})-([0-9A-Z]{2})$")

# R17-safe reason-коды валидации anchor (числа/коды, без контента).
ANCHOR_OK = "ok"
REASON_ANCHOR_BAD_FORMAT = "anchor_bad_format"
REASON_ANCHOR_UNKNOWN = "anchor_unknown"
REASON_ANCHOR_CHECKSUM_MISMATCH = "anchor_checksum_mismatch"
REASON_ANCHOR_MAP_UNAVAILABLE = "anchor_map_unavailable"


# ── Kill-switches (env-only, per-call; никогда не бросают) ─────────────────

def _flag(name: str, default: bool = True) -> bool:
    try:
        return bool(getattr(settings, name, default))
    except Exception:      # pragma: no cover - защитная ветка
        return default


def anchors_enabled() -> bool:
    """``SUMMARY_SOURCE_ANCHORS_ENABLED`` (default ON)."""
    return _flag("SUMMARY_SOURCE_ANCHORS_ENABLED", True)


def l1_anchor_repair_enabled() -> bool:
    """``SUMMARY_L1_ANCHOR_REPAIR_ENABLED`` (default ON)."""
    return _flag("SUMMARY_L1_ANCHOR_REPAIR_ENABLED", True)


def l2_evidence_repair_enabled() -> bool:
    """``SUMMARY_L2_EVIDENCE_REPAIR_ENABLED`` (default ON)."""
    return _flag("SUMMARY_L2_EVIDENCE_REPAIR_ENABLED", True)


def l2_targeted_revision_enabled() -> bool:
    """``SUMMARY_L2_TARGETED_REVISION_ENABLED`` (default ON)."""
    return _flag("SUMMARY_L2_TARGETED_REVISION_ENABLED", True)


# ── base36 helpers ─────────────────────────────────────────────────────────

def _base36(value: int, width: int) -> str:
    """Кодировать неотрицательный int в base36 фиксированной ширины
    (0-padded, uppercase). Значение вне ширины → ``ValueError``."""
    value = int(value)
    if value < 0:
        raise ValueError("base36: negative value")
    digits: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        digits.append(ALPHABET[rem])
    if not digits:
        digits = ["0"]
    text = "".join(reversed(digits))
    if len(text) > width:
        raise ValueError("base36: value exceeds width")
    return text.rjust(width, "0")


def _from_base36(text: str) -> int | None:
    """Декодировать base36-строку (uppercase); мусор → ``None``."""
    if not isinstance(text, str) or not text:
        return None
    value = 0
    for char in text:
        index = ALPHABET.find(char)
        if index < 0:
            return None
        value = value * 36 + index
    return value


def run_fingerprint(run_id, chat_id, window_from, window_to,
                    *, length: int = 16) -> str:
    """Короткий детерминированный fingerprint run'а (§1)."""
    material = f"{run_id}|{chat_id}|{window_from}|{window_to}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:max(4, length)]


def anchor_checksum(fingerprint: str, real_message_id, ordinal: int) -> str:
    """2-char base36 checksum (§1)."""
    material = f"{fingerprint}:{real_message_id}:{ordinal}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return _base36(int(digest[:8], 16) % CHECKSUM_MOD, CHECKSUM_WIDTH)


def make_anchor(ordinal: int, real_message_id, fingerprint: str) -> str:
    """Собрать anchor ``m<ordinal4>-<checksum2>`` (§1)."""
    return (f"m{_base36(ordinal, ORDINAL_WIDTH)}-"
            f"{anchor_checksum(fingerprint, real_message_id, ordinal)}")


def normalize_anchor(value) -> str | None:
    """Нормализовать anchor-токен: strip; префикс ``m`` — lowercase, тело —
    uppercase; иначе ``None``. Не проверяет checksum (это делает map)."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if not text or text[0] != "M":
        return None
    text = "m" + text[1:]
    if not ANCHOR_RE.match(text):
        return None
    return text


# ── Результат валидации одного anchor ──────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class AnchorCheck:
    """R17-safe результат проверки anchor (коды/числа, без контента)."""

    ok: bool
    reason: str
    anchor: str = ""
    ordinal: int | None = None
    real_message_id: int | None = None

    def as_log_fields(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class AnchorEntry:
    anchor: str
    ordinal: int
    real_message_id: int


@dataclasses.dataclass(frozen=True)
class SourceAnchorMap:
    """Immutable per-run bijection anchor ↔ real message id (R8-A-002)."""

    run_fingerprint: str
    entries: tuple
    source_count: int
    degraded: bool = False

    def __post_init__(self) -> None:
        by_anchor: dict = {}
        by_real: dict = {}
        for entry in self.entries:
            by_anchor[entry.anchor] = entry
            by_real.setdefault(entry.real_message_id, entry.anchor)
        object.__setattr__(self, "_by_anchor", by_anchor)
        object.__setattr__(self, "_by_real", by_real)

    # ── доступ ─────────────────────────────────────────────────────────────

    @property
    def source_anchors(self) -> tuple:
        """Anchors в порядке ordinal (канонический source-порядок)."""
        return tuple(entry.anchor for entry in
                     sorted(self.entries, key=lambda e: e.ordinal))

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, anchor) -> bool:
        normalized = normalize_anchor(anchor)
        return normalized is not None and normalized in self._by_anchor

    def entry(self, anchor) -> AnchorEntry | None:
        normalized = normalize_anchor(anchor)
        if normalized is None:
            return None
        return self._by_anchor.get(normalized)

    def real_id(self, anchor) -> int | None:
        entry = self.entry(anchor)
        return entry.real_message_id if entry is not None else None

    def anchor_for(self, real_message_id) -> str | None:
        return self._by_real.get(real_message_id)

    # ── валидация (parse → ordinal → real id → re-checksum → compare) ───────

    def validate(self, anchor) -> AnchorCheck:
        """Полная проверка anchor (§1 инвариант 4/5)."""
        normalized = normalize_anchor(anchor)
        if normalized is None:
            return AnchorCheck(ok=False, reason=REASON_ANCHOR_BAD_FORMAT,
                               anchor=str(anchor or "")[:32])
        entry = self._by_anchor.get(normalized)
        if entry is None:
            return AnchorCheck(ok=False, reason=REASON_ANCHOR_UNKNOWN,
                               anchor=normalized)
        expected = anchor_checksum(self.run_fingerprint,
                                   entry.real_message_id, entry.ordinal)
        if f"m{_base36(entry.ordinal, ORDINAL_WIDTH)}-{expected}" != normalized:
            return AnchorCheck(ok=False,
                               reason=REASON_ANCHOR_CHECKSUM_MISMATCH,
                               anchor=normalized)
        return AnchorCheck(ok=True, reason=ANCHOR_OK, anchor=normalized,
                           ordinal=entry.ordinal,
                           real_message_id=entry.real_message_id)

    def is_valid(self, anchor) -> bool:
        return self.validate(anchor).ok

    def resolve(self, anchor) -> int | None:
        check = self.validate(anchor)
        return check.real_message_id if check.ok else None

    def to_real_ids(self, anchors: Iterable) -> list:
        """Валидные anchors → real IDs (порядок входа, dedup; R8-A-002 №6)."""
        out: list = []
        for anchor in anchors or ():
            real = self.resolve(anchor)
            if real is not None and real not in out:
                out.append(real)
        return out

    def partition(self, anchors: Iterable) -> tuple:
        """Разделить вход на ``(valid_real_ids, invalid_anchors)``.

        R17-safe: invalid-список содержит только исходные токены (≤32 симв.),
        без контента. Дубли real id снимаются."""
        valid: list = []
        invalid: list = []
        for anchor in anchors or ():
            check = self.validate(anchor)
            if check.ok:
                if check.real_message_id not in valid:
                    valid.append(check.real_message_id)
            else:
                invalid.append(check.anchor[:32])
        return valid, invalid

    def check_anchor(self, anchor) -> AnchorCheck:
        return self.validate(anchor)


def _real_message_id(message) -> int | None:
    """``TG message_id`` при наличии; иначе stable ``db_id`` окна (§1)."""
    for key in ("message_id", "db_id"):
        value = message.get(key) if isinstance(message, dict) else None
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def anchor_space_item(item, anchor_map: SourceAnchorMap) -> dict:
    """§92-элемент → anchor-space: raw ``message_id``/``reply_to_id``
    заменяются на ``source_anchor``/``reply_to_anchor`` (R17: LLM не видит
    реальные id). Прочие поля сохраняются. Не бросает."""
    clone = dict(item)
    real = clone.get("message_id")
    if real is not None:
        anchor = anchor_map.anchor_for(real) if anchor_map is not None else None
        if anchor is not None:
            clone["source_anchor"] = anchor
        clone.pop("message_id", None)
    reply = clone.get("reply_to_id")
    if reply is not None:
        parent = anchor_map.anchor_for(reply) \
            if anchor_map is not None else None
        if parent is not None:
            clone["reply_to_anchor"] = parent
        clone.pop("reply_to_id", None)
    return clone


def build_anchor_map(window, *, run_id=None, chat_id=None) -> SourceAnchorMap | None:
    """Собрать ``SourceAnchorMap`` поверх immutable окна (§1).

    ``window`` — ``SummarySourceWindow`` или совместимый объект с
    ``run_id/chat_id/window_from/window_to/messages``. Возвращает ``None``
    (fail-open), если окно/сообщения недоступны ИЛИ нарушен инвариант
    биекции (дубль anchor, число entries ≠ числу сообщений) — тогда
    вызывающий считает anchor'ы unknown и идёт в local repair. Никогда не
    бросает."""
    try:
        if window is None:
            return None
        messages = list(getattr(window, "messages", ()) or ())
        if not messages:
            return None
        rid = run_id if run_id is not None else getattr(window, "run_id", "")
        cid = chat_id if chat_id is not None else getattr(window, "chat_id", 0)
        fingerprint = run_fingerprint(
            rid, cid, getattr(window, "window_from", None),
            getattr(window, "window_to", None))
        entries: list[AnchorEntry] = []
        seen_anchors: set = set()
        for ordinal, message in enumerate(messages):
            real = _real_message_id(message)
            if real is None:
                logger.warning(
                    "summary_source_anchors: message without id | ordinal=%d",
                    ordinal)
                return None
            anchor = make_anchor(ordinal, real, fingerprint)
            if anchor in seen_anchors:
                logger.warning(
                    "summary_source_anchors: anchor collision | ordinal=%d",
                    ordinal)
                return None
            seen_anchors.add(anchor)
            entries.append(AnchorEntry(anchor=anchor, ordinal=ordinal,
                                       real_message_id=real))
        # Build-assert (§1): биекция + число.
        if len(entries) != len(messages):
            logger.warning("summary_source_anchors: build assert failed "
                           "(entries=%d messages=%d)",
                           len(entries), len(messages))
            return None
        if len({e.real_message_id for e in entries}) != len(entries):
            logger.warning("summary_source_anchors: duplicate real ids in window")
            return None
        return SourceAnchorMap(run_fingerprint=fingerprint,
                               entries=tuple(entries),
                               source_count=len(messages))
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("summary_source_anchors: build failed", exc_info=True)
        return None


__all__ = [
    "ALPHABET", "ORDINAL_WIDTH", "CHECKSUM_WIDTH", "ANCHOR_RE",
    "ANCHOR_OK", "REASON_ANCHOR_BAD_FORMAT", "REASON_ANCHOR_UNKNOWN",
    "REASON_ANCHOR_CHECKSUM_MISMATCH", "REASON_ANCHOR_MAP_UNAVAILABLE",
    "AnchorCheck", "AnchorEntry", "SourceAnchorMap",
    "anchors_enabled", "l1_anchor_repair_enabled",
    "l2_evidence_repair_enabled", "l2_targeted_revision_enabled",
    "run_fingerprint", "anchor_checksum", "make_anchor", "normalize_anchor",
    "anchor_space_item",
    "build_anchor_map",
]
