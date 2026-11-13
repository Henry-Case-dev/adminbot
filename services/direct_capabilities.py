"""ASAP 7 (F1, architecture.md §1.4) — Capability→tools allowlist L1.

Единственный источник маппинга capability (L1) → фактические имена tools
(``services/tool_schemas.py``). Механика §1.4:

  ``resolved = CAPABILITY_TOOLS ∩ active_tools(lore, image)``

  * unknown/hallucinated capability → drop + agentic event
    ``L1_CAPABILITY_REJECTED (capability, reason)`` + честная пометка L2
    «недоступно» (D15). Не ошибка прогона;
  * ``statistics`` — тулa в наборе НЕТ (MCA-15 stats-intent — дет.
    пре-блок, не tool): резолвится в ∅ → честная пометка L2;
  * ``build_tool_plan`` (2+ URL + явное сравнение) остаётся дет. fast-path
    в response_extent — primary источник мульти-тул: capability-подсет,
    анонсируемая в ``chat_with_tools`` (§22 п.10 закрыт).

Никогда не бросает; имена tools сверяются с анонсированным runtime-набором.
"""
from __future__ import annotations

import dataclasses
import logging
import re

logger = logging.getLogger(__name__)

# §1.4: статическая таблица (точные имена tool_schemas.py).
CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "web_search": ("execute_web_search",),
    "fetch_url": ("fetch_article",),
    "chat_history": ("get_recent_history",),
    "chat_memory": ("query_chat_memory",),
    "user_memory": ("get_user_context",),
    "historical_search": ("dig_into_lore", "compile_lore_story"),
    "fact_check": ("fact_check",),
    "image_understanding": ("recognize_image",),
    "media_download": ("download_media",),
    "transcription": ("transcribe_video",),
    "video_summary": ("summarize_video",),
    "image_generation": ("generate_image",),
    # ASAP5 §20 (edit-route): существующий media_execution.submit_edit →
    # инструмент edit_image (маршрут Direct Chat; второй набор провайдеров
    # не создаётся).
    "image_edit": ("edit_image",),
    # ADD-TR.3 п.4 (слайс ADTR-TOOLS, 19.10.2026): health/checkup — реальный
    # инструмент get_bot_health (тот же путь, что канонический «чекап» 0g;
    # имя capability «health» уже принято в response_extent.CAPABILITY_TOOLS).
    # Без этой строки L1-планировщик не видел capability и свободное «бот,
    # как состояние сервера?» до инструмента не доходило (resolved = ∅).
    "health": ("get_bot_health",),
    # SELF-DIAG-01 corrective (13.11.2026, owner §1/§3): существующие
    # диагностические инструменты становятся адресуемыми возможностями L1.
    # Имена — из `diagnostic_policy.CAPABILITIES` (тот же ACL); второго
    # реестра/агента нет.
    "source_code": ("read_source_code",),
    "deep_diagnostics": ("inspect_runtime",),
    # §1.4: тулa нет — дет. пре-блок MCA-15; честная пометка L2 (не error).
    "statistics": (),
}

REASON_UNKNOWN = "unknown_capability"
REASON_NO_TOOL = "no_tool"
REASON_NOT_ACTIVE = "tool_not_active"
REASON_LOW_CONFIDENCE = "low_confidence"
#: SOUL-1 W10 (§5.10/§5.18): инструмент есть, но в этом чате недоступен по
#: реальному состоянию (модуль/ключ/квота) — наблюдаемый блокер, не тишина.
REASON_NOT_READY = "capability_not_ready"

# CFG-07A-2 (SF-15): человеческие формулировки reason-кодов для пометки
# Writer'а (коды в речь не идут — ни в этой пометке, ни по контракту канона).
REASON_LABELS: dict[str, str] = {
    REASON_UNKNOWN: "такой возможности нет",
    REASON_NO_TOOL: "инструмента для этого нет",
    REASON_NOT_ACTIVE: "инструмент сейчас не работает",
    REASON_LOW_CONFIDENCE: "уверенности мало, надёжнее без этого",
    REASON_NOT_READY: "сейчас недоступно (модуль, ключ или квота)",
}

#: CFG-07A-2 (SF-15): человеческие имена capability для пометки Writer'а
#: (те же смыслы, что в §5.1-каталоге, без англ. идентификаторов).
CAPABILITY_LABELS: dict[str, str] = {
    "web_search": "поиск в интернете",
    "fetch_url": "чтение страницы по ссылке",
    "chat_history": "свежая история чата",
    "chat_memory": "память чата",
    "user_memory": "данные о собеседнике",
    "historical_search": "старая переписка и лор",
    "fact_check": "проверка факта",
    "image_understanding": "разбор картинки",
    "media_download": "скачивание медиа",
    "transcription": "расшифровка видео",
    "video_summary": "пересказ видео",
    "image_generation": "генерация картинок",
    "image_edit": "редактирование картинок",
    "health": "здоровье сервера",
    "source_code": "чтение исходного кода",
    "deep_diagnostics": "глубокая диагностика",
    "statistics": "статистика чата",
}


def resolve_capabilities(requested, active_tool_names,
                         *, skip_capabilities=()) -> tuple[list[str],
                                                           list[tuple[str, str]]]:
    """§1.4: ``(resolved_tool_names, rejected[(capability, reason)])``.

    Порядок resolved — по порядку объявления capability (дет.); дубликат
    tool от разных capabilities схлопывается. Неизвестное имя → drop с
    reason; известное без активного тула → ``tool_not_active``; пустая
    таблица (statistics) → ``no_tool``. Никогда не бросает."""
    resolved: list[str] = []
    rejected: list[tuple[str, str]] = []
    active = {str(t or "").strip() for t in (active_tool_names or ())}
    skipped = {str(c or "").strip().lower() for c in (skip_capabilities or ())}
    for raw in (requested or ()):
        name = str(raw or "").strip().lower()
        if not name:
            continue
        if name in skipped:
            rejected.append((name, REASON_LOW_CONFIDENCE))
            continue
        tools = CAPABILITY_TOOLS.get(name)
        if tools is None:
            rejected.append((name, REASON_UNKNOWN))
            continue
        if not tools:
            rejected.append((name, REASON_NO_TOOL))
            continue
        hit = False
        for tool in tools:
            if tool in active and tool not in resolved:
                resolved.append(tool)
                hit = True
        if not hit:
            rejected.append((name, REASON_NOT_ACTIVE))
    return resolved, rejected


def available_capabilities(active_tool_names) -> list[str]:
    """Список capability, которые L1 может запросить при данном
    runtime-наборе (для контекста §1.5): тул активен ИЛИ capability без
    тула (statistics — честно присутствует, резолвится в пометку)."""
    active = {str(t or "").strip() for t in (active_tool_names or ())}
    caps: list[str] = []
    for cap, tools in CAPABILITY_TOOLS.items():
        if not tools or any(t in active for t in tools):
            caps.append(cap)
    return caps


def schemas_for_names(names, schemas) -> list[dict]:
    """Анонсируемый подсет схем: только имена из ``names`` (§1.1: в
    ``chat_with_tools`` уходит ТОЛЬКО resolved-подсет). ``names is None`` →
    полный набор (легаси-семантика). Никогда не бросает."""
    if names is None:
        return [s for s in (schemas or ()) if isinstance(s, dict)]
    wanted = {str(n or "").strip() for n in (names or ())}
    out: list[dict] = []
    for schema in (schemas or ()):
        try:
            name = str(((schema or {}).get("function") or {}).get("name")
                       or "").strip()
        except Exception:      # pragma: no cover - защитная ветка
            continue
        if name and name in wanted:
            out.append(schema)
    return out


def rejected_note(rejected) -> str:
    """Честная пометка L2 «недоступно» (§1.4/D15): одна строка-список;
    пусто → "". Никогда не бросает.

    CFG-07A-2 (SF-15/MB-11/MB-12): capability-имена и reason-коды уходят в
    Writer только в ЧЕЛОВЕЧЕСКОЙ формулировке (пометка — данные для модели,
    а не словарь для пересказа; контракт «не упоминай служебные пометки» —
    в каноне Direct). Неизвестный код/имя деградирует в нейтральное
    «сейчас недоступно» без англ. кода.
    """
    items = []
    for cap, reason in (rejected or ()):
        name = CAPABILITY_LABELS.get(str(cap or "").strip(),
                                     "эта возможность")
        why = REASON_LABELS.get(str(reason or "").strip(), "сейчас недоступно")
        items.append(f"{name} - {why}")
    if not items:
        return ""
    return ("Недоступные возможности (инструмента нет — не выдумывай "
            "результат, при необходимости честно скажи об этом): "
            + ", ".join(items))


# ═══════════════════════════════════════════════════════════════════════════
# §5.1 (SOUL-AMD.5.2/5.9/5.10): Semantic Intent → Capability
# ═══════════════════════════════════════════════════════════════════════════

#: Смысловые интенты действия → capability (та же таблица CAPABILITY_TOOLS).
INTENT_CREATE_IMAGE = "create_image"
#: ASAP5 §20: редактирование СУЩЕСТВУЮЩЕГО изображения — отдельный интент,
#: отдельная capability (изменение исходника ≠ создание нового).
INTENT_EDIT_IMAGE = "edit_image"
INTENT_WEB_SEARCH = "web_search"
INTENT_FACT_CHECK = "fact_check"
INTENT_CHAT_MEMORY = "chat_memory"
INTENT_NONE = ""

INTENT_CAPABILITY: dict[str, str] = {
    INTENT_CREATE_IMAGE: "image_generation",
    INTENT_EDIT_IMAGE: "image_edit",
    INTENT_WEB_SEARCH: "web_search",
    INTENT_FACT_CHECK: "fact_check",
    INTENT_CHAT_MEMORY: "chat_memory",
}

CONFIDENCE_HIGH = "high"
CONFIDENCE_AMBIGUOUS = "ambiguous"
CONFIDENCE_NONE = "none"

REASON_CREATE_COMMAND = "create_image_command"
REASON_CREATE_NEED = "create_image_need"
REASON_CREATE_CONCEIVE = "create_image_conceive_only"
REASON_CREATE_NEGATED = "create_image_negated"
REASON_CREATE_DEICTIC = "create_verb_without_object"
#: SOUL-1 W10 fix (review-w10 F2): чужая просьба/пересылка/«я сам нарисую» —
#: не поручение пользователя (наблюдаемая причина отказа от генерации).
REASON_CREATE_REPORTED = "create_image_reported"
REASON_CREATE_FORWARDED = "create_image_forwarded"
REASON_CREATE_SELF = "create_image_self_action"
#: ASAP5 §20: наблюдаемые причины edit-интента.
REASON_EDIT_REQUEST = "edit_image_request"
REASON_SEARCH = "search_request"
REASON_FACTCHECK = "factcheck_request"
REASON_MEMORY = "memory_request"
REASON_NONE = "no_action_intent"

# ── P0-A (2026-11-10, owner corrective) ─────────────────────────────────────
# У лексики НЕТ семантического авторитета для генерации изображений.
# Словари `_DRAW_VERB_STRONG` / `_DRAW_VERB_PREFIXED` / `_CREATE_VERB_GENERIC` /
# `_IMAGE_OBJECT` и все производные условия («действие+объект», «потребность+
# объект», conceive/negation/deictic/reported/self-attribution) УДАЛЕНЫ.
#
# Причина — реальный инцидент: в вопросе «чем отличается манга от не манги?
# тем что её японцы рисуют…» стем «рису» классифицировал реплику как поручение
# и ход заканчивался сообщением о квоте изображений вместо ответа по смыслу.
# Частное исключение для слова «рисуют» запрещено (P0-A §1/§7): устранён
# механизм, а не слово.
#
# Единственный детерминированный путь пользовательской генерации — явная
# команда «Бот, нарисуй <промпт>» (`services/image_generation.IMAGE_KEYWORD_RE`:
# обращение + императив; там же снятие обёртки и штатные параметры). Любой
# другой запрос решает L1 — его план (`capabilities_needed`/выбор инструмента)
# и есть семантический авторитет для `generate_image`. Второй LLM-классификатор,
# новые словари и новые настройки не вводятся (P0-A §5/§7).
#
# Поэтому `detect_action_intent` ниже возвращает image-интент ТОЛЬКО для самой
# команды (зеркалит `image_generation.is_image_keyword`, чтобы существующие
# двери пре-гейта/готовности оставались согласованными) и продолжает
# детектировать НЕ-image действия (поиск/фактчек/память).
_WORD_RE = re.compile(r"[а-яёa-z0-9\-]+")

# P1 semantic-routing (2026-11-10, §7): это НАБЛЮДАТЕЛЬНЫЕ маркеры формы
# запроса, а не семантический авторитет. Поручением искать/проверять/вспоминать
# считается только явная команда реестра (`services/command_registry.py`) или
# решение L1; ни один из этих наборов не форсирует tool call и не подменяет
# ось поиска.
_SEARCH_MARKERS = ("поищи", "поиск", "найди", "найти", "загугли", "погугли",
                   "в интернете", "в сети", "search")
_FACTCHECK_MARKERS = ("фактчек", "факт-чек", "проверь факт", "проверить факт",
                      "правда ли", "это правда", "проверь это", "fact check")
_MEMORY_MARKERS = ("что я говорил", "что я писал", "напомни", "вспомни",
                   "что было в чате", "помнишь")

#: Код-блоки/инлайн-код — пример кода, а не реплика пользователя.
_FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _without_code(text: str) -> str:
    """Текст без код-блоков и инлайн-кода (пример кода ≠ реплика)."""
    return _INLINE_CODE_RE.sub(" ", _FENCED_CODE_RE.sub(" ", str(text or "")))


def _has_stem(text: str, stems) -> bool:
    """Матч маркера по СЛОВАМ (граница слова), а не по подстроке:
    фразовый маркер («в интернете») ищется как подстрока, стем — только как
    начало слова. Не-image маркеры (поиск/фактчек/память) — форма запроса."""
    tokens = _WORD_RE.findall(text)
    for stem in stems:
        if " " in stem or "-" in stem:      # фразовый маркер
            if stem in text:
                return True
        elif any(word.startswith(stem) for word in tokens):
            return True
    return False


def _normalize(text: str) -> str:
    return str(text or "").strip().lower().replace("ё", "е")


# ── явная ФОРМА просьбы о проверке факта (review §9.5) ───────────────────────
# Словарь НЕ расширяется (§1.3): те же восемь маркеров, но подстрочный матч в
# любом месте текста сигналом больше не является — «вот это правда круто»,
# «спасибо, всё правда, как ты и сказал», «это правда было смешно» и шутка с
# цитатой («он сказал "правда ли это", и мы посмеялись») — обычная речь.
# Маркеры делятся по ГРАММАТИЧЕСКОЙ форме (это не новая лексика):
#   * просьба по форме («проверь факт…», «фактчек:…») — засчитывается в начале
#     клаузы;
#   * «правда ли» несёт вопросительную частицу «ли» — тоже в начале клаузы;
#   * «это правда» — утверждение, засчитывается только в вопросительной клаузе.
_FACTCHECK_QUESTION_START_MARKERS = ("правда ли",)
_FACTCHECK_STATEMENT_MARKERS = ("это правда",)
_FACTCHECK_REQUEST_MARKERS = tuple(
    marker for marker in _FACTCHECK_MARKERS
    if marker not in _FACTCHECK_QUESTION_START_MARKERS
    and marker not in _FACTCHECK_STATEMENT_MARKERS)
_WORD_CHARS = "а-яёa-z0-9"
#: Границы клаузы: точка/!/?/;/:/многоточие/запятая/перевод строки. Запятая
#: режет клаузу: «проверь, правда ли это» = просьба + вопрос, «спасибо, всё
#: правда, как ты и сказал» = три утверждения (обращение «бот,» тоже уходит).
_CLAUSE_BOUNDARY_RE = re.compile(r"[.!?;:…,\n]+")


def _phrase_regex(phrases) -> "re.Pattern":
    """Фразовый маркер как отдельное СЛОВО (граница с обеих сторон).

    «неправда ли» не содержит маркера «правда ли» (слева буква), «вот это
    правда круто» содержит, но не в форме запроса."""
    alternatives = "|".join(re.escape(str(p)) for p in phrases)
    return re.compile(
        rf"(?<![{_WORD_CHARS}])(?:{alternatives})(?![{_WORD_CHARS}])")


_FACTCHECK_PHRASE_RE = _phrase_regex(_FACTCHECK_MARKERS)
_FACTCHECK_REQUEST_RE = _phrase_regex(_FACTCHECK_REQUEST_MARKERS)
_FACTCHECK_QUESTION_START_RE = _phrase_regex(_FACTCHECK_QUESTION_START_MARKERS)


def _clauses(text: str):
    """Клаузы реплики: пары ``(текст, терминатор)``."""
    out: list[tuple[str, str]] = []
    start = 0
    for match in _CLAUSE_BOUNDARY_RE.finditer(text):
        out.append((text[start:match.start()], match.group(0)[:1]))
        start = match.end()
    out.append((text[start:], ""))
    return out


def _referential_hits(text: str) -> list:
    """Границы существующего референтного регекса (``неправда`` не считается).

    Лексика берётся из ``temporal_factcheck._REFERENTIAL_CLAIM_RE`` («проверь
    его слова», «не врёт?», «это правда?»); здесь добавляется только граница
    слова, чтобы «неправда» не читалось как «правда»."""
    try:
        from services import temporal_factcheck as _tf
        regex = _tf._REFERENTIAL_CLAIM_RE
    except Exception:      # pragma: no cover - защитная ветка
        return []
    hits = []
    for match in regex.finditer(text):
        if match.start() and text[match.start() - 1].isalnum():
            continue
        hits.append(match)
    return hits


def _referential_imperative_at_start(text: str) -> bool:
    """«проверь его слова / пост / сообщение» — просьба по форме в начале.

    Утверждения о правдивости («это правда…») в начале клаузы просьбой НЕ
    являются: «это правда было смешно» — обычная речь."""
    for match in _referential_hits(text):
        if match.start() == 0 and str(match.group(0)).startswith("проверь"):
            return True
    return False


def _referential_question(text: str) -> bool:
    """Референтная форма внутри вопросительной клаузы («не врёт?», «фейк?»)."""
    return bool(_referential_hits(text))


def is_explicit_factcheck_request(text) -> bool:
    """Явная просьба проверить факт: маркер + ФОРМА запроса (§1.3).

    Сигнал засчитывается, только если маркер (тот же набор) стоит в форме
    запроса: в начале клаузы («проверь факт: …», «фактчек: …», «правда ли,
    что …») либо в вопросительной клаузе («это правда?», «не врёт?»).
    Подстрока внутри утверждения сигналом не является, поэтому разговорная
    реплика не отменяет переиспользование прочитанного источника и не
    вызывает сетевой запрос. Никогда не бросает."""
    try:
        body = _without_code(_normalize(text))
        if not body:
            return False
        for clause, terminator in _clauses(body):
            core = clause.strip()
            if not core:
                continue
            if _FACTCHECK_REQUEST_RE.match(core):
                return True
            if _FACTCHECK_QUESTION_START_RE.match(core):
                return True
            if _referential_imperative_at_start(core):
                return True
            if terminator == "?":
                if _FACTCHECK_PHRASE_RE.search(core):
                    return True
                if _referential_question(core):
                    return True
        return False
    except Exception:      # pragma: no cover - защитная ветка
        return False


@dataclasses.dataclass(frozen=True)
class ActionIntent:
    """§5.1: смысловое намерение действия (дет., без LLM).

    ``intent`` — смысл («web_search»/«fact_check»/…); ``capability`` —
    capability из ``CAPABILITY_TOOLS``; ``confidence`` — ``high`` (действовать
    можно), ``ambiguous`` (нужен ОДИН уточняющий вопрос), ``none`` (действия
    нет). ``reason``/``evidence`` — наблюдаемая причина и слова-основание (R17:
    только слова запроса, без инфраструктуры).

    P0-A (2026-11-10): ``INTENT_CREATE_IMAGE`` детектором НЕ выдаётся — у
    лексики нет семантического авторитета для пользовательской генерации.
    Поля/свойства сохранены как СТРУКТУРНЫЙ контракт существующих потребителей
    (``_l1_capability_consistency``, ``intent_blockers``): сконструированный
    intent по плану L1 остаётся валидным, а словесный — больше не создаётся."""

    intent: str = INTENT_NONE
    capability: str = ""
    confidence: str = CONFIDENCE_NONE
    reason: str = REASON_NONE
    evidence: tuple[str, ...] = ()
    conceive_only: bool = False

    @property
    def actionable(self) -> bool:
        """Однозначное поручение создать изображение (можно действовать).

        P0-A: детектор такое поручение больше не выставляет — решение о
        генерации за явной командой «Бот, нарисуй …» либо за планом L1."""
        return (self.intent == INTENT_CREATE_IMAGE
                and self.confidence == CONFIDENCE_HIGH)

    @property
    def edit_actionable(self) -> bool:
        """ASAP5 §20: однозначное поручение ИЗМЕНИТЬ существующее изображение.

        Отдельно от ``actionable`` (создание): пре-гейт генерации не должен
        открывать генерацию для edit-просьбы — «новая независимая генерация
        не выдаётся за изменение оригинала»."""
        return (self.intent == INTENT_EDIT_IMAGE
                and self.confidence == CONFIDENCE_HIGH)


def _is_explicit_image_command(body: str) -> bool:
    """Реплика — явная команда «Бот, нарисуй <промпт>» (единственный
    словесный вход к генерации; определение команды живёт в одном месте —
    ``services/image_generation.is_image_keyword``). Никогда не бросает."""
    try:
        from services import image_generation as _ig
        return bool(_ig.is_image_keyword(body))
    except Exception:      # pragma: no cover - защитная ветка
        return False


def detect_action_intent(text, *, reply_text: str = "",
                         addressed: bool = False,
                         forwarded: bool = False) -> ActionIntent:
    """Детектор действий: явная команда генерации + не-image намерения.

    P0-A (2026-11-10, owner corrective): у лексики больше НЕТ семантического
    авторитета для пользовательской генерации. Стем «рису» в обычном вопросе
    («чем отличается манга… тем что её японцы рисуют?») давал
    ``INTENT_CREATE_IMAGE`` с высокой уверенностью, после чего ход завершался
    сообщением о квоте изображений вместо ответа по смыслу. Словари
    ``_DRAW_VERB_*``/``_CREATE_VERB_GENERIC``/``_IMAGE_OBJECT`` и производные
    эвристики (conceive/negation/deictic/reported/self) удалены и не
    восстанавливаются — ни здесь, ни в соседних слоях.

    Единственные два авторитета генерации:
      * явная команда «Бот, нарисуй <промпт>» — детерминированный fast-path
        (``image_generation.IMAGE_KEYWORD_RE`` + отмена в той же реплике);
      * план L1 (``capabilities_needed``/выбор инструмента модели).
    Этот детектор только ЗЕРКАЛИТ команду (чтобы существующие двери
    пре-гейта/готовности оставались согласованными), новых формулировок не
    добавляет.

    Прочие намерения (поиск/фактчек/память) — только НАБЛЮДАТЕЛЬНЫЙ сигнал
    формы запроса (телеметрия/диагностика). P1 semantic-routing (2026-11-10,
    §7): они больше не маршрутизируют ход и не форсируют tool call —
    ``execution_mode``/ось поиска получают решение из плана L1, а поручением
    считается только явная команда реестра (`services/command_registry.py`).

    Аргументы ``reply_text``/``addressed`` сохранены для совместимости
    вызывающих; ``forwarded=True`` (чужие слова) команду не исполняет.

    Никогда не бросает; без LLM-вызовов и I/O."""
    try:
        body = _without_code(_normalize(text))
        if not body:
            return ActionIntent()
        if _is_explicit_image_command(body):
            if forwarded:
                # Пересланная команда — чужие слова, не поручение пользователя.
                return ActionIntent(confidence=CONFIDENCE_NONE,
                                    reason=REASON_CREATE_FORWARDED,
                                    evidence=("explicit_command", "forwarded"))
            return ActionIntent(
                intent=INTENT_CREATE_IMAGE,
                capability=INTENT_CAPABILITY[INTENT_CREATE_IMAGE],
                confidence=CONFIDENCE_HIGH, reason=REASON_CREATE_COMMAND,
                evidence=("explicit_command",))
        # Прочие действия (паритет §5.18): поиск/фактчек/память. Маркер здесь —
        # ФОРМА запроса существующего маршрута, а не доказательство генерации.
        for markers, intent, reason in (
                (_FACTCHECK_MARKERS, INTENT_FACT_CHECK, REASON_FACTCHECK),
                (_SEARCH_MARKERS, INTENT_WEB_SEARCH, REASON_SEARCH),
                (_MEMORY_MARKERS, INTENT_CHAT_MEMORY, REASON_MEMORY)):
            if _has_stem(body, markers):
                return ActionIntent(
                    intent=intent, capability=INTENT_CAPABILITY[intent],
                    confidence=CONFIDENCE_HIGH, reason=reason,
                    evidence=(intent,))
        return ActionIntent()
    except Exception:      # pragma: no cover - защитная ветка
        return ActionIntent()


def intent_blockers(intent: ActionIntent, *, capability_status: str = "",
                    has_reply: bool = False) -> tuple[str, ...]:
    """§5.10/§5.18: наблюдаемые блокеры, из-за которых доступное действие
    не выбрано (пусто → блокеров нет). Не даёт «формально tool есть, но L1
    его не видит» без явной причины. Никогда не бросает (``intent=None`` —
    поручения нет, блокеров нет). ASAP5 §20: edit-интент проверяет
    capability ``image_edit`` (та же семантика «не ready» → блокер)."""
    if intent is None:
        return ()
    cap_intent = getattr(intent, "intent", "")
    if cap_intent not in (INTENT_CREATE_IMAGE, INTENT_EDIT_IMAGE):
        return ()
    if capability_status and capability_status != "ready":
        return (f"capability_{capability_status}",)
    if cap_intent == INTENT_CREATE_IMAGE \
            and intent.confidence == CONFIDENCE_AMBIGUOUS:
        return (REASON_CREATE_DEICTIC,)
    return ()


def emit_capability_rejected(capability, reason, *, chat_id=None,
                             run_id=None) -> None:
    """``L1_CAPABILITY_REJECTED (capability, reason)`` (§1.4; fail-open)."""
    try:
        from services.agentic_events import (L1_CAPABILITY_REJECTED,
                                             emit_agentic_event)
        name = str(capability or "").strip().replace(" ", "_")[:64]
        emit_agentic_event(L1_CAPABILITY_REJECTED,
                           capability=name or "unknown",
                           reason=str(reason or REASON_UNKNOWN),
                           chat_id=chat_id, run_id=run_id)
    except Exception:          # pragma: no cover - fail-open
        pass


__all__ = [
    "CAPABILITY_TOOLS", "REASON_UNKNOWN", "REASON_NO_TOOL",
    "REASON_NOT_ACTIVE", "REASON_LOW_CONFIDENCE", "resolve_capabilities",
    "REASON_NOT_READY",
    "available_capabilities", "schemas_for_names", "rejected_note",
    "emit_capability_rejected",
    # §5.1 (SOUL-AMD.5.2/5.9/5.10): semantic intent → capability
    "ActionIntent", "detect_action_intent", "intent_blockers",
    "is_explicit_factcheck_request",
    "INTENT_CREATE_IMAGE", "INTENT_EDIT_IMAGE", "INTENT_WEB_SEARCH",
    "INTENT_FACT_CHECK", "INTENT_CHAT_MEMORY", "INTENT_NONE",
    "INTENT_CAPABILITY",
    "CONFIDENCE_HIGH", "CONFIDENCE_AMBIGUOUS", "CONFIDENCE_NONE",
    "REASON_CREATE_COMMAND", "REASON_CREATE_NEED", "REASON_CREATE_CONCEIVE",
    "REASON_CREATE_NEGATED", "REASON_CREATE_DEICTIC",
    "REASON_CREATE_REPORTED", "REASON_CREATE_FORWARDED",
    "REASON_CREATE_SELF", "REASON_EDIT_REQUEST",
]
