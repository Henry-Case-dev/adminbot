"""F3 (T-1963/T-1964, ADR-1021-3) — единый канон стилевых блоков промптов.

Блок A «АНТИ-БОТ» и блок B «АСИММЕТРИЯ» вставляются во все отвечающие
каноны (chat/factcheck/search/summary/webpage/youtube/youtube_video/checkup).
Держим их в одном месте, чтобы 8 констант не разъезжались.

Дополнительно здесь живёт канон-инструкция по <bot_knowledge> (R1021):
из прежней формулировки R46-4 снята конфликтующая с ТЗ часть «Дай понять,
что ты уже проверял эту инфу ранее … не нужно повторять дважды» (F3 §2.3).
Прежний текст сохранён как ``LEGACY_BOT_KNOWLEDGE_INSTRUCTION`` — он уходит
в ``PREV_*_R1021`` слепки для идемпотентной канон-миграции PG (ADR-1013-3).

Языковая дисциплина: новые строки без кавычек-елочек и длинных тире
(прецедент R5/R9/R2020), без ``{}``-плейсхолдеров, запретные формулировки
описаны так, чтобы не цитироваться дословно (иначе grep-тест отсутствия
тропов ловил бы сам запрет).
"""
from __future__ import annotations

# Блок A — прямой запрет RLHF-тропов (финальный список владельца, UPD стр. 131).
# Раунд 10.22 (F6, ADR-1022-6 §5): п.7 — запрет шаблонных финалов/канцелярских
# вводных БЕЗ дословного цитирования клише (иначе grep-тест отсутствия тропов
# поймает сам запрет). Прежний 6-пунктовый текст сохранён как
# ``PREV_ANTI_BOT_BLOCK`` — уходит в ``PREV_*_R1022`` слепки (ADR-1013-3).
ANTI_BOT_BLOCK = """АНТИ-БОТ (СТРОГО ЗАПРЕЩЕНО):
1. Любые отсылки к тому, что ты ИИ, нейросеть, языковая модель или программа.
2. Сервисные формулы вроде "надеюсь, что помог" и "чем ещё помочь".
3. Зеркальные перепалки и передразнивание грубости оппонента в ответ.
4. Списки с буллитами и нумерованные перечни в самом ответе.
5. Морализаторство, нравоучения и назидательный финал.
6. Любые слова о том, что собеседник уже поднимал этот вопрос или повторяется.
7. Шаблонные концовки и канцелярские вводные: итоговые обобщения, заключительные формулы, жанровые штампы."""

# Слепок прод-канона раунда 10.21 (до п.7) — только для PREV_*_R1022-слепков
# и обратной канон-миграции PG (ADR-1013-3). НЕ используется в новых канонах.
PREV_ANTI_BOT_BLOCK = """АНТИ-БОТ (СТРОГО ЗАПРЕЩЕНО):
1. Любые отсылки к тому, что ты ИИ, нейросеть, языковая модель или программа.
2. Сервисные формулы вроде "надеюсь, что помог" и "чем ещё помочь".
3. Зеркальные перепалки и передразнивание грубости оппонента в ответ.
4. Списки с буллитами и нумерованные перечни в самом ответе.
5. Морализаторство, нравоучения и назидательный финал.
6. Любые слова о том, что собеседник уже поднимал этот вопрос или повторяется."""

# Блок B — структурная асимметрия вместо RLHF-шаблона.
ASYMMETRY_BLOCK = """АСИММЕТРИЯ:
1. Чередуй короткие рубленые фразы и длинные развёрнутые предложения, не выравнивай их длину.
2. В болтовне отвечай на главное, сознательно игнорируя часть набросов; если план требует полного разбора - разбирай его.
3. Вместо шаблонных приёмов используй одну контекстную метафору или сарказм.
4. Не заканчивай ответ вопросом, призывом или нравоучением."""

# Единый суффикс для всех отвечающих канонов.
STYLE_BLOCKS_SUFFIX = "\n\n" + ANTI_BOT_BLOCK + "\n\n" + ASYMMETRY_BLOCK

# Слепок суффикса раунда 10.21 (прежний ANTI_BOT без п.7) — для
# `PREV_*_R1022`-слепков идемпотентной канон-миграции PG (ADR-1013-3).
PREV_STYLE_BLOCKS_SUFFIX = (
    "\n\n" + PREV_ANTI_BOT_BLOCK + "\n\n" + ASYMMETRY_BLOCK
)

# Раунд 10.22 (F6, ADR-1022-6 §2.3): системное сообщение ретрая Validator
# Loop. Текст ретрая НЕ цитирует сами клише (grep-тест отсутствия тропов).
CLICHE_RETRY_SYSTEM_PROMPT = (
    "Ты нарушил Negative Constraints и использовал запрещенное клише. "
    "Перепиши ответ полностью, сделав его естественным."
)

# MCA-08 (D8, T-4907/T-4908): канон повтора при нарушении «только форма»
# (числа/отрицания/адресаты/смысл сохранены; измени только форму). Второго
# постпроцессора/paraphrase-модуля нет — этот промпт использует тот же
# Вербализатор внутри bounded-бюджета `verbalize_validated`.
FORM_GUARD_RETRY_SYSTEM_PROMPT = (
    "Перепиши ответ заново, сохранив все числа, отрицания, адресатов и смысл; "
    "измени только форму. Не добавляй новых имён и данных."
)

# MCA-15 (D5, T-4930/T-4931): канон повтора при незаземлённом числе о
# статистике чата. Один и тот же Вербализатор, bounded ≤1 (бюджет общий с
# клише/form-гардами); подставляется только проверенная формулировка.
NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT = (
    "СТОП: в ответе есть число о статистике чата, которого нет в проверенном "
    "измерении этого хода. Перепиши ответ, используя ТОЛЬКО проверенную "
    "формулировку ниже; число, единицу и область не меняй, других чисел о "
    "количестве сообщений/вхождений/авторов не добавляй.\n"
    "ПРОВЕРЕННАЯ ФОРМУЛИРОВКА: {verified_phrase}"
)

# CFG-07D.5 (21.10.2026): канон повтора при смысловой метаречи (backstage) —
# инверсные/вариативные формулировки, НЕ пойманные закрытыми сетами словаря
# (детерминированный срез для дословных формул остаётся на швах). Тот же
# Вербализатор, bounded ≤1 внутри общего бюджета `verbalize_validated`;
# подставляется КОД причины (R17: без приватных текстов). Честные ограничения
# («проверил — не нашёл подтверждений») запрещено вычищать вместе с метаречью.
METATEXT_RETRY_SYSTEM_PROMPT = (
    "СТОП: в ответе просочилась служебная метаречь о внутренней работе "
    "(код причины: {reason}). Перепиши ответ полностью: убери упоминания "
    "логов, справок, инструкций, инструментов и внутренних механик; не "
    "преувеличивай объём проверки (никаких «проверил всё в интернете»). "
    "Факты, ссылки, имена, числа и честные ограничения сохрани."
)

# Новый канон R1021: польза <bot_knowledge> без «уже проверял ранее».
# CFG-07A-2 (SF-11, 20.10.2026, ADR-1013-3): hostility-директива («унизить
# оппонента») снята из активных канонов НЕ-фактчек маршрутов — семантика
# suppress-правила 5 (persona.bot_knowledge_hostility, «используй её в
# ответе»). Сама BOT_KNOWLEDGE_INSTRUCTION НЕ меняется: она входит в канон
# фактчека (фриз CFG-06 W3) и в слепки PREV_*_R1022 / PREV_*_CFG07A, которые
# обязаны узнавать байты прежнего прод-канона (прецедент LEGACY_*).
BOT_KNOWLEDGE_INSTRUCTION = (
    "Если в блоке <bot_knowledge> есть информация по текущей теме, "
    "используй её, чтобы унизить оппонента своими знаниями."
)

# CFG-07A-2 (SF-11): нейтральная редакция для активных канонов
# search/youtube(×2)/web/summary-legacy. Польза <bot_knowledge> сохранена,
# hostility снята (байт-в-байт = результат suppress-правила 5).
BOT_KNOWLEDGE_INSTRUCTION_NEUTRAL = (
    "Если в блоке <bot_knowledge> есть информация по текущей теме, "
    "используй её в ответе."
)

# Исторический канон R46-4 (до раунда 10.21) — только для PREV-слепков.
LEGACY_BOT_KNOWLEDGE_INSTRUCTION = (
    "Если в блоке <bot_knowledge> есть информация по текущей теме, "
    "используй её, чтобы унизить оппонента своими знаниями. Дай понять, "
    "что ты уже проверял эту инфу ранее или смотрел ролик на эту тему, "
    "и тебе не нужно повторять дважды."
)

# ── Раунд 10.23 (F3, ADR-1023-3) — умный Вербализатор: типографика и режимы.
# FIX-CORRECTIVE-FOLLOWUP (21.10.2026, §2 владельца): «Разрешен мат и сленг.»
# УДАЛЕНО из блока — блок подключается ко ВСЕМ канонам, а режим мата задаёт
# только <Expression_Settings>. Остальной текст байт-в-байт прежний.
# PREV_TYPOGRAPHY_BLOCK — байт-в-байт слепок ДО правки: из него собираются
# PREV-композиции (PREV_CHAT_VERBALIZER_MCA23, PREV_SUMMARY_NARRATOR_R1028),
# обязанные узнавать прод-байты (ADR-1013-3).

TYPOGRAPHY_BLOCK = (
    "ТИПОГРАФИКА (ОБЯЗАТЕЛЬНО):\n"
    "Только короткие дефисы (-) и обычные двойные кавычки (\"\"). "
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»). "
    "Никаких понтов про \"я сделал за тебя работу\"."
)

PREV_TYPOGRAPHY_BLOCK = (
    "ТИПОГРАФИКА (ОБЯЗАТЕЛЬНО):\n"
    "Только короткие дефисы (-) и обычные двойные кавычки (\"\"). "
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»). "
    "Разрешен мат и сленг. Никаких понтов про \"я сделал за тебя работу\"."
)

MODE_CASUAL_BLOCK = (
    "РЕЖИМ CASUAL - ТОРОПЛИВОЕ ПИСЬМО:\n"
    "Имитируй торопливое письмо: короткие рубленые фразы, иногда начинай "
    "с маленькой буквы. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕН Markdown: никаких заголовков, "
    "списков, жирного, курсива и таблиц. Только живой текст."
)

MODE_SERIOUS_BLOCK = (
    "РЕЖИМ SERIOUS - ГРАМОТНО, ПО ДЕЛУ:\n"
    "Пиши грамотно и по существу, без воды и размазывания. Разрешено "
    "минимальное форматирование. Держи легкую циничную иронию, без пафоса "
    "и морализаторства."
)

MODE_DEEP_RESEARCH_BLOCK = (
    "РЕЖИМ DEEP_RESEARCH - ГЛУБОКИЙ РАЗБОР:\n"
    "Выведи переданный тебе структурированный отчет ПОЛНОСТЬЮ, ничего не "
    "выбрасывай и не сжимай. Интегрируй токсичный стиль органично, без "
    "пафосных вступлений."
)

# Канальные форматные блоки (UPD владельца): канал доставки, а не режим,
# определяет разрешённую разметку. Причина — защита от Telegram ParseError.
#
# ВАЖНО (review iter1, H2): «жирный» физически рендерится только там, где есть
# safe-HTML-доставка (`parse_mode="HTML"` + `escape_lore_html`). Поэтому у
# plain-канала две разновидности блока:
#   * `FORMAT_PLAIN_BLOCK` — HTML-capable (direct deep_research: есть safe-HTML);
#   * `FORMAT_PLAIN_TEXT_BLOCK` — text-only (саммари/фактчек без HTML-доставки):
#     никаких HTML-тегов, чтобы `<b>` не утёк сырым; акценты — словом/строем
#     фразы, перечисления — буллитами `- `.
FORMAT_PLAIN_BLOCK = (
    "ФОРМАТ PLAIN - ПРЯМОЙ ЧАТ (ОБЫЧНОЕ СООБЩЕНИЕ, HTML-РЕЖИМ):\n"
    "Обязательно используй жирный для акцентов: <b>акцент</b>. Перечисления "
    "давай простыми буллитами: \"- \".\n"
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ любые таблицы: Markdown (| ... |), HTML (<table>), "
    "ASCII-сетки. Telegram не переваривает таблицы в обычном сообщении, и ответ "
    "не уйдет. Без #-заголовков и тяжелой разметки."
)

FORMAT_PLAIN_TEXT_BLOCK = (
    "ФОРМАТ PLAIN - ПРЯМОЙ ЧАТ (ОБЫЧНОЕ СООБЩЕНИЕ, ТОЛЬКО ТЕКСТ):\n"
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ любые HTML-теги, включая <b> и <i>: этот канал "
    "не рендерит разметку, теги уйдут пользователю сырыми. Акцент делай строем "
    "фразы и порядком слов. Перечисления давай простыми буллитами: \"- \".\n"
    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ любые таблицы: Markdown (| ... |), HTML (<table>), "
    "ASCII-сетки. Без #-заголовков и тяжелой разметки."
)

FORMAT_RICH_BLOCK = (
    "ФОРМАТ RICH - СТАТЬЯ (sendRichMessage):\n"
    "Разрешено ВСЁ: полный Markdown/HTML, сложные таблицы, сетки и глубокая "
    "структура. Пользуйся силой статьи на полную."
)

_CHANNEL_PLAIN = "plain"
_CHANNEL_RICH = "rich"

MODE_BLOCKS: dict[str, str] = {
    "casual": MODE_CASUAL_BLOCK,
    "serious": MODE_SERIOUS_BLOCK,
    "deep_research": MODE_DEEP_RESEARCH_BLOCK,
}

# Раунд 10.24 (F6, ADR-1024-10 D2): «Резервный режим (Fallback)» — код-дефолт
# каталога (PG-ключ prompts.verbilizer_default_mode, widget select). Это НЕ
# штатный режим роутинга (его динамически выбирает Синтезатор из Stage-1), а
# предохранитель на сбойный путь: применяется ТОЛЬКО если Stage-1 не отдал
# валидный `response_mode`. Держим строку в одном месте: сид каталога и
# fail-safe compose используют один канон (ADR-1013-3).
VERBILIZER_DEFAULT_MODE = "casual"


def resolve_prompt(pg_key: str, code_default: str) -> str:
    """F8: промпт из PG (hot) с откатом на код-канон.

    Правка промпта в UI применяется без рестарта (hot-get); **пустое/
    whitespace** значение или отсутствие ключа → прежняя код-константа
    (инвариант spec §4.1/ADR D4: пустота не должна «обнулять» system-промпт).

    SOUL-1 (W1, §1.2/§7.2): ПЕРСИСТЕНТНОЕ значение проходит через единый
    реестр речевых инструкций — известные сегменты legacy-личности
    («токсичный … бот-абьюзер») вычищаются детерминированно на сборке
    (``prompt_registry.suppress_legacy_speech``), а незаписанное через API
    реестра значение канона старой личности удерживается (действует
    заводская редакция, fix-pass review-w1 BLOCKER-1). Кодовый fallback
    (PG down) не изменяется.
    """
    from services import hot_config as hot
    value = hot.get(pg_key, code_default)
    if isinstance(value, str) and value.strip():
        return _effective_speech(pg_key, value)
    return code_default


def _effective_speech(pg_key: str, value: str) -> str:
    """Единый проход persisted-значения через реестр (fail-open)."""
    try:
        from services import prompt_registry as pr
        text, _source = pr.resolve_hot_prompt(pg_key, value)
        return text
    except Exception:          # pragma: no cover — реестр не роняет резолв
        logger.warning("[prompt_style_blocks] реестр недоступен | key=%s",
                       pg_key, exc_info=True)
        return value


def resolve_prompt_with_source(pg_key: str, code_default: str) -> tuple:
    """ASAP-2.1 (T-3986): ``(effective, source)`` для observability.

    source ∈ ``{"global", "default"}``: непустое PG-значение → ``global``
    (hot-слой bot_settings; per-chat-слот для stage-ключей не читается —
    аудит T-3965/prompt-map-audit.md), иначе ``default`` (код-канон).
    SOUL-1 (W1): ``global`` отдаётся только при РЕАЛЬНОМ наличии ключа в
    персистентном слое (иначе это кодовый фолбек), само значение проходит
    общий реестр — см. ``resolve_prompt``; удержанное (без провенанса)
    значение канона старой личности отдаёт ``default``, потому что действует
    заводская редакция.
    """
    from services import hot_config as hot
    value = hot.get(pg_key, code_default)
    if isinstance(value, str) and value.strip():
        try:
            from services import prompt_registry as pr
            return pr.resolve_hot_prompt(pg_key, value)
        except Exception:      # pragma: no cover — реестр не роняет резолв
            logger.warning("[prompt_style_blocks] реестр недоступен | key=%s",
                           pg_key, exc_info=True)
            return value, "global"
    return code_default, "default"


def _resolve_mode_block(mode: str) -> str:
    """F8: режимный блок из PG (hot) с fallback на код-канон."""
    return resolve_prompt(f"prompts.verbilizer_mode_{mode}", MODE_BLOCKS[mode])


def _resolve_default_mode() -> str:
    """F8: режим по умолчанию из PG (hot) с fail-safe на код-канон."""
    from services import hot_config as hot
    value = str(hot.get("prompts.verbilizer_default_mode",
                        VERBILIZER_DEFAULT_MODE) or "").strip().lower()
    return value if value in MODE_BLOCKS else VERBILIZER_DEFAULT_MODE

# Review iter1 (H1): в `deep_research` буллиты ОБЯЗАТЕЛЬНЫ, поэтому при сборке
# промпта для этого режима снимаем безусловные запреты на списки/буллиты из
# общих блоков (ANTI_BOT п.4 и R11-правило 2 Рассказчика). Замены — точечные,
# чтобы базовые каноны и их слепки не трогались, а собранный промпт не содержал
# взаимоисключающих инструкций.
_DEEP_RESEARCH_OVERRIDES: tuple[tuple[str, str], ...] = (
    (
        "4. Списки с буллитами и нумерованные перечни в самом ответе.",
        "4. Перечисления оформляй простыми буллитами \"- \": в этом режиме "
        "они разрешены.",
    ),
    (
        "2. Не выводи Markdown, списки, пункты и эмодзи: только сплошной "
        "текст, разделённый абзацами.",
        "2. Не выводи сырой Markdown и эмодзи: перечисления давай буллитами "
        "\"- \", остальной текст - сплошным.",
    ),
)


def _apply_mode_overrides(base_prompt: str, response_mode: str) -> str:
    """Снять запреты на буллиты для ветки ``deep_research`` (H1)."""
    if response_mode != "deep_research":
        return base_prompt
    text = base_prompt
    for old, new in _DEEP_RESEARCH_OVERRIDES:
        text = text.replace(old, new)
    return text


def format_block(channel: str | None, *, html_safe: bool = False) -> str:
    """Канальный форматный блок.

    * ``rich`` → полный Markdown/HTML (F6);
    * ``plain`` + ``html_safe`` → HTML-capable plain (direct deep_research);
    * ``plain`` без ``html_safe`` → text-only plain (без любых HTML-тегов).
    Неизвестный канал трактуется как безопасный text-only plain."""
    if str(channel or "").strip().lower() == _CHANNEL_RICH:
        return FORMAT_RICH_BLOCK
    return FORMAT_PLAIN_BLOCK if html_safe else FORMAT_PLAIN_TEXT_BLOCK


def resolve_mode_parts(base_prompt: str, response_mode: str = "", *,
                       extent_block: str = "",
                       modes_enabled: bool = True) -> tuple[str, str, str]:
    """Части сборки нарратора: ``(candidate, base, mode_or_extent_block)``.

    SOUL-1 (W2): композер обязан использовать ТУ ЖЕ семантику режима, что
    ``compose_verbalizer_system`` (один владелец — этот модуль), поэтому
    выбор режима/дефолт/overrides/extent вынесены в общий хелпер, а
    ``compose_verbalizer_system`` собран поверх него байт-в-байт.

    ``modes_enabled=False`` (kill-switch `SMART_VERBALIZER_MODES_ENABLED`
    OFF) → режимный/extent-блок не выбирается вовсе (паритет legacy-пути),
    база по-прежнему проходит `.rstrip()` и ``_apply_mode_overrides``.
    """
    candidate = str(response_mode or "").strip().lower()
    if candidate not in MODE_BLOCKS:
        candidate = _resolve_default_mode()
    base = _apply_mode_overrides(str(base_prompt or "").rstrip(), candidate)
    if not modes_enabled:
        return candidate, base, ""
    block = str(extent_block) if str(extent_block or "").strip() \
        else _resolve_mode_block(candidate)
    return candidate, base, block


def compose_verbalizer_system(base_prompt: str, response_mode: str = "",
                              channel: str = _CHANNEL_PLAIN, *,
                              html_safe: bool = False,
                              character_block: str = "",
                              style_directives: str = "",
                              extent_block: str = "") -> str:
    """Narrator-промпт по режиму и каналу.

    Формула (ADR-1023-3 §Decision 4/10): модульный базовый narrator
    (уже включает ``STYLE_BLOCKS_SUFFIX`` + ``TYPOGRAPHY_BLOCK``) +
    ровно один ``MODE_*_BLOCK``; для ``deep_research`` добавляется ровно
    один канальный блок. Для ``deep_research`` безусловные запреты на
    буллиты снимаются (H1), чтобы требование буллитов не конфликтовало с базой.

    MCA-08 (D2, ADR-1028-11 AM-2): ``character_block`` — новый
    **опциональный** параметр (default "" → байт-паритет всех текущих
    потребителей). Непустой блок владельца/правил добавляется последним
    part'ом; каноны/оффсеты/режимы не меняются, второго сборщика нет.

    MCA-08 (D5, T-4904): ``style_directives`` — опциональный
    ``<Style_Requests>``-блок (default "" → байт-паритет); идёт после
    ``character_block`` (порядок хвоста: rules → style).

    MCA-23 (§11, Wave 3): ``extent_block`` — опциональный блок полноты из
    ResponsePlan (services/response_extent.render_extent_block). Непустой
    блок заменяет собой ``MODE_*_BLOCK`` (план — источник полноты; старые
    режимы остаются compat-алиасом и больше не задают длину Direct).
    Default "" → байт-паритет всех прежних потребителей (factcheck/summary
    продолжают получать mode-блок из PG/канона без изменений).

    Fallback-контракт (F6, ADR-1024-10 D3): валидный ``response_mode`` из
    Stage-1 приоритетен — ключ ``prompts.verbilizer_default_mode`` при этом
    **не читается**. ``_resolve_default_mode()`` (значение ключа, код-дефолт
    ``casual``) применяется ТОЛЬКО если ``response_mode`` пуст/невалиден —
    то есть исключительно на сбойном пути. Предохранитель никогда не
    перехватывает штатный динамический выбор Синтезатора.

    Дефолт аргумента — ``""`` (сигнал «режим не выбран»), а не валидный
    режим: так вызов без явного режима тоже уходит на fallback-ключ, и
    второй источник правды о дефолте не заводится (канон — ``casual``).
    """
    candidate, base, mode_block = resolve_mode_parts(
        base_prompt, response_mode, extent_block=extent_block)
    parts = [base]
    if mode_block:
        parts.append(mode_block)
    if candidate == "deep_research":
        parts.append(format_block(channel, html_safe=html_safe))
    if character_block:
        parts.append(str(character_block))
    if style_directives:
        parts.append(str(style_directives))
    return "\n\n".join(part for part in parts if part)


# ═══════════════════════════════════════════════════════════════════════════
# SOUL-1 (W3, SOUL-16.1.2/16.4.1) - короткий semantic hint Speech Style Policy
# ═══════════════════════════════════════════════════════════════════════════
# Слой 10 композера (`style_policy_hint`): КОРОТКИЙ семантический hint по
# активным правилам, а не вся база инструкций (SOUL-16.4.1). Жёсткие правила
# исполняются детерминированно (`services/style_policy`), мягкие привычки -
# bounded-инструкции Writer без обещания 100% соблюдения (SOUL-16.1.2).
# Тексты - UPPER-константы одного модуля: правка формулировки меняет отпечаток
# фабричного набора реестра и требует осознанной регистрации (блок реестра
# `style.policy.hint`, SOUL-AMD.3.2). Языковая дисциплина: без кавычек-елочек,
# длинных тире и фигурных плейсхолдеров.

STYLE_POLICY_HINT_OPEN = "<Style_Policy_Hint>"
STYLE_POLICY_HINT_CLOSE = "</Style_Policy_Hint>"
STYLE_POLICY_HINT_MAX_CHARS = 400
STYLE_POLICY_HINT_MAX_ITEMS = 5
HINT_SOFT_PREFIX = "Привычки письма (мягко, не всегда строго):"

HINT_ONE_WORD = ("Полнота: ровно одно лексическое слово. Без второго слова, "
                 "пояснений, emoji-хвоста и служебных меток.")
HINT_MICRO = ("Полнота: очень кратко, короткая реплика из нескольких слов; "
              "жёсткого ограничения в одно слово нет.")
HINT_TRAILING_PERIOD_HARD = ("Завершающая точка: НЕ ставь точку в самом конце "
                             "сообщения. Точки внутри фраз остаются.")
HINT_TRAILING_PERIOD_SOFT = ("Завершающая точка: обычно не ставь точку в самом "
                             "конце сообщения.")
HINT_QUOTES_HARD = ("Кавычки: НЕ используй графические кавычки в обычной речи. "
                    "Иронию и цитирование передавай интонацией и лексикой "
                    "(он назвал это базой), дословный текст не переписывай.")
HINT_QUOTES_SOFT = ("Кавычки: обычно обходись без графических кавычек в обычной "
                    "речи.")
HINT_EMOJI_HARD = "Эмодзи: не используй."
HINT_EMOJI_SOFT = "Эмодзи: обычно не используй."
HINT_LINE_BREAKS_PREFIX = "Переносы строк: не больше"
HINT_FORBIDDEN_CHARS = ("Запрещённые символы: не используй символы из списка "
                        "владельца.")
HINT_VERBATIM_PROTECTED = ("Защищённый текст (ссылки, код, дословные цитаты, "
                           "версии, данные) не переписывай и не порти.")


def render_style_policy_hint(policy=None, *, max_chars: int = 0,
                             max_items: int = 0) -> str:
    """Короткий hint активных правил Style Policy для Writer (слой 10).

    Вход - `services.style_policy.EffectiveStylePolicy` (или любой объект с
    полями ``extent``/``hard_kinds``/``soft_kinds``/``soft_instructions``).
    Выход - блок в обёртке ``<Style_Policy_Hint>`` или пустая строка (нет
    активных правил либо политика недоступна). Никогда не бросает."""
    try:
        limit_chars = int(max_chars) if int(max_chars or 0) > 0 \
            else STYLE_POLICY_HINT_MAX_CHARS
        limit_items = int(max_items) if int(max_items or 0) > 0 \
            else STYLE_POLICY_HINT_MAX_ITEMS
        lines: list[str] = []
        extent = str(getattr(policy, "extent", "") or "")
        if extent == "one_word":
            lines.append(HINT_ONE_WORD)
        elif extent == "micro":
            lines.append(HINT_MICRO)
        hard = {str(k) for k in (getattr(policy, "hard_kinds", ()) or ())}
        soft = {str(k) for k in (getattr(policy, "soft_kinds", ()) or ())}
        for kind, hard_line, soft_line in (
                ("trailing_period", HINT_TRAILING_PERIOD_HARD,
                 HINT_TRAILING_PERIOD_SOFT),
                ("quotation_marks", HINT_QUOTES_HARD, HINT_QUOTES_SOFT),
                ("emoji", HINT_EMOJI_HARD, HINT_EMOJI_SOFT)):
            if kind in hard:
                lines.append(hard_line)
            elif kind in soft:
                lines.append(soft_line)
        if "forbidden_chars" in hard or "forbidden_chars" in soft:
            lines.append(HINT_FORBIDDEN_CHARS)
        max_breaks = getattr(policy, "line_breaks_max", None)
        if isinstance(max_breaks, int) and max_breaks >= 0:
            lines.append(HINT_LINE_BREAKS_PREFIX + " " + str(max_breaks) + ".")
        if hard or soft:
            lines.append(HINT_VERBATIM_PROTECTED)
        soft_texts: list[str] = []
        for item in list(getattr(policy, "soft_instructions", ()) or ()):
            text = str(getattr(item, "text", "") or "").strip()
            if text:
                soft_texts.append(text)
            if len(soft_texts) >= limit_items:
                break
        if soft_texts:
            lines.append(HINT_SOFT_PREFIX)
            lines.extend("- " + text for text in soft_texts)
        if not lines:
            return ""
        body = "\n".join("- " + line for line in lines)
        block = (STYLE_POLICY_HINT_OPEN + "\n" + body + "\n"
                 + STYLE_POLICY_HINT_CLOSE)
        while len(block) > limit_chars and len(lines) > 1:
            lines.pop()
            body = "\n".join("- " + line for line in lines)
            block = (STYLE_POLICY_HINT_OPEN + "\n" + body + "\n"
                     + STYLE_POLICY_HINT_CLOSE)
        if len(block) > limit_chars:
            return ""
        return block
    except Exception:      # pragma: no cover - hint не роняет сборку
        return ""
