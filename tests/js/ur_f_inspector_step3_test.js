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
  turnSummaryNote: m.turnSummaryNote,
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

// ── 7. Доработка шага 1 (UR-20.4…20.8): строки, которых не было ──────────
(function () {
  // Собственный `this` с методами компонента: хелперы вызывают друг друга.
  const withTz = (tz) => Object.assign({}, m,
    { turnDiag: tz ? { clock: { timezone: tz } } : {} });

  // (1) UR-20.4: дата сообщения-родителя — тем же форматом, что у автора.
  const reply = m.turnSourceReply.call(withTz('Europe/Moscow'),
    { reply_to_id: 987654321000, reply_to_alias: 'Борис',
      reply_to_ts: 1792229400 });
  assert(/^в ответ на: Борис \(сообщение 987654321000, \d{2}\.\d{2} \d{2}:\d{2}\)$/
    .test(reply), 'дата родителя в строке: ' + reply);
  // Даты нет — прежняя честная строка без выдуманного времени.
  assert.strictEqual(
    m.turnSourceReply.call(withTz('Europe/Moscow'),
      { reply_to_id: 5, reply_to_alias: 'Борис' }),
    'в ответ на: Борис (сообщение 5)');

  // (2) UR-20.5: у конспекта — «конспект до <дата>» и диапазон, без id.
  const rows = m.turnBlockRows.call(withTz('Europe/Moscow'), { blocks: [
    { kind: 'global_head', role: 'p2', rendered: true, source_ids: [],
      first_ts: 1792000000, last_ts: 1792050000, tokens: 512 },
    { kind: 'global_tail', role: 'p1', rendered: true,
      source_ids: ['msg:1'], first_ts: 1792228800, last_ts: 1792229900,
      tokens: 800 },
  ] });
  assert(/^конспект до \d{2}\.\d{2} \d{2}:\d{2}/.test(rows[0].summary),
    'конспект до даты: ' + rows[0].summary);
  assert(rows[0].summary.indexOf('диапазон:') >= 0, rows[0].summary);
  assert(rows[0].summary.indexOf('единого id источника') >= 0);
  assert.strictEqual(rows[0].dates, '',
    'диапазон не дублируется второй строкой');
  assert.strictEqual(rows[0].refs.length, 0, 'id конспекта не выдуман');
  assert.strictEqual(rows[1].summary, '', 'у дословных строк — прежний вид');
  assert(rows[1].dates.indexOf('—') >= 0);
  // Старая трасса без дат: пусто, а не «01.01 1970».
  const oldRows = m.turnBlockRows.call(withTz('Europe/Moscow'), { blocks: [
    { kind: 'global_head', rendered: true, source_ids: [],
      first_ts: 0, last_ts: 0, tokens: 512 }] });
  assert.strictEqual(oldRows[0].summary, '');

  // (3) UR-20.6: отдельная строка L1 и строка L2 с фактическим пределом.
  const full = Object.assign({}, m, { turnDiag: {
    context: { l1: { model: 'test-model-8b', slot: 'l1_slot',
                     fallback: 'fb-model' } },
    selection: { budget: { slot: 'direct.primary', output_reserve: 12800 } },
    writer: { request: { provider: 'api.example', model: 'test-model-8b',
                         fallback_model: 'fb-model', max_output_tokens: 4096 },
              completion: { max_output_tokens_sent: 4096 } } } });
  assert.strictEqual(full.turnL1ModelLine(),
    'L1: модель test-model-8b · слот: выделенный планировщик (l1_slot) '
    + '· fallback: fb-model · запас на ответ 12 800');
  // Второй режим планирования — основная модель: слот показан, а не скрыт.
  const mainSlot = Object.assign({}, m, { turnDiag: {
    context: { l1: { model: 'test-model-8b', slot: 'main',
                     fallback: 'fb-model' } },
    selection: { budget: { slot: 'direct.primary', output_reserve: 12800 } } } });
  assert.strictEqual(mainSlot.turnL1ModelLine(),
    'L1: модель test-model-8b · слот: основная модель (main) '
    + '· fallback: fb-model · запас на ответ 12 800');
  assert.notStrictEqual(full.turnL1ModelLine(), mainSlot.turnL1ModelLine(),
    'два режима планирования обязаны различаться в карточке');
  assert.strictEqual(full.turnL2ModelLine(),
    'L2: api.example / test-model-8b · слот запроса: основной ответ '
    + '(direct.primary) · fallback: fb-model '
    + '· отправлено max output tokens: 4 096');
  // Старая трасса (поля `slot` нет) — «слот не зафиксирован», и чужой слот
  // L2 в строку L1 не подставляется.
  const oldL1 = Object.assign({}, m, { turnDiag: {
    context: { l1: { model: 'test-model-8b', fallback: 'fb-model' } },
    selection: { budget: { slot: 'direct.primary', output_reserve: 12800 } } } });
  const oldL1Line = oldL1.turnL1ModelLine();
  assert(oldL1Line.indexOf('слот не зафиксирован') >= 0, oldL1Line);
  assert(oldL1Line.indexOf('direct.primary') < 0, oldL1Line);
  assert.strictEqual(oldL1Line,
    'L1: модель test-model-8b · слот не зафиксирован · fallback: fb-model '
    + '· запас на ответ 12 800');
  // Пустота названа словами, чужой слот L2 не подставляется в L1.
  const empty = Object.assign({}, m, { turnDiag: {} });
  assert(/^L1: модель не зафиксирована/.test(empty.turnL1ModelLine()),
    empty.turnL1ModelLine());
  assert(/^L2: модель не зафиксирована/.test(empty.turnL2ModelLine()),
    empty.turnL2ModelLine());
  const noSlot = Object.assign({}, m, { turnDiag: {
    writer: { request: { provider: 'api.example', model: 'mm' },
              completion: {} }, selection: null } });
  const noSlotLine = noSlot.turnL2ModelLine();
  assert(noSlotLine.indexOf('слот запроса') < 0, noSlotLine);
  assert(noSlotLine.indexOf('max output tokens: не зафиксировано') >= 0,
    'отправленный предел честно неизвестен: ' + noSlotLine);

  // (4) UR-20.8/UR-29.3: IANA + локальное время со смещением + UTC +
  // источник настройки + присутствие часов на стадиях — ОДНОЙ строкой.
  const clockLine = m.turnClockLine.call(Object.assign({}, m), { clock: {
    timezone: 'Europe/Moscow', as_of_utc: '2026-11-06T12:00:00+00:00',
    timezone_source: 'chat', stages: ['l1', 'tool', 'l2'] } });
  assert(clockLine.indexOf('Europe/Moscow') === 0, clockLine);
  assert(/местное время \d{2}\.\d{2} 15:00 \(\+03:00\)/.test(clockLine),
    'локальные дата/время и смещение: ' + clockLine);
  assert(clockLine.indexOf('UTC 2026-11-06T12:00:00+00:00') >= 0, clockLine);
  assert(clockLine.indexOf('часы на этапах: L1, инструменты, ответ') >= 0,
    clockLine);
  assert.strictEqual(m.turnClockLine(null), 'нет данных');
  const noStages = m.turnClockLine.call(Object.assign({}, m),
    { clock: { timezone: 'UTC' } });
  assert(noStages.indexOf('часы на этапах: не зафиксированы') >= 0, noStages);
  assert(noStages.indexOf('местное время не зафиксировано') >= 0, noStages);
})();

// ── 8. UR-20.9: служебные значения карточки — только через словари ────────
(function () {
  const start = INDEX.indexOf('data-turn-inspector');
  const end = INDEX.indexOf('</template>',
    INDEX.indexOf('data-turn-unavailable', start));
  const section = INDEX.slice(start, end);

  // (1) Карта счётчиков LLM-вызовов: каждый вид назван словом, JSON нет.
  const calls = m.turnLlmCallsLine({ planning: 1, tool: 1, final: 1,
    continuation: 0, provider_retry: 1 });
  ['планирование L1 (planning): 1', 'инструменты (tool): 1',
    'ответ Writer (final): 1', 'продолжение ответа (continuation): 0',
    'повтор у провайдера (provider_retry): 1'].forEach(function (part) {
    assert(calls.indexOf(part) >= 0, 'LLM-вызовы без подписи: ' + part
      + ' → ' + calls);
  });
  assert(calls.indexOf('{') < 0 && calls.indexOf('"') < 0,
    'карта кодов не печатается JSON-ом: ' + calls);
  // Настоящий 0 — число при подписи, а НЕ «неизвестно».
  assert(calls.indexOf('continuation): неизвестно') < 0, calls);
  // Неизвестный вид вызова — «код: …», а не голый токен.
  assert(m.turnLlmCallsLine({ mystery_call: 2 })
    .indexOf('код: mystery_call: 2') >= 0);
  // Пустая карта (старая трасса) — честная пустота, не «{}».
  assert(m.turnLlmCallsLine(null).indexOf('не зафиксированы') >= 0);
  assert(m.turnLlmCallsLine({}).indexOf('не зафиксированы') >= 0);

  // (2) Остановка хода и источник текста — подписи, неизвестное — «код: …».
  assert.strictEqual(m.turnCodeLine('stop_reason', 'l1_silent'),
    'решение L1 — промолчать (l1_silent)');
  assert.strictEqual(m.turnCodeLine('stop_reason', 'l1_react_invalid'),
    'реакция L1 недопустима — тишина (l1_react_invalid)');
  assert.strictEqual(m.turnCodeLine('stop_reason', 'mystery_stop'),
    'код: mystery_stop');
  assert.strictEqual(m.turnCodeLine('text_source', 'source_restored'),
    'исходный текст вместо правки (форма не сохранена) (source_restored)');
  assert.strictEqual(m.turnCodeLine('text_source', 'weird_source'),
    'код: weird_source');

  // (3) Находки проверок: код form-гарда расшифрован, нули не выдаются за
  // находку и не печатаются сырым map.
  const checks = m.turnChecksLine({ form_guard: 'form_guard_leak_blocked',
    protected_facts_mismatch: false, needs_clarification: false,
    numeric_mismatch: 0, cliche_observed: 2, format_observed: 0 });
  assert(checks.indexOf('форма ответа: служебная разметка в тексте — правка '
    + 'заблокирована (form_guard_leak_blocked)') >= 0, checks);
  assert(checks.indexOf('замечены клише: 2') >= 0, checks);
  assert(checks.indexOf('{') < 0 && checks.indexOf('"') < 0,
    'находки не печатаются JSON-ом: ' + checks);
  assert(checks.indexOf('numeric_mismatch') < 0
    && checks.indexOf('format_observed') < 0,
    'нулевые находки не печатаются сырыми ключами: ' + checks);
  assert.strictEqual(m.turnChecksLine({ format_observed: 0 }), 'находок нет');
  assert.strictEqual(m.turnChecksLine(null), NO_DATA);
  assert(m.turnChecksLine({ form_guard: 'mystery_guard' })
    .indexOf('код: mystery_guard') >= 0, 'неизвестный код form-гарда');

  // (4) Инструмент и его ошибка: имя и код — словами.
  const tool = m.turnToolLine({ tool: 'execute_web_search', status: 'timeout',
    error: 'search_timeout', refs: 3, out_chars: 800 });
  assert(tool.indexOf('поиск в интернете (execute_web_search)') === 0, tool);
  assert(tool.indexOf('источник не ответил вовремя (search_timeout)') >= 0,
    tool);
  assert(tool.indexOf('истекло время (timeout)') >= 0, tool);
  const unknownTool = m.turnToolLine({ tool: 'mystery_tool', status: 'ok' });
  assert(unknownTool.indexOf('код: mystery_tool') === 0, unknownTool);
  assert(m.turnToolLine({ tool: 'fact_check', status: 'denied',
    error: 'chain_call_limit' }).indexOf('вызов запрещён гвардом (denied)')
    >= 0, 'статус denied не остаётся сырым кодом');

  // (5) Причина отказа Writer'а.
  assert.strictEqual(m.turnCodeLine('refused_reason', 'unfinished_answer'),
    'ответ остался незавершённым (unfinished_answer)');
  assert.strictEqual(m.turnCodeLine('refused_reason', 'empty_final'),
    'пустой текст после правок (empty_final)');
  assert.strictEqual(m.turnCodeLine('refused_reason', 'odd_reason'),
    'код: odd_reason');

  // (6) Разметка: ни одного JSON.stringify служебного значения в карточке.
  ['JSON.stringify(turnDiag.context.llm_calls',
    'JSON.stringify(turnDiag.writer.completion.checks'].forEach(function (raw) {
    assert(section.indexOf(raw) < 0, 'служебное значение печатается как есть: '
      + raw);
  });
  assert(section.indexOf('turnLlmCallsLine(') >= 0);
  assert(section.indexOf('turnChecksLine(') >= 0);
  assert(/turnCodeLine\(\s*'stop_reason'/.test(section),
    'stop_reason идёт через словарь');
  assert(/turnCodeLine\(\s*'text_source'/.test(section),
    'text_source идёт через словарь');
  assert(/turnCodeLine\(\s*'refused_reason'/.test(section),
    'refused_reason идёт через словарь');
  assert(section.indexOf('turnToolLine(t)') >= 0, 'строка инструмента на месте');

  // (7) Одна отрендеренная трасса: все ранее «голые» значения читаемы.
  const trace = {
    context: {
      llm_calls: { planning: 1, tool: 1, final: 1, continuation: 0,
        provider_retry: 1 },
      stop_reason: 'l1_silent',
      tools: [{ tool: 'execute_web_search', status: 'timeout',
        error: 'search_timeout', refs: 3 }],
    },
    writer: { completion: { text_source: 'source_restored',
      refused: true, refused_reason: 'unfinished_answer',
      checks: { form_guard: 'form_guard_leak_blocked', numeric_mismatch: 0 } } },
  };
  const rendered = [
    m.turnLlmCallsLine(trace.context.llm_calls),
    'Ход остановлен: ' + m.turnCodeLine('stop_reason',
      trace.context.stop_reason),
    m.turnToolLine(trace.context.tools[0]),
    'Текст: ' + m.turnCodeLine('text_source',
      trace.writer.completion.text_source),
    'Находки проверок: ' + m.turnChecksLine(trace.writer.completion.checks),
    'Честный отказ: ' + m.turnCodeLine('refused_reason',
      trace.writer.completion.refused_reason),
  ];
  ['l1_silent', 'source_restored', 'execute_web_search', 'planning',
    'form_guard_leak_blocked', 'search_timeout',
    'unfinished_answer'].forEach(function (code) {
    const line = rendered.filter(function (l) { return l.indexOf(code) >= 0; });
    assert(line.length === 1, 'код не отрендерен: ' + code);
    const before = line[0].slice(0, line[0].indexOf(code));
    assert(/\(\s*$/.test(before), 'код ' + code + ' без подписи: ' + line[0]);
  });
  rendered.forEach(function (line) {
    assert(line.indexOf('{') < 0 && line.indexOf('"') < 0,
      'отрендеренная строка не должна быть JSON-ом: ' + line);
  });
  // Неизвестная операция доставки — по-прежнему «код: …», не голый токен.
  assert(m.turnOpLine({ op: 'mystery_op', changed: false })
    .indexOf('код: mystery_op') === 0, 'неизвестная операция без подписи');
  // `pass`-правило по-прежнему не выдаёт себя за применённое.
  assert(m.turnRuleLine({ rule_id: 'q', kind: 'quotation_marks',
    status: 'pass' }).indexOf('сработало') < 0);
  assert(m.turnRuleLine({ rule_id: 'q', kind: 'quotation_marks',
    status: 'pass' }).indexOf('нарушений нет') >= 0);
})();

console.log('UR-F-STEP3-OK');
