"""UNIFIED-REPLY UR-C-CLOCK (arch contract §3): единый ChatClock/TimeSnapshot.

ЕДИНСТВЕННЫЙ сервис времени чата (UR-24/25/26): резолв effective IANA-пояса
по канонической цепочке UR-24.3 + вычисление локального времени через
``zoneinfo.ZoneInfo`` на конкретном UTC-instant серверных часов. Вторых
резолверов/часов не существует: Direct L1/L2, tool-оркестратор, инициатива,
фактчек и саммари получают ОДИН и тот же ``TimeSnapshot`` этого модуля.

Каноническая цепочка пояса (UR-24.3; "" = наследование, не зона):

    per-chat limits.chat_timezone
    → per-chat legacy limits.summary_timezone
    → global limits.chat_timezone
    → global legacy limits.summary_timezone
    → явно заданный legacy GOODMORNING_TZ (env; дефолт кода НЕ считается
      осознанным override)
    → прежний кодовый дефолт (settings.SUMMARY_TIMEZONE, source="factory")

Хранение мгновений остаётся в UTC (UR-24.4): этот модуль ничего не пишет,
не меняет timezone процесса и историю сообщений. Неизвестная зона → явная
деградация в UTC с ``timezone_source="utc_fallback"`` и ERROR-логом
(диагностика), не молчаливая подмена. ``config_version`` — updated_at
профиля чата (существующий chat_params кэш, сбрасываемый notify-каналом
сохранения); смена пояса меняет только представление на НОВЫХ ходах:
in-flight ход остаётся на своём неизменяемом ``TimeSnapshot``.

Инъекция ``clock`` — для детерминированных тестов (UR-25.3); UTC-округление
не превращает 23:59 в «завтра» (локальная дата считается из точного
aware-мгновения).
"""
from __future__ import annotations

import dataclasses
import datetime
import logging
import os
import zoneinfo
from typing import Callable

from config.settings import settings

logger = logging.getLogger(__name__)

#: Канонический пользовательский ключ пояса (UR-24.1) — единственный
#: редактируемый источник; legacy-ключи ниже читаются read-only.
CANON_TZ_KEY = "limits.chat_timezone"
#: Legacy-ключ саммари (read-only совместимость, UR-24.3).
LEGACY_SUMMARY_TZ_KEY = "limits.summary_timezone"

#: Фазы блока (UR-25.2): план хода vs финальная сборка ответа.
PHASE_PLAN = "plan"
PHASE_ANSWER = "answer"

# Таблица дней недели — РОВНО одна на проект (владелец таблицы —
# canonical_context; ChatClock её переиспользует, второй таблицы нет).
from services.canonical_context import _WEEKDAYS_RU  # noqa: E501  (переиспользование, не копия)


@dataclasses.dataclass(frozen=True)
class TimeSnapshot:
    """Неизменяемый снапшот времени чата (arch contract §3.1).

    ``as_of_utc`` — aware UTC-мгновение серверных часов (инъекция clock);
    ``local_datetime`` — aware локальное время чата (ZoneInfo на ЭТОТ
    instant, fold-корректное); ``timezone`` — IANA ID (fixed-offset
    «UTC+5» IANA ID не подменяет); ``utc_offset`` — "+HH:MM";
    ``timezone_source`` — chat | chat_legacy | global | global_legacy |
    legacy_goodmorning | factory | utc_fallback; ``config_version`` —
    updated_at профиля чата ("" — недоступен)."""

    as_of_utc: datetime.datetime
    local_datetime: datetime.datetime
    weekday: str
    timezone: str
    utc_offset: str
    timezone_source: str
    config_version: str


def _valid_iana(name: str) -> bool:
    """Строго валидное непустое IANA-имя (пустое/мусор → False)."""
    text = str(name or "").strip()
    if not text:
        return False
    try:
        zoneinfo.ZoneInfo(text)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError,
            FileNotFoundError, KeyError, OSError):
        return False
    return True


# Одноразовый конфликт-лог (UR-24.3: конфликт фиксируется, не скрытый сброс).
# Bounded: перегрелся → чистим старейшие ключи (set без порядка — просто
# опустошаем; повторный лог после перегрева не вредит).
_CONFLICT_LOGGED: set[tuple[str, str, str]] = set()
_CONFLICT_LOG_LIMIT = 256


def _log_conflict_once(chat_id, *, winner_key: str, loser_key: str,
                       winner_value: str, loser_value: str) -> None:
    key = (str(chat_id), winner_key, loser_key)
    if key in _CONFLICT_LOGGED:
        return
    if len(_CONFLICT_LOGGED) >= _CONFLICT_LOG_LIMIT:
        _CONFLICT_LOGGED.clear()
    _CONFLICT_LOGGED.add(key)
    logger.warning(
        "[chat_clock] timezone conflict | chat=%s | %s=%r wins over "
        "%s=%r (canonical chain UR-24.3)", chat_id, winner_key,
        winner_value, loser_key, loser_value)


async def _config_version(chat_id) -> str:
    """updated_at профиля чата как версия конфига ("" — нет/недоступен)."""
    if chat_id is None:
        return ""
    try:
        from services.chat_params import get_chat_updated_at
        return str(await get_chat_updated_at(int(chat_id)) or "")
    except Exception:      # pragma: no cover - fail-open diagnostics
        return ""


async def resolve_chat_timezone(chat_id) -> tuple[str, str, str]:
    """(iana, source, config_version) — каноническая цепочка UR-24.3.

    Чтение ТОЛЬКО существующих слоёв: per-chat overrides через кэш
    chat_params (сброс при сохранении — notify-канал), global через
    ConfigCache/hot с фаб-дефолтом настроек. Legacy-ключи — read-only
    совместимость: они НЕ создают второй редакторской поверхности.
    "" (пустая строка) означает наследование, НЕ зону. Конфликт явно
    заданных зон логируется одноразово, побеждает более специфичный
    канонический слой. Никогда не бросает."""
    cv = await _config_version(chat_id)
    from services import hot_config as hot

    per_chat: dict = {}
    if chat_id is not None:
        try:
            from services.chat_params import get_chat_params_cache
            cache = get_chat_params_cache()
            if cache is not None:
                root = await cache.get_chat_params(int(chat_id))
                per_chat = dict((root or {}).get("overrides") or {})
        except Exception:      # pragma: no cover - fail-open
            per_chat = {}

    def _chat_override(key: str) -> str | None:
        """Значение per-chat override или None (нет/"" → наследование).
        ТОЛЬКО overrides чата — global-слой сюда не подмешивается (иначе
        глобальное значение выдавалось бы за per-chat с source="chat")."""
        raw = per_chat.get(key)
        if raw is None:
            return None
        return str(raw).strip() or None

    def _global_value(key: str, factory_default: str) -> str:
        """Global-слой: ConfigCache/hot с settings-дефолтом (контракт R1
        прежнего hot.get)."" — fail-open."""
        try:
            return str(hot.get(key, factory_default) or "").strip()
        except Exception:      # pragma: no cover - fail-open
            return ""

    # Слой 1/2: per-chat canonical → per-chat legacy (только overrides).
    v1 = _chat_override(CANON_TZ_KEY)
    v2 = _chat_override(LEGACY_SUMMARY_TZ_KEY)
    if v1 is not None:
        if v2 is not None and v2 != v1:
            _log_conflict_once(chat_id, winner_key=CANON_TZ_KEY,
                               loser_key=LEGACY_SUMMARY_TZ_KEY,
                               winner_value=v1, loser_value=v2)
        if _valid_iana(v1):
            return v1, "chat", cv
    if v2 is not None and _valid_iana(v2):
        return v2, "chat_legacy", cv

    # Слой 3/4: global canonical → global legacy (ConfigCache/hot, фаб-дефолт
    # настроек — как в прежнем hot.get-контракте R1).
    g1 = _global_value(CANON_TZ_KEY, getattr(settings, "CHAT_TIMEZONE", ""))
    g2 = _global_value(LEGACY_SUMMARY_TZ_KEY,
                       getattr(settings, "SUMMARY_TIMEZONE", ""))
    if g1:
        if g2 and g2 != g1:
            _log_conflict_once(chat_id, winner_key=CANON_TZ_KEY,
                               loser_key=LEGACY_SUMMARY_TZ_KEY,
                               winner_value=g1, loser_value=g2)
        if _valid_iana(g1):
            return g1, "global", cv
    if g2 and _valid_iana(g2):
        return g2, "global_legacy", cv

    # Слой 5: legacy GOODMORNING_TZ — ТОЛЬКО явно заданный env (UR-24.3:
    # обычное значение из env-дефолта кода НЕ выдаётся за осознанный
    # override; поэтому читаем os.environ, а не settings).
    gm = str(os.environ.get("GOODMORNING_TZ", "") or "").strip()
    if gm and _valid_iana(gm):
        return gm, "legacy_goodmorning", cv

    # Слой 6: прежний кодовый дефолт.
    fallback = str(getattr(settings, "SUMMARY_TIMEZONE", "") or "").strip()
    if fallback and _valid_iana(fallback):
        return fallback, "factory", cv
    # Совсем без tzdata/настроек — честный UTC.
    return "UTC", "utc_fallback", cv


def _render_block(snap: TimeSnapshot, *, phase: str,
                  source_label: str | None = None) -> str:
    """ОДИН короткий машиночитаемый блок <Chat_Time_Context> (UR-25.6).

    User/data-content (НЕ system — prompt-cache); помечен как авторитетный
    серверный контекст. ``phase`` различает «время чата на момент
    планирования» и «на момент ответа»; ``source_label`` — отдельное поле
    «время источника» (не смешивается с временем чата, UR-25.2)."""
    local = snap.local_datetime
    lines = [
        '<Chat_Time_Context source="server" phase="%s">' % str(phase),
        "local: %s %s, %s (%s, UTC%s)" % (
            local.strftime("%d.%m.%Y"), local.strftime("%H:%M"),
            snap.weekday, snap.timezone, snap.utc_offset),
        "as_of_utc: %s" % snap.as_of_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    ]
    if snap.config_version:
        lines.append("config: %s" % snap.config_version)
    if snap.timezone_source == "utc_fallback":
        # Явная деградация (UR-24.4): блок честно показывает UTC-деградацию,
        # а не утверждает, что действует выбранный пояс.
        lines.append("tz_status: utc_fallback (iana zone unavailable)")
    if source_label:
        lines.append("source_time: %s" % str(source_label))
    lines.append("</Chat_Time_Context>")
    return "\n".join(lines)


async def snapshot(chat_id, *, at_utc=None,
                   clock: Callable[[], datetime.datetime] | None = None
                   ) -> TimeSnapshot:
    """TimeSnapshot чата на серверном UTC-мгновении (arch contract §3.1).

    ``at_utc`` — явное aware-мгновение (приоритет); ``clock`` — инъекция
    серверных часов для тестов; иначе ``datetime.now(timezone.utc)``.
    Не зависит от timezone контейнера/рабочей станции (UR-25.3): naive
    вход трактуется как UTC (конвенция прежнего ``format_chat_time``),
    локальное время считается только через ZoneInfo на конкретный
    instant. tzdata отсутствует → явная деградация в UTC
    (``timezone_source="utc_fallback"`` + ERROR-диагностика). Никогда
    не бросает."""
    try:
        if at_utc is not None:
            moment = at_utc
        elif clock is not None:
            moment = clock()
        else:
            moment = datetime.datetime.now(datetime.timezone.utc)
        if moment.tzinfo is None:
            # Naive — трактуем как UTC (конвенция format_chat_time), не как
            # локальное время контейнера (UR-BAN-05).
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        moment = moment.astimezone(datetime.timezone.utc)
    except Exception:      # pragma: no cover - защитная ветка
        moment = datetime.datetime.now(datetime.timezone.utc)

    iana, source, cv = await resolve_chat_timezone(chat_id)
    try:
        local = moment.astimezone(zoneinfo.ZoneInfo(iana))
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, FileNotFoundError,
            KeyError, OSError):
        logger.error(
            "[chat_clock] tzdata unavailable for %r — explicit UTC "
            "fallback | chat=%s (UR-24.4)", iana, chat_id)
        local = moment.astimezone(datetime.timezone.utc)
        source = "utc_fallback"
    offset = local.utcoffset() or datetime.timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    offset_str = "%s%02d:%02d" % (sign, total // 3600, (total % 3600) // 60)
    return TimeSnapshot(
        as_of_utc=moment,
        local_datetime=local,
        weekday=_WEEKDAYS_RU[local.weekday()],
        timezone=iana,
        utc_offset=offset_str,
        timezone_source=source,
        config_version=cv,
    )


def _minute_bucket(moment: datetime.datetime) -> int:
    return int(moment.timestamp()) // 60


async def ensure_answer_snapshot(plan_snap: TimeSnapshot, chat_id, *,
                                 clock: Callable[[], datetime.datetime]
                                 | None = None) -> tuple[TimeSnapshot, bool]:
    """(answer_snapshot, refreshed) для финальной сборки ответа (UR-25.2).

    Свежий ``answer_as_of_utc`` ТОЛЬКО если цепочка хода пересекла минуту
    или локальную полночь/дату; иначе reuse plan-снапшота (та же минута —
    время L1 и L2 совпадает, тест UR-C-CLOCK это ловит). Никогда не
    бросает."""
    try:
        if clock is not None:
            now = clock()
        else:
            now = datetime.datetime.now(datetime.timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        now = now.astimezone(datetime.timezone.utc)
        crossed = _minute_bucket(now) != _minute_bucket(plan_snap.as_of_utc)
        if not crossed:
            try:
                fresh_local_date = (now.astimezone(
                    zoneinfo.ZoneInfo(plan_snap.timezone)).date())
            except Exception:      # pragma: no cover
                fresh_local_date = now.date()
            if fresh_local_date != plan_snap.local_datetime.date():
                crossed = True
        if not crossed:
            return plan_snap, False
        return await snapshot(chat_id, clock=clock), True
    except Exception:      # pragma: no cover - fail-open reuse
        return plan_snap, False


def render_chat_time_context(snap: TimeSnapshot, *, phase: str,
                             source_label: str | None = None) -> str:
    """Публичный рендер единственного блока <Chat_Time_Context>."""
    return _render_block(snap, phase=phase, source_label=source_label)


BLOCK_OPEN = '<Chat_Time_Context source="server"'


def append_time_block(user_content: str, snap: TimeSnapshot, *, phase: str,
                      source_label: str | None = None) -> str:
    """Идемпотентное добавление блока в user-content стадии (ровно один
    блок на payload — UR-25.6/§3.3 seal-инвариант). Никогда не бросает."""
    try:
        text = str(user_content or "")
        if BLOCK_OPEN in text:
            return text
        block = _render_block(snap, phase=phase, source_label=source_label)
        return f"{text}\n\n{block}" if text.strip() else block
    except Exception:      # pragma: no cover - защитная ветка
        return str(user_content or "")


def attach_time_context(messages, snap: TimeSnapshot, *, phase: str,
                        source_label: str | None = None) -> list:
    """ЕДИНСТВЕННЫЙ helper сборки стадий (arch contract §3.1): добавляет
    блок в ПОСЛЕДНЕЕ user-сообщение payload'а (data-content, не system).
    Уровень сборки стадий — НЕ низкоуровневый llm_client (UR-26 запрещает
    глобальный prepend). Идемпотентно, никогда не бросает."""
    try:
        out: list = [dict(m) if isinstance(m, dict) else m
                     for m in (messages or [])]
        last_user = None
        for idx in range(len(out) - 1, -1, -1):
            msg = out[idx]
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user = idx
                break
        if last_user is None:
            return out
        out[last_user]["content"] = append_time_block(
            str(out[last_user].get("content") or ""), snap, phase=phase,
            source_label=source_label)
        return out
    except Exception:      # pragma: no cover - защитная ветка
        return list(messages or [])


def outbound_clock_meta(messages) -> dict | None:
    """Машиночитаемые поля блока из финального outbound payload (UR-26.7).

    None → блока нет (clock_included=false). Только код/числа, без текстов
    чата. Никогда не бросает."""
    try:
        last_user = None
        for msg in reversed(list(messages or [])):
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user = str(msg.get("content") or "")
                break
        if not last_user or BLOCK_OPEN not in last_user:
            return None
        start = last_user.find(BLOCK_OPEN)
        end = last_user.find("</Chat_Time_Context>", start)
        block = last_user[start:end if end != -1 else len(last_user)]
        meta: dict = {"clock_included": True}
        for line in block.splitlines():
            text = line.strip()
            if text.startswith("local:"):
                # "local: DD.MM.YYYY HH:MM, День (IANA, UTC+HH:MM)"
                tail = text[len("local:"):].strip()
                if "(" in tail and ")" in tail:
                    paren = tail[tail.find("(") + 1:tail.find(")")]
                    parts = [p.strip() for p in paren.split(",")]
                    if parts:
                        meta["timezone"] = parts[0][:64]
                    if len(parts) > 1:
                        meta["utc_offset"] = (
                            parts[1].replace("UTC", "").strip()[:8])
            elif text.startswith("as_of_utc:"):
                meta["as_of_utc"] = text[len("as_of_utc:"):].strip()[:32]
            elif text.startswith("config:"):
                meta["config_version"] = text[len("config:"):].strip()[:64]
            elif text.startswith('phase='):
                pass
            elif BLOCK_OPEN in text and 'phase="' in text:
                phase = text.split('phase="', 1)[1].split('"', 1)[0]
                meta["phase"] = phase[:16]
        return meta
    except Exception:      # pragma: no cover - защитная ветка
        return None


def log_clock_call(*, module: str, step: str, chat_id, messages,
                   channel: str = "primary") -> None:
    """Наблюдаемость модельного вызова (UR-26.7): stage, chat_id, timezone,
    as_of_utc, config_version, clock_included и причина пропуска. R17:
    без текстов payload'а. Никогда не бросает."""
    try:
        meta = outbound_clock_meta(messages)
        if meta is None:
            logger.info(
                "[clock_call] module=%s | step=%s | chat_id=%s | "
                "clock_included=false | skip_reason=no_time_block | "
                "channel=%s", module, step, chat_id, channel)
            return
        logger.info(
            "[clock_call] module=%s | step=%s | chat_id=%s | timezone=%s | "
            "as_of_utc=%s | config_version=%s | phase=%s | "
            "clock_included=true | channel=%s",
            module, step, chat_id, meta.get("timezone", ""),
            meta.get("as_of_utc", ""), meta.get("config_version", ""),
            meta.get("phase", ""), channel)
    except Exception:      # pragma: no cover
        pass


__all__ = [
    "TimeSnapshot",
    "CANON_TZ_KEY", "LEGACY_SUMMARY_TZ_KEY",
    "PHASE_PLAN", "PHASE_ANSWER",
    "resolve_chat_timezone", "snapshot", "ensure_answer_snapshot",
    "render_chat_time_context", "append_time_block", "attach_time_context",
    "outbound_clock_meta", "log_clock_call", "BLOCK_OPEN",
]
