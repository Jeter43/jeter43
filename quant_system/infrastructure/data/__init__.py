# trading_system/infrastructure/data/__init__.py
"""
数据管理模块
统一的数据访问接口
"""

from .manager import MarketData, PositionData, DataManager

__all__ = ['MarketData', 'PositionData', 'DataManager']