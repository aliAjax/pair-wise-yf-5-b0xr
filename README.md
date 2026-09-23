# 宠物寄养预约服务

替代电话登记的寄养管理小服务：登记宠物入住、查余位、查单只宠物预约；
床位满了自动进候补，入住前取消后最前面的候补自动补上。数据落盘，重启不丢。

纯 Python 3 标准库实现，无需安装任何依赖。

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `capacity.py` | **容量**：床位总量、已确认预约、按天余位计算、确认/取消 |
| `waitlist.py` | **候补**：FIFO 候补队列、释放床位后按顺序自动补位 |
| `api.py` | **请求入口**：HTTP 接口与业务编排（登记/取消/查询） |
| `storage.py` | 持久化：JSON 文件原子写入，重启自动恢复 |
| `main.py` | 启动入口：读取环境变量并拉起服务 |

## 启动

```bash
python3 main.py
# 可选环境变量：
#   PORT      监听端口，默认 8000
#   BEDS      床位总数，默认 5
#   DATA_FILE 数据文件，默认 boarding_data.json
BEDS=10 PORT=8000 python3 main.py
```

## 接口调用

### 1. 登记预约

```bash
curl -X POST http://localhost:8000/bookings \
  -d '{"pet_id": "A001", "start_date": "2026-10-01", "nights": 3}'
```

- 床位够 → `201` `{"status": "confirmed", "booking": {...}}`
- 床位不够 → `202` `{"status": "waitlisted", "position": 1, ...}`（进入候补）
- 该宠物已有预约或在候补中 → `409`，不能重复占位

### 2. 查看某天余位

```bash
curl "http://localhost:8000/availability?date=2026-10-01"
# {"date": "2026-10-01", "total_beds": 5, "occupied": 2, "remaining": 3}
```

### 3. 查看单只宠物的预约

```bash
curl http://localhost:8000/pets/A001/reservation
# 已确认: {"status": "confirmed", "booking": {...}}
# 候补中: {"status": "waitlisted", "position": 1}
# 无记录: 404
```

### 4. 入住前取消

```bash
curl -X POST http://localhost:8000/cancellations -d '{"pet_id": "A001"}'
```

- 取消已确认的预约会释放床位，候补队列中**排最前且放得下**的请求自动转为正式预约，
  响应里的 `promoted` 列出被补位的宠物；余位查询随即变化。
- 取消候补中的请求则直接移出队列。
- 已到入住日（含当天）之后不允许取消，返回 `409`。

## 业务规则

- 一次预约占用 `[入住日期, 入住日期+天数)` 区间内的每一天，区间内每天都需有余位才能确认。
- 同一只宠物同一时刻只能有一条已确认预约或候补记录。
- 候补按提交顺序排队；有床位释放时从队首扫描，放得下的立即补位，放不下的继续等待。
- 每次变更即时写入 `DATA_FILE`（先写临时文件再原子替换），重启后自动恢复。
