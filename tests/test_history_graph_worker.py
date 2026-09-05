"""Фаза 2 (T-764, F4 — часть B) — тесты Graph-воркера импорта истории.

Мини-БД (v7-схема через DatabaseService.initialize) + строки smart_messages
с import_key → воркер пачками: мок-LLM (успех/битый JSON/ошибки), density-
семплизация (id % K), resume по history_processed, дубли (INSERT OR IGNORE +
частичный UNIQUE-индекс, FTS не дублируется), dry-run (ничего не пишет),
транспорты openai/ollama (think-off в теле запроса), vec-запись float+int8
(rowid=fact_id) и конкурентность embed-клиента.
"""
import asyncio
import datetime
import json
import struct

import aiosqlite
import httpx
import pytest

from config.settings import settings
from services.database import DatabaseService
from services.summary_memory import (
    build_rag_context,
    _GRAPH_VEC_TABLE_SQL_INT8,
)
from tools.history_import import prompts
from tools.history_import.llm_worker import (
    EmbedClient,
    EmbedError,
    GraphWorker,
    HistoryLLMClient,
    HistoryLLMError,
    humanize_embed_error,
    humanize_history_llm_error,
    parse_facts_json,
    run_vec_backfill,
)

CHAT = -1002661910336
BASE_TS = 1_700_000_000          # 2023-11-14 22:13:20 UTC
_EMBED_DIM = settings.EMBEDDING_DIM


# ── помощники данных ────────────────────────────────────────────────


async def _make_db(tmp_path, rows: list[dict] | None = None,
                   *, create_vec: bool = False, name: str = "g.db") -> str:
    """БД с миграциями v1..v7 (+ опционально vec0-таблица float+int8)."""
    path = str(tmp_path / name)
    svc = DatabaseService(path)
    try:
        await svc.initialize()
    finally:
        await svc.close()
    if create_vec:
        import sqlite_vec
        conn = await aiosqlite.connect(path)
        await conn.enable_load_extension(True)
        try:
            await conn.load_extension(sqlite_vec.loadable_path())
        finally:
            await conn.enable_load_extension(False)
        await conn.execute(
            _GRAPH_VEC_TABLE_SQL_INT8.format(dim=_EMBED_DIM))
        await conn.commit()
        await conn.close()
    if rows:
        conn = await aiosqlite.connect(path)
        try:
            for row in rows:
                await conn.execute(
                    "INSERT INTO smart_messages (id, user_id, chat_id, text, "
                    "timestamp, author_name, import_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (row["id"], row.get("user_id", 1), CHAT, row["text"],
                     row["ts"], row.get("author", "вася"),
                     row.get("import_key", f"k{row['id']}")))
            await conn.commit()
        finally:
            await conn.close()
    return path


def _msg(id_: int, text: str, ts: int | None = None, **kw) -> dict:
    return {"id": id_, "text": text,
            "ts": ts if ts is not None else BASE_TS + id_ * 3600, **kw}


def _text_rows(n: int) -> list[dict]:
    """n содержательных сообщений (длина текста > min_fact_chars)."""
    return [_msg(i + 1, f"сообщение номер {i + 1} про общие дела чата")
            for i in range(n)]


async def _fetch_all(db_path: str, sql: str, params=()) -> list:
    """SELECT-хелпер на свежем соединении (+sqlite-vec для vec0-таблиц —
    иначе «no such module: vec0»)."""
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        try:
            import sqlite_vec
            await conn.enable_load_extension(True)
            try:
                await conn.load_extension(sqlite_vec.loadable_path())
            finally:
                await conn.enable_load_extension(False)
        except Exception:
            pass
        cursor = await conn.execute(sql, params)
        return await cursor.fetchall()
    finally:
        await conn.close()


async def _append_messages(db_path: str, rows: list[dict]) -> None:
    conn = await aiosqlite.connect(db_path)
    try:
        for row in rows:
            await conn.execute(
                "INSERT INTO smart_messages (id, user_id, chat_id, text, "
                "timestamp, author_name, import_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["id"], row.get("user_id", 1), CHAT, row["text"],
                 row["ts"], row.get("author", "вася"),
                 row.get("import_key", f"k{row['id']}")))
        await conn.commit()
    finally:
        await conn.close()


class FakeLLM:
    """Мок локальной LLM (контракт HistoryLLMClient.extract): сценарии."""

    def __init__(self, triples=None, error: Exception | None = None,
                 json_text=None):
        self.triples = triples or []
        self.error = error
        self.json_text = json_text
        self.calls: list[str] = []
        self.seen_max_facts = None

    async def extract(self, user_content: str, max_facts: int = 8):
        self.calls.append(user_content)
        self.seen_max_facts = max_facts
        if self.error is not None:
            raise self.error
        if self.json_text is not None:
            if isinstance(self.json_text, (dict, list)):
                content = json.dumps(self.json_text, ensure_ascii=False)
            else:
                content = self.json_text
            return parse_facts_json(content)
        return list(self.triples)

    def reset(self) -> None:
        self.calls.clear()
        self.seen_max_facts = None


class FakeEmbed:
    """Мок API-эмбеддинга: dim 3072, порядок сохранён, опциональный фейл."""

    def __init__(self, fail_on_call: int | None = None):
        self.calls: list[list[str]] = []
        self.fail_on_call = fail_on_call

    async def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        if self.fail_on_call is not None and len(self.calls) >= self.fail_on_call:
            raise EmbedError("mock: embed down")
        return [[0.1 + (idx % 5) * 0.01] * _EMBED_DIM
                for idx in range(len(texts))]

    async def aclose(self) -> None:  # pragma: no cover
        pass


async def _make_worker(db: str, llm: FakeLLM | None = None,
                       embed: FakeEmbed | None = None, **kw) -> GraphWorker:
    worker = GraphWorker(db, llm=llm or FakeLLM(), embed_client=embed,
                         chat_id=CHAT, **kw)
    return worker


# ── базовые юниты: промпт/парсинг ───────────────────────────────────

class TestPromptAndParsing:
    def test_system_prompt_is_canon(self):
        """Канон: архивариус, правила дат (не выдумывать/не возвращать),
        лимит фактов, структура {facts:[{subject,predicate,object,context}]}."""
        p = prompts.HISTORY_EXTRACT_PROMPT
        assert "архивариус" in p
        assert "ДАТЫ НЕ ВЫДУМЫВАЙ" in p
        assert "subject" in p and "predicate" in p and "object" in p
        assert "{max_facts}" in p            # плейсхолдер лимита пачки
        # форматируется без поломки скобок JSON-примеров
        filled = p.format(max_facts=8)
        assert "{max_facts}" not in filled
        assert '{"facts":' in filled or '"facts":' in filled
        s = prompts.HISTORY_EXTRACT_SCHEMA
        assert s["type"] == "object" and s["required"] == ["facts"]
        assert s["properties"]["facts"]["items"]["required"] == \
            ["subject", "predicate", "object"]

    def test_user_prompt_format_utc(self):
        """Пачка форматируется `[%Y-%m-%d %H:%M] Имя: текст` (UTC)."""
        rows = [
            {"timestamp": 1_700_000_000, "author_name": "Первый",
             "text": "привет, как дела"},
            {"timestamp": 1_700_000_400, "author_name": "Второй",
             "text": "вот фото"},
        ]
        text = prompts.build_history_user_prompt(rows)
        assert text == ("[2023-11-14 22:13] Первый: привет, как дела\n"
                        "[2023-11-14 22:20] Второй: вот фото")

    def test_parse_facts_robust(self):
        """Фенс-код/конверт/голый массив/мусор вокруг — принимаются;
        ОДНО-строчные формы (не-JSON/пусто) → [] (НЕ ошибка); мусорные
        элементы отбрасываются (subject==object, не-строки, длинный
        context, пустые predicate/object — qwen-сюрприз «object": ""»)."""
        good = ('```json\n{"facts": [{"subject": "вася", '
                '"predicate": "купил в марте 2025", "object": "дрон", '
                '"context": "из-за скидки"}]}\n```')
        facts = parse_facts_json(good)
        assert len(facts) == 1 and facts[0]["subject"] == "вася"
        assert facts[0]["context"] == "из-за скидки"
        noisy = ('Вот факты: [{"subject":"a", "predicate":"любит", '
                 '"object":"b"}] надеюсь помогло')
        assert len(parse_facts_json(noisy)) == 1
        assert parse_facts_json('{"facts": []}') == []
        assert parse_facts_json("[]") == []
        # Задача 1: не-JSON/пусто → [] («нет фактов» — НЕ ошибка)
        assert parse_facts_json("извините, я не смог") == []
        assert parse_facts_json("") == []
        assert parse_facts_json(None) == []
        mixed = ('[{"subject": "x", "predicate": "=", "object": "x"}, '
                 '{"subject": 1, "predicate": "p", "object": "o"}, '
                 '{"subject": "с", "predicate": "делает", "object": "о", '
                 '"context": "длинный ' + "к" * 500 + '"}]')
        facts = parse_facts_json(mixed)
        assert len(facts) == 1 and facts[0]["subject"] == "с"
        assert len(facts[0]["context"]) <= prompts.HISTORY_MAX_CONTEXT_CHARS

    def test_parse_facts_wrappers_and_fact_strings(self):
        """Задача 1: все разумные формы — {"facts"|"fact"|"data"|"result"}:
        обёртки, одиночный объект вместо массива, {"fact": "строка"}."""
        array = parse_facts_json('[{"subject": "a", "predicate": "любит", '
                                 '"object": "b"}]')
        assert array[0]["predicate"] == "любит"
        for wrapper, key in (("facts", "играет в"), ("data", "смотрит"),
                             ("result", "рисует")):
            raw = '{"%s": [{"subject": "петя", "predicate": "%s", ' \
                  '"object": "x"}]}' % (wrapper, key)
            facts = parse_facts_json(raw)
            assert len(facts) == 1 and facts[0]["predicate"] == key, wrapper
        assert parse_facts_json('{"fact": [{"subject": "a", "predicate": "p", '
                                '"object": "o"}]}')[0]["subject"] == "a"
        # одиночный объект вместо массива ({...} вместо [{...}])
        single = parse_facts_json('{"facts": {"subject": "a", "predicate": '
                                  '"уехал в", "object": "деревню"}}')
        assert len(single) == 1 and single[0]["object"] == "деревню"
        # {"fact": "строка"} — факт целиком; вернуть список строк
        fact_items = parse_facts_json('{"fact": [{"fact": "вася купил дрон"}, '
                                      '{"fact": "  петя  уехал  "}, '
                                      '{"fact": "   "}]}')
        assert fact_items == ["вася купил дрон", "петя уехал"]
        assert parse_facts_json('{"fact": "алина любит рынок"}') == \
            ["алина любит рынок"]

    def test_parse_facts_empty_triplets_filtered(self):
        """Задача 1(ж): null/пустые поля триплетов (qwen «object": ""») —
        фильтруются, массив не падает; валидные рядом сохраняются."""
        raw = ('{"facts": [{"subject": "Alina", "predicate": '
               '"считает спекуляцию рынком", "object": "", "context": ""}, '
               '{"subject": "вася", "predicate": null, "object": "x"}, '
               '{"subject": "петя", "predicate": "переехал в", '
               '"object": "город"}]}')
        facts = parse_facts_json(raw)
        assert len(facts) == 1
        assert facts[0]["subject"] == "петя"
        assert parse_facts_json(
            '{"facts": [{"subject": "Alina", "predicate": "считает", '
            '"object": ""}]}') == []


# ── транспорты LLM: формирование запроса ────────────────────────────

class _FakeHttp:
    """Замена httpx.AsyncClient.post: запись запросов, сценарий ответа."""

    def __init__(self, payloads: list[dict], status: int = 200):
        self.payloads = payloads
        self.status = status
        self.sent: list[dict] = []
        self.urls: list[str] = []
        self.headers_seen: list[dict] = []
        self._idx = 0

    async def post(self, url: str, json: dict, headers=None):
        self.sent.append(json)
        self.urls.append(url)
        self.headers_seen.append(headers)
        body = self.payloads[min(self._idx, len(self.payloads) - 1)]
        self._idx += 1
        return httpx.Response(self.status, json=body,
                              request=httpx.Request("POST", url))


def _openai_resp(content: str, *, usage: bool = False) -> dict:
    resp = {"choices": [{"message": {"content": content}}]}
    if usage:
        resp["usage"] = {"total_tokens": 1234}
    return resp


def _swap_http(client, fake) -> None:
    """Подмена AsyncClient клиента тестовой заглушкой.

    Оригинальный (ни разу не использованный) httpx.AsyncClient закрывается
    отложенно в текущем цикле — ресурсы не текут в asyncio-тестах."""
    original = client._client
    client._client = fake
    if original is not None and original is not fake:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(original.aclose())


class TestLLMTransports:
    def _client(self, **kw) -> HistoryLLMClient:
        return HistoryLLMClient(model="qwen3.5:9b",
                                endpoint="http://localhost:11434/v1", **kw)

    @pytest.mark.asyncio
    async def test_openai_body_and_think_off(self):
        """openai transport: /chat/completions, temperature 0,
        response_format json_object + оба поля думания (auto)."""
        llm = self._client(transport="openai", think_off_mode="auto")
        fake = _FakeHttp([_openai_resp(
            '{"facts": [{"subject": "а", "predicate": "любит", '
            '"object": "б"}]}')])
        _swap_http(llm, fake)
        try:
            facts = await llm.extract("пачка")
        finally:
            await llm.aclose()
        body = fake.sent[0]
        assert llm.url.endswith("/chat/completions")
        assert body["model"] == "qwen3.5:9b"
        assert body["temperature"] == 0
        assert body["response_format"] == {"type": "json_object"}
        assert body["think"] is False
        assert body["reasoning_effort"] == "none"
        assert body["messages"][0]["role"] == "system"
        assert "архивариус" in body["messages"][0]["content"]
        assert len(facts) == 1

    @pytest.mark.asyncio
    async def test_think_off_modes(self):
        """reasoning_effort → только OpenAI-поле; ollama_chat → только think."""
        for mode, has_think, has_reasoning in (
                ("reasoning_effort", False, True),
                ("ollama_chat", True, False)):
            llm = self._client(transport="openai", think_off_mode=mode)
            fake = _FakeHttp([_openai_resp('{"facts": []}')])
            _swap_http(llm, fake)
            try:
                await llm.extract("пачка")
            finally:
                await llm.aclose()
            body = fake.sent[0]
            assert ("think" in body) is has_think, mode
            assert ("reasoning_effort" in body) is has_reasoning, mode

    @pytest.mark.asyncio
    async def test_ollama_body(self):
        """ollama transport: /api/chat (host без /v1), think=False,
        format=JSON Schema, options temperature/num_ctx/num_predict."""
        llm = self._client(transport="ollama")
        fake = _FakeHttp([{"message": {"content": '{"facts": []}'}}])
        _swap_http(llm, fake)
        try:
            await llm.extract("пачка")
        finally:
            await llm.aclose()
        body = fake.sent[0]
        assert llm.url == "http://localhost:11434/api/chat"
        assert body["think"] is False
        assert body["stream"] is False
        assert body["format"] == prompts.HISTORY_EXTRACT_SCHEMA
        assert body["options"] == {"temperature": 0, "num_ctx": 8192,
                                   "num_predict": 1500}

    @pytest.mark.asyncio
    async def test_auto_resolve_transport(self):
        c1 = HistoryLLMClient("m", "http://x:11434/v1")
        c2 = HistoryLLMClient("m", "http://x:11434")
        c3 = HistoryLLMClient("m", "http://x:11434", transport="openai")
        try:
            assert c1.transport == "openai"
            assert c2.transport == "ollama"
            assert c3.transport == "openai"
        finally:
            await c1.aclose()
            await c2.aclose()
            await c3.aclose()

    @pytest.mark.asyncio
    async def test_garbage_json_means_no_facts(self):
        """Задача 1: не-JSON content — «нет фактов» ([]), БЕЗ ретрая и БЕЗ
        ошибки (парсер больше не падает на мусоре; пачка пойдёт дальше)."""
        llm = self._client(transport="openai")
        fake = _FakeHttp([_openai_resp("не JSON вовсе")])
        _swap_http(llm, fake)
        try:
            facts = await llm.extract("пачка")
        finally:
            await llm.aclose()
        assert facts == []
        assert len(fake.sent) == 1           # попытка не расходуется на ретрай
        assert fake.sent[0] == fake.sent[0]

    @pytest.mark.asyncio
    async def test_empty_content_hint_and_retry(self):
        """Пустой content (думание не выключено, usage>0) → ретрай → ошибка."""
        llm = self._client(transport="openai")
        fake = _FakeHttp([_openai_resp("", usage=True)] * 3)
        _swap_http(llm, fake)
        try:
            with pytest.raises(HistoryLLMError):
                await llm.extract("пачка")
        finally:
            await llm.aclose()
        assert len(fake.sent) == 2

    @pytest.mark.asyncio
    async def test_transport_retries_on_http_error(self):
        """503 → backoff-ретраи; после исчерпания — HistoryLLMError."""
        llm = self._client(transport="openai")
        llm.retries = 2
        fake = _FakeHttp([{"error": "down"}], status=503)
        _swap_http(llm, fake)
        try:
            with pytest.raises(HistoryLLMError):
                await llm.extract("пачка")
        finally:
            await llm.aclose()
        assert len(fake.sent) == 3           # 1 + 2 транспортных ретрая


# ── embed-клиент ────────────────────────────────────────────────────

class _FakeEmbedHttp(_FakeHttp):
    """HTTP-заглушка /embeddings: data[].embedding по числу входов."""

    async def post(self, url: str, json: dict, headers=None):
        self.sent.append(json)
        self.urls.append(url)
        self.headers_seen.append(headers)
        texts = json.get("input") or []
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"},
                                  request=httpx.Request("POST", url))
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.5] * _EMBED_DIM}
                           for _ in texts]},
            request=httpx.Request("POST", url))


class TestEmbedClient:
    @pytest.mark.asyncio
    async def test_batch_order_model_and_auth(self):
        """5 текстов: батчинг по 1, порядок результатов сохранён, URL/модель/
        Authorization корректны; авторизация не шлётся без ключа."""
        client = EmbedClient(base_url="https://embed.test/v1",
                             api_key="sk-test-key", model="gemini-x",
                             batch_size=1, timeout=5)
        fake = _FakeEmbedHttp([{}])
        _swap_http(client, fake)
        try:
            vectors = await client.embed([f"текст {i}" for i in range(5)])
        finally:
            await client.aclose()
        assert len(vectors) == 5
        assert all(len(v) == _EMBED_DIM for v in vectors)
        assert fake.urls == ["https://embed.test/v1/embeddings"] * 5
        assert fake.sent[0]["model"] == "gemini-x"
        assert fake.sent[4]["input"] == ["текст 4"]
        assert fake.headers_seen[0] == {"Authorization": "Bearer sk-test-key"}
        # без ключа — заголовок не шлётся
        anon = EmbedClient(base_url="https://embed.test/v1", model="m",
                           api_key="", batch_size=1, timeout=5)
        fake2 = _FakeEmbedHttp([{}])
        _swap_http(anon, fake2)
        try:
            await anon.embed(["текст"])
        finally:
            await anon.aclose()
        assert fake2.headers_seen[0] in (None, {})

    @pytest.mark.asyncio
    async def test_concurrency_limited_and_retries(self):
        """Конкурентность не превышает лимит; 5xx ретраится; фатальный 4xx —
        сразу EmbedError (без ретраев)."""
        import time as _time

        class _SlowHttp(_FakeEmbedHttp):
            def __init__(self):
                super().__init__([{}])
                self.active = 0
                self.peak = 0

            async def post(self, url: str, json: dict, headers=None):
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    await asyncio.sleep(0.03)
                    return await super().post(url, json, headers)
                finally:
                    self.active -= 1

        client = EmbedClient(base_url="https://embed.test/v1", model="m",
                             concurrency=2, batch_size=1, timeout=5)
        slow = _SlowHttp()
        _swap_http(client, slow)
        started = _time.monotonic()
        try:
            vectors = await client.embed([f"t{i}" for i in range(6)])
        finally:
            await client.aclose()
        assert len(vectors) == 6
        assert slow.peak <= 2
        assert _time.monotonic() - started >= 0.03 * 3   # 3 волны по 2

        client = EmbedClient(base_url="https://embed.test/v1", model="m",
                             concurrency=1, batch_size=1, timeout=5,
                             max_retries=1)
        fake = _FakeEmbedHttp([{}], status=500)
        _swap_http(client, fake)
        try:
            with pytest.raises(EmbedError):
                await client.embed(["текст"])
        finally:
            await client.aclose()
        assert len(fake.sent) == 2            # 1 + 1 ретрай

        client = EmbedClient(base_url="https://embed.test/v1", model="m",
                             concurrency=1, batch_size=1, timeout=5)
        fake = _FakeEmbedHttp([{}], status=400)
        _swap_http(client, fake)
        try:
            with pytest.raises(EmbedError):
                await client.embed(["текст"])
        finally:
            await client.aclose()
        assert len(fake.sent) == 1            # фатальный 4xx — без ретраев


class _FakeEmbedFailover:
    """Роутинг primary ↔ фоллбэк по URL (fallback.test): один fake на оба
    клиента EmbedClient (_client и ленивый _fb_client)."""

    def __init__(self, fb_status: int = 200, fb_body=None,
                 fb_exc: Exception | None = None,
                 primary_status: int = 403):
        self.fb_status = fb_status
        self.fb_body = fb_body
        self.fb_exc = fb_exc
        self.primary_status = primary_status
        self.urls: list[str] = []
        self.sent: list[dict] = []
        self.headers_seen: list[dict] = []

    async def post(self, url: str, json: dict, headers=None):
        self.urls.append(url)
        self.sent.append(json)
        self.headers_seen.append(headers)
        request = httpx.Request("POST", url)
        if "fallback.test" in url:
            if self.fb_exc is not None:
                raise self.fb_exc
            if self.fb_status != 200:
                return httpx.Response(self.fb_status,
                                      json={"error": "x"}, request=request)
            if self.fb_body is not None:
                return httpx.Response(200, json=self.fb_body, request=request)
            texts = json.get("input") or []
            return httpx.Response(
                200,
                json={"data": [{"embedding": [0.5] * _EMBED_DIM}
                               for _ in texts]},
                request=request)
        if self.primary_status != 200:
            return httpx.Response(self.primary_status,
                                  json={"error": "quota"}, request=request)
        texts = json.get("input") or []
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.25] * _EMBED_DIM}
                           for _ in texts]},
            request=request)


class TestEmbedClientFallback:
    """Раунд 5: embed-фоллбэк EMBEDDING_FALLBACK_* в EmbedClient воркера:
    одна попытка POST {fb}/embeddings после EmbedError primary."""

    def _client(self, fake, *, embed_fallback_model=None,
                embed_fallback_api_key_2=None, **kw) -> EmbedClient:
        client = EmbedClient(
            base_url="https://embed.test/v1", api_key="sk-primary",
            model="gemini-x", timeout=5,
            embed_fallback_base_url="https://fallback.test/v1",
            embed_fallback_api_key="sk-fb",
            embed_fallback_model=embed_fallback_model,
            embed_fallback_api_key_2=(
                embed_fallback_api_key_2
                if embed_fallback_api_key_2 is not None else ""),
            **kw)
        _swap_http(client, fake)
        client._fb_client = fake          # ленивый фоллбэк-клиент — тоже fake
        return client

    @pytest.mark.asyncio
    async def test_fallback_after_fatal_primary_403(self, caplog):
        """Primary 403 (фатальный 4xx) → одна попытка на фоллбэке → векторы;
        модель пустая → primary embed-модель; INFO-лог с primary_error."""
        import logging
        fake = _FakeEmbedFailover()
        client = self._client(fake)
        try:
            with caplog.at_level(logging.INFO):
                vectors = await client.embed(["текст"])
        finally:
            await client.aclose()
        assert vectors == [[0.5] * _EMBED_DIM]
        assert fake.urls == ["https://embed.test/v1/embeddings",
                             "https://fallback.test/v1/embeddings"]
        assert fake.sent[0]["model"] == "gemini-x"
        assert fake.sent[1] == {"model": "gemini-x", "input": ["текст"]}
        assert fake.headers_seen[1] == {"Authorization": "Bearer sk-fb"}
        assert any(
            "history graph: embed fallback OK | model=gemini-x | "
            "primary_error=EmbedError: embed HTTP 403" in r.message
            for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_explicit_model_kwarg(self):
        """Заданная embed_fallback_model → в payload фоллбэка."""
        fake = _FakeEmbedFailover()
        client = self._client(fake, embed_fallback_model="gemini-fb")
        try:
            assert client._fb_model == "gemini-fb"
            await client.embed(["текст"])
        finally:
            await client.aclose()
        assert fake.sent[1]["model"] == "gemini-fb"

    @pytest.mark.asyncio
    async def test_fallback_inactive_no_key_raises_primary(self, caplog):
        """Ключ пуст (явно "") → _fb_active False → проброс исходного
        EmbedError primary, фоллбэк-URL не вызывается."""
        import logging
        fake = _FakeEmbedFailover()
        client = EmbedClient(
            base_url="https://embed.test/v1", api_key="sk-primary",
            model="gemini-x", timeout=5,
            embed_fallback_base_url="https://fallback.test/v1",
            embed_fallback_api_key="", embed_fallback_api_key_2="")
        _swap_http(client, fake)
        try:
            assert client._fb_active is False
            with caplog.at_level(logging.WARNING):
                with pytest.raises(EmbedError) as ei:
                    await client.embed(["текст"])
        finally:
            await client.aclose()
        assert "embed HTTP 403" in str(ei.value)
        assert fake.urls == ["https://embed.test/v1/embeddings"]
        assert not any("embed fallback" in r.message
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_http_error_warns_and_raises_combined(self, caplog):
        """Фоллбэк 500 → WARNING «embed fallback failed | primary=… |
        fallback=status=500» + EmbedError «embed primary+fallback failed»."""
        import logging
        fake = _FakeEmbedFailover(fb_status=500)
        client = self._client(fake)
        try:
            with caplog.at_level(logging.WARNING):
                with pytest.raises(EmbedError) as ei:
                    await client.embed(["текст"])
        finally:
            await client.aclose()
        msg = str(ei.value)
        assert "embed primary+fallback failed | primary: EmbedError: " \
               "embed HTTP 403" in msg
        assert "| fallback: status=500" in msg
        assert any("history graph: embed fallback failed | "
                   "primary=EmbedError: embed HTTP 403" in r.message
                   and "| fallback=status=500" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_transport_error_warns_and_raises_combined(
            self, caplog):
        """Транспортный фейл фоллбэка → WARNING (fallback=ConnectError: …)
        + EmbedError «embed primary+fallback failed»."""
        import logging
        fake = _FakeEmbedFailover(
            fb_exc=httpx.ConnectError("fb недоступен",
                                      request=httpx.Request("POST", "https://x")))
        client = self._client(fake)
        try:
            with caplog.at_level(logging.WARNING):
                with pytest.raises(EmbedError) as ei:
                    await client.embed(["текст"])
        finally:
            await client.aclose()
        msg = str(ei.value)
        assert "embed primary+fallback failed | primary: EmbedError: " \
               "embed HTTP 403" in msg
        assert "| fallback: ConnectError: fb недоступен" in msg
        assert any("history graph: embed fallback failed | "
                   "primary=EmbedError: embed HTTP 403" in r.message
                   and "fallback=ConnectError: fb недоступен" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_bad_body_len_mismatch_raises(self):
        """Фоллбэк 200, но data[] с числом векторов ≠ числу текстов → EmbedError
        (len-проверка ответа фоллбэка)."""
        fake = _FakeEmbedFailover(fb_body={"data": []})
        client = self._client(fake)
        try:
            with pytest.raises(EmbedError) as ei:
                await client.embed(["текст"])
        finally:
            await client.aclose()
        assert "embed fallback вернул 0 векторов на 1 текстов" in str(ei.value)


class _FakeEmbedKeyCascade:
    """Каскад двух ключей EmbedClient: primary всегда 403 (embed.test),
    статус фоллбэка выбирается по Bearer ключа (fallback.test)."""

    def __init__(self, key_statuses: dict[str, int]):
        self.key_statuses = key_statuses
        self.urls: list[str] = []
        self.sent: list[dict] = []
        self.headers_seen: list[dict] = []
        self.calls_by_key: dict[str, int] = {}

    async def post(self, url: str, json: dict, headers=None):
        self.urls.append(url)
        self.sent.append(json)
        self.headers_seen.append(headers)
        request = httpx.Request("POST", url)
        if "fallback.test" in url:
            auth = (headers or {}).get("Authorization", "")
            key = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            self.calls_by_key[key] = self.calls_by_key.get(key, 0) + 1
            status = self.key_statuses.get(key, 200)
            if status != 200:
                return httpx.Response(status, json={"error": "x"},
                                      request=request)
            texts = json.get("input") or []
            return httpx.Response(
                200,
                json={"data": [{"embedding": [0.5] * _EMBED_DIM}
                               for _ in texts]},
                request=request)
        return httpx.Response(403, json={"error": "quota"}, request=request)


class TestEmbedClientKeyCascade:
    """Задача 1 (2026-09-05): каскад второго ключа в EmbedClient воркера —
    одна попытка на ключ (POST с Bearer ключа в headers запроса), успех →
    векторы; все фейлы → EmbedError с причинами по ключам."""

    def _client(self, fake, **kw) -> EmbedClient:
        return TestEmbedClientFallback()._client(
            fake, embed_fallback_api_key_2="sk-fb-2", **kw)

    @pytest.mark.asyncio
    async def test_key1_403_then_key2_200(self, caplog):
        """key1 403 → key2 200 → векторы; по одному запросу на ключ;
        INFO-лог успеха с key_idx=1; Bearer ключа — заголовком запроса."""
        import logging
        fake = _FakeEmbedKeyCascade({"sk-fb": 403, "sk-fb-2": 200})
        client = self._client(fake)
        try:
            assert client._fb_api_keys == ["sk-fb", "sk-fb-2"]
            with caplog.at_level(logging.INFO):
                vectors = await client.embed(["текст"])
        finally:
            await client.aclose()
        assert vectors == [[0.5] * _EMBED_DIM]
        assert fake.calls_by_key == {"sk-fb": 1, "sk-fb-2": 1}
        assert fake.urls[0] == "https://embed.test/v1/embeddings"
        assert fake.urls[1:] == ["https://fallback.test/v1/embeddings",
                                 "https://fallback.test/v1/embeddings"]
        assert fake.headers_seen[1] == {"Authorization": "Bearer sk-fb"}
        assert fake.headers_seen[2] == {"Authorization": "Bearer sk-fb-2"}
        assert any(
            "history graph: embed fallback OK | model=gemini-x | "
            "primary_error=EmbedError: embed HTTP 403" in r.message
            and "| key_idx=1" in r.message
            for r in caplog.records)

    @pytest.mark.asyncio
    async def test_key1_200_key2_not_called(self, caplog):
        """key1 200 → key2 НЕ вызывается; OK-лог с key_idx=0."""
        import logging
        fake = _FakeEmbedKeyCascade({"sk-fb": 200, "sk-fb-2": 200})
        client = self._client(fake)
        try:
            with caplog.at_level(logging.INFO):
                vectors = await client.embed(["текст"])
        finally:
            await client.aclose()
        assert vectors == [[0.5] * _EMBED_DIM]
        assert fake.calls_by_key == {"sk-fb": 1}
        assert any("key_idx=0" in r.message for r in caplog.records)
        assert not any("key_idx=1" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_all_keys_fail_raises_with_reasons_per_key(self, caplog):
        """Оба ключа 403 → ровно 1 запрос на ключ; EmbedError с причинами по
        ключам (key0=…; key1=…), reason-атрибут (человеческий текст);
        WARNING с человеческим объяснением + подсказкой Ctrl+C."""
        import logging
        fake = _FakeEmbedKeyCascade({"sk-fb": 403, "sk-fb-2": 403})
        client = self._client(fake)
        try:
            with caplog.at_level(logging.WARNING):
                with pytest.raises(EmbedError) as ei:
                    await client.embed(["текст"])
        finally:
            await client.aclose()
        assert fake.calls_by_key == {"sk-fb": 1, "sk-fb-2": 1}
        msg = str(ei.value)
        assert "embed primary+fallback failed | primary: EmbedError: " \
               "embed HTTP 403" in msg
        assert "| fallback: key0=status=403; key1=status=403" in msg
        assert ei.value.reason is not None and "403" in ei.value.reason
        assert any("history graph: embed fallback exhausted" in r.message
                   and "403" in r.message and "Ctrl+C" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_cascade_inactive_without_any_key(self):
        """Без ключей (оба пусты) → _fb_active False → проброс исходного
        EmbedError primary, запросов на фоллбэк нет."""
        fake = _FakeEmbedKeyCascade({})
        client = EmbedClient(
            base_url="https://embed.test/v1", api_key="sk-primary",
            model="gemini-x", timeout=5,
            embed_fallback_base_url="https://fallback.test/v1",
            embed_fallback_api_key="", embed_fallback_api_key_2="")
        _swap_http(client, fake)
        try:
            assert client._fb_api_keys == []
            assert client._fb_active is False
            with pytest.raises(EmbedError) as ei:
                await client.embed(["текст"])
        finally:
            await client.aclose()
        assert "embed HTTP 403" in str(ei.value)
        assert fake.urls == ["https://embed.test/v1/embeddings"]


class TestWorkerHumanizeErrors:
    """Задача 2 (2026-09-05): humanize_embed_error (llm_worker) — маппинг
    кодов; EmbedError несёт reason; пачка с LLM-ошибкой получает текст с
    причиной и судьбой пачки."""

    def test_humanize_401(self):
        text = humanize_embed_error(
            EmbedError("embed HTTP 401: bad key"))
        assert "(401)" in text and "проверьте" in text

    def test_humanize_403(self):
        text = humanize_embed_error(
            EmbedError("embed HTTP 403: quota exceeded"))
        assert "(403)" in text and "квота" in text

    def test_humanize_429(self):
        text = humanize_embed_error(
            EmbedError("embed HTTP 429 (попытка 1)"))
        assert "(429)" in text and "Рейт-лимит" in text

    def test_humanize_5xx(self):
        text = humanize_embed_error(
            EmbedError("embed HTTP 503 (попытка 2)"))
        assert "5xx" in text

    def test_humanize_transport_network(self):
        text = humanize_embed_error(
            EmbedError("embed транспорт недоступен (попытка 2): "
                       "ConnectError: нет соединения"))
        assert "Сеть недоступна" in text

    def test_humanize_timeout(self):
        text = humanize_embed_error(
            httpx.ReadTimeout("чтение зависло",
                              request=httpx.Request("POST", "https://x")))
        assert "Таймаут" in text

    def test_humanize_bad_json(self):
        text = humanize_embed_error(
            EmbedError("embed ответ без data[].embedding: 'data'"))
        assert "распознан" in text

    def test_humanize_unknown_default(self):
        text = humanize_embed_error(EmbedError("странная ошибка"))
        assert "Облачный API недоступен" in text

    def test_humanize_history_llm_http(self):
        """Задача 3: HistoryLLMError (локальная LLM) — РАЗДЕЛЬНЫЙ текст:
        про Ollama, НЕ про эмбеддинги."""
        text = humanize_history_llm_error(
            HistoryLLMError("LLM HTTP 503 (попытка 1)"))
        assert "Ollama" in text and "503" in text
        assert "data[].embedding" not in text

    def test_humanize_history_llm_transport(self):
        text = humanize_history_llm_error(
            HistoryLLMError("LLM транспорт недоступен (попытка 2): "
                            "ConnectError: нет соединения"))
        assert "Ollama недоступна" in text

    def test_humanize_history_llm_parse_error(self):
        """Задача 3(а): парсинг фактов — каноническая фраза «не удалось
        разобрать как список фактов» БЕЗ упоминания embedding."""
        text = humanize_history_llm_error(
            HistoryLLMError("LLM ответ — не JSON-массив фактов: «пробел»"))
        assert "не удалось разобрать как список фактов" in text
        assert "пачка пропущена" in text
        assert "embedding" not in text.lower()

    def test_humanize_history_and_embed_are_separate(self):
        """Задача 3(в): HistoryLLMError и EmbedError humanize-ятся раздельно
        (парсинг фактов ≠ эмбеддинги), их тексты НЕ пересекаются."""
        hist = humanize_history_llm_error(
            HistoryLLMError("LLM ответ — не JSON-массив фактов"))
        embed = humanize_embed_error(
            EmbedError("embed ответ без data[].embedding: 'data'"))
        assert "не удалось разобрать" in hist
        assert "data[].embedding" in embed
        assert "embedding" not in hist.lower()
        assert "не удалось разобрать" not in embed

    def test_embed_error_carries_reason_attribute(self):
        err = EmbedError("embed primary+fallback failed",
                         reason="Рейт-лимит (429) — воркер ждёт и повторит")
        assert err.reason is not None
        assert "429" in err.reason

    @pytest.mark.asyncio
    async def test_five_consecutive_errors_stop(self, tmp_path):
        """Задача 2(б): 5 ошибок пачек ПОДРЯД (без --skip-errors) → стоп с
        человеческим сообщением («стабильно отвечает ошибкой», прогресс
        сохранён, упавшие пачки НЕ помечены)."""
        db = await _make_db(tmp_path, _text_rows(30))
        llm = FakeLLM(error=HistoryLLMError(
            "LLM ответ — не JSON-массив фактов: «пробел»"))
        worker = await _make_worker(db, llm=llm, fact_density=1.0,
                                    batch_size=4)
        with pytest.raises(HistoryLLMError) as ei:
            await worker.run()
        msg = str(ei.value)
        assert "стабильно отвечает ошибкой" in msg
        assert "прогресс сохранён" in msg
        assert "НЕ помечены" in msg
        assert len(llm.calls) == 5
        # пачки (и оценённые строки) не помечены — повторятся след. запуском
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM smart_messages "
                "WHERE chat_id = ? AND history_processed = 0",
            (CHAT,)))[0]["c"] > 0
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"] == 0

    @pytest.mark.asyncio
    async def test_errors_then_success_continues(self, tmp_path, caplog):
        """Задача 2(б): 2 ошибки подряд → пачки пропускаются (WARNING «пачка
        N пропущена»), НЕ помечаются, процесс идёт дальше; после успеха
        счётчик сбрасывается — факты записываются, прогон завершается."""
        import logging
        caplog.set_level(logging.WARNING, logger="tools.history_import")
        db = await _make_db(tmp_path, _text_rows(40))

        class FlakyLLM(FakeLLM):
            def __init__(self):
                super().__init__()
                self.n = 0

            async def extract(self, user_content, max_facts=8):
                self.n += 1
                if self.n <= 2:
                    raise HistoryLLMError("LLM ответ — не JSON-массив фактов")
                return [{"subject": "вася", "predicate": "чинит",
                         "object": "сервер"}]

        llm = FlakyLLM()
        worker = await _make_worker(db, llm=llm, fact_density=0.5,
                                    batch_size=4)
        stats = await worker.run()
        assert stats["batches"] == 5
        assert stats["llm_errors"] == 2
        assert stats["facts_inserted"] == 3
        assert "пачка 1 пропущена" in caplog.text
        assert "пачка 2 пропущена" in caplog.text
        # пачки с ошибками (первая: id 2,4,6,8; вторая: id 10,12,14,16) НЕ
        # помечены; успешные (3-5) — помечены
        remain = await _fetch_all(
            db, "SELECT id FROM smart_messages WHERE history_processed = 0")
        assert {2, 4, 6, 8, 10, 12, 14, 16} <= {r["id"] for r in remain}
        done = await _fetch_all(
            db, "SELECT id FROM smart_messages WHERE history_processed = 1")
        assert {18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40} \
            <= {r["id"] for r in done}


# ── воркер: пачки/факты/resume ──────────────────────────────────────

class TestGraphWorker:
    @pytest.mark.asyncio
    async def test_worker_inserts_facts_from_batch(self, tmp_path):
        """Пачка → факты: origin history_import, weight 0.3, expires NULL,
        message_timestamp=MAX(ts), FTS-строка есть, processed=1 диапазону."""
        db = await _make_db(tmp_path, _text_rows(14))
        llm = FakeLLM(triples=[
            {"subject": "вася", "predicate": "купил в марте 2025",
             "object": "дрон"},
            {"subject": "петя", "predicate": "переехал в",
             "object": "новый город", "context": "из-за работы"},
        ])
        worker = await _make_worker(db, llm=llm, fact_density=0.5,
                                    batch_size=25)
        stats = await worker.run()
        assert stats["done"] is True
        assert stats["batches"] == 1
        assert stats["selected_msgs"] == 7     # id 2,4,…,14 (K=2)
        assert stats["facts_inserted"] == 2
        assert len(llm.calls) == 1
        assert llm.seen_max_facts == max(1, round(25 * 0.5))
        # user-промпт пачки: строки [%Y-%m-%d %H:%M] автор
        assert "[2023-11-" in llm.calls[0]
        assert "вася:" in llm.calls[0]
        # атрибуты фактов
        facts = await _fetch_all(
            db, "SELECT id, chat_id, fact, origin, expires_at, weight, "
                "status, target_user, message_timestamp "
                "FROM graph_facts ORDER BY id")
        assert len(facts) == 2
        for f in facts:
            assert f["chat_id"] == CHAT
            assert f["origin"] == "history_import"
            assert f["weight"] == 0.3
            assert f["expires_at"] is None
            assert f["status"] == "confirmed"
            assert f["target_user"] is None
        # message_timestamp = MAX(timestamp) пачки (сообщение id=14)
        assert facts[0]["message_timestamp"] == BASE_TS + 14 * 3600
        # FTS-строка есть
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts_fts"))[0]["c"] == 2
        # обработан ВЕСЬ диапазон пачки (вкл. нечётные density-пропуски)
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM smart_messages "
                "WHERE chat_id = ? AND history_processed = 0",
            (CHAT,)))[0]["c"] == 0

    @pytest.mark.asyncio
    async def test_resume_no_duplicates_new_rows_processed(self, tmp_path):
        """Второй прогон ничего не переобрабатывает; новые сообщения (id 7..10)
        обрабатываются; дублей фактов нет."""
        db = await _make_db(tmp_path, _text_rows(6))
        triples = [{"subject": "вася", "predicate": "знает про",
                    "object": "дрон"}]
        llm = FakeLLM(triples=triples)
        worker = await _make_worker(db, llm=llm, fact_density=0.5)
        stats1 = await worker.run()
        assert stats1["facts_inserted"] == 1
        count1 = (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"]
        # повторный прогон — пусто
        llm2 = FakeLLM(triples=[{"subject": "дубль", "predicate": "не должен",
                                 "object": "появиться"}])
        worker2 = await _make_worker(db, llm=llm2, fact_density=0.5)
        stats2 = await worker2.run()
        assert stats2["batches"] == 0 and stats2["done"] is True
        assert len(llm2.calls) == 0
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"] == count1
        # новые сообщения обрабатываются (только выбранные density: id 8, 10)
        await _append_messages(
            db, [_msg(i, f"новое событие номер {i} в чате")
                 for i in (7, 8, 9, 10)])
        worker3 = await _make_worker(db, llm=llm2, fact_density=0.5)
        stats3 = await worker3.run()
        assert stats3["batches"] == 1
        assert stats3["selected_msgs"] == 2
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"] == count1 + 1
        assert len(llm2.calls) == 1

    @pytest.mark.asyncio
    async def test_reset_rerun_ignores_duplicates(self, tmp_path):
        """--reset → переобработка: INSERT OR IGNORE (дубли rowcount 0),
        FTS не дублируется (edge 5), COUNT не растёт."""
        db = await _make_db(tmp_path, _text_rows(4))
        triples = [{"subject": "вася", "predicate": "пьёт", "object": "чай"}]
        worker = await _make_worker(db, llm=FakeLLM(triples=triples),
                                    fact_density=0.5)
        s1 = await worker.run()
        assert s1["facts_inserted"] == 1
        worker2 = await _make_worker(db, llm=FakeLLM(triples=triples),
                                     fact_density=0.5)
        s2 = await worker2.run(reset=True)
        assert s2["facts_inserted"] == 0
        assert s2["facts_ignored_dupes"] == 1
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"] == 1
        fts = await _fetch_all(db, "SELECT rowid FROM graph_facts_fts")
        rows = await _fetch_all(db, "SELECT id FROM graph_facts")
        assert {r["rowid"] for r in fts} == {r["id"] for r in rows}

    @pytest.mark.asyncio
    async def test_broken_json_batch_not_marked_and_retried(self, tmp_path):
        """Задача 2: одиночный LLM-фейл пачки (без --skip-errors) — пачка НЕ
        помечена, ПРОГОН ЗАВЕРШАЕТСЯ (не фатал!); следующий запуск с рабочим
        LLM обрабатывает — факты появляются ровно один раз."""
        db = await _make_db(tmp_path, _text_rows(6))
        worker = await _make_worker(
            db, llm=FakeLLM(error=HistoryLLMError("LLM умер")),
            fact_density=0.5)
        stats = await worker.run()          # НЕ raises
        assert stats["llm_errors"] == 1
        assert stats["done"] is False       # остались непомеченные кандидаты
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM smart_messages "
                "WHERE history_processed = 1"))[0]["c"] == 0
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"] == 0
        ok = FakeLLM(triples=[{"subject": "вася", "predicate": "вернулся из",
                               "object": "отпуска"}])
        worker2 = await _make_worker(db, llm=ok, fact_density=0.5)
        stats = await worker2.run()
        assert stats["batches"] == 1
        assert stats["facts_inserted"] == 1
        assert stats["llm_errors"] == 0

    @pytest.mark.asyncio
    async def test_skip_errors_continues(self, tmp_path):
        """--skip-errors: упавшая пачка пропускается (НЕ помечена) с
        WARNING-статистикой, следующие обрабатываются."""
        db = await _make_db(tmp_path, _text_rows(14))

        class FlakyLLM(FakeLLM):
            def __init__(self):
                super().__init__()
                self.n = 0

            async def extract(self, user_content, max_facts=8):
                self.n += 1
                if self.n == 1:
                    raise HistoryLLMError("первая пачка упала")
                return [{"subject": "вася", "predicate": "чинит",
                         "object": "сервер"}]

        llm = FlakyLLM()
        worker = await _make_worker(db, llm=llm, fact_density=0.5,
                                    batch_size=4, skip_errors=True)
        stats = await worker.run()
        assert stats["batches"] == 2
        assert stats["llm_errors"] == 1
        assert stats["facts_inserted"] == 1
        remain = await _fetch_all(
            db, "SELECT id FROM smart_messages WHERE history_processed = 0")
        assert {2, 4, 6, 8} <= {r["id"] for r in remain}
        done = await _fetch_all(
            db, "SELECT id FROM smart_messages WHERE history_processed = 1")
        assert {10, 12, 14} <= {r["id"] for r in done}

    @pytest.mark.asyncio
    async def test_limit_batches(self, tmp_path):
        """--limit N — стоп после N пачек (остаток не помечен)."""
        db = await _make_db(tmp_path, _text_rows(30))
        worker = await _make_worker(
            db, llm=FakeLLM(triples=[{"subject": "вася", "predicate": "спит",
                                      "object": "днём"}]),
            fact_density=0.5, batch_size=4)
        stats = await worker.run(limit_batches=1)
        assert stats["batches"] == 1
        assert stats["done"] is False
        assert stats["selected_msgs"] == 4       # id 2,4,6,8
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM smart_messages "
                "WHERE history_processed = 0"))[0]["c"] > 0

    @pytest.mark.asyncio
    async def test_min_fact_chars_filters_short_message(self, tmp_path):
        """Короткие тексты (трёп) не участвуют в пачках (--min-fact-chars)."""
        db = await _make_db(tmp_path, [
            _msg(1, "ок"),
            _msg(2, "окей"),
            _msg(3, "когда возвращаешься из отпуска? завтра или послезавтра"),
            _msg(4, "хз"),
        ])
        llm = FakeLLM(triples=[{"subject": "вася", "predicate": "в",
                                "object": "отпуске"}])
        worker = await _make_worker(db, llm=llm, fact_density=1.0,
                                    min_fact_chars=12)
        stats = await worker.run()
        assert stats["batches"] == 1
        assert stats["selected_msgs"] == 1     # только id=3 (длина ≥12)
        assert llm.calls and "возвращаешься" in llm.calls[0]
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM smart_messages "
                "WHERE history_processed = 0"))[0]["c"] == 0

    @pytest.mark.asyncio
    async def test_dry_run_counts_nothing_written(self, tmp_path):
        """dry-run: считает кандидатов/пачки, LLM не вызывает, БД не меняет."""
        db = await _make_db(tmp_path, _text_rows(10))
        worker = await _make_worker(db, llm=None, fact_density=0.5,
                                    embed_mode="skip")
        try:
            await worker.open()
            pending = await worker.pending_count()
            selected = await worker.pending_selected_count()
        finally:
            await worker.close()
        assert pending == 10
        assert selected == 5                   # id 2,4,6,8,10
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"] == 0

    @pytest.mark.asyncio
    async def test_fact_renders_message_date(self, tmp_path):
        """Факт с message_timestamp=дата сообщения рендерится [дата-сообщения]
        (build_rag_context 3-кортеж — COALESCE-источник уже покрыт T-760)."""
        db = await _make_db(tmp_path, _text_rows(4))
        worker = await _make_worker(
            db, llm=FakeLLM(triples=[{"subject": "вася", "predicate": "открыл",
                                      "object": "магазин"}]),
            fact_density=0.5, embed_mode="skip")
        await worker.run()
        facts = await _fetch_all(db, "SELECT fact, message_timestamp "
                                     "FROM graph_facts")
        row = facts[0]
        day = datetime.datetime.fromtimestamp(
            row["message_timestamp"], datetime.timezone.utc
        ).strftime("%Y-%m-%d")
        ctx = build_rag_context(
            [("history_import", row["fact"], row["message_timestamp"])])
        assert f"[{day}] " in ctx and "магазин" in ctx

    @pytest.mark.asyncio
    async def test_live_rows_excluded(self, tmp_path):
        """Строки без import_key (живая память бота) воркером не берутся."""
        db = await _make_db(tmp_path, [
            _msg(1, "импортированная история чата длинная и содержательная"),
            _msg(2, "живое сообщение бота тоже содержательное",
                 import_key=None),
        ])
        llm = FakeLLM(triples=[{"subject": "а", "predicate": "б",
                                "object": "в"}])
        worker = await _make_worker(db, llm=llm, fact_density=1.0)
        stats = await worker.run()
        assert stats["batches"] == 1
        assert stats["selected_msgs"] == 1
        done = await _fetch_all(
            db, "SELECT id FROM smart_messages WHERE history_processed = 1")
        assert {r["id"] for r in done} == {1}
        assert llm.calls and "импортированная" in llm.calls[0]


class _WavesLLM(FakeLLM):
    """Считающий мок: каждый вызов возвращает ОДИН уникальный факт
    (номер вызова) — счётчик вызовов == фактов без дублей-IGNORE."""

    def __init__(self):
        super().__init__()
        self.n = 0

    async def extract(self, user_content, max_facts=8):
        self.calls.append(user_content)
        self.n += 1
        return [{"subject": f"событие{self.n}", "predicate": "случилось",
                 "object": "в волне"}]


async def _processed_ids(db_path: str) -> set[int]:
    rows = await _fetch_all(
        db_path, "SELECT id FROM smart_messages WHERE history_processed = 1")
    return {int(r["id"]) for r in rows}


async def _anticorrelated_db(tmp_path) -> str:
    """БД как после FTS-импорта «свежим первым»: НОВЫЕ ts у НИЗКИХ id
    («свежая» волна 2026.json импортирована первой), СТАРЫЕ ts у ВЫСОКИХ id
    («старая» волна 10.2024/«желтой» импортирована последней)."""
    old_wave = [_msg(100 + i, f"старая волна сообщение {i} про события тех лет",
                     BASE_TS + i * 60) for i in range(10)]
    fresh_wave = [_msg(1 + i, f"свежая волна сообщение {i} про события этих дней",
                       BASE_TS + 10_000_000 + i * 60) for i in range(8)]
    return await _make_db(tmp_path, old_wave + fresh_wave)


class TestWorkerIdWindowBug:
    """B1-регресс (fix-раунд): выборка/пометка по id-диапазонам ломались на
    анти-корреляции id↔ts (FTS-импорт «свежий первым»)."""

    @pytest.mark.asyncio
    async def test_two_waves_all_candidates_extracted_no_loss(self, tmp_path):
        """Полный прогон по двум «импортным волнам» (старая — высокие id,
        свежая — низкие id): экстракция ВСЕХ кандидатов, done=True, потерь
        нет (пометка только фактически обработанных id, не диапазона)."""
        db = await _anticorrelated_db(tmp_path)
        llm = _WavesLLM()
        worker = await _make_worker(db, llm=llm, fact_density=1.0,
                                    batch_size=4)
        stats = await worker.run()
        # хронология: 10 старых (высокие id) → 3 пачки, затем 8 свежих
        # (низкие id) → 2 пачки; старая логика помечала бы весь [1..hi]
        # первой пачкой БЕЗ экстракции свежих
        assert stats["batches"] == 5
        assert stats["selected_msgs"] == 18
        assert stats["facts_inserted"] == 5
        assert stats["done"] is True
        assert len(llm.calls) == 5
        assert "старая волна" in llm.calls[0]
        assert "свежая волна" in llm.calls[-1]
        assert len(await _processed_ids(db)) == 18      # без потерь
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM smart_messages "
                "WHERE history_processed = 0"))[0]["c"] == 0

    @pytest.mark.asyncio
    async def test_resume_anticorrelated_no_loss(self, tmp_path):
        """--limit 1 (первая пачка — старые ts на высоких id): помечены
        ТОЛЬКО её строки (id IN), НИЗКИЕ id свежей волны НЕ помечены
        (старый id-диапазон [1..hi] пометил бы их без экстракции);
        второй прогон добивает ВСЁ — свежая волна экстрактится."""
        db = await _anticorrelated_db(tmp_path)
        llm = _WavesLLM()
        worker = await _make_worker(db, llm=llm, fact_density=1.0,
                                    batch_size=4)
        stats1 = await worker.run(limit_batches=1)
        assert stats1["batches"] == 1
        assert stats1["done"] is False
        assert stats1["facts_inserted"] == 1
        # ключевая регрессия: помечены ровно 4 строки первой пачки
        # (id 100..103), свежие низкие id (1..8) — НЕ помечены
        assert await _processed_ids(db) == {100, 101, 102, 103}
        remaining = await _fetch_all(
            db, "SELECT id FROM smart_messages WHERE history_processed = 0")
        assert {int(r["id"]) for r in remaining} == set(range(1, 9)) | \
            set(range(104, 110))
        # resume-прогон (новый воркер, тот же llm-счётчик): курсор
        # keyset-кортежа ничего не теряет
        worker2 = await _make_worker(db, llm=llm, fact_density=1.0,
                                     batch_size=4)
        stats2 = await worker2.run()
        assert stats2["batches"] == 4
        assert stats2["selected_msgs"] == 14
        assert stats2["facts_inserted"] == 4
        assert stats2["done"] is True
        assert len(llm.calls) == 5
        assert any("свежая волна" in c for c in llm.calls)
        assert len(await _processed_ids(db)) == 18
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts"))[0]["c"] == 5


# ── vec: float+int8 запись ──────────────────────────────────────────

def _vec_available() -> bool:
    try:
        import sqlite_vec  # noqa: F401
        return True
    except ImportError:
        return False


class TestWorkerVec:
    @pytest.mark.asyncio
    async def test_vec_rows_written_float_and_int8(self, tmp_path):
        """--embed-mode api: vec-строки (rowid=fact_id), float + int8
        (vec_quantize_int8), мета-колонки; probe+факты одним запросом."""
        if not _vec_available():
            pytest.skip("sqlite-vec not installed")
        db = await _make_db(tmp_path, _text_rows(6), create_vec=True)
        llm = FakeLLM(triples=[
            {"subject": "вася", "predicate": "запустил", "object": "бот"},
            {"subject": "петя", "predicate": "нашёл", "object": "баг"},
        ])
        embed = FakeEmbed()
        worker = await _make_worker(db, llm=llm, embed=embed,
                                    fact_density=0.5, embed_mode="api")
        stats = await worker.run()
        assert stats["facts_inserted"] == 2
        assert stats["no_vec"] == 0
        assert stats["vec"]["active"] is True
        assert stats["vec"]["int8"] is True
        rows = await _fetch_all(
            db, "SELECT rowid, chat_id, origin, expires_at, embedding, "
                "embedding_i8 FROM graph_facts_vec ORDER BY rowid")
        assert len(rows) == 2
        ids = await _fetch_all(db, "SELECT id FROM graph_facts ORDER BY id")
        assert [r["rowid"] for r in rows] == [r["id"] for r in ids]
        for r in rows:
            assert r["chat_id"] == CHAT
            assert r["origin"] == "history_import"
            assert r["expires_at"] is None
            # float-колонка — сырой бинарный блоб float32[dim] (не JSON!)
            float_vec = struct.unpack(f"<{_EMBED_DIM}f", bytes(r["embedding"]))
            assert len(float_vec) == _EMBED_DIM
            assert all(0.09 <= v <= 0.21 for v in float_vec)
            assert len(bytes(r["embedding_i8"])) == _EMBED_DIM
        assert embed.calls[0] == ["probe"]
        # факты одним запросом (второй probe — от повторного open() в done-
        # проверке run(); здесь важно: факт-вызов ровно один)
        assert ["вася запустил бот", "петя нашёл баг"] in embed.calls

    @pytest.mark.asyncio
    async def test_embed_failure_degrades_to_text(self, tmp_path):
        """Embed-фейл → факт остаётся текстом/FTS, no_vec-счётчик, сессия
        не падает; vec-строк нет."""
        if not _vec_available():
            pytest.skip("sqlite-vec not installed")
        db = await _make_db(tmp_path, _text_rows(6), create_vec=True)
        worker = await _make_worker(
            db, llm=FakeLLM(triples=[{"subject": "вася", "predicate": "готовит",
                                      "object": "отчёт"}]),
            embed=FakeEmbed(fail_on_call=2),   # probe ok, факты — фейл
            fact_density=0.5, embed_mode="api")
        stats = await worker.run()
        assert stats["facts_inserted"] == 1
        assert stats["no_vec"] == 1
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts_vec"))[0]["c"] == 0
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts_fts"))[0]["c"] == 1

    @pytest.mark.asyncio
    async def test_skip_embed_mode_no_vec_and_backfill(self, tmp_path):
        """--embed-mode skip → vec не пишется; --vec-backfill догоняет
        (float+int8); повторная догонка — no-op."""
        if not _vec_available():
            pytest.skip("sqlite-vec not installed")
        db = await _make_db(tmp_path, _text_rows(6), create_vec=True)
        worker = await _make_worker(
            db, llm=FakeLLM(triples=[{"subject": "вася", "predicate": "собрал",
                                      "object": "дрон"}]),
            fact_density=0.5, embed_mode="skip")
        stats = await worker.run()
        assert stats["facts_inserted"] == 1
        assert stats["vec"]["active"] is False
        assert stats["vec"]["reason"] == "--embed-mode skip"
        assert (await _fetch_all(
            db, "SELECT COUNT(*) AS c FROM graph_facts_vec"))[0]["c"] == 0
        report = await run_vec_backfill(db, embed_client=FakeEmbed(),
                                        chat_id=CHAT)
        assert report["vec_rows"] == 1
        assert report["no_vec"] == 0
        assert report["done"] is True
        rows = await _fetch_all(
            db, "SELECT rowid, embedding_i8 FROM graph_facts_vec")
        assert len(rows) == 1
        assert len(bytes(rows[0]["embedding_i8"])) == _EMBED_DIM
        report2 = await run_vec_backfill(db, embed_client=FakeEmbed(),
                                         chat_id=CHAT)
        assert report2["vec_rows"] == 0 and report2["checked"] == 0
