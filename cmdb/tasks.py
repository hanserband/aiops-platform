# cmdb/tasks.py

import ssl
import socket
import datetime
import requests
from celery import shared_task
from django.utils import timezone
from .models import SSLCertificate
from system.models import SystemConfig  # 假设 Webhook 配置存在 SystemConfig 中


def get_cert_info(domain, port=443):
    """获取证书信息的底层函数"""
    context = ssl.create_default_context()
    conn = context.wrap_socket(socket.socket(socket.AF_INET), server_hostname=domain)
    # 设置超时，防止卡死
    conn.settimeout(5.0)

    try:
        conn.connect((domain, port))
        cert = conn.getpeercert()
        conn.close()
        return cert, None
    except Exception as e:
        return None, str(e)


def send_alert(domain, days, error=None):
    """发送告警 (钉钉/企微)"""
    # 从系统配置中读取 Webhook (需要在 system/views.py 中 sys_setting 支持配置)
    ding_url = SystemConfig.objects.filter(key='dingtalk_webhook').first()
    wechat_url = SystemConfig.objects.filter(key='wechat_webhook').first()

    msg_title = f"🚨 SSL证书告警: {domain}"
    if error:
        msg_content = f"域名: {domain}\n状态: 检测失败\n原因: {error}"
    else:
        msg_content = f"域名: {domain}\n状态: 即将过期\n剩余天数: {days} 天\n请及时续费！"

    # 1. 发送钉钉
    if ding_url and ding_url.value:
        try:
            requests.post(ding_url.value, json={
                "msgtype": "text",
                "text": {"content": f"{msg_title}\n{msg_content}"}
            }, timeout=5)
        except:
            pass

    # 2. 发送企业微信
    if wechat_url and wechat_url.value:
        try:
            requests.post(wechat_url.value, json={
                "msgtype": "text",
                "text": {"content": f"{msg_title}\n{msg_content}"}
            }, timeout=5)
        except:
            pass


@shared_task
def check_ssl_certificates_task():
    """Celery 定时任务：批量检测证书"""
    certs = SSLCertificate.objects.all()
    for c in certs:
        cert_data, error = get_cert_info(c.domain, c.port)

        if error:
            c.is_valid = False
            c.error_msg = error
            c.save()
            if c.auto_alert:
                send_alert(c.domain, 0, error=error)
            continue

        # 解析日期
        # 格式示例: 'May 25 12:00:00 2025 GMT'
        date_fmt = r'%b %d %H:%M:%S %Y %Z'
        not_after_str = cert_data['notAfter']
        not_before_str = cert_data['notBefore']

        expire_date = datetime.datetime.strptime(not_after_str, date_fmt).replace(tzinfo=datetime.timezone.utc)
        start_date = datetime.datetime.strptime(not_before_str, date_fmt).replace(tzinfo=datetime.timezone.utc)

        now = timezone.now()
        remaining = (expire_date - now).days

        # 更新数据库
        c.issuer = dict(x[0] for x in cert_data['issuer'])['commonName']
        c.start_date = start_date
        c.expire_date = expire_date
        c.remaining_days = remaining
        c.is_valid = True
        c.error_msg = ""
        c.save()

        # 触发告警 (剩余 < 15 天)
        if c.auto_alert and remaining < 15:
            send_alert(c.domain, remaining)

    return f"Checked {len(certs)} domains."