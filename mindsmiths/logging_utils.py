"""Application logging with a rotating local file."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_path: str | Path, level: int = logging.INFO) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_mindsmiths_configured", False):
        return
    root.setLevel(level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    root._mindsmiths_configured = True  # type: ignore[attr-defined]
