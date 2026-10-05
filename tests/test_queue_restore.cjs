// Execute production component bodies/callbacks; replace only their JSX return.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const Babel = require('../gurunote/webui/vendor/babel.min.js');
const root = path.join(__dirname, '../gurunote/webui/components');
function compile(name, names) {
  const source = fs.readFileSync(path.join(root, name + '.jsx'), 'utf8');
  // The regression also executes the pre-fix callbacks, which lack this new helper.
  const exposed = names.filter(n => n !== 'restoreQueueResult' || source.includes('const restoreQueueResult ='));
  return Babel.transform(source, {
    presets: ['react'], plugins: [({ types: t }) => ({ visitor: {
      FunctionDeclaration(p) {
        if (p.node.id.name !== name) return;
        const body = p.node.body.body;
        const ret = body.findLast(x => x.type === 'ReturnStatement');
        ret.argument = t.objectExpression(exposed.map(n => t.objectProperty(t.identifier(n), t.identifier(n), false, true)));
      }
    } })]
  }).code;
}
const appCode = compile('App', ['acceptQueueSnapshot', 'mainSession', 'updateMainSession', 'previewRevisionRef', 'restoreQueueResult']);
const mainCode = compile('MainScreen', ['viewQueueItem']);
function fixture() {
  const slots = [], effects = [], listeners = {}, requests = [], pending = [];
  let cursor = 0, delayed = false;
  const React = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => {
        const apply = () => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; };
        if (delayed) pending.push(apply); else apply();
      }];
    },
    useRef(initial) { const i = cursor++; return slots[i] || (slots[i] = { current: initial }); },
    useCallback: fn => fn,
    useEffect: fn => effects.push(fn),
  };
  const window = { bus: {
    addEventListener: (name, fn) => { listeners[name] = fn; }, removeEventListener() {},
  }, pywebview: { api: {
    get_pipeline_queue_result: id => new Promise(resolve => requests.push({ id, resolve })),
    get_settings: async () => ({ ok: false }),
  } } };
  const context = vm.createContext({ React, window, console });
  vm.runInContext(appCode, context);
  let app = vm.runInContext('App()', context);
  effects.find(fn => fn.toString().includes("addEventListener('queue_changed'"))();
  const mainRefs = []; let mainCursor = 0;
  const mainContext = vm.createContext({ window, console, React: { ...React,
    useRef: initial => mainRefs[mainCursor] || (mainRefs[mainCursor++] = { current: initial }),
  } });
  vm.runInContext(mainCode, mainContext);
  function state() { cursor = 0; app = vm.runInContext('App()', context); return app.mainSession; }
  return {
    requests, state,
    snapshot: q => app.acceptQueueSnapshot(q),
    emit: (name, data) => listeners[name]({ detail: data }),
    patch: p => app.updateMainSession(p),
    delay: () => { delayed = true; },
    flush: () => { delayed = false; while (pending.length) pending.shift()(); },
    view(id) {
      mainCursor = 0;
      mainContext.props = { mainSession: state(), updateMainSession: app.updateMainSession, restoreQueueResult: app.restoreQueueResult };
      return vm.runInContext('MainScreen(props).viewQueueItem', mainContext)(id);
    },
  };
}
const queue = (job = 'a', version = 1, has_result = true) => ({ version, active_queue_id: job, items: [{ queue_id: job, job_id: job, status: 'running', has_result }] });
const partial = (revision, job = 'a') => ({ job_id: job, ok: true, is_partial: true, revision, text: `partial ${revision}` });
const final = (job = 'a') => ({ job_id: job, ok: true, is_partial: false, text: 'final' });
const settle = async (f, i, value) => { f.requests[i].resolve(value); await Promise.resolve(); await Promise.resolve(); };
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
test('older hydration cannot overwrite newer partial or lower revision', async () => {
  const f = fixture(); f.snapshot(queue()); f.emit('partial_result', partial(2));
  await settle(f, 0, partial(1)); assert.equal(f.state().result.revision, 2);
  f.emit('partial_result', partial(2)); assert.equal(f.state().result.revision, 2);
});
test('partial hydration cannot overwrite final result', async () => {
  const f = fixture(); f.snapshot(queue()); f.emit('result', final());
  await settle(f, 0, partial(1)); assert.equal(f.state().result.is_partial, false);
});
test('live selection reply cannot cross active job switch', async () => {
  const f = fixture(); f.snapshot(queue('a', 1, false)); f.view(null);
  f.snapshot(queue('b', 2, false)); await settle(f, 0, partial(1));
  assert.equal(f.state().result, null);
});
test('obsolete request cannot overwrite a later selection of the same item', async () => {
  const f = fixture(); f.snapshot(queue('a', 1, false)); f.view('old'); f.view('other'); f.view('old');
  await settle(f, 2, { ...final('old'), text: 'new selection' });
  await settle(f, 0, { ...final('old'), text: 'obsolete' });
  assert.equal(f.state().result.text, 'new selection');
});
test('equal revision rehydrate restores live partial after historical reading', async () => {
  const f = fixture(); f.snapshot(queue()); f.patch({ viewingQueueId: 'old', result: final('old') });
  f.emit('partial_result', partial(2)); f.view(null);
  await settle(f, 1, partial(2)); assert.equal(f.state().result.revision, 2);
});
test('equal final rehydrate restores live result after historical reading', async () => {
  const f = fixture(); f.snapshot(queue()); f.emit('result', final());
  f.patch({ viewingQueueId: 'old', result: final('old') }); f.view(null);
  await settle(f, 1, final()); assert.equal(f.state().result.job_id, 'a');
});
test('intentional historical selection survives active job changes', async () => {
  const f = fixture(); f.snapshot(queue('a', 1, false)); f.view('old');
  f.snapshot(queue('b', 2, false)); await settle(f, 0, final('old'));
  f.snapshot(queue('c', 3, false)); assert.equal(f.state().result.job_id, 'old');
});
test('guards execute when React applies the state updater', async () => {
  const f = fixture(); f.snapshot(queue()); f.delay(); await settle(f, 0, partial(1));
  f.emit('partial_result', partial(2)); f.flush(); assert.equal(f.state().result.revision, 2);
});
test('live selection cannot replace a pushed final with a partial', async () => {
  const f = fixture(); f.snapshot(queue('a', 1, false)); f.view(null);
  f.emit('result', final()); await settle(f, 0, partial(3));
  assert.equal(f.state().result.is_partial, false);
});
test('automatic hydration is invalidated by deliberate result selection', async () => {
  const f = fixture(); f.snapshot(queue()); f.view('old'); f.view(null);
  await settle(f, 2, partial(2)); await settle(f, 0, partial(1));
  assert.equal(f.state().result.revision, 2);
});
test('automatic hydration accepts equal revision and equal final', async () => {
  const f = fixture(); f.snapshot(queue()); f.emit('partial_result', partial(2));
  await settle(f, 0, { ...partial(2), text: 'equal restored' });
  assert.equal(f.state().result.text, 'equal restored');
  const g = fixture(); g.snapshot(queue()); g.emit('result', final());
  await settle(g, 0, { ...final(), text: 'equal final restored' });
  assert.equal(g.state().result.text, 'equal final restored');
});
test('empty live result clears the previously selected historical result', async () => {
  const f = fixture(); f.snapshot(queue('a', 1, false));
  f.patch({ viewingQueueId: 'old', result: final('old') }); f.view(null);
  await settle(f, 0, null); assert.equal(f.state().result, null);
});
(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log('PASS', name); }
    catch (e) { failed++; console.error('FAIL', name, e.message); }
  }
  console.log(`${tests.length - failed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})();
