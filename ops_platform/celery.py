# ops_platform/celery.py
import os
from celery import Celery

# 1. 设置默认 Django settings 模块
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ops_platform.settings')

# 2. 创建实例
app = Celery('ops_platform')

# 3. 从 settings.py 读取以 CELERY_ 开头的配置
# 这一步至关重要，否则它不知道 CELERY_RESULT_BACKEND 在哪里
app.config_from_object('django.conf:settings', namespace='CELERY')

# 4. 自动发现任务
app.autodiscover_tasks()