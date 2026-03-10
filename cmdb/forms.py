from django import forms
from .models import Server, ServerGroup,CloudAccount

class ServerForm(forms.ModelForm):
    class Meta:
        model = Server
        fields = ['hostname', 'ip_address', 'port', 'group','username', 'password', 'cpu_cores',
                  'memory_gb', 'os_name', 'provider', 'status']
        widgets = {
            'hostname': forms.TextInput(attrs={'class': 'form-control'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-control'}),
            'port': forms.NumberInput(attrs={'class': 'form-control'}),
            'group': forms.Select(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '若不修改请留空'}),
            'cpu_cores': forms.NumberInput(attrs={'class': 'form-control'}),
            'memory_gb': forms.NumberInput(attrs={'class': 'form-control'}),
            'os_name': forms.TextInput(attrs={'class': 'form-control'}),
            'provider': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }

class GroupForm(forms.ModelForm):
    class Meta:
        model = ServerGroup
        fields = ['name', 'parent']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'parent': forms.Select(attrs={'class': 'form-control'}),
        }

class CloudAccountForm(forms.ModelForm):
    class Meta:
        model = CloudAccount
        fields = ['name', 'access_key', 'secret_key', 'region']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '给这个账号起个名'}),
            'access_key': forms.TextInput(attrs={'class': 'form-control'}),
            'secret_key': forms.TextInput(attrs={'class': 'form-control', 'type': 'password'}),
            'region': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'cn-hangzhou'}),
        }