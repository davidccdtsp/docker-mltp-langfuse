import logging
import os

import requests as http_client

_LOKI_URL = os.environ.get("LOKI_URL", "http://alloy:3100/loki/api/v1/push")


class _LokiHandler(logging.Handler):
    """Pushes each log line to Loki via HTTP. Fails silently if Loki is unavailable."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "streams": [{
                    "stream": {"job": "trace-generator", "level": record.levelname.lower()},
                    "values": [[str(int(record.created * 1e9)), self.format(record)]],
                }]
            }
            http_client.post(_LOKI_URL, json=payload, timeout=2)
        except Exception:
            pass


logger = logging.getLogger("trace-generator")
logger.setLevel(logging.INFO)
_handler = _LokiHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_handler)
