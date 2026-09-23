"""宠物寄养服务 HTTP 入口（仅依赖 Python 标准库）。

启动：
    python3 app.py
环境变量：
    BOARDING_CAPACITY  总床位数，默认 10
    BOARDING_HOST      监听地址，默认 127.0.0.1
    BOARDING_PORT      监听端口，默认 8000
    BOARDING_DATA      数据文件路径，默认 data/boarding.json
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from petboarding.boarding_service import BoardingService, ServiceError
from petboarding.capacity import parse_capacity
from petboarding.storage import JsonStore

CAPACITY = parse_capacity(os.environ.get("BOARDING_CAPACITY"), default=10)
DATA_FILE = os.environ.get("BOARDING_DATA", "data/boarding.json")

service = BoardingService(JsonStore(DATA_FILE), CAPACITY)


class Handler(BaseHTTPRequestHandler):
    server_version = "PetBoarding/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = _single_values(parse_qs(parsed.query))
        try:
            if parsed.path == "/availability":
                self._write_json(200, service.availability(params.get("date")))
            elif parsed.path == "/pets":
                self._write_json(200, service.pet_status(_require(params, "pet_id")))
            elif parsed.path == "/reservations":
                self._write_json(200, service.list_reservations())
            elif parsed.path == "/waitlist":
                self._write_json(200, service.list_waitlist())
            elif parsed.path == "/health":
                self._write_json(200, {"status": "ok"})
            else:
                self._write_json(404, {"error": "not_found", "message": "路径不存在"})
        except ServiceError as exc:
            self._write_json(exc.status, {"error": exc.code, "message": exc.message})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_body()
        if isinstance(body, ServiceError):
            self._write_json(
                body.status, {"error": body.code, "message": body.message}
            )
            return
        try:
            if parsed.path == "/reservations":
                status, payload = service.create_request(
                    body.get("pet_id"), body.get("check_in"), body.get("days")
                )
                self._write_json(status, payload)
            elif parsed.path == "/cancellations":
                self._write_json(
                    200, service.cancel_request(_require(body, "pet_id"))
                )
            else:
                self._write_json(404, {"error": "not_found", "message": "路径不存在"})
        except ServiceError as exc:
            self._write_json(exc.status, {"error": exc.code, "message": exc.message})

    # ------------------------------------------------------------------ #
    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ServiceError(400, "invalid_json", "请求体必须是合法 JSON")
        if not isinstance(data, dict):
            return ServiceError(400, "invalid_json", "请求体必须是 JSON 对象")
        return data

    def _write_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def _single_values(parsed: dict[str, list[str]]) -> dict[str, str]:
    return {key: values[0] for key, values in parsed.items() if values}


def _require(values: dict, key: str) -> str:
    value = values.get(key)
    if value is None or not str(value).strip():
        raise ServiceError(400, f"missing_{key}", f"缺少参数：{key}")
    return value


def main() -> None:
    host = os.environ.get("BOARDING_HOST", "127.0.0.1")
    port = int(os.environ.get("BOARDING_PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"宠物寄养服务已启动：http://{host}:{port}")
    print(f"总床位 {CAPACITY}，数据文件 {DATA_FILE}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务……")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
