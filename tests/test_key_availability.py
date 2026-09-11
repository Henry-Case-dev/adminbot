"""Редизайн 10.5 (T-1139/T-1140/T-1148) — key-availability backend.

Покрывает:
  * OD11/OD16 safe migration: ``StatusService.llm_registry()`` — модели/base_url
    data-driven, дефолты = прежние литералы (``status.llm[]`` до/после идентичен);
  * OD12/OD19 leak-safety ``services/key_history.py``: allowlist-схема, атомарная
    запись, восстановление после рестарта, отсутствие сырых ключей, gitignore.
"""
import json
import os
import subprocess
from pathlib import Path

from services import hot_config as hot
from services.key_history import (
    KeyHistory,
    has_forbidden_content,
)
from services.status_service import StatusService


class _FakeCache:
    """Минимальный ConfigCache-стаб: get(key, default)."""

    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class TestSafeMigration:
    """OD11/OD16: ноль активного хардкода; значения сохраняются."""

    def test_defaults_match_previous_literals(self):
        hot.set_config_cache(None)
        reg = StatusService.llm_registry()
        by = {p["module_id"]: p for p in reg}
        assert by["stt_groq"]["base_url"] == "https://api.groq.com/openai/v1"
        assert by["stt_groq"]["model"] == "whisper-large-v3"
        assert by["stt_openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
        assert by["stt_openrouter"]["model"] == "openrouter/free"
        # 10.9: provider = host из base_url (без хардкода имён).
        assert by["stt_groq"]["provider"] == "api.groq.com"
        assert by["stt_openrouter"]["module_title"]
        assert by["stt_groq"]["model_source"] == "code"

    def test_configured_values_win_and_source_config(self):
        hot.set_config_cache(_FakeCache({
            "models.groq_base_url": "https://proxy.local/v1",
            "models.groq_transcribe_model": "whisper-custom",
            "models.openrouter_base_url": "https://or.local/v1",
            "models.openrouter_transcribe_model": "or/custom",
        }))
        try:
            by = {p["module_id"]: p for p in StatusService.llm_registry()}
        finally:
            hot.set_config_cache(None)
        assert by["stt_groq"]["base_url"] == "https://proxy.local/v1"
        assert by["stt_groq"]["model"] == "whisper-custom"
        assert by["stt_groq"]["model_source"] == "config"
        assert by["stt_openrouter"]["model"] == "or/custom"

    def test_catalog_rows_present_pg_only(self):
        from services.param_catalog import REGISTRY
        by_key = {s.pg_key: s for s in REGISTRY.values()}
        for pg_key in ("models.groq_base_url", "models.groq_transcribe_model",
                       "models.openrouter_base_url",
                       "models.openrouter_transcribe_model"):
            spec = by_key[pg_key]
            assert spec.settings_field is None      # PG-only (OD11/OD16)
            assert spec.env_name is None
            assert spec.group == "models_extra_providers"


class TestBaseUrlHotReload:
    """Reviewer D3/OD16: смена models.*_base_url из UI должна пересобирать
    реальные клиенты (Groq/OpenRouter/Video), даже если ключ не менялся."""

    def test_groq_client_rebuilds_on_base_url_change(self):
        from SmartModule.transcriber.groq_transcriber import GroqTranscriber
        cache = _FakeCache({
            "keys.groq_api_key": "gsk_test_key",
            "models.groq_base_url": "https://a.example/v1",
        })
        hot.set_config_cache(cache)
        try:
            t = GroqTranscriber(api_key="gsk_test_key")
            t._default_key = "gsk_test_key"      # ключ «не менялся»
            assert str(t._client.base_url).startswith("https://a.example")
            cache._values["models.groq_base_url"] = "https://b.example/v1"
            t._refresh_client()
            assert str(t._client.base_url).startswith("https://b.example")
        finally:
            hot.set_config_cache(None)

    def test_openrouter_client_rebuilds_on_base_url_change(self):
        from SmartModule.transcriber.openrouter_transcriber import (
            OpenRouterTranscriber,
        )
        cache = _FakeCache({
            "keys.openrouter_api_key": "sk_test_key",
            "models.openrouter_base_url": "https://a.example/v1",
        })
        hot.set_config_cache(cache)
        try:
            t = OpenRouterTranscriber(api_key="sk_test_key")
            t._default_key = "sk_test_key"
            assert str(t._client.base_url).startswith("https://a.example")
            cache._values["models.openrouter_base_url"] = "https://b.example/v1"
            t._refresh_client()
            assert str(t._client.base_url).startswith("https://b.example")
        finally:
            hot.set_config_cache(None)

    def test_video_client_rebuilds_on_base_url_change(self):
        from services.video_cascade_client import OpenRouterVideoClient
        cache = _FakeCache({
            "keys.openrouter_api_key": "sk_test_key",
            "models.openrouter_base_url": "https://a.example/v1",
        })
        hot.set_config_cache(cache)
        try:
            c = OpenRouterVideoClient(api_key="sk_test_key")
            assert str(c._get_client().base_url).startswith("https://a.example")
            cache._values["models.openrouter_base_url"] = "https://b.example/v1"
            assert str(c._get_client().base_url).startswith("https://b.example")
        finally:
            hot.set_config_cache(None)


def _sample_history(tmp_path: Path) -> KeyHistory:
    return KeyHistory(path=tmp_path / "status_key_history.json")


class TestKeyHistoryLeakSafety:
    def test_allowlist_only_in_file(self, tmp_path):
        hist = _sample_history(tmp_path)
        hist.record("stt_groq", "groq", "whisper-large-v3", True, 200,
                    ts=1_700_000_000, module_title="Транскрипт")
        assert hist.save() is True
        raw = (tmp_path / "status_key_history.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert set(data.keys()) == {"version", "generated_at", "providers"}
        prov = data["providers"][0]
        assert set(prov.keys()) == {"module_id", "provider", "model", "samples"}
        sample = prov["samples"][0]
        assert set(sample.keys()) == {"ts", "ok", "http_status"}
        # module_title НЕ пишется в файл (только в API-ответ).
        assert "module_title" not in raw
        assert "last4" not in raw

    def test_no_raw_secrets_marker(self, tmp_path):
        hist = _sample_history(tmp_path)
        hist.record("stt_groq", "groq", "whisper-large-v3", False, 401,
                    ts=1_700_000_000)
        hist.save()
        raw = (tmp_path / "status_key_history.json").read_text(encoding="utf-8")
        assert not has_forbidden_content(raw)
        for bad in ("sk-", "gsk_", "Bearer", "authorization", "api_key",
                    "initData", "password"):
            assert bad.lower() not in raw.lower()

    def test_atomic_and_restart_persistence(self, tmp_path):
        p = tmp_path / "status_key_history.json"
        hist = _sample_history(tmp_path)
        hist.record("llm_main", "deepseek", "deepseek-v4-flash", True, 200,
                    ts=1_700_000_000, module_title="Прямые ответы")
        hist.record("llm_main", "deepseek", "deepseek-v4-flash", False, 500,
                    ts=1_700_000_400)   # другой 5-мин слот
        assert hist.save()
        # нет .tmp-мусора (атомарность через os.replace)
        assert not list(tmp_path.glob("*.tmp"))
        assert not list(tmp_path.glob(".keyhist-*"))

        # «рестарт»: новый объект читает снимок.
        restarted = KeyHistory(path=p)
        payload = restarted.api_payload()
        prov = payload["providers"][0]
        assert prov["module_id"] == "llm_main"
        # module_title НЕ персистится (allowlist файла) → fallback на module_id.
        assert prov["module_title"] == "llm_main"
        assert [s["ok"] for s in prov["samples"]] == [True, False]
        assert [s["http_status"] for s in prov["samples"]] == [200, 500]

    def test_upsert_same_bucket(self, tmp_path):
        hist = _sample_history(tmp_path)
        hist.record("llm_main", "deepseek", "m", True, 200, ts=1_700_000_010)
        hist.record("llm_main", "deepseek", "m", False, 503, ts=1_700_000_020)
        samples = hist.api_payload()["providers"][0]["samples"]
        assert len(samples) == 1                      # тот же 5-мин слот
        assert samples[0]["http_status"] == 503

    def test_corrupt_file_fail_open(self, tmp_path):
        p = tmp_path / "status_key_history.json"
        p.write_text("{not valid json", encoding="utf-8")
        hist = KeyHistory(path=p)
        payload = hist.api_payload()
        assert payload["providers"] == []             # fail-open, без падения

    def test_ring_capped(self, tmp_path):
        from services.key_history import MAX_SAMPLES
        hist = _sample_history(tmp_path)
        for i in range(MAX_SAMPLES + 10):
            hist.record("x", "p", "m", True, 200, ts=1_700_000_000 + i * 300)
        assert len(hist.api_payload()["providers"][0]["samples"]) <= MAX_SAMPLES

    def test_gitignored(self):
        env = dict(os.environ)
        for target in ("var/status_key_history.json", "var/",
                       "MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2"):
            res = subprocess.run(
                ["git", "check-ignore", target],
                capture_output=True, text=True, env=env)
            assert res.returncode == 0, target   # ignored

    def test_tests_do_not_pollute_real_var(self):
        # M6: conftest перенаправляет singleton в temp (не var/).
        import tempfile
        from services.status_service import key_history
        p = str(key_history._path)
        assert "adminbot_test_keyhist" in p
        assert p.startswith(tempfile.gettempdir())

    def test_no_dead_allowlist_constant(self):
        # R10.5-4: мёртвый _ALLOWED_PROVIDER_KEYS удалён.
        import services.key_history as kh
        assert not hasattr(kh, "_ALLOWED_PROVIDER_KEYS")
