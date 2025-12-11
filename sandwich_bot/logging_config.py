"""
Logging configuration for the sandwich bot application.

Usage:
    from sandwich_bot.logging_config import setup_logging
    setup_logging()  # Call once at application startup

Environment variables:
    LOG_LEVEL: Set to DEBUG, INFO, WARNING, ERROR, or CRITICAL (default: INFO)
"""
import logging
import os
import sys


def setup_logging(level: str = None) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               If not provided, reads from LOG_LEVEL env var, defaults to INFO.
    """
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Validate level
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if level not in valid_levels:
        level = "INFO"

    numeric_level = getattr(logging, level)

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    # Set specific loggers
    logging.getLogger("sandwich_bot").setLevel(numeric_level)

    # Reduce noise from third-party libraries in non-debug mode
    if level != "DEBUG":
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.debug("Logging configured at %s level", level)
