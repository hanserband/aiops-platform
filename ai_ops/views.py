import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_exempt

from .models import ChatSession, ChatMessage, AIModel
from .utils import get_ai_client, ask_ai
from cmdb.models import Server, ServerMetric, TerminalLog


# ===========================
# AI 模型管理 (CRUD)
# ===========================
@login_required
@user_passes_test(lambda u: u.is_superuser)
def model_list(request):
    if request.method == 'POST':
        AIModel.objects.create(
            name=request.POST.get('name'),
            model_name=request.POST.get('model_name'),
            api_key=request.POST.get('api_key'),
            base_url=request.POST.get('base_url')
        )
        return redirect('model_list')
    return render(request, 'ai_ops/model_list.html', {'models': AIModel.objects.all()})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def model_delete(request, pk):
    AIModel.objects.filter(id=pk).delete()
    return redirect('model_list')


# ===========================
# 1. 服务器故障诊断 (已升级：包含磁盘和网络)
# ===========================
@login_required
def diagnose_server(request, server_id):
    if request.method != 'POST':
        return JsonResponse({'status': False, 'msg': 'Method not allowed'})

    model_id = request.POST.get('model_id')  # 获取前端选择的模型ID

    try:
        server = Server.objects.get(id=server_id)

        # 获取最近 20 个采样点 (约20分钟) 的数据
        metrics = ServerMetric.objects.filter(server=server).order_by('-created_at')[:20]
        if not metrics:
            return JsonResponse({'status': False, 'msg': '暂无监控数据，无法分析'})

        # === 修改点：增加 磁盘 和 网络流量 数据 ===
        data_summary = []
        for m in reversed(metrics):  # 时间正序
            # 格式化每行数据
            line = (
                f"[{m.created_at.strftime('%H:%M')}] "
                f"CPU:{m.cpu_usage}% "
                f"Mem:{m.mem_usage}% "
                f"Disk:{m.disk_usage}% "  # 新增磁盘
                f"Load:{m.load_1min} "
                f"NetIn:{m.net_in}KB/s "  # 新增入网
                f"NetOut:{m.net_out}KB/s"  # 新增出网
            )
            data_summary.append(line)

        data_text = "\n".join(data_summary)

        # === 修改点：更新提示词 Prompt ===
        prompt = f"""
        请分析服务器 "{server.hostname}" ({server.ip_address}) 的健康状况。
        操作系统: {server.os_name}

        最近20分钟监控数据 (包含CPU、内存、磁盘、负载、网络I/O):
        {data_text}

        请简要回答以下几点：
        1. 【资源趋势】CPU、内存、磁盘使用率是否正常？有无泄露或爆满风险？
        2. 【网络分析】入站/出站流量是否有异常突增？
        3. 【负载分析】系统负载是否过高？
        4. 【综合建议】给出具体的运维优化建议。
        """

        # 调用 AI (传入 model_id)
        result = ask_ai(prompt, model_id=model_id, system_role="你是一个资深的 Linux 性能优化专家。")

        if "error" in result:
            return JsonResponse({'status': False, 'msg': result['error']})

        return JsonResponse({'status': True, 'analysis': result['content']})

    except Exception as e:
        return JsonResponse({'status': False, 'msg': str(e)})


# ===========================
# 2. WebSSH 审计
# ===========================
@login_required
def audit_terminal_log(request, log_id):
    if request.method != 'POST':
        return JsonResponse({'status': False, 'msg': 'Method not allowed'})

    model_id = request.POST.get('model_id')

    try:
        log = TerminalLog.objects.get(id=log_id)
        if not log.log_file:
            return JsonResponse({'status': False, 'msg': '无录像文件'})

        content_lines = []
        with log.log_file.open('r') as f:
            for line in f:
                try:
                    item = json.loads(line)
                    if 'data' in item: content_lines.append(item['data'])
                except:
                    pass

        full_log = "".join(content_lines)[:4000]  # 截断

        prompt = f"""
        请审计以下 Linux SSH 终端操作录屏文本：

        {full_log}

        请分析：
        1. 操作者的主要目的是什么？
        2. 是否包含 rm -rf, drop table, wget 等高危或敏感命令？
        3. 是否有数据泄露风险？
        4. 给出安全评分 (0-100分，100为最安全)。
        """

        result = ask_ai(prompt, model_id=model_id, system_role="你是一个网络安全审计专家。")

        if "error" in result:
            return JsonResponse({'status': False, 'msg': result['error']})

        return JsonResponse({'status': True, 'report': result['content']})

    except Exception as e:
        return JsonResponse({'status': False, 'msg': str(e)})


# ===========================
# 3. AI 对话平台
# ===========================
@login_required
def chat_index(request):
    sessions = ChatSession.objects.filter(user=request.user)
    session_id = request.GET.get('session_id')
    current_session = None
    messages = []

    if session_id:
        current_session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        messages = current_session.messages.all()

    # 传递 AI 模型列表供前端选择
    return render(request, 'ai_ops/chat_ui.html', {
        'sessions': sessions,
        'current_session': current_session,
        'chat_messages': messages,
        'ai_models': AIModel.objects.all()
    })


@login_required
def create_session(request):
    session = ChatSession.objects.create(user=request.user, title="新对话")
    return JsonResponse({'status': True, 'session_id': session.id})


@login_required
def delete_session(request, session_id):
    ChatSession.objects.filter(id=session_id, user=request.user).delete()
    return JsonResponse({'status': True})


@login_required
@csrf_exempt
def send_msg(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'})

    try:
        data = json.loads(request.body)
        session_id = data.get('session_id')
        user_input = data.get('content')
        model_id = data.get('model_id')  # 前端传入

        if not session_id or not user_input:
            return JsonResponse({'error': '参数缺失'})

        session = get_object_or_404(ChatSession, id=session_id, user=request.user)

        # 更新会话绑定的模型
        if model_id:
            session.ai_model_id = model_id
            session.save()

        # 保存用户消息
        ChatMessage.objects.create(session=session, role='user', content=user_input)

        if session.messages.count() <= 1:
            session.title = user_input[:15]
            session.save()

        # 上下文
        history = session.messages.order_by('-created_at')[:10][::-1]
        context_msgs = [{"role": "system", "content": "你是一个专业的运维开发助手 AiOps AI。"}]
        for msg in history:
            context_msgs.append({"role": msg.role, "content": msg.content})

        # 调用 AI (使用 session.ai_model_id)
        client, model_name, err = get_ai_client(session.ai_model_id)
        if not client: return JsonResponse({'error': err})

        response = client.chat.completions.create(
            model=model_name,
            messages=context_msgs,
            temperature=0.7
        )
        ai_text = response.choices[0].message.content

        ChatMessage.objects.create(session=session, role='assistant', content=ai_text)

        return JsonResponse({'status': True, 'reply': ai_text})

    except Exception as e:
        return JsonResponse({'status': False, 'error': str(e)})


@login_required
@csrf_exempt
def generate_command(request):
    """
    WebSSH AI 助手：将自然语言需求转换为可执行的 Shell 命令
    """
    if request.method != 'POST':
        return JsonResponse({'status': False, 'msg': 'Method not allowed'})

    # 获取参数
    requirement = request.POST.get('requirement')
    os_name = request.POST.get('os', 'Linux')  # 默认 Linux，也可由前端传入具体发行版
    model_id = request.POST.get('model_id')  # 可选：指定使用的 AI 模型

    if not requirement:
        return JsonResponse({'status': False, 'msg': '请输入您的需求'})

    # 构造提示词 (Prompt)
    prompt = f"""
    你是一个资深的 Linux Shell 专家。请将用户的自然语言描述转换为一条精准、可执行的 {os_name} 命令。

    用户需求: {requirement}

    严格要求：
    1. 仅返回命令本身，不要包含 ```bash、``` 或任何 Markdown 格式。
    2. 不要包含任何解释、注释或多余的文字。
    3. 如果涉及高危操作（如 rm -rf），请确保命令是针对用户指定目标的。
    4. 如果需要多步操作，请使用 && 或 ; 连接。
    """

    try:
        # 调用通用的 ask_ai 工具函数 (在 ai_ops/utils.py 中定义)
        # system_role 设定为 Shell 生成器，减少 AI 废话
        result = ask_ai(prompt, model_id=model_id, system_role="Linux Shell Command Generator")

        if 'error' in result:
            return JsonResponse({'status': False, 'msg': result['error']})

        # 清理返回结果中的特殊字符（防止 AI 偶尔还是带了 Markdown 符号）
        cmd = result['content'].strip().replace('`', '').strip()

        return JsonResponse({'status': True, 'command': cmd})

    except Exception as e:
        return JsonResponse({'status': False, 'msg': str(e)})


@login_required
@csrf_exempt
def explain_log(request):
    """
    WebSSH AI 助手：解释选中的日志/报错
    """
    if request.method != 'POST':
        return JsonResponse({'status': False, 'msg': 'Method not allowed'})

    content = request.POST.get('content')
    model_id = request.POST.get('model_id')

    if not content:
        return JsonResponse({'status': False, 'msg': '请选择要解释的内容'})

    # 截取过长内容，防止 Token 溢出
    content = content[:2000]

    prompt = f"""
    请作为一名资深 Linux 运维专家，解释以下终端输出或日志报错的含义，并给出具体的排查或解决建议。

    【日志内容】：
    ```
    {content}
    ```

    请按以下格式回答：
    1. **问题分析**：简要说明发生了什么。
    2. **可能原因**：列出导致该问题的常见原因。
    3. **解决建议**：给出具体的修复命令或操作步骤。
    """

    try:
        result = ask_ai(prompt, model_id=model_id, system_role="Linux Log Analyzer")
        if 'error' in result:
            return JsonResponse({'status': False, 'msg': result['error']})
        return JsonResponse({'status': True, 'analysis': result['content']})
    except Exception as e:
        return JsonResponse({'status': False, 'msg': str(e)})


@login_required
@csrf_exempt
def assess_risk(request):
    """
    高危命令风险评估
    """
    if request.method != 'POST': return JsonResponse({'status': False})

    cmd = request.POST.get('command')
    model_id = request.POST.get('model_id')

    prompt = f"""
    用户准备在 Linux 服务器上执行高危命令：
    `{cmd}`

    请作为安全专家进行评估：
    1. 【破坏性】：该命令会造成什么后果？（如数据丢失、系统崩溃）
    2. 【可逆性】：操作是否可逆？
    3. 【建议】：是否应该执行？或者有更安全的替代方案？

    请简明扼要，用警告语气回答。
    """

    try:
        res = ask_ai(prompt, model_id=model_id, system_role="Linux Security Auditor")
        if 'error' in res: return JsonResponse({'status': False, 'msg': res['error']})
        return JsonResponse({'status': True, 'assessment': res['content']})
    except Exception as e:
        return JsonResponse({'status': False, 'msg': str(e)})


@login_required
def chat_index(request):
    """
    AI对话窗口
    """
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    current_session = None
    chat_messages = []

    session_id = request.GET.get('session_id')
    if session_id:
        try:
            current_session = sessions.get(id=session_id)
            chat_messages = ChatMessage.objects.filter(session=current_session).order_by('created_at')
        except ChatSession.DoesNotExist:
            pass

    ai_models = AIModel.objects.all()
    return render(request, 'ai_ops/chat_ui.html', {
        'sessions': sessions,
        'current_session': current_session,
        'chat_messages': chat_messages,
        'ai_models': ai_models,
        'page_title': 'AI 对话助手',
    })


@login_required
def create_session(request):
    session = ChatSession.objects.create(user=request.user, title='新会话')
    return JsonResponse({'status': True, 'session_id': session.id})


@login_required
def delete_session(request, session_id):
    ChatSession.objects.filter(id=session_id, user=request.user).delete()
    return JsonResponse({'status': True})