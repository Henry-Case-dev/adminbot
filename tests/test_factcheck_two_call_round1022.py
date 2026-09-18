"""F3 (T-2035…T-2043 + T-2094, ADR-1022-3) — фактчек: 2 физических вызова.

Покрытие: JSON-контракт Аналитика; изоляция Вербализатора (нет RAG/тегов);
validator-loop (брак → ретрай ≤2 → fallback 10.21); fallback при невалидном
JSON; kill-switch OFF → одиночный путь; grounding на выходе.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services.factcheck_prompts import FACTCHECK_ANALYST_SYSTEM_PROMPT
from services.factcheck_service import FactCheckService
from services.llm_client import LLMBadResponseError

pytestmark = pytest.mark.system2

_ANALYST_JSON = json.dumps({
    "claim": "земля плоская",
    "findings": [{"assertion": "земля плоская", "status": "false",
                  "human_time": "в августе", "author": "Вася",
                  "evidence": "спутники и фото"}],
    "verdict": "полный бред",
})


def _service(generate_side_effect):
    aggregator = MagicMock()
    aggregator.search = AsyncMock(return_value="хиты поиска")
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=generate_side_effect)
    return FactCheckService(aggregator, llm), llm


class TestFactcheckTwoCall:
    @pytest.mark.asyncio
    async def test_valid_two_call_pipeline(self):
        service, llm = _service([_ANALYST_JSON, "дерзкий вердикт"])
        result = await service.check_claim("земля плоская")
        assert result == "дерзкий вердикт"
        assert llm.generate.await_count == 2
        stage1 = llm.generate.await_args_list[0].args[0]
        stage2 = llm.generate.await_args_list[1].args[0]
        assert stage1[0]["content"] == FACTCHECK_ANALYST_SYSTEM_PROMPT
        assert "СИСТЕМНАЯ РОЛЬ:" in stage2[0]["content"]
        assert "{max_symbols}" not in stage2[0]["content"]
        assert stage2[1]["content"].startswith("АНАЛИЗ (JSON):")

    @pytest.mark.asyncio
    async def test_stage2_isolated_from_rag_and_context(self):
        service, llm = _service([_ANALYST_JSON, "ответ"])
        await service.check_claim("тезис", chat_context="<chat_context>СЕКРЕТ</chat_context>")
        stage2_user = llm.generate.await_args_list[1].args[0][1]["content"]
        assert "СЕКРЕТ" not in stage2_user
        assert "хиты поиска" not in stage2_user
        assert "chat_context" not in stage2_user

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_single(self):
        service, llm = _service(["не json", "одиночный вердикт"])
        result = await service.check_claim("тезис")
        assert result == "одиночный вердикт"
        assert llm.generate.await_count == 2
        # Последний вызов — одиночный путь (старый канон фактчека).
        single_system = llm.generate.await_args_list[-1].args[0][0]["content"]
        assert "третейский судья" in single_system

    @pytest.mark.asyncio
    async def test_stage1_id_leak_rejected_falls_back(self):
        bad = json.dumps({
            "claim": "c",
            "findings": [{"assertion": "a", "status": "true",
                          "human_time": "без даты", "author": None,
                          "evidence": "ссылка fact:123"}],
            "verdict": "v",
        })
        service, llm = _service([bad, "одиночный"])
        result = await service.check_claim("t")
        assert result == "одиночный"

    @pytest.mark.asyncio
    async def test_validator_exhausted_falls_back_to_single(self):
        service, llm = _service(
            [_ANALYST_JSON, "как ИИ", "подводя итог", "в заключение", "одиночный"])
        result = await service.check_claim("t")
        assert result == "одиночный"
        assert llm.generate.await_count == 5   # 1 аналитик + 3 вербализ + 1 single

    @pytest.mark.asyncio
    async def test_validator_retry_success(self):
        service, llm = _service([_ANALYST_JSON, "как ИИ", "чистый дерзкий текст"])
        result = await service.check_claim("t")
        assert result == "чистый дерзкий текст"
        assert llm.generate.await_count == 3

    @pytest.mark.asyncio
    async def test_kill_switch_off_single_call(self, monkeypatch):
        monkeypatch.setattr(Settings, "SYSTEM2_FACTCHECK_ENABLED", False)
        service, llm = _service(["одиночный вердикт"])
        result = await service.check_claim("t")
        assert result == "одиночный вердикт"
        assert llm.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_verbalizer_phantom_id_stripped(self):
        service, _llm = _service([_ANALYST_JSON, "вердикт fact:999 хвост"])
        result = await service.check_claim("t")
        assert "fact:999" not in result

    @pytest.mark.asyncio
    async def test_empty_final_raises_bad_response(self):
        service, _llm = _service([_ANALYST_JSON, "   ", "   "])
        with pytest.raises(LLMBadResponseError):
            await service.check_claim("t")
