# 任务：生成 MTP 双客户端验收的 50 题私有金标

你是独立出题和源码审核模型，不负责执行最终盲测。覆盖上一版输出。

## 唯一源码范围

只允许读取：

`/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce/backend/c12-mtp`

不得从 `c12-auth`、`c12-wms`、`c12-rcc`、`c12-park`、`c12-core`、`c12-report`、`c12-sys`、`c12-data`、`c12-egps`、`c12-facade`、`c12-scts` 或 `backend/c12-mtp` 之外的项目生成题目。

允许路径前缀：`/order-api/`、`/line-api/`、`/basic-api/`、`/highway-api/`、`/railway-api/`、`/shipping-api/`、`/settlement-api/`、`/declaration-api/`、`/declaration-interface-api/`、`/operation-api/`、`/message-api/`、`/inner/message/`、`/external-interface-api/`、`/zhiyun/`、`/sms/`、`/job-client-api/`、`/trace-api/`、`/admin/`、`/report/`。

禁止路径：`/api/`、`/test/`、`/internal/`、`/member-api/`。

## 题目分布

生成全新 50 题，编号 `accept-001` 至 `accept-050`：common 20、colloquial 10、explicit_constraint 8、sibling_disambiguation 8、intentional_ambiguity 4。

覆盖不同 MTP 服务、运输方式、端侧、资源、动作、分页/列表/单条/批量、请求位置和查找键。问题不得出现路径、HTTP 方法、Controller、Java 方法、Operation ID 或 interface_id。

普通题必须足以唯一确定接口。`intentional_ambiguity` 必须真正缺少决定性条件，至少存在两个合理候选，`expected_decision=clarify`。

## 源码与索引双重验证

每个答案必须从源码确认 method、path、service、请求、返回、兄弟区别和源码行号。

完成自然语言问题后，才允许用当前 Context Router MCP 验证索引存在性：先以工作目录 `/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce` 调用一次 `prepare_task_context(intent_type=interface_search)`；然后只用精确合同 `METHOD PATH` 调用 `search_forwarding_interfaces(limit=15)`。不得用自然语言问题预检排名。

只有搜索结果中出现完全一致的 `service + method + path` 才能保留，并记录 MCP 返回的 `interface_id`。未命中时丢弃该题并更换真实 MTP 接口。等价答案和澄清候选必须逐个验证。

## 私有金标

覆盖保存：`/Users/conchi/Desktop/Context-Router双客户端验收50题-私有金标.json`

```json
{
  "schema_version": "context-router-client-acceptance-gold-v2",
  "suite_id": "mtp-client-acceptance-2026-09-02-v2",
  "workspace_root": "/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce",
  "source_scope": "backend/c12-mtp",
  "case_count": 50,
  "cases": [
    {
      "case_id": "accept-001",
      "category": "common",
      "query": "自然语言问题",
      "expected_decision": "selected",
      "acceptable_interfaces": [
        {
          "interface_id": "MCP返回UUID",
          "service": "c12-mtp-example-biz",
          "method": "POST",
          "path": "/example/path",
          "operation_id": "ExampleController.method",
          "source_location": "backend/c12-mtp下相对路径:行号"
        }
      ],
      "gold_reason": "选择理由",
      "key_differentiators": ["与兄弟接口的区别"],
      "index_verification": {
        "verified": true,
        "query": "POST /example/path",
        "matched_interface_ids": ["MCP返回UUID"]
      }
    }
  ]
}
```

接口身份固定使用 `interface_id + service + method + path`，不能只用 method 和 path。

## 无答案题集

从金标机械派生并覆盖保存：`/Users/conchi/Desktop/Context-Router双客户端验收50题-无答案.json`

根字段为 `schema_version=context-router-client-acceptance-blind-v2`、`suite_id=mtp-client-acceptance-2026-09-02-v2`、`case_count=50`。每题只能包含 `case_id` 和 `query`，不得泄露其他字段。

完成前检查题号连续、分类数准确、全部源码位于 `backend/c12-mtp`、全部接口通过索引验证、两文件问题一致且 JSON 可解析。最后只回复两个文件路径、分类统计、源码范围检查和索引验证通过数量。
