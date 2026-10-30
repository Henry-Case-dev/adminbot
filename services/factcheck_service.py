"""Epic 33/46 — FactCheckService: пайплайн фактчека (R33-3, Sections 42.6/55.5).

check_claim: SearchAggregator.search → FACTCHECK_SYSTEM_PROMPT (подстановка
{max_symbols} через .replace) → build_user_content → LLMClient.generate →
cleanup_llm_text (R33-7, ВСЕГДА). Ошибки поиска/LLM пробрасываются в хендлер
(AllSearchEnginesFailedException / LLMError) — фразы выбирает хендлер.

Epic 46 (55.5): после aggregator.search() — fire_and_forget-хук
memorize_facts(chat_id, results, "search_fact") + гибридный RAG префиксом
user-контента. memory=None / chat_id=None → ровно старое поведение.

Раунд 10.20 (БЛОК 6.2, ADR-1020-5 п.1, T-1907): Full Tool Access — аддитивный
kwarg `tool_router` (DI из bot.py, только kwargs). Если роутер задан и есть
`chat_id`, вердикт считается существующим циклом `tool_loop.chat_with_tools`
(tool-сет `dig_into_lore` + `compile_lore_story` + `execute_web_search`), а не
одиночным `llm.generate`. Пайплайн «claim → вердикт» сохраняется: tool-loop —
обёртка ВОКРУГ `llm.generate`, второго синтеза нет. Роутер не задан
(старые вызовы/тесты) → ровно прежний одиночный вызов (R16-аддитивность).
"""
import dataclasses
import datetime
import json
import logging
import time

from config.settings import settings
from services import hot_config as hot
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    FACTCHECK_SYSTEM_PROMPT,
    FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
    PREV_FACTCHECK_VERBALIZER_R1023,
    CRITIQUE_POLICY_FORBIDDEN,
    build_critique_section_block,
    critique_policy_for_findings,
    critique_policy_for_verdict,
    resolve_critique_directive,
)
from services.grounding_validator import (
    collect_allowed_anchors,
    strip_phantom_tags,
)
from services.llm_client import LLMBadResponseError, LLMClient, LLMError
from services.media_group_buffer import (
    get_media_group_caption,
    get_media_group_ids,
)
from services import anticliche_cache
from services import mca_gates
from services import usage_events
from services.prompt_composer import speech_owner_block
from services.negative_constraints import (
    NumericContract,
    channel_enabled_rules,
    verbalize_validated,
)
from services.prompt_style_blocks import (
    compose_verbalizer_system,
    resolve_prompt,
)
from services.reply_postprocess import strip_reasoning_tags
from services.search_aggregator import SearchAggregator, AllSearchEnginesFailedException
from services import temporal_factcheck as tf
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, fire_and_forget
from services.summary_xml import escape_xml_text
from services.smartmodule_utils import strip_lore_html
from services.system2_handoff import (
    normalize_response_mode,
    parse_factcheck_analysis,
    stage2_payload,
)
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, resolve_lore_compiler_flag
from services.tool_schemas import factcheck_tools

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# EVOL §5 (W5) — настройка «Критический разнос» (service-level)
# ═══════════════════════════════════════════════════════════════════════════

#: Горячий ключ настройки раздела «Критический разнос» публичного фактчека.
#: Это НЕ дубль мастер-тумблера модуля (``flags.factcheck_enabled``):
#: раздел живёт только внутри уже включённого фактчека и по умолчанию ON.
#: Наследование — существующий механизм настроек: chat-override → global
#: (hot/PG) → заводской дефолт. Ключ каталога/UI заводит отдельный лейн
#: настроек; рантайм читает его уже сейчас (без UI-зависимости).
CRITIQUE_SECTION_KEY = "flags.factcheck_critique_section_enabled"


def critique_section_default() -> bool:
    """Заводской дефолт настройки (ON; §5.2 «default ON внутри фактчека»)."""
    return bool(getattr(settings, "FACTCHECK_CRITIQUE_SECTION_ENABLED", True))


async def resolve_critique_section(chat_id: int | None) -> tuple[bool, str]:
    """``(включён, источник)`` настройки раздела «Критический разнос».

    ``source`` — ``chat`` (override этого чата) | ``global`` (общий слой) |
    ``factory`` (заводской дефолт): тот же словарь, что у остальных
    per-chat параметров (CFG-01 §01.1). ``chat_id=None`` → глобальный слой.
    Никогда не бросает: сбой резолва → заводской дефолт (fail-open).
    """
    default = critique_section_default()
    if chat_id is None:
        try:
            return bool(hot.get(CRITIQUE_SECTION_KEY, default)), "global"
        except Exception:      # pragma: no cover — hot-слой не роняет ответ
            return default, "factory"
    try:
        from services.chat_params import get_chat_param_sourced
        value, source = await get_chat_param_sourced(
            int(chat_id), CRITIQUE_SECTION_KEY, default)
        return bool(value), str(source or "factory")
    except Exception:          # pragma: no cover — PG down → глобальный слой
        try:
            return bool(hot.get(CRITIQUE_SECTION_KEY, default)), "global"
        except Exception:
            return default, "factory"


async def _critique_section_block(chat_id: int | None, policy: str) -> str:
    """Блок инструкции раздела для публичной Writer-фазы.

    Настройка OFF или политика ``forbidden`` → ``""`` (раздела нет; факты,
    источники и оговорки остаются). Директива — активная редакция из единого
    EVOL-реестра (``resolve_critique_directive``), не вторая копия текста.
    """
    if str(policy or "") == CRITIQUE_POLICY_FORBIDDEN:
        return ""
    enabled, _source = await resolve_critique_section(chat_id)
    if not enabled:
        return ""
    return build_critique_section_block(policy,
                                        directive=resolve_critique_directive())


async def _speech_style_hint(chat_id: int | None) -> str:
    """Активный Style Policy hint для публичной Writer-фазы фактчека.

    SOUL-16: hint — слой стиля владельца (W3-владелец ``style_policy``).
    Пустое значение (ось выключена/нет правил) → ``""``: сборка прежняя
    байт-в-байт. Никогда не бросает.
    """
    if not chat_id:
        return ""
    try:
        from services.prompt_composer import speech_style_hint
        return str(await speech_style_hint(chat_id) or "").strip()
    except Exception:          # pragma: no cover — слой стиля не роняет Writer
        return ""


def _with_critique_block(base: str, block: str) -> str:
    """Дописать блок раздела к жанровому канону (пустой блок → байт-паритет)."""
    if not block:
        return base
    return f"{base}\n\n{block}"


def _metatext_retry_reason():
    """CFG-07D.5: callable причины смысловой метаречи для bounded retry
    Вербализатора — ТОЛЬКО в контуре pipeline v2 (тот же рубильник, что
    диспетчеризует handler/оркестратор: hot ``flags.factcheck_pipeline_v2``
    → env). OFF (default) → ``None``: контракт не активен, поведение
    байт-в-байт прежнее (OFF-паритет). Никогда не бросает."""
    try:
        from services.factcheck_orchestrator import pipeline_v2_enabled
        if not pipeline_v2_enabled():
            return None
    except Exception:      # pragma: no cover — fail-soft OFF
        return None
    try:
        from services.public_speech_guard import metatext_retry_reason
        return metatext_retry_reason
    except Exception:      # pragma: no cover — guard не роняет Writer
        return None


def _emit_factcheck(outcome: str, *, level: str = "INFO", **fields):
    """MCA-17 (`factcheck.run`): fail-open эмиссия (REUSE mca-13).

    Это событие ВЕРДИКТ-пайплайна (`check_claim`, process `factcheck.run`);
    события mca-20 temporal-пайплайна (`factcheck_temporal`,
    `check_claim_envelope`) — отдельный контур и здесь НЕ дублируются.
    R17: только chat_id/коды/длительность — claim-текст не переносится."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event("factcheck_run", outcome=outcome, level=level,
                       component="factcheck", **fields)
    except Exception:      # контракт не рвёт вердикт
        pass


def _temporal_max_evidence() -> int:
    """mca-20: потолок evidence-строк прогона (env-лимит gates, D16)."""
    try:
        from services import mca_gates
        return mca_gates.temporal_max_evidence_per_run()
    except Exception:      # pragma: no cover
        return 20


def _fmt_evidence_date(published_at) -> str:
    """D10/§18G.5: unix ts → ISO-дата для evidence-секции; None →
    'unknown' (честно; never now())."""
    if not published_at:
        return "unknown"
    try:
        return datetime.datetime.fromtimestamp(
            int(published_at), datetime.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown"


# ── CFG-06 W5: человекочитаемый дайджест вердикта для вербализатора ─────────
# (06A.5: enum-статусы/precision/as_of больше не попадают в payload
# вербализатора — только человеческие формулировки; «unknown» → слова).

_HUMAN_FACTUAL_VERDICT = {
    "supported": "утверждение подтверждается доступными данными",
    "refuted": "доступные данные утверждение не подтверждают",
    "mixed": "данные противоречивы — утверждение верно лишь частично",
}


def _human_factual_verdict(factual: str | None) -> str:
    return _HUMAN_FACTUAL_VERDICT.get(
        str(factual or ""), "данных недостаточно для уверенного вывода")


_HUMAN_TEMPORAL_STATUS = {
    "current": "данные актуальны",
    "outdated": "данные устарели",
    "old_but_valid": "данные старые, но к утверждению остаются применимы",
    "misleading_reuse": "старые данные поданы как свежие",
}


def _human_temporal_status(status: str | None) -> str:
    return _HUMAN_TEMPORAL_STATUS.get(
        str(status or ""), "свежесть данных определить не удалось")


def _human_evaluated_period(period: dict | None) -> str:
    """Даты периода проверки по-человечески; дат нет → '' (ключ в payload
    не попадает, никакого «unknown»/precision в тексте)."""
    def _fmt(ts):
        if not ts:
            return None
        try:
            return datetime.datetime.fromtimestamp(
                int(ts), datetime.timezone.utc).strftime("%d.%m.%Y")
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    p = period or {}
    p_from, p_to = _fmt(p.get("from")), _fmt(p.get("to"))
    if p_from and p_to and p_from != p_to:
        return f"с {p_from} по {p_to}"
    if p_from:
        return f"на {p_from}"
    return ""


# ── P0-FACTCHECK (owner 24.10.2026 §3.3/§3.5/§3.6): материал изображения ──────
# Текст с картинки приходит в анализ ЧЕРЕЗ СУЩЕСТВУЮЩИЙ Vision-контур
# (`mca_vision.render_media_context_async`: OCR + визуальное описание уже
# сохранённого анализа). Новый OCR/vision-пайплайн не создаётся; если анализ
# ещё не готов — честная пометка `image_not_analyzed`, подпись сохраняется.

@dataclasses.dataclass(frozen=True)
class ClaimMediaMaterial:
    """Что дали изображения публикации (для анализа и честности)."""
    text_suffix: str = ""             # блок для claim/envelope (пусто — нет)
    image_present: bool = False
    image_analyzed: bool = False
    image_not_analyzed: bool = False
    ocr_chars: int = 0
    caption: str = ""
    # P0-FACTCHECK media (owner 25.10.2026 §3/§4/§5/§7): альбом — несколько
    # изображений одной публикации; недоступность — технический факт, а не
    # «нет содержимого».
    vision_failed: bool = False       # чтение Vision-контура не удалось
    image_count: int = 0              # элементов с реально найденными активами
    pending_count: int = 0            # из них распознавание ещё не готово
    visual_descriptions: tuple[str, ...] = ()
    # Review fix (25.10.2026): описания — контекст, не тезис. В ``text_suffix``
    # они попадают только вместе с OCR; иначе идут отдельным блоком контекста.
    description_suffix: str = ""
    truncated: bool = False           # материал изображения обрезан по лимиту
    # ASAP-VISION-SYNC-01 §4: терминальный отказ распознавания — содержимое
    # картинки НЕ проверено (отличается от «файл недоступен» и от «нет
    # текста»); причина нормализована, а не пустая.
    image_unchecked: bool = False
    unchecked_reason: str = ""

    def notice(self) -> str:
        """Человеческое ограничение (никогда не выдумывает распознавание)."""
        parts: list[str] = []
        if self.image_unchecked:
            reason = ""
            try:
                from services import media_readiness
                reason = media_readiness.reason_text(self.unchecked_reason)
            except Exception:
                reason = self.unchecked_reason or "технический сбой"
            if self.image_count:
                parts.append("Часть изображений публикации распознать не "
                             f"удалось ({reason}) — их содержимое НЕ проверено, "
                             "проверено то, что доступно.")
            else:
                parts.append("Изображение распознать не удалось "
                             f"({reason}) — содержимое картинки НЕ проверено, "
                             "проверен только текст публикации.")
        if self.vision_failed:
            if self.image_count:
                parts.append("Не все изображения публикации удалось прочитать "
                             "(технический сбой) — проверено то, что доступно.")
            else:
                parts.append("Изображение не удалось прочитать (технический "
                             "сбой) — проверен только текст публикации.")
        if self.truncated:
            parts.append("Текст части изображений обрезан по лимиту — "
                         "проверено то, что вошло в материал.")
        if self.image_not_analyzed:
            if self.pending_count and self.pending_count < self.image_count:
                parts.append("Часть изображений публикации ещё не распознана — "
                             "учтено то, что уже прочитано.")
            else:
                parts.append("На изображении мог быть текст, но распознавание "
                             "ещё не готово — проверен только текст публикации.")
        return " ".join(parts)


_IMAGE_MEDIA_TYPES = frozenset({"photo", "sticker"})
_MAX_ALBUM_ELEMENTS = 10          # Telegram: media group ≤ 10 элементов


def _row_value(row, key):
    """Значение колонки из ``aiosqlite.Row``/dict/тестового двойника."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _row_is_image(row) -> bool:
    """Строка ``smart_messages`` — изображение для существующего Vision."""
    return str(_row_value(row, "media_type") or "") in _IMAGE_MEDIA_TYPES


def _message_image_hint(message) -> bool:
    """Есть ли в TG-сообщении изображение, пригодное Vision-контуру.

    Проверяются ТОЛЬКО реальные aiogram-атрибуты (``list[PhotoSize]``,
    документ с image-mime, статический стикер): тестовые MagicMock-двойники
    не должны притворяться фотографией, а анимации/видео — вне image-контура
    (D18, mca_vision)."""
    photo = getattr(message, "photo", None)
    if isinstance(photo, (list, tuple)):
        return bool(photo)
    document = getattr(message, "document", None)
    if document is not None:
        mime = getattr(document, "mime_type", None)
        if isinstance(mime, str) and mime.startswith("image/"):
            return True
    sticker = getattr(message, "sticker", None)
    if sticker is not None:
        return not (bool(getattr(sticker, "is_animated", False))
                    or bool(getattr(sticker, "is_video", False)))
    return False


def _descriptions_from_lines(lines) -> list[str]:
    """Визуальные описания из готового рендера (совместимость со старыми
    структурами без аддитивного ключа ``visual_descriptions``)."""
    prefix = "Визуальное описание (результат модели):"
    result: list[str] = []
    for line in lines or ():
        value = str(line or "")
        if value.startswith(prefix):
            text = value[len(prefix):].strip()
            if text:
                result.append(text)
    return result


def _labelled_block(prefix: str, index: int, multi: bool, tail: str,
                    body: str) -> str:
    number = f" {index}" if multi else ""
    return f"{prefix}{number}{tail}:\n{body}"


async def load_claim_media(db, chat_id: int | None,
                           tg_message_id: int | None, *,
                           render_async=None,
                           max_chars: int = 2000,
                           message_ids=None,
                           expected_images: int = 0,
                           media_wait_seconds: float | None = None,
                           ) -> ClaimMediaMaterial:
    """OCR/визуальное описание изображений публикации (REUSE mca_vision).

    ``message_ids`` (P0-FACTCHECK media §3) — элементы альбома: читаются ВСЕ,
    поэтому тезис получает текст каждого изображения, а не только целевого.
    ``expected_images`` — сколько элементов заведомо являются изображениями
    (TG-атрибут/``media_type``): расхождение с реально найденными активами —
    честная ТЕХНИЧЕСКАЯ недоступность (``vision_failed``), а не «нет
    изображения». Возвращает контракт «что попало в анализ»: ``text_suffix``
    уходит в claim/envelope (=> в поисковые запросы и в промпт аналитика),
    ``notice()`` — честная оговорка для ответа.

    Fail-open: любая ошибка чтения → пустой материал (прежнее поведение без
    изображения), но сам факт сбоя при наличии ожидаемого изображения
    помечается ``vision_failed``."""
    if db is None or not chat_id:
        return ClaimMediaMaterial(image_present=False,
                                  vision_failed=bool(expected_images))
    if render_async is None:
        try:
            from services import mca_vision
            render_async = mca_vision.render_media_context_async
        except Exception:          # pragma: no cover — vision выключен
            return ClaimMediaMaterial(image_present=False,
                                      vision_failed=bool(expected_images))
    ids: list[int] = []
    for value in (message_ids if message_ids is not None
                  else [tg_message_id]):
        try:
            mid = int(value)
        except (TypeError, ValueError):
            continue
        if mid and mid not in ids:
            ids.append(mid)
    rendered: list[dict] = []
    # ASAP-VISION-SYNC-01 §4 («Фактчек — специальное обязательное правило»):
    # ДО извлечения тезиса и до suitability-gate связанные изображения
    # доводятся до фактического анализа (bounded; reuse durable jobs, без
    # новых LLM-вызовов). Пока анализ идёт, «нечего проверять» запрещено:
    # ниже это честно помечается как pending, а терминальный отказ даёт
    # явную оговорку «содержимое картинки не проверено».
    readiness_by_message: dict = {}
    if ids:
        try:
            from services import media_readiness
            readiness_by_message = await media_readiness.prepare_images_ready(
                db, chat_id=int(chat_id), message_ids=ids,
                consumer="factcheck",
                wait_seconds=(media_wait_seconds
                              if media_wait_seconds is not None else None))
        except Exception:
            logger.warning("[factcheck] media readiness failed — прежний "
                           "путь | chat=%s", chat_id, exc_info=True)
            readiness_by_message = {}
    failed = 0
    for mid in ids[:_MAX_ALBUM_ELEMENTS]:
        try:
            media = await render_async(db, chat_id=int(chat_id),
                                       tg_message_id=int(mid))
        except Exception:
            failed += 1
            logger.warning("[factcheck] media context read failed — caption "
                           "only | chat=%s | tg=%s", chat_id, mid,
                           exc_info=True)
            continue
        if media:
            rendered.append(media)
    expected = max(0, int(expected_images or 0))
    if not rendered:
        # Изображения ожидались, но ни одного не прочитали — техническая
        # недоступность (а не «изображения нет»). Без ожидания — материала нет.
        return ClaimMediaMaterial(image_present=False,
                                  vision_failed=expected > 0)
    captions: list[str] = []
    ocr_blocks: list[str] = []
    desc_blocks: list[str] = []
    raw_descriptions: list[str] = []
    ocr_chars = 0
    pending = False
    pending_count = 0
    truncated = False
    multi = len(rendered) > 1
    # Review fix (25.10.2026): лимит — НА ОДИН элемент (не на всю публикацию).
    # 10 фото по ~400 симв. OCR помещаются полностью; тихой обрезки всех
    # изображений одним общим бюджетом больше нет. При превышении лимита
    # элемента — честный флаг truncated (=> оговорка в ответе).
    element_budget = max(200, int(max_chars or 2000))
    unchecked = False
    unchecked_reason = ""
    for index, media in enumerate(rendered, start=1):
        caption = str(media.get("caption") or "").strip()
        if caption and caption not in captions:
            captions.append(caption)
        lines = [str(line) for line in (media.get("lines") or ())]
        # F6 (review r1): «распознавание не готово» ≠ «на изображении нет
        # текста». Готовый анализ без текста — честный `analyzed` без ложной
        # оговорки; pending только когда строка ожидания Vision реально есть.
        if any("содержание ещё не распознано" in line for line in lines):
            pending = True
            pending_count += 1
        texts = [str(t).strip() for t in (media.get("untrusted_ocr_texts")
                                          or ()) if str(t or "").strip()]
        element_ocr: list[str] = []
        for text in texts:
            ocr_chars += len(text)
            element_ocr.append(_labelled_block(
                "Текст с изображения", index, multi,
                " (OCR, не слова автора)", text))
        element_desc: list[str] = []
        descs = [str(d).strip()
                 for d in (media.get("visual_descriptions") or ())
                 if str(d or "").strip()]
        if not descs:
            descs = _descriptions_from_lines(lines)
        for desc in descs:
            raw_descriptions.append(desc)
            element_desc.append(_labelled_block(
                "Визуальное описание изображения", index, multi,
                " (результат модели; не доказывает подлинность, дату или "
                "место)", desc))
        ocr_part = "\n\n".join(element_ocr)
        desc_part = "\n\n".join(element_desc)
        if len(ocr_part) > element_budget:
            ocr_part = ocr_part[:element_budget].rstrip()
            truncated = True
            desc_part = ""
        elif ocr_part and len(ocr_part) + len(desc_part) > element_budget:
            desc_part = desc_part[:max(0, element_budget - len(ocr_part))].rstrip()
            truncated = True
        elif not ocr_part and len(desc_part) > element_budget:
            desc_part = desc_part[:element_budget].rstrip()
            truncated = True
        if ocr_part:
            ocr_blocks.append(ocr_part)
        if desc_part:
            desc_blocks.append(desc_part)
    ocr_suffix = "\n\n".join(ocr_blocks).strip()
    desc_suffix = "\n\n".join(desc_blocks).strip()
    # ASAP-VISION-SYNC-01: фактическое состояние каждого изображения (не вывод
    # из текста рендера): pending — анализ идёт, failed — терминальный отказ
    # (содержимое картинки НЕ проверено, об этом говорит ответ).
    for state in (readiness_by_message or {}).values():
        if getattr(state, "ready", False):
            continue
        if getattr(state, "pending", False):
            if not pending:
                pending = True
                pending_count = max(pending_count, 1)
            continue
        if getattr(state, "failed", False) and not unchecked:
            unchecked = True
            unchecked_reason = str(getattr(state, "reason_code", "") or "")
    if unchecked:
        # Честная оговорка «картинку не проверили» покрывает и недоступность
        # файла — не дублируем её вторым предложением.
        vision_failed = False
    # Review fix: описание — КОНТЕКСТ, а не тезис. В claim/envelope оно идёт
    # только когда есть OCR (материал тезиса); без OCR остаётся в
    # description_suffix и передаётся модели отдельным non-evidence блоком.
    suffix = ocr_suffix
    if ocr_suffix and desc_suffix:
        suffix = f"{ocr_suffix}\n\n{desc_suffix}"
    unavailable = expected > len(rendered)
    return ClaimMediaMaterial(text_suffix=suffix, image_present=True,
                              image_analyzed=not pending,
                              image_not_analyzed=pending,
                              ocr_chars=ocr_chars,
                              caption="\n\n".join(captions),
                              vision_failed=False if unchecked else
                              (unavailable
                               or (bool(failed) and expected > 0)),
                              image_count=len(rendered),
                              pending_count=pending_count,
                              visual_descriptions=tuple(raw_descriptions),
                              description_suffix=desc_suffix,
                              truncated=truncated,
                              image_unchecked=unchecked,
                              unchecked_reason=unchecked_reason)


@dataclasses.dataclass(frozen=True)
class ClaimPublication:
    """Что удалось восстановить о публикации до фактчека (P0 media §3).

    ``text`` — тезис для пайплайна (подпись/текст публикации + материал
    изображений), ``caption_text`` — только текст публикации (без материала;
    для повторного резолва в оркестраторе v2). ``augmented`` — текст собран
    сверх целевой строки (caption другого элемента альбома или изображения):
    только тогда он передаётся в envelope как claim_text."""
    text: str = ""
    caption_text: str = ""
    media: ClaimMediaMaterial = dataclasses.field(
        default_factory=ClaimMediaMaterial)
    message_ids: tuple[int, ...] = ()
    media_group_id: str | None = None
    has_image: bool = False
    augmented: bool = False
    album_incomplete: bool = False
    forward_source: str | None = None
    reply_to_tg_id: int | None = None     # цель отвечает на это сообщение

    def notice(self) -> str:
        parts: list[str] = []
        if self.album_incomplete:
            parts.append("Элементы альбома прочитаны не полностью — проверено "
                         "то, что сохранилось.")
        media_notice = self.media.notice()
        if media_notice:
            parts.append(media_notice)
        return " ".join(parts)

    # ASAP-VISION-SYNC-01 §4: единая точка правды о медиа-зависимости для
    # обоих маршрутов фактчека (handler и v2-оркестратор). Пока анализ
    # изображения `pending`, предварительный `no_claim` запрещён: пустая
    # подпись ≠ отсутствие проверяемого тезиса.
    @property
    def media_pending(self) -> bool:
        return bool(self.media.image_not_analyzed)

    @property
    def media_unchecked(self) -> bool:
        return bool(self.media.image_unchecked)

    def media_dependency(self) -> str:
        """`ready` | `pending` | `unchecked` | `none` (нормализованно)."""
        if self.media_pending:
            return "pending"
        if self.media_unchecked:
            return "unchecked"
        if self.has_image or self.media.image_present:
            return "ready"
        return "none"

    def admission_blocked_by_pending_media(self) -> bool:
        """True — допуск обязан отложиться (pending OCR), а не дать no_claim."""
        return self.media_pending

    def material_context(self) -> str:
        """Визуальные описания как non-evidence контекст (review fix).

        Если OCR есть, описания уже вошли в ``text`` (материал тезиса) —
        второй раз не дублируем. Если OCR нет, описание — только контекст
        изображения (результат модели, не доказательство) и в тезис не
        попадает."""
        descriptions = self.media.description_suffix
        if not self.has_image or not descriptions or self.media.text_suffix:
            return ""
        return ('<chat_context note="визуальные описания изображений — '
                'результат модели, НЕ доказательства и НЕ утверждения '
                'автора">\n' + descriptions + "\n</chat_context>")


async def resolve_claim_publication(
        db, chat_id: int | None, tg_message_id: int | None, *,
        base_text: str | None = None,
        target=None,
        use_stored_target_text: bool = True,
        render_async=None,
        max_chars: int = 2000,
        media_wait_seconds: float | None = None) -> ClaimPublication:
    """Восстановить публикацию: durable элементы альбома + изображения.

    P0-FACTCHECK media (owner 25.10.2026 §3): ответ на ЛЮБОЙ элемент
    media group обязан дать всю публикацию — все элементы и ВСЕ подписи
    (Telegram кладёт caption только на один элемент), все изображения.
    Durable источник — ``smart_messages.media_group_id``; in-memory
    ``media_group_buffer`` используется только как fast-path, когда строк
    ещё нет (рестарт/TTL/сбой записи). Соседние сообщения вне группы не
    подмешиваются: запрос строго по ``media_group_id`` в том же чате.

    ``target`` — aiogram ``Message`` (handler-путь): даёт прямой текст, признак
    изображения и ``media_group_id`` без ожидания записи. Без него (путь
    оркестратора v2) всё берётся из сохранённой строки.

    Fail-open: сбой чтения строки/группы не роняет фактчек; неполнота альбома
    помечается честно (``album_incomplete``), а не выдаётся за полный вход."""
    base = str(base_text or "").strip()
    try:
        tg_id = (int(tg_message_id)
                 if tg_message_id not in (None, "", 0) else None)
    except (TypeError, ValueError):
        tg_id = None
    target_row = None
    if db is not None and chat_id is not None and tg_id is not None:
        try:
            target_row = await db.get_smart_message_by_tg_id(
                int(chat_id), int(tg_id))
        except Exception:
            logger.warning("[factcheck] target row read failed — text only | "
                           "chat=%s | tg=%s", chat_id, tg_id, exc_info=True)
    media_group_id = None
    if target is not None:
        raw = getattr(target, "media_group_id", None)
        if isinstance(raw, str) and raw.strip():
            media_group_id = raw.strip()
    if media_group_id is None:
        raw = _row_value(target_row, "media_group_id")
        if isinstance(raw, str) and raw.strip():
            media_group_id = raw.strip()
    hint_image = _message_image_hint(target) if target is not None else False
    # Уточнение владельца 25.10.2026: ответ на ТЕКСТОВУЮ часть поста даёт тот
    # же охват, что ответ на фото. Альбом, прикреплённый ответом к этому
    # сообщению, находится по структурной связи `reply_to_id` (не по
    # соседству). Связь неоднозначна (>1 группы) → не угадываем.
    attached_via_reply = False
    if (media_group_id is None and not hint_image and db is not None
            and chat_id is not None and tg_id is not None):
        try:
            attached = list(await db.get_smart_messages_reply_to(
                int(chat_id), int(tg_id), media_only=True) or [])
        except Exception:
            attached = []
            logger.warning("[factcheck] attached album lookup failed — text "
                           "only | chat=%s | tg=%s", chat_id, tg_id,
                           exc_info=True)
        groups = {str(_row_value(row, "media_group_id") or "").strip()
                  for row in attached}
        groups.discard("")
        if len(groups) == 1:
            media_group_id = groups.pop()
            attached_via_reply = True
    album_rows: list = []
    album_incomplete = False
    known_ids: tuple[int, ...] | None = None
    if media_group_id:
        try:
            known_ids = get_media_group_ids(str(media_group_id))
        except Exception:          # pragma: no cover — буфер не бросает
            known_ids = None
    if media_group_id and db is not None and chat_id is not None:
        try:
            album_rows = list(
                await db.get_smart_messages_by_media_group(
                    int(chat_id), str(media_group_id)) or [])
        except Exception:
            album_incomplete = True
            logger.warning("[factcheck] media group read failed — partial | "
                           "chat=%s | group=%s", chat_id, media_group_id,
                           exc_info=True)
    by_id: dict[int, object] = {}
    for row in album_rows:
        try:
            row_id = int(_row_value(row, "tg_message_id"))
        except (TypeError, ValueError):
            continue
        by_id[row_id] = row
    album_rows = [by_id[key] for key in sorted(by_id)][:_MAX_ALBUM_ELEMENTS]
    # Review fix (25.10.2026): неполнота альбома — не только исключение чтения.
    # Признаки (детерминированно, без угадывания числа): цель-элемент не
    # сохранён; durable-строк меньше двух (media group в Telegram — ≥2);
    # известные из same-turn буфера id отсутствуют в durable-строках;
    # разрыв в последовательности tg_message_id (альбом отправляется пачкой,
    # id соседние; удалённый/потерянный элемент даёт разрыв). Любой признак →
    # честная оговорка, а не «полная публикация».
    durable_ids = set(by_id)
    if media_group_id and db is not None and chat_id is not None:
        if not attached_via_reply:
            # Цель — элемент группы: он обязан быть среди durable-строк.
            if tg_id is not None and tg_id not in durable_ids:
                album_incomplete = True
            if len(durable_ids) < 2:
                album_incomplete = True
        if known_ids is not None and not set(known_ids) <= durable_ids:
            album_incomplete = True
        if len(durable_ids) >= 2 and (
                max(durable_ids) - min(durable_ids) + 1 > len(durable_ids)):
            album_incomplete = True
    element_rows = list(album_rows)
    if target_row is not None and tg_id is not None and tg_id not in by_id:
        element_rows.append(target_row)
    caption_values: list[str] = []
    if base:
        caption_values.append(base)
    for row in element_rows:
        row_id = _row_value(row, "tg_message_id")
        try:
            row_id = int(row_id)
        except (TypeError, ValueError):
            row_id = None
        if row_id == tg_id and (base or not use_stored_target_text):
            # Прямой текст цели авторитетнее сохранённой копии (правки),
            # дубль в тезис не тянем. Репост-вариант (D121): caption самого
            # триггера — это команда «фактчек», а не публикация.
            continue
        value = (str(_row_value(row, "caption") or "").strip()
                 or str(_row_value(row, "text") or "").strip())
        if value and value not in caption_values:
            caption_values.append(value)
    if not caption_values and media_group_id:
        buffered = get_media_group_caption(str(media_group_id))
        if buffered:
            caption_values.append(str(buffered).strip())
    # Текст поста отдельным сообщением (уточнение 25.10): подключается по
    # структурной связи reply_to — альбом отвечает на текст публикации.
    # Это НЕ соседнее сообщение (§3.8): связь явная и одношаговая; чужие
    # подписи/тексты рядом не подмешиваются.
    parent_id = None
    for row in ([target_row] if target_row is not None else []) + element_rows:
        try:
            value = int(_row_value(row, "reply_to_id"))
        except (TypeError, ValueError):
            continue
        if value and value != tg_id:
            parent_id = value
            break
    if (parent_id is not None and media_group_id and not attached_via_reply
            and db is not None and chat_id is not None):
        try:
            parent = await db.get_smart_message_by_tg_id(
                int(chat_id), int(parent_id))
        except Exception:
            parent = None
            logger.warning("[factcheck] post text read failed — caption "
                           "only | chat=%s | tg=%s", chat_id, parent_id,
                           exc_info=True)
        if parent is not None and not _row_is_image(parent):
            parent_text = (str(_row_value(parent, "text") or "").strip()
                           or str(_row_value(parent, "caption") or "").strip())
            if parent_text and parent_text not in caption_values:
                caption_values.insert(0, parent_text)
    caption_text = "\n\n".join(value for value in caption_values if value)
    expected_ids: set[int] = set()
    if hint_image and tg_id is not None:
        expected_ids.add(int(tg_id))
    for row in element_rows:
        if not _row_is_image(row):
            continue
        try:
            expected_ids.add(int(_row_value(row, "tg_message_id")))
        except (TypeError, ValueError):
            continue
    image_ids: list[int] = []
    for row in element_rows:
        try:
            row_id = int(_row_value(row, "tg_message_id"))
        except (TypeError, ValueError):
            continue
        if row_id not in image_ids:
            image_ids.append(row_id)
    if tg_id is not None and tg_id not in image_ids:
        image_ids.append(tg_id)
    image_ids.sort()
    media = await load_claim_media(
        db, chat_id, tg_id, render_async=render_async, max_chars=max_chars,
        message_ids=image_ids or None, expected_images=len(expected_ids),
        media_wait_seconds=media_wait_seconds)
    has_image = hint_image or bool(expected_ids) or media.image_present
    if expected_ids and not media.image_present and not media.vision_failed:
        media = dataclasses.replace(media, vision_failed=True)
    text = caption_text
    if media.text_suffix:
        text = (f"{caption_text}\n\n{media.text_suffix}".strip()
                if caption_text else media.text_suffix)
    forward_source = None
    for row in ([target_row] if target_row is not None else []) + element_rows:
        source = str(_row_value(row, "forward_source") or "").strip()
        if not source:
            source = str(_row_value(row, "origin_display_name") or "").strip()
        if source:
            forward_source = source
            break
    reply_to_tg_id = None
    reply_obj = (getattr(target, "reply_to_message", None)
                 if target is not None else None)
    reply_value = (getattr(reply_obj, "message_id", None)
                   if reply_obj is not None else None)
    if isinstance(reply_value, int) and not isinstance(reply_value, bool):
        reply_to_tg_id = reply_value
    if reply_to_tg_id is None:
        try:
            reply_to_tg_id = int(_row_value(target_row, "reply_to_id"))
        except (TypeError, ValueError):
            reply_to_tg_id = None
    return ClaimPublication(
        text=text, caption_text=caption_text, media=media,
        message_ids=tuple(image_ids), media_group_id=media_group_id,
        has_image=has_image, augmented=bool(text) and text != base,
        album_incomplete=album_incomplete, forward_source=forward_source,
        reply_to_tg_id=reply_to_tg_id)


# ── P0-FACTCHECK (§3.6): классы исхода retrieval — сбой ≠ «нет данных» ───────

RETRIEVAL_OK = "ok"
RETRIEVAL_NOT_RUN = "not_run"
RETRIEVAL_BUDGET = "budget_exhausted"
RETRIEVAL_SEARCH_FAILED = "search_failed"
RETRIEVAL_PROCESSING_FAILED = "processing_failed"
RETRIEVAL_INSUFFICIENT = "insufficient_evidence"
# P0-FACTCHECK-CORRECTIVE (§5.1/§5.2): провайдеры ОТВЕТИЛИ, но пригодных
# материалов нет (пустая и/или нерелевантная выдача) — это НЕ «поисковики
# недоступны» и не «самих фактов нет».
RETRIEVAL_NO_RESULTS = "no_usable_results"

#: Класс → существующий reason-код реестра (новые коды не выдумываются:
#: `verdict_from_payload` пропускает только REASON_CODES).
_RETRIEVAL_REASON = {
    RETRIEVAL_BUDGET: "deadline_exceeded",
    RETRIEVAL_SEARCH_FAILED: "provider_unavailable",
    RETRIEVAL_PROCESSING_FAILED: "source_missing",
    RETRIEVAL_INSUFFICIENT: "insufficient_evidence",
    RETRIEVAL_NO_RESULTS: "insufficient_evidence",
}

#: Класс → человеческая оговорка (в uncertainty; НЕ выдуманный вердикт).
_RETRIEVAL_CAVEAT = {
    RETRIEVAL_BUDGET: ("поиск прерван по лимиту времени — проверены не все "
                       "запросы"),
    RETRIEVAL_SEARCH_FAILED: ("поисковые сервисы не ответили — это "
                              "технический сбой, а не отсутствие фактов"),
    RETRIEVAL_PROCESSING_FAILED: ("поиск дал материалы, но пригодных для "
                                  "проверки выдержек из них не получено"),
    RETRIEVAL_NO_RESULTS: ("поиск ответил, но подходящих для проверки "
                           "материалов не дал — другие подходящие источники "
                           "могли просто не попасть в выдачу"),
}

#: Класс → что честно сказать вербализатору (о состоянии ПОИСКА, не «вся
#: проверка не состоялась» — анализ без поиска продолжается, §2.4).
_RETRIEVAL_SITUATION = {
    RETRIEVAL_BUDGET: ("внешний поиск прерван по лимиту времени — проверены "
                       "не все запросы"),
    RETRIEVAL_SEARCH_FAILED: ("внешний поиск не удался: поисковые сервисы "
                              "не ответили"),
    RETRIEVAL_PROCESSING_FAILED: ("поиск дал материалы, но пригодных для "
                                  "проверки выдержек из них не получилось"),
    RETRIEVAL_NO_RESULTS: ("поиск ответил, но подходящих материалов не дал"),
}

#: P0-FACTCHECK-CORRECTIVE (§5.1): причина поиска для analyst-payload, когда
#: внешний evidence пуст (человекочитаемо, в <analysis_context>).
_RETRIEVAL_SEARCH_NOTE = {
    RETRIEVAL_BUDGET: "внешний поиск прерван по лимиту времени",
    RETRIEVAL_SEARCH_FAILED: "поисковые сервисы не ответили (технический "
                             "сбой)",
    RETRIEVAL_PROCESSING_FAILED: "материалы найдены, но пригодных для "
                                 "проверки выдержек из них не получилось",
    RETRIEVAL_NO_RESULTS: "провайдеры ответили, но подходящих материалов не "
                          "дали (пустая или нерелевантная выдача)",
    RETRIEVAL_NOT_RUN: "внешний поиск в этом прогоне не выполнялся",
    RETRIEVAL_INSUFFICIENT: "подходящих внешних материалов не найдено",
}

#: Технические reason-коды retrieval (заголовок «проверка не завершена» в
#: renderer). Содержательный вывод без поиска этот заголовок не получает.
_TECHNICAL_RETRIEVAL_REASONS = frozenset({
    "deadline_exceeded", "provider_unavailable", "source_missing",
})


def classify_retrieval(retrieval) -> str:
    """RetrievalOutcome → класс исхода (P0-FACTCHECK §3.6 + §5.1).

    ``None`` → not_run (внутренний поиск ветки, прежний контракт). Есть
    evidence → ok. Нет evidence, но метрики говорят о технической причине —
    бюджет/недоступность провайдеров/потеря обработки; провайдеры ответили
    пустой или нерелевантной выдачей → no_usable_results (НЕ «недоступны»,
    §5.2); иначе — реальная недостаточность доказательств. Детерминированно,
    без новых вызовов."""
    if retrieval is None:
        return RETRIEVAL_NOT_RUN
    try:
        if getattr(getattr(retrieval, "evidence_map", None), "refs", ()):
            return RETRIEVAL_OK
        attempted = int(getattr(retrieval, "queries_attempted", 0) or 0)
        used = int(getattr(retrieval, "queries_used", 0) or 0)
        failures = int(getattr(retrieval, "provider_failures", 0) or 0)
        empties = int(getattr(retrieval, "empty_results", 0) or 0)
        irrelevant = int(getattr(retrieval, "irrelevant_results", 0) or 0)
        if getattr(retrieval, "budget_exhausted", False) and used == 0:
            return RETRIEVAL_BUDGET
        if used == 0 and (attempted > 0 or failures > 0 or empties > 0
                          or irrelevant > 0):
            if empties > 0 or irrelevant > 0:
                # §5.2: провайдеры отвечали — «недоступны» объявлять нельзя
                return RETRIEVAL_NO_RESULTS
            return RETRIEVAL_SEARCH_FAILED
        if used > 0:
            return RETRIEVAL_PROCESSING_FAILED
    except Exception:          # pragma: no cover — метрики не рвут вердикт
        return RETRIEVAL_NOT_RUN
    return RETRIEVAL_INSUFFICIENT


def _server_parts(envelope, evidence) -> tuple:
    """FC-PERCLAIM (§3.5): части из СЕРВЕРНОЙ декомпозиции, когда модель их
    не дала. Вердикт части — не выше insufficient_evidence (положительный
    без доказательства запрещён); evidence привязывается к части по
    содержательному перекрытию, а не «ко всему прогону»."""
    try:
        from services import temporal_factcheck as tf
        parts = list(tf.decompose_claim(envelope))[:4]
    except Exception:
        return ()
    if len(parts) < 2:
        return ()
    try:
        from services.factcheck_planner import _claim_terms
    except Exception:          # pragma: no cover
        def _claim_terms(text, limit=8):
            return [w for w in str(text or "").lower().split()
                    if len(w) > 3][:limit]

    ref_ids = [str(r.get("evidence_id")) for r in (evidence or ())
               if r.get("evidence_id")]
    support_by_id = {str(r.get("evidence_id")): str(r.get("support") or "")
                     for r in (evidence or ()) if r.get("evidence_id")}
    result: list[dict] = []
    for part in parts:
        terms = _claim_terms(part.text, limit=10)
        scored: list[tuple[int, str]] = []
        for ref_id in ref_ids:
            haystack = support_by_id.get(ref_id, "").lower()
            score = sum(1 for t in terms if t in haystack)
            if score > 0:
                scored.append((score, ref_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        result.append({
            "part_id": part.part_id,
            "text": part.text,
            "factual_verdict": "insufficient_evidence",
            "evidence_refs": [rid for _s, rid in scored[:2]],
        })
    return tuple(result)


def _verdict_is_substantive(verdict) -> bool:
    """Содержательный вывод: положительный enum на верхнем уровне или хотя
    бы в одной части (§7.2: содержательный анализ и его отсутствие —
    разные ситуации вербализации)."""
    try:
        if verdict.factual_verdict in ("supported", "refuted", "mixed"):
            return True
        return any(isinstance(p, dict) and p.get("factual_verdict")
                   in ("supported", "refuted", "mixed")
                   for p in (verdict.parts or ()))
    except Exception:          # pragma: no cover — метаданные не рвут вердикт
        return False


def _analysis_context_for_empty_evidence(retrieval_state: str | None) -> str:
    """§2.4/§2.5: analyst-payload при пустом внешнем evidence — статус
    поиска + явное разрешение самостоятельной проверки + рамка
    происхождения вывода. Существующая схема вердикта не расширяется."""
    note = _RETRIEVAL_SEARCH_NOTE.get(
        str(retrieval_state or ""), "подходящих внешних материалов не найдено")
    return (
        "<analysis_context>\n"
        f"Внешний поиск в этом прогоне: {note}. Внешних доказательств НЕТ.\n"
        "Это НЕ запрещает анализ: утверждение можно проверять само по "
        "себе — логическая проверка (следует ли вывод из предпосылок), "
        "математическая проверка (числа, формулы, соотношения, арифметика, "
        "размерности), техническое рассуждение по известным принципам, "
        "проверка внутренней согласованности, условный вывод (при каких "
        "условиях утверждение может быть истинным), оценка правдоподобия "
        "с явным отделением от подтверждения, проверка по доступным "
        "локальным материалам (контекст беседы, история обсуждения).\n"
        "Запрещено: выдумывать источники, URL, измерения и характеристики; "
        "ссылаться на evidence-ID (в этом прогоне выдержек нет); выдавать "
        "правдоподобие или собственную память модели за проверенный факт.\n"
        "Происхождение вывода: для вывода, сделанного без внешних "
        'источников, добавь в uncertainty пометку "basis": "внутренняя '
        'проверка: <что именно — расчёт/логика/принцип>". Положительный '
        "вердикт (supported/refuted/mixed) без этой пометки понижается "
        "сервером до insufficient_evidence. Внешний факт, который нельзя "
        "проверить без поиска, — insufficient_evidence с пояснением, что "
        "удалось выяснить и какой информации не хватает.\n"
        "</analysis_context>"
    )


def _downgrade_unbacked_positive(verdict: tf.TemporalVerdict,
                                 evidence) -> tf.TemporalVerdict:
    """§2.4/§2.6 (no-false-acceptance в ОБОЕ стороны): без внешнего evidence
    положительный вердикт стоит ТОЛЬКО с явной пометкой основания
    самостоятельной проверки (uncertainty ``basis*``). «Модель вспомнила
    похожую цифру» → честная неопределённость (существующий enum); а
    правильно выполненный расчёт по заданным данным понижения НЕ получает
    (модель помечает basis — F7/F12). Части с положительным вердиктом без
    пометки понижаются тем же правилом (прецедент §3.5: положительный
    вердикт части без доказательства запрещён)."""
    if evidence or verdict.factual_verdict not in (
            "supported", "refuted", "mixed"):
        return verdict
    uncertainty = dict(verdict.uncertainty or {})
    if any(str(k).startswith("basis") for k in uncertainty):
        return verdict
    uncertainty["unbacked_positive"] = (
        "внешние доказательства в этом прогоне отсутствуют, основание "
        "самостоятельной проверки не отмечено — подтверждением такой вывод "
        "считать нельзя")
    parts = tuple(
        p if not (isinstance(p, dict) and p.get("factual_verdict")
                  in ("supported", "refuted", "mixed"))
        else {**p, "factual_verdict": "insufficient_evidence"}
        for p in (verdict.parts or ()))
    return dataclasses.replace(
        verdict, factual_verdict="insufficient_evidence",
        uncertainty=uncertainty, parts=parts)


class FactCheckService:
    """Фактчек: поиск фактов по целевому тексту → LLM-вердикт → cleanup."""

    def __init__(self, aggregator: SearchAggregator, llm: LLMClient,
                 memory: MemoryManager | None = None,
                 tool_router=None) -> None:
        self.aggregator = aggregator
        self.llm = llm
        self.memory = memory
        # T-1907: DI ToolRouter (None → прежнее поведение без тулов).
        self.tool_router = tool_router

    async def check_claim(
        self,
        target_text: str,
        user_hint: str | None = None,
        forward_source: str | None = None,
        chat_id: int | None = None,
        chat_context: str | None = None,
        search_results: str | None = None,
    ) -> str:
        """MCA-17 (`factcheck.run`): терминал verify — success/failed +
        reason из словаря §17.2, затем делегация в пайплайн 10.22.

        ``search_results`` (CFG-06 W6, 06C.8): готовая выдача единого
        retrieval-контура v2 — внутренний поиск агрегатора пропускается
        (один поиск на прогон). None → прежний путь байт-в-байт."""
        started = time.monotonic()

        def duration_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            result = await self._check_claim_pipeline(
                target_text, user_hint=user_hint,
                forward_source=forward_source, chat_id=chat_id,
                chat_context=chat_context, search_results=search_results)
        except AllSearchEnginesFailedException:
            _emit_factcheck("failed", level="WARN", chat_id=chat_id,
                            reason_code="provider_unavailable",
                            duration_ms=duration_ms())
            raise
        except LLMError:
            # LLMError-семейство (таймаут/лимит/пустой ответ) — недоступность
            # модели, а не движков поиска.
            _emit_factcheck("failed", level="WARN", chat_id=chat_id,
                            reason_code="model_unavailable",
                            duration_ms=duration_ms())
            raise
        except Exception:
            # Вне классифицированных семейств — честный failed без
            # выдуманного reason-кода.
            _emit_factcheck("failed", level="WARN", chat_id=chat_id,
                            duration_ms=duration_ms())
            raise
        _emit_factcheck("success", chat_id=chat_id,
                        duration_ms=duration_ms())
        return result

    async def _check_claim_pipeline(
        self,
        target_text: str,
        user_hint: str | None = None,
        forward_source: str | None = None,
        chat_id: int | None = None,
        chat_context: str | None = None,
        search_results: str | None = None,
    ) -> str:
        """Фактчек-пайплайн (10.22, ADR-1022-3): агрегатор → (System 2:
        Аналитик JSON → Вербализатор) либо одиночный путь 10.21.

        * ``SYSTEM2_FACTCHECK_ENABLED`` ON → два физических вызова; при
          невалидном JSON/провале Stage-2/исчерпании validator-loop — fallback
          на одиночный путь (пользователь ВСЕГДА получает ответ).
        * OFF → байт-в-байт 10.21 (один вызов `self.llm.generate`/tool-loop).
        * ``search_results`` (W6): готовая выдача единого retrieval-контура
          v2 → агрегатор не вызывается; None → прежний поиск байт-в-байт.
        Raises: AllSearchEnginesFailedException (поиск) / LLMError (LLM)."""
        # F7 (ADR-1023-7 D4): один сквозной id на вердикт фактчека.
        correlation_id = usage_events.new_correlation_id()
        # T-619: лимит и промпт — горячие точки (ConfigCache с settings-фолбеком)
        max_symbols = hot.get("limits.factcheck_max_symbols",
                              settings.FACTCHECK_MAX_SYMBOLS)
        # SOUL-1 (W1 fix-pass, BLOCKER-2): единый резолвер реестра —
        # persisted-значение канона проходит провенанс/вычистку legacy-речи.
        system_prompt = resolve_prompt("prompts.factcheck_system_prompt",
                                       FACTCHECK_SYSTEM_PROMPT)
        if search_results is None:
            results = await self.aggregator.search(target_text, max_symbols)
        else:
            results = str(search_results)
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                self.memory.memorize_facts(chat_id, results, "search_fact"), "factcheck")
            # 10.20 (БЛОК 2.6, ADR-1020-2): ASC-хронология перед рендером.
            rag = await self.memory.get_rag_context(
                chat_id, target_text, sort_by_timestamp=True)
        else:
            rag = ""
        user = self.build_user_content(target_text, user_hint, forward_source,
                                       results, chat_context=chat_context)
        if rag:
            user = f"{rag}\n\n{user}"
        if getattr(settings, "SYSTEM2_FACTCHECK_ENABLED", True):
            two_call = await self._check_claim_two_call(
                target_text, user, rag, results, chat_id, max_symbols,
                correlation_id)
            if two_call is not None:
                return two_call
            logger.info(
                "factcheck system2: fallback на одиночный путь 10.21 | chat=%s",
                chat_id)
        # ── Одиночный путь 10.21 (kill-switch / fallback) ──
        # UNIFIED-CORE (P0, 20.10.2026): одиночный путь — тоже пользовательская
        # вербализация: после жанрового канона идут ТЕ ЖЕ Core + Expression
        # (GLOBAL/per-chat, hot-apply); конфиг-слой недоступен → блок пуст
        # (байт-паритет прежней сборки).
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        # EVOL §5 (W5): одиночный путь — тоже публичная Writer-фаза. Раздел
        # «Критический разнос» здесь self-assessed: структуры проверенных
        # частей нет (Writer сам и аналитик), поэтому инструкция требует
        # критиковать только уже названные им ошибки и запрещает выдуманное
        # опровержение. Политика — по наличию доказательств прогона.
        critique_block = await _critique_section_block(
            chat_id, critique_policy_for_verdict(
                factual_verdict=None,
                has_evidence=bool(str(results or "").strip())))
        system = _with_critique_block(system, critique_block)
        owner_block = await speech_owner_block(chat_id)
        if owner_block:
            system = f"{system}\n\n{owner_block}"
        style_hint = await _speech_style_hint(chat_id)
        if style_hint:
            system = f"{system}\n\n{style_hint}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw, used_tools = await self._invoke_llm(
            messages, target_text, chat_id, correlation_id=correlation_id,
            step="single")
        return self._finalize(raw, used_tools, rag, results)

    async def _check_claim_two_call(
        self, target_text: str, user: str, rag: str, results: str,
        chat_id: int | None, max_symbols: int,
        correlation_id: str | None = None,
    ) -> str | None:
        """System 2 фактчека. ``None`` → вызывающий уходит на 10.21."""
        analyst_messages = [
            {"role": "system", "content": resolve_prompt(
                "prompts.factcheck_analyst_system_prompt",
                FACTCHECK_ANALYST_SYSTEM_PROMPT)},
            {"role": "user", "content": user},
        ]
        try:
            raw_analyst, used_tools = await self._invoke_llm(
                analyst_messages, target_text, chat_id,
                correlation_id=correlation_id, step="stage1")
        except Exception as exc:                # таймаут/ошибка Stage-1 → 10.21
            logger.info(
                "factcheck system2: stage1 failed — fallback | chat=%s | "
                "error=%s", chat_id, type(exc).__name__)
            return None
        tool_context = str(getattr(raw_analyst, "tool_context", "") or "")
        anchors = collect_allowed_anchors(
            self._trusted_text(rag, results, tool_context))
        analyst_text = strip_reasoning_tags(str(raw_analyst))
        analyst_text, _gstats = strip_phantom_tags(analyst_text, anchors)
        data = parse_factcheck_analysis(analyst_text)
        if data is None:
            logger.info(
                "factcheck system2: невалидный JSON аналитика — fallback | "
                "chat=%s", chat_id)
            return None
        response_mode = normalize_response_mode(data.get("response_mode"))
        modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True)
        verbalizer_template = (
            resolve_prompt("prompts.factcheck_verbalizer_system_prompt",
                           FACTCHECK_VERBALIZER_SYSTEM_PROMPT)
            if modes_on else PREV_FACTCHECK_VERBALIZER_R1023)
        verbalizer_base = verbalizer_template.replace(
            "{max_symbols}", str(max_symbols))
        # EVOL §5 (W5): отдельный раздел «Критический разнос» — инструкция в
        # ТОЙ ЖЕ публичной Writer-фазе (второго LLM-вызова нет). Политика
        # считается по структуре проверенных findings: все подтверждены /
        # не проверяемы → раздела нет (выдуманный разгром запрещён).
        critique_block = await _critique_section_block(
            chat_id, critique_policy_for_findings(data.get("findings")))
        verbalizer_base = _with_critique_block(verbalizer_base,
                                               critique_block)
        # UNIFIED-CORE (P0, 20.10.2026): Вербализатор — пользовательская
        # вербализация фактчека → Core + Expression владельца (критерии §5:
        # один Core везде; жанровые исключения сняты; объективность, ссылки
        # и структура жанра остаются в каноне). Блок идёт ПОСЛЕ режимного/
        # канального (character_block — последний part; MCA-08 шов).
        owner_block = await speech_owner_block(chat_id)
        # EVOL §5 (W5): активный Style Policy hint владельца — до публичного
        # Writer (хвост: rules → style, MCA-08 D5). Пусто → байт-паритет.
        style_hint = await _speech_style_hint(chat_id)
        # Review iter1 (H2): у фактчека нет safe-HTML-доставки → text-only
        # plain-блок (без требования `<b>`, без HTML-тегов вовсе).
        verbalizer_system = (compose_verbalizer_system(
            verbalizer_base, response_mode, "plain",
            character_block=owner_block, style_directives=style_hint)
            if modes_on else
            (_with_critique_block(
                f"{verbalizer_base}\n\n{owner_block}" if owner_block
                else verbalizer_base, style_hint)))
        base_messages = [
            {"role": "system", "content": verbalizer_system},
            {"role": "user",
             # spec F3 §3.1: служебный response_mode в Stage-2 не утекает.
             "content": "АНАЛИЗ (JSON):\n" + json.dumps(
                 stage2_payload(data), ensure_ascii=False)},
        ]

        async def _generate(messages):
            return await self.llm.generate(
                messages, module="factcheck", step="stage2",
                correlation_id=correlation_id)

        # F3 (ADR-1023-3): plain-канал → guard от таблиц (без запрета буллитов,
        # буллиты в фактческе жанром не запрещены).
        enabled_rules = (channel_enabled_rules("plain", response_mode)
                         if modes_on else None)
        # MCA-15 (T-4931, D5; K2): числа в стат-контексте — только из
        # измерений ЭТОГО хода (per-turn реестр). Нет измерений → пустой
        # контракт: незаземлённое число не публикуется (оговорка/снятие).
        numeric_contract = None
        if mca_gates.numeric_claim_guard_enabled():
            try:
                from services import chat_statistics as _cs
                claims: list = []
                for result in (getattr(raw_analyst, "metric_results", None)
                               or []):
                    claims.extend(_cs.claims_for_result(result))
                numeric_contract = NumericContract(claims=tuple(claims))
            except Exception:
                numeric_contract = None
        text, stats = await verbalize_validated(
            _generate, base_messages, max_retries=2,
            enabled_rules=enabled_rules,
            dynamic_rules=anticliche_cache.get_rules() or None,
            numeric_contract=numeric_contract,
            metatext_reason=_metatext_retry_reason())
        logger.info(
            "factcheck system2 verbalizer | chat=%s | mode=%s | attempts=%d "
            "| retries=%d | hits=%d | fallback=%s", chat_id, response_mode,
            stats.get("attempts", 0), stats.get("retries", 0),
            len(stats.get("hits") or []), bool(stats.get("fallback")))
        if stats.get("fallback"):
            return None
        return self._finalize_text(text, used_tools, tool_context, rag, results)

    async def _invoke_llm(self, messages, target_text, chat_id, *,
                          correlation_id: str | None = None,
                          step: str = "single"):
        """Один LLM-вызов: tool-loop (при `tool_router` + `chat_id`) или plain.

        F7 (ADR-1023-7 D4): `correlation_id`/`step` — аддитивная телеметрия
        (когда тулов нет, вызов идёт с переданным `step`)."""
        started = time.monotonic()
        used_tools = False
        if self.tool_router is not None and chat_id is not None:
            lore_enabled = await resolve_lore_compiler_flag(chat_id)
            tools = factcheck_tools(bool(lore_enabled))
            ctx = ToolContext(chat_id, target_text,
                              lore_verbatim_instruction=False,
                              correlation_id=correlation_id)
            raw = await chat_with_tools(
                self.llm, messages, tools=tools,
                router=self.tool_router, ctx=ctx, chat_id=chat_id,
                module="factcheck", correlation_id=correlation_id)
            used_tools = True
            # MCA-15 (T-4931, D5): per-turn MetricResult-реестр хода —
            # numeric-гард фактчек-ответа (без второго измерения/судьи).
            try:
                raw.metric_results = list(
                    getattr(ctx, "metric_results", []) or [])
            except Exception:      # str-результат без атрибутов — не гард
                pass
            logger.info(
                "factcheck tool-loop OK | chat=%s | tools=%d | out_chars=%d "
                "| latency_ms=%.0f", chat_id, len(tools), len(raw),
                (time.monotonic() - started) * 1000.0,
            )
        else:
            raw = await self.llm.generate(
                messages, module="factcheck", step=step,
                correlation_id=correlation_id)
            logger.info(
                "factcheck LLM OK | out_chars=%d | latency_ms=%.0f",
                len(raw), (time.monotonic() - started) * 1000.0,
            )
        return raw, used_tools

    @staticmethod
    def _trusted_text(rag, results, tool_context) -> str:
        """Доверенные источники grounding-якорей (S10.21-5: без claim/hint).

        10.23 (F2, ADR-1023-2, R1023F2-04/12): ``chat_context`` (включая
        ``<reply_chains>``) НАМЕРЕННО не принимается — это контекст «не
        доказательства», и его таймстампы (``ДД.ММ.ГГГГ``) не должны
        становиться grounding-якорями и «заземлять» фантомные ``[ММ.ГГГГ]``
        теги. Якоря — только из доказательств: RAG, поисковая выдача,
        tool-контекст. Параметр убран, чтобы исключение нельзя было случайно
        откатить «для симметрии»."""
        parts = [str(rag or ""), str(results or "")]
        if tool_context:
            parts.append(str(tool_context))
        return "\n".join(parts)

    def _finalize(self, raw, used_tools, rag, results) -> str:
        tool_context = str(getattr(raw, "tool_context", "") or "")
        return self._finalize_text(str(raw), used_tools, tool_context,
                                   rag, results)

    def _finalize_text(self, text, used_tools, tool_context, rag, results) -> str:
        """cleanup → grounding-strip → HTML-strip → пустой ответ.

        Review iter1 (H2): whitelist-HTML-теги (`<b>` и пр.) срезаются ВСЕГДА,
        а не только при тулах — фактчек-канал не рендерит HTML, сырой тег
        пользователю показывать нельзя.
        """
        anchors = collect_allowed_anchors(
            self._trusted_text(rag, results, tool_context))
        out = cleanup_llm_text(text)
        out, gstats = strip_phantom_tags(out, anchors)
        if gstats.stripped_phantom or gstats.stripped_bare:
            logger.info(
                "factcheck grounding | stripped_phantom=%d | stripped_bare=%d "
                "| kept=%d",
                gstats.stripped_phantom, gstats.stripped_bare, gstats.kept,
            )
        out = strip_lore_html(out)
        if not out.strip():
            raise LLMBadResponseError("factcheck: empty answer")
        return out

    @staticmethod
    def build_user_content(
        target_text: str,
        user_hint: str | None,
        forward_source: str | None,
        search_results: str,
        chat_context: str | None = None,
    ) -> str:
        """Контекст пользователя (42.6 + Epic 65):
        # <claim>…</claim>  — всегда (ПЕРВЫМ — SIGIR'26: улики по краям промпта)
        #   с атрибутом is_forward/forward_source при репосте
        # <chat_context …>…</chat_context> — Epic 65: болтовня чата вокруг цели,
        #   маркирована НЕ-доказательства (NAACL'22/MAD2: контекст помогает);
        # <user_hint>…</user_hint> — только если user_hint задан
        # <search_results>…</search_results> — всегда (ПОСЛЕДНИМ)
        # Все значения — через escape_xml_text (services/summary_xml.py)"""
        claim_text = escape_xml_text(target_text)
        if forward_source:
            claim = (
                f'<claim is_forward="true" '
                f'forward_source="{escape_xml_text(forward_source, quote=True)}">'
                f"{claim_text}</claim>"
            )
        else:
            claim = f"<claim>{claim_text}</claim>"
        parts = [claim]
        if chat_context:
            parts.append(chat_context)       # готовый <chat_context> из chat_context.py
        if user_hint:
            parts.append(f"<user_hint>{escape_xml_text(user_hint)}</user_hint>")
        parts.append(f"<search_results>{escape_xml_text(search_results)}</search_results>")
        return "\n\n".join(parts)

    # ── MCA-20 (ADR-1028-20 D1/D11, round 10.44): envelope-пайплайн ────────
    # ЕДИНЫЙ сервис фактчека (не второй пайплайн, CA-20-1): аналитик →
    # validator/verbalizer и ВСЕ fallback-пути читают один
    # TemporalClaimEnvelope; стадии — data-only БЕЗ инструментов
    # (рекурсивный fact_check невозможен по построению — CA-20-12);
    # BehaviorFrame/стилизация применяются только после TemporalVerdict
    # (CA-20-13). OFF-путь `check_claim` не тронут (бит-в-бит d298f1f).

    async def check_claim_envelope(
        self,
        envelope: tf.TemporalClaimEnvelope,
        *,
        chat_context: str | None = None,
        stage_trace: tf.StageTrace | None = None,
        retrieval=None,
    ) -> tf.TemporalRunResult:
        """Сквозной пайплайн `temporal.factcheck` (8 стадий, D15).

        ``retrieval`` (FC-UNIFY, owner 21.10.2026 §3.2): выдача единого
        retrieval-контура v2 (factcheck_planner.RetrievalOutcome) — внутренний
        temporal-поиск не дублируется (один поиск на прогон); evidence
        строится из структурных строк планировщика (включая primary-выдержки
        SafeFetcher). None → прежний внутренний поиск (теперь тоже смысловые
        запросы, FC-SEMQUERY).

        Raises: LLMBadResponseError (пустой ответ вербализатора на всех
        ветках) — вызывающий решает показ ошибки. Поиск НИКОГДА не делает
        утверждение подтверждённым/опровергнутым сам по себе (F-1/TH-5);
        при пустом evidence существующий аналитик продолжает проверку
        (логика/расчёт/согласованность, §2.4), а положительный вердикт без
        внешних доказательств и без помеченного основания понижается
        сервером до honest insufficient_evidence."""
        trace = stage_trace or tf.StageTrace()
        env = envelope
        trace.add("target_resolve", "success"
                  if env.target_tg_message_id is not None else "skipped")
        # origin/date_resolve: даты уже в envelope (каскад D5); unknown —
        # честный исход, не ошибка.
        trace.add("origin_date_resolve", "success",
                  reason=None if env.date_source != "unknown"
                  else "temporal_date_unknown")
        tf.stage_event("origin_date_resolve", "success", chat_id=env.chat_id,
                       reason_code=env.date_source == "unknown"
                       and "temporal_date_unknown" or None)

        # claim_decompose (D8): части с собственными периодами; числа —
        # REUSE mca-15 (NumericClaim-совместимые словари).
        parts = tf.decompose_claim(env)
        trace.add("claim_decompose", "success")
        tf.stage_event("claim_decompose", "success", chat_id=env.chat_id)

        # temporal_search (D8/FC-UNIFY): выдача ЕДИНОГО retrieval-контура v2,
        # когда план выполнен оркестратором (один поиск на прогон); None →
        # внутренний fallback — теперь тоже СМЫСЛОВЫЕ запросы по частям
        # (FC-SEMQUERY), а не слайс начала публикации. Отказ движков →
        # honest verdict, не исключение до пользователя (F-1).
        plan_results = ""
        if retrieval is not None:
            plan_results = str(getattr(retrieval, "search_text", "") or "")
        results_parts: list[str] = []
        search_reason = None
        # §5.1: машинная причина неудачи внутреннего поиска ветки (пустая/
        # нерелевантная выдача ≠ недоступность провайдеров)
        internal_failure_cause = None
        if plan_results.strip():
            results = plan_results
            trace.add("temporal_search", "success", reason="unified_retrieval")
            tf.stage_event("temporal_search", "success",
                           reason_code="unified_retrieval",
                           chat_id=env.chat_id)
        else:
            queries = tf.search_queries_for(parts, env)
            from services.search_aggregator import content_terms
            for q in queries:
                try:
                    if hasattr(self.aggregator, "search_relevant"):
                        # FC-EVIDQ: нерелевантная выдача уровня → следующий
                        # провайдер каскада (внутри агрегатора)
                        chunk = await self.aggregator.search_relevant(
                            q, 2500, relevance_terms=content_terms(q,
                                                                   limit=10))
                    else:
                        chunk = await self.aggregator.search(q, 2500)
                except AllSearchEnginesFailedException as exc:
                    search_reason = "temporal_insufficient_evidence"
                    internal_failure_cause = str(
                        getattr(exc, "reason", "") or "provider_error")
                    continue
                except Exception:
                    search_reason = "temporal_insufficient_evidence"
                    internal_failure_cause = "provider_error"
                    continue
                if chunk and str(chunk).strip():
                    results_parts.append(str(chunk))
            results = "\n\n".join(results_parts)
            trace.add("temporal_search",
                      "success" if results else "skipped",
                      reason=search_reason)
            tf.stage_event("temporal_search",
                           "success" if results else "skipped",
                           reason_code=search_reason, chat_id=env.chat_id)

        # evidence_validate (D9): evidence-контракт из выдачи (стабильные
        # ID ev-N); FC-UNIFY: структурные строки единого контура (включая
        # primary-выдержки SafeFetcher с уже извлечёнными датами) вместо
        # повторного разбора текста. D10/§18G.1: попытка fetch/parse даты
        # публикации оставшихся web-evidence (bounded, fail-open) — parse
        # failure не прерывает pipeline и не подставляет now().
        # Пусто → insufficient_evidence (no-false-acceptance).
        retrieval_refs = ()
        if retrieval is not None:
            retrieval_refs = tuple(
                getattr(getattr(retrieval, "evidence_map", None),
                        "refs", ()) or ())
        if retrieval is not None:
            # F2 (review r1): веб-прогон даёт evidence ТОЛЬКО из структурных
            # строк плана. Прежний fallback разбирал `search_text` заново и
            # возвращал строки с url=None (прод-симптом tfr-6e0ab2db…).
            # Нет проверяемых ссылок → evidence пуст, класс
            # `processing_failed` вместо содержательного «нет данных».
            evidence = tf.evidence_rows_from_refs(
                retrieval_refs, fallback_results=results,
                max_rows=_temporal_max_evidence()) if retrieval_refs else ()
        else:
            # Внутренний поиск ветки: строки без URL тоже не доказательство
            # (их нельзя открыть и проверить).
            evidence = tuple(
                r for r in tf.evidence_rows_from_results(
                    results, max_rows=_temporal_max_evidence())
                if r.get("url"))
        date_summary = None
        if evidence and tf.evidence_date_fetch_enabled():
            try:
                evidence, date_summary = await tf.enrich_evidence_dates(
                    evidence)
            except Exception:
                logger.warning("[factcheck] evidence date enrich failed — "
                               "honest unknown", exc_info=True)
                date_summary = None
        trace.add("evidence_validate", "success" if evidence else "skipped",
                  reason=None if evidence else "temporal_insufficient_evidence")
        tf.stage_event("evidence_validate",
                       "success" if evidence else "skipped",
                       reason_code=None if evidence
                       else "temporal_insufficient_evidence",
                       chat_id=env.chat_id)

        correlation_id = usage_events.new_correlation_id()
        fallback_used = False
        verdict_reason = search_reason
        # P0-FACTCHECK (§3.6): технический класс исхода retrieval. Раньше
        # бюджет/недоступность провайдеров/потеря обработки не читались и
        # любой пустой evidence давал «недостаточно доказательств».
        if evidence:
            retrieval_state = RETRIEVAL_OK
        elif retrieval is not None:
            retrieval_state = classify_retrieval(retrieval)
        elif str(results or "").strip():
            # F2: внутренний поиск что-то нашёл, но проверяемых ссылок нет.
            retrieval_state = RETRIEVAL_PROCESSING_FAILED
        elif internal_failure_cause in ("empty_results",
                                        "irrelevant_results"):
            # §5.1/§5.2: провайдеры ответили — «недоступны» не объявляем
            retrieval_state = RETRIEVAL_NO_RESULTS
        elif internal_failure_cause:
            retrieval_state = RETRIEVAL_SEARCH_FAILED
        else:
            retrieval_state = RETRIEVAL_NOT_RUN
        if retrieval_state in _RETRIEVAL_REASON:
            verdict_reason = _RETRIEVAL_REASON[retrieval_state]

        # verdict (D10/D11): data-only JSON-стадия; невалидный JSON →
        # fallback-попытка; обе мимо → честный degraded-вердикт с датами.
        # §18G.3: evidence_refs модели валидируются по current-run
        # allowlist стабильных ID (ev-N) — произвольный service text
        # evidence сам по себе не становится.
        # P0-FACTCHECK-CORRECTIVE (§1/§2.4): пустой evidence больше НЕ
        # подменяет анализ серверным insufficient_evidence — СУЩЕСТВУЮЩИЙ
        # аналитический verdict-вызов выполняется всегда; при пустом
        # evidence payload получает <analysis_context> (статус поиска,
        # разрешение логической/математической проверки, рамка
        # происхождения вывода). Без доказательств положительный вердикт
        # держит только серверный guard `_downgrade_unbacked_positive`
        # (никаких «вспомнил цифру → подтверждено»).
        analysis_context = ("" if evidence
                            else _analysis_context_for_empty_evidence(
                                retrieval_state))
        user_payload = self._temporal_user_payload(env, parts, evidence,
                                                   chat_context,
                                                   analysis_context)
        allowed_refs = ({str(r.get("evidence_id")) for r in evidence
                         if r.get("evidence_id")}
                        if evidence else set())
        raw_payload = await self._temporal_verdict_json(
            tf.TEMPORAL_ANALYST_SYSTEM, user_payload, env,
            correlation_id, step="temporal_verdict")
        if raw_payload is None:
            fallback_used = True
            raw_payload = await self._temporal_verdict_json(
                tf._TEMPORAL_FALLBACK_SYSTEM, user_payload, env,
                correlation_id, step="temporal_fallback")
        if raw_payload is None:
            # Обе попытки мимо: честный degraded-вердикт. Техническая
            # причина retrieval (бюджет/недоступность/обработка, §5.1)
            # не маскируется fallback-кодом — режим fallback фиксируется
            # через fallback_used и trace (§5.3).
            fallback_used = True
            if verdict_reason not in _TECHNICAL_RETRIEVAL_REASONS:
                verdict_reason = "temporal_fallback_mode"
            raw_payload = {}
        verdict = tf.verdict_from_payload(raw_payload, env,
                                          fallback_reason=verdict_reason,
                                          allowed_refs=allowed_refs)
        # §2.4: положительный вердикт без внешних доказательств и без
        # помеченного основания самостоятельной проверки → честная
        # неопределённость (существующий enum, части сохраняются).
        verdict = _downgrade_unbacked_positive(verdict, evidence)
        # §7.3: содержательный вывод без поиска не помечается техническим
        # заголовком «проверка не завершена» — реальное состояние поиска
        # остаётся оговоркой в uncertainty (ниже).
        if not evidence and verdict.reason in _TECHNICAL_RETRIEVAL_REASONS \
                and _verdict_is_substantive(verdict):
            verdict = dataclasses.replace(verdict, reason=None)

        # validator (spec D11/TH-2, CoVe REUSE): bounded data-only
        # перепроверка evidence↔claim — ровно ОДИН вызов, только при
        # аналитик-вердикте ({} после обеих мимо-попыток валидировать
        # нечего). Согласие/мусор → вердикт стоит; disagree проходит
        # ТОЛЬКО через серверный guard (tf.apply_validator). Отказ/невалидный
        # JSON → СУЩЕСТВУЮЩИЙ fallback-путь с существующим reason-кодом
        # (честная деградация, не тихая). Стадия реестра не меняется:
        # исход фиксируется дополнительной записью "verdict" в трассе.
        validator_outcome = None
        if evidence and raw_payload:
            v_payload = await self._temporal_verdict_json(
                tf.TEMPORAL_VALIDATOR_SYSTEM,
                self._temporal_validator_payload(env, verdict, evidence),
                env, correlation_id, step="temporal_validator")
            if v_payload is not None:
                verdict, corrected = tf.apply_validator(verdict, v_payload,
                                                        env)
                validator_outcome = "corrected" if corrected else "validated"
            else:
                validator_outcome = "failed"
                if not fallback_used:
                    # Существующий fallback-путь (общий слот ≤1 попытки):
                    # валидация не удалась → строгий повтор аналитика;
                    # обе мимо → честный degraded-вердикт.
                    # REV-P1 (§18G.3): allowlist обязателен и здесь —
                    # fallback-промпт может вернуть refs, они фильтруются
                    # тем же current-run allowlist (ev-N), что и у аналитика.
                    fallback_used = True
                    verdict_reason = "temporal_fallback_mode"
                    retry = await self._temporal_verdict_json(
                        tf._TEMPORAL_FALLBACK_SYSTEM, user_payload, env,
                        correlation_id, step="temporal_fallback")
                    verdict = tf.verdict_from_payload(
                        retry or {}, env, fallback_reason=verdict_reason,
                        allowed_refs=allowed_refs)

        trace.add("verdict", "success",
                  reason=verdict.reason or verdict_reason)
        if validator_outcome:
            trace.add("verdict", validator_outcome,
                      reason="temporal_fallback_mode"
                      if validator_outcome == "failed" else None)
        # D10/§18G.4: временная недостаточность (даты оригинала неизвестны И
        # даты публикаций evidence не разпознаны) → bounded uncertainty,
        # НЕ forced certainty (вердикт не повышается и не понижается).
        if evidence and env.date_source == "unknown" and not any(
                r.get("date_parse_status") == "parsed" for r in evidence):
            uncertainty = dict(verdict.uncertainty or {})
            uncertainty.setdefault(
                "dates_unresolved",
                "дата публикации оригинала не определена — временная оценка "
                "ограничена")
            verdict = dataclasses.replace(verdict, uncertainty=uncertainty)
        # P0-FACTCHECK (§3.5): части есть даже без разбора модели — из
        # СЕРВЕРНОЙ декомпозиции, с вердиктом не выше insufficient и
        # привязкой evidence к части (в durable evidence раньше было
        # claim_part=null у всех строк). Положительный вердикт части без
        # доказательства запрещён.
        #
        # F5 (review r1): синтезированные части не должны противоречить
        # положительному общему вердикту («Подтверждается» + все части
        # «данных недостаточно»). Поэтому синтез только для честного
        # insufficient_evidence; иначе разбора частей нет вовсе.
        if not verdict.parts and verdict.factual_verdict == \
                "insufficient_evidence":
            server_parts = _server_parts(env, evidence)
            if server_parts:
                verdict = dataclasses.replace(verdict, parts=server_parts)
        # P0-FACTCHECK (§3.6): технический класс пишется в оговорки, чтобы
        # пользователь и вербализатор не читали «сбой» как «фактов нет».
        caveat = _RETRIEVAL_CAVEAT.get(retrieval_state)
        if caveat:
            uncertainty = dict(verdict.uncertainty or {})
            uncertainty["retrieval_state"] = caveat
            verdict = dataclasses.replace(verdict, uncertainty=uncertainty)
        tf.stage_event("verdict", "success", reason_code=verdict.reason,
                       chat_id=env.chat_id)

        # verbalize (D11/CA-20-13): стилизация ПОСЛЕ вердикта; даты/
        # оговорки — обязательная часть payload каждой стадии; все ветки
        # (включая fallback) получают один envelope.
        verdict_text = await self._temporal_verbalize(
            env, verdict, fallback_used, correlation_id,
            retrieval_state=retrieval_state)
        trace.add("verbalize", "success" if verdict_text else "skipped",
                  reason=None if verdict_text else "temporal_fallback_mode")

        if not verdict_text:
            verdict_text = self._temporal_fallback_text(
                env, verdict, retrieval_state=retrieval_state)

        return tf.TemporalRunResult(
            envelope=env, verdict=verdict, verdict_text=verdict_text,
            evidence_rows=evidence, stage_trace=trace.as_list(),
            fallback_used=fallback_used, cache_hit=False)

    def _temporal_user_payload(
        self, env: tf.TemporalClaimEnvelope, parts, evidence,
        chat_context: str | None, analysis_context: str = "",
    ) -> str:
        """User-content вердиктной стадии: <claim> + <temporal_context>
        (даты/периоды/режим — серверные метаданные, D2) + <evidence> +
        <chat_context> (НЕ доказательства — подпись как в legacy).
        P0-FACTCHECK-CORRECTIVE (§2.4): при пустом evidence добавляется
        <analysis_context> — статус поиска и рамка самостоятельной
        проверки (серверный текст, не доказательства)."""
        sections = [
            "<claim>" + escape_xml_text(env.claim_text) + "</claim>",
            "<temporal_context>" + escape_xml_text(json.dumps({
                "date_source": env.date_source,
                "original_published_at": env.original_published_at,
                "repost_received_at": env.repost_received_at,
                "claim_period": [env.claim_period_from,
                                 env.claim_period_to,
                                 env.claim_period_precision],
                "date_uncertainty": env.date_uncertainty,
                "assessment_mode": env.requested_mode,
                "analysis_as_of": env.analysis_as_of,
            }, ensure_ascii=False)) + "</temporal_context>",
        ]
        if parts:
            sections.append("<claim_parts>" + escape_xml_text(json.dumps(
                [{"part_id": p.part_id, "text": p.text,
                  "period": [p.period_from, p.period_to]}
                 for p in parts], ensure_ascii=False)) + "</claim_parts>")
        if evidence:
            # §18G.3/§18G.5: каждая выдержка — со стабильным ID и датой
            # публикации (unknown — честно); model evidence_refs ссылаются
            # только на эти ID (allowlist проверяется сервером).
            sections.append("<evidence>" + escape_xml_text("\n\n".join(
                "[%s] published: %s%s\n%s" % (
                    r.get("evidence_id") or "?",
                    _fmt_evidence_date(r.get("published_at")),
                    (" (%s)" % r["published_at_source"])
                    if r.get("published_at_source") else "",
                    r["support"])
                for r in evidence)) + "</evidence>")
        if analysis_context:
            sections.append(analysis_context)
        if chat_context:
            sections.append(chat_context)
        return "\n\n".join(sections)

    def _temporal_validator_payload(
        self, env: tf.TemporalClaimEnvelope, verdict: tf.TemporalVerdict,
        evidence,
    ) -> str:
        """User-content validator-стадии (D11/TH-2, data-only): утверждение +
        серверный контекст + черновой вердикт + выдержки. Untrusted-evidence
        остаётся ДАННЫМИ: экранирование то же, что у аналитика, контейнер
        <search_results> не разрывается содержимым сниппетов."""
        sections = [
            "<claim>" + escape_xml_text(env.claim_text) + "</claim>",
            "<temporal_context>" + escape_xml_text(json.dumps({
                "date_source": env.date_source,
                "original_published_at": env.original_published_at,
                "claim_period": [env.claim_period_from,
                                 env.claim_period_to,
                                 env.claim_period_precision],
                "assessment_mode": env.requested_mode,
            }, ensure_ascii=False)) + "</temporal_context>",
            "<verdict_draft>" + escape_xml_text(json.dumps({
                "factual_verdict": verdict.factual_verdict,
                "temporal_status": verdict.temporal_status,
                "evaluated_period": verdict.evaluated_period,
                "assessment_mode": verdict.assessment_mode,
            }, ensure_ascii=False)) + "</verdict_draft>",
            "<evidence>" + escape_xml_text("\n\n".join(
                "[%s] published: %s\n%s" % (
                    r.get("evidence_id") or "?",
                    _fmt_evidence_date(r.get("published_at")),
                    r["support"])
                for r in evidence)) + "</evidence>",
        ]
        return "\n\n".join(sections)

    async def _temporal_verdict_json(
        self, system: str, user_payload: str, env,
        correlation_id: str | None, *, step: str,
    ) -> dict | None:
        """Один data-only LLM-вызов вердиктной стадии → dict|None."""
        from services.system2_handoff import parse_json_object
        try:
            raw = await self.llm.generate(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user_payload}],
                module="factcheck", step=step,
                correlation_id=correlation_id)
        except Exception:
            return None
        payload = parse_json_object(str(raw))
        return payload if isinstance(payload, dict) else None

    async def _temporal_verbalize(
        self, env: tf.TemporalClaimEnvelope, verdict: tf.TemporalVerdict,
        fallback_used: bool, correlation_id: str | None,
        *, retrieval_state: str | None = None,
    ) -> str:
        """Вербализатор (REUSE существующего контракта фактчека): verdict →
        текст с СОХРАНЕНИЕМ существенных дат/оговорок (SC-R3c). Любой сбой
        → '' (вызывающий берёт детерминированный fallback-текст)."""
        max_symbols = hot.get("limits.factcheck_max_symbols",
                              settings.FACTCHECK_MAX_SYMBOLS)
        try:
            from services.factcheck_prompts import (
                FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
            )
            base = resolve_prompt(
                "prompts.factcheck_verbalizer_system_prompt",
                FACTCHECK_VERBALIZER_SYSTEM_PROMPT).replace(
                "{max_symbols}", str(max_symbols))
        except Exception:
            base = ("Перескажи проверку фактов кратко и по-человечески. "
                    "СОХРАНИ существенные даты и оговорки; не выдумывай "
                    "дат и фактов; недостаток данных честно называй.")
        # CFG-06 W5 (06A.5/06B, утечка «период проверки (unknown)»):
        # style_note с техполями удалён; вербализатор получает
        # человекочитаемый дайджест вердикта, сырые служебные поля
        # (enum-статусы, precision, as_of, тех-ключи uncertainty) — мимо
        # payload («unknown» → человеческие слова). Раскладка остального
        # текста (обёртка сообщений, порядок человекочитаемых ключей,
        # fallback_note) сохранена — байт-защита тестом W5.
        payload = {
            "verdict": _human_factual_verdict(verdict.factual_verdict),
            "freshness": _human_temporal_status(verdict.temporal_status),
        }
        period_phrase = _human_evaluated_period(verdict.evaluated_period)
        if period_phrase:
            payload["period"] = period_phrase
        caveats = [str(v).strip()
                   for v in (verdict.uncertainty or {}).values()
                   if str(v or "").strip()]
        if caveats:
            payload["caveats"] = caveats
        payload["parts"] = list(verdict.parts)
        payload["claim"] = env.claim_text
        situation = _RETRIEVAL_SITUATION.get(str(retrieval_state or ""))
        if situation:
            # §3.6: вербализатор не должен называть сбой «отсутствием фактов».
            payload["situation"] = situation
        if fallback_used:
            payload["fallback_note"] = (
                "структурированный анализ не удался — не утверждай больше, "
                "чем следует из данных")
        # §7.2: анализ без содержания ≠ поиск без результатов. Только когда
        # содержательного анализа НЕТ — короткая честная граница вместо
        # абзацев-компенсаций. Универсального правила длины НЕ вводится:
        # содержательный ответ передаётся как есть (§7.1).
        if not _verdict_is_substantive(verdict):
            payload["limit_note"] = (
                "содержательного разбора не получилось — коротко назови "
                "фактическое ограничение и какой информации не хватает, "
                "без абзацев ради объёма и без историй про сломанные "
                "инструменты")
        # UNIFIED-CORE (P0, владелец 20.10.2026): временной вербализатор —
        # пользовательская речь → тот же штатный шов, что Stage-2/одиночный
        # путь: Core + Expression владельца ПОСЛЕДНИМ блоком system (характер
        # по настройкам владельца; блок пуст → сборка байт-в-байт прежняя).
        # EVOL §5 (W5): тот же раздел «Критический разнос» и тот же слой
        # стиля, что на остальных публичных путях (политика — по проверенному
        # вердикту: supported/insufficient/техсбой → раздела нет).
        _chat = getattr(env, "chat_id", None)
        critique_block = await _critique_section_block(
            _chat, critique_policy_for_verdict(
                factual_verdict=verdict.factual_verdict,
                parts=tuple(verdict.parts or ()),
                reason_code=verdict.reason,
                fallback_used=bool(fallback_used),
                has_evidence=bool(verdict.parts or ())))
        base = _with_critique_block(base, critique_block)
        owner_block = await speech_owner_block(_chat)
        system = f"{base}\n\n{owner_block}" if owner_block else base
        style_hint = await _speech_style_hint(_chat)
        if style_hint:
            system = f"{system}\n\n{style_hint}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "ВЕРДИКТ (JSON):\n" + json.dumps(
                payload, ensure_ascii=False)},
        ]

        async def _generate(msgs):
            return await self.llm.generate(
                msgs, module="factcheck", step="temporal_verbalize",
                correlation_id=correlation_id)

        try:
            text, _stats = await verbalize_validated(
                _generate, messages, max_retries=1,
                dynamic_rules=anticliche_cache.get_rules() or None,
                metatext_reason=_metatext_retry_reason())
        except Exception:
            return ""
        try:
            out = cleanup_llm_text(strip_reasoning_tags(str(text)))
        except Exception:
            return ""
        return out.strip()

    @staticmethod
    def _temporal_fallback_text(env: tf.TemporalClaimEnvelope,
                                verdict: tf.TemporalVerdict,
                                *, retrieval_state: str | None = None) -> str:
        """Детерминированный честный текст (все ветки получают даты, D11):
        краткая дата/неопределённость без технической схемы (D15).

        P0-FACTCHECK (§3.6): технический сбой не маскируется под «мало
        данных» — фраза прямо называет причину (бюджет/недоступность/
        непригодные выдержки)."""
        import datetime as _dt

        def _fmt(ts):
            if not ts:
                return None
            try:
                return _dt.datetime.fromtimestamp(
                    int(ts), _dt.timezone.utc).strftime("%d.%m.%Y")
            except (ValueError, OverflowError, OSError):
                return None

        openers = {
            RETRIEVAL_BUDGET:
                "Проверку не удалось довести до конца: истёк лимит времени "
                "на поиск. Это не значит, что утверждение опровергнуто.",
            RETRIEVAL_SEARCH_FAILED:
                "Проверку не удалось выполнить: поисковые сервисы не "
                "ответили. Это технический сбой, а не отсутствие фактов.",
            RETRIEVAL_PROCESSING_FAILED:
                "Материалы найти удалось, но пригодных для проверки "
                "выдержек из них получить не вышло.",
            RETRIEVAL_NO_RESULTS:
                "Поиск ответил, но подходящих материалов не дал — поэтому "
                "вывод сделан без внешних источников.",
        }
        if _verdict_is_substantive(verdict):
            # §7: содержательный разбор не подменяется сообщением о сбое —
            # даже при отказе вербализатора разбор частей сохраняется.
            opener = ("Внешний поиск не удался, поэтому разбор сделан без "
                      "веб-источников."
                      if str(retrieval_state or "") in (
                          RETRIEVAL_BUDGET, RETRIEVAL_SEARCH_FAILED,
                          RETRIEVAL_PROCESSING_FAILED, RETRIEVAL_NO_RESULTS)
                      else "Недостаточно данных для полной проверки "
                           "утверждения.")
            pieces = [opener]
            for part in (verdict.parts or ())[:4]:
                if not isinstance(part, dict):
                    continue
                text = " ".join(str(part.get("text") or "").split())
                if not text:
                    continue
                label = {"supported": "подтверждается",
                         "refuted": "не подтверждается",
                         "mixed": "подтверждается частично",
                         "insufficient_evidence": "данных недостаточно"}.get(
                    str(part.get("factual_verdict") or ""), "")
                pieces.append(f"• {text}"
                              + (f" — {label}" if label else ""))
        else:
            pieces = [openers.get(str(retrieval_state or ""),
                                  "Недостаточно данных для полной проверки "
                                  "утверждения.")]
        orig = _fmt(env.original_published_at)
        if env.date_source in ("telegram_origin", "telegram_message") and orig:
            kind = "оригинала" if env.date_source == "telegram_origin" \
                else "сообщения"
            pieces.append(f"Дата {kind}: {orig}.")
        period = verdict.evaluated_period or {}
        p_from, p_to = _fmt(period.get("from")), _fmt(period.get("to"))
        if p_from and p_to and p_from != p_to:
            pieces.append(f"Проверялось на период {p_from}—{p_to}.")
        elif p_from:
            pieces.append(f"Проверялось на период {p_from}.")
        if verdict.temporal_status == "old_but_valid":
            pieces.append("Возраст публикации сам по себе не делает "
                          "утверждение ложным.")
        return " ".join(pieces)
