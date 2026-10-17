"""CORE-DOC evidence: провенанс полного текста, компактная редакция, выбор.

Офлайн-зонд (без PG/Telegram/LLM). Запуск из корня репозитория:

    .venv\\Scripts\\python.exe plans/features/soul-1/evidence/w1/_core_provenance_probe.py

Пишет рядом:
  * ``_core_full_text_byte_exact.txt`` — байт-в-байт сверка заводского текста
    с первоисточником и со строчными хешами SOUL-1 карты;
  * ``_core_compact_revision.txt`` — компактная редакция целиком, её размер и
    таблица деривации (строка источника → маркеры смысла);
  * ``_core_selection_probe.json`` — детерминированный выбор редакции в
    реальных резолверах (заводская / владелец / бюджет / чат / сброс / PG down).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from services import chat_params  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import prompt_composer as pc  # noqa: E402
from services import prompt_factory as pf  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from services.chat_prompts import (  # noqa: E402
    PERSONALITY_CORE_COMPACT_DERIVATION, PERSONALITY_CORE_COMPACT_TEXT,
    PERSONALITY_CORE_FULL_TEXT)

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = ROOT / pr.CORE_SOURCE["path"]
MAP = ROOT / pr.CORE_SOURCE["map"]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha12(text: str) -> str:
    return sha256(text)[:12]


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = []

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_updated_at(self, key):
        return None

    async def set(self, key, value, category):
        self.values[key] = value
        self.writes.append((key, value, category))


class FakeChats:
    def __init__(self):
        self.overrides = {}

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}

    async def set_chat_params(self, chat_id, patch, **kwargs):
        self.overrides[int(chat_id)] = dict(patch.get("overrides") or {})


def provenance_report() -> str:
    lines = SOURCE.read_text(encoding="utf-8").split("\n")
    start, end = pr.CORE_SOURCE["line_start"], pr.CORE_SOURCE["line_end"]
    from_source = "\n".join(lines[start - 1:end])
    factory = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    doc = json.loads(MAP.read_text(encoding="utf-8"))
    rows = {}
    for group in ("items", "additional_requirements"):
        for row in doc.get(group) or ():
            if isinstance(row, dict) and row.get("req_id"):
                rows[str(row["req_id"])] = row
    out = [
        "CORE-DOC / первоисточник Personality Core (SOUL-AMD.1.1)",
        f"source: {pr.CORE_SOURCE['path']}",
        f"chapter: {pr.CORE_SOURCE['chapter']}",
        f"heading: {pr.CORE_SOURCE['heading']} (строка {start - 2})",
        f"диапазон строк: {start}–{end} "
        f"(следующий абзац: {lines[end + 1][:40]!r})",
        f"map: {pr.CORE_SOURCE['map']} | amendment: "
        f"{pr.CORE_SOURCE['amendment']}",
        "",
        f"source_sha256 (файл): {sha256(SOURCE.read_text(encoding='utf-8'))}",
        f"map source_sha256    : {doc['source_sha256']}",
        f"equal                : "
        f"{sha256(SOURCE.read_text(encoding='utf-8')) == doc['source_sha256']}",
        "",
        f"factory block_id : {pr.CORE_FULL_BLOCK_ID}",
        f"factory revision : {pr.factory_revision(pr.CORE_FULL_BLOCK_ID)}",
        f"chars            : {len(factory)}",
        f"sha256           : {sha256(factory)}",
        f"sha256_12        : {sha12(factory)}",
        f"source chars     : {len(from_source)}",
        f"BYTE-EXACT       : {factory == from_source}",
        f"code == constant : {factory == PERSONALITY_CORE_FULL_TEXT}",
        "",
        "строки-хеши SOUL-1 карты (source_text_sha256):",
    ]
    for req_id in pr.CORE_SOURCE["req_ids"]:
        row = rows[req_id]
        line_no = int(row["source_line"])
        actual = sha256(lines[line_no - 1])
        out.append(
            f"  {req_id:<12} строка {line_no:<3} карта {row['source_text_sha256'][:16]}"
            f"… файл {actual[:16]}… совпало "
            f"{actual == row['source_text_sha256']} в-тексте "
            f"{lines[line_no - 1] in factory}")
    return "\n".join(out) + "\n"


def compact_report() -> str:
    compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    lines = SOURCE.read_text(encoding="utf-8").split("\n")
    out = [
        "CORE-DOC / компактная runtime-редакция Personality Core",
        f"block_id : {pr.CORE_COMPACT_BLOCK_ID}",
        f"factory revision : {pr.factory_revision(pr.CORE_COMPACT_BLOCK_ID)}",
        f"words    : {len(compact.split())} (ориентир SOUL-02: 150–250)",
        f"chars    : {len(compact)} | sha256_12: {sha12(compact)}",
        f"равна константе кода: {compact == PERSONALITY_CORE_COMPACT_TEXT}",
        "",
        "деривация (строка первоисточника → маркеры, обязанные остаться):",
    ]
    for line_no, markers in PERSONALITY_CORE_COMPACT_DERIVATION:
        out.append(f"  строка {line_no}: {', '.join(markers)}")
        out.append(f"    источник: {lines[line_no - 1][:88]}…")
    out += ["", "текст компактной редакции:", "-" * 72, compact]
    return "\n".join(out) + "\n"


async def selection_probe() -> dict:
    pr.reset_cache()
    cache = FakeHot({})
    chats = FakeChats()
    hot.set_config_cache(cache)
    chat_params.set_chat_params_cache(chats)
    pc.reset_state()
    probe: dict = {}

    ref = await pc.resolve_core_ref(101)
    probe["1_factory_default"] = {
        "text": "factory_compact" if ref.text == pr.factory_text(
            pr.CORE_COMPACT_BLOCK_ID) else "OTHER",
        "level": ref.detail_level, "reason": ref.detail_reason,
        "origin": ref.origin, "source": ref.source, "revision": ref.revision,
        "chars": len(ref.text)}

    await pf.write_speech_value(pr.CORE_FULL_BLOCK_ID, "ПОЛНЫЙ ТЕКСТ ВЛАДЕЛЬЦА",
                                cache=cache, actor="probe")
    ref = await pc.resolve_core_ref(101)
    probe["2_owner_full_edit"] = {
        "text": ref.text, "level": ref.detail_level, "reason": ref.detail_reason,
        "doc": cache.values[pr.CORE_DOC_KEY]}
    await pf.write_speech_value(pr.CORE_COMPACT_BLOCK_ID, "КОМПАКТ ВЛАДЕЛЬЦА",
                                cache=cache, actor="probe")
    ref = await pc.resolve_core_ref(101)
    probe["3_owner_compact_edit"] = {
        "text": ref.text, "level": ref.detail_level, "reason": ref.detail_reason,
        "full_text_preserved": cache.values[pr.CORE_DOC_KEY]["full_text"]}

    cache.values[pr.CORE_DOC_KEY] = {**cache.values[pr.CORE_DOC_KEY],
                                     "detail_level": "full"}
    import os
    os.environ["COMPOSER_LAYER_BUDGET_TOKENS"] = "5"
    ref = await pc.resolve_core_ref(101)
    probe["4_context_budget_downgrade"] = {
        "level": ref.detail_level, "reason": ref.detail_reason,
        "text": ref.text}
    os.environ.pop("COMPOSER_LAYER_BUDGET_TOKENS", None)

    await pf.write_speech_value(pr.CORE_COMPACT_BLOCK_ID, "КОМПАКТ ЧАТА",
                                cache=cache, chat_id=777,
                                get_root=chats.get_chat_params,
                                set_root=chats.set_chat_params)
    chat_ref = await pc.resolve_core_ref(777)
    global_ref = await pc.resolve_core_ref(101)
    probe["5_chat_override"] = {
        "chat": {"text": chat_ref.text, "source": chat_ref.source},
        "global": {"text": global_ref.text, "source": global_ref.source},
        "chat_doc": chats.overrides[777][pr.CORE_DOC_KEY]}

    plan = await pf.plan_factory_reset(pr.CORE_COMPACT_BLOCK_ID, cache=cache)
    done = await pf.apply_factory_reset(pr.CORE_COMPACT_BLOCK_ID, cache=cache)
    probe["6_factory_reset"] = {
        "plan_changed": plan["changed"], "plan_field": plan["document_field"],
        "applied": done["applied"], "revision": done["revision"],
        "doc_after": {k: (v[:24] if isinstance(v, str) else v)
                      for k, v in cache.values[pr.CORE_DOC_KEY].items()}}

    view = await pc.core_inspection(101)
    probe["7_inspector"] = view

    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    ref = await pc.resolve_core_ref(101)
    probe["8_pg_down"] = {"text": ref.text, "skip_reason": ref.skip_reason,
                          "source": ref.source}
    pr.reset_cache()
    return probe


def main() -> None:
    (HERE / "_core_full_text_byte_exact.txt").write_text(
        provenance_report(), encoding="utf-8", newline="\n")
    (HERE / "_core_compact_revision.txt").write_text(
        compact_report(), encoding="utf-8", newline="\n")
    probe = asyncio.run(selection_probe())
    (HERE / "_core_selection_probe.json").write_text(
        json.dumps(probe, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    print("evidence written:", HERE)


if __name__ == "__main__":
    main()
