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
    // §4.2 контракта: пороги LOD заданы ОТНОСИТЕЛЬНО обзора (r = scale/fit):
    // T1 = 0.85 (L0↔L1), T2 = 1.80 (L1↔L2), полоса гистерезиса δ = 0.12.
    overviewScale: 0.85,
    detailScale: 1.8,
    lod: {
      t1: 0.85,
      t2: 1.8,
      delta: 0.12,
      // §5.2 спеки: уровень 0 — «r < ~0.85, С КОРРЕКТИРОВКОЙ ПО ПЛОТНОСТИ».
      // Плотный кадр (702 узла в короткой широкой сцене) при r ≈ 1 физически
      // является обзором: ядер больше, чем различимых мест. Порог задан
      // числом ВИДИМЫХ узлов на 100 000 CSS-px², выход — на 20 % ниже
      // (свой гистерезис, чтобы плотность не мигала на границе).
      denseNodes: 240,       // мелкий набор всегда читаем поштучно
      densePer100k: 60,      // вход в обзор по плотности
      denseExitRatio: 0.8,   // выход из него (48/100k)
      // Плотностная поправка действует только в кадре ОБЗОРА (r ≈ 1): как
      // только пользователь приблизился, уровень определяется масштабом.
      // Иначе при движении внутрь плотного кольца уровень возвращался бы в 0.
      denseMaxRatio: 1.05,
      // §5.2 L0: кроме центров групп видны ключевые одиночные узлы.
      topKCap: 40,           // K = min(40, ⌈nodes/12⌉)
      topKDiv: 12,
    },
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
  /* CMV-C: палитра/формы — ровно спека §4.1 (таблица типов), те же hex, что
   * рисует сцена (`CogVisual.CONFIG.spec`) и что подписаны в CSS-легенде
   * (`.cog-legend__swatch--*`). Раньше здесь был другой набор оттенков, и
   * легенда обещала цвета, которых на канвасе не было. `box` у сущностей
   * запрещён спекой (крупные серые прямоугольники): сфера = `sphere` + декор
   * ядра в слое `fx`. Размеры совпадают с `CONFIG.baseDiameter` (`cog-visual`). */
  var KIND_STYLE = {
    fact: { color: '#32C8F3', shape: 'dot', size: 14, legend: true },
    belief: { color: '#A77BFF', shape: 'dotRing', size: 18, legend: true },
    paradigm: { color: '#728CFF', shape: 'hexagon', size: 22, legend: true },
    evolution_event: { color: '#FFB84D', shape: 'diamond', size: 13,
      legend: true },
    observation: { color: '#D97706', shape: 'diamondDim', size: 10,
      legend: false },
    entity: { color: '#9FB4CE', shape: 'sphere', size: 11, legend: false },
    other: { color: '#64748B', shape: 'dotNeutral', size: 9, legend: false },
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

  /* ── карточка (W7-S3): раздельные времена и названия связи ─────────────
   * Пять полей времени в payload РАЗНЫЕ по смыслу (§2.5 ТЗ: «дату создания/
   * обнаружения/последней модификации, каждая с корректным названием»).
   * Подписи фиксированы здесь, чтобы карточка не называла «время сохранения»
   * «датой события». */
  var TIME_FIELDS = [
    { key: 'occurredAt', label: 'Когда произошло' },
    { key: 'observedAt', label: 'Когда обнаружено' },
    { key: 'savedAt', label: 'Когда сохранено' },
    { key: 'confirmedAt', label: 'Когда подтверждено' },
    { key: 'updatedAt', label: 'Когда обновлено' },
  ];

  /* Русские названия ТОЛЬКО для машинных типов рёбер, которые формирует
   * сервер (`derived_from`/`revised_by`); остальные `relation_type` — реальные
   * строки из БД и не «переводятся» догадками. */
  var RELATION_LABELS = {
    derived_from: 'выведено из',
    revised_by: 'заменено версией',
  };

  /* Тип каталога «Памяти» для перехода из карточки (существующие типы
   * `memoryCatalogTypes`, нового маршрута не заводится). */
  var MEMORY_TYPE = { fact: 'facts', belief: 'context', paradigm: 'context' };

  function numberOrNull(value) {
    if (value === null || value === undefined || value === '') return null;
    var n = Number(value);
    return isFinite(n) ? n : null;
  }

  function numberOr(value, fallback) {
    var n = numberOrNull(value);
    return n === null ? fallback : n;
  }

  // Ограничение числа отрезком; пустой/инвертированный отрезок отдаёт `value`
  // (узкий кадр не должен превращаться в NaN).
  function clampNumber(value, lo, hi) {
    var v = numberOr(value, 0);
    var min = numberOr(lo, v);
    var max = numberOr(hi, v);
    if (!(max >= min)) return v;
    return Math.min(Math.max(v, min), max);
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

  var GROUP_NEUTRAL_LABEL = 'Группа';

  /* ── агрегаты уровня 0 (CMV-C): центры реальных групп ─────────────────── */

  /* buildAggregates(opts) -> {groups, flows, total, grouped, singles}
   *
   * §5.2 спеки (уровень 0): «на экране видны светящиеся центры настоящих
   * групп/агрегатов и ключевые отдельные узлы», «любой агрегат маркируется как
   * визуальное объединение с РЕАЛЬНЫМ количеством исходных элементов», «двойной
   * клик по группе переводит к её реальным участникам», §12.1 — «с первого
   * взгляда видно несколько пространственно отделённых групп/центров».
   *
   * Что здесь считается:
   *   * область, занятая узлами витрины, делится на тайлы (~`tileCss` CSS-px при
   *     обзоре, в СЕТЕВЫХ координатах, поэтому панорамирование и зум не меняют
   *     группировку). Тайл — визуальный «район» карты, а не семантическое
   *     сообщество: имя темы не выдумывается;
   *   * в группу попадают РЕАЛЬНЫЕ узлы: `memberIds` (отсортированы), `apexId`
   *     (самый связный реальный узел — якорь фокуса), `count`;
   *   * сумма `count` по группам равна числу размещённых узлов — агрегаты не
   *     теряют и не добавляют элементы;
   *   * `componentCount` показывает, сколько НАСТОЯЩИХ компонент (`computeClusters`
   *     по принятым рёбрам) попало в район — честная метрика вместо догадки;
   *   * подпись: реальный тип, если район однороден (≥80 %), реальное название
   *     парадигмы, если она доминирует, иначе нейтральное «Группа»;
   *   * `flows` — РЕАЛЬНЫЕ рёбра между разными районами (число связей, не оценка).
   *
   * opts: {nodes, edges, positions, fitScale, camera, viewport, tileCss, maxCols,
   *        maxRows, minMembers, maxGroups, radius, hideFrom, centerGap,
   *        centerPasses, centerMaxShift}
   * Чистая функция: порядок задаётся сортировкой, состояние модуля не читается,
   * Math.random/Date не используются.
   */
  function buildAggregates(opts) {
    opts = opts || {};
    var nodes = Array.isArray(opts.nodes) ? opts.nodes : [];
    var edges = Array.isArray(opts.edges) ? opts.edges : [];
    var positions = (opts.positions && typeof opts.positions === 'object')
      ? opts.positions : {};
    var fitScale = numberOr(opts.fitScale, 0);
    var tileCss = numberOr(opts.tileCss, 220);
    var maxCols = numberOr(opts.maxCols, 6);
    var maxRows = numberOr(opts.maxRows, 4);
    var minMembers = numberOr(opts.minMembers, 6);
    var maxGroups = numberOr(opts.maxGroups, 24);
    var hideFrom = numberOr(opts.hideFrom, 8);
    var rCfg = opts.radius || {};
    var camera = opts.camera || { x: 0, y: 0, scale: 1 };
    var viewport = opts.viewport || { width: 0, height: 0 };
    var camScale = numberOr(camera.scale, 1);
    if (!(camScale > 0)) camScale = 1;
    var width = numberOr(viewport.width, 0);
    var height = numberOr(viewport.height, 0);
    var empty = { groups: [], flows: [], total: 0, grouped: 0, singles: 0 };
    if (!nodes.length) return empty;

    // Позиции — единственный геометрический вход. Узел без позиции не
    // агрегируется (его и не видно): честный пропуск, а не «центр в нуле».
    var placed = [];
    var byId = {};
    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    var i;
    for (i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (!node || node.id === undefined) continue;
      var p = positions[String(node.id)];
      if (!p || numberOrNull(p.x) === null || numberOrNull(p.y) === null) continue;
      var rec = {
        id: String(node.id), kind: node.kind || 'other',
        title: typeof node.title === 'string' ? node.title : '',
        degree: numberOr(node.degree, 0), x: p.x, y: p.y,
      };
      placed.push(rec);
      byId[rec.id] = rec;
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }
    if (!placed.length) return empty;
    // Компоненты по РЕАЛЬНЫМ рёбрам — метрика честности района, не его границы.
    var comps = computeClusters({
      nodes: placed.map(function (n) {
        return { id: n.id, kind: n.kind, title: n.title };
      }),
      edges: edges,
    });
    var compOf = {};
    for (i = 0; i < comps.length; i += 1) {
      var comp = comps[i];
      for (var c = 0; c < comp.nodeIds.length; c += 1) {
        compOf[comp.nodeIds[c]] = comp.id;
      }
    }

    // Тайлинг занятой площади в сетевых координатах (стабилен при движении
    // камеры). Число тайлов — по размеру области при обзоре, с потолками.
    var spanX = Math.max(0, maxX - minX);
    var spanY = Math.max(0, maxY - minY);
    var tileNet = (fitScale > 0) ? (tileCss / fitScale) : tileCss;
    if (!(tileNet > 0)) tileNet = 1;
    var cols = Math.ceil(spanX / tileNet);
    var rows = Math.ceil(spanY / tileNet);
    if (!(cols >= 1)) cols = 1;
    if (!(rows >= 1)) rows = 1;
    cols = Math.min(Math.max(cols, 1), Math.max(1, maxCols));
    rows = Math.min(Math.max(rows, 1), Math.max(1, maxRows));
    var tileW = spanX > 0 ? spanX / cols : 1;
    var tileH = spanY > 0 ? spanY / rows : 1;

    var buckets = {};
    var bucketKeys = [];
    for (i = 0; i < placed.length; i += 1) {
      var item = placed[i];
      var gx = Math.min(cols - 1, Math.floor((item.x - minX) / tileW));
      var gy = Math.min(rows - 1, Math.floor((item.y - minY) / tileH));
      if (gx < 0) gx = 0;
      if (gy < 0) gy = 0;
      var key = gy + ':' + gx;
      var bucket = buckets[key];
      if (!bucket) {
        bucket = buckets[key] = { key: key, nodeIds: [],
          sx: 0, sy: 0, count: 0 };
        bucketKeys.push(key);
      }
      bucket.nodeIds.push(item.id);
      bucket.sx += item.x;
      bucket.sy += item.y;
      bucket.count += 1;
    }
    var merged = [];
    var small = [];
    for (i = 0; i < bucketKeys.length; i += 1) {
      var b = buckets[bucketKeys[i]];
      b.cx = b.sx / b.count;
      b.cy = b.sy / b.count;
      b.nodeIds.sort();
      if (b.count >= minMembers) merged.push(b);
      else small.push(b);
    }
    function distTo(g2, x, y) {
      var dx = g2.cx - x;
      var dy = g2.cy - y;
      return Math.sqrt(dx * dx + dy * dy);
    }
    // Редкие районы приклеиваются к ближайшему: одиночный центр с подписью на
    // один узел ничего не добавляет к обзору (сам узел и так виден).
    for (i = 0; i < small.length; i += 1) {
      var s2 = small[i];
      var host = null;
      var hostDist = Infinity;
      for (var m = 0; m < merged.length; m += 1) {
        var ds = distTo(merged[m], s2.cx, s2.cy);
        if (ds < hostDist) { hostDist = ds; host = merged[m]; }
      }
      if (host) {
        host.nodeIds = host.nodeIds.concat(s2.nodeIds);
        host.nodeIds.sort();
        host.count += s2.count;
        host.sx += s2.sx;
        host.sy += s2.sy;
        host.cx = host.sx / host.count;
        host.cy = host.sy / host.count;
      } else {
        merged.push(s2);
      }
    }
    // Потолок числа районов: лишние (самые мелкие) вливаются в ближайший.
    merged.sort(function (a, b3) {
      return (b3.count - a.count)
        || (a.key < b3.key ? -1 : (a.key > b3.key ? 1 : 0));
    });
    if (merged.length > maxGroups) {
      var kept = merged.slice(0, maxGroups);
      for (i = maxGroups; i < merged.length; i += 1) {
        var extra = merged[i];
        var near = null;
        var nearDist = Infinity;
        for (var q = 0; q < kept.length; q += 1) {
          var dd = distTo(kept[q], extra.cx, extra.cy);
          if (dd < nearDist) { nearDist = dd; near = kept[q]; }
        }
        near.nodeIds = near.nodeIds.concat(extra.nodeIds);
        near.nodeIds.sort();
        near.count += extra.count;
        near.sx += extra.sx;
        near.sy += extra.sy;
        near.cx = near.sx / near.count;
        near.cy = near.sy / near.count;
      }
      merged = kept;
    }

    var groups = [];
    var grouped = 0;
    var radiusBase = numberOr(rCfg.base, 10);
    var radiusLog = numberOr(rCfg.perLog2, 3.4);
    var radiusMin = numberOr(rCfg.min, 12);
    var radiusMax = numberOr(rCfg.max, 46);
    for (i = 0; i < merged.length; i += 1) {
      var grp = merged[i];
      var kinds = {};
      var apex = null;
      var titleCounts = {};
      var groupComps = {};
      for (var n = 0; n < grp.nodeIds.length; n += 1) {
        var rec2 = byId[grp.nodeIds[n]];
        if (!rec2) continue;
        kinds[rec2.kind] = (kinds[rec2.kind] || 0) + 1;
        groupComps[compOf[rec2.id] || '-'] = true;
        if (!apex || rec2.degree > apex.degree
            || (rec2.degree === apex.degree && rec2.id < apex.id)) {
          apex = rec2;
        }
        // §5.2/§13: тема района — самая ЧАСТАЯ реальная парадигма, а не первая
        // по алфавиту. Алфавитный выбор называл район произвольным заголовком:
        // при трёх парадигмах без доминанты подпись выдавала одну из них за
        // тему всего района.
        if (rec2.kind === 'paradigm' && rec2.title) {
          titleCounts[rec2.title] = (titleCounts[rec2.title] || 0) + 1;
        }
      }
      var paradigmTitle = null;
      var paradigmCount = 0;
      var titleKeys = Object.keys(titleCounts).sort();
      for (var tk = 0; tk < titleKeys.length; tk += 1) {
        if (titleCounts[titleKeys[tk]] > paradigmCount) {
          paradigmTitle = titleKeys[tk];
          paradigmCount = titleCounts[titleKeys[tk]];
        }
      }
      var paradigmShare = grp.count > 0 ? paradigmCount / grp.count : 0;
      var dominantKind = null;
      var bestCount = -1;
      var kindKeys = Object.keys(kinds).sort();
      for (var kk = 0; kk < kindKeys.length; kk += 1) {
        var kd = kindKeys[kk];
        var cnt = kinds[kd];
        var prio = KIND_PRIORITY[kd] === undefined
          ? KIND_PRIORITY.other : KIND_PRIORITY[kd];
        if (cnt > bestCount) {
          bestCount = cnt;
          dominantKind = kd;
        } else if (cnt === bestCount) {
          var cur = KIND_PRIORITY[dominantKind] === undefined
            ? KIND_PRIORITY.other : KIND_PRIORITY[dominantKind];
          if (prio < cur) dominantKind = kd;
        }
      }
      dominantKind = dominantKind || 'other';
      var dominantShare = grp.count > 0
        ? (kinds[dominantKind] || 0) / grp.count : 0;
      // §5.2 спеки: название — только там, где оно РЕАЛЬНО известно и реально
      // доминирует (однородный состав, тип ≥ 0.8 или парадигма с долей ≥ 0.6).
      // Смешанный район получает НЕЙТРАЛЬНУЮ маркировку и честное число, а не
      // выдуманную «тему» (§13).
      var baseLabel;
      if (dominantKind === 'paradigm' && paradigmTitle
          && dominantShare >= 0.6 && paradigmShare >= 0.6) {
        baseLabel = KIND_LABELS.paradigm + ': ' + paradigmTitle;
      } else if (dominantShare >= 0.8) {
        baseLabel = KIND_LABELS[dominantKind] || KIND_LABELS.other;
      } else {
        baseLabel = GROUP_NEUTRAL_LABEL;
      }
      var radius = radiusBase + radiusLog * Math.log(grp.count + 1) / Math.LN2;
      if (!(radius > 0)) radius = radiusBase;
      radius = Math.min(Math.max(radius, radiusMin), radiusMax);
      var screenX = (grp.cx - numberOr(camera.x, 0)) * camScale + width / 2;
      var screenY = (grp.cy - numberOr(camera.y, 0)) * camScale + height / 2;
      grouped += grp.count;
      groups.push({
        // Стабильный, воспроизводимый id: якорь (реальный узел-лидер) + тайл.
        id: 'agg:' + (apex ? apex.id : grp.nodeIds[0]) + ':' + grp.key,
        apexId: apex ? apex.id : grp.nodeIds[0],
        memberIds: grp.nodeIds,
        count: grp.count,
        tile: grp.key,
        componentCount: Object.keys(groupComps).length,
        kinds: kinds,
        dominantKind: dominantKind,
        dominantShare: dominantShare,
        // Самая частая РЕАЛЬНАЯ парадигма района и её доля: подпись берёт
        // название только при доминировании (см. baseLabel выше).
        paradigmTitle: paradigmTitle,
        paradigmShare: paradigmShare,
        // Честная подпись: реальный тип/название + реальное число элементов.
        label: baseLabel + ' · ' + grp.count,
        x: grp.cx, y: grp.cy,
        sx: screenX, sy: screenY,
        radius: radius,
        // Свёрнутая группа: её участники не рисуются поштучно (§5.2 L0).
        hideMembers: grp.count >= hideFrom,
      });
    }
    groups.sort(function (a, b4) {
      return (b4.count - a.count) || (a.id < b4.id ? -1 : (a.id > b4.id ? 1 : 0));
    });

    // Центры агрегатов не могут стоять друг на друге (§6.2 спеки — то же
    // правило, что для узлов; иначе «несколько отделённых групп» не видно, а
    // подписи гарантированно конфликтуют). Разводятся ТОЛЬКО центры нашего
    // слоя: позиции реальных узлов не меняются, камера не двигается.
    // Каждый проход заканчивается прижатием к кадру, поэтому центры никогда не
    // «выдавливаются» за границу и не схлопываются обратно у кромки.
    var sepGap = numberOr(opts.centerGap, 10);
    var sepPasses = numberOr(opts.centerPasses, 32);
    var sepMaxShift = numberOr(opts.centerMaxShift,
      Math.min(width, height) * 0.5);
    var startX = [];
    var startY = [];
    for (i = 0; i < groups.length; i += 1) {
      startX.push(groups[i].sx);
      startY.push(groups[i].sy);
    }
    function clampToFrame(g2) {
      if (!(width > 0 && height > 0)) return;
      var padX = Math.max(2, Math.min(width / 2 - 1, (g2.radius || 0) + 4));
      var padY = Math.max(2, Math.min(height / 2 - 1, (g2.radius || 0) + 4));
      var nx = Math.min(Math.max(g2.sx, padX), width - padX);
      var ny = Math.min(Math.max(g2.sy, padY), height - padY);
      g2.sx = nx;
      g2.sy = ny;
    }
    if (width > 0 && height > 0) {
      for (i = 0; i < groups.length; i += 1) clampToFrame(groups[i]);
    }
    for (var pass = 0; pass < sepPasses; pass += 1) {
      var shifted = false;
      for (var pa = 0; pa < groups.length; pa += 1) {
        for (var pb = pa + 1; pb < groups.length; pb += 1) {
          var ga = groups[pa];
          var gb = groups[pb];
          var ddx = gb.sx - ga.sx;
          var ddy = gb.sy - ga.sy;
          var dist = Math.sqrt(ddx * ddx + ddy * ddy);
          var need = (ga.radius || 0) + (gb.radius || 0) + sepGap;
          if (dist >= need) continue;
          if (dist < 0.001) {
            // Совпавшие центры разводятся по детерминированному направлению
            // (никакой случайности): угол зависит только от индексов пары.
            var ang = ((pa * 37 + pb * 11) % 360) * Math.PI / 180;
            ddx = Math.cos(ang);
            ddy = Math.sin(ang);
            dist = 1;
          }
          var deficit = (need - dist) / 2;
          var ux = ddx / dist;
          var uy = ddy / dist;
          ga.sx -= ux * deficit;
          ga.sy -= uy * deficit;
          gb.sx += ux * deficit;
          gb.sy += uy * deficit;
          shifted = true;
        }
      }
      if (width > 0 && height > 0) {
        for (i = 0; i < groups.length; i += 1) clampToFrame(groups[i]);
      }
      if (!shifted) break;
    }
    for (i = 0; i < groups.length; i += 1) {
      var mvx = groups[i].sx - startX[i];
      var mvy = groups[i].sy - startY[i];
      var mlen = Math.sqrt(mvx * mvx + mvy * mvy);
      if (mlen > sepMaxShift && mlen > 0) {
        mvx *= sepMaxShift / mlen;
        mvy *= sepMaxShift / mlen;
        groups[i].sx = startX[i] + mvx;
        groups[i].sy = startY[i] + mvy;
        if (width > 0 && height > 0) clampToFrame(groups[i]);
      }
      groups[i].shifted = !!(mvx || mvy);
      if (groups[i].shifted) {
        // Сетевые координаты центра пересчитываются из экранных: hit-test
        // раскрытия и отрисовка работают в одной системе.
        if (camScale > 0) {
          groups[i].x = (groups[i].sx - width / 2) / camScale
            + numberOr(camera.x, 0);
          groups[i].y = (groups[i].sy - height / 2) / camScale
            + numberOr(camera.y, 0);
        }
      }
    }

    // Потоки между центрами = РЕАЛЬНЫЕ рёбра между участниками разных групп.
    var groupOf = {};
    for (i = 0; i < groups.length; i += 1) {
      for (var gm = 0; gm < groups[i].memberIds.length; gm += 1) {
        groupOf[groups[i].memberIds[gm]] = groups[i].id;
      }
    }
    var flowMap = {};
    var flowKeys = [];
    for (i = 0; i < edges.length; i += 1) {
      var e = edges[i];
      if (!e) continue;
      var fromGroup = groupOf[String(e.from)];
      var toGroup = groupOf[String(e.to)];
      if (!fromGroup || !toGroup || fromGroup === toGroup) continue;
      var fkey = fromGroup < toGroup
        ? fromGroup + '>' + toGroup : toGroup + '>' + fromGroup;
      if (flowMap[fkey] === undefined) {
        flowMap[fkey] = {
          from: fromGroup < toGroup ? fromGroup : toGroup,
          to: fromGroup < toGroup ? toGroup : fromGroup,
          count: 0,
        };
        flowKeys.push(fkey);
      }
      flowMap[fkey].count += 1;
    }
    flowKeys.sort();
    var flows = [];
    for (i = 0; i < flowKeys.length; i += 1) flows.push(flowMap[flowKeys[i]]);

    return {
      groups: groups,
      flows: flows,
      total: placed.length,
      grouped: grouped,
      singles: placed.length - grouped,
    };
  }


  /* lodFor(r, prev, opts) -> 0 | 1 | 2
   *
   * Контракт §4.2 (формула заморожена), спека §5.1/§5.2:
   *   r = getScale() / fitScaleRef, T1 = 0.85, T2 = 1.80, δ = 0.12.
   * Подъём через порог — по ЗАВЫШЕННОМУ значению T·(1+δ), возврат — по
   * заниженному T·(1−δ); зона нечувствительности на границе 24 % по r, поэтому
   * дрожание колеса/пинча у порога не мигает.
   *
   * Дополнительно — «корректировка по плотности» из §5.2 спеки: плотный кадр
   * (density ≥ opts.densePer100k видимых узлов на 100 000 CSS-px²) читается как
   * уровень 0 даже при r ≈ 1 (fit на 702 узлах — это физически обзор, а не
   * рабочий вид). Плотностная поправка имеет ДВЕ полосы: по r (вход в обзор —
   * до denseMax, выход — только выше denseMax·(1+δ)) и по плотности (вход 60,
   * выход 48 узлов на 100k). Вместе они дают мёртвую зону у всех границ, поэтому
   * дрожание колеса/щипка и колебания числа видимых узлов не переключают уровень.
   * Детальный уровень (r ≥ T2·(1+δ)) приоритетнее плотности всегда: приближение
   * пользователя не отменяется.
   *
   * Функция чистая: `prev` — предыдущий уровень (память гистерезиса), никакого
   * состояния модуля, никаких Date/Math.random.
   */
  function lodFor(r, prev, opts) {
    opts = opts || {};
    var cfg = opts.cfg || DEFAULTS.lod;
    var t1 = numberOr(cfg.t1, DEFAULTS.lod.t1);
    var t2 = numberOr(cfg.t2, DEFAULTS.lod.t2);
    var d = numberOr(cfg.delta, DEFAULTS.lod.delta);
    var rise1 = t1 * (1 + d);
    var fall1 = t1 * (1 - d);
    var rise2 = t2 * (1 + d);
    var fall2 = t2 * (1 - d);
    var p = Math.round(clampNumber(
      (prev === undefined || prev === null) ? 1 : prev, 0, 2));
    var value = numberOr(r, 1);
    if (!(value >= 0)) value = 0;          // NaN/отрицательный масштаб — обзор
    var nodes = numberOr(opts.nodes, 0);
    var density = numberOr(opts.density, null);
    var denseNodes = numberOr(cfg.denseNodes, DEFAULTS.lod.denseNodes);
    var densePer100k = numberOr(cfg.densePer100k, DEFAULTS.lod.densePer100k);
    var denseMax = numberOr(cfg.denseMaxRatio, DEFAULTS.lod.denseMaxRatio);
    // Полоса r для плотностной поправки: ВХОД в обзор по плотности — не выше
    // denseMax, ВЫХОД из него — только выше denseMax·(1+δ). Мёртвая полоса по r
    // (12 %) гасит дрожание колеса/щипка у границы: уйти из обзора и вернуться
    // в него можно только с запасом, а не от каждого события ±1.5 % (§5.1).
    var denseInRatio = denseMax;
    var denseOutRatio = denseMax * (1 + d);
    // Плотность учитывается только на большом наборе: мелкий граф всегда читаем
    // поштучно. «Плотно» и «уже не плотно» разведены коэффициентом
    // denseExitRatio — у самой плотности своя 20 % полоса гистерезиса.
    var denseMeasured = nodes >= denseNodes && density !== null;
    var denseIn = denseMeasured && density >= densePer100k;
    var denseOut = !denseMeasured
      || density < densePer100k * numberOr(cfg.denseExitRatio,
        DEFAULTS.lod.denseExitRatio);
    // 1. Детальный уровень: приближение пользователя важнее плотности.
    if (value >= rise2) return 2;
    if (p === 2) {
      if (value >= fall2) return 2;
      return (value < fall1) ? 0 : 1;
    }
    // 2. Обзор: по r с гистерезисом ИЛИ по плотности кадра (§5.2 спеки).
    if (p === 0) {
      // r вышел за верхнюю границу плотностной полосы — пользователь
      // приближается, обзор снят масштабом.
      if (value > denseOutRatio) return 1;
      // r за порогом T1·(1+δ): обзор держится, только пока кадр остаётся
      // плотным. Гистерезис плотности — выход ниже densePer100k·denseExitRatio
      // (`denseOut`), а не на самой границе входа: иначе обзор мигал бы от
      // каждого изменения числа видимых узлов.
      if (value >= rise1 && denseOut) return 1;
      return 0;
    }
    // p === 1
    if (value < fall1) return 0;
    // В плотный обзор возвращаемся только внутри полосы входа (r ≤ denseMax):
    // между denseMax и denseMax·(1+δ) уровень остаётся рабочим.
    if (denseIn && value <= denseInRatio) return 0;
    return 1;
  }

  /* lodNodesOnScreen(nodes, width, height) -> плотность «узлов на 100k px²».
   * Чистая арифметика: сцена не измерена (0×0) — плотность 0 (не обзор). */
  function lodDensity(count, width, height) {
    var w = numberOr(width, 0);
    var h = numberOr(height, 0);
    var n = numberOr(count, 0);
    if (w <= 0 || h <= 0 || n <= 0) return 0;
    return (n * 100000) / (w * h);
  }

  /* lodTopK(nodeCount, cfg) -> сколько ключевых одиночных узлов видно на L0.
   * Контракт §4.3: K = min(40, ⌈nodes/12⌉). */
  function lodTopK(nodeCount, cfg) {
    var c = cfg || DEFAULTS.lod;
    var n = numberOr(nodeCount, 0);
    if (n <= 0) return 0;
    var byDiv = Math.ceil(n / numberOr(c.topKDiv, DEFAULTS.lod.topKDiv));
    return Math.min(numberOr(c.topKCap, DEFAULTS.lod.topKCap), byDiv);
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

  /* Порядок приоритета подписи (§4.4 спеки, §5.4 контракта):
   * выбранный → найденный поиском → hover → соседи выбранного → агрегат →
   * тип/степень → остальные. Ранг задаётся ЯВНО полем элемента, а не выводится
   * из «случайно совпавших» признаков: аллокатор не может «забыть» выбранный
   * узел и подписать вместо него соседний (§4.4 спеки).
   * Ранг 5 — обычный узел: дальше решают тип и степень (как раньше). */
  var LABEL_RANK = {
    selected: 0, search: 1, hover: 2, neighbor: 3, group: 4, other: 5,
  };

  function labelRankOf(item) {
    if (!item) return LABEL_RANK.other;
    // Явный числовой ранг от вызывающего: LOD-политика уровня (например, на
    // уровне 0 центры групп важнее ЛЮБОЙ подписи узла) задаётся снаружи, а
    // значения по умолчанию остаются детерминированными.
    var explicit = numberOrNull(item.rank);
    if (explicit !== null) return explicit;
    if (item.selected === true) return LABEL_RANK.selected;
    if (item.search === true) return LABEL_RANK.search;
    if (item.hover === true) return LABEL_RANK.hover;
    if (item.neighbor === true) return LABEL_RANK.neighbor;
    if (item.group === true) return LABEL_RANK.group;
    return LABEL_RANK.other;
  }

  function labelPriority(item) {
    var weight = KIND_PRIORITY[item.kind];
    return {
      rank: labelRankOf(item),
      kind: weight === undefined ? KIND_PRIORITY.other : weight,
      degree: -numberOr(item.degree, 0),
      length: (typeof item.title === 'string' ? item.title : '').length,
      id: typeof item.id === 'string' ? item.id : String(item.id || ''),
    };
  }

  function comparePriority(a, b) {
    var pa = labelPriority(a);
    var pb = labelPriority(b);
    if (pa.rank !== pb.rank) return pa.rank - pb.rank;
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
      if (item.selected === true || item.search === true
          || item.hover === true || item.kind === 'paradigm') mandatory += 1;
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
        rank: numberOrNull(item.rank),
        selected: item.selected === true,
        search: item.search === true,
        hover: item.hover === true,
        neighbor: item.neighbor === true,
        group: item.group === true,
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
        group: candidate.group === true,
        selected: candidate.selected === true,
        rank: labelPriority(candidate).rank,
        priority: labelPriority(candidate),
      });
    }
    // Сцена не остаётся «точками без имён»: узкий фильтр/плотный кластер
    // может отбросить ВСЕ подписи по коллизиям, и тогда пользователь видит
    // безымянные точки. Ставим одну — самую приоритетную. Если её бокс не
    // влезает в кадр по горизонтали/вертикали, подпись СДВИГАЕТСЯ внутрь
    // кадра (сама точка при этом в кадре), а не выбрасывается: сдвиг ограничен
    // половиной бокса, поэтому подпись остаётся у своей точки. Наложения нет по
    // определению — она единственная.
    if (!labels.length) {
      var fInset = numberOr(opts.edgeInset, cfg.padding);
      var vw = viewport ? numberOr(viewport.width, 0) : 0;
      var vh = viewport ? numberOr(viewport.height, 0) : 0;
      for (var f = 0; f < placeable.length; f += 1) {
        var fb = placeable[f];
        var ftext = labelText(fb, cfg.maxLabelChars);
        if (!ftext) continue;
        var fw = measureLabel(ftext, cfg.fontSize, cfg.charWidth);
        var fh = cfg.fontSize * 1.4;
        var lx = fb.x;
        var ly = fb.y;
        if (viewport) {
          // Точка за кадром — подписывать нечего (её и не видно).
          if (fb.x < 0 || fb.y < 0 || fb.x > vw || fb.y > vh) continue;
          lx = clampNumber(lx, fInset + fw / 2, vw - fInset - fw / 2);
          ly = clampNumber(ly, fInset + fh / 2, vh - fInset - fh / 2);
        }
        labels.push({
          id: fb.id, x: lx, y: ly, text: ftext,
          width: fw, height: fh,
          priority: labelPriority(fb),
        });
        break;
      }
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

  /* ── счётчики: четыре РАЗНЫЕ величины (§9.9 спеки, §9.3 контракта) ─────── */

  /* countSummary(opts) -> {
   *   db:     {nodes, edges, known}   — всего в базе (сервер может не отдавать);
   *   api:    {nodes, edges}          — принято из API;
   *   filter: {nodes, edges, ofNodes, ofEdges} — видимо после фильтра;
   *   screen: {nodes, edges, aggregates, aggregated, collapsed, total}
   * }
   *
   * Спека §9.9: «различать общее в базе (если сервер отдаёт), полученное с API,
   * видимое в текущем фильтре, агрегированное на экране. Не смешивать».
   * Поэтому «всего в БД» не оценивается: если сервер не отдал — `known:false`,
   * а не «примерно столько же» (§9.3 контракта); `screen.nodes` — то, что
   * различимо поштучно, `screen.aggregated` — сколько исходных элементов
   * свёрнуто в агрегаты (у них на экране честное число).
   */
  function countSummary(opts) {
    opts = opts || {};
    var model = opts.model || {};
    var view = opts.view || {};
    var scene = opts.scene || null;
    var apiNodes = Array.isArray(model.nodes) ? model.nodes.length : 0;
    var apiEdges = Array.isArray(model.edges) ? model.edges.length : 0;
    var viewNodes = Array.isArray(view.nodes) ? view.nodes.length : 0;
    var viewEdges = Array.isArray(view.edges) ? view.edges.length : 0;
    var shown = model.shownOf || null;
    var dbNodes = null;
    var dbEdges = null;
    if (shown && typeof shown === 'object') {
      // Приоритет — прямой итог сервера (`totals.nodes`), а не сумма по классам:
      // сумма охватывает только классы с известным total и занижала бы «в БД».
      var directNodes = numberOrNull(shown.totals && shown.totals.nodes);
      var directEdges = numberOrNull(shown.totals && shown.totals.edges);
      if (directNodes !== null && directNodes > 0) dbNodes = directNodes;
      if (directEdges !== null && directEdges > 0) dbEdges = directEdges;
      if (dbNodes === null) {
        var totalNodes = 0;
        var anyNodes = false;
        var byKind = shown.byKind || {};
        for (var kind in byKind) {
          if (!Object.prototype.hasOwnProperty.call(byKind, kind)) continue;
          var total = numberOrNull(byKind[kind] && byKind[kind].total);
          if (total === null || total <= 0) continue;
          totalNodes += total;
          anyNodes = true;
        }
        if (anyNodes) dbNodes = totalNodes;
      }
    }
    var aggregates = (scene && Array.isArray(scene.aggregates))
      ? scene.aggregates : [];
    var aggregated = 0;
    var collapsed = 0;
    var i;
    for (i = 0; i < aggregates.length; i += 1) {
      var g = aggregates[i];
      aggregated += numberOr(g && g.count, 0);
      if (g && g.hideMembers === true) collapsed += 1;
    }
    var singleVisible = Math.max(0, viewNodes - aggregated);
    return {
      db: {
        nodes: dbNodes, edges: dbEdges,
        known: dbNodes !== null || dbEdges !== null,
      },
      api: { nodes: apiNodes, edges: apiEdges },
      filter: {
        nodes: viewNodes, edges: viewEdges,
        ofNodes: apiNodes, ofEdges: apiEdges,
      },
      screen: {
        nodes: singleVisible,
        edges: viewEdges,
        aggregates: aggregates.length,
        aggregated: aggregated,
        collapsed: collapsed,
        total: singleVisible + aggregated,
      },
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

  /* ── W7-S3: карточка узла/ребра и адресные переходы ──────────────────── */

  function relationLabel(relation) {
    var key = String(relation == null ? '' : relation);
    if (!key) return 'тип не указан';
    return RELATION_LABELS[key] || key;
  }

  /* nodeTimes(node) -> [{key,label,value}]
   * Только РЕАЛЬНО заполненные поля времени: отсутствующее не подменяется
   * соседней датой (иначе «когда произошло» показывало бы время сохранения). */
  function nodeTimes(node) {
    var out = [];
    var time = (node && node.time) || {};
    for (var i = 0; i < TIME_FIELDS.length; i += 1) {
      var field = TIME_FIELDS[i];
      var value = numberOrNull(time[field.key]);
      if (value === null) continue;
      out.push({ key: field.key, label: field.label, value: value });
    }
    return out;
  }

  function nodeProvenance(node) {
    var prov = (node && node.provenance) || {};
    return {
      record: prov.record ? String(prov.record) : null,
      origin: prov.origin ? String(prov.origin) : null,
      messageId: numberOrNull(prov.message_id),
      sourceIds: Array.isArray(prov.source_ids) ? prov.source_ids.slice() : [],
      sourceRefs: Array.isArray(prov.source_refs) ? prov.source_refs.slice() : [],
      versionOf: numberOrNull(prov.version_of),
      dimension: prov.dimension ? String(prov.dimension) : null,
      entityType: prov.entity_type ? String(prov.entity_type) : null,
      agentId: prov.agent_id ? String(prov.agent_id) : null,
    };
  }

  /* nodeMetrics(node) -> {rows, note}
   * Показываются только метрики с РЕАЛЬНЫМ вычислением: importance/weight —
   * как есть из записи (природа названа), degree — по показанным связям.
   * `confidence`/`strength`/`freshness` не рассчитываются нигде в проекте,
   * поэтому их нет в строках, а есть honest-примечание. */
  function nodeMetrics(node) {
    var rows = [];
    var metrics = (node && node.metrics) || {};
    var importance = numberOrNull(metrics.importance);
    var weight = numberOrNull(metrics.weight);
    if (importance !== null) {
      rows.push({ key: 'importance', label: 'Важность', value: importance,
        nature: 'правило извлечения важности' });
    }
    if (weight !== null) {
      rows.push({ key: 'weight', label: 'Вес', value: weight,
        nature: 'правило извлечения веса' });
    }
    rows.push({ key: 'degree', label: 'Связей', value: numberOr(
      node ? node.degree : 0, 0), nature: 'по показанным связям' });
    return { rows: rows,
      note: 'уверенность, сила и свежесть не рассчитываются' };
  }

  /* nodeNeighbors(node, model) -> [{edgeId,id,title,kindLabel,relation,…}]
   * Только РЕАЛЬНО записанные рёбра модели (обе стороны уже проверены при
   * нормализации) — «связанные записи» не достраиваются по совпадению имён. */
  function nodeNeighbors(node, model) {
    var out = [];
    if (!node) return out;
    var edges = (model && model.edges) || [];
    var byId = (model && model.byId) || {};
    for (var i = 0; i < edges.length; i += 1) {
      var edge = edges[i];
      var otherId = null;
      if (edge.from === node.id) otherId = edge.to;
      else if (edge.to === node.id) otherId = edge.from;
      if (!otherId) continue;
      var other = byId[otherId] || null;
      out.push({
        edgeId: edge.id,
        id: otherId,
        title: (other && other.title) || otherId,
        kindLabel: (other && other.kindLabel) || '',
        relation: edge.relation,
        relationLabel: relationLabel(edge.relation),
        derived: edge.derived === true,
      });
    }
    return out;
  }

  /* nodeHistory(node, model) -> {available,count,nodes,reason}
   * «История изменений» — только реальные версии: рёбра `revised_by` и узлы
   * изменений, чьи `old_fact_id`/`new_fact_id` указывают на эту запись.
   * Реконструкция «было/стало» из текущего текста запрещена (§2.5 ТЗ). */
  function nodeHistory(node, model) {
    var empty = { available: false, count: 0, nodes: [],
      reason: 'версий этой записи не записано' };
    if (!node) return empty;
    var byId = (model && model.byId) || {};
    var nodes = (model && model.nodes) || [];
    var edges = (model && model.edges) || [];
    var out = [];
    var seen = {};
    var push = function (other) {
      if (!other || !other.id || seen[other.id]) return;
      seen[other.id] = true;
      out.push({ id: other.id, title: other.title || other.id,
        kindLabel: other.kindLabel || '' });
    };
    for (var i = 0; i < edges.length; i += 1) {
      var edge = edges[i];
      if (edge.relation !== 'revised_by') continue;
      if (edge.from !== node.id && edge.to !== node.id) continue;
      push(byId[edge.from === node.id ? edge.to : edge.from]);
    }
    var factId = numberOrNull((node.provenance || {}).fact_id);
    if (factId !== null) {
      for (var j = 0; j < nodes.length; j += 1) {
        var candidate = nodes[j];
        if (candidate.kind !== 'evolution_event') continue;
        var prov = candidate.provenance || {};
        if (numberOrNull(prov.old_fact_id) !== factId
            && numberOrNull(prov.new_fact_id) !== factId) continue;
        push(candidate);
      }
    }
    out.sort(function (a, b) {
      return a.id < b.id ? -1 : (a.id > b.id ? 1 : 0);
    });
    if (!out.length) return empty;
    return { available: true, count: out.length, nodes: out, reason: '' };
  }

  /* nodeCard(node, model) -> модель карточки узла (или null).
   *
   * Показывает ПО НАЛИЧИЮ ДАННЫХ; отсутствующее названо отсутствующим, а не
   * заменено правдоподобным значением. Кнопки — только работающие: у каждой
   * есть `enabled` и honest `reason` (почему нельзя) и конкретная `target`
   * (что именно откроется). Ни fetch, ни DOM, ни новых запросов здесь нет. */
  function nodeCard(node, model) {
    if (!node || typeof node !== 'object' || !node.id) return null;
    var kindKey = KINDS.indexOf(node.kind) >= 0 ? node.kind : 'other';
    var prov = nodeProvenance(node);
    var times = nodeTimes(node);
    var neighbors = nodeNeighbors(node, model);
    var history = nodeHistory(node, model);
    var metrics = nodeMetrics(node);
    var recordSource = (kindKey === 'fact' || kindKey === 'belief'
      || kindKey === 'paradigm') ? kindKey : null;
    var factId = numberOrNull((node.provenance || {}).fact_id);
    var sourceEnabled = recordSource !== null && prov.messageId !== null
      && node.chatId !== null;
    var sourceReason = '';
    if (!sourceEnabled) {
      if (recordSource === null) {
        if (kindKey === 'entity') sourceReason = 'у сущности нет сообщения-источника';
        else if (kindKey === 'observation') sourceReason = 'у наблюдения нет адреса сообщения';
        else sourceReason = 'у записи изменения нет сообщения-источника';
      } else {
        sourceReason = 'сообщение не записано в данных записи';
      }
    }
    var memoryQuery = node.title || '';
    var actions = [
      {
        id: 'source', label: 'Открыть источник', enabled: sourceEnabled,
        reason: sourceReason,
        target: sourceEnabled ? {
          type: 'record', source: recordSource, factId: factId,
          chatId: node.chatId, messageId: prov.messageId,
        } : null,
      },
      {
        id: 'history', label: 'История изменений', enabled: history.available,
        reason: history.reason,
        target: history.available
          ? { type: 'node', id: history.nodes[0].id } : null,
      },
      {
        id: 'memory', label: 'Открыть в Памяти', enabled: memoryQuery !== '',
        reason: memoryQuery ? '' : 'у записи нет названия — в каталоге её не найти',
        target: memoryQuery ? {
          type: 'memory', query: memoryQuery,
          memoryType: MEMORY_TYPE[kindKey] || 'all',
        } : null,
      },
      {
        id: 'links', label: 'Показать связи', enabled: neighbors.length > 0,
        reason: neighbors.length ? ''
          : (node.isolated ? 'связей не записано: узел изолирован'
            : 'связей не записано'),
        target: neighbors.length ? {
          type: 'links', nodeId: node.id,
          edgeIds: neighbors.map(function (n) { return n.edgeId; }),
        } : null,
      },
    ];
    return {
      kind: 'node',
      id: node.id,
      title: node.title || node.id,
      kindKey: kindKey,
      kindLabel: KIND_LABELS[kindKey],
      scope: node.scope === 'global' ? 'global' : 'chat',
      chatId: node.chatId,
      text: node.text === null || node.text === undefined ? null : String(node.text),
      textNote: (node.text === null || node.text === undefined)
        ? 'текст записи не сохранён' : '',
      status: node.status === null || node.status === undefined
        ? null : String(node.status),
      isolated: node.isolated === true,
      degree: numberOr(node.degree, 0),
      times: times,
      timesNote: times.length ? '' : 'время записи не указано',
      provenance: prov,
      metrics: metrics,
      neighbors: neighbors,
      history: history,
      actions: actions,
    };
  }

  /* edgeCard(edge, model) -> модель карточки ребра (или null).
   *
   * Показывает тип связи, обе сущности, provenance и ЧЕСТНОЕ обоснование:
   * `justification.recorded` берётся из payload как есть. Ребро без записи
   * причины не выдаётся за подтверждённую причинную связь (§2.5 ТЗ). */
  function edgeCard(edge, model) {
    if (!edge || typeof edge !== 'object' || !edge.id) return null;
    var byId = (model && model.byId) || {};
    var prov = edge.provenance || {};
    var factId = numberOrNull(prov.fact_id);
    var basis = prov.basis ? String(prov.basis) : null;
    var recorded = edge.justificationRecorded === true;
    var text;
    if (recorded) {
      text = factId !== null
        ? ('обоснование записано: связь создана фактом №' + factId)
        : 'обоснование записано';
    } else if (basis === 'supersedes') {
      text = 'обоснование не записано как факт; связь выведена из записи о '
        + 'замене версий (№' + numberOr(prov.old_fact_id, '—') + ' → №'
        + numberOr(prov.new_fact_id, '—') + ')';
    } else {
      text = 'обоснование не записано';
    }
    var rows = [];
    var addRow = function (key, label, value) {
      if (value === null || value === undefined || value === '') return;
      rows.push({ key: key, label: label, value: value });
    };
    addRow('edge_id', 'Запись ребра', numberOrNull(prov.edge_id));
    addRow('fact_id', 'Факт-обоснование', factId);
    addRow('origin', 'Происхождение', prov.origin ? String(prov.origin) : null);
    addRow('recorded_at', 'Записано', numberOrNull(prov.recorded_at));
    addRow('updated_at', 'Обновлено', numberOrNull(prov.updated_at));
    addRow('weight', 'Вес связи', numberOrNull(prov.weight));
    addRow('old_fact_id', 'Прежняя версия', numberOrNull(prov.old_fact_id));
    addRow('new_fact_id', 'Новая версия', numberOrNull(prov.new_fact_id));
    addRow('source_fact_id', 'Основание', numberOrNull(prov.source_fact_id));
    addRow('basis', 'Источник связи', basis);
    var endpoint = function (id) {
      var node = byId[id] || null;
      return {
        id: id,
        title: (node && node.title) || id,
        kindLabel: (node && node.kindLabel) || '',
      };
    };
    return {
      kind: 'edge',
      id: edge.id,
      relation: edge.relation || '',
      relationLabel: relationLabel(edge.relation),
      derived: edge.derived === true,
      kindLabel: edge.derived === true ? 'выведена из ссылки в данных'
        : 'записана в графе',
      endpoints: [endpoint(edge.from), endpoint(edge.to)],
      justification: {
        recorded: recorded,
        basis: basis,
        factId: factId,
        text: text,
        rows: rows,
      },
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
    TIME_FIELDS: TIME_FIELDS.map(function (f) {
      return { key: f.key, label: f.label };
    }),
    RELATION_LABELS: RELATION_LABELS,
    relationLabel: relationLabel,
    nodeTimes: nodeTimes,
    nodeHistory: nodeHistory,
    nodeNeighbors: nodeNeighbors,
    nodeCard: nodeCard,
    edgeCard: edgeCard,
    createCamera: createCamera,
    clampCamera: clampCamera,
    cameraFromNetwork: cameraFromNetwork,
    cameraToNetwork: cameraToNetwork,
    cameraEquals: cameraEquals,
    labelText: labelText,
    measureLabel: measureLabel,
    boxesOverlap: boxesOverlap,
    LABEL_RANK: LABEL_RANK,
    labelRankOf: labelRankOf,
    GROUP_NEUTRAL_LABEL: GROUP_NEUTRAL_LABEL,
    labelPriority: labelPriority,
    labelBudget: labelBudget,
    allocateLabels: allocateLabels,
    // CMV-C: LOD (гистерезис §4.2), агрегаты уровня 0 (§5.2), счётчики §9.9.
    lodFor: lodFor,
    lodDensity: lodDensity,
    lodTopK: lodTopK,
    buildAggregates: buildAggregates,
    countSummary: countSummary,
  };
});
