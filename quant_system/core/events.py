# quant_system/core/events.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Callable
from enum import Enum
import threading
from dataclasses import dataclass


class EventType(Enum):
    """事件类型"""
    # Broker 相关事件
    BROKER_CONNECTION_FAILED = None
    BROKER_CONNECTED = "broker_connected"
    BROKER_DISCONNECTED = "broker_disconnected"

    # 多市场相关事件
    MULTI_MARKET_CONNECTED = "multi_market_connected"
    MULTI_MARKET_DISCONNECTED = "multi_market_disconnected"
    MARKET_SWITCHED = "market_switched"

    # 订单相关事件
    ORDER_CREATED = "order_created"
    ORDER_UPDATE = "order_update"
    ORDER_PLACED = "order_placed"

    # 市场数据事件
    MARKET_DATA = "market_data"

    # 其他事件
    POSITION_UPDATE = "position_update"
    STRATEGY_SIGNAL = "strategy_signal"
    SYSTEM_ERROR = "system_error"
    RISK_ALERT = "risk_alert"


@dataclass
class Event:
    """事件基类"""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            import time
            self.timestamp = time.time()


class EventHandler(ABC):
    """事件处理器基类"""

    @abstractmethod
    def handle_event(self, event: Event):
        """处理事件"""
        pass


class EventBus:
    """事件总线"""

    def __init__(self):
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: EventType, handler: EventHandler):
        """订阅事件"""
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler):
        """取消订阅"""
        with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type].remove(handler)

    def publish(self, event: Event):
        """发布事件"""
        with self._lock:
            handlers = self._handlers.get(event.event_type, [])
            for handler in handlers:
                try:
                    handler.handle_event(event)
                except Exception as e:
                    print(f"❌ 事件处理异常: {e}")


# 全局事件总线实例
event_bus = EventBus()