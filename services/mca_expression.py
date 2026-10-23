"""ADD-EXP — единственный владелец логики слоя «Выражение» (манера речи).

Дизайн: `plans/features/add-exp/design-add-exp.md` §1.6, §2, §3, §6.
Здесь живут: канонические значения контролов, нормализация (read-alias
``allowed`` → ``occasional``), per-control effective-резолв chat→global→factory,
рендер слоя ``<Expression_Settings>`` (header §2.1 + строки §2.2 байт-в-байт),
builder ``composer.ExpressionSettings`` (preview и бой рендерят ОДИН текст),
few-shot набор ``<Expression_Examples>`` (§3.2/3.3) и диагностика §6
(closed-set классов, emit через ``mca_events``, R17: только коды/числа/хеши).

Границы (анти-дрейф): второй storage мата не создаётся — документ
``character.expression`` (bot_settings/chat_params) остаётся единственным;
второй рендер не создаётся — ``web/api/speech.py`` и runtime-сборки зовут
функции ЭТОГО модуля; постпроцессор вставки мата запрещён (EXP-INSTR.NOPOST).
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: Канонический ключ документа (единственный storage; ADD-1.E1).
EXPRESSION_DOC_KEY = "character.expression"

#: Закрытый набор канонических значений записи (§1.1): ``inherit`` —
#: ТОЛЬКО режим наследования chat→global, не четвёртая степень частоты.
EXPRESSION_MODES: tuple[str, ...] = ("inherit", "off", "occasional", "frequent")

#: Read-alias совместимости (§1.3): старый ``allowed`` читается как
#: ``occasional``; фоновых записей и спец-миграции нет.
EXPRESSION_ALIASES: dict[str, str] = {"allowed": "occasional"}

#: Полный набор значений по контролам (запись; closed-set).
EXPRESSION_CONTROL_VALUES: dict[str, tuple[str, ...]] = {
    "wit": ("inherit", "low", "normal", "high"),
    "sharpness": ("inherit", "soft", "normal", "sharp"),
    "profanity": EXPRESSION_MODES,
    "verbosity": ("inherit", "short", "normal", "long"),
}

#: Заводские значения, когда явного выбора владельца нет (§1.5).
#: ``profanity``: factory_default = ``occasional`` (мат разрешён, редкий,
#: реальный — совместимо с CFG-07B.1 «factory ON»).
EXPRESSION_FACTORY_DEFAULTS: dict[str, str] = {
    "profanity": "occasional",
}

#: Порядок контролов в слое (совпадает с EXPRESSION_CONTROLS в speech.py).
CONTROL_ORDER: tuple[str, ...] = ("wit", "sharpness", "profanity", "verbosity")

#: Метки контролов для слоя (`- <label>: <instruction>`).
CONTROL_LABELS: dict[str, str] = {
    "wit": "Остроумие",
    "sharpness": "Резкость",
    "profanity": "Мат",
    "verbosity": "Развёрнутость",
}

# ── §2.2: канонические инструкции слоя (уходят в LLM; байт-в-байт) ──────────

#: ADD-SAMPLES-UX §2 (20.10.2026, вечер — заменяет F3-формулировки
#: occasional/frequent): директивы — ТОЧНЫЕ тексты владельца, байт-в-байт.
#: CORRECTIVE-FOLLOWUP (21.10.2026, §2 владельца): тексты трёх режимов
#: ЗАФИКСИРОВАНЫ окончательно — Expression единственный источник настроек
#: мата, менять формулировки без подтверждённой необходимости запрещено.
#: Новых квот, счётчиков, случайной вставки ругательств и постпроцессора нет
#: (EXP-INSTR.NOPOST): частота задаётся только инструкцией. ``off`` не менялся.

PROFANITY_INSTRUCTIONS: dict[str, str] = {
    "off": "Не используй мат в собственной речи.",
    "occasional": (
        "Пиши разговорным языком с примесью мата. Нецензурные выражения "
        "используй как обычные эмоциональные оценки и междометия, без "
        "необходимости специально обосновывать их появление. Мат не должен "
        "доминировать в речи."
    ),
    "frequent": (
        "Пиши на живом разговорном языке с выраженным использованием мата. "
        "Нецензурная лексика — привычная часть твоего словаря: оценки, "
        "междометия, усиления и разговорные связки. Не заменяй её цензурными "
        "эвфемизмами."
    ),
}

#: Инструкции прочих контролов = прежние effect-тексты (слой рендерит их
#: одной строкой; формулировки не менялись этим слайсом).
CONTROL_INSTRUCTIONS: dict[str, dict[str, str]] = {
    "wit": {
        "low": ("Поводы для шутки почти не ищутся: по делу, без насилия "
                "над темой."),
        "normal": "Обычная манера: шутка появляется, когда она уместна.",
        "high": ("Повод ищется охотнее (сравнение, абсурдная деталь) — и "
                 "шутка не откладывается на потом."),
    },
    "sharpness": {
        "soft": "Подколка остаётся, но мягче; спор — по существу.",
        "normal": "Обычная язвительность ядра без перехода на личность.",
        "sharp": ("Резче и прямее: жёсткость формулировок и оценок, "
                  "а не переход на личность собеседника."),
    },
    "profanity": PROFANITY_INSTRUCTIONS,
    "verbosity": {
        "short": ("Короче по умолчанию; прямая просьба «подробнее» "
                  "по-прежнему важнее."),
        "normal": "Обычная длина, если план не задаёт другую.",
        "long": "Подробнее по умолчанию; «короче» пользователя важнее.",
    },
}

#: §2.1 → ASAP W1 (P0-D, §3.4 source-2026-10-22.md): header заменён текстом
#: владельца БАЙТ-В-БАЙТ. Сняты служебные описания для разработчиков
#: («Выражение владельца — прямые директивы…») и рассуждения о приоритетах/
#: механике приложения (§1.4, REQ-META-CLEAN); добавлено правило «не переноси
#: ограничения или разрешения из других речевых слоёв» (единственный владелец
#: режима мата — этот слой). Тексты режимов off/occasional/frequent
#: (PROFANITY_INSTRUCTIONS) НЕ тронуты — побуквенно прежние (CORRECTIVE-
#: FOLLOWUP 21.10.2026 зафиксировал их окончательно; байт-сверка с §3.4 в
#: tests/test_asap_w1_semantics.py). Прежний header виден в слепке
#: PREV_EXPRESSION_HEADER (только документация/история, НЕ runtime).
PREV_EXPRESSION_HEADER = (
    "<Expression_Settings>\n"
    "Выражение владельца - прямые директивы о манере речи; действуют на всю "
    "пользовательскую речь бота, включая фактчек, сводки, подписи и "
    "служебные ответы; дословные цитаты и чужой текст передаются как есть. "
    "Выполняй директивы ниже без ослаблений и без подмены другими слоями. "
    "Приоритет: полноту и форму задаёт план или прямая просьба — "
    "развёрнутость ниже действует, только если они молчат; эти "
    "настройки важнее общего разрешения канона; прямая просьба участника о "
    "форме важнее этих настроек:"
)
EXPRESSION_HEADER = (
    "<Expression_Settings>\n"
    "ПРАВИЛА МАНЕРЫ РЕЧИ\n"
    "Применяй перечисленные ниже параметры к собственной речи в готовом "
    "ответе. Это действующие инструкции по выражению, а не описание настроек "
    "и не пожелания. Они не меняют факты, не дополняют память и не отменяют "
    "требования конкретной задачи к содержанию. Прямую цитату передавай без "
    "стилистической подмены. Если задан режим нецензурной лексики, "
    "руководствуйся именно им; не переноси ограничения или разрешения из "
    "других речевых слоёв."
)
EXPRESSION_FOOTER = "</Expression_Settings>"

#: Обороты, запрещённые как ЕДИНСТВЕННОЕ правило (§2.3 п.2) — проверяются
#: тестом на строках occasional/frequent.
BANNED_SOLE_RULE_PHRASES: tuple[str, ...] = (
    "мат разрешён", "мат допустим", "естественно", "при необходимости",
    "необязателен", "не обязательный",
)

# ── §3.2: few-shot блок примеров регистра речи ──────────────────────────────

EXPRESSION_EXAMPLES_OPEN = '<Expression_Examples mode="%s">'
EXPRESSION_EXAMPLES_CLOSE = "</Expression_Examples>"
EXPRESSION_EXAMPLES_MAX_ITEMS = 4
EXPRESSION_EXAMPLES_MAX_CHARS = 700
#: §3.2: бюджет блока ≤ 140 токенов (оценка 4 символа ≈ токен) — при
#: нехватке строки отбрасываются, блок остаётся честным и закрытым.
EXPRESSION_EXAMPLES_MAX_TOKENS = 140

# ── §6: диагностика (closed-set классов; R17-safe) ─────────────────────────

EXPRESSION_DIAG_CLASSES: tuple[str, ...] = (
    "policy_not_injected", "composer_excluded", "model_ignored_instruction",
    "postprocess_changed", "provider_limitation", "unknown",
)

#: Класс → (outcome, level, существующий reason_code) для mca_events.
#: Новых кодов в REASON_CODES не заводим (закрытый набор принадлежит
#: mca_events); класс едет в `status`/`usage_json` как код.
_DIAG_EVENT_SHAPE: dict[str, tuple[str, str, str]] = {
    "policy_not_injected": ("failed", "WARN", "source_missing"),
    "composer_excluded": ("skipped", "INFO", "source_missing"),
    "model_ignored_instruction": ("failed", "WARN", "source_missing"),
    "postprocess_changed": ("failed", "WARN", "source_missing"),
    "provider_limitation": ("failed", "WARN", "provider_unavailable"),
    "unknown": ("silent", "INFO", "source_missing"),
}

_DIAG_DEDUP_MAX = 512
_diag_lock = threading.Lock()
_diag_emitted: "dict[tuple, None]" = {}

#: Детектор мата по корням (диагностический; bounded, word-start anchored).
PROFANITY_ROOTS: tuple[str, ...] = (
    r"бля", r"ху[йеёи]", r"пизд", r"заеб", r"охуе", r"мудак", r"нахуй",
    r"нахер", r"долбоеб", r"(?<![а-яё])еб", r"(?<![а-яё])ёб",
    r"(?<![а-яё])сука(?![а-яё])",
)
_PROFANITY_RE = re.compile(
    "|".join(PROFANITY_ROOTS), re.IGNORECASE | re.UNICODE)

#: Порог «N подряд без мата» для класса ``model_ignored_instruction``
#: (harness Ф6; одиночная проба НЕ приговор — §6).
MODEL_IGNORE_PROBES = 5


# ═══════════════════════════════════════════════════════════════════════════
# §1.1/§1.3 — нормализация и значения
# ═══════════════════════════════════════════════════════════════════════════


def normalize_mode(raw: Any) -> str:
    """Канонический режим ``profanity`` (alias ``allowed`` → ``occasional``)."""
    value = str(raw or "").strip().lower()
    value = EXPRESSION_ALIASES.get(value, value)
    return value if value in EXPRESSION_MODES else "inherit"


def normalize_expression(raw: Any) -> dict:
    """Валидация документа «Выражение» (закрытые наборы, ничего лишнего).

    Единственная точка нормализации: ``allowed`` читается как ``occasional``
    (read-alias, §1.3), неизвестное значение → ``inherit``.
    """
    doc = raw if isinstance(raw, Mapping) else {}
    out: dict[str, Any] = {"enabled": bool(doc.get("enabled", True))}
    for key, allowed in EXPRESSION_CONTROL_VALUES.items():
        value = str(doc.get(key) or "inherit").strip().lower()
        value = EXPRESSION_ALIASES.get(value, value)
        out[key] = value if value in allowed else "inherit"
    out["note"] = str(doc.get("note") or "")[:2000]
    return out


def _raw_value(raw_doc: Any, control: str) -> str:
    if not isinstance(raw_doc, Mapping):
        return ""
    return str(raw_doc.get(control) or "").strip().lower()


def resolve_effective(chat_doc: Any, global_doc: Any) -> dict:
    """Per-control merge (§1.2): chat_explicit → global_explicit → factory.

    ``inherit`` внутри документа = «нет явного выбора», дальше по цепочке.
    Возврат: ``{"enabled": bool, "note": str, "controls": {control: {value,
    source, migrated}}}``; ``migrated`` = значение пришло из alias ``allowed``.
    """
    chat_n = normalize_expression(chat_doc) if isinstance(chat_doc, Mapping) \
        else None
    glob_n = normalize_expression(global_doc) if isinstance(global_doc, Mapping) \
        else None
    controls: dict[str, dict] = {}
    for control in CONTROL_ORDER:
        value, source = "inherit", "factory_default"
        if chat_n is not None and chat_n.get(control) not in ("", "inherit"):
            value, source = str(chat_n[control]), "chat"
        elif glob_n is not None and glob_n.get(control) not in ("", "inherit"):
            value, source = str(glob_n[control]), "global"
        else:
            factory = str(EXPRESSION_FACTORY_DEFAULTS.get(control) or "")
            value = factory if factory in EXPRESSION_CONTROL_VALUES[control] \
                else "inherit"
        raw_layer = (chat_doc if source == "chat"
                     else global_doc if source == "global" else None)
        migrated = bool(_raw_value(raw_layer, control) in EXPRESSION_ALIASES)
        controls[control] = {"value": value, "source": source,
                             "migrated": migrated}
    owner_doc = chat_doc if isinstance(chat_doc, Mapping) else global_doc
    owner_n = normalize_expression(owner_doc) \
        if isinstance(owner_doc, Mapping) else None
    return {
        "enabled": bool(owner_n["enabled"]) if owner_n else True,
        "note": str(owner_n["note"]) if owner_n else "",
        "controls": controls,
    }


def expression_migration(chat_doc: Any, global_doc: Any) -> dict:
    """§1.3: ``migration`` для payload (``allowed`` → ``occasional``)."""
    for control, target in (("profanity", "occasional"),):
        for doc in (chat_doc, global_doc):
            if _raw_value(doc, control) == "allowed":
                return {control: {"from": "allowed", "to": target}}
    return {}


def effective_source(effective: Mapping[str, Any]) -> str:
    """Провенанс слоя для ``ExpressionSettings.source`` (chat/global/default)."""
    sources = {str((item or {}).get("source") or "")
               for item in (effective.get("controls") or {}).values()}
    if "chat" in sources:
        return "chat"
    if "global" in sources:
        return "global"
    return "default"


def effective_mode(effective: Mapping[str, Any]) -> str:
    """Канонический режим ``profanity`` из effective (или ``inherit``)."""
    item = (effective.get("controls") or {}).get("profanity") or {}
    return normalize_mode(item.get("value"))


# ═══════════════════════════════════════════════════════════════════════════
# §2.1/§2.2 — рендер слоя (единственная реализация; preview == бой)
# ═══════════════════════════════════════════════════════════════════════════


def _coerce_effective(source: Any) -> dict:
    """Принять effective-резолв ИЛИ сырой документ (совместимость вызовов)."""
    if isinstance(source, Mapping) and isinstance(
            source.get("controls"), Mapping):
        return dict(source)
    return resolve_effective(source, None)


def render_expression_text(source: Any) -> str:
    """Рендер слоя `expression` из owner-контролов (детерминированно, 0 LLM).

    ``source`` — effective-резолв (`resolve_effective`) или сырой документ
    (совместимость существующих вызовов). Контролы без явного значения строку
    не дают; профность-строка появляется, когда effective-режим разрешён
    (всегда, кроме ``enabled=false``).
    """
    effective = _coerce_effective(source)
    if not bool(effective.get("enabled", True)):
        return ""
    lines: list[str] = []
    for control in CONTROL_ORDER:
        item = (effective.get("controls") or {}).get(control) or {}
        value = normalize_mode(item.get("value")) \
            if control == "profanity" else str(item.get("value") or "inherit")
        if value in ("", "inherit"):
            continue
        instruction = (CONTROL_INSTRUCTIONS.get(control) or {}).get(value)
        if not instruction:
            continue
        lines.append(f"- {CONTROL_LABELS[control]}: {instruction}")
    note = str(effective.get("note") or "").strip()
    if note:
        lines.append(f"- Пожелание владельца: {note}")
    if not lines:
        return ""
    return EXPRESSION_HEADER + "\n" + "\n".join(lines) + "\n" + EXPRESSION_FOOTER


def sha12(text: str) -> str:
    """12-hex sha256 (та же ревизия, что у композера/реестра)."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def build_expression_settings(chat_doc: Any, global_doc: Any):
    """``composer.ExpressionSettings`` из пары документов (единый builder).

    Preview и боевые сборки используют ЭТУ функцию — текст слоя один и тот
    же (EXP-ACCEPT.PREVIEW: «предпросмотр не врёт»).
    """
    from services.prompt_composer import ExpressionSettings

    effective = resolve_effective(chat_doc, global_doc)
    enabled = bool(effective.get("enabled", True))
    text = render_expression_text(effective) if enabled else ""
    mode = effective_mode(effective)
    skip_reason = ""
    if not text.strip():
        skip_reason = "expression_disabled" if not enabled \
            else "expression_absent"
    return ExpressionSettings(
        text=text,
        revision=sha12(text) if text else "",
        source=effective_source(effective),
        mode=mode,
        enabled=enabled,
        skip_reason=skip_reason,
    )


# ═══════════════════════════════════════════════════════════════════════════
# §3.2/§3.3 — few-shot набор регистра речи (только свой режим; ≤4)
# ═══════════════════════════════════════════════════════════════════════════


class ExampleRender(str):
    """Блок примеров + фактический состав (ASAP3 §2: без скрытой потери).

    ``str``-совместим: существующие потребители читают значение как текст
    блока (``sha12``/``_estimate_tokens``/``startswith``), а состав доступен
    полями — сколько строк было у владельца и сколько реально вошло.
    """

    __slots__ = ("mode", "total_items", "included_items", "dropped",
                 "limited_by")

    def __new__(cls, block: str = "", *, mode: str = "", total_items: int = 0,
                included_items: int = 0, limited_by: str = "") -> "ExampleRender":
        obj = str.__new__(cls, block)
        obj.mode = str(mode or "")
        obj.total_items = int(total_items)
        obj.included_items = int(included_items)
        obj.dropped = max(0, obj.total_items - obj.included_items)
        obj.limited_by = str(limited_by or "")
        return obj

    def as_dict(self) -> dict:
        """R17-safe диагностика: только числа и коды, без текста реплик."""
        return {"mode": self.mode, "total_items": self.total_items,
                "included_items": self.included_items,
                "dropped": self.dropped, "limited_by": self.limited_by,
                "chars": len(self)}


def render_expression_examples_block(mode: str, rows: Any, *,
                                     available_items: int | None = None
                                     ) -> ExampleRender:
    """Блок ``<Expression_Examples mode="…">`` из строк библиотеки (§3.2).

    Бюджет ≤140 токенов: при перерасходе отбрасываются последние строки
    (блок всегда остаётся корректно закрытым); пустой результат → ``""``.
    ASAP3 §2: отбор/бюджет не молчат — фактический состав едет в
    :class:`ExampleRender` (``total_items``/``included_items``/``limited_by``).
    ``available_items`` — сколько подходящих одобренных строк было у владельца
    ДО лимита резолвера (§3.2, 4 строки): без него ``total_items`` описывал бы
    только остаток после отбора и потеря 5..N снова стала бы невидимой (#13).
    """
    mode = normalize_mode(mode)
    if mode not in ("off", "occasional", "frequent"):
        return ExampleRender("")
    candidates: list[str] = []
    for row in (rows or ()):
        theme = str(row.get("context_note") or "").strip() or "реплика"
        user_line = str(row.get("input_text") or "").strip()
        reply = str(row.get("reply_text") or "").strip()
        if not user_line or not reply:
            continue
        candidates.append(f"- {theme}: {user_line} -> {reply}")
    if not candidates:
        return ExampleRender("")
    total_items = max(len(candidates), int(available_items or 0))
    lines = candidates[:EXPRESSION_EXAMPLES_MAX_ITEMS]
    reasons: list[str] = []
    if total_items > len(lines):
        reasons.append("items")

    def _assemble(kept: list[str]) -> str:
        return "\n".join((
            EXPRESSION_EXAMPLES_OPEN % mode, "\n".join(kept),
            EXPRESSION_EXAMPLES_CLOSE))

    block = _assemble(lines)
    while lines:
        over_tokens = _estimate_tokens(block) > EXPRESSION_EXAMPLES_MAX_TOKENS
        over_chars = len(block) > EXPRESSION_EXAMPLES_MAX_CHARS
        if not (over_tokens or over_chars):
            break
        if over_tokens:
            reasons.append("tokens")
        if over_chars:
            reasons.append("chars")
        lines.pop()
        block = _assemble(lines) if lines else ""
    return ExampleRender(
        block, mode=mode, total_items=total_items,
        included_items=len(lines), limited_by="+".join(dict.fromkeys(reasons)))


def _estimate_tokens(text: str) -> int:
    """Тот же оценщик, что у композера (4 символа ≈ токен)."""
    return max(1, (len(str(text or "")) + 3) // 4)


async def build_expression_examples_refs(chat_id: int, mode: str, *,
                                         db=None) -> tuple:
    """SampleRef-блоки few-shot для effective-режима (§3.2/§3.3).

    Только свой набор (не все три); только одобренные владельцем примеры
    (`owner_approved=1`, `status='active'`, `technique='expression_register'`,
    тег режима). Своя ось `expression_examples_enabled` (env kill-switch).
    Никогда не бросает: сбой → пусто (честная причина в манифесте).
    """
    mode = normalize_mode(mode)
    if mode not in ("off", "occasional", "frequent"):
        return ()
    try:
        from services import mca_gates
        if not mca_gates.expression_examples_enabled():
            return ()
        from services import mca_sample_library as lib
        resolve_stats: dict = {}
        rows, reason = await lib.resolve_expression_examples_ex(
            chat_id, mode, db=db, stats=resolve_stats)
        # ASAP3 §2 (#13): total — из резолвера (до его лимита §3.2), иначе
        # render видит только ≤4 строки и «kept=4/4» скрывает потерю.
        text = render_expression_examples_block(
            mode, rows, available_items=int(resolve_stats.get("eligible", 0)
                                            or 0))
        if not text.strip():
            if reason == "not_owner_approved":
                # BLOCK-1/§3.3: строки режима ЕСТЬ, но ни одна не утверждена
                # владельцем — честная причина в манифесте (не «absent»),
                # в runtime не уходит ничего.
                from services.prompt_composer import SampleRef
                return (SampleRef(
                    block_id="expression_examples", text="", revision="",
                    source="global", technique="expression_register",
                    enabled=False,
                    skip_reason="not_owner_approved"),)
            if rows:
                # ASAP3 §2: одобренные строки ЕСТЬ, но технический бюджет
                # §3.2 (≤4 строки / 140 токенов / 700 симв.) не оставил ни
                # одной. Молчаливое «absent» выдавало бы потерю за пустой
                # набор: причина — budget_excluded (не лимит владельца).
                logger.warning(
                    "[expression] examples fit budget=0 | mode=%s | "
                    "rows=%d | by=%s", mode, len(rows),
                    getattr(text, "limited_by", ""))
                from services.prompt_composer import SampleRef
                return (SampleRef(
                    block_id="expression_examples", text="", revision="",
                    source="global", technique="expression_register",
                    enabled=False, skip_reason="budget_excluded"),)
            return ()
        from services.prompt_composer import SampleRef
        dropped = int(getattr(text, "dropped", 0) or 0)
        if dropped > 0:
            # ASAP3 §2: частичное исключение одобренных строк — не молча:
            # R17-safe числа в WARN (текст реплик не логируется).
            logger.warning(
                "[expression] examples capped | mode=%s | kept=%d/%d | by=%s",
                mode, int(getattr(text, "included_items", 0)),
                int(getattr(text, "total_items", 0)),
                getattr(text, "limited_by", ""))
        return (SampleRef(
            block_id="expression_examples",
            text=text,
            revision=sha12(text),
            source="global",
            library_version=str(
                (rows[0] or {}).get("library_version") or ""),
            technique="expression_register",
            reason=f"expression_examples:{mode}",
        ),)
    except Exception:
        logger.warning("[expression] examples refs failed — слой пропущен",
                       exc_info=True)
        return ()


# ═══════════════════════════════════════════════════════════════════════════
# §6 — диагностика: closed-set классов, дедуп 1×процесс, R17-safe
# ═══════════════════════════════════════════════════════════════════════════


def emit_expression_diag(cls: str, *, chat_id: int | None = None,
                         stage: str = "", detail: str = "",
                         mode: str = "") -> dict | None:
    """Эмиссия диагностического класса (fail-open, дедуп 1×процесс).

    R17: только коды/числа — класс/стадия/режим/деталь-код; текста промпта и
    ответа в полях нет.
    """
    name = str(cls or "")
    if name not in EXPRESSION_DIAG_CLASSES:
        name = "unknown"
    stage_code = _code_token(stage)
    detail_code = _code_token(detail)
    mode_code = normalize_mode(mode) if mode else ""
    key = (int(chat_id or 0), name, stage_code, detail_code, mode_code)
    with _diag_lock:
        if key in _diag_emitted:
            return None
        _diag_emitted[key] = None
        while len(_diag_emitted) > _DIAG_DEDUP_MAX:
            _diag_emitted.popitem(last=False)
    outcome, level, reason_code = _DIAG_EVENT_SHAPE[name]
    status = ":".join(p for p in ("expression_diag", name, stage_code,
                                  detail_code) if p)
    try:
        from services import mca_events
        return mca_events.emit_mca_event(
            "expression_diag", outcome=outcome, level=level,
            component="expression", stage=stage_code or "unknown",
            status=status[:120], chat_id=int(chat_id or 0),
            reason_code=reason_code,
            usage_json={"class": name, "mode": mode_code or "unknown",
                        "detail": detail_code or "none"})
    except Exception:      # pragma: no cover — fail-open
        return None


def reset_diag_dedup() -> None:
    """Сброс дедупа диагностики (тесты/диагностика)."""
    with _diag_lock:
        _diag_emitted.clear()


def _code_token(value: Any) -> str:
    """Код-токен для события: [a-z0-9_], ≤32 символов (R17-safe)."""
    token = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower())
    return token.strip("_")[:32]


def count_profanity(text: Any) -> int:
    """Сколько корней мата в тексте (диагностический счётчик, не редактор)."""
    return len(_PROFANITY_RE.findall(str(text or "")))


def classify_expression_response(raw: Any, mode: str, genre: str = "", *,
                                 probes: int = 1, marker_present: bool = True,
                                 provider_error: bool = False,
                                 postprocess: bool = False) -> str:
    """Класс §6 для контролируемой пробы (harness Ф6 / «Проверить вживую»).

    Одиночная проба честно НЕ приговор: ``model_ignored_instruction`` только
    при ``probes >= MODEL_IGNORE_PROBES`` (N=5 подряд) для режимов, где мат
    ожидается. ``genre`` — код жанра для будущего расширения (не текст).
    """
    if provider_error:
        return "provider_limitation"
    if not marker_present:
        return "policy_not_injected"
    if postprocess:
        return "postprocess_changed"
    mode_n = normalize_mode(mode)
    if mode_n == "off":
        return "model_ignored_instruction" if count_profanity(raw) > 0 else ""
    if mode_n in ("occasional", "frequent"):
        if count_profanity(raw) > 0:
            return ""
        if mode_n == "frequent" and int(probes or 0) >= MODEL_IGNORE_PROBES:
            return "model_ignored_instruction"
        return ""
    return "unknown"


def diag_classes() -> tuple[str, ...]:
    """Публичный closed-set классов (для payload/тестов)."""
    return EXPRESSION_DIAG_CLASSES


__all__ = [
    "EXPRESSION_DOC_KEY", "EXPRESSION_MODES", "EXPRESSION_ALIASES",
    "EXPRESSION_CONTROL_VALUES", "EXPRESSION_FACTORY_DEFAULTS",
    "CONTROL_ORDER", "CONTROL_LABELS", "CONTROL_INSTRUCTIONS",
    "PROFANITY_INSTRUCTIONS", "EXPRESSION_HEADER", "EXPRESSION_FOOTER",
    "BANNED_SOLE_RULE_PHRASES", "EXPRESSION_DIAG_CLASSES",
    "MODEL_IGNORE_PROBES", "PROFANITY_ROOTS",
    "normalize_mode", "normalize_expression", "resolve_effective",
    "expression_migration", "effective_source", "effective_mode",
    "render_expression_text", "build_expression_settings",
    "render_expression_examples_block", "build_expression_examples_refs",
    "emit_expression_diag", "reset_diag_dedup", "classify_expression_response",
    "count_profanity", "diag_classes", "sha12",
]
