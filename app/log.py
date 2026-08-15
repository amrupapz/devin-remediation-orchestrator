import json
import logging
import sys
import time

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger = logging.getLogger("orchestrator")
_logger.setLevel(logging.INFO)
_logger.handlers = [_handler]


def event(name: str, **fields) -> None:
    """Emit one structured JSON log line per state transition."""
    _logger.info(json.dumps({"ts": time.time(), "event": name, **fields}))
