"""Раунд 9 (AGI Memory, spec §3.5, T-827/E2) — NostalgiaWorker: ностальгия
слой B (проактивные «кстати...»).

P0-followup (§2, снапшот владельца 18.10.2026) — разделение сценариев:
  * A — контекстное воспоминание в АКТИВНОЙ беседе: последнее юзерское
    сообщение свежее окна silence (память идёт по текущей теме / «ровно год
    назад»); гейт 45-мин тишины и quiet hours НЕ применяются (беседа идёт);
  * B — автономное после затишья: тишина/quiet hours/паузы действуют.
Оба — тот же воркер, кандидаты, порог, budget, единый Decision/Writer/
SendRecheck (делегирование при K1+K3), анти-навязчивость (cooldown,
дневной лимит, Q14-стоп) — общая для A и B.

Фоновый SQLite-воркер по каркасу dream_worker (AsyncIOScheduler +
IntervalTrigger(minutes=limits.nostalgia_tick_minutes=60, timezone=…) +
max_instances=1 + coalesce), БЕЗ PG-lock. Джоб `nostalgia_tick`
регистрируется ВСЕГДА (hot-включение memory.nostalgia_enabled работает без
рестарта бота); при OFF тик — дешёвый no-op (событие skipped/disabled), а
ручные run_once режет kill-switch-флаг. Запуск в bot.py on_startup ПОСЛЕ
DreamWorker (fail-open); ручной run_once(chat_id) — для будущего F2-API
(D-8: test-эндпоинт НЕ в v1).

Тик (spec §3.5.3/§3.5.4; чаты — ТОЛЬКО активные PG-профили
ChatLoreStore.list_active_chat_ids, Q13; PG down/пусто → no-op WARNING):
дешёвые гейты чата (skip = WARNING без строк в nostalgia_log):
  1. флаг ON (тик), chat_id < 0, is_active-профиль;
  2. сценарий A/B по тишине: последнее юзерское сообщение свежее окна →
     A (без гейтов 3 и «тишины»); истории нет вовсе → no_history;
  3. quiet hours (только B): local-час (timezone summary_timezone) >= start
     ИЛИ < end (пересечение полуночи);
  4. cooldown: прошло ≥ nostalgia_cooldown_hours с последнего sent;
  5. дневной лимит: status='sent' за local-сутки < nostalgia_max_per_day;
  6. Q14 (анти-спам): среди последних sent чата за окно
     nostalgia_pause_hours (24 ч) нет подряд nostalgia_unanswered_max
     неотвеченных (юзерские сообщения после ts отправки — smart_messages,
     user_id NOT NULL и != bot_id); стоп → skip, чат молчит, пока окно
     pause_hours не пройдёт ИЛИ юзер не ответит (D-17: пауза неявная —
     то же условие повторяется на следующих тиках).
Дорогие шаги (строки в nostalgia_log):
  кандидаты (§3.5.2, P0 NOSTALGIA REWORK W1, source-2026-10-27
  NOST-01..04/07): исторические ЭПИЗОДЫ вместо «один год назад — три
  ближайших сообщения» — по годам фактического архива чата
  (get_chat_history_bounds, динамический список лет) в календарные
  годовщины текущего дня (часовой пояс чата, високосные годы; 365*86400
  удалено); окно уровня «день» (± nostalgia_year_back_days_window —
  существующая настройка владельца) адаптивно расширяется
  день → неделя → месяц → продолжение по факту события, пока сегмент
  касается границы окна (остановка — сегмент закрыт; уровни — масштабы
  исследования, не обязательные стадии). Реконструкция эпизода —
  существующее детерминированное ядро mca_episodes.segment_messages
  (время + reply-граф + участники; несвязанные обсуждения не склеиваются).
  Первичные сообщения эпизода → format_year_back_line (provenance
  «Переслано» сохранён; имена — актуальный алиас по uid, каскад
  summary_aliases) → 1 LLM-вызов (NOSTALGIA_PROMPT / NOSTALGIA_CORE_CANON).
  И/или «золотые» по последней теме (существующий fetch_golden_facts,
  ≤2 факта; W2: подмешиваются к историческому пулу — ОБА набора в
  payload). W2 (NOST-05): фиксированный вес происхождения 0.7 снят —
  исторический пул не гейтится арифметикой, содержательную пригодность
  решает типизированный вердикт модели; порог 0.3 +
  nostalgia_aggressiveness*0.5 остаётся техническим предварительным
  отбором только слабых «золотых» фактов. Ответ LLM типизирован
  (NOST-01): ровно UNCHANGED → skipped unchanged (дневной лимит не
  тратится); SAY [+ № блока] + вторая строка → текст реплики; ответ без
  вердикта — легаси-контент (совместимость). Семантический страж
  самоотказа по фразам (_SELF_DECLINE_* / is_self_declining_text)
  УДАЛЁН — смысловые
  решения не ищутся по спискам фраз. Текст: trim + cap
  nostalgia_max_send_chars, пустой → skipped empty; UNCHANGED-токен в
  контенте → брак. Отправка: legacy bot.send_message ИЛИ делегирование
  _delegate_initiative → handle_initiative (единый Decision, audit-1021
  §3). Отказ (UNCHANGED) — отсутствие публикации, без объяснения в чат.
  Сбой → status='error'; успех → status='sent'.

Fail-open (NFR-4): ошибка чата — WARNING, тик жив; бот не падает.

P0 NOSTALGIA REWORK W2 (28.10.2026, source-2026-10-27 NOST-05/06/08/09/11/12):
  * NOST-05: фиксированный вес происхождения (история 0.7 vs порог) снят —
    содержательная пригодность решается типизированным вердиктом LLM
    (NOST-01); порог агрессивности остаётся техническим предварительным
    отбором ТОЛЬКО для слабых «золотых» фактов (без фразовых списков и без
    арифметики как финального судьи). Количество сообщений не участвует в
    отборе (объём ≠ интересность). Контекстный сценарий учитывает
    содержание текущего разговора (секция «Текущий разговор» в user-блоке,
    окно шире «последних 5 отдельных слов»).
  * NOST-06: тематический режим по ВСЕЙ истории (FTS-семена существующим
    search_messages_fts + build_fts_query — тот же путь, что «золотые»),
    реконструкция тем же адаптивным движком (день → неделя → месяц →
    продолжение, _episode_around); календарный режим не предпочитается
    гарантированно — порядок предъявления технический (тематическая связь,
    затем свежесть), финальное решение — вердикт модели. Одного второго
    движка нет.
  * NOST-08: повторы — по ИДЕНТИЧНОСТИ эпизода (стабильные message_key,
    не текст): недавние опубликованные эпизоды (журнал nostalgia_log,
    окно 30 дней/10 отправок) исключаются из пула; все кандидаты — повторы
    → честный skip reason=repeat (искусственной новизны нет: молчание).
    Точный контроль повтора — протокольный номер блока: модель указывает
    выбранный эпизод вердиктом «SAY <№>» (детерминированный суффикс,
    parse_say_slot); в журнал пишется идентичность выбранного блока,
    голый SAY — консервативно все предъявленные. Разнообразие периодов —
    следствие исключения повторов и порядка предъявления, без квот.
  * NOST-11: плотные окна (>лимита) стратифицируются по времени (равные
    страты, каждая даёт своё начало — период покрыт, а не только голова);
    тематический поиск поэтапный (семена → отбор периодов → детализация);
    ошибка источника деградирует честно (флаг в meta, календарь живёт).
  * NOST-12: глубина поиска — memory.nostalgia_history_depth_years
    (0 = весь доступный архив, >0 — ограничение в годах); диагностика
    последнего запуска в meta nostalgia_log (периоды, источники, найдено/
    показано, повторы, ошибки архива, режим) — фактические runtime-данные.
  * Даты построчного рендера и заголовков эпизодов — в часовом поясе чата
    (review-w1 nonblocking 1).
"""
import asyncio
import datetime
import json
import logging
import re
import time

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from zoneinfo import ZoneInfo

from config.settings import settings
from services import hot_config as hot
from services import turn_payload_events as _tpe
from services.database import row_get
from services.mca_episodes import (
    SEGMENT_GAP_SECONDS,
    message_key,
    segment_messages,
)
from services.nostalgia_prompts import (
    NOSTALGIA_CORE_CANON,
    NOSTALGIA_PROMPT,
    _MEMES_LIMIT,
    build_nostalgia_user,
    clean_llm_text,
    contains_unchanged_token,
    format_golden_line,
    format_year_back_line,
    parse_nostalgia_answer,
    parse_say_slot,
)

logger = logging.getLogger(__name__)

_GOLDEN_FACT_LIMIT = 2         # spec §3.5.2: 1–2 факта по последней теме
_TOPIC_MESSAGES = 5            # spec §3.5.2: ключи последних 5 юзерских
_TOPIC_KEYWORDS_CAP = 40       # потолок значимых слов FTS-матча «темы»
_FALLBACK_WINDOW_HOURS = 24    # фолбэк окна неотвеченных (D-17: окно =
                               # nostalgia_pause_hours, дефолт 24 ч)
_KIND_NONE = "none"            # kind лога при «кандидатов нет»
_STATUS_SENT = "sent"
_STATUS_SKIPPED = "skipped"
_STATUS_ERROR = "error"

# ── P0 NOSTALGIA REWORK W1 (NOST-02/03/04/07): исторические эпизоды ────────
_HISTORY_LEVEL_DAY = "day"     # уровень A: календарный день годовщины
_HISTORY_LEVEL_WEEK = "week"   # уровень B: календарная ISO-неделя
_HISTORY_LEVEL_MONTH = "month"  # уровень C: календарный месяц
_HISTORY_CONTINUATION_MAX = 3  # уровень D: потолок продолжений (+месяц)
_WINDOW_FETCH_LIMIT = 600      # кап выборки одного окна (честный truncated)
_EPISODE_LINES_MAX = 12        # кап строк одного эпизода (голова+хвост)
_EPISODES_MAX = 4              # кап эпизодов в пуле (payload-выборка;
                               # ранжирование ДО капа + честный
                               # episodes_found/episodes_shown в meta —
                               # NOST-05/11: самое релевантное не теряется)
_SEGMENT_EPS = SEGMENT_GAP_SECONDS  # порог «касания» границы окна (30 мин)

# ── P0 NOSTALGIA REWORK W2 (NOST-05/06/08/11) ───────────────────────────────
_TOPIC_CONTEXT_MESSAGES = 40   # окно поиска всплеска беседы (не «последние 5»)
_CONTEXT_GAP_HOURS = 6         # разрыв, завершающий «один разговор»
_CONTEXT_PAYLOAD_MAX = 8       # строк «Текущего разговора» в payload
_THEMATIC_SEEDS_MAX = 12       # FTS-семена тем (предварительный отбор)
_THEMATIC_DETAIL_MAX = 2       # периодов к детализации (select-then-detail)
_STRATA_MAX = 8                # число страт плотного окна (NOST-11.3)
_REPEAT_LOOKBACK_SENT = 10     # последних sent-журналов = «недавно»
_REPEAT_LOOKBACK_DAYS = 30     # временнáя граница «недавно рассказано»

_TOPIC_WORD_RE = re.compile(r"[а-яёa-z0-9]{5,}", re.IGNORECASE)

# ── PROACTIVE NOSTALGIA (owner corrective 2026-11-10) ───────────────────────
# Инициативная ностальгия — не «ровно год назад в этот день» и не словарь тем:
# relevance берётся из ЕДИНОГО GraphRAG-retrieval (канал episode), покрытие
# периодов и повторяемость — из фактических журналов. Квантовое направление
# (VMQ-ONTO-01) — один plug-in `RandomSourceService`, только направление.
#
# FROZEN SEAM (NOSTALGIA SEAM RECONCILED):
#   plans/features/smart-module-semantic-routing/nostalgia-seam-contract.md
# Два общих интерфейса реализованы ровно по этому контракту:
#   * `NostalgiaWorker.recall_in_conversation(...)` — §1: шов проактивного
#     воспоминания; вызывается Observer/Decision, решение публиковать НЕ
#     принимает (генерация и отправка — тот же Writer/транспорт);
#   * `NostalgiaWorker._direction_pick(...)` — §3: единственная точка
#     подключения RandomSource (направление исследования).
_SEMANTIC_TOP_K = 6            # кандидатов памяти на один проход
_SEMANTIC_MATERIALIZE_MAX = 3  # сколько кандидатов реконструируется в эпизод
_SEMANTIC_CHANNEL = ("episode",)   # существующий канал единого retrieval
_RELEVANCE_W = 0.65            # вес смысловой релевантности в порядке
_COVERAGE_BONUS = 0.2          # незвучавший недавно период
_USAGE_BONUS = 0.1             # давно не рассказывалось (mca usage)
_FALLBACK_TOPICAL_REL = 0.45   # FTS/тематика — слабый сигнал, не решатель
_FALLBACK_OTHER_REL = 0.15
_DIRECTION_BAND = 0.999        # полоса равно допустимых для квантового выбора
_MEMORY_SUMMARY_CHARS = 160    # кап summary в подсказке памяти
_MEMORY_HINT_TOTAL = 3         # подсказок Observer за окно
_MEMORY_QUERY_CAP = 400        # запрос retrieval из текущей беседы


def _now_ts() -> int:
    """Текущее unix-время (обёртка — тесты подменяют для гейтов/окон)."""
    return int(time.time())


def _intent_delegation_enabled() -> bool:
    """MCA-09 (T-5038): K1+K3 ON → кандидат делегируется единому Decision/
    транспорту; OFF → legacy direct-send бит-в-бит 2.58.59 (никогда не
    бросает)."""
    try:
        from services import mca_gates
        return bool(mca_gates.intents_enabled()
                    and mca_gates.intent_decision_enabled())
    except Exception:      # pragma: no cover - защитная ветка
        return False


# ── MCA-17 (группа «Фоновые воркеры сна/памяти»): событие nostalgia.run ─────
_NOSTALGIA_COMPONENT = "nostalgia.run"


def _emit(event_name: str, outcome: str, *, level: str = "INFO",
          **fields) -> None:
    """Fail-open эмиссия события контракта §17.1 (REUSE `emit_mca_event`,
    mca-13; паттерн `graphrag_rebuild._emit`). R17: только ID/коды/числа —
    без текстов убеждений/сообщений."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(event_name, outcome=outcome, level=level, **fields)
    except Exception:      # контракт не рвёт поток воркера
        pass


def _ms_since(mono: float) -> int:
    """Длительность в мс от mono-отметки (bounded int, R17-safe)."""
    try:
        return max(0, int((time.monotonic() - mono) * 1000))
    except Exception:
        return 0


def _nostalgia_terminal(stats: dict, *, enabled: bool,
                        no_op: str | None = None) -> tuple[str, str | None]:
    """Честный исход прогона ностальгии (MCA-17): (outcome, reason_code) —
    ТОЛЬКО существующие коды словаря §17.2. Тексты кандидатов не переносятся
    (R17) — их аудит уже в nostalgia_log. `no_op` — внутренний маркер раннего
    выхода `_run_tick` (store отсутствует/PG down/нет чатов): недоступность
    PG-лора — это failed (не «нет кандидатов»)."""
    if not enabled:
        return "skipped", "disabled"
    if no_op in ("store_missing", "pg_down"):
        return "failed", "memory_service_missing"
    if stats.get("errors") and not stats.get("sent") \
            and stats.get("candidates"):
        return "failed", "provider_unavailable"
    if not stats.get("candidates") and not stats.get("sent"):
        return "skipped", "no_relevant_memory"
    return "success", None


def _day_start_ts(now_ts: int, tz_name: str | None = None) -> int:
    """Начало local-суток (полночь в timezone ностальгии) — дневной лимит
    §3.5.3 п.5 (edge 20: окна/сутки — local summary_timezone)."""
    zone = _zone(tz_name)
    local = datetime.datetime.fromtimestamp(now_ts, zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


def _local_hour(now_ts: int, tz_name: str | None = None) -> int:
    """Текущий local-час в timezone ностальгии (quiet hours)."""
    return datetime.datetime.fromtimestamp(now_ts, _zone(tz_name)).hour


def _zone(tz_name: str | None):
    try:
        return ZoneInfo(str(tz_name)) if tz_name else None
    except Exception:
        return None


# ── P0 NOSTALGIA REWORK W1: календарная арифметика и эпизоды ────────────────
# (NOST-02/03/04; детерминированная логика — даты/диапазоны/сегменты.
#  Семантических списков слов здесь нет и не должно появляться.)


def _local_datetime(ts: int, tz=None):
    """unix ts → aware-локальное время (tz чата) или naive local; None —
    битое значение. Никогда не бросает."""
    try:
        if tz is not None:
            return datetime.datetime.fromtimestamp(int(ts), tz)
        return datetime.datetime.fromtimestamp(int(ts))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _ts_date_local(ts, tz=None) -> str:
    """unix ts → ГГГГ-ММ-ДД в часовом поясе ЧАТА (NOST-02.2: часовой пояс
    чата; битое/пустое → '????-??-??'). Для дат-заголовков эпизодов;
    построчный рендер сообщений сохраняет прежний легаси-конвент."""
    dt = _local_datetime(ts, tz)
    if dt is None:
        return "????-??-??"
    return dt.strftime("%Y-%m-%d")


def _anniversary_date(today: datetime.date, year: int) -> datetime.date:
    """Календарная годовщина `today` в году `year` (NOST-02.2): дата
    вычисляется календарно, не вычитанием секунд. 29 февраля в невисокосный
    год → 28 февраля (документированное правило сопоставления; даты
    исходных сообщений при этом не изменяются)."""
    try:
        return datetime.date(year, today.month, today.day)
    except ValueError:            # 29 февраля → невисокосный год
        return datetime.date(year, today.month, 28)


def _shift_month_first(day: datetime.date, months: int) -> datetime.date:
    """1-е число месяца, смещённого на `months` календарных месяцев от
    месяца `day` (уровни C/D — календарные месяцы, не «30 дней»,
    NOST-03.1)."""
    total = day.year * 12 + (day.month - 1) + months
    return datetime.date(total // 12, total % 12 + 1, 1)


def _anniversary_window(anniv: datetime.date, tz, level: str,
                        continuation: int, base_days: int) -> tuple[int, int]:
    """Границы окна исследования годовщины в unix ts (NOST-02.2/3.1):
    календарные периоды в часовом поясе чата. day — сам день годовщины;
    week — календарная неделя (Пн..Вс) этого дня; month — календарный месяц;
    month+k — месяц, расширенный на k календарных месяцев в обе стороны
    (уровень D: продолжение по факту события; Новый год не обрывает
    эпизод). base_days (nostalgia_year_back_days_window — существующая
    настройка владельца) симметрично расширяет любой уровень."""
    pad = max(0, int(base_days or 0)) * 86400

    def midnight(d: datetime.date) -> int:
        dt = datetime.datetime(d.year, d.month, d.day)
        if tz is not None:
            dt = dt.replace(tzinfo=tz)
        return int(dt.timestamp())

    if level == _HISTORY_LEVEL_WEEK:
        start_day = anniv - datetime.timedelta(days=anniv.weekday())
        end_day = start_day + datetime.timedelta(days=7)
    elif level == _HISTORY_LEVEL_MONTH:
        start_day = anniv.replace(day=1)
        end_day = _shift_month_first(anniv, 1)
    elif level.startswith(_HISTORY_LEVEL_MONTH + "+"):
        start_day = _shift_month_first(anniv, -int(continuation or 0))
        end_day = _shift_month_first(anniv, 1 + int(continuation or 0))
    else:                          # _HISTORY_LEVEL_DAY
        start_day = anniv
        end_day = anniv + datetime.timedelta(days=1)
    return midnight(start_day) - pad, midnight(end_day) + pad


def _next_research_level(level: str, continuation: int) -> tuple[str, int] | None:
    """Следующий уровень исследования (NOST-03.1/3.3): день → неделя →
    месяц → продолжение по факту события с ограничением
    _HISTORY_CONTINUATION_MAX. Уровни — масштабы исследования, а не
    обязательные стадии: вызывающий переходит дальше только когда найденный
    эпизод касается границы текущего окна. None — потолок."""
    if level == _HISTORY_LEVEL_DAY:
        return _HISTORY_LEVEL_WEEK, 0
    if level == _HISTORY_LEVEL_WEEK:
        return _HISTORY_LEVEL_MONTH, 0
    if level == _HISTORY_LEVEL_MONTH:
        if continuation >= _HISTORY_CONTINUATION_MAX:
            return None
        return f"{_HISTORY_LEVEL_MONTH}+1", 1
    if level.startswith(_HISTORY_LEVEL_MONTH + "+"):
        if continuation >= _HISTORY_CONTINUATION_MAX:
            return None
        return f"{_HISTORY_LEVEL_MONTH}+{continuation + 1}", continuation + 1
    return None


def _row_dict(row) -> dict:
    """Строка smart_messages → dict со стабильным message_key (каноническая
    идентичность mca-03; существующий механизм mca_episodes)."""
    d = {k: row_get(row, k) for k in
         ("id", "user_id", "chat_id", "text", "timestamp", "author_name",
          "reply_to_id", "tg_message_id", "is_forward", "forward_source")}
    try:
        d["message_key"] = message_key(d)
    except ValueError:
        d["message_key"] = ""
    return d


def _segment_of_seed(segments: list, seed_keys: set) -> list | None:
    """Сегмент, содержащий ключи-семена (дополнение данных способно только
    СКЛЕИТЬ сегменты, не расщепить: union-find в segment_messages)."""
    best, best_n = None, 0
    for seg in segments:
        n = sum(1 for r in seg if r.get("message_key") in seed_keys)
        if n > best_n:
            best, best_n = seg, n
    return best


def _segment_rows_full(segment: list, by_key: dict) -> list:
    """segment_messages возвращает НОРМАЛИЗОВАННЫЕ slim-строки (message_key/
    timestamp/user_id/reply_to_key). Маппинг обратно на полные dict'ы
    smart_messages по стабильному ключу — рендеру нужны text/provenance/
    author_name. Неизвестный ключ не встречается (сегменты собираются из
    тех же строк); защитно пропускается."""
    out = []
    for r in segment or ():
        full = by_key.get(str(r.get("message_key") or ""))
        if full is not None:
            out.append(full)
    return out


def _segment_touches_window(segment: list, window: tuple[int, int]) -> bool:
    """Продолжение события наружу окна (NOST-03.2 п.4): сегмент касается
    границы окна ближе, чем зазор, которым сегментатор сам закрывает
    сегменты (SEGMENT_GAP_SECONDS). Пока касается — событие может иметь
    продолжение; перестал — расширение останавливается. Временная близость
    сама по себе не склеивает сообщения: решает reply-граф/гэпы
    segment_messages, не расстояние до границы."""
    if not segment:
        return False
    ts = [int(r.get("timestamp") or 0) for r in segment]
    lo, hi = min(ts), max(ts)
    return hi >= int(window[1]) - _SEGMENT_EPS or \
        lo <= int(window[0]) + _SEGMENT_EPS


def _seed_segment(segments: list, anniv: datetime.date, tz,
                  day_bounds: tuple[int, int]) -> list:
    """Выбор сегмента-повода года (детерминированный выбор ПОВОДА, не
    оценка ценности — NOST-05 вне этого слайса): пересекает сам день
    годовщины → больше сообщений этого дня, ничья → более ранний старт;
    иначе (окно шире дня из-за base_days владельца) — сегмент с ближайшим
    к дню годовщины промежутком. Несколько несвязанных обсуждений дня
    остаются отдельными сегментами (segment_messages их не склеивает)."""
    crossing: list = []
    near: list = []
    for seg in segments:
        days = set()
        for r in seg:
            dt = _local_datetime(r.get("timestamp"), tz)
            days.add(dt.date() if dt else None)
        if anniv in days:
            crossing.append(seg)
            continue
        ts = [int(r.get("timestamp") or 0) for r in seg]
        lo, hi = min(ts), max(ts)
        distance = max(0, int(day_bounds[0]) - hi, lo - int(day_bounds[1]))
        near.append((distance, lo, seg))
    if crossing:
        def cross_key(seg):
            n = 0
            for r in seg:
                dt = _local_datetime(r.get("timestamp"), tz)
                if dt and dt.date() == anniv:
                    n += 1
            lo = min(int(r.get("timestamp") or 0) for r in seg)
            return (-n, lo)
        return sorted(crossing, key=cross_key)[0]
    if near:
        near.sort(key=lambda t: (t[0], t[1]))
        return near[0][2]
    return []


def _episode_identity(ep: dict) -> dict:
    """Идентичность эпизода для контроля повторов (NOST-08.2): стабильные
    message_key первого/последнего сообщения (каноническая идентичность
    mca-03) + фактические границы. НЕ текст: один эпизод можно пересказать
    другими словами — идентичность не изменится.

    PROACTIVE NOSTALGIA (2026-11-10): `ref` — ссылка на запись долговременной
    памяти (`story:<id>` / `episode:<id>`), если эпизод пришёл из единого
    retrieval, а не только из реконструкции истории."""
    rows = ep.get("rows") or []
    keys = [str(r.get("message_key") or "") for r in rows]
    keys = [k for k in keys if k]
    return {"first": keys[0] if keys else "",
            "last": keys[-1] if keys else "",
            "start_ts": int(ep.get("start_ts") or 0),
            "end_ts": int(ep.get("end_ts") or 0),
            "year": int(ep.get("year") or 0),
            "ref": str(ep.get("memory_ref") or "")}


def _same_episode(ep: dict, told: dict) -> bool:
    """Тот же эпизод? (детерминированная проверка идентичности, NOST-08.2):
    совпадение ссылки на запись памяти → тот же эпизод; иначе точное
    совпадение границ ключей ИЛИ пересечение фактических диапазонов внутри
    одного года (сегменты непересекающи по времени; пересечение диапазонов =
    то же событие, найденное с чуть другими границами расширения). Буквального
    сравнения текстов нет."""
    if not told:
        return False
    ref = str(ep.get("memory_ref") or "")
    if ref and ref == str(told.get("ref") or ""):
        return True
    ep_first, ep_last = "", ""
    rows = ep.get("rows") or []
    keys = [str(r.get("message_key") or "") for r in rows]
    keys = [k for k in keys if k]
    if keys:
        ep_first, ep_last = keys[0], keys[-1]
    if ep_first and ep_first == str(told.get("first") or "") \
            and ep_last == str(told.get("last") or ""):
        return True
    if int(told.get("year") or 0) != int(ep.get("year") or 0):
        return False
    t_lo, t_hi = int(told.get("start_ts") or 0), int(told.get("end_ts") or 0)
    e_lo = int(ep.get("start_ts") or 0)
    e_hi = int(ep.get("end_ts") or 0)
    return t_lo <= e_hi and e_lo <= t_hi


def _episodes_dedup(cal: list, thematic: list) -> list:
    """Дедуп пула (NOST-06: эпизод может найтись обоими режимами):
    пересечение диапазонов одного года = один эпизод; приоритет — первый
    аргумент, второй дубль выпадает. Порядок входа сохраняется.

    PROACTIVE NOSTALGIA (2026-11-10): вызывающий подаёт ветки в порядке
    «смысловая память → тематическая → календарная», поэтому остаётся карточка
    с смысловой ссылкой (`memory_ref`) и/или тематической связью — календарная
    годовщина перестала быть приоритетным поводом (она даёт период, а не
    первенство)."""
    out: list = []
    for ep in list(cal) + list(thematic):
        if any(_same_episode(ep, kept) for kept in out):
            continue
        out.append(ep)
    return out


def _filter_repeats(pool: list, told: list) -> tuple[list, int]:
    """Исключение недавних опубликованных эпизодов (NOST-08.2).
    Возврат (свежие, число_повторов)."""
    fresh: list = []
    repeats = 0
    for ep in pool:
        if any(_same_episode(ep, t) for t in told):
            repeats += 1
            continue
        fresh.append(ep)
    return fresh, repeats


def _episode_weight(ep: dict, years: set[int]) -> float:
    """Вес эпизода для порядка предъявления (owner corrective 2026-11-10).

    Вес — технический предварительный отбор, не «оценка ценности»: финальное
    решение о публикации остаётся за вердиктом модели (NOST-01/05).

    * relevance — смысловая близость из ЕДИНОГО retrieval (канал episode),
      нормированная к [0,1]; без смыслового попадания остаётся слабый сигнал
      тематического FTS-поиска (не словарь-решатель);
    * coverage — период, который ещё не звучал в недавних воспоминаниях
      (разнообразие по фактам журнала, без квот);
    * usage — эпизод давно не рассказывался (mca usage), повторяемость уже
      исключена до отбора.
    Объём (число сообщений) не участвует — объём ≠ интересность.
    """
    try:
        relevance = float(ep.get("relevance"))
    except (TypeError, ValueError):
        relevance = None
    if relevance is None:
        relevance = (_FALLBACK_TOPICAL_REL if ep.get("topical")
                     else _FALLBACK_OTHER_REL)
    relevance = max(0.0, min(1.0, relevance))
    year = int(ep.get("year") or 0)
    coverage = 0.0 if year in years else _COVERAGE_BONUS
    usage = _USAGE_BONUS if ep.get("usage_stale") else 0.0
    return _RELEVANCE_W * relevance + coverage + usage


def _rank_episodes(pool: list, *, told_years=()) -> list:
    """Порядок предъявления (owner corrective 2026-11-10): взвешенный по
    смысловой релевантности, покрытию периодов и давности использования —
    вместо прежнего «тематическая связь, затем самый свежий год». Ничьи
    разрешаются свежестью периода, затем началом эпизода (детерминированно);
    объём (число сообщений) в порядке не участвует.

    Возврат — НОВЫЙ список (входной не меняется), эпизоды несут
    `weight_score` для честной диагностики прогона."""
    years = {int(y) for y in (told_years or ()) if y}
    scored = []
    for pos, ep in enumerate(pool):
        weight = _episode_weight(ep, years)
        ep["weight_score"] = round(weight, 4)
        scored.append((weight, -int(ep.get("year") or 0),
                       -int(ep.get("start_ts") or 0), pos, ep))
    scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return [item[4] for item in scored]


def _told_years(told: list) -> set[int]:
    """Годы недавно рассказанных эпизодов (покрытие периодов без квот)."""
    years: set[int] = set()
    for item in told or ():
        try:
            year = int((item or {}).get("year") or 0)
        except (TypeError, ValueError):
            continue
        if year:
            years.add(year)
    return years


def _pool_periods(shown: list, tz=None) -> dict:
    """Периоды предъявленного пула (честная диагностика NOST-12): календарные
    годы и фактические границы эпизодов (даты — в часовом поясе чата)."""
    return {"years": sorted({int(e.get("year") or 0) for e in shown}),
            "ranges": [{"from": _ts_date_local(e.get("start_ts"), tz),
                        "to": _ts_date_local(e.get("end_ts"), tz)}
                       for e in shown]}


def _pool_mode(has_cal: bool, has_thematic: bool) -> str | None:
    """Режим пула для диагностики (NOST-06/12): calendar|thematic|mixed."""
    if has_cal and has_thematic:
        return "mixed"
    if has_cal:
        return "calendar"
    if has_thematic:
        return "thematic"
    return None


def _payload_sections(*, episodes: bool, year_lines: bool, golden: bool,
                      lore: bool, memes: bool, context: bool) -> list[str]:
    """Секции, реально попавшие в user-блок LLM (честная диагностика
    NOST-12: какие источники использованы этим прогоном)."""
    out: list[str] = []
    if context:
        out.append("context")
    if episodes:
        out.append("episodes")
    if year_lines:
        out.append("year_lines")
    if golden:
        out.append("golden")
    if lore:
        out.append("lore")
    if memes:
        out.append("memes")
    return out


def _memory_query(rows: list[dict]) -> str:
    """Строка запроса к памяти из содержания текущей беседы.

    Это НЕ триггер и НЕ классификатор: текст последних реплик уходит в
    существующий retrieval как запрос, а решение «есть смысловая связь»
    принимает модель. Пусто → запроса нет."""
    texts = [" ".join(str((r or {}).get("text") or "").split())
             for r in (rows or [])[-6:]]
    return " ".join(t for t in texts if t)[:_MEMORY_QUERY_CAP]


async def memory_candidates(db, memory, chat_id: int, query: str, *,
                            top_k: int = _SEMANTIC_TOP_K
                            ) -> tuple[list[dict], str | None]:
    """Кандидаты-воспоминания из ЕДИНОГО GraphRAG retrieval (канал episode).

    Возврат (кандидаты, код ошибки). Кандидат ссылается на РЕАЛЬНУЮ запись
    памяти (`story:<id>` в mca_stories / `episode:<id>` в mca_episodes) и несёт
    оценку релевантности канала + фактические границы события. Ничего не
    выдумывает: запись, которую нельзя прочитать, отбрасывается.
    Никогда не бросает (fail-open → пусто + код ошибки)."""
    text = " ".join(str(query or "").split())
    if not text:
        return [], None
    try:
        from services import mca_retrieval_context as _rc
        request = _rc.RetrievalRequest(
            chat_id=int(chat_id), query=text, mode="auto",
            channels=_SEMANTIC_CHANNEL, top_k=max(1, int(top_k)))
        result = await _rc.retrieve(db, memory, request)
    except Exception:
        logger.warning("[nostalgia] semantic retrieval failed — пул без "
                       "смысловой ветки | chat_id=%s", chat_id, exc_info=True)
        return [], "retrieval_failed"
    try:
        from services.mca_episodes import EpisodeRepository
        repo = EpisodeRepository(db)
    except Exception:
        return [], "retrieval_failed"
    out: list[dict] = []
    legacy_rows: dict[int, dict] | None = None
    for cand in (getattr(result, "candidates", ()) or ()):
        if str(getattr(cand, "entity_type", "")) != "episode":
            continue
        ref_id = str(getattr(cand, "entity_id", "") or "")
        if not ref_id:
            continue
        score = float(getattr(cand, "score", 0.0) or 0.0)
        story = await repo.get_story(ref_id)
        if story:
            out.append({
                "ref": f"story:{ref_id}", "store": "story", "id": ref_id,
                "score": score,
                "title": str(story.get("title") or ""),
                "summary": str(story.get("summary") or ""),
                "start_ts": int(story.get("event_start_ts") or 0),
                "end_ts": int(story.get("event_end_ts") or 0)})
            continue
        episode = await repo.get_episode(ref_id)
        if episode:
            out.append({
                "ref": f"episode:{ref_id}", "store": "episode",
                "id": ref_id, "score": score,
                "title": str(episode.get("title") or ""),
                "summary": str(episode.get("summary") or ""),
                "start_ts": int(episode.get("event_start_ts") or 0),
                "end_ts": int(episode.get("event_end_ts") or 0),
                "used_at": episode.get("last_used_in_chat_at")})
            continue
        # legacy-история «Темы» (та же таблица lore_stories, что читает канал
        # episode): границы события неизвестны — берётся фактический last_ts
        # темы; сам эпизод всё равно реконструируется из РЕАЛЬНЫХ сообщений.
        if legacy_rows is None:
            try:
                rows = await db.list_lore_stories(int(chat_id), limit=200)
                legacy_rows = {int(r["id"]): dict(r) for r in (rows or ())}
            except Exception:
                legacy_rows = {}
        try:
            legacy = legacy_rows.get(int(ref_id))
        except (TypeError, ValueError):
            legacy = None
        if legacy:
            last_ts = int(legacy.get("last_ts") or 0)
            out.append({
                "ref": f"lore:{ref_id}", "store": "lore", "id": ref_id,
                "score": score,
                "title": str(legacy.get("topic") or ""),
                "summary": str(legacy.get("story") or ""),
                "start_ts": last_ts, "end_ts": last_ts})
    return out, None


async def memory_candidate_by_ref(db, ref: str, *, chat_id: int | None = None
                                  ) -> dict | None:
    """Кандидат памяти по ссылке журнала (`story:<id>`/`episode:<id>`).

    Нужен инициативной ностальгии в живом разговоре: решение уже принято
    общим Observer/Decision, остаётся прочитать ту же запись памяти, о
    которой шла речь. Нет записи → None (ссылка не переизобретается)."""
    text = str(ref or "").strip()
    store, _, ident = text.partition(":")
    if not ident:
        return None
    try:
        from services.mca_episodes import EpisodeRepository
        repo = EpisodeRepository(db)
    except Exception:
        return None
    if store == "story":
        story = await repo.get_story(ident)
        if not story:
            return None
        return {"ref": text, "store": "story", "id": ident, "score": 0.0,
                "title": str(story.get("title") or ""),
                "summary": str(story.get("summary") or ""),
                "start_ts": int(story.get("event_start_ts") or 0),
                "end_ts": int(story.get("event_end_ts") or 0)}
    if store == "episode":
        episode = await repo.get_episode(ident)
        if not episode:
            return None
        return {"ref": text, "store": "episode", "id": ident, "score": 0.0,
                "title": str(episode.get("title") or ""),
                "summary": str(episode.get("summary") or ""),
                "start_ts": int(episode.get("event_start_ts") or 0),
                "end_ts": int(episode.get("event_end_ts") or 0),
                "used_at": episode.get("last_used_in_chat_at")}
    if store == "lore":
        try:
            rows = await db.list_lore_stories(int(chat_id), limit=200)
        except Exception:
            return None
        for row in rows or ():
            data = dict(row)
            if str(data.get("id")) != ident:
                continue
            last_ts = int(data.get("last_ts") or 0)
            return {"ref": text, "store": "lore", "id": ident, "score": 0.0,
                    "title": str(data.get("topic") or ""),
                    "summary": str(data.get("story") or ""),
                    "start_ts": last_ts, "end_ts": last_ts}
        return None
    return None


async def related_memory_hints(db, memory, chat_id: int, query: str, *,
                               limit: int = _MEMORY_HINT_TOTAL
                               ) -> tuple[dict, ...]:
    """Bounded-подсказки реальных записей памяти для Observer.

    Проактивное воспоминание НЕ ищется по словарю тем: Observer видит
    кандидатов из того же GraphRAG retrieval, что и ответы по памяти, и сам
    решает, есть ли смысловая связь. Ничего не связано → пусто (молчание)."""
    try:
        from services import mca_exploration as me
        if not me.master_enabled():
            return ()
        if not await me.use_enabled(db, me.USE_MEMORY_RECALL, chat_id):
            return ()
    except Exception:
        return ()
    candidates, _error = await memory_candidates(
        db, memory, chat_id, query, top_k=max(1, int(limit)))
    hints: list[dict] = []
    for cand in candidates[:max(1, int(limit))]:
        hints.append({
            "ref": cand["ref"],
            "title": str(cand.get("title") or "")[:120],
            "summary": " ".join(str(cand.get("summary") or "").split()
                                )[:_MEMORY_SUMMARY_CHARS],
            "start_ts": int(cand.get("start_ts") or 0)})
    return tuple(hints)


class NostalgiaWorker:
    """Проактивная ностальгия тихих групп (слой B, spec §3.5)."""
    JOB_NOSTALGIA_ID = "nostalgia_tick"

    def __init__(self, db, memory=None, store=None, llm=None, bot=None,
                 bot_id: int | None = None) -> None:
        self.db = db
        self.memory = memory          # MemoryManager (fetch_golden_facts)
        self.store = store            # ChatLoreStore (list_active_chat_ids)
        self.llm = llm                # облачный LLMClient (NFR-1)
        self.bot = bot                # aiogram Bot (Q13: send_message)
        self.bot_id = int(bot_id or 0)
        self._run_lock = asyncio.Lock()
        self._tz_name = str(hot.get("limits.summary_timezone",
                                    settings.SUMMARY_TIMEZONE) or "UTC")
        self._scheduler = AsyncIOScheduler(timezone=self._tz_name)
        # W2: флаги последнего построения пула (честная диагностика NOST-12;
        # воркер однопоточен по _run_lock — состояние не гоняется).
        self._pool_flags: dict = {}

    # ── ключи (hot с фолбэком settings; категория memory, spec §3.6.4) ──

    def _key(self, name: str, default):
        return hot.get(f"memory.nostalgia_{name}", default)

    def _limit(self, name: str, default) -> int:
        return int(self._key(name, default) or 0)

    def _flag(self, name: str, default) -> bool:
        return bool(self._key(name, default))

    # ── служебное (F2-API, spec §3.6.2) ──────────────────────────────────

    @property
    def running(self) -> bool:
        """Идёт ли прогон (ручной run_once/тик) — анти-рейс 409 в API."""
        return self._run_lock.locked()

    # ── планировщик ───────────────────────────────────────────────

    def start(self) -> None:
        """Регистрирует джоб nostalgia_tick ВСЕГДА (P0-followup §2,
        18.10.2026): рубильник проверяется на КАЖДОМ тике и на каждом чате,
        поэтому hot-включение memory.nostalgia_enabled начинает работать без
        рестарта бота. OFF → тик — дешёвый no-op (honest skipped/disabled).
        Повторный start идемпотентен (replace_existing)."""
        enabled_now = self._flag("enabled", settings.NOSTALGIA_ENABLED)
        # Раунд 10 (F-10 §5.2): jitter тика (случайный сдвиг ≤ интервал/3);
        # 0 — если jitter явно не задан (тесты/конфиг без ключа).
        base_minutes = int(self._limit("tick_minutes",
                                       settings.NOSTALGIA_TICK_MINUTES) or 60)
        import random
        try:
            from services import worker_budget
            tick_minutes = base_minutes + (
                random.randint(0, worker_budget.jitter_safe(base_minutes))
                if worker_budget.jitter_active() else 0)
        except Exception:
            tick_minutes = base_minutes
        self._scheduler.add_job(
            self._tick,
            IntervalTrigger(
                minutes=tick_minutes,
                timezone=self._tz_name),
            id=self.JOB_NOSTALGIA_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        if not self._scheduler.running:
            self._scheduler.start()
        logger.info(
            "NostalgiaWorker %s (tick=%smin, silence=%smin, "
            "max_per_day=%s, aggressiveness=%s, flag=%s)",
            "started" if enabled_now
            else "registered (флаг off — ждёт hot-включения)",
            self._limit("tick_minutes", settings.NOSTALGIA_TICK_MINUTES),
            self._limit("min_silence_minutes",
                        settings.NOSTALGIA_MIN_SILENCE_MINUTES),
            self._limit("max_per_day", settings.NOSTALGIA_MAX_PER_DAY),
            self._key("aggressiveness",
                      settings.NOSTALGIA_AGGRESSIVENESS),
            "on" if enabled_now else "off")

    async def stop(self) -> None:
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("NostalgiaWorker stopped")
        except SchedulerNotRunningError:
            logger.info("NostalgiaWorker was not running — nothing to stop")

    # ── точки входа ───────────────────────────────────────────────

    async def _tick(self) -> None:
        """Scheduler-джоб: полный тик по активным PG-чатам. Анти-рейс с
        ручным run_once — _run_lock (одновременно не отправляем)."""
        if self._run_lock.locked():
            return
        async with self._run_lock:
            try:
                await self._run(manual=False)
            except Exception:
                logger.warning(
                    "[nostalgia] tick failed — fail-open", exc_info=True)

    async def run_once(self, chat_id: int | None = None) -> dict:
        """Ручной запуск «сейчас» (будущий F2-API). Kill-switch-флаг
        memory.nostalgia_enabled применяется и здесь (ФИКС R5/F-10 §6 —
        докс-строка «без флага» устарела), все гейты чата соблюдаются
        (сценарии A/B по тишине, quiet hours в B, cooldown/лимиты/Q14 —
        анти-спам ручным запуском не обходится). Идущий прогон →
        {"status": "already_running"}."""
        if self._run_lock.locked():
            return {"status": "already_running"}
        async with self._run_lock:
            try:
                stats = await self._run(manual=True, only_chat=chat_id)
            except Exception:
                logger.warning("[nostalgia] run_once failed — fail-open",
                               exc_info=True)
                return {"status": "error"}
        return {"status": "ok", **stats}

    # ── тик ───────────────────────────────────────────────────────

    async def _run(self, *, manual: bool,
                   only_chat: int | None = None) -> dict:
        """Тик ностальгии (MCA-17 `nostalgia.run`): событие start +
        ОДИН терминальный outcome на прогон (не на каждый чат/гейт).
        R17: только счётчики/коды. Тело — `_run_tick` (без изменений)."""
        started = time.monotonic()
        _emit("nostalgia_run", "start", component=_NOSTALGIA_COMPONENT)
        try:
            stats = await self._run_tick(manual=manual, only_chat=only_chat)
        except Exception:
            _emit("nostalgia_run", "failed",
                  component=_NOSTALGIA_COMPONENT,
                  duration_ms=_ms_since(started))
            raise
        # Внутренний маркер раннего выхода (no-op) не покидает воркер:
        # контракт возврата run_once остаётся бит-в-бит.
        no_op = stats.pop("_no_op", None)
        outcome, reason = _nostalgia_terminal(
            stats, enabled=self._flag("enabled", settings.NOSTALGIA_ENABLED),
            no_op=no_op)
        _emit("nostalgia_run", outcome,
              component=_NOSTALGIA_COMPONENT, reason_code=reason,
              duration_ms=_ms_since(started))
        return stats

    async def _run_tick(self, *, manual: bool,
                        only_chat: int | None = None) -> dict:
        now = _now_ts()
        stats = {"chats": 0, "candidates": 0, "sent": 0, "skipped": 0,
                 "errors": 0}
        # MOD-ACL-UX-01 M2 (§2.1/§2.3.1): глобальный `memory.nostalgia_enabled`
        # — наследуемый ДЕФОЛТ, а не запрет. Раньше здесь был ранний no-op,
        # из-за чего явный чатовый ON при GLOBAL OFF не исполнялся никогда.
        # Теперь тик идёт (дешёвый проход списка чатов), а допустимость
        # каждого чата решает ЕДИНЫЙ резолвер перед дорогими шагами.
        if only_chat is not None:
            chats: list = [int(only_chat)]
        elif self.store is None:
            logger.warning(
                "[nostalgia] tick: store отсутствует (PG-лор) — чатов нет "
                "(no-op, Q13)")
            stats["_no_op"] = "store_missing"     # MCA-17: failed, не «skip»
            return stats
        else:
            try:
                chats = [int(c) for c in
                         await self.store.list_active_chat_ids()]
            except Exception:
                logger.warning(
                    "[nostalgia] tick: PG down/список чатов недоступен — "
                    "no-op (Q13)", exc_info=True)
                stats["_no_op"] = "pg_down"       # MCA-17: failed, не «skip»
                return stats
            if not chats:
                logger.info("[nostalgia] tick: нет активных чатов (no-op)")
                stats["_no_op"] = "no_chats"
                return stats
        for chat_id in chats:
            result = await self._process_chat(chat_id, now, manual=manual)
            stats["chats"] += 1
            stats["candidates"] += result["candidates"]
            stats["sent"] += result["sent"]
            stats["skipped"] += result["skipped"]
            stats["errors"] += result["errors"]
        return stats

    # ── обработка чата ────────────────────────────────────────────

    async def _process_chat(self, chat_id: int, now: int, *,
                            manual: bool) -> dict:
        """Тик одного чата: гейты → кандидаты → порог → LLM → отправка →
        аудит nostalgia_log. Возвращает счётчики; fail-open (NFR-4)."""
        out = {"candidates": 0, "sent": 0, "skipped": 0, "errors": 0}
        try:
            # гейт 1: только группы/супергруппы (chat_id < 0, D-12).
            if chat_id >= 0:
                logger.info("[nostalgia] skip | chat=%s | reason=not_group",
                            chat_id)
                return out
            # ФИКС R5 → MOD-ACL-UX-01 M2: гейт один и он канонический
            # (`gates_enabled`: чатовый выбор → глобальный дефолт). Отдельная
            # проверка глобального `memory.nostalgia_enabled` удалена — она
            # была вторым, более сильным решателем и глушила явный чатовый ON.
            try:
                from services.feature_gates import gates_enabled
                if not await gates_enabled(chat_id, "nostalgia"):
                    logger.warning(
                        "[nostalgia] WARNING skip: gate nostalgia | "
                        "chat=%s", chat_id)
                    await self._log(chat_id, now, "none", None,
                                    "budget_skip",
                                    {"reason": "gate_nostalgia"})
                    return out
            except Exception:
                logger.warning(
                    "[nostalgia] gate check failed — fail-open | "
                    "chat=%s", chat_id, exc_info=True)
            # гейт 2: тишина (юзерские сообщения; истории нет → no_history).
            # P0-followup §2: тишина классифицирует сценарий, а не режет A —
            # свежее окна тишины сообщение = живая беседа (сценарий A:
            # контекстное воспоминание без требования 45 минут тишины);
            # старше → затишье (сценарий B: автономное воспоминание).
            last_ts = await self.db.get_last_user_message_ts(chat_id,
                                                             self.bot_id)
            if last_ts is None:
                logger.info(
                    "[nostalgia] skip | chat=%s | reason=no_history", chat_id)
                return out
            silence_min = int(self._limit(
                "min_silence_minutes",
                settings.NOSTALGIA_MIN_SILENCE_MINUTES) or 0) * 60
            active = last_ts + silence_min > now
            if active:
                logger.info(
                    "[nostalgia] scenario=A (живая беседа) | chat=%s | "
                    "silence=%smin → гейты тишины/quiet hours не применяются",
                    chat_id, (now - last_ts) // 60)
            # гейт 3: quiet hours — только сценарий B (автономное после
            # затишья; в живой беседе чат не спит и сообщение никого не
            # разбудит).
            if not active and self._quiet_hours(now):
                logger.info(
                    "[nostalgia] skip | chat=%s | reason=quiet_hours", chat_id)
                return out
            # гейт 4: cooldown между sent (Q14-формула, ключ cooldown).
            last_sent = await self._last_sent_ts(chat_id)
            cooldown = int(self._limit(
                "cooldown_hours", settings.NOSTALGIA_COOLDOWN_HOURS) or 0)
            if last_sent is not None and last_sent + cooldown * 3600 > now:
                logger.info("[nostalgia] skip | chat=%s | reason=cooldown",
                            chat_id)
                return out
            # гейт 5: дневной лимит (status='sent' за local-сутки; лимит
            # тратят ТОЛЬКО sent — unchanged/empty не считаются).
            day_start = _day_start_ts(now, self._tz_name)
            max_day = int(self._limit("max_per_day",
                                      settings.NOSTALGIA_MAX_PER_DAY) or 0)
            if max_day > 0 and await self.db.count_nostalgia_sent_since(
                    chat_id, day_start) >= max_day:
                logger.info("[nostalgia] skip | chat=%s | reason=max_per_day",
                            chat_id)
                return out
            # гейт 6: Q14-стоп после N неотвеченных подряд (+пауза).
            if await self._unanswered_stop(chat_id, now):
                logger.info(
                    "[nostalgia] skip | chat=%s | reason=unanswered (Q14)",
                    chat_id)
                return out
            # ── дорогие шаги: кандидаты → порог → LLM → отправка ─────
            await self._candidate_llm_send(chat_id, now, out, active=active)
        except Exception:
            logger.warning(
                "[nostalgia] chat tick failed — WARNING, тик жив | "
                "chat_id=%s", chat_id, exc_info=True)
            out["errors"] += 1
        return out

    def _quiet_hours(self, now: int) -> bool:
        """Quiet hours активны, если local-час >= start ИЛИ < end (23..8,
        пересечение полуночи — spec §3.5.3 п.3, edge 20: local summary_tz)."""
        start = int(self._limit("quiet_start_hour",
                                settings.NOSTALGIA_QUIET_START_HOUR) or 0)
        end = int(self._limit("quiet_end_hour",
                              settings.NOSTALGIA_QUIET_END_HOUR) or 0)
        hour = _local_hour(now, self._tz_name)
        return hour >= start or hour < end

    async def _last_sent_ts(self, chat_id: int) -> int | None:
        """ts последнего status='sent' чата (cooldown/пауза Q14)."""
        rows = await self.db.recent_nostalgia_sent(chat_id, None, 1)
        return int(rows[0]["ts"]) if rows else None

    async def _unanswered_stop(self, chat_id: int, now: int) -> bool:
        """Q14 (§3.5.3 п.6, фикс-раунд major/D-17): последние sent чата за
        окно = memory.nostalgia_pause_hours (24 ч) — если подряд
        nostalgia_unanswered_max из них НЕ отвечены (нет юзерских сообщений
        после ts отправки), стоп. Пауза неявная: пока не пройдёт окно
        pause_hours ИЛИ юзер не ответит, условие повторяется на следующих
        тиках (отправки не будет)."""
        pause = int(self._limit("pause_hours",
                                settings.NOSTALGIA_PAUSE_HOURS) or 0)
        window_hours = pause if pause > 0 else _FALLBACK_WINDOW_HOURS
        window = now - window_hours * 3600
        unanswered_max = int(self._limit(
            "unanswered_max", settings.NOSTALGIA_UNANSWERED_MAX) or 0)
        if unanswered_max <= 0:
            return False
        rows = await self.db.recent_nostalgia_sent(
            chat_id, window, unanswered_max + 1)
        consecutive = 0
        for row in rows:
            if await self.db.count_user_messages_after(
                    chat_id, self.bot_id, int(row["ts"])) > 0:
                break                       # эта и более старые отвечены
            consecutive += 1
            if consecutive >= unanswered_max:
                return True
        return False

    # ── кандидаты → порог → LLM → отправка ─────────────────────────

    async def _candidate_llm_send(self, chat_id: int, now: int,
                                  out: dict, *,
                                  active: bool = False,
                                  candidate: dict | None = None,
                                  pick_info: dict | None = None) -> None:
        """Дорогой шаг тика (§3.5.2–3.5.4): кандидат, порог агрессивности,
        1 облачный LLM-вызов, отправка. Все исходы — строка в nostalgia_log
        (status sent/skipped/error). Никогда не бросает (fail-open).
        `active` (P0-followup §2) — сценарий A (живая беседа): пробрасывается
        в user-блок LLM, чтобы преамбула не утверждала «в чате давно тихо».
        `candidate` (owner corrective 2026-11-10) — готовый кандидат
        живого разговора (`recall_in_conversation`): решение о связи уже
        принято общим Observer/Decision, а маршрут (порог, budget, единый
        Writer/SendRecheck, журнал) остаётся ОДИН и тот же."""
        if candidate is None:
            candidate, pick_info = await self._pick_candidate(chat_id, now)
        if candidate is None:
            # Честная диагностика (NOST-12): no_candidates / repeat
            # (все найденные эпизоды уже недавно публиковались) / ошибки
            # источников — фактические данные прогона, не «всегда успех».
            meta = {"reason": (pick_info or {}).get("reason")
                    or "no_candidates"}
            for field in ("mode", "episodes_found", "repeats_skipped",
                          "thematic_error", "archive_error",
                          "calendar_years", "context_messages"):
                value = (pick_info or {}).get(field)
                if value:
                    meta[field] = value
            await self._log(chat_id, now, _KIND_NONE, None, _STATUS_SKIPPED,
                            meta)
            logger.info("[nostalgia] skip | chat=%s | reason=%s",
                        chat_id, meta["reason"])
            return
        out["candidates"] += 1
        candidate["_pool_info"] = dict(pick_info or {})
        threshold = self._threshold()
        # NOST-05: порог агрессивности — технический предварительный отбор
        # ТОЛЬКО слабых «золотых» фактов; исторический пул (годовщины/
        # тематические) не гейтится фиксированной арифметикой происхождения —
        # содержательную пригодность решает типизированный вердикт LLM
        # (NOST-01) в том же вызове.
        if candidate["kind"] != "year_back" \
                and candidate["weight"] < threshold:
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {**self._candidate_meta(candidate),
                             "reason": "threshold",
                             "weight": round(candidate["weight"], 3),
                             "threshold": round(threshold, 3)})
            logger.info(
                "[nostalgia] skip | chat=%s | reason=threshold "
                "(weight=%.2f < %.2f)", chat_id, candidate["weight"],
                threshold)
            return
        # Раунд 10 (F-10 §5): consume до LLM-вызова генерации (global +
        # chat:<id>); False → nostalgia_log status='budget_skip'.
        if not await self._nostalgia_budget_ok(chat_id, candidate["text"]):
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), "budget_skip",
                            {"reason": "budget"})
            out["skipped"] += 1
            logger.warning(
                "[nostalgia] WARNING skip: budget nostalgia | chat=%s",
                chat_id)
            return
        raw = await self._llm_once(candidate, chat_id, active=active)
        if raw is None:
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_ERROR,
                            {"reason": "llm_error"})
            out["errors"] += 1
            return
        # P0 NOSTALGIA REWORK W1 (NOST-01): типизированный вердикт того же
        # вызова. "unchanged" — прежний формальный контракт отказа (skip,
        # дневной лимит не тратится); "say" — реплика со второй строки;
        # "legacy" — ответ без вердикта, трактуется как контент
        # (обратная совместимость). Семантический страж по фразам удалён:
        # содержательное решение — за моделью (вердикт) / Decision.
        verdict, content = parse_nostalgia_answer(raw)
        # NOST-08.2: протокольный номер выбранного блока (SAY <slot>) —
        # для точной записи идентичности рассказанного эпизода в журнал.
        chosen_slot = parse_say_slot(raw)
        if chosen_slot is not None:
            candidate["_chosen_slot"] = chosen_slot
        if verdict == "unchanged":
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {**self._candidate_meta(candidate),
                             "reason": "unchanged", "llm_skipped": True,
                             "protocol": verdict})
            out["skipped"] += 1
            logger.info(
                "[nostalgia] LLM UNCHANGED — skip | chat=%s | kind=%s",
                chat_id, candidate["kind"])
            return
        text = clean_llm_text(content if verdict == "say" else raw,
                              int(self._limit(
                                  "max_send_chars",
                                  settings.NOSTALGIA_MAX_SEND_CHARS) or 400))
        if not text:
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {**self._candidate_meta(candidate),
                             "reason": "empty", "llm_skipped": True,
                             "protocol": verdict})
            out["skipped"] += 1
            logger.info("[nostalgia] empty LLM text — skip | chat=%s",
                        chat_id)
            return
        # CFG-07A-2 (FA-06/G1): не-точное эхо служебного токена UNCHANGED
        # («UNCHANGED, но ...») — брак, а не контент: в чат токен не идёт.
        if contains_unchanged_token(text):
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {**self._candidate_meta(candidate),
                             "reason": "unchanged_echo",
                             "llm_skipped": True, "protocol": verdict})
            out["skipped"] += 1
            logger.info(
                "[nostalgia] UNCHANGED echo — skip | chat=%s | kind=%s",
                chat_id, candidate["kind"])
            return
        meta = {**self._candidate_meta(candidate), "reason": "sent",
                "protocol": verdict}
        # MCA-09 (T-5038, ADR-1028-16 D6): K1+K3 ON → готовый кандидат
        # делегируется в ЕДИНЫЙ Decision/транспорт (source=nostalgia,
        # trigger_kind=nostalgia_due, prepared_text_ref); решение может
        # завершиться silent — честный статус в nostalgia_log (без ложного
        # sent). K1/K3 OFF → legacy direct-send бит-в-бит 2.58.59.
        if _intent_delegation_enabled():
            delegated = await self._delegate_initiative(chat_id, text,
                                                        candidate)
            status = str(delegated.get("status") or "error")
            if status == "sent":
                await self._log(chat_id, now, candidate["kind"],
                                candidate.get("fact_id"), _STATUS_SENT,
                                {**meta, "path": "initiative"})
                out["sent"] += 1
                await self._mark_memory_used(chat_id, candidate)
            elif status == "error":
                # сбой единственного транспорта — честный error (не skip)
                await self._log(
                    chat_id, now, candidate["kind"],
                    candidate.get("fact_id"), _STATUS_ERROR,
                    {**self._candidate_meta(candidate),
                     "reason": "bot_api", "path": "initiative"})
                out["errors"] += 1
            else:
                await self._log(
                    chat_id, now, candidate["kind"],
                    candidate.get("fact_id"), _STATUS_SKIPPED,
                    {**self._candidate_meta(candidate),
                     "reason": f"initiative_{status}"})
                out["skipped"] += 1
                logger.info(
                    "[nostalgia] initiative path | chat=%s | status=%s",
                    chat_id, status)
            return
        # ── INIT-COORD (03.11.2026): legacy-отправка (K1/K3 OFF) идёт через ТУ
        # ЖЕ бронь публикации, что текст/callback-путь и мем: иначе она была
        # невидима для мема, а мем — для неё (спам-пара). Пречек объясняет,
        # бронь решает, `claimed→sending` — ровно перед `send_message`.
        from services import publication_coordination as _pubmod
        publication = await _pubmod.open_text_publication(
            self.db, int(chat_id),
            holder_ref="nostalgia:%s" % (candidate.get("fact_id")
                                         or candidate.get("kind") or "none"))
        refusal = (None if publication.granted
                   else (publication.reason or _pubmod.REASON_CONFLICT))
        if refusal is None:
            refusal = await publication.guard()
        if refusal:
            await publication.close(published=False)
            await self._log(chat_id, now, candidate["kind"],
                            candidate.get("fact_id"), _STATUS_SKIPPED,
                            {**self._candidate_meta(candidate),
                             "reason": "publication_conflict",
                             "detail": str(publication.detail or ""),
                             "coordination": publication.coordination})
            out["skipped"] += 1
            logger.info(
                "[nostalgia] publication conflict — skip | chat=%s | "
                "reason=%s | detail=%s", chat_id, refusal,
                publication.detail or "-")
            return
        published = False
        try:
            if self.bot is None:
                raise RuntimeError("nostalgia: bot instance missing (Q13)")
            await self.bot.send_message(chat_id, text)
            published = True
        except Exception as exc:
            logger.warning(
                "[nostalgia] send failed — error logged | chat=%s | error=%s",
                chat_id, exc)
            await self._log(
                chat_id, now, candidate["kind"], candidate.get("fact_id"),
                _STATUS_ERROR,
                {**self._candidate_meta(candidate),
                 "reason": "bot_api"})
            out["errors"] += 1
            return
        finally:
            await publication.close(published=published)
        await self._log(chat_id, now, candidate["kind"],
                        candidate.get("fact_id"), _STATUS_SENT,
                        {**meta, "coordination": publication.coordination})
        out["sent"] += 1
        await self._mark_memory_used(chat_id, candidate)
        logger.info(
            "[nostalgia] sent | chat=%s | kind=%s | chars=%d",
            chat_id, candidate["kind"], len(text))

    async def _mark_memory_used(self, chat_id: int, candidate: dict) -> None:
        """Отметить ФАКТ доставки записи памяти (mca usage: `last_used_in_chat_at`).

        Нужно разнообразию выбора: «поиск ≠ рассказ», колонка обновляется
        только после подтверждённой отправки. Fail-open — журнал ностальгии
        (nostalgia_log) остаётся главным контролем повторов."""
        refs = [str(e.get("memory_ref") or "")
                for e in (candidate.get("episodes") or ())]
        ids = [ref.split(":", 1)[1] for ref in refs
               if ref.startswith("episode:") and ":" in ref]
        if not ids:
            return
        try:
            from services import mca_exploration as me
            await me.mark_episodes_used_in_chat(
                self.db, ids, chat_id=int(chat_id))
        except Exception:
            logger.warning("[nostalgia] memory usage mark failed | chat=%s",
                           chat_id, exc_info=True)

    async def recall_in_conversation(self, chat_id: int, *,
                                     now: int | None = None,
                                     memory_refs=(), context_rows=None
                                     ) -> dict:
        """Инициативная ностальгия в ЖИВОМ разговоре — §1 контракта
        `plans/features/smart-module-semantic-routing/nostalgia-seam-contract.md`
        (NOSTALGIA SEAM RECONCILED; подпись заморожена).

        Состав по контракту:
          вход   — chat_id, ссылки на РЕАЛЬНЫЕ записи памяти (`memory_refs`,
                   `story:<id>`/`episode:<id>`/`lore:<id>`) и окно текущего
                   разговора; `now` — необязательные детерминированные часы;
          выход  — R17-статус `{"status", "reason_code"}`; допустимые статусы
                   sent/skipped/silent/disabled/error, молчание — нормальный
                   неисключительный исход;
          решает — НЕ шов: публикует Writer/Decision/бронь (как и по тику),
                   шов только материализует эпизод и просит писателя;
          место  — сразу после решения Observer (`_act_on_memory_recall`),
                   без ожидания следующего nostalgia_tick.

        Owner corrective 2026-11-10: решение «в текущей теме есть смысловая
        связь с прошлым» принимает существующий Observer/Decision (он видит
        те же записи памяти); здесь материализуется эпизод из РЕАЛЬНЫХ
        сообщений и текст пишет существующий Writer (NOSTALGIA_PROMPT).
        Публикация — единый `_delegate_initiative` → `handle_initiative`
        (SendRecheck, бронь публикации, настройки чата, вердикт модели).
        Второго пайплайна/пути отправки нет.

        Гейты анти-навязчивости — прежние пользовательские настройки
        (дневной лимит, Q14-стоп неотвеченных, флаг «Ностальгии»); повтор
        исключается журналом. Возврат — R17-статус:
        disabled / skipped / sent / silent / error."""
        stamp = int(now if now is not None else _now_ts())
        try:
            from services.feature_gates import gates_enabled
            if not await gates_enabled(int(chat_id), "nostalgia"):
                return {"status": "disabled", "reason_code": "gate_nostalgia"}
        except Exception:
            logger.warning("[nostalgia] conversation recall gate check "
                           "failed | chat_id=%s", chat_id, exc_info=True)
        day_start = _day_start_ts(stamp, self._tz_name)
        max_day = int(self._limit("max_per_day",
                                  settings.NOSTALGIA_MAX_PER_DAY) or 0)
        if max_day > 0 and await self.db.count_nostalgia_sent_since(
                int(chat_id), day_start) >= max_day:
            return {"status": "skipped", "reason_code": "max_per_day"}
        if await self._unanswered_stop(int(chat_id), stamp):
            return {"status": "skipped", "reason_code": "unanswered"}
        tz = _zone(self._tz_name)
        base_days = int(self._key(
            "year_back_days_window",
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW) or 0) or \
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW
        if not context_rows:
            context_rows, _words = await self._recent_context(int(chat_id))
        told = await self._told_identities(int(chat_id), stamp)
        refs = [str(r) for r in (memory_refs or ()) if str(r or "").strip()]
        episodes: list[dict] = []
        for ref in refs[:_EPISODES_MAX]:
            cand = await memory_candidate_by_ref(self.db, ref,
                                                chat_id=int(chat_id))
            if cand is None:
                continue
            ep = await self._episode_from_memory(
                int(chat_id), cand, tz, base_days)
            if ep is None:
                continue
            if any(_same_episode(ep, t) for t in told):
                continue
            episodes.append(ep)
        if not episodes:
            return {"status": "skipped", "reason_code": "no_relevant_memory"}
        ordered = _rank_episodes(episodes, told_years=_told_years(told))
        shown = ordered[:_EPISODES_MAX]
        names = await self._display_names(
            int(chat_id), [r for ep in shown for r in ep["rows"]])
        now_local = _local_datetime(stamp, tz)
        lines: list[str] = []
        for ep in shown:
            ep["years_ago"] = (now_local.year - ep["year"]) \
                if now_local else 0
            ep["lines"] = self._episode_lines(ep, names, tz)
            ep["start_date"] = _ts_date_local(ep["start_ts"], tz)
            ep["end_date"] = _ts_date_local(ep["end_ts"], tz)
            lines.extend(ep["lines"])
        for i, ep in enumerate(shown, start=1):
            ep["slot"] = i
        candidate = {
            "kind": "memory_recall", "fact_id": None,
            "weight": self._threshold(),
            "text": lines[0] if lines else "",
            "year_lines": lines, "episodes": shown, "golden_lines": [],
            "context_rows": list(context_rows or []),
            "topical": True,
            "_pool_info": {"mode": "conversation",
                           "episodes_found": len(episodes),
                           "episodes_shown": len(shown),
                           "context_messages": len(context_rows or []),
                           "periods": _pool_periods(shown, tz)},
        }
        out = {"candidates": 0, "sent": 0, "skipped": 0, "errors": 0}
        out["candidates"] += 1
        await self._candidate_llm_send(
            int(chat_id), stamp, out, active=True, candidate=candidate,
            pick_info=candidate["_pool_info"])
        if out["sent"]:
            return {"status": "sent"}
        if out["errors"]:
            return {"status": "error"}
        return {"status": "silent"}

    async def _delegate_initiative(self, chat_id: int, text: str,
                                   candidate: dict) -> dict:
        """T-5038: кандидат nostalgia → единый вход инициативы (тот же
        Decision/транспорт; второго контура/пути отправки нет).

        INIT-COORD (03.11.2026): координация публикаций — ТОТ ЖЕ порядок, что у
        наблюдателя: precheck → бронь → `claimed→sending` (`publish_guard`) →
        release. Без него текстовая инициатива и мем видели друг друга только
        по одному журналу и слали парой. Отказ брони = реплики нет; кандидат
        остаётся в пуле (годовщина/тема не «рассказана»).

        Ошибка делегирования → честный `error` (без legacy-фолбэка, чтобы не
        создать второй send-path и не задвоить отправку)."""
        from services import publication_coordination as _pubmod
        ref = "nostalgia:%s" % (candidate.get("fact_id")
                                or candidate.get("kind") or "none")
        publication = await _pubmod.open_text_publication(
            self.db, int(chat_id), holder_ref=ref)
        if not publication.granted:
            logger.info(
                "[nostalgia] publication conflict — no send | chat=%s | "
                "reason=%s | detail=%s", chat_id, publication.reason,
                publication.detail or "-")
            return {"status": "cancelled", "reason_code": publication.reason,
                    "detail": publication.detail,
                    "coordination": publication.coordination}
        status = "error"
        try:
            from services import mca_intents as _mi
            from services.direct_chat_service import handle_initiative
            cand = _mi.candidate_from_trigger(
                trigger_kind="nostalgia_due", chat_id=chat_id,
                source="nostalgia", prepared_text_ref=ref,
                reason_code="default")
            if cand is None:
                return {"status": "disabled"}
            situation = _mi.InitiativeSituation(
                trigger_kind="nostalgia_due", chat_id=chat_id)

            async def _guarded():
                """Свежая проверка чата перед отправкой (§2.5).

                Текст уже сгенерирован, но «Ностальгию» в этом чате могли
                выключить, пока шла генерация: OFF из снимка создания не
                публикует. Причина отказа — машиночитаемый код канонического
                резолвера; кандидат при этом не «рассказан» (остаётся в пуле).
                """
                from services.feature_gates import gate_blocks_publication
                block = await gate_blocks_publication(int(chat_id),
                                                      "nostalgia")
                if block:
                    return block
                return await publication.guard()

            result = await handle_initiative(
                bot=self.bot, chat_id=chat_id, situation=situation,
                candidates=[cand], prepared_text=text, db=self.db,
                publish_guard=_guarded)
            status = str((result or {}).get("status") or "error")
            return result
        except Exception:
            logger.warning("[nostalgia] initiative delegation failed",
                           exc_info=True)
            return {"status": "error"}
        finally:
            await publication.close(published=(status == "sent"))


    @staticmethod
    async def _nostalgia_budget_ok(chat_id: int, text: str) -> bool:
        """F-10 §5: consume global + chat:<id> (calls 1 + tokens est).
        ФИКС R4: приоритетная деградация по global-лимиту (nostalgia падает
        последней — allowed_workers) до consume."""
        from services import worker_budget
        if not await worker_budget.global_degradation_allows("nostalgia"):
            logger.warning(
                "[nostalgia] skip: global budget exhausted — degradation "
                "nostalgia | chat=%s", chat_id)
            return False
        est = worker_budget.estimate_tokens(text)
        ok = await worker_budget.consume(None, "global", "llm_calls", 1)
        if ok:
            ok = await worker_budget.consume(None, "global", "llm_tokens", est)
        if ok:
            ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                             "llm_calls", 1)
        if ok:
            ok = await worker_budget.consume(None, f"chat:{chat_id}",
                                             "llm_tokens", est)
        return ok

    def _threshold(self) -> float:
        """Порог срабатывания (§3.5.2): 0.3 + aggressiveness*0.5
        (aggressiveness зажат в [0, 1]; дефолт 0.3 → порог 0.45)."""
        aggr = max(0.0, min(1.0, float(self._key(
            "aggressiveness", settings.NOSTALGIA_AGGRESSIVENESS) or 0.3)))
        return 0.3 + aggr * 0.5

    async def _semantic_episodes(self, chat_id: int, query: str,
                                 tz, base_days: int) -> tuple[list[dict],
                                                               int, str | None]:
        """Смысловая ветка пула: GraphRAG-кандидаты → РЕАЛЬНЫЕ эпизоды.

        Кандидат retrieval указывает на запись памяти; здесь она
        материализуется в эпизод существующим детерминированным движком
        (`_episode_from_memory`) — никаких выдуманных сообщений. Relevance
        нормируется к [0,1] (лучший кандидат = 1.0). Возврат
        (эпизоды, число кандидатов, код ошибки)."""
        candidates, error = await memory_candidates(
            self.db, self.memory, chat_id, query)
        episodes: list[dict] = []
        for cand in candidates[:_SEMANTIC_MATERIALIZE_MAX]:
            ep = await self._episode_from_memory(chat_id, cand, tz, base_days)
            if ep:
                episodes.append(ep)
        if episodes:
            best = max(float(ep.get("relevance") or 0.0) for ep in episodes)
            for ep in episodes:
                score = float(ep.get("relevance") or 0.0)
                ep["relevance"] = round(score / best, 4) if best > 0 else 0.0
        return episodes, len(candidates), error

    async def _episode_from_memory(self, chat_id: int, cand: dict, tz,
                                   base_days: int) -> dict | None:
        """Запись долговременной памяти → исторический эпизод из реальных
        сообщений.

        Границы события — из самой записи (event_start_ts/event_end_ts); окно
        расширяется только существующим зазором сегментатора. Внутри окна
        берётся сегмент, который действительно покрывает событие
        (`segment_messages`: время + reply-граф + участники), затем эпизод
        достраивается общим движком `_episode_around` (день → неделя →
        месяц → продолжение). Нет реальных сообщений → None (память не
        пересказывается по summary)."""
        start = int(cand.get("start_ts") or 0)
        end = int(cand.get("end_ts") or 0) or start
        if start <= 0:
            return None
        pad = _SEGMENT_EPS * 2
        window = (start - pad, max(start, end) + pad)
        seen: set = set()
        rows, truncated = await self._fetch_window_rows(chat_id, window, seen)
        if not rows:
            return None
        segments = segment_messages(rows)
        best: list = []
        best_n = 0
        for seg in segments:
            n = sum(1 for r in seg
                    if window[0] <= int(r.get("timestamp") or 0) <= window[1])
            if n > best_n:
                best, best_n = seg, n
        seed_keys = {str(r.get("message_key") or "") for r in best}
        if not seed_keys:
            return None
        anchor = _local_datetime(start, tz)
        if anchor is None:
            return None
        card = await self._episode_around(
            chat_id, anchor.date(), seed_keys, tz, base_days,
            seed_rows=(rows, truncated), seen_keys=seen, topical=True)
        if not card:
            return None
        card["memory_ref"] = str(cand.get("ref") or "")
        card["memory_title"] = str(cand.get("title") or "")
        card["relevance"] = float(cand.get("score") or 0.0)
        used_at = cand.get("used_at")
        if used_at:
            age_days = (time.time() - float(used_at)) / 86400.0
            card["usage_stale"] = age_days >= 30
        return card

    async def _direction_pick(self, chat_id: int, ordered: list[int],
                              info: dict) -> int | None:
        """Единственная точка квантового направления (VMQ-ONTO-01) — §3
        контракта `plans/features/smart-module-semantic-routing/
        nostalgia-seam-contract.md` (NOSTALGIA SEAM RECONCILED).

        Контракт по существу (owner corrective 2026-11-10): случайность
        (`RandomSourceService`, purpose `memory_recall`) решает ТОЛЬКО, какой
        из равно допустимых по весу эпизодов займёт граничный слот
        предъявления — направление исследования. Достоверность воспоминания
        (источник — реальные сообщения) и обязанность публикации (вердикт
        модели + общий Decision) не затрагиваются: подмена источника на
        детерминированный меняет только распределение, не результат-истину.
        Нет полосы равенства/источник недоступен → None (детерминированный
        порядок).
        """
        if len(ordered) <= _EPISODES_MAX:
            return None
        pivot = ordered[_EPISODES_MAX - 1]
        band = [i for i in range(_EPISODES_MAX - 1, len(ordered))
                if ordered[i].get("weight_score", 0.0) + 1e-9
                >= pivot.get("weight_score", 0.0) * _DIRECTION_BAND]
        if len(band) < 2:
            return None
        try:
            from services import mca_exploration as me
            allowed, _reason = await me.exploration_allowed(
                self.db, me.PURPOSE_MEMORY_RECALL, chat_id)
            if not allowed:
                return None
            source = me.get_source(self.db)
            result = await source.draw_index(
                len(band), chat_id=chat_id, purpose=me.PURPOSE_MEMORY_RECALL,
                candidates=[str(i) for i in band])
        except Exception:
            logger.warning("[nostalgia] direction draw failed — порядок "
                           "детерминированный | chat_id=%s", chat_id)
            return None
        if result is None or getattr(result, "deferred", False):
            info["direction"] = {"deferred": True,
                                 "reason": str(getattr(result, "reason", "")
                                               or "deferred")}
            return None
        index = getattr(result, "index", None)
        if not isinstance(index, int) or not 0 <= index < len(band):
            return None
        info["direction"] = {
            "band": len(band), "index": index,
            "source": str(getattr(result, "source", "") or ""),
            "purpose": me.PURPOSE_MEMORY_RECALL}
        return band[index]

    async def _pick_candidate(self, chat_id: int, now: int
                              ) -> tuple[dict | None, dict]:
        """Лучший кандидат чата (§3.5.2; P0 REWORK W2, NOST-05/06/08/11).

        Пул (owner corrective 2026-11-10) — три источника ОДНОГО движка
        реконструкции `_episode_around`:
          1. смысловая память: ЕДИНЫЙ GraphRAG retrieval (канал episode,
             `mca_retrieval_context.retrieve`) → реальные записи
             долговременной памяти → эпизод из фактических сообщений;
          2. тематический поиск по всей истории (существующий FTS-путь);
          3. календарные периоды архива (годовщины — покрытие периодов, а не
             «ровно год назад»).
        Порядок предъявления взвешен: смысловая релевантность, покрытие
        периодов, давность использования (см. `_rank_episodes`). Прежний
        приоритет «~год назад» снят: календарный источник даёт периоды, а не
        приоритет. Финальное решение о публикации остаётся за типизированным
        вердиктом модели (NOST-01) и общим Decision; кап предъявления — после
        ранжирования (NOST-11.3).

        NOST-08.2: недавние опубликованные эпизоды исключаются по
        ИДЕНТИЧНОСТИ (ссылка на запись памяти / message_key, не текст); все
        кандидаты — повторы → None + info.reason=repeat (молчание).

        Возврат (кандидат|None, info) — info для честной диагностики
        nostalgia_log (NOST-12). None — кандидатов нет."""
        self._pool_flags = {}
        info: dict = {"reason": "no_candidates"}
        tz = _zone(self._tz_name)
        base_days = int(self._key(
            "year_back_days_window",
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW) or 0) or \
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW
        told = await self._told_identities(chat_id, now)
        told_years = _told_years(told)
        # содержание текущего разговора (NOST-05.3/06): и контекст payload,
        # и запрос к памяти — одно и то же окно беседы
        context_rows, topic_words = await self._recent_context(chat_id)
        query = _memory_query(context_rows) or " ".join(topic_words[:24])
        # 1) смысловая память: релевантность из единого retrieval
        semantic_episodes, semantic_found, semantic_error = \
            await self._semantic_episodes(chat_id, query, tz, base_days)
        info["semantic_found"] = semantic_found
        if semantic_error:
            info["semantic_error"] = semantic_error
        # 2) тематический FTS-путь по всей истории (слабый сигнал)
        thematic_episodes, thematic_error = await self._thematic_episodes(
            chat_id, topic_words, now, context_rows)
        # 3) календарные периоды архива (покрытие периодов)
        cal_episodes = await self._calendar_episodes(chat_id, now)
        topical_side = bool(thematic_episodes or semantic_episodes)
        info["mode"] = _pool_mode(bool(cal_episodes), topical_side)
        info["episodes_found"] = (len(cal_episodes) + len(thematic_episodes)
                                  + len(semantic_episodes))
        if thematic_error:
            info["thematic_error"] = True
        if self._pool_flags.get("archive_error"):
            info["archive_error"] = True
        info["calendar_years"] = list(self._pool_flags.get(
            "calendar_years") or [])
        info["context_messages"] = len(context_rows)
        # дедуп пересечений: смысловая ветка приоритетна (несёт relevance и
        # ссылку на запись памяти), затем тематическая, затем календарная
        pool = _episodes_dedup(
            semantic_episodes, thematic_episodes + cal_episodes)
        # NOST-08.2: исключение недавних повторов по идентичности эпизода
        fresh, repeats = _filter_repeats(pool, told)
        info["repeats_skipped"] = repeats
        if repeats:
            info["reason"] = "repeat"
        if fresh:
            ordered = _rank_episodes(fresh, told_years=told_years)
            chosen_index = await self._direction_pick(chat_id, ordered, info)
            if chosen_index is not None:
                chosen = ordered[chosen_index]
                rest = [e for e in ordered if e is not chosen]
                ordered = rest[:_EPISODES_MAX - 1] + [chosen] \
                    + rest[_EPISODES_MAX - 1:]
            shown = ordered[:_EPISODES_MAX]
            info["episodes_shown"] = len(shown)
            names = await self._display_names(
                chat_id, [r for ep in shown for r in ep["rows"]])
            now_local = _local_datetime(now, tz)
            lines: list[str] = []
            for ep in shown:
                ep["years_ago"] = (now_local.year - ep["year"]) \
                    if now_local else 0
                ep["lines"] = self._episode_lines(ep, names, tz)
                ep["start_date"] = _ts_date_local(ep["start_ts"], tz)
                ep["end_date"] = _ts_date_local(ep["end_ts"], tz)
                lines.extend(ep["lines"])
            info["periods"] = _pool_periods(shown, tz)
            # протокольные номера блоков (NOST-08.2): модель указывает
            # выбранный номер после SAY — журнал получает идентичность
            # ТОЛЬКО выбранного эпизода (голый SAY → все, консервативно)
            for i, ep in enumerate(shown, start=1):
                ep["slot"] = i
            # W1-контракт сохранён: в user-блок попадают ОБА набора —
            # «золотые» подмешиваются к историческому пулу (память полнее).
            golden = await self._golden_rows(chat_id)
            info["golden"] = len(golden)
            candidate = {"kind": "year_back", "fact_id": None,
                         "weight": self._threshold(),
                         "text": lines[0] if lines else "",
                         "year_lines": lines,
                         "episodes": shown,
                         "golden_lines": [format_golden_line(r)
                                          for r in golden],
                         "context_rows": context_rows,
                         "topical": bool(shown[0].get("topical")),
                         }
            return candidate, info
        # исторического пула нет (или всё — повторы) → «золотые» факты
        golden = await self._golden_rows(chat_id)
        info["golden"] = len(golden)
        if not golden:
            return None, info
        best: dict | None = None
        for row in golden:
            weight = 0.3 + 0.05 * max(1, int(row.get("importance") or 0))
            if best is None or weight > best["weight"]:
                best = {"kind": "golden",
                        "fact_id": int(row["id"]),
                        "weight": weight,
                        "text": format_golden_line(row)}
        best["year_lines"] = []
        best["episodes"] = []
        best["golden_lines"] = [format_golden_line(r) for r in golden]
        best["context_rows"] = context_rows
        best["topical"] = False
        return best, info

    async def _recent_context(self, chat_id: int) -> tuple[list[dict],
                                                           list[str]]:
        """Содержание ТЕКУЩЕГО разговора (NOST-05.3/06): последний всплеск
        беседы — от свежего сообщения назад до разрыва >_CONTEXT_GAP_HOURS
        (детерминированная граница «одного разговора»; в тихом чате окно
        «последних N сообщений за всё время» захватило бы годовалые реплики).
        Источник — существующий get_recent_user_messages (окно
        _TOPIC_CONTEXT_MESSAGES — не только «последние 5 отдельными
        словами»). Возврат (строки всплеска ASC, слова-темы для FTS).
        Fail-open: ошибка → ([], [])."""
        try:
            rows = await self.db.get_recent_user_messages(
                chat_id, self.bot_id, _TOPIC_CONTEXT_MESSAGES)
        except Exception:
            logger.warning(
                "[nostalgia] recent context failed — без контекста | "
                "chat_id=%s", chat_id, exc_info=True)
            return [], []
        # dict-строки (рендер/имена ожидают .get; sqlite3.Row → _row_dict)
        dict_rows: list[dict] = []
        for row in rows:                       # DESC: свежее → старее
            d = _row_dict(row)
            if str(d.get("text") or "").strip():
                dict_rows.append(d)
        # всплеск беседы: идём от свежих назад, разрыв > gap завершает
        burst: list[dict] = []
        prev_ts: int | None = None
        for d in dict_rows:
            ts = int(d.get("timestamp") or 0)
            if prev_ts is not None and prev_ts - ts > _CONTEXT_GAP_HOURS * 3600:
                break
            burst.append(d)
            prev_ts = ts
        burst.reverse()                        # ASC: старое → свежее
        words: list[str] = []
        seen: set[str] = set()
        for d in burst:
            for w in _TOPIC_WORD_RE.findall(str(d.get("text") or "").lower()):
                if w not in seen:
                    seen.add(w)
                    words.append(w)
        return burst, words[:_TOPIC_KEYWORDS_CAP]

    async def _thematic_episodes(self, chat_id: int, topic_words: list[str],
                                 now: int,
                                 context_rows: list | None = None
                                 ) -> tuple[list[dict], bool]:
        """Тематический режим (NOST-06/11.1-11.2): события по ВСЕЙ доступной
        истории, связанные с содержанием текущего разговора. Поэтапно:
        FTS-семена (существующий search_messages_fts + build_fts_query —
        тот же путь, что «золотые»; отсутствие второй поисковой системы) →
        группировка в периоды → детализация перспективных периодов тем же
        адаптивным движком `_episode_around` (второго движка нет; сырой
        архив в LLM не идёт). Семена-строки бота исключены (self-echo,
        NOST-07.2); сообщения ТЕКУЩЕГО разговора — не семена (история —
        до текущей беседы). Возврат (эпизоды, ошибка_источника — честная
        деградация NOST-11.4)."""
        if not topic_words:
            return [], False
        try:
            from services.summary_memory import build_fts_query
            match_query = build_fts_query(topic_words)
        except Exception:
            match_query = ""
        if not match_query:
            return [], False
        try:
            seeds = await self.db.search_messages_fts(
                chat_id, match_query, _THEMATIC_SEEDS_MAX, source_kind="any")
        except Exception:
            logger.warning(
                "[nostalgia] thematic search failed — режим пропущен | "
                "chat=%s", chat_id, exc_info=True)
            return [], True
        tz = _zone(self._tz_name)
        base_days = int(self._key(
            "year_back_days_window",
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW) or 0) or \
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW
        # границы текущего разговора: его сообщения — не исторические семена
        context_keys = {str(r.get("message_key") or "")
                        for r in (context_rows or [])}
        context_start = min((int(r.get("timestamp") or 0)
                             for r in (context_rows or []) if r), default=0)
        # self-echo: собственные строки бота — не семена истории
        periods: dict[int, dict] = {}   # локальный год → якорь периода
        for row in seeds:
            uid = row_get(row, "user_id")
            if uid is not None and int(uid) == self.bot_id:
                continue
            ts = row_get(row, "timestamp")
            dt = _local_datetime(ts, tz)
            if dt is None:
                continue
            d = _row_dict(row)
            key = str(d.get("message_key") or "")
            if not key or key in context_keys:
                continue
            if context_start and int(ts) >= context_start:
                continue                # это ещё текущая беседа, не история
            day_key = dt.date().toordinal()
            if day_key not in periods:
                periods[day_key] = {"day": dt.date(), "ts": int(ts),
                                    "seed_keys": {key}}
            else:
                periods[day_key]["seed_keys"].add(key)
        episodes: list[dict] = []
        # select-then-detail: детализируем не каждый семенной период,
        # а самые перспективные (порядок FTS-ранга = порядок семян)
        for p in list(periods.values())[:_THEMATIC_DETAIL_MAX]:
            try:
                ep = await self._episode_around(
                    chat_id, p["day"], p["seed_keys"], tz, base_days,
                    topical=True)
            except Exception:
                logger.warning(
                    "[nostalgia] thematic episode failed — период "
                    "пропущен | chat=%s", chat_id, exc_info=True)
                continue
            if ep:
                episodes.append(ep)
        if periods:
            self._pool_flags["thematic_anchors"] = [
                p["day"].isoformat() for p in
                list(periods.values())[:_THEMATIC_DETAIL_MAX]]
        return episodes, False

    async def _told_identities(self, chat_id: int, now: int) -> list[dict]:
        """Идентичности НЕДАВНО опубликованных эпизодов (NOST-08.2):
        существующий журнал отправки (recent_nostalgia_sent, окно
        _REPEAT_LOOKBACK_DAYS и последние _REPEAT_LOOKBACK_SENT строк) —
        meta.episode_ids пишутся при отправке. Не текстовое сравнение:
        identity = стабильные message_key/границы эпизода. Fail-open → []."""
        lookback = int(now) - _REPEAT_LOOKBACK_DAYS * 86400
        try:
            rows = await self.db.recent_nostalgia_sent(
                chat_id, lookback, _REPEAT_LOOKBACK_SENT)
        except Exception:
            logger.warning(
                "[nostalgia] told journal failed — повторы не проверяются "
                "| chat=%s", chat_id, exc_info=True)
            return []
        out: list[dict] = []
        for row in rows:
            try:
                meta = json.loads(str(row_get(row, "meta") or ""))
            except (TypeError, ValueError):
                continue
            for eid in (meta or {}).get("episode_ids") or []:
                if isinstance(eid, dict):
                    out.append(eid)
            # PROACTIVE NOSTALGIA (2026-11-10): ссылки на записи памяти,
            # рассказанные в прошлый раз — тот же эпизод не рассказывается
            # повторно, даже если сегмент реконструкции сместился.
            for ref in (meta or {}).get("memory_refs") or []:
                if isinstance(ref, str) and ref:
                    out.append({"ref": ref})
        return out

    async def _historical_lines(self, chat_id: int,
                                now: int) -> tuple[list[str], list[dict]]:
        """Исторический пул чата (NOST-02/03/04): эпизоды календарных
        годовщин по ВСЕМ годам фактического архива чата
        (get_chat_history_bounds — динамический список лет, без жёсткой
        конструкции «три запроса по году»; отсутствие материалов за год не
        ошибка и не обрыв поиска). Возврат (строки_пула, эпизоды); строки —
        рендер первичных сообщений (provenance сохранён), эпизоды —
        честные карточки для диагностики. Пусто — повода нет.
        W2: полный пул строит `_calendar_episodes` (без капа и рендера —
        его забирает `_episode_pool` с тематическим режимом и ранжированием
        NOST-05/06/08); здесь — кап предъявления и рендер (контракт W1)."""
        episodes = await self._calendar_episodes(chat_id, now)
        if not episodes:
            return [], []
        episodes.sort(key=lambda e: e["year"], reverse=True)  # свежие выше
        episodes = episodes[:_EPISODES_MAX]
        names = await self._display_names(
            chat_id, [r for ep in episodes for r in ep["rows"]])
        tz = _zone(self._tz_name)
        now_local = _local_datetime(now, tz)
        lines: list[str] = []
        for ep in episodes:
            ep["years_ago"] = (now_local.year - ep["year"]) \
                if now_local else 0
            ep["lines"] = self._episode_lines(ep, names, tz)
            # даты-заголовки эпизода — в часовом поясе чата (NOST-02.2)
            ep["start_date"] = _ts_date_local(ep["start_ts"], tz)
            ep["end_date"] = _ts_date_local(ep["end_ts"], tz)
            lines.extend(ep["lines"])
        return lines, episodes

    async def _calendar_episodes(self, chat_id: int,
                                 now: int) -> list[dict]:
        """Календарный режим (полный пул без капа/рендера, W2): эпизоды
        годовщин по всем годам архива с учётом глубины поиска
        (memory.nostalgia_history_depth_years: 0 = весь доступный архив,
        >0 — ограничение глубины в годах; NOST-12). Год пропущен/ошибка
        источника — год пропускается, поиск живёт (NOST-11.4)."""
        tz = _zone(self._tz_name)
        now_local = _local_datetime(now, tz)
        if now_local is None:
            return []
        try:
            bounds = await self.db.get_chat_history_bounds(chat_id)
        except Exception:
            logger.warning(
                "[nostalgia] archive bounds failed — без исторического "
                "пула | chat=%s", chat_id, exc_info=True)
            self._pool_flags["archive_error"] = True
            return []
        if not bounds:
            return []
        min_local = _local_datetime(int(bounds[0]), tz)
        if min_local is None:
            return []
        base_days = int(self._key(
            "year_back_days_window",
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW) or 0) or \
            settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW
        today = now_local.date()
        episodes: list[dict] = []
        # Динамические годы: от первого года архива до прошлого года
        # (текущий год — не «прошлое»; частичный первый год — не ошибка).
        # Глубина (NOST-12): необязательное ограничение «последними N годами».
        years = list(range(min_local.year, now_local.year))
        depth = self._limit("history_depth_years",
                            settings.NOSTALGIA_HISTORY_DEPTH_YEARS)
        if depth > 0:
            years = years[-depth:]
        self._pool_flags["calendar_years"] = list(years)
        for year in years:
            try:
                ep = await self._year_episode(chat_id, year, today, tz,
                                              base_days)
            except Exception:
                logger.warning(
                    "[nostalgia] year episode failed — год пропущен | "
                    "chat=%s | year=%s", chat_id, year, exc_info=True)
                continue
            if ep:
                episodes.append(ep)
        return episodes

    async def _year_episode(self, chat_id: int, year: int,
                            today: datetime.date, tz,
                            base_days: int) -> dict | None:
        """Эпизод годовщины одного исторического года (NOST-02/03/04):
        календарное окно → существующий детерминированный сегментатор
        mca_episodes.segment_messages (время + reply-граф + участники;
        несвязанные обсуждения не склеиваются) → адаптивное расширение окна
        день → неделя → месяц → продолжение, ПОКА сегмент касается границы
        окна; сегмент закрыт — событие завершилось, расширение останавливается
        (NOST-03.2). Эпизод может быть одним сообщением (NOST-04: минимум
        нет). None — в этом году повода нет (не ошибка, NOST-02.1).
        W2: реконструкция — общий движок `_episode_around` (тематический
        режим NOST-06 использует тот же лестничный механизм)."""
        anniv = _anniversary_date(today, year)
        day_bounds = _anniversary_window(anniv, tz, _HISTORY_LEVEL_DAY, 0, 0)
        window = _anniversary_window(anniv, tz, _HISTORY_LEVEL_DAY, 0,
                                     base_days)
        seen: set[str] = set()
        rows, truncated = await self._fetch_window_rows(chat_id, window, seen)
        if not rows:
            return None
        segments = segment_messages(rows)
        seed_keys = {r["message_key"] for r in
                     _seed_segment(segments, anniv, tz, day_bounds)}
        return await self._episode_around(
            chat_id, anniv, seed_keys, tz, base_days,
            seed_rows=(rows, truncated), seen_keys=seen)

    async def _episode_around(self, chat_id: int, anchor_day: datetime.date,
                              seed_keys: set, tz, base_days: int, *,
                              seed_rows: tuple[list[dict], bool] | None = None,
                              seen_keys: set | None = None,
                              fetch_limit: int | None = None,
                              topical: bool = False) -> dict | None:
        """Общий адаптивный движок реконструкции эпизода вокруг якорного дня
        (NOST-06: один движок для календарного и тематического режимов):
        лестница день → неделя → месяц → продолжение (существующие
        `_anniversary_window`/`_next_research_level`/`_segment_touches_window`),
        расширение — только пока сегмент семян касается границы окна.
        `seed_rows` — предзагруженные строки первого окна (календарный путь
        уже fetched их для выбора повода); `topical` — технический признак
        тематического происхождения (порядок предъявления, не оценка
        ценности — NOST-05)."""
        seen: set = seen_keys if seen_keys is not None else set()
        level, continuation = _HISTORY_LEVEL_DAY, 0
        window = _anniversary_window(anchor_day, tz, level, continuation,
                                     base_days)
        if seed_rows is not None:
            rows, truncated = seed_rows
        else:
            rows, truncated = await self._fetch_window_rows(
                chat_id, window, seen, fetch_limit)
        if not rows:
            return None
        by_key = {str(r.get("message_key") or ""): r for r in rows}
        segments = segment_messages(rows)
        while True:
            seg = _segment_of_seed(segments, seed_keys)
            if not seg or not _segment_touches_window(seg, window):
                break
            nxt = _next_research_level(level, continuation)
            if nxt is None:
                break                     # потолок продолжения (уровень D)
            level, continuation = nxt
            window = _anniversary_window(anchor_day, tz, level, continuation,
                                         base_days)
            more, tr = await self._fetch_window_rows(chat_id, window, seen,
                                                     fetch_limit)
            truncated = truncated or tr
            if not more:
                break
            rows = rows + more
            by_key.update({str(r.get("message_key") or ""): r for r in more})
            segments = segment_messages(rows)
        seg = _segment_of_seed(segments, seed_keys) or []
        full_seg = _segment_rows_full(seg, by_key)
        if not full_seg:
            return None
        card = self._episode_card(full_seg, anchor_day.year, level,
                                  continuation, window, truncated)
        card["topical"] = bool(topical)
        return card

    async def _fetch_window_rows(self, chat_id: int,
                                 window: tuple[int, int],
                                 seen_keys: set,
                                 limit: int | None = None
                                 ) -> tuple[list[dict], bool]:
        """Выборка сырых сообщений окна (get_chat_history_messages; бот-строки
        исключены — NOST-07.2 self-echo) с дедупом по стабильному ключу
        (overlap расширений не дублирует сообщения). truncated — окно
        усечено лимитом (честный признак в карточке).
        NOST-11.3 (W2): плотное окно (>лимита) НЕ прижимается к голове
        периода — стратификация по времени: окно делится на равные страты
        (≤_STRATA_MAX), каждая даёт своё начало; выборка покрывает весь
        исследуемый период. Fail-open: ошибка источника → пусто (NOST-11.4:
        недоступность одного источника не останавливает систему).
        `limit=None` → модульный кап _WINDOW_FETCH_LIMIT на момент ВЫЗОВА
        (тесты подменяют кап атрибутом модуля)."""
        if limit is None:
            limit = _WINDOW_FETCH_LIMIT
        lo, hi = int(window[0]), int(window[1])
        total: int | None = None
        try:
            total = await self.db.count_chat_history_messages(
                chat_id, lo, hi, self.bot_id)
        except Exception:
            total = None               # фолбэк: прежняя однократная выборка
        try:
            if total is not None and total > limit:
                rows = await self._fetch_window_stratified(
                    chat_id, lo, hi, total, limit, seen_keys)
                return rows, True
            rows = await self.db.get_chat_history_messages(
                chat_id, lo, hi, limit, self.bot_id)
        except Exception:
            logger.warning(
                "[nostalgia] history window fetch failed — окно пропущено "
                "| chat=%s", chat_id, exc_info=True)
            return [], False
        out: list[dict] = []
        for row in rows:
            d = _row_dict(row)
            key = str(d.get("message_key") or "")
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(d)
        return out, len(rows) >= limit

    async def _fetch_window_stratified(self, chat_id: int, lo: int, hi: int,
                                       total: int, limit: int,
                                       seen_keys: set) -> list[dict]:
        """Стратифицированная выборка плотного окна (NOST-11.3): равные
        временные страты, каждая отдаёт своё начало (детерминированно,
        индекс (chat_id, timestamp)); дедуп общий с расширениями. Выборка
        покрывает период, а не только его удобную для ORDER BY часть."""
        strata = min(_STRATA_MAX, max(1, limit))
        per = max(1, limit // strata)
        span = max(1, hi - lo)
        out: list[dict] = []
        for i in range(strata):
            s_lo = lo + i * span // strata
            s_hi = lo + (i + 1) * span // strata if i < strata - 1 else hi
            try:
                rows = await self.db.get_chat_history_messages(
                    chat_id, s_lo, s_hi, per, self.bot_id)
            except Exception:
                logger.warning(
                    "[nostalgia] stratum fetch failed — страта пропущена "
                    "| chat=%s | stratum=%s", chat_id, i, exc_info=True)
                continue
            for row in rows:
                d = _row_dict(row)
                key = str(d.get("message_key") or "")
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                out.append(d)
        return out

    def _episode_card(self, seg: list, year: int, level: str,
                      continuation: int, window: tuple[int, int],
                      truncated: bool) -> dict:
        """Карточка эпизода для пула/диагностики: фактические границы
        найденного сегмента (не календарной обрезки), достигнутый уровень
        исследования, счётчики. Строки рендерятся позже (после отбора
        ≤_EPISODES_MAX эпизодов) — rename-кэш алиасов строится один раз."""
        ordered = sorted(seg, key=lambda r: (int(r.get("timestamp") or 0),
                                             str(r.get("message_key") or "")))
        ts = [int(r.get("timestamp") or 0) for r in ordered]
        level_label = level if continuation <= 0 else f"{level}+{continuation}"
        return {"year": year,
                "level": level_label,
                "start_ts": min(ts),
                "end_ts": max(ts),
                "messages": len(ordered),
                "truncated": bool(truncated),
                "window": (int(window[0]), int(window[1])),
                "rows": ordered}

    def _episode_lines(self, ep: dict, display_names: dict,
                       tz=None) -> list[str]:
        """Строки эпизода для LLM/лога (рендер format_year_back_line —
        provenance «Переслано» и имена по uid; W2: даты строк — в часовом
        поясе чата, review-w1 nonblocking 1). Кап _EPISODE_LINES_MAX:
        голова+хвост хронологии (длинный эпизод не теряет начало и финал);
        полный счётчик — в карточке (nostalgia_log)."""
        lines = [l for l in (format_year_back_line(r, display_names, tz)
                             for r in ep["rows"]) if l]
        if len(lines) > _EPISODE_LINES_MAX:
            half = _EPISODE_LINES_MAX // 2
            lines = lines[:half] + lines[-half:]
        return lines

    async def _display_names(self, chat_id: int, rows: list) -> dict:
        """Актуальные имена участников по Telegram user_id (NOST-07.3):
        единый каскад summary_aliases (алиас чата → глобальный). Исторический
        author_name строк не подменяет алиасы и сам остаётся фолбэком рендера
        (старые имена пригодны, актуальные — приоритетны). Резолвер отдал
        сам id → имени нет (не выдумываем «автора 12345»; прецедент
        direct_chat). Fail-open: без резолвера — historical-рендер."""
        uids = sorted({int(r.get("user_id")) for r in rows
                       if r.get("user_id") not in (None, 0)})
        if not uids:
            return {}
        try:
            from services.summary_aliases import build_alias_resolver
            resolver = await build_alias_resolver(chat_id)
        except Exception:
            logger.warning(
                "[nostalgia] alias resolver failed — имена по author_name "
                "| chat=%s", chat_id, exc_info=True)
            return {}
        names: dict[int, str] = {}
        for uid in uids:
            try:
                name = str(resolver.resolve(uid) or "").strip()
            except Exception:
                continue
            if name and name != str(uid):
                names[uid] = name
        return names

    async def _golden_rows(self, chat_id: int) -> list:
        """«Золотые» по последней теме (§3.5.2): ключи (слова len≥5) последних
        5 юзерских сообщений → memory.fetch_golden_facts (importance ≥ порога,
        давность ≥ порога; ≤2 факта). memory отсутствует → [] (слабый слой —
        «год назад» достаточно)."""
        if self.memory is None:
            logger.info(
                "[nostalgia] memory недоступен — golden candidates пусты | "
                "chat_id=%s", chat_id)
            return []
        rows = await self.db.get_recent_user_messages(
            chat_id, self.bot_id, _TOPIC_MESSAGES)
        words: list[str] = []
        for row in reversed(rows):               # ASC: старое → свежее
            words.extend(_TOPIC_WORD_RE.findall(
                str(row["text"] or "").lower()))
        seen: set[str] = set()
        keywords = [w for w in words if not (w in seen or seen.add(w))] \
            [:_TOPIC_KEYWORDS_CAP]
        if not keywords:
            return []
        return await self.memory.fetch_golden_facts(
            chat_id, " ".join(keywords),
            min_importance=int(self._limit(
                "golden_min_importance",
                settings.NOSTALGIA_GOLDEN_MIN_IMPORTANCE) or 0),
            min_age_days=int(self._limit(
                "golden_min_days", settings.NOSTALGIA_GOLDEN_MIN_DAYS) or 0),
            limit=_GOLDEN_FACT_LIMIT)

    async def _worker_llm(self, messages: list[dict],
                          temperature: float | None = None) -> str:
        """F3/T-1439 (spec §5, рекомендовано): выделенная LLM роли
        background с фоллбэком на `generate` (моки/старые клиенты)."""
        worker_fn = getattr(self.llm, "generate_worker", None)
        if callable(worker_fn):
            return await worker_fn("background", messages,
                                   temperature=temperature)
        return await self.llm.generate(messages, temperature=temperature)

    async def _llm_once(self, candidate: dict, chat_id: int, *,
                        active: bool = False) -> str | None:
        """1 облачный LLM-вызов (NFR-1: только LLMClient-путь бота;
        локальная LLM запрещена — лимит владельца). Инжект round 10.15
        (spec §4): в user-блок добавляются Лор чата (manual → auto из
        профиля store) и локальные мемы (db.list_chat_memes); сбор — fail-open
        (ошибка источника → секция опускается). Возвращает текст ответа или
        None (ошибка/llm отсутствует — fail-open). `active` (P0-followup §2):
        сценарий A → преамбула «живая беседа» вместо «давно тихо»."""
        if self.llm is None:
            logger.warning("[nostalgia] llm отсутствует — нечего вызвать")
            return None
        lore_text = ""
        if self.store is not None:
            try:
                prof = await self.store.get_profile(chat_id)
                if prof is not None:
                    lore_text = prof.manual_lore or prof.auto_lore or ""
            except Exception:
                logger.warning(
                    "[nostalgia] lore fetch failed — без лора | chat_id=%s",
                    chat_id, exc_info=True)
                lore_text = ""
        memes: list = []
        try:
            memes = await self.db.list_chat_memes(
                chat_id, None, limit=_MEMES_LIMIT)
        except Exception:
            logger.warning(
                "[nostalgia] memes fetch failed — без мемов | chat_id=%s",
                chat_id, exc_info=True)
            memes = []
        context_lines: list[str] = []
        context_rows = candidate.get("context_rows") or []
        if context_rows:
            names = await self._display_names(chat_id, context_rows)
            tz = _zone(self._tz_name)
            # свежие реплики в конце диалога — последние N строк
            for row in context_rows[-_CONTEXT_PAYLOAD_MAX:]:
                line = format_year_back_line(row, names, tz)
                if line:
                    context_lines.append(line)
        user_text = build_nostalgia_user(
            candidate.get("year_lines") or [],
            candidate.get("golden_lines") or [],
            lore=lore_text, memes=memes, active=active,
            episodes=candidate.get("episodes") or [],
            context_lines=context_lines)
        candidate["payload_sections"] = _payload_sections(
            episodes=bool(candidate.get("episodes") or []),
            year_lines=bool(candidate.get("year_lines") or []),
            golden=bool(candidate.get("golden_lines") or []),
            lore=bool(lore_text), memes=bool(memes),
            context=bool(context_lines))
        if not user_text:
            return None
        # SOUL-AMD.2.6 (W4): воспоминание — авторский текст бота. Композер ON
        # → Core + жанровая рамка «Ностальгия» (SOUL-02/AMD.2.1); OFF →
        # прежний канон байт-в-байт (паритет W2). P0-followup §2: на ON-пути
        # база — NOSTALGIA_CORE_CANON (без тонально-личных утверждений,
        # конкурирующих с Core); функциональный контракт UNCHANGED остаётся
        # (служебное слово отказа сохраняется в любом режиме).
        # W2 (NOST-09.2): скрытая квота {max_words} из канонов удалена —
        # длина реплики ограничена ТОЛЬКО пользовательской настройкой
        # nostalgia_max_send_chars (clean_llm_text).
        try:
            from services import mca_authorial_speech as _authorial
            system_text, _manifest = await _authorial.authorial_system(
                chat_id=int(chat_id), writer="nostalgia_writer",
                genre="nostalgia",
                legacy_canon=NOSTALGIA_PROMPT,
                core_canon=NOSTALGIA_CORE_CANON)
        except Exception:
            logger.warning("[nostalgia] authorial system build failed — "
                           "прежний канон | chat_id=%s", chat_id,
                           exc_info=True)
            system_text = NOSTALGIA_PROMPT
        try:
            raw = await self._worker_llm([
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ], temperature=0.7)
        except Exception as exc:
            logger.warning(
                "[nostalgia] LLM call failed — error | error=%s", exc)
            # UR-26.3: транспортный сбой стадии nostalgia-Writer виден
            # кодом события (не молчаливый skip).
            _tpe.emit_stage(
                _tpe.STAGE_NOSTALGIA_TEXT, outcome="error", chat_id=chat_id,
                model=_tpe.llm_model(self.llm),
                provider=_tpe.llm_provider(self.llm),
                finish_reason="llm_error", decision="nostalgia_llm_error",
                clock={"clock_included": False,
                       "skip_reason": "nostalgia_by_design_no_clock"})
            return None
        # UR-26.3: payload-событие nostalgia-Writer. Подготовленный текст НЕ
        # получает вымышленного времени: ChatClock-блок в payload стадии
        # отсутствует BY DESIGN (исторические даты эпизодов идут в своём
        # поясе из данных, UR-27), и событие честно фиксирует это
        # отсутствие + digest произведённого текста (R17: без текста).
        _tpe.emit_stage(
            _tpe.STAGE_NOSTALGIA_TEXT, outcome="success", chat_id=chat_id,
            model=_tpe.llm_model(self.llm),
            provider=_tpe.llm_provider(self.llm),
            finish_reason="generated", chars=len(str(raw or "")),
            text_digest=_tpe.text_digest(str(raw or "")),
            decision="nostalgia_generated",
            clock={"clock_included": False,
                   "skip_reason": "nostalgia_by_design_no_clock"})
        return str(raw or "")

    async def _log(self, chat_id: int, ts: int, kind: str,
                   fact_id: int | None, status: str, meta: dict) -> None:
        """Строка nostalgia_log (fail-open: сбой лога — WARNING, тик жив)."""
        try:
            await self.db.log_nostalgia(
                chat_id, int(ts), kind=kind, fact_id=fact_id,
                status=status,
                meta=json.dumps(meta, ensure_ascii=False, default=str))
        except Exception:
            logger.warning(
                "[nostalgia] log failed — fail-open | chat_id=%s",
                chat_id, exc_info=True)

    @staticmethod
    def _candidate_meta(candidate: dict) -> dict:
        """Meta-поля кандидата для nostalgia_log.
        FIX-CORRECTIVE-R1 (nostalgia-audit §1/§5.3, 21.10.2026): раньше в
        `candidate_text` попадала ТОЛЬКО первая строка пула (year_lines[0]),
        а LLM получал весь пул ≤3 строк — построчная сверка финал↔источник
        по логу была невозможна (слепое пятно аудита). Теперь лог несёт
        ПОЛНЫЙ пул (year_lines + golden_lines).
        P0 REWORK W1 (подготовка диагностики NOST-12): `episodes` — честные
        карточки найденных эпизодов (год, фактические границы, уровень
        исследования, число сообщений, признак усечения окна).
        P0 REWORK W2 (NOST-12): диагностика фактического прогона — режим
        пула, исследованные годы, найдено/показано эпизодов, исключённые
        повторы, ошибки источников, секции payload; `episode_ids` —
        идентичности предъявленных эпизодов (пишутся при отправке,
        читаются `_told_identities` — контроль повторов NOST-08.2)."""
        meta = {"candidate": candidate.get("kind"),
                "candidate_text": candidate.get("text")}
        year_lines = candidate.get("year_lines") or []
        golden_lines = candidate.get("golden_lines") or []
        episodes = candidate.get("episodes") or []
        if year_lines:
            meta["year_lines"] = list(year_lines)
        if golden_lines:
            meta["golden_lines"] = list(golden_lines)
        if episodes:
            meta["episodes"] = [{"years_ago": e.get("years_ago"),
                                 "from": e.get("start_date"),
                                 "to": e.get("end_date"),
                                 "messages": e.get("messages"),
                                 "level": e.get("level"),
                                 "truncated": e.get("truncated"),
                                 "topical": bool(e.get("topical")),
                                 "relevance": e.get("relevance"),
                                 "weight": e.get("weight_score"),
                                 "memory_ref": e.get("memory_ref") or ""}
                                for e in episodes]
            # NOST-08.2: идентичности ДЛЯ ЖУРНАЛА ПОВТОРОВ. Модель указала
            # валидный номер блока (SAY <slot>) → только выбранный эпизод;
            # номер не указан/невалиден → все предъявленные (консервативно:
            # неизвестно, какой использован).
            slot = candidate.get("_chosen_slot")
            chosen = None
            if slot is not None:
                for e in episodes:
                    if e.get("slot") == slot:
                        chosen = e
                        break
            targets = [chosen] if chosen is not None else episodes
            meta["episode_ids"] = [_episode_identity(e) for e in targets]
            refs = [str(e.get("memory_ref") or "") for e in targets]
            refs = [ref for ref in dict.fromkeys(refs) if ref]
            if refs:
                meta["memory_refs"] = refs
            if chosen is None and len(episodes) > 1:
                meta["episode_slot_unknown"] = True
        info = candidate.get("_pool_info") or {}
        for field in ("mode", "episodes_found", "episodes_shown",
                      "repeats_skipped", "thematic_error", "archive_error",
                      "semantic_error", "semantic_found", "calendar_years",
                      "context_messages", "periods", "direction", "topical"):
            value = info.get(field)
            if value:
                meta[field] = value
        payload_sections = candidate.get("payload_sections")
        if payload_sections:
            meta["payload_sections"] = list(payload_sections)
        return meta
