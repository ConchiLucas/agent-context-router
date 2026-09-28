/* Shared by the extension and the Node regression tests. */
(function (root) {
  const PREFIX = "capture:v2:";
  const SENSITIVE = /authorization|cookie|password|passwd|secret|token|access[_-]?key|captcha|^_sid$/i;
  const INTERFACE_RESOURCE_TYPES = new Set(["xmlhttprequest", "xhr", "fetch"]);
  function isInterfaceResourceType(value) {
    return INTERFACE_RESOURCE_TYPES.has(String(value || "").toLowerCase());
  }
  function isExcludedInterfaceUrl(value) {
    try {
      const path = decodeURIComponent(new URL(value).pathname);
      if (/\/sse\/connect\/?$/.test(path)) return true;
      // Fetch/XHR may also preload Vite chunks. Never filter by extension alone:
      // API downloads such as /rest/mtp/.../template.xlsx must remain observable.
      const api = /\/(?:rest|api|[^/]+-api)(?:\/|$)/i.test(path);
      if (api) return false;
      if (/^\/pzh-mtp-ui\/?$/i.test(path)) return true;
      return /\/(?:assets|static|_next\/static)\//i.test(path) &&
        /\.(?:css|m?js|map|woff2?|ttf|otf|eot|png|jpe?g|gif|svg|ico|webp|avif)$/i.test(path);
    }
    catch { return true; }
  }
  function redact(value, key = "", depth = 0) {
    if (SENSITIVE.test(key)) return "[REDACTED]";
    if (depth > 30) return "[DEPTH_LIMIT]";
    if (Array.isArray(value)) return value.map(item => redact(item, "", depth + 1));
    if (value && typeof value === "object") return Object.fromEntries(
      Object.entries(value).map(([name, item]) => [name, redact(item, name, depth + 1)]));
    if (typeof value === "string") return value.replace(
      /((?:password|passwd|secret|token|authorization|cookie|access[_-]?key|_sid)["']?\s*[=:]\s*["']?)[^&\s,"'}]+/gi,
      "$1[REDACTED]");
    return value;
  }
  function body(value, maxBytes = 131072) {
    if (value == null || value === "") return null;
    let parsed = value;
    if (typeof value === "string") {
      try { parsed = JSON.parse(value); }
      catch {
        if (!value.trim().startsWith("{") && value.includes("=") && !value.includes("<")) {
          parsed = {};
          for (const [key, item] of new URLSearchParams(value)) {
            if (Object.hasOwn(parsed, key)) parsed[key] = [].concat(parsed[key], item);
            else Object.defineProperty(parsed, key, {value: item, writable: true, enumerable: true});
          }
        }
      }
    }
    const safe = redact(parsed), encoded = JSON.stringify(safe);
    if (new TextEncoder().encode(encoded).length <= maxBytes) return safe;
    return {_truncated: true, preview: encoded.slice(0, Math.floor(maxBytes / 6))};
  }
  function responseBody(content, base64 = false, mime = "") {
    const maxBytes = 262144;
    const type = String(mime).split(";")[0].toLowerCase();
    const textual = !type || type.startsWith("text/") || /(?:json|xml|javascript)$/.test(type);
    const bytes = base64 ? Math.floor(content.length * 3 / 4) - (content.endsWith("==") ? 2 : content.endsWith("=") ? 1 : 0)
      : new TextEncoder().encode(content).length;
    if (!textual) return {_capture_kind: "binary", observed_bytes: bytes};
    // Decode only a bounded prefix. Base64 alone does not imply binary (JSON can use it).
    const text = base64 ? new TextDecoder().decode(Uint8Array.from(atob(content.slice(0, 349528)), c => c.charCodeAt(0))) : content;
    if (text.includes("\u0000")) return {_capture_kind: "binary", observed_bytes: bytes};
    if (bytes > maxBytes) return {_capture_kind: "truncated", _truncated: true, observed_bytes: bytes};
    if (text === "") return null;
    try { JSON.parse(text); return body(text, maxBytes); }
    catch { return {_capture_kind: "text", observed_bytes: bytes}; }
  }
  function url(value) {
    const parsed = new URL(value);
    parsed.username = ""; parsed.password = ""; parsed.hash = "";
    for (const key of [...parsed.searchParams.keys()]) {
      if (SENSITIVE.test(key)) parsed.searchParams.set(key, "[REDACTED]");
    }
    return parsed.href;
  }
  function pathValue(value, path) {
    let current = value;
    for (const part of String(path || "").split(".").filter(Boolean)) {
      if (!current || typeof current !== "object" || !Object.hasOwn(current, part)) return null;
      current = current[part];
    }
    return typeof current === "string" || typeof current === "number" ? String(current).trim() : null;
  }
  function matchesRule(rawUrl, method, rule) {
    try {
      return String(method || "").toUpperCase() === String(rule?.method || "POST").toUpperCase() &&
        new URL(rawUrl).pathname.endsWith(String(rule?.pathSuffix || ""));
    } catch { return false; }
  }
  function authIdentityCandidate(rawUrl, method, requestBody, rules = []) {
    const safeBody = body(requestBody);
    if (!safeBody || typeof safeBody !== "object") return null;
    for (let index = 0; index < rules.length; index++) {
      const rule = rules[index];
      if (!matchesRule(rawUrl, method, rule?.login)) continue;
      for (const field of rule.login.accountFields || []) {
        const account = pathValue(safeBody, field);
        if (account && account !== "[REDACTED]" && account.length <= 240) {
          return {ruleIndex: index, loginAccount: account,
            addressNames: Array.isArray(rule.addressNames) ? rule.addressNames : []};
        }
      }
    }
    return null;
  }
  function confirmsAuthIdentity(rawUrl, method, candidate, rules = []) {
    const rule = Number.isInteger(candidate?.ruleIndex) ? rules[candidate.ruleIndex] : null;
    const confirmations = rule?.confirmations || (rule?.confirmation ? [rule.confirmation] : []);
    return confirmations.some(confirmation => matchesRule(rawUrl, method, confirmation));
  }
  class Store {
    constructor(storage, options = {}) {
      this.storage = storage;
      this.maxBytes = options.maxBytes || 100 * 1024 * 1024;
      this.records = new Map(); this.serial = Promise.resolve();
      this.stats = {captured: 0, stored: 0, deduplicated: 0, overflow: 0}; this.error = "";
      this.ready = this.load();
    }
    async load() {
      const data = await this.storage.get(null);
      for (const [key, record] of Object.entries(data)) if (key.startsWith(PREFIX)) {
        this.records.set(record.capture.capture_id, record);
      }
      Object.assign(this.stats, data.captureStats || {});
      if (Array.isArray(data.pendingInterfaceCaptures)) {
        for (const old of data.pendingInterfaceCaptures) {
          if (!old.capture?.capture_id || this.records.has(old.capture.capture_id)) continue;
          const record = {...old, capture: {...old.capture, revision: 1, capture_state: "complete"}, updatedAt: Date.now(), ackRevision: 0};
          await this.persist(record);
        }
        await this.storage.remove("pendingInterfaceCaptures");
      }
    }
    run(fn) {
      const operation = this.serial.then(() => this.ready).then(fn);
      this.serial = operation.catch(error => { this.error = `本地保存失败：${error.message}`; });
      return operation;
    }
    async persist(record) {
      await this.storage.set({[PREFIX + record.capture.capture_id]: record});
      this.records.set(record.capture.capture_id, record);
    }
    put(id, patch, meta = {}) {
      return this.run(async () => {
        const previous = this.records.get(id);
        const wasPending = previous && !previous.blocked && (previous.ackRevision || 0) < previous.capture.revision;
        const record = {...previous, ...meta, updatedAt: Date.now(), blocked: "",
          pendingSince: wasPending ? (previous.pendingSince ?? previous.updatedAt) : Date.now(),
          capture: {...previous?.capture, ...patch, capture_id: id, revision: (previous?.capture.revision || 0) + 1}};
        const bytes = item => new TextEncoder().encode(JSON.stringify(item)).length;
        const used = [...this.records.values()].reduce((sum, item) => sum + bytes(item), 0);
        if (used + bytes(record) - (previous ? bytes(previous) : 0) > this.maxBytes) {
          this.stats.overflow++;
          this.error = "本地队列容量不足，有请求未能保存；请恢复接收服务";
          await this.storage.set({captureStats: this.stats});
          return null;
        }
        await this.persist(record);
        if (!previous) this.stats.captured++;
        await this.storage.set({captureStats: this.stats});
        return record;
      });
    }
    acknowledge(batch, result) {
      return this.run(async () => {
        if (!Array.isArray(result.acknowledged)) throw new Error("接收端未返回逐条入库确认，请升级后端");
        let confirmed = 0;
        for (const snapshot of batch) {
          const id = snapshot.capture.capture_id;
          const ack = result.acknowledged.find(item => item.capture_id === id &&
            ["stored", "deduplicated"].includes(item.status) && item.revision >= snapshot.capture.revision);
          const previous = this.records.get(id);
          if (!previous || !ack) continue;
          const record = {...previous, ackRevision: Math.max(previous.ackRevision || 0, snapshot.capture.revision),
            matchStatus: ack.match_status, matchReason: ack.reason, blocked: ""};
          if (record.ackRevision >= record.capture.revision) record.pendingSince = null;
          if (!previous.ackRevision) {
            if (ack.status === "deduplicated" || ack.deduplicated) this.stats.deduplicated++;
            else this.stats.stored++;
          }
          await this.persist(record); confirmed++;
        }
        for (const rejected of result.rejected || []) {
          const snapshot = batch.find(item => item.capture.capture_id === rejected.capture_id);
          const record = this.records.get(rejected.capture_id);
          if (snapshot && record && record.capture.revision === snapshot.capture.revision) {
            await this.persist({...record, blocked: rejected.reason || "接收端拒绝"});
          }
        }
        await this.storage.set({captureStats: this.stats});
        return confirmed;
      });
    }
    pending() {
      return [...this.records.values()].filter(record => !record.blocked && (record.ackRevision || 0) < record.capture.revision);
    }
    correlate(tabId, rawUrl, method, startedAt) {
      const safeUrl = url(rawUrl);
      const candidates = [...this.records.values()].filter(record => record.tabId === tabId &&
        record.capture.url === safeUrl && record.capture.method === method && Math.abs(record.startedAt - startedAt) < 100);
      // Do not assign a body when simultaneous identical requests are ambiguous.
      return candidates.length === 1 ? candidates[0].capture.capture_id : null;
    }
    cleanup(now = Date.now()) {
      return this.run(async () => {
        for (const [id, record] of this.records) {
          if (record.capture.capture_state !== "started" && record.ackRevision >= record.capture.revision && now - record.updatedAt > 300000) {
            await this.storage.remove(PREFIX + id); this.records.delete(id);
          }
        }
      });
    }
  }
  const api = {Store, body, responseBody, url, redact, isInterfaceResourceType, isExcludedInterfaceUrl,
    authIdentityCandidate, confirmsAuthIdentity};
  if (typeof module !== "undefined") module.exports = api;
  else root.CaptureCore = api;
})(globalThis);
