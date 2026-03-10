# cmdb/agent_code.py

AGENT_SCRIPT_CONTENT = r"""
import json
import psutil
import time
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# === 配置区域 ===
HOST_PORT = 10050 
# =================

class MetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return # 静默模式，不输出访问日志

    def do_GET(self):
        if self.path != '/metrics':
            self.send_response(404)
            self.end_headers()
            return

        try:
            # 1. 流量与磁盘IO采样 (阻塞0.5秒计算速率)
            n1 = psutil.net_io_counters()
            d1 = psutil.disk_io_counters() # 第一次采样磁盘

            time.sleep(0.5)

            n2 = psutil.net_io_counters()
            d2 = psutil.disk_io_counters() # 第二次采样磁盘

            # 计算网络速率 KB/s
            net_in = round((n2.bytes_recv - n1.bytes_recv) / 1024 / 0.5, 2)
            net_out = round((n2.bytes_sent - n1.bytes_sent) / 1024 / 0.5, 2)

            # 计算磁盘速率 KB/s
            disk_read = round((d2.read_bytes - d1.read_bytes) / 1024 / 0.5, 2)
            disk_write = round((d2.write_bytes - d1.write_bytes) / 1024 / 0.5, 2)

            # 2. 采集基础指标
            data = {
                "cpu": psutil.cpu_percent(interval=None),
                "mem": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage('/').percent,
                "net_in": net_in,
                "net_out": net_out,
                "disk_read": disk_read,   # 新增
                "disk_write": disk_write, # 新增
                "load": 0
            }
            # 负载 (Windows下可能报错，需try)
            try: 
                if hasattr(psutil, 'getloadavg'):
                    data["load"] = psutil.getloadavg()[0]
            except: pass

            # 3. 返回 JSON
            response = json.dumps(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(response)

        except Exception as e:
            self.send_response(500)
            self.wfile.write(str(e).encode())

def run():
    # 绑定 0.0.0.0 允许外部访问
    server_address = ('0.0.0.0', HOST_PORT)
    httpd = HTTPServer(server_address, MetricsHandler)
    print(f"AiOps Agent is running on port {HOST_PORT}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    run()
"""