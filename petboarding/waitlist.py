"""候补队列：先到先得（FIFO），按加入顺序自动补位。"""

from __future__ import annotations

from datetime import date
from itertools import count
from typing import Optional


class Waitlist:
    """内存中的候补队列，条目由 boarding_service 统一持久化。"""

    def __init__(self, entries: Optional[list[dict]] = None) -> None:
        self._entries: list[dict] = list(entries or [])
        self._seq = count(
            max((int(e.get("seq", 0)) for e in self._entries), default=0) + 1
        )

    @property
    def entries(self) -> list[dict]:
        """按候补先后顺序返回条目（外部不要直接修改）。"""
        return self._entries

    def position_of(self, pet_id: str) -> Optional[int]:
        """返回宠物在候补队列中的位置（从 1 开始），不在队列返回 None。"""
        for index, entry in enumerate(self._entries):
            if entry["pet_id"] == pet_id:
                return index + 1
        return None

    def contains(self, pet_id: str) -> bool:
        return self.position_of(pet_id) is not None

    def add(self, pet_id: str, check_in: date, days: int) -> dict:
        entry = {
            "pet_id": pet_id,
            "check_in": check_in.isoformat(),
            "days": days,
            "seq": next(self._seq),
        }
        self._entries.append(entry)
        return entry

    def remove(self, pet_id: str) -> Optional[dict]:
        """宠物主动取消候补时移除其条目。"""
        for index, entry in enumerate(self._entries):
            if entry["pet_id"] == pet_id:
                return self._entries.pop(index)
        return None

    def pop_front(self) -> Optional[dict]:
        if self._entries:
            return self._entries.pop(0)
        return None

    def __len__(self) -> int:
        return len(self._entries)
