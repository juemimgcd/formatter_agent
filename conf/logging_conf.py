import sys
from loguru import logger


def setup_logger():
    logger.remove()

    # Ensure `{extra[module]}` is always present even if a call site forgets to bind.
    logger.configure(extra={"module": "unknown"})

    logger.add(
        sys.stdout,
        level="INFO",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} |"
            "{level} |"
            "{extra[module]} |"
            "{message}"
        )
    )



app_logger = logger






