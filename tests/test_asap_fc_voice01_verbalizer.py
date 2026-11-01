# -*- coding: utf-8 -*-
"""ASAP-FC-VOICE-01 / A — голос фактчека, единая точка речи, адаптивная подача.

Источник: `plans/owner_inputs/2026-11-02-asap-fc-voice-01.md` (§1-4 владельца) и
`plans/features/asap-fc-voice-01/arch/verbalizer-contract.md` (§3-6 контракта).

Что доказывается (и чем это может упасть):

1. **Ревизия канона голоса** — новые байты вербализатора, печать ревизии,
   метка, ступень миграции PG и цель откатa = ровно байты прода 2.58.148
   (`42442333d77d`). Без бампа печати/ступени это падает.
2. **Исторический жанр вместо шаблона** — в каноне есть прямая полемика,
   разбор логического разрыва и контраргумент; нет навязанных секций, запрета
   списков и старого ложного входного контракта «только claim/findings/verdict».
3. **Одна точка сборки речи на четыре маршрута** — двухвызовный Stage-2,
   временной вербализатор, одиночный путь и короткая персона-реплика получают
   Core/Expression/финальный контракт из `compose_speech_system`: ровно одно
   вхождение каждого слоя, Expression действует последним, ручной склейки
   `speech_owner_block` в модуле фактчека нет.
4. **Смысловые поля аналитика** — `inference_gap`/`counterpoint` в той же
   JSON-схеме (System2 и temporal-аналитик стадии v2), обратная совместимость,
   `tone_hint` не принимается, поля доезжают до Writer'а.
5. **Renderer не диктует форму** — нет обрезки тезисов, нет обязательного
   списка «По утверждениям» и шаблонного раздела; при пустом теле проверенные
   данные публикуются fallback-списком; вердикт и валидированные ссылки целы.
6. **Expression — единственный регулятор речи** — off/occasional/frequent дают
   ровно один слой `<Expression_Settings>` и соответствующий финальный
   контракт; канон не содержит собственного правила про мат.
7. **Direct не сломан** — делегат даёт байт-паритет с модульной функцией.

ЧЕГО ЭТОТ ФАЙЛ НЕ ДОКАЗЫВАЕТ (честная граница): какую именно форму выберет
модель на живом прогоне. Здесь проверяется эффективный payload (канон + слои +
renderer-поведение), а не текст будущего ответа LLM.

TEST-LIFECYCLE: CONTRACT owner=ASAP-FC-VOICE-01/A
"""
from __future__ import annotations

import dataclasses
import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import factcheck_orchestrator as orch
from services import factcheck_prompts as fp
from services import factcheck_renderer as fr
from services import factcheck_service as fs
from services import mca_expression as ex
from services import prompt_composer as pc
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services import temporal_factcheck as tf
from services.system2_handoff import parse_factcheck_analysis, stage2_payload

CHAT_ID = -100900

#: Метки слоёв владельца: проверяем ФАКТ доставки, а не текст инструкций.
CORE_MARKER = "ЯДРО-МАРКЕР-VOICE01"
EXPR_MARKER = "<Expression_Settings>\\nМАРКЕР-ВЫРАЖЕНИЯ-VOICE01\\n</Expression_Settings>"
EXPR_MARKER = EXPR_MARKER.replace("\\n", "\n")
EXPR_OPEN = "<Expression_Settings>"

#: Слова про мат в самом каноне голоса — запрещены (регулятор один: Expression).
_MAT_WORD_RE = re.compile(r"\bмат(а|у|е|ом|ов|ами|ах)?\b", re.IGNORECASE)


# ── Общие фейки окружения ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_composer():
    pc.reset_state()
    yield
    pc.reset_state()


@pytest.fixture(autouse=True)
def _isolate_hot_cache():
    """Не оставлять живой hot-кеш после прогона (изоляция файлов).

    Сборка через `compose_speech_system` читает действующие оси реальным
    резолвером и заполняет hot-слой процесса. Без сброса следующие файлы
    видят чужие значения настроек вместо дефолтов.
    """
    from services import hot_config as hot

    hot.set_config_cache(None)
    yield
    hot.set_config_cache(None)


@pytest.fixture
def owner_layers(monkeypatch):
    """Core + Expression активного чата — те же резолверы, что у Direct."""
    async def fake_core(chat_id):
        return pc.CoreRef(text=CORE_MARKER, enabled=True, source="chat")

    async def fake_expression(chat_id):
        return pc.ExpressionSettings(text=EXPR_MARKER, enabled=True,
                                     revision="rev-voice01", mode="occasional",
                                     source="chat")

    async def no_examples(chat_id, mode):
        return ()

    monkeypatch.setattr(pc, "resolve_core_ref", fake_core)
    monkeypatch.setattr(pc, "resolve_expression_settings", fake_expression)
    monkeypatch.setattr(ex, "build_expression_examples_refs", no_examples)
    return {"core": CORE_MARKER, "expression": EXPR_MARKER}


class _CaptureVerbalize:
    """Подменяет `verbalize_validated`: сохраняет фактический payload."""

    def __init__(self):
        self.messages = None
        self.calls = 0

    async def __call__(self, _generate, messages, **kwargs):
        self.messages = messages
        self.calls += 1
        return "готовый ответ", {"attempts": 1, "retries": 0, "hits": [],
                                 "fallback": False}


def _capture(monkeypatch) -> _CaptureVerbalize:
    cap = _CaptureVerbalize()
    monkeypatch.setattr(fs, "verbalize_validated", cap)
    return cap


def _env(claim: str = "в Килякете выпало 120 мм осадков за сутки"):
    return tf.TemporalClaimEnvelope(
        claim_id="c-1", chat_id=CHAT_ID, target_tg_message_id=900,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=901, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1760900000)


def _temporal_verdict(**kwargs):
    base = dict(
        factual_verdict="refuted", temporal_status="unknown",
        evaluated_period={"from": None, "to": None, "precision": "unknown"},
        assessment_mode="contextual", as_of=1760900000,
        evidence_refs=("ev-1",), uncertainty={}, parts=(), reason=None)
    base.update(kwargs)
    return tf.TemporalVerdict(**base)


def _analyst_json(**extra):
    data = {
        "claim": "В Telegram добавят ИИ-агентов через API",
        "findings": [{"assertion": "агентов подключат через API",
                      "status": "false", "human_time": "вчера",
                      "author": "автор", "evidence": "официального анонса нет"}],
        "verdict": "официального анонса нет",
    }
    data.update(extra)
    return data


def _two_call(monkeypatch, analyst: dict):
    cap = _capture(monkeypatch)
    llm = MagicMock()
    llm.generate = AsyncMock(
        side_effect=[json.dumps(analyst, ensure_ascii=False), "ответ"])
    service = fs.FactCheckService(MagicMock(), llm, None)
    return service, cap


def _assert_single_owner_layers(system: str) -> None:
    """Ровно один Core/Expression и финальный контракт Expression последним."""
    assert system.count(CORE_MARKER) == 1, "Core продублирован"
    assert system.count(EXPR_OPEN) == 1, "Expression продублирован"
    assert system.count(EXPR_MARKER) == 1
    # порядок композера: Core раньше Expression
    assert system.index(CORE_MARKER) < system.index(EXPR_MARKER)
    # приоритет настройки чата: финальный контракт Expression — последним
    assert system.rstrip().endswith(
        ex.render_expression_final_contract("occasional"))


# ═══ 1. Ревизия канона голоса: печать, метка, миграция, откат ═══════════════

class TestVoiceCanonRevision:
    def test_seal_label_and_fingerprint(self):
        canon = fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT
        label, seal = pr.FACTORY_REVISION_SEALS["factcheck.base.verbalizer"]
        assert label == "factcheck-voice-historic-01"
        assert pr.FACTORY_REVISION_LABELS["factcheck.base.verbalizer"] == label
        assert pr.sha12(pr.factory_text("factcheck.base.verbalizer")) == seal
        assert pr.seal_integrity() == {}
        assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12
        assert canon  # непустой канон

    def test_rollback_target_is_deployed_bytes(self):
        """Цель откатa — ровно байты прода 2.58.148, а не «похожий» слепок."""
        assert pr.sha12(fp.PREV_FACTCHECK_VERBALIZER_VOICE01) == "42442333d77d"
        assert fp.PREV_FACTCHECK_VERBALIZER_VOICE01 != \
            fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT
        steps = pm.PROMPT_MIGRATIONS[
            "prompts.factcheck_verbalizer_system_prompt"]
        assert steps[0] == (fp.PREV_FACTCHECK_VERBALIZER_VOICE01,
                            fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT)
        rollback = pm.ROLLBACK_MIGRATIONS[
            "prompts.factcheck_verbalizer_system_prompt"]
        assert rollback[0] == (fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
                               fp.PREV_FACTCHECK_VERBALIZER_VOICE01)

    def test_single_placeholder_only(self):
        canon = fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT
        assert set(re.findall(r"\{(\w+)\}", canon)) == {"max_symbols"}
        assert canon.count("{max_symbols}") == 1
        assert "{max_symbols}" not in canon.replace("{max_symbols}", "5000")

    def test_analyst_semantics_revision(self):
        """Стадия, которая реально работает в System2: та же JSON + 2 поля."""
        canon = fp.FACTCHECK_ANALYST_SYSTEM_PROMPT
        assert "inference_gap" in canon and "counterpoint" in canon
        # расширение схемы применилось (якорь замены сработал)
        assert fp._ANALYST_SCHEMA_ANCHOR not in canon
        assert pr.sha12(fp.PREV_FACTCHECK_ANALYST_VOICE01) == "806d6cc6af77"
        label, seal = pr.FACTORY_REVISION_SEALS["factcheck.base.analyst"]
        assert label == "factcheck-analyst-voice01-semantics"
        assert pr.sha12(pr.factory_text("factcheck.base.analyst")) == seal
        key = "prompts.factcheck_analyst_system_prompt"
        assert pm.PROMPT_MIGRATIONS[key][0] == (
            fp.PREV_FACTCHECK_ANALYST_VOICE01, canon)
        assert pm.ROLLBACK_MIGRATIONS[key][0] == (
            canon, fp.PREV_FACTCHECK_ANALYST_VOICE01)

    def test_temporal_analyst_seal(self):
        """Схема временного аналитика (v2-envelope) — та же ревизия полей."""
        label, seal = pr.FACTORY_REVISION_SEALS["temporal.analyst"]
        assert label == "temporal-analyst-voice01-semantics"
        assert pr.sha12(pr.factory_text("temporal.analyst")) == seal

    def test_single_canon_conflicting_directives_removed(self):
        """F3: одиночный канон очищен от двух конфликтов с новым контрактом.

        1) «торопливое письмо» — навязанная небрежная орфография;
        2) «Твоя собственная логика и кругозор важнее» — приоритет внутренней
        уверенности над первоисточником (FCV-P23).
        Одиночный канон — тот же жанр (ветка откAта/legacy-фолбэк).
        """
        canon = fp.FACTCHECK_SYSTEM_PROMPT
        label, seal = pr.FACTORY_REVISION_SEALS["factcheck.base.single"]
        assert label == "factcheck-single-voice01"
        assert pr.sha12(pr.factory_text("factcheck.base.single")) == seal
        # откат — ровно байты прода 2.58.148, в них оба конфликта ещё есть
        assert pr.sha12(fp.PREV_FACTCHECK_SINGLE_VOICE01) == "d02776dec166"
        assert "торопливое письмо" in fp.PREV_FACTCHECK_SINGLE_VOICE01
        assert "кругозор важнее" in fp.PREV_FACTCHECK_SINGLE_VOICE01
        assert "торопливое письмо" not in canon
        assert "кругозор важнее" not in canon
        # доказательная дисциплина «умной фильтрации» сохранена
        assert "Категорически запрещено притягивать мусорные ссылки" in canon
        # нормативная часть канона (фазы) и общие блоки не тронуты
        assert fp.FACTCHECK_PHASE_SCOPE_CORE in canon
        assert fp.FACTCHECK_PHASE_SCOPE_CORE in fp.PREV_FACTCHECK_SINGLE_VOICE01
        assert "торопливое" not in pr.factory_text("factcheck.base.verbalizer")


class TestVoiceCanonContent:
    def test_genre_voice_restored(self):
        canon = fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT
        for marker in ("Вступай в спор", "подмену причинности",
                       "inference_gap", "counterpoint",
                       "не удалось подтвердить"):
            assert marker in canon, marker

    def test_forced_format_removed(self):
        canon = fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT
        # запрет списков из общего блока A и режимный запрет структуры
        assert "Списки с буллитами и нумерованные перечни" not in canon
        assert "РЕЖИМ CASUAL" not in canon
        assert "сплошной текст" not in canon
        assert "2-4 предложения" not in canon
        # фиксированного раздела и заголовка канон не требует
        assert "Критический разнос" not in canon
        # старый ложный входной контракт заменён честным
        assert "Опирайся исключительно на поля JSON" not in canon

    def test_canon_does_not_regulate_profanity(self):
        assert _MAT_WORD_RE.search(fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT) is None

    def test_critique_directive_without_section(self):
        block = fp.build_critique_section_block(fp.CRITIQUE_POLICY_ALLOWED)
        assert fp.FACTCHECK_CRITIQUE_DIRECTIVE in block      # слово владельца
        assert fp.FACTCHECK_CRITIQUE_HEADING not in block    # без шаблона
        assert "Отдельного обязательного раздела" in block
        assert fp.build_critique_section_block(
            fp.CRITIQUE_POLICY_FORBIDDEN) == ""
        # политика остаётся детерминированной
        assert fp.critique_policy_for_findings(
            [{"status": "false"}]) == fp.CRITIQUE_POLICY_ALLOWED
        assert fp.critique_policy_for_findings(
            [{"status": "true"}, {"status": "unverifiable"}]) == \
            fp.CRITIQUE_POLICY_FORBIDDEN


# ═══ 2. Одна точка сборки речи на все четыре маршрута ═══════════════════════

class TestSingleCompositionPoint:
    def test_no_parallel_owner_path_in_factcheck(self):
        """Ручной склейки `speech_owner_block` в фактчеке больше нет."""
        assert not hasattr(fs, "speech_owner_block")
        src = open("services/factcheck_service.py", encoding="utf-8").read()
        assert "speech_owner_block(" not in src
        # единая точка вызывается всеми публичными сборками модуля
        assert src.count("_compose_genre_speech(") >= 4

    @pytest.mark.asyncio
    async def test_two_call_stage2_uses_single_point(self, monkeypatch,
                                                     owner_layers):
        service, cap = _two_call(monkeypatch, _analyst_json())
        await service._check_claim_two_call(
            "тезис", "USER", "", "RESULTS", CHAT_ID, 1000)
        system = cap.messages[0]["content"]
        _assert_single_owner_layers(system)
        # жанровый канон первым, слои владельца после него
        assert system.index("СИСТЕМНАЯ РОЛЬ") < system.index(CORE_MARKER)
        # прежний слой `<Speech_Base>` сохранён (его давал speech_owner_block)
        assert "<Speech_Base>" in system
        # доставлена АКТИВНАЯ редакция ключа вербализатора, не старая
        assert "Вступай в спор" in system

    @pytest.mark.asyncio
    async def test_temporal_verbalizer_uses_single_point(self, monkeypatch,
                                                        owner_layers):
        cap = _capture(monkeypatch)
        service = fs.FactCheckService(None, None, None)
        await service._temporal_verbalize(_env(), _temporal_verdict(), False,
                                         None)
        system = cap.messages[0]["content"]
        _assert_single_owner_layers(system)
        assert "<Speech_Base>" in system
        # envelope-маршрут (единственный активный в v2) читает ТОТ ЖЕ ключ
        # `prompts.factcheck_verbalizer_system_prompt` и получает новые байты
        assert "Вступай в спор" in system

    @pytest.mark.asyncio
    async def test_modes_off_returns_previous_factory_revision(self,
                                                              monkeypatch,
                                                              owner_layers):
        """§6 контракта: OFF умных режимов → прежняя заводская редакция."""
        monkeypatch.setattr(Settings, "SMART_VERBALIZER_MODES_ENABLED", False)
        cap = _capture(monkeypatch)
        service = fs.FactCheckService(None, None, None)
        await service._temporal_verbalize(_env(), _temporal_verdict(), False,
                                         None)
        system = cap.messages[0]["content"]
        # байты прода 2.58.148 (прежний канон), а не новый голос
        assert "Опирайся исключительно на поля JSON" in system
        assert "Вступай в спор" not in system

    @pytest.mark.asyncio
    async def test_temporal_verbalizer_keeps_speech_base_layer(self, monkeypatch,
                                                               owner_layers):
        """`<Speech_Base>` — отдельный слой манеры/длины/достоверности.

        До правки его добавлял `speech_owner_block`; теперь — единая точка
        сборки, но слой сохранён и присутствует ровно один раз.
        """
        cap = _capture(monkeypatch)
        service = fs.FactCheckService(None, None, None)
        await service._temporal_verbalize(_env(), _temporal_verdict(), False,
                                         None)
        system = cap.messages[0]["content"]
        _assert_single_owner_layers(system)
        assert system.count("<Speech_Base>") == 1
        assert system.count("</Speech_Base>") == 1

    @pytest.mark.asyncio
    async def test_single_route_uses_single_point(self, monkeypatch,
                                                  owner_layers):
        monkeypatch.setattr(Settings, "SYSTEM2_FACTCHECK_ENABLED", False)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="ответ")
        service = fs.FactCheckService(MagicMock(), llm, None)
        await service._check_claim_pipeline("тезис", chat_id=CHAT_ID,
                                           search_results="выдача")
        system = llm.generate.await_args_list[0].args[0][0]["content"]
        _assert_single_owner_layers(system)
        # одиночный канон (свой ключ) на месте: маршрут не потерял жанр
        assert "третейский судья" in system

    @pytest.mark.asyncio
    async def test_short_reply_uses_single_point(self, monkeypatch,
                                                 owner_layers):
        service = MagicMock()
        service.llm.generate = AsyncMock(return_value="какой именно тезис?")
        await orch.persona_short_reply(
            service, CHAT_ID,
            instruction="ответь одной короткой репликой",
            situation="два спора в контексте",
            fallback_phrases=("уточни",))
        system = service.llm.generate.await_args_list[0].args[0][0]["content"]
        _assert_single_owner_layers(system)
        assert system.index("ответь одной короткой репликой") < \
            system.index(CORE_MARKER)

    @pytest.mark.asyncio
    async def test_manifest_names_every_skipped_layer(self, monkeypatch):
        """Пропуск слоя не бывает неназванным (инвариант §6 контракта)."""
        system, manifest = await pc.compose_speech_system(
            chat_id=CHAT_ID, writer="factcheck_verbalizer",
            base_prompt="КАНОН", base_source="code",
            include_mode_block=False, identity_text="",
            identity_skipped="duplicate_of_persona",
            plan_skip="no_l1_plan_in_genre",
            humor_skip="genre_argued_analysis", include_speech_base=True)
        assert manifest is not None
        reasons = {t.layer: t.skip_reason for t in manifest.layers
                   if not t.rendered}
        assert reasons[pc.LAYER_IDENTITY] == "duplicate_of_persona"
        assert reasons[pc.LAYER_RESPONSE_PLAN] == "no_l1_plan_in_genre"
        assert reasons[pc.LAYER_HUMOR_CRAFT] == "genre_argued_analysis"
        for trace in manifest.layers:
            assert trace.skip_reason in pc.SKIP_REASONS, trace
            assert pc.skip_reason_label(trace.skip_reason) or not trace.skip_reason
        # режимного блока нет: он задавал чужую длину и запрет структуры
        assert "РЕЖИМ" not in system


# ═══ 3. Смысловые поля аналитика: та же JSON-стадия, обратная совместимость ═

class TestAnalystSemanticFields:
    def test_system2_parser_accepts_and_keeps_fields(self):
        parsed = parse_factcheck_analysis(json.dumps(_analyst_json(
            inference_gap="из «нет анонса» не следует «агентов не будет»",
            counterpoint="API мог быть подключен без публичного анонса")))
        assert parsed["inference_gap"].startswith("из «нет анонса»")
        assert parsed["counterpoint"].startswith("API мог быть")
        # до Writer'а едут те же поля, служебный response_mode — нет
        payload = stage2_payload(parsed)
        assert "inference_gap" in payload and "response_mode" not in payload

    def test_backward_compatible_without_fields(self):
        parsed = parse_factcheck_analysis(json.dumps(_analyst_json()))
        assert "inference_gap" not in parsed
        assert "counterpoint" not in parsed
        # мёртвый tone_hint больше не принимается
        parsed2 = parse_factcheck_analysis(
            json.dumps(_analyst_json(tone_hint="злее")))
        assert "tone_hint" not in parsed2

    def test_system_ids_rejected_in_semantic_fields(self):
        parsed = parse_factcheck_analysis(json.dumps(_analyst_json(
            inference_gap="см. fact:42")))
        assert "inference_gap" not in parsed

    def test_temporal_analyst_schema_has_fields(self):
        assert "inference_gap" in tf.TEMPORAL_ANALYST_SYSTEM
        assert "counterpoint" in tf.TEMPORAL_ANALYST_SYSTEM

    def test_temporal_verdict_carries_fields_and_survives_validator(self):
        env = _env()
        payload = {
            "factual_verdict": "refuted", "temporal_status": "unknown",
            "evaluated_period": {}, "uncertainty": {},
            "inference_gap": "обобщение по одному случаю",
            "counterpoint": "частный случай не опровергает явление",
        }
        verdict = tf.verdict_from_payload(payload, env)
        assert verdict.inference_gap == "обобщение по одному случаю"
        assert verdict.counterpoint.startswith("частный случай")
        # перепроверка validator'ом не стирает смысловые поля
        corrected, applied = tf.apply_validator(
            verdict, {"agree": False, "corrected_factual_verdict": "mixed"},
            env)
        assert applied is True
        assert corrected.inference_gap == verdict.inference_gap
        assert corrected.counterpoint == verdict.counterpoint
        # без полей — пусто (в payload не появится)
        bare = tf.verdict_from_payload(
            {"factual_verdict": "refuted", "temporal_status": "unknown"}, env)
        assert bare.inference_gap == "" and bare.counterpoint == ""

    @pytest.mark.asyncio
    async def test_fields_reach_writer_payload(self, monkeypatch,
                                              owner_layers):
        cap = _capture(monkeypatch)
        service = fs.FactCheckService(None, None, None)
        verdict = _temporal_verdict(
            inference_gap="из цифр не следует вывод о масштабе",
            counterpoint="масштаб мог быть указан в сноске")
        await service._temporal_verbalize(_env(), verdict, False, None)
        user = cap.messages[1]["content"]
        payload = json.loads(user[len("ВЕРДИКТ (JSON):\n"):])
        assert payload["inference_gap"] == "из цифр не следует вывод о масштабе"
        assert payload["counterpoint"] == "масштаб мог быть указан в сноске"
        # без полей ключей нет вовсе (пустые поля не передаются)
        cap2 = _capture(monkeypatch)
        await service._temporal_verbalize(_env(), _temporal_verdict(), False,
                                         None)
        payload2 = json.loads(cap2.messages[1]["content"][
            len("ВЕРДИКТ (JSON):\n"):])
        assert "inference_gap" not in payload2
        assert "counterpoint" not in payload2


# ═══ 4. Renderer: адаптивная подача, никакой обрезки и шаблонов ═════════════

def _checked(parts=(), factual="refuted", links=(), evidence_refs=()):
    refs = tuple(orch.EvidenceRef(evidence_id=f"ev-{i}", url=url,
                                 support="выдержка")
                 for i, url in enumerate(links, start=1))
    return orch.CheckedVerdict(
        verdict_text="Разбор.", route="envelope_temporal",
        factual_verdict=factual,
        evidence=orch.EvidenceMap(refs=refs,
                                  allowlist=tuple(r.evidence_id for r in refs)),
        evidence_refs=tuple(evidence_refs), parts=tuple(parts))


class TestRendererAdaptivePresentation:
    def test_short_simple_claim_stays_short(self):
        body = "Да, подтверждается."
        markup = fr.render_factcheck(
            orch.FactcheckPresentation(text=body, links=()), _checked()).text
        visible = fr.visible_text(markup)
        assert visible.endswith(body)
        # ни навязанных четырёх пунктов, ни вводного списка
        assert "•" not in visible
        assert "По утверждениям:" not in visible

    def test_complex_claim_may_use_headings_and_bullets(self):
        body = ("Короткий разбор по пунктам.\n\n"
                "Что реально следует\n"
                "- источник подтверждает только факт подключения\n"
                "- сроки в источниках отсутствуют\n\n"
                "Вывод остается прежним.")
        markup = fr.render_factcheck(
            orch.FactcheckPresentation(text=body, links=()), _checked()).text
        visible = fr.visible_text(markup)
        assert "Что реально следует" in visible
        assert "- источник подтверждает только факт подключения" in visible
        # авторские абзацы сохранены (пустая строка между блоками)
        assert "\n\n" in visible
        # renderer не добавляет своих секций
        assert "По утверждениям:" not in visible
        assert "Критический разнос" not in visible

    def test_renderer_escapes_markup_in_authored_text(self):
        body = "# Заголовок\n- пункт с <b>тегом</b> и & амперсандом"
        markup = fr.render_factcheck(
            orch.FactcheckPresentation(text=body, links=()), _checked()).text
        assert "&lt;b&gt;" in markup        # инъекция тега невозможна
        assert "&amp;" in markup
        assert fr.visible_text(markup).split("\n\n")[-1].startswith("# Заголовок")
    def test_claims_are_not_truncated(self):
        long_claim = ("В официальном релизе указано, что подключение агентов "
                      "через API начнётся не раньше следующего квартала, а "
                      "пилот будет ограничен тремя регионами и двумя "
                      "провайдерами одновременно")
        assert len(long_claim) > 110
        verdict = _checked(parts=({"part_id": "p1", "text": long_claim,
                                   "factual_verdict": "supported"},))
        markup = fr.render_factcheck(
            orch.FactcheckPresentation(text="   ", links=()), verdict).text
        visible = fr.visible_text(markup)
        assert long_claim in visible           # целиком, без «…»
        assert "…" not in visible

    def test_fallback_publishes_all_claims_without_cap(self):
        parts = tuple({"part_id": f"p{i}", "text": f"тезис номер {i}",
                       "factual_verdict": "supported"}
                      for i in range(1, 11))
        verdict = _checked(parts=parts)
        markup = fr.render_factcheck(
            orch.FactcheckPresentation(text="", links=()), verdict).text
        visible = fr.visible_text(markup)
        for i in range(1, 11):
            assert f"тезис номер {i}" in visible, i
        assert "не показаны" not in visible    # молчаливой утери нет

    def test_verdict_and_validated_links_kept(self):
        verdict = _checked(factual="mixed",
                           links=("https://news.example.org/a",),
                           evidence_refs=("ev-1",))
        presentation = orch.FactcheckPresentation(
            text="Разбор по существу.",
            links=("https://news.example.org/a", "https://fake.example.net/x"))
        text = fr.render_factcheck(presentation, verdict).text
        assert "<b>Подтверждается частично</b>" in text
        assert "https://news.example.org/a" in text
        assert "fake.example.net" not in text   # вне EvidenceMap прогона

    def test_plain_channel_keeps_headings_and_bullets_as_text(self):
        """Без parse_mode разметка не нужна: подзаголовок и пункты — текст."""
        body = "Что следует\n- пункт один\n- пункт два"
        plain = fr.render_plain(
            orch.FactcheckPresentation(text=body, links=()), _checked())
        assert plain.parse_mode is None
        assert "Что следует" in plain.text
        assert "- пункт один" in plain.text and "- пункт два" in plain.text
        assert "<b>" not in plain.text        # тегов, которые уйдут сырыми
        assert "**" not in plain.text

    def test_long_bullet_list_is_chunked_without_breaking_markup(self):
        body = "\n".join(f"- пункт {i} с текстом разбора" for i in range(1, 60))
        markup = fr.render_factcheck(
            orch.FactcheckPresentation(text=body, links=()), _checked()).text
        chunks = fr.split_entity_safe(markup, 400)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.count("<b>") == chunk.count("</b>")
            assert "- пункт" in chunk or "Подтверждается" in chunk

    def test_legacy_section_not_reformatted(self):
        body = ("Разбор по существу.\n\n"
                "Критический разнос: цифры взяты с потолка.")
        markup = fr.render_factcheck(
            orch.FactcheckPresentation(text=body, links=()),
            _checked()).text
        assert "<b>Критический разнос</b>" not in markup
        assert "цифры взяты с потолка" in fr.visible_text(markup)
        # выключенная настройка владельца соблюдается детерминированно
        stripped = fr.render_factcheck(
            orch.FactcheckPresentation(text=body, links=()),
            _checked(), allow_critique=False).text
        assert "Критический разнос" not in fr.visible_text(stripped)
        assert "Разбор по существу." in fr.visible_text(stripped)


# ═══ 5. Expression — единственный регулятор регистра ════════════════════════

class TestExpressionIsTheOnlyVoiceRegulator:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["off", "occasional", "frequent"])
    async def test_mode_resolves_through_expression_layer(self, monkeypatch,
                                                          mode):
        text = ("<Expression_Settings>\n"
                + ex.PROFANITY_INSTRUCTIONS[mode] + "\n</Expression_Settings>")

        async def fake_expression(chat_id):
            return pc.ExpressionSettings(text=text, enabled=True, mode=mode,
                                         revision=f"rev-{mode}", source="chat")

        async def no_examples(chat_id, _mode):
            return ()

        monkeypatch.setattr(pc, "resolve_expression_settings", fake_expression)
        monkeypatch.setattr(ex, "build_expression_examples_refs", no_examples)
        system, manifest = await pc.compose_speech_system(
            chat_id=CHAT_ID, writer="factcheck_verbalizer",
            base_prompt=fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
            base_source="code", include_mode_block=False,
            identity_skipped="duplicate_of_persona",
            plan_skip="no_l1_plan_in_genre",
            humor_skip="genre_argued_analysis", include_speech_base=True)
        # действующий слой — именно Expression выбранного режима, один раз
        assert system.count(EXPR_OPEN) == 1
        assert ex.PROFANITY_INSTRUCTIONS[mode] in system
        # финальный контракт того же режима — последним (приоритет настройки)
        assert system.rstrip().endswith(ex.render_expression_final_contract(mode))
        # канон не подменяет режим своим правилом
        assert _MAT_WORD_RE.search(fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT) is None
        # в манифесте слой отрендерен и назван владельцем
        expr = [t for t in manifest.layers if t.layer == pc.LAYER_EXPRESSION]
        assert expr and expr[0].rendered

    @pytest.mark.asyncio
    async def test_off_mode_has_no_enabled_register_words(self, monkeypatch):
        text = ("<Expression_Settings>\n"
                + ex.PROFANITY_INSTRUCTIONS["off"] + "\n</Expression_Settings>")

        async def fake_expression(chat_id):
            return pc.ExpressionSettings(text=text, enabled=True, mode="off",
                                         source="chat")

        monkeypatch.setattr(pc, "resolve_expression_settings", fake_expression)
        system, _m = await pc.compose_speech_system(
            chat_id=CHAT_ID, writer="factcheck_verbalizer", base_prompt="КАНОН",
            base_source="code", include_mode_block=False,
            include_speech_base=False)
        assert ex.PROFANITY_INSTRUCTIONS["frequent"] not in system
        assert ex.PROFANITY_INSTRUCTIONS["occasional"] not in system


# ═══ 6. Direct: делегат без изменения поведения ═════════════════════════════

class TestDirectNotRegressed:
    @pytest.mark.asyncio
    async def test_delegate_matches_module_function_bytes(self, monkeypatch,
                                                         owner_layers):
        from services.direct_chat_service import DirectChatService

        svc = DirectChatService.__new__(DirectChatService)
        kwargs = dict(chat_id=CHAT_ID, writer="l2_writer", run_id=None,
                      base_prompt="БАЗА DIRECT", base_key="",
                      base_default="", gates=pc.gates_from_config())
        via_method, manifest_method = await svc._compose_speech_system(**kwargs)
        direct, manifest_direct = await pc.compose_speech_system(**kwargs)
        assert via_method == direct
        assert manifest_method.manifest_id == manifest_direct.manifest_id
        # жанр фактчека в Direct не подмешивается
        assert "Вступай в спор" not in via_method
        assert "<Speech_Base>" in via_method      # базовая манера Direct цела

    @pytest.mark.asyncio
    async def test_direct_and_factcheck_get_same_owner_bytes(self, monkeypatch,
                                                             owner_layers):
        fact, _m = await pc.compose_speech_system(
            chat_id=CHAT_ID, writer="factcheck_verbalizer",
            base_prompt=fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
            base_source="code", include_mode_block=False,
            identity_skipped="duplicate_of_persona",
            plan_skip="no_l1_plan_in_genre",
            humor_skip="genre_argued_analysis", include_speech_base=True)
        direct, _m2 = await pc.compose_speech_system(
            chat_id=CHAT_ID, writer="l2_writer", base_prompt="БАЗА DIRECT",
            base_source="code")
        for marker in (CORE_MARKER, EXPR_MARKER):
            # байты слоя владельца идентичны, но каждое вхождение одно
            assert fact.count(marker) == 1
            assert direct.count(marker) == 1
        # различие жанров — только в каноне и наборе слоёв, не в owner-слое
        assert "Вступай в спор" in fact and "Вступай в спор" not in direct

    def test_l1_and_analyst_get_no_speech_style(self):
        """Стиль не переезжает в машинные стадии (аналитик/L1)."""
        from services import chat_prompts as cp
        for canon in (fp.FACTCHECK_ANALYST_SYSTEM_PROMPT,
                      cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT):
            assert "Вступай в спор" not in canon
            assert "<Expression_Settings>" not in canon
            assert "по-русски" not in canon.lower() or "json" in canon.lower()
