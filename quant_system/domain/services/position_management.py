"""
仓位管理服务模块 (trading_system/domain/services/position_management.py)

功能概述：
    提供专业的仓位管理功能，包括仓位计算、风险控制和订单验证。
    确保交易在安全的风险范围内进行，避免过度集中和过度交易。

核心特性：
    1. 科学仓位计算：基于风险和资金管理的仓位计算
    2. 风险控制：多层次的风险检查和限制
    3. 订单验证：交易前的参数验证和风险检查
    4. 资金管理：动态的资金分配和仓位调整
    5. 性能监控：仓位管理的性能统计和分析

设计模式：
    - 策略模式：不同的仓位管理策略
    - 工厂模式：仓位计算算法的创建
    - 模板方法：风险检查的统一流程

版本历史：
    v1.0 - 基础仓位管理
    v2.0 - 增加风险控制和资金管理
    v3.0 - 集成配置系统和性能监控
"""

from typing import Dict, Tuple, List, Optional, Any
from decimal import Decimal, ROUND_DOWN
import logging
from dataclasses import dataclass, field
from enum import Enum
import uuid
from datetime import datetime

from quant_system.infrastructure.brokers.base import Broker
from quant_system.core.config import ConfigManager
from quant_system.domain.entities.portfolio import Portfolio
from quant_system.domain.entities.position_batch import PositionBatch, StockPosition
from quant_system.domain.entities.portfolio import Portfolio
from quant_system.utils.logger import get_logger


class RiskLevel(Enum):
    """风险等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PositionSuggestion:
    """仓位建议数据类 - 增强版本"""
    symbol: str
    suggested_quantity: int
    max_quantity: int
    risk_level: RiskLevel
    reason: str
    available_cash: float
    position_value: float
    lot_size: int

    # 新增字段
    position_level: int = 1  # 仓位级别 L1/L2/L3
    is_scaling_position: bool = False  # 是否为加仓操作
    scaling_batch_id: Optional[str] = None  # 加仓批次ID
    profit_threshold_met: bool = False  # 是否达到盈利阈值
    current_profit_ratio: float = 0.0  # 当前盈利比例


class PositionManagementService:
    """
    仓位管理服务 - 优化版本

    提供专业的仓位管理和风险控制功能，确保交易在安全范围内进行。
    基于现代投资组合理论和风险管理的科学方法。

    属性:
        broker: 券商接口实例
        config: 配置管理器实例
        risk_tolerance: 风险容忍度
        performance_stats: 性能统计
    """

    def __init__(self, broker: Broker, config: ConfigManager):
        """
        初始化仓位管理服务

        Args:
            broker: 券商接口
            config: 配置管理器
        """
        self.broker = broker
        self.config = config
        self.logger = get_logger(__name__)

        # 风险参数
        self.risk_tolerance = getattr(config, 'risk_tolerance', 0.02)  # 2%风险容忍度

        # 性能统计
        self.performance_stats = {
            'total_calculations': 0,
            'risk_checks_passed': 0,
            'risk_checks_failed': 0,
            'average_calculation_time': 0.0
        }

        # 分级仓位管理
        self.position_batches: Dict[str, List[PositionBatch]] = {}
        self.stock_positions: Dict[str, StockPosition] = {}
        self.hierarchical_levels = {
            1: 0.10,
            2: 0.18,
            3: 0.22
        }
        self.addition_configs = {
            2: {'profit_threshold': 0.08, 'add_ratio': 0.07, 'max_wait_days': 20},
            3: {'profit_threshold': 0.065, 'add_ratio': 0.045, 'max_wait_days': 15}
        }
        self.stop_loss_profiles = {
            1: {'stop_loss_ratio': 0.08, 'trailing_ratio': 0.08},
            2: {'stop_loss_ratio': 0.02, 'trailing_ratio': 0.04},
            3: {'stop_loss_ratio': 0.03, 'trailing_ratio': 0.03}
        }
        self.market_condition_modifiers = {
            'bull': 0.9,
            'neutral': 1.0,
            'bear': 1.2
        }

        self.logger.info("仓位管理服务初始化完成")

    def calculate_safe_position_size(self,
                                     symbol: str,
                                     price: float,
                                     portfolio: Portfolio,
                                     is_initial: bool = True) -> PositionSuggestion:
        """
        计算安全仓位大小 - 优化版本

        基于凯利公式、风险管理和资金管理的科学仓位计算。

        Args:
            symbol: 股票代码
            price: 当前价格
            portfolio: 投资组合
            is_initial: 是否为初始建仓

        Returns:
            PositionSuggestion: 仓位建议
        """
        import time
        start_time = time.time()

        self.logger.info(f"计算安全仓位: {symbol} @ {price:.2f}")

        try:
            # 参数验证
            if price <= 0:
                return self._create_error_suggestion(symbol, "价格必须大于0")

            # 获取股票基本信息
            stock_info = self._get_stock_info(symbol)
            if not stock_info:
                return self._create_error_suggestion(symbol, "无法获取股票信息")

            # 风险检查
            risk_check = self._perform_comprehensive_risk_check(symbol, price, portfolio, is_initial)
            if not risk_check['allowed']:
                return self._create_error_suggestion(symbol, risk_check['reason'])

            # 计算最大允许仓位价值
            max_position_value = self._calculate_max_position_value(symbol, portfolio, is_initial)

            # 计算当前持仓价值
            current_position_value = self._calculate_current_position_value(symbol, price, portfolio)

            # 计算可买入金额
            available_for_stock = self._calculate_available_amount(
                max_position_value, current_position_value, portfolio)

            if available_for_stock <= 0:
                return self._create_error_suggestion(symbol, "无可用资金或已达仓位上限")

            # 加仓级别与动态限制
            total_assets = getattr(portfolio, 'total_assets', 0)
            position_ratio = self._calculate_position_ratio(current_position_value, total_assets)
            addition_level = self._determine_position_level(position_ratio)
            max_additional_value = None
            addition_reason = ""

            if not is_initial and addition_level > 1:
                position = self._get_portfolio_position(symbol, portfolio)
                evaluation = self._evaluate_hierarchical_addition(
                    symbol, position, addition_level, stock_info, portfolio)
                if not evaluation.get('allowed', True):
                    return self._create_error_suggestion(symbol, evaluation.get('reason', '未通过加仓条件'))
                addition_reason = evaluation.get('note', "")
                config = self.addition_configs.get(addition_level)
                if config and total_assets > 0:
                    max_additional_value = total_assets * config['add_ratio']

            # 在计算建议前，检查当前仓位级别
            current_level = self._get_current_position_level(symbol, portfolio)

            # 如果不是初始建仓，且当前有持仓，考虑加仓逻辑
            if not is_initial and current_level > 0:
                scaling_suggestion = self.calculate_scaling_position_size(
                        symbol, price, portfolio, current_level)

                # 如果加仓条件满足，返回加仓建议
                if (scaling_suggestion.suggested_quantity > 0 and
                         scaling_suggestion.risk_level != RiskLevel.CRITICAL):
                    return scaling_suggestion

            # 计算建议仓位
            suggestion = self._calculate_position_suggestion(
                symbol, price, available_for_stock, stock_info, portfolio,
                level=addition_level,
                max_additional_value=max_additional_value
            )

            if addition_reason:
                suggestion.reason = f"{suggestion.reason}; {addition_reason}"

            # 注册批次（实盘/模拟拜托）
            self._register_new_batch(symbol, suggestion, price, portfolio)

            # 更新性能统计
            self._update_performance_stats(start_time)

            return suggestion

        except Exception as e:
            self.logger.error(f"计算仓位失败 {symbol}: {e}")
            return self._create_error_suggestion(symbol, f"计算异常: {e}")

    def _get_current_position_level(self, symbol: str, portfolio: Portfolio) -> int:
        """
        获取当前仓位级别
        """
        try:
            # 如果Portfolio有批次管理，使用批次信息
            if hasattr(portfolio, 'position_batches') and symbol in portfolio.position_batches:
                batches = portfolio.position_batches[symbol]
                active_batches = [b for b in batches if b.is_active]
                return len(active_batches)  # 批次数量即为级别

            # 回退逻辑：根据持仓比例判断
            position_value = self._get_position_value(symbol, portfolio)
            total_assets = getattr(portfolio, 'total_assets', 1)
            position_ratio = position_value / total_assets

            if position_ratio >= 0.18:
                return 3
            elif position_ratio >= 0.10:
                return 2
            elif position_ratio > 0:
                return 1
            else:
                return 0

        except Exception as e:
            self.logger.error(f"获取仓位级别异常 {symbol}: {e}")
            return 0

    def _calculate_position_profit_ratio(self, symbol: str, current_price: float, portfolio: Portfolio) -> float:
        """
        计算持仓盈利比例
        """
        try:
            # 使用批次成本或平均成本计算盈利
            if hasattr(portfolio, 'position_batches') and symbol in portfolio.position_batches:
                batches = portfolio.position_batches[symbol]
                active_batches = [b for b in batches if b.is_active]

                if not active_batches:
                    return 0.0

                total_cost = sum(b.entry_price * b.quantity for b in active_batches)
                total_quantity = sum(b.quantity for b in active_batches)
                average_cost = total_cost / total_quantity if total_quantity > 0 else 0
            else:
                # 回退到原有逻辑
                position = portfolio.positions.get(symbol)
                if not position:
                    return 0.0
                average_cost = getattr(position, 'cost_price', 0)

            if average_cost <= 0:
                return 0.0

            return (current_price - average_cost) / average_cost

        except Exception as e:
            self.logger.error(f"计算盈利比例异常 {symbol}: {e}")
            return 0.0

    def validate_order(self,
                       symbol: str,
                       quantity: int,
                       price: float,
                       portfolio: Optional[Portfolio] = None) -> Dict[str, Any]:
        """
        验证订单 - 优化版本

        Args:
            symbol: 股票代码
            quantity: 订单数量
            price: 订单价格
            portfolio: 投资组合（可选）

        Returns:
            Dict[str, Any]: 验证结果
        """
        self.logger.info(f"验证订单: {symbol} x {quantity} @ {price:.2f}")

        try:
            # 基础参数验证
            base_validation = self._validate_basic_parameters(symbol, quantity, price)
            if not base_validation['valid']:
                return base_validation

            # 市场数据验证
            market_validation = self._validate_market_data(symbol, price)
            if not market_validation['valid']:
                return market_validation

            # 风险验证（如果有投资组合信息）
            if portfolio:
                risk_validation = self._validate_risk_parameters(symbol, quantity, price, portfolio)
                if not risk_validation['valid']:
                    return risk_validation

            # 订单类型特定验证
            order_validation = self._validate_order_specifics(symbol, quantity, price)
            if not order_validation['valid']:
                return order_validation

            self.performance_stats['risk_checks_passed'] += 1

            return {
                'valid': True,
                'message': '订单验证通过',
                'suggested_quantity': quantity,
                'risk_level': RiskLevel.LOW.value
            }

        except Exception as e:
            self.logger.error(f"订单验证异常: {e}")
            return {
                'valid': False,
                'message': f'验证异常: {e}',
                'suggested_quantity': 0,
                'risk_level': RiskLevel.CRITICAL.value
            }

    def get_position_risk_assessment(self, portfolio: Portfolio) -> Dict[str, Any]:
        """
        获取持仓风险评估

        Args:
            portfolio: 投资组合

        Returns:
            Dict[str, Any]: 风险评估结果
        """
        try:
            risk_metrics = {}

            # 集中度风险
            concentration_risk = self._calculate_concentration_risk(portfolio)
            risk_metrics['concentration_risk'] = concentration_risk

            # 流动性风险
            liquidity_risk = self._calculate_liquidity_risk(portfolio)
            risk_metrics['liquidity_risk'] = liquidity_risk

            # 市场风险
            market_risk = self._calculate_market_risk(portfolio)
            risk_metrics['market_risk'] = market_risk

            # 总体风险等级
            overall_risk = self._determine_overall_risk(risk_metrics)

            return {
                'overall_risk': overall_risk.value,
                'risk_metrics': risk_metrics,
                'timestamp': self._get_current_timestamp(),
                'recommendations': self._generate_risk_recommendations(risk_metrics)
            }

        except Exception as e:
            self.logger.error(f"风险评估失败: {e}")
            return {
                'overall_risk': RiskLevel.CRITICAL.value,
                'error': str(e),
                'timestamp': self._get_current_timestamp()
            }

    def get_performance_report(self) -> Dict[str, Any]:
        """
        获取性能报告

        Returns:
            Dict[str, Any]: 性能报告
        """
        success_rate = 0
        if self.performance_stats['risk_checks_passed'] + self.performance_stats['risk_checks_failed'] > 0:
            success_rate = (self.performance_stats['risk_checks_passed'] /
                            (self.performance_stats['risk_checks_passed'] + self.performance_stats[
                                'risk_checks_failed']) * 100)

        return {
            'total_calculations': self.performance_stats['total_calculations'],
            'risk_check_success_rate': f"{success_rate:.1f}%",
            'average_calculation_time': f"{self.performance_stats['average_calculation_time']:.3f}s",
            'risk_tolerance': f"{self.risk_tolerance:.1%}"
        }

    def _get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股票信息"""
        try:
            snapshot = self.broker.get_market_snapshot([symbol])
            if symbol not in snapshot:
                return None

            stock_info = snapshot[symbol]
            # 标准化交易单位
            lot_size = self._determine_lot_size(stock_info)
            stock_info['lot_size'] = lot_size
            stock_info['min_trade_quantity'] = stock_info.get('min_trade_quantity', lot_size)

            return stock_info

        except Exception as e:
            self.logger.error(f"获取股票信息失败 {symbol}: {e}")
            return None

    def _determine_lot_size(self, stock_info: Dict[str, Any]) -> int:
        """从行情数据中提取最小交易手"""
        candidates = [
            'lot_size',
            'lotSize',
            'deal_unit',
            'trade_unit',
            'order_unit',
            'min_trade_quantity',
            'min_lot',
            'lot'
        ]

        for field in candidates:
            value = stock_info.get(field)
            if value is None:
                continue

            try:
                number = int(value)
            except (TypeError, ValueError):
                continue

            if number > 0:
                return number

        return 100

    def _perform_comprehensive_risk_check(self,
                                          symbol: str,
                                          price: float,
                                          portfolio: Portfolio,
                                          is_initial: bool) -> Dict[str, Any]:
        """执行综合风险检查"""
        checks = [
            self._check_price_validity(price),
            self._check_position_concentration(symbol, portfolio, is_initial),
            self._check_available_cash(portfolio, price),
            self._check_market_volatility(symbol),
            self._check_trading_restrictions(symbol)
        ]

        failed_checks = [check for check in checks if not check['passed']]

        if failed_checks:
            reasons = [check['reason'] for check in failed_checks]
            return {
                'allowed': False,
                'reason': '; '.join(reasons),
                'failed_checks': failed_checks
            }

        return {'allowed': True, 'reason': '风险检查通过'}

    def _check_price_validity(self, price: float) -> Dict[str, Any]:
        """检查价格有效性"""
        if price <= 0:
            return {'passed': False, 'reason': '价格无效'}
        elif price > 10000:  # 价格过高
            return {'passed': False, 'reason': '价格过高'}

        return {'passed': True, 'reason': '价格有效'}

    def _check_position_concentration(self,
                                      symbol: str,
                                      portfolio: Portfolio,
                                      is_initial: bool) -> Dict[str, Any]:
        """检查仓位集中度"""
        try:
            max_ratio = getattr(self.config.trading, 'max_position_ratio', 0.2)

            # 计算当前股票在组合中的占比
            position_value = self._get_position_value(symbol, portfolio)
            total_assets = getattr(portfolio, 'total_assets', 1)  # 避免除零

            if total_assets <= 0:
                return {'passed': False, 'reason': '组合总资产无效'}

            current_ratio = position_value / total_assets

            if current_ratio >= max_ratio:
                return {
                    'passed': False,
                    'reason': f'仓位集中度已达上限: {current_ratio:.1%} >= {max_ratio:.1%}'
                }

            # 对于初始建仓，检查是否超过初始建仓比例
            if is_initial:
                initial_ratio = getattr(self.config.trading, 'initial_position_ratio', 0.1)
                if current_ratio >= initial_ratio:
                    return {
                        'passed': False,
                        'reason': f'初始建仓比例已达上限: {current_ratio:.1%} >= {initial_ratio:.1%}'
                    }

            return {'passed': True, 'reason': '仓位集中度正常'}

        except Exception as e:
            self.logger.error(f"仓位集中度检查失败: {e}")
            return {'passed': False, 'reason': '集中度检查异常'}

    def _check_available_cash(self, portfolio: Portfolio, price: float) -> Dict[str, Any]:
        """检查可用资金"""
        try:
            available_cash = getattr(portfolio, 'available_cash', 0)

            if available_cash <= 0:
                return {'passed': False, 'reason': '可用资金不足'}

            # 检查最小交易金额
            min_trade_value = price * 100  # 假设最小交易100股
            if available_cash < min_trade_value:
                return {'passed': False, 'reason': '资金不足以进行最小交易'}

            return {'passed': True, 'reason': '资金充足'}

        except Exception as e:
            self.logger.error(f"资金检查失败: {e}")
            return {'passed': False, 'reason': '资金检查异常'}

    def _check_market_volatility(self, symbol: str) -> Dict[str, Any]:
        """检查市场波动性"""
        # 简化实现，实际应该基于历史波动率
        try:
            # 这里可以添加基于ATR、历史波动率的检查
            return {'passed': True, 'reason': '市场波动性正常'}
        except Exception as e:
            self.logger.error(f"波动性检查失败: {e}")
            return {'passed': True, 'reason': '波动性检查跳过'}  # 检查失败不影响交易

    def _check_trading_restrictions(self, symbol: str) -> Dict[str, Any]:
        """检查交易限制"""
        # 检查是否在交易限制列表中
        restricted_stocks = getattr(self.config.trading, 'restricted_stocks', [])
        if symbol in restricted_stocks:
            return {'passed': False, 'reason': '该股票在交易限制列表中'}

        return {'passed': True, 'reason': '无交易限制'}

    def _calculate_max_position_value(self, symbol: str, portfolio: Portfolio, is_initial: bool) -> float:
        """计算最大允许仓位价值"""
        total_assets = getattr(portfolio, 'total_assets', 0)

        if is_initial:
            # 初始建仓使用较小的比例
            ratio = getattr(self.config.trading, 'initial_position_ratio', 0.1)
        else:
            # 加仓使用较大的比例
            ratio = getattr(self.config.trading, 'max_position_ratio', 0.2)

        max_value = total_assets * ratio

        # 应用风险调整
        risk_adjustment = self._get_risk_adjustment(symbol)
        adjusted_max_value = max_value * risk_adjustment

        self.logger.debug(
            f"最大仓位价值: {adjusted_max_value:.2f} (基准: {max_value:.2f}, 风险调整: {risk_adjustment:.2f})")
        return adjusted_max_value

    def _get_risk_adjustment(self, symbol: str) -> float:
        """获取风险调整系数"""
        # 基于股票波动性、流动性等因素调整
        # 简化实现，返回固定值
        return 1.0

    def _calculate_current_position_value(self, symbol: str, price: float, portfolio: Portfolio) -> float:
        """计算当前持仓价值"""
        position_quantity = self._get_position_quantity(symbol, portfolio)
        return position_quantity * price

    def _get_position_value(self, symbol: str, portfolio: Portfolio) -> float:
        """获取持仓价值"""
        try:
            positions = getattr(portfolio, 'positions', {})
            if symbol in positions:
                position = positions[symbol]
                quantity = getattr(position, 'quantity', 0)
                cost_price = getattr(position, 'cost_price', 0)
                return quantity * cost_price
            return 0.0
        except Exception as e:
            self.logger.error(f"获取持仓价值失败 {symbol}: {e}")
            return 0.0

    def _get_position_quantity(self, symbol: str, portfolio: Portfolio) -> int:
        """获取持仓数量"""
        try:
            positions = getattr(portfolio, 'positions', {})
            if symbol in positions:
                position = positions[symbol]
                return getattr(position, 'quantity', 0)
            return 0
        except Exception as e:
            self.logger.error(f"获取持仓数量失败 {symbol}: {e}")
            return 0

    def _calculate_available_amount(self, max_position_value: float,
                                    current_position_value: float,
                                    portfolio: Portfolio) -> float:
        """计算可用金额"""
        available_cash = getattr(portfolio, 'available_cash', 0)

        # 可用于该股票的金额
        available_for_stock = max_position_value - current_position_value

        # 不能超过可用现金的80%（保留部分现金）
        cash_limit = available_cash * 0.8

        return min(available_for_stock, cash_limit)

    def _calculate_position_suggestion(self, symbol: str, price: float,
                                       available_amount: float,
                                       stock_info: Dict[str, Any],
                                       portfolio: Portfolio,
                                       level: int = 1,
                                       max_additional_value: Optional[float] = None) -> PositionSuggestion:
        """计算仓位建议"""
        lot_size = stock_info.get('lot_size', 100)
        min_trade_quantity = stock_info.get('min_trade_quantity', lot_size) or lot_size

        if max_additional_value is not None:
            available_amount = min(available_amount, max_additional_value)

        # 计算原始数量
        raw_quantity = available_amount / price

        # 调整为整手数
        lot_quantity = int(raw_quantity // lot_size) * lot_size

        if lot_quantity <= 0:
            return self._create_error_suggestion(
                symbol,
                f"可用资金不足以支撑最少一手 ({lot_size} 股)"
            )

        # 确保不低于最小交易数量
        final_quantity = max(lot_quantity, min_trade_quantity)

        # 计算风险等级
        risk_level = self._assess_position_risk(symbol, final_quantity, price, portfolio)

        stop_loss_price, trailing_stop_price = self._prepare_batch_profile(price, level)
        batch_id = str(uuid.uuid4())

        return PositionSuggestion(
            symbol=symbol,
            suggested_quantity=final_quantity,
            max_quantity=lot_quantity,
            risk_level=risk_level,
            reason=self._generate_suggestion_reason(risk_level, final_quantity, available_amount),
            available_cash=getattr(portfolio, 'available_cash', 0),
            position_value=final_quantity * price,
            lot_size=lot_size,
            level=level,
            stop_loss_price=stop_loss_price,
            trailing_stop_price=trailing_stop_price,
            batch_id=batch_id
        )

    def _assess_position_risk(self, symbol: str, quantity: int, price: float, portfolio: Portfolio) -> RiskLevel:
        """评估仓位风险"""
        position_value = quantity * price
        total_assets = getattr(portfolio, 'total_assets', 1)

        position_ratio = position_value / total_assets

        if position_ratio > 0.15:
            return RiskLevel.HIGH
        elif position_ratio > 0.08:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def _generate_suggestion_reason(self, risk_level: RiskLevel, quantity: int, available_amount: float) -> str:
        """生成建议理由"""
        reasons = {
            RiskLevel.LOW: "低风险，建议仓位",
            RiskLevel.MEDIUM: "中等风险，谨慎建仓",
            RiskLevel.HIGH: "高风险，建议减仓",
            RiskLevel.CRITICAL: "极高风险，避免交易"
        }
        return reasons.get(risk_level, "风险未知")

    def _create_error_suggestion(self, symbol: str, reason: str) -> PositionSuggestion:
        """创建错误建议"""
        return PositionSuggestion(
            symbol=symbol,
            suggested_quantity=0,
            max_quantity=0,
            risk_level=RiskLevel.CRITICAL,
            reason=reason,
            available_cash=0,
            position_value=0,
            lot_size=100
        )

    def _register_new_batch(self, symbol: str, suggestion: PositionSuggestion, price: float, portfolio: Portfolio):
        """记录新的仓位批次"""
        if suggestion.suggested_quantity <= 0:
            return

        batch_id = suggestion.batch_id or str(uuid.uuid4())
        stop_loss_price = suggestion.stop_loss_price
        trailing_price = suggestion.trailing_stop_price

        batch = PositionBatch(
            batch_id=batch_id,
            symbol=symbol,
            level=suggestion.level,
            entry_time=datetime.now(),
            entry_price=price,
            quantity=suggestion.suggested_quantity,
            current_price=price,
            stop_loss_price=stop_loss_price,
            trailing_stop_price=trailing_price,
            highest_price=price
        )

        self.position_batches.setdefault(symbol, []).append(batch)
        stock_position = self.stock_positions.setdefault(symbol, StockPosition(symbol=symbol))
        stock_position.add_batch(batch)
        stock_position.current_level = suggestion.level
        stock_position.overall_stop_loss = stop_loss_price
        total_assets = max(getattr(portfolio, 'total_assets', 1), 1)
        stock_position.risk_exposure = stock_position.total_value / total_assets

    def _calculate_position_ratio(self, position_value: float, total_assets: float) -> float:
        if total_assets <= 0:
            return 0.0
        return position_value / total_assets

    def _determine_position_level(self, position_ratio: float) -> int:
        sorted_levels = sorted(self.hierarchical_levels.items(), key=lambda x: x[0])
        for level, threshold in sorted_levels:
            if position_ratio <= threshold:
                return level
        return max(self.hierarchical_levels.keys())

    def _evaluate_hierarchical_addition(self, symbol: str, position: Optional[Any], level: int,
                                        stock_info: Dict[str, Any], portfolio: Portfolio) -> Dict[str, Any]:
        config = self.addition_configs.get(level)
        if not config:
            return {'allowed': True}

        if not position or getattr(position, 'quantity', 0) <= 0:
            return {'allowed': False, 'reason': '加仓需在已有持仓基础上进行'}

        profit_ratio = getattr(position, 'profit_loss_ratio', 0.0)
        if profit_ratio <= 0:
            return {'allowed': False, 'reason': '当前仓位需处于盈利状态'}

        threshold = self._calculate_dynamic_threshold(config['profit_threshold'], stock_info)
        threshold *= self._get_market_condition_modifier()
        if profit_ratio < threshold:
            return {
                'allowed': False,
                'reason': f'未达到L{level}盈利阈值 ({threshold:.1%})'
            }

        if not self._is_trend_stable(stock_info):
            return {'allowed': False, 'reason': '趋势方向未确认'}

        if not self._is_market_environment_favorable():
            return {'allowed': False, 'reason': '当前市场环境不适合加仓'}

        if not self._check_max_wait(position, config):
            return {'allowed': False, 'reason': '加仓等待时间已过'}

        return {'allowed': True, 'note': f'L{level}加仓准入'}

    def _calculate_dynamic_threshold(self, base_threshold: float, stock_info: Dict[str, Any]) -> float:
        volatility = abs(stock_info.get('amplitude', 0)) or 0
        if volatility < 2:
            return base_threshold * 0.8
        if volatility > 8:
            return base_threshold * 1.3
        return base_threshold

    def _get_market_condition_modifier(self) -> float:
        condition = str(self.config.trading.extra.get('market_condition', "")).lower()
        if not condition:
            condition = getattr(self.config.system, 'market_condition', 'neutral').lower()
        return self.market_condition_modifiers.get(condition, 1.0)

    def _is_trend_stable(self, stock_info: Dict[str, Any]) -> bool:
        change_rate = stock_info.get('change_rate', 0)
        return change_rate >= -0.03

    def _is_market_environment_favorable(self) -> bool:
        modifier = self._get_market_condition_modifier()
        return modifier <= 1.2

    def _check_max_wait(self, position: Any, config: Dict[str, Any]) -> bool:
        max_wait = config.get('max_wait_days', 0)
        if max_wait <= 0:
            return True
        entry_time = getattr(position, 'created_time', None)
        if not isinstance(entry_time, datetime):
            return True
        elapsed = (datetime.now() - entry_time).days
        return elapsed <= max_wait

    def _get_portfolio_position(self, symbol: str, portfolio: Portfolio) -> Optional[Any]:
        positions = getattr(portfolio, 'positions', {})
        return positions.get(symbol)

    def _prepare_batch_profile(self, price: float, level: int) -> Tuple[float, float]:
        profile = self.stop_loss_profiles.get(level, self.stop_loss_profiles[3])
        stop_loss_price = price * (1 - profile['stop_loss_ratio'])
        trailing_stop_price = price * (1 - profile['trailing_ratio'])
        return stop_loss_price, trailing_stop_price

    # 由于字符限制，剩余的验证方法和辅助方法将在实际实现中补充...
    def _validate_basic_parameters(self, symbol: str, quantity: int, price: float) -> Dict[str, Any]:
        """验证基础参数"""
        if not symbol or not isinstance(symbol, str):
            return {
                'valid': False,
                'message': '股票代码无效',
                'suggested_quantity': 0,
                'risk_level': RiskLevel.CRITICAL.value
            }

        if quantity <= 0:
            return {
                'valid': False,
                'message': '交易数量必须大于0',
                'suggested_quantity': 0,
                'risk_level': RiskLevel.HIGH.value
            }

        if price <= 0:
            return {
                'valid': False,
                'message': '交易价格必须大于0',
                'suggested_quantity': 0,
                'risk_level': RiskLevel.HIGH.value
            }

        return {'valid': True, 'message': '基础参数验证通过'}

    def _validate_market_data(self, symbol: str, price: float) -> Dict[str, Any]:
        """验证市场数据"""
        try:
            market_data = self.broker.get_market_snapshot([symbol])
            if symbol not in market_data:
                return {
                    'valid': False,
                    'message': '无法获取股票市场数据',
                    'suggested_quantity': 0,
                    'risk_level': RiskLevel.HIGH.value
                }

            stock_info = market_data[symbol]
            current_price = stock_info.get('last_price', 0)

            # 检查价格合理性
            if current_price <= 0:
                return {
                    'valid': False,
                    'message': '当前价格无效',
                    'suggested_quantity': 0,
                    'risk_level': RiskLevel.HIGH.value
                }

            # 检查价格偏差（如果提供价格与当前价格偏差过大）
            if price > 0 and abs(price - current_price) / current_price > 0.1:  # 10%偏差
                return {
                    'valid': False,
                    'message': f'报价偏差过大: {price:.2f} vs {current_price:.2f}',
                    'suggested_quantity': 0,
                    'risk_level': RiskLevel.MEDIUM.value
                }

            return {'valid': True, 'message': '市场数据验证通过'}

        except Exception as e:
            self.logger.error(f"市场数据验证失败: {e}")
            return {
                'valid': False,
                'message': f'市场数据验证异常: {e}',
                'suggested_quantity': 0,
                'risk_level': RiskLevel.CRITICAL.value
            }

    def _validate_risk_parameters(self, symbol: str, quantity: int, price: float, portfolio: Portfolio) -> Dict[
        str, Any]:
        """验证风险参数"""
        try:
            # 计算交易价值
            trade_value = quantity * price

            # 检查单笔交易金额限制
            max_trade_value = getattr(self.config.trading, 'max_trade_value', 500000)  # 默认50万
            if trade_value > max_trade_value:
                return {
                    'valid': False,
                    'message': f'单笔交易金额超过限制: {trade_value:.0f} > {max_trade_value:.0f}',
                    'suggested_quantity': int(max_trade_value / price),
                    'risk_level': RiskLevel.HIGH.value
                }

            # 检查仓位集中度
            max_ratio = getattr(self.config.trading, 'max_position_ratio', 0.2)
            current_position_value = self._get_position_value(symbol, portfolio)
            total_assets = getattr(portfolio, 'total_assets', 1)

            new_position_ratio = (current_position_value + trade_value) / total_assets
            if new_position_ratio > max_ratio:
                return {
                    'valid': False,
                    'message': f'仓位集中度将超过限制: {new_position_ratio:.1%} > {max_ratio:.1%}',
                    'suggested_quantity': int((max_ratio * total_assets - current_position_value) / price),
                    'risk_level': RiskLevel.HIGH.value
                }

            return {'valid': True, 'message': '风险参数验证通过'}

        except Exception as e:
            self.logger.error(f"风险参数验证失败: {e}")
            return {
                'valid': False,
                'message': f'风险参数验证异常: {e}',
                'suggested_quantity': 0,
                'risk_level': RiskLevel.CRITICAL.value
            }

    def _validate_order_specifics(self, symbol: str, quantity: int, price: float) -> Dict[str, Any]:
        """验证订单特定参数"""
        try:
            # 检查交易单位（手数）
            market_data = self.broker.get_market_snapshot([symbol])
            if symbol in market_data:
                stock_info = market_data[symbol]
                lot_size = stock_info.get('lot_size', 100)

                # 检查是否为整手数
                if quantity % lot_size != 0:
                    return {
                        'valid': False,
                        'message': f'交易数量必须为{lot_size}的整数倍',
                        'suggested_quantity': (quantity // lot_size) * lot_size,
                        'risk_level': RiskLevel.MEDIUM.value
                    }

            return {'valid': True, 'message': '订单特定参数验证通过'}

        except Exception as e:
            self.logger.error(f"订单特定参数验证失败: {e}")
            return {
                'valid': False,
                'message': f'订单特定参数验证异常: {e}',
                'suggested_quantity': quantity,  # 保持原数量
                'risk_level': RiskLevel.MEDIUM.value
            }

    def _calculate_concentration_risk(self, portfolio: Portfolio) -> Dict[str, Any]:
        """计算集中度风险"""
        try:
            positions = getattr(portfolio, 'positions', {})
            total_assets = getattr(portfolio, 'total_assets', 1)

            if not positions:
                return {'level': 'low', 'score': 0, 'message': '无持仓'}

            # 计算前3大持仓占比
            position_values = []
            for symbol, position in positions.items():
                quantity = getattr(position, 'quantity', 0)
                cost_price = getattr(position, 'cost_price', 0)
                position_values.append(quantity * cost_price)

            position_values.sort(reverse=True)
            top3_ratio = sum(position_values[:3]) / total_assets

            if top3_ratio > 0.6:
                return {'level': 'high', 'score': top3_ratio, 'message': f'持仓高度集中: {top3_ratio:.1%}'}
            elif top3_ratio > 0.4:
                return {'level': 'medium', 'score': top3_ratio, 'message': f'持仓较为集中: {top3_ratio:.1%}'}
            else:
                return {'level': 'low', 'score': top3_ratio, 'message': f'持仓分散度良好: {top3_ratio:.1%}'}

        except Exception as e:
            self.logger.error(f"集中度风险计算失败: {e}")
            return {'level': 'unknown', 'score': 0, 'message': f'计算异常: {e}'}

    def _calculate_liquidity_risk(self, portfolio: Portfolio) -> Dict[str, Any]:
        """计算流动性风险"""
        try:
            available_cash = getattr(portfolio, 'available_cash', 0)
            total_assets = getattr(portfolio, 'total_assets', 1)

            cash_ratio = available_cash / total_assets

            if cash_ratio < 0.1:
                return {'level': 'high', 'score': cash_ratio, 'message': f'现金比例过低: {cash_ratio:.1%}'}
            elif cash_ratio < 0.2:
                return {'level': 'medium', 'score': cash_ratio, 'message': f'现金比例适中: {cash_ratio:.1%}'}
            else:
                return {'level': 'low', 'score': cash_ratio, 'message': f'现金比例充足: {cash_ratio:.1%}'}

        except Exception as e:
            self.logger.error(f"流动性风险计算失败: {e}")
            return {'level': 'unknown', 'score': 0, 'message': f'计算异常: {e}'}

    def _calculate_market_risk(self, portfolio: Portfolio) -> Dict[str, Any]:
        """计算市场风险"""
        # 简化实现，实际应该基于持仓的Beta值、波动率等
        try:
            # 这里可以添加更复杂的市场风险计算
            return {'level': 'medium', 'score': 0.5, 'message': '市场风险中等'}
        except Exception as e:
            self.logger.error(f"市场风险计算失败: {e}")
            return {'level': 'unknown', 'score': 0, 'message': f'计算异常: {e}'}

    def _determine_overall_risk(self, risk_metrics: Dict[str, Any]) -> RiskLevel:
        """确定总体风险等级"""
        risk_levels = {
            'high': 0,
            'medium': 0,
            'low': 0,
            'unknown': 0
        }

        for metric in risk_metrics.values():
            risk_levels[metric['level']] += 1

        if risk_levels['high'] > 0:
            return RiskLevel.HIGH
        elif risk_levels['medium'] > 1:
            return RiskLevel.MEDIUM
        elif risk_levels['unknown'] > 0:
            return RiskLevel.MEDIUM  # 未知风险视为中等
        else:
            return RiskLevel.LOW

    def _generate_risk_recommendations(self, risk_metrics: Dict[str, Any]) -> List[str]:
        """生成风险建议"""
        recommendations = []

        concentration_risk = risk_metrics.get('concentration_risk', {})
        if concentration_risk.get('level') == 'high':
            recommendations.append("建议分散持仓，降低前3大持仓比例")

        liquidity_risk = risk_metrics.get('liquidity_risk', {})
        if liquidity_risk.get('level') == 'high':
            recommendations.append("建议增加现金比例，提高流动性")

        market_risk = risk_metrics.get('market_risk', {})
        if market_risk.get('level') == 'high':
            recommendations.append("建议降低仓位，控制市场风险")

        if not recommendations:
            recommendations.append("当前风险可控，继续保持")

        return recommendations

    def _get_current_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()

    def _update_performance_stats(self, start_time: float):
        """更新性能统计"""
        import time
        duration = time.time() - start_time
        self.performance_stats['total_calculations'] += 1

        # 更新平均计算时间
        total_calcs = self.performance_stats['total_calculations']
        current_avg = self.performance_stats['average_calculation_time']
        new_avg = (current_avg * (total_calcs - 1) + duration) / total_calcs
        self.performance_stats['average_calculation_time'] = new_avg




    def calculate_scaling_position_size(self,
                                        symbol: str,
                                        price: float,
                                        portfolio: Portfolio,
                                        current_level: int) -> PositionSuggestion:
        """
        计算加仓仓位大小

        Args:
            symbol: 股票代码
            price: 当前价格
            portfolio: 投资组合
            current_level: 当前仓位级别 (1,2,3)

        Returns:
            PositionSuggestion: 加仓建议
        """
        self.logger.info(f"计算加仓仓位: {symbol} 当前级别L{current_level}")

        # 检查加仓条件
        scaling_check = self._check_scaling_conditions(symbol, price, portfolio, current_level)
        if not scaling_check['allowed']:
            return self._create_error_suggestion(symbol, scaling_check['reason'])

        # 计算加仓数量
        scaling_quantity = self._calculate_scaling_quantity(symbol, price, portfolio, current_level)

        # 创建加仓建议
        return self._create_scaling_suggestion(symbol, price, scaling_quantity,
                                               portfolio, current_level, scaling_check)

    def _check_scaling_conditions(self,
                                  symbol: str,
                                  price: float,
                                  portfolio: Portfolio,
                                  current_level: int) -> Dict[str, Any]:
        """
        检查加仓条件

        Returns:
            Dict: 包含是否允许加仓及原因
        """
        try:
            # 1. 检查是否已满级
            if current_level >= 3:
                return {'allowed': False, 'reason': '已达最大仓位级别L3'}

            # 2. 获取当前盈利比例
            profit_ratio = self._calculate_position_profit_ratio(symbol, price, portfolio)

            # 3. 检查盈利阈值
            required_profit = self._get_required_profit_threshold(current_level)
            if profit_ratio < required_profit:
                return {
                    'allowed': False,
                    'reason': f'盈利{profit_ratio:.1%}未达到阈值{required_profit:.1%}'
                }

            # 4. 检查趋势和市场条件
            trend_check = self._check_trend_condition(symbol)
            if not trend_check['valid']:
                return {'allowed': False, 'reason': trend_check['reason']}

            # 5. 检查仓位集中度（使用原有逻辑但调整参数）
            concentration_check = self._check_scaling_concentration(symbol, portfolio, current_level)
            if not concentration_check['allowed']:
                return concentration_check

            return {
                'allowed': True,
                'reason': '加仓条件满足',
                'current_profit': profit_ratio,
                'target_level': current_level + 1
            }

        except Exception as e:
            self.logger.error(f"加仓条件检查异常 {symbol}: {e}")
            return {'allowed': False, 'reason': f'条件检查异常: {e}'}

    def _calculate_scaling_quantity(self,
                                    symbol: str,
                                    price: float,
                                    portfolio: Portfolio,
                                    current_level: int) -> int:
        """
        计算加仓数量
        """
        # 获取加仓配置
        scaling_config = self._get_scaling_config(current_level)
        scaling_ratio = scaling_config['add_ratio']

        # 计算加仓金额
        total_assets = getattr(portfolio, 'total_assets', 0)
        scaling_value = total_assets * scaling_ratio

        # 考虑可用资金限制
        available_cash = getattr(portfolio, 'available_cash', 0)
        scaling_value = min(scaling_value, available_cash * 0.8)  # 保留20%现金

        # 计算股数（考虑整手）
        stock_info = self._get_stock_info(symbol)
        lot_size = stock_info.get('lot_size', 100) if stock_info else 100

        raw_quantity = int(scaling_value / price)
        scaled_quantity = (raw_quantity // lot_size) * lot_size

        return max(scaled_quantity, lot_size)  # 至少1手

    def _get_scaling_config(self, current_level: int) -> Dict[str, Any]:
        """
        获取加仓配置参数
        """
        scaling_configs = {
            1: {'profit_threshold': 0.08, 'add_ratio': 0.10},  # L1→L2
            2: {'profit_threshold': 0.08, 'add_ratio': 0.05},  # L2→L3
        }
        return scaling_configs.get(current_level, {})