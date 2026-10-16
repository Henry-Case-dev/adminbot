"""SOUL-13/SSRF-guard — порядок safe-fetch-гарда не зависит от trafilatura.

Регресс-контракт (инцидент, найденный лейном v6.3-tails): в
`WebContentExtractor._extract_trafilatura` проверка `mca_gates.safe_fetch_enabled()`
стояла ПОСЛЕ проверки наличия опционального пакета trafilatura. В окружении без
пакета уровень-1 падал `RuntimeError` до чтения гарда, и приватный/метадата-URL
уходил в облачные фолбеки (Tavily `/extract`, Exa `/contents`) — SSRF-инвариант
«опасное назначение не уходит в облако» держался только при установленной
trafilatura (в канонической среде баг замаскирован).

Наличие пакета переключается ЧЕРЕЗ СОБСТВЕННЫЙ ШОВ МОДУЛЯ
(`services.web_content_extractor.trafilatura = None`) — пакеты не удаляются.

TEST-LIFECYCLE: REGRESSION owner=SOUL-13/SSRF-guard
"""
from unittest.mock import MagicMock

import pytest

from services import mca_gates
from services import safe_fetch
from services.web_content_extractor import (
    WebContentExtractionFailedException,
    WebContentExtractor,
)

TAVILY_TEXT = "tavily raw_content из облачного экстрактора " * 5      # >150
TRAF_TEXT = "trafilatura: локально извлечённый контент страницы " * 4  # >150
PUBLIC_URL = "https://example.com/article"

#: (опасный URL, ожидаемый policy-код SafeFetcher) — литералы IP/схемы без DNS.
_DANGEROUS = [
    ("http://10.0.0.1/private", "destination_blocked"),
    ("http://169.254.169.254/latest/meta-data/", "metadata_endpoint_blocked"),
    ("file:///etc/passwd", "scheme_not_allowed"),
    ("https://user:pw@example.com/x", "credentials_in_url"),
]


def _set_trafilatura(monkeypatch, mode):
    """Шов модуля: 'installed' — рабочий mock, 'missing' — пакета нет."""
    if mode == "missing":
        monkeypatch.setattr("services.web_content_extractor.trafilatura", None)
        return None
    fake = MagicMock()
    fake.extract = MagicMock(return_value=TRAF_TEXT)
    monkeypatch.setattr("services.web_content_extractor.trafilatura", fake)
    return fake


def _extractor_with_recording_cloud_levels(monkeypatch, cloud_text=None):
    """Extractor с записывающими облачными уровнями (httpx не вызывается).

    `cloud_text is None` → уровень падает ValueError (провайдер недоступен)."""
    calls = []
    ext = WebContentExtractor(tavily_api_key="k", exa_api_key="k")

    def _level(name):
        async def _fn(url):
            calls.append((name, url))
            if cloud_text is None:
                raise ValueError(f"{name}: provider unavailable")
            return cloud_text
        return _fn

    monkeypatch.setattr(ext, "_extract_tavily", _level("tavily"))
    monkeypatch.setattr(ext, "_extract_exa", _level("exa"))
    return ext, calls


def _preflight_spy(record):
    """Spy на pre-flight назначения: без DNS/сети, записывает (trusted, url)."""
    async def _spy(url, *, trusted=False):
        record.append((trusted, str(url)))
        return safe_fetch.GuardedTarget(
            url=str(url), host="example.com", port=443, scheme="https")

    return _spy


class TestGuardOrderIndependentOfTrafilatura:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("trafilatura_mode", ["installed", "missing"])
    @pytest.mark.parametrize("url, code", _DANGEROUS)
    async def test_dangerous_destination_never_reaches_cloud_fallbacks(
            self, monkeypatch, url, code, trafilatura_mode):
        """Опасное назначение блокируется И без trafilatura: облачные фолбеки
        не вызываются, ошибка несёт policy-код (не `safe_error=None`).

        RED до фикса: при `missing` фолбеки получали приватный/метадата-URL."""
        ext, calls = _extractor_with_recording_cloud_levels(monkeypatch)
        _set_trafilatura(monkeypatch, trafilatura_mode)
        monkeypatch.setattr(mca_gates, "safe_fetch_enabled", lambda: True)
        try:
            with pytest.raises(WebContentExtractionFailedException) as exc:
                await ext.extract(url, 4000)
        finally:
            await ext.close()
        assert calls == []
        assert exc.value.safe_error is not None
        assert exc.value.safe_error.code == code

    @pytest.mark.asyncio
    async def test_guard_consulted_before_local_extraction_unavailable(
            self, monkeypatch):
        """Гард читается ДО отказа уровня-1: pre-flight назначения вызван
        (trusted=False), а безопасный URL по-прежнему идёт в облачный фолбек —
        каскад намеренно не изменён."""
        ext, calls = _extractor_with_recording_cloud_levels(
            monkeypatch, cloud_text=TAVILY_TEXT)
        _set_trafilatura(monkeypatch, "missing")
        monkeypatch.setattr(mca_gates, "safe_fetch_enabled", lambda: True)
        preflight = []
        monkeypatch.setattr(safe_fetch, "aguarded_target",
                            _preflight_spy(preflight))
        result = await ext.extract(PUBLIC_URL, 4000)
        assert result == TAVILY_TEXT
        assert preflight == [(False, PUBLIC_URL)]
        assert [name for name, _ in calls] == ["tavily"]

    @pytest.mark.asyncio
    async def test_gate_off_keeps_legacy_path_without_trafilatura(
            self, monkeypatch):
        """`MCA_SAFE_FETCH_ENABLED=OFF` → точный legacy-паритет: pre-flight не
        выполняется (иначе OFF молча получил бы новую проверку)."""
        ext, calls = _extractor_with_recording_cloud_levels(
            monkeypatch, cloud_text=TAVILY_TEXT)
        _set_trafilatura(monkeypatch, "missing")
        monkeypatch.setattr(mca_gates, "safe_fetch_enabled", lambda: False)
        preflight = []
        monkeypatch.setattr(safe_fetch, "aguarded_target",
                            _preflight_spy(preflight))
        result = await ext.extract("http://10.0.0.1/private", 4000)
        assert result == TAVILY_TEXT
        assert preflight == []
        assert [name for name, _ in calls] == ["tavily"]
