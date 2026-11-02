/* EVOL-COG-MAP (W7-S1) — клиентский адаптер «Когнитивной карты».
 *
 * Контракт: `plans/features/evol/arch/cog-map-contract.md` §3/§5.
 * Роль слоя: `GET /api/memory/cognitive-map` -> нормализованная модель ->
 * (S2) vis-network. Здесь НЕТ DOM, vis-network и сетевых вызовов: модуль
 * целиком состоит из чистых функций, поэтому проверяется в node без браузера
 * (`tests/js/evol_cognitive_map_test.js`).
 *
 * Zero-build / CSP `script-src 'self'`: обычный внешний файл по образцу
 * `web/static/execution_graph.js` — без inline, CDN, сборщика и зависимостей.
 *
 * Честность модели (повторяет контракт, а не улучшает его):
 *  - узлы без подтверждённых рёбер остаются `isolated: true`;
 *  - рёбра принимаются ТОЛЬКО когда оба конца есть в payload (концы не
 *    дорисовываются, «плотность ради красоты» запрещена);
 *  - `confidence`/`strength`/`freshness` не вычисляются и не появляются:
 *    неизвестное поле остаётся `null`;
 *  - степень (`degree`) считается по показанным рёбрам — это метрика
 *    отображения, а не «доказательность»;
 *  - версия payload проверяется: незнакомая версия не ломает разбор, но
 *    оставляет честный `warnings` (S2 показывает состояние, а не молчит).
 *
 * Соглашения об именах (camelCase) — как у `ExecutionGraph`: payload в
 * snake_case, модель в camelCase, конвертация только здесь.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;            // node unit-тесты
  }
  if (root) {
    root.CognitiveMap = api;         // браузер: window.CognitiveMap
  }
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var VERSION = 'cog-map/1';
  var ACCEPTED_VERSIONS = [VERSION];

  // Порядок как в контракте §2.3; незнакомый kind -> 'other' (данные не
  // теряются, но и не выдумывается новый тип).
  var KINDS = ['entity', 'fact', 'belief', 'paradigm', 'observation',
    'evolution_event', 'other'];
  var KIND_LABELS = {
    entity: 'Сущности',
    fact: 'Факты',
    belief: 'Убеждения',
    paradigm: 'Парадигмы',
    observation: 'Наблюдения',
    evolution_event: 'Изменения',
    other: 'Прочее',
  };
  // Приоритет подписи: парадигмы — центры кластеров, дальше по контракту §2.4.
  var KIND_PRIORITY = {
    paradigm: 0, belief: 1, fact: 2, entity: 3,
    observation: 4, evolution_event: 5, other: 6,
  };

  var DEFAULTS = {
    maxLabels: 26,        // §5 контракта: существующий maxVisible = 26
    mobileMaxLabels: 12,  // §5: визуальная константа мобильного режима
    overviewScale: 0.55,  // ниже — LOD overview: только приоритетные подписи
    detailScale: 1.2,     // начиная отсюда — detail: все места под подписи
    padding: 3,
    fontSize: 11,
    maxLabelChars: 34,
    charWidth: 0.55,      // доля fontSize на символ (кириллица, усреднённо)
    minScale: 0.15,
    maxScale: 4,
    // W7-S2: «данные на HH:MM» — порог устаревания считается на клиенте от
    // `generated_at` (контракт §4: `stale` — клиентское состояние, сервер его
    // не отдаёт). 15 минут = ритм существующего cognition-polling.
    staleMs: 15 * 60 * 1000,
  };

  /* ── визуальная система (§2.4 контракта) ─────────────────────────────── */
  /* Токены — существующая палитра приложения (user/topic/event/indigo), новых
   * цветов не вводится. Цвет НЕ единственный различитель: у каждого класса
   * своя форма, размер и строка легенды. `legend: true` — только четыре
   * класса, названные владельцем (Факты/Убеждения/Парадигмы/Изменения);
   * сущности и наблюдения — контекст, их строки легенды вторичны. */
  var KIND_STYLE = {
    fact: { color: '#38bdf8', shape: 'dot', size: 13, legend: true },
    belief: { color: '#a78bfa', shape: 'rounded', size: 15, legend: true },
    paradigm: { color: '#818cf8', shape: 'hexagon', size: 22, legend: true },
    evolution_event: { color: '#f59e0b', shape: 'diamond', size: 13,
      legend: true },
    observation: { color: '#d97706', shape: 'diamond', size: 10,
      legend: false },
    entity: { color: '#94a3b8', shape: 'box', size: 11, legend: false },
    other: { color: '#64748b', shape: 'dot', size: 10, legend: false },
  };
  // Порядок строк легенды = порядок слов владельца (ТЗ 1285).
  var LEGEND_ORDER = ['fact', 'belief', 'paradigm', 'evolution_event'];
  // Вторичные классы: показываются в легенде только если реально есть.
  var LEGEND_EXTRA = ['entity', 'observation'];

  var STATE_LABELS = {
    loading: 'загрузка карты…',
    not_loaded: 'визуализация грузится — счётчики уже видны',
    renderer_failed: 'визуализация недоступна — данные и счётчики сохранены',
    empty: 'в этой области нет фактов и связей',
    ready: '',
  };

  function numberOrNull(value) {
    if (value === null || value === undefined || value === '') return null;
    var n = Number(value);
    return isFinite(n) ? n : null;
  }

  function numberOr(value, fallback) {
    var n = numberOrNull(value);
    return n === null ? fallback : n;
  }

  function normalizeQuery(value) {
    return String(value === null || value === undefined ? '' : value)
      .toLowerCase().replace(/ё/g, 'е')
      .replace(/\s+/g, ' ').trim();
  }

  function aliasList(aliasMap, title) {
    if (!aliasMap || !title) return [];
    var key = normalizeQuery(title);
    var raw = aliasMap[key];
    if (raw === undefined) {
      // допускаем исходный (ненормализованный) ключ — карты алиасов проекта
      // приходят как есть (`summaryAliasesMap`).
      raw = aliasMap[title];
    }
    if (raw === undefined || raw === null) return [];
    var list = Array.isArray(raw) ? raw : String(raw).split(',');
    var out = [];
    for (var i = 0; i < list.length; i += 1) {
      var alias = normalizeQuery(list[i]);
      if (alias && out.indexOf(alias) < 0) out.push(alias);
    }
    return out;
  }

  function searchBlob(node) {
    var parts = [normalizeQuery(node.title)];
    for (var i = 0; i < node.aliases.length; i += 1) parts.push(node.aliases[i]);
    return parts.join(' ').replace(/\s+/g, ' ').trim();
  }

  function normalizeTime(raw) {
    var time = raw && typeof raw === 'object' ? raw : {};
    return {
      occurredAt: numberOrNull(time.occurred_at),
      observedAt: numberOrNull(time.observed_at),
      savedAt: numberOrNull(time.saved_at),
      confirmedAt: numberOrNull(time.confirmed_at),
      updatedAt: numberOrNull(time.updated_at),
    };
  }

  function normalizeNode(raw, aliasMap) {
    if (!raw || typeof raw !== 'object') return null;
    if (typeof raw.id !== 'string' || !raw.id) return null;
    var kind = KINDS.indexOf(raw.kind) >= 0 ? raw.kind : 'other';
    var metrics = raw.metrics && typeof raw.metrics === 'object'
      ? raw.metrics : {};
    var node = {
      id: raw.id,
      kind: kind,
      kindLabel: KIND_LABELS[kind],
      scope: raw.scope === 'global' ? 'global' : 'chat',
      chatId: numberOrNull(raw.chat_id),
      title: typeof raw.title === 'string' ? raw.title : '',
      text: typeof raw.text === 'string' ? raw.text : null,
      status: raw.status === null || raw.status === undefined
        ? null : String(raw.status),
      isolated: raw.isolated === true,
      time: normalizeTime(raw.time),
      provenance: raw.provenance && typeof raw.provenance === 'object'
        ? raw.provenance : {},
      metrics: {
        importance: numberOrNull(metrics.importance),
        weight: numberOrNull(metrics.weight),
        degree: numberOrNull(metrics.degree),
      },
      aliases: aliasList(aliasMap, typeof raw.title === 'string'
        ? raw.title : ''),
      degree: 0,
      edges: [],
      search: '',
    };
    node.search = searchBlob(node);
    return node;
  }

  function normalizeEdge(raw, byId) {
    if (!raw || typeof raw !== 'object') return null;
    if (typeof raw.from !== 'string' || typeof raw.to !== 'string') return null;
    if (!byId[raw.from] || !byId[raw.to]) return null; // концы не дорисовываем
    var provenance = raw.provenance && typeof raw.provenance === 'object'
      ? raw.provenance : {};
    return {
      id: typeof raw.id === 'string' && raw.id
        ? raw.id : (raw.from + '|' + raw.relation + '|' + raw.to),
      from: raw.from,
      to: raw.to,
      relation: typeof raw.relation === 'string' ? raw.relation : '',
      derived: raw.derived === true,
      chatId: numberOrNull(raw.chat_id),
      justificationRecorded: raw.justification_recorded === true
        || numberOrNull(provenance.fact_id) !== null,
      provenance: provenance,
    };
  }

  function normalizeShownOf(raw) {
    var source = raw && typeof raw === 'object' ? raw : {};
    var totals = source.totals && typeof source.totals === 'object'
      ? source.totals : {};
    var byKindRaw = source.by_kind && typeof source.by_kind === 'object'
      ? source.by_kind : {};
    var byKind = {};
    for (var kind in byKindRaw) {
      if (!Object.prototype.hasOwnProperty.call(byKindRaw, kind)) continue;
      var entry = byKindRaw[kind] || {};
      byKind[kind] = {
        shown: numberOr(entry.shown, 0),
        total: numberOr(entry.total, 0),
        truncated: entry.truncated === true,
      };
    }
    return {
      nodes: numberOr(source.nodes, 0),
      edges: numberOr(source.edges, 0),
      totals: {
        nodes: numberOr(totals.nodes, 0),
        edges: numberOr(totals.edges, 0),
      },
      unresolvedRefs: numberOr(source.unresolved_refs, 0),
      byKind: byKind,
    };
  }

  function emptyModel() {
    return {
      version: null,
      generatedAt: null,
      state: 'degraded',
      scope: { mode: 'chat', chatId: null },
      degraded: { active: false, notLoaded: [] },
      caps: { nodes: 0, edges: 0, perClass: 0, entityNodes: 0 },
      truncated: { nodes: false, edges: false, byClass: {} },
      shownOf: normalizeShownOf({}),
      nodes: [],
      edges: [],
      byId: {},
      adjacency: {},
      warnings: [],
    };
  }

  /* normalizePayload(payload, {aliases}) -> model
   * Никогда не бросает: битый/частичный ответ даёт пустую модель и warnings.
   */
  function normalizePayload(payload, opts) {
    opts = opts || {};
    var model = emptyModel();
    var source = payload && typeof payload === 'object' ? payload : null;
    if (!source) {
      model.warnings.push('payload_missing');
      return model;
    }
    if (typeof source.version !== 'string' || !source.version) {
      model.warnings.push('version_missing');
    } else {
      model.version = source.version;
      if (ACCEPTED_VERSIONS.indexOf(source.version) < 0) {
        model.warnings.push('version_mismatch');
      }
    }
    model.generatedAt = numberOrNull(source.generated_at);
    if (typeof source.state === 'string' && source.state) {
      model.state = source.state;
    }
    var scope = source.scope && typeof source.scope === 'object'
      ? source.scope : {};
    model.scope = {
      mode: scope.mode === 'global' ? 'global' : 'chat',
      chatId: numberOrNull(scope.chat_id),
    };
    var degraded = source.degraded && typeof source.degraded === 'object'
      ? source.degraded : {};
    // Контракт: `not_loaded` — источники, которые НЕ прочитались (это не то
    // же самое, что «данных нет»); `unavailable` читаем как совместимый алиас.
    var notLoaded = Array.isArray(degraded.not_loaded) ? degraded.not_loaded
      : (Array.isArray(degraded.unavailable) ? degraded.unavailable : []);
    model.degraded = {
      active: degraded.active === true,
      notLoaded: notLoaded.slice(),
    };
    var caps = source.caps && typeof source.caps === 'object' ? source.caps : {};
    model.caps = {
      nodes: numberOr(caps.nodes, 0),
      edges: numberOr(caps.edges, 0),
      perClass: numberOr(caps.per_class, 0),
      entityNodes: numberOr(caps.entity_nodes, 0),
    };
    var truncated = source.truncated && typeof source.truncated === 'object'
      ? source.truncated : {};
    var byClass = truncated.by_class && typeof truncated.by_class === 'object'
      ? truncated.by_class : {};
    model.truncated = {
      nodes: truncated.nodes === true,
      edges: truncated.edges === true,
      byClass: {
        fact: byClass.fact === true,
        belief: byClass.belief === true,
        paradigm: byClass.paradigm === true,
        evolution: byClass.evolution === true,
        entity: byClass.entity === true,
      },
    };
    model.shownOf = normalizeShownOf(source.shown_of);

    var aliasMap = opts.aliases && typeof opts.aliases === 'object'
      ? opts.aliases : null;
    var rawNodes = Array.isArray(source.nodes) ? source.nodes : [];
    var droppedNodes = 0;
    for (var i = 0; i < rawNodes.length; i += 1) {
      var node = normalizeNode(rawNodes[i], aliasMap);
      if (!node) {
        droppedNodes += 1;
        continue;
      }
      if (model.byId[node.id]) {
        // стабильные ключи уникальны; дубль — сигнал битого payload.
        model.warnings.push('duplicate_node');
        continue;
      }
      model.byId[node.id] = node;
      model.nodes.push(node);
    }
    if (droppedNodes) model.warnings.push('node_dropped');

    var rawEdges = Array.isArray(source.edges) ? source.edges : [];
    var seen = {};
    var droppedEdges = 0;
    for (var j = 0; j < rawEdges.length; j += 1) {
      var edge = normalizeEdge(rawEdges[j], model.byId);
      if (!edge || seen[edge.id]) {
        droppedEdges += 1;
        continue;
      }
      seen[edge.id] = true;
      model.edges.push(edge);
    }
    if (droppedEdges) model.warnings.push('edge_dropped');

    // степень/соседство — по ПРИНЯТЫМ рёбрам; isolated пересчитывается,
    // чтобы модель не показывала «связанный» узел без показанной связи.
    for (var k = 0; k < model.edges.length; k += 1) {
      var link = model.edges[k];
      var sourceNode = model.byId[link.from];
      var targetNode = model.byId[link.to];
      sourceNode.degree += 1;
      targetNode.degree += 1;
      sourceNode.edges.push(link.id);
      targetNode.edges.push(link.id);
      if (!model.adjacency[link.from]) model.adjacency[link.from] = [];
      if (!model.adjacency[link.to]) model.adjacency[link.to] = [];
      model.adjacency[link.from].push(link.to);
      model.adjacency[link.to].push(link.from);
    }
    for (var m = 0; m < model.nodes.length; m += 1) {
      if (model.nodes[m].metrics.degree === null) {
        model.nodes[m].metrics.degree = model.nodes[m].degree;
      }
      if (model.nodes[m].degree === 0) model.nodes[m].isolated = true;
      else model.nodes[m].isolated = false;
    }
    return model;
  }

  /* searchNodes(model, query) -> nodes: поиск по названию/алиасу.
   * Все слова запроса должны найтись (подстрока) — прежний паритет графа.
   */
  function searchNodes(model, query) {
    var needle = normalizeQuery(query);
    if (!needle || !model || !Array.isArray(model.nodes)) return [];
    var words = needle.split(' ').filter(Boolean);
    var hits = [];
    for (var i = 0; i < model.nodes.length; i += 1) {
      var node = model.nodes[i];
      var blob = node.search || '';
      var match = true;
      for (var w = 0; w < words.length; w += 1) {
        if (blob.indexOf(words[w]) < 0) {
          match = false;
          break;
        }
      }
      if (!match) continue;
      hits.push({
        node: node,
        prefix: blob.indexOf(needle) === 0 ? 1 : 0,
        length: (node.title || '').length,
      });
    }
    hits.sort(function (a, b) {
      return (b.prefix - a.prefix) || (a.length - b.length)
        || (a.node.id < b.node.id ? -1 : (a.node.id > b.node.id ? 1 : 0));
    });
    return hits.map(function (hit) { return hit.node; });
  }

  function toSet(list) {
    var set = {};
    if (!Array.isArray(list)) return set;
    for (var i = 0; i < list.length; i += 1) set[String(list[i])] = true;
    return set;
  }

  function isEmptySet(set) {
    for (var key in set) {
      if (Object.prototype.hasOwnProperty.call(set, key)) return false;
    }
    return true;
  }

  /* applyFilters(model, filters) -> {nodes, edges, counts}
   * filters: {kinds: [], scopes: [], chats: [], statuses: [], search: '',
   *          hideIsolated, cluster: 'cl:<id>', hideDerived}
   * Пустой список = «все». Чистая функция: никаких запросов и мутаций.
   *
   * `cluster` — тематический кластер (W7-S2): вычисляется по РЕАЛЬНЫМ рёбрам
   * (`computeClusters`), не по совпадению имён и не по близости на экране.
   */
  function applyFilters(model, filters) {
    filters = filters || {};
    if (!model || !Array.isArray(model.nodes)) {
      return { nodes: [], edges: [], counts: { nodes: 0, edges: 0,
        totalNodes: 0, hiddenNodes: 0 } };
    }
    var kinds = toSet(filters.kinds);
    // `scope` — global против chat (системные/глобальные записи не выдают
    // себя за чатовые); `chats: [null]` остаётся совместимым способом.
    var scopes = toSet(filters.scopes);
    var chats = toSet(filters.chats);
    var statuses = toSet(filters.statuses);
    var query = normalizeQuery(filters.search);
    var words = query ? query.split(' ') : [];
    var hideIsolated = filters.hideIsolated === true;
    var hideDerived = filters.hideDerived === true;
    var clusterNodes = null;
    if (typeof filters.cluster === 'string' && filters.cluster) {
      var clusters = computeClusters(model);
      for (var c = 0; c < clusters.length; c += 1) {
        if (clusters[c].id === filters.cluster) {
          clusterNodes = toSet(clusters[c].nodeIds);
          break;
        }
      }
      if (!clusterNodes) clusterNodes = {}; // неизвестный кластер — пустой вид
    }
    var picked = {};
    var nodes = [];
    for (var i = 0; i < model.nodes.length; i += 1) {
      var node = model.nodes[i];
      if (!isEmptySet(kinds) && !kinds[node.kind]) continue;
      if (clusterNodes && !clusterNodes[node.id]) continue;
      if (!isEmptySet(scopes) && !scopes[node.scope]) continue;
      if (!isEmptySet(chats) && !chats[String(node.chatId)]) continue;
      if (!isEmptySet(statuses) && !statuses[String(node.status)]) continue;
      if (hideIsolated && node.isolated) continue;
      if (words.length) {
        var blob = node.search || '';
        var ok = true;
        for (var w = 0; w < words.length; w += 1) {
          if (blob.indexOf(words[w]) < 0) { ok = false; break; }
        }
        if (!ok) continue;
      }
      picked[node.id] = true;
      nodes.push(node);
    }
    var edges = [];
    for (var j = 0; j < model.edges.length; j += 1) {
      var edge = model.edges[j];
      if (hideDerived && edge.derived) continue;
      if (picked[edge.from] && picked[edge.to]) edges.push(edge);
    }
    return {
      nodes: nodes,
      edges: edges,
      counts: {
        nodes: nodes.length,
        edges: edges.length,
        totalNodes: model.nodes.length,
        hiddenNodes: model.nodes.length - nodes.length,
      },
    };
  }

  /* ── кластеры по реальным связям (W7-S2) ─────────────────────────────── */

  /* computeClusters(model) -> [{id, nodeIds, size, kinds, dominantKind,
   *                             label, paradigmTitle}]
   *
   * Кластер = связная компонента по ПРИНЯТЫМ рёбрам. Никакой близости на
   * экране, похожести названий или LLM: только реально записанные отношения.
   * Изолированный узел — кластер из одного узла (это правда, а не ошибка).
   * Детерминизм: корень компоненты = минимальный id, порядок кластеров —
   * размер (по убыванию), затем id; повторный прогон даёт тот же результат.
   */
  function computeClusters(model) {
    var nodes = (model && Array.isArray(model.nodes)) ? model.nodes : [];
    var edges = (model && Array.isArray(model.edges)) ? model.edges : [];
    var parent = {};
    var i;
    for (i = 0; i < nodes.length; i += 1) parent[nodes[i].id] = nodes[i].id;
    function find(x) {
      while (parent[x] !== x) {
        parent[x] = parent[parent[x]];
        x = parent[x];
      }
      return x;
    }
    function union(a, b) {
      var ra = find(a);
      var rb = find(b);
      if (ra === rb) return;
      // Корень — минимальный id: результат не зависит от порядка рёбер.
      if (ra < rb) parent[rb] = ra; else parent[ra] = rb;
    }
    for (i = 0; i < edges.length; i += 1) {
      var edge = edges[i];
      if (!parent[edge.from] || !parent[edge.to]) continue;
      union(edge.from, edge.to);
    }
    var groups = {};
    var order = [];
    for (i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var root = find(node.id);
      if (!groups[root]) {
        groups[root] = { id: 'cl:' + root, root: root, nodeIds: [],
          kinds: {}, size: 0, paradigmTitle: null };
        order.push(root);
      }
      var group = groups[root];
      group.nodeIds.push(node.id);
      group.kinds[node.kind] = (group.kinds[node.kind] || 0) + 1;
      group.size += 1;
      if (node.kind === 'paradigm'
          && (group.paradigmTitle === null
            || node.title.length < group.paradigmTitle.length
            || (node.title.length === group.paradigmTitle.length
              && node.title < group.paradigmTitle))) {
        group.paradigmTitle = node.title;
      }
    }
    order.sort();
    var out = [];
    for (i = 0; i < order.length; i += 1) {
      var item = groups[order[i]];
      var dominantKind = null;
      var best = -1;
      var kindKeys = Object.keys(item.kinds).sort();
      for (var k = 0; k < kindKeys.length; k += 1) {
        var kind = kindKeys[k];
        var count = item.kinds[kind];
        var priority = KIND_PRIORITY[kind] === undefined
          ? KIND_PRIORITY.other : KIND_PRIORITY[kind];
        // Сначала частота, при равенстве — приоритет класса (парадигма выше).
        if (count > best) {
          best = count;
          dominantKind = kind;
        } else if (count === best) {
          var curPriority = KIND_PRIORITY[dominantKind] === undefined
            ? KIND_PRIORITY.other : KIND_PRIORITY[dominantKind];
          if (priority < curPriority) dominantKind = kind;
        }
      }
      item.nodeIds.sort();
      item.dominantKind = dominantKind || 'other';
      item.label = item.paradigmTitle
        ? (KIND_LABELS.paradigm + ': ' + item.paradigmTitle)
        : (KIND_LABELS[item.dominantKind] + ' · ' + item.size);
      out.push({
        id: item.id,
        nodeIds: item.nodeIds,
        size: item.size,
        kinds: item.kinds,
        dominantKind: item.dominantKind,
        paradigmTitle: item.paradigmTitle,
        label: item.label,
      });
    }
    out.sort(function (a, b) {
      return (b.size - a.size)
        || (a.id < b.id ? -1 : (a.id > b.id ? 1 : 0));
    });
    return out;
  }


  /* ── камера ──────────────────────────────────────────────────────────── */

  function createCamera() {
    return { x: 0, y: 0, scale: 1 };
  }

  function clampCamera(camera, opts) {
    opts = opts || {};
    var source = camera && typeof camera === 'object' ? camera : {};
    var minScale = numberOr(opts.minScale, DEFAULTS.minScale);
    var maxScale = numberOr(opts.maxScale, DEFAULTS.maxScale);
    var scale = numberOr(source.scale, 1);
    if (scale < minScale) scale = minScale;
    if (scale > maxScale) scale = maxScale;
    return {
      x: numberOr(source.x, 0),
      y: numberOr(source.y, 0),
      scale: scale,
    };
  }

  // vis-network отдаёт {position:{x,y}, scale}; храним плоскую камеру, чтобы
  // её можно было сохранить/восстановить без объекта рендерера (§2.8).
  function cameraFromNetwork(position, scale) {
    var pos = position && typeof position === 'object' ? position : {};
    return clampCamera({ x: pos.x, y: pos.y, scale: scale });
  }

  function cameraToNetwork(camera) {
    var cam = clampCamera(camera);
    return { position: { x: cam.x, y: cam.y }, scale: cam.scale };
  }

  function cameraEquals(left, right, epsilon) {
    var eps = numberOr(epsilon, 1e-6);
    var a = clampCamera(left);
    var b = clampCamera(right);
    return Math.abs(a.x - b.x) <= eps && Math.abs(a.y - b.y) <= eps
      && Math.abs(a.scale - b.scale) <= eps;
  }

  /* ── подписи (screen-space, LOD, детерминизм) ────────────────────────── */

  function labelText(item, limit) {
    var text = typeof item.title === 'string' ? item.title
      : (typeof item.label === 'string' ? item.label : '');
    text = text.replace(/\s+/g, ' ').trim();
    if (text.length <= limit) return text;
    return text.slice(0, limit - 1).replace(/\s+$/, '') + '…';
  }

  function measureLabel(text, fontSize, charWidth) {
    return Math.max(fontSize, text.length * fontSize * charWidth) + 6;
  }

  function boxesOverlap(a, b, padding) {
    var pad = numberOr(padding, 0);
    return Math.abs(a.x - b.x) * 2 < (a.width + b.width + pad * 2)
      && Math.abs(a.y - b.y) * 2 < (a.height + b.height + pad * 2);
  }

  function labelPriority(item) {
    var weight = KIND_PRIORITY[item.kind];
    return {
      selected: item.selected === true ? 0 : 1,
      kind: weight === undefined ? KIND_PRIORITY.other : weight,
      degree: -numberOr(item.degree, 0),
      length: (typeof item.title === 'string' ? item.title : '').length,
      id: typeof item.id === 'string' ? item.id : String(item.id || ''),
    };
  }

  function comparePriority(a, b) {
    var pa = labelPriority(a);
    var pb = labelPriority(b);
    if (pa.selected !== pb.selected) return pa.selected - pb.selected;
    if (pa.kind !== pb.kind) return pa.kind - pb.kind;
    if (pa.degree !== pb.degree) return pa.degree - pb.degree;
    if (pa.length !== pb.length) return pa.length - pb.length;
    return pa.id < pb.id ? -1 : (pa.id > pb.id ? 1 : 0);
  }

  /* allocateLabels(items, opts) -> {labels, hidden, shown, lod, maxLabels}
   * items: [{id, x, y, kind, title, degree, selected}]
   * opts: {scale, viewport:{width,height}, mobile, maxLabels, fontSize,
   *        padding, maxLabelChars}
   *
   * Детерминированно: порядок задан приоритетом, координаты входа не
   * сортируются случайно, Math.random/Date не используются. Массовое
   * наложение названий невозможно: бокс ставится только если не пересекается
   * с уже поставленными и целиком попадает во вьюпорт (§2.4 контракта).
   */
  /* labelBudget(items, cfg, opts) -> {budget, raw, boxArea, cap, fill, limit,
   *                                   mandatory, lod}
   *
   * Решение Architect §9.2: бюджет подписей выводится из ГЕОМЕТРИИ кадра, а не
   * из LOD-константы:
   *   budget = clamp(round(fill * W * H / boxArea), 4, cap)
   * где boxArea — средняя по кандидатам подпись через `measureLabel()`
   * (ширина `chars * 0.55 * fontSize`, высота `fontSize + padding`),
   * fill = 0.05 desktop / 0.04 mobile, cap = 26/12 — ЖЁСТКИЕ потолки
   * (`DEFAULTS.maxLabels`/`mobileMaxLabels` не меняются).
   * LOD — доля бюджета: overview = min(budget, 6), normal = min(budget, 16),
   * detail = budget. Выбранный узел и парадигмы подписываются всегда, поэтому
   * бюджет не может быть меньше их числа (но не выше cap).
   */
  function labelBudget(items, cfg, opts) {
    opts = opts || {};
    var mobile = opts.mobile === true;
    var cap = mobile
      ? Math.min(numberOr(cfg.maxLabels, DEFAULTS.maxLabels),
        DEFAULTS.mobileMaxLabels)
      : numberOr(cfg.maxLabels, DEFAULTS.maxLabels);
    var fontSize = numberOr(cfg.fontSize, DEFAULTS.fontSize);
    var charWidth = numberOr(cfg.charWidth, DEFAULTS.charWidth);
    var padding = numberOr(cfg.padding, DEFAULTS.padding);
    var maxChars = numberOr(cfg.maxLabelChars, DEFAULTS.maxLabelChars);
    var source = Array.isArray(items) ? items : [];
    var totalChars = 0;
    var counted = 0;
    var mandatory = 0;
    for (var i = 0; i < source.length; i += 1) {
      var item = source[i];
      if (!item || typeof item.id !== 'string') continue;
      if (numberOrNull(item.x) === null || numberOrNull(item.y) === null) continue;
      var text = labelText(item, maxChars);
      if (text) {
        totalChars += text.length;
        counted += 1;
      }
      if (item.selected === true || item.kind === 'paradigm') mandatory += 1;
    }
    var fill = mobile ? 0.04 : 0.05;
    var viewport = opts.viewport && typeof opts.viewport === 'object'
      ? opts.viewport : null;
    var width = viewport ? numberOr(viewport.width, 0) : 0;
    var height = viewport ? numberOr(viewport.height, 0) : 0;
    var boxArea = 0;
    var raw = 0;
    var budget;
    if (width > 0 && height > 0 && counted > 0) {
      var avgChars = totalChars / counted;
      var boxW = Math.max(fontSize, avgChars * fontSize * charWidth) + 6;
      var boxH = fontSize + padding;
      boxArea = Math.max(1, boxW * boxH);
      raw = Math.round((fill * width * height) / boxArea);
      budget = Math.min(cap, Math.max(4, raw));
    } else {
      // Без вьюпорта/кандидатов геометрии нет — остаётся только потолок.
      budget = Math.min(cap, 4);
    }
    if (mandatory) budget = Math.min(cap, Math.max(budget, mandatory));
    var scale = numberOr(opts.scale, 1);
    var overviewScale = numberOr(cfg.overviewScale, DEFAULTS.overviewScale);
    var detailScale = numberOr(cfg.detailScale, DEFAULTS.detailScale);
    var lod = scale < overviewScale ? 'overview'
      : (scale >= detailScale ? 'detail' : 'normal');
    var limit = lod === 'overview' ? Math.min(budget, 6)
      : (lod === 'normal' ? Math.min(budget, 16) : budget);
    return {
      budget: budget, raw: raw, boxArea: boxArea, cap: cap, fill: fill,
      limit: limit, mandatory: mandatory, lod: lod, counted: counted,
    };
  }

  /* allocateLabels(items, opts) -> {labels, hidden, shown, lod, maxLabels}
   * items: [{id, x, y, kind, title, degree, selected}]
   * opts: {scale, viewport:{width,height}, mobile, maxLabels, fontSize,
   *        padding, maxLabelChars}
   *
   * Детерминированно: порядок задан приоритетом, координаты входа не
   * сортируются случайно, Math.random/Date не используются. Массовое
   * наложение названий невозможно: бокс ставится только если не пересекается
   * с уже поставленными и целиком попадает во вьюпорт (§2.4 контракта).
   * Бюджет подписей — `labelBudget` (§9.2), LOD только ограничивает его долю.
   */
  function allocateLabels(items, opts) {
    opts = opts || {};
    var cfg = {
      maxLabels: numberOr(opts.maxLabels, DEFAULTS.maxLabels),
      fontSize: numberOr(opts.fontSize, DEFAULTS.fontSize),
      padding: numberOr(opts.padding, DEFAULTS.padding),
      maxLabelChars: numberOr(opts.maxLabelChars, DEFAULTS.maxLabelChars),
      charWidth: numberOr(opts.charWidth, DEFAULTS.charWidth),
      overviewScale: numberOr(opts.overviewScale, DEFAULTS.overviewScale),
      detailScale: numberOr(opts.detailScale, DEFAULTS.detailScale),
    };
    var scale = numberOr(opts.scale, 1);
    if (opts.mobile === true) {
      cfg.maxLabels = Math.min(cfg.maxLabels, DEFAULTS.mobileMaxLabels);
    }

    var viewport = opts.viewport && typeof opts.viewport === 'object'
      ? opts.viewport : null;
    var placeable = [];
    var source = Array.isArray(items) ? items : [];
    for (var i = 0; i < source.length; i += 1) {
      var item = source[i];
      if (!item || typeof item.id !== 'string') continue;
      var x = numberOrNull(item.x);
      var y = numberOrNull(item.y);
      if (x === null || y === null) continue;
      placeable.push({
        id: item.id, x: x, y: y, kind: item.kind,
        title: item.title, degree: item.degree,
        selected: item.selected === true,
      });
    }
    placeable.sort(comparePriority);

    var plan = labelBudget(placeable, cfg, {
      mobile: opts.mobile === true, viewport: viewport, scale: scale,
    });
    var lod = plan.lod;
    var budget = plan.limit;

    var placed = [];
    var labels = [];
    for (var p = 0; p < placeable.length; p += 1) {
      if (labels.length >= budget) break;
      var candidate = placeable[p];
      var text = labelText(candidate, cfg.maxLabelChars);
      if (!text) continue;
      var box = {
        id: candidate.id,
        x: candidate.x,
        y: candidate.y,
        width: measureLabel(text, cfg.fontSize, cfg.charWidth),
        height: cfg.fontSize * 1.4,
        text: text,
      };
      if (viewport) {
        // Подпись должна целиком лежать в кадре с отступом: у сцены скруглённые
        // края/рамка, и бокс, прижатый к самой кромке, визуально обрезается.
        var inset = numberOr(opts.edgeInset, cfg.padding);
        var halfW = box.width / 2;
        var halfH = box.height / 2;
        if (box.x - halfW < inset || box.y - halfH < inset
          || box.x + halfW > numberOr(viewport.width, 0) - inset
          || box.y + halfH > numberOr(viewport.height, 0) - inset) {
          continue;                       // за пределами сцены — не рисуем
        }
      }
      var collides = false;
      for (var q = 0; q < placed.length; q += 1) {
        if (boxesOverlap(box, placed[q], cfg.padding)) {
          collides = true;
          break;
        }
      }
      if (collides) continue;
      placed.push(box);
      labels.push({
        id: box.id, x: box.x, y: box.y, text: box.text,
        width: box.width, height: box.height,
        priority: labelPriority(candidate),
      });
    }
    return {
      labels: labels,
      hidden: placeable.length - labels.length,
      shown: labels.length,
      lod: lod,
      maxLabels: budget,
      // Диагностика §9.2 (приёмка в node-тесте): бюджет/потолок/заливка/
      // площадь бокса и число обязательных подписей.
      budget: plan.budget,
      cap: plan.cap,
      fill: plan.fill,
      boxArea: plan.boxArea,
      mandatory: plan.mandatory,
      scale: scale,
    };
  }

  function kindSummary(model) {
    var out = [];
    for (var i = 0; i < KINDS.length; i += 1) {
      var kind = KINDS[i];
      var shown = numberOr((model.shownOf.byKind[kind] || {}).shown, 0);
      var total = numberOr((model.shownOf.byKind[kind] || {}).total, 0);
      if (!shown && !total) continue;
      out.push({
        kind: kind,
        label: KIND_LABELS[kind],
        shown: shown,
        total: total,
        truncated: (model.shownOf.byKind[kind] || {}).truncated === true,
      });
    }
    return out;
  }

  /* nodeStyle(kind) -> {color, shape, size, legend} — детерминированно. */
  function nodeStyle(kind) {
    return KIND_STYLE[KINDS.indexOf(kind) >= 0 ? kind : 'other']
      || KIND_STYLE.other;
  }

  /* legendEntries(model) -> [{kind, label, color, shape, required}]
   *
   * Обязательные четыре строки — дословно слова владельца (ТЗ 1285):
   * «Факты», «Убеждения», «Парадигмы», «Изменения». Показываются ВСЕГДА
   * (легенда объясняет визуальную систему, а не только текущий кадр).
   * «Сущности»/«Наблюдения» — вторичный контекст: строка появляется только
   * если такие узлы реально есть в модели, и не подменяет четыре обязательных.
   */
  function legendEntries(model) {
    var out = [];
    var i;
    for (i = 0; i < LEGEND_ORDER.length; i += 1) {
      var kind = LEGEND_ORDER[i];
      var style = KIND_STYLE[kind];
      out.push({
        kind: kind,
        label: KIND_LABELS[kind],
        color: style.color,
        shape: style.shape,
        required: true,
      });
    }
    var present = {};
    var nodes = (model && Array.isArray(model.nodes)) ? model.nodes : [];
    for (i = 0; i < nodes.length; i += 1) present[nodes[i].kind] = true;
    for (i = 0; i < LEGEND_EXTRA.length; i += 1) {
      var extra = LEGEND_EXTRA[i];
      if (!present[extra]) continue;
      out.push({
        kind: extra,
        label: KIND_LABELS[extra],
        color: KIND_STYLE[extra].color,
        shape: KIND_STYLE[extra].shape,
        required: false,
      });
    }
    return out;
  }

  /* completeness(shownOf) -> {active, nodes:{shown,total}, edges:{...},
   *                            text}
   *
   * ОДНО правило на узлы и рёбра: «показано X из Y» включается ТОЛЬКО когда
   * `total > shown` (по S1-правке B1 таков любой реальный чат: снапшот берёт
   * окрестность сидов). Это честная неполнота, а НЕ ошибка: текст нейтрален,
   * никаких причин/статусов здесь нет. Полнота не обещается никогда, когда
   * показана часть.
   */
  function completeness(shownOf) {
    var src = shownOf && typeof shownOf === 'object' ? shownOf : {};
    var nodes = numberOr(src.nodes, 0);
    var edges = numberOr(src.edges, 0);
    var totals = src.totals && typeof src.totals === 'object' ? src.totals : {};
    var totalNodes = numberOr(totals.nodes, nodes);
    var totalEdges = numberOr(totals.edges, edges);
    var nodesShort = totalNodes > nodes;
    var edgesShort = totalEdges > edges;
    var parts = [];
    if (nodesShort) parts.push(nodes + ' из ' + totalNodes + ' узлов');
    if (edgesShort) parts.push(edges + ' из ' + totalEdges + ' связей');
    return {
      active: nodesShort || edgesShort,
      nodes: { shown: nodes, total: totalNodes, truncated: nodesShort },
      edges: { shown: edges, total: totalEdges, truncated: edgesShort },
      // Одна нейтральная строка: «показано X из Y». Никаких оценок и
      // предупреждений — это честная неполнота окрестности.
      text: parts.length ? ('показано ' + parts.join(' · ')) : '',
    };
  }

  /* mapClientState({model, renderer, failed, now, staleMs, visibleNodes})
   *        -> {state, notice, serverState, note, stale, empty, degraded}
   *
   * Разделение осей (контракт §4, §7.2) СОХРАНЕНО: `state` — факт о рендерере
   * (loading/not_loaded/stale/renderer_failed/ready + `empty`, когда данных
   * действительно нет). Серверные факты (`degraded`) в `state` не подмешиваются.
   *
   * Решение Architect §9.1: ВИДИМАЯ строка статуса одна и складывается по
   * «худшему факту»: `renderer_failed` → `loading`/`not_loaded` → `degraded` →
   * `empty` → `stale` → `ready`. Она отдаётся ОТДЕЛЬНЫМ полем `notice` (не
   * заменой `state`), чтобы отказ источника не прятался за «всё хорошо» и
   * чтобы «пусто» не объявлялось при `degraded.active === true` (отказавший
   * источник не имеет права выглядеть пустотой).
   *
   * `now` передаётся ВХОДОМ (чистая функция). `partial` — не состояние UI:
   * полноту показывает `completeness()` нейтральной строкой.
   */
  function mapClientState(opts) {
    opts = opts || {};
    var model = opts.model || null;
    var renderer = opts.renderer || 'ready';    // ready | missing | failed
    var staleMs = numberOr(opts.staleMs, DEFAULTS.staleMs);
    var serverState = model && typeof model.state === 'string'
      ? model.state : null;
    var nodeCount = model && Array.isArray(model.nodes) ? model.nodes.length : 0;
    var visibleNodes = numberOr(opts.visibleNodes, nodeCount);
    var generatedAt = model ? numberOrNull(model.generatedAt) : null;
    var now = numberOrNull(opts.now);
    var degradedActive = !!(model && model.degraded
      && model.degraded.active === true);
    var notLoaded = (model && model.degraded
      && Array.isArray(model.degraded.notLoaded))
      ? model.degraded.notLoaded.slice() : [];
    var stale = false;
    if (generatedAt !== null && now !== null && staleMs > 0) {
      stale = (now - generatedAt * 1000) > staleMs;
    }
    // «Пусто» — факт об ОТСУТСТВИИ ДАННЫХ. Пока источник отказал, пустоту
    // объявлять нельзя (§9.1): возможно, данные просто не прочитались.
    var dataEmpty = degradedActive ? false
      : (serverState === 'empty' || nodeCount === 0);
    // Пустая ВИТРИНА (фильтр скрыл всё) — факт вида, а не данных: «нет фактов
    // и связей» здесь было бы ложью, пользователю нужен сброс фильтра.
    var viewEmpty = !dataEmpty && visibleNodes === 0 && nodeCount > 0;
    var failed = opts.failed === true || renderer === 'failed';

    // Ось рендерера — без серверных фактов.
    var state;
    if (failed) state = 'renderer_failed';
    else if (renderer === 'missing') state = 'not_loaded';
    else if (!model) state = 'loading';
    else if (dataEmpty) state = 'empty';
    else if (stale) state = 'stale';
    else state = 'ready';

    // Видимая строка — «худший факт» (§9.1), включая отказ источника.
    var noticeKind;
    if (failed) noticeKind = 'renderer_failed';
    else if (renderer === 'missing') noticeKind = 'not_loaded';
    else if (!model) noticeKind = 'loading';
    else if (degradedActive) noticeKind = 'degraded';
    else if (dataEmpty) noticeKind = 'empty';
    else if (stale) noticeKind = 'stale';
    else noticeKind = 'ready';

    var noticeText;
    if (noticeKind === 'degraded') {
      noticeText = notLoaded.length
        ? 'часть источников не прочитана: ' + notLoaded.join(', ')
        : 'часть источников не прочитана';
    } else {
      noticeText = STATE_LABELS[noticeKind] || '';
    }
    return {
      state: state,
      notice: {
        kind: noticeKind,
        text: noticeText,
        sources: notLoaded,
        degraded: noticeKind === 'degraded',
      },
      serverState: serverState,
      note: STATE_LABELS[state] || '',
      noticeText: noticeText,
      stale: stale,
      empty: state === 'empty',
      viewEmpty: viewEmpty,
      degraded: degradedActive,
      generatedAt: generatedAt,
    };
  }

  return {
    VERSION: VERSION,
    ACCEPTED_VERSIONS: ACCEPTED_VERSIONS.slice(),
    KINDS: KINDS.slice(),
    KIND_LABELS: KIND_LABELS,
    KIND_STYLE: KIND_STYLE,
    LEGEND_ORDER: LEGEND_ORDER.slice(),
    STATE_LABELS: STATE_LABELS,
    DEFAULTS: DEFAULTS,
    normalizeQuery: normalizeQuery,
    normalizePayload: normalizePayload,
    normalizeShownOf: normalizeShownOf,
    searchNodes: searchNodes,
    applyFilters: applyFilters,
    computeClusters: computeClusters,
    kindSummary: kindSummary,
    nodeStyle: nodeStyle,
    legendEntries: legendEntries,
    completeness: completeness,
    mapClientState: mapClientState,
    createCamera: createCamera,
    clampCamera: clampCamera,
    cameraFromNetwork: cameraFromNetwork,
    cameraToNetwork: cameraToNetwork,
    cameraEquals: cameraEquals,
    labelText: labelText,
    measureLabel: measureLabel,
    boxesOverlap: boxesOverlap,
    labelPriority: labelPriority,
    labelBudget: labelBudget,
    allocateLabels: allocateLabels,
  };
});
