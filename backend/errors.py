"""跨服务统一异常；公开消息与内部异常细节分离。"""
import re


VALIDATION_MESSAGES = {
    'missing': '缺少必填参数。',
    'extra_forbidden': '包含未声明的参数。',
    'string_type': '参数必须是文本。',
    'string_too_short': '文本长度不足。',
    'string_too_long': '文本长度超出限制。',
    'string_pattern_mismatch': '文本格式不符合要求。',
    'int_type': '参数必须是整数。',
    'int_parsing': '参数必须是有效整数。',
    'greater_than_equal': '参数值低于允许的最小值。',
    'less_than_equal': '参数值超过允许的最大值。',
    'bool_type': '参数必须是布尔值。',
    'bool_parsing': '参数必须是有效布尔值。',
    'uuid_type': '会话或记录编号必须是有效的通用唯一标识符。',
    'uuid_parsing': '会话或记录编号格式无效。',
    'list_type': '参数必须是列表。',
    'too_short': '列表元素数量不足。',
    'too_long': '列表元素数量超出限制。',
    'literal_error': '参数值不在允许的选项中。',
    'json_invalid': '请求正文不是有效的 JSON 数据。',
    'model_attributes_type': '请求正文必须是对象。',
    'model_type': '参数必须是符合要求的对象。',
}


def validation_error_message(error: dict) -> str:
    """只返回中文说明，不回显输入值或异常上下文。"""
    if error['type'] == 'value_error':
        # 保留业务校验的中文说明，去掉校验库自动添加的英文前缀。
        message = error['msg'].removeprefix('Value error, ')
        if re.search(r'[\u3400-\u9fff]', message):
            return message
    return VALIDATION_MESSAGES.get(error['type'], '参数值不符合要求。')


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)
