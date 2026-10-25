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

from dataclasses import dataclass
from typing import Any, Mapping

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
# SPEECH-SIMPLIFY §2.2/§4: сняты обязательный ритм и фиксированная
# метафора/сарказм; длина и юмор задаются отдельными слоями.
PREV_ASYMMETRY_BLOCK = """АСИММЕТРИЯ:
1. Чередуй короткие рубленые фразы и длинные развёрнутые предложения, не выравнивай их длину.
2. В болтовне отвечай на главное, сознательно игнорируя часть набросов; если план требует полного разбора - разбирай его.
3. Вместо шаблонных приёмов используй одну контекстную метафору или сарказм.
4. Не заканчивай ответ вопросом, призывом или нравоучением."""

ASYMMETRY_BLOCK = """АСИММЕТРИЯ:
1. В болтовне отвечай на главное, не разбирай каждый набросок; если план требует полного разбора - разбирай его.
2. Не заканчивай ответ вопросом, призывом или нравоучением."""

# Единый суффикс для всех отвечающих канонов.
STYLE_BLOCKS_SUFFIX = "\n\n" + ANTI_BOT_BLOCK + "\n\n" + ASYMMETRY_BLOCK

# ── P0 SPEECH-SIMPLIFY (25.10.2026, source §2.1-2.3, §5) ────────────────────
# Базовая разговорная манера, юмор, длина и достоверность речи. Тексты —
# единственный источник `services.mca_expression` (байт-в-байт владельца);
# рендерятся ОДНИМ блоком в существующем expression-слое композера.
SPEECH_BASE_OPEN = "<Speech_Base>"
SPEECH_BASE_CLOSE = "</Speech_Base>"


def speech_base_block() -> str:
    """Блок базовых речевых инструкций владельца (без квот/постобработки)."""
    from services import mca_expression as _expr

    return "\n".join((
        SPEECH_BASE_OPEN,
        _expr.BASE_SPEECH_TEXT,
        "",
        _expr.HUMOR_TEXT,
        "",
        _expr.RESPONSE_LENGTH_TEXT,
        "",
        _expr.FACTUAL_SPEECH_TEXT,
        SPEECH_BASE_CLOSE,
    ))

# Слепок суффикса раунда 10.21 (прежний ANTI_BOT без п.7) — для
# `PREV_*_R1022`-слепков идемпотентной канон-миграции PG (ADR-1013-3).
PREV_STYLE_BLOCKS_SUFFIX = (
    "\n\n" + PREV_ANTI_BOT_BLOCK + "\n\n" + PREV_ASYMMETRY_BLOCK
)

#: Непосредственно предыдущий суффикс (прод 2.58.125: текущий ANTI_BOT +
#: прежняя ASYMMETRY). Нужен для точного отката Checkup после снятия
#: обязательной иронии/ритма.
PREV_SPEECH_STYLE_SUFFIX = (
    "\n\n" + ANTI_BOT_BLOCK + "\n\n" + PREV_ASYMMETRY_BLOCK
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
    "минимальное форматирование. Без пафоса и морализаторства."
)

# ── SPEECH-P0 (25.10.2026): писательская инструкция для разбора/анализа.
# Тексты — ДОСЛОВНО из `source-owner-p0-hotfix-addendum-2026-10-25.md` §1:
# (1) целевая инструкция анализа, (2) замена требования «сохрани структуру»
# для внутреннего analysis-пакета. Прежняя формулировка требовала вывести
# отчёт ПОЛНОСТЬЮ и ничего не сжимать — Writer не имел права перестроить
# ответ, поэтому простой вопрос «я злобный?» превращался в эссе. Прежние
# байты — слепок PREV_MODE_DEEP_RESEARCH_BLOCK (откат/история).
#
# Один источник текста на два потребителя (SPEECH-P0-CORE-SERIOUS):
#   * `MODE_DEEP_RESEARCH_BLOCK` — режим deep_research в system;
#   * `direct_l1.build_l2_plan_block(include_analysis=True)` — serious-разбор
#     (response_act=research без deep_research) в `<Response_Plan>`.
# Дублировать литералы нельзя: расхождение текстов снова разведёт
# «внутренний анализ» и Writer.
ANALYSIS_DIRECTIVE_TEXT = (
    "Проанализируй доступные сведения по существу вопроса. Отвечай прямо, "
    "естественно и соразмерно запросу. Используй наиболее релевантные "
    "подтверждённые наблюдения. Не превращай простой вопрос в "
    "психологическое эссе, хронологию событий или художественный рассказ. "
    "Подробный анализ проводи, когда его действительно просят. Не придумывай "
    "факты, даты, диалоги и причинные связи."
)

#: Замена прежнего требования «сохрани структуру» для внутреннего
#: analysis-пакета: пересказ служебной структуры в ответ не переносится.
ANALYSIS_WRITER_TEXT = (
    "Используй результаты анализа для ответа на вопрос, но не пересказывай "
    "внутреннюю структуру анализа. Передай главное естественным разговорным "
    "языком. Сохраняй существенные факты и выводы, не добавляя "
    "неподтверждённых подробностей."
)

#: P0-CORRECTIVE-3 (25.10.2026, `probes_final3.md` §6 проверка 4 / §7 F4):
#: в E несколько кавычек-обобщений, которых нет в переданных данных.
#: Тексты аддендума выше остаются байт-в-байт (их пин —
#: `test_speech_p0_hotfix_texts_analysis`), поэтому правило цитат живёт
#: отдельным носителем: режимный блок deep_research и plan-блок разбора,
#: ровно один раз на payload. Это инструкция Writer'у, не постпроцессор.
QUOTE_FIDELITY_TEXT = (
    "Цитируй дословно только то, что есть в переданных данных; если точной "
    "цитаты нет, не ставь кавычки - перескажи своими словами и не приписывай "
    "человеку слов, которых он не говорил. Вымышленные примеры, шутка и "
    "абсурд допустимы, но не как реальная цитата."
)

#: P0-CORRECTIVE (25.10.2026, §3 source-owner-p0-corrective «убрать лишние
#: мета-вступления; устранить обязательную структурированность там, где
#: пользователь её не просил»). Пробы `probes_final.md` §6 и `probes_final2.md`
#: §5 показали 5 из 8 ответов с преамбулой («Ладно, глянул…», «Да без
#: проблем, сейчас разложу», «Давай разберём»). Прежняя редакция была слишком
#: общей, поэтому здесь названы сами типы преамбул и жёстко задано место
#: ответа — первое содержательное предложение. P0-CORRECTIVE-3 (25.10.2026,
#: live `probes_final3.md` §5/§7: мета 4/20, списки без просьбы): добавлены
#: проверка «первая фраза про процесс — ответ неверен», один короткий
#: bad/good пример (не шаблон ответа), обращение и «да бля, ну ок»; список
#: прямо разрешён при явной просьбе пользователя. Директива по-прежнему НЕ
#: задаёт длину, формат или схему: только убирает служебный вход и
#: навязанную отчётность. Это инструкция Writer'у, не postprocess.
NO_META_STRUCTURE_TEXT = (
    "Не анонсируй разбор и не сообщай, что сейчас будешь делать. Не начинай "
    "с обращения, служебной подводки или отчёта о своих действиях: без \"ну\", "
    "\"ладно\", \"ок\", \"сейчас\", \"давай\", \"глянул\", \"разложу\", "
    "\"сейчас разложу\", \"разберём\", \"да бля, ну ок\" и похожих фраз, без "
    "обещаний разобрать. Первое содержательное предложение - сразу ответ или "
    "вывод по существу; первый абзац начинается с него, а не с твоих планов. "
    "Если первая фраза говорит о процессе, а не о деле, ответ неверен: "
    "перепиши начало. Не описывай, что ты посмотрел или собираешься разобрать, "
    "- говори, что из этого следует. Не нумеруй пункты и не делай отчётную "
    "структуру, разделы, подзаголовки или ярлыки, если пользователь не просил "
    "об этом прямо; при явной просьбе перечислить список уместен. Пример "
    "плохого начала: \"Ну ок, давай разложу по пунктам.\" Пример хорошего: "
    "\"Ты не злобный - просто резко реагируешь на одно и то же.\""
)

MODE_DEEP_RESEARCH_BLOCK = (
    "РЕЖИМ DEEP_RESEARCH - ГЛУБОКИЙ РАЗБОР:\n"
    + ANALYSIS_DIRECTIVE_TEXT + "\n"
    + ANALYSIS_WRITER_TEXT + "\n"
    + QUOTE_FIDELITY_TEXT + "\n"
    + NO_META_STRUCTURE_TEXT + "\n"
    "Глубина внутреннего разбора не обязана определять длину внешнего ответа."
)

#: Слепок прежнего режима DEEP_RESEARCH (прод до 25.10.2026) — только
#: история/откат, в сборке не участвует.
PREV_MODE_DEEP_RESEARCH_BLOCK = (
    "РЕЖИМ DEEP_RESEARCH - ГЛУБОКИЙ РАЗБОР:\n"
    "Выведи переданный тебе структурированный отчет ПОЛНОСТЬЮ, ничего не "
    "выбрасывай и не сжимай. Без пафосных вступлений."
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
# Слой 10 композера (`style_policy_hint`): семантический hint по активным
# правилам, а не вся база инструкций (SOUL-16.4.1). Жёсткие правила
# исполняются детерминированно (`services/style_policy`), мягкие привычки -
# bounded-инструкции Writer без обещания 100% соблюдения (SOUL-16.1.2).
# ASAP3 §1.2: по умолчанию лимитов нет - в блок входит КАЖДАЯ активная
# инструкция целиком (раньше скрытые 400/5 молча выкидывали поздние строки).
# Тексты - UPPER-константы одного модуля: правка формулировки меняет отпечаток
# фабричного набора реестра и требует осознанной регистрации (блок реестра
# `style.policy.hint`, SOUL-AMD.3.2). Языковая дисциплина: без кавычек-елочек,
# длинных тире и фигурных плейсхолдеров.

STYLE_POLICY_HINT_OPEN = "<Style_Policy_Hint>"
STYLE_POLICY_HINT_CLOSE = "</Style_Policy_Hint>"
#: ASAP3 §1.2: ``0`` (или отсутствие) = лимита НЕТ. Заводских 400/5 больше
#: нет: скрытая подстановка при ``<=0`` молча выкидывала поздние инструкции.
HINT_LIMIT_OFF = 0
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


@dataclass(frozen=True)
class HintExclusion:
    """Честно исключённая инструкция hint (ASAP3 §1.3).

    ``reason``: ``user_limit`` — не поместилась в лимит владельца;
    ``budget_excluded`` — не поместилась в явно переданный технический бюджет.
    """

    key: str
    kind: str
    reason: str = "user_limit"

    def as_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "reason": self.reason}


class HintRender(str):
    """Результат рендера hint: сам блок + диагностика состава.

    Наследует ``str``: существующие потребители (композер, реестр, тесты)
    читают значение как строку блока, а фактический состав доступен полями.
    ``truncated`` всегда ``False``: строки не режутся посередине.
    """

    __slots__ = ("total_items", "included_items", "included_keys", "excluded",
                 "max_chars", "max_items", "limited_by", "truncated")

    def __new__(cls, block: str = "", *, total_items: int = 0,
                included_items: int = 0, included_keys=(),
                excluded=(), max_chars: int = 0, max_items: int = 0,
                limited_by: str = "", truncated: bool = False) -> "HintRender":
        obj = str.__new__(cls, block)
        obj.total_items = int(total_items)
        obj.included_items = int(included_items)
        obj.included_keys = tuple(str(k) for k in (included_keys or ()))
        obj.excluded = tuple(excluded or ())
        obj.max_chars = int(max_chars)
        obj.max_items = int(max_items)
        obj.limited_by = str(limited_by or "")
        obj.truncated = bool(truncated)
        return obj

    @property
    def block(self) -> str:
        return str(self)

    @property
    def chars(self) -> int:
        return len(self)

    def as_dict(self) -> dict:
        """R17-safe диагностика (правила/виды/числа, без текста ответа)."""
        return {
            "chars": len(self),
            "total_items": self.total_items,
            "included_items": self.included_items,
            "max_chars": self.max_chars,
            "max_items": self.max_items,
            "limited_by": self.limited_by,
            "truncated": self.truncated,
            "included_keys": list(self.included_keys),
            "excluded": [row.as_dict() for row in self.excluded],
        }


@dataclass(frozen=True)
class _HintItem:
    """Одна атомарная инструкция hint (целая строка, не фрагмент)."""

    text: str
    kind: str
    rule_ids: tuple[str, ...] = ()
    soft: bool = False


def _limit_value(value: Any) -> int:
    """Пользовательский/технический лимит: ``<=0``/мусор = без ограничения."""
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return HINT_LIMIT_OFF
    return number if number > 0 else HINT_LIMIT_OFF


def _hint_candidates(policy) -> list[_HintItem]:
    """Все инструкции, которые МОГУТ попасть в блок (детерминированный порядок).

    Тире (``dash``) сюда не входит: правило исполняется детерминированно и не
    требует инструкции Writer. Правила фильтруются по ``enabled`` — в блоке
    только фактически действующие.
    """
    items: list[_HintItem] = []
    extent = str(getattr(policy, "extent", "") or "")
    if extent == "one_word":
        items.append(_HintItem(HINT_ONE_WORD, "extent"))
    elif extent == "micro":
        items.append(_HintItem(HINT_MICRO, "extent"))
    rules = [r for r in (getattr(policy, "rules", ()) or ())
             if bool(getattr(getattr(r, "rule", r), "enabled", True))]

    def ids(kind: str, strictness: str) -> tuple[str, ...]:
        return tuple(str(getattr(r, "id", "")) for r in rules
                     if str(getattr(r, "kind", "")) == kind
                     and str(getattr(r, "strictness", "")) == strictness)

    for kind, hard_line, soft_line in (
            ("trailing_period", HINT_TRAILING_PERIOD_HARD,
             HINT_TRAILING_PERIOD_SOFT),
            ("emoji", HINT_EMOJI_HARD, HINT_EMOJI_SOFT)):
        hard_ids = ids(kind, "hard")
        soft_ids = ids(kind, "soft")
        if hard_ids:
            items.append(_HintItem(hard_line, kind, hard_ids))
        elif soft_ids:
            items.append(_HintItem(soft_line, kind, soft_ids))
    # Кавычки (владелец 24.10.2026): режим A (normalize) исполняется
    # детерминированно — Writer не нужна инструкция. Инструкция остаётся
    # только для режима B (strip): «не используй кавычки».
    quotes_hard, quotes_soft = [], []
    for resolved in rules:
        if str(getattr(resolved, "kind", "")) != "quotation_marks":
            continue
        rule = getattr(resolved, "rule", resolved)
        params = getattr(rule, "params", {}) or {}
        if str(params.get("mode") or "").strip().lower() == "normalize":
            continue
        target = (quotes_hard if str(getattr(resolved, "strictness", ""))
                  == "hard" else quotes_soft)
        target.append(str(getattr(resolved, "id", "")))
    if quotes_hard:
        items.append(_HintItem(HINT_QUOTES_HARD, "quotation_marks",
                               tuple(quotes_hard)))
    elif quotes_soft:
        items.append(_HintItem(HINT_QUOTES_SOFT, "quotation_marks",
                               tuple(quotes_soft)))
    forbidden_ids = ids("forbidden_chars", "hard") + \
        ids("forbidden_chars", "soft")
    if forbidden_ids:
        items.append(_HintItem(HINT_FORBIDDEN_CHARS, "forbidden_chars",
                               forbidden_ids))
    max_breaks = getattr(policy, "line_breaks_max", None)
    if isinstance(max_breaks, int) and max_breaks >= 0:
        break_ids = ids("line_breaks", "hard") + ids("line_breaks", "soft")
        items.append(_HintItem(
            HINT_LINE_BREAKS_PREFIX + " " + str(max_breaks) + ".",
            "line_breaks", break_ids))
    soft_rows: list[_HintItem] = []
    for item in list(getattr(policy, "soft_instructions", ()) or ()):
        if not bool(getattr(item, "enabled", True)):
            continue
        text = str(getattr(item, "text", "") or "").strip()
        if text:
            soft_rows.append(_HintItem(
                text, "soft_instruction",
                (str(getattr(item, "id", "") or ""),), soft=True))
    writer_rules = []
    for r in rules:
        kind = str(getattr(r, "kind", ""))
        if kind == "dash":
            continue           # детерминированная замена, инструкция не нужна
        if kind == "quotation_marks":
            rule = getattr(r, "rule", r)
            params = getattr(rule, "params", {}) or {}
            if str(params.get("mode") or "").strip().lower() == "normalize":
                continue       # режим A тоже детерминированный
        writer_rules.append(r)
    if writer_rules or soft_rows:
        items.append(_HintItem(HINT_VERBATIM_PROTECTED, "verbatim_protected"))
    items.extend(soft_rows)
    return items


def _render_block(items: list[_HintItem]) -> str:
    if not items:
        return ""
    lines: list[str] = []
    prefix_done = False
    for item in items:
        if item.soft and not prefix_done:
            lines.append("- " + HINT_SOFT_PREFIX)
            prefix_done = True
        lines.append("- " + item.text)
    return (STYLE_POLICY_HINT_OPEN + "\n" + "\n".join(lines) + "\n"
            + STYLE_POLICY_HINT_CLOSE)


def _exclusions(items: list[_HintItem], reason: str) -> list[HintExclusion]:
    out: list[HintExclusion] = []
    for item in items:
        keys = item.rule_ids or (f"meta.{item.kind}",)
        for key in keys:
            out.append(HintExclusion(key=key, kind=item.kind, reason=reason))
    return out


def render_style_policy_hint(policy=None, *, limits: Mapping | None = None,
                             max_chars: int = 0, max_items: int = 0,
                             budget_chars: int = 0) -> HintRender:
    """Hint активных правил Style Policy для Writer (слой 10).

    Вход - `services.style_policy.EffectiveStylePolicy` (или любой объект с
    полями ``extent``/``hard_kinds``/``soft_kinds``/``soft_instructions``).
    Выход - :class:`HintRender`: блок ``<Style_Policy_Hint>`` и фактический
    состав. ``0``/отсутствие лимита = без ограничения (ASAP3 §1.2).

    Никакого обрезания строки посередине: инструкция либо входит целиком, либо
    исключается целиком с причиной (``user_limit``/``budget_excluded``).
    Никогда не бросает.
    """
    try:
        if isinstance(limits, Mapping):
            if "max_chars" in limits:
                max_chars = limits.get("max_chars")
            if "max_items" in limits:
                max_items = limits.get("max_items")
            if "budget_chars" in limits:
                budget_chars = limits.get("budget_chars")
        limit_chars = _limit_value(max_chars)
        limit_items = _limit_value(max_items)
        budget = _limit_value(budget_chars)
        candidates = _hint_candidates(policy)
        kept = list(candidates)
        excluded: list[HintExclusion] = []
        reasons: list[str] = []
        if limit_items and len(kept) > limit_items:
            excluded.extend(_exclusions(kept[limit_items:], "user_limit"))
            kept = kept[:limit_items]
            reasons.append("items")
        if limit_chars:
            while kept and len(_render_block(kept)) > limit_chars:
                excluded.extend(_exclusions(kept[-1:], "user_limit"))
                kept.pop()
                if "chars" not in reasons:
                    reasons.append("chars")
        if budget:
            while kept and len(_render_block(kept)) > budget:
                excluded.extend(_exclusions(kept[-1:], "budget_excluded"))
                kept.pop()
                if "budget" not in reasons:
                    reasons.append("budget")
        block = _render_block(kept)
        return HintRender(
            block, total_items=len(candidates), included_items=len(kept),
            included_keys=[key for item in kept
                           for key in (item.rule_ids or (f"meta.{item.kind}",))],
            excluded=tuple(excluded), max_chars=limit_chars,
            max_items=limit_items, limited_by="+".join(reasons),
            truncated=False)
    except Exception:      # pragma: no cover - hint не роняет сборку
        return HintRender("")
