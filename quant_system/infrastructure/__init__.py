# quant_system/infrastructure/__init__.py
"""
基础设施层
包含券商接口、数据管理等技术实现
"""

from .brokers.base import Broker
from .brokers.futu_link import FutuBroker

__all__ = ['Broker', 'FutuBroker']