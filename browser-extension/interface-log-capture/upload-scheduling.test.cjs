const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

function storage() {
  const data = {};
  return {
    get: async key => structuredClone(key == null ? data : {[key]: data[key]}),
    set: async values => Object.assign(data, structuredClone(values)),
    remove: async key => { delete data[key]; },
  };
}
function response(body, status = 201) {
  return {ok: status < 400, status, json: async () => ({acknowledged: (body.captures || []).map(c => ({
    capture_id: c.capture_id, revision: c.revision, status: 'stored', match_status: 'pending',
  }))})};
}
async function fixture({disk = storage(), now = 1000000, send = async body => response(body)} = {}) {
  const timers = new Map(), sent = [];
  let timerId = 0;
  const event = () => ({addListener() {}});
  const chrome = {
    storage: {local: disk, session: storage()},
    action: {setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {}, setTitle: async () => {}},
    webRequest: Object.fromEntries(['onBeforeRequest','onSendHeaders','onCompleted','onErrorOccurred','onBeforeRedirect'].map(key => [key,event()])),
    debugger: {onEvent: event(), onDetach: event()},
    tabs: {onUpdated: event(), onRemoved: event(), query: async () => [{id:7, url:'about:blank'}]},
    alarms: {onAlarm: event(), create() {}},
    runtime: {onConnect: event(), onInstalled: event(), onStartup: event(), onMessage: event()},
  };
  const context = vm.createContext({chrome, TextEncoder, TextDecoder, URL, URLSearchParams,
    crypto: webcrypto, structuredClone, AbortSignal,
    Date: class extends Date {static now() {return now;}},
    setTimeout: (fn, delay) => {const id = ++timerId; timers.set(id,{fn,at:now + delay}); return id;},
    clearTimeout: id => timers.delete(id),
    fetch: async (url, init) => {
      const body = JSON.parse(init.body);
      sent.push({url, body, at:now, bytes:Buffer.byteLength(init.body)});
      return send(body, url);
    },
    importScripts: file => vm.runInContext(fs.readFileSync(path.join(__dirname,file),'utf8'),context),
  });
  const run = code => vm.runInContext(code,context);
  async function settle() {
    for (let i = 0; i < 3; i++) await new Promise(resolve => setImmediate(resolve));
  }
  vm.runInContext(fs.readFileSync(path.join(__dirname,'service-worker.js'),'utf8'),context);
  await settle();
  return {
    disk, sent, run, settle, now: () => now,
    async put(id, environmentKey = 'uat', patch = {}) {
      context.input = {id, environmentKey, patch};
      await run(`store.put(input.id, {url:'http://localhost:3000/api/query', method:'POST',
        capture_state:'complete', ...input.patch}, {environmentKey:input.environmentKey})`);
      await run('scheduleFlush()');
    },
    async tick(ms) {
      const until = now + ms;
      for (let steps = 0; ; steps++) {
        assert.ok(steps < 100, 'upload timers must not spin on unacknowledged records');
        const next = [...timers].filter(([,timer]) => timer.at <= until).sort((a,b) => a[1].at - b[1].at)[0];
        if (!next) break;
        now = next[1].at; timers.delete(next[0]); next[1].fn(); await settle();
      }
      now = until; await settle();
    },
  };
}

test('10 pending captures trigger one batch without waiting five seconds', async () => {
  const f = await fixture();
  for (let i = 0; i < 9; i++) await f.put(String(i));
  await f.tick(0); assert.equal(f.sent.length,0);
  await f.put('9'); await f.tick(0);
  assert.equal(f.sent.length,1);
  assert.equal(f.sent[0].body.captures.length,10);
  assert.equal(f.run('store.pending().length'),0);
});

test('start, completion and later arrivals do not postpone the oldest five-second deadline', async () => {
  const f = await fixture();
  await f.run(`begin({requestId:'r', tabId:7, url:'http://localhost:3000/api/query', method:'POST', timeStamp:Date.now()})`);
  await f.tick(3000);
  await f.run(`finish({requestId:'r', tabId:7, statusCode:200, timeStamp:Date.now()})`);
  await f.put('later','local'); await f.tick(1999);
  assert.equal(f.sent.length,0);
  await f.tick(1);
  assert.equal(f.sent.length,1);
  assert.equal(f.sent[0].body.captures.length,2);
  assert.equal(f.sent[0].body.captures[0].capture_state,'complete');
  assert.equal(f.sent[0].body.captures[0].revision,2);
});

test('thresholds and payloads are isolated per environment', async () => {
  const f = await fixture();
  for (let i = 0; i < 5; i++) {await f.put('t'+i,'test'); await f.put('u'+i,'uat');}
  await f.tick(0); assert.equal(f.sent.length,0);
  await f.tick(5000);
  assert.deepEqual(f.sent.map(r => r.body.environment_key),['test','uat']);
  assert.deepEqual(f.sent.map(r => r.body.captures.length),[5,5]);
});

test('backlogs drain in batches of at most 10, with the tail using its original deadline', async () => {
  const f = await fixture();
  for (let i = 0; i < 25; i++) await f.put(String(i));
  await f.tick(0);
  assert.deepEqual(f.sent.map(r => r.body.captures.length),[10,10]);
  await f.tick(5000);
  assert.deepEqual(f.sent.map(r => r.body.captures.length),[10,10,5]);
});

test('UTF-8 request payloads are capped at one MiB without dropping the remaining captures', async () => {
  const f = await fixture();
  for (let i = 0; i < 10; i++) await f.put(String(i),'uat',{response_body:'中'.repeat(80000)});
  await f.tick(5000);
  assert.deepEqual(f.sent.map(r => r.body.captures.length),[4,4,2]);
  assert.ok(f.sent.every(r => r.bytes <= 1024 * 1024));
  assert.equal(f.run('store.pending().length'),0);
});

test('oversized individual records remain locally blocked and do not block valid records', async () => {
  const f = await fixture();
  await f.put('too-large','uat',{response_body:'中'.repeat(400000)});
  await f.put('normal'); await f.tick(5000);
  assert.deepEqual(f.sent[0].body.captures.map(c => c.capture_id),['normal']);
  assert.match(f.run('store.records.get("too-large").blocked'),/上限/);
  assert.equal(f.run('store.records.size'),2);
});

test('HTTP failures back off 5/10/20/30 seconds even above the threshold and during maintenance', async () => {
  const f = await fixture({send: async body => response(body,503)});
  for (let i = 0; i < 10; i++) await f.put(String(i));
  await f.tick(0);
  for (const delay of [5000,10000,20000,30000,30000]) {
    const before = f.sent.length;
    await f.put('new-'+before); await f.run('maintenance()'); await f.run('maintenance({force:true})');
    await f.tick(delay-1); assert.equal(f.sent.length,before);
    await f.tick(1); assert.equal(f.sent.length,before+1);
  }
  assert.equal(f.run('store.pending().length'),15);
});

test('worker restarts preserve retry deadlines; success resets backoff', async () => {
  const first = await fixture({send: async body => response(body,503)});
  await first.put('a'); await first.tick(5000); await first.tick(5000);
  const restarted = await fixture({disk:first.disk, now:first.now()});
  assert.equal(restarted.sent.length,0);
  await restarted.tick(9999); assert.equal(restarted.sent.length,0);
  await restarted.tick(1); assert.equal(restarted.sent.length,1);
  assert.equal(restarted.run('store.pending().length'),0);
  assert.deepEqual((await restarted.disk.get('captureUploadRetry')).captureUploadRetry,{});
});

test('worker restarts and maintenance respect a young record deadline and old-format records', async () => {
  const first = await fixture();
  await first.put('young'); await first.tick(2000);
  const restarted = await fixture({disk:first.disk, now:first.now()});
  await restarted.run('maintenance()'); assert.equal(restarted.sent.length,0);
  await restarted.tick(3000); assert.equal(restarted.sent.length,1);
  const disk = storage();
  await disk.set({'capture:v2:legacy':{capture:{capture_id:'legacy',revision:1,capture_state:'complete'},
    environmentKey:'uat',updatedAt:900000,ackRevision:0}});
  const legacy = await fixture({disk});
  assert.equal(legacy.sent.length,1);
});

test('an in-flight upload remains single and old ACK cannot swallow a new response revision', async () => {
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  const f = await fixture({send: async body => {await gate; return response(body);}});
  for (let i = 0; i < 10; i++) await f.put(String(i));
  await f.tick(0); assert.equal(f.sent.length,1);
  await f.put('0','uat',{response_body:{updated:true}});
  await f.run('flush({force:true})'); await f.tick(1000);
  assert.equal(f.sent.length,1);
  release(); await f.settle();
  assert.equal(f.run('store.pending().length'),1);
  await f.tick(4000);
  assert.equal(f.sent.length,2);
  assert.equal(f.sent[1].body.captures[0].revision,2);
  assert.equal(f.run('store.pending().length'),0);
});

test('enrichment after a complete ACK starts a new five-second wait', async () => {
  const f = await fixture();
  await f.put('a'); await f.tick(5000); await f.tick(1000);
  await f.put('a','uat',{response_body:{updated:true}});
  await f.tick(4999); assert.equal(f.sent.length,1);
  await f.tick(1); assert.equal(f.sent.length,2);
});

test('partial ACK retains only unconfirmed records and applies backoff', async () => {
  const f = await fixture({send: async body => response({...body,captures:body.captures.slice(0,1)})});
  await f.put('a'); await f.put('b'); await f.tick(5000);
  assert.equal(f.run('store.pending().length'),1);
  await f.tick(4999); assert.equal(f.sent.length,1);
  await f.tick(1); assert.equal(f.sent.length,2);
  assert.deepEqual(f.sent[1].body.captures.map(c => c.capture_id),['b']);
});

test('HTTP 200 without ACK and network timeouts preserve the queue without immediate retry', async () => {
  for (const send of [async () => ({ok:true,status:200,json:async () => ({})}), async () => {throw new Error('timeout');}]) {
    const f = await fixture({send});
    for (let i = 0; i < 10; i++) await f.put(String(i));
    await f.tick(4999);
    assert.equal(f.sent.length,1); assert.equal(f.run('store.pending().length'),10);
    await f.tick(1); assert.equal(f.sent.length,2);
  }
});

test('one environment failure does not block other environments', async () => {
  const f = await fixture({send: async body => response(body,body.environment_key === 'test' ? 503 : 201)});
  await f.put('t','test'); await f.put('u','uat'); await f.tick(5000);
  assert.equal(f.sent.length,2);
  assert.equal(f.run('store.pending()[0].environmentKey'),'test');
});

test('manual retry can upload a small fresh batch without waiting for the threshold', async () => {
  const f = await fixture();
  await f.put('a'); await f.run('maintenance({force:true})');
  assert.equal(f.sent.length,1);
});

test('identity and Session synchronization do not wait for the capture batch', async () => {
  const f = await fixture();
  await f.put('a');
  await f.run(`currentPageIdentity = async () => ({loginAccount:'fixture-user',roleName:'reader'});
    rememberAuth({requestId:'auth',tabId:7,url:'http://192.168.0.222:28080/rest/mtp/orders/page',
      requestHeaders:[{name:'_sid',value:'fixture-token'},{name:'X-System-Code',value:'mtp'}]})`);
  await f.run(`syncAuth({requestId:'auth',statusCode:200})`);
  assert.equal(f.sent.length,1);
  assert.ok(f.sent[0].url.endsWith('/auth'));
  assert.equal(f.run('store.pending().length'),1);
  assert.ok(!JSON.stringify(await f.disk.get(null)).includes('fixture-token'));
});
