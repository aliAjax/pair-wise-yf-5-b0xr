"""寄养请求入口：预约登记、取消、候补与自动补位、各类查询。

业务规则
--------
1. 登记 pet_id + check_in(YYYY-MM-DD) + days；床位足够直接确认。
2. 床位不足（入住区间内任意一天满房）时，请求进入候补队列（FIFO）。
3. 同一只宠物不能重复占位：已有“进行中/未来”的确认预约，或已在候补
   队列中时，新的请求会被拒绝（409）。已经全部结束（退房日 <= 今天）
   的历史预约不影响再次登记。
4. 入住前取消确认预约会释放床位，候补队列最前面的请求自动补上；
   若队首请求仍放不下，则保留其队首位置，本次不继续往后补（先到先得）。
5. 候补请求也可以随时取消；候补状态下不占用床位。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from threading import RLock
from typing import Any, Optional

from .capacity import can_fit, occupancy_on
from .storage import JsonStore
from .waitlist import Waitlist


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class BoardingService:
    def __init__(self, store: JsonStore, capacity: int) -> None:
        self.store = store
        self.capacity = capacity
        self.lock = RLock()
        data = store.load()
        self.reservations: list[dict] = data["reservations"]
        self.waitlist = Waitlist(data["waitlist"])

    # ------------------------------------------------------------------ #
    # 登记
    # ------------------------------------------------------------------ #
    def create_request(
        self,
        pet_id: str,
        check_in_raw: Any,
        days_raw: Any,
        today: Optional[date] = None,
    ) -> tuple[int, dict]:
        pet_id = _required_pet_id(pet_id)
        check_in = _parse_date(check_in_raw, "check_in")
        days = _parse_days(days_raw)
        today = today or date.today()
        if check_in < today:
            raise ServiceError(400, "invalid_date", "入住日期不能早于今天")

        with self.lock:
            if self._active_reservation(pet_id, today) is not None:
                raise ServiceError(
                    409,
                    "duplicate_pet",
                    f"宠物 {pet_id} 已有进行中或未来的预约，不能重复占位",
                )
            if self.waitlist.contains(pet_id):
                raise ServiceError(
                    409,
                    "already_waiting",
                    f"宠物 {pet_id} 已在候补队列中，不能重复登记",
                )

            if can_fit(check_in, days, self.reservations, self.capacity):
                record = self._confirm(pet_id, check_in, days, source="request")
                self._persist()
                return 201, {"status": "confirmed", "reservation": record}

            entry = self.waitlist.add(pet_id, check_in, days)
            self._persist()
            return 201, {
                "status": "waiting",
                "waitlist_entry": self._public_wait_entry(
                    entry, self.waitlist.position_of(pet_id)
                ),
            }

    # ------------------------------------------------------------------ #
    # 取消 + 自动补位
    # ------------------------------------------------------------------ #
    def cancel_request(self, pet_id: str, today: Optional[date] = None) -> dict:
        pet_id = _required_pet_id(pet_id)
        today = today or date.today()
        with self.lock:
            waiting = self.waitlist.remove(pet_id)
            if waiting is not None:
                self._persist()
                return {"cancelled": "waitlist", "pet_id": pet_id, "promoted": []}

            target = self._find_reservation(pet_id)
            if target is None:
                raise ServiceError(
                    404, "not_found", f"未找到宠物 {pet_id} 的预约或候补"
                )
            if date.fromisoformat(target["check_in"]) <= today:
                raise ServiceError(
                    409,
                    "too_late_to_cancel",
                    "已到入住日期，不再受理入住前取消",
                )

            self.reservations.remove(target)
            promoted = self._promote_waitlist(today)
            self._persist()
            return {
                "cancelled": "reservation",
                "pet_id": pet_id,
                "freed_reservation": self._public_reservation(target),
                "promoted": promoted,
            }

    def _promote_waitlist(self, today: date) -> list[dict]:
        """释放床位后，队首候补放得下就补上；放不下则停止并保留队首。"""
        promoted: list[dict] = []
        while self.waitlist.entries:
            head = self.waitlist.entries[0]
            pet_id = head["pet_id"]
            check_in = date.fromisoformat(head["check_in"])
            days = int(head["days"])
            if check_in < today:
                # 入住日已过的候补直接丢弃，继续尝试后面的请求
                self.waitlist.pop_front()
                continue
            if not can_fit(check_in, days, self.reservations, self.capacity):
                break
            self.waitlist.pop_front()
            # 双保险：补位宠物若已有进行中预约则跳过（正常不会发生）
            if self._active_reservation(pet_id, today) is None:
                promoted.append(
                    self._confirm(pet_id, check_in, days, source="waitlist")
                )
        return promoted

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def availability(self, day_raw: Any) -> dict:
        day = _parse_date(day_raw, "date")
        with self.lock:
            used = occupancy_on(day, self.reservations)
            return {
                "date": day.isoformat(),
                "capacity": self.capacity,
                "occupied": used,
                "remaining": max(0, self.capacity - used),
            }

    def pet_status(self, pet_id: str, today: Optional[date] = None) -> dict:
        pet_id = _required_pet_id(pet_id)
        today = today or date.today()
        with self.lock:
            active = self._active_reservation(pet_id, today)
            historical = [
                self._public_reservation(r)
                for r in self.reservations
                if r["pet_id"] == pet_id
                and _check_out(r) <= today
                and r is not active
            ]
            position = self.waitlist.position_of(pet_id)
            waiting_entry = None
            if position is not None:
                waiting_entry = self._public_wait_entry(
                    self.waitlist.entries[position - 1], position
                )
            return {
                "pet_id": pet_id,
                "reservation": self._public_reservation(active),
                "waiting": waiting_entry,
                "historical_reservations": historical,
            }

    def list_reservations(self) -> dict:
        with self.lock:
            return {
                "capacity": self.capacity,
                "count": len(self.reservations),
                "reservations": [
                    self._public_reservation(r) for r in self.reservations
                ],
            }

    def list_waitlist(self) -> dict:
        with self.lock:
            return {
                "count": len(self.waitlist),
                "waitlist": [
                    self._public_wait_entry(entry, index + 1)
                    for index, entry in enumerate(self.waitlist.entries)
                ],
            }

    # ------------------------------------------------------------------ #
    # 内部辅助（调用方须已持有 self.lock）
    # ------------------------------------------------------------------ #
    def _confirm(
        self, pet_id: str, check_in: date, days: int, source: str
    ) -> dict:
        record = {
            "id": self._new_reservation_id(),
            "pet_id": pet_id,
            "check_in": check_in.isoformat(),
            "days": days,
            "check_out": (check_in + timedelta(days=days)).isoformat(),
            "source": source,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.reservations.append(record)
        return record

    def _new_reservation_id(self) -> str:
        # 用已有最大序号 +1，避免取消后编号复用
        max_num = 0
        for res in self.reservations:
            raw = str(res.get("id", ""))
            if raw.startswith("R"):
                try:
                    max_num = max(max_num, int(raw[1:].split("-", 1)[0]))
                except ValueError:
                    continue
        return f"R{max_num + 1:04d}"

    def _persist(self) -> None:
        self.store.save(
            {
                "capacity": self.capacity,
                "reservations": self.reservations,
                "waitlist": self.waitlist.entries,
            }
        )

    def _find_reservation(self, pet_id: str) -> Optional[dict]:
        for res in self.reservations:
            if res["pet_id"] == pet_id:
                return res
        return None

    def _active_reservation(self, pet_id: str, today: date) -> Optional[dict]:
        """未结束（退房日 > 今天）的确认预约，含正在寄养中的。"""
        for res in self.reservations:
            if res["pet_id"] == pet_id and _check_out(res) > today:
                return res
        return None

    @staticmethod
    def _public_reservation(record: Optional[dict]) -> Optional[dict]:
        if record is None:
            return None
        return {
            "id": record["id"],
            "pet_id": record["pet_id"],
            "check_in": record["check_in"],
            "days": record["days"],
            "check_out": record["check_out"],
            "source": record.get("source", "request"),
            "created_at": record.get("created_at"),
        }

    @staticmethod
    def _public_wait_entry(entry: dict, position: int) -> dict:
        return {
            "position": position,
            "pet_id": entry["pet_id"],
            "check_in": entry["check_in"],
            "days": entry["days"],
        }


def _check_out(record: dict) -> date:
    return date.fromisoformat(record["check_in"]) + timedelta(
        days=int(record["days"])
    )


# ---------------------------------------------------------------------- #
# 入参校验
# ---------------------------------------------------------------------- #
def _required_pet_id(value: Any) -> str:
    if value is None or not str(value).strip():
        raise ServiceError(400, "missing_pet_id", "pet_id 不能为空")
    pet_id = str(value).strip()
    if len(pet_id) > 64:
        raise ServiceError(400, "invalid_pet_id", "pet_id 最长 64 个字符")
    return pet_id


def _parse_days(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise ServiceError(400, "invalid_days", "days 必须是正整数")
    if days <= 0:
        raise ServiceError(400, "invalid_days", "寄养天数必须大于 0")
    if days > 3650:
        raise ServiceError(400, "invalid_days", "单次寄养不能超过 3650 天")
    return days


def _parse_date(value: Any, field: str) -> date:
    if value is None or not str(value).strip():
        raise ServiceError(
            400, f"missing_{field}", f"{field} 不能为空，格式 YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ServiceError(
            400, f"invalid_{field}", f"{field} 日期格式应为 YYYY-MM-DD"
        )
