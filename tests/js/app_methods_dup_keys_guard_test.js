'use strict';
/* FIX-W6-LESSON — сторож класса дефектов «дублирующийся ключ в объектном
 * литерале `methods` (web/app.js)». Второй литерал МОЛЧА перекрывает первый,
 * поэтому вызывающий код (в т.ч. обработчики `@click` в index.html) начинает
 * попадать в чужую реализацию, а тесты, читающие `captured.methods`, видят
 * «правильное» имя с чужим поведением.
 *
 * Реальный случай (W6): ключ `lessonAction` был определён дважды — 7728
 * (память MCA-16, 3 аргумента) и 18884 (блок «Речь», 2 аргумента). Второй
 * перекрывал первый: `saveLessonCorrection` теряла payload applicability/
 * exceptions, кнопки «Память» (index.html:2817/2820) после действия грузили
 * раздел «Речь», а node tests/js/round1039_experience_lessons_test.js падал с
 * `TypeError: this.loreErrText is not a function` (app.js:18901).
 *
 * Как ловится: статический лексер определяет границы каждого литерала
 * `methods: { ... }` (строки/шаблоны/комментарии/регекспы учитываются) и
 * собирает ключи первого уровня. Дубль с РАЗНЫМИ телами → FAIL. Дубль с
 * байт-идентичными телами → «мёртвая» копия, FAIL, кроме заранее известного
 * исключения ниже. Дополнительно (тот же класс «ссылка разошлась с
 * реализацией»): каждый `@click(.stop)="name("` в index.html обязан
 * разрешаться в ключ одного из литералов methods, а поведенческая часть грузит
 * app.js со стабом Vue.createApp и проверяет, что `lessonAction` (путь памяти)
 * доводит payload applicability/exceptions до POST, `speechLessonAction` (блок
 * W6) шлёт POST и перезагружает раздел learning, и что это РАЗНЫЕ методы
 * (харнесс W6 кнопки «Пауза»/«Одобрить» не нажимает — иначе у переименования
 * нет поведенческого доказательства).
 *
 * Запуск:
 *   node tests/js/app_methods_dup_keys_guard_test.js                    (repo-пара)
 *   node tests/js/app_methods_dup_keys_guard_test.js <app.js> [index.html]
 *     (второй/третий аргумент — для фальсификации: прогон по pre-fix байтам
 *      обязан упасть)
 * Ожидаемо при корректных байтах: METHODS-DUP-KEYS-OK …
 *
 * TEST-LIFECYCLE: REGRESSION owner=soul-1/W6 (дубль ключа methods.lessonAction)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const TARGET = process.argv[2] || path.join(ROOT, 'web', 'app.js');
const HTML = process.argv[3] || path.join(ROOT, 'web', 'index.html');

// Известный «мёртвый» дубль: существует уже в HEAD (app.js 19842/19861 в
// blob'е HEAD), тела байт-идентичны, поведение не расходится. Вне полосы
// FIX-W6-LESSON (DO_NOT_TOUCH) — фиксируется здесь как ЯВНОЕ исключение, а не
// как молчание: если тела разойдутся или появится третья копия → FAIL.
const KNOWN_DEAD_DUPES = { _prefersReducedMotion: 2 };

// Санити-порог: если лексер развалится (0 блоков / почти нет ключей), сторож
// обязан упасть, а не «зеленеть» на пустом результате. На байтах кандидата
// разбирается 937 ключей (6 литералов methods), порог с запасом.
const MIN_KEYS = 700;

const isIdentStart = (c) => /[A-Za-z_$]/.test(c);
const isIdent = (c) => /[A-Za-z0-9_$]/.test(c);
const REGEX_PREV = '(,=:[!&|?{};+-*%~^<>';
const KEYWORD_RE = /(^|[^A-Za-z0-9_$])(return|typeof|case|in|of|new|delete|void|instanceof|do|else|yield|await)$/;

function lex(source) {
  const n = source.length;
  const inCode = new Uint8Array(n);
  const bracePair = new Map();
  const stack = [{ mode: 'code', open: [], interp: false }];
  let i = 0;

  function regexCanStart(at) {
    let k = at - 1;
    while (k >= 0 && /\s/.test(source[k])) k--;
    if (k < 0) return true;
    if (REGEX_PREV.indexOf(source[k]) >= 0) return true;
    let end = k + 1;
    let start = k;
    while (start >= 0 && isIdent(source[start])) start--;
    const word = source.slice(start + 1, end);
    return KEYWORD_RE.test(' ' + word);
  }

  while (i < n) {
    const top = stack[stack.length - 1];
    const c = source[i];
    if (top.mode === 'tpl') {
      inCode[i] = 0;
      if (c === '\\') { if (i + 1 < n) inCode[i + 1] = 0; i += 2; continue; }
      if (c === '`') { stack.pop(); i++; continue; }
      if (c === '$' && source[i + 1] === '{') {
        stack.push({ mode: 'code', open: [], interp: true });
        i += 2; continue;
      }
      i++; continue;
    }
    if (c === '/' && source[i + 1] === '/') {
      const end = source.indexOf('\n', i);
      const stop = end < 0 ? n : end;
      for (let k = i; k < stop; k++) inCode[k] = 0;
      i = stop; continue;
    }
    if (c === '/' && source[i + 1] === '*') {
      const end = source.indexOf('*/', i + 2);
      const stop = end < 0 ? n : end + 2;
      for (let k = i; k < stop; k++) inCode[k] = 0;
      i = stop; continue;
    }
    if (c === '"' || c === "'") {
      inCode[i] = 0;
      i++;
      while (i < n) {
        if (source[i] === '\\') { inCode[i] = 0; if (i + 1 < n) inCode[i + 1] = 0; i += 2; continue; }
        inCode[i] = 0;
        if (source[i] === c) { i++; break; }
        if (source[i] === '\n') { i++; break; }
        i++;
      }
      continue;
    }
    if (c === '`') { inCode[i] = 0; stack.push({ mode: 'tpl' }); i++; continue; }
    if (c === '/' && regexCanStart(i)) {
      inCode[i] = 0;
      i++;
      let inClass = false;
      while (i < n) {
        const d = source[i];
        if (d === '\\') { inCode[i] = 0; if (i + 1 < n) inCode[i + 1] = 0; i += 2; continue; }
        inCode[i] = 0;
        if (d === '[') inClass = true;
        else if (d === ']') inClass = false;
        else if ((d === '/' && !inClass) || d === '\n') { i++; break; }
        i++;
      }
      continue;
    }
    inCode[i] = 1;
    if (c === '{') { top.open.push(i); i++; continue; }
    if (c === '}') {
      if (top.interp && top.open.length === 0) { stack.pop(); i++; continue; }
      const o = top.open.pop();
      if (o !== undefined) bracePair.set(o, i);
      i++; continue;
    }
    i++;
  }
  return { inCode, bracePair };
}

function collectKeys(source, inCode, block, lineStarts) {
  const keys = [];
  const close = block.close;
  const lineOf = (idx) => {
    let lo = 0;
    let hi = lineStarts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (lineStarts[mid] <= idx) lo = mid; else hi = mid - 1;
    }
    return lo + 1;
  };
  let depth = 1;
  let i = block.open + 1;
  let expectKey = true;
  let cur = null;
  while (i < close) {
    if (!inCode[i]) { i++; continue; }
    const c = source[i];
    if (c === '{' || c === '(' || c === '[') { depth++; i++; continue; }
    if (c === '}' || c === ')' || c === ']') { depth--; i++; continue; }
    if (c === ',' && depth === 1) {
      if (cur) { cur.bodyEnd = i; keys.push(cur); cur = null; }
      expectKey = true; i++; continue;
    }
    if (depth === 1 && expectKey && (isIdentStart(c) || c === '"' || c === "'")) {
      let name = '';
      let j = i;
      if (c === '"' || c === "'") {
        j++;
        while (j < close && source[j] !== c) name += source[j++];
        j++;
      } else {
        while (j < close && isIdent(source[j])) name += source[j++];
      }
      let k = j;
      while (k < close && /\s/.test(source[k])) k++;
      if (source[k] === ':') {
        cur = { name, line: lineOf(i), bodyStart: k + 1, bodyEnd: close };
        expectKey = false;
        i = k + 1;
        continue;
      }
      i = j; continue;
    }
    i++;
  }
  if (cur) { cur.bodyEnd = close; keys.push(cur); }
  return keys;
}

const lineStarts = (src) => {
  const out = [0];
  for (let i = 0; i < src.length; i++) if (src.charCodeAt(i) === 10) out.push(i + 1);
  return out;
};

const norm = (s) => s.split('\n').map((l) => l.trim()).filter(Boolean).join('\n');

// Загрузка app.js как рантайма (Vue.createApp-стаб, как в node-тестах
// периметра): нужна только поведенческой части сторожа.
let capturedOptions = null;

function loadRuntime(target) {
  global.Vue = {
    createApp(opts) {
      capturedOptions = opts;
      return { component() {}, provide() {}, use() {}, mount() {} };
    },
  };
  global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
  global.document = {
    addEventListener() {},
    getElementById() { return null; },
    createElement(tag) {
      return { tagName: tag, className: '', value: '', style: {},
               setAttribute() {}, focus() {}, select() {}, remove() {} };
    },
    body: { appendChild(el) { return el; }, removeChild(el) { return el; } },
    execCommand() { return true; },
  };
  Object.defineProperty(global, 'navigator', {
    configurable: true,
    value: { clipboard: { writeText: async function () {} } },
  });
  global.sessionStorage = {
    _s: {},
    getItem(k) { return this._s[k] || null; },
    setItem(k, v) { this._s[k] = String(v); },
    removeItem(k) { delete this._s[k]; },
  };
  global.history = { replaceState() {} };
  global.Chart = function () {};
  global.fetch = async function () { throw new Error('no fetch in test'); };
  require(path.resolve(target));
  if (!capturedOptions) throw new Error('Vue.createApp не вызван при загрузке ' + target);
  return capturedOptions;
}

function findBlocks(src, inCode, bracePair) {
  const re = /\bmethods\s*:\s*\{/g;
  const blocks = [];
  let m;
  while ((m = re.exec(src))) {
    const open = m.index + m[0].length - 1;
    if (!inCode[open]) continue;
    const close = bracePair.get(open);
    if (close === undefined) return { blocks: null, brokenAt: open };
    blocks.push({ open, close });
  }
  return { blocks, brokenAt: -1 };
}

async function main() {
  const src = fs.readFileSync(TARGET, 'utf8');
  const ls = lineStarts(src);
  const { inCode, bracePair } = lex(src);
  const found = findBlocks(src, inCode, bracePair);
  if (!found.blocks) {
    console.error('GUARD-BROKEN: непарная скобка литерала methods на позиции ' + found.brokenAt);
    process.exit(1);
  }
  const blocks = found.blocks.map((b) => ({
    open: b.open,
    close: b.close,
    keys: collectKeys(src, inCode, b, ls),
  }));

  const totalKeys = blocks.reduce((a, b) => a + b.keys.length, 0);
  if (!blocks.length || totalKeys < MIN_KEYS) {
    console.error('GUARD-BROKEN: разобрано литералов methods=' + blocks.length
      + ', ключей=' + totalKeys + ' (порог ' + MIN_KEYS + ') — лексер не разобрал файл');
    process.exit(1);
  }

  const problems = [];
  const notes = [];
  blocks.forEach((block, bi) => {
    const byName = new Map();
    block.keys.forEach((k) => {
      if (!byName.has(k.name)) byName.set(k.name, []);
      byName.get(k.name).push(k);
    });
    byName.forEach((defs, name) => {
      if (defs.length < 2) return;
      const lines = defs.map((d) => d.line).join(', ');
      const bodies = defs.map((d) => norm(src.slice(d.bodyStart, d.bodyEnd)));
      const identical = bodies.every((b) => b === bodies[0]);
      const known = KNOWN_DEAD_DUPES[name] === defs.length && identical;
      if (known) {
        notes.push('мёртвый дубль (тела идентичны, известен в HEAD): `' + name
          + '` ×' + defs.length + ' @ ' + lines);
        return;
      }
      problems.push('дубль ключа `' + name + '` ×' + defs.length + ' @ строки ' + lines
        + (identical ? ' (тела идентичны, но ключ не в списке известных)'
                     : ' — тела РАЗЛИЧАЮТСЯ: вторая реализация молча перекрывает первую'));
    });
    if (!block.keys.length) problems.push('литерал methods #' + (bi + 1) + ' без ключей (парсер?)');
  });

  // Вторая (вспомогательная) проверка того же класса: обработчик `@click` в
  // index.html обязан разрешаться в метод. Дубль ключа ломает это с ОБЕИХ
  // сторон: либо ссылка ведёт в чужую реализацию (дубль), либо в никуда
  // (переименование в app.js без правки index.html). Ограничение: множество
  // методов собирается по всем литералам (root + дочерние компоненты), поэтому
  // проверка ловит «имени нет нигде», а не «имя не в том компоненте».
  if (fs.existsSync(HTML)) {
    const methods = new Set();
    blocks.forEach((b) => b.keys.forEach((k) => methods.add(k.name)));
    const html = fs.readFileSync(HTML, 'utf8');
    const re = /@click(?:\.\w+)?\s*=\s*"([A-Za-z_$][\w$]*)\s*\(/g;
    const missing = new Set();
    let h;
    while ((h = re.exec(html))) {
      if (!methods.has(h[1])) {
        const line = html.slice(0, h.index).split('\n').length;
        missing.add(h[1] + ' (index.html:' + line + ')');
      }
    }
    missing.forEach((x) => problems.push('обработчик @click не найден в methods: ' + x));
  } else {
    console.log('  WARN: ' + HTML + ' не найден — проверка ссылок @click пропущена');
  }

  // Третья (поведенческая) проверка того же класса: имена должны не только
  // существовать, но и попадать в СВОЮ реализацию. Харнесс
  // tools/ui_soul1_w6_speech_e2e.py кнопки «Пауза»/«Одобрить» раздела «Речь»
  // не нажимает (только стабит /api/memory/lessons/action), поэтому без этой
  // части у переименованного обработчика не было бы поведенческого
  // доказательства: на pre-fix байтах `methods.lessonAction` — это блок «Речь»,
  // и путь памяти теряет payload (ровно дефект, ради которого полоса).
  try {
    const m = loadRuntime(TARGET).methods || {};
    if (typeof m.speechLessonAction !== 'function') {
      problems.push('methods.speechLessonAction отсутствует — переименование блока W6 '
        + 'не применено или перекрыто дублем ключа');
    }
    if (m.lessonAction === m.speechLessonAction) {
      problems.push('methods.lessonAction и methods.speechLessonAction — один и тот же метод');
    }
    if (typeof m.lessonAction !== 'function') {
      problems.push('methods.lessonAction (MCA-16) отсутствует');
    } else {
      const c = { lessonsBusy: false, speechBusy: false }; const seen = [];
      c.api = async (url, opts) => { seen.push({ url, opts }); return { ok: true }; };
      c.loadLessons = async () => { seen.push({ lessons: true }); };
      await m.lessonAction.call(c, { lesson_id: 'L1', version: 3 }, 'correct',
        { applicability: 'tool:web', exceptions: 'e' });
      const post = seen.filter((x) => x.opts && x.opts.method === 'POST').pop();
      const body = post && JSON.parse(post.opts.body);
      if (!post || post.url !== '/api/memory/lessons/action') {
        problems.push('путь памяти: нет POST /api/memory/lessons/action');
      } else if (body.applicability !== 'tool:web' || body.exceptions !== 'e') {
        problems.push('путь памяти: payload applicability/exceptions не дошёл до POST '
          + JSON.stringify(body));
      }
    }
    if (typeof m.speechLessonAction === 'function') {
      const c = { speechBusy: false }; const seen = [];
      c.api = async (url, opts) => { seen.push({ url, opts }); return { ok: true }; };
      c.toast = (msg, kind) => { seen.push({ toast: msg, kind }); };
      c.loadSpeechSection = async (...a) => { seen.push({ section: a }); };
      await m.speechLessonAction.call(c, { lesson_id: 'L1', version: 2 }, 'suspend');
      const post = seen.filter((x) => x.opts && x.opts.method === 'POST').pop();
      const body = post && JSON.parse(post.opts.body);
      const reload = seen.some((x) => x.section && x.section[0] === 'learning'
        && x.section[1] === true);
      if (!post || post.url !== '/api/memory/lessons/action' || !body
          || body.lesson_id !== 'L1' || body.version !== 2 || body.action !== 'suspend') {
        problems.push('путь «Речь»: POST /api/memory/lessons/action не сформирован '
          + JSON.stringify(body));
      } else if (!reload) {
        problems.push('путь «Речь»: раздел learning не перезагружен (loadSpeechSection)');
      } else if (!seen.some((x) => x.toast)) {
        problems.push('путь «Речь»: тост не показан');
      }
    }
  } catch (e) {
    problems.push('поведенческая проверка упала: ' + (e && e.message || e));
  }

  if (problems.length) {
    console.error('METHODS-DUP-KEYS-FAIL (' + TARGET + ')');
    problems.forEach((p) => console.error('  - ' + p));
    process.exit(1);
  }

  console.log('METHODS-DUP-KEYS-OK blocks=' + blocks.length + ' keys=' + totalKeys
    + ' duplicate-problems=0 behavioral=ok');
  notes.forEach((nt) => console.log('  WARN: ' + nt));
}

module.exports = { lex, collectKeys, findBlocks, lineStarts, norm, loadRuntime, TARGET };

if (require.main === module) {
  main().catch((e) => {
    console.error('GUARD-BROKEN: ' + (e && e.stack || e));
    process.exit(1);
  });
}

