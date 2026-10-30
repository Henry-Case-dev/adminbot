"""EVOL §5 (W5) — фактчек: доказательность + фирменный «Критический разнос».

Восемь фиксированных offline-сценариев §5.4 (`plans/current_task.md`
1091–1141): моковый анализатор/источники/Writer, без сети, без живых
отправок в Telegram и без ручной оценки «достаточно резко».

Доказывается пользовательский контракт:

1. ``refuted`` → фактологически обоснованная критическая секция, в payload
   публичной Writer-фазы действует разрешённый style layer;
2. ``partially_true`` (mixed) → резкая критика только опровергнутых/
   недоказанных частей, подтверждённые остаются подтверждёнными;
3. ``supported`` → нет выдуманного опровержения, секция не публикуется;
4. ``insufficient_evidence``/``source_missing`` → нет имитации доказанного
   разгрома, границы проверки названы честно;
5. Core/Expression активного чата → ровно одно попадание в ФАКТИЧЕСКИЙ
   публичный payload; наследование/scope/владелец источника соблюдены;
6. настройка секции OFF → факты и источники остаются, секции нет, мастер-
   тумблер модуля не меняется;
7. render/HTML/чанкинг/цитаты → ссылка привязана к своему утверждению,
   секция не ломает разметку и не создаёт фантомных источников;
8. legacy/temporal/two-call/fallback маршруты → нет потери Core и
   противоречий между жанровыми инструкциями.

TEST-LIFECYCLE: CONTRACT owner=EVOL-§5 (фактчек: доказательность + разнос)
"""
from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_prompts as fp
from services import factcheck_renderer as fr
from services import prompt_composer as pc
from services import prompt_registry as pr
from services import temporal_factcheck as tf
from services.factcheck_service import (
    CRITIQUE_SECTION_KEY,
    FactCheckService,
    critique_section_default,
    resolve_critique_section,
)

CHAT_ID = -100555
TARGET_TG = 5500
TRIGGER_TG = 5501

CLAIM = "В Telegram добавят ИИ-агентов через API"
URL_PRIMARY = "https://news.example.org/agents"
URL_EXTRA = "https://docs.example.org/api"

HEADING = fp.FACTCHECK_CRITIQUE_HEADING
DIRECTIVE = fp.FACTCHECK_CRITIQUE_DIRECTIVE


# ── Фейки (без сети/БД/LLM) ─────────────────────────────────────────────────

class FakeDB:
    """Минимальный DB-фейк для ``tf.build_envelope`` (origin-строка)."""

    def __init__(self, text: str = CLAIM):
        self._row = {
            "text": text, "caption": None, "origin_type": None,
            "origin_sent_at": None, "sent_at": 1792200000,
            "current_revision": None, "content_hash": None,
            "origin_sender_user_id": None, "origin_chat_id": None,
            "origin_display_name": None, "author_name": None,
            "forward_source": None,
        }

    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(self._row)

    async def get_media_assets_for_message(self, chat_id, tg):
        return []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        return dict(self._row)

    async def get_smart_messages_reply_to(self, *a, **kw):
        return []


class FakeBot:
    id = 861000777

    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 900 + len(self.sent)})()

    async def send_chat_action(self, chat_id, action, **kw):
        return True


class StepLLM:
    """LLM-фейк: JSON на машинных стадиях, текст — на вербализации."""

    def __init__(self, *, verdict=None, text="Проверено.", analyst=None,
                 validator=None):
        self.verdict = verdict or {"factual_verdict": "insufficient_evidence",
                                   "temporal_status": "unknown"}
        self.validator = validator or {"agree": True}
        self.analyst = analyst
        self.text = text
        self.calls: list[dict] = []

    async def generate(self, messages, **kw):
        step = kw.get("step")
        self.calls.append({"step": step, "messages": messages})
        if step == "temporal_verdict":
            return json.dumps(self.verdict, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps(self.validator, ensure_ascii=False)
        if step == "stage1" and self.analyst is not None:
            return json.dumps(self.analyst, ensure_ascii=False)
        return self.text

    def system_of(self, step: str) -> str:
        for call in self.calls:
            if call["step"] == step:
                return call["messages"][0]["content"]
        raise AssertionError(f"нет вызова стадии {step}")


class Agg:
    def __init__(self, text="Выдача поиска про агентов Telegram\n" + URL_PRIMARY):
        self.text = text

    async def search(self, query, max_symbols):
        return self.text


def _evidence_map(*refs):
    return fsp.EvidenceMap(
        refs=tuple(fsp.EvidenceRef(evidence_id=eid, url=url, support=sup)
                   for eid, url, sup in refs),
        allowlist=tuple(eid for eid, _u, _s in refs))


def _outcome(*refs) -> fsp.RetrievalOutcome:
    """Retrieval-выдача единого контура v2 (один поиск на прогон)."""
    ev = _evidence_map(*refs) if refs else None
    return fsp.RetrievalOutcome(
        evidence_map=ev,
        search_text=("Материалы по тезису\n" + "\n".join(r[1] for r in refs)
                     if refs else ""),
        queries_attempted=1, queries_used=1,
        refs_collected=len(refs or ()), fetch_errors=0,
        budget_exhausted=False)


async def _run_temporal(llm: StepLLM, *, refs=(("ev-1", URL_PRIMARY,
                                                "подтверждает"),
                                               ("ev-2", URL_EXTRA,
                                                "уточняет")),
                        claim: str = CLAIM):
    """Реальный temporal-маршрут: envelope → вердикт → вербализация."""
    env, _reject = await tf.build_envelope(
        FakeDB(claim),
        tf.InputRef(kind="reply", chat_id=CHAT_ID,
                    target_tg_message_id=TARGET_TG,
                    trigger_tg_message_id=TRIGGER_TG))
    service = FactCheckService(aggregator=Agg(), llm=llm)
    run = await service.check_claim_envelope(env, retrieval=_outcome(*refs))
    return run


def _verdict_from_run(run) -> orch.CheckedVerdict:
    """Тот же egress-переход, что делает оркестратор (W3 → W5)."""
    refs = tuple(
        orch.EvidenceRef(evidence_id=str(r.get("evidence_id") or ""),
                         url=r.get("url"),
                         support=str(r.get("support") or ""),
                         source_kind=str(r.get("source_kind") or "secondary"))
        for r in (run.evidence_rows or ()))
    return orch.CheckedVerdict(
        verdict_text=run.verdict_text or "Вердикт.",
        route="envelope_temporal",
        factual_verdict=run.verdict.factual_verdict,
        temporal_status=run.verdict.temporal_status,
        evaluated_period=run.verdict.evaluated_period,
        uncertainty=run.verdict.uncertainty,
        evidence=orch.EvidenceMap(refs=refs,
                                 allowlist=tuple(r.evidence_id
                                                 for r in refs)),
        reason_code=run.verdict.reason,
        fallback_used=run.fallback_used,
        evidence_refs=tuple(run.verdict.evidence_refs or ()),
        parts=tuple(run.verdict.parts or ()))


def _publish(verdict: orch.CheckedVerdict, *, allow_critique: bool = True,
             notice: str = "") -> str:
    presentation = orch.build_presentation(verdict, notice=notice)
    return fr.render_factcheck(presentation, verdict,
                               allow_critique=allow_critique).text


def _two_call_service(analyst: dict, writer_text: str):
    """Two-call маршрут сервиса (Stage-1 JSON + Writer) без сети."""
    llm = MagicMock()
    llm.generate = AsyncMock(
        side_effect=[json.dumps(analyst, ensure_ascii=False), writer_text])
    return FactCheckService(Agg(), llm), llm


def _analyst(*findings: tuple[str, str], verdict: str = "Разбор готов."):
    return {
        "claim": CLAIM,
        "findings": [
            {"assertion": assertion, "status": status,
             "human_time": "вчера", "author": "автор", "evidence": evidence}
            for assertion, status, evidence in findings],
        "verdict": verdict,
    }


def _tags_balanced(chunk: str) -> bool:
    for tag in ("b", "i", "a"):
        if chunk.count(f"<{tag}") != chunk.count(f"</{tag}>"):
            return False
    return True


# ═══ 1. false → обоснованный разнос + разрешённый style layer ═══════════════

@pytest.mark.asyncio
async def test_case1_refuted_publishes_grounded_critique_with_style_layer(
        monkeypatch):
    writer = (
        "Тезис про агентов не подтверждается: официального анонса нет.\n\n"
        "Проверка по существу: в выдаче только пересказы, дат и цифр нет.\n\n"
        + HEADING + ": автор опять выдал желаемое за анонс, да ещё и с "
        "придуманным сроком - ни одного подтверждения этому нет.")
    llm = StepLLM(verdict={"factual_verdict": "refuted",
                           "temporal_status": "unknown",
                           "parts": [{"part_id": "p1",
                                      "text": "агентов добавят через API",
                                      "factual_verdict": "refuted",
                                      "evidence_refs": ["ev-1"]}]},
                  text=writer)
    # активный style layer владельца (Expression) — разрешённая грубость чата
    expression = "<Expression_Settings>\nMAT: разрешён\n</Expression_Settings>"
    monkeypatched = []

    async def fake_expression(chat_id):
        monkeypatched.append(chat_id)
        return pc.ExpressionSettings(text=expression, enabled=True,
                                     source="chat")

    monkeypatch.setattr(pc, "resolve_expression_settings", fake_expression)
    run = await _run_temporal(llm)

    payload = llm.system_of("temporal_verbalize")
    # директива владельца — дословно в ФАКТИЧЕСКОМ payload публичной фазы
    assert DIRECTIVE in payload
    assert HEADING + ":" in payload
    # разрешённый style layer того же чата дошёл до Writer (ровно один раз)
    assert payload.count("MAT: разрешён") == 1
    assert monkeypatched == [CHAT_ID]

    verdict = _verdict_from_run(run)
    assert verdict.factual_verdict == "refuted"
    markup = _publish(verdict)
    visible = fr.visible_text(markup)
    assert "<b>" + HEADING + "</b>" in markup          # отдельный блок
    assert HEADING in visible
    # критика опирается на установленную ошибку прогона, а не на новую «правду»
    assert "придуманным сроком" in visible
    # egress-guard не нейтрализует настроенный характер
    guarded, _v = orch._apply_delivery_guard(
        orch.build_presentation(verdict), verdict)
    assert HEADING in guarded.text and "придуманным сроком" in guarded.text


# ═══ 2. partially_true → критика только опровергнутых частей ════════════════

@pytest.mark.asyncio
async def test_case2_partial_critique_only_refuted_parts_confirmed_stay():
    writer = (
        "Часть про API подтверждается, часть про сроки - нет.\n\n"
        + HEADING + ": срок «со дня на день» - это чистая выдумка автора.")
    llm = StepLLM(verdict={"factual_verdict": "mixed",
                           "temporal_status": "unknown",
                           "parts": [
                               {"part_id": "p1",
                                "text": "агентов подключат через API",
                                "factual_verdict": "supported",
                                "evidence_refs": ["ev-1"]},
                               {"part_id": "p2",
                                "text": "запуск со дня на день",
                                "factual_verdict": "refuted",
                                "evidence_refs": ["ev-2"]}]},
                  text=writer)
    run = await _run_temporal(llm)
    payload = llm.system_of("temporal_verbalize")
    assert DIRECTIVE in payload
    # Writer видит структуру: подтверждённая и опровергнутая части различимы
    user_payload = [c["messages"][1]["content"] for c in llm.calls
                    if c["step"] == "temporal_verbalize"][0]
    assert "агентов подключат через API" in user_payload
    assert "запуск со дня на день" in user_payload

    verdict = _verdict_from_run(run)
    markup = _publish(verdict)
    visible = fr.visible_text(markup)
    assert "<b>Подтверждается частично</b>" in markup
    assert HEADING in visible
    # подтверждённая часть осталась подтверждённой и не переписана критикой
    assert "агентов подключат через API — подтверждается" in visible
    assert "запуск со дня на день — не подтверждается" in visible
    assert visible.index(HEADING) < visible.index("По утверждениям:")


# ═══ 3. true → нет выдуманного опровержения ═════════════════════════════════

@pytest.mark.asyncio
async def test_case3_supported_never_invents_refutation():
    writer = ("Тезис подтверждается: официальный анонс есть.\n\n"
              + HEADING + ": автор молодец, разъёбывать нечего.")
    llm = StepLLM(verdict={"factual_verdict": "supported",
                           "temporal_status": "unknown",
                           "parts": [{"part_id": "p1",
                                      "text": "агентов подключат через API",
                                      "factual_verdict": "supported",
                                      "evidence_refs": ["ev-1"]}]},
                  text=writer)
    run = await _run_temporal(llm)
    # инструкции раздела в payload нет вовсе: выдуманный разгром запрещён
    assert DIRECTIVE not in llm.system_of("temporal_verbalize")

    verdict = _verdict_from_run(run)
    assert verdict.factual_verdict == "supported"
    markup = _publish(verdict)
    visible = fr.visible_text(markup)
    assert "<b>Подтверждается</b>" in markup
    assert HEADING not in visible
    assert "разъёбывать" not in visible
    # факты и источники на месте
    assert "официальный анонс есть" in visible
    assert "news.example.org" in visible


# ═══ 4. insufficient_evidence / source_missing → без ложного разгрома ══════

@pytest.mark.asyncio
@pytest.mark.parametrize("verdict_json,refs,expected_headline", [
    ({"factual_verdict": "insufficient_evidence",
      "temporal_status": "unknown"},
     (("ev-1", URL_PRIMARY, "выдержка без опоры на тезис"),),
     "Недостаточно данных для проверки"),
    ({"factual_verdict": "insufficient_evidence",
      "temporal_status": "unknown",
      "reason": "source_missing"},
     (),
     "Проверка не завершена: материалы не удалось разобрать"),
])
async def test_case4_incomplete_data_no_fake_demolition(verdict_json, refs,
                                                        expected_headline):
    writer = ("Проверить тезис по источникам не удалось.\n\n"
              + HEADING + ": автор всё равно несёт чушь и всё выдумал.")
    llm = StepLLM(verdict=dict(verdict_json), text=writer)
    run = await _run_temporal(llm, refs=refs)
    assert DIRECTIVE not in llm.system_of("temporal_verbalize")

    verdict = _verdict_from_run(run)
    markup = _publish(verdict)
    visible = fr.visible_text(markup)
    assert expected_headline in visible
    assert HEADING not in visible
    assert "выдумал" not in visible
    # граница проверки названа, а не выдана за доказанный разгром
    assert ("ограничение" in visible.lower()
            or "недостаточно данных" in visible.lower()
            or "не удалось" in visible.lower())


# ═══ 5. Core/Expression: одно попадание в фактический payload ═══════════════

@pytest.mark.asyncio
async def test_case5_core_expression_single_inclusion_and_scope(monkeypatch):
    core_text = "ЯДРО-МАРКЕР: говори жёстко, но по делу."
    expr_text = "ЭКСПРЕССИЯ-МАРКЕР: ирония включена."
    seen: list[int] = []

    async def fake_core(chat_id):
        seen.append(int(chat_id))
        return pc.CoreRef(text=core_text, enabled=True, source="chat")

    async def fake_expression(chat_id):
        seen.append(int(chat_id))
        return pc.ExpressionSettings(text=expr_text, enabled=True,
                                     source="chat")

    monkeypatch.setattr(pc, "resolve_core_ref", fake_core)
    monkeypatch.setattr(pc, "resolve_expression_settings", fake_expression)

    llm = StepLLM(verdict={"factual_verdict": "refuted",
                           "temporal_status": "unknown"},
                  text="Тезис не подтверждается.\n\n" + HEADING
                       + ": цифры взяты с потолка.")
    await _run_temporal(llm)
    payload = llm.system_of("temporal_verbalize")
    assert payload.count(core_text) == 1        # ни одной второй копии Core
    assert payload.count(expr_text) == 1
    assert set(seen) == {CHAT_ID}               # scope: чат прогона

    # наследование настройки: chat-override → global → заводской дефолт
    async def fake_sourced(chat_id, key, default=None):
        assert key == CRITIQUE_SECTION_KEY
        return (False, "chat") if int(chat_id) == 777 else (True, "global")

    monkeypatch.setattr("services.chat_params.get_chat_param_sourced",
                        fake_sourced)
    assert await resolve_critique_section(777) == (False, "chat")
    assert await resolve_critique_section(555) == (True, "global")
    # владелец источника — существующий механизм настроек, не второй ключ
    assert CRITIQUE_SECTION_KEY != "flags.factcheck_enabled"
    assert critique_section_default() is True   # default ON внутри фактчека


# ═══ 6. настройка OFF → факты/источники остаются, секции нет ════════════════

@pytest.mark.asyncio
async def test_case6_section_off_keeps_facts_sources_and_master_toggle(
        monkeypatch):
    writer = ("Тезис не подтверждается: анонса нет.\n\n"
              "Проверка по существу: только пересказы.\n\n"
              + HEADING + ": автор нафантазировал срок.")
    llm = StepLLM(verdict={"factual_verdict": "refuted",
                           "temporal_status": "unknown"},
                  text=writer)

    async def off_sourced(chat_id, key, default=None):
        return (False, "chat")

    monkeypatch.setattr("services.chat_params.get_chat_param_sourced",
                        off_sourced)
    run = await _run_temporal(llm)
    assert DIRECTIVE not in llm.system_of("temporal_verbalize")

    verdict = _verdict_from_run(run)
    # оркестратор снимает раздел ДО презентации (настройка OFF)
    stripped = await orch._apply_critique_section_setting(CHAT_ID, verdict)
    assert HEADING not in stripped.verdict_text
    assert "Тезис не подтверждается: анонса нет." in stripped.verdict_text
    markup = _publish(stripped)
    visible = fr.visible_text(markup)
    assert HEADING not in visible
    assert "Тезис не подтверждается: анонса нет." in visible
    assert "Проверка по существу: только пересказы." in visible
    assert "news.example.org" in visible        # источники остаются
    assert "<b>Не подтверждается</b>" in markup
    # мастер-тумблер модуля не тронут этой осью
    assert CRITIQUE_SECTION_KEY != "flags.factcheck_enabled"
    assert bool(getattr(settings, "FACTCHECK_ENABLED", True)) is True


# ═══ 7. render/HTML/чанкинг/цитаты ══════════════════════════════════════════

@pytest.mark.asyncio
async def test_case7_render_chunking_and_citation_binding(monkeypatch):
    # pre-split entity-safe: каждая часть ≤ лимита (лимит занижен сценарием)
    monkeypatch.setattr(fr, "_CHUNK_LIMIT", 900)
    long_part = ("Материалы по тезису подтверждают только подключение через "
                 "API, но не сроки запуска. ") * 40
    writer = ("Тезис подтверждается частично.\n\n"
              "Проверка по существу: " + long_part + "\n\n"
              + HEADING + ": срок «со дня на день» - выдумка автора, "
              "официального анонса нет.")
    verdict = orch.CheckedVerdict(
        verdict_text=writer, route="envelope_temporal",
        factual_verdict="mixed",
        evidence=orch.EvidenceMap(
            refs=(orch.EvidenceRef(evidence_id="ev-1", url=URL_PRIMARY,
                                   support="подключение через API"),
                  orch.EvidenceRef(evidence_id="ev-2", url=URL_EXTRA,
                                   support="документация API")),
            allowlist=("ev-1", "ev-2")),
        evidence_refs=("ev-1",),
        parts=({"part_id": "p1", "text": "подключение через API",
                "factual_verdict": "supported", "evidence_refs": ["ev-1"]},))
    markup = _publish(verdict)
    # секция отдельным блоком и ровно один раз
    assert markup.count("<b>" + HEADING + "</b>") == 1
    # ссылка привязана к своему утверждению (в той же строке разбора)
    bound_line = [ln for ln in markup.splitlines()
                  if "подключение через API — подтверждается" in ln]
    assert bound_line and URL_PRIMARY in bound_line[0]
    # фантомных источников нет: все href — только из EvidenceMap прогона
    hrefs = set(re.findall(r'href="([^"]+)"', markup))
    assert hrefs <= {URL_PRIMARY, URL_EXTRA}
    # чанкинг: каждая часть — самостоятельный валидный HTML, секция не рвётся
    chunks = fr.split_entity_safe(markup, 900)
    assert len(chunks) > 1
    assert all(_tags_balanced(chunk) for chunk in chunks)
    assert "".join(chunks).count(HEADING) == 1
    # доставка через СУЩЕСТВУЮЩИЙ send_chunked_reply: >1 сообщения, без ошибок
    bot = FakeBot()
    presentation = fr.render_factcheck(
        orch.build_presentation(verdict), verdict)
    await fr.deliver_factcheck(bot, CHAT_ID, presentation,
                               reply_to_message_id=TARGET_TG)
    assert len(bot.sent) > 1
    joined = "\n".join(m["text"] for m in bot.sent)
    assert HEADING in joined and URL_PRIMARY in joined
    assert all(_tags_balanced(m["text"]) for m in bot.sent)
    # reply — только у первой части
    assert bot.sent[0].get("reply_to_message_id") == TARGET_TG
    assert all(not m.get("reply_to_message_id") for m in bot.sent[1:])


# ═══ 8. legacy/two-call/fallback: Core не теряется, жанр не противоречит ═══

@pytest.mark.system2
@pytest.mark.asyncio
async def test_case8_routes_keep_core_and_consistent_genre(monkeypatch):
    core_text = "ЯДРО-МАРКЕР: характер не теряется на маршруте."

    async def fake_core(chat_id):
        return pc.CoreRef(text=core_text, enabled=True, source="chat")

    async def fake_expression(chat_id):
        return pc.ExpressionSettings(text="", enabled=False)

    monkeypatch.setattr(pc, "resolve_core_ref", fake_core)
    monkeypatch.setattr(pc, "resolve_expression_settings", fake_expression)

    analyst = _analyst(("агентов подключат через API", "false",
                        "официального анонса нет"))
    writer = ("Тезис не подтверждается.\n\n" + HEADING
              + ": анонса нет, автор нафантазировал.")
    # (а) two-call: Core один раз, директива один раз
    service, llm = _two_call_service(analyst, writer)
    text = await service.check_claim(CLAIM, chat_id=CHAT_ID)
    system = llm.generate.await_args_list[1].args[0][0]["content"]
    assert system.count(core_text) == 1
    assert system.count(DIRECTIVE) == 1
    assert text  # публичный текст Writer'а получен

    # (б) legacy one-call (kill-switch): тот же контур речи. Патч — на классе
    # Settings через monkeypatch: instance-атрибут пережил бы тест и включил
    # two-call в следующих тестах (утечка глобального состояния).
    from config.settings import Settings as _Settings
    monkeypatch.setattr(_Settings, "SYSTEM2_FACTCHECK_ENABLED", False)
    single, single_llm = _two_call_service(analyst, writer)
    await single.check_claim(CLAIM, chat_id=CHAT_ID)
    single_system = single_llm.generate.await_args_list[0].args[0][0]["content"]
    assert single_system.count(core_text) == 1
    assert single_system.count(DIRECTIVE) == 1
    # жанровый канон остаётся на месте (нет подмены второго сборщика)
    assert "третейский судья" in single_system

    # (в) fallback-текст без LLM: никакого «разгрома» и потери оговорок
    env, _reject = await tf.build_envelope(
        FakeDB(CLAIM),
        tf.InputRef(kind="reply", chat_id=CHAT_ID,
                    target_tg_message_id=TARGET_TG,
                    trigger_tg_message_id=TRIGGER_TG))
    fallback_verdict = tf.TemporalVerdict(
        factual_verdict="insufficient_evidence", temporal_status="unknown",
        evaluated_period={}, assessment_mode="contextual",
        as_of=1792200000, parts=(), uncertainty={})
    fallback_text = FactCheckService._temporal_fallback_text(
        env, fallback_verdict, retrieval_state="budget_exhausted")
    assert HEADING not in fallback_text
    assert "лимит времени" in fallback_text

    # (г) секция не требует того, что запрещает жанровый канон
    block = fp.build_critique_section_block(fp.CRITIQUE_POLICY_ALLOWED)
    for forbidden in ("**", "###", "| ---"):
        assert forbidden not in block
    assert "никаких новых фактов" in block.lower()
    # (д) директива зарегистрирована в едином EVOL-реестре и опечатана
    spec = pr.block(fp.FACTCHECK_CRITIQUE_BLOCK_ID)
    assert spec is not None and spec.code_source.endswith(
        "FACTCHECK_CRITIQUE_DIRECTIVE")
    assert pr.factory_text(spec.block_id) == DIRECTIVE
    assert pr.seal_integrity() == {}
    assert pr.factory_revision(spec.block_id).startswith(pr.FACTORY_PREFIX)


# ═══ 9. каталог: обе ручки владельца существуют (POST ≠ 422) ═══════════════
# REVIEW-FIX B1: `flags.factcheck_critique_section_enabled` и
# `prompts.factcheck_critique_directive` обязаны быть в каталоге — иначе
# POST /api/config отвечает 422 «неизвестный ключ», а вкладка «Фактчек»
# (рендерится только из каталога) не показывает ни тумблер раздела, ни
# редактор директивы, то есть владелец физически не может их изменить.

def test_case9_catalog_exposes_both_owner_controls():
    from services import config_cache
    from services import param_catalog as pcat

    # (а) тумблер раздела: per-chat bool в СВОЕЙ группе подачи ответа
    flag = pcat.get_by_pg_key(CRITIQUE_SECTION_KEY)
    assert flag is not None, ("флага нет в каталоге → POST /api/config "
                              "вернёт 422 «неизвестный ключ»")
    assert flag.category == pcat.CATEGORY_FLAGS and flag.type == "bool"
    assert flag.per_chat is True and flag.hidden is False
    assert flag.group == "flags_factcheck_delivery"
    assert pcat.group_tab(flag.group) == pcat.TAB_MOD_FACTCHECK
    # это НЕ второй мастер-тумблер модуля: мастер остаётся единственным
    assert CRITIQUE_SECTION_KEY != "flags.factcheck_enabled"
    assert pcat.get_by_pg_key("flags.factcheck_enabled") is not None
    # default ON зеркалится в /api/config (иначе в UI был бы null, не «вкл»)
    assert config_cache._PG_ONLY_BOOL_DEFAULTS[CRITIQUE_SECTION_KEY] is True

    # (б) директива: PG-ключ привязан к реестровому блоку, группа фактчека
    spec = pr.block(fp.FACTCHECK_CRITIQUE_BLOCK_ID)
    assert spec is not None
    assert spec.pg_key == "prompts.factcheck_critique_directive"
    entry = pcat.get_by_pg_key(spec.pg_key)
    assert entry is not None, "промпт-ключа нет в каталоге → 422 в POST"
    assert entry.category == pcat.CATEGORY_PROMPTS and entry.type == "str"
    assert entry.per_chat is True
    assert entry.code_source == \
        "services.factcheck_prompts.FACTCHECK_CRITIQUE_DIRECTIVE"
    assert pcat.group_tab(entry.group) == pcat.TAB_PROMPTS
    # блок объявлен ровно один раз (нет второго объявления/скрытой копии)
    assert pr.unregistered_catalog_keys() == ()
    assert [b.block_id for b in pr.all_blocks()].count(
        spec.block_id) == 1


# ═══ 10. правка владельца директивы реально доходит до Writer ══════════════
# REVIEW-FIX B2: реестр читался только при непустом `spec.pg_key`; без него
# `resolve_critique_directive` всегда возвращал литерал, то есть правка
# владельца не могла повлиять на ответ.

@pytest.mark.asyncio
async def test_case10_owner_directive_revision_reaches_writer_prompt(
        monkeypatch):
    from services import hot_config as hot

    spec = pr.block(fp.FACTCHECK_CRITIQUE_BLOCK_ID)
    assert spec is not None and spec.pg_key
    key = spec.pg_key

    owner_revision = "Разнеси тезис по пунктам и назови, где именно подмена."
    monkeypatch.setattr(
        hot, "get",
        lambda name, default=None: owner_revision if name == key else default)
    assert fp.resolve_critique_directive() == owner_revision

    # правка владельца доходит до ФАКТИЧЕСКОГО system-промпта Writer'а
    llm = StepLLM(verdict={"factual_verdict": "refuted",
                           "temporal_status": "unknown"},
                  text="Тезис не подтверждается.\n\n" + HEADING
                       + ": цифры взяты с потолка.")
    await _run_temporal(llm)
    payload = llm.system_of("temporal_verbalize")
    assert owner_revision in payload
    assert DIRECTIVE not in payload      # заводская редакция вытеснена правкой

    # пустое/пробельное значение → заводской литерал (пустота не обнуляет)
    monkeypatch.setattr(hot, "get",
                        lambda name, default=None: "   ")
    assert fp.resolve_critique_directive() == DIRECTIVE

    # заводской текст и печать ревизии не изменились (не подмена канона)
    assert pr.factory_text(spec.block_id) == DIRECTIVE
    assert pr.FACTORY_REVISION_SEALS[spec.block_id] == (
        "factcheck-critique-w5", pr.sha12(DIRECTIVE))
    assert pr.seal_integrity() == {}
