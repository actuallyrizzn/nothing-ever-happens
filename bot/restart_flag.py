"""Optional restart handoff for web-only operators.

When ``NEH_RESTART_FLAG_PATH`` is set on the server, a successful Admin → Settings
save can create a flag file; a **cron** job (see ``scripts/neh_cron_restart.sh``)
removes the flag and restarts the bot. The running Python process does not restart
itself (avoids killing the HTTP handler mid-request).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def restart_flag_path() -> Path | None:
    raw = (os.getenv("NEH_RESTART_FLAG_PATH") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def restart_via_flag_enabled() -> bool:
    return restart_flag_path() is not None


def write_restart_flag_after_settings_save() -> bool:
    """Create the flag file atomically. Returns False if not configured or on I/O error."""
    path = restart_flag_path()
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        payload = f"requested_at={time.time():.3f}\n"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("neh_restart_flag_write_failed: %s", exc)
        return False
    logger.info("neh_restart_flag_written", extra={"path": str(path)})
    return True
