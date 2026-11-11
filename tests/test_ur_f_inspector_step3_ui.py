"""UR-F шаг 3 (контракт §5): UI инспектора хода — карточки, подписи, мобильный.

Проверяется ровно то, что видит владелец на вкладке «Что бот видел»:

  * четыре карточки с русскими названиями и прежним каркасом
    (`data-turn-stage="l1|tools|writer|delivery"`, сетка `grid gap-2
    md:grid-cols-2`) — секция не перестроена;
  * приёмка §5 размещена в нужных карточках: кто отвечал/кому (source +
    алиасы), часы хода со стадиями, бюджет одной строкой, счётчики
    «доступно/вошло», блоки вертикальными строками с датами в поясе чата и
    ссылками на id, отдельный список «не вошло, потому что …», свои реплики
    «не образец стиля», решение о поиске словами (+код моно), ссылки
    «заголовок → адрес», правила стиля «сработало правило: имя · причина»;
  * расшифровка кодов (UR-20): словари block-kind (включая MAP/Branch/Anchor/
    TTL), ops, решений/итогов поиска, статусов/видов/причин правил стиля;
    неизвестный код → «код: <значение>», не голый токен;
  * пустота и усечение: `null`/`stages.*=false` → «нет данных (трасса старше
    версии)», `truncated` объясняется словами;
  * сворачивание длинных списков (блоки >5, ссылки >3, правила >4) и
    мобильная вёрстка: без таблиц, без `truncate` на id/датах, без
    горизонтального скролла на 390 px.

Живая часть (Playwright) прогоняется через существующий инструмент волны
`tools/ui_urf_visual_e2e.py --only-inspector` на 1440×900 и 390×844.

TEST-LIFECYCLE: CONTRACT owner=UR-F (§5 UI), source=ur-f-inspector-contract.md.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
TOOL = ROOT / "tools" / "ui_urf_visual_e2e.py"

INSPECTOR_START = INDEX.index("data-turn-inspector")
SECTION = INDEX[INSPECTOR_START:INDEX.index("</template>", INDEX.index(
    "data-turn-unavailable", INSPECTOR_START))]

CARD_TITLES = ("Планирование (L1)", "Инструменты и поиск", "Что видел ответ",
               "Операции и доставка")


def _code_block(name):
    """Фрагмент словаря/метода app.js от объявления до закрывающей `}`."""
    at = APP_JS.index(name)
    depth = 0
    for index in range(at, len(APP_JS)):
        char = APP_JS[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return APP_JS[at:index + 1]
    raise AssertionError("не найден блок " + name)


class TestCards:
    """Каркас и названия карточек (не перестраиваем секцию)."""

    def test_four_cards_in_order(self):
        positions = [SECTION.index(title) for title in CARD_TITLES]
        assert positions == sorted(positions), "порядок карточек изменён"
        assert len(positions) == 4

    def test_stage_anchors_kept(self):
        for stage in ("l1", "tools", "writer", "delivery"):
            assert 'data-turn-stage="%s"' % stage in SECTION

    def test_grid_unchanged(self):
        assert "grid gap-2 md:grid-cols-2" in SECTION, \
            "сетка карточек §5 не должна меняться"

    def test_no_tables(self):
        assert "<table" not in SECTION, "§5: без таблиц"

    def test_no_truncate_on_ids_and_dates(self):
        assert not re.search(r'class="[^"]*\btruncate\b', SECTION), \
            "§5: никакого truncate на id/датах"

    def test_navigation_untouched(self):
        # Переключатель ходов и кнопка обновления остаются прежними.
        assert 'data-turn-selector' in SECTION
        assert 'data-turn-btn="n"' in SECTION
        assert "loadTurnDiagnostics(true)" in SECTION


class TestAcceptancePlacement:
    """Данные приёмки лежат в своих карточках (§5 п.1–4)."""

    def test_source_lines(self):
        assert "turnSourceWho(turnDiag.source)" in SECTION
        assert "turnSourceReply(turnDiag.source)" in SECTION
        assert "отвечал:" in _code_block("turnSourceWho: function")
        assert "в ответ на:" in _code_block("turnSourceReply: function")
        assert "не ответ на сообщение" in _code_block("turnSourceReply: function")

    def test_clock_stages_line(self):
        assert "turnClockStagesLine(" in SECTION
        assert "часы поданы на этапах" in _code_block(
            "turnClockStagesLine: function")

    def test_budget_one_line(self):
        block = _code_block("turnBudgetLine: function")
        for part in ("окно модели", "запас на ответ", "из бюджета", "режим:"):
            assert part in block

    def test_counts_line(self):
        block = _code_block("turnCountsLine: function")
        assert "доступно сообщений" in block
        assert "вошло в запрос" in block

    def test_blocks_rows_with_dates_and_refs(self):
        block = _code_block("turnBlockRows: function")
        assert "dates:" in block and "refs:" in block and "tokens:" in block
        assert "приоритет вытеснения" in SECTION, \
            "role — приоритет вытеснения, подписан честно"

    def test_dropped_list(self):
        assert "не вошло, потому что" in SECTION
        assert "turnDroppedLines(" in SECTION

    def test_self_outputs_disclaimer(self):
        assert re.search(r"не\s+образец\s+стиля", SECTION), \
            "свои реплики подписаны как НЕ образец стиля"
        assert "turnSelfOutputLines(" in SECTION

    def test_search_words_and_code(self):
        assert "turnSearchDecisionWord(" in SECTION
        assert 'class="font-mono text-gray-500"' in SECTION, \
            "код решения о поиске — рядом, моно"
        assert "поиск не дал ссылок" in SECTION

    def test_links_title_arrow_address(self):
        assert "turnLinkTitle(link)" in SECTION
        assert "→" in SECTION and "link.source_url" in SECTION
        assert "дата публикации не сообщается источником" in _code_block(
            "turnLinkWhen: function")

    def test_style_rules(self):
        assert "turnRuleLine(rule)" in SECTION
        assert "сработало правило" in _code_block("turnRuleLine: function")
        assert "причина:" in _code_block("turnRuleLine: function")
        # Текста правил и секретов в UI нет — только id/статус/причина.
        block = _code_block("turnRuleLine: function")
        assert "rule.detail" not in block
        assert "rule.text" not in block


class TestCodeDictionaries:
    """Расшифровка внутренних кодов (UR-20) — в словарях рядом с хелперами."""

    def test_block_kinds_have_labels(self):
        block = _code_block("block: {")
        for kind, label in (
                ("global_tail", "свежие сообщения"),
                ("global_middle", "подобранные сообщения"),
                ("episode", "старые эпизоды"),
                ("rag", "память, факты"),
                ("global_head", "конспект"),
                ("thread", "ветка ответов"),
                ("protected", "защищённые факты"),
                ("sandwich", "напоминание")):
            assert "%s: '%s'" % (kind, label) in block, kind

    def test_contract_short_names(self):
        block = _code_block("block: {")
        assert "MAP: 'карта участников'" in block
        assert "Branch: 'ветка ответов'" in block
        assert "Anchor: 'привязка к сообщению'" in block
        assert "TTL: 'срок жизни записи'" in block

    def test_ops_and_search_and_rules(self):
        assert "l2_scrubber:" in _code_block("ops: {")
        assert "required: 'поиск обязателен'" in _code_block(
            "search_decision: {")
        assert "beneficial: 'поиск полезен'" in _code_block(
            "search_decision: {")
        assert "not_applicable: 'поиск не нужен'" in _code_block(
            "search_decision: {")
        assert "repaired:" in _code_block("rule_status: {")
        assert "kind_handler_absent:" in _code_block("rule_reason: {")

    def test_trace_id_explained(self):
        assert "код хода (служебный, по нему собрана трасса)" in SECTION

    def test_unknown_code_fallback(self):
        assert "TURN_UNKNOWN_CODE = 'код: '" in APP_JS
        block = _code_block("function turnCodeText(")
        assert "TURN_UNKNOWN_CODE + String(code)" in block, \
            "неизвестный код не выводится сырым токеном"
        # Единственный путь «код → текст» прокинут в методы компонента.
        assert "turnCodeLine: function" in APP_JS


class TestHonestEmptiness:
    """`null`/`stages.*=false` → «нет данных», никогда 0 вместо «неизвестно»."""

    def test_no_data_phrase(self):
        assert "var TURN_NO_DATA = 'нет данных (трасса старше версии)'" \
            in APP_JS
        # Поля без значения рендерятся этим словосочетанием, а не нулём.
        for method in ("turnBudgetLine: function", "turnCountsLine: function",
                       "turnSourceWho: function"):
            assert "TURN_NO_DATA" in _code_block(method), method

    def test_missing_stage_helper(self):
        block = _code_block("turnMissing: function")
        assert "stages[kind] === false" in block
        assert "TURN_NO_DATA" in block

    def test_truncated_explained_in_words(self):
        block = _code_block("turnTruncNote: function")
        assert "показаны первые" in block
        assert "truncated !== true" in block, \
            "обычный ход не показывает тревожный флаг"


class TestCollapsing:
    """Длинные списки сворачиваются; пороги закреплены в шаблоне."""

    def test_thresholds(self):
        assert "var TURN_LIST_LIMITS = { blocks: 5, links: 3, rules: 4 };" \
            in APP_JS
        assert "'blocks', 5" in SECTION
        assert "'links', 3" in SECTION
        assert "'rules', 4" in SECTION

    def test_show_more_buttons(self):
        assert SECTION.count("показать") >= 3
        assert "data-turn-more-blocks" in SECTION
        assert "data-turn-more-links" in SECTION
        assert "data-turn-more-rules" in SECTION

    def test_local_state_only(self):
        block = _code_block("turnToggleMore: function")
        assert "turnDiagOpen" in block
        assert "localStorage" not in block, "состояние не сохраняется навсегда"


class TestMobileFirst:
    """Мобильная вёрстка: перенос длинных значений, никакого h-скролла."""

    def test_wrap_css(self):
        assert "[data-turn-inspector] .turn-wrap" in CSS
        marker = CSS.index("[data-turn-inspector] .turn-wrap")
        rule = CSS[marker:CSS.index("}", marker)]
        assert "overflow-wrap: anywhere" in rule
        assert "min-width: 0" in rule

    def test_rows_are_flex_columns(self):
        assert SECTION.count("flex flex-col") >= 4, \
            "строки блоков/ссылок — flex-col (§5)"

    def test_date_and_id_not_truncated(self):
        # Даты печатаются целиком форматом «dd.mm hh:mm».
        block = _code_block("function turnShortWhen(")
        assert "day: '2-digit'" in block and "minute: '2-digit'" in block
        assert "return ''" in block, "нет валидной даты — пусто, а не 1970"

    def test_single_column_below_768(self):
        # Одну колонку даёт сам Tailwind-каркас `md:grid-cols-2`.
        assert "md:grid-cols-2" in SECTION
        prebuilt = (ROOT / "web" / "static" / "vendor" / "tailwind.css"
                    ).read_text(encoding="utf-8")
        assert "@media (min-width:768px){.md\\:col-span-2" in prebuilt


class TestAcceptanceGaps:
    """Доработка шага 3: дата родителя, дата конспекта, модели L1/L2, часы.

    Раньше карточка не могла показать: (1) время сообщения, на которое
    отвечали — даты не было в событии; (2) дату конспекта — блок
    `global_head` приходил без дат и без ссылок; (3) модель/слот L2 — в UI
    была только модель L1; (4) локальное время и смещение часов — только
    IANA и UTC-инстант."""

    def test_reply_parent_time_rendered_like_author_line(self):
        block = _code_block("turnSourceReply: function")
        assert "reply_to_ts" in block, "дата родителя читается из проекции"
        assert "turnWhen(" in block, "формат тот же, что у строки автора"
        assert "в ответ на:" in block
        assert "письмо" not in block and "text" not in block, \
            "текст сообщения родителя в UI не подставляется"

    def test_summary_block_note(self):
        block = _code_block("turnSummaryNote: function")
        assert "конспект до " in block
        assert "диапазон" in block
        assert "единого id источника" in block
        # Ссылки (реальные id) приоритетнее: конспект без id — отдельная
        # ветка, а не подмена.
        assert "refs" in block
        assert "data-turn-block-summary" in SECTION

    def test_model_lines_both_stages(self):
        assert "turnL1ModelLine()" in SECTION
        assert "turnL2ModelLine()" in SECTION
        assert "data-turn-model-l1" in SECTION
        assert "data-turn-model-l2" in SECTION
        l1 = _code_block("turnL1ModelLine: function")
        assert "слот не зафиксирован" in l1, \
            "старая трасса без поля — честная фраза остаётся"
        assert "turnCodeText('slot', l1.slot)" in l1, \
            "известный слот рендерится подписью, а не сырым кодом"
        assert "fallback" in l1 and "запас на ответ" in l1
        assert "модель не зафиксирована" in l1, "пустота названа словами"
        l2 = _code_block("turnL2ModelLine: function")
        assert "отправлено max output tokens" in l2
        assert "max_output_tokens_sent" in l2, \
            "показывается фактически отправленный предел генерации"
        assert "модель не зафиксирована" in l2

    def test_clock_line_has_local_time_offset_and_stages(self):
        block = _code_block("turnClockLine: function")
        for part in ("clock.timezone", "местное время", "UTC ",
                     "timezone_source", "turnClockStagePresence"):
            assert part in block, part
        assert "clock.as_of_utc" in block, "инстант часов остаётся в строке"
        helper = _code_block("function turnLocalStamp(")
        assert "timeZoneName: 'longOffset'" in helper
        assert "day: '2-digit'" in helper and "minute: '2-digit'" in helper
        presence = _code_block("turnClockStagePresence: function")
        assert "часы на этапах" in presence
        assert "stage" in presence


class TestLiveViewports:
    """Живой прогон: 1440×900 и 390×844 (Playwright, существующий инструмент)."""

    def _run_tool(self, tmp_path):
        pytest.importorskip("playwright")
        assert TOOL.exists(), "нет инструмента визуального прогона волны"
        out = tmp_path / "urf"
        proc = subprocess.run(
            [sys.executable, str(TOOL), "--only-inspector", "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            timeout=300)
        combined = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0 and (
                "playwright install" in combined.lower()
                or "executable doesn't exist" in combined.lower()):
            pytest.skip("браузер Playwright не установлен в этом окружении")
        assert proc.returncode == 0, combined[-3000:]
        report = json.loads((out / "urf-visual-report.json")
                            .read_text(encoding="utf-8"))
        return out, report

    def test_mobile_and_desktop(self, tmp_path):
        out, report = self._run_tool(tmp_path)
        for label, single_column in (("inspector3-mobile-390", True),
                                     ("inspector3-desktop-1440", False)):
            data = report[label]
            assert data["titles"] == list(CARD_TITLES), label
            assert not data["hScroll"], "%s: горизонтальный скролл" % label
            assert not data["clipped"], "%s: обрезанный текст" % label
            assert data["truncateClass"] == 0, label
            assert data["collapsedByDefault"], "%s: списки не свёрнуты" % label
            after = data["afterExpand"]
            assert (after["blocks"], after["links"], after["rules"]) == (7, 4, 6)
            assert not after["hScroll"], "%s: h-скролл после раскрытия" % label
            assert data["hasUnknownFallback"], \
                "%s: неизвестный код показан не как «код: …»" % label
            assert data["unexplained"] == [], \
                "%s: сырой код без подписи" % label
            # ── Доработка шага 1: реальные строки карточек (UR-20.4…20.8)
            src_line = data["sourceLine"]
            assert "в ответ на:" in src_line
            assert re.search(r"сообщение \d+, \d{2}\.\d{2} \d{2}:\d{2}\)",
                             src_line), "%s: дата родителя: %r" % (label, src_line)
            clock_line = data["clockLine"]
            assert "Europe/Moscow" in clock_line
            assert "местное время" in clock_line, clock_line
            assert re.search(r"\(\+\d{2}:\d{2}\)", clock_line), \
                "%s: смещение пояса: %r" % (label, clock_line)
            assert "2026-11-06T12:00:00+00:00" in clock_line
            assert "часы на этапах:" in clock_line
            l1_line = data["modelL1"]
            assert "L1: модель test-model-8b" in l1_line, l1_line
            assert "слот: выделенный планировщик (l1_slot)" in l1_line, l1_line
            assert "fallback: test-model-8b-fallback" in l1_line
            assert "запас на ответ 12 800" in l1_line
            l2_line = data["modelL2"]
            assert "L2: api.example / test-model-8b" in l2_line, l2_line
            assert "основной ответ (direct.primary)" in l2_line
            assert "отправлено max output tokens: 4 096" in l2_line
            summaries = data["blockSummaries"]
            assert summaries, "%s: строка конспекта не отрендерена" % label
            assert "конспект до " in summaries[0], summaries[0]
            assert "диапазон:" in summaries[0]
            rects = data["cardRects"]
            assert len(rects) == 4
            lefts = {row["left"] for row in rects}
            if single_column:
                assert len(lefts) == 1, "%s: карточки не в одну колонку" % label
            else:
                assert len(lefts) == 2, "%s: карточки не в две колонки" % label
        assert report["console_error_count"] == 0, report["console_errors"]
        # Снимки доказательств реально созданы (не «пустой прогон»).
        for name in ("urf-inspector-step3-collapsed-mobile-390.png",
                     "urf-inspector-step3-collapsed-desktop-1440.png",
                     "urf-inspector-step3-writer-mobile-390.png"):
            assert (out / name).exists(), name
            assert (out / name).stat().st_size > 5000, name
