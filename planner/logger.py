import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(os.getenv("PLANNER_LOG_DIR", "logs"))
_LOG_FILE = _LOG_DIR / "planner.log"
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_LEVEL = os.getenv("PLANNER_LOG_LEVEL", "INFO").upper()


def get_logger(name: str = "planner") -> logging.Logger:
    """返回单例 logger，控制台 + 滚动文件双输出。多次调用幂等。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(_LEVEL)
    logger.propagate = False
    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as e:
        logger.warning("Cannot create log file %s: %s", _LOG_FILE, e)

    return logger
