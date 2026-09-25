"""A4 `image-context-memory-round1026` (Эпик 3, Wave 4; ADR-1026-19; risk R3).

Детерминированный helper над **существующими** источниками A6: один
источник истины для memory-aware image-пути (§22–§25). Одна реализация —
две точки вызова (direct `maybe_handle_keyword` и tool `_generate_image`).

Границы (binding, ADR-1026-19 D1/D2):
* НЕ второй резолвер имён (reuse `AliasResolver`/`build_alias_resolver`);
* НЕ второй RAG/generic-lookup/envelope/pipeline;
* НЕ импортирует `tool_router` (иначе цикл `tool_router`→`image_generation`
  →helper→`tool_router`); ридеры (`db.get_user_context_facts`, `memory.*`)
  вызываются напрямую по тем же контрактам, что и A6.

§37: любые факты/RAG-строки трактуются как ДАННЫЕ (не инструкции); §R17:
лог — только id/enum/числа/латентность (см. `log_image_context_build`,
эмитится из `image_generation.build_final_prompt` с `prompt_chars`).
"""
from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

# ── hard-потолки (код-константы; в пределах A6: appearance 10/20, slice 5/10,
# result 4000). Выходные капы — env-only `settings.IMAGE_CONTEXT_*`. ───────
_FACTS_HARD = 10
_SLICE_HARD = 5
_RESULT_MAX_CHARS = 4000
_FACTS_SCAN = 50            # bounded пул чтения graph_facts (<< A6 200)
_SLICE_SCAN = 20            # bounded пул сообщений/RAG

# Дефолты капов (§3.2); реальные значения — `settings.IMAGE_CONTEXT_*`.
_DEFAULTS = {
    "facts_max": 8,
    "fact_max_chars": 160,
    "slice_max": 3,
    "slice_max_chars": 200,
    "total_max_chars": 1200,
}
_SETTING_NAME = {
    "facts_max": "IMAGE_CONTEXT_FACTS_MAX",
    "fact_max_chars": "IMAGE_CONTEXT_FACT_MAX_CHARS",
    "slice_max": "IMAGE_CONTEXT_SLICE_MAX",
    "slice_max_chars": "IMAGE_CONTEXT_SLICE_MAX_CHARS",
    "total_max_chars": "IMAGE_CONTEXT_TOTAL_MAX_CHARS",
}

# Закрытый enum фактически использованных видов источников (D3).
SOURCE_ALIAS = "alias"
SOURCE_FACTS = "graph_facts"
SOURCE_PORTRAIT = "dossier_portrait"
SOURCE_SLICE = "message_slice"
SOURCE_RAG = "rag"

# ── A4 narrow visual extraction (пробел A4): ограниченный лексикон-стемы ──
_VISUAL_LEXICON = {
    "glasses": ("очк",),
    "beard": ("бород", "усы"),
    "hairstyle": ("причёс", "причес", "волос", "стриж", "лыс", "седин"),
    "clothing": ("одежд", "одет", "носит", "куртк", "костюм", "шляп",
                 "кепк", "пальто", "кроссовк"),
    "appearance": ("внешн", "выгляд", "высок", "низк", "худ", "полн",
                   "толст", "стройн", "глаз", "улыб", "тату", "шрам",
                   "рост", "лицо", "бров", "родинк", "веснушк", "модн"),
}
# Визуальные предпочтения — только прямо упомянутые.
_PREFERENCE_MARKERS = ("предпочита", "любит", "нравит", "обычно носит")
# Психологический denylist (приоритетно исключает факт из визуальных
# утверждений — §23 «психология ≠ внешность»).
_PSYCH_DENY = (
    "характер", "личность", "добр", "злой", "умн", "весёл", "весел",
    "груст", "темперамент", "настроен", "мышлен", "душевн", "эмпат",
    "интроверт", "экстраверт", "скромн", "застенчив", "уверен в себе",
)
# Узкий маркер «точное сходство» (D6) → ветка запроса фото/референса.
_EXACT_LIKENESS = (
    "точное сходство", "точный портрет", "как настоящий",
    "реалистичный портрет", "как на фото", "настоящее лицо", "похож как",
    "максимально похож",
)
_SELF_TOKENS = {"меня", "себя", "себе", "мою", "мой", "моя", "моё", "мое",
                "моей", "моём", "моем"}

# ── F1 collision guard (review T-3640; REQ-A4-09/-02/-08) ──────────────────
# Alias-матч — generic-токенный; короткое/общеупотребительное слово в чужом
# запросе («нарисуй кота») не должно «захватывать» чужое досье как субъекта.
# (b) alias-токен короче _MIN_ALIAS_TOKEN_LEN не персонализирует;
# (c)/(d) общеупотребительные image-объекты (RU/EN) — никогда не человек.
_MIN_ALIAS_TOKEN_LEN = 4
_ALIAS_STOPLIST = frozenset({
    # RU: кот
    "кот", "кота", "коту", "коте", "коты", "котов", "кошка", "кошки",
    "кошку", "кошке", "кошек", "котенок", "котёнок",
    # RU: лис
    "лис", "лиса", "лису", "лисе", "лисы", "лисов", "лисий",
    # RU: малыш/ребёнок
    "малыш", "малыша", "малышу", "малыше", "малыши", "малышей",
    "ребенок", "ребёнок", "ребенка", "ребёнка", "ребенку", "ребёнку",
    # RU: медведь
    "медведь", "медведя", "медведю", "медведи", "медведей",
    # RU: прочие частые image-объекты
    "пес", "пёс", "пса", "псы", "собака", "собаки", "собаку", "собак",
    "волк", "волка", "волки", "волков", "заяц", "зайца", "зайцы",
    "лошадь", "лошади", "корова", "коровы", "птица", "птицы", "рыба",
    "рыбы", "дракон", "дракона", "робот", "робота", "дерево", "дерева",
    "цветок", "цветка", "машина", "машины", "корабль", "корабля",
    "солнце", "луна", "звезда", "небо", "море", "замок",
    # EN
    "cat", "cats", "fox", "foxes", "baby", "child", "children",
    "bear", "bears", "dog", "dogs", "wolf", "wolves", "rabbit", "hare",
    "horse", "cow", "bird", "fish", "dragon", "robot", "tree", "flower",
    "car", "ship", "sun", "moon", "star", "sky", "sea", "castle",
})

# ── D13 corroboration gate (review T-3640 cycle-2 F1; ADR-1026-19 D13) ─────
# Alias-совпадение — только КАНДИДАТ; `resolved` выдаёт шлюз G1 (person-intent,
# класс-закрывающий) + G2 (persona-рекорд, REQ-A4-09) + G3 (image-object,
# defense-in-depth). G0 (len/stoplist) сохранён выше как defense-in-depth.

# G1 — закрытый набор person-intent маркеров (spec §3.1). Совпадение —
# casefold-exact по целому токену (или цельной многокорневой фразе);
# морфологическая терпимость допускается ТОЛЬКО как ТОЧНОЕ равенство стемов
# (`_stem(token) == _stem(marker)`), но НИКОГДА `token.startswith(marker)`.
# Это закрывает открытое префиксное семейство (фотон/фотоаппарат/фотография/
# фотомодель, портретист, …), утекавшее при прежнем `startswith` (review
# T-3640 cycle 3, C3-H1), и сохраняет склонения самих маркеров
# (портрет/портрета/портрету, внешность/внешности, выглядит/выглядел).
# «Только заглавная буква» НЕ учитывается и G1 не удовлетворяет.
_PERSON_INTENT_TOKENS = frozenset({
    "парень", "парня", "парню", "парне", "парни", "парней",
    "мужчина", "мужчины", "мужчину", "мужчине", "мужчин",
    "человек", "человека", "человеку", "человеке", "человеком", "люди",
    "девушка", "девушки", "девушку", "девушке", "девушек",
    "женщина", "женщины", "женщину", "женщине", "женщин",
    "друг", "друга", "другу", "друге", "друзья", "друзей", "другом",
    "подруга", "подруги", "подругу", "подруге", "подруг",
    "знакомый", "знакомая", "знакомого", "знакомому", "знакомой",
    "знакомые",
    # лицо/образ — только точные формы (без рискованных стемов)
    "лицо", "лица", "лице", "образ", "образа", "образу", "образом",
    "образе",
})
# Разрешённые словоформы маркеров; из них выводятся допустимые стемы.
# Префиксное семейство сюда намеренно НЕ входит: «фото» ≠ «фотон»,
# «портрет» ≠ «портретист», «снимок» ≠ «снимать».
_PERSON_INTENT_MARKER_FORMS = (
    # «как выглядит/выглядел/выглядела» (verb family)
    "выглядит", "выглядел", "выглядела", "выглядели", "выглядишь",
    "выгляжу", "выглядим", "выглядите", "выглядят",
    # «портрет» + безопасные склонения («портретист» — другое слово)
    "портрет", "портрета", "портрету", "портретом", "портрете",
    # «внешность/внешне»
    "внешность", "внешности", "внешностью", "внешн", "внешне",
    # «фото/фотограф» (НЕ фотон/фотоаппарат/фотография/фотомодель)
    "фото", "фотограф", "фотографа", "фотографу", "фотографом",
    "фотографе",
    # «снимок» + склонения (НЕ снимать/сними)
    "снимок", "снимка", "снимку", "снимке", "снимки", "снимков",
    # «досье»
    "досье",
    # «похож/похожа/похожий» (C3-M1; spec §3.1)
    "похож", "похожа", "похожий", "похожего", "похожей", "похожие",
    "похожих", "похожему", "похожим", "похожую",
)
# «про/о/об <человек>» — предлог удовлетворяет G1 ТОЛЬКО когда следующий
# токен — явная ссылка на человека (закрытый набор человек-существительных/
# местоимений), а НЕ произвольная тема. Голое «про <тему>»/«об <тему>»
# персонализацию не разблокирует (review C3-H1; консервативное no-leak
# чтение: имя после предлога намеренно НЕ принимается — false-negative).
_PERSON_INTENT_ABOUT = frozenset({"про", "о", "об"})
_PERSON_ABOUT_OBJECTS = _PERSON_INTENT_TOKENS | _SELF_TOKENS | frozenset({
    "него", "нему", "ним", "нём", "нем", "неё", "нее", "ней", "нею",
    "тебя", "тебе", "тобой", "вас", "вам", "вами", "нас", "нам",
    "нами", "них", "им", "ими", "ей", "его", "ему",
})

# G3 — производный image-object лексикон (spec §3.1): `_ALIAS_STOPLIST` +
# объектные стемы image-промпт-домена. Defense-in-depth (класс закрывает G1).
_IMAGE_OBJECT_EXTRA = frozenset({
    "тигр", "тигров", "тигрёнок", "роз", "розочек", "панд", "зайк",
    "ромашк", "лисичк", "ежик", "ёжик", "кит", "китов", "акул", "лев",
    "львов", "слон", "жираф", "зебр", "обезьян", "пантер", "гепард",
    "ягуар", "феникс", "единорог", "русалка", "принцесс", "принц",
    "рыцар", "воин", "самурай", "ниндзя", "пират", "космонавт",
    "астронавт", "киборг", "зомби", "вампир", "ведьм", "фея", "ангел",
    "демон", "тролл", "гном", "эльф", "орк", "динозавр", "мамонт",
    "бабочк", "пчел", "паук", "змея", "черепах", "дельфин", "осьминог",
    "краб", "пингвин", "сов", "орел", "орёл", "ворон", "голубь",
    "воробей", "синиц", "петух", "куриц", "утк", "гусь", "лебед",
    "павлин", "фламинго", "попугай", "хомяк", "мыш", "крыс", "белк",
    "енот", "барсук", "выдр", "бобр", "олен", "лось", "косул", "кабан",
    "свинья", "порос", "коз", "овц", "баран", "бык", "телен", "телён",
    "щенок", "снеговик", "клоун", "цирк", "дворец", "храм", "церковь",
    "башн", "лес", "поле", "гор", "рек", "озер", "океан", "пляж",
    "остров", "пещер", "вулкан", "пустын", "цветок", "куст", "трава",
    "лист", "яблок", "ягод", "гриб", "кактус", "пальм", "дуб", "берез",
    "берёз", "клен", "клён", "грузовик", "автобус", "поезд", "самолет",
    "самолёт", "вертолет", "вертолёт", "ракет", "лодк", "подлодк",
    "велосипед", "мотоцикл", "танк", "пушк", "меч", "щит", "стрел",
    "книг", "часы", "ламп", "стол", "стул", "кресл", "шкаф", "кроват",
    "дверь", "окн", "зеркал", "портрет", "картин", "статуя", "скульптур",
    # image-артефакты (review C3-H1): голое совпадение alias с «фото/снимок/
    # досье» — это предмет, не человек, поэтому точное совпадение имени и
    # слова-артефакта блокируется G3. Легитимные «фото Лёхи» не задеваются:
    # matched-токен там имя субъекта, а не артефакт.
    "фото", "снимок", "снимк", "досье",
    "круг", "квадрат", "треугольник", "сердц", "планет", "космос",
    "галактик", "комет", "метеорит", "дождь", "снег", "радуг", "гроз",
    "молния", "туман", "облак", "ветер", "огон", "огонь", "земл",
    "песок", "камень",
})
_IMAGE_OBJECT_LEXICON = frozenset(_ALIAS_STOPLIST) | _IMAGE_OBJECT_EXTRA
_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ── капы ──────────────────────────────────────────────────────────────────


def _cap(name: str) -> int:
    """Значение капа: `settings.IMAGE_CONTEXT_*` (env-only) → дефолт §3.2.
    Верхний предел всегда в A6-потолках (`_FACTS_HARD`/`_SLICE_HARD`)."""
    default = int(_DEFAULTS[name])
    value = default
    try:
        from config.settings import settings
        value = int(getattr(settings, _SETTING_NAME[name], default))
    except Exception:
        value = default
    if name == "facts_max":
        return max(1, min(value, _FACTS_HARD))
    if name == "slice_max":
        return max(0, min(value, _SLICE_HARD))
    if name == "total_max_chars":
        return max(1, min(value, _RESULT_MAX_CHARS))
    return max(1, value)


# ── санитайзинг / утилиты ──────────────────────────────────────────────────


def _sanitize(text) -> str:
    """Удаление управляющих символов + нормализация пробелов. Содержимое
    НЕ исполняется и не превращается в команды (§37)."""
    clean = _CONTROL_RE.sub(" ", str(text or ""))
    return " ".join(clean.split()).strip()


def _truncate(text, limit) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:max(1, limit - 1)].rstrip() + "…"


def _words(text) -> list[str]:
    return _WORD_RE.findall(str(text or "").casefold())


def _stem(word: str) -> str:
    """Консервативный стем (casefold + снятие одного падежного гласного).
    Только для alias-матча; длина < 3 не используется (анти-шум)."""
    w = str(word or "").casefold().strip()
    if len(w) >= 4 and w[-1] in "аеёиоуыэюяй":
        w = w[:-1]
    return w


# G3 stem-set производного image-object лексикона (после `_stem`).
_IMAGE_OBJECT_STEMS = frozenset(_stem(w) for w in _IMAGE_OBJECT_LEXICON)
# G1 маркер-стемы (точное равенство; вычисляются после определения `_stem`).
_PERSON_INTENT_MARKER_STEMS = frozenset(
    _stem(form) for form in _PERSON_INTENT_MARKER_FORMS)


def _mapping(aliases):
    return getattr(aliases, "_aliases", None) if aliases is not None else None


async def _lazy_aliases(chat_id):
    """Fail-open существующий per-chat резолвер (второй НЕ создаётся)."""
    try:
        from services.summary_aliases import build_alias_resolver
        return await build_alias_resolver(chat_id)
    except Exception:
        logger.warning("[image-ctx] aliases unavailable | chat=%s", chat_id)
        return None


def _alias_name(aliases, uid, fallback=None) -> str:
    if aliases is not None and hasattr(aliases, "resolve"):
        try:
            return str(aliases.resolve(int(uid), fallback or None, None))
        except Exception:
            pass
    return str(fallback or uid)


# ── B: разрешение субъекта (§24; D3) ───────────────────────────────────────


def _alias_stems(value) -> set:
    """Eligible normalized alias-token stems (F1 collision guard, T-3640).

    Spec §3.1 matches request tokens exactly after casefold + one-step
    conservative stem. F1 keeps that mechanism but adds guards so that a mere
    string collision with a common image-object word can no longer capture a
    foreign dossier as the image subject:
    * alias word raw length must be >= ``_MIN_ALIAS_TOKEN_LEN`` (b);
    * alias word listed in ``_ALIAS_STOPLIST`` (common RU/EN image objects) is
      never a person reference and is skipped (c)/(d)."""
    stems = set()
    for word in _words(value):
        word = word.casefold()
        if len(word) < _MIN_ALIAS_TOKEN_LEN or word in _ALIAS_STOPLIST:
            continue
        stems.add(_stem(word))
    return stems


def _resolve_subject(user_request, requester_id, aliases) -> dict:
    """Сигналы (приоритет, D3/D13): explicit user_id (зарезервировано) →
    alias-матч токенов запроса (**кандидат!**) → first-person + requester_id.
    Иначе `none` (только по отображаемому имени пользователь НЕ определяется).

    D13 (T-3646): alias-совпадение больше **не** даёт `resolved` — оно
    возвращает ``resolution="candidate"`` и ``candidates`` (id). Окончательное
    `resolved` выдаёт корроборационный шлюз (`_corroborate_subject`: G1
    person-intent + G2 persona-рекорд + G3 image-object). F1-guard'ом
    (`_alias_stems`, G0) alias-матч ограничен; first-person остаётся id-based
    (не строковым) и разрешается напрямую."""
    mapping = _mapping(aliases)
    matched: list[int] = []
    if isinstance(mapping, dict):
        request_stems = {_stem(t) for t in _words(user_request)}
        request_stems = {s for s in request_stems if len(s) >= 3}
        for key, value in mapping.items():
            try:
                uid = int(key)
            except (TypeError, ValueError):
                continue
            alias_stems = _alias_stems(value)
            if alias_stems & request_stems and uid not in matched:
                matched.append(uid)
    uniq = sorted(matched)
    if uniq:
        # D13: alias-матч — только кандидат (G0), не доказательство.
        return {"user_id": None, "name": "", "resolution": "candidate",
                "candidates": uniq}
    if requester_id is not None and _has_self_marker(user_request):
        uid = int(requester_id)
        return {"user_id": uid, "name": _alias_name(aliases, uid),
                "resolution": "resolved", "candidates": []}
    return {"user_id": None, "name": "", "resolution": "none",
            "candidates": []}


def _has_self_marker(user_request) -> bool:
    return bool(_SELF_TOKENS & set(_words(user_request)))


def _detect_exact_likeness(user_request) -> bool:
    low = str(user_request or "").casefold()
    return any(marker in low for marker in _EXACT_LIKENESS)


# ── D13 corroboration gate G1/G2/G3 (spec §3.1; ADR-1026-19 D13) ───────────


def _has_person_intent(user_request) -> bool:
    """G1: явный маркер ссылки на человека из закрытого набора (spec §3.1).

    Матчинг ТОЧНЫЙ (closed-set): цельный casefold-токен/фраза либо точное
    равенство стемов (``_stem(token) == _stem(marker)``). Префиксный матчинг
    запрещён — иначе открытые семейства (фотон/фотоаппарат/фотография/
    фотомодель, портретист, …) ложно получают person-intent (review C3-H1).
    Предлог «про/о/об» учитывается только перед токеном-человеком; голое
    «про <тема>» G1 не удовлетворяет. Заглавная буква сама по себе — слабый
    сигнал и G1 не даёт (здесь только casefold-токены), поэтому
    «Нарисуй Тигр» (только заглавная) G1 не проходит."""
    tokens = _words(user_request)
    if not tokens:
        return False
    if any(tokens[i] == "в" and tokens[i + 1] == "образе"
           for i in range(len(tokens) - 1)):
        return True
    for token in tokens:
        if token in _PERSON_INTENT_TOKENS:
            return True
        if _stem(token) in _PERSON_INTENT_MARKER_STEMS:
            return True
    for i in range(len(tokens) - 1):
        if tokens[i] in _PERSON_INTENT_ABOUT and \
                tokens[i + 1] in _PERSON_ABOUT_OBJECTS:
            return True
    return False


def _alias_value_for(mapping, uid):
    if not isinstance(mapping, dict):
        return None
    for key, value in mapping.items():
        try:
            if int(key) == int(uid):
                return value
        except (TypeError, ValueError):
            continue
    return None


def _matched_request_tokens(user_request, aliases, uid) -> list:
    """Токены запроса, чей стем совпал с eligible alias-стемами кандидата."""
    value = _alias_value_for(_mapping(aliases), uid)
    if value is None:
        return []
    alias_stems = _alias_stems(value)
    if not alias_stems:
        return []
    return [t for t in _words(user_request) if _stem(t) in alias_stems]


def _is_image_object(token) -> bool:
    """G3: токен классифицируется как image-объект/предмет-атрибут."""
    tok = str(token or "").casefold().strip()
    if not tok:
        return False
    if tok in _IMAGE_OBJECT_LEXICON:
        return True
    if _stem(tok) in _IMAGE_OBJECT_STEMS:
        return True
    # overlap с A4 visual-классификатором (предмет/атрибут)
    return _classify_visual(tok) is not None


def _candidate_is_image_object(user_request, aliases, uid) -> bool:
    tokens = _matched_request_tokens(user_request, aliases, uid)
    if not tokens:
        return False
    return all(_is_image_object(t) for t in tokens)


async def _persona_names(db, chat_id):
    """G2 reader: имена участников чата со счётчиком фактов (только
    name+count, БЕЗ текста фактов). Недоступен/ошибка → None (unknown_person)."""
    reader = getattr(db, "get_persona_names", None)
    if not callable(reader):
        return None
    try:
        return await reader(chat_id, int(time.time()))
    except Exception:
        logger.warning("[image-ctx] persona roster read failed | chat=%s",
                       chat_id)
        return None


def _name_in_roster(name, roster) -> bool:
    target = str(name or "").strip().casefold()
    if not target:
        return False
    for row in roster or []:
        if isinstance(row, dict):
            candidate = row.get("name")
        elif isinstance(row, (tuple, list)) and row:
            candidate = row[0]
        else:
            candidate = row
        if str(candidate or "").strip().casefold() == target:
            return True
    return False


async def _corroborate_subject(*, user_request, aliases, db, chat_id,
                               candidates) -> dict:
    """Шлюз D13 над alias-кандидатами: G1 → G2 → G3.

    Возврат ``{"resolution": "eligible"|"no_person_intent"|"unknown_person",
    "candidates": [uid], "names": {uid: name}}``. Факты досье здесь НЕ
    читаются (только roster name+count)."""
    if not _has_person_intent(user_request):
        return {"resolution": "no_person_intent", "candidates": [],
                "names": {}}
    roster = await _persona_names(db, chat_id)
    if roster is None:
        return {"resolution": "unknown_person", "candidates": [], "names": {}}
    names: dict = {}
    corroborated: list[int] = []
    for uid in candidates or []:
        name = _alias_name(aliases, uid)
        if _name_in_roster(name, roster):
            corroborated.append(int(uid))
            names[int(uid)] = name
    if not corroborated:
        return {"resolution": "unknown_person", "candidates": [], "names": {}}
    eligible = [uid for uid in corroborated
                if not _candidate_is_image_object(user_request, aliases, uid)]
    if not eligible:
        return {"resolution": "no_person_intent", "candidates": [],
                "names": names}
    return {"resolution": "eligible", "candidates": eligible, "names": names}


# ── C: визуальный срез (§22–§23; D4) ───────────────────────────────────────


def _classify_visual(text):
    """Стем-классификация визуальной категории. Психологический denylist
    проверяется ПЕРВЫМ → псих-факт никогда не становится внешностью."""
    low = str(text or "").casefold()
    if not low:
        return None
    if any(stem in low for stem in _PSYCH_DENY):
        return None
    for category, stems in _VISUAL_LEXICON.items():
        if any(stem in low for stem in stems):
            return category
    if any(marker in low for marker in _PREFERENCE_MARKERS):
        return "preferences"
    return None


def _fact_item(row, category) -> dict:
    return {
        "text": _sanitize(row.get("fact") or ""),
        "category": str(category),
        "confidence": "confirmed",
        "source_id": str(row.get("id") or ""),
    }


async def _collect_visual_facts(db, chat_id, name, facts_max) -> list:
    reader = getattr(db, "get_user_context_facts", None)
    if not callable(reader) or not name:
        return []
    try:
        rows = await reader(chat_id, name, _FACTS_SCAN, int(time.time()))
    except Exception:
        logger.warning("[image-ctx] facts read failed | chat=%s", chat_id)
        return []
    out: list[dict] = []
    for row in rows or []:
        try:
            row = dict(row)
        except (TypeError, ValueError):
            continue
        text = _sanitize(row.get("fact") or "")
        category = _classify_visual(text)
        if category is None:
            continue
        item = _fact_item(row, category)
        item["text"] = _truncate(item["text"], _cap("fact_max_chars"))
        out.append(item)
        if len(out) >= facts_max:
            break
    return out


def _entry_text(entry) -> str:
    if isinstance(entry, dict):
        return _sanitize(entry.get("fact") or entry.get("text") or "")
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return _sanitize(entry[1])
    return ""


async def _bounded_slice(memory, chat_id, name, slice_max, slice_chars) -> list:
    """Ленивый bounded срез RAG/сообщений; только визуально релевантные
    фрагменты; капы по числу/длине (D4)."""
    if memory is None or not name or slice_max <= 0:
        return []
    out: list[dict] = []
    getter = getattr(memory, "get_rag_facts", None)
    if callable(getter):
        try:
            rag = await getter(chat_id, name)
        except Exception:
            rag = []
        for entry in rag or []:
            text = _entry_text(entry)
            category = _classify_visual(text)
            if category is None:
                continue
            out.append({"text": _truncate(text, slice_chars),
                        "category": category, "kind": "rag"})
            if len(out) >= slice_max:
                return out
    searcher = getattr(memory, "search_long_term", None)
    if callable(searcher) and len(out) < slice_max:
        try:
            rows = await searcher(chat_id, [name], limit=_SLICE_SCAN)
        except Exception:
            rows = []
        for row in rows or []:
            try:
                item = dict(row)
            except (TypeError, ValueError):
                continue
            text = _sanitize(item.get("text") or "")
            category = _classify_visual(text)
            if category is None:
                continue
            out.append({"text": _truncate(text, slice_chars),
                        "category": category, "kind": "message"})
            if len(out) >= slice_max:
                break
    return out


async def _collect_dossier_context(db, chat_id, name, max_chars) -> str:
    """`dossier_portrait` — ТОЛЬКО не-визуальный контекст (паттерны/темы);
    никогда не источник черт лица/внешности (§23)."""
    getter = getattr(db, "get_generated_dossier", None)
    if not callable(getter) or not name:
        return ""
    try:
        dossier = await getter(chat_id, name)
    except Exception:
        return ""
    if not isinstance(dossier, dict):
        return ""
    patterns = [_sanitize(x) for x in (dossier.get("patterns") or [])
                if _sanitize(x)]
    themes = [_sanitize(x) for x in (dossier.get("themes") or [])
              if _sanitize(x)]
    parts = []
    if patterns:
        parts.append("Паттерны: " + "; ".join(patterns[:5]))
    if themes:
        parts.append("Темы: " + "; ".join(themes[:5]))
    return _truncate(" ".join(parts), max_chars)


def _apply_total_cap(memory_context: dict, total_chars: int) -> dict:
    """Общий бюджет среза (§3.2 `IMAGE_CONTEXT_TOTAL_MAX_CHARS`, ≤4000)."""
    used = 0
    kept_facts, kept_slice = [], []
    for item in memory_context.get("facts") or []:
        text = str(item.get("text") or "")
        if not text:
            continue
        if used + len(text) > total_chars and kept_facts:
            break
        used += len(text)
        kept_facts.append(item)
    for item in memory_context.get("slice") or []:
        text = str(item.get("text") or "")
        if not text:
            continue
        if used + len(text) > total_chars and kept_slice:
            break
        used += len(text)
        kept_slice.append(item)
    memory_context["facts"] = kept_facts
    memory_context["slice"] = kept_slice
    return memory_context


# ── сборка результата ──────────────────────────────────────────────────────


def _subject_public(subject: dict) -> dict:
    out = {"user_id": subject.get("user_id"),
           "name": str(subject.get("name") or ""),
           "resolution": str(subject.get("resolution") or "resolved")}
    if out["resolution"] == "ambiguous":
        out["candidates"] = list(subject.get("candidates") or [])
    return out


def _context(*, resolution, subject=None, facts=None, slice_=None,
             context=None, has_visual=False, artistic_only=True,
             ambiguous=False, exact_likeness=False, empty_reason="",
             latency_ms=0) -> dict:
    return {
        "resolution": str(resolution or ""),
        "subject": subject,
        "facts": list(facts or []),
        "slice": list(slice_ or []),
        "context": list(context or []),
        "has_visual": bool(has_visual),
        "artistic_only": bool(artistic_only),
        "ambiguous": bool(ambiguous),
        "exact_likeness": bool(exact_likeness),
        "empty_reason": str(empty_reason or ""),
        "latency_ms": int(latency_ms),
    }


def _result(subjects, required, sources, memory_context) -> dict:
    return {
        "resolved_subjects": list(subjects or []),
        "context_required": bool(required),
        "context_sources": list(sources or []),
        "memory_context": memory_context,
    }


def _empty(reason: str, *, resolution="none", exact=False) -> dict:
    return _result([], False, [], _context(
        resolution=resolution, artistic_only=False, exact_likeness=exact,
        empty_reason=reason))


# ── публичный API (D1/D2) ──────────────────────────────────────────────────


async def _build_resolved_result(*, chat_id, subject, exact, started, db,
                                 memory) -> dict:
    """Визуальный срез для подтверждённого субъекта (§3.2; D4). Читает факты
    ровно одного `user_id` (изоляция REQ-A4-11)."""
    name = subject["name"]
    facts_max = _cap("facts_max")
    facts = await _collect_visual_facts(db, chat_id, name, facts_max)
    sources = [SOURCE_ALIAS]
    if facts:
        sources.append(SOURCE_FACTS)
    dossier = await _collect_dossier_context(
        db, chat_id, name, _cap("fact_max_chars"))
    if dossier:
        sources.append(SOURCE_PORTRAIT)
    slice_: list[dict] = []
    if not facts:
        slice_ = await _bounded_slice(
            memory, chat_id, name, _cap("slice_max"),
            _cap("slice_max_chars"))
        kinds = {str(it.get("kind") or "") for it in slice_}
        if "rag" in kinds:
            sources.append(SOURCE_RAG)
        if "message" in kinds:
            sources.append(SOURCE_SLICE)
    has_visual = bool(facts or slice_)
    memory_context = _context(
        resolution="resolved", subject=subject, facts=facts, slice_=slice_,
        context=[dossier] if dossier else [], has_visual=has_visual,
        artistic_only=not has_visual, ambiguous=False,
        exact_likeness=exact,
        empty_reason="" if has_visual else "no_visual_data",
        latency_ms=int((time.monotonic() - started) * 1000))
    _apply_total_cap(memory_context, _cap("total_max_chars"))
    return _result([_subject_public(subject)], True,
                   _dedup(sources), memory_context)


def _ambiguous_result(subject, exact, started) -> dict:
    return _result(
        [_subject_public(subject)], True, [SOURCE_ALIAS],
        _context(resolution="ambiguous", ambiguous=True,
                 artistic_only=True, exact_likeness=exact,
                 empty_reason="ambiguous",
                 latency_ms=int((time.monotonic() - started) * 1000)))


async def build_image_memory_context(*, chat_id, user_request,
                                     requester_id=None, aliases=None,
                                     db=None, memory=None) -> dict:
    """Единственная реализация memory-доступа image-пути.

    Возврат: `{resolved_subjects, context_required, context_sources,
    memory_context}`. Fail-open: любая ошибка → `none`/honest `empty_reason`,
    image-путь не падает (§3.1).

    D13 (T-3646): alias-матч даёт **кандидата**, персонализацию разблокирует
    только корроборационный шлюз `_corroborate_subject` (G1 person-intent →
    G2 persona-рекорд → G3 image-object). Generic-запрос («нарисуй <сущ.»)
    персонализацию не открывает независимо от лексиконов (класс-инвариант)."""
    started = time.monotonic()
    exact = _detect_exact_likeness(user_request)
    try:
        if aliases is None:
            aliases = await _lazy_aliases(chat_id)
        subject = _resolve_subject(user_request, requester_id, aliases)
        resolution = subject["resolution"]
        if resolution == "none":
            return _empty("unknown_person", exact=exact)
        if resolution == "candidate":
            gate = await _corroborate_subject(
                user_request=user_request, aliases=aliases, db=db,
                chat_id=chat_id, candidates=subject.get("candidates") or [])
            gres = gate["resolution"]
            if gres == "no_person_intent":
                return _empty("no_person_intent", exact=exact)
            if gres == "unknown_person":
                return _empty("unknown_person", exact=exact)
            eligible = list(gate.get("candidates") or [])
            if len(eligible) > 1:
                return _ambiguous_result(
                    {"user_id": None, "name": "", "resolution": "ambiguous",
                     "candidates": eligible}, exact, started)
            uid = int(eligible[0])
            subject = {
                "user_id": uid,
                "name": gate.get("names", {}).get(uid)
                or _alias_name(aliases, uid),
                "resolution": "resolved", "candidates": []}
        return await _build_resolved_result(
            chat_id=chat_id, subject=subject, exact=exact, started=started,
            db=db, memory=memory)
    except Exception as exc:  # pragma: no cover — fail-open контракт
        logger.warning("[image-ctx] build failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        return _empty("empty", exact=exact)


def _dedup(values) -> list:
    out: list[str] = []
    for value in values or []:
        if value and value not in out:
            out.append(value)
    return out


def attach_image_memory(request, data) -> None:
    """Заполнение аддитивных полей A3 (§3.6) из результата helper."""
    if request is None or not isinstance(data, dict):
        return
    request.resolved_subjects = list(data.get("resolved_subjects") or [])
    request.context_required = bool(data.get("context_required"))
    request.context_sources = list(data.get("context_sources") or [])
    request.memory_context = data.get("memory_context") or {}


def build_reply_note(memory_context) -> str:
    """Reply-заметка (D5/D6): уточнение при неоднозначности, дисклеймер
    «арт ≠ портрет», запрос фото/референса при точном сходстве. Без имён и
    без текста досье."""
    if not isinstance(memory_context, dict):
        return ""
    parts = []
    if memory_context.get("ambiguous"):
        parts.append("В чате несколько совпадений по имени — уточните, "
                     "пожалуйста, о ком речь: без этого я не могу "
                     "персонализировать изображение.")
    if memory_context.get("exact_likeness"):
        parts.append("Для точного сходства пришлите, пожалуйста, фотографию "
                     "или визуальный референс — по описанию создаётся "
                     "художественная интерпретация, а не документальный "
                     "портрет.")
    elif memory_context.get("artistic_only") and \
            memory_context.get("has_visual") is False:
        parts.append("Это художественная интерпретация, а не достоверный "
                     "портрет.")
    return " ".join(parts)


def log_image_context_build(*, chat_id, subject_id, resolution, sources,
                            facts, slice_count, prompt_chars, artistic_only,
                            exact_likeness, empty_reason, latency_ms) -> None:
    """R17-safe лог (§3.5): только id/enum/числа/латентность. НИКОГДА —
    имена/текст досье/фактов/сообщений/промпта/ключей."""
    logger.info(
        "[image-ctx] build | chat_id=%s | subject_id=%s | resolution=%s | "
        "sources=%s | facts=%d | slice=%d | prompt_chars=%d | "
        "artistic_only=%s | exact_likeness=%s | empty_reason=%s | "
        "latency_ms=%d",
        chat_id, subject_id if subject_id is not None else "-",
        resolution or "-", ",".join(sources or []), int(facts),
        int(slice_count), int(prompt_chars), bool(artistic_only),
        bool(exact_likeness), empty_reason or "", int(latency_ms))
