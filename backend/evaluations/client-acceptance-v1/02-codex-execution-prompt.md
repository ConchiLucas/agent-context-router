# 任务：使用当前 Context Router MCP 完成 50 题盲测（Codex）

这是一次无答案验收。请使用全新任务上下文，不依赖以前对题目或接口的记忆。

## 输入与输出

- 只读取题目：`/Users/conchi/Desktop/Context-Router双客户端验收50题-无答案.json`
- 输出结果：`/Users/conchi/Desktop/Context-Router双客户端验收50题-Codex结果.json`
- 工作目录：`/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce`

不得读取名称含“私有金标”的文件、源码、数据库、历史测评、历史结果或接口语义导航器文件。不得使用普通文件搜索替代 MCP 接口检索。

## 每题必须执行的流程

1. 调用 `prepare_task_context`，传入当前 query、工作目录和 `intent_type=interface_search`。
2. 调用 `search_forwarding_interfaces`，`limit=15`。
3. 第一名证据不足或候选职责接近时，调用 `compare_forwarding_interfaces` 比较最小必要的 2～5 个候选。
4. 确定最终接口后调用 `read_forwarding_interface_detail` 核实接口合同；如果用户确实缺少决定性条件，输出 `clarify`。
5. 只能选择本题搜索返回的候选，不得创造或凭记忆填写接口。

严格禁止调用 `prepare_forwarding_request`、`execute_forwarding_request`、`apply_workspace_changes`、`start_workspace` 或任何写操作。即使题目描述新增、删除、保存接口，本任务也只是查找接口，不执行它。

## 结果格式

```json
{
  "schema_version": "context-router-client-acceptance-result-v2",
  "suite_id": "mtp-client-acceptance-2026-09-02-v2",
  "client": "codex",
  "mcp_server": "context_router",
  "case_count": 50,
  "cases": [
    {
      "case_id": "accept-001",
      "query": "原始问题，必须与输入完全一致",
      "status": "completed",
      "error": null,
      "task_id": 1,
      "decision": "selected",
      "selected_interface": {
        "interface_id": "UUID",
        "service": "c12-mtp-example-biz",
        "method": "POST",
        "path": "/example/path"
      },
      "clarification_question": null,
      "candidate_interfaces": [
        {
          "rank": 1,
          "interface_id": "UUID",
          "service": "c12-mtp-example-biz",
          "method": "POST",
          "path": "/example/path"
        }
      ],
      "tool_calls": ["prepare_task_context", "search_forwarding_interfaces", "read_forwarding_interface_detail"],
      "compared_interface_ids": [],
      "detailed_interface_ids": ["UUID"],
      "reason": "基于候选语义和合同的简短理由",
      "elapsed_ms": 0
    }
  ]
}
```

`selected_interface` 和每个候选必须原样记录 MCP 返回的 `interface_id + service + method + path`，不得省略 service，也不得根据路径自行补写 interface_id。`clarify` 时 `selected_interface` 必须为 `null`，并填写最小澄清问题。任何单题失败也必须保留该题，设置 `status=failed` 和 `error`，不能跳过。每完成10题立即覆盖保存一次结果文件作为检查点。全部完成后校验50个 case_id 无缺失、无重复，JSON可以正常解析，最后只回复输出路径和完成/失败数量。
