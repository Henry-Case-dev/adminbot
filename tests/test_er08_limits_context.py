"""ER-08 (02.11.2026) — реальные потери контекста L1, семантика лимитов и
дедлайнов, видимость неизвестной цены.

Класс: CONTRACT/REGRESSION. Каждый тест отвечает на конкретный пункт решения
владельца (`plans/owner_inputs/2026-11-02-limits-economics-decision.md`):

1. L1-пакет: исходное сообщение, цитата (reply), адресация и claim'ы в ХВОСТЕ
   длинных сообщений доезжают до планера; бюджет — из Model Capacity Resolver,
   а не из код-константы.
2. `metered_calls` — счётчик инструментов, не денег: read-only проверка фактов
   не блокируется «финансовой экономией», анти-петлевые гварды живут.
3. Дедлайн Direct Orchestrator не обрывает работу раньше tool-цепочки.
4. Неизвестная цена показывается как неизвестная (`price_known=false` +
   `unknown_rows`), а не как ноль.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

W19_TAIL = "ENDOFMSG19"
W20_TAIL = "CLAIMINSHORTMSG"
REPLY_TAIL = "CLAIMINQUOTE"
MSG_TAIL = "TAILMARK_QUEST"

#: Смысловой контрдовод в СЕРЕДИНЕ длинной реплики (не маркер в хвосте):
#: именно такие фразы раньше не доезжали до планера.
COUNTER_MID = "но на самом деле в 1017 нет функции X, это переименование"
#: Высокорисковый claim (существующий детектор `evidence_policy._high_risk`:
#: версия в трёх компонентах). Такой claim середина обязана достать ПЕРВЫМ.
RISK_CLAIM = "версия 1.2.3 не поддерживает функцию X."


def _quote_3000():
    """Цитата 3000 символов с высокорисковым claim'ом на позиции ~1500."""
    head = ("начало цитаты о версии " * 200)[:1490]
    tail = ("дальше идут подробности " * 200)[:3000 - 1490 - len(RISK_CLAIM) - 2]
    return head + " " + RISK_CLAIM + " " + tail


def _dense_rows(n=20, total=4096, gap=200):
    """Плотное высокорисковое окно (фикстура ревьюера B2): claim каждые ~gap."""
    rows = []
    for i in range(1, n + 1):
        parts: list[str] = []
        size = 0
        while size < total - 40:
            parts.append(("рассуждение " * (gap // 12))[:gap])
            parts.append(RISK_CLAIM)
            size = sum(len(p) for p in parts)
        body = " ".join(parts)[:total - 20] + f" ХВОСТ{i}"
        rows.append(_row(i, body))
    return rows


class _FakeUser:
    """Минимальный Telegram-user для пути `_l1_reply_block`."""

    def __init__(self, uid=705, first_name="Аня"):
        self.id = uid
        self.first_name = first_name
        self.username = None


class _FakeReply:
    def __init__(self, text):
        self.text = text
        self.caption = None
        self.from_user = _FakeUser()


class _FakeMessage:
    """Сообщение с цитатой — тот же контракт, что читает боевой код."""

    def __init__(self, reply_text):
        self.reply_to_message = _FakeReply(reply_text) if reply_text else None


def _real_reply_stats(quote: str, budget: int) -> dict:
    """Оси доставки цитаты ЧЕРЕЗ РЕАЛЬНУЮ сборку (ревью B1).

    ``DirectChatService._l1_reply_block`` → ``build_l1_context`` →
    ``reply_delivery_stats``. Именно этот путь раньше врал: в ``total``
    попадал уже срезанный блок, поэтому ``truncated`` всегда был ``False``."""
    from services import direct_l1 as l1
    from services.direct_chat_service import DirectChatService

    service = DirectChatService.__new__(DirectChatService)
    service.aliases = None
    message = _FakeMessage(quote)
    block = service._l1_reply_block(message, budget_tokens=budget)
    total = service._l1_reply_total_chars(message)
    ctx = l1.build_l1_context(query="q", reply_block=block, speaker="Аня",
                              budget_tokens=budget)
    return l1.reply_delivery_stats(ctx, budget, total_chars=total)


def _quote_with_centre(sentence: str, total: int = 5000) -> str:
    """Цитата, где ``sentence`` стоит РОВНО в центре (границы — по точкам)."""
    pos = total // 2 - len(sentence) // 2
    head = ("фраза первая. " * 900)[:pos]
    tail = ("дальше общий текст. " * 900)[: max(0, total - pos
                                               - len(sentence) - 1)]
    return head + sentence + " " + tail


def _mid_counter_row(total=755, pos=325):
    """Реплика с контрдоводом в СЕРЕДИНЕ (позиция ``pos`` из ``total``)."""
    head = ("контекст " * (pos // 9))[:pos]
    tail = ("подробности " * 80)[: max(0, total - pos - len(COUNTER_MID) - 1)]
    return _row(19, head + " " + COUNTER_MID + " " + tail)


def _full_window_with_mid_counter():
    """20-строчное окно: все реплики обычные, у 19-й контрдовод в середине."""
    rows = [_row(i, (f"реплика {i}: " + "разговор " * 200)[:500])
            for i in range(1, 19)]
    rows.append(_mid_counter_row())
    rows.append(_row(20, ("обсуждаем " * 50)[:420]))
    return rows


def _set_hot(monkeypatch, value):
    """Подменить hot-ключ пакета L1 (``None`` → ключ не задан, динамика)."""
    from services import hot_config as hot

    real_get = hot.get

    def _get(key, default=None):
        if key == "limits.direct_l1_context_tokens":
            return value
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", _get)


def _row(i, text, author="Аня"):
    return {"id": i, "author_name": author, "text": text, "user_id": 100 + i}


def _window(row_chars=500):
    rows = []
    for i in range(1, 15):
        rows.append(_row(i, (f"реплика {i}: " + "разговор " * 200)[:row_chars]))
    for i in range(15, 19):
        rows.append(_row(i, (f"реплика {i}: " + "обсуждаем " * 200)[:row_chars]))
    # 19: 700 символов, claim и контрдовод В КОНЦЕ (типичный контрдовод)
    rows.append(_row(19, ("контекст " * 60)
                     + " но на самом деле в 1017 нет функции X "
                     + ("подробности " * 10) + " " + W19_TAIL))
    # 20: 430 символов, claim в конце
    rows.append(_row(20, ("обсуждаем версию " * 30)[:400] + " " + W20_TAIL))
    return rows


def _reply(chars=760):
    return ("начало цитаты " * 60)[:chars - 30] + " " + REPLY_TAIL + " хвост"


def _message():
    return ("Длинное рассуждение пользователя. " * 55) + " Итог: " + MSG_TAIL


# ── 1. L1: реальные потери пакета ──────────────────────────────────────────

class TestL1PackageLosses:

    def test_window_line_tail_survives_static_floor(self):
        """REGRESSION: при прежнем фиксированном бюджете (1600 токенов) claim в
        ХВОСТЕ длинной реплики раньше терялся (головной срез `[:cap]`).
        Сценарий: 20 строк, cap строки = 200 (пол), claim на ~650-м символе."""
        from services import direct_l1 as l1

        ctx = l1.build_l1_context(query="q", window=_window(), speaker="Аня",
                                  addressee="Борис", budget_tokens=1600)
        assert l1.window_line_chars(_window(), budget_tokens=1600) == \
            l1.L1_WINDOW_LINE_CHARS          # пол сохранён — это не правка пола
        assert W19_TAIL in ctx, "claim/контрдовод в хвосте реплики не доехал"
        assert W20_TAIL in ctx

    def test_reply_block_tail_survives(self):
        """REGRESSION: цитата 760 символов при старом капе 400 символов теряла
        claim на ~740-м символе (головной срез)."""
        from services import direct_l1 as l1

        ctx = l1.build_l1_context(query="q", reply_block=_reply(),
                                  speaker="Аня", budget_tokens=1600)
        assert REPLY_TAIL in ctx
        body = ctx.split(f"[{l1.L1_REPLY_SECTION}]\n", 1)[1]
        assert len(body) > l1.L1_REPLY_BLOCK_CHARS

    @pytest.mark.asyncio
    async def test_quote_3000_keeps_counterargument_at_1500(self):
        """ФИКСТУРА РЕВЬЮЕРА (a), ER-08-RC P1: цитата 3000 символов с
        контрдоводом на позиции 1500. Прежний фиксированный кап 1200 доставлял
        голову 720 + хвост 480 — позиция 1500 попадала в выброшенную середину,
        и контрдовод не доезжал даже на бюджете из окна модели. Теперь потолок
        цитаты — производная бюджета (до 4096 = предел сообщения Telegram)."""
        from services import direct_l1 as l1
        from services.token_counter import count_tokens

        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash", fallback_model="deepseek-v4-flash")
        assert meta["source"] == "model_window"
        quote = ("начало цитаты о версии " * 200)[:1490] + " " + RISK_CLAIM \
            + " " + ("дальше идут подробности " * 200)
        quote = quote[:3000]
        assert quote.index(RISK_CLAIM) == 1491
        assert l1.reply_block_chars(budget) > l1.L1_REPLY_BLOCK_CHARS

        ctx = l1.build_l1_context(query="q", reply_block=quote, speaker="Аня",
                                  budget_tokens=budget)
        assert RISK_CLAIM in ctx, "контрдовод из середины цитаты не доехал"
        assert count_tokens(ctx) <= budget

    @pytest.mark.asyncio
    async def test_twenty_4096_replies_stay_in_budget_and_keep_quote(self):
        """ФИКСТУРА РЕВЬЮЕРА (b), ER-08-RC P1/P3: 20 реплик по 4096 символов.
        Пакет остаётся в бюджете на всех трёх краях, цитата не выпадает, и
        первая/последняя реплики доезжают (окно не схлопывается)."""
        from services import direct_l1 as l1
        from services.token_counter import count_tokens

        rows = []
        for i in range(1, 21):
            suffix = f" ХВОСТ{i}"
            body = ((f"реплика {i}: " + "рассуждение " * 500).ljust(4096)
                    )[:4096 - len(suffix)] + suffix
            assert len(body) == 4096
            rows.append(_row(i, body))
        quote = _quote_3000()
        assert len(quote) == 3000 and quote.index(RISK_CLAIM) == 1491

        for budget in (1600, 5400, 112737):
            ctx = l1.build_l1_context(query="q", current_question="вопрос",
                                      reply_block=quote, window=rows,
                                      speaker="Аня", budget_tokens=budget)
            tokens = count_tokens(ctx)
            assert tokens <= budget, f"бюджет {budget}: пакет {tokens}"
            assert RISK_CLAIM in ctx, f"бюджет {budget}: цитата потеряна"
            assert "ХВОСТ20" in ctx, f"бюджет {budget}: последняя реплика потеряна"
            assert "реплика 20" in ctx
            # Класс-C константы не тронуты (не «расширение», а доставка).
            assert l1.L1_WINDOW_MESSAGES == 20
            assert l1.L1_MESSAGE_CHARS_MAX == 8192
            assert l1.L1_CLIP_CHARS_MAX == 4096
            # Стоимость пакета ограничена физически: 20 сообщений Telegram по
            # 4096 символов, для русского текста ≥2 символа на токен.
            assert tokens <= 20 * l1.L1_CLIP_CHARS_MAX // 2

    def test_memory_hint_tail_survives_pressure(self):
        """Релевантные факты (срез bundle «КОНТЕКСТ ДИАЛОГА (не терять)»):
        ограничения/уроки стоят в КОНЦЕ блока — при сжатии хвост не теряется."""
        from services import direct_l1 as l1

        hints = ("КОНТЕКСТ ДИАЛОГА (не терять):\nАдресат: Борис\n"
                 + "факт " * 400 + "\n- УРОК_ХВОСТ")
        rows = [_row(i, ("реплика %d: " % i + "обсуждаем " * 100)[:700])
                for i in range(1, 20)]
        ctx = l1.build_l1_context(
            query="q", current_question=_message(), reply_block=_reply(),
            window=rows, speaker="Аня", memory_hints=hints,
            persona_frame="характер " * 45, budget_tokens=1200)
        assert "УРОК_ХВОСТ" in ctx
        assert "Адресат: Борис" in ctx

    def test_message_tail_reaches_planner(self):
        """Исходное сообщение: хвост (вопрос/итог) обязан доезжать."""
        from services import direct_l1 as l1

        ctx = l1.build_l1_context(query="q", current_question=_message(),
                                  speaker="Аня", budget_tokens=1600)
        assert MSG_TAIL in ctx

    @pytest.mark.asyncio
    async def test_plain_counterargument_at_1500_of_quote_is_delivered_5400(
            self):
        """ДИСКРИМИНИРУЮЩИЙ КЕЙС (ревью §6.1): цитата 3000, ОБЫЧНАЯ фраза
        (не высокорисковая — `_high_risk` её не ловит) на позиции 1500, бюджет
        5400. На базе кап цитаты был 1200 (голова 720 + хвост 480): позиция 1500
        попадала в выброшенную середину и фраза НЕ доезжала. Здесь доезжает
        именно благодаря середине среза (кап 2160, середина 25 % вокруг центра),
        то есть тест различает базу и кандидата."""
        from services import direct_l1 as l1
        from services.evidence_policy import _high_risk

        # Детектор берём из evidence_policy, а не из direct_l1: на базе
        # 613fae5d `l1._high_risk` не существует, и тест падал бы
        # AttributeError вместо честного «база теряет фразу» (ревью R2.4).
        assert _high_risk(COUNTER_MID) is False, "фраза должна быть НЕ риск"
        head = ("начало цитаты о версии " * 200)[:1490]
        tail = ("дальше идут подробности " * 200)[:3000 - 1490
                                                  - len(COUNTER_MID) - 2]
        quote = head + " " + COUNTER_MID + " " + tail
        assert len(quote) == 3000
        assert 1490 <= quote.index(COUNTER_MID) <= 1495

        assert l1.reply_block_chars(5400) == 2160
        ctx = l1.build_l1_context(query="q", reply_block=quote, speaker="Аня",
                                  budget_tokens=5400)
        assert COUNTER_MID in ctx, "обычный контрдовод из середины не доехал"

    @pytest.mark.asyncio
    async def test_mid_message_counterargument_reaches_middle_window(
            self, monkeypatch):
        """ПОЗИТИВНАЯ ГАРАНТИЯ СЕРЕДИНЫ (ER-08-RC P2): контрдовод из СЕРЕДИНЫ
        длинной реплики доезжает до планера, когда кап строки даёт середине
        место (окно 20 строк, cap = 0.12×бюджета; середина = 25 % среза вокруг
        центра текста). Замер фикстуры: реплика 755 симв., контрдовод
        325-364.

        ЧЕСТНАЯ ОГОВОРКА (ревью §6.1): на бюджете 5400 эта же фраза доезжала и
        на базе — головой (кап 1200 → голова 720 > 325). Поэтому кейс НЕ
        доказывает исправление, он лишь страхует от удаления середины
        (мутация «вырезать середину» его валит). Доказательство — соседний
        `test_plain_counterargument_at_1500_of_quote_is_delivered_5400`, который
        на базе падает.

        Честная граница ОСТАВЛЕНА: на полу капа 200 (static-1600) середина
        занимает 48 символов и не дотягивается до позиции 325 — это цена
        ручного капа. См. следующий тест: высокорисковый claim на той же
        позиции доезжает и на полу (claim-first), обычная фраза — нет."""
        from services import direct_l1 as l1

        rows = _full_window_with_mid_counter()
        assert len(rows) == 20
        assert COUNTER_MID in rows[-2]["text"]

        _set_hot(monkeypatch, 1600)
        static_budget, static_meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash", fallback_model="deepseek-v4-flash")
        assert static_budget == 1600 and static_meta["source"] == "hot"
        assert l1.window_line_chars(rows, budget_tokens=static_budget) == 200
        ctx_static = l1.build_l1_context(query="q", window=rows,
                                        speaker="Аня",
                                        budget_tokens=static_budget)
        assert COUNTER_MID not in ctx_static     # честная граница пола капа

        # Тот же путь, но кап строки даёт середине место (бюджет 5400).
        ctx_wide = l1.build_l1_context(query="q", window=rows, speaker="Аня",
                                      budget_tokens=5400)
        assert COUNTER_MID in ctx_wide, "середина среза не доехала"

        _set_hot(monkeypatch, None)              # живой путь: динамика
        live_budget, live_meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash", fallback_model="deepseek-v4-flash")
        assert live_meta["source"] == "model_window"
        assert live_budget > 20000
        ctx_live = l1.build_l1_context(query="q", window=rows, speaker="Аня",
                                       budget_tokens=live_budget)
        assert COUNTER_MID in ctx_live           # на живом бюджете — доезжает

    @pytest.mark.asyncio
    async def test_high_risk_claim_outside_centre_is_pulled_claim_first(
            self, monkeypatch):
        """CLAIM-FIRST (ER-08-RC P2): высокорисковый claim (существующий
        детектор `evidence_policy._high_risk`) доезжает даже тогда, когда он
        стоит ДАЛЕКО от центра длинной реплики и за пределами головы среза:
        середина добирает его атомарно (бюджет середины ≤ 320 симв.).

        Честная граница: та же позиция с ОБЫЧНОЙ (не высокорисковой) фразой не
        доставляется — иначе «середина гарантирована» превратилась бы в ложь."""
        from services import direct_l1 as l1

        filler = [_row(i, (f"реплика {i}: " + "разговор " * 200)[:400])
                  for i in range(1, 20)]

        def rows_with(text):
            return filler + [_row(20, text)]

        long_row_claim = ("фраза первая. " * 40)[:300] + RISK_CLAIM + " " \
            + ("дальше общий текст. " * 200)
        long_row_plain = ("фраза первая. " * 40)[:300] + " " + COUNTER_MID \
            + " " + ("дальше общий текст. " * 200)
        assert l1.window_line_chars(rows_with(long_row_claim),
                                    budget_tokens=1600) == 200

        ctx_claim = l1.build_l1_context(query="q",
                                        window=rows_with(long_row_claim),
                                        speaker="Аня", budget_tokens=1600)
        assert RISK_CLAIM in ctx_claim, "claim-first не дотянулся до claim'а"

        ctx_plain = l1.build_l1_context(query="q",
                                        window=rows_with(long_row_plain),
                                        speaker="Аня", budget_tokens=1600)
        assert COUNTER_MID not in ctx_plain       # честная граница: не claim

    def test_dense_high_risk_window_keeps_all_replies(self):
        """РЕГРЕССИЯ B2 (ревью): плотное высокорисковое окно не теряет РЕПЛИКИ.

        Фикстура ревьюера: 20 реплик по 4096 символов, высокорисковое
        предложение каждые ~200 символов. На базе 613fae5d при 1600/2000/2600
        доезжали все 20 реплик (2000/240/312 симв. на строку). Кандидат с
        безлимитным claim-first раздувал строку до 294 симв., шаг 0 упирался в
        пол 200, и шаг 1 выбрасывал старые реплики (10 и 5 из 20).

        Инвариант: claim-first не выходит за кап строки, поэтому число
        доставленных реплик не ниже базы, а строка не длиннее капа (+префикс
        автора)."""
        from services import direct_l1 as l1
        from services.token_counter import count_tokens


        rows = _dense_rows()
        for budget in (1600, 2000, 2600):
            line_cap = l1.window_line_chars(rows, budget_tokens=budget)
            ctx = l1.build_l1_context(query="q", window=rows, speaker="Аня",
                                      budget_tokens=budget)
            assert count_tokens(ctx) <= budget
            delivered = set(re.findall(r"ХВОСТ(\d+)", ctx))
            assert len(delivered) == 20, (
                f"бюджет {budget}: доехало {len(delivered)} из 20 реплик")
            block = ctx.split("[ПОСЛЕДНИЕ СООБЩЕНИЯ]\n", 1)[1].split(
                "\n\n[", 1)[0]
            longest = max(len(line) for line in block.splitlines())
            # +5 — префикс «Аня: », который добавляется к срезу строки.
            assert longest <= line_cap + 5, (
                f"бюджет {budget}: строка {longest} длиннее капа {line_cap}")

    def test_reply_section_protected_under_hint_pressure(self):
        """Переполнение: сжимается ОКНО, а не цитата; claim в цитате выживает,
        окно при этом честно теряет строки (счётчик «ГРАНИЦА ИСТОРИИ»)."""
        from services import direct_l1 as l1

        rows = [_row(i, ("реплика %d: " % i + "обсуждаем " * 100)[:700])
                for i in range(1, 20)] + [_row(20, "обсуждаем " * 100)]
        ctx = l1.build_l1_context(
            query="q", current_question=_message(), reply_block=_reply(),
            window=rows, speaker="Аня",
            memory_hints=("память: " + "факт " * 400)[:2000],
            persona_frame="характер " * 45, budget_tokens=1600)
        assert REPLY_TAIL in ctx
        window_part = ctx.split("[ПОСЛЕДНИЕ СООБЩЕНИЯ]\n", 1)
        delivered = (len(window_part[1].split("\n\n[", 1)[0].splitlines())
                     if len(window_part) > 1 else 0)
        assert delivered < len(rows)
        assert "[ГРАНИЦА ИСТОРИИ]" in ctx

    @pytest.mark.asyncio
    async def test_full_window_claim_reaches_planner_with_derived_budget(self):
        """ГЛАВНОЕ: бюджет из реального окна модели (Model Capacity Resolver)
        → в полном 20-строчном окне claim'ы в хвостах доезжают до планера."""
        from services import direct_l1 as l1
        from services.token_counter import count_tokens

        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash",
            mandatory_tokens=count_tokens("систем промпт " * 200))
        assert budget > l1.L1_CONTEXT_FLOOR_TOKENS
        assert meta["source"] == "model_window"
        assert meta["context_window"] >= 131072
        assert l1.window_line_chars(_window(), budget_tokens=budget) > \
            l1.L1_WINDOW_LINE_CHARS
        ctx = l1.build_l1_context(
            query="q", current_question=_message(), reply_block=_reply(),
            window=_window(), speaker="Аня", addressee="Борис",
            budget_tokens=budget)
        for marker in (MSG_TAIL, W19_TAIL, W20_TAIL, REPLY_TAIL):
            assert marker in ctx
        # Бюджет — реальная граница пакета, а не «сколько влезло».
        assert count_tokens(ctx) <= budget
        assert "Адресат: Борис" in ctx

    @pytest.mark.asyncio
    async def test_budget_shrinks_with_small_model_window(self, monkeypatch):
        """Тот же резолвер: маленькое окно модели → меньший бюджет, но не ниже
        прежнего пола (правка не ухудшает чистую установку)."""
        from config.settings import Settings
        from services import direct_l1 as l1
        from services import model_capacity as capacity

        monkeypatch.setattr(Settings, "CHAT_MODEL_CONTEXT_WINDOW", 5000)
        capacity.invalidate_capacity_cache()
        capacity._WINDOW_CACHE.clear()
        try:
            budget, meta = await l1.resolve_l1_context_budget(
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash")
            # Окно 5000 → доступный вход ≈ 3.4k токенов (reserve вывода 1024 +
            # safety) — меньше, чем на 131k, и не ниже прежнего пола.
            assert meta["context_window"] == 5000
            assert l1.L1_CONTEXT_FLOOR_TOKENS <= budget < 5000
        finally:
            capacity.invalidate_capacity_cache()
            capacity._WINDOW_CACHE.clear()

    @pytest.mark.asyncio
    async def test_explicit_operator_cap_is_highest_priority(self, monkeypatch):
        """Явный hot-ключ оператора остаётся высшим приоритетом (ручное
        решение не перебивается динамикой) — пока он НИЖЕ окна модели."""
        from services import direct_l1 as l1

        _set_hot(monkeypatch, 2400)
        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash")
        assert budget == 2400 and meta["source"] == "hot"
        assert budget < meta["available_input_budget"]
        assert "clamped_by_window" not in meta

    @pytest.mark.asyncio
    async def test_hot_above_model_window_is_clamped_by_window(self, monkeypatch):
        """F-4 ревью: hot-значение выше окна модели НЕ пробивает окно.

        Было: floor = max(1600, hot) → при hot=200000 и окне 131072 итоговый
        бюджет = 200000 (запрос больше окна модели). Стало: бюджет = доступный
        вход модели, hot авторитетен только ниже окна; факт клампа виден в
        `clamped_by_window`."""
        from services import direct_l1 as l1

        _set_hot(monkeypatch, 200000)
        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash", fallback_model="deepseek-v4-flash",
            mandatory_tokens=400)
        available = meta["available_input_budget"]
        assert 0 < available <= 131072
        assert budget == available, "итог не может превышать вход модели"
        assert budget < 200000
        assert meta["source"] == "hot"
        assert meta.get("clamped_by_window") is True

    @pytest.mark.asyncio
    async def test_budget_never_exceeds_window_for_unknown_model(
            self, monkeypatch):
        """Тот же кламп на консервативном fallback-окне неизвестной модели:
        бюджет остаётся внутри 16384, даже если hot просит больше."""
        from services import direct_l1 as l1

        _set_hot(monkeypatch, 50000)
        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://example.invalid/v1",
            model="model-that-does-not-exist-xyz")
        assert meta["context_window"] <= 16384
        assert budget <= meta["available_input_budget"] <= 16384
        assert budget < 50000

    @pytest.mark.asyncio
    async def test_fallback_window_source_is_reported_honestly(self):
        """`source` не врёт: когда бюджет сужен fallback-моделью (композер не
        знает, кто ответит), пишется `model_window_fallback`, а не
        `model_window`."""
        from services import direct_l1 as l1

        budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-v4-flash", fallback_model="gpt-4-mini",
            mandatory_tokens=400)
        assert meta["source"] == "model_window_fallback"
        assert meta["fallback_model"] == "gpt-4-mini"
        assert budget == meta["available_input_budget"] < 20000

    def test_clip_body_does_not_cut_inside_url(self):
        """Срез не рвёт URL пополам (источник остаётся целым и в голове, и в
        хвосте); длина может вырасти на длину URL — это bounded."""
        from services import direct_l1 as l1

        url = "https://example.com/" + "a" * 120
        head_case = ("x" * 100) + " " + url + " " + ("y" * 400)
        assert url in l1.clip_body(head_case, 200)
        tail_case = ("y" * 400) + " " + url + " " + ("z" * 20)
        assert url in l1.clip_body(tail_case, 200)
        # Обычный текст по-прежнему укладывается в кап.
        assert len(l1.clip_body("a" * 1000, 200)) == 200

    def test_message_cap_from_budget_not_writer_800(self):
        """Исходное сообщение: кап L1 выводится из бюджета, а не берётся
        Writer-путь 800 символов."""
        from services import direct_l1 as l1

        assert l1.message_cap_chars(1600) == 3200
        assert l1.message_cap_chars(112000) == l1.L1_MESSAGE_CHARS_MAX
        long_message = ("слово " * 700)[:3900] + " " + MSG_TAIL
        ctx = l1.build_l1_context(query="q", current_question=long_message,
                                  speaker="Аня", budget_tokens=112000)
        assert long_message.strip() in ctx

    def test_live_path_passes_derived_budget(self):
        """AST-проверка живой проводки: оба L1-сайта передают бюджет, а
        прямой путь — и кап исходного сообщения из него."""
        text = (ROOT / "services/direct_chat_service.py").read_text(
            encoding="utf-8")
        plan = text[text.index("async def _plan_direct_l1"):]
        plan = plan[:plan.index("async def _attach_l1_plan_meta")]
        assert "await _l1.resolve_l1_context_budget(" in plan
        assert "budget_tokens=_l1_budget" in plan
        assert "cap_chars=_l1.message_cap_chars(_l1_budget)" in plan
        init = text[text.index("async def plan_initiative_decision"):]
        init = init[:init.index("async def generate_initiative_reply")]
        assert "await _l1.resolve_l1_context_budget(" in init
        assert "budget_tokens=_init_budget" in init

    def test_reply_truncated_is_truthful_on_the_real_path(self):
        """B1 (ревью R2.2): `l1_reply_truncated` не врёт на ЖИВОМ пути.

        Производственный код подаёт в `reply_delivery_stats` уже срезанный
        блок, поэтому `total` обязан считаться от ИСХОДНОЙ цитаты
        (`message.reply_to_message.text`). Проверяем через реальную сборку:
        короткая цитата → `truncated=False` и `delivered == total`; цитата
        3000 при капе 640 (hot 1600) → `truncated=True` по краю A
        arch §6.2; та же цитата на живом бюджете → `truncated=False` (среза
        нет)."""
        short = "короткая цитата целиком"
        stats_short = _real_reply_stats(short, 1600)
        assert stats_short["truncated"] is False
        assert stats_short["delivered_chars"] == stats_short["total_chars"]
        # total — длина исходной цитаты с шапкой автора, а не среза.
        assert stats_short["total_chars"] >= len(short)

        edge_a = ("фраза первая. " * 900)[:3000]
        stats_edge = _real_reply_stats(edge_a, 1600)
        assert stats_edge["chars_cap"] == 640
        assert stats_edge["total_chars"] == len(edge_a) + len("автор: Аня\n")
        assert stats_edge["truncated"] is True, "край A: срез не отмечен"
        assert stats_edge["delivered_chars"] < stats_edge["total_chars"]
        assert stats_edge["kept_mid"] is True

        stats_live = _real_reply_stats(edge_a, 113085)
        assert stats_live["chars_cap"] == 4096
        assert stats_live["truncated"] is False, "на живом бюджете среза нет"
        assert stats_live["delivered_chars"] == stats_live["total_chars"]

    def test_centre_claim_does_not_eat_the_middle_share(self):
        """B3 (ревью R2.3): claim в ЦЕНТРЕ занимает место В доле середины, а
        не вместо неё.

        Прежняя ветка `if not any(centre inside)` не добавляла окно добора,
        когда claim накрывал центр: на живом бюджете доезжало 3064 вместо
        ~4090 (середина 39 вместо ~1020), на hot-1600 — 531 вместо ~630.
        Теперь доставка с claim'ом в центре равна доставке без него."""
        plain = "просто общий текст про текущую ситуацию."
        with_claim = _real_reply_stats(_quote_with_centre(RISK_CLAIM), 113085)
        without = _real_reply_stats(_quote_with_centre(plain), 113085)
        assert with_claim["chars_cap"] == without["chars_cap"] == 4096
        assert with_claim["kept_mid"] is True
        assert abs(with_claim["delivered_chars"]
                   - without["delivered_chars"]) <= 8
        # Доля середины используется целиком: ≥95 % капа, а не 75 %.
        assert without["delivered_chars"] >= int(0.95 * 4096)
        assert with_claim["delivered_chars"] >= int(0.95 * 4096)

        hot_claim = _real_reply_stats(_quote_with_centre(RISK_CLAIM), 1600)
        hot_plain = _real_reply_stats(_quote_with_centre(plain), 1600)
        assert hot_claim["chars_cap"] == hot_plain["chars_cap"] == 640
        assert abs(hot_claim["delivered_chars"]
                   - hot_plain["delivered_chars"]) <= 8
        assert hot_claim["delivered_chars"] >= int(0.95 * 640)

    def test_live_path_emits_reply_cap_axes(self):
        """ER-08-RC §3: шесть осей доставки цитаты проводятся на ОБОИХ L1-сайтах
        (Direct — через meta/plan_meta, инициатива — через существующий канал
        record_l1_diagnostics), и обе идут в `_l1_usage_plan_meta`."""
        text = (ROOT / "services/direct_chat_service.py").read_text(
            encoding="utf-8")
        keys = ("l1_reply_chars_cap", "l1_line_chars_cap",
                "l1_reply_total_chars", "l1_reply_delivered_chars",
                "l1_reply_truncated", "l1_kept_mid")
        plan = text[text.index("async def _plan_direct_l1"):]
        plan = plan[:plan.index("async def _attach_l1_plan_meta")]
        for key in keys:
            assert f'meta["{key}"]' in plan, f"{key} не доезжает до plan_meta"
        init = text[text.index("async def plan_initiative_decision"):]
        init = init[:init.index("async def generate_initiative_reply")]
        for key in keys:
            assert f"{key}=" in init, f"{key} нет в инициативном L1-сайте"
        helper = text[text.index("def _l1_usage_plan_meta"):]
        helper = helper[:helper.index("def _l1_usage_diag")] \
            if "def _l1_usage_diag" in helper else helper[:4000]
        for key in keys:
            assert key in helper, f"{key} не проходит через _l1_usage_plan_meta"

    def test_plan_meta_exposes_effective_budget_and_source(self):
        """Durable-наблюдаемость (§8 «контракт замера»): эффективный лимит и
        его источник доезжают до usage-plan_meta."""
        from services import direct_l1 as l1
        from services import usage_events as ue
        from services.direct_chat_service import _l1_usage_plan_meta

        out = _l1_usage_plan_meta(
            l1.L1Plan(), {"l1_context_budget": 4096,
                          "l1_context_source": "model_window"},
            fallback_flag="", latency_ms=5, input_chars=100)
        safe = ue.sanitize_plan_meta(out)
        assert safe["l1_context_budget"] == 4096
        assert safe["l1_context_source"] == "model_window"
        assert {"l1_context_budget", "l1_context_source"} <= set(
            ue.PLAN_META_FIELDS)

    def test_reply_delivery_axes_are_present_and_truthful(self):
        """ER-08-RC §3 (ревью B1): шесть осей есть, они ПРАВДИВЫ и не несут
        текста.

        Короткая цитата → ``truncated=False`` и ``delivered == total``;
        длинная → ``truncated=True``, ``delivered < total``, ``kept_mid``
        отражает сохранённую середину среза. Те же числа принимает
        ``record_l1_diagnostics`` (Inspector), и весь набор проходит
        R17-whitelist `sanitize_plan_meta`."""
        from services import direct_l1 as l1
        from services import usage_events as ue
        from services.direct_chat_service import _l1_usage_plan_meta

        keys = ("l1_reply_chars_cap", "l1_line_chars_cap",
                "l1_reply_total_chars", "l1_reply_delivered_chars",
                "l1_reply_truncated", "l1_kept_mid")

        short = "короткая цитата целиком"
        ctx_short = l1.build_l1_context(query="q", reply_block=short,
                                        speaker="Аня", budget_tokens=1600)
        stats_short = l1.reply_delivery_stats(ctx_short, 1600,
                                              total_chars=len(short))
        assert stats_short["chars_cap"] == l1.reply_block_chars(1600) == 640
        assert stats_short["total_chars"] == len(short)
        assert stats_short["delivered_chars"] == stats_short["total_chars"]
        assert stats_short["truncated"] is False
        assert stats_short["kept_mid"] is False

        quote = _quote_3000()
        ctx_long = l1.build_l1_context(query="q", reply_block=quote,
                                       speaker="Аня", budget_tokens=1600)
        stats_long = l1.reply_delivery_stats(ctx_long, 1600,
                                             total_chars=len(quote))
        assert stats_long["truncated"] is True
        assert stats_long["delivered_chars"] < stats_long["total_chars"]
        assert stats_long["kept_mid"] is True
        assert stats_long["delivered_chars"] <= stats_long["chars_cap"]

        meta = {"l1_line_chars_cap": 200,
                "l1_reply_chars_cap": stats_long["chars_cap"],
                "l1_reply_total_chars": stats_long["total_chars"],
                "l1_reply_delivered_chars": stats_long["delivered_chars"],
                "l1_reply_truncated": stats_long["truncated"],
                "l1_kept_mid": stats_long["kept_mid"]}
        out = _l1_usage_plan_meta(l1.L1Plan(), meta, fallback_flag="",
                                  latency_ms=5, input_chars=100)
        safe = ue.sanitize_plan_meta(out)
        assert set(keys) <= set(safe)
        assert safe["l1_reply_truncated"] is True
        assert safe["l1_kept_mid"] is True
        assert safe["l1_reply_total_chars"] == stats_long["total_chars"]
        assert safe["l1_reply_delivered_chars"] == \
            stats_long["delivered_chars"]
        assert safe["l1_reply_chars_cap"] == stats_long["chars_cap"]
        assert safe["l1_line_chars_cap"] == 200
        # R17: в полях нет текста — только числа и bool.
        for key in keys:
            assert not isinstance(safe[key], str), f"{key} содержит текст"

        # Same axes in the existing Inspector channel (record_l1_diagnostics).
        from services import direct_l1 as _l1
        _l1.record_l1_diagnostics(987654, **{k: safe[k] for k in keys})
        stored = _l1.get_l1_diagnostics(987654) or {}
        for key in keys:
            assert stored.get(key) == safe[key]
        _l1._l1_diagnostics.pop(987654, None)


# ── 2. metered / деньги ────────────────────────────────────────────────────

class TestMeteredIsToolCounterNotMoney:

    def test_read_only_evidence_tools_are_not_cost_limited(self):
        from services import tool_loop

        for name in ("execute_web_search", "fetch_article", "fact_check"):
            assert name in tool_loop.METERED_TOOLS        # факт метричности
            assert tool_loop.cost_limited_tool(name) is False
        for name in ("generate_image", "edit_image", "summarize_video",
                     "transcribe_video", "recognize_image"):
            assert tool_loop.cost_limited_tool(name) is True

    def test_anti_loop_guards_still_present(self):
        """Защита сохранена: общий cap вызовов, раунды, один вызов ≤2 раза."""
        from services import tool_loop

        assert tool_loop.TOOL_MAX_TOTAL_CALLS == 6
        assert tool_loop._TOOL_MAX_SAME_CALL == 2
        assert tool_loop.TOOL_MAX_ROUNDS == 4
        assert tool_loop._TOOL_CALLS_PER_ROUND_MAX == 2

    @pytest.mark.asyncio
    async def test_chain_meta_reports_cost_calls_separately(self, monkeypatch):
        """`chain_meta` объясняет отказ числами: `metered` (факт метричности)
        и `cost_calls` («денежный» счётчик) — разные оси."""
        from services import direct_execution as de

        class _Router:
            def __init__(self):
                self.dispatched = []

            async def dispatch(self, name, arguments, ctx):
                self.dispatched.append(name)
                return f"данные:{name}"

        def _steps(*a, **kw):
            return ([{"step_id": f"s{i}", "tool": tool,
                      "arguments": {"q": f"v{i}"}, "depends_on": [],
                      "failure_policy": "optional"}
                     for i, tool in enumerate((
                         "execute_web_search", "fetch_article",
                         "generate_image", "summarize_video"))], [])

        monkeypatch.setattr(de, "derive_simple_steps", _steps)
        router = _Router()
        result = await de.run_simple_tools(
            plan=None, router=router, ctx=None, query="x", chat_id=1,
            correlation_id="corr",
            announced={"execute_web_search", "fetch_article",
                       "generate_image", "summarize_video"})
        assert len(router.dispatched) == 4
        assert result.chain_meta["metered"] == 4     # все 4 метричные
        assert result.chain_meta["cost_calls"] == 2  # только generate/summarize

    def test_money_limits_on_cannot_silently_block_evidence(self):
        """ГРАНИЦА: механизм денежных caps инертен (нет runtime-вызывающих) и
        при неизвестной цене не отказывает — включение флага не может молча
        срезать проверку фактов."""
        from config.settings import Settings
        from services import mca_money_limits as ml

        import_re = re.compile(
            r"^\s*(?:from|import)\s+.*mca_money_limits", re.MULTILINE)
        for path in (ROOT / "services").glob("*.py"):
            if path.name == "mca_money_limits.py":
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            assert not import_re.search(source), path.name
        assert Settings.MCA_MONEY_LIMITS_ENABLED is False
        # Механизм, вызванный вручную при неизвестной цене, не отказывает.
        decision = ml.check_and_reserve("direct", None, price_known=False)
        assert decision["allowed"] is True


# ── 3. Дедлайны ────────────────────────────────────────────────────────────


class TestOrchestratorEvidenceHeader:
    """№31: планировщику уходит структурный статус источника, а не только
    слепой 400-символьный срез текста."""

    def test_evidence_so_far_has_structural_status(self):
        from services import direct_execution as de

        src = de.EvidenceSource(
            tool="fetch_article", status="ok", content="x" * 2000,
            total_chars=2000, delivered_chars=400, truncated=True,
            delivered=True)
        messages = de._orchestrator_messages(
            query="q", allowlist=[], evidence_sources=[src], steps_done=[])
        body = messages[1]["content"]
        assert "status=ok" in body
        assert "delivered=400/2000" in body
        assert "truncated=yes" in body
        # Срез остаётся добавкой (untrusted-обёртка не сломана).
        assert "ДАННЫЕ ИНСТРУМЕНТА" in body

class TestDeadlines:

    def test_orchestrator_deadline_matches_tool_chain(self):
        """Аудит: оркестратор больше не обрывает работу на 90 с при tool-цепочке
        360 с (per-tool: поиск 25 + статья 45 = 70 с на шаг)."""
        from config.settings import Settings
        from services import direct_execution as de
        from services import tool_loop

        assert de.orchestrator_max_time_seconds() == \
            tool_loop._chain_timeout_seconds() == 360.0
        assert Settings.MCA_TOOL_CHAIN_TIMEOUT_SECONDS == 360.0

    def test_orchestrator_follows_chain_timeout_setting(self, monkeypatch):
        from config.settings import Settings
        from services import direct_execution as de

        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 180.0)
        assert de.orchestrator_max_time_seconds() == 180.0

    def test_orchestrator_explicit_override_kept(self, monkeypatch):
        from config.settings import Settings
        from services import direct_execution as de

        monkeypatch.setattr(
            Settings, "DIRECT_ORCHESTRATOR_MAX_TIME_SECONDS", 45.0,
            raising=False)
        assert de.orchestrator_max_time_seconds() == 45.0

    def test_chain_budget_uses_same_resolvers(self, monkeypatch):
        """ChainBudget (simple/adaptive) берёт те же значения, что tool_loop,
        а не собственные копии констант."""
        import time

        from config.settings import Settings
        from services import direct_execution as de

        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", 120.0)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", 5)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_METERED_CALLS", 3)
        budget = de.ChainBudget()
        assert budget.max_total == 5 and budget.max_metered == 3
        remaining = budget.deadline - time.monotonic()
        assert 110.0 < remaining <= 120.0


# ── 4. Видимость неизвестной цены ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_cost_group_marks_unknown_price(tmp_path):
    """Неизвестный тариф не превращается в ноль: сумма идёт только по
    `price_known`, а непрозрачные строки видны отдельным счётчиком."""
    from services import mca_events as me
    from services.database import DatabaseService

    d = DatabaseService(str(tmp_path / "er08.db"))
    await d.initialize()
    try:
        me.emit_mca_event("A", outcome=me.OUTCOME_SUCCESS, component="summary",
                          usage_json={"cost_usd": 0.25, "price_known": True})
        me.emit_mca_event("B", outcome=me.OUTCOME_SUCCESS, component="summary",
                          usage_json={"cost_usd": None, "price_known": False})
        await me.flush_events(d)
        m = await me.metrics(d)
        cost = m["metrics"]["cost"]
        assert cost["by_category"]["summary"] == 0.25
        assert cost["known_rows"] == 1 and cost["unknown_rows"] == 1
        assert cost["price_known"] is False
    finally:
        await d.close()
