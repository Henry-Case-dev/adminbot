"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D5; spec §3.8/§19–§21,
§53/§57/§58) — Image Prompt Compiler + CoverBrief.

Compiler собирает prompt из компонент §19 под capability выбранной модели,
**priority-aware** (§20): P0 (runtime invariants + issue number) не режется
случайным `text[:N]`; при pressure сначала сокращается P2.

`CoverBrief` (§21) — компактный сюжет вместо полной Summary-prose. Summary-pipeline
не знает конкретные prompt-limits image-provider.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from services.image_capabilities import (
    UNIT_BYTES,
    UNIT_TOKENS,
    ImageModelCapabilities,
)

logger = logging.getLogger(__name__)

# Приоритеты компонент (spec §3/D3 P0–P3).
P0 = 0   # обязательная механика edit — НИКОГДА не режется
P1 = 1   # сущность стиля/бренд — НИКОГДА не режется строковыми ножницами
P2 = 2   # ключевые детали Summary (сжимаются в semantic brief)
P3 = 3   # декоративные hints (режутся первыми)


def semantic_compression_enabled() -> bool:
    """Kill-switch `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED` (T-4815; env-only,
    default ON). OFF → прежний 3-уровневый алгоритм байт-в-байт."""
    try:
        from config.settings import settings
        return bool(getattr(settings, "IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


@dataclass
class PromptComponent:
    """Одна компонента prompt с приоритетом (§19/§20)."""

    text: str
    priority: int = P1
    label: str = ""

    def __post_init__(self):
        self.text = str(self.text or "").strip()


@dataclass
class CoverBrief:
    """Компактное представление сюжета обложки (§21)."""

    scene: str = ""
    mood: str = ""
    subjects: list[str] = field(default_factory=list)
    callouts: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.scene or self.mood or self.subjects or self.callouts)

    def render(self, *, max_chars: int | None = None) -> str:
        """Собрать компактный текст; при `max_chars` — обрезать сюжетную часть.

        CoverBrief — P1-компонента: при давлении сжимается (но не ниже
        осмысленного минимума), не ломая P0.
        """
        parts: list[str] = []
        if self.scene:
            parts.append(f"Сюжет: {self.scene}")
        if self.mood:
            parts.append(f"Настроение: {self.mood}")
        if self.subjects:
            parts.append("Персонажи/объекты: " + ", ".join(self.subjects))
        if self.callouts:
            parts.append("Выноски: " + "; ".join(self.callouts))
        text = " ".join(parts)
        if max_chars is not None and max_chars >= 0 and len(text) > max_chars:
            # Обрезаем по границе слова (не рвём середину слова), это P1 — можно.
            cut = text[:max_chars].rsplit(" ", 1)[0].strip()
            return cut
        return text


@dataclass
class CompiledPrompt:
    """Результат компиляции: prompt + метрики для budget indicator (§57).

    ASAP 4.2 Step 2c-1 (T-4816): `original_len`/`resolved_limit` — Inspector
    `Original N / Resolved limit M / Compiled K`; `exceeded`/`reason` —
    first-class `prompt_limit_exceeded` (P0+P1 не влезли → Base Cover)."""

    prompt: str
    static_len: int = 0
    reserve_len: int = 0
    scene_allowance: int = 0
    limit: int | None = None
    unit: str = "unknown"
    dropped: list[str] = field(default_factory=list)
    original_len: int = 0
    resolved_limit: int | None = None
    exceeded: bool = False
    reason: str = ""
    # ASAP 4.3 (§9, T-4849): безопасный breakdown компонент для UI
    # (`label → units`) — Style/Context/Refs/System без полного prompt.
    components: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "static_len": self.static_len,
            "reserve_len": self.reserve_len,
            "scene_allowance": self.scene_allowance,
            "limit": self.limit,
            "unit": self.unit,
            "dropped": list(self.dropped),
            "original_len": self.original_len,
            "resolved_limit": self.resolved_limit,
            "exceeded": self.exceeded,
            "reason": self.reason,
            "components": dict(self.components),
        }


def _component_lens(components: list[PromptComponent], unit: str, *,
                    brief: str = "") -> dict:
    """Длины компонент по label (для budget breakdown §9)."""
    out: dict = {}
    for comp in components:
        if comp.text:
            out[comp.label or ("p%d" % comp.priority)] = \
                _units_of(comp.text, unit)
    if brief:
        out["cover_brief"] = _units_of(brief, unit)
    return out


def brief_from_text(text: str | None, *, max_chars: int = 400) -> CoverBrief:
    """Собрать компактный `CoverBrief` из Summary-prose (§19/§21).

    Deterministic, без LLM/сети: первое содержательное предложение prose как
    сцена обложки; при отсутствии текста — пустой brief. Компактнее полной
    prose; Summary-pipeline не знает prompt-limits image-provider.
    """
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return CoverBrief()
    match = re.search(r"^(.+?[.!?])(\s|$)", raw)
    scene = match.group(1).strip() if match else raw
    if max_chars and len(scene) > max_chars:
        scene = scene[:max_chars].rsplit(" ", 1)[0].strip()
    return CoverBrief(scene=scene)


def _units_of(text: str, unit: str) -> int:
    """Длина текста в единицах capability (§18): chars/bytes/tokens/unknown.

    tokens — приблизительный estimator (не грубый фиксированный пересчёт);
    unknown → измеряем в chars для внутренней арифметики давления.
    """
    if unit == UNIT_BYTES:
        return len(text.encode("utf-8"))
    if unit == UNIT_TOKENS:
        # Мягкий estimator: ~4 символа/токен + словоразрывы. Не «грубый перевод»
        # ради UI-цифры, а консервативная оценка для давления.
        return max(1, int(len(text) / 4) + text.count(" "))
    return len(text)     # chars / unknown → символы


def _join(components: list[PromptComponent]) -> str:
    return " ".join(c.text for c in components if c.text)


def _compact_semantic_brief(text: str) -> str:
    """P2 → compact semantic brief: только первое смысловое предложение
    (семантическое сжатие, НЕ `[:N]`). Пусто → пусто (P2 опускается)."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return ""
    match = re.search(r"^(.+?[.!?])(\s|$)", raw)
    return (match.group(1) if match else raw).strip()


def compile_prompt(components: list[PromptComponent], *,
                   capabilities: ImageModelCapabilities,
                   budget_component: str = "") -> CompiledPrompt:
    """Собрать prompt под capability модели (spec §3/D3 P0–P3).

    ON `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED`: P0 (механика edit) и P1
    (стиль/бренд) — абсолютный приоритет, НИКОГДА не режутся строковыми
    ножницами; давление снимается сначала с P3, затем P2 → compact semantic
    brief; если P0+P1 не помещаются → `exceeded=True`,
    `reason="prompt_limit_exceeded"` (caller публикует Base Cover).
    OFF → прежний 3-уровневый алгоритм байт-в-байт."""
    if not semantic_compression_enabled():
        return _compile_prompt_legacy(
            components, capabilities=capabilities,
            budget_component=budget_component)
    limit = capabilities.prompt_limit.value
    unit = capabilities.prompt_limit.unit
    known = capabilities.prompt_limit.known and limit is not None
    p0 = [c for c in components if c.priority <= P0 and c.text]
    p1 = [c for c in components if c.priority == P1 and c.text]
    p2 = [c for c in components if c.priority == P2 and c.text]
    p3 = [c for c in components if c.priority == P3 and c.text]
    brief = str(budget_component or "").strip()
    full_parts = (list(p0) + list(p1) + list(p2)
                  + ([PromptComponent(brief, P2, "cover_brief")] if brief
                     else []) + list(p3))
    original_len = _units_of(_join(full_parts), unit)
    dropped: list[str] = []
    if not known:
        prompt = _join(full_parts)
        return CompiledPrompt(
            prompt=prompt, static_len=_units_of(_join(p0 + p1), unit),
            reserve_len=0, scene_allowance=0, limit=None,
            unit=unit or "unknown", dropped=[], original_len=original_len,
            resolved_limit=None, exceeded=False, reason="",
            components=_component_lens(full_parts, unit))
    limit = int(limit)
    required = _join(p0 + p1)
    required_len = _units_of(required, unit)
    static_len = required_len
    if required_len > limit:
        # P0+P1 не влезают — строковые ножницы запрещены; честный overflow.
        return CompiledPrompt(
            prompt=required, static_len=static_len, reserve_len=0,
            scene_allowance=0, limit=limit, unit=unit,
            dropped=[c.label or c.text[:24] for c in (p2 + p3)],
            original_len=original_len, resolved_limit=limit, exceeded=True,
            reason="prompt_limit_exceeded",
            components=_component_lens(full_parts, unit))
    working = required
    # P2 (explicit) — добавляем по возможности целиком; иначе semantic brief.
    for comp in p2:
        trial = (working + " " + comp.text).strip()
        if _units_of(trial, unit) <= limit:
            working = trial
        else:
            dropped.append(comp.label or comp.text[:24])
    if brief:
        trial = (working + " " + brief).strip()
        if _units_of(trial, unit) <= limit:
            working = trial
        else:
            compact = _compact_semantic_brief(brief)
            trial2 = (working + " " + compact).strip() if compact else working
            if compact and _units_of(trial2, unit) <= limit:
                working = trial2
            else:
                dropped.append("cover_brief")
    # P3 — декоративные, при давлении первыми.
    for comp in p3:
        trial = (working + " " + comp.text).strip()
        if _units_of(trial, unit) <= limit:
            working = trial
        else:
            dropped.append(comp.label or comp.text[:24])
    scene_allowance = max(0, limit - _units_of(working, unit))
    return CompiledPrompt(
        prompt=working, static_len=static_len, reserve_len=0,
        scene_allowance=scene_allowance, limit=limit, unit=unit,
        dropped=dropped, original_len=original_len, resolved_limit=limit,
        exceeded=False, reason="",
        components=_component_lens(full_parts, unit))


def _compile_prompt_legacy(components: list[PromptComponent], *,
                           capabilities: ImageModelCapabilities,
                           budget_component: str = "") -> CompiledPrompt:
    """OFF-контур `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED=false`
    (байт-в-байт 2.58.47): P0+P1 static, P2 режется первым."""
    limit = capabilities.prompt_limit.value
    unit = capabilities.prompt_limit.unit
    static = [c for c in components if c.priority <= P1 and c.text]
    p2 = [c for c in components if c.priority == P2 and c.text]

    static_len = _units_of(_join(static), unit)
    reserve_len = _units_of(budget_component, unit) if budget_component else 0
    dropped: list[str] = []

    if limit is None or not capabilities.prompt_limit.known:
        compiled = _join(static + p2)
        if budget_component:
            compiled = (compiled + " " + budget_component).strip()
        return CompiledPrompt(
            prompt=compiled, static_len=static_len, reserve_len=reserve_len,
            scene_allowance=0, limit=None, unit="unknown", dropped=[])

    limit = int(limit)
    working = list(static)
    for comp in reversed(p2):
        trial = working + p2
        if _units_of(_join(trial), unit) + reserve_len <= limit:
            break
        p2 = [c for c in p2 if c is not comp]
        dropped.append(comp.label or comp.text[:24])

    base_text = _join(working + p2)
    used = _units_of(base_text, unit) + reserve_len
    scene_allowance = max(0, limit - used)

    if budget_component:
        scene = budget_component
        if _units_of(scene, unit) > scene_allowance:
            if unit == "tokens":
                approx = scene_allowance * 4
                scene = scene[:max(0, approx)].rsplit(" ", 1)[0].strip()
            else:
                scene = scene[:scene_allowance].rsplit(" ", 1)[0].strip()
        base_text = (base_text + " " + scene).strip() if scene else base_text
    elif scene_allowance == 0 and _units_of(base_text, unit) > limit:
        working2 = [c for c in working if c.priority == P0]
        p1 = [c for c in working if c.priority == P1] + p2
        while p1 and _units_of(_join(working2 + p1), unit) > limit:
            dropped.append(p1[-1].label or p1[-1].text[:24])
            p1.pop()
        base_text = _join(working2 + p1)

    return CompiledPrompt(
        prompt=base_text, static_len=static_len, reserve_len=reserve_len,
        scene_allowance=scene_allowance, limit=limit, unit=unit,
        dropped=dropped, original_len=static_len + reserve_len,
        resolved_limit=limit, exceeded=False, reason="",
        components=_component_lens(components, unit, brief=budget_component))


def estimate_budget(components: list[PromptComponent], *,
                    capabilities: ImageModelCapabilities,
                    reserve_text: str = "") -> dict:
    """Estimate для budget indicator (§57): статика / reserve / запас сюжета.

    При неизвестном лимите — без ложных чисел (§57/§58).
    """
    limit = capabilities.prompt_limit.value
    unit = capabilities.prompt_limit.unit
    static_len = _units_of(_join([c for c in components if c.text]), unit)
    reserve = _units_of(reserve_text, unit) if reserve_text else 0
    if limit is None or not capabilities.prompt_limit.known:
        return {"known": False, "static": static_len, "reserve": reserve,
                "scene_allowance": None, "unit": unit}
    scene = max(0, int(limit) - static_len - reserve)
    return {"known": True, "static": static_len, "reserve": reserve,
            "scene_allowance": scene, "unit": unit,
            "limit": int(limit)}
