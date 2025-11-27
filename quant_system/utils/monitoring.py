# trading_system/utils/monitoring.py
"""
性能监控模块 - 提供统一的性能统计、监控和报告功能
"""

import time
import functools
from typing import Dict, Any, Optional, Callable, List, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from threading import Lock
import statistics
from enum import Enum


class MonitorLevel(Enum):
    """监控级别枚举"""
    BASIC = "basic"  # 基础监控
    DETAILED = "detailed"  # 详细监控
    DEBUG = "debug"  # 调试级别


@dataclass
class PerformanceStats:
    """性能统计数据类"""
    operation_name: str
    call_count: int = 0
    total_time: float = 0.0
    average_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    last_call_time: Optional[datetime] = None
    success_count: int = 0
    error_count: int = 0
    recent_times: List[float] = field(default_factory=list)

    def update(self, execution_time: float, success: bool = True):
        """更新统计信息"""
        self.call_count += 1
        self.total_time += execution_time
        self.average_time = self.total_time / self.call_count
        self.min_time = min(self.min_time, execution_time)
        self.max_time = max(self.max_time, execution_time)
        self.last_call_time = datetime.now()

        if success:
            self.success_count += 1
        else:
            self.error_count += 1

        # 维护最近100次调用时间
        self.recent_times.append(execution_time)
        if len(self.recent_times) > 100:
            self.recent_times.pop(0)

    def get_recent_stats(self, window: int = 10) -> Dict[str, float]:
        """获取最近N次调用的统计"""
        if not self.recent_times or window <= 0:
            return {}

        recent_data = self.recent_times[-window:]
        return {
            'recent_avg': statistics.mean(recent_data),
            'recent_median': statistics.median(recent_data),
            'recent_min': min(recent_data),
            'recent_max': max(recent_data),
            'recent_std': statistics.stdev(recent_data) if len(recent_data) > 1 else 0.0
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        recent_stats = self.get_recent_stats(10)
        return {
            'operation_name': self.operation_name,
            'call_count': self.call_count,
            'total_time': round(self.total_time, 4),
            'average_time': round(self.average_time, 4),
            'min_time': round(self.min_time, 4),
            'max_time': round(self.max_time, 4),
            'success_rate': round(self.success_count / self.call_count * 100, 2) if self.call_count > 0 else 0,
            'last_call_time': self.last_call_time.isoformat() if self.last_call_time else None,
            'recent_stats': recent_stats
        }


class PerformanceMonitor:
    """
    性能监控器 - 单例模式
    提供统一的性能统计和监控功能
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        """初始化监控器"""
        self._stats: Dict[str, PerformanceStats] = {}
        self._monitor_level = MonitorLevel.BASIC
        self._enabled = True
        self._start_time = datetime.now()
        self._stats_lock = Lock()

    def set_monitor_level(self, level: MonitorLevel):
        """设置监控级别"""
        self._monitor_level = level

    def enable_monitoring(self):
        """启用监控"""
        self._enabled = True

    def disable_monitoring(self):
        """禁用监控"""
        self._enabled = False

    def record_operation(self, operation_name: str, execution_time: float, success: bool = True):
        """记录操作性能"""
        if not self._enabled:
            return

        with self._stats_lock:
            if operation_name not in self._stats:
                self._stats[operation_name] = PerformanceStats(operation_name)

            self._stats[operation_name].update(execution_time, success)

    def get_operation_stats(self, operation_name: str) -> Optional[PerformanceStats]:
        """获取指定操作的统计"""
        with self._stats_lock:
            return self._stats.get(operation_name)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有统计信息"""
        with self._stats_lock:
            return {name: stats.to_dict() for name, stats in self._stats.items()}

    def get_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        with self._stats_lock:
            total_operations = sum(stats.call_count for stats in self._stats.values())
            total_time = sum(stats.total_time for stats in self._stats.values())
            success_rate = (
                sum(stats.success_count for stats in self._stats.values()) / total_operations * 100
                if total_operations > 0 else 0
            )

            return {
                'total_operations': total_operations,
                'total_monitored_time': round(total_time, 4),
                'overall_success_rate': round(success_rate, 2),
                'monitored_operations': len(self._stats),
                'system_uptime': round((datetime.now() - self._start_time).total_seconds(), 2),
                'monitor_level': self._monitor_level.value,
                'enabled': self._enabled
            }

    def clear_stats(self):
        """清空统计信息"""
        with self._stats_lock:
            self._stats.clear()
            self._start_time = datetime.now()

    def get_slow_operations(self, threshold: float = 1.0) -> List[Dict[str, Any]]:
        """获取执行时间超过阈值的操作"""
        slow_ops = []
        with self._stats_lock:
            for stats in self._stats.values():
                if stats.average_time > threshold:
                    slow_ops.append(stats.to_dict())

        return sorted(slow_ops, key=lambda x: x['average_time'], reverse=True)

    def get_high_frequency_operations(self, threshold: int = 100) -> List[Dict[str, Any]]:
        """获取高频调用操作"""
        high_freq_ops = []
        with self._stats_lock:
            for stats in self._stats.values():
                if stats.call_count > threshold:
                    high_freq_ops.append(stats.to_dict())

        return sorted(high_freq_ops, key=lambda x: x['call_count'], reverse=True)


# 全局性能监控器实例
_performance_monitor = PerformanceMonitor()


def performance_monitor(operation_name: Optional[str] = None, level: MonitorLevel = MonitorLevel.BASIC):
    """
    性能监控装饰器

    Args:
        operation_name: 操作名称，如果为None则使用函数名
        level: 监控级别
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 如果监控被禁用，直接执行函数
            if not _performance_monitor._enabled:
                return func(*args, **kwargs)

            op_name = operation_name or func.__name__
            start_time = time.time()
            success = True

            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                execution_time = time.time() - start_time
                _performance_monitor.record_operation(op_name, execution_time, success)

        return wrapper

    return decorator


class Timer:
    """
    计时器上下文管理器
    用于手动测量代码块执行时间
    """

    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time = None
        self.execution_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.execution_time = time.time() - self.start_time
        success = exc_type is None
        _performance_monitor.record_operation(self.operation_name, self.execution_time, success)

    def get_elapsed_time(self) -> float:
        """获取已用时间"""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time


def get_performance_monitor() -> PerformanceMonitor:
    """获取性能监控器实例"""
    return _performance_monitor


def enable_performance_monitoring(level: MonitorLevel = MonitorLevel.BASIC):
    """启用性能监控"""
    _performance_monitor.enable_monitoring()
    _performance_monitor.set_monitor_level(level)


def disable_performance_monitoring():
    """禁用性能监控"""
    _performance_monitor.disable_monitoring()


def get_performance_summary() -> Dict[str, Any]:
    """获取性能摘要"""
    return _performance_monitor.get_summary()


def get_operation_performance(operation_name: str) -> Optional[Dict[str, Any]]:
    """获取指定操作的性能数据"""
    stats = _performance_monitor.get_operation_stats(operation_name)
    return stats.to_dict() if stats else None


def clear_performance_stats():
    """清空性能统计"""
    _performance_monitor.clear_stats()


def generate_performance_report() -> Dict[str, Any]:
    """生成性能报告"""
    summary = _performance_monitor.get_summary()
    all_stats = _performance_monitor.get_all_stats()
    slow_operations = _performance_monitor.get_slow_operations()
    high_frequency_ops = _performance_monitor.get_high_frequency_operations()

    return {
        'summary': summary,
        'detailed_stats': all_stats,
        'slow_operations': slow_operations,
        'high_frequency_operations': high_frequency_ops,
        'report_time': datetime.now().isoformat()
    }


# 导出主要功能
__all__ = [
    'performance_monitor',
    'Timer',
    'PerformanceMonitor',
    'MonitorLevel',
    'get_performance_monitor',
    'enable_performance_monitoring',
    'disable_performance_monitoring',
    'get_performance_summary',
    'get_operation_performance',
    'clear_performance_stats',
    'generate_performance_report'
]