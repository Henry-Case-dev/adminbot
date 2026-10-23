"""SOUL-07 (W4) — Few-Shot библиотека примеров: хранение, CRUD, отбор.

Контракт слайса (design-source-of-truth §2.3 + requirements-map W4):

* **SOUL-07.0/07.1** — единственная новая таблица слайса `humor_samples`
  (построчный CRUD/архив/ревизия/фильтры), заводская подборка 15–30
  ОРИГИНАЛЬНЫХ и разных по композиции примеров сидируется как
  **неодобренные черновики** (`owner_approved=0`,
  `source_kind='bot_suggested'`): библиотека никогда не выдаётся за
  проверенную владельцем.
* **SOUL-07.2** — на ответ отбирается 1–3 уместных и различных примера
  (или ни одного): семантика/тема, diversity, recency/penalty, пригодность к
  extent, жёсткая cross-chat/PII изоляция (двойная защита: запись + отбор).
* **SOUL-07.3** — A/B версий библиотеки (`library_version`) и честное
  «почему выбраны именно эти примеры»; различаются владелец добавил вручную,
  бот предложил, проверенный успешный ответ.

Политика отбора живёт в документе `humor.selection` (bot_settings + chat
override) — второго config service нет.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

#: Ось A/B и версия заводской подборки.
STARTER_LIBRARY_VERSION = "starter-1"
DEFAULT_LIBRARY_VERSION = "v1"

SAMPLE_SOURCE_KINDS: tuple[str, ...] = (
    "owner_manual", "bot_suggested", "verified_success",
)
SAMPLE_STATUSES: tuple[str, ...] = ("active", "archived")
SAMPLE_SCOPES: tuple[str, ...] = ("global", "chat")
#: ADD-SAMPLES-UX §1: приёмы Humor Craft — основание миграции «Юмор».
HUMOR_CRAFT_TECHNIQUES: tuple[str, ...] = (
    "absurd_escalation", "literalism", "deadpan", "bureaucratic_logic",
    "unexpected_analogy",
)
SAMPLE_TECHNIQUES: tuple[str, ...] = HUMOR_CRAFT_TECHNIQUES + (
    "other",
    # ADD-EXP §3.3: набор регистра речи (off/occasional/frequent) — своя
    # техника, жёстко изолированная от humor-пути отбора.
    "expression_register",
)
MAX_RUDENESS = 3

# ── ADD-SAMPLES-UX §1: три реальные категории + явный режим мата ────────────
#: Ровно три категории записи (SU-CAT.ENTRY). ``legacy`` — служебное значение
#: миграции для неоднозначных строк (`technique='other'`): владелец
#: переклассифицирует сам, отбор не угадывает за него (SU-CAT.MIGRATE).
SAMPLE_CATEGORIES: tuple[str, ...] = ("general", "humor", "mat")
SAMPLE_CATEGORY_LABELS: dict[str, str] = {
    "general": "Общие", "humor": "Юмор", "mat": "Мат", "legacy": "Legacy",
}
SAMPLE_CATEGORY_STORAGE: tuple[str, ...] = SAMPLE_CATEGORIES + ("legacy",)
#: Явное поле режима для категории «Мат» (не теги; SU-CAT.MAT).
EXPRESSION_SAMPLE_MODES: tuple[str, ...] = ("off", "occasional", "frequent")
#: Технический бюджет §3.2: строк на режим (совпадает с
#: ``mca_expression.EXPRESSION_EXAMPLES_MAX_ITEMS``; импорт не нужен, чтобы не
#: заводить цикл). Отбор НЕ обрывается на этом числе молча: резолвер считает
#: все подходящие строки и отдаёт числа в ``stats`` (ASAP3 §2, #13).
EXPRESSION_RESOLVE_MAX_ITEMS = 4

#: Технические поля записи (design §2.3: «ровно требуемые источником +
#: технические»): ревизия, дедуп сидов, учёт применений для recency/penalty.
TECHNICAL_FIELDS: tuple[str, ...] = (
    "seed_key", "revision", "sensitivity_flags", "uses_count", "last_used_at",
    "approved_at", "created_at", "updated_at", "created_by", "updated_by",
)

# ── DDL (единственная таблица; v37 = категории/режим/tombstone/override) ────
SCHEMA_VERSION_HUMOR_SAMPLES = 37

SAMPLES_DDL = (
    "CREATE TABLE IF NOT EXISTS humor_samples ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "seed_key TEXT, "
    "input_text TEXT NOT NULL, "
    "reply_text TEXT NOT NULL, "
    "technique TEXT, "
    "context_note TEXT, "
    "language TEXT NOT NULL DEFAULT 'ru', "
    "tags TEXT, "
    "rudeness_level INTEGER, "
    "author_user_id INTEGER, "
    "source_kind TEXT NOT NULL CHECK (source_kind IN "
    "('owner_manual','bot_suggested','verified_success')), "
    "scope TEXT NOT NULL CHECK (scope IN ('global','chat')), "
    "chat_id INTEGER, "
    "owner_approved INTEGER NOT NULL DEFAULT 0, "
    "status TEXT NOT NULL DEFAULT 'active' CHECK (status IN "
    "('active','archived')), "
    "library_version TEXT NOT NULL DEFAULT 'v1', "
    "revision INTEGER NOT NULL DEFAULT 1, "
    "sensitivity_flags TEXT, "
    "uses_count INTEGER NOT NULL DEFAULT 0, "
    "last_used_at INTEGER, "
    "approved_at INTEGER, "
    "created_at INTEGER NOT NULL, "
    "updated_at INTEGER NOT NULL, "
    "created_by TEXT, "
    "updated_by TEXT, "
    # ADD-SAMPLES-UX §1/§3: категория (general/humor/mat; legacy = только
    # миграция, владелец переклассифицирует), явный режим мата, постоянный
    # tombstone по seed_key и метка владельческой правки.
    "category TEXT NOT NULL DEFAULT 'legacy', "
    "expression_mode TEXT, "
    "tombstone INTEGER NOT NULL DEFAULT 0, "
    "tombstone_at INTEGER, "
    "owner_modified INTEGER NOT NULL DEFAULT 0, "
    "owner_modified_at INTEGER, "
    "CHECK (scope <> 'chat' OR chat_id IS NOT NULL))"
)

SAMPLES_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_humor_samples_seed "
    "ON humor_samples(seed_key) WHERE seed_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_humor_samples_pick "
    "ON humor_samples(status, scope, chat_id, owner_approved)",
    "CREATE INDEX IF NOT EXISTS idx_humor_samples_technique "
    "ON humor_samples(technique)",
    "CREATE INDEX IF NOT EXISTS idx_humor_samples_version "
    "ON humor_samples(library_version, status)",
    "CREATE INDEX IF NOT EXISTS idx_humor_samples_category "
    "ON humor_samples(category, status, tombstone)",
)

#: v37 (ADD-SAMPLES-UX §1/§3): аддитивные колонки для существующих БД
#: (SQLite ALTER TABLE ADD COLUMN; повтор guardируется по `table_info`).
SAMPLES_V37_ADD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("category",
     "ALTER TABLE humor_samples ADD COLUMN category TEXT NOT NULL "
     "DEFAULT 'legacy'"),
    ("expression_mode",
     "ALTER TABLE humor_samples ADD COLUMN expression_mode TEXT"),
    ("tombstone",
     "ALTER TABLE humor_samples ADD COLUMN tombstone INTEGER NOT NULL "
     "DEFAULT 0"),
    ("tombstone_at",
     "ALTER TABLE humor_samples ADD COLUMN tombstone_at INTEGER"),
    ("owner_modified",
     "ALTER TABLE humor_samples ADD COLUMN owner_modified INTEGER NOT NULL "
     "DEFAULT 0"),
    ("owner_modified_at",
     "ALTER TABLE humor_samples ADD COLUMN owner_modified_at INTEGER"),
)

_COLS = (
    "seed_key", "input_text", "reply_text", "technique", "context_note",
    "language", "tags", "rudeness_level", "author_user_id", "source_kind",
    "scope", "chat_id", "owner_approved", "status", "library_version",
    "revision", "sensitivity_flags", "uses_count", "last_used_at",
    "approved_at", "created_at", "updated_at", "created_by", "updated_by",
    "category", "expression_mode", "tombstone", "tombstone_at",
    "owner_modified", "owner_modified_at",
)

# ── Политика отбора `humor.selection` ──────────────────────────────────────
SELECTION_DOC_KEY = "humor.selection"
SELECTION_DOC_CATEGORY = "content"

#: Границы политики (bounded; SOUL-15.7 «не пихать библиотеку целиком»).
POLICY_LIMITS: dict[str, tuple[float, float]] = {
    "max_items": (1, 3),
    "max_tokens": (40, 700),
    "diversity_min_distance": (0.0, 0.9),
    "recency_penalty": (0.0, 0.9),
    "max_per_technique": (1, 2),
    "min_relevance": (0.0, 0.9),
    "ab_weight": (0.05, 0.95),
}

DEFAULT_POLICY: dict[str, Any] = {
    "enabled": True,
    "max_items": 3,
    "max_tokens": 320,
    "diversity_min_distance": 0.34,
    "recency_penalty": 0.25,
    "max_per_technique": 1,
    "min_relevance": 0.0,
    "ab_enabled": False,
    "ab_versions": ["v1", "v2"],
    "ab_weight": 0.5,
}

#: Блок few-shot (шаблон; реестр `humor.few_shot.block`).
HUMOR_FEW_SHOT_OPEN = (
    "<Examples>\n"
    "Примеры ниже задают механизм мышления, а не готовые фразы: не копируй "
    "лексику, имена и детали дословно и не переноси чужие реалии в этот чат."
)
HUMOR_FEW_SHOT_LINE = "Вход: {input}\nОтвет: {reply}"
HUMOR_FEW_SHOT_CLOSE = "</Examples>"
#: Единая заводская редакция рамки слоя (регистрируется как один блок
#: `humor.few_shot.block`: Factory Default/диффы/откат видят весь шаблон).
HUMOR_FEW_SHOT_TEMPLATE = "\n".join(
    (HUMOR_FEW_SHOT_OPEN, HUMOR_FEW_SHOT_LINE, HUMOR_FEW_SHOT_CLOSE))
MAX_TOTAL_CHARS = 3000

# ── Защита от утечек/PII (SOUL-07.2) ───────────────────────────────────────
_MENTION_RE = re.compile(r"(^|\s)@[A-Za-z0-9_]{3,}")
_TG_LINK_RE = re.compile(r"tg://[^\s\"']+")
_LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{6,}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")


def scan_sensitivity(*parts: str) -> tuple[str, ...]:
    """Маркеры персональных/чужих данных (детерминированно, без LLM)."""
    text = " ".join(str(p or "") for p in parts)
    flags: list[str] = []
    if _MENTION_RE.search(text):
        flags.append("mention")
    if _TG_LINK_RE.search(text):
        flags.append("tg_link")
    if _LONG_DIGITS_RE.search(text):
        flags.append("long_digits")
    if _EMAIL_RE.search(text):
        flags.append("email")
    if _PHONE_RE.search(text):
        flags.append("phone")
    return tuple(flags)


# ═══════════════════════════════════════════════════════════════════════════
# Заводская подборка: 18 оригинальных примеров, разные по композиции
# (неодобренные черновики: owner_approved=False, source_kind=bot_suggested)
# ═══════════════════════════════════════════════════════════════════════════

STARTER_SAMPLES: tuple[dict, ...] = (
    dict(seed_key="starter-01", technique="bureaucratic_logic",
         rudeness_level=1, tags=["быт", "процедура"],
         input_text="Опять забыл выключить свет в подъезде",
         reply_text="Это не забывчивость, а несогласованная заявка: ресурс "
                    "израсходован, заявителя нет, акт не составлен. По "
                    "регламенту подъезд теперь проходит по статье "
                    "«бесхозное освещение» и до конца месяца платит сам за "
                    "себя",
         context_note="Бытовая жалоба без адресата: перенос в процедуру."),
    dict(seed_key="starter-02", technique="absurd_escalation",
         rudeness_level=2, tags=["нарастание", "детали"],
         input_text="Да я просто чайник поставил",
         reply_text="Начали с чайника, закончим аудитом кухни. Сначала он "
                    "свистит, потом ты начинаешь ему отвечать, потом "
                    "появляется расписание дежурств, а к четвергу чайник "
                    "уже требует паспорт и прописку. И самое подлое — "
                    "формально он прав",
         context_note="Эскалация от мелкого действия к системе правил."),
    dict(seed_key="starter-03", technique="literalism",
         rudeness_level=0, tags=["оговорка"],
         input_text="У меня голова кругом идёт",
         reply_text="Тогда у тебя проблема с креплением: круг вращается, а "
                    "список задач продолжает расти. Нужен либо подшипник, "
                    "либо повод остановиться",
         context_note="Фразеологизм понят как техническое описание."),
    dict(seed_key="starter-04", technique="deadpan",
         rudeness_level=1, tags=["сухо", "одна-две-фразы"],
         input_text="Я всё воскресенье разбирал шкаф",
         reply_text="Разумно. Шкаф предупредил заранее, что иначе разберёт "
                    "тебя",
         context_note="Нелепое утверждение как обыденный факт, без эмоций."),
    dict(seed_key="starter-05", technique="unexpected_analogy",
         rudeness_level=1, tags=["аналогия", "детали"],
         input_text="Тимлид снова перенёс сроки",
         reply_text="Это как тектоника плит: кажется, что ничего не "
                    "происходит, а потом выясняется, что всё уже "
                    "сместилось на три недели. И виноват, конечно, "
                    "рельеф",
         context_note="Аналогия из отдалённой области с внутренней логикой."),
    dict(seed_key="starter-06", technique="bureaucratic_logic",
         rudeness_level=2, tags=["семья", "регламент"],
         input_text="Кот опять разбудил в четыре утра",
         reply_text="Он не будильник, он надзорная инстанция. Четыре утра — "
                    "контрольная проверка: если поднимешься, значит живой, "
                    "значит кормить можно и дальше",
         context_note="Домашнее животное как орган контроля."),
    dict(seed_key="starter-07", technique="absurd_escalation",
         rudeness_level=2, tags=["техника", "нарастание"],
         input_text="Ноутбук стал громко шуметь",
         reply_text="Это уже не вентилятор, а переговоры. Сначала он гудит "
                    "для порядка, потом начинает обсуждение нагрузки, к "
                    "вечеру излагает претензии к твоим вкладкам. Через "
                    "неделю потребует своего человека в переговорах",
         context_note="Эскалация предмета до субъекта с требованиями."),
    dict(seed_key="starter-08", technique="literalism",
         rudeness_level=1, tags=["оговорка", "офис"],
         input_text="Я просто не могу закрыть этот проект",
         reply_text="Дверь не заедает, закрытие — это статус. Возьми "
                    "протокол, отметь три достижения и объяви проект "
                    "закрытым официально, а не эмоционально",
         context_note="«Закрыть» понято буквально."),
    dict(seed_key="starter-09", technique="deadpan",
         rudeness_level=0, tags=["сухо"],
         input_text="Знакомый говорит, что выиграл у казино",
         reply_text="Казино тоже участвует в этой истории, но почему-то "
                    "молчит",
         context_note="Короткая сухая реплика без объяснений."),
    dict(seed_key="starter-10", technique="unexpected_analogy",
         rudeness_level=2, tags=["аналогия", "быт"],
         input_text="Сосед сверлит стену вторые выходные",
         reply_text="Акустическая терапия по расписанию: сначала локально, "
                    "потом резонанс на весь дом, а к концу дня "
                    "формируется устойчивый вкус к шуму. Клиническая "
                    "картина обошлась соседу дешевле, чем тебе",
         context_note="Аналогия из медицины с конкретной механикой."),
    dict(seed_key="starter-11", technique="bureaucratic_logic",
         rudeness_level=1, tags=["работа", "смета"],
         input_text="Планёрка закончилась ничем",
         reply_text="Нет, результат есть: подтверждено отсутствие "
                    "лишних решений, освоено сорок минут бюджета, составлен "
                    "устный отчёт о состоянии неопределённости",
         context_note="Пустое событие как оформленный результат."),
    dict(seed_key="starter-12", technique="absurd_escalation",
         rudeness_level=3, tags=["нарастание", "грубо"],
         input_text="Да я просто забыл про эту встречу",
         reply_text="Сначала это было опоздание, потом — «не пришёл», потом "
                    "— «мы его не звали», а к обеду уже существует легенда "
                    "о мальчике, который строил календарь и пропал в нём. "
                    "Вся группа будет рассказывать её новым сотрудникам",
         context_note="Эскалация мелкого промаха до фольклора."),
    dict(seed_key="starter-13", technique="literalism",
         rudeness_level=2, tags=["оговорка", "цифры"],
         input_text="У нас в отделе три с половиной человека",
         reply_text="Половина человека — это, скорее всего, стажёр на "
                    "четверть ставки и вечная надежда на вторую половину. "
                    "Отчёт при этом закрывается целой головой",
         context_note="Дробное число сотрудников понято буквально."),
    dict(seed_key="starter-14", technique="other",
         rudeness_level=0, tags=["серьёзно", "без-шутки"],
         input_text="У меня нет сил что-то делать, всё валится",
         reply_text="Тогда сейчас не юмор, а механика: выбери одну задачу, "
                    "которая не сломает всё остальное, если её отложить, и "
                    "отложи именно её. Остальное подождёт, оно не "
                    "обидится",
         context_note="Серьёзный контекст: комический приём сознательно не "
                      "применяется."),
    dict(seed_key="starter-15", technique="other",
         rudeness_level=0, tags=["серьёзно", "техника"],
         input_text="Почему у меня тест падает только в CI?",
         reply_text="Обычно расходятся окружение и время. Сначала проверь, "
                    "что версия зависимости в CI та же, и покажи реальный "
                    "лог падения — без него гадание дороже продукта",
         context_note="Технический вопрос: суть важнее формы."),
    dict(seed_key="starter-16", technique="deadpan",
         rudeness_level=1, tags=["сухо", "спорт"],
         input_text="Я вчера пробежал десять километров",
         reply_text="Инвентаризация показала: есть десять километров и "
                    "нет двух дней жизни. Сделка закрыта без выгоды",
         context_note="Сухой вывод вместо похвалы."),
    dict(seed_key="starter-17", technique="unexpected_analogy",
         rudeness_level=1, tags=["аналогия", "эмоции"],
         input_text="Меня раздражает, что всё делают без меня",
         reply_text="Это как архитектура без обратной связи: пока всё "
                    "держится, никто не замечает, что несущих стен нет. "
                    "Раздражение здесь — первый датчик, а не характер",
         context_note="Аналогия объясняет эмоцию, а не обесценивает."),
    dict(seed_key="starter-18", technique="bureaucratic_logic",
         rudeness_level=2, tags=["хобби", "налог"],
         input_text="Купил ещё одну гитару, жена не в курсе",
         reply_text="Это ввоз без декларации. У любой гитары есть "
                    "таможенная стоимость, счёт за струны и обязательство "
                    "играть хотя бы раз в квартал. Проверка явится "
                    "вместе с уборкой",
         context_note="Покупка как импорт с обязательствами."),
)

# ═══════════════════════════════════════════════════════════════════════════
# ADD-EXP §3.1/§3.3 — заводской набор регистра речи (12 черновиков)
# 3 режима × 4 бытовые темы; тег режима — в `tags`, тема — в `context_note`.
# `owner_approved=False` (черновики: в runtime не идут, `not_owner_approved`);
# `source_kind='bot_suggested'`, `scope='global'` — как у humor-сидов.
# ═══════════════════════════════════════════════════════════════════════════

EXPRESSION_STARTER_LIBRARY_VERSION = "expr-starter-1"

#: Тег режима для отбора (`tags` строки библиотеки).
EXPRESSION_MODE_TAGS: dict[str, str] = {
    "off": "mode:off", "occasional": "mode:occasional",
    "frequent": "mode:frequent",
}

_EXPRESSION_THEMES: tuple[str, ...] = (
    "дружеский стёб", "спор", "короткий ответ", "быт",
)


def _expression_seed(mode: str, theme: str, user_line: str,
                     reply: str) -> dict:
    slug = {"дружеский стёб": "banter", "спор": "spor",
            "короткий ответ": "short", "быт": "byt"}[theme]
    return dict(
        seed_key=f"expr-{mode}-{slug}", technique="expression_register",
        # ADD-SAMPLES-UX §1: категория «Мат» и ЯВНОЕ поле режима (теги
        # остаются для совместимости, но режим читается из поля, не из тега).
        category="mat", expression_mode=mode,
        tags=[EXPRESSION_MODE_TAGS[mode], "expression"],
        input_text=user_line, reply_text=reply,
        context_note=theme)


EXPRESSION_STARTER_SAMPLES: tuple[dict, ...] = (
    # off
    _expression_seed("off", "дружеский стёб",
                     "Ну ты и выдал вчера с этим докладом",
                     "Выдал, признаю. Зато никто не уснул."),
    _expression_seed("off", "спор",
                     "Твой вариант вообще не работает",
                     "Он не работает у того, кто ставит его криво. "
                     "У меня крутится, и стабильно."),
    _expression_seed("off", "короткий ответ",
                     "Пойдёшь завтра?", "Пойду."),
    _expression_seed("off", "быт",
                     "Интернет опять отвалился",
                     "Классика. Перезагрузи роутер, обычно помогает."),
    # occasional
    _expression_seed("occasional", "дружеский стёб",
                     "Ну ты и выдал вчера с этим докладом",
                     "Выдал, признаю. Зато никто не уснул, бля."),
    _expression_seed("occasional", "спор",
                     "Твой вариант вообще не работает",
                     "Он не работает у того, кто ставит его криво. "
                     "У меня крутится, пиздец как стабильно."),
    _expression_seed("occasional", "короткий ответ",
                     "Пойдёшь завтра?", "Пойду, хули."),
    _expression_seed("occasional", "быт",
                     "Интернет опять отвалился",
                     "Классика, бля. Перезагрузи роутер, обычно помогает."),
    # frequent
    _expression_seed("frequent", "дружеский стёб",
                     "Ну ты и выдал вчера с этим докладом",
                     "Ага, выдал. Хуёво выдал, зато никто не уснул."),
    _expression_seed("frequent", "спор",
                     "Твой вариант вообще не работает",
                     "Он не работает у того, кто ставит его криво, вот и "
                     "весь хуй. У меня крутится, пиздец как стабильно."),
    _expression_seed("frequent", "короткий ответ",
                     "Пойдёшь завтра?", "Пойду, хули. Куда я денусь."),
    _expression_seed("frequent", "быт",
                     "Интернет опять отвалился",
                     "Охуенная классика. Перезагрузи роутер, помогает "
                     "через раз, но хоть что-то."),
)


# ═══════════════════════════════════════════════════════════════════════════
# ADD-SAMPLES-UX §3: заводской набор в коде — ЭТАЛОН для просмотра/явного
# восстановления. Действующий источник истины для правок — БД.
# ═══════════════════════════════════════════════════════════════════════════

_FACTORY_SEED_ACTORS: frozenset[str] = frozenset({
    "starter_seed", "expression_seed",
})

#: Поля, чья владельческая правка помечает заводскую карточку
#: «Изменено владельцем» (одобрение/архив — отдельные состояния, не правка).
OWNER_MODIFIED_FIELDS: frozenset[str] = frozenset({
    "input_text", "reply_text", "technique", "context_note", "language",
    "tags", "rudeness_level", "category", "expression_mode", "scope",
})


def factory_seed_index() -> dict[str, dict]:
    """`seed_key` → заводское определение из текущего кода (эталон)."""
    index: dict[str, dict] = {}
    for sample in STARTER_SAMPLES:
        key = str(sample.get("seed_key") or "")
        if key:
            index[key] = sample
    for sample in EXPRESSION_STARTER_SAMPLES:
        key = str(sample.get("seed_key") or "")
        if key:
            index[key] = sample
    return index


def factory_seed_for(seed_key: str) -> dict | None:
    """Заводское определение по seed_key (None — набора нет в этой версии)."""
    return factory_seed_index().get(str(seed_key or "")) or None


def _factory_fields(sample: Mapping[str, Any]) -> dict:
    """Поля заводской редакции (как их посеял бы seed; без служебных).

    Категория — по правилу СИДА (starter → humor; expression → mat), ровно
    как в `seed_starter_samples`/`seed_expression_samples`, иначе честный
    diff-vs-factory помечал бы нетронутые сиды как «изменённые владельцем».
    """
    fields = {k: sample.get(k) for k in (
        "seed_key", "input_text", "reply_text", "technique", "context_note",
        "tags", "rudeness_level", "category", "expression_mode") if k in sample}
    if "category" not in fields:
        fields["category"] = (
            "mat" if fields.get("technique") == "expression_register"
            else "humor")
    return fields


# ═══════════════════════════════════════════════════════════════════════════
# Доступ к БД (единственный контур — существующий lore/experience DB)
# ═══════════════════════════════════════════════════════════════════════════


def get_db():
    """Активная БД памяти (или None — честная деградация)."""
    try:
        from services import lore_runtime
        return lore_runtime.get_lore_db()
    except Exception:
        logger.warning("[humor-samples] db unavailable", exc_info=True)
        return None


def _db_ready(db) -> bool:
    return db is not None and hasattr(db, "db") and hasattr(
        db, "write_transaction")


async def table_ready(db) -> bool:
    """Таблица существует (иначе честный `schema_absent`, а не пустая выдача)."""
    if not _db_ready(db):
        return False
    try:
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='humor_samples'")
        return await cursor.fetchone() is not None
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Записи: нормализация и проверки
# ═══════════════════════════════════════════════════════════════════════════


def _now(ts: int | float | None = None) -> int:
    return int(ts if ts is not None else time.time())


def _tags_json(tags: Any) -> str | None:
    if isinstance(tags, str):
        items = [t.strip() for t in re.split(r"[,\n]", tags) if t.strip()]
    elif isinstance(tags, (list, tuple, set)):
        items = [str(t).strip() for t in tags if str(t).strip()]
    else:
        items = []
    items = [t[:32] for t in items][:12]
    return json.dumps(items, ensure_ascii=False) if items else None


def parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(t) for t in raw]
    try:
        parsed = json.loads(str(raw or "[]"))
    except Exception:
        return []
    return [str(t) for t in parsed] if isinstance(parsed, list) else []


def _clip_field(name: str, value: Any, cap: int) -> str:
    """Обрезка поля примера до cap с честным WARN (ASAP3 §2).

    Владелец может вставить текст длиннее технического потолка; сохранение
    раньше резало его молча. R17-safe: в лог идут только имя поля и числа.
    """
    text = str(value or "").strip()
    if len(text) <= cap:
        return text
    logger.warning("[humor-samples] field clipped | field=%s | chars=%d -> %d",
                   name, len(text), cap)
    return text[:cap]


def normalize_fields(fields: Mapping[str, Any]) -> dict:
    """Нормализовать входные поля (fail-closed по закрытым наборам)."""
    out: dict[str, Any] = {}
    if "input_text" in fields:
        out["input_text"] = _clip_field(
            "input_text", fields.get("input_text"), 2000)
    if "reply_text" in fields:
        out["reply_text"] = _clip_field(
            "reply_text", fields.get("reply_text"), 4000)
    if "technique" in fields:
        technique = str(fields.get("technique") or "other")
        out["technique"] = technique if technique in SAMPLE_TECHNIQUES else "other"
    if "context_note" in fields:
        out["context_note"] = str(fields.get("context_note") or "").strip()[:600]
    if "language" in fields:
        out["language"] = (str(fields.get("language") or "ru").strip()[:12]
                           or "ru")
    if "tags" in fields:
        out["tags"] = _tags_json(fields.get("tags"))
    if "rudeness_level" in fields:
        try:
            level = int(fields.get("rudeness_level") or 0)
        except (TypeError, ValueError):
            level = 0
        out["rudeness_level"] = max(0, min(MAX_RUDENESS, level))
    if "source_kind" in fields:
        kind = str(fields.get("source_kind") or "owner_manual")
        out["source_kind"] = (kind if kind in SAMPLE_SOURCE_KINDS
                              else "owner_manual")
    if "scope" in fields:
        scope = str(fields.get("scope") or "global")
        out["scope"] = scope if scope in SAMPLE_SCOPES else "global"
    if "chat_id" in fields:
        try:
            out["chat_id"] = (int(fields.get("chat_id"))
                              if fields.get("chat_id") is not None else None)
        except (TypeError, ValueError):
            out["chat_id"] = None
    if "owner_approved" in fields:
        out["owner_approved"] = 1 if fields.get("owner_approved") else 0
    if "status" in fields:
        status = str(fields.get("status") or "active")
        out["status"] = status if status in SAMPLE_STATUSES else "active"
    if "library_version" in fields:
        out["library_version"] = (str(fields.get("library_version")
                                      or DEFAULT_LIBRARY_VERSION).strip()[:32]
                                  or DEFAULT_LIBRARY_VERSION)
    if "author_user_id" in fields:
        try:
            out["author_user_id"] = (int(fields.get("author_user_id"))
                                     if fields.get("author_user_id")
                                     is not None else None)
        except (TypeError, ValueError):
            out["author_user_id"] = None
    if "seed_key" in fields:
        seed_key = str(fields.get("seed_key") or "").strip()[:64]
        out["seed_key"] = seed_key or None
    # ADD-SAMPLES-UX §1: категория и явный режим мата (закрытые наборы).
    # Пустое значение = «не передавалось» (ключ убирается); непустое
    # невалидное → None (fail-closed: вызывающий обязан отклонить).
    if "category" in fields:
        category = str(fields.get("category") or "").strip().lower()
        if not category:
            out.pop("category", None)
        # 'legacy' через запись не ставится — только миграция.
        else:
            out["category"] = (category if category in SAMPLE_CATEGORIES
                               else None)
    if "expression_mode" in fields:
        mode = str(fields.get("expression_mode") or "").strip().lower()
        if not mode:
            out.pop("expression_mode", None)
        else:
            out["expression_mode"] = (mode if mode in EXPRESSION_SAMPLE_MODES
                                      else None)
    return out


def derive_category(technique: Any) -> str:
    """Категория новой записи по приёму (только для НОВЫХ записей).

    ``expression_register`` → mat; приёмы Humor Craft → humor; остальное →
    general (владелец пишет обычный пример; UI всегда передаёт категорию
    явно). Для МИГРАЦИИ существующих строк это правило не применяется —
    там неоднозначное `other` остаётся `legacy` (SU-CAT.MIGRATE).
    """
    technique = str(technique or "")
    if technique == "expression_register":
        return "mat"
    if technique in HUMOR_CRAFT_TECHNIQUES:
        return "humor"
    return "general"


def validate_write(fields: Mapping[str, Any]) -> tuple[bool, str]:
    """Проверки записи (fail-closed): обязательные поля, scope, утечки."""
    if not str(fields.get("input_text") or "").strip():
        return False, "empty_input_text"
    if not str(fields.get("reply_text") or "").strip():
        return False, "empty_reply_text"
    if str(fields.get("scope") or "global") == "chat" \
            and fields.get("chat_id") is None:
        return False, "chat_scope_without_chat"
    if str(fields.get("source_kind") or "") not in SAMPLE_SOURCE_KINDS:
        return False, "unknown_source_kind"
    if str(fields.get("scope") or "") not in SAMPLE_SCOPES:
        return False, "unknown_scope"
    # ADD-SAMPLES-UX §1: категория сквозная и валидируется сервером.
    category = str(fields.get("category") or "")
    if category and category not in SAMPLE_CATEGORY_STORAGE:
        return False, "unknown_category"
    mode = fields.get("expression_mode")
    if mode is not None and str(mode) not in EXPRESSION_SAMPLE_MODES:
        return False, "unknown_expression_mode"
    return True, ""


def record_view(row: Mapping[str, Any]) -> dict:
    """Карточка записи для UI/API (маскирование не нужно: это свои данные)."""
    approved = bool(row.get("owner_approved"))
    status = str(row.get("status") or "active")
    seed_key = str(row.get("seed_key") or "")
    owner_modified = bool(row.get("owner_modified"))
    # ADD-SAMPLES-UX §4.1: происхождение карточки одной меткой
    # («Заводской / Мой / Изменено владельцем»).
    if not seed_key:
        origin = "owner"
    elif owner_modified:
        origin = "modified"
    else:
        origin = "factory"
    category = str(row.get("category") or "legacy")
    mode = row.get("expression_mode")
    return {
        "id": int(row.get("id") or 0),
        "input_text": str(row.get("input_text") or ""),
        "reply_text": str(row.get("reply_text") or ""),
        "technique": str(row.get("technique") or "other"),
        "context_note": str(row.get("context_note") or ""),
        "language": str(row.get("language") or "ru"),
        "tags": parse_tags(row.get("tags")),
        "rudeness_level": int(row.get("rudeness_level") or 0),
        "source_kind": str(row.get("source_kind") or "owner_manual"),
        "scope": str(row.get("scope") or "global"),
        "chat_id": row.get("chat_id"),
        "owner_approved": approved,
        # SOUL-07.1: черновики НЕ выдаются за одобренные владельцем.
        "approval": "approved" if approved else "proposed",
        "status": status,
        "library_version": str(row.get("library_version")
                               or DEFAULT_LIBRARY_VERSION),
        "revision": int(row.get("revision") or 1),
        "uses_count": int(row.get("uses_count") or 0),
        "last_used_at": row.get("last_used_at"),
        "sensitivity_flags": _flags(row.get("sensitivity_flags")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "created_by": row.get("created_by"),
        "updated_by": row.get("updated_by"),
        "seed_key": row.get("seed_key"),
        # ADD-SAMPLES-UX §1/§3/§4: категория, явный режим, происхождение,
        # tombstone (удалённое владельцем не исчезает молча).
        "category": category,
        "category_label": SAMPLE_CATEGORY_LABELS.get(category, category),
        "expression_mode": str(mode) if mode in EXPRESSION_SAMPLE_MODES
        else None,
        "origin": origin,
        "origin_label": {"factory": "Заводской", "owner": "Мой",
                         "modified": "Изменено владельцем"}[origin],
        "owner_modified": owner_modified,
        "owner_modified_at": row.get("owner_modified_at"),
        "tombstone": bool(row.get("tombstone")),
        "tombstone_at": row.get("tombstone_at"),
        "factory_in_code": bool(seed_key) and seed_key in factory_seed_index(),
    }


def _flags(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw]
    try:
        parsed = json.loads(str(raw or "[]"))
    except Exception:
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


# ═══════════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════════


async def list_samples(db=None, *, chat_id: int | None = None,
                       technique: str | None = None,
                       status: str | None = None,
                       scope: str | None = None,
                       library_version: str | None = None,
                       category: str | None = None,
                       include_tombstoned: bool = False,
                       query: str = "",
                       limit: int = 200) -> list[dict]:
    """Карточки библиотеки: chat-scope виден только своему чату (изоляция).

    ADD-SAMPLES-UX: tombstone-строки (удалённые владельцем заводские) по
    умолчанию скрыты из всех выдач — они не «исчезли молча», их состояние
    отдаёт ``list_tombstoned``; категория фильтруется по явному полю.
    """
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return []
    where: list[str] = []
    args: list[Any] = []
    if not include_tombstoned:
        where.append("tombstone = 0")
    if chat_id is not None:
        where.append("((scope = 'global') OR (scope = 'chat' AND chat_id = ?))")
        args.append(int(chat_id))
    else:
        where.append("scope = 'global'")
    if technique:
        where.append("technique = ?")
        args.append(str(technique))
    if status:
        where.append("status = ?")
        args.append(str(status))
    if scope:
        where.append("scope = ?")
        args.append(str(scope))
    if library_version:
        where.append("library_version = ?")
        args.append(str(library_version))
    if category:
        # фильтр по категории — по явному полю записи (не по тегам/приёму).
        where.append("category = ?")
        args.append(str(category))
    sql = "SELECT * FROM humor_samples"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id LIMIT ?"
    args.append(max(1, min(int(limit or 200), 500)))
    try:
        cursor = await db.db.execute(sql, tuple(args))
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        logger.warning("[humor-samples] list failed", exc_info=True)
        return []
    term = str(query or "").strip().casefold()
    if term:
        rows = [r for r in rows
                if term in str(r.get("input_text") or "").casefold()
                or term in str(r.get("reply_text") or "").casefold()
                or any(term in t.casefold() for t in parse_tags(r.get("tags")))]
    return [record_view(r) for r in rows]


async def list_tombstoned(db=None, *, chat_id: int | None = None,
                          limit: int = 200) -> list[dict]:
    """Удалённые владельцем заводские карточки (tombstone по seed_key).

    SU-FACT.SEMANTICS: после удаления состояние показывается, а не молчит;
    владельцу доступно явное «Восстановить исходный».
    """
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return []
    where = ["tombstone = 1", "seed_key IS NOT NULL"]
    args: list[Any] = []
    if chat_id is not None:
        where.append("((scope = 'global') OR (scope = 'chat' AND chat_id = ?))")
        args.append(int(chat_id))
    try:
        cursor = await db.db.execute(
            "SELECT * FROM humor_samples WHERE " + " AND ".join(where)
            + " ORDER BY id LIMIT ?", tuple(args + [max(1, min(int(limit), 500))]))
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        logger.warning("[humor-samples] tombstoned list failed", exc_info=True)
        return []
    return [record_view(r) for r in rows]


async def get_sample(db=None, sample_id: int = 0) -> dict | None:
    """Карточка по id (включая tombstone — restore/гвардам он виден)."""
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return None
    try:
        cursor = await db.db.execute(
            "SELECT * FROM humor_samples WHERE id = ?", (int(sample_id),))
        row = await cursor.fetchone()
    except Exception:
        logger.warning("[humor-samples] get failed", exc_info=True)
        return None
    return record_view(dict(row)) if row is not None else None


async def _insert(db, record: dict, *, op_name: str) -> dict:
    async def _body(conn):
        await conn.execute(
            "INSERT INTO humor_samples (" + ",".join(_COLS) + ") VALUES ("
            + ",".join("?" for _ in _COLS) + ")",
            tuple(record.get(c) for c in _COLS))
        cursor = await conn.execute("SELECT last_insert_rowid() AS id")
        row = await cursor.fetchone()
        return int(row["id"]) if row is not None else 0

    sample_id = await db.write_transaction(_body, op_name=op_name)
    return await get_sample(db, int(sample_id)) or {}


async def create_sample(db=None, *, fields: Mapping[str, Any],
                        actor: str = "") -> tuple[dict | None, str]:
    """Создать пример. Возврат ``(карточка|None, reason)``."""
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return None, "db_unavailable"
    data = {**{"source_kind": "owner_manual", "scope": "global"},
            **normalize_fields(fields)}
    # Невалидная категория/режим (непустые) отклоняются — без угадывания.
    for guarded in ("category", "expression_mode"):
        if guarded in data and data[guarded] is None:
            return None, "unknown_" + guarded
    # Категория новой записи: явная или по приёму (UI всегда передаёт явно).
    if not data.get("category"):
        data["category"] = derive_category(
            fields.get("technique", data.get("technique")))
    ok, reason = validate_write(data)
    if not ok:
        return None, reason
    flags = scan_sensitivity(data.get("input_text"), data.get("reply_text"),
                             data.get("context_note"))
    if flags:
        # SOUL-07.2: утечка/PII не попадает в библиотеку.
        return None, "sensitive:" + ",".join(flags)
    now = _now()
    record = {**{c: None for c in _COLS}, **data}
    record.update({
        "language": data.get("language") or "ru",
        "scope": data.get("scope") or "global",
        "technique": data.get("technique") or "other",
        "source_kind": data.get("source_kind") or "owner_manual",
        "status": data.get("status") or "active",
        "library_version": data.get("library_version")
        or DEFAULT_LIBRARY_VERSION,
        "category": data.get("category") or "general",
        "tombstone": 0, "owner_modified": 0,
        "revision": 1, "uses_count": 0, "owner_approved": 0,
        "sensitivity_flags": None, "created_at": now, "updated_at": now,
        "created_by": str(actor or ""), "updated_by": str(actor or ""),
    })
    try:
        view = await _insert(db, record, op_name="humor_sample_insert")
    except Exception:
        logger.warning("[humor-samples] insert failed", exc_info=True)
        return None, "write_error"
    return view, ""


async def update_sample(db=None, sample_id: int = 0, *,
                        fields: Mapping[str, Any], actor: str = "",
                        expected_revision: int | None = None
                        ) -> tuple[dict | None, str]:
    """Правка примера (ревизия инкрементируется; optimistic-проверка)."""
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return None, "db_unavailable"
    current = await get_sample(db, sample_id)
    if current is None:
        return None, "not_found"
    if expected_revision is not None \
            and int(expected_revision) != int(current.get("revision") or 1):
        return None, "revision_conflict"
    data = normalize_fields(fields)
    # None в нормализованных category/expression_mode = невалидное значение
    # (fail-closed, без угадывания); отсутствие ключа = «не менять».
    for guarded in ("category", "expression_mode"):
        if guarded in data and data[guarded] is None:
            return None, "unknown_" + guarded
    merged = {**current, **data}
    ok, reason = validate_write(merged)
    if not ok:
        return None, reason
    flags = scan_sensitivity(merged.get("input_text"), merged.get("reply_text"),
                             merged.get("context_note"))
    if flags:
        return None, "sensitive:" + ",".join(flags)
    sets = dict(data)
    sets["revision"] = int(current.get("revision") or 1) + 1
    sets["updated_at"] = _now()
    sets["updated_by"] = str(actor or "")
    # ADD-SAMPLES-UX §3: содержательная правка заводской карточки владельцем
    # помечает её «Изменено владельцем» (+ время). Сид/restore метку не ставят
    # и не снимают чужую историю; метку сбрасывает только явный restore.
    if str(current.get("seed_key") or "") \
            and str(actor or "") not in _FACTORY_SEED_ACTORS \
            and (OWNER_MODIFIED_FIELDS & set(data)):
        sets["owner_modified"] = 1
        sets["owner_modified_at"] = sets["updated_at"]
    if "tags" in sets and isinstance(sets["tags"], list):
        sets["tags"] = _tags_json(sets["tags"])
    if "owner_approved" in sets:
        sets["owner_approved"] = 1 if sets["owner_approved"] else 0
        sets["approved_at"] = _now() if sets["owner_approved"] else None
    if not sets:
        return current, ""

    async def _body(conn):
        columns = ", ".join(f"{c} = ?" for c in sets)
        await conn.execute(
            f"UPDATE humor_samples SET {columns} WHERE id = ?",
            tuple(sets.values()) + (int(sample_id),))
        return True

    try:
        await db.write_transaction(_body, op_name="humor_sample_update")
    except Exception:
        logger.warning("[humor-samples] update failed", exc_info=True)
        return None, "write_error"
    return await get_sample(db, sample_id), ""


async def set_approval(db=None, sample_id: int = 0, *, approved: bool,
                       actor: str = "") -> tuple[dict | None, str]:
    """Отметить пример эталонным («согласовано владельцем») или снять метку."""
    return await update_sample(db, sample_id,
                               fields={"owner_approved": bool(approved)},
                               actor=actor)


async def archive_sample(db=None, sample_id: int = 0, *, archived: bool = True,
                         actor: str = "") -> tuple[dict | None, str]:
    return await update_sample(db, sample_id,
                               fields={"status": "archived" if archived
                                       else "active"},
                               actor=actor)


async def delete_sample(db=None, sample_id: int = 0) -> tuple[bool, str]:
    """Удалить пример (архив — мягкая альтернатива; подтверждается UI).

    ADD-SAMPLES-UX §3 (SU-PERSIST.TOMB): заводская строка (seed_key) не
    стирается физически — ставится постоянный tombstone; отсутствие строки
    НЕ трактуется как разрешение пересоздать её. Владельческие карточки
    (без seed_key) удаляются физически — восстанавливать нечего.
    """
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return False, "db_unavailable"
    current = await get_sample(db, sample_id)
    if current is None:
        return False, "not_found"
    if str(current.get("seed_key") or ""):
        now = _now()

        async def _tomb(conn):
            await conn.execute(
                "UPDATE humor_samples SET tombstone = 1, tombstone_at = ?, "
                "updated_at = ?, updated_by = 'owner_delete' WHERE id = ?",
                (now, now, int(sample_id)))
            return True

        try:
            await db.write_transaction(_tomb, op_name="humor_sample_delete")
        except Exception:
            logger.warning("[humor-samples] tombstone failed", exc_info=True)
            return False, "write_error"
        return True, ""

    async def _body(conn):
        await conn.execute("DELETE FROM humor_samples WHERE id = ?",
                           (int(sample_id),))
        return True

    try:
        await db.write_transaction(_body, op_name="humor_sample_delete")
    except Exception:
        logger.warning("[humor-samples] delete failed", exc_info=True)
        return False, "write_error"
    return True, ""


# ═══════════════════════════════════════════════════════════════════════════
# ADD-SAMPLES-UX §3: явное восстановление заводских редакций
# (только подтверждённое действие; force у сида никогда не resurrection)
# ═══════════════════════════════════════════════════════════════════════════


def _diff_owner_vs_factory(current: Mapping[str, Any]) -> list[dict]:
    """Список отличий владельческой карточки от заводского эталона."""
    sample = factory_seed_for(str(current.get("seed_key") or ""))
    if sample is None:
        return []
    diffs: list[dict] = []
    for field in ("input_text", "reply_text", "technique", "context_note",
                  "rudeness_level"):
        factory_value = sample.get(field)
        if field in ("tags",):
            continue
        current_value = current.get(field)
        if field == "tags":
            factory_value = parse_tags(factory_value)
        if str(current_value or "") != str(factory_value or ""):
            diffs.append({"field": field, "factory": factory_value,
                          "current": current_value})
    if sorted(parse_tags(current.get("tags"))) != \
            sorted(parse_tags(sample.get("tags"))):
        diffs.append({"field": "tags", "factory": parse_tags(
            sample.get("tags")), "current": parse_tags(current.get("tags"))})
    factory_category = _factory_fields(sample).get("category")
    if str(current.get("category") or "") != str(factory_category or ""):
        diffs.append({"field": "category",
                      "factory": factory_category,
                      "current": current.get("category")})
    if str(current.get("expression_mode") or "") != str(
            sample.get("expression_mode") or ""):
        diffs.append({"field": "expression_mode",
                      "factory": sample.get("expression_mode"),
                      "current": current.get("expression_mode")})
    return diffs


async def restore_factory_sample(db=None, sample_id: int = 0, *,
                                 confirm: bool = False,
                                 actor: str = "factory_restore"
                                 ) -> tuple[dict | None, str]:
    """Явно восстановить ОДИН заводской пример (только при confirm=True).

    Без confirm возвращает ``(None, "needs_confirmation")`` — тихого
    восстановления не существует. Восстановление одного примера не трогает
    остальные и не пересоздаёт библиотеку. Tombstone снимается только здесь.
    """
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return None, "db_unavailable"
    if not confirm:
        return None, "needs_confirmation"
    current = await get_sample(db, sample_id)
    if current is None:
        return None, "not_found"
    seed_key = str(current.get("seed_key") or "")
    if not seed_key:
        return None, "not_factory"
    sample = factory_seed_for(seed_key)
    if sample is None:
        # SU-PERSIST.STORE: владельческие данные живут даже когда заводской
        # набор исчез из кода — молча подменять их нельзя.
        return None, "factory_seed_absent"
    fields = _factory_fields(sample)
    fields.update({
        "owner_approved": False,          # заводское = черновик, не эталон
        "status": "active",
        "tombstone": 0,
        "owner_modified": 0,
    })
    sets = normalize_fields(fields)
    sets.update({
        "revision": int(current.get("revision") or 1) + 1,
        "updated_at": _now(),
        "updated_by": str(actor),
        "tombstone": 0,
        "tombstone_at": None,
        "owner_modified": 0,
        "owner_modified_at": None,
    })

    async def _body(conn):
        columns = ", ".join(f"{c} = ?" for c in sets)
        await conn.execute(
            f"UPDATE humor_samples SET {columns} WHERE id = ?",
            tuple(sets.values()) + (int(sample_id),))
        return True

    try:
        await db.write_transaction(_body, op_name="humor_sample_restore")
    except Exception:
        logger.warning("[humor-samples] factory restore failed", exc_info=True)
        return None, "write_error"
    return await get_sample(db, sample_id), ""


def restore_factory_preview_item(current: Mapping[str, Any]) -> dict:
    """Данные экрана сравнения для одной заводской карточки (честный diff)."""
    seed_key = str(current.get("seed_key") or "")
    sample = factory_seed_for(seed_key)
    return {
        "id": int(current.get("id") or 0),
        "seed_key": seed_key,
        "title": str(current.get("input_text") or "")[:80],
        "origin": str(current.get("origin") or "factory"),
        "tombstone": bool(current.get("tombstone")),
        "revision": int(current.get("revision") or 1),
        "owner_modified_at": current.get("owner_modified_at"),
        "factory_in_code": sample is not None,
        "diffs": _diff_owner_vs_factory(current) if sample is not None else [],
    }


async def restore_factory_preview(db=None, *,
                                  chat_id: int | None = None) -> dict:
    """Экран сравнения ПЕРЕД массовым восстановлением: что будет затронуто.

    Затронуты только заводские карточки с владельческой правкой или
    tombstone («Сбросить всё» — никогда не действие по умолчанию).
    """
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return {"available": False, "reason": "db_unavailable",
                "items": []}
    try:
        # REV-SAMPLES-UX b.1: tombstone-заводские карточки тоже затронуты
        # восстановлением — без include_tombstoned проверка tombstone ниже
        # была dead-check, а владелец не видел удалённые строки в diff.
        rows = await list_samples(db, chat_id=chat_id, limit=500,
                                  include_tombstoned=True)
    except Exception:
        logger.warning("[humor-samples] restore preview failed", exc_info=True)
        return {"available": False, "reason": "read_error", "items": []}
    items = []
    for row in rows:
        if not str(row.get("seed_key") or ""):
            continue
        if bool(row.get("tombstone")) or bool(row.get("owner_modified")) \
                or _diff_owner_vs_factory(row):
            items.append(restore_factory_preview_item(row))
    return {"available": True, "reason": "", "items": items,
            "note": ("Восстановление возвращает заводской текст и снимает "
                     "утверждение владельца; применяется только после "
                     "явного подтверждения.")}


async def restore_factory_all(db=None, *, chat_id: int | None = None,
                              confirm: bool = False) -> dict:
    """Массовое восстановление заводских карточек (только явный confirm).

    Восстанавливает ровно те карточки, что показал preview (владельческие
    правки/tombstone заводских строк). ``confirm=False`` → честный отказ.
    """
    if not confirm:
        return {"ok": False, "reason": "needs_confirmation",
                "restored": 0, "failed": []}
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return {"ok": False, "reason": "db_unavailable",
                "restored": 0, "failed": []}
    preview = await restore_factory_preview(db, chat_id=chat_id)
    restored = 0
    failed: list[dict] = []
    for item in preview.get("items", ()):
        view, reason = await restore_factory_sample(
            db, int(item.get("id") or 0), confirm=True)
        if view is None:
            failed.append({"id": item.get("id"), "reason": reason})
            continue
        restored += 1
    return {"ok": not failed, "restored": restored, "failed": failed,
            "reason": ""}


async def mark_used(db=None, sample_ids: Iterable[int] = (),
                    *, ts: int | float | None = None) -> int:
    """Отметить применение (recency/penalty + видимая телеметрия)."""
    ids = [int(i) for i in (sample_ids or ()) if int(i) > 0]
    if not ids:
        return 0
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return 0

    async def _body(conn):
        now = _now(ts)
        for sample_id in ids[:3]:
            await conn.execute(
                "UPDATE humor_samples SET uses_count = uses_count + 1, "
                "last_used_at = ? WHERE id = ?", (now, sample_id))
        return True

    try:
        await db.write_transaction(_body, op_name="humor_sample_used")
    except Exception:
        logger.warning("[humor-samples] mark_used failed", exc_info=True)
        return 0
    return min(len(ids), 3)


async def seed_starter_samples(db=None, *, force: bool = False) -> dict:
    """Идемпотентный сид заводской подборки (черновики, НЕ одобренные).

    Повтор — no-op по `seed_key`; владельческие правки не перетираются
    (существующая строка сида не обновляется). ADD-SAMPLES-UX §3:
    tombstone-строки НЕ воскресают — ни повторным сидом, ни force
    (восстановление — только ``restore_factory_sample`` с подтверждением);
    ``force`` больше не перезаписывает содержимое существующих строк и
    влияет только на подсчёт (неявных путей force нет).
    """
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return {"seeded": 0, "skipped": 0, "reason": "db_unavailable"}
    seeded = skipped = 0
    for sample in STARTER_SAMPLES:
        seed_key = str(sample.get("seed_key") or "")
        if not seed_key:
            continue
        try:
            cursor = await db.db.execute(
                "SELECT id, tombstone FROM humor_samples WHERE seed_key = ?",
                (seed_key,))
            row = await cursor.fetchone()
        except Exception:
            logger.warning("[humor-samples] seed lookup failed", exc_info=True)
            return {"seeded": seeded, "skipped": skipped,
                    "reason": "read_error"}
        if row is not None:
            # Строка существует: tombstone (намеренное удаление) или обычный
            # повтор — пересоздание запрещено (SU-PERSIST.TOMB/IDEM).
            skipped += 1
            continue
        fields = {**sample, "category": "humor", "scope": "global",
                  "source_kind": "bot_suggested",
                  "library_version": STARTER_LIBRARY_VERSION,
                  "owner_approved": False}
        view, reason = await create_sample(db, fields=fields,
                                           actor="starter_seed")
        if view is None:
            logger.warning("[humor-samples] seed write failed | key=%s | "
                           "reason=%s", seed_key, reason)
            continue
        seeded += 1
    return {"seeded": seeded, "skipped": skipped, "reason": ""}


async def seed_expression_samples(db=None, *, force: bool = False) -> dict:
    """ADD-EXP §3.3: идемпотентный сид набора регистра речи (черновики).

    Существующий механизм сидов (`seed_key`, повтор — no-op, правки владельца
    не перетираются); `owner_approved=False` — в runtime до одобрения владельца
    примеры НЕ идут (`not_owner_approved` — честная причина, не дефект).
    ADD-SAMPLES-UX §3: tombstone-строки (владелец удалил намеренно) не
    пересоздаются ни при повторе, ни при force.
    """
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return {"seeded": 0, "skipped": 0, "reason": "db_unavailable"}
    seeded = skipped = 0
    for sample in EXPRESSION_STARTER_SAMPLES:
        seed_key = str(sample.get("seed_key") or "")
        if not seed_key:
            continue
        try:
            cursor = await db.db.execute(
                "SELECT id, tombstone FROM humor_samples WHERE seed_key = ?",
                (seed_key,))
            row = await cursor.fetchone()
        except Exception:
            logger.warning("[humor-samples] expr seed lookup failed",
                           exc_info=True)
            return {"seeded": seeded, "skipped": skipped,
                    "reason": "read_error"}
        if row is not None:
            skipped += 1
            continue
        fields = {**sample, "scope": "global", "source_kind": "bot_suggested",
                  "library_version": EXPRESSION_STARTER_LIBRARY_VERSION,
                  "owner_approved": False}
        view, reason = await create_sample(db, fields=fields,
                                           actor="expression_seed")
        if view is None:
            logger.warning("[humor-samples] expr seed write failed | key=%s | "
                           "reason=%s", seed_key, reason)
            continue
        seeded += 1
    return {"seeded": seeded, "skipped": skipped, "reason": ""}


async def resolve_expression_examples(chat_id: int, mode: str, *,
                                      db=None) -> tuple[dict, ...]:
    """ADD-EXP §3.3: строки набора СВОЕГО режима (≤4), только эталоны.

    Тонкая обёртка над `resolve_expression_examples_ex` (совместимый контракт:
    только строки). Условия отбора: ``technique='expression_register'`` + тег
    режима + ``owner_approved=1`` + ``status='active'``; scope — global или
    свой чат (изоляция чатов). Ось `expression_examples_enabled` — env
    kill-switch: OFF → пусто. Никогда не бросает.
    """
    rows, _reason = await resolve_expression_examples_ex(chat_id, mode, db=db)
    return rows


async def resolve_expression_examples_ex(chat_id: int, mode: str, *,
                                         db=None,
                                         stats: dict | None = None
                                         ) -> tuple[tuple[dict, ...], str]:
    """`(строки, честная причина)` — BLOCK-1: «нет одобренных» ≠ «нет строк».

    Причины: ``""`` (набор собран) | ``expression_examples_disabled`` (ось OFF) |
    ``expression_examples_absent`` (строк режима нет вовсе / хранилище
    недоступно) | ``not_owner_approved`` (строки режима есть, но ни одна не
    утверждена владельцем — в runtime не идут, §3.3). Никогда не бросает.

    ADD-SAMPLES-UX §1/§5: отбор читает ЯВНОЕ поле `category='mat'` +
    `expression_mode`, а не произвольные теги (тег не создаёт режим;
    mat-карточка без поля режима в отбор не попадает — владелец задаёт
    режим в редакторе).

    ASAP3 §2 (#13): ``stats`` — необязательный out-параметр с фактическим
    составом ДО технического лимита ``EXPRESSION_RESOLVE_MAX_ITEMS``:
    ``eligible`` (сколько одобренных строк режима реально подошло),
    ``selected`` (сколько отдано) и ``dropped``. Без него числа потерялись бы:
    вызывающий код видел только ≤4 строки и не мог отличить «у владельца 4
    примера» от «у владельца 20, вошло 4».
    """
    from services import mca_gates
    if stats is not None:
        # Любой ранний выход оставляет честные нули, а не прошлый вызов.
        stats.clear()
        stats.update({"eligible": 0, "selected": 0, "dropped": 0})
    mode = str(mode or "")
    if mode not in EXPRESSION_SAMPLE_MODES:
        return (), "expression_examples_absent"
    if not mca_gates.expression_examples_enabled():
        return (), "expression_examples_disabled"
    db = db if db is not None else get_db()
    if not _db_ready(db):
        return (), "expression_examples_absent"
    if not await table_ready(db):
        return (), "expression_examples_absent"
    try:
        rows = await list_samples(db, chat_id=int(chat_id or 0),
                                  category="mat", status="active")
    except Exception:
        logger.warning("[humor-samples] expr resolve failed", exc_info=True)
        return (), "expression_examples_absent"
    out: list[dict] = []
    eligible = 0
    drafts_in_mode = 0
    for view in rows:
        # Явное поле режима; теги режим не создают (SU-CAT.MAT).
        if str(view.get("expression_mode") or "") != mode:
            continue                       # только набор effective-режима
        scope = str(view.get("scope") or "global")
        row_chat = view.get("chat_id")
        if scope == "chat" and (row_chat is None
                                or int(row_chat) != int(chat_id or 0)):
            continue
        if not bool(view.get("owner_approved")):
            drafts_in_mode += 1            # черновик владельца: не эталон
            continue
        if _flags(view.get("sensitivity_flags")):
            continue
        if scan_sensitivity(view.get("input_text"), view.get("reply_text")):
            continue
        # ASAP3 §2 (#13): считаем ВСЕ подходящие строки; лимит §3.2 только
        # ограничивает выдачу, а не счёт (иначе потеря 5..N невидима).
        eligible += 1
        if len(out) < EXPRESSION_RESOLVE_MAX_ITEMS:
            out.append(dict(view))
    if stats is not None:
        stats.update({"eligible": eligible, "selected": len(out),
                      "dropped": max(0, eligible - len(out))})
    if out:
        return tuple(out), ""
    if drafts_in_mode:
        # BLOCK-1: примеры ЕСТЬ, но не одобрены — честная причина (не «absent»).
        return (), "not_owner_approved"
    return (), "expression_examples_absent"





# ═══════════════════════════════════════════════════════════════════════════
# Политика отбора `humor.selection`
# ═══════════════════════════════════════════════════════════════════════════


def normalize_policy(raw: Any) -> dict:
    """Нормализовать документ политики (fail-safe дефолты, bounded)."""
    policy = dict(DEFAULT_POLICY)
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            name = str(key)
            if name not in policy:
                continue
            if name in POLICY_LIMITS and not isinstance(value, bool):
                lo, hi = POLICY_LIMITS[name]
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                policy[name] = int(max(lo, min(hi, number))) \
                    if name in ("max_items", "max_tokens",
                                "max_per_technique") \
                    else max(lo, min(hi, number))
                continue
            if name == "enabled" or name == "ab_enabled":
                policy[name] = bool(value)
            elif name == "ab_versions":
                versions = [str(v)[:32] for v in (value or [])
                            if str(v).strip()][:2]
                if len(versions) == 2:
                    policy[name] = versions
    if policy["max_per_technique"] < 1:
        policy["max_per_technique"] = 1
    return policy


async def resolve_policy(chat_id: int | None = None) -> tuple[dict, str]:
    """Действующая политика отбора: chat → global → default."""
    global_doc: Any = None
    chat_doc: Any = None
    try:
        from services import hot_config as hot
        global_doc = hot.get(SELECTION_DOC_KEY, None)
    except Exception:
        global_doc = None
    if chat_id:
        try:
            from services.chat_params import get_chat_params_cache
            cache = get_chat_params_cache()
            if cache is not None:
                root = await cache.get_chat_params(int(chat_id))
                if isinstance(root, Mapping):
                    chat_doc = (root.get("overrides") or {}).get(
                        SELECTION_DOC_KEY)
        except Exception:
            chat_doc = None
    if isinstance(chat_doc, Mapping):
        return normalize_policy({**normalize_policy(global_doc), **chat_doc}), \
            "chat"
    if isinstance(global_doc, Mapping):
        return normalize_policy(global_doc), "global"
    return dict(DEFAULT_POLICY), "default"


# ═══════════════════════════════════════════════════════════════════════════
# Отбор 1–3 примеров (детерминированный, 0 LLM)
# ═══════════════════════════════════════════════════════════════════════════

_TOKEN_RE = re.compile(r"[\w\-]{3,}", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.casefold() for t in _TOKEN_RE.findall(str(text or ""))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _extent_fits(reply_text: str, extent: str) -> bool:
    extent = str(extent or "")
    words = len(str(reply_text or "").split())
    if extent == "one_word":
        return False                     # слой примеров не нужен вовсе
    if extent == "micro":
        return words <= 12
    if extent in ("compact", "short"):
        return words <= 40
    return True


def ab_version_for(chat_id: int, policy: Mapping[str, Any]) -> str:
    """Детерминированное распределение A/B по чату (без рандома/состояния)."""
    if not policy.get("ab_enabled"):
        return ""
    versions = list(policy.get("ab_versions") or [])
    if len(versions) != 2:
        return ""
    try:
        weight = float(policy.get("ab_weight", 0.5))
    except (TypeError, ValueError):
        weight = 0.5
    material = hashlib.sha256(f"ab|{int(chat_id)}".encode("utf-8")).digest()
    bucket = int.from_bytes(material[:4], "big") / 0xFFFFFFFF
    return str(versions[0] if bucket < weight else versions[1])


@dataclass(frozen=True)
class Selection:
    """Результат отбора: примеры + честные причины (SOUL-07.3)."""

    samples: tuple[dict, ...] = ()
    reasons: tuple[dict, ...] = ()
    excluded: tuple[dict, ...] = ()
    reason_code: str = ""
    policy_source: str = "default"
    library_version: str = ""

    @property
    def tokens_estimate(self) -> int:
        return sum(int(r.get("estimated_tokens") or 0) for r in self.reasons)


def _candidate_bonus(technique: str, wanted: str) -> float:
    if not wanted:
        return 0.0
    return 0.4 if str(technique) == str(wanted) else 0.0


def select_samples(rows: Sequence[Mapping[str, Any]], *,
                   chat_id: int = 0, technique: str = "",
                   extent: str = "", context: str = "",
                   category: str = "",
                   policy: Mapping[str, Any] | None = None,
                   penalties: Mapping[str, float] | None = None,
                   now_ts: int | float | None = None) -> Selection:
    """Отобрать ≤max_items примеров (или ни одного) с причинами.

    Чистая функция (без I/O) — проверяется тестами на изоляцию/утечки.
    ADD-SAMPLES-UX §5: ``category`` ограничивает отбор своей категорией
    (humor/general); mat-строки не попадают в humor-путь НИКОГДА — по
    категории ИЛИ по приёму (не по совпадению слов); неклассифицированное
    legacy в runtime не идёт, пока владелец не выберет категорию.
    """
    pol = normalize_policy(policy)
    penalties = dict(penalties or {})
    if not pol.get("enabled"):
        return Selection(reason_code="samples_disabled")
    if str(extent or "") == "one_word":
        return Selection(reason_code="samples_extent_fit")
    version = ab_version_for(int(chat_id or 0), pol)
    now = _now(now_ts)
    wanted = str(technique or "")
    scored: list[tuple[float, dict]] = []
    excluded: list[dict] = []
    for row in rows:
        rid = int(row.get("id") or 0)
        row_category = str(row.get("category") or "")
        if str(row.get("technique") or "") == "expression_register" \
                or row_category == "mat":
            # ADD-EXP §3.3 + ADD-SAMPLES-UX §5: жёсткая изоляция осей —
            # humor/general-путь НИКОГДА не берёт набор регистра речи
            # (категория/приём, а не совпадение слов).
            excluded.append({"id": rid, "reason": "expression_register"})
            continue
        if row_category == "legacy":
            # Неоднозначные legacy-строки: категорию выбирает владелец.
            excluded.append({"id": rid, "reason": "category_unassigned"})
            continue
        if category and row_category != category:
            # Пример другой категории не подмешивается в чужой блок.
            excluded.append({"id": rid, "reason": "category_mismatch"})
            continue
        if str(row.get("status") or "active") != "active":
            excluded.append({"id": rid, "reason": "archived"})
            continue
        if not bool(row.get("owner_approved")):
            # SOUL-07.1/07.3: черновики не идут в runtime как эталоны.
            excluded.append({"id": rid, "reason": "not_owner_approved"})
            continue
        scope = str(row.get("scope") or "global")
        row_chat = row.get("chat_id")
        if scope == "chat":
            if row_chat is None or int(row_chat) != int(chat_id or 0):
                excluded.append({"id": rid, "reason": "cross_chat_guard"})
                continue
        elif row_chat is not None:
            excluded.append({"id": rid, "reason": "cross_chat_guard"})
            continue
        if _flags(row.get("sensitivity_flags")):
            excluded.append({"id": rid, "reason": "leakage_guard"})
            continue
        if scan_sensitivity(row.get("input_text"), row.get("reply_text")):
            excluded.append({"id": rid, "reason": "leakage_guard"})
            continue
        row_version = str(row.get("library_version")
                          or DEFAULT_LIBRARY_VERSION)
        if version and row_version != version:
            continue
        if not _extent_fits(str(row.get("reply_text") or ""), extent):
            excluded.append({"id": rid, "reason": "extent_fit"})
            continue
        query_tokens = _tokens(context)
        row_tokens = _tokens(f"{row.get('input_text')} "
                             f"{row.get('reply_text')} "
                             f"{row.get('context_note')}")
        relevance = _jaccard(query_tokens, row_tokens) if query_tokens else 0.0
        freshness = 0.05 if int(row.get("uses_count") or 0) == 0 else 0.0
        score = (0.45 * relevance
                 + _candidate_bonus(str(row.get("technique") or ""), wanted)
                 + freshness)
        penalty = float(penalties.get(str(row.get("id")), 0.0))
        penalty += float(penalties.get(
            "technique:" + str(row.get("technique") or ""), 0.0))
        try:
            recency_penalty = float(pol.get("recency_penalty", 0.0))
        except (TypeError, ValueError):
            recency_penalty = 0.0
        last_used = row.get("last_used_at")
        if last_used:
            try:
                age_h = max(0.0, (now - float(last_used)) / 3600.0)
            except (TypeError, ValueError):
                age_h = 999.0
            if age_h < 6.0:
                penalty += recency_penalty * (1.0 - age_h / 6.0)
        total = score - penalty
        if total < float(pol.get("min_relevance", 0.0)):
            excluded.append({"id": rid, "reason": "below_min_score",
                             "score": round(total, 4)})
            continue
        scored.append((total, {**dict(row), "_score": total,
                               "_relevance": round(relevance, 4),
                               "_penalty": round(penalty, 4)}))
    scored.sort(key=lambda item: (-item[0], int(item[1].get("id") or 0)))
    picked: list[dict] = []
    reasons: list[dict] = []
    per_technique: dict[str, int] = {}
    used_tokens = 0
    max_items = int(pol.get("max_items", 3))
    max_tokens = int(pol.get("max_tokens", 320))
    max_per_technique = int(pol.get("max_per_technique", 1))
    min_distance = float(pol.get("diversity_min_distance", 0.0))
    for score, row in scored:
        rid = int(row.get("id") or 0)
        if len(picked) >= max_items:
            excluded.append({"id": rid, "reason": "max_items"})
            continue
        technique_key = str(row.get("technique") or "other")
        if per_technique.get(technique_key, 0) >= max_per_technique:
            excluded.append({"id": rid, "reason": "same_technique"})
            continue
        row_tokens = _tokens(str(row.get("reply_text") or ""))
        if any(_jaccard(row_tokens, _tokens(
                str(other.get("reply_text") or ""))) > (1.0 - min_distance)
                for other in picked):
            excluded.append({"id": rid, "reason": "not_diverse"})
            continue
        text = render_line(row)
        from services.prompt_composer import estimate_tokens
        cost = estimate_tokens(text)
        if used_tokens + cost > max_tokens:
            excluded.append({"id": rid, "reason": "budget_exceeded"})
            continue
        used_tokens += cost
        picked.append(row)
        per_technique[technique_key] = per_technique.get(technique_key, 0) + 1
        reasons.append({
            "id": rid, "score": round(float(score), 4),
            "relevance": row.get("_relevance"),
            "penalty": row.get("_penalty"),
            "technique": technique_key,
            "library_version": str(row.get("library_version") or ""),
            "source_kind": str(row.get("source_kind") or ""),
            "estimated_tokens": cost,
            "why": _why(row, wanted, bool(penalties)),
        })
    if not picked:
        return Selection(excluded=tuple(excluded),
                         reason_code="samples_absent", library_version=version)
    return Selection(samples=tuple(picked), reasons=tuple(reasons),
                     excluded=tuple(excluded), reason_code="samples_selected",
                     library_version=version)


def _why(row: Mapping[str, Any], wanted: str, has_penalties: bool) -> str:
    parts = [f"категория={row.get('category') or 'legacy'}",
             f"техника={row.get('technique') or 'other'}"]
    if wanted and str(row.get("technique")) == wanted:
        parts.append("совпадает с выбранной стратегией")
    parts.append(f"источник={row.get('source_kind')}")
    if bool(row.get("owner_approved")):
        parts.append("эталон владельца")
    else:
        parts.append("черновик (не эталон)")
    parts.append(f"версия={row.get('library_version')}")
    if int(row.get("uses_count") or 0):
        parts.append(f"применений={int(row.get('uses_count') or 0)}")
    if has_penalties:
        parts.append("учтён контекстный штраф")
    return "; ".join(parts)


def render_line(row: Mapping[str, Any]) -> str:
    """Одна строка примера (вход → ответ)."""
    return HUMOR_FEW_SHOT_LINE.format(
        input=str(row.get("input_text") or "").strip(),
        reply=str(row.get("reply_text") or "").strip())


def render_block(samples: Sequence[Mapping[str, Any]]) -> str:
    """bounded блок few-shot для композера (или пусто)."""
    lines = [render_line(row) for row in (samples or ())]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return ""
    block = "\n\n".join([HUMOR_FEW_SHOT_OPEN, "\n\n".join(lines),
                         HUMOR_FEW_SHOT_CLOSE])
    return block[:MAX_TOTAL_CHARS]


# ── ADD-SAMPLES-UX §5: различимый блок общих примеров ──────────────────────
GENERAL_FEW_SHOT_OPEN = (
    "<General_Examples>\n"
    "Примеры ниже задают манеру ответа: тон, лаконичность, реакцию. "
    "Не копируй лексику и детали дословно и не переноси чужие реалии в этот "
    "чат."
)
GENERAL_FEW_SHOT_LINE = HUMOR_FEW_SHOT_LINE
GENERAL_FEW_SHOT_CLOSE = "</General_Examples>"
GENERAL_FEW_SHOT_TEMPLATE = "\n".join(
    (GENERAL_FEW_SHOT_OPEN, GENERAL_FEW_SHOT_LINE, GENERAL_FEW_SHOT_CLOSE))


def render_general_block(samples: Sequence[Mapping[str, Any]]) -> str:
    """bounded блок общих примеров `<General_Examples>` (или пусто)."""
    lines = [render_line(row) for row in (samples or ())]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return ""
    block = "\n\n".join([GENERAL_FEW_SHOT_OPEN, "\n\n".join(lines),
                         GENERAL_FEW_SHOT_CLOSE])
    return block[:MAX_TOTAL_CHARS]


# ═══════════════════════════════════════════════════════════════════════════
# Провайдер слоя для композера + телеметрия отбора
# ═══════════════════════════════════════════════════════════════════════════


async def resolve_refs(*, chat_id: int, technique: str = "", extent: str = "",
                       context: str = "", penalties: Mapping[str, float]
                       | None = None, db=None) -> tuple[tuple, Selection]:
    """`SampleRef`-блоки для композера + трасса отбора (0 LLM).

    ADD-SAMPLES-UX §5: два различимых блока — `<General_Examples>`
    (block_id ``general_few_shot``) и существующий humor-блок `<Examples>`
    (block_id ``few_shot``). Каждый ограничен своей политикой (1–3 / ноль),
    без смешивания без метки; дополнительных LLM-вызовов нет.
    """
    from services.prompt_composer import SampleRef
    if not mca_library_gate_on():
        return (), Selection(reason_code="samples_disabled")
    db = db if db is not None else get_db()
    policy, source = await resolve_policy(chat_id)
    if not _db_ready(db):
        return (), Selection(reason_code="samples_unavailable",
                             policy_source=source)
    if not await table_ready(db):
        return (), Selection(reason_code="samples_absent",
                             policy_source=source)
    rows = await list_samples(db, chat_id=chat_id, status="active")
    raw_rows = [_to_row(view) for view in rows]
    selection = select_samples(raw_rows, chat_id=chat_id, technique=technique,
                               extent=extent, context=context,
                               category="humor", policy=policy,
                               penalties=penalties)
    selection = replace(selection, policy_source=source)
    general_selection = select_samples(
        raw_rows, chat_id=chat_id, technique="", extent=extent,
        context=context, category="general", policy=policy,
        penalties=penalties)
    general_selection = replace(general_selection, policy_source=source)
    refs = []
    if general_selection.samples:
        text = render_general_block(general_selection.samples)
        refs.append(SampleRef(
            block_id="general_few_shot", text=text,
            revision=sha12(text),
            source="global",
            library_version=str(general_selection.library_version or ""),
            technique="",
            reason="general_examples:" + "; ".join(
                str(r.get("why") or "") for r in general_selection.reasons)))
        await mark_used(db, [int(r.get("id") or 0) for r
                             in general_selection.samples])
    for row in selection.samples:
        text = render_line(row)
        refs.append(SampleRef(
            block_id="few_shot", text=text,
            revision=str(row.get("revision") or 1),
            source=str(row.get("scope") or "global"),
            library_version=str(row.get("library_version") or ""),
            technique=str(row.get("technique") or ""),
            reason=_why(row, technique, bool(penalties))))
    if selection.samples:
        await mark_used(db, [int(r.get("id") or 0) for r in selection.samples])
        _emit_selection(chat_id, selection)
    if general_selection.samples:
        _emit_selection(chat_id, general_selection, category="general")
    return tuple(refs), selection


def sha12(text: str) -> str:
    """12-hex sha256 (та же ревизия, что у композера/реестра)."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def _to_row(view: Mapping[str, Any]) -> dict:
    """Карточка API → строка таблицы (для чистого отбора)."""
    return {
        "id": view.get("id"), "input_text": view.get("input_text"),
        "reply_text": view.get("reply_text"), "technique": view.get("technique"),
        "context_note": view.get("context_note"),
        "language": view.get("language"), "tags": view.get("tags"),
        "rudeness_level": view.get("rudeness_level"),
        "source_kind": view.get("source_kind"), "scope": view.get("scope"),
        "chat_id": view.get("chat_id"),
        "owner_approved": view.get("owner_approved"),
        "status": view.get("status"),
        "library_version": view.get("library_version"),
        "revision": view.get("revision"), "uses_count": view.get("uses_count"),
        "last_used_at": view.get("last_used_at"),
        "sensitivity_flags": view.get("sensitivity_flags"),
        "category": view.get("category"),
        "expression_mode": view.get("expression_mode"),
        "owner_modified": view.get("owner_modified"),
    }


def mca_library_gate_on() -> bool:
    try:
        from services import mca_gates
        return bool(mca_gates.humor_library_enabled())
    except Exception:                      # pragma: no cover
        return False


def _emit_selection(chat_id: int, selection: Selection, *,
                    category: str = "humor") -> None:
    """Трасса отбора в существующую телеметрию (без второго стора).

    ADD-SAMPLES-UX: категория отбора видна в `status` (cat:humor/general) —
    Inspector/диагностика различает блоки без новых сторов.
    """
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(
            "humor_samples_selected", outcome="success", component="humor",
            reason_code="samples_selected",
            status="cat:" + str(category or "humor"),
            chat_id=chat_id,
            entity_ids=[str(r.get("id")) for r in selection.reasons],
            selected=len(selection.samples),
            excluded=len(selection.excluded),
            library_version=selection.library_version or "")
    except Exception:
        return


async def telemetry(db=None, *, chat_id: int | None = None) -> dict:
    """Видимая телеметрия библиотеки (honest zero-состояния)."""
    db = db if db is not None else get_db()
    out: dict[str, Any] = {
        "available": _db_ready(db), "total": 0, "approved": 0, "proposed": 0,
        "archived": 0, "chat_scoped": 0, "by_technique": {},
        "by_version": {}, "uses_total": 0, "starter_seeded": 0,
        # ADD-EXP (BLOCK-1): заводской набор регистра речи считается отдельно —
        # владелец видит «сколько заведено» по каждой подборке, без склейки.
        "expression_starter_seeded": 0,
        # ADD-SAMPLES-UX: покатегорийные счётчики (текущей категории UI) +
        # tombstone-счётчик удалённых заводских.
        "by_category": {c: 0 for c in SAMPLE_CATEGORY_STORAGE},
        "approved_by_category": {c: 0 for c in SAMPLE_CATEGORY_STORAGE},
        "tombstoned": 0,
        "ab": {"enabled": False, "versions": []},
    }
    if not _db_ready(db):
        out["reason"] = "db_unavailable"
        return out
    if not await table_ready(db):
        out["reason"] = "schema_absent"
        return out
    try:
        rows = await list_samples(db, chat_id=chat_id, status=None, limit=500)
    except Exception:
        out["reason"] = "read_error"
        return out
    out["total"] = len(rows)
    for row in rows:
        technique = str(row.get("technique") or "other")
        out["by_technique"][technique] = \
            out["by_technique"].get(technique, 0) + 1
        version = str(row.get("library_version") or DEFAULT_LIBRARY_VERSION)
        out["by_version"][version] = out["by_version"].get(version, 0) + 1
        category = str(row.get("category") or "legacy")
        if category not in out["by_category"]:
            out["by_category"][category] = 0
            out["approved_by_category"][category] = 0
        out["by_category"][category] += 1
        if row.get("owner_approved"):
            out["approved"] += 1
            out["approved_by_category"][category] += 1
        else:
            out["proposed"] += 1
        if str(row.get("status")) == "archived":
            out["archived"] += 1
        if str(row.get("scope")) == "chat":
            out["chat_scoped"] += 1
        if str(row.get("seed_key") or ""):
            if str(row.get("library_version") or "") == \
                    EXPRESSION_STARTER_LIBRARY_VERSION:
                out["expression_starter_seeded"] += 1
            else:
                out["starter_seeded"] += 1
        out["uses_total"] += int(row.get("uses_count") or 0)
    tombstoned = await list_tombstoned(db, chat_id=chat_id, limit=500)
    out["tombstoned"] = len(tombstoned)
    policy, source = await resolve_policy(chat_id)
    out["policy_source"] = source
    out["ab"] = {"enabled": bool(policy.get("ab_enabled")),
                 "versions": list(policy.get("ab_versions") or []),
                 "pinned": ab_version_for(int(chat_id or 0), policy)}
    out["runtime_note"] = (
        "В runtime уходят только помеченные владельцем эталоны "
        "(owner_approved) активной версии библиотеки: 1–3 примера или ни одного."
    )
    return out


# ═══════════════════════════════════════════════════════════════════════════
# ADD-SAMPLES-UX §1: миграция категорий v37 (идемпотентная, обратимая
# по данным — technique/tags/содержимое не изменяются, только новые поля)
# ═══════════════════════════════════════════════════════════════════════════


def migration_category_for(technique: Any) -> str:
    """Правило миграции §1: expression_register → mat; приёмы юмора → humor;
    неоднозначное `other` → legacy (владелец переклассифицирует сам)."""
    technique = str(technique or "")
    if technique == "expression_register":
        return "mat"
    if technique in HUMOR_CRAFT_TECHNIQUES:
        return "humor"
    return "legacy"


def migration_mode_from_tags(tags: Any) -> str | None:
    """Режим из режимного тега — ТОЛЬКО для бэкфила миграции существующих
    строк. Новые записи и отбор читают явное поле, тег режим не создаёт."""
    tags_lower = {str(t).strip().lower() for t in parse_tags(tags)}
    for mode in EXPRESSION_SAMPLE_MODES:
        if EXPRESSION_MODE_TAGS[mode] in tags_lower:
            return mode
    return None


async def backfill_categories_v37(db) -> dict:
    """Бэкфил `category`/`expression_mode` существующих строк (v37).

    Идемпотентно: трогаются только строки с ``category='legacy'`` (значение
    по умолчанию колонки) и mat-строки без поля режима при наличии режимного
    тега. ID/ревизии/approved/содержимое/scope/архив/история/A-B не меняются.
    Повтор — no-op.
    """
    counts = {"mat": 0, "humor": 0, "legacy": 0, "mode_from_tag": 0}
    if not _db_ready(db):
        return counts
    try:
        cursor = await db.db.execute(
            "SELECT id, technique, tags, category, expression_mode "
            "FROM humor_samples")
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        logger.warning("[humor-samples] v37 backfill read failed",
                       exc_info=True)
        return counts
    for row in rows:
        rid = int(row.get("id") or 0)
        category = str(row.get("category") or "legacy")
        updates: dict[str, Any] = {}
        if category == "legacy":
            target = migration_category_for(row.get("technique"))
            if target != "legacy":
                updates["category"] = target
                counts[target] += 1
            else:
                counts["legacy"] += 1
        if str(row.get("technique") or "") == "expression_register" \
                and not row.get("expression_mode"):
            mode = migration_mode_from_tags(row.get("tags"))
            if mode:
                updates["expression_mode"] = mode
                counts["mode_from_tag"] += 1
        if not updates:
            continue
        sets = ", ".join(f"{c} = ?" for c in updates)
        try:
            await db.db.execute(
                f"UPDATE humor_samples SET {sets} WHERE id = ?",
                tuple(updates.values()) + (rid,))
        except Exception:
            logger.warning("[humor-samples] v37 backfill row failed | id=%s",
                           rid, exc_info=True)
    return counts


# ═══════════════════════════════════════════════════════════════════════════
# ADD-SAMPLES-UX §5: «Почему не используется?» / «Почему выбран?» —
# human-readable причина из существующего детерминированного отбора
# (без симуляции; нет данных — честное «Нет данных о последнем выборе»)
# ═══════════════════════════════════════════════════════════════════════════

WHY_NO_DATA = "Нет данных о последнем выборе"


def humanize_exclusion_reason(reason: str, *, row: Mapping[str, Any] | None
                              = None, effective_mode: str = "") -> str:
    """Человекочитаемая причина из причин существующего отбора (не симуляция)."""
    reason = str(reason or "")
    if reason == "not_owner_approved":
        return "Черновик — ещё не утверждён"
    if reason == "archived":
        return "Пример в архиве"
    if reason == "category_unassigned":
        return ("Пример не отнесён к категории — выберите «Общие», «Юмор» "
                "или «Мат» в редакторе")
    if reason == "category_mismatch":
        return "Не подошёл к этому запросу (другая категория)"
    if reason == "expression_register":
        return "Не подошёл к этому запросу (пример речевого регистра)"
    if reason == "mode_mismatch":
        card_mode = str((row or {}).get("expression_mode") or "")
        label = {"off": "Без мата", "occasional": "Эпизодически",
                 "frequent": "Часто"}.get(card_mode, card_mode)
        effective_label = {"off": "Без мата", "occasional": "Эпизодически",
                           "frequent": "Часто"}.get(
            str(effective_mode or ""), str(effective_mode or ""))
        return ("Этот пример относится к режиму «%s», сейчас выбран «%s»"
                % (label or "не задан", effective_label or "не задан"))
    if reason == "mode_unassigned":
        return "Режим мата не задан — выберите его в редакторе"
    if reason == "cross_chat_guard":
        return "Пример принадлежит другому чату"
    if reason == "leakage_guard":
        return "Пример помечен защитой от утечек"
    if reason == "extent_fit":
        return "Не подошёл к этому запросу (объём ответа)"
    if reason == "max_items":
        return "Превышен лимит примеров на ответ"
    if reason == "same_technique":
        return "Не подошёл к этому запросу (уже взят пример этого приёма)"
    if reason == "not_diverse":
        return "Не подошёл к этому запросу (похож на уже выбранный)"
    if reason == "budget_exceeded":
        return "Превышен бюджет примеров"
    if reason == "below_min_score":
        return "Не подошёл к этому запросу"
    if reason == "samples_disabled":
        return "Отбор примеров выключен политикой"
    return ""


async def why_for_sample(db, *, chat_id: int | None, sample_id: int,
                         message: str = "", technique: str = "",
                         extent: str = "", effective_mode: str = "") -> dict:
    """Причина применения/неприменения КОНКРЕТНОЙ карточки (детерминированно).

    Источник — тот же отбор, что в runtime (`select_samples` /
    `resolve_expression_examples_ex`); effective-режим Expression передаёт
    вызывающий (существующий резолв слоя). Ни одного дополнительного
    LLM-вызова, ничего не отправляется. Нет данных — честное ``WHY_NO_DATA``.
    """
    current = await get_sample(db, sample_id)
    if current is None:
        return {"ok": False, "reason": "not_found", "why": WHY_NO_DATA,
                "selected": False}
    if bool(current.get("tombstone")):
        return {"ok": True, "selected": False,
                "why": "Пример удалён владельцем (восстановите исходный, "
                       "если он снова нужен)",
                "reason_code": "tombstone"}
    if str(current.get("status") or "") == "archived":
        return {"ok": True, "selected": False,
                "why": humanize_exclusion_reason("archived"),
                "reason_code": "archived"}
    category = str(current.get("category") or "legacy")
    if category == "mat":
        from services import mca_gates
        if not mca_gates.expression_examples_enabled():
            return {"ok": True, "selected": False,
                    "why": "Набор примеров регистра выключен",
                    "reason_code": "expression_examples_disabled"}
        effective = str(effective_mode or "").strip().lower()
        if effective not in EXPRESSION_SAMPLE_MODES:
            return {"ok": True, "selected": False, "why": WHY_NO_DATA,
                    "reason_code": "no_data"}
        if str(current.get("expression_mode") or "") != effective:
            return {"ok": True, "selected": False,
                    "why": humanize_exclusion_reason(
                        "mode_mismatch", row=current,
                        effective_mode=effective),
                    "reason_code": "mode_mismatch"}
        if not str(current.get("expression_mode") or ""):
            return {"ok": True, "selected": False,
                    "why": humanize_exclusion_reason("mode_unassigned"),
                    "reason_code": "mode_unassigned"}
        rows, reason = await resolve_expression_examples_ex(
            int(chat_id or 0), effective, db=db)
        if any(int(r.get("id") or 0) == sample_id for r in rows):
            return {"ok": True, "selected": True,
                    "why": "Выбран как пример текущего режима «%s»"
                           % {"off": "Без мата", "occasional": "Эпизодически",
                              "frequent": "Часто"}.get(effective, effective),
                    "reason_code": "selected"}
        if reason == "not_owner_approved" and not bool(
                current.get("owner_approved")):
            return {"ok": True, "selected": False,
                    "why": humanize_exclusion_reason("not_owner_approved"),
                    "reason_code": "not_owner_approved"}
        if reason == "expression_examples_absent":
            return {"ok": True, "selected": False,
                    "why": humanize_exclusion_reason("max_items"),
                    "reason_code": "max_items"}
        return {"ok": True, "selected": False, "why": WHY_NO_DATA,
                "reason_code": "no_data"}
    # general/humor/legacy — тот же отбор, что в runtime.
    if category == "legacy":
        return {"ok": True, "selected": False,
                "why": humanize_exclusion_reason("category_unassigned"),
                "reason_code": "category_unassigned"}
    rows = await list_samples(db, chat_id=chat_id, status="active")
    raw_rows = [_to_row(row) for row in rows]
    policy, _source = await resolve_policy(chat_id)
    if not policy.get("enabled"):
        # SU-FS.WHY: отбор выключен — честная причина, не симуляция.
        return {"ok": True, "selected": False,
                "why": humanize_exclusion_reason("samples_disabled"),
                "reason_code": "samples_disabled"}
    selection = select_samples(
        raw_rows, chat_id=int(chat_id or 0), technique=str(technique or ""),
        extent=str(extent or ""), context=str(message or ""),
        category=category, policy=policy)
    picked_ids = {int(r.get("id") or 0) for r in selection.samples}
    if sample_id in picked_ids:
        why = next((str(r.get("why") or "") for r in selection.reasons
                    if int(r.get("id") or 0) == sample_id), "")
        return {"ok": True, "selected": True,
                "why": "Выбран в блок «%s»: %s"
                       % (SAMPLE_CATEGORY_LABELS.get(category, category),
                          why or "уместен этому запросу"),
                "reason_code": "selected"}
    excluded = next((e for e in selection.excluded
                     if int(e.get("id") or 0) == sample_id), None)
    if excluded is None:
        return {"ok": True, "selected": False, "why": WHY_NO_DATA,
                "reason_code": "no_data"}
    text = humanize_exclusion_reason(str(excluded.get("reason") or ""))
    if not text:
        return {"ok": True, "selected": False, "why": WHY_NO_DATA,
                "reason_code": "no_data"}
    return {"ok": True, "selected": False, "why": text,
            "reason_code": str(excluded.get("reason") or "")}
