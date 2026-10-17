"""W4 (SOUL-06/07/08) — снять РЕАЛЬНЫЕ ответы API для UI-прогона.

Фикстура снимается настоящим слоем (не выдумывается): те же функции
`web/api/speech.py` на временной БД (миграция v36 + заводские черновики +
часть эталонов + реальный отбор), горячем кэше и chat-параметрах.

Запуск: `py -3 tools/ui_soul1_w4_dump_fixture.py`
Выход: `plans/features/soul-1/evidence/w4/api-fixture.json`
"""
import asyncio
import dataclasses
import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("UNIFIED_COMPOSER_ENABLED", "1")
os.environ.setdefault("HUMOR_CRAFT_ENABLED", "1")
os.environ.setdefault("HUMOR_LIBRARY_ENABLED", "1")
os.environ.setdefault("HUMOR_FEEDBACK_ENABLED", "1")

OUT = REPO / "plans" / "features" / "soul-1" / "evidence" / "w4" / "api-fixture.json"
CHAT_ID = -100500


class _Hot:
    """Горячий кэш конфигурации: оси ON + документ Core + документ ремесла."""

    def __init__(self):
        self.values = {
            "flags.unified_composer_enabled": True,
            "flags.character_core_enabled": True,
            "flags.speech_style_policy_enabled": True,
            "flags.humor_craft_enabled": True,
            "flags.humor_library_enabled": True,
            "flags.humor_feedback_enabled": True,
            "character.core": {
                "revision": 3, "enabled": True,
                "full_text": "ХАРАКТЕР ВЛАДЕЛЬЦА (полная редакция)",
                "compact_text": "ХАРАКТЕР ВЛАДЕЛЬЦА (компактная редакция)"},
            "humor.craft": {"enabled": True, "disabled_techniques": [],
                            "revision": 2, "updated_at": "2026-10-17T10:00:00Z"},
            "humor.selection": dict(
                enabled=True, max_items=3, max_tokens=320,
                diversity_min_distance=0.34, recency_penalty=0.25,
                max_per_technique=1, min_relevance=0.0, ab_enabled=False,
                ab_versions=["v1", "v2"], ab_weight=0.5),
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value

    def set_many(self, items):
        for key, value in items:
            self.values[key] = value


class _ChatCache:
    def __init__(self):
        self.overrides = {}

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None

    async def set_chat_params(self, chat_id, payload):
        self.overrides.setdefault(int(chat_id), {}).update(
            (payload or {}).get("overrides") or {})


USER = types.SimpleNamespace(id=4242, first_name="Owner")
CTX = types.SimpleNamespace(is_global_admin=True, effective_permissions=None)


def _run(coro):
    """Совместимость: снятие фикстуры — один прогон на процесс."""
    return asyncio.run(coro)


async def main() -> int:
    import services.mca_gates as gates
    from services import chat_params, hot_config, lore_runtime
    from services import mca_sample_library as samples_lib
    from services.database import DatabaseService
    import web.api.speech as S

    tmp = Path(tempfile.mkdtemp(prefix="w4-fixture-"))
    db = DatabaseService(str(tmp / "fixture.db"))
    await db.initialize()
    hot_config.set_config_cache(_Hot())
    chat_params.set_chat_params_cache(_ChatCache())
    lore_runtime.set_lore_components(db=db)

    async def _access(request, user, x_chat_id):
        return hot_config.get_config_cache(), (CHAT_ID if x_chat_id else None), CTX

    S._access = _access                      # только для снятия фикстуры

    await samples_lib.seed_starter_samples(db)
    rows = await samples_lib.list_samples(db, chat_id=CHAT_ID, status="active",
                                          limit=500)
    approved = 0
    for row in rows:
        if approved < 4 and row["technique"] in (
                "bureaucratic_logic", "deadpan", "literalism",
                "unexpected_analogy"):
            await samples_lib.set_approval(db, row["id"], approved=True,
                                           actor="fixture")
            approved += 1
    # один эталон — с репликой, чтобы карточки показывали реальные данные
    for row in rows:
        if not row["owner_approved"]:
            await samples_lib.create_sample(db, fields={
                "input_text": "сосед опять сверлит вторые выходные",
                "reply_text": "по регламенту это уже плановая акустическая "
                              "терапия дома: заявка принята, замеры сделаны, "
                              "заключение — шум есть, виноват рельеф",
                "technique": "bureaucratic_logic",
                "context_note": "бытовой шум как процедура",
                "tags": "соседи, шум", "rudeness_level": 2,
                "source_kind": "owner_manual", "scope": "global"}, actor="fixture")
            break
    await samples_lib.create_sample(db, fields={
        "input_text": "я вчера весь вечер чинил кран",
        "reply_text": "кран выиграл по очкам, но проиграл по регламенту: "
                      "замена согласована, сроки сорваны",
        "technique": "absurd_escalation", "tags": "быт",
        "rudeness_level": 1, "source_kind": "bot_suggested",
        "scope": "global"}, actor="bot")

    # Реальный проход окна реакций: сценарий «подхватили метафору».
    import time as _time
    from services import mca_humor_feedback as hf
    now = int(_time.time())
    await hf.capture_send(db, chat_id=CHAT_ID, message_id=555,
                          reply_to_message_id=554, trace_id="fixture-run-1",
                          strategy="bureaucratic_logic",
                          technique="bureaucratic_logic",
                          core_revision="core123abcd", model="fixture-model",
                          channel="plain", delivered=True, ts=now - 120)
    await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, ?, ?, 'text', 'u', 0, NULL)",
        (777, CHAT_ID, "тогда подъезд подаёт заявку в двух экземплярах",
         555, now - 100))
    await db.db.commit()

    class _LLM:
        async def generate(self, messages, **kwargs):
            return json.dumps([{"i": 0, "signal": "metaphor_continuation",
                                "confidence": "high", "subject_user_id": 777,
                                "evidence": "развил образ",
                                "metaphor_continued": True}],
                              ensure_ascii=False)

    counters = await hf.run_window_pass(db, llm=_LLM())

    payload = {
        "overview": await S.get_overview(None, USER, str(CHAT_ID)),
        "humor": await S.get_humor(None, USER, str(CHAT_ID)),
        "examples": await S.get_examples(None, USER, str(CHAT_ID)),
        "learning": await S.get_learning(None, USER, str(CHAT_ID)),
        "probe": await S.post_humor_technique_test(
            None, USER, S.HumorTechniqueTest(technique="bureaucratic_logic",
                                             profile="speech_plain"),
            str(CHAT_ID)),
        "why": await S.post_examples_why(
            None, USER, S.SampleWhyRequest(
                technique="bureaucratic_logic", extent="normal",
                message="сосед сверлит стену вторые выходные"),
            str(CHAT_ID)),
        "counters": counters,
        "gates": S._gate_state(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                              default=str), encoding="utf-8", newline="\n")
    print("fixture written:", OUT)
    print("humor techniques:", len(payload["humor"]["techniques"]),
          "| library:", payload["humor"]["library"].get("total"),
          "approved:", payload["humor"]["library"].get("approved"))
    print("examples:", payload["examples"]["count"],
          "| learning signals:", payload["learning"]["humor_feedback"]["signals"])
    print("gates:", payload["gates"])
    print("window counters:", counters)
    try:
        await db.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
