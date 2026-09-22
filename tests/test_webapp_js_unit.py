"""Редизайн 10.5 (Reviewer D1/D2) — РЕАЛЬНЫЕ JS-тесты (node), не grep.

Запускает tests/js/routing_test.js в stubbed-окружении: проверяет hub-aware
RBAC-гейт (D1) и отбрасывание устаревших in-flight ответов scope (D2).
Пропускается, если node недоступен.
"""
import os
import shutil
import subprocess

import pytest


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    return node


def _run_js(script: str, ok_marker: str = "JS-UNIT-OK"):
    node = _node()
    assert os.path.exists(script)
    res = subprocess.run(
        [node, script],
        capture_output=True, text=True, timeout=60,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert res.returncode == 0, (
        "JS-UNIT провалился (%s):\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (script, res.stdout, res.stderr))
    assert ok_marker in res.stdout


def test_js_unit_routing_and_scope_guard():
    _run_js(os.path.join("tests", "js", "routing_test.js"))


def test_js_unit_round1021_ui_audit():
    """F6 round 10.21 (T-1990…T-2000): регресс-зонды UI-аудита —
    glass/grid/mask/gradient/sticky + инвариант меню + регресс
    `_syntheticGroup` (метод, а не computed)."""
    _run_js(os.path.join("tests", "js", "round1021_ui_audit_test.js"))


def test_js_unit_round1022_aliases():
    """F2 round 10.22 (T-2032): KV-редактор `summary_aliases` рендерит пары из
    объекта И из строки-JSON (двойное кодирование) — регресс-гейт."""
    _run_js(os.path.join("tests", "js", "round1022_aliases_test.js"),
            ok_marker="ALIASES-UNIT-OK")


def test_js_unit_round1022_dossier_rebuild():
    """F8 round 10.22 (ADR-1022-8): фронт пересборки досье — статусы/job-view,
    POST period, 409-подхват, отмена+rollback-статус, polling, localStorage."""
    _run_js(os.path.join("tests", "js", "round1022_dossier_rebuild_test.js"),
            ok_marker="DOSSIER-REBUILD-UNIT-OK")


def test_js_unit_round1023_verbilizer_tabs():
    """F8 round 10.23 (ADR-1023-8): stage-секции «Промпты», Tabs режимов,
    блок анти-клише (force/PUT/fail-open)."""
    _run_js(os.path.join("tests", "js", "round1023_verbilizer_tabs_test.js"),
            ok_marker="VERBILIZER-UNIT-OK")


def test_js_unit_round1024_nodeflow():
    """F3 round 10.24 (ADR-1024-7): визуальное дерево вызова (Node Flow) —
    проекция steps[] (двухслойный/tool/single/image/пусто), нейминг,
    kill-switch uiFlag (OFF → бейджи), CSP/no-CDN."""
    _run_js(os.path.join("tests", "js", "round1024_nodeflow_test.js"),
            ok_marker="NODEFLOW-UNIT-OK")


def test_js_unit_round1024_image_module():
    """F5 round 10.24 (ADR-1024-9): карточка «Генерация изображений» в
    «Модулях» — toggleKey/tab/icon, вкладка mod_images с группой
    flags_module_images (один дом), menu-freeze +1, гейт uiFlag."""
    _run_js(os.path.join("tests", "js", "round1024_image_module_test.js"),
            ok_marker="IMAGE-MODULE-OK")


def test_js_unit_round1024_prompts_ui():
    """F6 round 10.24 (ADR-1024-10): плоский grid «Промптов» (без аккордеонов),
    fallback-режим → casual, табы режимов внутри карточек модулей."""
    _run_js(os.path.join("tests", "js", "round1024_prompts_ui_test.js"),
            ok_marker="PROMPTS-UI-UNIT-OK")


def test_js_unit_round1024_image_key():
    """F11 round 10.24 (ADR-1024-12): image-секрет → PUT /api/config/keys/own
    (global), не в общий POST; маска → 0 запросов; GET-режим disable+clear."""
    _run_js(os.path.join("tests", "js", "round1024_image_key_test.js"),
            ok_marker="IMAGE-KEY-OK")


def test_js_unit_round1024_aliases_render():
    """F10 round 10.24 (ADR-1024-11): РЕАЛЬНЫЙ render-тест kv-editor — значение
    из API отрисовывается при монтировании, deep-watch на замену/мутацию
    `item` (регресс shallow-бага), массив пар, Empty State, индикатор
    источника и kill-switch (OFF → прежний path-watcher)."""
    _run_js(os.path.join("tests", "js", "round1024_aliases_render_test.js"),
            ok_marker="ALIASES-RENDER-OK")


def test_js_unit_round1024_dossier_feed():
    """F4 round 10.24 (ADR-1024-8): вертикальная кликабельная «Живая лента
    досье» — dossierFeedLoop/скорость, клик-путь GLOBAL→чат→досье (UPD3 №9),
    a11y (клоны aria-hidden/без таб-стопа), kill-switch uiFlag."""
    _run_js(os.path.join("tests", "js", "round1024_dossier_feed_test.js"),
            ok_marker="DOSSIER-FEED-OK")


def test_js_unit_round1025_hotfix4_shell():
    """hotfix4 round 10.25 (ADR-1025-8 D2, T-2518): позиция mobile-панели —
    `--tg-viewport-bottom-offset` + CSS-фолбэк, `viewport-fit=cover`,
    touch/safe-area сохранены, матрица проверяет вертикаль."""
    _run_js(os.path.join("tests", "js",
                         "round1025_hotfix4_shell_test.js"),
            ok_marker="JS-UNIT-OK round1025_hotfix4_shell_test")


def test_js_unit_round1024_providers_fullscreen():
    """F24 round 10.24 (ADR-1024-24): fullscreen-sync с TMA + реактивный
    аккордеон — initExpandState/переживание ремаунта, C2 (синхронизация из
    $event, идемпотентность), подписки/отписки fullscreen, безопасность вне TG."""
    _run_js(os.path.join("tests", "js",
                         "round1024_providers_fullscreen_test.js"),
            ok_marker="PROVIDERS-FS-OK")


def test_js_unit_round1025_scope_selector():
    """F3 round 10.25 (§5/§42/§43/§70): селектор области — три режима
    (Глобально/Чат/ЛС), отсутствие смешивания значений/черновиков, отброс
    stale-ответов старого scope, источник значения (global vs override),
    «Вернуть глобальное значение» = DELETE override, предупреждение при
    несохранённых правках."""
    _run_js(os.path.join("tests", "js",
                         "round1025_scope_selector_test.js"),
            ok_marker="SCOPE-SELECTOR-OK")


def test_js_unit_round1025_hotfix6_lens_heartbeat_shell():
    """hotfix6 round 10.25 (ADR-1025-12, T-2583…T-2613): линза-преломление без
    backdrop url-фильтра (feature-detect+кап), offset max(A,B,C),
    Canvas-2D §15 (гистерезис/UNKNOWN/телеметрия отдельно), двухстрочная шапка
    + резерв --header-h + fullscreen."""
    _run_js(os.path.join("tests", "js",
                         "round1025_hotfix6_lens_heartbeat_shell_test.js"),
            ok_marker="HOTFIX6-LENS-HEARTBEAT-SHELL-OK")


def test_js_unit_round1025_hotfix7_shell_glass_heartbeat():
    """hotfix7 round 10.25 (ADR-1025-13, T-2658…T-2694): единый `--shell-h` +
    два режима normal/fullscreen (legacy-откат UI_SHELL_LAYOUT_V2), premium
    ECG sweep-wipe (нет pulseX, off-путь canvas-legacy UI_HEARTBEAT_PREMIUM),
    серо-графитовый `--shell-*`-слой + specular/texture (UI_SHELL_GLASS_V2),
    env-only флаги в settings/routes, матрица 5 режимов."""
    _run_js(os.path.join("tests", "js",
                         "round1025_hotfix7_shell_glass_heartbeat_test.js"),
            ok_marker="HOTFIX7-SHELL-GLASS-HEARTBEAT-OK")


def test_js_unit_round1025_hotfix8_shell_aurora():
    """hotfix8 round 10.25 (ADR-1025-16, T-2748…T-2782): shell v3 §4
    (`data-glass="shell"`, снятие цветной линзы A, sidebar 208–224px),
    aurora/mesh (5 blob + legacy `bg-wash-legacy`), env-only флаги."""
    _run_js(os.path.join("tests", "js",
                         "round1025_hotfix8_shell_aurora_test.js"),
            ok_marker="HOTFIX8-SHELL-AURORA-OK")


def test_js_unit_round1025_hotfix9_shell_flex_glass_aurora():
    """hotfix9 round 10.25 (ADR-1025-17, T-2793…T-2836): единый источник
    `--app-usable-height` (+ алиас `--shell-h`), flex-колонка shell-mobile/
    fullscreen, nav в потоке (не fixed), модалка modal-actions, полное удаление
    `--shell-texture`, графитовые токены §8, vendored Liquid Glass/OGL
    (same-origin, CSP-safe), Dark Aurora Flow, env-only флаги, APP_VERSION."""
    _run_js(os.path.join("tests", "js",
                         "round1025_hotfix9_shell_flex_glass_aurora_test.js"),
            ok_marker="HOTFIX9-SHELL-FLEX-GLASS-AURORA-OK")


def test_js_unit_round1025_hotfix10_glass_geometry_bg():
    """hotfix10 round 10.25 (ADR-1025-18, T-2843…T-2864): откат стекла с
    функциональных целей + GlassSurface, единая рабочая поверхность Main, единая
    высота без двойного safe-area, resize OGL-фона (fullscreen/viewport),
    APP_VERSION (bumped hotfix10→F6 2.58.14)."""
    _run_js(os.path.join("tests", "js",
                         "round1025_hotfix10_glass_geometry_bg_test.js"),
            ok_marker="HOTFIX10-GLASS-GEOMETRY-BG-OK")


def test_js_unit_round1025_f4_module_store():
    """F4 round 10.25 (ADR-1025-14 D1/D2): ModuleConfigurationStore —
    ключ scope_type/scope_id/module_id, одна мутация на действие,
    in-flight guard, структурный откат §41, stale §42, счётчики §45,
    поиск/синонимы §44, избранное в localStorage §34–§36, §72/§73."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f4_module_store_test.js"),
            ok_marker="MODULE-STORE-OK")


def test_js_unit_round1025_f4_catalog_ui():
    """F4 round 10.25 (§32–§35/D6/D7): структура страницы «Модули», сетка
    каталога ≤3/2/1 и панели ≤4/2/2–1, тач-цель ≥44×44, «карточка ≠ тумблер»,
    «Настроить» → openModuleWorkspace → openModuleWindow, нет карусели."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f4_catalog_ui_test.js"),
            ok_marker="MODULE-CATALOG-OK")


def test_js_unit_round1025_f5_workspace_route():
    """F5 round 10.25 (ADR-1025-15 D1/D2/D6, §46): workspace-маршрут
    `#/modules/<slug>[/<wt>[/<stage>/<key>]]`, routeToTab = m.tab
    (RBAC/kill-switch), неизвестный slug → витрина, шов openModuleWorkspace →
    страница + fallback openModuleWindow, тумблер из store F4, инвариант
    покрытия групп."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f5_workspace_route_test.js"),
            ok_marker="MODULE-WORKSPACE-OK")


def test_js_unit_round1025_f5_models():
    """F5 round 10.25 (ADR-1025-15 D4/§49): 6 групп «Моделей и подключений»
    (каждый блок ровно раз), advanced-блоки, workspace-модели модуля,
    «Проверить» → /api/llm/test,/api/images/test, §49 «сохранённая модель не
    подменяется» (0 POST при открытии), R17."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f5_models_test.js"),
            ok_marker="MODELS-GROUPS-OK")


def test_js_unit_round1025_f5_prompts_single_source():
    """F5 round 10.25 (ADR-1025-15 D3/§48/§85): «один промпт — один источник»
    (два маршрута → один configItem `prompts.*`), фокус промпта, редактор не в
    аккордеоне, один write-path, две двери-маршрута, канон не в web."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f5_prompts_single_source_test.js"),
            ok_marker="PROMPTS-SINGLE-SOURCE-OK")


def test_js_unit_round1025_f6_execution_graph():
    """F6 round 10.25 (ADR-1025-19 D1/D2/D8, §24/§25/§28): adapter
    ExecutionGraph — одно-/двухслойный вызов, tool без parent_id, unknown
    шаг, неизвестная цена, агрегат, фильтры, расширяемость enum."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f6_execution_graph_test.js"),
            ok_marker="F6-EXECGRAPH-OK")


def test_js_unit_round1025_f6_analytics_memory():
    """F6 round 10.25 (ADR-1025-19 D2–D8, §21–§29/§52–§59/§75/§76/§116):
    4 режима карты, фильтры L1/L2/модель/модуль, честные состояния §28,
    превью Статуса §21, mobile §29, мониторинг §76, одна система §116."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f6_analytics_memory_test.js"),
            ok_marker="F6-ANALYTICS-MEMORY-OK")


def test_js_unit_round1025_f7_permsoc_local():
    """F7 round 10.25 (ADR-1025-20 D1–D7, §60–§67): PERMsoc — локальное
    пространство чата. Без чата блоков нет; 6 блоков + partition «ключ ровно
    в одном блоке»; guard «PERMsoc-ключ не пишется в global»; OFF блока
    сохраняет дочерние; блок-гейты reactions/schedule + kill-switch;
    единицы kostik_reply_probability (round-trip 0–1 ↔ 0–100 %)."""
    _run_js(os.path.join("tests", "js",
                         "round1025_f7_permsoc_local_test.js"),
            ok_marker="F7-PERMSOC-LOCAL-UNIT-OK")
