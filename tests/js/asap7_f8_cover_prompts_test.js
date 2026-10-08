'use strict';
/* ASAP 7 F8 (§2.5/§10) — Run Inspector «Фактический промпт»: РЕАЛЬНЫЙ
 * JS-тест (не grep) по образцу asap41_zone_g_inspector_test.js.
 *
 * Проверяем поведение, а не только строки:
 *   1) computed'ы существуют и читаются шаблоном как свойства;
 *   2) рендер-гейт: блок скрыт БЕЗ данных cover_prompts И у не-глобал
 *      админа (isGlobalAdminEffective=false), виден только при admin+данных;
 *   3) группы Base/Style: exact-текст попыток, chars, limit/limit_source,
 *      meta (provider/model/route), hash;
 *   4) loader: drill-down запрашивает include_prompt=true ТОЛЬКО у
 *      global admin; ответ без параметра не создаёт cover_prompts;
 *   5) R17: в index.html зоне Run Inspector нет секретов.
 *
 * Запуск: node tests/js/asap7_f8_cover_prompts_test.js
 *         → ASAP7-F8-COVER-PROMPTS-OK
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
const computed = captured.computed;

// (1) computed'ы существуют — читаются шаблоном как свойства.
['pipelineCoverPrompts', 'pipelineCoverPromptsVisible',
 'pipelineCoverPromptGroups'].forEach(function (name) {
  assert.strictEqual(typeof computed[name], 'function', '1: computed ' + name);
});
assert.strictEqual(typeof methods.pipelineCoverPromptMeta, 'function',
  '1: helper pipelineCoverPromptMeta');
assert.strictEqual(typeof methods.pipelineCoverAttemptReason, 'function',
  '1: helper pipelineCoverAttemptReason');

const COVER_PROMPTS = {
  base: {
    schema: 'cover_prompt_manifest/v1', operation: 'base',
    provider: 'nano-gpt.com', model: 'painter-x', route: 'image_generation',
    resolved_limit: 1000, limit_unit: 'chars', limit_source: 'assembly_cap',
    attempts: [{ attempt: 1, prompt: 'BASE-EXACT-PROMPT', outcome: 'ok',
                 reason: '' }],
    final_prompt: 'BASE-EXACT-PROMPT', final_chars: 17,
    prompt_hash: 'a'.repeat(16),
  },
  style: {
    schema: 'cover_prompt_manifest/v1', operation: 'edit',
    provider: 'nano-gpt.com', model: 'painter-x', route: 'image_api',
    resolved_limit: 3800, limit_unit: '3800:chars',
    limit_source: 'capability_registry',
    attempts: [
      { attempt: 1, prompt: 'STYLE-ATTEMPT-1', outcome: 'retry_superseded',
        reason: 'prompt_limit_unknown' },
      { attempt: 2, prompt: 'STYLE-ATTEMPT-2', outcome: 'ok', reason: '' },
    ],
    final_prompt: 'STYLE-ATTEMPT-2', final_chars: 14,
    prompt_hash: 'b'.repeat(16),
  },
};

function ctx(coverPrompts, isAdmin) {
  const raw = {
    pipelineData: coverPrompts === undefined
      ? null : { cover_prompts: coverPrompts },
    isGlobalAdminEffective: isAdmin,
  };
  // computed-зависимости как в рантайме (развёрнутые значения + хелперы)
  raw.pipelineCoverPrompts = computed.pipelineCoverPrompts.call(raw);
  raw.pipelineCoverPromptMeta = methods.pipelineCoverPromptMeta;
  return raw;
}

// (2) рендер-гейт: fail-closed по умолчанию.
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(ctx(null, true)),
  false, '2: нет данных → блок скрыт (даже у админа)');
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(
  ctx(COVER_PROMPTS, false)), false, '2: не-глобал → блок скрыт');
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(
  ctx(COVER_PROMPTS, true)), true, '2: admin + данные → блок виден');
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(
  ctx({ base: null, style: null }, true)), false,
  '2: честная пустота (обе джобы нет) → блок скрыт');

// (3) группы: exact-тексты обеих попыток Style + Base, лимиты, meta.
const groups = computed.pipelineCoverPromptGroups.call(
  ctx(COVER_PROMPTS, true));
assert.strictEqual(groups.length, 2, '3: две группы (base+style)');
const base = groups[0], style = groups[1];
assert.strictEqual(base.key, 'base');
assert.strictEqual(base.final_prompt, 'BASE-EXACT-PROMPT');
assert.strictEqual(base.attempts.length, 1);
assert.strictEqual(base.attempts[0].prompt, 'BASE-EXACT-PROMPT');
assert.strictEqual(base.limit_label, '1000 chars');
assert.ok(base.meta.indexOf('nano-gpt.com') >= 0 && base.meta.indexOf('painter-x') >= 0,
  '3: meta provider/model');
assert.strictEqual(style.key, 'style');
assert.strictEqual(style.attempts.length, 2, '3: обе попытки Style');
assert.strictEqual(style.attempts[0].prompt, 'STYLE-ATTEMPT-1');
assert.strictEqual(style.attempts[0].outcome, 'retry_superseded');
assert.strictEqual(style.attempts[1].prompt, 'STYLE-ATTEMPT-2');
assert.strictEqual(style.final_prompt, 'STYLE-ATTEMPT-2');
assert.strictEqual(style.limit_label, '3800 chars');
assert.strictEqual(style.limit_source, 'capability_registry');
assert.strictEqual(methods.pipelineCoverAttemptReason(style.attempts[0]),
  'retry_superseded — prompt_limit_unknown');

// (4) loader: include_prompt=true только у global admin.
function loaderCtx(isAdmin, inspector, detail) {
  const urls = [];
  const c = {
    pipelineBusy: false,
    pipelineMode: 'latest',
    pipelineSelectedRunId: 'run-f8',
    pipelineData: null,
    isGlobalAdminEffective: isAdmin,
    api: async function (url) {
      urls.push(url);
      if (url.indexOf('/inspector') >= 0) return inspector;
      return detail;
    },
  };
  return { c: c, urls: urls };
}

(async function () {
  let l = loaderCtx(true, { run: { run_id: 'r' } },
                    { run: { run_id: 'run-f8' }, cover_prompts: COVER_PROMPTS });
  await methods.loadPipelineInspector.call(l.c);
  assert.ok(l.urls.some(function (u) {
    return u.indexOf('/api/analytics/pipeline/runs/run-f8'
      + '?include_prompt=true') >= 0;
  }), '4: global admin → include_prompt=true');
  assert.strictEqual(l.c.pipelineData.cover_prompts, COVER_PROMPTS,
    '4: cover_prompts сохранены для рендера');

  l = loaderCtx(false, { run: { run_id: 'r' } },
                { run: { run_id: 'run-f8' } });
  await methods.loadPipelineInspector.call(l.c);
  assert.ok(l.urls.every(function (u) {
    return u.indexOf('include_prompt') < 0;
  }), '4: не-глобал → запрос БЕЗ include_prompt');
  assert.strictEqual(l.c.pipelineData.cover_prompts, null,
    '4: cover_prompts нет (прежний safe-ответ)');

  // (5) R17: в зоне Run Inspector нет секретов.
  const INDEX = fs.readFileSync(
    path.join(ROOT, 'web', 'index.html'), 'utf8');
  const startG = INDEX.indexOf('pipeline-inspector-block');
  const endG = INDEX.indexOf('embeddings-inspector-block');
  assert.ok(startG > 0 && endG > startG, '5: зона Run Inspector найдена');
  const zoneHtml = INDEX.slice(startG, endG);
  ['api_key', 'apikey', 'secret_value', 'credential_value'].forEach(
    function (bad) {
      assert.ok(zoneHtml.toLowerCase().indexOf(bad) < 0, '5: нет ' + bad);
    });
  // новый блок внутри зоны (не вне её)
  assert.ok(zoneHtml.indexOf('pipeline-cover-prompts') > 0,
    '5: блок в зоне Run Inspector');

  console.log('ASAP7-F8-COVER-PROMPTS-OK');
})().catch(function (e) { console.error(e); process.exit(1); });
