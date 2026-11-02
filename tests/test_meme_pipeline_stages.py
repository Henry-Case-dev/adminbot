"""MEME-PIPELINE-REFactor-01 / P1 — три этапа мем-пайплайна и бюджет длины.

Контракт владельца (§1–§3, §5, §7 ТЗ; arch/integration-decisions.md §1–§5):

  * этап A — выжимка по окну БЕЗ потолка длины (ни цели, ни обрезки);
  * этап B — обязательный отдельный LLM-вызов «выжимка → короткий абсурдный
    прикол»; именно здесь работает потолок: ``J = max(0, L - T)`` уходит
    модели явной инструкцией, защитная обрезка — только страховка;
  * этап C — image prompt собирается из ШАБЛОНА и ПРИКОЛА (не выжимки);
  * журнал различает четыре этапа (summary/joke/image_generation/publish)
    с причинами пропуска/провала, шаблоном, посчитанным J и фактической
    длиной прикола — без новых колонок и без текстов прикола;
  * успех = только изображение; текст прикола не уходит в чат никогда;
  * ``manual=True`` обходит квоту/кулдаун/минимум сообщений/random/тихие
    часы/in-flight/гейт, но НЕ готовность image-модуля и наличие журнала.

Каждая проверка может упасть: суммы и длины считаются от реальных настроек,
подменены только внешние границы (LLM, image-провайдер, Telegram).

TEST-LIFECYCLE: CONTRACT owner=2026-11-03-meme-pipeline-refactor-01
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import initiative_observer as obs
from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import prompt_registry as pr

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
BUCKET = "2026-11-03"
PREFIX = meme.MEME_IMAGE_PROMPT
JOKE_PROMPT = "Придумай короткий абсурдный прикол из этой выжимки."
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}


# ── фикстуры и фейки (сеть и Telegram не используются) ──────────────────────

@pytest.fixture(autouse=True)
def _reset_ring():
    meme.reset_process_attempts()
    pr.reset_cache()
    yield
    meme.reset_process_attempts()
    pr.reset_cache()


def _ledger(tmp_path):
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme_stages.db"))
    led.apply_schema()
    return led


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=50, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _rows(chat_id: int, n: int = 5) -> list[dict]:
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


def _run(coro):
    return asyncio.run(coro)


class _Hit:
    def __init__(self, value=0.0):
        self.value = value

    async def draw_probability(self, **kwargs):
        return mrs.DrawResult(value=self.value, deferred=False,
                              fallback_reason=None, source="pseudorandom",
                              selected_source="quantum", draw_id="draw-1")


class _Provider:
    def __init__(self, *, ok=True, called=True, reason=""):
        self.ok = ok
        self.called = called
        self.reason = reason
        self.calls: list[tuple] = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=self.ok, called=self.called,
                               reason=self.reason, content=b"png")


class _Feed:
    """Один журнал событий на все фейки: порядок этапов доказуем."""

    def __init__(self, events=None):
        self.events: list[str] = events if events is not None else []
        self.summary_calls: list[tuple] = []
        self.joke_calls: list[tuple] = []

    def summarizer(self, text="хук"):
        feed = self

        async def _inner(chat_id, rows, system):
            feed.events.append("summary")
            feed.summary_calls.append((chat_id, rows, system))
            return text

        return _inner

    def joke(self, text="прикол"):
        feed = self

        async def _inner(chat_id, summary, instruction):
            feed.events.append("joke")
            feed.joke_calls.append((chat_id, summary, instruction))
            return text

        return _inner

    def joke_raises(self, exc=RuntimeError("llm down")):
        feed = self

        async def _inner(chat_id, summary, instruction):
            feed.events.append("joke")
            feed.joke_calls.append((chat_id, summary, instruction))
            raise exc

        return _inner


async def _ok_gate(_chat_id):
    return True, "ok"


async def _consider(tmp_path, chat_id=-100, *, feed=None, summarizer=None,
                    joke_generator=None, provider=None, gate=_ok_gate,
                    sender=None, ledger=None, settings=None,
                    messages=None, model_chars=200, prompt_override=None,
                    image_status=None, initiative_enabled=None, **kwargs):
    led = ledger if ledger is not None else _ledger(tmp_path)
    feed = feed if feed is not None else _Feed()
    provider = provider if provider is not None else _Provider()
    sent: list[tuple] = []

    async def _wrapped(prompt, cid, jid):
        feed.events.append("image")
        return await provider(prompt, cid, jid)

    async def _sender(cid, content, prompt):
        feed.events.append("publish")
        sent.append((cid, content, prompt))

    result = await meme.consider_chat(
        None, chat_id,
        settings=settings if settings is not None else _settings(),
        ledger=led, now=NOW, tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=initiative_enabled or (lambda: True),
        image_status=IMAGE_OK if image_status is None else image_status,
        random_source=_Hit(),
        messages=messages if messages is not None else _rows(chat_id),
        summarizer=summarizer if summarizer is not None
        else feed.summarizer(),
        joke_generator=joke_generator if joke_generator is not None
        else feed.joke(),
        image_provider=_wrapped, publish_gate=gate,
        sender=sender if sender is not None else _sender,
        model_chars=model_chars, prompt_override=prompt_override, **kwargs)
    feed.sent = sent
    return result, provider, led, feed


def _facts_by_stage(led, chat_id=-100) -> dict[str, dict]:
    """Разбор журнала одним штатным разборщиком (как витрина)."""
    out: dict[str, dict] = {}
    for row in led.attempts(chat_id):
        facts = meme.parse_attempt_facts(row)
        if facts:
            out[str(row["stage"])] = facts
    return out


# ── этап A: у выжимки больше нет потолка ───────────────────────────────────

def test_stage_a_summary_has_no_length_ceiling(tmp_path):
    """Окно из 40 реплик → полная выжимка в 3000 символов, без обрезки.

    Мутация: вернуть `target` в вызов суммаризатора или постфактум-обрезку —
    тест падает (либо TypeError на сигнатуре, либо короткая выжимка).
    """
    long_summary = "выжимка-маркер " * 200                # 3000 символов
    feed = _Feed()
    result, provider, led, feed = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer(long_summary),
        model_chars=120, messages=_rows(-100, n=40)))

    # Суммаризатор получил окно целиком и НЕ получил числовой цели.
    called_chat, called_rows, called_system = feed.summary_calls[0]
    assert called_chat == -100
    assert len(called_rows) == 40
    assert called_system == meme.MEME_SUMMARY_SYSTEM_PROMPT
    assert "уложись" not in called_system.casefold()      # инструкции потолка нет
    # Этап B получил выжимку ЦЕЛИКОМ (никакой обрезки на 120 символах).
    assert feed.joke_calls[0][1] == long_summary.strip()
    assert len(feed.joke_calls[0][1]) > 120
    facts = _facts_by_stage(led)
    assert facts["summary"]["chars"] == len(long_summary.strip())
    # Итоговый prompt ограничен потолком L, а не длиной выжимки.
    assert result.limit.ceiling == 120
    assert len(provider.calls[0][0]) <= 120
    assert result.published is True


# ── этап B: явная инструкция с точным N = J ─────────────────────────────────

def test_stage_b_instruction_carries_exact_j_budget(tmp_path):
    """L=800 из админской настройки, T = |шаблон| + 1, J = L - T дословно."""
    feed = _Feed()
    result, _, led, feed = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        settings=_settings(length_admin=800), model_chars=None))

    expected_t = len(PREFIX) + 1
    expected_j = 800 - expected_t
    instruction = feed.joke_calls[0][2]
    assert instruction.startswith(JOKE_PROMPT)
    assert f"Сгенерируй прикол длиной не более {expected_j} символов." \
        in instruction
    assert result.limit.ceiling == 800
    assert result.limit.template_chars == expected_t
    assert result.limit.joke_budget == expected_j
    assert result.limit.source == "admin_setting"
    facts = _facts_by_stage(led)["joke"]
    assert facts["limit"] == expected_j
    assert facts["template_chars"] == expected_t
    assert facts["ceiling"] == 800


def test_stage_b_budget_follows_effective_template_with_placeholder(tmp_path):
    """Шаблон с ``{joke}``: T считается без плейсхолдера, подстановка на место."""
    template = "{joke} — мем с шрифтом импакт"
    feed = _Feed()
    result, provider, led, feed = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        joke_generator=feed.joke("абсурдный прикол"),
        settings=_settings(length_admin=100), model_chars=None,
        prompt_override=template))

    expected_t = len(template) - len(meme.JOKE_PLACEHOLDER)
    expected_j = 100 - expected_t
    assert result.limit.placeholder == "slot"
    assert result.limit.template_chars == expected_t
    assert result.limit.joke_budget == expected_j
    assert f"не более {expected_j} символов" in feed.joke_calls[0][2]
    assert provider.calls[0][0] == "абсурдный прикол — мем с шрифтом импакт"
    assert meme.JOKE_PLACEHOLDER not in provider.calls[0][0]
    assert _facts_by_stage(led)["joke"]["placeholder"] == "slot"


# ── этап C: в промпт картинки идёт прикол, а не выжимка ─────────────────────

def test_stage_c_image_prompt_uses_joke_not_summary(tmp_path):
    summary = "СЫРАЯ-ВЫЖИМКА " * 20
    joke = "ПРИКОЛ-МАРКЕР про дедлайн"
    feed = _Feed()
    _, provider, _, _ = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer(summary),
        joke_generator=feed.joke(joke)))

    prompt = provider.calls[0][0]
    assert joke in prompt
    assert "СЫРАЯ-ВЫЖИМКА" not in prompt
    assert prompt == f"{PREFIX} {joke}"


# ── защитная обрезка: только страховка от перелёта ──────────────────────────

def test_protective_trim_only_when_model_overshoots(tmp_path):
    """Основной механизм — инструкция; обрезка срабатывает только на перелёте."""
    feed = _Feed()
    over = "слово " * 200                                  # 1200 символов
    result, provider, led, _ = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        joke_generator=feed.joke(over), model_chars=120))

    budget = result.limit.joke_budget
    prompt = provider.calls[0][0]
    assert len(prompt) <= 120                              # инвариант T+J<=L
    facts = _facts_by_stage(led)["joke"]
    assert facts["trimmed"] is True
    assert facts["chars"] <= budget
    assert facts["chars"] < len(over.strip())

    # Контроль: прикол в бюджете не режется вообще.
    feed2 = _Feed()
    exact = "короткий прикол"
    other = tmp_path / "ok"
    other.mkdir()
    result2, provider2, led2, _ = _run(_consider(
        other, feed=feed2, summarizer=feed2.summarizer("хук"),
        joke_generator=feed2.joke(exact), model_chars=120))
    assert provider2.calls[0][0] == f"{PREFIX} {exact}"
    assert _facts_by_stage(led2)["joke"]["trimmed"] is False
    assert result2.prompt == f"{PREFIX} {exact}"


# ── четыре различимых этапа в журнале ──────────────────────────────────────

def test_four_stage_rows_carry_template_budget_and_joke_length(tmp_path):
    feed = _Feed()
    result, provider, led, _ = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        joke_generator=feed.joke("прикол"), model_chars=200))

    rows = {str(row["stage"]): row for row in led.attempts(-100)}
    assert {"summary", "joke", "image_generation", "publish"} <= set(rows)
    facts = _facts_by_stage(led)
    assert facts["summary"]["chars"] == len("хук")
    assert facts["joke"]["chars"] == len("прикол")
    assert facts["joke"]["limit"] == result.limit.joke_budget
    assert facts["joke"]["ceiling"] == 200
    assert facts["joke"]["trimmed"] is False
    assert facts["joke"]["source"] == "factory"
    assert facts["image_generation"]["template_source"] == "factory"
    assert "meme-image-evol014" in facts["image_generation"][
        "template_revision"]
    assert facts["image_generation"]["chars"] == len(provider.calls[0][0])
    assert facts["publish"]["gate"] == "ok"
    assert facts["publish"]["manual"] is False
    # В журнале нет текстов прикола — только числа и лаконичные коды.
    for row in led.attempts(-100):
        assert "прикол" not in str(row.get("detail") or "")
    assert "joke" not in result.as_dict()      # текст не уходит в payload


def test_joke_failure_is_its_own_stage_and_costs_no_slot(tmp_path):
    """Провал B: свой код, провайдер не вызван, квота не потрачена."""
    feed = _Feed()
    result, provider, led, _ = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        joke_generator=feed.joke_raises()))

    assert result.stage == meme.STAGE_FAILED
    assert result.reason == meme.SKIP_JOKE_FAILED
    assert "RuntimeError" in result.detail
    assert provider.calls == []
    assert led.spent(-100, BUCKET) == 0
    rows = led.attempts(-100)
    assert {str(row["stage"]) for row in rows} >= {"summary", "failed"}
    failed = [row for row in rows if row["stage"] == meme.STAGE_FAILED][0]
    assert failed["reason_code"] == meme.SKIP_JOKE_FAILED
    assert meme.STAGE_JOKE not in {str(row["stage"]) for row in rows}


def test_zero_budget_and_empty_joke_are_distinct_skips(tmp_path):
    """J<=0 и пустой прикол — разные причины, LLM/провайдер не вызываются."""
    feed = _Feed()
    zero, provider, led, feed = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        model_chars=50, prompt_override="ш" * 200))
    assert zero.reason == meme.SKIP_NO_JOKE_BUDGET
    assert zero.limit.joke_budget == 0
    assert feed.summary_calls == []            # пропуск ДО платной выжимки
    assert provider.calls == []
    assert led.spent(-100, BUCKET) == 0

    feed2 = _Feed()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    empty, provider2, led2, _ = _run(_consider(
        empty_dir, feed=feed2, summarizer=feed2.summarizer("хук"),
        joke_generator=feed2.joke("   "), model_chars=200))
    assert empty.reason == meme.SKIP_JOKE_EMPTY
    assert empty.detail == "empty_joke"
    assert provider2.calls == []
    assert led2.spent(-100, BUCKET) == 0


# ── выдача: только изображение ─────────────────────────────────────────────

class _RecordingBot:
    """Фейковый бот: пишет КАЖДЫЙ исходящий вызов в порядке отправки."""

    def __init__(self):
        self.id = 4242
        self.calls: list[tuple] = []

    async def send_photo(self, chat_id, photo, **kwargs):
        self.calls.append(("photo", int(chat_id), photo, dict(kwargs)))
        return SimpleNamespace(message_id=100 + len(self.calls))

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("text", int(chat_id), str(text), dict(kwargs)))
        return SimpleNamespace(message_id=200 + len(self.calls))


def test_image_only_delivery_keeps_joke_and_prompt_internal(tmp_path):
    """Успех = ОДИН исходящий вызов: фото, без caption и без текста."""
    bot = _RecordingBot()
    sender = obs.InitiativeObserverRunner(None, bot=bot)._meme_sender()
    joke = "прикол-маркер про созвон"
    feed = _Feed()
    result, provider, _, _ = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        joke_generator=feed.joke(joke), sender=sender))

    assert result.published is True
    assert len(bot.calls) == 1, bot.calls
    kind, chat_id, _payload, kwargs = bot.calls[0]
    assert kind == "photo" and chat_id == -100
    assert "caption" not in kwargs
    assert [call for call in bot.calls if call[0] == "text"] == []
    assert joke not in str(bot.calls)
    assert PREFIX not in str(bot.calls)
    assert provider.calls[0][0] == f"{PREFIX} {joke}"


# ── manual=True: обход ограничений авто-инициативы ─────────────────────────

def test_manual_bypasses_quota_cooldown_activity_random_and_gate(tmp_path):
    """Квота 0 + кулдаун + мало сообщений + промах random + тихие часы +
    выключенные тумблеры + закрытый гейт → ручной запуск всё равно публикует."""
    led = _ledger(tmp_path)
    sealed = led.reserve(chat_id=-100, day_bucket=BUCKET, job_id="prev",
                         limit=3, tz_name="UTC", tz_source="utc_fallback",
                         now_ts=int(NOW.timestamp()) - 60)
    assert sealed.ok
    led.mark("prev", "provider_called")

    sent = []

    async def sender(chat_id, content, prompt):
        sent.append((chat_id, content))

    async def closed_gate(_chat_id):
        return False, "recheck_demoted"

    feed = _Feed()
    result, provider, _, _ = _run(_consider(
        tmp_path, ledger=led, feed=feed, summarizer=feed.summarizer("хук"),
        joke_generator=feed.joke("прикол"), gate=closed_gate, sender=sender,
        settings=_settings(enabled=False, daily_limit=0, cooldown_seconds=3600,
                           min_messages=99, quiet_hours="00:00-23:59"),
        messages=_rows(-100, n=1), model_chars=200, manual=True,
        initiative_enabled=lambda: False))

    assert result.published is True and result.reason == "sent"
    assert result.manually_triggered is True
    assert len(sent) == 1 and len(provider.calls) == 1
    facts = _facts_by_stage(led)["publish"]
    assert facts["manual"] is True
    assert facts["gate"] == "manual_bypass"
    # Квота дня не тронута: ручной запуск не создаёт бронь.
    assert led.status_counts(-100, BUCKET) == {"provider_called": 1}


def test_manual_keeps_image_and_schema_gates(tmp_path):
    """Ручной запуск не обходит физику: нет image backend/журнала — честный skip."""
    feed = _Feed()
    no_image, provider, _, _ = _run(_consider(
        tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
        model_chars=200, manual=True,
        image_status={"available": False, "reason":
                      meme.SKIP_IMAGE_NOT_CONFIGURED},
        initiative_enabled=lambda: False))
    assert no_image.reason == meme.SKIP_IMAGE_NOT_CONFIGURED
    assert provider.calls == []

    feed2 = _Feed()
    no_schema = _run(meme.consider_chat(
        None, -100, settings=_settings(enabled=False, daily_limit=0),
        ledger=None, now=NOW, tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=lambda: False, image_status=IMAGE_OK,
        messages=_rows(-100), summarizer=feed2.summarizer(),
        joke_generator=feed2.joke(), model_chars=200, manual=True))
    assert no_schema.reason == meme.SKIP_SCHEMA


# ── бюджет: единая функция для рантайма и витрины ──────────────────────────

@pytest.mark.parametrize("template, placeholders", [
    (PREFIX, 0),
    ("{joke} — мем", 1),
    ("{joke} мем {joke}", 2),
])
def test_budget_matrix_is_one_computation(template, placeholders):
    """L/T/J считает ОДНА функция; второго арифметического входа нет."""
    budget = meme.resolve_meme_budget(model_chars=400, admin=None,
                                      explicit=None, template=template)
    assert budget.placeholder == ("slot" if placeholders == 1 else
                                 ("append" if placeholders == 0 else "invalid"))
    assert budget.ceiling == 400
    assert budget.joke_budget == max(0, 400 - budget.template_chars)
    # Печать «шаблон без прикола» совпадает с фактической подстановкой пустого.
    assert len(meme.render_image_prompt(template, "")) == budget.template_chars
    # Второго имени для тех же чисел больше нет (обёртка витрины удалена в P2):
    # витрина зовёт resolve_meme_budget напрямую.
    assert not hasattr(meme, "resolve_length_limit")


def test_factory_prompts_are_exact_and_registered():
    """Дословные заводские тексты этапов A/B и целостность печатей реестра."""
    assert meme.MEME_JOKE_PROMPT == JOKE_PROMPT
    assert pr.factory_text(meme.JOKE_PROMPT_BLOCK_ID) == JOKE_PROMPT
    assert pr.factory_text(meme.SUMMARY_PROMPT_BLOCK_ID) == \
        meme.MEME_SUMMARY_SYSTEM_PROMPT
    assert pr.seal_integrity() == {}
    assert "потолок" not in meme.MEME_SUMMARY_SYSTEM_PROMPT.casefold()
    view = meme.active_prompt_view(meme.JOKE_PROMPT_BLOCK_ID,
                                   override="Придумай прикол про кота.")
    assert view["text"] == "Придумай прикол про кота."
    assert view["differs_from_factory"] is True


def test_prompt_layers_use_registry_pg_key(monkeypatch):
    """Чат-override → hot → заводской текст; ключ берётся из блока реестра.

    Мутация: читать промпт мимо слоёв (константа) — тест падает.
    """
    from types import SimpleNamespace

    from services import hot_config

    monkeypatch.setattr(pr, "block",
                        lambda block_id: SimpleNamespace(
                            block_id=block_id, pg_key="prompts.test_meme_joke"))
    chats: dict = {-100: "  чатовый прикол  "}
    global_layer: dict = {}

    async def _sourced(chat_id, key, default=None):
        """Штатный резолвер слоёв: override чата → глобальный слой."""
        assert key == "prompts.test_meme_joke"
        if int(chat_id) in chats:
            return chats[int(chat_id)], "chat"
        if key in global_layer:
            return global_layer[key], "global"
        return default, "factory"

    monkeypatch.setattr("services.chat_params.get_chat_param_sourced", _sourced)
    monkeypatch.setattr(hot_config, "get", lambda key, default=None: default)

    chat_view = _run(meme.effective_meme_prompt(
        -100, meme.JOKE_PROMPT_BLOCK_ID, factory=meme.MEME_JOKE_PROMPT))
    assert chat_view["text"] == "  чатовый прикол  "
    assert chat_view["source"] == "chat"

    # Пустой/пробельный чатовый слой не обнуляет промпт: дальше hot, затем заводской.
    chats[-100] = "   "
    hot_view = _run(meme.effective_meme_prompt(
        -100, meme.JOKE_PROMPT_BLOCK_ID, factory=meme.MEME_JOKE_PROMPT))
    assert hot_view["text"] == JOKE_PROMPT
    assert hot_view["source"] == "factory"

    del chats[-100]
    global_layer["prompts.test_meme_joke"] = "глобальный прикол"
    global_view = _run(meme.effective_meme_prompt(
        -100, meme.JOKE_PROMPT_BLOCK_ID, factory=meme.MEME_JOKE_PROMPT))
    assert global_view["text"] == "глобальный прикол"
    assert global_view["source"] == "global"      # слой различим, не «setting»
    assert global_view["differs_from_factory"] is True

    # Блок без pg_key каталога ничего не выдумывает — действует заводской текст.
    monkeypatch.setattr(pr, "block",
                        lambda block_id: SimpleNamespace(
                            block_id=block_id, pg_key=None))
    plain = _run(meme.effective_meme_prompt(
        -100, meme.JOKE_PROMPT_BLOCK_ID, factory=meme.MEME_JOKE_PROMPT))
    assert plain["text"] == JOKE_PROMPT
    assert plain["source"] == "factory"


def test_compact_facts_roundtrip_and_parse_guard():
    """Один разборщик фактов: JSON читается, текст причины — нет."""
    assert meme.compact_facts({}) == ""
    payload = {"limit": 100, "chars": 42, "trimmed": False}
    text = meme.compact_facts(payload)
    assert json.loads(text) == payload
    assert meme.parse_attempt_facts({"detail": text}) == payload
    assert meme.parse_attempt_facts({"detail": "recheck_demoted"}) == {}
    assert meme.parse_attempt_facts({"detail": "{битый json"}) == {}
    assert meme.parse_attempt_facts({"detail": ""}) == {}


def test_analytics_snapshot_exposes_joke_stage_without_texts(tmp_path):
    feed = _Feed()
    _run(_consider(tmp_path, feed=feed, summarizer=feed.summarizer("хук"),
                   joke_generator=feed.joke("прикол"), model_chars=200))
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme_stages.db"))
    snap = meme.analytics_snapshot(led, chat_id=-100)
    assert snap["counters"][meme.STAGE_JOKE] == 1
    assert snap["joke"] == {"attempts": 1, "avg_chars": float(len("прикол")),
                            "trimmed": 0}
    assert "прикол" not in json.dumps(snap, ensure_ascii=False)
