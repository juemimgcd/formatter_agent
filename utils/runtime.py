from conf.settings import settings
from utils.exceptions import WorkflowError


def ensure_runtime_directories() -> None:
    """创建项目运行过程中必须存在的目录。"""
    # 确保运行期依赖的输出目录已经创建好。
    settings.output_dir.mkdir(parents=True, exist_ok=True)


def validate_runtime_environment() -> None:
    """校验运行环境中的关键配置是否齐全。"""
    # 检查当前运行环境是否缺少必要的关键配置项。
    missing_vars: list[str] = []

    if not settings.database_url:
        missing_vars.append("DATABASE_URL")

    if missing_vars:
        raise WorkflowError(f"运行环境缺少关键配置: {', '.join(missing_vars)}")
