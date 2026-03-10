import os
from celery.schedules import crontab
from pathlib import Path
import django.utils.encoding

try:
    django.utils.encoding.force_text = django.utils.encoding.force_str
except AttributeError:
    pass
# ==========================================================
AUTH_PASSWORD_VALIDATORS = [
    # 检查密码是否与用户信息（如用户名）太相似
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    # 检查最小长度
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,  # 修改为你想要的最小长度
        }
    },
    {
        'NAME': 'system.validators.ComplexPasswordValidator',
    },
    # 检查是否是常见弱密码（如 123456）
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    # 检查是否全是数字
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
# 基础路径
BASE_DIR = Path(__file__).resolve().parent.parent

# === 1. 安全配置 (支持从环境变量读取，适配 Docker) ===
# 生产环境必须修改 Secret Key
# 生成 DJANGO_SECRET_KEY
#python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'


SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-prod-key-please-change-me')

# 调试模式: 默认开启，生产环境通过环境变量 DJANGO_DEBUG=False 关闭
#DEBUG = False
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'
# 允许的主机: 生产环境建议填具体域名或 IP
ALLOWED_HOSTS = ['*']
FERNET_KEYS = [
    os.environ.get('APP_MASTER_KEY', 'T-zxxxx_PLEASE_CHANGE_THIS_IN_PRODUCTION_xxxx=')
]
# CSRF 可信源 (解决 Docker/Nginx 反代时的 CSRF 验证失败)
CSRF_TRUSTED_ORIGINS = ['http://127.0.0.1:8000', 'http://localhost:8000']
# LDAP
AUTHENTICATION_BACKENDS = [
    # 1. 自定义 LDAP 认证
    'system.auth_backend.LDAPBackend',

    # 2. Django 原生数据库认证 (保底)
    'django.contrib.auth.backends.ModelBackend',
]
# === 2. 应用注册 ===
INSTALLED_APPS = [
    'daphne',  # 必须放在第一位 (ASGI支持)

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # 第三方库
    'channels',  # WebSocket
    'fernet_fields',  # 字段加密
    # 自定义应用
    'system',  # 用户、角色、仪表盘、系统设置
    'cmdb',  # 服务器、WebSSH、Agent、云同步
    'ai_ops',  # AI 对话、诊断、模型管理
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise: 负责在生产环境(DEBUG=False)下高效分发静态文件
    'whitenoise.middleware.WhiteNoiseMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'ops_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],  # 指向根目录 templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ASGI 入口 (WebSocket 必须)
ASGI_APPLICATION = 'ops_platform.asgi.application'

# === 3. 数据库配置 (优先读取环境变量，适配 Docker MySQL) ===
#DB_NAME = os.environ.get('DB_NAME', 'ops_platform')
#DB_USER = os.environ.get('DB_USER', 'root')
#DB_PASSWORD = os.environ.get('DB_PASSWORD', '123456')  # 本地测试密码
#DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')  # 本地或 Docker Service Name
#DB_PORT = os.environ.get('DB_PORT', '3306')
#
#DATABASES = {
#    'default': {
#        'ENGINE': 'django.db.backends.mysql',
#        'NAME': DB_NAME,
#        'USER': DB_USER,
#        'PASSWORD': DB_PASSWORD,
#        'HOST': DB_HOST,
#        'PORT': DB_PORT,
#        'OPTIONS': {
#            'charset': 'utf8mb4',
#            # SQL 模式严格模式，防止数据截断不报错
#            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
#        }
#    }
#}
DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
}
# === 4. Channels 配置 (WebSocket) ===
REDIS_HOST = os.environ.get('REDIS_HOST', '192.168.10.128')
REDIS_PORT = os.environ.get('REDIS_PORT', '6379')
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '123456') # 您的Redis密码

# 构造 Redis URL (格式: redis://:password@host:port/db)
if REDIS_PASSWORD:
    # 注意: 密码前的冒号(:)不能少
    REDIS_URL_CELERY_BROKER = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
    REDIS_URL_CELERY_RESULT = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/1'
    # Channels 专用: 直接使用带密码的 URL
    CHANNEL_REDIS_URL = f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0'
else:
    REDIS_URL_CELERY_BROKER = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'
    REDIS_URL_CELERY_RESULT = f'redis://{REDIS_HOST}:{REDIS_PORT}/1'
    CHANNEL_REDIS_URL = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'

# CHANNEL_LAYERS = {#多人协调模式，需配置好redis
#     "default": {
#         "BACKEND": "channels_redis.core.RedisChannelLayer",
#         "CONFIG": {
#             "hosts": [CHANNEL_REDIS_URL],
#         },
#     },
# }
CHANNEL_LAYERS = {#单人模式
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}
CELERY_BROKER_URL = REDIS_URL_CELERY_BROKER
CELERY_RESULT_BACKEND = REDIS_URL_CELERY_RESULT
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Shanghai'
# 可选: 避免死锁
CELERYD_FORCE_EXECV = True

# === 5. 国际化与时区 ===
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True  # 开启时区支持，数据库存 UTC，前端显示本地时间

# === 6. 静态文件配置 ===
STATIC_URL = '/static/'
# 开发环境查找静态文件的目录
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]
# 生产环境收集静态文件的目录 (运行 collectstatic 后生成)
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
# WhiteNoise 存储引擎 (压缩与缓存)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# === 7. 自定义用户模型 ===
AUTH_USER_MODEL = 'system.User'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# === 8. 密码加密密钥 (Fernet) ===
# 用于加密存储 SSH 密码、API Key 等敏感信息
# 生成 APP_MASTER_KEY (Fernet Key)
#python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
# 生产环境请务必更换此 Key！生成方法: from cryptography.fernet import Fernet; Fernet.generate_key()
FERNET_KEYS = [
    'T-zxxxx_PLEASE_CHANGE_THIS_IN_PRODUCTION_xxxx='
]

CELERY_BEAT_SCHEDULE = {
    'check-ssl-certs-every-day': {
        'task': 'cmdb.tasks.check_ssl_certificates_task',
        # 每天早上 9 点执行
        'schedule': crontab(hour=9, minute=0),
    },
}
# === 9. 默认主键类型 ===
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# === 10. 日志配置 (生产环境必备) ===
# 即使 DEBUG=False，也能在 Docker logs 中看到错误信息
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        # 业务模块日志开启 DEBUG 级别以便排查
        'cmdb': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'ai_ops': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'k8s_manager': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}