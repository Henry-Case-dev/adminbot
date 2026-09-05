"""Фаза 2 (T-761..T-763, F1/F3 — часть B) — Graph-воркер импорта истории.

`python manage.py import_history --mode graph` — локально на ноутбуке юзера,
на СНАПШОТЕ прод-БД (edge 13 spec: против живой БД бота воркер не запускается
— SQLite-локи). Переиспользуются ТОЛЬКО SQL-образцы записи vec
(summary_memory._insert_graph_vec_row :1011-1027), формат пачки-промпта и
формат вектора (float JSON + int8 через vec_quantize_int8); MemoryManager/
крон-сервисы бота НЕ поднимаются.

Пайплайн (пачка 25 по умолчанию):
1. выборка: `smart_messages` чата с import_key (только импортированная
   история), history_processed = 0, length(text) >= --min-fact-chars и
   density-шаг `(id % K) == 0` (K = round(1/fact_density); детерминированная
   семплизация — регулятор объёма/стоимости). Хронологический keyset-курсор
   на КОРТЕЖЕ (timestamp, id): `WHERE (timestamp, id) > (?, ?) ORDER BY
   timestamp ASC, id ASC` (row-value SQLite). Id-диапазоны НЕ используются:
   FTS-импорт идёт «свежим первым» — НИЗКИЕ id у НОВЫХ ts, высокие id у
   старых ts; окно по id [cursor..hi] первой пачки старых ts пометило бы
   весь диапазон [1..hi] processed БЕЗ экстракции (fix B1);
2. LLM (локальная Ollama, think off) извлекает триплеты
   {subject, predicate, object, context?} → fact-строка «subject predicate
   object» (как live-путь summary_memory.py:1325);
3. запись: insert_graph_fact(origin='history_import', weight=0.3,
   expires_at=NULL, status='confirmed', message_timestamp=MAX(timestamp)
   пачки — spec Q10/edge 15: LLM даты не присылает) + FTS-строка внутри +
   vec-строка float+int8 (--embed-mode api; session-кэш текст→вектор);
   дубли (частичный UNIQUE-индекс idx_graph_facts_history_import) → INSERT OR
   IGNORE (or_ignore=True), возврат 0 — не ошибка;
4. после успеха пачки помечаются ТОЛЬКО фактически обработанные строки
   (`UPDATE smart_messages SET history_processed=1 WHERE id IN (…)` —
   диапазонов НЕТ). Density-пропуски (id % K != 0) и короткие тексты в
    выборку не попадают НИКОГДА — их добивает _sweep_remaining в конце
    полного прогона (без ошибок и без --limit). Пачка с ошибкой LLM НЕ
    помечается и НЕ фатальна (WARNING + пропуск, курсор двигается дальше,
    следующий запуск повторит); стоп — ТОЛЬКО при N ошибках ПОДРЯД (N=5,
    без --skip-errors — «модель стабильно отвечает ошибкой») или --strict
    (нет в CLI; --skip-errors отключает счётчик и продолжает всегда).

Два транспорта LLM (Q5): 'openai' (дефолт, POST {endpoint}/chat/completions
с response_format json_object + think-выключение) и 'ollama' (POST
{host}/api/chat, think=False + format=JSON-Schema). Способ выключения думания
qwen3.5 — константа _THINK_OFF_* (см. ниже; belt-and-suspenders: и think, и
reasoning_effort — лишние поля Ollama игнорирует).

--vec-backfill — подрежим того же --mode graph (spec 3.5 п.4): догонка
векторов для фактов history_import без vec-строки (закрывает --embed-mode
skip задним числом).
"""
import asyncio
import json
import logging
import random
import re
import time

import httpx

from config.settings import settings
from tools.history_import import prompts

logger = logging.getLogger(__name__)

# ── Константы воркера ────────────────────────────────────────────────
DEFAULT_FACT_DENSITY = 0.15   # решение оркестратора (после B5-аудита 4 файлов)
DEFAULT_MIN_FACT_CHARS = 12   # мин. длина ТЕКСТА сообщения для участия в пачке
DEFAULT_BATCH_SIZE = 25       # spec §3.5: пачка до 25 сообщений
DEFAULT_EMBED_CONCURRENCY = 8  # параллельные embed-запросы (части B/G)
HISTORY_IMPORT_WEIGHT = 0.3    # FR-9: ниже chat_history 0.5 — старое не перебивает
MAX_FACTS_PER_BATCH_FLOOR = 1  # максимум фактов пачки max(1, round(N×density))

# Q5 (spec 3.5/edge 8): qwen3.5 думает по умолчанию. OpenAI-совместимый
# /v1/chat/completions глушит думание через OpenAI-стандартный
# reasoning_effort="none" (новые сборки Ollama) И top-level think:False
# (нативные сборки); лишние/неизвестные поля Ollama игнорирует — кладём оба
# (belt-and-suspenders, проверено @Architect T-747/F1 на установленной
# юзером Ollama). Нативный /api/chat — только think:False.
THINK_OFF_FIELDS = {"reasoning_effort": "none", "think": False}
THINK_OFF_REASONING = {"reasoning_effort": "none"}
THINK_OFF_THINK_FIELD = {"think": False}

_LLM_TIMEOUT_S = 300.0        # локальный decode qwen3.5:9b — долго
_LLM_TRANSPORT_RETRIES = 2    # ретраи на транспорте (поверх первой попытки)
_LLM_RETRY_BACKOFF = 1.5      # сон = backoff_base * 2**attempt + jitter
_LLM_JSON_RETRIES = 1         # битый JSON/пустой content: одна повторная
                              # попытка ТЕМ ЖЕ запросом (не меняя temperature)
_EMBED_TIMEOUT_S = 120.0
_EMBED_MAX_RETRIES = 2
_EMBED_BATCH_SIZE = 32        # текстов на один POST /embeddings
_VEC_BACKFILL_CHUNK = 50      # фактов на один проход догонки векторов
_EMBED_PROBE_TEXT = "probe"   # стартовый пробник (как у бота) — проверка
                              # доступности API и dim == dim таблицы
_WORKER_LOG_EVERY_BATCHES = 100   # INFO раз в N пачек

# Задача «не-фатальность пачек» (2026-09-05): сколько ошибок пачек ПОДРЯД
# (без --skip-errors) → стоп прогона. 1–2 ошибки — пачка пропускается (НЕ
# помечается), процесс продолжается (это локальная модель, сбои одиночные);
# 5 подряд — похоже на системный сбой (Ollama встала/формат сломан): стоп
# с человеческой подсказкой (упавшие пачки повторятся след. запуском).
LLM_FAILURES_BEFORE_STOP = 5

# Регулярки устойчивого парсинга JSON-ответа LLM.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_EMPTY_RE = re.compile(r"^\s*$")


class HistoryLLMError(Exception):
    """Ошибка Graph-этапа: LLM недоступен/битый JSON/мусор после ретраев."""


class EmbedError(Exception):
    """Фатальная ошибка API-эмбеддинга (после ретраев/исчерпания каскада)."""

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        # Задача 2 (2026-09-05): человекочитаемая причина (русский текст для
        # консоли) — проставляется при фейле ВСЕХ ключей каскада.
        self.reason = reason


# ── Задача 2 (2026-09-05): человекочитаемая причина embed/LLM-сбоя ─────────
# Статус извлекается из текста исключения (наши форматы: «HTTP 403»,
# «server error 502», «auth failed (401)», «status=429»…) или атрибута;
# затем классификация по типу/тексту. Русская строка — для WARNING-логов
# воркера и печати в консоли вместо голого исключения.

_HTTP_STATUS_IN_MSG_RE = re.compile(
    r"\b(?:HTTP\s+|server error |auth failed \(|status=|rate limited \()(\d{3})\b")
_EMBED_TIMEOUT_RE = re.compile(
    r"timed? ?out|timeout|таймаут|завис", re.IGNORECASE)
_EMBED_TRANSPORT_RE = re.compile(
    r"transport|транспорт|соединение|connect|read error|недоступ", re.IGNORECASE)


def _embed_error_status(exc: BaseException) -> int | None:
    """HTTP-статус причины из атрибута исключения либо его текста."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and 100 <= status < 1000:
        return status
    match = _HTTP_STATUS_IN_MSG_RE.search(str(exc))
    return int(match.group(1)) if match else None


def humanize_embed_error(exc: BaseException) -> str:
    """Понятная русская причина embed/LLM-сбоя: 401/403/429/5xx по
    статус-коду из текста/атрибутов исключения, затем таймаут/транспорт/
    битый ответ по типу и тексту. Незнакомое → общая строка (тип/код
    остаются в тексте исходного исключения, если он печатается рядом)."""
    status = _embed_error_status(exc)
    if status == 401:
        return ("Ключ API не принят (401) — проверьте LLM_API_KEY и запасные "
                "ключи эмбеддинга (EMBEDDING_FALLBACK_API_KEY(_2)) в .env")
    if status == 403:
        return ("Доступ запрещён (403): квота исчерпана или ключ без прав на "
                "эмбеддинги — пробуется запасной ключ; если исчерпаны все "
                "ключи — проверьте их в .env")
    if status == 429:
        return ("Рейт-лимит (429) — воркер ждёт и повторит; если повторяется "
                "часто — снизьте --embed-concurrency")
    if status is not None and 500 <= status < 600:
        return "Облачный API нестабилен (5xx) — повтор с паузой"
    text = str(exc)
    name = type(exc).__name__.lower()
    if (isinstance(exc, (httpx.TimeoutException, TimeoutError))
            or "timeout" in name or _EMBED_TIMEOUT_RE.search(text)):
        return "Таймаут облачного API — повтор с паузой"
    if (isinstance(exc, httpx.TransportError)
            or "transport" in name or _EMBED_TRANSPORT_RE.search(text)):
        return "Сеть недоступна — проверьте соединение"
    if "json" in text.lower() or "data[].embedding" in text \
            or "вернул" in text.lower():
        return ("Ответ API не распознан (битый JSON, нет data[].embedding "
                "или неверное число векторов в ответе)")
    if status is not None and 400 <= status < 500:
        return (f"API отклонил запрос (HTTP {status}) — проверьте "
                f"конфигурацию/модель (.env EMBEDDING_*)")
    return "Облачный API недоступен — см. детали выше"


def humanize_history_llm_error(exc: BaseException) -> str:
    """Понятная русская причина сбоя ЛОКАЛЬНОЙ LLM Graph-этапа: HTTP-статус
    Ollama, транспорт, пустой content (думание), неразобранный JSON-факт.
    ОТДЕЛЬНО от humanize_embed_error (та — для EmbedError и ТОЛЬКО про
    эмбеддинги: data[].embedding/число векторов; сюда её слова не текут)."""
    text = str(exc)
    status = _embed_error_status(exc)
    if status is not None and 500 <= status < 600:
        return (f"Ollama нестабильна (HTTP {status}) — проверьте процесс "
                f"/ модель (ollama serve)")
    if (isinstance(exc, (httpx.TimeoutException, TimeoutError))
            or _EMBED_TIMEOUT_RE.search(text)
            or _EMBED_TRANSPORT_RE.search(text)):
        return ("Ollama недоступна — проверьте ollama serve и эндпоинт "
                "--endpoint")
    if "пустой content" in text or "думание" in text:
        return ("модель вернула пустой ответ — похоже, думание qwen3.5 не "
                "выключено (попробуйте --think-off-mode reasoning_effort)")
    if "json" in text.lower() or "фактов" in text.lower() \
            or "разобрать" in text.lower() or "content" in text.lower():
        return ("Ответ модели не удалось разобрать как список фактов — "
                "пачка пропущена и будет повторена")
    if status is not None and status >= 400:
        return (f"Ollama отклонила запрос (HTTP {status}) — проверьте "
                f"название модели --model")
    return ("Локальная LLM недоступна/стабильно отвечает ошибкой — "
            "проверьте Ollama и формат ответа модели")


# ── Парсинг ответа LLM ───────────────────────────────────────────────

# Ключи-конверты {{"facts"|"fact"|"data"|"result": […]}} — модели часто
# оборачивают список фактов (или одиночный факт) в объект (В т.ч. qwen).
_WRAPPER_KEYS = ("facts", "fact", "data", "result")


def _clean_str(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _item_fact(item) -> dict | str | None:
    """Элемент списка фактов: триплет {subject,predicate,object,context?} →
    валидный dict (пустые триплеты → None); объект со строковым ключом
    "fact" → строка-факт целиком («устойчивость» к qwen-сюрпризу: модель
    может вернуть {"fact": "…"} вместо триплета)."""
    if isinstance(item, dict):
        fact = item.get("fact")
        if isinstance(fact, str):
            cleaned = _clean_str(fact)
            return cleaned or None
        return _validate_history_fact(item)
    if isinstance(item, str):
        cleaned = _clean_str(item)
        return cleaned or None
    return None


def _validate_history_fact(item) -> dict | None:
    """Валидация триплета {subject, predicate, object, context?}: строки,
    нормализация пробелов, капсы (как live _validate_fact, summary_memory.py:
    392-415, но context ≤200 симв — HISTORY_MAX_CONTEXT_CHARS); subject ==
    object → отсев; сленг/мат сохраняется как есть (без casefold)."""
    if not isinstance(item, dict):
        return None
    try:
        subject, predicate, obj = (item["subject"], item["predicate"],
                                   item["object"])
    except (KeyError, TypeError):
        return None
    if not all(isinstance(v, str) for v in (subject, predicate, obj)):
        return None
    norm_s = re.sub(r"\s+", " ", str(subject)).strip()
    norm_p = re.sub(r"\s+", " ", str(predicate)).strip()
    norm_o = re.sub(r"\s+", " ", str(obj)).strip()
    if not (norm_s and norm_p and norm_o):
        return None
    if (len(norm_s) > prompts.HISTORY_MAX_NAME_CHARS
            or len(norm_o) > prompts.HISTORY_MAX_NAME_CHARS):
        return None
    if len(norm_p) > prompts.HISTORY_MAX_PREDICATE_CHARS:
        return None
    if norm_s == norm_o:
        return None
    context = item.get("context")
    if context is not None and not isinstance(context, str):
        context = None
    ctx = re.sub(r"\s+", " ", str(context)).strip() if context else ""
    return {"subject": norm_s, "predicate": norm_p, "object": norm_o,
            "context": ctx[:prompts.HISTORY_MAX_CONTEXT_CHARS]}


def parse_facts_json(raw: str) -> list[dict | str]:
    """Устойчивый парсер ответа LLM (Graph-этап) — НИКОГДА не падает.

    Принимает ВСЕ разумные формы: (а) JSON-массив объектов; (б) конверт
    {{"facts"|"fact"|"data"|"result": […]}} — разворачивается (модели часто
    оборачивают); (в) объекты с ключом "fact" (строка) — факт целиком;
    (г) триплеты {{subject, predicate, object, context?}} — валидируются
    (как live _validate_fact; пустые/недостоверные поля → отсев);
    (д) ```json …``` фенс-обёртка снимается; (е) текст до/после массива —
    берётся первый '[' … последний ']'. Не-JSON/мусор → [] («нет фактов» —
    НЕ ошибка: пачка считается пустой, воркер продолжает; в отличие от
    старого поведения, TRUE-ошибок парсинга больше нет)."""
    if not raw:
        return []
    text = str(raw).strip()
    text = _JSON_FENCE_RE.sub("", text).strip()
    if not text:
        return []
    data = None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        pass
    if not isinstance(data, (dict, list)):
        # устойчивое извлечение массива: первый '[' … последний ']'
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except (ValueError, TypeError):
                data = None
    if isinstance(data, dict):
        for key in _WRAPPER_KEYS:
            if key in data:
                data = data[key]
                break
    if isinstance(data, str):
        cleaned = _clean_str(data)
        return [cleaned] if cleaned else []
    if isinstance(data, dict):
        fact = _item_fact(data)
        return [fact] if fact is not None else []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        fact = _item_fact(item)
        if fact is not None:
            out.append(fact)
    return out


def fact_sentence(triplet: dict) -> str:
    """Факт-строка graph_facts: «subject predicate object» (как live-путь
    summary_memory.py:1325; context в строку НЕ входит — он только для
    проверяемости в пачке)."""
    return f"{triplet['subject']} {triplet['predicate']} {triplet['object']}"


# ── Transport: локальная LLM (Ollama) ────────────────────────────────

def resolve_transport(endpoint: str, transport: str) -> str:
    """'auto' → 'openai', если endpoint оканчивается на '/v1' (Ollama
    OpenAI-совместимый), иначе 'ollama' (нативный /api/chat)."""
    if transport != "auto":
        return transport
    return "openai" if endpoint.rstrip("/").endswith("/v1") else "ollama"


def chat_url(endpoint: str, transport: str) -> str:
    """URL вызова: openai → {endpoint}/chat/completions; ollama → {host}
    /api/chat (host = endpoint без суффикса /v1)."""
    if transport == "ollama":
        host = endpoint.rstrip("/")
        if host.endswith("/v1"):
            host = host[:-len("/v1")]
        return host + "/api/chat"
    return endpoint.rstrip("/") + "/chat/completions"


def think_off_fields(think_off_mode: str) -> dict:
    """Поля отключения думания в теле запроса (Q5):
    'auto' (дефолт) — и think:False, и reasoning_effort:"none"
    (belt-and-suspenders — Ollama игнорирует лишнее);
    'reasoning_effort' — только OpenAI-стандартное поле;
    'ollama_chat' — только нативное think:False (как в /api/chat)."""
    if think_off_mode == "reasoning_effort":
        return dict(THINK_OFF_REASONING)
    if think_off_mode == "ollama_chat":
        return dict(THINK_OFF_THINK_FIELD)
    return dict(THINK_OFF_FIELDS)


class HistoryLLMClient:
    """Асинхронный клиент локального inference (сырой httpx POST — openai-
    пакет не обязателен, spec 3.1). transport: openai | ollama | auto."""

    def __init__(self, model: str, endpoint: str = "http://localhost:11434/v1",
                 transport: str = "auto", think_off_mode: str = "auto",
                 timeout: float = _LLM_TIMEOUT_S):
        self.model = model
        self.endpoint = endpoint
        self.transport = resolve_transport(endpoint, transport)
        self.think_off_mode = think_off_mode
        self.url = chat_url(endpoint, self.transport)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout), follow_redirects=True)
        self.retries = _LLM_TRANSPORT_RETRIES

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:  # pragma: no cover
            pass

    def _payload(self, messages: list[dict], max_facts: int) -> dict:
        system = prompts.HISTORY_EXTRACT_PROMPT.format(max_facts=max_facts)
        msgs = [{"role": "system", "content": system}, *messages]
        if self.transport == "ollama":
            return {
                "model": self.model,
                "messages": msgs,
                "stream": False,
                "think": False,
                "format": prompts.HISTORY_EXTRACT_SCHEMA,
                "options": {"temperature": 0, "num_ctx": 8192,
                            "num_predict": 1500},
            }
        payload = {
            "model": self.model,
            "messages": msgs,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        payload.update(think_off_fields(self.think_off_mode))
        return payload

    async def extract(self, user_content: str,
                      max_facts: int = MAX_FACTS_PER_BATCH_FLOOR) -> list[dict]:
        """Одна пачка: POST → парсинг триплетов. Ретраи: на транспорте —
        до self.retries (2) дополнительных попыток с backoff (недоступен/
        429/5xx/таймаут); при 200 с битым JSON/пустым content — до
        _LLM_JSON_RETRIES повторных попыток ТЕМ ЖЕ запросом (temperature
        НЕ меняем); после — HistoryLLMError (пачка к повторам след.
        запуска/скипу)."""
        payload = self._payload(
            [{"role": "user", "content": user_content}], max_facts=max_facts)
        json_left = _LLM_JSON_RETRIES
        last_exc: Exception | None = None
        for attempt in range(1 + self.retries):
            try:
                response = await self._client.post(self.url, json=payload)
                await response.aread()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = HistoryLLMError(
                    f"LLM транспорт недоступен (попытка {attempt + 1}): {exc}")
                logger.warning("history graph LLM: %s | url=%s", last_exc,
                               self.url)
                await self._sleep_backoff(attempt)
                continue
            if response.status_code in (408, 425, 429) or response.status_code >= 500:
                last_exc = HistoryLLMError(
                    f"LLM HTTP {response.status_code} (попытка {attempt + 1})")
                logger.warning("history graph LLM: %s | url=%s",
                               last_exc, self.url)
                await self._sleep_backoff(attempt)
                continue
            if response.status_code != 200:
                # 4xx (кроме ретраимых выше) — конфиг/модель: ретраить смысла нет
                raise HistoryLLMError(
                    f"LLM HTTP {response.status_code}: "
                    f"{response.text[:300]}")
            # HTTP 200: разбор ответа; битый JSON/пустой content — повтор
            # тем же запросом (json_left), транспортные ретраи НЕ тратятся
            try:
                content = self._response_content(response.json())
            except (ValueError, KeyError, TypeError) as exc:
                raise HistoryLLMError(
                    f"LLM ответ без content/не JSON: {exc}") from exc
            if content is None or _EMPTY_RE.match(content):
                # пустой content (думание не выключено: ответ мог уйти в
                # reasoning_content) — edge 8: детект + WARNING с подсказкой
                if self._usage_hint(response.json()):
                    logger.warning(
                        "history graph LLM: пустой content при ненулевом usage "
                        "— похоже, думание qwen3.5 не выключено; подсказки: "
                        "--think-off-mode reasoning_effort | ollama_chat | "
                        "модель без думания (qwen3:14b)")
                if json_left > 0:
                    json_left -= 1
                    logger.warning(
                        "history graph LLM: пустой content — повторная попытка "
                        "тем же запросом")
                    continue
                raise HistoryLLMError(
                    "LLM пустой content после ретраев (думание не выключено?)")
            try:
                return parse_facts_json(content)
            except HistoryLLMError:
                if json_left > 0:
                    json_left -= 1
                    logger.warning(
                        "history graph LLM: битый JSON — повторная попытка "
                        "тем же запросом")
                    continue
                raise
        # исчерпаны транспорт-ретраи
        if last_exc is not None:
            raise last_exc
        raise HistoryLLMError("LLM недоступен: все попытки исчерпаны")

    @staticmethod
    def _response_content(data: dict) -> str | None:
        if not isinstance(data, dict):
            raise ValueError("response is not a dict")
        if "message" in data:                    # нативный /api/chat
            msg = data.get("message") or {}
            content = msg.get("content")
            if not content and msg.get("reasoning_content"):
                content = None
            return content if isinstance(content, str) else None
        choices = data.get("choices") or []      # OpenAI-совместимый
        if not choices:
            raise KeyError("no choices in response")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        return content if isinstance(content, str) else None

    @staticmethod
    def _usage_hint(data: dict) -> bool:
        """Признак «думание не выключено»: пустой content при ненулевом
        usage (spec edge 8) — подсказка юзеру."""
        try:
            usage = data.get("usage") or {}
            total = usage.get("total_tokens") or 0
            return int(total) > 0
        except (TypeError, ValueError):
            return False

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(
            min(_LLM_RETRY_BACKOFF * (2 ** attempt), 30.0)
            + random.uniform(0, 0.3))


# ── Transport: API-эмбеддинги (как бот: POST {base}/embeddings) ──────

class EmbedClient:
    """Маленький embed-хелпер на сыром httpx (LLMClient бота не поднимаем —
    воркер без крон-сервисов; контракт тот же: POST /embeddings →
    data[].embedding, dim 3072 gemini-embedding-001 из .env ноутбука).
    Батчинг: тексты режутся на _EMBED_BATCH_SIZE и шлются конкурентно
    (semaphore --embed-concurrency); на 300k фактов × ~40 токенов такой
    режим ≈ параллель × одиночная латентность (NFR-5, ~$4–10)."""

    def __init__(self, base_url: str | None = None,
                 api_key: str | None = None, model: str | None = None,
                 concurrency: int = DEFAULT_EMBED_CONCURRENCY,
                 batch_size: int = _EMBED_BATCH_SIZE,
                 timeout: float = _EMBED_TIMEOUT_S,
                 max_retries: int = _EMBED_MAX_RETRIES,
                 embed_fallback_base_url: str | None = None,
                 embed_fallback_api_key: str | None = None,
                 embed_fallback_model: str | None = None,
                 embed_fallback_api_key_2: str | None = None):
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.LLM_API_KEY
        self.model = model or settings.EMBEDDING_MODEL_NAME
        self.concurrency = max(1, int(concurrency))
        self.batch_size = max(1, int(batch_size))
        self.timeout = timeout
        self.max_retries = max_retries
        self.url = f"{self.base_url}/embeddings"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout), follow_redirects=True)
        self._sem = asyncio.Semaphore(self.concurrency)
        # Embed-фоллбэк EMBEDDING_FALLBACK_* (как LLMClient бота): попытки на
        # фоллбэке после EmbedError primary. Активен ТОЛЬКО при base_url +
        # >=1 ключе; пустая модель → primary embed-модель. Задача 1: каскад
        # ключей [key1, key2, …] (пустые отбрасываются; R17: значения ключей
        # НИКОГДА не логируются).
        self._fb_base_url = (
            settings.EMBEDDING_FALLBACK_BASE_URL
            if embed_fallback_base_url is None else embed_fallback_base_url
        ).rstrip("/") or ""
        self._fb_api_key = (
            settings.EMBEDDING_FALLBACK_API_KEY
            if embed_fallback_api_key is None else embed_fallback_api_key
        ) or ""
        fb_key_2 = (
            settings.EMBEDDING_FALLBACK_API_KEY_2
            if embed_fallback_api_key_2 is None else embed_fallback_api_key_2
        ) or ""
        self._fb_api_keys = [key for key in (self._fb_api_key, fb_key_2)
                             if key]
        self._fb_model = (
            (settings.EMBEDDING_FALLBACK_MODEL
             if embed_fallback_model is None else embed_fallback_model)
            or ""
        ).strip() or self.model
        self._fb_url = (f"{self._fb_base_url}/embeddings"
                        if self._fb_base_url else "")
        self._fb_active = bool(self._fb_base_url) and bool(self._fb_api_keys)
        self._fb_client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:  # pragma: no cover
            pass
        if self._fb_client is not None:
            try:
                await self._fb_client.aclose()
            except Exception:  # pragma: no cover
                pass
            self._fb_client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Векторы для текстов в ИСХОДНОМ порядке. Ретраи внутри чанка
        (429/5xx/транспорт); фатальные 4xx/битый ответ → EmbedError."""
        if not texts:
            return []
        clean = [str(t) for t in texts]
        chunks = [clean[i:i + self.batch_size]
                  for i in range(0, len(clean), self.batch_size)]
        results = await asyncio.gather(
            *(self._embed_chunk(chunk) for chunk in chunks))
        return [vector for chunk in results for vector in chunk]

    async def _embed_chunk(self, chunk: list[str]) -> list[list[float]]:
        """Чанк: primary (ретраи 429/5xx/транспорт) → EmbedError → КАСКАД
        ключей embed-фоллбэка (EMBEDDING_FALLBACK_*; одна попытка на ключ,
        Bearer ключа — заголовком конкретного запроса); фейл всех ключей →
        EmbedError «embed primary+fallback failed | primary: … | fallback: …»
        (причины по ключам; пачка НЕ помечается — факты остаются текстом,
        no_vec)."""
        async with self._sem:
            try:
                return await self._embed_chunk_primary(chunk)
            except EmbedError as primary_exc:
                if not self._fb_active:
                    raise
                primary_desc = f"{type(primary_exc).__name__}: {primary_exc}"
                per_key_desc: list[str] = []
                for idx, key in enumerate(self._fb_api_keys):
                    fb_resp = None
                    fb_desc = "no-response"
                    try:
                        fb_resp = await self._post_embed_fallback(chunk,
                                                                  api_key=key)
                    except Exception as fb_exc:
                        fb_desc = f"{type(fb_exc).__name__}: {fb_exc}"
                    if fb_resp is not None and fb_resp.status_code == 200:
                        try:
                            data = fb_resp.json()
                            vectors = [item["embedding"]
                                       for item in data["data"]]
                        except (ValueError, KeyError, TypeError) as parse_exc:
                            fb_desc = f"bad response: {parse_exc}"
                            per_key_desc.append(fb_desc)
                            logger.warning(
                                "history graph: embed fallback key %d failed "
                                "| %s", idx, fb_desc)
                            continue
                        if len(vectors) != len(chunk):
                            fb_desc = (
                                f"embed fallback вернул {len(vectors)} "
                                f"векторов на {len(chunk)} текстов")
                            per_key_desc.append(fb_desc)
                            logger.warning(
                                "history graph: embed fallback key %d failed "
                                "| %s", idx, fb_desc)
                            continue
                        logger.info(
                            "history graph: embed fallback OK | model=%s | "
                            "primary_error=%s | key_idx=%d",
                            self._fb_model, primary_desc, idx)
                        return vectors
                    if fb_resp is not None and fb_resp.status_code != 200:
                        fb_desc = f"status={fb_resp.status_code}"
                    per_key_desc.append(fb_desc)
                    logger.warning(
                        "history graph: embed fallback key %d failed | %s",
                        idx, fb_desc)
                if len(per_key_desc) == 1:
                    fb_summary = per_key_desc[0]
                else:
                    fb_summary = "; ".join(
                        f"key{i}={desc}" for i, desc in enumerate(per_key_desc))
                human_reason = humanize_embed_error(primary_exc)
                logger.warning(
                    "history graph: embed fallback failed | primary=%s | "
                    "fallback=%s", primary_desc, fb_summary)
                # Задача 2: человеческое объяснение + рекомендация паузы
                # (прогресс пишется по факту обработанных пачек).
                logger.warning(
                    "history graph: embed fallback exhausted — %s. Процесс "
                    "можно поставить на паузу: Ctrl+C — прогресс сохранён, "
                    "повторный запуск продолжит с чекпоинта", human_reason)
                raise EmbedError(
                    "embed primary+fallback failed | "
                    f"primary: {primary_desc} | fallback: {fb_summary}",
                    reason=human_reason,
                ) from primary_exc

    async def _post_embed_fallback(self, chunk: list[str],
                                   api_key: str) -> httpx.Response:
        """РОВНО одна попытка POST {fb}/embeddings; Bearer <api_key> ключа
        каскада — заголовок конкретного запроса (клиент общий, без auth)."""
        client = self._get_fb_client()
        headers = {"Authorization": f"Bearer {api_key}"}
        response = await client.post(
            self._fb_url,
            json={"model": self._fb_model, "input": chunk},
            headers=headers)
        await response.aread()
        return response

    def _get_fb_client(self) -> httpx.AsyncClient:
        """Ленивый ОБЩИЙ клиент embed-фоллбэка БЕЗ auth: ключ каскада —
        заголовком каждого запроса (_post_embed_fallback), один клиент
        переиспользуется всеми ключами."""
        if self._fb_client is None:
            self._fb_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout), follow_redirects=True)
        return self._fb_client

    async def _embed_chunk_primary(self, chunk: list[str]) -> list[list[float]]:
        """Ретраи внутри чанка (429/5xx/транспорт); фатальные 4xx/битый ответ
        → EmbedError. Семафор держит вызывающий _embed_chunk."""
        last_exc: Exception | None = None
        for attempt in range(1 + self.max_retries):
            try:
                response = await self._client.post(
                    self.url,
                    json={"model": self.model, "input": chunk},
                    headers=self._headers())
                await response.aread()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = EmbedError(
                    f"embed транспорт недоступен (попытка {attempt + 1}): "
                    f"{exc}")
                await self._sleep_backoff(attempt)
                continue
            if response.status_code in (408, 425, 429) or response.status_code >= 500:
                last_exc = EmbedError(
                    f"embed HTTP {response.status_code} "
                    f"(попытка {attempt + 1})")
                await self._sleep_backoff(attempt)
                continue
            if response.status_code != 200:
                raise EmbedError(
                    f"embed HTTP {response.status_code}: "
                    f"{response.text[:300]}")
            try:
                data = response.json()
                vectors = [item["embedding"] for item in data["data"]]
            except (ValueError, KeyError, TypeError) as exc:
                raise EmbedError(
                    f"embed ответ без data[].embedding: {exc}") from exc
            if len(vectors) != len(chunk):
                raise EmbedError(
                    f"embed вернул {len(vectors)} векторов на "
                    f"{len(chunk)} текстов — повторная попытка")
            return vectors
        if last_exc is not None:
            raise last_exc
        raise EmbedError("embed недоступен: все попытки исчерпаны")

    def _headers(self) -> dict:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def _sleep_backoff(self, attempt: int) -> None:
        await asyncio.sleep(
            min(2.0 * (2 ** attempt), 30.0) + random.uniform(0, 0.3))


# ── Vec: чтение схемы снапшота + запись (как summary_memory:1011-1027) ──

def _vec_dim_from_ddl(sql: str) -> int | None:
    match = re.search(r"float\[(\d+)\]", sql)
    return int(match.group(1)) if match else None


async def _load_vec_extension(conn) -> bool:
    """sqlite-vec в соединение (как summary_memory.initialize :597-609).
    Возвращает False при недоступности расширения (vec-путь отключён)."""
    try:
        import sqlite_vec
        await conn.enable_load_extension(True)
        try:
            await conn.load_extension(sqlite_vec.loadable_path())
        finally:
            try:
                await conn.enable_load_extension(False)
            except Exception:
                pass
        return True
    except Exception:
        logger.warning("history graph: sqlite-vec недоступен — факты пойдут "
                       "текстом/FTS (vec отложен)", exc_info=True)
        return False


async def _insert_vec_row(conn, fact_id: int, chat_id: int, fact: str,
                          origin: str, expires_at, vector: list[float],
                          use_int8: bool) -> None:
    """INSERT vec-строки (rowid=fact_id) — SQL-образец summary_memory.
    _insert_graph_vec_row (float+int8; json.dumps вектора)."""
    if use_int8:
        await conn.execute(
            "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
            "expires_at, embedding, embedding_i8) VALUES (?, ?, ?, ?, ?, ?, "
            "vec_quantize_int8(?, 'unit'))",
            (fact_id, fact_id, chat_id, origin, expires_at,
             json.dumps(vector), json.dumps(vector)))
    else:
        await conn.execute(
            "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
            "expires_at, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (fact_id, fact_id, chat_id, origin, expires_at,
             json.dumps(vector)))


class GraphWorker:
    """Воркер --mode graph (T-761..T-763): сырьё smart_messages →
    факты history_import (+FTS+vec). Работает ТОЛЬКО на снапшоте БД.

    Экземпляр держит session-кэш embed-векторов {текст: вектор} — один и тот
    же текст в прогоне не эмбеддится дважды (edge 9)."""

    def __init__(self, db_path: str, *,
                 llm: "HistoryLLMClient | None" = None,
                 embed_client: EmbedClient | None = None,
                 chat_id: int = -1002661910336,
                 batch_size: int = DEFAULT_BATCH_SIZE,
                 fact_density: float = DEFAULT_FACT_DENSITY,
                 min_fact_chars: int = DEFAULT_MIN_FACT_CHARS,
                 embed_mode: str = "api",   # api|skip
                 skip_errors: bool = False,
                 llm_failures_before_stop: int = LLM_FAILURES_BEFORE_STOP,
                 progress=None):
        self.db_path = db_path
        self.llm = llm
        self.embed_client = embed_client
        self.chat_id = chat_id
        self.batch_size = max(1, int(batch_size))
        self.density = max(0.01, min(1.0, float(fact_density)))
        self.min_fact_chars = max(0, int(min_fact_chars))
        self.embed_mode = embed_mode if embed_mode in ("api", "skip") else "api"
        self.skip_errors = skip_errors
        # защита «модель стабильно отвечает ошибкой»: N ошибок пачек ПОДРЯД
        # без --skip-errors → стоп (пачки НЕ помечены — повторятся след.
        # запуском); 1–2 ошибки — просто пропуск и продолжение.
        self.llm_failures_before_stop = max(1, int(llm_failures_before_stop))
        self.progress = progress
        # K-шаг density-семплизации (детерминированный модуль id).
        # Код-обоснование: K = round(1/density) — сообщение участвует в
        # пачках, если (id % K) == 0 → ~каждое K-е; density 0.15 → K=7
        # (пачка 25 ≈ 25 выбранных на ~25×7 строк импорта, пропуская 6 из
        # 7). id не подряд после дедупа импорта и НЕ коррелирует с ts
        # (FTS-импорт «свежим первым») — модуль лишь приближение к
        # «каждому K-му» (приемлемо: детерминизм семплизации + keyset-
        # resume по (timestamp, id) без потерь; см. _fetch_batch).
        self.k_step = max(1, min(1000, int(round(1.0 / self.density))))
        self.max_facts_per_batch = max(
            MAX_FACTS_PER_BATCH_FLOOR, int(round(self.batch_size * self.density)))
        # замеры/счётчики
        self.stats = {
            "batches": 0, "selected_msgs": 0, "facts_inserted": 0,
            "facts_ignored_dupes": 0, "no_vec": 0, "llm_errors": 0,
            "swept": 0,
        }
        self.vec = {"active": False, "int8": False, "dim": None,
                    "reason": "vec не задействован"}
        self._embed_cache: dict[str, list[float]] = {}
        self._svc = None

    # ── подготовка ──────────────────────────────────────────────────
    async def open(self) -> None:
        """Миграции v1..v7 (DatabaseService.initialize — идемпотентно) +
        загрузка sqlite-vec + само-проверка dim вектора (spec 3.5)."""
        from services.database import DatabaseService
        self._svc = DatabaseService(self.db_path)
        await self._svc.initialize()
        await self._probe_vec()

    async def close(self) -> None:
        if self._svc is not None:
            try:
                await self._svc.close()
            except Exception:
                pass
            self._svc = None

    async def _probe_vec(self) -> None:
        """vec-путь: sqlite-vec + graph_facts_vec в снапшоте + embed API.
        Расхождение dim таблицы и dim эмбеддинга — fail-fast (spec 3.5);
        недоступность расширения/таблицы/API → vec отключён (факты остаются
        ТЕКСТОМ, счётчик no_vec — деградация как боевая)."""
        self.vec = {"active": False, "int8": False, "dim": None,
                    "reason": "vec не задействован"}
        if self.embed_mode != "api":
            self.vec["reason"] = "--embed-mode skip"
            return
        if self.embed_client is None:
            self.vec["reason"] = "embed-клиент не задан"
            return
        cursor = await self._svc.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='graph_facts_vec'")
        row = await cursor.fetchone()
        if row is None or not row["sql"]:
            self.vec["reason"] = "в снапшоте нет graph_facts_vec"
            return
        stored_dim = _vec_dim_from_ddl(row["sql"])
        int8 = "embedding_i8" in row["sql"]
        if stored_dim is None:
            self.vec["reason"] = "не удалось прочитать dim из DDL vec-таблицы"
            return
        if not await _load_vec_extension(self._svc.db):
            self.vec["reason"] = "sqlite-vec расширение недоступно"
            return
        # пробник API: dim ответа == dim таблицы (иначе fail-fast)
        try:
            vectors = await self.embed_client.embed([_EMBED_PROBE_TEXT])
            api_dim = len(vectors[0]) if vectors and vectors[0] else 0
        except EmbedError as exc:
            logger.warning("history graph: embed probe failed — vec отложен "
                           "(факты текстом); error=%s", exc)
            self.vec["reason"] = "embed probe failed"
            return
        if api_dim != stored_dim:
            raise HistoryLLMError(
                f"dim-расхождение vec0-таблицы снапшота: таблица "
                f"graph_facts_vec float[{stored_dim}], API-эмбеддинг вернул "
                f"{api_dim} (EMBEDDING_MODEL_NAME/EMBEDDING_DIM в .env?) — "
                f"fail-fast по spec 3.5")
        self.vec = {"active": True, "int8": int8, "dim": stored_dim,
                    "reason": ""}
        logger.info("history graph: vec готов | dim=%d | int8=%s",
                    stored_dim, int8)

    # ── сырьё ───────────────────────────────────────────────────────
    async def pending_count(self) -> int:
        """Кандидатов к обработке: с import_key, не обработанные, текст
        ≥ min_fact_chars (без density-фильтра — для dry-run/ETA)."""
        cursor = await self._svc.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages WHERE chat_id = ? "
            "AND import_key IS NOT NULL AND history_processed = 0 "
            "AND length(text) >= ?",
            (self.chat_id, self.min_fact_chars))
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def pending_selected_count(self) -> int:
        """…с density-шагом (id % K == 0) — это ровно то, что воркер
        отправит в LLM (прогресс/ETA)."""
        cursor = await self._svc.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages WHERE chat_id = ? "
            "AND import_key IS NOT NULL AND history_processed = 0 "
            f"AND (id % {self.k_step}) = 0 AND length(text) >= ?",
            (self.chat_id, self.min_fact_chars))
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def _fetch_batch(self) -> list:
        """25 следующих кандидатов в хронологическом порядке ((timestamp, id)
        ASC). Keyset-курсор прогона — кортеж (timestamp, id) ПОСЛЕДНЕЙ строки
        предыдущей пачки (`(timestamp, id) > (?, ?)` — SQLite row-value),
        НЕ id-диапазон: FTS-импорт идёт «свежим первым» — низкие id у новых
        ts, старые ts на высоких id, оконная пометка [cursor..hi] пометила бы
        весь импорт БЕЗ экстракции (см. _mark_batch_processed). Пропуски
        density (id % K != 0) и короткие тексты в выборку не попадают никогда
        — их добивает _sweep_remaining в конце полного прогона."""
        sql = (
            "SELECT id, chat_id, user_id, text, timestamp, author_name "
            "FROM smart_messages WHERE chat_id = ? "
            "AND import_key IS NOT NULL AND history_processed = 0 "
            f"AND (id % {self.k_step}) = 0 AND length(text) >= ? "
        )
        params: list = [self.chat_id, self.min_fact_chars]
        if self._cursor is not None:
            sql += "AND (timestamp, id) > (?, ?) "
            params.extend(self._cursor)
        sql += "ORDER BY timestamp ASC, id ASC LIMIT ?"
        params.append(self.batch_size)
        cursor = await self._svc.db.execute(sql, params)
        return await cursor.fetchall()

    async def _mark_batch_processed(self, batch: list) -> None:
        """Пометить обработанными ТОЛЬКО фактически обработанные строки
        пачки (`UPDATE … WHERE id IN (…)` — НЕ диапазон id). Только import-
        строки чата (live/чужие чаты не трогаем — они и так не кандидаты).
        Keyset-курсор: (timestamp, id) последней строки пачки — следующий
        fetch строго «больше», пропущенных/непомеченных строк в прогоне
        курсор не обгоняет (resume-безопасно)."""
        if not batch:
            return
        ids = [int(row["id"]) for row in batch]
        placeholders = ",".join("?" for _ in ids)
        await self._svc.db.execute(
            f"UPDATE smart_messages SET history_processed = 1 "
            f"WHERE chat_id = ? AND import_key IS NOT NULL "
            f"AND id IN ({placeholders})",
            [self.chat_id, *ids])
        await self._svc.db.commit()
        last = batch[-1]
        self._cursor = (int(last["timestamp"]), int(last["id"]))

    async def _sweep_remaining(self) -> int:
        """Финал ПОЛНОГО прогона (без ошибок и без --limit): оставшиеся
        непомеченные import-строки — density-пропуски (id % K != 0) и
        короткие тексты (длина < min_fact_chars); в выборку они не попадают
        НИКОГДА → помечаем, чтобы dry-run/прогресс были нулевыми и пачки
        не пересканировались. При ошибках прогона (llm_errors > 0) или
        --limit НЕ вызывается — непомеченные кандидаты должны повториться
        следующим запуском."""
        cursor = await self._svc.db.execute(
            "UPDATE smart_messages SET history_processed = 1 "
            "WHERE chat_id = ? AND import_key IS NOT NULL "
            "AND history_processed = 0", (self.chat_id,))
        await self._svc.db.commit()
        return cursor.rowcount

    async def _reset_processed(self) -> int:
        """--reset: переобработка всех импортированных строк чата (дубли
        фактов отсекаются частичным UNIQUE-индексом при вставке)."""
        cursor = await self._svc.db.execute(
            "UPDATE smart_messages SET history_processed = 0 "
            "WHERE chat_id = ? AND import_key IS NOT NULL", (self.chat_id,))
        await self._svc.db.commit()
        return cursor.rowcount

    # ── факты ───────────────────────────────────────────────────────
    async def _save_batch_facts(self, triples: list[dict],
                                message_ts: int) -> None:
        """Факты пачки: INSERT OR IGNORE (дубль → 0, не ошибка) + FTS (внутри
        insert_graph_fact) + vec (--embed-mode api). no_vec — embed фейлы."""
        conn = self._svc.db
        texts_to_embed: list[str] = []
        for triplet in triples:
            if isinstance(triplet, str):
                # факт-строка целиком ({"fact": "…"} из ответа LLM)
                fact = triplet.strip()
                if not fact:
                    continue
            else:
                fact = fact_sentence(triplet)
            fact_id = await self._svc.insert_graph_fact(
                chat_id=self.chat_id, fact=fact, origin="history_import",
                expires_at=None, target_user=None, weight=HISTORY_IMPORT_WEIGHT,
                status="confirmed", message_timestamp=message_ts,
                or_ignore=True)
            if fact_id == 0:
                self.stats["facts_ignored_dupes"] += 1
                continue
            self.stats["facts_inserted"] += 1
            if self.vec["active"] and self.embed_mode == "api":
                texts_to_embed.append(fact)
        if not texts_to_embed:
            return
        vectors = await self._embed_many(texts_to_embed)
        for fact, vector in zip(texts_to_embed, vectors):
            if vector is None:
                self.stats["no_vec"] += 1
                continue
            fact_id = await self._fact_id_for_inserted(fact, message_ts)
            if fact_id is None:
                continue   # строка ушла (удаление/rollback) — не наша забота
            try:
                await _insert_vec_row(conn, fact_id, self.chat_id, fact,
                                      "history_import", None, vector,
                                      self.vec["int8"])
            except Exception:
                self.stats["no_vec"] += 1
                logger.warning("history graph: vec-insert failed (fact "
                               "остался текстом)", exc_info=True)

    async def _fact_id_for_inserted(self, fact: str,
                                    message_ts: int) -> int | None:
        """rowid свежевставленного факта (после OR IGNORE-дублей возможен
        рассинхрон факт↔последний lastrowid — ищем по UNIQUE-тройке)."""
        cursor = await self._svc.db.execute(
            "SELECT id FROM graph_facts WHERE chat_id = ? AND fact = ? "
            "AND message_timestamp = ? AND origin = 'history_import'",
            (self.chat_id, fact, message_ts))
        row = await cursor.fetchone()
        return int(row["id"]) if row else None

    async def _embed_many(self, texts: list[str]) -> list:
        """Векторы текстов (порядок сохранён); None = фейл эмбеддинга.
        Session-кэш текст→вектор (edge 9); embed-фейл не роняет пачку —
        факт остаётся текстом (деградация как боевая)."""
        out: list = []
        todo: list[tuple[int, str]] = []
        for index, text in enumerate(texts):
            cached = self._embed_cache.get(text)
            if cached is not None:
                out.append((index, cached))
            else:
                todo.append((index, text))
        if todo:
            try:
                vectors = await self.embed_client.embed(
                    [t for _, t in todo])
            except EmbedError as exc:
                # Задача 2: человекочитаемая причина (403/429/сеть/…)
                logger.warning(
                    "history graph: embed batch failed — %d фактов останутся "
                    "текстом (no_vec); reason=%s",
                    len(todo),
                    exc.reason or humanize_embed_error(exc))
                vectors = [None] * len(todo)
            for (index, text), vector in zip(todo, vectors):
                if vector:
                    self._embed_cache[text] = vector
                    out.append((index, vector))
                else:
                    out.append((index, None))
        ordered = [None] * len(texts)
        for index, value in out:
            ordered[index] = value
        return ordered

    # ── главный цикл ────────────────────────────────────────────────
    async def run(self, limit_batches: int = 0, reset: bool = False) -> dict:
        """Обработка до исчерпания кандидатов (или --limit N пачек).
        Возвращает отчёт-статистику (пачки/факты/ошибки/no_vec/…)."""
        started = time.monotonic()
        await self.open()
        if reset:
            await self._reset_processed()
        total = await self.pending_selected_count()
        self.stats["total_selected"] = total
        if self.progress is not None:
            try:
                self.progress.total = total
                self.progress.refresh()
            except Exception:
                pass
        limit = int(limit_batches) if limit_batches else 0
        self._cursor: tuple[int, int] | None = None
        completed = False
        # Задача «не-фатальность пачек»: ошибка пачки — WARNING + пропуск
        # (без пометки), счётчик ПОДРЯД; N подряд (без --skip-errors) — стоп.
        consecutive_errors = 0
        try:
            while True:
                batch = await self._fetch_batch()
                if not batch:
                    completed = True
                    break
                if limit and self.stats["batches"] >= limit:
                    completed = False
                    break
                n = len(batch)
                self.stats["batches"] += 1
                self.stats["selected_msgs"] += n
                ok, batch_exc = await self._process_batch(batch)
                if ok:
                    consecutive_errors = 0
                    # факты записаны — помечаем ТОЛЬКО строки пачки
                    # (id IN; resume без потерь/дублей)
                    await self._mark_batch_processed(batch)
                else:
                    # пропуск (без пометки): двигаем курсор дальше, след.
                    # запуск (курсор сбрасывается) повторит упавшую пачку
                    consecutive_errors += 1
                    last = batch[-1]
                    self._cursor = (int(last["timestamp"]), int(last["id"]))
                    if (not self.skip_errors
                            and consecutive_errors
                            >= self.llm_failures_before_stop):
                        reason = (humanize_history_llm_error(batch_exc)
                                  if batch_exc is not None
                                  else "ошибка LLM-этапа (без деталей)")
                        stop = HistoryLLMError(
                            f"модель стабильно отвечает ошибкой "
                            f"({consecutive_errors} пачек подряд: {reason}) "
                            f"— проверьте Ollama и формат ответа, затем "
                            f"перезапустите: прогресс сохранён, упавшие "
                            f"пачки НЕ помечены и будут повторены")
                        # человекочитаемая причина (печать в manage.py)
                        stop.reason = (
                            f"стоп: {consecutive_errors} ошибок LLM подряд. "
                            f"{reason} — проверьте Ollama и формат ответа, "
                            f"затем перезапустите: прогресс сохранён")
                        raise stop
                if self.stats["batches"] % _WORKER_LOG_EVERY_BATCHES == 0:
                    elapsed = time.monotonic() - started
                    msg_rate = (self.stats["selected_msgs"] / max(1.0, elapsed)
                                if elapsed else 0.0)
                    remaining = max(0, total - self.stats["selected_msgs"])
                    eta = remaining / msg_rate if msg_rate else 0.0
                    logger.info(
                        "history graph: пачек=%d | msgs=%d | фактов=%d | "
                        "dupes=%d | no_vec=%d | llm_errors=%d | "
                        "msg/s=%.1f | ETA≈%.0fс",
                        self.stats["batches"], self.stats["selected_msgs"],
                        self.stats["facts_inserted"],
                        self.stats["facts_ignored_dupes"], self.stats["no_vec"],
                        self.stats["llm_errors"], msg_rate, eta)
                if self.progress is not None:
                    self.progress.update(n)
        finally:
            # полный прогон без ошибок → добить density-хвост; иначе (обрыв/
            # лимит/ошибки) — НЕ помечать (resume/повторы след. запуском)
            if completed and self.stats["llm_errors"] == 0:
                try:
                    self.stats["swept"] = await self._sweep_remaining()
                except Exception:
                    self.stats["swept"] = 0
            else:
                self.stats["swept"] = 0
            await self.close()
        if completed:
            # done = в истории НЕ осталось выбранных кандидатов (скип-пачки
            # --skip-errors не помечаются — прогон формально завершился, но
            # данные остались; done=False честно отражает «нужен ещё заход»)
            try:
                await self.open()
                left = await self.pending_selected_count()
                await self.close()
                completed = left == 0
            except Exception:
                completed = False
        self.stats["done"] = completed
        self.stats["duration"] = time.monotonic() - started
        self.stats["vec"] = dict(self.vec)
        self.stats["vec"]["reason"] = (self.vec["reason"] or "ok")
        return self.stats

    async def _process_batch(self, batch: list) -> tuple[bool, Exception | None]:
        """Пачка: LLM → факты (+vec). Возвращает (успех, ошибка):
        (True, None) — факты записаны, вызывающий помечает окно;
        (False, exc) — пачка пропущена: WARNING с человеческой причиной,
        НЕ помечена (повтор след. запуском), ПРОЦЕСС ПРОДОЛЖАЕТ (ошибка
        НЕ фатальна; стоп — только при N ошибках подряд в run())."""
        try:
            user_content = prompts.build_history_user_prompt(batch)
            triples = await self.llm.extract(
                user_content, max_facts=self.max_facts_per_batch)
        except HistoryLLMError as exc:
            self.stats["llm_errors"] += 1
            reason = getattr(exc, "reason", None) \
                or humanize_history_llm_error(exc)
            logger.warning(
                "history graph: пачка %d пропущена: %s — будет повторена "
                "при следующем запуске (Ctrl+C безопасен)",
                self.stats["batches"], reason)
            return False, exc
        triples = triples[:self.max_facts_per_batch]
        await self._save_batch_facts(triples, message_ts=max(
            row["timestamp"] for row in batch))
        return True, None


async def run_vec_backfill(db_path: str, *, embed_client: EmbedClient,
                           chat_id: int = -1002661910336,
                           progress=None) -> dict:
    """--vec-backfill (spec 3.5 п.4): догонка векторов фактов history_import
    без vec-строки (`id NOT IN (SELECT rowid FROM graph_facts_vec)`) — после
    прогонов с --embed-mode skip. Пишет float+int8 как основной воркер."""
    started = time.monotonic()
    from services.database import DatabaseService
    svc = DatabaseService(db_path)
    cache: dict[str, list[float]] = {}
    report = {"vec_rows": 0, "no_vec": 0, "checked": 0, "duration": 0.0,
              "done": False}
    vec = {"active": False, "int8": False, "dim": None, "reason": ""}
    try:
        await svc.initialize()
        cursor = await svc.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='graph_facts_vec'")
        row = await cursor.fetchone()
        if row is None or not row["sql"]:
            report["done"] = True
            report["vec"] = {"active": False, "reason": "нет graph_facts_vec"}
            return report
        stored_dim = _vec_dim_from_ddl(row["sql"])
        vec["int8"] = "embedding_i8" in row["sql"]
        if stored_dim is None or not await _load_vec_extension(svc.db):
            report["vec"] = {"active": False,
                             "reason": "нет dim/расширения sqlite-vec"}
            return report
        vec["active"] = True
        vec["dim"] = stored_dim
        try:
            probe = await embed_client.embed([_EMBED_PROBE_TEXT])
            if len(probe[0]) != stored_dim:
                raise HistoryLLMError(
                    f"dim-расхождение: таблица float[{stored_dim}], "
                    f"API вернул {len(probe[0])} — см. .env EMBEDDING_DIM")
        except EmbedError:
            report["vec"] = {"active": False,
                             "reason": "embed probe failed"}
            return report
        while True:
            cursor = await svc.db.execute(
                "SELECT id, chat_id, fact, origin, expires_at FROM graph_facts "
                "WHERE origin = 'history_import' "
                "AND id NOT IN (SELECT fact_id FROM graph_facts_vec) "
                f"LIMIT {_VEC_BACKFILL_CHUNK}")
            rows = await cursor.fetchall()
            if not rows:
                break
            for start in range(0, len(rows), 10):
                chunk = rows[start:start + 10]
                texts = []
                for r in chunk:
                    cached = cache.get(r["fact"])
                    if cached is not None:
                        texts.append(None)
                    else:
                        texts.append(r["fact"])
                missing = [t for t in texts if t is not None]
                vectors = await embed_client.embed(missing) if missing else []
                index = 0
                for r in chunk:
                    report["checked"] += 1
                    vector = cache.get(r["fact"])
                    if vector is None:
                        vector = vectors[index] if index < len(vectors) else None
                        index += 1
                    if not vector:
                        report["no_vec"] += 1
                        continue
                    cache[r["fact"]] = vector
                    try:
                        await _insert_vec_row(
                            svc.db, r["id"], r["chat_id"], r["fact"],
                            r["origin"], r["expires_at"], vector, vec["int8"])
                        report["vec_rows"] += 1
                    except Exception:
                        report["no_vec"] += 1
                        logger.warning(
                            "history graph backfill: vec-insert failed для "
                            "fact_id=%s", r["id"], exc_info=True)
                await svc.db.commit()
            if progress is not None:
                progress.update(len(rows))
        report["done"] = True
        report["vec"] = dict(vec)
        report["vec"]["reason"] = "ok"
    finally:
        try:
            await svc.close()
        except Exception:
            pass
        try:
            await embed_client.aclose()
        except Exception:
            pass
    report["duration"] = time.monotonic() - started
    return report
