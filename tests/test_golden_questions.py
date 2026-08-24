"""Epic 60 (Section 66.7, T-485): «золотые вопросы» — тест-прогон.

Прогоняет tests/golden_questions.json через полный пайплайн памяти
(memorize_facts → get_rag_context) на синтетической БД с детерминированными
векторами (без API-вызовов). Ритуал после релизов памяти — см.
scripts/run_golden_questions.py."""
import pytest

from scripts.run_golden_questions import run_golden


@pytest.mark.asyncio
async def test_golden_questions_all_pass(tmp_path):
    """66.7: все вопросы из golden_questions.json находят ожидаемые ключевые
    факты в RAG-контексте (KNN-путь sqlite-vec или FTS-фолбек)."""
    passed, total = await run_golden(db_path=str(tmp_path / "golden.db"))
    assert total == 3
    assert passed == total
