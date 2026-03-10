from django.contrib import admin
from django.urls import path,include
from system import views
from cmdb import views as cmdb
from ai_ops import views as ai_ops
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),

    # 系统管理 - 用户
    path('sys/users/', views.user_list, name='user_list'),
    path('sys/users/toggle/<int:user_id>/', views.toggle_user_status, name='toggle_user_status'),
    path('sys/users/delete/<int:user_id>/', views.delete_user, name='delete_user'),
    path('sys/users/role/<int:user_id>/', views.user_edit_role, name='user_edit_role'),

    # 系统管理 - 角色
    path('sys/roles/', views.role_list, name='role_list'),
    path('sys/roles/add/', views.role_create, name='role_create'),
    path('sys/roles/edit/<int:role_id>/', views.role_edit, name='role_edit'),
    path('sys/roles/delete/<int:role_id>/', views.role_delete, name='role_delete'),

    path('sys/settings/', views.sys_setting, name='sys_setting'),
    path('sys/users/edit/<int:user_id>/', views.user_edit, name='user_edit'),

    # 密码管理
    path('sys/users/reset-pwd/<int:user_id>/', views.admin_reset_password, name='admin_reset_password'),
    path('sys/profile/change-pwd/', views.change_own_password, name='change_own_password'),
    # CMDB - 服务器
    path('cmdb/servers/', cmdb.server_list, name='server_list'),
    path('cmdb/servers/add/', cmdb.server_add, name='server_add'),
    path('cmdb/servers/edit/<int:pk>/', cmdb.server_edit, name='server_edit'),
    path('cmdb/servers/delete/<int:pk>/', cmdb.server_delete, name='server_delete'),
    path('cmdb/servers/sync/', cmdb.sync_aliyun, name='sync_aliyun'),
    path('agent/uninstall/', cmdb.agent_uninstall, name='agent_uninstall'),
    # CMDB - 分组 (简单路由，用于处理表单提交)
    path('cmdb/groups/add/', cmdb.group_add, name='group_add'),
    # 账号管理
    path('cmdb/accounts/', cmdb.account_list, name='account_list'),
    path('cmdb/accounts/delete/<int:pk>/', cmdb.account_delete, name='account_delete'),
    #webssh
    path('cmdb/ssh/<int:server_id>/', cmdb.webssh, name='webssh'),
    #证书
    path('ssl/', cmdb.ssl_cert_list, name='ssl_cert_list'),
    path('ssl/add/', cmdb.ssl_cert_add, name='ssl_cert_add'),
    path('ssl/delete/<int:pk>/', cmdb.ssl_cert_delete, name='ssl_cert_delete'),
    path('ssl/refresh/', cmdb.ssl_cert_refresh, name='ssl_cert_refresh'),
    path('ssl/config/', cmdb.ssl_config_save, name='ssl_config_save'),

    path('agent/install/', cmdb.agent_install, name='agent_install'),
    # 服务器导入导出
    path('server/export/', cmdb.server_export, name='server_export'),  # 导出
    path('server/import/', cmdb.server_import, name='server_import'),
    #文件上传下载
    path('cmdb/server/upload/<int:server_id>/', cmdb.server_file_upload, name='server_file_upload'),
    path('cmdb/server/download/<int:server_id>/', cmdb.server_file_download, name='server_file_download'),
    path('server/<int:server_id>/files/',cmdb.server_file_ops,name='server_file_ops'),
    path('java/ops/', cmdb.java_ops_index, name='java_ops_index'),
    path('java/get_processes/', cmdb.get_java_processes, name='get_java_processes'),
    path('java/diagnose/', cmdb.diagnose_java_process, name='diagnose_java_process'),
    path('ai/', include('ai_ops.urls'))
]