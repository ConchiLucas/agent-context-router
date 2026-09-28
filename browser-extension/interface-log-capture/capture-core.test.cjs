const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Store, body, url, isInterfaceResourceType, isExcludedInterfaceUrl,
  authIdentityCandidate, confirmsAuthIdentity} = require('./capture-core.js');
function storage() {
  let data = {};
  return {get: async () => structuredClone(data), set: async values => Object.assign(data, structuredClone(values)),
    remove: async key => { delete data[key]; }};
}
const capture = {url: 'http://localhost:3000/rest/mtp/orders/save', method: 'POST', request_body: {id: 1}, capture_state: 'complete'};
test('static preloads are excluded without hiding API downloads or unknown routes', () => {
  for (const path of ['/pzh-mtp-ui', '/pzh-mtp-ui/', '/pzh-mtp-ui/assets/page-hash.css?v=1',
    '/assets/app.js', '/static/font.woff2', '/_next/static/chunks/app.js', '/assets/a%2Ecss']) {
    assert.equal(isExcludedInterfaceUrl('http://localhost:3000' + path), true, path);
  }
  for (const path of ['/rest/mtp/api/download/template.css', '/rest/mtp/assets/app.js',
    '/line-api/assets/a.svg', '/api/download/a.png', '/unknown/newQuery',
    '/report.xlsx', '/assets/query', '/my-assets/app.css']) {
    assert.equal(isExcludedInterfaceUrl('http://localhost:3000' + path), false, path);
  }
});
const ack = record => ({capture_id: record.capture.capture_id, revision: record.capture.revision, status: 'stored', match_status: 'pending'});
test('distinct identical requests are retained and restored after worker restart', async () => {
  const disk = storage(), first = new Store(disk);
  await first.put('a', capture); await first.put('b', capture);
  const second = new Store(disk); await second.ready;
  assert.equal(second.pending().length, 2);
  assert.deepEqual(second.pending().map(item => item.capture.capture_id), ['a','b']);
});
test('partial ACK and HTTP-success-without-ACK never discard unconfirmed requests', async () => {
  const store = new Store(storage());
  await store.put('a', capture); await store.put('b', capture);
  const batch = structuredClone(store.pending());
  await assert.rejects(store.acknowledge(batch, {imported_count: 2}), /逐条/);
  assert.equal(store.pending().length, 2);
  await store.acknowledge(batch, {acknowledged: [ack(batch[0])]});
  assert.deepEqual(store.pending().map(item => item.capture.capture_id), ['b']);
});
test('daily read deduplication ACK clears the queue without counting a stored row', async () => {
  const store = new Store(storage());
  await store.put('read-duplicate', capture);
  const batch = structuredClone(store.pending());
  await store.acknowledge(batch, {acknowledged: [{...ack(batch[0]), deduplicated: true}]});
  assert.equal(store.pending().length, 0);
  assert.equal(store.stats.stored, 0);
  assert.equal(store.stats.deduplicated, 1);
});
test('in-flight upload ACK cannot erase response enrichment', async () => {
  const store = new Store(storage());
  await store.put('a', {...capture, capture_state: 'started'});
  const old = structuredClone(store.pending());
  await store.put('a', {capture_state: 'complete', response_body: {ok: true}});
  await store.acknowledge(old, {acknowledged: [ack(old[0])]});
  assert.equal(store.pending()[0].capture.revision, 2);
  const next = structuredClone(store.pending());
  await store.acknowledge(next, {acknowledged: [ack(next[0])]});
  assert.equal(store.pending().length, 0);
  assert.equal(store.stats.stored, 1);
});
test('cleanup keeps unacknowledged and in-flight records', async () => {
  const store = new Store(storage());
  await store.put('pending', capture);
  await store.put('started', {...capture, capture_state: 'started'});
  await store.put('saved', capture);
  const batch = store.pending().filter(item => item.capture.capture_id !== 'pending');
  await store.acknowledge(batch, {acknowledged: batch.map(ack)});
  await store.cleanup(Date.now() + 600000);
  assert.deepEqual([...store.records.keys()], ['pending', 'started']);
});
test('quota failure is explicit and preserves existing queue', async () => {
  const store = new Store(storage(), {maxBytes: 800});
  await store.put('a', capture);
  assert.equal(await store.put('b', {...capture, request_body: 'x'.repeat(900)}), null);
  assert.equal(store.pending().length, 1);
  assert.equal(store.stats.overflow, 1);
  assert.match(store.error, /容量不足/);
});
test('concurrent identical requests never receive guessed response bodies', async () => {
  const store = new Store(storage());
  await store.put('a', capture, {tabId: 7, startedAt: 1000});
  assert.equal(store.correlate(7, capture.url, 'POST', 1001), 'a');
  await store.put('b', capture, {tabId: 7, startedAt: 1002});
  assert.equal(store.correlate(7, capture.url, 'POST', 1001), null);
});
test('credentials are removed before truncation and URLs lose userinfo', () => {
  const value = body(JSON.stringify({password: 'never-store', items: 'x'.repeat(10000)}), 100);
  assert.ok(value._truncated);
  assert.ok(!JSON.stringify(value).includes('never-store'));
  assert.ok(!url('http://user:secret@localhost:3000/a?token=never-store#private').includes('never-store'));
  assert.deepEqual(body('password=never-store&id=1'), {password:'[REDACTED]', id:'1'});
});
test('failed local write does not report a captured record', async () => {
  const disk = storage(), store = new Store(disk); await store.ready;
  disk.set = async () => {throw new Error('disk full');};
  await assert.rejects(store.put('a', capture));
  assert.equal(store.stats.captured, 0);
  assert.equal(store.pending().length, 0);
});
test('only Fetch/XHR resource types are treated as interfaces', () => {
  for (const type of ['xmlhttprequest', 'XHR', 'Fetch']) assert.equal(isInterfaceResourceType(type), true);
  for (const type of ['Document', 'Script', 'Image', 'EventSource', 'WebSocket', '', null]) {
    assert.equal(isInterfaceResourceType(type), false);
  }
});
test('SSE connect streams are excluded without hiding other SSE control APIs', () => {
  assert.equal(isExcludedInterfaceUrl('http://localhost:3000/rest/sys/api/sse/connect?businessType=taskcenter'), true);
  assert.equal(isExcludedInterfaceUrl('http://localhost:3000/api/sse/connect/'), true);
  assert.equal(isExcludedInterfaceUrl('http://localhost:3000/api/sse/disconnect'), false);
  assert.equal(isExcludedInterfaceUrl('http://localhost:3000/api/orders/connect'), false);
  assert.equal(isExcludedInterfaceUrl('not a url'), true);
});
test('login identity rules extract only the account and require the configured confirmation request', () => {
  const rules = [{
    login: {method: 'POST', pathSuffix: '/login', accountFields: ['username', 'mobile']},
    confirmations: [
      {method: 'POST', pathSuffix: '/bind-system'},
      {method: 'POST', pathSuffix: '/current-user'},
    ],
  }];
  const candidate = authIdentityCandidate('http://localhost/login', 'POST',
    JSON.stringify({username: 'superadmin', password: 'never-store', captcha: 'abcd'}), rules);
  assert.deepEqual(candidate, {ruleIndex: 0, loginAccount: 'superadmin', addressNames: []});
  assert.equal(confirmsAuthIdentity('http://localhost/current-user', 'POST', candidate, rules), true);
  assert.equal(confirmsAuthIdentity('http://localhost/bind-system', 'POST', candidate, rules), true);
  assert.equal(confirmsAuthIdentity('http://localhost/orders', 'POST', candidate, rules), false);
  assert.equal(JSON.stringify(candidate).includes('never-store'), false);
});
