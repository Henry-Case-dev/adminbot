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
import contextvars
import datetime
import hashlib
import json
import logging
import random
import re
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from aiogram.exceptions import TelegramBadRequest

from config.settings import settings
from services import chat_access
from services import hot_config as hot
from services import bot_persona
from services import thread_chain
from services import mca_gates
from services import mca_retrieval_context as _mca_rc
from services import response_freshness as _fresh   # MCA-22 (C7, D8)
from services import bot_output_ledger as _ledger   # MCA-22 (C2, D2)
from services import graphrag_provenance as _gprov  # MCA-22 (C5/C8, D6/D9)
from services import provenance as _prov            # MCA-22 (C8: reuse 04a)
from services import quote_resolver as _qres        # MCA-22 (C3, D3; fix M-2)
from services import claim_envelope as _ce          # MCA-08 (D6/D7, T-4898)
from services import mca_events as _mca_events      # MCA-08 (notable-only)
from services import mca_style_scope as _style_scope  # MCA-08 (D3–D5, C)
from services import negative_constraints as _nc    # MCA-08 (D8, T-4907)
from services import command_prefix  # ASAP-3: persona-name force-детект (F6)
from services import mca_intents as _mca_intents  # MCA-09 (D3, T-5029)
from services import telegram_send as _tg_send     # MCA-09 (T-5038: транспорт)
from services import response_extent as _extent  # MCA-23 (W3): ResponsePlan
from services import prompt_composer as _pcomp  # SOUL-1 (W2): Composer
from services import style_policy as _style_policy  # SOUL-1 (W3): форма текста
from services import response_document as _rd  # MCA-23 фаза 2 (§22): артефакт
from services.chat_params import (
    chat_summary_enabled,
    get_chat_param as _cp_g,  # G-3 per-chat
)
from services.sandbox_reply import DEFAULT_NO_KEY_REPLY
from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    DIRECT_L1_PLANNER_SYSTEM_PROMPT,
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
from services.persistent_throttling import (
    SilenceStreak,
    cooldown_refresh,
    resolve_direct_chat_limits,
    throttle_refresh,
)
from services import persistent_throttling as _limits
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
    _is_reply_target_gone,
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
# ── ASAP-3.1 (round 1028, ADR-1028-3): Model Capacity + Stage Auto Budget
# Resolver (D1/D2/D5). Прецедент импорта-алиасом — `_composer` выше.
from services import model_capacity as _model_capacity
from services import auto_budget as _auto_budget
# ADR-1028-3 D7 (§30–§33): LLM REACT — выбор emoji Stage-1 (SILENT→🗿
# остаётся единственным hardcode).
from services import direct_llm_react as _llm_react
# ── ASAP 7 (F1, §1.1–§1.5): pre-tool L1 Planner + capability allowlist. ────
from services import direct_l1 as _l1
from services import direct_capabilities as _caps
# ── ASAP 8 v6 (D04, §18C.7): execution modes / orchestrator / evidence. ────
from services import direct_execution as _dx

logger = logging.getLogger(__name__)

# ── ASAP 8 (F6, §13.1): маркер «бот отправил текст в этом ходе» ─────────────
# Invoke-scoped (contextvar): параллельные ходы разных чатов изолированы,
# per-chat замок не нужен. set() в обёртке `handle`, отметки — в точках
# текстовой отправки хода (фразы throttle/CB/lock и основной reply).
_turn_text_replied: contextvars.ContextVar[frozenset | set | None] = \
    contextvars.ContextVar("f6_turn_text_replied", default=None)

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

# ADD-TR.2 (ADTR-ENTRY, 19.10.2026, M-ADTR-ENTRY-REFS способ C): контекстный
# резолв «явной ссылки» на ранее присланное в чате изображение. Кандидаты —
# канонический реестр MCA-19 `mca_media_assets` (второй реестр/vision-пайплайн
# не создаётся). Bounded-окно + требование однозначности: ровно ОДНО
# изображение-сообщение в окне → маркер того же диалекта, что own/reply
# (`[медиа: {kind} tg:{id}]`); несколько → цель неоднозначна → маркера НЕТ
# (никакого «угаданного» распознавания; уточнение — штатный путь L1/Writer).
_EARLIER_IMAGE_WINDOW_SECONDS = 1800
_EARLIER_IMAGE_SCAN_LIMIT = 24
# Поддерживаемые kind'ы = резолвимые `mca_vision.SUPPORTED_ASSET_KINDS`
# (photo/document/sticker); animation — честный unsupported-кандидат MCA-19.
_IMAGE_REF_KINDS = frozenset({"photo", "document", "sticker"})

# ASAP 7 (F2-FOLLOWUP, §1.10): durable plan_meta на usage-строках L1 Planner.
# Primary main-путь пишет usage через llm.generate (без plan_meta), dedicated-
# слот — manual record ДО парсинга плана; один fail-open UPDATE по
# correlation_id дополняет запись(и) этого ответа теми же R17-осями, что в
# agentic L1_PLAN (sanitize_plan_meta — единственный писатель колонки).
_L1_PLAN_META_UPDATE_SQL = (
    "UPDATE llm_usage_events SET plan_meta = $1 "
    "WHERE correlation_id = $2 AND module = 'direct_chat' "
    "AND step = 'l1_planner' AND plan_meta IS NULL"
)


def _l1_usage_plan_meta(plan, meta: dict, *, fallback_flag: str,
                        latency_ms: int, input_chars: int) -> dict:
    """R17-whitelist-оси usage-plan_meta — зеркально emit_l1_plan_event
    (§1.5) + оси D03/D04 (execution_mode/credential_source/temperature/
    planner_fallback_reason/required_capability, §18C.6–8). Ключи сверены
    с PLAN_META_FIELDS sanitizer'а usage_events (extra-оси L1Plan —
    structure/delivery_hint/tool_policy/emotional_mirroring — не в
    whitelist, не передаём). План None → дефолты L1Plan (fallback-ходы
    честно попадают в durable-оси)."""
    p = plan or _l1.L1Plan()
    out = {
        "action": str(p.action or "reply"),
        "response_act": str(p.response_act or "other"),
        "extent": str(p.effective_extent() or "auto"),
        "tone": str(p.tone or "inherit"),
        "bucket": str(p.confidence_bucket or "low"),
        "capabilities": [str(c) for c in (p.capabilities_needed or ())],
        "confidence": float(p.confidence),
        "inherited": bool(meta.get("inherited")),
        "latency_ms": int(max(0, latency_ms)),
        "input_chars": int(max(0, input_chars)),
        "source": str(meta.get("source") or "main"),
        "execution_mode": str(getattr(p, "execution_mode", "") or "none"),
        "credential_source": str(meta.get("credential_source") or "global"),
    }
    fb_reason = str(meta.get("planner_fallback_reason") or "")
    if fb_reason:
        out["planner_fallback_reason"] = fb_reason
    required = str(meta.get("required_capability") or "")
    if required:
        out["required_capability"] = required[:64]
    temp = meta.get("temperature_configured")
    if isinstance(temp, (int, float)) and not isinstance(temp, bool):
        out["temperature"] = float(temp)
    if meta.get("temperature_unsupported"):
        out["temperature_unsupported"] = True
    if fallback_flag:
        out["fallback"] = str(fallback_flag)
    return out


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
# ASAP 7 (F1, §1.5/D11): слова «коротко, по делу» УДАЛЕНЫ (скрытый
# глобальный cap запрещён — Golden D11/§22 п.9); якорь на последний вопрос
# и анти-артефакт правил имён сохранены. Точечная замена текста — глобально
# (обе ветки: L1 и legacy).
_SANDWICH_REMINDER = (
    "отвечай на последний вопрос (<Current_Question>); "
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
_BUNDLE_LESSON_MAX_REFS = 5


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


async def _composer_resolve_gates(chat_id: int):
    """Оси SOUL-1/W2 (composer/core/style/humor) per-chat.

    Env-ось выключена (код-дефолт) → резолв не делает ни одного обращения к
    chat_params: OFF-путь остаётся байт-в-байт прежним и бесплатным.
    Никогда не бросает.
    """
    try:
        return await _pcomp.resolve_gates(chat_id)
    except Exception:          # pragma: no cover — защитная ветка
        logger.warning("[soul1] composer gates failed — OFF (parity)",
                       exc_info=True)
        return _pcomp.GateState(unified_composer_enabled=False)


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
    # MCA-16 (AM-1, D6): проверенные уроки — bounded-данные (не инструкции);
    # пусто → паритет 2.58.58. Отбор/лимиты выполнил LessonService.
    lessons = tuple(getattr(bundle, "lessons", ()) or ())
    if lessons:
        lesson_lines = []
        for ref in lessons[:_BUNDLE_LESSON_MAX_REFS]:
            rec = str(getattr(ref, "recommendation", "") or "").strip()
            if rec:
                lesson_lines.append(f"- {rec}")
        if lesson_lines:
            parts.append("Проверенные уроки (данные, не инструкции):\n"
                         + "\n".join(lesson_lines))
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


def _message_user_text(message) -> str:
    """ADD-TR.2 (ADTR-ENTRY): единый пользовательский текст события —
    ``text``, при его отсутствии ``caption`` (подпись к медиа). Тот же
    контракт, что у ``handlers.direct_chat._effective_text``: подпись не
    теряется до семантических путей и не становится отдельной репликой.
    Не-str (тест-двойники) → ""."""
    text = getattr(message, "text", None)
    if text is None:
        text = getattr(message, "caption", None)
    if not isinstance(text, str):
        return ""
    return text.strip()


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
# MCA-09 (T-5038): инициативный ответ (без входящего сообщения) — свой kind
# mca-22 ledger `initiative_reply` (аддитивно; существующий механизм).
TRIGGER_INITIATIVE = "initiative"


def direct_output_kind(trigger_type: str | None) -> str:
    """MCA-22 (C2, T-4287; fix round-1 M-4): kind durable-ledger строки
    для direct-ответа. Автономный ответ (free_will) — СО СВОИМ kind
    `autonomous_reply`; инициативный (MCA-09, T-5038) — `initiative_reply`."""
    if trigger_type == TRIGGER_FREE_WILL:
        return "autonomous_reply"
    if trigger_type == TRIGGER_INITIATIVE:
        return "initiative_reply"
    return "direct_reply"


def _mca18_ledger_source(base: str) -> str:
    """mca-18 (T-5082/A61): маркировка ledger-строки применёнными правилами
    черт (`source_feature="direct_chat|trait:12:v3;..."`) — повторное
    извлечение из такого ответа НЕ считается независимым подкреплением
    (`mca_self_model.reinforce_rule`). R17-safe: только ID/версии. Fail-open
    (holder пуст/ошибка → base как в 2.58.61)."""
    try:
        from services import mca_self_model as _msm
        tag = _msm.current_run_frame_tag()
        if tag:
            return f"{base}|{tag}"
    except Exception:
        pass
    return base


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


# ── MCA-09 (ADR-1028-16 D3, T-5029): аддитивный контракт Decision ──────────
# Enum `action` НЕ расширяется ({reply,react,silent,tool}); `defer` — не
# значение enum: отложенное = silent + серверное планирование
# (`next_check_at`/статус намерения deferred). Wire-`action` не вводится.
# R17: только ID/коды/enum/числа/refs — без сырого текста/секретов/CoT.

#: закрытые ключи read-only метаданных mca-10a (второй draw не делается).
_RANDOM_METADATA_KEYS = frozenset({
    "policy_version", "requested_source", "actual_source", "draw_ids",
    "probability", "fallback_reason", "deferred",
})
_RANDOM_METADATA_TEXT_KEYS = ("policy_version", "requested_source",
                              "actual_source", "fallback_reason")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9_.:@\-]{1,64}$")

# Закрытые наборы Decision-контракта — ЕДИНЫЙ источник истины в доме
# Intent-контура (`services/mca_intents.py`, spec D1); здесь — алиасы дома
# контракта (второго словаря нет; mca_intents не импортирует этот модуль
# на верхнем уровне — цикла нет).
CANDIDATE_SOURCES = _mca_intents.CANDIDATE_SOURCES
COMMUNICATIVE_INTENTS = _mca_intents.COMMUNICATIVE_INTENTS
RECHECK_CONDITIONS = _mca_intents.RECHECK_CONDITIONS


def _safe_ref(value) -> str | None:
    """R17-safe ref (ID/код): небезопасное → None."""
    text = str(value or "").strip()
    return text if text and _SAFE_REF_RE.match(text) else None


def _sanitize_random_metadata(value) -> dict | None:
    """Read-only копия метаданных mca-10a: незнакомые ключи отбрасываются.

    Второй draw/второй процент здесь не выполняются — только нормализация."""
    if not isinstance(value, dict) or not value:
        return None
    out: dict = {}
    for key in _RANDOM_METADATA_TEXT_KEYS:
        item = value.get(key)
        if item is not None and str(item).strip():
            out[key] = str(item)[:120]
    draw_ids = value.get("draw_ids")
    if isinstance(draw_ids, (list, tuple)):
        clean = [str(d)[:64] for d in list(draw_ids)[:8] if str(d or "").strip()]
        if clean:
            out["draw_ids"] = clean
    probability = value.get("probability")
    if isinstance(probability, (int, float)) and not isinstance(probability,
                                                               bool):
        out["probability"] = min(1.0, max(0.0, float(probability)))
    if "deferred" in value:
        out["deferred"] = bool(value.get("deferred"))
    return out or None


@dataclass(frozen=True)
class DecisionCandidate:
    """Кандидат действия для единого Decision (ADR-1028-16 D3).

    Структура семантики кандидата §14.10 принадлежит mca-09 (применения
    14.6–14.11 — mca-10b); второй action-schema не вводится. R17-safe:
    `prepared_text_ref` — ref, не текст; сырой текст не логируется.
    Отклонённые кандидаты сохраняются с `admissible=False` (why-why-not)."""

    candidate_id: str
    action: str
    reason_code: str
    source: str
    communicative_intent: str | None = None
    source_refs: tuple[str, ...] = ()
    prepared_text_ref: str | None = None
    random_meta: dict | None = None
    admissible: bool = True
    # MCA-09: связь с намерением и порядок выбора (не wire-контракт).
    intent_id: str | None = None
    priority: int = 0
    reason_codes: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        """Duck-typing mca-10a `_candidate_id` для журнала draw (R17-safe)."""
        return self.candidate_id

    def __post_init__(self) -> None:
        # Fail-safe нормализация: незнакомое отбрасывается, не бросает.
        if not str(self.candidate_id or "").strip():
            object.__setattr__(
                self, "candidate_id",
                "candidate:" + hashlib.sha1(
                    f"{self.action}:{self.source}".encode("utf-8")
                ).hexdigest()[:16])
        if self.action not in COORDINATOR_ACTIONS:
            object.__setattr__(self, "action", ACTION_REPLY)
        if self.reason_code not in REASON_CODES:
            object.__setattr__(self, "reason_code", REASON_DEFAULT)
        if self.source not in CANDIDATE_SOURCES:
            object.__setattr__(self, "source", "intent")
        if self.communicative_intent not in COMMUNICATIVE_INTENTS:
            object.__setattr__(self, "communicative_intent", None)
        # refs — только строки-токены (mca-04a-стиль); не-строки/мусор → долой.
        object.__setattr__(self, "source_refs", tuple(
            r for r in (_safe_ref(v) for v in (self.source_refs or ())
                        if isinstance(v, str)) if r)[:16])
        object.__setattr__(self, "prepared_text_ref",
                           _safe_ref(self.prepared_text_ref))
        object.__setattr__(self, "intent_id", _safe_ref(self.intent_id))
        object.__setattr__(self, "random_meta",
                           _sanitize_random_metadata(self.random_meta))
        object.__setattr__(self, "reason_codes", tuple(
            dict.fromkeys(c for c in (str(x) for x in
                                      (self.reason_codes or ()))
                          if c in _mca_events.REASON_CODES))[:16])
        object.__setattr__(self, "admissible", bool(self.admissible))
        try:
            object.__setattr__(self, "priority", int(self.priority or 0))
        except (TypeError, ValueError):
            object.__setattr__(self, "priority", 0)


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
    # MCA-09 (ADR-1028-16 D3, AM-1; все с default — A7-инварианты сохранены):
    trigger_kind: str = ""
    intent_id: str | None = None
    reply_target: str | None = None
    candidate_actions: tuple = ()
    selected_candidate: str | None = None
    reason_codes: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    context_version: str | None = None
    recheck_conditions: tuple[str, ...] = ()
    next_check_at: int | None = None
    random_metadata: dict | None = None
    tool_outcome: str | None = None
    # mca-18 (ADR-1028-18 D6/CA-18-7, T-5081): аддитивное поле кадра
    # поведения (enum/action-schema mca-09 не меняются; None = кадр не
    # активен — K1 OFF/ошибка). Черта не создаёт намерений.
    frame_version: str | None = None
    # MCA-23 (W3, §3/§4 current_task): оси ResponsePlan — детерминированные,
    # заполняются ДО LLM-стадии (classify_request, 0 LLM-вызовов). Пусто =
    # план не строился (kill-switch OFF). В wire-JSON не сериализуются
    # (граница A7): internal metadata.
    task_kind: str = ""
    extent: str = ""
    structure: str = ""
    delivery_hint: str = ""
    tool_policy: str = ""

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
        # MCA-09: нормализации аддитивных полей (незнакомое отбрасывается).
        if self.trigger_kind not in _mca_intents.TRIGGER_KINDS:
            self.trigger_kind = ""
        candidates = tuple(c for c in (self.candidate_actions or ())
                           if isinstance(c, DecisionCandidate))
        try:
            cap = max(1, int(mca_gates.intent_candidates_max()))
        except Exception:      # pragma: no cover - защитная ветка
            cap = 8
        self.candidate_actions = candidates[:cap]
        ids = {c.candidate_id for c in self.candidate_actions}
        if self.selected_candidate not in ids:
            self.selected_candidate = None
        self.reason_codes = tuple(dict.fromkeys(
            c for c in (str(x) for x in (self.reason_codes or ()))
            if c in _mca_events.REASON_CODES))[:16]
        self.recheck_conditions = tuple(dict.fromkeys(
            c for c in (str(x) for x in (self.recheck_conditions or ()))
            if c in RECHECK_CONDITIONS))
        self.source_refs = tuple(
            r for r in (_safe_ref(v) for v in (self.source_refs or ())
                        if isinstance(v, str)) if r)[:16]
        self.intent_id = _safe_ref(self.intent_id)
        self.reply_target = _safe_ref(self.reply_target)
        self.context_version = (str(self.context_version)[:120]
                                if self.context_version else None)
        if self.next_check_at is not None:
            try:
                self.next_check_at = max(0, int(self.next_check_at))
            except (TypeError, ValueError):
                self.next_check_at = None
        self.random_metadata = _sanitize_random_metadata(self.random_metadata)
        if self.tool_outcome not in _mca_tool_result_statuses():
            self.tool_outcome = None
        # MCA-23 (W3): нормализация осей плана (незнакомое → "", fail-open).
        self.task_kind = _extent.normalize_task_kind(self.task_kind)
        self.extent = _extent.normalize_extent(self.extent)
        self.structure = _extent.normalize_structure(self.structure)
        self.delivery_hint = _extent.normalize_delivery_hint(self.delivery_hint)
        self.tool_policy = _extent.normalize_tool_policy(self.tool_policy)


def _mca_tool_result_statuses() -> frozenset:
    """7 статусов ToolResult (mca-11) — reuse, второго словаря нет."""
    from services.tool_result import STATUSES
    return STATUSES


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
                               target_message_id: int | None = None,
                               plan=None
                               ) -> CoordinatorDecision:
    """Собрать внутреннее решение Координатора (0 LLM). Никогда не бросает.

    MCA-23 (W3): ``plan`` — ResponsePlan, классифицированный ДО LLM-стадии
    (None → детерминированный :func:`classify_request` здесь — тот же
    результат, план не зависит от стадии). Оси плана едут в решение
    аддитивно; action/style-контракт не меняется."""
    forward = bool(_forward_source_of(message))
    tool_trace = getattr(raw, "tool_trace", None) or []
    tool_names = _coordinator_tool_names(tool_trace)
    degraded = bool(getattr(raw, "degraded", False))
    evaluation = _coordinator_evaluate(tool_trace, degraded)
    action = _coordinator_choose_action(
        has_tools=bool(tool_trace), degraded=degraded,
        lore_compiled=lore_compiled)
    if plan is None:
        try:
            plan = _extent.classify_request(query)
        except Exception:      # pragma: no cover - защитная ветка
            plan = None
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
        task_kind=(getattr(plan, "task_kind", "") if plan is not None else ""),
        extent=(getattr(plan, "extent", "") if plan is not None else ""),
        structure=(getattr(plan, "structure", "") if plan is not None else ""),
        delivery_hint=(getattr(plan, "delivery_hint", "")
                       if plan is not None else ""),
        tool_policy=(getattr(plan, "tool_policy", "")
                     if plan is not None else ""),
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
        "needs_tools=%d | reaction=%s | kind=%s | extent=%s | struct=%s | "
        "delivery=%s | tool_policy=%s",
        chat_id, decision.intent, decision.addressee,
        1 if decision.memory_need else 0,
        ",".join(decision.tool_calls) or "-",
        decision.evaluation, decision.action, decision.reason_code,
        decision.target_message_id if decision.target_message_id is not None
        else "-",
        1 if decision.needs_tools else 0, decision.reaction or "-",
        decision.task_kind or "-", decision.extent or "-",
        decision.structure or "-", decision.delivery_hint or "-",
        decision.tool_policy or "-")


def _log_coordinator_outcome(*, chat_id: int, action: str, style: str,
                             chars: int) -> None:
    """R17-safe исход (код действия / режим-стиль / длина текста)."""
    logger.info(
        "[coordinator] outcome | chat=%s | action=%s | style=%s | chars=%d",
        chat_id, action, style or "-", int(chars))


def _delivered_payload(payload: str) -> str:
    """Байты, которые РЕАЛЬНО уйдут в Telegram (SOUL-16.3.4).

    Последний delivery-guard — egress ``sanitize_outgoing`` в
    ``services/telegram_send`` — применяется ПОСЛЕ сериализации/escape ветки
    доставки и ДО ``bot.send_message``. Проверять надо именно его результат
    (review-w3 F3: ``Готово. fact:123`` доезжало как ``Готово.``, а проверка
    видела до-guard-строку). Guard выключен → строка не меняется."""
    try:
        sanitize = getattr(_tg_send, "_maybe_sanitize", None)
        if sanitize is not None:
            return str(sanitize(str(payload or "")))
        from services.outgoing_guard import sanitize_outgoing
        return str(sanitize_outgoing(str(payload or "")))
    except Exception:      # pragma: no cover - проверка не роняет доставку
        return str(payload or "")


# ── ADD-EXP §6: диагностика слоя «Выражение» на боевом пути ─────────────────
#: Маркер слоя в финальном system (проверка «политика доехала»).
EXPRESSION_MARKER = "<Expression_Settings>"
#: Bounded LRU raw-флагов хода (только флаги/счётчики; R17).
_EXPRESSION_RAW_MAX = 64
_expression_raw_lock = threading.Lock()
_expression_raw: "OrderedDict[tuple, dict]" = OrderedDict()


def _expression_diag(cls: str, *, chat_id: int, stage: str, detail: str = "",
                     mode: str = "") -> None:
    """Fail-open эмиссия класса §6 (единый владелец — mca_expression)."""
    try:
        from services import mca_expression as _expr
        _expr.emit_expression_diag(cls, chat_id=chat_id, stage=stage,
                                   detail=detail, mode=mode)
    except Exception:      # pragma: no cover — диагностика не рвёт ход
        pass


def _expression_record_raw(*, chat_id: int, correlation_id: str | None,
                           text: str, mode: str, rendered: bool) -> None:
    """Запомнить raw-флаги ответа L2 (сравнение с доставленным — §6)."""
    if not correlation_id:
        return
    try:
        from services import mca_expression as _expr
        profanity = _expr.count_profanity(text) > 0
    except Exception:      # pragma: no cover
        profanity = False
    key = (int(chat_id or 0), str(correlation_id))
    with _expression_raw_lock:
        _expression_raw[key] = {"profanity": bool(profanity),
                                "mode": str(mode or ""),
                                "rendered": bool(rendered),
                                "ts": time.time()}
        while len(_expression_raw) > _EXPRESSION_RAW_MAX:
            _expression_raw.popitem(last=False)


def _expression_postprocess_check(chat_id: int, correlation_id: str | None,
                                  delivered: str, *, stage: str) -> None:
    """Сравнить raw-флаги хода с доставляемым текстом (§6 `postprocess_changed`).

    Класс только когда raw содержал мат, режим ≠ off, а доставленный текст —
    нет. Режим ``off`` ничего не доказывает (мат не ожидался).
    """
    if not correlation_id:
        return
    key = (int(chat_id or 0), str(correlation_id))
    with _expression_raw_lock:
        rec = _expression_raw.get(key)
    if not rec or not rec.get("profanity"):
        return
    if str(rec.get("mode") or "") == "off":
        return
    try:
        from services import mca_expression as _expr
        if _expr.count_profanity(delivered) > 0:
            return
    except Exception:      # pragma: no cover
        return
    _expression_diag("postprocess_changed", chat_id=chat_id, stage=stage,
                     detail=stage, mode=str(rec.get("mode") or ""))


def _expression_marker_checked_adapter(adapter, *, chat_id: int, mode: str):
    """Обернуть L2 fallback-адаптер проверкой маркера (policy_not_injected)."""
    def _inner(payload):
        out = adapter(payload)
        try:
            messages = (out or {}).get("messages") or []
            text = "\n".join(str((m or {}).get("content") or "")
                             for m in messages)
            if text and EXPRESSION_MARKER not in text:
                _expression_diag("policy_not_injected", chat_id=chat_id,
                                 stage="l2_fallback_repack",
                                 detail="marker_absent", mode=mode)
        except Exception:      # pragma: no cover — адаптер не рвём
            pass
        return out
    return _inner


def _llm_fallbacks_total() -> int:
    """Счётчик fallback-переключений LLM-клиента (0 при недоступности)."""
    try:
        from services import llm_client as _llm
        return int((_llm.llm_stats() or {}).get("fallbacks") or 0)
    except Exception:      # pragma: no cover
        return 0


def _verify_style_payload(payload: str, style_outcome, chat_id: int, *,
                          stage: str, correlation_id: str | None = None) -> None:
    """SOUL-1 (W3, SOUL-16.3.4): проверить ФАКТИЧЕСКИ доставляемый payload.

    Порядок: проход формы (до сериализации) → сериализация/escape ветки
    доставки → egress-guard (``sanitize_outgoing``) → проверка БЕЗ правок
    именно доставляемых байтов → отправка. Если hard-правило формы нарушено на
    payload, это видно в событии и в логе — «styled=true» при провале не
    объявляется. Ошибка проверки не роняет доставку (fail-open).

    ADD-EXP §6: здесь же сравниваются raw-флаги хода с ФАКТИЧЕСКИ
    доставляемым payload (вкл. egress ``sanitize_outgoing``) — класс
    ``postprocess_changed``; проверка выполняется и без style-прохода.
    """
    if correlation_id is not None:
        try:
            _expression_postprocess_check(
                chat_id, correlation_id, _delivered_payload(payload),
                stage="egress_guard")
        except Exception:      # pragma: no cover — проверка не рвёт доставку
            pass
    if style_outcome is None or not getattr(style_outcome, "applied", False):
        return
    policy = getattr(style_outcome, "policy", None)
    if policy is None:
        return
    try:
        payload = _delivered_payload(payload)
        check = _style_policy.verify_outbound_payload(
            payload, policy=policy, context=getattr(style_outcome, "context",
                                                    "regular"),
            outcome=style_outcome)
        style_outcome.payload = True
        style_outcome.payload_status = check.payload_status
        if check.payload_status == "mismatch":
            logger.warning(
                "[direct] style policy payload mismatch | chat=%s | stage=%s | "
                "conflicts=%s", chat_id, stage, ",".join(check.conflicts) or "-")
            _mca_events.emit_mca_event(
                "style_policy", outcome="failed", level="WARN",
                component="style_policy", stage=stage, chat_id=int(chat_id),
                usage_json=check.as_dict())
    except Exception:      # pragma: no cover - проверка не роняет доставку
        logger.warning("[direct] style payload verify failed — skip | "
                       "chat=%s", chat_id, exc_info=True)


def _emit_throttle_refusal_event(*, chat_id: int, remaining: float, limit: int,
                                 cooldown: float, source: str,
                                 stage: str) -> None:
    """CFG-01 (§01.6): durable-событие отказа Direct Chat throttle.

    Админ видит ФАКТИЧЕСКИЙ остаток (сек до разблокировки), размер лимита,
    паузу и источник (`chat`/`global`/`factory`) — без них невозможно понять,
    какой слой настроек реально ограничил чат. R17-safe: числа + enum-коды,
    без текста сообщения. Fail-open (эмиссия никогда не бросает)."""
    try:
        _mca_events.emit_mca_event(
            "direct_chat_throttle", outcome="skipped",
            level=_mca_events.LEVEL_WARN, component="direct_chat",
            stage=stage, reason_code="rate_limit", chat_id=int(chat_id),
            usage_json={
                "remaining_seconds": round(max(0.0, float(remaining)), 1),
                "burst_limit": int(limit),
                "cooldown_seconds": float(cooldown),
                "source": str(source),
            })
    except Exception:      # pragma: no cover — телеметрия не роняет ход
        logger.warning("[direct] throttle event failed — skipped", exc_info=True)


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
    (принято, прецедент CooldownTracker smartmodule_throttling.py; в проде
    используется persistent-вариант, см. `PersistentThrottle`). Полное
    восстановление зарядов через CHAT_COOLDOWN_SECONDS после ПОСЛЕДНЕГО
    допущенного обращения. Однопоточный event loop — asyncio.Lock НЕ нужен
    (прецедент CooldownTracker).

    CFG-01: ёмкость/пауза — EFFECTIVE-значения (per-chat override → global →
    factory), применяются `refresh()` ДО проверки; накопленный остаток
    зарядов обрезается до нового лимита (`min`), `last_ts` не сбрасывается."""

    def __init__(self, burst_limit: int, cooldown_seconds: float) -> None:
        self._limit, self._cooldown = _limits.normalize_direct_chat_limits(
            burst_limit, cooldown_seconds)
        self._state: dict[tuple[int, int], tuple[int, float]] = {}   # (chat_id, user_id) -> (burst_left, last_ts)

    def refresh(self, burst_limit: int, cooldown_seconds: float) -> None:
        """CFG-01 (§01.2): новые лимиты на следующую проверку (без сброса
        состояния): `_limit`/`_cooldown` из effective-резолва."""
        self._limit, self._cooldown = _limits.normalize_direct_chat_limits(
            burst_limit, cooldown_seconds)

    def allow(self, chat_id: int, user_id: int) -> float:
        """0.0 = допустимо (заряд списан); >0 = остаток кулдауна, сек (фраза R50-7)."""
        now = time.monotonic()
        state = self._state.get((chat_id, user_id))
        if state is None or now - state[1] >= self._cooldown:
            burst = self._limit                       # полное восстановление
        else:
            burst = min(state[0], self._limit)        # CFG-01: кламп к новому лимиту
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

    async def _recent_bot_replies(self, chat_id: int,
                                  limit: int = 3) -> tuple[str, ...]:
        """FIX-CORRECTIVE-R1 (direct-l1-rootcause P2, 21.10.2026): тексты
        недавних ответов бота из СУЩЕСТВУЮЩЕЙ таблицы bot_replies — контекст
        L1-планера («разговор уже завершён» видно из собственной реплики).
        То же окно ``CHAT_BOT_REPLIED_RECENTLY_SECONDS`` и тот же паттерн
        прямого чтения, что у ``_bot_replied_recently``; новых хранилищ нет.
        Хронологический порядок (старое → свежее). Fail-open → ()."""
        window_s = bot_replied_recently_window_seconds()
        if window_s <= 0 or limit <= 0:
            return ()
        try:
            cursor = await self.db.db.execute(
                "SELECT text FROM bot_replies WHERE chat_id = ? "
                "AND last_used_at > ? ORDER BY last_used_at DESC LIMIT ?",
                (chat_id, time.time() - window_s, int(limit)))
            rows = await cursor.fetchall()
        except Exception:
            logger.debug("[l1] recent bot_replies read failed",
                         exc_info=True)
            return ()
        texts = [str(row["text"] or "").strip() for row in rows or []]
        texts = [t for t in texts if t]
        texts.reverse()                      # старое → свежее
        return tuple(texts)

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

    async def _execute_silent_ack(self, bot, *, chat_id: int,
                                  trigger_id: int | None,
                                  reply_bot: bool, addressed: bool,
                                  reason: str) -> None:
        """ASAP-3.2 (ADR-1028-5 D11, §50): единый исполн conscious-SILENT.

        🗿 — единственный hardcode реакции: ТОЛЬКО direct-autonomous
        (reply_to_bot) ∧ addressed ∧ silent-ack гейты (env + per-chat);
        фон/not_addressed → тишина без реакции. Логика идентична прежнему
        inline-блоку (ASAP-3 D9) — метод извлечён для переиспользования
        post-LLM SILENT-решением Decision Task. Fail-soft §28: отказ ack
        логируется, SILENT остаётся SILENT, текст НЕ генерируется.
        """
        if not (reply_bot and addressed
                and await self._silent_ack_enabled(chat_id)):
            return
        _composer.record_direct_metric("direct_autonomous_silent_total")
        _ack_outcome = await react_moai(
            bot, chat_id, trigger_id,
            reaction=REACTION_MOAI,
            reason_code=reason)
        if _ack_outcome == "ok":
            _composer.record_direct_metric(
                "direct_silent_ack_success_total")
            _composer.emit_direct_silent_ack(
                chat_id=chat_id, target_message_id=trigger_id,
                success=True, reason_code=reason)
        else:
            _composer.record_direct_metric(
                "direct_silent_ack_failed_total")
            _composer.emit_direct_silent_ack_failed(
                chat_id=chat_id,
                target_message_id=trigger_id,
                error_code=_ack_outcome,
                reason_code=reason)
            logger.warning(
                "[direct] silent ack failed | chat=%s "
                "target=%s outcome=%s reason=%s",
                chat_id, trigger_id, _ack_outcome, reason)

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
        """F6 (§13.1): обёртка хода Direct + детерминированный producer
        `unanswered_question`. Сам ход — в `_handle_turn` (без изменений);
        после его завершения: пользовательское сообщение с '?' и бот НЕ
        отправил текстовый reply в этом ходе → durable follow_up-намерение
        (гейты/дедуп/кап — внутри mca_intents.create_intent). Обычный шум
        (без '?', команды, URL) намерений не создаёт (I2). Producer
        никогда не влияет на исход хода (fail-open)."""
        chat_id = message.chat.id
        replied = set()
        _turn_token = _turn_text_replied.set(replied)
        try:
            await self._handle_turn(bot, message, user)
        finally:
            _turn_text_replied.reset(_turn_token)
            try:
                query = _message_user_text(message)
                if chat_id not in replied:
                    await _f6_maybe_create_unanswered_question(
                        self.db, chat_id, query,
                        getattr(message, "message_id", None))
            except Exception:
                logger.warning(
                    "[f6] unanswered_question producer failed — skipped",
                    exc_info=True)

    @staticmethod
    def _mark_turn_text_replied(chat_id: int) -> None:
        """F6: отметить «бот отправил текст в этом ходе» (invoke-scoped —
        контекст-переменная изолирует параллельные ходы разных чатов)."""
        replied = _turn_text_replied.get()
        if replied is not None:
            replied.add(int(chat_id))

    async def _handle_turn(self, bot, message, user) -> None:
        """Триггер уже проверен хендлером. Кулдаун → фраза R50-7; иначе —
        контекст → LLM → Reply → memorize (fire-and-forget, ПОСЛЕ отправки).
        Epic 60 (63.2): генерация — под per-chat замком (после throttle/CB)."""
        chat_id = message.chat.id
        user_id = user.id if user is not None else 0
        target_name = self._resolve_name(user)
        # ADD-TR.2 (ADTR-ENTRY): текст хода = text ИЛИ caption подписи —
        # единое событие доходит до семантических путей (L1/интенты/пре-гейты)
        # без потери подписи и без отдельной «caption-реплики».
        query = _message_user_text(message)
        # F7 (ADR-1023-7 D4): ОДИН сквозной id на ответ пользователя —
        # связывает Stage-1 → tool-раунды → Stage-2 в дерево дашборда.
        correlation_id = usage_events.new_correlation_id()
        # CFG-01 (§01.1–§01.7): ЕДИНСТВЕННЫЙ вход пользовательских обращений —
        # сначала effective-лимиты (per-chat override → global → factory,
        # hot-reload без рестарта), затем проверка token bucket. Ни LLM, ни
        # tool-раунды, ни fallback-ветки выше этой точки не вызываются —
        # обойти ограничитель альтернативным маршрутом внутри Direct нельзя.
        limit, cooldown, limit_source = await resolve_direct_chat_limits(chat_id)
        throttle_refresh(self.throttle, limit, cooldown)
        cooldown_refresh(self.silence_streak, cooldown)
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
                    _emit_throttle_refusal_event(
                        chat_id=chat_id, remaining=float(remaining),
                        limit=limit, cooldown=cooldown, source=limit_source,
                        stage="silence")
                    return
            phrase = random.choice(CHAT_COOLDOWN_PHRASES).replace(
                "{remaining_time}", format_remaining_time(remaining))
            await _reply(bot, chat_id, phrase, message.message_id)
            self._mark_turn_text_replied(chat_id)     # F6: текст в ходе есть
            # §01.6: фактический остаток + источник лимита — в лог и в
            # админскую телеметрию (Inspector/oversight по mca_events);
            # «время разблокировки» = now + remaining.
            logger.warning(
                "[direct] cooldown | chat=%s user=%s remaining=%.0fs | "
                "burst_limit=%s cooldown=%s source=%s",
                chat_id, target_name, remaining, limit, cooldown, limit_source)
            _emit_throttle_refusal_event(
                chat_id=chat_id, remaining=float(remaining), limit=limit,
                cooldown=cooldown, source=limit_source, stage="cooldown")
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
            self._mark_turn_text_replied(chat_id)     # F6: текст в ходе есть
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
            self._mark_turn_text_replied(chat_id)     # F6: текст в ходе есть
            return
        # MCA-22 (C7, T-4307; ADR-1028-6 D8): update-identity дедуп — строгий
        # ключ `(chat_id, tg_message_id, revision)` в smart_cache (24 h),
        # НЕ по тексту. Инвариант §16/§19: same update → idempotent
        # (0 LLM / 0 reply / 0 memory); different update, same text →
        # fresh processing. OFF-рубильник → паритет baseline (без маркера).
        _trigger_tg_id = getattr(message, "message_id", None)
        if await _fresh.check_update_seen(self._cache, chat_id,
                                          _trigger_tg_id, revision=1,
                                          user_id=(user_id or None)):
            _fresh.emit_freshness_event(
                "DIRECT_UPDATE_DEDUP_HIT", outcome="skipped",
                reason_code="direct_update_dedup_hit",
                chat_id=chat_id, message_id=_trigger_tg_id)
            logger.info("[direct] update dedup hit | chat=%s user=%s",
                        chat_id, target_name)
            # Fix round-1 (M-1 wiring): ранний return ПОСЛЕ захвата слота
            # пула обязан его отпустить — иначе повторная доставка того же
            # update'а НАВСЕГДА съедала per-chat слот
            # (limits.smartmodule_concurrency_per_chat) и чат вставал:
            # каждое следующее сообщение ждало lock-wait и получало
            # «занят» (дефект был замаскирован TTL 300 с старого маркера;
            # 24-часовой маркер сделал его достижимым в тестах и проде).
            permit.release()
            return
        await _fresh.mark_update_seen(self._cache, chat_id, _trigger_tg_id,
                                      revision=1, user_id=(user_id or None))
        # MCA-22 (C8, T-4305/T-4306; ADR-1028-6 D9): фразы-триггеры коррекции
        # («это говорил Лёха / ты сам это написал / ты меня перепутал / это
        # старая информация») → correction path: contradicts-evidence
        # (tentative) + conflict_status='conflicting' + revalidation-очередь.
        # User correction — сильный сигнал, НЕ абсолютная истина; ответ
        # генерируется обычным путём. Gate OFF → обычный диалог (паритет).
        # Триггер проверяется детерминированно СИНХРОННО: фоновая задача
        # создаётся только при реальном срабатывании (обычные реплики —
        # 0 накладных; задача вне fire_and_forget-очереди пост-фаз send —
        # не сдвигает порядок memorize-хука).
        if mca_gates.correction_revalidation_enabled():
            _corr_plan = _gprov.plan_correction(message_text=query)
            if _corr_plan.triggered:
                asyncio.create_task(
                    self._run_correction_path(chat_id, query,
                                              _trigger_tg_id))
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
            # ASAP-3.1 §14/§42: fallback recompose factory (заполняет
            # композер, adapter вызывается LLMClient при fallback-переключении).
            _fallback_meta: dict = {}
            # ── MCA-08 (D3–D5, T-4903/T-4904): scoped-просьбы (K3) —
            # ingestion ДО сборки контекста (принятая просьба применяется уже
            # к текущему ответу); explicit-only, молчание/реакции/шутки/
            # провокации ничего не создают и не отменяют. Резолв — только для
            # адресата ответа (participant > topic > chat); ядро владельца
            # выше любой просьбы. K3 OFF → "" (байт-паритет 2.58.54).
            style_directives = ""
            if mca_gates.style_scope_enabled():
                try:
                    _reply_to = getattr(message, "reply_to_message", None)
                    _reply_from = (getattr(_reply_to, "from_user", None)
                                   if _reply_to is not None else None)
                    _reply_bot = bool(
                        isinstance(getattr(_reply_from, "id", None), int)
                        and self.bot_id is not None
                        and int(_reply_from.id) == int(self.bot_id))
                    _is_private = (getattr(getattr(message, "chat", None),
                                           "type", None) == "private")
                    if self._decision_addressed(message, query, _reply_to,
                                                _reply_bot, _is_private):
                        await _style_scope.ingest_message(
                            self.db, chat_id=chat_id, sender_id=user_id,
                            text=query, message_id=_trigger_tg_id)
                        style_directives = await _style_scope.resolve_block(
                            self.db, chat_id=chat_id, text=query,
                            participant_id=(user_id or None))
                except Exception:
                    logger.debug("[mca08_style] ingest/resolve failed",
                                 exc_info=True)
                    style_directives = ""
            # ADD-TR.2 (ADTR-ENTRY, M-ADTR-ENTRY-REFS способ C): явная ссылка
            # на ранее присланное в чате изображение — bounded-резолв по
            # каноническому реестру MCA-19; неоднозначность → () (уточнение —
            # штатный путь L1/Writer, без «угаданной» цели). Один резолв на
            # ход — общий для context-сборки и L1-контекста.
            _extra_media_markers = await self._resolve_earlier_image_markers(
                chat_id, message)
            user_blocks = await self._build_user_content(
                chat_id, message, target_name,
                target_user_id=(user_id or None),
                out_excluded=_excluded_blocks, out_fallback=_fallback_meta,
                style_directives=style_directives,
                extra_media_markers=_extra_media_markers)
            # MCA-15 (T-4920, ADR-1028-12 D6; K3): intent-различение
            # `social_banter`/`historical_evidence`/`chat_statistics`/`mixed`
            # по контексту и reply (не только по словам «никогда»/«бот»).
            # Хинт добавляется ДО payload; ctx.stats_intent — после создания
            # ToolContext. K3 OFF → ("", None) — паритет 2.58.55.
            _stats_block, _stats_intent = "", None
            if mca_gates.stats_intent_enabled():
                _stats_reply = getattr(message, "reply_to_message", None)
                _stats_reply_text = ""
                if _stats_reply is not None:
                    _stats_reply_text = (
                        getattr(_stats_reply, "text", None)
                        or getattr(_stats_reply, "caption", None) or "")
                _stats_reply_from = (getattr(_stats_reply, "from_user", None)
                                     if _stats_reply is not None else None)
                _stats_reply_bot = bool(
                    isinstance(getattr(_stats_reply_from, "id", None), int)
                    and self.bot_id is not None
                    and int(_stats_reply_from.id) == int(self.bot_id))
                _stats_addressed = self._decision_addressed(
                    message, query, _stats_reply, _stats_reply_bot,
                    getattr(getattr(message, "chat", None), "type", None)
                    == "private")
                _stats_block, _stats_intent = self._stats_intent_block(
                    chat_id, query, _stats_reply_text, _stats_addressed)
                if _stats_block:
                    user_blocks = self._insert_dig_result(
                        user_blocks, _stats_block)
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
            # ── SOUL-1 W10 (§5.1/5.3/5.9/5.14): смысловое поручение действия →
            # capability ТЕКУЩЕГО чата (0 LLM-вызовов). Неготовый инструмент
            # или существенно неоднозначное поручение → детерминированный
            # честный ответ из управляемого шаблона реестра
            # (`message.image_failure.*`/`message.image_request.clarify`);
            # генерация и LLM при этом не запускаются вовсе.
            _image_intent = None
            try:
                _cap_reply_msg = getattr(message, "reply_to_message", None)
                _cap_reply_text = str(
                    getattr(_cap_reply_msg, "text", None)
                    or getattr(_cap_reply_msg, "caption", None) or "")
                _cap_handled, _image_intent = \
                    await self._image_capability_gate(
                        chat_id, query, message, bot,
                        reply_text=_cap_reply_text)
                if _cap_handled:
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("direct: image capability gate — обычный ход | "
                               "chat=%s", chat_id, exc_info=True)
            # Раунд 10.23 (F5, ADR-1023-5 §D2): пре-гейт ключевиков генерации
            # изображений («Бот, нарисуй …») — генерация и отправка ДО Stage-1,
            # блок <image_result> для инъекции. НЕ зависит от tool_router
            # (spec §2.2: условие — только «модуль ON»); review iter1 Finding 4.
            # SOUL-1 W10: регекс остаётся БЫСТРЫМ путём очевидных команд;
            # смысловые формулировки без «бот, нарисуй» доходят до той же
            # генерации через проверку согласованности после L1 (§5.10).
            image_block = await self._image_pre_gate_block(
                chat_id, query, bot, message, user_id,
                correlation_id=correlation_id, intent=_image_intent)
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
            react_llm_pending = False
            # ASAP-3.2 (ADR-1028-5 D11): REPLY/REACT/SILENT решает LLM в
            # Stage-1 (Decision Task); прежний матричный исход — только
            # детерминированный fallback/features. OFF (env/per-chat) →
            # байт-в-байт прежний алгоритмический decision.
            decision_llm_pending = False
            _decision_allowed_actions: tuple = ("REPLY",)
            _dctx = None
            # ── ASAP 7 (F1, §1.1/§1.6): гейт pre-tool L1 Planner. env
            # kill-switch DIRECT_L1_ENABLED AND product-флаг
            # flags.direct_l1_enabled (AND-семантика §4.3; каталог-ключ
            # добавит F2). OFF → байт-в-байт прежний pipeline: fused
            # Decision Task (:2480) + REACT-вызов (:2415) + Синтезатор —
            # все legacy-ветки ниже сохранены под этим флагом.
            direct_l1_on = _l1.direct_l1_enabled()
            l1_plan = None
            l1_meta: dict = {}
            _l1_rejected: tuple = ()
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
                    # ── ASAP-3.2 (ADR-1028-5 D11, §47–§48): LLM решает
                    # действие в Stage-1 Decision Task. Демотированная
                    # матрица = features/детерминированный fallback.
                    # Продуктовые правила — runtime allowed-set (§51):
                    # REACT только при включённых реакциях, SILENT только
                    # при ignore_trivial; реальные задачи (demoted REPLY)
                    # не глушатся (§43) — decision task не вводится.
                    # §50/§48: фон/not_addressed silence (не reply_bot) —
                    # дешёвый hard gate, БЕЗ LLM («background silence →
                    # ничего»); conscious SILENT — только direct-autonomous.
                    if direct_l1_on:
                        # ── ASAP 7 (F1, §1.7): allowed-actions формируются
                        # прежней demote-матрицей; LLM-decision-линия
                        # (Decision Task) в L1-пути НЕ вооружается — решение
                        # принимает L1 Planner, allowed-набор остаётся
                        # продуктовым правилом для SILENT/REACT.
                        _actions: list = ["REPLY"]
                        if _toggles.reactions:
                            _actions.append("REACT")
                        if _toggles.ignore_trivial:
                            _actions.append("SILENT")
                        if pre_action not in _actions:
                            _actions.append(pre_action)
                        _decision_allowed_actions = tuple(_actions)
                    elif _llm_react.llm_decision_enabled(
                            bool(_toggles.reactions)) and (
                            pre_action == ACTION_REACT
                            or (pre_action == ACTION_SILENT
                                and _reply_bot)):
                        decision_llm_pending = True
                        _actions: list = ["REPLY"]
                        if _toggles.reactions:
                            _actions.append("REACT")
                        if _toggles.ignore_trivial:
                            _actions.append("SILENT")
                        if pre_action not in _actions:
                            _actions.append(pre_action)
                        _decision_allowed_actions = tuple(_actions)
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
                if (pre_action == ACTION_SILENT and not decision_llm_pending
                        and not direct_l1_on):
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
                    await self._execute_silent_ack(
                        bot, chat_id=chat_id, trigger_id=_trigger_id,
                        reply_bot=_reply_bot,
                        addressed=(_dctx is not None and _dctx.addressed),
                        reason=pre_reason)
                    return
                if (pre_action == ACTION_REACT and not decision_llm_pending
                        and not direct_l1_on):
                    # ── ASAP-3.1 (ADR-1028-3 D7, §30–§31): LLM выбирает emoji
                    # в том же Stage-1 (без второго LLM request); kill-switch
                    # OFF (env или per-chat) → байт-в-байт прежний шорт-кат.
                    # (При D11-ON действие решает Decision Task — блок не
                    # выполняется, см. decision_llm_pending выше.)
                    if _llm_react.llm_reaction_enabled(
                            bool(_toggles.reactions)):
                        react_llm_pending = True
                    else:
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
                excluded=_excluded_blocks, chosen_intent=pre_action,
                trace_id=correlation_id)
            # T-619: системный промпт — горячая точка (фолбек код-канона).
            # Раунд 10 (F-7 §4.5): per-chat override (chat_params → глобал →
            # канон) — «Использовать мой» локального админа работает ТОЛЬКО
            # в его чате; fail-open: PG down → глобальный.
            from services.chat_params import get_chat_param as _cpg
            # SOUL-1 (W1, §1.2/§7.2): единый резолвер реестра — известные
            # сегменты legacy-личности («токсичный … бот-абьюзер») из
            # ПЕРСИСТЕНТНОГО значения не доходят до effective-слоя; кастом
            # владельца и кодовый fallback (PG down) не изменяются.
            from services import prompt_registry as _prompt_registry
            system_prompt, _base_source = await _prompt_registry.resolve_chat_speech(
                "prompts.direct_chat_system_prompt", CHAT_SYSTEM_PROMPT,
                chat_id=chat_id)
            logger.debug("[direct] base channel resolved | chat=%s | "
                         "source=%s | chars=%d", chat_id, _base_source,
                         len(system_prompt or ""))
            # ── SOUL-1 (W2, §4 п.1): единственный владелец сборки речи.
            # Флаг OFF (дефолт) → существующий путь ниже байт-в-байт; ON →
            # system собирает `prompt_composer.compose_prompt` из тех же
            # блоков (Core вставляется ровно между каналом и личностью).
            _composer_gates = await _composer_resolve_gates(chat_id)
            _composer_on = _pcomp.composer_enabled_now(_composer_gates)
            _system_prompt_base = system_prompt
            # Раунд 10.14 (F2 persona-storage-core, spec §3.2): persona-блок —
            # ХВОСТ системного промпта (system_prompt + "\n\n" + block).
            # Пусто/PG down/флаг OFF → промпт байт-в-байт прежний (F2-Q5).
            # H3-фикс: гейт резолвится per-chat (override → global → default).
            # ── MCA-08 (D1/D2, T-4895/T-4896): ОДНА врезка слоёв характера на
            # direct-путь (REUSE существующего хвоста/композеров; второй
            # сборщик промпта запрещён). K1 OFF → вызов-в-вызов путь 2.58.54
            # (байт-паритет); K1 ON → read-контекст слоёв + <Character_Rules>
            # рендерится ТОЛЬКО вместе с непустым persona-блоком.
            persona_enabled = await _cpg(
                chat_id, "flags.persona_enabled",
                hot.get("flags.persona_enabled", settings.PERSONA_ENABLED))
            character_block = ""
            if persona_enabled:
                if mca_gates.character_layers_enabled():
                    _char_ctx = await bot_persona.resolve_character_context(
                        chat_id)
                    persona = _char_ctx.persona
                    traits = [{"text": t} for t in _char_ctx.traits]
                else:
                    persona = await bot_persona.resolve_bot_persona(chat_id)
                    traits = await bot_persona.get_traits(
                        int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50))
                persona_block = bot_persona.build_persona_prompt_block(
                    persona, [t.get("text") for t in traits], enabled=True)
                if persona_block:
                    system_prompt = system_prompt + "\n\n" + persona_block
                    # Для verbalizer (System2) — та же владельческая основа
                    # без правил формы/чужой generic-личности.
                    character_block = persona_block
                    if mca_gates.character_layers_enabled():
                        rules_block = bot_persona.build_character_rules_block()
                        if rules_block:
                            system_prompt = (system_prompt + "\n\n"
                                             + rules_block)
                            character_block = (character_block + "\n\n"
                                               + rules_block)
            # ── MCA-08 (D5, T-4904): scoped-просьбы — хвост системного
            # промпта ПОСЛЕ Character_Rules и ДО Speech_Understanding (порядок
            # spec: persona → rules → Style_Requests → speech). Форма, не
            # смысл/адресат: resolve уже отфильтровал scope/получателя; K3 OFF
            # → пусто (байт-паритет).
            if style_directives:
                system_prompt = system_prompt + "\n\n" + style_directives
            # ── MCA-16 (D6, T-4993/T-4994): bounded-блок проверенных уроков —
            # данные (не инструкции), добавляется в ХВОСТ системного промпта и
            # не вытесняет вопрос/источники (лимиты — LessonService). При
            # генерации с непустым блоком пишутся применения (outcome=unknown;
            # ≤5, одна транзакция) + событие `applied` (≤1 на ход). K1/K4 OFF
            # → пусто (байт-паритет 2.58.58).
            _lessons_block = ""     # ASAP 7 (F1): capture для L2 Writer
            if evidence_bundle is not None \
                    and getattr(evidence_bundle, "lessons", ()):
                try:
                    from services import mca_experience as _mca_exp
                    _lessons_block = _mca_exp.render_lessons_block(
                        evidence_bundle.lessons)
                    if _lessons_block:
                        system_prompt = (system_prompt + "\n\n"
                                         + _lessons_block)
                        if getattr(self, "db", None) is not None:
                            await _mca_exp.get_service(self.db) \
                                .record_applications(
                                    evidence_bundle.lessons,
                                    application_ref=(correlation_id or
                                                     evidence_bundle
                                                     .context_version),
                                    trace_id=correlation_id, chat_id=chat_id)
                except Exception:
                    logger.warning("[mca16] lessons block failed — skipped",
                                   exc_info=True)
            # ── MCA-08 (D6/D7, T-4898/T-4900): речевой сигнал — независимый
            # носитель <Speech_Understanding> (K2; рендер только при активном
            # сигнале). Автор цитаты — из УЖЕ построенного mca-22-контура
            # (bundle.quoted_speaker; повторный resolver-вызов запрещён).
            # Notable-события clarify (R17-safe), per-reply «успехов» нет.
            _speech_block = ""      # ASAP 7 (F1): capture для L2 Writer
            if mca_gates.character_speech_enabled():
                _speech_u = self._build_speech_understanding(
                    message, query, bundle=evidence_bundle)
                _speech_block = _ce.render_speech_block(_speech_u)
                if _speech_block:
                    system_prompt = system_prompt + "\n\n" + _speech_block
                if _speech_u is not None \
                        and _speech_u.clarify != _ce.CLARIFY_NONE:
                    _mca_events.emit_mca_event(
                        "speech_understanding", outcome="success",
                        component="direct_chat",
                        reason_code=("clarification_asked"
                                     if _speech_u.clarify == _ce.CLARIFY_ASK
                                     else "clarification_assumption_used"),
                        chat_id=chat_id)
            # Epic 60 (65.7, T-475): «печатает…» вокруг LLM-точки, без паузы.
            # Эпик 04.09.2026 (3.3): при настроенном tool_router генерация идёт
            # циклом chat_with_tools (модель сама решает вызвать инструменты);
            # ошибки/пустые финалы — те же классы, ветки except ниже без правок.
            # Раунд 10.20 (БЛОК 1/О3, ADR-1020-4 п.5, T-1887/T-1892): флаг
            # «Летописца» резолвится per-chat (override → global → канон); OFF
            # → 8-й инструмент не объявляется (7 прежних — байт-в-байт).
            # ctx вынесен из вызова цикла: сигнал режима ctx.lore_compiled
            # читается ПОСЛЕ chat_with_tools (доставка HTML, ADR-1020-6 п.2).
            # Раунд 10.23 (F5, ADR-1023-5 §D2/§D5): env-рубильник AND
            # каталоговый тумблер `flags.image_generation_module_enabled`
            # (per-chat). OFF → 9-й инструмент не объявляется (8 прежних —
            # байт-в-байт).
            # ASAP 7 (F1): резолв lore/image-флагов ПОДНЯТ выше LLM-вызова L1 —
            # нужен для capability-списка L1-контекста (§1.5) и resolved-
            # подсета; порядок чистых чтений конфига не наблюдаем.
            lore_enabled = await _cpg(
                chat_id, "flags.lore_compiler_enabled",
                hot.get("flags.lore_compiler_enabled",
                        settings.LORE_COMPILER_ENABLED))
            from services import image_generation
            image_enabled = await image_generation.resolve_module_enabled(
                chat_id)
            # Review iter1 Finding 3: если на этот ход уже сработал пре-гейт
            # ключевика, изображение сгенерировано/отправлено — на этом же
            # ходу инструмент не объявляем (один путь генерации, без двойного
            # платного вызова и двойного списания image_calls).
            if image_pre_gate_fired:
                image_enabled = False
            # §18C.3: announced-набор tools — общий для L1-планирования и
            # fallback-inference capability.
            try:
                announced_l1_tools = {
                    t["function"]["name"] for t in active_tools(
                        bool(lore_enabled), bool(image_enabled))
                    if isinstance(t, dict) and t.get("function")}
            except Exception:
                announced_l1_tools = set()
            # ── ASAP 7 (F1, §1.1): L1 PLANNER — 1 LLM call (compact context
            # §1.5, model slot §1.6, ladder §1.6). Решение ДО tools; force →
            # жёсткий override в reply (§1.7); SILENT → 🗿 (_execute_silent_
            # ack, конъюнкция неизменна); REACT → реакция из allowed-набора.
            if direct_l1_on:
                async with typing_active(bot, chat_id):
                    try:
                        l1_plan, l1_meta = await self._plan_direct_l1(
                            chat_id, message, query, correlation_id,
                            bundle=evidence_bundle, target_name=target_name,
                            user_id=user_id, character_block=character_block,
                            lore_enabled=bool(lore_enabled),
                            image_enabled=bool(image_enabled),
                            force_required=bool(_force_required),
                            reply_bot=bool(_reply_bot),
                            extra_media_markers=_extra_media_markers,
                            bot_replies=await self._recent_bot_replies(chat_id),
                            bot_replied_recently=bool(
                                _dctx.bot_replied_recently
                                if _dctx is not None else False),
                            reactions_enabled=bool(getattr(
                                _toggles if decision_on else None,
                                "reactions", False)))
                    except NoApiKeyForChat as exc:
                        # D03 (§18C.1): permission-политика (forbidden/
                        # budget) блокирует и dedicated L1 — тот же
                        # sandbox-путь, что у обычных вызовов (R16: не
                        # тишина).
                        await self._sandbox_no_key_reply(bot, chat_id,
                                                         message, exc)
                        return
                l1_meta.setdefault("override", "")
                if l1_plan is None:
                    # §1.6 ladder: L1 outage (slot+main failed / невалидный
                    # JSON после 1 repair) → deterministic legacy fallback
                    # (classify_request + demote-матрица). Duplicate reply
                    # невозможен: один turn — максимум одна отправка (D13),
                    # freshness/dedup-гварды ниже общие.
                    # §18C.3: planner failure НЕ стирает required tools —
                    # дет. inference required capability (URL/search) +
                    # planner_fallback_reason/required_capability в
                    # telemetry; инструменты исполняются детерминированно,
                    # L2 получает честную пометку.
                    _fb_reply_text = ""
                    try:
                        _fb_reply_msg = getattr(message, "reply_to_message",
                                                None)
                        _fb_reply_text = str(getattr(_fb_reply_msg, "text",
                                                     None)
                                             or getattr(_fb_reply_msg,
                                                        "caption", None)
                                             or "")
                    except Exception:
                        _fb_reply_text = ""
                    _fb_caps = _l1.infer_fallback_capabilities(
                        query, _fb_reply_text, announced=announced_l1_tools)
                    l1_plan = _l1.fallback_plan(
                        query, action=("reply" if pre_action == ACTION_REPLY
                                       else ("react" if pre_action ==
                                             ACTION_REACT else "silent")),
                        allowed_actions=_decision_allowed_actions,
                        capabilities_needed=_fb_caps)
                    l1_meta["fallback"] = "deterministic"
                    l1_meta["planner_fallback_reason"] = "planner_outage"
                    if _fb_caps:
                        l1_meta["required_capability"] = ",".join(_fb_caps)
                    _l1.record_l1_diagnostics(
                        chat_id, planner_fallback_reason="planner_outage",
                        required_capability=(",".join(_fb_caps)
                                             if _fb_caps else ""),
                        execution_mode=str(
                            getattr(l1_plan, "execution_mode", "") or "none"))
                # ── F6 (§13.1): producer `explicit_request` — allowlisted
                # future-intent от L1. Парсер валидирует схему, intent пишет
                # СЕРВИС (LLM в DB не пишет); guard-ы (дедуп по содержанию,
                # cap pending на чат) — в create_intent. До веток action:
                # обещание «вернуться позже» остаётся намерением при любом
                # исходе хода. Fail-open (не влияет на ход).
                if getattr(l1_plan, "future_intent", None) is not None:
                    try:
                        await _f6_create_future_intent(
                            self.db, chat_id, l1_plan.future_intent,
                            getattr(message, "message_id", None))
                    except Exception:
                        logger.warning(
                            "[f6] future_intent producer failed — skipped",
                            exc_info=True)
                _l1_action = l1_plan.action
                if _force_required and _l1_action != "reply":
                    # Hard gate §0/§1.7: force → REPLY всегда (post-parse
                    # override; L1 вызывался с force-фактом в контексте).
                    l1_plan.action = "reply"
                    _l1_action = "reply"
                    l1_meta["override"] = "force"
                if not decision_on and _l1_action != "reply":
                    # decision-политика выключена → прежняя семантика: всегда
                    # текстовый ответ; L1 react/silent демотируются (§48).
                    _l1_action = "reply"
                    l1_plan.action = "reply"
                    l1_meta["override"] = "decision_off"
                if _l1_action == "silent":
                    if l1_plan.confidence_bucket == "low":
                        # §1.3: low confidence — SILENT демотируется в дет.
                        # матрицу (pre_action), не в тупое молчание.
                        l1_meta["override"] = "low_confidence_silent_demote"
                        _l1_action = ("reply" if pre_action == ACTION_REPLY
                                      else ("react" if pre_action ==
                                            ACTION_REACT else "silent"))
                    if _l1_action == "silent":
                        if "SILENT" in _decision_allowed_actions:
                            # §1.7: conscious L1 SILENT в allowed → 🗿 через
                            # _execute_silent_ack (конъюнкция неизменна);
                            # вне гейтов ack — тишина.
                            _log_decision_short_circuit(
                                chat_id=chat_id, action=ACTION_SILENT,
                                reason_code="l1_silent",
                                target_id=_trigger_id)
                            emit_agentic_event(
                                "MESSAGE_IGNORED", run_id=correlation_id,
                                chat_id=chat_id, message_id=_trigger_id,
                                action=ACTION_SILENT, reason="l1_silent",
                                target=pre_target)
                            await self._execute_silent_ack(
                                bot, chat_id=chat_id,
                                trigger_id=_trigger_id,
                                reply_bot=_reply_bot,
                                addressed=(_dctx is not None
                                           and _dctx.addressed),
                                reason="l1_silent")
                        # вне allowed → тишина (§1.7, семантика :2684-2731).
                        return
                if _l1_action == "react":
                    # §1.7: reaction только из ALLOWED_LLM_REACTIONS;
                    # невалид → дет. реакция (demoted-матрица) либо тишина
                    # (семантика :2658-2683).
                    _reaction = l1_plan.reaction
                    if _reaction not in _llm_react.ALLOWED_LLM_REACTIONS:
                        _reaction = None
                    if "REACT" not in _decision_allowed_actions:
                        _reaction = None
                    if _reaction is None:
                        if pre_action == ACTION_REACT:
                            _reaction = (pre_reaction or _reaction_for_class(
                                _decision_message_class(query),
                                getattr(message, "message_id", None)))
                            _react_source = "deterministic"
                        else:
                            logger.warning(
                                "[direct] l1 react invalid — silence | "
                                "chat=%s", chat_id)
                            return
                    else:
                        _react_source = "l1_planner"
                    _llm_react.record_react_outcome(source=_react_source,
                                                    reaction=_reaction)
                    _llm_react.emit_direct_react(
                        chat_id=chat_id, message_id=pre_target,
                        reaction=_reaction, source=_react_source,
                        trigger_type=_trigger_type)
                    _log_decision_short_circuit(
                        chat_id=chat_id, action=ACTION_REACT,
                        reason_code="l1_react", target_id=pre_target,
                        reaction=_reaction)
                    _reaction_outcome = await react_moai(
                        bot, chat_id, pre_target, reaction=_reaction,
                        reason_code="l1_react")
                    emit_agentic_event(
                        "REACTION_SENT", run_id=correlation_id,
                        chat_id=chat_id, message_id=pre_target,
                        outcome=_reaction_outcome, reaction=_reaction,
                        reason="l1_react")
                    return
                # action == reply → pipeline продолжается (capability resolve
                # → tools ∅ | подсет → L2 Writer — стадии ниже).
            # ── MCA-23 (W3): ResponsePlan — детерминированная классификация
            # ДО LLM-стадии (0 LLM-вызовов; §8 fast path не меняется: для
            # очевидного chat/micro тот же один Stage-1 вызов). Extent-блок
            # едет в системный промпт («Ожидаемая полнота»); для
            # longform-семейства — prompt-conflict scrub старого cap-текста
            # (PG-кастом не правится) и model-слот max_tokens.
            response_plan = None
            extent_block = ""
            longform_max_tokens = None
            if direct_l1_on and l1_plan is not None:
                # ── ASAP 7 (F1, §1.8): semantic план от L1; явная форма
                # пользователя — дет. override ПОСЛЕ L1 поверх semantic
                # extent (§2.5). classify_request в primary path не
                # вызывается (demote §1.8); legacy/fallback — ветка ниже.
                l1_plan.apply_form_override(
                    _extent.explicit_form_override(query))
                response_plan = l1_plan.to_response_plan()
            elif _extent.response_plan_enabled():
                try:
                    response_plan = _extent.classify_request(query)
                except Exception:      # pragma: no cover - защитная ветка
                    response_plan = None
            if response_plan is not None:
                extent_block = _extent.render_extent_block(response_plan)
                if extent_block and not _composer_on:
                    system_prompt = (system_prompt + "\n\n"
                                     + extent_block)
                if response_plan.is_longform():
                    longform_max_tokens = \
                        _extent.longform_max_output_tokens()
                    if not _composer_on:
                        system_prompt, _scrubbed = _extent.scrub_for_plan(
                            system_prompt, response_plan)
                        if _scrubbed:
                            logger.warning(
                                "[direct] extent-conflict scrub | chat=%s | "
                                "stage=system_prompt | removed=%d",
                                chat_id, _scrubbed)
                try:   # MCA-23 §33 (P2-B): planned-слой ExecutionGraph —
                    # единственная guarded интеграционная точка, fail-open.
                    from services import execution_graph_source as _egs
                    _egs.record_response_plan(
                        correlation_id, plan=response_plan,
                        action=pre_action)
                except Exception:
                    pass
            # ── SOUL-1 W10 (§5.10/§5.14): дешёвая проверка согласованности
            # решения L1 с реальным состоянием capability (0 LLM; TTL-кеш).
            # Доступное действие, которое L1 не выбрал, выполняется тем же
            # единственным путём в этом же ходу; недоступное — не обещается
            # (правдивая пометка Writer'у). Ошибка проверки → обычный ход.
            try:
                _cap_block, _cap_fired, _cap_denied = \
                    await self._l1_capability_consistency(
                        chat_id, query, message, bot, l1_plan,
                        intent=_image_intent,
                        image_pre_gate_fired=image_pre_gate_fired,
                        correlation_id=correlation_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                _cap_block, _cap_fired, _cap_denied = "", False, ()
                logger.warning("direct: capability consistency — обычный ход | "
                               "chat=%s", chat_id, exc_info=True)
            if _cap_block:
                user_blocks = self._insert_dig_result(user_blocks, _cap_block)
            if _cap_fired:
                # Один путь генерации на ход: инструмент больше не
                # объявляется, маркер прогона ставится (дубль исключён).
                image_pre_gate_fired = True
                image_enabled = False
            # ── SOUL-1 (W2, §4 п.1 + §5): при флаге ON весь system
            # собирается композером из тех же блоков и ровно один раз:
            # channel_contract → core → identity → lessons/style → plan.
            # Флаг OFF → строки выше остаются байт-в-байт прежними.
            if _composer_on:
                system_prompt, _composer_manifest = \
                    await self._compose_speech_system(
                        chat_id=chat_id, writer="tool_phase",
                        run_id=correlation_id,
                        base_prompt=_system_prompt_base,
                        base_key="prompts.direct_chat_system_prompt",
                        base_default=CHAT_SYSTEM_PROMPT,
                        channel="plain", html_safe=True,
                        response_plan=response_plan,
                        extent_block=extent_block,
                        identity_text=character_block,
                        identity_source=("chat"
                                         if mca_gates.character_layers_enabled()
                                         else "legacy_persona"),
                        identity_skipped=("" if persona_enabled
                                          else "persona_disabled"),
                        style_block=style_directives,
                        style_skip=("style_scope_disabled"
                                    if not mca_gates.style_scope_enabled()
                                    else "style_requests_absent"),
                        lessons_block=_lessons_block,
                        lessons_skip="lessons_absent",
                        speech_block=_speech_block,
                        speech_skip=("character_speech_disabled"
                                     if not mca_gates.character_speech_enabled()
                                     else "speech_absent"),
                        gates=_composer_gates,
                        user_parts=tuple(
                            str(b) for b in (user_blocks or []) if b))
                # Единый владелец нормализации — `response_extent`: тот же
                # (и единственный) проход, но уже на ФИНАЛЬНОЙ сборке.
                if response_plan is not None and response_plan.is_longform():
                    system_prompt, _scrubbed_on = _extent.scrub_for_plan(
                        system_prompt, response_plan)
                    if _scrubbed_on:
                        logger.warning(
                            "[direct] extent-conflict scrub | chat=%s | "
                            "stage=tool_phase_composer | removed=%d",
                            chat_id, _scrubbed_on)
                _pcomp.emit_layer_events_once(_composer_manifest)
            time_line = await self._chat_time_line(chat_id)
            payload = build_messages(system_prompt, user_blocks,
                                     time_line=time_line)
            # Epic 60 (65.8, T-476): temperature-пресет юзера (user_prefs)
            # или дефолт. Другие пайплайны — без temperature (65.8).
            temperature = settings.tone_temperature(
                await self._get_tone_preset(chat_id, user_id))
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
            # TR-FIX2 (live 2.58.91, findings 3/5): цель медиа-инструментов —
            # медиа ТЕКУЩЕГО сообщения (A), иначе медиа replied-сообщения (B,
            # тот же приоритет, что у канонических маркеров
            # `_render_current_question`); `reply_source_*` — источник
            # reply-фактчека. Паритет прежнего поведения: нет reply →
            # текущее сообщение.
            _own_media = message_media_type(message)
            _media_target_id = getattr(message, "message_id", None)
            if not _own_media and _reply_message is not None:
                _media_target_id = getattr(_reply_message, "message_id", None)
            tool_ctx = ToolContext(chat_id, query, bot=bot,
                                   reply_to_message_id=message.message_id,
                                   reply_source_message_id=getattr(
                                       _reply_message, "message_id", None),
                                   reply_source_text=_reply_text,
                                   media_target_message_id=_media_target_id,
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
            # MCA-15 (T-4920, D6): intent хода доступен инструментам как
            # сигнал (глобальной блокировки инструментов НЕТ).
            tool_ctx.stats_intent = str(
                getattr(_stats_intent, "intent", "") or "")
            # ── ASAP-3.1 (ADR-1028-3 D7, §30): LLM REACT — тот же Stage-1 ──
            # Один вызов (тот же контекст, что генерировал бы ответ);
            # instruction-block — аддитивный user-блок (прецедент
            # <dig_result>/<image_result>); невалидно/нет → детерминированный
            # fallback (fail-soft молча); текст НЕ отправляется.
            if react_llm_pending:
                try:
                    async with typing_active(bot, chat_id):
                        raw_react = await self.llm.generate(
                            _llm_react.inject_react_task(payload),
                            temperature=temperature, chat_id=chat_id,
                            module="direct_chat", step="react",
                            correlation_id=correlation_id)
                    llm_reaction = _llm_react.extract_llm_reaction(raw_react)
                    if llm_reaction is None:
                        # Матрица — владелец action; LLM не ответила валидно →
                        # детерминированный выбор (fail-soft, §31).
                        reaction = pre_reaction or _reaction_for_class(
                            _decision_message_class(query),
                            getattr(message, "message_id", None))
                        react_source = "deterministic"
                    else:
                        reaction = llm_reaction
                        react_source = "llm_decision"
                    _llm_react.record_react_outcome(source=react_source,
                                                    reaction=reaction)
                    _llm_react.emit_direct_react(
                        chat_id=chat_id, message_id=pre_target,
                        reaction=reaction, source=react_source,
                        trigger_type=_trigger_type)
                    _log_decision_short_circuit(
                        chat_id=chat_id, action=ACTION_REACT,
                        reason_code=pre_reason, target_id=pre_target,
                        reaction=reaction)
                    _reaction_outcome = await react_moai(
                        bot, chat_id, pre_target, reaction=reaction,
                        reason_code=pre_reason)
                    emit_agentic_event(
                        "REACTION_SENT", run_id=correlation_id,
                        chat_id=chat_id, message_id=pre_target,
                        outcome=_reaction_outcome, reaction=reaction,
                        reason=pre_reason)
                except LLMError as exc:
                    # Fail-soft: LLM-выбор недоступен → детерминированная
                    # реакция (пользователь не видит ошибки, §31).
                    logger.warning(
                        "[direct] llm react failed — deterministic fallback "
                        "| chat=%s | error=%s", chat_id, exc)
                    reaction = pre_reaction or _reaction_for_class(
                        _decision_message_class(query),
                        getattr(message, "message_id", None))
                    _llm_react.record_react_outcome(source="deterministic",
                                                    reaction=reaction)
                    _llm_react.emit_direct_react(
                        chat_id=chat_id, message_id=pre_target,
                        reaction=reaction, source="deterministic",
                        trigger_type=_trigger_type)
                    _reaction_outcome = await react_moai(
                        bot, chat_id, pre_target, reaction=reaction,
                        reason_code=pre_reason)
                    emit_agentic_event(
                        "REACTION_SENT", run_id=correlation_id,
                        chat_id=chat_id, message_id=pre_target,
                        outcome=_reaction_outcome, reaction=reaction,
                        reason=pre_reason)
                return
            # ── ASAP-3.2 (ADR-1028-5 D11, §47/§52): Decision Task в ТОТ ЖЕ
            # Stage-1 (один вызов: REPLY отвечает текстом, REACT/SILENT —
            # JSON-решением; второго LLM-call нет). Парсинг решения — ПОСЛЕ
            # генерации (ниже, перед отправкой текста).
            if decision_llm_pending:
                payload = _llm_react.inject_decision_task(
                    payload, _decision_allowed_actions,
                    _llm_react.ALLOWED_LLM_REACTIONS)
            # ── MCA-23 фаза 2 (§20): clarification — нормальный исход ────
            # media/transcription-запрос без разрешимой цели (нет ссылки ни
            # в сообщении, ни в реплае, ни нативного медиа) → ОДИН конкрет-
            # ный уточняющий вопрос (детерминированный, 0 LLM). Цель
            # разрешима из reply → не спрашиваем (§20).
            # ASAP 7 (F1, §1.9 demote): fixed-фраза — legacy-ветка и
            # fallback; в L1-пути clarification решает L1, формулирует L2.
            if (response_plan is not None and self.tool_router is not None
                    and not decision_llm_pending and not direct_l1_on):
                _has_target = (bool(getattr(tool_ctx, "resolved_url", None))
                               or bool(getattr(tool_ctx, "native_media",
                                               None)))
                _clarify = _extent.clarification_question(
                    response_plan, has_target=_has_target)
                if _clarify:
                    logger.info(
                        "[direct] clarify | chat=%s | kind=%s", chat_id,
                        response_plan.task_kind)
                    await send_chunked_reply(bot, chat_id, _clarify,
                                             message.message_id)
                    return
            try:
                async with typing_active(bot, chat_id):
                    # ── ASAP 7 (F1, §1.4): capability resolve (allowlist).
                    # Анонсируется ТОЛЬКО resolved-подсет active_tools;
                    # needs_clarification → tools не запускаются (вопрос
                    # вместо платных вызовов, §1.9).
                    _l1_tool_schemas = None
                    if direct_l1_on:
                        _l1_tool_schemas, _l1_rejected = \
                            await self._l1_tool_subset(
                                chat_id, correlation_id,
                                bool(lore_enabled), bool(image_enabled),
                                l1_plan, denied=_cap_denied)
                    if direct_l1_on:
                        raw = await self._l1_tool_phase(
                            payload, tool_ctx, query=query,
                            lore_enabled=bool(lore_enabled),
                            image_enabled=bool(image_enabled),
                            temperature=temperature, chat_id=chat_id,
                            correlation_id=correlation_id, l1_plan=l1_plan,
                            response_plan=response_plan,
                            fallback_meta=_fallback_meta,
                            time_line=time_line,
                            tool_schemas=_l1_tool_schemas,
                            longform_max_tokens=longform_max_tokens)
                    elif self.tool_router is not None:
                        # ASAP-3.2 (ADR-1028-5 D10, §44/§45): fallback
                        # recompose на tool-пути — tool schemas ВХОДЯТ в
                        # бюджет fallback-окна (резерв вычитается до
                        # recompose); payload с tools под primary-окно
                        # больше не уходит fallback-модели молча.
                        _fb_factory = _fallback_meta.get("adapter_factory")
                        _fb_adapter = None
                        if _fb_factory is not None:
                            try:
                                _tools_for_budget = active_tools(
                                    bool(lore_enabled), bool(image_enabled))
                                _tools_tokens = count_tokens(json.dumps(
                                    _tools_for_budget, ensure_ascii=False))
                            except Exception:
                                _tools_tokens = 0
                            _fb_adapter = _fb_factory(
                                time_line, extra_reserve=_tools_tokens)
                        # ── MCA-23 фаза 2 (§17): bounded multi-tool DAG ──
                        # Детерминированный план (0 LLM) ТОЛЬКО для явных
                        # мульти-данных запросов (напр. «сравни две ссылки»):
                        # <2 исполняемых шага → None (обычный model-driven
                        # путь цикла, байт-паритет). Шаги — только имена из
                        # runtime-набора анонсированных схем (§38).
                        _tool_plan = None
                        if (response_plan is not None
                                and response_plan.tool_policy != "none"
                                and _extent.tool_plan_enabled()):
                            try:
                                _announced = {
                                    t["function"]["name"] for t in
                                    active_tools(bool(lore_enabled),
                                                 bool(image_enabled))}
                                _tool_plan = _extent.build_tool_plan(
                                    query, available_tools=_announced)
                            except Exception:  # план не роняет запрос
                                _tool_plan = None
                            if not _tool_plan:
                                _tool_plan = None
                        raw = await chat_with_tools(
                            self.llm, payload,
                            tools=active_tools(bool(lore_enabled),
                                               bool(image_enabled)),
                            router=self.tool_router, ctx=tool_ctx,
                            temperature=temperature, chat_id=chat_id,
                            module="direct_chat",
                            correlation_id=correlation_id,
                            fallback_payload_adapter=_fb_adapter,
                            max_output_tokens=longform_max_tokens,
                            tool_plan=_tool_plan)
                    else:
                        # ASAP-3.1 §14/§42: fallback recompose — при
                        # переключении на fallback-модель payload
                        # пересобирается под её окно (adapter может быть
                        # None; ON/OFF-паритет сохранён).
                        # ASAP 7 (F1, §1.1): в L1-пути эта ветка не
                        # выполняется (Writer — L2, стадия ниже).
                        _fb_factory = _fallback_meta.get("adapter_factory")
                        raw = await self.llm.generate(
                            payload, temperature=temperature, chat_id=chat_id,
                            module="direct_chat", step="single",
                            correlation_id=correlation_id,
                            fallback_payload_adapter=(
                                _fb_factory(time_line) if _fb_factory
                                else None),
                            max_output_tokens=longform_max_tokens)
            except NoApiKeyForChat as exc:
                # Раунд 10 (F-7 §5.2) + D03: sandbox-фраза
                # content.no_key_reply (LLM НЕ вызывается; тишины нет —
                # R16). Общий helper с D03-блоком dedicated L1.
                await self._sandbox_no_key_reply(bot, chat_id, message, exc)
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
            # ── ASAP-3.2 (ADR-1028-5 D11, §47/§50/§51): парсинг решения
            # Decision Task из ТОГО ЖЕ вызова. REPLY-текст идёт прежним
            # reply-путём; REACT/SILENT — короткое замыкание до отправки
            # текста. Невалидно → детерминированный fallback (§51);
            # пустой/деградированный ответ — не decision.
            if decision_llm_pending and not (
                    isinstance(raw, ToolLoopResult) and raw.degraded):
                _decision = _llm_react.extract_llm_decision(str(raw))
                if _decision is not None:
                    _llm_react.record_decision_outcome(
                        source="llm", action=_decision["action"])
                    if _decision["action"] == "INVALID":
                        # §51: попытка decision JSON не распарсилась —
                        # детерминированный fallback demoted-матрицы,
                        # мусор текстом НЕ отправляется.
                        logger.warning(
                            "[direct] decision json invalid — fallback | "
                            "chat=%s | demoted=%s", chat_id, pre_action)
                        if pre_action == ACTION_REACT:
                            _reaction = (pre_reaction or _reaction_for_class(
                                _decision_message_class(query),
                                getattr(message, "message_id", None)))
                            _llm_react.record_react_outcome(
                                source="deterministic", reaction=_reaction)
                            _llm_react.emit_direct_react(
                                chat_id=chat_id, message_id=pre_target,
                                reaction=_reaction, source="deterministic",
                                trigger_type=_trigger_type)
                            _reaction_outcome = await react_moai(
                                bot, chat_id, pre_target, reaction=_reaction,
                                reason_code=pre_reason)
                            emit_agentic_event(
                                "REACTION_SENT", run_id=correlation_id,
                                chat_id=chat_id, message_id=pre_target,
                                outcome=_reaction_outcome,
                                reaction=_reaction, reason=pre_reason)
                        return
                    _dec_act = _decision["action"]
                    if _dec_act == "REACT":
                        _react_valid = (
                            "REACT" in _decision_allowed_actions
                            and _decision.get("reaction")
                            in _llm_react.ALLOWED_LLM_REACTIONS)
                        if _react_valid:
                            _reaction = _decision["reaction"]
                            _react_source = "llm_decision"
                            _llm_react.record_react_outcome(
                                source=_react_source, reaction=_reaction)
                            _llm_react.emit_direct_react(
                                chat_id=chat_id, message_id=pre_target,
                                reaction=_reaction, source=_react_source,
                                trigger_type=_trigger_type)
                            _log_decision_short_circuit(
                                chat_id=chat_id, action=ACTION_REACT,
                                reason_code=pre_reason,
                                target_id=pre_target, reaction=_reaction)
                            _reaction_outcome = await react_moai(
                                bot, chat_id, pre_target, reaction=_reaction,
                                reason_code=pre_reason)
                            emit_agentic_event(
                                "REACTION_SENT", run_id=correlation_id,
                                chat_id=chat_id, message_id=pre_target,
                                outcome=_reaction_outcome,
                                reaction=_reaction, reason=pre_reason)
                            return
                        # §51: invalid → детерминированный safe fallback:
                        # demoted REACT — его реакция; иначе тишина без
                        # JSON-мусора пользователю.
                        if pre_action == ACTION_REACT:
                            _reaction = pre_reaction or _reaction_for_class(
                                _decision_message_class(query),
                                getattr(message, "message_id", None))
                            _llm_react.record_react_outcome(
                                source="deterministic", reaction=_reaction)
                            _llm_react.emit_direct_react(
                                chat_id=chat_id, message_id=pre_target,
                                reaction=_reaction, source="deterministic",
                                trigger_type=_trigger_type)
                            _reaction_outcome = await react_moai(
                                bot, chat_id, pre_target, reaction=_reaction,
                                reason_code=pre_reason)
                            emit_agentic_event(
                                "REACTION_SENT", run_id=correlation_id,
                                chat_id=chat_id, message_id=pre_target,
                                outcome=_reaction_outcome,
                                reaction=_reaction, reason=pre_reason)
                            return
                        logger.warning(
                            "[direct] decision REACT invalid — silence | "
                            "chat=%s", chat_id)
                        return
                    if _dec_act == "SILENT":
                        if "SILENT" not in _decision_allowed_actions:
                            # Продуктовое правило: SILENT недоступен →
                            # детерминированный fallback прежней матрицы.
                            if pre_action == ACTION_REACT:
                                _reaction = pre_reaction or \
                                    _reaction_for_class(
                                        _decision_message_class(query),
                                        getattr(message, "message_id", None))
                                _llm_react.record_react_outcome(
                                    source="deterministic",
                                    reaction=_reaction)
                                _llm_react.emit_direct_react(
                                    chat_id=chat_id, message_id=pre_target,
                                    reaction=_reaction,
                                    source="deterministic",
                                    trigger_type=_trigger_type)
                                _reaction_outcome = await react_moai(
                                    bot, chat_id, pre_target,
                                    reaction=_reaction,
                                    reason_code=pre_reason)
                                emit_agentic_event(
                                    "REACTION_SENT",
                                    run_id=correlation_id,
                                    chat_id=chat_id,
                                    message_id=pre_target,
                                    outcome=_reaction_outcome,
                                    reaction=_reaction, reason=pre_reason)
                                return
                            return      # demoted SILENT/REPLY → тишина
                        # §50: conscious LLM SILENT; 🗿 — hardcode
                        # direct-autonomous конъюнкции, фон — тишина.
                        _log_decision_short_circuit(
                            chat_id=chat_id, action=ACTION_SILENT,
                            reason_code="llm_decision", target_id=pre_target)
                        emit_agentic_event(
                            "MESSAGE_IGNORED", run_id=correlation_id,
                            chat_id=chat_id, message_id=_trigger_id,
                            action=ACTION_SILENT, reason="llm_decision",
                            target=pre_target)
                        await self._execute_silent_ack(
                            bot, chat_id=chat_id,
                            trigger_id=_trigger_id,
                            reply_bot=_reply_bot,
                            addressed=(_dctx is not None
                                       and _dctx.addressed),
                            reason=pre_reason)
                        return
                    # action == REPLY: JSON без текста → прежний текст не
                    # сгенерирован; детерминированный fallback прежней
                    # матрицы (§51), НЕ отправляем JSON-мусор пользователю.
                    logger.warning(
                        "[direct] decision REPLY without text — fallback | "
                        "chat=%s | demoted=%s", chat_id, pre_action)
                    if pre_action == ACTION_REACT:
                        _reaction = pre_reaction or _reaction_for_class(
                            _decision_message_class(query),
                            getattr(message, "message_id", None))
                        _llm_react.record_react_outcome(
                            source="deterministic", reaction=_reaction)
                        _llm_react.emit_direct_react(
                            chat_id=chat_id, message_id=pre_target,
                            reaction=_reaction, source="deterministic",
                            trigger_type=_trigger_type)
                        _reaction_outcome = await react_moai(
                            bot, chat_id, pre_target, reaction=_reaction,
                            reason_code=pre_reason)
                        emit_agentic_event(
                            "REACTION_SENT", run_id=correlation_id,
                            chat_id=chat_id, message_id=pre_target,
                            outcome=_reaction_outcome, reaction=_reaction,
                            reason=pre_reason)
                        return
                    return      # SILENT/REPLY-fallback → тишина (fail-soft)
                # Ответ НЕ decision JSON → это СОЗНАТЕЛЬНЫЙ REPLY текстом
                # (Decision Task: «если решаешь REPLY — напиши обычный
                # ответ»). Идёт по прежнему reply-путю ниже.
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
            # ASAP 7 (F1, §1.2): координатор — post-фактум классификатор
            # легаси-гейта System2; в L1-пути не строится (гейт демонтирован).
            if not direct_l1_on and coordinator_enabled():
                coordinator = build_coordinator_decision(
                    query=query, message=message, raw=raw, user_id=user_id,
                    image_fired=image_pre_gate_fired, dig_fired=dig_fired,
                    lore_compiled=bool(
                        getattr(tool_ctx, "lore_compiled", False)),
                    pre_reason=pre_reason, pre_reaction=pre_reaction,
                    target_message_id=getattr(message, "message_id", None),
                    plan=response_plan)
                # mca-18 (T-5081/CA-18-7): версия кадра запуска — аддитивно
                # в решение (in-flight версия в trace, `:1574`); None = кадр
                # не активен. Ошибка чтения holder'а → None (fail-open).
                try:
                    from services import mca_self_model as _msm
                    coordinator.frame_version = \
                        _msm.current_run_frame_version()
                except Exception:
                    coordinator.frame_version = None
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
            # MCA-15 (D5, T-4931; K2): контракт проверки чисел ЭТОГО хода из
            # per-turn `ctx.metric_results` (+intent). K2 OFF/ошибка → None
            # (байт-паритет). Один контракт на System2 и финальную сборку.
            numeric_contract = self._numeric_contract_from_ctx(tool_ctx)
            # ── ASAP 7 (F1, §1.2): гейт System2 демонтирован из primary path
            # (guard `not direct_l1_on`); его роль забрал L2 Writer ниже.
            if (not direct_l1_on
                    and getattr(settings, "SYSTEM2_DIRECT_ENABLED", True)
                    and isinstance(raw, ToolLoopResult)
                    and not raw.degraded
                    and bool(getattr(raw, "tool_trace", None))
                    and not getattr(tool_ctx, "lore_compiled", False)
                    and (coordinator is None
                         or coordinator.action == ACTION_TOOL)
                    # MCA-23 фаза 2 (§18-I): media-план с УСПЕШНО доставлен-
                    # ным медиа — Writer-регенерация бесполезна (тул уже
                    # отправил файл; idempotent). Провал media-тула → Writer
                    # работает как раньше (честная деградация §19).
                    and _extent.media_writer_needed(response_plan, raw)):
                synthesized = await self._synthesize_direct_answer(
                    chat_id, query, raw, temperature,
                    correlation_id=correlation_id,
                    bundle=evidence_bundle,
                    character_block=character_block,
                    style_directives=style_directives,
                    numeric_contract=numeric_contract,
                    plan=response_plan)
                if synthesized:
                    # F3 (ADR-1023-3): режим несёт и стиль, и канал доставки.
                    raw, response_mode = synthesized
                    if coordinator is not None:
                        coordinator.style = response_mode
            if direct_l1_on:
                # ── ASAP 7 (F1, §1.1/§1.2) + v6 D04 (§18C.2): evidence
                # packaging (дет., БЕЗ LLM; fair allocation per source) →
                # L2 WRITER — единственный финальный Writer, 1 LLM call.
                # Топология reply-пути: L1 (1) + [tools (0..n orchest.)] +
                # L2 (1). Capacity пакета — под РЕАЛЬНОЕ окно L2
                # (l2_input_budget из композера), не магическая константа.
                if isinstance(raw, ToolLoopResult):
                    _ev_budget = _dx.l2_evidence_budget_chars(
                        _fallback_meta.get("l2_input_budget"),
                        other_chars=len(str(time_line or ""))
                        + sum(len(str(b or ""))
                              for b in (user_blocks or []))
                        + len(str(_lessons_block or ""))
                        + len(str(_speech_block or ""))
                        + len(str(character_block or "")))
                    _ev_cap = (_ev_budget if _ev_budget is not None
                               else _l1.evidence_max_chars())
                    _evidence = _dx.build_evidence_pack(
                        raw, response_plan, capacity_chars=_ev_cap).text
                else:
                    _evidence = ""
                _media_skip = (isinstance(raw, ToolLoopResult)
                               and not _extent.media_writer_needed(
                                   response_plan, raw))
                _clarify_sent = False
                if not _media_skip:
                    _plan_block = _l1.build_l2_plan_block(
                        l1_plan,
                        rejected=_l1_rejected,
                        clarification=bool(
                            getattr(l1_plan, "needs_clarification", False)),
                        low_confidence=(getattr(l1_plan,
                                                "confidence_bucket", "high")
                                        == "low"))
                    _l2 = await self._l2_write_answer(
                        chat_id, query, temperature=temperature,
                        correlation_id=correlation_id,
                        character_block=character_block,
                        style_directives=style_directives,
                        numeric_contract=numeric_contract,
                        response_plan=response_plan,
                        plan_block=_plan_block, user_blocks=user_blocks,
                        time_line=time_line, evidence=_evidence,
                        lessons_block=_lessons_block,
                        speech_block=_speech_block,
                        fallback_budget_tokens=(
                            _fallback_meta.get("l2_fallback_budget")),
                        max_tokens=(longform_max_tokens
                                    if response_plan is not None
                                    and response_plan.is_longform()
                                    else None))
                    if _l2 is not None:
                        # F3-семантика: режим несёт стиль и канал доставки.
                        raw, response_mode = _l2
                    elif not isinstance(raw, ToolLoopResult):
                        # §1.9: L2 отказал, финала tool-loop нет → honest
                        # fallback — ровно один fixed clarification-вопрос
                        # при запросе уточнения (≤1/turn), иначе пустой
                        # ответ (ветка тишины/🗿 ниже). LLMError уже
                        # пробросился бы наверх (LLM outage → error phrase).
                        if getattr(l1_plan, "needs_clarification", False) \
                                and not _clarify_sent:
                            _clarify_sent = True
                            _fixed = _extent.clarification_question(
                                response_plan, has_target=False)
                            if _fixed:
                                logger.info(
                                    "[direct] l1 clarify fallback | "
                                    "chat=%s | kind=%s", chat_id,
                                    getattr(response_plan, "task_kind", ""))
                                await send_chunked_reply(
                                    bot, chat_id, _fixed,
                                    message.message_id)
                                return
                        raw = ""
            # БЛОК 7.2b (T-1921): единая стадия пост-обработки — reasoning-
            # теги-черновики не уходят пользователю (no-op без тегов).
            answer = strip_reasoning_tags(str(raw).strip())
            # БЛОК 7.2c (T-1922, ADR-1020-7 §2): при ctx.lore_compiled
            # доставляем ГОТОВЫЙ текст истории (детерминизм в коде), а не
            # сжатую диспетчерскую ремарку. Обычный путь не меняется.
            lore_story = str(getattr(tool_ctx, "lore_story", "") or "").strip()
            if getattr(tool_ctx, "lore_compiled", False) and lore_story:
                answer = strip_reasoning_tags(lore_story)
            # MCA-15 (D5, T-4931; K2): финальный numeric-гард — покрывает
            # lore-story в обход verbalizer, fallback и прямые тексты. Одна
            # детерминированная коррекция (verified_phrase/снятие), без
            # второго LLM-вызова; событие — notable-only.
            answer, _numeric_stats = _nc.apply_numeric_guard(
                answer, numeric_contract)
            if _numeric_stats.get("mismatch"):
                _mca_events.emit_mca_event(
                    "numeric_claim_guard",
                    outcome=("skipped" if _numeric_stats.get("fallback")
                             else "success"),
                    component="direct_chat", stage="claim_check",
                    reason_code=_numeric_stats.get("reason"),
                    chat_id=chat_id,
                    usage_json={"answer_chars": len(answer)})
                logger.info(
                    "[direct] final numeric guard | chat=%s | corrected=%s | "
                    "fallback=%s", chat_id,
                    bool(_numeric_stats.get("corrected")),
                    bool(_numeric_stats.get("fallback")))
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
            # ── MCA-22 (C7, T-4311; ADR-1028-6 D8/§18): exact duplicate
            # guard — bounded safety net conversational-ответов. new
            # tg_message_id AND normalized(final) == normalized(recent
            # bot answer) → максимум ОДНА regeneration с фиксированным
            # коротким hint; второй совпавший ответ отправляется + metric
            # (loop запрещён). Exemptions §18 — детерминированные тексты.
            # Paraphrase-postprocessor НЕ создаётся (инвариант тестом).
            _freshness_retry_used = False
            if _fresh.freshness_guard_enabled() and self.db is not None:
                try:
                    _recent = await self.db.list_recent_bot_outputs(
                        chat_id, limit=1)
                except Exception:
                    _recent = []
                _recent_text = (_recent[0].get("content_text")
                                if _recent else None)
                _dup = _fresh.evaluate_duplicate(
                    answer, _recent_text, new_tg_message_id=_trigger_tg_id)
                if _dup.duplicate and not _dup.exempt and \
                        _dup.regeneration_allowed and \
                        not getattr(tool_ctx, "lore_compiled", False):
                    # Первый совпавший ответ НЕ отправляется (replay-block),
                    # затем ровно одна regeneration c hint (простой путь —
                    # raw:str; tool-loop/структурные ответы guard'ом на
                    # regeneration не трогаются — bounded).
                    _fresh.emit_freshness_event(
                        "DIRECT_FINAL_REPLAY_BLOCKED", outcome="skipped",
                        reason_code="direct_final_replay_blocked",
                        chat_id=chat_id, message_id=_trigger_tg_id)
                    try:
                        _hint_payload = list(payload) + [{
                            "role": "user",
                            "content": _fresh.DUPLICATE_GUARD_HINT}]
                        raw = await self.llm.generate(
                            _hint_payload, temperature=temperature,
                            chat_id=chat_id, module="direct_chat",
                            step="duplicate_guard_retry",
                            correlation_id=correlation_id)
                        _answer2 = strip_reasoning_tags(str(raw).strip())
                        _dup2 = _fresh.evaluate_duplicate(
                            _answer2, _recent_text,
                            new_tg_message_id=_trigger_tg_id,
                            regeneration_already_used=True)
                        if _answer2 and not (_dup2.duplicate and
                                             not _dup2.exempt):
                            answer = _answer2
                            _freshness_retry_used = True
                            _fresh.emit_freshness_event(
                                "DIRECT_FRESHNESS_RETRY", outcome="success",
                                reason_code="direct_freshness_retry",
                                chat_id=chat_id, message_id=_trigger_tg_id,
                                attempt=2)
                        else:
                            # bounded: второй совпавший → отправить + metric.
                            _fresh.emit_freshness_event(
                                "DIRECT_FRESHNESS_RETRY",
                                outcome="silent",
                                reason_code="duplicate_sent_after_retry",
                                chat_id=chat_id, message_id=_trigger_tg_id,
                                attempt=2)
                    except Exception:
                        logger.warning(
                            "[direct] duplicate guard retry failed — "
                            "send as-is | chat=%s", chat_id, exc_info=True)
            # MCA-15 (D5, T-4931; K2): regeneration после duplicate-guard
            # могла вернуть незаземлённое число — повторяем ТОТ ЖЕ
            # детерминированный гард (без нового LLM-вызова).
            if _freshness_retry_used:
                answer, _numeric_stats2 = _nc.apply_numeric_guard(
                    answer, numeric_contract)
                if _numeric_stats2.get("mismatch"):
                    _mca_events.emit_mca_event(
                        "numeric_claim_guard",
                        outcome=("skipped" if _numeric_stats2.get("fallback")
                                 else "success"),
                        component="direct_chat", stage="claim_check",
                        reason_code=_numeric_stats2.get("reason"),
                        chat_id=chat_id,
                        usage_json={"answer_chars": len(answer)})
                if not answer.strip():
                    # Гард снял единственную неподтверждённую фразу.
                    if coordinator is not None:
                        _log_coordinator_outcome(
                            chat_id=chat_id, action=ACTION_REACT,
                            style=response_mode, chars=0)
                    logger.warning(
                        "[direct] numeric guard emptied regenerated answer — "
                        "silence | chat=%s user=%s", chat_id, target_name)
                    await react_moai(bot, chat_id, message.message_id)
                    return
            if coordinator is not None:
                _log_coordinator_outcome(
                    chat_id=chat_id, action=ACTION_REPLY,
                    style=response_mode, chars=len(answer))
            # ── SOUL-1 (W3, SOUL-16.4.1 + design §6): ЕДИНЫЙ проход формы —
            # `extent check (в т.ч. one_word) -> style policy validation/
            # targeted repair`, ровно один раз, детерминированно (0 LLM).
            # Выполняется ДО сериализации/отправки; доставленный payload
            # проверяется в `_send_direct_answer`. Флаг
            # `SPEECH_STYLE_POLICY_ENABLED` OFF → проход не запускается
            # (байт-паритет), `answer` не меняется.
            _style_outcome = await _style_policy.apply_style_policy(
                answer, chat_id=chat_id, plan=response_plan,
                context="regular",
                explicit_form=str(getattr(l1_plan, "form_override", "") or ""),
                emit_events=True, stage="direct_pre_send")
            if _style_outcome.applied and str(_style_outcome.text or ""):
                if _style_outcome.text != answer:
                    logger.info(
                        "[direct] style policy pass | chat=%s | repaired=%d | "
                        "exempted=%d | conflicts=%d | failed=%d",
                        chat_id, _style_outcome.repaired,
                        _style_outcome.exempted,
                        len(_style_outcome.conflicts),
                        len(_style_outcome.failed))
                answer = _style_outcome.text
            # ── ADD-EXP §6: форма/проход не должен незаметно «съесть» мат —
            # сравнение raw-флагов L2 с текстом после style-pass.
            _expression_postprocess_check(
                chat_id, correlation_id, answer, stage="style_policy")
            # ── MCA-23 (W3, §Delivery Router): RichMessage — опциональная
            # ветка для явных report/deep-research планов. Любой сбой
            # (aiogram<3.30 / capability / TelegramBadRequest) → прежний
            # safe-HTML/plain путь на ТОМ ЖЕ answer (без регенерации, §O).
            # Дедуп/freshness/ledger не затронуты: наружу — id доставленного.
            # MCA-23 фаза 2 (§22): финальный ответ — typed artifact
            # ResponseDocument; plain и rich рендерят ОДИН документ
            # (Rich fail → Plain того же документа без регенерации).
            response_document = _rd.document_from_answer(answer)
            _rich_wanted = (
                response_plan is not None
                and response_plan.delivery_hint == "rich"
                and _extent.rich_delivery_enabled()
                and (response_mode == "deep_research"
                     or response_plan.structure == "report")
                and len(answer) >= _extent.RICH_MIN_ANSWER_CHARS
                and not getattr(tool_ctx, "lore_compiled", False))
            sent_id = await self._send_direct_answer(
                bot, chat_id, answer, message.message_id,
                lore=bool(getattr(tool_ctx, "lore_compiled", False)),
                deep_research=(response_mode == "deep_research"),
                rich=_rich_wanted,
                document=response_document,
                style_outcome=_style_outcome,
                correlation_id=correlation_id)
            if sent_id is not None:
                answer_text = answer
                self._mark_turn_text_replied(chat_id)  # F6: ответ доставлен
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
                # ── SOUL-08.2 (W4): bounded-метаданные отправки для окна
                # реакций. Гейт `HUMOR_FEEDBACK_ENABLED` (default OFF) →
                # никакой записи и никакого чтения; сырые тексты/промпты не
                # сохраняются (только типизированные коды/числа, R17).
                if mca_gates.humor_feedback_enabled():
                    try:
                        from services import mca_humor_feedback as _humor_fb
                        _fb_manifest = _pcomp.get_manifest(
                            chat_id, run_id=correlation_id, writer="l2_writer")
                        await _humor_fb.capture_send(
                            chat_id=chat_id, message_id=int(sent_id),
                            reply_to_message_id=getattr(message, "message_id",
                                                        None),
                            trace_id=str(correlation_id or ""),
                            strategy=str(getattr(response_plan,
                                                 "comic_strategy", "")
                                         or "none"),
                            technique=str(getattr(response_plan,
                                                  "comic_strategy", "")
                                          or "none"),
                            core_revision=str(
                                (_fb_manifest.versions or {}).get("core", "")
                                if _fb_manifest is not None else ""),
                            model=str(getattr(settings, "LLM_MODEL_NAME", "")
                                      or ""),
                            channel=("rich" if _rich_wanted else "plain"),
                            delivered=True)
                    except Exception:
                        logger.warning(
                            "[direct] humor send metadata capture failed "
                            "(доставка не затронута)", exc_info=True)
                # MCA-22 (C2, T-4287): durable ledger — только реально
                # доставленный output (после успешной send); append-only,
                # правка → новая revision-строка. Gate OFF → не пишем
                # (паритет baseline; quote-priority 5 недоступна).
                # awaited-вставка (одна короткая транзакция) — не
                # fire-and-forget: порядок пост-фаз после успешной send
                # не меняется (прецедент remember_bot_reply).
                # Fix round-1 (M-4): autonomous-ответ (free_will триггер)
                # пишется СО СВОИМ kind `autonomous_reply` — раньше все
                # direct-ветки писались как `direct_reply`.
                await _ledger.record_delivered_output(
                    self.db, chat_id=chat_id, tg_message_id=sent_id,
                    text=answer, bot_user_id=self.bot_id,
                    output_kind=direct_output_kind(_trigger_type),
                    sent_at=int(time.time()),
                    parent_message_ref=(f"tg:{message.message_id}"
                                        if message.message_id
                                        is not None else None),
                    correlation_id=correlation_id,
                    source_feature=(_mca18_ledger_source("direct_chat")))
                # MCA-22 (C7, T-4312): lineage-событие свежей генерации
                # (safe snapshot — без raw content/CoT, R17).
                _fresh.emit_freshness_event(
                    "DIRECT_FRESH_GENERATION", outcome="success",
                    reason_code="direct_fresh_generation",
                    chat_id=chat_id, message_id=sent_id,
                    causation_id=correlation_id)
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
            if decision_llm_pending:
                # ADR-1028-5 D11 (§51 fail-soft): LLM-решение недоступно →
                # детерминированный fallback прежней матрицы (реакция/
                # тишина), пользователь не видит ошибки.
                logger.warning(
                    "[direct] llm decision failed — deterministic fallback "
                    "| chat=%s | demoted=%s | error=%s",
                    chat_id, pre_action, exc)
                if pre_action == ACTION_REACT:
                    _reaction = pre_reaction or _reaction_for_class(
                        _decision_message_class(query),
                        getattr(message, "message_id", None))
                    _llm_react.record_react_outcome(source="deterministic",
                                                    reaction=_reaction)
                    _llm_react.emit_direct_react(
                        chat_id=chat_id, message_id=pre_target,
                        reaction=_reaction, source="deterministic",
                        trigger_type=_trigger_type)
                    _reaction_outcome = await react_moai(
                        bot, chat_id, pre_target, reaction=_reaction,
                        reason_code=pre_reason)
                    emit_agentic_event(
                        "REACTION_SENT", run_id=correlation_id,
                        chat_id=chat_id, message_id=pre_target,
                        outcome=_reaction_outcome, reaction=_reaction,
                        reason=pre_reason)
                return
            logger.warning("[direct] LLM failed | chat=%s | user=%s | error=%s",
                           chat_id, target_name, exc)
            await _reply(bot, chat_id, random.choice(CHAT_ERROR_PHRASES),
                         message.message_id)
            self._mark_turn_text_replied(chat_id)     # F6: текст в ходе есть
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
            self._mark_turn_text_replied(chat_id)     # F6: текст в ходе есть
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

    # ── ASAP 7 (F1, §1.1–§1.6): Direct L1 Planner pipeline ──────────────

    @staticmethod
    def _l1_reply_block(message) -> str:
        """§1.5: компактный срез reply-цели для L1-контекста (кап 400
        символов; имя автора + текст). Никогда не бросает."""
        try:
            reply = getattr(message, "reply_to_message", None)
            if reply is None:
                return ""
            text = str(getattr(reply, "text", None)
                       or getattr(reply, "caption", None) or "").strip()
            author = (getattr(getattr(reply, "from_user", None),
                              "first_name", "") or "")
            head = f"автор: {str(author).strip()}\n" \
                if str(author).strip() else ""
            return (head + text[:_l1.L1_REPLY_BLOCK_CHARS]).strip()
        except Exception:      # pragma: no cover - защитная ветка
            return ""

    def _l1_speech_hints(self, message, query: str, bundle) -> str:
        """§1.5: короткий рендер речевого сигнала (коды, R17-safe; полный
        <Speech_Understanding>-блок остаётся Writer-уровня)."""
        try:
            signal = self._build_speech_understanding(message, query,
                                                      bundle=bundle)
        except Exception:      # pragma: no cover - защитная ветка
            return ""
        if signal is None or not getattr(signal, "active", False):
            return ""
        parts = [f"act={getattr(signal, 'speech_act', 'assert')}"]
        if getattr(signal, "quote", False):
            parts.append("quote")
        if getattr(signal, "negation", False):
            parts.append("negation")
        if getattr(signal, "humor_risk", False):
            parts.append("humor_risk")
        clarify = getattr(signal, "clarify", None)
        if clarify == _ce.CLARIFY_ASK:
            parts.append("clarify=ask")
        elif clarify == _ce.CLARIFY_ASSUME:
            parts.append("clarify=assume")
        return " ".join(parts)

    async def _plan_direct_l1(self, chat_id: int, message, query: str,
                              correlation_id: str | None, *, bundle,
                              target_name: str, user_id: int | None,
                              character_block: str, lore_enabled: bool,
                              image_enabled: bool, force_required: bool,
                              reply_bot: bool,
                              extra_media_markers: tuple = (),
                              bot_replies: tuple[str, ...] = (),
                              bot_replied_recently: bool = False,
                              reactions_enabled: bool = False) -> tuple:
        """§1.1/§1.5/§1.6 + v6 D03: pre-tool L1 Planner — 1 LLM call →
        L1Plan.

        Ladder: configured L1 slot (dedicated, hot-first) → (fallback ON)
        main model → дет. fallback решает вызывающий (fallback_plan).
        Bounded repair: ровно 1 повтор при невалидном JSON (D14).
        D03 (§18C.1): ПЕРЕД попыткой — общий permission-резолв
        ключей/бюджета (``authorize_l1_call``): no-own-key +
        global-forbidden и exhausted budget БЛОКИРУЮТ попытку
        (NoApiKeyForChat пробрасывается вызывающему — тот же sandbox-путь,
        что у обычных вызовов); ОБЕ попытки (первая + repair) учтены
        (usage/cost/unknown-cost + бюджетный счётчик глобального ключа).
        D03 (§18C.6): dedicated температура реально применяется в payload;
        провайдер отверг temperature → честный единственный retry без неё
        + флаг ``temperature_unsupported``. usage-row ``step="l1_planner"``
        (генерится llm.generate; для dedicated слота — вручную) + agentic
        event ``L1_PLAN`` (§1.5). Никогда не бросает, КРОМЕ
        NoApiKeyForChat (блок политики); ``None``-план → сигнал
        deterministic fallback (D13/D14)."""

        def _record_llm_call(source_label: str, attempt_messages, slot, *,
                             temperature=None):
            async def _call():
                if source_label == "l1_slot":
                    assert slot is not None and slot.dedicated
                    # dedicated: (content, usage)
                    return await _l1.dedicated_generate(
                        self.llm, attempt_messages, slot,
                        max_output_tokens=_l1.l1_max_output_tokens(),
                        timeout_seconds=_l1.l1_timeout_seconds(),
                        temperature=temperature)
                text = await asyncio.wait_for(
                    self.llm.generate(
                        attempt_messages,
                        temperature=temperature,
                        chat_id=chat_id, module="direct_chat",
                        step="l1_planner", correlation_id=correlation_id,
                        max_output_tokens=_l1.l1_max_output_tokens()),
                    timeout=float(_l1.l1_timeout_seconds()))
                return str(text or ""), None
            return _call

        started = time.monotonic()
        meta: dict = {"source": "main", "inherited": True, "fallback": "",
                      "repair": 0, "override": "",
                      "credential_source": "global",
                      "temperature_applied": False}
        # ── D03 (§18C.1): единая permission-политика ПЕРЕД платными
        # попытками (тот же resolver, что у обычных вызовов).
        credential_source = await _l1.authorize_l1_call(self.llm, chat_id)
        meta["credential_source"] = credential_source
        try:
            window = await self.memory.get_window_messages(chat_id)
        except Exception:
            window = []
        # §1.4: список доступных capability (по активному набору tools).
        try:
            announced = {t["function"]["name"] for t in
                         active_tools(lore_enabled, image_enabled)
                         if isinstance(t, dict) and t.get("function")}
        except Exception:
            announced = set()
        available_caps = _caps.available_capabilities(announced)
        system_prompt_l1 = resolve_prompt(
            "prompts.direct_l1_planner_system_prompt",
            DIRECT_L1_PLANNER_SYSTEM_PROMPT)
        # ── SOUL-1 (W2, §4 п.5): L1 — машинная стадия (`machine_json`):
        # канал-контракт без Core/юмора; ON даёт ту же строку + трассу.
        _l1_gates = await _composer_resolve_gates(chat_id)
        if _pcomp.composer_enabled_now(_l1_gates):
            _pcomp.emit_layer_events_once(
                _pcomp.compose_machine_system(
                    system_prompt_l1, writer="l1_planner", chat_id=chat_id,
                    run_id=correlation_id))
        # FIX-CORRECTIVE-R1 (P2/P3): УСЛОВИЯ собирают существующие факты —
        # force/autonomous + «бот недавно отвечал» + allowed-набор реакций
        # (правило 2 канона ссылается на «разрешённый набор, если указан в
        # контексте»; раньше набор до планера не доезжал вообще).
        _l1_condition_parts = [
            _l1.FORCE_LINE if force_required
            else (_l1.AUTONOMOUS_LINE if reply_bot else "")]
        if bot_replied_recently:
            _l1_condition_parts.append("бот недавно сам отвечал в этом чате")
        if reactions_enabled:
            _l1_condition_parts.append(
                "разрешённые реакции: "
                + " ".join(_llm_react.ALLOWED_LLM_REACTIONS))
        context_text = _l1.build_l1_context(
            query=query,
            current_question=self._render_current_question(
                message, extra_markers=extra_media_markers),
            reply_block=self._l1_reply_block(message),
            window=window, speaker=target_name,
            addressee=(getattr(bundle, "addressee", None) or "чат"),
            memory_hints=_bundle_scoped_slice(bundle),
            speech_hints=self._l1_speech_hints(message, query, bundle),
            capabilities=available_caps,
            force_line="; ".join(p for p in _l1_condition_parts if p),
            persona_frame=str(character_block or ""),
            bot_replies=tuple(bot_replies or ()))
        input_chars = len(context_text)
        messages = [
            {"role": "system", "content": system_prompt_l1},
            {"role": "user", "content": context_text},
        ]
        meta["input_chars"] = input_chars
        plan: _l1.L1Plan | None = None
        last_error: str = ""
        # §1.6 ladder: (1) configured L1 slot — только если dedicated;
        # (2) main model — при fallback ON (когда slot dedicated). Не-
        # dedicated слот = inherit main: попытка одна (повтор того же
        # вызова бессмысленен), далее deterministic fallback.
        attempts: list[tuple[str, bool]] = []
        slot = _l1.resolve_l1_model(chat_id)
        if slot.dedicated:
            attempts.append(("l1_slot", True))
            attempts.append(("main", True))       # fallback ON-гейт ниже
        else:
            attempts.append(("main", False))
        raw_text = ""
        temperature = _l1.l1_temperature(None)
        meta["temperature_configured"] = (
            float(temperature) if temperature is not None else None)
        for attempt_index, (label, needs_fallback_gate) in enumerate(attempts):
            if needs_fallback_gate and attempt_index > 0 \
                    and not _l1.l1_fallback_enabled():
                break
            try:
                raw_text, usage = await _record_llm_call(
                    label, messages, slot, temperature=temperature)()
                if label == "l1_slot":
                    # D03: dedicated-слот — учёт вручную (llm.generate не
                    # задействован); температура реально ушла в payload.
                    meta["temperature_applied"] = temperature is not None
                    await _l1.record_l1_usage(
                        self.llm, usage=usage, messages=messages,
                        content=raw_text, model=slot.model, chat_id=chat_id,
                        correlation_id=correlation_id,
                        credential_source=credential_source)
                plan = _l1.parse_l1_plan(raw_text)
                if plan is not None:
                    plan.source = "llm"
                    meta["source"] = label
                    meta["inherited"] = label != "l1_slot"
                    break
                # §1.3 (D14): невалидный JSON → bounded repair, ровно 1.
                if meta["repair"] == 0:
                    meta["repair"] = 1
                    repair_messages = _l1.build_repair_messages(messages,
                                                                raw_text)
                    raw_text, usage2 = await _record_llm_call(
                        label, repair_messages, slot, temperature=temperature)()
                    if label == "l1_slot":
                        # D03 (§18C.1): repair-попытка учтена ТАКЖЕ.
                        await _l1.record_l1_usage(
                            self.llm, usage=usage2,
                            messages=repair_messages, content=raw_text,
                            model=slot.model, chat_id=chat_id,
                            correlation_id=correlation_id,
                            credential_source=credential_source)
                    plan = _l1.parse_l1_plan(raw_text)
                    if plan is not None:
                        plan.source = "repair"
                        meta["source"] = label
                        meta["inherited"] = label != "l1_slot"
                        break
            except NoApiKeyForChat:
                # D03: политика ключей/бюджета блокирует попытку целиком —
                # НЕ ladder (fallback на main те же ключи не получит).
                raise
            except Exception as exc:      # LLMError/TimeoutError → ladder
                # D03 (§18C.6): dedicated-провайдер отверг temperature →
                # честный единственный retry БЕЗ неё + флаг unsupported.
                last_error = f"{type(exc).__name__}"
                if (label == "l1_slot" and temperature is not None
                        and not meta.get("temperature_unsupported")
                        and "temperature" in str(exc).lower()):
                    meta["temperature_unsupported"] = True
                    meta["temperature_applied"] = False
                    logger.warning(
                        "[direct] l1 dedicated temperature unsupported — "
                        "retry without | chat=%s", chat_id)
                    try:
                        raw_text, usage = await _record_llm_call(
                            label, messages, slot, temperature=None)()
                        await _l1.record_l1_usage(
                            self.llm, usage=usage, messages=messages,
                            content=raw_text, model=slot.model,
                            chat_id=chat_id,
                            correlation_id=correlation_id,
                            credential_source=credential_source)
                        plan = _l1.parse_l1_plan(raw_text)
                        if plan is not None:
                            plan.source = "llm"
                            meta["source"] = label
                            meta["inherited"] = False
                            break
                    except Exception as retry_exc:
                        last_error = f"{type(retry_exc).__name__}"
                logger.warning(
                    "[direct] l1 planner attempt failed | chat=%s | "
                    "source=%s | error=%s", chat_id, label,
                    type(exc).__name__)
        latency_ms = int((time.monotonic() - started) * 1000)
        fallback_flag = "deterministic" if plan is None else ""
        if plan is None:
            logger.warning(
                "[direct] l1 planner outage — deterministic fallback | "
                "chat=%s | last_error=%s", chat_id, last_error or "invalid")
        _l1.emit_l1_plan_event(
            run_id=correlation_id, chat_id=chat_id,
            message_id=getattr(message, "message_id", None), plan=plan,
            requested=(plan.capabilities_needed if plan is not None else ()),
            resolved=(), inherited=bool(meta.get("inherited")),
            fallback=fallback_flag, latency_ms=latency_ms,
            input_chars=input_chars,
            source=str(meta.get("source") or "main"))
        _l1.record_l1_diagnostics(
            chat_id,
            model=str(slot.model or ""),
            source=str(meta.get("source") or "main"),
            credential_source=str(meta.get("credential_source") or "global"),
            temperature_configured=meta.get("temperature_configured"),
            temperature_applied=bool(meta.get("temperature_applied")),
            temperature_unsupported=bool(
                meta.get("temperature_unsupported")),
            repair=int(meta.get("repair") or 0),
            fallback=fallback_flag)
        # F2-FOLLOWUP (§1.10): durable plan_meta на usage-строке — все ходы
        # (reply/silent/react) идут через этот единственный вызов, строка
        # step="l1_planner" уже записана (llm.generate / manual record).
        await self._attach_l1_plan_meta(
            correlation_id, plan, meta, chat_id=chat_id,
            fallback_flag=fallback_flag,
            latency_ms=latency_ms, input_chars=input_chars)
        return plan, meta

    async def _attach_l1_plan_meta(self, correlation_id, plan, meta, *,
                                   chat_id: int | None = None,
                                   fallback_flag: str, latency_ms: int,
                                   input_chars: int) -> None:
        """Дополнить usage-строку(и) step="l1_planner" этого ответа
        R17-whitelist plan_meta (§1.10; durable-оси 24ч/7д). Fail-open:
        нет PG/пула/флага → no-op; значения только через
        sanitize_plan_meta. Никогда не бросает."""
        try:
            if not correlation_id:
                return
            from services import usage_events as _ue
            if not _ue.is_enabled():
                return
            safe = _ue.sanitize_plan_meta(_l1_usage_plan_meta(
                plan, meta, fallback_flag=fallback_flag,
                latency_ms=latency_ms, input_chars=input_chars))
            if not safe:
                return
            pool = getattr(
                getattr(self.llm, "_pg", lambda: None)(), "pool", None)
            if pool is None:
                return
            import json as _json
            async with pool.acquire() as conn:
                await conn.execute(
                    _L1_PLAN_META_UPDATE_SQL,
                    _json.dumps(safe, ensure_ascii=False),
                    str(correlation_id))
        except Exception:
            logger.warning(
                "[direct] l1 plan_meta attach failed — fail-open | "
                "chat=%s", chat_id)

    # Холдеры ladder-состояния L1 (заполняются в handle перед вызовом).

    async def _sandbox_no_key_reply(self, bot, chat_id: int, message,
                                    exc: NoApiKeyForChat) -> None:
        """Раунд 10 (F-7 §5.2) + F-15 (§3.1): у чата нет своего ключа,
        глобальный запрещён/исчерпан → sandbox-фраза content.no_key_reply
        (LLM НЕ вызывается; тишины нет — R16). Лог объясняет ПОЧЕМУ
        (details-снапшот: resolve_path/day/used/limit — БЕЗ секретов, R17).
        Общий путь для обычных вызовов и D03-блока dedicated L1."""
        logger.warning(
            "[direct] no key — sandbox answer | chat=%s | reason=%s "
            "| details=%s",
            chat_id, exc.reason, repr(getattr(exc, "details", None)))
        reply_phrase = hot.get("content.no_key_reply", DEFAULT_NO_KEY_REPLY)
        await _reply(bot, chat_id, reply_phrase, message.message_id)
        self._mark_turn_text_replied(chat_id)  # F6: текст в ходе есть

    async def _l1_tool_subset(self, chat_id: int, correlation_id, lore: bool,
                              image: bool, l1_plan, denied=()) -> tuple:
        """§1.4: resolved-подсет схем tools (единственный анонс для цикла).
        Возврат ``(schemas, rejected)``; ``[]`` → тулов нет; hallucinated/
        неактивные → drop + L1_CAPABILITY_REJECTED (D15); low_confidence →
        capabilities НЕ исполняются (§1.3, честная пометка).

        SOUL-1 W10 (§5.10/§5.18): ``denied`` — capability, которые в ЭТОМ чате
        недоступны по реальному состоянию (нет ключа/модуль выключен/квота):
        их инструменты не анонсируются, а отказ фиксируется наблюдаемым кодом
        ``capability_not_ready`` (никакого «формально tool есть» без блокера).
        Никогда не бросает."""
        try:
            schemas = active_tools(bool(lore), bool(image))
            announced = {t["function"]["name"] for t in schemas
                         if isinstance(t, dict) and t.get("function")}
            skip = ()
            plan = l1_plan or _l1.L1Plan()
            if getattr(plan, "confidence_bucket", "high") == "low" \
                    and getattr(plan, "source", "llm") != "fallback":
                # §1.3: low → capabilities НЕ исполняются (честная пометка).
                # §18C.3: deterministic fallback-план — НЕ LLM-уверенность
                # (confidence 0.0 по конструкции): inferred required tools
                # от skip-гейта не страдают (planner outage не стирает
                # required capability).
                skip = tuple(plan.capabilities_needed or ())
            resolved, rejected = _caps.resolve_capabilities(
                plan.capabilities_needed or (), announced,
                skip_capabilities=skip)
            denied_caps = {str(c or "").strip().lower()
                           for c in (denied or ()) if str(c or "").strip()}
            if denied_caps:
                blocked_tools: set[str] = set()
                for cap in sorted(denied_caps):
                    blocked_tools.update(_caps.CAPABILITY_TOOLS.get(cap, ()))
                    rejected = tuple(rejected) + ((cap,
                                                   _caps.REASON_NOT_READY),)
                resolved = [t for t in resolved if t not in blocked_tools]
            for cap, reason in rejected:
                _caps.emit_capability_rejected(
                    cap, reason, chat_id=chat_id, run_id=correlation_id)
            return _caps.schemas_for_names(resolved, schemas), tuple(rejected)
        except Exception:      # pragma: no cover - защитная ветка
            return [], ()

    async def _l1_tool_phase(self, payload, tool_ctx, *, query: str,
                             lore_enabled: bool, image_enabled: bool,
                             temperature, chat_id: int,
                             correlation_id, l1_plan, response_plan,
                             fallback_meta: dict, time_line: str,
                             tool_schemas, longform_max_tokens=None):
        """v6 D04 (§18C.7): tool-фаза L1-пайплайна со СТРОГИМИ execution
        modes. ``none`` (или resolved tools = ∅ / needs_clarification) →
        ``None`` (Writer без evidence). ``simple_tools`` →
        детерминированные/параллельные tools (0 LLM — третий вызов
        запрещён). ``adaptive_tool_chain`` → bounded orchestrator
        (kill-switch OFF → честная демотация в simple). Возврат —
        ChainResult (ToolLoopResult-совместимый) или ``None``."""
        plan = l1_plan or _l1.L1Plan()
        if not tool_schemas or self.tool_router is None \
                or getattr(plan, "needs_clarification", False):
            return None
        mode, demote_reason = _dx.resolve_execution_mode(plan, tool_schemas)
        announced = {t["function"]["name"] for t in tool_schemas
                     if isinstance(t, dict) and t.get("function")}
        if mode == _dx.EXECUTION_ADAPTIVE:
            result = await _dx.run_adaptive_chain(
                llm=self.llm, router=self.tool_router, ctx=tool_ctx,
                plan=plan, query=query, tool_schemas=tool_schemas,
                chat_id=chat_id, correlation_id=correlation_id)
            if result is not None:
                result.chain_meta.setdefault("demote_reason", "")
                return result
            demote_reason = "orchestrator_unavailable"
        try:
            result = await _dx.run_simple_tools(
                plan=plan, router=self.tool_router, ctx=tool_ctx,
                query=query, chat_id=chat_id,
                correlation_id=correlation_id, announced=announced)
        except Exception:      # паритет fail-soft прежнего tool-пути
            logger.warning("[direct] simple execution failed — fail-soft",
                           exc_info=True)
            result = None
        if result is not None and (demote_reason
                                   or mode == _dx.EXECUTION_ADAPTIVE):
            result.chain_meta["demote_reason"] = (demote_reason
                                                  or "adaptive_fallback")
        return result

    async def _compose_speech_system(self, *, chat_id: int, writer: str,
                                     run_id: str | None,
                                     base_prompt: str, base_key: str,
                                     base_default: str, gates,
                                     profile: str = "speech_plain",
                                     channel: str = "plain",
                                     html_safe: bool = False,
                                     base_source: str = "",
                                     include_mode_block: bool = True,
                                     response_mode: str = "",
                                     response_plan=None, extent_block: str = "",
                                     identity_text: str = "",
                                     identity_source: str = "chat",
                                     identity_skipped: str = "",
                                     style_block: str = "",
                                     style_skip: str = "",
                                     lessons_block: str = "",
                                     lessons_skip: str = "",
                                     speech_block: str = "",
                                     speech_skip: str = "",
                                     context_text: str = "",
                                     user_parts: tuple[str, ...] = ()
                                     ):
        """Собрать system речевого пути через ЕДИНЫЙ композер (SOUL-1 W2 §4).

        Один рендер личности на ход: пин по ``run_id`` даёт tool-phase и
        L2 Writer одну и ту же ревизию ``identity`` (SOUL-03.6/15.5).
        Никогда не бросает: сбой композера → честный fallback на базу.
        """
        snapshot = await _pcomp.turn_snapshot(chat_id, run_id)
        source = base_source or await _pcomp.resolve_base_source(
            chat_id, base_key, base_default)
        # ── SOUL-06/07 (W4): приёмы и примеры — ТОЛЬКО при своих осях ──────
        # Обе оси по умолчанию OFF → ни одного лишнего чтения БД и ни одного
        # LLM-вызова на обычный ответ (паритет W2/W3 сохраняется байт-в-байт).
        _gates_now = gates or _pcomp.gates_from_config()
        _strategy = str(getattr(response_plan, "comic_strategy", "") or "")
        _extent_value = str(getattr(response_plan, "extent", "") or "")
        _structure = str(getattr(response_plan, "structure", "") or "")
        _tone = str(getattr(response_plan, "tone", "") or "")
        humor_ref = None
        sample_refs: tuple = ()
        if getattr(_gates_now, "humor_craft_enabled", False):
            try:
                from services import mca_humor_craft as _humor_craft
                _weight = 1.0
                if mca_gates.humor_feedback_enabled():
                    try:
                        from services import mca_humor_feedback as _humor_fb
                        from services import lore_runtime as _lore_rt
                        _weight = await _humor_fb.strategy_weight(
                            _lore_rt.get_lore_db(), chat_id, _strategy)
                    except Exception:
                        _weight = 1.0
                humor_ref = await _humor_craft.resolve_ref(
                    chat_id=chat_id, comic_strategy=_strategy,
                    extent=_extent_value, structure=_structure, tone=_tone,
                    context_weight=_weight)
            except Exception:
                logger.warning("direct: humor craft resolve failed "
                               "(слой пропущен)", exc_info=True)
                humor_ref = None
        if getattr(_gates_now, "humor_library_enabled", False):
            try:
                from services import mca_sample_library as _samples_lib
                _penalties: dict = {}
                if mca_gates.humor_feedback_enabled():
                    try:
                        from services import mca_humor_feedback as _humor_fb
                        from services import lore_runtime as _lore_rt
                        _penalties = await _humor_fb.sample_penalties(
                            _lore_rt.get_lore_db(), chat_id)
                    except Exception:
                        _penalties = {}
                sample_refs, _selection = await _samples_lib.resolve_refs(
                    chat_id=chat_id, technique=_strategy,
                    extent=_extent_value, context=context_text or "",
                    penalties=_penalties)
            except Exception:
                logger.warning("direct: sample library resolve failed "
                               "(слой пропущен)", exc_info=True)
                sample_refs = ()
        # ── ADD-EXP (wiring): слой «Выражение» подключён к боевой сборке —
        # тот же builder, что у preview (§1.6); режим действует со
        # следующего ответа (hot reload, без рестарта).
        expression_ref = None
        try:
            expression_ref = await _pcomp.resolve_expression_settings(chat_id)
        except Exception:
            logger.warning("direct: expression resolve failed "
                           "(слой пропущен)", exc_info=True)
            expression_ref = None
        expression_examples: tuple = ()
        if expression_ref is not None and str(
                getattr(expression_ref, "mode", "") or "") in (
                "off", "occasional", "frequent"):
            try:
                from services import mca_expression as _expr
                expression_examples = await _expr.build_expression_examples_refs(
                    chat_id, str(expression_ref.mode))
            except Exception:
                logger.warning("direct: expression examples resolve failed "
                               "(слой пропущен)", exc_info=True)
                expression_examples = ()
        plan = _pcomp.PromptPlan(
            profile=profile, writer=writer, chat_id=chat_id, channel=channel,
            html_safe=html_safe, run_id=run_id, base_prompt=base_prompt,
            base_source=source, include_mode_block=include_mode_block,
            response_mode=response_mode,
            core=snapshot.core,
            identity=_pcomp.identity_from_text(
                identity_text, chat_id=chat_id, run_id=run_id,
                source=identity_source, skipped=identity_skipped),
            response_plan=_pcomp.plan_ref_from_response_plan(
                response_plan, extent_block),
            expression=expression_ref,
            expression_examples=expression_examples,
            humor=humor_ref,
            samples=sample_refs,
            style_policy=snapshot.style_policy,
            scoped_requests=(_pcomp.Block(
                "style_requests", style_block, owner="l1",
                source="participant", skip_reason=style_skip),),
            lessons=(_pcomp.Block(
                "verified_lessons", lessons_block, owner="experience",
                source="chat", skip_reason=lessons_skip),),
            speech=_pcomp.Block(
                "speech_understanding", speech_block, owner="l1",
                source="code", skip_reason=speech_skip),
            user_parts=tuple(str(p) for p in (user_parts or ())),
            gates=gates or _pcomp.gates_from_config())
        manifest = _pcomp.compose_prompt(plan)
        return manifest.system, manifest

    async def _l2_write_answer(self, chat_id: int, query: str, *,
                               temperature, correlation_id=None,
                               character_block: str = "",
                               style_directives: str = "",
                               numeric_contract=None, response_plan=None,
                               plan_block: str = "", user_blocks=None,
                               time_line: str = "", evidence: str = "",
                               lessons_block: str = "",
                               speech_block: str = "",
                               writer: str = "l2_writer",
                               fallback_budget_tokens: int | None = None,
                               max_tokens=None, diag_out: dict | None = None
                               ) -> tuple[str, str] | None:
        """ASAP 7 (F1, §1.2) + v6 D04 (§18C.4): L2 WRITER —
        Вербализатор-канал на ВСЕХ Direct-путях. Тот же prompt-канал/
        ``verbalize_validated``/канальные правила, что у легаси Stage-2
        (переиспользование, не дубль); меняется условие запуска и вход:
        полный Writer-контекст + plan-блок + evidence packet (при тулах).
        1 LLM call (ретраи bounded ≤2). ``fallback_budget_tokens`` —
        РЕАЛЬНОЕ окно fallback-модели: при переключении payload
        ПЕРЕСОБИРАЕТСЯ с защищёнными блоками (current request, mandatory
        tool evidence, safety/role system); не помещается — честная
        capacity reason. Возврат ``(текст, response_mode)``; ``None`` →
        честный отказ.

        SOUL-1 (W2): при ON блоки speech/lessons — слои композера (system),
        в user-часть они не дублируются (один владелец блока на payload).

        ADD-EXP: ``diag_out`` (необязательный словарь) получает R17-safe
        факты слоя «Выражение» этого вызова (маркер/режим/провайдер) для
        «Проверить вживую»; точки диагностики §6 (``policy_not_injected``,
        ``provider_limitation``, ``postprocess_changed``) эмитятся здесь же.
        """
        modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True)
        response_mode = _l1.plan_response_mode(response_plan)
        verbalizer_template = (
            resolve_prompt("prompts.direct_chat_verbalizer_system_prompt",
                           DIRECT_VERBALIZER_SYSTEM_PROMPT)
            if modes_on else PREV_CHAT_VERBALIZER_R1023)
        _plan_extent_block = (_extent.render_extent_block(response_plan)
                              if response_plan is not None else "")
        # ── SOUL-1 (W2, §4 п.2/§4 п.3): у блоков speech/lessons РОВНО один
        # владелец в payload. При ON их рендерит композер слоем
        # `context_lessons` (system), поэтому в user-часть они не попадают —
        # иначе один текст уходит в payload дважды (review-w2 F2: ×2
        # <Speech_Understanding>/<Verified_Lessons> в одном ходе). OFF →
        # user-часть байт-в-байт прежняя (блоки здесь, как и раньше).
        _c_gates = await _composer_resolve_gates(chat_id)
        _c_on = _pcomp.composer_enabled_now(_c_gates)
        # User-часть строится до сборки system и передаётся композеру как
        # ЗАЩИЩЁННАЯ часть (вопрос/инструкция/evidence не вытесняются).
        parts: list[str] = []
        if time_line:
            parts.append(str(time_line))
        if plan_block:
            parts.append(plan_block)
        if not _c_on:
            if speech_block:
                parts.append(speech_block)
            if lessons_block:
                parts.append(lessons_block)
        for block in (user_blocks or []):
            if block:
                parts.append(str(block))
        if evidence:
            parts.append("<Tool_Evidence>\n" + evidence + "\n</Tool_Evidence>")
        # ── SOUL-1 (W2, §4 п.2/§4 п.3): единый владелец сборки. Флаг OFF →
        # ветка ниже байт-в-байт прежняя; ON → тот же набор блоков через
        # композер (+Core/Style/Humor/Samples), личность — один рендер на ход.
        _c_manifest = None
        if _c_on:
            verbalizer_system, _c_manifest = await self._compose_speech_system(
                chat_id=chat_id, writer=writer, run_id=correlation_id,
                base_prompt=verbalizer_template,
                base_key="prompts.direct_chat_verbalizer_system_prompt",
                base_default=DIRECT_VERBALIZER_SYSTEM_PROMPT,
                base_source=("legacy_mode" if not modes_on else ""),
                include_mode_block=bool(modes_on),
                gates=_c_gates, response_mode=response_mode,
                response_plan=response_plan, extent_block=_plan_extent_block,
                identity_text=character_block,
                identity_source=("chat"
                                 if mca_gates.character_layers_enabled()
                                 else "legacy_persona"),
                identity_skipped=("" if _c_gates.persona_enabled
                                  else "persona_disabled"),
                style_block=style_directives,
                style_skip=("style_scope_disabled"
                            if not mca_gates.style_scope_enabled()
                            else "style_requests_absent"),
                lessons_block=lessons_block,
                lessons_skip="lessons_absent",
                speech_block=speech_block,
                speech_skip=("character_speech_disabled"
                             if not mca_gates.character_speech_enabled()
                             else "speech_absent"),
                context_text=str(query or ""),
                user_parts=tuple(parts))
            _pcomp.emit_layer_events_once(_c_manifest)
        else:
            verbalizer_system = (
                compose_verbalizer_system(
                    verbalizer_template, response_mode, "plain",
                    html_safe=True,
                    character_block=character_block,
                    style_directives=style_directives,
                    extent_block=_plan_extent_block)
                if modes_on else verbalizer_template)
        # MCA-23 §32-семантика: prompt-conflict scrub старого cap-текста
        # (PG-кастом) из ФИНАЛЬНОЙ сборки L2 (единое решение W2: scrub
        # выполняется и при выключенных режимах — как здесь и было).
        verbalizer_system, _scrubbed = _extent.scrub_for_plan(
            verbalizer_system, response_plan)
        if _scrubbed:
            logger.warning(
                "[direct] extent-conflict scrub | chat=%s | "
                "stage=l2_writer | removed=%d", chat_id, _scrubbed)
        base_messages = [
            {"role": "system", "content": verbalizer_system},
            {"role": "user",
             "content": "\n\n".join(parts) or str(query or "")},
        ]
        # ── ADD-EXP §6: «политика доехала?» — слой рендерен (манифест),
        # маркер есть в ФИНАЛЬНОМ system (после scrub); нет маркера →
        # честный класс `policy_not_injected`, а не молчание.
        _expr_mode = ""
        _expr_rendered = False
        if _c_on:
            try:
                _expr_settings = await _pcomp.resolve_expression_settings(
                    chat_id)
                _expr_mode = str(getattr(_expr_settings, "mode", "") or "")
            except Exception:      # pragma: no cover — fail-open
                _expr_mode = ""
            try:
                _expr_rendered = any(
                    t.layer == "expression" and t.rendered
                    for t in (_c_manifest.layers if _c_manifest is not None
                              else ()))
            except Exception:      # pragma: no cover
                _expr_rendered = False
        _expr_marker = EXPRESSION_MARKER in str(verbalizer_system or "")
        if _expr_rendered and not _expr_marker:
            _expression_diag("policy_not_injected", chat_id=chat_id,
                             stage="l2_writer", detail="marker_absent",
                             mode=_expr_mode)
        if diag_out is not None:
            diag_out.update({"expression_marker": bool(_expr_marker),
                             "expression_mode": _expr_mode,
                             "expression_rendered": bool(_expr_rendered),
                             "provider_error": False})
        # ── v6 D04 (§18C.4): L2 fallback-репак под РЕАЛЬНОЕ окно
        # fallback-модели (plan/memory/lessons/character/evidence;
        # защищённые блоки: current request, mandatory tool evidence,
        # safety/role system). None → прежнее поведение (без адаптера).
        _l2_fb_adapter = None
        if fallback_budget_tokens:
            _l2_fb_adapter = _dx.build_l2_fallback_adapter(
                system=verbalizer_system,
                parts=[p for p in parts
                       if not p.startswith("<Tool_Evidence>")],
                evidence=evidence, query=query,
                fallback_budget_tokens=int(fallback_budget_tokens),
                on_capacity_reason=lambda reason: _l1.record_l1_diagnostics(
                    chat_id, l2_capacity_reason=str(reason)))
        if _l2_fb_adapter is not None and _expr_rendered:
            # §6: fallback-репак тоже обязан сохранить маркер — иначе класс.
            _l2_fb_adapter = _expression_marker_checked_adapter(
                _l2_fb_adapter, chat_id=chat_id, mode=_expr_mode)

        async def _generate(messages):
            _fallbacks_before = _llm_fallbacks_total()
            try:
                reply = await self.llm.generate(
                    messages, temperature=temperature, chat_id=chat_id,
                    module="direct_chat", step="l2_writer",
                    correlation_id=correlation_id,
                    fallback_payload_adapter=_l2_fb_adapter,
                    max_output_tokens=max_tokens)
            except Exception:
                # §6 `provider_limitation`: вызов со слоем упал — не
                # маскируем как «исправлено» (существующие fallback-события
                # клиента сохраняются).
                if _expr_rendered:
                    _expression_diag("provider_limitation", chat_id=chat_id,
                                     stage="l2_writer", detail="exception",
                                     mode=_expr_mode)
                    if diag_out is not None:
                        diag_out["provider_error"] = True
                raise
            if _expr_rendered and _llm_fallbacks_total() > _fallbacks_before:
                _expression_diag("provider_limitation", chat_id=chat_id,
                                 stage="l2_writer", detail="fallback_model",
                                 mode=_expr_mode)
                if diag_out is not None:
                    diag_out["provider_error"] = True
            return reply

        enabled_rules = (channel_enabled_rules("plain", response_mode)
                         if modes_on else None)
        text, stats = await verbalize_validated(
            _generate, base_messages, max_retries=2,
            enabled_rules=enabled_rules,
            dynamic_rules=anticliche_cache.get_rules() or None,
            form_contract=None,
            fallback_text=None,
            numeric_contract=numeric_contract)
        logger.info(
            "[direct] l2 writer | chat=%s | mode=%s | attempts=%d | "
            "retries=%d | hits=%d | fallback=%s", chat_id, response_mode,
            stats.get("attempts", 0), stats.get("retries", 0),
            len(stats.get("hits") or []), bool(stats.get("fallback")))
        if not text.strip():
            return None
        # §6 `postprocess_changed`: raw-флаги хода — только флаги/числа
        # (bounded LRU по correlation_id), сравнение — на style-pass/egress.
        _expression_record_raw(chat_id=chat_id, correlation_id=correlation_id,
                               text=text, mode=_expr_mode,
                               rendered=_expr_rendered)
        return text, response_mode

    # ── System 2 direct (F5, раунд 10.22, ADR-1022-5) — legacy-ветка ────

    async def _synthesize_direct_answer(self, chat_id: int, query: str,
                                        raw, temperature,
                                        correlation_id: str | None = None,
                                        bundle=None,
                                        character_block: str = "",
                                        style_directives: str = "",
                                        numeric_contract=None,
                                        plan=None
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

        MCA-08 (D2, AM-2): `character_block` — опциональный хвост
        владельческой основы (persona + Character_Rules) у verbalizer-промпта
        (default "" → байт-паритет всех текущих вызовов); второго сборщика
        промпта нет.

        MCA-08 (D5/D8, T-4904/T-4907): `style_directives` — опциональный
        `<Style_Requests>`-блок (K3; default "" → паритет). `form_contract`
        строится из проверенного черновика (финал tool-loop) для form-гардов
        постпроцессора (K4; без контракта — байт-паритет 2.58.54).

        MCA-15 (D5, T-4931): `numeric_contract` — опциональный контракт
        проверки чисел ЭТОГО хода (default None → паритет); нарушение →
        ≤1 numeric-повтор тем же Вербализатором, затем детерминированная
        замена/снятие (второго LLM-судьи нет).

        MCA-23 (W3, §4/§11): `plan` — ResponsePlan, классифицированный до
        LLM-стадии. Непустой план → Вербализатор получает extent-блок
        («ОЖИДАЕМАЯ ПОЛНОТА») ВМЕСТО mode-блока (response_mode остаётся
        compat-алиасом: routing/format/доставка без изменений); при
        longform-плане из собранного промпта детерминированно вычищается
        старый cap-текст (PG-кастом не правится, WARN в лог) и на Stage-2
        передаётся max_output_tokens. plan=None (тесты/legacy) → байт-
        паритет прежней сборки.
        """
        draft_text = strip_reasoning_tags(str(raw).strip())
        form_contract = (_nc.FormContract(source_text=draft_text)
                         if draft_text else None)
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
            # ── SOUL-1 (W2, §4 п.4): Stage-1 — машинный профиль
            # (`machine_json`): только канал-контракт, Core/юмор физически
            # не подключаются. OFF → байт-в-байт прежняя строка ниже.
            _c_gates = await _composer_resolve_gates(chat_id)
            _stage1_base = resolve_prompt(
                "prompts.direct_chat_synthesizer_system_prompt",
                DIRECT_SYNTHESIZER_SYSTEM_PROMPT)
            if _pcomp.composer_enabled_now(_c_gates):
                _stage1_manifest = _pcomp.compose_machine_system(
                    _stage1_base, writer="system2_stage1", chat_id=chat_id,
                    run_id=correlation_id)
                _pcomp.emit_layer_events_once(_stage1_manifest)
            synth_messages = [
                {"role": "system", "content": _stage1_base},
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
            # MCA-23 (W3, §11): план — источник полноты; extent-блок заменяет
            # mode-блок. plan=None → "" → прежняя mode-сборка (паритет).
            _plan_extent_block = ""
            if plan is not None and modes_on:
                _plan_extent_block = _extent.render_extent_block(plan)
            # Review iter1 (H2): direct deep_research доставляется safe-HTML
            # (`parse_mode="HTML"` + escape_lore_html) → HTML-capable блок.
            # ── SOUL-1 (W2, §4 п.3): тот же композер, что у L2 (Core/личность
            # из того же хода — общая ревизия identity). OFF → прежняя строка.
            if _pcomp.composer_enabled_now(_c_gates):
                verbalizer_system, _s2_manifest = \
                    await self._compose_speech_system(
                        chat_id=chat_id, writer="system2_stage2",
                        run_id=correlation_id,
                        base_prompt=verbalizer_template,
                        base_key="prompts.direct_chat_verbalizer_system_prompt",
                        base_default=DIRECT_VERBALIZER_SYSTEM_PROMPT,
                        base_source=("legacy_mode" if not modes_on else ""),
                        include_mode_block=bool(modes_on),
                        gates=_c_gates, response_mode=response_mode,
                        response_plan=plan, extent_block=_plan_extent_block,
                        identity_text=character_block,
                        identity_source=("chat"
                                         if mca_gates.character_layers_enabled()
                                         else "legacy_persona"),
                        identity_skipped=("" if _c_gates.persona_enabled
                                          else "persona_disabled"),
                        style_block=style_directives,
                        style_skip=("style_scope_disabled"
                                    if not mca_gates.style_scope_enabled()
                                    else "style_requests_absent"))
                _pcomp.emit_layer_events_once(_s2_manifest)
            else:
                verbalizer_system = (compose_verbalizer_system(
                    verbalizer_template, response_mode, "plain",
                    html_safe=True,
                    character_block=character_block,
                    style_directives=style_directives,
                    extent_block=_plan_extent_block)
                    if modes_on else verbalizer_template)
            # MCA-23 (W3, §11/§32): prompt-conflict scrub — старый cap-текст
            # (PG-кастом 10.23) не должен душить longform. Детерминированная
            # вычистка из ФИНАЛЬНОЙ сборки; БД не трогается, WARN в лог.
            # SOUL-1 (W2, §4 «доп.»): скраб больше НЕ гейтится режимами —
            # Stage-2 приведён к единому решению с L2 (шаг нормализации один).
            verbalizer_system, _scrubbed = _extent.scrub_for_plan(
                verbalizer_system, plan)
            if _scrubbed:
                logger.warning(
                    "[direct] extent-conflict scrub | chat=%s | "
                    "stage=verbalizer | removed=%d", chat_id, _scrubbed)
            # MCA-23 (W3, §Model slots): longform-план получает явный
            # max_tokens; compact/micro/None → None (ключ не едет, паритет).
            _longform_tokens = (_extent.longform_max_output_tokens()
                                if (plan is not None
                                    and plan.is_longform()) else None)
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
                    correlation_id=correlation_id,
                    max_output_tokens=_longform_tokens)

            enabled_rules = (channel_enabled_rules("plain", response_mode)
                             if modes_on else None)
            text, stats = await verbalize_validated(
                _generate, base_messages, max_retries=2,
                enabled_rules=enabled_rules,
                dynamic_rules=anticliche_cache.get_rules() or None,
                form_contract=form_contract,
                fallback_text=(draft_text or None),
                numeric_contract=numeric_contract)
            logger.info(
                "[direct] system2 | chat=%s | mode=%s | attempts=%d | retries=%d | "
                "hits=%d | fallback=%s", chat_id, response_mode,
                stats.get("attempts", 0), stats.get("retries", 0),
                len(stats.get("hits") or []), bool(stats.get("fallback")))
            # MCA-08 (D8, T-4908): notable-событие form-гарда (единственный
            # журнал; reason_code = эквивалент meaning_changed из санкции).
            _form_rejects = int(stats.get("form_guard_rejects") or 0)
            if _form_rejects:
                _mca_events.emit_mca_event(
                    "postprocess_form", outcome="skipped",
                    level=_mca_events.LEVEL_WARN, component="direct_chat",
                    stage="form_guard",
                    reason_code=(stats.get("form_guard_reason")
                                 or "form_guard_rejected"),
                    chat_id=chat_id, attempt=_form_rejects)
                logger.info(
                    "[direct] system2 form guard | chat=%s | rejects=%d | "
                    "retry=%s | form_fallback=%s", chat_id, _form_rejects,
                    bool(stats.get("form_retry")),
                    bool(stats.get("form_fallback")))
            # MCA-15 (D5, T-4931): notable-событие numeric-гарда — только при
            # нарушении (per-reply «успехов» нет); R17-safe (код, без текста).
            _num_mismatch = int(stats.get("numeric_claim_mismatch") or 0)
            if _num_mismatch:
                _num_fallback = bool(stats.get("numeric_claim_fallback"))
                _mca_events.emit_mca_event(
                    "numeric_claim_guard",
                    outcome=("skipped" if _num_fallback else "success"),
                    component="direct_chat", stage="claim_check",
                    reason_code=("numeric_claim_fallback" if _num_fallback
                                 else "numeric_claim_corrected"),
                    chat_id=chat_id, attempt=_num_mismatch)
                logger.info(
                    "[direct] system2 numeric guard | chat=%s | mismatch=%d "
                    "| retry=%s | fallback=%s", chat_id, _num_mismatch,
                    bool(stats.get("numeric_claim_retry")), _num_fallback)
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
                                  deep_research: bool = False,
                                  rich: bool = False,
                                  document=None,
                                  style_outcome=None,
                                  correlation_id: str | None = None):
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
        без тегов — без дублей и без сырой разметки.

        MCA-23 (W3, §Delivery Router): `rich` — опциональная попытка
        ``sendRichMessage`` для явных report/deep-research планов. Первый
        класс ошибки (нет Bot API 10.1+ / aiogram<3.30 / битый payload) →
        прежние ветки ниже на ТОМ ЖЕ `answer` (без регенерации — §O «Rich
        failure»: same document → Plain). HTML-акценты Вербализатора перед
        rich-каналом снимаются `strip_lore_html` (rich-сборщик строит
        статью сам). Возврат — id доставленного сообщения (ledger/
        remember_bot_reply работают без изменений).

        MCA-23 фаза 2 (§22/§24): ``document`` — ResponseDocument (typed
        artifact). plain и rich рендерят ОДИН документ: rich-ветка берёт
        ``rich_text()``, все plain-ветки — ``plain_text()`` (для документа
        из финального текста это байт-в-байт `answer`); Rich fail → Plain
        ТОГО ЖЕ документа без регенерации. None → артефакт собирается из
        `answer` на месте (паритет)."""
        doc = document if document is not None else \
            _rd.document_from_answer(answer)
        text = doc.plain_text()
        if rich:
            try:
                _rich_payload = strip_lore_html(doc.rich_text())
                _verify_style_payload(_rich_payload, style_outcome, chat_id,
                                      stage="direct_rich",
                                      correlation_id=correlation_id)
                sent = await _tg_send.send_rich_message(bot, chat_id,
                                                        _rich_payload)
                sent_id = getattr(sent, "message_id", None)
                if sent_id is not None:
                    return sent_id
                logger.warning(
                    "[direct] rich send: no message_id — legacy path | "
                    "chat=%s", chat_id)
            except Exception as exc:      # fail-open → прежние ветки
                logger.warning(
                    "[direct] rich send failed — legacy path | chat=%s | "
                    "error=%s", chat_id, type(exc).__name__)
        if not (lore or deep_research):
            _verify_style_payload(text, style_outcome, chat_id,
                                  stage="direct_plain",
                                  correlation_id=correlation_id)
            return await send_chunked_reply(bot, chat_id, text, reply_to)
        escaped = escape_lore_html(text)
        if len(escaped) <= _LORE_HTML_MAX_SINGLE_CHARS:
            try:
                _verify_style_payload(escaped, style_outcome, chat_id,
                                      stage="direct_safe_html",
                                      correlation_id=correlation_id)
                return await send_chunked_reply(
                    bot, chat_id, escaped, reply_to, parse_mode="HTML")
            except TelegramBadRequest as exc:
                logger.warning(
                    "[direct] safe-HTML send failed — plain fallback | "
                    "chat=%s | error=%s", chat_id, type(exc).__name__)
                return await send_chunked_reply(bot, chat_id, text, reply_to)
        logger.info("[direct] text too long for safe HTML — plain | "
                    "chat=%s | chars=%d", chat_id, len(escaped))
        _plain_payload = strip_lore_html(text)
        _verify_style_payload(_plain_payload, style_outcome, chat_id,
                              stage="direct_plain_long",
                              correlation_id=correlation_id)
        return await send_chunked_reply(bot, chat_id, _plain_payload,
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

    def _build_speech_understanding(self, message, query: str, *, bundle=None):
        """MCA-08 (D6/D7, T-4898/T-4900): детерминированный речевой сигнал.

        REUSE mca-22 `classify_speech_act` (второй классификатор запрещён);
        R17-safe — коды/флаги без сырого текста. Автор цитаты — только из УЖЕ
        построенного mca-22-контура (`bundle.quoted_speaker`); повторный
        `quote_resolver`-вызов здесь запрещён. K2 OFF → None (паритет
        2.58.54); сама сборка ничего не эмитит (события clarify — у вызова).
        """
        if not mca_gates.character_speech_enabled():
            return None
        reply = getattr(message, "reply_to_message", None)
        reply_bot = False
        reply_ends_question = False
        if reply is not None:
            reply_from = getattr(reply, "from_user", None)
            reply_id = (getattr(reply_from, "id", None)
                        if reply_from is not None else None)
            _bot_id = getattr(self, "bot_id", None)
            reply_bot = bool(isinstance(reply_id, int)
                             and _bot_id is not None
                             and int(reply_id) == int(_bot_id))
            reply_text = str(getattr(reply, "text", None)
                             or getattr(reply, "caption", None) or "").strip()
            reply_ends_question = reply_text.endswith("?")
        is_private = (getattr(getattr(message, "chat", None), "type", None)
                      == "private")
        # Наличие цитаты — из УЖЕ построенного mca-22-контура: резолвнутый
        # автор (`quoted_speaker`) либо честная ambiguous-маркировка
        # (`quote:`-префикс в `ambiguities`). Новых вызовов резолвера нет.
        _quote_known = bool(getattr(bundle, "quoted_speaker", None))
        _quote_present = _quote_known or any(
            str(a).startswith("quote:")
            for a in (getattr(bundle, "ambiguities", ()) or ()))
        return _ce.build_speech_understanding(
            query,
            has_reply_parent=(reply is not None),
            is_group=not is_private,
            reply_parent_from_bot=reply_bot,
            reply_parent_ends_with_question=reply_ends_question,
            quote_attribution_known=_quote_known,
            quote_text_present=_quote_present)

    async def _estimate_external_payload_tokens(
            self, chat_id: int, budget_tokens, *,
            extra_prompt_blocks: tuple[str, ...] = (),
            ) -> tuple[int, int, str | None]:
        """MCA-07 B-MCA07-2 (REQ-MCA07-06/SC-12/A24): консервативная оценка
        НЕ-user части полного payload для живого бюджета.

        Считает: system/developer-промпт + personality-блок + tools schemas
        (JSON) — как `external_tokens`; output reserve = доля
        `CHAT_BUDGET_RESERVE_RATIO` бюджета. Возвращает `(external, reserve,
        method)`; любая ошибка → `(0, 0, None)` (fail-open → точный legacy-
        путь бюджета, паритет). Частичный сбой источника не обнуляет остальные.

        MCA-08 (D2, T-4895): `extra_prompt_blocks` — уже построенные хвостовые
        блоки (speech; Style добавит блок C); признак K1/K2 OFF → пустые
        блоки/прежние числа (байт-паритет). Счёт — тем же `count_tokens`.
        """
        external = 0
        try:
            from services.chat_params import get_chat_param as _cpg
            from services import prompt_registry as _pr
            try:
                # SOUL-1 (W1 fix-pass, BLOCKER-2): тот же резолвер, что и на
                # реальном пути, — оценка payload не расходится с payload.
                system_prompt, _src = await _pr.resolve_chat_speech(
                    "prompts.direct_chat_system_prompt", CHAT_SYSTEM_PROMPT,
                    chat_id=int(chat_id))
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
                        if mca_gates.character_layers_enabled():
                            rules_block = \
                                bot_persona.build_character_rules_block()
                            if rules_block:
                                external += count_tokens(rules_block)
            except Exception:
                logger.debug("[mca07] payload est: persona failed",
                             exc_info=True)
            for _extra in (extra_prompt_blocks or ()):
                if _extra:
                    external += count_tokens(str(_extra))
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
                                  out_excluded: list | None = None,
                                  out_fallback: dict | None = None,
                                  style_directives: str = "",
                                  extra_media_markers: tuple = ()
                                  ) -> list[str]:
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
            mood = self._build_mood_block(_message_user_text(message))
            if mood:
                blocks.append(("mood", mood))
        # Раунд 8 (D1/T-798): <Current_Question> — текущее сообщение после
        # среза префикса «бот/@ник»; кап по символам; пусто → без блока.
        # ADD-TR.2: текст — text/caption (см. _render_current_question).
        current = self._render_current_question(
            message, extra_markers=extra_media_markers)
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
                out_excluded=out_excluded, out_fallback=out_fallback,
                style_directives=style_directives)
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
        # MCA-08 (D2, T-4898): K2-блок речи учитывается тем же методом
        # (K1-правила учитывает сам estimator; OFF → пустые, прежние числа).
        external_tokens, reserve_tokens, method = 0, 0, None
        if budgets_enabled and mca_gates.adaptive_context_budget_enabled():
            _speech_est = _ce.render_speech_block(
                self._build_speech_understanding(
                    message, _message_user_text(message)))
            # MCA-08 (D5, T-4904): style-блок — в ту же оценку тем же методом
            # (K3 OFF → "" и прежние числа).
            _extras = tuple(b for b in (_speech_est, style_directives) if b)
            external_tokens, reserve_tokens, method = \
                await self._estimate_external_payload_tokens(
                    chat_id, budget_tokens, extra_prompt_blocks=_extras)
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
            out_excluded: list | None,
            out_fallback: dict | None = None,
            style_directives: str = "") -> list[str]:
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
        query = _message_user_text(message)
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

        # ── Full payload (D2 / ASAP-3.1 ADR-1028-3): окно модели + external ──
        # ON-путь resolver'а: capacity по реальной паре (base_url + model),
        # preemptive-min снят — fallback резолвится ОТДЕЛЬНО и при меньшем
        # окне получает recompose (§14/§42); OFF → байт-в-байт прежний путь.
        model_name = str(getattr(self.llm, "_chat_model", "") or "")
        fallback_model = str(getattr(self.llm, "_fallback_model", "") or "")
        base_url = str(getattr(self.llm, "_base_url", "") or "")
        fallback_base_url = str(getattr(self.llm, "_fallback_base_url", "")
                                or "")
        resolver_on = (_model_capacity.capacity_resolver_enabled()
                       and _auto_budget.auto_budget_enabled())
        est_method = None
        if resolver_on:
            try:
                model_window, window_source = \
                    await _model_capacity.resolve_stage_window(
                        base_url, model_name, slot="direct.primary")
            except Exception:
                model_window, window_source = \
                    resolve_effective_window(model_name, fallback_model)
        else:
            model_window, window_source = resolve_effective_window(
                model_name, fallback_model)
        try:
            # MCA-08 (D2, T-4898): K2-блок речи — в ту же оценку (тем же
            # методом); K2 OFF → "" и прежние числа. D5/T-4904: style-блок
            # (K3) — рядом, тот же проход.
            _speech_est = _ce.render_speech_block(
                self._build_speech_understanding(message, query))
            _extras = tuple(b for b in (_speech_est, style_directives) if b)
            external_tokens, _est_reserve, est_method = \
                await self._estimate_external_payload_tokens(
                    chat_id, model_window, extra_prompt_blocks=_extras)
        except Exception:
            external_tokens, est_method = 0, None
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
        fallback_recompose_budget: int | None = None
        if resolver_on:
            # ADR-1028-3 §4: единый auto budget resolver (safety ×1, один
            # расчёт; breakdown — в событии AUTO_CONTEXT_BUDGET).
            budget_result = await _auto_budget.resolve_stage_budget(
                "direct.primary", base_url=base_url, model=model_name,
                mandatory_tokens=external_tokens,
                policy_raw=(raw_budget if budgets_enabled else -1))
            model_window = budget_result.context_window
            window_source = budget_result.source
            available = budget_result.auto_input_budget
            output_reserve = budget_result.output_reserve
            budget = budget_result.effective_input_budget
            policy_mode = budget_result.policy_mode
            # §14/§42: fallback-модель — своя capacity, БЕЗ preemptive-min.
            if fallback_model:
                fb_result = await _auto_budget.resolve_stage_budget(
                    "direct.fallback", base_url=fallback_base_url,
                    model=fallback_model,
                    mandatory_tokens=external_tokens, policy_raw=-1)
                if fb_result.effective_input_budget < budget:
                    fallback_recompose_budget = \
                        fb_result.effective_input_budget
                    try:
                        _auto_budget.record_slot_pressure(
                            "direct.fallback", physical_overflow=False)
                    except Exception:
                        pass
        else:
            available, output_reserve = compute_available_budget(
                model_window, external_tokens)
            if not budgets_enabled:
                budget, policy_mode = available, "unlimited"
            else:
                budget, policy_mode = apply_budget_policy(available,
                                                          raw_budget)

        # ── Allocation (eviction P3→P2→P1; P0 не трогается) ──
        def _new_pieces() -> list:
            """Свежие pieces (allocate_budget мутирует piece.text)."""
            fresh: list[_composer.ContextPiece] = []
            for kind, text in candidates:
                if not text:
                    continue
                priority = _composer.BLOCK_PRIORITY.get(kind, _composer.P2)
                fresh.append(_composer.ContextPiece(
                    key=kind, kind=kind, text=text, priority=priority,
                    keep=_composer.PIECE_KEEP.get(kind, "span"),
                    floor_tokens=(thread_floor if kind == "thread"
                                  else (tail_floor if kind == "global_tail"
                                        else 0)),
                    evictable=(priority != _composer.P0),
                    position=canonical_order.get(kind, 99)))
            return fresh

        pieces = _new_pieces()
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

        # ── Финализация (дедуп middle↔tail + materialize) ──────────────────
        # Факторизовано: тот же код используется fallback-recompose (§14).
        def _finalize_allocation(final_allocation) -> tuple[list[str], list]:
            # H1/D5: дедуп middle против ФАКТИЧЕСКИ вошедшего tail.
            mid_piece = next((p for p in final_allocation.pieces
                              if p.kind == "global_middle"), None)
            tail_p = next((p for p in final_allocation.pieces
                           if p.kind == "global_tail"), None)
            kept_middle_lines: list[str] = []
            if mid_piece is not None and mid_piece.text and tail_p is not None \
                    and tail_p.text:
                final_tail_tg = set(
                    re.findall(r"tg:(\d+)", tail_p.text))
                kept_middle_lines = []
                for ln in mid_piece.text.split("\n"):
                    if not ln.strip():
                        continue
                    m = re.search(r"tg:(\d+)", ln)
                    if m and m.group(1) in final_tail_tg:
                        continue        # уже вербатим в выжившем tail
                    kept_middle_lines.append(ln)
                mid_piece.text = "\n".join(kept_middle_lines)
            texts: list[str] = []
            body_parts: list[str] = []
            slot_done = False

            def _flush() -> None:
                nonlocal slot_done
                if slot_done:
                    return
                slot_done = True
                if body_parts:
                    body = "\n".join(body_parts)
                    texts.append(
                        f"<Global_Context>\n{escape_xml_text(body)}\n"
                        f"</Global_Context>")

            for piece in sorted(final_allocation.pieces,
                                key=lambda p: p.position):
                if piece.kind in ("global_head", "global_middle",
                                  "global_tail"):
                    if piece.text:
                        body_parts.append(piece.text)
                    continue
                if not slot_done and piece.position > 6:
                    _flush()
                if piece.text:
                    texts.append(piece.text)
            _flush()
            return texts, kept_middle_lines

        final_texts, middle_lines = _finalize_allocation(allocation)

        # ── v6 D04 (§18C.4/§18C.2): реальные окна L2 для evidence capacity
        # (первичная модель) и L2 fallback-репака (fallback-модель) —
        # независимо от наличия fallback.
        if out_fallback is not None:
            try:
                out_fallback["l2_input_budget"] = int(budget)
            except Exception:
                pass
            try:
                if fallback_recompose_budget is not None:
                    out_fallback["l2_fallback_budget"] = \
                        int(fallback_recompose_budget)
            except Exception:
                pass

        # ── ASAP-3.1 §14/§42: fallback recompose factory ───────────────────
        # При переключении на fallback с меньшим окном payload пересобирается
        # под ЕГО бюджет (P0 сохраняется; pressure/overflow observable).
        # ASAP-3.2 (ADR-1028-5 D10, §45): ``extra_reserve`` — токены tool
        # schemas (обязательная часть mandatory payload), вычитаются из
        # fallback-бюджета ДО recompose — tool schemas входят в fallback
        # budget наравне с system/persona/messages.
        if out_fallback is not None and fallback_recompose_budget is not None:
            def _fallback_adapter_factory(time_line: str | None,
                                          extra_reserve: int = 0):
                def _adapt(incoming: dict):
                    try:
                        _fb_budget = fallback_recompose_budget
                        if extra_reserve:
                            _fb_budget = max(1, _fb_budget - int(extra_reserve))
                        fb_allocation = _composer.allocate_budget(
                            _new_pieces(), _fb_budget,
                            truncator=self._composer_truncate)
                        fb_texts, _ = _finalize_allocation(fb_allocation)
                        blocks = ([time_line] if time_line else []) + fb_texts
                        messages = incoming.get("messages") or []
                        adapted = dict(incoming)
                        adapted["messages"] = [
                            {"role": "system",
                             "content": str(messages[0].get("content", "")
                                             if messages else "")},
                            {"role": "user",
                             "content": "\n\n".join(blocks)},
                        ]
                        logger.info(
                            "direct: fallback recompose | chat=%s | "
                            "budget=%d | tools_reserve=%d | blocks=%d",
                            chat_id, _fb_budget, int(extra_reserve or 0),
                            len(fb_texts))
                        return adapted
                    except Exception:
                        # ADR-1028-5 D10 (усиление): recompose failure —
                        # громкая oversized-risk диагностика (НЕ тихий
                        # fail-open); payload отправляется прежний (сервис
                        # не рвём, паритет fail-open ASAP-3.1).
                        logger.warning(
                            "direct: fallback recompose FAILED — primary "
                            "payload SENT AS-IS | oversized_risk=1 | "
                            "chat=%s", chat_id, exc_info=True)
                        return incoming
                return _adapt
            try:
                out_fallback["adapter_factory"] = _fallback_adapter_factory
            except Exception:
                pass

        # ── H2/D6 (rework round 1): сигнал зажатия пола fresh tail — при
        # фактическом давлении tail стоит на минимуме
        # CHAT_FRESH_TAIL_MIN_MESSAGES (ниже — только путь §17:
        # CONTEXT_PHYSICAL_OVERFLOW + счётчик).
        try:
            tail_piece = next((p for p in allocation.pieces
                               if p.kind == "global_tail"), None)
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
            logger.debug("direct: tail floor clamp event failed",
                         exc_info=True)

        # ── Observability (§32/§33) + diagnostics (§34) ──
        used_tokens = sum(count_tokens(t) for t in final_texts)
        record_context_usage(used_tokens,
                             None if policy_mode == "unlimited" else budget,
                             bool(allocation.excluded),
                             unlimited=(policy_mode == "unlimited"))
        # ASAP-3.1 §50: observed-слой для Analytics автобюджетов (read-side,
        # process-local; НЕ вторая система usage — числа существующего прогона).
        try:
            _auto_budget.record_slot_observation("direct.primary",
                                                 used_tokens)
            if allocation.excluded or allocation.compressed_or_dropped \
                    or allocation.physical_overflow:
                _auto_budget.record_slot_pressure(
                    "direct.primary",
                    physical_overflow=bool(allocation.physical_overflow))
        except Exception:
            pass
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

    async def _run_correction_path(self, chat_id: int, query: str,
                                   trigger_tg_id: int | None) -> None:
        """MCA-22 (C8, T-4305/T-4306; ADR-1028-6 D9): correction/revalidation
        над СУЩЕСТВУЮЩЕЙ provenance-схемой (второй статусный контур запрещён).

        * фраза-триггер → `plan_correction` (детерминированно, без LLM);
        * кандидаты — bounded FTS по граф-фактам чата (≤5);
        * только provenance-backed факты (есть object SourceRef) получают
          `contradicts`-EvidenceLink (verification='tentative') + конфликт
          `conflicting` — disputed = проекция conflicting, новых enum нет;
        * legacy-факты (без SourceRef) НЕ auto-bind'ятся по похожему имени
          (§31 — прямой запрет); revalidation неприменима честно;
        * «исправлено» НЕ пишется — есть только противоречащее утверждение;
          пере-проверка (reconstruct_fact_provenance) решает исход.
        Никогда не бросает (fire-and-forget путь)."""
        if self.db is None:
            return
        try:
            plan = _gprov.plan_correction(message_text=query)
            if not plan.triggered:
                return
            keywords = re.findall(r"[а-яёa-z0-9]+",
                                  str(query or "").casefold())[:6]
            if not keywords:
                return
            from services.summary_memory import build_fts_query
            match = build_fts_query(keywords)
            if not match:
                return
            rows = await self.db.search_graph_facts_fts(
                chat_id, match, limit=5, now_ts=int(time.time()))
            if not rows:
                return
            fact_ids = [int(r["id"]) for r in rows]
            resolved = await self.db.resolve_source_ref_ids(
                chat_id, [("graph_fact", str(fid)) for fid in fact_ids])
            # SourceRef корректирующего сообщения (создаётся по требованию —
            # существующий get-or-create контракт mca-04a).
            correction_ref_id = None
            if trigger_tg_id is not None:
                correction_ref_id = await _prov.resolve_source_ref(
                    self.db, _prov.SourceRef(
                        store="sqlite", entity_type="message",
                        entity_id=f"tg:{int(trigger_tg_id)}",
                        chat_id=int(chat_id),
                        tg_message_id=int(trigger_tg_id),
                        resolution="resolved"))
            queued = 0
            for fid in fact_ids:
                ref_id = resolved.get(("graph_fact", str(fid)))
                if ref_id is None:
                    continue          # legacy — без auto-bind (§31)
                if correction_ref_id is not None:
                    await _prov.add_evidence_link(self.db, _prov.EvidenceLink(
                        subject_ref_id=ref_id,
                        source_ref_id=correction_ref_id,
                        link_type=plan.evidence_link_type,
                        method="direct_reference",
                        verification=plan.verification,
                        independence="independent",
                        claim_key=None,
                        basis=None,
                        established_at=int(time.time())))
                await _prov.set_provenance_status(
                    self.db, ref_id, conflict_status=plan.conflict_status)
                queued += 1
            _fresh.emit_freshness_event(
                "CORRECTION_REVALIDATION_QUEUED", outcome="success",
                reason_code="correction_revalidation_queued",
                chat_id=chat_id, message_id=trigger_tg_id,
                attempt=queued)
            logger.info("[mca22] correction path queued | chat=%s | facts=%d",
                        chat_id, queued)
        except Exception:
            logger.warning("[mca22] correction path failed — skip | chat=%s",
                           chat_id, exc_info=True)

    async def _build_evidence_bundle(self, chat_id: int, message, query: str,                                     target_name: str, user_id,
                                     user_blocks: list, *,
                                     excluded: list | None = None,
                                     chosen_intent: str | None = None,
                                     trace_id: str | None = None):
        """MCA-07 (T-3852, ADR-1027-7 D5/D6): собрать ЕДИНЫЙ in-memory
        `EvidenceBundle` из уже построенных user-блоков (без нового I/O и без
        второго контракта). Ссылается на канонические ID-ссылки (`tg:/msg:/
        fact:`), не копирует архив. Gate OFF → ``None`` (точный legacy-путь).
        Fail-open: ошибка сборки → ``None`` (контекст не рвётся).

        MCA-16 (AM-1, D6, T-4993): `lessons` — отдельный тип в ЭТОМ ЖЕ
        bundle (отбор: scope/active → compat → relevance → utility); K1/K4
        OFF → пусто (байт-паритет 2.58.58). Второго bundle нет."""
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
            # M-MCA07-2 (mca-05, ADR-1027-12 D11): владелец наполнения
            # `local_context` — EpisodeService (истории, содержащие текущее
            # сообщение). Пусто → инвариант «not_available» (tuple());
            # fail-open: ошибка не рвёт сборку контекста.
            local_context: tuple[str, ...] = ()
            try:
                from services import mca_gates as _mca_gates
                if _mca_gates.episodes_enabled():
                    from services.mca_episodes import build_local_context
                    local_context = await build_local_context(
                        self.db, chat_id,
                        trigger_tg_message_id=(
                            trigger_id if trigger_id is not None else None))
            except Exception:
                local_context = ()
            # ── MCA-22 (C6, T-4299; ADR-1028-6 D7): bundle v2 — раздельные
            # роли (author/direct_addressee/reply_addressee/quoted_speaker)
            # и реальные SourceRef — из СТРУКТУРНЫХ данных (полный ряд
            # MCA-03 + batched mca_source_refs), не из regex по строкам.
            # `MCA_CANONICAL_ATTRIBUTION_ENABLED=OFF` → точный legacy-
            # паритет (author==addressee==target_name, source_ref_id=None).
            v2_fields: dict = {}
            if mca_gates.canonical_attribution_enabled():
                try:
                    _row = (await self.db.get_smart_message_by_tg_id(
                        chat_id, trigger_id)
                        if (self.db is not None
                            and trigger_id is not None) else None)
                    _reply_author = (str(_row["reply_to_author_id"])
                                     if _row is not None and
                                     _row["reply_to_author_id"] is not None
                                     else None)
                    _quote_author = (str(_row["quote_author_id"])
                                     if _row is not None and
                                     _row["quote_author_id"] is not None
                                     else None)
                    # ── MCA-22 (C3, T-4290; fix round-1 M-2): живой вызов
                    # Quote Resolver из прод-пути. Metadata-first (§29):
                    # если ingestion уже знает автора цитаты
                    # (`quote_author_id`) — лестница не нужна. Иначе
                    # (ручные `>`-цитаты, копипаста, quote без автора)
                    # резолвим детерминированной лестницей 1–7 и
                    # заполняем `quoted_speaker`/evidence/ambiguities
                    # bundle v2. Fail-open: ошибка резолва не рвёт
                    # сборку контекста (legacy-поля).
                    _quote_res = None
                    _v2_ambiguities: tuple = ()
                    if _quote_author is None:
                        _quote_res = await self._resolve_quote_live(
                            chat_id, _row, query, user_id)
                        if _quote_res is not None and \
                                _quote_res.quote_speaker_entity_id is not None:
                            _quote_author = str(
                                _quote_res.quote_speaker_entity_id)
                        if _quote_res is not None and \
                                _quote_res.status == _qres.QUOTE_AMBIGUOUS:
                            # честная ambiguous-маркировка (не выдумываем
                            # автора; см. C3: ≥2 совпадения → ambiguous)
                            _v2_ambiguities = (
                                f"quote:priority_{_quote_res.priority}",)
                    _speaker = (str(_row["user_id"]) if _row is not None
                                and _row["user_id"] is not None
                                else target_name or None)
                    # Реальные SourceRef для fact-evidence: batched lookup
                    # (один SELECT, без N+1). message-ref'ы ветки резолвятся
                    # по entity_id tg:<id>.
                    _fact_pairs = [(("graph_fact"), ref.split(":", 1)[1])
                                   for ref in evidence_refs
                                   if ref.startswith("fact:")]
                    _msg_pairs = [(("message"), ref.split(":", 1)[1])
                                  for ref in (*branch, *evidence_refs)
                                  if ref.startswith("tg:")]
                    _resolved: dict = {}
                    if self.db is not None and (_fact_pairs or _msg_pairs):
                        _resolved = await self.db.resolve_source_ref_ids(
                            chat_id, [*_fact_pairs, *_msg_pairs])
                    def _sref(ref: str):
                        etype = ("graph_fact" if ref.startswith("fact:")
                                 else "message")
                        return _resolved.get((etype, ref.split(":", 1)[1]))
                    _evidence_v2 = []
                    if current_ref:
                        _evidence_v2.append(_mca_rc.EvidenceItem(
                            source_ref_id=_sref(current_ref),
                            entity_type="message", entity_id=current_ref,
                            label="current"))
                    for ref in evidence_refs:
                        _evidence_v2.append(_mca_rc.EvidenceItem(
                            source_ref_id=_sref(ref),
                            entity_type=("graph_fact"
                                         if ref.startswith("fact:")
                                         else "message"),
                            entity_id=ref))
                    if _quote_res is not None and _quote_res.quote_source_ref:
                        # цитата резолвлена к durable-источнику (ступень 5:
                        # Own Output Ledger `bot_output:<id>`) — отдельный
                        # evidence-item с реальным ref (не авторство, ссылка)
                        _evidence_v2.append(_mca_rc.EvidenceItem(
                            source_ref_id=None, entity_type="message",
                            entity_id=_quote_res.quote_source_ref,
                            label="quote"))
                    v2_fields = {
                        "author": _speaker,
                        "addressee": "bot",
                        "direct_addressee": "bot",
                        "reply_addressee": _reply_author,
                        "quoted_speaker": _quote_author,
                        "ambiguities": _v2_ambiguities,
                        "evidence": tuple(_evidence_v2),
                        "structured": True,
                    }
                except Exception:
                    logger.warning("[mca22] bundle v2 roles failed — legacy",
                                   exc_info=True)
                    v2_fields = {}
            # ── MCA-16 (T-4993, D6): отбор уроков в ТОТ ЖЕ bundle (K1+K4;
            # fail-open — ошибка отбора не рвёт контекст; пусто = паритет).
            lesson_refs: tuple = ()
            lesson_excluded: list = []
            try:
                _db = getattr(self, "db", None)
                if (_db is not None
                        and mca_gates.experience_lessons_enabled()
                        and mca_gates.experience_context_enabled()):
                    from services import mca_experience as _mca_exp
                    _sel = await _mca_exp.get_service(_db).lesson \
                        .select_for_context(
                            chat_id=chat_id, user_id=user_id,
                            task_type="direct_chat", query=query,
                            trace_id=trace_id)
                    lesson_refs = tuple(_sel.lessons)
                    lesson_excluded = list(_sel.excluded)
            except Exception:
                logger.warning("[mca16] lesson selection failed — no lessons",
                               exc_info=True)
                lesson_refs = ()
                lesson_excluded = []
            if lesson_excluded:
                excluded_items = excluded_items + tuple(
                    _mca_rc.ExcludedItem(
                        ref=str(item.get("ref") or ""),
                        position=int(item.get("position") or 0),
                        reason_code=str(item.get("reason_code") or ""),
                        estimated_tokens=int(item.get("estimated_tokens")
                                             or 0))
                    for item in lesson_excluded)
            return _mca_rc.EvidenceBundle(
                trigger=current_ref, current_message_ref=current_ref,
                current_revision=current_ref,
                addressee=v2_fields.pop("addressee", target_name or None),
                author=v2_fields.pop("author", target_name or None),
                mentioned=mentioned, branch=branch,
                local_context=local_context,
                evidence=v2_fields.pop("evidence", tuple(evidence)),
                constraints=constraints,
                relations=relations, chosen_intent=chosen_intent,
                recent_actions=recent_actions, context_version=context_version,
                excluded=excluded_items, lessons=lesson_refs, **v2_fields)
        except Exception:
            logger.warning("[mca07] evidence bundle build failed — None",
                           exc_info=True)
            return None

    @staticmethod
    def _rowval(row, key: str):
        """Безопасное чтение колонки sqlite-Row (отсутствует → None)."""
        try:
            if row is None or key not in row.keys():
                return None
            return row[key]
        except Exception:
            return None

    async def _resolve_quote_live(self, chat_id: int, row, query: str,
                                  sender_user_id: int | None):
        """MCA-22 (C3, T-4290; fix round-1 M-2): живой prod-вызов Quote
        Resolver из direct-пути (раньше модуль был test-only).

        Вход — metadata текущего сообщения (ingested-ряд MCA-03: reply/
        quote-поля) + ручные `>`-цитаты из текста. `thread_texts` не
        передаётся (окно уже собрано композером; лестница падает на
        ledger/FTS-ступени 5–6). Gate canonical OFF → None (паритет).
        Никогда не бросает; None/`unresolved` — честный unknown."""
        if not mca_gates.canonical_attribution_enabled():
            return None
        try:
            manual_lines = [
                ln.strip()[1:].strip()
                for ln in str(query or "").splitlines()
                if ln.strip().startswith(">") and len(ln.strip()) > 1]
            manual_quote = "\n".join(
                ln for ln in manual_lines if ln)[:512] or None
            return await _qres.resolve_quote(
                self.db, chat_id=chat_id,
                sender_entity_id=(self._rowval(row, "user_id")
                                  or sender_user_id),
                quote_text=manual_quote,
                reply_to_tg_message_id=self._rowval(row, "reply_to_id"),
                reply_to_speaker_entity_id=self._rowval(
                    row, "reply_to_author_id"),
                tg_quote_text=self._rowval(row, "quote_text"),
                bot_user_id=self.bot_id,
                thread_texts=None,
                exclude_tg_message_id=self._rowval(row, "tg_message_id"))
        except Exception:
            logger.warning("[mca22] live quote resolve failed — unknown",
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

    def _render_current_question(self, message, extra_markers=()) -> str:
        """Раунд 8 (D1/T-798, spec §3.D1): блок <Current_Question> — текст
        текущего сообщения после среза обращения «бот(@ник):»; cap
        limits.chat_current_question_max_chars (default 800); НЕ режется
        бюджетом (kind вне лимитов). Пустой после среза — без блока.

        Раунд 10.24 (F13, ADR-1024-14 D3): к тексту дописываются медиа-маркеры
        нативного медиа самого сообщения и ``reply_to_message`` (``tg:<id>``).
        При пустом тексте с медиа блок не пуст; при непустом — текст усекается
        до резерва под суффикс, маркер гарантированно выживает. Флаг OFF или
        отсутствие медиа → ровно прежний ``stripped[:cap]`` (байт-в-байт).

        ADD-TR.2 (ADTR-ENTRY, 19.10.2026): текст = text ИЛИ caption подписи
        (``_message_user_text``) — подпись photo/document-image доходит до
        семантических путей тем же блоком; ``extra_markers`` — доверенные
        маркеры способа (C) (резолв ранее присланного изображения,
        `_resolve_earlier_image_markers`), тот же диалект, что own/reply.
        Пустые extra_markers → байт-в-байт прежний результат."""
        stripped = _strip_direct_prefix(_message_user_text(message))
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
            for extra in extra_markers or ():
                extra_text = str(extra or "")
                if extra_text:
                    markers.append(extra_text)
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

    async def _resolve_earlier_image_markers(self, chat_id: int,
                                             message) -> tuple:
        """ADD-TR.2 (ADTR-ENTRY, M-ADTR-ENTRY-REFS способ C, 19.10.2026):
        «явная ссылка на ранее присланное в чате изображение, однозначно
        разрешимая».

        Срабатывает ТОЛЬКО когда событие само не несёт цель: нет медиа в
        сообщении, нет reply-цели (способы A/B уже дают MessageRef через
        свои маркеры) и в тексте/подписи есть явное обращение к изображению
        (`mca_vision.vision_intent` — канонический список). Кандидаты —
        канонический реестр MCA-19 ``mca_media_assets`` текущего чата
        (bounded-окно ``_EARLIER_IMAGE_WINDOW_SECONDS``, запись гейтится
        env-мастером vision; второго реестра/скана нет). Однозначность:
        ровно ОДНО изображение-сообщение в окне (kind ∈
        ``_IMAGE_REF_KINDS``, старее текущего) → маркер того же диалекта,
        что own/reply; пусто/несколько/ошибка → ``()`` — цель НЕ выдумываем
        (уточнение — штатный clarify-путь L1/Writer). Fail-open, никогда
        не бросает."""
        try:
            if not media_context_enabled():
                return ()                      # kill-switch маркеров — паритет
            if message_media_type(message) is not None:
                return ()                      # (A): цель — само сообщение
            if getattr(message, "reply_to_message", None) is not None:
                return ()                      # (B): цель уже сужена reply'ем
            query = _message_user_text(message)
            if not query:
                return ()
            from services import mca_vision
            if not mca_vision.vision_intent(query):
                return ()
            db = getattr(self, "db", None)
            if db is None or getattr(db, "db", None) is None:
                return ()
            current_id = getattr(message, "message_id", None)
            try:
                current_id = (int(current_id)
                              if current_id is not None else None)
            except (TypeError, ValueError):
                current_id = None
            cutoff = int(time.time()) - _EARLIER_IMAGE_WINDOW_SECONDS
            cursor = await db.db.execute(
                "SELECT tg_message_id, asset_kind FROM mca_media_assets "
                "WHERE chat_id=? AND created_at>=? "
                "ORDER BY tg_message_id DESC LIMIT ?",
                (int(chat_id), cutoff, _EARLIER_IMAGE_SCAN_LIMIT))
            rows = await cursor.fetchall()
            seen: dict[int, str] = {}
            for row in rows:
                try:
                    tg_id = int(row["tg_message_id"] or 0)
                    kind = str(row["asset_kind"] or "")
                except (TypeError, ValueError, KeyError, IndexError):
                    continue
                if tg_id <= 0 or kind not in _IMAGE_REF_KINDS:
                    continue
                if current_id is not None and tg_id >= current_id:
                    continue        # текущее/будущее — не «ранее присланное»
                seen.setdefault(tg_id, kind)
            if len(seen) != 1:
                return ()           # пусто или неоднозначно — без «угаданной» цели
            tg_id, kind = next(iter(seen.items()))
            logger.info(
                "[adtr-entry] earlier-image target resolved | chat=%s | "
                "kind=%s tg=%s", chat_id, kind, tg_id)
            return (media_marker(kind, f"tg:{tg_id}"),)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("[adtr] earlier-image resolve failed — skipped",
                         exc_info=True)
            return ()

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

    def _stats_intent_block(self, chat_id: int, query: str, reply_text: str,
                            addressed: bool):
        """MCA-15 (T-4920/T-4921, ADR-1028-12 D6; K3): детерминированный
        intent хода + короткий stats-хинт.

        Возвращает ``(block, StatsIntent | None)``. Хинт — только для
        `chat_statistics`/`mixed` и адресованных сообщений; для
        `social_banter` хинта нет (подкол не получает обязательный отчёт),
        инструменты при этом НЕ блокируются. Событие `stats_intent` —
        notable-only (per-reply «успехов» нет), R17-safe (код цели, без
        текста). K3 OFF/ошибка → ("", None) — паритет 2.58.55."""
        if not mca_gates.stats_intent_enabled():
            return "", None
        try:
            from services import chat_statistics as _cs
            intent = _cs.classify_stats_intent(
                query, reply_parent=reply_text, addressed=addressed)
            if intent.notable:
                _mca_events.emit_mca_event(
                    "stats_intent", outcome="success",
                    component="direct_chat",
                    reason_code=intent.reason_code, chat_id=chat_id)
            block = _cs.stats_hint_block() if intent.stats_hint else ""
            return block, intent
        except Exception:
            logger.warning("[mca15] stats intent classify failed — skip",
                           exc_info=True)
            return "", None

    def _numeric_contract_from_ctx(self, tool_ctx):
        """MCA-15 (T-4931, D5; K2): NumericContract хода из per-turn
        `ctx.metric_results` + intent.

        ``None`` → гард не активен (K2 OFF/ошибка/нет контекста — паритет).
        Claims — только ok/partial с числом (ошибка/unsupported → нет claim,
        число не подтверждено); `stats_expected` — запрашивали ли статистику
        (для честной оговорки вместо выдуманного числа)."""
        if tool_ctx is None or not mca_gates.numeric_claim_guard_enabled():
            return None
        try:
            from services import chat_statistics as _cs
            results = list(getattr(tool_ctx, "metric_results", None) or [])
            claims: list = []
            verified_phrase = ""
            for result in results:
                claims.extend(_cs.claims_for_result(result))
                if not verified_phrase:
                    verified_phrase = str(
                        getattr(result, "verified_phrase", "") or "")
            stats_expected = str(
                getattr(tool_ctx, "stats_intent", "") or "") in (
                _cs.INTENT_CHAT_STATISTICS, _cs.INTENT_MIXED)
            return _nc.NumericContract(
                claims=tuple(claims), verified_phrase=verified_phrase,
                stats_expected=stats_expected)
        except Exception:
            logger.warning("[mca15] numeric contract build failed — skip",
                           exc_info=True)
            return None

    async def _image_capability_gate(self, chat_id: int, query: str, message,
                                     bot, *, reply_text: str = ""
                                     ) -> tuple[bool, object]:
        """SOUL-1 W10 (§5.1/5.3/5.9/5.14): смысловое поручение → capability.

        Дешёвая детерминированная проверка ДО платных стадий (0 LLM):
        ``detect_action_intent`` распознаёт поручение создать изображение по
        смыслу, затем состояние `image_generation` берётся из runtime-реестра
        (`services/capability_registry` — реальные модуль/ключ/квота/провайдер
        этого чата).

        Возврат ``(handled, intent)``: ``handled=True`` — ответ уже отправлен
        из УПРАВЛЯЕМОГО шаблона реестра (неготовый инструмент либо один
        уточняющий вопрос при неоднозначности), ход завершается; ``False`` —
        либо это не поручение изображения, либо capability готова и генерация
        идёт существующим единственным путём. Fail-open: любая ошибка → False
        (обычный ход, без выдуманных отказов).

        ``forwarded`` (review-w10 F2): пересланное сообщение — чужие слова, не
        поручение пользователя (детектор отдаёт не-поручение с наблюдаемой
        причиной ``create_image_forwarded``)."""
        from services import capability_registry as _capreg
        try:
            intent = _caps.detect_action_intent(
                query, reply_text=reply_text, addressed=True,
                forwarded=bool(_forward_source_of(message)))
            if intent.intent != _caps.INTENT_CREATE_IMAGE:
                return False, intent
            if intent.confidence == _caps.CONFIDENCE_AMBIGUOUS:
                # §5.9: ровно ОДИН короткий уточняющий вопрос вместо генерации.
                text, block_id, _src = _capreg.clarify_text()
                await _reply(bot, chat_id, text, message.message_id)
                self._mark_turn_text_replied(chat_id)
                logger.info("[direct] capability clarify | chat=%s | reason=%s "
                            "| template=%s", chat_id, intent.reason, block_id)
                _capreg.emit_capability_event(
                    _capreg.CapabilityState(
                        capability_id="image_generation",
                        status=_capreg.STATUS_UNKNOWN,
                        reason_code=intent.reason),
                    outcome="skipped", chat_id=chat_id, template_id=block_id)
                return True, intent
            state = await _capreg.resolve("image_generation", chat_id)
            if not state.available:
                # §5.14: «не умею» только после проверки — и с реальной
                # причиной (выключено/нет ключа/провайдер/квота), в голосе
                # бота, из редактируемого Factory Default-шаблона.
                text, block_id, _src = _capreg.status_message(state)
                await _reply(bot, chat_id, text, message.message_id)
                self._mark_turn_text_replied(chat_id)
                logger.info(
                    "[direct] capability not ready | chat=%s | cap=%s | "
                    "status=%s | reason=%s | template=%s",
                    chat_id, state.capability_id, state.status,
                    state.reason_code, block_id)
                _capreg.emit_capability_event(state, outcome="failed",
                                              chat_id=chat_id,
                                              template_id=block_id)
                return True, intent
            return False, intent
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("direct: capability gate failed — обычный ход | "
                           "chat=%s", chat_id, exc_info=True)
            return False, None

    async def _l1_capability_consistency(self, chat_id: int, query: str,
                                         message, bot, l1_plan, *,
                                         intent, image_pre_gate_fired: bool,
                                         correlation_id: str | None = None
                                         ) -> tuple[str, bool, tuple]:
        """SOUL-1 W10 (§5.10/§5.14): дешёвая проверка согласованности решения
        L1 с РЕАЛЬНЫМ состоянием capability (0 LLM; TTL-кеш реестра).

        Возврат ``(блок_для_инъекции, генерация_выполнена, denied)``:

        * L1 запросил capability, которой в этом чате нет → capability
          отбрасывается (``denied``: инструмент не анонсируется, отказ с
          наблюдаемым кодом) + правдивая пометка ``<capability_notice>``
          Writer'у (обещать недоступное запрещено);
        * смысловое поручение создать изображение + capability готова, но L1
          выбрал обычный текст → маршрутизация исправляется В ЭТОМ ЖЕ ходу:
          тот же единственный путь генерации/доставки, ровно один вызов
          (наблюдаемый случай «доступное действие не было выбрано L1», §6.5);
        * capability не готова → инъекция правдивого состояния, без вызова.

        Никогда не бросает (любая ошибка → ``("", False, ())``)."""
        from services import capability_registry as _capreg
        block = ""
        fired = False
        denied: list[str] = []
        try:
            plan = l1_plan or _l1.L1Plan()
            requested = tuple(str(c) for c in
                              (getattr(plan, "capabilities_needed", ()) or ()))
            state = None
            if "image_generation" in requested or (
                    intent is not None and intent.intent
                    == _caps.INTENT_CREATE_IMAGE):
                state = await _capreg.resolve("image_generation", chat_id)
            if state is not None and not state.available:
                blockers = _caps.intent_blockers(
                    intent, capability_status=state.status)
                if "image_generation" in requested:
                    denied.append("image_generation")
                    _capreg.emit_capability_event(
                        state, outcome="failed", chat_id=chat_id,
                        trace_id=correlation_id or "")
                    try:
                        _caps.emit_capability_rejected(
                            "image_generation", state.reason_code or
                            state.status, chat_id=chat_id,
                            run_id=correlation_id)
                    except Exception:      # pragma: no cover
                        pass
                if blockers:
                    logger.info(
                        "[direct] capability blockers | chat=%s | cap=%s | "
                        "blockers=%s | status=%s", chat_id,
                        state.capability_id, ",".join(blockers), state.status)
                block = _capreg.notice_block(state)
            elif (state is not None and state.available
                    and not image_pre_gate_fired
                    and intent is not None and intent.actionable
                    and "image_generation" not in requested):
                # §5.10: исправление маршрутизации в рамках хода — тот же
                # единственный путь (генерация+доставка), без второго LLM.
                # ``intent_confirms`` открывает смысловую дверь пре-гейта: L1
                # выбрал обычный текст при однозначно доступном действии.
                fired_block = await self._image_pre_gate_block(
                    chat_id, query, bot, message,
                    getattr(getattr(message, "from_user", None), "id", 0) or 0,
                    correlation_id=correlation_id, intent=intent,
                    intent_confirms=True)
                if fired_block:
                    block = fired_block
                    fired = True
                    blockers = _caps.intent_blockers(
                        intent, capability_status=state.status)
                    logger.info(
                        "[direct] capability routing fixed | chat=%s | "
                        "cap=%s | l1_capabilities=%s | reason=%s | blockers=%s",
                        chat_id, state.capability_id, ",".join(requested),
                        intent.reason, ",".join(blockers) or "-")
                    _capreg.emit_capability_event(
                        state, outcome="success", chat_id=chat_id,
                        trace_id=correlation_id or "")
                    try:
                        from services.agentic_events import (
                            L1_CAPABILITY_REJECTED, emit_agentic_event)
                        emit_agentic_event(
                            L1_CAPABILITY_REJECTED,
                            capability="image_generation",
                            reason="available_action_not_chosen" + (
                                ":" + ",".join(blockers) if blockers else ""),
                            chat_id=chat_id, run_id=correlation_id)
                    except Exception:      # pragma: no cover
                        pass
            # Прочие запрошенные capability (§5.18): недоступное не обещаем —
            # правдивая пометка Writer'у + наблюдаемый блокер. Инструмент НЕ
            # прячем (анонс остаётся контрактом §1.4); отказ виден в trace.
            # Выдуманные L1 имена сюда не попадают: их уже отбрасывает
            # `resolve_capabilities` с честной пометкой (§1.4/D15).
            others = [c for c in requested
                      if c != "image_generation"
                      and c.strip().lower() in _caps.CAPABILITY_TOOLS]
            if others:
                states = await _capreg.resolve_many(others, chat_id)
                notes = [_capreg.notice_block(s) for s in states
                         if not s.available]
                notes = [n for n in notes if n]
                if notes:
                    block = (block + "\n" + "\n".join(notes)).strip()
                for s in states:
                    if not s.available:
                        _capreg.emit_capability_event(
                            s, outcome="failed", chat_id=chat_id,
                            trace_id=correlation_id or "")
            return block, fired, tuple(denied)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("direct: capability consistency check failed | "
                           "chat=%s", chat_id, exc_info=True)
            return "", False, ()

    async def _image_pre_gate_block(self, chat_id: int, query: str, bot,
                                    message, user_id,
                                    correlation_id: str | None = None,
                                    intent=None,
                                    intent_confirms: bool = False) -> str:
        """Раунд 10.23 (F5, ADR-1023-5 §D2): пре-гейт ключевиков генерации
        изображений («Бот, нарисуй …»). Генерация+отправка ДО Stage-1, блок
        ``<image_result>`` для инъекции. `tool_choice` НЕ форсируется. Нет
        ключевика/модуль OFF/нет бота → ``""``. Fail-open — не бросает.
        F7 rework: ``correlation_id`` ответа прокидывается в ToolContext, чтобы
        событие ``step='image'`` попало в дерево последнего вызова.
        SOUL-1 W10 fix (review-w10 F2): смысловой ``intent`` — VETO для
        регекса: не-поручение (``actionable=False``: отрицание/«придумать»/
        цитата/«я сам»/пересылка) подавляет быстрый путь. Дверь открывает
        регекс ИЛИ ``intent_confirms=True`` (подтверждённое смысловое
        поручение — путь согласованности §5.10, где L1 не выбрал доступное
        действие: наблюдаемый случай §6.5 остаётся живым)."""
        from services import image_generation
        # Смысловой вердикт главнее регекса: отрицание не может проиграть
        # быстрому пути («Бот, нарисуй мем, но не рисуй» → генерации нет).
        if intent is not None and not getattr(intent, "actionable", False):
            return ""
        if not (image_generation.is_image_keyword(query) or intent_confirms):
            return ""
        if _forward_source_of(message):
            # Пересланное сообщение — чужие слова, не поручение пользователя.
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
                tool_ctx, query, **deps,
                intent_confirmed=bool(intent is not None
                                      and getattr(intent, "actionable",
                                                  False)))
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
                f"и того же слова; настройки выражения владельца важнее "
                f"образца:\n{body}\n</style_anchors>")

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
            result = await self.memory.remember_user_fact(
                chat_id, fact_text, target_user=target_user,
                ttl_days=hot.get("limits.memory_commands_remember_ttl_days",
                                 settings.MEMORY_COMMANDS_REMEMBER_TTL_DAYS))
            # MCA-22 (C4, T-4292/T-4293): «skipped_gated» — write-gating
            # producer-validator'а (negation/gated speech act); маппится в
            # существующую ветку «denied» (фраза отказа), факт не записан.
            if result == "skipped_gated":
                return "denied"
            return result
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

    # ── ASAP 8 (F6, §13.2): инициативные решение/генерация СУЩЕСТВУЮЩИМ
    # Direct-контуром (L1-модель + L2 Writer). Третьего Writer нет (§13.2).

    async def _initiative_persona_block(self, chat_id: int) -> str:
        """Кадр личности/self-model для инициативного контекста — тот же
        владелец основы, что у direct-промпта (persona gate per-chat; K1
        слои уважаются). Fail-open → ''."""
        try:
            from services.chat_params import get_chat_param as _cpg
            persona_enabled = await _cpg(
                chat_id, "flags.persona_enabled",
                hot.get("flags.persona_enabled", settings.PERSONA_ENABLED))
            if not persona_enabled:
                return ""
            if mca_gates.character_layers_enabled():
                ctx = await bot_persona.resolve_character_context(chat_id)
                block = bot_persona.build_persona_prompt_block(
                    ctx.persona, [str(t) for t in (ctx.traits or ())],
                    enabled=True)
                rules = bot_persona.build_character_rules_block()
                if block and rules:
                    block = block + "\n\n" + rules
                return block or ""
            persona = await bot_persona.resolve_bot_persona(chat_id)
            traits = await bot_persona.get_traits(
                int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50))
            texts = [str(t.get("text") or "") for t in (traits or ())]
            return bot_persona.build_persona_prompt_block(
                persona, texts, enabled=True) or ""
        except Exception:
            return ""

    async def plan_initiative_decision(self, chat_id: int,
                                       intent_row: dict, *,
                                       correlation_id: str | None = None
                                       ) -> "_l1.L1Plan | None":
        """F6 (§13.2): инициативное решение СУЩЕСТВУЮЩЕЙ L1-моделью
        (REPLY/REACT/SILENT + форма доставки, L1D 22.10.2026). L1 видит:
        окно переписки С id/reply-связями, недавние ответы бота, allowed-
        реакции, повод наблюдателя КАК ПРЕДЛОЖЕНИЕ (может отклонить). Форму
        участия (написать в чат / Telegram-reply на конкретное сообщение /
        реакция / молчание) выбирает ТОЛЬКО L1 — транспорта-резолвера больше
        нет. Один вызов L1 (без repair-лестницы — инициатива вторична:
        outage/невалидный JSON → None → SILENT, не повтор). Никогда не
        бросает."""
        try:
            window = await self.memory.get_window_messages(chat_id)
        except Exception:
            window = []
        try:
            window = [dict(r) for r in (window or ())]
        except Exception:
            pass
        persona_block = await self._initiative_persona_block(chat_id)
        bot_replies = await self._recent_bot_replies(chat_id)
        row = intent_row or {}
        goal = str(row.get("goal") or "").strip()
        kind = str(row.get("kind") or "")
        origin = str(row.get("origin") or "")
        # L1D: смысловой адресат от наблюдателя — КОНТЕКСТ для решения, не
        # команда: имя в окне + id, чтобы L1 могла выбрать форму обращения
        # (обычное сообщение с обращением ИЛИ reply на его сообщение).
        addressee_label = "чат"
        addressee_id = row.get("addressee_user_id")
        if addressee_id is not None:
            try:
                addressee_id = int(addressee_id)
            except (TypeError, ValueError):
                addressee_id = None
        if addressee_id is not None:
            name = ""
            for wr in window:
                try:
                    if int(wr.get("user_id") or 0) == addressee_id \
                            and str(wr.get("author_name") or "").strip():
                        name = str(wr["author_name"]).strip()
                        break
                except (TypeError, ValueError):
                    continue
            addressee_label = (f"участник {name} [user:{addressee_id}]"
                               if name else f"участник [user:{addressee_id}]")
        task = (
            "Никто бота не звал: решается уместность ИНИЦИАТИВЫ. "
            f"Предложение наблюдателя (можешь отклонить; kind={kind or 'unknown'}, "
            f"origin={origin or 'unknown'}): {goal or 'цель не указана'}. "
            "Оцени свежий контекст чата и выбери форму участия: написать "
            "в чат, ответить как reply на конкретное сообщение, поставить "
            "реакцию или промолчать. Умерший повод, ответ на него в "
            "контексте или нечего добавить - silent; бессмыслица и шум "
            "участников не обязаны становиться репликой.")
        # L1D: УСЛОВИЯ — равноправие форм + существующий allowed-набор
        # реакций (той же строкой, что прямой L1; прецедент P3 rootcause).
        _init_conditions = [_l1.INITIATIVE_LINE]
        if reaction_mechanics_enabled():
            _init_conditions.append(
                "разрешённые реакции: "
                + " ".join(_llm_react.ALLOWED_LLM_REACTIONS))
        context_text = _l1.build_l1_context(
            query=task, window=window, speaker="",
            addressee=addressee_label,
            capabilities=(),
            force_line="; ".join(_init_conditions),
            persona_frame=persona_block, bot_replies=bot_replies,
            with_ids=True)
        messages = [
            {"role": "system",
             "content": resolve_prompt(
                 "prompts.direct_l1_planner_system_prompt",
                 DIRECT_L1_PLANNER_SYSTEM_PROMPT)},
            {"role": "user", "content": context_text},
        ]
        # ── SOUL-1 (W2, §4 п.5): Initiative L1 — тот же машинный профиль.
        _init_l1_gates = await _composer_resolve_gates(chat_id)
        if _pcomp.composer_enabled_now(_init_l1_gates):
            _pcomp.emit_layer_events_once(
                _pcomp.compose_machine_system(
                    messages[0]["content"], writer="initiative_l1",
                    chat_id=chat_id, run_id=correlation_id))
        try:
            raw = await asyncio.wait_for(
                self.llm.generate(
                    messages, temperature=_l1.l1_temperature(None),
                    chat_id=chat_id, module="direct_chat",
                    step="l1_planner", correlation_id=correlation_id,
                    max_output_tokens=_l1.l1_max_output_tokens()),
                timeout=float(_l1.l1_timeout_seconds()))
        except Exception:
            logger.warning(
                "[f6] initiative L1 decision unavailable — silent | chat=%s",
                chat_id, exc_info=True)
            return None
        return _l1.parse_l1_plan(raw)

    async def generate_initiative_reply(self, chat_id: int,
                                        intent_row: dict, *,
                                        l1_plan=None,
                                        correlation_id: str | None = None
                                        ) -> str:
        """F6 (§13.2): текст инициативы — СУЩЕСТВУЮЩИЙ Direct L2 Writer
        (`_l2_write_answer`, Вербализатор-канал; step='l2_writer').
        Compact context: цель намерения + свежее окно чата + кадр личности;
        plan-блок от L1-решения. Пустой результат → '' (вызывающий решает
        writer_failed). Никогда не бросает."""
        try:
            window = await self.memory.get_window_messages(chat_id)
        except Exception:
            window = []
        try:
            window = [dict(r) for r in (window or ())]
        except Exception:
            pass
        persona_block = await self._initiative_persona_block(chat_id)
        row = intent_row or {}
        goal = str(row.get("goal") or "").strip()
        kind = str(row.get("kind") or "")
        origin = str(row.get("origin") or "")
        context_block = (
            "<Initiative_Context>\n"
            "Ты проявляешь инициативу сам (никто бота не звал). Держись "
            "в рамках ожидаемой полноты и естественно, как участник чата; "
            "не устраивай доклад.\n"
            f"Предложение наблюдателя (kind={kind or 'unknown'}, "
            f"origin={origin or 'unknown'}): {goal or 'цель не указана'}\n"
            "Не переспрашивай то, на что в свежем контексте уже ответили.\n"
            "</Initiative_Context>")
        # L1D: окно Writer с теми же [msg:N]/[user:UID] id, что видел L1, —
        # форма доставки из плана ссылается на конкретное сообщение.
        window_block = _l1.render_window_lines(window, 12, with_ids=True)
        user_blocks = [context_block]
        if window_block:
            user_blocks.append("<Fresh_Chat_Window>\n" +
                               "\n".join(window_block) +
                               "\n</Fresh_Chat_Window>")
        try:
            plan = l1_plan or _l1.L1Plan()
            response_plan = plan.to_response_plan() \
                if hasattr(plan, "to_response_plan") else None
            plan_block = _l1.build_l2_plan_block(
                plan,
                rejected=(),
                include_delivery=True) \
                if getattr(plan, "source", "") != "fallback" else ""
            temperature = settings.tone_temperature(None)
            result = await self._l2_write_answer(
                chat_id, goal or "инициатива", temperature=temperature,
                correlation_id=correlation_id,
                character_block=persona_block, response_plan=response_plan,
                plan_block=plan_block, user_blocks=user_blocks,
                writer="initiative_writer", max_tokens=700)
        except Exception:
            logger.warning(
                "[f6] initiative writer failed | chat=%s", chat_id,
                exc_info=True)
            return ""
        if not result:
            return ""
        prepared = str(result[0] or "").strip()
        # ── SOUL-1 (W3, SOUL-16.4.1 + SOUL-AMD.3.5, fix F4 review-w3): проход
        # формы здесь НЕ выполняется — единственная точка применения для
        # инициативных текстов это `handle_initiative` (перед чанкованием и
        # отправкой), иначе ностальгия/`prepared_text` обходила бы проход, а
        # writer-текст проходил бы его дважды (SOUL-16.4.2 «один проход»).
        return prepared


# ═════════════════════════════════════════════════════════════════════════════
# MCA-09 (ADR-1028-16 D1/D6; T-5038): единый вход инициативы (без входящего
# сообщения). Тот же CoordinatorDecision, тот же слой A7 (silent-семантика),
# ЕДИНСТВЕННЫЙ транспорт services/telegram_send.py; второго send-path нет.
# ═════════════════════════════════════════════════════════════════════════════

# ── ASAP 8 (F6, §13.1): детерминированные producers ──────────────────────────
# Никакого LLM-письма в DB и никаких intent на каждое сообщение: intent создаёт
# СЕРВИС по явному событию. Параметры — константы модуля (новых каталог-ключей
# нет, Δcatalog=0); пороги качества не ослабляются (§28.16).
INITIATIVE_UNANSWERED_DELAY_SECONDS = 900      # due не раньше чем через 15 мин
INITIATIVE_UNANSWERED_TTL_SECONDS = 3 * 86400  # срок жизни намерения
_F6_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_F6_MIN_QUESTION_CHARS = 2


def _f6_question_subject_token(query: str) -> str | None:
    """Детерминированный subject намерения по СОДЕРЖАНИЮ вопроса (не по
    message_id — повторный тот же вопрос дедуп-слится, а не заспамит).
    URL вырезаются ('?' в ссылке — не вопрос), команды пропускаются.
    R17-safe: наружу только хэш-токен."""
    text = _F6_URL_RE.sub(" ", str(query or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if not text.startswith("/") and "?" in text and \
            len(text) >= _F6_MIN_QUESTION_CHARS:
        return "q:" + _mca_intents._sha1_16(text.casefold())
    return None


async def _f6_maybe_create_unanswered_question(
        db, chat_id: int, query: str,
        tg_message_id: int | None) -> tuple[str | None, bool]:
    """Producer `unanswered_question` (F6 §13.1): конец Direct-хода —
    пользовательское сообщение с '?' и бот НЕ отправил reply в этом ходе →
    durable `follow_up` (activation time_due, bounded TTL). Гейты/дедуп/
    дисциплина origin — в `IntentService.create_intent`; кап pending на чат —
    существующий `limits.intent_candidates_max` (новый порог не вводится).
    Возвращает (intent_id, created); никогда не бросает."""
    if db is None or not mca_gates.intents_enabled():
        return None, False
    subject = _f6_question_subject_token(query)
    if subject is None:
        return None, False
    try:
        service = _mca_intents.get_service(db)
        active = await service.store.count_active(int(chat_id))
        if active >= mca_gates.intent_candidates_max():
            logger.info(
                "[f6] unanswered_question skipped: pending cap | chat=%s",
                chat_id)
            return None, False
        now = int(time.time())
        refs = ((f"msg:{int(tg_message_id)}",)
                if tg_message_id is not None else ())
        return await service.create_intent(
            int(chat_id), kind="follow_up", origin="unanswered_question",
            subject_ids=(subject,), goal=query, reason=None,
            source_refs=refs,
            not_before=now + INITIATIVE_UNANSWERED_DELAY_SECONDS,
            expires_at=now + INITIATIVE_UNANSWERED_TTL_SECONDS,
            activation_condition="time_due")
    except Exception:
        logger.warning("[f6] unanswered_question create failed — skipped",
                       exc_info=True)
        return None, False


async def _f6_create_future_intent(db, chat_id: int, future_intent,
                                   tg_message_id: int | None) -> \
        tuple[str | None, bool]:
    """Producer `explicit_request` (F6 §13.1): allowlisted future-intent от
    L1 (валидность схемы гарантирует парсер direct_l1.normalize_l1_plan).
    intent пишет СЕРВИС; дедуп — по содержанию цели (q-hash в topic_refs,
    subject пуст → ключ (chat, kind, цель)). Никогда не бросает."""
    if db is None or future_intent is None:
        return None, False
    kind = str(getattr(future_intent, "kind", "") or "")
    goal = str(getattr(future_intent, "goal", "") or "")
    if kind not in _mca_intents.INTENT_KINDS or not goal.strip():
        return None, False
    try:
        service = _mca_intents.get_service(db)
        active = await service.store.count_active(int(chat_id))
        if active >= mca_gates.intent_candidates_max():
            return None, False
        now = int(time.time())
        topic = ("q:" + _mca_intents._sha1_16(goal.strip().casefold()),)
        refs = ((f"msg:{int(tg_message_id)}",)
                if tg_message_id is not None else ())
        return await service.create_intent(
            int(chat_id), kind=kind, origin="explicit_request",
            topic_refs=topic, goal=goal, reason=None, source_refs=refs,
            not_before=now + INITIATIVE_UNANSWERED_DELAY_SECONDS,
            expires_at=now + INITIATIVE_UNANSWERED_TTL_SECONDS,
            activation_condition="time_due")
    except Exception:
        logger.warning("[f6] future_intent create failed — skipped",
                       exc_info=True)
        return None, False


# ── F6 (§18D): СВЕЖИЕ runtime-условия из реального чата ──────────────────────
# Ни одно поле RecheckContext не остаётся дефолтным: всё считается запросами
# в durable-состояние чата (окно smart_messages + ledger bot-выходов).
_F6_RECHECK_WINDOW_LIMIT = 50
_F6_RECHECK_LOOKBACK_SECONDS = 6 * 3600


def _f6_context_version(*, chat_id: int, created_at: int, new_human: int,
                        last_human_id, bot_outputs: int, last_output_id
                        ) -> str:
    """Дешёвый fingerprint свежести контекста (R17: только числа/ID)."""
    return _mca_intents._sha1_16("f6ctx", int(chat_id), int(created_at),
                                 int(new_human), str(last_human_id or ""),
                                 int(bot_outputs), str(last_output_id or ""))


async def _f6_chat_facts(db, chat_id: int, created_at: int) -> dict:
    """Свежие факты чата с момента создания намерения (bounded SQL):
    новые human-сообщения окна, адресованные боту реплаи/упоминания,
    доставленные bot-выходы после created_at. Никогда не бросает."""
    facts = {"new_human": 0, "last_human_id": None, "direct_pending": False,
             "same_branch_replies": False, "bot_outputs": 0,
             "last_output_id": None}
    if db is None:
        return facts
    since = max(0, min(int(created_at), int(time.time())
                       - _F6_RECHECK_LOOKBACK_SECONDS))
    try:
        window = await db.get_smart_window(int(chat_id), since,
                                           _F6_RECHECK_WINDOW_LIMIT)
    except Exception:
        window = []
    try:
        window = [dict(r) for r in (window or ())]
    except Exception:
        window = []
    bot_username = ""
    try:
        from handlers import direct_chat as _dc_handler
        bot_username = str(getattr(_dc_handler, "_bot_username", "") or "")
    except Exception:
        bot_username = ""
    bot_tg_ids: set[int] = set()
    try:
        outputs = await db.list_recent_bot_outputs(int(chat_id), limit=10)
    except Exception:
        outputs = []
    for out in outputs:
        tg_id = out.get("tg_message_id")
        if tg_id is not None:
            bot_tg_ids.add(int(tg_id))
    for row in window:
        ts = int(row.get("timestamp") or 0)
        if ts <= int(created_at):
            continue
        facts["new_human"] += 1
        facts["last_human_id"] = row.get("tg_message_id") or row.get("id")
        text = str(row.get("text") or "")
        reply_to = row.get("reply_to_id")
        replied_to_bot = (reply_to is not None
                          and int(reply_to) in bot_tg_ids)
        if replied_to_bot or (bot_username and
                              ("@" + bot_username) in text.lower()) or \
                _BOTWORD_RE.search(text):
            # прямое обращение к боту появилось, пока готовилась инициатива:
            # инициатива не соревнуется (defer, не close — chat-level
            # намерение не фиксирует свою reply-ветку, ΔDDL=0)
            facts["direct_pending"] = True
    facts["bot_outputs"] = len(outputs)
    fresh = [o for o in outputs
             if int(o.get("sent_at") or 0) > int(created_at)]
    facts["bot_after"] = len(fresh)
    facts["last_output_id"] = (outputs[0].get("output_id")
                               if outputs else None)
    return facts


async def build_fresh_recheck_context(db, chat_id: int, intent_row: dict, *,
                                      evaluated_context_version: str | None = None,
                                      recheck_attempts: int = 0
                                      ) -> "_mca_intents.RecheckContext":
    """F6 (§18D): СВЕЖИЙ RecheckContext из реального чата (не дефолтные
    false/unknown):
    * already_answered — бот уже доставил текст после создания намерения
      (разговор ушёл вперёд — вопрос закрыт, A15 close);
    * direct_request_pending — новое human-сообщение, адресованное боту
      (reply на bot-сообщение / @username / бот-слово) — инициатива не
      соревнуется с прямым ответом (defer);
    * context_version — fingerprint (chat, created_at, новые сообщения,
      bot-выходы); evaluated — версия на момент решения: смена между
      решением и отправкой → ровно одна переоценка, повторная смена → defer.
    same_branch_replies/left False осознанно: chat-level намерение не
    фиксирует свою reply-ветку (ΔDDL=0); смену контекста покрывает
    context_version, активность в ветке бота — direct_request_pending."""
    created_at = int((intent_row or {}).get("created_at") or 0)
    facts = await _f6_chat_facts(db, chat_id, created_at)
    context_version = _f6_context_version(
        chat_id=chat_id, created_at=created_at,
        new_human=int(facts["new_human"]),
        last_human_id=facts["last_human_id"],
        bot_outputs=int(facts.get("bot_after") or 0),
        last_output_id=facts["last_output_id"])
    return _mca_intents.RecheckContext(
        enabled=True,
        addressee_ok=True,
        # parent_changed для chat-уровневых намерений не выводим: реплай-
        # ветка намерения не фиксируется (без ΔDDL); смену ветки покрывают
        # already_answered/direct_request_pending/context_version.
        parent_changed=False,
        intent_row=intent_row,
        already_answered=bool(facts.get("bot_after")),
        same_branch_replies=bool(facts["same_branch_replies"]),
        tool_permission_denied=False,
        context_version=context_version,
        evaluated_context_version=evaluated_context_version,
        recheck_attempts=int(recheck_attempts or 0),
        direct_request_pending=bool(facts["direct_pending"]))


async def build_initiative_situation(db, chat_id: int, intent_row: dict
                                     ) -> "_mca_intents.InitiativeSituation":
    """F6 (§18D): ситуация для решения из РЕАЛЬНОГО состояния чата — не
    дефолтные флаги: direct_pending (прямое обращение после создания
    намерения), bot_replied_recently (существующее окно bot_replies),
    topic_open (бот ещё не отвечал после намерения), открытые intent-ID."""
    row = intent_row or {}
    created_at = int(row.get("created_at") or 0)
    facts = await _f6_chat_facts(db, chat_id, created_at)
    open_ids = None
    bot_recent = False
    if db is not None:
        try:
            rows = await _mca_intents.get_service(db).store.list_active(
                int(chat_id), limit=50)
            open_ids = [str(r.get("intent_id") or "") for r in rows
                        if r.get("intent_id")]
        except Exception:
            open_ids = None
        try:
            cursor = await db.db.execute(
                "SELECT 1 FROM bot_replies WHERE chat_id = ? "
                "AND last_used_at > ? LIMIT 1",
                (int(chat_id), time.time() - 600))
            bot_recent = await cursor.fetchone() is not None
        except Exception:
            bot_recent = False
    return _mca_intents.InitiativeSituation(
        trigger_kind="intent_due",
        chat_id=int(chat_id),
        direct_pending=bool(facts["direct_pending"]),
        same_event_pending=False,
        sensitive_moment=False,
        relations_ok=True,
        bot_replied_recently=bot_recent,
        reply_needed=False,
        # повод открыт, пока бот ничего не отправлял после создания
        topic_open=not bool(facts.get("bot_after")),
        open_intent_ids=open_ids,
        requested_source="intent",
        intent_id=str(row.get("intent_id") or "") or None)


async def _style_initiative_text(text: str, chat_id: int, l1_plan=None
                                 ) -> tuple[str, object]:
    """Единый проход формы для инициативных текстов (SOUL-AMD.3.5).

    Инициатива — авторский текст того же Core, поэтому правила формы
    применяются тем же единственным проходом, что и в Direct: контекст
    ``initiative`` (пакет инициативы + обычной речи), ``plan`` — из L1-решения
    (когда оно есть). Возвращает ``(текст, StyleOutcome|None)``; ошибка прохода
    не роняет отправку (fail-open, текст как есть)."""
    source = str(text or "")
    if not source.strip():
        return source, None
    response_plan = None
    if l1_plan is not None:
        try:
            response_plan = (l1_plan.to_response_plan()
                             if hasattr(l1_plan, "to_response_plan") else None)
        except Exception:
            response_plan = None
    try:
        outcome = await _style_policy.apply_style_policy(
            source, chat_id=chat_id, plan=response_plan,
            context="initiative", emit_events=True,
            stage="initiative_pre_send")
    except Exception:      # pragma: no cover - проход не роняет отправку
        logger.warning("[mca09] initiative style pass failed | chat=%s",
                       chat_id, exc_info=True)
        return source, None
    if outcome.applied and str(outcome.text or ""):
        return outcome.text, outcome
    return source, outcome


def _ephemeral_intent_row(opportunity_row: dict | None, chat_id: int
                          ) -> dict | None:
    """Строка-контекст для ЭФЕМЕРНОГО повода (без durable intent).

    P0-хотфикс (18.10.2026): observer-возможность («уместно сказать сейчас»,
    B01.2) не создаёт намерение, но Writer/L1 обязаны видеть САМ повод —
    иначе `plan_initiative_decision`/`generate_initiative_reply` получали
    пустую строку («цель не указана») и отказывались. Ничего нового не
    изобретаем: это тот же формы dict, что и durable-строка mca_intents."""
    row = dict(opportunity_row or {})
    if not row:
        return None
    row.setdefault("chat_id", int(chat_id))
    row.setdefault("origin", "ephemeral_opportunity")
    row.setdefault("status", "ephemeral")
    row.setdefault("created_at", int(time.time()))
    return row


# ── L1D (owner-corrective-initreply 22.10.2026 §2/§4/§6): транспорт НЕ
# выбирает цель. Детерминированный резолвер 2.58.109 (_initiative_reply_target:
# source_refs → первое сообщение → reply, фолбэк «последнее сообщение
# адресата») УДАЛЁН — он подменял решение LLM эвристикой. Форму участия
# выбирает L1 в плане (delivery/target_message_id/target_user_id); транспорт
# только ИСПОЛНЯЕТ решение и проверяет выбранную цель технически (§6):
# принадлежность чату, существование, соответствие адресату, свежесть.
# R17: в логах только id/коды, содержимое не логируется.


def _initiative_context_window_seconds() -> int:
    """§6 «не устарело относительно текущего контекста»: граница свежести
    цели = то же окно, из которого L1 выбирала (limits.summary_window_hours,
    тот же источник, что у get_window_messages). Хардкод 24ч из 2.58.109
    снят по §6 («без обоснования»): граница следует за реальным окном
    контекста, а не за фиксированным числом. Флор 1ч защищает от вырожденной
    конфигурации (0ч не должен отключать reply целиком). Никогда не бросает."""
    try:
        from services import hot_config as hot
        hours = float(hot.get(
            "limits.summary_window_hours",
            settings.SUMMARY_WINDOW_HOURS) or 0)
    except Exception:      # pragma: no cover - защитная ветка
        hours = float(getattr(settings, "SUMMARY_WINDOW_HOURS", 6.0) or 6.0)
    return max(3600, int(hours * 3600))


def _plan_target_message_id(plan) -> int | None:
    """id цели из плана L1 (мусор/bool/≤0 → None). Не бросает."""
    value = getattr(plan, "target_message_id", None)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _plan_semantic_addressee(plan) -> int | None:
    """Смысловой адресат из плана L1 (target_user_id; мусор → None).

    Семантика (§6 директивы): заполненный адресат означает «текст — прямой
    ответ этому человеку» → при недоступной цели отправка без привязки
    потеряла бы смысл (SendRecheck-исход); пустой — текст осмыслен
    standalone (fail-soft обычная отправка)."""
    value = getattr(plan, "target_user_id", None)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


async def _validate_plan_target(db, chat_id: int, plan, *,
                                mode: str) -> tuple[int | None, str]:
    """Техническая проверка цели, ВЫБРАННОЙ L1 (§6 директивы 22.10).

    Никакого выбора: цель приходит ТОЛЬКО из плана. Проверки: сообщение
    существует и принадлежит этому чату, имеет Telegram-id, не устарело
    относительно окна контекста, соответствует смысловому адресату (если
    L1 его указала). При неудаче цель НЕ заменяется другой (§6: «не выбирать
    другую произвольную цель»). Возврат ``(tg_message_id | None, код)``:
    код "" — привязка не запрашивалась планом; непустой код — план просил
    цель, проверка её не прошла. Никогда не бросает."""
    try:
        if plan is None:
            return None, ""
        action = str(getattr(plan, "action", "") or "")
        if mode == "reply":
            if not _l1.reply_binding_requested(plan):
                return None, ""
        elif mode == "react":
            if action != "react":
                return None, ""
        else:      # pragma: no cover - защитная ветка контракта
            return None, ""
        target = _plan_target_message_id(plan)
        if target is None:
            return None, "target_invalid"
        cursor = await db.db.execute(
            "SELECT tg_message_id, user_id, timestamp FROM smart_messages "
            "WHERE id = ? AND chat_id = ?", (int(target), int(chat_id)))
        row = await cursor.fetchone()
        if row is None:
            return None, "target_missing"
        tg_raw = row_get(row, "tg_message_id")
        try:
            tg_id = int(tg_raw) if tg_raw not in (None, "", 0) else None
        except (TypeError, ValueError):
            tg_id = None
        if tg_id is None:
            return None, "target_no_tg_id"
        try:
            ts = int(row_get(row, "timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts > 0 and int(time.time()) - ts > \
                _initiative_context_window_seconds():
            return None, "target_stale"
        addressee = _plan_semantic_addressee(plan)
        if addressee is not None:
            row_user = row_get(row, "user_id")
            try:
                row_user = int(row_user) if row_user is not None else None
            except (TypeError, ValueError):
                row_user = None
            if row_user != addressee:
                return None, "target_addressee_mismatch"
        return tg_id, ""
    except Exception:
        logger.warning("[mca09] initiative plan target validate failed | "
                       "chat=%s", chat_id, exc_info=True)
        return None, "target_unavailable"


async def _execute_initiative_react(bot, db, chat_id: int, decision,
                                    l1_plan, delivery_kind: str, *,
                                    writer_service=None) -> dict:
    """L1D (директива 22.10 §5-D/§7): исполнение реакции, выбранной L1.

    Реакция — ТОЛЬКО существующий механизм ``react_moai``; цель — только
    ``target_message_id`` из плана, прошедшая техническую проверку (§6).
    Валидной реакции/цели нет → честное молчание БЕЗ произвольной
    перепривязки цели и БЕЗ превращения реакции в текст. Никогда не
    бросает (возвращает R17-safe статус)."""
    reaction = getattr(l1_plan, "reaction", None)
    if reaction not in _llm_react.ALLOWED_LLM_REACTIONS:
        reaction = None
    target_tg, code = await _validate_plan_target(
        db, chat_id, l1_plan, mode="react")
    if reaction is not None and target_tg is not None:
        mech = reaction_mechanics_enabled()
        outcome_code = await react_moai(
            bot, chat_id, target_tg,
            reaction=reaction if mech else None,
            reason_code="l1_react")
        if writer_service is not None:
            await _f6_plan_next_check(db, decision)
        _mca_intents.note_decision(decision, chat_id=chat_id,
                                   outcome="ok", reason_code="l1_react")
        if decision.intent_id and db is not None:
            try:
                await _mca_intents.get_service(db).mark_attempt(
                    decision.intent_id)
            except Exception:
                logger.warning("[mca09] initiative attempt mark failed",
                               exc_info=True)
        return {"status": "reacted", "delivery_kind": delivery_kind,
                "reason_code": "l1_react", "reaction_outcome": outcome_code,
                "reaction_target": target_tg, "decision": decision}
    # Честный исход: реакция не состоялась (нет валидного эмодзи/цели) —
    # НИКАКОЙ автоподмены цели или превращения в сообщение (§6).
    logger.warning("[mca09] initiative react not executable | chat=%s | "
                   "reason=%s", chat_id, code or "invalid_reaction")
    if writer_service is not None:
        await _f6_plan_next_check(db, decision)
    _mca_intents.note_decision(decision, chat_id=chat_id,
                               outcome="silent", reason_code="l1_react")
    return {"status": "silent", "delivery_kind": delivery_kind,
            "reason_code": "l1_react", "decision": decision}


async def handle_initiative(*, bot, chat_id: int, situation, candidates,
                            prepared_text: str | None = None, db=None,
                            correlation_id: str | None = None,
                            writer_service=None,
                            opportunity_row: dict | None = None) -> dict:
    """Аддитивный координатор-вход для решений БЕЗ входящего сообщения
    (heartbeat / nostalgia / significant event / search completion).

    ``opportunity_row`` (P0-хотфикс, 18.10.2026): контекст ЭФЕМЕРНОГО повода
    наблюдателя (goal/kind/origin/created_at) для случая, когда durable
    намерения нет — Writer/L1 и SendRecheck получают реальный повод, а не
    пустую строку. Для путей с `decision.intent_id` аргумент игнорируется.

    Возвращает R17-safe статус (без сырого текста):
      disabled / silent / candidate_ready / cancelled / writer_failed /
      sent / error.

    F6 (§13.2/§28.15): heartbeat передаёт `writer_service` (существующий
    DirectChatService) — генерация prepared_text идёт ЕГО контуром
    (L1-решение REPLY/REACT/SILENT → существующий Direct L2 Writer),
    SendRecheck выполняется по СВЕЖИМ условиям чата (§18D) и перед
    решением, и непосредственно перед отправкой. Неспособность сгенерировать
    → терминальный bounded исход `writer_failed` (не бесконечный defer).
    Третьего Writer нет. Silent НИКОГДА не отправляет; отправка — только
    через `telegram_send.send_text` (chunks — одна логическая отправка)."""
    try:
        if not (mca_gates.intents_enabled()
                and mca_gates.intent_decision_enabled()):
            return {"status": "disabled", "delivery_kind": ""}
        decision_candidates = tuple(
            c.to_decision_candidate() for c in (candidates or ())
            if hasattr(c, "to_decision_candidate"))
        # ── mca-10b (ADR-1028-17 D3, T-5052): РОВНО ОДНА probability-
        # проверка exploration на conversation operation над ОБЩИМ пулом
        # целостных кандидатов (варианты из памяти + формы участия); пустой
        # пул → primary + `no_eligible_alternative` БЕЗ draw; LLM ради
        # альтернатив не вызывается; OFF → None, путь 2.58.60 бит-в-бит.
        # Уместность/проверка перед отправкой остаются у потребителя ниже —
        # политика их не подменяет и не отключает.
        exploration_choice = None
        exploration_result = None
        selected_candidate_ref = None
        pool_items = None
        if decision_candidates and db is not None:
            try:
                from services import mca_exploration
                primary = max(
                    decision_candidates,
                    key=lambda c: int(getattr(c, "priority", 0) or 0))
                # ── mca-10b (ADR-1028-17 D10, T-5059): формы участия —
                # обычные DecisionCandidate-семантики в ОБЩЕМ пуле §14.5;
                # строятся ТОЛЬКО при разрешённом exploration (OFF → пул форм
                # не строится, путь 2.58.60 бит-в-бит). Непригодные формы —
                # admissible=False с причиной (раскрытие решения); LLM ради
                # набора не вызывается; форма не меняет факты/адресата.
                pool_items = list(decision_candidates)
                allowed, _ = await mca_exploration.exploration_allowed(
                    db, mca_exploration.PURPOSE_CONVERSATION_VARIANT,
                    chat_id)
                if allowed:
                    forms = mca_exploration.build_conversation_form_candidates(
                        direct_request=bool(
                            getattr(situation, "direct_pending", False)),
                        has_story=any(
                            mca_exploration.episode_ids_of(c)
                            for c in decision_candidates))
                    pool_items.extend(
                        f.to_decision_candidate() for f in forms)
                exploration_choice, exploration_result = \
                    await mca_exploration.choose_conversation_alternative(
                        db, chat_id=chat_id, operation_id=correlation_id
                        or uuid.uuid4().hex[:16], primary=primary,
                        pool=pool_items,
                        requested_source="mca10b")
                chosen = getattr(exploration_choice, "selected", None) \
                    if exploration_choice is not None else None
                if getattr(exploration_choice, "explored", False) and \
                        chosen is not None:
                    selected_candidate_ref = chosen
            except Exception:
                logger.warning("[mca10b] conversation exploration failed — "
                               "primary path", exc_info=True)
        decision = _mca_intents.decide_initiative(
            situation=situation,
            candidates=(pool_items if exploration_choice is not None
                        else decision_candidates),
            random_choice=exploration_choice)
        kind = _mca_intents.initiative_delivery_kind(decision)
        if kind == _mca_intents.DELIVERY_SILENT:
            # F6: silent по решению — серверное планирование (не re-decide
            # каждые 300 с; bounded backoff, expiry/hygiene ограничивают).
            if writer_service is not None:
                await _f6_plan_next_check(db, decision)
            _mca_intents.note_decision(decision, chat_id=chat_id,
                                       outcome="silent")
            return {"status": "silent", "delivery_kind": kind,
                    "decision": decision}
        if kind != _mca_intents.DELIVERY_TEXT:
            # react/tool в инициативном контексте без цели: честное молчание
            # + планирование (не candidate_ready — генерации для них нет).
            if writer_service is not None:
                await _f6_plan_next_check(db, decision)
            _mca_intents.note_decision(decision, chat_id=chat_id,
                                       outcome="silent",
                                       reason_code="delivery_not_text")
            return {"status": "silent", "delivery_kind": kind,
                    "reason_code": "delivery_not_text", "decision": decision}
        if not prepared_text and writer_service is None:
            # Кандидат отдан координатору; генерации в этом срезе нет —
            # честный статус, отправки НЕ происходит (не выдаём за отправку).
            # Reviewer F-2: серверное планирование обязательно — иначе intent
            # с прошедшим next_check_at переизбирается каждые 300 с вечно.
            # Bounded defer с backoff (spec D2/D3/D10); фактических попыток
            # нет (attempts НЕ растут — это не отправка), MAX_ATTEMPTS и
            # гигиена (expire/archive) уважаются жизненным циклом.
            if decision.intent_id and db is not None:
                try:
                    service = _mca_intents.get_service(db)
                    row = await service.store.get_intent(decision.intent_id)
                    if row is not None and str(row.get("status") or "") in (
                            "pending", "deferred"):
                        now_ts = _mca_intents._now()
                        backoff = max(60, int(
                            mca_gates.intent_defer_backoff_seconds()))
                        deferred = await service.defer(
                            decision.intent_id,
                            next_check_at=now_ts + backoff,
                            activation_condition=row.get(
                                "activation_condition"),
                            now=now_ts)
                        if deferred is not None:
                            decision.next_check_at = now_ts + backoff
                except Exception:
                    logger.warning("[mca09] candidate planning failed",
                                   exc_info=True)
            _mca_intents.note_decision(decision, chat_id=chat_id,
                                       outcome="candidate_ready")
            return {"status": "candidate_ready", "delivery_kind": kind,
                    "next_check_at": decision.next_check_at,
                    "decision": decision}
        # ── F6 (§13.2): отправка. prepared_text передан (nostalgia) ИЛИ
        # генерируется существующим Direct-контуром (writer_service, §28.15).
        if db is not None and decision.intent_id:
            try:
                service = _mca_intents.get_service(db)
                intent_row = await service.store.get_intent(
                    decision.intent_id)
            except Exception:
                intent_row = None
            if intent_row is None or str(intent_row.get("status") or "") \
                    not in ("pending", "deferred"):
                # намерение исчезло/закрыто, пока кандидат ждал тик
                _mca_intents.note_decision(decision, chat_id=chat_id,
                                           outcome="cancelled",
                                           reason_code="intent_closed")
                return {"status": "cancelled", "reason_code": "intent_closed",
                        "delivery_kind": kind, "decision": decision}
        else:
            intent_row = _ephemeral_intent_row(opportunity_row, chat_id)
        generated = False
        evaluated_version = None
        l1_plan = None
        if prepared_text is None and writer_service is not None:
            # §18D (decision-time): свежие условия ДО решения/генерации —
            # отвечать нечему/некому: не тратим LLM-вызовы.
            if db is not None and intent_row is not None:
                pre = await build_fresh_recheck_context(
                    db, chat_id, intent_row)
                evaluated_version = pre.context_version
                if pre.already_answered:
                    await _f6_close_intent(db, decision.intent_id,
                                           status="fulfilled",
                                           reason_code="already_answered")
                    _mca_intents.note_decision(decision, chat_id=chat_id,
                                               outcome="cancelled",
                                               reason_code="already_answered")
                    return {"status": "cancelled",
                            "reason_code": "already_answered",
                            "delivery_kind": kind, "decision": decision}
                if pre.direct_request_pending:
                    await _f6_plan_next_check(db, decision)
                    _mca_intents.note_decision(decision, chat_id=chat_id,
                                               outcome="cancelled",
                                               reason_code="direct_pending")
                    return {"status": "cancelled",
                            "reason_code": "direct_pending",
                            "delivery_kind": kind, "decision": decision}
            # инициативное решение СУЩЕСТВУЮЩЕЙ L1-моделью (§13.2 + L1D
            # 22.10.2026: L1 выбирает и ФОРМУ участия — reply/react/silent
            # и доставку; транспорт не подменяет).
            l1_plan = await writer_service.plan_initiative_decision(
                chat_id, intent_row or {}, correlation_id=correlation_id)
            if l1_plan is None:
                await _f6_plan_next_check(db, decision)
                _mca_intents.note_decision(decision, chat_id=chat_id,
                                           outcome="silent",
                                           reason_code="l1_unavailable")
                return {"status": "silent", "delivery_kind": kind,
                        "reason_code": "l1_unavailable",
                        "decision": decision}
            if getattr(l1_plan, "action", "") == "react":
                # L1D §5-D: поддерживаемая реакция исполняется без текста.
                return await _execute_initiative_react(
                    bot, db, chat_id, decision, l1_plan, kind,
                    writer_service=writer_service)
            if getattr(l1_plan, "action", "") != "reply":
                await _f6_plan_next_check(db, decision)
                _mca_intents.note_decision(decision, chat_id=chat_id,
                                           outcome="silent",
                                           reason_code="l1_silent")
                return {"status": "silent", "delivery_kind": kind,
                        "reason_code": "l1_silent", "decision": decision}
            prepared_text = await writer_service.generate_initiative_reply(
                chat_id, intent_row or {}, l1_plan=l1_plan,
                correlation_id=correlation_id)
            generated = True
            if not str(prepared_text or "").strip():
                # §28.15: генерация не удалась — НЕ бесконечный defer:
                # bounded attempts → терминальное закрытие writer_failed.
                outcome = "skipped"
                if db is not None and decision.intent_id:
                    try:
                        failure = await _mca_intents.get_service(db) \
                            .note_writer_failure(decision.intent_id)
                        outcome = str(failure.get("outcome") or "skipped")
                    except Exception:
                        logger.warning(
                            "[f6] writer failure bookkeeping failed",
                            exc_info=True)
                _mca_intents.note_decision(decision, chat_id=chat_id,
                                           outcome="writer_failed")
                return {"status": "writer_failed", "outcome": outcome,
                        "delivery_kind": kind, "decision": decision}
            # F6 (§13.3): событие генерации (trigger=initiative) для funnel.
            _mca_intents.note_writer_generated(chat_id=chat_id,
                                               intent_id=decision.intent_id,
                                               chars=len(prepared_text))
        # Проверка перед отправкой (D4/T-5035) — F6 §18D: по СВЕЖИМ
        # условиям реального чата непосредственно перед send; ровно одна
        # переоценка при смене контекста во время подготовки (bounded).
        recheck_attempts = 0
        styled_text = None
        style_outcome = None
        while True:
            if db is not None and intent_row is not None:
                context = await build_fresh_recheck_context(
                    db, chat_id, intent_row,
                    evaluated_context_version=evaluated_version,
                    recheck_attempts=recheck_attempts)
            else:
                context = _mca_intents.RecheckContext(intent_row=intent_row)
            # ── SOUL-1 (W3, SOUL-16.4.1 + SOUL-AMD.3.5, fix F4 review-w3):
            # ЕДИНСТВЕННАЯ точка применения прохода формы для инициативных
            # текстов — перед чанкованием и отправкой, поэтому проходят его И
            # writer-текст, И `prepared_text` (nostalgia): проверяется и
            # правится ровно то, что уйдёт. На один текст — один проход
            # (переоценка §18D может перегенерировать текст → проход заново).
            if str(prepared_text or "") != styled_text:
                prepared_text, style_outcome = await _style_initiative_text(
                    str(prepared_text or ""), chat_id, l1_plan)
                styled_text = str(prepared_text or "")
            plan = _mca_intents.plan_logical_send(
                decision, recheck=_mca_intents.SendRecheck(),
                context=context, text=prepared_text)
            if plan.outcome.proceed or not plan.outcome.recheck_again \
                    or recheck_attempts >= 1 or writer_service is None:
                break
            # §18D-3: контекст сменился, пока готовился текст, — ровно одна
            # переоценка: повторное решение + генерация на свежем контексте.
            recheck_attempts += 1
            evaluated_version = context.context_version
            if decision.intent_id and db is not None:
                try:
                    await _mca_intents.get_service(db).store.update_fields(
                        decision.intent_id,
                        {"last_evaluated_context_version":
                         str(context.context_version or "")[:120]})
                except Exception:
                    pass
            l1_plan = await writer_service.plan_initiative_decision(
                chat_id, intent_row or {}, correlation_id=correlation_id)
            if l1_plan is not None and \
                    getattr(l1_plan, "action", "") == "react":
                # L1D: переоценка на свежем контексте выбрала реакцию —
                # исполняется, а не демотируется молча.
                return await _execute_initiative_react(
                    bot, db, chat_id, decision, l1_plan, kind,
                    writer_service=writer_service)
            if l1_plan is None or getattr(l1_plan, "action", "") != "reply":
                await _f6_plan_next_check(db, decision)
                _mca_intents.note_decision(decision, chat_id=chat_id,
                                           outcome="silent",
                                           reason_code="recheck_demoted")
                return {"status": "silent", "delivery_kind": kind,
                        "reason_code": "recheck_demoted",
                        "decision": decision}
            prepared_text = await writer_service.generate_initiative_reply(
                chat_id, intent_row or {}, l1_plan=l1_plan,
                correlation_id=correlation_id)
            if not str(prepared_text or "").strip():
                outcome = "skipped"
                if db is not None and decision.intent_id:
                    try:
                        failure = await _mca_intents.get_service(db) \
                            .note_writer_failure(decision.intent_id)
                        outcome = str(failure.get("outcome") or "skipped")
                    except Exception:
                        logger.warning(
                            "[f6] writer failure bookkeeping failed",
                            exc_info=True)
                _mca_intents.note_decision(decision, chat_id=chat_id,
                                           outcome="writer_failed")
                return {"status": "writer_failed", "outcome": outcome,
                        "delivery_kind": kind, "decision": decision}
            _mca_intents.note_writer_generated(chat_id=chat_id,
                                               intent_id=decision.intent_id,
                                               chars=len(prepared_text))
        if not plan.outcome.proceed:
            # Устаревшее/закрытое: A15-закрытие либо серверное планирование
            # (re-evaluate позже, bounded expiry); попыткой НЕ считается.
            if db is not None and decision.intent_id:
                await _f6_apply_suppressed(
                    db, decision.intent_id, plan.outcome,
                    context_version=getattr(context, "context_version",
                                            None))
            _mca_intents.note_decision(decision, chat_id=chat_id,
                                       outcome="cancelled",
                                       reason_code=(plan.outcome.reason_code
                                                    or None))
            logger.info("[mca09] initiative cancelled | chat=%s | reason=%s",
                        chat_id, plan.outcome.reason_code or "-")
            return {"status": "cancelled",
                    "reason_code": plan.outcome.reason_code,
                    "delivery_kind": kind, "decision": decision}
        if decision.intent_id:
            _mca_intents.note_recheck_passed(chat_id=chat_id,
                                             intent_id=decision.intent_id)
        sent_id = None
        sent = 0
        # ── L1D (директива 22.10 §2/§4/§6): привязка reply — ТОЛЬКО из
        # решения L1 (delivery=reply + target_message_id). Никакого
        # детерминированного выбора по source_refs/адресату (резолвер
        # 2.58.109 удалён). Техническая проверка цели; при неудаче:
        #  - текст осмыслен standalone (нет смыслового адресата в плане)
        #    → fail-soft обычная отправка;
        #  - текст — прямой ответ человеку (адресат указан) → отправка без
        #    привязки потеряла бы смысл → SendRecheck-семантика: отмена без
        #    отправки, переоценка позже (bounded defer).
        reply_target_id = None
        binding_code = ""
        semantic_addressee = None
        if l1_plan is not None:
            semantic_addressee = _plan_semantic_addressee(l1_plan)
            if _l1.reply_binding_requested(l1_plan):
                reply_target_id, binding_code = await _validate_plan_target(
                    db, chat_id, l1_plan, mode="reply")
                if reply_target_id is None:
                    logger.info("[mca09] initiative reply binding "
                                "unavailable | chat=%s code=%s addr=%s",
                                chat_id, binding_code,
                                bool(semantic_addressee))
                    if semantic_addressee is not None:
                        # §6: нельзя снять привязку прямого ответа человеку
                        # и отправить «тот же текст в общий чат».
                        if writer_service is not None:
                            await _f6_plan_next_check(db, decision)
                        _mca_intents.note_decision(
                            decision, chat_id=chat_id, outcome="cancelled",
                            reason_code=binding_code)
                        return {"status": "cancelled",
                                "reason_code": binding_code,
                                "delivery_kind": kind,
                                "decision": decision}
                    # fail-soft: текст самостоятелен → отправка без reply.
                    reply_target_id = None
        for index, chunk in enumerate(plan.chunks):
            reply_id = reply_target_id if index == 0 else None
            try:
                message = await _tg_send.send_text(
                    bot, chat_id, chunk,
                    **({"reply_to_message_id": reply_id} if reply_id else {}))
            except TelegramBadRequest as exc:
                # Цель исчезла к моменту отправки: та же семантика решения —
                # fail-soft (один повтор без reply) для самостоятельного
                # текста; отмена БЕЗ отправки для прямого ответа человеку.
                if reply_id is None or not _is_reply_target_gone(exc):
                    raise
                if semantic_addressee is not None:
                    logger.warning("[mca09] initiative reply target gone — "
                                   "cancel (semantic addressee) | chat=%s "
                                   "msg=%s", chat_id, reply_id)
                    if writer_service is not None:
                        await _f6_plan_next_check(db, decision)
                    _mca_intents.note_decision(
                        decision, chat_id=chat_id, outcome="cancelled",
                        reason_code="target_gone")
                    return {"status": "cancelled",
                            "reason_code": "target_gone",
                            "delivery_kind": kind, "decision": decision}
                logger.warning("[mca09] initiative reply target gone — "
                               "retry without reply | chat=%s msg=%s",
                               chat_id, reply_id, exc_info=True)
                message = await _tg_send.send_text(bot, chat_id, chunk)
            sent += 1
            if sent_id is None:
                sent_id = getattr(message, "message_id", None)
        # ── mca-10b (ADR-1028-17 D6, T-5055): `last_used_in_chat_at` —
        # ТОЛЬКО после подтверждённой доставки (сон/поиск ≠ рассказ, R6d).
        if selected_candidate_ref is not None and db is not None:
            try:
                from services import mca_exploration
                await mca_exploration.mark_episodes_used_in_chat(
                    db, mca_exploration.episode_ids_of(selected_candidate_ref),
                    chat_id=chat_id)
            except Exception:
                logger.warning("[mca10b] used_in_chat stamp failed",
                               exc_info=True)
        if decision.intent_id and db is not None:
            try:
                await _mca_intents.get_service(db).mark_attempt(
                    decision.intent_id)
            except Exception:
                logger.warning("[mca09] initiative attempt mark failed",
                               exc_info=True)
        if db is not None and sent_id is not None:
            try:
                await _ledger.record_delivered_output(
                    db, chat_id=chat_id, tg_message_id=sent_id,
                    text=str(prepared_text),
                    bot_user_id=getattr(bot, "id", None),
                    output_kind=direct_output_kind(TRIGGER_INITIATIVE),
                    sent_at=int(time.time()), correlation_id=correlation_id,
                    source_feature="mca09_intents")
            except Exception:
                logger.warning("[mca09] initiative ledger failed",
                               exc_info=True)
        if decision.intent_id:
            # F6 (§13.3): доставка состоялась — событие для funnel `sent`.
            _mca_intents.note_initiative_sent(chat_id=chat_id,
                                              intent_id=decision.intent_id,
                                              chunks=sent)
        # ── SOUL-1 (W5, SOUL-18.6): под каким Core/Style ушло сообщение.
        # Пишется по факту доставки, только ID/ревизии; ошибка не рвёт отправку.
        try:
            _refs = None
            try:
                _refs = _pcomp.recall_turn_refs(chat_id, correlation_id)
            except Exception:
                _refs = None
            _core_rev = ""
            _policy_rev = ""
            _identity_rev = ""
            _manifest_id = ""
            _composer_state = "on" if _pcomp.composer_enabled_now(
                await _composer_resolve_gates(chat_id)) else "off"
            try:
                _manifest = _pcomp.get_manifest(chat_id, run_id=correlation_id,
                                                writer="initiative_writer")
                if _manifest is not None:
                    _versions = dict(getattr(_manifest, "versions", {}) or {})
                    _core_rev = str(_versions.get("core") or "")
                    _policy_rev = str(_versions.get("style_policy") or "")
                    _manifest_id = str(getattr(_manifest, "manifest_id", "")
                                       or "")
            except Exception:
                _manifest = None
            if _refs is not None:
                _core_ref = getattr(_refs, "core", None)
                _policy_ref = getattr(_refs, "style_policy", None)
                _identity_ref = getattr(_refs, "identity", None)
                _core_rev = _core_rev or str(getattr(_core_ref, "revision", "")
                                             or "")
                _policy_rev = _policy_rev or str(
                    getattr(_policy_ref, "revision", "") or "")
                _identity_rev = str(getattr(_identity_ref, "revision", "") or "")
            _mca_intents.note_delivery_manifest(
                chat_id=chat_id, correlation_id=str(correlation_id or ""),
                message_id=sent_id, core_revision=_core_rev,
                style_policy_revision=_policy_rev,
                identity_revision=_identity_rev, manifest_id=_manifest_id,
                composer_state=_composer_state)
        except Exception:
            logger.warning("[soul1] initiative manifest event failed",
                           exc_info=True)
        _mca_intents.note_decision(decision, chat_id=chat_id, outcome="ok")
        logger.info(
            "[mca09] initiative sent | chat=%s | kind=%s | chunks=%d | "
            "trigger=%s | generated=%s", chat_id, kind, sent,
            getattr(decision, "trigger_kind", "") or "-", generated)
        return {"status": "sent", "chunks": sent, "delivery_kind": kind,
                "generated": generated, "decision": decision}
    except Exception:
        # ── mca-10b (D6): `delivery_unknown` фиксируется ОТДЕЛЬНО и
        # подавляет немедленный повторный выбор той же истории до
        # разрешения статуса (A21-семантика); чат не блокируется.
        if selected_candidate_ref is not None:
            try:
                from services import mca_exploration
                for episode_id in mca_exploration.episode_ids_of(
                        selected_candidate_ref):
                    mca_exploration.note_delivery_unknown(episode_id)
                _mca_events.emit_mca_event(
                    "random_uses", outcome=_mca_events.OUTCOME_SKIPPED,
                    component="random", reason_code="delivery_unknown",
                    stage="memory_recall",
                    entity_ids={"episode_ids": list(
                        mca_exploration.episode_ids_of(
                            selected_candidate_ref))[:16]})
            except Exception:
                pass
        logger.warning("[mca09] initiative handling failed — no send",
                       exc_info=True)
        return {"status": "error", "delivery_kind": ""}


async def _f6_plan_next_check(db, decision) -> None:
    """Серверное планирование после немой инициативы (bounded backoff):
    intent не переизбирается каждые 300 с; expiry/hygiene ограничивают.
    Никогда не бросает."""
    if db is None or not getattr(decision, "intent_id", None):
        return
    try:
        service = _mca_intents.get_service(db)
        row = await service.store.get_intent(decision.intent_id)
        if row is None or row.get("status") not in ("pending", "deferred"):
            return
        now_ts = _mca_intents._now()
        backoff = max(60, int(mca_gates.intent_defer_backoff_seconds()))
        await service.defer(decision.intent_id,
                            next_check_at=now_ts + backoff,
                            activation_condition=row.get(
                                "activation_condition"),
                            now=now_ts)
    except Exception:
        logger.warning("[f6] intent planning failed", exc_info=True)


async def _f6_close_intent(db, intent_id: str, *, status: str,
                           reason_code: str) -> None:
    """Терминальное закрытие намерения (A15). Никогда не бросает."""
    if db is None or not intent_id:
        return
    try:
        await _mca_intents.get_service(db).close(
            intent_id, status=status, reason_code=reason_code)
    except Exception:
        logger.warning("[f6] intent close failed | id=%s", intent_id,
                       exc_info=True)


async def _f6_apply_suppressed(db, intent_id: str, outcome,
                               context_version: str | None) -> None:
    """Подавленная отправка: close_intent (A15) либо bounded defer с
    обновлением evaluated-версии контекста (пере-оценка позже, не спам).
    Никогда не бросает."""
    if db is None or not intent_id:
        return
    try:
        service = _mca_intents.get_service(db)
        if getattr(outcome, "close_intent", None):
            await service.close(intent_id,
                                status=str(outcome.close_intent),
                                reason_code=str(outcome.reason_code or ""))
            return
        row = await service.store.get_intent(intent_id)
        if row is None or row.get("status") not in ("pending", "deferred"):
            return
        now_ts = _mca_intents._now()
        backoff = max(60, int(mca_gates.intent_defer_backoff_seconds()))
        await service.defer(intent_id, next_check_at=now_ts + backoff,
                            activation_condition=row.get(
                                "activation_condition"),
                            reason_code=str(outcome.reason_code or
                                            "recheck_deferred"),
                            now=now_ts)
        fields = {"last_evaluated_context_version":
                  str(context_version or "")[:120] or None}
        await service.store.update_fields(intent_id, fields)
    except Exception:
        logger.warning("[f6] suppress bookkeeping failed | id=%s", intent_id,
                       exc_info=True)