# -*- coding: utf-8 -*-
"""Dump артефактов NOSTALGIA-FIX: рендер system-промпта ON/OFF + поля кандидата.

Запуск из корня репозитория: py -3 <этот файл> > <out.txt>
Read-only: ничего не пишет в БД; hot-кэш/chat_params — локальные заглушки.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from services import mca_authorial_speech as au          # noqa: E402
from services import prompt_composer as pc              # noqa: E402
from services.nostalgia_prompts import (                # noqa: E402
    NOSTALGIA_CORE_CANON, NOSTALGIA_PROMPT)
from services.nostalgia_worker import _MAX_WORDS        # noqa: E402


class _Hot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        return None

    def set_many(self, items):
        return None


class _Chat:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None


CORE = "ТЫ — ХАРАКТЕР ВЛАДЕЛЬЦА (Core)."


async def main() -> int:
    from services import chat_params, hot_config

    legacy = NOSTALGIA_PROMPT.format(max_words=_MAX_WORDS)
    core = NOSTALGIA_CORE_CANON.format(max_words=_MAX_WORDS)

    # ── ON: композер + Core ────────────────────────────────────────────────
    os.environ["UNIFIED_COMPOSER_ENABLED"] = "1"
    hot_config.set_config_cache(_Hot({
        "flags.unified_composer_enabled": True,
        "character.core": {"revision": 3, "enabled": True,
                           "full_text": CORE, "compact_text": CORE}}))
    chat_params.set_chat_params_cache(_Chat())
    pc.reset_state()
    on_system, on_manifest = await au.authorial_system(
        chat_id=-1002661910336, writer="nostalgia_writer", genre="nostalgia",
        legacy_canon=legacy, core_canon=core)

    # ── OFF: прежний канон байт-в-байт ─────────────────────────────────────
    os.environ.pop("UNIFIED_COMPOSER_ENABLED", None)
    hot_config.set_config_cache(_Hot())
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    off_system, off_manifest = await au.authorial_system(
        chat_id=-1002661910336, writer="nostalgia_writer", genre="nostalgia",
        legacy_canon=legacy, core_canon=core)

    print("== NOSTALGIA system prompt: composer ON (Core) ==")
    print("manifest:", "composed" if on_manifest is not None else "None")
    print(on_system)
    print()
    print("== NOSTALGIA system prompt: composer OFF (legacy canon) ==")
    print("manifest:", "composed" if off_manifest is not None else "None")
    print("bytes_equal_legacy_canon:", off_system == legacy)
    print(off_system)
    print()
    print("== grep-checks ==")
    print('ON  contains "токсично-тёплый":', "токсично-тёплый" in on_system)
    print('ON  contains "ленивая печать":', "ленивая печать" in on_system)
    print('ON  contains "UNCHANGED":', "UNCHANGED" in on_system)
    print("ON  contains Core:", CORE in on_system)
    print("ON  contains genre rules:",
          au.genre_rules("nostalgia") in on_system)
    print('OFF contains "токсично-тёплый":',
          "токсично-тёплый" in off_system)
    print("OFF byte-parity with NOSTALGIA_PROMPT:", off_system == legacy)

    # ── Поля делегированного кандидата (различимый источник) ───────────────
    from services import mca_intents as mi
    cand = mi.candidate_from_trigger(
        trigger_kind="nostalgia_due", chat_id=-1002661910336,
        source="nostalgia", prepared_text_ref="nostalgia:year_back",
        reason_code="default")
    dc = cand.to_decision_candidate()
    print()
    print("== delegated candidate (единый Decision) ==")
    print("source:", dc.source)
    print("trigger_kind:", cand.trigger_kind)
    print("prepared_text_ref:", cand.prepared_text_ref)
    print("priority:", dc.priority, "| action:", dc.action)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
