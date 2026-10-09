"""MCA-23 (Wave 3, §2/§4/§10-§12 current_task) — ResponsePlan: оси полноты.

Детерминированная (0 LLM-вызовов) классификация запроса по осям канона
MCA-23 §4: ``task_kind`` / ``extent`` / ``structure`` / ``delivery`` /
``tool_policy``. Строится ДО LLM-стадии в direct_chat (fast path §8 не
меняется: для очевидного chat/micro план не создаёт второго вызова).

Разделение осей (§4): ``complexity`` и ``extent`` не смешиваются - класс-
вопрос может требовать двух предложений, простой фанфик - длинного ответа.

Явная инструкция пользователя о длине (§12) имеет высокий приоритет:
«коротко/в двух словах» и «подробно/распиши/полный разбор» перекрывают
семантическую подсказку task-kind (фанфик/объяснение -> longform-семейство,
болтовня -> compact).

Здесь же - канон Direct extent-блоков для Вербализатора (§11: unconditional
«Коротко: одно-два предложения» заменён extent-блоком) и детерминированный
prompt-conflict scrub (§11/§32: старый cap-текст из PG-кастома вычищается из
финальной сборки промпта при longform-плане, БД не правится).

Языковая дисциплина: новые строки промптов без ёлочек и длинных тире
(прецедент R5/R9/R2020), без ``{}``-плейсхолдеров. R17: классификатор не
логирует текст запроса, только оси плана.
"""
from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Оси канона §4 ────────────────────────────────────────────────────────────

EXTENTS = ("micro", "compact", "normal", "detailed", "longform", "exhaustive")

# Семейство «полных» extent'ов: для них снимается cap-семантика (§10/§11),
# поднимается max_output_tokens и работает prompt-conflict scrub.
LONGFORM_FAMILY = frozenset({"detailed", "longform", "exhaustive"})

TASK_KINDS = ("social_chat", "direct_answer", "explanation", "creative_writing",
              "research", "comparison", "summarization", "historical_recall",
              "media_download", "media_generation", "transcription")

STRUCTURES = ("chat", "answer", "explanation", "story", "summary",
              "comparison", "report", "steps")

TOOL_POLICIES = ("none", "auto", "required", "constrained")

DELIVERY_HINTS = ("plain", "rich", "media", "none", "")

# Rich-доставка (§Delivery Router): минимум контента, чтобы «статья» из трёх
# слов не уходила rich-каналом. Число код-константа (не PG).
RICH_MIN_ANSWER_CHARS = 400

# Env-дефолт max_output_tokens для longform-планов (§Model slots).
DEFAULT_LONGFORM_MAX_OUTPUT_TOKENS = 4096
_MAX_OUTPUT_TOKENS_CEILING = 16384

# ── MCA-23 фаза 2 (§17/§39): bounded multi-tool план ────────────────────────
# Потолки developer-level (§39). Числа код-константы; исполнение —
# services/tool_loop (поверх существующего цикла, НЕ второй агент).
PLAN_MAX_STEPS = 6            # шагов в плане не больше суммарного cap вызовов
PLAN_MAX_REPLANS = 2          # §39 ceiling; фаза 2: re-plan не выполняется
PLAN_MAX_FETCH_STEPS = 3      # больше ссылок в запросе → план не строим

# §14: предпочтительные capability names → реальные tools. Шаги с именем,
# отсутствующим в runtime-наборе (анонсированном LLM), не исполняются (§38).
CAPABILITY_TOOLS = {
    "memory_search": "query_chat_memory",
    "lore_search": "dig_into_lore",
    "web_search": "execute_web_search",
    "article_fetch": "fetch_article",
    "video_transcript": "transcribe_video",
    "video_summary": "summarize_video",
    "media_download": "download_media",
    "image_generation": "generate_image",
    "factcheck": "fact_check",
    "user_context": "get_user_context",
    "health": "get_bot_health",
}


@dataclass(frozen=True)
class ResponsePlan:
    """Внутренний план ответа (MCA-23 §3, минимальная семантика).

    Internal metadata - пользователь её не видит, в wire-JSON Stage-1/Stage-2
    не сериализуется (граница A7 сохранена). ``source`` - R17-safe код
    происхождения: ``explicit`` (явная инструкция длины) | ``task-kind`` |
    ``mode_alias`` | ``default``.
    """

    task_kind: str = "social_chat"
    extent: str = "compact"
    structure: str = "chat"
    delivery_hint: str = "plain"
    tool_policy: str = "auto"
    source: str = "default"

    def is_longform(self) -> bool:
        """Семейство «полных» extent'ов (см. :data:`LONGFORM_FAMILY`)."""
        return self.extent in LONGFORM_FAMILY


def normalize_extent(value) -> str:
    """Валидный extent или ``""`` (fail-open, никогда не бросает)."""
    candidate = str(value or "").strip().lower()
    return candidate if candidate in EXTENTS else ""


def normalize_task_kind(value) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in TASK_KINDS else ""


def normalize_structure(value) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in STRUCTURES else ""


def normalize_tool_policy(value) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in TOOL_POLICIES else ""


def normalize_delivery_hint(value) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in DELIVERY_HINTS else ""


def response_plan_enabled() -> bool:
    """Kill-switch ``DIRECT_RESPONSE_PLAN_ENABLED`` (env, default ON).

    OFF -> план не строится, extent-блок/scrub/max_tokens не применяются
    (точный legacy-путь). Резолв per-call, никогда не бросает (R3)."""
    try:
        from config.settings import settings
        return bool(getattr(settings, "DIRECT_RESPONSE_PLAN_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def rich_delivery_enabled() -> bool:
    """Kill-switch ``DIRECT_RICH_DELIVERY_ENABLED`` (env, default ON)."""
    try:
        from config.settings import settings
        return bool(getattr(settings, "DIRECT_RICH_DELIVERY_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def tool_plan_enabled() -> bool:
    """Kill-switch ``DIRECT_TOOL_PLAN_ENABLED`` (env, default ON; фаза 2).

    OFF → мульти-шаговый DAG-план не строится вовсе (запросы идут прежним
    model-driven путём цикла; байт-паритет). Резолв per-call, не бросает."""
    try:
        from config.settings import settings
        return bool(getattr(settings, "DIRECT_TOOL_PLAN_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def longform_max_output_tokens() -> int | None:
    """``max_tokens`` для longform-планов; ``<=0``/ошибка -> None (off).

    Консервативный код-дефолт 4096 (env ``DIRECT_LONGFORM_MAX_OUTPUT_TOKENS``);
    model-aware clamp - фаза 2 (реестр max_output асинхронный, per-turn
    сетевой вызов недопустим). Передаётся ТОЛЬКО для явно полных задач."""
    try:
        from config.settings import settings
        value = int(getattr(settings, "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS",
                            DEFAULT_LONGFORM_MAX_OUTPUT_TOKENS))
    except (TypeError, ValueError):
        value = DEFAULT_LONGFORM_MAX_OUTPUT_TOKENS
    except Exception:      # pragma: no cover - защитная ветка
        return None
    if value <= 0:
        return None
    return min(value, _MAX_OUTPUT_TOKENS_CEILING)


# ── §5: backward-compat алиасы casual/serious/deep_research ─────────────────

MODE_ALIAS_PLANS: dict[str, ResponsePlan] = {
    "casual": ResponsePlan(task_kind="social_chat", extent="compact",
                           structure="chat", delivery_hint="plain",
                           tool_policy="auto", source="mode_alias"),
    "serious": ResponsePlan(task_kind="explanation", extent="normal",
                            structure="answer", delivery_hint="plain",
                            tool_policy="auto", source="mode_alias"),
    "deep_research": ResponsePlan(task_kind="research", extent="detailed",
                                  structure="report", delivery_hint="rich",
                                  tool_policy="auto", source="mode_alias"),
}


def plan_from_response_mode(mode: str) -> ResponsePlan | None:
    """§5 mapping: старый режим -> оси плана (compat, не источник routing)."""
    candidate = str(mode or "").strip().lower()
    return MODE_ALIAS_PLANS.get(candidate)


# ── §12: детерминированная классификация (0 LLM) ─────────────────────────────

_PEER_PREFIX_RE = re.compile(
    r"^(?:(?:бот(?:ина|яра|ик)?|@[\w_]+)[,:]?\s+)+", re.IGNORECASE)

_EXPLICIT_LONG_RE = re.compile(
    r"подробн|детальн|разв[её]рнут|развернут|распиши|полный разбор|"
    r"по полочкам|исчерпывающ|максимально полно|вс[её] в деталях|напиши статью|"
    r"сделай статью", re.IGNORECASE)
_EXPLICIT_SHORT_RE = re.compile(
    r"коротко|короче|кратко|вкратце|в двух словах|пару слов|"
    r"пару предложений|одним предложением|одной фразой|одним словом|"
    r"только вывод|tl;?dr", re.IGNORECASE)
_CREATIVE_RE = re.compile(
    r"фанфик|истори[ю]|рассказ|новелл|повесть|сценарий|стих|поэм|хокку|"
    r"пьес|придумай|сочини", re.IGNORECASE)
_EXPLAIN_RE = re.compile(
    r"объясни|объяснить|как работает|как устроен|почему|в ч[её]м разниц|"
    r"разниц[ау]\s|чем отличает|разбери|что такое|расскажи про|расскажи о|"
    r"как сделать", re.IGNORECASE)
_COMPARE_RE = re.compile(
    r"сравни|что лучше|vs\.?\s|отличи\b|против\b", re.IGNORECASE)
_RESEARCH_RE = re.compile(
    r"исследован|доклад|отч[её]т\b|отчет\b|глубокий анализ|проанализируй|"
    r"полный обзор|изучи|собери (?:вс[её]|данные|инфу)", re.IGNORECASE)
_SUMMARY_RE = re.compile(
    r"выжимк|перескажи|саммари|краткое содержание|сократи|конспект", re.IGNORECASE)
_STEPS_RE = re.compile(r"по шагам|пошагов|инструкци|how-?to", re.IGNORECASE)
_NOSTALGIA_RE = re.compile(
    r"помнишь|помните|как мы тогда|что было с|кто был тот|год назад|"
    r"лет назад", re.IGNORECASE)
_MEDIA_DL_RE = re.compile(r"скачай|сгрузи|загрузи видео|сохрани видео", re.IGNORECASE)
_MEDIA_GEN_RE = re.compile(
    r"нарисуй|сгенерируй (?:картин|изображ)|сделай картинку|сделай изображение",
    re.IGNORECASE)
_TRANSCRIBE_RE = re.compile(
    r"транскрибируй|расшифруй видео|транскрипц", re.IGNORECASE)
_TOOL_HINT_RE = re.compile(
    r"посмотри в интернете|поищи|погугли|прочитай ссылку|найди в интернете|"
    r"проверь в сети|проверь в интернете|свежие данные|актуальные новости",
    re.IGNORECASE)
# Фаза 2 (§17): явные мульти-данные запросы — сравнение/совместное чтение
# нескольких ссылок. ОДНА ссылка/без ссылок → план не строится (обычный путь).
_MULTI_READ_RE = re.compile(
    r"сравни|сравнение|что лучше|отличи|разниц|vs\.?\s|прочитай|изучи|"
    r"перескажи|выжимк|саммари|обе ссылки|что в (?:этих|обеих)", re.IGNORECASE)
_URL_STRIP_RE = re.compile(r"https?://\S+")
_YESNO_RE = re.compile(r"^\s*да\s*(?:или|/|-)\s*нет\b", re.IGNORECASE)

_WORD_SPLIT_RE = re.compile(r"\s+")

_EXTENT_OF_TASK = {
    "creative_writing": ("longform", "story"),
    "research": ("detailed", "report"),
    "comparison": ("detailed", "comparison"),
    "explanation": ("detailed", "explanation"),
    "summarization": ("compact", "summary"),
    "historical_recall": ("normal", "answer"),
    "media_download": ("normal", "answer"),
    "media_generation": ("normal", "answer"),
    "transcription": ("normal", "answer"),
}


def classify_request(query) -> ResponsePlan:
    """Детерминированный план по тексту запроса (никогда не бросает).

    Приоритет: (1) task-kind по маркерам; (2) явная инструкция длины (§12)
    перекрывает extent task-kind'а; (3) короткий вопрос без маркеров -> micro;
    (4) болтовня -> compact. R17: текст не логируется.

    ASAP 7 (§1.8 demote): в primary path (``flags.direct_l1_enabled=ON``)
    НЕ вызывается — semantic brain теперь L1 Planner
    (services/direct_l1). Осталась как safe fallback при L1 outage
    (direct_l1.fallback_plan) и в legacy-ветке
    (``DIRECT_L1_ENABLED=false``, байт-паритет)."""
    text = str(query or "").strip()
    plan = ResponsePlan(source="default")
    if not text:
        return plan
    stripped = _PEER_PREFIX_RE.sub("", text).strip() or text
    low = stripped.lower()

    task_kind = ""
    structure = "answer"
    tool_policy = "auto"
    if _MEDIA_DL_RE.search(low):
        task_kind = "media_download"
    elif _MEDIA_GEN_RE.search(low):
        task_kind = "media_generation"
    elif _TRANSCRIBE_RE.search(low):
        task_kind = "transcription"
    elif _RESEARCH_RE.search(low):
        task_kind = "research"
    elif _CREATIVE_RE.search(low):
        task_kind = "creative_writing"
    elif _SUMMARY_RE.search(low):
        task_kind = "summarization"
    elif _COMPARE_RE.search(low):
        task_kind = "comparison"
    elif _EXPLAIN_RE.search(low):
        task_kind = "explanation"
    elif _NOSTALGIA_RE.search(low):
        task_kind = "historical_recall"
    elif _STEPS_RE.search(low):
        task_kind = "explanation"

    explicit_short = bool(_EXPLICIT_SHORT_RE.search(low))
    explicit_long = bool(_EXPLICIT_LONG_RE.search(low))
    wants_tools = bool(_TOOL_HINT_RE.search(low))

    if task_kind:
        extent, structure = _EXTENT_OF_TASK.get(
            task_kind, ("normal", "answer"))
    else:
        extent, structure = "normal", "answer"

    if task_kind == "creative_writing":
        tool_policy = "none"       # §16: фанфик не требует web/memory
    if wants_tools or task_kind in ("research", "comparison", "media_download",
                                    "media_generation", "transcription",
                                    "summarization"):
        tool_policy = "auto"

    # §12: явная инструкция длины имеет высокий приоритет над task-kind.
    if explicit_short and not explicit_long:
        extent = "compact"
        source = "explicit"
    elif explicit_long:
        extent = "longform"
        source = "explicit"
    elif task_kind:
        source = "task-kind"
    else:
        source = "default"

    # (3) короткий вопрос без семантических маркеров -> micro (§8 fast path).
    if task_kind == "" and not explicit_long and not explicit_short \
            and stripped.endswith("?") \
            and len(_WORD_SPLIT_RE.split(stripped)) <= 3:
        task_kind = "direct_answer"
        extent = "micro"
        structure = "answer"
        source = "default"

    if task_kind == "direct_answer":
        if _YESNO_RE.match(low):
            extent = "micro"

    if task_kind == "":
        task_kind = "social_chat"
        structure = "chat"
        if extent == "normal":
            extent = "compact"

    # §23 Delivery Router policy: media-задача → media-канал (тул доставляет
    # медиа сам; Writer-регенерация не нужна при успехе, §18-I).
    delivery = "rich" if (task_kind == "research"
                          or structure == "report") else "plain"
    if task_kind in ("media_download", "media_generation"):
        delivery = "media"
    return ResponsePlan(task_kind=task_kind, extent=extent,
                        structure=structure, delivery_hint=delivery,
                        tool_policy=tool_policy, source=source)


# ── ASAP 7 (§1.8/§2.5): explicit-form parser — deterministic override ────────
# Явная форма пользователя применяется ПОСЛЕ L1 поверх semantic extent.
# Закрытый результат — токены L1_EXTENTS (services/direct_l1): одна из форм
# или "" (нет явной формы). Regex-семейства существующие (§12); «одним
# словом» добавлено (§2.5 ТЗ). Никогда не бросает.

_EXPLICIT_ONE_WORD_RE = re.compile(r"одним словом|в одно слово", re.IGNORECASE)


def explicit_form_override(query) -> str:
    """Явная инструкция формы (§2.5): ``one_word`` | ``longform`` |
    ``compact`` | ``""``. Приоритет: one_word > longform > compact
    (как в classify_request §12: явная длинная сильнее явной короткой).
    Никогда не бросает."""
    try:
        text = str(query or "").strip()
        if not text:
            return ""
        low = _PEER_PREFIX_RE.sub("", text).strip().lower()
        if not low:
            return ""
        if _EXPLICIT_ONE_WORD_RE.search(low):
            return "one_word"
        if _EXPLICIT_LONG_RE.search(low):
            return "longform"
        if _EXPLICIT_SHORT_RE.search(low):
            return "compact"
        return ""
    except Exception:      # pragma: no cover - parser не роняет запрос
        return ""


# ── §11: extent-блоки Вербализатора / системного промпта ────────────────────

_EXTENT_BLOCKS: dict[str, str] = {
    "micro": (
        "ОЖИДАЕМАЯ ПОЛНОТА: МИКРО. Ответ - одна короткая фраза или да/нет. "
        "Без разворотов и списков: ровно то, о чём спросили."),
    "compact": (
        "ОЖИДАЕМАЯ ПОЛНОТА: КОМПАКТНО. Несколько коротких живых предложений "
        "по делу. Без вступлений и итоговых обобщений."),
    "normal": (
        "ОЖИДАЕМАЯ ПОЛНОТА: ОБЫЧНАЯ. Раскрой суть в меру: несколько "
        "предложений, самая важная деталь не выбрасывается."),
    "detailed": (
        "ОЖИДАЕМАЯ ПОЛНОТА: ПОДРОБНО. Раскрой тему полностью: ключевые "
        "пункты, причины и нужные детали. Не сокращай ответ так, чтобы "
        "задача осталась неполной. Воду не лей, но и не обрубай."),
    "longform": (
        "ОЖИДАЕМАЯ ПОЛНОТА: РАЗВЁРНУТЫЙ ТЕКСТ. Задача требует законченного "
        "полного результата. Заверши её до конца: не обрывай после "
        "вступления и не подменяй результат пересказом. Длина определяется "
        "задачей, а не лимитом предложений."),
    "exhaustive": (
        "ОЖИДАЕМАЯ ПОЛНОТА: ИСЧЕРПЫВАЮЩЕ. Включи все найденные детали и "
        "оговорки. Заверши задачу полностью, ничего существенного не "
        "выбрасывай."),
}

_STRUCTURE_RU = {
    "chat": "болтовня",
    "answer": "прямой ответ",
    "explanation": "разбор",
    "story": "история",
    "summary": "выжимка",
    "comparison": "сравнение",
    "report": "отчёт",
    "steps": "шаги",
}


def render_extent_block(plan: ResponsePlan | None) -> str:
    """Блок «ОЖИДАЕМАЯ ПОЛНОТА» для промпта; неизвестный/None -> "".

    Extent-блок заменяет собой старый mode-блок длины (§11) и едет и в
    системный промпт Stage-1, и в собранный Вербализатор."""
    if plan is None:
        return ""
    extent = normalize_extent(plan.extent)
    if not extent:
        return ""
    block = _EXTENT_BLOCKS[extent]
    structure = normalize_structure(plan.structure)
    if structure and structure != "chat":
        block = (block + " Форма результата: "
                 + _STRUCTURE_RU[structure] + ".")
    return block


# ── §11/§32: prompt-conflict scrub (старый cap-текст из PG-кастома) ─────────

_CAP_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"Ты должен отвечать ОЧЕНЬ коротко\.?", re.IGNORECASE),
    re.compile(
        r"Твой ответ должен состоять СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ "
        r"ПРЕДЛОЖЕНИЙ\.?", re.IGNORECASE),
    re.compile(
        r"Если напишешь больше двух предложений\s*[-—]\s*система упадет\.?",
        re.IGNORECASE),
    re.compile(r"Максимум пара язвительных фраз\.?", re.IGNORECASE),
    re.compile(r"Коротко\s*:\s*одно[-\s]два предложения\.?", re.IGNORECASE),
)
_ORPHAN_NUMBERING_RE = re.compile(r"^\s*\d+\.\s*$", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def strip_cap_phrases(text: str) -> tuple[str, int]:
    """Вычистить канонические cap-фразы из собранного промпта.

    Возвращает ``(очищенный текст, число удалённых фраз)``. БД/PG не правит -
    только финальная сборка (§11). Никогда не бросает."""
    cleaned = str(text or "")
    removed = 0
    for pattern in _CAP_PATTERNS:
        cleaned, n = pattern.subn("", cleaned)
        removed += n
    if removed:
        cleaned = _ORPHAN_NUMBERING_RE.sub("", cleaned)
        cleaned = _BLANK_RUN_RE.sub("\n\n", cleaned)
    return cleaned, removed


def scrub_for_plan(text: str, plan: ResponsePlan | None) -> tuple[str, int]:
    """Scrub только для longform-семейства; иначе текст без изменений."""
    if plan is None or not plan.is_longform():
        return str(text or ""), 0
    return strip_cap_phrases(text)


def plan_snapshot(plan: ResponsePlan | None) -> dict:
    """R17-safe словарь осей плана (observability/логи, без текста запроса)."""
    if plan is None:
        return {}
    return dataclasses.asdict(plan)


# ── MCA-23 фаза 2 (§17): детерминированный multi-tool план (0 LLM) ──────────

def resolve_tool_name(name) -> str:
    """§14: capability name → реальный tool; реальное имя — как есть.
    Неизвестные строки проходят как есть — валидацию по runtime-набору
    (неизвестный tool не исполняется, §38) делает нормализация плана
    в tool_loop.normalize_tool_plan. Никогда не бросает."""
    candidate = str(name or "").strip()
    if not candidate:
        return ""
    return CAPABILITY_TOOLS.get(candidate, candidate)


def build_tool_plan(query, *, available_tools=None,
                    max_fetch_steps: int = PLAN_MAX_FETCH_STEPS) -> list[dict]:
    """План инструментов для ЯВНЫХ мульти-данных запросов (§17, 0 LLM).

    ASAP 7 (§1.4/§1.8 demote): дет. fast-path ТОЛЬКО для объективного факта
    «2+ URL + явное сравнение»; primary источник мульти-тул — capability-
    подсет L1 (services/direct_capabilities). В L1-ветке вызывается с
    ``available_tools`` = resolved-подсет.

    Активация — только при (а) маркере совместного чтения/сравнения и
    (б) ≥2 уникальных http(s)-ссылках в запросе. Шаги:

    .. code-block:: python
        {"step_id": str, "tool": str, "arguments": dict,
         "depends_on": [step_id...], "failure_policy": "required|optional"}

    Контракт: инструменты — ТОЛЬКО имена из runtime-набора (``available_tools``
    — имена анонсированных LLM схем; шаг с неизвестным именем выбрасывается,
    §38); <2 исполняемых шага → ``[]`` (обычный model-driven путь, байт-
    паритет). failure_policy fetch-шагов = ``optional`` (§19: partial failure
    сохраняет успешные результаты), явный web-hint → optional web-шаг (§E).
    R17: текст запроса не логируется. Никогда не бросает.
    """
    try:
        text = str(query or "").strip()
        if not text or not tool_plan_enabled():
            return []
        stripped = _PEER_PREFIX_RE.sub("", text).strip() or text
        low = stripped.lower()
        if not _MULTI_READ_RE.search(low):
            return []
        from services.smartmodule_urls import extract_urls
        urls: list[str] = []
        for url in extract_urls(stripped):
            if url not in urls:
                urls.append(url)
        if len(urls) < 2 or len(urls) > max(2, int(max_fetch_steps)):
            return []
        steps: list[dict] = []
        for index, url in enumerate(urls, 1):
            steps.append({
                "step_id": f"fetch_{index}",
                "tool": "fetch_article",
                "arguments": {"url": url},
                "depends_on": [],
                "failure_policy": "optional",
            })
        if _TOOL_HINT_RE.search(low):
            # §E: опциональная проверка интернета поверх сравнения ссылок.
            search_query = _URL_STRIP_RE.sub(" ", stripped)
            search_query = re.sub(r"\s{2,}", " ", search_query).strip(" ,;-")
            if search_query:
                steps.append({
                    "step_id": "web_1",
                    "tool": "execute_web_search",
                    "arguments": {"query": search_query[:256]},
                    "depends_on": [],
                    "failure_policy": "optional",
                })
        # §38: шаги с именем вне runtime-набора не исполняются.
        if available_tools is not None:
            allowed = {str(t or "") for t in available_tools}
            steps = [s for s in steps if s["tool"] in allowed]
        return steps if len(steps) >= 2 else []
    except Exception:      # pragma: no cover - план не роняет запрос
        return []


# ── MCA-23 фаза 2 (§20): clarification — один конкретный вопрос ─────────────

CLARIFY_MEDIA_TARGET = (
    "Скинь ссылку на видео — скачаю. Если видео уже есть в чате, "
    "просто ответь реплаем на него.")

_CLARIFY_KINDS = frozenset({"media_download", "transcription"})


def clarification_question(plan: ResponsePlan | None, *,
                           has_target: bool) -> str:
    """§20: media/transcription без разрешимой цели → ОДИН конкретный
    вопрос (что именно сделать, а не «уточните пожалуйста»). Цель
    разрешима из сообщения/реплая/нативного медиа → ``""`` — не спрашиваем.
    Никогда не бросает."""
    if plan is None or has_target:
        return ""
    if str(getattr(plan, "task_kind", "")) in _CLARIFY_KINDS:
        return CLARIFY_MEDIA_TARGET
    return ""


# ── MCA-23 фаза 2 (§18-I/§23): media-ветка Delivery Router ──────────────────

def is_media_delivery(plan: ResponsePlan | None) -> bool:
    """План требует media-канала (media_download/media_generation)."""
    return plan is not None and plan.delivery_hint == "media"


def media_writer_needed(plan: ResponsePlan | None, raw) -> bool:
    """§18-I: нужен ли Writer после tool-цикла.

    media-план с УСПЕШНО доставленным медиа → False (тул уже доставил
    медиа; бесполезная Writer-регенерация не запускается, idempotent).
    Провал media-тула / не-media план / нет envelopes → True (честная
    деградация §19 и прежнее поведение). Никогда не бросает."""
    if not is_media_delivery(plan):
        return True
    try:
        from services.tool_loop import media_delivered
        return not media_delivered(raw)
    except Exception:      # pragma: no cover - защитная ветка
        return True
