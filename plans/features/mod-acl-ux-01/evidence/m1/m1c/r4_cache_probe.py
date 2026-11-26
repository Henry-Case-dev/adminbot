"""Проба R4: текст из кэшей (снимок хода / кольцо провайдера) у чатовой роли.

Запуск: python r4_cache_probe.py <tree-root>
"""
import os
import sys
import types

ROOT = os.path.abspath(sys.argv[1])
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)

import tests.test_mod_acl_ux_01_m1c_prompt_chat_acl as T  # noqa: E402
from services import prompt_composer as pc  # noqa: E402

SNAP = "M1C-R4-SNAP-MARK"
RING = "M1C-R4-RING-MARK"
BASE = "prompts.direct_chat_verbalizer_system_prompt"


class MP:
    def __init__(self):
        self.undo = []

    def setattr(self, obj, name, value):
        self.undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo_all(self):
        for obj, name, old in reversed(self.undo):
            setattr(obj, name, old)


mp = MP()
mp.setattr(T.deps_mod, "settings", types.SimpleNamespace(API_TOKEN=T.TEST_TOKEN))
client = T.make_client(mp, roles=T.INSPECTOR_ROLES)
# Снимок реального хода с маркером в базовом тексте.
pc.compose_prompt(pc.PromptPlan(profile=pc.PROFILE_SPEECH_PLAIN,
                                writer="l2_writer", chat_id=T.CHAT_A,
                                run_id="r4snapshot", base_prompt=SNAP,
                                gates=pc.gates_from_config()))
pc.reset_provider_calls()
pc.record_provider_call(payload={"probe": 1},
                        messages=[{"role": "system", "content": RING},
                                  {"role": "user", "content": "u"}],
                        correlation_id="r4corr", chat_id=T.CHAT_A)
h = T._hdr(T.LOCAL_ADMIN, T.CHAT_A)
print("tree:", ROOT)
plain = client.get("/api/speech/inspector", headers=h)
sent = ""
exact = ""
try:
    body = plain.json()
    sent = str((body.get("sent") or {}).get("system_masked") or "")
    exact = str((body.get("exact") or {}).get("system") or "")
except Exception:
    body = {}
print("inspector plain:", plain.status_code,
      "| sent mark:", SNAP in sent,
      "| exact mark:", RING in exact,
      "| restricted:", (body.get("sent") or {}).get("text_restricted", ""))
corr = client.get("/api/speech/inspector?correlation_id=r4corr", headers=h)
print("inspector?correlation_id:", corr.status_code, "mark:", RING in corr.text)
adm = client.get("/api/speech/inspector", headers=T._hdr(T.ADMIN, T.CHAT_A))
print("inspector admin: sent mark:", SNAP in adm.text, "| ring mark:", RING in adm.text)
pc.reset_provider_calls()
pc.reset_state()
mp.undo_all()
