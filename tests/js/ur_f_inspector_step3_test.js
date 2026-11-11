'use strict';
/* UR-F шаг 3 (контракт §5) — РЕАЛЬНЫЙ JS-тест UI инспектора хода.
 *
 * Загружает web/app.js в stubbed-окружении (Vue.createApp перехватывает
 * options) и проверяет именно то, что видит владелец в карточках:
 *   1. Расшифровка кодов (UR-20): block-kind, MAP/Branch/Anchor/TTL, ops,
 *      решение и итог поиска, статусы/виды/причины правил стиля. Неизвестный
 *      код → «код: <значение>», а не голый токен.
 *   2. Честная пустота: отсутствующая секция/стадия → «нет данных (трасса
 *      старше версии)», НИКОГДА 0 вместо «неизвестно» (UR-20.5/20.6).
 *   3. Однострочники бюджета и счётчиков; даты — в поясе чата, id — без
 *      обрезки и разрядов.
 *   4. Сворачивание длинных списков: пороги 5/3/4, по умолчанию свёрнуто,
 *      «показать ещё» раскрывает (локальное состояние).
 *   5. `truncated` объясняется словами, а не тревожным флагом.
 *
 * Запуск: node tests/js/ur_f_inspector_step3_test.js   (печатает UR-F-STEP3-OK)
 */
const path = require('path');
const assert = require('assert');
const fs = require('fs');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return {
      component() {}, provide() {}, use() {}, mount() {},
    };
  },
};
global.window = { location: { hash: '' }, addEventListener() {},
  Telegram: null };
global.window.CogVisual = require(path.join(__dirname, '..', '..', 'web',
  'static', 'cog-visual.js'));
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) {
    return { tagName: tag, className: '', value: '', style: {},
             setAttribute() {}, focus() {}, select() {}, remove() {} };
  },
  body: { appendChild() {}, removeChild() {} },
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

const ROOT = path.join(__dirname, '..', '..');
require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const m = captured.methods;
const data = captured.data();
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'),
  'utf8');

const NO_DATA = 'нет данных (трасса старше версии)';
const texts = (arr) => (arr || []).join(' | ');
//: Мини-VM: методы инспектора вызывают друг друга через `this`, как в
//: настоящем компоненте. Здесь тот же набор методов на обычном объекте.
const vm = (extra) => Object.assign({
  turnTz: m.turnTz,
  turnWhen: m.turnWhen,
  turnBlockDates: m.turnBlockDates,
  turnTurnOpen: null,
}, extra || {});

// ── 1. Расшифровка кодов (UR-20) ─────────────────────────────────────────
(function () {
  // Блоки контекста: ровно те подписи, что названы в контракте §5.
  const blocks = {
    global_tail: 'свежие сообщения',
    global_middle: 'подобранные сообщения',
    episode: 'старые эпизоды',
    rag: 'память, факты',
    global_head: 'конспект',
    thread: 'ветка ответов',
    protected: 'защищённые факты',
    sandwich: 'напоминание',
  };
  Object.keys(blocks).forEach(function (code) {
    assert.strictEqual(m.turnCodeLine('block', code),
      blocks[code] + ' (' + code + ')',
      'подпись блока ' + code);
  });
  // Короткие имена из контракта §5 (MAP/Branch/Anchor/TTL).
  assert.strictEqual(m.turnCodeLine('block', 'MAP'),
    'карта участников (MAP)', 'MAP → карта участников');
  assert.strictEqual(m.turnCodeLine('block', 'Branch'),
    'ветка ответов (Branch)', 'Branch → ветка ответов');
  assert.strictEqual(m.turnCodeLine('block', 'Anchor'),
    'привязка к сообщению (Anchor)', 'Anchor → привязка к сообщению');
  assert.strictEqual(m.turnCodeLine('block', 'TTL'),
    'срок жизни записи (TTL)', 'TTL → срок жизни записи');
  // Машинные теги частей payload (путь без композера) тоже объяснены.
  ['Tool_Evidence', 'Current_Question', 'Global_Context', 'RAG_Memory',
    'Old_Episode', 'Conversation_Thread', 'UserResolutionMap',
    'protected_facts', 'chat_lore'].forEach(function (code) {
    const line = m.turnCodeLine('block', code);
    assert(line.indexOf('код: ') !== 0,
      'тег части payload объяснён: ' + code + ' → ' + line);
  });

  // Операции доставки — подписи, а не сырые имена (UR-20.8).
  assert.strictEqual(m.turnOpLine({ op: 'l2_scrubber', changed: false,
    chars: 10 }), 'очистка ответа Writer (l2_scrubber) · без изменений · 10 симв.',
    'ops подписываются понятным именем');
  assert(m.turnDeliveryLabel({ outcome: 'success', digest_match: false,
    divergence_reason: 'l2_scrubber,owner_style_punctuation' }, 'success')
    .indexOf('финальная очистка') < 0, 'нет выдуманной подписи');
  const diverged = m.turnDeliveryLabel({ outcome: 'success',
    digest_match: false,
    divergence_reason: 'l2_scrubber,owner_style_punctuation' }, 'success');
  assert(diverged.indexOf('l2_scrubber') >= 0
    && diverged.indexOf('очистка ответа Writer') >= 0,
    'причина расхождения digest расшифрована: ' + diverged);

  // Решение о поиске — словами (UR-20.7), код остаётся рядом.
  assert.strictEqual(m.turnSearchDecisionWord({ decision: 'required' }),
    'поиск обязателен');
  assert.strictEqual(m.turnSearchDecisionWord({ decision: 'beneficial' }),
    'поиск полезен');
  assert.strictEqual(m.turnSearchDecisionWord({ decision: 'not_applicable' }),
    'поиск не нужен');
  assert.strictEqual(m.turnSearchDecisionWord({ decision: 'weird' }),
    'код: weird', 'неизвестное решение — читаемый fallback');
  assert(m.turnSearchActionLine({ called: false, status: 'skipped_not_required',
    skip_reason: 'user_forbidden_external' })
    .indexOf('внешний поиск выключен в чате') >= 0,
    'причина пропуска поиска объяснена словами');

  // Статусы правил стиля — только из закрытого набора (UR-20.8).
  ['pass', 'repaired', 'exempted', 'conflict', 'failed', 'denied',
    'not_applicable'].forEach(function (status) {
    const line = m.turnCodeLine('rule_status', status);
    assert(line.indexOf('код: ') !== 0, 'статус правила объяснён: ' + status);
  });
  assert.strictEqual(m.turnCodeLine('rule_status', 'glitch'), 'код: glitch');
  // Сработавшее правило: «сработало правило: <имя> · причина <код>».
  const fired = m.turnRuleLine({ rule_id: 'dash.hard.factory', kind: 'dash',
    status: 'repaired', reason: 'dash_replaced' });
  assert(fired.indexOf('сработало правило: тире') === 0,
    'строка сработавшего правила: ' + fired);
  assert(fired.indexOf('тире заменено (dash_replaced)') >= 0,
    'причина правила расшифрована: ' + fired);
  // Правило без нарушений не называется «сработавшим».
  assert(m.turnRuleLine({ rule_id: 'q', kind: 'quotation_marks',
    status: 'pass' }).indexOf('сработало') < 0,
    'pass-правило не выдаёт себя за сработавшее');
  assert(m.turnRuleLine({ rule_id: 'x', kind: 'one_word', status: 'failed',
    reason: 'mystery_reason' }).indexOf('код: mystery_reason') >= 0,
    'неизвестная причина правила — fallback «код: …»');
  // Текста правил и секретов в строке нет — только имя/статус/причина.
  assert(!/secret|detail|текст правила/i.test(fired), 'нет текста правил');

  // Действие L1 и причина запуска хода.
  assert.strictEqual(m.turnCodeLine('action', 'reply'), 'ответить (reply)');
  assert.strictEqual(m.turnCodeLine('action', 'mystery'), 'код: mystery');
  assert.strictEqual(m.turnCodeLine('trigger', 'reply_to_bot'),
    'ответ на сообщение бота (reply_to_bot)');
})();

// ── 2. Честная пустота: «нет данных», а не 0 ─────────────────────────────
(function () {
  assert.strictEqual(m.turnBudgetLine(null), NO_DATA,
    'нет снимка выбора — честная пустота');
  assert.strictEqual(m.turnCountsLine(null), NO_DATA);
  assert.strictEqual(m.turnSourceWho(null), NO_DATA);
  assert.strictEqual(m.turnSourceReply(null), NO_DATA);
  assert.strictEqual(m.turnStyleHeader(null),
    'правила стиля не зафиксированы (трасса старше версии)');
  assert(m.turnSearchDecisionWord(null).indexOf('не зафиксировано') >= 0,
    'нет search — «решение не зафиксировано»');
  assert.strictEqual(m.turnTruncNote(null), '');
  assert.deepStrictEqual(m.turnBlockRows(null), []);
  assert.deepStrictEqual(m.turnDroppedLines(null), []);
  assert.deepStrictEqual(m.turnSelfOutputLines(null), []);

  // Старое поле (null) внутри существующей секции — «неизвестно», не 0.
  const budget = m.turnBudgetLine({ window: null, output_reserve: null,
    payload_tokens: null, budget: null, policy_mode: null });
  assert(/неизвестно/.test(budget), 'числа неизвестны словом: ' + budget);
  assert(!/(^|\s)0(\s|$)/.test(budget),
    'никакого 0 вместо неизвестного: ' + budget);
  const counts = m.turnCountsLine({ available_messages: null,
    included_messages: null });
  assert(/неизвестно/.test(counts) && !/(^|\s)0(\s|$)/.test(counts),
    'счётчики не подменяются нулём: ' + counts);

  // Присутствие стадии в `stages` — источник формулировки «нет данных».
  const ctxOld = { turnDiag: { stages: { context: true, writer: false } } };
  assert.strictEqual(m.turnMissing.call(ctxOld, 'writer'), NO_DATA,
    'stages.writer=false → «трасса старше версии»');
  assert.strictEqual(m.turnMissing.call(ctxOld, 'context'), 'нет данных');

  // Стадии часов: null (неизвестно) ≠ пустой список (не подавались).
  assert(m.turnClockStagesLine({ stages: null })
    .indexOf('не зафиксированы') >= 0, 'stages=null — честно «неизвестно»');
  assert.strictEqual(m.turnClockStagesLine({ stages: ['l1', 'tool', 'l2'] }),
    'часы поданы на этапах: L1, инструменты, ответ');
  assert.strictEqual(m.turnClockStagesLine({ stages: [] }),
    'часы не поданы ни на одной стадии');
})();

// ── 3. Однострочники, пояс чата, id без обрезки ──────────────────────────
(function () {
  const budget = m.turnBudgetLine({
    window: 128000, window_source: 'model_map', output_reserve: 12800,
    payload_tokens: 5400, budget: 16000, policy_mode: 'dynamic' });
  assert.strictEqual(budget,
    'окно модели 128 000 (из справочника моделей) · запас на ответ 12 800 '
    + '· вошло 5 400 из бюджета 16 000 · режим: динамический',
    'бюджет — одна строка с расшифровкой режима');
  assert.strictEqual(m.turnCountsLine({ available_messages: 25,
    included_messages: 12 }),
    'доступно сообщений 25 · вошло в запрос 12');

  const ctx = vm({ turnDiag: { clock: { timezone: 'Europe/Moscow' } } });
  const when = m.turnWhen.call(ctx, 1792229900);
  assert(/^\d{2}\.\d{2} \d{2}:\d{2}$/.test(when),
    'дата в поясе чата: ' + when);
  // Пояса нет — честные UTC-цифры с пометкой, а не выдуманная зона.
  const utc = m.turnWhen.call(vm({ turnDiag: null }), 1792229900);
  assert(/ UTC$/.test(utc), 'без пояса — явная пометка UTC: ' + utc);

  const rows = m.turnBlockRows.call(vm(), { blocks: [
    { kind: 'global_tail', role: 'p1', rendered: true,
      source_ids: ['msg:987654321012', 'fact:42', 'summary:-100500:2'],
      first_ts: 1792228800, last_ts: 1792229900, tokens: 800 },
    { kind: 'mystery_kind', role: 'p3', rendered: false,
      skip_reason: 'budget_exceeded', source_ids: [],
      first_ts: 0, last_ts: 0, tokens: 0 },
    { kind: 'sandwich', role: 'p0', rendered: true, source_ids: [],
      first_ts: null, last_ts: null, tokens: null },
  ] });
  assert.strictEqual(rows.length, 3, 'каждый блок — отдельная строка');
  assert.strictEqual(rows[0].name, 'свежие сообщения', 'понятное имя блока');
  assert.strictEqual(rows[0].priority, 'вытесняется последним',
    'role — приоритет вытеснения, не роль участника');
  assert(rows[0].dates.indexOf('—') >= 0, 'даты блока: ' + rows[0].dates);
  assert.deepStrictEqual(rows[0].refs,
    ['сообщение 987654321012', 'факт памяти 42', 'конспект -100500:2'],
    'ссылки блока названы по-человечески: ' + rows[0].refs.join(', '));
  assert.strictEqual(rows[1].name, 'код: mystery_kind',
    'неизвестный вид блока — читаемый fallback');
  assert.strictEqual(rows[1].skip, 'не вошло в запрос: не поместилось в окно модели');
  assert.strictEqual(rows[2].tokens, '', 'нулевые токены не выдумываются');
  assert.strictEqual(rows[2].dates, '', 'нулевой ts — даты нет, а не 1970');

  const dropped = m.turnDroppedLines({ dropped: [
    { reason_code: 'budget_exceeded', kind: 'global_middle', count: 3 },
    { reason_code: 'mystery_reason', kind: 'thread', count: 1 }] });
  assert.strictEqual(dropped[0],
    'не поместилось в окно модели · подобранные сообщения · 3 шт.');
  assert.strictEqual(dropped[1],
    'код: mystery_reason · ветка ответов · 1 шт.');

  const own = m.turnSelfOutputLines({
    self_outputs: [{ source_id: 'bot_output:42', tg_message_id: 4242,
      ts: 1792229800 }] });
  assert(own[0].indexOf('сообщение 4242') === 0 && own[0].indexOf('·') > 0,
    'своя реплика — tg id и дата: ' + own[0]);
})();

// ── 4. Сворачивание длинных списков (§5: 5 / 3 / 4) ──────────────────────
(function () {
  const blocks = new Array(7).fill({ kind: 'global_tail' });
  const links = new Array(4).fill({ source_url: 'https://x.test/1' });
  const rules = new Array(6).fill({ rule_id: 'r', kind: 'dash' });
  const ctx = { turnDiagOpen: {} };
  assert.strictEqual(m.turnVisibleList.call(ctx, blocks, 'blocks', 5).length,
    5, 'блоки: свёрнуто до 5');
  assert.strictEqual(m.turnHiddenCount.call(ctx, blocks, 'blocks', 5), 2,
    'скрыто 2 → «показать ещё 2»');
  assert.strictEqual(m.turnVisibleList.call(ctx, links, 'links', 3).length, 3,
    'ссылки: свёрнуто до 3');
  assert.strictEqual(m.turnHiddenCount.call(ctx, links, 'links', 3), 1);
  assert.strictEqual(m.turnVisibleList.call(ctx, rules, 'rules', 4).length, 4,
    'правила: свёрнуто до 4');
  assert.strictEqual(m.turnHiddenCount.call(ctx, rules, 'rules', 4), 2);
  // Короткий список не сворачивается вовсе.
  assert.strictEqual(m.turnVisibleList.call(ctx, blocks.slice(0, 3),
    'blocks', 5).length, 3);
  assert.strictEqual(m.turnHiddenCount.call(ctx, blocks.slice(0, 3),
    'blocks', 5), 0);
  // Раскрытие — локальное состояние экрана, списки при этом целы.
  m.turnToggleMore.call(ctx, 'blocks');
  assert.strictEqual(ctx.turnDiagOpen.blocks, true, 'раскрытие записано');
  assert.strictEqual(m.turnVisibleList.call(ctx, blocks, 'blocks', 5).length,
    7, 'после «показать ещё» видны все');
  assert.strictEqual(m.turnHiddenCount.call(ctx, blocks, 'blocks', 5), 0,
    'кнопка исчезает после раскрытия');

  // Пороги из контракта закреплены в разметке, а не «на глаз».
  assert(INDEX.indexOf("'blocks', 5") >= 0, 'порог блоков в шаблоне');
  assert(INDEX.indexOf("'links', 3") >= 0, 'порог ссылок в шаблоне');
  assert(INDEX.indexOf("'rules', 4") >= 0, 'порог правил в шаблоне');
  assert.strictEqual(data.turnDiagOpen && typeof data.turnDiagOpen,
    'object', 'состояние раскрытия живёт в data');
})();

// ── 5. `truncated` объясняется словами, а не флагом ──────────────────────
(function () {
  const note = m.turnTruncNote({ truncated: true, dropped_total: 9,
    blocks: new Array(7).fill({ kind: 'rag' }),
    dropped: [{ reason_code: 'budget_exceeded' }, { reason_code: 'compressed' }],
    self_outputs: [{ tg_message_id: 1 }] });
  assert(note.indexOf('показаны первые 2 из 9') >= 0,
    'усечение потерянных — конкретными числами: ' + note);
  assert(note.indexOf('показаны 7') >= 0, 'блоки названы числом: ' + note);
  assert(m.turnTruncNote({ truncated: false }).indexOf('сокращена') < 0,
    'обычный ход не показывает тревожный флаг');

  // Ссылки: пустая дата публикации не выдумывается (UR-20.7).
  assert.strictEqual(m.turnLinkWhen({ source_id: 'web:1' }),
    'дата публикации не сообщается источником');
  assert.strictEqual(m.turnLinkWhen({ published_at: '2026-11-01' }),
    'опубликовано 01.11.2026');
  assert.strictEqual(m.turnLinkTitle({ source_id: 'web:1' }),
    'источник из поиска 1', 'без заголовка — понятная ссылка на источник');
})();

// ── 6. Разметка: карточки, отсутствие таблиц и обрезки (§5) ──────────────
(function () {
  const start = INDEX.indexOf('data-turn-inspector');
  assert(start > 0, 'секция инспектора на месте');
  const section = INDEX.slice(start, INDEX.indexOf('</div>\n\n              <!-- ── B07',
    start));
  assert(section.length > 2000, 'секция инспектора найдена целиком');
  const titles = ['Планирование (L1)', 'Инструменты и поиск',
    'Что видел ответ', 'Операции и доставка'];
  let last = -1;
  titles.forEach(function (t) {
    const at = section.indexOf(t);
    assert(at > last, 'карточка «' + t + '» на своём месте');
    last = at;
  });
  assert(section.indexOf('grid gap-2 md:grid-cols-2') >= 0,
    'каркас сетки не перестроен');
  ['l1', 'tools', 'writer', 'delivery'].forEach(function (stage) {
    assert(section.indexOf('data-turn-stage="' + stage + '"') >= 0,
      'карточка ' + stage + ' сохранена');
  });
  assert(section.indexOf('<table') < 0, 'никаких таблиц в инспекторе');
  assert(!/class="[^"]*\btruncate\b/.test(section),
    'ни одного truncate на id/датах в инспекторе');
  assert(section.indexOf('turn-wrap') >= 0, 'строки переносятся');
  assert(CSS.indexOf('[data-turn-inspector] .turn-wrap') >= 0,
    'CSS переноса длинных значений добавлен');
  assert(CSS.indexOf('overflow-wrap: anywhere') >= 0,
    'длинные id/адреса переносятся, а не обрезаются');
  assert(/не\s+образец\s+стиля/.test(section),
    'свои реплики честно не названы образцом стиля');
})();

console.log('UR-F-STEP3-OK');
