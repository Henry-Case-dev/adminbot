"""SOUL-1 / W3 — Speech Style Policy: типизированные правила формы письма.

Нормативная база (обязательные источники слайса):
  * ``source-current-task.md`` §17-§18 (SOUL-16.1-16.4: типы правил и модель
    данных, контракт кавычек, контракт завершающей точки, исполнение/
    приоритеты/стоимость/изоляция) и §6 (SOUL-05: ``one_word`` против
    ``micro``, валидатор, цепочка до Telegram payload), §10 (SOUL-09:
    антизалипание наблюдаемое и пропорциональное);
  * ``source-architectural-clarification.md`` §3.5 (Speech Style Policy —
    самостоятельный управляемый слой, простые строгие ограничения проверяются
    детерминированно, URL/цитаты/код/машинные данные защищены, применяется ко
    всем подходящим авторским выходам, включая fallback);
  * ``design-source-of-truth.md`` §2.2 (документ ``style.policy`` на scope:
    ``revision``/``presets_applied``/``rules``/``soft_instructions``/``history``;
    правило: id, kind, params, strictness, scope, enabled, owner, revision,
    created_at, updated_at, reason, conflict_strategy, content_type_exemptions,
    origin) и §3 п.1-3 (существующие ``bot_settings``/``ConfigCache``/
    ``chat_params``/RBAC — второй config service НЕ создаётся);
  * ``design-composer-contract.md`` §3 слой 10 (короткий ``style_policy_hint``,
    НЕ вся база правил) и §6 (единый пост-проход: invariants → extent check →
    style validation/targeted repair → Telegram serialization → outbound
    validation; владелец прохода — этот модуль; идемпотентность).

Границы слайса W3: правила ФОРМЫ финального пользовательского текста и их
исполнение. Personality Core/композер — W2, UI «Стиль письма» — W6, отбор
примеров/фидбек — W4. Речь-каноны (``prompts.*``) здесь не правятся.

Инварианты:
  1. Ни одна ветка не бросает: недоступный/битый документ → пустая политика +
     диагностируемая причина (fail-open, паритет остальных слоёв).
  2. Ноль LLM-вызовов на нарушение: проверка и правка детерминированные.
     Смысловая переформулировка — не более ОДНОГО bounded repair на класс
     контента и только по явно переданному вызывающим callback (SOUL-16.4.5).
  3. Защищённые сегменты (URL, код, JSON, дословная цитата, версия,
     многоточие, разметка/Telegram entities) не повреждаются никогда: байты
     payload сохраняются, нарушение показывается как ``exempted``/``conflict``,
     а не как успешный ``pass`` (SOUL-16.2.3/16.3.3).
  4. Идемпотентность: повторный проход на нормализованном тексте = no-op
     (``repaired=0``), кроме случая включения правила между проходами.
  5. R17: в логи/события уходят только коды, числа и хеши, без текста ответа.

TEST-LIFECYCLE: CONTRACT owner=SOUL-16.1.1/16.2/16.3/16.4 + SOUL-05.2/05.5 +
SOUL-09.1/09.2 (soul-1, слайс W3)
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

# ── Документ (design-source-of-truth §2.2) ──────────────────────────────────

DOC_KEY = "style.policy"
DOC_CATEGORY = "content"
DOC_VERSION = 1
HISTORY_MAX = 20
SOFT_INSTRUCTIONS_MAX = 12
RULES_MAX = 64

#: Закрытый набор kind (W3 фиксирует значения; расширение = правка + тест).
RULE_KINDS = ("trailing_period", "quotation_marks", "emoji", "line_breaks",
              "one_word", "forbidden_chars")
STRICTNESS = ("hard", "soft")
#: ``scope`` правила = контекстный пакет (SOUL-16.1.3): обычная речь/инициатива/
#: редакционная публикация/код-и-структурированный вывод. ``chat`` — правило,
#: созданное на уровне чата (по смыслу обычная речь этого чата).
RULE_SCOPES = ("global", "chat", "initiative", "editorial",
               "code_or_structured")
CONTEXT_PACKS = ("regular", "initiative", "editorial", "code_or_structured")
#: Контексты, к которым правила формы не применяются вовсе (SOUL-16.4.4:
#: машинные стадии — SQL/JSON-планы/память/поисковые запросы).
MACHINE_CONTEXTS = ("machine", "machine_json", "internal")
CONFLICT_STRATEGIES = ("exempt_protected", "deny_incompatible", "prefer_task")
DEFAULT_CONFLICT_STRATEGY = "exempt_protected"
DEFAULT_EXEMPTIONS = ("verbatim_quote", "url", "code", "json",
                      "markdown_markup", "telegram_entity", "version_literal",
                      "ellipsis")
SPAN_KINDS = ("plain", "verbatim_quote", "url", "code", "json",
              "markdown_markup", "telegram_entity", "version_literal",
              "ellipsis")
ORIGINS = ("owner", "preset", "migration", "experience_proposal",
           "factory_default")

#: Исходы (закрытый набор, SOUL-16.1.1 + design-composer-contract §5).
STATUS_PASS = "pass"
STATUS_REPAIRED = "repaired"
STATUS_EXEMPTED = "exempted"
STATUS_CONFLICT = "conflict"
STATUS_FAILED = "failed"
STATUS_DENIED = "denied"
STATUS_NA = "not_applicable"
STATUSES = (STATUS_PASS, STATUS_REPAIRED, STATUS_EXEMPTED, STATUS_CONFLICT,
            STATUS_FAILED, STATUS_DENIED, STATUS_NA)
#: Исходы, при которых НЕЛЬЗЯ объявлять ``styled=true`` (SOUL-15.7).
BLOCKING_STATUSES = frozenset({STATUS_CONFLICT, STATUS_FAILED, STATUS_DENIED})

#: Приоритет (SOUL-16.4.2): безопасность/факты/каналы > дословность и явная
#: задача пользователя > owner-правила обычной речи > chat-scoped правила >
#: мягкие навыки Experience > генеративные предпочтения L1/Writer.
PRECEDENCE = (
    "safety_facts_channel",
    "verbatim_and_explicit_task",
    "owner_hard_ordinary_speech",
    "chat_scoped_rules",
    "experience_soft_habits",
    "l1_writer_preferences",
)

#: Каталог kind для UI/Inspector (W6): назначение простыми словами.
RULE_KIND_SPECS: dict[str, dict] = {
    "trailing_period": {
        "title_ru": "Точка в конце сообщения",
        "purpose": "Убирать завершающую точку в обычной речи (не внутри "
                   "URL/версий/многоточий/кода/разметки).",
        "params": {"ellipsis": "keep|strip"},
        "hard_effect": "точка снимается детерминированно на финальном тексте",
        "soft_effect": "инструкция Writer, без обещания 100% соблюдения",
    },
    "quotation_marks": {
        "title_ru": "Кавычки",
        "purpose": "Запрет графических кавычек в обычной речи с защитой "
                   "апострофов, литералов, JSON и разметки.",
        "params": {"classes": ["«»", "„“", "“”", "\"", "'"],
                   "detect_apostrophe": True},
        "hard_effect": "безопасные простые случаи правятся; смысловые — "
                       "честный conflict, а не удаление кавычек вслепую",
        "soft_effect": "просьба переформулировать без графических кавычек",
    },
    "emoji": {
        "title_ru": "Эмодзи",
        "purpose": "Запрет эмодзи в обычной речи (защищённые сегменты и "
                   "Telegram-эмодзи-сущности не трогаются).",
        "params": {},
        "hard_effect": "эмодзи снимаются детерминированно",
        "soft_effect": "инструкция Writer",
    },
    "line_breaks": {
        "title_ru": "Переносы строк",
        "purpose": "Ограничение числа переносов строк в сообщении.",
        "params": {"max_breaks": 2},
        "hard_effect": "схлопываются только пустые прогоны; превышение "
                       "одиночными переносами показывается как conflict",
        "soft_effect": "инструкция Writer",
    },
    "one_word": {
        "title_ru": "Ровно одно слово",
        "purpose": "Строгий режим ответа одним лексическим словом "
                   "(one_word, отдельно от micro).",
        "params": {"allow_trailing_punct": True},
        "hard_effect": "финальный валидатор: ровно одно лексическое слово, "
                       "одна минимальная локальная правка",
        "soft_effect": "не применяется (kind всегда строгий по смыслу)",
    },
    "forbidden_chars": {
        "title_ru": "Запрещённые символы",
        "purpose": "Список символов, которые владелец не хочет видеть в "
                   "обычной речи.",
        "params": {"chars": ["…"]},
        "hard_effect": "символы снимаются в обычном тексте",
        "soft_effect": "инструкция Writer",
    },
}

#: Шаблоны (presets, SOUL-16.1.5) — стартовые удобства, не личности.
PRESET_SPECS: dict[str, dict] = {
    "regular_chat": {
        "title_ru": "Обычная переписка",
        "description": "Ничего не запрещает: только мягкая привычка живой речи.",
        "soft_instructions": ["Пиши естественными фразами, без канцелярита."],
        "rules": [],
    },
    "no_quotes": {
        "title_ru": "Без кавычек",
        "description": "В обычной речи без графических кавычек; дословность, "
                       "код и ссылки не переписываются.",
        "soft_instructions": [],
        "rules": [{"id": "quotation_marks.hard.no_graphic",
                   "kind": "quotation_marks",
                   "strictness": "hard",
                   "params": {"classes": ["«»", "„“", "“”", "\"", "'"],
                              "detect_apostrophe": True},
                   "conflict_strategy": "exempt_protected",
                   "reason": "владелец: без кавычек в обычной речи"}],
    },
    "no_trailing_period": {
        "title_ru": "Без точек на конце",
        "description": "Убирать завершающую точку в обычной речи.",
        "soft_instructions": [],
        "rules": [{"id": "trailing_period.hard.strip",
                   "kind": "trailing_period",
                   "strictness": "hard",
                   "params": {"ellipsis": "keep"},
                   "conflict_strategy": "exempt_protected",
                   "reason": "владелец: без точки в конце сообщения"}],
    },
    "no_emoji": {
        "title_ru": "Без эмодзи",
        "description": "Эмодзи в обычной речи не используются.",
        "soft_instructions": [],
        "rules": [{"id": "emoji.hard.off", "kind": "emoji",
                   "strictness": "hard", "params": {},
                   "conflict_strategy": "exempt_protected",
                   "reason": "владелец: без эмодзи"}],
    },
    "casual_concise": {
        "title_ru": "Разговорный и лаконичный",
        "description": "Мягкие привычки: меньше перечислений, живые фразы, "
                       "без лишних тире.",
        "soft_instructions": ["Меньше перечислений, больше живых фраз.",
                              "Не злоупотребляй тире и вводными словами."],
        "rules": [],
    },
}
PRESET_NAMES = tuple(PRESET_SPECS)

#: Дефолтные исключения по типу содержимого для hard-правил (SOUL-16.2.3).
_UNSET = object()


def _sha12(text: Any) -> str:
    try:
        payload = text if isinstance(text, str) else json.dumps(
            text, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:      # pragma: no cover - хеш не роняет проход
        payload = str(text)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _tokens_est(text: str) -> int:
    """Оценка токенов тем же оценщиком, что в композере (fallback len/4)."""
    try:
        from services.prompt_composer import estimate_tokens
        return int(estimate_tokens(text))
    except Exception:
        return max(1, len(str(text or "")) // 4)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Модель данных
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StyleRule:
    """Одна типизированная запись правил (SOUL-16.1.4)."""

    id: str
    kind: str
    strictness: str = "hard"
    scope: str = "global"
    params: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    owner: Any = None
    revision: int = 1
    created_at: str = ""
    updated_at: str = ""
    reason: str = ""
    conflict_strategy: str = DEFAULT_CONFLICT_STRATEGY
    content_type_exemptions: tuple[str, ...] = DEFAULT_EXEMPTIONS
    origin: str = "owner"

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind,
                "strictness": self.strictness, "scope": self.scope,
                "params": dict(self.params or {}), "enabled": self.enabled,
                "owner": self.owner, "revision": self.revision,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "reason": self.reason,
                "conflict_strategy": self.conflict_strategy,
                "content_type_exemptions": list(self.content_type_exemptions),
                "origin": self.origin}


@dataclass(frozen=True)
class SoftInstruction:
    """Мягкая редакционная привычка (bounded-инструкция Writer)."""

    id: str
    text: str
    scope: str = "global"
    enabled: bool = True
    owner: Any = None
    revision: int = 1

    def as_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "scope": self.scope,
                "enabled": self.enabled, "owner": self.owner,
                "revision": self.revision}


@dataclass(frozen=True)
class ResolvedRule:
    """Правило в эффективной политике: + слой-источник значения."""

    rule: StyleRule
    source: str = "global"        # global | chat | preset | inherited

    @property
    def id(self) -> str:
        return self.rule.id

    @property
    def kind(self) -> str:
        return self.rule.kind

    @property
    def strictness(self) -> str:
        return self.rule.strictness

    def as_dict(self) -> dict:
        row = self.rule.as_dict()
        row["source"] = self.source
        return row


@dataclass(frozen=True)
class EffectiveStylePolicy:
    """Эффективная политика для конкретного scope + типа выхода."""

    rules: tuple[ResolvedRule, ...] = ()
    soft_instructions: tuple[SoftInstruction, ...] = ()
    context: str = "regular"
    source: str = "default"        # global | chat | default
    revision: str = ""
    presets_applied: tuple[str, ...] = ()
    skip_reason: str = ""
    conflicts: tuple[str, ...] = ()
    extent: str = ""
    hint: str = ""
    hint_tokens: int = 0

    @property
    def enabled(self) -> bool:
        return bool(self.rules or self.soft_instructions)

    @property
    def hard_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({r.kind for r in self.rules
                             if r.strictness == "hard" and r.rule.enabled}))

    @property
    def soft_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({r.kind for r in self.rules
                             if r.strictness == "soft" and r.rule.enabled}))

    @property
    def line_breaks_max(self) -> int | None:
        value = None
        for resolved in self.rules:
            if resolved.kind != "line_breaks" or not resolved.rule.enabled:
                continue
            try:
                candidate = int((resolved.rule.params or {}).get(
                    "max_breaks", 2))
            except (TypeError, ValueError):
                candidate = 2
            value = candidate if value is None else min(value, candidate)
        return value

    def rules_for_kind(self, kind: str) -> tuple[ResolvedRule, ...]:
        return tuple(r for r in self.rules
                     if r.kind == kind and r.rule.enabled)

    def as_dict(self) -> dict:
        """R17-safe вид для Inspector/UI (W6) и тестов."""
        return {
            "context": self.context, "source": self.source,
            "revision": self.revision, "extent": self.extent,
            "presets_applied": list(self.presets_applied),
            "skip_reason": self.skip_reason,
            "conflicts": list(self.conflicts),
            "rules": [r.as_dict() for r in self.rules],
            "soft_instructions": [s.as_dict() for s in self.soft_instructions],
            "hard_kinds": list(self.hard_kinds),
            "soft_kinds": list(self.soft_kinds),
            "hint_chars": len(self.hint), "hint_tokens": self.hint_tokens,
        }


@dataclass(frozen=True)
class RuleOutcome:
    """Объяснимый исход одного правила (pass/repaired/exempted/conflict/...)."""

    rule_id: str
    kind: str
    strictness: str = "hard"
    status: str = STATUS_PASS
    reason: str = ""
    source: str = ""
    detail: tuple[tuple[str, Any], ...] = ()

    def as_dict(self) -> dict:
        return {"rule_id": self.rule_id, "kind": self.kind,
                "strictness": self.strictness, "status": self.status,
                "reason": self.reason, "source": self.source,
                "detail": dict(self.detail)}


@dataclass
class StyleOutcome:
    """Результат единого прохода нормализации (до и после сериализации)."""

    text: str = ""
    context: str = "regular"
    policy_revision: str = ""
    policy_source: str = "default"
    applied: bool = False
    skip_reason: str = ""
    extent: Any = None                       # response_extent.ExtentCheck | None
    results: list[RuleOutcome] = field(default_factory=list)
    repetition: tuple[dict, ...] = ()
    notes: tuple[str, ...] = ()
    payload: bool = False
    payload_status: str = ""
    elapsed_ms: float = 0.0
    repair_used: int = 0
    #: Снимок политики, применённой проходом (для payload-проверки доставки);
    #: в ``as_dict()`` не сериализуется (R17: только коды/ревизия).
    policy: Any = None
    #: План ответа, с которым шёл проход (extent-проверка payload); не
    #: сериализуется.
    plan: Any = None

    @property
    def repaired(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_REPAIRED)

    @property
    def exempted(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_EXEMPTED)

    @property
    def conflicts(self) -> tuple[str, ...]:
        return tuple(r.rule_id for r in self.results
                     if r.status == STATUS_CONFLICT)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(r.rule_id for r in self.results
                     if r.status == STATUS_FAILED)

    @property
    def denied(self) -> bool:
        return any(r.status == STATUS_DENIED for r in self.results)

    @property
    def styled(self) -> bool:
        """``False`` — hard-правило провалено/конфликт/deny (нельзя выдавать
        за успешный pass, SOUL-15.7)."""
        return not any(r.status in BLOCKING_STATUSES for r in self.results
                       if r.strictness == "hard")

    @property
    def extent_status(self) -> str:
        return str(getattr(self.extent, "status", "") or "")

    def status_counts(self) -> dict:
        counts = {status: 0 for status in STATUSES}
        for row in self.results:
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts

    def as_dict(self) -> dict:
        """R17-safe (коды/числа/хеши; текста ответа нет)."""
        return {
            "context": self.context, "applied": self.applied,
            "skip_reason": self.skip_reason,
            "policy_revision": self.policy_revision,
            "policy_source": self.policy_source,
            "styled": self.styled, "denied": self.denied,
            "counts": self.status_counts(),
            "conflicts": list(self.conflicts), "failed": list(self.failed),
            "exempted": self.exempted, "repaired": self.repaired,
            "extent": (self.extent.as_dict() if self.extent is not None
                       else {}),
            "repetition": list(self.repetition),
            "payload": self.payload, "payload_status": self.payload_status,
            "elapsed_ms": round(float(self.elapsed_ms), 3),
            "repair_used": self.repair_used,
            "text_chars": len(self.text), "text_sha12": _sha12(self.text),
            "notes": list(self.notes),
        }


# ═══════════════════════════════════════════════════════════════════════════
# 2. Документ: нормализация, валидация, presets, merge
# ═══════════════════════════════════════════════════════════════════════════

def _as_document(raw: Any) -> dict | None:
    """JSON-документ из ``bot_settings``/``chat_params`` (dict или jsonb-str)."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw.decode("utf-8")
                                if isinstance(raw, (bytes, bytearray)) else raw)
        except Exception:
            return None
        return dict(parsed) if isinstance(parsed, Mapping) else None
    return None


def _text_id(value: Any, fallback: str) -> str:
    candidate = re.sub(r"\s+", "_", str(value or "").strip())[:64]
    return candidate or fallback


def normalize_rule(raw: Any, *, index: int = 0,
                   default_origin: str = "owner") -> tuple[StyleRule | None,
                                                           tuple[str, ...]]:
    """Сырая запись правила → :class:`StyleRule` (или ``None``) + диагностика.

    Никогда не бросает. Неизвестный ``kind``/``strictness``/``scope`` и
    не-словарь → правило отбрасывается с причиной (реестр не «догадывается»).
    """
    issues: list[str] = []
    if not isinstance(raw, Mapping):
        return None, ("rule_not_object",)
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in RULE_KINDS:
        return None, (f"rule_kind_unknown:{kind or 'empty'}",)
    strictness = str(raw.get("strictness") or "hard").strip().lower()
    if strictness not in STRICTNESS:
        issues.append(f"rule_strictness_default:{strictness or 'empty'}")
        strictness = "hard"
    scope = str(raw.get("scope") or "global").strip().lower()
    if scope not in RULE_SCOPES:
        issues.append(f"rule_scope_default:{scope or 'empty'}")
        scope = "global"
    strategy = str(raw.get("conflict_strategy")
                   or DEFAULT_CONFLICT_STRATEGY).strip().lower()
    if strategy not in CONFLICT_STRATEGIES:
        issues.append(f"rule_strategy_default:{strategy or 'empty'}")
        strategy = DEFAULT_CONFLICT_STRATEGY
    params = raw.get("params")
    params = dict(params) if isinstance(params, Mapping) else {}
    exemptions = raw.get("content_type_exemptions")
    if isinstance(exemptions, (list, tuple)):
        exemption_tuple = tuple(str(x) for x in exemptions
                                if str(x) in SPAN_KINDS)
    else:
        exemption_tuple = DEFAULT_EXEMPTIONS
    origin = str(raw.get("origin") or default_origin).strip() or default_origin
    try:
        revision = int(raw.get("revision", 1) or 1)
    except (TypeError, ValueError):
        revision = 1
    rule_id = _text_id(raw.get("id"),
                       f"{kind}.{strictness}.{index}")
    if not str(raw.get("id") or "").strip():
        issues.append("rule_id_generated")
    if not str(raw.get("reason") or "").strip():
        issues.append("rule_reason_absent")
    return StyleRule(
        id=rule_id, kind=kind, strictness=strictness, scope=scope,
        params=params, enabled=bool(raw.get("enabled", True)),
        owner=raw.get("owner"), revision=revision,
        created_at=str(raw.get("created_at") or ""),
        updated_at=str(raw.get("updated_at") or ""),
        reason=str(raw.get("reason") or ""),
        conflict_strategy=strategy,
        content_type_exemptions=exemption_tuple,
        origin=origin), tuple(issues)


def normalize_soft(raw: Any, *, index: int = 0) -> SoftInstruction | None:
    """Сырая мягкая привычка → :class:`SoftInstruction` (или ``None``)."""
    if not isinstance(raw, Mapping):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    scope = str(raw.get("scope") or "global").strip().lower()
    if scope not in RULE_SCOPES:
        scope = "global"
    try:
        revision = int(raw.get("revision", 1) or 1)
    except (TypeError, ValueError):
        revision = 1
    return SoftInstruction(
        id=_text_id(raw.get("id"), f"soft.{index}"), text=text, scope=scope,
        enabled=bool(raw.get("enabled", True)), owner=raw.get("owner"),
        revision=revision)


def validate_document(raw: Any) -> tuple[dict, tuple[str, ...]]:
    """Нормализовать документ ``style.policy`` и вернуть диагностику.

    Возвращает ``(document, issues)``. Неизвестные kind/поля не «протекают» в
    рантайм: правило отбрасывается и причина видна. Никогда не бросает."""
    doc = _as_document(raw)
    if doc is None:
        return {}, ("document_unreadable",) if raw not in (None, _UNSET) \
            else ()
    issues: list[str] = []
    rules: list[StyleRule] = []
    seen: set[str] = set()
    raw_rules = doc.get("rules")
    if isinstance(raw_rules, (list, tuple)):
        for index, item in enumerate(raw_rules[:RULES_MAX]):
            rule, rule_issues = normalize_rule(item, index=index)
            issues.extend(rule_issues)
            if rule is None or rule.id in seen:
                if rule is not None:
                    issues.append(f"rule_duplicate:{rule.id}")
                continue
            seen.add(rule.id)
            rules.append(rule)
        if len(raw_rules) > RULES_MAX:
            issues.append("rules_truncated")
    elif raw_rules is not None:
        issues.append("rules_not_list")
    soft: list[SoftInstruction] = []
    raw_soft = doc.get("soft_instructions")
    if isinstance(raw_soft, (list, tuple)):
        for index, item in enumerate(raw_soft[:SOFT_INSTRUCTIONS_MAX]):
            entry = normalize_soft(item, index=index)
            if entry is not None:
                soft.append(entry)
        if len(raw_soft) > SOFT_INSTRUCTIONS_MAX:
            issues.append("soft_truncated")
    elif raw_soft is not None:
        issues.append("soft_not_list")
    presets = tuple(str(x) for x in (doc.get("presets_applied") or ())
                    if str(x) in PRESET_SPECS)
    if doc.get("presets_applied") and len(presets) != len(
            list(doc.get("presets_applied") or ())):
        issues.append("presets_unknown_ignored")
    try:
        revision = int(doc.get("revision", 1) or 1)
    except (TypeError, ValueError):
        revision = 1
        issues.append("revision_default")
    history = doc.get("history")
    history = list(history) if isinstance(history, (list, tuple)) else []
    normalized = {
        "v": int(doc.get("v", DOC_VERSION) or DOC_VERSION),
        "revision": revision,
        "presets_applied": list(presets),
        "rules": [r.as_dict() for r in rules],
        "soft_instructions": [s.as_dict() for s in soft],
        "history": history[:HISTORY_MAX],
        "updated_at": str(doc.get("updated_at") or ""),
        "updated_by": doc.get("updated_by"),
        "reason": str(doc.get("reason") or ""),
    }
    return normalized, tuple(issues)


def build_document(*, rules: Iterable[Any] = (), soft: Iterable[Any] = (),
                   presets: Iterable[str] = (), revision: int = 1,
                   owner: Any = None, reason: str = "",
                   updated_at: str = "") -> dict:
    """Собрать валидный документ политики (UI/тесты/миграция).

    Presets разворачиваются в правила/привычки (``origin=preset:<name>``),
    затем применяются явные записи. Никогда не бросает."""
    preset_names = [str(p) for p in (presets or ()) if str(p) in PRESET_SPECS]
    expanded: list[dict] = []
    for name in preset_names:
        expanded.extend(preset_rules(name))
    expanded.extend(dict(r) if isinstance(r, Mapping) else r
                    for r in (rules or ()))
    soft_rows: list[dict] = []
    for name in preset_names:
        soft_rows.extend(preset_soft(name))
    soft_rows.extend(dict(s) if isinstance(s, Mapping) else s
                     for s in (soft or ()))
    doc = {
        "v": DOC_VERSION, "revision": int(revision or 1),
        "presets_applied": preset_names, "rules": expanded,
        "soft_instructions": soft_rows,
        "updated_at": updated_at or _now_iso(), "updated_by": owner,
        "reason": str(reason or ""), "history": [],
    }
    normalized, _issues = validate_document(doc)
    return normalized


def preset_rules(name: str) -> list[dict]:
    """Правила шаблона (SOUL-16.1.5) как обычные записи реестра."""
    spec = PRESET_SPECS.get(str(name or ""))
    if not spec:
        return []
    out: list[dict] = []
    for raw in spec.get("rules") or ():
        row = dict(raw)
        row.setdefault("scope", "global")
        row.setdefault("enabled", True)
        row.setdefault("owner", None)
        row.setdefault("revision", 1)
        row["origin"] = f"preset:{name}"
        out.append(row)
    return out


def preset_soft(name: str) -> list[dict]:
    """Мягкие привычки шаблона (SOUL-16.1.5)."""
    spec = PRESET_SPECS.get(str(name or ""))
    if not spec:
        return []
    out: list[dict] = []
    for index, text in enumerate(spec.get("soft_instructions") or ()):
        out.append({"id": f"soft.{name}.{index}", "text": str(text),
                    "scope": "global", "enabled": True, "revision": 1})
    return out


def rule_applies(rule: StyleRule, context: str) -> bool:
    """Применимо ли правило к запрошенному контексту (SOUL-16.1.3/16.4.4).

    ``global``/``chat`` — обычная речь (включая инициативу того же чата);
    ``initiative``/``editorial``/``code_or_structured`` — только свой пакет.
    Машинные стадии не получают правил формы вовсе."""
    pack = str(context or "regular").strip().lower() or "regular"
    if pack in MACHINE_CONTEXTS:
        return False
    if pack == "code_or_structured":
        # Пакет кода/данных: действуют только явные правила этого пакета
        # (обычная речь не диктует форму коду и структурированному выводу).
        return rule.scope == "code_or_structured"
    if rule.scope in ("global", "chat"):
        return pack in ("regular", "initiative")
    return rule.scope == pack


def merge_documents(global_doc: Any = None,
                    chat_doc: Any = None) -> tuple[tuple[ResolvedRule, ...],
                                                   tuple[SoftInstruction, ...],
                                                   tuple[str, ...]]:
    """Детерминированный merge global + chat (design-source-of-truth §2.2).

    Правило с тем же ``id`` в chat-документе ЗАМЕНЯЕТ глобальное; новое ``id``
    добавляется; ``enabled=false`` в chat отключает правило. Ничего не
    «протекает» из чужого чата: chat-документ передаётся вызывающим. Никогда
    не бросает."""
    conflicts: list[str] = []
    glob, glob_issues = validate_document(global_doc)
    chat, chat_issues = validate_document(chat_doc)
    for issue in (glob_issues + chat_issues):
        conflicts.append(f"doc_issue:{issue}")
    rows: "OrderedDict[str, ResolvedRule]" = OrderedDict()
    for rule in _rules_of(glob):
        rows[rule.id] = ResolvedRule(rule=rule, source="preset"
                                     if rule.origin.startswith("preset:")
                                     else "global")
    for rule in _rules_of(chat):
        rows[rule.id] = ResolvedRule(rule=rule, source="chat")
    soft: "OrderedDict[str, SoftInstruction]" = OrderedDict()
    for entry in _soft_of(glob):
        soft[entry.id] = entry
    for entry in _soft_of(chat):
        soft[entry.id] = entry
    return tuple(rows.values()), tuple(soft.values()), tuple(conflicts)


def _rules_of(doc: Mapping) -> tuple[StyleRule, ...]:
    out: list[StyleRule] = []
    for index, raw in enumerate(doc.get("rules") or ()):
        rule, _issues = normalize_rule(raw, index=index)
        if rule is not None:
            out.append(rule)
    return tuple(out)


def _soft_of(doc: Mapping) -> tuple[SoftInstruction, ...]:
    out: list[SoftInstruction] = []
    for index, raw in enumerate(doc.get("soft_instructions") or ()):
        entry = normalize_soft(raw, index=index)
        if entry is not None:
            out.append(entry)
    return tuple(out)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Резолв effective_style_policy (после scope/типа выхода, ДО Writer)
# ═══════════════════════════════════════════════════════════════════════════

def build_hint(policy: EffectiveStylePolicy, *, max_chars: int = 0) -> str:
    """Короткий semantic hint активных правил (слой 10 композера)."""
    try:
        from services.prompt_style_blocks import render_style_policy_hint
        return render_style_policy_hint(policy, max_chars=max_chars)
    except Exception:      # pragma: no cover - hint не роняет резолв
        return ""


def effective_policy_sync(global_doc: Any = None, chat_doc: Any = None, *,
                          context: str = "regular",
                          extent: str = "", enabled: bool = True,
                          skip_reason: str = "") -> EffectiveStylePolicy:
    """Собрать эффективную политику из уже прочитанных документов.

    Чистая функция (без I/O) — используется и рантайм-резолвером, и тестами, и
    Inspector'ом. Никогда не бросает."""
    pack = str(context or "regular").strip().lower() or "regular"
    if not enabled:
        return EffectiveStylePolicy(context=pack, source="default",
                                    skip_reason=skip_reason
                                    or "style_policy_disabled",
                                    extent=str(extent or ""))
    if pack in MACHINE_CONTEXTS:
        return EffectiveStylePolicy(context=pack, source="default",
                                    skip_reason="machine_stage",
                                    extent=str(extent or ""))
    try:
        rules, soft, conflicts = merge_documents(global_doc, chat_doc)
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("[style_policy] merge failed", exc_info=True)
        return EffectiveStylePolicy(context=pack, skip_reason="read_error",
                                    extent=str(extent or ""))
    glob_doc, _gi = validate_document(global_doc)
    chat_doc_n, _ci = validate_document(chat_doc)
    if chat_doc_n:
        source = "chat"
    elif glob_doc:
        source = "global"
    else:
        source = "default"
    applicable = tuple(r for r in rules if rule_applies(r.rule, pack))
    soft_rows = tuple(s for s in soft if s.enabled and _soft_applies(s, pack))
    policy = EffectiveStylePolicy(
        rules=applicable, soft_instructions=soft_rows, context=pack,
        source=source,
        revision=_policy_revision(glob_doc, chat_doc_n),
        presets_applied=tuple(chat_doc_n.get("presets_applied")
                              or glob_doc.get("presets_applied") or ()),
        skip_reason=("style_policy_absent" if not applicable and not soft_rows
                     else ""),
        conflicts=conflicts, extent=str(extent or ""))
    hint = build_hint(policy)
    policy = dataclasses.replace(policy, hint=hint,
                                 hint_tokens=_tokens_est(hint) if hint else 0)
    return policy


def _soft_applies(entry: SoftInstruction, pack: str) -> bool:
    if pack in MACHINE_CONTEXTS:
        return False
    if pack == "code_or_structured":
        return entry.scope == "code_or_structured"
    if entry.scope in ("global", "chat"):
        return pack in ("regular", "initiative")
    return entry.scope == pack


def _policy_revision(glob_doc: Mapping, chat_doc: Mapping) -> str:
    """Ревизия эффективной политики (в версии/провенансе, SOUL-15.5)."""
    parts = []
    for doc, tag in ((glob_doc, "g"), (chat_doc, "c")):
        if doc:
            parts.append(f"{tag}{int(doc.get('revision', 1) or 1)}"
                         f".{_sha12({k: v for k, v in doc.items() if k != 'history'})}")
    return "|".join(parts)


async def _read_layers(chat_id: int) -> tuple[Any, Any, bool]:
    """``(global_doc, chat_doc, ok)`` из существующих слоёв (без нового store).

    Глобальный — ``bot_settings('style.policy')`` через hot-кэш; чатовый —
    ``chat_params.overrides`` того же ключа (design §2.2). ``ok=False`` при
    недоступности конфигурационного слоя (PG outage) — политика не
    выдумывается (no silent degradation)."""
    from services import hot_config as hot
    global_doc = None
    chat_doc = None
    ok = True
    try:
        global_doc = hot.get(DOC_KEY, None)
    except Exception:
        ok = False
    try:
        from services.chat_params import get_chat_params_cache
        cache = get_chat_params_cache()
        if cache is not None:
            root = await cache.get_chat_params(int(chat_id or 0))
            if isinstance(root, Mapping):
                chat_doc = (root.get("overrides") or {}).get(DOC_KEY)
    except Exception:
        chat_doc = None
    return global_doc, chat_doc, ok


async def effective_style_policy(chat_id: int, *, context: str = "regular",
                                 extent: str = "",
                                 enabled: bool | None = None,
                                 global_doc: Any = _UNSET,
                                 chat_doc: Any = _UNSET
                                 ) -> EffectiveStylePolicy:
    """Эффективная политика для чата и типа выхода (SOUL-16.4.1).

    Вызывается ПОСЛЕ выбора scope/типа выхода и ДО Writer: отдаёт правила,
    soft-привычки, источник на каждое правило и короткий hint. Флаг
    ``SPEECH_STYLE_POLICY_ENABLED`` OFF → пустая политика с причиной
    ``style_policy_disabled`` (паритет). Никогда не бросает."""
    if enabled is None:
        try:
            from services import mca_gates
            enabled = bool(mca_gates.speech_style_policy_enabled())
        except Exception:      # pragma: no cover - защитная ветка
            enabled = False
    if not enabled:
        return effective_policy_sync(context=context, extent=extent,
                                     enabled=False)
    if global_doc is _UNSET or chat_doc is _UNSET:
        read_global, read_chat, ok = await _read_layers(chat_id)
        if global_doc is _UNSET:
            global_doc = read_global
        if chat_doc is _UNSET:
            chat_doc = read_chat
        if not ok and not global_doc and not chat_doc:
            return effective_policy_sync(context=context, extent=extent,
                                         enabled=False,
                                         skip_reason="style_policy_unavailable")
    return effective_policy_sync(global_doc, chat_doc, context=context,
                                 extent=extent, enabled=True)


async def resolve_style_policy_ref(chat_id: int, *, context: str = "regular",
                                   extent: str = ""):
    """Снимок политики в форме ``prompt_composer.StylePolicyRef`` (слой 10).

    Композер (W2) запрашивает снимок в начале хода и кладёт в манифест
    ``versions.style_policy`` + hint. Хинт покрывает обычную речь и инициативу
    того же чата (редакционные/кодовые правила в чатовый hint не попадают).
    Никогда не бросает."""
    policy = await effective_style_policy(chat_id, context=context,
                                         extent=extent)
    try:
        from services.prompt_composer import StylePolicyRef
    except Exception:      # pragma: no cover - композер недоступен
        return None
    return StylePolicyRef(
        hint=policy.hint, revision=policy.revision or "",
        source=policy.source or "default",
        rule_count=len(policy.rules),
        soft_count=len(policy.soft_instructions),
        enabled=True,
        skip_reason=policy.skip_reason)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Семантические сегменты: защищённые спаны (SOUL-16.3.3/16.2.3)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Span:
    """Семантический сегмент текста (позиции в исходной строке)."""

    start: int
    end: int
    kind: str = "plain"

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


#: Приоритет перекрытия: чем раньше, тем «сильнее» сегмент.
_SPAN_PRIORITY = ("code", "json", "verbatim_quote", "telegram_entity", "url",
                  "version_literal", "markdown_markup", "ellipsis")

_URL_RE = re.compile(r"(?:https?://|tg://|www\.)[^\s<>()\"'«»\[\]]+",
                     re.IGNORECASE)
_URL_TRAIL = ".,;:!?…"
_VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.]+)?\b")
_ELLIPSIS_RE = re.compile(r"\.{3,}|…")
_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|s|strike|del|code|pre|a|blockquote|span|"
    r"tg-spoiler|tg-emoji)\b[^>]*>", re.IGNORECASE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
#: Кодовый фрагмент без обратных кавычек: вызов функции со скобками
#: (``print("hi")``, ``foo(bar)``) — кавычки внутри не графические (SOUL-16.3.3).
_CODE_CALL_RE = re.compile(r"\b[A-Za-z_][\w.]*\s*\([^()\n]{0,120}\)")
#: Технический литерал-путь/файл (``C:\\path\\x.txt``, ``/etc/hosts``,
#: ``report.json``) — кавычки вокруг него не графические (SOUL-16.3.3).
_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\[^\s\"'«»]+)"
    r"|(?:/[\w./-]{3,})"
    r"|(?:\b[\w-]+\.(?:txt|json|py|md|log|csv|png|jpg|jpeg|pdf|exe|zip|tar|gz"
    r"|html|css|js|ya?ml|toml|ini|cfg|sql|sh|bat|ps1)\b)")
_MD_TOKEN_RE = re.compile(r"\*\*|__|~~|\|\|")
_FENCE_RE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)


def _fence_spans(text: str) -> list[Span]:
    """Ограждённые блоки кода (включая незакрытый хвост — защищаем как есть)."""
    spans: list[Span] = []
    marks = list(_FENCE_RE.finditer(text))
    index = 0
    while index < len(marks):
        opener = marks[index]
        closer = marks[index + 1] if index + 1 < len(marks) else None
        end = closer.end() if closer is not None else len(text)
        spans.append(Span(opener.start(), end, "code"))
        index += 2 if closer is not None else 1
    return spans


#: Пределы распознавания машинных данных (bounded: текст ответа короткий).
_JSON_SCAN_LIMIT = 20000
_JSON_MAX_CANDIDATES = 256


def _json_block_end(text: str, start: int) -> int | None:
    """Конец сбалансированного ``{...}``/``[...]`` от ``start`` или ``None``.

    Строки и escape-последовательности учитываются: ``{"a": "}"}`` — один
    блок, а не два."""
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, min(len(text), start + _JSON_SCAN_LIMIT)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return pos + 1
    return None


def _json_like(block: str) -> bool:
    """Похоже ли на машинную запись, даже если ``json.loads`` её не принял.

    Признак — кавычки плюс ``:``/``,`` внутри скобок: кавычки здесь синтаксис
    данных, а не речь. Такая запись защищается целиком (SOUL-16.2.3: показать
    ``exempted``/``conflict``, а не молча испортить байты)."""
    return '"' in block and (":" in block or "," in block)


def _unterminated_json_like(text: str, start: int) -> bool:
    """Явный признак НЕзакрытой машинной записи сразу после скобки.

    ``{"k": "v`` / ``["a", ...`` — сегментировать безопасно нельзя, поэтому
    остаток защищается как есть; обычный текст со скобкой (``Смотри [ссылка]``)
    сюда не попадает."""
    cursor = start + 1
    limit = min(len(text), start + 64)
    while cursor < limit and text[cursor] in " \t":
        cursor += 1
    if cursor >= len(text):
        return False
    char = text[cursor]
    if char == '"':
        return True
    return text[start] == "[" and char in "{["


def _json_spans(text: str) -> list[Span]:
    """Фрагменты-машинные данные (JSON) — в любом месте сообщения.

    Распознаются и блоки-строки, и inline-фрагменты в середине фразы, включая
    вложенные объекты, массивы и escape-кавычки: любые ``{...}``/``[...]`` с
    корректной вложенностью, которые ``json.loads`` принимает целиком. Если
    разбор не удался, но запись явно машинная (``_json_like``/
    ``_unterminated_json_like``), она всё равно защищается: повреждение
    payload запрещено (SOUL-16.2.3/16.3.3, review-w3 F1)."""
    spans: list[Span] = []
    length = len(text)
    index = 0
    attempts = 0
    while index < length and attempts < _JSON_MAX_CANDIDATES:
        if text[index] not in "{[":
            index += 1
            continue
        attempts += 1
        end = _json_block_end(text, index)
        if end is None:
            if _unterminated_json_like(text, index):
                spans.append(Span(index, length, "json"))
                break
            index += 1
            continue
        block = text[index:end]
        try:
            json.loads(block)
            parsed = True
        except Exception:
            parsed = False
        if parsed or _json_like(block):
            spans.append(Span(index, end, "json"))
            index = end            # вложенные фрагменты уже внутри сегмента
            continue
        index += 1
    return spans


def segment(text: Any, *, verbatim: bool = False,
            extra_protected: Iterable[str] = ()) -> tuple[Span, ...]:
    """Разобрать текст на семантические сегменты (SOUL-16.3.3).

    Защищённые типы: ``code`` (ограждённый/инлайн), ``json``,
    ``telegram_entity`` (HTML/Telegram-разметка), ``url``,
    ``version_literal`` (``1.2.3``), ``markdown_markup``, ``ellipsis``,
    ``verbatim_quote`` (весь текст либо явно переданные фрагменты). Никогда
    не бросает."""
    source = str(text or "")
    if not source:
        return ()
    raw: list[Span] = []
    try:
        raw.extend(_fence_spans(source))
        raw.extend(Span(m.start(), m.end(), "code")
                   for m in _INLINE_CODE_RE.finditer(source))
        raw.extend(Span(m.start(), m.end(), "code")
                   for m in _CODE_CALL_RE.finditer(source))
        for match in _PATH_RE.finditer(source):
            end = match.end()
            while end > match.start() and source[end - 1] in _URL_TRAIL:
                end -= 1
            if end > match.start():
                raw.append(Span(match.start(), end, "code"))
        raw.extend(_json_spans(source))
        raw.extend(Span(m.start(), m.end(), "telegram_entity")
                   for m in _TAG_RE.finditer(source))
        for match in _URL_RE.finditer(source):
            end = match.end()
            while end > match.start() and source[end - 1] in _URL_TRAIL:
                end -= 1
            if end > match.start():
                raw.append(Span(match.start(), end, "url"))
        raw.extend(Span(m.start(), m.end(), "version_literal")
                   for m in _VERSION_RE.finditer(source))
        raw.extend(Span(m.start(), m.end(), "markdown_markup")
                   for m in _MD_TOKEN_RE.finditer(source))
        raw.extend(Span(m.start(), m.end(), "ellipsis")
                   for m in _ELLIPSIS_RE.finditer(source))
        if verbatim:
            raw.append(Span(0, len(source), "verbatim_quote"))
        for fragment in (extra_protected or ()):
            needle = str(fragment or "")
            if not needle:
                continue
            start = source.find(needle)
            while start >= 0:
                raw.append(Span(start, start + len(needle), "verbatim_quote"))
                start = source.find(needle, start + 1)
    except Exception:      # pragma: no cover - сегментация не роняет проход
        logger.warning("[style_policy] segment failed", exc_info=True)
        return ()
    return _merge_spans(raw)


def _merge_spans(spans: Sequence[Span]) -> tuple[Span, ...]:
    """Слить пересечения: приоритет по :data:`_SPAN_PRIORITY`.

    Пересекающиеся сегменты объединяются в ОБЪЕДИНЕНИЕ диапазонов (kind — у
    победителя по приоритету): защита только расширяется, никогда не сужается.
    Иначе узкий приоритетный сегмент (вложенный ``code`` внутри ``json``)
    вытеснял широкий и остаток машинных данных становился обычным текстом —
    hard-правило кавычек портило байты JSON (review-w3 F1)."""
    if not spans:
        return ()
    order = {kind: index for index, kind in enumerate(_SPAN_PRIORITY)}
    ranked = sorted(spans, key=lambda s: (s.start, order.get(s.kind, 99),
                                          -(s.end - s.start)))
    merged: list[Span] = []
    for span in ranked:
        if span.end <= span.start:
            continue
        hit = True
        while hit:
            hit = False
            index = 0
            while index < len(merged):
                kept = merged[index]
                if span.start < kept.end and span.end > kept.start:
                    winner = kept if order.get(kept.kind, 99) <= \
                        order.get(span.kind, 99) else span
                    span = Span(min(kept.start, span.start),
                                max(kept.end, span.end), winner.kind)
                    merged.pop(index)
                    hit = True
                    continue
                index += 1
        merged.append(span)
    return tuple(sorted(merged, key=lambda s: s.start))


def protected_ranges(spans: Sequence[Span], *,
                     exemptions: Iterable[str] | None = None
                     ) -> tuple[tuple[int, int], ...]:
    """Диапазоны защищённых сегментов (кроме ``plain``)."""
    allowed = None if exemptions is None else {str(x) for x in exemptions}
    return tuple((s.start, s.end) for s in spans
                 if s.kind != "plain"
                 and (allowed is None or s.kind in allowed))


def plain_regions(text: Any,
                  spans: Sequence[Span]) -> tuple[tuple[int, int], ...]:
    """Диапазоны обычного текста (дополнение защищённых сегментов)."""
    source = str(text or "")
    regions: list[tuple[int, int]] = []
    cursor = 0
    for span in sorted(spans, key=lambda s: s.start):
        if span.start > cursor:
            regions.append((cursor, span.start))
        cursor = max(cursor, span.end)
    if cursor < len(source):
        regions.append((cursor, len(source)))
    return tuple(regions)


def span_kind_at(spans: Sequence[Span], index: int) -> str:
    """Тип сегмента, содержащего позицию (``plain`` если не защищён)."""
    for span in spans:
        if span.start <= index < span.end:
            return span.kind
    return "plain"


def segment_view(text: Any, **kwargs) -> list[dict]:
    """R17-safe витрина сегментов (kind/позиции, без текста) для тестов/UI."""
    return [{"kind": s.kind, "start": s.start, "end": s.end}
            for s in segment(text, **kwargs)]


# ═══════════════════════════════════════════════════════════════════════════
# 5. Детерминированный валидатор/форматтер правил формы (SOUL-16.1.1)
# ═══════════════════════════════════════════════════════════════════════════

#: Порядок исполнения правил внутри одного прохода. Завершающая точка —
#: ПОСЛЕДНЕЙ: она решает про финальный символ уже изменённого текста.
RULE_ORDER = ("emoji", "forbidden_chars", "quotation_marks", "line_breaks",
              "one_word", "trailing_period")

#: Unicode-пробелы/невидимые символы (SOUL-16.3.1: последний содержательный знак).
_TRAILING_WS = " \t\r\n\u00a0\u200b\u200c\u200d\ufeff\u2060\u2028\u2029"
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2049\u203C\uFE0F"
    "\u20E3\u200D]+")
_QUOTE_CLASS_PAIRS: dict[str, tuple[str, str]] = {
    "«»": ("«", "»"), "„“": ("„", "“"), "“”": ("“", "”"),
    "\"\"": ("\"", "\""), "\"": ("\"", "\""), "'": ("'", "'"),
}
_DIGIT_RE = re.compile(r"\d")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _resolve_exemptions(rule: StyleRule, spans: Sequence[Span]
                        ) -> tuple[tuple[int, int], ...]:
    """Защищённые диапазоны с учётом исключений конкретного правила."""
    allowed = set(rule.content_type_exemptions or DEFAULT_EXEMPTIONS)
    return protected_ranges(spans, exemptions=allowed)


def _protected_kind_in(spans: Sequence[Span], start: int, end: int) -> str:
    for span in spans:
        if span.kind == "plain":
            continue
        if start < span.end and end > span.start:
            return span.kind
    return ""


def _in_plain(spans: Sequence[Span], index: int) -> bool:
    return span_kind_at(spans, index) == "plain"


def _strategy_outcome(rule: StyleRule, *, protected_kind: str,
                      reason: str) -> tuple[str, str]:
    """Исход при невозможности безопасной правки (SOUL-16.2.3/16.4.2)."""
    if rule.conflict_strategy == "deny_incompatible":
        return STATUS_DENIED, f"denied:{reason}"
    if rule.conflict_strategy == "prefer_task":
        return STATUS_EXEMPTED, f"task_precedence:{reason}"
    if protected_kind:
        return STATUS_EXEMPTED, "protected_verbatim"
    return STATUS_CONFLICT, reason


# ── 5.1 Обработчики правил ──────────────────────────────────────────────────
# Каждый возвращает ``(status, new_text, reason, detail)``. ``new_text``
# заполняется только при безопасной локальной правке.

def _apply_emoji(text: str, rule: StyleRule,
                 spans: Sequence[Span]) -> tuple:
    found = [m for m in _EMOJI_RE.finditer(text)
             if _in_plain(spans, m.start())]
    protected_hits = [m for m in _EMOJI_RE.finditer(text)
                      if not _in_plain(spans, m.start())]
    if not found:
        if protected_hits:
            return (STATUS_EXEMPTED, None, "protected_verbatim",
                    {"protected": len(protected_hits)})
        return (STATUS_PASS, None, "", {})
    if rule.strictness != "hard":
        return (STATUS_NA, None, "soft_habit_writer_only",
                {"observed": len(found)})
    new = text
    for start, end in reversed(plain_regions(text, spans)):
        chunk = new[start:end]
        cleaned = _EMOJI_RE.sub(" ", chunk)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        if chunk[:1] and not chunk[:1].isspace():
            cleaned = cleaned.lstrip(" \t")
        if chunk[-1:] and not chunk[-1:].isspace():
            cleaned = cleaned.rstrip(" \t")
        new = new[:start] + cleaned + new[end:]
    return (STATUS_REPAIRED, new, "emoji_removed",
            {"removed": len(found), "protected_kept": len(protected_hits)})


def _apply_forbidden_chars(text: str, rule: StyleRule,
                           spans: Sequence[Span]) -> tuple:
    raw = (rule.params or {}).get("chars")
    if isinstance(raw, str):
        chars = [raw]
    elif isinstance(raw, (list, tuple)):
        chars = [str(c) for c in raw if str(c)]
    else:
        chars = []
    if not chars:
        return (STATUS_NA, None, "rule_params_absent", {})
    hits = 0
    protected_hits = 0
    for char in chars:
        start = text.find(char)
        while start >= 0:
            if _in_plain(spans, start):
                hits += 1
            else:
                protected_hits += 1
            start = text.find(char, start + 1)
    if not hits:
        if protected_hits:
            return (STATUS_EXEMPTED, None, "protected_verbatim",
                    {"protected": protected_hits})
        return (STATUS_PASS, None, "", {})
    if rule.strictness != "hard":
        return (STATUS_NA, None, "soft_habit_writer_only", {"observed": hits})
    char_set = set()
    for char in chars:
        char_set.update(char)
    pieces: list[str] = []
    for index, symbol in enumerate(text):
        if symbol in char_set and _in_plain(spans, index):
            continue
        pieces.append(symbol)
    new = re.sub(r"[ \t]{2,}", " ", "".join(pieces))
    return (STATUS_REPAIRED, new, "forbidden_chars_removed",
            {"removed": hits, "protected_kept": protected_hits})


def _quote_positions(text: str, spans: Sequence[Span],
                     pairs: Sequence[tuple[str, str]],
                     *, detect_apostrophe: bool) -> tuple[list, dict]:
    """``(пары кавычек, позиции по классам)`` в обычном тексте.

    Стек открывающих: неоднозначные символы (``“`` закрывает ``„“`` и
    открывает ``“”``) разрешаются по контексту — сначала закрытие верхушки
    стека, иначе открытие. Непарные символы возвращаются как ``unpaired``."""
    open_map: dict[str, int] = {}
    for class_index, (open_char, _close) in enumerate(pairs):
        open_map.setdefault(open_char, class_index)
    stack: list[tuple[int, int]] = []       # (позиция, индекс класса)
    matched: list[tuple[int, int, int]] = []
    unmatched_close: list[int] = []
    by_class: dict[int, list[int]] = {index: [] for index in range(len(pairs))}
    for index, char in enumerate(text):
        if not _in_plain(spans, index):
            continue
        is_open = char in open_map
        is_close = any(char == close for _open, close in pairs)
        if not is_open and not is_close:
            continue
        prev_char = text[index - 1] if index > 0 else ""
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if detect_apostrophe:
            if char == "'" and _LETTER_RE.match(prev_char or " ") and \
                    _LETTER_RE.match(next_char or " "):
                continue             # апостроф внутри слова, не кавычка
            if char in ("'", "\"", "\u2019") and _DIGIT_RE.match(
                    prev_char or ""):
                continue             # минуты/футы/дюймы рядом с числом
        if stack:
            open_position, class_index = stack[-1]
            if char == pairs[class_index][1]:
                matched.append((open_position, index, class_index))
                stack.pop()
                by_class[class_index].extend((open_position, index))
                continue
        if is_open:
            stack.append((index, open_map[char]))
            continue
        unmatched_close.append(index)
    for position, _class_index in stack:
        unmatched_close.append(position)
    return matched, by_class, unmatched_close


def _protected_machine_quotes(text: str, spans: Sequence[Span],
                              pairs: Sequence[tuple[str, str]]) -> int:
    """Кавычки внутри защищённых сегментов при наличии JSON-фрагмента.

    Машинные данные (``{"k": "v"}``) — не ирония: кавычки там синтаксис.
    Возвращает их число, чтобы исход был честным ``exempted``, а не «pass»
    (SOUL-16.2.3, review-w3 F1). Обычный код без JSON (``print("hi")``) сюда
    не попадает — его контракт не меняется."""
    try:
        if not _json_spans(text):
            return 0
    except Exception:      # pragma: no cover - защитная ветка
        return 0
    chars = {char for pair in pairs for char in pair}
    count = 0
    for index, char in enumerate(text):
        if char in chars and span_kind_at(spans, index) != "plain":
            count += 1
    return count


def _apply_quotation_marks(text: str, rule: StyleRule,
                           spans: Sequence[Span]) -> tuple:
    params = rule.params or {}
    classes = params.get("classes")
    if isinstance(classes, str):
        classes = [classes]
    if not isinstance(classes, (list, tuple)) or not classes:
        classes = ["«»", "„“", "“”", "\"", "'"]
    pairs: list[tuple[str, str]] = []
    for entry in classes:
        key = str(entry)
        if key in _QUOTE_CLASS_PAIRS:
            pairs.append(_QUOTE_CLASS_PAIRS[key])
        elif len(key) >= 2:
            pairs.append((key[0], key[1]))
        elif key:
            pairs.append((key, key))
    if not pairs:
        return (STATUS_NA, None, "rule_params_absent", {})
    detect_apostrophe = bool(params.get("detect_apostrophe", True))
    found, _by_class, unpaired_positions = _quote_positions(
        text, spans, pairs, detect_apostrophe=detect_apostrophe)
    unpaired = len(unpaired_positions)
    if not found and not unpaired:
        protected_machine = _protected_machine_quotes(text, spans, pairs)
        if protected_machine:
            return (STATUS_EXEMPTED, None, "protected_verbatim",
                    {"protected": protected_machine, "span": "json"})
        return (STATUS_PASS, None, "", {})
    if rule.strictness != "hard":
        return (STATUS_NA, None, "soft_habit_writer_only",
                {"observed": len(found) * 2 + unpaired})
    removals: list[int] = []
    conflicts = 0
    exempted = 0
    reason_out = "protected_verbatim"
    for start, end, _class_index in sorted(found, reverse=True):
        inner = text[start + 1:end]
        span_kind = _protected_kind_in(spans, start + 1, end) or \
            _protected_kind_in(spans, start, end + 1)
        if span_kind:
            status, reason = _strategy_outcome(
                rule, protected_kind=span_kind, reason="quotes_in_protected")
            if status == STATUS_EXEMPTED:
                exempted += 1
                reason_out = reason
            else:
                conflicts += 1
            continue
        if len(inner.strip().split()) > 1:
            # Многословная цитата без требования дословности: удалять кавычки
            # вслепую нельзя (SOUL-16.2.2) — исход по стратегии правила.
            status, reason = _strategy_outcome(
                rule, protected_kind="", reason="quotes_require_rephrase")
            if status == STATUS_EXEMPTED:
                exempted += 1
                reason_out = reason
            else:
                conflicts += 1
            continue
        removals.extend((start, end))
    if not removals:
        if conflicts:
            status, reason = _strategy_outcome(
                rule, protected_kind="", reason="quotes_require_rephrase")
            return (status, None, reason, {"conflicts": conflicts,
                                           "protected": exempted})
        if exempted:
            return (STATUS_EXEMPTED, None, reason_out,
                    {"protected": exempted, "unpaired": unpaired})
        return (STATUS_CONFLICT, None, "unpaired_quote",
                {"unpaired": unpaired})
    new = text
    for position in sorted(set(removals), reverse=True):
        new = new[:position] + new[position + 1:]
    detail = {"removed_pairs": len(set(removals)) // 2,
              "conflicts": conflicts, "protected": exempted,
              "unpaired": unpaired,
              "risk": "irony_may_be_lost"}
    if conflicts:
        # Часть кавычек снята безопасно, но остались требующие переформулировки:
        # правка применена, правило НЕ объявляется пройденным (SOUL-15.7).
        return (STATUS_CONFLICT, new, "quotes_require_rephrase", detail)
    if unpaired:
        return (STATUS_CONFLICT, new, "unpaired_quote_left", detail)
    return (STATUS_REPAIRED, new, "ironic_quotes_removed", detail)


def _apply_line_breaks(text: str, rule: StyleRule,
                       spans: Sequence[Span]) -> tuple:
    try:
        limit = int((rule.params or {}).get("max_breaks", 2))
    except (TypeError, ValueError):
        limit = 2
    if limit < 0:
        return (STATUS_NA, None, "rule_params_absent", {})
    regions = plain_regions(text, spans)
    total = 0
    for start, end in regions:
        total += text[start:end].count("\n")
    if total <= limit:
        return (STATUS_PASS, None, "", {"breaks": total, "max": limit})
    if rule.strictness != "hard":
        return (STATUS_NA, None, "soft_habit_writer_only",
                {"observed": total, "max": limit})
    new = text
    for start, end in reversed(regions):
        chunk = new[start:end]
        new = new[:start] + re.sub(r"\n{3,}", "\n\n", chunk) + new[end:]
    recount = 0
    regions2 = plain_regions(new, segment(new))
    for start, end in regions2:
        recount += new[start:end].count("\n")
    if recount <= limit:
        return (STATUS_REPAIRED, new, "blank_line_runs_collapsed",
                {"breaks": recount, "max": limit, "before": total})
    if new != text:
        # Частичная безопасная правка (пустые прогоны схлопнуты), но лимит
        # всё ещё превышен одиночными переносами → честный conflict.
        return (STATUS_CONFLICT, new, "line_breaks_exceeded",
                {"breaks": recount, "max": limit, "before": total})
    return (STATUS_CONFLICT, None, "line_breaks_exceeded",
            {"breaks": recount, "max": limit})


def _apply_one_word(text: str, rule: StyleRule, spans: Sequence[Span], *,
                    plan=None, explicit_form: str = "",
                    covered_by_extent: bool = False) -> tuple:
    from services import response_extent as _extent

    if covered_by_extent:
        return (STATUS_NA, None, "covered_by_extent_check", {})
    if rule.strictness != "hard":
        return (STATUS_NA, None, "soft_habit_writer_only", {})
    plan_extent = str(getattr(plan, "extent", "") or "")
    if explicit_form in _extent.LONGFORM_FAMILY or plan_extent in \
            _extent.LONGFORM_FAMILY:
        # Явная длинная задача пользователя старше правила владельца обычной
        # речи (SOUL-16.4.2) — конфликт показывается, форма не ломается.
        status, reason = _strategy_outcome(
            rule, protected_kind="", reason="owner_rule_vs_task")
        return (status, None, reason, {"plan_extent": plan_extent or "explicit"})
    check = _extent.check_extent(
        text, _extent.ResponsePlan(extent="one_word"), explicit_form="one_word",
        ignore_ranges=_resolve_exemptions(rule, spans))
    if check.status == STATUS_PASS:
        return (STATUS_PASS, None, "", {"words": len(check.words)})
    if check.status == STATUS_REPAIRED:
        return (STATUS_REPAIRED, check.text, check.reason,
                dict(check.detail))
    if check.status == STATUS_EXEMPTED:
        return (STATUS_EXEMPTED, None, check.reason, dict(check.detail))
    if check.status == STATUS_CONFLICT:
        return (STATUS_CONFLICT, None, check.reason, dict(check.detail))
    return (STATUS_FAILED, None, check.reason, dict(check.detail))


def _apply_trailing_period(text: str, rule: StyleRule,
                           spans: Sequence[Span]) -> tuple:
    stripped = text.rstrip(_TRAILING_WS)
    if not stripped or not stripped.endswith("."):
        return (STATUS_PASS, None, "", {})
    index = len(stripped) - 1
    previous = stripped[index - 1] if index > 0 else ""
    ellipsis = (rule.params or {}).get("ellipsis", "keep")
    is_ellipsis = previous == "." or bool(
        _ELLIPSIS_RE.fullmatch(stripped[max(0, index - 2):index + 1]))
    span_kind = span_kind_at(spans, index)
    if is_ellipsis or span_kind == "ellipsis":
        if str(ellipsis) != "strip":
            return (STATUS_EXEMPTED, None, "ellipsis_kept",
                    {"param": "ellipsis=keep"})
        start = index
        while start > 0 and stripped[start - 1] == ".":
            start -= 1
        return (STATUS_REPAIRED, stripped[:start].rstrip(_TRAILING_WS),
                "ellipsis_removed", {"removed": index + 1 - start})
    if span_kind != "plain":
        return (STATUS_EXEMPTED, None, "protected_verbatim",
                {"span": span_kind})
    if rule.strictness != "hard":
        return (STATUS_NA, None, "soft_habit_writer_only",
                {"observed": "trailing_period"})
    return (STATUS_REPAIRED, stripped[:index].rstrip(_TRAILING_WS),
            "trailing_period_removed", {})


_RULE_HANDLERS = {
    "emoji": _apply_emoji,
    "forbidden_chars": _apply_forbidden_chars,
    "quotation_marks": _apply_quotation_marks,
    "line_breaks": _apply_line_breaks,
    "trailing_period": _apply_trailing_period,
}


class StylePolicyValidator:
    """Один валидатор/форматтер для типизированных правил формы.

    ``run(text)`` — детерминированная проверка + безопасная локальная правка;
    ``verify(text)`` — проверка БЕЗ правок (payload после сериализации). Оба
    режима объяснимы per-rule и никогда не бросают."""

    def __init__(self, policy: EffectiveStylePolicy, *,
                 context: str = "regular", verbatim: bool = False,
                 extra_protected: Iterable[str] = (), plan=None,
                 explicit_form: str = "",
                 extent_status: str = "") -> None:
        self.policy = policy
        self.context = str(context or "regular")
        self.verbatim = bool(verbatim)
        self.extra_protected = tuple(extra_protected or ())
        self.plan = plan
        self.explicit_form = str(explicit_form or "")
        self.extent_status = str(extent_status or "")

    # ── публичный вход ─────────────────────────────────────────────────────
    def run(self, text: Any) -> tuple[str, list[RuleOutcome]]:
        """Проверка + безопасные правки. Возвращает ``(текст, исходы)``."""
        return self._execute(text, repair=True)

    def verify(self, text: Any) -> tuple[str, list[RuleOutcome]]:
        """Проверка БЕЗ правок (для доставленного payload)."""
        return self._execute(text, repair=False)

    # ── внутреннее ─────────────────────────────────────────────────────────
    def _execute(self, text: Any, *, repair: bool
                 ) -> tuple[str, list[RuleOutcome]]:
        current = str(text or "")
        results: list[RuleOutcome] = []
        if not self.policy.rules:
            return current, results
        covered_one_word = (str(getattr(self.plan, "extent", "") or "")
                            == "one_word"
                            or self.explicit_form == "one_word")
        for kind in RULE_ORDER:
            for resolved in self.policy.rules_for_kind(kind):
                rule = resolved.rule
                spans = segment(current, verbatim=self.verbatim,
                                extra_protected=self.extra_protected)
                try:
                    if kind == "one_word":
                        status, new_text, reason, detail = _apply_one_word(
                            current, rule, spans, plan=self.plan,
                            explicit_form=self.explicit_form,
                            covered_by_extent=(covered_one_word
                                               and self.extent_status
                                               in (STATUS_PASS,
                                                   STATUS_REPAIRED)))
                    else:
                        handler = _RULE_HANDLERS.get(kind)
                        if handler is None:
                            results.append(RuleOutcome(
                                rule_id=rule.id, kind=kind,
                                strictness=rule.strictness,
                                status=STATUS_NA,
                                reason="kind_handler_absent",
                                source=resolved.source))
                            continue
                        if self.verbatim and kind != "one_word":
                            # Дословный текст: байты не меняются НИКОГДА.
                            # Нарушение показывается как exempted, а не pass.
                            probe = handler(current, rule, ())
                            if probe[0] in (STATUS_REPAIRED, STATUS_CONFLICT,
                                            STATUS_FAILED):
                                status, new_text, reason, detail = (
                                    STATUS_EXEMPTED, None,
                                    "protected_verbatim", probe[3])
                            else:
                                status, new_text, reason, detail = (
                                    probe[0], None, probe[2], probe[3])
                        else:
                            status, new_text, reason, detail = handler(
                                current, rule, spans)
                except Exception:      # pragma: no cover - правило не роняет проход
                    logger.warning("[style_policy] rule failed | kind=%s",
                                   kind, exc_info=True)
                    results.append(RuleOutcome(
                        rule_id=rule.id, kind=kind,
                        strictness=rule.strictness, status=STATUS_FAILED,
                        reason="rule_error", source=resolved.source))
                    continue
                if status == STATUS_REPAIRED and new_text is not None:
                    if repair:
                        current = new_text
                    else:
                        status = STATUS_CONFLICT
                        reason = f"payload_still_violates:{reason}"
                elif new_text is not None and repair:
                    # Частичная безопасная правка при честном conflict:
                    # текст улучшен, исход остаётся непроходным.
                    current = new_text
                results.append(RuleOutcome(
                    rule_id=rule.id, kind=kind, strictness=rule.strictness,
                    status=status, reason=reason, source=resolved.source,
                    detail=tuple(sorted(dict(detail or {}).items()))))
        return current, results


# ═══════════════════════════════════════════════════════════════════════════
# 6. Антизалипание (SOUL-09): скользящее окно собственных фраз + capped ban-list
# ═══════════════════════════════════════════════════════════════════════════
# Существующие контуры (negative_constraints/anticliche_cache/freshness-guard)
# НЕ дублируются: здесь — наблюдаемое окно собственных реплик бота (лексические
# n-граммы) и пропорциональная реакция. Критичный повтор целой реплики
# остаётся за существующим duplicate-guard (одна bounded regeneration);
# некритичный повтор правится локально и НЕ порождает дорогую генерацию.

REPEAT_WINDOW_MAX = 12              # последних реплик бота на чат
REPEAT_TTL_SECONDS = 6 * 3600
NGRAM_N = 3
NGRAM_MIN_CHARS = 12
BAN_MAX = 50                        # capped динамический ban-list
BAN_TTL_SECONDS = 24 * 3600
BAN_ARCHIVE_MAX = 200               # bounded архив (TTL-вытеснение)
PHRASE_MIN_WORDS = 4                # «устойчивая привычка» короче — не наказываем
WHOLE_MESSAGE_WORDS = 6

_REPEAT_LOCK = threading.Lock()
_REPEAT_WINDOWS: "OrderedDict[int, deque]" = OrderedDict()
_BANS: dict[int, "OrderedDict[str, float]"] = {}
_BAN_ARCHIVE: dict[int, "OrderedDict[str, float]"] = {}

_WORD_SPLIT_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
#: Графические кавычки: фрагмент с ними считается цитатой и не «наказывается»
#: (SOUL-09.1: удачный повтор цитаты — не залипание).
_QUOTED_RE = re.compile(r"[«»„“”\"']")
_UNSAFE_PHRASE_RE = re.compile(
    r"@\w+|https?://|\b[\w.+-]+@[\w-]+\.[\w.]+\b|\d{4,}|[A-Za-z0-9+/]{24,}")


def _normalize_for_repeat(text: str) -> str:
    lowered = str(text or "").lower()
    lowered = re.sub(r"[^\w\s]+", " ", lowered, flags=re.UNICODE)
    return _WORD_SPLIT_RE.sub(" ", lowered).strip()


def _ngrams(text: str, size: int = NGRAM_N) -> tuple[str, ...]:
    words = _normalize_for_repeat(text).split(" ")
    words = [w for w in words if w]
    if len(words) < size:
        return ()
    out = []
    for index in range(len(words) - size + 1):
        gram = " ".join(words[index:index + size])
        if len(gram) >= NGRAM_MIN_CHARS:
            out.append(gram)
    return tuple(out)


def _phrase_is_safe(phrase: str) -> bool:
    """Без персональных имён/секретов/адресов/длинных чисел (SOUL-09.2)."""
    text = str(phrase or "").strip()
    if not text or _UNSAFE_PHRASE_RE.search(text):
        return False
    words = text.split(" ")
    for word in words[1:]:
        if word[:1].isupper():
            return False        # не первое слово с заглавной — вероятное имя
    return True


def record_bot_output(chat_id: int, text: str, *, now: float | None = None
                      ) -> None:
    """Записать собственную реплику в скользящее окно чата (bounded/TTL)."""
    try:
        key = int(chat_id or 0)
        stamp = float(now if now is not None else time.time())
        grams = _ngrams(text)
        with _REPEAT_LOCK:
            window = _REPEAT_WINDOWS.get(key)
            if window is None:
                window = deque(maxlen=REPEAT_WINDOW_MAX)
                _REPEAT_WINDOWS[key] = window
            window.append((stamp, _normalize_for_repeat(text), grams))
            while len(_REPEAT_WINDOWS) > 512:
                _REPEAT_WINDOWS.popitem(last=False)
    except Exception:      # pragma: no cover - наблюдаемость не роняет ответ
        logger.warning("[style_policy] repeat record failed", exc_info=True)


def detect_repetition(text: str, chat_id: int, *, now: float | None = None
                      ) -> tuple[dict, ...]:
    """Наблюдаемый повтор в окне собственных фраз (R17-safe: без текста).

    Возвращает находки: ``severity`` ∈ ``critical`` (почти вся реплика),
    ``sticky`` (повтор целой фразы ≥ ``PHRASE_MIN_WORDS`` слов),
    ``minor`` (общий n-грамм). Никогда не бросает."""
    try:
        key = int(chat_id or 0)
        stamp = float(now if now is not None else time.time())
        normalized = _normalize_for_repeat(text)
        if not normalized:
            return ()
        with _REPEAT_LOCK:
            window = list(_REPEAT_WINDOWS.get(key) or ())
        findings: list[dict] = []
        seen: set[str] = set()
        current_words = normalized.split(" ")
        for ts, previous, grams in window:
            if stamp - ts > REPEAT_TTL_SECONDS:
                continue
            if previous == normalized and len(current_words) >= 1:
                findings.append({"kind": "whole_message", "severity": "critical",
                                 "words": len(current_words)})
                continue
            previous_words = previous.split(" ")
            for gram in grams:
                if gram in seen or gram not in normalized:
                    continue
                seen.add(gram)
                size = len(gram.split(" "))
                severity = ("sticky" if size >= PHRASE_MIN_WORDS
                            or len(current_words) >= WHOLE_MESSAGE_WORDS
                            else "minor")
                findings.append({"kind": "ngram", "severity": severity,
                                 "ngram_len": size, "phrase_sha12":
                                 _sha12(gram),
                                 "phrase_words": size})
        if not findings:
            return ()
        order = {"critical": 0, "sticky": 1, "minor": 2}
        findings.sort(key=lambda row: order.get(row["severity"], 9))
        return tuple(findings[:6])
    except Exception:      # pragma: no cover - детектор не роняет ответ
        logger.warning("[style_policy] repetition detect failed", exc_info=True)
        return ()


def _local_repetition_repair(text: str, findings: Sequence[dict],
                             spans: Sequence[Span]) -> tuple[str, int]:
    """Локальная замена обнаруженного повтора (SOUL-09.2: сначала локально).

    Снимается только ПОВТОРЯЮЩАЯСЯ финальная фраза (≥ ``PHRASE_MIN_WORDS``
    слов, вне защищённых сегментов), если ответ остаётся непустым. Суть ответа
    не переписывается: фраза, в которой НЕТ найденного повтора, не удаляется
    никогда (review-w3 F2) — хвост сверяется с фактическими находками по
    хешам n-грамм. Повтор не в хвосте → текст не трогаем (наблюдение)."""
    if not findings:
        return text, 0
    sticky = [row for row in findings if row.get("severity") == "sticky"]
    if not sticky:
        return text, 0
    repeated = {str(row.get("phrase_sha12") or "") for row in sticky}
    repeated.discard("")
    if not repeated:
        return text, 0
    sentences = [part for part in _SENTENCE_SPLIT_RE.split(str(text or ""))
                 if part.strip()]
    if len(sentences) < 2:
        return text, 0
    tail = sentences[-1]
    words = tail.split()
    if len(words) < PHRASE_MIN_WORDS:
        return text, 0
    start = text.rfind(tail)
    if start < 0 or _protected_kind_in(spans, start, start + len(tail)):
        return text, 0
    if not _phrase_is_safe(tail):
        return text, 0
    if _QUOTED_RE.search(tail):
        return text, 0        # цитата (графические кавычки) не наказывается
    if not any(_sha12(gram) in repeated for gram in _ngrams(tail)):
        # Финальная фраза не содержит найденного повтора: удалять её нельзя
        # (это была бы потеря постороннего текста).
        return text, 0
    candidate = text[:start].rstrip()
    if candidate.strip():
        return candidate, 1
    return text, 0


def _prune_bans(key: int, *, now: float) -> None:
    bans = _BANS.get(key)
    if not bans:
        return
    expired = [gram for gram, ts in bans.items()
               if now - ts > BAN_TTL_SECONDS]
    for gram in expired:
        bans.pop(gram, None)
        archive = _BAN_ARCHIVE.setdefault(key, OrderedDict())
        archive[gram] = now
        while len(archive) > BAN_ARCHIVE_MAX:
            archive.popitem(last=False)


def register_dynamic_ban(chat_id: int, phrase: str, *,
                         now: float | None = None) -> bool:
    """Добавить фразу в capped/TTL динамический ban-list (без имён/секретов)."""
    try:
        text = str(phrase or "").strip()
        if not text or not _phrase_is_safe(text):
            return False
        key = int(chat_id or 0)
        stamp = float(now if now is not None else time.time())
        with _REPEAT_LOCK:
            bans = _BANS.setdefault(key, OrderedDict())
            bans[text] = stamp
            while len(bans) > BAN_MAX:
                bans.popitem(last=False)
            _prune_bans(key, now=stamp)
        return True
    except Exception:      # pragma: no cover
        return False


def dynamic_bans_view(chat_id: int, *, now: float | None = None) -> dict:
    """R17-safe вид ban-list (числа/хеши; без фраз) для телеметрии/UI."""
    try:
        key = int(chat_id or 0)
        stamp = float(now if now is not None else time.time())
        with _REPEAT_LOCK:
            _prune_bans(key, now=stamp)
            bans = list((_BANS.get(key) or {}).items())
            archive = list((_BAN_ARCHIVE.get(key) or {}).items())
        return {"active": len(bans), "archived": len(archive),
                "cap": BAN_MAX, "ttl_seconds": BAN_TTL_SECONDS,
                "hashes": [_sha12(gram) for gram, _ts in bans[:10]]}
    except Exception:      # pragma: no cover
        return {"active": 0, "archived": 0, "cap": BAN_MAX,
                "ttl_seconds": BAN_TTL_SECONDS, "hashes": []}


def repetition_view(chat_id: int, *, now: float | None = None) -> dict:
    """R17-safe наблюдаемость окна (для телеметрии/UI, без текста)."""
    try:
        key = int(chat_id or 0)
        stamp = float(now if now is not None else time.time())
        with _REPEAT_LOCK:
            window = list(_REPEAT_WINDOWS.get(key) or ())
        fresh = [row for row in window if stamp - row[0] <= REPEAT_TTL_SECONDS]
        return {"window": len(fresh), "cap": REPEAT_WINDOW_MAX,
                "ttl_seconds": REPEAT_TTL_SECONDS, "ngram_n": NGRAM_N,
                "hashes": [_sha12(row[1]) for row in fresh[-5:]]}
    except Exception:      # pragma: no cover
        return {"window": 0, "cap": REPEAT_WINDOW_MAX,
                "ttl_seconds": REPEAT_TTL_SECONDS, "ngram_n": NGRAM_N,
                "hashes": []}


def reset_repetition_state() -> None:
    """Сброс in-process состояния окна/ban-list (тесты, restart)."""
    with _REPEAT_LOCK:
        _REPEAT_WINDOWS.clear()
        _BANS.clear()
        _BAN_ARCHIVE.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 7. Единый проход нормализации (design-composer-contract §6)
# ═══════════════════════════════════════════════════════════════════════════

#: Инструкция ОДНОГО bounded смыслового ремонта (SOUL-16.4.5). Не цитирует
#: клише и не задаёт новых фактов: только форма (кавычки/точка/эмодзи) при
#: полном сохранении смысла, ссылок, кода и дословных цитат.
STYLE_REPAIR_INSTRUCTION = (
    "Перепиши ответ, сохранив смысл, факты, числа, ссылки, код и дословные "
    "цитаты без изменений. Измени только форму: убери графические кавычки в "
    "обычной речи, передай иронию словами, не ставь точку в самом конце "
    "сообщения, не используй эмодзи. Ничего не добавляй к содержанию.")

_MACHINE_SKIP = ("style_policy_disabled", "style_policy_unavailable",
                 "machine_stage")


def _revision_int(revision: str) -> int | None:
    """Числовая ревизия из строки политики (``g3.ab12`` → 3) или ``None``."""
    match = re.match(r"[gc](\d+)", str(revision or ""))
    return int(match.group(1)) if match else None


def _emit_style_event(outcome: StyleOutcome, *, chat_id: int, stage: str
                      ) -> None:
    """Notable-событие о непроходном исходе (fail-open, R17-safe)."""
    try:
        if outcome.styled and not outcome.repetition:
            return
        from services import mca_events as _events
        status = "failed" if (outcome.failed or outcome.denied) else "skipped"
        if outcome.styled and outcome.repetition:
            status = "success"
        _events.emit_mca_event(
            "style_policy", outcome=status, level="WARN",
            component="style_policy", stage=stage, chat_id=int(chat_id or 0),
            duration_ms=round(float(outcome.elapsed_ms), 3),
            style_revision=_revision_int(outcome.policy_revision),
            usage_json=outcome.as_dict())
    except Exception:      # pragma: no cover - событие не роняет ответ
        logger.warning("[style_policy] event emit failed", exc_info=True)


async def apply_style_policy(text: Any, *, chat_id: int = 0, plan=None,
                             policy: EffectiveStylePolicy | None = None,
                             context: str = "regular",
                             explicit_form: str = "",
                             verbatim: bool = False,
                             extra_protected: Iterable[str] = (),
                             repair=None, repair_allowed: bool = False,
                             record: bool = True, emit_events: bool = False,
                             stage: str = "pre_send") -> StyleOutcome:
    """Единый проход: extent check → правила формы → антизалипание.

    Порядок фиксирован (design-composer-contract §6). Вызывается ДО
    сериализации/отправки; проверка доставленного payload — отдельно
    (:func:`verify_outbound_payload`). Ноль LLM-вызовов; смысловой ремонт —
    не более ОДНОГО и только по переданному ``repair`` (SOUL-16.4.5).
    Никогда не бросает."""
    started = time.perf_counter()
    source = str(text or "")
    result = StyleOutcome(text=source, context=str(context or "regular"))
    try:
        from services import mca_gates
        if not mca_gates.speech_style_policy_enabled():
            result.applied = False
            result.skip_reason = "style_policy_disabled"
            return result
    except Exception:      # pragma: no cover - защитная ветка
        result.applied = False
        result.skip_reason = "style_policy_unavailable"
        return result
    try:
        if policy is None:
            policy = await effective_style_policy(
                chat_id, context=context,
                extent=str(getattr(plan, "extent", "") or ""))
        result.policy_revision = policy.revision or ""
        result.policy_source = policy.source or "default"
        result.policy = policy
        result.plan = plan
        if policy.skip_reason in _MACHINE_SKIP and not policy.rules \
                and not policy.soft_instructions:
            result.applied = False
            result.skip_reason = policy.skip_reason
            return result
        result.applied = True
        result.skip_reason = policy.skip_reason
        # ── 1. extent check (в т.ч. one_word), владелец — response_extent ──
        current = source
        if plan is not None:
            from services import response_extent as _extent
            if _extent.response_plan_enabled():
                spans = segment(current, verbatim=verbatim,
                                extra_protected=extra_protected)
                check = _extent.check_extent(
                    current, plan, explicit_form=explicit_form,
                    ignore_ranges=protected_ranges(spans))
                result.extent = check
                if check.text:
                    current = check.text
        # ── 2. правила формы (детерминированно, локальные безопасные правки) ─
        validator = StylePolicyValidator(
            policy, context=context, verbatim=verbatim,
            extra_protected=extra_protected, plan=plan,
            explicit_form=explicit_form, extent_status=result.extent_status)
        current, results = validator.run(current)
        result.results = results
        # ── 3. ОДИН bounded смысловой ремонт (только при явном callback) ────
        if repair is not None and repair_allowed and _needs_repair(results):
            try:
                repaired_text = await repair(current, STYLE_REPAIR_INSTRUCTION)
            except Exception:
                logger.warning("[style_policy] bounded repair failed",
                               exc_info=True)
                repaired_text = ""
            repaired_text = str(repaired_text or "")
            if repaired_text.strip() and repaired_text != current:
                result.repair_used = 1
                current, results = validator.run(repaired_text)
                result.results = results
                if plan is not None:
                    from services import response_extent as _extent2
                    spans2 = segment(current, verbatim=verbatim,
                                     extra_protected=extra_protected)
                    check2 = _extent2.check_extent(
                        current, plan, explicit_form=explicit_form,
                        ignore_ranges=protected_ranges(spans2))
                    result.extent = check2
                    current = check2.text or current
        # ── 4. антизалипание: наблюдаемо и пропорционально (SOUL-09) ────────
        if chat_id:
            findings = detect_repetition(current, chat_id)
            if findings:
                spans3 = segment(current, verbatim=verbatim,
                                 extra_protected=extra_protected)
                # Локальная замена повтора выполняется только когда у слоя
                # есть владельческая политика (правила/привычки): без неё
                # повтор ТОЛЬКО наблюдается (никакой тихой потери текста,
                # SOUL-09.1 «не наказывать повтор без повода»).
                if policy.rules or policy.soft_instructions:
                    trimmed, removed = _local_repetition_repair(
                        current, findings, spans3)
                    if removed:
                        current = trimmed
                        current, results = validator.run(current)
                        result.results = results
                        findings = tuple(dict(row, repaired=True)
                                         for row in findings)
                result.repetition = findings
            if record and current.strip():
                record_bot_output(chat_id, current)
        result.text = current
    except Exception:      # pragma: no cover - проход не роняет ответ
        logger.warning("[style_policy] pass failed — text unchanged",
                       exc_info=True)
        result.text = source
        result.applied = False
        result.skip_reason = "pass_error"
    result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    if emit_events and chat_id:
        _emit_style_event(result, chat_id=chat_id, stage=stage)
    return result


def _needs_repair(results: Sequence[RuleOutcome]) -> bool:
    """Нужен ли ОДИН bounded смысловой ремонт (конфликт/провал/deny)."""
    return any(row.strictness == "hard"
               and row.status in (STATUS_CONFLICT, STATUS_FAILED, STATUS_DENIED)
               for row in results)


def verify_outbound_payload(payload: Any, *, policy: EffectiveStylePolicy,
                            context: str = "regular", verbatim: bool = False,
                            extra_protected: Iterable[str] = (),
                            plan=None, explicit_form: str = "",
                            outcome: StyleOutcome | None = None) -> StyleOutcome:
    """Проверка ФАКТИЧЕСКИ доставляемого payload (SOUL-16.3.4).

    Выполняется ПОСЛЕ сериализации (escape/parse_mode/разметка) и БЕЗ правок:
    ``repaired`` в этом режиме означает «payload всё ещё нарушает правило» →
    ``conflict``, чтобы нельзя было объявить ``styled=true``. Никогда не
    бросает."""
    text = str(payload or "")
    result = StyleOutcome(text=text, context=str(context or "regular"),
                          payload=True, applied=True)
    try:
        result.policy_revision = policy.revision or ""
        result.policy_source = policy.source or "default"
        result.policy = policy
        validator = StylePolicyValidator(
            policy, context=context, verbatim=verbatim,
            extra_protected=extra_protected,
            plan=getattr(outcome, "plan", None) if outcome is not None
            else plan,
            explicit_form=explicit_form,
            extent_status=str(getattr(outcome, "extent_status", "") or ""))
        _text, results = validator.verify(text)
        result.results = results
        if plan is not None:
            from services import response_extent as _extent
            spans = segment(text, verbatim=verbatim,
                            extra_protected=extra_protected)
            result.extent = _extent.check_extent(
                text, plan, explicit_form=explicit_form,
                ignore_ranges=protected_ranges(spans))
        blocking = [row for row in results
                    if row.strictness == "hard"
                    and row.status in BLOCKING_STATUSES]
        if str(getattr(result.extent, "status", "")) in (STATUS_FAILED,
                                                         STATUS_CONFLICT):
            blocking.append(RuleOutcome(
                rule_id="extent.check", kind="extent", strictness="hard",
                status=str(result.extent.status),
                reason=str(result.extent.reason),
                source="l1"))
        result.payload_status = "mismatch" if blocking else "ok"
    except Exception:      # pragma: no cover - проверка не роняет доставку
        logger.warning("[style_policy] payload verify failed", exc_info=True)
        result.payload_status = "unknown"
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 8. Запись документа (owner API; UI — W6) и витрина реестра правил
# ═══════════════════════════════════════════════════════════════════════════

async def save_policy_document(document: Mapping[str, Any], *,
                               chat_id: int | None = None, cache=None,
                               actor: Any = None, reason: str = "",
                               expected_updated_at: str | None = None,
                               pg=None, get_root=None, set_root=None) -> dict:
    """Записать документ политики (глобально или per-chat) через существующие
    слои: ``ConfigCache``/``bot_settings`` либо ``chat_params.overrides``.

    Ревизия инкрементируется, предыдущая редакция уходит в bounded ``history``
    (SOUL-16.1.4: revision/created_at/updated_at/history). Никакого второго
    config service (SOUL-15.1). Никогда не бросает."""
    try:
        normalized, issues = validate_document(document)
        if not normalized:
            return {"applied": False, "reason": "document_invalid",
                    "issues": list(issues)}
        previous_doc: dict = {}
        if chat_id is not None:
            from services import chat_params
            get_root = get_root or chat_params.get_all_chat_params
            set_root = set_root or (lambda chat, patch, **kw:
                                    chat_params.set_chat_params(chat, patch,
                                                                **kw))
            root = await (get_root(int(chat_id), pg=pg) if pg is not None
                          else get_root(int(chat_id)))
            overrides = dict((root or {}).get("overrides") or {})
            previous_doc, _ = validate_document(overrides.get(DOC_KEY))
        else:
            from services import hot_config as hot
            target = cache if cache is not None else hot.get_config_cache()
            if target is None:
                return {"applied": False, "reason": "config_cache_unavailable"}
            previous_doc, _ = validate_document(target.get(DOC_KEY, None))
        revision = int(previous_doc.get("revision", 0) or 0) + 1
        history = list(previous_doc.get("history") or [])
        if previous_doc:
            history.insert(0, {
                "revision": int(previous_doc.get("revision", 1) or 1),
                "rules_sha256_12": _sha12(previous_doc.get("rules") or []),
                "updated_at": previous_doc.get("updated_at") or "",
                "updated_by": previous_doc.get("updated_by"),
            })
        normalized["revision"] = revision
        normalized["history"] = history[:HISTORY_MAX]
        normalized["updated_at"] = _now_iso()
        normalized["updated_by"] = actor
        normalized["reason"] = str(reason or normalized.get("reason") or "")
        if chat_id is not None:
            overrides[DOC_KEY] = normalized
            patch = {"overrides": overrides}
            if pg is not None and expected_updated_at is not None:
                await set_root(int(chat_id), patch, pg=pg,
                               expected_updated_at=expected_updated_at)
            elif pg is not None:
                await set_root(int(chat_id), patch, pg=pg)
            else:
                await set_root(int(chat_id), patch)
            scope = "chat"
        else:
            # ConfigCache.set — async (services/config_cache.py:681); без
            # await документ отдавался как applied=true, но не персистился
            # (релиз 2.58.86: POST /api/speech/style scope=global).
            await target.set(DOC_KEY, normalized, category=DOC_CATEGORY)
            scope = "global"
        logger.info("[style_policy] document saved | scope=%s | revision=%d | "
                    "rules=%d | soft=%d", scope, revision,
                    len(normalized.get("rules") or []),
                    len(normalized.get("soft_instructions") or []))
        return {"applied": True, "scope": scope, "revision": revision,
                "rules": len(normalized.get("rules") or []),
                "soft_instructions": len(
                    normalized.get("soft_instructions") or []),
                "issues": list(issues)}
    except Exception:
        logger.warning("[style_policy] document save failed", exc_info=True)
        return {"applied": False, "reason": "save_error"}


async def reset_chat_policy(chat_id: int, *, pg=None, get_root=None,
                            set_root=None,
                            expected_updated_at: str | None = None) -> dict:
    """«Сбросить для чата»: возврат к наследованию глобальной политики.

    Это НЕ заводской сброс глобального документа (SOUL-AMD.4.3): глобальный
    слой не изменяется. Никогда не бросает."""
    try:
        from services import chat_params
        get_root = get_root or chat_params.get_all_chat_params
        set_root = set_root or (lambda chat, patch, **kw:
                                chat_params.set_chat_params(chat, patch, **kw))
        root = await (get_root(int(chat_id), pg=pg) if pg is not None
                      else get_root(int(chat_id)))
        overrides = dict((root or {}).get("overrides") or {})
        if DOC_KEY not in overrides:
            return {"applied": False, "reason": "no_chat_override",
                    "chat_id": int(chat_id)}
        overrides.pop(DOC_KEY, None)
        patch = {"overrides": overrides}
        if pg is not None and expected_updated_at is not None:
            await set_root(int(chat_id), patch, pg=pg,
                           expected_updated_at=expected_updated_at)
        elif pg is not None:
            await set_root(int(chat_id), patch, pg=pg)
        else:
            await set_root(int(chat_id), patch)
        return {"applied": True, "chat_id": int(chat_id),
                "inherits": "global"}
    except Exception:
        logger.warning("[style_policy] chat reset failed", exc_info=True)
        return {"applied": False, "reason": "reset_error"}


def style_policy_view(global_doc: Any = None, chat_doc: Any = None, *,
                      context: str = "regular", extent: str = "",
                      enabled: bool = True) -> dict:
    """Витрина для UI/Inspector (W6): правила, источники, шаблоны, причины.

    Содержит ровно то, что нужно редактору «Стиль письма»: активные правила с
    источником, soft-привычки, доступные presets, каталог kind, диагностику
    документа, конфликты и (R17-safe) эффективную ревизию. Никогда не
    бросает."""
    try:
        policy = effective_policy_sync(global_doc, chat_doc, context=context,
                                      extent=extent, enabled=enabled)
        glob_doc, glob_issues = validate_document(global_doc)
        chat_doc_n, chat_issues = validate_document(chat_doc)
        return {
            "key": DOC_KEY, "category": DOC_CATEGORY,
            "context": policy.context, "source": policy.source,
            "revision": policy.revision,
            "presets_applied": list(policy.presets_applied),
            "available_presets": [
                {"id": name, "title_ru": spec["title_ru"],
                 "description": spec["description"],
                 "rules": len(spec.get("rules") or ()),
                 "soft_instructions": len(spec.get("soft_instructions") or ())}
                for name, spec in PRESET_SPECS.items()],
            "rule_kinds": [{"kind": kind, **RULE_KIND_SPECS.get(kind, {})}
                           for kind in RULE_KINDS],
            "rules": [r.as_dict() for r in policy.rules],
            "soft_instructions": [s.as_dict()
                                  for s in policy.soft_instructions],
            "hard_kinds": list(policy.hard_kinds),
            "soft_kinds": list(policy.soft_kinds),
            "skip_reason": policy.skip_reason,
            "conflicts": list(policy.conflicts),
            "document": {
                "global_present": bool(glob_doc),
                "chat_present": bool(chat_doc_n),
                "global_issues": list(glob_issues),
                "chat_issues": list(chat_issues),
                "global_revision": int(glob_doc.get("revision", 0) or 0),
                "chat_revision": int(chat_doc_n.get("revision", 0) or 0),
                "inheritance": ("chat" if chat_doc_n else
                                "global" if glob_doc else "factory_default"),
            },
            "hint": policy.hint, "hint_tokens": policy.hint_tokens,
            "precedence": list(PRECEDENCE),
            "statuses": list(STATUSES),
        }
    except Exception:
        logger.warning("[style_policy] view failed", exc_info=True)
        return {"key": DOC_KEY, "category": DOC_CATEGORY, "rules": [],
                "soft_instructions": [], "available_presets": [],
                "rule_kinds": [], "skip_reason": "view_error",
                "conflicts": ["view_error"], "document": {},
                "hint": "", "hint_tokens": 0,
                "precedence": list(PRECEDENCE), "statuses": list(STATUSES)}
