"""候补队列：床位不足时排队，有位置释放后按先后顺序自动补位。"""
from __future__ import annotations

from datetime import date

from capacity import parse_date


class WaitlistEntry:
    """一条候补请求，字段与正式预约相同。"""

    def __init__(self, pet_id: str, start: date, nights: int):
        self.pet_id = pet_id
        self.start = start
        self.nights = nights

    def to_dict(self) -> dict:
        return {
            "pet_id": self.pet_id,
            "start_date": self.start.isoformat(),
            "nights": self.nights,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WaitlistEntry":
        return cls(str(data["pet_id"]), parse_date(data["start_date"]), int(data["nights"]))


class Waitlist:
    """先进先出的候补队列，列表顺序即排队顺序。"""

    def __init__(self, entries=None):
        self.entries = list(entries or [])

    def has(self, pet_id: str) -> bool:
        return any(e.pet_id == pet_id for e in self.entries)

    def position(self, pet_id: str) -> int | None:
        """返回 1 开始的排队位次，不在队列中返回 None。"""
        for i, e in enumerate(self.entries):
            if e.pet_id == pet_id:
                return i + 1
        return None

    def add(self, pet_id: str, start: date, nights: int) -> WaitlistEntry:
        entry = WaitlistEntry(pet_id, start, nights)
        self.entries.append(entry)
        return entry

    def remove(self, pet_id: str) -> WaitlistEntry | None:
        for e in self.entries:
            if e.pet_id == pet_id:
                self.entries.remove(e)
                return e
        return None

    def promote(self, capacity) -> list[WaitlistEntry]:
        """有床位释放后，按排队顺序扫描：排在前面的请求只要现在放得下，
        就自动转为正式预约；放不下的继续留在队列里等下一次机会。"""
        promoted, remaining = [], []
        for entry in self.entries:
            if capacity.find(entry.pet_id) is None and capacity.fits(
                entry.pet_id, entry.start, entry.nights
            ):
                capacity.confirm(entry.pet_id, entry.start, entry.nights)
                promoted.append(entry)
            else:
                remaining.append(entry)
        self.entries = remaining
        return promoted
