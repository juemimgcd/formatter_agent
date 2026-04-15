from schemas.agent_schema import ExecutionPlan, OutputSchema, PlanStep
from schemas.intent_schema import SearchIntent


def build_execution_plan(
    intent: SearchIntent,
    output_schema: OutputSchema,
) -> ExecutionPlan:
    """Build a lightweight, explainable plan for the existing pipeline."""
    # 基于查询意图和输出 schema 构造轻量可解释的执行计划。
    steps = [
        PlanStep(
            name="search",
            tool_name="web_search",
            description="获取开放网页候选结果",
        ),
        PlanStep(
            name="rank",
            tool_name="candidate_rank",
            description="对候选结果去重、重排并截取 top-k",
        ),
        PlanStep(
            name="structure",
            tool_name="result_structure",
            description=f"按 {output_schema.name} 生成结构化结果",
        ),
        PlanStep(
            name="export",
            tool_name="excel_export",
            description="将结构化结果导出为 Excel 载体",
        ),
    ]
    return ExecutionPlan(
        plan_id=f"{intent.intent_type}_{output_schema.name}_v1",
        intent_type=intent.intent_type,
        schema_name=output_schema.name,
        steps=steps,
        summary=(
            f"根据 {intent.intent_type} intent 和 {output_schema.name} schema "
            "执行 search -> rank -> structure -> export"
        ),
    )
