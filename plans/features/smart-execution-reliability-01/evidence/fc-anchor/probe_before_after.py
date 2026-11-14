"""Before/after запросов SFC-12-09 residual (`fc-anchor`, записанный сценарий).

Сравнивает план, который строит базовый `services/factcheck_planner.py`
(коммит `0beed63d`, deployed 2.58.202) и текущий файл рабочей ветки.

Запуск из корня репозитория:
    .venv/Scripts/python.exe plans/features/smart-execution-reliability-01/evidence/fc-anchor/probe_before_after.py

Ничего не пишет в репозиторий, сеть/БД/прод не использует.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

BASE_REF = "0beed63d"
REPO = Path(__file__).resolve().parents[5]

#: Восстановленный mixed-сценарий live-прогона 153116Z (2.58.202): материал
#: начинается с названия практики, LLM сузил `material_part` до подстроки БЕЗ
#: него, вопрос ссылается на «эту традицию» и перечисляет страны.
RECORDED_MATERIAL = ("Женское обрезание — древняя традиция, которая "
                     "существует уже тысячи лет. Она распространена во многих "
                     "странах Африки и Ближнего Востока, и на её сохранение "
                     "повлияли США.")
RECORDED_MATERIAL_PART = ("Она распространена во многих странах Африки и "
                          "Ближнего Востока, и на её сохранение повлияли США")
RECORDED_REQUEST = ("Реально ли есть страны с этой традицией, которые не "
                    "влияли на её сохранение: Франция, Великобритания и "
                    "Германия?")

sys.path.insert(0, str(REPO))

from config.settings import settings  # noqa: E402
from services import factcheck_orchestrator as orch  # noqa: E402
from services import factcheck_planner as fixed  # noqa: E402
from services import factcheck_suitability as fsg  # noqa: E402

object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)

base_src = subprocess.run(
    ["git", "-C", str(REPO), "show",
     f"{BASE_REF}:services/factcheck_planner.py"],
    capture_output=True, check=True).stdout.decode("utf-8")
base = types.ModuleType("base_fc_planner")
sys.modules["base_fc_planner"] = base
exec(compile(base_src, "<base_fc_planner>", "exec"), base.__dict__)  # noqa: S102


def decision(item_text=RECORDED_MATERIAL_PART):
    items = (fsg.ClaimItem(text=item_text,
                           claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                           verifiable=True, source="literal"),)
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM, claim_items=items,
        scope="web", reason_code="probe", confidence=0.9, target_ref={})


subject = orch._subject_from_decision(
    material_text=RECORDED_MATERIAL, request_text=RECORDED_REQUEST,
    material_author="Автор поста", request_author="Аня",
    material_tg_message_id=5010, request_tg_message_id=5011,
    decision={"subject": RECORDED_MATERIAL_PART + " " + RECORDED_REQUEST,
              "material_part": RECORDED_MATERIAL_PART,
              "request_part": RECORDED_REQUEST, "form_request": ""})

common = dict(claim_text=subject.text, subject_origin=subject.origin,
              subject_anchor_tg_message_id=subject.request_tg_message_id,
              subject_author=subject.request_author,
              subject_request_text=subject.request_part,
              subject_material_text=subject.material_part)

before = base.build_retrieval_plan(decision(), **common)
after = fixed.build_retrieval_plan(
    decision(), subject_full_material_text=subject.material_text, **common)

out = {
    "base_ref": BASE_REF,
    "subject_origin": subject.origin,
    "subject_material_part": subject.material_part,
    "subject_request_part": subject.request_part,
    "subject_material_part_has_topic": "обрезание" in subject.material_part.lower(),
    "queries_before": [q.text for q in (before.queries if before else [])],
    "queries_after": [q.text for q in (after.queries if after else [])],
    "claims_before": [[c.claim_id, c.text] for c in (before.claims if before else [])],
    "claims_after": [[c.claim_id, c.text] for c in (after.claims if after else [])],
}
print(json.dumps(out, ensure_ascii=False, indent=2))
