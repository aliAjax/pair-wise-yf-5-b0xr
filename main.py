"""启动入口：读取环境变量配置，加载持久化数据，启动 HTTP 服务。"""
import os

from api import create_server

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    total_beds = int(os.environ.get("BEDS", "5"))
    data_file = os.environ.get("DATA_FILE", "boarding_data.json")

    server = create_server(port, total_beds, data_file)
    print(f"宠物寄养服务已启动: http://localhost:{port}  (床位 {total_beds}, 数据文件 {data_file})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止，数据已保存。")
