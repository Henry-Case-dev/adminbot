'use strict';
/* EVOL-COG-MAP (W7-S1) — чистый адаптер карты (`web/static/cognitive-map.js`).
 *
 * TEST-LIFECYCLE: CONTRACT owner=EVOL-COG-MAP (W7-S1)
 * Контракт: `plans/features/evol/arch/cog-map-contract.md` §3/§5/§6.
 *
 * Проверяется РЕАЛЬНЫЙ файл адаптера без DOM/vis-network: нормализация
 * payload, поиск по названию/алиасу, фильтры (тип/чат/статус) с разрывом
 * рёбер на отфильтрованных концах, камера, аллокатор подписей (детерминизм,
 * отсутствие пересечений, LOD-пороги, потолки 26/12), а также отсутствие
 * сетевых вызовов в модуле.
 *
 * Запуск: node tests/js/evol_cognitive_map_test.js
 * Успешный маркер: EVOL-COG-MAP-S1-OK
 */
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const SRC_PATH = path.join(__dirname, '..', '..', 'web', 'static', 'cognitive-map.js');
const CM = require(SRC_PATH);

let checks = 0;
function ok(cond, message) {
  assert.ok(cond, message);
  checks += 1;
}
function eq(actual, expected, message) {
  assert.deepStrictEqual(actual, expected, message);
  checks += 1;
}

// ── фикстура payload (форма как у GET /api/memory/cognitive-map) ───────────
function payload() {
  return {
    version: 'cog-map/1',
    generated_at: 1762000000,
    state: 'partial',
    scope: { mode: 'chat', chat_id: -1001 },
    degraded: { active: false, not_loaded: [] },
    sources: { facts: 'loaded', graph: 'loaded' },
    caps: { nodes: 800, edges: 2400, per_class: 150, classes: 4, entity_nodes: 792 },
    shown_of: {
      nodes: 6,
      edges: 4,
      totals: { nodes: 900, edges: 2400 },
      unresolved_refs: 1,
      by_kind: {
        fact: { shown: 2, total: 300, truncated: true },
        belief: { shown: 1, total: 1, truncated: false },
        paradigm: { shown: 1, total: 1, truncated: false },
        entity: { shown: 2, total: 598, truncated: true },
      },
    },
    truncated: { nodes: true, edges: false,
      by_class: { fact: true, belief: false, paradigm: false,
        evolution: false, entity: true } },
    nodes: [
      {
        id: 'fact:-1001:1', kind: 'fact', scope: 'chat', chat_id: -1001,
        title: 'Любит утренний кофе без сахара',
        text: 'Любит утренний кофе без сахара',
        status: 'confirmed', isolated: false,
        time: { occurred_at: 1750000000, observed_at: null, saved_at: 1750000100,
          confirmed_at: 1750000100, updated_at: null },
        provenance: { record: 'graph_facts', fact_id: 1, chat_id: -1001,
          origin: 'chat_history', message_id: 555, source_ids: [] },
        metrics: { importance: 7, weight: 0.5, degree: null },
        refs: { supersedes: null, source_ids: [] },
      },
      {
        id: 'fact:-1001:2', kind: 'fact', scope: 'chat', chat_id: -1001,
        title: 'Старый факт про кофе', text: 'Старый факт про кофе',
        status: 'superseded', isolated: true,
        time: { occurred_at: null, observed_at: null, saved_at: null,
          confirmed_at: null, updated_at: null },
        provenance: { record: 'graph_facts', fact_id: 2, chat_id: -1001 },
        metrics: { importance: 3, weight: null, degree: null },
        refs: {},
      },
      {
        id: 'belief:-1001:3', kind: 'belief', scope: 'chat', chat_id: -1001,
        title: 'Кофе — ритуал', text: 'Кофе — ритуал', status: 'confirmed',
        isolated: false,
        time: { occurred_at: null, observed_at: null, saved_at: 1750000200,
          confirmed_at: null, updated_at: null },
        provenance: { record: 'graph_facts', fact_id: 3, chat_id: -1001 },
        metrics: { importance: 6, weight: 0.4, degree: null },
        refs: { source_ids: [1] },
      },
      {
        id: 'paradigm:-1001:4', kind: 'paradigm', scope: 'chat', chat_id: -1001,
        title: 'Бережёт утро', text: 'Бережёт утро', status: 'confirmed',
        isolated: true,
        time: { occurred_at: null, observed_at: null, saved_at: null,
          confirmed_at: null, updated_at: null },
        provenance: { record: 'graph_facts', fact_id: 4, chat_id: -1001 },
        metrics: { importance: 9, weight: null, degree: null },
        refs: {},
      },
      {
        id: 'ent:-1001:10', kind: 'entity', scope: 'chat', chat_id: -1001,
        title: 'Хаб', text: null, status: null, isolated: false,
        time: { occurred_at: null, observed_at: null, saved_at: null,
          confirmed_at: null, updated_at: null },
        provenance: { record: 'nodes', node_id: 10, entity_type: 'user' },
        metrics: { importance: null, weight: null, degree: 2 },
      },
      {
        id: 'ent:-1001:11', kind: 'entity', scope: 'chat', chat_id: -1001,
        title: 'Тема', text: null, status: null, isolated: false,
        time: { occurred_at: null, observed_at: null, saved_at: null,
          confirmed_at: null, updated_at: null },
        provenance: { record: 'nodes', node_id: 11, entity_type: 'topic' },
        metrics: { importance: null, weight: null, degree: 1 },
      },
    ],
    edges: [
      { id: 'edge:-1001:1', from: 'ent:-1001:10', to: 'ent:-1001:11',
        relation: 'обсуждали', kind: 'recorded', derived: false,
        chat_id: -1001, justification_recorded: true,
        provenance: { edge_id: 1, fact_id: 1, origin: 'chat_history',
          basis: 'fact_provenance' } },
      { id: 'derived:-1001:1:fact', from: 'fact:-1001:1', to: 'ent:-1001:10',
        relation: 'derived_from', kind: 'derived', derived: true,
        chat_id: -1001, justification_recorded: true,
        provenance: { edge_id: 1, fact_id: 1, basis: 'edge_fact_id' } },
      { id: 'revision:-1001:1:2', from: 'fact:-1001:2', to: 'fact:-1001:1',
        relation: 'revised_by', kind: 'derived', derived: true,
        chat_id: -1001, justification_recorded: false,
        provenance: { chat_id: -1001, old_fact_id: 2, new_fact_id: 1,
          basis: 'supersedes' } },
      // ребро на отсутствующий узел — обязано быть отброшено (концы не
      // дорисовываются)
      { id: 'edge:-1001:99', from: 'ent:-1001:10', to: 'ent:-1001:99',
        relation: 'обсуждали', kind: 'recorded', derived: false,
        chat_id: -1001, justification_recorded: false, provenance: {} },
    ],
  };
}

const ALIASES = { 'Хаб': ['хаб', 'центр'], 'кофе — ритуал': 'ритуал' };

// ── 1. модуль не тянет DOM/сеть ────────────────────────────────────────────
function codeOnly(source) {
  // комментарии не считаем: важно, что модуль не ИСПОЛЬЗУЕТ сеть/движок.
  return source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .split('\n')
    .map((line) => line.replace(/(^|\s)\/\/.*$/, ' '))
    .join('\n');
}

(function testNoDomNoNetwork() {
  const src = codeOnly(fs.readFileSync(SRC_PATH, 'utf8'));
  ok(typeof window === 'undefined' || window.CognitiveMap,
    'модуль экспортируется в браузере как window.CognitiveMap');
  ok(!/fetch\s*\(/.test(src), 'в адаптере нет fetch');
  ok(!/XMLHttpRequest/.test(src), 'в адаптере нет XMLHttpRequest');
  ok(!/vis\.Network|new\s+DataSet|vis\.DataSet/.test(src),
    'адаптер не зависит от vis-network');
  ok(!/document\.(getElementById|querySelector|createElement)/.test(src),
    'адаптер не работает с DOM');
  ok(!/Math\.random/.test(src), 'аллокатор детерминирован (без Math.random)');
})();

// ── 2. нормализация payload ────────────────────────────────────────────────
(function testNormalize() {
  const model = CM.normalizePayload(payload(), { aliases: ALIASES });
  eq(model.version, 'cog-map/1', 'версия payload сохраняется');
  eq(model.state, 'partial', 'состояние partial сохраняется');
  eq(model.scope, { mode: 'chat', chatId: -1001 }, 'scope чата сохраняется');
  eq(model.nodes.length, 6, 'все валидные узлы приняты');
  eq(model.edges.length, 3, 'ребро на отсутствующий узел отброшено');
  ok(model.warnings.indexOf('edge_dropped') >= 0,
    'отброшенное ребро отмечено warning-ом');
  ok(model.edges.every((e) => model.byId[e.from] && model.byId[e.to]),
    'у всех принятых рёбер оба конца существуют');
  eq(model.byId['ent:-1001:10'].degree, 2, 'степень считается по рёбрам');
  eq(model.byId['paradigm:-1001:4'].isolated, true,
    'парадигма без рёбер остаётся изолированной');
  eq(model.byId['fact:-1001:1'].isolated, false,
    'узел с подтверждённым ребром не изолирован');
  eq(model.byId['fact:-1001:2'].time.occurredAt, null,
    'отсутствующее время остаётся null');
  eq(model.byId['fact:-1001:1'].time.occurredAt, 1750000000,
    'occurred_at не смешан с saved_at');
  eq(model.byId['fact:-1001:1'].metrics.importance, 7, 'importance — реальное');
  ok(!('confidence' in model.byId['fact:-1001:1'].metrics),
    'confidence/strength/freshness не рассчитываются');
  eq(model.shownOf.byKind.fact, { shown: 2, total: 300, truncated: true },
    'shown_of по классам сохраняется');

  // незнакомый kind -> other, битые узлы отбрасываются
  const weird = payload();
  weird.nodes = [
    { id: 'x:1', kind: 'hologram', title: 'Непонятное' },
    { id: '', kind: 'fact', title: 'без id' },
  ];
  weird.edges = [];
  const m2 = CM.normalizePayload(weird);
  eq(m2.nodes.length, 1, 'узел без id отброшен');
  eq(m2.nodes[0].kind, 'other', 'незнакомый kind не выдумывает тип');
  ok(m2.warnings.indexOf('version_missing') < 0, 'версия на месте');

  // частичный/битый ответ не бросает
  const m3 = CM.normalizePayload(null);
  eq(m3.nodes.length, 0, 'пустой payload → пустая модель');
  ok(m3.warnings.indexOf('payload_missing') >= 0, 'пустой payload отмечен');

  const m4 = CM.normalizePayload({ version: 'v99', nodes: [], edges: [] });
  ok(m4.warnings.indexOf('version_mismatch') >= 0,
    'незнакомая версия даёт честный warning, а не падение');

  // `not_loaded` (источник не прочитался) — это не «данных нет»
  const degraded = CM.normalizePayload({
    version: 'cog-map/1', state: 'degraded',
    degraded: { active: true, not_loaded: ['graph', 'facts'] },
    sources: { graph: 'not_loaded', facts: 'not_loaded' },
    nodes: [], edges: [],
  });
  eq(degraded.degraded.notLoaded, ['graph', 'facts'],
    'список незагруженных источников сохраняется отдельно от пустоты');
  eq(degraded.state, 'degraded', 'состояние degraded не подменяется empty');
  eq(degraded.nodes.length, 0, 'пустые узлы при degraded — это не «пусто»');
})();

// ── 3. поиск по названию и алиасу ──────────────────────────────────────────
(function testSearch() {
  const model = CM.normalizePayload(payload(), { aliases: ALIASES });
  eq(CM.searchNodes(model, 'кофе').length, 3,
    'поиск по названию находит факты и убеждение про кофе');
  eq(CM.searchNodes(model, 'ритуал').map((n) => n.id), ['belief:-1001:3'],
    'поиск идёт и по алиасу, а не только по названию');
  eq(CM.searchNodes(model, 'центр').map((n) => n.id), ['ent:-1001:10'],
    'алиас сущности работает');
  eq(CM.searchNodes(model, 'КОФЕ РИТУАЛ').length, 1,
    'многословный запрос и регистр не мешают');
  eq(CM.searchNodes(model, 'ёлка').length, 0, 'нет совпадений — пустой список');
  eq(CM.searchNodes(model, '   ').length, 0, 'пустой запрос ничего не ищет');
})();

// ── 4. фильтры (тип/чат/статус/поиск) ──────────────────────────────────────
(function testFilters() {
  const model = CM.normalizePayload(payload(), { aliases: ALIASES });
  const all = CM.applyFilters(model, {});
  eq(all.counts.nodes, 6, 'без фильтров видны все узлы');
  eq(all.counts.edges, 3, 'без фильтров видны все рёбра');

  const kinds = CM.applyFilters(model, { kinds: ['fact'] });
  eq(kinds.counts.nodes, 2, 'фильтр по типу оставляет только факты');
  ok(kinds.edges.every((e) => kinds.nodes.some((n) => n.id === e.from)),
    'ребро не остаётся без своего конца');
  eq(kinds.counts.edges, 1,
    'остаётся только связь между оставшимися фактами (revised_by)');
  eq(kinds.edges[0].relation, 'revised_by',
    'связь факт↔сущность разорвана фильтром, а не перерисована');

  const entities = CM.applyFilters(model, { kinds: ['entity'] });
  eq(entities.counts.edges, 1, 'связь между двумя сущностями сохраняется');

  const chats = CM.applyFilters(model, { chats: [-1001] });
  eq(chats.counts.nodes, 6, 'фильтр по своему чату ничего не теряет');
  const otherChat = CM.applyFilters(model, { chats: [-2002] });
  eq(otherChat.counts.nodes, 0, 'чужой чат не показывается');

  const superseded = CM.applyFilters(model, { statuses: ['superseded'] });
  eq(superseded.counts.nodes, 1, 'фильтр по статусу работает');

  const bySearch = CM.applyFilters(model, { search: 'кофе' });
  eq(bySearch.counts.nodes, 3, 'фильтр-поиск совпадает с searchNodes');
  ok(bySearch.counts.hiddenNodes === 3, 'счётчик скрытых узлов честный');

  const noIsolated = CM.applyFilters(model, { hideIsolated: true });
  eq(noIsolated.counts.nodes, 4, 'изолированные узлы можно скрыть');
  ok(noIsolated.nodes.every((n) => n.isolated === false),
    'в выборке не осталось изолированных');

  // явный фильтр области: глобальные/системные записи не выдают себя за чат
  const scoped = CM.normalizePayload({
    version: 'cog-map/1',
    nodes: [
      { id: 'fact:-1001:1', kind: 'fact', title: 'Факт чата', chat_id: -1001,
        scope: 'chat' },
      { id: 'evt:global:dream:1', kind: 'evolution_event',
        title: 'Системный decay', chat_id: null, scope: 'global' },
    ],
    edges: [],
  });
  eq(CM.applyFilters(scoped, { scopes: ['global'] }).nodes.map((n) => n.id),
    ['evt:global:dream:1'], 'фильтр scopes=global оставляет системную запись');
  eq(CM.applyFilters(scoped, { scopes: ['chat'] }).counts.nodes, 1,
    'фильтр scopes=chat не тащит глобальную запись');
  eq(CM.applyFilters(scoped, { chats: [null] }).nodes.map((n) => n.id),
    ['evt:global:dream:1'], 'совместимость: chats:[null] = глобальная область');

  // фильтры не мутируют модель (чистая функция)
  eq(model.nodes.length, 6, 'модель не изменилась после фильтрации');
})();

// ── 5. камера ──────────────────────────────────────────────────────────────
(function testCamera() {
  const cam = CM.createCamera();
  eq(cam, { x: 0, y: 0, scale: 1 }, 'стартовая камера нейтральна');
  eq(CM.clampCamera({ x: 5, y: -5, scale: 99 }).scale, 4,
    'верхний предел масштаба ограничен');
  eq(CM.clampCamera({ x: 5, y: -5, scale: 0.001 }).scale, 0.15,
    'нижний предел масштаба ограничен');
  eq(CM.cameraFromNetwork({ x: 12, y: -30 }, 1.75),
    { x: 12, y: -30, scale: 1.75 }, 'камера из vis-network (позиция+масштаб)');
  eq(CM.cameraToNetwork({ x: 12, y: -30, scale: 1.75 }),
    { position: { x: 12, y: -30 }, scale: 1.75 },
    'камера обратно в формат vis-network');
  ok(CM.cameraEquals({ x: 0, y: 0, scale: 1 }, { x: 0, y: 0, scale: 1 }),
    'равные камеры сравниваются');
  ok(!CM.cameraEquals({ x: 0, y: 0, scale: 1 }, { x: 0, y: 0, scale: 1.01 }),
    'разные камеры не равны');
  // сохранение/восстановление камеры в пределах сессии (структуры данных)
  const saved = JSON.parse(JSON.stringify(CM.cameraFromNetwork({ x: 3, y: 4 }, 2)));
  eq(CM.cameraToNetwork(saved), { position: { x: 3, y: 4 }, scale: 2 },
    'камера переживает сериализацию');
})();

// ── 6. аллокатор подписей ──────────────────────────────────────────────────
function labelItems(count) {
  const items = [];
  for (let i = 0; i < count; i += 1) {
    items.push({
      id: 'n' + i,
      x: 40 + (i % 8) * 60,
      y: 40 + Math.floor(i / 8) * 45,
      kind: i === 0 ? 'paradigm' : (i % 3 === 0 ? 'entity' : 'fact'),
      title: 'Подпись ' + i,
      degree: count - i,
      selected: i === 0,
    });
  }
  return items;
}

(function testLabels() {
  const items = labelItems(60);
  const opts = { scale: 1.4, viewport: { width: 900, height: 700 } };
  const first = CM.allocateLabels(items, opts);
  const second = CM.allocateLabels(items, opts);
  eq(first, second, 'аллокатор детерминирован (два прогона совпали)');
  ok(first.labels.length <= CM.DEFAULTS.maxLabels,
    'потолок подписей не превышен (26)');
  ok(first.labels.length > 0, 'подписи вообще появляются');
  ok(first.labels.some((l) => l.id === 'n0'), 'выбранный/главный узел подписан');

  for (let i = 0; i < first.labels.length; i += 1) {
    for (let j = i + 1; j < first.labels.length; j += 1) {
      assert.ok(
        !CM.boxesOverlap(first.labels[i], first.labels[j], 0),
        'подписи не пересекаются: ' + first.labels[i].text + ' / '
          + first.labels[j].text
      );
      checks += 1;
    }
  }

  const overview = CM.allocateLabels(items,
    { scale: CM.DEFAULTS.overviewScale - 0.1,
      viewport: { width: 900, height: 700 } });
  eq(overview.lod, 'overview', 'малый масштаб → LOD overview');
  ok(overview.labels.length <= 6,
    'на обзорном масштабе подписей мало (LOD работает)');
  ok(overview.labels.length <= first.labels.length,
    'LOD не увеличивает число подписей при уменьшении масштаба');

  const normal = CM.allocateLabels(items, { scale: 0.9,
    viewport: { width: 900, height: 700 } });
  eq(normal.lod, 'normal', 'средний масштаб → normal');
  const detail = CM.allocateLabels(items, { scale: 2,
    viewport: { width: 900, height: 700 } });
  eq(detail.lod, 'detail', 'крупный масштаб → detail');

  const mobile = CM.allocateLabels(items, { scale: 2, mobile: true,
    viewport: { width: 360, height: 620 } });
  ok(mobile.maxLabels <= CM.DEFAULTS.mobileMaxLabels,
    'на мобильном потолок подписей ≤12 (визуальная константа)');
  ok(mobile.labels.length <= CM.DEFAULTS.mobileMaxLabels,
    'мобильная сцена не подписывает всё подряд');

  const outside = CM.allocateLabels(
    [{ id: 'off', x: 5000, y: 5000, kind: 'fact', title: 'За сценой' }],
    { viewport: { width: 400, height: 300 } });
  eq(outside.shown, 0, 'подпись за вьюпортом не рисуется');

  const noCoords = CM.allocateLabels(
    [{ id: 'nc', kind: 'fact', title: 'Без позиции' }], {});
  eq(noCoords.shown, 0, 'узел без координат не подписывается');

  const empty = CM.allocateLabels([], {});
  eq(empty.shown, 0, 'пустой вход — пустой результат');
  eq(empty.hidden, 0, 'скрытых подписей нет на пустом входе');
})();

// ── 7. сводка по типам для легенды/«показано X из Y» ───────────────────────
(function testKindSummary() {
  const model = CM.normalizePayload(payload(), { aliases: ALIASES });
  const summary = CM.kindSummary(model);
  const fact = summary.find((s) => s.kind === 'fact');
  ok(fact, 'сводка содержит факты');
  eq(fact.shown, 2, 'показанное число фактов совпадает с payload');
  eq(fact.total, 300, 'полное число фактов не подменяется показанным');
  eq(fact.truncated, true, 'обрезанный класс помечен');
  ok(summary.every((s) => s.label && s.total >= s.shown),
    'легенда не обещает больше, чем показано');
})();

console.log('EVOL-COG-MAP-S1-OK checks=' + checks);

/* ═══ W7-S2 (карта на новом payload): визуальная система, кластеры по
 * реальным связям, честная полнота и клиентские состояния. Всё — чистые
 * функции адаптера, поэтому проверяется в node без DOM и vis-network. */

const S2 = (function () {
  let s2 = 0;
  function ok2(cond, message) {
    assert.ok(cond, message);
    s2 += 1;
  }
  function eq2(actual, expected, message) {
    assert.deepStrictEqual(actual, expected, message);
    s2 += 1;
  }

  // ── 8. легенда: слова владельца и различитель не только цветом ─────────
  const model = CM.normalizePayload(payload(), { aliases: ALIASES });
  const legend = CM.legendEntries(model);
  const required = legend.filter((e) => e.required);
  eq2(required.map((e) => e.label),
    ['Факты', 'Убеждения', 'Парадигмы', 'Изменения'],
    'легенда: четыре обязательных слова владельца (ТЗ 1285)');
  eq2(required.map((e) => e.kind),
    ['fact', 'belief', 'paradigm', 'evolution_event'],
    'легенда: обязательные классы — четыре когнитивных');
  ok2(required.every((e) => /^#[0-9a-f]{6}$/i.test(e.color)),
    'легенда: у каждого класса свой цвет токена');
  eq2(new Set(required.map((e) => e.color)).size, 4,
    'легенда: цвета классов различаются');
  eq2(required.map((e) => e.shape),
    ['dot', 'rounded', 'hexagon', 'diamond'],
    'легенда: различие не только цветом — своя форма');
  ok2(legend.every((e) => e.label !== 'Эволюция характера'),
    '«Эволюция характера» — заголовок лент, а не строка легенды');
  // Вторичные классы показываются только если реально есть в модели.
  ok2(legend.some((e) => e.kind === 'entity' && e.required === false),
    'сущности — вторичная строка (есть в модели)');
  ok2(!legend.some((e) => e.kind === 'observation'),
    'наблюдения не выдумываются, если их нет в данных');

  // ── 9. визуальный стиль узла детерминирован и не цвето-только ─────────
  eq2(CM.nodeStyle('paradigm').size > CM.nodeStyle('fact').size, true,
    'парадигма крупнее факта (центр кластера)');
  eq2(CM.nodeStyle('fact').color, '#38bdf8', 'факты — прохладный голубой');
  eq2(CM.nodeStyle('belief').color, '#a78bfa', 'убеждения — мягкий фиолетовый');
  eq2(CM.nodeStyle('paradigm').color, '#818cf8', 'парадигмы — индиго');
  eq2(CM.nodeStyle('evolution_event').color, '#f59e0b',
    'изменения — янтарный акцент');
  eq2(CM.nodeStyle('entity').shape !== CM.nodeStyle('fact').shape, true,
    'сущности отличаются формой, а не только цветом');
  eq2(CM.nodeStyle('неизвестный').color, CM.KIND_STYLE.other.color,
    'незнакомый тип не бросает и не выдумывает цвет');

  // ── 10. кластеры по РЕАЛЬНЫМ связям: детерминизм, изоляты, чаты ────────
  const clusterFixture = CM.normalizePayload({
    version: 'cog-map/1', state: 'ok',
    nodes: [
      { id: 'paradigm:1:1', kind: 'paradigm', title: 'Доверие', chat_id: 1 },
      { id: 'belief:1:2', kind: 'belief', title: 'Верю словам', chat_id: 1 },
      { id: 'fact:1:3', kind: 'fact', title: 'Обещал и сделал', chat_id: 1 },
      { id: 'fact:1:4', kind: 'fact', title: 'Изолированный факт', chat_id: 1 },
      { id: 'fact:2:5', kind: 'fact', title: 'Чужой чат', chat_id: 2 },
    ],
    edges: [
      { id: 'e1', from: 'belief:1:2', to: 'fact:1:3',
        relation: 'derived_from', derived: true },
      { id: 'e2', from: 'paradigm:1:1', to: 'belief:1:2',
        relation: 'derived_from', derived: true },
    ],
  });
  const clusters = CM.computeClusters(clusterFixture);
  eq2(clusters.length, 3, 'кластеры: компонента + два изолированных узла');
  eq2(clusters[0].size, 3, 'кластеры: связная компонента из трёх узлов');
  eq2(clusters[0].paradigmTitle, 'Доверие',
    'кластер назван по реальной парадигме');
  eq2(clusters[0].label, 'Парадигмы: Доверие',
    'подпись кластера — парадигма, а не выдуманная тема');
  eq2(clusters.filter((c) => c.size === 1).length, 2,
    'изолированные узлы — честные кластеры из одного узла');
  ok2(clusters.every((c) => c.nodeIds.length === 1
    || c.nodeIds.indexOf('fact:2:5') < 0),
  'кластеры не приписывают узлу чужого чата несуществующую связь');
  eq2(CM.computeClusters(clusterFixture), clusters,
    'кластеры детерминированы: повторный прогон идентичен');
  ok2(JSON.stringify(CM.computeClusters(clusterFixture))
    === JSON.stringify(clusters),
  'кластеры: порядок не зависит от порядка объектов');
  const bigFirst = CM.computeClusters(CM.normalizePayload({
    version: 'cog-map/1',
    nodes: [
      { id: 'a:1', kind: 'fact', title: 'A' },
      { id: 'b:2', kind: 'fact', title: 'B', chat_id: 1 },
      { id: 'c:3', kind: 'fact', title: 'C', chat_id: 1 },
    ],
    edges: [{ id: 'x', from: 'b:2', to: 'c:3', relation: 'supports' }],
  }));
  eq2(bigFirst.map((c) => c.size), [2, 1], 'кластеры: крупные первыми');

  // ── 11. фильтр по кластеру: рёбра не рвутся, счётчики честные ──────────
  const clusterId = clusters[0].id;
  const filtered = CM.applyFilters(clusterFixture, { cluster: clusterId });
  eq2(filtered.counts.nodes, 3, 'фильтр кластера: только его узлы');
  eq2(filtered.counts.edges, 2, 'фильтр кластера: только внутренние рёбра');
  ok2(filtered.nodes.every((n) => n.id.indexOf(':1:') > 0),
    'фильтр кластера: узлы чужого чата не подмешиваются');
  const unknownCluster = CM.applyFilters(clusterFixture, { cluster: 'cl:нет' });
  eq2(unknownCluster.counts.nodes, 0,
    'неизвестный кластер даёт пустой вид, а не всю карту');
  const noDerived = CM.applyFilters(clusterFixture, { hideDerived: true });
  eq2(noDerived.counts.edges, 0,
    'скрытие производных рёбер убирает только их');

  // ── 12. «показано X из Y»: одно правило, нейтральный текст ─────────────
  const short = CM.completeness(model.shownOf);
  eq2(short.active, true, 'полнота: часть данных → строка включается');
  eq2(short.nodes, { shown: 6, total: 900, truncated: true },
    'полнота: X и Y — из payload, а не из state');
  eq2(short.text, 'показано 6 из 900 узлов · 4 из 2400 связей',
    'полнота: нейтральный текст «показано X из Y»');
  ok2(!/ошибк|сбой|внимани|предупрежд/i.test(short.text),
    'полнота подаётся нейтрально, а не как ошибка');
  const complete = CM.completeness({ nodes: 5, edges: 3,
    totals: { nodes: 5, edges: 3 } });
  eq2(complete.active, false, 'полнота: полный набор → строки нет');
  eq2(complete.text, '', 'полнота: нечего показывать — текста нет');
  const edgesShortOnly = CM.completeness({ nodes: 5, edges: 3,
    totals: { nodes: 5, edges: 9 } });
  eq2(edgesShortOnly.text, 'показано 3 из 9 связей',
    'полнота: обрезаны только связи — честная формулировка');
  eq2(edgesShortOnly.nodes.truncated, false,
    'полнота: узлы не помечены обрезанными');
  const missing = CM.completeness(null);
  eq2(missing.active, false, 'полнота: без `shown_of` не выдумывает числа');

  // ── 13. клиентское состояние ≠ серверный `state` ──────────────────────
  const fresh = 1762000000;
  const nowMs = (fresh + 60) * 1000;
  eq2(CM.mapClientState({ model, renderer: 'ready', now: nowMs }).state,
    'ready', 'partial + свежие данные + рендерер готов → ready (не «ошибка»)');
  eq2(CM.mapClientState({ model, renderer: 'ready', now: nowMs }).serverState,
    'partial', 'серверный state сохраняется отдельно');
  eq2(CM.mapClientState({ model: null, renderer: 'ready', now: nowMs }).state,
    'loading', 'нет модели → loading');
  eq2(CM.mapClientState({ model, renderer: 'missing', now: nowMs }).state,
    'not_loaded', 'vis-network не загружен → not_loaded');
  eq2(CM.mapClientState({ model, renderer: 'failed', now: nowMs }).state,
    'renderer_failed', 'рендерер упал → renderer_failed');
  eq2(CM.mapClientState({ model, renderer: 'ready',
    now: (fresh + 16 * 60) * 1000 }).state, 'stale',
  'старые данные → stale (порог считается на клиенте)');
  eq2(CM.mapClientState({ model, renderer: 'ready', now: nowMs,
    staleMs: 0 }).state, 'ready', 'staleMs=0 отключает проверку устаревания');
  const emptyModel = CM.normalizePayload({ version: 'cog-map/1',
    state: 'empty', nodes: [], edges: [] });
  eq2(CM.mapClientState({ model: emptyModel, renderer: 'ready', now: nowMs })
    .state, 'empty', 'серверное empty → пустое состояние');
  eq2(CM.mapClientState({ model, renderer: 'ready', now: nowMs,
    visibleNodes: 0 }).state, 'ready',
  'фильтр скрыл все узлы — это НЕ пустота данных (state остаётся ready)');
  eq2(CM.mapClientState({ model, renderer: 'ready', now: nowMs,
    visibleNodes: 0 }).viewEmpty, true,
  'фильтр скрыл все узлы → отдельный факт вида (viewEmpty)');
  eq2(CM.mapClientState({ model, renderer: 'ready', now: nowMs })
    .viewEmpty, false, 'непустая витрина не помечена пустой');
  eq2(CM.mapClientState({ model: emptyModel, renderer: 'ready', now: nowMs })
    .viewEmpty, false, 'пустота данных — не «пустота по фильтру»');
  ok2(CM.STATE_LABELS.not_loaded && CM.STATE_LABELS.renderer_failed,
    'у клиентских состояний есть честные подписи');
  ok2(!/ошибк/i.test(CM.STATE_LABELS.not_loaded),
    'загрузка визуализации не подаётся как ошибка');

  // ── 14. §9.1: видимая заметка по «худшему факту», `notice` рядом с `state` ─
  // Модель с отказом источника и БЕЗ узлов — ровно то, что отдаёт сервер
  // (`state='degraded'` + `degraded.active` при упавшей выборке).
  const degradedEmpty = CM.normalizePayload({
    version: 'cog-map/1', state: 'degraded', generated_at: fresh,
    degraded: { active: true, not_loaded: ['memory_cycle'] },
    nodes: [], edges: [], shown_of: { nodes: 0, edges: 0,
                                       totals: { nodes: 0, edges: 0 } },
  });
  const degEmpty = CM.mapClientState({ model: degradedEmpty,
    renderer: 'ready', now: nowMs });
  eq2(degEmpty.notice.kind, 'degraded',
    '§9.1: отказ источника — видимая заметка, а не «пусто»');
  eq2(degEmpty.empty, false,
    '§9.1: `empty` запрещён, пока degraded.active === true');
  ok2(degEmpty.state !== 'empty',
    '§9.1: клиентское `state` тоже не объявляет пустоту при отказе');
  eq2(degEmpty.notice.text, 'часть источников не прочитана: memory_cycle',
    '§9.1: заметка называет непрочитанный источник');
  eq2(degEmpty.notice.sources, ['memory_cycle'],
    '§9.1: список источников отдаётся отдельным полем');
  ok2(degEmpty.notice.kind !== 'ready' && degEmpty.notice.degraded === true,
    '§9.1: отказ не выглядит «всё хорошо»');

  // Отказ источника ПРИ НАЛИЧИИ данных: клиентская ось — ready, видимая — degraded.
  const degradedData = CM.normalizePayload({
    version: 'cog-map/1', state: 'degraded', generated_at: fresh,
    degraded: { active: true, not_loaded: ['edges'] },
    nodes: [{ id: 'fact:1:1', kind: 'fact', title: 'Есть факт' }],
    edges: [], shown_of: { nodes: 1, edges: 0,
                           totals: { nodes: 1, edges: 0 } },
  });
  const degData = CM.mapClientState({ model: degradedData, renderer: 'ready',
    now: nowMs });
  eq2(degData.state, 'ready',
    '§9.1: оси раздельные — рендерер в порядке, `state` = ready');
  eq2(degData.notice.kind, 'degraded',
    '§9.1: видимая строка всё равно сообщает об отказе');
  // Приоритет «худшего факта» для остальных комбинаций.
  eq2(CM.mapClientState({ model: degradedData, renderer: 'failed',
    now: nowMs }).notice.kind, 'renderer_failed',
  '§9.1: renderer_failed выше degraded');
  eq2(CM.mapClientState({ model: null, renderer: 'missing',
    now: nowMs }).notice.kind, 'not_loaded',
  '§9.1: not_loaded выше degraded (модели ещё нет)');
  const degradedStale = CM.mapClientState({ model: degradedData,
    renderer: 'ready', now: (fresh + 3600) * 1000 });
  eq2(degradedStale.notice.kind, 'degraded',
    '§9.1: degraded выше stale');
  // Без отказа источника пустота объявляется как обычно.
  const plainEmpty = CM.mapClientState({ model: emptyModel, renderer: 'ready',
    now: nowMs });
  eq2(plainEmpty.notice.kind, 'empty',
    'без отказа источника пустота — видимая заметка');
  eq2(plainEmpty.empty, true, 'empty остаётся честным фактом данных');
  // Полный набор: заметки нет, состояние ready.
  const plainReady = CM.mapClientState({ model, renderer: 'ready', now: nowMs });
  eq2(plainReady.notice.kind, 'ready', 'всё в порядке → заметки нет');
  eq2(plainReady.notice.text, '', 'в порядке — пустой текст заметки');
  // Свежесть/полнота независимы от заметки.
  eq2(plainReady.notice.kind, degData.notice.kind === 'degraded'
    ? 'ready' : 'degraded', 'полнота и статус — независимые поля');

  // ── 15. §9.2: бюджет подписей из ГЕОМЕТРИИ кадра ───────────────────────
  function labelItems(count, chars, extra) {
    const out = [];
    for (let i = 0; i < count; i += 1) {
      out.push({
        id: 'l' + i,
        x: 40 + (i % 5) * 60,
        y: 30 + Math.floor(i / 5) * 55,
        kind: 'fact',
        title: 'я'.repeat(chars),
      });
    }
    return out.concat(extra || []);
  }
  function budgetOf(items, w, h, mobile, chars) {
    return CM.labelBudget(items, {
      maxLabels: CM.DEFAULTS.maxLabels,
      mobileMaxLabels: CM.DEFAULTS.mobileMaxLabels,
      fontSize: CM.DEFAULTS.fontSize,
      padding: CM.DEFAULTS.padding,
      charWidth: CM.DEFAULTS.charWidth,
      maxLabelChars: chars || CM.DEFAULTS.maxLabelChars,
    }, { mobile: mobile, viewport: { width: w, height: h }, scale: 1 });
  }
  const items12 = labelItems(12, 20);
  const small = budgetOf(items12, 320, 300, true);
  const mid = budgetOf(items12, 1000, 400, false);
  const large = budgetOf(items12, 1440, 900, false);
  ok2(small.budget >= 4, '§9.2: минимальный бюджет — 4 подписи');
  ok2(small.budget <= CM.DEFAULTS.mobileMaxLabels,
    '§9.2: мобильный бюджет ≤ потолка 12');
  ok2(large.budget <= CM.DEFAULTS.maxLabels,
    '§9.2: бюджет ≤ жёсткого потолка 26');
  ok2(mid.budget < large.budget,
    '§9.2: бюджет растёт с площадью кадра (1000×400 < 1440×900)');
  ok2(small.budget < large.budget,
    '§9.2: узкий мобильный кадр даёт меньший бюджет, чем большой десктоп');
  eq2(small.fill, 0.04, '§9.2: мобильная заливка 0.04');
  eq2(large.fill, 0.05, '§9.2: десктопная заливка 0.05');
  // Длина подписи участвует: длиннее подпись — меньше подписей влезает.
  const shortBudget = budgetOf(labelItems(12, 6), 1000, 400, false, 34);
  const longBudget = budgetOf(labelItems(12, 34), 1000, 400, false, 34);
  ok2(longBudget.budget < shortBudget.budget,
    '§9.2: длина подписи уменьшает бюджет (геометрия, не константа)');
  // Один и тот же кадр: мобильный fill < десктопного при равной площади.
  const sameAreaMobile = budgetOf(items12, 800, 600, true);
  const sameAreaDesktop = budgetOf(items12, 800, 600, false);
  ok2(sameAreaMobile.budget < sameAreaDesktop.budget,
    '§9.2: на одних данных mobile-бюджет меньше десктопного');
  ok2(sameAreaMobile.budget <= CM.DEFAULTS.mobileMaxLabels
    && sameAreaDesktop.budget <= CM.DEFAULTS.maxLabels,
  '§9.2: оба бюджета под своими потолками');
  // Обязательные подписи: выбранный узел и парадигма подписаны всегда.
  const mandatoryItems = labelItems(6, 30, [
    { id: 'sel', x: 60, y: 60, kind: 'fact', title: 'Выбранный', selected: true },
    { id: 'par', x: 90, y: 90, kind: 'paradigm', title: 'Парадигма' },
  ]);
  const tiny = CM.allocateLabels(mandatoryItems, {
    scale: 1, viewport: { width: 400, height: 300 },
    maxLabelChars: 34, fontSize: 11,
  });
  ok2(tiny.mandatory >= 2, '§9.2: обязательные подписи посчитаны');
  ok2(tiny.budget >= tiny.mandatory,
    '§9.2: бюджет не меньше числа обязательных подписей');
  ok2(tiny.labels.some((l) => l.id === 'sel'),
    '§9.2: выбранный узел подписан даже в тесном кадре');
  ok2(tiny.labels.some((l) => l.id === 'par'),
    '§9.2: парадигма подписана даже в тесном кадре');
  // Тесный кадр с ШЕСТЬЮ парадигмами: геометрический бюджет (< 6) поднимается
  // до числа обязательных подписей — иначе «всегда подписаны» не выполнялось бы.
  const manyParadigms = [];
  for (let i = 0; i < 6; i += 1) {
    manyParadigms.push({
      id: 'p' + i, x: 20 + i * 18, y: 40, kind: 'paradigm',
      title: 'Парадигма ' + i,
    });
  }
  const crowded = CM.allocateLabels(manyParadigms, {
    scale: 1, viewport: { width: 160, height: 80 }, fontSize: 11,
  });
  eq2(crowded.mandatory, 6, '§9.2: шесть обязательных подписей (парадигмы)');
  ok2(crowded.budget >= 6,
    '§9.2: бюджет поднят до числа обязательных подписей');
  ok2(crowded.budget <= CM.DEFAULTS.maxLabels,
    '§9.2: и при этом не выше жёсткого потолка');
  // LOD — доля бюджета, а не отдельная константа.
  const overview = CM.allocateLabels(items12, {
    scale: CM.DEFAULTS.overviewScale - 0.1,
    viewport: { width: 1440, height: 900 },
  });
  const normal = CM.allocateLabels(items12, {
    scale: 0.9, viewport: { width: 1440, height: 900 },
  });
  const detail = CM.allocateLabels(items12, {
    scale: 2, viewport: { width: 1440, height: 900 },
  });
  ok2(overview.maxLabels <= Math.min(normal.budget, 6),
    '§9.2: overview — доля бюджета, не больше 6');
  eq2(normal.maxLabels, Math.min(normal.budget, 16),
    '§9.2: normal — доля бюджета, не больше 16');
  eq2(detail.maxLabels, detail.budget,
    '§9.2: detail — весь бюджет');
  ok2(overview.labels.length <= normal.labels.length
    && normal.labels.length <= detail.labels.length,
  '§9.2: чем выше LOD, тем не меньше подписей');
  // Подпись не прижимается к кромке кадра (у сцены скругление/рамка):
  // бокс обязан лежать внутри с отступом `padding`.
  const edgeItems = [
    { id: 'top', x: 200, y: 3, kind: 'fact', title: 'У самой кромки' },
    { id: 'mid', x: 200, y: 150, kind: 'fact', title: 'В центре' },
  ];
  const edge = CM.allocateLabels(edgeItems, {
    scale: 1, viewport: { width: 400, height: 300 },
  });
  ok2(!edge.labels.some((l) => l.id === 'top'),
    'подпись у самой кромки кадра не рисуется (обрезалась бы рамкой)');
  ok2(edge.labels.every((l) => l.y - l.height / 2 >= CM.DEFAULTS.padding
    && l.x - l.width / 2 >= CM.DEFAULTS.padding),
  'все подписи внутри кадра с отступом');
  // Узкий фильтр/плотный кластер: все подписи могут выпасть по коллизиям.
  // Тогда рисуется ОДНА — самая приоритетная, иначе карта = безымянные точки.
  const crowdedSame = [
    { id: 'a', x: 100, y: 100, kind: 'fact', title: 'Очень длинная подпись первая' },
    { id: 'b', x: 104, y: 102, kind: 'fact', title: 'Очень длинная подпись вторая' },
    { id: 'c', x: 106, y: 98, kind: 'fact', title: 'Очень длинная подпись третья' },
  ];
  const dense = CM.allocateLabels(crowdedSame, {
    scale: 1, viewport: { width: 260, height: 200 }, maxLabelChars: 30,
    fontSize: 11,
  });
  eq2(dense.labels.length, 1,
    'плотный кластер: подписана ровно одна точка, сцена не «немая»');
  ok2(dense.labels[0].id === 'a',
    'плотный кластер: подписана самая приоритетная (при равенстве — первая)');
  // Честное исключение: если ни одна подпись не помещается в кадр, подписей
  // нет — подписывать точку за кадром бессмысленно.
  const allOutside = CM.allocateLabels(
    [{ id: 'far', x: 900, y: 700, kind: 'fact', title: 'Далеко' }],
    { scale: 1, viewport: { width: 260, height: 200 } });
  eq2(allOutside.labels.length, 0,
    'всё за кадром — подписей нет (ни одного «висящего» имени)');
  // Точка В кадре, но у самой кромки: бокс подписи туда не помещается. Подпись
  // не выбрасывается, а СДВИГАЕТСЯ внутрь кадра — иначе узкий фильтр на
  // телефоне оставлял сцену вообще без имён (живой прогон 390: 3 узла, 0
  // подписей).
  const atEdge = CM.allocateLabels(
    [{ id: 'e1', x: 3, y: 3, kind: 'fact', title: 'У самой кромки кадра' }],
    { scale: 1, viewport: { width: 260, height: 200 }, fontSize: 11 });
  eq2(atEdge.labels.length, 1, 'точка у кромки всё равно подписана');
  // Допуск 0.5 px: сравнение с отступом после clamp идёт на границе и
  // упирается в плавающую точку (66.5 − 63.50000000000001 = 2.9999999999).
  const EPS_PX = 0.51;
  ok2(atEdge.labels[0].x - atEdge.labels[0].width / 2
      >= CM.DEFAULTS.padding - EPS_PX
    && atEdge.labels[0].y - atEdge.labels[0].height / 2
      >= CM.DEFAULTS.padding - EPS_PX
    && atEdge.labels[0].x + atEdge.labels[0].width / 2
       <= 260 - CM.DEFAULTS.padding + EPS_PX,
    'сдвинутая подпись целиком внутри кадра с отступом');
  // Несколько узлов у кромки: подписан самый приоритетный, а не случайный.
  const edgeMany = CM.allocateLabels([
    { id: 'z', x: 2, y: 40, kind: 'observation', title: 'Наблюдение у кромки' },
    { id: 'p', x: 4, y: 44, kind: 'paradigm', title: 'Парадигма у кромки' },
  ], { scale: 1, viewport: { width: 260, height: 200 }, fontSize: 11 });
  eq2(edgeMany.labels.map((l) => l.id), ['p'],
    'у кромки подписана самая приоритетная запись');

  return s2;
})();

checks += S2;
console.log('EVOL-COG-MAP-S2-OK checks=' + S2);

/* ═══ W7-S3 (карточка узла/ребра): что показано по payload, честное
 * отсутствие данных, обоснование связи и адресные переходы. Всё — чистые
 * функции адаптера (DOM/vis/сети здесь нет). */

const S3 = (function () {
  let s3 = 0;
  function ok3(cond, message) {
    assert.ok(cond, message);
    s3 += 1;
  }
  function eq3(actual, expected, message) {
    assert.deepStrictEqual(actual, expected, message);
    s3 += 1;
  }

  const model = CM.normalizePayload(payload(), { aliases: ALIASES });
  const byId = (id) => model.byId[id];
  const action = (card, id) => card.actions.filter((a) => a.id === id)[0];

  // ── 15. узлы: показ по наличию данных ──────────────────────────────────
  const fact = CM.nodeCard(byId('fact:-1001:1'), model);
  eq3(fact.kind, 'node', 'карточка узла помечена своим видом');
  eq3(fact.id, 'fact:-1001:1', 'карточка называет конкретную запись');
  eq3(fact.title, 'Любит утренний кофе без сахара', 'заголовок из модели');
  eq3(fact.text, 'Любит утренний кофе без сахара', 'полный текст из модели');
  eq3(fact.kindLabel, 'Факты', 'тип назван словом класса');
  eq3(fact.scope, 'chat', 'область записи сохранена');
  eq3(fact.chatId, -1001, 'чат записи сохранён');
  // Раздельные времена: только заполненные, каждая со своим названием.
  eq3(fact.times.map((t) => t.key), ['occurredAt', 'savedAt', 'confirmedAt'],
    'показаны только реально заполненные поля времени');
  eq3(fact.times.map((t) => t.label),
    ['Когда произошло', 'Когда сохранено', 'Когда подтверждено'],
    'у каждой даты своё название (не «дата» на всё)');
  eq3(fact.timesNote, '', 'при наличии времени примечание не нужно');
  // Provenance: источник/сообщение/основания.
  eq3(fact.provenance.messageId, 555, 'адрес сообщения-источника в карточке');
  eq3(fact.provenance.origin, 'chat_history', 'происхождение записи сохранено');
  // Метрики: только реально посчитанное + честное примечание.
  eq3(fact.metrics.rows.map((r) => r.key), ['importance', 'weight', 'degree'],
    'показаны importance/weight/degree — у каждой названа природа');
  ok3(fact.metrics.rows.every((r) => r.nature && r.nature.length > 3),
    'у каждой метрики названа её природа (не «доказательность»)');
  ok3(!/confidence|strength|freshness/.test(JSON.stringify(fact.metrics.rows)),
    'confidence/strength/freshness не выдумываются как метрики');
  ok3(fact.metrics.note.indexOf('не рассчитываются') >= 0,
    'нерасчитываемые метрики названы словами, а не нулём');
  // Время отсутствует целиком — честное «не указано», а не подстановка.
  const oldFact = CM.nodeCard(byId('fact:-1001:2'), model);
  eq3(oldFact.times, [], 'пустое время не заполняется соседней датой');
  eq3(oldFact.timesNote, 'время записи не указано',
    'отсутствие времени названо отсутствием');
  eq3(oldFact.provenance.messageId, null, 'нет сообщения — нет выдуманного id');
  eq3(oldFact.text, 'Старый факт про кофе', 'текст показан и без времени');

  // ── 16. четыре адресных перехода и честные причины отказа ───────────────
  eq3(fact.actions.map((a) => a.id), ['source', 'history', 'memory', 'links'],
    'карточка содержит ровно четыре контрактных действия');
  eq3(fact.actions.map((a) => a.label),
    ['Открыть источник', 'История изменений', 'Открыть в Памяти',
      'Показать связи'],
    'подписи кнопок — слова контракта');
  const source = action(fact, 'source');
  eq3(source.enabled, true, 'факт с сообщением: источник доступен');
  eq3(source.target,
    { type: 'record', source: 'fact', factId: 1, chatId: -1001, messageId: 555 },
    'цель «Открыть источник» — конкретная запись и конкретное сообщение');

  const entity = CM.nodeCard(byId('ent:-1001:10'), model);
  const entitySource = action(entity, 'source');
  eq3(entitySource.enabled, false,
    'у сущности нет сообщения — кнопка не работает');
  ok3(/сущности/.test(entitySource.reason),
    'причина отказа названа, а не скрыта: ' + entitySource.reason);
  eq3(entitySource.target, null, 'неработающее действие не имеет цели');

  const paradigm = CM.nodeCard(byId('paradigm:-1001:4'), model);
  const paradigmSource = action(paradigm, 'source');
  eq3(paradigmSource.enabled, false,
    'у парадигмы без сообщения источник недоступен');
  ok3(/сообщение не записано/.test(paradigmSource.reason),
    'причина — «сообщение не записано», без выдуманной ссылки');
  // Изолированный узел: связей не записано — это сказано словами.
  const linksIsolated = action(paradigm, 'links');
  eq3(linksIsolated.enabled, false, 'у изолированной парадигмы связей нет');
  ok3(/изолирован/.test(linksIsolated.reason),
    'изолированность названа причиной, а не пустым списком');
  eq3(paradigm.neighbors, [], 'соседи не дорисовываются из совпадения имён');
  // История: у записи без версий её честно нет.
  const belief = CM.nodeCard(byId('belief:-1001:3'), model);
  const historyNone = action(belief, 'history');
  eq3(historyNone.enabled, false, 'у записи без версий истории нет');
  eq3(historyNone.reason, 'версий этой записи не записано',
    'отсутствие истории названо, а не реконструировано');
  // У старой версии история ЕСТЬ и ведёт к конкретной новой записи.
  const historyOldFact = action(oldFact, 'history');
  eq3(historyOldFact.enabled, true, 'реальная связь версий делает историю доступной');
  eq3(historyOldFact.target, { type: 'node', id: 'fact:-1001:1' },
    'история ведёт к конкретной версии, а не в раздел');
  // История факта 1: реальное ребро revised_by (версия 2 → 1).
  const historyFact = action(fact, 'history');
  eq3(historyFact.enabled, true, 'реальная версия записи делает историю доступной');
  eq3(historyFact.target, { type: 'node', id: 'fact:-1001:2' },
    '«История изменений» ведёт к конкретной записи-версии, а не в раздел');
  eq3(fact.history.nodes.map((n) => n.id), ['fact:-1001:2'],
    'список версий — реальные узлы модели');
  // Память: поиск каталога предзаполняется названием и типом записи.
  const memory = action(fact, 'memory');
  eq3(memory.target,
    { type: 'memory', query: 'Любит утренний кофе без сахара', memoryType: 'facts' },
    '«Открыть в Памяти» несёт контекст узла (запрос и тип)');
  eq3(action(byId('paradigm:-1001:4') ? paradigm : paradigm, 'memory').target.memoryType,
    'context', 'парадигма ищется в каталоге как «контекст»');

  // ── 17. связи узла: строки ведут к конкретным рёбрам/записям ────────────
  const factLinks = action(fact, 'links');
  eq3(factLinks.enabled, true, 'у связанного факта «Показать связи» работает');
  eq3(factLinks.target.edgeIds.slice().sort(),
    ['derived:-1001:1:fact', 'revision:-1001:1:2'],
    'цель «Показать связи» — конкретные записанные рёбра');
  eq3(fact.neighbors.length, 2, 'карточка перечисляет реальные связи узла');
  ok3(fact.neighbors.every((n) => n.edgeId && n.id && n.relationLabel),
    'у каждой связи есть ребро, вторая запись и название типа');
  eq3(fact.neighbors[0].relationLabel, 'выведено из',
    'машинный тип связи назван по-русски');
  eq3(CM.relationLabel('обсуждали'), 'обсуждали',
    'реальный relation_type не переводится догадкой');
  eq3(CM.relationLabel(''), 'тип не указан',
    'пустой тип связи не притворяется названным');

  // ── 18. ребро: тип, обе сущности, обоснование ЗАПИСАНО или НЕТ ─────────
  const recorded = CM.edgeCard(model.edges.filter((e) => e.id === 'edge:-1001:1')[0],
    model);
  eq3(recorded.kind, 'edge', 'карточка ребра помечена своим видом');
  eq3(recorded.relation, 'обсуждали', 'тип связи показан как записан');
  eq3(recorded.derived, false, 'записанное ребро не выдаётся за производное');
  eq3(recorded.kindLabel, 'записана в графе', 'происхождение ребра названо');
  eq3(recorded.endpoints.map((e) => e.id), ['ent:-1001:10', 'ent:-1001:11'],
    'обе сущности ребра — конкретные узлы модели');
  eq3(recorded.endpoints.map((e) => e.title), ['Хаб', 'Тема'],
    'концы ребра названы заголовками записей');
  eq3(recorded.justification.recorded, true, 'обоснование из payload сохранено');
  ok3(recorded.justification.text.indexOf('фактом №1') > 0,
    'обоснование называет факт-основание: ' + recorded.justification.text);
  ok3(recorded.justification.rows.some((r) => r.key === 'basis'
    && r.value === 'fact_provenance'),
  'provenance ребра показан (источник связи)');

  const noJustification = CM.edgeCard(
    model.edges.filter((e) => e.id === 'derived:-1001:1:fact')[0], model);
  eq3(noJustification.justification.recorded, true,
    'производное ребро с fact_id имеет записанное обоснование');

  const superseded = CM.edgeCard(
    model.edges.filter((e) => e.id === 'revision:-1001:1:2')[0], model);
  eq3(superseded.justification.recorded, false,
    'у ребра версий отдельного факта-обоснования нет — не притворяемся');
  ok3(/замене версий/.test(superseded.justification.text)
    && /№2/.test(superseded.justification.text),
  'причина версии названа реальной записью: ' + superseded.justification.text);
  eq3(superseded.relationLabel, 'заменено версией',
    'ребро версий названо по-русски');

  const bare = CM.edgeCard({ id: 'edge:x', from: 'ent:-1001:10',
    to: 'ent:-1001:11', relation: '', derived: false,
    justificationRecorded: false, provenance: {} }, model);
  eq3(bare.justification.recorded, false, 'ребро без provenance честно без причины');
  eq3(bare.justification.text, 'обоснование не записано',
    'текст отсутствия обоснования — прямой, без «вероятно»');
  eq3(bare.relationLabel, 'тип не указан', 'пустой тип не выдумывается');
  eq3(bare.justification.rows, [], 'нет provenance — нет выдуманных строк');

  // ── 19. отсутствие данных не превращается в «правдоподобное» ───────────
  const empty = CM.normalizePayload({ version: 'cog-map/1', nodes: [
    { id: 'obs:1:5', kind: 'observation', title: 'Заметка', text: null,
      status: null, provenance: { record: 'mca_trait_observations',
        observation_id: 5, chat_id: 1, source_refs: [{ message_id: 9 }] } },
    { id: 'evt:1:revision:6', kind: 'evolution_event', title: 'Версия заменена',
      text: null, status: 'superseded', chat_id: 1,
      provenance: { record: 'graph_facts.supersedes', chat_id: 1,
        new_fact_id: 6, old_fact_id: 5 } },
  ], edges: [] });
  const obs = CM.nodeCard(empty.byId['obs:1:5'], empty);
  eq3(obs.text, null, 'у наблюдения нет текста — карточка не выдумывает');
  eq3(obs.textNote, 'текст записи не сохранён', 'отсутствие текста названо');
  eq3(obs.provenance.sourceRefs.length, 1,
    'ссылки источника показаны (реальные refs записи)');
  eq3(action(obs, 'source').enabled, false,
    'у наблюдения нет сообщения — источник недоступен');
  ok3(/наблюдения/.test(action(obs, 'source').reason),
    'причина отказа у наблюдения названа');
  const evt = CM.nodeCard(empty.byId['evt:1:revision:6'], empty);
  eq3(evt.textNote, 'текст записи не сохранён',
    'у записи изменения текста нет — это сказано');
  ok3(/изменения/.test(action(evt, 'source').reason),
    'у записи изменения нет сообщения — причина названа');
  ok3(evt.history.available === false, 'у самого события версий нет');

  // ── 20. детерминизм и защита от мусора ─────────────────────────────────
  eq3(JSON.stringify(CM.nodeCard(byId('fact:-1001:1'), model)),
    JSON.stringify(CM.nodeCard(byId('fact:-1001:1'), model)),
    'карточка детерминирована: повторный вызов даёт тот же результат');
  eq3(CM.nodeCard(null, model), null, 'без узла карточка не строится');
  eq3(CM.edgeCard(null, model), null, 'без ребра карточка не строится');
  eq3(CM.nodeTimes({ time: {} }), [], 'пустой блок времени — пустой список дат');
  eq3(CM.TIME_FIELDS.map((f) => f.key),
    ['occurredAt', 'observedAt', 'savedAt', 'confirmedAt', 'updatedAt'],
    'пять разных времён названы раздельно');

  return s3;
})();

checks += S3;
console.log('EVOL-COG-MAP-S3-OK checks=' + S3);
