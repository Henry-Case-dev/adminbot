'use strict';
/* ASAP 7 F8 (§2.5/§10) + ASAP 8 F4 (§4.1–§4.3) — Run Inspector
 * «Фактический промпт»: РЕАЛЬНЫЙ JS-тест (не grep) по образцу
 * asap41_zone_g_inspector_test.js.
 *
 * Проверяем поведение, а не только строки:
 *   1) computed'ы существуют и читаются шаблоном как свойства;
 *   2) рендер-гейт F4: блок у global admin ВИДЕН ВСЕГДА (нет манифестов →
 *      явная причина, C6/§28.8), у не-глобала скрыт;
 *   3) группы Base/Style: exact-текст попыток, chars, limit/limit_source,
 *      meta (provider/model/route), hash;
 *   4) loader: drill-down запрашивает include_prompt=true ТОЛЬКО у
 *      global admin; F4 latest-режим (пустой выбор) — прямой вызов
 *      /api/analytics/pipeline/runs/latest?include_prompt=true (§28.7,
 *      без extra-click); не-глобал latest НЕ вызывает;
 *   5) R17: в index.html зоне Run Inspector нет секретов;
 *   6) F4-хвосты: coverManifestSourceLabel знает CONTENT_PRESERVATION;
 *      статус-RU карта полная (C6-коды); promptStylePreviewCompile (C7)
 *      шлёт mode + draft.instruction в preview-compile.
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
 'pipelineCoverPromptGroups', 'pipelineCoverPromptsStatus',
 'pipelineCoverPromptMissingRows'].forEach(function (name) {
  assert.strictEqual(typeof computed[name], 'function', '1: computed ' + name);
});
assert.strictEqual(typeof methods.pipelineCoverPromptMeta, 'function',
  '1: helper pipelineCoverPromptMeta');
assert.strictEqual(typeof methods.pipelineCoverAttemptReason, 'function',
  '1: helper pipelineCoverAttemptReason');
assert.strictEqual(typeof methods.pipelineCoverPromptStatusRu, 'function',
  '1: helper pipelineCoverPromptStatusRu');
assert.strictEqual(typeof methods.promptStylePreviewCompile, 'function',
  '1: helper promptStylePreviewCompile (C7)');

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
  cover_prompts_status: { base: 'ok', style: 'ok' },
};

function ctx(coverPrompts, isAdmin) {
  const raw = {
    pipelineData: coverPrompts === undefined
      ? null : { cover_prompts: coverPrompts },
    isGlobalAdminEffective: isAdmin,
  };
  // computed-зависимости как в рантайме (развёрнутые значения + хелперы)
  raw.pipelineCoverPrompts = computed.pipelineCoverPrompts.call(raw);
  raw.pipelineCoverPromptsStatus =
    computed.pipelineCoverPromptsStatus.call(raw);
  raw.pipelineCoverPromptMeta = methods.pipelineCoverPromptMeta;
  raw.pipelineCoverPromptStatusRu = methods.pipelineCoverPromptStatusRu;
  return raw;
}

// (2) рендер-гейт F4: global admin → блок ВИДЕН ВСЕГДА (нет манифестов —
// явная причина вместо сокрытия, C6/§28.8); не-глобал → скрыт.
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(ctx(null, true)),
  true, '2: global admin → блок виден даже без данных (C6)');
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(
  ctx(COVER_PROMPTS, false)), false, '2: не-глобал → блок скрыт');
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(
  ctx(COVER_PROMPTS, true)), true, '2: admin + данные → блок виден');
assert.strictEqual(computed.pipelineCoverPromptsVisible.call(
  ctx({ base: null, style: null,
        cover_prompts_status: { base: 'legacy_run', style: 'legacy_run' } },
     true)), true, '2: нет манифестов → блок виден с причиной (C6/§28.8)');

// (2b) причина-строки: обе стороны missing → честные RU-тексты.
{
  const c = ctx({ base: null, style: null,
                  cover_prompts_status: { base: 'base_manifest_missing',
                                          style: 'style_job_failed' } }, true);
  const rows = computed.pipelineCoverPromptMissingRows.call(c);
  assert.strictEqual(rows.length, 2, '2b: две missing-строки');
  assert.ok(rows[0].text.indexOf('манифест Base не найден') >= 0,
    '2b: base_manifest_missing → RU');
  assert.ok(rows[1].text.indexOf('Style-джоба завершилась без манифеста') >= 0,
    '2b: style_job_failed → RU');
  // полные данные → строк нет
  const cOk = ctx(COVER_PROMPTS, true);
  assert.strictEqual(
    computed.pipelineCoverPromptMissingRows.call(cOk).length, 0,
    '2b: обе стороны ok → missing-строк нет');
  // частичный кейс: base есть, style not linked → одна строка
  const cPart = ctx({ base: COVER_PROMPTS.base, style: null,
                      cover_prompts_status: { base: 'ok',
                                              style: 'style_job_not_linked' } },
                    true);
  const rowsPart = computed.pipelineCoverPromptMissingRows.call(cPart);
  assert.strictEqual(rowsPart.length, 1, '2b: частичный кейс → одна строка');
  assert.ok(rowsPart[0].text.indexOf('Style-джоба не связана') >= 0,
    '2b: style_job_not_linked → RU');
  assert.strictEqual(methods.pipelineCoverPromptStatusRu('legacy_run'),
    'прогон до эпохи манифестов (legacy)', '2b: legacy_run → RU');
}

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

// (4) loader: include_prompt=true только у global admin; F4 latest-режим.
function loaderCtx(isAdmin, inspector, detail, latest, selected) {
  const urls = [];
  const c = {
    pipelineBusy: false,
    pipelineMode: 'latest',
    pipelineSelectedRunId: selected === undefined ? 'run-f8' : selected,
    pipelineData: null,
    isGlobalAdminEffective: isAdmin,
    api: async function (url) {
      urls.push(url);
      if (url.indexOf('/inspector') >= 0) return inspector;
      if (url.indexOf('/runs/latest') >= 0) return latest;
      return detail;
    },
  };
  return { c: c, urls: urls };
}

(async function () {
  let l = loaderCtx(true, { run: { run_id: 'r' } },
                    { run: { run_id: 'run-f8' }, cover_prompts: COVER_PROMPTS,
                      cover_prompts_status: { base: 'ok', style: 'ok' } });
  await methods.loadPipelineInspector.call(l.c);
  assert.ok(l.urls.some(function (u) {
    return u.indexOf('/api/analytics/pipeline/runs/run-f8'
      + '?include_prompt=true') >= 0;
  }), '4: global admin → include_prompt=true');
  assert.strictEqual(l.c.pipelineData.cover_prompts, COVER_PROMPTS,
    '4: cover_prompts сохранены для рендера');
  assert.deepStrictEqual(l.c.pipelineData.cover_prompts_status,
    { base: 'ok', style: 'ok' }, '4: status сохранён для рендера (C6)');

  l = loaderCtx(false, { run: { run_id: 'r' } },
                { run: { run_id: 'run-f8' } });
  await methods.loadPipelineInspector.call(l.c);
  assert.ok(l.urls.every(function (u) {
    return u.indexOf('include_prompt') < 0;
  }), '4: не-глобал → запрос БЕЗ include_prompt');
  assert.strictEqual(l.c.pipelineData.cover_prompts, null,
    '4: cover_prompts нет (прежний safe-ответ)');

  // F4 §4.1 (C5): latest-режим (пустой выбор) — прямой вызов latest
  // endpoint с include_prompt (§28.7: никакого скрытого extra-click).
  l = loaderCtx(true, { run: { run_id: 'stale' } }, null,
                { run: { run_id: 'latest-1' }, cover_prompts: COVER_PROMPTS,
                  cover_prompts_status: { base: 'ok', style: 'ok' } },
                '');
  await methods.loadPipelineInspector.call(l.c);
  assert.ok(l.urls.some(function (u) {
    return u.indexOf('/api/analytics/pipeline/runs/latest'
      + '?include_prompt=true') >= 0;
  }), '4: latest-режим, admin → вызов /runs/latest?include_prompt=true');
  assert.strictEqual(l.c.pipelineData.cover_prompts, COVER_PROMPTS,
    '4: latest cover_prompts сохранены');
  assert.strictEqual(l.c.pipelineData.run.run_id, 'latest-1',
    '4: карта прогона = latest-детал (карточка и промпты про один run)');

  // F4: не-глобал в latest-режиме НЕ вызывает /runs/latest (403 fail-closed
  // endpoint; без спама 403 в поллинге 15с).
  l = loaderCtx(false, { run: { run_id: 'r' } }, null, null, '');
  await methods.loadPipelineInspector.call(l.c);
  assert.ok(l.urls.every(function (u) {
    return u.indexOf('/runs/latest') < 0;
  }), '4: не-глобал → без вызова /runs/latest');

  // F4: latest недоступен (ошибка сети) → честная пустота, без крэша.
  l = loaderCtx(true, { run: { run_id: 'r' } }, null, null, '');
  l.c.api = async function (url) {
    l.urls.push(url);
    if (url.indexOf('/inspector') >= 0) return { run: { run_id: 'r' } };
    throw new Error('network');
  };
  await methods.loadPipelineInspector.call(l.c);
  assert.strictEqual(l.c.pipelineData.cover_prompts, null,
    '4: ошибка latest → cover_prompts нет');
  assert.strictEqual(l.c.pipelineData.run.run_id, 'r',
    '4: карта прогона из inspector сохранена');

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
  assert.ok(zoneHtml.indexOf('pipelineCoverPromptMissingRows') > 0,
    '5: reason-строки в зоне Run Inspector (C6)');

  // (6) F4-хвост a: coverManifestSourceLabel знает CONTENT_PRESERVATION.
  assert.strictEqual(methods.coverManifestSourceLabel(
    { key: 'CONTENT_PRESERVATION', source: 'code' }),
    'Инвариант сохранения сюжета', '6: CONTENT_PRESERVATION → RU');

  // (7) F4 C7: promptStylePreviewCompile — server compiler, mode+draft.
  const bodies = [];
  const stItem = { value: 'STYLE-DRAFT-TEXT' };
  const psc = {
    promptStylePreview: { busy: false, mode: 'style', chatId: 0,
                          result: null, message: '' },
    api: async function (url, opts) {
      bodies.push({ url: url, body: JSON.parse(opts.body) });
      return { status: 'ok', mode: 'style', final_prompt: 'X',
               components: [], budget: {} };
    },
  };
  await methods.promptStylePreviewCompile.call(psc, stItem);
  assert.strictEqual(bodies[0].url, '/api/cover/preview-compile',
    '7: POST preview-compile');
  assert.strictEqual(bodies[0].body.mode, 'style', '7: mode=style');
  assert.strictEqual(bodies[0].body.draft.instruction, 'STYLE-DRAFT-TEXT',
    '7: draft = значение редактора (exact current draft)');
  assert.strictEqual(psc.promptStylePreview.result.status, 'ok',
    '7: результат сохранён как есть (без JS-компиляции)');
  // base mode + контекст
  psc.promptStylePreview.mode = 'base';
  psc.promptStylePreview.chatId = -1001234567890;
  await methods.promptStylePreviewCompile.call(psc, stItem);
  assert.strictEqual(bodies[1].body.mode, 'base', '7: mode=base');
  assert.deepStrictEqual(bodies[1].body.context,
    { chat_id: -1001234567890 }, '7: test-контекст передаётся');

  console.log('ASAP7-F8-COVER-PROMPTS-OK');
})().catch(function (e) { console.error(e); process.exit(1); });
