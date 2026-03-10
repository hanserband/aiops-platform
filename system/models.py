from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    phone = models.CharField("手机号", max_length=11, blank=True, null=True)
    department = models.CharField("部门", max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.username
class SystemConfig(models.Model):
    """系统配置表 (Key-Value)"""
    key = models.CharField("配置项键", max_length=50, unique=True)
    value = models.TextField("配置项值", blank=True, null=True)
    description = models.CharField("描述", max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = "系统配置"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.key} = {self.value}"