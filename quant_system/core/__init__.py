# quant_system/core/__init__.py
"""
核心框架模块
包含配置管理、事件系统、异常定义等
"""

from .config import ConfigManager, SystemMode, SelectionStrategy, RiskStrategy
from .trading_config import TradingConfig, BacktestConfig, BrokerConfig
from .events import Event, EventType, EventBus, event_bus
from .exceptions import TradingSystemError, BrokerConnectionError, OrderExecutionError, InsufficientFundsError
from .logger import (
    logger,
    colored_logger,
    setup_logger,
    setup_colored_logger,
    get_logger,
    info,
    debug,
    warning,
    error,
    critical,
    exception,
    LoggerConfig
)

__all__ = [
    'ConfigManager',
    'TradingConfig',
    'BacktestConfig',
    'BrokerConfig',
    'SystemMode',
    'SelectionStrategy',
    'RiskStrategy',
    'Event', 'EventType', 'EventBus', 'event_bus',
    'TradingSystemError',
    'BrokerConnectionError',
    'OrderExecutionError',
    'InsufficientFundsError',
    'logger',
    'colored_logger',
    'setup_logger',
    'setup_colored_logger',
    'get_logger',
    'info',
    'debug',
    'warning',
    'error',
    'critical',
    'exception',
    'LoggerConfig'
]