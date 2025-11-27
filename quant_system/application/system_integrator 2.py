"""
系统服务集成器
负责初始化和管理所有分级仓位相关服务
"""

from typing import Dict, Any, Optional
import logging

from quant_system.utils.logger import get_logger
from quant_system.infrastructure.brokers.base import Broker
from quant_system.core.config import ConfigManager

# 导入分级仓位服务
try:
    from quant_system.domain.services.position_scaling_service import PositionScalingService
    from quant_system.domain.services.batch_risk_service import BatchRiskService
    from quant_system.domain.services.position_management import PositionManagementService
except ImportError as e:
    logging.warning(f"导入分级仓位服务失败: {e}")


class SystemServiceIntegrator:
    """
    系统服务集成器

    负责初始化、管理和协调所有分级仓位相关服务，
    提供统一的接口给交易系统使用。
    """

    def __init__(self, broker: Broker, config: ConfigManager):
        """
        初始化系统服务集成器

        Args:
            broker: 券商接口
            config: 配置管理器
        """
        self.broker = broker
        self.config = config
        self.logger = get_logger(__name__)

        # 服务实例
        self.position_manager: Optional[PositionManagementService] = None
        self.scaling_service: Optional[PositionScalingService] = None
        self.batch_risk_service: Optional[BatchRiskService] = None

        # 服务状态
        self.services_initialized = False
        self.scaling_enabled = False

        self.logger.info("系统服务集成器初始化完成")

    def initialize_services(self) -> bool:
        """
        初始化所有服务

        Returns:
            bool: 初始化是否成功
        """
        try:
            self.logger.info("🔄 初始化系统服务...")

            # 检查分级仓位是否启用
            self.scaling_enabled = self._check_scaling_enabled()

            # 初始化基础仓位管理服务
            self.position_manager = PositionManagementService(
                broker=self.broker,
                config=self.config
            )
            self.logger.info("✅ 仓位管理服务初始化完成")

            # 如果启用分级仓位，初始化相关服务
            if self.scaling_enabled:
                self._initialize_scaling_services()
            else:
                self.logger.info("ℹ️ 分级仓位功能未启用")

            self.services_initialized = True
            self.logger.info("🎉 所有系统服务初始化完成")
            return True

        except Exception as e:
            self.logger.error(f"❌ 服务初始化失败: {e}")
            return False

    def _check_scaling_enabled(self) -> bool:
        """
        检查分级仓位是否启用

        Returns:
            bool: 是否启用分级仓位
        """
        try:
            # 从配置中检查
            if hasattr(self.config, 'trading') and hasattr(self.config.trading, 'position_scaling_enabled'):
                enabled = self.config.trading.position_scaling_enabled
                self.logger.info(f"分级仓位配置: {'启用' if enabled else '禁用'}")
                return enabled

            # 检查系统配置
            if hasattr(self.config, 'system'):
                system_config = getattr(self.config, 'system', {})
                if isinstance(system_config, dict):
                    trading_config = system_config.get('trading', {})
                    return trading_config.get('enable_position_scaling', False)

            return False

        except Exception as e:
            self.logger.warning(f"检查分级仓位配置失败: {e}")
            return False

    def _initialize_scaling_services(self) -> None:
        """
        初始化分级仓位相关服务
        """
        try:
            # 初始化分级仓位服务
            self.scaling_service = PositionScalingService(
                broker=self.broker,
                config=self.config
            )
            self.logger.info("✅ 分级仓位服务初始化完成")

            # 初始化批次风控服务
            self.batch_risk_service = BatchRiskService(
                broker=self.broker,
                config=self.config
            )
            self.logger.info("✅ 批次风控服务初始化完成")

            self.logger.info("🎯 分级仓位系统就绪")

        except Exception as e:
            self.logger.error(f"分级仓位服务初始化失败: {e}")
            raise

    def get_scaling_opportunities(self, portfolio, market_data):
        """
        获取加仓机会

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            List: 加仓机会列表
        """
        if not self.scaling_enabled or not self.scaling_service:
            return []

        try:
            return self.scaling_service.find_scaling_opportunities(portfolio, market_data)
        except Exception as e:
            self.logger.error(f"获取加仓机会失败: {e}")
            return []

    def check_batch_risks(self, portfolio, market_data):
        """
        检查批次风险

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            List: 风险评估列表
        """
        if not self.scaling_enabled or not self.batch_risk_service:
            return []

        try:
            return self.batch_risk_service.check_batch_risks(portfolio, market_data)
        except Exception as e:
            self.logger.error(f"检查批次风险失败: {e}")
            return []

    def execute_batch_actions(self, portfolio, assessments):
        """
        执行批次动作

        Args:
            portfolio: 投资组合
            assessments: 风险评估列表

        Returns:
            List: 执行结果列表
        """
        if not self.scaling_enabled or not self.batch_risk_service:
            return []

        try:
            return self.batch_risk_service.execute_batch_actions(portfolio, assessments)
        except Exception as e:
            self.logger.error(f"执行批次动作失败: {e}")
            return []

    def calculate_safe_position(self, symbol, price, portfolio, is_initial=True):
        """
        计算安全仓位

        Args:
            symbol: 股票代码
            price: 价格
            portfolio: 投资组合
            is_initial: 是否初始建仓

        Returns:
            PositionSuggestion: 仓位建议
        """
        if not self.position_manager:
            raise RuntimeError("仓位管理服务未初始化")

        return self.position_manager.calculate_safe_position_size(
            symbol, price, portfolio, is_initial
        )

    def calculate_scaling_position(self, symbol, price, portfolio, current_level):
        """
        计算加仓仓位

        Args:
            symbol: 股票代码
            price: 价格
            portfolio: 投资组合
            current_level: 当前级别

        Returns:
            PositionSuggestion: 加仓建议
        """
        if not self.scaling_enabled or not self.position_manager:
            raise RuntimeError("分级仓位服务未启用或未初始化")

        # 使用增强的仓位管理服务
        if hasattr(self.position_manager, 'calculate_scaling_position_size'):
            return self.position_manager.calculate_scaling_position_size(
                symbol, price, portfolio, current_level
            )
        else:
            # 回退到基础计算
            return self.position_manager.calculate_safe_position_size(
                symbol, price, portfolio, is_initial=False
            )

    def get_system_status(self) -> Dict[str, Any]:
        """
        获取系统状态

        Returns:
            Dict[str, Any]: 系统状态信息
        """
        status = {
            'services_initialized': self.services_initialized,
            'scaling_enabled': self.scaling_enabled,
            'position_manager_ready': self.position_manager is not None,
            'scaling_service_ready': self.scaling_service is not None,
            'batch_risk_service_ready': self.batch_risk_service is not None,
        }

        # 添加服务详细状态
        if self.scaling_service:
            status['scaling_service'] = self.scaling_service.get_scaling_report()

        if self.batch_risk_service:
            status['batch_risk_service'] = self.batch_risk_service.get_risk_report()

        return status

    def shutdown(self) -> None:
        """
        关闭所有服务
        """
        self.logger.info("正在关闭系统服务...")

        # 这里可以添加服务清理逻辑
        self.services_initialized = False
        self.scaling_enabled = False

        self.logger.info("系统服务已关闭")


# 全局服务集成器实例
_global_integrator: Optional[SystemServiceIntegrator] = None


def get_global_integrator() -> Optional[SystemServiceIntegrator]:
    """
    获取全局服务集成器实例

    Returns:
        Optional[SystemServiceIntegrator]: 全局集成器实例
    """
    return _global_integrator


def initialize_global_integrator(broker: Broker, config: ConfigManager) -> SystemServiceIntegrator:
    """
    初始化全局服务集成器

    Args:
        broker: 券商接口
        config: 配置管理器

    Returns:
        SystemServiceIntegrator: 全局集成器实例
    """
    global _global_integrator
    _global_integrator = SystemServiceIntegrator(broker, config)
    return _global_integrator


# 导出
__all__ = [
    'SystemServiceIntegrator',
    'get_global_integrator',
    'initialize_global_integrator'
]