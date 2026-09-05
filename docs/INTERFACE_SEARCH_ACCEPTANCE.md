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
- 工作空间专属术语、业务语义和接口合同可以保存在数据库中。
- 迁移不得以降低候选召回率换取更高 Top1，也不得增加工作空间业务硬编码兜底。
- 人工或模型最终裁决属于客户端行为；服务端只提供候选、可解释差异和准确合同。
