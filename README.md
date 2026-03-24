# 运维平台 Ops Platform

> 一个基于 Django + Daphne 的智能运维管理平台，支持服务器监控、AI 模型接入与多云主机管理。

---

## 快速开始

### 第一步：初始化数据库 & 创建管理员账号

```bash
python reset_db.py
python manage.py createsuperuser
```

按照提示输入用户名、邮箱和密码，完成管理员账号的创建。

---

### 第二步：启动 Web 服务

```bash
daphne -b 0.0.0.0 -p 8000 ops_platform.asgi:application
```

服务启动后，在浏览器中访问：

```
http://localhost:8000
```

---

### 第三步：启动服务器监控 Agent

```bash
python manage.py run_agent
```

此命令将开启后台 Agent，持续采集并监控服务器运行状态。

---

## 配置说明

以下配置均在 **网页端** 完成。

### 4.1 配置 AI 模型

进入 **系统配置 → AI 模型配置**，点击「添加模型」，填写以下信息：

| 字段 | 值 |
|------|-----|
| 名称 | DeepSeek |
| 模型标识 | `deepseek-chat` |
| Base URL | `https://api.deepseek.com/v1` |
| API Key | 填写你自己的 API Key |

---

### 4.2 录入服务器

进入 **服务器管理 → 主机列表**，支持两种方式添加主机：

- **手动录入**：点击「手动录入」，逐台填写服务器信息。
- **自动同步**：绑定阿里云账号后，系统将自动拉取并同步云上服务器列表。

---

## 技术栈

- **后端框架**：Django
- **ASGI 服务器**：Daphne
- **AI 接入**：兼容 OpenAI 协议的大模型（如 DeepSeek）
- **多云支持**：阿里云（更多云平台持续接入中）
