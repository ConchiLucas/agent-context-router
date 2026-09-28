const byId = id => document.getElementById(id);
const reasons = {interface_not_found: "接口目录未收录", ambiguous_interface: "匹配到多个接口", in_progress: "请求进行中",
  origin_mismatch: "地址与环境不一致", forwarding_configuration_missing: "缺少转发地址", matching_database_error: "关联失败，可重新匹配"};
let generation = 0;
async function refresh(type = "status") {
  const current = ++generation;
  document.querySelectorAll("button").forEach(button => button.disabled = true);
  byId("error").hidden = true;
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const status = await chrome.runtime.sendMessage({type, tabId: tab?.id});
    if (!status.stats) throw new Error(status.error || "读取采集状态失败");
    byId("mode").textContent = `网络监听已注册 · ${status.bodyMode}`;
    byId("counts").replaceChildren();
    for (const [label, value] of [["已采集", status.stats.captured], ["已入库（至少初始记录）", status.stats.stored], ["查询接口当日去重", status.stats.deduplicated || 0], ["待传更新", status.pending], ["失败待处理", status.failed], ["容量不足次数", status.stats.overflow]]) {
      const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = label; dd.textContent = value;
      byId("counts").append(dt, dd);
    }
    if (status.error) { byId("error").textContent = status.error; byId("error").hidden = false; }
    const response = await fetch(`${status.apiUrl}?workspace_id=${status.workspaceId}&limit=30`, {signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error(`读取入库记录失败：HTTP ${response.status}`);
    const data = await response.json();
    if (current !== generation) return;
    byId("summary").textContent = `服务端累计：已关联 ${data.counts.matched || 0}，待匹配／进行中 ${data.counts.pending || 0}。下方显示最近 30 条。`;
    byId("records").replaceChildren();
    for (const record of data.records) {
      const details = document.createElement("details"), summary = document.createElement("summary"), pre = document.createElement("pre");
      const state = record.capture_state === "started" ? "进行中" : record.capture_state === "incomplete" ? "未完整结束" : String(record.status_code ?? "无状态码");
      summary.textContent = `[${record.environment_key}] ${record.method} ${record.url} · ${state} · ${record.match_status === "matched" ? "已关联" : reasons[record.reason] || "待匹配"}${record.response_body_missing ? " · 缺响应正文" : ""}`;
      details.append(summary, pre);
      details.addEventListener("toggle", async () => {
        if (!details.open || pre.dataset.loaded) return;
        pre.textContent = "正在读取脱敏内容…";
        try {
          const result = await fetch(`${status.apiUrl}?workspace_id=${status.workspaceId}&capture_id=${encodeURIComponent(record.capture_id)}`, {signal: AbortSignal.timeout(10000)});
          if (!result.ok) throw new Error(`HTTP ${result.status}`);
          const detail = await result.json(); pre.textContent = JSON.stringify(detail.records[0]?.payload || {}, null, 2); pre.dataset.loaded = "true";
        } catch (error) { pre.textContent = `读取失败：${error.message}，收起后重试`; }
      });
      byId("records").append(details);
    }
    if (!data.records.length) byId("records").textContent = "尚无入库记录。启用扩展后，正常操作业务页面即可采集。";
  } catch (error) { byId("error").textContent = error.message; byId("error").hidden = false; }
  finally { document.querySelectorAll("button").forEach(button => button.disabled = false); }
}
byId("refresh").addEventListener("click", () => refresh());
byId("retry").addEventListener("click", () => refresh("retry"));
byId("reconcile").addEventListener("click", () => refresh("reconcile"));
void refresh();
