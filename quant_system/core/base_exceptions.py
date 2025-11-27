#quant_system/core/base_exceptions.py
"""
基础异常模块 - 避免循环导入
包含不依赖其他模块的基础异常类
"""

from typing import Optional, Dict, Any


class QuantSystemError(Exception):
    """量化系统基础异常类"""

    def __init__(self, message: str, error_code: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，便于序列化"""
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'error_code': self.error_code,
            'details': self.details
        }


class ConfigError(QuantSystemError):
    """配置相关异常基类"""
    pass


class ConfigValidationError(ConfigError):
    """配置验证失败异常"""
    pass


class ConfigNotFoundError(ConfigError):
    """配置未找到异常"""
    pass


class EnvironmentConfigError(ConfigError):
    """环境配置异常"""
    pass


# 导出所有基础异常类
__all__ = [
    'QuantSystemError',
    'ConfigError',
    'ConfigValidationError',
    'ConfigNotFoundError',
    'EnvironmentConfigError'
]