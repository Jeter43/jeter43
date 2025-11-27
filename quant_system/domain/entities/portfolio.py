"""
投资组合实体模块
定义投资组合和持仓相关的数据结构和业务逻辑
提供完整的组合管理和风险控制功能
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from decimal import Decimal
import uuid
from datetime import datetime

from quant_system.core.exceptions import DataValidationError
from quant_system.utils.monitoring import performance_monitor
from .order import OrderSide

# 新增导入
try:
    from .position_batch import PositionBatch, PositionBatchManager, PositionBatchStatus
except ImportError:
    # 如果position_batch还不存在，定义空类避免导入错误
    class PositionBatchStatus:
        ACTIVE = "active"


    class PositionBatch:
        pass


    class PositionBatchManager:
        pass


@dataclass
class Position:
    """持仓实体类 - 增强版本，支持批次管理"""

    symbol: str  # 标的代码
    quantity: int  # 持仓数量
    cost_price: float  # 成本价格
    current_price: float = 0.0  # 当前价格
    position_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 持仓唯一标识
    created_time: datetime = field(default_factory=datetime.now)  # 创建时间
    updated_time: datetime = field(default_factory=datetime.now)  # 更新时间

    # 新增字段：支持分级仓位管理
    position_level: int = 1  # 仓位级别: 1=初始, 2=第一次加仓, 3=第二次加仓
    batch_ids: List[str] = field(default_factory=list)  # 关联的批次ID列表

    def __post_init__(self):
        """数据类初始化后处理，用于数据验证"""
        self.symbol = self.symbol.strip().upper()
        self._validate_position()

    def _validate_position(self) -> None:
        """验证持仓数据的有效性"""
        errors = []

        if not self.symbol:
            errors.append("标的代码不能为空")

        if self.quantity < 0:
            errors.append(f"持仓数量不能为负数: {self.quantity}")

        if self.cost_price < 0:
            errors.append(f"成本价格不能为负数: {self.cost_price}")

        if self.current_price < 0:
            errors.append(f"当前价格不能为负数: {self.current_price}")

        if self.position_level not in [1, 2, 3]:
            errors.append(f"仓位级别必须在1-3之间: {self.position_level}")

        if errors:
            raise DataValidationError(
                message="持仓数据验证失败",
                details={'errors': errors, 'position': self.to_dict()}
            )

    @property
    def market_value(self) -> float:
        """持仓市值 = 数量 × 当前价格"""
        return self.quantity * self.current_price

    @property
    def cost_value(self) -> float:
        """持仓成本 = 数量 × 成本价格"""
        return self.quantity * self.cost_price

    @property
    def profit_loss(self) -> float:
        """浮动盈亏 = (当前价格 - 成本价格) × 数量"""
        return (self.current_price - self.cost_price) * self.quantity

    @property
    def profit_loss_ratio(self) -> float:
        """盈亏比例 = (当前价格 - 成本价格) / 成本价格"""
        if self.cost_price > 0 and self.cost_value > 0:
            return (self.current_price - self.cost_price) / self.cost_price
        return 0.0

    @property
    def is_profitable(self) -> bool:
        """是否盈利"""
        return self.profit_loss > 0

    @property
    def weight_in_portfolio(self, total_assets: float) -> float:
        """在投资组合中的权重"""
        if total_assets > 0:
            return self.market_value / total_assets
        return 0.0

    def update_price(self, new_price: float) -> None:
        """更新当前价格"""
        if new_price < 0:
            raise DataValidationError(f"价格不能为负数: {new_price}")

        self.current_price = new_price
        self.updated_time = datetime.now()

    def add_quantity(self, additional_quantity: int, additional_cost: float, new_level: int = None) -> None:
        """
        增加持仓数量（加仓操作）- 增强版本

        Args:
            additional_quantity: 增加的数量
            additional_cost: 增加的成本
            new_level: 新的仓位级别
        """
        if additional_quantity <= 0:
            raise DataValidationError(f"增加数量必须大于0: {additional_quantity}")

        if additional_cost <= 0:
            raise DataValidationError(f"增加成本必须大于0: {additional_cost}")

        # 计算新的平均成本
        total_quantity = self.quantity + additional_quantity
        total_cost = self.cost_value + additional_cost

        self.cost_price = total_cost / total_quantity
        self.quantity = total_quantity

        # 更新仓位级别
        if new_level and new_level > self.position_level:
            self.position_level = new_level

        self.updated_time = datetime.now()

    def reduce_quantity(self, reduce_quantity: int) -> float:
        """减少持仓数量（减仓操作）"""
        if reduce_quantity <= 0:
            raise DataValidationError(f"减少数量必须大于0: {reduce_quantity}")

        if reduce_quantity > self.quantity:
            raise DataValidationError(
                f"减少数量超过持仓数量: {reduce_quantity} > {self.quantity}"
            )

        # 计算实现的盈亏
        realized_pnl = (self.current_price - self.cost_price) * reduce_quantity

        # 更新持仓
        self.quantity -= reduce_quantity
        self.updated_time = datetime.now()

        return realized_pnl

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式 - 增强版本"""
        base_dict = {
            'position_id': self.position_id,
            'symbol': self.symbol,
            'quantity': self.quantity,
            'cost_price': self.cost_price,
            'current_price': self.current_price,
            'market_value': self.market_value,
            'cost_value': self.cost_value,
            'profit_loss': self.profit_loss,
            'profit_loss_ratio': self.profit_loss_ratio,
            'is_profitable': self.is_profitable,
            'position_level': self.position_level,
            'batch_ids': self.batch_ids,
            'created_time': self.created_time.isoformat(),
            'updated_time': self.updated_time.isoformat()
        }
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        """从字典创建持仓实例 - 增强版本"""
        created_time = datetime.fromisoformat(data['created_time']) if isinstance(data['created_time'], str) else data[
            'created_time']
        updated_time = datetime.fromisoformat(data['updated_time']) if isinstance(data['updated_time'], str) else data[
            'updated_time']

        return cls(
            symbol=data['symbol'],
            quantity=data['quantity'],
            cost_price=data['cost_price'],
            current_price=data.get('current_price', 0.0),
            position_id=data.get('position_id', str(uuid.uuid4())),
            created_time=created_time,
            updated_time=updated_time,
            position_level=data.get('position_level', 1),
            batch_ids=data.get('batch_ids', [])
        )


@dataclass
class Portfolio:
    """
    投资组合实体类 - 增强版本
    支持分级仓位管理和批次跟踪
    """

    account_id: str  # 账户ID
    total_assets: float = 0.0  # 总资产
    cash: float = 0.0  # 现金
    available_cash: float = 0.0  # 可用现金
    initial_capital: float = 0.0  # 初始资金
    positions: Dict[str, Position] = field(default_factory=dict)  # 持仓字典
    portfolio_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 组合ID
    created_time: datetime = field(default_factory=datetime.now)  # 创建时间
    updated_time: datetime = field(default_factory=datetime.now)  # 更新时间

    # 风险控制参数
    max_position_weight: float = 0.20  # 单标的最大权重 (20%)
    max_initial_weight: float = 0.10  # 首次建仓最大权重 (10%)
    stop_loss_ratio: float = 0.10  # 止损比例 (10%)

    # 新增：分级仓位管理
    position_batches: Dict[str, List[PositionBatch]] = field(default_factory=dict)  # 仓位批次管理
    batch_manager: PositionBatchManager = field(default_factory=PositionBatchManager)  # 批次管理器

    def __post_init__(self):
        """数据类初始化后处理"""
        self._validate_portfolio()

    def _validate_portfolio(self) -> None:
        """验证投资组合数据的有效性"""
        errors = []

        if not self.account_id:
            errors.append("账户ID不能为空")

        if self.total_assets < 0:
            errors.append(f"总资产不能为负数: {self.total_assets}")

        if self.cash < 0:
            errors.append(f"现金不能为负数: {self.cash}")

        if self.available_cash < 0:
            errors.append(f"可用现金不能为负数: {self.available_cash}")

        if self.available_cash > self.cash:
            errors.append(f"可用现金不能超过总现金: {self.available_cash} > {self.cash}")

        if self.max_position_weight <= 0 or self.max_position_weight > 1:
            errors.append(f"最大仓位权重必须在0-1之间: {self.max_position_weight}")

        if errors:
            raise DataValidationError(
                message="投资组合数据验证失败",
                details={'errors': errors, 'portfolio': self.to_dict()}
            )

    @property
    def market_value(self) -> float:
        """持仓总市值"""
        return sum(position.market_value for position in self.positions.values())

    @property
    def total_value(self) -> float:
        """总价值 = 现金 + 持仓市值"""
        return self.cash + self.market_value

    @property
    def unrealized_pnl(self) -> float:
        """总浮动盈亏"""
        return sum(position.profit_loss for position in self.positions.values())

    @property
    def total_return(self) -> float:
        """总收益率"""
        if self.initial_capital > 0:
            return (self.total_value - self.initial_capital) / self.initial_capital
        return 0.0

    @property
    def position_count(self) -> int:
        """持仓标的数量"""
        return len([p for p in self.positions.values() if p.quantity > 0])

    # 新增方法：分级仓位管理
    def get_position_level(self, symbol: str) -> int:
        """
        获取指定股票的仓位级别

        Args:
            symbol: 股票代码

        Returns:
            int: 仓位级别 (0=无持仓, 1=初始, 2=第一次加仓, 3=第二次加仓)
        """
        symbol = symbol.strip().upper()
        if symbol in self.positions:
            return self.positions[symbol].position_level
        return 0

    def get_active_batches(self, symbol: str) -> List[PositionBatch]:
        """
        获取指定股票的所有活跃批次

        Args:
            symbol: 股票代码

        Returns:
            List[PositionBatch]: 活跃批次列表
        """
        symbol = symbol.strip().upper()
        if hasattr(self.batch_manager, 'get_active_batches_by_symbol'):
            return self.batch_manager.get_active_batches_by_symbol(symbol)
        return []

    def add_position_batch(self, batch: PositionBatch) -> None:
        """
        添加仓位批次

        Args:
            batch: 仓位批次实例
        """
        symbol = batch.symbol.strip().upper()

        # 添加到批次管理器
        if hasattr(self.batch_manager, 'add_batch'):
            self.batch_manager.add_batch(batch)

        # 更新持仓的批次ID列表
        if symbol in self.positions:
            if batch.batch_id not in self.positions[symbol].batch_ids:
                self.positions[symbol].batch_ids.append(batch.batch_id)

        self.updated_time = datetime.now()

    def calculate_scaling_position_value(self, symbol: str, target_level: int) -> float:
        """
        计算加仓可用的最大金额

        Args:
            symbol: 股票代码
            target_level: 目标仓位级别

        Returns:
            float: 最大加仓金额
        """
        current_level = self.get_position_level(symbol)
        if current_level == 0:
            return 0.0

        # 根据目标级别计算可加仓金额
        scaling_ratios = {
            1: 0.10,  # L1 -> L2: 加仓10%
            2: 0.05  # L2 -> L3: 加仓5%
        }

        if target_level in scaling_ratios:
            max_scaling_value = self.total_assets * scaling_ratios[target_level]
            # 考虑可用资金限制
            return min(max_scaling_value, self.available_cash * 0.8)

        return 0.0

    def update_batch_prices(self, symbol: str, new_price: float) -> None:
        """
        更新指定股票所有批次的价格

        Args:
            symbol: 股票代码
            new_price: 新价格
        """
        symbol = symbol.strip().upper()

        # 更新批次价格
        if hasattr(self.batch_manager, 'update_prices'):
            self.batch_manager.update_prices(symbol, new_price)

        # 更新持仓价格（保持原有逻辑）
        self.update_position_price(symbol, new_price)

    def check_batch_stop_losses(self, symbol: str) -> List[PositionBatch]:
        """
        检查需要止损的批次

        Args:
            symbol: 股票代码

        Returns:
            List[PositionBatch]: 需要止损的批次列表
        """
        symbol = symbol.strip().upper()
        if hasattr(self.batch_manager, 'check_stop_losses'):
            return self.batch_manager.check_stop_losses(symbol)
        return []

    # 保持原有方法不变（向后兼容）
    @performance_monitor("portfolio_update_from_account")
    def update_from_account_info(self, account_info: Dict[str, float]) -> None:
        """从账户信息更新投资组合"""
        required_fields = ['total_assets']
        missing_fields = [field for field in required_fields if field not in account_info]

        if missing_fields:
            raise DataValidationError(
                f"账户信息缺少必要字段: {missing_fields}",
                details={'account_info': account_info}
            )

        self.total_assets = account_info.get('total_assets', 0.0)
        self.cash = account_info.get('cash')
        self.available_cash = (
                account_info.get('available_cash')
                or account_info.get('cash')
                or account_info.get('available_funds')
                or 0.0
        )
        self.updated_time = datetime.now()

        if self.initial_capital == 0 and self.total_assets > 0:
            self.initial_capital = self.total_assets

    @performance_monitor("portfolio_update_position_price")
    def update_position_price(self, symbol: str, new_price: float) -> None:
        """更新持仓价格"""
        symbol = symbol.strip().upper()
        if symbol in self.positions:
            self.positions[symbol].update_price(new_price)
            self.updated_time = datetime.now()

    @performance_monitor("portfolio_batch_update_prices")
    def batch_update_prices(self, price_updates: Dict[str, float]) -> None:
        """批量更新持仓价格 - 增强版本，同时更新批次价格"""
        for symbol, price in price_updates.items():
            self.update_batch_prices(symbol, price)

    @performance_monitor("portfolio_calculate_max_position")
    def calculate_max_position_value(self, symbol: str, is_initial: bool = True) -> float:
        """计算最大可建仓价值"""
        max_weight = self.max_initial_weight if is_initial else self.max_position_weight

        current_position_value = 0.0
        if symbol in self.positions:
            current_position_value = self.positions[symbol].market_value

        max_additional_value = self.total_assets * max_weight - current_position_value

        return max(0, max_additional_value)

    @performance_monitor("portfolio_get_position")
    def get_position(self, symbol: str) -> Optional[Position]:
        """获取指定标的的持仓"""
        symbol = symbol.strip().upper()
        return self.positions.get(symbol)

    def get_position_quantity(self, symbol: str) -> int:
        """获取持仓数量"""
        position = self.get_position(symbol)
        return position.quantity if position else 0

    @performance_monitor("portfolio_add_position")
    def add_position(self, symbol: str, quantity: int, cost_price: float, level: int = 1, batch_id: str = None) -> None:
        """
        添加或更新持仓 - 增强版本，支持分级管理

        Args:
            symbol: 标的代码
            quantity: 数量
            cost_price: 成本价格
            level: 仓位级别
            batch_id: 批次ID
        """
        symbol = symbol.strip().upper()

        if symbol in self.positions:
            # 更新现有持仓
            self.positions[symbol].add_quantity(quantity, quantity * cost_price, level)
        else:
            # 创建新持仓
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                cost_price=cost_price,
                current_price=cost_price,
                position_level=level
            )

        # 记录批次ID
        if batch_id and batch_id not in self.positions[symbol].batch_ids:
            self.positions[symbol].batch_ids.append(batch_id)

        self.updated_time = datetime.now()

    @performance_monitor("portfolio_remove_position")
    def remove_position(self, symbol: str, quantity: int) -> float:
        """减少或移除持仓"""
        symbol = symbol.strip().upper()

        if symbol not in self.positions:
            raise DataValidationError(f"持仓不存在: {symbol}")

        realized_pnl = self.positions[symbol].reduce_quantity(quantity)

        if self.positions[symbol].quantity == 0:
            del self.positions[symbol]

        self.updated_time = datetime.now()
        return realized_pnl

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式 - 增强版本"""
        base_dict = {
            'portfolio_id': self.portfolio_id,
            'account_id': self.account_id,
            'total_assets': self.total_assets,
            'cash': self.cash,
            'available_cash': self.available_cash,
            'initial_capital': self.initial_capital,
            'market_value': self.market_value,
            'total_value': self.total_value,
            'unrealized_pnl': self.unrealized_pnl,
            'total_return': self.total_return,
            'cash_ratio': self.cash_ratio,
            'position_count': self.position_count,
            'positions': {symbol: position.to_dict() for symbol, position in self.positions.items()},
            'created_time': self.created_time.isoformat(),
            'updated_time': self.updated_time.isoformat(),
            'risk_parameters': {
                'max_position_weight': self.max_position_weight,
                'max_initial_weight': self.max_initial_weight,
                'stop_loss_ratio': self.stop_loss_ratio
            }
        }
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Portfolio':
        """从字典创建投资组合实例 - 增强版本"""
        created_time = datetime.fromisoformat(data['created_time']) if isinstance(data['created_time'], str) else data[
            'created_time']
        updated_time = datetime.fromisoformat(data['updated_time']) if isinstance(data['updated_time'], str) else data[
            'updated_time']

        portfolio = cls(
            account_id=data['account_id'],
            total_assets=data['total_assets'],
            cash=data['cash'],
            available_cash=data['available_cash'],
            initial_capital=data.get('initial_capital', data['total_assets']),
            portfolio_id=data.get('portfolio_id', str(uuid.uuid4())),
            created_time=created_time,
            updated_time=updated_time
        )

        # 恢复持仓
        positions_data = data.get('positions', {})
        for symbol, position_data in positions_data.items():
            portfolio.positions[symbol] = Position.from_dict(position_data)

        return portfolio

    def __str__(self) -> str:
        """投资组合的字符串表示"""
        return (f"Portfolio(账户:{self.account_id} 总资产:{self.total_assets:.2f} "
                f"现金:{self.cash:.2f} 持仓数:{self.position_count})")

    def __repr__(self) -> str:
        """投资组合的详细表示"""
        return (f"Portfolio(portfolio_id={self.portfolio_id}, account_id={self.account_id}, "
                f"total_assets={self.total_assets}, cash={self.cash}, "
                f"position_count={self.position_count})")


# 导出所有类
__all__ = ['Position', 'Portfolio']