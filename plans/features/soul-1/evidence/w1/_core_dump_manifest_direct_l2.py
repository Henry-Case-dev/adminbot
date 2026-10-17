"""CORE-DOC evidence: Core в манифесте РЕАЛЬНОГО Direct-пути (композер ON).

Сценарии (оба — настоящие методы Direct-пути, офлайн, без Telegram/LLM/БД):
  1. документа владельца нет → действует ЗАВОДСКАЯ редакция Core
     (``fac:<sha12>``, ``reason=factory_default``);
  2. правка компактной редакции через API реестра
     (``prompt_factory.write_speech_value``) → следующая сборка берёт
     владельческий текст (``r<n>.<sha12>``, ``reason=owner_setting``).

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe plans/features/soul-1/evidence/w1/_core_dump_manifest_direct_l2.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

HERE = pathlib.Path(__file__).resolve().parent
OUT_JSON = HERE / "_core_manifest_direct_l2.json"
OUT_TXT = HERE / "_core_manifest_direct_l2.txt"
_OUT_LINES: list[str] = []


def emit(line: str = "") -> None:
    """Печать + накопление UTF-8-версии отчёта (PowerShell tee пишет UTF-16)."""
    _OUT_LINES.append(str(line))
    print(line)


IDENTITY = ("<Persona>\nИмя: Бот.\n</Persona>\n\n<Character_Rules>\n"
            "Не раскрывать, что ты ИИ.\n</Character_Rules>")
STYLE = "<Style_Requests>\nПиши без канцелярита.\n</Style_Requests>"
LESSONS = "<Verified_Lessons>\n- не обещать сроков\n</Verified_Lessons>"
SPEECH = "<Speech_Understanding>\nact=assert\n</Speech_Understanding>"
OWNER_COMPACT = ("КОМПАКТ ВЛАДЕЛЬЦА: наблюдательный, язвительный, абсурдный; "
                 "мат — инструмент, а не приправа; не выдумывать факты.")


class FakeHot:
    def __init__(self, values):
        self.values = dict(values)
        self.writes = []

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default

    def get_updated_at(self, key):
        return None

    async def set(self, key, value, category):
        self.values[key] = value
        self.writes.append((key, value, category))


class StubLLM:
    def __init__(self):
        self.captured = []

    async def generate(self, messages, **kwargs):
        self.captured.append({"step": kwargs.get("step"),
                              "messages": [dict(m) for m in messages]})
        return "ОТВЕТ ДЛЯ ЗАМЕРА СБОРКИ"


async def _run() -> dict:
    from services import chat_params
    from services import hot_config as hot
    from services import prompt_composer as pc
    from services import prompt_factory as pf
    from services import prompt_registry as pr
    from services import response_extent as _extent
    from services.direct_chat_service import DirectChatService as D

    os.environ["UNIFIED_COMPOSER_ENABLED"] = "1"
    cache = FakeHot({"flags.unified_composer_enabled": True,
                     "flags.character_core_enabled": True})
    hot.set_config_cache(cache)
    chat_params.set_chat_params_cache(None)
    pr.reset_cache()
    pc.reset_state()

    class Stub:
        _compose_speech_system = D._compose_speech_system
        _l2_write_answer = D._l2_write_answer

        def __init__(self, llm):
            self.llm = llm
            self.db = None

    plan = _extent.ResponsePlan(task_kind="explanation", extent="detailed",
                                structure="answer", delivery_hint="plain",
                                tool_policy="none", source="l1")
    run_id = "soul1-core-doc-evidence"
    result: dict = {"produced_by": "plans/features/soul-1/evidence/w1/"
                                   "_core_dump_manifest_direct_l2.py",
                    "composer_flag": {"env": "UNIFIED_COMPOSER_ENABLED=1",
                                      "flags.unified_composer_enabled": True},
                    "note": "офлайн: без Telegram/LLM/БД; PG недоступен → "
                            "in-memory hot-кэш (в проде — bot_settings)",
                    "scenarios": {}}

    async def dump(name: str) -> dict:
        pc.reset_state()
        tool_system, tool_manifest = await D._compose_speech_system(
            Stub(StubLLM()), chat_id=12345, writer="tool_phase", run_id=run_id,
            base_prompt="БАЗА КАНАЛА (prompts.direct_chat_system_prompt)",
            base_key="prompts.direct_chat_system_prompt",
            base_default="БАЗА КАНАЛА", include_mode_block=False,
            gates=pc.gates_from_config(), response_plan=plan,
            extent_block=_extent.render_extent_block(plan),
            identity_text=IDENTITY, style_block=STYLE,
            lessons_block=LESSONS, speech_block=SPEECH)
        llm2 = StubLLM()
        await D._l2_write_answer(
            Stub(llm2), 12345, "почему упал сервис", temperature=0.7,
            correlation_id=run_id, character_block=IDENTITY,
            style_directives=STYLE, response_plan=plan,
            plan_block="<Plan>extent=detailed</Plan>",
            user_blocks=["<Context>окно чата</Context>"], lessons_block=LESSONS,
            speech_block=SPEECH, max_tokens=4096)
        l2_manifest = pc.get_manifest(12345, run_id=run_id, writer="l2_writer")
        l2_system = llm2.captured[-1]["messages"][0]["content"]
        block = {
            "tool_phase": {"system_chars": len(tool_system or ""),
                           "layers": pc.render_effective_layers(tool_manifest)},
            "l2_writer": {"system_chars": len(l2_system or ""),
                          "system_sha256_12": hashlib.sha256(
                              l2_system.encode("utf-8")).hexdigest()[:12],
                          "layers": pc.render_effective_layers(l2_manifest)},
            "core_revision_same_turn": {
                "tool_phase": tool_manifest.versions["core"],
                "l2_writer": l2_manifest.versions["core"],
                "same": (tool_manifest.versions["core"]
                         == l2_manifest.versions["core"])},
            "factory_core_text_in_system": (
                pr.factory_text(pr.CORE_COMPACT_BLOCK_ID) in l2_system),
        }
        result["scenarios"][name] = block
        emit("=" * 78)
        emit(f"## {name}")
        for stage in ("tool_phase", "l2_writer"):
            layers = block[stage]["layers"]
            emit(f"-- {stage}: chars={block[stage]['system_chars']} "
                 f"manifest_id={layers['manifest_id']} "
                 f"tokens_total={layers['tokens_total']}")
            emit(f"{'layer':<20}{'rendered':<10}{'source':<10}"
                 f"{'revision':<24}{'chars':>6}{'tok':>5}  detail/skip")
            for lay in layers["layers"]:
                emit(f"{lay['layer']:<20}{str(lay['rendered']):<10}"
                     f"{lay['source']:<10}{lay['revision'][:22]:<24}"
                     f"{lay['chars']:>6}{lay['tokens']:>5}  "
                     f"{lay['detail'] or lay['skip_reason']}")
            emit("versions.core=" + str(layers["versions"]["core"])
                 + " | core_detail=" + str(layers["versions"]["core_detail"]))
        emit("factory compact in system: "
             + str(block["factory_core_text_in_system"]))
        emit("core revision same turn: "
             + json.dumps(block["core_revision_same_turn"]))
        return block

    await dump("1_factory_default_no_owner_doc")
    await pf.write_speech_value(pr.CORE_COMPACT_BLOCK_ID, OWNER_COMPACT,
                                cache=cache, actor="evidence")
    await dump("2_owner_edit_via_registry_api")
    result["owner_doc"] = {k: (v if not isinstance(v, str) or len(v) < 80 else
                               v[:77] + "…")
                           for k, v in (cache.values.get(pr.CORE_DOC_KEY)
                                        or {}).items()}
    return result


def main() -> None:
    dumped = asyncio.run(_run())
    OUT_JSON.write_text(json.dumps(dumped, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8", newline="\n")
    OUT_TXT.write_text("\n".join(_OUT_LINES) + "\n", encoding="utf-8",
                       newline="\n")
    print("WROTE", OUT_JSON)
    print("WROTE", OUT_TXT)


if __name__ == "__main__":
    main()
