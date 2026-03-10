from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib import messages
from django.db.models import Count, Avg
from django.utils.timezone import localtime  # 引入时区处理工具
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
# 引入相关模型
from .models import User, SystemConfig
from .forms import RoleForm
from cmdb.models import Server, ServerMetric, ServerGroup, ServerGroupAuth
from ai_ops.models import AIModel  # 引入 AI 模型用于仪表盘诊断
from django.contrib.auth.models import Permission, Group

# ===========================
# 权限检查辅助函数
# ===========================
def is_admin(user):
    return user.is_superuser


# ===========================
# 认证与账户 (Auth)
# ===========================
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)

        if user:
            if user.is_active:
                login(request, user)
                return redirect('dashboard')
            else:
                messages.error(request, "账号被禁用或待审核，请联系管理员")
        else:
            messages.error(request, "用户名或密码错误")

    return render(request, 'login.html')


def register_view(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        p_conf = request.POST.get('password_confirm')

        if p != p_conf:
            messages.error(request, "两次密码输入不一致")
            return render(request, 'register.html')

        if User.objects.filter(username=u).exists():
            messages.error(request, "用户名已存在")
            return render(request, 'register.html')
        try:
            # user=None 因为用户还没创建，如果是修改密码场景可以传 user 对象
            validate_password(p, user=None)
        except ValidationError as e:
            # e.messages 是一个错误信息列表
            for msg in e.messages:
                messages.error(request, msg)
            return render(request, 'register.html')

        # 3. 校验通过，创建用户
        user = User.objects.create_user(username=u, password=p)
        user.is_active = False
        user.save()
        messages.success(request, "注册成功，请等待管理员审核")
        return redirect('login')

    return render(request, 'register.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def change_own_password(request):
    """用户修改自己的密码"""
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # 保持登录状态
            messages.success(request, "密码修改成功")
            return redirect('dashboard')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'password_change.html', {'form': form})


# ===========================
# 仪表盘 (Dashboard) - 核心逻辑
# ===========================
# system/views.py

@login_required
def dashboard(request):
    user = request.user

    # === 1. 权限过滤 (新增逻辑) ===
    # 默认获取所有，如果是普通用户则进行过滤
    base_qs = Server.objects.all()

    if not user.is_superuser:
        # 获取用户所在的角色(Group) ID 列表
        my_role_ids = user.groups.values_list('id', flat=True)
        # 查询这些角色绑定的服务器分组 ID
        allowed_group_ids = ServerGroupAuth.objects.filter(
            role_id__in=my_role_ids
        ).values_list('server_group_id', flat=True)

        # 过滤：只保留在授权分组内的主机
        base_qs = base_qs.filter(group_id__in=allowed_group_ids)

    # === 2. 准备数据源 ===
    # 下拉框数据：用户能看见的且正在运行的服务器
    all_servers = base_qs.filter(status='Running')
    server_id = request.GET.get('server_id')

    # 初始化默认值
    cpu_val = mem_val = load_val = 0
    sys_info = {}
    trend_qs = []

    # 定义指标字段 (含 CPU, 内存, 网络, 磁盘, IO)
    metric_fields = [
        'created_at', 'cpu_usage', 'mem_usage',
        'net_in', 'net_out', 'disk_usage',
        'disk_read_rate', 'disk_write_rate'
    ]
    has_agent = True
    if server_id:
        # === 单机视图 ===
        # 使用 base_qs.get 确保用户不能通过 URL 暴力遍历访问无权查看的主机
        current_server = get_object_or_404(base_qs, id=server_id)
        latest_metric = current_server.metrics.first()

        if latest_metric:
            cpu_val = latest_metric.cpu_usage
            mem_val = latest_metric.mem_usage
            load_val = latest_metric.load_1min

        sys_info = {
            'hostname': current_server.hostname,
            'os': current_server.os_name,
            'cpu_model': f"{current_server.cpu_cores} vCPU",
            'cores': current_server.cpu_cores,
            'load': load_val,
            'uptime': 'Running',
            'ip': current_server.ip_address,
            'has_agent': has_agent,
        }
        if has_agent:
            latest_metric = current_server.metrics.first()
            if latest_metric:
                cpu_val = latest_metric.cpu_usage
                mem_val = latest_metric.mem_usage
                load_val = latest_metric.load_1min
                sys_info['load'] = load_val
            else:
                sys_info['load'] = 0
        # 获取该机器的趋势数据
            trend_qs = current_server.metrics.values(*metric_fields).order_by('-created_at')[:20][::-1]
        else:
            # 未安装 Agent，数据置空
            sys_info['load'] = '-'
            trend_qs = []

    else:
        # === 集群平均视图 ===
        # 仅统计用户有权查看的 Running 服务器
        agent_servers = all_servers.filter(use_agent=True)
        metrics_list = [s.metrics.first() for s in agent_servers if s.metrics.exists()]
        if metrics_list:
            count = len(metrics_list)
            cpu_val = sum(m.cpu_usage for m in metrics_list) / count
            mem_val = sum(m.mem_usage for m in metrics_list) / count
            load_val = sum(m.load_1min for m in metrics_list) / count

        sys_info = {
            'hostname': 'Cluster Avg',
            'os': 'Mixed',
            'cpu_model': 'vCPU Pool',
            'cores': sum(s.cpu_cores for s in all_servers),  # 仅统计可见核心数
            'load': round(load_val, 2),
            'uptime': f"{all_servers.count()} Nodes",
            'ip': '-',
            'has_agent': True
        }

        # 趋势图：只显示用户有权查看的服务器产生的指标数据
        # 注意：这里简单取了所有可见服务器的最新20条记录（混合），
        # 严谨做法是按时间聚合 avg()，但为保持代码简单暂不修改聚合逻辑，仅做权限过滤
        trend_qs = ServerMetric.objects.filter(server__in=agent_servers).values(*metric_fields).order_by('-created_at')[:20][::-1]
    # 计算健康度
    system_health = ((100 - cpu_val) + (100 - mem_val)) / 2
    if system_health < 0: system_health = 0

    # 统计在线率 (分母为用户可见的总数，分子为用户可见的在线数)
    total_count = base_qs.count()
    running_count = all_servers.count()
    online_rate = (running_count / total_count * 100) if total_count > 0 else 0

    context = {
        'page_title': '仪表盘',
        'all_servers': all_servers,
        'current_server_id': int(server_id) if server_id else None,

        'server_count': total_count,
        'running_count': running_count,

        'metrics': {
            'cpu': round(cpu_val, 1),
            'mem': round(mem_val, 1),
            'health': round(system_health, 1),
            'online_rate': round(online_rate, 1)
        },
        'sys_info': sys_info,

        # 图表数据源
        'trend_dates': [localtime(x['created_at']).strftime('%H:%M') for x in trend_qs],
        'trend_cpu': [x['cpu_usage'] for x in trend_qs],
        'trend_mem': [x['mem_usage'] for x in trend_qs],
        'trend_net_in': [x.get('net_in', 0) for x in trend_qs],
        'trend_net_out': [x.get('net_out', 0) for x in trend_qs],
        'trend_disk': [x.get('disk_usage', 0) for x in trend_qs],
        'trend_disk_read': [x.get('disk_read_rate', 0) for x in trend_qs],
        'trend_disk_write': [x.get('disk_write_rate', 0) for x in trend_qs],

        'ai_models': AIModel.objects.all(),
    }
    return render(request, 'index.html', context)


# ===========================
# 用户管理 (User Management)
# ===========================
@login_required
@user_passes_test(is_admin)
def user_list(request):
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'user_list.html', {'users': users, 'page_title': '用户管理'})
@login_required
@user_passes_test(is_admin)
def role_create(request):
    """创建角色 + 绑定数据权限 + 绑定功能权限"""
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save()

            # 1. 保存数据权限 (Server Group)
            group_ids = request.POST.getlist('server_groups')
            for gid in group_ids:
                if gid:
                    ServerGroupAuth.objects.create(role=role, server_group_id=gid)

            # 2. 保存功能权限 (Django Permissions)
            perm_ids = request.POST.getlist('permissions')
            if perm_ids:
                role.permissions.set(perm_ids)

            messages.success(request, "角色创建成功")
            return redirect('role_list')
    else:
        form = RoleForm()

    # 获取系统所有权限，并按 APP 分组 (优化展示)
    # 我们只关注我们关心的 app: cmdb
    target_apps = ['cmdb']
    all_perms = Permission.objects.filter(content_type__app_label__in=target_apps).select_related('content_type')

    return render(request, 'role_form.html', {
        'form': form,
        'all_server_groups': ServerGroup.objects.all(),
        'all_perms': all_perms,  # 传递权限列表
        'page_title': '新建角色'
    })


@login_required
@user_passes_test(is_admin)
def user_edit(request, user_id):
    """编辑用户 (修改基本信息 + 设为管理员)"""
    target_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        target_user.username = request.POST.get('username')
        target_user.email = request.POST.get('email')
        target_user.phone = request.POST.get('phone')
        target_user.department = request.POST.get('department')

        # 处理管理员开关
        is_superuser = request.POST.get('is_superuser') == 'on'
        if target_user == request.user and not is_superuser:
            messages.error(request, "为了安全，您不能取消自己的管理员权限")
        else:
            target_user.is_superuser = is_superuser
            target_user.is_staff = is_superuser  # 同步开启后台登录权限

        target_user.save()
        messages.success(request, f"用户 {target_user.username} 信息已更新")
        return redirect('user_list')

    return render(request, 'user_form.html', {'target_user': target_user, 'page_title': '编辑用户'})


@login_required
@user_passes_test(is_admin)
def admin_reset_password(request, user_id):
    """管理员强制重置用户密码"""
    target_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        form = SetPasswordForm(user=target_user, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"用户 {target_user.username} 的密码已重置")
            return redirect('user_list')
    else:
        form = SetPasswordForm(user=target_user)
    return render(request, 'password_reset.html', {'form': form, 'target_user': target_user})


@login_required
@user_passes_test(is_admin)
def toggle_user_status(request, user_id):
    """激活/禁用用户"""
    user = get_object_or_404(User, id=user_id)
    if user != request.user:
        user.is_active = not user.is_active
        user.save()
        messages.success(request, f"用户 {user.username} 状态已更新")
    return redirect('user_list')


@login_required
@user_passes_test(is_admin)
def delete_user(request, user_id):
    """删除用户"""
    user = get_object_or_404(User, id=user_id)
    if user != request.user:
        user.delete()
        messages.warning(request, f"用户 {user.username} 已删除")
    return redirect('user_list')

# ===========================
# LDAP
# ===========================


@login_required
@user_passes_test(is_admin)
def user_edit_role(request, user_id):
    """分配角色"""
    target_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        role_ids = request.POST.getlist('roles')
        target_user.groups.set(role_ids)
        messages.success(request, "角色分配成功")
        return redirect('user_list')
    context = {
        'target_user': target_user,
        'all_roles': Group.objects.all(),
        'user_roles': target_user.groups.values_list('id', flat=True)
    }
    return render(request, 'user_role_edit.html', context)


# ===========================
# 角色管理 (Role - Data Permission)
# ===========================
@login_required
@user_passes_test(is_admin)
def role_list(request):
    roles = Group.objects.annotate(user_count=Count('user')).all()
    return render(request, 'role_list.html', {'roles': roles, 'page_title': '角色管理'})


@login_required
@user_passes_test(is_admin)
def role_create(request):
    """创建角色 + 绑定数据权限"""
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save()
            # 获取勾选的服务器分组 ID
            group_ids = request.POST.getlist('server_groups')
            for gid in group_ids:
                if gid:
                    ServerGroupAuth.objects.create(role=role, server_group_id=gid)
            messages.success(request, "角色创建成功")
            return redirect('role_list')
    else:
        form = RoleForm()

    return render(request, 'role_form.html', {
        'form': form,
        'all_server_groups': ServerGroup.objects.all(),  # 供前端选择
        'page_title': '新建角色'
    })


@login_required
@user_passes_test(is_admin)
def role_edit(request, role_id):
    """编辑角色"""
    role = get_object_or_404(Group, id=role_id)
    if request.method == 'POST':
        form = RoleForm(request.POST, instance=role)
        if form.is_valid():
            form.save()

            # 1. 更新数据权限
            ServerGroupAuth.objects.filter(role=role).delete()
            group_ids = request.POST.getlist('server_groups')
            bulk_list = [ServerGroupAuth(role=role, server_group_id=gid) for gid in group_ids if gid]
            ServerGroupAuth.objects.bulk_create(bulk_list)

            # 2. 更新功能权限
            perm_ids = request.POST.getlist('permissions')
            role.permissions.set(perm_ids)

            messages.success(request, "角色更新成功")
            return redirect('role_list')
    else:
        form = RoleForm(instance=role)

    # 数据准备
    current_group_ids = list(ServerGroupAuth.objects.filter(role=role).values_list('server_group_id', flat=True))
    current_perm_ids = list(role.permissions.values_list('id', flat=True))  # 当前已拥有的权限ID

    target_apps = ['cmdb', 'script_manager', 'k8s_manager']
    all_perms = Permission.objects.filter(content_type__app_label__in=target_apps).select_related(
        'content_type').order_by('content_type__model')

    return render(request, 'role_form.html', {
        'form': form,
        'role': role,
        'all_server_groups': ServerGroup.objects.all(),
        'current_group_ids': current_group_ids,
        'all_perms': all_perms,
        'current_perm_ids': current_perm_ids,
        'page_title': '编辑角色'
    })


@login_required
@user_passes_test(is_admin)
def role_delete(request, role_id):
    get_object_or_404(Group, id=role_id).delete()
    return redirect('role_list')


# ===========================
# 系统参数设置 (System Config)
# ===========================
@login_required
@user_passes_test(is_admin)
def sys_setting(request):
    """系统参数设置 (支持 阿里云 + LDAP 分离保存)"""

    # 定义所有需要从数据库读取的配置键 (用于页面回显)
    all_keys = [
        'ldap_enabled', 'ldap_server_url', 'ldap_bind_dn',
        'ldap_bind_password', 'ldap_user_search_base', 'ldap_user_filter'
    ]

    if request.method == 'POST':
        action = request.POST.get('action')

        # === 分支 2: 保存 LDAP 配置 ===
        if action == 'save_ldap':
            ldap_keys = [
                'ldap_enabled', 'ldap_server_url', 'ldap_bind_dn',
                'ldap_bind_password', 'ldap_user_search_base', 'ldap_user_filter'
            ]
            for k in ldap_keys:
                val = request.POST.get(k, '').strip()
                SystemConfig.objects.update_or_create(key=k, defaults={'value': val})
            messages.success(request, "LDAP 配置已更新")

    # 查询所有配置并转为字典，供模板使用
    configs = {k: getattr(SystemConfig.objects.filter(key=k).first(), 'value', '') for k in all_keys}

    return render(request, 'settings.html', {'configs': configs, 'page_title': '系统参数'})