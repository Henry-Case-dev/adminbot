"""ASAP-4 волна C (epic `asap-4-embedding-graphrag-cover-runtime`, spec §3
C.1–C.4, ADR-1028-7 D7; T-4422…T-4426) — Summary full-window.

Покрытие:
  * T-4422 (§50.36/§51/§52): capacity guard — planning estimate до model
    call (прод-кейс Q17: chunks=1 на 688 сообщений обязан стать >1);
    deterministic repair переполнения (дедуп/подсмыслы/бюджет) — 31+ фактов
    в широком топике НЕ invalid'ит весь прогон (golden J); merge-union
    после шардирования не превышает структурные капы; reply-chain/evidence
    сохраняются при cross-chunk merge (§50.33/§50.34); fail-soft §50.35 не
    тронут; kill-switch OFF → too_many_facts → invalid (бит-в-бит).
  * T-4423 (§53/§53.1/§53.2/§54, §50.20): 5 reason codes; фикс «named
    quote при найденном тексте + доказанном спикере → valid»; repair
    (de-quote/снятие спикера) вместо whole-run Legacy (§75); ambiguous →
    repair; attribution не ослаблен (неподтверждённая прямая речь не
    публикуется); метрики quotes_total/verified/repaired/removed;
    kill-switch OFF → прежняя матрица (баг §50.20 живёт — rollback).
  * T-4424 (§55/§56/§57): Legacy full-window — тихий XML hard stop удалён;
    reuse semantic package; §74: 688 сообщений — нет silent 307; малые
    окна бит-в-бит; degraded coverage виден; kill-switch OFF → прежний
    cap.
  * T-4425 (§50.37/§58): coverage-метрики source window (числа, R17);
    MAX_SUMMARY_PARTS — НЕ input coverage cap (guard-тест); source
    normalization не меняет смысл, алгоритмическая предфильтрация ASAP-2.1
    не восстановлена (R4-D-038).
  * mca_events: новые reason codes волны C в едином словаре REASON_CODES.

R17: в логах только числа/коды/id; тексты цитат и сообщений не логируются.
"""
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import mca_events as me
from services import summary_generator as sg
from services.summary_l1_capacity import (
    estimate_expected_facts,
    plan_required_chunks,
    repair_capacity_overflow,
)
from services.summary_l1_clusterizer import run_l1, last_run_coverage
from services.summary_legacy_fullwindow import (
    build_legacy_package_content,
    compute_package_coverage,
    flat_fits,
)
from services.summary_l2_writer import validate_l2_document, run_l2
from services.summary_quote_repair import (
    REASON_QUOTE_SOURCE_AMBIGUOUS,
    REASON_QUOTE_SPEAKER_MISMATCH,
    REASON_QUOTE_SPEAKER_UNRESOLVED,
    REASON_QUOTE_TEXT_NOT_FOUND,
    REASON_QUOTE_ATTRIBUTION_REPAIRED,
    process_paragraph_quotes,
)
from services.summary_run_log import RunContext
from services.summary_xml import XmlGroundingBuilder

pytestmark = pytest.mark.asap4

CHAT = -100266
RID = "asap4c-run-0001"


@pytest.fixture(autouse=True)
def _wc_env(monkeypatch):
    """Волна C по умолчанию ON (прод-дефолты). Capacity planning живёт в
    конверте lossless chunking ASAP-3.1 (единый envelope: auto/manual_cap +
    SUMMARY_COVERAGE_CHUNKING_ENABLED) — conftest-изоляция ASAP-3.1 держит
    этот флаг OFF для не-asap31 тестов, сценарии зоны C доопределяют его
    явно (паттерн волны B `_wb_env`)."""
    _flag(monkeypatch, "SUMMARY_COVERAGE_CHUNKING_ENABLED", True)
    yield


# ── helpers ────────────────────────────────────────────────────────────────

def _flag(monkeypatch, name, value):
    """Патч флага на всех вариантах класса Settings (паттерн Wave A/B
    S10.18-10: reload пересоздаёт config.settings.settings, сервисные
    модули держат instance исходного класса — патчим все)."""
    import config.settings as _cs
    import services.summary_l1_capacity as _cap
    import services.summary_quote_repair as _qr
    import services.summary_legacy_fullwindow as _lfw
    classes = {Settings, type(_cs.settings), type(_cap.settings),
               type(_qr.settings), type(_lfw.settings)}
    for _cls in classes:
        monkeypatch.setattr(_cls, name, value, raising=False)


def _row(i, *, text=None, reply_to=None, author="Вася", user_id=10):
    return {
        "id": 1000 + i,
        "tg_message_id": 5000 + i,
        "timestamp": 1_759_400_000 + i,
        "user_id": user_id,
        "author_name": author,
        "text": text if text is not None else f"сообщение номер {i}",
        "reply_to_id": reply_to,
        "media_type": "text",
    }


def _rows(count, *, reply_every=0):
    return [_row(i, reply_to=(5000 + i - 1) if reply_every
                and i % reply_every == 0 else None)
            for i in range(1, count + 1)]


def _payload_for_content(user_content: str, *, topic="широкая тема",
                         fact_per_message: bool = True) -> str:
    """Валидный §95-payload по фактическому чанку (fake LLM): все id чанка —
    одна тема; ≤30 фактов/тред не гарантируем — переполнение ловит guard
    (или нет — по kill-switch)."""
    ids: list = []
    for line in str(user_content).splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        mid = item.get("message_id")
        if isinstance(mid, int) and not isinstance(mid, bool):
            ids.append(mid)
    facts = [{"text": f"факт про сообщение {mid}",
              "evidence_message_ids": [mid]}
             for mid in (ids if fact_per_message else ids[:5])]
    return json.dumps({
        "schema_version": 2,
        "threads": [{"thread_id": "thread_001", "topic": topic,
                     "message_ids": list(ids), "facts": facts}],
        "unassigned_message_ids": [],
    }, ensure_ascii=False)


class ScriptLLM:
    """Fake LLM-канал для ``run_l1``: payload'ы по очереди; последний
    переиспользуется (каждый chunk-прогон строит payload по своему
    user-контенту)."""

    def __init__(self, mode="per_chunk", fixed=None):
        self.mode = mode
        self.fixed = fixed
        self.calls = []

    async def __call__(self, messages):
        self.calls.append(messages)
        if self.mode == "fixed":
            return self.fixed
        return _payload_for_content(messages[1]["content"])


class L2FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self.payload


def _pkg(*, fragments=None, facts=None):
    return {"schema_version": 2, "status": "ok",
            "threads": [{"thread_id": "thread_001", "name": "тема",
                         "description": "", "chronology": [],
                         "evidence_ids": [],
                         "facts": facts or [],
                         "fragments": fragments or []}],
            "unassigned_message_ids": [], "service": {}, "budget": {}}


def _frag(mid, author_id, name, text):
    return {"message_id": mid, "author_id": author_id, "display_name": name,
            "timestamp": 1, "reply_to_id": None, "text": text}


def _doc(title="Статья", paragraphs=None):
    return {"schema_version": 1, "title": title,
            "paragraphs": paragraphs or [{"text": "текст", "emphasis": None}]}


# ══ T-4422 (§50.36/§51/§52): capacity guard ════════════════════════════════

class TestCapacityPlanning:
    def test_q17_planning_gives_more_than_one_chunk_for_688(self):
        """Прод-кейс Q17: 688 сообщений (tokens_in=46118 влезли в один
        запрос) — planning обязан был дать >1 chunk."""
        rows = _rows(688)
        expected = estimate_expected_facts(rows)
        assert expected > 0
        assert plan_required_chunks(expected) >= 2

    def test_reply_density_raises_estimate(self):
        flat = estimate_expected_facts(_rows(100))
        dense = estimate_expected_facts(_rows(100, reply_every=2))
        assert dense > flat

    @pytest.mark.asyncio
    async def test_q17_688_messages_sharded_no_invalid(self, caplog):
        """688 сообщений, вход влезает в один запрос → шардирование по
        кардинальности: >1 LLM-вызов, merged результат ok, coverage 100%,
        ни одно сообщение не потеряно (§74-каркас на уровне L1)."""
        rows = _rows(688)
        llm = ScriptLLM()
        with caplog.at_level(logging.INFO):
            result = await run_l1(llm=None, rows=rows, chat_id=CHAT,
                                  correlation_id=RID,
                                  budget=("tokens", 10_000_000),
                                  llm_call=llm)
        assert result.status == "ok", result.invalid_reason
        assert len(llm.calls) >= 2            # planning дал >1 chunk
        assert result.chunk_count == len(llm.calls)
        assert result.facts_count == 688      # ничего не потеряно
        coverage = last_run_coverage()
        assert coverage is not None
        assert coverage["source_messages_total"] == 688
        assert coverage["coverage_percent"] == 100.0
        assert any("L1_CAPACITY_PLAN" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_golden_j_wide_topic_31_facts_not_invalid(self):
        """Golden J: 31+ полезных фактов в широком топике — pipeline
        чинит детерминированно, whole run НЕ invalid."""
        rows = _rows(40)
        payload = json.dumps({
            "schema_version": 2,
            "threads": [{"thread_id": "thread_001", "topic": "широкая тема",
                         "message_ids": [5000 + i for i in range(1, 41)],
                         "facts": [{"text": f"полезный факт номер {n}",
                                    "evidence_message_ids": [
                                        5000 + (n % 40) + 1]}
                                   for n in range(1, 46)]}],
            "unassigned_message_ids": [],
        }, ensure_ascii=False)
        llm = ScriptLLM(mode="fixed", fixed=payload)
        result = await run_l1(llm=None, rows=rows, chat_id=CHAT,
                              correlation_id=RID,
                              budget=("tokens", 10_000_000), llm_call=llm)
        assert result.status == "ok", result.invalid_reason
        assert result.facts_count == 45
        # Подсмысл ≤ структурного капа.
        max_thread = max(len(t["facts"])
                         for t in result.payload["threads"])
        assert max_thread <= 30

    @pytest.mark.asyncio
    async def test_guard_off_too_many_facts_invalid_parity(self, monkeypatch):
        """OFF-паритет (spec §8.2): guard OFF → too_many_facts → invalid →
        fallback package (как сейчас), ретрая/починки нет."""
        _flag(monkeypatch, "SUMMARY_L1_CAPACITY_GUARD_ENABLED", False)
        rows = _rows(40)
        payload = json.dumps({
            "schema_version": 2,
            "threads": [{"thread_id": "thread_001", "topic": "т",
                         "message_ids": [5000 + i for i in range(1, 41)],
                         "facts": [{"text": f"факт {n}",
                                    "evidence_message_ids": [
                                        5000 + (n % 40) + 1]}
                                   for n in range(1, 46)]}],
            "unassigned_message_ids": [],
        }, ensure_ascii=False)
        llm = ScriptLLM(mode="fixed", fixed=payload)
        result = await run_l1(llm=None, rows=rows, chat_id=CHAT,
                              correlation_id=RID,
                              budget=("tokens", 10_000_000), llm_call=llm)
        assert result.status == "invalid"
        assert result.invalid_reason == "too_many_facts"
        assert len(llm.calls) == 1

    def test_repair_capacity_overflow_units(self):
        """§51-юниты: дедуп дубликатов, split подсмыслов, бюджет."""
        facts = [{"text": f"факт {n}", "evidence_message_ids": [n]}
                 for n in range(1, 36)]
        facts.append({"text": "факт 1", "evidence_message_ids": [99]})
        data = {"schema_version": 2,
                "threads": [{"topic": "тема", "message_ids": list(range(1, 101)),
                             "facts": facts}],
                "unassigned_message_ids": []}
        payload, stats = repair_capacity_overflow(data)
        assert payload is not None
        assert stats["duplicates_merged"] == 1
        assert stats["threads_split"] == 1
        merged = payload["threads"]
        assert len(merged) == 2
        assert all(len(t["facts"]) <= 30 for t in merged)
        # Evidence дубликата объединён.
        first = [f for f in merged[0]["facts"]
                 if f["text"] == "факт 1"][0]
        assert 1 in first["evidence_message_ids"]
        assert 99 in first["evidence_message_ids"]

    def test_repair_budget_allocation_drops_lowest_evidence(self):
        """MAX_FACTS_TOTAL=1000 — структурный потолок: при тотальном
        переполнении первыми вылетают наименее подтверждённые факты,
        счётчик виден."""
        threads = []
        n = 0
        for t in range(40):
            facts = []
            for _ in range(30):
                n += 1
                facts.append({"text": f"уникальный факт {n}",
                              "evidence_message_ids": [n] if n % 2 else
                              [n, n + 1]})
            threads.append({"topic": f"тема {t}", "message_ids": [n],
                            "facts": facts})
        payload, stats = repair_capacity_overflow(
            {"schema_version": 2, "threads": threads,
             "unassigned_message_ids": []})
        assert stats["facts_dropped_budget"] > 0
        total = sum(len(t["facts"]) for t in payload["threads"])
        assert total <= 1000
        # Каждая тема сохранила представительство (не вынесена целиком).
        assert len(payload["threads"]) == 40

    def test_repair_input_not_mutated(self):
        facts = [{"text": f"факт {n}", "evidence_message_ids": [n]}
                 for n in range(1, 36)]
        data = {"schema_version": 2,
                "threads": [{"topic": "т", "message_ids": [1], "facts": facts}],
                "unassigned_message_ids": []}
        import copy
        snapshot = copy.deepcopy(data)
        repair_capacity_overflow(data)
        assert data == snapshot

    @pytest.mark.asyncio
    async def test_cross_chunk_merge_preserves_reply_evidence(self):
        """§50.33/§50.34: overlap-сообщение связывает чанки; тема с
        пересечением id объединяется, evidence union — вопрос в A и ответ
        в B не теряются; many-to-many сохранён."""
        rows = _rows(6)
        # Два чанка по 3 сообщения с overlap: fake строит по чанку, topics
        # одинаковые → merge по пересечению message_ids.
        llm = ScriptLLM()
        result = await run_l1(llm=None, rows=rows, chat_id=CHAT,
                              correlation_id=RID,
                              budget=("tokens", 10_000_000), llm_call=llm)
        assert result.status == "ok"
        # 6 сообщений, ожидаемых фактов ~1 → один chunk; здесь проверяем
        # только merge-механику на payload уровне.
        from services.summary_l1_clusterizer import merge_l1_payloads
        merged = merge_l1_payloads([
            {"schema_version": 2,
             "threads": [{"thread_id": "thread_001", "topic": "т",
                          "message_ids": [1, 2, 3],
                          "facts": [{"text": "вопрос",
                                     "evidence_message_ids": [1]}]}],
             "unassigned_message_ids": []},
            {"schema_version": 2,
             "threads": [{"thread_id": "thread_001", "topic": "т",
                          "message_ids": [3, 4, 5],
                          "facts": [{"text": "ответ",
                                     "evidence_message_ids": [4]}]}],
             "unassigned_message_ids": []},
        ])
        assert len(merged["threads"]) == 1
        assert merged["threads"][0]["message_ids"] == [1, 2, 3, 4, 5]
        texts = {f["text"] for f in merged["threads"][0]["facts"]}
        assert texts == {"вопрос", "ответ"}      # уникальные факты живы

    @pytest.mark.asyncio
    async def test_failsoft_unknown_id_still_invalid(self):
        """§50.35 не тронут: unknown message_id — fail-soft класс контракта
        (repair удаляет битое, structure бесполезна → correction-класс),
        capacity guard НЕ маскирует структурные причины."""
        payload = json.dumps({
            "schema_version": 2,
            "threads": [{"thread_id": "thread_001", "topic": "т",
                         "message_ids": [999999],
                         "facts": [{"text": "факт",
                                    "evidence_message_ids": [999999]}]}],
            "unassigned_message_ids": [],
        }, ensure_ascii=False)
        llm = ScriptLLM(mode="fixed", fixed=payload)
        result = await run_l1(llm=None, rows=_rows(3), chat_id=CHAT,
                              correlation_id=RID,
                              budget=("tokens", 10_000_000), llm_call=llm)
        assert result.status == "invalid"
        assert result.invalid_reason == "l1_useless_after_repair"


# ══ T-4423 (§53/§53.1/§53.2/§54, §50.20): quote-контур ═════════════════════

QUOTE = "на улице шёл сильный дождь"


class TestQuoteRepair:
    def test_found_and_proven_speaker_valid_fix_50_20(self):
        """Фикс §50.20: цитата найдена в пакете + именная атрибуция +
        спикер доказан фрагментом → VALID (не reject)."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        text = f'Вася: "{QUOTE}"'
        new_text, stats = process_paragraph_quotes(text, package)
        assert new_text == text                  # без изменений
        assert stats.verified == 1
        assert stats.repaired == 0
        assert stats.failure_reason is None

    def test_found_speaker_mismatch_repaired(self):
        """found + атрибуция ≠ автору фрагмента → repair (снять имя +
        de-quote), причина quote_speaker_mismatch; документ не падает."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        text = f'Лёха: "{QUOTE}"'
        new_text, stats = process_paragraph_quotes(text, package)
        assert "Лёха" not in new_text
        assert '"' not in new_text
        assert QUOTE in new_text                 # событие сохранено
        assert REASON_QUOTE_SPEAKER_MISMATCH in stats.reason_codes
        assert REASON_QUOTE_ATTRIBUTION_REPAIRED in stats.reason_codes
        assert stats.repaired == 1
        assert stats.failure_reason is None

    def test_not_found_named_repaired(self):
        """Выдуманная цитата + именная атрибуция: раньше — reject всей
        статьи; теперь — repair (§53: не отправлять статью в Legacy из-за
        одной repairable цитаты)."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        text = 'Вася: "совсем выдуманная фраза которой нет"'
        new_text, stats = process_paragraph_quotes(text, package)
        assert REASON_QUOTE_TEXT_NOT_FOUND in stats.reason_codes
        assert REASON_QUOTE_ATTRIBUTION_REPAIRED in stats.reason_codes
        assert stats.repaired == 1
        assert "Вася" not in new_text
        assert '"' not in new_text

    def test_not_found_without_attribution_dequoted(self):
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        text = 'Кто-то якобы сказал "совсем выдуманная фраза".'
        new_text, stats = process_paragraph_quotes(text, package)
        assert REASON_QUOTE_TEXT_NOT_FOUND in stats.reason_codes
        assert '"' not in new_text
        assert stats.verified == 0

    def test_ambiguous_source_repaired(self):
        """Цитата матчится с фрагментами ДВУХ разных авторов →
        quote_source_ambiguous → repair (ближайшее имя не подставляется)."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE),
                                  _frag(102, 20, "Лёха", f"преамбула {QUOTE}")])
        text = f'Макс: "{QUOTE}"'
        new_text, stats = process_paragraph_quotes(text, package)
        assert REASON_QUOTE_SOURCE_AMBIGUOUS in stats.reason_codes
        assert "Макс" not in new_text
        assert stats.repaired == 1

    def test_speaker_unresolved_when_only_fact_text(self):
        """Цитата есть только среди facts (без авторского контекста
        фрагментов) → speaker unresolved → repair, не reject."""
        package = _pkg(facts=[{"text": QUOTE,
                               "evidence_message_ids": [101]}])
        text = f'Вася: "{QUOTE}"'
        new_text, stats = process_paragraph_quotes(text, package)
        assert REASON_QUOTE_SPEAKER_UNRESOLVED in stats.reason_codes
        assert stats.repaired == 1
        assert "Вася" not in new_text

    def test_verb_tail_attribution_repaired(self):
        """Хвостовая атрибуция с доказанным спикером → валидно (текст не
        меняется, §50.20-фикс); ремонт не нужен."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        text = f'"{QUOTE}", — сказал Вася'
        new_text, stats = process_paragraph_quotes(text, package)
        assert new_text == text
        assert stats.verified == 1
        assert stats.repaired == 0

    def test_verb_tail_unproven_speaker_repaired(self):
        """Хвостовая атрибуция БЕЗ имени (`— сказал`) → спикер не доказан →
        repair снимает хвост и кавычки."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        text = f'"{QUOTE}", — сказал кто-то из участников'
        new_text, stats = process_paragraph_quotes(text, package)
        assert '"' not in new_text
        assert stats.repaired == 1

    def test_metrics_safe_no_quote_text(self, caplog):
        """Метрики §53.2 без текстов цитат (R17): as_metrics — только
        числа/коды."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        _text, stats = process_paragraph_quotes(
            f'Лёха: "{QUOTE}"', package)
        blob = json.dumps(stats.as_metrics(), ensure_ascii=False)
        assert QUOTE not in blob
        assert stats.as_metrics()["quotes_total"] == 1
        assert stats.as_metrics()["quotes_repaired"] == 1

    def test_metrics_split_repair_history_vs_unresolved_blockers(self):
        """W1-A: as_metrics разделяет историю УСПЕШНЫХ ремонтов
        (quote_repair_reason_codes: конкретная причина + repaired-маркер) и
        текущие неустранённые блокеры (quote_unresolved_blockers — на
        usable-документе пусто); quote_reason_codes = union обоих
        (совместимость старых читателей логов/observability)."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        _text, stats = process_paragraph_quotes(
            f'Лёха: "{QUOTE}"', package)
        m = stats.as_metrics()
        assert REASON_QUOTE_SPEAKER_MISMATCH in m["quote_repair_reason_codes"]
        assert REASON_QUOTE_ATTRIBUTION_REPAIRED in \
            m["quote_repair_reason_codes"]
        assert m["quote_unresolved_blockers"] == []
        assert m["quote_reason_codes"] == sorted(
            set(m["quote_repair_reason_codes"])
            | set(m["quote_unresolved_blockers"]))

    def test_metrics_unresolved_blockers_on_repair_impossible(
            self, monkeypatch):
        """W1-A: repair невозможен (fail-closed путь §54) → причина
        фиксируется как ЖИВОЙ unresolved-блокер (proof для review) +
        failure_reason для писателя; в union она тоже видна."""
        import services.summary_quote_repair as qr
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        monkeypatch.setattr(qr, "_repair_quote_span", lambda t, q: (t, False))
        monkeypatch.setattr(qr, "_remove_quote_span", lambda t, q: (t, False))
        _text, stats = qr.process_paragraph_quotes(
            f'Лёха: "{QUOTE}"', package)
        # цитата в пуле, имя атрибуции ≠ автор фрагмента → speaker mismatch
        assert stats.failure_reason == REASON_QUOTE_SPEAKER_MISMATCH
        assert stats.unresolved_blockers == [REASON_QUOTE_SPEAKER_MISMATCH]
        m = stats.as_metrics()
        assert m["quote_unresolved_blockers"] == [REASON_QUOTE_SPEAKER_MISMATCH]
        assert REASON_QUOTE_SPEAKER_MISMATCH in m["quote_reason_codes"]

    def test_validate_metrics_split_fields_writer_merge(self):
        """W1-A: валидатор несёт раздельные каналы в metrics: repair-история
        (+ repaired-маркер), unresolved-блокеры пусты на usable-документе,
        quote_reason_codes = union (совместимость Decision Trace/логов)."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        doc = _doc(paragraphs=[{"text": f'Лёха: "{QUOTE}"',
                                "emphasis": None}])
        document, metrics = validate_l2_document(doc, package)
        assert document is not None
        assert set(metrics["quote_repair_reason_codes"]) == {
            REASON_QUOTE_SPEAKER_MISMATCH, REASON_QUOTE_ATTRIBUTION_REPAIRED}
        assert metrics["quote_unresolved_blockers"] == []
        # union (писатель сохраняет порядок поступления — сравниваем множества)
        assert set(metrics["quote_reason_codes"]) == (
            set(metrics["quote_repair_reason_codes"])
            | set(metrics["quote_unresolved_blockers"]))

    def test_validate_document_with_repairable_quote_ok(self):
        """Интеграция валидатора (ON): один плохой quote в живой статье →
        документ валиден, абзац отремонтирован (§75 — repair до Legacy)."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        doc = _doc(paragraphs=[
            {"text": f'Вася: "{QUOTE}", и все пошли домой', "emphasis": None},
            {"text": 'Потом Лёха: "выдумка которой нет в пакете"',
             "emphasis": None},
            {"text": "Финал вечера — тишина.", "emphasis": None},
        ])
        document, metrics = validate_l2_document(doc, package)
        assert document is not None, metrics
        assert metrics["quotes_total"] == 2
        assert metrics["quotes_verified"] == 1     # доказанная — сохранена
        assert metrics["quotes_repaired"] == 1     # выдуманная — отремонтирована
        assert metrics["status"] == "ok"

    def test_attribution_not_weakened_verified_quote_kept(self):
        """§54: доказанная цитата сохраняется (атрибуция не ослабляется)."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        doc = _doc(paragraphs=[
            {"text": f'Вася: "{QUOTE}"', "emphasis": None}])
        document, metrics = validate_l2_document(doc, package)
        assert document is not None
        text = document["paragraphs"][0]["text"]
        assert QUOTE in text
        assert metrics["quotes_verified"] == 1

    def test_off_parity_50_20_matrix(self, monkeypatch):
        """Kill-switch OFF → прежняя validator-матрица §50.20 бит-в-бит
        (named+found → reject quote_attribution; unverified+named →
        reject)."""
        _flag(monkeypatch, "SUMMARY_QUOTE_REPAIR_ENABLED", False)
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        doc = _doc(paragraphs=[{"text": f'Вася: "{QUOTE}"',
                                "emphasis": None}])
        document, metrics = validate_l2_document(doc, package)
        assert document is None
        assert metrics["reason"] == "quote_attribution"
        doc2 = _doc(paragraphs=[{"text": 'Вася: "выдумка которой нет"',
                                 "emphasis": None}])
        document2, metrics2 = validate_l2_document(doc2, package)
        assert document2 is None
        assert metrics2["reason"] == "quote_attribution"

    @pytest.mark.asyncio
    async def test_s75_run_l2_repairs_not_legacy(self):
        """§75: одна неподтверждённая цитата в живой статье → run_l2
        возвращает usable-документ (repair), а не invalid → LEVEL-3 Legacy
        не запускается."""
        package = _pkg(fragments=[_frag(101, 10, "Вася", QUOTE)])
        payload = json.dumps(_doc(paragraphs=[
            {"text": f'Вася: "{QUOTE}"', "emphasis": None},
            {"text": 'Затем Макс: "полностью выдуманная цитата"',
             "emphasis": None},
        ], title="Вечер"), ensure_ascii=False)
        llm = L2FakeLLM(payload)
        result = await run_l2(llm, package, service={},
                              correlation_id=RID, chat_id=CHAT)
        assert result.usable, (result.status, result.invalid_reason)
        texts = [p["text"] for p in result.document["paragraphs"]]
        # Доказанная цитата сохранена с атрибуцией (§54: attribution не
        # ослабляется), выдуманная — отремонтирована (без кавычек/имени).
        assert f'"{QUOTE}"' in texts[0] and "Вася" in texts[0]
        assert '"' not in texts[1] and "Макс" not in texts[1]
        assert result.metrics["quotes_verified"] == 1
        assert result.metrics["quotes_repaired"] == 1

    def test_reason_codes_in_mca_events_vocabulary(self):
        """Новые reason codes §53.1 — в ЕДИНОМ словаре mca_events (не новый
        словарь). Umbrella ``quote_attribution`` остаётся в L2-писателе
        (логи/OFF-совместимость), новые подпричины — здесь."""
        for code in (REASON_QUOTE_TEXT_NOT_FOUND,
                     REASON_QUOTE_SPEAKER_UNRESOLVED,
                     REASON_QUOTE_SPEAKER_MISMATCH,
                     REASON_QUOTE_SOURCE_AMBIGUOUS,
                     REASON_QUOTE_ATTRIBUTION_REPAIRED):
            assert code in me.REASON_CODES
        for code in ("l1_capacity_sharded", "l1_capacity_repaired",
                     "legacy_full_window", "legacy_coverage_degraded"):
            assert code in me.REASON_CODES


# ══ T-4424 (§55/§56/§57): Legacy full-window ═══════════════════════════════

def _caps_hot(monkeypatch, max_messages, max_chars):
    from services import hot_config as hot
    real_get = hot.get

    def fake_get(key, default=None):
        if key == "limits.summary_max_window_messages":
            return max_messages
        if key == "limits.summary_max_context_chars":
            return max_chars
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


class LegacyFakeLLM:
    """Fake основного LLM для Legacy-пайплайна (generate — async)."""

    def __init__(self, text="саммари текста"):
        self.text = text
        self.messages = None

    async def generate(self, messages, **kwargs):
        self.messages = messages
        return self.text


def _legacy_gen(monkeypatch, rows):
    from tests.test_summary_generator import FakeMemory
    llm = LegacyFakeLLM()
    gen = sg.SummaryGenerator(FakeMemory(rows), XmlGroundingBuilder(),
                              llm, AsyncMock())
    gen._hybrid_l2_enabled = AsyncMock(return_value=False)
    return gen


class TestLegacyFullWindow:
    @pytest.mark.asyncio
    async def test_q74_688_messages_no_silent_307(self, monkeypatch, caplog):
        """§74: 688-message synthetic source — нет silent 307-cap: весь
        window представлен в контенте (full-window пакет), coverage 100%."""
        _caps_hot(monkeypatch, max_messages=100, max_chars=5000)
        rows = _rows(688)
        gen = _legacy_gen(monkeypatch, rows)
        ctx = RunContext(run_id=RID, chat_id=CHAT, mode="off")
        with caplog.at_level(logging.INFO):
            published = await gen._run_legacy_pipeline(
                CHAT, rows, None, None, RID, ctx, skip_memorize=True)
        assert published is True
        assert any("LEGACY_FULL_WINDOW" in r.message
                   and "source_messages=688" in r.message
                   for r in caplog.records)
        assert ctx.source_total == 688
        assert ctx.source_considered == 688
        assert ctx.source_coverage == 100.0
        assert not any("LEGACY_COVERAGE_DEGRADED" in r.message
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_small_window_flat_xml_bit_identical(self, monkeypatch,
                                                       caplog):
        """Малое окно (≤ кап) — плоский <chat_history> бит-в-бит, без
        full-window ветки и без coverage-записи."""
        _caps_hot(monkeypatch, max_messages=500, max_chars=120000)
        rows = _rows(5)
        gen = _legacy_gen(monkeypatch, rows)
        ctx = RunContext(run_id=RID, chat_id=CHAT, mode="off")
        with caplog.at_level(logging.INFO):
            published = await gen._run_legacy_pipeline(
                CHAT, rows, None, None, RID, ctx, skip_memorize=True)
        assert published is True
        assert not any("LEGACY_FULL_WINDOW" in r.message
                       for r in caplog.records)
        assert ctx.source_coverage is None
        assert gen.llm.messages is not None
        assert "<chat_history>" in gen.llm.messages[1]["content"]

    @pytest.mark.asyncio
    async def test_semantic_package_reuse_from_hybrid(self, monkeypatch,
                                                      caplog):
        """ADR D7.3: Level-3 получает ТОТ ЖЕ hierarchical-reduced пакет,
        что и L2 (semantic_package) — вторая редукция не строится."""
        _caps_hot(monkeypatch, max_messages=10, max_chars=1000)
        rows = _rows(30)
        package = {
            "schema_version": 2, "status": "ok",
            "threads": [{"thread_id": "thread_001", "name": "тема",
                         "description": "",
                         "chronology": [{"message_id": 5000 + i,
                                         "timestamp": 1 + i,
                                         "topic_ids": ["thread_001"]}
                                        for i in range(1, 31)],
                         "evidence_ids": [], "facts": [],
                         "fragments": [_frag(5000 + i, 10, "Вася",
                                             f"текст {i}")
                                       for i in range(1, 31)]}],
            "unassigned_message_ids": [], "service": {}, "budget": {}}
        gen = _legacy_gen(monkeypatch, rows)
        ctx = RunContext(run_id=RID, chat_id=CHAT, mode="off")
        with caplog.at_level(logging.INFO):
            published = await gen._run_legacy_pipeline(
                CHAT, rows, None, None, RID, ctx, skip_memorize=True,
                semantic_package=package)
        assert published is True
        assert any("mode=semantic_package" in r.message
                   for r in caplog.records)
        assert ctx.source_considered == 30
        assert ctx.source_coverage == 100.0
        content = gen.llm.messages[1]["content"]
        assert "ИСТОРИЯ ЧАТА" in content
        assert '"message_id":5030' in content       # хвост окна жив

    @pytest.mark.asyncio
    async def test_degraded_coverage_visible(self, monkeypatch, caplog):
        """§57: пакет покрыл не всё окно → degraded coverage ВИДЕН
        (WARN + событие + run state), никогда не молча."""
        _caps_hot(monkeypatch, max_messages=10, max_chars=1000)
        rows = _rows(30)
        package = {
            "schema_version": 2, "status": "ok",
            "threads": [{"thread_id": "thread_001", "name": "тема",
                         "description": "",
                         "chronology": [{"message_id": 5000 + i,
                                         "timestamp": 1 + i,
                                         "topic_ids": ["thread_001"]}
                                        for i in range(1, 14)],
                         "evidence_ids": [], "facts": [],
                         "fragments": []}],
            "unassigned_message_ids": [], "service": {}, "budget": {}}
        gen = _legacy_gen(monkeypatch, rows)
        ctx = RunContext(run_id=RID, chat_id=CHAT, mode="off")
        with caplog.at_level(logging.WARNING):
            published = await gen._run_legacy_pipeline(
                CHAT, rows, None, None, RID, ctx, skip_memorize=True,
                semantic_package=package)
        assert published is True
        assert any("LEGACY_COVERAGE_DEGRADED" in r.message
                   for r in caplog.records)
        assert ctx.source_coverage == pytest.approx(
            round(100.0 * 13 / 30, 2))

    @pytest.mark.asyncio
    async def test_off_parity_xml_hard_stop(self, monkeypatch, caplog):
        """Kill-switch OFF → прежний тихий XML hard stop бит-в-бит (без
        full-window, без coverage)."""
        _flag(monkeypatch, "SUMMARY_LEGACY_FULL_WINDOW_ENABLED", False)
        _caps_hot(monkeypatch, max_messages=100, max_chars=5000)
        rows = _rows(688)
        gen = _legacy_gen(monkeypatch, rows)
        ctx = RunContext(run_id=RID, chat_id=CHAT, mode="off")
        with caplog.at_level(logging.INFO):
            published = await gen._run_legacy_pipeline(
                CHAT, rows, None, None, RID, ctx, skip_memorize=True)
        assert published is True
        assert not any("LEGACY_FULL_WINDOW" in r.message
                       for r in caplog.records)
        assert ctx.source_coverage is None
        content = gen.llm.messages[1]["content"]
        assert "<chat_history>" in content
        # Обрезка по капу сообщений видна (прод-поведение 307/688).
        assert content.count("<message ") <= 100

    @pytest.mark.asyncio
    async def test_max_summary_parts_not_input_cap(self, monkeypatch):
        """§58-guard: MAX_SUMMARY_PARTS — только выходные части; input
        coverage от него НЕ зависит (байт-идентичный контент окна)."""
        _caps_hot(monkeypatch, max_messages=100, max_chars=5000)
        rows = _rows(200)
        seen = []
        for parts in (1, 4):
            gen = _legacy_gen(monkeypatch, rows)
            ctx = RunContext(run_id=RID, chat_id=CHAT, mode="off")
            await gen._run_legacy_pipeline(
                CHAT, rows, None, None, RID, ctx, max_parts=parts,
                skip_memorize=True)
            seen.append((ctx.source_considered, ctx.source_coverage,
                         gen.llm.messages[1]["content"]))
        assert seen[0][0] == seen[1][0] == 200
        assert seen[0][1] == seen[1][1] == 100.0
        assert seen[0][2] == seen[1][2]           # контент окна идентичен

    @pytest.mark.asyncio
    async def test_prefilter_not_restored(self, monkeypatch):
        """R4-D-038: source normalization не меняет смысл; алгоритмическая
        предфильтрация ASAP-2.1 не восстановлена — все сообщения окна
        представлены (considered == total), потерь «по важности» нет."""
        from services.summary_l1_clusterizer import pack_l1_input
        rows = _rows(50)
        pack = pack_l1_input(rows, CHAT, token_limit=1_000_000)
        assert len(pack.payload) == 50           # ничего не выброшено
        assert pack.truncated is False
        _caps_hot(monkeypatch, max_messages=10, max_chars=1000)
        package = {
            "schema_version": 2, "status": "ok",
            "threads": [{"thread_id": "thread_001", "name": "т",
                         "description": "",
                         "chronology": [{"message_id": 5000 + i,
                                         "timestamp": i,
                                         "topic_ids": ["thread_001"]}
                                        for i in range(1, 51)],
                         "evidence_ids": [], "facts": [], "fragments": []}],
            "unassigned_message_ids": [], "service": {}, "budget": {}}
        coverage = compute_package_coverage(package, 50)
        assert coverage["source_messages_considered"] == 50
        assert coverage["coverage_percent"] == 100.0

    def test_flat_fits_and_package_content_units(self):
        xml_small = ("<chat_history>\n" + "\n".join(
            f'<message id="{i}" timestamp="" author="в" reply_to_id="" '
            f'type="text">т</message>' for i in range(3))
            + "\n</chat_history>")
        assert flat_fits(xml_small, 3) is True
        assert flat_fits(xml_small, 4) is False
        assert flat_fits("<chat_history/>", 0) is True
        package = {
            "schema_version": 2, "status": "ok",
            "threads": [{"thread_id": "thread_001", "name": "т",
                         "description": "д",
                         "chronology": [{"message_id": 7, "timestamp": 1,
                                         "topic_ids": ["thread_001"]}],
                         "evidence_ids": [],
                         "facts": [{"text": "ф",
                                    "evidence_message_ids": [7]}],
                         "fragments": [_frag(7, 1, "в", "текст")]}],
            "unassigned_message_ids": [8], "service": {}, "budget": {}}
        coverage = compute_package_coverage(package, 8)
        assert coverage["source_messages_considered"] == 2   # 7 и 8
        content = build_legacy_package_content(package)
        assert '"unassigned_message_ids":[8]' in content
        assert '"message_id":7' in content
        assert "service" not in content
        assert "budget" not in content
