"""容量与床位占用计算。

入住日期为闭区间起点，住 N 天占用日期为：
    check_in, check_in+1, ..., check_in+(N-1)
即退房日 check_in+N 当天不再占床。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping

MAX_CAPACITY = 10_000
DEFAULT_CAPACITY = 10


def parse_capacity(raw, default: int = DEFAULT_CAPACITY) -> int:
    """从环境变量解析总床位数，非法值回落到默认值。"""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(value, MAX_CAPACITY)


def stay_dates(check_in: date, days: int) -> list[date]:
    """一次寄养实际占用的全部日期。"""
    return [check_in + timedelta(days=i) for i in range(days)]


def occupancy_on(day: date, reservations: Iterable[Mapping]) -> int:
    """统计某天已确认预约占用的床位数。"""
    count = 0
    for res in reservations:
        start = _to_date(res["check_in"])
        end = start + timedelta(days=int(res["days"]))
        if start <= day < end:
            count += 1
    return count


def remaining_on(day: date, reservations: Iterable[Mapping], capacity: int) -> int:
    """某天剩余床位数（不会小于 0）。"""
    return max(0, capacity - occupancy_on(day, reservations))


def can_fit(check_in: date, days: int, reservations, capacity: int) -> bool:
    """判断整个寄养区间内是否每天都至少有 1 个空床。"""
    if days <= 0:
        return False
    occupied: dict[date, int] = {}
    for res in reservations:
        start = _to_date(res["check_in"])
        end = start + timedelta(days=int(res["days"]))
        for d in stay_dates(check_in, days):
            if start <= d < end:
                occupied[d] = occupied.get(d, 0) + 1
    return all(occupied.get(d, 0) < capacity for d in stay_dates(check_in, days))


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
