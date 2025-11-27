"""
基础风控策略模块 (quant_system/domain/strategies/risk_basic.py)

功能概述：
    基础风险控制策略，提供止损、仓位控制和风险检查功能。
    基于投资组合理论和风险管理的科学方法。

核心特性：
    1. 止损管理：基于盈亏比例的自动止损
    2. 仓位控制：单票仓位和总仓位风险控制
    3. 风险检查：多层次的风险评估和预警
    4. 配置驱动：基于配置的动态风险参数调整
    5. 实时监控：结合实时市场数据的风险计算

设计模式：
    - 策略模式：可互换的风险控制算法
    - 观察者模式：风险状态监控和通知
    - 模板方法：标准化的风险检查流程

版本历史：
    v1.0 - 基础止损策略
    v2.0 - 增加仓位控制和风险评估
    v3.0 - 集成配置系统和实时监控
"""

import sys
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from decimal import Decimal

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from .base import RiskStrategy, ExecutionResult, StrategyConfig


class BasicRiskStrategy(RiskStrategy):
    """
    基础风控策略 - 优化版本

    提供基础的风险控制功能，包括止损、仓位控制和风险评估。
    基于科学的投资组合理论和风险管理原则。

    属性:
        broker: 券商接口实例
        config: 配置管理器实例
        stop_loss_ratio: 止损比例阈值
        position_limit_ratio: 单票仓位限制比例
        max_drawdown_limit: 最大回撤限制
        volatility_threshold: 波动率阈值
        performance_stats: 性能统计
    """

    def __init__(self, broker=None, config=None, strategy_config: Optional[StrategyConfig] = None):
        """
        初始化基础风控策略

        Args:
            broker: 券商接口实例
            config: 配置管理器实例
            strategy_config: 策略特定配置
        """
        # 初始化基类
        super_config = strategy_config or StrategyConfig()
        super().__init__("basic_stop_loss", super_config)

        # 依赖注入
        self.broker = broker
        self.config = config
        self.logger = get_logger(__name__)

        # 风险参数配置
        self.stop_loss_ratio = 0.05  # 止损比例 5%
        self.position_limit_ratio = 0.2  # 单票仓位限制 20%
        self.max_drawdown_limit = 0.1  # 最大回撤限制 10%
        self.volatility_threshold = 0.02  # 波动率阈值 2%

        # 性能统计
        self.performance_stats = {
            'total_checks': 0,
            'risk_events_detected': 0,
            'stop_loss_triggers': 0,
            'position_limit_triggers': 0,
            'average_check_time': 0.0,
            'last_check_time': None
        }

        # 从配置更新参数
        self._update_parameters_from_config()

        self.logger.info(f"✅ 基础风控策略初始化完成: {self.name}")

    def _update_parameters_from_config(self):
        """从配置更新风险参数"""
        try:
            if self.config and hasattr(self.config, 'trading'):
                trading_config = self.config.trading

                # 更新止损比例
                if hasattr(trading_config, 'stop_loss_ratio'):
                    self.stop_loss_ratio = trading_config.stop_loss_ratio

                # 更新仓位限制
                if hasattr(trading_config, 'max_position_ratio'):
                    self.position_limit_ratio = trading_config.max_position_ratio

            # 从策略特定配置更新
            if (self.config and
                    hasattr(self.config, 'system') and
                    hasattr(self.config.system, 'risk_strategies_config')):

                risk_config = self.config.system.risk_strategies_config.get(
                    'basic_stop_loss', {})

                if hasattr(risk_config, 'risk_threshold'):
                    self.stop_loss_ratio = risk_config.risk_threshold
                if hasattr(risk_config, 'weight'):
                    self.config.weight = risk_config.weight

            self.logger.debug(f"风控参数已从配置更新: 止损={self.stop_loss_ratio:.1%}")

        except Exception as e:
            self.logger.warning(f"配置更新异常: {e}")

    def check_risk(self, portfolio: Any, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行综合风险检查

        Args:
            portfolio: 投资组合对象
            market_data: 市场数据字典

        Returns:
            Dict[str, Any]: 风险检查结果
        """
        start_time = datetime.now()
        risk_actions = []
        risk_level = 'LOW'

        self.logger.debug("🔍 执行基础风控检查...")

        try:
            # 1. 止损检查
            stop_loss_actions = self._check_stop_loss(portfolio, market_data)
            risk_actions.extend(stop_loss_actions)

            # 2. 仓位集中度检查
            position_risk_actions = self._check_position_concentration(portfolio)
            risk_actions.extend(position_risk_actions)

            # 3. 资金风险检查
            cash_risk_actions = self._check_cash_risk(portfolio)
            risk_actions.extend(cash_risk_actions)

            # 4. 市场风险检查
            market_risk_actions = self._check_market_risk(portfolio, market_data)
            risk_actions.extend(market_risk_actions)

            # 确定总体风险等级
            risk_level = self._determine_overall_risk_level(risk_actions)

            # 更新性能统计
            self._update_performance_stats(start_time, len(risk_actions))

            # 记录风险检查结果
            if risk_actions:
                self.logger.warning(f"🚨 发现 {len(risk_actions)} 个风险事件")
            else:
                self.logger.info("✅ 风险检查通过")

        except Exception as e:
            self.logger.error(f"风险检查执行失败: {e}")
            risk_level = 'HIGH'
            risk_actions.append({
                'action': 'SYSTEM_ERROR',
                'reason': f'风险检查系统异常: {str(e)}',
                'urgency': 'HIGH'
            })

        return {
            'risk_level': risk_level,
            'actions': risk_actions,
            'strategy': self.name,
            'checked_positions': len(getattr(portfolio, 'positions', {})),
            'timestamp': datetime.now().isoformat(),
            'parameters': {
                'stop_loss_ratio': self.stop_loss_ratio,
                'position_limit_ratio': self.position_limit_ratio,
                'max_drawdown_limit': self.max_drawdown_limit
            }
        }

    def _check_stop_loss(self, portfolio: Any, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        检查止损条件

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            List[Dict[str, Any]]: 止损建议列表
        """
        actions = []

        positions = getattr(portfolio, 'positions', {})
        if not positions:
            return actions

        for symbol, position in positions.items():
            try:
                # 获取当前价格
                current_price = self._get_current_price(symbol, market_data)
                if current_price <= 0:
                    continue

                # 计算盈亏比例
                cost_price = getattr(position, 'cost_price', 0)
                if cost_price <= 0:
                    continue

                profit_ratio = (current_price - cost_price) / cost_price

                # 止损检查
                if profit_ratio <= -self.stop_loss_ratio:
                    actions.append({
                        'symbol': symbol,
                        'action': 'STOP_LOSS',
                        'reason': f'亏损达到{abs(profit_ratio):.1%}，超过止损阈值{self.stop_loss_ratio:.1%}',
                        'quantity': getattr(position, 'quantity', 0),
                        'current_price': current_price,
                        'cost_price': cost_price,
                        'profit_ratio': profit_ratio,
                        'urgency': 'HIGH'
                    })

                    self.performance_stats['stop_loss_triggers'] += 1
                    self.logger.warning(
                        f"🚨 {symbol} 触发止损: 亏损{abs(profit_ratio):.1%} "
                        f"(成本:{cost_price:.2f}, 现价:{current_price:.2f})"
                    )

            except Exception as e:
                self.logger.error(f"止损检查失败 {symbol}: {e}")
                continue

        return actions

    def _check_position_concentration(self, portfolio: Any) -> List[Dict[str, Any]]:
        """
        检查仓位集中度风险

        Args:
            portfolio: 投资组合

        Returns:
            List[Dict[str, Any]]: 仓位风险建议列表
        """
        actions = []

        try:
            positions = getattr(portfolio, 'positions', {})
            total_assets = getattr(portfolio, 'total_assets', 0)

            if total_assets <= 0 or not positions:
                return actions

            # 计算每个持仓的权重
            position_weights = {}
            for symbol, position in positions.items():
                quantity = getattr(position, 'quantity', 0)
                cost_price = getattr(position, 'cost_price', 0)
                position_value = quantity * cost_price
                weight = position_value / total_assets
                position_weights[symbol] = weight

            # 检查单票仓位限制
            for symbol, weight in position_weights.items():
                if weight > self.position_limit_ratio:
                    actions.append({
                        'symbol': symbol,
                        'action': 'REDUCE_POSITION',
                        'reason': f'仓位集中度{weight:.1%}超过限制{self.position_limit_ratio:.1%}',
                        'current_weight': weight,
                        'suggested_weight': self.position_limit_ratio,
                        'urgency': 'MEDIUM'
                    })

                    self.performance_stats['position_limit_triggers'] += 1
                    self.logger.warning(
                        f"⚠️ {symbol} 仓位过重: {weight:.1%} > {self.position_limit_ratio:.1%}"
                    )

            # 检查前3大持仓集中度
            sorted_weights = sorted(position_weights.values(), reverse=True)
            top3_concentration = sum(sorted_weights[:3])

            if top3_concentration > 0.6:  # 前3大持仓超过60%
                actions.append({
                    'action': 'DIVERSIFY',
                    'reason': f'前3大持仓集中度{top3_concentration:.1%}过高',
                    'concentration_ratio': top3_concentration,
                    'urgency': 'MEDIUM'
                })

        except Exception as e:
            self.logger.error(f"仓位集中度检查失败: {e}")

        return actions

    def _check_cash_risk(self, portfolio: Any) -> List[Dict[str, Any]]:
        """
        检查资金风险

        Args:
            portfolio: 投资组合

        Returns:
            List[Dict[str, Any]]: 资金风险建议列表
        """
        actions = []

        try:
            available_cash = getattr(portfolio, 'available_cash', 0)
            total_assets = getattr(portfolio, 'total_assets', 0)

            if total_assets <= 0:
                return actions

            cash_ratio = available_cash / total_assets

            # 检查现金比例
            if cash_ratio < 0.1:  # 现金比例低于10%
                actions.append({
                    'action': 'INCREASE_CASH',
                    'reason': f'现金比例{cash_ratio:.1%}过低，建议保留至少10%现金',
                    'current_ratio': cash_ratio,
                    'suggested_ratio': 0.1,
                    'urgency': 'MEDIUM'
                })
                self.logger.warning(f"💰 现金比例偏低: {cash_ratio:.1%}")

            elif cash_ratio > 0.5:  # 现金比例高于50%
                actions.append({
                    'action': 'DEPLOY_CASH',
                    'reason': f'现金比例{cash_ratio:.1%}过高，建议适当配置资产',
                    'current_ratio': cash_ratio,
                    'suggested_ratio': 0.3,
                    'urgency': 'LOW'
                })
                self.logger.info(f"💰 现金比例较高: {cash_ratio:.1%}")

        except Exception as e:
            self.logger.error(f"资金风险检查失败: {e}")

        return actions

    def _check_market_risk(self, portfolio: Any, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        检查市场风险

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            List[Dict[str, Any]]: 市场风险建议列表
        """
        actions = []

        try:
            # 计算组合整体涨跌幅
            total_change = self._calculate_portfolio_change(portfolio, market_data)

            if total_change < -0.05:  # 组合整体下跌超过5%
                actions.append({
                    'action': 'MONITOR_MARKET',
                    'reason': f'组合近期下跌{abs(total_change):.1%}，建议密切关注市场',
                    'portfolio_change': total_change,
                    'urgency': 'MEDIUM'
                })
                self.logger.info(f"📉 组合近期表现: {total_change:+.1%}")

        except Exception as e:
            self.logger.error(f"市场风险检查失败: {e}")

        return actions

    def _get_current_price(self, symbol: str, market_data: Dict[str, Any]) -> float:
        """
        获取当前价格

        Args:
            symbol: 股票代码
            market_data: 市场数据

        Returns:
            float: 当前价格
        """
        try:
            if symbol in market_data:
                return float(market_data[symbol].get('last_price', 0))
            return 0.0
        except (ValueError, TypeError):
            return 0.0

    def _calculate_portfolio_change(self, portfolio: Any, market_data: Dict[str, Any]) -> float:
        """
        计算投资组合变化

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            float: 组合变化率
        """
        try:
            # 简化实现：计算持仓股票的平均涨跌幅
            positions = getattr(portfolio, 'positions', {})
            if not positions:
                return 0.0

            changes = []
            for symbol in positions.keys():
                if symbol in market_data:
                    change = market_data[symbol].get('change_rate', 0)
                    changes.append(change)

            return sum(changes) / len(changes) if changes else 0.0

        except Exception as e:
            self.logger.error(f"组合变化计算失败: {e}")
            return 0.0

    def _determine_overall_risk_level(self, risk_actions: List[Dict[str, Any]]) -> str:
        """
        确定总体风险等级

        Args:
            risk_actions: 风险建议列表

        Returns:
            str: 风险等级
        """
        if not risk_actions:
            return 'LOW'

        # 检查是否有高风险事件
        high_risk_actions = [action for action in risk_actions
                             if action.get('urgency') == 'HIGH']
        if high_risk_actions:
            return 'HIGH'

        # 检查是否有中等风险事件
        medium_risk_actions = [action for action in risk_actions
                               if action.get('urgency') == 'MEDIUM']
        if medium_risk_actions:
            return 'MEDIUM'

        return 'LOW'

    def _update_performance_stats(self, start_time: datetime, risk_actions_count: int):
        """
        更新性能统计

        Args:
            start_time: 开始时间
            risk_actions_count: 风险事件数量
        """
        execution_time = (datetime.now() - start_time).total_seconds()

        self.performance_stats['total_checks'] += 1
        self.performance_stats['last_check_time'] = datetime.now()

        if risk_actions_count > 0:
            self.performance_stats['risk_events_detected'] += 1

        # 更新平均检查时间
        total_checks = self.performance_stats['total_checks']
        current_avg = self.performance_stats['average_check_time']
        new_avg = (current_avg * (total_checks - 1) + execution_time) / total_checks
        self.performance_stats['average_check_time'] = new_avg

    def should_stop_loss(self, position: Any, market_data: Dict[str, Any]) -> bool:
        """
        判断是否应该止损

        Args:
            position: 持仓对象
            market_data: 市场数据

        Returns:
            bool: 是否应该止损
        """
        try:
            symbol = getattr(position, 'symbol', '')
            current_price = self._get_current_price(symbol, market_data)
            cost_price = getattr(position, 'cost_price', 0)

            if current_price <= 0 or cost_price <= 0:
                return False

            profit_ratio = (current_price - cost_price) / cost_price
            return profit_ratio <= -self.stop_loss_ratio

        except Exception as e:
            self.logger.error(f"止损判断失败: {e}")
            return False

    def execute(self, data: Dict[str, Any]) -> ExecutionResult:
        """
        执行风控策略

        Args:
            data: 输入数据

        Returns:
            ExecutionResult: 执行结果
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

    def get_performance_metrics(self) -> Dict[str, Any]:
        """获取策略性能指标"""
        base_metrics = super().get_performance_metrics()
        base_metrics.update({
            'strategy_specific': {
                'risk_parameters': {
                    'stop_loss_ratio': self.stop_loss_ratio,
                    'position_limit_ratio': self.position_limit_ratio,
                    'max_drawdown_limit': self.max_drawdown_limit
                },
                'performance_stats': self.performance_stats,
                'risk_detection_rate': (
                        self.performance_stats['risk_events_detected'] /
                        max(self.performance_stats['total_checks'], 1)
                )
            }
        })
        return base_metrics

    def update_risk_parameters(self, new_parameters: Dict[str, Any]):
        """
        更新风险参数

        Args:
            new_parameters: 新参数
        """
        if 'stop_loss_ratio' in new_parameters:
            self.stop_loss_ratio = new_parameters['stop_loss_ratio']
        if 'position_limit_ratio' in new_parameters:
            self.position_limit_ratio = new_parameters['position_limit_ratio']
        if 'max_drawdown_limit' in new_parameters:
            self.max_drawdown_limit = new_parameters['max_drawdown_limit']

        self.logger.info(f"🔄 风控参数已更新: {new_parameters}")

# 导出类
__all__ = ['BasicRiskStrategy']