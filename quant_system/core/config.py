"""
配置管理模块 (quant_system/core/config.py)

功能概述：
    统一管理量化交易系统的所有配置项，支持多环境、多市场、多策略的灵活配置。
    采用分层配置设计，确保配置的隔离性、安全性和可维护性。

核心特性：
    1. 环境隔离：支持开发、测试、生产环境独立配置
    2. 多市场支持：统一接口管理不同市场的交易配置
    3. 策略管理：动态启用/禁用交易策略，支持权重配置
    4. 类型安全：使用枚举和数据类型确保配置正确性
    5. 热重载：支持运行时配置更新（部分配置）

设计模式：
    - 组合模式：分层配置结构
    - 策略模式：可插拔的策略配置
    - 单例模式：全局配置管理器（在应用层实现）

版本历史：
    v1.0 - 基础配置管理
    v2.0 - 增加多市场支持和环境隔离
    v3.0 - 增强类型安全和配置验证
"""
from __future__ import annotations
import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, ClassVar
from enum import Enum
import logging
from pathlib import Path


# 导入市场配置
from .market_config import MultiMarketConfig, MarketType, BrokerType, MarketConfig
# 导入配置类
from quant_system.core.trading_config import TradingConfig, BacktestConfig, BrokerConfig, TradingEnvironment



# 配置模块的日志器
logger = logging.getLogger(__name__)


class Environment(Enum):
    """系统运行环境枚举"""
    DEVELOPMENT = "development"  # 开发环境 - 用于本地开发和测试
    TESTING = "testing"  # 测试环境 - 用于自动化测试
    STAGING = "staging"  # 预生产环境 - 用于最终测试
    PRODUCTION = "production"  # 生产环境 - 实盘交易


class SystemMode(Enum):
    """系统工作模式枚举"""
    STOCK_SELECTION_ONLY = "stock_selection_only"  # 仅选股模式 - 只运行选股策略
    RISK_MANAGEMENT_ONLY = "risk_management_only"  # 仅风控模式 - 只运行风控策略
    FULL_AUTOMATION = "full_automation"  # 全自动模式 - 选股+风控+交易
    BACKTEST = "backtest"  # 回测模式 - 历史数据测试
    DEBUG = "debug"  # 添加DEBUG模式


class SelectionStrategy(Enum):
    """选股策略类型枚举"""
    TECHNICAL_ANALYSIS = "technical_analysis"  # 技术分析选股
    PRIORITY_STOCKS = "priority_stocks"  # 优先股选股
    MIXED_STRATEGY = "mixed_strategy"  # 混合策略选股


class RiskStrategy(Enum):
    """风控策略类型枚举"""
    BASIC_STOP_LOSS = "basic_stop_loss"  # 基础止损策略
    ADVANCED_RISK_MANAGEMENT = "advanced_risk_management"  # 高级风控策略


@dataclass
class StrategyConfig:
    """
    策略配置基类

    所有策略配置的基类，定义了策略的通用属性和方法。
    采用组合模式，支持策略的灵活组合和权重配置。

    属性:
        enabled: 策略是否启用
        weight: 策略权重 (0.0-1.0)，用于多策略组合时的权重计算
    """
    enabled: bool = True
    weight: float = field(default=1.0, metadata={"min": 0.0, "max": 1.0})  # 策略权重

    def validate(self) -> List[str]:
        """
        验证配置有效性

        Returns:
            List[str]: 错误信息列表，空列表表示验证通过
        """
        errors = []
        if not 0.0 <= self.weight <= 1.0:
            errors.append(f"策略权重必须在 0.0 到 1.0 之间，当前值: {self.weight}")
        return errors


@dataclass
class SelectionStrategyConfig(StrategyConfig):
    """
    选股策略配置

    选股策略的特定配置，包括选股数量限制和评分阈值。

    属性:
        max_stocks: 最大选股数量，防止过度分散投资
        min_score: 最小评分阈值，低于此分数的股票不会被选中
    """
    max_stocks: int = field(default=10, metadata={"min": 1, "max": 100})
    min_score: float = field(default=60.0, metadata={"min": 0.0, "max": 100.0})

    def validate(self) -> List[str]:
        """
        验证选股策略配置

        Returns:
            List[str]: 错误信息列表
        """
        errors = super().validate()
        if self.max_stocks < 1:
            errors.append(f"最大选股数量必须大于0，当前值: {self.max_stocks}")
        if not 0.0 <= self.min_score <= 100.0:
            errors.append(f"最小评分必须在 0.0 到 100.0 之间，当前值: {self.min_score}")
        return errors


@dataclass
class RiskStrategyConfig(StrategyConfig):
    """
    风控策略配置

    风控策略的特定配置，包括风险阈值和自动执行设置。

    属性:
        risk_threshold: 风险阈值 (0.0-1.0)，超过此阈值触发风控
        auto_execute: 是否自动执行风控动作，True时系统自动处理，False时仅告警
    """
    risk_threshold: float = field(default=0.7, metadata={"min": 0.0, "max": 1.0})
    auto_execute: bool = False  # 是否自动执行风控动作

    def validate(self) -> List[str]:
        """
        验证风控策略配置

        Returns:
            List[str]: 错误信息列表
        """
        errors = super().validate()
        if not 0.0 <= self.risk_threshold <= 1.0:
            errors.append(f"风险阈值必须在 0.0 到 1.0 之间，当前值: {self.risk_threshold}")
        return errors


@dataclass
class SystemConfig:
    """
    系统运行配置

    管理系统运行模式、策略配置、执行频率等核心参数。
    支持动态启用/禁用策略，灵活调整系统行为。

    属性:
        mode: 系统运行模式
        allow_non_trading_hours: 是否允许在非交易时间运行（用于数据准备等）
        selection_strategies_config: 选股策略配置字典
        risk_strategies_config: 风控策略配置字典
        selection_interval_minutes: 选股策略执行间隔（分钟）
        risk_check_interval_seconds: 风控检查间隔（秒）
        trading_check_interval_seconds: 交易检查间隔（秒）
        monitored_stocks: 监控股票列表
    """
    # 系统运行模式
    mode: SystemMode = SystemMode.FULL_AUTOMATION
    allow_non_trading_hours: bool = True  # 允许非交易时间运行

    # 策略配置字典 - 使用field确保每个实例有独立的字典
    selection_strategies_config: Dict[str, SelectionStrategyConfig] = field(default_factory=lambda: {
        "technical_analysis": SelectionStrategyConfig(
            enabled=True,
            weight=1.0,
            max_stocks=10,
            min_score=60.0
        ),
        "realtime_monitoring": SelectionStrategyConfig(
            enabled=False,
            weight=1.0,
            max_stocks=50,
            min_score=50.0
        ),
        "priority_stocks": SelectionStrategyConfig(
            enabled=True,
            weight=1.0,
            max_stocks=8,
            min_score=70.0
        ),
        "mixed_strategy": SelectionStrategyConfig(
            enabled=True,
            weight=1.0,
            max_stocks=12,
            min_score=65.0
        )
    })

    risk_strategies_config: Dict[str, RiskStrategyConfig] = field(default_factory=lambda: {
        "basic_stop_loss": RiskStrategyConfig(
            enabled=True,
            weight=1.0,
            risk_threshold=0.8,
            auto_execute=True
        ),
        "advanced_risk_management": RiskStrategyConfig(
            enabled=True,
            weight=1.0,
            risk_threshold=0.7,
            auto_execute=False
        )
    })

    # 执行频率配置
    selection_interval_minutes: int = field(default=120, metadata={"min": 1})  # 选股间隔
    risk_check_interval_seconds: int = field(default=60, metadata={"min": 1})  # 风控检查间隔
    trading_check_interval_seconds: int = field(default=10, metadata={"min": 1})  # 交易检查间隔

    # 监控配置
    monitored_stocks: List[str] = field(default_factory=list)
    
    # 日志配置
    log_level: str = field(default="INFO", metadata={"choices": ["DEBUG", "INFO", "WARNING", "ERROR"]})  # 日志级别
    debug_mode: bool = field(default=False)  # 是否启用详细调试日志

    @property
    def selection_strategies(self) -> List[str]:
        """返回启用的选股策略名称（向后兼容属性）"""
        return [name for name, cfg in self.selection_strategies_config.items() if getattr(cfg, 'enabled', False)]

    @property
    def risk_strategies(self) -> List[str]:
        """返回启用的风控策略名称（向后兼容属性）"""
        return [name for name, cfg in self.risk_strategies_config.items() if getattr(cfg, 'enabled', False)]

    def get_enabled_selection_strategies(self) -> List[str]:
        """
        获取启用的选股策略名称列表

        Returns:
            List[str]: 启用的选股策略名称列表
        """
        return [name for name, config in self.selection_strategies_config.items()
                if config.enabled]

    def get_enabled_risk_strategies(self) -> List[str]:
        """
        获取启用的风控策略名称列表

        Returns:
            List[str]: 启用的风控策略名称列表
        """
        return [name for name, config in self.risk_strategies_config.items()
                if config.enabled]

    def enable_strategy(self, strategy_type: str, strategy_name: str, enabled: bool = True):
        """
        启用/禁用指定策略

        Args:
            strategy_type: 策略类型 ('selection' 或 'risk')
            strategy_name: 策略名称
            enabled: 是否启用
        """
        config_dict = (self.selection_strategies_config if strategy_type == "selection"
                       else self.risk_strategies_config if strategy_type == "risk"
        else None)

        if config_dict and strategy_name in config_dict:
            config_dict[strategy_name].enabled = enabled
            action = "启用" if enabled else "禁用"
            logger.info(f"{action} {strategy_type} 策略: {strategy_name}")
        else:
            logger.warning(f"策略不存在: {strategy_type}.{strategy_name}")

    def set_strategy_weight(self, strategy_type: str, strategy_name: str, weight: float):
        """
        设置策略权重

        Args:
            strategy_type: 策略类型 ('selection' 或 'risk')
            strategy_name: 策略名称
            weight: 策略权重 (0.0-1.0)
        """
        config = self._get_strategy_config(strategy_type, strategy_name)
        if config:
            if 0.0 <= weight <= 1.0:
                config.weight = weight
                logger.info(f"设置 {strategy_type}.{strategy_name} 权重为: {weight}")
            else:
                logger.error(f"权重值必须在 0.0 到 1.0 之间: {weight}")

    def _get_strategy_config(self, strategy_type: str, strategy_name: str) -> Optional[StrategyConfig]:
        """内部方法：获取策略配置对象"""
        if strategy_type == "selection":
            return self.selection_strategies_config.get(strategy_name)
        elif strategy_type == "risk":
            return self.risk_strategies_config.get(strategy_name)
        return None

    def validate(self) -> List[str]:
        """
        验证系统配置有效性

        Returns:
            List[str]: 错误信息列表
        """
        errors = []

        # 验证频率配置
        if self.selection_interval_minutes < 1:
            errors.append("选股间隔必须大于0分钟")
        if self.risk_check_interval_seconds < 1:
            errors.append("风控检查间隔必须大于0秒")
        if self.trading_check_interval_seconds < 1:
            errors.append("交易检查间隔必须大于0秒")

        # 验证策略配置
        for name, config in self.selection_strategies_config.items():
            if config.enabled:
                errors.extend([f"选股策略 {name}: {error}"
                               for error in config.validate()])

        for name, config in self.risk_strategies_config.items():
            if config.enabled:
                errors.extend([f"风控策略 {name}: {error}"
                               for error in config.validate()])

        return errors


@dataclass
class ConfigManager:
    """
    配置管理器 - 多环境多市场优化版本

    核心功能：
        1. 统一管理所有系统配置
        2. 支持多环境配置隔离
        3. 支持多市场动态切换
        4. 提供配置验证和安全性检查
        5. 支持配置持久化和热重载

    使用示例：
        config = ConfigManager(environment=Environment.DEVELOPMENT)
        config.switch_market(MarketType.HK)
        enabled_strategies = config.get_mode_specific_strategies()
    """

    # 类常量
    SUPPORTED_ENVIRONMENTS: ClassVar[List[Environment]] = [
        Environment.DEVELOPMENT,
        Environment.TESTING,
        Environment.STAGING,
        Environment.PRODUCTION
    ]

    # 实例属性
    environment: Environment = Environment.DEVELOPMENT  # 当前环境

    # 核心配置组件
    trading: TradingConfig = field(default_factory=TradingConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    multi_market: MultiMarketConfig = field(default_factory=MultiMarketConfig)

    # 当前选中的市场
    current_market: MarketType = MarketType.HK

    def __post_init__(self):
        """
        初始化后处理

        负责：
        1. 环境变量加载
        2. 配置验证
        3. 环境特定配置设置
        """
        try:
            self._load_environment_config()
            self._validate_config()
            logger.info(f"配置管理器初始化完成 - 环境: {self.environment.value}")
        except Exception as e:
            logger.error(f"配置管理器初始化失败: {e}")
            # 不重新抛出异常，而是设置默认配置
            self._setup_default_config()
            logger.info("已恢复默认配置")

    def _setup_default_config(self):
        """设置默认配置作为备选方案"""
        # 确保多市场配置有基本设置
        if not hasattr(self.multi_market, 'markets') or not self.multi_market.markets:
            # 创建默认市场配置
            self.multi_market = MultiMarketConfig()

        # 确保当前市场有效
        if self.current_market not in self.multi_market.markets:
            self.current_market = list(self.multi_market.markets.keys())[
                0] if self.multi_market.markets else MarketType.HK

    def _load_environment_config(self):
        """加载环境特定配置"""
        try:
            env_prefix = f"TRADING_SYSTEM_{self.environment.value.upper()}_"

            # 从环境变量加载配置示例
            debug_env = os.getenv(f"{env_prefix}DEBUG")
            if debug_env:
                self.system.allow_non_trading_hours = debug_env.lower() in ['true', '1', 'yes']

            logger.debug(f"已加载 {self.environment.value} 环境配置")
        except Exception as e:
            logger.warning(f"加载环境配置失败: {e}，使用默认值")

    def _validate_config(self):
        """验证所有配置的有效性 - 修复版本"""
        errors = []

        # 验证环境
        if self.environment not in self.SUPPORTED_ENVIRONMENTS:
            errors.append(f"不支持的环境: {self.environment}")

        # 验证多市场配置
        if not hasattr(self.multi_market, 'markets'):
            errors.append("多市场配置缺失")
        elif not self.multi_market.markets:
            errors.append("没有配置任何市场")
        else:
            # 验证当前市场是否在可用市场中
            if self.current_market not in self.multi_market.markets:
                available_markets = list(self.multi_market.markets.keys())
                errors.append(f"当前市场 {self.current_market.value} 不在可用市场中: {[m.value for m in available_markets]}")

        # 验证系统配置
        try:
            system_errors = self.system.validate()
            errors.extend(system_errors)
        except Exception as e:
            errors.append(f"系统配置验证失败: {e}")

        if errors:
            error_msg = "配置验证失败:\n" + "\n".join(f"  - {error}" for error in errors)
            logger.warning(error_msg)
            # 改为警告而不是抛出异常，让系统可以继续运行
            # 在实际生产环境中，可能需要根据严重程度决定是否抛出异常

    def switch_market(self, market_type: MarketType) -> bool:
        """
        切换交易市场

        Args:
            market_type: 要切换的市场类型

        Returns:
            bool: 切换是否成功

        Raises:
            ValueError: 当市场未配置或未启用时
        """
        try:
            if not hasattr(self.multi_market, 'markets') or market_type not in self.multi_market.markets:
                logger.error(f"市场 {market_type.value} 未配置")
                return False

            market_config = self.multi_market.get_market_config(market_type)
            if not market_config or not getattr(market_config, 'enabled', True):
                logger.error(f"市场 {market_type.value} 未启用")
                return False

            # 执行市场切换
            old_market = self.current_market
            self.current_market = market_type

            logger.info(f"市场切换: {old_market.value} -> {market_type.value}")
            if market_config:
                logger.info(f"  券商: {getattr(market_config, 'broker_type', 'Unknown')}")
                logger.info(f"  货币: {getattr(market_config, 'currency', 'Unknown')}")

            return True

        except Exception as e:
            logger.error(f"切换市场失败: {e}")
            return False

    def get_current_market_config(self) -> Optional[MarketConfig]:
        """获取当前市场配置 - 修复版本"""
        try:
            if (hasattr(self.multi_market, 'get_market_config') and
                self.current_market in self.multi_market.markets):
                return self.multi_market.get_market_config(self.current_market)
            return None
        except Exception as e:
            logger.error(f"获取当前市场配置失败: {e}")
            return None

    def list_available_markets(self) -> List[Dict[str, Any]]:
        """列出所有可用市场信息 - 修复版本"""
        available_markets = []

        try:
            if not hasattr(self.multi_market, 'get_enabled_markets'):
                # 返回默认市场
                return [{
                    'market_type': MarketType.HK,
                    'broker_type': BrokerType.FUTU,
                    'currency': 'HKD',
                    'enabled': True,
                    'is_current': True
                }]

            enabled_markets = self.multi_market.get_enabled_markets()
            for market_type in enabled_markets:
                config = self.multi_market.get_market_config(market_type)
                available_markets.append({
                    'market_type': market_type,
                    'broker_type': getattr(config, 'broker_type', BrokerType.FUTU),
                    'currency': getattr(config, 'currency', 'HKD'),
                    'enabled': getattr(config, 'enabled', True),
                    'is_current': market_type == self.current_market
                })
        except Exception as e:
            logger.error(f"获取可用市场列表失败: {e}")
            # 返回默认市场作为备选
            available_markets = [{
                'market_type': MarketType.HK,
                'broker_type': BrokerType.FUTU,
                'currency': 'HKD',
                'enabled': True,
                'is_current': True
            }]

        return available_markets

    def enable_market(self, market_type: MarketType) -> bool:
        """
        启用指定市场

        Args:
            market_type: 要启用的市场类型

        Returns:
            bool: 操作是否成功
        """
        try:
            if market_type in self.multi_market.markets:
                market_config = self.multi_market.get_market_config(market_type)
                if market_config:
                    market_config.enabled = True
                    logger.info(f"已启用市场: {market_type.value}")
                    return True
            return False
        except Exception as e:
            logger.error(f"启用市场失败: {e}")
            return False

    def update_mode(self, new_mode: SystemMode):
        """更新系统运行模式"""
        old_mode = self.system.mode
        self.system.mode = new_mode

        logger.info(f"系统模式变更: {old_mode.value} -> {new_mode.value}")

        # 根据模式调整策略配置
        self._adjust_strategies_for_mode(new_mode)

    def _adjust_strategies_for_mode(self, mode: SystemMode):
        """根据系统模式自动调整策略配置"""
        if mode == SystemMode.STOCK_SELECTION_ONLY:
            # 选股模式下禁用所有风控策略
            for strategy_name in self.system.risk_strategies_config:
                self.system.enable_strategy("risk", strategy_name, False)
        elif mode == SystemMode.RISK_MANAGEMENT_ONLY:
            # 风控模式下禁用所有选股策略
            for strategy_name in self.system.selection_strategies_config:
                self.system.enable_strategy("selection", strategy_name, False)

    def get_available_strategies(self, strategy_type: str) -> List[str]:
        """获取指定类型的所有可用策略名称"""
        if strategy_type == "selection":
            return list(self.system.selection_strategies_config.keys())
        elif strategy_type == "risk":
            return list(self.system.risk_strategies_config.keys())
        else:
            logger.warning(f"未知的策略类型: {strategy_type}")
            return []

    def get_strategy_config(self, strategy_type: str, strategy_name: str) -> Optional[StrategyConfig]:
        """获取指定策略的配置对象"""
        return self.system._get_strategy_config(strategy_type, strategy_name)

    def get_scaling_level_config(self, level: int) -> Optional[Any]:
        """获取分级仓位某个级别的配置"""
        try:
            if hasattr(self.trading, 'get_scaling_level_config'):
                return self.trading.get_scaling_level_config(level)
        except Exception as exc:
            logger.warning(f"获取分级仓位配置失败: {exc}")
        return None

    def enable_selection_strategies(self, strategy_names: List[str]):
        """批量启用选股策略，禁用未指定的策略"""
        for name in self.system.selection_strategies_config:
            self.system.selection_strategies_config[name].enabled = (name in strategy_names)

        enabled_strategies = self.system.get_enabled_selection_strategies()
        logger.info(f"选股策略配置已更新: {enabled_strategies}")

    def enable_risk_strategies(self, strategy_names: List[str]):
        """批量启用风控策略，禁用未指定的策略"""
        for name in self.system.risk_strategies_config:
            self.system.risk_strategies_config[name].enabled = (name in strategy_names)

        enabled_strategies = self.system.get_enabled_risk_strategies()
        logger.info(f"风控策略配置已更新: {enabled_strategies}")

    def set_strategy_parameters(self, strategy_type: str, strategy_name: str, **kwargs):
        """动态设置策略参数"""
        config = self.get_strategy_config(strategy_type, strategy_name)
        if config:
            for key, value in kwargs.items():
                if hasattr(config, key):
                    old_value = getattr(config, key)
                    setattr(config, key, value)
                    logger.info(f"策略参数更新: {strategy_type}.{strategy_name}.{key} = {old_value} -> {value}")
                else:
                    logger.warning(f"策略参数不存在: {strategy_type}.{strategy_name}.{key}")

    def get_mode_specific_strategies(self) -> Dict[str, List[str]]:
        """根据当前系统模式获取应该启用的策略"""
        mode = self.system.mode

        if mode == SystemMode.STOCK_SELECTION_ONLY:
            return {
                'selection': self.system.get_enabled_selection_strategies(),
                'risk': []  # 选股模式下不启用风控
            }
        elif mode == SystemMode.RISK_MANAGEMENT_ONLY:
            return {
                'selection': [],  # 风控模式下不启用选股
                'risk': self.system.get_enabled_risk_strategies()
            }
        else:  # FULL_AUTOMATION 和 BACKTEST
            return {
                'selection': self.system.get_enabled_selection_strategies(),
                'risk': self.system.get_enabled_risk_strategies()
            }

    def save_to_file(self, file_path: str):
        """保存配置到文件"""
        config_dict = self.to_dict()
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存到: {file_path}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            raise

    def load_from_file(self, file_path: str):
        """从文件加载配置"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            self.update_from_dict(config_dict)
            logger.info(f"配置已从文件加载: {file_path}")
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            raise

    def update_from_dict(self, config_dict: Dict[str, Any]):
        """从字典更新配置（支持部分更新）"""
        for section, values in config_dict.items():
            if hasattr(self, section):
                section_obj = getattr(self, section)
                self._update_section_from_dict(section_obj, values)

        logger.info("配置已从字典更新")

    def _update_section_from_dict(self, section_obj: Any, values: Dict[str, Any], section_path: str = ""):
        """递归更新配置节（修复版本）"""
        for key, value in values.items():
            current_path = f"{section_path}.{key}" if section_path else key

            if hasattr(section_obj, key):
                current_value = getattr(section_obj, key)

                # 如果是字典且当前值也是字典，递归更新
                if isinstance(value, dict) and isinstance(current_value, dict):
                    self._update_section_from_dict(current_value, value, current_path)
                else:
                    # 特殊处理：如果更新交易配置的市场相关参数
                    if current_path == "trading.max_position_ratio" and hasattr(section_obj, 'position_config'):
                        section_obj.position_config.max_single_position = value
                    elif current_path == "trading.max_stocks" and hasattr(section_obj, 'position_config'):
                        section_obj.position_config.diversification_min = value
                    else:
                        setattr(section_obj, key, value)
            else:
                logger.warning(f"配置项不存在: {current_path}")

    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典格式（修复版本）"""
        config_dict = {
            'environment': self.environment.value,
            'current_market': self.current_market.value,
            'system': {
                'mode': self.system.mode.value,
                'allow_non_trading_hours': self.system.allow_non_trading_hours,
                'selection_strategies': {
                    name: {
                        'enabled': config.enabled,
                        'weight': config.weight,
                        'min_score': getattr(config, 'min_score', 60.0),
                        'max_stocks': getattr(config, 'max_stocks', 10)
                    } for name, config in self.system.selection_strategies_config.items()
                },
                'risk_strategies': {
                    name: {
                        'enabled': config.enabled,
                        'weight': config.weight,
                        'risk_threshold': getattr(config, 'risk_threshold', 0.7),
                        'auto_execute': getattr(config, 'auto_execute', False)
                    } for name, config in self.system.risk_strategies_config.items()
                },
                'selection_interval_minutes': self.system.selection_interval_minutes,
                'risk_check_interval_seconds': self.system.risk_check_interval_seconds,
                'trading_check_interval_seconds': self.system.trading_check_interval_seconds,
                'monitored_stocks': self.system.monitored_stocks
            }
        }

        # 安全地添加交易配置（如果属性存在）
        if hasattr(self.trading, 'environment'):
            config_dict['trading'] = {
                'environment': self.trading.environment.value,
                'commission_rate': getattr(self.trading, 'commission_rate', 0.0003),
                'slippage': getattr(self.trading, 'slippage', 0.001),
                # 从position_config获取仓位相关配置
                'max_position_ratio': getattr(self.trading.position_config, 'max_single_position', 0.1),
                'max_stocks': getattr(self.trading.position_config, 'diversification_min', 10),
            }

        # 安全地添加回测配置
        if hasattr(self.backtest, 'start_date'):
            config_dict['backtest'] = {
                'start_date': self.backtest.start_date,
                'end_date': self.backtest.end_date,
                'initial_capital': self.backtest.initial_capital,
                'enabled': True  # 如果有回测配置，则认为启用
            }

        # 安全地添加券商配置
        if hasattr(self.broker, 'host'):
            config_dict['broker'] = {
                'name': getattr(self.broker, 'username', 'default_broker'),
                'host': self.broker.host,
                'port': self.broker.port
            }

        return config_dict


# 配置管理器工厂函数
def create_config_manager(environment: Environment = Environment.DEVELOPMENT) -> ConfigManager:
    """
    创建配置管理器实例

    Args:
        environment: 系统运行环境

    Returns:
        ConfigManager: 配置管理器实例
    """
    return ConfigManager(environment=environment)


# 使用示例和测试代码
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO)

    # 创建配置管理器实例
    config = create_config_manager(Environment.DEVELOPMENT)

    # 演示基本功能
    print("=== 配置管理器演示 ===")
    print(f"环境: {config.environment.value}")
    print(f"当前市场: {config.current_market.value}")
    print(f"系统模式: {config.system.mode.value}")

    # 显示可用市场
    markets = config.list_available_markets()
    print(f"\n可用市场: {len(markets)} 个")
    for market in markets:
        status = "✅ 当前" if market['is_current'] else "✅ 可用"
        print(f"  {status} {market['market_type'].value} - {market['broker_type'].value}")

    # 显示启用的策略
    strategies = config.get_mode_specific_strategies()
    print(f"\n启用的策略:")
    print(f"  选股: {strategies['selection']}")
    print(f"  风控: {strategies['risk']}")

    print("\n🎯 配置管理器初始化完成！")