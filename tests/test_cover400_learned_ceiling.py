# TEST-LIFECYCLE: REGRESSION owner=COVER-400/learned-safe-ceiling
"""COVER-400: первый Style Edit-prompt не должен упираться в лимит.

Наблюдение прода (30 ч, 5/5 первых попыток): `nano-gpt.com/qwen-image-3-pro`
(`image_api`) отклоняет полный EDIT-prompt 968 символов как too long, а
сжатое mandatory-ядро 759 символов принимает 2xx. Learned safe ceiling
(`runtime_safe`, НЕ provider exact) писался только в TTL-кеш capabilities
(`_DEFAULT_TTL_SECONDS` = 900 с), поэтому после истечения TTL каждый новый
job снова шёл с лимитом `unknown` и снова отправлял полный prompt.

Проверяем два свойства:
1. learned ceiling переживает истечение TTL-кеша capabilities;
2. при известном learned ceiling полный P0+P1, не влезающий в потолок, сразу
   компилируется в уже проверенное mandatory-ядро (без платного 400), а
   exact/manual лимиты по-прежнему дают честный `prompt_limit_exceeded`.
"""

from __future__ import annotations

from services import cover_style_jobs as cjobs
from services import image_capabilities as cap

PROVIDER = "nano-gpt.com"
BASE_URL = "https://nano-gpt.com/api"
MODEL = "qwen-image-3-pro"
ROUTE = "image_api"

# Наблюдение прода: 968 → 400 «prompt is too long», 759 → 2xx.
OBSERVED_REJECTED = 968
OBSERVED_ACCEPTED = 759

LONG_INSTRUCTION = (
    "Перерисуй обложку в стиле плотного редакционного коллажа: сохрани "
    "композицию, лица и свет исходного кадра, добавь бумажную фактуру и "
    "аккуратные тени. Палитра сдержанная, тёплая, с приглушённым контрастом "
    "и мягким зерном по краям. Заголовок держи крупно, по левой трети, "
    "выключка по левому краю, межбуквенный интервал плотный. Фон под текстом "
    "чуть притемни градиентом, чтобы буквы читались без обводки. Второстепенные "
    "подписи собери мелким кеглем в две колонки под заголовком. Фотографию "
    "не кадрируй сильнее исходной, не меняй позы людей и не добавляй новых "
    "персонажей. Цветокоррекция: тёплые света, холодные тени, аккуратный "
    "баланс белого, без пересветов на коже. Детализируй ткань, волосы и "
    "мелкие блики, но не превращай кадр в пластиковую CGI-картинку. "
    "Сохрани читаемость мелкого текста на исходных элементах и не добавляй "
    "водяных знаков, рамок, штампов и посторонних логотипов."
)


def _profile():
    return {
        "profile_id": "cover400", "name": "Cover400",
        "pipeline_mode": "generate_then_edit",
        "instruction": LONG_INSTRUCTION,
        "counter_enabled": False, "counter_value": 0,
        "counter_format": "Выпуск {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 1,
        "enabled": True,
        "references": [],
    }


def _caps_learned(value=OBSERVED_ACCEPTED):
    return cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit(value=value, unit=cap.UNIT_CHARS,
                                     source=cap.SOURCE_RUNTIME_SAFE))


def _caps_exact(value):
    return cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit(value=value, unit=cap.UNIT_CHARS,
                                     source=cap.SOURCE_INTERNAL))


def test_learned_ceiling_survives_capability_cache_ttl(monkeypatch):
    """TTL истёк → learned safe ceiling всё равно применяется к резолву."""
    cap.reset_cache()
    try:
        cap.record_runtime_safe_ceiling(
            PROVIDER, BASE_URL, MODEL, ROUTE, OBSERVED_ACCEPTED,
            cap.UNIT_CHARS, only_raise=True)

        # Имитируем реальное истечение TTL-кеша capabilities (900 с).
        monkeypatch.setattr(cap, "_ttl", lambda: -1.0)
        got = cap.resolve_capabilities(PROVIDER, BASE_URL, MODEL,
                                       route=ROUTE,
                                       operation=cap.OPERATION_EDIT)
        assert got.prompt_limit.value == OBSERVED_ACCEPTED
        assert got.prompt_limit.source == cap.SOURCE_RUNTIME_SAFE
        assert cap.prompt_limit_source_taxonomy(got.prompt_limit.source) \
            == cap.TAXONOMY_LEARNED_SAFE_CEILING
        # learned ceiling НЕ выдаётся за точный максимум провайдера.
        assert cap.prompt_limit_is_exact(
            cap.prompt_limit_source_taxonomy(got.prompt_limit.source)) is False

        # Другой route не наследует чужой потолок.
        other = cap.resolve_capabilities(PROVIDER, BASE_URL, MODEL,
                                         route="image_edits",
                                         operation=cap.OPERATION_EDIT)
        assert other.prompt_limit.value != OBSERVED_ACCEPTED
    finally:
        cap.reset_cache()


def test_first_compile_degrades_to_proven_core_under_learned_ceiling():
    """Первый compile под learned ceiling не равен 968 и не «exceeded»."""
    full_unknown = cjobs.compile_style_prompt(
        _profile(), issue_display="Выпуск 42",
        capabilities=cap.conservative_unknown())
    assert len(full_unknown.prompt) > OBSERVED_ACCEPTED, \
        "сценарий воспроизводится: полный prompt длиннее наблюдённого потолка"

    compiled = cjobs.compile_style_prompt(
        _profile(), issue_display="Выпуск 42",
        capabilities=_caps_learned())

    assert getattr(compiled, "exceeded", False) is False
    assert len(compiled.prompt) <= OBSERVED_ACCEPTED, \
        "первый prompt обязан влезать в learned safe ceiling"
    assert len(compiled.prompt) != len(full_unknown.prompt)
    report = compiled.edit_report
    assert report.get("preflight_degraded") == "learned_safe_ceiling"
    assert report.get("degraded_limit") == OBSERVED_ACCEPTED
    assert report.get("final_chars") == len(compiled.prompt)

    # Деградация — ровно то mandatory-ядро, которое уже принималось провайдером.
    core = cjobs.compile_style_prompt(
        _profile(), issue_display="Выпуск 42",
        capabilities=_caps_learned(), retry_core=True)
    assert compiled.prompt == core.prompt


def test_exact_limit_keeps_honest_overflow_without_paid_call():
    """Published exact лимит: overflow остаётся честным, без деградации."""
    compiled = cjobs.compile_style_prompt(
        _profile(), issue_display="Выпуск 42",
        capabilities=_caps_exact(300))
    assert compiled.exceeded is True
    assert compiled.reason == "prompt_limit_exceeded"
    assert "preflight_degraded" not in (getattr(compiled, "edit_report", {})
                                        or {})
