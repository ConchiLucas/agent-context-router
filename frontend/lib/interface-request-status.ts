import type { InterfaceForwardingInterface } from "./types";

export function interfaceRequestStatus(item: Pick<InterfaceForwardingInterface, "request_status" | "last_requested_at">) {
  const status = item.request_status ?? (item.last_requested_at ? "requested" : "not_requested");
  const labels = {
    not_requested: "未请求", has_data: "有数据", no_data: "无数据",
    succeeded: "请求成功", not_found: "404", business_error: "业务报错", error: "其他报错", requested: "已请求",
  };
  return { label: labels[status], tone: status === "not_found" || status === "error" || status === "business_error" ? "error"
    : status === "has_data" || status === "succeeded" ? "success" : "neutral" };
}
