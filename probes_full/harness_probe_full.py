#!/usr/bin/env python3
"""P0 FULL probe (corrected 25.10.2026): один реальный L1 на весь payload.

Исполняется ИЗ ТОГО ЖЕ ДЕРЕВА, что и проверяемый код (`--root`), read-only:
PG через read-only сессию, SQLite через mode=ro; без Telegram/деплоя/записи.

Отличия от прежней копии (аудит `evidence/p0-hotfix/l1-harness-audit.md` §6-7):

* версия пинуется: git HEAD/ветка/грязность + sha256 импортированных модулей,
  запуск из самого дерева (никакой staging-копии без `.git`);
* ОДИН реальный план L1 на весь payload: mode, extent-блок, plan-блок и
  system собираются из одного и того же решения L1;
* принудительный research — отдельный сценарий `--force-plan research`,
  помеченный `forced=true` (не выдаётся за решение L1);
* счётчики — по фактическим `psb.ANALYSIS_DIRECTIVE_TEXT` /
  `psb.ANALYSIS_WRITER_TEXT` в system/user/total (не по ASCII-именам);
* RAG — реальной цепочкой прод-сервиса (`_rag_rows_with_ranks` → фильтр
  self-origin → `dedup_rag_vs_global` → `_mark_rag_fact` →
  `order_rag_facts_asc` → `build_rag_context(origin_labels=True)` →
  `<RAG_Memory>` + cap); ошибка рендера = `invalid`, без подмены строками;
* user-часть — в порядке сервиса (time_line → plan → speech/lessons при
  composer OFF → user_blocks → evidence) и передаётся композеру как
  защищённые `user_parts`;
* сбой L1/сборки — `invalid`, а не детерминированный fallback-план.

`--case C` (P0-CORRECTIVE §1.4/§3, проверка 8) — короткая бытовая реплика
как СЛЕДУЮЩЕЕ сообщение в том же историческом окне, что у A: та же история,
та же точка времени, отличается только текущая реплика. Стенд не навязывает
режим: маршрут L1 пишется как есть (`research` у C — это находка, не сбой
стенда). Текст C синтетический — это фиксируется полем `question_source`.
A/B идут прежним путём (`question_source=db`, реальные сообщения окна).

F6 (прежний прогон): `manifest.versions.core` — ревизия, а не текст, и
читалась как атрибут mapping (всегда пусто → 0). Теперь размер core берётся
из реально отрендеренного слоя (`layers[block_id=core]`), ревизия/редакция —
из `versions`, плюс `sha12`/`in_system` фактического текста.

`--self-check` — офлайн-проверка счётчиков/предиката/пинов на целевом дереве;
обязателен перед серверным сеансом.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import inspect
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

CHAT_ID = -1002661910336
TG_A, TG_B = 1175252, 1175255
TS_A, TS_B = 1792873281, 1792873478
AUTHOR_UID = 42115912
AUTHOR_DISPLAY = "Гипербореец"   # Telegram display; authoritative name = live alias
AUTHOR = AUTHOR_DISPLAY          # replaced at runtime by the live resolver

#: `--case C` (P0-CORRECTIVE §1.4/§3, проверка 8): короткая бытовая реплика.
#: Одна строка, обычный разговорный вопрос, БЕЗ просьбы разбирать историю или
#: переписку. Никакого отношения к маршрутизации: L1 решает сам, стенд только
#: фиксирует решение (`mode`, `analysis_predicate`, `l1_plan`).
CASE_C_QUESTION = "Слушай, а ты дождь любишь или тебя от него тоже ломает?"
CASE_C_NOTE = ("synthetic: короткая бытовая реплика в том же окне, что у A; "
               "режим не навязан — решение L1 записано как есть")

PINNED_MODULES = (
    "services/chat_prompts.py",
    "services/direct_l1.py",
    "services/prompt_style_blocks.py",
    "services/response_extent.py",
    "services/direct_chat_service.py",
    "services/summary_memory.py",
    "services/prompt_composer.py",
    "services/prompt_registry.py",
)


def sha12(text) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


#: Абсолютный путь стенда, зафиксированный при импорте: `self_check` делает
#: `os.chdir(root)`, после чего относительный `__file__` уже не разрешается.
HARNESS_PATH = os.path.abspath(__file__)


def unbound_local_findings(source: str) -> list:
    """AST-проверка: имя прочитано в функции раньше своего присваивания.

    Python считает имя локальным, если оно присвоено ГДЕ УГОДНО в функции;
    чтение до первого присваивания даёт `UnboundLocalError` в рантайме. Ровно
    так живой прогон `e0a46414` потерял RAG и не дошёл до L2: `llm` читался на
    строке 1030, а `llm = _make_llm(...)` стоял на 1072, — и `--self-check`
    этого не видел, потому что не вызывал `_run`.

    Области видимости соблюдаются: параметры, `global`/`nonlocal`, вложенные
    функции/лямбды/классы (их тела исполняются позже) и включения (у цели своя
    область) не дают ложных срабатываний. Возвращает список находок; пусто =
    чисто.
    """
    findings: list = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [{"function": "<module>", "name": "<syntax>",
                 "line": getattr(exc, "lineno", 0), "first_assign": 0}]

    def scan(fn) -> None:
        params = set()
        for group in (fn.args.posonlyargs, fn.args.args, fn.args.kwonlyargs):
            params.update(a.arg for a in group)
        if fn.args.vararg:
            params.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            params.add(fn.args.kwarg.arg)
        assigned: dict = {}
        loads: list = []
        declared: set = set()

        def note(name: str, line: int) -> None:
            if name not in assigned or line < assigned[name]:
                assigned[name] = line

        def outer_loads(node) -> None:
            """Загрузки поддерева вне области включения (итератор for)."""
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.Lambda)):
                    continue
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    loads.append((sub.id, sub.lineno))

        def walk(node) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    note(child.name, child.lineno)   # имя связывается здесь
                    continue                         # тело — другая область
                if isinstance(child, ast.Lambda):
                    continue
                if isinstance(child, ast.ClassDef):
                    note(child.name, child.lineno)
                    continue
                if isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp,
                                      ast.GeneratorExp)):
                    if child.generators:             # только внешний итератор
                        outer_loads(child.generators[0].iter)
                    continue
                if isinstance(child, ast.Global):
                    declared.update(child.names)
                    continue
                if isinstance(child, ast.Nonlocal):
                    declared.update(child.names)
                    continue
                if isinstance(child, ast.ExceptHandler) and child.name:
                    note(child.name, child.lineno)
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        note((alias.asname or alias.name).split(".")[0],
                             child.lineno)
                if isinstance(child, ast.ImportFrom):
                    for alias in child.names:
                        note(alias.asname or alias.name, child.lineno)
                if isinstance(child, ast.Name):
                    if isinstance(child.ctx, ast.Store):
                        note(child.id, child.lineno)
                    elif isinstance(child.ctx, ast.Load):
                        loads.append((child.id, child.lineno))
                walk(child)

        walk(fn)
        for name, line in loads:
            first = assigned.get(name)
            if first is None or name in params or name in declared:
                continue
            if line < first:
                findings.append({"function": fn.name, "name": name,
                                 "line": line, "first_assign": first})

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scan(node)
    return findings


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_state(root: str) -> dict:
    def _run(*args):
        try:
            return subprocess.run(["git", "-C", root, *args], check=True,
                                  capture_output=True, text=True,
                                  timeout=20).stdout.strip()
        except Exception as exc:                      # noqa: BLE001
            return "ERR:%s" % exc
    return {"commit": _run("rev-parse", "HEAD"),
            "branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(_run("status", "--porcelain")),
            "dirty_files": _run("status", "--porcelain").splitlines()[:20]}


def module_pins(root: str) -> dict:
    out = {}
    for rel in PINNED_MODULES:
        path = os.path.join(root, rel)
        out[rel] = {"sha256": sha256_file(path), "chars": os.path.getsize(path)}
    return out


def env(path, key):
    for line in open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if s.startswith(key + "="):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def jload(raw, default=None):
    try:
        return json.loads(raw)
    except Exception:
        return default


def case_inputs(case, rows) -> dict:
    """Вход текущего хода для `--case A/B/C`. Никогда не бросает.

    A/B: реальное сообщение чата из окна `window_A`/`window_B` (прежний путь
    байт-в-байт). C: та же точка времени и та же история, что у A (сообщение
    запроса A из истории исключено), а текущая реплика — короткая бытовая
    `CASE_C_QUESTION`; её происхождение фиксируется (`question_source`).
    """
    name = str(case or "A").upper()
    key = "A" if name == "C" else name
    target_ts = TS_A if key == "A" else TS_B
    tg_id = TG_A if key == "A" else TG_B
    if name == "C":
        return {"window_key": key, "target_ts": target_ts, "tg_id": tg_id,
                "question": CASE_C_QUESTION,
                "question_source": "synthetic_case_c",
                "question_note": CASE_C_NOTE}
    question = ""
    for m in rows or ():
        if str(m.get("tg_message_id")) == str(tg_id):
            question = m.get("text") or ""
    return {"window_key": key, "target_ts": target_ts, "tg_id": tg_id,
            "question": question, "question_source": "db",
            "question_note": ""}


class ROCache:
    """Read-only stand-in for the app's config cache (hot_config + chat params)."""

    pg_available = True

    def __init__(self, settings, chat_params):
        self._settings = settings
        self._chat_params = chat_params or {}
        self._journal = []

    def get(self, key, default=None):
        overrides = self._chat_params.get("overrides") or {}
        if key in overrides:
            return overrides[key]
        return self._settings.get(key, default)

    async def get_chat_params(self, chat_id):
        self._journal.append(chat_id)
        return {"overrides": self._chat_params}

    async def set(self, *a, **k):
        raise RuntimeError("read-only probe: cache.set forbidden")


async def load_pg(root):
    import asyncpg

    dsn = ""
    for key in ("DATABASE_URL", "POSTGRES_DSN", "PG_DSN"):
        dsn = env(os.path.join(root, ".env"), key)
        if dsn:
            break
    if not dsn:
        raise RuntimeError("no PG DSN in .env")
    conn = await asyncpg.connect(dsn, timeout=20)
    await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    ro = await conn.fetchval("SHOW transaction_read_only")
    out = {"read_only": ro, "settings": {}, "chat_params": {}, "personas": None,
           "traits": [], "identity": None}
    for r in await conn.fetch("SELECT key, value FROM bot_settings"):
        out["settings"][r["key"]] = jload(r["value"], r["value"])
    try:
        rows = await conn.fetch(
            "SELECT chat_params FROM chat_profiles WHERE chat_id = $1", CHAT_ID)
        if rows and rows[0]["chat_params"]:
            out["chat_params"] = jload(rows[0]["chat_params"], {}) or {}
    except Exception as exc:                          # noqa: BLE001
        out["chat_params_error"] = str(exc)[:160]
    for table, key in (("personas", "personas"), ("persona_traits", "traits")):
        try:
            if table == "personas":
                rows = await conn.fetch(
                    "SELECT * FROM personas WHERE chat_id = $1 OR is_global "
                    "ORDER BY is_global LIMIT 5", CHAT_ID)
            else:
                rows = await conn.fetch(
                    "SELECT * FROM persona_traits WHERE chat_id = $1 "
                    "ORDER BY id DESC LIMIT 50", CHAT_ID)
            out[key] = [dict(r) for r in rows]
        except Exception as exc:                      # noqa: BLE001
            out[key + "_error"] = str(exc)[:160]
    await conn.close()
    return out


def load_sqlite(root):
    conn = sqlite3.connect(
        "file:%s?mode=ro" % os.path.join(root, "local_database.db"),
        uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    out = {}
    try:
        cur = conn.cursor()
        window = [dict(r) for r in cur.execute(
            "SELECT * FROM smart_messages WHERE chat_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (CHAT_ID, TS_A - 5400, max(TS_A, TS_B))).fetchall()]
        out["window_A"] = [m for m in window
                           if int(m["timestamp"]) <= TS_A]
        out["window_B"] = [m for m in window
                           if int(m["timestamp"]) <= TS_B]
        for name, sql in (
            ("graph_facts", "SELECT * FROM graph_facts WHERE chat_id = ? "
                            "ORDER BY id DESC LIMIT 40"),
            ("lore_stories", "SELECT * FROM lore_stories WHERE chat_id = ? "
                             "ORDER BY id DESC LIMIT 6"),
            ("mca_lessons", "SELECT * FROM mca_lessons LIMIT 40"),
            ("chat_running_summary", "SELECT * FROM chat_running_summary "
                                     "WHERE chat_id = ? LIMIT 3"),
            ("summary_runs", "SELECT * FROM summary_runs WHERE chat_id = ? "
                             "ORDER BY rowid DESC LIMIT 4"),
            ("summary_levels", "SELECT * FROM chat_summary_levels "
                               "WHERE chat_id = ? LIMIT 3"),
        ):
            try:
                out[name] = [dict(r) for r in cur.execute(sql, (CHAT_ID,)).fetchall()]
            except Exception as exc:                  # noqa: BLE001
                out[name + "_error"] = str(exc)[:160]
    finally:
        conn.close()
    return out


def build_window_text(rows, limit=50):
    lines = []
    for m in rows[-limit:]:
        txt = (m.get("text") or "").strip()
        if txt:
            lines.append("%s: %s" % (m.get("author_name") or "?", txt))
    return "\n".join(lines)


def text_counts(text: str, psb) -> dict:
    """Честные счётчики: фактические тексты, а не ASCII-имена констант."""
    directive = getattr(psb, "ANALYSIS_DIRECTIVE_TEXT", "") or ""
    writer = getattr(psb, "ANALYSIS_WRITER_TEXT", "") or ""
    no_meta = getattr(psb, "NO_META_STRUCTURE_TEXT", "") or ""
    return {"directive": text.count(directive) if directive else 0,
            "writer": text.count(writer) if writer else 0,
            "no_meta": text.count(no_meta) if no_meta else 0,
            "no_meta_constant": bool(no_meta),
            "ascii_marker": text.count("ANALYSIS_DIRECTIVE")}


def payload_counts(system: str, user_text: str, psb) -> dict:
    s, u = text_counts(system, psb), text_counts(user_text, psb)
    total = text_counts(system + "\n\n" + user_text, psb)
    return {"system": s, "user": u, "total": total,
            "invariant_1x1": (total["directive"], total["writer"]) == (1, 1),
            "invariant_0x0": (total["directive"], total["writer"]) == (0, 0),
            # P0-CORRECTIVE §3: контракт «без мета-вступления» должен доехать
            # до Writer'а ровно один раз на разборе и ни разу на обычном
            # ответе. 0 при существующей константе — разрыв сборки, не PASS.
            "invariant_no_meta_1x1": total["no_meta"] == 1,
            "invariant_no_meta_0": total["no_meta"] == 0}


def core_report(manifest, system: str) -> dict:
    """Реально отрендеренный core-слой, а не поле versions (фикс F6).

    `manifest.versions["core"]` — РЕВИЗИЯ (строка), текст лежит в
    `layers[block_id="core"].text`; прежняя версия читала mapping как объект
    с атрибутом и всегда получала 0. Здесь размер/sha берутся из слоя,
    ревизия и редакция — из `versions`; `in_system` показывает, что именно
    этот текст физически вошёл в финальный system.
    """
    versions = dict(getattr(manifest, "versions", {}) or {})
    layers = tuple(getattr(manifest, "layers", ()) or ())
    trace = next((t for t in layers
                  if str(getattr(t, "block_id", "")) == "core"), None)
    text = str(getattr(trace, "text", "") or "")
    return {"revision": str(versions.get("core") or ""),
            "detail": versions.get("core_detail"),
            "chars": int(getattr(trace, "chars", 0) or 0),
            "rendered": bool(getattr(trace, "rendered", False)),
            "skip_reason": str(getattr(trace, "skip_reason", "") or ""),
            "sha12": sha12(text) if text else "",
            "text_chars": len(text),
            "in_system": bool(text) and text in str(system or "")}


# ── RAG: реальная цепочка прод-сервиса (без самодельного рендера) ───────────

#: Источник `<RAG_Memory>` в прогоне. `service` — фактическая функция сервиса
#: (`DirectChatService._build_rag_block`) над реальной `MemoryManager`; `dump`
#: — прежний дамп 40 строк, только явный fallback с причиной (никогда молча).
RAG_SERVICE = "service"
RAG_DUMP = "dump"


class _RagMessage:
    """Минимальный message для `_build_rag_block`: сервис читает только .text."""

    def __init__(self, text: str) -> None:
        self.text = text


class _RecordingMemory:
    """Прокси памяти: делегирует ВСЁ внутрь и записывает факт retrieval.

    Зачем: эквивалентность надо доказывать данными, а не словами — фиксируем
    аргументы вызова (`get_rag_facts(chat_id, query, **kwargs)`), число строк,
    их id и sha, чтобы в отчёте было видно, что RAG для A/B шёл по РАЗНЫМ
    query и вернул разные наборы (прежний дамп был одинаковым для всех).
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[dict] = []

    async def get_rag_facts(self, chat_id, query, **kwargs):
        rows = await self._inner.get_rag_facts(chat_id, query, **kwargs)
        rows = list(rows or [])
        self.calls.append({
            "chat_id": chat_id,
            "query": str(query or ""),
            "kwargs": {k: v for k, v in sorted(kwargs.items())},
            "rows": len(rows),
            "ids": [r.get("id") for r in rows if isinstance(r, dict)][:12],
            "rows_sha12": sha12(json.dumps(
                [r for r in rows if isinstance(r, dict)],
                ensure_ascii=False, sort_keys=True, default=str)),
            "ranks": _rank_histogram(rows),
        })
        return rows

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _rank_histogram(rows) -> dict:
    """Распределение read-policy ранга по фактическим строкам retrieval."""
    out: dict[str, int] = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        try:
            from services import graphrag_provenance as _gprov
            rank = _gprov.read_policy_rank(row)
        except Exception:                             # noqa: BLE001
            rank = None
        out[str(rank)] = out.get(str(rank), 0) + 1
    return out


async def service_memory(root: str, llm):
    """Реальная `MemoryManager` над READ-ONLY снимком БД (никаких записей).

    Доступность vec ОТРАЖАЕТСЯ по фактической таблице снимка, а не создаётся:
    в проде vec уже инициализирован, поэтому холодный экземпляр без этого
    флага уходил бы в FTS-ветку. Обе ветки — код продукта; запись touch на
    read-only падает в его штатный try/except и на текущий ответ не влияет.
    """
    from pathlib import Path as _Path

    from config.settings import settings
    from services.database import DatabaseService
    from services.summary_memory import MemoryManager

    db_path = os.path.join(root, "local_database.db")
    if not os.path.exists(db_path):
        raise FileNotFoundError("local_database.db отсутствует в --root")
    db = DatabaseService(_Path(db_path))
    await db.initialize_readonly()
    memory = MemoryManager(db, llm, aliases=None)
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('graph_facts_vec', 'graph_facts_vec_int8')")
    names = {r[0] for r in await cursor.fetchall()}
    has_vec = "graph_facts_vec" in names
    if has_vec:
        memory._vec_available = True
        memory._vec_dim = int(getattr(settings, "EMBEDDING_DIM", 0) or 0)
        memory._vec_off_reason = None
    else:
        memory._vec_off_reason = "extension"
    return memory, {"memory_class": type(memory).__name__,
                    "db_read_only": True,
                    "vec_reflected": has_vec,
                    "vec_dim": getattr(memory, "_vec_dim", None),
                    "vec_tables": sorted(names)}


async def build_rag_block(root: str, sq: dict, question: str, global_ctx: str,
                          hot, llm=None,
                          source: str = RAG_SERVICE) -> tuple[str, dict]:
    """`<RAG_Memory>` из РЕАЛЬНОГО пути сервиса (F4 ревью).

    Основной путь: `DirectChatService._build_rag_block` — тот же метод, что
    собирает RAG в проде (те же фильтры self-origin, dedup с global, реранк,
    хронология, пометки достоверности, cap). Стенд не переписывает эту логику,
    поэтому «эквивалентность» = буквально один и тот же код; различие только в
    backend памяти: здесь реальная `MemoryManager` над read-only снимком.

    Fallback на прежний дамп 40 строк разрешён, но помечается
    `rag_source=dump` + причина; тихой подмены нет.
    """
    meta: dict = {"rag_source": source, "query": question}
    if source == RAG_SERVICE:
        try:
            from services.direct_chat_service import DirectChatService

            memory, mem_meta = await service_memory(root, llm)
            meta.update(mem_meta)
            recorder = _RecordingMemory(memory)
            service = DirectChatService.__new__(DirectChatService)
            service.memory = recorder
            block, hint = await service._build_rag_block(
                CHAT_ID, _RagMessage(question), global_ctx)
            call = recorder.calls[0] if recorder.calls else {}
            meta.update({
                "function": "DirectChatService._build_rag_block",
                "retrieval": "MemoryManager.get_rag_facts",
                "retrieval_call": call,
                "rows": call.get("rows", 0),
                "nostalgia_hint": bool(hint),
                "empty": not bool(block),
            })
            if not call:
                # Ранний выход сервиса (флаг RAG выключен / нет данных):
                # это НЕ эквивалентный пустой RAG по умолчанию — фиксируем.
                meta["retrieval_skipped"] = (
                    "сервис вернулся до retrieval: flags.graph_rag_enabled="
                    "%s" % hot.get("flags.graph_rag_enabled", None))
            return block, meta
        except Exception as exc:                      # noqa: BLE001
            meta["service_error"] = "%s: %s" % (type(exc).__name__,
                                                str(exc)[:300])
            meta["rag_source"] = RAG_DUMP
    return _dump_rag_block(sq, global_ctx, hot, meta)


def _dump_rag_block(sq: dict, global_ctx: str, hot,
                    meta: dict) -> tuple[str, dict]:
    """Явный fallback: прежний дамп строк БД, НЕ retrieval по query."""
    from services import provenance as _prov
    from services.summary_memory import build_rag_context

    rows = sq.get("graph_facts") or []
    meta["rag_source"] = RAG_DUMP
    meta["rows"] = len(rows)
    meta["kept"] = 0
    meta["render"] = "real"
    meta["dump_reason"] = ("реальный путь недоступен: "
                           + str(meta.get("service_error") or "задан --rag-source dump"))
    if not rows:
        meta["render"] = "absent"
        return "", meta
    try:
        from services.direct_chat_service import (
            _SELF_ECHO_INSTRUCTION, _mark_rag_fact, _rag_rows_with_ranks,
            dedup_rag_vs_global, order_rag_facts_asc)
        modern = True
    except ImportError as exc:
        # legacy-дерево (prod 534ac7dd): provenance-хелперов ещё нет.
        modern = False
        meta["legacy_import_error"] = str(exc)[:120]
    content = ""
    kept = []
    if modern:
        facts, ranks = _rag_rows_with_ranks(rows)
        facts = [item for item in facts
                 if not _prov.is_self_referential_origin(item[0])]
        meta["after_self_filter"] = len(facts)
        kept = dedup_rag_vs_global(facts, global_ctx) if facts else []
        meta["after_dedup"] = len(kept)
        if kept:
            kept = [_mark_rag_fact(item, ranks) for item in kept]
            content = build_rag_context(
                order_rag_facts_asc(kept), origin_labels=True)
            if content and any(str(item[0]) == "bot_self_reply"
                               for item in kept):
                content = f"{_SELF_ECHO_INSTRUCTION}\n{content}"
    else:
        # legacy-рендер: те же реальные строки, без provenance-пометок.
        kept = [(r.get("origin"), r.get("fact"), r.get("created_at"),
                 r.get("target_user"), r.get("id"),
                 r.get("forward_from") or "", False) for r in rows]
        meta["after_self_filter"] = len(kept)
        meta["after_dedup"] = len(kept)
        content = build_rag_context(kept, origin_labels=True)
        meta["render"] = "legacy"
    if not content:
        meta["kept"] = 0
        return "", meta
    cap = int(hot.get("limits.graph_rag_context_max_chars",
                      _service_settings().GRAPH_RAG_CONTEXT_MAX_CHARS)
              or 0)
    meta["cap"] = cap
    if cap and len(content) > cap:
        content = content[:cap]
    meta["kept"] = len(kept)
    return f"<RAG_Memory>\n{content}\n</RAG_Memory>", meta


def _service_settings():
    from services import direct_chat_service
    return direct_chat_service.settings


def _dump_marker_ok() -> bool:
    """Fallback обязан быть помечен: `rag_source=dump` + причина, не молча."""
    block, meta = _dump_rag_block({"graph_facts": []}, "", _HotStub(), {})
    return (block == "" and meta.get("rag_source") == RAG_DUMP
            and bool(meta.get("dump_reason")))


class _HotStub:
    """hot-конфиг для офлайн-проверки dump-пути: только дефолты settings."""

    def get(self, key, default=None):
        return default


def run_summary(result: dict) -> dict:
    """Компактная сводка прогона. Никогда не бросает.

    `rag_source` обязан отражать ФАКТИЧЕСКИЙ путь сборки блока: `service` или
    `dump`. `null`/отсутствие здесь означало бы «стенд не знает, чем собрал
    RAG» — ровно так дефект `e0a46414` выглядел в отчёте. Значение берётся из
    `rag.rag_source`, а если по какой-то причине его нет — пишется
    `unreported`, а не пусто.
    """
    rag = dict(result.get("rag") or {})
    keys = ("label", "case", "question_source", "forced", "invalid", "fatal",
            "l1_plan", "mode", "no_meta_contract", "payload_counts")
    summary = {k: result.get(k) for k in keys}
    rag_source = result.get("rag_source") or rag.get("rag_source")
    summary["rag_source"] = rag_source or "unreported"
    summary["rag"] = {k: v for k, v in
                      ((k, rag.get(k)) for k in
                       ("rows", "kept", "retrieval", "block_sha12",
                        "dump_reason")) if v is not None}
    summary["rag"]["rag_source"] = summary["rag_source"]
    summary["l2_meta"] = {k: (result.get("l2_meta") or {}).get(k) for k in
                          ("flagged", "total", "analyzer")}
    summary["l2_chars"] = [r.get("chars") for r in result.get("l2_runs") or []]
    summary["stage_errors"] = result.get("stage_errors") or {}
    return summary


def self_check(root: str, json_out: bool = False) -> int:
    os.chdir(root)
    sys.path.insert(0, root)
    from services import chat_prompts as cp
    from services import direct_l1 as l1
    from services import prompt_composer as pcomp
    from services import prompt_style_blocks as psb
    from services import response_extent as extent
    from services.chat_prompts import (DIRECT_L1_PLANNER_SYSTEM_PROMPT
                                       as code_l1)

    # WRITER-NO-META-FINAL: мета-фраза в НАЧАЛЕ строки промпта — это
    # случайно попавший пример/подводка, а не перечисление запрета внутри
    # самой директивы (там слова стоят в середине строки).
    meta_re = re.compile(
        r"(?im)^[ \t]*[\"'«“]?(?:ладно|ок|сейчас|давай|глянул|разложу|"
        r"разберём)\b")

    pins = {"root": root, "git": git_state(root), "modules": module_pins(root)}
    # 1) счётчик по фактическому тексту = 1; ASCII-имя константы = 0
    synthetic = "a " + psb.ANALYSIS_DIRECTIVE_TEXT + " b " + \
        psb.ANALYSIS_WRITER_TEXT + " c"
    counts = text_counts(synthetic, psb)
    # 2) предикат и режим на синтетическом research-плане
    plan = l1.normalize_l1_plan({
        "action": "reply", "response_act": "research", "extent": "compact",
        "structure": "answer", "confidence": 0.8})
    answer = l1.normalize_l1_plan({
        "action": "reply", "response_act": "answer", "extent": "compact",
        "structure": "chat", "confidence": 0.8})
    # 3) тот же путь сборки, что в _run: mode/extent/plan из одного плана
    extent_block = extent.render_extent_block(plan.to_response_plan())
    plan_block = l1.build_l2_plan_block(plan, include_analysis=True)
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", l1.plan_response_mode(plan), "plain",
        html_safe=True, extent_block=extent_block)
    synthetic_payload = payload_counts(system, plan_block, psb)
    # 4) WRITER-NO-META-FINAL: research/compact и casual обязаны нести
    # директиву (план), deep/auto — режимный блок; итог ровно 1× на payload.
    _meta = psb.NO_META_STRUCTURE_TEXT
    research_payload = system + "\n\n" + plan_block
    casual_extent = extent.render_extent_block(answer.to_response_plan())
    casual_block = l1.build_l2_plan_block(answer, modes_on=True)
    casual_system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", l1.plan_response_mode(answer),
        "plain", html_safe=True, extent_block=casual_extent)
    casual_payload = casual_system + "\n\n" + casual_block
    deep_plan = l1.normalize_l1_plan({
        "action": "reply", "response_act": "research", "extent": "auto",
        "structure": "report", "delivery_hint": "rich", "confidence": 0.9})
    deep_block = l1.build_l2_plan_block(deep_plan, modes_on=True)
    deep_system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", "deep_research", "rich",
        html_safe=True,
        extent_block=extent.render_extent_block(deep_plan.to_response_plan()))
    deep_payload = deep_system + "\n\n" + deep_block
    payloads = {"research": research_payload, "casual": casual_payload,
                "deep_auto": deep_payload}
    meta_free = {}
    for name, payload in payloads.items():
        # директива сама перечисляет запрещённые слова — исключаем её из
        # скана, чтобы проверять именно случайные мета-примеры промпта.
        meta_free[name] = meta_re.search(payload.replace(_meta, "")) is None
    answer_extent = extent.render_extent_block(answer.to_response_plan())
    answer_plan_block = l1.build_l2_plan_block(answer)
    answer_system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", l1.plan_response_mode(answer), "plain",
        html_safe=True, extent_block=answer_extent)
    answer_payload = payload_counts(answer_system, answer_plan_block, psb)
    # F6-regression: отчёту о core нужен размер ОТРЕНДЕРЕННОГО слоя, а не
    # атрибут mapping `versions` (прежняя версия всегда давала 0).
    core_text = "<Personality_Core>контрольный слой</Personality_Core>"
    fake_manifest = pcomp.PromptManifest(
        system="<Channel_Canon/>\n\n" + core_text,
        versions={"core": "abc123def456", "core_detail": "full:owner_setting"},
        layers=(pcomp.LayerTrace(layer="core", block_id="core",
                                 chars=len(core_text), rendered=True,
                                 text=core_text),))
    core_rep = core_report(fake_manifest, fake_manifest.system)
    # `--case C`: тот же вход, что у A, отличается только текущая реплика.
    row_a = [{"tg_message_id": TG_A, "text": "запрос A"},
             {"tg_message_id": 999, "text": "прочее"}]
    cin_a = case_inputs("A", row_a)
    cin_c = case_inputs("C", row_a)
    # F2: анализатор меты должен ловить преамбулу во ВТОРОМ предложении
    # (тип A1: «эмоция. Ладно, глянул…») и не трогать чистый ответ.
    from analyze_l2_meta import analyze_text as _meta_analyze
    meta_bad = _meta_analyze(
        "Ох бля, Макс, ну ты даёшь запрос. Ладно, глянул твои сообщения.\n\n"
        "Ты вступился за Костю.")
    meta_ok = _meta_analyze("Он не злобный, он просто устал от споров.")

    from services.direct_chat_service import DirectChatService as _DCSimpl
    _rag_block_method = _DCSimpl._build_rag_block

    # F4 (review): RAG-блок собирает РЕАЛЬНАЯ функция сервиса, а не копия
    # логики в стенде. Проверяем три вещи: (а) метод — тот самый класс-метод,
    # (б) вызов retrieval идёт с прод-аргументами (include_direct_reply/
    # include_self/with_meta=True), (в) блок непустой и помечен rag_source.
    class _FakeMemory:
        def __init__(self):
            self.calls = []

        async def get_rag_facts(self, chat_id, query, **kwargs):
            self.calls.append({"chat_id": chat_id, "query": query,
                               "kwargs": dict(kwargs)})
            return [{"id": 7, "origin": "chat_history",
                     "fact": "Макс заступился за Костю",
                     "rag_ts": 1792873000, "message_timestamp": 1792873000,
                     "created_at": 1792873000, "target_user": None,
                     "tg_message_id": 42, "item_id": "tg:42",
                     "forward_from": "", "expired": False,
                     "expires_at": None, "chat_id": CHAT_ID,
                     "status": "confirmed", "subject_ref_id": None,
                     "speaker_author_id": 42115912,
                     "assertion_kind": "opinion",
                     "attribution_method": "speaker",
                     "provenance_channel": "chat"}]

    fake = _FakeMemory()

    async def _rag_probe():
        from services.direct_chat_service import DirectChatService
        svc = DirectChatService.__new__(DirectChatService)
        svc.memory = _RecordingMemory(fake)
        block, hint = await svc._build_rag_block(
            CHAT_ID, _RagMessage("вопрос для RAG"), "контекст окна")
        return block, hint, svc

    try:
        rag_block, _rag_hint, _svc = asyncio.run(_rag_probe())
        _rag_err = ""
    except Exception as exc:                          # noqa: BLE001
        rag_block, _rag_err = "", "%s: %s" % (type(exc).__name__,
                                             str(exc)[:200])
        _rag_hint = ""
    rag_call = (fake.calls or [{}])[0]
    # Guard полосы «UnboundLocalError в _run»: (а) реальный файл стенда,
    # (б) образец с дефектом того же вида, (в) корректный образец.
    _unbound_file_err = ""
    try:
        with open(HARNESS_PATH, encoding="utf-8") as fh:
            _harness_src = fh.read()
    except OSError as exc:                            # noqa: BLE001
        _harness_src = ""
        _unbound_file_err = str(exc)[:160]
    _unbound_current = (unbound_local_findings(_harness_src)
                        if _harness_src else
                        [{"function": "<file>", "name": "<unreadable>",
                          "line": 0, "first_assign": 0,
                          "error": _unbound_file_err}])
    _unbound_bad = unbound_local_findings(
        "def run(args, result):\n"
        "    block, meta = make(result, llm=llm)\n"
        "    llm = build(args)\n"
        "    return block\n")
    _unbound_ok = unbound_local_findings(
        "def run(args, result):\n"
        "    llm = build(args)\n"
        "    block, meta = make(result, llm=llm)\n"
        "    return block\n")
    results = {
        "counts_1x1": counts["directive"] == 1 and counts["writer"] == 1,
        "ascii_marker_zero": counts["ascii_marker"] == 0,
        "payload_1x1": synthetic_payload["invariant_1x1"],
        "predicate_research": l1.analysis_directive_needed(plan) is True,
        "predicate_answer": l1.analysis_directive_needed(answer) is False,
        "mode_research_serious": l1.plan_response_mode(plan) == "serious",
        "modules_under_root": all(
            os.path.commonpath([os.path.abspath(root),
                                os.path.abspath(p)]) == os.path.abspath(root)
            for p in (psb.__file__, l1.__file__)),
        # P0-CORRECTIVE §1.1/§3: harness обязан исполнять code-canon кандидата
        # (не старый PG) и не обрезать Core.
        "code_l1_canon_material_routing": (
            "response_act=research" in code_l1
            and "Смотри, что человек просит сделать с материалом" in code_l1
            and "приоритет у\n   разбора" in code_l1
            and "проанализируй мои сообщения" not in code_l1.lower()),
        "code_l1_canon_not_pg_stage": (
            code_l1 != cp.PREV_DIRECT_L1_PLANNER_R3B
            and code_l1 != cp.PREV_DIRECT_L1_PLANNER_P0CS
            and code_l1 != cp.PREV_DIRECT_L1_PLANNER_P0CS2),
        "core_full_not_truncated": (
            pcomp.simplify_core_for_prompt(cp.PERSONALITY_CORE_FULL_TEXT)
            == cp.PERSONALITY_CORE_FULL_TEXT),
        # WRITER-NO-META-FINAL: покрыты оба фактические ветки и casual.
        "no_meta_research_plan_once": (
            research_payload.count(_meta) == 1 and _meta in plan_block),
        "no_meta_casual_plan_once": (
            casual_payload.count(_meta) == 1 and _meta in casual_block),
        "no_meta_deep_auto_mode_once": (
            deep_payload.count(_meta) == 1 and _meta in deep_system),
        "meta_phrases_absent_from_prompts": all(meta_free.values()),
        # Контракт «без мета-вступления» доезжает до Writer'а один раз на
        # разборе и ни разу на обычном ответе. Позиция не важна: проверяется
        # ФАКТ присутствия в собранном payload, а не имя блока.
        "no_meta_directive_1x1_research": (
            synthetic_payload["system"]["no_meta_constant"]
            and synthetic_payload["invariant_no_meta_1x1"]),
        # Обычный ответ: директива тоже едет (WRITER-NO-META-FINAL: мета-вход
        # запрещён в любом ответе), но ровно один раз и только в plan-части —
        # дублирования с режимным блоком нет.
        "no_meta_directive_1x1_answer": (
            answer_payload["invariant_no_meta_1x1"]
            and answer_payload["user"]["no_meta"] == 1
            and answer_payload["system"]["no_meta"] == 0),
        # F6: отчётность по core — из отрендеренного слоя.
        "core_report_chars": core_rep["chars"] == len(core_text),
        "core_report_revision": core_rep["revision"] == "abc123def456",
        "core_report_in_system": core_rep["in_system"] is True,
        "core_report_sha12": core_rep["sha12"] == sha12(core_text),
        # --case C: проводка входа.
        "case_a_unchanged": (cin_a["question"] == "запрос A"
                             and cin_a["question_source"] == "db"
                             and cin_a["target_ts"] == TS_A
                             and cin_a["tg_id"] == TG_A),
        "case_c_synthetic": (cin_c["question"] == CASE_C_QUESTION
                             and cin_c["question_source"]
                             == "synthetic_case_c"),
        "case_c_same_window_as_a": (cin_c["window_key"] == "A"
                                    and cin_c["target_ts"] == TS_A
                                    and cin_c["tg_id"] == TG_A),
        "case_c_short_single_line": (
            "\n" not in CASE_C_QUESTION and len(CASE_C_QUESTION) <= 120),
        # F2: категории раздельные, второй-предложенческий тип ловится.
        "meta_detector_catches_second_sentence": (
            meta_bad["flagged"] and bool(meta_bad["announce"])
            and bool(meta_bad["leadin"])),
        "meta_detector_clean_answer": not meta_ok["flagged"],
        # F4: RAG — реальная функция сервиса с прод-аргументами retrieval.
        "rag_service_function_real": (
            not _rag_err
            and type(_svc)._build_rag_block is _rag_block_method),
        "rag_service_retrieval_kwargs": (
            rag_call.get("kwargs") == {"include_direct_reply": True,
                                       "include_self": True,
                                       "with_meta": True}),
        "rag_service_query_passed": (
            rag_call.get("chat_id") == CHAT_ID
            and rag_call.get("query") == "вопрос для RAG"),
        "rag_service_block_rendered": (
            rag_block.startswith("<RAG_Memory>")
            and "Макс заступился за Костю" in rag_block),
        "rag_dump_marked": _dump_marker_ok(),
        # ── регрессия живого прогона e0a46414 (UnboundLocalError) ────────────
        # Guard обязан (а) молчать на этом файле, (б) ловить именно этот
        # класс дефекта на образце, (в) не срабатывать на корректном образце.
        "no_use_before_assignment": not _unbound_current,
        "unbound_guard_catches_pattern": (
            [f["name"] for f in _unbound_bad] == ["llm"]
            and _unbound_bad[0]["line"] < _unbound_bad[0]["first_assign"]),
        "unbound_guard_clean_pattern": not _unbound_ok,
        # rag_source в сводке = фактический путь сборки, никогда не null.
        "summary_rag_source_service": (
            run_summary({"rag": {"rag_source": RAG_SERVICE}})["rag_source"]
            == RAG_SERVICE),
        "summary_rag_source_dump": (
            run_summary({"rag": {"rag_source": RAG_DUMP}})["rag_source"]
            == RAG_DUMP),
        "summary_rag_source_never_null": (
            run_summary({})["rag_source"] == "unreported"),
    }
    ok = all(results.values())
    out = {"self_check": "PASS" if ok else "FAIL", "results": results,
           "counts": counts, "synthetic_payload": synthetic_payload,
           "unbound_guard": {"file_findings": _unbound_current,
                             "bad_sample": _unbound_bad,
                             "harness": HARNESS_PATH},
           "meta_detector": {"bad": meta_bad["meta"], "ok": meta_ok["meta"]},
           "meta_check": {"free": meta_free,
                          "payload_counts": {
                              name: payload.count(_meta)
                              for name, payload in payloads.items()}},
           "answer_payload": answer_payload,
           "core_report": core_rep,
           "case_inputs": {"A": cin_a, "C": cin_c},
           "code_l1_canon": {"chars": len(code_l1), "sha12": sha12(code_l1),
                             "prev_p0cs2_sha12": sha12(
                                 cp.PREV_DIRECT_L1_PLANNER_P0CS2)},
           "pins": pins}
    # self-check — машинная проверка: JSON печатается целиком (обрезанный
    # вывод нельзя распарсить в evidence-пайплайне).
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def _make_llm(root, result):
    from services.llm_client import LLMClient
    base = env(os.path.join(root, ".env"), "LLM_BASE_URL")
    keyv = env(os.path.join(root, ".env"), "LLM_API_KEY")
    model = env(os.path.join(root, ".env"), "LLM_MODEL_NAME")
    # F4: RAG-путь делает query-embedding тем же клиентом, что и прод, —
    # без embed-конфига реальный retrieval молча ушёл бы в FTS-fallback.
    client = LLMClient(base, keyv, model,
                       env(os.path.join(root, ".env"),
                           "EMBEDDING_MODEL_NAME") or "",
                       embed_base_url=env(os.path.join(root, ".env"),
                                          "EMBEDDING_BASE_URL") or "",
                       embed_api_key=env(os.path.join(root, ".env"),
                                         "EMBEDDING_API_KEY") or "")

    async def _noop(*a, **k):
        return None

    for name in ("_record_analytics", "_record_global_usage"):
        if hasattr(client, name):
            setattr(client, name, _noop)
    try:
        from services import mca_events
        mca_events.emit_mca_event = lambda *a, **k: None
    except Exception:                                 # noqa: BLE001
        pass
    try:
        from services import usage_events
        usage_events.record = _noop
    except Exception:                                 # noqa: BLE001
        pass
    result["llm"] = {"model": model,
                     "base_host": base.split("//")[-1].split("/")[0]}
    return client


def resolve_author(pg: dict) -> tuple[str, dict]:
    """Живой алиас автора (uid 42115912) из PG-карт; display — только nickname."""
    from services.summary_aliases import (AliasResolver, merge_alias_maps,
                                          parse_alias_map)
    settings = pg.get("settings") or {}
    chat = pg.get("chat_params") or {}
    gmap = parse_alias_map(settings.get("limits.summary_aliases"))
    cmap = parse_alias_map((chat.get("overrides") or {}).get(
        "limits.summary_aliases"))
    resolver = AliasResolver(merge_alias_maps(gmap, cmap))
    name = resolver.resolve(AUTHOR_UID, AUTHOR_DISPLAY, None)
    source = ("chat" if str(AUTHOR_UID) in cmap
              else "global" if str(AUTHOR_UID) in gmap else "fallback")
    return name, {"uid": AUTHOR_UID, "display": AUTHOR_DISPLAY,
                  "resolved": name, "source": source,
                  "chat_alias": cmap.get(str(AUTHOR_UID), ""),
                  "global_alias": gmap.get(str(AUTHOR_UID), "")}


def _plan_dict(plan):
    if plan is None:
        return None
    keys = ("action", "response_act", "extent", "structure", "tone",
            "delivery_hint", "confidence", "confidence_bucket", "source",
            "needs_clarification")
    return {k: getattr(plan, k, None) for k in keys}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--ast-check", default="",
                    help="проверить произвольный python-файл на чтение имени "
                         "до присваивания в функции (exit 1 при находках)")
    ap.add_argument("--label", default="probe")
    ap.add_argument("--case", default="A", choices=("A", "B", "C"),
                    help="A/B — реальные сообщения чата; C — короткая бытовая "
                         "реплика в том же окне, что у A (синтетический текст, "
                         "режим решает L1)")
    ap.add_argument("--out", default="")
    ap.add_argument("--repeats", type=int, default=None,
                    help="L2-повторов на прогон (A/B: 2, C: 1 по умолчанию)")
    ap.add_argument("--skip-l2", action="store_true")
    ap.add_argument("--rag-source", default=RAG_SERVICE,
                    choices=(RAG_SERVICE, RAG_DUMP),
                    help="service — реальный путь сервиса (по умолчанию); "
                         "dump — прежний дамп строк, помечается в отчёте")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--force-plan", default="",
                    choices=("", "research"))
    ap.add_argument("--force-extent", default="normal",
                    choices=("compact", "normal", "auto", "detailed"))
    ap.add_argument("--force-structure", default="answer",
                    choices=("answer", "report"))
    ap.add_argument("--l1-attempts", type=int, default=3,
                    help="повторы L1 только при невалидном JSON (как в сервисе)")
    ap.add_argument("--l1-prompt", default="code",
                    choices=("code", "pg"),
                    help="code = канон кандидата (после миграции); pg = текущий PG")
    ap.add_argument("--use-code-l1-canon", action="store_true",
                    help="явно взять DIRECT_L1_PLANNER_SYSTEM_PROMPT из кода "
                         "кандидата (эквивалент --l1-prompt code)")
    args = ap.parse_args()
    if args.ast_check:
        path = os.path.abspath(args.ast_check)
        with open(path, encoding="utf-8") as fh:
            found = unbound_local_findings(fh.read())
        for item in found:
            print("%(function)s: '%(name)s' читается стр. %(line)s, "
                  "присваивается стр. %(first_assign)s" % item)
        print("ast_check %s findings=%d" % (path, len(found)))
        return 0 if not found else 1
    if args.self_check:
        return self_check(args.root)
    if not args.out:
        print("--out is required (no silent console-only run)", file=sys.stderr)
        return 2
    # Короткий бытовой case C — один L2-вызов по умолчанию (A/B прежние 2).
    if args.repeats is None:
        args.repeats = 1 if args.case == "C" else 2

    os.chdir(args.root)
    sys.path.insert(0, args.root)
    result = {"label": args.label, "root": args.root, "case": args.case,
              "chat_id": CHAT_ID, "forced": bool(args.force_plan),
              "force_plan": args.force_plan or None,
              "invalid": "", "stage_errors": {},
              "pins": {"git": git_state(args.root),
                       "harness": {
                           "path": os.path.abspath(__file__),
                           "sha256": sha256_file(os.path.abspath(__file__))},
                       "modules": module_pins(args.root)}}
    try:
        asyncio.run(_run(args, result))
    except Exception as exc:                          # noqa: BLE001
        import traceback
        result["fatal"] = "%s: %s" % (type(exc).__name__, str(exc)[:400])
        result["traceback"] = traceback.format_exc()[-2500:]
    json.dump(result, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    summary = run_summary(result)
    # Сводка печатается целиком (payload внутри нет): её парсят скрипты
    # сопровождения, обрезанный JSON для них бесполезен.
    print(json.dumps(summary, ensure_ascii=False))
    if result.get("fatal") or result.get("invalid"):
        # Невалидный прогон не должен выглядеть зелёным: вызывающий скрипт
        # получает exit 1 и точную причину в stderr.
        print("RUN_INVALID=%s" % (result.get("fatal")
                                  or result.get("invalid")), file=sys.stderr)
        return 1
    return 0


async def _run(args, result):
    from services import hot_config as hot
    from services import prompt_composer as pcomp
    from services import prompt_style_blocks as psb
    from services import response_extent as extent
    from services import direct_l1 as l1mod
    from services.prompt_style_blocks import resolve_prompt
    from services.prompt_registry import resolve_chat_speech

    pg = await load_pg(args.root)
    sq = load_sqlite(args.root)
    # --case C: та же история и точка времени, что у A (сообщение запроса A из
    # истории исключено); отличается только текущая реплика. A/B — прежний
    # путь без изменений.
    cinfo = case_inputs(args.case, sq.get("window_%s" % (
        "A" if args.case == "C" else args.case), []))
    result["sources"] = {
        "pg_read_only": pg["read_only"],
        "settings_keys": len(pg["settings"]),
        "chat_param_keys": len(pg["chat_params"]),
        "window_key": cinfo["window_key"],
        "window_messages": len(sq.get("window_%s" % cinfo["window_key"], [])),
        "graph_facts_rows": len(sq.get("graph_facts", [])),
        "lore_stories_rows": len(sq.get("lore_stories", [])),
        "mca_lessons_rows": len(sq.get("mca_lessons", [])),
    }
    cache = ROCache(pg["settings"], pg["chat_params"])
    hot.set_config_cache(cache)
    author, alias_meta = resolve_author(pg)
    result["alias_probe"] = alias_meta
    result["expression_doc"] = {
        "global": pg["settings"].get("character.expression"),
        "chat": (pg["chat_params"].get("overrides") or {}).get(
            "character.expression"),
    }

    from services import bot_persona
    try:
        import asyncpg
        dsn = ""
        for k in ("DATABASE_URL", "POSTGRES_DSN"):
            dsn = env(os.path.join(args.root, ".env"), k)
            if dsn:
                break
        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=2,
            server_settings={"default_transaction_read_only": "on"})
        bot_persona.set_persona_pool(pool)
    except Exception as exc:                          # noqa: BLE001
        result["stage_errors"]["persona_pool"] = str(exc)[:200]

    target_ts = cinfo["target_ts"]
    tg_id = cinfo["tg_id"]
    rows = sq.get("window_%s" % cinfo["window_key"], [])
    win = [m for m in rows
           if str(m.get("tg_message_id")) != str(tg_id)]
    question = cinfo["question"]
    result["question"] = question
    result["question_source"] = cinfo["question_source"]
    result["question_note"] = cinfo["question_note"]
    result["target_ts"] = target_ts

    # ── identity / persona (PG pool + real renderers)
    character_block = ""
    try:
        from services import mca_gates
        if mca_gates.character_layers_enabled():
            ctx = await bot_persona.resolve_character_context(CHAT_ID)
            persona, traits = ctx.persona, list(ctx.traits)
        else:
            persona = await bot_persona.resolve_bot_persona(CHAT_ID)
            traits = await bot_persona.get_traits(50)
        character_block = bot_persona.build_persona_prompt_block(
            persona, traits, enabled=True) or ""
        if mca_gates.character_layers_enabled():
            rules = bot_persona.build_character_rules_block()
            if rules:
                character_block = (character_block + "\n\n" + rules).strip()
    except Exception as exc:                          # noqa: BLE001
        result["stage_errors"]["identity"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:220])
    result["identity_block_chars"] = len(character_block)

    # ── реальный L2 summary (SQLite)
    summary_text = ""
    rows = sq.get("chat_running_summary") or []
    if rows:
        row = rows[0]
        summary_text = str(row.get("summary") or row.get("text") or "")
    result["l2_summary"] = {"chars": len(summary_text),
                            "sha12": sha12(summary_text) if summary_text else ""}

    # ── реальный RAG (ошибка рендера = invalid, без fallback-строк)
    # LLM-клиент нужен УЖЕ здесь: реальный retrieval делает query-embedding
    # тем же клиентом, что и прод. Клиент создаётся до первого использования
    # (иначе `llm` — локальная переменная, прочитанная до присваивания).
    llm = _make_llm(args.root, result)
    window_text = build_window_text(win)
    try:
        rag_block, rag_meta = await build_rag_block(
            args.root, sq, question, window_text, hot, llm=llm,
            source=getattr(args, "rag_source", RAG_SERVICE) or RAG_SERVICE)
    except Exception as exc:                          # noqa: BLE001
        rag_block, rag_meta = "", {"render": "error",
                                   "rag_source": RAG_DUMP}
        result["invalid"] = "rag_render"
        result["stage_errors"]["rag"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:220])
    result["rag"] = dict(rag_meta, block_chars=len(rag_block),
                         block_sha12=sha12(rag_block))
    # Фактический источник RAG виден и на верхнем уровне отчёта: `null` здесь
    # означал бы «стенд не знает, чем собрал блок» — так быть не должно.
    result["rag_source"] = ((result["rag"] or {}).get("rag_source")
                            or "unreported")

    # ── реальные lessons (SQLite) через реальный рендерер
    lessons_block = ""
    try:
        from services import mca_experience as mca_exp
        lessons = sq.get("mca_lessons") or []
        if lessons:
            lessons_block = mca_exp.render_lessons_block(lessons)
    except Exception as exc:                          # noqa: BLE001
        result["stage_errors"]["lessons"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:200])
    result["lessons_block_chars"] = len(lessons_block)

    # ── base prompt + gates
    base_prompt, base_source = await resolve_chat_speech(
        "prompts.direct_chat_verbalizer_system_prompt", "", chat_id=CHAT_ID)
    if not base_prompt:
        base_prompt, base_source = await resolve_chat_speech(
            "prompts.direct_chat_system_prompt", "", chat_id=CHAT_ID)
    result["base_prompt"] = {"chars": len(base_prompt or ""),
                             "sha12": sha12(base_prompt),
                             "source": base_source}
    gates = pcomp.gates_from_config()
    result["gates"] = {k: getattr(gates, k, None) for k in
                       ("unified_composer_enabled", "character_core_enabled",
                        "persona_enabled", "character_layers_enabled",
                        "smart_verbalizer_modes_enabled",
                        "expression_examples_enabled", "humor_library_enabled",
                        "humor_craft_enabled")}
    modes_on = bool(getattr(gates, "smart_verbalizer_modes_enabled", True))

    # ── L1: один реальный план (или явно помеченный forced)
    from services.direct_chat_service import (
        DIRECT_L1_PLANNER_SYSTEM_PROMPT as code_l1_system)
    pg_l1_system = resolve_prompt("prompts.direct_l1_planner_system_prompt",
                                  None) or ""
    _want_code = bool(getattr(args, "use_code_l1_canon", False)) \
        or args.l1_prompt == "code"
    if _want_code:
        l1_system = code_l1_system
        canon_source = "code"
    else:
        l1_system = pg_l1_system or code_l1_system
        canon_source = "pg" if pg_l1_system else "code"
        if pg_l1_system and pg_l1_system != code_l1_system:
            # честная пометка: PG ещё на прежней ступени (миграция не прошла)
            result["l1_canon_stale_pg"] = True
    result["l1_canon"] = {
        "chars": len(l1_system), "sha12": sha12(l1_system),
        "canon_source": canon_source,
        "source": canon_source,
        "code_canon_requested": _want_code,
        "pg_chars": len(pg_l1_system), "pg_sha12": sha12(pg_l1_system),
        "code_chars": len(code_l1_system), "code_sha12": sha12(code_l1_system),
        "pg_matches_code": pg_l1_system == code_l1_system,
        "l1_prompt_mode": args.l1_prompt}
    plan = None
    if args.force_plan:
        plan = l1mod.normalize_l1_plan({
            "action": "reply", "response_act": args.force_plan,
            "extent": args.force_extent, "structure": args.force_structure,
            "delivery_hint": "plain", "confidence": 1.0})
        result["plan_source"] = "forced"
    else:
        try:
            l1_context = l1mod.build_l1_context(
                query=question, current_question=question,
                reply_block="", window=win, speaker=author, addressee=author,
                memory_hints=rag_block, speech_hints="", capabilities=(),
                force_line="", persona_frame=character_block, bot_replies=(),
                history_partial=False, alias_resolver=None)
        except Exception as exc:                      # noqa: BLE001
            result["invalid"] = result["invalid"] or "l1_context"
            result["stage_errors"]["l1_context"] = "%s: %s" % (
                type(exc).__name__, str(exc)[:300])
            l1_context = None
        result["l1_input"] = {"system_sha12": sha12(l1_system),
                              "context_chars": len(l1_context or ""),
                              "context_sha12": sha12(l1_context)}
        if l1_context is not None:
            attempts = []
            for _attempt in range(max(1, args.l1_attempts)):
                t0 = time.time()
                try:
                    raw_l1 = await llm.generate(
                        [{"role": "system", "content": l1_system},
                         {"role": "user", "content": l1_context}],
                        temperature=(l1mod.l1_temperature(None)
                                     if hasattr(l1mod, "l1_temperature") else None),
                        chat_id=None, module="probe", step="l1_planner",
                        max_output_tokens=l1mod.l1_max_output_tokens())
                    attempts.append(str(raw_l1 or "")[:2000])
                    plan = l1mod.parse_l1_plan(raw_l1)
                except Exception as exc:              # noqa: BLE001
                    result["stage_errors"]["l1_call"] = "%s: %s" % (
                        type(exc).__name__, str(exc)[:300])
                    attempts.append("ERROR: %s" % str(exc)[:200])
                    plan = None
                result["l1_elapsed_s"] = round(time.time() - t0, 1)
                if plan is not None:
                    break
            result["l1_attempts"] = len(attempts)
            result["l1_attempt_raws"] = attempts
            result["l1_raw"] = attempts[-1][:4000] if attempts else ""
        if plan is None:
            # никакого fallback-плана: прогон невалиден
            result["invalid"] = result["invalid"] or "l1_plan"
            result["plan_source"] = "invalid"
            return
        result["plan_source"] = "llm"
    result["l1_plan"] = _plan_dict(plan)

    # ── ОДИН план на весь payload
    if plan is None:
        result["invalid"] = result["invalid"] or "l1_plan"
        return
    try:
        response_mode = l1mod.plan_response_mode(plan)
        response_plan = plan.to_response_plan()
        extent_block = extent.render_extent_block(response_plan)
        _adn = getattr(l1mod, "analysis_directive_needed", None)
        if _adn is not None:
            include_analysis = bool(_adn(plan, modes_on=modes_on))
        else:
            # legacy-дерево (prod 534ac7dd): предиката нет — analysis-текстов
            # в нём быть не может; это фиксируется, а не маскируется abort'ом.
            include_analysis = False
            result["predicate_absent"] = True
        if include_analysis is None:
            result["invalid"] = result["invalid"] or "predicate_absent"
            return
        _builder = l1mod.build_l2_plan_block
        try:
            _accepts = "include_analysis" in inspect.signature(
                _builder).parameters
            _accepts_modes = "modes_on" in inspect.signature(
                _builder).parameters
        except (TypeError, ValueError):
            _accepts = _accepts_modes = False
        _kwargs = {}
        if _accepts:
            _kwargs["include_analysis"] = include_analysis
        if _accepts_modes:
            # WRITER-NO-META-FINAL: носитель директивы зависит от режимов,
            # поэтому стенд обязан передавать реальный флаг, как сервис.
            _kwargs["modes_on"] = modes_on
        plan_block = _builder(plan, **_kwargs) if _kwargs else _builder(plan)
    except Exception as exc:                          # noqa: BLE001
        result["invalid"] = result["invalid"] or "plan_build"
        result["stage_errors"]["plan_build"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:300])
        return
    result["mode"] = response_mode
    result["analysis_predicate"] = include_analysis
    result["extent_block_chars"] = len(extent_block)
    result["plan_block"] = {"chars": len(plan_block),
                            "sha12": sha12(plan_block)}

    # ── user-часть в порядке сервиса: plan → speech/lessons (composer OFF) →
    #    user_blocks (rag → global → target → current) → evidence (нет).
    #    <Chat_Summary> не изобретаем: в direct-пути пересказ приходит внутри
    #    global head/tail; summary фиксируется отдельным фактом, не инжектом.
    user_blocks = [b for b in (
        rag_block,
        ("<Global_Context>\n" + window_text + "\n</Global_Context>")
        if window_text else "") if b]
    _c_on = pcomp.composer_enabled_now(await pcomp.resolve_gates(CHAT_ID))
    parts = []
    if plan_block:
        parts.append(plan_block)
    if not _c_on:
        if lessons_block:
            parts.append(lessons_block)
    parts.extend(user_blocks)
    parts.extend(("<Target_User>%s</Target_User>" % author,
                  "<Current_Question>\n" + question + "\n</Current_Question>"))
    user_text = "\n\n".join([p for p in parts if p])
    result["composer_on"] = _c_on
    result["summary_injection"] = {"chars": len(summary_text),
                                   "injected": False,
                                   "reason": "summary живёт в global head/tail"}

    # ── system из того же плана; user_parts передаются композеру
    from services.direct_chat_service import DirectChatService
    try:
        system, manifest = await DirectChatService._compose_speech_system(
            None, chat_id=CHAT_ID, writer="l2_writer", run_id="p0-probe",
            base_prompt=base_prompt,
            base_key="prompts.direct_chat_verbalizer_system_prompt",
            base_default="", gates=gates, channel="plain", html_safe=True,
            base_source=(base_source or ""), include_mode_block=True,
            response_mode=response_mode, response_plan=response_plan,
            extent_block=extent_block, identity_text=character_block,
            identity_source="chat",
            identity_skipped=("" if getattr(gates, "persona_enabled", True)
                              else "persona_disabled"),
            lessons_block=lessons_block,
            lessons_skip=("" if lessons_block else "lessons_absent"),
            speech_block="", speech_skip="speech_absent",
            context_text=question,
            user_parts=(tuple(parts) if _c_on else ()))
        # тот же конфликт-скраб, что сервис применяет к ФИНАЛЬНОЙ сборке
        system, _scrubbed = extent.scrub_for_plan(system, response_plan)
        result["extent_scrub_removed"] = int(_scrubbed or 0)
        result["layers"] = [{"layer": t.layer, "block_id": t.block_id,
                             "chars": t.chars, "rendered": bool(t.rendered),
                             "skip_reason": t.skip_reason}
                            for t in manifest.layers]
        result["core"] = core_report(manifest, system)
    except Exception as exc:                          # noqa: BLE001
        result["invalid"] = result["invalid"] or "compose_system"
        result["stage_errors"]["compose_system"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:300])
        return

    # F6 (review): `core_marker` убран — литерала `<Personality_Core>` в
    # payload нет ни в одном дереве (ядро — обычный текст), поэтому поле
    # всегда false и читалось как «Core отсутствует». Реальный размер/sha —
    # в `result["core"]` из отрендеренного слоя (и `in_system`).
    result["system"] = {"chars": len(system), "sha12": sha12(system),
                        "expression_marker": "<Expression" in system}
    result["author"] = author
    try:
        from services.mca_expression import (
            PROFANITY_FREQUENT_TEXT, PROFANITY_OCCASIONAL_TEXT,
            PROFANITY_OFF_TEXT)
        result["expression_check"] = {
            "frequent_text": PROFANITY_FREQUENT_TEXT in system,
            "occasional_text": PROFANITY_OCCASIONAL_TEXT in system,
            "off_text": PROFANITY_OFF_TEXT in system,
        }
    except Exception as exc:                          # noqa: BLE001
        result["expression_check"] = {"error": str(exc)[:160]}
    result["user"] = {"chars": len(user_text), "sha12": sha12(user_text)}
    counts = payload_counts(system, user_text, psb)
    result["payload_counts"] = counts
    research = str(getattr(plan, "response_act", "")) == "research"
    if research and include_analysis and not counts["invariant_1x1"]:
        result["invalid"] = result["invalid"] or "counter_invariant"
    if not research and not include_analysis and not counts["invariant_0x0"]:
        result["invalid"] = result["invalid"] or "counter_invariant"
    # Контракт «без мета-вступления» (§3): директива едет в payload РОВНО один
    # раз для любого direct-ответа. Носитель выбирает сборка: план (обычные
    # ответы и research) ИЛИ режимный блок deep_research, пока его не вытеснил
    # extent-блок. Проверяется ФАКТ в собранном payload, поэтому перенос блока
    # в другое место не проходит молча: и дубль, и потеря помечаются invalid,
    # а не зелёным прогоном. Legacy-дерево без константы инвариант не
    # применяет (в нём директивы нет вовсе).
    _no_meta_on = bool(counts["system"]["no_meta_constant"])
    _renders_extent = getattr(l1mod, "_renders_extent_block", None)
    try:
        _extent_on = bool(_renders_extent(plan)) if _renders_extent else False
    except Exception:                                 # noqa: BLE001
        _extent_on = False
    _mode_carries = bool(modes_on and response_mode == "deep_research"
                         and not _extent_on)
    _need = 1 if (_mode_carries or plan_block) else 0
    result["no_meta_contract"] = {
        "applies": _no_meta_on,
        "count": counts["total"]["no_meta"],
        "required": _need,
        "carrier": ("mode_block" if _mode_carries
                    else "plan_block" if plan_block else "none"),
    }
    if _no_meta_on and counts["total"]["no_meta"] != _need:
        result["invalid"] = result["invalid"] or "no_meta_invariant"
    result["payload"] = {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text}]}
    if result["invalid"]:
        return
    if args.skip_l2:
        return

    l2 = []
    max_tokens = 2400
    for i in range(max(1, args.repeats)):
        t0 = time.time()
        rec = {"repeat": i + 1, "temperature": args.temperature,
               "max_tokens": max_tokens}
        try:
            text = await llm.generate(
                result["payload"]["messages"], temperature=args.temperature,
                chat_id=None, module="probe", step="l2_writer",
                max_output_tokens=max_tokens)
            rec.update({"chars": len(text or ""), "sha12": sha12(text),
                        "text": text})
        except Exception as exc:                      # noqa: BLE001
            rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        rec["elapsed_s"] = round(time.time() - t0, 1)
        l2.append(rec)
    result["l2_runs"] = [{k: v for k, v in r.items() if k != "text"}
                         for r in l2]
    result["l2_texts"] = [r.get("text") or "" for r in l2]
    # F2 (review): мета-вступления считает закоммиченный анализатор, а не
    # отдельный незакоммиченный скрипт. Категории раздельные (анонс/подводка/
    # ярлык), окно — первые 1–2 предложения первого абзаца; цитаты вырезаны.
    # Отчёт только фиксирует факт, поведение не меняет.
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from analyze_l2_meta import analyze_text
        per_run = []
        for text in result["l2_texts"]:
            rep = analyze_text(text)
            per_run.append({"flagged": rep["flagged"],
                            "categories": {name: rep[name]
                                           for name in ("announce", "leadin",
                                                        "label")},
                            "window": rep["window"]})
        result["l2_meta"] = {
            "analyzer": "probes_full/analyze_l2_meta.py",
            "analyzer_sha256": sha256_file(os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "analyze_l2_meta.py")),
            "flagged": sum(1 for r in per_run if r["flagged"]),
            "total": len(per_run),
            "runs": per_run,
        }
    except Exception as exc:                          # noqa: BLE001
        result["l2_meta"] = {"analyzer_error": "%s: %s" % (
            type(exc).__name__, str(exc)[:200])}


if __name__ == "__main__":
    raise SystemExit(main())
