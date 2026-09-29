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

Epic 60 (Section 63.2, R60-2, T-461): per-chat замок вокруг генерации
ПОСЛЕ throttle/CB-веток (мгновенные — не стоят в очереди); таймаут
CHAT_LOCK_WAIT_SECONDS → CHAT_LOCK_BUSY_PHRASES; FIFO → порядок ответов.
Раунд N (T-839/T-840): per-chat asyncio.Lock заменён на пул семафоров
services/smartmodule_concurrency (ChatConcurrencyPool) — до N параллельных
генераций одного чата (limits.smartmodule_concurrency_per_chat, 1 = строгая
очередь как раньше); таймаут ожидания по-прежнему CHAT_LOCK_WAIT_SECONDS →
CHAT_LOCK_BUSY_PHRASES.

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
    anchors→rag→thread→global(keep-head)→map→nostalgia (маркер слоя A —
    последним, раунд 9 E1/T-826).
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

Раунд 9 (AGI Memory, spec §3.1.4/Q3, T-819/B4): инжект `<user_relations>` —
строка отношений собеседника (стадия/активность/заметка админа) сразу после
<Target_User>, kind "relations" в uncuttable (вне контекст-бюджета), cap
limits.relations_inject_max_chars (600) до инжекта. Гейты: глобальный флаг
flags.relations_tone_enabled И per-chat relations_enabled из PG-профиля
(кэш); только группы (chat_id<0, D-12); RelationsService — лениво из
lore_runtime (не установлен/ошибка → блока нет, 0 влияния на поведение).
Канон R9 (§3.2.2) уже описывает блок и тон по стадиям.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass

from aiogram.exceptions import TelegramBadRequest

from config.settings import settings
from services import chat_access
from services import hot_config as hot
from services import bot_persona
from services import thread_chain
from services import mca_gates
from services import mca_retrieval_context as _mca_rc
from services import command_prefix  # ASAP-3: persona-name force-детект (F6)
from services.chat_params import (
    chat_summary_enabled,
    get_chat_param as _cp_g,  # G-3 per-chat
)
from services.sandbox_reply import DEFAULT_NO_KEY_REPLY
from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    DIRECT_SYNTHESIZER_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
    PREV_CHAT_VERBALIZER_R1023,
)
from services.dossier_prompts import format_dossier_block
from services.llm_client import (
    LLMBadResponseError,
    LLMError,
    LLMServerError,
    LLMTimeoutError,
    LLMTransportError,
    NoApiKeyForChat,
)
from services.llm_circuit_breaker import STATE_HALF_OPEN, LLMCircuitBreaker
from services.budget_limits import context_state
from services.canonical_context import (
    format_chat_time,
    format_context_item,
    resolve_item_id,
    strip_context_header,
)
from services.database import row_get
from services.media_marker import (
    media_context_enabled, media_marker, message_media_type)
from services import native_media as native_media_module
from services.payload_builder import build_messages
from services.persistent_throttling import SilenceStreak
from services.smartmodule_concurrency import get_smartmodule_concurrency_pool
from services.smartmodule_phrases import (
    CHAT_COOLDOWN_PHRASES,
    CHAT_ERROR_PHRASES,
    CHAT_LLM_DOWN_PHRASES,
    CHAT_LOCK_BUSY_PHRASES,
)
from services.smartmodule_throttling import format_remaining_time
from services.smartmodule_utils import (
    REACTION_APPROVE,
    REACTION_FIRE,
    REACTION_LAUGH,
    _reply,
    escape_lore_html,
    react_moai,
    reaction_mechanics_enabled,
    send_chunked_reply,
    strip_lore_html,
)
from services.smart_cache import normalize_text
from services.smartmodule_urls import resolve_context_url
from services.self_reflection import extract_self_essence, record_extractor_status
from services.summary_memory import (
    _SELF_ECHO_INSTRUCTION,
    build_rag_context,
    dedup_rag_vs_global,
    fire_and_forget,
    order_rag_facts_asc,
)
from services.summary_xml import escape_xml_text
from services.target_marking import is_target_row
from services.token_counter import (
    append_protected_spans,
    count_tokens,
    estimation_method,
    has_protected_spans,
    resolve_chat_limit,
    resolve_context_tokens,
    safe_budget,
    truncate_to_tokens,
    truncate_to_tokens_keep_head,
)
from services.context_middleware import truncate_keep_header
from services.reply_postprocess import strip_reasoning_tags
from services import anticliche_cache
from services.agentic_events import emit_agentic_event
from services import usage_events
from services.negative_constraints import (
    channel_enabled_rules,
    verbalize_validated,
)
from services.prompt_style_blocks import (
    compose_verbalizer_system,
    resolve_prompt,
)
from services.system2_handoff import (
    normalize_response_mode,
    parse_direct_synthesis,
    redact_secrets,
    stage2_payload,
)
from services.tool_loop import chat_with_tools, ToolLoopResult
from services.tool_router import ToolContext
from services.tool_schemas import active_tools
from services.typing_manager import typing_active
from services.user_relations import STAGE_RU
from services.nostalgia_prompts import format_nostalgia_hint
# ── ASAP-3 (round 1028, ADR-1028-2): единый Direct Context Composer + ──────
# model-aware capacity (D1–D7) и observability-хелперы (D15). Consumer-side:
# token_counter/Summary не меняются (D11).
from services import direct_context_composer as _composer
from services.model_capacity import (
    apply_budget_policy,
    compute_available_budget,
    resolve_effective_window,
)

logger = logging.getLogger(__name__)

# Раунд 9 (B4/T-819): маркер обрезания <user_relations> по кап-символам.
_RELATIONS_CUT_MARKER = "…[обрезано]"
# Раунд 9 (T-821/C2(6), фикс-раунд major-1, spec §3.2.3): маркеры ностальгии
# для пре-гейта dig (флаг flags.dig_pre_gate_enabled, default false). Regex
# по тексту сообщения (без границ слов — «как мы тогда гуляли» и т.п.);
# «в 20\d\d» — упоминание года («в 2024»).
_NOSTALGIA_MARKERS_RE = re.compile(
    r"помнишь|помните|как мы тогда|как вы тогда|год назад|лет назад|"
    r"в 20\d\d|кто был тот|а было же|когда-то", re.IGNORECASE)
# Потолок инжекта <dig_result> (спека §3.2.3; dig уже режет 3500 сам —
# страховка для результатов не-dig веток).
_DIG_RESULT_MAX_CHARS = 3600
# S10.20-10: лимит Telegram-сообщения — HTML-история шлётся разметкой только
# если экранированный текст влезает в ОДИН чанк (иначе чанкинг мог порвать
# тег → TelegramBadRequest → дубль текста plain-фолбэком).
_LORE_HTML_MAX_SINGLE_CHARS = 4096
# Раунд 9 (E1/T-826, spec §3.5.1): доля блок-маркера ностальгии в бюджете
# урезания — константа (REGISTRY-ключа в spec §3.6.4 нет): блок маленький
# (фикс-кап 300 симв. ДО инжекта), в общем порядке урезания участвует
# ПОСЛЕДНИМ (после map), при давлении режется целиком.
_NOSTALGIA_BUDGET_RATIO = 0.02
# MCA-07 (T-3849, D7): резерв токенов под protected-span-хвост при обрезке
# (отрицание/ID/дата переносятся, а не теряются).
_PROTECTED_SPAN_RESERVE_BUDGET = 48

# MCA-07 (T-3851): одноразовый маркер эмиссии `answer_cache_disabled` (не
# спамим событием на каждое сообщение; R17-safe — только код).
_answer_cache_disabled_emitted = False


def _answer_cache_disabled_notified() -> bool:
    """True, если событие `answer_cache_disabled` уже эмитировано в процессе."""
    global _answer_cache_disabled_emitted
    if _answer_cache_disabled_emitted:
        return True
    _answer_cache_disabled_emitted = True
    return False


def _legacy_text_replay_enabled() -> bool:
    """MCA-07 (T-3851): прежний text-replay активен только при гейте OFF.

    ON (default) → MCA-07 context-keyed политика (legacy-кеш query/chat/user
    для контекстных ответов отключён); OFF → прежний ответный кеш (baseline)."""
    return not mca_gates.context_answer_cache_enabled()

# ── F5 (cognition-dashboard-round1013, spec §3.6/F5-Q4): in-memory
#    accounting последнего собранного контекста + времени инжекта лора.
#    R17-safe: только ОЦЕНКА токенов (число), флаг урезания и ts; ни текста
#    промпта, ни эмбеддингов, ни ключей. Рестарт сбрасывает (прецедент
#    DirectChatThrottle) — фронт показывает «—», если данных нет.
_PROCESS_ACCOUNTING: dict = {
    "context_used": None,       # оценка токенов последнего контекста
    "context_limit": None,      # применённый cap CHAT_CONTEXT_BUDGET_TOKENS
    "context_unlimited": False,  # D-7: общий бюджет `-1` → «Безлимит (∞)»
    "context_truncated": False,  # RAG/стиль резались (красный прогресс-бар)
    "lore_last_inject_at": None,  # ts последнего инжекта <chat_lore>
    "updated_at": None,
}


def record_context_usage(used: int | None, limit: int | None,
                         truncated: bool, unlimited: bool = False) -> None:
    """F5: записать оценку последнего контекста (вызывает _apply_context_budget).
    D-7: `unlimited=True` (бюджет `-1`) → `limit=None`, UI показывает
    «Безлимит (∞)» вместо ложных 100% (used/used). Никогда не бросает —
    телеметрия не должна ломать генерацию."""
    try:
        _PROCESS_ACCOUNTING["context_used"] = (
            int(used) if used is not None else None)
        _PROCESS_ACCOUNTING["context_limit"] = (
            None if unlimited else (int(limit) if limit is not None else None))
        _PROCESS_ACCOUNTING["context_unlimited"] = bool(unlimited)
        _PROCESS_ACCOUNTING["context_truncated"] = bool(truncated)
        _PROCESS_ACCOUNTING["updated_at"] = int(time.time())
    except Exception:  # pragma: no cover — защитная сетка
        logger.warning("direct: context accounting record failed",
                       exc_info=True)


def record_lore_inject(ts: int | None = None) -> None:
    """F5: запомнить ts инжекта <chat_lore> (виджет «Интеллект и Память»)."""
    try:
        _PROCESS_ACCOUNTING["lore_last_inject_at"] = int(
            ts if ts is not None else time.time())
    except Exception:  # pragma: no cover
        logger.warning("direct: lore inject accounting failed", exc_info=True)


def get_process_accounting() -> dict:
    """F5: снимок accounting для /api/status.context и cognition/status.
    ASAP-3 (D15): + `direct_metrics` — счётчики §46 (process-local)."""
    snapshot = {
        "context_used": _PROCESS_ACCOUNTING.get("context_used"),
        "context_limit": _PROCESS_ACCOUNTING.get("context_limit"),
        "context_unlimited": bool(
            _PROCESS_ACCOUNTING.get("context_unlimited")),
        "context_truncated": bool(_PROCESS_ACCOUNTING.get("context_truncated")),
        "lore_last_inject_at": _PROCESS_ACCOUNTING.get("lore_last_inject_at"),
        "updated_at": _PROCESS_ACCOUNTING.get("updated_at"),
    }
    try:
        snapshot["direct_metrics"] = _composer.direct_metrics_snapshot()
    except Exception:      # pragma: no cover - защитная сетка
        snapshot["direct_metrics"] = {}
    return snapshot


_PERSONA_MAX_ITEMS = 10          # 66.9: карточка — до 10 фактов/связей
# F8 (cognition-irony-dossier-round1013, spec §6): общий символьный бюджет
# блоков досье [Факты]/[Локальные мемы/Ярлыки] (мемы режутся первыми).
_PERSONA_DOSSIER_MAX_CHARS = 1200
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

# MCA-07 (T-3852, ADR-1027-7 D5/D6): EvidenceBundle в живом пути. Из user-
# блоков извлекаются только ССЫЛКИ-идентификаторы канонического рендера
# (`tg:/msg:/fact:`) и ограничения (текущий вопрос) — не сырьё (R17).
_REF_ID_RE = re.compile(r"(?:tg|msg|fact):\d+")
_BUNDLE_BLOCK_MAX_REFS = 20


def _block_with_tag(blocks, tag: str) -> str:
    """Первый user-блок, содержащий ``<tag`` (fail-open → "").

    Принимает как список строк (реальный путь), так и пары (kind, text)."""
    needle = f"<{tag}"
    for block in blocks or []:
        if isinstance(block, (tuple, list)) and block:
            text = str(block[-1])
        else:
            text = str(block)
        if needle in text:
            return text
    return ""


# ── ASAP-3 (ADR-1028-2 D4/D5): tg-id хелперы episode/middle-контура ─────────

def _tg_id_of_row(row) -> int | None:
    """tg_message_id строки smart_messages (int | None, fail-open)."""
    try:
        value = row_get(row, "tg_message_id")
    except Exception:
        value = None
    try:
        return int(value) if value not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


def _tg_id_of_ref(ref: str) -> int | None:
    """tg-id из канонической ссылки ``tg:<id>`` (иначе None)."""
    text = str(ref or "").strip()
    if text.startswith("tg:"):
        try:
            return int(text[3:])
        except ValueError:
            return None
    return None


def _inner_tag_text(block: str, tag: str) -> str:
    """Внутренний текст ``<tag>…</tag>`` (без тега); нет → ""."""
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>",
                      str(block or ""), re.DOTALL)
    return match.group(1).strip() if match else ""


def _block_lines(block: str) -> list[str]:
    """Непустые строки блока (bounded — обрезаются вызывающим)."""
    return [line.strip() for line in str(block or "").splitlines()
            if line.strip()]


def _map_names(block: str) -> list[str]:
    """Имена из ``<UserResolutionMap>`` (строки ``«имя - uid»`` → имя)."""
    names: list[str] = []
    for line in _block_lines(_inner_tag_text(block, "UserResolutionMap")):
        name = line.split(" - ", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _bundle_scoped_slice(bundle) -> str:
    """Компактный scoped-срез bundle для System2 после tool loop (D6/SC-09).

    Адресат/автор/ветка/ограничения/`context_version` — R17-safe (имена, ID-
    ссылки, версия). Пусто при ``bundle is None`` или gate OFF (паритет)."""
    if bundle is None or not mca_gates.evidence_bundle_enabled():
        return ""
    parts: list[str] = []
    if getattr(bundle, "addressee", None):
        parts.append(f"Адресат: {bundle.addressee}")
    if getattr(bundle, "author", None):
        parts.append(f"Автор: {bundle.author}")
    branch = tuple(getattr(bundle, "branch", ()) or ())
    if branch:
        parts.append("Ветка: " + ", ".join(branch[:_BUNDLE_BLOCK_MAX_REFS]))
    constraints = tuple(getattr(bundle, "constraints", ()) or ())
    if constraints:
        parts.append("Ограничения: " + "; ".join(constraints))
    context_version = getattr(bundle, "context_version", None)
    if not parts and not context_version:
        return ""
    header = "КОНТЕКСТ ДИАЛОГА (не терять):"
    text = header + (("\n" + "\n".join(parts)) if parts else "")
    # R17: свободный текст маскируется; context_version — детерминированный
    # хэш-версия (не секрет), добавляется ПОСЛЕ маскирования.
    text = redact_secrets(text)
    if context_version:
        text += f"\ncontext_version: {context_version}"
    return text


def _format_generated_portrait_block(generated) -> str:
    """F1 (spec §3.2.1): аддитивные блоки карточки `/persona` из
    сгенерированного Слоем Б портрета. Нет строки/пусто → '' (байт-в-байт
    прежний вывод карточки)."""
    if not isinstance(generated, dict):
        return ""
    portrait = str(generated.get("portrait") or "").strip()
    patterns = [str(x).strip() for x in (generated.get("patterns") or [])
                if str(x).strip()]
    themes = [str(x).strip() for x in (generated.get("themes") or [])
              if str(x).strip()]
    parts = []
    if portrait:
        parts.append("[Психологический портрет]\n" + portrait)
    if patterns:
        parts.append("[Паттерны]\n" + "\n".join(patterns))
    if themes:
        parts.append("[Темы]\n" + "\n".join(themes))
    return "\n".join(parts)


def _parse_mood_words(raw: str) -> tuple[str, ...]:
    """65.9: comma-separated env → кортеж слов (нижний регистр)."""
    return tuple(w.strip().lower() for w in str(raw or "").split(",") if w.strip())


def _forward_source_of(message) -> str:
    """Источник пересылки TG-сообщения (для provenance факта, T-1924).

    Реюз готового каскада `handlers.summary._extract_forward_source` (ленивый
    импорт — сервис не зависит от handler-слоя на загрузке). Не forward или
    ошибка → '' (R16: не выдумываем)."""
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return ""
    try:
        from handlers.summary import _extract_forward_source
        return str(_extract_forward_source(origin) or "")
    except Exception:
        logger.debug("[direct] forward source extract failed — skipped")
        return ""


def _nostalgia_markers(text: str) -> bool:
    """Раунд 9 (фикс-раунд major-1, spec §3.2.3): есть ли в сообщении маркер
    ностальгии (помнишь, как мы тогда, год назад, «в 20XX» и т.п.)."""
    return bool(_NOSTALGIA_MARKERS_RE.search(str(text or "")))


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


# Раунд 10.23 (F2, ADR-1023-2): цепочка реплаев вынесена в общий util
# `services/thread_chain.py`; здесь — обратно-совместимые алиасы (тесты/код
# direct продолжают импортировать `_ChainItem`/`_speaker_tag`).
_ChainItem = thread_chain.ChainItem


def _speaker_tag(name: str, uid, *, is_bot: bool = False,
                 suffix: str = "") -> str:
    """Раунд 8 (§3.0/C1): display-строка участника — делегат общего
    ``thread_chain.speaker_tag`` (F2). «{имя}{суффикс} [{uid}]» (бот —
    «{имя} [bot]»). uid None/0 → без скобки."""
    return thread_chain.speaker_tag(name, uid, is_bot=is_bot, suffix=suffix)


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
    # 10.20 (БЛОК 0, ADR-1020-1 ред. 3, Р5/R23): после канонизации строк
    # <Global_Context> первое «:» уезжает в заголовок («msg:<id>») — сначала
    # срезаем канонический заголовок, затем (для не-канонических строк)
    # сохраняем легаси-разбор по первому «:» (speaker-prefix).
    stripped = strip_context_header(text)
    if stripped != text:
        content = stripped.strip()
    else:
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


# ── A1 (round 10.26, ADR-1026-14 D1/D2/D9): Координатор инструментов ──────
# Программный слой принятия решения ВНУТРИ существующего Синтезатора
# (direct-контур). 0 LLM-вызовов (§13 «не создавать дополнительный LLM-вызов
# там, где достаточно программной логики»); модельный выбор инструментов
# сохранён (`tool_choice='auto'`); wire-поле `action` НЕ вводится (граница
# A7). Решение — внутренний объект; логи — R17-safe (числа/коды/имена
# инструментов, без сырья/промптов/сырых ответов LLM).

ACTION_REPLY = "reply"      # доставка текста (готовый текст / Вербализатор)
ACTION_REACT = "react"      # не-текстовый исход (существующая 🗿-реакция)
ACTION_SILENT = "silent"    # молчание без реакции (резерв A8; политика не вводится)
ACTION_TOOL = "tool"        # ход с реально вызванными инструментами → Stage-2
COORDINATOR_ACTIONS = (ACTION_REPLY, ACTION_REACT, ACTION_SILENT, ACTION_TOOL)

# ── A7 (round 10.26, ADR-1026-20 D1/D3/D5/D9): Decision Making ──────────────
# Программная политика §42–§45 (Фаза P) + контекст §47 + R17-safe reason_code.
# 0 LLM-вызовов; реакции — reuse существующего `react_moai` (D5).
REACTION_MOAI = "🗿"

# Закрытый R17-safe словарь причин решения (D9; ровно 15 кодов).
REASON_EXPLICIT_REQUEST = "explicit_request"
REASON_QUESTION = "question"
REASON_IMAGE_REACTION = "image_reaction"
REASON_LAUGHTER = "laughter"
REASON_EMOTION = "emotion"
REASON_ACKNOWLEDGEMENT = "acknowledgement"
REASON_EMOJI_REACTION = "emoji_reaction"
REASON_NOT_ADDRESSED = "not_addressed"
REASON_DIALOGUE_COMPLETED = "dialogue_completed"
REASON_RECENT_REPLY = "recent_reply"
REASON_TOOL_RESULT = "tool_result"
REASON_TOOL_UNAVAILABLE = "tool_unavailable"
REASON_DISABLED = "disabled"
REASON_DEFAULT = "default"
REASON_ERROR = "error"
# ASAP-3 (ADR-1028-2 D8, §19A/§21): force-keyword/имя/mention → гарантированный
# текстовый ответ. Аддитивный 16-й код (существующие 15 не переименовываются).
REASON_FORCE_DIRECT = "force_direct"
REASON_CODES = frozenset({
    REASON_EXPLICIT_REQUEST, REASON_QUESTION, REASON_IMAGE_REACTION,
    REASON_LAUGHTER, REASON_EMOTION, REASON_ACKNOWLEDGEMENT,
    REASON_EMOJI_REACTION, REASON_NOT_ADDRESSED, REASON_DIALOGUE_COMPLETED,
    REASON_RECENT_REPLY, REASON_TOOL_RESULT, REASON_TOOL_UNAVAILABLE,
    REASON_DISABLED, REASON_DEFAULT, REASON_ERROR,
    REASON_FORCE_DIRECT,
})

# A8 (round 10.26, ADR-1026-21 D1): детерминированная карта `reason_code →
# эмодзи` (механика, делегированная A7→A8 в ADR-1026-20 D5). A7-политика
# «когда/какую» (классы/приоритеты/`action`) НЕ меняется — меняется только
# значение эмодзи уже выбранной ветки `react`. `REACTION_MOAI` 🗿 — дефолт/
# fallback. Строки `:832/839/847/859` используют `_reaction_for_reason(...)`.
_REACTION_BY_REASON = {
    REASON_IMAGE_REACTION: REACTION_LAUGH,
    REASON_LAUGHTER: REACTION_LAUGH,
    REASON_EMOJI_REACTION: REACTION_APPROVE,
    REASON_EMOTION: REACTION_FIRE,
}


def _reaction_for_reason(reason: str | None) -> str:
    """Контекстный эмодзи для reason-кода A7 (D1); 🗿 — дефолт/fallback.

    Kill-switch OFF → всегда 🗿 (OFF-лог и OFF-поведение совпадают, D10)."""
    if not reaction_mechanics_enabled():
        return REACTION_MOAI
    return _REACTION_BY_REASON.get(reason, REACTION_MOAI)


# Программные классы сообщений (§3.3) — R17-safe (внутренние коды).
MSG_EXPLICIT = "explicit_request"
MSG_QUESTION = "question"
MSG_LAUGHTER = "laughter"
MSG_EMOJI = "emoji_only"
MSG_ACK = "acknowledgement"
MSG_OTHER = "other"

# §43-маркеры явных содержательных обращений (программно, без LLM).
_EXPLICIT_MARKERS = (
    "нарисуй", "сгенерируй", "картинк", "изображени", "фактчек",
    "проверь факт", "правда ли", "найди", "загугли", "поищи", "объясни",
    "расскажи", "что ты знаешь", "ответь в стиле", "переведи", "прочитай",
    "скачай", "сделай", "покажи", "напиши", "составь", "придумай", "помоги",
)
# Вопросительные конструкции (без «?») — считаем question (§42/§43).
_QUESTION_STARTS = ("кто", "что", "где", "когда", "почему", "зачем", "как",
                    "какой", "какая", "какие", "сколько", "куда", "чей",
                    "можно ли")
_LAUGH_RE = re.compile(
    r"а?хах|хаха|хех|кек|лол|ржу|ору\b|смешно|😂|🤣|😆|😹|🙈",
    re.IGNORECASE)
# Одиночный эмодзи/знак (без букв и цифр), короткий.
_EMOJI_ONLY_RE = re.compile(r"^[^\w]{1,8}$", re.UNICODE)
# A7 (F-3): вопросительная пунктуация без слов («?», «???», «?!») — это
# короткий, но реальный вопрос (§42/REQ-A7-12), а не эмодзи-реакция.
_QUESTION_PUNCT_RE = re.compile(r"^[^\w]*\?[^\w]*$", re.UNICODE)
# A7 (F-3): прочая «пустая» пунктуация без слов («...», «..») — тоже НЕ
# эмодзи-реакция; fail-safe → other (политика ответит, не «съест»).
_ELLIPSIS_ONLY_RE = re.compile(r"^[.\s…]+$", re.UNICODE)
# Короткие подтверждения (§42) — точные формы (нормализованные).
_ACK_WORDS = frozenset({
    "ок", "окей", "ok", "okay", "понял", "поняла", "понятно", "спасибо",
    "благодарю", "ясно", "принято", "ладно", "хорошо", "угу", "ага",
    "плюс", "👍", "🔥",
})
_BOTWORD_RE = re.compile(r"(?i)\bбот\w*")
_ACK_STRIP = " \t!.,…"


# ── ASAP-3 (round 1028, ADR-1028-2 D9, §24): REACT — полноценный outcome ───
# Детерминированные наборы кандидатов по классу сообщения (аддитивно к карте
# A8 `_REACTION_BY_REASON`; только standard Telegram reaction enum). Выбор из
# набора — стабильный hash по message_id (детерминизм, без LLM/рандома).
_REACTION_SETS_BY_CLASS: dict[str, tuple[str, ...]] = {
    MSG_LAUGHTER: (REACTION_LAUGH, "🤣"),      # laughter → 😂/🤣
    MSG_EMOJI: (REACTION_APPROVE, "👌"),        # ack/emoji → 👍/👌
    MSG_ACK: (REACTION_APPROVE, "👌", "❤️"),    # подтверждение/похвала
}
_REACTION_DOUBT_SET: tuple[str, ...] = ("🤨", "🤔")   # сомнение (context-ветки)


def _stable_reaction_pick(candidates: tuple[str, ...],
                          message_id) -> str:
    """Детерминированный выбор из набора (stable hash по message_id)."""
    if not candidates:
        return REACTION_MOAI
    try:
        key = int(message_id)
    except (TypeError, ValueError):
        key = 0
    return candidates[key % len(candidates)]


def _reaction_for_class(message_class: str, message_id=None) -> str:
    """Реакция по классу сообщения (набор кандидатов + стабильный выбор)."""
    if not reaction_mechanics_enabled():
        return REACTION_MOAI
    candidates = _REACTION_SETS_BY_CLASS.get(message_class)
    if not candidates:
        return REACTION_MOAI
    return _stable_reaction_pick(candidates, message_id)


# ── ASAP-3 (ADR-1028-2 D8, §19/§20/§23): trigger-модель адресации ───────────
TRIGGER_FORCE_KEYWORD = "force_keyword"
TRIGGER_MENTION = "mention"
TRIGGER_PERSONA_NAME = "persona_name"
TRIGGER_REPLY_TO_BOT = "reply_to_bot"
TRIGGER_FREE_WILL = "free_will"


def silent_ack_enabled() -> bool:
    """Kill-switch `DIRECT_SILENT_ACK_ENABLED` (env ClassVar, default ON;
    per-call; никогда не бросает). OFF → тишина без 🗿 (паритет baseline)."""
    try:
        return bool(getattr(settings, "DIRECT_SILENT_ACK_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def autonomous_reply_enabled() -> bool:
    """Env-дефолт `CHAT_AUTONOMOUS_REPLY_ENABLED` (Settings-поле, default ON;
    per-chat-override — `flags.chat_autonomous_reply_enabled`)."""
    try:
        return bool(getattr(settings, "CHAT_AUTONOMOUS_REPLY_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def bot_replied_recently_window_seconds() -> int:
    """`CHAT_BOT_REPLIED_RECENTLY_SECONDS` (env, default 600; ≥0)."""
    try:
        value = int(getattr(settings, "CHAT_BOT_REPLIED_RECENTLY_SECONDS",
                            600))
    except Exception:      # pragma: no cover - защитная ветка
        value = 600
    return max(0, value)


def _resolve_direct_trigger(query: str, *, reply_to_bot: bool,
                            bot_username: str, persona_name_check=None
                            ) -> tuple[str, bool]:
    """Матрица §4.1 (D8): ``(trigger_type, force_reply_required)``.

    Приоритет: (1) force — botword / persona-name / mention в тексте
    (независимо от reply) → force_reply_required=True; (2) reply_to_bot →
    autonomous (Decision Making); (3) прочее → free_will (в handle() не
    попадает; фон живёт своей политикой — 🗿 запрещён). R17: текст не
    логируется, только классификация."""
    text = str(query or "")
    # (1a) бот-слово («бот, …»/«ботик»/…) — configured pattern-семья.
    if _BOTWORD_RE.search(text):
        return TRIGGER_FORCE_KEYWORD, True
    # (1b) имя персоны («Олег, …») — F6-резолв хендлера.
    if persona_name_check is not None and persona_name_check(text):
        return TRIGGER_PERSONA_NAME, True
    # (1c) упоминание: @username в тексте (entities-ветку проверил гейт).
    if bot_username and ("@" + bot_username) in text.lower():
        return TRIGGER_MENTION, True
    # (2) Telegram reply на сообщение бота → автономное решение.
    if reply_to_bot:
        return TRIGGER_REPLY_TO_BOT, False
    return TRIGGER_FREE_WILL, False


@dataclass
class DecisionContext:
    """Контекст §47 (R17-safe признаки, без сырого текста) для Фазы P.

    ASAP-3 (ADR-1028-2 D8): аддитивные поля адресации `trigger_type`
    (force_keyword|mention|persona_name|reply_to_bot|free_will) и
    `force_reply_required` (§20: force → ACTION_REPLY всегда; reply_to_bot →
    Decision Making). Заполняются резолвом матрицы в handle()."""

    reply_to_bot: bool = False
    reply_to_is_image: bool = False
    reply_to_is_article: bool = False
    has_question: bool = False
    bot_replied_recently: bool = False
    expects_tool_result: bool = False
    is_private: bool = False
    addressed: bool = True
    trigger_type: str = TRIGGER_FREE_WILL
    force_reply_required: bool = False


@dataclass
class DecisionToggles:
    """3 тумблера §48 (per-chat override→global→default)."""

    ignore_trivial: bool = True
    reactions: bool = True
    image_reactions: bool = True

# R17-safe коды намерения (не сырой текст запроса).
INTENT_IMAGE = "image"
INTENT_NOSTALGIA = "nostalgia"
INTENT_FORWARD = "forward"
INTENT_QUESTION = "question"
INTENT_CHAT = "chat"

# R17-safe коды адресата (роль, не имя).
ADDRESSEE_AUTHOR = "author"
ADDRESSEE_FORWARD = "forward"
ADDRESSEE_REPLY = "reply"
ADDRESSEE_UNKNOWN = "unknown"

# Оценка результатов инструментов (R17-safe код).
EVAL_NONE = "none"
EVAL_OK = "ok"
EVAL_PARTIAL = "partial"
EVAL_FAILED = "failed"
EVAL_DEGRADED = "degraded"

# Инструменты памяти — программная классификация «необходимость памяти».
_MEMORY_TOOLS = frozenset(
    {"query_chat_memory", "dig_into_lore", "get_recent_history"})


@dataclass
class CoordinatorDecision:
    """Внутренний объект решения Координатора (ADR-1026-14 D2).

    НЕ сериализуется в Stage-1/Stage-2 JSON (wire-`action` не вводится —
    граница A7). ``action`` — пред-текстовое решение (``tool``/``reply``);
    ``style`` — режим-стиль (``response_mode``), заполняется после Stage-1.
    """

    intent: str
    addressee: str
    memory_need: bool
    tool_calls: tuple
    evaluation: str
    action: str
    style: str = ""
    enabled: bool = True
    # A7 (ADR-1026-20 D1): аддитивные поля контракта решения. `action` — не
    # tool; `style=silent` недопустим (нормализуется ниже).
    target_message_id: int | None = None
    reaction: str | None = None
    reason_code: str = REASON_DEFAULT
    needs_tools: bool = False

    def __post_init__(self) -> None:
        # Инварианты 1/2 (ADR D1/§39): action ∈ {reply,react,silent,tool};
        # `style=silent` невозможен; реакция — только при action=react.
        if self.action not in COORDINATOR_ACTIONS:
            self.action = ACTION_REPLY
        if self.style == "silent":
            self.style = ""
        if self.action != ACTION_REACT:
            self.reaction = None
        if self.reason_code not in REASON_CODES:
            self.reason_code = REASON_DEFAULT


def coordinator_enabled() -> bool:
    """Kill-switch Координатора (env-only ClassVar, default ON; D6/D7).

    Резолв per-call (не кэшируется): OFF → точный legacy-путь. Никогда не
    бросает (R3)."""
    return bool(getattr(settings, "DIRECT_COORDINATOR_ENABLED", True))


def decision_making_enabled() -> bool:
    """Kill-switch A7 `DIRECT_DECISION_MAKING_ENABLED` (env-only, default ON).

    Резолв per-call; OFF → точный A1-baseline (политика §42–§45 не строится;
    `action` ∈ {tool,reply}). Никогда не бросает (R3)."""
    return bool(getattr(settings, "DIRECT_DECISION_MAKING_ENABLED", True))


def _coordinator_intent(query: str, *, image_fired: bool, dig_fired: bool,
                        forward: bool) -> str:
    """Намерение — программно (существующие маркеры пре-гейтов), без LLM."""
    if image_fired:
        return INTENT_IMAGE
    if dig_fired:
        return INTENT_NOSTALGIA
    if forward:
        return INTENT_FORWARD
    text = str(query or "").strip()
    if text.endswith("?"):
        return INTENT_QUESTION
    return INTENT_CHAT


def _coordinator_addressee(message, *, forward: bool, has_author: bool) -> str:
    """Адресат — существующий программный резолв (роль, R17-safe)."""
    if forward:
        return ADDRESSEE_FORWARD
    reply = getattr(message, "reply_to_message", None)
    if reply is not None and getattr(reply, "from_user", None) is not None:
        return ADDRESSEE_REPLY
    if has_author:
        return ADDRESSEE_AUTHOR
    return ADDRESSEE_UNKNOWN


def _coordinator_tool_names(tool_trace) -> tuple:
    """Имена фактически вызванных инструментов (модельный выбор) — порядок
    сохранён, дубликаты убраны; R17-safe (имена — коды канона)."""
    seen: list[str] = []
    for entry in tool_trace or []:
        name = str(entry.get("tool") or "").strip()
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _coordinator_evaluate(tool_trace, degraded: bool) -> str:
    """Оценка результатов инструментов — программно, без LLM."""
    if degraded:
        return EVAL_DEGRADED
    trace = list(tool_trace or [])
    if not trace:
        return EVAL_NONE
    ok = sum(1 for entry in trace if entry.get("ok"))
    if ok == len(trace):
        return EVAL_OK
    if ok == 0:
        return EVAL_FAILED
    return EVAL_PARTIAL


def _coordinator_choose_action(*, has_tools: bool, degraded: bool,
                               lore_compiled: bool) -> str:
    """Пред-текстовое решение о действии (до генерации итогового текста).

    Зеркалит существующий гейт Stage-2 (`direct_chat_service.py:814–818`):
    ``tool`` ⇔ есть реально вызванные инструменты, финал не деградировал и не
    ``lore_compiled``. Иначе — ``reply``. Поведенчески-сохраняюще: гейт
    Вербализатора не меняется (политика молчания/реакций — A8)."""
    if lore_compiled:
        return ACTION_REPLY
    if has_tools and not degraded:
        return ACTION_TOOL
    return ACTION_REPLY


def _coordinator_memory_need(tool_names, *, dig_fired: bool,
                             lore_compiled: bool) -> bool:
    """Необходимость памяти — по существующим контурам (RAG/память/инстру-
    менты памяти), без LLM."""
    if dig_fired or lore_compiled:
        return True
    return bool(set(tool_names) & _MEMORY_TOOLS)


def _coordinator_reason(*, action: str, tool_names: tuple, evaluation: str,
                        degraded: bool, lore_compiled: bool,
                        pre_reason: str) -> str:
    """R17-safe причина итогового действия Фазы T (D9)."""
    if action == ACTION_TOOL:
        # Провал инструмента при ожидании результата → честная ошибка (§43);
        # итоговый текст даёт существующий Stage-2 (не молчание).
        return (REASON_TOOL_UNAVAILABLE if evaluation == EVAL_FAILED
                else REASON_TOOL_RESULT)
    if tool_names and (degraded or evaluation == EVAL_FAILED):
        return REASON_TOOL_UNAVAILABLE
    if lore_compiled:
        return REASON_TOOL_RESULT
    return pre_reason or REASON_DEFAULT


def build_coordinator_decision(*, query: str, message, raw, user_id,
                               image_fired: bool, dig_fired: bool,
                               lore_compiled: bool,
                               pre_reason: str = REASON_DEFAULT,
                               pre_reaction: str | None = None,
                               target_message_id: int | None = None
                               ) -> CoordinatorDecision:
    """Собрать внутреннее решение Координатора (0 LLM). Никогда не бросает."""
    forward = bool(_forward_source_of(message))
    tool_trace = getattr(raw, "tool_trace", None) or []
    tool_names = _coordinator_tool_names(tool_trace)
    degraded = bool(getattr(raw, "degraded", False))
    evaluation = _coordinator_evaluate(tool_trace, degraded)
    action = _coordinator_choose_action(
        has_tools=bool(tool_trace), degraded=degraded,
        lore_compiled=lore_compiled)
    return CoordinatorDecision(
        intent=_coordinator_intent(query, image_fired=image_fired,
                                   dig_fired=dig_fired, forward=forward),
        addressee=_coordinator_addressee(message, forward=forward,
                                         has_author=bool(user_id)),
        memory_need=_coordinator_memory_need(
            tool_names, dig_fired=dig_fired, lore_compiled=lore_compiled),
        tool_calls=tool_names,
        evaluation=evaluation,
        action=action,
        target_message_id=target_message_id,
        reaction=pre_reaction if action == ACTION_REACT else None,
        reason_code=_coordinator_reason(
            action=action, tool_names=tool_names, evaluation=evaluation,
            degraded=degraded, lore_compiled=lore_compiled,
            pre_reason=pre_reason),
        needs_tools=bool(tool_names),
    )


def _decision_message_class(text: str) -> str:
    """Программная классификация сообщения (§3.3), без LLM/случайности."""
    raw = str(text or "").strip()
    if not raw:
        return MSG_OTHER
    low = raw.lower().strip(_ACK_STRIP)
    if low in _ACK_WORDS:
        return MSG_ACK
    # A7 (F-3): «?»/«???»/«?!» — короткий реальный вопрос, не эмодзи (§42).
    if _QUESTION_PUNCT_RE.match(raw):
        return MSG_QUESTION
    # A7 (F-3): «...»/«..» — не эмодзи-реакция; fail-safe → other.
    if _ELLIPSIS_ONLY_RE.match(raw):
        return MSG_OTHER
    if _EMOJI_ONLY_RE.match(raw):
        return MSG_EMOJI
    if _LAUGH_RE.search(raw):
        return MSG_LAUGHTER
    if raw.endswith("?"):
        return MSG_QUESTION
    if any(marker in low for marker in _EXPLICIT_MARKERS):
        return MSG_EXPLICIT
    first = low.split(" ", 1)[0]
    if any(low.startswith(word) for word in _QUESTION_STARTS) or \
            first in _QUESTION_STARTS:
        return MSG_QUESTION
    return MSG_OTHER


def _decision_pre_action(*, message_class: str, context: DecisionContext,
                         toggles: DecisionToggles, target_message_id=None,
                         image_pre_gate_fired: bool = False,
                         dig_pre_gate_fired: bool = False
                         ) -> tuple[str, str, str | None, int | None]:
    """Фаза P (§3.3): (action, reason_code, reaction, target_message_id).

    Детерминированный приоритет: реальные задачи (explicit/question) всегда
    перевешивают; без случайности; fail-safe → ``reply``."""
    try:
        # (3) пре-гейт (image/dig) уже отправил результат — не глушим.
        if image_pre_gate_fired or dig_pre_gate_fired:
            return ACTION_REPLY, REASON_TOOL_RESULT, None, target_message_id
        # (1) явные содержательные обращения / (2) вопросы.
        if message_class == MSG_EXPLICIT:
            return ACTION_REPLY, REASON_EXPLICIT_REQUEST, None, target_message_id
        if message_class == MSG_QUESTION or context.has_question:
            return ACTION_REPLY, REASON_QUESTION, None, target_message_id
        # (4) ожидается результат инструмента / ответ на статью-результат —
        # отвечаем итогом (не глушим и не уходим в «эмоциональную» реакцию).
        # F-2: поля §47 теперь реально прочитываются политикой.
        if context.expects_tool_result or (
                context.reply_to_bot and context.reply_to_is_article):
            return ACTION_REPLY, REASON_TOOL_RESULT, None, target_message_id
        # (5/6) эмоциональные короткие — реакция (не универсальный исход).
        if message_class in (MSG_LAUGHTER, MSG_EMOJI):
            if context.reply_to_bot and context.reply_to_is_image:
                if toggles.image_reactions:
                    reason = (REASON_IMAGE_REACTION
                              if message_class == MSG_LAUGHTER
                              else REASON_EMOJI_REACTION)
                    return (ACTION_REACT, reason, _reaction_for_reason(reason),
                            target_message_id)
                # IMAGE_REACTIONS OFF → существующий текстовый путь.
                return ACTION_REPLY, REASON_DEFAULT, None, target_message_id
            if toggles.reactions:
                reason = (REASON_LAUGHTER if message_class == MSG_LAUGHTER
                          else REASON_EMOJI_REACTION)
                return (ACTION_REACT, reason, _reaction_for_reason(reason),
                        target_message_id)
            return ACTION_REPLY, REASON_DEFAULT, None, target_message_id
        # (7) подтверждения (§42).
        if message_class == MSG_ACK:
            if toggles.ignore_trivial:
                return (ACTION_SILENT, REASON_ACKNOWLEDGEMENT, None,
                        target_message_id)
            if toggles.reactions:
                return (ACTION_REACT, REASON_EMOTION,
                        _reaction_for_reason(REASON_EMOTION),
                        target_message_id)
            return ACTION_REPLY, REASON_DEFAULT, None, target_message_id
        # (8) не адресовано боту (§45). F-2: в ЛС (private) любое сообщение
        # адресовано боту — «не адресовано» применимо только в групповом
        # контексте, поэтому там ветку молчания не включаем.
        if not context.addressed and not context.is_private:
            if toggles.ignore_trivial:
                reason = (REASON_RECENT_REPLY if context.bot_replied_recently
                          else REASON_NOT_ADDRESSED)
                return ACTION_SILENT, reason, None, target_message_id
            if toggles.reactions:
                return (ACTION_REACT, REASON_EMOTION,
                        _reaction_for_reason(REASON_EMOTION),
                        target_message_id)
            return ACTION_REPLY, REASON_DEFAULT, None, target_message_id
        # (9) бот недавно ответил, продолжение не нужно (reply-ветка §45).
        if context.bot_replied_recently and toggles.ignore_trivial:
            return ACTION_SILENT, REASON_RECENT_REPLY, None, target_message_id
        # (10) иначе — ответ.
        return ACTION_REPLY, REASON_DEFAULT, None, target_message_id
    except Exception:      # fail-safe: никогда не ложное молчание
        logger.warning("[decision] policy error — reply", exc_info=True)
        return ACTION_REPLY, REASON_ERROR, None, target_message_id


def _log_coordinator_decision(decision: CoordinatorDecision, *,
                              chat_id: int,
                              with_decision_fields: bool = False) -> None:
    """R17-safe событие решения (числа/коды/имена инструментов).

    ``with_decision_fields`` (A7) добавляет ``reason_code``/``target_id``/
    ``needs_tools``/``reaction``; OFF → строка байт-в-байт как A1."""
    if not with_decision_fields:
        logger.info(
            "[coordinator] decision | chat=%s | intent=%s | addressee=%s | "
            "memory=%d | tools=%s | eval=%s | action=%s",
            chat_id, decision.intent, decision.addressee,
            1 if decision.memory_need else 0,
            ",".join(decision.tool_calls) or "-",
            decision.evaluation, decision.action)
        return
    logger.info(
        "[coordinator] decision | chat=%s | intent=%s | addressee=%s | "
        "memory=%d | tools=%s | eval=%s | action=%s | reason=%s | target=%s | "
        "needs_tools=%d | reaction=%s",
        chat_id, decision.intent, decision.addressee,
        1 if decision.memory_need else 0,
        ",".join(decision.tool_calls) or "-",
        decision.evaluation, decision.action, decision.reason_code,
        decision.target_message_id if decision.target_message_id is not None
        else "-",
        1 if decision.needs_tools else 0, decision.reaction or "-")


def _log_coordinator_outcome(*, chat_id: int, action: str, style: str,
                             chars: int) -> None:
    """R17-safe исход (код действия / режим-стиль / длина текста)."""
    logger.info(
        "[coordinator] outcome | chat=%s | action=%s | style=%s | chars=%d",
        chat_id, action, style or "-", int(chars))


def _log_decision_short_circuit(*, chat_id: int, action: str, reason_code: str,
                                target_id: int | None,
                                reaction: str | None = None) -> None:
    """R17-safe лог Фазы P (silent/react): только id/enum (§3.9)."""
    logger.info(
        "[decision] action | chat=%s | action=%s | reason=%s | target=%s | "
        "reaction=%s",
        chat_id, action, reason_code,
        target_id if target_id is not None else "-", reaction or "-")


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
                 chat_lore_cache=None, concurrency_pool=None) -> None:
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
        # Раунд N (T-839/T-840): per-chat пул семафоров генерации — замена
        # R60-2-лока (T-461). Синглтон по умолчанию (общий с summary/
        # хендлерами smart module); DI для тестов. N — limits.
        # smartmodule_concurrency_per_chat (1 = строгая очередь как раньше).
        self._concurrency = (concurrency_pool if concurrency_pool is not None
                             else get_smartmodule_concurrency_pool())
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

    # ── A7 Decision Making (round 10.26, ADR-1026-20 D3/D6/D8) ──

    def _decision_addressed(self, message, query: str, reply,
                            reply_to_bot: bool,
                            is_private: bool = False) -> bool:
        """Адресовано ли сообщение боту (§45). Консервативно: при
        отсутствии явного встречного сигнала — ``True`` (handle вызывается
        только после trigger-гейта; ложное молчание недопустимо). F-2:
        в ЛС (``private``) сообщение всегда адресовано боту."""
        if reply_to_bot or is_private:
            return True
        text = str(query or "")
        if self.bot_username and ("@" + self.bot_username) in text.lower():
            return True
        if _BOTWORD_RE.search(text):
            return True
        if reply is None:
            return True
        reply_from = getattr(reply, "from_user", None)
        rid = getattr(reply_from, "id", None) if reply_from is not None else None
        if (isinstance(rid, int) and self.bot_id is not None
                and rid != self.bot_id):
            return False          # явный ответ другому пользователю
        return True

    async def _bot_replied_recently(self, chat_id: int) -> bool:
        """ASAP-3 (ADR-1028-2 D8, §23): НЕЗАВИСИМЫЙ признак «бот недавно
        отвечал» — окно `CHAT_BOT_REPLIED_RECENTLY_SECONDS` (env, default 600)
        по bot_replies (`last_used_at` — время доступа, консервативная
        аппроксимация conversational-сигнала). Больше НЕ приравнивается к
        reply_to_bot. Влияет на автономную SILENT-ветку (reason=recent_reply),
        не отменяет force. Fail-open → False."""
        window_s = bot_replied_recently_window_seconds()
        if window_s <= 0:
            return False
        try:
            cursor = await self.db.db.execute(
                "SELECT 1 FROM bot_replies WHERE chat_id = ? "
                "AND last_used_at > ? LIMIT 1",
                (chat_id, time.time() - window_s))
            return await cursor.fetchone() is not None
        except Exception:
            logger.debug("[decision] bot_replied_recently read failed",
                         exc_info=True)
            return False

    async def _decision_context(self, chat_id: int, message,
                                query: str) -> DecisionContext:
        """Контекст §47 из существующих источников (без нового хранилища).
        Fail-open → консервативный контекст (addressed=True → reply)."""
        try:
            reply = getattr(message, "reply_to_message", None)
            reply_to_bot = False
            if reply is not None:
                reply_from = getattr(reply, "from_user", None)
                rid = (getattr(reply_from, "id", None)
                       if reply_from is not None else None)
                if (isinstance(rid, int) and self.bot_id is not None
                        and rid == self.bot_id):
                    reply_to_bot = True
            reply_media = (message_media_type(reply)
                           if reply is not None else None)
            reply_is_image = reply_media == "photo"
            reply_is_article = bool(getattr(reply, "web_page", None)) \
                if reply is not None else False
            is_private = (getattr(getattr(message, "chat", None), "type", None)
                          == "private")
            # F-2 / §47(6): «ожидается результат инструмента». Pre-LLM (до
            # tool_trace) — эвристика по replied-сообщению бота-результата:
            # статья (fetch_article) или не-фото медиа (document/video/…).
            # Фото ведёт отдельная image-ветка (5/6), поэтому в expects не
            # входит. Только для ответа на сообщение бота.
            expects_tool_result = bool(
                reply_to_bot and (reply_is_article
                                  or reply_media not in (None, "photo")))
            return DecisionContext(
                reply_to_bot=reply_to_bot,
                reply_to_is_image=reply_is_image,
                reply_to_is_article=reply_is_article,
                has_question=_decision_message_class(query) == MSG_QUESTION,
                # ASAP-3 (фикс §23): независимый временной сигнал (окно
                # CHAT_BOT_REPLIED_RECENTLY_SECONDS), НЕ `= reply_to_bot`.
                bot_replied_recently=await self._bot_replied_recently(
                    chat_id),
                expects_tool_result=expects_tool_result,
                is_private=is_private,
                addressed=self._decision_addressed(
                    message, query, reply, reply_to_bot,
                    is_private=is_private),
            )
        except Exception:
            logger.warning("[decision] context error — conservative reply",
                           exc_info=True)
            return DecisionContext(addressed=True)

    async def _silent_ack_enabled(self, chat_id: int) -> bool:
        """ASAP-3 (D10): env `DIRECT_SILENT_ACK_ENABLED` AND per-chat
        `flags.chat_silent_ack_enabled` (env-дефолт от env-флага; hot-key).
        OFF → тишина без 🗿 (паритет baseline). Fail-open → False."""
        if not silent_ack_enabled():
            return False
        try:
            from services.chat_params import get_chat_param as _cpg
            value = await _cpg(
                chat_id, "flags.chat_silent_ack_enabled",
                hot.get("flags.chat_silent_ack_enabled",
                        silent_ack_enabled()))
            return bool(value)
        except Exception:
            logger.warning("[decision] silent-ack toggle error — off",
                           exc_info=True)
            return False

    async def _autonomous_reply_enabled(self, chat_id: int) -> bool:
        """ASAP-3 (D10): per-chat `flags.chat_autonomous_reply_enabled`
        (default ON). False → reply-to-bot этого чата всегда текстовый ответ
        (decision-матрица не применяется). Fail-open → env-дефолт."""
        try:
            from services.chat_params import get_chat_param as _cpg
            value = await _cpg(
                chat_id, "flags.chat_autonomous_reply_enabled",
                hot.get("flags.chat_autonomous_reply_enabled",
                        autonomous_reply_enabled()))
            return bool(value)
        except Exception:
            return autonomous_reply_enabled()

    async def _decision_toggles(self, chat_id: int) -> DecisionToggles:
        """3 тумблера §48: per-chat override→global→default (fail-open)."""
        try:
            from services.chat_params import get_chat_param as _cpg
            ignore = await _cpg(
                chat_id, "flags.chat_decision_ignore_trivial_enabled",
                hot.get("flags.chat_decision_ignore_trivial_enabled",
                        settings.CHAT_DECISION_IGNORE_TRIVIAL_ENABLED))
            reactions = await _cpg(
                chat_id, "flags.chat_decision_reactions_enabled",
                hot.get("flags.chat_decision_reactions_enabled",
                        settings.CHAT_DECISION_REACTIONS_ENABLED))
            image_reactions = await _cpg(
                chat_id, "flags.chat_decision_image_reactions_enabled",
                hot.get("flags.chat_decision_image_reactions_enabled",
                        settings.CHAT_DECISION_IMAGE_REACTIONS_ENABLED))
            return DecisionToggles(bool(ignore), bool(reactions),
                                   bool(image_reactions))
        except Exception:
            logger.warning("[decision] toggles error — defaults", exc_info=True)
            return DecisionToggles()

    # ── Поток хендлера (58.4) ─────────────────────────────────

    async def handle(self, bot, message, user) -> None:
        """Триггер уже проверен хендлером. Кулдаун → фраза R50-7; иначе —
        контекст → LLM → Reply → memorize (fire-and-forget, ПОСЛЕ отправки).
        Epic 60 (63.2): генерация — под per-chat замком (после throttle/CB)."""
        chat_id = message.chat.id
        user_id = user.id if user is not None else 0
        target_name = self._resolve_name(user)
        query = (message.text or "").strip()
        # F7 (ADR-1023-7 D4): ОДИН сквозной id на ответ пользователя —
        # связывает Stage-1 → tool-раунды → Stage-2 в дерево дашборда.
        correlation_id = usage_events.new_correlation_id()
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
        # Epic 60 (63.2, T-461) — раунд N (T-840): слот пула ПОСЛЕ
        # throttle/CB-веток (мгновенные, не стоят в очереди); таймаут
        # ожидания → CHAT_LOCK_BUSY_PHRASES. Текст лога сохранён
        # («lock wait timeout») — грепается тестами/мониторингом.
        permit = await self._concurrency.try_acquire(
            chat_id,
            timeout=hot.get("limits.chat_lock_wait_seconds",
                            settings.CHAT_LOCK_WAIT_SECONDS))
        if permit is None:
            logger.warning("direct: lock wait timeout | chat=%s user=%s",
                           chat_id, target_name)
            await _reply(bot, chat_id, random.choice(CHAT_LOCK_BUSY_PHRASES),
                         message.message_id)
            return
        answer_text: str | None = None
        dedup_key = None
        try:
            # Epic 60 (67.4, T-499): дедуп одинаковых текстов подряд (п.8) —
            # ПОСЛЕ throttle/CB/замка (D237: троттлинг остаётся первым
            # барьером), ПЕРЕД сборкой контекста. Ключ «чат+человек+текст»;
            # payload — сохранённый ответ → повторная отправка; "" — прошлый
            # раз без ответа → молчание; None (первый раз/TTL истёк) — обычный
            # поток. Внутри try/finally: ранний return обязан отпустить замок.
            # MCA-07 (T-3851, ADR-1027-7 D9): при `MCA_CONTEXT_ANSWER_CACHE_
            # ENABLED` ON прежний text-replay по одному нормализованному
            # query/chat/user для контекстных ответов ОТКЛЮЧЁН (дедуп одного
            # Telegram update по (chat_id, tg_message_id) — отдельный механизм
            # идентичности mca-03, сохраняется). OFF → прежний ответный кеш.
            answer_cache_policy_on = mca_gates.context_answer_cache_enabled()
            if answer_cache_policy_on and not _answer_cache_disabled_notified():
                # L-MCA07-4: отдельная стадия `answer_cache` (не `summary`).
                _mca_rc.emit_stage_event("answer_cache", "skipped",
                                         reason_code="answer_cache_disabled")
            if self._cache is not None and _legacy_text_replay_enabled() and hot.get(
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
            # MCA-07 (T-3852): исключённые бюджетом блоки → EvidenceBundle.
            _excluded_blocks: list = []
            user_blocks = await self._build_user_content(
                chat_id, message, target_name,
                target_user_id=(user_id or None),
                out_excluded=_excluded_blocks)
            # Раунд 9 (T-821/C2(6), фикс-раунд major-1, spec §3.2.3): пре-гейт
            # маркеров ностальгии — принудительный dig ДО генерации, результат
            # в <dig_result> ПЕРЕД <Target_User> (флаг off/нет маркера/нет
            # роутера → ничего; раунды TOOL_MAX_ROUNDS не тратятся).
            dig_fired = False
            if self.tool_router is not None:
                dig_block = await self._dig_pre_gate_block(chat_id, query)
                if dig_block:
                    dig_fired = True
                    user_blocks = self._insert_dig_result(user_blocks,
                                                          dig_block)
            # Раунд 10.23 (F5, ADR-1023-5 §D2): пре-гейт ключевиков генерации
            # изображений («Бот, нарисуй …») — генерация и отправка ДО Stage-1,
            # блок <image_result> для инъекции. НЕ зависит от tool_router
            # (spec §2.2: условие — только «модуль ON»); review iter1 Finding 4.
            image_block = await self._image_pre_gate_block(
                chat_id, query, bot, message, user_id,
                correlation_id=correlation_id)
            image_pre_gate_fired = bool(image_block)
            if image_block:
                user_blocks = self._insert_dig_result(user_blocks, image_block)
            # A7 (round 10.26, ADR-1026-20 D2/D3/D4): Фаза P — программное
            # решение о действии ДО генерации текста (0 LLM-вызовов).
            # `silent`/`react` — короткое замыкание; `reply` — существующий
            # путь. OFF kill-switch → точный A1-baseline (политика не
            # строится). Реальные задачи (explicit/question) никогда не
            # глушатся (§43).
            pre_action = ACTION_REPLY
            decision_on = decision_making_enabled()
            # A9 (ADR-1026-22 D5/D6): DECISION_START — вход Фазы P (0 LLM).
            _p_started = time.monotonic()
            _trigger_id = getattr(message, "message_id", None)
            emit_agentic_event(
                "DECISION_START", run_id=correlation_id, chat_id=chat_id,
                message_id=_trigger_id)
            # ── ASAP-3 (ADR-1028-2 D8, §30): trigger-резолв матрицы §4.1 ──
            # (гейт хендлера уже состоялся); DIRECT_TRIGGER — R17-safe
            # (trigger_type/флаги, без raw text).
            _reply_obj = getattr(message, "reply_to_message", None)
            _reply_bot = False
            if _reply_obj is not None:
                _reply_from = getattr(_reply_obj, "from_user", None)
                _rid = (getattr(_reply_from, "id", None)
                        if _reply_from is not None else None)
                _reply_bot = (isinstance(_rid, int)
                              and self.bot_id is not None
                              and _rid == self.bot_id)
            _trigger_type, _force_required = _resolve_direct_trigger(
                query, reply_to_bot=_reply_bot,
                bot_username=self.bot_username,
                persona_name_check=command_prefix.name_mentioned)
            _is_private = (getattr(getattr(message, "chat", None), "type",
                                   None) == "private")
            _composer.emit_direct_trigger(
                chat_id=chat_id, message_id=_trigger_id,
                trigger_type=_trigger_type,
                force_reply_required=_force_required,
                reply_to_bot=_reply_bot, is_private=_is_private,
                addressed=True)
            # F-5 / §3.3 (строка 0): OFF kill-switch → политика не строится,
            # но причина решения фиксируется как `disabled` (диагностический
            # контракт). Наблюдаемый формат A1-лога сохраняется байт-в-байт.
            pre_reason = REASON_DEFAULT if decision_on else REASON_DISABLED
            pre_reaction = None
            pre_target = None
            _dctx = None
            if decision_on:
                _dctx = await self._decision_context(chat_id, message, query)
                # Аддитивные поля адресации (контракт A7 — только расширение).
                _dctx.trigger_type = _trigger_type
                _dctx.force_reply_required = _force_required
                _toggles = await self._decision_toggles(chat_id)
                if _force_required:
                    # ── Приоритет 1 (§19A/§21, T-4019): FORCE DIRECT —
                    # гарантированный ACTION_REPLY; шорт-каты ignore_trivial/
                    # recent_reply/low_information НЕ применяются (гейт до
                    # них и до LLM). Decision Maker влияет только на
                    # стиль/длину (технические ветки ниже — единственные
                    # исключения).
                    pre_action = ACTION_REPLY
                    pre_reason = REASON_FORCE_DIRECT
                    _composer.record_direct_metric("direct_force_reply_total")
                elif _reply_bot and not await self._autonomous_reply_enabled(
                        chat_id):
                    # Per-chat `flags.chat_autonomous_reply_enabled=false`:
                    # decision-матрица не применяется → текстовый ответ.
                    pre_action = ACTION_REPLY
                    pre_reason = REASON_DEFAULT
                    _composer.record_direct_metric("direct_force_reply_total")
                else:
                    pre_action, pre_reason, pre_reaction, pre_target = \
                        _decision_pre_action(
                            message_class=_decision_message_class(query),
                            context=_dctx, toggles=_toggles,
                            target_message_id=getattr(message, "message_id",
                                                      None),
                            image_pre_gate_fired=image_pre_gate_fired,
                            dig_pre_gate_fired=dig_fired)
                    if pre_action == ACTION_REACT:
                        _composer.record_direct_metric(
                            "direct_autonomous_react_total")
                # A9 (D5/D6): DECISION_COMPLETE — уже принятое решение
                # (A9 только наблюдает; политика A7 не дублируется). ASAP-3:
                # аддитивные поля trigger_type/force_reply_required/
                # message_class (контракт §31).
                emit_agentic_event(
                    "DECISION_COMPLETE", run_id=correlation_id, chat_id=chat_id,
                    message_id=_trigger_id, action=pre_action,
                    reason=pre_reason,
                    trigger_type=_trigger_type,
                    force_reply_required=_force_required,
                    message_class=_decision_message_class(query),
                    duration_ms=int((time.monotonic() - _p_started) * 1000))
                if pre_action == ACTION_SILENT:
                    _log_decision_short_circuit(
                        chat_id=chat_id, action=ACTION_SILENT,
                        reason_code=pre_reason, target_id=pre_target)
                    # A9 (D6): silent-short-circuit → MESSAGE_IGNORED.
                    emit_agentic_event(
                        "MESSAGE_IGNORED", run_id=correlation_id,
                        chat_id=chat_id, message_id=_trigger_id,
                        action=ACTION_SILENT, reason=pre_reason,
                        target=pre_target)
                    # ── ASAP-3 (ADR-1028-2 D9, §25–§28, T-4023): SILENT+🗿 —
                    # строго конъюнкция: trigger direct-autonomous
                    # (reply_to_bot) ∧ addressed ∧ decision executed ∧ финал
                    # SILENT + гейты (env + per-chat). Запрещён на фоне/
                    # not_addressed/тех-ветках (те до decision не доходят).
                    if _reply_bot and _dctx is not None and _dctx.addressed \
                            and await self._silent_ack_enabled(chat_id):
                        _composer.record_direct_metric(
                            "direct_autonomous_silent_total")
                        _ack_outcome = await react_moai(
                            bot, chat_id, _trigger_id,
                            reaction=REACTION_MOAI,
                            reason_code=pre_reason)
                        if _ack_outcome == "ok":
                            _composer.record_direct_metric(
                                "direct_silent_ack_success_total")
                            _composer.emit_direct_silent_ack(
                                chat_id=chat_id, target_message_id=_trigger_id,
                                success=True, reason_code=pre_reason)
                        else:
                            # §28 fail-soft: SILENT остаётся SILENT, отказ
                            # логируется, текст НЕ генерируется.
                            _composer.record_direct_metric(
                                "direct_silent_ack_failed_total")
                            _composer.emit_direct_silent_ack_failed(
                                chat_id=chat_id,
                                target_message_id=_trigger_id,
                                error_code=_ack_outcome,
                                reason_code=pre_reason)
                            logger.warning(
                                "[direct] silent ack failed | chat=%s "
                                "target=%s outcome=%s reason=%s",
                                chat_id, _trigger_id, _ack_outcome,
                                pre_reason)
                    return
                if pre_action == ACTION_REACT:
                    _log_decision_short_circuit(
                        chat_id=chat_id, action=ACTION_REACT,
                        reason_code=pre_reason, target_id=pre_target,
                        reaction=pre_reaction)
                    _reaction_outcome = await react_moai(
                        bot, chat_id, pre_target,
                        reaction=pre_reaction,
                        reason_code=pre_reason)
                    # A9 (D5): REACTION_SENT — после outcome A8 (7-enum).
                    emit_agentic_event(
                        "REACTION_SENT", run_id=correlation_id,
                        chat_id=chat_id, message_id=pre_target,
                        outcome=_reaction_outcome, reaction=pre_reaction,
                        reason=pre_reason)
                    return
                # Autonomous REPLY (матрица выбрала текстовый исход).
                if _reply_bot and not _force_required:
                    _composer.record_direct_metric(
                        "direct_autonomous_reply_total")
            # MCA-07 (T-3852, ADR-1027-7 D5/D6/SC-09/SC-10): ЕДИНЫЙ
            # EvidenceBundle собирается один раз ПОСЛЕ решения (решение
            # вкладывается в `chosen_intent`) и проходит decision → tools →
            # synthesis(System2) → формулировку. Ссылается на канонические
            # ID-ссылки, архив не дублируется; gate OFF → None (паритет).
            evidence_bundle = await self._build_evidence_bundle(
                chat_id, message, query, target_name, user_id, user_blocks,
                excluded=_excluded_blocks, chosen_intent=pre_action)
            # T-619: системный промпт — горячая точка (фолбек код-канона).
            # Раунд 10 (F-7 §4.5): per-chat override (chat_params → глобал →
            # канон) — «Использовать мой» локального админа работает ТОЛЬКО
            # в его чате; fail-open: PG down → глобальный.
            from services.chat_params import get_chat_param as _cpg
            system_prompt = await _cpg(
                chat_id, "prompts.direct_chat_system_prompt",
                hot.get("prompts.direct_chat_system_prompt",
                        CHAT_SYSTEM_PROMPT))
            # Раунд 10.14 (F2 persona-storage-core, spec §3.2): persona-блок —
            # ХВОСТ системного промпта (system_prompt + "\n\n" + block).
            # Пусто/PG down/флаг OFF → промпт байт-в-байт прежний (F2-Q5).
            # H3-фикс: гейт резолвится per-chat (override → global → default).
            persona_enabled = await _cpg(
                chat_id, "flags.persona_enabled",
                hot.get("flags.persona_enabled", settings.PERSONA_ENABLED))
            if persona_enabled:
                persona = await bot_persona.resolve_bot_persona(chat_id)
                traits = await bot_persona.get_traits(
                    int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50))
                persona_block = bot_persona.build_persona_prompt_block(
                    persona, [t.get("text") for t in traits], enabled=True)
                if persona_block:
                    system_prompt = system_prompt + "\n\n" + persona_block
            payload = build_messages(system_prompt, user_blocks,
                                     time_line=await self._chat_time_line(chat_id))
            # Epic 60 (65.8, T-476): temperature-пресет юзера (user_prefs)
            # или дефолт. Другие пайплайны — без temperature (65.8).
            temperature = settings.tone_temperature(
                await self._get_tone_preset(chat_id, user_id))
            # Epic 60 (65.7, T-475): «печатает…» вокруг LLM-точки, без паузы.
            # Эпик 04.09.2026 (3.3): при настроенном tool_router генерация идёт
            # циклом chat_with_tools (модель сама решает вызвать инструменты);
            # ошибки/пустые финалы — те же классы, ветки except ниже без правок.
            # Раунд 10.20 (БЛОК 1/О3, ADR-1020-4 п.5, T-1887/T-1892): флаг
            # «Летописца» резолвится per-chat (override → global → канон); OFF
            # → 8-й инструмент не объявляется (7 прежних — байт-в-байт).
            # ctx вынесен из вызова цикла: сигнал режима ctx.lore_compiled
            # читается ПОСЛЕ chat_with_tools (доставка HTML, ADR-1020-6 п.2).
            lore_enabled = await _cpg(
                chat_id, "flags.lore_compiler_enabled",
                hot.get("flags.lore_compiler_enabled",
                        settings.LORE_COMPILER_ENABLED))
            # Раунд 10.23 (F5, ADR-1023-5 §D2/§D5): env-рубильник AND
            # каталоговый тумблер `flags.image_generation_module_enabled`
            # (per-chat). OFF → 9-й инструмент не объявляется (8 прежних —
            # байт-в-байт).
            from services import image_generation
            image_enabled = await image_generation.resolve_module_enabled(
                chat_id)
            # Review iter1 Finding 3: если на этот ход уже сработал пре-гейт
            # ключевика, изображение сгенерировано/отправлено — на этом же
            # ходу инструмент не объявляем (один путь генерации, без двойного
            # платного вызова и двойного списания image_calls).
            if image_pre_gate_fired:
                image_enabled = False
            # Раунд 10.24 (F13→F14, T-2295): эмиссия `ToolContext.native_media` —
            # интерфейсная строка связи. Файл принадлежит F13, но F13-коммит
            # эмиссию не отдал, поэтому она влита F14 вместе с модулем
            # `services.native_media` (зафиксировано в tasks.md F14). Резолвер
            # безопасен (никогда не бросает). При OFF-флаге значение не мешает:
            # нативный резолв в `tool_router` гейтится `NATIVE_MEDIA_TOOLS_ENABLED`.
            # A2 (ADR-1026-15 D6): общий контекстный резолв ссылки — текущее
            # сообщение → reply (без новых I/O; не per-phrase). Однозначная
            # ссылка доступна `fetch_article` без повторной присылки.
            _reply_message = getattr(message, "reply_to_message", None)
            _reply_text = ""
            if _reply_message is not None:
                _reply_text = (getattr(_reply_message, "text", None)
                               or getattr(_reply_message, "caption", None) or "")
            tool_ctx = ToolContext(chat_id, query, bot=bot,
                                   reply_to_message_id=message.message_id,
                                   user_id=user_id,
                                   correlation_id=correlation_id,
                                   resolved_url=resolve_context_url(
                                       query, _reply_text),
                                   native_media=
                                   native_media_module.resolve_reply_video(
                                       message),
                                   # A3 (ADR-1026-16 D3): авторитетный маркер
                                   # прогона — пре-гейт сработал → 'generate_
                                   # image' на этом же ходу вернёт skipped
                                   # даже если модель его вызовет.
                                   image_request_handled=
                                   image_pre_gate_fired)
            # MCA-07 (T-3852): тот же единственный bundle доступен инструментам
            # (REUSE: контракт, не второй сборщик; R17 — ссылки/refs).
            tool_ctx.evidence_bundle = evidence_bundle
            try:
                async with typing_active(bot, chat_id):
                    if self.tool_router is not None:
                        raw = await chat_with_tools(
                            self.llm, payload,
                            tools=active_tools(bool(lore_enabled),
                                               bool(image_enabled)),
                            router=self.tool_router, ctx=tool_ctx,
                            temperature=temperature, chat_id=chat_id,
                            module="direct_chat",
                            correlation_id=correlation_id)
                    else:
                        raw = await self.llm.generate(
                            payload, temperature=temperature, chat_id=chat_id,
                            module="direct_chat", step="single",
                            correlation_id=correlation_id)
            except NoApiKeyForChat as exc:
                # Раунд 10 (F-7 §5.2): у чата нет своего ключа, глобальный
                # запрещён/исчерпан → sandbox-фраза content.no_key_reply
                # (LLM НЕ вызывается; тишины нет — R16).
                # F-15 (§3.1): лог объясняет ПОЧЕМУ (details-снапшот:
                # resolve_path/day/used/limit — БЕЗ секретов, R17).
                logger.warning(
                    "[direct] no key — sandbox answer | chat=%s | reason=%s "
                    "| details=%s",
                    chat_id, exc.reason,
                    repr(getattr(exc, "details", None)))
                reply_phrase = hot.get(
                    "content.no_key_reply", DEFAULT_NO_KEY_REPLY)
                await _reply(bot, chat_id, reply_phrase, message.message_id)
                return
            except LLMBadResponseError as exc:
                # Epic 60 (65.1, T-469): модель ЖИВА, но ответила пустым →
                # молчание + 🗿 (НЕ R13-фраза, НЕ заглушка). Ветка ДО
                # except LLMError — R13-эталоны байт-в-байт.
                logger.warning(
                    "[direct] empty answer — silence | chat=%s user=%s | error=%s",
                    chat_id, target_name, exc)
                await react_moai(bot, chat_id, message.message_id)
                return
            if isinstance(raw, ToolLoopResult) and raw.degraded:
                # БЛОК 7.1 (T-1919): деградация tool-цикла — ответ уже есть
                # (частичный/заглушка), но фиксируем для наблюдаемости (R17).
                logger.warning(
                    "[direct] tool-loop degraded | chat=%s | reason=%s | "
                    "rounds_used=%d", chat_id, raw.reason, raw.rounds_used)
            # A1 (round 10.26, ADR-1026-14 D1/D2): программный слой решения о
            # действии ВНУТРИ существующего Синтезатора — координатор строит
            # внутреннее решение ДО генерации итогового текста (§14 «решение о
            # действии и итоговый текст — разные задачи»). 0 LLM-вызовов;
            # wire-`action` не вводится. Kill-switch OFF → координатор не
            # строится (точный legacy-путь, без лишних логов).
            coordinator = None
            if coordinator_enabled():
                coordinator = build_coordinator_decision(
                    query=query, message=message, raw=raw, user_id=user_id,
                    image_fired=image_pre_gate_fired, dig_fired=dig_fired,
                    lore_compiled=bool(
                        getattr(tool_ctx, "lore_compiled", False)),
                    pre_reason=pre_reason, pre_reaction=pre_reaction,
                    target_message_id=getattr(message, "message_id", None))
                _log_coordinator_decision(
                    coordinator, chat_id=chat_id,
                    with_decision_fields=decision_on)
            # Раунд 10.22 (F5, ADR-1022-5): System 2 (Синтезатор тулов →
            # Вербализатор) — ТОЛЬКО при реально вызванных тулах, успешном
            # tool-финале и НЕ lore_compiled (детерминированная HTML-история
            # остаётся вне System 2, Д-9). Любой сбой → финал tool-loop.
            # A1 (D4): то же условие, выраженное через решение координатора
            # (`action == tool` ⇔ те же условия) — Вербализатор не запускается
            # при не-текстовом решении (молчание/реакция не генерируют текст).
            response_mode = "serious"      # F3: fail-safe до Stage-2
            if (getattr(settings, "SYSTEM2_DIRECT_ENABLED", True)
                    and isinstance(raw, ToolLoopResult)
                    and not raw.degraded
                    and bool(getattr(raw, "tool_trace", None))
                    and not getattr(tool_ctx, "lore_compiled", False)
                    and (coordinator is None
                         or coordinator.action == ACTION_TOOL)):
                synthesized = await self._synthesize_direct_answer(
                    chat_id, query, raw, temperature,
                    correlation_id=correlation_id,
                    bundle=evidence_bundle)
                if synthesized:
                    # F3 (ADR-1023-3): режим несёт и стиль, и канал доставки.
                    raw, response_mode = synthesized
                    if coordinator is not None:
                        coordinator.style = response_mode
            # БЛОК 7.2b (T-1921): единая стадия пост-обработки — reasoning-
            # теги-черновики не уходят пользователю (no-op без тегов).
            answer = strip_reasoning_tags(str(raw).strip())
            # БЛОК 7.2c (T-1922, ADR-1020-7 §2): при ctx.lore_compiled
            # доставляем ГОТОВЫЙ текст истории (детерминизм в коде), а не
            # сжатую диспетчерскую ремарку. Обычный путь не меняется.
            lore_story = str(getattr(tool_ctx, "lore_story", "") or "").strip()
            if getattr(tool_ctx, "lore_compiled", False) and lore_story:
                answer = strip_reasoning_tags(lore_story)
            if not answer:
                if coordinator is not None:
                    _log_coordinator_outcome(
                        chat_id=chat_id, action=ACTION_REACT,
                        style=response_mode, chars=0)
                logger.warning(
                    "[direct] empty answer — silence | chat=%s user=%s",
                    chat_id, target_name)
                await react_moai(bot, chat_id, message.message_id)
                return
            if coordinator is not None:
                _log_coordinator_outcome(
                    chat_id=chat_id, action=ACTION_REPLY,
                    style=response_mode, chars=len(answer))
            sent_id = await self._send_direct_answer(
                bot, chat_id, answer, message.message_id,
                lore=bool(getattr(tool_ctx, "lore_compiled", False)),
                deep_research=(response_mode == "deep_research"))
            if sent_id is not None:
                answer_text = answer
                # MCA-07 (T-3852, D11): `context_version`/число исключений —
                # в наблюдаемость (R17: только версия/числа, без сырья).
                if evidence_bundle is not None:
                    _mca_rc.emit_stage_event(
                        "bundle", "success", chat_id=chat_id,
                        config_version=evidence_bundle.context_version,
                        entity_ids=[evidence_bundle.context_version])
                # D3/T-800: parent = сообщение, на которое бот ответил
                await self.remember_bot_reply(
                    chat_id, sent_id, answer,
                    parent_tg_message_id=message.message_id)
                # REVISE S2: memorize ТОЛЬКО ПОСЛЕ успешной отправки (58.8) —
                # fire-and-forget внутри гейта sent_id. Раунд 8 (C6/T-797):
                # wrapper с пост-фазой «факты про третьих лиц не приписываются
                # спрашивающему» (target_user уже = канон автора запроса).
                fire_and_forget(
                    self._memorize_direct_reply(
                        chat_id, query, answer, target_name,
                        tg_message_id=getattr(message, "message_id", None),
                        forward_from=_forward_source_of(message),
                        asker_user_id=(user_id or None)),
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
            permit.release()   # раунд N (T-840): слот пула возвращён
            # Epic 60 (67.4, T-499): исход попытки — в дедуп-кэш: успешный
            # ответ → payload-ответ (повтор получит его из кэша); ЛЮБОЙ
            # неуспех (🗿-пустой/LLMError/исключение/send fail) → маркер ""
            # → повтор того же текста молчит. Заглушки в кэш НЕ пишутся.
            if dedup_key is not None and self._cache is not None:
                await self._cache.set_dedup(dedup_key, answer_text or "")

    # ── System 2 direct (F5, раунд 10.22, ADR-1022-5) ───────────

    async def _synthesize_direct_answer(self, chat_id: int, query: str,
                                        raw, temperature,
                                        correlation_id: str | None = None,
                                        bundle=None
                                        ) -> tuple[str, str] | None:
        """Синтезатор тулов → Вербализатор. ``None`` → финал tool-loop.

        Stage-1 получает ТОЛЬКО санитизированную «кашу» логов; Stage-2 —
        ONLY валидированную JSON-справку (изоляция). Любой сбой/невалидный
        JSON/пустой ответ → ``None`` (fail-safe, R17: логи без содержимого).

        Раунд 10.23 (F3, ADR-1023-3): возвращает ``(текст, response_mode)`` —
        режим нужен вызывающему, чтобы выбрать канал доставки (deep_research →
        safe-HTML «Летописца»). Роутера третьим вызовом нет: режим едет в
        том же JSON Stage-1.

        MCA-07 (T-3852, ADR-1027-7 D6/SC-09): при переданном `bundle` Stage-1
        получает scoped-срез ЕДИНОГО EvidenceBundle (адресат/ветка/ограничения/
        `context_version`) — System2 после tool loop НЕ теряет контекст и НЕ
        получает только вопрос+tool output. `bundle=None`/gate OFF → прежний
        Stage-1 (байт-в-байт, паритет).
        """
        try:
            tool_context = redact_secrets(
                str(getattr(raw, "tool_context", "") or ""))
            trace = getattr(raw, "tool_trace", []) or []
            trace_summary = ", ".join(
                f"{entry.get('tool')}:{entry.get('out_chars')}"
                for entry in trace if entry.get("tool")) or "-"
            synth_user = (
                f"СООБЩЕНИЕ ЮЗЕРА:\n{query}\n\n"
                f"ИНСТРУМЕНТЫ (сводка):\n{trace_summary}\n\n"
                f"ВЫВОДЫ ИНСТРУМЕНТОВ:\n{tool_context}"
            )
            # MCA-07 D6: scoped-срез bundle не теряется после tool loop.
            bundle_slice = _bundle_scoped_slice(bundle)
            if bundle_slice:
                synth_user = f"{bundle_slice}\n\n{synth_user}"
            synth_messages = [
                {"role": "system", "content": resolve_prompt(
                    "prompts.direct_chat_synthesizer_system_prompt",
                    DIRECT_SYNTHESIZER_SYSTEM_PROMPT)},
                {"role": "user", "content": synth_user},
            ]
            raw_synth = await self.llm.generate(
                synth_messages, temperature=temperature, chat_id=chat_id,
                module="direct_chat", step="stage1",
                correlation_id=correlation_id)
            data = parse_direct_synthesis(str(raw_synth))
            if data is None:
                logger.info(
                    "[direct] system2: невалидная справка — fallback | chat=%s",
                    chat_id)
                return None
            # Review iter1 (M1): при kill-switch OFF режим не выбирается вовсе
            # (fail-safe serious) — включая маршрут доставки.
            modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True)
            response_mode = (normalize_response_mode(data.get("response_mode"))
                             if modes_on else "serious")
            verbalizer_template = (
                resolve_prompt("prompts.direct_chat_verbalizer_system_prompt",
                               DIRECT_VERBALIZER_SYSTEM_PROMPT)
                if modes_on else PREV_CHAT_VERBALIZER_R1023)
            # Review iter1 (H2): direct deep_research доставляется safe-HTML
            # (`parse_mode="HTML"` + escape_lore_html) → HTML-capable блок.
            verbalizer_system = (compose_verbalizer_system(
                verbalizer_template, response_mode, "plain", html_safe=True)
                if modes_on else verbalizer_template)
            base_messages = [
                {"role": "system", "content": verbalizer_system},
                {"role": "user",
                 # spec F3 §3.1: служебный response_mode в Stage-2 не утекает.
                 "content": "СПРАВКА (JSON):\n" + json.dumps(
                     stage2_payload(data), ensure_ascii=False)},
            ]

            async def _generate(messages):
                return await self.llm.generate(
                    messages, temperature=temperature, chat_id=chat_id,
                    module="direct_chat", step="stage2",
                    correlation_id=correlation_id)

            enabled_rules = (channel_enabled_rules("plain", response_mode)
                             if modes_on else None)
            text, stats = await verbalize_validated(
                _generate, base_messages, max_retries=2,
                enabled_rules=enabled_rules,
                dynamic_rules=anticliche_cache.get_rules() or None)
            logger.info(
                "[direct] system2 | chat=%s | mode=%s | attempts=%d | retries=%d | "
                "hits=%d | fallback=%s", chat_id, response_mode,
                stats.get("attempts", 0), stats.get("retries", 0),
                len(stats.get("hits") or []), bool(stats.get("fallback")))
            if not text.strip():
                return None
            return text, response_mode
        except Exception as exc:                # fail-safe → финал tool-loop
            logger.info(
                "[direct] system2 failed — fallback tool-loop | chat=%s | "
                "error=%s", chat_id, type(exc).__name__)
            return None

    # ── Context Partitioning (58.6) ─────────────────────────────

    @staticmethod
    async def _send_direct_answer(bot, chat_id: int, answer: str,
                                  reply_to: int | None, *,
                                  lore: bool = False,
                                  deep_research: bool = False):
        """Доставка ответа DirectChat (раунд 10.20, T-1892, О5/ADR-1020-6 п.3).

        Обычный путь — байт-в-байт `parse_mode=None`. Под-путь safe-HTML
        (режим «Летописца» `lore` ИЛИ F3 `deep_research` прямого чата):
        ЛОКАЛЬНЫЙ ``parse_mode="HTML"``, текст экранируется по whitelist-тегов
        (`escape_lore_html`); при ``TelegramBadRequest`` (битая разметка) —
        деградация на plain-text с ИСХОДНЫМ текстом (диалог не роняется,
        история не теряется). Глобальный `parse_mode` не меняется.

        S10.20-10: HTML-ветка используется ТОЛЬКО если экранированный текст
        влезает в одно сообщение (≤4096). Иначе чанкинг по пробелам мог
        разорвать тег → `TelegramBadRequest` на 2-м чанке → фолбэк пересылал
        ВЕСЬ ответ plain (дубль). Длинный ответ уходит одной plain-доставкой
        без тегов — без дублей и без сырой разметки."""
        if not (lore or deep_research):
            return await send_chunked_reply(bot, chat_id, answer, reply_to)
        escaped = escape_lore_html(answer)
        if len(escaped) <= _LORE_HTML_MAX_SINGLE_CHARS:
            try:
                return await send_chunked_reply(
                    bot, chat_id, escaped, reply_to, parse_mode="HTML")
            except TelegramBadRequest as exc:
                logger.warning(
                    "[direct] safe-HTML send failed — plain fallback | "
                    "chat=%s | error=%s", chat_id, type(exc).__name__)
                return await send_chunked_reply(bot, chat_id, answer, reply_to)
        logger.info("[direct] text too long for safe HTML — plain | "
                    "chat=%s | chars=%d", chat_id, len(escaped))
        return await send_chunked_reply(bot, chat_id, strip_lore_html(answer),
                                        reply_to)

    async def _chat_time_line(self, chat_id: int) -> str:
        """10.20 (БЛОК 5.1, О2/О4 FINAL, ADR-1020-3): строка Time Injection
        `[Текущее время в чате: DD.MM.YYYY, HH:MM, День недели]` в таймзоне
        чата. Источник — НОВЫЙ ключ `limits.chat_timezone` (per-chat override
        → global → код-дефолт; пусто → фолбэк `limits.summary_timezone`,
        который НЕ трогаем). Вставляется ПЕРВЫМ user-блоком в `build_messages`
        (system статичен — prompt-cache не ломаем).
        """
        tz = await _cp_g(
            chat_id, "limits.chat_timezone",
            hot.get("limits.chat_timezone",
                    getattr(settings, "CHAT_TIMEZONE", "")))
        fallback = hot.get("limits.summary_timezone",
                           settings.SUMMARY_TIMEZONE)
        return format_chat_time(tz_name=tz, fallback_tz=fallback)

    async def _estimate_external_payload_tokens(
            self, chat_id: int, budget_tokens) -> tuple[int, int, str | None]:
        """MCA-07 B-MCA07-2 (REQ-MCA07-06/SC-12/A24): консервативная оценка
        НЕ-user части полного payload для живого бюджета.

        Считает: system/developer-промпт + personality-блок + tools schemas
        (JSON) — как `external_tokens`; output reserve = доля
        `CHAT_BUDGET_RESERVE_RATIO` бюджета. Возвращает `(external, reserve,
        method)`; любая ошибка → `(0, 0, None)` (fail-open → точный legacy-
        путь бюджета, паритет). Частичный сбой источника не обнуляет остальные.
        """
        external = 0
        try:
            from services.chat_params import get_chat_param as _cpg
            try:
                system_prompt = await _cpg(
                    chat_id, "prompts.direct_chat_system_prompt",
                    hot.get("prompts.direct_chat_system_prompt",
                            CHAT_SYSTEM_PROMPT))
                external += count_tokens(system_prompt)
            except Exception:
                logger.debug("[mca07] payload est: system prompt failed",
                             exc_info=True)
            try:
                persona_enabled = await _cpg(
                    chat_id, "flags.persona_enabled",
                    hot.get("flags.persona_enabled", settings.PERSONA_ENABLED))
                if persona_enabled:
                    persona = await bot_persona.resolve_bot_persona(chat_id)
                    traits = await bot_persona.get_traits(
                        int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50))
                    persona_block = bot_persona.build_persona_prompt_block(
                        persona, [t.get("text") for t in traits], enabled=True)
                    if persona_block:
                        external += count_tokens(persona_block)
            except Exception:
                logger.debug("[mca07] payload est: persona failed",
                             exc_info=True)
            try:
                lore_enabled = await _cpg(
                    chat_id, "flags.lore_compiler_enabled",
                    hot.get("flags.lore_compiler_enabled",
                            settings.LORE_COMPILER_ENABLED))
                from services import image_generation as _img
                image_enabled = await _img.resolve_module_enabled(chat_id)
                tools = active_tools(bool(lore_enabled), bool(image_enabled))
                external += count_tokens(json.dumps(tools, ensure_ascii=False))
            except Exception:
                logger.debug("[mca07] payload est: tools schemas failed",
                             exc_info=True)
            ratio = hot.get("limits.chat_budget_reserve_ratio",
                            settings.CHAT_BUDGET_RESERVE_RATIO)
            try:
                reserve = max(0, int(int(budget_tokens) * float(ratio)))
            except (TypeError, ValueError):
                reserve = 0
            if external <= 0 and reserve <= 0:
                return 0, 0, None
            return external, reserve, estimation_method()
        except Exception:
            logger.warning("[mca07] external payload estimate failed — legacy",
                           exc_info=True)
            return 0, 0, None

    async def _build_user_content(self, chat_id: int, message,
                                  target_name: str,
                                  target_user_id: int | None = None,
                                  out_excluded: list | None = None) -> list[str]:
        """Порядок сборки user-контента (Раунд 8, B2/T-791, spec §3.B2) —
        «важное к концу» (FR-22/п.24): map → branch → rag → global → thread →
        target → relations → protected → lore → mood → current → anchors →
        sandwich. Статика вверх, критичное (target/relations/protected/
        current) ближе к концу. Раунд 9 (T-819/B4, spec §3.1.4): блок
        <user_relations> (kind "relations") — СРАЗУ ПОСЛЕ ("target", …), до
        protected/lore; кап по символам — до инжекта; uncuttable (вне
        контекст-бюджета). Раунд 8 (C5/T-796): <Target_User> с uid автора
        запроса (NFR-2: скобки только в контекстных блоках direct_chat).
        Порядок регистрации роутеров/хендлеров НЕ меняется — меняется только
        эта сборка. Раунд 8 (F2/T-808): двухпроходность — <Global_Context>
        собирается РАНЬШЕ <RAG_Memory> (текст фона нужен для словарного
        дедупа RAG), контент-порядок blocks (rag → global) не меняется.
        Раунд 9 (E1/T-826, spec §3.5.1): маркер «золотых» (kind "nostalgia")
        встаёт ПОСЛЕ relations, до mood (подсказка «важное к концу»)."""
        window = await self.memory.get_window_messages(chat_id)
        # Раунд 10.23 (F1, ADR-1023-1): текущий пользовательский ход —
        # триггер маркировки (сопоставление по Telegram message_id).
        # R1023F1-01: маркер ставится РОВНО ОДИН раз на всю сборку — только в
        # <Global_Context> (единственный «исторический» блок; цепочка стартует
        # от текущего хода, поэтому thread/branch его дублируют). Вспомогательные
        # блоки получают trigger_message_id=None и маркер не расходуют.
        trigger_message_id = getattr(message, "message_id", None)
        # Раунд 8 (C2/T-793): карта по активным участникам (24 ч) + окно;
        # суффиксы-дискриминаторы (C3/T-794) считаются один раз на рендер.
        active = await self._active_participants(chat_id)
        roster, suffix_map = self._participant_roster(window, active)
        blocks: list[tuple[str, str]] = []
        alias_map = self._alias_map_block(roster)
        if alias_map:
            blocks.append(("map", alias_map))
        # ASAP-3 (ADR-1028-2 D3/D7): композер — walk до CHAT_THREAD_WALK_MAX,
        # билдеры global/thread в режиме «без self-усечения».
        composer_mode = _composer.composer_on()
        if composer_mode:
            chain = await self._collect_thread_chain(
                chat_id, message, depth=_composer.thread_walk_max())
        else:
            chain = await self._collect_thread_chain(chat_id, message)
        if self._is_reply_trigger(message) and len(chain) >= 2:
            branch = self._render_branch(chain, suffix_map)
            if branch:
                blocks.append(("branch", branch))
        # F2: global считается раньше RAG (тело фона — для словарного дедупа).
        global_parts: dict | None = None
        if composer_mode:
            global_parts = await self._build_global_context_parts(
                chat_id, window, roster, suffix_map,
                trigger_message_id=trigger_message_id)
            global_ctx = "\n".join(
                global_parts["head_lines"] + global_parts["tail_lines"])
        else:
            global_ctx = await self._build_global_context(
                chat_id, window, roster, suffix_map,
                trigger_message_id=trigger_message_id)
        # Раунд 9 (E1/T-826): второй элемент кортежа — маркер «золотых»
        # (блок kind "nostalgia" ставится ПОЗЖЕ: после relations, до mood).
        rag_block, nostalgia_hint = await self._build_rag_block(
            chat_id, message, global_ctx)
        if rag_block:
            blocks.append(("rag", rag_block))
        if composer_mode:
            # <Global_Context> materializируется композером из частей
            # (head=P2 / middle=P3 / tail=P1) на слоте global.
            pass
        elif global_ctx:
            blocks.append(("global", global_ctx))
        if composer_mode:
            thread = self._render_thread(chain, suffix_map, None,
                                         trigger_message_id, truncate=False)
        else:
            thread = self._render_thread(chain, suffix_map,
                                         await self._thread_limit(chat_id))
        if thread:
            blocks.append(("thread", thread))
        # Раунд 8 (C5/T-796): блок адресата — канон + uid запросившего.
        target_block = (f"<Target_User>{escape_xml_text(target_name)}"
                        f"{_speaker_tag('', target_user_id)}"
                        f"</Target_User>")
        blocks.append(("target", target_block))
        # Раунд 9 (AGI Memory, B4/T-819, spec §3.1.4/Q3): <user_relations> —
        # СРАЗУ ПОСЛЕ ("target", …) и ДО protected/lore (гейты: глобальный
        # флаг И per-chat relations_enabled; RelationsService из lore_runtime;
        # fail-open: пусто/не установлен → блока нет).
        relations_block = await self._build_user_relations(
            chat_id, target_user_id, target_name)
        if relations_block:
            blocks.append(("relations", relations_block))
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
        # Раунд 9 (E1/T-826, spec §3.5.1): ностальгия-маркер — в user-контент
        # ПОСЛЕ relations, до mood (compact: фикс-кап до инжекта, в общем
        # порядке урезания участвует последним — _apply_context_budget).
        if nostalgia_hint:
            blocks.append(("nostalgia", nostalgia_hint))
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
        # ── ASAP-3 (ADR-1028-2 D3): единый композер — classification P0–P3 →
        # full payload → allocation → materialize (порядок блоков не меняется).
        if composer_mode:
            return await self._compose_user_content(
                chat_id=chat_id, message=message, blocks=blocks, chain=chain,
                window=window, roster=roster, suffix_map=suffix_map,
                global_parts=global_parts, target_name=target_name,
                target_user_id=target_user_id,
                trigger_message_id=trigger_message_id,
                out_excluded=out_excluded)
        # Раунд 10.4 (B-2): гейт бюджетов — per-chat резолв (override →
        # hot.get → default; без override — байт-в-байт старое поведение).
        from services.chat_params import get_chat_param as _budget_gate
        from services import budget_gate as _master_gate
        # F21 (ADR-1024-22 D5): master-рубильник бюджетов приоритетен —
        # эффективный гейт контекста = master AND context-флаг. При master OFF
        # усечение выключено, даже если flags.chat_context_budgets_enabled=true;
        # при master ON поведение ровно как прежде (context-флаг решает).
        _master_on = await _master_gate.budgets_enabled(chat_id)
        _context_on = await _budget_gate(
            chat_id, "flags.chat_context_budgets_enabled",
            hot.get("flags.chat_context_budgets_enabled",
                    settings.CHAT_CONTEXT_BUDGETS_ENABLED))
        budgets_enabled = bool(_master_on) and bool(_context_on)
        budget_tokens = await _budget_gate(
            chat_id, "limits.chat_context_budget_tokens",
            hot.get("limits.chat_context_budget_tokens",
                    settings.CHAT_CONTEXT_BUDGET_TOKENS))
        # F4 (10.19, ADR-1019-4 D2): видимая причина возможного двойного
        # усечения — один WARNING на чат (fail-open, только числа, R17-safe).
        # D-1: инвариант учитывает оценку неприкосновенных блоков (fixed),
        # иначе реальная global-доля 0.30×(budget−fixed) может быть меньше
        # safe_budget(global_cap), а проверка «budget < caps» это пропустит.
        _uncuttable_kinds = ("target", "relations", "protected", "lore",
                             "current", "sandwich")
        fixed_est = sum(count_tokens(text) for kind, text in blocks
                        if kind in _uncuttable_kinds)
        await self._check_context_config_invariant(chat_id, budget_tokens,
                                                   fixed_est)
        # MCA-07 B-MCA07-2 (SC-12/A24): полный payload в живом call-site.
        external_tokens, reserve_tokens, method = 0, 0, None
        if budgets_enabled and mca_gates.adaptive_context_budget_enabled():
            external_tokens, reserve_tokens, method = \
                await self._estimate_external_payload_tokens(chat_id,
                                                             budget_tokens)
        return self._apply_context_budget(
            blocks, budgets_enabled, budget_tokens,
            external_tokens=(external_tokens or None),
            reserve_tokens=reserve_tokens,
            estimation_method=method,
            out_excluded=out_excluded)

    # ── ASAP-3 (round 1028, ADR-1028-2 D3–D7): Direct Context Composer ────

    async def _build_global_context_parts(
            self, chat_id: int, window: list, roster: list | None = None,
            suffix_map: dict[int, str] | None = None,
            trigger_message_id=None) -> dict:
        """ASAP-3 (D3/D5/D6): части <Global_Context> БЕЗ self-усечения
        (композер вызывает вместо `_build_global_context`).

        Зеркало legacy-билдера (3688-3754): running summary (без TTL-смерти)
        + level-2 → head_lines (P2-фон); verbatim-сообщения после watermark →
        tail_rows (P1, keep-end) с гарантированным полом
        CHAT_FRESH_TAIL_MIN_MESSAGES; кандидаты middle = post-watermark до
        пола. Без summary — последние CHAT_GLOBAL_CONTEXT_LIMIT сообщений
        (soft target, D13) как tail. RAG-дедупу отдаётся head+tail текст."""
        roster = roster or []
        suffix_map = suffix_map or {}
        tail_min = _composer.fresh_tail_min_messages()
        parts: dict = {
            "head_lines": [], "middle_rows": [], "tail_rows": [],
            "tail_lines": [], "window_end_ts": None, "raw_count": 0,
            "has_summary": False,
        }
        summary_text = None
        window_end_ts = None
        raw_count = 0
        if await chat_summary_enabled(chat_id):
            try:
                row = await self.db.get_running_summary(chat_id, time.time())
                if row is not None:
                    summary_text = row["summary"]
                    raw_count = int(row["raw_count"] or 0)
                    window_end_ts = row["window_end_ts"]
                if summary_text is not None:
                    try:
                        l2 = await self.db.get_summary_level(chat_id, 2)
                        if l2 is not None and (l2["summary"] or "").strip():
                            level2_text = str(l2["summary"]).strip()
                            cap2 = int(await _cp_g(
                                chat_id, "limits.chat_level2_max_chars",
                                hot.get("limits.chat_level2_max_chars",
                                        settings.CHAT_LEVEL2_MAX_CHARS)) or 0)
                            if cap2 and len(level2_text) > cap2:
                                level2_text = level2_text[-cap2:]
                            parts["head_lines"].append(
                                "широкий фон: " + level2_text)
                    except Exception:
                        logger.warning(
                            "direct: level2 read failed — without L2 row "
                            "| chat=%s", chat_id, exc_info=True)
            except Exception:
                logger.warning("direct: running summary read failed | chat=%s",
                               chat_id, exc_info=True)
        if summary_text is not None:
            parts["has_summary"] = True
            parts["window_end_ts"] = window_end_ts
            parts["raw_count"] = raw_count
            parts["head_lines"].append(
                f"фон: конспект из {raw_count} сообщений, "
                f"ниже дословно свежий хвост")
            parts["head_lines"].append(summary_text)
            post_rows = []
            for row in window:
                if int(row["timestamp"] or 0) <= window_end_ts:
                    continue
                if not (row["text"] or ""):
                    continue
                post_rows.append(row)
            # H1/D5 (rework round 1, сплит по review B-ASAP3-1): fresh tail =
            # ПОСЛЕДНИЕ tail_min post-watermark строк (P1, floor = весь piece —
            # тише резать нельзя, ниже только §17); middle-кандидаты = весь
            # НЕпокрытый хвостом диапазон → top-K ≤ CHAT_MIDDLE_MAX_MESSAGES
            # (P3, важность-вес). Дедуп middle — только против фактически
            # вошедшего tail (пост-аллокационная страховка).
            parts["tail_rows"] = post_rows[-tail_min:]
            parts["middle_rows"] = (post_rows[:-tail_min]
                                    if len(post_rows) > tail_min else [])
            parts["tail_lines"] = [
                self._context_row_line(
                    row, suffix_map, trigger_message_id=trigger_message_id)
                for row in parts["tail_rows"]]
        else:
            _g_limit = int(await _cp_g(
                chat_id, "limits.chat_global_context_limit",
                hot.get("limits.chat_global_context_limit",
                        settings.CHAT_GLOBAL_CONTEXT_LIMIT)) or 0)
            recent = window[-max(1, _g_limit):]
            tail_rows = [row for row in recent if (row["text"] or "")]
            parts["tail_rows"] = tail_rows
            parts["tail_lines"] = [
                self._context_row_line(
                    row, suffix_map, trigger_message_id=trigger_message_id)
                for row in tail_rows]
            if tail_rows:
                parts["head_lines"].append(
                    f"фон: дословно последние {len(tail_rows)} сообщений")
        return parts

    def _composer_truncate(self, piece, limit_tokens: int) -> str:
        """Усечение piece'а существующими механиками (D3): обёрнутые блоки —
        `_truncate_block` (теги + protected spans + importance); сырые части
        Global — целыми строками (head — keep-head конспекта; tail/middle —
        keep-end). Никакого `text[:N]`."""
        if piece.kind == "global_head":
            return "\n".join(_composer.truncate_lines_keep_start(
                piece.text.split("\n"), limit_tokens))
        if piece.kind in ("global_middle", "global_tail"):
            return "\n".join(_composer.truncate_lines_keep_end(
                piece.text.split("\n"), limit_tokens))
        return self._truncate_block(piece.text, limit_tokens,
                                    kind=piece.kind)

    async def _build_old_episodes(
            self, chat_id: int, query: str, tail_rows: list,
            suffix_map: dict[int, str]) -> tuple[str, dict]:
        """ASAP-3 (ADR-1028-2 D4, §9–§11): old verbatim episode retrieval.

        Вход — хиты ЕДИНОГО retrieval-контракта mca-07 (`mode="history"`,
        каналы exact/lexical; REUSE обязателен, второй движок запрещён).
        Границы — детерминированная чистая функция
        `_composer.compute_episode_span` (gap ≤ CHAT_EPISODE_GAP_SECONDS +
        reply-graph closure + склейка + капы), 0 LLM-вызовов, идемпотентно.
        Дедуп против fresh tail (пересечение → клип). Рендер — канонические
        строки яруса A в `<Old_Episode>` (P0). Explainability: лог
        hit → span → причина; счётчик direct_old_episode_retrieval_total."""
        stats = {"count": 0, "messages": 0, "tokens": 0, "hits": 0}
        if not mca_gates.retrieval_context_enabled():
            return "", stats
        text = str(query or "").strip()
        if not text:
            return "", stats
        try:
            request = _mca_rc.RetrievalRequest(
                chat_id=chat_id, query=text, mode="history", top_k=8,
                reply_depth=0)
            result = await _mca_rc.retrieve(self.db, self.memory, request)
        except Exception:
            logger.warning("direct: episode retrieval failed — skip | chat=%s",
                           chat_id, exc_info=True)
            return "", stats
        tail_tg = {_tg_id_of_row(row) for row in tail_rows}
        tail_tg.discard(None)
        used_tg: set[int] = set(tail_tg)
        max_count = _composer.episode_max_count()
        max_msgs = _composer.episode_max_messages()
        gap_s = _composer.episode_gap_seconds()
        episode_lines: list[str] = []
        for cand in result.candidates:
            if stats["count"] >= max_count:
                break
            if cand.entity_type != "message":
                continue
            hit_tg = _tg_id_of_ref(cand.id)
            if hit_tg is None or hit_tg in used_tg:
                continue
            stats["hits"] += 1
            try:
                rows = await self.db.get_messages_around(
                    chat_id, hit_tg, before=120, after=60)
            except Exception:
                logger.warning("direct: episode rows read failed | chat=%s",
                               chat_id, exc_info=True)
                continue
            span = _composer.compute_episode_span(
                rows, hit_tg, gap_seconds=gap_s, max_messages=max_msgs)
            if span is None:
                continue
            start, end, reason = span
            span_rows = [row for row in rows[start:end + 1]
                         if (row["text"] or "")
                         and _tg_id_of_row(row) not in used_tg]
            if not span_rows:
                continue
            lines = [self._context_row_line(row, suffix_map,
                                            trigger_message_id=None)
                     for row in span_rows]
            for row in span_rows:
                tg = _tg_id_of_row(row)
                if tg is not None:
                    used_tg.add(tg)
            episode_lines.extend(lines)
            stats["count"] += 1
            stats["messages"] += len(lines)
            logger.info(
                "direct: old episode | chat=%s hit=tg:%s span=%s..%s "
                "rows=%d reason=%s", chat_id, hit_tg,
                _tg_id_of_row(rows[start]), _tg_id_of_row(rows[end]),
                len(lines), reason)
        if not episode_lines:
            return "", stats
        stats["tokens"] = count_tokens("\n".join(episode_lines))
        _composer.record_direct_metric("direct_old_episode_retrieval_total")
        body = escape_xml_text("\n".join(episode_lines))
        return f"<Old_Episode>\n{body}\n</Old_Episode>", stats

    async def _compose_user_content(
            self, *, chat_id: int, message, blocks: list, chain: list,
            window: list, roster: list, suffix_map: dict[int, str],
            global_parts: dict, target_name: str,
            target_user_id: int | None, trigger_message_id,
            out_excluded: list | None) -> list[str]:
        """ASAP-3 (ADR-1028-2 D3): единый композер Dynamic/Unlimited.

        Конвейер §6 ТЗ: candidates (существующие билдеры, global/thread без
        self-усечения + old episodes + middle-подбор) → классификация P0–P3 →
        фактический full payload (model_capacity D1/D2; safety-множитель РОВНО
        один раз) → allocation (eviction P3→P2→P1, floors) → materialize
        (порядок блоков payload НЕ меняется). Physical overflow — явная
        деградация §3.9. Observability: CONTEXT_CAPACITY/SELECT/PRESSURE/
        PHYSICAL_OVERFLOW + счётчики §46 + diagnostics-снапшот (miniapp §34).
        Ошибки аллокации → fail-open: legacy `_apply_context_budget` на
        собранных кандидатах."""
        query = (message.text or "").strip()
        try:
            episode_block, episode_stats = await self._build_old_episodes(
                chat_id, query, global_parts["tail_rows"], suffix_map)
        except Exception:
            logger.warning("direct: episode build failed — skip | chat=%s",
                           chat_id, exc_info=True)
            episode_block, episode_stats = "", {"count": 0, "messages": 0,
                                                "tokens": 0, "hits": 0}

        # ── Кандидаты → pieces (позиции = канонический порядок блоков) ──
        # map → branch → episode → rag → global(head/middle/tail) → thread →
        # target → relations → protected → lore → nostalgia → mood → current
        # → anchors → sandwich (совместимость «важное к концу», D3).
        canonical_order = _composer.CANONICAL_ORDER
        candidates: list[tuple[str, str]] = [
            (kind, text) for kind, text in blocks
            if kind != "thread" and text]
        middle_lines = self._compose_middle_lines(
            global_parts, query, chain, roster)
        candidates.append(("episode", episode_block))
        candidates.extend([
            ("global_head", "\n".join(global_parts["head_lines"])),
            ("global_middle", "\n".join(middle_lines)),
            ("global_tail", "\n".join(global_parts["tail_lines"])),
        ])
        # Thread piece c floor (минимальная гарантия глубины рендера, D7).
        thread_text = ""
        thread_floor = 0
        for kind, text in blocks:
            if kind == "thread":
                thread_text = text
                break
        if thread_text:
            try:
                guaranteed = int(await _cp_g(
                    chat_id, "limits.chat_thread_max_depth",
                    hot.get("limits.chat_thread_max_depth",
                            settings.CHAT_THREAD_MAX_DEPTH)) or 0)
            except Exception:
                guaranteed = int(settings.CHAT_THREAD_MAX_DEPTH or 6)
            guaranteed = max(1, guaranteed)
            body_lines = thread_text.split("\n")
            keep_n = min(max(1, guaranteed), len(body_lines))
            thread_floor = count_tokens("\n".join(body_lines[-keep_n:]))
            candidates.append(("thread", thread_text))

        # H2/D6 (rework round 1): РЕАЛЬНЫЙ wiring пола fresh verbatim tail —
        # floor piece'а global_tail = токены последних
        # CHAT_FRESH_TAIL_MIN_MESSAGES строк (резервируется на ВСЕХ путях
        # давления ДО других слоёв; ниже — только путь §17 с событием).
        tail_floor = 0
        for kind, text in candidates:
            if kind == "global_tail" and text:
                tail_floor = _composer.tail_floor_tokens(
                    text, _composer.fresh_tail_min_messages())
                break

        pieces: list[_composer.ContextPiece] = []
        for kind, text in candidates:
            if not text:
                continue
            priority = _composer.BLOCK_PRIORITY.get(kind, _composer.P2)
            pieces.append(_composer.ContextPiece(
                key=kind, kind=kind, text=text, priority=priority,
                keep=_composer.PIECE_KEEP.get(kind, "span"),
                floor_tokens=(thread_floor if kind == "thread"
                              else (tail_floor if kind == "global_tail"
                                    else 0)),
                evictable=(priority != _composer.P0),
                position=canonical_order.get(kind, 99)))

        # ── Full payload (D2): окно модели + external (MCA-07 REUSE) ──
        model_name = str(getattr(self.llm, "_chat_model", "") or "")
        fallback_model = str(getattr(self.llm, "_fallback_model", "") or "")
        model_window, window_source = resolve_effective_window(
            model_name, fallback_model)
        try:
            external_tokens, _est_reserve, est_method = \
                await self._estimate_external_payload_tokens(
                    chat_id, model_window)
        except Exception:
            external_tokens, est_method = 0, None
        available, output_reserve = compute_available_budget(
            model_window, external_tokens)
        # Policy-слой (D2): -1 → Unlimited; 0/None → Dynamic; >0 → cap.
        from services.chat_params import get_chat_param as _budget_gate
        from services import budget_gate as _master_gate
        _master_on = await _master_gate.budgets_enabled(chat_id)
        _context_on = await _budget_gate(
            chat_id, "flags.chat_context_budgets_enabled",
            hot.get("flags.chat_context_budgets_enabled",
                    settings.CHAT_CONTEXT_BUDGETS_ENABLED))
        budgets_enabled = bool(_master_on) and bool(_context_on)
        raw_budget = await _budget_gate(
            chat_id, "limits.chat_context_budget_tokens",
            hot.get("limits.chat_context_budget_tokens",
                    settings.CHAT_CONTEXT_BUDGET_TOKENS))
        if not budgets_enabled:
            budget, policy_mode = available, "unlimited"
        else:
            budget, policy_mode = apply_budget_policy(available, raw_budget)

        # ── Allocation (eviction P3→P2→P1; P0 не трогается) ──
        try:
            allocation = _composer.allocate_budget(
                pieces, budget, truncator=self._composer_truncate)
        except Exception:
            logger.warning(
                "direct: composer allocation failed — legacy budget "
                "| chat=%s", chat_id, exc_info=True)
            legacy_blocks = [(kind, text) for kind, text in candidates if text]
            return self._apply_context_budget(
                legacy_blocks, budgets_enabled, raw_budget,
                out_excluded=out_excluded)

        # ── H1/D5 (rework round 1): дедуп middle против ФАКТИЧЕСКИ вошедшего
        # tail (после аллокации) — tail-кандидаты шире floor'а, и при слабом
        # давлении часть middle-подбора уже вербатим в выжившем tail.
        middle_piece = next((p for p in allocation.pieces
                             if p.kind == "global_middle"), None)
        tail_piece = next((p for p in allocation.pieces
                           if p.kind == "global_tail"), None)
        if middle_piece and middle_piece.text and tail_piece \
                and tail_piece.text:
            final_tail_tg = set(re.findall(r"tg:(\d+)", tail_piece.text))
            kept_middle = []
            for ln in middle_piece.text.split("\n"):
                if not ln.strip():
                    continue
                m = re.search(r"tg:(\d+)", ln)
                if m and m.group(1) in final_tail_tg:
                    continue            # уже вербатим в выжившем tail
                kept_middle.append(ln)
            middle_piece.text = "\n".join(kept_middle)
            middle_lines = kept_middle

        # ── H2/D6 (rework round 1): сигнал зажатия пола fresh tail — при
        # фактическом давлении tail стоит на минимуме
        # CHAT_FRESH_TAIL_MIN_MESSAGES (ниже — только путь §17:
        # CONTEXT_PHYSICAL_OVERFLOW + счётчик).
        try:
            pressure_engaged = bool(
                allocation.compressed_or_dropped or allocation.excluded
                or allocation.physical_overflow)
            if pressure_engaged and tail_piece is not None \
                    and tail_piece.text:
                final_tail_lines = len(
                    [ln for ln in tail_piece.text.split("\n")
                     if ln.strip()])
                _composer.emit_context_tail_floor_clamped(
                    chat_id=chat_id,
                    final_messages=final_tail_lines,
                    floor_messages=_composer.fresh_tail_min_messages())
        except Exception:
            logger.debug("direct: tail floor clamp event failed", exc_info=True)

        # ── Materialize (порядок блоков payload НЕ меняется) ──
        final_texts: list[str] = []
        global_body_parts: list[str] = []
        global_slot_done = False

        def _flush_global() -> None:
            nonlocal global_slot_done
            if global_slot_done:
                return
            global_slot_done = True
            if global_body_parts:
                body = "\n".join(global_body_parts)
                final_texts.append(
                    f"<Global_Context>\n{escape_xml_text(body)}\n"
                    f"</Global_Context>")

        for piece in sorted(allocation.pieces, key=lambda p: p.position):
            if piece.kind in ("global_head", "global_middle", "global_tail"):
                if piece.text:
                    global_body_parts.append(piece.text)
                continue
            if not global_slot_done and piece.position > 6:
                # слот global (позиции 4–6) пройден — блок на своём месте.
                _flush_global()
            if piece.text:
                final_texts.append(piece.text)
        _flush_global()

        # ── Observability (§32/§33) + diagnostics (§34) ──
        used_tokens = sum(count_tokens(t) for t in final_texts)
        record_context_usage(used_tokens,
                             None if policy_mode == "unlimited" else budget,
                             bool(allocation.excluded),
                             unlimited=(policy_mode == "unlimited"))
        summary_lag = None
        summary_age = None
        if global_parts["has_summary"]:
            summary_lag = (len(global_parts["tail_rows"])
                           + len(global_parts["middle_rows"]))
            if global_parts["window_end_ts"]:
                summary_age = max(0, int(time.time()
                                         - int(global_parts["window_end_ts"])))
        summary_revision = await self._summary_revision(chat_id)
        _composer.emit_context_capacity(
            model=model_name, window=model_window, window_source=window_source,
            external_tokens=external_tokens, output_reserve=output_reserve,
            available_context=available, budget=budget,
            policy_mode=policy_mode, summary_revision=summary_revision,
            summary_watermark=global_parts["window_end_ts"],
            summary_lag_messages=summary_lag, summary_age=summary_age,
            estimation_method=est_method)
        tail_tokens = count_tokens("\n".join(global_parts["tail_lines"]))
        _composer.emit_context_select(
            chat_id=chat_id, message_id=trigger_message_id,
            recent_verbatim_messages=len(global_parts["tail_lines"]),
            recent_verbatim_tokens=tail_tokens,
            reply_thread_messages=(len(chain) if thread_text else 0),
            old_episode_count=episode_stats["count"],
            old_episode_messages=episode_stats["messages"],
            old_episode_tokens=episode_stats["tokens"],
            middle_selected_messages=len(middle_lines),
            compressed_background_tokens=count_tokens(
                "\n".join(global_parts["head_lines"])),
            rag_tokens=count_tokens(next(
                (t for k, t in candidates if k == "rag"), "")))
        # M-ASAP3-1: pressure — и полные дропы, и полурезки (compression).
        if allocation.excluded or allocation.compressed_or_dropped:
            _composer.record_direct_metric("direct_context_pressure_total")
            _composer.emit_context_pressure(
                chat_id=chat_id,
                excluded_low_priority=len(allocation.excluded),
                compressed_or_dropped=allocation.compressed_or_dropped,
                physical_overflow=allocation.physical_overflow,
                unsummarized_tail_messages=summary_lag or 0,
                unsummarized_tail_tokens=tail_tokens)
        if allocation.physical_overflow:
            _composer.record_direct_metric(
                "direct_context_physical_overflow_total")
            _composer.emit_context_physical_overflow(
                chat_id=chat_id,
                preserved_kinds=allocation.preserved_kinds,
                available=allocation.available, needed=allocation.needed)
            logger.warning(
                "direct: context physical overflow | chat=%s available=%d "
                "needed=%d preserved=%s", chat_id, allocation.available,
                allocation.needed,
                ",".join(allocation.preserved_kinds) or "-")
        if out_excluded is not None:
            for item in allocation.excluded:
                out_excluded.append(dict(item))
        _composer.record_diagnostics(chat_id, {
            "model": model_name[:64], "window": int(model_window),
            "window_source": str(window_source),
            "external_tokens": int(external_tokens),
            "output_reserve": int(output_reserve),
            "available_context": int(available), "budget": int(budget),
            "policy_mode": str(policy_mode), "payload": int(used_tokens),
            "recent_verbatim_messages": len(global_parts["tail_lines"]),
            "recent_verbatim_tokens": int(tail_tokens),
            "old_episode_count": int(episode_stats["count"]),
            "old_episode_messages": int(episode_stats["messages"]),
            "middle_selected_messages": len(middle_lines),
            "compressed_background_tokens": count_tokens(
                "\n".join(global_parts["head_lines"])),
            "excluded_low_priority": len(allocation.excluded),
            "physical_overflow": bool(allocation.physical_overflow),
            "updated_at": int(time.time()),
        })
        return final_texts

    def _compose_middle_lines(self, global_parts: dict, query: str,
                              chain: list, roster: list) -> list[str]:
        """D5: importance-aware top-K выбор unsummarized middle (bounded
        `CHAT_MIDDLE_MAX_MESSAGES`) из диапазона, не покрытого гарантированным
        floor'ом хвоста (candidates уже = post_rows[:-tail_min], см. parts).
        Хронологический ASC (детерминизм). Дедуп против ФАКТИЧЕСКИ вошедшего
        tail выполняется после аллокации (см. _compose_user_content)."""
        middle_rows = list(global_parts.get("middle_rows") or [])
        if not middle_rows:
            return []
        top_k = _composer.middle_max_messages()
        chain_tg: set[int] = set()
        for item in chain or []:
            ref = str(getattr(item, "item_id", "") or "")
            if ref.startswith("tg:"):
                try:
                    chain_tg.add(int(ref[3:]))
                except ValueError:
                    continue
        participants: set[int] = set()
        for entry in roster or ():
            try:
                uid, _display = entry
                if uid is not None:
                    participants.add(int(uid))
            except (TypeError, ValueError):
                continue
        selected = _composer.select_middle(
            middle_rows, query=query, chain_tg_ids=chain_tg,
            participant_ids=participants, top_k=top_k)
        lines = []
        for row in selected:
            if not (row["text"] or ""):
                continue
            lines.append(self._context_row_line(row, {}, None))
        return lines

    async def _summary_revision(self, chat_id: int) -> str | None:
        """M-MCA07-1: revision источников сводки (`window_end_ts:raw_count`).

        Fail-open → None (нет БД/метода/строки/ошибка)."""
        db = getattr(self, "db", None)
        if db is None or not hasattr(db, "get_running_summary"):
            return None
        try:
            row = await db.get_running_summary(chat_id, time.time())
        except Exception:
            return None
        if row is None:
            return None
        try:
            return f"{row['window_end_ts']}:{row['raw_count']}"
        except Exception:
            return None

    async def _build_evidence_bundle(self, chat_id: int, message, query: str,
                                     target_name: str, user_id,
                                     user_blocks: list, *,
                                     excluded: list | None = None,
                                     chosen_intent: str | None = None):
        """MCA-07 (T-3852, ADR-1027-7 D5/D6): собрать ЕДИНЫЙ in-memory
        `EvidenceBundle` из уже построенных user-блоков (без нового I/O и без
        второго контракта). Ссылается на канонические ID-ссылки (`tg:/msg:/
        fact:`), не копирует архив. Gate OFF → ``None`` (точный legacy-путь).
        Fail-open: ошибка сборки → ``None`` (контекст не рвётся)."""
        if not mca_gates.evidence_bundle_enabled():
            return None
        try:
            trigger_id = getattr(message, "message_id", None)
            current_ref = (f"tg:{trigger_id}" if trigger_id is not None
                           else None)
            # Ветка reply-графа и evidence-ссылки — из канонического рендера.
            branch_block = (
                _block_with_tag(user_blocks, "Conversation_Branch")
                + "\n"
                + _block_with_tag(user_blocks, "Conversation_Thread"))
            branch = tuple(dict.fromkeys(
                _REF_ID_RE.findall(branch_block)))[:_BUNDLE_BLOCK_MAX_REFS]
            rag_block = _block_with_tag(user_blocks, "RAG_Memory")
            evidence_refs = tuple(dict.fromkeys(
                _REF_ID_RE.findall(rag_block)))[:_BUNDLE_BLOCK_MAX_REFS]
            current_q = _inner_tag_text(
                _block_with_tag(user_blocks, "Current_Question"),
                "Current_Question")
            constraints = (current_q,) if current_q else ()
            evidence = []
            if current_ref:
                evidence.append(_mca_rc.EvidenceItem(
                    source_ref_id=None, entity_type="message",
                    entity_id=current_ref, label="current"))
            for ref in evidence_refs:
                entity_type = ("graph_fact" if ref.startswith("fact:")
                               else "message")
                evidence.append(_mca_rc.EvidenceItem(
                    source_ref_id=None, entity_type=entity_type,
                    entity_id=ref))
            excluded_items = tuple(
                _mca_rc.ExcludedItem(
                    ref=str(item.get("kind") or ""), position=idx,
                    reason_code=str(item.get("reason_code") or ""),
                    estimated_tokens=int(item.get("estimated_tokens") or 0))
                for idx, item in enumerate(excluded or []))
            # M-MCA07-2: доступные поля §11.2 из уже построенных блоков.
            mentioned = tuple(dict.fromkeys(
                _map_names(_block_with_tag(user_blocks, "UserResolutionMap")))
            )[:_BUNDLE_BLOCK_MAX_REFS]
            relations = tuple(dict.fromkeys(
                _block_lines(_block_with_tag(user_blocks, "user_relations")))
            )[:_BUNDLE_BLOCK_MAX_REFS]
            recent_actions = (chosen_intent,) if chosen_intent else ()
            # M-MCA07-1: context_version — над current-revision + веткой +
            # evidence + summary_revision (derived из running summary).
            summary_revision = await self._summary_revision(chat_id)
            selected_refs = ([(current_ref, current_ref)] if current_ref else [])
            selected_refs += [(ref, None) for ref in (*branch, *evidence_refs)]
            context_version = _mca_rc.compute_context_version(
                current_revision=current_ref,
                selected_refs=selected_refs,
                summary_revision=summary_revision,
                policy_version=_mca_rc.RETRIEVAL_POLICY_VERSION)
            return _mca_rc.EvidenceBundle(
                trigger=current_ref, current_message_ref=current_ref,
                current_revision=current_ref,
                addressee=target_name or None, author=target_name or None,
                mentioned=mentioned, branch=branch, local_context=(),
                evidence=tuple(evidence), constraints=constraints,
                relations=relations, chosen_intent=chosen_intent,
                recent_actions=recent_actions, context_version=context_version,
                excluded=excluded_items)
        except Exception:
            logger.warning("[mca07] evidence bundle build failed — None",
                           exc_info=True)
            return None

    async def _check_context_config_invariant(self, chat_id: int,
                                              budget_tokens,
                                              fixed_tokens: int = 0) -> None:
        """F4 (ADR-1019-4 D2, D-1): видимая причина возможного двойного
        усечения. Инвариант сравнивает **реально применяемые доли**
        `_apply_context_budget` (от `effective = budget − fixed_tokens`):
        global-долю `CHAT_BUDGET_GLOBAL_RATIO × effective` с
        `safe_budget(global_cap)` и thread-долю с `safe_budget(thread_cap)`.
        Если доля меньше per-block потолка — при общем давлении блок режется
        «второй раз». Fail-open: любая ошибка — молча (диагностика не должна
        ломать ответ); один WARNING на чат; только числа (R17-safe)."""
        try:
            warned = getattr(self, "_ctx_cfg_warned", None)
            if warned is None:
                warned = self._ctx_cfg_warned = set()
            if chat_id in warned:
                return
            warned.add(chat_id)
            if context_state(budget_tokens) == "unlimited":
                return
            budget = (int(budget_tokens)
                      if context_state(budget_tokens) == "cap"
                      else int(settings.CHAT_CONTEXT_BUDGET_TOKENS))
            _g = await _cp_g(
                chat_id, "limits.chat_global_context_max_tokens",
                hot.get("limits.chat_global_context_max_tokens",
                        settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS))
            _t = await _cp_g(
                chat_id, "limits.chat_thread_max_tokens",
                hot.get("limits.chat_thread_max_tokens",
                        settings.CHAT_THREAD_MAX_TOKENS))
            gcap = resolve_context_tokens(
                _g, int(settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS or 5000))
            tcap = resolve_context_tokens(
                _t, int(settings.CHAT_THREAD_MAX_TOKENS or 3000))
            gbudget = safe_budget(gcap)
            tbudget = safe_budget(tcap)
            effective = max(1, budget - max(0, int(fixed_tokens or 0)))
            g_share = max(1, int(effective * hot.get(
                "limits.chat_budget_global_ratio",
                settings.CHAT_BUDGET_GLOBAL_RATIO)))
            t_share = max(1, int(effective * hot.get(
                "limits.chat_budget_thread_ratio",
                settings.CHAT_BUDGET_THREAD_RATIO)))
            if g_share < gbudget or t_share < tbudget:
                logger.warning(
                    "[direct] context config inconsistent | budget=%d "
                    "fixed=%d -> effective=%d | global_share=%d < "
                    "global_budget=%d or thread_share=%d < thread_budget=%d — "
                    "возможно двойное усечение блоков",
                    budget, int(fixed_tokens or 0), effective,
                    g_share, gbudget, t_share, tbudget)
        except Exception:
            logger.debug("direct: context config invariant check failed",
                         exc_info=True)

    def _render_current_question(self, message) -> str:
        """Раунд 8 (D1/T-798, spec §3.D1): блок <Current_Question> — текст
        текущего сообщения после среза обращения «бот(@ник):»; cap
        limits.chat_current_question_max_chars (default 800); НЕ режется
        бюджетом (kind вне лимитов). Пустой после среза — без блока.

        Раунд 10.24 (F13, ADR-1024-14 D3): к тексту дописываются медиа-маркеры
        нативного медиа самого сообщения и ``reply_to_message`` (``tg:<id>``).
        При пустом тексте с медиа блок не пуст; при непустом — текст усекается
        до резерва под суффикс, маркер гарантированно выживает. Флаг OFF или
        отсутствие медиа → ровно прежний ``stripped[:cap]`` (байт-в-байт)."""
        stripped = _strip_direct_prefix(message.text or "")
        markers: list[str] = []
        if media_context_enabled():
            own = message_media_type(message)
            if own:
                markers.append(
                    media_marker(own, f"tg:{getattr(message, 'message_id', '')}"))
            reply = getattr(message, "reply_to_message", None)
            reply_type = message_media_type(reply)
            if reply_type:
                markers.append(
                    media_marker(
                        reply_type, f"tg:{getattr(reply, 'message_id', '')}"))
        if not stripped and not markers:
            return ""
        cap = int(hot.get("limits.chat_current_question_max_chars",
                          settings.CHAT_CURRENT_QUESTION_MAX_CHARS) or 0) \
            or 800
        if markers:
            suffix = " ".join(markers)
            room = max(0, cap - len(suffix) - 1)
            if room:
                body = stripped[:room] + (" " + suffix if stripped else suffix)
            else:
                body = suffix
        else:
            body = stripped[:cap]
        return (f"<Current_Question>\n"
                f"{escape_xml_text(body)}\n"
                f"</Current_Question>")

    @staticmethod
    def _is_reply_trigger(message) -> bool:
        """Раунд 8 (D4/T-801): сообщение — reply (есть reply_to_message)."""
        return getattr(message, "reply_to_message", None) is not None

    # ── Раунд 9 (AGI Memory, T-819/B4, spec §3.1.4/Q3): <user_relations> ──

    async def _dig_pre_gate_block(self, chat_id: int, query: str) -> str:
        """Пре-гейт маркеров ностальгии (major-1, spec §3.2.3): маркер в
        сообщении И флаг flags.dig_pre_gate_enabled (default false) →
        dig_into_lore через роутер (dispatch по имени, как модель) →
        блок `<dig_result>\n…\n</dig_result>`. Ничего (""): флаг off, нет
        маркера, нет роутера, пустой/служебный результат («отключен»/
        «ОШИБКА …»/пусто). Fail-open — никогда не бросает."""
        if not hot.get("flags.dig_pre_gate_enabled",
                       settings.DIG_PRE_GATE_ENABLED):
            return ""
        text = str(query or "").strip()
        if not text or not _nostalgia_markers(text):
            return ""
        router = self.tool_router
        if router is None or not hasattr(router, "dispatch"):
            return ""
        try:
            raw = await router.dispatch(
                "dig_into_lore",
                {"query": text, "mode": "both"},
                ToolContext(chat_id, text))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "direct: dig pre-gate failed — блок не строится | chat=%s",
                chat_id, exc_info=True)
            return ""
        result = str(raw or "").strip()
        if not result:
            return ""
        if result.startswith("ОШИБКА") \
                or "отключен" in result.lower():
            logger.info(
                "direct: dig pre-gate служебный ответ — без инжекта | chat=%s",
                chat_id)
            return ""
        if len(result) > _DIG_RESULT_MAX_CHARS:
            result = result[:_DIG_RESULT_MAX_CHARS].rstrip() + "…"
        return f"<dig_result>\n{result}\n</dig_result>"

    @staticmethod
    def _insert_dig_result(user_blocks: list[str], dig_block: str
                           ) -> list[str]:
        """Блок <dig_result> ПЕРЕД <Target_User> (spec §3.2.3: «важное к
        концу», но результат копания должен быть виден до адресата-блока)."""
        if not dig_block:
            return user_blocks
        target_idx = next(
            (i for i, b in enumerate(user_blocks)
             if b.startswith("<Target_User>")), None)
        if target_idx is None:
            return list(user_blocks) + [dig_block]
        blocks = list(user_blocks)
        blocks.insert(target_idx, dig_block)
        return blocks

    async def _image_pre_gate_block(self, chat_id: int, query: str, bot,
                                    message, user_id,
                                    correlation_id: str | None = None) -> str:
        """Раунд 10.23 (F5, ADR-1023-5 §D2): пре-гейт ключевиков генерации
        изображений («Бот, нарисуй …»). Генерация+отправка ДО Stage-1, блок
        ``<image_result>`` для инъекции. `tool_choice` НЕ форсируется. Нет
        ключевика/модуль OFF/нет бота → ``""``. Fail-open — не бросает.
        F7 rework: ``correlation_id`` ответа прокидывается в ToolContext, чтобы
        событие ``step='image'`` попало в дерево последнего вызова."""
        from services import image_generation
        if not image_generation.is_image_keyword(query):
            return ""
        if not await image_generation.resolve_module_enabled(chat_id):
            return ""
        # Review iter1 Finding 4: роутер здесь НЕ нужен — генерация и отправка
        # выполняются сервисом самостоятельно (spec §2.2: условие — «модуль ON»).
        try:
            tool_ctx = ToolContext(
                chat_id, query, bot=bot,
                reply_to_message_id=getattr(message, "message_id", None),
                user_id=user_id,
                correlation_id=correlation_id)
            # A4 (ADR-1026-19 D1/§7.3): те же источники, что у tool-пути —
            # один helper, две точки вызова (второго резолвера/RAG нет).
            # Зависимости передаются только если доступны (совместимость с
            # прежними вызовами/фасадами без memory/db/aliases).
            deps = {}
            for name in ("aliases", "db", "memory"):
                value = getattr(self, name, None)
                if value is not None:
                    deps[name] = value
            return await image_generation.maybe_handle_keyword(
                tool_ctx, query, **deps)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "direct: image pre-gate failed — блок не строится | chat=%s",
                chat_id, exc_info=True)
            return ""

    async def _build_user_relations(self, chat_id: int,
                                    target_user_id: int | None,
                                    target_name: str) -> str:
        """Блок `<user_relations>` — карточка ЦЕЛЕВОГО собеседника (D-14,
        фикс-раунд: компактная строка вместо списка активных юзеров):
        `{Имя}: {стадия_ru}, в чате с {first_seen:ГГГГ-ММ}, {N} сообщ. за
        30 дней` (+ суффикс «(ручная пометка админа)» при manual-стадии;
        + «| пометка: {note}» если есть заметка админа).
        Гейты (0 влияния на поведение при любом «нет»): только группы
        (chat_id < 0, D-12); глобальный флаг flags.relations_tone_enabled;
        per-chat relations_enabled из PG-профиля (кэш; нет профиля/ошибка →
        нет); RelationsService лениво из lore_runtime (не установлен → нет).
        Cap limits.relations_inject_max_chars (600) ДО инжекта (маркер
        «…[обрезано]»); kind "relations" uncuttable в _apply_context_budget.
        Fail-open: любая ошибка → "" (WARNING, диалог жив)."""
        if chat_id >= 0:
            return ""
        if not hot.get("flags.relations_tone_enabled",
                       settings.RELATIONS_TONE_ENABLED):
            return ""
        if target_user_id in (None, 0):
            return ""
        from services import lore_runtime
        service = lore_runtime.get_relations_service()
        if service is None:
            return ""
        try:
            cache = self.chat_lore_cache or lore_runtime.get_lore_cache()
            profile = await cache.get(chat_id) if cache is not None else None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "direct: relations profile gate failed — блок не строится | "
                "chat=%s", chat_id, exc_info=True)
            return ""
        if profile is None or not getattr(profile, "relations_enabled", False):
            return ""
        try:
            relation = await service.get_user_relation(
                chat_id, int(target_user_id))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "direct: relations read failed — блок не строится | chat=%s",
                chat_id, exc_info=True)
            return ""
        if not relation:
            return ""
        stage = str(relation.get("stage") or "stranger")
        stage_ru = STAGE_RU.get(stage, stage)
        if relation.get("stage_manual"):
            stage_ru = f"{stage_ru} (ручная пометка админа)"
        name = escape_xml_text(str(target_name or "").strip()) \
            or str(relation.get("user_id") or target_user_id)
        line = f"{name}: {stage_ru}"
        first_seen = relation.get("first_seen")
        try:
            fs = int(first_seen)
            fs_month = datetime.datetime.fromtimestamp(fs).strftime("%Y-%m")
        except (TypeError, ValueError, OSError, OverflowError):
            fs_month = None
        if fs_month:
            line = f"{line}, в чате с {fs_month}"
        msg30 = int(relation.get("msg30") or 0)
        line = f"{line}, {msg30} сообщ. за 30 дней"
        note = relation.get("note")
        if note:
            line = f"{line} | пометка: {escape_xml_text(str(note))}"
        opening, closing = "<user_relations>", "</user_relations>"
        cap = int(hot.get("limits.relations_inject_max_chars",
                          settings.RELATIONS_INJECT_MAX_CHARS) or 0) \
            or 600
        if len(opening) + len(line) + len(closing) > cap:
            room = max(0, cap - len(opening) - len(closing)
                       - len(_RELATIONS_CUT_MARKER))
            line = line[:room].rstrip() + _RELATIONS_CUT_MARKER
        return f"{opening}{line}{closing}"

    # ── Раунд 8: memorize-хук с пост-фазой атрибуции (C6/T-797) ──

    async def _memorize_direct_reply(self, chat_id: int, query: str,
                                     answer: str, asker_canon: str, *,
                                     tg_message_id: int | None = None,
                                     forward_from: str = "",
                                     asker_user_id: int | None = None) -> None:
        """C6: memorize_facts (target_user = канон автора запроса — «кто
        спрашивал», как и было) + пост-фаза: subject/object фактов,
        совпадающие с участниками карты чата, НЕ остаются на спрашивающем —
        target_user переназначается тому участнику (факты о третьих лицах
        не засоряют карточку и квоту спрашивающего). Fail-open: ошибка БД →
        WARNING, факты остаются записанными (NFR-6).

        Раунд 10.14 (F1 anti-echo-self-reply, ADR-1014-2 D4, spec §3.3):
        при flags.bot_self_awareness_enabled (дефолт True):
          1) запрос юзера пишется отдельным фактом bot_direct_reply;
          2) ответ бота проходит LLM-экстрактор сути (self_reflection);
          3) суть пишется отдельным origin='bot_self_reply' (вес 0.2);
        self НЕ переприсваивается (_reassign_fact_owners берёт только
        bot_direct_reply, before_id снят ДО обоих вызовов). Флаг OFF → ровно
        прежняя строка байт-в-байт (query\\nanswer под bot_direct_reply)."""
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
        # H3-фикс: гейт самоосознания резолвится per-chat (override → global).
        from services.chat_params import get_chat_param as _self_gate
        self_aware = await _self_gate(
            chat_id, "flags.bot_self_awareness_enabled",
            hot.get("flags.bot_self_awareness_enabled",
                    settings.BOT_SELF_AWARENESS_ENABLED))
        if self_aware:
            # ON: запрос — сам по себе, ответ бота — сутью в self-origin.
            await self.memory.memorize_facts(
                chat_id, query, "bot_direct_reply", target_user=asker_canon,
                tg_message_id=tg_message_id, forward_from=forward_from)
            try:
                essence = await extract_self_essence(
                    self.llm, answer, chat_id=chat_id,
                    on_status=record_extractor_status)
            except Exception:
                logger.warning(
                    "direct: self essence extraction crashed — self fact "
                    "skipped | chat=%s", chat_id, exc_info=True)
                essence = ""
            if essence:
                try:
                    await self.memory.memorize_self_reply(chat_id, essence)
                except Exception:
                    logger.warning(
                        "direct: self fact write failed — skipped | chat=%s",
                        chat_id, exc_info=True)
        else:
            # OFF: байт-в-байт прежнее поведение.
            await self.memory.memorize_facts(
                chat_id, f"{query}\n{answer}", "bot_direct_reply",
                target_user=asker_canon,
                tg_message_id=tg_message_id, forward_from=forward_from)
        if before_id is None:
            return
        # MCA-04a FIX п.1 (spec §4.6, A85/A86): при включённой субъект-
        # атрибуции эвристика `_reassign_fact_owners` заменяется валидируемой
        # атрибуцией (subject_ref + attribution_method + assertion_kind); OFF —
        # точный legacy-путь (паритет baseline).
        try:
            from services import provenance as _prov
            _attribution_on = _prov.attribution_enabled()
        except Exception:
            _attribution_on = False
        if _attribution_on:
            try:
                await self._apply_fact_attribution(
                    chat_id, asker_canon, before_id,
                    tg_message_id=tg_message_id,
                    asker_user_id=asker_user_id)
            except Exception:
                logger.warning(
                    "direct: fact attribution failed — facts stay on asker "
                    "| chat=%s user=%s", chat_id, asker_canon, exc_info=True)
            return
        try:
            await self._reassign_fact_owners(chat_id, asker_canon, before_id)
        except Exception:
            logger.warning(
                "direct: fact owner reassign failed — facts stay on asker "
                "| chat=%s user=%s", chat_id, asker_canon, exc_info=True)

    async def _apply_fact_attribution(self, chat_id: int, asker_canon: str,
                                      min_id: int, *,
                                      tg_message_id: int | None = None,
                                      asker_user_id: int | None = None
                                      ) -> None:
        """MCA-04a FIX п.1 (spec §4.6): валидируемая субъект-атрибуция фактов
        direct-reply. Заменяет эвристику `_fact_owner_canon`:

        * subject == asker → `self_report`, target_user остаётся asker;
        * subject — другой участник карты → `third_party`, target_user=subject;
        * subject не участник (общие знания/новости/этимология) →
          `world_knowledge`, target_user=NULL (не личный факт спрашивающего);
        * subject — бот → `bot_self_reply` (отдельно от фактов о людях).

        Для личных (self_report/third_party) пишется `subject_ref_id`
        (устойчивый ID) и SourceRef-связь. Fail-open на каждый факт."""
        from services import provenance
        participants = await self._active_participants(chat_id)
        canons = {self.aliases.canon_name(name) for _, name
                  in self._participant_roster([], participants)[0]}
        canons = {c for c in canons if c}
        canons.add(asker_canon)
        try:
            cursor = await self.db.db.execute(
                "SELECT id, fact, tg_message_id, origin FROM "
                "graph_facts WHERE chat_id = ? AND id > ? AND "
                "origin = 'bot_direct_reply' ORDER BY id ASC",
                (chat_id, int(min_id)))
            rows = await cursor.fetchall()
        except Exception:
            logger.warning("direct: attribution read failed | chat=%s",
                           chat_id, exc_info=True)
            return
        # B-MCA04A-1: для self-report субъект = говорящий по устойчивому
        # `user_id` (из апдейта), а не поиск по имени — одноимённые не сливаются.
        # При отсутствии user_id — fail-open резолв по канон-имени.
        if asker_user_id:
            speaker_ref = provenance.user_source_ref(
                chat_id, int(asker_user_id))
        else:
            speaker_ref = await provenance.resolve_subject_ref(
                self.db, chat_id, asker_canon, canon=self.aliases.canon_name)
        speaker_uid = (int(speaker_ref.entity_id)
                       if speaker_ref.resolution == "resolved" else None)
        for row in rows:
            fid = int(row["id"])
            subject = provenance.guess_subject(
                row["fact"], canons, self.aliases.canon_name)
            if subject is None:
                method = "world_knowledge"
                kind = "world_knowledge"
            else:
                method = provenance.classify_attribution_method(
                    origin=row["origin"], subject=subject, speaker=asker_canon,
                    canon=self.aliases.canon_name, participants=canons)
                kind = provenance.classify_assertion_kind(
                    subject, row["fact"], canon=self.aliases.canon_name,
                    participants=canons)
            subject_ref_id = None
            new_target = None
            if method in ("self_report", "third_party") \
                    and kind != "world_knowledge":
                if method == "self_report" \
                        and speaker_ref.resolution == "resolved":
                    # Self-report: субъект — это говорящий (устойчивый ID),
                    # без поиска по имени (одноимённые не сливаются).
                    ref = speaker_ref
                else:
                    ref = await provenance.resolve_subject_ref(
                        self.db, chat_id, subject,
                        canon=self.aliases.canon_name)
                subject_ref_id = await provenance.resolve_source_ref(
                    self.db, ref)
                new_target = subject
            try:
                async def _body(conn, _id=fid, _t=new_target,
                                _sref=subject_ref_id, _m=method, _k=kind,
                                _sp=speaker_uid):
                    await conn.execute(
                        "UPDATE graph_facts SET target_user = ?, "
                        "subject_ref_id = ?, attribution_method = ?, "
                        "assertion_kind = ?, speaker_author_id = ?, "
                        "provenance_channel = COALESCE(provenance_channel, "
                        "'live') WHERE id = ?",
                        (_t, _sref, _m, _k, _sp, _id))
                await self.db.write_transaction(
                    _body, op_name="direct_fact_attribution")
                await provenance.record_fact_provenance(
                    self.db, fact_id=fid, chat_id=chat_id,
                    origin=row["origin"], target_user=new_target,
                    subject=subject, assertion_kind=kind,
                    attribution_method=method, speaker_author_id=speaker_uid,
                    provenance_channel="live",
                    tg_message_id=(row["tg_message_id"]
                                   if row["tg_message_id"] is not None
                                   else tg_message_id))
            except Exception:
                logger.warning(
                    "direct: fact attribution UPDATE failed — fact stays | "
                    "fact_id=%s", fid, exc_info=True)

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
                # MCA-01 §5.1 (T-3736): запись в общую connection идёт через
                # согласованный single-writer-механизм (write_transaction),
                # а не прямым `execute + commit`.
                async def _body(conn, _id=row["id"], _owner=owner):
                    await conn.execute(
                        "UPDATE graph_facts SET target_user = ? WHERE id = ?",
                        (_owner, _id))
                    return True
                await self.db.write_transaction(
                    _body, op_name="direct_fact_owner_reassign")
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

    def _apply_context_budget(self, blocks: list[tuple[str, str]],
                              enabled=None, budget_tokens=None, *,
                              external_tokens: int | None = None,
                              reserve_tokens: int = 0,
                              estimation_method: str | None = None,
                              excluded_categories: list | None = None,
                              out_excluded: list | None = None
                              ) -> list[str]:
        """Доли CHAT_CONTEXT_BUDGET_TOKENS (Раунд 8, B2/D2/T-791/T-799,
        spec §3.B2): map/rag/global/thread/anchors + новая доля branch (0.03)
        — от effective_budget = max(1, budget − fixed_tokens), где fixed =
        неприкосновенные kinds: target, protected, lore, current, sandwich,
        relations (раунд 9, T-819: relations в uncuttable — spec §3.1.4/Q3;
        защита от раздувания — кап limits.relations_inject_max_chars ДО
        инжекта) (вне per-block лимитов и вне порядка урезания). mood делит
        долю target на той же effective-базе (как раньше) и в общем цикле не
        участвует. Порядок урезания при превышении ОБЩЕГО бюджета (новая
        важность, D2/E1): Style_Anchors → RAG → Thread → Global(keep-head:
        конспект-голова держится, режется конец) → Map → Nostalgia-маркер
        (E1/T-826: участвует последним — маленький фикс-кап до инжекта).
        Выключено → ровно старые потолки секций (64.7).
        Раунд 10.4 (B-2): enabled=None → hot.get (старое поведение, тесты);
        caller передаёт per-chat резолв из get_chat_param (async-точка).

        MCA-07 (T-3849, ADR-1027-7 D7): при `MCA_ADAPTIVE_CONTEXT_BUDGET_
        ENABLED` ON и переданном `external_tokens` учитывается ПОЛНЫЙ payload
        (system/developer/personality + tools schemas + tool results + overhead
        = `external_tokens`; output reserve = `reserve_tokens`): бюджет под
        user-блоки = cap − external − reserve; pre-flight фиксирует заведомое
        переполнение обязательной части (`context_overflow`/`budget_exceeded`);
        логируются размер/резерв/исключённые категории/метод. OFF или
        `external_tokens=None` → прежняя числовая база (паритет baseline)."""
        # T-619: бюджеты — горячие точки (фолбек settings)
        # F4 (10.19, ADR-1019-4 D3): sentinel общего бюджета. `-1` = безлимит →
        # агрегатное усечение НЕ применяется (per-block потолки уже отработали в
        # `_build_global_context`/`_render_thread`); `0`/None = «не задано» →
        # глобальный дефолт (16000); `>0` = cap.
        raw_budget = budget_tokens if budget_tokens is not None else hot.get(
            "limits.chat_context_budget_tokens",
            settings.CHAT_CONTEXT_BUDGET_TOKENS)
        bstate = context_state(raw_budget)
        if bstate == "unlimited":
            total = sum(count_tokens(text) for _, text in blocks)
            # D-7: безлимит → limit=None + флаг unlimited, иначе виджет
            # показывал 100% (used/limit = total/total).
            record_context_usage(total, None, False, unlimited=True)
            logger.debug(
                "direct: context budget unlimited (-1) — aggregate truncation "
                "skipped | tokens=%d", total)
            return [text for _, text in blocks]
        budget = (int(raw_budget) if bstate == "cap"
                  else int(settings.CHAT_CONTEXT_BUDGET_TOKENS))
        if enabled is None:
            enabled = hot.get("flags.chat_context_budgets_enabled",
                              settings.CHAT_CONTEXT_BUDGETS_ENABLED)
        if not enabled:
            # F5/§3.6: бюджеты выключены — всё равно фиксируем оценку
            # последнего контекста (used/cap/truncated=False) для дашборда.
            record_context_usage(
                sum(count_tokens(text) for _, text in blocks), budget, False)
            return [text for _, text in blocks]
        # MCA-07 D7: полный учёт payload (только при явно переданном
        # `external_tokens` — иначе прежняя числовая база, паритет).
        adaptive = mca_gates.adaptive_context_budget_enabled()
        budget_cap = budget
        external = max(0, int(external_tokens or 0))
        reserve = max(0, int(reserve_tokens or 0))
        count_external = external_tokens is not None
        if adaptive and count_external:
            budget = max(1, budget_cap - external - reserve)
        uncuttable = ("target", "relations", "protected", "lore", "current",
                      "sandwich")
        fixed_tokens = sum(count_tokens(text) for kind, text in blocks
                           if kind in uncuttable)
        effective = max(1, budget - fixed_tokens)
        if adaptive and count_external and \
                (fixed_tokens + external + reserve) > budget_cap:
            # Pre-flight: обязательная часть (fixed + external + reserve) уже
            # не влезает — заведомо переполненный запрос (сигнал на
            # дополнительный retrieval/суммирование/уточнение).
            _mca_rc.emit_stage_event(
                "budget", "failed", reason_code="context_overflow",
                level="WARN", input_tokens=fixed_tokens + external + reserve)
            logger.warning(
                "direct: context overflow (mandatory) | fixed=%d external=%d "
                "reserve=%d cap=%d — нужен доп. retrieval/суммирование/"
                "уточнение", fixed_tokens, external, reserve, budget_cap)

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
            # Раунд 9 (E1/T-826): маркер ностальгии — крошечная доля (блок
            # компактный по построению); участвует в общем урезании ПОСЛЕДНИМ.
            "nostalgia": max(1, int(effective * _NOSTALGIA_BUDGET_RATIO)),
        }
        # global-пол: под общим давлением global не опускается ниже своей доли
        # (D2.4: конспект-минимум, порядок жертв tail → L1(keep-head)).
        global_floor = limits["global"]
        did_truncate = False   # F5/§3.6: маркер «RAG/стиль урезаются»

        def truncate(kind: str, text: str) -> str:
            nonlocal did_truncate
            if text is None or kind not in limits or limits[kind] <= 0:
                return text
            truncated = self._truncate_block(text, limits[kind], kind=kind)
            if truncated != text:
                did_truncate = True
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
                did_truncate = True
                texts["mood"] = self._truncate_block(
                    texts["mood"], mood_limit, kind="mood")
                logger.warning(
                    "direct: budget truncation | block=mood | tokens=%d -> %d",
                    mood_before, count_tokens(texts["mood"]))
        for kind in ("map", "rag", "branch", "anchors"):
            if kind in texts:
                texts[kind] = truncate(kind, texts[kind])
        # F4 (10.19, ADR-1019-4 D1; фикс D-1): global/thread уже ограничены
        # своими per-block потолками в сборщиках (`_build_global_context`/
        # `_render_thread`). Агрегатный проход по долям НЕ должен резать их
        # «второй раз»: доля 0.30×(budget−fixed) может оказаться меньше
        # safe_budget(global_cap), но блок, собранный под свой потолок, обязан
        # влезать. Эти два блока участвуют только в цикле урезания — и только
        # при фактическом переполнении ОБЩЕГО бюджета (total > budget).

        total = sum(count_tokens(text) for text in texts.values())
        if total > budget:
            # Порядок урезания (сначала дешёвое), геометрическими шагами.
            # global режется keep-head (конспект держится) и не опускается
            # ниже своей доли (D2.4/E1); map — предпоследняя (карта
            # атрибуции); nostalgia — ПОСЛЕДНЯЯ (E1/T-826: маркер отдаётся
            # лишь когда всё остальное уже сжато).
            order = ("anchors", "rag", "thread", "global", "map",
                     "nostalgia")
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
                    did_truncate = True
                    total = sum(count_tokens(text)
                                for text in texts.values())
                    progress = True
                if not progress:
                    break
        # MCA-07 B-MCA07-2 (pre-flight degradation): обязательная часть
        # (fixed + external + reserve) не влезает даже после урезания — не
        # отправляем заведомо переполненный user-контекст: полностью сбрасываем
        # остаточные cuttable-блоки (сигнал `context_overflow` — выше).
        if adaptive and count_external and \
                (fixed_tokens + external + reserve) > budget_cap:
            for kind, _text in blocks:
                if kind not in uncuttable and texts.get(kind):
                    texts[kind] = ""
                    did_truncate = True
            total = sum(count_tokens(text) for text in texts.values())
        # F5/§3.6: телеметрия последнего контекста для дашборда (оценка).
        record_context_usage(total, budget, did_truncate)
        # MCA-07 D7/SC-12/SC-13: логировать фактический размер/резерв/
        # исключённые категории/метод/причину (R17-safe: только числа/коды).
        if adaptive and count_external:
            total_payload = total + external + reserve
            excluded = [str(c)[:40] for c in (excluded_categories or [])][:20]
            logger.info(
                "direct: full payload | total=%d (user=%d external=%d "
                "reserve=%d) | cap=%d | fixed=%d | method=%s | excluded=%s | "
                "truncated=%s", total_payload, total, external, reserve,
                budget_cap, fixed_tokens, estimation_method or "tiktoken",
                ",".join(excluded) or "-", did_truncate)
            _mca_rc.emit_stage_event(
                "budget", "success" if total_payload <= budget_cap else "failed",
                reason_code=(None if total_payload <= budget_cap
                             else "budget_exceeded"),
                input_tokens=total_payload, output_tokens=reserve,
                config_version=estimation_method)
        # MCA-07 (T-3852): блоки, целиком вытесненные бюджетом, попадают в
        # `excluded[]` EvidenceBundle с причиной (R17-safe: kind/числа).
        if out_excluded is not None and enabled:
            for kind, text in blocks:
                if not texts.get(kind):
                    try:
                        est = count_tokens(text)
                    except Exception:      # pragma: no cover - защитная ветка
                        est = 0
                    out_excluded.append(
                        {"kind": kind, "reason_code": "budget_exceeded",
                         "estimated_tokens": est})
        return [texts[kind] for kind, _ in blocks if texts[kind]]

    def _truncate_block(self, block: str, limit_tokens: int,
                        kind: str = "") -> str:
        """66.12 + MCA-07 (T-3849, D7): обрезка блока по токенам с сохранением
        ОТКРЫВАЮЩЕГО/закрывающего тегов.

        ON `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` и наличии protected spans
        (отрицание/ID/дата), которые иначе были бы отрезаны, — резервируем
        бюджет и переносим их в защищённый хвост (смысл не меняется). OFF или
        отсутствие spans — байт-в-байт прежнее поведение (`_truncate_block_raw`)."""
        if (mca_gates.adaptive_context_budget_enabled() and limit_tokens > 0
                and isinstance(block, str) and has_protected_spans(block)
                and count_tokens(block) > limit_tokens):
            reserve = _PROTECTED_SPAN_RESERVE_BUDGET
            base = self._truncate_block_raw(
                block, max(1, limit_tokens - reserve), kind)
            return append_protected_spans(base, block, limit_tokens)
        return self._truncate_block_raw(block, limit_tokens, kind)

    def _truncate_block_raw(self, block: str, limit_tokens: int,
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
            # БЛОК 7.3a (T-1923): header-safe усечение тела — ведущий
            # `[Дата Время | Автор | ID | Переслано]:` неприкосновенен
            # (global/thread/rag/…: режется только body).
            return opening + truncate_keep_header(
                body, inner_budget, kind=kind) + closing
        return truncate_keep_header(text, limit_tokens, kind=kind)

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
        record_lore_inject()   # F5/§3.2: ts инжекта лора для виджета
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
            # F8 (spec §6): при активном фильтре — мемы чата (status chat_meme)
            # отдельным блоком; при OFF list_chat_memes не вызывается.
            irony_on = bool(hot.get("flags.irony_filter_enabled",
                                    settings.IRONY_FILTER_ENABLED))
            memes = (await self.db.list_chat_memes(
                chat_id, canon, limit=_PERSONA_MAX_ITEMS) if irony_on else [])
            # F1 (spec §3.2.1): сгенерированный портрет Слоя Б (производная
            # graph_facts.status='dossier_portrait'). Отдельный try — сбой
            # чтения портрета НЕ ломает карточку (fail-open).
            try:
                generated = await self.db.get_generated_dossier(chat_id, canon)
            except Exception:
                generated = None
        except Exception:
            logger.warning("direct: persona card read failed | chat=%s name=%s",
                           chat_id, name, exc_info=True)
            return None
        generated_block = _format_generated_portrait_block(generated)
        facts = card["facts"]
        links = card["links"]
        lore_lines = [lore_inner] if lore_inner else []
        if not irony_on:
            # Поведение 10.12 БАЙТ-В-БАЙТ (spec §6/§9): плоский список.
            n = len(facts) + len(protected) + len(lore_lines)
            m = len(links)
            lines = lore_lines + list(protected) + list(facts)
            lines += [f"{link['source_name']} ({link['relation_type']}) "
                      f"{link['target_name']}" for link in links]
            lines = lines[:_PERSONA_MAX_ITEMS]
            if n == 0 and m == 0 and not generated_block:
                return None
            body = "\n".join(f"{i}. {text}" for i, text in enumerate(lines, 1))
            if generated_block:
                body = f"{body}\n{generated_block}" if body else generated_block
            return f"карточка: {canon}\nзнаю о тебе: {n} фактов, {m} связей\n{body}"
        # F8: досье двумя блоками — [Факты] и [Локальные мемы/Ярлыки].
        fact_lines = (lore_lines + list(protected) + list(facts))[
            :_PERSONA_MAX_ITEMS]
        meme_lines = [str(item.get("fact") if isinstance(item, dict) else item)
                      for item in (memes or [])]
        meme_lines = [t for t in meme_lines if t.strip()][:_PERSONA_MAX_ITEMS]
        n = len(fact_lines)
        m = len(links)
        if not fact_lines and not meme_lines and not links and not generated_block:
            return None
        body_parts = []
        dossier = format_dossier_block(fact_lines, meme_lines,
                                       _PERSONA_DOSSIER_MAX_CHARS)
        if dossier:
            body_parts.append(dossier)
        if links:
            body_parts.append("\n".join(
                f"{i}. {link['source_name']} ({link['relation_type']}) "
                f"{link['target_name']}" for i, link in enumerate(links, 1)))
        if generated_block:
            body_parts.append(generated_block)
        body = "\n".join(body_parts)
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
            hours = int(await _cp_g(
                chat_id, "limits.chat_map_participants_hours",
                hot.get("limits.chat_map_participants_hours",
                        settings.CHAT_MAP_PARTICIPANTS_HOURS)) or 24) or 24
            cap = int(await _cp_g(
                chat_id, "limits.chat_map_participants_cap",
                hot.get("limits.chat_map_participants_cap",
                        settings.CHAT_MAP_PARTICIPANTS_CAP)) or 0) or 150
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
                               global_ctx: str) -> tuple[str, str]:
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
            test_empty_rag_section_omitted).
        Раунд 9 (E1/T-826, spec §3.5.1): возвращает (rag_block, nostalgia_hint)
        — hint «золотых» считается ПОСЛЕ F2-дедупа и F4-реранка, ДО рендера
        (передаётся в user-контент блоком kind "nostalgia" ПОСЛЕ relations/
        до mood); гейты: флаг memory.nostalgia_layer_a_enabled, чат группой
        (chat_id < 0, D-12), query есть, kept непуст.
        Раунд 10.14 (F1, ADR-1014-2 D5/D7): include_self=True — свои прошлые
        слова участвуют; если среди kept есть self, первой строкой внутрь
        <RAG_Memory> добавляется _SELF_ECHO_INSTRUCTION (канон промпта direct
        не меняется → PREV/PROMPT_MIGRATIONS не нужны)."""
        if not hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
            return "", ""
        query = getattr(message, "text", None) or ""
        try:
            facts = await self.memory.get_rag_facts(
                chat_id, query, include_direct_reply=True, include_self=True)
        except Exception:
            logger.warning("direct: rag facts failed — no rag block | chat=%s",
                           chat_id, exc_info=True)
            return "", ""
        if not facts:
            return "", ""
        # F2: дубли конспекта/verbatim-хвоста фона из RAG-блока исключаются
        # (никогда не бросает — fail-open внутри).
        kept = dedup_rag_vs_global(facts, global_ctx)
        if not kept:
            return "", ""
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
            return "", ""
        # F2/T-1429 (spec §4.4, 4.1.c): граф-активация — при частой связке
        # 2–3 узлов в L1 связанные архивные beliefs поднимаются в горячий
        # кэш БЕЗ dig_into_lore (только показ). Флаг off → [] (0 изменений);
        # fail-open: ошибка/нет метода → без инжекта.
        try:
            activation = getattr(self.memory, "graph_activation_facts", None)
            if callable(activation):
                extra = await activation(chat_id)
                if extra:
                    seen = {str(f[1]) for f in kept}
                    kept = list(kept) + [f for f in extra
                                         if str(f[1]) not in seen]
        except Exception:
            logger.warning(
                "direct: graph activation failed — no inject | chat=%s",
                chat_id, exc_info=True)
        # E1: «золотой» маркер — после отбора, ДО рендера (0 LLM-вызовов).
        hint = ""
        if query and chat_id < 0 and hot.get(
                "memory.nostalgia_layer_a_enabled",
                settings.NOSTALGIA_LAYER_A_ENABLED):
            hint = await self._build_nostalgia_hint(chat_id, query, kept)
        # F3: единый формат строки с origin-меткой; дата — внутри факта.
        # 10.20 (БЛОК 2.6, ADR-1020-2 п.1): ASC-хронология ПОСЛЕ дедупа/реранка/
        # граф-активации, ПЕРЕД рендером (состав top-K не меняется).
        content = build_rag_context(order_rag_facts_asc(kept), origin_labels=True)
        if not content:
            return "", ""
        # F1/T-1482 (ADR-1014-2 D5): анти-эхо — только когда в блоке есть
        # собственные прошлые слова бота (origin='bot_self_reply').
        # L4-фикс: инструкция добавляется ДО расчёта cap, иначе итоговый
        # <RAG_Memory> превышал limits.graph_rag_context_max_chars.
        if any(str(item[0]) == "bot_self_reply" for item in kept):
            content = f"{_SELF_ECHO_INSTRUCTION}\n{content}"
        # R10.4-7 (F5 round1014, T-1518): cap — per-chat override (get_chat_param
        # → hot.get → default), иначе сохранённое для чата значение в direct-пути
        # игнорировалось. Зеркалит summary_memory.get_rag_context (_chat_limit).
        cap = int(await _cp_g(
            chat_id, "limits.graph_rag_context_max_chars",
            hot.get("limits.graph_rag_context_max_chars",
                    settings.GRAPH_RAG_CONTEXT_MAX_CHARS)) or 0)
        if cap and len(content) > cap:
            logger.warning("direct: rag context truncated to %d chars | chat=%s",
                           cap, chat_id)
            content = content[:cap]
        logger.info("direct: rag block | facts=%d | chat=%s", len(kept), chat_id)
        return f"<RAG_Memory>\n{content}\n</RAG_Memory>", hint

    # ── Раунд 9 (AGI Memory, E1/T-826, spec §3.5.1): маркер «золотых» ──

    async def _build_nostalgia_hint(self, chat_id: int, query: str,
                                    kept: list) -> str:
        """Строка-маркер слоя A (spec §3.5.1): «золотой» факт чата по теме
        запроса (fetch_golden_facts: kind='fact', importance ≥
        nostalgia_golden_min_importance, давность ≥ nostalgia_golden_min_days
        по COALESCE(message_timestamp, created_at), FTS-матч). Факт уже в
        `kept` (RAG-блоке) — маркера нет (нет нового сигнала). Максимум
        nostalgia_layer_a_max_hints (1); фикс-кап nostalgia_hint_max_chars
        (300) — внутри format_nostalgia_hint ДО инжекта. 0 добавочных
        LLM-вызовов; ошибка/пусто → "" (WARNING, диалог жив — NFR-4)."""
        try:
            golden = await self.memory.fetch_golden_facts(
                chat_id, query,
                min_importance=int(hot.get(
                    "memory.nostalgia_golden_min_importance",
                    settings.NOSTALGIA_GOLDEN_MIN_IMPORTANCE) or 0),
                min_age_days=int(hot.get(
                    "memory.nostalgia_golden_min_days",
                    settings.NOSTALGIA_GOLDEN_MIN_DAYS) or 0),
                limit=max(1, int(hot.get(
                    "memory.nostalgia_layer_a_max_hints",
                    settings.NOSTALGIA_LAYER_A_MAX_HINTS) or 1)))
        except Exception:
            logger.warning(
                "direct: nostalgia hint failed — no hint | chat=%s",
                chat_id, exc_info=True)
            return ""
        if not golden:
            return ""
        cap = int(hot.get("memory.nostalgia_hint_max_chars",
                          settings.NOSTALGIA_HINT_MAX_CHARS) or 0) or 300
        kept_texts = {str(f[1]).strip().casefold() for f in (kept or [])
                      if len(f) > 1}
        for row in golden:
            text = str(row.get("fact") or "").strip()
            if not text:
                continue
            if text.casefold() in kept_texts:
                continue
            return format_nostalgia_hint(
                text, row.get("rag_ts") or row.get("created_at"), cap)
        return ""

    # ── <Global_Context> (Раунд 8: D2/T-799 keep-head + E1/T-803 importance,
    #    D5/T-802 метки-строки, C1/T-792 uid-рендеры) ────────────

    async def _build_global_context(self, chat_id: int, window: list,
                                    roster: list | None = None,
                                    suffix_map: dict[int, str] | None = None,
                                    trigger_message_id=None,
                                    truncate: bool = True) -> str:
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
        # F-14 (S2, spec §4.2): гейт через chat_summary_enabled — ЛС не
        # наследует глобальный ON (саммари в ЛС по умолчанию OFF).
        if await chat_summary_enabled(chat_id):
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
                            cap2 = int(await _cp_g(
                                chat_id, "limits.chat_level2_max_chars",
                                hot.get("limits.chat_level2_max_chars",
                                        settings.CHAT_LEVEL2_MAX_CHARS)) or 0)
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
                tail.append(self._context_row_line(
                    row, suffix_map, trigger_message_id=trigger_message_id))
        else:
            _g_limit = int(await _cp_g(
                chat_id, "limits.chat_global_context_limit",
                hot.get("limits.chat_global_context_limit",
                        settings.CHAT_GLOBAL_CONTEXT_LIMIT)) or 0)
            recent = window[-max(1, _g_limit):]
            for row in recent:
                text = row["text"] or ""
                if not text:
                    continue
                tail.append(self._context_row_line(
                    row, suffix_map, trigger_message_id=trigger_message_id))
            if not tail:
                return ""
            # D5: метка verbatim-режима — по отобранной ветке окна
            # (n = число строк после среза recent-ветки).
            head.append(f"фон: дословно последние {len(tail)} сообщений")
        kind, limit = resolve_chat_limit(
            await _cp_g(chat_id, "limits.chat_global_context_max_tokens",
                        hot.get("limits.chat_global_context_max_tokens",
                                settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS)),
            int(settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS or 5000),
            "CHAT_GLOBAL_CONTEXT_MAX_CHARS",
            await _cp_g(chat_id, "limits.chat_global_context_max_chars",
                        hot.get("limits.chat_global_context_max_chars",
                                settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS)),
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
        # ASAP-3 (ADR-1028-2 D3): композер вызывает билдер с truncate=False —
        # полный кандидат без self-усечения и без WARN `truncated`
        # (единственная точка распределения бюджета — композер).
        if truncate and measure("\n".join(head + tail)) > budget:
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

    def _context_row_line(self, row, suffix_map: dict[int, str],
                          trigger_message_id=None) -> str:
        """10.20 (БЛОК 0, ADR-1020-1 ред. 3, точка 2): каноническая строка
        сообщения окна (ярус A) — ts/автор/ID/forward из smart_messages-row;
        отсутствующие в источнике поля опускаются (R16, не выдумываем).
        10.23 (F1): совпавший с триггером ``tg_message_id`` получает маркер."""
        name, uid = self._row_speaker(row)
        author = _speaker_tag(name, uid, suffix=suffix_map.get(uid, ""))
        forward_source = (row_get(row, "forward_source")
                          if row_get(row, "is_forward") else None)
        return format_context_item(
            ts=row_get(row, "timestamp"), author=author,
            item_id=resolve_item_id(
                tg_message_id=row_get(row, "tg_message_id"),
                message_id=row_get(row, "id")),
            forward_source=forward_source, text=row_get(row, "text") or "",
            kind="msg",
            is_target=is_target_row(row, trigger_message_id))

    # ── <Conversation_Thread> / <Conversation_Branch> (Раунд 8: D3/T-800,
    #    D4/T-801 — цепочка сквозь бот-ответы, итог ветки без LLM) ──

    async def _collect_thread_chain(self, chat_id: int, message,
                                    depth: int | None = None) -> list:
        """Рекурсивная цепочка reply по tg_message_id (глубина
        CHAT_THREAD_MAX_DEPTH). Раунд 10.23 (F2, ADR-1023-2): реализация
        вынесена в общий ``services/thread_chain.py`` (паритет с фактчеком);
        здесь остаётся только per-chat резолв глубины и alias-резолвер имени.
        Возвращает ``[thread_chain.ChainItem]`` от ТЕКУЩЕГО к корню.
        ASAP-3 (ADR-1028-2 D7): композер передаёт ``depth=CHAT_THREAD_WALK_MAX``
        (walk до корня, hard-cap 40, cycle-safe) — рендер ограничивается
        бюджетом P1; per-chat глубина остаётся минимальной гарантией."""
        if depth is None:
            _depth = await _cp_g(chat_id, "limits.chat_thread_max_depth",
                                 hot.get("limits.chat_thread_max_depth",
                                         settings.CHAT_THREAD_MAX_DEPTH))
        else:
            _depth = depth
        return await thread_chain.collect_thread_chain(
            self.db, chat_id, message, int(_depth or 0),
            row_speaker=self._row_speaker,
            bot_name_resolver=self._resolve_bot_name,
            bot_reply_getter=self.get_bot_reply,
            bot_parent_getter=self._bot_reply_parent)

    def _chain_line(self, item, suffix_map: dict[int, str],
                    trigger_message_id=None) -> str:
        """10.20 (БЛОК 0, точка 3): каноническая строка хода цепочки (ярус A).
        F2 (10.23): делегат ``thread_chain.format_chain_line`` (единый рендер
        с фактчеком); F1: ход-триггер получает маркер."""
        return thread_chain.format_chain_line(
            item, suffix_map, trigger_message_id)

    async def _thread_limit(self, chat_id: int):
        """Раунд 10.4 (G-ремедиация): per-chat лимит треда (tokens/chars) —
        resolve_chat_limit-кортеж; без override — байт-в-байт старое."""
        kind, limit = resolve_chat_limit(
            await _cp_g(chat_id, "limits.chat_thread_max_tokens",
                        hot.get("limits.chat_thread_max_tokens",
                                settings.CHAT_THREAD_MAX_TOKENS)),
            int(settings.CHAT_THREAD_MAX_TOKENS or 3000),
            "CHAT_THREAD_MAX_CHARS",
            await _cp_g(chat_id, "limits.chat_thread_max_chars",
                        hot.get("limits.chat_thread_max_chars",
                                settings.CHAT_THREAD_MAX_CHARS)),
            "CHAT_THREAD",
        )
        return kind, limit

    def _render_thread(self, chain: list, suffix_map: dict[int, str],
                       thread_limit=None, trigger_message_id=None,
                       truncate: bool = True) -> str:
        """Рендер полной цепочки сверху-вниз (лимиты 64.7, keep-end —
        verbatim-диалог не участвует в importance-удержании E1).
        10.23 (F1): ход-триггер получает маркер.
        ASAP-3 (ADR-1028-2 D3/D7): композер вызывает с truncate=False —
        полный кандидат (walk ≤ CHAT_THREAD_WALK_MAX), усечение — композером
        (keep-end, без WARN `truncated`)."""
        if not chain:
            return ""
        lines = [self._chain_line(item, suffix_map, trigger_message_id)
                 for item in reversed(chain)]
        body = "\n".join(lines)
        if not truncate:
            return (f"<Conversation_Thread>\n"
                    f"{escape_xml_text(body)}\n</Conversation_Thread>")
        if thread_limit is not None:
            kind, limit = thread_limit
        else:
            kind, limit = resolve_chat_limit(
                hot.get("limits.chat_thread_max_tokens",
                        settings.CHAT_THREAD_MAX_TOKENS),
                int(settings.CHAT_THREAD_MAX_TOKENS or 3000),
                "CHAT_THREAD_MAX_CHARS",
                hot.get("limits.chat_thread_max_chars",
                        settings.CHAT_THREAD_MAX_CHARS),
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

    def _render_branch(self, chain: list, suffix_map: dict[int, str],
                       trigger_message_id=None) -> str:
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
        lines = [self._chain_line(item, suffix_map, trigger_message_id)
                 for item in fresh]
        body = "\n".join(lines)
        return (f"<Conversation_Branch>\n"
                f"{escape_xml_text(body)}\n</Conversation_Branch>")

    async def _build_conversation_thread(self, chat_id: int, message) -> str:
        """Публичная сборка <Conversation_Thread> (58.6): цепочка reply от
        текущего сообщения (D3: сквозь бот-ответы по bot_reply_parents)."""
        chain = await self._collect_thread_chain(chat_id, message)
        return self._render_thread(chain, {}, await self._thread_limit(chat_id))

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