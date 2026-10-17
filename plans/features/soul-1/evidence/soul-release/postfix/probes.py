# -*- coding: utf-8 -*-
"""FIX-SOUL-F1F3 — focused probes for the F1 (summary_l2_writer cleanup)
and F3 (/persona phrase) fix.

Runs the REAL registry code against the factory canon and prints the
observable contract:
  * F1: gate marker fires; exactly two rules remove the legacy-voice
    instruction and the dvach vocabulary; section header stays; contracts
    intact; idempotent; custom untouched; code fallback (PG down) byte-equal.
  * F3: /persona phrase has the {tone} slot, no old-persona markers; registry
    reclassified (legacy_persona off, revision label bumped); the old text is
    still caught by the guard (regression detection).
  * fingerprint guard constant matches ``factory_set_fingerprint()``.

Run from the repo root:  py -3 <this file>
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve()
for _ in range(12):
    REPO = REPO.parent
    if (REPO / "services" / "prompt_registry.py").exists():
        break
sys.path.insert(0, str(REPO))

from services import prompt_registry as pr      # noqa: E402
from services import summary_prompts as sp      # noqa: E402
from services.smartmodule_phrases import CHAT_PERSONA_PHRASE  # noqa: E402


def sha12(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def main() -> int:
    print("== F1: summary.base.l2_writer cleanup (resolve-time, source=global) ==")
    canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
    stripped, info = pr.suppress_legacy_speech(canon, source="global")
    print("canon sha12 / len        :", sha12(canon), len(canon))
    print("effective sha12 / len    :", sha12(stripped), len(stripped))
    print("known_canon / marker     :", info.known_canon, "/", info.legacy_present)
    print("removed / labels         :", info.removed, list(info.labels))
    print("F1 phrase gone           :",
          "сохраняй характер бота и атмосферу конфы" not in stripped)
    print("dvach phrase gone        :", "двачерские обороты" not in stripped)
    print("Core voice present       :", "держи голос Core" in stripped)
    print("sarcasm/slang/mat kept   :",
          "Сарказм, интернет-сленг и мат разрешены" in stripped)
    print("section header kept      :", "СТИЛЬ (характер бота)" in stripped)
    contracts = ("ГРАММАТИКА", "ФАКТЫ И МОДАЛЬНОСТЬ", "ЭВИДЕНЦИЯ", "АКЦЕНТЫ",
                 "ЖЁСТКИЕ ПРАВИЛА", "ФИНАЛ", "ДЛИНА И ДЕДУПЛИКАЦИЯ",
                 "АВТОРЫ И ОТВЕТЫ В ПАКЕТЕ")
    print("contracts intact         :", all(c in stripped for c in contracts))
    again, second = pr.suppress_legacy_speech(stripped, source="global")
    print("idempotent               :", again == stripped and second.removed == 0)
    custom = canon + "\n\nправка владельца"
    print("custom untouched         :",
          pr.suppress_legacy_speech(custom, source="global")[0] == custom)
    print("code fallback unchanged  :",
          pr.suppress_legacy_speech(canon, source="default")[0] == canon)
    print()
    print("== F3: /persona phrase ==")
    print("phrase                   :", CHAT_PERSONA_PHRASE)
    print("{tone} slot kept         :", "{tone}" in CHAT_PERSONA_PHRASE)
    print("legacy marker in phrase  :",
          pr.legacy_persona_present(CHAT_PERSONA_PHRASE))
    spec = pr.block("message.smartmodule.chat_persona")
    print("registry legacy_persona  :", spec.legacy_persona)
    print("revision label           :",
          pr.FACTORY_REVISION_LABELS.get(spec.block_id))
    old_phrase = ("я тот самый токсичный бот-абьюзер. тон: {tone}. "
                  "настроение подстраиваю сам")
    print("old text caught by guard :", pr.legacy_persona_present(old_phrase))
    print()
    print("== registry guard ==")
    print("factory_set_fingerprint  :", pr.factory_set_fingerprint())
    print("FACTORY_SET_SHA256_12    :", pr.FACTORY_SET_SHA256_12)
    print("match                    :",
          pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
