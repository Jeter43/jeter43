"""
仓位批次实体模块
用于管理分级加仓系统中的不同批次仓位
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid


class PositionBatchStatus(Enum):
    """仓位批次状态枚举"""
    ACTIVE = "active"  # 活跃中
    STOPPED = "stopped"  # 已止损
    CLOSED = "closed"  # 已平仓
    PROFIT_TAKEN = "profit_taken"  # 已止盈


@dataclass
class PositionBatch:
    """
    仓位批次实体
    记录每次加仓的独立信息，支持分级风控
    """

    # 基础标识信息
    batch_id: str  # 批次唯一标识
    symbol: str  # 股票代码
    portfolio_id: str  # 所属投资组合ID

    # 仓位级别信息
    level: int  # 仓位级别: 1=初始, 2=第一次加仓, 3=第二次加仓

    # 交易信息
    entry_time: datetime  # 建仓时间
    entry_price: float  # 建仓价格
    quantity: int  # 持仓数量
    parent_batch_id: Optional[str] = None  # 父批次ID（用于追踪加仓关系）
    transaction_cost: float = 0.0  # 交易成本

    # 当前状态信息
    current_price: float = 0.0  # 当前价格
    update_time: datetime = field(default_factory=datetime.now)  # 最后更新时间

    # 风控参数
    initial_stop_loss: float = 0.0  # 初始止损价
    trailing_stop_price: float = 0.0  # 移动止损价
    highest_price: float = 0.0  # 达到的最高价（用于移动止损）
    take_profit_price: Optional[float] = None  # 止盈价

    # 状态管理
    status: PositionBatchStatus = PositionBatchStatus.ACTIVE
    exit_time: Optional[datetime] = None  # 平仓时间
    exit_price: Optional[float] = None  # 平仓价格
    exit_reason: Optional[str] = None  # 平仓原因

    # 性能统计
    max_profit_ratio: float = 0.0  # 最大盈利比例
    max_drawdown_ratio: float = 0.0  # 最大回撤比例

    def __post_init__(self):
        """初始化后处理"""
        # 设置初始最高价和移动止损
        if self.current_price == 0:
            self.current_price = self.entry_price

        if self.highest_price == 0:
            self.highest_price = self.entry_price

        if self.trailing_stop_price == 0 and self.initial_stop_loss > 0:
            self.trailing_stop_price = self.initial_stop_loss

    @property
    def market_value(self) -> float:
        """当前市值"""
        return self.current_price * self.quantity

    @property
    def cost_value(self) -> float:
        """成本市值"""
        return self.entry_price * self.quantity

    @property
    def profit_loss(self) -> float:
        """盈亏金额"""
        return self.market_value - self.cost_value - self.transaction_cost

    @property
    def profit_ratio(self) -> float:
        """盈亏比例"""
        if self.cost_value <= 0:
            return 0.0
        return self.profit_loss / self.cost_value

    @property
    def is_profitable(self) -> bool:
        """是否盈利"""
        return self.profit_ratio > 0

    @property
    def holding_days(self) -> int:
        """持有天数"""
        return (datetime.now() - self.entry_time).days

    def update_price(self, new_price: float, update_time: datetime = None):
        """
        更新价格并重新计算风控参数

        Args:
            new_price: 新价格
            update_time: 更新时间
        """
        self.current_price = new_price
        self.update_time = update_time or datetime.now()

        # 更新最高价
        if new_price > self.highest_price:
            self.highest_price = new_price
            self.max_profit_ratio = (new_price - self.entry_price) / self.entry_price

        # 更新最大回撤
        current_drawdown = (self.highest_price - new_price) / self.highest_price
        if current_drawdown > self.max_drawdown_ratio:
            self.max_drawdown_ratio = current_drawdown

    def update_trailing_stop(self, trailing_stop_ratio: float):
        """
        更新移动止损价

        Args:
            trailing_stop_ratio: 移动止损比例
        """
        if self.highest_price > 0:
            new_stop_price = self.highest_price * (1 - trailing_stop_ratio)
            # 移动止损只能向上移动
            if new_stop_price > self.trailing_stop_price:
                self.trailing_stop_price = new_stop_price

    def should_stop_loss(self) -> bool:
        """是否应该止损"""
        if self.status != PositionBatchStatus.ACTIVE:
            return False

        # 检查移动止损
        if self.trailing_stop_price > 0 and self.current_price <= self.trailing_stop_price:
            return True

        # 检查初始止损
        if self.initial_stop_loss > 0 and self.current_price <= self.initial_stop_loss:
            return True

        return False

    def close_position(self, exit_price: float, reason: str, exit_time: datetime = None):
        """
        平仓操作

        Args:
            exit_price: 平仓价格
            reason: 平仓原因
            exit_time: 平仓时间
        """
        self.exit_price = exit_price
        self.exit_reason = reason
        self.exit_time = exit_time or datetime.now()
        self.current_price = exit_price

        # 根据盈亏设置状态
        if self.profit_ratio > 0:
            self.status = PositionBatchStatus.PROFIT_TAKEN
        else:
            self.status = PositionBatchStatus.STOPPED

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'batch_id': self.batch_id,
            'symbol': self.symbol,
            'portfolio_id': self.portfolio_id,
            'level': self.level,
            'parent_batch_id': self.parent_batch_id,
            'entry_time': self.entry_time.isoformat(),
            'entry_price': self.entry_price,
            'quantity': self.quantity,
            'current_price': self.current_price,
            'market_value': self.market_value,
            'cost_value': self.cost_value,
            'profit_loss': self.profit_loss,
            'profit_ratio': self.profit_ratio,
            'status': self.status.value,
            'highest_price': self.highest_price,
            'trailing_stop_price': self.trailing_stop_price,
            'initial_stop_loss': self.initial_stop_loss,
            'holding_days': self.holding_days,
            'max_profit_ratio': self.max_profit_ratio,
            'max_drawdown_ratio': self.max_drawdown_ratio
        }

    @classmethod
    def create_initial_batch(cls,
                             symbol: str,
                             portfolio_id: str,
                             entry_price: float,
                             quantity: int,
                             stop_loss_ratio: float = 0.08) -> 'PositionBatch':
        """
        创建初始仓位批次（L1级别）

        Args:
            symbol: 股票代码
            portfolio_id: 组合ID
            entry_price: 建仓价格
            quantity: 数量
            stop_loss_ratio: 止损比例

        Returns:
            PositionBatch: 初始批次实例
        """
        stop_loss_price = entry_price * (1 - stop_loss_ratio)

        return cls(
            batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            symbol=symbol,
            portfolio_id=portfolio_id,
            level=1,
            entry_time=datetime.now(),
            entry_price=entry_price,
            quantity=quantity,
            current_price=entry_price,
            initial_stop_loss=stop_loss_price,
            trailing_stop_price=stop_loss_price,
            highest_price=entry_price
        )

    @classmethod
    def create_scaling_batch(cls,
                             symbol: str,
                             portfolio_id: str,
                             entry_price: float,
                             quantity: int,
                             parent_batch: 'PositionBatch',
                             stop_loss_ratio: float = 0.04) -> 'PositionBatch':
        """
        创建加仓批次

        Args:
            symbol: 股票代码
            portfolio_id: 组合ID
            entry_price: 加仓价格
            quantity: 加仓数量
            parent_batch: 父批次
            stop_loss_ratio: 止损比例（加仓批次更紧）

        Returns:
            PositionBatch: 加仓批次实例
        """
        stop_loss_price = entry_price * (1 - stop_loss_ratio)

        return cls(
            batch_id=f"batch_{uuid.uuid4().hex[:8]}",
            symbol=symbol,
            portfolio_id=portfolio_id,
            level=parent_batch.level + 1,
            parent_batch_id=parent_batch.batch_id,
            entry_time=datetime.now(),
            entry_price=entry_price,
            quantity=quantity,
            current_price=entry_price,
            initial_stop_loss=stop_loss_price,
            trailing_stop_price=stop_loss_price,
            highest_price=entry_price
        )


@dataclass
class StockPosition:
    """
    股票级别的聚合视图，维护一个标的的所有仓位批次和风险指标
    """

    symbol: str
    batches: List[PositionBatch] = field(default_factory=list)
    current_level: int = 0
    overall_stop_loss: float = 0.0
    risk_exposure: float = 0.0

    def add_batch(self, batch: PositionBatch) -> None:
        """添加批次并更新聚合级别"""
        self.batches.append(batch)
        if batch.level > self.current_level:
            self.current_level = batch.level

    @property
    def total_value(self) -> float:
        """当前持仓总市值"""
        return sum(batch.market_value for batch in self.batches)


class PositionBatchManager:
    """
    仓位批次管理器
    提供批量操作和查询功能
    """

    def __init__(self):
        self.batches: Dict[str, PositionBatch] = {}  # batch_id -> PositionBatch
        self.symbol_batches: Dict[str, list] = {}  # symbol -> list of batch_ids

    def add_batch(self, batch: PositionBatch):
        """添加批次"""
        self.batches[batch.batch_id] = batch

        if batch.symbol not in self.symbol_batches:
            self.symbol_batches[batch.symbol] = []
        self.symbol_batches[batch.symbol].append(batch.batch_id)

    def get_batches_by_symbol(self, symbol: str) -> list[PositionBatch]:
        """获取指定股票的所有批次"""
        batch_ids = self.symbol_batches.get(symbol, [])
        return [self.batches[bid] for bid in batch_ids if bid in self.batches]

    def get_active_batches_by_symbol(self, symbol: str) -> list[PositionBatch]:
        """获取指定股票的活跃批次"""
        batches = self.get_batches_by_symbol(symbol)
        return [b for b in batches if b.status == PositionBatchStatus.ACTIVE]

    def get_batches_by_level(self, symbol: str, level: int) -> list[PositionBatch]:
        """获取指定股票和级别的批次"""
        batches = self.get_batches_by_symbol(symbol)
        return [b for b in batches if b.level == level]

    def update_prices(self, symbol: str, new_price: float):
        """更新指定股票所有批次的价格"""
        batches = self.get_batches_by_symbol(symbol)
        for batch in batches:
            batch.update_price(new_price)

    def check_stop_losses(self, symbol: str) -> list[PositionBatch]:
        """检查需要止损的批次"""
        active_batches = self.get_active_batches_by_symbol(symbol)
        stopped_batches = []

        for batch in active_batches:
            if batch.should_stop_loss():
                stopped_batches.append(batch)

        return stopped_batches