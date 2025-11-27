# trading_system/domain/entities/order.py
"""
订单实体模块
定义订单相关的数据结构和业务逻辑
提供完整的订单生命周期管理
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
import uuid

from quant_system.core.exceptions import DataValidationError
from quant_system.utils.monitoring import performance_monitor


class OrderSide(Enum):
    """
    订单方向枚举
    定义买入和卖出两种交易方向
    """
    BUY = "BUY"  # 买入订单
    SELL = "SELL"  # 卖出订单

    @classmethod
    def from_string(cls, side_str: str) -> 'OrderSide':
        """
        从字符串转换订单方向

        Args:
            side_str: 订单方向字符串，不区分大小写

        Returns:
            OrderSide: 对应的订单方向枚举

        Raises:
            ValueError: 当字符串无法匹配任何订单方向时
        """
        side_str_upper = side_str.upper()
        for side in cls:
            if side.value == side_str_upper:
                return side
        raise ValueError(f"无效的订单方向: {side_str}")


class OrderType(Enum):
    """
    订单类型枚举
    定义市价单和限价单两种订单类型
    """
    MARKET = "MARKET"  # 市价单 - 以当前市场最优价格成交
    LIMIT = "LIMIT"  # 限价单 - 以指定或更优价格成交

    @classmethod
    def from_string(cls, type_str: str) -> 'OrderType':
        """
        从字符串转换订单类型

        Args:
            type_str: 订单类型字符串，不区分大小写

        Returns:
            OrderType: 对应的订单类型枚举

        Raises:
            ValueError: 当字符串无法匹配任何订单类型时
        """
        type_str_upper = type_str.upper()
        for order_type in cls:
            if order_type.value == type_str_upper:
                return order_type
        raise ValueError(f"无效的订单类型: {type_str}")


class OrderStatus(Enum):
    """
    订单状态枚举
    定义订单的完整生命周期状态
    """
    PENDING = "PENDING"  # 待提交 - 订单已创建但未提交到券商
    SUBMITTED = "SUBMITTED"  # 已提交 - 订单已提交到券商系统
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 部分成交 - 订单部分成交
    FILLED = "FILLED"  # 完全成交 - 订单全部成交
    CANCELLED = "CANCELLED"  # 已取消 - 订单已被取消
    REJECTED = "REJECTED"  # 已拒绝 - 订单被券商拒绝
    EXPIRED = "EXPIRED"  # 已过期 - 订单已超过有效期

    @classmethod
    def get_active_statuses(cls) -> list['OrderStatus']:
        """获取活跃状态列表"""
        return [cls.PENDING, cls.SUBMITTED, cls.PARTIALLY_FILLED]

    @classmethod
    def get_completed_statuses(cls) -> list['OrderStatus']:
        """获取完成状态列表"""
        return [cls.FILLED, cls.CANCELLED, cls.REJECTED, cls.EXPIRED]

    @classmethod
    def is_terminal_status(cls, status: 'OrderStatus') -> bool:
        """检查是否为终止状态"""
        return status in cls.get_completed_statuses()


@dataclass
class Order:
    """
    订单实体类
    表示一个完整的交易订单，包含所有订单相关属性和业务逻辑
    """

    # 基础订单信息
    symbol: str  # 交易标的代码 (如: "000001.SZ")
    quantity: int  # 订单数量 (必须为正整数)
    price: float  # 订单价格 (市价单为0，限价单为正数)
    side: OrderSide  # 订单方向 (买入/卖出)

    # 订单配置
    order_type: OrderType = OrderType.MARKET  # 订单类型 (市价/限价)
    status: OrderStatus = OrderStatus.PENDING  # 订单状态
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # 订单唯一标识

    # 成交信息
    filled_quantity: int = 0  # 已成交数量
    filled_price: float = 0.0  # 成交均价
    filled_amount: float = 0.0  # 成交金额

    # 时间信息
    created_time: datetime = field(default_factory=datetime.now)  # 创建时间
    updated_time: datetime = field(default_factory=datetime.now)  # 最后更新时间
    submitted_time: Optional[datetime] = None  # 提交时间
    filled_time: Optional[datetime] = None  # 成交时间

    # 附加信息
    remark: str = ""  # 订单备注
    strategy_id: Optional[str] = None  # 策略标识
    broker_order_id: Optional[str] = None  # 券商订单ID

    # 风险控制
    stop_price: Optional[float] = None  # 止损价格
    limit_price: Optional[float] = None  # 限价价格

    def __post_init__(self):
        """数据类初始化后处理，用于数据验证和清理"""
        self.symbol = self.symbol.strip().upper()
        self._validate_order()

    def _validate_order(self) -> None:
        """
        验证订单数据的有效性

        Raises:
            DataValidationError: 当订单数据无效时抛出
        """
        errors = []

        # 验证标的代码
        if not self.symbol:
            errors.append("标的代码不能为空")

        # 验证数量
        if self.quantity <= 0:
            errors.append(f"订单数量必须大于0: {self.quantity}")

        # 验证价格
        if self.order_type == OrderType.LIMIT and self.price <= 0:
            errors.append(f"限价单价格必须大于0: {self.price}")

        # 验证价格合理性
        if self.price > 0 and self.price > 1_000_000:  # 假设最大价格100万
            errors.append(f"订单价格异常: {self.price}")

        # 验证数量合理性
        if self.quantity > 10_000_000:  # 假设最大数量1000万
            errors.append(f"订单数量异常: {self.quantity}")

        if errors:
            raise DataValidationError(
                message="订单数据验证失败",
                details={'errors': errors, 'order': self.to_dict()}
            )

    @performance_monitor("order_validate")
    def validate(self) -> bool:
        """
        验证订单有效性（兼容性方法）

        Returns:
            bool: 订单是否有效
        """
        try:
            self._validate_order()
            return True
        except DataValidationError:
            return False

    @performance_monitor("order_update_status")
    def update_status(self,
                      new_status: OrderStatus,
                      filled_qty: int = 0,
                      filled_price: float = 0.0,
                      broker_order_id: Optional[str] = None) -> None:
        """
        更新订单状态

        Args:
            new_status: 新的订单状态
            filled_qty: 成交数量 (默认为0)
            filled_price: 成交价格 (默认为0.0)
            broker_order_id: 券商订单ID (可选)

        Raises:
            DataValidationError: 当状态更新数据无效时抛出
        """
        # 验证状态转换的合法性
        if OrderStatus.is_terminal_status(self.status):
            raise DataValidationError(
                f"无法更新终止状态的订单: {self.status.value} -> {new_status.value}",
                details={'current_status': self.status.value, 'new_status': new_status.value}
            )

        # 验证成交数据
        if filled_qty < 0 or filled_qty > self.quantity:
            raise DataValidationError(
                f"无效的成交数量: {filled_qty}",
                details={'quantity': self.quantity, 'filled_quantity': filled_qty}
            )

        if filled_price < 0:
            raise DataValidationError(f"成交价格不能为负数: {filled_price}")

        # 更新状态
        old_status = self.status
        self.status = new_status
        self.updated_time = datetime.now()

        # 更新成交信息
        if filled_qty > 0:
            self.filled_quantity = filled_qty
            self.filled_price = filled_price
            self.filled_amount = filled_qty * filled_price

            # 如果是首次成交，设置成交时间
            if self.filled_time is None and filled_qty > 0:
                self.filled_time = datetime.now()

        # 更新券商订单ID
        if broker_order_id:
            self.broker_order_id = broker_order_id

        # 设置提交时间
        if new_status == OrderStatus.SUBMITTED and self.submitted_time is None:
            self.submitted_time = datetime.now()

        # 记录状态变更日志（在实际项目中可以记录到日志系统）
        print(f"订单状态变更: {old_status.value} -> {new_status.value} [订单: {self.order_id}]")

    @property
    def is_completed(self) -> bool:
        """订单是否已完成（终止状态）"""
        return OrderStatus.is_terminal_status(self.status)

    @property
    def is_active(self) -> bool:
        """订单是否活跃（非终止状态）"""
        return not self.is_completed

    @property
    def remaining_quantity(self) -> int:
        """剩余未成交数量"""
        return max(0, self.quantity - self.filled_quantity)

    @property
    def filled_value(self) -> float:
        """已成交价值"""
        return self.filled_quantity * self.filled_price

    @property
    def avg_filled_price(self) -> float:
        """平均成交价格"""
        if self.filled_quantity > 0:
            return self.filled_amount / self.filled_quantity
        return 0.0

    @property
    def is_fully_filled(self) -> bool:
        """是否完全成交"""
        return self.filled_quantity >= self.quantity

    @property
    def is_partially_filled(self) -> bool:
        """是否部分成交"""
        return 0 < self.filled_quantity < self.quantity

    def calculate_commission(self, commission_rate: float = 0.0003) -> float:
        """
        计算预估佣金

        Args:
            commission_rate: 佣金费率，默认万分之三

        Returns:
            float: 预估佣金金额
        """
        if self.filled_amount > 0:
            return self.filled_amount * commission_rate
        elif self.price > 0:
            estimated_amount = self.quantity * self.price
            return estimated_amount * commission_rate
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """
        将订单转换为字典格式

        Returns:
            Dict[str, Any]: 包含所有订单信息的字典
        """
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'quantity': self.quantity,
            'price': self.price,
            'side': self.side.value,
            'order_type': self.order_type.value,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'filled_price': self.filled_price,
            'filled_amount': self.filled_amount,
            'remaining_quantity': self.remaining_quantity,
            'created_time': self.created_time.isoformat(),
            'updated_time': self.updated_time.isoformat(),
            'submitted_time': self.submitted_time.isoformat() if self.submitted_time else None,
            'filled_time': self.filled_time.isoformat() if self.filled_time else None,
            'remark': self.remark,
            'strategy_id': self.strategy_id,
            'broker_order_id': self.broker_order_id,
            'is_completed': self.is_completed,
            'is_active': self.is_active
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Order':
        """
        从字典创建订单实例

        Args:
            data: 包含订单数据的字典

        Returns:
            Order: 订单实例
        """
        # 处理枚举类型转换
        side = OrderSide.from_string(data['side']) if isinstance(data['side'], str) else data['side']
        order_type = OrderType.from_string(data['order_type']) if isinstance(data['order_type'], str) else data[
            'order_type']
        status = OrderStatus(data['status']) if isinstance(data['status'], str) else data['status']

        # 处理时间字段
        created_time = datetime.fromisoformat(data['created_time']) if isinstance(data['created_time'], str) else data[
            'created_time']
        updated_time = datetime.fromisoformat(data['updated_time']) if isinstance(data['updated_time'], str) else data[
            'updated_time']

        submitted_time = None
        if data.get('submitted_time'):
            submitted_time = datetime.fromisoformat(data['submitted_time']) if isinstance(data['submitted_time'],
                                                                                          str) else data[
                'submitted_time']

        filled_time = None
        if data.get('filled_time'):
            filled_time = datetime.fromisoformat(data['filled_time']) if isinstance(data['filled_time'], str) else data[
                'filled_time']

        return cls(
            symbol=data['symbol'],
            quantity=data['quantity'],
            price=data['price'],
            side=side,
            order_type=order_type,
            status=status,
            order_id=data.get('order_id', str(uuid.uuid4())),
            filled_quantity=data.get('filled_quantity', 0),
            filled_price=data.get('filled_price', 0.0),
            filled_amount=data.get('filled_amount', 0.0),
            created_time=created_time,
            updated_time=updated_time,
            submitted_time=submitted_time,
            filled_time=filled_time,
            remark=data.get('remark', ''),
            strategy_id=data.get('strategy_id'),
            broker_order_id=data.get('broker_order_id')
        )

    def __str__(self) -> str:
        """订单的字符串表示"""
        return (f"Order({self.symbol} {self.side.value} {self.order_type.value} "
                f"Qty:{self.quantity}@{self.price} Status:{self.status.value})")

    def __repr__(self) -> str:
        """订单的详细表示"""
        return (f"Order(order_id={self.order_id}, symbol={self.symbol}, "
                f"side={self.side.value}, type={self.order_type.value}, "
                f"quantity={self.quantity}, price={self.price}, status={self.status.value})")


# 导出所有类
__all__ = ['OrderSide', 'OrderType', 'OrderStatus', 'Order']