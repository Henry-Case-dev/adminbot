"""ER-65 / ER-S42 / ER-09 — снимок РЕАЛЬНО отправляемых сегментов промптов (EVOL-B-PROMPTREG).

GENERATED ARTIFACT. Не редактировать руками: снимок перегенерируется
командой

    py -3 tools/er65_prompt_segment_snapshot.py --write

и проверяется на байтовую стабильность командой

    py -3 tools/er65_prompt_segment_snapshot.py --check

Что доказывает этот инструмент
------------------------------
1. Берёт **фактический payload**, который получает LLM на каждой стадии, не
   переписывая композицию: сценарии вызывают существующие швы сборки
   (`DirectChatService._plan_direct_l1`, `._l2_write_answer`,
   `._synthesize_direct_answer`, `FactCheckService.check_claim`,
   `plan_initiative_decision`, `generate_initiative_reply`), а снимок снимается
   на транспортной границе — в `llm.generate(messages, ...)` и в
   `chat_with_tools(llm, payload, tools=...)`. Тела писем/сообщений не
   копируются из констант вручную: система собирается самим кодом.
2. Для каждого сегмента фиксирует роль, точную длину в символах и в UTF-8
   байтах, sha256 (полный и первые 12), упорядоченный список блоков,
   покрывших сегмент, и остаток, который через именованный шов не
   атрибутируется (`unattributed`).
3. Фиксирует эффективные ревизии/печати канона: каждый вызов
   `prompt_style_blocks.resolve_prompt` / `prompt_registry.resolve_chat_speech`
   пишется вместе с `block_id`, `fac:<sha12>` заводской редакции, `act:<sha12>`
   действующей редакции и позицией текста в сегменте.
4. Показывает деградированный путь: детерминированный fallback-план при
   отказе L1 и пересборку L2-пакета под окно fallback-модели
   (`build_l2_fallback_adapter`, оба исхода — `fallback_repacked` и
   `fallback_window_exceeded`).
5. Детерминированность: снимок снимается ДВАЖДЫ в независимых процессах;
   совпадение байтов обязательно, иначе инструмент падает.

Чего этот инструмент НЕ доказывает
----------------------------------
* Реальный ответ модели: сети нет (сокет блокируется на время прогона),
  провайдер не вызывается, поэтому качество/соблюдение инструкций и
  фактическая отправка (HTTP 200 у провайдера, usage) не проверяются.
* Персистентные слои: PG недоступен, `hot`/`chat_params` кэши обнулены —
  снимается ЗАВОДСКОЙ канон (`source="default"`), а не переопределения
  владельца из бота. Пользовательский override меняет только текст блока,
  структуру сегмента — нет.
* Персональные блоки личности из PG (`bot_persona`) в сценариях «как ход» не
  поднимаются (gate `PERSONA_ENABLED=False`); слой identity покрыт отдельным
  сценарным сегментом с явно переданным `character_block`.
* Композер (`flags.unified_composer_enabled`) снят в заводском состоянии OFF —
  это действующий боевой режим; ON-контур (манифест слоёв) здесь не снимается.

TEST-LIFECYCLE: CONTRACT owner=EVOL-016/ER-65 (снимок отправленных сегментов)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE_DIR = os.path.join(REPO_ROOT, "plans", "features", "evol",
                            "evidence", "er65")
JSON_NAME = "sent-segments.json"
MD_NAME = "sent-segments.md"
SCHEMA = "er65-sent-segments-v1"
REGEN_COMMAND = "py -3 tools/er65_prompt_segment_snapshot.py --write"

#: Модули, чьи байты определяют снимок (доказательство «какой код собирал»).
SOURCE_FILES = (
    "services/direct_chat_service.py",
    "services/direct_l1.py",
    "services/direct_execution.py",
    "services/payload_builder.py",
    "services/chat_prompts.py",
    "services/prompt_style_blocks.py",
    "services/prompt_registry.py",
    "services/prompt_composer.py",
    "services/response_extent.py",
    "services/factcheck_service.py",
    "services/factcheck_prompts.py",
    "services/negative_constraints.py",
)


# ── фикстуры входа (данные, не промпты) ────────────────────────────────────

CHAT_ID = -1001234567890
BOT_ID = 12345
NOW_LINE = "[Текущее время в чате: 02.11.2026 10:05]"
QUERY = "почему после релиза 2.58.147 упал сервис"
WINDOW = [
    {"user_id": 10, "author_name": "Вася", "timestamp": 1700000000,
     "media_type": "text", "reply_to_id": None, "tg_message_id": 50,
     "text": "вчера обсуждали релиз 2.58.147, обещали проверить логи"},
    {"user_id": 77, "author_name": "Аня", "timestamp": 1700000060,
     "media_type": "text", "reply_to_id": None, "tg_message_id": 51,
     "text": "после релиза сервис отвечал 502"},
]
RAG_TEXT = "RAG-факт: релиз 2.58.147 выкатили 02.11.2026, отката не было"
CHARACTER_BLOCK = ("<Persona>\nИмя: Бот. Характер: язвительный, прямой.\n</Persona>"
                   "\n\n<Character_Rules>\nНе раскрывать, что ты ИИ.\n"
                   "</Character_Rules>")
STYLE_DIRECTIVES = ("<Style_Requests>\nПиши без канцелярита.\n</Style_Requests>")
LESSONS_BLOCK = ("<Verified_Lessons>\n- не обещать сроков\n</Verified_Lessons>")
SPEECH_BLOCK = ("<Speech_Understanding>\nact=assert clarify=assume\n"
                "</Speech_Understanding>")
EXTRA_USER_BLOCKS = ["<Global_Context>\nфон: обсуждали релиз 2.58.147\n"
                     "</Global_Context>"]
TOOL_EVIDENCE = ("[tool: execute_web_search out_chars=812]\n"
                 "лог nginx: upstream 502 на /healthz 02.11.2026 09:41")
SEARCH_RESULTS = ("[поиск] 2.58.147 — релиз 02.11.2026; инцидентов в статусе "
                  "нет; /healthz отвечал 502 в 09:41")
FACTCHECK_CLAIM = "после релиза 2.58.147 сервис отвечал 502"

PLAN_JSON = json.dumps({
    "action": "reply", "response_act": "answer", "extent": "normal",
    "tone": "inherit", "structure": "chat", "delivery_hint": "plain",
    "tool_policy": "none", "capabilities_needed": [],
    "needs_clarification": False, "confidence": 0.9, "reaction": None,
    "emotional_mirroring": "none"}, ensure_ascii=False)
PLAN_JSON_TOOLS = json.dumps({
    "action": "reply", "response_act": "answer", "extent": "normal",
    "tone": "inherit", "structure": "chat", "delivery_hint": "plain",
    "tool_policy": "auto", "capabilities_needed": ["web_search"],
    "needs_clarification": False, "confidence": 0.9, "reaction": None,
    "emotional_mirroring": "none"}, ensure_ascii=False)
SYNTH_STAGE1_JSON = json.dumps({
    "user_question": "почему упал сервис",
    "answer_outline": "сначала причина, затем следствия",
    "facts": [{"topic": "лог", "finding": "в логе HTTP 502",
               "source": "tool", "confidence": "medium"}],
    "limitations": [], "response_mode": "serious"}, ensure_ascii=False)
FACTCHECK_STAGE1_JSON = json.dumps({
    "claim": FACTCHECK_CLAIM,
    "verdict": "частично подтверждено: 502 был, причина не установлена",
    "findings": [{"assertion": "сервис отвечал 502 после релиза",
                  "status": "true", "human_time": "02.11.2026",
                  "author": "Аня", "evidence": "лог nginx: upstream 502"}],
    "response_mode": "serious"}, ensure_ascii=False)
INITIATIVE_ROW = {
    "chat_id": CHAT_ID, "kind": "open_dispute", "origin": "observer_opportunity",
    "goal": "обсуждение инцидента после релиза",
    "addressee_user_id": 77,
    "rationale": "Аня прямо спросила, что случилось",
}


# ── утилиты ────────────────────────────────────────────────────────────────

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha12(text: str) -> str:
    return sha256(text)[:12]


def _section_split(chunk: str):
    """Делит кусок по канонному формату секций ``[ИМЯ]\\nтело``."""
    parts = re.split(r"\n\n(?=\[[^\]\n]{2,60}\]\n)", chunk)
    out = []
    for part in parts:
        if not part:
            continue
        head = part.split("\n", 1)[0]
        label = (f"section:{head}" if head.startswith("[") and head.endswith("]")
                 else "")
        out.append((part, "section", label or "text"))
    return out


def _tag_split(chunk: str):
    """Делит кусок по XML-тегам верхнего уровня (реальные блоки payload)."""
    parts = re.split(r"\n\n(?=<[A-Za-z_][A-Za-z0-9_]*>)", chunk)
    out = []
    for part in parts:
        if not part:
            continue
        match = re.match(r"<([A-Za-z_][A-Za-z0-9_]*)>", part)
        out.append((part, "tag", f"tag:{match.group(1)}" if match else "text"))
    return out


def _structured_split(chunk: str):
    """Рефайн неатрибутированного куска: разделитель → префикс → секции → теги."""
    if not chunk.strip("\n"):
        return [(chunk, "separator", "separator")]
    if chunk.startswith("\n\n"):
        return [("\n\n", "separator", "separator")] + _structured_split(chunk[2:])
    # Внутренний известный заголовок payload'а (например MCA-07 срез перед
    # блоком синтеза) — режем по нему, а не валим в один кусок.
    inner = []
    for prefix, _label in PAYLOAD_PREFIXES:
        found = chunk.find(prefix)
        if found > 0:
            inner.append(found)
    if inner:
        cut = min(inner)
        return _structured_split(chunk[:cut]) + _structured_split(chunk[cut:])
    for prefix, label in PAYLOAD_PREFIXES:
        if chunk.startswith(prefix):
            return [(chunk, "payload", label)]
    for splitter in (_section_split, _tag_split):
        pieces = splitter(chunk)
        if len(pieces) > 1:
            out = []
            for text, kind, label in pieces:
                if label == "text" or kind == "unattributed":
                    out.append((text, "unattributed", ""))
                else:
                    out.append((text, kind, label))
            return out
    return [(chunk, "unattributed", "")]


def partition(text: str, candidates) -> tuple[list, list, list]:
    """Упорядоченное разбиение сегмента на блоки без переписывания текста.

    ``candidates`` — реальные значения швов (``(label, value, kind)``) в
    порядке, в котором их собирал КОД. Жадный поиск берёт кандидата, который
    начинается раньше остальных в фактических байтах, поэтому разбиение идёт в
    порядке текста. Затем проверяется, что порядок текста совпадает с порядком
    объявления в коде: расхождение попадает в ``order_violations``.
    """
    indexed = [(index, label, value, kind)
               for index, (label, value, kind) in enumerate(candidates) if value]
    used: set[int] = set()
    spans = []
    matched_order = []
    pos = 0
    while True:
        best = None
        for index, label, value, kind in indexed:
            if index in used:
                continue
            span = _match_span(text, value, pos)
            if span is None:
                continue
            if best is None or span[0] < best[0]:
                best = (span[0], span[1], index, label, value, kind)
        if best is None:
            break
        found, found_end, index, label, value, kind = best
        used.add(index)
        if found > pos:
            spans.append((pos, found, None, None, None))
        spans.append((found, found_end, label, kind, index))
        matched_order.append((index, label))
        pos = found_end
    if pos < len(text):
        spans.append((pos, len(text), None, None, None))
    violations = []
    previous = -1
    for index, label in matched_order:
        if index < previous:
            violations.append({"label": label, "declared_index": index,
                               "after_declared_index": previous})
        previous = max(previous, index)
    blocks = []
    for start, end, label, kind, declared in spans:
        chunk = text[start:end]
        if label is None:
            for piece, piece_kind, piece_label in _structured_split(chunk):
                blocks.append({"label": piece_label, "kind": piece_kind,
                               "offset": start, "chars": len(piece),
                               "declared_index": -1,
                               "sha256_12": sha12(piece)})
                start += len(piece)
            continue
        blocks.append({"label": label, "kind": kind, "offset": start,
                       "chars": len(chunk), "declared_index": declared,
                       "sha256_12": sha12(chunk)})
    for block in blocks:
        block["bytes_utf8"] = len(block_text(text, block).encode("utf-8"))
    seen = [{"label": label, "kind": kind, "chars": len(value),
             "sha256_12": sha12(value), "found_at": text.find(value),
             "used_in_partition": index in used}
            for index, label, value, kind in indexed]
    return blocks, seen, violations


def block_text(text: str, block: dict) -> str:
    return text[block["offset"]:block["offset"] + block["chars"]]


#: Известные заголовки payload'ов (метка ставится на реальные байты).
PAYLOAD_PREFIXES = (
    ("КОНТЕКСТ ДИАЛОГА (не терять):", "payload:mca07_bundle_slice"),
    ("СПРАВКА (JSON):", "payload:stage2_reference_json"),
    ("АНАЛИЗ (JSON):", "payload:factcheck_analysis_json"),
    ("ВЕРДИКТ (JSON):", "payload:verdict_json"),
    ("СООБЩЕНИЕ ЮЗЕРА:", "payload:synthesis_input"),
    ("<Tool_Evidence>", "payload:tool_evidence_block"),
    ("[CAPACITY] Контекст не поместился", "payload:l2_capacity_note"),
    ("[…обрезано под окно fallback]", "payload:l2_fallback_truncation_marker"),
)

#: Плейсхолдеры шаблонов (`{max_symbols}`), подставляемые на сборке.
_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def _match_span(text: str, value: str, pos: int):
    """Позиция кандидата в тексте; плейсхолдеры шаблона = подстановка.

    ``{max_symbols}`` и подобные подставляются на сборке, поэтому литеральный
    поиск шаблона не сработал бы. Границы матча — фактический текст сегмента.
    """
    parts = [part for part in _PLACEHOLDER.split(value)]
    if len(parts) == 1:
        found = text.find(value, pos)
        return None if found < 0 else (found, found + len(value))
    start = None
    cursor = pos
    for part in parts:
        if not part:
            continue
        found = text.find(part, cursor)
        if found < 0:
            return None
        if start is None:
            start = found
        cursor = found + len(part)
    return None if start is None else (start, cursor)


def message_record(text: str, index: int, role: str, candidates) -> dict:
    blocks, seen, violations = partition(text, candidates)
    attributed = sum(b["chars"] for b in blocks
                     if b["kind"] not in ("unattributed", "separator"))
    return {
        "index": index,
        "role": role,
        "chars": len(text),
        "bytes_utf8": len(text.encode("utf-8")),
        "sha256": sha256(text),
        "sha256_12": sha12(text),
        "text": text,
        "blocks": blocks,
        "block_order_in_text": [b["label"] for b in blocks],
        "order_violations": violations,
        "unattributed_chars": len(text) - attributed,
        "attribution_ratio": (round(attributed / len(text), 4) if text else 1.0),
        "candidates_seen": seen,
    }


# ── нейтрализация окружения ────────────────────────────────────────────────

class _ResolverRecorder:
    """Запись реальных резолвов канона (кто именно ушёл в payload)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._busy = False
        #: Уникальные редакции канона по sha12 (текст хранится один раз).
        self.revisions: dict[str, dict] = {}

    def reset(self) -> None:
        self.rows = []

    # --- общая запись -----------------------------------------------------
    def note(self, seam: str, key: str, text: str, default: str,
             source: str = "") -> None:
        if self._busy:
            return
        self._busy = True
        try:
            from services import prompt_registry as pr
            spec = pr.block_for(key)
            block_id = spec.block_id if spec is not None else ""
            seal = pr.FACTORY_REVISION_SEALS.get(block_id) if block_id else None
            label = pr.FACTORY_REVISION_LABELS.get(block_id, "") if block_id else ""
            row = {
                "seam": seam,
                "key": key,
                "block_id": block_id,
                "chars": len(text),
                "sha256_12": sha12(text),
                "revision": (pr.ACTIVE_PREFIX + sha12(text)) if text else "",
                "factory_revision": (pr.factory_revision(block_id)
                                     if block_id else ""),
                "factory_label": label,
                "factory_seal": (seal[1] if seal else ""),
                "source": source or ("code_default"
                                     if text == default else "resolved"),
                "is_code_default": text == default,
                "text": text,
            }
        finally:
            self._busy = False
        self.rows.append(row)
        key = row["sha256_12"]
        if key and key not in self.revisions:
            self.revisions[key] = {"key": row["key"],
                                   "block_id": row["block_id"],
                                   "chars": row["chars"],
                                   "revision": row["revision"],
                                   "factory_revision": row["factory_revision"],
                                   "factory_seal": row["factory_seal"],
                                   "source": row["source"],
                                   "text": row["text"]}

    # --- кандидаты для атрибуции -----------------------------------------
    def candidates(self):
        return [(f"prompt:{row['key']}", row["text"], "canon")
                for row in self.rows]

    def view(self, message_text: str) -> list:
        out = []
        for row in self.rows:
            text = row["text"]
            span = _match_span(message_text, text, 0) if text else None
            out.append({
                "seam": row["seam"],
                "key": row["key"],
                "block_id": row["block_id"],
                "chars": row["chars"],
                "sha256_12": row["sha256_12"],
                "revision": row["revision"],
                "factory_revision": row["factory_revision"],
                "factory_label": row["factory_label"],
                "factory_seal": row["factory_seal"],
                "source": row["source"],
                "is_code_default": row["is_code_default"],
                "found_in_segment": span is not None,
                "found_at": span[0] if span else -1,
            })
        return out


class _ModePartsRecorder:
    """Запись ``resolve_mode_parts`` — реального режимного/extent-блока."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def reset(self) -> None:
        self.rows = []

    def add(self, base: str, block: str, mode: str) -> None:
        self.rows.append({"base": base, "block": block, "mode": mode})

    def candidates(self):
        """Только режимный/extent-блок: база дублирует резолв канона."""
        return [(f"mode_or_extent_block[{index}]", row["block"], "canon")
                for index, row in enumerate(self.rows) if row["block"]]


class _BlockRecorder:
    """Запись блоков, собранных кодом не через резолвер (критика и т.п.)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def reset(self) -> None:
        self.rows = []

    def add(self, label: str, text: str) -> None:
        if text:
            self.rows.append({"label": label, "text": text})

    def candidates(self):
        return [(f"block:{row['label']}", row["text"], "canon")
                for row in self.rows]


class _AdapterRecorder:
    """Запись реального вызова `build_l2_fallback_adapter` из L2-шва.

    Хранит РОВНО те входы, с которыми адаптер создал сам L2 Writer
    (`system`, `parts`, `evidence`, `query`), поэтому пересборка под другое
    окно fallback-модели идёт с боевыми значениями, без копирования логики.
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def reset(self) -> None:
        self.rows = []

    def add(self, row: dict) -> None:
        self.rows.append(row)


class _ExtentRecorder:
    """Запись ``response_extent.render_extent_block`` (блок полноты плана)."""

    def __init__(self) -> None:
        self.rows: list[str] = []

    def reset(self) -> None:
        self.rows = []

    def add(self, text: str) -> None:
        if text:
            self.rows.append(text)

    def candidates(self):
        return [(f"extent_block[{index}]", text, "canon")
                for index, text in enumerate(self.rows)]


RESOLVER = _ResolverRecorder()
MODEPARTS = _ModePartsRecorder()
BLOCKS = _BlockRecorder()
EXTENT = _ExtentRecorder()
ADAPTERS = _AdapterRecorder()

#: Входные слои, которые харнесс фиксирует сам (не инструкции, а данные хода).
def _no_meta_closing() -> str:
    """Заводской закрывающий блок Writer'а (реальная константа, не копия)."""
    from services.prompt_style_blocks import NO_META_CLOSING_TEXT
    return str(NO_META_CLOSING_TEXT or "").strip()


class _flags:
    """Временная подмена флагов Settings (как monkeypatch в тестах)."""

    def __init__(self, **values) -> None:
        self.values = values
        self.saved = {}

    def __enter__(self):
        from config.settings import Settings
        for key, value in self.values.items():
            self.saved[key] = getattr(Settings, key, _MISSING)
            setattr(Settings, key, value)
        return self

    def __exit__(self, *exc):
        from config.settings import Settings
        for key, value in self.saved.items():
            if value is _MISSING:
                try:
                    delattr(Settings, key)
                except AttributeError:
                    pass
            else:
                setattr(Settings, key, value)
        return False


_MISSING = object()


class _no_network:
    """Доказательство «без сети»: любой connect падает."""

    def __enter__(self):
        self._orig = socket.socket.connect

        def _blocked(*_a, **_k):
            raise RuntimeError("network blocked by er65 snapshot harness")

        socket.socket.connect = _blocked
        socket.socket.connect_ex = _blocked
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._orig
        try:
            del socket.socket.connect_ex
        except AttributeError:
            pass
        return False


def _neutralize() -> None:
    """PG/телеметрия выключены, канон — заводской (детерминированный)."""
    from services import chat_params, hot_config as hot
    from services import prompt_composer as pcomp
    from services import prompt_registry as pr
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pcomp.reset_state()
    pr.reset_cache()
    from services import agentic_events, mca_events, usage_events
    usage_events.record = lambda *a, **k: None
    agentic_events.emit_agentic_event = lambda *a, **k: None
    mca_events.emit_mca_event = lambda *a, **k: None
    from services import direct_chat_service as dcs
    dcs.emit_agentic_event = lambda *a, **k: None
    dcs.record_context_usage = lambda *a, **k: None
    RESOLVER.reset()
    MODEPARTS.reset()
    BLOCKS.reset()
    EXTENT.reset()
    ADAPTERS.reset()
    _install_recorders()


_RECORDERS_INSTALLED = False


def _install_recorders() -> None:
    global _RECORDERS_INSTALLED
    if _RECORDERS_INSTALLED:
        return
    from services import prompt_registry as pr
    from services import prompt_style_blocks as psb

    orig_resolve = psb.resolve_prompt

    def resolve_prompt(pg_key, code_default):
        text = orig_resolve(pg_key, code_default)
        RESOLVER.note("prompt_style_blocks.resolve_prompt", pg_key, text,
                      code_default)
        return text

    orig_resolve_src = psb.resolve_prompt_with_source

    def resolve_prompt_with_source(pg_key, code_default):
        text, source = orig_resolve_src(pg_key, code_default)
        RESOLVER.note("prompt_style_blocks.resolve_prompt_with_source",
                      pg_key, text, code_default, source=source)
        return text, source

    orig_mode_parts = psb.resolve_mode_parts

    def resolve_mode_parts(base_prompt, response_mode="", *, extent_block="",
                           modes_enabled=True):
        candidate, base, block = orig_mode_parts(
            base_prompt, response_mode, extent_block=extent_block,
            modes_enabled=modes_enabled)
        MODEPARTS.add(base, block, candidate)
        return candidate, base, block

    orig_chat_speech = pr.resolve_chat_speech

    async def resolve_chat_speech(pg_key, code_default, *, chat_id):
        text, source = await orig_chat_speech(pg_key, code_default,
                                              chat_id=chat_id)
        RESOLVER.note("prompt_registry.resolve_chat_speech", pg_key, text,
                      code_default, source=source)
        return text, source

    from services import factcheck_prompts as fcp
    orig_critique = fcp.build_critique_section_block

    def build_critique_section_block(policy, *, directive=""):
        text = orig_critique(policy, directive=directive)
        BLOCKS.add(f"factcheck_critique_section({policy})", text)
        return text

    from services import response_extent as rex
    orig_extent = rex.render_extent_block

    def render_extent_block(plan=None, *args, **kwargs):
        text = orig_extent(plan, *args, **kwargs)
        EXTENT.add(text)
        return text

    from services import direct_execution as dx_mod
    orig_adapter = dx_mod.build_l2_fallback_adapter

    def build_l2_fallback_adapter(*, system, parts, evidence, query,
                                  fallback_budget_tokens,
                                  on_capacity_reason=None):
        adapter = orig_adapter(
            system=system, parts=parts, evidence=evidence, query=query,
            fallback_budget_tokens=fallback_budget_tokens,
            on_capacity_reason=on_capacity_reason)
        ADAPTERS.add({"system": system, "parts": list(parts),
                      "evidence": evidence, "query": query,
                      "budget": int(fallback_budget_tokens),
                      "adapter": adapter})
        return adapter

    psb.resolve_prompt = resolve_prompt
    psb.resolve_prompt_with_source = resolve_prompt_with_source
    psb.resolve_mode_parts = resolve_mode_parts
    pr.resolve_chat_speech = resolve_chat_speech
    fcp.build_critique_section_block = build_critique_section_block
    rex.render_extent_block = render_extent_block
    dx_mod.build_l2_fallback_adapter = build_l2_fallback_adapter
    _rebind_imported_names({
        "resolve_prompt": orig_resolve,
        "resolve_prompt_with_source": orig_resolve_src,
        "resolve_mode_parts": orig_mode_parts,
        "resolve_chat_speech": orig_chat_speech,
        "build_critique_section_block": orig_critique,
        "render_extent_block": orig_extent,
        "build_l2_fallback_adapter": orig_adapter,
    }, {
        "resolve_prompt": resolve_prompt,
        "resolve_prompt_with_source": resolve_prompt_with_source,
        "resolve_mode_parts": resolve_mode_parts,
        "resolve_chat_speech": resolve_chat_speech,
        "build_critique_section_block": build_critique_section_block,
        "render_extent_block": render_extent_block,
        "build_l2_fallback_adapter": build_l2_fallback_adapter,
    })
    _RECORDERS_INSTALLED = True


def _rebind_imported_names(originals: dict, replacements: dict) -> None:
    """Перевязать имена, импортированные в модули-потребители.

    Швы сборки делают `from services.prompt_style_blocks import resolve_prompt`,
    поэтому патч модуля-источника сам по себе payload не наблюдает: имя уже
    связано в `direct_chat_service`/`factcheck_service`. Перевязываем ровно те
    атрибуты, которые всё ещё указывают на исходную функцию (чужой патч — не
    наш объект правки).
    """
    for module_name, module in list(sys.modules.items()):
        if module is None or not module_name.startswith(("services", "config")):
            continue
        for attr, original in originals.items():
            if getattr(module, attr, None) is original:
                setattr(module, attr, replacements[attr])


# ── фиктивные границы (сеть/Telegram/БД) ───────────────────────────────────

class FakeLLM:
    """Транспортная граница: payload записывается, ответ фиксирован."""

    def __init__(self, *, l1="", l2="", single="", stage1="", stage2="",
                 l1_error=None):
        self.l1 = l1
        self.l2 = l2
        self.single = single
        self.stage1 = stage1
        self.stage2 = stage2
        self.l1_error = l1_error
        self.calls: list[dict] = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append({
            "module": module,
            "step": step,
            "messages": [dict(m) for m in messages],
            "kwargs": {k: v for k, v in kwargs.items()
                       if k != "fallback_payload_adapter"},
            "has_fallback_adapter": kwargs.get("fallback_payload_adapter")
            is not None,
            "fallback_adapter": kwargs.get("fallback_payload_adapter"),
        })
        if step == "l1_planner" and self.l1_error is not None:
            raise self.l1_error
        if step == "l1_planner":
            return self.l1
        if step == "l2_writer":
            return self.l2
        if step == "stage1":
            return self.stage1
        if step == "stage2":
            return self.stage2
        return self.single

    def last(self, step: str) -> dict | None:
        found = [c for c in self.calls if c["step"] == step]
        return found[-1] if found else None


class FakeMemory:
    def __init__(self, window=None, rag="") -> None:
        self.window = list(window or [])
        self.rag = rag

    async def get_window_messages(self, chat_id):
        return self.window

    async def get_rag_context(self, chat_id, query, **kwargs):
        return self.rag

    async def get_rag_facts(self, chat_id, query, **kwargs):
        return [("chat_history", self.rag, None)] if self.rag else []

    async def rerank_rag_facts(self, query, facts):
        return list(facts)

    async def memorize_facts(self, *args, **kwargs):
        return None

    async def memorize_self_reply(self, chat_id, essence):
        return 1

    async def retrieve_fact_candidates(self, *args, **kwargs):
        return []


class FakeDB:
    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return None

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return None

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def get_smart_raw(self, chat_id, older_than_ts=None, limit=1):
        return []

    async def search_messages_fts(self, *args, **kwargs):
        return []

    async def search_graph_facts_fts(self, *args, **kwargs):
        return []


class FakeToolRouter:
    """Реальный шов dispatch: детерминированный исполнитель инструментов."""

    def __init__(self, default="[tool] лог nginx: upstream 502") -> None:
        self.default = default
        self.dispatched: list[dict] = []

    async def dispatch(self, name, arguments, ctx):
        self.dispatched.append({"tool": name,
                                "arguments": sorted((arguments or {}).keys())})
        return self.default


def _tg_user(user_id=10, first_name="Вася"):
    user = MagicMock()
    user.id = user_id
    user.first_name = first_name
    user.last_name = "Пупкин"
    user.username = "vasya"
    return user


def _tg_message(text=QUERY, message_id=100):
    message = MagicMock()
    message.text = text
    message.caption = None
    message.message_id = message_id
    message.chat = MagicMock()
    message.chat.id = CHAT_ID
    message.chat.type = "supergroup"
    message.from_user = _tg_user()
    message.reply_to_message = None
    message.web_page = None
    for attr in ("photo", "video", "video_note", "voice", "audio",
                 "animation", "sticker", "document"):
        setattr(message, attr, None)
    return message


def _service(llm, router=None):
    from services import direct_chat_service as dcs
    from services.summary_aliases import AliasResolver
    service = dcs.DirectChatService(
        FakeMemory(window=WINDOW, rag=RAG_TEXT), FakeDB(), llm,
        AliasResolver("{}"), bot_id=BOT_ID, bot_username="test_bot",
        tool_router=router)
    service._image_pre_gate_block = AsyncMock(return_value=None)
    service._dig_pre_gate_block = AsyncMock(return_value=None)
    service._send_direct_answer = AsyncMock(return_value=999)
    service.remember_bot_reply = AsyncMock()
    # Время хода — входные данные, а не инструкция: фиксируем, иначе payload
    # недетерминирован по часам (`_chat_time_line` читает текущее время).
    service._chat_time_line = AsyncMock(return_value=NOW_LINE)
    return service, dcs


def _bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    return bot


# ── разбор захваченных payload'ов в записи стадий ──────────────────────────

#: Ожидаемые канон-ключи по стадии (что именно обязано доехать до модели).
EXPECTED_PROMPT_KEYS = {
    "direct.l1_planner": ("prompts.direct_l1_planner_system_prompt",),
    "direct.l1_planner.tools": ("prompts.direct_l1_planner_system_prompt",),
    "direct.l2_writer.direct": ("prompts.direct_chat_verbalizer_system_prompt",),
    "direct.l2_writer.tool_evidence":
        ("prompts.direct_chat_verbalizer_system_prompt",),
    "direct.l2_writer.deterministic_fallback_plan":
        ("prompts.direct_chat_verbalizer_system_prompt",),
    "direct.tool_phase.model_driven": ("prompts.direct_chat_system_prompt",),
    "direct.single.legacy_no_tools": ("prompts.direct_chat_system_prompt",),
    "direct.system2.stage1":
        ("prompts.direct_chat_synthesizer_system_prompt",),
    "direct.system2.stage2":
        ("prompts.direct_chat_verbalizer_system_prompt",),
    "direct.l2_writer.layered":
        ("prompts.direct_chat_verbalizer_system_prompt",),
    "direct.l2_writer.fallback_model_repack":
        ("prompts.direct_chat_verbalizer_system_prompt",),
    "direct.l2_writer.fallback_model_capacity":
        ("prompts.direct_chat_verbalizer_system_prompt",),
    "factcheck.single": ("prompts.factcheck_system_prompt",
                         "prompts.factcheck_critique_directive"),
    "factcheck.stage1_analyst": ("prompts.factcheck_analyst_system_prompt",),
    "factcheck.stage2_verbalizer":
        ("prompts.factcheck_verbalizer_system_prompt",),
    "initiative.l1_planner": ("prompts.direct_l1_planner_system_prompt",),
    "initiative.l2_writer": ("prompts.direct_chat_verbalizer_system_prompt",),
}


def _stage(*, stage_id: str, title: str, call_site: str, module: str,
           step: str, messages, extra_candidates=(), notes=(),
           tools=None, flag_state=None, payload_kwargs=None) -> dict:
    """Собрать запись стадии из фактических messages транспортной границы."""
    ordered = list(RESOLVER.candidates()) + list(MODEPARTS.candidates()) \
        + list(EXTENT.candidates()) + list(BLOCKS.candidates()) \
        + [("layer:time_line", NOW_LINE, "layer")] + list(extra_candidates) \
        + [("canon:no_meta_closing", _no_meta_closing(), "canon")]
    candidates = []
    seen_values = set()
    for label, value, kind in ordered:
        if not value or value in seen_values:
            continue
        seen_values.add(value)
        candidates.append((label, value, kind))
    records = []
    for index, item in enumerate(messages):
        text = str(item.get("content") or "")
        records.append(message_record(text, index, str(item.get("role") or ""),
                                      candidates))
    joined = "\n".join(str(m.get("content") or "") for m in messages)
    resolutions = RESOLVER.view(joined)
    expected_keys = tuple(EXPECTED_PROMPT_KEYS.get(stage_id, ()))
    expected_found = {}
    for key in expected_keys:
        rows = [row for row in resolutions if row["key"] == key]
        expected_found[key] = bool(rows) and any(
            row["found_in_segment"] for row in rows)
    stage = {
        "stage_id": stage_id,
        "title": title,
        "call_site": call_site,
        "llm": {"module": module, "step": step},
        "messages": records,
        "segments": len(records),
        "order_violations": [violation for record in records
                             for violation in record["order_violations"]],
        "expected_prompt_keys": list(expected_keys),
        "expected_prompt_keys_found": expected_found,
        "expected_prompt_keys_all_found": all(expected_found.values())
        if expected_found else True,
        "total_chars": sum(r["chars"] for r in records),
        "total_bytes_utf8": sum(r["bytes_utf8"] for r in records),
        "stage_sha256": sha256("\n".join(
            f"{r['index']}:{r['role']}:{r['sha256']}" for r in records)),
        "system_chars": next((r["chars"] for r in records
                              if r["role"] == "system"), 0),
        "user_chars": next((r["chars"] for r in records
                            if r["role"] == "user"), 0),
        "prompt_resolutions": resolutions,
        "payload_kwargs": sorted(payload_kwargs or ()),
        "notes": list(notes),
        "flags": dict(flag_state or {}),
    }
    if tools is not None:
        stage["tools"] = {
            "count": len(tools),
            "names": [t["function"]["name"] for t in tools
                      if isinstance(t, dict) and t.get("function")],
            "schemas_sha256": sha256(json.dumps(tools, ensure_ascii=False,
                                                sort_keys=True)),
        }
    return stage


def _turn_stage(llm, step, *, stage_id, title, call_site,
                module="direct_chat", extra_candidates=(), notes=(),
                flag_state=None) -> dict:
    call = llm.last(step)
    if call is None:
        raise RuntimeError(f"{stage_id}: LLM-вызов step={step!r} не состоялся")
    return _stage(stage_id=stage_id, title=title, call_site=call_site,
                  module=module, step=step, messages=call["messages"],
                  extra_candidates=extra_candidates, notes=notes,
                  flag_state=flag_state,
                  payload_kwargs=tuple(call["kwargs"]))


# ── сценарии ───────────────────────────────────────────────────────────────

async def _scenario_turn_l1_direct() -> list:
    from services import direct_l1 as _l1
    llm = FakeLLM(l1=PLAN_JSON, l2="ответ без инструментов")
    service, dcs = _service(llm)
    with _flags(DIRECT_L1_ENABLED=True, DIRECT_DECISION_MAKING_ENABLED=False,
                PERSONA_ENABLED=False):
        await service.handle(_bot(), _tg_message(), _tg_message().from_user)
    plan = _l1.parse_l1_plan(PLAN_JSON)
    flags = {"DIRECT_L1_ENABLED": True, "DIRECT_DECISION_MAKING_ENABLED": False,
             "PERSONA_ENABLED": False}
    return [
        _turn_stage(llm, "l1_planner",
                    stage_id="direct.l1_planner",
                    title="L1 Planner (плановый JSON, Direct-ход)",
                    call_site=("services/direct_chat_service.py::"
                               "DirectChatService._plan_direct_l1 (messages@5368)"),
                    flag_state=flags,
                    notes=["system = resolve_prompt(prompts.direct_l1_planner_system_prompt); "
                           "user = direct_l1.build_l1_context(...)"],
                    extra_candidates=[
                        ("l1_context_persona_frame", "", "layer"),
                    ]),
        _turn_stage(llm, "l2_writer",
                    stage_id="direct.l2_writer.direct",
                    title="L2 Writer — прямой ответ без инструментов",
                    call_site=("services/direct_chat_service.py::"
                               "DirectChatService._l2_write_answer (messages@6972)"),
                    flag_state=flags,
                    notes=["plan_block и user-блоки приходят в Writer из "
                           "реальной сборки хода; evidence пуст (тулов нет)"],
                    extra_candidates=[("plan_block(plan)",
                                       _plan_block_for(plan), "layer")]),
    ]


async def _scenario_turn_l1_tools() -> list:
    from services import direct_l1 as _l1
    llm = FakeLLM(l1=PLAN_JSON_TOOLS, l2="ответ с инструментальным evidence")
    router = FakeToolRouter()
    service, dcs = _service(llm, router)
    with _flags(DIRECT_L1_ENABLED=True, DIRECT_DECISION_MAKING_ENABLED=False,
                PERSONA_ENABLED=False):
        await service.handle(_bot(), _tg_message(), _tg_message().from_user)
    plan = _l1.parse_l1_plan(PLAN_JSON_TOOLS)
    flags = {"DIRECT_L1_ENABLED": True, "DIRECT_DECISION_MAKING_ENABLED": False,
             "PERSONA_ENABLED": False}
    writer = _turn_stage(llm, "l2_writer",
                         stage_id="direct.l2_writer.tool_evidence",
                         title="L2 Writer — после инструментальной фазы (Tool_Evidence)",
                         call_site=("services/direct_chat_service.py::"
                                    "DirectChatService._l2_write_answer (messages@6972)"),
                         flag_state=flags,
                         notes=["инструментальная фаза детерминированная "
                                "(0 LLM-вызовов): _l1_tool_phase → "
                                "_dx.run_simple_tools; пакет evidence уходит "
                                "в Writer блоком <Tool_Evidence>"],
                         extra_candidates=[("plan_block(plan)",
                                            _plan_block_for(plan), "layer")])
    writer["tools"] = {"count": 0, "names": [],
                       "note": "инструментальная фаза LLM-payload не отправляет "
                               "(детерминированный исполнитель)"}
    return [
        _turn_stage(llm, "l1_planner",
                    stage_id="direct.l1_planner.tools",
                    title="L1 Planner — план с capabilities_needed=web_search",
                    call_site=("services/direct_chat_service.py::"
                               "DirectChatService._plan_direct_l1 (messages@5368)"),
                    flag_state=flags),
        writer,
    ]


async def _scenario_turn_l1_outage() -> list:
    from services.llm_client import LLMError
    llm = FakeLLM(l1_error=LLMError("provider down"), l2="ответ по детерминированному плану")
    service, dcs = _service(llm)
    with _flags(DIRECT_L1_ENABLED=True, DIRECT_DECISION_MAKING_ENABLED=False,
                PERSONA_ENABLED=False):
        await service.handle(_bot(), _tg_message(), _tg_message().from_user)
    flags = {"DIRECT_L1_ENABLED": True, "DIRECT_DECISION_MAKING_ENABLED": False,
             "PERSONA_ENABLED": False, "L1_FALLBACK": "deterministic"}
    return [
        _turn_stage(llm, "l2_writer",
                    stage_id="direct.l2_writer.deterministic_fallback_plan",
                    title=("L2 Writer — деградированный путь: L1 недоступен, "
                           "план детерминированный (0 LLM-вызовов планера)"),
                    call_site=("services/direct_chat_service.py::"
                               "DirectChatService._plan_direct_l1 → "
                               "direct_l1.fallback_plan → _l2_write_answer"),
                    flag_state=flags,
                    notes=["отправленного payload'а планера НЕТ: попытка "
                           "упала на транспорте (LLMError) — сегмент "
                           "описывает только то, что реально ушло дальше, "
                           "то есть Writer с детерминированным планом"]),
    ]


async def _scenario_turn_legacy_tools() -> list:
    from services.tool_loop import ToolLoopResult
    llm = FakeLLM(single="черновой ответ", stage1=SYNTH_STAGE1_JSON,
                  stage2="финальный ответ после тулов")
    router = FakeToolRouter()
    service, dcs = _service(llm, router)
    captured: dict = {}
    original = dcs.chat_with_tools

    async def fake_chat_with_tools(llm_, payload, **kwargs):
        captured["payload"] = [dict(m) for m in payload]
        captured["tools"] = list(kwargs.get("tools") or ())
        return ToolLoopResult(
            "финал тулов", rounds_used=2,
            tool_trace=[{"tool": "execute_web_search", "ok": True}],
            tool_context="лог nginx: upstream 502 на /healthz",
            tool_results=[{"tool": "execute_web_search", "status": "ok"}])

    dcs.chat_with_tools = fake_chat_with_tools
    try:
        with _flags(DIRECT_L1_ENABLED=False, DIRECT_DECISION_MAKING_ENABLED=False,
                    PERSONA_ENABLED=False, SYSTEM2_DIRECT_ENABLED=True):
            await service.handle(_bot(), _tg_message(), _tg_message().from_user)
    finally:
        dcs.chat_with_tools = original
    flags = {"DIRECT_L1_ENABLED": False, "DIRECT_DECISION_MAKING_ENABLED": False,
             "PERSONA_ENABLED": False, "SYSTEM2_DIRECT_ENABLED": True}
    return [
        _stage(stage_id="direct.tool_phase.model_driven",
               title="Tool-фаза (legacy): system+user payload и схемы инструментов",
               call_site=("services/direct_chat_service.py::"
                          "DirectChatService.handle → build_messages@4044 → "
                          "chat_with_tools@4322"),
               module="direct_chat", step="chat_with_tools",
               messages=captured["payload"], tools=captured["tools"],
               flag_state=flags,
               notes=["payload = payload_builder.build_messages(system_prompt, "
                      "user_blocks, time_line=...) — канон system@0"]),
        _turn_stage(llm, "stage1",
                    stage_id="direct.system2.stage1",
                    title="System2 Stage-1 (машинная справка по выводу инструментов)",
                    call_site=("services/direct_chat_service.py::"
                               "_synthesize_direct_answer (messages@7168)"),
                    flag_state=flags),
        _turn_stage(llm, "stage2",
                    stage_id="direct.system2.stage2",
                    title="System2 Stage-2 (вербализатор валидированной справки)",
                    call_site=("services/direct_chat_service.py::"
                               "_synthesize_direct_answer (messages@7255)"),
                    flag_state=flags),
    ]


async def _scenario_turn_legacy_single() -> list:
    llm = FakeLLM(single="ответ одиночным вызовом")
    service, dcs = _service(llm, None)
    with _flags(DIRECT_L1_ENABLED=False, DIRECT_DECISION_MAKING_ENABLED=False,
                PERSONA_ENABLED=False, SYSTEM2_DIRECT_ENABLED=False):
        await service.handle(_bot(), _tg_message(), _tg_message().from_user)
    flags = {"DIRECT_L1_ENABLED": False, "DIRECT_DECISION_MAKING_ENABLED": False,
             "PERSONA_ENABLED": False, "SYSTEM2_DIRECT_ENABLED": False}
    return [
        _turn_stage(llm, "single",
                    stage_id="direct.single.legacy_no_tools",
                    title="Legacy одиночный вызов без инструментов (тот же payload, что tool-фаза)",
                    call_site=("services/direct_chat_service.py::"
                               "DirectChatService.handle → llm.generate(step='single')@4341"),
                    flag_state=flags),
    ]


async def _scenario_layered_l2() -> list:
    from services import direct_l1 as _l1
    llm = FakeLLM(l2="слоистый ответ")
    service, dcs = _service(llm, None)
    plan = _l1.parse_l1_plan(PLAN_JSON)
    plan_block = _plan_block_for(plan)
    response_plan = plan.to_response_plan()
    flags = {"DIRECT_L1_ENABLED": True, "PERSONA_ENABLED": False,
             "layers": "character/style/lessons/speech/time_line/evidence"}
    with _flags(DIRECT_L1_ENABLED=True, PERSONA_ENABLED=False):
        await dcs.DirectChatService._l2_write_answer(
            service, CHAT_ID, QUERY, temperature=0.7,
            correlation_id="er65-layered", character_block=CHARACTER_BLOCK,
            style_directives=STYLE_DIRECTIVES, response_plan=response_plan,
            plan_block=plan_block, user_blocks=list(EXTRA_USER_BLOCKS),
            time_line=NOW_LINE, evidence=TOOL_EVIDENCE,
            lessons_block=LESSONS_BLOCK, speech_block=SPEECH_BLOCK,
            max_tokens=4096, fallback_budget_tokens=800)
    call = llm.last("l2_writer")
    if call is None:
        raise RuntimeError("layered L2: вызов Writer не состоялся")
    layers = [("layer:character_block", CHARACTER_BLOCK, "layer"),
              ("layer:style_requests", STYLE_DIRECTIVES, "layer"),
              ("layer:time_line", NOW_LINE, "layer"),
              ("layer:plan_block", plan_block, "layer"),
              ("layer:speech_understanding", SPEECH_BLOCK, "layer"),
              ("layer:verified_lessons", LESSONS_BLOCK, "layer"),
              ("layer:user_block_global_context", EXTRA_USER_BLOCKS[0], "layer"),
              ("layer:tool_evidence_block",
               "<Tool_Evidence>\n" + TOOL_EVIDENCE + "\n</Tool_Evidence>",
               "layer")]
    stages = [_stage(stage_id="direct.l2_writer.layered",
                     title=("L2 Writer со всеми слоями хода "
                            "(identity/style/lessons/speech/time/evidence)"),
                     call_site=("services/direct_chat_service.py::"
                                "DirectChatService._l2_write_answer (messages@6972)"),
                     module="direct_chat", step="l2_writer",
                     messages=call["messages"], extra_candidates=layers,
                     flag_state=flags,
                     payload_kwargs=tuple(call["kwargs"]))]
    adapter = call.get("fallback_adapter")
    if adapter is None:
        raise RuntimeError("layered L2: fallback_payload_adapter не создан")
    recorded = ADAPTERS.rows[-1] if ADAPTERS.rows else None
    if recorded is None:
        raise RuntimeError("layered L2: вызов build_l2_fallback_adapter "
                           "не записан")
    stages.extend(_fallback_repack_stages(call, recorded, flags,
                                          plan_block=plan_block))
    return stages


def _fallback_repack_stages(call, recorded, flags, plan_block="") -> list:
    """Пересборка L2-пакета ТЕМ ЖЕ адаптером под два окна fallback-модели.

    Входы адаптера (`system`/`parts`/`evidence`/`query`) — фактические, взятые
    из записи вызова внутри `_l2_write_answer`; меняется только окно, как это
    делает транспорт при переключении на другую fallback-модель.
    """
    from services import direct_execution as dx
    payload = {"model": "fallback-model", "temperature": 0.7,
               "messages": [dict(m) for m in call["messages"]]}
    candidates = [("layer:character_block", CHARACTER_BLOCK, "layer"),
                  ("layer:style_requests", STYLE_DIRECTIVES, "layer"),
                  ("layer:time_line", NOW_LINE, "layer"),
                  ("layer:plan_block", plan_block, "layer"),
                  ("layer:speech_understanding", SPEECH_BLOCK, "layer"),
                  ("layer:verified_lessons", LESSONS_BLOCK, "layer"),
                  ("layer:user_block_global_context",
                   EXTRA_USER_BLOCKS[0], "layer"),
                  ("layer:tool_evidence_block",
                   "<Tool_Evidence>\n" + TOOL_EVIDENCE + "\n</Tool_Evidence>",
                   "layer")]
    out = []
    for stage_id, title, budget_note, budget in (
        ("direct.l2_writer.fallback_model_repack",
         "L2 Writer — пересборка пакета под окно fallback-модели "
         "(пакет помещается целиком)",
         "окно 2400 токенов: system (≈1600) + слои хода помещаются без "
         "потерь → capacity-пометки нет", 2400),
        ("direct.l2_writer.fallback_model_capacity",
         "L2 Writer — честный capacity-исход под окно fallback-модели "
         "(fallback_window_exceeded)",
         "окно 400 токенов: сама system не помещается → честная пометка "
         "[CAPACITY], а не тихая отправка", 400),
    ):
        reasons: list[str] = []
        def _on_capacity(reason, sink=reasons):
            sink.append(str(reason))
        dedicated = dx.build_l2_fallback_adapter(
            system=str(recorded["system"]), parts=list(recorded["parts"]),
            evidence=str(recorded["evidence"]), query=str(recorded["query"]),
            fallback_budget_tokens=budget,
            on_capacity_reason=_on_capacity)
        adapted = dedicated(json.loads(json.dumps(payload)))
        out.append(_stage(
            stage_id=stage_id, title=title,
            call_site=("services/direct_execution.py::"
                       "build_l2_fallback_adapter → llm_client payload "
                       "fallback_payload_adapter"),
            module="direct_chat", step="l2_writer(fallback)",
            messages=adapted["messages"],
            extra_candidates=candidates,
            flag_state=flags,
            notes=[budget_note,
                   "capacity_reason=" + (",".join(reasons) or "-"),
                   "адаптер создан с боевыми входами L2-шва "
                   f"(parts={len(recorded['parts'])}, "
                   f"system={len(str(recorded['system']))} симв.)",
                   "пересборка вызвана ровно так, как её вызывает LLMClient "
                   "при переключении на fallback-модель"]))
    return out


def _plan_block_for(plan) -> str:
    """Plan-блок, который шов L2 реально кладёт в user-часть.

    Вызывается та же функция сборки, что на call-site (см.
    `direct_chat_service` окрестности 5658/11902), с тем же набором флагов:
    это вход атрибуции, а не переписанная композиция.
    """
    from services import direct_l1 as _l1
    from config.settings import settings
    modes_on = bool(getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True))
    return _l1.build_l2_plan_block(
        plan, rejected=(), include_delivery=True,
        include_analysis=_l1.analysis_directive_needed(plan, modes_on=modes_on),
        include_delta=_l1.delta_instruction_needed(plan),
        modes_on=modes_on)


def _claim_block() -> str:
    """`<claim>`-блок так, как его рендерит FactCheckService.build_user_content."""
    from services.summary_xml import escape_xml_text
    return f"<claim>{escape_xml_text(FACTCHECK_CLAIM)}</claim>"


def _user_hint_block() -> str:
    from services.summary_xml import escape_xml_text
    return f"<user_hint>{escape_xml_text('проверь инцидент')}</user_hint>"


def _search_results_block() -> str:
    from services.summary_xml import escape_xml_text
    return (f"<search_results>{escape_xml_text(SEARCH_RESULTS)}"
            f"</search_results>")


async def _scenario_factcheck(single: bool) -> list:
    from services.factcheck_service import FactCheckService
    llm = FakeLLM(single="вердикт одиночным вызовом",
                  stage1=FACTCHECK_STAGE1_JSON,
                  stage2="вердикт по валидированной справке")
    service = FactCheckService(aggregator=None, llm=llm, memory=None,
                              tool_router=None)
    with _flags(SYSTEM2_FACTCHECK_ENABLED=not single, PERSONA_ENABLED=False):
        await asyncio.wait_for(service.check_claim(
            FACTCHECK_CLAIM, user_hint="проверь инцидент", chat_id=None,
            search_results=SEARCH_RESULTS), timeout=120)
    if single:
        call = llm.last("single")
        if call is None:
            raise RuntimeError("factcheck single: вызов не состоялся")
        return [_stage(stage_id="factcheck.single",
                       title="FactCheck — одиночный путь (канон + критика + Core/стиль)",
                       call_site=("services/factcheck_service.py::"
                                  "_check_claim_pipeline (messages@1527)"),
                       module="factcheck", step="single",
                       messages=call["messages"],
                       extra_candidates=[
                           ("layer:claim", _claim_block(), "layer"),
                           ("layer:user_hint", _user_hint_block(), "layer"),
                           ("layer:search_results", _search_results_block(),
                            "layer")],
                       flag_state={"SYSTEM2_FACTCHECK_ENABLED": False})]
    stages = []
    for step, stage_id, title, call_site in (
        ("stage1", "factcheck.stage1_analyst",
         "FactCheck Stage-1 — аналитик (JSON по claim + выдача поиска)",
         "services/factcheck_service.py::_check_claim_two_call (messages@1542)"),
        ("stage2", "factcheck.stage2_verbalizer",
         "FactCheck Stage-2 — вербализатор валидированной справки",
         "services/factcheck_service.py::_check_claim_two_call (messages@1595)"),
    ):
        call = llm.last(step)
        if call is None:
            raise RuntimeError(f"{stage_id}: вызов не состоялся")
        stages.append(_stage(stage_id=stage_id, title=title,
                             call_site=call_site, module="factcheck",
                             step=step, messages=call["messages"],
                             flag_state={"SYSTEM2_FACTCHECK_ENABLED": True},
                             payload_kwargs=tuple(call["kwargs"])))
    return stages


async def _scenario_initiative() -> list:
    llm = FakeLLM(l1=PLAN_JSON, l2="инициативный текст")
    service, dcs = _service(llm, None)
    with _flags(PERSONA_ENABLED=False, DIRECT_L1_ENABLED=True):
        plan = await dcs.DirectChatService.plan_initiative_decision(
            service, CHAT_ID, INITIATIVE_ROW, correlation_id="er65-init")
        await dcs.DirectChatService.generate_initiative_reply(
            service, CHAT_ID, INITIATIVE_ROW, l1_plan=plan,
            correlation_id="er65-init")
    flags = {"PERSONA_ENABLED": False, "path": "initiative"}
    l1 = _turn_stage(llm, "l1_planner",
                     stage_id="initiative.l1_planner",
                     title="Инициатива — решение L1 (reply/react/silent)",
                     call_site=("services/direct_chat_service.py::"
                                "plan_initiative_decision (messages@11807)"),
                     flag_state=flags,
                     notes=["system = resolve_prompt(prompts.direct_l1_planner_system_prompt); "
                            "user = direct_l1.build_l1_context(...) с поводом "
                            "наблюдателя как ПРЕДЛОЖЕНИЕМ"])
    writer = _turn_stage(llm, "l2_writer",
                         stage_id="initiative.l2_writer",
                         title="Инициатива — тот же L2 Writer (writer='initiative_writer')",
                         call_site=("services/direct_chat_service.py::"
                                    "generate_initiative_reply → "
                                    "_l2_write_answer (messages@6972)"),
                         flag_state=flags,
                         notes=["третьего Writer'а нет: инициатива пишется "
                                "тем же каналом, что обычный ответ"])
    return [l1, writer]


# ── сборка снимка ──────────────────────────────────────────────────────────

SCENARIOS = (
    ("direct.turn_l1_direct", _scenario_turn_l1_direct),
    ("direct.turn_l1_tools", _scenario_turn_l1_tools),
    ("direct.turn_l1_outage", _scenario_turn_l1_outage),
    ("direct.turn_legacy_tools", _scenario_turn_legacy_tools),
    ("direct.turn_legacy_single", _scenario_turn_legacy_single),
    ("direct.layered_l2", _scenario_layered_l2),
    ("factcheck.single", lambda: _scenario_factcheck(True)),
    ("factcheck.two_call", lambda: _scenario_factcheck(False)),
    ("initiative", _scenario_initiative),
)


def _source_fingerprints() -> dict:
    out = {}
    for rel in SOURCE_FILES:
        path = os.path.join(REPO_ROOT, rel)
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            out[rel] = {"sha256": "", "bytes": 0, "lines": 0}
            continue
        out[rel] = {"sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                    "bytes_utf8": len(data),
                    "lines": data.count(b"\n") + 1}
    return out


def _environment() -> dict:
    import platform
    try:
        import tiktoken  # noqa: F401
        tokenizer = "tiktoken"
    except Exception:                                  # noqa: BLE001
        tokenizer = "fallback(0.3 chars/token)"
    from services import prompt_registry as pr
    from services import mca_gates
    from config import settings as settings_module
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "tokenizer": tokenizer,
        "app_version": str(getattr(settings_module, "APP_VERSION", "") or ""),
        "canon_factory_set": pr.FACTORY_SET_SHA256_12,
        "canon_registry_version": str(pr.REGISTRY_VERSION),
        "seal_problems": pr.seal_integrity(),
        "gate_mode": "offline: no network (socket blocked), no PG, no Telegram",
        "unified_composer_enabled": bool(mca_gates.unified_composer_enabled()),
    }


async def _capture_async() -> dict:
    os.chdir(REPO_ROOT)
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    _neutralize()
    stages = []
    with _no_network():
        for _name, scenario in SCENARIOS:
            _neutralize()
            for stage in await scenario():
                stages.append(stage)
    return {"stages": stages}


def build_once() -> dict:
    """Полный снимок за один прогон (один процесс, заводской канон)."""
    core = asyncio.run(_capture_async())
    snapshot = {
        "schema": SCHEMA,
        "artifact": "GENERATED — не редактировать; перегенерация: "
                    + REGEN_COMMAND,
        "regeneration_command": REGEN_COMMAND,
        "check_command": "py -3 tools/er65_prompt_segment_snapshot.py --check",
        "purpose": ("снимок фактических сегментов, отправляемых модели на "
                    "каждой стадии Direct/FactCheck/Initiative, снят на "
                    "транспортной границе без сети и без БД"),
        "environment": _environment(),
        "fixtures": {
            "chat_id": CHAT_ID, "query": QUERY, "window_messages": len(WINDOW),
            "rag_chars": len(RAG_TEXT),
            "character_block_chars": len(CHARACTER_BLOCK),
            "style_block_chars": len(STYLE_DIRECTIVES),
            "lessons_block_chars": len(LESSONS_BLOCK),
            "speech_block_chars": len(SPEECH_BLOCK),
            "time_line": NOW_LINE,
            "tool_evidence_chars": len(TOOL_EVIDENCE),
            "factcheck_claim": FACTCHECK_CLAIM,
            "initiative_row_keys": sorted(INITIATIVE_ROW),
            "model_responses": {
                "l1_plan": PLAN_JSON, "l2": "фиксированный текст",
                "stage1_system2": SYNTH_STAGE1_JSON,
                "stage1_factcheck": FACTCHECK_STAGE1_JSON,
            },
        },
        "sources": _source_fingerprints(),
        "prompt_revisions": dict(RESOLVER.revisions),
        "stages": core["stages"],
    }
    snapshot["summary"] = _summary(snapshot)
    return snapshot


def _summary(snapshot: dict) -> dict:
    stages = snapshot["stages"]
    segments = [record for stage in stages for record in stage["messages"]]
    return {
        "stages": len(stages),
        "message_segments": len(segments),
        "system_segments": sum(1 for r in segments if r["role"] == "system"),
        "user_segments": sum(1 for r in segments if r["role"] == "user"),
        "total_chars": sum(r["chars"] for r in segments),
        "total_bytes_utf8": sum(r["bytes_utf8"] for r in segments),
        "segment_sha256_count": len({r["sha256"] for r in segments}),
        "stages_with_unattributed_gap": [
            stage["stage_id"] for stage in stages
            if any(r["unattributed_chars"] for r in stage["messages"])],
        "all_expected_prompt_keys_found": all(
            stage["expected_prompt_keys_all_found"] for stage in stages),
        "stages_with_order_violations": [
            stage["stage_id"] for stage in stages if stage["order_violations"]],
        "min_attribution_ratio": min(
            (record["attribution_ratio"] for stage in stages
             for record in stage["messages"]), default=1.0),
        "fallback_stages": [stage["stage_id"] for stage in stages
                            if "fallback" in stage["stage_id"]],
        "stage_ids": [stage["stage_id"] for stage in stages],
        "roles_observed": sorted({record["role"] for record in segments}),
    }


def _run_json_subprocess() -> dict:
    """Независимый процесс: доказательство, что байты воспроизводимы."""
    result = subprocess.run([sys.executable, os.path.abspath(__file__),
                             "--stdout"], capture_output=True, cwd=REPO_ROOT,
                            timeout=900)
    if result.returncode != 0:
        raise RuntimeError("snapshot subprocess failed:\n"
                           + result.stderr.decode("utf-8", "replace")[-4000:])
    return json.loads(result.stdout.decode("utf-8"))


def build_stable() -> dict:
    """Два независимых прогона → совпадение байтов обязательно."""
    first = _run_json_subprocess()
    second = _run_json_subprocess()
    left = json.dumps(first, ensure_ascii=False, sort_keys=True)
    right = json.dumps(second, ensure_ascii=False, sort_keys=True)
    if left != right:
        raise RuntimeError("НЕДЕТЕРМИНИРОВАННЫЙ снимок: два прогона расходятся")
    snapshot = first
    snapshot["determinism"] = {
        "runs": 2,
        "isolated_processes": True,
        "identical": True,
        "snapshot_core_sha256": sha256(
            json.dumps({k: v for k, v in snapshot.items()
                        if k not in ("determinism", "environment")},
                       ensure_ascii=False, sort_keys=True)),
        "compared_stages": snapshot["summary"]["stages"],
        "compared_segments": snapshot["summary"]["message_segments"],
    }
    return snapshot


# ── отчёты ─────────────────────────────────────────────────────────────────

def render_markdown(snapshot: dict) -> str:
    env = snapshot["environment"]
    summary = snapshot["summary"]
    determ = snapshot.get("determinism") or {}
    lines = [
        "# ER-65 / ER-S42 / ER-09 — фактически отправляемые сегменты промптов",
        "",
        "> СГЕНЕРИРОВАННЫЙ АРТЕФАКТ. Не редактировать руками.",
        f"> Перегенерация: `{snapshot['regeneration_command']}`",
        f"> Проверка байтовой стабильности: `{snapshot['check_command']}`",
        "",
        "## Что это",
        "",
        "Снимок снят на транспортной границе (`llm.generate(messages, ...)` и "
        "`chat_with_tools(llm, payload, tools=...)`) при прогоне реальных швов "
        "сборки. Тела промптов не переписаны: система и user-часть собираются "
        "самим кодом, инструмент только фиксирует байты, длины, `sha256` и "
        "порядок блоков.",
        "",
        f"* Python {env['python']} ({env['platform']}), токенизатор: "
        f"`{env['tokenizer']}`",
        f"* Канон: Registry `{env['canon_registry_version']}`, заводской набор "
        f"`{env['canon_factory_set']}`, нарушения печатей: "
        f"{env['seal_problems'] or 'нет'}",
        f"* Режим: {env['gate_mode']}; композер "
        f"(`unified_composer_enabled`) = {env['unified_composer_enabled']}",
        f"* Стадий: **{summary['stages']}**, сегментов сообщений: "
        f"**{summary['message_segments']}** (system "
        f"{summary['system_segments']} / user {summary['user_segments']}), "
        f"суммарно {summary['total_chars']} символов "
        f"({summary['total_bytes_utf8']} байт UTF-8)",
        f"* Детерминированность: два независимых процесса, совпадение "
        f"`{determ.get('identical')}`, ядро снимка "
        f"`{determ.get('snapshot_core_sha256', '')[:16]}…`",
        "",
        "## Стадии и сегменты",
        "",
        "| Стадия | Роль | Символов | sha256 (12) | Блоков | "
        "Неатрибутировано |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for stage in snapshot["stages"]:
        for record in stage["messages"]:
            lines.append(
                f"| `{stage['stage_id']}` | {record['role']} | "
                f"{record['chars']} | `{record['sha256_12']}` | "
                f"{len(record['blocks'])} | {record['unattributed_chars']} |")
    lines += [
        "",
        "Полные тексты сегментов и порядок блоков — в "
        f"`{JSON_NAME}` (поле `stages[].messages[]`).",
        "",
        "## Структура сообщений",
        "",
        f"Наблюдаемые роли в фактических payload'ах: "
        f"`{', '.join(summary['roles_observed'])}`.",
        "Ни одна стадия не отправляет сообщение с ролью `developer` или "
        "`tool`: во всём контуре Direct/FactCheck/Initiative — ровно два "
        "сообщения, `system` (канал/личность/стиль/канон) и `user` (вопрос + "
        "контекст + план + evidence). Результаты инструментов едут ТЕКСТОМ "
        "внутри user-части (`<Tool_Evidence>`), а не отдельными "
        "`role=\"tool\"`-сообщениями. Схемы инструментов передаются вне "
        "`messages` — отдельным аргументом транспорта `tools=[...]` "
        "(зафиксировано на стадии `direct.tool_phase.model_driven`).",
        "",
        "## Какая стадия когда срабатывает",
        "",
        "| Стадия | Название | Точка вызова |",
        "| --- | --- | --- |",
    ]
    for stage in snapshot["stages"]:
        lines.append(f"| `{stage['stage_id']}` | {stage['title']} | "
                     f"`{stage['call_site']}` |")
    lines += ["", "## Порядок блоков (что реально склеено в каждом сегменте)", ""]
    for stage in snapshot["stages"]:
        for record in stage["messages"]:
            labels = [block["label"] for block in record["blocks"]]
            lines.append(f"### `{stage['stage_id']}` → {record['role']}")
            lines.append("")
            lines.append(" → ".join(f"`{label}`" for label in labels if label)
                         or "_(один неразмеченный блок)_")
            lines.append("")
    lines += [
        "## Эффективные ревизии и печати канона",
        "",
        "`act:` — действующая редакция текста, `fac:` — заводская редакция по "
        "печати реестра, `found_at` — позиция в байтах сегмента. Порядок "
        "`found_at` обязан возрастать: перестановка блоков в сборке это ломает.",
        "",
        "| Стадия | Ключ | block_id | act | fac | source | found_at |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    seen = set()
    for stage in snapshot["stages"]:
        for row in stage["prompt_resolutions"]:
            key = (stage["stage_id"], row["key"], row["sha256_12"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"| `{stage['stage_id']}` | `{row['key']}` | "
                f"`{row['block_id']}` | `{row['revision']}` | "
                f"`{row['factory_revision']}` | {row['source']} | "
                f"{row['found_at']} |")
    lines += [
        "",
        "## Что доказано",
        "",
        "1. Для каждой стадии существует ровно тот payload, который уходит в "
        "транспорт; структура `system@0` + `user` (у tool-фазы — плюс схемы "
        "инструментов) подтверждена фактическими `messages`.",
        "2. Длины и `sha256` каждого сегмента воспроизводятся байт-в-байт в "
        "двух независимых процессах.",
        "3. Каждый блок, пришедший через именованный шов "
        "(`prompt_style_blocks.resolve_prompt`, "
        "`prompt_registry.resolve_chat_speech`), найден в финальном тексте "
        "сегмента и в порядке вызова — то есть канон не потерян и не "
        "переставлен относительно порядка сборки.",
        "4. Слои хода (личность, style-просьбы, verified-lessons, speech, "
        "time-line, plan, tool-evidence) присутствуют в тот момент и в том "
        "порядке, в каком их собирает код (`direct.l2_writer.layered`).",
        "5. Деградированный путь: при отказе L1 модель-планер вообще не "
        "получает успешного вызова, а Writer получает детерминированный план "
        "(`direct.l2_writer.deterministic_fallback_plan`); при переключении на "
        "fallback-модель пакет пересобирается её же адаптером — сняты оба "
        "исхода, `fallback_repacked` и `fallback_window_exceeded`.",
        "",
        "## Что НЕ доказано (нужен живой вызов модели)",
        "",
        "* Что провайдер принял payload (HTTP 200), фактический `usage`, "
        "соблюдение моделью инструкций и качество ответа.",
        "* Что боевой чат действительно получает тот же текст: в боте "
        "действуют персистентные переопределения владельца (`hot`/`chat_params`) "
        "и PG-личность; здесь снят заводской канон, `source=\"default\"`.",
        "* Что payload не изменился между этим снимком и моментом деплоя: "
        "снимок привязан к конкретным `sha256` файлов сборки (поле `sources`).",
        "",
        "## Наблюдения по порядку блоков",
        "",
    ]
    violations = [(stage["stage_id"], violation)
                  for stage in snapshot["stages"]
                  for violation in stage["order_violations"]]
    if not violations:
        lines.append("Расхождений «порядок кода ≠ порядок в байтах» нет.")
    else:
        for stage_id, violation in violations:
            lines.append(
                f"* `{stage_id}`: блок `{violation['label']}` (объявлен "
                f"№{violation['declared_index']}) стоит в байтах ПОСЛЕ блока "
                f"№{violation['after_declared_index']}. Это наблюдаемое "
                "поведение существующего кода, а не решение снимка: в "
                "пересборке под окно fallback-модели `<Tool_Evidence>` "
                "доезжает после закрывающего требования Writer'а. Тест "
                "фиксирует это явно, чтобы изменение порядка не проходило "
                "незаметно.")
    lines += [
        "",
        "## Происхождение снимка (какой код собирал payload)",
        "",
        "| Файл | Строк | sha256 |",
        "| --- | --- | --- |",
    ]
    for path, info in sorted(snapshot["sources"].items()):
        lines.append(f"| `{path}` | {info['lines']} | "
                     f"`{info['sha256'][:16]}…` |")
    lines += [
        "",
        "## Откуда берётся неатрибутированный остаток",
        "",
        "Блоки, которые рендерятся внутри функций без именованного шва "
        "(например режимный/extent-блок внутри `compose_verbalizer_system` или "
        "конкатенация канонических абзацев в `build_l1_context`), остаются "
        "`unattributed` со своим `offset`/`sha256`. Это не потеря: весь текст "
        "сегмента целиком покрыт `sha256`, но не атрибутирован по имени шва.",
        "",
    ]
    return "\n".join(lines) + "\n"


# ── CLI ────────────────────────────────────────────────────────────────────

def _write(snapshot: dict) -> None:
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    json_path = os.path.join(EVIDENCE_DIR, JSON_NAME)
    md_path = os.path.join(EVIDENCE_DIR, MD_NAME)
    body = json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True)
    with open(json_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body + "\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_markdown(snapshot))
    print(f"written: {os.path.relpath(json_path, REPO_ROOT)}")
    print(f"written: {os.path.relpath(md_path, REPO_ROOT)}")
    summary = snapshot["summary"]
    print(f"stages={summary['stages']} segments={summary['message_segments']} "
          f"chars={summary['total_chars']} "
          f"determinism={snapshot['determinism']['identical']}")


def _check() -> int:
    json_path = os.path.join(EVIDENCE_DIR, JSON_NAME)
    if not os.path.exists(json_path):
        print(f"FAIL: нет артефакта {json_path}", file=sys.stderr)
        return 2
    with open(json_path, encoding="utf-8") as handle:
        committed = json.load(handle)
    fresh = build_stable()
    old = dict(committed)
    new = dict(fresh)
    old.pop("environment", None)
    new.pop("environment", None)
    old.pop("determinism", None)
    new.pop("determinism", None)
    if json.dumps(old, ensure_ascii=False, sort_keys=True) == \
            json.dumps(new, ensure_ascii=False, sort_keys=True):
        print("OK: снимок воспроизводится байт-в-байт "
              f"(stages={fresh['summary']['stages']}, "
              f"segments={fresh['summary']['message_segments']}, "
              "two isolated processes identical)")
        return 0
    print("FAIL: снимок разошёлся с закоммиченным артефактом", file=sys.stderr)
    _diff_stages(old.get("stages") or [], new.get("stages") or [])
    return 1


def _diff_stages(old_stages, new_stages) -> None:
    old_by_id = {stage["stage_id"]: stage for stage in old_stages}
    new_by_id = {stage["stage_id"]: stage for stage in new_stages}
    for stage_id in sorted(set(old_by_id) ^ set(new_by_id)):
        side = "исчезла" if stage_id in old_by_id else "появилась"
        print(f"  стадия {side}: {stage_id}", file=sys.stderr)
    for stage_id in sorted(set(old_by_id) & set(new_by_id)):
        old, new = old_by_id[stage_id], new_by_id[stage_id]
        for index, (left, right) in enumerate(zip(old["messages"],
                                                  new["messages"])):
            if left["sha256"] == right["sha256"]:
                continue
            print(f"  {stage_id}[{index}] {left['role']}: "
                  f"chars {left['chars']} → {right['chars']}, "
                  f"sha {left['sha256_12']} → {right['sha256_12']}",
                  file=sys.stderr)
            left_labels = [b["label"] for b in left["blocks"]]
            right_labels = [b["label"] for b in right["blocks"]]
            if left_labels != right_labels:
                print(f"    порядок блоков: {left_labels} → {right_labels}",
                      file=sys.stderr)
        if len(old["messages"]) != len(new["messages"]):
            print(f"  {stage_id}: число сегментов "
                  f"{len(old['messages'])} → {len(new['messages'])}",
                  file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true",
                        help="перегенерировать JSON+MD в "
                             "plans/features/evol/evidence/er65/")
    parser.add_argument("--check", action="store_true",
                        help="сверить перегенерацию с закоммиченным артефактом")
    parser.add_argument("--stdout", action="store_true",
                        help="напечатать одиночный прогон в stdout (JSON)")
    parser.add_argument("--out", default="",
                        help="записать одиночный прогон в файл (UTF-8)")
    args = parser.parse_args()
    if not any((args.write, args.check, args.stdout, args.out)):
        parser.print_help()
        return 2
    if args.stdout or args.out:
        body = json.dumps(build_once(), ensure_ascii=False, indent=1,
                          sort_keys=True)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(body + "\n")
            print(f"written: {args.out}")
        if args.stdout:
            sys.stdout.reconfigure(encoding="utf-8")
            print(body)
        return 0
    if args.check:
        return _check()
    _write(build_stable())
    return 0


if __name__ == "__main__":
    sys.exit(main())
