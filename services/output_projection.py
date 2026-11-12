"""SELF-DIAG-01 D2 — структурная проекция секретов и защищённого вывода.

Модуль исполняет абсолютный запрет выдачи credential values через чат
(owner amendment 2026-11-09 §4, ТЗ §9). Запрет НЕ основан на списке слов
«пароль/токен»: источник истины — типизированный каталог параметров
(`services.param_catalog`), где у записи есть канонический тип чувствительности
(`sensitivity`; `SECRET_VALUE` — секрет), плюс фактические runtime-значения
секретов (settings/секрет-стор/BYOK). Легаси-флаг `secret` не решает, надо ли
защищать значение: сбор известных секретов идёт по `is_secret_value`.
Сравнение идёт по ЗНАЧЕНИЯМ, поэтому перефразирование запроса ничего не меняет.

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
#: Значения зеркалят канонический закрытый набор `services.param_catalog`
#: (SELF-DIAG-01 `SD1-D2-23`); паритет проверяется тестом
#: `test_output_projection_constants_match_catalog`, правило вывода типа
#: здесь больше НЕ дублируется — `sensitivity_of_pg_key` читает каталог.
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

#: Виды вывода, для которых неполнота источников секретов — отказ (fail-closed),
#: а не «надеемся, что значения нет». Сырой контент такого вида уже мог
#: содержать credential value, и проверить это нечем.
RAW_OUTPUT_KINDS: tuple[str, ...] = ("logs", "traceback", "prompt",
                                     "tool_result", "final")

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


#: Тип credential-значения в реестре: одно значение или список значений.
CREDENTIAL_KIND_SCALAR = "scalar"
CREDENTIAL_KIND_LIST = "list"


@dataclasses.dataclass(frozen=True)
class CredentialField:
    """Явная запись типизированного реестра credential-источников."""

    settings_field: str
    pg_key: str
    kind: str = CREDENTIAL_KIND_SCALAR


#: Типизированный реестр ВСЕХ текущих credential-полей настроек.
#: Реестр явный (а не эвристика по имени): тест `test_credential_registry`
#: сверяет его с фактическими полями `Settings`, поэтому новый ключ без
#: регистрации ломает сборку, а не утекает в вывод.
CREDENTIAL_FIELDS: tuple[CredentialField, ...] = (
    CredentialField("API_TOKEN", "api_token"),
    CredentialField("LLM_API_KEY", "keys.llm_api_key"),
    CredentialField("LLM_FALLBACK_API_KEY", "keys.llm_fallback_api_key"),
    CredentialField("EMBEDDING_API_KEY", "keys.embedding_api_key"),
    CredentialField("EMBEDDING_FALLBACK_API_KEY",
                    "keys.embedding_fallback_api_key"),
    CredentialField("EMBEDDING_FALLBACK_API_KEY_2",
                    "keys.embedding_fallback_api_key_2"),
    CredentialField("EMBEDDING_EXTRA_API_KEYS",
                    "keys.embedding_extra_api_keys", CREDENTIAL_KIND_LIST),
    CredentialField("TAVILY_API_KEY", "keys.tavily_api_key"),
    CredentialField("EXA_API_KEY", "keys.exa_api_key"),
    CredentialField("GROQ_API_KEY", "keys.groq_api_key"),
    CredentialField("OPENROUTER_API_KEY", "keys.openrouter_api_key"),
    CredentialField("IMAGE_API_KEY", "keys.image_api_key"),
    CredentialField("IMAGE_STYLE_API_KEY", "keys.image_style_api_key"),
    CredentialField("VISION_API_KEY", "keys.vision_api_key"),
    CredentialField("INTEL_HISTORY_API_KEY", "keys.intel_history_api_key"),
    CredentialField("INTEL_BG_API_KEY", "keys.intel_bg_api_key"),
    CredentialField("INTEL_REFLECTION_API_KEY",
                    "keys.intel_reflection_api_key"),
    CredentialField("RANDOM_QUANTUM_API_KEY", "keys.random_quantum_api_key"),
    CredentialField("MEDIA_SHARE_SECRET", "keys.media_share_secret"),
    CredentialField("SUMMARY_L1_API_KEY", "keys.summary_l1_api_key"),
    CredentialField("SUMMARY_L2_API_KEY", "keys.summary_l2_api_key"),
    CredentialField("SOURCE_READ_GITHUB_TOKEN",
                    "keys.source_read_github_token"),
    CredentialField("YOUTUBE_TRANSCRIPT_PROXY_URL",
                    "keys.youtube_transcript_proxy_url"),
    CredentialField("YOUTUBE_TRANSCRIPT_PROXY_USERNAME",
                    "keys.youtube_transcript_proxy_username"),
    CredentialField("YOUTUBE_TRANSCRIPT_PROXY_PASSWORD",
                    "keys.youtube_transcript_proxy_password"),
    CredentialField("YOUTUBE_COOKIES_FILE", "keys.youtube_cookies_file"),
    CredentialField("SAFE_FETCH_UPSTREAM_PROXY", "safe_fetch_upstream_proxy"),
)

#: Резделитель списковых credential-полей (через запятую/пробел/перевод строки).
_LIST_SPLIT = re.compile(r"[,\s]+")

#: Имена причин отказа проекции (наблюдаемость, без самих значений).
REASON_SOURCES_UNAVAILABLE = "secret_sources_unavailable"
REASON_SOURCES_INCOMPLETE = "secret_sources_incomplete"


@dataclasses.dataclass(frozen=True)
class SecretSnapshot:
    """Известные значения секретов + ЯВНАЯ полнота источников.

    `complete=False` означает: перечислить все credential-значения не
    удалось (часть источников недоступна), поэтому сравнение по значениям
    не может доказать отсутствие секрета в сыром выводе.
    """

    values: dict[str, str]
    complete: bool
    missing: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        if self.complete:
            return "secret_sources_complete"
        if not self.missing:
            return REASON_SOURCES_INCOMPLETE
        return f"{REASON_SOURCES_INCOMPLETE}:{','.join(self.missing)}"


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

    Единственный источник истины — запись каталога (`ParamSpec.sensitivity`,
    SELF-DIAG-01 `SD1-D2-23`): тип объявлен при регистрации либо зафиксирован
    для легаси-строки. Проекция больше не дублирует правило вывода — она
    только читает его. Неизвестный ключ → `PUBLIC_DIAGNOSTIC`.
    """
    try:
        from services import param_catalog as catalog
        spec = catalog.get_by_pg_key(pg_key)
    except Exception:                                  # pragma: no cover
        return SENSITIVITY_PUBLIC
    if spec is None:
        return SENSITIVITY_PUBLIC
    return spec.resolved_sensitivity


def is_secret_pg_key(pg_key: str) -> bool:
    return sensitivity_of_pg_key(pg_key) == SENSITIVITY_SECRET


def _catalog_secret_keys() -> tuple[str, ...]:
    """PG-ключи каталога с каноническим типом `SECRET_VALUE` (вкл. cache-only).

    Класс берётся из `ParamSpec.is_secret_value`, а не из легаси-флага
    `secret`: единственный источник истины — `sensitivity` каталога
    (`SD1-D2-23`). Иначе новый провайдер с `SECRET_VALUE` + `secret=False`
    не попадал бы в набор известных секретов.
    """
    from services import param_catalog as catalog
    return tuple(sorted(spec.pg_key for spec in catalog.REGISTRY.values()
                        if spec.is_secret_value))


def _config_cache_secret_sources() -> dict[str, bool]:
    """Действующие секретные ключи конфиг-кэша: {pg_key: списковый ли}.

    Рабочее значение параметра живёт в `bot_settings` (ConfigCache), а не в
    `Settings`: ключ, заданный в админке, отличается от env-дефолта. Поэтому
    сравнивать нужно ЗНАЧЕНИЕ ИЗ КЭША — в том числе для ключей без поля в
    `Settings` (`keys.direct_l1_api_key`, `keys.summary_l2_api_key`, инфра-
    секреты каталога) и для ключей реестра credential-полей, которые можно
    переопределить через админку (`keys.llm_api_key` и другие).
    """
    kinds: dict[str, bool] = {
        field.pg_key: field.kind == CREDENTIAL_KIND_LIST
        for field in CREDENTIAL_FIELDS
    }
    for pg_key in _catalog_secret_keys():
        kinds.setdefault(pg_key, False)
    return kinds


def known_secret_values(cache=None, *, use_cache: bool = True,
                        ) -> SecretSnapshot:
    """Известные runtime-значения секретов + полнота источников.

    Источники:
      1) типизированный реестр credential-полей `CREDENTIAL_FIELDS`
         (settings/секрет-стор);
      2) поля каталога параметров с каноническим типом `SECRET_VALUE`
         и `settings_field` (страховка, если каталог расширили без правки
         реестра; тип читается из `ParamSpec.is_secret_value`, а не из
         легаси-флага `secret`);
      3) токен бота (`settings.API_TOKEN`);
      4) значения секретов, объявленных в каталоге с env-именем, — ВСЕГДА
         из `os.environ` (`POSTGRES_DSN`, `SENTRY_DSN`,
         `LOGTAIL_SOURCE_TOKEN`, `TELEGRAM_API_ID/HASH`,
         `COBALT_HTTP_PROXY` и другие). Для части из них поля в `Settings`
         нет, и в конфиг-кэше их тоже нет: промах кэша не должен скрывать
         значение окружения;
      5) ДЕЙСТВУЮЩИЕ значения ВСЕХ секретных ключей конфиг-кэша: реестра
         credential-полей (переопределяемых через админку —
         `keys.llm_api_key` и другие) и каталога, включая cache-only ключи
         без `settings_field` (`keys.direct_l1_api_key`,
         `keys.summary_l1_api_key`), плюс глобальные секреты
         `services.chat_keys`.

    `SecretSnapshot.complete=False` — часть источников прочитать не удалось;
    для сырого вывода это отказ (см. `sanitize`). Ключ конкретного чата
    (BYOK) добавляет `known_secret_values_async`.

    Кэш значений (`_SECRET_CACHE_TTL`) наполняется только ПОЛНЫМ набором,
    собранным С конфиг-кэшем: снимок без кэша не объявляет себя полным для
    последующего вызова, у которого кэш есть, иначе первый (бедный) набор
    «отравлял» бы TTL-кэш и прятал кэш-секрет на следующие 60 секунд.
    """
    global _secret_cache
    now = time.monotonic()
    if use_cache and _secret_cache is not None \
            and _secret_cache[0] > now:
        return SecretSnapshot(dict(_secret_cache[1]), True)

    missing: list[str] = []
    try:
        values = _settings_secret_values()
    except Exception:
        logger.warning("[diag-secrets] сбор источников секретов "
                       "не удался", exc_info=True)
        return SecretSnapshot({}, False, ("settings",))
    try:
        # Окружение процесса читается ВСЕГДА (до и независимо от кэша):
        # часть секретов каталога живёт только в env, и промах конфиг-кэша
        # не должен скрывать их значение.
        for name, value in _env_secret_values().items():
            values.setdefault(name, value)
    except Exception:
        logger.warning("[diag-secrets] окружение процесса недоступно — "
                       "полнота источников секретов неизвестна", exc_info=True)
        missing.append("env")

    if cache is None:
        # Отсутствие конфиг-кэша — не ошибка (прецедент BYOK/`pg` выше: «без
        # хранилища ключей чата не бывает»). Без ConfigCache в этом процессе
        # не действует ни одно значение `bot_settings`: `hot_config.get`
        # обслуживает settings-дефолт, поэтому собранный набор Settings и
        # есть полный набор ДЕЙСТВУЮЩИХ здесь credential-значений. Обратный
        # случай — кэш есть, но чтение упало — это «неизвестно» и отказ.
        logger.debug("[diag-secrets] конфиг-кэш не подключён — действуют "
                     "только settings-значения")
    else:
        sources: dict[str, bool] = {}
        try:
            from services import chat_keys
            for name in sorted(chat_keys.global_secret_keys()):
                sources.setdefault(name, False)
        except Exception:
            logger.warning("[diag-secrets] список глобальных секретов "
                           "недоступен", exc_info=True)
            missing.append("global_secrets")
        try:
            for name, is_list in _config_cache_secret_sources().items():
                sources.setdefault(name, is_list)
        except Exception:
            logger.warning("[diag-secrets] каталог секретных ключей "
                           "недоступен", exc_info=True)
            missing.append("catalog")
        for name in sorted(sources):
            try:
                value = cache.get(name)
            except Exception:
                # Кэш не читается → какие значения в нём лежат, неизвестно.
                logger.warning("[diag-secrets] секрет конфиг-кэша не читается "
                               "— полнота неизвестна | key=%s", name,
                               exc_info=True)
                missing.append("config_cache")
                break
            _remember_source_value(values, value, name,
                                   is_list=sources[name])
    # Ключ конкретного чата (BYOK) читается только асинхронно —
    # см. `known_secret_values_async`.
    snapshot = SecretSnapshot(values, not missing, tuple(missing))
    # Только полный набор, собранный С конфиг-кэшем, годится как общий
    # TTL-кэш: снимок без кэша не содержит значений `bot_settings` и,
    # будучи закэшированным, отравил бы следующий вызов с живым кэшем.
    if use_cache and cache is not None and snapshot.complete:
        _secret_cache = (now + _SECRET_CACHE_TTL, dict(values))
    return snapshot


async def known_secret_values_async(cache=None, pg=None,
                                    chat_id: int | None = None,
                                    ) -> SecretSnapshot:
    """Асинхронная версия: добавляет BYOK-ключ конкретного чата.

    Ошибка чтения ключа чата трактуется как «неизвестно» (`complete=False`),
    а не как «ключа нет»: иначе сырой вывод мог бы пройти без проверки.
    Отсутствие PG-пула — не ошибка: без хранилища ключей чата не бывает.
    """
    snapshot = known_secret_values(cache=cache)
    values = dict(snapshot.values)
    missing = list(snapshot.missing)
    if chat_id is not None and getattr(pg, "pool", None) is not None:
        try:
            from services import chat_keys
            for name in sorted(chat_keys.BYOK_KEYS_WHITELIST):
                value = await chat_keys.get_chat_key(pg, int(chat_id), name,
                                                     strict=True)
                _remember(values, value, name)
        except Exception:
            logger.warning("[diag-secrets] ключ чата недоступен — "
                           "полнота источников неизвестна | chat=%s",
                           chat_id, exc_info=True)
            missing.append("byok")
    return SecretSnapshot(values, snapshot.complete and not missing,
                          tuple(missing) or snapshot.missing)


def _settings_secret_values() -> dict[str, str]:
    """Значения credential-полей из реестра + секреты каталога параметров.

    Секретность записи каталога определяется каноническим типом
    (`is_secret_value`), а не легаси-флагом `secret`: источник истины один.
    """
    from config.settings import settings
    from services import param_catalog as catalog

    values: dict[str, str] = {}
    for field in CREDENTIAL_FIELDS:
        raw = getattr(settings, field.settings_field)
        if field.kind == CREDENTIAL_KIND_LIST:
            for part in _LIST_SPLIT.split(str(raw or "")):
                _remember(values, part, field.pg_key)
        else:
            _remember(values, raw, field.pg_key)
    for spec in catalog.REGISTRY.values():
        if not spec.is_secret_value or not spec.settings_field:
            continue
        _remember(values, getattr(settings, spec.settings_field, None),
                  spec.pg_key)
    # Токен бота — секрет даже если поле не помечено в каталоге.
    _remember(values, getattr(settings, "API_TOKEN", None), "settings.API_TOKEN")
    return values


def _env_secret_values() -> dict[str, str]:
    """Секреты каталога, объявленные с env-именем, — из `os.environ`.

    Части секретов нет ни в `Settings`, ни в `bot_settings`
    (`postgres_dsn`, `postgres_password`, `sentry_dsn`,
    `logtail_source_token`, `telegram_api_id`, `telegram_api_hash`,
    `cobalt_http_proxy`): их рантайм-значение живёт только в окружении
    процесса. Поэтому окружение читается всегда, а не через конфиг-кэш, и
    промах кэша не может спрятать значение. Пустое/короткое значение
    секретом не считается (`_remember` отсекает).
    """
    import os

    from services import param_catalog as catalog

    values: dict[str, str] = {}
    for spec in catalog.REGISTRY.values():
        # Канонический тип, а не легаси `secret`: иначе env-секрет нового
        # провайдера (`SECRET_VALUE` + `secret=False`) не попадал бы в набор.
        if not spec.is_secret_value or not spec.env_name:
            continue
        _remember(values, os.environ.get(spec.env_name), spec.env_name)
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


def _remember_source_value(values: dict[str, str], value, name: str, *,
                           is_list: bool = False) -> None:
    """Запомнить значение источника: списковое поле раскладывается на части.

    Значение приходит из конфиг-кэша, где списковый секрет лежит либо
    строкой через запятую, либо готовым списком (jsonb). Скалярное значение
    НЕ режется: запятая внутри ключа — часть самого ключа.
    """
    if isinstance(value, (list, tuple, set, frozenset)):
        for part in value:
            _remember(values, part, name)
        return
    if is_list:
        for part in _LIST_SPLIT.split(str(value or "")):
            _remember(values, part, name)
        return
    _remember(values, value, name)


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

_REASON_NO_SOURCE = "secret_sources_unavailable"


def _normalize_secrets(secrets) -> tuple[dict[str, str] | None, bool, str]:
    """(значения, полон ли набор, машинная причина) для любого входа."""
    if isinstance(secrets, SecretSnapshot):
        return dict(secrets.values), secrets.complete, secrets.reason
    if secrets is None:
        return None, False, _REASON_NO_SOURCE
    # Явный словарь — заявленный вызывающим полный инвентарь значений.
    return dict(secrets), True, "secret_sources_complete"


def sanitize(text: str, *, kind: str = "text", secrets=None,
             fail_closed_kinds: tuple[str, ...] = RAW_OUTPUT_KINDS,
             ) -> DeliveryResult:
    """Удалить известные секреты и credential-паттерны из текста.

    `kind` — «logs» | «traceback» | «prompt» | «tool_result» | «final» |
    «text». Если источники секретов недоступны ИЛИ неполны
    (`SecretSnapshot.complete is False`), для сырого вывода возвращается
    `allowed=False`: сырой текст не выдаётся вообще, потому что отсутствие
    значения в неполном наборе ничего не доказывает.
    """
    original = "" if text is None else str(text)
    values, complete, reason = _normalize_secrets(secrets)
    if not complete:
        report = RedactionReport(STATUS_BLOCKED, 0, (), reason)
        if kind in fail_closed_kinds:
            return DeliveryResult(False, "", report)
        return DeliveryResult(True, original, report)

    out = original
    kinds: list[str] = []
    redacted = 0
    # Длинные значения первыми: иначе короткое «съест» часть длинного.
    for value, name in sorted((values or {}).items(), key=lambda kv: -len(kv[0])):
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


def assert_secret_free(text: str, secrets=None) -> bool:
    """True — ни одно известное значение секрета не встречается в тексте.

    Неизвестный/неполный набор источников → `False` («доказать нельзя»),
    а не «надеемся, что чисто».
    """
    values, complete, _reason = _normalize_secrets(secrets)
    if not complete:
        return False
    blob = "" if text is None else str(text)
    return not any(value and value in blob for value in (values or {}))


def prompt_digest(text: str) -> dict:
    """Безопасные метаданные защищённого промпта для аудита (без текста)."""
    import hashlib
    blob = "" if text is None else str(text)
    return {
        "prompt_chars": len(blob),
        "prompt_digest": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
    }
