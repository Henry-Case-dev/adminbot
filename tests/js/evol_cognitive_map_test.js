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
 * Успешный маркер: EVOL-COG-MAP-S1-OK (адаптер), -S2-OK (карта: легенда,
 * кластеры, бюджет подписей §9.2), -S3-OK (карточка узла/ребра: provenance,
 * обоснование связи, адресные переходы и их честные отказы).
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
    ['dot', 'dotRing', 'hexagon', 'diamond'],
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
  // CMV-C: палитра — ровно спека §4.1 (те же hex, что у сцены и CSS-легенды).
  eq2(CM.nodeStyle('fact').color, '#32C8F3', 'факты — циан #32C8F3');
  eq2(CM.nodeStyle('belief').color, '#A77BFF', 'убеждения — фиолетовый #A77BFF');
  eq2(CM.nodeStyle('paradigm').color, '#728CFF', 'парадигмы — #728CFF');
  eq2(CM.nodeStyle('evolution_event').color, '#FFB84D',
    'изменения — янтарный #FFB84D');
  eq2(CM.nodeStyle('entity').color, '#9FB4CE',
    'сущности — серебристо-голубой #9FB4CE');
  eq2(CM.nodeStyle('observation').color, '#D97706', 'наблюдения — #D97706');
  eq2(CM.nodeStyle('fact').shape, 'dot', 'факты — световая точка');
  eq2(CM.nodeStyle('belief').shape, 'dotRing', 'убеждения — круг с кольцом');
  eq2(CM.nodeStyle('entity').shape, 'sphere', 'сущности — сфера, а НЕ box');
  ok2(CM.KINDS.every((k) => CM.KIND_STYLE[k].shape !== 'box'),
    'ни один тип не рисуется прямоугольником (§4.1)');
  // Раскладка/сцена/легенда должны называть ОДИН цвет, иначе легенда врёт.
  const V = require(path.join(__dirname, '..', '..', 'web', 'static',
    'cog-visual.js'));
  ok2(CM.KINDS.every((k) => CM.KIND_STYLE[k].color
    === V.CONFIG.spec[k].color),
  'палитра адаптера совпадает с палитрой сцены (cog-visual)');
  ok2(CM.KINDS.every((k) => CM.KIND_STYLE[k].size
    === V.CONFIG.baseDiameter[k]),
  'размеры типов совпадают с базовыми диаметрами сцены');
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
  // CMV-D (побочная находка ревью CMV-C): имя кластера — САМАЯ ЧАСТАЯ
  // реальная парадигма, а не самый короткий заголовок. Семантика не меняется:
  // это подпись показа (фильтр «Кластер»), данные и связи те же.
  const titled = CM.computeClusters(CM.normalizePayload({
    version: 'cog-map/1', state: 'ok',
    nodes: [
      { id: 'paradigm:1:1', kind: 'paradigm', title: 'Alpha', chat_id: 1 },
      { id: 'paradigm:1:2', kind: 'paradigm', title: 'Alpha', chat_id: 1 },
      { id: 'paradigm:1:3', kind: 'paradigm', title: 'Zeta', chat_id: 1 },
      { id: 'paradigm:1:4', kind: 'paradigm', title: 'Zeta', chat_id: 1 },
      { id: 'paradigm:1:5', kind: 'paradigm', title: 'Zeta', chat_id: 1 },
      { id: 'fact:1:6', kind: 'fact', title: 'Факт', chat_id: 1 },
    ],
    edges: [
      { id: 't1', from: 'paradigm:1:1', to: 'fact:1:6', relation: 'about' },
      { id: 't2', from: 'paradigm:1:2', to: 'fact:1:6', relation: 'about' },
      { id: 't3', from: 'paradigm:1:3', to: 'fact:1:6', relation: 'about' },
      { id: 't4', from: 'paradigm:1:4', to: 'fact:1:6', relation: 'about' },
      { id: 't5', from: 'paradigm:1:5', to: 'fact:1:6', relation: 'about' },
    ],
  }));
  eq2(titled[0].paradigmTitle, 'Zeta',
    'кластер назван ЧАСТОЙ парадигмой, а не самой короткой (Alpha)');
  eq2(titled[0].label, 'Парадигмы: Zeta', 'подпись кластера — частая парадигма');
  eq2(CM.computeClusters(CM.normalizePayload({
    version: 'cog-map/1', state: 'ok',
    nodes: [
      { id: 'paradigm:2:1', kind: 'paradigm', title: 'Trust', chat_id: 2 },
      { id: 'paradigm:2:2', kind: 'paradigm', title: 'Trust', chat_id: 2 },
      { id: 'paradigm:2:3', kind: 'paradigm', title: 'Doubt', chat_id: 2 },
      { id: 'paradigm:2:4', kind: 'paradigm', title: 'Doubt', chat_id: 2 },
      { id: 'fact:2:5', kind: 'fact', title: 'Факт', chat_id: 2 },
      { id: 'fact:2:6', kind: 'fact', title: 'Второй', chat_id: 2 },
    ],
    edges: [
      { id: 'u1', from: 'paradigm:2:1', to: 'fact:2:5', relation: 'about' },
      { id: 'u2', from: 'paradigm:2:2', to: 'fact:2:6', relation: 'about' },
      { id: 'u3', from: 'paradigm:2:3', to: 'fact:2:5', relation: 'about' },
      { id: 'u4', from: 'paradigm:2:4', to: 'fact:2:6', relation: 'about' },
    ],
  }))[0].paradigmTitle, 'Doubt',
  'ничья по частоте решается детерминированно (короткий, затем алфавит)');

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
    { id: 'ent:1:7', kind: 'entity', title: '', text: null, status: null,
      chat_id: 1, provenance: { record: 'graph_entities', entity_id: 7,
        chat_id: 1 } },
  ], edges: [] });
  const obs = CM.nodeCard(empty.byId['obs:1:5'], empty);
  eq3(obs.text, null, 'у наблюдения нет текста — карточка не выдумывает');
  eq3(obs.textNote, 'Текст записи отсутствует', 'отсутствие текста названо');
  eq3(obs.provenance.sourceRefs.length, 1,
    'ссылки источника показаны (реальные refs записи)');
  eq3(action(obs, 'source').enabled, false,
    'у наблюдения нет сообщения — источник недоступен');
  ok3(/наблюдения/.test(action(obs, 'source').reason),
    'причина отказа у наблюдения названа');
  const evt = CM.nodeCard(empty.byId['evt:1:revision:6'], empty);
  eq3(evt.textNote, 'Текст записи отсутствует',
    'у записи изменения текста нет — это сказано');
  ok3(/изменения/.test(action(evt, 'source').reason),
    'у записи изменения нет сообщения — причина названа');
  ok3(evt.history.available === false, 'у самого события версий нет');

  // ── 19a. CMV-CARD-07: узел без заголовка ────────────────────────────────
  // Шапка карточки — нейтральная метка, сырой ID не становится заголовком;
  // сам ID сохраняется в модели карточки (детали/атрибут) и не пропадает.
  const ent = CM.nodeCard(empty.byId['ent:1:7'], empty);
  eq3(ent.title, 'Без названия',
    'без заголовка шапка карточки не показывает сырой ID');
  eq3(ent.titleAbsent, true, 'отсутствие заголовка помечено для деталей');
  eq3(ent.id, 'ent:1:7', 'ID записи остаётся в карточке (детали/атрибут)');
  eq3(ent.textNote, 'Текст записи отсутствует',
    'у узла без текста absent-формулировка та же');
  eq3(CM.nodeCard(byId('fact:-1001:1'), model).title,
    'Любит утренний кофе без сахара',
    'реальное название не подменяется меткой');
  eq3(CM.nodeCard(byId('fact:-1001:1'), model).titleAbsent, false,
    'у записи с названием пометки об отсутствии нет');

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


/* ── CMV-C: LOD (гистерезис), приоритет подписей, агрегаты L0, счётчики ──── */
const S4 = (function testCmvC() {
  let s4 = 0;
  function ok4(cond, message) {
    assert.ok(cond, message);
    s4 += 1;
  }
  function eq4(actual, expected, message) {
    assert.deepStrictEqual(actual, expected, message);
    s4 += 1;
  }
  function near4(actual, expected, message) {
    assert.ok(Math.abs(actual - expected) <= 1e-9,
      message + ' (получено ' + actual + ', ждали ' + expected + ')');
    s4 += 1;
  }

  // ── 1. LOD: формула, гистерезис, отсутствие мигания у порогов ──────────
  const T1 = CM.DEFAULTS.lod.t1;
  const T2 = CM.DEFAULTS.lod.t2;
  const D = CM.DEFAULTS.lod.delta;
  eq4([T1, T2, D], [0.85, 1.8, 0.12], '§4.2: T1=0.85, T2=1.80, δ=0.12');
  const small = { nodes: 10, density: 5 };
  // Подъём — по завышенному порогу, возврат — по заниженному.
  near4(T1 * (1 + D), 0.952, 'вход в рабочий вид: T1·(1+δ)');
  near4(T1 * (1 - D), 0.748, 'возврат в обзор: T1·(1−δ)');
  eq4(CM.lodFor(0.94, 0, small), 0, 'r=0.94 с уровня 0 остаётся обзором');
  eq4(CM.lodFor(0.96, 0, small), 1, 'r=0.96 с уровня 0 поднимает в рабочий');
  eq4(CM.lodFor(0.90, 1, small), 1, 'r=0.90 с уровня 1 НЕ сбрасывает (24 % зона)');
  // Именно ЗОНА: 0.80 лежит между T1·(1−δ)=0.748 и T1=0.85 и не должна сбрасывать.
  eq4(CM.lodFor(0.80, 1, small), 1,
    'r=0.80 остаётся рабочей (порог возврата занижен на δ)');
  eq4(CM.lodFor(0.60, 1, small), 0, 'r=0.60 — обзор');
  eq4(CM.lodFor(0.74, 1, small), 0, 'r=0.74 с уровня 1 опускает в обзор');
  eq4(CM.lodFor(1.90, 1, small), 1, 'r=1.90 с уровня 1 ещё не детальный');
  eq4(CM.lodFor(2.02, 1, small), 2, 'r=2.02 поднимает в детальный (T2·(1+δ))');
  eq4(CM.lodFor(1.60, 2, small), 2, 'r=1.60 с уровня 2 ещё детальный');
  eq4(CM.lodFor(1.57, 2, small), 1, 'r=1.57 с уровня 2 опускает в рабочий');
  eq4(CM.lodFor(0.70, 2, small), 0, 'r=0.70 с уровня 2 опускает в обзор');

  // Главное свойство: монотонный проход по r НЕ даёт колебаний уровня.
  function walk(start, target, steps) {
    let prev = start;
    const trace = [];
    for (let i = 1; i <= steps; i += 1) {
      const r = start + (target - start) * (i / steps);
      prev = CM.lodFor(r, prev, small);
      trace.push({ r: r, lod: prev });
    }
    return trace;
  }
  function bounces(trace) {
    const bad = [];
    for (let i = 1; i < trace.length; i += 1) {
      const grew = trace[i].r > trace[i - 1].r;
      if (grew && trace[i].lod < trace[i - 1].lod) bad.push(trace[i]);
      if (!grew && trace[i].lod > trace[i - 1].lod) bad.push(trace[i]);
    }
    return bad;
  }
  const up = walk(0.5, 2.6, 220);
  const down = walk(2.6, 0.5, 220);
  eq4(bounces(up), [], 'LOD: на увеличении уровня нет откатов (220 шагов)');
  eq4(bounces(down), [], 'LOD: на уменьшении нет прыжков вверх (220 шагов)');
  ok4(up[up.length - 1].lod === 2, 'LOD: к r=2.6 уровень детальный');
  ok4(down[down.length - 1].lod === 0, 'LOD: обратно к r=0.5 уровень обзорный');
  // Микро-дрожание колеса внутри зоны нечувствительности: уровень стоит.
  function jitter(start, amp, steps) {
    let prev = CM.lodFor(start, start >= 0.952 ? 1 : 0, small);
    const seen = [prev];
    for (let i = 0; i < steps; i += 1) {
      const r = start + (i % 2 === 0 ? amp : -amp);
      prev = CM.lodFor(r, prev, small);
      seen.push(prev);
    }
    return Array.from(new Set(seen));
  }
  eq4(jitter(0.945, 0.003, 40), [0],
    'LOD: дрожание НИЖЕ порога T1 не мигает (уровень постоянный)');
  eq4(jitter(0.960, 0.003, 40), [1],
    'LOD: дрожание ВЫШЕ порога T1 не сбрасывает уровень');
  eq4(jitter(1.90, 0.05, 40), [1],
    'LOD: дрожание у порога T2 не поднимает уровень раньше времени');
  eq4(jitter(2.05, 0.02, 40), [2],
    'LOD: дрожание у порога T2 не роняет детальный уровень');

  // ── 2. Плотностная поправка §5.2: плотный кадр = обзор ────────────────
  const dense = { nodes: 702, density: 176 };
  const sparse = { nodes: 702, density: 4 };
  eq4(CM.lodFor(1.0, 1, dense), 0,
    '§5.2: плотный кадр при r=1 читается как обзор (агрегаты)');
  eq4(CM.lodFor(1.0, 1, sparse), 1, '§5.2: разреженный кадр при r=1 — рабочий вид');
  eq4(CM.lodFor(1.0, 1, { nodes: 12, density: 900 }), 1,
    '§5.2: поправка не применяется к МЕЛКОМУ набору (240 порог)');
  eq4(CM.lodFor(1.4, 1, dense), 1,
    '§5.2: при приближении плотность больше не возвращает в обзор');
  eq4(CM.lodFor(2.3, 2, dense), 2, 'плотность не отменяет детальный уровень');
  eq4(CM.lodFor(1.0, 0, dense), 0, 'обзор по плотности устойчив (нет мигания)');
  eq4(CM.lodFor(1.0, 0, sparse), 1, 'обзор выходит, когда кадр перестал быть плотным');
  // Регресс F1 (ревью CMV-C): плотностная граница не мигает. Раньше выход из
  // обзора по плотности был жёстким `r > 1.05`, и при 702 узлах уровень
  // переключался на каждом событии колеса (1.045/1.060 = 12 переключений).
  const denseWalk = { nodes: 702, density: 176 };
  function denseTrace(startR, endR, step, prev) {
    const out = [];
    let p = prev;
    const dir = endR >= startR ? 1 : -1;
    for (let r = startR; dir > 0 ? r <= endR + 1e-9 : r >= endR - 1e-9;
      r += dir * step) {
      p = CM.lodFor(Math.round(r * 1000) / 1000, p, denseWalk);
      out.push({ r: Math.round(r * 1000) / 1000, lod: p });
    }
    return out;
  }
  function switches(trace) {
    let n = 0;
    for (let i = 1; i < trace.length; i += 1) {
      if (trace[i].lod !== trace[i - 1].lod) n += 1;
    }
    return n;
  }
  const upBand = denseTrace(1.0, 1.15, 0.005, 0);
  eq4(switches(upBand), 0,
    '§5.1: обход 1.00→1.15 в плотном кадре не переключает уровень');
  const backBand = denseTrace(1.15, 1.0, 0.005, 0);
  eq4(switches(backBand), 0,
    '§5.1: обход 1.15→1.00 в плотном кадре не переключает уровень');
  const roundTrip = upBand.concat(backBand.slice(1));
  eq4(switches(roundTrip), 0,
    '§5.1: плотностная полоса гасит дрожание ±1.5 % у границы 1.05');
  ok4(upBand.every((s) => s.lod === 0),
    '§5.1: внутри полосы плотный кадр остаётся обзором');
  // Выход из плотного обзора — только с запасом: r > denseMax·(1+δ) = 1.176.
  eq4(CM.lodFor(1.17, 0, denseWalk), 0, '§5.1: r=1.17 ещё внутри полосы обзора');
  eq4(CM.lodFor(1.19, 0, denseWalk), 1, '§5.1: r=1.19 уже вне полосы — рабочий вид');
  eq4(CM.lodFor(1.19, 1, denseWalk), 1, '§5.1: обратно в обзор по плотности не тянет');
  eq4(CM.lodFor(1.04, 1, denseWalk), 0, '§5.1: вход в обзор по плотности — до 1.05');
  // Дрожание ±0.01 около самой границы входа: переход возможен не более одного
  // раза (вход в обзор), обратных переключений быть не должно.
  let jprev = 1;
  const jseen = [jprev];
  for (let i = 0; i < 60; i += 1) {
    jprev = CM.lodFor(i % 2 === 0 ? 1.04 : 1.06, jprev, denseWalk);
    jseen.push(jprev);
  }
  ok4(switches(jseen.map((lod) => ({ lod }))) <= 1,
    '§5.1: дрожание ±0.01 у 1.05 даёт не более одного переключения');
  eq4(jseen[jseen.length - 1], 0,
    '§5.1: после дрожания у границы уровень остаётся обзорным');
  // Гистерезис плотности: кадр, переставший быть плотным, отпускает обзор.
  eq4(CM.lodFor(1.0, 0, { nodes: 702, density: 50 }), 0,
    '§5.1: плотность в 20 % полосе (50 из 60) ещё держит обзор');
  eq4(CM.lodFor(1.0, 0, { nodes: 702, density: 40 }), 1,
    '§5.1: плотность ниже 48/100k отпускает обзор');
  // Плотность считается от площади кадра, а не от константы.
  near4(CM.lodDensity(702, 1252, 318), 176.32165893061668,
    'плотность = узлы на 100k px²');
  eq4(CM.lodDensity(0, 1252, 318), 0, 'плотность пустого кадра = 0');
  eq4(CM.lodDensity(10, 0, 0), 0, 'неизмеренная сцена не даёт плотности');
  eq4(CM.lodTopK(702), 40, '§4.3: K = min(40, ⌈702/12⌉)');
  eq4(CM.lodTopK(24), 2, '§4.3: K = ⌈24/12⌉ = 2 для малого набора');

  // ── 3. Приоритет подписей: явный ранг, а не «похожесть» ────────────────
  eq4(CM.LABEL_RANK.selected, 0, 'ранг: выбранный — первый');
  eq4(CM.LABEL_RANK.search, 1, 'ранг: найденный поиском — второй (§4.4)');
  eq4(CM.LABEL_RANK.hover, 2, 'ранг: hover — третий');
  eq4(CM.LABEL_RANK.neighbor, 3, 'ранг: сосед выбранного — четвёртый');
  eq4(CM.LABEL_RANK.group, 4, 'ранг: центр группы — пятый (уровень 0)');
  eq4(CM.LABEL_RANK.other, 5, 'ранг: обычный узел — последний');
  eq4(CM.labelRankOf({ selected: true, neighbor: true }), 0,
    'выбранный не понижается флагом соседа');
  eq4(CM.labelRankOf({ group: true }), 4, 'группа получает ранг группы');
  eq4(CM.labelRankOf({ rank: 7 }), 7, 'явный ранг вызывающего уважается');

  const crowd = [
    { id: 'n1', x: 100, y: 100, kind: 'paradigm', title: 'Парадигма', degree: 9 },
    { id: 'n2', x: 102, y: 100, kind: 'paradigm', title: 'Парадигма 2', degree: 9 },
    { id: 'n3', x: 104, y: 100, kind: 'fact', title: 'Факт', degree: 1 },
  ];
  const prio = CM.allocateLabels(crowd, {
    scale: 1, viewport: { width: 200, height: 120 }, maxLabelChars: 12,
  });
  eq4(prio.labels.length, 1, 'тесный кадр: помещается одна подпись');
  eq4(prio.labels[0].id, 'n1', 'при равенстве — по приоритету типа и id');
  const chosen = CM.allocateLabels(crowd.concat([
    { id: 'sel', x: 100, y: 100, kind: 'fact', title: 'Выбранный', selected: true },
  ]), { scale: 1, viewport: { width: 200, height: 120 }, maxLabelChars: 12 });
  eq4(chosen.labels[0].id, 'sel',
    '§4.4: выбранный узел подписывается первым, даже рядом с парадигмами');
  const searched = CM.allocateLabels(crowd.concat([
    { id: 'hit', x: 100, y: 100, kind: 'other', title: 'Найденный', search: true },
  ]), { scale: 1, viewport: { width: 200, height: 120 }, maxLabelChars: 12 });
  eq4(searched.labels[0].id, 'hit', '§4.4: результат поиска важнее обычных узлов');
  const hovered = CM.allocateLabels(crowd.concat([
    { id: 'hov', x: 100, y: 100, kind: 'other', title: 'Наведение', hover: true },
  ]), { scale: 1, viewport: { width: 200, height: 120 }, maxLabelChars: 12 });
  eq4(hovered.labels[0].id, 'hov', '§4.4: hover важнее обычных узлов');

  // ── 4. Коллизии: подписи в экранных координатах не накладываются ───────
  const many = [];
  for (let i = 0; i < 60; i += 1) {
    many.push({
      id: 'g' + i,
      x: 40 + ((i * 53) % 700),
      y: 30 + ((i * 97) % 380),
      kind: ['fact', 'belief', 'paradigm', 'entity'][i % 4],
      title: 'Подпись номер ' + i,
      degree: i % 7,
    });
  }
  const packed = CM.allocateLabels(many, {
    scale: 1.2, viewport: { width: 800, height: 440 }, maxLabelChars: 24,
  });
  ok4(packed.labels.length >= 4, 'плотный кадр всё равно подписан');
  let overlapPairs = 0;
  for (let i = 0; i < packed.labels.length; i += 1) {
    for (let j = i + 1; j < packed.labels.length; j += 1) {
      if (CM.boxesOverlap(packed.labels[i], packed.labels[j], 0)) overlapPairs += 1;
    }
  }
  eq4(overlapPairs, 0, '§4.4: в экранных координатах подписи не накладываются');
  ok4(packed.labels.every((l) => l.x - l.width / 2 >= 0
    && l.x + l.width / 2 <= 800), 'подписи целиком внутри кадра по X');
  // Детерминизм: тот же кадр — тот же план (никаких «прыгающих» подписей).
  const packed2 = CM.allocateLabels(many, {
    scale: 1.2, viewport: { width: 800, height: 440 }, maxLabelChars: 24,
  });
  eq4(packed2.labels.map((l) => l.id), packed.labels.map((l) => l.id),
    'план подписей детерминирован при одном кадре');

  // ── 5. Агрегаты уровня 0: реальные элементы, честные числа, обратимость ─
  const aggNodes = [];
  const aggPos = {};
  const aggEdges = [];
  let seed = 7;
  function rnd(limit) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return (seed >> 7) % limit;
  }
  const kinds = ['fact', 'belief', 'paradigm', 'entity'];
  for (let c = 0; c < 3; c += 1) {
    for (let i = 0; i < 30; i += 1) {
      const id = 'a' + c + '_' + i;
      aggNodes.push({
        id: id, kind: kinds[(c + i) % 3], degree: 1 + (i % 6),
        title: 'Запись ' + c + '-' + i,
      });
      aggPos[id] = { x: c * 420 + (i % 6) * 34, y: Math.floor(i / 6) * 40 };
      if (i > 0) aggEdges.push({ id: 'e' + c + '_' + i, from: 'a' + c + '_' + (i - 1), to: id });
    }
  }
  // Мост между районами — РЕАЛЬНОЕ ребро (иначе потоков быть не должно).
  aggEdges.push({ id: 'bridge', from: 'a0_0', to: 'a1_5' });
  const agg = CM.buildAggregates({
    nodes: aggNodes, edges: aggEdges, positions: aggPos, fitScale: 1,
    camera: { x: 0, y: 0, scale: 1 }, viewport: { width: 1300, height: 400 },
    tileCss: 220,
  });
  ok4(agg.groups.length >= 2,
    'L0: районная сетка даёт несколько центров (' + agg.groups.length + ')');
  const allMembers = [];
  const realIds = new Set(aggNodes.map((n) => n.id));
  let membersReal = true;
  agg.groups.forEach((g) => {
    ok4(Array.isArray(g.memberIds) && g.memberIds.length === g.count,
      'L0: count равен числу реальных участников');
    ok4(typeof g.label === 'string' && g.label.indexOf('· ' + g.count) > 0,
      'L0: подпись несёт РЕАЛЬНОЕ число элементов (' + g.label + ')');
    ok4(realIds.has(g.apexId), 'L0: якорь группы — реальный узел (' + g.apexId + ')');
    g.memberIds.forEach((m) => {
      allMembers.push(m);
      if (!realIds.has(m)) membersReal = false;
    });
  });
  ok4(membersReal, 'L0: все участники — РЕАЛЬНЫЕ id из набора');
  eq4(allMembers.length, aggNodes.length,
    'L0: агрегаты покрывают весь размещённый набор');
  eq4(new Set(allMembers).size, allMembers.length,
    'L0: ни один узел не входит в два района');
  eq4(agg.grouped, aggNodes.length, 'L0: «свёрнуто» = все размещённые узлы');
  eq4(agg.total, aggNodes.length, 'L0: total = размещённые узлы');
  ok4(agg.groups.every((g) => g.id.indexOf('agg:') === 0),
    'L0: у агрегатов собственные id, не пересекающиеся с узлами');
  // Центры разведены: кольца не накладываются друг на друга.
  let minGap = Infinity;
  for (let i = 0; i < agg.groups.length; i += 1) {
    for (let j = i + 1; j < agg.groups.length; j += 1) {
      const a = agg.groups[i];
      const b = agg.groups[j];
      const d = Math.hypot(a.sx - b.sx, a.sy - b.sy);
      minGap = Math.min(minGap, d - (a.radius + b.radius));
    }
  }
  ok4(minGap > -1, 'L0: центры районов разведены (кольца не слипаются)');
  // Тесный кадр: два района физически не влезают рядом — центры обязаны
  // разъехаться, иначе кольца сливаются в одно пятно.
  const tightNodes = [];
  const tightPos = {};
  for (let i = 0; i < 60; i += 1) {
    const id = 't' + i;
    tightNodes.push({ id: id, kind: 'fact', degree: 1, title: 't' + i });
    tightPos[id] = { x: (i % 10) * 30, y: Math.floor(i / 10) * 20 };
  }
  const tight = CM.buildAggregates({
    nodes: tightNodes, edges: [], positions: tightPos, fitScale: 1,
    camera: { x: 0, y: 0, scale: 1 }, viewport: { width: 200, height: 120 },
    tileCss: 220,
  });
  ok4(tight.groups.length >= 2, 'тесный кадр: районов не меньше двух');
  let tightMin = Infinity;
  for (let i = 0; i < tight.groups.length; i += 1) {
    for (let j = i + 1; j < tight.groups.length; j += 1) {
      const a = tight.groups[i];
      const b = tight.groups[j];
      tightMin = Math.min(tightMin, Math.hypot(a.sx - b.sx, a.sy - b.sy)
        - (a.radius + b.radius));
    }
  }
  ok4(tightMin > 0,
    'тесный кадр: кольца районов не соприкасаются (зазор ' + tightMin.toFixed(1) + ')');
  ok4(agg.groups.every((g) => g.sx >= 0 && g.sx <= 1300
    && g.sy >= 0 && g.sy <= 400), 'L0: центры остаются в кадре');
  // Потоки — только реальные рёбра между районами.
  const groupOf = {};
  agg.groups.forEach((g) => g.memberIds.forEach((m) => { groupOf[m] = g.id; }));
  const realCross = aggEdges.filter((e) => groupOf[e.from]
    && groupOf[e.to] && groupOf[e.from] !== groupOf[e.to]).length;
  const flowSum = agg.flows.reduce((acc, f) => acc + f.count, 0);
  eq4(flowSum, realCross, 'L0: сумма потоков = число реальных межузловых связей');
  const groupIds = new Set(agg.groups.map((g) => g.id));
  ok4(agg.flows.every((f) => groupIds.has(f.from) && groupIds.has(f.to)
    && f.from !== f.to && f.count > 0),
  'L0: потоки ссылаются на существующие районы и не «сами на себя»');
  // Обратимость: по memberIds район можно раскрыть в реальные узлы.
  const first = agg.groups[0];
  const back = first.memberIds.filter((id) => realIds.has(id));
  eq4(back.length, first.count, 'L0: район обратим в реальные узлы');
  // Детерминизм и независимость от камеры (группировка та же при сдвиге).
  const aggMoved = CM.buildAggregates({
    nodes: aggNodes, edges: aggEdges, positions: aggPos, fitScale: 1,
    camera: { x: 55, y: -20, scale: 1 }, viewport: { width: 1300, height: 400 },
    tileCss: 220,
  });
  eq4(aggMoved.groups.map((g) => g.memberIds.join(',')),
    agg.groups.map((g) => g.memberIds.join(',')),
    'L0: состав районов не зависит от положения камеры');
  ok4(aggMoved.groups[0].sx !== agg.groups[0].sx,
    'L0: экранные центры зависят от камеры (проекция, а не мировые координаты)');
  // Смешанный район не выдумывает «тему».
  const mixed = agg.groups.filter((g) => g.dominantShare < 0.8);
  ok4(mixed.every((g) => g.label.indexOf(CM.GROUP_NEUTRAL_LABEL) === 0),
    'L0: смешанный район подписан нейтрально («' + CM.GROUP_NEUTRAL_LABEL + '»)');
  // Регресс F2 (ревью CMV-C): тема района — ДОМИНИРУЮЩАЯ парадигма, а не первая
  // по алфавиту. Раньше подпись брала лексикографически первый заголовок и
  // выдавала его за тему всего района (§5.2/§13).
  function oneDistrict(members) {
    const nodes = [];
    const positions = {};
    members.forEach((m, idx) => {
      nodes.push({ id: m.id, kind: m.kind, degree: 1, title: m.title });
      positions[m.id] = { x: 40 + (idx % 3) * 30, y: 40 + Math.floor(idx / 3) * 26 };
    });
    return CM.buildAggregates({
      nodes: nodes, edges: [], positions: positions, fitScale: 1,
      camera: { x: 0, y: 0, scale: 1 }, viewport: { width: 900, height: 400 },
      tileCss: 220, minMembers: 6,
    });
  }
  // Три равновесные парадигмы: «Альфа» первая по алфавиту, но не доминирует.
  const splitMembers = [];
  ['Альфа', 'Бета', 'Гамма'].forEach((title, t) => {
    for (let i = 0; i < 3; i += 1) {
      splitMembers.push({ id: 'p' + t + i, kind: 'paradigm', title: title });
    }
  });
  for (let i = 0; i < 3; i += 1) {
    splitMembers.push({ id: 'sf' + i, kind: 'fact', title: 'Наблюдение ' + i });
  }
  const splitAgg = oneDistrict(splitMembers);
  eq4(splitAgg.groups.length, 1, '§5.2: район из 12 узлов собран в один');
  const splitGroup = splitAgg.groups[0];
  ok4(splitGroup.dominantKind === 'paradigm' && splitGroup.dominantShare >= 0.6,
    '§5.2: парадигмы — доминирующий тип района');
  ok4(splitGroup.paradigmShare < 0.6,
    '§5.2: ни одна парадигма не доминирует (доля ' + splitGroup.paradigmShare + ')');
  eq4(splitGroup.label, CM.GROUP_NEUTRAL_LABEL + ' · 12',
    '§5.2: район без доминирующей парадигмы подписан нейтрально («'
      + splitGroup.label + '»)');
  ok4(splitGroup.label.indexOf('Альфа') < 0,
    '§5.2: алфавитно первая парадигма не выдаётся за тему района');
  // Даже когда парадигмы — 90 % состава, в подписи не появляется КОНКРЕТНОЕ
  // название: тема не выдумывается, называется только тип.
  const kindOnlyMembers = splitMembers.slice(0, 9);
  kindOnlyMembers.push({ id: 'kf0', kind: 'fact', title: 'Единственный факт' });
  const kindOnlyGroup = oneDistrict(kindOnlyMembers).groups[0];
  ok4(kindOnlyGroup.dominantKind === 'paradigm' && kindOnlyGroup.paradigmShare < 0.6,
    '§5.2: тип парадигм доминирует, конкретное название — нет');
  ok4(kindOnlyGroup.label.indexOf('Альфа') < 0
    && kindOnlyGroup.label.indexOf('Бета') < 0
    && kindOnlyGroup.label.indexOf('Гамма') < 0,
  '§5.2: ни одно недоминирующее название не попадает в подпись ('
    + kindOnlyGroup.label + ')');
  // Одна парадигма ≥60 % — её название район подписать вправе.
  const dominantMembers = [];
  for (let i = 0; i < 7; i += 1) {
    dominantMembers.push({ id: 'd' + i, kind: 'paradigm', title: 'Доверие' });
  }
  for (let i = 0; i < 3; i += 1) {
    dominantMembers.push({ id: 'df' + i, kind: 'fact', title: 'Факт ' + i });
  }
  const dominantAgg = oneDistrict(dominantMembers);
  eq4(dominantAgg.groups.length, 1, '§5.2: район с доминантой собран в один');
  const dominantGroup = dominantAgg.groups[0];
  ok4(dominantGroup.paradigmTitle === 'Доверие',
    '§5.2: тема района — самая частая парадигма («' + dominantGroup.paradigmTitle + '»)');
  eq4(dominantGroup.label, CM.KIND_LABELS.paradigm + ': Доверие · 10',
    '§5.2: доминирующая парадигма называется в подписи района');
  // Та же парадигма доминирует по ТИПУ, но её заголовок — лишь 5 из 12:
  // название темы всё равно не выводится (иначе район назван по 1 узлу).
  const thinMembers = [];
  for (let i = 0; i < 5; i += 1) {
    thinMembers.push({ id: 'td' + i, kind: 'paradigm', title: 'Доверие' });
  }
  ['Воля', 'Ирония', 'Тревога', 'Надежда', 'Сомнение'].forEach((title, t) => {
    thinMembers.push({ id: 'tu' + t, kind: 'paradigm', title: title });
  });
  for (let i = 0; i < 2; i += 1) {
    thinMembers.push({ id: 'tf' + i, kind: 'fact', title: 'Факт ' + i });
  }
  const thinAgg = oneDistrict(thinMembers);
  const thinGroup = thinAgg.groups[0];
  ok4(thinGroup.dominantKind === 'paradigm' && thinGroup.dominantShare >= 0.6
    && thinGroup.paradigmShare < 0.6,
  '§5.2: тип доминирует, а конкретный заголовок — нет ('
    + thinGroup.paradigmShare + ')');
  ok4(thinGroup.paradigmTitle === 'Доверие',
    '§5.2: самая частая парадигма всё же определяется («' + thinGroup.paradigmTitle + '»)');
  ok4(thinGroup.label.indexOf('Доверие') < 0 && thinGroup.label.indexOf('Воля') < 0,
    '§5.2: парадигма с долей ниже 0.6 не становится темой района ('
      + thinGroup.label + ')');
  eq4(thinGroup.label, CM.KIND_LABELS.paradigm + ' · 12',
    '§5.2: при 0.83 парадигм называется ТИП, а не конкретное название');
  // Пустой вход — пустой выход (никаких «центров в нуле»).
  const aggEmpty = CM.buildAggregates({ nodes: [], edges: [], positions: {} });
  eq4([aggEmpty.groups.length, aggEmpty.total, aggEmpty.grouped], [0, 0, 0],
    'L0: пустой набор не даёт агрегатов');
  const aggNoPos = CM.buildAggregates({
    nodes: [{ id: 'x', kind: 'fact', degree: 0, title: 'x' }],
    edges: [], positions: {}, fitScale: 1,
  });
  eq4(aggNoPos.total, 0, 'L0: узел без позиции не агрегируется');
  const aggBadPos = CM.buildAggregates({
    nodes: [
      { id: 'ok1', kind: 'fact', degree: 0, title: 'a' },
      { id: 'nan1', kind: 'fact', degree: 0, title: 'b' },
      { id: 'str1', kind: 'fact', degree: 0, title: 'c' },
    ],
    edges: [],
    positions: { ok1: { x: 10, y: 10 }, nan1: { x: NaN, y: 5 }, str1: { x: 'x', y: 7 } },
    fitScale: 1,
  });
  eq4(aggBadPos.total, 1,
    'L0: нечисловые координаты не превращаются в «центр в нуле»');
  eq4(aggBadPos.groups.reduce((acc, g) => acc + g.count, 0), 1,
    'L0: в агрегаты попадают только размещённые узлы');

  // ── 6. Счётчики §9.9: четыре разные величины, без смешивания ───────────
  const countModel = {
    nodes: new Array(30).fill(0),
    edges: new Array(50).fill(0),
    shownOf: { byKind: {}, totals: { nodes: 52600, edges: 98000 } },
  };
  const countView = { nodes: new Array(12).fill(0), edges: new Array(19).fill(0) };
  const countScene = {
    aggregates: [
      { id: 'agg:1', count: 5, hideMembers: true },
      { id: 'agg:2', count: 3, hideMembers: false },
    ],
  };
  const counts = CM.countSummary({
    model: countModel, view: countView, scene: countScene,
  });
  eq4(counts.api.nodes, 30, 'счётчики: «из API» — узлы принятого набора');
  eq4(counts.api.edges, 50, 'счётчики: «из API» — связи принятого набора');
  eq4(counts.filter.nodes, 12, 'счётчики: «после фильтра» — своя величина');
  eq4(counts.filter.ofNodes, 30, 'счётчики: «видно X из Y» знает Y');
  eq4(counts.screen.aggregates, 2, 'счётчики: «на экране» — число агрегатов');
  eq4(counts.screen.aggregated, 8, 'счётчики: «на экране» — свёрнуто в агрегаты');
  eq4(counts.screen.collapsed, 1, 'счётчики: свёрнутых районов один');
  eq4(counts.screen.nodes, 4, 'счётчики: различимых поштучно = витрина − свёрнутые');
  eq4(counts.screen.total, 12, 'счётчики: сумма «на экране» = витрина');
  eq4(counts.db.known, true, 'счётчики: сервер прислал «всего» — это отдельный факт');
  eq4(counts.db.nodes, 52600, 'счётчики: «в БД» — прямой итог сервера');
  eq4(counts.db.edges, 98000, 'счётчики: связи «всего в базе» не равны связям API');
  ok4(counts.db.nodes !== counts.api.nodes || counts.db.nodes === null,
    'счётчики: «в БД» и «из API» — РАЗНЫЕ величины, не смешаны');
  const countsUnknown = CM.countSummary({
    model: { nodes: [1], edges: [] }, view: { nodes: [1], edges: [] }, scene: null,
  });
  eq4(countsUnknown.db.nodes, null, 'счётчики: без shownOf «в БД» = null (не выдумка)');
  eq4(countsUnknown.db.known, false, 'счётчики: «в БД» помечено как неизвестное');
  eq4(countsUnknown.screen.aggregates, 0, 'счётчики: без агрегатов экран честный');

  return s4;
})();

checks += S4;
console.log('EVOL-CMV-C-LOD-MAP-OK checks=' + S4);
checks += S3;
console.log('EVOL-COG-MAP-S3-OK checks=' + S3);
