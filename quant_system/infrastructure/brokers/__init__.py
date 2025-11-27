# quant_system/infrastructure/brokers/__init__.py
"""
券商接口模块
支持多券商接入的统一接口
"""

from .base import Broker
from .futu_link import FutuBroker

try:
    from .binance_link import BinanceBroker
    __all__ = ['Broker', 'FutuBroker', 'BinanceBroker']
except ImportError:
    BinanceBroker = None
    __all__ = ['Broker', 'FutuBroker']