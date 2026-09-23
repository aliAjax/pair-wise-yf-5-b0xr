"""容量管理：维护床位总量、已确认预约，并计算任意日期的余位。"""
from __future__ import annotations

from datetime import date, timedelta


class CapacityError(Exception):
    """预约冲突等业务错误，message 可直接返回给调用方。"""


def parse_date(value) -> date:
    """把 YYYY-MM-DD 字符串解析为日期，格式错误时抛出业务异常。"""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise CapacityError(f"日期格式不正确: {value!r}，应为 YYYY-MM-DD")


class Booking:
    """一条已确认的寄养预约：宠物编号、入住日期、寄养天数。"""

    def __init__(self, pet_id: str, start: date, nights: int):
        self.pet_id = pet_id
        self.start = start
        self.nights = nights

    @property
    def end(self) -> date:
        """离店日期（占用 [start, end) 区间内的每一天）。"""
        return self.start + timedelta(days=self.nights)

    def covers(self, day: date) -> bool:
        return self.start <= day < self.end

    def to_dict(self) -> dict:
        return {
            "pet_id": self.pet_id,
            "start_date": self.start.isoformat(),
            "nights": self.nights,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Booking":
        return cls(str(data["pet_id"]), parse_date(data["start_date"]), int(data["nights"]))


class CapacityManager:
    """按天计算床位占用，负责确认预约与入住前取消。"""

    def __init__(self, total_beds: int, bookings=None):
        if total_beds < 1:
            raise ValueError("total_beds 必须 >= 1")
        self.total_beds = total_beds
        self.bookings = list(bookings or [])

    def occupied(self, day: date) -> int:
        return sum(1 for b in self.bookings if b.covers(day))

    def remaining(self, day: date) -> int:
        return self.total_beds - self.occupied(day)

    def find(self, pet_id: str) -> Booking | None:
        for b in self.bookings:
            if b.pet_id == pet_id:
                return b
        return None

    def fits(self, pet_id: str, start: date, nights: int) -> bool:
        """入住期间每一天都至少有一个余位，才放得下。"""
        return all(
            self.remaining(start + timedelta(days=i)) >= 1 for i in range(nights)
        )

    def confirm(self, pet_id: str, start: date, nights: int) -> Booking:
        if self.find(pet_id):
            raise CapacityError(f"宠物 {pet_id} 已有预约，不能重复占位")
        if not self.fits(pet_id, start, nights):
            raise CapacityError("床位不足，无法确认")
        booking = Booking(pet_id, start, nights)
        self.bookings.append(booking)
        return booking

    def cancel(self, pet_id: str, today: date) -> Booking:
        """入住前取消，释放占用的床位；已到入住日则不允许取消。"""
        booking = self.find(pet_id)
        if booking is None:
            raise CapacityError(f"宠物 {pet_id} 没有已确认的预约")
        if today >= booking.start:
            raise CapacityError("已到入住日或已入住，不能取消")
        self.bookings.remove(booking)
        return booking
