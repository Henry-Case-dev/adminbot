"""mca-21-guides (round 10.48) — контент-фаза: покрытие матрицы T-5204 и
честность контента (spec §1 D4 / §2 D5-D6 / §4 D10 / §8 TH-1/TH-6, SC-R3c).

Проверки:
  * Г1 (plans/docs/intelligence_user_guide.md): новые разделы §12–§18 по
    матрице (самостоятельность, случайность, опыт, статистика, изображения,
    временной фактчек, наблюдаемость); «где смотреть» — реальные экраны;
  * Г2 (info_text.md): раздел «12. Распознавание изображений» — три
    примера-цитаты по образцу, без слеш-команд, имя персонажа — не триггер;
    честные пояснения (повтор/уточнение/файл/выключено);
  * запрещённые обещания (:1824/:16413) — grep 0 попаданий в обоих гайдах;
  * честные дефолты вместо «вечных» обещаний (сон/денежные лимиты выключены
    по умолчанию; изображения — тумблер чата; фактчек/опыт включены);
  * рендер-безопасность (TH-6): канон Г2 использует только теги, разрешённые
    существующим рендером+CSS (h1/h2/p/blockquote/b/i/a), без on*/style;
  * поиск по «Справке» (helpContent → filteredHelpToc): новые заголовки
    уникальны — якоря и поиск их видят;
  * SC-R3c (негативный): канон-ключи content.* не читаются ботоведческим
    кодом — восстановление/правка текста не может откатить поведение бота.
"""
import re
from pathlib import Path

from services.info_service import (
    DEFAULT_INFO_TEXT,
    GUIDE_CANON_VERSION,
    INFO_CANON_VERSION,
    KNOWN_GUIDE_SNAPSHOTS,
    KNOWN_INFO_SNAPSHOTS,
    PREV_R1048_DEFAULT_INFO_TEXT,
    PREV_R1048_INTELLIGENCE_GUIDE,
    canon_drift,
    guide_version_for,
)

ROOT = Path(__file__).resolve().parent.parent
GUIDE_MD = (ROOT / "plans" / "docs" / "intelligence_user_guide.md").read_text(
    encoding="utf-8")
INFO_MD = (ROOT / "info_text.md").read_text(encoding="utf-8")

# ── матрица T-5204 → Г1: новые разделы §12–§18 ──────────────────────────────

G1_NEW_SECTIONS = (
    ("## 12. Самостоятельность", "возвращается к теме сам", "«Статус»"),
    ("## 13. Случайность", "источник случайности", "«Источник случайности»"),
    ("## 14. Обучение на опыте", "банк опыта", "«Память»"),
    ("## 15. Достоверная статистика", "точную фразу", "частично"),
    ("## 16. Изображения", "тумблером", "«Модули»"),
    ("## 17. Временной фактчек", "выдают за свежий", "«Гайде по фичам бота»"),
    ("## 18. Наблюдаемость", "исход и причину", "«Аналитика»"),
)


class TestGuide1MatrixCoverage:
    """MCA21-R1 (SC-R1a): каждая тема матрицы имеет место в Г1."""

    def test_new_sections_present_with_where_to_look(self):
        for heading, fact_marker, where_marker in G1_NEW_SECTIONS:
            assert heading in GUIDE_MD, heading
            assert fact_marker in GUIDE_MD, fact_marker
            assert where_marker in GUIDE_MD, where_marker

    def test_core_topics_actualized(self):
        # T-5205 (ядро): память/честное время; досье/происхождение/пересборка;
        # истории; сны без фиксированных часов; личность; повторы.
        for marker in (
            "не становится \"сегодняшней\"",          # честное время (MCA-03)
            "происхождение",                          # досье (MCA-04)
            "пересобрать заново из всего архива",     # пересборка (MCA-04)
            "Продолжение он дописывает",              # истории (MCA-05)
            "цепочка \"как думали раньше",             # парадигмы с историей
            "ксерокопию прошлого ответа",             # повторы (ASAP-3)
            "цитата не становится мнением",           # атрибуция (MCA-22)
            "обновления не стирают память",           # MCA-14 через эффект
        ):
            assert marker in GUIDE_MD, marker

    def test_where_to_look_uses_real_screens(self):
        # D4(г): названия экранов совпадают с релизом (Статус/Модули/
        # Аналитика/Память).
        for screen in ("«Статус»", "«Модули»", "«Аналитика»", "«Память»"):
            assert screen in GUIDE_MD, screen

    def test_memory_words_management(self):
        # Пробел матрицы #4: управление памятью словами.
        assert "запомни: у Толяна день рождения в марте" in GUIDE_MD
        assert "забудь про литрбол" in GUIDE_MD

    def test_stub_not_advertised(self):
        # Игровая заглушка вне гайдов (:1824): ни слова про игру/игровую
        # заглушку как функцию.
        low = GUIDE_MD.lower()
        for marker in ("игровая заглушка", "мини-игр", "миниигр"):
            assert marker not in low, marker


class TestGuide2ImageSection:
    """MCA21-R2 (SC-R2a): раздел изображений по образцу файла."""

    def test_section_12_present(self):
        assert "<h2>12. Распознавание изображений" in INFO_MD

    def test_three_examples_by_the_book(self):
        for frag in (
            "<blockquote><b><i>Бот, что на картинке?</i></b></blockquote>",
            "<blockquote><b><i>Бот, прочитай текст на скрине</i></b></blockquote>",
            "<blockquote><b><i>Бот, опиши фото</i></b></blockquote>",
        ):
            assert frag in INFO_MD, frag

    def test_no_slash_commands_in_image_section(self):
        section = INFO_MD[INFO_MD.index("<h2>12."):]
        plain = re.sub(r"</?[a-z0-9]+[^>]*>", "", section)
        assert "/" not in plain  # D5: без слеш-команд

    def test_name_is_example_not_trigger(self):
        # «Бот» в примерах — образец обращения (как во всём файле), без
        # формулировок-триггеров вида «работает только по имени».
        section = INFO_MD[INFO_MD.index("<h2>12."):]
        assert "только по имени" not in section
        assert "обязательное имя" not in section

    def test_d6_explanations_present(self):
        # D6: повтор/уточнение/файл/выключено + картинка ≠ истина.
        for marker in (
            "Повторный вопрос по той же картинке заново разбирать не заставит",
            "переспросит",
            "пришли картинку заново",
            "тумблером в настройках чата",
            "не автоматически правда",
            "фактчеком",
        ):
            assert marker in INFO_MD, marker


class TestHonestyDefaults:
    """D4(a)/(б): честные значения вместо жёстких обещаний; запрещённых
    обещаний нет (SC-R1b, grep-лист D4(б) → 0 попаданий)."""

    def test_forbidden_promises_absent(self):
        for text in (GUIDE_MD, INFO_MD):
            low = text.lower()
            for promise in (
                "никогда не путает", "никогда не ошибается", "безошибочн",
                "сознани", "читает недоступный архив", "обучается весам",
                "учит веса", "переобучает веса", "всегда прав",
                "никогда не врёт", "не врёт никогда",
            ):
                assert promise not in low, promise

    def test_honest_defaults_stated(self):
        # Сон выключен по умолчанию (MCA-06); денежные лимиты выключены
        # (MCA-11); изображения — тумблер чата (MCA-19).
        assert "По умолчанию бот не спит" in GUIDE_MD
        assert "Денежные лимиты по умолчанию выключены" in GUIDE_MD
        assert "включается отдельно, тумблером" in INFO_MD
        # Работающее по умолчанию: фактчек по времени (MCA-20) и опыт
        # (MCA-16) — включены сразу.
        assert "Работает по умолчанию" in GUIDE_MD
        assert "Работает это сразу, без включения" in GUIDE_MD

    def test_no_fixed_hours_promised(self):
        # D4(a): фиксированные часы/кулдауны не обещаются как вечные.
        assert "с четырёх до шести утра" not in GUIDE_MD
        assert "сорок пять минут" not in GUIDE_MD
        assert "около двенадцати часов" not in GUIDE_MD
        assert "Раз в сутки, сразу после обычного сна" not in GUIDE_MD

    def test_r17_no_real_identifiers(self):
        # R17: обезличенные персонажи гайда (Толян/Леха/Олег — вымышленные
        # обитатели текста), без живых чатов/секретов.
        for text in (GUIDE_MD, INFO_MD):
            assert "sk-" not in text.lower()
            assert "api_key" not in text.lower()
            assert "-100" not in text   # маска живых chat-id


class TestRenderSafety:
    """TH-6: текст не ломает существующий рендер — только теги, на которые
    уже есть DOMPurify-пропуск и CSS."""

    def test_info_canon_tag_allowlist(self):
        tags = set(re.findall(r"</?([a-z0-9]+)[^>]*>", DEFAULT_INFO_TEXT))
        assert tags <= {"h1", "h2", "p", "blockquote", "b", "i", "a"}, tags
        # никаких обработчиков/инлайн-стилей даже в разрешённых тегах
        assert not re.search(r"\son\w+=", DEFAULT_INFO_TEXT)
        assert "style=" not in DEFAULT_INFO_TEXT

    def test_info_canon_anchor_titles_unique(self):
        # Поиск по «Справке» строит якоря из h1/h2 — заголовки уникальны.
        titles = re.findall(r"<h2>(\d+\..+?)</h2>", DEFAULT_INFO_TEXT)
        assert len(titles) == len(set(titles)) == 12
        assert "12. Распознавание изображений (бот видит картинки)" in titles

    def test_guide1_anchor_titles_unique(self):
        titles = re.findall(r"^## (\d+\. .+)$", GUIDE_MD, re.M)
        assert len(titles) == len(set(titles)) == 19


class TestCanonKeysNotBehaviorSurface:
    """SC-R3c (негативный тест): восстановление/правка канон-текста не может
    изменить поведение бота — ключи content.* читает только цепочка
    InfoService/ConfigCache/каталог/API."""

    def test_canon_keys_surface_restricted(self):
        allowed = {
            "services\\info_service.py",
            "services\\config_cache.py",
            "services\\param_catalog.py",   # _CONTENT: read-only записи каталога
            "web\\api\\routes.py",          # контракты /api/info* (RBAC)
        }
        hits = []
        for base in ("services", "handlers", "web"):
            for path in (ROOT / base).rglob("*.py"):
                rel = path.relative_to(ROOT).as_posix()
                if "static" in rel or "vendor" in rel:
                    continue
                try:
                    body = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if ("content.info_how_it_works" in body
                        or "content.intelligence_guide" in body):
                    if rel.replace("/", "\\") not in allowed:
                        hits.append(rel)
        assert hits == [], f"канон-ключи читает ботоведческий код: {hits}"


class TestCanonVersionInvariant:
    """D7/SC-R3a: версии/слепки согласованы; инвариант guide_version_for."""

    def test_versions_and_registries(self):
        assert INFO_CANON_VERSION == 6
        assert GUIDE_CANON_VERSION == 3
        assert len(KNOWN_INFO_SNAPSHOTS) == 5
        assert len(KNOWN_GUIDE_SNAPSHOTS) == 2
        assert KNOWN_INFO_SNAPSHOTS[-1] is PREV_R1048_DEFAULT_INFO_TEXT
        assert KNOWN_GUIDE_SNAPSHOTS[-1] is PREV_R1048_INTELLIGENCE_GUIDE

    def test_guide_version_for_invariant(self):
        assert guide_version_for(GUIDE_MD) == GUIDE_CANON_VERSION
        assert guide_version_for(PREV_R1048_INTELLIGENCE_GUIDE) == 2
        assert guide_version_for(KNOWN_GUIDE_SNAPSHOTS[0]) == 1
        assert guide_version_for("") == GUIDE_CANON_VERSION

    def test_prev_snapshots_are_drift_not_canon(self):
        assert canon_drift(PREV_R1048_DEFAULT_INFO_TEXT) is True
        assert canon_drift(DEFAULT_INFO_TEXT) is False
        assert DEFAULT_INFO_TEXT == INFO_MD   # байт-зеркало сид-файла
