"""EVOL-001..005 — виджеты статуса: единая система строк, движение, окно записи.

Структурные (и один интеграционный на роут) проверки по
`plans/current_task.md` §1:

  EVOL-001 — один дизайн-набор строк на четыре источника («Новые факты»,
             «Убеждения (Сон)», «Парадигмы (Глубокий сон)», «Эволюция
             характера (Личность)»), названия разделов сохранены, длинный
             текст открывается целиком (обрезанного кликабельного хвоста нет);
  EVOL-002 — общая схема движения/ручной прокрутки (CSS-контейнер + JS-
             контроллер), legacy CSS-marquee не конкурирует;
  EVOL-003 — окно ТОЙ ЖЕ сущности: поля, раздельные даты, честное «нет
             данных», focus trap/возврат фокуса/блокировка фона;
  EVOL-004 — переход к первоисточнику (цепочка/трасса) и связанным записям
             ТОГО ЖЕ объекта; нет кнопок «в общий раздел»; причина недоступности
             внешней ссылки названа;
  EVOL-005 — дата/возраст строки, честные пустые состояния по фактической
             причине, подпись чата/области.

Плюс: аддитивная передача полей `graph_facts` в `/api/oversight/dossier_feed`
(даты/тип/полный текст/адрес первоисточника) и нулевой diff защищённой оптики.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import unicodedata
from pathlib import Path

import pytest

from web.api import oversight as ov

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
OVERSIGHT_PY = (ROOT / "web" / "api" / "oversight.py").read_text(encoding="utf-8")


def _section(start: str, end: str, text: str = INDEX) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


# ── EVOL-001: одна система строк на четыре источника ────────────────────────
class TestSharedRowSystem:
    def test_four_viewports_share_one_scheme(self):
        assert INDEX.count('v-sfeed="statusRecordOpen"') == 4, (
            "EVOL-002: все четыре источника используют один контроллер "
            "движения (одна директива на контейнер)")
        assert INDEX.count("data-sfeed-viewport") == 4

    def test_rows_are_whole_clickable_buttons(self):
        # Строка — одна кнопка: кликабельна вся площадь, обрезанного
        # «кликабельного хвоста» нет; полный текст — в окне записи.
        assert INDEX.count('class="sfeed-item"') == 4
        for src in ("fact", "belief", "paradigm", "trait"):
            assert ('data-sfeed-type="%s"' % src) in INDEX, src
        for src in ("'fact'", "'belief'", "'paradigm'", "'trait'"):
            assert ("openStatusRecord(%s" % src) in INDEX, src
        assert 'data-sfeed-row' in INDEX

    def test_section_titles_preserved(self):
        for title in ("Новые факты", "Что бот недавно запомнил",
                      "Убеждения", "Парадигмы", "Эволюция характера",
                      "Мониторинг Интеллекта"):
            assert title in INDEX, title

    def test_semantic_difference_is_label_only(self):
        # Различие источников — бейдж/подпись, а не отдельная вёрстка.
        for cls in ("sfeed-item__badge--fact", "sfeed-item__badge--belief",
                    "sfeed-item__badge--paradigm", "sfeed-item__badge--trait"):
            assert cls in INDEX, cls
            assert "." + cls in CSS, cls
        # Одинаковая высота окна и строки — один набор переменных.
        assert "--sfeed-row-h" in CSS and "--sfeed-h" in CSS
        assert re.search(r"\.sfeed-viewport \{[\s\S]{0,300}height: var\(--sfeed-h\)",
                         CSS), "EVOL-001: одна высота окна"
        assert re.search(r"\.sfeed-item \{[\s\S]{0,400}height: var\(--sfeed-row-h\)",
                         CSS), "EVOL-001: одна высота строки"

    def test_activity_highlight_and_fading_borders(self):
        assert 'data-sfeed-active' in APP_JS, "EVOL-001: подсветка активности"
        assert '.sfeed-item[data-sfeed-active="1"]' in CSS
        assert re.search(r"\.sfeed-viewport \{[\s\S]{0,700}mask-image: linear-gradient",
                         CSS), "EVOL-001: затухающие границы окна"

    def test_no_glass_layer_overlap(self):
        # Строки не создают новых слоёв/фильтров: только фон/границы.
        row_css = _section(".sfeed-item {", "}", CSS)
        for forbidden in ("backdrop-filter", "z-index", "position: absolute",
                          "url(#lg"):
            assert forbidden not in row_css, (
                "EVOL-001: строка не добавляет слой стекла (%s)" % forbidden)


# ── EVOL-002 (review-fix): РЕАЛЬНАЯ разметка «Новых фактов» ────────────────
class TestRealMarkupRowGeometry:
    """Блокер Reviewer: в реальном шаблоне «Новые факты» — единственная лента
    БЕЗ обёртки `.sfeed-track` (строки — прямые дети окна), и на контейнер
    действует legacy-правило `.status-facts .facts-list` с `display:flex`.
    Во flex-контейнере строка с `flex-shrink:1` сжималась с 64px до ~13px,
    текст факта получал высоту 0. Здесь проверяется настоящий фрагмент
    `index.html` (с предком `.status-facts`, без `.ribbon-track`) и CSS-
    каскад: строка не сжимается, legacy-правило не задаёт строке размеров.
    """

    @staticmethod
    def _facts_card() -> str:
        return _section(
            '<div v-if="isGlobalAdmin" class="card p-4 status-facts',
            "<!-- ═══ EVOL-003/004/005: модальное окно записи", INDEX)

    def test_real_markup_has_no_track_wrapper(self):
        card = self._facts_card()
        assert "status-facts" in card, "предок .status-facts — часть реальной разметки"
        assert "ribbon-track" not in card, (
            "в «Новых фактах» нет обёртки .sfeed-track: строки — прямые дети "
            "окна (именно поэтому сжатие flex-контейнера видно здесь)")
        assert 'class="facts-list scroll-thin sfeed-viewport"' in card
        assert "data-sfeed-viewport" in card
        assert 'class="sfeed-item" data-sfeed-row' in card
        assert "sfeed-item__text" in card, "текст факта — часть строки"

    def test_row_cannot_shrink_in_flex_container(self):
        row_css = _section(".sfeed-item {", "}", CSS)
        assert "flex: 0 0 var(--sfeed-row-h)" in row_css, (
            "EVOL-002: строка не сжимается и не растягивается — иначе во "
            "flex-контейнере «Новых фактов» 64px сжимаются до ~13px")
        assert "height: var(--sfeed-row-h)" in row_css

    def test_legacy_facts_rule_does_not_own_row_size(self):
        legacy = _section(".status-facts .facts-list {", "}", CSS)
        # Контейнеру нужна колоночная раскладка (строки — прямые дети), но
        # размеры строк задаёт только общий слой `.sfeed-*`.
        for forbidden in ("height", "max-height", "flex:", "flex-shrink",
                          "flex-basis"):
            assert forbidden not in legacy, (
                "legacy-правило не должно задавать размеры окна/строки: %s"
                % forbidden)
        assert "gap: var(--sfeed-gap)" in legacy, "шаг строк — общий токен"
        # Никаких правил, переопределяющих геометрию строки по этому предку.
        assert re.search(
            r"\.status-facts \.facts-list \.sfeed-item \{[^}]*"
            r"(flex|height)", CSS) is None, (
            "нет legacy-переопределений размера строки по предку .status-facts")



# ── EVOL-002: движение и ручная прокрутка ──────────────────────────────────
class TestMotionAndManualScroll:
    def test_container_is_real_scroller(self):
        assert re.search(r"\.sfeed-viewport \{[\s\S]{0,500}overflow-y: auto", CSS)
        assert re.search(r"\.sfeed-viewport \{[\s\S]{0,700}overscroll-behavior: contain",
                         CSS)

    def test_legacy_css_marquee_disabled_for_new_lists(self):
        assert ".ribbon-track.sfeed-track { animation: none !important; }" in CSS

    def test_controller_contract(self):
        for marker in ("pauseManual", "resumeMs", "setModal", "prefers-reduced-motion",
                       "MutationObserver", "ResizeObserver", "requestAnimationFrame"):
            assert marker in APP_JS, marker
        # Один экземпляр на контейнер (нет конкурирующих таймеров/слушателей).
        assert "el.__sfeed" in APP_JS
        # Ручные способы управления подписаны явно.
        for ev in ("'wheel'", "'touchstart'", "'keydown'", "'scroll'",
                   "'focusin'", "'mouseenter'"):
            assert ev in APP_JS, ev

    def test_reduced_motion_has_no_forced_animation(self):
        assert re.search(
            r"@media \(prefers-reduced-motion: reduce\) \{[\s\S]{0,400}"
            r"\.sfeed-viewport \{[^}]*mask-image: none !important", CSS)
        assert ".sfeed-item { transition: none !important; }" in CSS

    def test_no_artificial_movement_when_short(self):
        # Ядро: max<=0 → idle и y=0 (не двигаем искусственно).
        assert re.search(r"if \(s\.max <= 0\) \{[\s\S]{0,120}phase = 'idle'",
                         APP_JS)


# ── EVOL-003: окно записи той же сущности ──────────────────────────────────
class TestRecordModal:
    def test_modal_is_single_overlay_with_a11y(self):
        modal = _section("<!-- ═══ EVOL-003/004/005: модальное окно записи",
                         "<!-- ═══ F11 (§12/§19, ADR-1025-23 D1/D5): Строка 5",)
        assert 'role="dialog"' in modal
        assert 'aria-modal="true"' in modal
        assert 'aria-labelledby="sfeed-rec-title"' in modal
        assert 'tabindex="-1"' in modal
        assert 'data-sfeed-modal' in modal
        # Никакого нового окна браузера.
        assert "window.open" not in modal and 'target="_blank"' not in modal

    def test_close_paths_and_focus(self):
        assert '@click.self="closeStatusRecord()"' in INDEX, "клик вне окна"
        assert 'aria-label="Закрыть окно записи"' in INDEX, "явная кнопка"
        assert "if (this.statusRecordOpen) { this.closeStatusRecord(); return; }" \
            in APP_JS, "Esc закрывает верхний слой"
        assert "statusRecordReturnFocus" in APP_JS, "возврат фокуса"
        assert "statusRecordKeydown" in APP_JS, "focus trap (Tab)"
        assert "sfeed-modal-open" in INDEX and "sfeed-modal-open" in CSS, \
            "фоновая прокрутка заблокирована"

    def test_fields_and_distinct_dates(self):
        block = _section("_statusRecordFrom: function", "// Открытие модалки", APP_JS)
        for label in ("Полный текст", "Тип записи", "Чат / область", "Субъект",
                      "Связанный Telegram user id", "Записано (извлечение)",
                      "Дата события (сообщение)", "Подтверждено",
                      "Последнее обновление", "Происхождение", "Статус",
                      "Источники", "Изменения"):
            assert label in block, label
        # Смысл каждой даты различается и опирается на своё поле БД.
        for col in ("graph_facts.created_at", "graph_facts.message_timestamp",
                    "graph_facts.last_confirmed_at"):
            assert col in block, col
        assert block.count("push('updated_at'") == 1
        assert "missing: (value == null || value === '')" in block, \
            "EVOL-003: отсутствующее поле помечено отсутствующим"

    def test_missing_field_marker_in_markup(self):
        assert "rec-missing" in INDEX and ".rec-missing" in CSS
        assert "нет данных" in INDEX


# ── EVOL-004: первоисточник и связанные записи ─────────────────────────────
class TestSourceDrilldown:
    def test_drill_uses_object_specific_endpoints(self):
        assert "/api/memory/dream/chain?fact_id=" in APP_JS
        assert "/api/memory/attribution/trace?chat_id=" in APP_JS
        assert "data-rec-drill" in INDEX
        assert "data-rec-related" in INDEX
        assert "statusRecordRelatedList" in APP_JS and "statusRecordRelatedList" in INDEX
        assert "data-rec-dossier" in INDEX, "досье субъекта — конкретный объект"

    def test_no_generic_section_navigation_in_modal(self):
        modal = _section("<!-- ═══ EVOL-003/004/005: модальное окно записи",
                         "<!-- ═══ F11 (§12/§19, ADR-1025-23 D1/D5): Строка 5",)
        assert "shellNavTo(" not in modal, "нет кнопки «в общий раздел»"
        assert "navigateTo(" not in modal

    def test_external_link_reason_is_stated(self):
        assert "statusRecordTgNote" in APP_JS
        block = _section("statusRecordTgNote: function", "loadDossierFeed", APP_JS)
        assert "username" in block, "причина недоступности внешней ссылки названа"
        assert "недоступна" in block


# ── EVOL-005: дата/возраст и честные пустые состояния ──────────────────────
class TestDatesAndEmptyStates:
    def test_row_shows_date_and_exact_in_details(self):
        assert "statusRowDateLabel(it.created_at)" in INDEX
        assert "statusRowTitle(" in INDEX
        assert "statusRowDateLabel: function" in APP_JS
        assert "statusRowAgeLabel: function" in APP_JS

    def test_empty_state_by_real_cause(self):
        assert "statusFeedEmptyReason" in APP_JS
        block = _section("statusFeedEmptyReason: function",
                         "// EVOL-004: подпись якоря цепочки", APP_JS)
        assert "выключен настройкой" in block, "disabled ≠ empty"
        assert "задача ещё не наступала" in block
        assert "лента ещё не запрашивалась" in block, "empty ≠ не загружали"
        # Пробел назван честно, а не замаскирован выдуманной причиной.
        assert "не передаёт" in block
        # Ошибка загрузки — отдельное состояние с причиной.
        assert "data-sfeed-error" in INDEX
        assert "Не удалось загрузить ленту" in INDEX

    def test_scope_label_for_both_chats_and_global(self):
        block = _section("_statusScopeLabel: function", "// Нормализация записи", APP_JS)
        assert "Весь бот (GLOBAL)" in block, "global-admin режим подписан"
        assert "oversightData" in block and "accessChats" in block, \
            "подпись чата из существующих источников"
        assert "Чат ' + chatId" in block, "честный fallback по id"


# ── Роут: аддитивная передача полей graph_facts ────────────────────────────
class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    async def execute(self, sql, params):
        self.calls.append((sql, params))
        return _FakeCursor(self._rows)


class _FakeDB:
    """Стаб: `dossier_feed` (строки как из graph_facts) + provenance-чтение."""

    def __init__(self, rows, meta_rows=None):
        self._rows = rows
        self.db = _FakeConn(meta_rows or [])

    async def dossier_feed(self, limit=12, chat_id=None):
        return list(self._rows)

    async def get_active_participants(self, chat_id, since_ts, cap):
        return []


class _NoMetaDB(_FakeDB):
    """Провенанс-чтение падает (нет колонки/БД) → поля остаются null."""

    class _Boom:
        async def execute(self, *a, **k):
            raise RuntimeError("no such column")

    def __init__(self, rows):
        super().__init__(rows)
        self.db = self._Boom()


def _feed_row(**kw):
    row = {"chat_id": -100, "name": "Толян", "fact": "любит мемы",
           "id": 42, "kind": "fact", "created_at": 1000,
           "message_timestamp": 900, "last_confirmed_at": 1100}
    row.update(kw)
    return row


def _call_route(monkeypatch, db):
    monkeypatch.setattr(ov.lore_runtime, "get_lore_db", lambda: db)

    async def _build(chat_id):
        return None

    monkeypatch.setattr(ov.summary_aliases, "build_alias_resolver", _build)
    return asyncio.run(ov.dossier_feed(None, None, chat_id=None, limit=12))


class TestDossierFeedWiring:
    def test_passes_timestamps_text_and_provenance(self, monkeypatch):
        db = _FakeDB([_feed_row()],
                     meta_rows=[{"id": 42, "origin": "chat_history",
                                 "tg_message_id": 777,
                                 "attribution_method": "direct"}])
        body = _call_route(monkeypatch, db)
        item = body["items"][0]
        assert item["text"] == "любит мемы", "EVOL-003: полный текст"
        assert item["excerpt"] == "любит мемы"
        assert item["id"] == 42
        assert item["created_at"] == 1000
        assert item["message_timestamp"] == 900
        assert item["last_confirmed_at"] == 1100
        assert item["origin"] == "chat_history"
        assert item["tg_message_id"] == 777, "EVOL-004: адрес первоисточника"
        # Один read-only запрос на пачку, без записи и новых таблиц.
        assert len(db.db.calls) == 1
        assert "graph_facts" in db.db.calls[0][0]
        assert "INSERT" not in db.db.calls[0][0].upper()
        assert "UPDATE" not in db.db.calls[0][0].upper()

    def test_provenance_failure_is_fail_open(self, monkeypatch):
        body = _call_route(monkeypatch, _NoMetaDB([_feed_row()]))
        item = body["items"][0]
        assert item["tg_message_id"] is None
        assert item["origin"] is None
        assert item["text"] == "любит мемы", "остальные поля не теряются"

    def test_null_dates_stay_null(self, monkeypatch):
        db = _FakeDB([_feed_row(created_at=None, message_timestamp=None,
                                last_confirmed_at=None, id=None)])
        item = _call_route(monkeypatch, db)["items"][0]
        assert item["created_at"] is None and item["message_timestamp"] is None
        assert item["last_confirmed_at"] is None
        assert item["id"] is None
        assert db.db.calls == [], "без id provenance не читается"


# ── Защищённая визуальная основа не тронута ────────────────────────────────
PROTECTED = (
    "web/static/glass.js",
    "web/static/polygon-background.js",
    "web/static/aurora-flow.js",
)


@pytest.mark.parametrize("rel", PROTECTED)
def test_protected_optics_zero_diff(rel):
    proc = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel],
                          cwd=str(ROOT), capture_output=True)
    assert proc.returncode == 0, "EVOL: защищённая оптика не меняется (%s)" % rel


def test_no_new_backend_logic_or_ddl():
    # EVOL-005: роут только передаёт существующие поля; новых таблиц/DDL нет.
    assert "CREATE TABLE" not in OVERSIGHT_PY
    assert "ALTER TABLE" not in OVERSIGHT_PY
    assert "INSERT INTO" not in OVERSIGHT_PY
