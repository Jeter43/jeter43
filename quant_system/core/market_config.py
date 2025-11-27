#quant_system/core/market_config.py
"""
市场配置管理模块 (quant_system/core/market_config.py)

功能概述：
    统一管理多市场交易配置，支持A股、港股、美股、加密货币、期货等市场。
    提供市场特定的交易时间、券商接口、货币单位等配置。

核心特性：
    1. 多市场支持：统一接口管理不同市场的交易配置
    2. 交易时间管理：自动处理不同市场的交易时间规则
    3. 券商抽象：支持多种券商接口的统一配置
    4. 货币支持：自动处理货币转换和汇率
    5. 市场状态：动态启用/禁用特定市场

设计模式：
    - 工厂模式：市场配置的创建和管理
    - 策略模式：不同市场的交易时间策略
    - 组合模式：多市场配置的统一管理

版本历史：
    v1.0 - 基础市场配置
    v2.0 - 增加多市场支持和交易时间管理
    v3.0 - 增强券商配置和货币支持
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, ClassVar
from enum import Enum
import logging
from datetime import datetime, time
import pytz

# 配置模块的日志器
logger = logging.getLogger(__name__)


class MarketType(Enum):
    """
    市场类型枚举

    支持的主要交易市场类型，每种市场有特定的交易规则和特性。
    """
    A_SHARE = "a_share"  # A股市场 - 上海/深圳证券交易所
    HK = "hk"  # 港股市场 - 香港交易所
    US = "us"  # 美股市场 - 纽约证券交易所/NASDAQ
    CRYPTO = "crypto"  # 加密货币市场 - 全球数字货币交易
    FUTURES = "futures"  # 期货市场 - 商品/金融期货
    FOREX = "forex"  # 外汇市场 - 货币对交易


class BrokerType(Enum):
    """
    券商类型枚举

    支持的券商和交易接口，每种券商有特定的API和连接方式。
    """
    FUTU = "futu"  # 富途证券 - 港股、美股主力券商
    EASTMONEY = "eastmoney"  # 东方财富 - A股主流券商
    BINANCE = "binance"  # 币安 - 加密货币交易所
    IBKR = "ibkr"  # Interactive Brokers - 国际多市场券商
    CTP = "ctp"  # CTP期货接口 - 国内期货交易
    SIMULATION = "simulation"  # 模拟交易接口 - 用于测试


@dataclass
class TradingHours:
    """
    交易时间配置

    管理市场的交易时间段，支持复杂的交易时间规则。
    包括常规交易时间、盘前盘后交易时间等。
    """
    timezone: str = "Asia/Shanghai"  # 时区
    regular_hours: List[Dict[str, str]] = field(default_factory=list)  # 常规交易时段
    pre_market_hours: List[Dict[str, str]] = field(default_factory=list)  # 盘前交易
    post_market_hours: List[Dict[str, str]] = field(default_factory=list)  # 盘后交易
    holidays: List[str] = field(default_factory=list)  # 节假日列表

    def is_trading_time(self, check_time: Optional[datetime] = None) -> bool:
        """
        检查当前是否在交易时间内

        Args:
            check_time: 检查的时间，默认为当前时间

        Returns:
            bool: 是否在交易时间内
        """
        if not check_time:
            check_time = datetime.now(pytz.timezone(self.timezone))

        # 检查是否为节假日
        date_str = check_time.strftime("%Y-%m-%d")
        if date_str in self.holidays:
            return False

        # 检查交易时间段
        for session in self.regular_hours + self.pre_market_hours + self.post_market_hours:
            start_time = self._parse_time(session['start'])
            end_time = self._parse_time(session['end'])

            current_time = check_time.time()
            if start_time <= current_time <= end_time:
                return True

        return False

    def _parse_time(self, time_str: str) -> time:
        """解析时间字符串为time对象"""
        return datetime.strptime(time_str, "%H:%M").time()

    def get_next_trading_session(self) -> Dict[str, Any]:
        """
        获取下一个交易时段信息

        Returns:
            Dict[str, Any]: 下一个交易时段的开始和结束时间
        """
        # 简化实现，实际应该计算下一个交易时段
        if self.regular_hours:
            return self.regular_hours[0]
        return {}


@dataclass
class MarketConfig:
    """
    单个市场配置

    管理特定市场的所有配置信息，包括交易规则、券商接口、货币单位等。

    属性:
        market_type: 市场类型
        broker_type: 券商类型
        enabled: 是否启用该市场
        trading_hours: 交易时间配置
        currency: 基础货币
        parameters: 市场特定参数
        min_trade_amount: 最小交易金额
        price_precision: 价格精度
        amount_precision: 数量精度
    """
    market_type: MarketType
    broker_type: BrokerType
    enabled: bool = True
    trading_hours: TradingHours = field(default_factory=TradingHours)
    currency: str = "CNY"
    parameters: Dict[str, Any] = field(default_factory=dict)
    min_trade_amount: float = 0.0
    price_precision: int = 2
    amount_precision: int = 0

    def __post_init__(self):
        """初始化后处理 - 设置默认值"""
        if not self.trading_hours.regular_hours:
            self.trading_hours = self._get_default_trading_hours()

        # 设置市场特定默认参数
        self._set_market_defaults()

        logger.debug(f"市场配置初始化: {self.market_type.value}")

    def _get_default_trading_hours(self) -> TradingHours:
        """
        获取默认交易时间配置

        Returns:
            TradingHours: 默认交易时间配置
        """
        if self.market_type == MarketType.A_SHARE:
            return TradingHours(
                timezone="Asia/Shanghai",
                regular_hours=[
                    {'start': '09:30', 'end': '11:30'},
                    {'start': '13:00', 'end': '15:00'}
                ],
                holidays=['2024-01-01', '2024-02-10', '2024-02-11']  # 示例节假日
            )
        elif self.market_type == MarketType.HK:
            return TradingHours(
                timezone="Asia/Hong_Kong",
                regular_hours=[
                    {'start': '09:30', 'end': '12:00'},
                    {'start': '13:00', 'end': '16:00'}
                ]
            )
        elif self.market_type == MarketType.US:
            return TradingHours(
                timezone="America/New_York",
                regular_hours=[
                    {'start': '09:30', 'end': '16:00'}
                ],
                pre_market_hours=[
                    {'start': '04:00', 'end': '09:30'}
                ],
                post_market_hours=[
                    {'start': '16:00', 'end': '20:00'}
                ]
            )
        elif self.market_type == MarketType.CRYPTO:
            return TradingHours(
                timezone="UTC",
                regular_hours=[
                    {'start': '00:00', 'end': '24:00'}  # 7x24小时交易
                ]
            )
        else:
            return TradingHours()

    def _set_market_defaults(self):
        """设置市场特定的默认参数"""
        defaults = {
            MarketType.A_SHARE: {
                'min_trade_amount': 100.0,  # 最小交易金额100元
                'price_precision': 2,
                'amount_precision': 0,  # 整数股
                'parameters': {'trade_unit': 100}  # 交易单位：手
            },
            MarketType.HK: {
                'min_trade_amount': 0.0,  # 港股无最小交易金额限制
                'price_precision': 3,
                'amount_precision': 0,
                'parameters': {'trade_unit': 1}
            },
            MarketType.US: {
                'min_trade_amount': 1.0,  # 最小1美元
                'price_precision': 2,
                'amount_precision': 0,
                'parameters': {'trade_unit': 1}
            },
            MarketType.CRYPTO: {
                'min_trade_amount': 10.0,  # 最小10USDT
                'price_precision': 8,  # 加密货币需要更高精度
                'amount_precision': 6,
                'parameters': {'trade_unit': 0.001}
            }
        }

        if self.market_type in defaults:
            market_defaults = defaults[self.market_type]
            self.min_trade_amount = market_defaults['min_trade_amount']
            self.price_precision = market_defaults['price_precision']
            self.amount_precision = market_defaults['amount_precision']
            self.parameters.update(market_defaults['parameters'])

    def is_market_open(self) -> bool:
        """
        检查市场是否开盘

        Returns:
            bool: 市场是否处于交易时间
        """
        return self.trading_hours.is_trading_time()

    def validate_config(self) -> List[str]:
        """
        验证市场配置有效性

        Returns:
            List[str]: 错误信息列表
        """
        errors = []

        if not self.currency:
            errors.append("货币类型不能为空")

        if self.min_trade_amount < 0:
            errors.append("最小交易金额不能为负数")

        if self.price_precision < 0:
            errors.append("价格精度不能为负数")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'market_type': self.market_type.value,
            'broker_type': self.broker_type.value,
            'enabled': self.enabled,
            'currency': self.currency,
            'min_trade_amount': self.min_trade_amount,
            'price_precision': self.price_precision,
            'amount_precision': self.amount_precision,
            'parameters': self.parameters
        }


@dataclass
class MultiMarketConfig:
    """
    多市场配置管理器

    统一管理所有市场的配置，支持市场的动态启用/禁用、默认市场设置等。

    属性:
        markets: 市场配置字典
        default_market: 默认市场类型
        auto_switch: 是否自动切换最佳市场
    """
    markets: Dict[MarketType, MarketConfig] = field(default_factory=dict)
    default_market: MarketType = MarketType.HK
    auto_switch: bool = False  # 是否自动根据条件切换市场

    def __post_init__(self):
        """初始化后处理 - 确保有默认市场配置"""
        if not self.markets:
            self._initialize_default_markets()

        # 确保默认市场存在且启用
        if (self.default_market not in self.markets or
                not self.markets[self.default_market].enabled):
            self._set_safe_default_market()

        logger.info("多市场配置管理器初始化完成")

    def _initialize_default_markets(self):
        """初始化默认市场配置"""
        self.markets = {
            MarketType.HK: MarketConfig(
                market_type=MarketType.HK,
                broker_type=BrokerType.FUTU,
                currency="HKD",
                parameters={
                    'host': '127.0.0.1',
                    'port': 11111,
                    'security_firm': 'FUTU'
                }
            ),
            MarketType.A_SHARE: MarketConfig(
                market_type=MarketType.A_SHARE,
                broker_type=BrokerType.EASTMONEY,
                currency="CNY",
                enabled=True,
                parameters={
                    'api_key': 'your_eastmoney_key',
                    'security_firm': 'EASTMONEY'
                }
            ),
            MarketType.US: MarketConfig(
                market_type=MarketType.US,
                broker_type=BrokerType.FUTU,
                currency="USD",
                enabled=True,
                parameters={
                    'host': '127.0.0.1',
                    'port': 11111,
                    'security_firm': 'FUTU_US'
                }
            ),
            MarketType.CRYPTO: MarketConfig(
                market_type=MarketType.CRYPTO,
                broker_type=BrokerType.BINANCE,
                currency="USDT",
                enabled=True,  # 默认禁用加密货币
                parameters={
                    'api_key': 'your_binance_key',
                    'secret_key': 'your_binance_secret',
                    'testnet': True  # 默认使用测试网络
                }
            )
        }

    def _set_safe_default_market(self):
        """设置安全的默认市场（第一个启用的市场）"""
        enabled_markets = self.get_enabled_markets()
        if enabled_markets:
            self.default_market = enabled_markets[0]
            logger.info(f"默认市场已设置为: {self.default_market.value}")
        else:
            logger.warning("没有可用的启用市场")

    def enable_market(self, market_type: MarketType):
        """
        启用指定市场

        Args:
            market_type: 要启用的市场类型
        """
        if market_type in self.markets:
            self.markets[market_type].enabled = True
            logger.info(f"已启用市场: {market_type.value}")
        else:
            logger.warning(f"市场未配置: {market_type.value}")

    def disable_market(self, market_type: MarketType):
        """
        禁用指定市场

        Args:
            market_type: 要禁用的市场类型
        """
        if market_type in self.markets:
            self.markets[market_type].enabled = False

            # 如果禁用的是默认市场，重新设置默认市场
            if market_type == self.default_market:
                self._set_safe_default_market()

            logger.info(f"已禁用市场: {market_type.value}")

    def get_enabled_markets(self) -> List[MarketType]:
        """
        获取所有已启用的市场类型列表

        Returns:
            List[MarketType]: 已启用的市场类型列表
        """
        return [market_type for market_type, config in self.markets.items()
                if config.enabled]

    def get_available_markets(self) -> List[MarketType]:
        """
        获取所有可用的市场类型列表（包括配置但未启用的）

        Returns:
            List[MarketType]: 所有已配置的市场类型列表
        """
        return list(self.markets.keys())

    def set_default_market(self, market_type: MarketType):
        """
        设置默认市场

        Args:
            market_type: 要设置为默认的市场类型

        Raises:
            ValueError: 当市场未配置或未启用时
        """
        if market_type not in self.markets:
            raise ValueError(f"市场未配置: {market_type.value}")

        if not self.markets[market_type].enabled:
            raise ValueError(f"市场未启用: {market_type.value}")

        self.default_market = market_type
        logger.info(f"默认市场已设置为: {market_type.value}")

    def get_market_config(self, market_type: MarketType) -> MarketConfig:
        """
        获取指定市场的配置

        Args:
            market_type: 市场类型

        Returns:
            MarketConfig: 市场配置对象

        Raises:
            KeyError: 当市场未配置时
        """
        if market_type not in self.markets:
            raise KeyError(f"市场未配置: {market_type.value}")

        return self.markets[market_type]

    def get_current_market_config(self) -> MarketConfig:
        """
        获取当前默认市场的配置

        Returns:
            MarketConfig: 当前默认市场的配置
        """
        return self.get_market_config(self.default_market)

    def add_market(self, config: MarketConfig):
        """
        添加新的市场配置

        Args:
            config: 市场配置对象
        """
        self.markets[config.market_type] = config
        logger.info(f"已添加市场配置: {config.market_type.value}")

    def remove_market(self, market_type: MarketType):
        """
        移除市场配置

        Args:
            market_type: 要移除的市场类型
        """
        if market_type in self.markets:
            del self.markets[market_type]

            # 如果移除的是默认市场，重新设置默认市场
            if market_type == self.default_market:
                self._set_safe_default_market()

            logger.info(f"已移除市场: {market_type.value}")

    def get_open_markets(self) -> List[MarketType]:
        """
        获取当前正在交易的市场列表

        Returns:
            List[MarketType]: 正在交易的市场列表
        """
        open_markets = []
        for market_type, config in self.markets.items():
            if config.enabled and config.is_market_open():
                open_markets.append(market_type)
        return open_markets

    def validate_all_markets(self) -> Dict[MarketType, List[str]]:
        """
        验证所有市场的配置有效性

        Returns:
            Dict[MarketType, List[str]]: 每个市场的错误信息字典
        """
        errors = {}
        for market_type, config in self.markets.items():
            market_errors = config.validate_config()
            if market_errors:
                errors[market_type] = market_errors
        return errors

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'default_market': self.default_market.value,
            'auto_switch': self.auto_switch,
            'markets': {
                market_type.value: config.to_dict()
                for market_type, config in self.markets.items()
            }
        }


# 市场配置工厂函数
def create_market_config(market_type: MarketType, **kwargs) -> MarketConfig:
    """
    创建市场配置实例

    Args:
        market_type: 市场类型
        **kwargs: 其他配置参数

    Returns:
        MarketConfig: 市场配置实例
    """
    return MarketConfig(market_type=market_type, **kwargs)


# 使用示例和测试代码
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO)

    # 创建多市场配置管理器
    multi_market = MultiMarketConfig()

    # 演示功能
    print("=== 多市场配置演示 ===")
    print(f"默认市场: {multi_market.default_market.value}")

    enabled_markets = multi_market.get_enabled_markets()
    print(f"启用的市场: {[m.value for m in enabled_markets]}")

    open_markets = multi_market.get_open_markets()
    print(f"正在交易的市场: {[m.value for m in open_markets]}")

    # 显示所有市场状态
    print("\n市场状态详情:")
    for market_type in multi_market.get_available_markets():
        config = multi_market.get_market_config(market_type)
        status = "✅ 启用" if config.enabled else "❌ 禁用"
        trading = "🟢 交易中" if config.is_market_open() else "🔴 休市"
        print(f"  {status} {trading} {market_type.value} - {config.broker_type.value}")