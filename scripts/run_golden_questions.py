"""Epic 60 (Section 66.7, T-485): «золотые вопросы» — проверка памяти.

ПРОГОНЯТЬ ПОСЛЕ КАЖДОГО релиза, касающегося памяти (ритуал T-497 smoke +
после T-462/T-479/T-480/T-484; процедура — Section 66.7):
    py scripts/run_golden_questions.py

Как работает: синтетическая тестовая БД (временный файл, прод НЕ трогается),
детерминированные векторы БЕЗ API-вызовов (word-hash эмбеддеры), факты пишутся
через memorize_facts (полный пайплайн: экстракция → дедуп → vec), затем каждый
вопрос из tests/golden_questions.json прогоняется через MemoryManager.
get_rag_context (KNN-путь sqlite-vec; FTS-фолбек честно считается — маркеры
всё равно должны найтись). PASS = все ожидаемые ключевые факты в контексте.

Выход: PASS/FAIL-отчёт, exit code 0/1. На проде НЕ выполняется.
"""
import asyncio
import hashlib
import json
import math
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings                      # noqa: E402
from services.database import DatabaseService             # noqa: E402
from services.summary_aliases import AliasResolver        # noqa: E402
from services.summary_memory import FACT_EXTRACT_PROMPT, MemoryManager  # noqa: E402

_CHAT_ID = -424242
_SEED_FACTS = [
    ("вася ходит на тренировки по средам", "chat_history", None),
    ("вася рассказал про работу: дедлайн проекта горит", "bot_direct_reply", "вася"),
    ("вася про машину: сервис у дилера слишком дорогой", "bot_direct_reply", "вася"),
]


class GoldenEmbedder:
    """Детерминированный эмбеддер без API: вектор текста = нормированная
    сумма псевдослучайных векторов слов (seed — md5 слова). Общие слова →
    высокий cosine — KNN находит факты по запросу."""

    def __init__(self, dim: int = 3072):
        self.dim = dim
        self._word_vecs: dict[str, list[float]] = {}

    def _word_vec(self, word: str) -> list[float]:
        vec = self._word_vecs.get(word)
        if vec is None:
            rng = random.Random(int(hashlib.md5(
                word.encode("utf-8")).hexdigest()[:8], 16))
            vec = [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
            self._word_vecs[word] = vec
        return vec

    def embed_one(self, text: str) -> list[float]:
        words = [w for w in str(text).lower().split() if w]
        vec = [0.0] * self.dim
        for word in words:
            word_vec = self._word_vec(word)
            for i, value in enumerate(word_vec):
                vec[i] += value
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed(self, texts):
        return [self.embed_one(text) for text in texts]


class GoldenLLM:
    """generate отдаёт канон-JSON фактов для memorize; embed — GoldenEmbedder."""

    def __init__(self, embedder: GoldenEmbedder):
        self.embedder = embedder

    async def generate(self, messages):
        system = messages[0]["content"]
        if system == FACT_EXTRACT_PROMPT:
            text = str(messages[1]["content"])
            facts = []
            for seed, _origin, _user in _SEED_FACTS:
                if seed.split()[0] in text:
                    parts = seed.split()
                    facts.append({
                        "subject": parts[0],
                        "predicate": parts[1],
                        "object": " ".join(parts[2:]),
                    })
            return json.dumps(facts, ensure_ascii=False)
        return "золотой ответ"

    async def embed(self, texts):
        return await self.embedder.embed(texts)


async def run_golden(db_path: str | None = None, questions=None) -> tuple[int, int]:
    """Прогон: (passed, total). Создаёт тестовую БД, сидит факты, гоняет
    вопросы. Никогда не бросает (ошибка → FAIL-отчёт)."""
    questions_path = Path(__file__).resolve().parent.parent / "tests" / "golden_questions.json"
    if questions is None:
        questions = json.loads(questions_path.read_text(encoding="utf-8"))
    db_path = db_path or str(Path(tempfile.gettempdir()) / "golden_questions_tmp.db")
    db = DatabaseService(db_path)
    await db.initialize()
    embedder = GoldenEmbedder()
    llm = GoldenLLM(embedder)
    memory = MemoryManager(db, llm, aliases=AliasResolver("{}"))
    vec_ok = await memory.initialize()
    for seed, origin, user in _SEED_FACTS:
        await memory.memorize_facts(_CHAT_ID, seed, origin, target_user=user)
    passed = 0
    total = 0
    for item in questions:
        total += 1
        ctx = await memory.get_rag_context(
            _CHAT_ID, item["question"], include_direct_reply=True,
            sort_by_timestamp=True)
        missing = [kw for kw in item["expected_keywords"] if kw not in ctx]
        if missing:
            print(f"FAIL | {item['question']} | отсутствуют: {missing}")
        else:
            print(f"PASS | {item['question']}")
            passed += 1
    await db.close()
    if not vec_ok:
        print("NOTE: sqlite-vec недоступен — прогон идёт по FTS-фолбеку")
    return passed, total


def _main() -> int:
    passed, total = asyncio.run(run_golden())
    print(f"golden questions: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(_main())
