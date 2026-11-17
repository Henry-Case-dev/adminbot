"""QRNG P3 — mutation-проба селектора (red-proof каждого инварианта).

Запуск из корня worktree:
`python plans/features/vmq-onto-01/evidence/qrng-recovery/p3/mutation_probe.py`

Каждая мутация — точная байтовая замена (ровно одно вхождение) в
`services/mca_random_source.py` или `services/param_catalog.py`, затем
целевой pytest-набор. Файлы восстанавливаются в `finally`; sha256 сверяется.
Сети не касается. JSON — один объект в stdout.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
MODULE = ROOT / "services" / "mca_random_source.py"
CATALOG = ROOT / "services" / "param_catalog.py"
ROUTES = ROOT / "web" / "api" / "routes.py"
TESTS = "tests/test_qrng_p3_selector.py"

MUTATIONS = [
    {
        "id": "M1",
        "file": MODULE,
        "mutation": "фильтр провайдера в reserve_draw/chunk отключён "
                    "(рисуется самая старая партия любого провайдера)",
        "anchor": (
            '        if not ids:\n'
            '            return " AND 0", ()\n'
            '        return (" AND provider IN (" + ",".join("?" * len(ids)) '
            '+ ")", ids)\n'
        ).encode("utf-8"),
        "replacement": b'        return "", ()\n',
        "targets": [
            f"{TESTS}::TestResolveMatrix::"
            "test_primary_lfdr_uses_lfdr_batch_not_oldest"],
    },
    {
        "id": "M2",
        "file": MODULE,
        "mutation": "снятое сохранённое значение молча считается известным "
                    "(requires_resolution → set)",
        "anchor": (
            '    return (PRIMARY_SETTING_SET if canonical_provider_id(text)\n'
            '            else PRIMARY_SETTING_REQUIRES_RESOLUTION)\n'
        ).encode("utf-8"),
        "replacement": b"    return PRIMARY_SETTING_SET\n",
        "targets": [
            f"{TESTS}::TestRetiredValue::"
            "test_unknown_saved_primary_requires_resolution",
            f"{TESTS}::TestConfigApi::test_global_unknown_provider_is_422"],
    },
    {
        "id": "M3",
        "file": CATALOG,
        "mutation": "primary_provider теряет global_only (чатовая запись "
                    "принимается)",
        "anchor": (
            '                       "LfDR QRNG (аппаратный QRNG)"),\n'
            '        global_only=True, sensitivity=SENSITIVITY_CONFIG),\n'
        ).encode("utf-8"),
        "replacement": (
            '                       "LfDR QRNG (аппаратный QRNG)"),\n'
            '        sensitivity=SENSITIVITY_CONFIG),\n'
        ).encode("utf-8"),
        "targets": [
            f"{TESTS}::TestConfigApi::"
            "test_chat_scope_write_is_422_for_all_three"],
    },
    {
        "id": "M4",
        "file": MODULE,
        "mutation": "PRNG включается без явной настройки (скрытая подмена)",
        "anchor": (
            '            if effective_provider is not None:\n'
            '                mode = MODE_QUANTUM\n'
            '            elif await self.fallback_enabled(chat_id):\n'
            '                mode = MODE_PSEUDORANDOM\n'
            '            else:\n'
            '                mode = "deferred"\n'
        ).encode("utf-8"),
        "replacement": (
            '            if effective_provider is not None:\n'
            '                mode = MODE_QUANTUM\n'
            '            else:\n'
            '                mode = MODE_PSEUDORANDOM\n'
        ).encode("utf-8"),
        "targets": [
            f"{TESTS}::TestResolveMatrix::test_all_unavailable_deferred_not_prng",
            f"{TESTS}::TestResolveMatrix::"
            "test_fallback_disabled_only_primary_then_deferred"],
    },
    {
        "id": "M5",
        "file": MODULE,
        "mutation": "fallback_order игнорируется (всегда только primary)",
        "anchor": (
            '    head = [primary]\n'
            '    for pid in tail:\n'
            '        if pid != primary and pid not in head:\n'
            '            head.append(pid)\n'
            '    return tuple(head)\n'
        ).encode("utf-8"),
        "replacement": b"    return (primary,)\n",
        "targets": [
            f"{TESTS}::TestResolveMatrix::"
            "test_primary_unavailable_falls_to_next_with_reserve",
            f"{TESTS}::TestResolveMatrix::test_primary_default_ibm_unavailable_"
            "goes_to_configured_anu"],
    },
    {
        "id": "M6",
        "file": CATALOG,
        "mutation": "validation fallback_order не проверяет id реестра",
        "anchor": (
            '        for item in items:\n'
            '            if not isinstance(item, str) or item not in ids:\n'
            '                return (f"{_QRNG_ORDER_PG_KEY}: недопустимый '
            'провайдер "\n'
            '                        f"{item!r} — допустимы только '
            'действующие id: "\n'
            '                        f"{\', \'.join(ids)}")\n'
            '            if item in seen:\n'
        ).encode("utf-8"),
        "replacement": (
            '        for item in items:\n'
            '            if item in seen:\n'
        ).encode("utf-8"),
        "targets": [
            f"{TESTS}::TestCatalogContract::test_validation_rules",
            f"{TESTS}::TestConfigApi::test_global_order_validation_422"],
    },
    {
        "id": "M7",
        "file": MODULE,
        "mutation": "LfDR refill создаёт одноразовый клиент (N1: "
                    "breaker/min-interval теряются)",
        "anchor": (
            '            batch = await lfdr_fetch(client=self._get_lfdr_client(),\n'
            '                                     length=self._batch_length())\n'
        ).encode("utf-8"),
        "replacement": (
            b"            batch = await lfdr_fetch(length=self._batch_length())\n"
        ),
        "targets": [
            f"{TESTS}::TestLfdrRuntime::test_refill_lfdr_uses_one_shared_client",
            f"{TESTS}::TestLfdrRuntime::"
            "test_shared_client_min_interval_and_breaker"],
    },
    {
        "id": "M8",
        "file": MODULE,
        "mutation": "configured=true фейково-зелёный для всех провайдеров "
                    "(IBM без конфигурации)",
        "anchor": (
            '        if pid == PROVIDER_ID_LFDR:\n'
            '            return True\n'
            '        return False\n'
        ).encode("utf-8"),
        "replacement": (
            '        if pid == PROVIDER_ID_LFDR:\n'
            '            return True\n'
            '        return True\n'
        ).encode("utf-8"),
        "targets": [
            f"{TESTS}::TestStatusDto::test_dto_fields_and_no_fake_green"],
    },
    {
        "id": "M9",
        "file": MODULE,
        "mutation": "сырое сохранённое primary подменяется каноническим при "
                    "чтении (trace снятого значения теряется)",
        "anchor": (
            '        raw = _hot_setting(SETTING_PRIMARY_PROVIDER, None)\n'
            '        return str(raw or "").strip()\n'
        ).encode("utf-8"),
        "replacement": (
            '        raw = _hot_setting(SETTING_PRIMARY_PROVIDER, None)\n'
            '        return canonical_provider_id(raw)\n'
        ).encode("utf-8"),
        "targets": [
            f"{TESTS}::TestRetiredValue::"
            "test_unknown_saved_primary_requires_resolution"],
    },
    {
        "id": "M10",
        "file": MODULE,
        "mutation": "F2: нет перехода к следующему провайдеру после неудачи "
                    "(failover выключен)",
        "anchor": (
            '            attempts.append({"provider": target, "status": "failed",\n'
            '                             "reason": result.get("reason")})\n'
            '            self._last_refill_reason = result.get("reason")\n'
            '        last = attempts[-1] if attempts else {"provider": None,\n'
        ).encode("utf-8"),
        "replacement": (
            '            attempts.append({"provider": target, "status": "failed",\n'
            '                             "reason": result.get("reason")})\n'
            '            self._last_refill_reason = result.get("reason")\n'
            '            break\n'
            '        last = attempts[-1] if attempts else {"provider": None,\n'
        ).encode("utf-8"),
        "targets": [
            f"{TESTS}::TestRefillFailover::"
            "test_anu_failure_falls_to_lfdr_and_draw_uses_it"],
    },
    {
        "id": "M11",
        "file": MODULE,
        "mutation": "F3: заводской PRNG-дефолт возвращён в true",
        "anchor": b"DEFAULT_FALLBACK = False\n",
        "replacement": b"DEFAULT_FALLBACK = True\n",
        "targets": [
            f"{TESTS}::TestFactoryPrngDefault::test_factory_default_is_false",
            f"{TESTS}::TestFactoryPrngDefault::"
            "test_new_install_without_saved_value_defers"],
    },
    {
        "id": "M12",
        "file": ROUTES,
        "mutation": "F1: chat-scope снова показывает глобальные ключи "
                    "селектора non-admin",
        "anchor": (
            '            if (not ctx.is_global_admin\n'
            '                    and key in _random_source.SELECTOR_SETTING_KEYS):\n'
            '                continue\n'
        ).encode("utf-8"),
        "replacement": (
            '            if False:\n'
            '                continue\n'
        ).encode("utf-8"),
        "targets": [
            f"{TESTS}::TestChatVisibility::"
            "test_member_chat_scope_hides_selector"],
    },
]


def _run(targets: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "--tb=no",
         "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    failed = [line.split(" ", 1)[1] for line in lines
              if line.startswith("FAILED ")]
    summary = lines[-1] if lines else ""
    return {"returncode": proc.returncode, "summary": summary,
            "failed": failed}


def main() -> dict:
    originals = {path: path.read_bytes()
                 for path in (MODULE, CATALOG, ROUTES)}
    shas = {str(path): hashlib.sha256(data).hexdigest()
            for path, data in originals.items()}
    out = {"modules": {str(k): v for k, v in shas.items()},
           "mutations": []}
    try:
        for item in MUTATIONS:
            path = item["file"]
            anchor = item["anchor"]
            original = originals[path]
            count = original.count(anchor)
            if count != 1:
                raise RuntimeError(
                    f"{item['id']}: anchor occurrences={count}, expected 1")
            path.write_bytes(original.replace(anchor, item["replacement"]))
            result = _run(item["targets"])
            killed = result["returncode"] != 0 and bool(result["failed"])
            out["mutations"].append({
                "id": item["id"], "mutation": item["mutation"],
                "file": str(path.relative_to(ROOT)),
                "targets": item["targets"],
                "returncode": result["returncode"],
                "summary": result["summary"],
                "failed": result["failed"], "killed": killed,
            })
    finally:
        for path, data in originals.items():
            path.write_bytes(data)
    restored = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in originals}
    out["restored_sha256"] = restored
    out["restored_ok"] = restored == shas
    out["all_killed"] = all(m["killed"] for m in out["mutations"])
    return out


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not (result["restored_ok"] and result["all_killed"]):
        raise SystemExit(1)
