"""Epic 60 (Section 64.7, T-468): tiktoken-счётчик + тримминг по токенам.

Ленивый import tiktoken; encoding = TOKENIZER_ENCODING (default o200k_base —
лучшая компрессия кириллицы, T-459 тема 1). tiktoken/кодировка недоступны →
fallback int(len * 0.3) (рус ≈ 0.3 токена/символ) + WARNING один раз на
кодировку (деградация R3-стиля). tiktoken — ТОЛЬКО упреждающий тримминг;
фактические лимиты — usage из API-ответа (llm_client, INFO usage in/out).

Переводятся ровно 3 лимита (64.7): CHAT_GLOBAL_CONTEXT_MAX_TOKENS (5000),
CHAT_THREAD_MAX_TOKENS (3000), SUMMARY_MAX_CONTEXT_TOKENS (30000) — как
потолок user_content перед generate. Старые *_CHARS-ключи — АВАРИЙНЫЙ
верхний fallback (resolve_chat_limit: токенный пуст нигде + chars задан в
env → chars).

F4 (10.19, ADR-1019-4 D3/D4, ADR-1019-8 D2/D3): токенные контекст-лимиты
имеют sentinel-семантику семейства «контекст» (`budget_limits.context_state`):

* `< 0` (канон `-1`) → **безлимит** → практический потолок
  `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (env-only, default 32000);
* `0` / `None` → **не задано** → глобальный дефолт (`token_default`);
* `> 0` → cap (как раньше).

Это устраняет S10.19-13 (контекст «обрезался до 1 токена» при `-1`/`0`).
"""
import logging
import os

from config.settings import settings
from services import hot_config as hot
from services.budget_limits import context_state

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 0.3          # рус ≈ 0.3 токена/символ (o200k, T-459 тема 1)

# Имя кодировки -> tiktoken.Encoding | None (кэш; WARNING один раз на имя).
_ENCODINGS: dict[str, object] = {}


def _get_encoding():
    """tiktoken-кодировка для hot.get("models.tokenizer_encoding", settings.TOKENIZER_ENCODING); None — fallback."""
    name = hot.get("models.tokenizer_encoding", settings.TOKENIZER_ENCODING)
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


def truncate_to_tokens_keep_head(text: str, max_tokens: int) -> str:
    """Раунд 8 (T-799/D2, spec 3.D2): срез ПО ТОКЕНАМ с НАЧАЛА строки —
    первые max_tokens токенов («держать голову»: конспект сверху
    Global_Context переживает обрезку, первым режется конец — свежий
    verbatim-хвост). WARNING при обрезке. max_tokens < 1 → "". fallback —
    голова по символам (max_tokens / 0.3)."""
    text = str(text or "")
    if not text or max_tokens < 1:
        return ""
    encoding = _get_encoding()
    if encoding is not None:
        tokens = encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text
        try:
            kept = encoding.decode(tokens[:max_tokens])
        except Exception:
            logger.warning(
                "token_counter: decode failed — chars fallback head slice")
            return text[:int(max_tokens / _CHARS_PER_TOKEN)]
        logger.warning("token_counter: keep-head truncated to %d tokens (was %d)",
                       max_tokens, len(tokens))
        return kept
    if int(len(text) * _CHARS_PER_TOKEN) <= max_tokens:
        return text
    logger.warning("token_counter: keep-head truncated to %d tokens (chars fallback)",
                   max_tokens)
    return text[:int(max_tokens / _CHARS_PER_TOKEN)]


def resolve_context_tokens(token_value, token_default: int) -> int:
    """F4 (10.19, ADR-1019-8 D2/D3): эффективный ПОТОЛОК токенов контекстного
    ключа с sentinel-семантикой семейства «контекст»:

    * `< 0` → безлимит → `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (env-only);
    * `0` / `None` / мусор → «не задано» → `token_default` (глобальный дефолт);
    * `> 0` → cap.

    Чистая функция (без I/O); используется и в resolve_chat_limit, и в
    инвариант-проверке конфигурации контекста."""
    state = context_state(token_value)
    if state == "unlimited":
        return int(settings.CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS)
    if state == "cap":
        return int(token_value)
    # D-8 (10.19): отрицательный env-дефолт (`CHAT_GLOBAL_CONTEXT_MAX_TOKENS=-1`
    # при незаданном токен-значении) не должен вернуть `-1` → `safe_budget(-1)
    # = 1` («мина» S10.19-13). Клампим снизу до 1.
    return max(1, int(token_default))


def safe_budget(max_tokens: int) -> int:
    """Запас TOKEN_SAFETY_MULTIPLIER (токенизатор DeepSeek ≠ o200k, ±15%)."""
    return max(1, int(max_tokens / hot.get("models.token_safety_multiplier", settings.TOKEN_SAFETY_MULTIPLIER)))


def resolve_chat_limit(token_value, token_default: int, chars_env: str,
                       chars_value: int, label: str) -> tuple[str, int]:
    """64.7 + F4 (10.19, ADR-1019-4 D3/D4): ('tokens', N) или ('chars', N).

    Токенный лимит задан → tokens со sentinel-семантикой контекста
    (`resolve_context_tokens`: `-1` → потолок безлимита, `0` → дефолт, `>0` →
    cap). Токенный пуст нигде (`None`) + chars задан в env → АВАРИЙНЫЙ
    chars-fallback (`logger.debug`, не штатный путь). Иначе — дефолтный
    токенный бюджет (`token_default`).
    """
    if token_value is not None:
        return ("tokens", resolve_context_tokens(token_value, token_default))
    if os.getenv(chars_env) is not None:
        logger.debug(
            "%s: токенный лимит не задан, %s задан — chars-fallback=%d "
            "(аварийный путь)",
            label, chars_env, chars_value,
        )
        return ("chars", chars_value)
    # D-8 (10.19): тот же кламп, что и в resolve_context_tokens — отрицательный
    # env-дефолт не превращается в `safe_budget(-1) = 1`.
    return ("tokens", max(1, int(token_default)))
