"""SOUL-1 (W2) — evidence: манифест композера на РЕАЛЬНОМ Direct-сценарии.

Прогоняет настоящие методы Direct-пути (`_l2_write_answer` — primary L2 Writer
и `_compose_speech_system(writer="tool_phase")` — хвост tool-фазы того же
хода) с ВКЛЮЧЁННЫМ композером и печатает `render_effective_layers`: слои,
порядок, ревизии, оценку токенов, `skip_reason`, конфликты.

Офлайн и read-only: без Telegram, без внешних LLM, без записи в БД.
Локальный PG недоступен → глобальный слой читается через in-memory
hot-кэш; документ `character.core` — тестовая запись (регистрация ключа в
каталоге и миграция владельческого текста — отдельные слайсы W1/каталога).

Запуск (из корня репозитория):
    .venv\\Scripts\\python.exe plans/features/soul-1/evidence/w2/dump_manifest_direct_l2.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "manifest-direct-l2.json")

CORE_TEXT = (
    "Ты — живой участник неформального чата, а не ассистент. Наблюдательный, "
    "язвительный, с абсурдным мышлением: замечаешь нелепое в обычном. Мат "
    "уместен, когда делает фразу точнее, но не как обязательная приправа. "
    "Обычный разговор, серьёзный ответ и молчание — часть характера.")
POLICY_SOFT = "не ставить точки в конце коротких фраз"
SOFT_2 = "без канцелярских вводных"
IDENTITY = ("<Persona>\nИмя: Бот.\n</Persona>\n\n<Character_Rules>\n"
            "Не раскрывать, что ты ИИ.\n</Character_Rules>")
STYLE = "<Style_Requests>\nПиши без канцелярита.\n</Style_Requests>"
LESSONS = "<Verified_Lessons>\n- не обещать сроков\n</Verified_Lessons>"
SPEECH = "<Speech_Understanding>\nact=assert\n</Speech_Understanding>"
TIME_LINE = "Время: 16.10.2026 10:05"
EVIDENCE = "[tool: execute_web_search out_chars=812]"


class FakeHot:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default


class StubLLM:
    def __init__(self):
        self.captured = []

    async def generate(self, messages, **kwargs):
        self.captured.append({"step": kwargs.get("step"),
                              "messages": [dict(m) for m in messages]})
        return "ОТВЕТ ДЛЯ ЗАМЕРА СБОРКИ"


def main() -> None:
    os.environ["UNIFIED_COMPOSER_ENABLED"] = "1"
    import asyncio
    asyncio.run(_run())


async def _run() -> None:
    from services import hot_config as hot
    from services import chat_params
    from services import response_extent as _extent
    from services import prompt_composer as pc
    from services.direct_chat_service import DirectChatService as D

    hot.set_config_cache(FakeHot({
        "flags.unified_composer_enabled": True,
        "flags.character_core_enabled": True,
        "flags.speech_style_policy_enabled": True,
        "character.core": {
            "revision": 7, "enabled": True, "full_text": CORE_TEXT,
            "compact_text": CORE_TEXT, "compact_words": len(CORE_TEXT.split()),
            "compact_tokens_est": (len(CORE_TEXT) + 3) // 4,
            "detail_level": "compact", "origin": "owner_edit",
            "updated_at": "2026-10-16T10:00:00Z", "updated_by": 1},
        "style.policy": {
            "revision": 12, "rules": [],
            "soft_instructions": [
                {"id": "s1", "enabled": True, "text": POLICY_SOFT},
                {"id": "s2", "enabled": True, "text": SOFT_2}]},
    }))
    chat_params.set_chat_params_cache(None)
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
    run_id = "soul1-w2-evidence-run"

    # ── 1. tool-phase (тот же ход, writer=tool_phase) ───────────────────────
    llm_a = StubLLM()
    svc_a = Stub(llm_a)
    tool_system, tool_manifest = await D._compose_speech_system(
        svc_a, chat_id=12345, writer="tool_phase", run_id=run_id,
        base_prompt="БАЗА КАНАЛА (prompts.direct_chat_system_prompt)",
        base_key="prompts.direct_chat_system_prompt",
        base_default="БАЗА КАНАЛА", include_mode_block=False,
        gates=pc.gates_from_config(), response_plan=plan,
        extent_block=_extent.render_extent_block(plan),
        identity_text=IDENTITY, style_block=STYLE,
        lessons_block=LESSONS, speech_block=SPEECH,
        user_parts=("<Tool_Evidence>" + EVIDENCE + "</Tool_Evidence>",))

    # ── 2. L2 Writer (primary Direct answer path, тот же run_id) ────────────
    llm_b = StubLLM()
    svc_b = Stub(llm_b)
    await D._l2_write_answer(
        svc_b, 12345, "почему упал сервис", temperature=0.7,
        correlation_id=run_id, character_block=IDENTITY,
        style_directives=STYLE, response_plan=plan,
        plan_block="<Plan>extent=detailed</Plan>",
        user_blocks=["<Context>окно чата</Context>"], time_line=TIME_LINE,
        evidence=EVIDENCE, lessons_block=LESSONS, speech_block=SPEECH,
        max_tokens=4096)
    l2_manifest = pc.get_manifest(12345, run_id=run_id, writer="l2_writer")
    l2_system = llm_b.captured[-1]["messages"][0]["content"]
    l2_user = llm_b.captured[-1]["messages"][1]["content"]

    dumped = {
        "produced_by": "plans/features/soul-1/evidence/w2/"
                       "dump_manifest_direct_l2.py",
        "composer_flag": {"flags.unified_composer_enabled": True,
                          "env": "UNIFIED_COMPOSER_ENABLED=1"},
        "note": ("офлайн, без Telegram/LLM/БД; Core-документ — тестовая запись "
                 "in-memory hot-кэша (ключ ещё не в каталоге)"),
        "run_id": run_id,
        "scenario": "Direct L2 Writer (primary path) + tool-phase того же хода",
        "shared_identity_version_same_turn": {
            "tool_phase": tool_manifest.versions.get("identity"),
            "l2_writer": (l2_manifest.versions.get("identity")
                          if l2_manifest else None),
        },
        "tool_phase": {
            "system_chars": len(tool_system or ""),
            "system_sha256_12": hashlib.sha256(
                (tool_system or "").encode("utf-8")).hexdigest()[:12],
            "layers": pc.render_effective_layers(tool_manifest),
        },
        "l2_writer": {
            "system_chars": len(l2_system or ""),
            "system_sha256_12": hashlib.sha256(
                (l2_system or "").encode("utf-8")).hexdigest()[:12],
            "user_chars": len(l2_user or ""),
            "layers": pc.render_effective_layers(l2_manifest),
        },
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(dumped, fh, ensure_ascii=False, indent=2)

    print("WROTE", OUT_JSON)
    for name in ("tool_phase", "l2_writer"):
        block = dumped[name]
        print("=" * 74)
        print(f"## {name}: system chars={block['system_chars']} "
              f"sha12={block['system_sha256_12']} "
              f"tokens_total={block['layers']['tokens_total']} "
              f"manifest_id={block['layers']['manifest_id']}")
        print(f"{'layer':<20}{'rendered':<10}{'source':<12}{'revision':<24}"
              f"{'chars':>6}{'tok':>5}  skip_reason")
        for layer in block["layers"]["layers"]:
            print(f"{layer['layer']:<20}{str(layer['rendered']):<10}"
                  f"{layer['source']:<12}{layer['revision'][:22]:<24}"
                  f"{layer['chars']:>6}{layer['tokens']:>5}  "
                  f"{layer['skip_reason']}")
        print(f"versions: {json.dumps(block['layers']['versions'], ensure_ascii=False)}")
        print(f"conflicts: {block['layers']['conflict_ids']}")
        print(f"order_matches_canonical: "
              f"{block['layers']['order_matches_canonical']}")
    print("=" * 74)
    print("shared identity version (one render per turn):",
          dumped["shared_identity_version_same_turn"])


if __name__ == "__main__":
    main()
