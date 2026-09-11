"""Раунд 10.6 (T-1210/A4/D4) — безопасный probe провайдеров для
`POST /api/llm/test`.

Тестирует ПЕРЕДАННЫЕ блоком `base_url`/`model`/`api_key` (можно до сохранения)
минимальным запросом. R17: `api_key` никогда не возвращается/не логируется,
тело ошибки санитизируется (без эха ключа). Никакого импорта тяжёлых
сервисов — только httpx (уже в стеке).

Контракт блоков:
  * chat-блоки: direct_main, direct_fallback, transcribe_openrouter,
    video_summary_openrouter (нужны base_url+model+key);
  * STT-блок: transcribe_groq — POST /audio/transcriptions (Whisper не
    chat-модель; chat-probe давал ложный error и красную карточку);
  * embeddings — требует base_url (UI не рендерит кнопку теста: base_url нет);
  * search_keys — НЕ требует base_url (ходит на фиксированные Exa/Tavily);
  * media_share — не сетевой: проверяет, что секрет задан;
  * checkup_betterstack — best-effort HTTP-probe хоста SQL API (вызывается
    только контрактом; UI-кнопки нет — настройки живут в Модуле 9).
`llm_guard` намеренно НЕ в KNOWN_BLOCKS: это не сетевой провайдер, а таймауты/
ретраи — UI не показывает кнопку «Проверить» для него.
"""
import logging

import httpx

logger = logging.getLogger(__name__)

# Блоки, которые шлют OpenAI-совместимый chat-запрос (нужен base_url).
_LLM_BLOCKS = frozenset({
    "direct_main", "direct_fallback", "transcribe_groq",
    "transcribe_openrouter", "video_summary_openrouter",
})
# Блоки эмбеддингов (нужен base_url).
_EMBEDDING_BLOCKS = frozenset({"embeddings"})
# Все допустимые блоки (UI §6.2 + контракт §6.3).
# MINOR-2: `search_keys:tavily`/`search_keys:exa` — раздельные пробы ключей.
KNOWN_BLOCKS = _LLM_BLOCKS | _EMBEDDING_BLOCKS | {
    "search_keys", "search_keys:tavily", "search_keys:exa",
    "media_share", "checkup_betterstack",
}

_TIMEOUT_SECONDS = 15.0


def sanitize_error(text: str | None, api_key: str | None) -> str:
    """Убирает ключ из текста ошибки и обрезает (R17 — без эха)."""
    msg = (text or "").strip()
    if api_key:
        msg = msg.replace(api_key, "***")
    # Обрезаем длинные HTML-простыни провайдера.
    if len(msg) > 300:
        msg = msg[:300] + "…"
    return msg or "ошибка провайдера"


def _bearer(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _safe_base(base_url: str) -> tuple[str, str | None]:
    """SSRF-минимум: только https; http разрешён ЛИШЬ для точных loopback-хостов.

    Хост определяется через ``urllib.parse.urlsplit`` (не префиксным
    `startswith`, который пропускал ``http://localhost.evil.com``).

    Возвращает (нормализованный base, ошибка|None)."""
    import urllib.parse
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return "", "не задан base_url"
    try:
        parts = urllib.parse.urlsplit(base)
    except ValueError:
        return base, "base_url должен начинаться с https://"
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if scheme == "https":
        return base, None
    # http — строго точный loopback-хост (не `localhost.evil.com`).
    if scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
        return base, None
    return base, "base_url должен начинаться с https://"


async def _post_json(client: httpx.AsyncClient, url: str, headers: dict,
                     body: dict) -> httpx.Response:
    return await client.post(url, headers=headers, json=body)


async def _post_multipart(client: httpx.AsyncClient, url: str, headers: dict,
                          data: dict, files: dict) -> httpx.Response:
    """multipart-запрос (STT-эндпоинт принимает файл, а не JSON)."""
    return await client.post(url, headers=headers, data=data, files=files)


def _silent_wav(seconds: float = 0.3, rate: int = 16000) -> bytes:
    """Минимальный валидный WAV с тишиной — полезная нагрузка STT-probe.

    Реальное `POST /audio/transcriptions` (Groq/Whisper) требует файл;
    пустой payload провайдеры часто отвергают. Тишина 0.3с безобидна и
    не расходует квоту на осмысленную расшифровку (ADR-109-3)."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


async def probe_openai(base_url: str, api_key: str = "", model: str = "",
                       kind: str = "chat",
                       timeout: float = _TIMEOUT_SECONDS) -> dict:
    """Единый минимальный probe провайдера (ADR-109-3).

    ``kind``:
      * ``chat`` → POST /chat/completions (max_tokens=1);
      * ``embeddings`` → POST /embeddings;
      * ``stt`` → POST /audio/transcriptions с минимальным WAV (Groq/Whisper;
        chat-модель whisper не поддерживает, поэтому chat-probe всегда падал).

    Возвращает ``{ok, status, http_status, latency_ms[, error]}`` со статусами
    ``ok | error | timeout | unreachable | not_configured``. Секреты не
    возвращаются (R17): тело ошибки санитизируется."""
    import time
    started = time.monotonic()

    def _res(ok: bool, status: str, http_status=None, error=None) -> dict:
        out = {
            "ok": ok,
            "status": status,
            "http_status": http_status,
            "latency_ms": int((time.monotonic() - started) * 1000.0),
        }
        if error:
            out["error"] = error
        return out

    base, base_error = _safe_base(base_url)
    if base_error:
        return _res(False, "not_configured", None, base_error)
    if not (api_key or "").strip():
        return _res(False, "not_configured", None, "ключ не задан")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if kind == "stt":
                resp = await _post_multipart(
                    client, f"{base}/audio/transcriptions", _bearer(api_key),
                    {"model": model},
                    {"file": ("probe.wav", _silent_wav(), "audio/wav")})
            elif kind == "embeddings":
                resp = await _post_json(
                    client, f"{base}/embeddings", _bearer(api_key),
                    {"model": model, "input": "ping"})
            else:
                resp = await _post_json(
                    client, f"{base}/chat/completions", _bearer(api_key),
                    {"model": model, "max_tokens": 1,
                     "messages": [{"role": "user", "content": "ping"}]})
    except httpx.TimeoutException as exc:
        return _res(False, "timeout", None, sanitize_error(str(exc), api_key))
    except httpx.HTTPError as exc:
        return _res(False, "unreachable", None,
                    sanitize_error(str(exc), api_key))
    except Exception as exc:   # защита от не-httpx сетевых ошибок
        return _res(False, "unreachable", None,
                    sanitize_error(str(exc), api_key))

    if resp.status_code < 400:
        return _res(True, "ok", resp.status_code)
    return _res(False, "error", resp.status_code,
                sanitize_error(resp.text, api_key))


async def probe_block(block: str, base_url: str = "", model: str = "",
                      api_key: str = "") -> dict:
    """Возвращает {"ok", "http_status", "latency_ms", "model"[, "error"]}."""
    import time
    started = time.monotonic()

    def _result(ok: bool, status, error=None) -> dict:
        out = {
            "ok": ok,
            "http_status": status,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "model": model,
        }
        if error:
            out["error"] = error
        return out

    if block not in KNOWN_BLOCKS:
        return _result(False, None, "неизвестный блок")

    # media_share — не сетевой LLM: проверяем, что секрет задан.
    if block == "media_share":
        if api_key:
            return _result(True, 200)
        return _result(False, None, "секрет подписи не задан")

    # MAJOR-1: search_keys НЕ требует base_url — ходит на фиксированные
    # Exa/Tavily; ветка обрабатывается ДО проверки base_url.
    # MINOR-2: суффикс `:tavily`/`:exa` тестирует КОНКРЕТНЫЙ ключ.
    if block.startswith("search_keys"):
        provider = None
        if ":" in block:
            provider = block.split(":", 1)[1]
            if provider not in ("tavily", "exa"):
                return _result(False, None, "неизвестный блок")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await _probe_search(client, (base_url or "").strip(),
                                           api_key, provider=provider)
        except httpx.HTTPError as exc:
            return _result(False, None, sanitize_error(str(exc), api_key))
        if resp.status_code < 400:
            return _result(True, resp.status_code)
        return _result(False, resp.status_code,
                       sanitize_error(resp.text, api_key))

    # checkup_betterstack — простой GET хоста (не OpenAI-совместимый).
    if block == "checkup_betterstack":
        base, base_error = _safe_base(base_url)
        if base_error:
            return _result(False, None, base_error)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.get(base, headers=_bearer(api_key))
        except httpx.HTTPError as exc:
            return _result(False, None, sanitize_error(str(exc), api_key))
        if resp.status_code < 400:
            return _result(True, resp.status_code)
        return _result(False, resp.status_code, sanitize_error(resp.text, api_key))

    # ADR-109-3: chat/embeddings/stt — единый probe_openai.
    #   * transcribe_groq — Whisper-модель принимает только
    #     POST /audio/transcriptions (chat давал ложный error);
    #   * transcribe_openrouter — расшифровка идёт через chat.completions с
    #     input_audio (см. openrouter_transcriber), поэтому chat-probe корректен;
    #   * embeddings — POST /embeddings; остальные — POST /chat/completions.
    if block == "transcribe_groq":
        kind = "stt"
    elif block in _EMBEDDING_BLOCKS:
        kind = "embeddings"
    else:
        kind = "chat"
    result = await probe_openai(base_url, api_key, model, kind=kind,
                                timeout=_TIMEOUT_SECONDS)
    if result["ok"]:
        return _result(True, result["http_status"])
    return _result(False, result["http_status"], result.get("error"))


async def _probe_search(client: httpx.AsyncClient, base: str,
                        api_key: str, provider: str | None = None
                        ) -> httpx.Response:
    """Поисковый ключ: provider ('tavily'|'exa') либо авто по base/api_key."""
    low = base.lower()
    if provider is None:
        provider = "exa" if ("exa" in low
                             or (api_key or "").startswith("exa-")) else "tavily"
    if provider == "exa":
        return await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key},
            json={"query": "ping", "numResults": 1})
    return await client.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": "ping", "max_results": 1})
