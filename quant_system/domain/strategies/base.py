"""
策略基类模块 (quant_system/domain/strategies/base.py)

功能概述：
    定义量化交易策略的抽象基类和接口规范。
    提供策略模式的基础架构，支持选股策略和风控策略的统一管理。

核心特性：
    1. 抽象接口：定义策略执行的统一接口
    2. 类型安全：明确的策略类型枚举和类型提示
    3. 生命周期管理：策略的启用/禁用状态管理
    4. 扩展性：易于添加新策略类型的架构设计

设计模式：
    - 模板方法模式：定义算法骨架，子类实现具体步骤
    - 策略模式：可互换的算法实现
    - 工厂模式：策略的创建和管理

版本历史：
    v1.0 - 基础策略抽象类
    v2.0 - 增加策略类型枚举和生命周期管理
    v3.0 - 增强类型安全和扩展性
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, ClassVar
from enum import Enum
import logging
from dataclasses import dataclass
from datetime import datetime


class StrategyType(Enum):
    """
    策略类型枚举

    明确区分不同类型的交易策略，便于策略工厂进行分类管理。
    """
    SELECTION = "selection"  # 选股策略 - 负责股票选择和评分
    RISK_MANAGEMENT = "risk_management"  # 风控策略 - 负责风险控制和止损
    TIMING = "timing"  # 择时策略 - 负责市场时机判断
    PORTFOLIO = "portfolio"  # 组合策略 - 负责资产配置和再平衡


@dataclass
class StrategyConfig:
    """策略配置数据类"""
    enabled: bool = True
    weight: float = 1.0
    parameters: Dict[str, Any] = None

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


@dataclass
class ExecutionResult:
    """策略执行结果数据类"""
    success: bool
    data: Dict[str, Any]
    message: str
    execution_time: datetime
    strategy_name: str

    def __post_init__(self):
        if self.execution_time is None:
            self.execution_time = datetime.now()


class BaseStrategy(ABC):
    """
    策略抽象基类

    所有具体策略的基类，定义策略的通用接口和行为。
    采用模板方法模式，确保策略执行的一致性。

    属性:
        name: 策略名称（唯一标识）
        strategy_type: 策略类型
        enabled: 策略启用状态
        config: 策略配置
        logger: 策略专用日志器
        version: 策略版本
    """

    # 类常量
    SUPPORTED_STRATEGY_TYPES: ClassVar[List[StrategyType]] = [
        StrategyType.SELECTION,
        StrategyType.RISK_MANAGEMENT,
        StrategyType.TIMING,
        StrategyType.PORTFOLIO
    ]

    def __init__(self, name: str, strategy_type: StrategyType, config: Optional[StrategyConfig] = None,
                 broker: Optional[Any] = None, stock_pool_manager: Optional[Any] = None):
        """
        初始化策略基类

        Args:
            name: 策略名称（应该唯一）
            strategy_type: 策略类型
            config: 策略配置（可选）

        Raises:
            ValueError: 当策略类型不支持时
        """
        if strategy_type not in self.SUPPORTED_STRATEGY_TYPES:
            raise ValueError(f"不支持的策略类型: {strategy_type}")

        self.name = name
        self.strategy_type = strategy_type
        self.config = config or StrategyConfig()
        self.broker = broker
        self.stock_pool_manager = stock_pool_manager
        self.enabled = self.config.enabled
        self.logger = logging.getLogger(f"strategy.{name}")
        self.version = "1.0.0"
        self._execution_count = 0
        self._last_execution_time: Optional[datetime] = None

        self.logger.debug(f"策略初始化: {name} ({strategy_type.value})")

    @abstractmethod
    def execute(self, data: Dict[str, Any]) -> ExecutionResult:
        """
        执行策略 - 抽象方法

        所有具体策略必须实现此方法，定义策略的核心逻辑。

        Args:
            data: 策略执行所需的数据

        Returns:
            ExecutionResult: 策略执行结果

        Raises:
            StrategyDisabledError: 当策略被禁用时
            StrategyExecutionError: 当策略执行失败时
        """
        pass

    def validate_input(self, data: Dict[str, Any]) -> bool:
        """
        验证输入数据

        Args:
            data: 待验证的数据

        Returns:
            bool: 数据是否有效
        """
        required_fields = self.get_required_input_fields()
        for field in required_fields:
            if field not in data:
                self.logger.error(f"缺少必要字段: {field}")
                return False
        return True

    def get_required_input_fields(self) -> List[str]:
        """
        获取策略需要的输入字段

        Returns:
            List[str]: 必需的输入字段列表
        """
        return []

    def enable(self) -> None:
        """启用策略"""
        if self.enabled:
            self.logger.warning(f"策略 {self.name} 已经启用")
            return

        self.enabled = True
        self.config.enabled = True
        self.logger.info(f"✅ 策略已启用: {self.name}")

    def disable(self) -> None:
        """禁用策略"""
        if not self.enabled:
            self.logger.warning(f"策略 {self.name} 已经禁用")
            return

        self.enabled = False
        self.config.enabled = False
        self.logger.info(f"⏸️ 策略已禁用: {self.name}")

    def update_config(self, new_config: StrategyConfig) -> None:
        """
        更新策略配置

        Args:
            new_config: 新的策略配置
        """
        old_enabled = self.enabled
        self.config = new_config
        self.enabled = new_config.enabled

        if old_enabled != new_config.enabled:
            status = "启用" if new_config.enabled else "禁用"
            self.logger.info(f"🔄 策略状态变更: {self.name} -> {status}")

        self.logger.debug(f"策略配置已更新: {self.name}")

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        获取策略性能指标

        Returns:
            Dict[str, Any]: 性能指标数据
        """
        return {
            'strategy_name': self.name,
            'strategy_type': self.strategy_type.value,
            'enabled': self.enabled,
            'execution_count': self._execution_count,
            'last_execution_time': self._last_execution_time,
            'version': self.version,
            'config': {
                'weight': self.config.weight,
                'parameters': self.config.parameters
            }
        }

    def _record_execution(self) -> None:
        """记录策略执行"""
        self._execution_count += 1
        self._last_execution_time = datetime.now()

    def __str__(self) -> str:
        """字符串表示"""
        return f"Strategy(name={self.name}, type={self.strategy_type.value}, enabled={self.enabled})"

    def __repr__(self) -> str:
        """详细字符串表示"""
        return (f"BaseStrategy(name={self.name}, type={self.strategy_type.value}, "
                f"enabled={self.enabled}, version={self.version})")

    def get_stock_pool(self, pool_id: str = 'default') -> List[str]:
        """
        获取股票池中的股票列表

        Args:
            pool_id: 股票池ID，默认为'default'

        Returns:
            List[str]: 股票代码列表
        """
        if self.stock_pool_manager:
            return self.stock_pool_manager.get_stocks_from_pool(pool_id)
        else:
            self.logger.warning("股票池管理器未初始化，使用默认股票")
            return ['HK.00700', 'HK.00005', 'HK.00941']  # 默认股票

    def get_available_stock_pools(self) -> Dict[str, Any]:
        """
        获取可用的股票池信息

        Returns:
            Dict[str, Any]: 股票池信息字典
        """
        if self.stock_pool_manager:
            return self.stock_pool_manager.list_available_pools()
        else:
            return {}




class SelectionStrategy(BaseStrategy):
    """
    选股策略基类

    专门用于股票选择的策略基类，提供选股相关的通用功能。
    支持全市场扫描和条件筛选。

    属性:
        allow_non_trading_hours: 是否允许在非交易时间运行
        min_universe_size: 最小股票池大小
        max_candidates: 最大候选股票数量
    """

    def __init__(self, name: str, config: Optional[StrategyConfig] = None, broker: Optional[Any] = None, stock_pool_manager: Optional[Any] = None):
        """
        初始化选股策略

        Args:
            name: 策略名称
            config: 策略配置
        """
        super().__init__(name, StrategyType.SELECTION, config, broker, stock_pool_manager)
        self.allow_non_trading_hours = True
        self.min_universe_size = 50
        self.max_candidates = 20

    @abstractmethod
    def select_stocks(self, universe: List[str]) -> List[Dict[str, Any]]:
        """
        从股票池中选股 - 抽象方法

        Args:
            universe: 股票池列表

        Returns:
            List[Dict[str, Any]]: 选中的股票信息列表

        Raises:
            InsufficientUniverseError: 当股票池太小无法有效选股时
        """
        pass

    def execute(self, data: Dict[str, Any]) -> ExecutionResult:
        """
        执行选股策略

        Args:
            data: 包含股票池等数据的字典

        Returns:
            ExecutionResult: 选股结果
        """
        start_time = datetime.now()

        try:
            # 检查策略状态
            if not self.enabled:
                return ExecutionResult(
                    success=False,
                    data={},
                    message=f"策略 {self.name} 已被禁用",
                    execution_time=start_time,
                    strategy_name=self.name
                )

            # 验证输入数据
            if not self.validate_input(data):
                return ExecutionResult(
                    success=False,
                    data={},
                    message="输入数据验证失败",
                    execution_time=start_time,
                    strategy_name=self.name
                )

            # 获取股票池
            universe = data.get('universe', [])
            if len(universe) < self.min_universe_size:
                self.logger.warning(f"股票池太小: {len(universe)} < {self.min_universe_size}")

            # 执行选股
            selected_stocks = self.select_stocks(universe)

            # 记录执行
            self._record_execution()

            # 返回结果
            return ExecutionResult(
                success=True,
                data={
                    'selected_stocks': selected_stocks,
                    'universe_size': len(universe),
                    'selected_count': len(selected_stocks),
                    'selection_ratio': len(selected_stocks) / max(len(universe), 1)
                },
                message=f"成功选中 {len(selected_stocks)} 只股票",
                execution_time=start_time,
                strategy_name=self.name
            )

        except Exception as e:
            self.logger.error(f"选股策略执行失败: {e}")
            return ExecutionResult(
                success=False,
                data={},
                message=f"策略执行异常: {str(e)}",
                execution_time=start_time,
                strategy_name=self.name
            )

    def _should_run_selection(self) -> bool:
        """
        判断是否应该执行选股

        Returns:
            bool: 是否执行选股
        """
        if self.allow_non_trading_hours:
            return True

        # 如果需要检查交易时间，可以在这里实现
        # return self._is_trading_hours()
        return True

    def get_required_input_fields(self) -> List[str]:
        """获取选股策略需要的输入字段"""
        return ['universe']

    def validate_universe(self, universe: List[str]) -> bool:
        """
        验证股票池

        Args:
            universe: 股票池列表

        Returns:
            bool: 股票池是否有效
        """
        if not isinstance(universe, list):
            self.logger.error("股票池必须是列表类型")
            return False

        if len(universe) == 0:
            self.logger.error("股票池不能为空")
            return False

        # 检查股票代码格式（简化验证）
        for stock in universe[:10]:  # 只检查前10个样本
            if not isinstance(stock, str) or len(stock) < 2:
                self.logger.error(f"无效的股票代码格式: {stock}")
                return False

        return True


class RiskStrategy(BaseStrategy):
    """
    风控策略基类

    专门用于风险控制的策略基类，提供风险检查和止损相关的通用功能。
    支持多层次的 risk assessment。

    属性:
        risk_threshold: 风险阈值
        auto_execute: 是否自动执行风控动作
    """

    def __init__(self, name: str, config: Optional[StrategyConfig] = None):
        """
        初始化风控策略

        Args:
            name: 策略名称
            config: 策略配置
        """
        super().__init__(name, StrategyType.RISK_MANAGEMENT, config)
        self.risk_threshold = 0.7
        self.auto_execute = False

    @abstractmethod
    def check_risk(self, portfolio: Any, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        检查风险并返回风控建议 - 抽象方法

        Args:
            portfolio: 投资组合对象
            market_data: 市场数据

        Returns:
            Dict[str, Any]: 风险检查结果
        """
        pass

    @abstractmethod
    def should_stop_loss(self, position: Any, market_data: Dict[str, Any]) -> bool:
        """
        判断是否应该止损 - 抽象方法

        Args:
            position: 持仓对象
            market_data: 市场数据

        Returns:
            bool: 是否应该止损
        """
        pass

    def execute(self, data: Dict[str, Any]) -> ExecutionResult:
        """
        执行风控策略

        Args:
            data: 包含投资组合和市场数据的字典

        Returns:
            ExecutionResult: 风控检查结果
        """
        start_time = datetime.now()

        try:
            # 检查策略状态
            if not self.enabled:
                return ExecutionResult(
                    success=False,
                    data={},
                    message=f"策略 {self.name} 已被禁用",
                    execution_time=start_time,
                    strategy_name=self.name
                )

            # 验证输入数据
            if not self.validate_input(data):
                return ExecutionResult(
                    success=False,
                    data={},
                    message="输入数据验证失败",
                    execution_time=start_time,
                    strategy_name=self.name
                )

            # 执行风险检查
            portfolio = data.get('portfolio')
            market_data = data.get('market_data', {})

            risk_result = self.check_risk(portfolio, market_data)

            # 记录执行
            self._record_execution()

            # 返回结果
            return ExecutionResult(
                success=True,
                data=risk_result,
                message=f"风险检查完成，风险等级: {risk_result.get('risk_level', 'UNKNOWN')}",
                execution_time=start_time,
                strategy_name=self.name
            )

        except Exception as e:
            self.logger.error(f"风控策略执行失败: {e}")
            return ExecutionResult(
                success=False,
                data={},
                message=f"策略执行异常: {str(e)}",
                execution_time=start_time,
                strategy_name=self.name
            )

    def get_required_input_fields(self) -> List[str]:
        """获取风控策略需要的输入字段"""
        return ['portfolio', 'market_data']


# 自定义异常类
class StrategyError(Exception):
    """策略基础异常类"""
    pass


class StrategyDisabledError(StrategyError):
    """策略被禁用异常"""
    pass


class StrategyExecutionError(StrategyError):
    """策略执行异常"""
    pass


class InsufficientUniverseError(StrategyError):
    """股票池不足异常"""
    pass

