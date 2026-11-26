"""RED/поведенческий пробник choke point: один и тот же сценарий на дереве.

Запуск: python redex_probe.py <tree-root>
Импортирует стенд из замка ТОГО дерева (до/после корректива) и печатает
статусы 6 поверхностей r3 + наличие маркера в теле.
"""
import os
import sys
import types

ROOT = os.path.abspath(sys.argv[1])
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)

import tests.test_mod_acl_ux_01_m1c_prompt_chat_acl as T  # noqa: E402


class MP:
    def __init__(self):
        self.undo = []

    def setattr(self, obj, name, value):
        self.undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo_all(self):
        for obj, name, old in reversed(self.undo):
            setattr(obj, name, old)


def token(mp):
    mp.setattr(T.deps_mod, "settings",
               types.SimpleNamespace(API_TOKEN=T.TEST_TOKEN))


T.pr.set_release_policy_active(True)
BASE = "prompts.direct_chat_verbalizer_system_prompt"
MARK = "M1C-CHOKE-MARK"
DENY = {"view_roles": ["moderator"], "edit_roles": ["moderator"]}

mp = MP()
token(mp)
client = T.make_client(mp, matrix=DENY, matrix_key=BASE)
T._patch_chat_root(mp, overrides={BASE: MARK})
h = T._hdr(T.LOCAL_ADMIN, T.CHAT_A)
block = T.pr.by_pg_key(BASE).block_id
print("tree:", ROOT)
print("TREE_ROOT_MARKER present in /api/speech/try:")
r = client.post("/api/speech/try", json={"text": "привет"}, headers=h)
print("  try:", r.status_code, "mark:", MARK in r.text)
print("  reset:", client.post(f"/api/speech/block/{block}/reset",
                              json={"mode": "chat"}, headers=h).status_code)
print("  rollback:", client.post(
    f"/api/speech/block/{block}/rollback",
    json={"revision": "rev:abcdef123456", "sha256_12": "abcdef123456"},
    headers=h).status_code)
mp.undo_all()

mp2 = MP()
token(mp2)
INSPECTOR_ROLES = {
    **T.ROLES,
    "local_admin": {"permissions": {"sections": ["limits", "flags", "content"],
                                    "actions": ["edit_persona"]},
                    "is_custom": False, "role_type": "local_admin"},
}
c3 = T.make_client(mp2, matrix=DENY, matrix_key=BASE, roles=INSPECTOR_ROLES)
T._patch_chat_root(mp2, overrides={BASE: MARK})
r3 = c3.get("/api/speech/inspector",
            headers=T._hdr(T.LOCAL_ADMIN, T.CHAT_A))
print("  inspector(edit_persona):", r3.status_code, "mark:", MARK in r3.text)
mp2.undo_all()

mp3 = MP()
token(mp3)
key = T.mi.prompt_setting_key(T.mi.IMAGE_PROMPT_BLOCK_ID)
c2 = T.make_client(mp3, matrix={"view_roles": ["local_admin"],
                                "edit_roles": []}, matrix_key=key)
resp = c2.post("/api/initiative/meme-settings",
               json={"prompt_image": "M1C-CHOKE-MEME"},
               headers=T._hdr(T.LOCAL_ADMIN, T.CHAT_A))
print("  meme POST:", resp.status_code)
mp3.undo_all()
