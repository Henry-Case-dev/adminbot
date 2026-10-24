"""SOUL-06 (W4) — Humor Craft: управляемый ситуационный слой приёмов.

Границы модуля (requirements-map `.json`/`-amendment.json`, W4):

* **SOUL-06.0** — это НЕ отдельный юморист: приёмы выбирает L1
  (`ResponsePlan.comic_strategy`, §3 SOUL-05), а здесь живёт ровно
  ситуационный слой ремесла, его диагностический toggle и измеримое
  влияние отдельных приёмов.
* **SOUL-06.1–06.5** — пять техник с заводскими редакциями текстов
  (регистрируются в Prompt Registry как `humor.technique.*`).
* **SOUL-06.6** — главный критерий: причинная связность и уместность, а не
  частота мата/метафор/оскорблений; запрещены повторяемые шаблоны ввода и
  финала; серьёзная информация не ломается комическим приёмом.
* **SOUL-06.7** — toggle диагностического выключения Humor Craft с
  сохранением Personality Core; тестируемость отдельных приёмов; **0
  дополнительных LLM-вызовов на обычный ответ** по умолчанию; любая
  дополнительная оценка кандидатов — опциональна, ограничена бюджетом и
  выключена по умолчанию.

Модуль не делает сетевых/LLM-вызовов в основном пути: `est_calls=0`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from services import mca_gates
from services.prompt_composer import HumorStrategy

logger = logging.getLogger(__name__)

#: Версия политики отбора приёмов (трассируемость решения).
HUMOR_CRAFT_POLICY_VERSION = "soul1-w4-craft-1"

#: Закрытый набор техник — совпадает с `direct_l1.COMIC_STRATEGIES`
#: (единственный источник выбора — совет L1, SOUL-05).
TECHNIQUES: tuple[str, ...] = (
    "absurd_escalation", "literalism", "deadpan", "bureaucratic_logic",
    "unexpected_analogy",
)

#: Заголовок приёма (что именно просим у Writer) — НЕ уровень токсичности.
TECHNIQUE_TITLES: dict[str, str] = {
    "absurd_escalation": "Абсурдная эскалация",
    "literalism": "Буквализм",
    "deadpan": "Сухой deadpan",
    "bureaucratic_logic": "Бюрократический/экономический перенос",
    "unexpected_analogy": "Неожиданная, но содержательная аналогия",
}

# ── Заводские редакции приёмов (Factory Defaults, SOUL-AMD.4.1) ─────────────
# Требования к тексту (SOUL-06.1–06.6): описан МЕХАНИЗМ приёма, нет требования
# частоты, нет предписания материться/оскорблять, нет шаблонных финалов.

HUMOR_TECHNIQUE_ABSURD_ESCALATION = (
    "<Humor_Technique name=\"absurd_escalation\">\n"
    "Прими предпосылку собеседника как правило вымышленного мира и покажи "
    "одно-два следствия, которые логично из неё вытекают.\n"
    "</Humor_Technique>"
)

HUMOR_TECHNIQUE_LITERALISM = (
    "<Humor_Technique name=\"literalism\">\n"
    "Пойми метафору, оговорку или фигуру речи буквально и покажи, что из "
    "этого следует.\n"
    "</Humor_Technique>"
)

HUMOR_TECHNIQUE_DEADPAN = (
    "<Humor_Technique name=\"deadpan\">\n"
    "Скажи нелепую вещь спокойно, как обыденный факт, без восклицаний. "
    "Ничего не объясняй и не подсказывай, что это шутка.\n"
    "</Humor_Technique>"
)

HUMOR_TECHNIQUE_BUREAUCRATIC_LOGIC = (
    "<Humor_Technique name=\"bureaucratic_logic\">\n"
    "Разбери бытовую ситуацию как процедуру или отчёт: кто заявитель, какие "
    "сроки, что считается исполнением.\n"
    "</Humor_Technique>"
)

HUMOR_TECHNIQUE_UNEXPECTED_ANALOGY = (
    "<Humor_Technique name=\"unexpected_analogy\">\n"
    "Свяжи ситуацию с отдалённой областью через конкретную деталь, чтобы "
    "связь объясняла исходную ситуацию.\n"
    "</Humor_Technique>"
)

#: Заводская редакция по коду техники (единственный источник текста).
TECHNIQUE_TEXTS: dict[str, str] = {
    "absurd_escalation": HUMOR_TECHNIQUE_ABSURD_ESCALATION,
    "literalism": HUMOR_TECHNIQUE_LITERALISM,
    "deadpan": HUMOR_TECHNIQUE_DEADPAN,
    "bureaucratic_logic": HUMOR_TECHNIQUE_BUREAUCRATIC_LOGIC,
    "unexpected_analogy": HUMOR_TECHNIQUE_UNEXPECTED_ANALOGY,
}

#: Общая рамка слоя (главный критерий и границы ремесла, SOUL-06.6).
HUMOR_CRAFT_GUARD = (
    "<Humor_Craft>\n"
    "Приём уместен, только если ситуация располагает. Не растягивай шутку. "
    "Не объясняй шутку и не называй приём. Факты, числа, ссылки и суть "
    "просьбы неприкосновенны.\n"
    "</Humor_Craft>"
)

#: Запрещённые шаблонные финалы/зачины (SOUL-06.6) — проверяются тестом и
#: валидатором приёма (не отдельным LLM-вызовом).
BANNED_TEMPLATES: tuple[str, ...] = (
    "нет ты", "классика жанра", "это как если бы", "это как будто бы",
    "вот это поворот",
)

#: Границы объёма слоя (bounded; не вытесняет вопрос/evidence/Core).
MAX_LAYER_CHARS = 800
MAX_LAYER_TOKENS = 220

#: Профили/структуры, где комический приём выключается (серьёзный контекст).
SERIOUS_STRUCTURES = frozenset({"report", "code", "structured", "data"})
SERIOUS_TONES = frozenset({"serious", "dry", "neutral"})
#: Extent-режимы, где приём звучит уместно (SOUL-06.6 «серьёзное не ломаем»).
DEADPAN_ONLY_EXTENTS = frozenset({"one_word", "micro"})

#: Опциональная оценка кандидатов (SOUL-06.7): выключена по умолчанию,
#: ограничена бюджетом и отдельно измеряется.
CANDIDATE_EVAL_MAX_CANDIDATES = 2
CANDIDATE_EVAL_MAX_CALLS = 1
CANDIDATE_EVAL_TIMEOUT_S = 20.0

# ── Документ владельца `humor.craft` (bot_settings/chat_params) ─────────────
HUMOR_CRAFT_DOC_KEY = "humor.craft"
HUMOR_CRAFT_DOC_CATEGORY = "content"


# ═══════════════════════════════════════════════════════════════════════════
# Резолв настроек (никогда не бросает)
# ═══════════════════════════════════════════════════════════════════════════


def _as_document(raw: Any) -> dict:
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


async def _read_doc(chat_id: int | None) -> tuple[dict, str]:
    """(документ, источник): chat override → global → default."""
    chat_doc: dict = {}
    global_doc: dict = {}
    if chat_id:
        try:
            from services.chat_params import get_chat_params_cache
            cache = get_chat_params_cache()
            if cache is not None:
                root = await cache.get_chat_params(int(chat_id))
                if isinstance(root, Mapping):
                    chat_doc = _as_document(
                        (root.get("overrides") or {}).get(HUMOR_CRAFT_DOC_KEY))
        except Exception:
            chat_doc = {}
    try:
        from services import hot_config as hot
        global_doc = _as_document(hot.get(HUMOR_CRAFT_DOC_KEY, None))
    except Exception:
        global_doc = {}
    if chat_doc:
        return chat_doc, "chat"
    if global_doc:
        return global_doc, "global"
    return {}, "default"


@dataclass(frozen=True)
class CraftConfig:
    """Действующая конфигурация ремесла (виден источник значения)."""

    enabled: bool = True
    disabled_techniques: tuple[str, ...] = ()
    source: str = "default"
    revision: int = 0

    def technique_enabled(self, technique: str) -> bool:
        if not self.enabled:
            return False
        return str(technique) not in self.disabled_techniques


async def resolve_config(chat_id: int | None = None) -> CraftConfig:
    """Действующие настройки ремесла (chat → global → default). Fail-open."""
    try:
        doc, source = await _read_doc(chat_id)
    except Exception:                      # pragma: no cover — защитная ветка
        return CraftConfig(source="default")
    disabled: list[str] = []
    raw = doc.get("disabled_techniques")
    if isinstance(raw, (list, tuple)):
        disabled = [str(t) for t in raw if str(t) in TECHNIQUES]
    try:
        revision = int(doc.get("revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    if not doc:
        return CraftConfig(source="default")
    return CraftConfig(enabled=bool(doc.get("enabled", True)),
                       disabled_techniques=tuple(sorted(set(disabled))),
                       source=source, revision=revision)


def gate_on() -> bool:
    """Env+каталоговая ось `HUMOR_CRAFT_ENABLED` (default OFF)."""
    try:
        return bool(mca_gates.humor_craft_enabled())
    except Exception:                      # pragma: no cover
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Отбор приёма (детерминированный; 0 LLM)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TechniqueDecision:
    """Решение по приёму с честной причиной (для манифеста/UI)."""

    technique: str = ""
    reason: str = ""
    candidates_evaluated: int = 0
    extra_llm_calls: int = 0


def _serious_context(structure: str, tone: str) -> bool:
    return (str(structure or "") in SERIOUS_STRUCTURES
            or str(tone or "") in SERIOUS_TONES)


def select_technique(*, comic_strategy: str, extent: str = "",
                     structure: str = "", tone: str = "",
                     config: CraftConfig | None = None,
                     context_weight: float = 1.0) -> TechniqueDecision:
    """Выбрать приём по совету L1 с учётом уместности и контекста.

    ``context_weight`` — вес стратегии В ЭТОМ чате из контура обратной связи
    (SOUL-08: отрицательная обратная связь ослабляет стратегию в контексте).
    Никогда не включает приём, которого не советовал L1.
    """
    cfg = config or CraftConfig()
    strategy = str(comic_strategy or "")
    if not strategy or strategy == "none":
        return TechniqueDecision(reason="humor_no_strategy")
    if strategy not in TECHNIQUES:
        return TechniqueDecision(reason="humor_unknown_strategy")
    if not cfg.technique_enabled(strategy):
        return TechniqueDecision(reason="humor_disabled")
    if _serious_context(structure, tone):
        return TechniqueDecision(reason="humor_serious_context")
    extent = str(extent or "")
    if extent in DEADPAN_ONLY_EXTENTS and strategy != "deadpan":
        # Короткая форма: длинная эскалация ломает контракт объёма.
        return TechniqueDecision(reason="humor_extent_fit")
    try:
        weight = float(context_weight)
    except (TypeError, ValueError):
        weight = 1.0
    if weight <= 0.05:
        return TechniqueDecision(reason="humor_context_penalty")
    return TechniqueDecision(technique=strategy,
                             reason="humor_strategy:" + strategy)


# ═══════════════════════════════════════════════════════════════════════════
# Рендер слоя
# ═══════════════════════════════════════════════════════════════════════════


def technique_text(technique: str) -> str:
    """Заводская редакция техники (пусто — неизвестная техника)."""
    return str(TECHNIQUE_TEXTS.get(str(technique), ""))


def render_layer(technique: str, *, guard: str | None = None,
                 text: str | None = None) -> str:
    """Общая рамка + текст приёма (bounded, без дублей)."""
    body = str(text if text is not None else technique_text(technique)).strip()
    if not body:
        return ""
    frame = str(HUMOR_CRAFT_GUARD if guard is None else guard).strip()
    layer = f"{frame}\n{body}" if frame else body
    return layer[:MAX_LAYER_CHARS]


def layer_calls(technique: str) -> int:
    """Дополнительные LLM-вызовы основного пути: всегда 0 (SOUL-06.7)."""
    return 0 if technique else 0


def accepts_output(text: str) -> tuple[bool, str]:
    """Проверка готового текста на запрещённые шаблоны (детерминированная).

    Возврат ``(ok, reason)``: ``reason == ""`` — чисто; иначе код причины.
    Используется диагностикой/UI; Writer не переписывается вторым LLM.
    """
    body = str(text or "").casefold()
    if not body.strip():
        return True, ""
    for template in BANNED_TEMPLATES:
        if template in body:
            return False, "humor_template_repeat:" + template.replace(" ", "_")
    return True, ""


# ═══════════════════════════════════════════════════════════════════════════
# Провайдер слоя для композера (шов JB-2)
# ═══════════════════════════════════════════════════════════════════════════


async def resolve_ref(*, chat_id: int, comic_strategy: str, extent: str = "",
                      structure: str = "", tone: str = "",
                      context_weight: float = 1.0
                      ) -> HumorStrategy | None:
    """`HumorStrategy` для композера или None (слой не рендерится).

    Гейт OFF / toggle владельца OFF / несоветованный приём → None с честной
    причиной в ``skip_reason``. Никаких LLM-вызовов.
    """
    if not gate_on():
        return HumorStrategy(skip_reason="humor_disabled", enabled=False,
                             source="library")
    cfg = await resolve_config(chat_id)
    decision = select_technique(comic_strategy=comic_strategy, extent=extent,
                                structure=structure, tone=tone, config=cfg,
                                context_weight=context_weight)
    if not decision.technique:
        return HumorStrategy(skip_reason=decision.reason, enabled=False,
                             source=str(cfg.source or "default"))
    layer = render_layer(decision.technique)
    if not layer.strip():
        return HumorStrategy(skip_reason="humor_no_strategy", enabled=False,
                             source=str(cfg.source or "default"))
    from services.prompt_registry import sha12
    return HumorStrategy(
        text=layer, technique=decision.technique,
        revision=sha12(layer), source=str(cfg.source or "default"),
        enabled=True)


# ═══════════════════════════════════════════════════════════════════════════
# Диагностика и тестируемость приёмов (SOUL-06.7; 0 LLM)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TechniqueProbe:
    """Измеримое влияние приёма: что именно уйдёт в слой и чем он отличается."""

    technique: str
    title: str
    enabled: bool
    layer_chars: int = 0
    layer_tokens: int = 0
    layer_revision: str = ""
    reason: str = ""
    detail: list[str] = field(default_factory=list)


def probe_technique(technique: str, *, config: CraftConfig | None = None,
                    comic_strategy: str = "") -> TechniqueProbe:
    """Проверка ОДНОГО приёма: точный слой, версия, объём, причина отказа."""
    cfg = config or CraftConfig()
    title = TECHNIQUE_TITLES.get(str(technique), str(technique))
    if str(technique) not in TECHNIQUES:
        return TechniqueProbe(technique=str(technique), title=title,
                              enabled=False, reason="humor_unknown_strategy")
    if not cfg.technique_enabled(str(technique)):
        return TechniqueProbe(technique=str(technique), title=title,
                              enabled=False, reason="humor_disabled")
    layer = render_layer(str(technique))
    from services.prompt_composer import estimate_tokens
    from services.prompt_registry import sha12
    decision = select_technique(comic_strategy=(comic_strategy
                                                or str(technique)),
                                config=cfg)
    detail = [f"policy={HUMOR_CRAFT_POLICY_VERSION}",
              f"source={cfg.source}",
              f"gate={'on' if gate_on() else 'off'}",
              f"selection={decision.reason}",
              f"llm_calls={layer_calls(technique)}"]
    return TechniqueProbe(
        technique=str(technique), title=title, enabled=True,
        layer_chars=len(layer), layer_tokens=estimate_tokens(layer),
        layer_revision=sha12(layer), reason="", detail=detail)


def technique_catalog(config: CraftConfig | None = None) -> list[dict]:
    """Все приёмы с реальным состоянием (для раздела «Юмор»)."""
    cfg = config or CraftConfig()
    out: list[dict] = []
    for technique in TECHNIQUES:
        probe = probe_technique(technique, config=cfg)
        out.append({
            "id": technique, "title": probe.title,
            "enabled": bool(probe.enabled and gate_on()),
            "owner_enabled": bool(cfg.technique_enabled(technique)),
            "layer_chars": probe.layer_chars,
            "layer_tokens": probe.layer_tokens,
            "layer_revision": probe.layer_revision,
            "reason": probe.reason or "humor_ready",
            "gate": bool(gate_on()),
            "source": cfg.source,
            "detail": list(probe.detail),
        })
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Опциональная оценка кандидатов (SOUL-06.7): OFF по умолчанию
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CandidateEvalResult:
    """Результат опциональной оценки: честно, сколько вызовов потрачено."""

    applied: bool = False
    reason: str = ""
    calls: int = 0
    candidates: tuple[str, ...] = ()


async def evaluate_candidates(*, candidates: Sequence[str], chat_id: int = 0,
                              llm=None) -> CandidateEvalResult:
    """Опциональный отбор лучшего кандидата (default OFF, bounded).

    Включён только при ``HUMOR_CANDIDATE_EVAL_ENABLED`` (env+каталог) и
    переданном ``llm``. Строго ограничен: ≤2 кандидата, ≤1 вызов, таймаут,
    при любой ошибке — honest no-op (ответ уже готов, ветка диагностическая).
    """
    items = [str(c) for c in (candidates or ()) if str(c).strip()]
    if not mca_gates.humor_candidate_eval_enabled():
        return CandidateEvalResult(reason="candidate_eval_disabled")
    if llm is None:
        return CandidateEvalResult(reason="candidate_eval_no_llm")
    if len(items) < 2:
        return CandidateEvalResult(reason="candidate_eval_single")
    picked = items[:CANDIDATE_EVAL_MAX_CANDIDATES]
    try:
        import asyncio as _asyncio
        prompt = ("Выбери вариант с причинной связностью и уместностью, без "
                  "оценки частоты мата.\n" + "\n---\n".join(picked))
        await _asyncio.wait_for(
            llm.generate([{"role": "user", "content": prompt}],
                         temperature=0.0, module="humor",
                         step="candidate_eval", max_output_tokens=64),
            timeout=CANDIDATE_EVAL_TIMEOUT_S)
    except Exception:
        logger.warning("[humor] candidate eval failed (ignored)", exc_info=True)
        return CandidateEvalResult(reason="candidate_eval_error",
                                   calls=CANDIDATE_EVAL_MAX_CALLS,
                                   candidates=tuple(picked))
    return CandidateEvalResult(applied=True, reason="candidate_eval_applied",
                               calls=CANDIDATE_EVAL_MAX_CALLS,
                               candidates=tuple(picked))
