"""ASAP 5 (asap5-final-fixes, D7/D8/D9; T-5249/T-5250/T-5251) — Cover Prompt Assembly.

Единая server-side сборка cover-промптов (Base Generation + Style Edit) и
``CoverPromptManifest`` — один источник истины для всех трёх представлений
(spec §10A.1: отдельная frontend-сборка «preview prompt» запрещена).

SERIALIZE-1 (spec §4, D8): сборка cover-промпта ВЫНЕСЕНА из
``services/summary_generator.py`` сюда бит-в-бит; в summary_generator остаются
импортируемые shim-имена (join-инвариант для тестов 10.23–10.25 и
``web/api/summary_test.py``). После этого ленда B2 сам summary_generator не
трогает; B1 владеет своими функциями этого файла.

Контракты:
* D8 — Base = BASE_STYLE + STORY_SCENE (minimum budget: стиль не вытесняет
  сюжет) + SUMMARY_CONTEXT (bounded representation финального approved
  Summary: title + главные события; без нового LLM-call);
* D9 — story-minimum = 160 chars или 100% оригинала, если короче; profile
  identity ≥ 50% instruction; ``minimal=True`` (P0+style, потеря сюжета)
  запрещён — вместо него bounded semantic squeeze;
* D7 — ``CoverPromptManifest``: компоненты с source/priority/original/sent/
  status kept|compacted|omitted/reason + provider/model/route/operation/
  resolved_limit/limit_unit/limit_source/final_prompt/final_chars/
  prompt_hash (sha256[:16]) и массив attempts (обе фактические строки).
  Полный prompt НЕ попадает в generic server log; чтение — только
  admin-authorized API (fail-closed: ``manifest_public`` без явного
  разрешения отдаёт только числа/enum).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from config.settings import settings
from services.summary_prompts import SUMMARY_COVER_STYLE_DEFAULT  # re-export

# ── D9: обязательные минимумы Style Edit при любом retry ────────────────────

STORY_MIN_CHARS = 160
PROFILE_IDENTITY_MIN_RATIO = 0.5
# D8: bounded representation финального Summary для SUMMARY_CONTEXT.
SUMMARY_CONTEXT_MAX_CHARS = 400

MANIFEST_SCHEMA = "cover_prompt_manifest/1"

_WS_RUN_RE = re.compile(r"\s+")
_SENTENCE_END_RE = re.compile(r"^(.+?[.!?])(?:\s|$)")


def prompt_hash(text: str) -> str:
    """Короткий R17-safe хэш промпта (существующая конвенция sha256[:16])."""
    return hashlib.sha256(
        str(text or "").encode("utf-8")).hexdigest()[:16]


def _collapse(text) -> str:
    return _WS_RUN_RE.sub(" ", str(text or "")).strip()


def _cut_at_or_after(raw: str, floor: int) -> str:
    """Срез ``raw`` по границе слова на позиции ≥ ``floor`` (не ниже floor).

    Граница слова ищется ВПЕРЁД от floor — результат гарантированно не короче
    floor; границы нет (одно слово) — режем только по границе, т.е. не режем
    вовсе (minimum — это нижняя граница, больше разрешено)."""
    if len(raw) <= floor:
        return raw
    rest = re.search(r"\s", raw[floor:])
    if rest:
        return raw[:floor + rest.start()].strip()
    return raw.strip()


def _cut_at_or_before(raw: str, cap: int) -> str:
    """Срез ``raw`` по границе слова на позиции ≤ ``cap`` (не выше cap)."""
    if len(raw) <= cap:
        return raw
    cut = raw[:max(0, cap)]
    sp = cut.rfind(" ")
    if sp > 0:
        cut = cut[:sp]
    return cut.strip()


# ── D9: story-minimum и profile identity floor ──────────────────────────────

def story_floor_text(text, min_chars: int = STORY_MIN_CHARS) -> str:
    """D9: story-minimum — 160 chars или 100% оригинала, если короче.

    Сюжет при squeeze режется НЕ ниже минимума (граница слова); оригинал
    короче минимума едет целиком. Никогда не бросает."""
    raw = _collapse(text)
    if not raw or len(raw) <= min_chars:
        return raw
    return _cut_at_or_after(raw, min_chars)


def profile_identity_floor(text,
                           ratio: float = PROFILE_IDENTITY_MIN_RATIO) -> str:
    """D9: minimum profile identity — ≥ ``ratio`` (0.5) текущей instruction.

    Режется по границе слова на позиции ≥ ratio·len; короткие инструкции
    едят целиком. Никогда не бросает."""
    raw = _collapse(text)
    if not raw:
        return ""
    target = max(1, int(len(raw) * float(ratio)))
    if len(raw) <= target:
        return raw
    return _cut_at_or_after(raw, target)


# ── D8: SUMMARY_CONTEXT — bounded representation финального Summary ─────────

def summary_context_text(title, paragraphs=None,
                         max_chars: int = SUMMARY_CONTEXT_MAX_CHARS) -> str:
    """Bounded SUMMARY_CONTEXT от финального approved Summary (0 LLM).

    title + по одному первому предложению абзацев (главные события/участники),
    суммарно ≤ ``max_chars`` по границе слова. Детерминированно, никогда не
    бросает."""
    parts: list[str] = []
    head = _collapse(title)
    if head:
        parts.append(head)
    for para in (paragraphs or ()):
        txt = _collapse(para)
        if not txt:
            continue
        match = _SENTENCE_END_RE.match(txt)
        parts.append(match.group(1).strip() if match else txt)
        if len(" ".join(parts)) >= max_chars:
            break
    text = " ".join(parts)
    if len(text) > max_chars:
        text = _cut_at_or_before(text, max_chars)
    return text


# ── D8: Base Cover prompt contract ──────────────────────────────────────────

def _base_cap(key: str, default: int) -> int:
    try:
        return int(getattr(settings, key, default))
    except (TypeError, ValueError):
        return default


def base_prompt_plan(base_style, story_scene, summary_context, *,
                     style_cap: int | None = None,
                     total_cap: int | None = None,
                     story_min: int = STORY_MIN_CHARS) -> list[dict]:
    """План Base-промпта: BASE_STYLE → STORY_SCENE → SUMMARY_CONTEXT.

    Стиль приоритетен до своего капа (``SUMMARY_COVER_STYLE_MAX_CHARS``),
    общий кап — ``SUMMARY_COVER_PROMPT_MAX_CHARS``; у сюжета ЯВНЫЙ minimum
    budget (D8): если остаток после стиля меньше story-minimum, стиль
    подрезается, чтобы сюжет дошёл. Без контекста план совпадает с прежним
    ``compose_cover_image_prompt(style, story)`` байт-в-бит. Каждый элемент:
    key/source/priority/original_text/sent_text/status/reason."""
    style_cap = _base_cap("SUMMARY_COVER_STYLE_MAX_CHARS", 500) \
        if style_cap is None else int(style_cap)
    total_cap = _base_cap("SUMMARY_COVER_PROMPT_MAX_CHARS", 1000) \
        if total_cap is None else int(total_cap)
    style_cap = max(0, style_cap)
    total_cap = max(0, total_cap)

    s = _collapse(base_style)
    story = _collapse(story_scene)
    ctx = _collapse(summary_context)

    sent_style = s[:style_cap]
    reason_style = "kept"
    if story:
        # D8: story-minimum — стиль не вытесняет сюжет.
        need = min(len(story), max(1, int(story_min)))
        if total_cap - len(sent_style) - 1 < need:
            allowed = max(0, total_cap - need - 1)
            if allowed < len(sent_style):
                sent_style = s[:allowed]
                reason_style = ("compacted:story_minimum"
                                if sent_style else "omitted:story_minimum")
    remaining = total_cap - len(sent_style) - 1
    sent_story = story[:max(0, remaining)] if story else ""
    room = total_cap - len(sent_style) - len(sent_story) \
        - (1 if (sent_style and sent_story) else 0) \
        - (1 if (sent_style or sent_story) else 0)
    sent_ctx = ctx[:max(0, room)] if ctx else ""

    def _status(original: str, sent: str) -> tuple[str, str]:
        if not original:
            return "omitted", "empty"
        if sent == original:
            return "kept", ""
        if sent:
            return "compacted", "cap"
        return "omitted", "cap"

    st_s = _status(s, sent_style)
    st_story = _status(story, sent_story)
    st_ctx = _status(ctx, sent_ctx)
    if reason_style.startswith("compacted") and st_s[0] == "compacted":
        st_s = ("compacted", "story_minimum")
    elif reason_style.startswith("omitted") and not sent_style and s:
        st_s = ("omitted", "story_minimum")

    return [
        {"key": "BASE_STYLE", "source": "settings", "priority": "P1",
         "original_text": s, "sent_text": sent_style,
         "status": st_s[0], "reason": st_s[1]},
        {"key": "STORY_SCENE", "source": "summary_stage1", "priority": "P1",
         "original_text": story, "sent_text": sent_story,
         "status": st_story[0], "reason": st_story[1]},
        {"key": "SUMMARY_CONTEXT", "source": "final_summary", "priority": "P2",
         "original_text": ctx, "sent_text": sent_ctx,
         "status": st_ctx[0], "reason": st_ctx[1]},
    ]


def compose_base_cover_prompt(base_style, story_scene, summary_context, *,
                              style_cap: int | None = None,
                              total_cap: int | None = None,
                              story_min: int = STORY_MIN_CHARS) -> str:
    """Base-промпт из трёх компонент (D8/T-5250): style + story + context."""
    plan = base_prompt_plan(base_style, story_scene, summary_context,
                            style_cap=style_cap, total_cap=total_cap,
                            story_min=story_min)
    return " ".join(p["sent_text"] for p in plan if p["sent_text"])


# ── Extraction (SERIALIZE-1): прежние compose-функции бит-в-бит ─────────────

# Раунд 10.23 (F6, ADR-1023-6): прежний жёсткий кап (историческое имя —
# используется тестами 10.23 как справка). Раунд 10.24 (F12/ADR-1024-4 D2):
# общий кап вынесен в env-only `SUMMARY_COVER_PROMPT_MAX_CHARS` (1000), а
# кап стиля — в `SUMMARY_COVER_STYLE_MAX_CHARS` (500).
COVER_IMAGE_PROMPT_MAX = 300


def compose_cover_image_prompt(style: str | None, cover_prompt: str) -> str:
    """«Стиль обложки» + visual prompt (F12/ADR-1024-4 D2, AMEND 1023-6).

    Стиль сохраняется ПРИОРИТЕТНО (до своего капа
    `SUMMARY_COVER_STYLE_MAX_CHARS`), visual добирает остаток до общего капа
    `SUMMARY_COVER_PROMPT_MAX_CHARS`; при переполнении режется visual, а не
    стиль (инструкция владельца типа «PERMsoc» обязана дойти до модели)."""
    style_cap = int(getattr(settings, "SUMMARY_COVER_STYLE_MAX_CHARS", 500))
    total_cap = int(getattr(settings, "SUMMARY_COVER_PROMPT_MAX_CHARS", 1000))
    s = (style or "").strip()[:max(0, style_cap)]
    remaining = total_cap - len(s) - 1
    v = (cover_prompt or "").strip()[:max(0, remaining)]
    return " ".join(part for part in (s, v) if part)


def resolve_cover_style(value) -> str:
    """T-2509 (hotfix4, ADR-1025-8 D1): эффективный «Стиль обложки».

    Настроенный владельцем стиль применяется как есть; код-дефолт — ТОЛЬКО
    когда значение реально отсутствует или пусто (``None``/пробелы). Гарантия:
    потеря «стиля владельца» не превращается в пустой стиль, а честно
    откатывается к дефолту."""
    if value is None:
        return SUMMARY_COVER_STYLE_DEFAULT
    text = value if isinstance(value, str) else str(value)
    return text.strip() or SUMMARY_COVER_STYLE_DEFAULT


def cover_style_markers(style: str) -> dict:
    """T-2508 (hotfix4, R17): маркеры содержимого стиля — БЕЗ самого текста.

    * ``has_comic`` — стиль требует комикс-подачу;
    * ``has_heading`` — явно задан короткий заголовок
      (``heading``/``title``/``PERMsoc``/«заголовок»);
    * ``style_is_default`` — доехал код-дефолт (настроенный стиль НЕ пришёл).

    Review L10.25H4-3: токены заголовка — по ГРАНИЦАМ СЛОВ (``\\bpermsoc\\b``,
    ``\\bheading\\b``, ``\\btitle\\b``) + «заголов» (рус.), чтобы не ловить
    ложные подстроки («permanent», «permission», «entitled»).
    """
    text = (style or "").lower()
    has_heading = bool(re.search(r"\b(?:permsoc|heading|title)\b", text)) \
        or "заголов" in text
    return {
        "has_comic": "comic" in text,
        "has_heading": has_heading,
        "style_is_default": (style or "").strip() == SUMMARY_COVER_STYLE_DEFAULT,
    }


# ASAP-2.1 (контракт (e)/T-3979): служебный шиз-постфикс LLM — strip-защита
# перенесена сюда вместе с `_derive_fallback_cover_prompt` (SERIALIZE-1):
# только strip-защита в derive; вынесение семантического выбора/детекции —
# вне responsibility этого модуля.
_SHIZ_MARKER = "самым главным шизом объявляется"


def derive_fallback_cover_prompt(text: str) -> str:
    """Детерминированный visual-промпт обложки из текста саммари (T-2485).

    Без доп. LLM-вызова: корень фолбэка — провайдерские таймауты, поэтому
    лишний вызов того же провайдера ненадёжен и/или зависает. Берём первую
    фразу, снимаем rich-разметку и служебный шиз-постфикс, режем каноном
    ``SUMMARY_COVER_PROMPT_MAX/300``. Никогда не бросает."""
    try:
        # Lazy import: избегаем цикла summary_generator ↔ cover_prompt_assembly
        # (SERIALIZE-1: сборка вынесена, rich-разметка осталась в генераторе).
        from services.summary_generator import downgrade_rich_to_plain
        plain = downgrade_rich_to_plain(str(text or "")).strip()
        plain = plain.replace(_SHIZ_MARKER, "").strip()
        if not plain:
            return ""
        first = re.split(r"(?<=[.!?…])\s+", plain, maxsplit=1)[0].strip()
        from services.system2_handoff import normalize_cover_prompt
        return normalize_cover_prompt(first)
    except Exception:  # pragma: no cover - defensive
        return ""


# ── D7: CoverPromptManifest ─────────────────────────────────────────────────

MANIFEST_KEYS = ("BASE_STYLE", "STORY_SCENE", "SUMMARY_CONTEXT",
                 "STYLE_PROFILE", "RUNTIME_INVARIANTS", "REFERENCES")


@dataclass
class ManifestComponent:
    """Компонента манифеста (D7): source/priority/original/sent/status/reason."""

    key: str
    source: str = ""
    priority: str = ""
    original_text: str = ""
    sent_text: str = ""
    status: str = "omitted"          # kept | compacted | omitted
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key, "source": self.source, "priority": self.priority,
            "original_text": self.original_text,
            "original_chars": len(self.original_text),
            "sent_text": self.sent_text, "sent_chars": len(self.sent_text),
            "status": self.status, "reason": self.reason,
        }


@dataclass
class ManifestAttempt:
    """Фактическая попытка отправки (D7 attempts[]): полная строка + hash."""

    attempt: int
    prompt: str
    outcome: str = "sent"            # sent | ok | retry_superseded | failed
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "attempt": int(self.attempt), "prompt": self.prompt,
            "chars": len(self.prompt), "prompt_hash": prompt_hash(self.prompt),
            "outcome": self.outcome, "reason": self.reason,
        }


@dataclass
class CoverPromptManifest:
    """Единый манифест фактической отправки (D7, T-5249).

    Один и тот же манифест читают все три представления (Constructor /
    Style Editor / Analytics). Полный prompt хранится ТОЛЬКО здесь
    (durable job/run evidence); в generic server log не попадает; наружу —
    только через ``manifest_public`` (fail-closed, admin-authorized)."""

    operation: str                    # "base" | "preview" | "edit"
    components: list[ManifestComponent] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    route: str = ""
    resolved_limit: int | None = None
    limit_unit: str = "unknown"
    limit_source: str = "unknown"     # capability_registry | last_success |
    #                                   runtime_safe | assembly_cap | unknown
    attempts: list[ManifestAttempt] = field(default_factory=list)
    final_prompt: str = ""

    @property
    def final_chars(self) -> int:
        return len(self.final_prompt)

    @property
    def final_hash(self) -> str:
        return prompt_hash(self.final_prompt)

    def to_dict(self) -> dict:
        return {
            "schema": MANIFEST_SCHEMA,
            "operation": self.operation,
            "components": [c.to_dict() for c in self.components],
            "provider": self.provider, "model": self.model,
            "route": self.route,
            "resolved_limit": self.resolved_limit,
            "limit_unit": self.limit_unit,
            "limit_source": self.limit_source,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_prompt": self.final_prompt,
            "final_chars": self.final_chars,
            "prompt_hash": self.final_hash,
        }


def manifest_public(manifest, *, include_prompt: bool = False) -> dict | None:
    """Fail-closed view манифеста для API/UI (D7/INV-4).

    Без явного ``include_prompt=True`` (admin-authorized вызывающий) полные
    тексты НЕ отдаются — только числа/enum/статусы/хэши. ``None`` — тихо."""
    if not isinstance(manifest, dict):
        return None
    try:
        data = json.loads(json.dumps(manifest, ensure_ascii=False))
    except (TypeError, ValueError):      # pragma: no cover - defensive
        data = dict(manifest)
    if not include_prompt:
        data["final_prompt"] = ""
        for att in data.get("attempts") or []:
            att["prompt"] = ""
        for comp in data.get("components") or []:
            comp["original_text"] = ""
            comp["sent_text"] = ""
    return data


def build_base_manifest(*, base_style: str, story_scene: str,
                        summary_context: str, final_prompt: str,
                        provider: str = "", model: str = "",
                        route: str = "image_generation", outcome: str = "sent",
                        reason: str = "",
                        style_cap: int | None = None,
                        total_cap: int | None = None) -> dict:
    """D7-манифест Base Generation (T-5249/T-5250) из плана сборки."""
    plan = base_prompt_plan(base_style, story_scene, summary_context,
                            style_cap=style_cap, total_cap=total_cap)
    components = [ManifestComponent(
        key=p["key"], source=p["source"], priority=p["priority"],
        original_text=p["original_text"], sent_text=p["sent_text"],
        status=p["status"], reason=p["reason"]) for p in plan]
    manifest = CoverPromptManifest(
        operation="base", components=components,
        provider=str(provider or ""), model=str(model or ""), route=route,
        resolved_limit=_base_cap("SUMMARY_COVER_PROMPT_MAX_CHARS", 1000)
        if total_cap is None else int(total_cap),
        limit_unit="chars", limit_source="assembly_cap",
        attempts=[ManifestAttempt(attempt=1, prompt=final_prompt,
                                  outcome=outcome, reason=reason)],
        final_prompt=final_prompt)
    return manifest.to_dict()


def _sent_of(original: str, final_prompt: str) -> tuple[str, str, str]:
    """(sent, status, reason) компоненты по факту в финальном промпте."""
    text = _collapse(original)
    if not text:
        return "", "omitted", "empty"
    if text in final_prompt:
        return text, "kept", ""
    return "", "omitted", "squeezed"


def build_style_manifest(*, issue_display: str, instruction: str,
                         base_style_prompt: str = "", refs_text: str = "",
                         ref_roles_text: str = "", story_scene: str = "",
                         context_text: str = "", final_prompt: str = "",
                         provider: str = "", model: str = "", route: str = "",
                         operation: str = "edit", resolved_limit=None,
                         limit_unit: str = "unknown",
                         limit_source: str = "unknown",
                         attempts: list | None = None) -> dict:
    """D7-манифест Style Edit (T-5249/T-5251) по факту финального промпта."""
    runtime_text = runtime_invariants_text(issue_display)
    story_full = _collapse(story_scene)
    story_floor = story_floor_text(story_scene)
    instruction_floor = profile_identity_floor(instruction)
    if story_full and story_floor in final_prompt:
        story_sent = story_floor
        story_status = "kept" if story_sent == story_full else "compacted"
        story_reason = "" if story_sent == story_full else "story_minimum"
    else:
        story_sent, story_status, story_reason = "", "omitted", "squeezed"
    ctx_full = _collapse(context_text)
    ctx_sent, ctx_status, ctx_reason = _sent_of(ctx_full, final_prompt)
    instr_full = _collapse(instruction)
    if instr_full and instr_full in final_prompt:
        instr_sent, instr_status, instr_reason = \
            instr_full, "kept", ""
    elif instruction_floor and instruction_floor in final_prompt:
        instr_sent, instr_status, instr_reason = \
            instruction_floor, "compacted", "profile_identity_floor"
    else:
        instr_sent, instr_status, instr_reason = "", "omitted", "squeezed"
    refs_full = _collapse(refs_text)
    roles_full = _collapse(ref_roles_text)
    if refs_full and refs_full in final_prompt:
        refs_sent, refs_status, refs_reason = refs_full, "kept", ""
    elif roles_full and roles_full in final_prompt:
        refs_sent, refs_status, refs_reason = \
            roles_full, "compacted", "roles_only"
    else:
        refs_sent, refs_status, refs_reason = "", "omitted", "squeezed"
    base_full = _collapse(base_style_prompt)
    base_sent, base_status, base_reason = _sent_of(base_full, final_prompt)
    components = [
        ManifestComponent(key="RUNTIME_INVARIANTS", source="code",
                          priority="P0", original_text=runtime_text,
                          sent_text=(runtime_text if runtime_text
                                     in final_prompt else ""),
                          status=("kept" if runtime_text in final_prompt
                                  else "omitted"),
                          reason=("" if runtime_text in final_prompt
                                  else "squeezed")),
        ManifestComponent(key="STYLE_PROFILE", source="style_profile",
                          priority="P1", original_text=instr_full,
                          sent_text=instr_sent, status=instr_status,
                          reason=instr_reason),
        ManifestComponent(key="BASE_STYLE", source="settings", priority="P1",
                          original_text=base_full, sent_text=base_sent,
                          status=base_status, reason=base_reason),
        ManifestComponent(key="REFERENCES", source="style_profile",
                          priority="P2", original_text=refs_full,
                          sent_text=refs_sent, status=refs_status,
                          reason=refs_reason),
        ManifestComponent(key="STORY_SCENE", source="summary_stage1",
                          priority="P2", original_text=story_full,
                          sent_text=story_sent, status=story_status,
                          reason=story_reason),
        ManifestComponent(key="SUMMARY_CONTEXT", source="final_summary",
                          priority="P2", original_text=ctx_full,
                          sent_text=ctx_sent, status=ctx_status,
                          reason=ctx_reason),
    ]
    manifest = CoverPromptManifest(
        operation=str(operation or "edit"), components=components,
        provider=str(provider or ""), model=str(model or ""), route=route,
        resolved_limit=(int(resolved_limit)
                        if resolved_limit is not None else None),
        limit_unit=str(limit_unit or "unknown"),
        limit_source=str(limit_source or "unknown"),
        attempts=[ManifestAttempt(**a) for a in (attempts or [])],
        final_prompt=final_prompt)
    return manifest.to_dict()


def runtime_invariants_text(issue_display: str) -> str:
    """P0-текст runtime-инвариантов Style Edit (номер выпуска + no-dupes).

    Единый источник строки для compile и манифеста (T-5249: манифест описывает
    фактически отправленные компоненты, а не вторую компиляцию)."""
    return ("Сохрани номер выпуска «%s». Не добавляй дубликатов уже "
            "присутствующих на обложке элементов." % issue_display)


def reference_roles_text(refs: list | None) -> str:
    """Mandatory reference roles (T-5251): labels ролей — не выбрасываются
    молча; описания (детали) при squeeze опускаются, картинки-референсы
    (reference_paths) при retry не меняются."""
    labels = []
    for ref in (refs or []):
        label = str((ref or {}).get("label") or "").strip()
        if label:
            labels.append(label)
    return "; ".join(labels)
