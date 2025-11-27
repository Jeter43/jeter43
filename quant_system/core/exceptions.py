# quant_system/core/exceptions.py

"""
统一异常处理模块 - 定义量化交易系统的所有自定义异常
提供清晰的异常层次结构和错误处理机制
"""

from typing import Optional, Dict, Any, List

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


# ============================================================================
# 配置相关异常
# ============================================================================

class ConfigError(QuantSystemError):
    """配置相关异常基类"""
    pass


class ConfigNotFoundError(ConfigError):
    """配置未找到异常"""
    pass


class ConfigValidationError(ConfigError):
    """配置验证失败异常"""
    pass


class EnvironmentConfigError(ConfigError):
    """环境配置异常"""
    pass


# ============================================================================
# 交易系统基础异常
# ============================================================================

class TradingSystemError(QuantSystemError):
    """交易系统基础异常"""

    def __init__(self, message: str, system_component: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if system_component:
            details['system_component'] = system_component
        super().__init__(message, error_code="TRADING_SYSTEM_ERROR", details=details)


class InsufficientFundsError(QuantSystemError):
    """资金不足异常"""

    def __init__(self, message: str, required_amount: Optional[float] = None,
                 available_amount: Optional[float] = None, **kwargs):
        details = kwargs.pop('details', {})
        if required_amount is not None:
            details['required_amount'] = required_amount
        if available_amount is not None:
            details['available_amount'] = available_amount
        super().__init__(message, error_code="INSUFFICIENT_FUNDS", details=details)


class TradingSessionError(QuantSystemError):
    """交易会话异常"""

    def __init__(self, message: str, session_id: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if session_id:
            details['session_id'] = session_id
        super().__init__(message, error_code="TRADING_SESSION_ERROR", details=details)


class PortfolioError(QuantSystemError):
    """投资组合异常"""

    def __init__(self, message: str, portfolio_id: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if portfolio_id:
            details['portfolio_id'] = portfolio_id
        super().__init__(message, error_code="PORTFOLIO_ERROR", details=details)


# ============================================================================
# Broker 相关异常
# ============================================================================

class BrokerError(QuantSystemError):
    """Broker异常基类"""
    pass


class BrokerConnectionError(BrokerError):
    """Broker连接异常"""

    def __init__(self, message: str, broker_type: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if broker_type:
            details['broker_type'] = broker_type
        super().__init__(message, error_code="BROKER_CONNECTION_ERROR", details=details)


class BrokerOperationError(BrokerError):
    """Broker操作异常"""

    def __init__(self, message: str, operation: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if operation:
            details['operation'] = operation
        super().__init__(message, error_code="BROKER_OPERATION_ERROR", details=details)


class OrderExecutionError(BrokerError):
    """订单执行异常"""

    def __init__(self, message: str, symbol: Optional[str] = None, order_id: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if symbol:
            details['symbol'] = symbol
        if order_id:
            details['order_id'] = order_id
        super().__init__(message, error_code="ORDER_EXECUTION_ERROR", details=details)


class MarketDataError(BrokerError):
    """市场数据异常"""

    def __init__(self, message: str, symbol: Optional[str] = None, data_type: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if symbol:
            details['symbol'] = symbol
        if data_type:
            details['data_type'] = data_type
        super().__init__(message, error_code="MARKET_DATA_ERROR", details=details)


# ============================================================================
# 市场相关异常
# ============================================================================

class MarketError(QuantSystemError):
    """市场相关异常基类"""
    pass


class MarketNotSupportedError(MarketError):
    """市场不支持异常"""

    def __init__(self, message: str, market_type: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if market_type:
            details['market_type'] = market_type
        super().__init__(message, error_code="MARKET_NOT_SUPPORTED", details=details)


class MarketClosedError(MarketError):
    """市场已关闭异常"""

    def __init__(self, message: str, market_type: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if market_type:
            details['market_type'] = market_type
        super().__init__(message, error_code="MARKET_CLOSED", details=details)


# ============================================================================
# 数据管理相关异常
# ============================================================================

class DataError(QuantSystemError):
    """数据相关异常基类"""
    pass


class DataManagerError(DataError):
    """数据管理器异常"""

    def __init__(self, message: str, operation: Optional[str] = None, symbol: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if operation:
            details['operation'] = operation
        if symbol:
            details['symbol'] = symbol
        super().__init__(message, error_code="DATA_MANAGER_ERROR", details=details)


class DataValidationError(DataError):
    """数据验证异常"""

    def __init__(self, message: str, data_type: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if data_type:
            details['data_type'] = data_type
        super().__init__(message, error_code="DATA_VALIDATION_ERROR", details=details)


class DataNotFoundError(DataError):
    """数据未找到异常"""

    def __init__(self, message: str, data_type: Optional[str] = None, identifier: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if data_type:
            details['data_type'] = data_type
        if identifier:
            details['identifier'] = identifier
        super().__init__(message, error_code="DATA_NOT_FOUND", details=details)


# ============================================================================
# 策略相关异常
# ============================================================================

class StrategyError(QuantSystemError):
    """策略相关异常基类"""
    pass


class StrategyExecutionError(StrategyError):
    """策略执行异常"""

    def __init__(self, message: str, strategy_name: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if strategy_name:
            details['strategy_name'] = strategy_name
        super().__init__(message, error_code="STRATEGY_EXECUTION_ERROR", details=details)


class StrategyValidationError(StrategyError):
    """策略验证异常"""

    def __init__(self, message: str, strategy_name: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if strategy_name:
            details['strategy_name'] = strategy_name
        super().__init__(message, error_code="STRATEGY_VALIDATION_ERROR", details=details)


# ============================================================================
# 风控相关异常
# ============================================================================

class RiskManagementError(QuantSystemError):
    """风控相关异常基类"""
    pass


class RiskLimitExceededError(RiskManagementError):
    """风险限额超限异常"""

    def __init__(self, message: str, limit_type: Optional[str] = None, current_value: Optional[float] = None, **kwargs):
        details = kwargs.pop('details', {})
        if limit_type:
            details['limit_type'] = limit_type
        if current_value is not None:
            details['current_value'] = current_value
        super().__init__(message, error_code="RISK_LIMIT_EXCEEDED", details=details)


class PositionLimitError(RiskManagementError):
    """仓位限制异常"""

    def __init__(self, message: str, symbol: Optional[str] = None, position_type: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if symbol:
            details['symbol'] = symbol
        if position_type:
            details['position_type'] = position_type
        super().__init__(message, error_code="POSITION_LIMIT_ERROR", details=details)


# ============================================================================
# 系统初始化相关异常
# ============================================================================

class SystemInitializationError(QuantSystemError):
    """系统初始化异常"""

    def __init__(self, message: str, component: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if component:
            details['component'] = component
        super().__init__(message, error_code="SYSTEM_INIT_ERROR", details=details)


class SystemShutdownError(QuantSystemError):
    """系统关闭异常"""

    def __init__(self, message: str, component: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if component:
            details['component'] = component
        super().__init__(message, error_code="SYSTEM_SHUTDOWN_ERROR", details=details)


class DependencyError(QuantSystemError):
    """依赖项异常"""

    def __init__(self, message: str, dependency: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if dependency:
            details['dependency'] = dependency
        super().__init__(message, error_code="DEPENDENCY_ERROR", details=details)


# ============================================================================
# 工具函数
# ============================================================================

def create_error_response(error: Exception) -> Dict[str, Any]:
    """创建标准化的错误响应"""
    if isinstance(error, QuantSystemError):
        return error.to_dict()
    else:
        return {
            'error_type': error.__class__.__name__,
            'message': str(error),
            'error_code': 'UNKNOWN_ERROR',
            'details': {}
        }


def is_connection_error(error: Exception) -> bool:
    """检查是否为连接类错误"""
    return isinstance(error, (BrokerConnectionError,))


def is_retryable_error(error: Exception) -> bool:
    """检查是否为可重试的错误"""
    return isinstance(error, (
        BrokerConnectionError,
        MarketDataError,
        DataNotFoundError
    ))


def get_error_category(error: Exception) -> str:
    """获取错误类别"""
    error_map = {
        'ConfigError': 'configuration',
        'BrokerError': 'broker',
        'MarketError': 'market',
        'DataError': 'data',
        'StrategyError': 'strategy',
        'RiskManagementError': 'risk'
    }

    for base_class, category in error_map.items():
        if any(base_class in str(cls) for cls in error.__class__.__bases__):
            return category

    return 'unknown'


# 导出所有异常类
__all__ = [
    # 基础异常
    'QuantSystemError',
    'TradingSystemError',

    # 配置异常
    'ConfigError',
    'ConfigNotFoundError',
    'ConfigValidationError',
    'EnvironmentConfigError',

    # Broker异常
    'BrokerError',
    'BrokerConnectionError',
    'BrokerOperationError',
    'OrderExecutionError',
    'MarketDataError',

    # 市场异常
    'MarketError',
    'MarketNotSupportedError',
    'MarketClosedError',

    # 数据异常
    'DataError',
    'DataManagerError',
    'DataValidationError',
    'DataNotFoundError',

    # 策略异常
    'StrategyError',
    'StrategyExecutionError',
    'StrategyValidationError',

    # 风控异常
    'RiskManagementError',
    'RiskLimitExceededError',
    'PositionLimitError',

    # 资金异常
    'InsufficientFundsError',  # 新增

    # 系统异常
    'SystemInitializationError',
    'SystemShutdownError',
    'DependencyError',
    'TradingSessionError',     # 新增
    'PortfolioError',          # 新增

    # 工具函数
    'create_error_response',
    'is_connection_error',
    'is_retryable_error',
    'get_error_category'
]