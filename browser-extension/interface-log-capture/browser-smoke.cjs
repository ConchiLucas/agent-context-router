// Run with PLAYWRIGHT_MODULE pointing to the installed Playwright package.
// All HTTP traffic is sent to a disposable loopback fixture, never business APIs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'acr-capture-smoke-'));
const records = new Map();
const authSyncs = [];
let online = true, businessCount = 0;
const server = http.createServer(async (req, res) => {
  if (req.url.startsWith('/collector')) {
    if (!online) { res.writeHead(503); res.end('{}'); return; }
    if (req.method === 'GET') {
      res.setHeader('Content-Type', 'application/json');
      const q = new URL(req.url, 'http://fixture').searchParams;
      const items = [...records.values()].filter(c => !q.get('capture_id') || q.get('capture_id') === c.capture_id);
      res.end(JSON.stringify({counts: {pending: records.size}, records: items.map(c => ({...c, environment_key:'local', match_status:'pending', reason:'interface_not_found', payload:c}))})); return;
    }
    let text = ''; for await (const chunk of req) text += chunk;
    const data = JSON.parse(text);
    if (req.url === '/collector/auth') {
      authSyncs.push(data);
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({status:'synced'})); return;
    }
    for (const item of data.captures) if (!records.has(item.capture_id) || item.revision > records.get(item.capture_id).revision) records.set(item.capture_id, item);
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({acknowledged: data.captures.map(c => ({capture_id:c.capture_id, revision:c.revision, status:'stored', match_status:'pending', reason:'interface_not_found'}))})); return;
  }
  if (req.url.startsWith('/api/')) {
    businessCount++;
    for await (const chunk of req) {} // Drain payload without logging it.
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ok:true, marker:req.url})); return;
  }
  res.setHeader('Content-Type', 'text/html');
  res.end('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>录制验证 fixture</title><body>仅本地测试页面</body></html>');
});
async function eventually(check, label, timeout = 15000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) { if (await check()) return; await new Promise(r => setTimeout(r,100)); }
  throw new Error('Timed out: ' + label);
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const extension = path.join(temp, 'extension'), profile = path.join(temp, 'profile');
  fs.mkdirSync(extension);
  for (const file of fs.readdirSync(__dirname)) if (/\.(js|html|css|json)$/.test(file)) fs.copyFileSync(path.join(__dirname,file),path.join(extension,file));
  const workerFile = path.join(extension, 'service-worker.js');
  let code = fs.readFileSync(workerFile,'utf8').replace('http://127.0.0.1:49173/api/interface-forwarding/browser-captures',origin+'/collector');
  code = code.replace('origins: {',`origins: { "${origin}": "local",`);
  fs.writeFileSync(workerFile,code);
  const manifestPath = path.join(extension,'manifest.json'), manifest = JSON.parse(fs.readFileSync(manifestPath,'utf8'));
  manifest.host_permissions.push(`${origin}/*`); fs.writeFileSync(manifestPath,JSON.stringify(manifest));
  const devtoolsFile = path.join(extension,'devtools.js');
  fs.writeFileSync(devtoolsFile,fs.readFileSync(devtoolsFile,'utf8').replace('if (![','if (!['+JSON.stringify(origin)+','));
  async function launch(devtools = false) {
    const context = await chromium.launchPersistentContext(profile,{headless:false, devtools,
      ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {}),
      args:[`--disable-extensions-except=${extension}`,`--load-extension=${extension}`,...(devtools ? ['--auto-open-devtools-for-tabs'] : [])]});
    let worker = context.serviceWorkers()[0];
    if (!worker) worker = await context.waitForEvent('serviceworker');
    return {context,worker};
  }
  let {context,worker} = await launch();
  try {
    let page = await context.newPage(); await page.goto(origin);
    await eventually(() => worker.evaluate(() => attached.size > 0),'debugger body channel attached');
    await page.evaluate(async () => { await fetch('/api/single',{method:'POST',
      headers:{_sid:'fixture-login-secret','X-System-Code':'mtp'},
      body:JSON.stringify({id:1,password:'test-secret'})}); });
    await eventually(() => authSyncs.length === 1,'environment-scoped header synchronization');
    assert.equal(authSyncs[0].environment_key,'local');
    assert.equal(authSyncs[0].headers._sid,'fixture-login-secret');
    await eventually(() => [...records.values()].some(c => c.url.endsWith('/api/single') && c.capture_state === 'complete' && c.response_body_missing === false),'single request and response saved');
    const single = [...records.values()].find(c => c.url.endsWith('/api/single'));
    assert.equal(single.request_body.password,'[REDACTED]');
    assert.equal(single.response_body.marker,'/api/single');
    await page.evaluate(async () => {
      await Promise.all([1,2].map(() => fetch('/api/repeated',{method:'POST',body:'{"id":1}'})));
      const frame=document.createElement('iframe'); frame.src='/frame'; document.body.append(frame);
      await new Promise(resolve => frame.onload=resolve);
      await frame.contentWindow.fetch('/api/frame',{method:'POST',body:'{"id":2}'});
      await new Promise(resolve => { const xhr=new XMLHttpRequest(); xhr.open('POST','/api/xhr'); xhr.onloadend=resolve; xhr.send('{"id":3}'); });
    });
    await eventually(() => [...records.values()].filter(c => c.capture_state === 'complete').length === 5,'two identical requests, iframe, XHR');
    assert.equal([...records.values()].filter(c => c.url.endsWith('/api/repeated')).length,2);
    online=false;
    await page.evaluate(async () => {await fetch('/api/offline',{method:'POST',body:'{"id":4}'});});
    await page.reload();
    await eventually(() => worker.evaluate(() => store.pending().some(r => r.capture.url.endsWith('/api/offline') && r.capture.capture_state === 'complete')),'offline capture persisted across page reload');
    await context.close(); online=true;
    ({context,worker}=await launch(true));
    await eventually(() => [...records.values()].some(c => c.url.endsWith('/api/offline') && c.capture_state === 'complete'),'browser restart replay of pending capture');
    page = await context.newPage(); await page.goto(origin);
    await eventually(() => worker.evaluate(() => devtoolsTabs.size > 0),'DevTools bridge connected');
    await page.evaluate(async () => {
      await fetch('/api/devtools',{method:'POST',body:'{"id":5}'});
      await fetch('/api/sse/connect?businessType=taskcenter');
    });
    await eventually(() => [...records.values()].some(c => c.url.endsWith('/api/devtools') && c.capture_state === 'complete' && !c.response_body_missing),'DevTools request and response saved');
    assert.ok(![...records.values()].some(c => c.url.includes('/api/sse/connect')));
    const id = new URL(worker.url()).host;
    const popup = await context.newPage(); await popup.goto(`chrome-extension://${id}/popup.html`);
    await popup.getByText('最近保存的请求',{exact:true}).waitFor();
    await eventually(async () => (await popup.locator('#records details').count()) === 7,'popup shows stored pending records');
    for (const width of [375,768,1440]) {
      await popup.setViewportSize({width,height:900});
      assert.ok(await popup.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await popup.evaluate(() => document.documentElement.style.zoom='2');
    await popup.setViewportSize({width:375,height:900});
    assert.ok(await popup.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await popup.evaluate(() => document.documentElement.style.zoom='1');
    await popup.screenshot({path:path.join(temp,'popup.png'),fullPage:true});
    assert.equal(businessCount,8);
    assert.ok(!JSON.stringify([...records.values()]).includes('fixture-login-secret'));
    const disk = await worker.evaluate(() => chrome.storage.local.get(null));
    assert.ok(!JSON.stringify(disk).includes('fixture-login-secret'));
    console.log(JSON.stringify({passed:true,actualRequests:businessCount,storedRequests:records.size,
      scenarios:['fetch with response','identical concurrent requests','iframe','XHR','offline + reload','browser restart','DevTools response bridge','popup + responsive + 200%'],artifacts:temp}));
  } catch (error) {
    const session = await context.browser().newBrowserCDPSession();
    console.error('Browser targets:', (await session.send('Target.getTargets')).targetInfos.map(t=>({type:t.type,url:t.url})));
    console.error('Saved fixture records:', [...records.values()].map(c => ({url:c.url,state:c.capture_state,revision:c.revision,missing:c.response_body_missing})));
    console.error('Worker:', await worker.evaluate(() => ({error:store.error, uploadError, pending:store.pending().map(r=>({url:r.capture.url,state:r.capture.capture_state,revision:r.capture.revision})),stats:store.stats})).catch(()=>null));
    throw error;
  } finally { await context.close(); }
})().catch(error => {console.error(error);process.exitCode=1;}).finally(() => server.close());
