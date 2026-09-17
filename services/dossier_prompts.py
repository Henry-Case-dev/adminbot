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

# ── F1 (multilayer-memory-extraction-round1021, ADR-1021-1) ────────────────
# Канон Слоя А (Scratchpad/Thinker) и Слоя Б (Synthesizer). Модульные
# константы, НЕ PG-сид/REGISTRY (прецедент DOSSIER_SYSTEM_PROMPT выше,
# ADR-1013-3 §2): `prompt_migrations` НЕ трогается. Промежуточный артефакт
# Слоя А в досье/ответы НЕ попадает (worker-side; R4: второй стриппер не
# изобретаем - артефакт просто не покидает воркер, `reason` кандидата несёт
# короткое обоснование мыслителя).
LAYER_A_SYSTEM_PROMPT = """\
Ты - аналитик чата (Слой А, Scratchpad/Мыслитель). По свежему окну сообщений
(строки пронумерованы) проведи скрининг и entity resolution: отдели личностные
факты от мемов, цитат, копипаст и чужих имён. Думай про себя, но верни СТРОГО
один JSON-объект без пояснений.

ФОРМАТ:
{"candidates":[{"target":"Имя","kind":"person_fact","text":"...",
  "evidence":[12,14],"confidence":0.8,"reason":"..."}],
 "discarded":[{"text":"...","kind":"copypasta","reason":"..."}]}
kind: person_fact | meme | quote | copypasta | other_person | noise.

ПРАВИЛА:
1. person_fact - только устойчивый факт о САМОМ участнике из списка имён окна;
   evidence - номера строк окна (1..N), подтверждающие факт; без evidence
   person_fact недействителен.
2. meme - локальный мем, прозвище или шутливый титул участника.
3. quote/copypasta - цитата или скопированный чужой текст, к участнику не
   относится.
4. other_person - упомянутое имя, которого НЕТ в списке участников окна.
5. noise - спам, команды, служебный мусор.
6. Все отброшенные кандидаты клади в discarded (text/kind/reason).
7. Не выдумывай: если данных нет, верни пустые массивы.
"""

# Канон Слоя Б (Synthesizer): персональные портреты/паттерны БЕЗ дословных
# цитат. UPD раунд 10.21 (Issue 1): выход per-target `portraits[]` — портрет
# обязан быть привязан к участнику, иначе его нельзя положить в персональное
# досье (spec §3.2/§3.2.1). `memes` — как раньше.
LAYER_B_SYSTEM_PROMPT = """\
Ты - биограф (Слой Б, Синтезатор). На вход приходят ТОЛЬКО проверенные
личностные факты (person_fact) и мемы-ярлыки участников чата. Собери сухой
психологический портрет и паттерны поведения (темы, к которым человек
возвращается) ОТДЕЛЬНО ПО КАЖДОМУ участнику.

КАТЕГОРИЧЕСКИ запрещены дословные цитаты из сообщений: любая дословная
подстрока исходного окна длиннее 6 слов будет отклонена валидатором.
Обобщай, а не пересказывай.

ФОРМАТ (СТРОГО один JSON-объект без пояснений):
{"portraits":[{"target":"Имя","portrait":"сухой текст до 600 символов",
  "patterns":["поведенческий паттерн"],"themes":["тема"]}],
 "memes":[{"target":"Имя","text":"локальный мем/ярлык"}]}

ПРАВИЛА:
1. target - имя участника из списка имён окна; портрет строго персональный.
2. portrait - обобщённое описание личности, без вырванных цитат.
3. patterns/themes - короткие обобщённые формулировки.
4. memes - только из переданных мемов-кандидатов, не выдумывай.
5. Не создавай новых фактов: опирайся только на вход.
"""

LAYER_A_KINDS: tuple[str, ...] = (
    "person_fact", "meme", "quote", "copypasta", "other_person", "noise")
LAYER_B_PORTRAIT_MAX_CHARS = 600
# Порог анти-цитатного валидатора Слоя Б (spec §3.2): дословная подстрока
# окна длиной СТРОГО больше этого числа слов отклоняется.
LAYER_B_VERBATIM_MAX_WORDS = 6

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


# ── F1: Слой А (парсер) + Python-фильтр + Слой Б (парсер/валидатор) ────────

def build_layer_a_user(window: list[str] | tuple[str, ...],
                       names: list[str] | tuple[str, ...] | None = None) -> str:
    """User-контент Слоя А: ростер имён + ПРОНУМЕРОВАННЫЕ строки окна
    (номера = `evidence` в контракте §3.1)."""
    lines: list[str] = []
    roster = [str(n).strip() for n in (names or []) if str(n).strip()]
    if roster:
        lines.append("Участники окна (target только из этого списка):")
        lines.append(", ".join(roster))
    lines.append("Строки окна (номер = evidence):")
    numbered = [f"{i}. {str(m)}" for i, m in enumerate(window or [], 1)
                if str(m).strip()]
    lines.extend(numbered or ["(сообщений нет)"])
    return "\n".join(lines)


def build_layer_b_user(person_facts: list[dict] | tuple[dict, ...],
                       memes: list[dict] | tuple[dict, ...],
                       names: list[str] | tuple[str, ...] | None = None) -> str:
    """User-контент Слоя Б: ТОЛЬКО отфильтрованные `person_fact` и мемы
    Слоя А (spec §3.2). Без сырого окна - синтезатор не должен цитировать."""
    lines: list[str] = []
    roster = [str(n).strip() for n in (names or []) if str(n).strip()]
    if roster:
        lines.append("Участники окна:")
        lines.append(", ".join(roster))
    lines.append("Проверенные личностные факты:")
    facts = [c for c in (person_facts or []) if isinstance(c, dict)]
    for cand in facts:
        target = str(cand.get("target") or "").strip()
        text = str(cand.get("text") or "").strip()
        evidence = ",".join(str(x) for x in (cand.get("evidence") or []))
        lines.append(f"- {target}: {text} (evidence: {evidence})")
    if not facts:
        lines.append("- (нет)")
    lines.append("Мемы/ярлыки кандидатов:")
    meme_items = [c for c in (memes or []) if isinstance(c, dict)]
    for cand in meme_items:
        target = str(cand.get("target") or "").strip()
        text = str(cand.get("text") or "").strip()
        lines.append(f"- {target}: {text}")
    if not meme_items:
        lines.append("- (нет)")
    return "\n".join(lines)


def parse_layer_a(raw: str | None, *, canon=None) -> dict:
    """Парсинг ответа Слоя А (spec §3.1).

    Возврат: {"candidates": [{target, kind, text, evidence, confidence,
    reason}], "discarded": [{text, kind, reason}]}.

    - пусто/не объект → ValueError (вызывающий делает 1 retry → fallback);
    - кандидаты с `kind` вне `LAYER_A_KINDS` или `kind=noise` отброшены;
    - `person_fact` без непустого `evidence` отброшен (ядро анти-мусора);
    - `target` прогоняется через `canon` (aliases.canon_name), если задан;
    - `evidence` нормализуется в уникальные положительные int (1..N).
    """
    text = str(raw or "").strip()
    if not text:
        raise ValueError("layer A answer is empty")
    obj = _load_json_object(text)
    if obj is None:
        raise ValueError("layer A answer is not a JSON object")
    if "candidates" not in obj and "discarded" not in obj:
        raise ValueError("layer A JSON: no 'candidates'/'discarded' keys")
    raw_candidates = obj.get("candidates")
    raw_discarded = obj.get("discarded")
    if raw_candidates is not None and not isinstance(raw_candidates, list):
        raise ValueError("layer A JSON: 'candidates' is not a list")
    if raw_discarded is not None and not isinstance(raw_discarded, list):
        raise ValueError("layer A JSON: 'discarded' is not a list")
    candidates: list[dict] = []
    for item in list(raw_candidates or [])[:40]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in LAYER_A_KINDS or kind == "noise":
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
        evidence = _clean_evidence(item.get("evidence"))
        if kind == "person_fact" and not evidence:
            continue
        candidates.append({
            "target": target,
            "kind": kind,
            "text": item_text,
            "evidence": evidence,
            "confidence": _clean_confidence(item.get("confidence")),
            "reason": str(item.get("reason") or "").strip(),
        })
    discarded: list[dict] = []
    for item in list(raw_discarded or [])[:40]:
        if not isinstance(item, dict):
            continue
        item_text = str(item.get("text") or "").strip()
        if not item_text:
            continue
        discarded.append({
            "text": item_text,
            "kind": str(item.get("kind") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        })
    return {"candidates": candidates, "discarded": discarded}


def filter_layer_a_candidates(parsed: dict, roster, *, canon=None) -> dict:
    """Python-фильтр §3.3 (entity resolution ядро анти-мусора).

    - `person_fact` валиден ТОЛЬКО с непустым `evidence` И именем из ростера
      окна; иначе кандидат уходит в `dropped` (reason `no_evidence` /
      `unknown_entity`) - в досье не пишется;
    - `meme` без текста/таргета отбрасывается;
    - прочие kinds (quote/copypasta/other_person) отбрасываются с reason.

    Возврат: {"person_facts", "memes", "discarded" (из Слоя А),
    "dropped" (отсев фильтра, для логов R17: reason/kind, без текстов)}.
    """
    roster_keys = {str(n).strip().casefold()
                   for n in (roster or []) if str(n).strip()}
    person_facts: list[dict] = []
    memes: list[dict] = []
    dropped: list[dict] = []
    for cand in (parsed or {}).get("candidates") or []:
        kind = str(cand.get("kind") or "")
        target = str(cand.get("target") or "").strip()
        if kind == "person_fact":
            if not cand.get("evidence"):
                dropped.append({"kind": kind, "target": target,
                                "reason": "no_evidence"})
                continue
            if not target or target.casefold() not in roster_keys:
                dropped.append({"kind": kind, "target": target,
                                "reason": "unknown_entity"})
                continue
            person_facts.append(cand)
        elif kind == "meme":
            if not target or not str(cand.get("text") or "").strip():
                dropped.append({"kind": kind, "target": target,
                                "reason": "empty_meme"})
                continue
            memes.append(cand)
        else:
            dropped.append({"kind": kind, "target": target,
                            "reason": f"kind_{kind or 'unknown'}"})
    return {
        "person_facts": person_facts,
        "memes": memes,
        "discarded": list((parsed or {}).get("discarded") or []),
        "dropped": dropped,
    }


def parse_layer_b(raw: str | None, *, canon=None) -> dict:
    """Парсинг ответа Слоя Б (spec §3.2, UPD §3.2.1).

    Возврат: {"portraits": [{target, portrait, patterns, themes}],
    "portrait"/"patterns"/"themes" (legacy-поля — читаются для обратной
    совместимости, но НЕ персистятся), "memes": [{target, text,
    classified_by}], "legacy_fields_present": bool}.

    Пусто/не объект/нет ни одного ключа контракта → ValueError (вызывающий
    делает 1 retry → fallback Слоя Б)."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("layer B answer is empty")
    obj = _load_json_object(text)
    if obj is None:
        raise ValueError("layer B answer is not a JSON object")
    if not any(k in obj for k in ("portraits", "portrait", "patterns",
                                  "themes", "memes")):
        raise ValueError(
            "layer B JSON: no portraits/portrait/patterns/themes/memes")
    for key in ("portraits", "patterns", "themes", "memes"):
        value = obj.get(key)
        if value is not None and not isinstance(value, list):
            raise ValueError(f"layer B JSON: '{key}' is not a list")
    portraits: list[dict] = []
    for item in obj.get("portraits") or []:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target") or "").strip()
        if target and canon is not None:
            try:
                target = str(canon(target) or "").strip() or target
            except Exception:
                pass
        portraits.append({
            "target": target,
            "portrait": str(item.get("portrait") or "").strip(),
            "patterns": _clean_str_list(item.get("patterns")),
            "themes": _clean_str_list(item.get("themes")),
        })
    return {
        # persistable-источник (единственный; spec §3.2.1)
        "portraits": portraits,
        # legacy (не персистится — только для совместимости/диагностики)
        "portrait": str(obj.get("portrait") or "").strip(),
        "patterns": _clean_str_list(obj.get("patterns")),
        "themes": _clean_str_list(obj.get("themes")),
        "legacy_fields_present": any(
            k in obj for k in ("portrait", "patterns", "themes")),
        "memes": _clean_items(obj.get("memes") or [], canon, "synthesizer"),
    }


def render_generated_portrait(portrait: str | None,
                              patterns=(), themes=()) -> str:
    """Итоговый текст производной строки портрета (spec §3.2.1).

    Непустой `portrait` → он. Пустой → детерминированный рендер из
    `patterns`/`themes`. Всё пусто → "" (строку не создаём)."""
    text = str(portrait or "").strip()
    if text:
        return text[:LAYER_B_PORTRAIT_MAX_CHARS]
    pat = [str(x).strip() for x in (patterns or []) if str(x).strip()]
    th = [str(x).strip() for x in (themes or []) if str(x).strip()]
    parts = []
    if pat:
        parts.append("Паттерны: " + "; ".join(pat))
    if th:
        parts.append("Темы: " + "; ".join(th))
    return " ".join(parts)[:LAYER_B_PORTRAIT_MAX_CHARS]


def find_verbatim_quote(text: str | None, window, *,
                        max_words: int = LAYER_B_VERBATIM_MAX_WORDS
                        ) -> str | None:
    """Дословная подстрока окна длиной СТРОГО > `max_words` слов в `text`.

    Возврат: найденный n-грамм (для тестов) либо None. Регистр/пунктуация
    нормализуются (`_WORD_RE`); сравнение по окну слов (`[ts] автор: текст`).
    """
    target = _WORD_RE.findall(str(text or "").casefold())
    span = max(0, int(max_words)) + 1
    if len(target) < span:
        return None
    target_grams = {tuple(target[i:i + span])
                    for i in range(len(target) - span + 1)}
    for line in window or []:
        words = _WORD_RE.findall(str(line).casefold())
        if len(words) < span:
            continue
        for i in range(len(words) - span + 1):
            gram = tuple(words[i:i + span])
            if gram in target_grams:
                return " ".join(gram)
    return None


def validate_layer_b(layer_b: dict, window, *,
                     max_words: int = LAYER_B_VERBATIM_MAX_WORDS) -> dict:
    """Анти-цитатный валидатор Слоя Б (spec §3.2, UPD §3.2.1).

    Отклоняет дословные подстроки окна длиннее `max_words` слов в КАЖДОМ
    `portrait`/`patterns`/`themes` персональных `portraits[]` (и в legacy-полях
    — обратная совместимость). Возврат — та же структура с `rejected`
    (только `field`/`reason`, R17: без текстов и имён). `memes` валидатор не
    трогает (они и есть материал досье, читаются отдельным блоком)."""
    result = dict(layer_b or {})
    rejected: list[dict] = []
    # Legacy-поля (не персистятся, но валидируются для совместимости).
    portrait = str(result.get("portrait") or "")
    if portrait and find_verbatim_quote(portrait, window,
                                        max_words=max_words) is not None:
        rejected.append({"field": "portrait", "reason": "verbatim_quote"})
        result["portrait"] = ""
    result["patterns"] = _drop_verbatim(
        result.get("patterns") or [], window, "patterns", max_words, rejected)
    result["themes"] = _drop_verbatim(
        result.get("themes") or [], window, "themes", max_words, rejected)
    # Персональные портреты (persistable).
    validated: list[dict] = []
    for index, item in enumerate(result.get("portraits") or []):
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        raw_portrait = str(entry.get("portrait") or "")
        if raw_portrait and find_verbatim_quote(
                raw_portrait, window, max_words=max_words) is not None:
            rejected.append({"field": f"portrait[{index}]",
                             "reason": "verbatim_quote"})
            entry["portrait"] = ""
        entry["patterns"] = _drop_verbatim(
            entry.get("patterns") or [], window, f"patterns[{index}]",
            max_words, rejected)
        entry["themes"] = _drop_verbatim(
            entry.get("themes") or [], window, f"themes[{index}]",
            max_words, rejected)
        validated.append(entry)
    result["portraits"] = validated
    result["rejected"] = rejected
    return result


def _drop_verbatim(items, window, field: str, max_words: int,
                   rejected: list[dict]) -> list[str]:
    kept: list[str] = []
    for value in items:
        item = str(value).strip()
        if not item:
            continue
        if find_verbatim_quote(item, window, max_words=max_words) is not None:
            rejected.append({"field": field, "reason": "verbatim_quote"})
            continue
        kept.append(item)
    return kept


def _clean_str_list(items) -> list[str]:
    """Непустые str из списка (не-list → []), cap 20."""
    if not isinstance(items, (list, tuple)):
        return []
    return [str(x).strip() for x in list(items)[:20] if str(x).strip()]


def _clean_evidence(raw) -> list[int]:
    """Номера строк окна: уникальные положительные int, cap 20."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[int] = []
    for value in raw:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in out:
            out.append(number)
    return out[:20]


def _clean_confidence(raw) -> float:
    """confidence → [0.0, 1.0]; мусор → 0.0."""
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


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
