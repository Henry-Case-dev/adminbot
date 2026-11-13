"""S13 RED probe: concrete contract gaps on a given checkout.

Usage: python red_probe.py <repo-path>

Prints one line per observation. On the base (d20a7f73) each observation is a
defect; on the S13 branch each is fixed. No network, no DB, no LLM.
"""
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.WARNING)

repo = sys.argv[1]
sys.path.insert(0, repo)

from config.settings import settings                  # noqa: E402

# Планировщик — часть pipeline v2 (OFF-паритет: при выключенном флаге плана
# нет). Для сравнения стадий включаем тот же effective-режим, что в проде
# после выката S13.
object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)

from services import factcheck_context as fcx          # noqa: E402
from services import factcheck_planner as fsp         # noqa: E402
from services import factcheck_orchestrator as orch   # noqa: E402
from services import factcheck_suitability as fsg     # noqa: E402
from services import temporal_factcheck as tf         # noqa: E402

CHAT = -100991
TARGET = 5010
TRIGGER = 5011
MATERIAL = ("Древняя традиция женского обрезания существует тысячи лет. "
            "На её распространение влияли Франция, Великобритания, Германия "
            "и США.")
QUESTION = ("Есть ли страны, где традиция сохраняется без влияния Франции, "
            "Великобритании, Германии и США?")
ROW = {"text": MATERIAL, "caption": None, "origin_type": None,
       "origin_sent_at": None, "sent_at": 1792200000, "current_revision": 3,
       "content_hash": "hash-1", "origin_sender_user_id": None,
       "origin_chat_id": None, "origin_display_name": None,
       "author_name": "Автор поста", "forward_source": None}


class DB:
    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(ROW)

    async def get_messages_around(self, chat_id, tg, before, after):
        return []


def emit(tag, value):
    print(f"{tag}\t{json.dumps(value, ensure_ascii=False)}")


ctx = fcx.ConversationContext(
    chat_id=CHAT, target_tg_message_id=TARGET, trigger_tg_message_id=TRIGGER,
    messages=(), window={"before": 10, "after": 0}, newest_message_id=900)

# O1: cache identity of the context slice ignores the actual subject.
try:
    k_mat = fcx.slice_cache_key(ctx, before=10, after=0, claim_text=MATERIAL)
    k_q = fcx.slice_cache_key(ctx, before=10, after=0, claim_text=QUESTION)
except TypeError:
    k_mat = fcx.slice_cache_key(ctx, before=10, after=0)
    k_q = fcx.slice_cache_key(ctx, before=10, after=0)
emit("O1_slice_key_differs_by_subject", bool(k_mat and k_q and k_mat != k_q))
emit("O1_keys", [k_mat, k_q])

# O2: `_claim_units` loses the rest of an established subject (a user
#     condition) because only claim_item fragments survive.
part1 = "Древняя традиция женского обрезания существует тысячи лет."
condition = "Проверить только период 1990–2000 годов."
item = fsg.ClaimItem(text=part1, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                     verifiable=True, source="literal")
units = fsp._claim_units([item], part1 + " " + condition)
emit("O2_full_subject_survives_claim_units",
     any("1990" in u for u in units))
emit("O2_units", units)

# O3: retrieval plan accepts the established subject + provenance.
decision = fsg.SuitabilityDecision(
    decision=fsg.DECISION_CHECKABLE, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
    claim_items=(item,), scope="web", reason_code="test", confidence=0.9,
    target_ref={})
try:
    plan = fsp.build_retrieval_plan(
        decision, claim_text=QUESTION, subject_origin="request",
        subject_anchor_tg_message_id=TRIGGER, subject_author="Аня",
        subject_request_text=QUESTION)
    emit("O3_plan_accepts_subject_provenance", plan is not None)
    if plan is not None:
        emit("O3_query_texts", [q.text for q in plan.queries])
        emit("O3_anchor_origins", [r.get("origin") for r in plan.claim_anchors])
except TypeError as exc:
    emit("O3_plan_accepts_subject_provenance", False)
    emit("O3_error", str(exc))

# O4: resolver of the single subject (LLM semantic stage) exists and keeps
#     material/request/subject separately.
class LLM:
    async def generate(self, messages, **kw):
        return json.dumps({"subject": QUESTION, "material_part": "",
                           "request_part": QUESTION, "form_request": ""},
                          ensure_ascii=False)


class Service:
    llm = LLM()


try:
    subject = asyncio.run(orch.resolve_check_subject(
        Service(), material_text=MATERIAL, request_text=QUESTION,
        material_author="Автор поста", request_author="Аня",
        material_tg_message_id=TARGET, request_tg_message_id=TRIGGER,
        chat_id=CHAT))
    emit("O4_resolver_exists", True)
    emit("O4_subject", subject.text)
    emit("O4_origin", getattr(subject, "origin", None))
    emit("O4_request_preserved",
         getattr(subject, "request_text", None) == QUESTION)
except AttributeError as exc:
    emit("O4_resolver_exists", False)
    emit("O4_error", str(exc))

# O5: envelope carries request/material/date/author separately for a question.
ref = tf.InputRef(
    kind="reply", chat_id=CHAT, target_tg_message_id=TARGET,
    trigger_tg_message_id=TRIGGER,
    claim_text=MATERIAL,                       # как в прод-пути base: материал
    hint=QUESTION, attribution={"author": "Автор поста"},
    **({"subject": subject} if "subject" in getattr(
        tf.InputRef, "__dataclass_fields__", {}) else {}))
env, reason = asyncio.run(tf.build_envelope(DB(), ref))
emit("O5_envelope_reason", reason)
if env is not None:
    emit("O5_claim_text_is_question", env.claim_text == QUESTION)
    emit("O5_has_request_text_field", hasattr(env, "request_text"))
    emit("O5_has_material_claim_field", hasattr(env, "material_claim_text"))
    emit("O5_material_date_not_transferred",
         getattr(env, "original_published_at", "MISSING") is None)
    emit("O5_attribution_author", env.attribution.get("author"))
    emit("O5_subject_fingerprint", bool(getattr(env, "subject_fingerprint", None)))
