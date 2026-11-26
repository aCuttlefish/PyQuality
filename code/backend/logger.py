import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_logger = logging.getLogger("pyquality")
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    _logger.addHandler(fh)
    _logger.addHandler(sh)


def get_logger(name: str = "pyquality") -> logging.Logger:
    return _logger.getChild(name) if name != "pyquality" else _logger


def log_request(method: str, path: str, status: int, duration_ms: float, **extra) -> None:
    msg = f"{method} {path} -> {status} ({duration_ms:.0f}ms)"
    if extra:
        msg += " " + " ".join(f"{k}={v}" for k, v in extra.items())
    if status >= 500:
        _logger.error(msg)
    elif status >= 400:
        _logger.warning(msg)
    else:
        _logger.info(msg)