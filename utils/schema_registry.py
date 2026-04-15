from schemas.intent_schema import SearchIntent
from schemas.agent_schema import OutputSchema, OutputSchemaField


def get_generic_search_result_schema() -> OutputSchema:
    # 返回开放领域查询默认使用的结构化输出 schema。
    return OutputSchema(
        name="generic_search_result",
        version="v1",
        description="开放领域查询的默认结构化搜索结果 schema",
        fields=[
            OutputSchemaField(name="query", description="用户原始查询"),
            OutputSchemaField(name="title", description="结果标题"),
            OutputSchemaField(name="source", description="来源站点或域名"),
            OutputSchemaField(name="url", description="结果链接"),
            OutputSchemaField(name="content_type", description="内容类型", required=False),
            OutputSchemaField(name="region", description="地域信息", required=False),
            OutputSchemaField(name="role_direction", description="角色或主题方向", required=False),
            OutputSchemaField(name="summary", description="结构化摘要", required=False),
            OutputSchemaField(name="quality_score", description="结果质量分", required=False),
            OutputSchemaField(name="extraction_notes", description="抽取说明", required=False),
        ],
    )


def resolve_output_schema(intent: SearchIntent) -> OutputSchema:
    # 根据解析出的查询意图选择对应的输出 schema。
    if intent.target_schema_name == "generic_search_result":
        return get_generic_search_result_schema()
    return get_generic_search_result_schema()
