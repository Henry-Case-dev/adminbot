"""SOUL-1 (W2) — evidence fix-pass F2: ровно одна копия speech/lessons в payload.

Прогоняет РЕАЛЬНЫЙ путь `_l2_write_answer` с ВКЛЮЧЁННЫМ композером
(`UNIFIED_COMPOSER_ENABLED=1` + каталоговый тумблер) и печатает:
  * счётчики маркеров `<Speech_Understanding>` / `<Verified_Lessons>` в
    system, user и во всём payload (должно быть ровно ×1 на payload);
  * счётчики защищённых user-блоков (инструкция/контекст/evidence);
  * слои манифеста, которые реально рендерились (context_lessons-владелец);
  * edge-кейс «в user-части больше нет блоков»: вопрос не теряется.

Офлайн и read-only: без Telegram, без внешних LLM, без записи в БД.
Локальный PG недоступен → глобальный слой читается через in-memory hot-кэш.

Запуск (из корня репозитория):
    .venv\\Scripts\\python.exe plans/features/soul-1/evidence/w2/dump_on_single_copy_payload.py
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

OUT_TXT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "on-payload-single-copy.txt")

MARKERS = ("<Speech_Understanding>", "<Verified_Lessons>")
IDENTITY = ("<Persona>\nИмя: Бот.\n</Persona>\n\n<Character_Rules>\n"
            "Не раскрывать, что ты ИИ.\n</Character_Rules>")
STYLE = "<Style_Requests>\nПиши без канцелярита.\n</Style_Requests>"
LESSONS = "<Verified_Lessons>\n- не обещать сроков\n</Verified_Lessons>"
SPEECH = "<Speech_Understanding>\nact=assert\n</Speech_Understanding>"
TIME_LINE = "Время: 16.10.2026 10:05"
EVIDENCE = "[tool: execute_web_search out_chars=812]"
CORE = "ЯДРО_СЦЕНАРИЯ: живой участник чата, а не ассистент."
PLAN_BLOCK = "<Plan>extent=detailed</Plan>"
CONTEXT = "<Context>окно чата</Context>"


class FakeHot:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default) if key in self.values else default


class FakeChatCache:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}


class StubLLM:
    def __init__(self):
        self.captured = []

    async def generate(self, messages, **kwargs):
        self.captured.append({"step": kwargs.get("step"),
                              "messages": [dict(m) for m in messages]})
        return "ОТВЕТ ДЛЯ ЗАМЕРА СБОРКИ"

    def _pg(self):
        return None


def sha12(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def counts(text: str) -> str:
    return ", ".join(f"{m}×{text.count(m)}" for m in MARKERS)


async def main() -> None:
    os.environ["UNIFIED_COMPOSER_ENABLED"] = "1"
    await _run()


async def _run() -> None:
    from services import hot_config as hot
    from services import chat_params
    from services import prompt_composer as pc
    from services import response_extent as _extent
    from services.direct_chat_service import DirectChatService as D

    hot.set_config_cache(FakeHot({
        "flags.unified_composer_enabled": True,
        "flags.character_core_enabled": True,
        "character.core": {"revision": 7, "enabled": True,
                           "full_text": CORE, "compact_text": CORE,
                           "detail_level": "compact", "origin": "owner_edit"},
    }))
    chat_params.set_chat_params_cache(FakeChatCache())
    pc.reset_state()

    class Stub:
        _compose_speech_system = D._compose_speech_system
        _l2_write_answer = D._l2_write_answer

        def __init__(self, llm):
            self.llm = llm
            self.db = None

    plan = _extent.ResponsePlan(task_kind="explanation", extent="detailed",
                                structure="answer", delivery_hint="plain")
    lines: list[str] = []
    lines.append("SOUL-1 / W2 — fix-pass F2: один владелец speech/lessons "
                 "на payload (композер ON)")
    lines.append("produced_by: plans/features/soul-1/evidence/w2/"
                 "dump_on_single_copy_payload.py")
    lines.append("flags: env UNIFIED_COMPOSER_ENABLED=1 + "
                 "hot flags.unified_composer_enabled=true")
    lines.append("offline: без Telegram/LLM/БД; PG недоступен "
                 "(глобальный слой = in-memory hot-кэш)")
    lines.append("")

    # ── сценарий 1: полный ход L2 Writer (как в реальном рантайме) ──────────
    llm = StubLLM()
    await D._l2_write_answer(
        Stub(llm), 12345, "почему упал сервис", temperature=0.7,
        correlation_id="soul1-w2-f2", character_block=IDENTITY,
        style_directives=STYLE, response_plan=plan, plan_block=PLAN_BLOCK,
        user_blocks=[CONTEXT], time_line=TIME_LINE, evidence=EVIDENCE,
        lessons_block=LESSONS, speech_block=SPEECH, max_tokens=4096)
    cap = llm.captured[-1]["messages"]
    system, user = cap[0]["content"], cap[1]["content"]
    payload = system + "\n\n" + user
    manifest = pc.get_manifest(12345, run_id="soul1-w2-f2", writer="l2_writer")
    rendered_ids = sorted({t.block_id for t in manifest.layers if t.rendered})

    lines.append("## сценарий 1 — L2 Writer (complete turn, flag ON)")
    lines.append(f"system chars={len(system)} sha256_12={sha12(system)}")
    lines.append(f"user   chars={len(user)} sha256_12={sha12(user)}")
    lines.append(f"system: {counts(system)}")
    lines.append(f"user  : {counts(user)}")
    lines.append(f"payload (system+user): {counts(payload)}   "
                 "<- ожидание: ×1 на каждый маркер")
    lines.append("duplication (payload>1): "
                 + str(any(payload.count(m) > 1 for m in MARKERS)))
    lines.append("protected user-parts (×1 each): "
                 + f"{PLAN_BLOCK}×{user.count(PLAN_BLOCK)}, "
                   f"{CONTEXT}×{user.count(CONTEXT)}, "
                   f"{TIME_LINE}×{user.count(TIME_LINE)}, "
                   f"<Tool_Evidence>×{user.count('<Tool_Evidence>')}")
    lines.append("manifest rendered block_ids: "
                 + ", ".join(rendered_ids))
    lines.append("context_lessons rendered: "
                 + str([t.block_id for t in manifest.layers
                        if t.layer == "context_lessons" and t.rendered]))
    lines.append("")

    # ── сценарий 2: в user-части больше нет блоков → вопрос не теряется ────
    llm2 = StubLLM()
    await D._l2_write_answer(
        Stub(llm2), 12346, "второй вопрос", temperature=0.7,
        correlation_id="soul1-w2-f2-edge", lessons_block=LESSONS,
        speech_block=SPEECH)
    cap2 = llm2.captured[-1]["messages"]
    system2, user2 = cap2[0]["content"], cap2[1]["content"]
    lines.append("## сценарий 2 — edge: speech/lessons едут только слоями")
    lines.append(f"user == query: {user2 == 'второй вопрос'}")
    lines.append(f"system: {counts(system2)}")
    lines.append(f"user  : {counts(user2)}")
    lines.append(f"payload: {counts(system2 + chr(10) + user2)}")
    lines.append("")

    text = "\n".join(lines)
    os.makedirs(os.path.dirname(OUT_TXT), exist_ok=True)
    with open(OUT_TXT, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    print("WROTE", OUT_TXT)


if __name__ == "__main__":
    asyncio.run(main())
