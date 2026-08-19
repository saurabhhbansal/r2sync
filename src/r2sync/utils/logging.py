"""Structured logging utilities for r2sync."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from r2sync.utils.paths import get_logs_dir


class MemoryLogHandler(logging.Handler):
    """Thread-safe in-memory ring buffer of recent log records for GUI display."""

    def __init__(self, capacity: int = 1000):
        super().__init__()
        self.capacity = capacity
        self.records: List[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "message": self.format(record),
            }
            self.records.append(entry)
            if len(self.records) > self.capacity:
                self.records.pop(0)
        except Exception:
            self.handleError(record)

    def get_records(self) -> List[dict]:
        return list(self.records)

    def clear(self) -> None:
        self.records.clear()


_memory_handler = MemoryLogHandler()


def get_memory_log_handler() -> MemoryLogHandler:
    return _memory_handler


def setup_logger(
    name: str = "r2sync",
    level: int = logging.INFO,
    log_to_file: bool = True,
    file_prefix: str = "app",
) -> logging.Logger:
    """Configure and return the root or named logger with file and console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    _memory_handler.setFormatter(formatter)
    logger.addHandler(_memory_handler)

    if log_to_file:
        try:
            logs_dir = get_logs_dir()
            today_str = datetime.now().strftime("%Y-%m-%d")
            log_file = logs_dir / f"{file_prefix}_{today_str}.log"
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            logger.addHandler(file_handler)
        except Exception as e:
            sys.stderr.write(f"Failed to setup file logger: {e}\n")

    return logger
