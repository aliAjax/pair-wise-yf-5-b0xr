"""JSON 文件持久化：启动加载、每次变更后原子写盘，重启后记录仍在。"""

from __future__ import annotations

import json
import os
import tempfile
from threading import RLock
from typing import Any


class JsonStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self.lock = RLock()

    def load(self) -> dict[str, Any]:
        with self.lock:
            if not os.path.exists(self.path):
                return {"reservations": [], "waitlist": []}
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data.setdefault("reservations", [])
            data.setdefault("waitlist", [])
            return data

    def save(self, data: dict[str, Any]) -> None:
        """同目录临时文件 + 原子替换，避免写一半导致文件损坏。"""
        with self.lock:
            directory = os.path.dirname(os.path.abspath(self.path)) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                os.replace(tmp_path, self.path)
            except BaseException:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
