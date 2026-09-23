"""端到端自检：直接驱动业务层（不启动 HTTP）。

用法：python3 self_check.py
会使用独立的临时数据文件，不影响正式数据。
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

from petboarding.boarding_service import BoardingService, ServiceError
from petboarding.storage import JsonStore

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def expect_error(name: str, status: int, fn) -> None:
    try:
        fn()
    except ServiceError as exc:
        check(name, exc.status == status, f"得到 {exc.status}/{exc.code}")
        return
    check(name, False, "未返回错误")


def main() -> None:
    tmp_dir = tempfile.mkdtemp(prefix="boarding_check_")
    data_path = os.path.join(tmp_dir, "boarding.json")
    today = date.today()
    d1 = (today + timedelta(days=3)).isoformat()
    d2 = (today + timedelta(days=4)).isoformat()

    print("== 1. 容量 2，登记 3 只宠物：前 2 个确认，第 3 个候补 ==")
    svc = BoardingService(JsonStore(data_path), capacity=2)
    _, r1 = svc.create_request("P001", d1, 2)
    _, r2 = svc.create_request("P002", d1, 2)
    _, r3 = svc.create_request("P003", d1, 2)
    check("P001 确认", r1["status"] == "confirmed")
    check("P002 确认", r2["status"] == "confirmed")
    check("P003 候补", r3["status"] == "waiting")
    check("P003 候补位置为 1", r3["waitlist_entry"]["position"] == 1)

    print("== 2. 余位查询随状态变化 ==")
    avail = svc.availability(d1)
    check("入住日余位 0", avail["remaining"] == 0, str(avail))
    avail_next = svc.availability((today + timedelta(days=10)).isoformat())
    check("空闲日余位 2", avail_next["remaining"] == 2)

    print("== 3. 同一只宠物不能重复占位 ==")
    expect_error("P001 再次登记被拒(409)", 409,
                 lambda: svc.create_request("P001", d2, 1))
    expect_error("候补 P003 再次登记被拒(409)", 409,
                 lambda: svc.create_request("P003", d2, 1))

    print("== 4. 单只宠物查询 ==")
    status = svc.pet_status("P001")
    check("P001 有确认预约", status["reservation"] is not None)
    check("P001 不在候补", status["waiting"] is None)
    status3 = svc.pet_status("P003")
    check("P003 在候补第 1 位", status3["waiting"]["position"] == 1)

    print("== 5. 入住前取消 P001，队首 P003 自动补位 ==")
    result = svc.cancel_request("P001")
    check("取消类型为 reservation", result["cancelled"] == "reservation")
    check("P003 自动补上",
          [r["pet_id"] for r in result["promoted"]] == ["P003"],
          str(result["promoted"]))
    check("候补队列清空", svc.list_waitlist()["count"] == 0)
    avail = svc.availability(d1)
    check("余位仍为 0（P003 补上）", avail["remaining"] == 0, str(avail))
    status3 = svc.pet_status("P003")
    check("P003 现在是确认预约且来源为候补",
          status3["reservation"] is not None
          and status3["reservation"]["source"] == "waitlist")

    print("== 6. 候补请求自己取消；取消确认预约后顺延补位 ==")
    svc.cancel_request("P002")  # 释放 1 床，队列空，无补位
    # P004 长住 5 天占掉最后 1 床；P005、P006 同样 5 天只能排队
    _, r4 = svc.create_request("P004", d1, 5)
    _, r5 = svc.create_request("P005", d1, 5)
    _, r6 = svc.create_request("P006", d1, 5)
    check("P004 确认", r4["status"] == "confirmed")
    check("P005 候补第 1", r5["waitlist_entry"]["position"] == 1)
    check("P006 候补第 2", r6["waitlist_entry"]["position"] == 2)
    result = svc.cancel_request("P005")
    check("取消候补返回 waitlist", result["cancelled"] == "waitlist")
    check("P006 升为队首",
          svc.pet_status("P006")["waiting"]["position"] == 1)
    # 取消 P004 的确认预约，队首 P006 自动补上
    result = svc.cancel_request("P004")
    check("P006 顺延补位",
          [r["pet_id"] for r in result["promoted"]] == ["P006"])

    print("== 7. 重启后记录仍在 ==")
    svc2 = BoardingService(JsonStore(data_path), capacity=2)
    pets = {r["pet_id"] for r in svc2.list_reservations()["reservations"]}
    check("确认预约恢复(P003/P006，已取消的不在)",
          pets == {"P003", "P006"}, str(pets))
    check("候补队列恢复为空", svc2.list_waitlist()["count"] == 0)

    print("== 8. 参数校验 ==")
    expect_error("缺 pet_id", 400, lambda: svc2.create_request("", d1, 1))
    expect_error("日期格式错误", 400,
                 lambda: svc2.create_request("P999", "2026/10/01", 1))
    expect_error("天数为 0", 400, lambda: svc2.create_request("P999", d1, 0))
    expect_error("取消不存在的宠物", 404, lambda: svc2.cancel_request("NOPE"))

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
