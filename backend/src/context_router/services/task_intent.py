from __future__ import annotations

from context_router.schemas.context import (
    TaskExecutionContract,
    TaskIntentSource,
    TaskIntentType,
)

TASK_INTENT_TYPES: tuple[TaskIntentType, ...] = (
    "interface_execute",
    "data_query",
    "task_execute",
    "bug_investigate",
    "bug_fix",
)


def build_task_execution_contract(
    *,
    intent_type: TaskIntentType,
    error_signal: bool,
    intent_summary: str | None,
    intent_source: TaskIntentSource,
) -> TaskExecutionContract:
    required_steps: list[str]
    visualization_targets: list[str]
    instructions: list[str]
    mutation_policy = "forbidden" if intent_type == "bug_investigate" else "allowed"

    if intent_type == "interface_execute":
        required_steps = [
            "search_forwarding_interfaces",
            "prepare_forwarding_request",
            "execute_forwarding_request",
            "save_task_visualization_result",
        ]
        visualization_targets = ["task", "interface"]
        instructions = [
            "根据用户描述选择导入接口并组装参数，直接执行已准备的只读计划。",
            "接口执行成功或失败都会由服务端自动写入接口可视化。",
        ]
    elif intent_type == "data_query":
        required_steps = [
            "search_value_mappings",
            "save_data_visualization_query",
            "save_task_visualization_result",
        ]
        visualization_targets = ["task", "data"]
        instructions = [
            "用户描述包含业务名称、ID、编码或编号时，先调用 search_value_mappings；"
            "命中后用 resolve_value_candidates 获取当前任务环境的真实业务值。",
            "映射搜索和解析可以在 prepare 后直接执行；命中映射时不要为了确认数据库、"
            "表或过滤条件再调用 read_task_context、search_database_objects 或原始 SQL。",
            "用户要求随机或任意一个值时，调用 resolve_value_candidates 并设置 "
            "selection=random、limit=用户要求的数量；不要使用 ORDER BY RAND()。",
            "没有合适的已发布映射时，才调用 read_task_context、search_relation_tables 和 "
            "search_database_objects 定位数据库与表结构。",
            "使用解析出的业务值完成只读查询，并保存准确的数据可视化查询条件。",
            "不要为了填充页面伪造表名、数据库别名或查询值。",
        ]
    elif intent_type == "bug_investigate":
        required_steps = ["save_task_visualization_result"]
        visualization_targets = ["task"]
        instructions = [
            "本任务只允许查询和取证，不得修改、部署或启动工作空间。",
            "只有从当前任务已注册容器中确认错误时才生成日志可视化记录。",
        ]
        if error_signal:
            required_steps[0:0] = ["list_task_containers", "inspect_container_errors"]
            visualization_targets.append("log")
    elif intent_type == "bug_fix":
        required_steps = ["apply_workspace_changes", "save_task_visualization_result"]
        visualization_targets = ["task"]
        instructions = [
            "完成根因定位、代码修改、工作空间更新和真实验证后再结束任务。",
            "只有从当前任务已注册容器中确认错误时才生成日志可视化记录。",
        ]
        if error_signal:
            required_steps[0:0] = ["list_task_containers", "inspect_container_errors"]
            visualization_targets.append("log")
    else:
        required_steps = ["save_task_visualization_result"]
        visualization_targets = ["task"]
        instructions = ["根据任务选择最短的授权链路执行并验证，不为填充页面调用无关工具。"]

    return TaskExecutionContract(
        intent_type=intent_type,
        error_signal=error_signal,
        intent_summary=intent_summary,
        intent_source=intent_source,
        mutation_policy=mutation_policy,
        required_steps=required_steps,
        visualization_targets=visualization_targets,  # type: ignore[arg-type]
        instructions=instructions,
    )
