"""Раунд 9 (AGI Memory, T-825/D4, spec §3.4.5/Q10) — промпт-канон дистилляции
«сна» (DreamWorker).

Канон-константа модуля (НЕ PG-сид и НЕ REGISTRY-ключ — прецедент
_CHAT_RAG_RERANK_SYSTEM_PROMPT summary_memory.py:237; Q10: промпты
дистилляции/ностальгии живут в модулях, как lore_prompts).

Структура финального текста — spec §3.4.5 (системная роль, ПРАВИЛА 1–4,
user-блок). Контракт ответа: СТРОГО JSON-объект
{"beliefs":[{"text":"...","evidence":[номера фактов]}]}; пусто — {"beliefs":[]}
или одно слово UNCHANGED. Запрет кавычек-ёлочек и длинных тире — в тексте
ответа убеждений (канон-стиль, NFR-6). Свой текст — без «», —, – (байт-тесты).
"""
import datetime
import json
import re

# F1/T-1421 (spec §9, ADR-1013-3): PREV-слепок прежнего канона, байт-в-байт
# (до правила 5). PROMPT_MIGRATIONS НЕ трогается: канон — модульная константа,
# не PG-сид (ADR-1013-3 §2.3), мигрировать нечего.
PREV_DREAM_DISTILL_PROMPT = """\
Ты - синтезатор долговременной памяти чата. Тебе дают кластер фактов (каждый
с номером, датой и текстом), повторяющихся в переписке чата. Если в кластере
есть устойчивое повторяющееся правило про человека, обычай чата или регулярное
событие - сформулируй 1-2 коротких убеждения (до 120 символов каждое),
обобщающих эти факты. Убеждение не должно противоречить ни одному факту
кластера.

ПРАВИЛА:
1. Отвечай СТРОГО одним JSON-объектом без пояснений:
   {"beliefs":[{"text":"...","evidence":[<номера фактов>]}]}
2. Каждое убеждение опирается минимум на 2 факта кластера; evidence - их
   номера из списка.
3. Текст убеждения - без кавычек-ёлочек и длинных тире.
4. Если устойчивого повторения нет или факты противоречат друг другу -
   верни {"beliefs":[]} либо одно слово: UNCHANGED.
"""

# Спека §3.4.5 + F1/T-1421 §6: структура и требования канона; финальный текст
# собран по шаблону spec (системная роль → ПРАВИЛА 1-5 → UNCHANGED-вариант
# пустоты). Правило 5 добавлено F1: учёт дат фактов и требование ДИНАМИКИ.
DREAM_DISTILL_PROMPT = """\
Ты - синтезатор долговременной памяти чата. Тебе дают кластер фактов (каждый
с номером, датой и текстом), повторяющихся в переписке чата. Если в кластере
есть устойчивое повторяющееся правило про человека, обычай чата или регулярное
событие - сформулируй 1-2 коротких убеждения (до 120 символов каждое),
обобщающих эти факты. Убеждение не должно противоречить ни одному факту
кластера.

ПРАВИЛА:
1. Отвечай СТРОГО одним JSON-объектом без пояснений:
   {"beliefs":[{"text":"...","evidence":[<номера фактов>]}]}
2. Каждое убеждение опирается минимум на 2 факта кластера; evidence - их
   номера из списка.
3. Текст убеждения - без кавычек-ёлочек и длинных тире.
4. Если устойчивого повторения нет или факты противоречат друг другу -
   верни {"beliefs":[]} либо одно слово: UNCHANGED.
5. Учитывай даты фактов. Если правило или ситуация менялись во времени,
   сформулируй ДИНАМИКУ: что было раньше и что стало теперь.
"""


def order_dream_rows(rows: list[dict], *, max_facts: int = 25) -> list[dict]:
    """F1/T-1421 (spec §6): факты кластера в ХРОНОЛОГИЧЕСКОМ порядке —
    `_fact_date` ASC, затем id ASC; обрезка до `max_facts`. Нумерация
    evidence в `build_dream_user` идёт по позиции в ЭТОМ порядке (вызывающий
    строит source_ids тем же порядком)."""
    ordered = sorted(rows, key=lambda r: (_fact_date(r), r.get("id") or 0))
    return list(ordered[: int(max_facts)])


def build_dream_user(rows: list[dict], *, max_facts: int = 25) -> str:
    """User-блок дистилляции (§3.4.5 + F1/T-1421): до `max_facts` фактов
    `N. [ГГГГ-ММ-ДД] текст` — ХРОНОЛОГИЧЕСКИЙ порядок (`_fact_date` ASC,
    затем id ASC; spec §6), нумерация 1..N — на неё ссылаются evidence."""
    lines = ["Кластер фактов чата:"]
    for i, row in enumerate(order_dream_rows(rows, max_facts=max_facts), 1):
        text = " ".join(str(row.get("fact") or "").split())
        date = _fact_date(row)
        lines.append(f"{i}. [{date}] {text}")
    return "\n".join(lines)


def _fact_date(row: dict) -> str:
    """Дата факта в user-блоке: message_timestamp или created_at (unix →
    ГГГГ-ММ-ДД local; битое/пустое → '????-??-??')."""
    ts = row.get("message_timestamp") or row.get("created_at")
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "????-??-??"


def parse_distill_answer(raw: str | None, fact_ids: list[int],
                         min_evidence: int = 2) -> list[dict]:
    """Парсинг ответа LLM (§3.4.5): JSON-объект {"beliefs": [...]} или слово
    UNCHANGED (пустота). Возвращает список belief-диктов:
    {"text": str, "evidence": [реальные graph_facts.id, ...]}.
    - beliefs пусто/UNCHANGED → [] (статус unchanged);
    - кривой JSON → raise ValueError (вызывающий делает 1 retry);
    - evidence-номера вне списка — отбрасываются;
    - belief с < `min_evidence` реальных фактов НЕ пишется (анти-галлюцинации),
      кривой текст — не пишется."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty distill answer")
    if _is_unchanged(text):
        return []
    obj = _load_json_object(text)
    if obj is None:
        raise ValueError("distill answer is not a JSON object")
    raw_beliefs = obj.get("beliefs")
    if raw_beliefs is None:
        if obj:
            raise ValueError("distill JSON: no 'beliefs' key")
        return []
    if not isinstance(raw_beliefs, list):
        raise ValueError("distill JSON: 'beliefs' is not a list")
    result: list[dict] = []
    for item in raw_beliefs[: 4]:        # защита от мусорных хвостов
        if not isinstance(item, dict):
            continue
        belief_text = str(item.get("text") or "").strip()
        if not belief_text:
            continue
        evidence: list[int] = []
        raw_evidence = item.get("evidence")
        if isinstance(raw_evidence, list):
            for num in raw_evidence:
                try:
                    evidence.append(fact_ids[int(num) - 1])
                except (TypeError, ValueError, IndexError):
                    continue
        # уникальность, порядок фактов id ASC (стабильный рендер/хранение)
        seen = set()
        evidence = sorted(fid for fid in evidence
                          if fid not in seen and not seen.add(fid))
        if len(evidence) < min_evidence:
            continue
        result.append({"text": belief_text, "evidence": evidence})
    return result


def _is_unchanged(text: str) -> bool:
    """Ответ LLM == UNCHANGED (равенство с точностью до регистра/пробелов —
    как is_unchanged_response у lore_prompts)."""
    return str(text or "").strip().upper() == "UNCHANGED"


# ── F3/T-1437 (cognition-deep-sleep, spec §4): канон «Мост времени» ────────
# Новый модульный канон глубокого сна (ADR-1013-3 §2: не PG-сид, PREV не
# нужен — канона до F3 не существовало; PROMPT_MIGRATIONS не трогаем).
# Контракт ответа: СТРОГО JSON {"paradigms":[{"text":"...","anchors":[...]}]}.
DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT = """\
Ты - синтезатор долговременной памяти чата на этапе глубокого сна. Тебе дают
свежий контекст чата (недавние убеждения и выжимку активности за последние
часы) и подборку старых фактов из истории. Найди связь между текущими
событиями и историческими фактами и сформулируй мета-факт (парадигму) о
развитии ситуации или человека.

ПРАВИЛА:
1. Отвечай СТРОГО одним JSON-объектом без пояснений:
   {"paradigms":[{"text":"...","anchors":[<номера исторических фактов>]}]}
2. Парадигма - обобщение о ДИНАМИКЕ (что было раньше и что стало теперь),
   а не пересказ отдельного факта.
3. Каждая парадигма опирается минимум на 2 исторических факта; anchors - их
   номера из нумерованного списка.
4. Текст парадигмы до 200 символов, без кавычек-ёлочек и длинных тире.
5. Если связи нет или данных мало - верни {"paradigms":[]}.
"""


def _anchor_parts(item) -> tuple:
    """Исторический якорь → (origin, fact, rag_ts, target_user). Принимает
    4-кортеж RAG (`get_rag_facts`) или dict (гибкий вход для тестов)."""
    if isinstance(item, dict):
        return (item.get("origin"), item.get("fact"),
                item.get("rag_ts") or item.get("created_at"),
                item.get("target_user"))
    if isinstance(item, (tuple, list)):
        seq = list(item) + [None, None, None, None]
        return (seq[0], seq[1], seq[2], seq[3])
    return (None, str(item or ""), None, None)


def _anchor_date(item) -> str:
    """Дата якоря (ГГГГ-ММ-ДД; UTC — как _fact_prefix/summary_memory; битое/
    пустое → '????-??-??')."""
    ts = _anchor_parts(item)[2]
    try:
        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return "????-??-??"


def build_bridge_user(packet: dict, historical: list, *,
                      max_beliefs: int = 20,
                      max_recent: int = 40) -> str:
    """User-блок «Моста времени» (F3/T-1437, spec §4): свежий контекст
    (убеждения только что завершившегося сна + выжимка 12ч) и нумерованный
    список исторических фактов (номера 1..N — на них ссылаются anchors).

    `packet` = {"beliefs": [dict с полем 'fact'...], "recent": [dict 'fact']}.
    `historical` — список 4-кортежей RAG (`get_rag_facts`) или dict."""
    beliefs = [b for b in (packet.get("beliefs") or [])
               if str(b.get("fact") or "").strip()][: int(max_beliefs)]
    recent = [r for r in (packet.get("recent") or [])
              if str(r.get("fact") or "").strip()][: int(max_recent)]
    lines = ["Свежий контекст чата:"]
    if beliefs:
        lines.append("Убеждения только что завершившегося сна:")
        for i, row in enumerate(beliefs, 1):
            lines.append(f"{i}. {_clean(row.get('fact'))}")
    if recent:
        lines.append("Выжимка активности за последние 12 часов:")
        for row in recent:
            lines.append(f"- {_clean(row.get('fact'))}")
    if not beliefs and not recent:
        lines.append("(свежих данных нет)")
    lines.append("")
    lines.append("Исторические факты (номера для anchors):")
    if historical:
        for i, item in enumerate(historical, 1):
            lines.append(f"{i}. [{_anchor_date(item)}] "
                         f"{_clean(_anchor_parts(item)[1])}")
    else:
        lines.append("(исторических фактов не найдено)")
    return "\n".join(lines)


def _clean(value) -> str:
    """Однострочный текст (схлопнутые пробелы) — стабильный рендер промпта."""
    return " ".join(str(value or "").split())


def parse_bridge_answer(raw: str | None, anchor_count: int = 0,
                        min_anchors: int = 2) -> list[dict]:
    """Парсинг ответа «Моста времени» (F3/T-1437, spec §4): JSON-объект
    {"paradigms":[{"text":"...","anchors":[<номера>]}]} или пустой UNCHANGED.
    Возвращает [{"text": str, "anchors": [валидные номера 1..anchor_count]}]:
    - пусто/UNCHANGED/{"paradigms":[]} → [];
    - кривой JSON → raise ValueError (вызывающий делает 1 retry);
    - anchors вне 1..anchor_count отбрасываются; парадигма с < min_anchors
      реальных опор НЕ пишется (анти-галлюцинации; spec §4/промпт: минимум
      ДВЕ исторические опоры); пустой текст — не пишется."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty bridge answer")
    if _is_unchanged(text):
        return []
    obj = _load_json_object(text)
    if obj is None:
        raise ValueError("bridge answer is not a JSON object")
    raw_items = obj.get("paradigms")
    if raw_items is None:
        if obj:
            raise ValueError("bridge JSON: no 'paradigms' key")
        return []
    if not isinstance(raw_items, list):
        raise ValueError("bridge JSON: 'paradigms' is not a list")
    result: list[dict] = []
    cap = max(0, int(anchor_count))
    for item in raw_items[: 8]:          # защита от мусорных хвостов
        if not isinstance(item, dict):
            continue
        paradigm_text = str(item.get("text") or "").strip()
        if not paradigm_text:
            continue
        anchors: list[int] = []
        raw_anchors = item.get("anchors")
        if isinstance(raw_anchors, list):
            for num in raw_anchors:
                try:
                    value = int(num)
                except (TypeError, ValueError):
                    continue
                if 1 <= value <= cap and value not in anchors:
                    anchors.append(value)
        if len(anchors) < max(1, int(min_anchors)):
            continue
        result.append({"text": paradigm_text, "anchors": anchors})
    return result



def _load_json_object(text: str) -> dict | None:
    """JSON-объект из ответа: прямой json.loads или срез между первой '{' и
    последней '}' (код-фенсы/пояснения вокруг — не мешают)."""
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
