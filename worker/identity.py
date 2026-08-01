from __future__ import annotations

import socket
import uuid


def generate_worker_id() -> str:
    hostname = socket.gethostname().replace(" ", "-")[:32]
    return f"{hostname}-{uuid.uuid4().hex[:12]}"
