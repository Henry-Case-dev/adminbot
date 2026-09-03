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
"""
import asyncio
import hashlib
import logging
import random
import re
import time

from config.settings import settings
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
from services.summary_memory import fire_and_forget
from services.summary_xml import escape_xml_text
from services.token_counter import (
    count_tokens,
    resolve_chat_limit,
    safe_budget,
    truncate_to_tokens,
)
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext
from services.tool_schemas import TOOL_CALLING_TOOLS
from services.typing_manager import typing_active

logger = logging.getLogger(__name__)

_PERSONA_MAX_ITEMS = 10          # 66.9: карточка — до 10 фактов/связей
_BLOCK_RE = re.compile(          # 66.12: блок «<Tag>\n…\n</Tag>» (тело для обрезки)
    r"^(<[A-Za-z_]+>\n)(.*)(\n</[A-Za-z_]+>)\s*$", re.DOTALL)


def _parse_mood_words(raw: str) -> tuple[str, ...]:
    """65.9: comma-separated env → кортеж слов (нижний регистр)."""
    return tuple(w.strip().lower() for w in str(raw or "").split(",") if w.strip())


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
                 breaker=None, cache=None, tool_router=None) -> None:
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

    # ── bot_replies (персистентная таблица; TTL 3600/cap 200 — 63.1) ──

    async def remember_bot_reply(self, chat_id: int, tg_message_id: int, text: str) -> None:
        """UPSERT ответа бота в bot_replies ПОСЛЕ успешной отправки (58.6).
        Fail-open: ошибка БД — WARNING, цепочка просто не запомнится."""
        try:
            await self.db.upsert_bot_reply(chat_id, tg_message_id, text, time.time())
        except Exception:
            logger.warning(
                "direct: bot_replies persist failed | chat=%s msg=%s",
                chat_id, tg_message_id, exc_info=True)

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
                            await self.remember_bot_reply(chat_id, replay_id, cached)
                        logger.info("[direct] dedup replay | chat=%s user=%s",
                                    chat_id, target_name)
                    else:
                        logger.info("[direct] dedup silence | chat=%s user=%s",
                                    chat_id, target_name)
                    return
            user_blocks = await self._build_user_content(chat_id, message, target_name)
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
                await self.remember_bot_reply(chat_id, sent_id, answer)
                # REVISE S2: memorize ТОЛЬКО ПОСЛЕ успешной отправки (58.8) —
                # fire-and-forget внутри гейта sent_id
                fire_and_forget(
                    self.memory.memorize_facts(
                        chat_id, f"{query}\n{answer}", "bot_direct_reply",
                        target_user=target_name),
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

    async def _build_user_content(self, chat_id: int, message, target_name: str) -> list[str]:
        """Порядок 58.9/59.3 + 65.4/65.9/65.10: [map, RAG_Memory, Target_User,
        Protected_Facts, Mood, Global_Context, Thread, Style_Anchors];
        статичное вверх, динамика вниз; <Target_User> — динамика.
        Epic 60 (66.12, T-490): бюджеты контекста — per-block токен-потолки от
        CHAT_CONTEXT_BUDGET_TOKENS + порядок урезания; порядок секций и
        промпты НЕ меняются; <Target_User> не урезается никогда (R50-1)."""
        window = await self.memory.get_window_messages(chat_id)
        blocks: list[tuple[str, str]] = []
        alias_map = self._build_alias_map(window)
        if alias_map:
            blocks.append(("map", alias_map))
        rag = await self.memory.get_rag_context(
            chat_id, (message.text or ""),
            sort_by_timestamp=True, include_direct_reply=True)
        if rag:
            blocks.append(("rag", f"<RAG_Memory>\n{rag}\n</RAG_Memory>"))
        blocks.append(("target", f"<Target_User>{escape_xml_text(target_name)}</Target_User>"))
        # Epic 60 (65.10, T-478): защищённые факты — сразу после Target_User.
        protected = await self._build_protected_facts(chat_id, target_name)
        if protected:
            blocks.append(("protected", protected))
        # Epic 60 (65.9, T-477): настроение — user-блок, промпт R50-4 не тронут.
        # T-619: флаг и слова настроения — горячие точки (фолбек settings).
        if hot.get("flags.chat_mood_enabled", settings.CHAT_MOOD_ENABLED):
            mood = self._build_mood_block((message.text or ""))
            if mood:
                blocks.append(("mood", mood))
        global_ctx = await self._build_global_context(chat_id, window)
        if global_ctx:
            blocks.append(("global", global_ctx))
        thread = await self._build_conversation_thread(chat_id, message)
        if thread:
            blocks.append(("thread", thread))
        # Epic 60 (65.4, T-472): стилевые якоря — ПОСЛЕ Thread (динамика вниз).
        anchors = await self._build_style_anchors(chat_id)
        if anchors:
            blocks.append(("anchors", anchors))
        # 66.12 (T-490): потолки сборки (порядок блоков НЕ меняется).
        return self._apply_context_budget(blocks)

    # ── Epic 60 Фаза D (66.12, T-490): бюджеты контекста ─────────

    def _apply_context_budget(self, blocks: list[tuple[str, str]]) -> list[str]:
        """Доли CHAT_CONTEXT_BUDGET_TOKENS: map/global/thread/rag/target+mood/
        anchors (66.12). Target_User и protected_facts НЕ урезаются. Сначала
        per-block потолки (truncate_to_tokens + WARNING), затем при превышении
        ОБЩЕГО бюджета — порядок урезания (сначала дешёвое): Style_Anchors →
        Global_Context → Thread → RAG_Memory → UserResolutionMap.
        Выключено → ровно старые потолки секций (64.7)."""
        # T-619: бюджеты — горячие точки (фолбек settings)
        if not hot.get("flags.chat_context_budgets_enabled",
                       settings.CHAT_CONTEXT_BUDGETS_ENABLED):
            return [text for _, text in blocks]
        budget = hot.get("limits.chat_context_budget_tokens",
                         settings.CHAT_CONTEXT_BUDGET_TOKENS)
        limits = {
            "map": max(1, int(budget * hot.get(
                "limits.chat_budget_map_ratio", settings.CHAT_BUDGET_MAP_RATIO))),
            "rag": max(1, int(budget * hot.get(
                "limits.chat_budget_rag_ratio", settings.CHAT_BUDGET_RAG_RATIO))),
            "target": max(1, int(budget * hot.get(
                "limits.chat_budget_target_ratio", settings.CHAT_BUDGET_TARGET_RATIO))),
            "global": max(1, int(budget * hot.get(
                "limits.chat_budget_global_ratio", settings.CHAT_BUDGET_GLOBAL_RATIO))),
            "thread": max(1, int(budget * hot.get(
                "limits.chat_budget_thread_ratio", settings.CHAT_BUDGET_THREAD_RATIO))),
            "anchors": max(1, int(budget * hot.get(
                "limits.chat_budget_anchors_ratio", settings.CHAT_BUDGET_ANCHORS_RATIO))),
        }

        def truncate(kind: str, text: str) -> str:
            if text is None or kind not in limits or limits[kind] <= 0:
                return text
            truncated = self._truncate_block(text, limits[kind])
            if truncated != text:
                logger.warning(
                    "direct: budget truncation | block=%s | tokens=%d -> %d",
                    kind, count_tokens(text), count_tokens(truncated))
            return truncated

        texts = {kind: text for kind, text in blocks}
        # target+mood делят долю target; Target_User неприкосновенен.
        if "mood" in texts:
            target_tokens = count_tokens(texts.get("target", ""))
            mood_limit = max(0, limits["target"] - target_tokens)
            mood_before = count_tokens(texts["mood"])
            if mood_before > mood_limit:
                texts["mood"] = self._truncate_block(texts["mood"], mood_limit)
                logger.warning(
                    "direct: budget truncation | block=mood | tokens=%d -> %d",
                    mood_before, count_tokens(texts["mood"]))
        for kind in ("map", "rag", "global", "thread", "anchors"):
            if kind in texts:
                texts[kind] = truncate(kind, texts[kind])

        total = sum(count_tokens(text) for text in texts.values())
        if total > budget:
            # Порядок урезания (сначала дешёвое), геометрическими шагами.
            order = ("anchors", "global", "thread", "rag", "map")
            for _ in range(20):
                if total <= budget:
                    break
                progress = False
                for kind in order:
                    if total <= budget:
                        break
                    if kind not in texts or limits[kind] <= 0:
                        continue
                    limits[kind] = max(0, limits[kind] // 2)
                    texts[kind] = self._truncate_block(texts[kind], limits[kind])
                    total = sum(count_tokens(text) for text in texts.values())
                    progress = True
                if not progress:
                    break
        return [texts[kind] for kind, _ in blocks if texts[kind]]

    def _truncate_block(self, block: str, limit_tokens: int) -> str:
        """66.12: обрезка блока по токенам с сохранением ОТКРЫВАЮЩЕГО и
        закрывающего тегов (тело режется С КОНЦА — свежие строки важнее,
        прецедент 64.7)."""
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
            return opening + truncate_to_tokens(body, inner_budget) + closing
        return truncate_to_tokens(text, limit_tokens)

    # ── Epic 60 Фаза C (65.4/65.9/65.10): якоря, настроение, защита ──

    async def _build_style_anchors(self, chat_id: int) -> str:
        """65.4: секция <style_anchors> из последних ответов бота (bot_replies,
        ASC). VERBATIM-шаблон; user-блок — R50-4 неприкосновенен. Fail-open:
        ошибка БД → WARNING + без секции."""
        if not hot.get("flags.chat_style_anchors_enabled",
                       settings.CHAT_STYLE_ANCHORS_ENABLED):
            return ""
        try:
            replies = await self.db.last_bot_replies(
                chat_id, hot.get("limits.chat_style_anchors_count",
                                 settings.CHAT_STYLE_ANCHORS_COUNT),
                time.time())
        except Exception:
            logger.warning("direct: style anchors read failed | chat=%s",
                           chat_id, exc_info=True)
            return ""
        if not replies:
            return ""
        anchor_cap = hot.get("limits.chat_style_anchor_max_chars",
                             settings.CHAT_STYLE_ANCHOR_MAX_CHARS)
        body = "\n".join(
            f"{i}. {t[:anchor_cap]}" for i, t in enumerate(replies, 1))
        return f"<style_anchors>\nвот как ты отвечал недавно, держи тон:\n{body}\n</style_anchors>"

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

    async def _build_protected_facts(self, chat_id: int, target_name: str) -> str:
        """65.10: защищённые факты подмешиваются в контекст (карточки-слоты —
        не размазываются при сжатии). Fail-open → без секции."""
        try:
            facts = await self.db.get_protected_facts(chat_id, target_name)
        except Exception:
            logger.warning("direct: protected facts read failed | chat=%s",
                           chat_id, exc_info=True)
            return ""
        if not facts:
            return ""
        body = "\n".join(f"- {escape_xml_text(fact)}" for fact in facts)
        return (f"<protected_facts>\nважные факты, помни о них всегда:\n"
                f"{body}\n</protected_facts>")

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
            protected = await self.db.get_protected_facts(chat_id, canon)
        except Exception:
            logger.warning("direct: persona card read failed | chat=%s name=%s",
                           chat_id, name, exc_info=True)
            return None
        facts = card["facts"]
        links = card["links"]
        n = len(facts) + len(protected)
        m = len(links)
        lines = list(protected) + list(facts)
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

    def _build_alias_map(self, window: list) -> str:
        """User Resolution Map (R51-2): «имя — user_id» по участникам окна
        Global_Context (алиасы.resolve); блок в НАЧАЛЕ user-контента (D211)."""
        names: dict[int, str] = {}
        for row in window:
            uid = row["user_id"]
            if uid is None:
                continue
            if uid not in names:
                names[uid] = self.aliases.resolve(
                    uid, (row["author_name"] or None), None)
        if not names:
            return ""
        lines = [f"{name} — {uid}" for uid, name in names.items()]
        return "<UserResolutionMap>\n" + "\n".join(lines) + "\n</UserResolutionMap>"

    async def _build_global_context(self, chat_id: int, window: list) -> str:
        """Последние CHAT_GLOBAL_CONTEXT_LIMIT сообщений (окно уже ASC),
        «[имя]: текст». Epic 60 (64.6, T-467): валидный бегущий конспект →
        <Global_Context> = конспект + дословный хвост сообщений с
        ts > window_end_ts. Epic 60 (64.7, T-468): потолок — токены
        (CHAT_GLOBAL_CONTEXT_MAX_TOKENS, срез С КОНЦА; chars — fallback)."""
        summary_text = None
        window_end_ts = None
        if hot.get("flags.chat_running_summary_enabled",
                   settings.CHAT_RUNNING_SUMMARY_ENABLED):
            try:
                row = await self.db.get_running_summary(chat_id, time.time())
                if row is not None:
                    summary_text = row["summary"]
                    window_end_ts = row["window_end_ts"]
            except Exception:
                logger.warning("direct: running summary read failed | chat=%s",
                               chat_id, exc_info=True)
        if summary_text is not None:
            lines = [summary_text]
            for row in window:
                if int(row["timestamp"] or 0) <= window_end_ts:
                    continue
                text = row["text"] or ""
                if not text:
                    continue
                name = self.aliases.resolve(
                    int(row["user_id"] or 0), (row["author_name"] or None), None)
                lines.append(f"{name}: {text}")
            body = "\n".join(lines)
        else:
            recent = window[-hot.get("limits.chat_global_context_limit",
                                     settings.CHAT_GLOBAL_CONTEXT_LIMIT):]
            lines = []
            for row in recent:
                text = row["text"] or ""
                if not text:
                    continue
                name = self.aliases.resolve(
                    int(row["user_id"] or 0), (row["author_name"] or None), None)
                lines.append(f"{name}: {text}")
            if not lines:
                return ""
            body = "\n".join(lines)
        kind, limit = resolve_chat_limit(
            hot.get("limits.chat_global_context_max_tokens", settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS), 1000,
            "CHAT_GLOBAL_CONTEXT_MAX_CHARS", hot.get("limits.chat_global_context_max_chars", settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS),
            "CHAT_GLOBAL_CONTEXT",
        )
        if kind == "tokens":
            budget = safe_budget(limit)
            if count_tokens(body) > budget:
                logger.warning("direct: global context truncated | tokens=%d -> %d",
                               count_tokens(body), budget)
                body = truncate_to_tokens(body, budget)
        elif len(body) > limit:
            logger.warning("direct: global context truncated | chars=%d", len(body))
            body = body[:limit]
        return f"<Global_Context>\n{escape_xml_text(body)}\n</Global_Context>"

    async def _build_conversation_thread(self, chat_id: int, message) -> str:
        """Рекурсивная цепочка reply по tg_message_id (глубина
        CHAT_THREAD_MAX_DEPTH): user-сообщения из БД (observer сохраняет все),
        бот-сообщения из bot_replies (Epic 60, 63.1 — персистентная таблица);
        при обрыве (нет reply_to_id/не найдено/TTL истёк) — стоп.
        Рендер сверху-вниз."""
        chain: list[tuple[str, str]] = []
        current_id = message.message_id
        seen: set[int] = set()
        for _ in range(hot.get("limits.chat_thread_max_depth",
                               settings.CHAT_THREAD_MAX_DEPTH)):
            if current_id is None or current_id in seen:
                break
            seen.add(current_id)
            row = await self.db.get_smart_message_by_tg_id(chat_id, current_id)
            if row is not None:
                text = row["text"] or ""
                if text:
                    name = self.aliases.resolve(
                        int(row["user_id"] or 0), (row["author_name"] or None), None)
                    chain.append((name, text))
                current_id = row["reply_to_id"]
                continue
            bot_text = await self.get_bot_reply(chat_id, current_id)
            if bot_text is not None:
                chain.append((self._resolve_bot_name(), bot_text))
                break                      # бот-сообщение — конец цепочки
            break                          # обрыв: нет reply_to_id/не найдено
        if not chain:
            return ""
        lines = [f"{name}: {text}" for name, text in reversed(chain)]
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
