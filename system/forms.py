from django import forms
from django.contrib.auth.models import Group


class RoleForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']

    name = forms.CharField(
        label="角色名称",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '例如：运维经理'})
    )
