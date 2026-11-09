"""SELF-DIAG-01 D2 — структурная проекция секретов и защищённого вывода.

Модуль исполняет абсолютный запрет выдачи credential values через чат
(owner amendment 2026-11-09 §4, ТЗ §9). Запрет НЕ основан на списке слов
«пароль/токен»: источник истины — типизированный каталог параметров
(`services.param_catalog`), где у поля есть флаг `secret`, плюс фактические
runtime-значения секретов (settings/секрет-стор/BYOK). Сравнение идёт по
ЗНАЧЕНИЯМ, поэтому перефразирование запроса ничего не меняет.

Правила:
  * значение секрета никогда не сериализуется в результат инструмента или
    в сообщение: только `configured`, `last4`/маскированный фингерпринт,
    статус (`project_secret_value`);
  * любой текст на выходе (лог, traceback, ответ инструмента, финальная
    доставка) проходит `sanitize` — известные значения заменяются на
    «скрыто:<имя>», дополнительно применяются pattern/heuristic маркеры
    (только как ВТОРАЯ линия, не единственная защита);
  * high-risk сырой контент (логи/traceback/промпт) при невозможности
    собрать источники секретов → fail-closed (`allowed=False`).
"""
from __future__ import annotations

import dataclasses
import logging
import re
import time

logger = logging.getLogger(__name__)

#: Типы чувствительности (ТЗ §9.1): обязательны при регистрации провайдера.
SENSITIVITY_PUBLIC = "PUBLIC_DIAGNOSTIC"
SENSITIVITY_CONFIG = "NON_SECRET_CONFIG"
SENSITIVITY_PROMPT_CONTENT = "PROMPT_CONTENT"
SENSITIVITY_SECRET = "SECRET_VALUE"

SENSITIVITY_VALUES: tuple[str, ...] = (
    SENSITIVITY_PUBLIC, SENSITIVITY_CONFIG, SENSITIVITY_PROMPT_CONTENT,
    SENSITIVITY_SECRET,
)

STATUS_CLEAN = "clean"
STATUS_PARTIALLY_REDACTED = "partially_redacted"
STATUS_BLOCKED = "blocked"

#: Маркер удалённого фрагмента (не содержит самого значения).
REDACTION_MARKER = "«скрыто:{name}»"

#: Минимальная длина значения, которое вообще отслеживаем (короткие строки
#: дают ложные срабатывания и не являются credential value).
_MIN_SECRET_LEN = 8
_SECRET_CACHE_TTL = 60.0

#: Вторая линия (дополнительно, НЕ единственная защита): явные форматы
#: известных провайдеров. Намеренно узкие — чтобы не портить обычный текст.
_PATTERN_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("telegram_bot_token",
     re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
    ("openai_like_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{0,4096}?"
                r"-----END [A-Z ]*PRIVATE KEY-----")),
)

_secret_cache: tuple[float, dict[str, str]] | None = None


def reset_secret_cache() -> None:
    """Сброс кэша известных значений секретов (тесты/ротация ключей)."""
    global _secret_cache
    _secret_cache = None


@dataclasses.dataclass(frozen=True)
class RedactionReport:
    """Наблюдаемый результат санитизации (без самих значений)."""

    status: str
    redacted: int
    kinds: tuple[str, ...]
    reason: str

    @property
    def clean(self) -> bool:
        return self.status == STATUS_CLEAN


@dataclasses.dataclass(frozen=True)
class DeliveryResult:
    """Итог проверки текста перед доставкой."""

    allowed: bool
    text: str
    report: RedactionReport


# ── Источник истины о секретных полях ──────────────────────────────────────

def sensitivity_of_pg_key(pg_key: str) -> str:
    """Тип чувствительности ключа каталога (ТЗ §9.1).

    Секретные ключи (`keys.*`, spec.secret) → `SECRET_VALUE`; ключи
    категории prompts → `PROMPT_CONTENT`; прочие ключи каталога →
    `NON_SECRET_CONFIG`; неизвестный ключ → `PUBLIC_DIAGNOSTIC`.
    """
    try:
        from services import param_catalog as catalog
        spec = catalog.get_by_pg_key(pg_key)
    except Exception:                                  # pragma: no cover
        return SENSITIVITY_PUBLIC
    if spec is None:
        return SENSITIVITY_PUBLIC
    if spec.secret or spec.category == catalog.CATEGORY_KEYS:
        return SENSITIVITY_SECRET
    if spec.category == catalog.CATEGORY_PROMPTS:
        return SENSITIVITY_PROMPT_CONTENT
    return SENSITIVITY_CONFIG


def is_secret_pg_key(pg_key: str) -> bool:
    return sensitivity_of_pg_key(pg_key) == SENSITIVITY_SECRET


def known_secret_values(cache=None, *, use_cache: bool = True,
                        ) -> dict[str, str] | None:
    """Известные runtime-значения секретов {значение: имя}.

    `None` — источники собрать не удалось (fail-closed для high-risk
    контента). Список строится из типизированных источников:
      1) поля `Settings` с флагом `secret` в каталоге параметров;
      2) токен бота (`settings.API_TOKEN`);
      3) действующие глобальные секреты (`services.chat_keys`).
    Ключ конкретного чата (BYOK) добавляет `known_secret_values_async`.
    """
    global _secret_cache
    now = time.monotonic()
    if use_cache and _secret_cache is not None \
            and _secret_cache[0] > now:
        values = dict(_secret_cache[1])
    else:
        try:
            values = _settings_secret_values()
        except Exception:                              # pragma: no cover
            logger.warning("[diag-secrets] сбор источников секретов "
                           "не удался", exc_info=True)
            return None
        if use_cache:
            _secret_cache = (now + _SECRET_CACHE_TTL, dict(values))

    if cache is not None:
        try:
            from services import chat_keys
            for name in sorted(chat_keys.global_secret_keys()):
                value = cache.get(name)
                _remember(values, value, name)
        except Exception:                              # pragma: no cover
            logger.warning("[diag-secrets] глобальные секреты недоступны",
                           exc_info=True)
    # Ключ конкретного чата (BYOK) читается только асинхронно —
    # см. `known_secret_values_async`.
    return values


async def known_secret_values_async(cache=None, pg=None,
                                    chat_id: int | None = None) -> dict[str, str] | None:
    """Асинхронная версия: добавляет BYOK-ключ конкретного чата."""
    values = known_secret_values(cache=cache)
    if values is None:
        return None
    if chat_id is not None and getattr(pg, "pool", None) is not None:
        try:
            from services import chat_keys
            for name in sorted(chat_keys.BYOK_KEYS_WHITELIST):
                value = await chat_keys.get_chat_key(pg, int(chat_id), name)
                _remember(values, value, name)
        except Exception:                              # pragma: no cover
            logger.warning("[diag-secrets] ключ чата недоступен",
                           exc_info=True)
    return values


def _settings_secret_values() -> dict[str, str]:
    from config.settings import settings
    from services import param_catalog as catalog

    values: dict[str, str] = {}
    for spec in catalog.REGISTRY.values():
        if not spec.secret or not spec.settings_field:
            continue
        _remember(values, getattr(settings, spec.settings_field, None),
                  spec.pg_key)
    # Токен бота — секрет даже если поле не помечено в каталоге.
    _remember(values, getattr(settings, "API_TOKEN", None), "settings.API_TOKEN")
    return values


def _remember(values: dict[str, str], value, name: str) -> None:
    if not isinstance(value, str):
        return
    text = value.strip()
    if len(text) < _MIN_SECRET_LEN:
        return
    if text.lower() in {"true", "false", "none", "null"}:
        return
    values.setdefault(text, name)


# ── Проекция секретного поля (никогда значение) ────────────────────────────

def project_secret_value(name: str, value) -> dict:
    """Безопасное представление секретного поля: наличие + статус, без текста.

    Ровно то, что разрешено отдавать в чат/UI (ТЗ §7.2/§9.1): `configured`,
    `last4` (маскированный фингерпринт), `status`. Значение не покидает
    backend.
    """
    configured = bool(value)
    last4 = None
    if configured:
        text = str(value)
        last4 = text[-4:] if len(text) > 4 else None
    return {
        "name": name,
        "sensitivity": SENSITIVITY_SECRET,
        "configured": configured,
        "last4": last4,
        "status": "configured" if configured else "not_configured",
    }


# ── Санитизация вывода ────────────────────────────────────────────────────

def sanitize(text: str, *, kind: str = "text", secrets: dict[str, str] | None = None,
             fail_closed_kinds: tuple[str, ...] = ("logs", "traceback", "prompt"),
             ) -> DeliveryResult:
    """Удалить известные секреты и credential-паттерны из текста.

    `kind` — «logs» | «traceback» | «prompt» | «tool_result» | «final» |
    «text». Если `secrets is None` (источники недоступны), для high-risk
    видов возвращается `allowed=False` (fail-closed), а не «надеемся, что
    секретов нет».
    """
    original = "" if text is None else str(text)
    if secrets is None:
        report = RedactionReport(STATUS_BLOCKED, 0, (),
                                 "secret_sources_unavailable")
        if kind in fail_closed_kinds:
            return DeliveryResult(False, "", report)
        return DeliveryResult(True, original, report)

    out = original
    kinds: list[str] = []
    redacted = 0
    # Длинные значения первыми: иначе короткое «съест» часть длинного.
    for value, name in sorted(secrets.items(), key=lambda kv: -len(kv[0])):
        if value and value in out:
            count = out.count(value)
            out = out.replace(value, REDACTION_MARKER.format(name=name))
            redacted += count
            if "secret_value" not in kinds:
                kinds.append("secret_value")
    for name, pattern in _PATTERN_RULES:
        out, hits = pattern.subn(REDACTION_MARKER.format(name=name), out)
        if hits:
            redacted += hits
            if name not in kinds:
                kinds.append(name)

    if redacted:
        return DeliveryResult(
            True, out,
            RedactionReport(STATUS_PARTIALLY_REDACTED, redacted, tuple(kinds),
                            "secret_fragments_removed"))
    return DeliveryResult(True, out,
                          RedactionReport(STATUS_CLEAN, 0, (), "no_secret_values"))


def assert_secret_free(text: str, secrets: dict[str, str] | None) -> bool:
    """True — ни одно известное значение секрета не встречается в тексте."""
    if secrets is None:
        return True
    blob = "" if text is None else str(text)
    return not any(value and value in blob for value in secrets)


def prompt_digest(text: str) -> dict:
    """Безопасные метаданные защищённого промпта для аудита (без текста)."""
    import hashlib
    blob = "" if text is None else str(text)
    return {
        "prompt_chars": len(blob),
        "prompt_digest": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
    }
