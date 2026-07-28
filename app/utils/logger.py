import logging


def configure_logging(level: str = "INFO") -> None:
    """設定應用程式共用日誌格式。"""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
