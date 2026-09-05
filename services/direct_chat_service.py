"""Epic 50 — DirectChatService (Section 58, D200/D203-D207).

DirectChatThrottle — Token Bucket (58.5): per (chat_id, user_id), in-memory,
рестарт сбрасывает (прецедент CooldownTracker); полное восстановление
зарядов через CHAT_COOLDOWN_SECONDS после ПОСЛЕДНЕГО допущенного обращения.
Epic 60 (63.1): persistent-версия — services/persistent_throttling.PersistentThrottle
(таблица throttle_state, UPSERT, стена time.time); handle() принимает и sync-
(in-memory fallback), и async-инстанс (asyncio.iscoroutine).

DirectChatService — сборка контекст-секций (58.6), generate через
build_messages (58.9/59.3), bot_replies (персистентная таблица, TTL 3600 /
cap 200 — Epic 60, 63.1) для цепочек <Conversation_Thread>, fire-and-forget
memorize_facts с origin='bot_direct_reply' (58.8) ПОСЛЕ успешной отправки.

Epic 53 (Section 62.3.3, D216): CB-обёртка LLMCircuitBreaker — OPEN → фраза
CHAT_LLM_DOWN_PHRASES БЕЗ вызова LLM; транзиентные классы инкрементят CB;
успех (в т.ч. фоллбэка) сбрасывает CB. Скоуп — только direct_chat.

Epic 60 (Section 63.2, R60-2, T-461): per-chat asyncio.Lock вокруг генерации
ПОСЛЕ throttle/CB-веток (мгновенные — не стоят в очереди); таймаут
CHAT_LOCK_WAIT_SECONDS → CHAT_LOCK_BUSY_PHRASES; FIFO → порядок ответов.

Epic 60 (Section 65, Фаза C, T-469…T-478): 🗿-молчание на пустой ответ
(65.1), стачка кулдаунов → молчание (65.3), <style_anchors> (65.4), команды
/clear /persona /tone /forget (65.5), typing-индикатор (65.7), temperature-
пресеты из user_prefs (65.8), mood-блок (65.9), protected_facts (65.10).

Epic 60 (Section 66, Фаза D, T-487/T-490): /persona <имя> — карточка человека
из графа (66.9); бюджеты контекста — доли от CHAT_CONTEXT_BUDGET_TOKENS с
порядком урезания (66.12); порядок секций и промпты НЕ меняются.

Раунд 8 (Context-Layer X-Features, spec.md; T-791…T-803 частично):
  * B2 (T-791): реордер user-блока «важное к концу» — map → branch → rag →
    global → thread → target → protected → lore → mood → current → anchors →
    sandwich; бюджет на effective-базе (неприкосновенные: target/protected/
    lore/current/sandwich), новая доля branch, порядок урезания
    anchors→rag→thread→global(keep-head)→map.
  * C1/C3/C5 (T-792/T-794/T-796): uid-рендеры «{имя} [{uid}]» / «{имя} [bot]»
    во внутренних строках (global/thread/branch) и <Target_User>; карта
    остаётся «{имя} — {uid}»; дискриминатор коллизий display-имён —
    ТОЛЬКО на рендере контекста (чистые пути суффиксов не содержат).
  * C2 (T-793): карта по активным участникам (24 ч) + участники окна.
  * C6 (T-797): memorize-хук «кто спрашивал» + пост-фаза: факты про третьих
    лиц (subject/object из карты участников) не приписываются спрашивающему.
  * D1 (T-798): блок <Current_Question> (срез префикса «бот/@ник», кап).
  * D3/D4 (T-800/T-801): thread сквозь бот-ответы (bot_reply_parents) +
    <Conversation_Branch> (reply-ветка ≥ 2 ходов, без LLM).
  * D5 (T-802): метки-строки свежести в начале <Global_Context>.
  * D2/E1 (T-799/T-803): global держит голову (конспект не режется первым),
    importance-удержание verbatim-строк (флаг chat_importance_keep_enabled).
  * E2/E4 (T-804/T-806): инжект level-2 («широкий фон: …», keep-end кап) в
    <Global_Context> при L1+L2; конспект читается без TTL-смерти.
  * F1-F4 (T-807…T-810): direct-RAG — факты rel-порядка (get_rag_facts),
    словарный дедуп против <Global_Context> (dedup_rag_vs_global),
    origin-метки «[{label}] {date}» (origin_labels), опциональный LLM-реранк
    (flags.chat_rag_rerank_enabled, fail-open).
"""
import asyncio
import hashlib
import logging
import random
import re
import time

from config.settings import settings
from services import chat_access
from services import hot_config as hot
from services.chat_prompts import CHAT_SYSTEM_PROMPT
from services.llm_client import (
    LLMBadResponseError,
    LLMError,
    LLMServerError,
    LLMTimeoutError,
    LLMTransportError,
)
from services.llm_circuit_breaker import STATE_HALF_OPEN, LLMCircuitBreaker
from services.payload_builder import build_messages
from services.persistent_throttling import SilenceStreak
from services.smartmodule_phrases import (
    CHAT_COOLDOWN_PHRASES,
    CHAT_ERROR_PHRASES,
    CHAT_LLM_DOWN_PHRASES,
    CHAT_LOCK_BUSY_PHRASES,
)
from services.smartmodule_throttling import format_remaining_time
from services.smartmodule_utils import _reply, react_moai, send_chunked_reply
from services.smart_cache import normalize_text
from services.summary_memory import build_rag_context, dedup_rag_vs_global, fire_and_forget
from services.summary_xml import escape_xml_text
from services.token_counter import (
    count_tokens,
    resolve_chat_limit,
    safe_budget,
    truncate_to_tokens,
    truncate_to_tokens_keep_head,
)
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext
from services.tool_schemas import TOOL_CALLING_TOOLS
from services.typing_manager import typing_active

logger = logging.getLogger(__name__)

_PERSONA_MAX_ITEMS = 10          # 66.9: карточка — до 10 фактов/связей
# Раунд 3 (3.7/C1, T-696): анти-залипание style_anchors («сцуко»-инцидент).
_STYLE_ANCHOR_LOOKBACK = 5       # буфер выборки поверх count (ищем «разные»)
_STICKY_MIN_WORD_LEN = 3         # короче — не «слово-префикс» (a/и/в…)
_STICKY_MIN_FREQ = 2             # >=2 из окна = залипший префикс
_BLOCK_RE = re.compile(          # 66.12: блок «<Tag>\n…\n</Tag>» (тело для обрезки)
    r"^(<[A-Za-z_]+>\n)(.*)(\n</[A-Za-z_]+>)\s*$", re.DOTALL)
# Раунд 8 (B2/FR-23, п.25): sandwich-строка — финальное напоминание в конце
# user-блока (последняя строка контента; в лимиты бюджета НЕ входит).
_SANDWICH_REMINDER = (
    "отвечай коротко, по делу, на последний вопрос (<Current_Question>); "
    "людей называй именами из карты, без скобок и номеров")
# Раунд 8 (D1/T-798): срез префикса обращения «бот(:)»/«@ник(:)» в начале
# сообщения для <Current_Question> (зеркало _PEER_PREFIX_RE хендлера
# handlers/direct_chat.py:307-308; поведение память-команд не меняется).
_PEER_PREFIX_RE = re.compile(
    r"^(?:(?:бот(?:ина|яра|ик)?|@[\w_]+)[,:]?\s+)+", re.IGNORECASE)


def _parse_mood_words(raw: str) -> tuple[str, ...]:
    """65.9: comma-separated env → кортеж слов (нижний регистр)."""
    return tuple(w.strip().lower() for w in str(raw or "").split(",") if w.strip())


def _strip_direct_prefix(text: str) -> str:
    """Раунд 8 (D1/T-798): текст запроса после срезания обращения к боту —
    «бот(:)», «@никнейм(:)» и пробелов в начале (тот же цикл, что хендлер
    память-команд). Остаток ровно равный обращению («бот», «бот,», «@ник»)
    → "" (блок <Current_Question> не рендерится)."""
    s = str(text or "").strip()
    while True:
        m = _PEER_PREFIX_RE.match(s)
        if not m:
            break
        s = s[m.end():].strip()
    if re.fullmatch(r"(?:бот(?:ина|яра|ик)?|@[\w_]+)[,:]?", s, re.IGNORECASE):
        return ""
    return s


def _speaker_tag(name: str, uid, *, is_bot: bool = False,
                 suffix: str = "") -> str:
    """Раунд 8 (§3.0/C1): display-строка участника для внутренних рендеров —
    «{имя}{суффикс} [{uid}]» (бот — «{имя} [bot]»). uid None/0 → без скобки.
    suffix — дискриминатор коллизии (C3), пуст при отсутствии коллизии."""
    rendered = f"{name}{suffix}"
    if is_bot:
        return f"{rendered} [bot]"
    if uid not in (None, 0):
        return f"{rendered} [{uid}]"
    return rendered


def _collision_suffix(uid: int, username: str | None = None) -> str:
    """Раунд 8 (C3/T-794): дискриминатор для второго и последующих участников
    с одинаковым display: « ({username})» без @ — если юзернейм известен;
    иначе « (#{последние 4 цифры uid})». Чистые пути суффиксов не содержат —
    дискриминация ТОЛЬКО на этапе рендера контекста (NFR-2)."""
    if username:
        return f" ({str(username).lstrip('@')})"
    return f" (#{str(uid)[-4:]})"


def _line_markers(line: str, names: frozenset[str]) -> frozenset[str]:
    """Раунд 8 (E1/T-803): маркеры важности строки (без LLM) — по
    содержательной части (после speaker-префикса «имя: »), чтобы имя автора
    не делало «важными» любые реплики:
      name   — display/канон участника карты в тексте;
      bot    — «бот»/«[bot]»;
      quote  — кавычки/елочки/апострофы-цитата;
      number — содержит число;
      qmark  — заканчивается на «?»;
      long   — ≥ 3 слов.
    Возвращает подмножество маркеров."""
    text = str(line or "")
    idx = text.find(":")
    content = text[idx + 1:].strip() if idx != -1 else text
    markers: set[str] = set()
    low = content.casefold()
    if any(n in low for n in names):
        markers.add("name")
    if "бот" in low or "[bot]" in low:
        markers.add("bot")
    if any(q in content for q in ('"', "«", "»", "“", "”", "'")):
        markers.add("quote")
    if re.search(r"\d", content):
        markers.add("number")
    if content.rstrip().endswith("?"):
        markers.add("qmark")
    if len(content.split()) >= 3:
        markers.add("long")
    return frozenset(markers)


def trim_verbatim_lines(lines: list[str], max_units: int, *,
                        names: frozenset[str] = frozenset(),
                        keep_important: bool = True,
                        measure=None) -> list[str]:
    """Раунд 8 (E1/T-803): обрезка verbatim-строк ДО лимита с importance-
    удержанием (порядок ASC сохраняется, строки НЕ переупорядочиваются).
    Жертва — всегда со стороны НАЧАЛА диапазона (старое):
      1) самая старая строка без маркеров («шум»);
      2) самая старая с ровно одним слабым маркером (число/«?»/≥3 слов);
      3) самая старая строка вообще (дальше — резерв токен-обрезания головы).
    keep_important=False → ровно старое поведение: срез с начала списка до
    лимита (без маркер-фильтра). measure — count_tokens (токены) или len
    (символы, chars-ветка D2)."""
    if measure is None:
        measure = count_tokens
    kept = list(lines)
    if not keep_important:
        while kept and measure("\n".join(kept)) > max_units:
            kept.pop(0)
        return kept
    strong = frozenset(("name", "bot", "quote"))
    weak = frozenset(("number", "qmark", "long"))

    def bucket(line: str) -> int:
        markers = _line_markers(line, names)
        if not markers:
            return 0                      # шум — первым
        if not (markers & strong) and len(markers & weak) == 1:
            return 1                      # ровно один слабый маркер
        return 2                          # сильные/неоднозначные — последними

    while kept and measure("\n".join(kept)) > max_units:
        for target in (0, 1, 2):
            victim_idx = None
            for i, line in enumerate(kept):
                if bucket(line) == target:
                    victim_idx = i
                    break
            if victim_idx is not None:
                kept.pop(victim_idx)
                break
        else:
            kept.pop(0)                   # теоретически недостижимо
    return kept


class DirectChatThrottle:
    """Token Bucket (R50-7): per (chat_id, user_id). In-memory; рестарт сбрасывает
    (принято, прецедент CooldownTracker smartmodule_throttling.py). Полное
    восстановление зарядов через CHAT_COOLDOWN_SECONDS после ПОСЛЕДНЕГО
    допущенного обращения. Однопоточный event loop — asyncio.Lock НЕ нужен
    (прецедент CooldownTracker)."""

    def __init__(self, burst_limit: int, cooldown_seconds: float) -> None:
        self._limit = burst_limit
        self._cooldown = cooldown_seconds
        self._state: dict[tuple[int, int], tuple[int, float]] = {}   # (chat_id, user_id) -> (burst_left, last_ts)

    def allow(self, chat_id: int, user_id: int) -> float:
        """0.0 = допустимо (заряд списан); >0 = остаток кулдауна, сек (фраза R50-7)."""
        now = time.monotonic()
        state = self._state.get((chat_id, user_id))
        if state is None or now - state[1] >= self._cooldown:
            burst = self._limit                       # полное восстановление
        else:
            burst = state[0]
        if burst <= 0:
            return max(1.0, self._cooldown - (now - state[1]))   # ceil-по-остатку
        self._state[(chat_id, user_id)] = (burst - 1, now)
        return 0.0


class DirectChatService:
    """Контекст-партишн (58.6) + ответ строго Reply-ом (58.4) + memorize-hook."""

    def __init__(self, memory, db, llm, aliases, throttle=None,
                 bot_id: int | None = None, bot_username: str | None = None,
                 breaker=None, cache=None, tool_router=None,
                 chat_lore_cache=None) -> None:
        self.memory = memory
        self.db = db
        self.llm = llm
        self.aliases = aliases
        # Эпик 04.09.2026 (3.3, FR-17): tool_router=None → ровно старое
        # поведение (generate без tools); настроен — диалог идёт через
        # chat_with_tools (цикл tool_calls, финальный текст как обычно).
        self.tool_router = tool_router
        self.throttle = throttle or DirectChatThrottle(
            hot.get("limits.chat_burst_limit", settings.CHAT_BURST_LIMIT), hot.get("limits.chat_cooldown_seconds", settings.CHAT_COOLDOWN_SECONDS))
        self.bot_id = bot_id
        self.bot_username = (bot_username or "").lower()
        # Epic 53 (62.3.3): CB-обёртка direct_chat. breaker инжектируем для
        # тестов; None → автогенерация из settings (LLM_CB_ENABLED).
        self._breaker = breaker if breaker is not None else (
            LLMCircuitBreaker(
                hot.get("models.llm_cb_failure_threshold", settings.LLM_CB_FAILURE_THRESHOLD),
                hot.get("models.llm_cb_cooldown_seconds", settings.LLM_CB_COOLDOWN_SECONDS),
            ) if hot.get("flags.llm_cb_enabled", settings.LLM_CB_ENABLED) else None
        )
        # Epic 60 (63.2, T-461): per-chat замки генерации. Словарь — под
        # своим локом; ленивая чистка незалоченных при переполнении.
        # T-501: pending-счётчик ожидантов per-lock (инкремент ДО выхода из
        # guard) — ленивая чистка не выселяет лок, на котором корутина ещё
        # не успела войти в acquire (иначе гонка: два «владельца» чата).
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._chat_locks_guard = asyncio.Lock()
        self._chat_lock_pending: dict[asyncio.Lock, int] = {}
        # Epic 60 (65.3, T-471): стачка кулдаунов (throttle_state scope=
        # 'direct_silence'); persistent при рубильнике Фазы A, иначе — memory.
        self.silence_streak = SilenceStreak(
            hot.get("limits.chat_cooldown_seconds", settings.CHAT_COOLDOWN_SECONDS),
            db if hot.get("flags.throttle_persistent_enabled", settings.THROTTLE_PERSISTENT_ENABLED) else None)
        # Epic 60 (65.9, T-477): слова настроения — comma-separated env
        # (правило п.49: никаких списков в коде).
        self._mood_negative = _parse_mood_words(settings.CHAT_MOOD_NEGATIVE_WORDS)
        self._mood_positive = _parse_mood_words(settings.CHAT_MOOD_POSITIVE_WORDS)
        # Epic 60 (67.4, T-499): дедуп одинаковых текстов подряд. cache
        # инжектится из bot.py (get_smart_cache()); None → фича неактивна
        # (прецедент DI-тестов), env-рубильник CHAT_DEDUP_ENABLED — свой.
        self._cache = cache
        # Раунд 7 (chat-lore-management-v2, T-781/F1): PG-лор чатов —
        # опциональный ChatLoreCache (None → выключено → старое поведение;
        # тесты и вызовы без инжекта не меняются; spec §3.9).
        self.chat_lore_cache = chat_lore_cache
        self._lore_cache_errors = 0       # дедуп WARNING (раз в 50 попыток)

    # ── bot_replies (персистентная таблица; TTL 3600/cap 200 — 63.1) ──

    async def remember_bot_reply(self, chat_id: int, tg_message_id: int,
                                 text: str,
                                 parent_tg_message_id: int | None = None) -> None:
        """UPSERT ответа бота в bot_replies ПОСЛЕ успешной отправки (58.6).
        Раунд 8 (D3/T-800): + parent-линк «на какое сообщение отвечал бот»
        (bot_reply_parents) — thread-walk продолжает цепочку сквозь бот-ответы.
        Fail-open: ошибка БД — WARNING, цепочка просто не запомнится."""
        try:
            await self.db.upsert_bot_reply(chat_id, tg_message_id, text, time.time())
            await self.db.set_bot_reply_parent(
                chat_id, tg_message_id, parent_tg_message_id, time.time())
        except Exception:
            logger.warning(
                "direct: bot_replies persist failed | chat=%s msg=%s",
                chat_id, tg_message_id, exc_info=True)

    async def _bot_reply_parent(self, chat_id: int,
                                tg_message_id: int) -> int | None:
        """Раунд 8 (D3): parent-сообщение бот-ответа (ленивый TTL в БД).
        Fail-open → None (цепочка оборвётся на боте — обратная совместимость)."""
        try:
            return await self.db.get_bot_reply_parent(
                chat_id, tg_message_id, time.time())
        except Exception:
            logger.warning(
                "direct: bot_reply_parents read failed | chat=%s msg=%s",
                chat_id, tg_message_id, exc_info=True)
            return None

    async def get_bot_reply(self, chat_id: int, tg_message_id: int) -> str | None:
        """Текст ответа бота из bot_replies (ленивый TTL на чтении).
        Fail-open → None (цепочка <Conversation_Thread> оборвётся)."""
        try:
            return await self.db.get_bot_reply(chat_id, tg_message_id, time.time())
        except Exception:
            logger.warning(
                "direct: bot_replies read failed | chat=%s msg=%s",
                chat_id, tg_message_id, exc_info=True)
            return None

    # ── Per-chat замок генерации (R60-2, 63.2, T-461) ──────────────

    async def _get_chat_lock(self, chat_id: int) -> asyncio.Lock:
        """asyncio.Lock per chat_id (FIFO → порядок ответов). Чистка ленивая:
        при len > CHAT_LOCK_MAX_ENTRIES — удалить незалоченные БЕЗ ожидающих
        (T-501: pending>0 — корутина вышла из guard, но ещё не вошла в
        acquire; eviction такого лока подменил бы объект → два владельца)."""
        async with self._chat_locks_guard:
            lock = self._chat_locks.get(chat_id)
            if lock is None:
                lock = self._chat_locks[chat_id] = asyncio.Lock()
            self._chat_lock_pending[lock] = (
                self._chat_lock_pending.get(lock, 0) + 1)
            if len(self._chat_locks) > hot.get("limits.chat_lock_max_entries",
                                               settings.CHAT_LOCK_MAX_ENTRIES):
                for cid, candidate in list(self._chat_locks.items()):
                    if cid == chat_id or candidate.locked():
                        continue
                    if self._chat_lock_pending.get(candidate, 0) > 0:
                        continue
                    del self._chat_locks[cid]
                    self._chat_lock_pending.pop(candidate, None)
            return lock

    def _drop_chat_lock_pending(self, lock: asyncio.Lock) -> None:
        """T-501: снять одну бронь ожиданта. Вызывается после разрешения
        acquire-попытки: успех → лок уже locked() (чистке не подлежит),
        таймаут → корутина ушла. Нулевой счётчик удаляется."""
        remaining = self._chat_lock_pending.get(lock, 0) - 1
        if remaining > 0:
            self._chat_lock_pending[lock] = remaining
        else:
            self._chat_lock_pending.pop(lock, None)

    # ── Поток хендлера (58.4) ─────────────────────────────────

    async def handle(self, bot, message, user) -> None:
        """Триггер уже проверен хендлером. Кулдаун → фраза R50-7; иначе —
        контекст → LLM → Reply → memorize (fire-and-forget, ПОСЛЕ отправки).
        Epic 60 (63.2): генерация — под per-chat замком (после throttle/CB)."""
        chat_id = message.chat.id
        user_id = user.id if user is not None else 0
        target_name = self._resolve_name(user)
        query = (message.text or "").strip()
        remaining = self.throttle.allow(chat_id, user_id)
        if asyncio.iscoroutine(remaining):
            remaining = await remaining   # persistent-троттлинг (63.1)
        if remaining > 0:
            # Epic 60 (65.3, T-471): стачка кулдаунов подряд → при достижении
            # CHAT_SILENCE_AFTER_COOLDOWNS — МОЛЧАНИЕ (без фразы R50-7).
            # T-619: флаги — горячие точки (фолбек settings).
            if hot.get("flags.chat_silence_enabled", settings.CHAT_SILENCE_ENABLED):
                streak = await self.silence_streak.bump(chat_id, user_id)
                if streak >= hot.get("limits.chat_silence_after_cooldowns",
                                     settings.CHAT_SILENCE_AFTER_COOLDOWNS):
                    logger.warning(
                        "[direct] silent after %d cooldowns | chat=%s user=%s",
                        streak, chat_id, target_name)
                    return
            phrase = random.choice(CHAT_COOLDOWN_PHRASES).replace(
                "{remaining_time}", format_remaining_time(remaining))
            await _reply(bot, chat_id, phrase, message.message_id)
            logger.warning("[direct] cooldown | chat=%s user=%s remaining=%.0fs",
                           chat_id, target_name, remaining)
            return
        # Epic 60 (65.3): успешный допуск сбрасывает стачку.
        if hot.get("flags.chat_silence_enabled", settings.CHAT_SILENCE_ENABLED):
            await self.silence_streak.reset(chat_id, user_id)
        logger.info("[direct] triggered | chat=%s user=%s", chat_id, target_name)
        # Epic 53 (62.3.3): CB OPEN → БЕЗ вызова LLM (0 запросов в апстрим),
        # сразу человеческая фраза CHAT_LLM_DOWN_PHRASES. Throttle-заряд уже
        # списан (троттлинг остаётся нижней защитой, 62.1 в.5).
        if self._breaker is not None and not self._breaker.allow_request():
            logger.warning("[direct] circuit breaker open | chat=%s user=%s",
                           chat_id, target_name)
            await _reply(bot, chat_id, random.choice(CHAT_LLM_DOWN_PHRASES),
                         message.message_id)
            return
        # Epic 60 (63.2, T-461): замок ПОСЛЕ throttle/CB-веток (мгновенные,
        # не стоят в очереди); таймаут ожидания → CHAT_LOCK_BUSY_PHRASES.
        lock = await self._get_chat_lock(chat_id)
        try:
            async with asyncio.timeout(
                    hot.get("limits.chat_lock_wait_seconds",
                            settings.CHAT_LOCK_WAIT_SECONDS)):
                await lock.acquire()
        except (asyncio.TimeoutError, TimeoutError):
            self._drop_chat_lock_pending(lock)   # T-501: бронь снята
            logger.warning("direct: lock wait timeout | chat=%s user=%s",
                           chat_id, target_name)
            await _reply(bot, chat_id, random.choice(CHAT_LOCK_BUSY_PHRASES),
                         message.message_id)
            return
        self._drop_chat_lock_pending(lock)   # успех: лок locked(), чистке не подлежит
        answer_text: str | None = None
        dedup_key = None
        try:
            # Epic 60 (67.4, T-499): дедуп одинаковых текстов подряд (п.8) —
            # ПОСЛЕ throttle/CB/замка (D237: троттлинг остаётся первым
            # барьером), ПЕРЕД сборкой контекста. Ключ «чат+человек+текст»;
            # payload — сохранённый ответ → повторная отправка; "" — прошлый
            # раз без ответа → молчание; None (первый раз/TTL истёк) — обычный
            # поток. Внутри try/finally: ранний return обязан отпустить замок.
            if self._cache is not None and hot.get(
                    "flags.chat_dedup_enabled", settings.CHAT_DEDUP_ENABLED) \
                    and query:
                dedup_key = hashlib.md5(
                    f"direct_dedup\x00{chat_id}\x00{user_id}\x00"
                    f"{normalize_text(query)}".encode("utf-8")
                ).hexdigest()
                cached = await self._cache.get_dedup(dedup_key)
                if cached is not None:
                    dedup_key = None          # исход уже решён — finally не перезапишет
                    if cached:
                        replay_id = await send_chunked_reply(
                            bot, chat_id, cached, message.message_id)
                        if replay_id is not None:
                            # D3/T-800: parent = сообщение, на которое реплика
                            await self.remember_bot_reply(
                                chat_id, replay_id, cached,
                                parent_tg_message_id=message.message_id)
                        logger.info("[direct] dedup replay | chat=%s user=%s",
                                    chat_id, target_name)
                    else:
                        logger.info("[direct] dedup silence | chat=%s user=%s",
                                    chat_id, target_name)
                    return
            user_blocks = await self._build_user_content(
                chat_id, message, target_name,
                target_user_id=(user_id or None))
            # T-619: системный промпт — горячая точка (фолбек код-канона)
            system_prompt = hot.get("prompts.direct_chat_system_prompt",
                                    CHAT_SYSTEM_PROMPT)
            payload = build_messages(system_prompt, user_blocks)
            # Epic 60 (65.8, T-476): temperature-пресет юзера (user_prefs)
            # или дефолт. Другие пайплайны — без temperature (65.8).
            temperature = settings.tone_temperature(
                await self._get_tone_preset(chat_id, user_id))
            # Epic 60 (65.7, T-475): «печатает…» вокруг LLM-точки, без паузы.
            # Эпик 04.09.2026 (3.3): при настроенном tool_router генерация идёт
            # циклом chat_with_tools (модель сама решает вызвать инструменты);
            # ошибки/пустые финалы — те же классы, ветки except ниже без правок.
            try:
                async with typing_active(bot, chat_id):
                    if self.tool_router is not None:
                        raw = await chat_with_tools(
                            self.llm, payload, tools=TOOL_CALLING_TOOLS,
                            router=self.tool_router,
                            ctx=ToolContext(chat_id, query),
                            temperature=temperature)
                    else:
                        raw = await self.llm.generate(payload,
                                                      temperature=temperature)
            except LLMBadResponseError as exc:
                # Epic 60 (65.1, T-469): модель ЖИВА, но ответила пустым →
                # молчание + 🗿 (НЕ R13-фраза, НЕ заглушка). Ветка ДО
                # except LLMError — R13-эталоны байт-в-байт.
                logger.warning(
                    "[direct] empty answer — silence | chat=%s user=%s | error=%s",
                    chat_id, target_name, exc)
                await react_moai(bot, chat_id, message.message_id)
                return
            answer = str(raw).strip()
            if not answer:
                logger.warning(
                    "[direct] empty answer — silence | chat=%s user=%s",
                    chat_id, target_name)
                await react_moai(bot, chat_id, message.message_id)
                return
            sent_id = await send_chunked_reply(bot, chat_id, answer, message.message_id)
            if sent_id is not None:
                answer_text = answer
                # D3/T-800: parent = сообщение, на которое бот ответил
                await self.remember_bot_reply(
                    chat_id, sent_id, answer,
                    parent_tg_message_id=message.message_id)
                # REVISE S2: memorize ТОЛЬКО ПОСЛЕ успешной отправки (58.8) —
                # fire-and-forget внутри гейта sent_id. Раунд 8 (C6/T-797):
                # wrapper с пост-фазой «факты про третьих лиц не приписываются
                # спрашивающему» (target_user уже = канон автора запроса).
                fire_and_forget(
                    self._memorize_direct_reply(chat_id, query, answer,
                                                target_name),
                    "direct")
            logger.info("[direct] reply sent | chat=%s user=%s", chat_id, target_name)
            # Epic 53 (62.3.3): успех (в т.ч. фоллбэка) → полный сброс CB.
            if self._breaker is not None:
                self._breaker.on_success()
        except LLMError as exc:
            logger.warning("[direct] LLM failed | chat=%s | user=%s | error=%s",
                           chat_id, target_name, exc)
            await _reply(bot, chat_id, random.choice(CHAT_ERROR_PHRASES),
                         message.message_id)
            # Epic 53 (62.3.3): транзиентные классы → инкремент CB. Если CB в
            # HALF_OPEN — текущий вызов и есть пробная генерация: ЛЮБОЙ LLMError
            # пробы (в т.ч. не-транзиентный: апстрим ответил 4xx/auth) снова
            # открывает CB, чтобы он не залип в HALF_OPEN навсегда.
            if self._breaker is not None:
                if isinstance(exc, (LLMTimeoutError, LLMServerError, LLMTransportError)):
                    self._breaker.on_failure()
                elif self._breaker.state == STATE_HALF_OPEN:
                    self._breaker.on_failure()
        except Exception:
            logger.exception("[direct] unexpected | chat=%s", chat_id)
            await _reply(bot, chat_id, random.choice(CHAT_ERROR_PHRASES),
                         message.message_id)
            # H1: пробная генерация в HALF_OPEN, упавшая НЕ-LLMError (БД в
            # _build_user_content, TelegramRetryAfter и пр.), снова открывает
            # CB — иначе CB залипнет в HALF_OPEN навсегда (allow_request в
            # HALF_OPEN всегда False, пробная уже израсходована).
            if self._breaker is not None and self._breaker.state == STATE_HALF_OPEN:
                self._breaker.on_failure()
        finally:
            lock.release()
            # Epic 60 (67.4, T-499): исход попытки — в дедуп-кэш: успешный
            # ответ → payload-ответ (повтор получит его из кэша); ЛЮБОЙ
            # неуспех (🗿-пустой/LLMError/исключение/send fail) → маркер ""
            # → повтор того же текста молчит. Заглушки в кэш НЕ пишутся.
            if dedup_key is not None and self._cache is not None:
                await self._cache.set_dedup(dedup_key, answer_text or "")

    # ── Context Partitioning (58.6) ─────────────────────────────

    async def _build_user_content(self, chat_id: int, message,
                                  target_name: str,
                                  target_user_id: int | None = None) -> list[str]:
        """Порядок сборки user-контента (Раунд 8, B2/T-791, spec §3.B2) —
        «важное к концу» (FR-22/п.24): map → branch → rag → global → thread →
        target → protected → lore → mood → current → anchors → sandwich.
        Статика вверх, критичное (target/protected/current) ближе к концу.
        Раунд 8 (C5/T-796): <Target_User> с uid автора запроса (NFR-2: скобки
        только в контекстных блоках direct_chat). Порядок регистрации
        роутеров/хендлеров НЕ меняется — меняется только эта сборка.
        Раунд 8 (F2/T-808): двухпроходность — <Global_Context> собирается
        РАНЬШЕ <RAG_Memory> (текст фона нужен для словарного дедупа RAG),
        контент-порядок blocks (rag → global) не меняется."""
        window = await self.memory.get_window_messages(chat_id)
        # Раунд 8 (C2/T-793): карта по активным участникам (24 ч) + окно;
        # суффиксы-дискриминаторы (C3/T-794) считаются один раз на рендер.
        active = await self._active_participants(chat_id)
        roster, suffix_map = self._participant_roster(window, active)
        blocks: list[tuple[str, str]] = []
        alias_map = self._alias_map_block(roster)
        if alias_map:
            blocks.append(("map", alias_map))
        # Раунд 8 (D4/T-801): итог reply-ветки над фоном — без LLM, только
        # для reply-триггера с цепочкой ≥ 2 ходов (полный Thread — ниже).
        chain = await self._collect_thread_chain(chat_id, message)
        if self._is_reply_trigger(message) and len(chain) >= 2:
            branch = self._render_branch(chain, suffix_map)
            if branch:
                blocks.append(("branch", branch))
        # F2: global считается раньше RAG (тело фона — для словарного дедупа).
        global_ctx = await self._build_global_context(
            chat_id, window, roster, suffix_map)
        rag_block = await self._build_rag_block(chat_id, message, global_ctx)
        if rag_block:
            blocks.append(("rag", rag_block))
        if global_ctx:
            blocks.append(("global", global_ctx))
        thread = self._render_thread(chain, suffix_map)
        if thread:
            blocks.append(("thread", thread))
        # Раунд 8 (C5/T-796): блок адресата — канон + uid запросившего.
        target_block = (f"<Target_User>{escape_xml_text(target_name)}"
                        f"{_speaker_tag('', target_user_id)}"
                        f"</Target_User>")
        blocks.append(("target", target_block))
        # Epic 60 (65.10, T-478): защищённые факты — сразу после Target_User.
        # Раунд 7 (T-781/F1, Q1): PG-лор (ChatLoreCache) — состояние ДО
        # сборки protected: при активном PG-лоре SQLite chat-level канал
        # (user_name IS NULL — легаси-лор раунда 5) целиком исключается
        # (include_chat_level=False) — текст константы не задвоится; блок
        # <chat_lore> идёт СРАЗУ ПОСЛЕ <protected_facts> (spec §3.9).
        lore_active, lore_inner = await self._chat_lore_state(chat_id)
        protected = await self._build_protected_facts(
            chat_id, target_name, include_chat_level=not lore_active)
        if protected:
            blocks.append(("protected", protected))
        if lore_inner:
            blocks.append(("lore", f"<chat_lore>\n{lore_inner}\n</chat_lore>"))
        # Epic 60 (65.9, T-477): настроение — user-блок, промпт R50-4 не тронут.
        # T-619: флаг и слова настроения — горячие точки (фолбек settings).
        if hot.get("flags.chat_mood_enabled", settings.CHAT_MOOD_ENABLED):
            mood = self._build_mood_block((message.text or ""))
            if mood:
                blocks.append(("mood", mood))
        # Раунд 8 (D1/T-798): <Current_Question> — текущее сообщение после
        # среза префикса «бот/@ник»; кап по символам; пусто → без блока.
        current = self._render_current_question(message)
        if current:
            blocks.append(("current", current))
        # Epic 60 (65.4, T-472): стилевые якоря — у конца (форма, не содержание).
        anchors = await self._build_style_anchors(chat_id)
        if anchors:
            blocks.append(("anchors", anchors))
        # Раунд 8 (B2/FR-23, п.25): sandwich-напоминание — последней строкой
        # user-контента (только если контент вообще есть).
        if blocks:
            blocks.append(("sandwich", _SANDWICH_REMINDER))
        return self._apply_context_budget(blocks)

    def _render_current_question(self, message) -> str:
        """Раунд 8 (D1/T-798, spec §3.D1): блок <Current_Question> — текст
        текущего сообщения после среза обращения «бот(@ник):»; cap
        limits.chat_current_question_max_chars (default 800); НЕ режется
        бюджетом (kind вне лимитов). Пустой после среза — без блока."""
        stripped = _strip_direct_prefix(message.text or "")
        if not stripped:
            return ""
        cap = int(hot.get("limits.chat_current_question_max_chars",
                          settings.CHAT_CURRENT_QUESTION_MAX_CHARS) or 0) \
            or 800
        return (f"<Current_Question>\n"
                f"{escape_xml_text(stripped[:cap])}\n"
                f"</Current_Question>")

    @staticmethod
    def _is_reply_trigger(message) -> bool:
        """Раунд 8 (D4/T-801): сообщение — reply (есть reply_to_message)."""
        return getattr(message, "reply_to_message", None) is not None

    # ── Раунд 8: memorize-хук с пост-фазой атрибуции (C6/T-797) ──

    async def _memorize_direct_reply(self, chat_id: int, query: str,
                                     answer: str, asker_canon: str) -> None:
        """C6: memorize_facts (target_user = канон автора запроса — «кто
        спрашивал», как и было) + пост-фаза: subject/object фактов,
        совпадающие с участниками карты чата, НЕ остаются на спрашивающем —
        target_user переназначается тому участнику (факты о третьих лицах
        не засоряют карточку и квоту спрашивающего). Fail-open: ошибка БД →
        WARNING, факты остаются записанными (NFR-6)."""
        before_id = None
        try:
            cursor = await self.db.db.execute(
                "SELECT COALESCE(MAX(id), 0) FROM graph_facts "
                "WHERE chat_id = ? AND origin = 'bot_direct_reply'",
                (chat_id,))
            row = await cursor.fetchone()
            before_id = int(row[0]) if row is not None else 0
        except Exception:
            logger.warning(
                "direct: fact batch bound failed — reassign skipped | chat=%s",
                chat_id, exc_info=True)
            before_id = None
        await self.memory.memorize_facts(
            chat_id, f"{query}\n{answer}", "bot_direct_reply",
            target_user=asker_canon)
        if before_id is None:
            return
        try:
            await self._reassign_fact_owners(chat_id, asker_canon, before_id)
        except Exception:
            logger.warning(
                "direct: fact owner reassign failed — facts stay on asker "
                "| chat=%s user=%s", chat_id, asker_canon, exc_info=True)

    async def _reassign_fact_owners(self, chat_id: int, asker_canon: str,
                                    min_id: int) -> None:
        """C6/T-797: пост-фаза переназначения target_user (без доп. LLM).
        Для каждого факта батча (id > min_id, origin='bot_direct_reply',
        target_user = asker_canon): subject-канон из начала факта — канон
        другого участника карты → запись на него; иначе object-канон
        (subject не участник) → на него; иначе факт остаётся на
        спрашивающем (темы/общие слова). Ошибка БД на факте — WARNING,
        факт остаётся (fail-open)."""
        participants = await self._active_participants(chat_id)
        canons = {self.aliases.canon_name(name) for _, name
                  in self._participant_roster([], participants)[0]}
        canons = {c for c in canons if c}
        canons.add(asker_canon)
        try:
            cursor = await self.db.db.execute(
                "SELECT id, fact FROM graph_facts "
                "WHERE chat_id = ? AND id > ? AND origin = 'bot_direct_reply' "
                "AND target_user = ?",
                (chat_id, min_id, asker_canon))
            rows = await cursor.fetchall()
        except Exception:
            logger.warning("direct: fact owner reassign read failed | chat=%s",
                           chat_id, exc_info=True)
            return
        for row in rows:
            owner = self._fact_owner_canon(str(row["fact"] or ""),
                                           canons, asker_canon)
            if owner is None or owner.casefold() == asker_canon.casefold():
                continue
            try:
                await self.db.db.execute(
                    "UPDATE graph_facts SET target_user = ? WHERE id = ?",
                    (owner, row["id"]))
                await self.db.db.commit()
            except Exception:
                logger.warning(
                    "direct: fact owner UPDATE failed — fact stays | fact_id=%s",
                    row["id"], exc_info=True)

    @staticmethod
    def _fact_owner_canon(sentence: str, canons: frozenset | set,
                          asker_canon: str) -> str | None:
        """C6: канон-владелец факта из предложения «subject predicate object
        (context)»: (1) канон-участник в НАЧАЛЕ предложения (subject),
        отличный от asker; (2) иначе — канон-участник в тексте (object) при
        subject-НЕ-участнике; (3) иначе None — факт остаётся спрашивающему.
        Совпадения — по casefold, участники отсортированы по длине (длинное
        имя не «съедается» префиксом короткого)."""
        text = str(sentence or "")
        low = text.casefold()
        members = sorted((str(c) for c in canons if str(c)),
                         key=lambda c: len(c), reverse=True)
        subject = None
        for canon in members:
            prefix = canon.casefold()
            if low == prefix or low.startswith(prefix + " "):
                subject = canon
                break
        if subject is not None:
            if subject.casefold() != asker_canon.casefold():
                return subject
            return None
        for canon in members:
            if canon.casefold() == asker_canon.casefold():
                continue
            if canon.casefold() in low:
                return canon
        return None

    # ── Epic 60 Фаза D (66.12, T-490): бюджеты контекста ─────────

    def _apply_context_budget(self, blocks: list[tuple[str, str]]) -> list[str]:
        """Доли CHAT_CONTEXT_BUDGET_TOKENS (Раунд 8, B2/D2/T-791/T-799,
        spec §3.B2): map/rag/global/thread/anchors + новая доля branch (0.03)
        — от effective_budget = max(1, budget − fixed_tokens), где fixed =
        неприкосновенные kinds: target, protected, lore, current, sandwich
        (вне per-block лимитов и вне порядка урезания). mood делит долю
        target на той же effective-базе (как раньше) и в общем цикле не
        участвует. Порядок урезания при превышении ОБЩЕГО бюджета (новая
        важность, D2/E1): Style_Anchors → RAG → Thread → Global(keep-head:
        конспект-голова держится, режется конец) → Map (карта — последняя).
        Выключено → ровно старые потолки секций (64.7)."""
        # T-619: бюджеты — горячие точки (фолбек settings)
        if not hot.get("flags.chat_context_budgets_enabled",
                       settings.CHAT_CONTEXT_BUDGETS_ENABLED):
            return [text for _, text in blocks]
        budget = hot.get("limits.chat_context_budget_tokens",
                         settings.CHAT_CONTEXT_BUDGET_TOKENS)
        uncuttable = ("target", "protected", "lore", "current", "sandwich")
        fixed_tokens = sum(count_tokens(text) for kind, text in blocks
                           if kind in uncuttable)
        effective = max(1, budget - fixed_tokens)

        def share(key: str, default_ratio: float) -> int:
            return max(1, int(effective * hot.get(key, default_ratio)))

        limits = {
            "map": share("limits.chat_budget_map_ratio",
                         settings.CHAT_BUDGET_MAP_RATIO),
            "rag": share("limits.chat_budget_rag_ratio",
                         settings.CHAT_BUDGET_RAG_RATIO),
            "global": share("limits.chat_budget_global_ratio",
                            settings.CHAT_BUDGET_GLOBAL_RATIO),
            "thread": share("limits.chat_budget_thread_ratio",
                            settings.CHAT_BUDGET_THREAD_RATIO),
            "anchors": share("limits.chat_budget_anchors_ratio",
                             settings.CHAT_BUDGET_ANCHORS_RATIO),
            # Раунд 8 (T-791): доля <Conversation_Branch> (0.03); в общем
            # порядке урезания branch НЕ участвует (компактный по построению).
            "branch": max(1, int(effective * hot.get(
                "limits.chat_budget_branch_ratio",
                settings.CHAT_BUDGET_BRANCH_RATIO))),
            # Доля «target+mood» — живёт только для mood (target неприкосновенен).
            "target": share("limits.chat_budget_target_ratio",
                            settings.CHAT_BUDGET_TARGET_RATIO),
        }
        # global-пол: под общим давлением global не опускается ниже своей доли
        # (D2.4: конспект-минимум, порядок жертв tail → L1(keep-head)).
        global_floor = limits["global"]

        def truncate(kind: str, text: str) -> str:
            if text is None or kind not in limits or limits[kind] <= 0:
                return text
            truncated = self._truncate_block(text, limits[kind], kind=kind)
            if truncated != text:
                logger.warning(
                    "direct: budget truncation | block=%s | tokens=%d -> %d",
                    kind, count_tokens(text), count_tokens(truncated))
            return truncated

        texts = {kind: text for kind, text in blocks}
        # mood делит долю target на effective-базе; Target_User неприкосновенен.
        if "mood" in texts:
            target_tokens = count_tokens(texts.get("target", ""))
            mood_limit = max(0, limits["target"] - target_tokens)
            mood_before = count_tokens(texts["mood"])
            if mood_before > mood_limit:
                texts["mood"] = self._truncate_block(
                    texts["mood"], mood_limit, kind="mood")
                logger.warning(
                    "direct: budget truncation | block=mood | tokens=%d -> %d",
                    mood_before, count_tokens(texts["mood"]))
        for kind in ("map", "rag", "global", "thread", "branch", "anchors"):
            if kind in texts:
                texts[kind] = truncate(kind, texts[kind])

        total = sum(count_tokens(text) for text in texts.values())
        if total > budget:
            # Порядок урезания (сначала дешёвое), геометрическими шагами.
            # global режется keep-head (конспект держится) и не опускается
            # ниже своей доли (D2.4/E1); map — последняя (карта атрибуции).
            order = ("anchors", "rag", "thread", "global", "map")
            for _ in range(20):
                if total <= budget:
                    break
                progress = False
                for kind in order:
                    if total <= budget:
                        break
                    if kind not in texts or limits[kind] <= 0:
                        continue
                    if kind == "global":
                        limits[kind] = max(global_floor, limits[kind] // 2)
                    else:
                        limits[kind] = max(0, limits[kind] // 2)
                    texts[kind] = self._truncate_block(
                        texts[kind], limits[kind], kind=kind)
                    total = sum(count_tokens(text)
                                for text in texts.values())
                    progress = True
                if not progress:
                    break
        return [texts[kind] for kind, _ in blocks if texts[kind]]

    def _truncate_block(self, block: str, limit_tokens: int,
                        kind: str = "") -> str:
        """66.12: обрезка блока по токенам с сохранением ОТКРЫВАЮЩЕГО и
        закрывающего тегов. Раунд 8 (D2/T-799): для kind='global' — keep-head
        (тело режется С НАЧАЛА — конспект-голова держится, verbatim-хвост
        отдаётся первым, spec §3.D2/Q8); остальные kinds — как сегодня
        (keep-end: свежие строки важнее, прецедент 64.7)."""
        text = str(block or "")
        if count_tokens(text) <= limit_tokens:
            return text
        if limit_tokens <= 0:
            return ""
        match = _BLOCK_RE.match(text)
        if match:
            opening, body, closing = match.groups()
            inner_budget = limit_tokens - count_tokens(opening) - count_tokens(closing)
            if inner_budget <= 0:
                return opening + closing.lstrip("\n")
            if kind == "global":
                return opening + truncate_to_tokens_keep_head(
                    body, inner_budget) + closing
            return opening + truncate_to_tokens(body, inner_budget) + closing
        if kind == "global":
            return truncate_to_tokens_keep_head(text, limit_tokens)
        return truncate_to_tokens(text, limit_tokens)

    # ── Epic 60 Фаза C (65.4/65.9/65.10): якоря, настроение, защита ──

    @staticmethod
    def _normalize_first_word(text: str) -> str:
        """3.7/C1: первое слово ответа (lower, без пунктуации); пусто/короче
        _STICKY_MIN_WORD_LEN → не «слово-префикс»."""
        m = re.match(r"\s*([а-яёa-z0-9]+)", str(text).lower())
        word = m.group(1) if m else ""
        return word if len(word) >= _STICKY_MIN_WORD_LEN else ""

    @staticmethod
    def _detect_sticky(window) -> set[str]:
        """3.7/C1: первые слова с частотой >= _STICKY_MIN_FREQ в окне
        последних ответов → «залипшие» префиксы (исключаются из якорей)."""
        from collections import Counter
        prefixes = [DirectChatService._normalize_first_word(t)
                    for t in window]
        counts = Counter(p for p in prefixes if p)
        return {word for word, cnt in counts.items()
                if cnt >= _STICKY_MIN_FREQ}

    async def _build_style_anchors(self, chat_id: int) -> str:
        """65.4: секция <style_anchors> из последних ответов бота (bot_replies,
        ASC). Раунд 3 (3.7/C1): анти-залипание — если >=2 из последних `count`
        начинаются с одного и того же первого слова («сцуко,» и пр.), такие
        ответы НЕ попадают в якоря (выбираются более старые различные из
        буфера _STYLE_ANCHOR_LOOKBACK; повтор-префиксы исключаются);
        не осталось ни одного → секции нет (безопаснее, чем модель-«попугай»).
        Инструкция смягчена: «держи общую интонацию, НЕ копируй дословно, не
        начинай каждый ответ с одного и того же слова». VERBATIM-шаблон в
        тестах; user-блок — R50-4 неприкосновенен. Fail-open: ошибка БД →
        WARNING + без секции."""
        if not hot.get("flags.chat_style_anchors_enabled",
                       settings.CHAT_STYLE_ANCHORS_ENABLED):
            return ""
        try:
            count = hot.get("limits.chat_style_anchors_count",
                            settings.CHAT_STYLE_ANCHORS_COUNT)
            replies = await self.db.last_bot_replies(
                chat_id, count + _STYLE_ANCHOR_LOOKBACK, time.time())
        except Exception:
            logger.warning("direct: style anchors read failed | chat=%s",
                           chat_id, exc_info=True)
            return ""
        if not replies:
            return ""
        sticky = self._detect_sticky(replies[-count:])
        selected: list[str] = []
        used_prefixes: set[str] = set()
        for text in reversed(replies):                 # свежие → старые
            if len(selected) >= count:
                break
            first = self._normalize_first_word(text)
            if first and (first in sticky or first in used_prefixes):
                continue                               # залипший/повтор
            if first:
                used_prefixes.add(first)
            selected.append(text)
        if not selected:
            return ""
        selected.reverse()                             # хронология ASC
        anchor_cap = hot.get("limits.chat_style_anchor_max_chars",
                             settings.CHAT_STYLE_ANCHOR_MAX_CHARS)
        body = "\n".join(
            f"{i}. {t[:anchor_cap]}" for i, t in enumerate(selected, 1))
        return (f"<style_anchors>\nподражай общей интонации этих ответов, "
                f"но НЕ копируй дословно и не начинай каждый ответ с одного "
                f"и того же слова:\n{body}\n</style_anchors>")

    def _build_mood_block(self, query: str) -> str:
        """65.9: лёгкая эвристика по словам (без LLM-вызова). Блок ПОСЛЕ
        <Target_User>; системный промпт R50-4 НЕ меняется ни на байт.
        T-619: слова настроения — горячая точка (фолбек settings)."""
        text = str(query or "").lower()
        negative = _parse_mood_words(hot.get(
            "reactions.chat_mood_negative_words", settings.CHAT_MOOD_NEGATIVE_WORDS))
        positive = _parse_mood_words(hot.get(
            "reactions.chat_mood_positive_words", settings.CHAT_MOOD_POSITIVE_WORDS))
        mood = None
        if any(w in text for w in negative):
            mood = "зло"
        elif any(w in text for w in positive):
            mood = "радостно"
        if mood is None:
            return ""
        return (f"<mood>собеседник звучит {mood}, "
                f"подстрой тон под это, но не переигрывай</mood>")

    async def _build_protected_facts(self, chat_id: int, target_name: str,
                                     include_chat_level: bool = True) -> str:
        """65.10: защищённые факты подмешиваются в контекст (карточки-слоты —
        не размазываются при сжатии). Fail-open → без секции.
        Раунд 5 (T-732): include_chat_level=True — чат-лор виден ВСЕМ юзерам
        чата ВСЕГДА (65.10 + раунд 5). Раунд 7 (T-781/F1): при активном
        PG-лоре вызывающий передаёт include_chat_level=False — SQLite
        chat-level канал не дублируется (дедуп ТОЛЬКО на чтении, Q1)."""
        try:
            facts = await self.db.get_protected_facts(
                chat_id, target_name, include_chat_level=include_chat_level)
        except Exception:
            logger.warning("direct: protected facts read failed | chat=%s",
                           chat_id, exc_info=True)
            return ""
        if not facts:
            return ""
        body = "\n".join(f"- {escape_xml_text(fact)}" for fact in facts)
        return (f"<protected_facts>\nважные факты, помни о них всегда:\n"
                f"{body}\n</protected_facts>")

    # ── Раунд 7 (T-781/F1): PG-лор чатов — состояние инжекта (spec §3.9) ──

    async def _chat_lore_state(self, chat_id: int) -> tuple[bool, str]:
        """Состояние PG-лора чата: `(lore_active, inner)` — inner —
        экранированный текст блока (manual + `---` + auto, cap
        limits.lore_inject_max_chars, авто-текст режется первым, маркер
        «…[обрезано]»; БЕЗ тегов <chat_lore> — обёртку добавляет вызов).

        Правила (Q1/§3.9):
          * flags.lore_inject_enabled=false ИЛИ cache не инжектирован →
            (False, "") — ровно старое поведение;
          * исключение/PG down → WARNING с дедупом (раз в 50 попыток) →
            (False, "") (fail-open: SQLite-легаси работает);
          * профиля нет / not is_active / оба поля пусты → (False, "");
          * иначе → (True, inner) — cap ДО инжекта, блок не режется
            контекст-бюджетом (_apply_context_budget: kind "lore" вне
            лимитов и порядка урезания)."""
        if not hot.get("flags.lore_inject_enabled",
                       settings.LORE_INJECT_ENABLED):
            return False, ""
        cache = self.chat_lore_cache
        if cache is None:
            return False, ""
        try:
            profile = await cache.get(chat_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._lore_cache_errors += 1
            if self._lore_cache_errors % 50 == 1:
                logger.warning(
                    "direct: chat lore cache failed — fail-open (пусто) | "
                    "chat=%s", chat_id, exc_info=True)
            return False, ""
        if profile is None or not profile.is_active:
            return False, ""
        manual = (profile.manual_lore or "").strip()
        auto = (profile.auto_lore or "").strip()
        if not manual and not auto:
            return False, ""
        from services.lore_prompts import format_lore_block
        cap = int(hot.get("limits.lore_inject_max_chars",
                          settings.LORE_INJECT_MAX_CHARS) or 0)
        # экранирование ДО cap: XML-спецсимволы не ломают блок; cap считается
        # по экранированной форме (spec §3.6: содержимое экранируется)
        block = format_lore_block(escape_xml_text(manual),
                                  escape_xml_text(auto), cap)
        if not block:
            return False, ""
        inner = block[len("<chat_lore>\n"):]
        if inner.endswith("\n</chat_lore>"):
            inner = inner[: -len("\n</chat_lore>")]
        return True, inner

    # ── Epic 60 Фаза C (65.5/65.8): команды /clear /persona /tone /forget ──

    async def _get_tone_preset(self, chat_id: int, user_id: int) -> str | None:
        """65.8: пресет юзера из user_prefs. Fail-open → None (дефолт)."""
        try:
            return await self.db.get_user_tone_preset(chat_id, user_id)
        except Exception:
            logger.warning("direct: user_prefs read failed | chat=%s",
                           chat_id, exc_info=True)
            return None

    async def get_tone_preset(self, chat_id: int, user_id: int) -> str | None:
        """65.5 /tone без аргумента: показать текущий пресет."""
        return await self._get_tone_preset(chat_id, user_id)

    async def set_tone_preset(self, chat_id: int, user_id: int,
                              preset_key: str) -> None:
        """65.5 /tone: записать пресет в user_prefs."""
        try:
            await self.db.set_user_tone_preset(chat_id, user_id, preset_key)
        except Exception:
            logger.warning("direct: user_prefs write failed | chat=%s",
                           chat_id, exc_info=True)

    async def clear_user_dialogue(self, chat_id: int, user) -> int:
        """65.5 /clear: стереть диалог с юзером (bot_replies чата +
        bot_direct_reply-факты юзера). Fail-open → 0."""
        try:
            return await self.db.clear_direct_dialogue(
                chat_id, self._resolve_name(user))
        except Exception:
            logger.warning("direct: /clear failed | chat=%s", chat_id, exc_info=True)
            return 0

    async def forget_user_fact(self, chat_id: int, user, phrase: str) -> int:
        """65.5/65.10 /forget: удалить конкретный(е) факт(ы) юзера (FTS);
        защищённые факты не трогаются. Fail-open → 0."""
        try:
            return await self.db.forget_direct_facts(
                chat_id, self._resolve_name(user), phrase, int(time.time()))
        except Exception:
            logger.warning("direct: /forget failed | chat=%s", chat_id, exc_info=True)
            return 0

    # ── Раунд 4 (T-712/T-715, FR-D1/FR-D4/FR-D5, spec 3.4.4): ──────────
    # Память-команды «запомни/забудь» (origin='user_memory'). RBAC: админ/
    # модер — всегда (target_user NULL → факт чата / весь чат); юзер — только
    # при флаге flags.memory_commands_user_enabled (иначе "denied").

    _MEMORY_FACT_MAX_CHARS = 500   # spec 3.4.2: кап аргумента «запомни» (спам)

    async def remember_user_fact(self, chat_id: int, user, fact_text: str) -> str:
        """«запомни» → "saved" | "duplicate" | "denied" | "error" (fail-open).
        Привилегия: admin/mod — всегда, target_user=None (факт чата); юзер —
        только при флаге, target_user=канон-имя (алиас-резолв _resolve_name).
        ttl — hot limits.memory_commands_remember_ttl_days (дефолт settings,
        365; 0/пусто = вечно). Аргумент схлопывается и усекается до 500
        символов (усечение — INFO-лог)."""
        fact_text = " ".join(str(fact_text or "").split())
        if len(fact_text) > self._MEMORY_FACT_MAX_CHARS:
            fact_text = fact_text[:self._MEMORY_FACT_MAX_CHARS]
            logger.info("[user_memory] факт усечён до %d символов | chat=%s",
                        self._MEMORY_FACT_MAX_CHARS, chat_id)
        if not fact_text:
            return "error"
        if chat_access.privilege(user.id) == "user":
            if not hot.get("flags.memory_commands_user_enabled",
                           settings.MEMORY_COMMANDS_USER_ENABLED):
                return "denied"
            target_user = self._resolve_name(user)
        else:
            target_user = None
        try:
            return await self.memory.remember_user_fact(
                chat_id, fact_text, target_user=target_user,
                ttl_days=hot.get("limits.memory_commands_remember_ttl_days",
                                 settings.MEMORY_COMMANDS_REMEMBER_TTL_DAYS))
        except Exception:
            logger.warning(
                "[user_memory] remember failed | chat=%s user=%s",
                chat_id, user.id, exc_info=True)
            return "error"

    async def forget_user_facts(self, chat_id: int, user,
                                phrase: str) -> tuple[str, int, str]:
        """«забудь» → ("ok"|"denied"|"error", removed, query). Scope: юзер
        (флаг on) — свои факты (target_user=канон-имя); админ/модер — весь
        чат (target_user любой). Слова — до 5 по >=3 симв (AND-семантика).
        Fail-open → 0. protected_facts в выборку не попадают (БД-грань)."""
        if chat_access.privilege(user.id) == "user":
            if not hot.get("flags.memory_commands_user_enabled",
                           settings.MEMORY_COMMANDS_USER_ENABLED):
                return "denied", 0, ""
            target_user = self._resolve_name(user)
        else:
            target_user = None
        query = " ".join(str(phrase or "").split())
        try:
            words = self.db._memory_forget_words(query)
            removed = await self.db.forget_memory_facts(
                chat_id, words, target_user=target_user, now_ts=int(time.time()))
            return "ok", removed, query
        except Exception:
            logger.warning(
                "[user_memory] forget failed | chat=%s user=%s",
                chat_id, user.id, exc_info=True)
            return "error", 0, ""

    # ── Epic 60 Фаза D (66.9, T-487): карточки пользователей ─────

    def persona_access(self, user, name: str) -> bool:
        """66.9: свою карточку видит сам юзер; ЧУЖУЮ — только ADMIN_USER_ID
        (R17 — чувствительные данные). Совпадение — канон-имя (aliases) или
        user_id."""
        if user is None:
            return False
        if getattr(user, "id", None) == settings.ADMIN_USER_ID:
            return True
        requested = str(name or "").strip().casefold()
        own = self._resolve_name(user).casefold()
        return requested in (own, str(getattr(user, "id", "")).casefold())

    async def build_persona_card(self, chat_id: int, name: str) -> str | None:
        """66.9: карточка человека — агрегация графа без отдельной таблицы:
        прямые факты (target_user) + top-связи (edges по user-узлу) +
        защищённые факты. Формат VERBATIM; None — пусто (фраза из 66.9).
        Fail-open → None."""
        canon = self.aliases.canon_name(name)
        try:
            card = await self.db.get_persona_card(
                chat_id, canon, _PERSONA_MAX_ITEMS, time.time())
            # Раунд 5 (T-732, дельта 4.6.2): include_chat_level=True — чат-лор
            # включается в карточку (решение владельца: «уместно: лор чата
            # в карточке»); идёт первыми строками списка, формат 66.9 VERBATIM
            # и счётчик N (одна строка на чат) не меняются.
            # Раунд 7 (T-781/F1, spec §3.9): при активном PG-лоре SQLite
            # chat-level канал исключается (include_chat_level=False), текст
            # PG-лора добавляется ПЕРВОЙ «строкой» списка (многострочный
            # текст одним элементом; счётчик «знаю о тебе» считает лор как
            # +1); при неактивном PG-лоре — ровно как в раунде 5.
            lore_active, lore_inner = await self._chat_lore_state(chat_id)
            protected = await self.db.get_protected_facts(
                chat_id, canon, include_chat_level=not lore_active)
        except Exception:
            logger.warning("direct: persona card read failed | chat=%s name=%s",
                           chat_id, name, exc_info=True)
            return None
        facts = card["facts"]
        links = card["links"]
        lore_lines = [lore_inner] if lore_inner else []
        n = len(facts) + len(protected) + len(lore_lines)
        m = len(links)
        lines = lore_lines + list(protected) + list(facts)
        lines += [f"{link['source_name']} ({link['relation_type']}) "
                  f"{link['target_name']}" for link in links]
        lines = lines[:_PERSONA_MAX_ITEMS]
        if n == 0 and m == 0:
            return None
        body = "\n".join(f"{i}. {text}" for i, text in enumerate(lines, 1))
        return f"карточка: {canon}\nзнаю о тебе: {n} фактов, {m} связей\n{body}"

    async def list_persona_names(self, chat_id: int) -> list[tuple[str, int]]:
        """66.9: /persona list (только ADMIN_USER_ID) — имена + счётчики
        прямых фактов. Fail-open → []."""
        try:
            return await self.db.get_persona_names(chat_id, time.time())
        except Exception:
            logger.warning("direct: persona list read failed | chat=%s",
                           chat_id, exc_info=True)
            return []

    # ── Участники и карта (Раунд 8: C2/T-793 активные, C3/T-794 дискриминатор) ──

    def _build_alias_map(self, window: list,
                         participants: list | None = None) -> str:
        """User Resolution Map (R51-2): «имя — user_id» (алиасы.resolve);
        блок в НАЧАЛЕ user-контента (D211). Раунд 8 (C2/T-793): источник —
        активные участники (limits.chat_map_participants_hours) + участники
        окна; формат строки «{имя} — {uid}» сохранён (Q1: в карте uid
        «столбцом», скобки избыточны). Fail-open: participants пусто/ошибка —
        поведение только-окно (регресс)."""
        roster, _ = self._participant_roster(window, participants)
        return self._alias_map_block(roster)

    @staticmethod
    def _alias_map_block(roster: list[tuple[int, str]]) -> str:
        """Строки карты из готового roster (C2.3: урезание «с конца списка» —
        менее активные строки)."""
        if not roster:
            return ""
        lines = [f"{display} — {uid}" for uid, display in roster]
        return "<UserResolutionMap>\n" + "\n".join(lines) + "\n</UserResolutionMap>"

    async def _active_participants(self, chat_id: int) -> list:
        """Раунд 8 (C2/T-793): SQL-агрегат активных участников чата за
        limits.chat_map_participants_hours (default 24 ч) по smart_messages
        (индекс idx_smart_messages_chat_ts уже есть; новый DDL НЕ вводим).
        Порядок — активность (cnt DESC, uid ASC — в SQL). Fail-open → []
        (только окно; NFR-6)."""
        try:
            hours = int(hot.get("limits.chat_map_participants_hours",
                                settings.CHAT_MAP_PARTICIPANTS_HOURS) or 24)
            cap = int(hot.get("limits.chat_map_participants_cap",
                              settings.CHAT_MAP_PARTICIPANTS_CAP) or 0) or 150
            since = int(time.time()) - hours * 3600
            return await self.db.get_active_participants(chat_id, since, cap)
        except Exception:
            logger.warning(
                "direct: active participants failed — window only | chat=%s",
                chat_id, exc_info=True)
            return []

    def _participant_roster(self, window: list,
                            participants: list | None = None
                            ) -> tuple[list[tuple[int, str]], dict[int, str]]:
        """Раунд 8 (C2/C3/T-793/T-794): (roster, suffix_map) для карты и
        внутренних рендеров. roster — [(uid, display)] в порядке активности
        (participants, cnt DESC); окно-участники — на своих активных
        позициях (author_name первого встреченного в окне), внеоконные
        активные дополняют; при пустых participants — порядок окна (как
        сегодня, fail-open). Cap limits.chat_map_participants_cap (150).
        suffix_map — uid → дискриминатор коллизии display.casefold() (C3):
        второй+ участник по uid ASC получает суффикс « (username)»/« (#хвост)»;
        ТОЛЬКО на рендере контекста — чистые пути его не видят (NFR-2)."""
        cap = int(hot.get("limits.chat_map_participants_cap",
                          settings.CHAT_MAP_PARTICIPANTS_CAP) or 0) or 150
        window_authors: dict[int, str] = {}
        for row in window:
            uid = row["user_id"]
            if uid in (None, 0) or uid in window_authors:
                continue
            window_authors[uid] = row["author_name"] or None
        if participants:
            extras: dict[int, str] = {}
            for row in participants:
                uid = row["user_id"]
                if uid in (None, 0) or uid in window_authors:
                    continue
                extras[uid] = row["author_name"] or None
            uids = [uid for uid in (row["user_id"] for row in participants)
                    if uid not in (None, 0)
                    and (uid in window_authors or uid in extras)]
        else:
            uids = [uid for uid in window_authors]
        uids = uids[:cap]
        displays: dict[int, str] = {}
        for uid in uids:
            author = window_authors.get(uid)
            if author is None:
                author = extras.get(uid) if participants else None
            displays[uid] = self.aliases.resolve(uid, author, None)
        collisions: dict[str, list[int]] = {}
        for uid, name in displays.items():
            collisions.setdefault(str(name).casefold(), []).append(uid)
        suffix_map: dict[int, str] = {}
        for group in collisions.values():
            if len(group) < 2:
                continue
            for uid in sorted(group)[1:]:
                suffix_map[uid] = _collision_suffix(uid)
        roster = [(uid, f"{displays[uid]}{suffix_map.get(uid, '')}")
                  for uid in uids]
        return roster, suffix_map

    # ── <RAG_Memory> direct-пути (Раунд 8: F1/T-807, F2/T-808, F3/T-809,
    #    F4/T-810 — факты по релевантности, дедуп ↔ фон, origin-метки,
    #    опциональный LLM-реранк) ─────────────────────────────────

    async def _build_rag_block(self, chat_id: int, message,
                               global_ctx: str) -> str:
        """Блок `<RAG_Memory>` direct-пути (F1-F4):
        F1 — факты из memory.get_rag_facts: порядок РЕЛЕВАНТНОСТИ (KNN
            rel = cosine × w_eff + MMR / FTS w_eff DESC), БЕЗ хроно-
            сортировки (sort_by_timestamp остался только у легаси
            get_rag_context — search/factcheck не тронуты);
        F2 — словарный дедуп фактов против текста <Global_Context>
            (dedup_rag_vs_global, порог limits.chat_rag_dedup_overlap_ratio);
        F4 — при flags.chat_rag_rerank_enabled=True: LLM-фильтр top-k
            (memory.rerank_rag_facts, fail-open); off → 0 вызовов;
        F3 — рендер с origin-метками «[{label}] {date} текст» (build_rag_context
            origin_labels=True). Fail-open: любая ошибка/пусто → "" (блок не
            рендерится, WARNING — NFR-6); RAG выключен → "" (регресс
            test_empty_rag_section_omitted)."""
        if not hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
            return ""
        query = getattr(message, "text", None) or ""
        try:
            facts = await self.memory.get_rag_facts(
                chat_id, query, include_direct_reply=True)
        except Exception:
            logger.warning("direct: rag facts failed — no rag block | chat=%s",
                           chat_id, exc_info=True)
            return ""
        if not facts:
            return ""
        # F2: дубли конспекта/verbatim-хвоста фона из RAG-блока исключаются
        # (никогда не бросает — fail-open внутри).
        kept = dedup_rag_vs_global(facts, global_ctx)
        if not kept:
            return ""
        # F4: флаг off → 0 лишних LLM-вызовов (ранний выход ДО сериализации).
        if hot.get("flags.chat_rag_rerank_enabled",
                   settings.CHAT_RAG_RERANK_ENABLED):
            try:
                kept = await self.memory.rerank_rag_facts(query, kept)
            except Exception:
                logger.warning(
                    "direct: rag rerank failed — original facts | chat=%s",
                    chat_id, exc_info=True)
        if not kept:
            return ""
        # F3: единый формат строки с origin-меткой; дата — внутри факта.
        content = build_rag_context(kept, origin_labels=True)
        cap = int(hot.get("limits.graph_rag_context_max_chars",
                          settings.GRAPH_RAG_CONTEXT_MAX_CHARS) or 0)
        if cap and len(content) > cap:
            logger.warning("direct: rag context truncated to %d chars | chat=%s",
                           cap, chat_id)
            content = content[:cap]
        if not content:
            return ""
        logger.info("direct: rag block | facts=%d | chat=%s", len(kept), chat_id)
        return f"<RAG_Memory>\n{content}\n</RAG_Memory>"

    # ── <Global_Context> (Раунд 8: D2/T-799 keep-head + E1/T-803 importance,
    #    D5/T-802 метки-строки, C1/T-792 uid-рендеры) ────────────

    async def _build_global_context(self, chat_id: int, window: list,
                                    roster: list | None = None,
                                    suffix_map: dict[int, str] | None = None
                                    ) -> str:
        """Последние CHAT_GLOBAL_CONTEXT_LIMIT сообщений (окно уже ASC),
        «{имя} [{uid}]: текст» (C1). Epic 60 (64.6): валидный бегущий конспект
        → конспект + дословный хвост (ts > window_end_ts). Раунд 8 (D2/Q8):
        внутренний потолок — keep-head-семантика: verbatim-хвост режется
        первым (importance-удержание E1), конспект — последним (срез головы
        truncate_to_tokens_keep_head); chars-ветка — тот же порядок шагов.
        Раунд 8 (D5/T-802): первая строка body — метка-строка объёма
        («фон: конспект из N сообщений…» / «фон: дословно последние N…»).
        Раунд 8 (E2/T-804): при наличии L1 и level-2 (широкий фон) строка
        L2 с меткой «широкий фон:» — ПЕРВОЙ строкой body (кап
        limits.chat_level2_max_chars, keep-end; в иерархии бюджетных жертв
        L2 жертвуется последней — голова body). Раунд 8 (E4/T-806):
        конспект читается без TTL-смерти (get_running_summary не удаляет
        по expires_at — тихий чат держит конспект до пересборки по
        заполнению).
        roster/suffix_map — участники карты текущего рендера (C2/C3):
        суффиксы-дискриминаторы строк и имена для importance-маркеров E1."""
        roster = roster or []
        suffix_map = suffix_map or {}
        summary_text = None
        raw_count = 0
        window_end_ts = None
        level2_text = None
        if hot.get("flags.chat_running_summary_enabled",
                   settings.CHAT_RUNNING_SUMMARY_ENABLED):
            try:
                row = await self.db.get_running_summary(chat_id, time.time())
                if row is not None:
                    summary_text = row["summary"]
                    raw_count = int(row["raw_count"] or 0)
                    window_end_ts = row["window_end_ts"]
                if summary_text is not None:
                    # E2: level-2 инжектится ТОЛЬКО вместе с L1 (строка L2 —
                    # сжатие ПРЕДЫДУЩЕГО L1). Ошибка/отсутствие уровня —
                    # fail-open: без строки, конспект как был.
                    try:
                        l2 = await self.db.get_summary_level(chat_id, 2)
                        if l2 is not None and (l2["summary"] or "").strip():
                            level2_text = str(l2["summary"]).strip()
                            cap2 = int(hot.get(
                                "limits.chat_level2_max_chars",
                                settings.CHAT_LEVEL2_MAX_CHARS) or 0)
                            if cap2 and len(level2_text) > cap2:
                                logger.warning(
                                    "direct: level2 capped to %d chars | chat=%s",
                                    cap2, chat_id)
                                level2_text = level2_text[-cap2:]
                    except Exception:
                        logger.warning(
                            "direct: level2 read failed — without L2 row "
                            "| chat=%s", chat_id, exc_info=True)
            except Exception:
                logger.warning("direct: running summary read failed | chat=%s",
                               chat_id, exc_info=True)
        head: list[str] = []
        tail: list[str] = []
        if summary_text is not None:
            # E2/D5: «широкий фон:» + L2 первой строкой body (метка-префикс),
            # затем метка summary-режима (возраст НЕ вводим — конспект живёт
            # по заполнению окна, Q11/E4) и сам конспект L1.
            if level2_text:
                head.append("широкий фон: " + level2_text)
            head.append(f"фон: конспект из {raw_count} сообщений, "
                        f"ниже дословно свежий хвост")
            head.append(summary_text)
            for row in window:
                if int(row["timestamp"] or 0) <= window_end_ts:
                    continue
                text = row["text"] or ""
                if not text:
                    continue
                name, uid = self._row_speaker(row)
                tail.append(f"{_speaker_tag(name, uid, suffix=suffix_map.get(uid, ''))}: {text}")
        else:
            recent = window[-hot.get("limits.chat_global_context_limit",
                                     settings.CHAT_GLOBAL_CONTEXT_LIMIT):]
            for row in recent:
                text = row["text"] or ""
                if not text:
                    continue
                name, uid = self._row_speaker(row)
                tail.append(f"{_speaker_tag(name, uid, suffix=suffix_map.get(uid, ''))}: {text}")
            if not tail:
                return ""
            # D5: метка verbatim-режима — по отобранной ветке окна
            # (n = число строк после среза recent-ветки).
            head.append(f"фон: дословно последние {len(tail)} сообщений")
        kind, limit = resolve_chat_limit(
            hot.get("limits.chat_global_context_max_tokens", settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS), 1000,
            "CHAT_GLOBAL_CONTEXT_MAX_CHARS", hot.get("limits.chat_global_context_max_chars", settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS),
            "CHAT_GLOBAL_CONTEXT",
        )
        measure = count_tokens if kind == "tokens" else len
        keep_important = bool(hot.get(
            "flags.chat_importance_keep_enabled",
            settings.CHAT_IMPORTANCE_KEEP_ENABLED))
        # E1: имена для маркеров важности — display-имена участников карты
        # текущего рендера (casefold; канон-имена фактов не нужны — строки
        # рендера несут display).
        names = frozenset(str(display).casefold()
                          for _, display in roster)
        budget = safe_budget(limit) if kind == "tokens" else limit
        if measure("\n".join(head + tail)) > budget:
            logger.warning("direct: global context truncated | %s=%d -> %d",
                           kind, measure("\n".join(head + tail)), budget)
            tail = trim_verbatim_lines(
                tail, max(0, budget - measure("\n".join(head))),
                names=names, keep_important=keep_important, measure=measure)
            if measure("\n".join(head + tail)) > budget:
                # резерв: keep-head по всему body (конец режется — конспект
                # держится); метка-строка («широкий фон: …»/«фон: …»)
                # сохраняется первой.
                body = "\n".join(head + tail)
                if kind == "tokens":
                    body = truncate_to_tokens_keep_head(body, max(1, budget))
                else:
                    body = body[:budget]
                lines = body.split("\n")
                if lines and lines[0].startswith(("широкий фон: ", "фон: ")):
                    head = [lines[0]]
                    tail = [ln for ln in lines[1:] if ln.strip()]
                else:
                    head, tail = [], [ln for ln in lines if ln.strip()]
        body = "\n".join(head + tail)
        return f"<Global_Context>\n{escape_xml_text(body)}\n</Global_Context>"

    def _row_speaker(self, row) -> tuple[str, int | None]:
        """(display-имя, uid) строки окна: резолв существующим каскадом
        алиас → никнейм → юзернейм (без изменений; uid — только добавка
        рендера)."""
        uid = row["user_id"]
        name = self.aliases.resolve(
            int(uid or 0), (row["author_name"] or None), None)
        return name, uid

    # ── <Conversation_Thread> / <Conversation_Branch> (Раунд 8: D3/T-800,
    #    D4/T-801 — цепочка сквозь бот-ответы, итог ветки без LLM) ──

    async def _collect_thread_chain(self, chat_id: int, message) -> list:
        """Рекурсивная цепочка reply по tg_message_id (глубина
        CHAT_THREAD_MAX_DEPTH): user-сообщения из БД (observer сохраняет все),
        бот-сообщения из bot_replies (Epic 60, 63.1). Раунд 8 (D3/T-800):
        на бот-сообщении цепочка НЕ обрывается — текст добавляется и ход
        продолжается от parent-сообщения (bot_reply_parents); break — только
        терминальный: нет reply_to_id / не найдено / parent нет или протух /
        глубина исчерпана / сообщение уже в seen.
        Возвращает [(uid, display-имя, text, is_bot)] — от ТЕКУЩЕГО
        сообщения (самое свежее первое) к корню."""
        depth = int(hot.get("limits.chat_thread_max_depth",
                            settings.CHAT_THREAD_MAX_DEPTH) or 0)
        chain: list[tuple[int | None, str, str, bool]] = []
        current_id = getattr(message, "message_id", None)
        seen: set[int] = set()
        for _ in range(max(1, depth)):
            if current_id is None or current_id in seen:
                break
            seen.add(current_id)
            row = await self.db.get_smart_message_by_tg_id(chat_id, current_id)
            if row is not None:
                text = row["text"] or ""
                if text:
                    name, uid = self._row_speaker(row)
                    chain.append((uid, name, text, False))
                current_id = row["reply_to_id"]
                continue
            bot_text = await self.get_bot_reply(chat_id, current_id)
            if bot_text is not None:
                chain.append((None, self._resolve_bot_name(), bot_text, True))
                parent = await self._bot_reply_parent(chat_id, current_id)
                if parent is None:
                    break
                current_id = parent
                continue
            break                          # обрыв: нет reply_to_id/не найдено
        return chain

    def _chain_line(self, item, suffix_map: dict[int, str]) -> str:
        """Рендер одного хода цепочки (C1): «{имя}{дискр} [{uid}]: {текст}»,
        бот-ход — «{имя} [bot]: {текст}»."""
        uid, name, text, is_bot = item
        if is_bot:
            return f"{_speaker_tag(name, None, is_bot=True)}: {text}"
        return (f"{_speaker_tag(name, uid, suffix=suffix_map.get(uid, ''))}: "
                f"{text}")

    def _render_thread(self, chain: list, suffix_map: dict[int, str]) -> str:
        """Рендер полной цепочки сверху-вниз (лимиты 64.7, keep-end —
        verbatim-диалог не участвует в importance-удержании E1)."""
        if not chain:
            return ""
        lines = [self._chain_line(item, suffix_map)
                 for item in reversed(chain)]
        body = "\n".join(lines)
        kind, limit = resolve_chat_limit(
            hot.get("limits.chat_thread_max_tokens", settings.CHAT_THREAD_MAX_TOKENS), 500,
            "CHAT_THREAD_MAX_CHARS", hot.get("limits.chat_thread_max_chars", settings.CHAT_THREAD_MAX_CHARS),
            "CHAT_THREAD",
        )
        if kind == "tokens":
            budget = safe_budget(limit)
            if count_tokens(body) > budget:
                logger.warning("direct: thread truncated | tokens=%d -> %d",
                               count_tokens(body), budget)
                body = truncate_to_tokens(body, budget)
        elif len(body) > limit:
            logger.warning("direct: thread truncated | chars=%d", len(body))
            body = body[:limit]
        return f"<Conversation_Thread>\n{escape_xml_text(body)}\n</Conversation_Thread>"

    def _render_branch(self, chain: list, suffix_map: dict[int, str]) -> str:
        """Раунд 8 (D4/T-801): <Conversation_Branch> — компактный итог
        reply-ветки: последние limits.chat_branch_context_hops (default 3)
        ходов уже собранной цепочки (без LLM, без повторного walk). Полный
        <Conversation_Thread> рендерится ниже. Вызывается только для
        reply-триггера и цепочки глубины ≥ 2."""
        if not chain:
            return ""
        hops = int(hot.get("limits.chat_branch_context_hops",
                           settings.CHAT_BRANCH_CONTEXT_HOPS) or 0) or 3
        fresh = list(reversed(chain[:max(1, hops)]))     # ASC: старое → новое
        lines = [self._chain_line(item, suffix_map) for item in fresh]
        body = "\n".join(lines)
        return (f"<Conversation_Branch>\n"
                f"{escape_xml_text(body)}\n</Conversation_Branch>")

    async def _build_conversation_thread(self, chat_id: int, message) -> str:
        """Публичная сборка <Conversation_Thread> (58.6): цепочка reply от
        текущего сообщения (D3: сквозь бот-ответы по bot_reply_parents)."""
        chain = await self._collect_thread_chain(chat_id, message)
        return self._render_thread(chain, {})

    # ── Имена (R50-1, каскад Алиас → Никнейм → Юзернейм, БЕЗ '@') ──

    def _resolve_name(self, user) -> str:
        if user is None:
            return "кто-то"
        nickname = self._build_nickname(user)
        return self.aliases.resolve(
            user.id, nickname, getattr(user, "username", None))

    def _resolve_bot_name(self) -> str:
        if self.bot_id is not None:
            return self.aliases.resolve(self.bot_id, None, self.bot_username or None)
        return self.bot_username or "бот"

    @staticmethod
    def _build_nickname(user) -> str | None:
        parts = []
        for attr in ("first_name", "last_name"):
            value = getattr(user, attr, None)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        return " ".join(parts) if parts else None
