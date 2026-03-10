# ai_ops/models.py
from django.db import models
from system.models import User
from fernet_fields import EncryptedCharField #

class AIModel(models.Model):
    """AI 模型配置表"""
    name = models.CharField("模型别名", max_length=50, help_text="例如: DeepSeek-V3, GPT-4")
    model_name = models.CharField("模型标识", max_length=50, help_text="API调用的模型名, 如: deepseek-chat, gpt-3.5-turbo")
    api_key = EncryptedCharField("API Key", max_length=200)
    base_url = models.CharField("Base URL", max_length=200, default="https://api.openai.com/v1")
    is_default = models.BooleanField("是否默认", default=False)

    def __str__(self):
        return self.name

class ChatSession(models.Model):
    """对话会话"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField("会话标题", max_length=100, default="新会话")
    ai_model = models.ForeignKey(AIModel, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']


class ChatMessage(models.Model):
    """对话消息记录"""
    ROLE_CHOICES = (('user', '用户'), ('assistant', 'AI'))

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField("内容")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']