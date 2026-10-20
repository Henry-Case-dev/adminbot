"""SOUL-1 / W6 — «Речь и характер»: API-клей MiniApp (слайс SOUL-AMD.6.x/8.3).

Единственный владелец UI-контракта «Речи и характера». Никакой второй
архитектуры не вводится:

* речевые блоки читаются/пишутся ЕДИНСТВЕННЫМ путём реестра —
  ``services.prompt_factory.write_speech_value`` / ``apply_factory_reset`` /
  ``reset_chat_override`` (SOUL-AMD.1.1/4.1; иначе правка владельца будет
  удержана резолвером, см. W1 §«BLOCKER-1»);
* правила формы — ``services.style_policy`` (документ ``style.policy``,
  SOUL-16), как глобально, так и per-chat;
* состояния реестра — ``services.prompt_registry`` (``registry_view``,
  ``effective_prompt``, ``core_selection_view``, ``style_policy_view``);
* манифест/слои — ``services.prompt_composer`` (Inspector, «Попробовать»);
* способности чата — ``services.capability_registry.capability_view``
  (SOUL-AMD.6.5) + существующая телеметрия ``services.mca_events``;
* «Обучение» — существующие уроки Experience (``mca_experience``) и их
  применения; humor-feedback контур (SOUL-08) — слайс W4.

RBAC — существующие права: ``edit_persona`` / секция ``content`` для чата и
``param.<category>.<key>`` для глобального ключа (design-source-of-truth §3.3);
Inspector — только уполномоченные администраторы (SOUL-AMD.6.4).

R17: наружу не уходят значения ключей/секреты; тела промптов отдаются только
прошедшим RBAC-проверку и маскируются (``redact_secrets`` + длинные числовые
ID), TTL хранения манифеста — in-memory bounded кэш композера.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aiogram.utils.web_app import WebAppUser

from services import prompt_registry as pr
from services import mca_expression as expression
from services import mca_humor_craft as humor_craft
from services import mca_humor_feedback as humor_feedback
from services import mca_sample_library as samples_lib

from web.api.deps import can_edit_param, get_cache, get_tma_user
from web.api.routes import (
    _chat_id_or_none,
    _persona_access,
    _persona_can_edit,
    _persona_can_view,
)

logger = logging.getLogger(__name__)

speech_router = APIRouter()

#: Документ owner-контролов «Выражение» (SOUL-10.3). Один ключ = один
#: JSON-документ на scope (R1/R3 design-source-of-truth): глобально —
#: ``bot_settings``, per-chat — ``chat_params.overrides``. Новый ключ НЕ
#: добавляется в каталог: каталог — витрина параметров (Δ каталога = 0,
#: прецедент W3 ``evidence/w3/catalog-delta-decision.txt``), а единственным
#: путём правки речи остаётся реестр/документы сущностей.
#: ADD-EXP: логика — единственный владелец ``services.mca_expression``
#: (значения/нормализация/резолв/рендер); здесь — UI-контракт и ре-экспорт.
EXPRESSION_DOC_KEY = expression.EXPRESSION_DOC_KEY
EXPRESSION_DOC_CATEGORY = "content"
EXPRESSION_REVISION_MAX = 12

#: Категория документа Personality Core (design-source-of-truth §2.1:
#: `content`, per-chat наследуется).
CORE_DOC_CATEGORY = "content"

#: Блок-база канала Direct для предпросмотра/Inspector (L2 Writer).
BASE_BLOCK_PG_KEY = "prompts.direct_chat_verbalizer_system_prompt"

#: Закрытый набор человеческих контролов (SOUL-10.3: «ограниченная настройка
#: привычек, а не числовые promise-индикаторы»). Никаких частот/процентов.
#: ADD-EXP §1.1/§2.2/§5.1.2: у `profanity` — явные режимы фактического
#: речевого поведения; `instruction` — канонические строки слоя
#: (единственный владелец текста — ``services.mca_expression``).
EXPRESSION_CONTROLS: tuple[dict, ...] = (
    {
        "id": "wit",
        "label": "Остроумие",
        "question": "Насколько охотно искать шутку и неожиданное сравнение",
        "options": [
            {"value": "inherit", "label": "Как настроено (по умолчанию)"},
            {"value": "low", "label": "Реже обычного"},
            {"value": "normal", "label": "Обычно"},
            {"value": "high", "label": "Чаще искать повод"},
        ],
        "effect": {
            "low": "Поводы для шутки почти не ищутся: по делу, без насилия "
                   "над темой.",
            "normal": "Обычная манера: шутка появляется, когда она уместна.",
            "high": "Повод ищется охотнее (сравнение, абсурдная деталь), но "
                    "уместность всё равно решает L1.",
        },
    },
    {
        "id": "sharpness",
        "label": "Резкость",
        "question": "Насколько жёстко можно спорить и подкалывать",
        "options": [
            {"value": "inherit", "label": "Как настроено (по умолчанию)"},
            {"value": "soft", "label": "Мягче обычного"},
            {"value": "normal", "label": "Обычно"},
            {"value": "sharp", "label": "Жёстче обычного"},
        ],
        "effect": {
            "soft": "Подколка остаётся, но мягче; спор — по существу.",
            "normal": "Обычная язвительность ядра без перехода в травлю.",
            "sharp": "Резче и прямее; оскорбления и травля не появляются — "
                     "жёсткость формулировки, а не агрессия к человеку.",
        },
    },
    {
        "id": "profanity",
        "label": "Мат",
        "question": "Как часто мат звучит в собственных ответах бота",
        "options": [
            {"value": "inherit",
             "label": "Как в глобальных настройках (наследование)"},
            {"value": "off", "label": "Без мата"},
            {"value": "occasional", "label": "Эпизодически"},
            {"value": "frequent", "label": "Часто"},
        ],
        "effect": {
            "off": "Свои формулировки — без мата. Цитаты и чужой текст "
                   "передаются как есть.",
            "occasional": "Мат иногда, в обычной разговорной речи: без "
                          "особого повода, но и не постоянно.",
            "frequent": "Мат свободно и регулярно: привычная часть "
                        "повседневной речи, в большинстве неформальных "
                        "реплик, без насильных вставок.",
        },
    },
    {
        "id": "verbosity",
        "label": "Развёрнутость",
        "question": "Обычная длина ответа, когда пользователь не задал формат",
        "options": [
            {"value": "inherit", "label": "Как настроено (по умолчанию)"},
            {"value": "short", "label": "Короче обычного"},
            {"value": "normal", "label": "Обычно"},
            {"value": "long", "label": "Подробнее обычного"},
        ],
        "effect": {
            "short": "Короче по умолчанию; прямая просьба «подробнее» "
                     "по-прежнему важнее.",
            "normal": "Обычная длина (её всё равно выбирает L1 по задаче).",
            "long": "Подробнее по умолчанию; «короче» пользователя важнее.",
        },
    },
)

#: ADD-EXP §2.1/§5.1.2: строки слоя (`- <label>: <instruction>`) — из
#: единственного владельца текста; дрейф ловится тестом.
for _control in EXPRESSION_CONTROLS:
    _control["instruction"] = dict(
        expression.CONTROL_INSTRUCTIONS.get(_control["id"]) or {})

EXPRESSION_VALUES: dict[str, tuple[str, ...]] = dict(
    expression.EXPRESSION_CONTROL_VALUES)

#: ADD-EXP §2.2: честные примечания раздела (интенсивность, а не «мягкая
#: привычка»; проверка результата — «Проверить вживую»).
EXPRESSION_NOTES: str = (
    "Настройки задают интенсивность и форму собственной речи; частоту "
    "определяет выбранный режим. Цитаты и чужой текст передаются как есть; "
    "сводки звучат тем же голосом персонажа; просьба «без мата» уважается "
    "всегда. Реальную частоту можно проверить в «Проверить вживую»."
)

#: Заводские примеры для before/after «Стиля письма» (SOUL-16.2.1/2.2 + 16.3.x).
STYLE_EXAMPLES: tuple[dict, ...] = (
    {"id": "quotes_hard", "label": "Кавычки (обычная речь)",
     "text": "Ну это «гениальная» идея, я считаю",
     "expects": "Кавычки-ирония вокруг одного слова"},
    {"id": "quotes_verbatim", "label": "Дословная цитата (защищено)",
     "text": "Он сказал «я не отдам ни рубля» и вышел",
     "expects": "Многословная цитата не режется вслепую (conflict/exempted)"},
    {"id": "trailing_period", "label": "Точка в конце",
     "text": "Ну да, логично.",
     "expects": "Снятие одной завершающей точки, без пробелов/слэшей"},
    {"id": "trailing_protected", "label": "Точка и путь/версия (защищено)",
     "text": "Смотри https://example.org/other. и версия 1.2.3.",
     "expects": "URL и версия не тронуты, снимается только точка фразы"},
    {"id": "emoji", "label": "Эмодзи",
     "text": "Отличная новость 😀😀, поздравляю",
     "expects": "Правило эмодзи применяется вне защищённых спанов"},
    {"id": "machine_json", "label": "Машинные данные",
     "text": "Данные: {\"note\": \"ok\"} — вот.",
     "expects": "JSON байт-в-байт, exempted вместо ложного «pass»"},
)

#: Закрытый набор техник юмора (SOUL-06/W4) для фильтра раздела «Юмор».
HUMOR_TECHNIQUES: tuple[dict, ...] = (
    {"id": "absurd_escalation", "title": "Абсурдная эскалация",
     "description": "Принять предпосылку как правило вымышленного мира и "
                    "довести её до логического края."},
    {"id": "literalism", "title": "Буквализм",
     "description": "Понять метафору буквально и обнаружить комическое "
                    "следствие."},
    {"id": "deadpan", "title": "Сухой deadpan",
     "description": "Спокойно утверждать нелепое как обыденный факт."},
    {"id": "bureaucratic_logic", "title": "Бюрократический/экономический перенос",
     "description": "Трактовать быт как процесс с регламентом и сметой."},
    {"id": "unexpected_analogy", "title": "Неожиданная, но содержательная аналогия",
     "description": "Смешать отдалённые области так, чтобы аналогия "
                    "объясняла исходную ситуацию."},
    {"id": "other", "title": "Другое", "description": "Прочие приёмы библиотеки."},
)

#: ADD-EXP (BLOCK-1) §3.3: набор регистра речи — СВОЯ техника библиотеки
#: (не юмор). В перечне раздела «Примеры» она нужна владельцу, чтобы видеть,
#: фильтровать и утверждать эти карточки существующим механизмом; ось юмора
#: (`HUMOR_TECHNIQUES`, humor-фильтр/приём) НЕ расширяется.
EXPRESSION_REGISTER_TECHNIQUE: dict = {
    "id": "expression_register",
    "title": "Регистр речи (мат: без / эпизодически / часто)",
    "description": "Короткие разговорные примеры одного режима мата — "
                   "заводские черновики; в runtime идут только утверждённые "
                   "владельцем.",
}

#: Перечень техник для раздела «Примеры»: приёмы юмора + регистр речи.
SAMPLE_TECHNIQUES_UI: tuple[dict, ...] = (
    HUMOR_TECHNIQUES + (EXPRESSION_REGISTER_TECHNIQUE,))

#: Поля сущности Sample Library (design-source-of-truth §2.3) — контракт W4.
#: Раздел «Примеры» рендерит карточки ровно по этой схеме; пока W4 не поставлен
#: (нет таблицы/CRUD), данные не выдумываются: API честно отдаёт
#: ``status="not_implemented_w4"`` и пустой список.
SAMPLE_ENTITY_FIELDS: tuple[dict, ...] = (
    {"id": "input_text", "label": "Вход", "type": "text", "required": True},
    {"id": "reply_text", "label": "Ответ бота", "type": "text", "required": True},
    {"id": "technique", "label": "Приём", "type": "enum",
     "values": [t["id"] for t in SAMPLE_TECHNIQUES_UI]},
    {"id": "context_note", "label": "Контекст", "type": "text"},
    {"id": "language", "label": "Язык", "type": "text", "default": "ru"},
    {"id": "tags", "label": "Теги", "type": "tags"},
    {"id": "rudeness_level", "label": "Резкость (0–3)", "type": "int"},
    {"id": "source_kind", "label": "Источник", "type": "enum",
     "values": ["owner_manual", "bot_suggested", "verified_success"]},
    {"id": "scope", "label": "Область", "type": "enum",
     "values": ["global", "chat"]},
    {"id": "owner_approved", "label": "Согласовано владельцем", "type": "bool"},
    {"id": "status", "label": "Статус", "type": "enum",
     "values": ["active", "archived"]},
)

_LONG_ID_RE = re.compile(r"\b\d{6,}\b")
_TELEGRAM_LINK_RE = re.compile(r"tg://[^\s\"']+")


def _mask_text(text: Any) -> str:
    """Маскировка приватного в отдаваемом тексте (R17/§6.4).

    Секреты — существующим каноническим маскером логов
    (``llm_client._mask_secrets``: Bearer/Basic, пары ``key=value`` и
    ``"key": "value"``, префикс-ключи) + ``redact_secrets`` как второй слой;
    длинные числовые ID (telegram user/chat/message) и tg-ссылки — локально.
    Никогда не бросает.
    """
    raw = str(text or "")
    try:
        from services.llm_client import _mask_secrets as _canonical_mask
        raw = _canonical_mask(raw)
    except Exception:       # pragma: no cover — защитная ветка
        pass
    try:
        from services.system2_handoff import redact_secrets
        raw = redact_secrets(raw)
    except Exception:       # pragma: no cover — защитная ветка
        pass
    raw = _TELEGRAM_LINK_RE.sub("[redacted-link]", raw)
    return _LONG_ID_RE.sub("[id]", raw)


# ═══════════════════════════════════════════════════════════════════════════
# P0 PERSIST-FIX (source-p0-hotfix-2026-10-18 §2, аудит §3): честный chat-путь
# ═══════════════════════════════════════════════════════════════════════════

#: Человеческая причина инфраструктурного сбоя записи (source §2.2: код
#: `write_error` в UI — не диагноз; 5xx = инфраструктура, 4xx = валидация).
WRITE_UNAVAILABLE_DETAIL = ("не удалось сохранить: постоянное хранилище "
                            "недоступно, попробуйте позже")
RESET_UNAVAILABLE_DETAIL = ("не удалось сбросить переопределение: постоянное "
                            "хранилище недоступно, попробуйте позже")

#: Человеческие причины сбоев управления обучением юмора (SOUL-08.11).
_LEARNING_ERROR_DETAILS = {
    "write_error": "не удалось сохранить: постоянное хранилище недоступно",
    "humor_feedback_disabled": ("контур обучения юмора выключен (ось "
                                "HUMOR_FEEDBACK_ENABLED)"),
    "lesson_contour_unavailable": "контур уроков опыта недоступен",
    "unknown_action": "неизвестное действие",
    "error": "операция с уроком не удалась — данные не изменены",
}


def _learning_error_detail(reason: str) -> str:
    return _LEARNING_ERROR_DETAILS.get(str(reason), str(reason) or "не выполнено")


def _doc_pg(cache):
    """PG-хендл для chat-записей — как в рабочих разделах MiniApp
    (`pg=cache.pg`, прецедент web/api/routes.py:706/:1013).

    None — честный случай «пула реально нет»: запись останется невыполненной
    с явной ошибкой (не тихий in-memory успех)."""
    return getattr(cache, "pg", None) if cache is not None else None


def _as_doc(raw) -> dict | None:
    """JSON-документ слоя: dict или JSON-строка (jsonb без зарегистрированного
    кодека). Прецедент ``style_policy._as_document`` (аудит §7, латентный C1):
    `_expression_document`/`_core_payload` принимали только dict."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw.decode("utf-8")
                                if isinstance(raw, (bytes, bytearray)) else raw)
        except Exception:
            return None
        return dict(parsed) if isinstance(parsed, Mapping) else None
    return None


def _chat_write_detail(exc: Exception) -> str:
    """Человеческая причина сбоя chat-записи (без кода `write_error`)."""
    if type(exc).__name__ == "ChatParamsConflict":
        return ("не удалось сохранить: профиль чата не найден или изменён — "
                "обновите экран и повторите")
    return WRITE_UNAVAILABLE_DETAIL


# ═══════════════════════════════════════════════════════════════════════════
# Доступ (существующие права; новых прав/чекбоксов не вводим)
# ═══════════════════════════════════════════════════════════════════════════

async def _access(request: Request, user: WebAppUser, x_chat_id: str | None):
    """(cache, chat_id, ctx) — существующий per-chat RBAC-путь персоны."""
    return await _persona_access(request, user, x_chat_id)


def _can_view(ctx, chat_id: int | None) -> bool:
    return _persona_can_view(ctx, is_global=chat_id is None, chat_id=chat_id)


def _can_edit_speech(cache, user: WebAppUser, ctx, *, pg_key: str,
                     chat_id: int | None) -> bool:
    """Право правки речевого значения: чат — существующий edit-путь,
    глобально — право на ключ (``param.<category>.<key>``, design §3.3)."""
    if getattr(ctx, "is_global_admin", False):
        return True
    if not _persona_can_edit(ctx, is_global=chat_id is None):
        # Глобальный ключ: у роли может быть право именно на ключ.
        if chat_id is None and pg_key:
            try:
                if can_edit_param(cache, user.id, pg_key):
                    return True
            except Exception:   # pragma: no cover — защитная ветка
                pass
        return False
    if chat_id is None and pg_key:
        try:
            if can_edit_param(cache, user.id, pg_key):
                return True
        except Exception:       # pragma: no cover
            pass
    return True


def _can_edit_inspector(ctx) -> bool:
    """Inspector — только уполномоченные администраторы (SOUL-AMD.6.4)."""
    if bool(getattr(ctx, "is_global_admin", False)):
        return True
    from web.api.routes import _persona_has_edit_action
    return bool(_persona_has_edit_action(ctx))


def _library_can_edit(cache, user: WebAppUser, ctx, *, chat_id: int | None
                      ) -> bool:
    """Право на правку ПРИМЕРОВ (SOUL-07.1/design §3.3, §5).

    Чат — существующий chat-level edit-путь; глобально — отдельное
    право-действие ``edit_humor_library`` либо существующее право правки
    речи (глобальный админ входит по умолчанию). Это серверная проверка:
    новых фронтенд-чекбоксов нет, право не выводится из одного тумблера.
    """
    if bool(getattr(ctx, "is_global_admin", False)):
        return True
    if chat_id is None:
        return (_has_humor_library_action(ctx)
                or _can_edit_speech(cache, user, ctx, pg_key="", chat_id=None))
    return bool(_persona_can_edit(ctx, is_global=False))


def _has_humor_library_action(ctx) -> bool:
    """Действие ``edit_humor_library`` у роли (fail-closed)."""
    try:
        from services.permissions import requires_permission as match_permission
        from services.permissions import Permissions
        perms = getattr(ctx, "effective_permissions", None)
        if perms is None:
            perms = Permissions.from_dict({})
        return bool(match_permission(perms, "edit_humor_library"))
    except Exception:                   # pragma: no cover — защитная ветка
        return False


async def _humor_craft_payload(cache, chat_id: int | None) -> dict:
    """Состояние ремесла: ось гейта + документ владельца (SOUL-06.7)."""
    cfg = await humor_craft.resolve_config(chat_id)
    return {
        "gate": bool(humor_craft.gate_on()),
        "enabled": bool(cfg.enabled),
        "source": str(cfg.source),
        "revision": int(cfg.revision),
        "disabled_techniques": list(cfg.disabled_techniques),
        "techniques": humor_craft.technique_catalog(cfg),
        "policy_version": humor_craft.HUMOR_CRAFT_POLICY_VERSION,
        "scenarios": humor_feedback.scenario_summary(),
        "note": ("Выключение ремесла — диагностическое: Personality Core, "
                 "стиль и примеры продолжают работать, ответы становятся "
                 "суше, а не «другим персонажем»."),
    }


async def _examples_counts(chat_id: int | None) -> dict:
    """Реальная статистика библиотеки (честные нули/причина недоступности)."""
    try:
        return await samples_lib.telemetry(samples_lib.get_db(),
                                           chat_id=chat_id)
    except Exception:
        logger.warning("[speech] samples telemetry failed", exc_info=True)
        return {"available": False, "reason": "read_error", "total": 0,
                "approved": 0, "proposed": 0}


async def _examples_card() -> dict:
    """Карточка «Примеры» хаба: состояние и деталь по факту (F3 REVIEW-W4).

    Ничего не приукрашивается: нет таблицы/базы → `off` и точная причина;
    есть → счётчики эталонов и черновиков (пустая библиотека — честный ноль).
    """
    counts = await _examples_counts(None)
    if not counts.get("available"):
        reason = str(counts.get("reason") or "unavailable")
        return {"state": "off", "ready": False,
                "detail": "библиотека недоступна: %s" % reason}
    total = int(counts.get("total") or 0)
    approved = int(counts.get("approved") or 0)
    proposed = int(counts.get("proposed") or 0)
    if not total:
        return {"state": "ready", "ready": True,
                "detail": "библиотека пуста: заведите подборку примеров"}
    return {"state": "ready", "ready": True,
            "detail": "карточек: %d · эталонов: %d · черновиков: %d"
                      % (total, approved, proposed)}


def _learning_card(gates: dict) -> dict:
    """Карточка «Обучение» хаба: уроки опыта + реакции на шутки по оси."""
    lessons_on = bool(gates.get("experience_lessons_enabled"))
    feedback_on = bool(gates.get("humor_feedback_enabled"))
    if not lessons_on:
        return {"state": "off",
                "detail": "контур опыта выключен — собирать нечего"}
    if feedback_on:
        return {"state": "ready",
                "detail": ("уроки опыта и реакции на шутки включены: "
                           "сигналы, гипотезы, влияние на следующий ответ")}
    return {"state": "ready",
            "detail": ("уроки опыта доступны; реакции на шутки выключены "
                       "(ось HUMOR_FEEDBACK_ENABLED)")}


async def _write_document(cache, chat_id: int | None, key: str, values: dict,
                          *, actor: Any = None) -> dict:
    """Запись JSON-документа сущности существующим контуром (SOUL-15).

    Глобально — ``ConfigCache`` (bot_settings, категория ``content``);
    per-chat — ``chat_params.overrides``. Второго config service нет;
    ``prompts.*`` не затрагиваются (правки речи идут путём реестра).
    """
    from services import chat_params
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id is None:
        if cache is None:
            return {"applied": False, "reason": "config_cache_unavailable"}
        try:
            current = _as_doc(cache.get(key, None))
        except Exception:
            current = None
        doc = dict(current) if isinstance(current, dict) else {}
        history = list(doc.get("history") or [])
        if doc:
            history.insert(0, {
                "revision": int(doc.get("revision", 1) or 1),
                "values_sha256_12": pr.sha12(json.dumps(
                    {k: v for k, v in doc.items()
                     if k not in ("history", "revision", "updated_at")},
                    sort_keys=True, ensure_ascii=False, default=str)),
                "updated_at": doc.get("updated_at") or ""})
        doc = {**{k: v for k, v in doc.items()
                  if k not in ("history", "revision", "updated_at")}, **values}
        doc["revision"] = int((current or {}).get("revision", 0) or 0) + 1
        doc["history"] = history[:EXPRESSION_REVISION_MAX]
        doc["updated_at"] = now
        doc["updated_by"] = actor
        try:
            await cache.set(key, doc, category=EXPRESSION_DOC_CATEGORY)
        except Exception:
            logger.warning("[speech] document write failed | key=%s", key,
                           exc_info=True)
            return {"applied": False, "reason": "write_error"}
        return {"applied": True, "revision": doc["revision"]}
    try:
        pg = _doc_pg(cache)
        root = await (chat_params.get_all_chat_params(int(chat_id), pg=pg)
                      if pg is not None
                      else chat_params.get_all_chat_params(int(chat_id)))
        overrides = dict((root or {}).get("overrides") or {})
        current = _as_doc(overrides.get(key))
        doc = dict(current) if isinstance(current, dict) else {}
        doc = {**{k: v for k, v in doc.items()
                  if k not in ("history", "revision", "updated_at")}, **values}
        doc["revision"] = int(((current or {}).get("revision") or 0)) + 1
        doc["updated_at"] = now
        doc["updated_by"] = actor
        overrides[key] = doc
        await chat_params.set_chat_params(int(chat_id),
                                         {"overrides": overrides}, pg=pg)
        return {"applied": True, "revision": doc["revision"],
                "chat_id": int(chat_id)}
    except Exception:
        logger.warning("[speech] chat document write failed | key=%s", key,
                       exc_info=True)
        return {"applied": False, "reason": "write_error"}


# ═══════════════════════════════════════════════════════════════════════════
# Чтение слоёв (реестр / документы)
# ═══════════════════════════════════════════════════════════════════════════

async def _chat_overrides(chat_id: int | None) -> dict:
    if chat_id is None:
        return {}
    try:
        from services import chat_params
        root = await chat_params.get_all_chat_params(int(chat_id))
        return dict((root or {}).get("overrides") or {})
    except Exception:
        logger.warning("[speech] chat overrides read failed", exc_info=True)
        return {}


def _effective_dict(eff) -> dict:
    """EffectivePrompt → сериализуемый вид (тексты + провенанс + диагностика)."""
    return {
        "block_id": eff.block_id,
        "pg_key": eff.pg_key,
        "text": eff.text,
        "source": eff.source,
        "scope_label": _scope_label(eff.source),
        "revision": eff.revision,
        "factory_revision": eff.factory_revision,
        "differs_from_factory": bool(eff.differs_from_factory),
        "stored_differs_from_factory": bool(eff.stored_differs_from_factory),
        "legacy_persona_present": bool(eff.legacy_persona_present),
        "legacy_stripped": bool(eff.legacy_stripped),
        "legacy_removed": int(eff.legacy_removed or 0),
        "withheld": bool(eff.withheld),
        "withheld_revision": eff.withheld_revision,
        "stored_source": eff.stored_source,
        "provenance_reason": eff.provenance_reason,
        "diagnostics": list(eff.diagnostics or ()),
        "chars": len(eff.text or ""),
    }


def _scope_label(source: str) -> str:
    """«Factory / Global Custom / Chat Override / Inherited» (SOUL-AMD.4.3)."""
    return {
        "chat": "Chat Override",
        "global": "Global Custom",
        "default": "Factory",
        "code": "Factory",
        "missing": "нет блока",
    }.get(str(source or ""), str(source or ""))


def _spec_meta(spec) -> dict:
    return {
        "block_id": spec.block_id,
        "purpose": spec.purpose,
        "family": spec.family,
        "scope": spec.scope,
        "pg_key": spec.pg_key or "",
        #: Редактируется ли блок из MiniApp (у блоков без PG-ключа нет пути
        #: записи — они видны, но кнопка сохранения честно выключена).
        "editable": bool(spec.pg_key),
        "pg_doc_field": spec.pg_doc_field,
        "consumers": list(spec.consumers or ()),
        "composition_point": spec.composition_point,
        "enabled_by": spec.enabled_by,
        #: Включённость блока по реальной оси, если ось в закрытом наборе
        #: SOUL-1 (иначе None — никакая «включённость» не выдумывается).
        "enabled_axis": _enabled_axis(spec.enabled_by),
        "enabled_value": _enabled_axis_value(spec.enabled_by),
        "owner_lane": spec.owner_lane,
        "speech": bool(spec.speech),
        "legacy_persona": bool(spec.legacy_persona),
        "provenance_required": bool(pr.withholding_required(spec)),
        "ui": spec.ui,
        "production_kind": pr.production_kind(spec.block_id),
        "factory_revision": pr.factory_revision(spec.block_id),
        "factory_chars": len(pr.factory_text(spec.block_id)),
    }


async def _blocks_rows(cache, chat_id: int | None) -> list[dict]:
    overrides = await _chat_overrides(chat_id)
    rows: list[dict] = []
    for spec in pr.all_blocks():
        row = _spec_meta(spec)
        pg_value = None
        chat_value = None
        if spec.pg_key and cache is not None:
            try:
                pg_value = cache.get(spec.pg_key, None)
            except Exception:
                pg_value = None
        if spec.pg_key:
            chat_value = overrides.get(spec.pg_key)
        eff = pr.effective_prompt(spec.block_id, pg_value=pg_value,
                                  chat_value=chat_value)
        row["effective"] = _effective_dict(eff)
        row["has_chat_override"] = chat_value is not None
        row["has_global_value"] = pg_value is not None
        row["editable"] = bool(spec.pg_key)
        rows.append(row)
    return rows


#: Оси SOUL-1 (env AND тумблер), которые видны в «Речи и характере».
_AXIS_BY_FLAG: dict[str, str] = {
    "unified_composer_enabled": "unified_composer_enabled",
    "character_core_enabled": "character_core_enabled",
    "speech_style_policy_enabled": "speech_style_policy_enabled",
    "humor_library_enabled": "humor_library_enabled",
    "humor_feedback_enabled": "humor_feedback_enabled",
    "persona_enabled": "persona_enabled",
    "experience_learning_enabled": "experience_lessons_enabled",
    # env-рубильники, которые реестр называет в `enabled_by`:
    "smart_verbalizer_modes_enabled": "smart_verbalizer_modes_enabled",
    "direct_response_plan_enabled": "response_plan_enabled",
    "character_layers_enabled": "character_layers_enabled",
    "mca_character_layers_enabled": "character_layers_enabled",
}


def _enabled_axis(enabled_by: Any) -> str:
    """Ось включённости блока: только из закрытого набора, иначе "" (нет данных)."""
    text = str(enabled_by or "")
    match = re.search(r"flags\.([a-z0-9_]+)", text)
    if not match:
        match = re.search(r"\b([A-Z][A-Z0-9_]{4,})\b", text)
        if match:
            key = match.group(1).lower()
            return _AXIS_BY_FLAG.get(key, "")
        return ""
    return _AXIS_BY_FLAG.get(match.group(1), "")


def _enabled_axis_value(enabled_by: Any) -> Any:
    """Разрешённое значение оси (None — ось не в закрытом наборе)."""
    axis = _enabled_axis(enabled_by)
    if not axis:
        return None
    gates = _gate_state()
    return bool(gates.get(axis)) if axis in gates else None


def _gate_state() -> dict:
    """Реальные оси (SOUL-15.6): что включено сейчас, без домыслов."""
    out: dict[str, bool] = {}
    try:
        from services import mca_gates
        out = {
            "unified_composer_enabled": bool(
                mca_gates.unified_composer_enabled()),
            "character_core_enabled": bool(mca_gates.character_core_enabled()),
            "speech_style_policy_enabled": bool(
                mca_gates.speech_style_policy_enabled()),
            "humor_library_enabled": bool(mca_gates.humor_library_enabled()),
            "humor_feedback_enabled": bool(mca_gates.humor_feedback_enabled()),
            "expression_examples_enabled": bool(
                mca_gates.expression_examples_enabled()),
            "experience_lessons_enabled": bool(
                mca_gates.experience_lessons_enabled()),
        }
        try:
            from config.settings import settings
            out["smart_verbalizer_modes_enabled"] = bool(getattr(
                settings, "SMART_VERBALIZER_MODES_ENABLED", True))
        except Exception:
            pass
        try:
            from services import response_extent
            out["response_plan_enabled"] = bool(
                response_extent.response_plan_enabled())
        except Exception:
            pass
        try:
            from services import hot_config as hot
            from config.settings import settings as _s
            out["persona_enabled"] = bool(hot.get(
                "flags.persona_enabled", getattr(_s, "PERSONA_ENABLED", True)))
        except Exception:
            pass
        try:
            out["character_layers_enabled"] = bool(
                mca_gates.character_layers_enabled())
        except Exception:
            pass
    except Exception:
        logger.warning("[speech] gates read failed", exc_info=True)
    return out


def _read_global_doc(cache, key: str):
    """Глобальный JSON-документ: из переданного ConfigCache, иначе hot.get.

    В продакшене это ОДИН и тот же кэш (`hot_config` читает тот же
    ConfigCache), поэтому чтение через запрос-кэш не создаёт второго источника
    истины и позволяет проверять слой без PG.
    """
    if cache is not None:
        try:
            return cache.get(key, None)
        except Exception:       # pragma: no cover — защитная ветка
            pass
    try:
        from services import hot_config as hot
        return hot.get(key, None)
    except Exception:           # pragma: no cover
        return None


async def _expression_document(cache, chat_id: int | None) -> dict:
    """Документы «Выражения» для scope + per-control effective (§1.2).

    Возврат: ``{document, global_present, chat_present, inheritance,
    effective, migration, global_document, chat_document}``. ``document`` —
    слой scope (chat override или global) для формы; ``effective`` — merge
    chat→global→factory по каждому контролу.
    """
    global_doc = _as_doc(_read_global_doc(cache, EXPRESSION_DOC_KEY))
    chat_doc = None
    if chat_id is not None:
        overrides = await _chat_overrides(chat_id)
        chat_doc = _as_doc(overrides.get(EXPRESSION_DOC_KEY))
    doc = chat_doc if isinstance(chat_doc, dict) else (
        global_doc if isinstance(global_doc, dict) else None)
    return {
        "document": dict(doc) if isinstance(doc, dict) else None,
        "global_document": dict(global_doc) if isinstance(global_doc, dict)
        else None,
        "chat_document": dict(chat_doc) if isinstance(chat_doc, dict) else None,
        "global_present": isinstance(global_doc, dict),
        "chat_present": isinstance(chat_doc, dict),
        "inheritance": ("chat" if isinstance(chat_doc, dict)
                        else "global" if isinstance(global_doc, dict)
                        else "factory_default"),
    }


def _normalize_expression(raw: Any) -> dict:
    """Валидация документа «Выражение» (единственный владелец — §1.6).

    Публичное имя сохраняется: ``allowed`` читается как ``occasional``
    (read-alias §1.3), неизвестное → ``inherit``.
    """
    return expression.normalize_expression(raw)


def render_expression_text(source: Any) -> str:
    """Рендер слоя `expression` (единственная реализация — §1.6).

    Принимает effective-резолв (§1.2) или сырой документ; preview и боевые
    сборки рендерят ОДИН текст (EXP-ACCEPT.PREVIEW).
    """
    return expression.render_expression_text(source)


async def _expression_payload(cache, chat_id: int | None) -> dict:
    """Payload раздела «Выражение» (§5.1.6).

    ``effective`` — per-control merge chat→global→factory со источником;
    ``migration`` — read-alias ``allowed``→``occasional`` до первого
    сохранения; в global scope наследование не предлагается (эффективное
    значение разрешено явно), в chat scope форма показывает слой чата.
    """
    layers = await _expression_document(cache, chat_id)
    doc = layers["document"]
    normalized = _normalize_expression(doc)
    global_doc = layers["global_document"]
    chat_doc = layers["chat_document"]
    effective = expression.resolve_effective(chat_doc, global_doc)
    migration = expression.expression_migration(chat_doc, global_doc)
    text = expression.render_expression_text(effective)
    scope = "chat" if chat_id is not None else "global"

    def _option_values(control: dict) -> list[dict]:
        options = list(control.get("options") or ())
        item = effective["controls"].get(control["id"]) or {}
        current = str(item.get("value") or "inherit")
        if scope == "global" and current != "inherit":
            # §5.1.6: в глобальном scope наследования нет — эффективное
            # значение разрешается явно. Если явного значения нет вовсе
            # (контролы без заводского дефолта), опция «как настроено»
            # остаётся честным описанием текущего состояния.
            options = [o for o in options
                       if str(o.get("value")) != "inherit"]
        return options

    def _form_values() -> dict:
        if scope == "global":
            # Явное эффективное значение: владелец не остаётся с
            # непроверяемым «как в характере».
            return {key: str((effective["controls"].get(key) or {}).get(
                "value") or "inherit") for key in EXPRESSION_VALUES}
        # chat scope: слой чата; нет документа → наследование.
        return {key: normalized.get(key) for key in EXPRESSION_VALUES}

    controls_out: list[dict] = []
    for control in EXPRESSION_CONTROLS:
        item = effective["controls"].get(control["id"]) or {}
        controls_out.append({
            **{k: v for k, v in control.items() if k != "effect"},
            "options": _option_values(control),
            "effect": (control.get("effect") or {}).get(
                str(item.get("value") or "inherit"), ""),
            "effective": str(item.get("value") or "inherit"),
            "effective_source": str(item.get("source") or "factory_default"),
        })
    return {
        "doc_key": EXPRESSION_DOC_KEY,
        "scope": scope,
        "chat_id": chat_id,
        "document": normalized,
        "present": isinstance(doc, dict),
        "global_present": layers["global_present"],
        "chat_present": layers["chat_present"],
        "inheritance": layers["inheritance"],
        "controls": controls_out,
        "values": _form_values(),
        "allows": {key: list(values)
                   for key, values in EXPRESSION_VALUES.items()},
        "effective": effective["controls"],
        "migration": migration,
        "note": normalized.get("note") or "",
        "notes": EXPRESSION_NOTES,
        "rendered_text": text,
        "rendered_chars": len(text),
        # ADD-EXP (wiring-слайс): слой подключён к боевым речевым путям
        # (Direct/Initiative/жанровые авторские тексты) — значение действует
        # со следующего ответа. Честная диагностика сохраняется.
        "runtime_wired": True,
        "runtime_note": ("Слой «Выражение» подключён к боевым речевым путям "
                         "(Direct/Initiative); значение действует со "
                         "следующего ответа."),
        "gates": _gate_state(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# «Характер» (Core): полная/компактная редакции, scope, версии, откат
# ═══════════════════════════════════════════════════════════════════════════

def _diff_summary(before: str, after: str) -> dict:
    """Компактный diff «до/после» без построчного шума (для UI-предпросмотра)."""
    b = str(before or "")
    a = str(after or "")
    prefix = 0
    for i, (x, y) in enumerate(zip(b, a)):
        if x != y:
            break
        prefix = i + 1
    suffix = 0
    while (suffix < (len(b) - prefix) and suffix < (len(a) - prefix)
           and b[len(b) - 1 - suffix] == a[len(a) - 1 - suffix]):
        suffix += 1
    changed_before = b[prefix:len(b) - suffix] if suffix else b[prefix:]
    changed_after = a[prefix:len(a) - suffix] if suffix else a[prefix:]
    return {
        "same": b == a,
        "before_chars": len(b),
        "after_chars": len(a),
        "delta_chars": len(a) - len(b),
        "changed": {
            "before": changed_before[:4000],
            "after": changed_after[:4000],
            "before_chars": len(changed_before),
            "after_chars": len(changed_after),
        },
        "truncated": (len(changed_before) > 4000
                      or len(changed_after) > 4000),
    }


async def _block_detail(cache, user: WebAppUser, ctx, chat_id: int | None,
                        block_id: str) -> dict:
    spec = pr.block(block_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="блок не найден")
    overrides = await _chat_overrides(chat_id)
    pg_value = None
    if spec.pg_key and cache is not None:
        try:
            pg_value = cache.get(spec.pg_key, None)
        except Exception:
            pg_value = None
    chat_value = overrides.get(spec.pg_key) if spec.pg_key else None
    eff = pr.effective_prompt(spec.block_id, pg_value=pg_value,
                              chat_value=chat_value)
    factory = pr.factory_text(spec.block_id)
    history: list[dict] = []
    try:
        from services import prompt_factory as pf
        history = await pf.history_for(spec.block_id, cache=cache)
    except Exception:
        logger.warning("[speech] history read failed", exc_info=True)
    plan: dict = {}
    try:
        from services import prompt_factory as pf
        plan = await pf.plan_factory_reset(spec.block_id, cache=cache)
    except Exception:
        logger.warning("[speech] factory plan failed", exc_info=True)
    gap = None
    if spec.pg_doc_field:
        # Для блока-поля документа Core: показать и вторую редакцию, чтобы
        # правка одной не выглядела как «весь Core».
        doc = chat_value if isinstance(chat_value, dict) else (
            pg_value if isinstance(pg_value, dict) else None)
        gap = {
            "document_field": spec.pg_doc_field,
            "other_field_present": bool(
                pr.doc_field_text(doc, "compact_text" if spec.pg_doc_field
                                  == "full_text" else "full_text").strip()),
            "detail_level": str((doc or {}).get("detail_level") or ""),
            "document_enabled": (doc or {}).get("enabled"),
        }
    return {
        **_spec_meta(spec),
        "effective": _effective_dict(eff),
        "factory_text": factory,
        "stored_text": (pr.doc_field_text(chat_value or pg_value,
                                          spec.pg_doc_field)
                        if spec.pg_doc_field else None),
        "chat_value_present": chat_value is not None,
        "global_value_present": pg_value is not None,
        "history": [
            {k: row.get(k) for k in
             ("revision", "kind", "scope", "sha256_12", "chars", "updated_at",
              "actor", "reason")}
            for row in history
        ],
        "history_text_available": bool(history),
        "factory_plan": plan,
        "preview_diff": _diff_summary(factory, eff.text or ""),
        "document": gap,
        "can_edit": _can_edit_speech(cache, user, ctx, pg_key=spec.pg_key or "",
                                     chat_id=chat_id),
    }


async def _core_payload(cache, user: WebAppUser, ctx, chat_id: int | None
                        ) -> dict:
    """Раздел «Характер»: обе редакции, режим scope, версии, история, откат."""
    overrides = await _chat_overrides(chat_id)
    pg_doc = None
    if cache is not None:
        try:
            pg_doc = _as_doc(cache.get(pr.CORE_DOC_KEY, None))
        except Exception:
            pg_doc = None
    chat_doc = _as_doc(overrides.get(pr.CORE_DOC_KEY))
    active_doc = chat_doc if isinstance(chat_doc, dict) else (
        pg_doc if isinstance(pg_doc, dict) else None)
    source = ("chat" if isinstance(chat_doc, dict)
              else "global" if isinstance(pg_doc, dict) else "default")
    selection = pr.core_selection_view(
        active_doc, source=source, budget_tokens=_composer_budget())
    factory_full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    factory_compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    full_eff = pr.effective_prompt(pr.CORE_FULL_BLOCK_ID, pg_value=pg_doc,
                                   chat_value=chat_doc)
    compact_eff = pr.effective_prompt(pr.CORE_COMPACT_BLOCK_ID, pg_value=pg_doc,
                                      chat_value=chat_doc)
    history: list[dict] = []
    try:
        from services import prompt_factory as pf
        history = (await pf.history_for(pr.CORE_FULL_BLOCK_ID, cache=cache)
                   + await pf.history_for(pr.CORE_COMPACT_BLOCK_ID,
                                          cache=cache))
    except Exception:
        logger.warning("[speech] core history failed", exc_info=True)
    history.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    inspection: dict = {}
    try:
        from services import prompt_composer as composer
        inspection = await composer.core_inspection(int(chat_id or 0))
    except Exception:
        logger.warning("[speech] core inspection failed", exc_info=True)
    return {
        "block_ids": {"full": pr.CORE_FULL_BLOCK_ID,
                      "compact": pr.CORE_COMPACT_BLOCK_ID},
        "doc_key": pr.CORE_DOC_KEY,
        "scope": "chat" if chat_id is not None else "global",
        "chat_id": chat_id,
        "inheritance": ("chat" if isinstance(chat_doc, dict)
                        else "global" if isinstance(pg_doc, dict)
                        else "factory_default"),
        "global_present": isinstance(pg_doc, dict),
        "chat_present": isinstance(chat_doc, dict),
        "permanent_note": ("Core — постоянный характер: он действует "
                           "постоянно, а не как разовая инструкция. Правки "
                           "можно менять и возвращать (версии/откат/"
                           "заводской сброс)."),
        "selection": selection,
        "factory": {"full_text": factory_full,
                    "compact_text": factory_compact,
                    "full_chars": len(factory_full),
                    "compact_chars": len(factory_compact),
                    "full_revision": pr.factory_revision(pr.CORE_FULL_BLOCK_ID),
                    "compact_revision": pr.factory_revision(
                        pr.CORE_COMPACT_BLOCK_ID)},
        "document": {
            "revision": (active_doc or {}).get("revision"),
            "enabled": bool((active_doc or {}).get("enabled", True)),
            "detail_level": str((active_doc or {}).get("detail_level")
                                or "compact"),
            "origin": (active_doc or {}).get("origin"),
            "updated_at": (active_doc or {}).get("updated_at"),
            "present": isinstance(active_doc, dict),
        },
        "editions": {
            "full": {
                "text": full_eff.text,
                "source": full_eff.source,
                "scope_label": _scope_label(full_eff.source),
                "revision": full_eff.revision,
                "factory_revision": full_eff.factory_revision,
                "differs_from_factory": bool(full_eff.differs_from_factory),
                "withheld": bool(full_eff.withheld),
                "diagnostics": list(full_eff.diagnostics or ()),
                "chars": len(full_eff.text or ""),
            },
            "compact": {
                "text": compact_eff.text,
                "source": compact_eff.source,
                "scope_label": _scope_label(compact_eff.source),
                "revision": compact_eff.revision,
                "factory_revision": compact_eff.factory_revision,
                "differs_from_factory": bool(compact_eff.differs_from_factory),
                "withheld": bool(compact_eff.withheld),
                "diagnostics": list(compact_eff.diagnostics or ()),
                "chars": len(compact_eff.text or ""),
            },
        },
        "diff": {
            "full": _diff_summary(factory_full, full_eff.text or ""),
            "compact": _diff_summary(factory_compact, compact_eff.text or ""),
        },
        "history": [
            {k: row.get(k) for k in
             ("revision", "kind", "scope", "sha256_12", "chars", "updated_at",
              "actor", "reason")}
            for row in history[:20]
        ],
        "inspection": inspection,
        "gates": _gate_state(),
        "can_edit": _can_edit_speech(cache, user, ctx,
                                     pg_key=pr.CORE_DOC_KEY,
                                     chat_id=chat_id),
    }


def _composer_budget() -> int:
    try:
        from services import mca_gates
        return int(mca_gates.composer_additive_budget_tokens())
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# «Стиль письма» (SOUL-16) — правила формы, hard/soft, preview, истории
# ═══════════════════════════════════════════════════════════════════════════

async def _style_documents(cache) -> tuple[Any, Any]:
    return _read_global_doc(cache, "style.policy"), None


async def _style_payload(cache, chat_id: int | None,
                         context: str = "regular") -> dict:
    global_doc, _ = await _style_documents(cache)
    overrides = await _chat_overrides(chat_id)
    chat_doc = overrides.get("style.policy")
    view = pr.style_policy_view(global_doc, chat_doc, context=context)
    # Состав шаблонов отдаёт СЕРВЕР (не UI): иначе кнопка «+ шаблон» правила
    # выдумывала бы локально. Источник — существующие preset_rules/preset_soft.
    try:
        from services import style_policy as sp
        view["preset_documents"] = {
            name: {"rules": sp.preset_rules(name),
                   "soft_instructions": sp.preset_soft(name)}
            for name in sp.PRESET_SPECS}
    except Exception:
        logger.warning("[speech] preset documents failed", exc_info=True)
        view["preset_documents"] = {}
    view["scope"] = "chat" if chat_id is not None else "global"
    view["chat_id"] = chat_id
    view["examples"] = [dict(item) for item in STYLE_EXAMPLES]
    view["gates"] = _gate_state()
    return view


async def _style_preview(candidate: Any, chat_id: int | None,
                         context: str = "regular", cache=None) -> dict:
    """Before/after на заводских примерах: текущая политика vs кандидат.

    Детерминированно (0 LLM): тот же ``apply_style_policy``, что и в рантайме,
    но БЕЗ записи в окно повторов (``record=False``) и без телеметрии.
    """
    from services import style_policy as sp
    global_doc, _ = await _style_documents(cache)
    overrides = await _chat_overrides(chat_id)
    chat_doc = overrides.get("style.policy")
    current = sp.effective_policy_sync(global_doc, chat_doc, context=context)
    cand_doc = candidate if isinstance(candidate, dict) or candidate is None \
        else None
    # Кандидат того же scope, что и правка: глобальный документ НЕ мёржится с
    # текущим (иначе удаление правила в кандидате было бы не видно), чат —
    # мёржится по контракту §16.1.4.
    cand = (sp.effective_policy_sync(global_doc, cand_doc, context=context)
            if chat_id is not None
            else sp.effective_policy_sync(cand_doc, None, context=context))
    rows: list[dict] = []
    for example in STYLE_EXAMPLES:
        text = str(example.get("text") or "")
        before = await sp.apply_style_policy(
            text, chat_id=0, policy=current, context=context,
            record=False, emit_events=False, stage="preview")
        after = await sp.apply_style_policy(
            text, chat_id=0, policy=cand, context=context,
            record=False, emit_events=False, stage="preview")
        rows.append({
            "id": example.get("id"),
            "label": example.get("label"),
            "expects": example.get("expects"),
            "before_text": before.text,
            "after_text": after.text,
            "changed": before.text != after.text,
            "before": before.as_dict(),
            "after": after.as_dict(),
        })
    return {
        "context": context,
        "candidate_present": cand_doc is not None,
        "candidate_revision": cand.revision,
        "current_revision": current.revision,
        "rows": rows,
    }


# ═══════════════════════════════════════════════════════════════════════════
# «Возможности бота» (SOUL-AMD.6.5) + trace
# ═══════════════════════════════════════════════════════════════════════════

async def _capabilities_payload(chat_id: int | None) -> dict:
    out: dict = {"chat_id": chat_id, "capabilities": [], "trace": [],
                 "trace_note": "", "summary": {}}
    try:
        from services import capability_registry as cr
        states = await cr.capability_view(chat_id)
        out["capabilities"] = states
        counts: dict[str, int] = {}
        for state in states:
            key = str(state.get("status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        out["summary"] = counts
        out["statuses"] = ["ready", "disabled", "not_configured",
                           "temporarily_unavailable", "quota_exhausted",
                           "unsupported", "unknown"]
    except Exception:
        logger.warning("[speech] capability view failed", exc_info=True)
        out["error"] = "capability_view_failed"
    # Trace: реальные события существующей телеметрии (intent → capability →
    # tool → check → call → result → delivery), включая
    # «доступное действие не было выбрано L1».
    try:
        from services import capability_registry as cr2
        from services import lore_runtime, mca_events
        db = lore_runtime.get_lore_db()
        if db is None:
            out["trace_note"] = "telemetry_db_unavailable"
        else:
            events = await mca_events.query_events(db, chat_id=chat_id,
                                                   limit=200)
            keep = {"capability_registry", "image_generation", "tool_router",
                    "direct_chat", "prompt_layers", "prompt_composer"}
            rows = []
            for ev in events:
                name = str(ev.get("event") or ev.get("event_name") or "")
                comp = str(ev.get("component") or "")
                reason = str(ev.get("reason_code") or "")
                if comp not in keep and name not in keep:
                    continue
                if name in ("capability_check", "capability_message"):
                    stage = "check" if name == "capability_check" else "message"
                elif reason == "available_action_not_chosen":
                    stage = "intent_not_chosen"
                else:
                    stage = "stage"
                rows.append({
                    "ts": ev.get("ts"),
                    "event": name,
                    "component": comp,
                    "stage": stage,
                    "outcome": ev.get("outcome"),
                    "status": ev.get("status"),
                    "reason_code": reason,
                    "entity_id": ev.get("entity_id"),
                    "trace_id": ev.get("trace_id"),
                    "level": ev.get("level"),
                })
                if len(rows) >= 60:
                    break
            out["trace"] = rows
            out["trace_note"] = ("события из существующей телеметрии "
                                 "(mca_events); «доступное действие не было "
                                 "выбрано» — reason_code "
                                 "available_action_not_chosen")
            out["trace_not_chosen"] = [row for row in rows
                                       if row.get("reason_code")
                                       == "available_action_not_chosen"]
        _ = cr2
    except Exception:
        logger.warning("[speech] capability trace failed", exc_info=True)
        out["trace_note"] = "trace_unavailable"
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Effective Prompt Inspector (SOUL-AMD.6.4)
# ═══════════════════════════════════════════════════════════════════════════

#: Writers, чьи манифесты — сборка РЕАЛЬНОГО хода (не предпросмотр UI).
REAL_TURN_WRITERS: tuple[str, ...] = (
    "l2_writer", "system2_stage2", "tool_phase", "initiative_writer",
)
#: Writer предпросмотра UI: его манифест НЕ является доказательством вызова.
PREVIEW_WRITER = "speech_ui_preview"


def _composer_manifest_store() -> list:
    """Манифесты композера в порядке вставки (старые → новые); [] при сбое.

    Чтение только-на-чтение in-memory кэша композера (``_manifests``) под его
    же локом: публичного перечисления манифестов композер не отдаёт, а
    ``services/**`` этому слайсу недоступен. Хранилище bounded
    (``MANIFEST_CACHE_MAX``), копия короткая; при любом сбое/переименовании
    внутренностей — честный пустой список (никаких выдуманных снимков).
    """
    from services import prompt_composer as composer
    store = getattr(composer, "_manifests", None)
    if store is None:
        return []
    lock = getattr(composer, "_manifest_lock", None)
    try:
        if lock is not None:
            with lock:
                return list(store.values())
        return list(store.values())
    except Exception:
        logger.warning("[speech] composer manifest scan failed", exc_info=True)
        return []


def _latest_real_turn_manifest(chat_key: int):
    """Самый свежий манифест РЕАЛЬНОГО хода для чата (SOUL-AMD.6.4).

    Рантайм пишет манифест с ``run_id=correlation_id`` (uuid хода,
    ``direct_chat_service._compose_speech_system``), поэтому поиск по ключу без
    run_id его не находит (review-w6 F1). Настоящий ход всегда добавляет НОВЫЙ
    ключ (новый uuid), значит последний по вставке манифест реального writer'а —
    последний ход; предпросмотр UI писателя не вытесняет и за доказательство
    вызова не выдаётся. Снимка нет → ``None`` (честное «только предпросмотр»).
    """
    from services import prompt_composer as composer
    chat_key = int(chat_key or 0)
    latest = None
    for manifest in _composer_manifest_store():
        if int(getattr(manifest, "chat_id", 0) or 0) != chat_key:
            continue
        if str(getattr(manifest, "writer", "") or "") not in REAL_TURN_WRITERS:
            continue
        latest = manifest
    if latest is not None:
        return latest
    # Совместимость с сидами/тестами без run_id (ключ ``(chat, "-", writer)``):
    # сам композер поддерживает такой манифест, поэтому он тоже честен как
    # «собранный payload хода», хотя рантайм всегда пишет uuid.
    for writer in REAL_TURN_WRITERS:
        candidate = composer.get_manifest(chat_key, writer=writer)
        if candidate is not None:
            return candidate
    return None


async def _inspector_payload(cache, user, ctx, chat_id: int | None) -> dict:
    """Предпросмотр vs фактически отправленный payload + провенанс слоёв.

    «Предпросмотр» — детерминированная сборка текущей конфигурации тем же
    композером (0 LLM, ничего не отправляет). «Фактически отправлено» — снимок
    манифеста последнего разрешённого хода (in-memory, bounded, TTL процесса);
    отсутствие снимка честно помечается ``last_run_present=false`` — собранный
    шаблон НЕ выдаётся за доказательство реального вызова.
    """
    from services import prompt_composer as composer
    chat_key = int(chat_id or 0)
    # Снимок «фактически отправлено» — ТОЛЬКО манифест реального хода
    # (writer'ы Direct/System2/Initiative), а не предпросмотр UI: собранный
    # шаблон нельзя выдавать за доказательство реального вызова (SOUL-AMD.6.4).
    # Рантайм пишет манифест с run_id=uuid хода → ищем самый свежий манифест
    # реального writer'а по чату, а не по ключу без run_id (review-w6 F1).
    manifest = _latest_real_turn_manifest(chat_key)
    sent_writer = str(getattr(manifest, "writer", "") or "") \
        if manifest is not None else ""
    preview_only = manifest is None and composer.get_manifest(
        chat_key, writer=PREVIEW_WRITER) is not None
    preview: dict = {}
    try:
        preview = await _preview_manifest(cache, chat_id,
                                          text="(предпросмотр без сообщения)")
    except Exception:
        logger.warning("[speech] inspector preview failed", exc_info=True)
    core: dict = {}
    try:
        # Тот же источник, что у витрины/предпросмотра: запрос-кэш + чат-слой.
        core_payload = await _core_payload(cache, user, ctx, chat_id)
        selection = core_payload.get("selection") or {}
        edition = (core_payload.get("editions") or {}).get(
            "full" if selection.get("level") == "full" else "compact", {})
        core = {
            "level": selection.get("level"),
            "reason": selection.get("reason"),
            "source": edition.get("source"),
            "scope_label": edition.get("scope_label"),
            "revision": selection.get("revision") or edition.get("revision"),
            "active_revision": edition.get("revision"),
            "chars": edition.get("chars"),
            "document_revision": (core_payload.get("document") or {}).get(
                "revision"),
            "factory_revisions": {
                "full": (core_payload.get("factory") or {}).get(
                    "full_revision"),
                "compact": (core_payload.get("factory") or {}).get(
                    "compact_revision"),
            },
        }
    except Exception:
        logger.warning("[speech] inspector core failed", exc_info=True)
    sent: dict = {}
    if manifest is not None:
        layers = composer.render_effective_layers(manifest)
        sent = {
            "manifest_id": manifest.manifest_id,
            "writer": manifest.writer,
            "profile": manifest.profile,
            "run_id": manifest.run_id,
            "chat_id": manifest.chat_id,
            "tokens_total": manifest.tokens_total,
            "versions": dict(manifest.versions or {}),
            "flags": dict(manifest.flags or {}),
            "layers": layers.get("layers", []),
            "layer_order": layers.get("layer_order", []),
            "order_matches_canonical": layers.get("order_matches_canonical"),
            "conflicts": layers.get("conflicts", []),
            "skipped_layers": layers.get("skipped_layers", []),
            "diff_vs_previous": layers.get("diff_vs_previous"),
            "system_masked": _mask_text(manifest.system),
            "user_parts_masked": [_mask_text(p) for p in
                                  (manifest.user_parts or ())],
            "system_chars": len(manifest.system or ""),
        }
    return {
        "chat_id": chat_id,
        "last_run_present": manifest is not None,
        "last_run_note": ("" if manifest is not None else
                          ("В памяти процесса есть только предпросмотр сборки "
                           "(его манифест не является доказательством реального "
                           "вызова). Снимок хода появится после настоящего "
                           "ответа бота." if preview_only else
                           "Снимка фактического хода в памяти нет: показан "
                           "только предпросмотр сборки (не доказательство "
                           "реального вызова).")),
        "sent": sent,
        "sent_note": (("снимок последнего хода для writer=%s из памяти "
                       "процесса композера: это собранный payload хода, а не "
                       "подтверждение доставки в Telegram" % sent_writer)
                      if manifest is not None else ""),
        "sent_writers": list(REAL_TURN_WRITERS),
        "preview": preview,
        "core": core,
        "masked": True,
        "retention": ("манифест живёт в in-memory bounded кэше композера "
                      "(процесс/ход); тексты маскируются (секреты, длинные ID)"),
        "gates": _gate_state(),
    }


async def _preview_manifest(cache, chat_id: int | None, *, text: str,
                            candidate: dict | None = None,
                            profile: str = "speech_plain") -> dict:
    """Сборка композером текущей конфигурации (и/или кандидата) — без LLM.

    Читает реальные значения: базу канала (из реестра), Core (документ),
    правила формы (``style.policy``), «Выражение» (owner-документ).
    """
    from services import prompt_composer as composer
    from services import style_policy as sp

    candidate = candidate if isinstance(candidate, dict) else {}
    overrides = await _chat_overrides(chat_id)
    chat_id_key = int(chat_id or 0)

    base_key = "prompts.direct_chat_verbalizer_system_prompt"
    base_raw = ""
    base_block = pr.by_pg_key(BASE_BLOCK_PG_KEY)
    if base_block is not None:
        base_pg = None
        if cache is not None:
            try:
                base_pg = cache.get(BASE_BLOCK_PG_KEY, None)
            except Exception:
                base_pg = None
        base_chat = overrides.get(BASE_BLOCK_PG_KEY)
        base_raw = str(pr.effective_prompt(
            base_block.block_id, pg_value=base_pg,
            chat_value=base_chat).text or "")
    if not base_raw and base_block is not None:
        base_raw = pr.factory_text(base_block.block_id)

    core_doc = overrides.get(pr.CORE_DOC_KEY)
    if not isinstance(core_doc, dict):
        raw_core = _read_global_doc(cache, pr.CORE_DOC_KEY)
        core_doc = raw_core if isinstance(raw_core, dict) else None
        core_source = "global"
    else:
        core_source = "chat"
    cand_core = candidate.get("core_document")
    if isinstance(cand_core, dict):
        core_doc = cand_core
        core_source = "global"
    # CoreRef собирается из ТОГО ЖЕ документа, что видит Inspector/витрина;
    # если документа нет — честный резолв композера (`core_absent`), а не
    # «пустой характер».
    core_ref = None
    if isinstance(core_doc, dict):
        core_ref = await _core_ref_from_doc(core_doc, source=core_source)
    if core_ref is None:
        core_ref = await composer.resolve_core_ref(chat_id_key)

    style_doc = overrides.get("style.policy")
    if not isinstance(style_doc, dict):
        style_doc = _read_global_doc(cache, "style.policy")
        style_doc = style_doc if isinstance(style_doc, dict) else None
    if isinstance(candidate.get("style_document"), dict):
        style_doc = candidate["style_document"]
    policy = sp.effective_policy_sync(None, style_doc, context="regular")
    hint = policy.hint or ""

    # ADD-EXP §1.6/§5.1.7: слой «Выражение» собирается ТЕМ ЖЕ builder-ом, что
    # бой (per-control merge chat→global→factory) — предпросмотр не врёт.
    expression_chat = overrides.get(EXPRESSION_DOC_KEY)
    expression_global = _read_global_doc(cache, EXPRESSION_DOC_KEY)
    if isinstance(candidate.get("expression_document"), dict):
        # Кандидат формы — «что если» документ того слоя, куда сохраняем.
        if chat_id is not None:
            expression_chat = candidate["expression_document"]
        else:
            expression_global = candidate["expression_document"]
    expression_settings = expression.build_expression_settings(
        expression_chat if isinstance(expression_chat, dict) else None,
        expression_global if isinstance(expression_global, dict) else None)

    gates = composer.gates_from_config()
    try:
        gates = await composer.resolve_gates(chat_id_key)
    except Exception:
        pass
    plan = composer.PromptPlan(
        profile=profile if profile in composer.PROFILES
        else composer.PROFILE_SPEECH_PLAIN,
        writer="speech_ui_preview",
        chat_id=chat_id_key,
        base_prompt=base_raw,
        core=core_ref,
        gates=gates,
        style_policy=composer.StylePolicyRef(
            hint=hint, revision=policy.revision or "",
            source=policy.source or "default",
            rule_count=len(policy.rules or ()),
            skip_reason=policy.skip_reason or ""),
        expression=expression_settings,
    )
    manifest = composer.compose_prompt(plan)
    layers = composer.render_effective_layers(manifest)["layers"]
    return {
        "manifest_id": manifest.manifest_id,
        "writer": manifest.writer,
        "profile": manifest.profile,
        "tokens_total": manifest.tokens_total,
        "layers": layers,
        "layer_order": [t.layer for t in manifest.layers],
        "versions": dict(manifest.versions or {}),
        "flags": dict(manifest.flags or {}),
        "conflicts": [c.conflict_id for c in manifest.conflicts],
        "system_masked": _mask_text(manifest.system),
        "system_chars": len(manifest.system or ""),
        "preview_note": ("Предпросмотр — детерминированный текст инструкции, "
                         "не речевой результат; для проверки голоса — "
                         "«Проверить вживую». Слои, которые приносит сам ход "
                         "(identity/plan/lessons/few-shot библиотеки W4), "
                         "помечены реальной причиной пропуска — это не "
                         "«сломанный характер»."),
    }


async def _core_ref_from_doc(doc: dict, *, source: str):
    """CoreRef из конкретного документа (кандидат/предпросмотр)."""
    from services import prompt_composer as composer
    selection = pr.core_selection(doc, source=source,
                                  budget_tokens=_composer_budget())
    return composer.CoreRef(
        text=str(selection.get("text") or ""),
        revision=str(selection.get("revision") or ""),
        source=str(selection.get("source") or source),
        document_revision=str(selection.get("document_revision") or ""),
        detail_level=str(selection.get("level") or "compact"),
        detail_reason=str(selection.get("reason") or ""),
        compact_words=int(selection.get("compact_words") or 0),
        origin=str(selection.get("origin") or ""),
        enabled=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# «Обучение» (SOUL-10.6) — существующие уроки Experience + честный статус W4
# ═══════════════════════════════════════════════════════════════════════════

async def _learning_payload(chat_id: int | None) -> dict:
    gates = _gate_state()
    humor_enabled = bool(gates.get("humor_feedback_enabled"))
    humor: dict = {
        "enabled": humor_enabled,
        "available": False,
        "reason": ("humor_feedback_disabled" if not humor_enabled else ""),
        "note": ("Сбор реакций на шутки (что подхватили / что не зашло / "
                 "гипотезы) — контур SOUL-08 внутри существующего Experience: "
                 "отдельного обучения нет. Отсутствие реакций — не провал: "
                 "такие окна остаются unknown."),
        "entries": [], "signals": {}, "confidence": {}, "unknown_windows": 0,
        "sends": 0, "hypotheses": [], "decay_note": (
            "Ослабление приёма действует только в этом чате и затухает со "
            "временем без новых наблюдений."),
        "policy": humor_feedback.POLICY_VERSION,
        "classifier": humor_feedback.CLASSIFIER_VERSION,
        "scenarios": humor_feedback.scenario_summary(),
        "controls": {"pause": "set_paused", "approve": "approve_lesson",
                     "reject": "reject_lesson", "reset": "reset_learning"},
    }
    if humor_enabled:
        try:
            from services import lore_runtime
            db = lore_runtime.get_lore_db()
            telemetry = await humor_feedback.telemetry(db, chat_id=chat_id)
            humor.update({
                "available": bool(telemetry.get("available")),
                "reason": str(telemetry.get("reason") or ""),
                "sends": int(telemetry.get("sends") or 0),
                "signals": telemetry.get("signals") or {},
                "confidence": telemetry.get("confidence") or {},
                "unknown_windows": int(telemetry.get("unknown_windows") or 0),
                "hypotheses": telemetry.get("hypotheses") or [],
                "paused": bool(telemetry.get("paused")),
                "no_data_note": telemetry.get("no_data_note") or "",
            })
            humor["entries"] = [
                {"lesson_id": lesson.get("lesson_id"),
                 "technique": lesson.get("technique"),
                 "direction": lesson.get("direction"),
                 "status": lesson.get("status"),
                 "updated_at": lesson.get("updated_at"),
                 "decay": lesson.get("decay"),
                 "influence": ("приём применяется реже" if
                               str(lesson.get("direction")) == "weaken"
                               else "приём подтверждён как уместный")}
                for lesson in (telemetry.get("lessons") or [])
            ]
        except Exception:
            logger.warning("[speech] humor feedback telemetry failed",
                           exc_info=True)
            humor["reason"] = "read_error"
    out: dict = {
        "humor_feedback": humor,
        "lessons": {"enabled": bool(gates.get("experience_lessons_enabled")),
                    "state": "unknown", "items": [], "count": 0},
        "note": ("Простым языком: «что зашло» — счётчики сигналов по классам и "
                 "уверенности; «какие гипотезы» — уроки-кандидаты; «повлияло "
                 "ли на следующий ответ» — активные предпочтения чата и их "
                 "затухание. Числа — из реальных наблюдений, не из догадок."),
    }
    if not gates.get("experience_lessons_enabled", True):
        out["lessons"]["state"] = "disabled"
        return out
    try:
        from services import lore_runtime, mca_experience as me
        db = lore_runtime.get_lore_db()
        if db is None:
            out["lessons"]["state"] = "no_db"
            return out
        rows = await me.get_service(db).list_lessons(chat_id=chat_id, limit=50)
        if chat_id is None:
            rows = [r for r in rows if str(r.get("scope")) == "global"]
        items = []
        for lesson in rows[:50]:
            items.append({
                "lesson_id": lesson.get("lesson_id"),
                "version": lesson.get("version"),
                "type": lesson.get("type"),
                "scope": lesson.get("scope"),
                "scope_chat_id": lesson.get("scope_chat_id"),
                "recommendation": _mask_text(lesson.get("recommendation")),
                "applicability": _mask_text(lesson.get("applicability")),
                "exceptions": _mask_text(lesson.get("exceptions")),
                "status": lesson.get("status"),
                "applied": (str(lesson.get("status")) == "active"
                            and not bool(lesson.get("recheck_required"))),
                "counters": {
                    "success": int(lesson.get("counters_success") or 0),
                    "failure": int(lesson.get("counters_failure") or 0),
                    "unknown": int(lesson.get("counters_unknown") or 0),
                },
                "applications_count": int(lesson.get("applications_count")
                                          or 0),
                "updated_at": lesson.get("updated_at"),
                "sources": {
                    "policy": lesson.get("policy_version"),
                    "proposal": lesson.get("proposal_version"),
                    "validator": lesson.get("validator_version"),
                },
                "confidence": {
                    "trusted": not bool(lesson.get("unverified")),
                    "historical": bool(lesson.get("historical")),
                    "recheck_required": bool(lesson.get("recheck_required")),
                },
            })
        out["lessons"]["items"] = items
        out["lessons"]["count"] = len(items)
        out["lessons"]["state"] = "implemented" if items else "not_run"
    except Exception:
        logger.warning("[speech] learning lessons failed", exc_info=True)
        out["lessons"]["state"] = "error"
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Модели запросов
# ═══════════════════════════════════════════════════════════════════════════

class BlockWrite(BaseModel):
    text: str = Field(max_length=200000)
    scope: str = Field(default="auto", max_length=8)
    reason: str = Field(default="", max_length=200)
    expected_updated_at: str | None = None


class BlockReset(BaseModel):
    mode: str = Field(default="factory", max_length=16)
    apply: bool = False
    confirm: bool = False
    reason: str = Field(default="", max_length=200)
    expected_updated_at: str | None = None


class BlockRollback(BaseModel):
    sha256_12: str = Field(min_length=4, max_length=64)
    scope: str = Field(default="auto", max_length=8)
    reason: str = Field(default="", max_length=200)


class StyleWrite(BaseModel):
    document: dict
    scope: str = Field(default="auto", max_length=8)
    reason: str = Field(default="", max_length=200)
    expected_updated_at: str | None = None


class StylePreview(BaseModel):
    document: dict | None = None
    context: str = Field(default="regular", max_length=32)


class ExpressionWrite(BaseModel):
    values: dict
    scope: str = Field(default="auto", max_length=8)


class CoreMeta(BaseModel):
    detail_level: str | None = None
    enabled: bool | None = None
    scope: str = Field(default="auto", max_length=8)


class TryRequest(BaseModel):
    text: str = Field(max_length=4000)
    profile: str = Field(default="speech_plain", max_length=32)
    candidate: dict | None = None
    generate: bool = False
    chat_model: str | None = Field(default=None, max_length=200)


# ═══════════════════════════════════════════════════════════════════════════
# Эндпоинты
# ═══════════════════════════════════════════════════════════════════════════

@speech_router.get("/speech/overview")
async def get_overview(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Точка входа «Речь и характер»: компактная витрина + статус разделов."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    gates = _gate_state()
    core: dict = {}
    try:
        core = await _core_payload(cache, user, ctx, chat_id)
    except Exception:
        logger.warning("[speech] overview core failed", exc_info=True)
    style: dict = {}
    try:
        style = await _style_payload(cache, chat_id)
    except Exception:
        logger.warning("[speech] overview style failed", exc_info=True)
    capabilities: dict = {}
    try:
        capabilities = await _capabilities_payload(chat_id)
    except Exception:
        logger.warning("[speech] overview capabilities failed", exc_info=True)
    expression = await _expression_payload(cache, chat_id)
    # ── F3 REVIEW-W4: карточки хаба описывают ФАКТИЧЕСКОЕ состояние
    # поставленных разделов (примеры — реальная библиотека, обучение —
    # существующие уроки опыта + реакции на шутки по своей оси).
    examples_card = await _examples_card()
    learning_card = _learning_card(gates)
    core_level = str((core.get("selection") or {}).get("level"))
    core_edition = (core.get("editions") or {}).get(
        "full" if core_level == "full" else "compact", {})
    return {
        "scope": "chat" if chat_id is not None else "global",
        "chat_id": chat_id,
        "inheritance": core.get("inheritance"),
        "gates": gates,
        "sections": [
            {"id": "core", "icon": "psychology", "title": "Характер",
             "subtitle": "Постоянный характер: полная и компактная редакции",
             "state": ("withheld" if core_edition.get("withheld")
                       else "custom" if core_edition.get("differs_from_factory")
                       else "factory"),
             "detail": ("Действует %s редакция · %s зн." % (
                 "полная" if core_level == "full" else "компактная",
                 core_edition.get("chars") or 0)),
             "ready": True},
            {"id": "style", "icon": "format_quote", "title": "Стиль письма",
             "subtitle": "Кавычки, точки, эмодзи, оформление",
             "state": ("custom" if (style.get("rules") or
                                    style.get("soft_instructions"))
                       else "factory"),
             # TJ-3 (P0A-UX §3.2): карточка витрины — человеческой строкой;
             # сырое `inheritance` (chat/global/factory_default) в основном
             # UI не показывается (доступно в детали раздела).
             "detail": (("Правил: %d · %s" % (
                 len(style.get("rules") or []),
                 {"chat": "переопределено для чата",
                  "global": "задано глобально",
                  "factory_default": "заводское значение"}.get(
                      (style.get("document") or {}).get("inheritance"),
                      "по настройке")))
                 if (style.get("rules") or style.get("soft_instructions"))
                 else "Правил пока нет — форма текста как обычно"),
             "ready": True},
            {"id": "expression", "icon": "tune", "title": "Выражение",
             "subtitle": "Остроумие, резкость, мат, развёрнутость",
             "state": ("custom" if expression.get("present") else "factory"),
             "detail": ("задано владельцем" if expression.get("present")
                        else "по умолчанию"),
             "ready": True},
            {"id": "humor", "icon": "theater_comedy", "title": "Юмор",
             "subtitle": "Приёмы и примеры шуток",
             "state": ("enabled" if gates.get("humor_library_enabled")
                       else "off"),
             "detail": ("библиотека включена" if gates.get(
                 "humor_library_enabled") else "библиотека выключена"),
             "ready": True},
            {"id": "examples", "icon": "library_books", "title": "Примеры",
             "subtitle": "Карточки примеров (few-shot)",
             "state": str(examples_card["state"]),
             "detail": str(examples_card["detail"]),
             "ready": bool(examples_card["ready"])},
            {"id": "try", "icon": "science", "title": "Попробовать",
             "subtitle": "Сравнение current и candidate",
             "state": "ready", "detail": "ничего не отправляет в Telegram",
             "ready": True},
            {"id": "learning", "icon": "school", "title": "Обучение",
             "subtitle": "Что зашло и что повлияло на ответ",
             "state": str(learning_card["state"]),
             "detail": str(learning_card["detail"]),
             "ready": True},
        ],
        "advanced": [
            {"id": "all", "icon": "list_alt", "title": "Все инструкции",
             "subtitle": "Каждый блок реестра: текст, версия, scope, откат",
             "ready": True},
            {"id": "inspector", "icon": "fact_check",
             "title": "Effective Prompt Inspector",
             "subtitle": "Предпросмотр и фактически отправленный payload",
             "ready": _can_edit_inspector(ctx)},
            {"id": "capabilities", "icon": "extension",
             "title": "Возможности бота",
             "subtitle": "Что доступно в этом чате и почему",
             "ready": True},
        ],
        "capability_summary": capabilities.get("summary") or {},
        "registry": {
            "blocks": len(pr.registry_view()),
            "version": pr.REGISTRY_VERSION,
            "factory_set": pr.factory_set_fingerprint(),
        },
        "can_edit": _can_edit_speech(cache, user, ctx, pg_key=pr.CORE_DOC_KEY,
                                     chat_id=chat_id),
        "can_view_inspector": _can_edit_inspector(ctx),
    }


@speech_router.get("/speech/blocks")
async def get_blocks(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
    family: Annotated[str | None, Query(max_length=64)] = None,
    speech_only: Annotated[bool, Query()] = False,
):
    """«Все инструкции»: все блоки реестра с effective-состоянием."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    rows = await _blocks_rows(cache, chat_id)
    if family:
        rows = [r for r in rows if str(r.get("family")) == family]
    if speech_only:
        rows = [r for r in rows if r.get("speech")]
    families = sorted({str(r.get("family") or "") for r in rows})
    return {"scope": "chat" if chat_id is not None else "global",
            "chat_id": chat_id, "blocks": rows, "families": families,
            "registry_version": pr.REGISTRY_VERSION,
            "gates": _gate_state(),
            "stale_values": _stale_values_count()}


def _stale_values_count() -> int:
    """Значения, удержанные резолвером (провенанс) — витрина конфликта W1."""
    try:
        return len(pr.withheld_values())
    except Exception:
        return 0


@speech_router.get("/speech/block/{block_id}")
async def get_block(
    block_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Детали блока: текущая/заводская версия, diff, история, провенанс."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    return await _block_detail(cache, user, ctx, chat_id, block_id)


@speech_router.post("/speech/block/{block_id}")
async def post_block(
    block_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: BlockWrite,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сохранение значения — ЕДИНСТВЕННЫМ путём реестра (write_speech_value)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    spec = pr.block(block_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="блок не найден")
    if not spec.pg_key:
        raise HTTPException(status_code=409,
                            detail="блок не редактируется из MiniApp")
    scope = _resolve_scope(body.scope, chat_id)
    if not _can_edit_speech(cache, user, ctx, pg_key=spec.pg_key,
                            chat_id=scope[0]):
        raise HTTPException(status_code=403, detail="нет права на правку речи")
    from services import prompt_factory as pf
    try:
        result = await pf.write_speech_value(
            block_id, body.text, cache=cache, actor=user.id,
            reason=body.reason or "owner_edit", chat_id=scope[0],
            pg=_doc_pg(cache) if scope[0] is not None else None,
            expected_updated_at=body.expected_updated_at)
    except Exception as exc:
        name = type(exc).__name__
        if name == "FactoryConflict":
            raise HTTPException(status_code=409,
                                detail="значение изменено другим путём") from exc
        if name == "ChatParamsConflict":
            raise HTTPException(status_code=409,
                                detail=_chat_write_detail(exc)) from exc
        logger.warning("[speech] write failed", exc_info=True)
        raise HTTPException(status_code=503,
                            detail=WRITE_UNAVAILABLE_DETAIL) from exc
    if not result.get("applied") and result.get("reason") not in (
            "already_that_value",):
        raise HTTPException(status_code=409, detail=str(
            result.get("reason") or "не применено"))
    return {"ok": True, "block_id": block_id, "result": result,
            "effective": _effective_after_write(cache, chat_id, block_id)}


def _resolve_scope(scope: str, chat_id: int | None) -> tuple[int | None, str]:
    """`auto|global|chat` → (chat_id для записи, ярлык)."""
    value = str(scope or "auto").lower()
    if value == "global":
        return None, "global"
    if value == "chat":
        if chat_id is None:
            raise HTTPException(status_code=422,
                                detail="scope=chat требует X-Chat-Id")
        return int(chat_id), "chat"
    return chat_id, "chat" if chat_id is not None else "global"


def _effective_after_write(cache, chat_id: int | None, block_id: str) -> dict:
    """Чтение эффективного значения после записи (диагностика/удержание)."""
    spec = pr.block(block_id)
    pg_value = None
    if spec is not None and spec.pg_key and cache is not None:
        try:
            pg_value = cache.get(spec.pg_key, None)
        except Exception:
            pg_value = None
    eff = pr.effective_prompt(block_id, pg_value=pg_value, chat_value=None)
    return _effective_dict(eff)


@speech_router.post("/speech/block/{block_id}/reset")
async def post_block_reset(
    block_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: BlockReset,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сброс: заводской вариант (с diff) или «сбросить переопределение чата»."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    spec = pr.block(block_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="блок не найден")
    if not spec.pg_key:
        raise HTTPException(status_code=409,
                            detail="блок не редактируется из MiniApp")
    from services import prompt_factory as pf
    mode = str(body.mode or "factory").lower()
    if mode == "chat":
        if chat_id is None:
            raise HTTPException(status_code=422,
                                detail="сброс чата требует X-Chat-Id")
        if not _can_edit_speech(cache, user, ctx, pg_key=spec.pg_key,
                                chat_id=chat_id):
            raise HTTPException(status_code=403, detail="нет права")
        try:
            result = await pf.reset_chat_override(int(chat_id), block_id,
                                                  pg=_doc_pg(cache))
        except Exception as exc:
            if type(exc).__name__ == "FactoryConflict":
                raise HTTPException(
                    status_code=409,
                    detail="значение изменено другим путём") from exc
            if type(exc).__name__ == "ChatParamsConflict":
                raise HTTPException(status_code=409,
                                    detail=_chat_write_detail(exc)) from exc
            logger.warning("[speech] chat reset failed", exc_info=True)
            raise HTTPException(status_code=503,
                                detail=RESET_UNAVAILABLE_DETAIL) from exc
        if not result.get("applied") and result.get("reason") not in (
                "no_chat_override",):
            logger.warning("[speech] chat reset not applied | reason=%s",
                           result.get("reason"))
            raise HTTPException(status_code=503,
                                detail=RESET_UNAVAILABLE_DETAIL)
        return {"ok": bool(result.get("applied")), "mode": "chat",
                "result": result, "inherits": "global"}
    if not _can_edit_speech(cache, user, ctx, pg_key=spec.pg_key, chat_id=None):
        raise HTTPException(status_code=403, detail="нет права на глобальный "
                                                   "сброс")
    if not body.apply:
        return {"ok": True, "mode": "factory", "plan": await
                pf.plan_factory_reset(block_id, cache=cache), "applied": False}
    result = await pf.apply_factory_reset(
        block_id, cache=cache, actor=user.id,
        expected_updated_at=body.expected_updated_at,
        reason=body.reason or "factory_reset")
    return {"ok": bool(result.get("applied")) or result.get("reason")
            == "already_factory", "mode": "factory", "result": result,
            "effective": _effective_after_write(cache, chat_id, block_id)}


@speech_router.post("/speech/block/{block_id}/rollback")
async def post_block_rollback(
    block_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: BlockRollback,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Откат к ревизии из истории — тем же путём записи (write_speech_value)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    spec = pr.block(block_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="блок не найден")
    if not spec.pg_key:
        raise HTTPException(status_code=409, detail="блок не редактируется")
    scope_id, _label = _resolve_scope(body.scope, chat_id)
    if not _can_edit_speech(cache, user, ctx, pg_key=spec.pg_key,
                            chat_id=scope_id):
        raise HTTPException(status_code=403, detail="нет права на правку речи")
    from services import prompt_factory as pf
    history = await pf.history_for(block_id, cache=cache)
    target = None
    for row in history:
        if str(row.get("sha256_12") or "") == str(body.sha256_12):
            target = row
            break
    if target is None or not str(target.get("text") or ""):
        raise HTTPException(status_code=404,
                            detail="ревизия не найдена в истории")
    try:
        result = await pf.write_speech_value(
            block_id, str(target.get("text") or ""), cache=cache, actor=user.id,
            reason=body.reason or ("rollback:" + str(body.sha256_12)[:12]),
            chat_id=scope_id,
            pg=_doc_pg(cache) if scope_id is not None else None)
    except Exception as exc:
        if type(exc).__name__ == "FactoryConflict":
            raise HTTPException(
                status_code=409,
                detail="значение изменено другим путём") from exc
        if type(exc).__name__ == "ChatParamsConflict":
            raise HTTPException(status_code=409,
                                detail=_chat_write_detail(exc)) from exc
        logger.warning("[speech] rollback failed", exc_info=True)
        raise HTTPException(status_code=503,
                            detail=WRITE_UNAVAILABLE_DETAIL) from exc
    if not result.get("applied") and result.get("reason") not in (
            "already_that_value",):
        raise HTTPException(status_code=409, detail=str(
            result.get("reason") or "не применено"))
    return {"ok": True, "result": result,
            "rolled_back_to": str(body.sha256_12),
            "effective": _effective_after_write(cache, chat_id, block_id)}


@speech_router.get("/speech/core")
async def get_core(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раздел «Характер»: обе редакции, режим scope, diff, версии, откат."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    return await _core_payload(cache, user, ctx, chat_id)


@speech_router.post("/speech/core/meta")
async def post_core_meta(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: CoreMeta,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Документные поля Core: detail_level (компактная/полная) и enabled."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    scope_id, _label = _resolve_scope(body.scope, chat_id)
    if not _can_edit_speech(cache, user, ctx, pg_key=pr.CORE_DOC_KEY,
                            chat_id=scope_id):
        raise HTTPException(status_code=403, detail="нет права на правку ядра")
    if body.detail_level is not None and str(body.detail_level) not in (
            pr.CORE_DETAIL_LEVELS):
        raise HTTPException(status_code=422, detail="неизвестный detail_level")
    result = await _write_core_meta(cache, scope_id, body, actor=user.id)
    if not result.get("applied"):
        logger.warning("[speech] core meta not applied | scope=%s | reason=%s",
                       "chat" if scope_id is not None else "global",
                       result.get("reason"))
        raise HTTPException(status_code=503,
                            detail=WRITE_UNAVAILABLE_DETAIL)
    return {"ok": True, "result": result}


async def _write_core_meta(cache, chat_id: int | None, body: CoreMeta,
                           actor: Any = None) -> dict:
    """Запись полей документа Core (не текстов): revision инкрементируется.

    Тексты редакций пишутся ТОЛЬКО через ``write_speech_value`` — здесь
    меняются документные поля, провенанс текстов не затрагивается.
    """
    from services import chat_params
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id is None:
        if cache is None:
            return {"applied": False, "reason": "config_cache_unavailable"}
        try:
            current = _as_doc(cache.get(pr.CORE_DOC_KEY, None))
        except Exception:
            current = None
        doc = dict(current) if isinstance(current, dict) else {}
        doc.setdefault("full_text", "")
        doc.setdefault("compact_text", "")
        if body.detail_level is not None:
            doc["detail_level"] = str(body.detail_level)
        if body.enabled is not None:
            doc["enabled"] = bool(body.enabled)
        doc["revision"] = int(doc.get("revision", 0) or 0) + 1
        doc["origin"] = str(doc.get("origin") or "owner_edit")
        doc["updated_at"] = now
        doc["updated_by"] = actor
        try:
            await cache.set(pr.CORE_DOC_KEY, doc,
                            category=CORE_DOC_CATEGORY)
        except Exception:
            logger.warning("[speech] core meta write failed", exc_info=True)
            return {"applied": False, "reason": "write_error"}
        return {"applied": True, "scope": "global", "revision": doc["revision"]}
    try:
        pg = _doc_pg(cache)
        root = await (chat_params.get_all_chat_params(int(chat_id), pg=pg)
                      if pg is not None
                      else chat_params.get_all_chat_params(int(chat_id)))
        overrides = dict((root or {}).get("overrides") or {})
        current = _as_doc(overrides.get(pr.CORE_DOC_KEY))
        doc = dict(current) if isinstance(current, dict) else {}
        if not doc:
            # Наследование: базой для локальной правки служит глобальный Core.
            global_doc = None
            if cache is not None:
                try:
                    global_doc = _as_doc(cache.get(pr.CORE_DOC_KEY, None))
                except Exception:
                    global_doc = None
            doc = dict(global_doc) if isinstance(global_doc, dict) else {}
        if body.detail_level is not None:
            doc["detail_level"] = str(body.detail_level)
        if body.enabled is not None:
            doc["enabled"] = bool(body.enabled)
        doc["revision"] = int(doc.get("revision", 0) or 0) + 1
        doc["origin"] = str(doc.get("origin") or "owner_edit")
        doc["updated_at"] = now
        doc["updated_by"] = actor
        overrides[pr.CORE_DOC_KEY] = doc
        await chat_params.set_chat_params(int(chat_id),
                                          {"overrides": overrides}, pg=pg)
        return {"applied": True, "scope": "chat", "chat_id": int(chat_id),
                "revision": doc["revision"]}
    except Exception:
        logger.warning("[speech] core meta chat write failed", exc_info=True)
        return {"applied": False, "reason": "write_error"}


@speech_router.get("/speech/style")
async def get_style(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
    context: Annotated[str, Query(max_length=32)] = "regular",
):
    """Раздел «Стиль письма»: правила, hard/soft, источники, примеры."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    payload = await _style_payload(cache, chat_id, context=context)
    payload["can_edit"] = _can_edit_speech(cache, user, ctx, pg_key="",
                                           chat_id=chat_id)
    return payload


@speech_router.post("/speech/style")
async def post_style(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: StyleWrite,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сохранение правил формы (глобально/для чата) через style_policy."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    scope_id, _label = _resolve_scope(body.scope, chat_id)
    if not _can_edit_speech(cache, user, ctx, pg_key="", chat_id=scope_id):
        raise HTTPException(status_code=403, detail="нет права на стиль письма")
    from services import style_policy as sp
    result = await sp.save_policy_document(
        body.document, chat_id=scope_id, cache=cache, actor=user.id,
        reason=body.reason or "owner_edit",
        expected_updated_at=body.expected_updated_at, pg=_doc_pg(cache))
    if not result.get("applied"):
        reason = str(result.get("reason") or "не применено")
        if reason == "document_invalid":
            # P0 PERSIST-FIX: явная валидационная ошибка вместо тихой потери
            # правила (unknown kind/не-объект) при applied:true.
            issues = [str(i) for i in (result.get("blocking_issues")
                                       or result.get("issues") or [])]
            detail = "документ не прошёл проверку"
            if issues:
                detail += ": " + "; ".join(issues[:4])
            raise HTTPException(status_code=409, detail=detail)
        if reason == "conflict":
            # Чужой optimistic-токен: документ не записан, текст не потерян.
            raise HTTPException(
                status_code=409,
                detail=("документ изменён другим путём — обновите экран; "
                        "ваш текст не потерян"))
        logger.warning("[speech] style save not applied | reason=%s", reason)
        raise HTTPException(status_code=503,
                            detail=WRITE_UNAVAILABLE_DETAIL)
    return {"ok": True, "result": result,
            "view": await _style_payload(cache, chat_id)}


@speech_router.post("/speech/style/reset-chat")
async def post_style_reset_chat(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """«Сбросить для чата»: возврат к наследованию (НЕ заводской сброс)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    if not _can_edit_speech(cache, user, ctx, pg_key="", chat_id=chat_id):
        raise HTTPException(status_code=403, detail="нет права")
    from services import style_policy as sp
    result = await sp.reset_chat_policy(int(chat_id), pg=_doc_pg(cache))
    if not result.get("applied") and result.get("reason") != "no_chat_override":
        # P0 PERSIST-FIX: сбой сброса — явная ошибка, а не ложное
        # «переопределения для чата не было».
        logger.warning("[speech] style chat reset not applied | error=%s",
                       result.get("error") or result.get("reason"))
        raise HTTPException(status_code=503,
                            detail=RESET_UNAVAILABLE_DETAIL)
    return {"ok": bool(result.get("applied")), "result": result,
            "view": await _style_payload(cache, chat_id)}


@speech_router.post("/speech/style/preview")
async def post_style_preview(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: StylePreview,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Before/after на заводских примерах: текущая политика vs кандидат."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    return await _style_preview(body.document, chat_id,
                                context=body.context or "regular",
                                cache=cache)


@speech_router.get("/speech/expression")
async def get_expression(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раздел «Выражение»: человеческие контролы, эффект, preview, сброс."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    payload = await _expression_payload(cache, chat_id)
    payload["can_edit"] = _can_edit_speech(cache, user, ctx, pg_key="",
                                           chat_id=chat_id)
    return payload


@speech_router.post("/speech/expression")
async def post_expression(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: ExpressionWrite,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сохранение настроек выражения (глобально/для чата)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    scope_id, _label = _resolve_scope(body.scope, chat_id)
    if not _can_edit_speech(cache, user, ctx, pg_key="", chat_id=scope_id):
        raise HTTPException(status_code=403, detail="нет права на выражение")
    result = await _write_expression(cache, scope_id, body.values)
    if not result.get("applied"):
        # P0 PERSIST-FIX: отказ записи «Выражения» — инфраструктурный
        # (write_error/config_cache_unavailable): честные 5xx, не 409 с кодом.
        logger.warning("[speech] expression write not applied | reason=%s",
                       result.get("reason"))
        raise HTTPException(status_code=503,
                            detail=WRITE_UNAVAILABLE_DETAIL)
    return {"ok": True, "result": result,
            "view": await _expression_payload(cache, chat_id)}


async def _write_expression(cache, chat_id: int | None, values: dict) -> dict:
    """Запись документа «Выражение» (существующие слои: bot_settings/chat)."""
    from services import chat_params
    normalized = _normalize_expression(values)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id is None:
        if cache is None:
            return {"applied": False, "reason": "config_cache_unavailable"}
        try:
            current = _as_doc(cache.get(EXPRESSION_DOC_KEY, None))
        except Exception:
            current = None
        doc = dict(current) if isinstance(current, dict) else {}
        history = list(doc.get("history") or [])
        if doc:
            history.insert(0, {"revision": int(doc.get("revision", 1) or 1),
                               "values_sha256_12": pr.sha12(json.dumps(
                                   _normalize_expression(doc), sort_keys=True,
                                   ensure_ascii=False)),
                               "updated_at": doc.get("updated_at") or ""})
        doc = {**{k: v for k, v in doc.items()
                  if k not in ("history", "revision", "updated_at")},
               **normalized}
        doc["revision"] = int((current or {}).get("revision", 0) or 0) + 1
        doc["history"] = history[:EXPRESSION_REVISION_MAX]
        doc["updated_at"] = now
        try:
            await cache.set(EXPRESSION_DOC_KEY, doc,
                            category=EXPRESSION_DOC_CATEGORY)
        except Exception:
            logger.warning("[speech] expression write failed", exc_info=True)
            return {"applied": False, "reason": "write_error"}
        return {"applied": True, "scope": "global", "revision": doc["revision"]}
    try:
        pg = _doc_pg(cache)
        root = await (chat_params.get_all_chat_params(int(chat_id), pg=pg)
                      if pg is not None
                      else chat_params.get_all_chat_params(int(chat_id)))
        overrides = dict((root or {}).get("overrides") or {})
        current = _as_doc(overrides.get(EXPRESSION_DOC_KEY))
        doc = dict(current) if isinstance(current, dict) else {}
        doc = {**{k: v for k, v in doc.items()
                  if k not in ("history", "revision", "updated_at")},
               **normalized}
        doc["revision"] = int(((current or {}).get("revision") or 0)) + 1
        doc["updated_at"] = now
        overrides[EXPRESSION_DOC_KEY] = doc
        await chat_params.set_chat_params(int(chat_id),
                                          {"overrides": overrides}, pg=pg)
        return {"applied": True, "scope": "chat", "chat_id": int(chat_id),
                "revision": doc["revision"]}
    except Exception:
        logger.warning("[speech] expression chat write failed", exc_info=True)
        return {"applied": False, "reason": "write_error"}


@speech_router.post("/speech/expression/reset-chat")
async def post_expression_reset_chat(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сброс настроек выражения к наследованию глобальных (данные не теряем)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    if not _can_edit_speech(cache, user, ctx, pg_key="", chat_id=chat_id):
        raise HTTPException(status_code=403, detail="нет права")
    from services import chat_params
    pg = _doc_pg(cache)
    try:
        root = await (chat_params.get_all_chat_params(int(chat_id), pg=pg)
                      if pg is not None
                      else chat_params.get_all_chat_params(int(chat_id)))
        overrides = dict((root or {}).get("overrides") or {})
        if EXPRESSION_DOC_KEY not in overrides:
            return {"ok": False, "reason": "no_chat_override",
                    "view": await _expression_payload(cache, chat_id)}
        overrides.pop(EXPRESSION_DOC_KEY, None)
        await chat_params.set_chat_params(int(chat_id),
                                          {"overrides": overrides}, pg=pg)
    except Exception:
        logger.warning("[speech] expression reset failed", exc_info=True)
        raise HTTPException(status_code=503,
                            detail=RESET_UNAVAILABLE_DETAIL)
    return {"ok": True, "inherits": "global",
            "view": await _expression_payload(cache, chat_id)}


# ── ADD-EXP §5.1.8: «Проверить вживую» — контролируемая проба голоса ────────

#: Минимальный интервал между пробами (rate-limit, bounded; без очередей).
LIVE_CHECK_MIN_INTERVAL_SECONDS = 30.0
_live_check_state: dict = {"ts": 0.0, "busy": False}


def _direct_service():
    """Singleton DirectChatService (DI bot.py → handlers.direct_chat).

    ``None`` → Direct-модуль не поднят в этом процессе: проба честно
    недоступна (ничего не выдумываем и не зовём модель мимо боевого пути).
    """
    try:
        from handlers import direct_chat as _dc
        return getattr(_dc, "_service", None)
    except Exception:
        return None


class ExpressionLiveCheck(BaseModel):
    """Текст пробы для реального L2-вызова тем же путём (без доставки)."""

    message: str = Field(default="", max_length=500)


@speech_router.post("/speech/expression/live-check")
async def post_expression_live_check(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: ExpressionLiveCheck,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Один реальный L2-вызов (writer ``speech_ui_live_check``) + класс §6.

    Честный способ проверить речевой результат тем же путём/моделью:
    доставки в Telegram нет, второго «пробного» промпта нет — тот же боевой
    L2-канал. Rate-limit + ровно одна проба в полёте.
    """
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    if not _can_edit_speech(cache, user, ctx, pg_key="", chat_id=chat_id):
        raise HTTPException(status_code=403, detail="нет права на проверку")
    message = str(body.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="нужен текст пробы")
    now = time.time()
    if _live_check_state.get("busy") or (
            now - float(_live_check_state.get("ts") or 0.0)
            < LIVE_CHECK_MIN_INTERVAL_SECONDS):
        raise HTTPException(
            status_code=429,
            detail="Проба уже выполняется или была меньше "
                   f"{int(LIVE_CHECK_MIN_INTERVAL_SECONDS)} с назад — "
                   "подождите немного")
    service = _direct_service()
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Боевой Direct-путь в этом процессе недоступен — проба "
                   "не выполнена (модель мимо боевого пути не вызываем)")
    try:
        from services import prompt_composer as composer
        settings_ref = await composer.resolve_expression_settings(chat_id)
        mode = str(settings_ref.mode or "")
    except Exception:
        mode = ""
    correlation_id = None
    try:
        from services import usage_events as _ue
        correlation_id = _ue.new_correlation_id()
    except Exception:
        correlation_id = None
    try:
        from config.settings import settings as _settings
        temperature = _settings.tone_temperature(None)
    except Exception:
        temperature = 0.7
    diag_out: dict = {}
    started = time.perf_counter()
    _live_check_state["busy"] = True
    try:
        result = await service._l2_write_answer(
            chat_id, message, temperature=temperature,
            correlation_id=correlation_id, writer="speech_ui_live_check",
            diag_out=diag_out)
    except Exception:
        logger.warning("[speech] expression live-check failed", exc_info=True)
        expression.emit_expression_diag(
            "provider_limitation", chat_id=chat_id,
            stage="speech_ui_live_check", detail="exception", mode=mode)
        raise HTTPException(status_code=502,
                            detail="Проба не выполнена: вызов не прошёл "
                                   "(класс provider_limitation)")
    finally:
        _live_check_state["busy"] = False
        _live_check_state["ts"] = time.time()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if not result:
        return {"ok": False, "reason": "empty_answer", "mode": mode,
                "elapsed_ms": elapsed_ms, "diag_class": "",
                "note": ("Пустой ответ пробы: вызов не дал текста "
                         "(ничего не выдумываем).")}
    text, response_mode = str(result[0] or ""), str(result[1] or "")
    marker = bool(diag_out.get("expression_marker"))
    diag_class = expression.classify_expression_response(
        text, mode, genre="speech_ui_live_check", probes=1,
        marker_present=marker,
        provider_error=bool(diag_out.get("provider_error")))
    return {
        "ok": True,
        "mode": mode or "unknown",
        "reply": text,
        "reply_chars": len(text),
        "profanity_roots": expression.count_profanity(text),
        "diag_class": diag_class,
        "expression_marker": marker,
        "response_mode": response_mode,
        "elapsed_ms": elapsed_ms,
        "delivery": {"telegram_send": False},
        "note": ("Один реальный L2-вызов тем же боевым путём "
                 "(writer=speech_ui_live_check), без доставки в Telegram. "
                 "Одиночная проба не приговор: класс "
                 "`model_ignored_instruction` подтверждается набором Ф6 "
                 "(N≥5 подряд)."),
    }


@speech_router.get("/speech/humor")
async def get_humor(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раздел «Юмор»: приёмы, включённость, честный статус библиотеки W4."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    gates = _gate_state()
    can_edit = _can_edit_speech(cache, user, ctx, pg_key="", chat_id=chat_id)
    craft = await _humor_craft_payload(cache, chat_id)
    counts = await _examples_counts(chat_id)
    by_technique = dict((counts or {}).get("by_technique") or {})
    techniques = []
    for item in HUMOR_TECHNIQUES:
        state = next((t for t in craft["techniques"]
                      if t["id"] == item["id"]), None)
        item_id = str(item["id"])
        techniques.append({
            **item,
            # Реальное состояние: ось гейта + документ владельца. Для «other»
            # отдельной техники нет — показываем состояние реестра.
            "enabled": bool(state["enabled"]) if state is not None
            else bool(gates.get("humor_craft_enabled")),
            "owner_enabled": bool(state["owner_enabled"]) if state is not None
            else False,
            "layer_tokens": int((state or {}).get("layer_tokens") or 0),
            "layer_revision": str((state or {}).get("layer_revision") or ""),
            "reason": str((state or {}).get("reason")
                          or "humor_not_a_technique"),
            "gate": bool(gates.get("humor_craft_enabled")),
            "source": str(craft.get("source") or "default"),
            "samples": int(by_technique.get(item_id) or 0),
        })
    library_available = bool(counts.get("available"))
    return {
        "scope": "chat" if chat_id is not None else "global",
        "chat_id": chat_id,
        "gates": gates,
        "techniques": techniques,
        "craft": craft,
        "library": {
            "available": library_available,
            "reason": str(counts.get("reason") or ""),
            "note": ("Приёмы — ситуационный слой (SOUL-06): технику советует "
                     "L1 (`comic_strategy`), слой не создаёт второго "
                     "характера и не тратит LLM-вызовов на обычный ответ."
                     if library_available else
                     "Библиотеки нет: показаны приёмы и их реальное "
                     "состояние, примеры не подменяются."),
            **{k: counts.get(k) for k in ("total", "approved", "proposed",
                                          "archived", "uses_total",
                                          "by_version", "runtime_note")
               if k in counts},
        },
        "technique_preview_note": (
            "Кнопка «Проверить приём» показывает точный текст слоя, его "
            "версию и объём — без вызова модели и без отправки в Telegram."),
        "scenarios": humor_feedback.scenario_summary(),
        "policy_version": humor_craft.HUMOR_CRAFT_POLICY_VERSION,
        "can_edit": can_edit,
    }


class HumorCraftWrite(BaseModel):
    """Включение ремесла и отдельные приёмы (диагностический toggle)."""

    enabled: bool | None = None
    disabled_techniques: list[str] | None = Field(default=None,
                                                  max_length=8)
    scope: str = Field(default="auto", max_length=8)


@speech_router.post("/speech/humor/craft")
async def post_humor_craft(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: HumorCraftWrite,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Запись документа `humor.craft` (toggle ремесла; Core не затрагивается).

    SOUL-06.7: диагностическое выключение Humor Craft сохраняет Personality
    Core. Запись идёт существующим контуром (`bot_settings`/`chat_params`),
    второго сервиса настроек нет; `prompts.*` не пишутся вовсе."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_edit_speech(cache, user, ctx, pg_key="", chat_id=chat_id):
        raise HTTPException(status_code=403, detail="нет права на правку речи")
    scope_chat, scope_label = _resolve_scope(body.scope, chat_id)
    if scope_chat is None and not _can_edit_speech(cache, user, ctx, pg_key="",
                                                   chat_id=None):
        raise HTTPException(status_code=403,
                            detail="нужно право на глобальную правку речи")
    values: dict = {}
    if body.enabled is not None:
        values["enabled"] = bool(body.enabled)
    if body.disabled_techniques is not None:
        values["disabled_techniques"] = [
            str(t) for t in body.disabled_techniques
            if str(t) in humor_craft.TECHNIQUES][:8]
    if not values:
        raise HTTPException(status_code=422, detail="нечего сохранять")
    result = await _write_document(cache, scope_chat,
                                  humor_craft.HUMOR_CRAFT_DOC_KEY,
                                  values, actor=user.id)
    if not result.get("applied"):
        raise HTTPException(status_code=503,
                            detail=WRITE_UNAVAILABLE_DETAIL)
    return {"ok": True, "scope": scope_label, **result,
            "craft": await _humor_craft_payload(cache, chat_id)}


class HumorTechniqueTest(BaseModel):
    """Тест влияния ОДНОГО приёма (0 LLM; манифест по правилам композера)."""

    technique: str = Field(max_length=64)
    message: str = Field(default="", max_length=2000)
    profile: str = Field(default="speech_plain", max_length=32)


@speech_router.post("/speech/humor/technique/test")
async def post_humor_technique_test(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: HumorTechniqueTest,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Что именно уйдёт слоем `humor_craft` для этого приёма (без LLM)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    if str(body.technique) not in humor_craft.TECHNIQUES:
        raise HTTPException(status_code=422, detail="неизвестный приём")
    cfg = await humor_craft.resolve_config(chat_id)
    probe = humor_craft.probe_technique(body.technique, config=cfg)
    decision = humor_craft.select_technique(
        comic_strategy=str(body.technique), config=cfg)
    layer = humor_craft.render_layer(body.technique) if probe.enabled else ""
    manifest = None
    if layer:
        try:
            from services import prompt_composer as composer
            gate = composer.GateState(
                unified_composer_enabled=True, character_core_enabled=True,
                speech_style_policy_enabled=True, humor_library_enabled=False,
                humor_craft_enabled=True)
            composed = composer.compose_prompt(composer.PromptPlan(
                profile=str(body.profile or "speech_plain"),
                writer=PREVIEW_WRITER, chat_id=int(chat_id or 0),
                base_prompt="", humor=composer.HumorStrategy(
                    text=layer, technique=str(body.technique),
                    revision=probe.layer_revision, source=cfg.source),
                gates=gate))
            manifest = composer.manifest_for_events(composed)
        except Exception:
            logger.warning("[speech] humor technique preview failed",
                           exc_info=True)
    return {
        "ok": True, "chat_id": chat_id,
        "technique": str(body.technique), "title": probe.title,
        "enabled": bool(probe.enabled and humor_craft.gate_on()),
        "gate": bool(humor_craft.gate_on()),
        "owner_enabled": bool(cfg.technique_enabled(body.technique)),
        "source": cfg.source, "revision": cfg.revision,
        "selection_reason": decision.reason,
        "layer_text_masked": _mask_text(layer),
        "layer_chars": probe.layer_chars, "layer_tokens": probe.layer_tokens,
        "layer_revision": probe.layer_revision,
        "detail": list(probe.detail),
        "extra_llm_calls": humor_craft.layer_calls(body.technique),
        "manifest": manifest,
        "note": ("Предпросмотр — сборка композера, а не доказательство "
                 "реального вызова модели."),
    }


@speech_router.get("/speech/examples")
async def get_examples(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
    technique: Annotated[str | None, Query(max_length=64)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    category: Annotated[str | None, Query(max_length=16)] = None,
):
    """Раздел «Примеры»: реальная библиотека (карточки по схеме сущности W4).

    ADD-SAMPLES-UX §1: три реальные категории (general/humor/mat; legacy —
    только миграция, владелец переклассифицирует) читаются из ЯВНОГО поля
    записи; §3 — tombstone-группа удалённых заводских отдаётся отдельно.
    """
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    can_edit = _library_can_edit(cache, user, ctx, chat_id=chat_id)
    db = samples_lib.get_db()
    db_ok = await samples_lib.table_ready(db)
    items: list[dict] = []
    deleted: list[dict] = []
    reason = "" if db_ok else ("db_unavailable" if db is None
                               else "schema_absent")
    if db_ok:
        try:
            category_filter = category if category in \
                samples_lib.SAMPLE_CATEGORY_STORAGE else None
            rows = await samples_lib.list_samples(
                db, chat_id=chat_id, technique=technique, status=status,
                category=category_filter, limit=200)
            items = [dict(row) for row in rows]
            deleted = await samples_lib.list_tombstoned(db, chat_id=chat_id)
            deleted = [dict(row) for row in deleted][:50]
        except Exception:
            logger.warning("[speech] samples list failed", exc_info=True)
            reason = "read_error"
    if not can_edit:
        # Чужой/неполный доступ: тексты примеров не отдаём открыто.
        items = [{**row, "input_text": _mask_text(row.get("input_text")),
                  "reply_text": _mask_text(row.get("reply_text")),
                  "context_note": _mask_text(row.get("context_note"))}
                 for row in items]
    counts = await _examples_counts(chat_id)
    policy, policy_source = await samples_lib.resolve_policy(chat_id)
    return {
        "scope": "chat" if chat_id is not None else "global",
        "chat_id": chat_id,
        "status": ("implemented" if items else
                   ("empty" if db_ok else "unavailable")),
        "available": bool(db_ok),
        "reason": reason,
        "note": ("Примеры — данные (таблица `humor_samples`), а не промпт: "
                 "владелец добавляет, правит, архивирует и утверждает "
                 "эталоны. В runtime уходят только утверждённые."),
        "entity_fields": [dict(f) for f in SAMPLE_ENTITY_FIELDS],
        "techniques": [dict(t) for t in SAMPLE_TECHNIQUES_UI],
        # ADD-SAMPLES-UX §1: категории записи (ровно три для записи;
        # legacy — служебный раздел миграции, показывается для переклассификации).
        "categories": [
            {"id": cat, "title": samples_lib.SAMPLE_CATEGORY_LABELS[cat]}
            for cat in samples_lib.SAMPLE_CATEGORIES
        ] + [{"id": "legacy",
              "title": samples_lib.SAMPLE_CATEGORY_LABELS["legacy"]}],
        "filters": {"technique": technique, "status": status,
                    "category": category},
        "items": items,
        "deleted": deleted,
        "count": len(items),
        "starter": {
            "version": samples_lib.STARTER_LIBRARY_VERSION,
            "expected": len(samples_lib.STARTER_SAMPLES),
            "seeded": int(counts.get("starter_seeded") or 0),
            # ADD-EXP (BLOCK-1): заводской набор регистра речи — отдельная
            # подборка (сиды живут в той же таблице, счётчики не склеиваются).
            "expression_version": samples_lib.EXPRESSION_STARTER_LIBRARY_VERSION,
            "expression_expected": len(samples_lib.EXPRESSION_STARTER_SAMPLES),
            "expression_seeded": int(
                counts.get("expression_starter_seeded") or 0),
        },
        "telemetry": counts,
        "policy": policy,
        "policy_source": policy_source,
        "ab": counts.get("ab") or {"enabled": False, "versions": []},
        "runtime_note": ("В runtime уходит 1–3 утверждённых примера (слой "
                         "few_shot) при включённой оси `HUMOR_LIBRARY_ENABLED` "
                         "и включённой политике `humor.selection`; не "
                         "утверждённые черновики в runtime не попадают."),
        "can_edit": can_edit,
    }


class SampleWrite(BaseModel):
    """Создание/правка примера (поля ровно по схеме сущности)."""

    input_text: str = Field(default="", max_length=2000)
    reply_text: str = Field(default="", max_length=4000)
    technique: str = Field(default="other", max_length=64)
    context_note: str = Field(default="", max_length=600)
    language: str = Field(default="ru", max_length=12)
    tags: list[str] = Field(default_factory=list, max_length=12)
    rudeness_level: int = 0
    source_kind: str = Field(default="owner_manual", max_length=24)
    scope: str = Field(default="global", max_length=8)
    library_version: str = Field(default="", max_length=32)
    owner_approved: bool | None = None
    status: str = Field(default="active", max_length=12)
    expected_revision: int | None = None
    # ADD-SAMPLES-UX §1: явная категория записи и режим мата для «Мат».
    category: str = Field(default="", max_length=16)
    expression_mode: str = Field(default="", max_length=16)


class SamplePolicyWrite(BaseModel):
    """Политика отбора `humor.selection` (bounded на сервере)."""

    enabled: bool | None = None
    max_items: int | None = None
    max_tokens: int | None = None
    diversity_min_distance: float | None = None
    recency_penalty: float | None = None
    max_per_technique: int | None = None
    ab_enabled: bool | None = None
    ab_versions: list[str] | None = Field(default=None, max_length=2)
    ab_weight: float | None = None
    scope: str = Field(default="auto", max_length=8)


class SampleWhyRequest(BaseModel):
    technique: str = Field(default="", max_length=64)
    extent: str = Field(default="", max_length=16)
    message: str = Field(default="", max_length=2000)


@speech_router.post("/speech/examples")
async def post_example(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: SampleWrite,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Добавить пример в библиотеку (существующий контур БД; RBAC)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    fields = body.model_dump()
    scope = str(fields.pop("scope", "global") or "global")
    if scope == "chat" and chat_id is None:
        raise HTTPException(status_code=422,
                            detail="для примера чата нужен X-Chat-Id")
    fields["scope"] = scope
    fields["chat_id"] = int(chat_id) if scope == "chat" else None
    fields["author_user_id"] = user.id
    view, reason = await samples_lib.create_sample(
        samples_lib.get_db(), fields=fields, actor=str(user.id))
    if view is None:
        code = 422 if reason and not reason.startswith("db_") else 503
        raise HTTPException(status_code=code, detail=reason or "не сохранено")
    return {"ok": True, "item": view}


async def _guard_sample_chat_scope(sample_id: int, chat_id: int | None) -> dict:
    """Пример доступен только своему чату (SOUL-07.2, F1 REVIEW-W4).

    Одна проверка на все мутации карточки (update/delete/approve/archive),
    чтобы граница изоляции не расходилась между обработчиками: chat-scoped
    пример чужого чата → 403 (глобальный пример от чата не зависит).
    """
    current = await samples_lib.get_sample(samples_lib.get_db(), sample_id)
    if current is None:
        raise HTTPException(status_code=404, detail="пример не найден")
    if str(current.get("scope")) == "chat" \
            and int(current.get("chat_id") or 0) != int(chat_id or 0):
        raise HTTPException(status_code=403,
                            detail="пример принадлежит другому чату")
    return current


@speech_router.post("/speech/examples/{sample_id:int}")
async def post_example_update(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    sample_id: int,
    body: SampleWrite,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Правка примера (ревизия + optimistic-проверка версии)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    await _guard_sample_chat_scope(sample_id, chat_id)
    fields = body.model_dump()
    expected = fields.pop("expected_revision", None)
    fields.pop("scope", None)
    fields.pop("library_version", None)
    view, reason = await samples_lib.update_sample(
        samples_lib.get_db(), sample_id, fields=fields, actor=str(user.id),
        expected_revision=expected)
    if view is None:
        code = 409 if reason == "revision_conflict" else (
            422 if reason and not reason.startswith("db_") else 503)
        raise HTTPException(status_code=code, detail=reason or "не сохранено")
    return {"ok": True, "item": view}


@speech_router.post("/speech/examples/{sample_id}/approve")
async def post_example_approve(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    sample_id: int,
    x_chat_id: Annotated[str | None, Header()] = None,
    approved: Annotated[bool, Query()] = True,
):
    """Отметить пример эталонным (или снять метку): runtime берёт эталоны."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    await _guard_sample_chat_scope(sample_id, chat_id)
    view, reason = await samples_lib.set_approval(
        samples_lib.get_db(), sample_id, approved=bool(approved),
        actor=str(user.id))
    if view is None:
        raise HTTPException(status_code=422, detail=reason or "не сохранено")
    return {"ok": True, "item": view}


@speech_router.post("/speech/examples/{sample_id}/archive")
async def post_example_archive(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    sample_id: int,
    x_chat_id: Annotated[str | None, Header()] = None,
    archived: Annotated[bool, Query()] = True,
):
    """Архив/возврат примера (данные сохраняются)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    await _guard_sample_chat_scope(sample_id, chat_id)
    view, reason = await samples_lib.archive_sample(
        samples_lib.get_db(), sample_id, archived=bool(archived),
        actor=str(user.id))
    if view is None:
        raise HTTPException(status_code=422, detail=reason or "не сохранено")
    return {"ok": True, "item": view}


@speech_router.delete("/speech/examples/{sample_id}")
async def delete_example(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    sample_id: int,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Удалить пример (архив — мягкая альтернатива, подтверждает UI)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    await _guard_sample_chat_scope(sample_id, chat_id)
    ok, reason = await samples_lib.delete_sample(samples_lib.get_db(),
                                                 sample_id)
    if not ok:
        raise HTTPException(status_code=503, detail=reason or "не удалено")
    return {"ok": True, "deleted": int(sample_id)}


@speech_router.post("/speech/examples/seed")
async def post_examples_seed(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Поставить заводские подборки черновиков (идемпотентно; без «одобрения»).

    ADD-EXP (BLOCK-1): сидятся ДВЕ подборки — приёмы юмора (W4) и набор
    регистра речи (12 черновиков «без мата / эпизодически / часто»), иначе
    владелец не мог бы увидеть и утвердить их существующим механизмом, а слой
    примеров в runtime оставался бы пустым. Черновики (`owner_approved=0`) —
    в runtime не идут (`not_owner_approved`), пока владелец не утвердит.
    """
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    db = samples_lib.get_db()
    result = await samples_lib.seed_starter_samples(db)
    if result.get("reason") == "db_unavailable":
        raise HTTPException(status_code=503, detail="база недоступна")
    expression_result = await samples_lib.seed_expression_samples(db)
    if expression_result.get("reason") == "db_unavailable":
        raise HTTPException(status_code=503, detail="база недоступна")
    return {"ok": True, **result,
            "expression_seeded": int(expression_result.get("seeded") or 0),
            "expression_skipped": int(expression_result.get("skipped") or 0),
            "note": ("Черновики заведены БЕЗ владельческого одобрения: "
                     "эталонами их не считает ни runtime, ни статистика. "
                     "Набор регистра речи (12 карточек) до утверждения не "
                     "попадает в ответы — причина `not_owner_approved`.")}


@speech_router.post("/speech/examples/restore-factory/preview")
async def post_restore_factory_preview(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Экран сравнения ПЕРЕД восстановлением заводских карточек (§3).

    Показывает ровно те заводские карточки, чьи владельческие правки/удаления
    будут затронуты; «Сбросить всё» никогда не является действием по
    умолчанию — применение отдельным подтверждённым вызовом.
    """
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    preview = await samples_lib.restore_factory_preview(
        samples_lib.get_db(), chat_id=chat_id)
    return {"ok": bool(preview.get("available")), **preview}


class RestoreFactoryRequest(BaseModel):
    """Явное подтверждение восстановления заводских редакций (§3)."""

    confirm: bool = False


@speech_router.post("/speech/examples/restore-factory")
async def post_restore_factory_all(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: RestoreFactoryRequest,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Массовое восстановление заводских карточек (только явный confirm).

    Неявных путей нет: без ``confirm=true`` — честный отказ без изменений;
    silent-force на старте/деплое/миграциях отсутствует by design.
    """
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    result = await samples_lib.restore_factory_all(
        samples_lib.get_db(), chat_id=chat_id, confirm=bool(body.confirm))
    if not body.confirm:
        return {"ok": False, "reason": "needs_confirmation",
                "note": "без явного подтверждения ничего не изменено",
                **{k: v for k, v in result.items() if k != "reason"}}
    if result.get("reason") == "db_unavailable":
        raise HTTPException(status_code=503, detail="база недоступна")
    return {"ok": True, **result,
            "note": ("Восстановлены только заводские карточки из экрана "
                     "сравнения; владельческие (не заводские) примеры не "
                     "тронуты.")}


@speech_router.post("/speech/examples/{sample_id}/restore-factory/preview")
async def post_restore_factory_preview_one(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    sample_id: int,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сравнение одной заводской карточки с эталоном (до восстановления)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    current = await _guard_sample_chat_scope(sample_id, chat_id)
    if not str(current.get("seed_key") or ""):
        raise HTTPException(status_code=422, detail="пример не заводской")
    item = samples_lib.restore_factory_preview_item(current)
    item["factory"] = (samples_lib._factory_fields(
        samples_lib.factory_seed_for(str(current.get("seed_key") or "")))
        if current.get("factory_in_code") else None)
    if not current.get("factory_in_code"):
        item["note"] = ("исходник этой карточки отсутствует в текущей версии "
                        "заводского набора; ваши данные сохранены")
    return {"ok": True, "item": item}


@speech_router.post("/speech/examples/{sample_id}/restore-factory")
async def post_restore_factory_one(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    sample_id: int,
    body: RestoreFactoryRequest,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Явно восстановить ОДИН заводской пример (подтверждение обязательно)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    await _guard_sample_chat_scope(sample_id, chat_id)
    view, reason = await samples_lib.restore_factory_sample(
        samples_lib.get_db(), sample_id, confirm=bool(body.confirm))
    if view is None:
        if reason == "needs_confirmation":
            raise HTTPException(status_code=428,
                                detail="нужно явное подтверждение")
        if reason == "not_found":
            raise HTTPException(status_code=404, detail="пример не найден")
        if reason == "not_factory":
            raise HTTPException(status_code=422, detail="пример не заводской")
        if reason == "factory_seed_absent":
            raise HTTPException(
                status_code=409,
                detail=("исходник отсутствует в текущей заводской версии; "
                        "ваши данные сохранены"))
        raise HTTPException(status_code=503, detail=reason or "не сохранено")
    return {"ok": True, "item": view,
            "note": ("Восстановлен только этот пример; остальные карточки "
                     "и приложение не затронуты.")}


@speech_router.post("/speech/examples/{sample_id}/why")
async def post_example_why(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    sample_id: int,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """«Почему не используется? / Почему выбран?» — по конкретной карточке.

    Human-readable причина из существующего детерминированного отбора и
    effective-режима Expression; нет данных — честное «Нет данных о последнем
    выборе» (причины не симулируются; 0 LLM-вызовов).
    """
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    db = samples_lib.get_db()
    if not await samples_lib.table_ready(db):
        return {"ok": False, "reason": "db_unavailable",
                "why": samples_lib.WHY_NO_DATA, "selected": False}
    effective_mode = ""
    try:
        from services.prompt_composer import resolve_expression_settings
        ref = await resolve_expression_settings(chat_id)
        effective_mode = str(getattr(ref, "mode", "") or "")
    except Exception:
        logger.warning("[speech] why: effective mode resolve failed",
                       exc_info=True)
        effective_mode = ""
    result = await samples_lib.why_for_sample(
        db, chat_id=chat_id, sample_id=sample_id, effective_mode=effective_mode)
    return {"ok": True, **result}


@speech_router.post("/speech/examples/policy")
async def post_examples_policy(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: SamplePolicyWrite,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Запись политики отбора `humor.selection` (bounded; chat → override)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на правку примеров")
    scope_chat, scope_label = _resolve_scope(body.scope, chat_id)
    if scope_chat is None and not _library_can_edit(cache, user, ctx,
                                                    chat_id=None):
        raise HTTPException(status_code=403,
                            detail="нужно право на глобальную правку примеров")
    values = {k: v for k, v in body.model_dump().items()
              if k != "scope" and v is not None}
    if not values:
        raise HTTPException(status_code=422, detail="нечего сохранять")
    normalized = samples_lib.normalize_policy(
        {**samples_lib.DEFAULT_POLICY, **values})
    result = await _write_document(
        cache, scope_chat, samples_lib.SELECTION_DOC_KEY, normalized,
        actor=user.id)
    if not result.get("applied"):
        raise HTTPException(status_code=503,
                            detail=WRITE_UNAVAILABLE_DETAIL)
    policy, source = await samples_lib.resolve_policy(chat_id)
    return {"ok": True, "scope": scope_label, "policy": policy,
            "policy_source": source}


@speech_router.post("/speech/examples/why")
async def post_examples_why(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: SampleWhyRequest,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """«Почему выбраны именно эти примеры»: детерминированная трасса отбора."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    db = samples_lib.get_db()
    if not await samples_lib.table_ready(db):
        return {"ok": False, "reason": "db_unavailable", "selected": [],
                "excluded": []}
    rows = [samples_lib._to_row(row)
            for row in await samples_lib.list_samples(db, chat_id=chat_id,
                                                      status="active")]
    policy, source = await samples_lib.resolve_policy(chat_id)
    selection = samples_lib.select_samples(
        rows, chat_id=int(chat_id or 0), technique=str(body.technique or ""),
        extent=str(body.extent or ""), context=str(body.message or ""),
        policy=policy)
    return {
        "ok": True, "policy_source": source,
        "policy": policy,
        "library_version": selection.library_version,
        "reason_code": selection.reason_code,
        "selected": [dict(r) for r in selection.reasons],
        "excluded": [dict(r) for r in selection.excluded][:50],
        "tokens_estimate": selection.tokens_estimate,
        "note": ("Отбор ничего не отправляет: это та же политика, что "
                 "применяется в runtime, показанная на вашем примере."),
    }


@speech_router.get("/speech/capabilities")
async def get_capabilities(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """«Возможности бота»: что доступно/выключено/сломано и почему."""
    _cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    return await _capabilities_payload(chat_id)


@speech_router.get("/speech/inspector")
async def get_inspector(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Effective Prompt Inspector (только уполномоченные администраторы)."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_edit_inspector(ctx):
        raise HTTPException(status_code=403, detail="нет доступа к Inspector")
    return await _inspector_payload(cache, user, ctx, chat_id)


@speech_router.get("/speech/learning")
async def get_learning(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раздел «Обучение»: уроки опыта + реальные реакции на шутки (W4)."""
    _cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    payload = await _learning_payload(chat_id)
    payload["humor_feedback"]["can_manage"] = _library_can_edit(
        _cache, user, ctx, chat_id=chat_id)
    return payload


class HumorLearningAction(BaseModel):
    """Действия владельца по обучению юмора (SOUL-08.11)."""

    action: str = Field(max_length=32)          # pause|resume|approve|reject|reset
    lesson_id: str = Field(default="", max_length=64)
    version: int | None = None


@speech_router.post("/speech/learning/humor")
async def post_learning_humor(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: HumorLearningAction,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """pause/resume/approve/reject/reset-learning без потери данных."""
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422,
                            detail="нужен X-Chat-Id: обучение идёт по чатам")
    if not _library_can_edit(cache, user, ctx, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет права на управление обучением")
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    pg = _doc_pg(cache)
    action = str(body.action or "")
    if action in ("pause", "resume"):
        result = await humor_feedback.set_paused(db, int(chat_id),
                                                 action == "pause", pg=pg)
    elif action in ("approve", "reject"):
        if not body.lesson_id:
            raise HTTPException(status_code=422, detail="нужен lesson_id")
        result = await humor_feedback.lesson_action(
            db, int(chat_id), str(body.lesson_id), version=body.version,
            action=action)
    elif action == "reset":
        result = await humor_feedback.reset_learning(db, int(chat_id), pg=pg)
    else:
        raise HTTPException(status_code=422, detail="неизвестное действие")
    if not result.get("ok"):
        reason = str(result.get("reason") or "не выполнено")
        logger.warning("[speech] learning action not applied | action=%s | "
                       "reason=%s | error=%s", action, reason,
                       result.get("error"))
        # P0 PERSIST-FIX: реальная причина наружу человеческим языком;
        # инфраструктурный сбой — 503, а не 409 с кодом в лицо владельцу.
        status = 503 if reason == "write_error" else 409
        raise HTTPException(status_code=status,
                            detail=_learning_error_detail(reason))
    view = await _learning_payload(chat_id)
    view["humor_feedback"]["can_manage"] = True
    return {"ok": True, "action": action, "result": result, "learning": view}


@speech_router.post("/speech/try")
async def post_try(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    body: TryRequest,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """«Попробовать»: current vs candidate на одинаковых входах.

    По умолчанию ничего не отправляет в Telegram и не создаёт уроков; вызов
    модели — только по явному ``generate=true`` (один вызов на вариант).
    """
    cache, chat_id, ctx = await _access(request, user, x_chat_id)
    if not _can_view(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к речи")
    candidate = body.candidate if isinstance(body.candidate, dict) else {}
    current = await _preview_manifest(cache, chat_id, text=body.text,
                                      profile=body.profile)
    cand = None
    if candidate:
        cand = await _preview_manifest(cache, chat_id, text=body.text,
                                       profile=body.profile,
                                       candidate=candidate)
    from services import style_policy as sp
    preview_policy = await sp.effective_style_policy(int(chat_id or 0),
                                                    context="regular")
    style_pass = await sp.apply_style_policy(
        body.text, chat_id=0, policy=preview_policy, context="regular",
        record=False, emit_events=False, stage="preview")
    from services import response_extent as extent_mod
    from services import style_policy as sp2
    spans = sp2.segment(body.text)
    protected = [{"kind": span.kind, "text": _mask_text(
        body.text[span.start:span.end])[:200]}
        for span in spans if span.kind != "plain"][:10]
    out = {
        "text_masked": _mask_text(body.text),
        "scope": "chat" if chat_id is not None else "global",
        "chat_id": chat_id,
        "profile": body.profile,
        "current": current,
        "candidate": cand,
        "cost": {
            "current_tokens": current.get("tokens_total"),
            "candidate_tokens": (cand or {}).get("tokens_total"),
            "delta_tokens": ((cand or {}).get("tokens_total") or 0)
            - (current.get("tokens_total") or 0) if cand else None,
            "estimator": "тот же оценщик, что в композере (4 симв. ≈ 1 токен)",
        },
        "extent": {
            "values": list(getattr(extent_mod, "EXTENTS", ()) or ()),
            "response_plan_enabled": bool(
                extent_mod.response_plan_enabled()),
            "style_pass": style_pass.as_dict(),
            "style_text_masked": _mask_text(style_pass.text),
        },
        "facts": {
            "protected_spans": protected,
            "protected_count": len(protected),
            "note": ("Проверка сохранности: URL/код/JSON/цитаты/версии — "
                     "защищённые спаны; правила формы их не меняют "
                     "(exempted/conflict вместо ложного pass)."),
        },
        "strategy": {
            "layers_current": [t["layer"] for t in
                               (current.get("layers") or []) if t.get("rendered")],
            "layers_candidate": [t["layer"] for t in
                                 ((cand or {}).get("layers") or ())
                                 if t.get("rendered")],
            "conflicts_current": current.get("conflicts"),
            "conflicts_candidate": (cand or {}).get("conflicts"),
        },
        "delivery": {"telegram_send": False, "lessons_created": 0,
                     "note": "по умолчанию тест ничего не отправляет и не "
                             "создаёт постоянных уроков"},
        "generation": None,
    }
    if body.generate:
        out["generation"] = await _generate_variants(
            current, cand, body, chat_id)
    return out


async def _generate_variants(current: dict, cand: dict | None,
                             body: TryRequest, chat_id: int | None) -> dict:
    """Реальный вызов модели для вариантов (явное действие владельца)."""
    from config import settings
    from services import hot_config as hot
    from services.llm_client import LLMClient
    try:
        client = LLMClient(
            hot.get("models.llm_base_url", settings.LLM_BASE_URL),
            hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            body.chat_model or hot.get("models.llm_model_name",
                                       settings.LLM_MODEL_NAME),
            hot.get("models.embedding_model_name",
                    settings.EMBEDDING_MODEL_NAME),
        )
    except Exception:
        logger.warning("[speech] try generation client failed", exc_info=True)
        return {"ok": False, "reason": "client_unavailable"}
    out: dict = {"ok": True, "variants": {}}
    for name, variant in (("current", current), ("candidate", cand)):
        if variant is None:
            continue
        messages = [{"role": "system", "content": variant.get(
            "system_masked") or ""},
            {"role": "user", "content": body.text}]
        started = time.perf_counter()
        try:
            reply = await client.generate(messages, chat_id=chat_id,
                                          module="speech_ui",
                                          step="try_lab")
            out["variants"][name] = {
                "ok": True,
                "reply_masked": _mask_text(reply),
                "chars": len(reply or ""),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:
            out["variants"][name] = {"ok": False,
                                     "error": type(exc).__name__}
            out["ok"] = False
    out["note"] = ("вызовы реального провайдера (по одному на вариант), "
                   "отправки в Telegram нет, уроки не создаются")
    return out


__all__ = ["speech_router", "render_expression_text", "EXPRESSION_DOC_KEY"]
