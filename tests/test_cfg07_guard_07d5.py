"""CFG-07D.5 — bounded retry смысловой метаречи + FA-*/MB-10/11/12-детекторы.

Волна 07D.5 (план plans/features/cfg/cfg-07-build-plan.md §07C-G, хвост
07cg-reuse-audit.md §3, 07cg-tail.md §6):

* машинные артефакты корпуса 07A-1 (FA-06 UNCHANGED / FA-07 nostalgia_hint:
  / FA-08 [СИСТЕМНОЕ УВЕДОМЛЕНИЕ, JSON-эхо FA-01/02, метка SF-16,
  MB-10 tech-поля / MB-11 reason-коды / MB-12 tool-имена) детектируются в
  public_speech_guard и срезаются детерминированно — факты/числа/ссылки
  целы; границы токенов (``host_not_actively``/``myunchanged`` не ловятся);
* смысловой слой: инверсные/вариативные формулировки тотальной проверки
  («весь интернет я проверил»), НЕ пойманные закрытыми сетами 07D.2, —
  находка ``semantic:total_verification_variant``; дословные формулы
  задваивания не дают (детерминированный ремонт существует);
* bounded retry: ``verbalize_validated(metatext_reason=...)`` — ОДИН
  повтор с кодом причины внутри СУЩЕСТВУЮЩЕГО бюджета (≤2, ≤1 на
  metatext), неудача → честная деградация
  (``metatext_fallback`` + ``strip_guard_findings``), без фиктивных
  успехов; default ``None`` → байт-паритет (stats без новых ключей);
* wiring: factcheck Stage-2/temporal-вербализатор передают контракт
  ТОЛЬКО в контуре pipeline v2 (тот же рубильник) — OFF (default) →
  контракт ``None``, поведение прежнее;
* POSITIVE-контролы (корпус PC-*, honesty-пулы, renderer/checkup-каноны)
  — 0 ложных.

Всё на моках: сеть, LLM и реальные чаты не используются.

TEST-LIFECYCLE: CONTRACT owner=CFG-07D5
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.settings import settings
from services import public_speech_guard as psg
from services import smartmodule_phrases as ph
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE
from services.factcheck_renderer import _NO_LINKS_NOTICE, _VERDICT_HEADLINE
from services.negative_constraints import verbalize_validated

# ── Фикстуры корпуса (07a1-corpus.json — source of record) ──────────────────

SEMANTIC_INVERSE = "весь интернет я проверил: тезис подтверждается"
SEMANTIC_INVERSE_2 = "Тезис опровергается. Всю сеть я перерыл — ничего нет."
CLOSED_DIRECT = "Я проверил всё в интернете: тезис не подтверждается."
CLEAN_VERDICT = "Тезис подтверждается по трём ссылкам, вот первоисточник."

#: Грязные фикстуры: (corpus_id, текст, остаток-факт после среза | None).
DIRTY_FIXTURES = [
    ("FA-06", "UNCHANGED, история не поменялась", "история не поменялась"),
    ("FA-07", "nostalgia_hint: Вася упоминал дачу", "Вася упоминал дачу"),
    ("FA-08", "[СИСТЕМНОЕ УВЕДОМЛЕНИЕ] модуль недоступен",
     "модуль недоступен"),
    ("FA-01", '{"reason": "temporal_date_unknown"} тезис подтверждается',
     "тезис подтверждается"),
    ("FA-02", 'режим "response_mode" не выбран, ответ готов',
     "ответ готов"),
    ("SF-16",
     "[Архивная справка: 01.2024 | Вася | ID]: к слову про дачу — это было "
     "год назад", "к слову про дачу"),
    ("MB-10", "Период проверки: 2024 год, источник подтверждает.",
     "2024 год, источник подтверждает."),
    ("MB-11", "tool_not_active — поэтому ссылок нет", "поэтому ссылок нет"),
    ("MB-12", "запустил execute_web_search и нашёл подтверждение",
     "и нашёл подтверждение"),
]


# ── Harness (моки, без сети/LLM/реальных чатов) ─────────────────────────────

class _Gen:
    """Фейковый Вербализатор: сценарий ответов + журнал сообщений."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.seen: list[list[dict]] = []

    async def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        return self.answers.pop(0)


@pytest.fixture
def v2_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


@pytest.fixture
def v2_off():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


def _corpus() -> dict:
    path = Path(__file__).resolve().parents[1] / psg.CORPUS_PATH
    return json.loads(path.read_text(encoding="utf-8"))


# ════════════════════════════════════════════════════════════════════════════
# 1. Машинные артефакты: детекция + детерминированный срез (факты целы)
# ════════════════════════════════════════════════════════════════════════════

class TestMachineArtifactDetectors:
    @pytest.mark.parametrize("corpus_id,text,fact_kept", DIRTY_FIXTURES)
    def test_dirty_detected_and_cut_facts_kept(self, corpus_id, text,
                                               fact_kept):
        """Грязная фикстура корпуса: находка с id записи; guard срезает
        артефакт, содержательный остаток жив."""
        assert psg.find_machine_artifacts(text) == (corpus_id,), text
        res = psg.guard_public_text(text)
        assert corpus_id in res.findings, text
        assert res.changed is True and res.repaired is True, text
        assert fact_kept in res.text, text

    def test_unrepairable_artifact_reports_empty(self):
        """Сплошной машинный артефакт → вырожденный остаток (text=""),
        шов обязан подставить честный класс — без фиктивного тела."""
        res = psg.guard_public_text('{"reason": "temporal_date_unknown"}')
        assert res.text == ""
        assert res.changed is True and res.repaired is False
        assert "FA-01" in res.findings

    def test_token_boundaries_no_false_positive(self):
        """Границы машинных токенов: подстроки внутри других слов/token'ов
        не срабатывают (07A.7 — не растущий black-list)."""
        for text in ("host_not_actively отвечает",
                     "myunchanged токен не при чём",
                     "неnostalgia_hint: другой случай",
                     "история ии и мифология",
                     "в проверенных источниках этого нет",
                     "проверенный интернет-магазин"):
            assert psg.find_machine_artifacts(text) == (), text
            assert psg.find_semantic_metatext(text) == (), text

    def test_admin_context_passthrough(self):
        """Явный админ-контекст: техсправка с машинным полем не режется
        (07A.5 — блокировка метаречи не заставляет врать)."""
        text = "Период проверки настраивается в админке, поле as_of."
        res = psg.guard_public_text(text, admin_context=True)
        assert res.text == text and res.admin_context is True

    def test_strip_guard_findings_idempotent(self):
        """strip_guard_findings идемпотентен (повторное применение швами)."""
        once = psg.strip_guard_findings(
            "Период проверки: 2024. UNCHANGED. Тезис верен.")
        twice = psg.strip_guard_findings(once)
        assert once == twice
        assert "2024" in once and "Тезис верен" in once

    def test_bracket_strip_keeps_honest_brackets(self):
        # TEST-LIFECYCLE: REGRESSION owner=CFG-07D5 (review-07d5 F2)
        """Срез FA-08 режет ТОЛЬКО системную bracket-вставку: честные
        скобки («[1]», «[прим. автора]») целы. Раньше дефектная форма
        строила шаблон с ведущей '[' как char-class'ом (а не литеральной
        скобкой) и резала произвольные скобочные блоки."""
        text = "[СИСТЕМНОЕ УВЕДОМЛЕНИЕ: x] см. [1] и [прим. автора]"
        assert psg.find_machine_artifacts(text) == ("FA-08",)
        assert psg.strip_guard_findings(text) == "см. [1] и [прим. автора]"
        res = psg.guard_public_text(text)
        assert res.changed is True and res.repaired is True
        assert res.text == "см. [1] и [прим. автора]"
        assert "СИСТЕМНОЕ УВЕДОМЛЕНИЕ" not in res.text


class TestCorpusParity:
    """Детекторы покрывают РОВНО записи корпуса (источник — сам файл)."""

    def test_corpus_rows_covered(self):
        entries = {e["id"]: e for e in _corpus()["entries"]}
        covered = {"FA-06", "FA-07", "FA-08", "FA-01", "FA-02", "SF-16",
                   "MB-10", "MB-11", "MB-12"}
        for key in sorted(covered):
            entry = entries[key]
            if "pattern" in entry:
                markers = [entry["pattern"], *entry.get("alt", ())]
            else:
                # SF-16 (SOURCE_FIX): источник — метка архивных блоков
                # («Архивная справка», E3-эхо MB-02; запрет в digest уже
                # живёт в system2_handoff).
                markers = ["Архивная справка"]
            for marker in markers:
                probe = f"ну да, {marker}, двигаемся дальше"
                assert psg.find_machine_artifacts(probe) == (key,), \
                    (key, marker)

    def test_machine_family_ids_registered(self):
        ids = {f.corpus_id for f in psg._MACHINE_FAMILIES}
        assert ids == {"FA-06", "FA-07", "FA-08", "FA-01", "FA-02",
                       "SF-16", "MB-10", "MB-11", "MB-12"}
        assert all(f.detect and f.strip for f in psg._MACHINE_FAMILIES)


# ════════════════════════════════════════════════════════════════════════════
# 2. Смысловой слой: инверсии overclaim (закрытые сеты их не ловят)
# ════════════════════════════════════════════════════════════════════════════

class TestSemanticLayer:
    def test_inverse_overclaim_detected(self):
        """Инверсия («весь интернет я проверил») — находка смыслового
        слоя; закрытый сет 07D.2 её НЕ ловит (остаток 07cg-tail §2.2)."""
        assert not psg.claims_total_verification(SEMANTIC_INVERSE)
        assert psg.find_semantic_metatext(SEMANTIC_INVERSE) == (
            "semantic:total_verification_variant",)
        assert not psg.claims_total_verification(
            "Тезис опровергается. Всю сеть я перерыл.")
        assert psg.find_semantic_metatext(SEMANTIC_INVERSE_2)

    def test_closed_direct_form_not_double_reported(self):
        """Дословная формула покрыта закрытым сетом → детерминированный
        ремонт существует; смысловой слой её НЕ задваивает."""
        assert psg.claims_total_verification(CLOSED_DIRECT)
        assert psg.find_semantic_metatext(CLOSED_DIRECT) == ()

    def test_participles_and_hypernyms_clean(self):
        """Причастия/чужие объекты не ловятся (грамматика закрытая)."""
        for text in ("в проверенных источниках этого нет",
                     "весь интернет-магазин я проверил",
                     "вся сеть фастфуда обсуждает закрытие",
                     "тезис проверен по трём ссылкам"):
            assert psg.find_semantic_metatext(text) == (), text

    def test_retry_reason_only_for_semantic(self):
        """metatext_retry_reason: причина ТОЛЬКО для смысловой метаречи;
        дословные формулы и машинные артефакты → None (срез существует,
        бюджет retry не тратится); чистое → None."""
        assert psg.metatext_retry_reason(
            SEMANTIC_INVERSE) == "metatext_semantic:total_verification_variant"
        assert psg.metatext_retry_reason(CLOSED_DIRECT) is None
        assert psg.metatext_retry_reason("по моим логам") is None
        assert psg.metatext_retry_reason("UNCHANGED") is None
        assert psg.metatext_retry_reason(CLEAN_VERDICT) is None
        assert psg.metatext_retry_reason(
            "проверил — не нашёл подтверждений") is None   # PC-01

    def test_honest_negation_not_flagged_dirty_inverse_is(self):
        # TEST-LIFECYCLE: REGRESSION owner=CFG-07D5 (review-07d5 F3)
        """Честное ограничение с «не» перед глаголом НЕ даёт retry-код
        (класс PC-01, retry-канон: «честные ограничения сохрани»);
        грязная инверсия без «не» — ДАЁТ."""
        honest = "Тезис не подтверждён — весь интернет я не проверил."
        assert psg.find_semantic_metatext(honest) == ()
        assert psg.metatext_retry_reason(honest) is None
        # отрицание с двойным пробелом тоже не триггер
        assert psg.find_semantic_metatext(
            "весь интернет я не  проверил") == ()
        # «не», слитое с чужим словом («была/в сети»), НЕ гасит детектор:
        # грязная инверсия с «-не»-окончанием соседнего слова ловится
        assert psg.find_semantic_metatext(
            "Вся сеть была изучена мной вчера") == (
            "semantic:total_verification_variant",)
        # грязная инверсия — прежнее поведение
        assert psg.metatext_retry_reason(SEMANTIC_INVERSE) == \
            "metatext_semantic:total_verification_variant"

    def test_semantic_not_stripped_silently_in_guard(self):
        """Guard НЕ срезает инверсию без дословной формулы (для неё —
        retry в Вербализаторе), но честно репортит находку; после
        неудачного retry инверсная формула срезается strip-грамматикой."""
        res = psg.guard_public_text("Обсуждали весь интернет вчера.")
        assert res.findings == ()          # объект без глагола — чисто
        stripped = psg.strip_guard_findings("Весь интернет я проверил.")
        assert "весь интернет" not in stripped.lower()
        assert "проверил" not in stripped.lower()


# ════════════════════════════════════════════════════════════════════════════
# 3. 0 ложных на POSITIVE-контролях (пулы/каноны/примеры владельца)
# ════════════════════════════════════════════════════════════════════════════

class TestNoFalsePositives:
    def test_owner_canon_pools_clean(self):
        """Все владельческие пулы/канонические тексты: 0 машинных
        артефактов, 0 смысловых находок, guard байт-в-байт."""
        checked = 0
        for name in dir(ph):
            if not name.isupper():
                continue
            value = getattr(ph, name)
            texts: list[str] = []
            if isinstance(value, tuple) and value and \
                    all(isinstance(x, str) for x in value):
                texts = list(value)
            elif isinstance(value, str):
                texts = [value]
            elif isinstance(value, dict):
                texts = [v for v in value.values() if isinstance(v, str)]
            for text in texts:
                assert psg.find_machine_artifacts(text) == (), (name, text)
                assert psg.find_semantic_metatext(text) == (), (name, text)
                assert psg.guard_public_text(text).text == text, \
                    (name, text)
                checked += 1
        assert checked >= 60

    def test_honest_canon_texts_clean(self):
        for text in (_NO_LINKS_NOTICE, CHECKUP_FALLBACK_NOTICE,
                     *_VERDICT_HEADLINE.values(),
                     "проверил — не нашёл подтверждений",      # PC-01
                     "такого сообщения не нашлось",            # PC-02
                     "не смог сделать саммари",                # PC-03
                     "эта часть сейчас недоступна",            # PC-09
                     "нашёл подтверждение",
                     "кстати, год назад мы обсуждали этот маршрут",
                     "логи сервера чистые, инцидентов нет",
                     "анализ показывает рост нагрузки",
                     "проверка заняла минуту, всё работает"):
            assert psg.find_machine_artifacts(text) == (), text
            assert psg.find_semantic_metatext(text) == (), text
            assert psg.guard_public_text(text).text == text, text

    def test_positives_from_corpus_file(self):
        """Каждый POSITIVE-пример корпуса (example/alt) — чист."""
        for entry in _corpus()["entries"]:
            if entry.get("cls") != "POSITIVE":
                continue
            for text in [entry.get("example", ""),
                         *entry.get("alt", ())]:
                if not text or len(text) < 3:
                    continue
                assert psg.find_machine_artifacts(text) == (), \
                    (entry["id"], text)
                assert psg.find_semantic_metatext(text) == (), \
                    (entry["id"], text)


# ════════════════════════════════════════════════════════════════════════════
# 4. Bounded retry семантика (verbalize_validated, metatext_reason)
# ════════════════════════════════════════════════════════════════════════════

def _real_reason(text):
    return psg.metatext_retry_reason(text)


@pytest.mark.system2     # conftest: валидатор ON (прод-дефолт) для контракта
class TestBoundedRetrySemantics:
    @pytest.mark.asyncio
    async def test_retry_repairs_within_limit(self):
        """Грязный семантике ответ → ОДИН повтор с причиной → чисто;
        attempts ≤ лимита (≤2 всего), metatext_retry=True."""
        gen = _Gen([SEMANTIC_INVERSE, CLEAN_VERDICT])
        text, stats = await verbalize_validated(
            gen, [{"role": "system", "content": "base"}],
            max_retries=2, metatext_reason=_real_reason)
        assert text == CLEAN_VERDICT
        assert stats["attempts"] == 2 and stats["retries"] == 1
        assert stats["metatext_retry"] is True
        assert stats["metatext_fallback"] is False
        assert stats["metatext_rejects"] == 1
        # причина (код, не приватный текст) — в retry-промпте
        retry_system = gen.seen[1][-1]
        assert retry_system["role"] == "system"
        assert "metatext_semantic:total_verification_variant" \
            in retry_system["content"]

    @pytest.mark.asyncio
    async def test_metatext_retry_cap_one_in_shared_budget(self):
        """Metatext-повтор ≤1: даже при max_retries=2 второй retry не
        уходит на metatext (бюджет общий, не растёт)."""
        gen = _Gen([SEMANTIC_INVERSE, SEMANTIC_INVERSE, SEMANTIC_INVERSE])
        text, stats = await verbalize_validated(
            gen, [{"role": "system", "content": "base"}],
            max_retries=2, metatext_reason=_real_reason)
        assert stats["attempts"] <= 3          # initial + ≤2
        assert stats["metatext_retry"] is True
        assert stats["metatext_fallback"] is True
        # деградация: инверсная формула срезана, факт цел
        assert "весь интернет" not in text.lower()
        assert "проверил" not in text.lower()
        assert "тезис подтверждается" in text.lower()

    @pytest.mark.asyncio
    async def test_retry_error_honest_fallback(self):
        """Ошибка generate на ретрае → последний успешный текст с
        детерминированной зачисткой (без выдуманных вердиктов)."""
        class Boom:
            def __init__(self):
                self.n = 0

            async def __call__(self, messages):
                self.n += 1
                if self.n == 1:
                    return SEMANTIC_INVERSE
                raise RuntimeError("llm down")

        text, stats = await verbalize_validated(
            Boom(), [{"role": "system", "content": "base"}],
            max_retries=2, metatext_reason=_real_reason)
        assert stats["retry_error"] is True
        assert stats["metatext_fallback"] is True
        assert "весь интернет" not in text.lower()
        assert "тезис подтверждается" in text.lower()

    @pytest.mark.asyncio
    async def test_closed_formula_costs_no_retry(self):
        """Дословная overclaim-формула: детектор даёт None → retry НЕ
        тратится (ремонт — детерминированный срез на delivery-шве)."""
        gen = _Gen([CLOSED_DIRECT])
        text, stats = await verbalize_validated(
            gen, [{"role": "system", "content": "base"}],
            max_retries=2, metatext_reason=_real_reason)
        assert stats["attempts"] == 1
        assert int(stats.get("metatext_rejects") or 0) == 0
        assert text == CLOSED_DIRECT           # валидатор не меняет

    @pytest.mark.asyncio
    async def test_default_none_byte_parity(self):
        """metatext_reason=None (default): stats без новых ключей,
        поведение байт-в-байт прежнее."""
        gen = _Gen([CLEAN_VERDICT])
        text, stats = await verbalize_validated(
            gen, [{"role": "system", "content": "base"}])
        assert text == CLEAN_VERDICT
        assert not any(k.startswith("metatext") for k in stats)

    @pytest.mark.asyncio
    async def test_kill_switch_bypasses_metatext(self, monkeypatch):
        """Kill-switch валидатора OFF → один прямой вызов, контракт не
        применяется (прежний документированный bypass)."""
        # Флаг — ClassVar (config/settings.py): патчим КЛАСС через
        # monkeypatch. Инстанс-патч через object.__setattr__ оставил бы
        # тень-инстанс после restore, которая навсегда перекрывает
        # класс-патчи чужих тестов (ломает комбинированные прогоны,
        # review-07d5 F1).
        monkeypatch.setattr(type(settings),
                            "SYSTEM2_VALIDATOR_LOOP_ENABLED", False)
        gen = _Gen([SEMANTIC_INVERSE])
        text, stats = await verbalize_validated(
            gen, [{"role": "system", "content": "base"}],
            metatext_reason=_real_reason)
        assert stats["enabled"] is False
        assert stats["attempts"] == 1
        assert int(stats.get("metatext_rejects") or 0) == 0
        # тень-инстанс не осталась: флаг читается с класса, как до патча
        assert "SYSTEM2_VALIDATOR_LOOP_ENABLED" not in vars(settings)


# ════════════════════════════════════════════════════════════════════════════
# 5. Wiring фактчека: контракт живёт ТОЛЬКО в v2-контуре (OFF-паритет)
# ════════════════════════════════════════════════════════════════════════════

class _CaptureVerbalize:
    def __init__(self):
        self.kwargs: list[dict] = []

    async def __call__(self, _generate, messages, **kwargs):
        self.kwargs.append(kwargs)
        return "ок, вердикт", {"attempts": 1, "retries": 0, "hits": [],
                               "fallback": False}


def _make_service():
    from services import factcheck_service as fs
    return fs, fs.FactCheckService(aggregator=None, llm=None, memory=None)


def _analyst_raw(monkeypatch, svc):
    async def fake_invoke(messages, target_text, chat_id, *,
                          correlation_id=None, step="single"):
        return ('{"claim": "дрожжи это грибы", "verdict": "опровергается", '
                '"findings": [{"assertion": "дрожжи не грибы", '
                '"status": "false", "evidence": "учебник биологии", '
                '"human_time": "без даты"}]}'), False

    monkeypatch.setattr(svc, "_invoke_llm", fake_invoke)


class TestFactcheckV2Wiring:
    def test_gate_helper_off_and_on(self, v2_off):
        """OFF (default): helper возвращает None → контракт не активен."""
        from services.factcheck_service import _metatext_retry_reason
        assert _metatext_retry_reason() is None

    def test_gate_helper_on_returns_detector(self, v2_on):
        from services.factcheck_service import _metatext_retry_reason
        assert _metatext_retry_reason() is psg.metatext_retry_reason

    @pytest.mark.asyncio
    async def test_temporal_verbalizer_wires_contract_v2_on(
            self, v2_on, monkeypatch):
        """v2 ON: temporal-вербализатор передаёт metatext-контракт."""
        from services import factcheck_service as fs
        from services import temporal_factcheck as tf
        cap = _CaptureVerbalize()
        monkeypatch.setattr(fs, "verbalize_validated", cap)
        fs_svc, svc = _make_service()
        env = tf.TemporalClaimEnvelope(
            claim_id="c-1", chat_id=777, target_tg_message_id=9200,
            target_revision=None, target_content_hash=None,
            trigger_tg_message_id=9201,
            claim_text="дрожжи это грибы", claim_span=None,
            source_type="text", attribution={}, origin_type=None,
            origin_sender_user_id=None, origin_chat_id=None,
            origin_display_name=None, repost_received_at=None,
            original_published_at=None,
            original_published_precision=None, claim_period_from=None,
            claim_period_to=None, claim_period_precision=None,
            date_source="unknown", date_precision="unknown",
            date_timezone=None, date_uncertainty={},
            requested_mode="contextual", analysis_as_of=1760900000)
        verdict = tf.TemporalVerdict(
            factual_verdict="refuted", temporal_status="unknown",
            evaluated_period={"from": None, "to": None,
                              "precision": "unknown"},
            assessment_mode="contextual", as_of=1760900000,
            evidence_refs=("ev-1",), uncertainty={}, parts=(), reason=None)
        await svc._temporal_verbalize(env, verdict, False, None)
        assert len(cap.kwargs) == 1
        assert cap.kwargs[0].get("metatext_reason") is \
            psg.metatext_retry_reason

    @pytest.mark.asyncio
    async def test_temporal_verbalizer_off_no_contract(
            self, v2_off, monkeypatch):
        """v2 OFF: temporal-вербализатор передаёт None (байт-паритет)."""
        from services import factcheck_service as fs
        from services import temporal_factcheck as tf
        cap = _CaptureVerbalize()
        monkeypatch.setattr(fs, "verbalize_validated", cap)
        fs_svc, svc = _make_service()
        env = tf.TemporalClaimEnvelope(
            claim_id="c-1", chat_id=777, target_tg_message_id=9200,
            target_revision=None, target_content_hash=None,
            trigger_tg_message_id=9201,
            claim_text="дрожжи это грибы", claim_span=None,
            source_type="text", attribution={}, origin_type=None,
            origin_sender_user_id=None, origin_chat_id=None,
            origin_display_name=None, repost_received_at=None,
            original_published_at=None,
            original_published_precision=None, claim_period_from=None,
            claim_period_to=None, claim_period_precision=None,
            date_source="unknown", date_precision="unknown",
            date_timezone=None, date_uncertainty={},
            requested_mode="contextual", analysis_as_of=1760900000)
        verdict = tf.TemporalVerdict(
            factual_verdict="refuted", temporal_status="unknown",
            evaluated_period={"from": None, "to": None,
                              "precision": "unknown"},
            assessment_mode="contextual", as_of=1760900000,
            evidence_refs=("ev-1",), uncertainty={}, parts=(), reason=None)
        await svc._temporal_verbalize(env, verdict, False, None)
        assert len(cap.kwargs) == 1
        assert cap.kwargs[0].get("metatext_reason") is None

    @pytest.mark.asyncio
    async def test_stage2_verbalizer_wires_contract_v2_on(
            self, v2_on, monkeypatch):
        """v2 ON: Stage-2 Вербализатор фактчека передаёт контракт."""
        from services import factcheck_service as fs
        cap = _CaptureVerbalize()
        monkeypatch.setattr(fs, "verbalize_validated", cap)
        fs_svc, svc = _make_service()
        _analyst_raw(monkeypatch, svc)

        async def no_owner_block(chat_id):
            return ""

        monkeypatch.setattr(fs, "speech_owner_block", no_owner_block)
        monkeypatch.setattr(svc, "_finalize_text",
                            lambda *a, **k: "ФИНАЛ")
        await svc._check_claim_two_call(
            "дрожжи это грибы", "USER", "", "RESULTS", 777, 1000)
        assert len(cap.kwargs) == 1
        assert cap.kwargs[0].get("metatext_reason") is \
            psg.metatext_retry_reason

    @pytest.mark.asyncio
    async def test_stage2_verbalizer_off_no_contract(
            self, v2_off, monkeypatch):
        """v2 OFF: Stage-2 передаёт None — OFF-паритет прод-пути."""
        from services import factcheck_service as fs
        cap = _CaptureVerbalize()
        monkeypatch.setattr(fs, "verbalize_validated", cap)
        fs_svc, svc = _make_service()
        _analyst_raw(monkeypatch, svc)

        async def no_owner_block(chat_id):
            return ""

        monkeypatch.setattr(fs, "speech_owner_block", no_owner_block)
        monkeypatch.setattr(svc, "_finalize_text",
                            lambda *a, **k: "ФИНАЛ")
        await svc._check_claim_two_call(
            "дрожжи это грибы", "USER", "", "RESULTS", 777, 1000)
        assert len(cap.kwargs) == 1
        assert cap.kwargs[0].get("metatext_reason") is None


# ════════════════════════════════════════════════════════════════════════════
# 6. Delivery-шов v2: машинные артефакты срезаются до Telegram (07D.5)
# ════════════════════════════════════════════════════════════════════════════

class TestDeliverySeamMachineArtifacts:
    @pytest.mark.parametrize("corpus_id,text,fact_kept", [
        ("MB-10", "Период проверки: 2024. Тезис не подтверждается.",
         "не подтверждается"),
        ("MB-11", "tool_not_active. Тезис не подтверждается.",
         "не подтверждается"),
        ("FA-08", "[СИСТЕМНОЕ УВЕДОМЛЕНИЕ] Тезис не подтверждается.",
         "не подтверждается"),
    ])
    def test_apply_guard_cuts_artifacts_keeps_verdict(
            self, corpus_id, text, fact_kept):
        """Артефакт в payload Writer'а: delivery-шов срезает его до
        Telegram, enum-вердикт (реальный статус) цел."""
        from services.factcheck_orchestrator import (
            CheckedVerdict,
            FactcheckPresentation,
            _apply_delivery_guard,
        )
        assert corpus_id in psg.guard_public_text(text).findings
        presentation = FactcheckPresentation(text=text)
        verdict = CheckedVerdict(verdict_text=text, route="legacy_single",
                                 factual_verdict="refuted")
        pres2, verdict2 = _apply_delivery_guard(presentation, verdict)
        assert fact_kept in pres2.text
        assert verdict2.factual_verdict == "refuted"   # enum цел

    def test_apply_guard_semantic_reports_and_strips_inverse(self):
        """Инверсия без дословной формулы: retry — в Вербализаторе, а
        delivery-шов честно репортит находку телеметрией И режет
        инверсную формулу defense-in-depth (_INVERSE_STRIP_RE входит в
        _strip_matches → guard_public_text меняет текст; review-07d5 F4:
        докам приведены к факту). Остаток « .» после среза — существующий
        класс уборки _strip_matches (так же режет закрытые формулы на
        HEAD) — вне скоупа волны. Чистые тексты байт-в-байт."""
        res = psg.guard_public_text(
            "Тезис подтверждается. Весь интернет я проверил.")
        assert "semantic:total_verification_variant" in res.findings
        assert res.changed is True and res.repaired is True
        assert "весь интернет" not in res.text.lower()
        assert "проверил" not in res.text.lower()
        assert "Тезис подтверждается" in res.text
        from services.factcheck_orchestrator import (
            CheckedVerdict,
            FactcheckPresentation,
            _apply_delivery_guard,
        )
        presentation = FactcheckPresentation(
            text="Тезис подтверждается, вопрос исчерпан.")
        verdict = CheckedVerdict(verdict_text="Тезис подтверждается.",
                                 route="legacy_single",
                                 factual_verdict="supported")
        pres2, verdict2 = _apply_delivery_guard(presentation, verdict)
        assert pres2.text == presentation.text    # чистое не тронуто
        assert verdict2.factual_verdict == "supported"
