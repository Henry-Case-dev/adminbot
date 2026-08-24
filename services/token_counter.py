"""Epic 60 (Section 64.7, T-468): tiktoken-счётчик + тримминг по токенам.

Ленивый import tiktoken; encoding = TOKENIZER_ENCODING (default o200k_base —
лучшая компрессия кириллицы, T-459 тема 1). tiktoken/кодировка недоступны →
fallback int(len * 0.3) (рус ≈ 0.3 токена/символ) + WARNING один раз на
кодировку (деградация R3-стиля). tiktoken — ТОЛЬКО упреждающий тримминг;
фактические лимиты — usage из API-ответа (llm_client, INFO usage in/out).

Переводятся ровно 3 лимита (64.7): CHAT_GLOBAL_CONTEXT_MAX_TOKENS (1000),
CHAT_THREAD_MAX_TOKENS (500), SUMMARY_MAX_CONTEXT_TOKENS (30000) — как
потолок user_content перед generate. Старые *_CHARS-ключи — верхний
fallback (resolve_chat_limit: токенный пуст + chars задан в env → chars).
"""
import logging
import os

from config.settings import settings

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 0.3          # рус ≈ 0.3 токена/символ (o200k, T-459 тема 1)

# Имя кодировки -> tiktoken.Encoding | None (кэш; WARNING один раз на имя).
_ENCODINGS: dict[str, object] = {}


def _get_encoding():
    """tiktoken-кодировка для settings.TOKENIZER_ENCODING; None — fallback."""
    name = settings.TOKENIZER_ENCODING
    if name in _ENCODINGS:
        return _ENCODINGS[name] or None
    encoding = None
    try:
        import tiktoken
        try:
            encoding = tiktoken.get_encoding(name)
        except Exception:
            logger.warning(
                "token_counter: encoding %s unavailable — chars×0.3 fallback (R3)",
                name,
            )
    except ImportError:
        logger.warning(
            "token_counter: tiktoken unavailable — chars×0.3 fallback (R3)"
        )
    _ENCODINGS[name] = encoding
    return encoding


def count_tokens(text: str) -> int:
    """Токены (TOKENIZER_ENCODING); fallback — int(len * 0.3)."""
    text = str(text or "")
    if not text:
        return 0
    encoding = _get_encoding()
    if encoding is not None:
        return len(encoding.encode(text))
    return int(len(text) * _CHARS_PER_TOKEN)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Срез ПО ТОКЕНАМ с КОНЦА строки (последние max_tokens токенов — самые
    свежие сообщения в хвосте контекста). WARNING при обрезке. max_tokens < 1
    → "". fallback — хвост по символам (max_tokens / 0.3)."""
    text = str(text or "")
    if not text or max_tokens < 1:
        return ""
    encoding = _get_encoding()
    if encoding is not None:
        tokens = encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text
        try:
            kept = encoding.decode(tokens[-max_tokens:])
        except Exception:
            logger.warning("token_counter: decode failed — chars fallback slice")
            return text[-int(max_tokens / _CHARS_PER_TOKEN):]
        logger.warning("token_counter: truncated to %d tokens (was %d)",
                       max_tokens, len(tokens))
        return kept
    if int(len(text) * _CHARS_PER_TOKEN) <= max_tokens:
        return text
    logger.warning("token_counter: truncated to %d tokens (chars fallback)",
                   max_tokens)
    return text[-int(max_tokens / _CHARS_PER_TOKEN):]


def safe_budget(max_tokens: int) -> int:
    """Запас TOKEN_SAFETY_MULTIPLIER (токенизатор DeepSeek ≠ o200k, ±15%)."""
    return max(1, int(max_tokens / settings.TOKEN_SAFETY_MULTIPLIER))


def resolve_chat_limit(token_value, token_default: int, chars_env: str,
                       chars_value: int, label: str) -> tuple[str, int]:
    """64.7: ('tokens', N) или ('chars', N).

    Токенный лимит задан (settings-поле не None) → tokens. Токенный пуст +
    chars задан в env → chars-fallback с WARNING. Иначе дефолтный токенный
    бюджет (1000/500/30000).
    """
    if token_value is not None:
        return ("tokens", token_value)
    if os.getenv(chars_env) is not None:
        logger.warning(
            "%s: токенный лимит не задан, %s задан — chars-fallback=%d",
            label, chars_env, chars_value,
        )
        return ("chars", chars_value)
    return ("tokens", token_default)
