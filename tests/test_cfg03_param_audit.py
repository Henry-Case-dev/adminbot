"""CFG-03 (Ф2) — контракт аудита всех параметров MiniApp (579 записей).

TEST-LIFECYCLE: CONTRACT owner=CFG-03

Машинно проверяемые звенья цепочки CFG-03.M по ВСЕМ записям REGISTRY
(не 579 ручных эссе — класс-подход + сканы):

  * UI-покрытие: у каждого visible-параметра есть место рендера
    (config-вкладка / документированный спец-экран / synthetic-группа app.js);
    `UI_missing` пуст ИЛИ явно классифицирован (CFG-03.1);
  * consumer-покрытие: у каждого параметра есть runtime-потребитель
    (литерал pg_key / settings-поле / env-имя / динамический шаблон);
    «мёртвые ручки» — ровно документированный список с честным описанием
    (CFG-03.1/.6); env-only без Python-читателя — документированы (docker);
  * согласованность каталога: группа/категория, settings-поле, семейство
    типов дефолтов, select-дефолты, hidden/api-only (CFG-03.5);
  * класс-негативы: coercion по типам каталога + OFF/ON флагов и лимит
    1-вместо-10 через effective-резолвер (CFG-03.11/.12, класс-подход);
  * пины: счётчики, TSV/screen-map полнота (детали идемпотентности —
    tests/test_round1025_f8_registry.py, не дублируются).

Живые/DB-roundtrip проверки классов переиспользуются из P0/B06/SOUL-1/
CFG-01/02A/02B/02C evidence (prep-cfg-03 §2/§3.5) — здесь статический
контракт + resolver-классы без моков, изображающих проверку.
"""
import re
import sys
from pathlib import Path

import pytest

from services import param_catalog as pc

ROOT = Path(__file__).resolve().parent.parent

RUNTIME_DIRS = ("config", "handlers", "services", "web", "filters", "scripts",
                "SmartModule")
RUNTIME_ROOT_FILES = ("bot.py", "manage.py")
WEB_EXTRA = ("web/app.js", "web/index.html")

# Файлы, где встречается сам каталог/его экспорт — не потребители значения.
NON_CONSUMER = {"services/param_catalog.py", "scripts/migrate_env_to_pg.py"}

# ── Документированные «мёртвые ручки» (visible, без runtime-читателя) ───────
# Найдены repo-wide статическим сканом (tools/cfg03_param_inventory.py) и
# адъюдицированы в evidence/cfg-03 (README §Design/§Findings). Список
# ТОЧНЫЙ: новая мёртвая ручка или возвращённый потребитель = падение.
DEAD_KNOBS = {
    "limits.chat_budget_response_ratio":
        "runtime-читателя нет (repo-wide scan; ни литерал, ни settings-поле)",
    "limits.chat_lock_max_entries":
        "runtime-читателя нет (repo-wide scan)",
    "limits.dig_year_back_window_days":
        "runtime-читателя нет (repo-wide scan)",
    "limits.memory_backup_keep":
        "отключено политикой владельца UPD3 №5 (см. services/memory_backup.py)",
    "keys.random_quantum_provider":
        "информационное имя провайдера; ANU захардкожен (mca_random_source)",
    "limits.youtube_transcript_proxy_locations":
        "runtime-читателя нет (движок использует URL/логин-пароль прокси)",
    "limits.youtube_transcript_proxy_retries":
        "runtime-читателя нет (каскадные ретраи _MAX_CASCADE_RETRIES)",
}

# Маркеры честной витрины (CFG-03.6) — хотя бы один в описании.
HONESTY_MARKERS = ("не действует", "не влияет", "игнорируется",
                   "не используется", "не читается", "не потребляется",
                   "информационное")

# env-only без Python-читателя: потребитель — docker-compose (вне рантайма).
DOCKER_ENV = {
    "postgres_db", "postgres_user", "postgres_password",
    "telegram_api_id", "telegram_api_hash", "cobalt_http_proxy",
}
# env-only, не читаемый даже docker-контуром (значение в settings, но не
# используется) — документированная мёртвая env-ручка.
ENV_UNUSED = {"media_base"}

# Группы, рендерящиеся вне config-вкладок (документированные спец-экраны).
SPECIAL_SCREEN_GROUPS = {"content_info"}  # «Справка» (#/info)

# Документированные исключения согласованности (не дефекты).
GROUP_CATEGORY_EXCEPTIONS = {
    # тумблер «Бюджеты контекста» живёт в секции лимитов бюджетов (mod_direct)
    "flags.chat_context_budgets_enabled",
}

# CFG-03-F2 (22.10.2026, закрытие backlog «F2-типы CFG-03»): семейство
# типов выровнено с дефолтами Settings — cooldown int→float (дефолт 300.0,
# резолвер float(...)), retries int→str (дефолт '', рантайм не читает);
# пины чужих слайсов переутверждены (catalog delta + re-pin, §3.4).
# Исключений не осталось — новое расхождение типов падает само.
TYPE_FAMILY_EXCEPTIONS: set[str] = set()


def _strip_comments(line: str, js: bool = False) -> str:
    in_s = in_d = False
    prev = ""
    for i, ch in enumerate(line):
        if ch == "'" and not in_d and prev != "\\":
            in_s = not in_s
        elif ch == '"' and not in_s and prev != "\\":
            in_d = not in_d
        elif not in_s and not in_d:
            if js and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                return line[:i]
            if not js and ch == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i]
        prev = ch
    return line


def _runtime_files() -> list[Path]:
    files: list[Path] = [ROOT / n for n in RUNTIME_ROOT_FILES
                         if (ROOT / n).exists()]
    for d in RUNTIME_DIRS:
        base = ROOT / d
        if base.exists():
            files += [p for p in base.rglob("*.py")
                      if "__pycache__" not in p.parts]
    for rel in WEB_EXTRA:
        if (ROOT / rel).exists():
            files.append(ROOT / rel)
    files += sorted(ROOT.glob("web/static/*.js"))
    return files


class _Scan:
    """Один проход по runtime-коду: литералы, идентификаторы, шаблоны."""

    LIT_RE = re.compile(r'"([^"\n]{1,120})"|\'([^\'\n]{1,120})\'')
    IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
    DYN_RE = re.compile(
        r"""f["']([A-Za-z0-9_.]*)\{([A-Za-z_]\w*)\}([A-Za-z0-9_.]*)["']""")
    FIELD_DEF_RE = re.compile(r"^\s*[A-Z][A-Z0-9_]*\s*:")
    # продолжение `_env_*(... "NAME", default)` на следующей строке
    FIELD_DEF_CONT_RE = re.compile(r'^\s*["\'][A-Z][A-Z0-9_]*["\']\s*,')

    def __init__(self):
        self.literals: set[str] = set()
        self.idents: set[str] = set()
        self.templates: list[tuple[str, str, str]] = []  # head, tail, rel
        self.file_literals: dict[str, set[str]] = {}
        for path in _runtime_files():
            rel = path.relative_to(ROOT).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            is_js = path.suffix in (".js", ".html")
            fset: set[str] = set()
            for raw in text.splitlines():
                line = _strip_comments(raw, js=is_js)
                if rel == "config/settings.py" and (
                        self.FIELD_DEF_RE.match(line)
                        or self.FIELD_DEF_CONT_RE.match(line)):
                    continue  # объявление поля Settings — не потребитель
                for m in self.LIT_RE.finditer(line):
                    lit = m.group(1) or m.group(2)
                    fset.add(lit)
                    if rel not in NON_CONSUMER:
                        self.literals.add(lit)
                for m in self.IDENT_RE.finditer(line):
                    if rel not in NON_CONSUMER:
                        self.idents.add(m.group(1))
                for m in self.DYN_RE.finditer(line):
                    if rel not in NON_CONSUMER:
                        self.templates.append((m.group(1), m.group(3), rel))
            self.file_literals[rel] = fset

    def consumed(self, spec: pc.ParamSpec) -> bool:
        pg = spec.pg_key
        if pg in self.literals:
            return True
        if spec.settings_field and (spec.settings_field in self.literals
                                    or spec.settings_field in self.idents):
            return True
        if spec.env_name and spec.env_name in self.literals:
            return True
        for head, tail, rel in self.templates:
            if not head or not pg.startswith(head):
                continue
            if tail and not pg.endswith(tail):
                continue
            middle = pg[len(head):len(pg) - len(tail) if tail else None]
            if not middle or middle not in self.file_literals.get(rel, set()):
                continue
            if "_" in middle or len(middle) >= 6:
                return True
        return False


@pytest.fixture(scope="module")
def scan() -> _Scan:
    return _Scan()


@pytest.fixture(scope="module")
def app_js() -> str:
    return (ROOT / "web/app.js").read_text(encoding="utf-8")


def _render_place(spec: pc.ParamSpec, synthetic: set) -> str | None:
    if spec.category is None:
        return "env (api-only)"
    if spec.hidden:
        return "hidden"
    if spec.group and pc.group_tab(spec.group):
        return "tab:" + pc.group_tab(spec.group)
    if spec.group in SPECIAL_SCREEN_GROUPS:
        return "special:" + spec.group
    if (spec.category, spec.group) in synthetic:
        return "synthetic:" + spec.group
    return None


class TestUiCoverage:
    def test_no_undocumented_ui_missing(self, app_js):
        """CFG-03.1: REGISTRY − (вкладки ∪ спец-экраны ∪ synthetic) = ∅."""
        synthetic = set(re.findall(
            r"_syntheticGroup\(\s*'([a-z_]+)'\s*,\s*'([a-z_]+)'\s*\)",
            app_js))
        missing = [s.pg_key for s in pc.REGISTRY.values()
                   if _render_place(s, synthetic) is None]
        assert missing == [], (
            "UI_missing без документированной классификации: %s" % missing)

    def test_content_media_synthetic_group_documented(self, app_js):
        """content_media (tab=None) рендерится synthetic-группой в окне
        Модуля 6 (app.js:3154-3159/3390-3394) — не UI_missing."""
        assert "_syntheticGroup('content', 'content_media')" in app_js
        assert pc.group_tab("content_media") is None
        specs = [s for s in pc.REGISTRY.values()
                 if s.group == "content_media"]
        assert specs, "группа content_media потеряла параметры"

    def test_visible_params_ui_visibility_matches_place(self):
        """hidden/api-only/visible ↔ фактическое место (REQ-F8-08)."""
        for spec in pc.REGISTRY.values():
            if spec.hidden:
                assert spec.category is not None
            if spec.category is None:
                # env-only: UI-места нет, api-only в screen-map
                assert not spec.group


class TestConsumerCoverage:
    def test_visible_dead_knobs_are_exactly_documented(self, scan):
        """CFG-03.1: у каждого параметра — потребитель, либо он в списке."""
        dead = {s.pg_key for s in pc.REGISTRY.values()
                if s.category is not None and not scan.consumed(s)}
        assert dead == set(DEAD_KNOBS), (
            "недокументированные мёртвые ручки: %s; "
            "устаревшие записи списка: %s"
            % (sorted(dead - set(DEAD_KNOBS)),
               sorted(set(DEAD_KNOBS) - dead)))

    def test_dead_knobs_honest_descriptions(self):
        """CFG-03.6: мёртвая ручка не изображает действующую настройку."""
        problems = []
        for key in DEAD_KNOBS:
            spec = pc.get_by_pg_key(key)
            assert spec is not None, key
            desc = (spec.description or "").lower()
            if not any(m in desc for m in HONESTY_MARKERS):
                problems.append((key, spec.description))
        assert problems == [], (
            "описание не предупреждает о неработоспособности: %s" % problems)

    def test_env_only_without_python_reader_documented(self, scan):
        """env-only без Python-читателя: docker-контур или env-мусор."""
        dead_env = {s.pg_key for s in pc.REGISTRY.values()
                    if s.category is None and not scan.consumed(s)}
        assert dead_env == DOCKER_ENV | ENV_UNUSED, (
            "недокументированные env-only: %s"
            % sorted(dead_env - DOCKER_ENV - ENV_UNUSED))

    def test_docker_env_consumed_by_compose(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        for key in DOCKER_ENV:
            spec = pc.get_by_pg_key(key)
            assert spec is not None and spec.env_name in compose, key

    def test_dynamic_consumer_paths_intact(self):
        """Динамические потребители (шаблон + слаг) не потеряны."""
        checks = [
            ("services/user_relations.py", 'f"limits.{name}"'),
            ("services/llm_client.py", 'f"models.{slug}_base_url"'),
            ("services/mca_exploration.py",
             'f"memory.random_uses_{use}"'),
        ]
        for rel, snippet in checks:
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert snippet in text, (rel, snippet)


class TestCatalogConsistency:
    def test_group_category_consistency(self):
        groups = {g.id: g for g in pc.GROUPS}
        keys_slots: set[str] = set()
        for _tid, rules in pc.TAB_RULES:
            for cat, sel in rules:
                if cat == pc.CATEGORY_KEYS and isinstance(sel, frozenset):
                    keys_slots |= set(sel)
        problems = []
        for spec in pc.REGISTRY.values():
            if spec.category is None:
                continue
            assert spec.group in groups, (spec.pg_key, spec.group)
            if groups[spec.group].category == spec.category:
                continue
            if spec.category == pc.CATEGORY_KEYS and spec.group in keys_slots:
                continue  # keys-слот в models_*-группе (TAB_RULES)
            if spec.pg_key in GROUP_CATEGORY_EXCEPTIONS:
                continue
            problems.append((spec.pg_key, spec.group))
        assert problems == []

    def test_settings_field_type_family(self):
        """Тип каталога ↔ тип factory-дефолта Settings (CFG-03.5)."""
        import dataclasses
        from config.settings import Settings
        dc_fields = {f.name for f in dataclasses.fields(Settings)}
        problems = []
        for spec in pc.REGISTRY.values():
            field = spec.settings_field
            if not field or spec.type == "str" or not hasattr(Settings, field):
                continue
            value = getattr(Settings, field)
            ann = str(Settings.__annotations__.get(field, ""))
            allowed = {"int": ("int",), "float": ("float", "int"),
                       "bool": ("bool",),
                       "json": ("str", "list", "dict", "tuple", "NoneType")}
            family = allowed.get(spec.type, ())
            if "None" in ann:
                family = family + ("NoneType",)
            kind = "dataclass" if field in dc_fields else "classvar"
            if type(value).__name__ not in family:
                problems.append((spec.pg_key, spec.type,
                                 type(value).__name__, kind))
        extra = [p for p in problems if p[0] not in TYPE_FAMILY_EXCEPTIONS]
        assert extra == [], (
            "каталог-тип ≠ дефолт Settings: %s (документированные "
            "исключения: %s)" % (extra, sorted(TYPE_FAMILY_EXCEPTIONS)))

    def test_type_family_regressions_fixed(self):
        """CFG-03-F2 (REGRESSION, 22.10.2026): закрытые расхождения типов.

        Два former TYPE_FAMILY_EXCEPTIONS ключа: тип каталога == тип
        factory-дефолта Settings (cooldown float 300.0, retries str '').
        TEST-LIFECYCLE: REGRESSION owner=CFG-03-F2
        """
        from config.settings import Settings
        for pg_key, field, expected in (
            ("limits.image_freq_limit_cooldown_seconds",
             "IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS", "float"),
            ("limits.youtube_transcript_proxy_retries",
             "YOUTUBE_TRANSCRIPT_PROXY_RETRIES", "str"),
        ):
            spec = pc.get_by_pg_key(pg_key)
            assert spec is not None, pg_key
            assert spec.type == expected, pg_key
            assert type(getattr(Settings, field)).__name__ == expected, pg_key
        # Пин-тесты чужих слайсов переутверждены тем же значением.
        assert pc.get("IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS").type == \
            pc.get_by_pg_key("limits.image_freq_limit_cooldown_seconds").type
        assert pc.get("YOUTUBE_TRANSCRIPT_PROXY_RETRIES").type == \
            pc.get_by_pg_key("limits.youtube_transcript_proxy_retries").type

    def test_select_params_consistent(self):
        for spec in pc.REGISTRY.values():
            if spec.widget != "select":
                continue
            assert spec.select_options, spec.pg_key
            assert len(spec.select_options) == len(spec.select_labels), \
                spec.pg_key
            assert len(set(spec.select_options)) == len(spec.select_options), \
                spec.pg_key

    def test_hidden_and_api_only_documented(self):
        hidden = {s.pg_key for s in pc.REGISTRY.values() if s.hidden}
        assert hidden == {"limits.factcheck_context_messages",
                          "prompts.summary_cover_style_id"}
        api_only = {s.pg_key for s in pc.REGISTRY.values()
                    if s.category is None}
        assert len(api_only) == 25


class TestClassNegatives:
    """Класс-негативы (CFG-03.11/.12): тип-классы + OFF/ON и лимит 1-в-10.

    Резолвер — реальный (services.chat_params), БД — in-memory фикстура
    прецедента tests/test_chat_params.py (без моков самого резолвера).
    """

    @pytest.fixture
    def env(self, monkeypatch):
        from tests.test_chat_params import _FakeConn, _FakePg
        from services.chat_params import ChatParamsCache
        conn = _FakeConn()
        pg = _FakePg(conn)
        cache = ChatParamsCache(pg)
        monkeypatch.setattr("services.chat_params._chat_params_cache", cache)
        return conn, pg, cache

    def test_normalize_value_type_classes(self):
        nv = pc.normalize_value
        assert nv("limits.image_daily_limit", "7") == 7
        assert nv("limits.image_daily_limit", 7.0) == 7
        # float-класс: доли не теряются
        assert nv("limits.chat_budget_target_ratio", "0.25") == 0.25
        assert nv("flags.vision_enabled", "on") is True
        assert nv("flags.vision_enabled", "off") is False
        assert nv("limits.summary_aliases", '{"a": "b"}') == {"a": "b"}
        # мусор: не падаем и не теряем значение молча
        assert nv("limits.image_daily_limit", "мусор") == "мусор"

    @pytest.mark.asyncio
    async def test_int_limit_negative_1_vs_10(self, env, monkeypatch):
        from services.chat_params import get_chat_param, set_chat_params
        conn, pg, _ = env
        conn.add_profile(-10001)
        monkeypatch.setattr("services.hot_config.get",
                            lambda key, default=None: default)
        await set_chat_params(
            -10001, {"overrides": {"limits.image_daily_limit": 1}},
            changed_by=1, pg=pg)
        assert await get_chat_param(
            -10001, "limits.image_daily_limit", 10) == 1
        await set_chat_params(-10001, {"overrides": {}}, changed_by=1, pg=pg)
        assert await get_chat_param(
            -10001, "limits.image_daily_limit", 10) == 10

    @pytest.mark.asyncio
    async def test_flag_off_on_effective(self, env, monkeypatch):
        from services.chat_params import get_chat_param
        conn, _pg, _ = env
        monkeypatch.setattr(
            "services.hot_config.get",
            lambda key, default=None: True
            if key == "flags.vision_enabled" else default)
        # OFF (override) при глобальном ON
        conn.add_profile(-10002, {"overrides": {"flags.vision_enabled": False}})
        assert await get_chat_param(
            -10002, "flags.vision_enabled", True) is False
        # ON (override) — возвращает включённое состояние
        conn.add_profile(-10003, {"overrides": {"flags.vision_enabled": True}})
        assert await get_chat_param(
            -10003, "flags.vision_enabled", False) is True
        # override нет → наследование глобального ON
        conn.add_profile(-10004)
        assert await get_chat_param(
            -10004, "flags.vision_enabled", False) is True


class TestPins:
    def test_counts_and_artifacts(self):
        assert len(pc.REGISTRY) == 581
        assert len(pc.GROUPS) == 119
        assert len(pc._TAB_BY_GROUP) == 117
        assert len(pc.TAB_RULES) == 22
        tsv = (ROOT / "plans/docs/param-registry-round1025.tsv").read_text(
            encoding="utf-8").splitlines()
        assert len(tsv) - 1 == 581
        screen_keys = set()
        for line in (ROOT / "plans/docs/screen-map-round1025.md").read_text(
                encoding="utf-8").splitlines():
            if line.startswith("| ") and not line.startswith("| old_screen"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 9:
                    screen_keys.add(cells[1])
        assert screen_keys == {s.pg_key for s in pc.REGISTRY.values()}
