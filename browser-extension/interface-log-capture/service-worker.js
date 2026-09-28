importScripts("capture-core.js");
const CONFIG = {
  apiUrl: "http://127.0.0.1:49173/api/interface-forwarding/browser-captures",
  workspaceId: "b9ce65eddc27437d9615177fbd07cb0a",
  upload: {
    threshold: 10, maxBatchSize: 10, maxBatchBytes: 1024 * 1024,
    maxWaitMs: 5000, retryBaseMs: 5000, retryMaxMs: 30000,
  },
  origins: {
    "http://localhost:2077": "local", "http://127.0.0.1:2077": "local",
    "http://localhost:3000": "local", "http://127.0.0.1:3000": "local",
    "http://localhost:3001": "local", "http://127.0.0.1:3001": "local",
    "http://192.168.0.222:18080": "test", "http://192.168.0.222:28080": "uat",
    "http://223.87.29.28:30080": "pre",
  },
  // Workspace-specific paths and fields are data; the matching implementation stays generic.
  authIdentityRules: [{
    login: {method: "POST", pathSuffix: "/system/login/pcLogin", accountFields: ["username", "mobile"]},
    addressNames: ["运营端"],
    pageIdentity: {
      pathPrefixes: ["/op", "/pzh-mtp-ui", "/pzh-portal-admin-ui"],
      storage: "sessionStorage", tokenKey: "token",
      piniaRoots: ["#app", "#micro_training_app"], piniaStore: "user",
      accountFields: ["userName"], roleFields: [], requireRole: false,
      credentialHeader: "_sid",
    },
    confirmations: [
      {method: "POST", pathSuffix: "/system/login/bindSystem"},
      {method: "POST", pathSuffix: "/system/login/getLoginUserInfo"},
    ],
  }, {
    login: {method: "POST", pathSuffix: "/userInfo/noAuth/portalLogin", accountFields: ["username", "mobile"]},
    addressNames: ["门户端"],
    pageIdentity: {
      pathPrefix: "/hub/", storage: "sessionStorage",
      userKey: "c12-portal-ui:userInfo", tokenKey: "c12-portal-ui:token",
      accountFields: ["mobile", "username"], roleFields: ["currentIdentityName"],
      credentialHeader: "_sid",
    },
    confirmations: [{method: "POST", pathSuffix: "/userInfo/getLoginUserInfo"}],
  }, {
    login: {method: "POST", pathSuffix: "/auth/api/system/login/login", accountFields: ["username", "mobile"]},
    addressNames: ["管理端"],
    confirmations: [{method: "POST", pathSuffix: "/auth/api/system/login/getLoginUserInfo"}],
  }, {
    login: {method: "POST", pathSuffix: "/api/app/auth/login", accountFields: ["mobile"]},
    addressNames: ["司机端"],
    pageIdentity: {
      pathPrefix: "/hep-h5", storage: "localStorage",
      userKey: "userInfo", tokenKey: "token",
      accountFields: ["mobile", "userName"], roleFields: [], requireRole: false,
      credentialHeader: "_sid",
    },
    confirmations: [{method: "POST", pathSuffix: "/api/app/auth/getLoginUserInfo"}],
  }],
};
const FILTER = {urls: Object.keys(CONFIG.origins).map(origin => `${origin}/*`), types: ["xmlhttprequest"]};
const store = new CaptureCore.Store(chrome.storage.local);
const attached = new Set(), attaching = new Set(), devtoolsTabs = new Set(), debuggerRequests = new Map();
let flushing = false, flushTimer = null, uploadError = "";
// Credentials never enter the durable request/response queue.
const authRequests = new Map();
let authError = "";
let authLifecycle = Promise.resolve();
// Credentials stay in memory, never in the durable capture queue or logs.
const authPending = new Map(), authSynced = new Map(), authLatest = new Map();
let authFlushing = false, authTimer = null;
async function queueAuth(payload, observedAt = Date.now()) {
  const scope = JSON.stringify([payload.environment_key, new URL(payload.url).origin,
    payload.login_account, payload.role_name, payload.address_names, payload.headers['x-system-code']]);
  const key = JSON.stringify([payload.environment_key, new URL(payload.url).origin,
    new URL(payload.url).pathname, payload.login_account, payload.role_name, payload.address_names]);
  const signature = JSON.stringify(payload.headers), now = Date.now();
  const latest = authLatest.get(scope);
  if (latest && latest.expiresAt > now && latest.observedAt > observedAt) return;
  if (authLatest.size >= 128 && !latest) authLatest.delete(authLatest.keys().next().value);
  authLatest.set(scope, {observedAt, expiresAt: now + 300000});
  for (const [pendingKey, item] of authPending) {
    if (item.scope === scope && item.signature !== signature) authPending.delete(pendingKey);
  }
  const old = authPending.get(key), sent = authSynced.get(key);
  if (sent?.signature === signature && sent.expiresAt > now) return;
  if (!old || old.signature !== signature) {
    if (authPending.size >= 32 && !old) authPending.delete(authPending.keys().next().value);
    authPending.set(key, {payload, signature, scope, attempts: 0, nextAt: now, expiresAt: now + 300000});
  }
  await flushAuth();
}
async function flushAuth() {
  if (authFlushing) return;
  authFlushing = true;
  if (authTimer !== null) clearTimeout(authTimer);
  authTimer = null;
  try {
    for (const [key, item] of authPending) {
      const now = Date.now();
      if (item.expiresAt <= now) { authPending.delete(key); authError = '登录身份同步已过期，请刷新业务页面'; continue; }
      if (item.nextAt > now) continue;
      item.attempts++;
      try {
        const response = await fetch(`${CONFIG.apiUrl}/auth`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          signal: AbortSignal.timeout(10000), body: JSON.stringify(item.payload),
        });
        if (!response.ok) {
          const failure = response.status === 400 ? await response.json().catch(() => null) : null;
          const detail = typeof failure?.detail === 'string' && failure.detail.length <= 160 &&
            !/[\r\n\x00]/.test(failure.detail) ? `：${failure.detail}` : '';
          throw new Error(`登录身份同步 HTTP ${response.status}${detail}`);
        }
        const result = await response.json();
        if (result.status !== 'synced') throw new Error('登录身份未确认，尚未保存');
        if (authPending.get(key) === item) authPending.delete(key);
        if (authSynced.size >= 128) authSynced.delete(authSynced.keys().next().value);
        authSynced.set(key, {signature: item.signature, expiresAt: Date.now() + 300000});
        authError = '';
      } catch (error) {
        authError = error.message;
        if (authPending.get(key) !== item) continue;
        if (item.attempts >= 5) {
          // Keep an exhausted tombstone until TTL: repeated traffic cannot reset retries.
          item.nextAt = item.expiresAt;
          authError = '登录身份同步失败5次，请恢复服务后刷新业务页面';
        } else item.nextAt = Date.now() + Math.min(30000, 5000 * 2 ** (item.attempts - 1));
      }
    }
  } finally {
    authFlushing = false;
    if (authPending.size) authTimer = setTimeout(() => {
      authTimer = null; void flushAuth();
    }, Math.max(0, Math.min(...[...authPending.values()].map(item => item.nextAt)) - Date.now()));
  }
}
function requestBody(details) {
  if (details.requestBody?.formData) return details.requestBody.formData;
  return (details.requestBody?.raw || []).map(part =>
    part.bytes ? new TextDecoder().decode(part.bytes) : "[FILE]").join("");
}
function pendingIdentityKey(details) { return `pending-auth-identity:${environment(details.url)}:${details.tabId}`; }
// Runs in the page, returning only allowlisted identity fields and a token-match
// boolean. Neither credentials nor the complete user profile leave this function.
function readPageIdentity(rule, expectedOrigin, credential) {
  const prefixes = rule.pathPrefixes || [rule.pathPrefix];
  if (location.origin !== expectedOrigin || !prefixes.some(prefix => prefix &&
    (location.pathname === prefix.replace(/\/$/, "") ||
      location.pathname.startsWith(prefix.replace(/\/$/, "") + "/")))) return null;
  function decode(value) {
    for (let i = 0; i < 3 && typeof value === "string"; i++) {
      try { value = JSON.parse(value); } catch { break; }
    }
    return value;
  }
  const storage = rule.storage === "localStorage" ? localStorage : sessionStorage;
  const token = decode(storage.getItem(rule.tokenKey));
  if (!credential || typeof token !== "string" || token !== credential) return null;
  let user;
  if (rule.piniaStore) {
    for (const selector of rule.piniaRoots || []) {
      const candidate = document.querySelector(selector)?.__vue_app__?.config?.globalProperties
        ?.$pinia?._s?.get(rule.piniaStore);
      if (candidate?.token === credential) { user = candidate; break; }
    }
    if (!user) return null;
  } else user = decode(storage.getItem(rule.userKey));
  function pick(fields, limit) {
    for (const field of fields || []) {
      const value = field.split(".").reduce((item, key) => item?.[key], user);
      if (typeof value === "string" && value.trim() && value.length <= limit && !/[\r\n\x00]/.test(value)) return value.trim();
    }
    return "";
  }
  const loginAccount = pick(rule.accountFields, 240), roleName = pick(rule.roleFields, 160);
  return loginAccount && (roleName || rule.requireRole === false) ? {loginAccount, roleName} : null;
}
async function currentPageIdentity(auth) {
  if (!attached.has(auth.tabId)) return null;
  for (const rule of CONFIG.authIdentityRules) {
    if (!rule.pageIdentity) continue;
    try {
      const response = await command({tabId: auth.tabId}, "Runtime.evaluate", {
        expression: `(${readPageIdentity.toString()})(${JSON.stringify(rule.pageIdentity)},${JSON.stringify(new URL(auth.url).origin)},${JSON.stringify(auth.headers[rule.pageIdentity.credentialHeader] || "")})`,
        returnByValue: true,
      });
      const identity = response.result?.value;
      if (identity?.loginAccount && (identity.roleName || rule.pageIdentity.requireRole === false)) {
        return {...identity, addressNames: rule.addressNames};
      }
    } catch { /* No unverified cross-service identity fallback. */ }
  }
  return null;
}
async function rememberLoginIdentity(details) {
  const candidate = CaptureCore.authIdentityCandidate(
    details.url, details.method, requestBody(details), CONFIG.authIdentityRules);
  if (!candidate) return;
  await chrome.storage.session.set({[pendingIdentityKey(details)]: {...candidate, capturedAt: Date.now()}});
}
async function rememberAuth(details) {
  if (CaptureCore.isExcludedInterfaceUrl(details.url)) return;
  const headers = Object.fromEntries((details.requestHeaders || [])
    .filter(item => ["_sid", "authorization", "x-system-code"].includes(item.name.toLowerCase()))
    .map(item => [item.name.toLowerCase(), item.value || ""])
    .sort(([a], [b]) => a.localeCompare(b)));
  if (!headers._sid && !headers.authorization) return;
  authRequests.set(details.requestId, {headers, url: details.url, tabId: details.tabId, capturedAt: Date.now()});
}
async function syncAuth(details) {
  const auth = authRequests.get(details.requestId);
  authRequests.delete(details.requestId);
  if (!auth || Date.now() - auth.capturedAt > 300000 || details.statusCode < 200 || details.statusCode >= 300) return;
  // Group identical credentials across tabs, but never merge different accounts.
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(auth.headers)));
  const fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  const key = `auth-session:${environment(auth.url)}:${fingerprint}`;
  const saved = await chrome.storage.session.get(key);
  const sessionId = saved[key] || crypto.randomUUID();
  if (!saved[key]) await chrome.storage.session.set({[key]: sessionId});
  const pendingKey = pendingIdentityKey(auth);
  const pendingSaved = await chrome.storage.session.get(pendingKey);
  let pending = pendingSaved[pendingKey];
  const pendingFresh = pending && Date.now() - pending.capturedAt <= 300000;
  if (pendingFresh && !pending.confirmedAt) {
    if (CaptureCore.confirmsAuthIdentity(auth.url, details.method, pending, CONFIG.authIdentityRules)) {
      pending = {...pending, confirmedAt: Date.now()};
      await chrome.storage.session.set({[pendingKey]: pending});
    } else {
      // A configured login must not create a temporary anonymous identity before
      // the current-user request confirms the account and its target address.
      return;
    }
  }
  // Authentication endpoints can use a different service prefix than forwarding targets.
  // Keep the confirmed account briefly, then attach it to the next real business request
  // from the same tab/environment; the backend still enforces exact address boundaries.
  const confirmedIdentity = await currentPageIdentity(auth) || (pendingFresh && pending.confirmedAt ? pending : null);
  if (!confirmedIdentity?.loginAccount || confirmedIdentity.loginAccount.toLowerCase().startsWith("browser-session:")) return;
  await queueAuth({workspace_id: CONFIG.workspaceId, environment_key: environment(auth.url),
        url: auth.url, session_id: sessionId, headers: auth.headers,
        ...(confirmedIdentity?.addressNames?.length ? {address_names: confirmedIdentity.addressNames} : {}),
        ...(confirmedIdentity ? {login_account: confirmedIdentity.loginAccount,
          role_name: confirmedIdentity.roleName || ""} : {})}, auth.capturedAt);
}
function environment(url) { try { return CONFIG.origins[new URL(url).origin]; } catch { return null; } }
function safe(task) { Promise.resolve(task).catch(error => { uploadError = error.message; void badge(); }); }
let uploadRetries = {};
const uploadRetryReady = chrome.storage.local.get("captureUploadRetry").then(data => {
  uploadRetries = data.captureUploadRetry || {};
});
function requestRecord(details) {
  return [...store.records.values()].find(record => record.requestId === details.requestId &&
    record.tabId === details.tabId && record.capture.capture_state === "started");
}
function uploadDueAt(records, key, now, force = false) {
  // A response revision must not postpone the oldest unacknowledged observation.
  const oldest = records.reduce((time, record) => Math.min(time, record.pendingSince ?? record.updatedAt ?? now), now);
  const due = force || records.length >= CONFIG.upload.threshold ? now : oldest + CONFIG.upload.maxWaitMs;
  return Math.max(due, uploadRetries[key]?.nextAttemptAt || 0);
}
async function scheduleFlush() {
  await store.ready; await uploadRetryReady;
  if (flushing) return;
  if (flushTimer !== null) clearTimeout(flushTimer);
  flushTimer = null;
  const now = Date.now(), pending = store.pending();
  const times = [...new Set(Object.values(CONFIG.origins))].flatMap(key => {
    const records = pending.filter(record => record.environmentKey === key);
    return records.length ? [uploadDueAt(records, key, now)] : [];
  });
  if (times.length) flushTimer = setTimeout(() => {
    flushTimer = null; safe(flush());
  }, Math.max(0, Math.min(...times) - now));
}
async function badge() {
  await store.ready;
  const count = store.pending().length, failed = [...store.records.values()].filter(item => item.blocked).length;
  const error = store.error || uploadError || authError;
  await chrome.action.setBadgeText({text: error || failed ? "!" : count ? String(count) : "监听"});
  await chrome.action.setBadgeBackgroundColor({color: error || failed ? "#b42318" : "#16845b"});
  await chrome.action.setTitle({title: `接口录制：已采集 ${store.stats.captured}，已入库 ${store.stats.stored}，当日去重 ${store.stats.deduplicated || 0}，待传 ${count}，失败 ${failed}\n${error || "点击查看详情；响应内容采集可能不完整"}`});
}
async function begin(details) {
  await store.ready; await store.serial;
  if (!environment(details.url) || details.url.startsWith(CONFIG.apiUrl) || CaptureCore.isExcludedInterfaceUrl(details.url)) return;
  const previous = requestRecord(details);
  if (previous) await store.put(previous.capture.capture_id, {capture_state: "incomplete"});
  const rawRequestBody = requestBody(details);
  await store.put(crypto.randomUUID(), {
    url: CaptureCore.url(details.url), method: details.method,
    request_body: CaptureCore.body(rawRequestBody), response_body: null,
    status_code: null, duration_ms: 0, capture_state: "started", response_body_missing: true,
  }, {environmentKey: environment(details.url), requestId: details.requestId,
    tabId: details.tabId, frameId: details.frameId, startedAt: details.timeStamp});
  await scheduleFlush(); await badge();
}
async function finish(details, failure = false) {
  await store.ready; await store.serial;
  const record = requestRecord(details);
  if (!record) return;
  await store.put(record.capture.capture_id, {
    status_code: details.statusCode >= 100 && details.statusCode <= 599 ? details.statusCode : null,
    duration_ms: Math.max(0, Math.min(2147483647, Math.round(details.timeStamp - record.startedAt))),
    capture_state: failure ? "incomplete" : "complete",
    ...(failure ? {response_body: {_capture_error: details.error || "request_interrupted"}} : {}),
  });
  await scheduleFlush(); await badge();
}
// Register synchronously: these events cover frames independently of page JS.
// Serialize lifecycle events so a fast response cannot overtake durable begin().
let lifecycle = Promise.resolve();
function event(operation) { lifecycle = lifecycle.then(operation).catch(error => { uploadError = error.message; }); safe(lifecycle.then(badge)); }
chrome.webRequest.onBeforeRequest.addListener(details => {
  safe(rememberLoginIdentity(details)); event(() => begin(details));
}, FILTER, ["requestBody"]);
chrome.webRequest.onSendHeaders.addListener(details => safe(rememberAuth(details)), FILTER, ["requestHeaders"]);
chrome.webRequest.onCompleted.addListener(details => {
  authLifecycle = authLifecycle.then(() => syncAuth(details)).catch(() => { authError = '登录身份同步失败'; });
  safe(authLifecycle.then(badge));
}, FILTER);
chrome.webRequest.onErrorOccurred.addListener(details => authRequests.delete(details.requestId), FILTER);
chrome.webRequest.onBeforeRedirect.addListener(details => authRequests.delete(details.requestId), FILTER);
chrome.webRequest.onCompleted.addListener(details => event(() => finish(details)), FILTER);
chrome.webRequest.onErrorOccurred.addListener(details => event(() => finish(details, true)), FILTER);
chrome.webRequest.onBeforeRedirect.addListener(details => event(() => finish(details)), FILTER);
function uploadBody(batch) {
  return JSON.stringify({workspace_id: CONFIG.workspaceId, environment_key: batch[0].environmentKey,
    captures: batch.map(record => record.capture)});
}
async function selectUploadBatch(records) {
  const batch = [];
  for (const record of records) {
    const snapshot = structuredClone(record);
    if (new TextEncoder().encode(uploadBody([...batch, snapshot])).length > CONFIG.upload.maxBatchBytes) {
      if (batch.length) break;
      // Keep oversized records locally and report them, without blocking the rest.
      await store.run(async () => {
        const current = store.records.get(snapshot.capture.capture_id);
        if (current?.capture.revision === snapshot.capture.revision) {
          await store.persist({...current, blocked: "单条记录超过上传大小上限，已保留本地记录"});
        }
      });
      continue;
    }
    batch.push(snapshot);
    if (batch.length >= CONFIG.upload.maxBatchSize) break;
  }
  return batch;
}
async function uploadBatch(batch) {
  const response = await fetch(CONFIG.apiUrl, {
    method: "POST", headers: {"Content-Type": "application/json"}, signal: AbortSignal.timeout(10000),
    body: uploadBody(batch),
  });
  if (response.status === 422 && batch.length > 1) {
    let confirmed = 0;
    for (const item of batch) confirmed += await uploadBatch([item]);
    return confirmed;
  }
  if (response.status === 422) {
    await store.run(async () => {
      const record = store.records.get(batch[0].capture.capture_id);
      if (record?.capture.revision === batch[0].capture.revision) await store.persist({...record, blocked: "字段校验失败，已保留本地记录"});
    }); return 0;
  }
  if (!response.ok) throw new Error(`接收服务 HTTP ${response.status}；记录留在本地等待重试`);
  return store.acknowledge(batch, await response.json());
}
async function flush({force = false} = {}) {
  await store.ready; await uploadRetryReady;
  if (flushing) return;
  flushing = true;
  if (flushTimer !== null) clearTimeout(flushTimer);
  flushTimer = null;
  try {
    for (const key of new Set(Object.values(CONFIG.origins))) {
      const records = store.pending().filter(record => record.environmentKey === key);
      if (!records.length || uploadDueAt(records, key, Date.now(), force) > Date.now()) continue;
      try {
        const batch = await selectUploadBatch(records);
        if (!batch.length) continue;
        await uploadBatch(batch);
        if (batch.some(snapshot => {
          const current = store.records.get(snapshot.capture.capture_id);
          return current && !current.blocked && (current.ackRevision || 0) < snapshot.capture.revision;
        })) throw new Error("接收服务未确认全部记录；未确认部分留在本地等待重试");
        delete uploadRetries[key];
      } catch (error) {
        const failures = Math.min((uploadRetries[key]?.failures || 0) + 1, 4);
        const delay = Math.min(CONFIG.upload.retryBaseMs * 2 ** (failures - 1), CONFIG.upload.retryMaxMs);
        uploadRetries[key] = {failures, nextAttemptAt: Date.now() + delay, error: error.message};
      }
      // Persist only retry metadata; worker restarts must not bypass backoff.
      await chrome.storage.local.set({captureUploadRetry: uploadRetries});
    }
    uploadError = Object.values(uploadRetries).map(retry => retry.error).join("；");
    await store.cleanup();
  } finally {
    flushing = false; await scheduleFlush(); await badge();
  }
}
async function command(source, method, params = {}) { return chrome.debugger.sendCommand(source, method, params); }
async function enableNetwork(source) {
  await command(source, "Network.enable", {maxPostDataSize: 262144, maxResourceBufferSize: 1048576, maxTotalBufferSize: 8388608});
  await command(source, "Target.setAutoAttach", {autoAttach: true, waitForDebuggerOnStart: false, flatten: true});
}
async function attach(tab) {
  if (!Number.isInteger(tab.id) || !environment(tab.url) || attached.has(tab.id) || attaching.has(tab.id) || devtoolsTabs.has(tab.id)) return;
  attaching.add(tab.id);
  try {
    await chrome.debugger.attach({tabId: tab.id}, "1.3");
    await enableNetwork({tabId: tab.id}); attached.add(tab.id);
  } catch { /* webRequest remains active; popup reports the missing body channel. */ }
  finally { attaching.delete(tab.id); }
}
async function enrich(tabId, url, method, startedAt, content, requestBody) {
  await lifecycle; await store.ready; await store.serial;
  const id = store.correlate(tabId, url, method, startedAt);
  if (!id) return;
  // Both response channels already parse, redact and bound via responseBody.
  const patch = {response_body: content, response_body_missing: false};
  if (requestBody != null) patch.request_body = CaptureCore.body(requestBody);
  await store.put(id, patch); await scheduleFlush();
}
chrome.debugger.onEvent.addListener((source, method, params) => safe((async () => {
  if (source.tabId == null) return;
  if (method === "Target.attachedToTarget") { await enableNetwork({tabId: source.tabId, sessionId: params.sessionId}); return; }
  const key = `${source.tabId}:${source.sessionId || "root"}:${params.requestId}`;
  if (method === "Network.requestWillBeSent" && environment(params.request?.url) &&
    CaptureCore.isInterfaceResourceType(params.type) && !CaptureCore.isExcludedInterfaceUrl(params.request.url)) {
    debuggerRequests.set(key, {url: CaptureCore.url(params.request.url), method: params.request.method,
      startedAt: params.wallTime * 1000, requestBody: CaptureCore.body(params.request.postData)});
  } else if (method === "Network.responseReceived") {
    const request = debuggerRequests.get(key);
    if (request) request.mimeType = params.response?.mimeType;
  } else if (method === "Network.loadingFinished") {
    const request = debuggerRequests.get(key); debuggerRequests.delete(key);
    if (!request || devtoolsTabs.has(source.tabId)) return;
    try {
      const response = await command(source, "Network.getResponseBody", {requestId: params.requestId});
      const observed = CaptureCore.responseBody(response.body, response.base64Encoded, request.mimeType);
      await enrich(source.tabId, request.url, request.method, request.startedAt, observed, request.requestBody);
    } catch { /* The durable record explicitly marks missing response content. */ }
  } else if (method === "Network.loadingFailed") debuggerRequests.delete(key);
})()));
chrome.debugger.onDetach.addListener(source => {
  attached.delete(source.tabId);
  for (const key of debuggerRequests.keys()) if (key.startsWith(`${source.tabId}:`)) debuggerRequests.delete(key);
  safe(badge());
});
chrome.runtime.onConnect.addListener(port => {
  if (port.name !== "capture-devtools") return;
  let tabId;
  port.onMessage.addListener(message => {
    if (message.type === "hello") {
      tabId = message.tabId; devtoolsTabs.add(tabId);
      if (attached.has(tabId)) safe(chrome.debugger.detach({tabId}));
    } else if (message.type === "response" && tabId != null) safe(enrich(tabId, message.url, message.method, message.startedAt, message.body, message.requestBody));
  });
  port.onDisconnect.addListener(() => { devtoolsTabs.delete(tabId); if (tabId != null) safe(chrome.tabs.get(tabId).then(attach)); });
});
chrome.tabs.onUpdated.addListener((id, change, tab) => { if (change.url || change.status === "complete") safe(attach(tab)); });
chrome.tabs.onRemoved.addListener(tabId => event(async () => {
  for (const [id, auth] of authRequests) if (auth.tabId === tabId) authRequests.delete(id);
  attached.delete(tabId); devtoolsTabs.delete(tabId); await store.ready;
  for (const record of [...store.records.values()]) if (record.tabId === tabId && record.capture.capture_state === "started") {
    await store.put(record.capture.capture_id, {capture_state: "incomplete"});
  } await scheduleFlush();
}));
async function maintenance({force = false} = {}) {
  void flushAuth();
  for (const [id, auth] of authRequests) if (Date.now() - auth.capturedAt > 300000) authRequests.delete(id);
  await lifecycle; await store.ready;
  const tabs = await chrome.tabs.query({}), ids = new Set(tabs.map(tab => tab.id));
  for (const record of [...store.records.values()]) if (record.capture.capture_state === "started" &&
    ((record.tabId >= 0 && !ids.has(record.tabId)) || Date.now() - record.startedAt > 600000)) {
    await store.put(record.capture.capture_id, {capture_state: "incomplete"});
  }
  await Promise.all(tabs.map(attach)); await flush({force});
}
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "capture-maintenance") safe(maintenance()); });
chrome.runtime.onInstalled.addListener(() => safe(maintenance()));
chrome.runtime.onStartup.addListener(() => safe(maintenance()));
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id) return false;
  (async () => {
    await store.ready;
    if (message.type === "retry") {
      await store.run(async () => { for (const record of [...store.records.values()]) if (record.blocked) await store.persist({...record, blocked: ""}); });
      store.error = ""; await maintenance({force: true});
    }
    if (message.type === "reconcile") {
      const response = await fetch(`${CONFIG.apiUrl}/reconcile?workspace_id=${CONFIG.workspaceId}`, {method: "POST", signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error(`重新匹配失败：HTTP ${response.status}`);
    }
    const records = [...store.records.values()];
    reply({stats: store.stats, pending: store.pending().length, failed: records.filter(record => record.blocked).length,
      error: store.error || uploadError || authError, bodyMode: devtoolsTabs.has(message.tabId) ? "DevTools 补充响应" : attached.has(message.tabId) ? "调试器补充响应" : "仅请求与状态码，响应内容可能缺失",
      apiUrl: CONFIG.apiUrl, workspaceId: CONFIG.workspaceId});
  })().catch(error => reply({error: error.message})); return true;
});
chrome.alarms.create("capture-maintenance", {periodInMinutes: 0.5});
safe(maintenance());
