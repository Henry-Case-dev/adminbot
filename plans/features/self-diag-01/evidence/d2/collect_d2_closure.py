"""D2 closure evidence collector: measures the real candidate, writes JSON.

Run from the repository worktree root:
    python plans/features/self-diag-01/evidence/d2/collect_d2_closure.py <out_dir>

Не является тестом и не входит в набор приёмки: одноразовый измеритель
фактических значений для evidence-файлов `sd1_d2_23.json`/`sd1_d2_24.json`.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "evidence")

sys.path.insert(0, ROOT)

from services import output_projection as projection   # noqa: E402
from services import param_catalog as catalog          # noqa: E402
from services import settings_view                      # noqa: E402


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def _pytest(*paths):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *paths, "-q", "-p",
         "no:cacheprovider", "--tb=line"],
        cwd=ROOT, capture_output=True, text=True)
    tail = [line for line in proc.stdout.splitlines() if line.strip()][-1:]
    return {"command": "python -m pytest " + " ".join(paths) + " -q",
            "exit_code": proc.returncode, "summary": tail[0] if tail else ""}


def main():
    head = _git("rev-parse", "HEAD")
    base = "16fa04e77c56db44c23cb5c8a9386f6cfd756628"
    sensitivity = {}
    for spec in catalog.REGISTRY.values():
        key = spec.resolved_sensitivity
        sensitivity[key] = sensitivity.get(key, 0) + 1
    sources = {}
    for spec in catalog.REGISTRY.values():
        key = spec.sensitivity_source
        sources[key] = sources.get(key, 0) + 1

    d2_23 = {
        "row": "SD1-D2-23",
        "candidate_commit": head,
        "base_commit": base,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "source_line": 269,
        "contract": ("Источник истины о секретных полях — каталог/secret store "
                     "с типами sensitivity; для нового провайдера sensitivity "
                     "обязательна при регистрации."),
        "measured": {
            "registry_entries": len(catalog.REGISTRY),
            "sensitivity_distribution": sensitivity,
            "sensitivity_source_distribution": sources,
            "audit_problems": catalog.audit_sensitivity(),
            "sensitivity_values": list(catalog.SENSITIVITY_VALUES),
            "secret_keys": len(catalog.secret_setting_specs()),
            "projection_matches_catalog": all(
                projection.sensitivity_of_pg_key(spec.pg_key)
                == spec.resolved_sensitivity
                for spec in catalog.REGISTRY.values()),
            "keys_llm_api_key": catalog.get_by_pg_key(
                "keys.llm_api_key").secret,
            "keys_llm_api_key_sensitivity": catalog.get_by_pg_key(
                "keys.llm_api_key").resolved_sensitivity,
            "flags_checkup_enabled_sensitivity": catalog.get_by_pg_key(
                "flags.checkup_enabled").resolved_sensitivity,
            "prompt_sensitivity": catalog.get_by_pg_key(
                "prompts.checkup_system_prompt").resolved_sensitivity,
        },
        "registration_gate": {
            "api": "services.param_catalog.register_param",
            "error_without_sensitivity": "ParamSensitivityRequired",
            "error_on_contradiction": "ParamSensitivityError",
            "import_time_audit": "ParamSensitivityError on contradictory rows",
        },
        "tests": [_pytest("tests/test_param_sensitivity_registration.py"),
                  _pytest("tests/test_param_catalog.py")],
        "red": {
            "base_run": ("tests/test_param_sensitivity_registration.py on "
                         f"{base[:8]}: 10 failed "
                         "(AttributeError: module 'services.param_catalog' has "
                         "no attribute 'SENSITIVITY_PROMPT_CONTENT' / "
                         "no attribute 'register_param')"),
            "green_run": "tests/test_param_sensitivity_registration.py: 10 passed",
        },
    }

    fake_cache = type("C", (), {
        "get": lambda self, key, default=None: {
            "keys.image_api_key": "sk-live-abcdef123456",
            "limits.checkup_max_symbols": 1200,
        }.get(str(key), default)})()

    secret_view = settings_view.setting_view("keys.image_api_key",
                                             cache=fake_cache)
    config_view = settings_view.setting_view("limits.checkup_max_symbols",
                                             cache=fake_cache)
    summary = settings_view.secret_status_summary(cache=fake_cache)
    d2_24 = {
        "row": "SD1-D2-24",
        "candidate_commit": head,
        "base_commit": base,
        "source_line": 270,
        "contract": ("Секретный blob никогда не сериализуется в "
                     "DiagnosticEvidenceBundle или обычный ToolResult; "
                     "возвращаются configured/effective/last_success/"
                     "last_error_code/key_fingerprint."),
        "measured": {
            "adapter": "services.settings_view.setting_view",
            "view_fields": list(settings_view.VIEW_FIELDS),
            "secret_view": secret_view,
            "secret_value_in_view": "sk-live-abcdef123456" in json.dumps(
                secret_view, ensure_ascii=False),
            "config_view_effective": config_view["effective"],
            "config_view_value_exposed": config_view["value_exposed"],
            "summary_total": summary["total"],
            "summary_configured": summary["configured"],
            "summary_value_exposed": summary["value_exposed"],
            "bundle_probe": "config.secret_status",
            "bundle_source_id": "config:secret_status",
        },
        "tests": [_pytest("tests/test_diagnostic_settings_adapter.py"),
                  _pytest("tests/test_evidence_bundle.py"),
                  _pytest("tests/test_diagnostic_probes.py")],
        "red": {
            "base_run": ("tests/test_diagnostic_settings_adapter.py on "
                         f"{base[:8]}: collection error ImportError: cannot "
                         "import name 'settings_view' from 'services'"),
            "green_run": "tests/test_diagnostic_settings_adapter.py: 12 passed",
        },
        "honest_limits": [
            "last_success/last_error_code заполняются только там, где "
            "capability_registry уже наблюдал исход (image/web_search/"
            "dependencies); остальные ключи — None + outcome_observed=false, "
            "not_checked содержит live_provider_probe.",
            "key_fingerprint — last4 (уже принятая проектом форма); списки, "
            "промпты и значения короче 8 символов фингерпринта не получают.",
            "Список подробностей ограничен MAX_DETAILED_SECRETS=20, остальные "
            "имена видны в truncated_keys; значение секрета не выдаётся ни в "
            "одном поле.",
            "Реальный прод-рантайм и реальные коды ошибок провайдеров не "
            "проверялись: деплоя в этой задаче нет.",
        ],
    }

    os.makedirs(OUT, exist_ok=True)
    for name, payload in (("sd1_d2_23.json", d2_23),
                          ("sd1_d2_24.json", d2_24)):
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1,
                      sort_keys=False)
            handle.write("\n")
        print("wrote", path)


if __name__ == "__main__":
    main()
