import time
import requests
import paramiko
import logging
from concurrent.futures import ThreadPoolExecutor
from django.core.management.base import BaseCommand
from apscheduler.schedulers.blocking import BlockingScheduler
from django.conf import settings
from django.db import connections
from cmdb.models import Server, ServerMetric

logger = logging.getLogger(__name__)

def collect_single_server(server_id):
    # 在线程开始时关闭旧连接，防止 MySQL "Gone away" 错误
    connections.close_all()
    
    try:
        server = Server.objects.get(id=server_id)
        
        # 数据结构初始化
        metrics = {
            'cpu': 0.0, 'mem': 0.0, 'disk': 0.0, 
            'load': 0.0, 'net_in': 0.0, 'net_out': 0.0,
            'disk_write_rate':0.0, 'disk_read_rate':0.0,
        }

        # ==========================================
        # 模式 A: Agent 拉取 (速度极快，保持不变)
        # ==========================================
        if server.use_agent:
            agent_url = f"http://{server.ip_address}:10050/metrics"
            try:
                resp = requests.get(agent_url, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    metrics.update(data)
                else:
                    return 
            except Exception:
                return

        # ==========================================
        # 模式 B: SSH 拉取 (核心优化：指令聚合)
        # ==========================================
        else:
            if not server.username or not server.password:
                return

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    hostname=server.ip_address, port=server.port,
                    username=server.username, password=server.password, 
                    timeout=5, banner_timeout=5
                )

                # -------------------------------------------------------
                # 核心魔法：组合命令
                # 1. 也是为了减少 RTT，一次交互拿完所有数据
                # 2. 流量计算需要间隔，我们在 Shell 里 sleep 1，并在前后打印流量
                # 3. 使用 echo "|||" 作为分隔符方便 split
                # -------------------------------------------------------
                disk_cmd = "grep -E 'sd[a-z]|vd[a-z]|nvme[0-9]n[0-9]' /proc/diskstats | awk '{r+=$6; w+=$10} END {print r, w}'"
                cmd_chain = (
                    "export TERM=dumb; "
                    "top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}'; "  # 1. CPU (us+sy)
                    "echo '|||'; "
                    "free -m | grep Mem | awk '{print $3/$2 * 100.0}'; " # 2. Mem
                    "echo '|||'; "
                    "uptime | awk -F'load average: ' '{print $2}' | awk -F',' '{print $1}'; " # 3. Load
                    "echo '|||'; "
                    "df -h / | tail -1 | awk '{print $5}' | sed 's/%//'; " # 4. Disk
                    "echo '|||'; "
                    "cat /proc/net/dev; " # 5. Net Start
                    "sleep 1; "
                    "echo '|||'; "
                    f"{disk_cmd}; "        # 6. Disk IO Start <--- 新增
                    "sleep 1; "
                    "echo '|||'; "
                    "cat /proc/net/dev; "  # 7. Net End
                    "echo '|||'; "
                    f"{disk_cmd}"          # 8. Disk IO End   <--- 新增
                )

                stdin, stdout, stderr = client.exec_command(cmd_chain, timeout=10)
                output = stdout.read().decode().strip()
                
                # --- 解析数据 ---
                parts = output.split('|||')
                if len(parts) >= 6:
                    metrics['cpu'] = float(parts[0].strip() or 0)
                    metrics['mem'] = float(parts[1].strip() or 0)
                    metrics['load'] = float(parts[2].strip() or 0)
                    metrics['disk'] = float(parts[3].strip() or 0)
                    
                    # 流量计算逻辑
                    net_start = parts[4].strip()
                    net_end = parts[5].strip()
                    metrics['net_in'], metrics['net_out'] = calculate_net_speed(net_start, net_end)
                    metrics['disk_read'], metrics['disk_write'] = calculate_disk_speed(parts[5], parts[7])
            except Exception as e:
                logger.error(f"[SSH Error] {server.hostname}: {e}")
                return
            finally:
                client.close()

        # ==========================================
        # 数据入库
        # ==========================================
        ServerMetric.objects.create(
            server=server,
            cpu_usage=round(metrics['cpu'], 1),
            mem_usage=round(metrics['mem'], 1),
            disk_usage=round(metrics['disk'], 1),
            load_1min=metrics['load'],
            net_in=metrics['net_in'],
            net_out=metrics['net_out'],
            disk_read_rate=metrics['disk_read'],
            disk_write_rate=metrics['disk_write']
        )

    except Exception as e:
        logger.error(f"[Error] {server_id}: {str(e)}")

def calculate_net_speed(start_str, end_str):
    """辅助函数：解析 /proc/net/dev 计算差值"""
    def parse_proc_net(content):
        rx, tx = 0, 0
        for line in content.split('\n'):
            if ':' in line and 'lo' not in line: # 排除 lo 回环
                parts = line.split(':')[1].split()
                if len(parts) >= 9:
                    rx += int(parts[0])
                    tx += int(parts[8])
        return rx, tx

    rx1, tx1 = parse_proc_net(start_str)
    rx2, tx2 = parse_proc_net(end_str)
    
    # 转换为 KB/s (间隔已经是1秒了)
    in_speed = round((rx2 - rx1) / 1024.0, 2)
    out_speed = round((tx2 - tx1) / 1024.0, 2)
    return in_speed, out_speed

def job_collect_all():
    logger.info("--- Start Collection Cycle ---")
    # 只取 ID，减少内存占用
    server_ids = Server.objects.filter(status='Running').values_list('id', flat=True)
    count = len(server_ids)
    if count == 0: return

    # 动态调整线程数：如果服务器少于50台，就用服务器数量；否则最大100
    # 注意：连接数过多可能会撑爆数据库连接池，需在 settings.py 调大 CONN_MAX_AGE 和 MySQL 连接数
    worker_num = min(count, 100) 

    logger.info(f"Collecting {count} servers with {worker_num} threads...")

    with ThreadPoolExecutor(max_workers=worker_num) as executor:
        executor.map(collect_single_server, server_ids)

class Command(BaseCommand):
    help = "启动监控采集进程 (Optimized)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Monitor Agent Started (Optimized)...'))
        scheduler = BlockingScheduler(timezone=settings.TIME_ZONE)
        
        # 建议采集间隔不要低于 60s，因为 SSH 连接本身有开销
        scheduler.add_job(job_collect_all, 'interval', seconds=60, id='collect_metrics', replace_existing=True, max_instances=1)
        
        try:
            job_collect_all()
            scheduler.start()
        except KeyboardInterrupt:
            self.stdout.write("Stopped.")


def calculate_disk_speed(start_str, end_str):
    """
    计算磁盘 IO 速率 (KB/s)
    输入格式: "234235 523523" (读扇区数 写扇区数)
    """
    try:
        r1, w1 = map(int, start_str.strip().split())
        r2, w2 = map(int, end_str.strip().split())

        # 扇区通常为 512 Bytes
        # 差值 * 512 / 1024 = KB
        # 因为间隔是 1 秒，所以直接就是 KB/s
        read_kb = (r2 - r1) * 512 / 1024
        write_kb = (w2 - w1) * 512 / 1024

        return round(read_kb, 2), round(write_kb, 2)
    except:
        return 0.0, 0.0