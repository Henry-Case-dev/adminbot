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


def _secret_key_sets():
    """Легаси-набор (`spec.secret`) против канонического (`is_secret_value`)."""
    from services import output_projection

    legacy = {spec.pg_key for spec in catalog.REGISTRY.values() if spec.secret}
    canonical = set(output_projection._catalog_secret_keys())
    return legacy, canonical


def _reproduce_single_source_of_truth():
    """Ревью-блокер: SECRET_VALUE + secret=False обязан защищаться.

    Возвращает наблюдаемые факты и всегда убирает временную запись.
    """
    import config.settings as settings_module

    token_env = "env-sot-token-13579"
    token_settings = "settings-sot-token-24680"
    token_cache = "cache-sot-token-35791"
    field = "SOT_TEMP_PROVIDER_API_KEY"
    pg_key = "keys.sot_temp_provider_api_key"

    class _Proxy:
        def __init__(self, base):
            object.__setattr__(self, "_base", base)

        def __getattr__(self, name):
            if name == field:
                return token_settings
            return getattr(object.__getattribute__(self, "_base"), name)

    class _Cache:
        def get(self, key, default=None):
            return token_cache if str(key) == pg_key else default

    spec = catalog.ParamSpec(field, field, catalog.CATEGORY_KEYS,
                             "SOT temp provider", "str", secret=False,
                             sensitivity=catalog.SENSITIVITY_SECRET)
    facts = {}
    old_env = os.environ.get(field)
    original_settings = settings_module.settings
    try:
        catalog.register_param(spec, replace=True)
        os.environ[field] = token_env
        settings_module.settings = _Proxy(original_settings)
        projection.reset_secret_cache()
        snapshot = projection.known_secret_values(cache=_Cache(),
                                                  use_cache=False)
        sanitized = projection.sanitize(
            f"token env={token_env} cfg={token_settings} pg={token_cache}",
            kind="tool_result", secrets=snapshot)
        from services import log_ring
        log_ring._SECRETS = None
        log_line = log_ring.sanitize(f"ERROR {token_settings}")
        from services import debug_config

        class _DumpCache(_Cache):
            is_initialized = True
            pg_available = True
            loaded_at = "2026-11-13T00:00:00+00:00"

            def get_all(self):
                return {pg_key: token_cache}

            def get_updated_at(self, key):
                return None

        dump_item = debug_config.build_dump(_DumpCache(), key=pg_key)["item"]
        stored = catalog.get_by_pg_key(pg_key)
        facts = {
            "registered": stored is not None,
            "resolved_sensitivity": stored.resolved_sensitivity if stored else None,
            "legacy_secret_flag": stored.secret if stored else None,
            "is_secret_value": stored.is_secret_value if stored else None,
            "snapshot_values_total": len(snapshot.values),
            "snapshot_knows_env": token_env in snapshot.values,
            "snapshot_knows_settings": token_settings in snapshot.values,
            "snapshot_knows_cache": token_cache in snapshot.values,
            "sanitize_status": sanitized.report.status,
            "sanitize_kept_any_token": any(
                token in sanitized.text
                for token in (token_env, token_settings, token_cache)),
            "log_line_masked": token_settings not in log_line,
            "debug_dump_secret": dump_item.get("secret"),
            "debug_dump_masked": token_settings not in str(
                dump_item.get("value")),
        }
    finally:
        catalog.REGISTRY.pop(field, None)
        catalog._BY_PG_KEY.pop(pg_key, None)
        settings_module.settings = original_settings
        if old_env is None:
            os.environ.pop(field, None)
        else:
            os.environ[field] = old_env
        projection.reset_secret_cache()
    return facts


def main():
    head = _git("rev-parse", "HEAD")
    base = "16fa04e77c56db44c23cb5c8a9386f6cfd756628"
    legacy_keys, canonical_keys = _secret_key_sets()
    sot = _reproduce_single_source_of_truth()
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
        "single_source_of_truth": {
            "predicate": "ParamSpec.is_secret_value "
                         "(resolved_sensitivity == SECRET_VALUE)",
            "consumers": [
                "output_projection._catalog_secret_keys",
                "output_projection._settings_secret_values",
                "output_projection._env_secret_values",
                "log_ring._collect_secrets",
                "debug_config._is_secret",
            ],
            "legacy_secret_key_count": len(legacy_keys),
            "canonical_secret_key_count": len(canonical_keys),
            "keys_lost": sorted(legacy_keys - canonical_keys),
            "keys_added": sorted(canonical_keys - legacy_keys),
            "reviewer_reproduction": sot,
            "fix_red_on": "f2f2583821a1ead995ce164becdf791ce9927d01",
            "fix_red_result": "3 failed: snapshot empty, log line kept the "
                              "token, debug dump secret=False (raw value)",
        },
        "tests": [_pytest("tests/test_param_sensitivity_registration.py"),
                  _pytest("tests/test_param_catalog.py"),
                  _pytest("tests/test_log_ring.py"),
                  _pytest("tests/test_debug_config.py")],
        "red": {
            "base_run": ("tests/test_param_sensitivity_registration.py on "
                         f"{base[:8]}: 10 failed "
                         "(AttributeError: module 'services.param_catalog' has "
                         "no attribute 'SENSITIVITY_PROMPT_CONTENT' / "
                         "no attribute 'register_param')"),
            "green_run": ("tests/test_param_sensitivity_registration.py: "
                          "13 passed (10 первого раунда + 3 регрессии "
                          "единого предиката)"),
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
