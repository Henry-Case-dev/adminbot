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
