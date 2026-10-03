"""Project-wide logging configuration.

Logs to console and artifacts/logs/{YYYY-MM-DD}.log per Part II Section II.8.
"""

from __future__ import annotations

import datetime
import logging

from nasdaq100.paths import logs_dir


def setup_logger(name: str = "nasdaq100") -> logging.Logger:
    """Configure and return a logger instance with console and file handlers."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler in artifacts/logs/
    try:
        log_directory = logs_dir()
        log_directory.mkdir(parents=True, exist_ok=True)
        today_str = datetime.date.today().isoformat()
        log_file = log_directory / f"{today_str}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        # Fallback cleanly if file handler creation fails (e.g. read-only env)
        pass

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the root 'nasdaq100' namespace."""
    setup_logger("nasdaq100")
    if name.startswith("nasdaq100"):
        return logging.getLogger(name)
    return logging.getLogger(f"nasdaq100.{name}")
