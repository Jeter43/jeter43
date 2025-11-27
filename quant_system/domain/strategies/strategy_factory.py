# quant_system/domain/strategies/strategy_factory.py
"""
策略工厂模块 - 精简版（在保证现有功能不变的前提下清理冗余）
"""

import sys
import os
from typing import Dict, List, Any, Optional, Type
from datetime import datetime
from dataclasses import dataclass
import inspect
import traceback

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from .base import BaseStrategy, StrategyType, StrategyConfig, SelectionStrategy
from quant_system.core.config import SelectionStrategyConfig


@dataclass
class StrategyRegistry:
    """策略注册信息"""
    strategy_class: Type[BaseStrategy]
    strategy_type: StrategyType
    description: str = ""
    enabled_by_default: bool = True


class StrategyFactory:
    """
    策略工厂 - 精简版
    """

    def __init__(self, broker=None, config=None, stock_pool_manager=None):
        """
        初始化策略工厂
        """
        self.broker = broker
        self.config = config
        self.stock_pool_manager = stock_pool_manager
        self.logger = get_logger(__name__)

        # 策略实例缓存
        self.strategy_instances: Dict[str, BaseStrategy] = {}

        # 策略注册表
        self._strategy_registry: Dict[str, StrategyRegistry] = {}

        # 性能统计
        self.performance_stats = {
            'total_creations': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'average_creation_time': 0.0
        }

        # 自动注册所有策略
        self._register_all_strategies()

        # 初始化策略实例
        self._initialize_strategies()

        self.logger.info(f"✅ 策略工厂初始化完成，已注册 {len(self._strategy_registry)} 个策略")
        if self.stock_pool_manager:
            self.logger.info("📊 股票池管理器已集成")

    def _register_all_strategies(self):
        """注册所有策略"""
        try:
            # 注册技术分析选股策略
            from .selection_technical import TechnicalSelectionStrategy
            self._register_strategy(
                "technical_analysis",
                TechnicalSelectionStrategy,
                StrategyType.SELECTION,
                "技术分析选股策略",
                True
            )

            # 注册实时数据选股策略（不使用历史K线）
            from .selection_realtime import RealtimeSelectionStrategy
            self._register_strategy(
                "realtime_monitoring",
                RealtimeSelectionStrategy,
                StrategyType.SELECTION,
                "实时数据选股策略（纯实时，不使用历史K线）",
                True
            )

            # 注册自选股策略
            from .selection_priority import PriorityStocksStrategy
            self._register_strategy(
                "priority_stocks",
                PriorityStocksStrategy,
                StrategyType.SELECTION,
                "自选股策略",
                True
            )

            # 注册混合策略
            from .selection_mixed import MixedStrategy
            self._register_strategy(
                "mixed_strategy",
                MixedStrategy,
                StrategyType.SELECTION,
                "混合选股策略",
                True
            )

            # 注册基础风控策略
            from .risk_basic import BasicRiskStrategy
            self._register_strategy(
                "basic_stop_loss",
                BasicRiskStrategy,
                StrategyType.RISK_MANAGEMENT,
                "基础风控策略",
                True
            )

            # 注册高级风控策略
            from .risk_advanced import AdvancedRiskStrategy
            self._register_strategy(
                "advanced_risk_management",
                AdvancedRiskStrategy,
                StrategyType.RISK_MANAGEMENT,
                "高级风控策略",
                True
            )

            self.logger.debug("所有策略注册完成")

        except ImportError as e:
            self.logger.error(f"策略注册失败: {e}")
            # 在开发环境中继续初始化（宽容模式）
            if self.config and hasattr(self.config, 'environment') and getattr(self.config.environment, 'value', None) == 'development':
                self.logger.warning("开发环境: 继续初始化，部分策略可能不可用")

    def _register_strategy(self, strategy_name: str, strategy_class: Type[BaseStrategy],
                           strategy_type: StrategyType, description: str = "",
                           enabled_by_default: bool = True):
        """
        注册策略类
        """
        self._strategy_registry[strategy_name] = StrategyRegistry(
            strategy_class=strategy_class,
            strategy_type=strategy_type,
            description=description,
            enabled_by_default=enabled_by_default
        )
        self.logger.debug(f"注册策略: {strategy_name}")

    def _initialize_strategies(self):
        """初始化所有策略实例"""
        self.logger.info("🏭 初始化策略实例...")

        initialized_count = 0
        for strategy_name, registry in self._strategy_registry.items():
            try:
                # 检查配置中的启用状态
                strategy_config = self._get_strategy_config(strategy_name, registry)

                if strategy_config.enabled:
                    # 创建策略实例
                    strategy_instance = self._create_strategy_instance(
                        strategy_name, registry, strategy_config
                    )
                    if strategy_instance:
                        self.strategy_instances[strategy_name] = strategy_instance
                        initialized_count += 1
                        self.logger.debug(f"✅ 策略实例化: {strategy_name}")
                    else:
                        self.logger.warning(f"⚠️ 策略实例化为None: {strategy_name}")
                else:
                    self.logger.debug(f"⏸️ 策略被禁用: {strategy_name}")

            except Exception as e:
                self.logger.error(f"❌ 策略初始化失败 {strategy_name}: {e}")
                if self.config and hasattr(self.config, 'environment') and getattr(self.config.environment, 'value', None) == 'development':
                    self.logger.warning(f"开发环境: 跳过策略 {strategy_name}")
                continue

        self.logger.info(f"🎯 策略实例化完成: {initialized_count}/{len(self._strategy_registry)} 个策略")

    def _get_strategy_config(self, strategy_name: str, registry: StrategyRegistry) -> StrategyConfig:
        """
        获取策略配置（优先系统配置，回退默认）
        """
        # 从系统配置更新
        if self.config and hasattr(self.config, 'system'):
            system_config = self.config.system

            # 选股策略配置
            if registry.strategy_type == StrategyType.SELECTION:
                if hasattr(system_config, 'selection_strategies_config'):
                    selection_configs = system_config.selection_strategies_config
                    if strategy_name in selection_configs:
                        strategy_cfg = selection_configs[strategy_name]
                        # 直接使用SelectionStrategyConfig对象，保留max_stocks等属性
                        if isinstance(strategy_cfg, SelectionStrategyConfig):
                            return strategy_cfg
                        else:
                            # 如果不是SelectionStrategyConfig，创建新的
                            # SelectionStrategyConfig已在文件顶部导入，直接使用
                            return SelectionStrategyConfig(
                                enabled=getattr(strategy_cfg, 'enabled', registry.enabled_by_default),
                                weight=getattr(strategy_cfg, 'weight', 1.0),
                                max_stocks=getattr(strategy_cfg, 'max_stocks', 10),
                                min_score=getattr(strategy_cfg, 'min_score', 60.0)
                            )

            # 风控策略配置
            elif registry.strategy_type == StrategyType.RISK_MANAGEMENT:
                if hasattr(system_config, 'risk_strategies_config'):
                    risk_configs = system_config.risk_strategies_config
                    if strategy_name in risk_configs:
                        strategy_cfg = risk_configs[strategy_name]
                        return strategy_cfg

        # 默认配置
        if registry.strategy_type == StrategyType.SELECTION:
            # SelectionStrategyConfig已在文件顶部导入，直接使用
            return SelectionStrategyConfig(
                enabled=registry.enabled_by_default,
                weight=1.0,
                max_stocks=10,
                min_score=60.0
            )
        else:
            return StrategyConfig(
                enabled=registry.enabled_by_default,
                weight=1.0,
                parameters={}
            )

    def _create_strategy_instance(self, strategy_name: str, registry: StrategyRegistry,
                                  config: StrategyConfig) -> Optional[BaseStrategy]:
        """
        创建策略实例
        """
        start_time = datetime.now()

        try:
            # 获取策略类
            strategy_class = registry.strategy_class

            # 分析策略类的初始化参数
            sig = inspect.signature(strategy_class.__init__)
            params = [p for p in sig.parameters.keys() if p != 'self']

            # 构建初始化参数
            init_kwargs = {}

            # 判断是否为 SelectionStrategy 子类（使用已导入的 SelectionStrategy）
            is_selection_strategy = False
            try:
                is_selection_strategy = issubclass(strategy_class, SelectionStrategy)
            except TypeError:
                # 如果不是类或无法判断，则根据注册类型回退判断
                is_selection_strategy = (registry.strategy_type == StrategyType.SELECTION)

            if is_selection_strategy:
                init_kwargs = {
                    'name': strategy_name,
                    'config': config,
                    'broker': self.broker
                }
                self.logger.debug(f"🔧 使用选股策略参数模式: {strategy_name}")
            else:
                # 其他策略类型的参数处理（兼容 strategy_config 或 config 命名）
                if 'strategy_config' in params:
                    init_kwargs['strategy_config'] = config
                elif 'config' in params:
                    init_kwargs['config'] = config

                if 'broker' in params:
                    init_kwargs['broker'] = self.broker

            # 传递股票池管理器（如果需要）
            if 'stock_pool_manager' in params and self.stock_pool_manager:
                init_kwargs['stock_pool_manager'] = self.stock_pool_manager

            self.logger.debug(f"创建策略 {strategy_name} 使用参数: {list(init_kwargs.keys())}")

            # 创建策略实例
            instance = strategy_class(**init_kwargs)

            # 更新性能统计
            self._update_creation_stats(start_time)

            self.logger.debug(f"✅ 策略实例创建成功: {strategy_name} -> {type(instance).__name__}")
            return instance

        except Exception as e:
            self.logger.error(f"❌ 策略实例创建失败 {strategy_name}: {e}")
            self.logger.error(f"详细堆栈: {traceback.format_exc()}")
            return None

    def get_selection_strategy(self, strategy_name: str) -> Optional[BaseStrategy]:
        """
        获取选股策略
        """
        try:
            strategy = self._get_strategy_by_type(strategy_name, StrategyType.SELECTION)
            if strategy is None:
                self.logger.warning(f"选股策略获取为None: {strategy_name}")
            return strategy
        except Exception as e:
            self.logger.error(f"获取选股策略失败 {strategy_name}: {e}")
            return None

    def get_risk_strategy(self, strategy_name: str) -> Optional[BaseStrategy]:
        """
        获取风控策略
        """
        try:
            strategy = self._get_strategy_by_type(strategy_name, StrategyType.RISK_MANAGEMENT)
            if strategy is None:
                self.logger.warning(f"风控策略获取为None: {strategy_name}")
            return strategy
        except Exception as e:
            self.logger.error(f"获取风控策略失败 {strategy_name}: {e}")
            return None

    def _get_strategy_by_type(self, strategy_name: str, expected_type: StrategyType) -> Optional[BaseStrategy]:
        """
        按类型获取策略
        """
        try:
            # 检查缓存
            if strategy_name in self.strategy_instances:
                strategy = self.strategy_instances[strategy_name]
                if strategy and strategy.strategy_type == expected_type:
                    self.performance_stats['cache_hits'] += 1
                    return strategy

            # 检查注册表
            if strategy_name not in self._strategy_registry:
                self.logger.error(f"策略不存在: {strategy_name}")
                return None

            registry = self._strategy_registry[strategy_name]
            if registry.strategy_type != expected_type:
                self.logger.error(f"策略类型不匹配: {strategy_name}")
                return None

            # 创建新实例
            self.performance_stats['cache_misses'] += 1
            strategy_config = self._get_strategy_config(strategy_name, registry)

            if not strategy_config.enabled:
                self.logger.warning(f"策略被禁用: {strategy_name}")
                return None

            strategy_instance = self._create_strategy_instance(strategy_name, registry, strategy_config)

            if strategy_instance:
                # 缓存实例
                self.strategy_instances[strategy_name] = strategy_instance
                return strategy_instance
            else:
                self.logger.error(f"策略实例创建失败: {strategy_name}")
                return None

        except Exception as e:
            self.logger.error(f"获取策略失败 {strategy_name}: {e}")
            return None

    def get_all_selection_strategies(self) -> List[BaseStrategy]:
        """
        获取所有选股策略
        """
        selection_strategies = []

        for strategy_name, registry in self._strategy_registry.items():
            if registry.strategy_type == StrategyType.SELECTION:
                try:
                    strategy = self.get_selection_strategy(strategy_name)
                    if strategy:
                        selection_strategies.append(strategy)
                    else:
                        self.logger.warning(f"选股策略获取为None: {strategy_name}")
                except Exception as e:
                    self.logger.error(f"获取选股策略失败 {strategy_name}: {e}")
                    continue

        return selection_strategies

    def get_all_risk_strategies(self) -> List[BaseStrategy]:
        """
        获取所有风控策略
        """
        risk_strategies = []

        for strategy_name, registry in self._strategy_registry.items():
            if registry.strategy_type == StrategyType.RISK_MANAGEMENT:
                try:
                    strategy = self.get_risk_strategy(strategy_name)
                    if strategy:
                        risk_strategies.append(strategy)
                    else:
                        self.logger.warning(f"风控策略获取为None: {strategy_name}")
                except Exception as e:
                    self.logger.error(f"获取风控策略失败 {strategy_name}: {e}")
                    continue

        return risk_strategies

    def list_available_strategies(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        列出所有可用策略
        """
        strategies_info = {
            'selection': [],
            'risk_management': []
        }

        for strategy_name, registry in self._strategy_registry.items():
            strategy_info = {
                'name': strategy_name,
                'type': registry.strategy_type.value,
                'description': registry.description,
                'enabled_by_default': registry.enabled_by_default,
                'is_instantiated': strategy_name in self.strategy_instances and self.strategy_instances[
                    strategy_name] is not None
            }

            # 按类型分组
            if registry.strategy_type == StrategyType.SELECTION:
                strategies_info['selection'].append(strategy_info)
            elif registry.strategy_type == StrategyType.RISK_MANAGEMENT:
                strategies_info['risk_management'].append(strategy_info)

        return strategies_info

    def _update_creation_stats(self, start_time: datetime):
        """更新创建统计"""
        creation_time = (datetime.now() - start_time).total_seconds()

        self.performance_stats['total_creations'] += 1

        # 更新平均创建时间
        total_creations = self.performance_stats['total_creations']
        current_avg = self.performance_stats['average_creation_time']
        new_avg = (current_avg * (total_creations - 1) + creation_time) / total_creations
        self.performance_stats['average_creation_time'] = new_avg

    def __str__(self) -> str:
        return f"StrategyFactory(strategies={len(self.strategy_instances)}/{len(self._strategy_registry)})"


# 导出类
__all__ = ['StrategyFactory']
