import uuid
from django.db import models
from fernet_fields import EncryptedCharField
from django.contrib.auth.models import Group
from system.models import User
from fernet_fields import EncryptedCharField  # 确保引入
import ipaddress
class ServerGroup(models.Model):
    """服务器分组 (树形结构)"""
    name = models.CharField("组名", max_length=50)
    # self-referencing ForeignKey 实现无限层级目录
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children',
                               verbose_name="上级分组")

    def __str__(self):
        return self.name


class Server(models.Model):
    """服务器资产"""
    PROVIDER_CHOICES = (
        ('aliyun', '阿里云'),
        ('private', '私有/物理机'),
    )
    STATUS_CHOICES = (
        ('Running', '运行中'),
        ('Stopped', '已停止'),
    )

    group = models.ForeignKey(ServerGroup, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="所属分组")
    hostname = models.CharField("主机名", max_length=100)
    ip_address = models.GenericIPAddressField("IP地址", unique=True)
    port = models.IntegerField("SSH端口", default=22)
    username = models.CharField("SSH用户名", max_length=50, default='root')
    password = EncryptedCharField("SSH密码", max_length=100, blank=True, null=True)
    # 硬件配置
    cpu_cores = models.IntegerField("CPU核数", default=1)
    memory_gb = models.IntegerField("内存(GB)", default=1)
    os_name = models.CharField("操作系统", max_length=100, default="CentOS 7.9")

    # 云同步相关
    provider = models.CharField("来源", max_length=20, choices=PROVIDER_CHOICES, default='private')
    instance_id = models.CharField("实例ID", max_length=100, blank=True, null=True)  # 云厂商的ID
    status = models.CharField("状态", max_length=20, choices=STATUS_CHOICES, default='Running')
    use_agent = models.BooleanField("使用Agent", default=False, help_text="开启后将停止SSH采集，等待Agent上报")
    agent_token = models.CharField("Agent Token", max_length=64, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # 自动生成 Token
        if not self.agent_token:
            self.agent_token = uuid.uuid4().hex
        super().save(*args, **kwargs)
    def __str__(self):
        return f"{self.hostname} ({self.ip_address})"


class CloudAccount(models.Model):
    """云账号管理 (支持阿里云/腾讯云)"""
    PROVIDER_CHOICES = (
        ('aliyun', '阿里云 (Aliyun)'),
        ('tencent', '腾讯云 (Tencent)'),
    )

    name = models.CharField("账号名称/别名", max_length=50, help_text="例如：生产环境主账号")

    # AccessKey ID 不敏感，明文存储以便检索
    access_key = models.CharField("AccessKey ID", max_length=100)

    # SecretKey 极为敏感，使用 AES (Fernet) 加密存储
    # 数据库中存储的是乱码，读取时自动解密
    secret_key = EncryptedCharField("AccessKey Secret", max_length=100)

    region = models.CharField("默认区域", max_length=50, default="cn-hangzhou")
    type = models.CharField("云厂商", max_length=20, default='aliyun', choices=PROVIDER_CHOICES)

    create_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_type_display()} - {self.name}"


class TerminalLog(models.Model):
    """WebSSH 审计日志"""
    user = models.ForeignKey('system.User', on_delete=models.CASCADE, verbose_name="操作人")
    server = models.ForeignKey(Server, on_delete=models.SET_NULL, null=True, verbose_name="服务器")
    channel_name = models.CharField("WebSocket频道", max_length=100)

    # 存储录像文件的路径（文本文件）
    log_file = models.FileField("录像文件", upload_to='ssh_logs/%Y/%m/%d/', blank=True, null=True)

    start_time = models.DateTimeField("开始时间", auto_now_add=True)
    end_time = models.DateTimeField("结束时间", null=True, blank=True)

    class Meta:
        ordering = ['-start_time']


class ServerMetric(models.Model):
    """服务器实时性能指标"""
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='metrics')
    cpu_usage = models.FloatField("CPU使用率", default=0.0)
    mem_usage = models.FloatField("内存使用率", default=0.0)
    disk_usage = models.FloatField("磁盘使用率", default=0.0, help_text="/ 分区")
    load_1min = models.FloatField("1分钟负载", default=0.0)
    net_in = models.FloatField("入站流量", default=0.0)
    net_out = models.FloatField("出站流量", default=0.0)
    disk_read_rate = models.FloatField("磁盘读取速率(KB/s)", default=0.0)
    disk_write_rate = models.FloatField("磁盘写入速率(KB/s)", default=0.0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        get_latest_by = 'created_at'

class ServerGroupAuth(models.Model):
    """
    角色与服务器分组的权限绑定
    记录：角色 ID=1 能看 分组 ID=5
    """
    role = models.ForeignKey(Group, on_delete=models.CASCADE, verbose_name="角色", related_name='server_group_auths')
    server_group = models.ForeignKey(ServerGroup, on_delete=models.CASCADE, verbose_name="服务器分组")

    class Meta:
        unique_together = ('role', 'server_group')


class HighRiskAudit(models.Model):
    """高危命令审计日志"""
    ACTION_CHOICES = (
        ('blocked', '拦截/取消'),
        ('executed', '强制执行'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="操作人")
    server = models.ForeignKey(Server, on_delete=models.CASCADE, verbose_name="服务器")
    command = models.TextField("高危命令")
    risk_level = models.CharField("风险等级", max_length=20, default="High")
    ai_advice = models.TextField("AI评估建议", blank=True, null=True)
    action = models.CharField("最终动作", max_length=20, choices=ACTION_CHOICES, default='blocked')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "高危审计"


class SSLCertificate(models.Model):
    """SSL 证书监控"""
    domain = models.CharField("域名", max_length=100, unique=True)
    port = models.IntegerField("端口", default=443)

    # 证书信息 (自动更新)
    issuer = models.CharField("颁发机构", max_length=200, blank=True)
    start_date = models.DateTimeField("签发时间", null=True, blank=True)
    expire_date = models.DateTimeField("过期时间", null=True, blank=True)
    remaining_days = models.IntegerField("剩余天数", default=0)

    # 状态
    is_valid = models.BooleanField("是否有效", default=True)
    error_msg = models.TextField("错误信息", blank=True)

    # 告警配置
    auto_alert = models.BooleanField("自动告警", default=True)

    updated_at = models.DateTimeField("最后检测时间", auto_now=True)

    def __str__(self):
        return self.domain

    class Meta:
        verbose_name = "SSL证书"
        verbose_name_plural = "SSL证书"
