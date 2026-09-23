# 宠物医院寄养服务

电话登记寄养、床位不足进候补、退订后队首自动补位的可启动服务。
**只用 Python 3 标准库，无需 pip 安装任何依赖。**

## 目录结构

| 文件 | 职责 |
| --- | --- |
| `petboarding/capacity.py` | 业务文件 ①：总容量、按天占用/余位计算、某段寄养能否放下 |
| `petboarding/waitlist.py` | 业务文件 ②：候补队列（FIFO：入队、查位置、移除、取队首） |
| `petboarding/boarding_service.py` | 业务文件 ③：请求入口——登记、取消、自动补位、余位/宠物查询、重复占位校验 |
| `petboarding/storage.py` | 基础设施：JSON 文件持久化（临时文件 + 原子替换，线程安全） |
| `app.py` | HTTP 启动入口（标准库 `http.server`） |
| `self_check.py` | 端到端自检脚本（不启动 HTTP，直接跑全部业务规则） |

## 启动

需要 Python 3.8+。

```bash
python3 app.py
# 宠物寄养服务已启动：http://127.0.0.1:8000
# 总床位 10，数据文件 data/boarding.json
```

可用环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BOARDING_CAPACITY` | `10` | 总床位数 |
| `BOARDING_HOST` | `127.0.0.1` | 监听地址（对外可用 `0.0.0.0`） |
| `BOARDING_PORT` | `8000` | 监听端口 |
| `BOARDING_DATA` | `data/boarding.json` | 数据文件路径 |

例：`BOARDING_CAPACITY=30 BOARDING_PORT=9000 python3 app.py`

所有预约与候补在每次变更后立即写入 JSON 文件，**重启进程后记录仍在**。

## API 调用说明

请求/响应均为 JSON，日期统一 `YYYY-MM-DD`。

### 1. 登记寄养 `POST /reservations`

请求体：`pet_id`（宠物编号）、`check_in`（入住日期）、`days`（寄养天数，正整数）。

- 床位足够 → `201`，`status: "confirmed"`。
- 入住区间内任意一天满房 → `201`，`status: "waiting"`，进入候补队列并返回位置。
- 该宠物已有进行中/未来的预约，或已在候补队列 → `409`（同一只宠物不能重复占位）。
- 参数缺失/格式错误、入住日期早于今天 → `400`。

```bash
curl -s -X POST http://127.0.0.1:8000/reservations \
  -H 'Content-Type: application/json' \
  -d '{"pet_id":"P001","check_in":"2026-10-01","days":3}'
```

确认：

```json
{ "status": "confirmed",
  "reservation": { "id": "R0001", "pet_id": "P001",
    "check_in": "2026-10-01", "days": 3, "check_out": "2026-10-04",
    "source": "request", "created_at": "2026-09-23T22:00:00" } }
```

满房候补：

```json
{ "status": "waiting",
  "waitlist_entry": { "position": 1, "pet_id": "P003",
    "check_in": "2026-10-01", "days": 3 } }
```

> 床位口径：住 N 天占用入住日到退房日前一天（`check_out = check_in + N`，
> 退房当天的床位可给下一只宠物）。

### 2. 查某天余位 `GET /availability?date=YYYY-MM-DD`

```bash
curl -s 'http://127.0.0.1:8000/availability?date=2026-10-01'
# {"date":"2026-10-01","capacity":10,"occupied":8,"remaining":2}
```

### 3. 查单只宠物的预约 `GET /pets?pet_id=P001`

返回当前确认预约（`reservation`，没有则 `null`）、候补状态（`waiting`）
以及已结束的历史预约。候补自动补位后再查，`waiting` 会消失、`reservation` 出现。

### 4. 取消（入住前）`POST /cancellations`

```bash
curl -s -X POST http://127.0.0.1:8000/cancellations \
  -H 'Content-Type: application/json' -d '{"pet_id":"P001"}'
```

- 取消的是**确认预约且入住日还没到**：释放床位，候补队列**最前面的请求自动补上**，
  补位结果在响应的 `promoted` 数组里；紧接着的余位/宠物查询会立即反映新状态。
- 队首请求若因房型区间仍放不下，则保留其队首位置，本次不跳过它往后补（先到先得）。
- 取消的是候补请求：仅从候补队列移除，不影响床位。
- 已到入住日期的确认预约不能再取消（`409`）；查无此宠物 → `404`。

### 5. 其它查询

- `GET /reservations`：全部确认预约。
- `GET /waitlist`：候补队列（含位置）。
- `GET /health`：存活探针。

## 自检

```bash
python3 self_check.py
```

覆盖：满房进候补、重复占位拒绝、余位查询、入住前取消触发队首自动补位、
查询结果随动、候补取消、重启持久化、参数校验（预期输出 `28 通过，0 失败`）。

## 关键业务规则一览

1. 登记只需宠物编号 + 入住日期 + 寄养天数。
2. 整个寄养区间每天都有空床才确认，否则整条请求进候补（不做部分日期确认）。
3. 同一只宠物同时只能有一个进行中/未来的确认预约，且只能在候补队列里出现一次；
   已完全结束（退房日 ≤ 今天）的历史预约不影响再次登记。
4. 入住前取消确认预约 → 立即释放 → 队首候补自动补位并落盘。
5. 所有写操作在同一把进程内锁内完成，数据用“临时文件 + rename”原子写盘。
