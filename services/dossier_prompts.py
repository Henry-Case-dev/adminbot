"""F8 (cognition-irony-dossier-round1013, spec §4) — канон «Досье»/иронии.

Модульные канон-константы (НЕ PG-сид, НЕ REGISTRY-ключ — прецедент Q10/NFR-6
раунда 9 и ADR-1013-3 §2: `prompt_migrations` для них НЕ трогается).
`DOSSIER_SYSTEM_PROMPT` — системный промпт воркера, собирающего досье:
он раскладывает добычу по двум корзинам `real_facts` (реальная биография) и
`chat_memes` (оскорбительные/абсурдные титулы и локальные мемы).

PREV-слепок (`PREV_DOSSIER_SYSTEM_PROMPT`) для greenfield-канона пуст:
до F8 отдельного промпта досье в коде НЕ существовало (байт-тест фиксирует
отсутствие исторического значения, ADR-1013-3 §2.2).

Ниже — чистые хелперы (НЕ канон): keyword fail-safe, парсер ответа,
сборка user-контента и рендер досье двумя блоками.
"""
import json
import re

# ── КАНОН (spec §4.1; не редактировать без PR) ─────────────────────────────
# Дословная инструкция ТЗ §2 («Иронический фильтр») + строгий JSON-контракт.
DOSSIER_SYSTEM_PROMPT = """\
Ты - архивариус, собирающий досье на людей в чате. По свежему окну сообщений
извлеки сведения о людях и разложи их по двум корзинам: real_facts (реальные
факты биографии) и chat_memes (локальные мемы и ярлыки).

ИРОНИЧЕСКИЙ ФИЛЬТР: Пользователи часто шутят и используют сарказм. Оскорбительные или абсурдные титулы (например, 'мегачмо', 'повелитель грибов') записывать в отдельный массив `chat_memes`, а не в `real_facts`.

ПРАВИЛА:
1. Отвечай СТРОГО одним JSON-объектом без пояснений:
   {"real_facts":[{"target":"Имя","text":"..."}],
    "chat_memes":[{"target":"Имя","text":"..."}]}
2. target - имя участника из списка имён окна (как в сообщениях).
3. В real_facts только устойчивые факты о человеке (где живёт, чем занят,
   реальные события). Шутки, дразнилки, прозвища, титулы - в chat_memes.
4. Не выдумывай: если данных нет, верни пустые массивы.
"""

# Greenfield-канон: до F8 промпта досье не было, исторического PREV нет.
PREV_DOSSIER_SYSTEM_PROMPT = ""

# Fail-safe (spec §4.1/§11): фразы-ярлыки, которые ОБЯЗАНЫ попасть в
# chat_memes, даже если LLM ошибочно отнесла их к real_facts.
KEYWORD_MEME_HINTS: tuple[str, ...] = (
    "мегачмо",
    "повелитель грибов",
    "повелитель",
    "лорд",
    "король",
    "королева",
    "царь",
    "император",
    "бог",
    "боженька",
)

_FACTS_HEADER = "[Факты]"
_MEMES_HEADER = "[Локальные мемы/Ярлыки]"
_WORD_RE = re.compile(r"[0-9a-zа-яё]+")


def matches_meme_hint(text: str | None) -> bool:
    """True — фраза матчит keyword fail-safe (мем).

    Одиночные слова матчатся по границе слова (чтобы «бог» не ловился в
    «богатый»), фразы из нескольких слов — как подстрока (схлопнутые
    пробелы). Регистр не важен."""
    normalized = " ".join(str(text or "").casefold().split())
    if not normalized:
        return False
    for hint in KEYWORD_MEME_HINTS:
        needle = hint.casefold()
        if " " in needle:
            if needle in normalized:
                return True
        elif needle in _WORD_RE.findall(normalized):
            return True
    return False


def build_dossier_user(window: list[str] | tuple[str, ...],
                       names: list[str] | tuple[str, ...] | None = None) -> str:
    """User-контент воркера досье: список имён окна (шпаргалка для `target`)
    + строки окна `[ts] автор: текст` (готовые строки воркера)."""
    lines: list[str] = []
    roster = [str(n).strip() for n in (names or []) if str(n).strip()]
    if roster:
        lines.append("Участники чата (используй эти имена в target):")
        lines.append(", ".join(roster))
    lines.append("Свежие сообщения чата:")
    messages = [str(m) for m in (window or []) if str(m).strip()]
    lines.extend(messages or ["(сообщений нет)"])
    return "\n".join(lines)


def parse_dossier_answer(raw: str | None, *, canon=None) -> dict:
    """Парсинг ответа LLM (spec §4.1).

    Возврат: {"real_facts": [{"target": str, "text": str, "classified_by": str}],
              "chat_memes": [...]}.

    - UNCHANGED/пусто → оба массива пусты;
    - кривой JSON/не объект → raise ValueError (вызывающий делает 1 retry);
    - элементы не-dict/без `text` — отброшены;
    - `target` прогоняется через `canon` (aliases.canon_name), если задан;
    - keyword fail-safe: real_fact, матчащий KEYWORD_MEME_HINTS, переносится
      в chat_memes (`classified_by="keyword"`).
    """
    text = str(raw or "").strip()
    if not text or text.upper() == "UNCHANGED":
        return {"real_facts": [], "chat_memes": []}
    obj = _load_json_object(text)
    if obj is None:
        raise ValueError("dossier answer is not a JSON object")
    raw_facts = obj.get("real_facts")
    raw_memes = obj.get("chat_memes")
    if raw_facts is None and raw_memes is None:
        raise ValueError("dossier JSON: no 'real_facts'/'chat_memes' keys")
    if raw_facts is not None and not isinstance(raw_facts, list):
        raise ValueError("dossier JSON: 'real_facts' is not a list")
    if raw_memes is not None and not isinstance(raw_memes, list):
        raise ValueError("dossier JSON: 'chat_memes' is not a list")
    facts = _clean_items(raw_facts or [], canon, "llm")
    memes = _clean_items(raw_memes or [], canon, "llm")
    kept: list[dict] = []
    for item in facts:
        if matches_meme_hint(item["text"]):
            memes.append({**item, "classified_by": "keyword"})
        else:
            kept.append(item)
    return {"real_facts": kept, "chat_memes": memes}


def _clean_items(items: list, canon, classified_by: str) -> list[dict]:
    """Нормализация массива: dict + непустой text; target через canon."""
    result: list[dict] = []
    for item in list(items)[:20]:            # защита от мусорных хвостов
        if not isinstance(item, dict):
            continue
        item_text = str(item.get("text") or "").strip()
        if not item_text:
            continue
        target = str(item.get("target") or "").strip()
        if target and canon is not None:
            try:
                target = str(canon(target) or "").strip()
            except Exception:
                pass
        result.append({"target": target, "text": item_text,
                       "classified_by": classified_by})
    return result


def format_dossier_block(facts: list[str] | tuple[str, ...],
                         memes: list[str] | tuple[str, ...],
                         cap_chars: int) -> str:
    """Рендер досье двумя блоками (spec §6): `[Факты]` и
    `[Локальные мемы/Ярлыки]`.

    - пустой блок НЕ рендерится (старое досье без memes → только `[Факты]`);
    - общий бюджет `cap_chars`; при переполнении первыми урезаются МЕМЫ,
      затем факты; cap_chars <= 0 — без ограничения;
    - при нехватке места под сами заголовки возвращается ""."""
    fact_items = [str(x).strip() for x in (facts or []) if str(x).strip()]
    meme_items = [str(x).strip() for x in (memes or []) if str(x).strip()]
    if not fact_items and not meme_items:
        return ""
    cap = int(cap_chars or 0)

    def rendered(f: list[str], m: list[str]) -> str:
        parts = []
        if f:
            parts.append(_FACTS_HEADER + "\n" + "\n".join(f))
        if m:
            parts.append(_MEMES_HEADER + "\n" + "\n".join(m))
        return "\n".join(parts)

    text = rendered(fact_items, meme_items)
    if cap <= 0 or len(text) <= cap:
        return text
    while meme_items and len(rendered(fact_items, meme_items)) > cap:
        meme_items.pop()
    text = rendered(fact_items, meme_items)
    if len(text) <= cap:
        return text
    while fact_items and len(rendered(fact_items, meme_items)) > cap:
        fact_items.pop()
    text = rendered(fact_items, meme_items)
    return text if len(text) <= cap else ""


def _load_json_object(text: str) -> dict | None:
    """JSON-объект из ответа: прямой json.loads или срез между первой '{' и
    последней '}' (код-фенсы/пояснения вокруг не мешают)."""
    candidates = [text]
    fenced = re.sub(r"^```[a-zA-Z]*\s*", "", text.strip())
    fenced = re.sub(r"\s*```\s*$", "", fenced)
    if fenced != text:
        candidates.append(fenced)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start: end + 1])
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None
    return None
