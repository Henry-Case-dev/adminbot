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

# Лексика (стемы, регистр не важен): НЕ одна регулярка «нарисуй» — смысл
# собирается из пары «действие + объект»/«потребность + объект», отдельно
# различаются «создать» и «придумать». Стем матчится по НАЧАЛУ слова
# (граница слова), а не подстрокой: «арт» внутри квартир*/карт*/март*/
# стартап*, «мем» внутри мемориальн*/мембран* — НЕ объект изображения.
# Ложное срабатывание (платная генерация) дороже пропуска.
_DRAW_VERB_STRONG = ("нарису", "рисуй", "рису", "сгенер", "изобраз",
                     "намалю", "забабах", "сварган", "накида", "нафигач",
                     "намути", "замути")
#: Приставочные глаголы рисования («перерисуй мем») — поручение ТОЛЬКО с
#: объектом изображения: «перерисуй схему в отчёте» картинку не заказывает.
_DRAW_VERB_PREFIXED = ("перерису", "дорису", "подрису", "зарису")
#: «Создать/сделать» — общие глаголы: поручение только с объектом изображения
#: («сделай уборку»/«создай план»/«сделай план на март» картинку не заказывают).
_CREATE_VERB_GENERIC = ("созда", "сдела", "сделай")
_IMAGE_OBJECT = ("мем", "картин", "изображен", "инфографик", "комикс", "арт",
                 "иллюстрац", "постер", "скетч", "пикч", "визуализ", "баннер",
                 "рисун", "фотореализ", "коллаж", "аватарк", "фотож")
#: Слова, которые НАЧИНАЮТСЯ как стем, но объектом/действием не являются
#: (явные исключения вместо сырой подстроки — «квартира»/«март»/«мемориальный»).
_STEM_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "арт": ("артефакт", "артери", "артрит", "артист", "артикул", "артел",
            "артподготовк"),
    "мем": ("мемориал", "меморандум", "мембран", "мембер"),
    "рису": ("рисун",),          # «рисунок» — объект изображения, не действие
    "спор": ("спорт", "спортивн"),   # «мем про спорт» ≠ «давай поспорим»
    "текст": ("текстил",),           # «мем про текстиль» ≠ просьба придумать
    "подпис": ("подписк", "подписчик"),
}
_NEED_MARKER = ("нужн", "нужен", "надо", "хочу", "давай", "можешь", "можно")
# ASAP5 §20: edit-маркеры — изменение СУЩЕСТВУЮЩЕГО изображения (исходник
# резолвится router'ом: reply / собственное медиа / ранее присланное).
# «Перерисуй/дорисуй» остаются CREATE (прецедент тестов W10: «перерисуй мем»
# — поручение создать), поэтому edit-глаголы НЕ пересекаются с
# _DRAW_VERB_*; create-глагол сильнее edit (смешанная просьба — создание).
_EDIT_VERB = ("измен", "редактир", "отредактир", "поменя", "поправ",
              "исправ", "перезалей", "перекрас")
#: Удаление/добавление объекта НА готовом изображении — edit только с
#: локативом («на картинке/фото/меме»), иначе «добавь мем в чат» — не edit.
_EDIT_REMOVE = ("убер", "сотри", "стори", "удал", "замени", "добав", "встав",
                "впиши", "надпис")
_EDIT_LOCATIVE_RE = re.compile(
    r"(?:\b(?:на|с|со)\s+(?:картин|фото|изображен|мем|рисунк|арте|скрин|пикч))",
    re.IGNORECASE)
_CONCEIVE = ("придума", "концепт", "идея", "идею", "идеи", "идей", "сценар",
             "сюжет", "текст", "подпис", "шутк", "вариант", "предложи",
             "назван", "заголовк", "описан")
#: Инструментальная форма («мем С текстом», «с подписью») — это ТЗ на картинку,
#: а не просьба придумать текст (иначе «сделай мем с текстом» терял бы
#: поручение создать изображение).
_CONCEIVE_INSTRUMENTAL_RE = re.compile(
    r"(?:с\s+текстом)|(?:с\s+подпис)|(?:и\s+текст)|(?:подпис\s+снизу)"
    r"|(?:с\s+назван)",
    re.IGNORECASE)
_DEICTIC = ("это", "этот", "эту", "эти", "то", "что-нибудь", "что-то",
            "чтото", "как-нибудь", "какнибудь", "красиво", "покруче",
            "получше")
#: Обсуждение/разговор про мемы ≠ поручение нарисовать («давай обсудим мемы»).
_DISCUSS = ("обсуд", "поговор", "пошути", "расскаж", "вспомн", "объясн",
            "поясн", "перескаж", "разбер", "обсужд", "спор")
_WORD_RE = re.compile(r"[а-яёa-z0-9\-]+")

_SEARCH_MARKERS = ("поищи", "поиск", "найди", "найти", "загугли", "погугли",
                   "в интернете", "в сети", "search")
_FACTCHECK_MARKERS = ("фактчек", "факт-чек", "проверь факт", "проверить факт",
                      "правда ли", "это правда", "проверь это", "fact check")
_MEMORY_MARKERS = ("что я говорил", "что я писал", "напомни", "вспомни",
                   "что было в чате", "помнишь")

# «Создавать» ≠ «придумывать»: отрицание/запрет рисовать снимает поручение
# (SOUL-AMD.5.9 — «придумай концепт мема, рисовать не надо»). Отмена/«не надо»
# без явного «рису» — тоже отказ (ложный платный вызов дороже пропуска).
_NEGATED_CREATE_RE = re.compile(
    r"(?:\bне\s+(?:рису|нарису|созда|сгенер|изобраз|малю|дела))"
    r"|(?:\bне\s+(?:меня|меняй|измен|редактир|поменя|трогай|убирай|удал|исправ))"
    r"|(?:рисовать\s+не\s+надо)|(?:не\s+надо\s+рисов)"
    r"|(?:без\s+(?:картин|изображен|рисунк|мем|арт))"
    r"|(?:только\s+текст)|(?:только\s+текстом)|(?:текстом\s+обойд)"
    r"|(?:словами\s+без)"
    r"|(?:\bне\s+(?:надо|нужно|нужен|нужна|стоит)\b)"
    r"|(?:(?<!не )\b(?:забудь|отмен\w*|отбой))",
    re.IGNORECASE)

#: Пересылка/цитата: чужая просьба — не поручение пользователя. Атрибуция
#: («сказал», «просил», «написал», «цитата») имеет вес только ДО слов поручения:
#: «нарисуй мем про то, что Петя сказал» — наша просьба, не цитата.
_ATTRIBUTION_RE = re.compile(
    r"(?:сказал(?:а|и)?|говорил(?:а|и)?|говорит|просил(?:а|и)?|просит|"
    r"написал(?:а|и)?|пишет|передал(?:а|и)?|переда[её]т|цитат\w*|"
    r"цитиру\w*|спрашивал(?:а|и)?|спросил(?:а|и)?)",
    re.IGNORECASE)

#: «Я сам(а) нарисую» / «мне нужно нарисовать» — пользователь сделает это сам:
#: генерация не наша (глагол в 1-м лице или «сам»/«мне нужно» рядом с
#: действием, не любое «сам»).
_SELF_ACTION_RE = re.compile(
    r"(?:\bя\s+сам[аи]?\s+(?:нарис|рис|сдела|созда|сгенер|изобраз|намалю|"
    r"замут|намут)\w*)"
    r"|(?:\b(?:нарисую|сделаю|создам|сгенерю|намалюю)\s+сам[аи]?\b)"
    r"|(?:\bмне\s+(?:нужно|надо|хочется)\s+(?:нарис|рис|сдела|созда|сгенер|"
    r"изобраз|намалю)\w*)",
    re.IGNORECASE)

#: Код-блоки/инлайн-код — пример кода, а не поручение боту.
_FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _without_code(text: str) -> str:
    """Текст без код-блоков и инлайн-кода (пример кода ≠ поручение)."""
    return _INLINE_CODE_RE.sub(" ", _FENCED_CODE_RE.sub(" ", str(text or "")))


def _stem_hits_word(word: str, stem: str) -> bool:
    """Стем совпадает с НАЧАЛОМ слова и не входит в явные исключения."""
    if not word.startswith(stem):
        return False
    for blocked in _STEM_EXCLUSIONS.get(stem, ()):
        if word.startswith(blocked):
            return False
    return True


def _has_stem(text: str, stems) -> bool:
    """Смысловой матч по СЛОВАМ (граница слова), а не по подстроке:
    «арт» не матчит «квартира»/«март», «мем» — «мемориальный»."""
    tokens = _WORD_RE.findall(text)
    for stem in stems:
        if " " in stem or "-" in stem:      # фразовый маркер («в интернете»)
            if stem in text:
                return True
        elif any(_stem_hits_word(word, stem) for word in tokens):
            return True
    return False


def _is_intent_word(word: str) -> bool:
    """Слово — признак поручения (действие рисования/создания или объект)."""
    return (_has_stem(word, _DRAW_VERB_STRONG)
            or _has_stem(word, _DRAW_VERB_PREFIXED)
            or _has_stem(word, _CREATE_VERB_GENERIC)
            or _has_stem(word, _IMAGE_OBJECT))


def _reported_speech(body: str) -> bool:
    """Чужая просьба: атрибуция стоит ДО слов поручения."""
    match = _ATTRIBUTION_RE.search(body)
    if match is None:
        return False
    for word in _WORD_RE.finditer(body):
        if word.start() > match.start():
            break
        if _is_intent_word(word.group(0)):
            return False
    return True


def _normalize(text: str) -> str:
    return str(text or "").strip().lower().replace("ё", "е")


@dataclasses.dataclass(frozen=True)
class ActionIntent:
    """§5.1: смысловое намерение действия (дет., без LLM).

    ``intent`` — смысл («create_image»/…); ``capability`` — capability из
    ``CAPABILITY_TOOLS``; ``confidence`` — ``high`` (действовать можно),
    ``ambiguous`` (нужен ОДИН уточняющий вопрос), ``none`` (действия нет).
    ``reason``/``evidence`` — наблюдаемая причина и слова-основание (R17:
    только слова запроса, без инфраструктуры)."""

    intent: str = INTENT_NONE
    capability: str = ""
    confidence: str = CONFIDENCE_NONE
    reason: str = REASON_NONE
    evidence: tuple[str, ...] = ()
    conceive_only: bool = False

    @property
    def actionable(self) -> bool:
        """Однозначное поручение создать изображение (можно действовать)."""
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


def detect_action_intent(text, *, reply_text: str = "",
                         addressed: bool = False,
                         forwarded: bool = False) -> ActionIntent:
    """Смысловой детектор поручения действия (SOUL-AMD.5.1/5.2/5.9/5.10).

    Регекс остаётся быстрым путём очевидных команд; этот детектор — вторая,
    смысловая дверь: «сделай мем», «нужна инфографика», «давай изобразим это
    в виде комикса», «сделай картинку из этой ситуации» распознаются по паре
    «действие/потребность + объект изображения». Просьба ПРИДУМАТЬ идею/
    текст/сценарий и явное отрицание рисования генерацию НЕ запускают;
    неоднозначное поручение («сделай это») помечается ``ambiguous``.

    Не поручение (0 генераций) и наблюдаемая причина:

    * ``forwarded=True`` (пересланное сообщение) — чужие слова;
    * чужая просьба («Петя сказал: нарисуй мем») — атрибуция ДО поручения;
    * пользователь нарисует сам («я сам нарисую мем»);
    * пример кода (код-блок/инлайн-код) — текст внутри кода не команда;
    * стем только как начало слова: «квартира»/«март»/«мемориальный» —
      не объект изображения.

    Никогда не бросает; без LLM-вызовов и I/O."""
    try:
        raw = str(text or "")
        body = _without_code(_normalize(raw))
        evidence: list[str] = []
        if not body:
            return ActionIntent()
        reply_body = _without_code(_normalize(reply_text))
        negated = bool(_NEGATED_CREATE_RE.search(body))
        explicit_draw = _has_stem(body, _DRAW_VERB_STRONG)
        prefixed_draw = _has_stem(body, _DRAW_VERB_PREFIXED)
        generic_create = _has_stem(body, _CREATE_VERB_GENERIC)
        verb = explicit_draw or prefixed_draw or generic_create
        obj = _has_stem(body, _IMAGE_OBJECT)
        # ASAP5 §20: edit-детекция (изменение исходника ≠ создание нового).
        edit_verb = _has_stem(body, _EDIT_VERB)
        edit_remove = _has_stem(body, _EDIT_REMOVE)
        edit_locative = bool(_EDIT_LOCATIVE_RE.search(body))
        is_edit = ((edit_verb and obj) or (edit_remove and edit_locative)) \
            and not (explicit_draw or prefixed_draw or generic_create)
        conceive = _has_stem(body, _CONCEIVE) and not bool(
            _CONCEIVE_INSTRUMENTAL_RE.search(body))
        need = _has_stem(body, _NEED_MARKER)
        for flag, name in ((verb, "verb"), (obj, "image_object"),
                           (conceive, "conceive"), (need, "need"),
                           (negated, "negated"), (is_edit, "edit")):
            if flag:
                evidence.append(name)
        # 0. Пересылка: текст чужого сообщения — не поручение пользователя.
        if forwarded and (verb or obj):
            evidence.append("forwarded")
            return ActionIntent(confidence=CONFIDENCE_NONE,
                                reason=REASON_CREATE_FORWARDED,
                                evidence=tuple(evidence))
        # 1. Чужая просьба («Петя сказал: нарисуй мем») — адресат не бот/не
        #    пользователь: генерации нет (обычный ход).
        if (verb or obj) and _reported_speech(body):
            evidence.append("reported")
            return ActionIntent(confidence=CONFIDENCE_NONE,
                                reason=REASON_CREATE_REPORTED,
                                evidence=tuple(evidence))
        # 2. «Я сам нарисую» — пользователь делает это сам, не поручает боту.
        if (verb or obj) and _SELF_ACTION_RE.search(body):
            evidence.append("self")
            return ActionIntent(confidence=CONFIDENCE_NONE,
                                reason=REASON_CREATE_SELF,
                                evidence=tuple(evidence))
        # 3. Запрет/отказ рисовать сильнее поручения (придумать ≠ нарисовать).
        if negated and (verb or obj or is_edit):
            return ActionIntent(
                confidence=CONFIDENCE_NONE,
                reason=(REASON_CREATE_CONCEIVE if conceive
                        else REASON_CREATE_NEGATED),
                evidence=tuple(evidence), conceive_only=bool(conceive))
        # 3.5 (ASAP5 §20): edit-поручение ПЕРЕЖИВАет need-маркеры («можешь
        # изменить мем») — иначе общий need-путь шага 4 misroute'ил бы edit
        # в платную генерацию нового изображения.
        if is_edit:
            if _has_stem(body, _DISCUSS):
                return ActionIntent(evidence=tuple(evidence))
            return ActionIntent(
                intent=INTENT_EDIT_IMAGE,
                capability=INTENT_CAPABILITY[INTENT_EDIT_IMAGE],
                confidence=CONFIDENCE_HIGH, reason=REASON_EDIT_REQUEST,
                evidence=tuple(evidence))
        # 4. Объект изображения + действие/потребность → поручение создать.
        if obj and (verb or need):
            if _has_stem(body, _DISCUSS) and not explicit_draw:
                # «давай обсудим мемы» / «расскажи про мемы» — разговор, не ТЗ.
                return ActionIntent(evidence=tuple(evidence))
            if conceive and not explicit_draw:
                # «сделай текст мема»/«нужен концепт мема» — просьба придумать.
                return ActionIntent(
                    confidence=CONFIDENCE_NONE, reason=REASON_CREATE_CONCEIVE,
                    evidence=tuple(evidence), conceive_only=True)
            return ActionIntent(
                intent=INTENT_CREATE_IMAGE,
                capability=INTENT_CAPABILITY[INTENT_CREATE_IMAGE],
                confidence=CONFIDENCE_HIGH,
                reason=(REASON_CREATE_COMMAND if verb
                        else REASON_CREATE_NEED),
                evidence=tuple(evidence))
        # 5. Явная команда рисовать без объекта («Бот, нарисуй») — действие.
        #    «Сделай/создай» без объекта сюда НЕ попадают: «сделай уборку»,
        #    «создай план на март» — не поручение картинки.
        if explicit_draw and not conceive:
            return ActionIntent(
                intent=INTENT_CREATE_IMAGE,
                capability=INTENT_CAPABILITY[INTENT_CREATE_IMAGE],
                confidence=CONFIDENCE_HIGH, reason=REASON_CREATE_COMMAND,
                evidence=tuple(evidence))
        # 6. Слабое «сделай/создай/перерисуй» + указатель без объекта —
        #    существенная неоднозначность: один короткий уточняющий вопрос.
        if (generic_create or prefixed_draw) and not conceive and not negated:
            tokens = set(_WORD_RE.findall(body))
            deictic = bool(tokens & set(_DEICTIC))
            if deictic and (addressed or bool(reply_body)):
                return ActionIntent(
                    intent=INTENT_CREATE_IMAGE,
                    capability=INTENT_CAPABILITY[INTENT_CREATE_IMAGE],
                    confidence=CONFIDENCE_AMBIGUOUS,
                    reason=REASON_CREATE_DEICTIC, evidence=tuple(evidence))
            return ActionIntent()
        # 7. Прочие действия (паритет §5.18): поиск/фактчек/память.
        for markers, intent, reason in (
                (_FACTCHECK_MARKERS, INTENT_FACT_CHECK, REASON_FACTCHECK),
                (_SEARCH_MARKERS, INTENT_WEB_SEARCH, REASON_SEARCH),
                (_MEMORY_MARKERS, INTENT_CHAT_MEMORY, REASON_MEMORY)):
            if _has_stem(body, markers):
                return ActionIntent(
                    intent=intent, capability=INTENT_CAPABILITY[intent],
                    confidence=CONFIDENCE_HIGH, reason=reason,
                    evidence=(intent,))
        return ActionIntent(evidence=tuple(evidence))
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
    "INTENT_CREATE_IMAGE", "INTENT_EDIT_IMAGE", "INTENT_WEB_SEARCH",
    "INTENT_FACT_CHECK", "INTENT_CHAT_MEMORY", "INTENT_NONE",
    "INTENT_CAPABILITY",
    "CONFIDENCE_HIGH", "CONFIDENCE_AMBIGUOUS", "CONFIDENCE_NONE",
    "REASON_CREATE_COMMAND", "REASON_CREATE_NEED", "REASON_CREATE_CONCEIVE",
    "REASON_CREATE_NEGATED", "REASON_CREATE_DEICTIC",
    "REASON_CREATE_REPORTED", "REASON_CREATE_FORWARDED",
    "REASON_CREATE_SELF", "REASON_EDIT_REQUEST",
]
