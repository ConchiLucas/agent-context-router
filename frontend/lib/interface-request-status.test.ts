import assert from "node:assert/strict";
import test from "node:test";
import { interfaceRequestStatus } from "./interface-request-status";
import type { InterfaceForwardingInterface } from "./types";

test("request badges distinguish data, operations, errors and unknown results", () => {
  const labels = { not_requested: "未请求", has_data: "有数据", no_data: "无数据", succeeded: "请求成功", not_found: "404", business_error: "业务报错", error: "其他报错", requested: "已请求" };
  for (const [status, label] of Object.entries(labels)) {
    assert.equal(interfaceRequestStatus({ request_status: status as InterfaceForwardingInterface["request_status"], last_requested_at: null }).label, label);
  }
  assert.equal(interfaceRequestStatus({ last_requested_at: null }).label, "未请求");
  assert.equal(interfaceRequestStatus({ last_requested_at: "2026-09-22" }).label, "已请求");
  assert.equal(interfaceRequestStatus({ request_status: "error", last_requested_at: null }).tone, "error");
  assert.equal(interfaceRequestStatus({ request_status: "business_error", last_requested_at: null }).tone, "error");
});
