import logging
import traceback
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from .models import SystemConfig

# 尝试导入 ldap3
try:
    from ldap3 import Server, Connection, ALL, NTLM

    LDAP_AVAILABLE = True
except ImportError:
    LDAP_AVAILABLE = False

logger = logging.getLogger(__name__)
User = get_user_model()


class LDAPBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        # 0. 基础检查
        if not LDAP_AVAILABLE:
            # logger.warning("LDAP 模块未安装 (pip install ldap3)")
            return None

        if not username or not password:
            return None

        # 1. 从数据库读取配置
        try:
            # 使用 .first() 避免 DoesNotExist 报错，方便调试
            def get_conf(key):
                obj = SystemConfig.objects.filter(key=key).first()
                return obj.value if obj else None

            config = {
                'enabled': get_conf('ldap_enabled'),
                'server_url': get_conf('ldap_server_url'),
                'bind_dn': get_conf('ldap_bind_dn'),
                'bind_password': get_conf('ldap_bind_password'),
                'search_base': get_conf('ldap_user_search_base'),
                'user_filter': get_conf('ldap_user_filter')
            }

            # 检查关键配置是否缺失
            if not config['enabled'] or config['enabled'] != '1':
                return None  # LDAP 未开启，跳过

            if not config['server_url']:
                logger.error("[LDAP] 配置错误: Server URL 为空")
                return None

            # [Debug] 打印配置 (密码打码)
            debug_conf = config.copy()
            debug_conf['bind_password'] = '******'
            logger.info(f"[LDAP] Attempting auth for '{username}' with config: {debug_conf}")

        except Exception as e:
            logger.error(f"[LDAP] Config Read Error: {e}")
            return None

        # 2. 连接 LDAP
        conn = None
        try:
            logger.info(f"[LDAP] Connecting to {config['server_url']}...")
            server = Server(config['server_url'], get_info=ALL)

            # 管理员绑定
            conn = Connection(server, user=config['bind_dn'], password=config['bind_password'], auto_bind=True)
            logger.info(f"[LDAP] Bind successful as {config['bind_dn']}")

            # 3. 搜索用户
            search_filter = config['user_filter'] % {'user': username}
            logger.info(f"[LDAP] Searching: base='{config['search_base']}', filter='{search_filter}'")

            conn.search(config['search_base'], search_filter, attributes=['entryDN', 'mail', 'cn', 'sn'])

            if not conn.entries:
                logger.warning(f"[LDAP] User '{username}' not found in LDAP directory.")
                return None

            user_entry = conn.entries[0]
            user_dn = user_entry.entry_dn
            logger.info(f"[LDAP] User found: {user_dn}")

            # 4. 验证用户密码 (重新绑定)
            user_conn = Connection(server, user=user_dn, password=password)
            if not user_conn.bind():
                logger.warning(f"[LDAP] Password verification failed for '{username}'")
                return None

            logger.info(f"[LDAP] Password verified for '{username}'")

            # 5. 本地用户映射
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                # 自动创建用户
                user = User(username=username)
                user.set_unusable_password()
                # 尝试同步邮箱
                if 'mail' in user_entry:
                    user.email = str(user_entry.mail)
                user.save()
                logger.info(f"[LDAP] Created new local user: {username}")

            return user

        except Exception as e:
            # === 关键修改：打印完整堆栈信息 ===
            logger.error(f"[LDAP] Exception: {str(e)}")
            logger.error(traceback.format_exc())
            return None
        finally:
            if conn:
                conn.unbind()