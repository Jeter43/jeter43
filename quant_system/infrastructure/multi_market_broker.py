# quant_system/infrastructure/multi_market_broker.py

"""
多市场Broker管理器 - 优化版本
统一管理不同市场的券商连接，提供完整的配置集成和错误处理
"""

import sys
import os
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from enum import Enum
from functools import wraps
import threading
from dataclasses import dataclass

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.core.events import EventType
from quant_system.utils.logger import get_logger
from quant_system.utils.monitoring import performance_monitor
from quant_system.core.config import ConfigManager, MarketType, BrokerType
from quant_system.core.exceptions import (
    BrokerConnectionError,
    BrokerOperationError,
    OrderExecutionError,
    MarketNotSupportedError,
    DataManagerError
)
from quant_system.core.events import Event, EventType, event_bus
from .brokers.base import Broker
from .brokers.futu_link import FutuBroker

try:
    from .brokers.binance_link import BinanceBroker
    BINANCE_AVAILABLE = True
except ImportError:
    BinanceBroker = None
    BINANCE_AVAILABLE = False


def handle_multi_market_errors(func):
    """多市场Broker错误处理装饰器"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            error_msg = f"多市场Broker操作失败 [{func.__name__}]: {e}"
            self.logger.error(error_msg)
            raise BrokerOperationError(error_msg) from e
    return wrapper


class ConnectionStatus(Enum):
    """连接状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MarketConnection:
    """市场连接信息"""
    market_type: MarketType
    broker: Broker
    status: ConnectionStatus
    connect_time: Optional[datetime]
    last_activity: Optional[datetime]
    error_count: int


class MultiMarketBroker:
    """多市场Broker管理器 - 优化版本"""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.logger = get_logger(__name__)

        # 连接管理
        self._market_connections: Dict[MarketType, MarketConnection] = {}
        self._current_market: Optional[MarketType] = None
        self._connection_lock = threading.RLock()

        # 性能统计
        self._start_time = datetime.now()
        self._total_operations = 0

        # 自动重连配置
        self._auto_reconnect = True
        self._max_reconnect_attempts = 3

    @performance_monitor("multi_market_connect")
    @handle_multi_market_errors
    def connect(self) -> bool:
        """连接所有已启用市场的Broker - 修复版本"""
        self.logger.info("🔗 连接多市场Broker...")
        # 详细日志已移至日志文件，控制台不显示

        with self._connection_lock:
            # 修复：优先连接当前市场
            current_market = self.config.current_market
            if not current_market:
                self.logger.error("❌ 没有设置当前市场")
                # 详细日志已移至日志文件
                return False

            self.logger.info(f"🔗 连接当前市场: {current_market.value}")
            # 详细日志已移至日志文件

            # 只连接当前市场
            # 详细日志已移至日志文件
            connection_result = self._connect_market(current_market)
            # 详细日志已移至日志文件

            if connection_result:
                # 设置当前市场
                self._current_market = current_market
                self.logger.info(f"✅ 多市场Broker连接完成: 当前市场 {current_market.value}")
                # 详细日志已移至日志文件

                # 发布连接事件（如果失败不影响连接）
                try:
                    # 详细日志已移至日志文件
                    event_bus.publish(Event(
                        event_type=EventType.MULTI_MARKET_CONNECTED,
                        data={
                            'connected_markets': self.get_connected_markets(),
                            'default_market': self._current_market.value,
                            'timestamp': datetime.now()
                        }
                    ))
                    # 详细日志已移至日志文件
                except Exception as e:
                    self.logger.warning(f"⚠️ 发布连接事件失败: {e}，但不影响连接")
                    # 详细日志已移至日志文件
                
                # 详细日志已移至日志文件
                return True
            else:
                self.logger.error(f"❌ 当前市场 {current_market.value} 连接失败")
                return False

    @handle_multi_market_errors
    def _connect_market(self, market_type: MarketType) -> bool:
        """连接指定市场的Broker"""
        market_config = self.config.multi_market.get_market_config(market_type)
        if not market_config:
            self.logger.warning(f"市场 {market_type.value} 配置不存在")
            return False

        try:
            # 创建Broker实例
            broker = self._create_broker(market_config)
            if not broker:
                self.logger.warning(f"不支持的券商类型: {market_config.broker_type.value}")
                return False

            # 更新连接状态
            self._market_connections[market_type] = MarketConnection(
                market_type=market_type,
                broker=broker,
                status=ConnectionStatus.CONNECTING,
                connect_time=None,
                last_activity=None,
                error_count=0
            )

            # 连接Broker
            if broker.connect():
                connection = self._market_connections[market_type]
                connection.status = ConnectionStatus.CONNECTED
                connection.connect_time = datetime.now()
                connection.last_activity = datetime.now()

                self.logger.info(f"✅ {market_type.value} 市场连接成功")
                return True
            else:
                connection = self._market_connections[market_type]
                connection.status = ConnectionStatus.ERROR
                connection.error_count += 1

                self.logger.error(f"❌ {market_type.value} 市场连接失败")
                return False

        except Exception as e:
            self.logger.error(f"连接 {market_type.value} 市场异常: {e}")

            # 更新错误状态
            if market_type in self._market_connections:
                connection = self._market_connections[market_type]
                connection.status = ConnectionStatus.ERROR
                connection.error_count += 1

            return False

    def _create_broker(self, market_config) -> Optional[Broker]:
        """创建Broker实例"""
        broker_type = market_config.broker_type

        broker_map = {
            BrokerType.FUTU: FutuBroker,
            # BrokerType.EASTMONEY: EastMoneyBroker,  # 后续实现
        }
        
        # 添加 Binance broker（如果可用）
        if BINANCE_AVAILABLE and BinanceBroker:
            broker_map[BrokerType.BINANCE] = BinanceBroker

        broker_class = broker_map.get(broker_type)
        if broker_class:
            return broker_class(self.config)
        else:
            self.logger.warning(f"不支持的券商类型: {broker_type.value}")
            if broker_type == BrokerType.BINANCE and not BINANCE_AVAILABLE:
                self.logger.warning("💡 提示: 需要安装 python-binance 库: pip install python-binance")
            return None

    @performance_monitor("multi_market_switch")
    @handle_multi_market_errors
    def switch_market(self, market_type: MarketType) -> bool:
        """切换当前市场"""
        with self._connection_lock:
            if market_type not in self._market_connections:
                self.logger.error(f"市场 {market_type.value} 未连接")
                return False

            connection = self._market_connections[market_type]
            if connection.status != ConnectionStatus.CONNECTED:
                self.logger.error(f"市场 {market_type.value} 连接状态异常: {connection.status.value}")
                return False

            self._current_market = market_type
            self.config.switch_market(market_type)
            connection.last_activity = datetime.now()

            self.logger.info(f"🔄 已切换到 {market_type.value} 市场")

            # 发布市场切换事件
            event_bus.publish(Event(
                event_type=EventType.MARKET_SWITCHED,
                data={
                    'market_type': market_type.value,
                    'timestamp': datetime.now()
                }
            ))

            return True

    def get_current_broker(self) -> Optional[Broker]:
        """获取当前Broker"""
        if self._current_market and self._current_market in self._market_connections:
            return self._market_connections[self._current_market].broker
        return None

    def get_broker(self, market_type: MarketType) -> Optional[Broker]:
        """获取指定市场的Broker"""
        if market_type in self._market_connections:
            return self._market_connections[market_type].broker
        return None

    def is_market_connected(self, market_type: MarketType) -> bool:
        """检查市场是否已连接"""
        return (market_type in self._market_connections and
                self._market_connections[market_type].status == ConnectionStatus.CONNECTED)

    def get_connected_markets(self) -> List[MarketType]:
        """获取已连接的市场列表"""
        return [
            market_type for market_type, connection in self._market_connections.items()
            if connection.status == ConnectionStatus.CONNECTED
        ]

    def get_connection_status(self, market_type: MarketType) -> Optional[ConnectionStatus]:
        """获取市场连接状态"""
        if market_type in self._market_connections:
            return self._market_connections[market_type].status
        return None

    @handle_multi_market_errors
    def disconnect(self):
        """断开所有Broker连接"""
        self.logger.info("🔚 断开所有市场连接...")

        with self._connection_lock:
            for market_type, connection in self._market_connections.items():
                try:
                    connection.broker.disconnect()
                    connection.status = ConnectionStatus.DISCONNECTED
                    self.logger.info(f"🔌 断开 {market_type.value} 市场连接")
                except Exception as e:
                    self.logger.error(f"断开 {market_type.value} 连接异常: {e}")

            self._market_connections.clear()
            self._current_market = None

            # 发布断开事件
            event_bus.publish(Event(
                event_type=EventType.MULTI_MARKET_DISCONNECTED,
                data={'timestamp': datetime.now()}
            ))

            self.logger.info("✅ 所有市场连接已断开")

    @handle_multi_market_errors
    def reconnect_market(self, market_type: MarketType) -> bool:
        """重新连接指定市场"""
        self.logger.info(f"🔄 重新连接 {market_type.value} 市场...")

        # 先断开连接
        if market_type in self._market_connections:
            try:
                self._market_connections[market_type].broker.disconnect()
            except Exception as e:
                self.logger.warning(f"断开 {market_type.value} 连接时发生异常: {e}")

        # 重新连接
        return self._connect_market(market_type)

    # 代理方法 - 将调用转发给当前Broker
    @performance_monitor("multi_market_get_account_info")
    @handle_multi_market_errors
    def get_account_info(self) -> Dict[str, float]:
        """获取当前市场账户信息"""
        broker = self.get_current_broker()
        if broker:
            self._total_operations += 1
            return broker.get_account_info()
        return {}

    @performance_monitor("multi_market_get_positions")
    @handle_multi_market_errors
    def get_positions(self, symbols: List[str] = None) -> Dict[str, Any]:
        """获取当前市场持仓"""
        broker = self.get_current_broker()
        if broker:
            self._total_operations += 1
            return broker.get_positions(symbols)
        return {}

    @performance_monitor("multi_market_get_market_snapshot")
    @handle_multi_market_errors
    def get_market_snapshot(self, symbols: List[str]) -> Dict[str, Any]:
        """获取当前市场快照"""
        broker = self.get_current_broker()
        if broker:
            self._total_operations += 1
            return broker.get_market_snapshot(symbols)
        return {}

    @performance_monitor("multi_market_place_order")
    @handle_multi_market_errors
    def place_order(self, symbol: str, quantity: int, price: float,
                   side: str, order_type: str = "MARKET") -> bool:
        """在当前市场下单"""
        broker = self.get_current_broker()
        if broker:
            self._total_operations += 1

            # 更新活动时间
            if self._current_market in self._market_connections:
                self._market_connections[self._current_market].last_activity = datetime.now()

            return broker.place_order(symbol, quantity, price, side, order_type)
        return False

    @performance_monitor("multi_market_subscribe")
    @handle_multi_market_errors
    def subscribe(self, symbols: List[str], subtypes: List[str]) -> bool:
        """订阅当前市场行情"""
        broker = self.get_current_broker()
        if broker:
            self._total_operations += 1
            return broker.subscribe(symbols, subtypes)
        return False

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        current_uptime = (datetime.now() - self._start_time).total_seconds()

        market_stats = {}
        for market_type, connection in self._market_connections.items():
            market_stats[market_type.value] = {
                'status': connection.status.value,
                'connect_time': connection.connect_time,
                'last_activity': connection.last_activity,
                'error_count': connection.error_count,
                'uptime': (datetime.now() - connection.connect_time).total_seconds()
                          if connection.connect_time else 0
            }

        return {
            'total_operations': self._total_operations,
            'total_uptime': current_uptime,
            'current_market': self._current_market.value if self._current_market else None,
            'connected_markets': len(self.get_connected_markets()),
            'market_stats': market_stats
        }

    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        health_status = {
            'overall': 'healthy',
            'markets': {},
            'timestamp': datetime.now()
        }

        for market_type in self.config.multi_market.get_enabled_markets():
            market_health = {
                'configured': True,
                'connected': self.is_market_connected(market_type),
                'status': self.get_connection_status(market_type).value
                         if self.get_connection_status(market_type) else 'unknown'
            }

            if not market_health['connected'] and market_health['configured']:
                health_status['overall'] = 'degraded'

            health_status['markets'][market_type.value] = market_health

        return health_status


# 导出类
__all__ = ['MultiMarketBroker', 'ConnectionStatus', 'MarketConnection']