/* VMQ-TIME-09 (19.11.2026) — чистые helper'ы UI «покрытие памяти по годам».
 *
 * Один прогон = один ход: Writer-блоки (`direct_turn_selection.blocks[].years`)
 * и вызовы `retrieve()` (`mca07_retrieval`) одного `trace_id`. Никакой
 * агрегации: все числа — целые счётчики фактов/кандидатов этого прогона,
 * процентов/шкал/донатов здесь нет и не появляется.
 *
 * Zero-build / CSP `script-src 'self'`: обычный UMD-модуль, как
 * `execution_graph.js`/`cognitive-map.js`. Node-тест подключает его через
 * `require`; браузер — глобальным `window.StatusAnalytics`.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.StatusAnalytics = api;
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  //: Закрытый набор причин исключения кандидата-факта (единый с backend).
  var EXCLUSION_KEYS = ['policy_operative', 'status', 'expired',
    'relevance', 'budget'];
  var EXCLUSION_LABELS = {
    policy_operative: 'квота оперативного набора',
    status: 'статус',
    expired: 'давность',
    relevance: 'релевантность',
    budget: 'контекстный бюджет',
  };
  var EXCLUSION_SHORT = {
    policy_operative: 'квота',
    status: 'статус',
    expired: 'давность',
    relevance: 'релевантность',
    budget: 'бюджет',
  };
  var MAX_YEARS = 8;
  var CHIPS_MAX = 3;

  function _int(value) {
    if (typeof value === 'number' && isFinite(value)) {
      return Math.trunc(value);
    }
    if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
      return parseInt(value, 10);
    }
    return null;
  }

  function _list(value) {
    return Array.isArray(value) ? value : [];
  }

  /** Годы: только настоящие календарные годы с положительным счётчиком. */
  function sortedYears(years) {
    if (!years || typeof years !== 'object' || Array.isArray(years)) {
      return [];
    }
    var out = [];
    Object.keys(years).forEach(function (key) {
      if (!/^\d{4}$/.test(String(key))) {
        return;
      }
      var year = parseInt(key, 10);
      var count = _int(years[key]);
      if (!year || year < 1900 || count === null || count <= 0) {
        return;
      }
      out.push({ year: year, count: count });
    });
    out.sort(function (a, b) { return a.year - b.year; });
    return out.slice(0, MAX_YEARS);
  }

  function yearsText(years) {
    if (years === null || typeof years === 'undefined') {
      return 'нет данных';
    }
    var rows = sortedYears(years);
    if (!rows.length) {
      return 'нет фактов';
    }
    return rows.map(function (row) {
      return row.year + ' — ' + row.count;
    }).join(' · ');
  }

  /** Причины исключения: только при наличии измерения (present). */
  function exclusionRows(excluded, present) {
    if (!present) {
      return null;
    }
    var source = (excluded && typeof excluded === 'object') ? excluded : {};
    return EXCLUSION_KEYS.map(function (key) {
      var count = _int(source[key]);
      return {
        key: key,
        label: EXCLUSION_LABELS[key],
        short: EXCLUSION_SHORT[key],
        count: (count === null || count < 0) ? 0 : count,
      };
    });
  }

  function exclusionText(excluded, present) {
    var rows = exclusionRows(excluded, present);
    if (rows === null) {
      return 'нет данных';
    }
    var total = rows.reduce(function (sum, row) { return sum + row.count; }, 0);
    if (!total) {
      return 'исключений не было';
    }
    return rows.map(function (row) {
      return row.short + ' ' + row.count;
    }).join(' · ');
  }

  function _writerRow(block) {
    var years = block && block.years;
    var present = !!(block && block.years_present === true);
    return {
      kind: block.kind,
      delivered: block.rendered === true,
      skipReason: block.skip_reason || '',
      years: present ? (years || {}) : null,
      yearsPresent: present,
      // F3: при `years_present=true` API отдаёт `years: null` для
      // измеренного пустого набора — это «нет фактов», а не «нет данных».
      yearsText: present ? yearsText(years || {}) : 'нет данных',
      chips: present ? sortedYears(years).slice(0, CHIPS_MAX) : [],
      chipsTotal: present ? sortedYears(years).length : 0,
    };
  }

  /**
   * Writer-блоки: только факты (`rag`) и строки эпизодов (`episode`).
   * `global_tail`/`global_middle` — история чата, не память: в покрытие не
   * входят. `rendered=false` — «не дошло», но причина сохраняется.
   */
  function writerBlocks(blocks) {
    var out = { facts: null, episodes: null, ignoredHistory: 0 };
    _list(blocks).forEach(function (block) {
      if (!block || typeof block !== 'object') {
        return;
      }
      if (block.kind === 'global_tail' || block.kind === 'global_middle') {
        out.ignoredHistory += 1;
        return;
      }
      if (block.kind === 'rag' && out.facts === null) {
        out.facts = _writerRow(block);
      } else if (block.kind === 'episode' && out.episodes === null) {
        out.episodes = _writerRow(block);
      }
    });
    return out;
  }

  function _runs(runs) {
    return _list(runs).filter(function (run) {
      return run && typeof run === 'object';
    });
  }

  /** Основной вызов хода: первый НЕ-периодный (не порядок массива). */
  function primaryRun(runs) {
    var list = _runs(runs);
    if (!list.length) {
      return null;
    }
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].period !== true) {
        return list[i];
      }
    }
    return list[0];
  }

  /** Самый свежий вызов по `ts` (stale-порядок массива не выдаётся за ход). */
  function latestRun(runs) {
    var list = _runs(runs);
    var best = null;
    list.forEach(function (run) {
      var ts = _int(run.ts);
      if (best === null || (ts !== null && ts > _int(best.ts))) {
        best = run;
      }
    });
    return best;
  }

  function sortRuns(runs) {
    return _runs(runs).slice().sort(function (a, b) {
      return (_int(a.ts) || 0) - (_int(b.ts) || 0);
    });
  }

  function _runView(run) {
    var yearsPresent = run.years_present === true;
    var excludedPresent = run.excluded_present === true;
    var emptyYears = yearsPresent && !sortedYears(run.years).length;
    var reason = String(run.reason_code || '');
    return {
      ts: _int(run.ts),
      outcome: run.outcome || '',
      reason: reason,
      policy: run.policy || '',
      period: run.period === true,
      // F1: шаблон читает `run.yearsPresent`; поле обязано быть в модели,
      // иначе рядом с реальными годами печатается «нет данных».
      yearsPresent: yearsPresent,
      years: yearsPresent ? (run.years || {}) : null,
      yearsText: yearsPresent ? yearsText(run.years || {}) : 'нет данных',
      chips: yearsPresent ? sortedYears(run.years).slice(0, CHIPS_MAX) : [],
      // B8: измеренный ноль с причиной `retrieval_empty` показывает код
      // причины (brief §3.4), а не только «нет фактов».
      emptyText: !emptyYears ? ''
        : (reason === 'retrieval_empty'
          ? '0 фактов (выдача пуста, причина: retrieval_empty)'
          : 'нет фактов'),
      excluded: run.excluded || {},
      excludedPresent: excludedPresent,
      exclusionText: exclusionText(run.excluded, excludedPresent),
      emptyYears: emptyYears,
      emptyExcluded: excludedPresent
        && !exclusionRows(run.excluded, true).some(function (row) {
          return row.count > 0;
        }),
    };
  }

  /** Подпись хода: «последний ход» только для turn=1 (F4). */
  function turnLabel(turn, turnsCount) {
    var number = _int(turn);
    if (number === null || number <= 1) {
      return 'последний ход';
    }
    var total = _int(turnsCount);
    if (total !== null && total >= number) {
      return 'ход ' + number + ' из ' + total;
    }
    return 'ход ' + number;
  }

  function _limitations(selection, truncated) {
    var out = [];
    if (truncated) {
      out.push('Детализация блоков усечена — отсутствующие годы не '
        + 'считаются нулями.');
    }
    if (selection && selection.truncated === true && !truncated) {
      out.push('Детализация блоков усечена — отсутствующие годы не '
        + 'считаются нулями.');
    }
    return out;
  }

  function _base(state, text) {
    return {
      state: state,
      text: text,
      writer: { facts: null, episodes: null, ignoredHistory: 0 },
      writerNote: '',
      runs: [],
      primary: null,
      runCount: 0,
      extraRuns: 0,
      memoryPeriod: null,
      limitations: [],
    };
  }

  /**
   * Полный view обеих поверхностей (Status — компактно, Analytics — список
   * вызовов). Вход — payload `/api/direct/turn-diagnostics` + состояние
   * загрузчика (`no_chat`/`error`/`loading`).
   */
  function view(payload) {
    var data = payload && typeof payload === 'object' ? payload : {};
    if (data.loading) {
      return _base('loading', 'Загрузка покрытия…');
    }
    if (data.no_chat) {
      return _base('no_chat',
        'Выберите чат — покрытие привязано к выбранному чату.');
    }
    if (data.error) {
      return _base('error',
        'Не удалось загрузить покрытие: ' + String(data.error));
    }
    if (data.available !== true) {
      var reason = String(data.reason || '');
      if (reason === 'no_turn_traces') {
        return _base('empty', 'Ходов этого чата ещё нет — покрытие '
          + 'появится после первого ответа.');
      }
      if (reason === 'trace_not_found') {
        return _base('empty', 'Выбранный ход не найден в трассе — '
          + 'показывать нечего.');
      }
      return _base('empty', 'Покрытие недоступно (' + (reason || 'нет данных')
        + ').');
    }
    var selection = (data.selection && typeof data.selection === 'object')
      ? data.selection : null;
    if (selection === null) {
      var noSelection = _base('no_selection',
        'У выбранного хода нет снимка памяти (ответ без памяти / '
        + 'трасса неполная).');
      noSelection.limitations = _limitations(null, false);
      return noSelection;
    }
    var truncated = selection.truncated === true;
    var writer = writerBlocks(selection.blocks);
    var runs = sortRuns(data.retrieval).map(_runView);
    var out = _base(truncated ? 'truncated' : 'ready', '');
    out.writer = writer;
    out.runs = runs;
    out.runCount = runs.length;
    out.extraRuns = Math.max(0, runs.length - 1);
    out.primary = runs.length ? primaryRun(runs) : null;
    out.memoryPeriod = (selection.memory_period
      && typeof selection.memory_period === 'object')
      ? selection.memory_period : null;
    out.limitations = _limitations(selection, truncated);
    if (!writer.facts) {
      out.writerNote = truncated
        ? 'RAG-блок: не зафиксировано (детализация усечена) — отсутствующие '
          + 'годы не считаются нулями.'
        : 'RAG-блок: не зафиксировано — не дошёл до Writer.';
    }
    if (truncated) {
      out.text = out.limitations[0] || 'Детализация блоков усечена.';
      return out;
    }
    if (!runs.length) {
      out.state = 'no_retrieval';
      out.text = 'Событий retrieval с привязкой к этому ходу нет — '
        + 'Writer-часть показана.';
      return out;
    }
    out.text = (writer.facts && writer.facts.delivered
      ? 'Дошло до Writer: ' + writer.facts.yearsText
      : 'RAG-блок не дошёл до Writer');
    return out;
  }

  return {
    EXCLUSION_KEYS: EXCLUSION_KEYS,
    EXCLUSION_LABELS: EXCLUSION_LABELS,
    MAX_YEARS: MAX_YEARS,
    CHIPS_MAX: CHIPS_MAX,
    sortedYears: sortedYears,
    yearsText: yearsText,
    exclusionRows: exclusionRows,
    exclusionText: exclusionText,
    writerBlocks: writerBlocks,
    primaryRun: primaryRun,
    latestRun: latestRun,
    sortRuns: sortRuns,
    turnLabel: turnLabel,
    view: view,
  };
});
