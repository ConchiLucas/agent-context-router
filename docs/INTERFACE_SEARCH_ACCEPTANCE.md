# 接口语义检索迁移验收

## 当前冻结基线

当前基线来自 2026-09-01 的 200 题全新模型双盲测评，并按源码等价规则完成审核。

| 指标 | 已观测结果 | 回归门槛 |
| --- | ---: | ---: |
| Top15 候选召回率 | 100.00% | 100.00% |
| 最终正确率（含合理澄清） | 95.50% | ≥ 95.00% |
| 已选择接口准确率 | 98.91% | ≥ 98.00% |
| Top15 未召回数 | 0 | 0 |

机器可读基线位于 `backend/evaluations/interface-search-baseline-v1.json`。其中记录原始报告、模型结果和冻结清单的 SHA-256；原始测评资产继续保留在独立接口语义导航器项目，避免在迁移项目中复制私有金标和大量业务样本。

## 自动回归

代码回归固定验证以下只读渐进链路：

```text
prepare_task_context(interface_search)
  -> search_forwarding_interfaces
  -> compare_forwarding_interfaces（候选接近时）
  -> read_forwarding_interface_detail（最终确认）
```

`interface_search` 的 `mutation_policy` 必须为 `forbidden`，链路不得调用 `prepare_forwarding_request`、`execute_forwarding_request`、`apply_workspace_changes` 或其他写操作。

批量评测应为三种接口工具携带同一 `run_id`，每道题使用独立 `item_id`，并以 `step_id/attempt` 区分搜索、比较、详情与重试。该上下文只用于观测，不得参与答案选择。审核时可通过 `GET /api/mcp-traces/{task_id}?run_id=...&item_id=...` 读取该题真实调用序列，并用搜索摘要中的 `search_id` 关联完整搜索会话；候选 `rank/retrieval_rank/score` 用于区分“未召回、排序偏差、语义冲突和模型裁决偏差”。

运行后端回归：

```bash
cd backend
uv run pytest tests/test_context_preparation.py tests/test_interface_search_mcp_flow.py tests/test_interface_search_quality_gate.py
```

对新的 200 题报告执行质量门槛检查：

```bash
cd backend
uv run python scripts/check_interface_search_quality.py --report /absolute/path/to/report.json
```

退出码为 `0` 表示全部门槛通过，`1` 表示存在回归。固定题集只用于防回归；任何“准确率提升”的结论必须另外生成未见题集验证。

Codex 与 Antigravity 的迁移后真实客户端验收使用
`backend/evaluations/client-acceptance-v1/`。该目录提供私有金标生成提示词、两份客户端盲测提示词、质量门槛和统一评分命令；两个客户端必须使用同一份无答案题集。

## 迁移边界

- 检索、比较和详情读取代码必须与具体工作空间无关。
- 调用层级只能按通用架构信号推断：显式服务名、显式网关/直连措辞、服务角色和路径角色；不得把具体工作空间的服务名或业务路径写入 Python 规则。门户调用方在没有显式服务或直连条件时可以软偏好前端网关/BFF，显式服务与显式直连必须覆盖该偏好。
- 调用层级不一致只能作为可解释的软冲突和排序惩罚，不能成为硬过滤条件；候选召回仍须保留下游直连接口供比较。
- 运输方式、鉴权和路由角色等身份既可来自路径与服务，也可来自已审核的通用语义字段；同义词扩展必须表达通用概念，不得绑定具体 Workspace。
- 路由身份的多个独立条件必须共同参与评分，不能因先命中“门户”等宽泛条件而跳过 noAuth、运输方式、操作或输出形态；带“不是……”的区分说明不得反向成为正向身份信号。
- 高置信度语义槽位冲突只允许施加有上限的软惩罚，不得覆盖精确接口身份或显式“服务 + 操作”身份，也不得把候选从召回结果中硬删除。
- 候选比较必须显式展示鉴权、调用层级、路由角色以及输出和其他区分条件，供客户端裁决或提出最小澄清问题。
- 工作空间专属术语、业务语义和接口合同可以保存在数据库中。
- 迁移不得以降低候选召回率换取更高 Top1，也不得增加工作空间业务硬编码兜底。
- 人工或模型最终裁决属于客户端行为；服务端只提供候选、可解释差异和准确合同。
- 评测轨迹必须以通用 `trace_context.item_id=record_id` 隔离题目，并以客户端身份和 `run_id` 隔离执行轮次；相同题面的不同版本不得因提示词摘要相同而共享客户端结果。旧轨迹仅可在题面唯一时兼容回退。
