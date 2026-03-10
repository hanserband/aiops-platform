# system/validators.py
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

class ComplexPasswordValidator:
    def validate(self, password, user=None):
        if not re.findall('[A-Z]', password):
            raise ValidationError(
                _("密码必须包含至少一个大写字母。"),
                code='password_no_upper',
            )
        if not re.findall('[a-z]', password):
            raise ValidationError(
                _("密码必须包含至少一个小写字母。"),
                code='password_no_lower',
            )
        if not re.findall('[0-9]', password):
            raise ValidationError(
                _("密码必须包含至少一个数字。"),
                code='password_no_number',
            )
        if not re.findall('[^A-Za-z0-9]', password):
             raise ValidationError(
                _("密码必须包含至少一个特殊字符。"),
                code='password_no_symbol',
            )

    def get_help_text(self):
        return _(
            "您的密码必须包含至少一个大写字母、小写字母、数字和特殊字符。"
        )