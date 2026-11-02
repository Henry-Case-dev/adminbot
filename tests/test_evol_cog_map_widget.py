"""EVOL-COG-MAP (W7-S2) — виджет «Когнитивной карты» на новом payload.

TEST-LIFECYCLE: CONTRACT owner=EVOL-COG-MAP (W7-S2)
Контракт: `plans/features/evol/arch/cog-map-contract.md` §1/§4/§8 (слайс S2),
исходник: `plans/current_task.md` §2.1–§2.6 (строки 1242–1302).

Что доказывается:
  * виджет «Статуса» читает `GET /api/memory/cognitive-map` и НЕ читает
    старый `/api/memory/graph` (тот остаётся работоспособным серверным
    контрактом — его судьба в S4);
  * РЕАЛЬНЫЙ payload эндпоинта (`build_cognitive_map` на in-memory SQLite)
    проходит через настоящий адаптер `web/static/cognitive-map.js` и даёт
    рабочую модель: легенда словами владельца, кластеры по реальным связям,
    честное «показано X из Y», клиентское состояние `ready` при `partial`;
  * «показано X из Y» — НЕЙТРАЛЬНАЯ строка (серый текст, не предупреждение),
    включается по `totals > shown`, а не по `state`;
  * клиентские состояния (`loading/not_loaded/stale/renderer_failed`)
    отдельны от серверного `state` и отображаются честно;
  * старый маршрут `#/status/graph` и endpoint `/api/memory/graph` целы.

Запуск: pytest tests/test_evol_cog_map_widget.py -q
"""
import json
import os
import shutil
import subprocess
import sys

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# Хелперы/фикстуры S1 переиспользуются (одна фикстура на весь слайс).
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import test_evol_cog_map_api as S1  # noqa: E402  фикстуры/хелперы S1
from web.api import cognitive_map as cm  # noqa: E402


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


APP_JS = _read("web/app.js")
INDEX = _read("web/index.html")
CSS = _read("web/static/app.css")
ADAPTER = _read("web/static/cognitive-map.js")
MEMORY_API = _read("web/api/memory_agi.py")


def _block(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


def _map_block(html: str) -> str:
    """Разметка встраиваемого виджета карты (включая полноэкранный блок)."""
    start = html.index('data-cog-map')
    return html[start:html.index('Мониторинг Интеллекта', start)]


@pytest_asyncio.fixture
async def db():
    from services.database import DatabaseService
    service = DatabaseService(":memory:")
    await service.initialize()
    yield service
    await service.close()


# ── 1. данные: реальный payload → настоящий адаптер (node) ───────────────────

_NODE_PROBE = r"""
const path = require('path');
const CM = require(path.join(process.argv[2], 'web', 'static',
  'cognitive-map.js'));
const payload = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const model = CM.normalizePayload(payload, { aliases: {} });
const clusters = CM.computeClusters(model);
const clusters2 = CM.computeClusters(model);
const state = CM.mapClientState({ model: model, renderer: 'ready',
  now: (model.generatedAt + 60) * 1000 });
process.stdout.write(JSON.stringify({
  version: model.version,
  warnings: model.warnings,
  state: model.state,
  nodes: model.nodes.length,
  edges: model.edges.length,
  ids: model.nodes.map(function (n) { return n.id; }),
  kinds: model.nodes.map(function (n) { return n.kind; }),
  isolated: model.nodes.filter(function (n) { return n.isolated; }).length,
  completeness: CM.completeness(model.shownOf),
  legend: CM.legendEntries(model).map(function (e) {
    return [e.kind, e.label, e.required];
  }),
  shapes: CM.legendEntries(model).map(function (e) {
    return CM.nodeStyle(e.kind).shape;
  }),
  clusters: clusters.map(function (c) {
    return { id: c.id, size: c.size, label: c.label,
             dominant: c.dominantKind };
  }),
  clustersDeterministic: JSON.stringify(clusters) === JSON.stringify(clusters2),
  clientState: state,
  total: model.shownOf.totals,
}));
"""


def _run_node_probe(payload: dict, tmp_path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — проверка адаптера пропущена")
    script = tmp_path / "cog_probe.js"
    data = tmp_path / "payload.json"
    script.write_text(_NODE_PROBE, encoding="utf-8")
    data.write_text(json.dumps(payload), encoding="utf-8")
    res = subprocess.run([node, str(script), ROOT, str(data)],
                         capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.asyncio
async def test_real_payload_through_real_adapter(db, tmp_path):
    """Payload продакшн-сборки → адаптер: модель, легенда, кластеры, полнота."""
    await S1._seed_two_chats(db)
    payload = await cm.build_cognitive_map(db, S1.CHAT_A)
    probe = _run_node_probe(payload, tmp_path)

    assert probe["version"] == "cog-map/1"
    assert probe["warnings"] == [], probe["warnings"]
    assert probe["nodes"] > 0 and probe["edges"] > 0
    # Изоляция чатов на уровне данных: все ключи чат-квалифицированы.
    chat_prefix = ":%d:" % S1.CHAT_A
    assert all(i.startswith(("fact", "belief", "paradigm", "obs", "evt", "ent"))
               for i in probe["ids"])
    assert all(str(S1.CHAT_B) not in i for i in probe["ids"]), \
        "узел чужого чата попал в карту чата A"
    assert all(chat_prefix in i for i in probe["ids"]
               if i.startswith(("fact:", "belief:", "paradigm:", "obs:",
                                "evt:", "ent:"))), probe["ids"]

    # Честная полнота: снапшот отдаёт окрестность сидов + отбрасывает сирот.
    assert probe["total"]["nodes"] > probe["nodes"]
    assert probe["completeness"]["active"] is True
    text = probe["completeness"]["text"]
    assert text.startswith("показано %d из %d узлов"
                           % (probe["nodes"], probe["total"]["nodes"])), text
    assert not any(w in text.lower() for w in
                   ("ошибк", "сбой", "внимание", "предупрежд")), text
    # Серверный state при этом `partial` — это не ошибка, а норма.
    assert probe["state"] == "partial"
    assert probe["clientState"]["state"] == "ready", probe["clientState"]
    assert probe["clientState"]["serverState"] == "partial"

    # Легенда: слова владельца + различие не только цветом.
    required = [row for row in probe["legend"] if row[2]]
    assert [row[1] for row in required] == ["Факты", "Убеждения", "Парадигмы",
                                            "Изменения"]
    assert len({shape for shape in probe["shapes"][:4]}) == 4
    assert "Эволюция характера" not in [row[1] for row in probe["legend"]]

    # Кластеры по реальным связям, детерминированно.
    assert probe["clustersDeterministic"] is True
    assert sum(c["size"] for c in probe["clusters"]) == probe["nodes"]
    assert max(c["size"] for c in probe["clusters"]) >= 2, probe["clusters"]
    assert all(c["label"] for c in probe["clusters"])


# ── 2. разметка виджета ─────────────────────────────────────────────────────

def test_widget_markup_and_legend():
    block = _map_block(INDEX)
    assert 'data-cog-map' in block
    assert "Когнитивная карта" in block
    assert "Граф связей" not in block, "в виджете карты остался старый заголовок"
    # Легенда с четырьмя словами владельца, у каждого — свой тип.
    for kind, label in (("fact", "Факты"), ("belief", "Убеждения"),
                        ("paradigm", "Парадигмы"),
                        ("evolution_event", "Изменения")):
        assert 'cogLegend' in block
        assert label in INDEX
    assert "cog-legend__swatch--fact" in CSS
    assert "cog-legend__swatch--paradigm" in CSS
    assert "clip-path" in CSS            # форма, не только цвет
    # Контролы паритета: поиск по имени/алиасу, тип, кластер, сброс, fullscreen.
    assert 'graph-search__input' in block
    assert 'v-model="graphFilterGroup"' in block
    assert 'v-model="cognitionMapCluster"' in block
    assert "@click=\"graphResetView()\"" in block
    assert "@click=\"openGraphFull()\"" in block
    # Та же позиция в сетке «Статуса» и тот же маршрут полного экрана.
    assert 'class="card p-4 status-graph sg-12"' in INDEX
    assert 'class="status-graph-full"' in INDEX
    assert 'ref="graphFullPanel"' in INDEX


def test_completeness_line_is_neutral():
    """«Показано X из Y» — нейтральный текст, а не предупреждение/ошибка."""
    start = INDEX.index("data-cog-completeness")
    line_start = INDEX.rindex("<span", 0, start)
    tag = INDEX[line_start:INDEX.index(">", start) + 1]
    assert "text-gray-500" in tag, tag
    assert "amber" not in tag and "red" not in tag, tag
    assert "data-cog-completeness" in tag

    # Включается по полноте данных (`cogCompleteness.active`), не по `state`.
    assert 'v-if="cogCompleteness.active' in INDEX
    assert "state === 'partial'" not in INDEX
    assert "state === 'partial'" not in APP_JS

    # Само правило — pure-функция адаптера: `totals > shown`.
    assert "totalNodes > nodes" in ADAPTER
    assert "totalEdges > edges" in ADAPTER
    # Текст собирается без оценок и причин.
    body = _block(ADAPTER, "function completeness(shownOf) {", "/* mapClientState")
    assert "показано " in body
    assert "ошибк" not in body.lower()


def test_client_states_mapped_honestly():
    block = _block(APP_JS, "renderCognitionGraph: async function () {",
                   "_cogApplyData: function")
    assert "ensureVisNetwork" in block
    assert "cognitionMapVisMissing = true" in block  # not_loaded
    assert "cognitionMapFailed = true" in block      # renderer_failed
    assert "CognitiveMap" in APP_JS
    # Клиентское состояние считается отдельно от серверного `state`.
    state_fn = _block(APP_JS, "_cogClientState: function () {",
                      "searchCognitionGraph: async function")
    assert "mapClientState" in state_fn
    assert "COG_MAP_STALE_MS" in state_fn
    assert "this.cognitionNetwork" in state_fn
    for marker in ("loading", "not_loaded", "stale", "renderer_failed"):
        assert marker in ADAPTER, marker
    # Шаблон показывает состояние честно (data-cog-state + подпись).
    assert ':data-cog-state="cogClientState.state"' in INDEX
    assert "cogClientState.note" in INDEX


# ── 3. источник данных и судьба старого контракта ───────────────────────────

def test_widget_reads_new_endpoint_only():
    assert "COG_MAP_ENDPOINT = '/api/memory/cognitive-map'" in APP_JS
    load = _block(APP_JS, "loadCognitionGraph: async function () {",
                  "_graphSignature: function")
    assert "COG_MAP_ENDPOINT" in load
    assert "normalizePayload" in load
    assert "/api/memory/graph" not in load, \
        "виджет всё ещё читает legacy-снапшот"
    # Загрузка висит на существующем cognition-polling (без нового поллера).
    assert "this.loadCognitionGraph();" in APP_JS


def test_legacy_route_and_api_stay_alive():
    # Маршрут полного экрана и родитель — не тронуты (retirement — S4).
    assert "'#/status/graph': 'status'" in APP_JS
    assert "'#/status/graph': '#/'" in APP_JS
    # Старый серверный контракт продолжает существовать.
    assert '"/memory/graph"' in MEMORY_API or "'/memory/graph'" in MEMORY_API
    assert "memory/graph" in MEMORY_API
    # Legacy-рендер удалён из продукта, vis-network остаётся self-host.
    assert "'/static/vendor/vis-network/vis-network.min.js'" in APP_JS
    assert "cdn.jsdelivr.net" not in INDEX
    assert "unpkg.com" not in INDEX


def test_adapter_loaded_before_app():
    assert "/static/cognitive-map.js" in INDEX
    assert INDEX.index("/static/cognitive-map.js") < INDEX.index("/web/app.js")
    # Zero-build: обычный внешний файл, без inline-инициализации и CDN.
    assert "<script src=\"/static/cognitive-map.js" in INDEX
    assert "window.CognitiveMap" in ADAPTER


def test_no_second_graph_engine_or_new_dependency():
    # Ни одной новой библиотеки: рендер — существующий vis-network.
    for banned in ("cytoscape", "d3-force", "d3.min.js", "sigma"):
        assert banned not in INDEX.lower()
    # Данные карты не уходят в LLM/эмбеддинги при рендере.
    render = _block(APP_JS, "renderCognitionGraph: async function () {",
                    "_cogClientState: function")
    for banned in ("/api/memory/embeddings", "/api/llm", "summarize"):
        assert banned not in render
    # Клиентский слой не делает сетевых вызовов (чистые функции адаптера).
    assert "fetch(" not in ADAPTER
    assert "XMLHttpRequest" not in ADAPTER


# ── 4. node-набор адаптера (S1 + S2 проверки) ───────────────────────────────

def test_adapter_node_suite_runs():
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    res = subprocess.run(
        [node, os.path.join("tests", "js", "evol_cognitive_map_test.js")],
        capture_output=True, text=True, timeout=90, cwd=ROOT)
    assert res.returncode == 0, res.stderr
    assert "EVOL-COG-MAP-S1-OK" in res.stdout
    assert "EVOL-COG-MAP-S2-OK" in res.stdout
