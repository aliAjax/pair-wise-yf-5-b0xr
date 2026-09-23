"""持久化：把预约与候补写入本地 JSON 文件，重启后自动恢复。"""
from __future__ import annotations

import json
import os
import threading


class Storage:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return {"bookings": [], "waitlist": []}
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("bookings", [])
        data.setdefault("waitlist", [])
        return data

    def save(self, data: dict) -> None:
        """先写临时文件再原子替换，避免中途断电留下半个文件。"""
        tmp = self.path + ".tmp"
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
