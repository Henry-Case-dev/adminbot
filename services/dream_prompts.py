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

# Спека §3.4.5: структура и требования канона; финальный текст собран по
# шаблону spec (системная роль → ПРАВИЛА 1-4 → UNCHANGED-вариант пустоты).
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
"""


def build_dream_user(rows: list[dict], *, max_facts: int = 25) -> str:
    """User-блок дистилляции (§3.4.5): до `max_facts` фактов
    `N. [ГГГГ-ММ-ДД] текст` — сортировка по importance DESC (затем id ASC —
    стабильно), нумерация 1..N — на неё ссылаются evidence."""
    ordered = sorted(rows, key=lambda r: (int(r.get("importance") or 0),
                                          r.get("id") or 0), reverse=True)
    lines = ["Кластер фактов чата:"]
    for i, row in enumerate(ordered[: int(max_facts)], 1):
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
