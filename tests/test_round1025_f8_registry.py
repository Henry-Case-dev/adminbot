"""F8 round 10.25 — маркер-тесты реестра/карт/сохранности (T-3011/T-3012, ADR-1025-21 D6).

Доказывают (read-only enabler):
  * полноту реестра: `{internal_key}` == REGISTRY == 459; пустых ячеек нет;
  * дельту 411 → 459 = 48 (перечислена явно, `status=new`);
  * отсутствие открытых секретов во всех артефактах F8 (R17);
  * идемпотентность генератора `--check` (и детект искусственного расхождения);
  * карту экранов: 0 параметров «без нового места»; `api-only` помечены;
  * карту виджетов: присутствует, покрывает обязательные виджеты, `api-only` выделен;
  * diff по 8 срезам без реальных изменений; классификатор/R17-маску;
  * инварианты: Δ DDL=0, Δ каталога=0, `web/api/routes.py` соответствует
    объявленному контракту путей/методов/RBAC, `APP_VERSION` согласован,
    `tools/*` не импортируются рантаймом (read-only/CSP).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402
import tools.config_snapshot_diff as csd  # noqa: E402
from services import param_catalog as pc  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "round1025" / "f8_baseline.json")
    .read_text(encoding="utf-8"))
CATALOG_BASELINE = json.loads(
    (ROOT / "tests" / "fixtures" / "round1025" / "catalog_baseline.json")
    .read_text(encoding="utf-8"))
INVENTORY = ROOT / "plans" / "archive" / "settings-persistence-audit-round1014" / "inventory.tsv"
ARTIFACTS = [ROOT / p for p in FIXTURE["artifacts"]]

# F8-инварианты больше НЕ пинят sha256 всего исходного файла.
# Byte-freeze заменён содержательными контрактами:
#   * routes: tests/routes_contract.py (набор путей/методов + initData/RBAC);
#   * param_catalog: идентичность ключей/счётчиков + генератор --check
#     (описания/типы/секретность в переэмитированных артефактах);
#   * pg_db: идемпотентность DDL_STATEMENTS + цепочка миграций.
# Механический re-pin полного хэша при любой правке файла устранён.


def _registry_keys() -> set[str]:
    return {s.pg_key for s in pc.REGISTRY.values()}


def _inventory_keys() -> set[str]:
    keys = set()
    for i, line in enumerate(INVENTORY.read_text(encoding="utf-8").splitlines()):
        if i == 0:
            continue
        cells = line.split("\t")
        if len(cells) > 2 and cells[2]:
            keys.add(cells[2])
    return keys


def _read_registry_rows() -> list[dict]:
    lines = (ROOT / FIXTURE["artifacts"][0]).read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def _parse_screen_keys() -> set[str]:
    text = (ROOT / "plans/docs/screen-map-round1025.md").read_text(encoding="utf-8")
    keys = set()
    for line in text.replace("\r\n", "\n").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 9 and cells[0] != "old_screen":
            keys.add(cells[1])
    return keys


# ── Δ каталога = 0 / Δ DDL = 0 / роуты / версия ─────────────────────────────

class TestFrozenInvariants:
    def test_param_catalog_identity_contract(self):
        # Вместо sha256 файла: состав каталога объявлен baseline-фикстурой
        # (ключи) и счётчиками; описания/типы/секретность контролирует
        # переэмиссия артефактов (`gen.run_check`). Любое необъявленное
        # добавление/удаление ключа падает здесь и в TestGenerator.
        assert set(pc.REGISTRY) == set(CATALOG_BASELINE["registry_keys"])
        valid_types = {"bool", "int", "float", "str", "json"}
        valid_sensitivity = {"NON_SECRET_CONFIG", "SECRET_VALUE",
                             "PROMPT_CONTENT"}
        for key, spec in pc.REGISTRY.items():
            assert str(key).strip() and spec.title_ru
            assert spec.type in valid_types, (key, spec.type)
            assert spec.sensitivity in valid_sensitivity, (key, spec.sensitivity)
            if spec.secret:
                assert spec.sensitivity == "SECRET_VALUE", (
                    key, spec.sensitivity)

    def test_ddl_source_contract(self):
        # Вместо sha256 pg_db.py: DDL не содержит разрушающих операторов,
        # создаёт ключевые таблицы идемпотентно (IF NOT EXISTS), а цепочка
        # миграций строго возрастает и не повторяется.
        import re as _re

        import services.database as database_mod
        import services.pg_db as pg_db_mod
        statements = pg_db_mod.DDL_STATEMENTS
        assert statements
        for stmt in statements:
            upper = " ".join(stmt.upper().split())
            assert "DROP TABLE" not in upper, "разрушающий DDL: %s" % stmt[:120]
            assert "TRUNCATE" not in upper, "разрушающий DDL: %s" % stmt[:120]
            if _re.match(r"CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)", upper):
                assert "IF NOT EXISTS" in upper, (
                    "CREATE без IF NOT EXISTS: %s" % stmt[:120])
        ddl_src = "\n".join(statements)
        for table in ("bot_settings", "bot_roles", "bot_admins",
                      "cover_style_connections"):
            assert _re.search(r"CREATE TABLE IF NOT EXISTS %s\b" % table,
                              ddl_src, _re.IGNORECASE), table
        versions = [step.version
                    for step in database_mod.DatabaseService.migration_steps()]
        assert versions == sorted(versions)
        assert len(versions) == len(set(versions))

    def test_routes_contract_intact(self):
        # Вместо sha256 routes.py: контракт путей/методов/initData/RBAC
        # (tests/routes_contract.py). Падает при удалении маршрута, смене
        # метода, снятии проверки прав, появлении необъявленного маршрута.
        from tests.routes_contract import assert_routes_contract_intact
        assert_routes_contract_intact()

    def test_counts_frozen(self):
        # ASAP-2.1 (ADR-1028-1 D1, контракт (i)): санкционированная
        # ОТРИЦАТЕЛЬНАЯ Δ каталога — -8 ключей summary_filter_* и -2 группы;
        # TAB_RULES 21 in-place (счётчик не менялся). 489→481 / 107→105 /
        # 105→103; delta 78→70 (8 удалённых ключей были частью Δ round1026).
        # ASAP-3 (round 1028, ADR-1028-2 D12, санкция spec §6): +2 ключа
        # (flags.chat_autonomous_reply_enabled — Settings-поле CHAT_
        # AUTONOMOUS_REPLY_ENABLED; flags.chat_silent_ack_enabled — PG-only)
        # в существующую группу flags_decision_making → 481→483; delta
        # 70→72. GROUPS/_TAB_BY_GROUP/TAB_RULES — in-place (105/103/21).
        # ASAP-3.1 (round 1028, ADR-1028-3, санкция spec 10.1): +1 ключ
        # models.chat_context_window_override (Settings-поле CHAT_MODEL_
        # CONTEXT_WINDOW; первая каталогизация ClassVar → Settings 423→424)
        # + 6 переименований labels/группы → 483→484; delta 72→73.
        # ASAP 4.4 (T-4880, §5.3): +1 non-secret ключ
        # keys.embedding_quota_group_labels (hot; ClassVar
        # EMBEDDING_QUOTA_GROUP_LABELS) → 488→489; delta 77→78.
        # MCA-10a (ADR-1028-14 D8/D12, санкция §13.2): +13 ключей / +2 группы
        # (memory_random/keys_random) / +2 tab-маппинга; TAB_RULES 21 in-place;
        # delta 78→91 → 502/107/105/21.
        # v6.3 B01 (W1-CHAT-INTEL): +10 ключей INITIATIVE_* (2 flags_intent,
        # 8 limits_intent), группы/табы in-place → 571/120/118/23.
        # SOUL-1 mobile-prompts (2026-10-16): +1 PG-only промпт-ключ
        # prompts.direct_l1_planner_system_prompt → 572/120/118/23
        # (группа/вкладка/Settings/secret/hidden без изменений).
        # P0-FACTCHECK §6.3 (FC-06C, round 10.48): −2 мёртвых TTL-ключа
        # TEMPORAL_FRESHNESS_* (кеш вердиктов удалён) → 586/121/119/23.
        # EVOL-031 (30.10.2026): −5 ключей Exact Match Cache / direct_dedup
        # (replay готовых ответов удалён; вкладка smart_cache снята) →
        # 581/119/117/22 (ключи/группы/табы каталога).
        assert len(pc.REGISTRY) == FIXTURE["counts"]["REGISTRY"] == 668
        assert len(pc.GROUPS) == FIXTURE["counts"]["GROUPS"] == 121
        assert len(pc._TAB_BY_GROUP) == \
            FIXTURE["counts"]["TAB_BY_GROUP"] == 119
        assert len(pc.TAB_RULES) == FIXTURE["counts"]["TAB_RULES"] == 23

    def test_registry_keys_match_catalog_baseline(self):
        # F1-baseline фиксирует ключи REGISTRY (settings_field/env), не pg_key.
        assert set(pc.REGISTRY.keys()) == set(CATALOG_BASELINE["registry_keys"])

    def test_app_version_recorded(self):
        # L-F9S-3: маркер F8 не ослабляется: исторический fixture остаётся
        # снимком 2.58.15, а runtime-версия проверяется каноническим
        # контрактом (согласованность settings.py ↔ meta ↔ index.html),
        # а не литералом текущего номера.
        assert FIXTURE["app_version"] == "2.58.15"
        from tests.version_contract import assert_version_contract
        assert_version_contract()

    def test_routes_set_declared(self):
        from tests.routes_contract import load_manifest
        declared = {row["path"] for row in load_manifest()["routes"]}
        assert declared  # непустой объявленный набор
        assert "/health" in declared

    def test_tools_not_imported_by_runtime(self):
        """Read-only: рантайм-модули не импортируют `tools/*` (CSP/zero-build)."""
        for sub in ("services", "web", "handlers"):
            for path in (ROOT / sub).rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                # Запрещены только F8-инструменты (прочие `tools/*` — легаси).
                for token in FIXTURE["runtime_import_forbidden"]:
                    assert token not in text, f"{path}: импорт {token}"


# ── Реестр: полнота / дельта / R17 ──────────────────────────────────────────

class TestRegistry:
    def test_rows_complete_no_empty(self):
        rows = _read_registry_rows()
        # ASAP-2.1 (ADR-1028-1 D1): санкционированная Δ −8 → 481.
        # ASAP-3 (ADR-1028-2 D12): санкционированная Δ +2 → 483.
        # ASAP-3.1 (ADR-1028-3): санкционированная Δ +1 → 484.
        # ASAP 4.4 (T-4880): санкционированная Δ +1 → 489.
        # MCA-10a (ADR-1028-14 D8/D12, санкция §13.2): санкционированная
        # Δ +13 (memory.random_* ×4 + keys.random_quantum_* ×9) → 502.
        # ASAP 7 F2 (§1.6): +9 (L1 Planner); параллельный F4 in-flight — снято
        # фактом на момент reissue (560).
        # v6.3 B01 (W1-CHAT-INTEL): +10 (INITIATIVE_*) → 571.
        # SOUL-1 mobile-prompts (2026-10-16): +1 (L1 Planner) → 572.
        # P0-FACTCHECK §6.3 (FC-06C): −2 (TEMPORAL_FRESHNESS_*) → 586.
        # EVOL-031 (30.10.2026): −5 (Exact Match Cache / direct_dedup) → 581.
        assert len(rows) == 668
        assert [r["internal_key"] for r in rows] == sorted(_registry_keys())
        assert all(v != "" for r in rows for v in r.values())
        assert len(rows[0]) == len(gen.TSV_COLUMNS) == 23

    def test_delta_explicit(self):
        # round1026 S1 (ADR-1026-1 D1): санкционированная Δ +8 → дельта 56.
        # round1026 A5 (ADR-1026-17 D9): санкционированная Δ +1 → дельта 59.
        # ASAP-2.1 (ADR-1028-1 D1): санкционированная ОТРИЦАТЕЛЬНАЯ Δ −8
        # (все 8 были частью Δ round1026 S1) → дельта 70.
        # ASAP-3 (ADR-1028-2 D12): санкционированная Δ +2 → дельта 72.
        # ASAP-3.1 (ADR-1028-3): санкционированная Δ +1 → дельта 73.
        # ASAP 4.4 (T-4880): санкционированная Δ +1 → дельта 78.
        # MCA-10a (ADR-1028-14 D8/D12): санкционированная Δ +13 → дельта 91.
        # v6.3 B01 (W1-CHAT-INTEL): санкционированная Δ +10 → дельта 160.
        # SOUL-1 mobile-prompts (2026-10-16): +1 → дельта 161.
        delta = _registry_keys() - _inventory_keys()
        # ASAP 7 F2 (§1.10): дельта 127→149 (+9 F2; F4 in-flight — фактом).
        # P0-FACTCHECK §6.3 (FC-06C): −2 → дельта 175.
        # EVOL-031 (30.10.2026): снятые 5 ключей — исторические (Epic 51,
        # до инвентаря round1014), в delta-набор не входили → дельта 175
        # без изменений (FIXTURE см. tools/_evol031_reissue_f8.py).
        assert len(delta) == FIXTURE["counts"]["delta"] == 267
        new_rows = {r["internal_key"] for r in _read_registry_rows()
                    if r["status"] == "new"}
        assert new_rows == delta

    def test_secret_rows_masked(self):
        rows = _read_registry_rows()
        secret_rows = [r for r in rows if r["secret"] == "true"]
        # +1 (ASAP 4.4 T-4880): keys.embedding_quota_group_labels — F8
        # belt-and-suspenders `category == keys → secret` (ParamSpec.secret
        # остаётся false: label — не секрет; маска в артефактах консервативна).
        # MCA-10a (ADR-1028-14 D8): +9 keys.random_quantum_* (все — category
        # keys → консервативная маска; истинный `secret=True` только у
        # api_key). Санкционная формулировка «secret 32→33» считала только
        # истинный секрет; семантика артефакта (`secret or category==keys`)
        # даёт 32→41 — см. evidence MCA-10a (блок C, F8-дельта).
        # ASAP 7 F2 (§1.6): +1 keys.direct_l1_api_key (secret) → 43.
        assert len(secret_rows) == 46
        for row in secret_rows:
            assert row["current_value"] == gen.SECRET_MASK
            assert row["default_value"] == gen.SECRET_MASK

    def test_hidden_key_preserved(self):
        rows = _read_registry_rows()
        hidden = [r for r in rows if r["hidden"] == "true"]
        # ASAP-3.2 (ТЗ §102/§124): +1 hidden — `prompts.summary_cover_
        # style_id` (ID/выбор стиля, НЕ текстовый промпт; один user-facing
        # источник правды — Summary → Стили обложки / POST /api/cover/select).
        # Раунд 10.23 (ADR-1023-2): +1 — limits.factcheck_context_messages
        # (legacy окно фактчека, источник миграции).
        # RLR-05-ADMIN (d49b10ac, REMOVE-LEGACY-REPHRASING §6.2) и UR-F
        # (a5ee0864, UR-14.2/16/21.13/21.17/21.21/24.2): +13 — ключи без
        # активного рантайм-читателя выведены из UI/params-meta, запись в
        # реестре/правах сохранена (значение читаемо, DML/миграций нет).
        # Артефакт F8 переэмитирован той же волной (TSV/screen-map), поэтому
        # счётчик ниже — фактическое состояние каталога, а не дрейф.
        # QND-NONDET (10.11.2026): +1 hidden — initiative.trigger_probability
        # (прежний бинарный гейт стал верхней границей вероятности; значение
        # читается как p_max) → 16.
        # QRNG P3 (17.11.2026, arch D4): +1 hidden — keys.random_quantum_provider
        # (информационное имя провайдера; runtime читает random.primary_provider,
        # строка/значение в БД остаются) → 17.
        # UR-F (26.11.2026, UR-21/21.01, release 2.58.249): +2 hidden —
        # limits.chat_context_fill_ratio (не триггер конспекта) и
        # limits.chat_current_question_max_chars (символьный потолок снят);
        # значения читаемы по PG-ключу, из пользовательского редактирования
        # выведены → 19.
        assert len(hidden) == 19
        hidden_keys = {r["internal_key"] for r in hidden}
        assert hidden_keys == {
            "flags.chat_mood_enabled",
            "flags.chat_style_anchors_enabled",
            "initiative.trigger_probability",
            "keys.random_quantum_provider",
            "limits.chat_budget_anchors_ratio",
            "limits.chat_budget_response_ratio",
            "limits.chat_context_fill_ratio",
            "limits.chat_current_question_max_chars",
            "limits.chat_lock_max_entries",
            "limits.chat_style_anchor_max_chars",
            "limits.chat_style_anchors_count",
            "limits.chat_timezone",
            "limits.factcheck_context_messages",
            "limits.summary_timezone",
            "prompts.direct_chat_synthesizer_system_prompt",
            "prompts.summary_cover_style_id",
            "reactions.chat_mood_negative_words",
            "reactions.chat_mood_positive_words",
            "reactions.goodmorning_tz",
        }
        # hidden сохранён в реестре/правах, но вне UI.
        for r in hidden:
            assert r["ui_visibility"] == "hidden"

    def test_no_open_secrets_in_artifacts(self):
        blob = "\n".join(p.read_text(encoding="utf-8") for p in ARTIFACTS)
        assert gen.scan_for_open_secrets(blob) == []

    def test_meta_provenance(self):
        meta = (ROOT / "plans/docs/param-registry-round1025.meta.md").read_text(
            encoding="utf-8")
        # ASAP-2.1 (ADR-1028-1 D1): переиздание после отрицательной Δ −8.
        # ASAP-3.1 (ADR-1028-3): переиздание после Δ +1 (483→484, 72→73).
        # ASAP 4.4 (T-4880): переиздание после Δ +1 (488→489, 77→78).
        # MCA-10a (ADR-1028-14 D8/D12): переиздание после Δ +13 (502, 91).
        # ASAP 5 (asap5-final-fixes, T-5256): переиздание после Δ +6
        # (529, 118).
        # ASAP 7 F2: reissue под 560/149 (+9 F2; F4 in-flight — фактом).
        # v6.3 B01 (W1-CHAT-INTEL): reissue под 571/160 (+10 INITIATIVE_*).
        # SOUL-1 mobile-prompts (2026-10-16): reissue под 572/161.
        # P0-FACTCHECK §6.3 (FC-06C): reissue под 586/175 (−2 TTL-ключа).
        # EVOL-031 (30.10.2026): reissue под 581/175 (−5 EMC/dedup-ключей).
        # EVOL §5 W5 review-fix B1 (31.10.2026): reissue под 595/189
        # (+2 ключа подачи фактчека).
        # MOD-ACL-UX-01 amendment (09.11.2026): reissue под 606/205
        # (+11 PG-only порогов/бюджетов уроков).
        assert "668" in meta and "411" in meta and "267" in meta
        from config.settings import APP_VERSION
        assert APP_VERSION in meta


# ── Карта экранов ───────────────────────────────────────────────────────────

class TestScreenMap:
    def test_all_params_have_a_place(self):
        keys = _parse_screen_keys()
        assert keys == _registry_keys()  # ⊇ и == (каталог — источник)
        # ASAP-2.1 (ADR-1028-1 D1): санкционированная Δ −8 → 481.
        # ASAP-3.1 (ADR-1028-3): санкционированная Δ +1 → 484.
        # ASAP 4.4 (T-4880): санкционированная Δ +1 → 489.
        # MCA-10a (ADR-1028-14 D8/D12): санкционированная Δ +13 → 502.
        # MCA-10b (ADR-1028-17 D16): санкционированная Δ +6 → 510.
        # v6.3 B01 (W1-CHAT-INTEL): санкционированная Δ +10 → 571.
        # SOUL-1 mobile-prompts (2026-10-16): санкционированная Δ +1 → 572.
        # P0-FACTCHECK §6.3 (FC-06C): санкционированная Δ −2 → 586.
        # EVOL-031 (30.10.2026): санкционированная Δ −5 → 581.
        assert len(keys) == 668

    def test_no_empty_new_screen(self):
        text = (ROOT / "plans/docs/screen-map-round1025.md").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("| ") and not line.startswith("| old_screen"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 9:
                    assert cells[2], "пустое новое место: %s" % cells[1]

    def test_ui_visibility_domain(self):
        text = (ROOT / "plans/docs/screen-map-round1025.md").read_text(encoding="utf-8")
        values = set()
        for line in text.splitlines():
            if line.startswith("| ") and not line.startswith("| old_screen"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 9:
                    values.add(cells[5])
        assert values <= {"visible", "hidden", "api-only"}
        assert "api-only" in values  # 25 env-only ключей помечены


# ── Карта виджетов ──────────────────────────────────────────────────────────

class TestWidgetMap:
    def test_marker_and_required_widgets(self):
        text = (ROOT / "plans/docs/widget-map-round1025.md").read_text(encoding="utf-8")
        assert "widget-map-round1025" in text
        for marker in ("Граф связей", "Логи", "Живая лента досье",
                       "Мониторинг интеллекта", "Карта LLM-вызовов",
                       "Системные метрики", "Живое сердцебиение"):
            assert marker in text, marker

    def test_api_only_section_present(self):
        text = (ROOT / "plans/docs/widget-map-round1025.md").read_text(encoding="utf-8")
        assert "api-only" in text
        assert "/api/debug/config" in text
        assert "≠ сохранено" in text


# ── Генератор: идемпотентность --check + детект расхождения ─────────────────

class TestGeneratorIdempotency:
    def test_check_passes_on_committed(self):
        assert gen.run_check() == 0

    def test_check_subprocess_exit_zero(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools/gen_param_registry_round1025.py"),
             "--check"], cwd=str(ROOT), capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_check_detects_tsv_mismatch(self, monkeypatch, tmp_path):
        bogus = tmp_path / "param-registry-round1025.tsv"
        bogus.write_text("internal_key\tbogus\n", encoding="utf-8", newline="\n")
        monkeypatch.setattr(gen, "TSV_PATH", bogus)
        assert gen.run_check() != 0

    def test_check_detects_screen_mismatch(self, monkeypatch, tmp_path):
        bogus = tmp_path / "screen-map-round1025.md"
        bogus.write_text("# bogus\n", encoding="utf-8", newline="\n")
        monkeypatch.setattr(gen, "SCREEN_PATH", bogus)
        assert gen.run_check() != 0


# ── Snapshot-diff: 8 срезов, 0 изменений ────────────────────────────────────

class TestSnapshotDiff:
    def test_selftest(self):
        assert csd.run_selftest() == 0

    def test_no_changes_on_identical_snapshots(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        csd.emit_baseline(before)
        csd.emit_baseline(after)
        result = csd.diff_dirs(before, after)
        assert set(result) == set(csd.SLICES)
        total = {k: sum(len(result[s][k]) for s in csd.SLICES)
                 for k in ("added", "removed", "changed")}
        assert total == {"added": 0, "removed": 0, "changed": 0}

    def test_classifier_detects_real_changes(self):
        got = csd.classify({"a": "1", "b": "2"}, {"a": "1", "c": "3"})
        assert got == {"added": ["c"], "removed": ["b"],
                       "changed": [], "unchanged": ["a"]}

    def test_report_has_all_slices(self):
        result = {s: {"added": [], "removed": [], "changed": [],
                      "unchanged": []} for s in csd.SLICES}
        report = csd.render_report(result, "test")
        for s in csd.SLICES:
            assert f"| {s} |" in report
        assert "0" in report

    def test_safe_value_masks_secret_like(self):
        assert csd.safe_value("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ012345") == \
            csd.SECRET_MASK
        assert csd.safe_value("plain-value") == "plain-value"

    def test_committed_report_exists(self):
        report = (ROOT / "plans/reports/round1025_f8_config_diff.md").read_text(
            encoding="utf-8")
        for s in csd.SLICES:
            assert f"| {s} |" in report
