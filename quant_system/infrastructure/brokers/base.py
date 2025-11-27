# quant_system/infrastructure/brokers/base.py
"""
券商接口抽象基类
只包含抽象接口定义，具体实现应在单独的文件中（如 futu_link.py）
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from quant_system.infrastructure.data.manager import MarketData, PositionData


class Broker(ABC):
    """券商接口抽象基类"""

    @abstractmethod
    def connect(self) -> bool:
        """连接券商"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def get_account_info(self) -> Dict[str, float]:
        """获取账户信息"""
        pass

    @abstractmethod
    def get_positions(self, symbols: Optional[List[str]] = None) -> Dict[str, PositionData]:
        """获取持仓"""
        pass

    @abstractmethod
    def get_market_snapshot(self, symbols: List[str]) -> Dict[str, MarketData]:
        """获取市场快照"""
        pass

    @abstractmethod
    def place_order(self, symbol: str, quantity: int, price: float,
                    side: str, order_type: str = "MARKET") -> bool:
        """下单"""
        pass

    @abstractmethod
    def subscribe(self, symbols: List[str], subtypes: List[str]) -> bool:
        """订阅行情"""
        pass