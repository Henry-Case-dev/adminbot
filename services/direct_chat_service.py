"""Epic 50 — DirectChatService (Section 58, D200/D203-D207).

DirectChatThrottle — Token Bucket (58.5): per (chat_id, user_id), in-memory,
рестарт сбрасывает (прецедент CooldownTracker); полное восстановление
зарядов через CHAT_COOLDOWN_SECONDS после ПОСЛЕДНЕГО допущенного обращения.

DirectChatService — сборка контекст-секций (58.6), generate через
build_messages (58.9/59.3), _bot_replies (LRU 200/TTL 3600, прецедент
MediaGroupCaptionBuffer) для цепочек <Conversation_Thread>, fire-and-forget
memorize_facts с origin='bot_direct_reply' (58.8) ПОСЛЕ успешной отправки.
"""
import logging
import random
import time
from collections import OrderedDict

from config.settings import settings
from services.chat_prompts import CHAT_SYSTEM_PROMPT
from services.llm_client import LLMError
from services.payload_builder import build_messages
from services.smartmodule_phrases import CHAT_COOLDOWN_PHRASES, CHAT_ERROR_PHRASES
from services.smartmodule_throttling import format_remaining_time
from services.smartmodule_utils import _reply, send_chunked_reply
from services.summary_memory import fire_and_forget
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)

_BOT_REPLIES_MAX = 200        # лимит LRU (прецедент media_group_buffer.MAX_ENTRIES)
_BOT_REPLIES_TTL = 3600.0     # TTL ленивый


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
                 bot_id: int | None = None, bot_username: str | None = None) -> None:
        self.memory = memory
        self.db = db
        self.llm = llm
        self.aliases = aliases
        self.throttle = throttle or DirectChatThrottle(
            settings.CHAT_BURST_LIMIT, settings.CHAT_COOLDOWN_SECONDS)
        self.bot_id = bot_id
        self.bot_username = (bot_username or "").lower()
        # (chat_id, tg_message_id) -> (text, ts); записывается ПОСЛЕ успешной
        # отправки ответа бота (58.6).
        self._bot_replies: OrderedDict[tuple[int, int], tuple[str, float]] = OrderedDict()

    # ── _bot_replies (LRU 200 / TTL 3600, прецедент MediaGroupCaptionBuffer) ──

    def _cleanup_bot_replies(self) -> None:
        now = time.monotonic()
        expired = [k for k, rec in self._bot_replies.items() if now - rec[1] > _BOT_REPLIES_TTL]
        for k in expired:
            del self._bot_replies[k]

    def remember_bot_reply(self, chat_id: int, tg_message_id: int, text: str) -> None:
        self._cleanup_bot_replies()
        self._bot_replies[(chat_id, tg_message_id)] = (text, time.monotonic())
        self._bot_replies.move_to_end((chat_id, tg_message_id))
        if len(self._bot_replies) > _BOT_REPLIES_MAX:
            self._bot_replies.popitem(last=False)

    def get_bot_reply(self, chat_id: int, tg_message_id: int) -> str | None:
        rec = self._bot_replies.get((chat_id, tg_message_id))
        if rec is None:
            return None
        if time.monotonic() - rec[1] > _BOT_REPLIES_TTL:
            del self._bot_replies[(chat_id, tg_message_id)]
            return None
        return rec[0]

    # ── Поток хендлера (58.4) ─────────────────────────────────

    async def handle(self, bot, message, user) -> None:
        """Триггер уже проверен хендлером. Кулдаун → фраза R50-7; иначе —
        контекст → LLM → Reply → memorize (fire-and-forget, ПОСЛЕ отправки)."""
        chat_id = message.chat.id
        user_id = user.id if user is not None else 0
        target_name = self._resolve_name(user)
        query = (message.text or "").strip()
        remaining = self.throttle.allow(chat_id, user_id)
        if remaining > 0:
            phrase = random.choice(CHAT_COOLDOWN_PHRASES).replace(
                "{remaining_time}", format_remaining_time(remaining))
            await _reply(bot, chat_id, phrase, message.message_id)
            logger.warning("[direct] cooldown | chat=%s user=%s remaining=%.0fs",
                           chat_id, target_name, remaining)
            return
        logger.info("[direct] triggered | chat=%s user=%s", chat_id, target_name)
        try:
            user_blocks = await self._build_user_content(chat_id, message, target_name)
            payload = build_messages(CHAT_SYSTEM_PROMPT, user_blocks)
            raw = await self.llm.generate(payload)
            answer = str(raw).strip()
            sent_id = await send_chunked_reply(bot, chat_id, answer, message.message_id)
            if sent_id is not None:
                self.remember_bot_reply(chat_id, sent_id, answer)
                # REVISE S2: memorize ТОЛЬКО ПОСЛЕ успешной отправки (58.8) —
                # fire-and-forget внутри гейта sent_id
                fire_and_forget(
                    self.memory.memorize_facts(
                        chat_id, f"{query}\n{answer}", "bot_direct_reply",
                        target_user=target_name),
                    "direct")
            logger.info("[direct] reply sent | chat=%s user=%s", chat_id, target_name)
        except LLMError as exc:
            logger.warning("[direct] LLM failed | chat=%s | user=%s | error=%s",
                           chat_id, target_name, exc)
            await _reply(bot, chat_id, random.choice(CHAT_ERROR_PHRASES),
                         message.message_id)
        except Exception:
            logger.exception("[direct] unexpected | chat=%s", chat_id)
            await _reply(bot, chat_id, random.choice(CHAT_ERROR_PHRASES),
                         message.message_id)

    # ── Context Partitioning (58.6) ─────────────────────────────

    async def _build_user_content(self, chat_id: int, message, target_name: str) -> list[str]:
        """Порядок 58.9/59.3: [map, RAG_Memory, Target_User, Global_Context,
        Thread]; статичное вверх, динамика вниз; <Target_User> — динамика."""
        window = await self.memory.get_window_messages(chat_id)
        blocks: list[str] = []
        alias_map = self._build_alias_map(window)
        if alias_map:
            blocks.append(alias_map)
        rag = await self.memory.get_rag_context(
            chat_id, (message.text or ""),
            sort_by_timestamp=True, include_direct_reply=True)
        if rag:
            blocks.append(f"<RAG_Memory>\n{rag}\n</RAG_Memory>")
        blocks.append(f"<Target_User>{escape_xml_text(target_name)}</Target_User>")
        global_ctx = self._build_global_context(window)
        if global_ctx:
            blocks.append(global_ctx)
        thread = await self._build_conversation_thread(chat_id, message)
        if thread:
            blocks.append(thread)
        return blocks

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

    def _build_global_context(self, window: list) -> str:
        """Последние CHAT_GLOBAL_CONTEXT_LIMIT сообщений (окно уже ASC),
        «[имя]: текст», потолок CHAT_GLOBAL_CONTEXT_MAX_CHARS (slice + WARNING)."""
        recent = window[-settings.CHAT_GLOBAL_CONTEXT_LIMIT:]
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
        if len(body) > settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS:
            logger.warning("direct: global context truncated | chars=%d", len(body))
            body = body[:settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS]
        return f"<Global_Context>\n{escape_xml_text(body)}\n</Global_Context>"

    async def _build_conversation_thread(self, chat_id: int, message) -> str:
        """Рекурсивная цепочка reply по tg_message_id (глубина
        CHAT_THREAD_MAX_DEPTH): user-сообщения из БД (observer сохраняет все),
        бот-сообщения из _bot_replies (в БД их нет — B9-стиль); при обрыве
        (нет reply_to_id/не найдено/TTL истёк) — стоп. Рендер сверху-вниз."""
        chain: list[tuple[str, str]] = []
        current_id = message.message_id
        seen: set[int] = set()
        for _ in range(settings.CHAT_THREAD_MAX_DEPTH):
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
            bot_text = self.get_bot_reply(chat_id, current_id)
            if bot_text is not None:
                chain.append((self._resolve_bot_name(), bot_text))
                break                      # бот-сообщение — конец цепочки
            break                          # обрыв: нет reply_to_id/не найдено
        if not chain:
            return ""
        lines = [f"{name}: {text}" for name, text in reversed(chain)]
        body = "\n".join(lines)
        if len(body) > settings.CHAT_THREAD_MAX_CHARS:
            logger.warning("direct: thread truncated | chars=%d", len(body))
            body = body[:settings.CHAT_THREAD_MAX_CHARS]
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
