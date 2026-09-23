"""请求入口：HTTP API，把登记、查询、取消请求路由到容量与候补模块。"""
from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from capacity import Booking, CapacityError, CapacityManager, parse_date
from storage import Storage
from waitlist import Waitlist, WaitlistEntry


class BoardingService:
    """把容量与候补串起来的业务门面，所有改动即时落盘。"""

    def __init__(self, capacity: CapacityManager, waitlist: Waitlist, storage: Storage):
        self.capacity = capacity
        self.waitlist = waitlist
        self.storage = storage
        self._lock = threading.Lock()

    def _save(self) -> None:
        self.storage.save({
            "bookings": [b.to_dict() for b in self.capacity.bookings],
            "waitlist": [e.to_dict() for e in self.waitlist.entries],
        })

    def book(self, pet_id: str, start: date, nights: int) -> tuple[int, dict]:
        """登记预约：放得下直接确认，放不下进候补；已有预约/候补的宠物拒绝重复占位。"""
        with self._lock:
            if self.capacity.find(pet_id) or self.waitlist.has(pet_id):
                raise CapacityError(f"宠物 {pet_id} 已有预约或在候补中，不能重复占位")
            if self.capacity.fits(pet_id, start, nights):
                booking = self.capacity.confirm(pet_id, start, nights)
                self._save()
                return 201, {"status": "confirmed", "booking": booking.to_dict()}
            entry = self.waitlist.add(pet_id, start, nights)
            self._save()
            return 202, {
                "status": "waitlisted",
                "position": self.waitlist.position(pet_id),
                "request": entry.to_dict(),
            }

    def cancel(self, pet_id: str, today: date | None = None) -> dict:
        """入住前取消：释放床位后，候补队列自动补位。"""
        today = today or date.today()
        with self._lock:
            if self.waitlist.has(pet_id):
                self.waitlist.remove(pet_id)
                self._save()
                return {"status": "waitlist_cancelled", "pet_id": pet_id}
            booking = self.capacity.cancel(pet_id, today)
            promoted = self.waitlist.promote(self.capacity)
            self._save()
            return {
                "status": "cancelled",
                "released": booking.to_dict(),
                "promoted": [e.to_dict() for e in promoted],
            }

    def availability(self, day: date) -> dict:
        with self._lock:
            return {
                "date": day.isoformat(),
                "total_beds": self.capacity.total_beds,
                "occupied": self.capacity.occupied(day),
                "remaining": self.capacity.remaining(day),
            }

    def reservation_of(self, pet_id: str) -> dict | None:
        with self._lock:
            booking = self.capacity.find(pet_id)
            if booking:
                return {"status": "confirmed", "booking": booking.to_dict()}
            if self.waitlist.has(pet_id):
                return {"status": "waitlisted", "position": self.waitlist.position(pet_id)}
            return None


def _make_handler(service: BoardingService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PetBoarding/1.0"

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise CapacityError("请求体不是合法的 JSON")
            if not isinstance(data, dict):
                raise CapacityError("请求体应为 JSON 对象")
            return data

        def _handle(self, fn) -> None:
            try:
                fn()
            except CapacityError as e:
                self._send(409, {"error": str(e)})

        def do_POST(self) -> None:
            path = urlparse(self.path).path

            if path == "/bookings":
                def run():
                    data = self._read_json()
                    pet_id = str(data.get("pet_id") or "").strip()
                    if not pet_id:
                        raise CapacityError("缺少 pet_id")
                    nights = data.get("nights")
                    if not isinstance(nights, int) or nights < 1:
                        raise CapacityError("nights 必须是 >= 1 的整数")
                    start = parse_date(data.get("start_date"))
                    code, payload = service.book(pet_id, start, nights)
                    self._send(code, payload)
                self._handle(run)

            elif path == "/cancellations":
                def run():
                    data = self._read_json()
                    pet_id = str(data.get("pet_id") or "").strip()
                    if not pet_id:
                        raise CapacityError("缺少 pet_id")
                    self._send(200, service.cancel(pet_id))
                self._handle(run)

            else:
                self._send(404, {"error": "未知路径"})

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/availability":
                def run():
                    day_str = parse_qs(parsed.query).get("date", [None])[0]
                    if not day_str:
                        raise CapacityError("缺少查询参数 date=YYYY-MM-DD")
                    self._send(200, service.availability(parse_date(day_str)))
                self._handle(run)

            elif path.startswith("/pets/") and path.endswith("/reservation"):
                pet_id = path[len("/pets/"):-len("/reservation")].strip("/")
                result = service.reservation_of(pet_id)
                if result is None:
                    self._send(404, {"error": f"宠物 {pet_id} 没有预约或候补记录"})
                else:
                    self._send(200, result)

            else:
                self._send(404, {"error": "未知路径"})

        def log_message(self, fmt, *args):  # 保持控制台干净
            pass

    return Handler


def create_server(port: int, total_beds: int, data_file: str) -> ThreadingHTTPServer:
    storage = Storage(data_file)
    data = storage.load()
    capacity = CapacityManager(
        total_beds, [Booking.from_dict(d) for d in data["bookings"]]
    )
    waitlist = Waitlist([WaitlistEntry.from_dict(d) for d in data["waitlist"]])
    service = BoardingService(capacity, waitlist, storage)
    return ThreadingHTTPServer(("0.0.0.0", port), _make_handler(service))
