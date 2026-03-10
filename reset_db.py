import os
import shutil
import glob

# 定义项目涉及的 App
APPS = ['system', 'cmdb', 'ai_ops']


def clean_project():
    print("🚀 开始清理数据库和迁移文件...")

    # 1. 删除 SQLite 数据库文件
    if os.path.exists("db.sqlite3"):
        os.remove("db.sqlite3")
        print("✅ 已删除 db.sqlite3")
    else:
        print("ℹ️ db.sqlite3 不存在，跳过")

    # 2. 清理各个 App 下的 migrations 文件夹
    for app in APPS:
        migration_path = os.path.join(app, 'migrations')
        if not os.path.exists(migration_path):
            print(f"⚠️ {app} 没有 migrations 文件夹，跳过")
            continue

        # 获取所有文件
        files = glob.glob(os.path.join(migration_path, "*"))
        for f in files:
            filename = os.path.basename(f)
            # 保留 __init__.py，删除其他所有 .py 和 .pyc 文件
            if filename != "__init__.py" and (filename.endswith(".py") or filename.endswith(".pyc")):
                try:
                    os.remove(f)
                    print(f"   已删除: {f}")
                except Exception as e:
                    print(f"   ❌ 删除失败 {f}: {e}")
            elif os.path.isdir(f) and filename == "__pycache__":
                try:
                    shutil.rmtree(f)
                    print(f"   已清理: {f}")
                except:
                    pass

    print("\n✨ 清理完成！正在重新初始化...\n")

   ## 3. 重新执行 Django 命令
    os.system("python manage.py makemigrations system cmdb ai_ops script_manager k8s_manager")
    os.system("python manage.py migrate")
    print("\n🎉 数据库重置成功！")
    print("👉 请务必执行: python manage.py createsuperuser 创建管理员账号")


if __name__ == "__main__":
    confirm = input("⚠️  警告：此操作将清空所有数据！确认执行请输入 'y': ")
    if confirm.lower() == 'y':
        clean_project()
    else:
        print("已取消。")