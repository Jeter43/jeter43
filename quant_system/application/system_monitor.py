# trading_system/application/system_monitor.py
"""
系统状态监控
实时监控系统运行状态和性能指标
"""

import sys
import os
import time
import psutil
import threading
from typing import Dict, Any, List,Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from quant_system.core.config import ConfigManager, SystemMode


@dataclass
class SystemMetrics:
    """系统性能指标"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_usage: float
    active_threads: int
    system_mode: str
    strategies_active: int
    positions_monitored: int
    last_trade_time: Optional[datetime] = None


@dataclass
class Alert:
    """系统告警"""
    level: str  # INFO, WARNING, ERROR, CRITICAL
    message: str
    timestamp: datetime
    component: str
    details: Dict[str, Any] = field(default_factory=dict)


class SystemMonitor:
    """系统状态监控器"""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.logger = get_logger()
        self.monitoring = False

        # 监控状态
        self.metrics_history: List[SystemMetrics] = []
        self.active_alerts: List[Alert] = []
        self.performance_stats: Dict[str, Any] = {}

        # 监控配置
        self.monitoring_config = {
            'cpu_threshold': 80.0,  # CPU使用率告警阈值
            'memory_threshold': 85.0,  # 内存使用率告警阈值
            'disk_threshold': 90.0,  # 磁盘使用率告警阈值
            'check_interval': 60,  # 检查间隔(秒)
            'max_metrics_history': 1000  # 最大历史记录数
        }

        self.is_monitoring = False

    def start_monitoring(self):
        """启动系统监控"""
        self.monitoring = True
        self.logger.info("🔍 启动系统监控")

        # 在后台线程中运行监控循环
        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()
        self.logger.info("✅ 系统监控已在后台线程启动")

    def _monitor_loop(self):
        """监控循环 - 在后台线程中运行"""
        self.logger.info("🔍 监控循环开始运行")

        while self.monitoring:
            try:
                # 使用新的配置属性名
                mode = self.config.system.mode
                selection_strategies = self.config.system.get_enabled_selection_strategies()
                risk_strategies = self.config.system.get_enabled_risk_strategies()

                # 监控逻辑...
                self.logger.debug("📊 系统监控运行中...")
                time.sleep(30)  # 30秒检查一次

            except Exception as e:
                self.logger.error(f"监控循环异常: {e}")
                time.sleep(60)  # 出错后等待1分钟

        self.logger.info("🛑 监控循环结束")

    def stop_monitoring(self):
        """停止监控"""
        self.is_monitoring = False
        self.logger.info("🛑 停止系统监控")

    def _monitoring_loop(self):
        """监控循环"""
        while self.is_monitoring:
            try:
                # 收集系统指标
                metrics = self._collect_system_metrics()
                self.metrics_history.append(metrics)

                # 检查系统健康状态
                self._check_system_health(metrics)

                # 清理历史数据
                self._cleanup_old_metrics()

                # 等待下一次检查
                time.sleep(self.monitoring_config['check_interval'])

            except Exception as e:
                self.logger.error(f"监控循环异常: {e}")
                time.sleep(10)  # 出错后等待10秒再继续

    def _collect_system_metrics(self) -> SystemMetrics:
        """收集系统指标 - 修复版本"""
        # 系统资源使用情况
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # 进程信息
        process = psutil.Process()
        active_threads = process.num_threads()

        # 使用新的配置属性名
        selection_count = len(self.config.system.get_enabled_selection_strategies())
        risk_count = len(self.config.system.get_enabled_risk_strategies())

        return SystemMetrics(
            timestamp=datetime.now(),
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            disk_usage=disk.percent,
            active_threads=active_threads,
            system_mode=self.config.system.mode.value,
            strategies_active=selection_count + risk_count,
            positions_monitored=len(self.config.system.monitored_stocks)
        )

    def _check_system_health(self, metrics: SystemMetrics):
        """检查系统健康状态"""
        alerts = []

        # CPU检查
        if metrics.cpu_percent > self.monitoring_config['cpu_threshold']:
            alerts.append(Alert(
                level='WARNING',
                message=f'CPU使用率过高: {metrics.cpu_percent:.1f}%',
                timestamp=datetime.now(),
                component='System',
                details={'cpu_percent': metrics.cpu_percent}
            ))

        # 内存检查
        if metrics.memory_percent > self.monitoring_config['memory_threshold']:
            alerts.append(Alert(
                level='WARNING',
                message=f'内存使用率过高: {metrics.memory_percent:.1f}%',
                timestamp=datetime.now(),
                component='System',
                details={'memory_percent': metrics.memory_percent}
            ))

        # 磁盘检查
        if metrics.disk_usage > self.monitoring_config['disk_threshold']:
            alerts.append(Alert(
                level='ERROR',
                message=f'磁盘使用率过高: {metrics.disk_usage:.1f}%',
                timestamp=datetime.now(),
                component='System',
                details={'disk_usage': metrics.disk_usage}
            ))

        # 处理告警
        for alert in alerts:
            self._handle_alert(alert)

    def _handle_alert(self, alert: Alert):
        """处理系统告警"""
        self.active_alerts.append(alert)

        # 根据告警级别记录日志
        if alert.level == 'CRITICAL':
            self.logger.critical(f"🚨 {alert.message}")
        elif alert.level == 'ERROR':
            self.logger.error(f"❌ {alert.message}")
        elif alert.level == 'WARNING':
            self.logger.warning(f"⚠️ {alert.message}")
        else:
            self.logger.info(f"ℹ️ {alert.message}")

        # 限制告警数量
        if len(self.active_alerts) > 50:
            self.active_alerts = self.active_alerts[-50:]

    def _cleanup_old_metrics(self):
        """清理旧的指标数据"""
        if len(self.metrics_history) > self.monitoring_config['max_metrics_history']:
            # 保留最近的数据
            keep_count = self.monitoring_config['max_metrics_history'] // 2
            self.metrics_history = self.metrics_history[-keep_count:]

    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态报告"""
        if not self.metrics_history:
            return {'status': 'UNKNOWN', 'message': 'No metrics collected'}

        latest_metrics = self.metrics_history[-1]

        # 确定系统状态
        status = 'HEALTHY'
        if any(alert.level in ['ERROR', 'CRITICAL'] for alert in self.active_alerts[-5:]):
            status = 'CRITICAL'
        elif any(alert.level == 'WARNING' for alert in self.active_alerts[-5:]):
            status = 'WARNING'

        return {
            'status': status,
            'timestamp': latest_metrics.timestamp,
            'metrics': {
                'cpu_usage': f"{latest_metrics.cpu_percent:.1f}%",
                'memory_usage': f"{latest_metrics.memory_percent:.1f}%",
                'disk_usage': f"{latest_metrics.disk_usage:.1f}%",
                'active_threads': latest_metrics.active_threads,
                'system_mode': latest_metrics.system_mode,
                'active_strategies': latest_metrics.strategies_active,
                'monitored_positions': latest_metrics.positions_monitored
            },
            'active_alerts': len([a for a in self.active_alerts if a.timestamp > datetime.now() - timedelta(hours=1)]),
            'performance_stats': self.performance_stats
        }

    def record_strategy_performance(self, strategy_name: str, performance: Dict[str, Any]):
        """记录策略性能指标"""
        if 'strategies' not in self.performance_stats:
            self.performance_stats['strategies'] = {}

        self.performance_stats['strategies'][strategy_name] = {
            **performance,
            'last_update': datetime.now()
        }

    def record_trade_activity(self, symbol: str, action: str, quantity: int, price: float):
        """记录交易活动"""
        if 'trades' not in self.performance_stats:
            self.performance_stats['trades'] = {
                'today_count': 0,
                'today_volume': 0,
                'last_trade_time': None
            }

        self.performance_stats['trades']['today_count'] += 1
        self.performance_stats['trades']['today_volume'] += quantity * price
        self.performance_stats['trades']['last_trade_time'] = datetime.now()

    def clear_old_alerts(self, older_than_hours: int = 24):
        """清理旧的告警"""
        cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
        self.active_alerts = [
            alert for alert in self.active_alerts
            if alert.timestamp > cutoff_time
        ]

    def generate_daily_report(self) -> Dict[str, Any]:
        """生成每日报告"""
        today = datetime.now().date()
        today_metrics = [
            m for m in self.metrics_history
            if m.timestamp.date() == today
        ]

        if not today_metrics:
            return {'error': 'No data for today'}

        # 计算统计信息
        cpu_values = [m.cpu_percent for m in today_metrics]
        memory_values = [m.memory_percent for m in today_metrics]

        return {
            'date': today.isoformat(),
            'metrics_summary': {
                'cpu_avg': sum(cpu_values) / len(cpu_values),
                'cpu_max': max(cpu_values),
                'memory_avg': sum(memory_values) / len(memory_values),
                'memory_max': max(memory_values),
            },
            'alerts_today': len([
                a for a in self.active_alerts
                if a.timestamp.date() == today
            ]),
            'system_uptime': self._get_system_uptime(),
            'performance_stats': self.performance_stats
        }

    def _get_system_uptime(self) -> str:
        """获取系统运行时间"""
        if not self.metrics_history:
            return "Unknown"

        start_time = self.metrics_history[0].timestamp
        uptime = datetime.now() - start_time

        days = uptime.days
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60

        return f"{days}d {hours}h {minutes}m"


# 导出类
__all__ = ['SystemMonitor', 'SystemMetrics', 'Alert']