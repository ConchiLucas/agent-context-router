from __future__ import annotations

from context_router.schemas.context import (
    TaskExecutionContract,
    TaskIntentSource,
    TaskIntentType,
)

TASK_INTENT_TYPES: tuple[TaskIntentType, ...] = (
    "interface_discovery",
    "interface_execute",
    "data_query",
    "task_execute",
    "bug_investigate",
    "bug_fix",
    "code_change",
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
    hard_requirements: list[str] = []
    completion_requirements: list[str] = ["task_result_saved"]
    mutation_policy = "forbidden" if intent_type == "bug_investigate" else "allowed"

    if intent_type == "interface_discovery":
        required_steps = [
            "search_forwarding_interfaces",
            "save_task_visualization_result",
        ]
        visualization_targets = ["task"]
        instructions = [
            "本任务只查找、比较或说明接口，不准备或执行请求。",
            "优先使用搜索结果的 match_score、match_reasons、CRUD 和业务语义；只有候选歧义或"
            "用户询问参数、响应、影响表时读取接口详情。",
            "搜索结果 goal_completed=true 时直接保存任务结论，不检索项目文档。",
        ]
    elif intent_type == "interface_execute":
        required_steps = [
            "search_forwarding_interfaces",
            "prepare_forwarding_request",
            "execute_forwarding_request",
            "save_task_visualization_result",
        ]
        visualization_targets = ["task", "interface"]
        instructions = [
            "根据用户明确描述选择导入接口并组装参数，直接执行已准备的请求计划；读取、新增、"
            "修改、删除及未分类接口均可执行。",
            "接口执行成功或失败都会由服务端自动写入接口可视化。",
            "同一任务中相同请求成功后由服务端复用原执行结果，不会再次发送 HTTP 请求。",
            "接口成功后只保存一次任务结论；可省略 verification_call_ids，由服务端自动关联"
            "最新成功执行。不要为查找记录 ID 再次准备请求、执行接口、读取任务环境或检索文档。",
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
            "映射返回的显示字段已经满足请求时，直接用 mapping_id 和成功解析调用号保存"
            "数据可视化；不要再次搜索 Schema 或表关系。",
            "没有合适的已发布映射时，才调用 read_task_context、search_relation_tables 和 "
            "search_database_objects 定位数据库与表结构。",
            "确需完整记录时按映射来源和值字段执行一次有界只读查询；保存数据可视化时"
            "携带成功解析或查询的 execution_tool_call_id，使记录直接标记为已查询。",
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
            hard_requirements.append("attempt_registered_error_log_inspection_when_error_signal")
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
            hard_requirements.append(
                "attempt_registered_error_log_inspection_before_apply_when_error_signal"
            )
        completion_requirements[0:0] = [
            "workspace_changes_applied",
            "verified_outcome",
        ]
    elif intent_type == "code_change":
        required_steps = ["apply_workspace_changes", "save_task_visualization_result"]
        visualization_targets = ["task"]
        instructions = [
            "使用 Agent 原生文件和终端能力完成源码搜索、修改与项目规定的验证。",
            "完成一轮修改后只提交一次实际 Workspace 相对路径，再等待运行操作终态。",
            "数据库、接口、日志、中间件和表关联是可按需叠加的取证能力，不改变主意图。",
        ]
        completion_requirements[0:0] = [
            "workspace_changes_applied",
            "verified_outcome",
        ]
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
        hard_requirements=hard_requirements,
        completion_requirements=completion_requirements,
        recommended_flow=required_steps,
    )
