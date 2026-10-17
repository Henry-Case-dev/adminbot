# -*- coding: utf-8 -*-
"""W5 parity-ON/OFF witness: оси OFF → поведение ровно как до слайса.

Запуск: py -3 tools/_soul1_w5_parity.py
Выход: plans/features/soul-1/evidence/w5/parity-off.json
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "plans" / "features" / "soul-1" / "evidence" / "w5" / \
    "parity-off.json"

from services import chat_params, hot_config, mca_gates  # noqa: E402
from services import initiative_observer as obs  # noqa: E402
from services.database import DatabaseService  # noqa: E402

CHAT = -777


class _Hot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _CP:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}


async def main() -> dict:
    report: dict = {}
    # 1) ось публикации проверки: default OFF (env-половина отсутствует)
    os.environ.pop("INITIATIVE_DIAGNOSTICS_PUBLISH_ENABLED", None)
    for catalog_value in (False, True):
        hot_config.set_config_cache(_Hot(
            {"flags.initiative_diagnostics_publish_enabled": catalog_value}))
        chat_params.set_chat_params_cache(_CP())
        report["publish_axis_%s" % ("catalog_on" if catalog_value else
                                    "catalog_off")] = \
            mca_gates.initiative_diagnostics_publish_enabled()
    report["w5_gates_registry"] = {
        name: {"default": default, "parity_documented": len(parity) > 20}
        for name, (default, parity) in mca_gates.W5_GATES.items()}
    report["w5_axes_do_not_collide_with_existing"] = not (
        set(mca_gates.W5_GATES) & set(mca_gates.KILL_SWITCHES))

    # 2) мягкие цели не заданы → лимиты байт-в-байт как профиль
    hot_config.set_config_cache(_Hot({}))
    chat_params.set_chat_params_cache(_CP())
    tmp = Path(tempfile.mkdtemp(prefix="w5_parity_"))
    db = DatabaseService(str(tmp / "parity.db"))
    await db.initialize()
    try:
        profile = await obs.frequency_profile(CHAT)
        effective = await obs.effective_limits(db, CHAT)
        normal = obs.FREQUENCY_PROFILES[obs.DEFAULT_PROFILE]
        report["profile_hard_keys_equal_table"] = all(
            profile[key] == value for key, value in normal.items())
        report["soft_targets_unset"] = (
            profile["soft_target_replies_per_day"] == 0
            and profile["soft_target_observation_interval_seconds"] == 0)
        report["easing_flags"] = dict(effective["easing"])
        report["effective_equals_profile"] = all(
            effective[key] == profile[key]
            for key in ("min_gap_seconds", "max_replies_per_day",
                        "eval_min_interval_seconds", "eval_min_messages",
                        "eval_llm_budget_per_day",
                        "max_replies_per_topic", "day_window_seconds"))
        report["block_state_readonly"] = True
        before = await obs.latest_observe_payload(db)
        await obs.chat_block_state(db, CHAT)
        after = await obs.latest_observe_payload(db)
        report["block_state_readonly"] = (before == after)
    finally:
        await db.close()
        hot_config.set_config_cache(None)
        chat_params.set_chat_params_cache(None)
    report["note"] = (
        "ось публикации проверки default OFF (env AND каталог); мягкие цели "
        "0/0 → классы лимитов не меняются; 0 доп. LLM-вызовов на обычный "
        "ответ подтверждён существующим тестом "
        "test_soul1_flags_composition.py::test_zero_extra_llm_calls_on_"
        "normal_answer")
    return report


if __name__ == "__main__":
    payload = asyncio.new_event_loop().run_until_complete(main())
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
