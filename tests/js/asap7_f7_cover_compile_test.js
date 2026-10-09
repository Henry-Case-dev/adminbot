'use strict';
/* ASAP 7 F7 (§9.2–§9.4, §22 п.15) — «Фактическая сборка промпта»: РЕАЛЬНЫЙ
 * JS-тест (не grep) по образцу asap7_f8_cover_prompts_test.js.
 *
 * Проверяем поведение, а не только строки:
 *   1) coverCompilePreview ходит на POST /api/cover/preview-compile с draft
 *      snapshot'ом редактора и выбранным контекстом; ответ сервера
 *      сохраняется КАК ЕСТЬ (frontend промпт не пересобирает);
 *   2) exact final — только у status ok (честный placeholder без
 *      фейкового «итогового промпта»);
 *   3) budget/reason хелперы — честные тексты (preview context not
 *      selected, unknown limit, резерв);
 *   4) ошибка сети — message, результата нет (ничего не рисуем);
 *   5) index.html: блок в редакторе стиля, гейт coverStyles.isAdmin,
 *      exact-текст биндится на server-значения; copy-кнопки; R17 — нет
 *      секретов в зоне.
 *
 * Запуск: node tests/js/asap7_f7_cover_compile_test.js
 *         → ASAP7-F7-COVER-COMPILE-OK
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
global.window = { location: { hash: '' }, addEventListener() {}, Telegram: null };
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, focus() {}, select() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  execCommand() { return true; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
Object.defineProperty(global, 'navigator', {
  value: { clipboard: { writeText: async function () {} } },
  configurable: true,
});
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
assert(captured, 'Vue.createApp должен быть вызван');
const methods = captured.methods;

// (1) loader: POST на server compiler, ответ как есть.
function compileCtx(response, fail) {
  const calls = [];
  const c = {
    coverStyles: {
      compileBusy: false,
      compileChatId: -100777,
      compile: { result: null, message: '' },
      current: {
        profile_id: 'csp_f7',
        instruction: 'COMIC-DRAFT-INSTRUCTION',
        pipeline_mode: 'generate_then_edit',
        counter_enabled: false,
        next_issue_number: 2,
        counter_format: 'ВЫПУСК {counter}',
        model_mode: 'default',
        connection_id: null,
        model_id: null,
      },
    },
    coverStyleDraftSnapshot: methods.coverStyleDraftSnapshot,
    coverStyleNextNumber: methods.coverStyleNextNumber,
    api: async function (url, opts) {
      calls.push({ url: url, opts: opts || {} });
      if (fail) throw { message: 'network down' };
      return response;
    },
  };
  return { c: c, calls: calls };
}

const OK_RESULT = {
  status: 'ok',
  reason: '',
  context: { test_id: 'f7prev1', chat_id: -100777,
             source: 'summary_test_run' },
  style_source: 'draft_instruction',
  manifest: {
    operation: 'base', route: 'preview_compile',
    resolved_limit: 1000, limit_unit: 'chars',
    limit_source: 'assembly_cap',
    final_prompt: 'SERVER-COMPILED-STORY SERVER-COMPILED-CTX '
      + 'COMIC-DRAFT-INSTRUCTION',
    final_chars: 62, prompt_hash: 'a'.repeat(16),
    components: [
      { key: 'STORY_SCENE', status: 'kept', reason: '',
        original_text: 'SERVER-COMPILED-STORY', sent_text: 'SERVER-COMPILED-STORY',
        original_chars: 20, sent_chars: 20 },
      { key: 'SUMMARY_CONTEXT', status: 'kept', reason: '',
        original_text: 'SERVER-COMPILED-CTX', sent_text: 'SERVER-COMPILED-CTX',
        original_chars: 19, sent_chars: 19 },
      { key: 'BASE_STYLE', status: 'kept', reason: '',
        original_text: 'COMIC-DRAFT-INSTRUCTION',
        sent_text: 'COMIC-DRAFT-INSTRUCTION',
        original_chars: 23, sent_chars: 23 },
    ],
  },
  // единая форма breakdown'а: верхнеуровневые components (§9.3)
  components: [
    { key: 'STORY_SCENE', status: 'kept', reason: '',
      original_text: 'SERVER-COMPILED-STORY', sent_text: 'SERVER-COMPILED-STORY',
      original_chars: 20, sent_chars: 20 },
    { key: 'SUMMARY_CONTEXT', status: 'kept', reason: '',
      original_text: 'SERVER-COMPILED-CTX', sent_text: 'SERVER-COMPILED-CTX',
      original_chars: 19, sent_chars: 19 },
    { key: 'BASE_STYLE', status: 'kept', reason: '',
      original_text: 'COMIC-DRAFT-INSTRUCTION',
      sent_text: 'COMIC-DRAFT-INSTRUCTION',
      original_chars: 23, sent_chars: 23 },
  ],
  final_prompt: 'SERVER-COMPILED-STORY SERVER-COMPILED-CTX '
    + 'COMIC-DRAFT-INSTRUCTION',
  budget: {
    resolved_limit: 1000, limit_unit: 'chars',
    limit_source: 'assembly_cap', limit_known: false,
    compile_cap_chars: 1000, used_chars: 62, remaining_chars: 938,
    reserved: { story_min: 160, context_max: 400 },
  },
};

(async function () {
  // (1) запрос + as-is сохранение ответа
  let env = compileCtx(OK_RESULT);
  await methods.coverCompilePreview.call(env.c);
  assert.strictEqual(env.calls.length, 1, '1: один запрос');
  assert.strictEqual(env.calls[0].url, '/api/cover/preview-compile',
    '1: url preview-compile');
  assert.strictEqual(env.calls[0].opts.method, 'POST', '1: POST');
  const sentBody = JSON.parse(env.calls[0].opts.body);
  assert.strictEqual(sentBody.profile_id, 'csp_f7', '1: profile_id');
  assert.strictEqual(sentBody.draft.instruction,
    'COMIC-DRAFT-INSTRUCTION', '1: draft snapshot редактора');
  assert.deepStrictEqual(sentBody.context, { chat_id: -100777 },
    '1: выбранный test-context');
  assert.strictEqual(env.c.coverStyles.compile.result, OK_RESULT,
    '1: ответ сервера сохранён КАК ЕСТЬ (server-compiled)');
  assert.strictEqual(env.c.coverStyles.compileBusy, false, '1: busy снят');

  // контекст не выбран → context: null (честный placeholder сервера)
  env = compileCtx(OK_RESULT);
  env.c.coverStyles.compileChatId = 0;
  await methods.coverCompilePreview.call(env.c);
  assert.strictEqual(JSON.parse(env.calls[0].opts.body).context, null,
    '1: без контекста — context:null (§9.4)');

  // (2) exact final — только status ok; честный placeholder (§9.4) не
  //     рисует фейковый «итоговый промпт».
  const placeholder = {
    status: 'no_context', reason: 'not_selected',
    message: 'Test-контекст не выбран…',
    style_source: 'draft_instruction',
    final_prompt: null,
    components: [
      { key: 'STORY_SCENE', status: 'omitted',
        reason: 'preview_context_not_selected',
        original_text: '', sent_text: '', original_chars: 0, sent_chars: 0 },
      { key: 'SUMMARY_CONTEXT', status: 'omitted',
        reason: 'preview_context_not_selected',
        original_text: '', sent_text: '', original_chars: 0, sent_chars: 0 },
      { key: 'BASE_STYLE', status: 'kept', reason: '',
        original_text: 'COMIC-DRAFT-INSTRUCTION',
        sent_text: 'COMIC-DRAFT-INSTRUCTION',
        original_chars: 23, sent_chars: 23 },
    ],
    budget: OK_RESULT.budget,
  };
  env.c.coverStyles.compile.result = placeholder;
  assert.strictEqual(
    methods.coverCompileFinalText.call(env.c), '',
    '2: placeholder без фейкового финального промпта');
  env.c.coverStyles.compile.result = OK_RESULT;
  assert.strictEqual(methods.coverCompileFinalText.call(env.c),
    OK_RESULT.manifest.final_prompt, '2: ok → exact server text');
  const noFinal = JSON.parse(JSON.stringify(OK_RESULT));
  noFinal.status = 'no_context';
  noFinal.manifest = null;
  env.c.coverStyles.compile.result = noFinal;
  assert.strictEqual(methods.coverCompileFinalText.call(env.c), '',
    '2: no_context → пусто даже при наличии manifest');
  env.c.coverStyles.compile.result = OK_RESULT;
  assert.strictEqual(methods.coverCompileFinalText.call(env.c),
    OK_RESULT.manifest.final_prompt, '2: ok → exact server text');

  // (3) reason/budget хелперы
  assert.strictEqual(methods.coverCompileReasonText.call(
    env.c, { reason: 'preview_context_not_selected' }),
    'preview context not selected', '3: §9.4 фраза');
  assert.strictEqual(methods.coverCompileReasonText.call(
    env.c, { reason: '' }), '—', '3: пустая причина');
  env.c.coverStyles.compile.result = OK_RESULT;
  const budgetOk = methods.coverCompileBudgetText.call(env.c);
  assert.ok(budgetOk.indexOf('Лимит компиляции: 1000 симв.') >= 0
    && budgetOk.indexOf('Использовано: 62') >= 0
    && budgetOk.indexOf('Осталось: 938') >= 0
    && budgetOk.indexOf('Резерв: сцена ≥160') >= 0,
    '3: бюджет ok: ' + budgetOk);
  assert.ok(budgetOk.indexOf('Лимит провайдера неизвестен') >= 0,
    '3: unknown limit честно назван');
  const known = JSON.parse(JSON.stringify(OK_RESULT));
  known.budget.limit_known = true;
  known.budget.resolved_limit = 3800;
  known.budget.limit_unit = 'tokens';
  known.budget.limit_source = 'capability_registry';
  env.c.coverStyles.compile.result = known;
  const budgetKnown = methods.coverCompileBudgetText.call(env.c);
  assert.ok(budgetKnown.indexOf('Лимит провайдера: 3800 токенов '
    + '(capability_registry)') >= 0,
    '3: known limit с единицей и источником: ' + budgetKnown);

  // (4) ошибка сети — message, результата нет
  env = compileCtx(null, true);
  await methods.coverCompilePreview.call(env.c);
  assert.strictEqual(env.c.coverStyles.compile.result, null,
    '4: результата нет');
  assert.strictEqual(env.c.coverStyles.compile.message, 'network down',
    '4: сообщение об ошибке показано');

  // (5) index.html: зона compile в редакторе стиля + гейт admin +
  //     exact-бинды + copy; R17 — нет секретов.
  const INDEX = fs.readFileSync(
    path.join(ROOT, 'web', 'index.html'), 'utf8');
  const startG = INDEX.indexOf('<!-- ASAP 7 F7');
  assert.ok(startG > 0, '5: блок data-cover-compile найден');
  const endG = INDEX.indexOf('data-cover-style-refs');
  assert.ok(endG > startG, '5: блок внутри редактора (до референсов)');
  const zoneHtml = INDEX.slice(startG, endG);
  assert.ok(zoneHtml.indexOf('coverStyles.isAdmin') >= 0,
    '5: гейт global admin');
  assert.ok(zoneHtml.indexOf('Фактическая сборка промпта') >= 0,
    '5: заголовок §9.3');
  assert.ok(zoneHtml.indexOf('data-cover-compile-final-text') > 0,
    '5: exact compiled text рендерится');
  assert.ok(zoneHtml.indexOf("@click=\"copyText(coverCompileFinalText())\"") > 0,
    '5: copy exact-текста');
  assert.ok(zoneHtml.indexOf('data-cover-compile-table') > 0
    && zoneHtml.indexOf('data-cover-compile-texts') > 0,
    '5: таблица компонент + раскрываемые тексты (§9.3)');
  // breakdown читает ВЕРХНЕУРОВНЕВЫЕ components (единая форма обоих
  // состояний), а не manifest.components
  assert.ok(
    zoneHtml.indexOf('coverStyles.compile.result.components') > 0,
    '5: таблица из result.components (server-контракт)');
  ['api_key', 'apikey', 'secret_value', 'credential_value'].forEach(
    function (bad) {
      assert.ok(zoneHtml.toLowerCase().indexOf(bad) < 0, '5: нет ' + bad);
    });
  // Test Style: полный exact compiled prompt в манифесте job'а
  const mExact = INDEX.indexOf('data-cover-manifest-exact');
  assert.ok(mExact > 0, '5: exact-блок манифеста Test Style');
  const mZone = INDEX.slice(mExact, mExact + 1600);
  assert.ok(mZone.indexOf(
    'coverStyles.preview.prompt_manifest.final_prompt') > 0,
    '5: exact prompt из server-манифеста job\'а');
  assert.ok(mZone.indexOf('data-cover-manifest-final-copy') > 0,
    '5: copy кнопка exact prompt');

  console.log('ASAP7-F7-COVER-COMPILE-OK');
})().catch(function (e) { console.error(e); process.exit(1); });
