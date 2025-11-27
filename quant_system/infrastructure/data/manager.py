# trading_system/infrastructure/data/manager.py
"""
数据管理器 - 优化版本
提供统一的市场数据和持仓数据管理
"""

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import pandas as pd
from functools import wraps

from quant_system.utils.logger import get_logger
from quant_system.utils.monitoring import performance_monitor
from quant_system.core.exceptions import DataManagerError


def handle_data_errors(func):
    """数据管理器错误处理装饰器"""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            error_msg = f"数据管理器操作失败 [{func.__name__}]: {e}"
            self.logger.error(error_msg)
            raise DataManagerError(error_msg) from e

    return wrapper


@dataclass
class MarketData:
    """市场数据类"""
    symbol: str
    last_price: float
    open_price: float
    high_price: float
    low_price: float
    volume: int
    change_rate: float
    turnover: float
    timestamp: datetime
    prev_close: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_volume: int = 0
    ask_volume: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MarketData':
        """从字典创建市场数据"""
        return cls(
            symbol=str(data.get('code', '')).strip(),
            last_price=float(data.get('last_price', 0)),
            open_price=float(data.get('open_price', 0)),
            high_price=float(data.get('high_price', 0)),
            low_price=float(data.get('low_price', 0)),
            volume=int(data.get('volume', 0)),
            change_rate=float(data.get('change_rate', 0)),
            turnover=float(data.get('turnover', 0)),
            timestamp=datetime.now(),
            prev_close=float(data.get('prev_close', data.get('close_price', 0))),
            bid_price=float(data.get('bid_price', 0)),
            ask_price=float(data.get('ask_price', 0)),
            bid_volume=int(data.get('bid_volume', 0)),
            ask_volume=int(data.get('ask_volume', 0))
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @property
    def price_change(self) -> float:
        """价格变动"""
        return self.last_price - self.prev_close

    @property
    def is_positive(self) -> bool:
        """是否上涨"""
        return self.change_rate > 0


@dataclass
class PositionData:
    """持仓数据类"""
    symbol: str
    quantity: int
    cost_price: float
    market_value: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_rate: float
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any], current_price: float = 0) -> 'PositionData':
        """从字典创建持仓数据"""
        quantity = int(data.get('quantity', 0))
        cost_price = float(data.get('cost_price', 0))
        market_value = float(data.get('market_value', quantity * current_price))

        # 计算盈亏
        unrealized_pnl = (current_price - cost_price) * quantity if quantity > 0 else 0
        unrealized_pnl_rate = (current_price / cost_price - 1) * 100 if cost_price > 0 else 0

        return cls(
            symbol=str(data.get('symbol', '')).strip(),
            quantity=quantity,
            cost_price=cost_price,
            market_value=market_value,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_rate=unrealized_pnl_rate,
            timestamp=datetime.now()
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @property
    def is_profitable(self) -> bool:
        """是否盈利"""
        return self.unrealized_pnl > 0


class DataManager:
    """数据管理器 - 优化版本"""

    def __init__(self, broker):
        self.broker = broker
        self.logger = get_logger(__name__)

        # 数据缓存
        self._market_data_cache: Dict[str, MarketData] = {}
        self._position_data_cache: Dict[str, PositionData] = {}
        self._last_update_time: Optional[datetime] = None

        # 统计信息
        self._update_count = 0

    @performance_monitor("data_get_current_price")
    @handle_data_errors
    def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        symbol = symbol.strip().upper()

        # 检查缓存
        if symbol in self._market_data_cache:
            cached_data = self._market_data_cache[symbol]
            # 检查缓存是否过期（5秒）
            if (datetime.now() - cached_data.timestamp).total_seconds() < 5:
                return cached_data.last_price

        # 从broker获取最新数据
        snapshot = self.broker.get_market_snapshot([symbol])
        if symbol in snapshot:
            price = float(snapshot[symbol].get('last_price', 0))

            # 更新缓存
            market_data = MarketData.from_dict(snapshot[symbol])
            self._market_data_cache[symbol] = market_data
            self._last_update_time = datetime.now()
            self._update_count += 1

            return price

        self.logger.warning(f"无法获取 {symbol} 的当前价格")
        return 0.0

    @performance_monitor("data_get_market_data")
    @handle_data_errors
    def get_market_data(self, symbols: List[str]) -> Dict[str, MarketData]:
        """获取多个标的的市场数据"""
        if not symbols:
            return {}

        symbols = [s.strip().upper() for s in symbols]

        # 检查缓存中已有的数据
        result = {}
        symbols_to_fetch = []

        for symbol in symbols:
            if symbol in self._market_data_cache:
                cached_data = self._market_data_cache[symbol]
                # 检查缓存是否过期
                if (datetime.now() - cached_data.timestamp).total_seconds() < 5:
                    result[symbol] = cached_data
                else:
                    symbols_to_fetch.append(symbol)
            else:
                symbols_to_fetch.append(symbol)

        # 获取缺失的数据
        if symbols_to_fetch:
            snapshot = self.broker.get_market_snapshot(symbols_to_fetch)
            for symbol in symbols_to_fetch:
                if symbol in snapshot:
                    market_data = MarketData.from_dict(snapshot[symbol])
                    self._market_data_cache[symbol] = market_data
                    result[symbol] = market_data
                else:
                    self.logger.warning(f"无法获取 {symbol} 的市场数据")

        self._last_update_time = datetime.now()
        self._update_count += len(symbols_to_fetch)

        return result

    @performance_monitor("data_get_positions")
    @handle_data_errors
    def get_positions(self, symbols: Optional[List[str]] = None) -> Dict[str, PositionData]:
        """获取持仓数据"""
        # 从broker获取持仓信息
        positions_data = self.broker.get_positions(symbols)

        result = {}
        symbols_to_check = list(positions_data.keys()) if not symbols else symbols

        if symbols_to_check:
            # 获取当前价格
            market_data = self.get_market_data(symbols_to_check)

            for symbol in symbols_to_check:
                if symbol in positions_data:
                    current_price = market_data[symbol].last_price if symbol in market_data else 0.0

                    position_data = PositionData.from_dict(
                        {**positions_data[symbol], 'symbol': symbol},
                        current_price
                    )
                    result[symbol] = position_data
                    self._position_data_cache[symbol] = position_data

        return result

    @performance_monitor("data_get_portfolio_value")
    @handle_data_errors
    def get_portfolio_value(self) -> Dict[str, float]:
        """获取投资组合价值"""
        account_info = self.broker.get_account_info()
        positions = self.get_positions()

        total_market_value = sum(pos.market_value for pos in positions.values())
        total_pnl = sum(pos.unrealized_pnl for pos in positions.values())

        return {
            'total_assets': account_info.get('total_assets', 0),
            'cash': account_info.get('cash', 0),
            'market_value': total_market_value,
            'unrealized_pnl': total_pnl,
            'available_cash': account_info.get('available_cash', 0)
        }

    def clear_cache(self):
        """清空数据缓存"""
        cache_size = len(self._market_data_cache)
        self._market_data_cache.clear()
        self._position_data_cache.clear()
        self.logger.info(f"已清空数据缓存，原缓存大小: {cache_size}")

    def get_cache_info(self) -> Dict[str, Any]:
        """获取缓存信息"""
        return {
            'market_data_cache_size': len(self._market_data_cache),
            'position_data_cache_size': len(self._position_data_cache),
            'last_update_time': self._last_update_time,
            'total_updates': self._update_count
        }

    @handle_data_errors
    def validate_symbol(self, symbol: str) -> bool:
        """验证股票代码格式"""
        symbol = symbol.strip().upper()

        # 基本格式验证
        if not symbol:
            return False

        # 富途股票代码格式验证
        if symbol.endswith('.HK'):
            return len(symbol) > 3
        elif symbol.endswith('.US'):
            return len(symbol) > 3
        else:
            # A股代码验证
            return len(symbol) == 6 and symbol.isdigit()

    @performance_monitor("data_batch_update")
    @handle_data_errors
    def batch_update(self, symbols: List[str]) -> Dict[str, Any]:
        """批量更新数据"""
        start_time = datetime.now()

        market_data = self.get_market_data(symbols)
        positions = self.get_positions(symbols)
        portfolio = self.get_portfolio_value()

        execution_time = (datetime.now() - start_time).total_seconds()

        return {
            'market_data': market_data,
            'positions': positions,
            'portfolio': portfolio,
            'execution_time': execution_time,
            'symbols_processed': len(symbols),
            'timestamp': datetime.now()
        }