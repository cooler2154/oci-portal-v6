# backend/core/logging_setup.py
# ---------------------------------------------------------------
# Configures two loggers:
#   - app_logger  : DEBUG/INFO/WARN/ERROR  → debug.log + console
#   - audit_logger: INFO only              → audit.log
#
# Usage:
#   from core.logging_setup import app_logger, audit_logger
#   app_logger.info("Something happened")
#   audit_logger.info("user=x action=STOP instance=y")
# ---------------------------------------------------------------

import logging
import sys
from logging.handlers import RotatingFileHandler
from core.config import settings


def _make_logger(name: str, filepath: str, level: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(module)-12s] %(message)s",
        datefmt="%H:%M:%S.%f"[:-3],
    )

    # Rotating file handler — max 5 MB, keep 3 backups
    fh = RotatingFileHandler(filepath, maxBytes=5_000_000, backupCount=3)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Also print to stdout so Docker logs work out of the box
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


# Application / debug logger
app_logger = _make_logger(
    "oci_portal",
    settings.LOG_FILE,
    settings.LOG_LEVEL,
)

# Audit logger — always INFO, separate file
audit_logger = _make_logger(
    "oci_portal.audit",
    settings.AUDIT_LOG_FILE,
    "INFO",
)
