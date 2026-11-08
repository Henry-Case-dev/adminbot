"""EVOL-COG-MAP (W7-S2/S3) — виджет «Когнитивной карты» на новом payload.

TEST-LIFECYCLE: CONTRACT owner=EVOL-COG-MAP (W7-S2/S3)
Контракт: `plans/features/evol/arch/cog-map-contract.md` §1/§4/§8/§9 (слайсы
S2–S3), исходник: `plans/current_task.md` §2.1–§2.6 (строки 1242–1302).

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
  * S3: карточка узла/ребра — один общий слой (панель справа / нижний лист),
    поля только из payload, честное «не записано», четыре адресных перехода,
    Back/Esc закрывают карточку первой, камера и выбор сохраняются;
  * старый маршрут `#/status/graph` и endpoint `/api/memory/graph` целы.

Запуск: pytest tests/test_evol_cog_map_widget.py -q
"""
import json
import os
import re
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
# CMV-A (EPIC-CM-VISUAL-01): единый визуальный преобразователь карты.
VISUAL = _read("web/static/cog-visual.js")


def _block(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


def _media_block(css: str, query: str, selector: str) -> str:
    """Тело `@media <query>`, внутри которого реально описано `selector`.

    В файле несколько одинаковых медиа-запросов; «первый попавшийся» проверял
    бы чужой блок. Скобки считаем, чтобы срез не выходил за пределы запроса.
    """
    needle = "@media (%s) {" % query
    pos = 0
    while True:
        pos = css.find(needle, pos)
        if pos < 0:
            raise AssertionError("@media (%s) с %s не найден" % (query, selector))
        depth, end = 0, pos
        for end in range(css.index("{", pos), len(css)):
            if css[end] == "{":
                depth += 1
            elif css[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        body = css[pos:end + 1]
        if selector in body:
            return body
        pos = end + 1


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

def _legend_binding(html_block: str) -> dict:
    """Как шаблон связывает легенду: тип ↔ метка ↔ swatch.

    Метки легенды — динамические (`v-for="lg in cogLegend"`), поэтому
    разметка обязана привязывать КАЖДУЮ строку к своему типу и брать текст
    из адаптера; сами слова владельца проверяются в node-тесте адаптера
    (`legendEntries().filter(required)`), а не «поиском слова в документе».
    """
    start = html_block.index('data-cog-legend')
    block = html_block[start:html_block.index(">", start) + 1]
    tail = html_block[start:html_block.index("</div>", start) + 6]
    return {
        "block": tail,
        "for": 'v-for="lg in cogLegend"' in tail,
        "kind_binding": ':data-cog-legend-kind="lg.kind"' in tail,
        "label_binding": "{{ lg.label }}" in tail,
        # swatch-класс строится из типа строки, а не захардкожен одной формой
        "swatch_binding": "cog-legend__swatch--' + lg.kind" in tail,
    }


def test_widget_markup_and_legend():
    block = _map_block(INDEX)
    assert 'data-cog-map' in block
    assert "Когнитивная карта" in block
    assert "Граф связей" not in block, "в виджете карты остался старый заголовок"
    # Легенда в разметке: строка на каждый класс модели, тип и метка берутся
    # из одного источника (адаптер), swatch — по типу.
    binding = _legend_binding(block)
    assert binding["for"], "нет перебора строк легенды"
    assert binding["kind_binding"], "строка легенды не привязана к типу"
    assert binding["label_binding"], "метка легенды не берётся из адаптера"
    assert binding["swatch_binding"], "swatch не привязан к типу"
    # Форма на каждый ОБЯЗАТЕЛЬНЫЙ класс — в CSS (не только цвет).
    for kind in ("fact", "belief", "paradigm", "evolution_event",
                 "entity", "observation"):
        assert "cog-legend__swatch--" + kind in CSS, kind
    assert "clip-path" in CSS            # форма, не только цвет
    # MEM-08-S3 (SC-21/SC-28, MEM-08.28): в обычном режиме контролы ровно
    # ОДНОГО поля «Найти в памяти»; прежний toolbar (тип/кластер/«Найти»)
    # остаётся только как аварийный OFF-паритет гейта (§4.10), поэтому
    # `v-model="graphFilterGroup"`/`v-model="cognitionMapCluster"` живут в
    # ветке `v-if="!cogSearchEnabled"`, а не в видимой строке.
    assert 'graph-search__input' in block
    assert 'data-cog-legacy-search' in block
    assert 'v-if="!cogSearchEnabled"' in block
    assert 'v-model="cogSearch.query"' in block
    assert 'v-model="graphFilterGroup"' in block      # только OFF-паритет
    assert 'v-model="cognitionMapCluster"' in block   # только OFF-паритет
    assert "@click=\"graphResetView()\"" in block
    assert "@click=\"openGraphFull()\"" in block
    # Та же позиция в сетке «Статуса» и тот же маршрут полного экрана.
    assert 'class="card p-4 status-graph sg-12"' in INDEX
    assert 'class="status-graph-full"' in INDEX
    assert 'ref="graphFullPanel"' in INDEX


def test_mem08_s3_single_omnibox_in_both_views():
    """MEM-08-S3/SC-21/SC-28: ОДНО поле «Найти в памяти» в обоих видах.

    Второй поисковой формы/строки нет (MEM-08.14, INV-15); оба блока
    (встроенная карта и полный экран) читают ОДНО состояние `cogSearch` и
    взаимоисключающи по `graphFullVisible` — прежний toolbar остаётся только
    как аварийный OFF-паритет гейта (§4.10).
    """
    embedded = _map_block(INDEX)
    full = _fs_block(INDEX)
    for name, block in (("встроенный", embedded), ("полный экран", full)):
        assert block.count('data-cog-omni role="search"') == 1, name
        assert block.count("data-cog-omni-input") == 1, name
        assert block.count('aria-label="Найти в памяти"') == 1, name
        assert 'v-model="cogSearch.query"' in block, name
        assert '@keydown="cogSearchKeydown($event)"' in block, name
        assert 'placeholder="Человек, событие, факт или вопрос…"' in block, name
        assert 'data-cog-search-state' in block, name
        assert 'data-cog-legacy-search' in block, name
        assert 'data-cog-communities=' in block, name
        # Второй модели/второго поля в блоке нет.
        assert 'graphSearchQuery' in block      # только OFF-ветка
    # Один и тот же state используется ровно в двух (взаимоисключающих) местах.
    assert INDEX.count('v-model="cogSearch.query"') == 2
    assert "cogSearch: {" in APP_JS
    assert "COG_SEARCH_ENDPOINT = '/api/memory/search'" in APP_JS
    assert 'cogFsSearch' not in APP_JS and 'fullscreenSearch' not in APP_JS
    # Стили omnibox: прикреплённая панель + safe-area + reduced-motion.
    assert ".cog-omni__panel" in CSS and "max-height" in CSS
    assert "env(safe-area-inset-bottom" in CSS
    assert "prefers-reduced-motion" in CSS


def test_visible_status_is_single_worst_fact():
    """§9.1: одна видимая строка статуса; «пусто» и «отказ» не сосуществуют."""
    embedded = _map_block(INDEX)
    full = INDEX[INDEX.index('class="status-graph-full"'):]
    full = full[:full.index("Мониторинг") if "Мониторинг" in full
                else len(full)]
    for name, block in (("встроенный", embedded), ("полный экран", full)):
        assert block.count('v-if="cogStatus.kind !== \'ready\'"') == 1, name
        assert block.count('data-cog-degraded') == 1, name
        assert block.count('v-else-if="cogFilterEmpty"') == 1, name
        assert "text-amber-300" in block, name
        assert "cogStatus.degraded" in block, name
        assert "cogViewCounters" in block, name
        # Контракт §4: пустота ведёт в «Память» и в полном экране тоже.
        assert "openMemoryFromCogMap()" in block, name
    # Порядок приоритетов закреплён в адаптере (§9.1).
    body = _block(ADAPTER, "function mapClientState(opts) {",
                  "  return {\n    VERSION: VERSION,")
    assert "else if (degradedActive) noticeKind = 'degraded';" in body
    assert "else if (dataEmpty) noticeKind = 'empty';" in body
    order = [body.index("noticeKind = 'renderer_failed'"),
             body.index("noticeKind = 'not_loaded'"),
             body.index("noticeKind = 'loading'"),
             body.index("noticeKind = 'degraded'"),
             body.index("noticeKind = 'empty'"),
             body.index("noticeKind = 'stale'"),
             body.index("noticeKind = 'ready'")]
    assert order == sorted(order), "приоритет видимой заметки нарушен"
    assert "var dataEmpty = degradedActive ? false" in body, \
        "empty не должен объявляться при отказе источника"
    # Пустая витрина (фильтр) — отдельный факт вида, а не пустота данных.
    assert "var viewEmpty = !dataEmpty && visibleNodes === 0" in body


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
    # Реактивность витрины (B1): computed/шаблон читают ТОЛЬКО поля из `data`,
    # а не внутренние `_cog*` (иначе DOM показывает прошлый кадр).
    data_block = _block(APP_JS, "cognitionMapCluster: '',",
                        "_cognitionGraphSig: null,")
    assert "cogViewNodes: 0" in data_block
    assert "cogViewEdges: 0" in data_block
    assert "this.cogViewNodes" in state_fn, \
        "клиентское состояние должно читать реактивный счётчик витрины"
    assert "this._cogView" not in state_fn, \
        "нереактивное `_cogView` не должно попадать в computed-цепочку"
    # Шаблон показывает состояние честно (data-cog-state + подпись).
    assert ':data-cog-state="cogStatus.kind"' in INDEX
    assert "cogStatus.text" in INDEX


def test_empty_to_data_recreates_scene_and_keeps_counters_honest():
    """B1: переход 0→N пересоздаёт сеть/делает fit и не оставляет «пусто»."""
    render = _block(APP_JS, "renderCognitionGraph: async function () {",
                    "_cogApplyData: function")
    assert "var prevViewNodes = this.cogViewNodes;" in render
    assert "emptyToData" in render, \
        "переход 0→N не отличим от обычного обновления (узлы уйдут за кадр)"
    assert "&& !emptyToData" in render
    assert "this.cogViewNodes = (view.nodes || []).length;" in render
    assert "this.cogViewEdges = (view.edges || []).length;" in render
    # «Пусто по фильтру» не может висеть при непустой витрине: оба числа —
    # из одного реактивного источника, а пустота вида отделена от пустоты
    # данных (`viewEmpty` против `dataEmpty`).
    filt = _block(APP_JS, "cogFilterEmpty: function () {",
                  "// F11 (§19/D5)")
    assert "this._cogClientState().viewEmpty === true" in filt
    assert "cogStatus.kind !== 'ready'" in filt


def test_camera_captured_after_animation_finished():
    """B4: установившийся вид снимается на `animationFinished`."""
    net = _block(APP_JS, "_cogCreateNetwork: function (",
                 "_cogRedraw: function")
    assert "net.on('animationFinished'" in net, \
        "камера не снимается после анимации — сохранённый вид отстаёт"
    assert "_cogCaptureCamera()" in net


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
    # Старый серверный контракт продолжает существовать (маршрут ручки).
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
    assert "EVOL-COG-MAP-S3-OK" in res.stdout


# ── 5. W7-S3: карточка узла/ребра, обоснование связи, адресные переходы ─────

def _card_block() -> str:
    start = INDEX.index('id="cog-card"')
    return INDEX[start:INDEX.index("</template>", INDEX.index(
        "data-cog-edge-provenance"))]


def test_card_is_one_shared_layer():
    """Карточка — ОДИН слой для встроенной карты и полного экрана."""
    assert INDEX.count('id="cog-card"') == 1, \
        "карточка размножена по разметке (два источника правды)"
    block = _card_block()
    assert 'role="dialog"' in block and 'aria-modal="true"' in block
    assert 'tabindex="-1"' in block
    assert '@keydown="cogCardKeydown($event)"' in block
    assert 'data-cog-card-close' in block, "нет способа закрыть карточку"
    assert ':data-cog-card="cogCard.kind"' in block
    assert ':data-cog-card-id="cogCard.id"' in block
    # Прежний встроенный бейдж-блок удалён: запись не показывается дважды.
    assert "data-cog-detail" not in INDEX
    # Модель карточки строит адаптер, а не шаблон.
    assert "nodeCard: nodeCard" in ADAPTER and "edgeCard: edgeCard" in ADAPTER


def test_card_shows_fields_from_payload_only():
    """Разметка читает поля модели карточки; отсутствующее названо словами."""
    block = _card_block()
    for marker in ("cogCard.text || cogCard.textNote",
                   "cogCard.timesNote",
                   "cogCard.metrics.note",
                   "cogCard.history.reason",
                   "cogCard.justification.text",
                   "cogCard.provenance.messageId",
                   "cogCard.provenance.sourceIds",
                   "cogCard.provenance.sourceRefs",
                   "cogCardScopeLabel"):
        assert marker in block, marker
    # Три-четыре даты подписаны по отдельности (label приходит из адаптера).
    assert ':data-cog-time="t.key"' in block
    assert "{{ t.label }}" in block
    # Метрики подписаны природой значения, а не «уверенностью».
    assert "{{ m.nature }}" in block
    assert "confidence" not in block and "freshness" not in block
    # Ребро: обоснование берётся из payload, а не сочиняется в шаблоне.
    assert ':data-cog-justification-recorded="cogCard.justification.recorded ? ' \
           "'1' : '0'\"" in block


def test_card_buttons_are_address_transitions_not_decorations():
    """Четыре действия: цель — конкретный объект, у неработающего — причина."""
    block = _card_block()
    assert 'v-for="act in cogCard.actions"' in block
    assert ':data-cog-action="act.id"' in block
    assert ':disabled="!act.enabled"' in block
    assert ':data-cog-action-reason="act.id"' in block, \
        "неработающее действие молчит (декоративная кнопка)"
    body = _block(APP_JS, "cogCardAction: function (id, ev) {",
                  "openCogHistory: function () {")
    for marker in ("openCogSource(ev)", "openCogHistory()",
                   "openMemoryFromCogMap(card)", "cogShowLinks()"):
        assert marker in body, marker
    assert "act.reason || 'действие недоступно'" in body, \
        "отказ действия не сообщается пользователю"
    # «Открыть источник» — существующее окно записи ТОЙ ЖЕ записи + drill.
    src = _block(APP_JS, "openCogSource: function (ev) {",
                 "openCogHistory: function () {")
    assert "this.openStatusRecord(t.source" in src
    assert "statusRecordDrill" in src
    assert "t.me/" not in src and "telegram.me" not in src, \
        "выдуманная ссылка на сообщение"
    # «История изменений» ведёт к конкретному узлу модели.
    hist = _block(APP_JS, "openCogHistory: function () {",
                  "_cogSelectNode: function")
    assert "act.target.id" in hist
    assert "openCogNodeCard(targetId" in hist


def test_card_transitions_do_not_invent_or_request():
    """Открытие карточки не делает запросов и не двигает камеру."""
    for name, end in (("openCogNodeCard: function (nodeId, opts) {",
                       "openCogEdgeCard: function (edgeId, opts) {"),
                      ("openCogEdgeCard: function (edgeId, opts) {",
                       "_cogRefreshCard: function () {")):
        body = _block(APP_JS, name, end)
        for banned in ("this.api(", "fetch(", "net.fit(", "net.focus(",
                       "moveTo(", "_cogCaptureCamera()"):
            assert banned not in body, (name, banned)
    # Камера и фильтры при закрытии не сбрасываются: closeCogCard только
    # снимает слой и возвращает фокус сцене.
    close = _block(APP_JS, "closeCogCard: function () {",
                   "cogCardKeydown: function (ev) {")
    for banned in ("_cogCamera =", "fit(", "graphFilterGroup =",
                   "cognitionMapCluster =", "renderCognitionGraph"):
        assert banned not in close, banned
    assert "_cogGraphEl()" in close and "focus(" in close, \
        "фокус не возвращается на сцену с выбранным узлом"


def test_memory_transition_keeps_node_context_and_is_honest():
    body = _block(APP_JS, "openMemoryFromCogMap: function (card) {",
                  "_cogCardFind: function (card, id) {")
    assert "this.memoryCatalogQuery = target ? String(target.query || '')" in body
    assert "this.memoryCatalogType = target ?" in body
    assert "navTo('#/memory')" in body
    note = _block(APP_JS, "cogMemoryNote: function () {",
                  "// F11 (§19/D5)")
    assert "в каталоге «Памяти» сейчас нет" in note
    assert "ещё не загружен" in note
    assert 'data-memory-from-cog' in INDEX, \
        "честная заметка о отсутствии записи не показана пользователю"


def test_memory_catalog_relation_uses_human_label():
    """Каталог «Памяти» — адрес перехода из карточки: без машинных строк.

    `derived_from` в списке связей каталога читается как обрывок кода и
    обесценивает переход «Открыть в Памяти» из карточки.
    """
    body = _block(APP_JS, "// 3) Связи", "// 4) Контекст")
    assert "C.relationLabel(e.relation)" in body
    assert "body: e.relation ||" not in body, \
        "каталог показывает машинный тип связи (derived_from)"


def test_show_links_is_not_undone_by_reselection():
    """«Показать связи» не сворачивает себя повторным показом записи.

    Программное выделение узла (`selectNodes`) поднимает `selectNode`, а тот
    обновляет открытую карточку. Безусловный сброс `cogCardLinksExpanded` там
    означал бы, что кнопка отменяет собственное действие (живой прогон 390:
    «Показать связи» не раскрыло список).
    """
    node = _block(APP_JS, "openCogNodeCard: function (nodeId, opts) {",
                  "openCogEdgeCard: function (edgeId, opts) {")
    edge = _block(APP_JS, "openCogEdgeCard: function (edgeId, opts) {",
                  "_cogRefreshCard: function () {")
    assert "if (!same) this.cogCardLinksExpanded = false;" in node
    assert "if (!sameEdge) this.cogCardLinksExpanded = false;" in edge
    for body in (node, edge):
        # Ровно ОДИН сброс и только под условием «это другая запись».
        assert body.count("cogCardLinksExpanded = false") == 1, \
            "показ той же записи сворачивает раскрытые связи"
    links = _block(APP_JS, "cogShowLinks: function () {",
                   "// Клик по ребру снимает выделение")
    assert "this.cogCardLinksExpanded = true;" in links
    assert "_cogSelectNode(card.id)" in links


def test_card_is_back_stack_layer_and_keyboard_reachable():
    layers = _block(APP_JS, "function backStackLayers(vm) {",
                    "// Закрывает РОВНО один (верхний) слой")
    assert "if (vm.cogCardOpen) ids.push('cog-card');" in layers
    assert layers.index("ids.push('record')") < layers.index("ids.push('cog-card')")
    assert layers.index("ids.push('cog-card')") < layers.index(
        "ids.push('graph-full')"), \
        "Back в полном экране должен сначала закрывать карточку"
    assert "case 'cog-card': close('closeCogCard'); return true;" in APP_JS
    # Клавиатура: сцена — единственный focusable-элемент карты.
    assert INDEX.count('data-cog-scene') == 2, \
        "сцена встроенной карты и полного экрана должны быть одинаково доступны"
    assert 'tabindex="0" data-cog-scene' in INDEX
    assert '@keydown.enter.prevent="openCogSelectedCard()"' in INDEX
    assert "openCogSelectedCard: function () {" in APP_JS
    # Esc идёт общим путём (back-stack), второго обработчика не заводим.
    assert "_trapTabKey(ev, ev.currentTarget, false)" in APP_JS


def test_card_layout_is_panel_on_desktop_and_sheet_on_mobile():
    assert ".cog-card {" in CSS
    block = _block(CSS, ".cog-card {", ".cog-card__head {")
    assert "position: fixed" in block
    assert "right: 12px" in block, "desktop: панель справа, а не окно поверх всего"
    assert "width: 344px" in block
    assert "max-height: calc(100dvh" in block
    mobile = _media_block(CSS, "max-width: 767px", ".cog-card {")
    # CMV-D (§3.2 спеки, CMV-FSM-03): нижний лист стартует на 40 % высоты
    # (полоса 35–45) и раскрывается до 80 % (полоса 75–85). Прежние «52dvh без
    # раскрытия» контрактом не являются: свайп/ручка меняют высоту.
    assert "bottom: 0" in mobile and "height: 40dvh" in mobile, \
        "телефон: нижний лист 40 % высоты"
    assert "max-height: 85dvh" in mobile, "телефон: лист раскрывается до 80–85 %"
    expanded = _media_block(CSS, "max-width: 767px", ".cog-card--expanded {")
    assert "height: 80dvh" in expanded, "телефон: раскрытие листа не реализовано"
    assert "top: auto" in mobile and "right: 0" in mobile, \
        "на телефоне панель перестаёт быть правой панелью"
    assert "safe-area-inset-bottom" in mobile
    assert "data-glass=\"b\"" in _card_block(), \
        "материал карточки — существующий токен стекла"


def test_record_window_esc_closes_only_its_own_layer():
    """review-B1: Esc в окне записи закрывает РОВНО свой слой.

    Поведение (последовательность состояний слоёв) доказывает живой стенд
    `tools/ui_evol_w15_composition_e2e.py`; здесь закреплена ПРИЧИНА дефекта:
    окно записи закрывается собственным обработчиком, поэтому обязано
    остановить всплытие ДО закрытия. Иначе событие доходит до глобального
    `_onKeydown` → `escClose()` → `backStackClose()` и закрывает следующий
    слой — карточку узла, из которой окно и открыто.
    """
    handler = _block(APP_JS, "statusRecordKeydown: function (ev) {",
                     "_trapTabKey(ev, ev.currentTarget, false);")
    assert "ev.stopPropagation()" in handler, \
        "Esc окна записи снова всплывает до глобального обработчика (два слоя за Esc)"
    assert handler.index("ev.stopPropagation()") < handler.index(
        "this.closeStatusRecord()"), \
        "всплытие должно останавливаться ДО закрытия окна"
    # Проверка осмысленна только пока глобальный обработчик закрывает слой.
    win = _block(APP_JS, "_onKeydown = function (e) {",
                 "window.addEventListener('keydown', _onKeydown);")
    assert "_appVm.escClose()" in win
    # Тот же приём у палитры — единый порядок, а не второй стиль.
    palette = APP_JS[APP_JS.index("paletteKeydown: function (event) {"):]
    palette = palette[:palette.index("_paletteHotkey: function (event) {")]
    assert "event.stopPropagation()" in palette


def test_source_action_returns_focus_to_card_button():
    """review-B2: окно записи из карточки возвращает фокус на «Открыть источник».

    `plans/current_task.md:79` (EVOL-003) требует возврата фокуса на исходную
    строку; из карточки исходная точка — нажатая кнопка действия. Поэтому
    событие клика обязано дойти до `openStatusRecord` (он запоминает
    `ev.currentTarget` и возвращает фокус ЕДИНСТВЕННЫМ механизмом —
    `_restoreOverlayFocus`); без него фокус уходит на BODY.

    Поведение доказано node-проверкой `tests/js/evol_cog_map_card_focus_test.js`
    на настоящем `web/app.js`: Esc, крестик и `goBack()` возвращают фокус
    именно на кнопку, карточка при этом остаётся открытой с той же записью.
    Здесь же закреплена проводка разметки: без `$event` поведение недостижимо.
    """
    assert '@click="cogCardAction(act.id, $event)"' in _card_block(), \
        "разметка не передаёт инициатора в действие карточки"
    body = _block(APP_JS, "cogCardAction: function (id, ev) {",
                  "openCogHistory: function () {")
    assert "this.openCogSource(ev)" in body, \
        "действие «Открыть источник» теряет событие клика"
    src = _block(APP_JS, "openCogSource: function (ev) {",
                 "openCogHistory: function () {")
    assert "}, ev);" in src, \
        "openStatusRecord вызван без инициатора — фокус вернётся на BODY"
    # Возврат фокуса остаётся ОДНИМ механизмом (второго не заводим).
    assert APP_JS.count("function _restoreOverlayFocus(") == 1
    assert "_restoreOverlayFocus(back)" in _block(
        APP_JS, "closeStatusRecord: function () {",
        "statusRecordKeydown: function (ev) {")
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    res = subprocess.run(
        [node, os.path.join("tests", "js", "evol_cog_map_card_focus_test.js")],
        capture_output=True, text=True, timeout=90, cwd=ROOT)
    assert res.returncode == 0, res.stderr
    assert "EVOL-COG-MAP-CARD-FOCUS-OK" in res.stdout


# ── 6. CMV-A (EPIC-CM-VISUAL-01): интеграция и инварианты ────────────────────
# Пакет A не меняет визуальный язык: он фиксирует ОДИН жизненный цикл графа,
# ОДНО преобразование модель→DataSet, камеру по формуле `fitScaleRef` и один
# кадровый владелец. Пороги/формы/свечение — пакеты B/C/D, здесь их нет.

def test_cmv_visual_layer_is_single_and_loaded_before_app():
    """§10.1(3): одно преобразование nodes/edges → DataSet, ДО app.js."""
    assert "/static/cog-visual.js" in INDEX
    assert (INDEX.index("/static/cognitive-map.js")
            < INDEX.index("/static/cog-visual.js")), \
        "визуальный слой загружен раньше адаптера модели"
    assert (INDEX.index("/static/cog-visual.js")
            < INDEX.index("/web/app.js")), \
        "app.js использует window.CogVisual — файл обязан быть раньше"
    assert "window.CogVisual" in VISUAL
    # Слои не размываются: визуальный файл не знает про модель и сеть.
    for banned in ("normalizePayload", "this.api(", "fetch(",
                   "XMLHttpRequest", "vis.Network"):
        assert banned not in VISUAL, banned


def test_cmv_visual_constants_live_in_one_layer():
    """INV-05: геометрия/цвет/альфа собраны в одном конфиг-слое."""
    assert "var CONFIG = {" in VISUAL
    assert "padRatio: 1.1" in VISUAL, "формула обзора 1.1 — константа конфига"
    assert "nominalRadius: 12" in VISUAL
    assert "dimOpacity" in VISUAL
    # В app.js не осталось литералов визуала: только ссылки на конфиг-слой.
    assert "rgba(148,163,184" not in APP_JS
    assert "roundness: 0.35" not in APP_JS
    assert "Math.min(5, Math.log(1 + degree))" not in APP_JS
    assert "COG_MAP_DIM_OPACITY" not in APP_JS
    assert "V.nodeRows(" in APP_JS and "V.edgeRows(" in APP_JS, \
        "строки DataSet строит единый преобразователь"


def test_cmv_one_scene_owner_and_fixed_teardown():
    """§1 контракта: сцена создаётся в одном месте и снимается по порядку."""
    assert APP_JS.count("this._cogScene = {") == 1, \
        "второй владелец сцены (второй canvas/RAF) недопустим"
    create = _block(APP_JS, "_cogCreateNetwork: function (",
                    "_cogRedraw: function")
    assert "this._cogScene = {" in create
    teardown = _block(APP_JS, "destroyCognitionGraph: function () {",
                      "_startCognitionTimer: function")
    order = [
        "cancelAnimationFrame", "scene.ro.disconnect()", "scene.io.disconnect()",
        "clearTimeout(scene.watchdog)", "this.cognitionNetwork.destroy()",
        "this._cogScene = null",
    ]
    pos = [teardown.index(step) for step in order]
    assert pos == sorted(pos), "порядок сноса сцены нарушен: %r" % (pos,)
    # Второго window/document-листенера под граф нет — только наблюдатели.
    assert "window.addEventListener" not in create
    assert "document.addEventListener" not in create
    assert "new ResizeObserver(" in APP_JS
    assert "new IntersectionObserver(" in APP_JS


def test_cmv_camera_is_fit_scale_ref_not_vis_fit():
    """§4.1: камера обзора — `moveTo` по формуле от ПОЗИЦИЙ, не vis.fit()."""
    assert "_cogApplyFit: function (animate) {" in APP_JS
    body = _block(APP_JS, "_cogApplyFit: function (animate) {",
                  "_cogAttachSceneObservers: function (el) {")
    assert "net.moveTo({" in body
    compute = _block(APP_JS, "_cogComputeFit: function () {",
                     "_cogRefreshFitScale: function")
    assert "V.fitCamera(" in compute
    assert "getPositions()" in compute
    # Позиции — единственный вход bbox: размеры строк DataSet не участвуют.
    assert "row.size" not in compute and ".size" not in compute
    # Первый кадр больше не делает `fit()` перед стабилизацией (двойной кадр).
    assert "net.fit({ animation: false })" not in APP_JS
    # «Сбросить вид» и сброс поиска идут тем же путём камеры.
    reset = _block(APP_JS, "graphResetView: function () {",
                   "openGraphFull: function () {")
    assert "_cogApplyFit(" in reset and "cognitionNetwork.fit(" not in reset
    clear = _block(APP_JS, "clearCognitionGraphSearch: function () {",
                   "graphNeighborsOf: function (nodeId) {")
    assert "_cogApplyFit(" in clear and "cognitionNetwork.fit(" not in clear


def test_cmv_one_frame_owner_and_visibility_pause():
    """§7.3/§10.2: один RAF-владелец КАРТЫ, пауза на скрытой вкладке."""
    scene_region = _block(APP_JS, "_cogCreateNetwork: function (",
                          "_cogApplyHighlight: function")
    assert scene_region.count("requestAnimationFrame(") == 1, \
        "у карты должен быть один кадровый владелец (нашёлся не один)"
    assert "_cogPauseScene: function () {" in APP_JS
    assert "_cogResumeScene: function () {" in APP_JS
    body = _block(APP_JS, "_cogRequestFrame: function () {",
                  "_cogPaintFrame: function (t) {")
    assert "scene.raf != null) return false" in body, \
        "single-flight: второй кадр не планируется"
    assert "scene.paused" in body and "document.hidden" in body
    assert "this.reducedMotion" in body, \
        "prefers-reduced-motion не запускает непрерывные кадры"
    vis = _block(APP_JS, "onVisibilityChange: function () {",
                 "// Алиасы spec §3.6.3")
    assert "_cogPauseScene()" in vis and "_cogResumeScene()" in vis
    # Счётчики приёмки §10.3 доступны без «магии» в консоли.
    counters = _block(APP_JS, "_cogDebugCounters: function () {",
                      "_cogApplyHighlight: function")
    for key in ("netCount", "rafActive", "observerCount", "listeners",
                "fitScale", "canvases", "settled"):
        assert key + ":" in counters, key


def test_cmv_physics_terminates_once():
    """§6.1/§8.1: стабилизация терминальна, камера ставится один раз."""
    assert "COG_SETTLE_WATCHDOG_MS" in APP_JS
    create = _block(APP_JS, "_cogCreateNetwork: function (",
                    "_cogRedraw: function")
    assert "settleView();" in create and "scene.settled" in create, \
        "повторное событие стабилизации не должно ставить камеру второй раз"
    assert "if (scene.settled) {" in create
    assert "stopSimulation()" in create, "страховка терминации симуляции"
    assert "physics: { enabled: false }" in create


def test_cmv_node_suites_run():
    """Живые node-прогоны: преобразование, камера, жизненный цикл."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    for script, marker in (
        # CMV-B: визуальный тест теперь покрывает формы/палитру/свечение/
        # импульсы/пульс/физику — маркер пакета B.
        ("evol_cog_visual_test.js", "EVOL-CMV-B-VISUAL-OK"),
        ("evol_cog_scene_test.js", "EVOL-CMV-A-SCENE-OK"),
        # CMV-D: fullscreen/инспектор/лист/счётчики/смена чата/фокус.
        ("evol_cmv_d_fullscreen_test.js", "EVOL-CMV-D-OK"),
        ("routing_test.js", "JS-UNIT-OK"),
    ):
        res = subprocess.run(
            [node, os.path.join("tests", "js", script)],
            capture_output=True, text=True, timeout=120, cwd=ROOT)
        assert res.returncode == 0, script + ": " + res.stderr[-2000:]
        assert marker in res.stdout, script + ": " + res.stdout[-2000:]


# ═══ CMV-D (EPIC-CM-VISUAL-01): fullscreen, инспектор, mobile, счётчики ══════
# Спека §2.1-§2.3, §3.1-§3.2, §8.2, §9, §11, §12.3. Живые измерения — стенд
# `tools/ui_cmv_d_fullscreen_e2e.py`; здесь закреплены ПРИЧИНЫ (структура,
# стили, точки отказа), без которых живые проверки были бы случайными.

D_BLOCK = _map_block(INDEX)


def _fs_block(html: str) -> str:
    """Разметка полноэкранного интерфейса исследования."""
    start = html.index('class="status-graph-full"')
    return html[start:html.index('id="cog-card"', start)]


def test_cmv_d_fullscreen_is_a_research_ui_not_a_canvas():
    """§3.1: панель с ОДНИМ порядком контролов + сцена и инспектор под ней."""
    full = _fs_block(INDEX)
    assert "cog-fs__bar" in full, "нет панели полного экрана"
    order = ["cog-fs__brand", "data-cog-counters", "graph-search cog-fs__search",
             "graphResetView()", "closeGraphFull()"]
    positions = [full.index(marker) for marker in order]
    assert positions == sorted(positions), \
        "порядок панели нарушен: название → счётчики → поиск → фильтры → " \
        "сброс → закрыть"
    assert "cog-fs__body" in full and "cog-fs__scene" in full
    assert 'id="cog-inspector-slot"' in full, \
        "нет колонки инспектора в полном экране"
    assert full.index("cog-fs__scene") < full.index("cog-inspector-slot"), \
        "инспектор должен идти после сцены (отдельная колонка, не оверлей)"
    # Панель — одна строка на опорных ширинах: 56–64 px по §3.1.
    bar = _block(CSS, ".cog-fs__bar {", ".cog-fs__brand {")
    assert "min-height: 60px" in bar


def test_cmv_d_inspector_is_a_grid_column_not_an_overlay():
    """§3.1/CMV-FS-02/CMV-VIS-09: колонка 300–360 px, сцена сужается."""
    grid = _block(CSS, ".status-graph-full.has-inspector .cog-fs__body {",
                  ".status-graph-full.has-inspector .cog-fs__inspector {")
    assert "grid-template-columns" in grid and "clamp(300px" in grid \
        and "360px" in grid, grid
    dock = _media_block(CSS, "min-width: 768px", ".cog-card--dock {")
    assert "position: static" in dock, \
        "панель инспектора не должна быть абсолютно позиционированной"
    assert "position: fixed" not in dock, "fixed-панель перекрывала бы сцену"
    assert "overflow-y: auto" in dock, "у инспектора нет собственного scroll"
    # Пустая колонка места не занимает (FS-03): display:none до появления записи.
    inspector = _block(CSS, ".cog-fs__inspector {",
                       ".cog-fs__scene .cognition-graph--full")
    assert "display: none" in inspector
    # Телефонный лист существует отдельно и места не занимает.
    mobile = _media_block(CSS, "max-width: 767px",
                          ".status-graph-full .cog-fs__inspector {")
    assert "height: 0" in mobile, \
        "слот инспектора на телефоне не должен занимать высоту"


def test_cmv_d_embedded_inspector_sits_below_the_scene():
    """§8.2/CMV-CARD-08: под сценой, а не «в углу поверх узлов»."""
    block = D_BLOCK
    assert 'id="cog-embed-inspector"' in block, \
        "нет панели инспектора во встроенной карте"
    assert block.index("data-cog-scene") < block.index('id="cog-embed-inspector"'), \
        "панель должна быть ПОД сценой"
    embed = _block(CSS, ".cog-card--embed {", ".cog-card--embed .cog-card__grip")
    assert "position: static" in embed, "встроенный инспектор не должен плавать"
    assert "max-height: 40dvh" in embed, "панель должна быть компактной"
    assert "overflow-y: auto" in embed, "у панели нет собственного scroll"
    # Один слой: та же карточка телепортируется в слот, второй разметки нет
    # (контракт §9.1: маркер `<teleport>` + одна модель `cogCard`).
    assert INDEX.count('id="cog-card"') == 1
    assert '<teleport v-if="cogCard" :to="cogCardSlot">' in INDEX, \
        "карточка не переезжает в слот своего режима"
    assert "cogCardSlot: function () {" in APP_JS, "нет выбора слота показа"
    assert "'#cog-inspector-slot' : '#cog-embed-inspector'" in APP_JS, \
        "слоты режимов названы не те"
    # Второй карточки/второй логики нет: ручной перенос DOM не нужен.
    assert "_cogMountCard" not in APP_JS, \
        "карточка должна переезжать телепортом, а не ручным appendChild"


def test_cmv_d_scene_height_and_mobile_controls():
    """§2.1 (400/420 px) и §2.3 (390 px, тач-цели ≥44)."""
    scene = _block(CSS, ".cognition-graph {", ".cog-fx {")
    assert "height: 420px" in scene, "рабочая цель §2.1 — 420 px"
    assert "320px" not in scene, "осталась прежняя высота 320 px"
    mobile_scene = _media_block(CSS, "max-width: 767px",
                                ".cognition-graph { height: clamp(")
    assert "clamp(340px" in mobile_scene, "на телефоне минимум 340 px"
    assert "touch-action: none" in scene, \
        "без touch-action сцена не может держать пинч/пан"
    # 44 px для действий карточки и контролов шапки на телефоне.
    mobile_card = _media_block(CSS, "max-width: 767px", ".cog-card {")
    assert ".cog-card__action .btn-ghost { min-height: 44px; }" in mobile_card
    assert ".cog-card__toggle { min-height: 44px; }" in mobile_card
    assert ".status-graph-full .btn-ghost { min-height: 44px; }" in CSS
    # Шапка на 390: заголовок и «Полный экран» — одна строка (мета отдельной).
    head = _block(CSS, ".cog-head {", ".cog-count__sep")
    assert "cog-head__row" in head and "flex-wrap: nowrap" in head
    assert "cog-head__meta" in head and "flex-wrap: wrap" in head


def test_cmv_d_counters_distinguish_four_values():
    """§9.9/CMV-NAV-07: БД / API / фильтр / экран — разные величины."""
    for block in (D_BLOCK, _fs_block(INDEX)):
        assert "cogCounterParts" in block, "нет раздельных частей счётчиков"
        assert ':data-cog-count="part.key"' in block, \
            "части счётчиков не размечены данными (различие не проверяемо)"
    body = _block(APP_JS, "cogCounterParts: function () {",
                  "cogCounters: function () {")
    for marker in ("'db'", "'api'", "'screen'", "в базе", "из API",
                   "на экране"):
        assert marker in body, marker
    assert "countSummary" in _block(APP_JS, "_cogCounts: function () {",
                                    "_cogRefreshCounts: function")
    # Публикация в реактивные данные (шаблон не читает `_cog*`).
    refresh = _block(APP_JS, "_cogRefreshCounts: function () {",
                     "_cogSetHover: function")
    assert "this.cogCounts = counts || null" in refresh
    assert "this._cogCountsSig = sig" in refresh, "нет защиты от лишних пересчётов"
    # «Фильтр» остаётся отдельной строкой существующего контракта.
    assert "cogViewCounters" in D_BLOCK
    assert "cogViewCounters" in _fs_block(INDEX)


def test_cmv_d_truncated_is_labelled_and_explained():
    """§2.2: «Отображена часть графа» + объяснение; честность не ослаблена."""
    for block in (D_BLOCK, _fs_block(INDEX)):
        assert "data-cog-truncated" in block, "усечение не помечено"
        assert ':title="cogTruncated.hint"' in block, \
            "усечение не объясняется по hover"
        assert "Отображена часть графа" in block
    body = _block(APP_JS, "cogTruncated: function () {",
                  "cogViewCounters: function () {")
    assert "tr.nodes === true" in body and "tr.edges === true" in body
    assert "comp.active === true" in body
    assert "сервер не отдал" in body, "поиск по неотданной части не оговорён"
    # Нейтральность прежней строки полноты не тронута (регресс-контракт §9.1).
    at = INDEX.index("data-cog-completeness")
    assert "text-gray-500" in INDEX[at - 200:at + 40]


def test_cmv_d_hint_line_is_compact_and_one_time():
    """§2.2 строка 4 (CMV-HDR-04): подсказка жестов — не постоянная плашка."""
    for block in (D_BLOCK, _fs_block(INDEX)):
        pass
    block = D_BLOCK
    assert "data-cog-hint>" in block, "нет строки подсказки под сценой"
    assert "cogHintText" in block
    # Доступность без лишнего визуально скрытого узла: полный текст подсказки
    # живёт в aria-label сцены и в `title`.
    assert ':title="cogHintText"' in block, "нет подсказки на самой сцене"
    assert "Колесо/щипок" in block and "нажатие — связи" in block, \
        "полный текст подсказки не в aria-label сцены"
    assert "cog-hint__sr" not in block, \
        "визуально скрытая копия текста не нужна (и попадает под проверки вёрстки)"
    # Полный экран: та же доступная подсказка (сцена иная, текст один).
    assert ':title="cogHintText"' in _fs_block(INDEX)
    hint = _block(APP_JS, "cogHintText: function () {",
                  "cogHintVisible: function () {")
    for part in ("Колесо/щипок — масштаб", "Перетаскивание — перемещение",
                 "Нажатие — связи"):
        assert part in hint, part
    visible = _block(APP_JS, "cogHintVisible: function () {",
                     "// CMV-D (§3.1/§8.2 спеки): МЕСТО показа")
    assert "this.cogHintSeen !== true" in visible and "this.cogEmpty" in visible
    # Подсказка уходит после ПЕРВОГО действия с картой, а не по таймеру.
    for method in ("graphSelectNode: function (nodeId) {",
                   "applyGraphFilter: function () {"):
        assert "this._cogHintDone();" in _block(APP_JS, method, "\n      },\n")
    css = _block(CSS, ".cog-hint {", ".cog-card {")
    assert "flex-wrap: wrap" in css, "подсказка обязана переноситься по словам"


def test_cmv_d_neighbour_navigation_and_focus_return():
    """§9/CMV-NAV-05/06: «Перейти» и возврат фокуса на кнопку открытия."""
    card = _card_block()
    assert ':data-cog-neighbor-go="nb.id"' in card, "нет навигации «Перейти»"
    assert '@click="cogFocusNeighbor(nb.id)"' in card
    assert 'ref="cogFullBtn"' in D_BLOCK, "кнопка открытия — точка возврата"
    focus = _block(APP_JS, "cogFocusNeighbor: function (nodeId) {",
                   "// F2 (T-1560/1561")
    assert "net.focus(" in focus and "graphApplySelectionLabels" in focus
    assert "openCogNodeCard(nodeId)" in focus
    # Открытие карточки по-прежнему не двигает камеру (§W7-S3).
    node_card = _block(APP_JS, "openCogNodeCard: function (nodeId, opts) {",
                       "openCogEdgeCard: function (edgeId, opts) {")
    assert "net.focus(" not in node_card
    close = _block(APP_JS, "closeGraphFull: function () {",
                   "// Кнопка «Полный экран»")
    assert "this._cogReturnFocusToFullBtn()" in close, \
        "закрытие полного экрана не возвращает фокус"
    ret = _block(APP_JS, "_cogReturnFocusToFullBtn: function () {",
                 "// F11 (L-F11S-3, §16/D4): initial focus")
    assert "document.activeElement" in ret, \
        "успех фокуса не проверяется — отвязанный узел сойдёт за успех"
    assert "setTimeout(attempt" in ret, "нет ограниченного повтора"


def test_cmv_d_states_error_and_chat_switch_are_honest():
    """§11: пусто/ошибка с повтором/last-known-good/чужой чат."""
    for block in (D_BLOCK, _fs_block(INDEX)):
        assert "data-cog-load-error" in block and "data-cog-load-retry" in block, \
            "отказ загрузки не показан с действием повтора"
    load = _block(APP_JS, "loadCognitionGraph: async function () {",
                  "_graphSignature: function")
    assert "this._cogChatGen" in load, "ответ прошлого чата не отбрасывается"
    assert "this.cogLoadError = null" in load
    assert "this.cogLoadError = {" in load
    inval = _block(APP_JS, "_cogInvalidateForChatSwitch: function () {",
                   "// ── CMV-D: места показа карточки")
    assert "this.cognitionGraphData = null" in inval
    assert "this._cogChatGen = (this._cogChatGen || 0) + 1" in inval
    assert "if (hadPrev" in inval, "новый чат не перезапрашивает карту"
    assert "this._cogInvalidateForChatSwitch();" in APP_JS
    render = _block(APP_JS, "renderCognitionGraph: async function () {",
                    "_cogApplyData: function")
    assert "if (!model) {" in render and "destroyCognitionGraph()" in render, \
        "прежний граф остаётся на экране при отсутствии модели"
    # Пусто / одно-узловое состояние ведут в «Память» (контракт §4).
    assert "openMemoryFromCogMap()" in D_BLOCK


def test_cmv_d_cluster_label_is_most_frequent_title():
    """Побочная находка ревью CMV-C: имя кластера — частая парадигма."""
    body = _block(ADAPTER, "function computeClusters(model) {",
                  "var GROUP_NEUTRAL_LABEL")
    assert "titleCounts" in body, "частота заголовков не считается"
    assert "tkCount > paradigmCount" in body, \
        "кластер снова называется произвольным (самым коротким) заголовком"
    assert "node.title.length < group.paradigmTitle.length" not in body
