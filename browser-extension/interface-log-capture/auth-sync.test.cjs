const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

function fixture() {
  const saved = {}, sent = [];
  const source = fs.readFileSync(require('node:path').join(__dirname, 'service-worker.js'), 'utf8');
  const context = vm.createContext({importScripts() {}, CaptureCore: {
    Store: class {}, isExcludedInterfaceUrl: () => false,
    confirmsAuthIdentity: (url, method) => method === 'POST' && url.endsWith('/current-user'),
  },
    chrome: {storage: {local: {}, session: {
      get: async key => ({[key]: saved[key]}), set: async value => Object.assign(saved, value),
    }}}, crypto: webcrypto, TextEncoder, URL, AbortSignal, setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, init) => {sent.push({url, body: JSON.parse(init.body)}); return {ok: true, json: async () => ({status:'synced'})};},
  });
  vm.runInContext(source.slice(0, source.indexOf('function safe(')), context);
  return {context, sent, saved};
}
test('local management origin and login rule stay separate from portal and operations', () => {
  const f = fixture();
  const core = require('./capture-core.js');
  const rules = vm.runInContext('CONFIG.authIdentityRules', f.context);
  assert.equal(vm.runInContext('environment("http://localhost:2077/rest/auth/api/system/login/login")', f.context), 'local');
  assert.equal(vm.runInContext('environment("http://127.0.0.1:2077/op/login")', f.context), 'local');
  const candidate = core.authIdentityCandidate('http://localhost:2077/rest/auth/api/system/login/login', 'POST', JSON.stringify({username:'fixture-admin'}), rules);
  assert.equal(candidate.loginAccount, 'fixture-admin');
  assert.equal(JSON.stringify(candidate.addressNames), JSON.stringify(['管理端']));
  assert.ok(core.confirmsAuthIdentity('http://localhost:2077/rest/auth/api/system/login/getLoginUserInfo', 'POST', candidate, rules));
  assert.equal(core.confirmsAuthIdentity('http://localhost:2077/rest/portal/userInfo/getLoginUserInfo', 'POST', candidate, rules), false);
});
test('driver H5 login rule is isolated across TEST, UAT and PRE', () => {
  const f = fixture();
  const core = require('./capture-core.js');
  const rules = vm.runInContext('CONFIG.authIdentityRules', f.context);
  for (const [origin, environment] of [
    ['http://192.168.0.222:18080', 'test'],
    ['http://192.168.0.222:28080', 'uat'],
    ['http://223.87.29.28:30080', 'pre'],
  ]) {
    assert.equal(vm.runInContext(`environment(${JSON.stringify(origin + '/hep-h5/pages/login/login')})`, f.context), environment);
    const candidate = core.authIdentityCandidate(origin + '/rest/facade/api/app/auth/login',
      'POST', JSON.stringify({mobile:'18900006666',password:'never-copy'}), rules);
    assert.equal(candidate.loginAccount, '18900006666');
    assert.deepEqual(Array.from(candidate.addressNames), ['司机端']);
    assert.ok(core.confirmsAuthIdentity(origin + '/rest/facade/api/app/auth/getLoginUserInfo',
      'POST', candidate, rules));
    assert.equal(core.confirmsAuthIdentity(origin + '/rest/portal/userInfo/getLoginUserInfo',
      'POST', candidate, rules), false);
  }
});
async function request(f, id, port, token, status = 200, reverse = false) {
  const requestHeaders = [{name:'_sid',value:token},{name:'X-System-Code',value:'mtp'},
    {name:'Cookie',value:'must-not-copy'},{name:'Host',value:'must-not-copy'}];
  f.context.details = {requestId:id, url:`http://192.168.0.222:${port}/rest/mtp/orders/page`,
    tabId:Number(id), requestHeaders:reverse ? requestHeaders.reverse() : requestHeaders, statusCode:status};
  await vm.runInContext('rememberAuth(details); syncAuth(details)', f.context);
}
test('auth sync isolates environments, groups tabs, and excludes unrelated headers', async () => {
  const f = fixture();
  vm.runInContext('currentPageIdentity = async () => ({loginAccount:"fixture-user", roleName:"reader"})', f.context);
  await request(f,'1',18080,'test-fixture');
  await request(f,'2',28080,'uat-fixture');
  await request(f,'3',18080,'test-fixture',200,true);
  assert.deepEqual(f.sent.map(r => r.body.environment_key), ['test','uat']);
  assert.notEqual(f.sent[0].body.session_id, f.sent[1].body.session_id);
  assert.deepEqual(f.sent[0].body.headers, {_sid:'test-fixture','x-system-code':'mtp'});
  assert.ok(!JSON.stringify(f.saved).includes('test-fixture'));
  assert.ok(!JSON.stringify(f.sent).includes('must-not-copy'));
});

test('failed auth retries are bounded and repeated traffic does not reset backoff', async () => {
  const f = fixture(); let calls = 0;
  f.context.fetch = async () => {calls++; throw new Error('offline');};
  vm.runInContext('currentPageIdentity = async () => ({loginAccount:"fixture-user",roleName:"reader"})', f.context);
  await request(f,'1',28080,'fixture');
  await request(f,'1',28080,'fixture');
  assert.equal(calls,1);
  for (let i=0;i<4;i++) await vm.runInContext('for (const item of authPending.values()) item.nextAt=0; flushAuth()', f.context);
  assert.equal(calls,5);
  await request(f,'1',28080,'fixture');
  assert.equal(calls,5);
  assert.equal(vm.runInContext('[...authPending.values()][0].attempts',f.context),5);
  await request(f,'1',28080,'new-fixture');
  assert.equal(calls,6);
});

test('retry succeeds after recovery; skipped acknowledgements are not success', async () => {
  const f = fixture(); let calls=0;
  f.context.fetch = async () => ({ok:true,json:async()=>({status:++calls===1?'skipped':'synced'})});
  vm.runInContext('currentPageIdentity = async () => ({loginAccount:"fixture-user",roleName:"reader"})', f.context);
  await request(f,'1',28080,'fixture');
  assert.equal(vm.runInContext('authPending.size',f.context),1);
  await vm.runInContext('for (const item of authPending.values()) item.nextAt=0; flushAuth()',f.context);
  assert.equal(vm.runInContext('authPending.size',f.context),0);
  await request(f,'1',28080,'fixture');
  assert.equal(calls,2);
});

test('expired auth is discarded and a newer credential cancels older route retries', async () => {
  const f = fixture(); let calls=0;
  f.context.fetch=async()=>{calls++;throw new Error('offline');};
  f.context.payload={environment_key:'uat',url:'http://example.test/rest/mtp/a',
    login_account:'fixture',role_name:'reader',headers:{_sid:'old'}};
  await vm.runInContext('queueAuth(payload, 10)',f.context);
  await vm.runInContext('queueAuth({...payload,url:"http://example.test/rest/mtp/b",headers:{_sid:"new"}},20)',f.context);
  assert.equal(vm.runInContext('authPending.size',f.context),1);
  await vm.runInContext('queueAuth(payload, 10)',f.context);
  assert.equal(calls,2);
  await vm.runInContext('for(const item of authPending.values()) item.expiresAt=0; flushAuth()',f.context);
  assert.equal(vm.runInContext('authPending.size',f.context),0);
  assert.equal(calls,2);
});
test('401 does not publish a failed credential', async () => {
  const f = fixture();
  await request(f,'1',18080,'expired-fixture',401);
  assert.equal(f.sent.length,0);
});
test('different credentials never overwrite the same browser identity', async () => {
  const f = fixture();
  vm.runInContext('currentPageIdentity = async () => ({loginAccount:"fixture-user", roleName:"reader"})', f.context);
  await request(f,'1',18080,'first-fixture');
  await request(f,'1',18080,'second-fixture');
  assert.notEqual(f.sent[0].body.session_id, f.sent[1].body.session_id);
});
test('unidentified sessions never publish forwarding credentials', async () => {
  const f = fixture();
  await request(f, '1', 18080, 'anonymous-fixture');
  assert.equal(f.sent.length, 0);
});
test('configured login waits for confirmation instead of creating an anonymous identity', async () => {
  const f = fixture();
  const pendingKey = 'pending-auth-identity:test:1';
  f.saved[pendingKey] = {ruleIndex:1, loginAccount:'15259212926',
    addressNames:['门户端'], capturedAt:Date.now()};
  await request(f,'1',18080,'portal-token');
  assert.equal(f.sent.length,0);
  f.context.details = {requestId:'2',
    url:'http://192.168.0.222:18080/rest/portal/member-api/portal/userInfo/current-user',
    method:'POST', tabId:1, requestHeaders:[{name:'_sid',value:'portal-token'},
      {name:'X-System-Code',value:'portal'}], statusCode:200};
  await vm.runInContext('rememberAuth(details); syncAuth(details)', f.context);
  assert.equal(f.sent.length,1);
  assert.equal(f.sent[0].body.login_account,'15259212926');
  assert.deepEqual(f.sent[0].body.address_names,['门户端']);
});

test('page identity requires matching origin, page, credential and selected role', () => {
  const f = fixture();
  f.context.location = {origin:'http://example.test', pathname:'/hub/personalCenter'};
  f.context.sessionStorage = {getItem: key => key === 'token' ? JSON.stringify('fixture') :
    JSON.stringify(JSON.stringify({mobile:'user-a',currentIdentityName:'货主',password:'never-return'}))};
  f.context.rule = {pathPrefix:'/hub/',storage:'sessionStorage',tokenKey:'token',userKey:'user',
    accountFields:['mobile'],roleFields:['currentIdentityName']};
  const result = vm.runInContext('readPageIdentity(rule,"http://example.test","fixture")', f.context);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {loginAccount:'user-a',roleName:'货主'});
  assert.equal(vm.runInContext('readPageIdentity(rule,"http://other.test","fixture")',f.context),null);
  assert.equal(vm.runInContext('readPageIdentity(rule,"http://example.test","other-token")',f.context),null);
  f.context.location.pathname='/mgmt/';
  assert.equal(vm.runInContext('readPageIdentity(rule,"http://example.test","fixture")',f.context),null);
});
test('driver H5 page identity only returns a mobile when the stored token matches the request', () => {
  const f = fixture();
  f.context.location = {origin:'http://192.168.0.222:18080', pathname:'/hep-h5/pages/index/index'};
  f.context.localStorage = {getItem: key => key === 'token' ? JSON.stringify('driver-token') :
    JSON.stringify({mobile:'18900006666',password:'never-return'})};
  const rule = vm.runInContext('CONFIG.authIdentityRules.at(-1).pageIdentity', f.context);
  f.context.rule = rule;
  const result = vm.runInContext('readPageIdentity(rule,"http://192.168.0.222:18080","driver-token")', f.context);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {loginAccount:'18900006666',roleName:''});
  assert.equal(vm.runInContext('readPageIdentity(rule,"http://192.168.0.222:18080","old-token")',f.context),null);
  f.context.location.pathname='/op/orders';
  assert.equal(vm.runInContext('readPageIdentity(rule,"http://192.168.0.222:18080","driver-token")',f.context),null);
});

test('observed business request receives the verified role after login window expires', async () => {
  const f = fixture();
  vm.runInContext('currentPageIdentity = async () => ({loginAccount:"user-a",roleName:"货主",addressNames:["门户端"]})',f.context);
  await request(f,'1',28080,'fixture');
  assert.equal(f.sent[0].body.role_name,'货主');
  assert.equal(f.sent[0].body.login_account,'user-a');
  assert.equal(f.sent[0].body.url,'http://192.168.0.222:28080/rest/mtp/orders/page');
});

function operationsPage(f, token = 'ops-token', account = 'superadmin') {
  f.context.location = {origin:'http://192.168.0.222:28080', pathname:'/op/orders'};
  f.context.sessionStorage = {getItem: key => key === 'token' ? JSON.stringify(token) : null};
  const user = {token, userName:account, password:'never-return', roleNames:['运营端管理员']};
  f.context.document = {querySelector: selector => selector === '#app' ?
    {__vue_app__:{config:{globalProperties:{$pinia:{_s:new Map([['user',user]])}}}}} : null};
  vm.runInContext('attached.add(1); command = async (_target, _method, params) => ({result:{value:eval(params.expression)}})',f.context);
  return user;
}

test('operations page syncs after five minutes and refreshes the same account credential', async () => {
  const f = fixture();
  const user = operationsPage(f);
  f.saved['pending-auth-identity:uat:1'] = {loginAccount:'old-user',capturedAt:Date.now()-600000,confirmedAt:1};
  await request(f,'1',28080,'ops-token');
  assert.equal(f.sent.length,1);
  assert.equal(f.sent[0].body.login_account,'superadmin');
  assert.equal(f.sent[0].body.role_name,'');
  assert.deepEqual(f.sent[0].body.address_names,['运营端']);
  assert.ok(!JSON.stringify(f.sent).includes('never-return'));
  user.token = 'refreshed';
  f.context.sessionStorage.getItem = () => JSON.stringify('refreshed');
  await request(f,'1',28080,'refreshed');
  assert.equal(f.sent.length,2);
  assert.equal(f.sent[1].body.headers._sid,'refreshed');
  user.userName = 'new-user';
  await request(f,'1',28080,'refreshed');
  assert.equal(f.sent[2].body.login_account,'new-user');
});

test('operations page recovers without login history, rejects stale requests and logged-out users', async () => {
  const f = fixture();
  const user = operationsPage(f);
  await request(f,'1',28080,'stale-token');
  assert.equal(f.sent.length,0);
  await request(f,'1',28080,'ops-token');
  assert.equal(f.sent.length,1);
  user.token = '';
  await request(f,'1',28080,'ops-token');
  assert.equal(f.sent.length,1);
  user.token = 'ops-token';
  f.context.location.pathname='/op-other/orders';
  await request(f,'1',28080,'ops-token');
  assert.equal(f.sent.length,1);
});
