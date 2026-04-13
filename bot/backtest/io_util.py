from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any, Iterator


class ArchiveFileLock:
    """Exclusive non-blocking-friendly lock under ``archive_root``."""

    def __init__(self, archive_root: Path, name: str = "ingest.lock") -> None:
        self._path = Path(archive_root) / name
        self._fh: Any = None

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a+", encoding="utf-8")
        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)

    def __exit__(self, *args: object) -> None:
        if self._fh is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            yield obj
