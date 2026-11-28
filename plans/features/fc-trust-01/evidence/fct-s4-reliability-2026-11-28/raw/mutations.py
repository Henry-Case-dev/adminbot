"""FCT-1001/1002 мутационная проверка (Builder, 2026-11-28).

Каждая мутация — минимальная порча реального механизма; соответствующий
детерминированный тест обязан стать RED. После прогона файл возвращается
`git checkout --` (дерево снова = candidate bd454b4fe).

Запуск (из worktree): python <этот файл> > raw/mutations.txt
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    encoding="utf-8").stdout.strip())
PY = sys.executable
TEST = "tests/test_fc_trust_s4_reliability.py"
RETRIEVAL = "tests/test_fc_trust_retrieval.py"

MUTATIONS = [
    {
        "id": "M-FCT1001-PARK",
        "file": "services/embedding_control_plane.py",
        "why": "убрать парковку отказавшей ноги в credential_health",
        "old": """        self._registry.mark_credential(
            credential.alias, HEALTH_COOLDOWN,
            cooldown_s=_PROVIDER_UNAVAILABLE_COOLDOWN_S,
            key_fp=credential_key_fingerprint(credential.api_key))""",
        "new": """        if False:  # mutation: no parking
            self._registry.mark_credential(
                credential.alias, HEALTH_COOLDOWN,
                cooldown_s=_PROVIDER_UNAVAILABLE_COOLDOWN_S,
                key_fp=credential_key_fingerprint(credential.api_key))""",
        "test": f"{TEST}::TestFCT1001ProviderFallback::"
                "test_failed_leg_is_parked_and_serving_leg_is_healthy",
    },
    {
        "id": "M-FCT1001-SPEND-PARK",
        "file": "services/embedding_control_plane.py",
        "why": "убрать kind-aware парковку 429 spend (старый короткий кулдаун)",
        "old": """    if not quota_kind_parking_enabled():
        return retry_after_seconds(info), False, \"\"""",
        "new": """    return retry_after_seconds(info), False, ""
    if not quota_kind_parking_enabled():
        return retry_after_seconds(info), False, \"\"""",
        "test": f"{TEST}::TestFCT1001ProviderFallback::"
                "test_all_legs_spend_parked_is_bounded_and_honest",
    },
    {
        "id": "M-FCT1001-BACKOFF",
        "file": "services/embedding_control_plane.py",
        "why": "убрать транспортный backoff (немедленный повтор)",
        "old": """                await asyncio.sleep(min(
                    _TRANSPORT_BACKOFF_BASE * (2 ** (stats.attempts - 1)),
                    _TRANSPORT_BACKOFF_CAP))""",
        "new": """                await asyncio.sleep(0)  # mutation: no backoff""",
        "test": f"{TEST}::TestFCT1001ProviderFallback::"
                "test_single_leg_transport_backoff_is_bounded",
    },
    {
        "id": "M-FCT1001-CANCEL-REFUND",
        "file": "handlers/factcheck.py",
        "why": "отмена не возвращает пользовательский слот",
        "old": "    refunded = await _refund_cooldown(chat_id, user_id, "
               "_CANCELLED_OUTCOME)",
        "new": "    refunded = True  # mutation: slot not refunded",
        "test": f"{TEST}::TestFCT1001CooperativeCancel::"
                "test_cancelled_check_stops_and_refunds_user_limit",
    },
    {
        "id": "M-FCT1001-SINGLEFLIGHT",
        "file": "services/persistent_throttling.py",
        "why": "вернуть неатомарную пару remaining()+touch()",
        "old": """        try:
            return await _db_write(self._db, _body, op_name="throttle_claim",
                                   chat_id=chat_id)""",
        "new": """        try:
            # mutation: старое неатомарное окно между проверкой и занятием
            remaining = await self.remaining(chat_id, user_id)
            if remaining > 0:
                return False, remaining
            await self.touch(chat_id, user_id)
            return True, 0.0""",
        "test": f"{TEST}::TestFCT1001SingleFlight::"
                "test_persistent_tracker_does_not_double_provider_call",
    },
    {
        "id": "M-FCT1001-LIMIT-EARLY",
        "file": "handlers/factcheck.py",
        "why": "не возвращать слот после технического/раннего отказа",
        "old": "    if outcome in _EARLY_OUTCOMES:",
        "new": "    if False:  # mutation: early refusal consumes the limit",
        "test": f"{TEST}::TestFCT1001LimitAccounting::"
                "test_technical_error_refunds_and_verdict_keeps",
    },
    {
        "id": "M-FCT1002-CACHE",
        "file": "services/factcheck_context.py",
        "why": "убрать chat_id из идентичности кэша среза",
        "old": '        "chat_id": ctx.chat_id,\n',
        "new": "",
        "test": f"{TEST}::TestFCT1002ChatIsolation::"
                "test_slice_cache_never_serves_another_chat",
    },
    {
        "id": "M-FCT1002-EGRESS",
        "file": "services/factcheck_orchestrator.py",
        "why": "просочить внутренние evidence_refs в публикуемый текст",
        "old": "    text = _egress_clean(verdict.verdict_text)",
        "new": "    text = (_egress_clean(verdict.verdict_text) + \" \"\n"
               "            + \" \".join(verdict.evidence_refs))  # mutation",
        "test": f"{TEST}::TestFCT1002ChatIsolation::"
                "test_published_payload_has_no_internal_fields_or_foreign_links",
    },
    {
        "id": "M-FCT1002-MIX",
        "file": "services/factcheck_service.py",
        "why": "общий глобальный coverage между одновременными прогонами чатов",
        "old": """    parts = [dict(p) for p in (verdict.parts or ()) if isinstance(p, dict)]""",
        "new": """    # mutation: общий кэш покрытия между чатами
    _shared = globals().get("_MUT_SHARED_COVERAGE")
    if _shared is not None:
        coverage = _shared
    else:
        globals()["_MUT_SHARED_COVERAGE"] = coverage
    parts = [dict(p) for p in (verdict.parts or ()) if isinstance(p, dict)]""",
        "test": f"{TEST}::TestFCT1002ChatIsolation::"
                "test_roles_and_sources_do_not_mix_between_chats",
    },
    {
        "id": "M-FCT1001-PLANNER-CANCEL",
        "file": "services/factcheck_planner.py",
        "why": "игнорировать кооперативную отмену в retrieval-контуре",
        "old": """    def _cancel_requested() -> bool:
        if is_cancelled is None:
            return False""",
        "new": """    def _cancel_requested() -> bool:
        return False  # mutation: cancellation ignored
        if is_cancelled is None:
            return False""",
        "test": f"{RETRIEVAL}::test_cancelled_run_is_reported_as_cancelled",
    },
]


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main() -> int:
    failed = 0
    for m in MUTATIONS:
        path = ROOT / m["file"]
        original = path.read_text(encoding="utf-8")
        count = original.count(m["old"])
        print(f"\n=== {m['id']} | {m['file']} | {m['why']}")
        print(f"anchor_occurrences={count}")
        if count != 1:
            print("RESULT: SETUP_FAILED")
            failed += 1
            continue
        mutated = original.replace(m["old"], m["new"], 1)
        try:
            path.write_text(mutated, encoding="utf-8")
            proc = run([PY, "-m", "pytest", m["test"], "-q", "--no-header",
                        "-p", "no:cacheprovider"])
            lines = [ln for ln in proc.stdout.splitlines()
                     if ln.startswith(("FAILED", "ERROR")) or
                     "passed" in ln or "failed" in ln]
            for ln in lines[-6:]:
                print(ln)
            print(f"RESULT: {'RED (ok)' if proc.returncode == 1 else 'NOT_RED'}")
            if proc.returncode != 1:
                failed += 1
        finally:
            path.write_text(original, encoding="utf-8")
            rev = run(["git", "checkout", "--", m["file"]])
            if rev.returncode != 0:
                print("REVERT_FAILED", rev.stderr)
                failed += 1
    print(f"\nmutations={len(MUTATIONS)} unexpected={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
