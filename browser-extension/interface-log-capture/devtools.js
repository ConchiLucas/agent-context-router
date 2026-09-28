let port;
function connect() {
  port = chrome.runtime.connect({name: "capture-devtools"});
  port.postMessage({type: "hello", tabId: chrome.devtools.inspectedWindow.tabId});
  port.onDisconnect.addListener(() => setTimeout(connect, 1000));
}
connect();
chrome.devtools.network.onRequestFinished.addListener(request => {
  if (!CaptureCore.isInterfaceResourceType(request._resourceType) || CaptureCore.isExcludedInterfaceUrl(request.request.url)) return;
  const origin = new URL(request.request.url).origin;
  if (!["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001", "http://192.168.0.222:18080", "http://192.168.0.222:28080"].includes(origin)) return;
  request.getContent((content, encoding) => {
    if (typeof content !== "string") return;
    try {
      const observed = CaptureCore.responseBody(content, encoding === "base64", request.response?.content?.mimeType);
      port.postMessage({type: "response", url: CaptureCore.url(request.request.url), method: request.request.method,
        startedAt: Date.parse(request.startedDateTime), body: observed,
        requestBody: request.request.postData?.text == null ? null : CaptureCore.body(request.request.postData.text)});
    } catch { /* webRequest already saved the request entry. */ }
  });
});
