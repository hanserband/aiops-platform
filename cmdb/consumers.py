import json
import time
import threading
import paramiko
import re
import pyte
from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer
from django.utils import timezone
from django.core.files.base import ContentFile
from .models import Server, TerminalLog, HighRiskAudit


class SSHConsumer(WebsocketConsumer):
    def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            self.close()
            return

        self.server_id = self.scope['url_route']['kwargs'].get('id')
        query_string = self.scope.get('query_string', b'').decode()
        params = dict(x.split('=') for x in query_string.split('&') if '=' in x)

        raw_room_id = params.get('room')
        if raw_room_id:
            self.mode = 'guest'
            self.room_id = re.sub(r'[^a-zA-Z0-9\-\.]', '-', raw_room_id)
        else:
            self.mode = 'host'
            self.room_id = re.sub(r'[^a-zA-Z0-9\-\.]', '-', self.channel_name)

        # Pyte 屏幕初始化
        self.screen = pyte.Screen(80, 24)
        self.stream = pyte.Stream(self.screen)

        self.ssh = None
        self.chan = None
        self.log_buffer = []
        self.pending_command = None

        try:
            async_to_sync(self.channel_layer.group_add)(self.room_id, self.channel_name)
        except Exception:
            self.close()
            return

        self.accept()

        if self.mode == 'host':
            self.init_ssh_connection()
        else:
            self.send(json.dumps({'data': f'\r\n\x1b[33m[System] Joined Room: {self.room_id}\x1b[0m\r\n'}))

    def init_ssh_connection(self):
        try:
            self.server = Server.objects.get(id=self.server_id)
            self.terminal_log = TerminalLog.objects.create(
                user=self.user, server=self.server, channel_name=self.channel_name
            )
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(
                hostname=self.server.ip_address, port=self.server.port,
                username=self.server.username, password=self.server.password,
                timeout=10
            )
            self.chan = self.ssh.invoke_shell(term='xterm')

            t = threading.Thread(target=self.loop_read)
            t.daemon = True
            t.start()

            self.send(json.dumps({'message': f'Connected to {self.server.hostname} (Smart Audit Enabled)...\r\n'}))
            self.send(json.dumps({'action': 'room_info', 'room_id': self.room_id}))
        except Exception as e:
            self.send(json.dumps({'message': f'Error: {str(e)}\r\n'}))
            self.close()

    def disconnect(self, close_code):
        try:
            async_to_sync(self.channel_layer.group_discard)(self.room_id, self.channel_name)
        except:
            pass
        if self.mode == 'host':
            self.save_log_file()
            if hasattr(self, 'terminal_log'):
                self.terminal_log.end_time = timezone.now()
                self.terminal_log.save()
            if self.ssh: self.ssh.close()

    def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except:
            return
        action = data.get('action')
        payload = data.get('data')

        if action == 'confirm_risk':
            self.execute_pending_command(True, data.get('ai_advice', ''))
        elif action == 'cancel_risk':
            self.execute_pending_command(False, data.get('ai_advice', ''))

        elif action == 'resize' and self.mode == 'host':
            cols = data.get('cols', 80)
            rows = data.get('rows', 24)
            if self.chan:
                self.chan.resize_pty(width=cols, height=rows)
            # 同步调整虚拟屏幕
            self.screen.resize(lines=rows, columns=cols)

        elif payload:
            if self.mode == 'guest':
                async_to_sync(self.channel_layer.group_send)(
                    self.room_id, {'type': 'forward_input', 'data': payload, 'sender': self.channel_name}
                )
            else:
                self.handle_input(payload)

    def loop_read(self):
        """
        [极致优化版] 读取 SSH 输出
        优化点：直接通过 self.send 发送给当前用户，消除 Redis 广播带来的几十毫秒延迟
        """
        while True:
            try:
                # 阻塞等待数据
                if self.chan.recv_ready():
                    # 贪婪读取：一次性读完缓冲区所有数据，减少 IO 次数
                    data = self.chan.recv(4096)
                    while self.chan.recv_ready():
                        chunk = self.chan.recv(4096)
                        data += chunk
                        if len(data) > 65536: break

                    if not data: break

                    decoded = data.decode('utf-8', errors='ignore')

                    # === 优化点 1: 喂给审计屏幕 (如果您用了 Pyte 方案) ===
                    # 如果您没用 Pyte 方案，请删除这两行
                    if hasattr(self, 'stream'):
                        self.stream.feed(decoded)

                    # === 优化点 2: 极速回显 (直接发给当前用户) ===
                    # 不经过 Redis，延迟最低
                    self.send(json.dumps({'data': decoded}))

                    # === 优化点 3: 异步广播 (给围观的 Guest 看) ===
                    # 带上 sender_channel_name，防止自己收到重复消息
                    async_to_sync(self.channel_layer.group_send)(
                        self.room_id,
                        {
                            'type': 'broadcast_output',
                            'data': decoded,
                            'sender_channel_name': self.channel_name  # <--- 关键标记
                        }
                    )

                    # 4. 存日志
                    self.log_buffer.append(json.dumps({'time': time.time(), 'data': decoded}) + "\n")
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"Loop Read Error: {e}")
                break

    def handle_input(self, data):
        """
        [多行命令优化版] 屏幕内容审计
        """
        if not self.chan: return

        for char in data:
            should_send = True

            # === 检测回车键 ===
            if char in ['\r', '\n']:
                # 触发命令重组逻辑
                full_cmd = self.reconstruct_command_from_screen()

                print(f"[Smart-Audit] Captured: '{full_cmd}'")

                # 高危正则匹配
                patterns = [
                    r'(?:^|[;&|\s])rm\s+.*(?:-[a-zA-Z]*[rR]|--recursive)',
                    r'(?:^|[;&|\s])(mkfs|mkswap|fdisk|parted|sfdisk)\s+',
                    r'(?:^|[;&|\s])dd\s+.*if=',
                    r'(?:^|[;&|\s])(reboot|shutdown|poweroff|halt|init\s+0)',
                    r':\(\)\{\s*:\s*\|\s*:\s*&\s*\}\s*;'
                ]

                is_dangerous = False
                for p in patterns:
                    if re.search(p, full_cmd, re.IGNORECASE):
                        is_dangerous = True
                        break

                if is_dangerous:
                    print(f"[Smart-Audit] 🛑 BLOCKED: {full_cmd}")

                    self.pending_command = full_cmd
                    self.send(json.dumps({'action': 'risk_warning', 'command': full_cmd}))

                    try:
                        self.chan.send('\x03')
                    except:
                        pass

                    should_send = False

            if should_send:
                try:
                    self.chan.send(char)
                except:
                    pass

    def reconstruct_command_from_screen(self):
        """
        [核心逻辑] 从虚拟屏幕回溯，拼接多行命令
        """
        # 1. 获取光标当前行号
        cursor_y = self.screen.cursor.y
        lines = self.screen.display

        # 2. 向上回溯寻找提示符 (Prompt)
        # 提示符特征：通常以 #, $, > 结尾，后面可能有空格
        # 我们设定一个回溯上限 (例如向上找 10 行)，防止性能损耗
        start_y = cursor_y
        prompt_pattern = re.compile(r'^.*?[#$%>]\s?')

        for i in range(cursor_y, max(-1, cursor_y - 10), -1):
            line_content = lines[i]
            # 如果这行看起来像是一个提示符行
            if prompt_pattern.match(line_content):
                start_y = i
                break

        # 3. 提取并拼接命令
        cmd_parts = []
        for i in range(start_y, cursor_y + 1):
            line = lines[i].rstrip()  # 去掉行末空格

            # 如果是第一行 (包含提示符)，需要去掉提示符
            if i == start_y:
                # 使用 sub 去掉匹配到的 prompt 部分
                line = prompt_pattern.sub('', line, count=1)

            cmd_parts.append(line)

        # 4. 合并多行
        # 有些终端换行会在行末加反斜杠 \，或者直接硬换行
        # 这里简单用空格连接，足以应对 rm -rf 的审计
        full_command = "".join(cmd_parts).strip()

        return full_command

    def execute_pending_command(self, is_confirm, ai_advice=""):
        if not self.pending_command: return

        try:
            HighRiskAudit.objects.create(
                user=self.user, server=self.server, command=self.pending_command,
                ai_advice=ai_advice, action='executed' if is_confirm else 'blocked'
            )
        except:
            pass

        if is_confirm:
            # 发送命令 + 回车
            self.chan.send(self.pending_command + '\r')
            msg = f'\r\n\x1b[31m[System] ⚠️ 已执行: {self.pending_command}\x1b[0m\r\n'
        else:
            msg = f'\r\n\x1b[32m[System] 已取消\x1b[0m\r\n'

        async_to_sync(self.channel_layer.group_send)(
            self.room_id, {'type': 'broadcast_output', 'data': msg}
        )
        self.pending_command = None

    def save_log_file(self):
        if not self.log_buffer: return
        content = "".join(self.log_buffer)
        fname = f"audit_{self.terminal_log.id}_{int(time.time())}.jsonl"
        self.terminal_log.log_file.save(fname, ContentFile(content))

    def broadcast_output(self, event):
        """
        处理广播消息
        优化点：如果是自己发出的 SSH 数据，直接忽略（因为 loop_read 里已经直发了）
        """
        # 如果消息是自己产生的，就不再发送给自己，避免重复和延迟抖动
        if event.get('sender_channel_name') == self.channel_name:
            return

        self.send(json.dumps({'data': event['data']}))

    def forward_input(self, event):
        if self.mode == 'host' and event['sender'] != self.channel_name:
            self.handle_input(event['data'])