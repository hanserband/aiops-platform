# ai_ops/utils.py
from openai import OpenAI
from .models import AIModel


def get_ai_client(model_id=None):
    """
    根据 ID 获取 AI 客户端和模型名
    返回: (client, model_name, error_msg)
    """
    ai_conf = None
    if model_id:
        try:
            ai_conf = AIModel.objects.get(id=model_id)
        except AIModel.DoesNotExist:
            pass

    # 如果没指定或找不到，用默认的
    if not ai_conf:
        ai_conf = AIModel.objects.filter(is_default=True).first()

    if not ai_conf:
        # 如果连默认的都没有，随便找一个
        ai_conf = AIModel.objects.first()

    if not ai_conf:
        return None, None, "未配置任何 AI 模型，请先在【AI 模型管理】中添加。"

    try:
        client = OpenAI(
            api_key=ai_conf.api_key,
            base_url=ai_conf.base_url,
            timeout=120.0,  # <--- 强制 120秒超时，防止死等
            max_retries=2  # <--- 失败后只重试2次，不要一直试
        )
        return client, ai_conf.model_name, ""

    except Exception as e:
        return None, None, str(e)


def ask_ai(prompt, model_id=None, system_role="You are a helpful DevOps assistant."):
    """通用问答 (诊断/审计用)"""
    client, model_name, err = get_ai_client(model_id)
    if not client:
        return {"error": err}

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_role},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )
        return {"content": response.choices[0].message.content}
    except Exception as e:
        return {"error": f"AI 调用失败: {str(e)}"}