"""
分级仓位服务模块
专门处理盈利加仓逻辑和分级仓位管理
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from enum import Enum

from quant_system.utils.logger import get_logger
from quant_system.domain.entities.portfolio import Portfolio
from quant_system.domain.entities.position_batch import PositionBatch, PositionBatchStatus


class ScalingCondition(Enum):
    """加仓条件枚举"""
    PROFIT_THRESHOLD = "profit_threshold"  # 盈利阈值
    TREND_CONFIRMATION = "trend_confirmation"  # 趋势确认
    VOLUME_CONFIRMATION = "volume_confirmation"  # 成交量确认
    MARKET_CONDITION = "market_condition"  # 市场环境
    TECHNICAL_STRENGTH = "technical_strength"  # 技术面强度


@dataclass
class ScalingOpportunity:
    """加仓机会数据类"""
    symbol: str
    current_level: int
    target_level: int
    suggested_quantity: int
    suggested_price: float
    current_profit_ratio: float
    confidence_score: float  # 置信度分数 0-100
    conditions_met: List[ScalingCondition]
    risk_level: str
    reason: str
    timestamp: datetime


class PositionScalingService:
    """
    分级仓位服务

    专门处理盈利加仓逻辑，提供智能的加仓条件检查和仓位计算。
    与基础仓位管理服务协同工作，实现科学的分级仓位管理。
    """

    def __init__(self, broker=None, config=None):
        """
        初始化分级仓位服务

        Args:
            broker: 券商接口
            config: 配置管理器
        """
        self.broker = broker
        self.config = config
        self.logger = get_logger(__name__)

        # 加仓配置
        self.scaling_config = self._load_scaling_config()

        # 状态跟踪
        self.opportunity_cache: Dict[str, ScalingOpportunity] = {}
        self.last_analysis_time: Optional[datetime] = None

        self.logger.info("分级仓位服务初始化完成")

    def _load_scaling_config(self) -> Dict[str, Any]:
        """
        加载分级仓位配置

        Returns:
            Dict[str, Any]: 分级仓位配置
        """
        default_config = {
            'enabled': True,
            'check_interval_minutes': 30,
            'levels': {
                1: {'max_ratio': 0.10, 'stop_loss': 0.08},
                2: {
                    'profit_threshold': 0.08,
                    'add_ratio': 0.10,
                    'max_ratio': 0.20,
                    'stop_loss': 0.04,
                    'min_holding_days': 3
                },
                3: {
                    'profit_threshold': 0.08,
                    'add_ratio': 0.05,
                    'max_ratio': 0.25,
                    'stop_loss': 0.03,
                    'min_holding_days': 5
                }
            },
            'conditions': {
                'min_confidence_score': 70,
                'required_trend_strength': 60,
                'volume_increase_ratio': 1.2,
                'max_market_decline': -0.02
            }
        }

        try:
            if self.config and hasattr(self.config.trading, 'position_scaling_enabled'):
                if self.config.trading.position_scaling_enabled:
                    # 从配置中加载参数
                    config = {'enabled': True}
                    levels_config = {}

                    for level in [1, 2, 3]:
                        level_config = self.config.get_scaling_level_config(level)
                        if level_config:
                            levels_config[level] = {
                                'max_ratio': getattr(level_config, 'max_ratio',
                                                     default_config['levels'][level]['max_ratio']),
                                'profit_threshold': getattr(level_config, 'profit_threshold', None),
                                'add_ratio': getattr(level_config, 'add_ratio', None),
                                'stop_loss': getattr(level_config, 'stop_loss_ratio',
                                                     default_config['levels'][level]['stop_loss']),
                                'min_holding_days': getattr(level_config, 'min_holding_days', 3)
                            }

                    config['levels'] = levels_config
                    return config

        except Exception as e:
            self.logger.warning(f"加载分级仓位配置失败，使用默认配置: {e}")

        return default_config

    def find_scaling_opportunities(self, portfolio: Portfolio, market_data: Dict[str, Any]) -> List[ScalingOpportunity]:
        """
        寻找加仓机会

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            List[ScalingOpportunity]: 加仓机会列表
        """
        if not self.scaling_config['enabled']:
            return []

        opportunities = []

        try:
            # 检查每个持仓的加仓条件
            for symbol, position in portfolio.positions.items():
                if symbol not in market_data:
                    continue

                current_data = market_data[symbol]
                current_price = current_data.get('last_price', 0)

                if current_price <= 0:
                    continue

                # 分析加仓机会
                opportunity = self._analyze_scaling_opportunity(
                    symbol, position, portfolio, current_data, current_price
                )

                if opportunity and opportunity.confidence_score >= self.scaling_config['conditions'][
                    'min_confidence_score']:
                    opportunities.append(opportunity)
                    self.opportunity_cache[symbol] = opportunity

            self.last_analysis_time = datetime.now()
            self.logger.info(f"发现 {len(opportunities)} 个加仓机会")

        except Exception as e:
            self.logger.error(f"寻找加仓机会异常: {e}")

        return opportunities

    def _analyze_scaling_opportunity(self, symbol: str, position: Any,
                                     portfolio: Portfolio, market_data: Dict[str, Any],
                                     current_price: float) -> Optional[ScalingOpportunity]:
        """
        分析单个股票的加仓机会

        Args:
            symbol: 股票代码
            position: 持仓对象
            portfolio: 投资组合
            market_data: 市场数据
            current_price: 当前价格

        Returns:
            Optional[ScalingOpportunity]: 加仓机会，如果不满足条件返回None
        """
        try:
            # 获取当前仓位级别
            current_level = self._get_current_position_level(portfolio, symbol)
            if current_level >= 3:  # 已达最高级别
                return None

            # 检查基础条件
            base_conditions = self._check_base_conditions(symbol, position, portfolio, current_level)
            if not base_conditions['met']:
                return None

            # 检查级别特定条件
            level_conditions = self._check_level_specific_conditions(
                symbol, position, portfolio, current_level, market_data, current_price
            )
            if not level_conditions['met']:
                return None

            # 计算目标级别和数量
            target_level = current_level + 1
            suggested_quantity = self._calculate_scaling_quantity(
                symbol, portfolio, target_level, current_price
            )

            if suggested_quantity <= 0:
                return None

            # 计算置信度分数
            confidence_score = self._calculate_confidence_score(
                base_conditions, level_conditions, current_level
            )

            # 确定风险等级
            risk_level = self._assess_scaling_risk(confidence_score, current_level, target_level)

            # 创建加仓机会
            opportunity = ScalingOpportunity(
                symbol=symbol,
                current_level=current_level,
                target_level=target_level,
                suggested_quantity=suggested_quantity,
                suggested_price=current_price,
                current_profit_ratio=base_conditions['profit_ratio'],
                confidence_score=confidence_score,
                conditions_met=base_conditions['met_conditions'] + level_conditions['met_conditions'],
                risk_level=risk_level,
                reason=self._generate_opportunity_reason(base_conditions, level_conditions, current_level,
                                                         target_level),
                timestamp=datetime.now()
            )

            return opportunity

        except Exception as e:
            self.logger.error(f"分析加仓机会异常 {symbol}: {e}")
            return None

    def _get_current_position_level(self, portfolio: Portfolio, symbol: str) -> int:
        """
        获取当前仓位级别

        Args:
            portfolio: 投资组合
            symbol: 股票代码

        Returns:
            int: 仓位级别
        """
        try:
            if hasattr(portfolio, 'get_position_level'):
                return portfolio.get_position_level(symbol)
            else:
                # 回退逻辑
                position = portfolio.positions.get(symbol)
                if not position:
                    return 0

                # 根据批次数量判断级别
                active_batches = self._get_active_batches(portfolio, symbol)
                return len(active_batches)

        except Exception as e:
            self.logger.error(f"获取仓位级别异常 {symbol}: {e}")
            return 0

    def _get_active_batches(self, portfolio: Portfolio, symbol: str) -> List[PositionBatch]:
        """
        获取活跃批次

        Args:
            portfolio: 投资组合
            symbol: 股票代码

        Returns:
            List[PositionBatch]: 活跃批次列表
        """
        try:
            if hasattr(portfolio, 'get_active_batches'):
                return portfolio.get_active_batches(symbol)
            elif hasattr(portfolio, 'batch_manager'):
                return portfolio.batch_manager.get_active_batches_by_symbol(symbol)
            else:
                return []
        except Exception as e:
            self.logger.error(f"获取活跃批次异常 {symbol}: {e}")
            return []

    def _check_base_conditions(self, symbol: str, position: Any,
                               portfolio: Portfolio, current_level: int) -> Dict[str, Any]:
        """
        检查基础加仓条件

        Args:
            symbol: 股票代码
            position: 持仓对象
            portfolio: 投资组合
            current_level: 当前级别

        Returns:
            Dict[str, Any]: 检查结果
        """
        conditions_met = []

        try:
            # 1. 盈利检查
            profit_ratio = (position.current_price - position.cost_price) / position.cost_price
            if profit_ratio > 0:
                conditions_met.append(ScalingCondition.PROFIT_THRESHOLD)

            # 2. 持仓时间检查（如果有批次信息）
            holding_condition_met = self._check_holding_period(portfolio, symbol, current_level)
            if holding_condition_met:
                conditions_met.append(ScalingCondition.TREND_CONFIRMATION)

            # 3. 市场环境检查
            market_condition_met = self._check_market_condition()
            if market_condition_met:
                conditions_met.append(ScalingCondition.MARKET_CONDITION)

            return {
                'met': len(conditions_met) >= 2,  # 至少满足2个基础条件
                'profit_ratio': profit_ratio,
                'met_conditions': conditions_met
            }

        except Exception as e:
            self.logger.error(f"检查基础条件异常 {symbol}: {e}")
            return {'met': False, 'profit_ratio': 0, 'met_conditions': []}

    def _check_level_specific_conditions(self, symbol: str, position: Any,
                                         portfolio: Portfolio, current_level: int,
                                         market_data: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        检查级别特定条件

        Args:
            symbol: 股票代码
            position: 持仓对象
            portfolio: 投资组合
            current_level: 当前级别
            market_data: 市场数据
            current_price: 当前价格

        Returns:
            Dict[str, Any]: 检查结果
        """
        conditions_met = []
        level_config = self.scaling_config['levels'].get(current_level + 1, {})

        try:
            # 1. 盈利阈值检查
            profit_ratio = (current_price - position.cost_price) / position.cost_price
            required_profit = level_config.get('profit_threshold', 0.08)

            if profit_ratio >= required_profit:
                conditions_met.append(ScalingCondition.PROFIT_THRESHOLD)

            # 2. 趋势确认检查
            trend_strength = self._analyze_trend_strength(symbol, market_data)
            if trend_strength >= self.scaling_config['conditions']['required_trend_strength']:
                conditions_met.append(ScalingCondition.TREND_CONFIRMATION)

            # 3. 成交量确认检查
            volume_condition = self._check_volume_confirmation(symbol, market_data)
            if volume_condition:
                conditions_met.append(ScalingCondition.VOLUME_CONFIRMATION)

            # 4. 技术面强度检查
            technical_strength = self._analyze_technical_strength(symbol, market_data)
            if technical_strength > 50:  # 中等以上技术强度
                conditions_met.append(ScalingCondition.TECHNICAL_STRENGTH)

            return {
                'met': len(conditions_met) >= 2,  # 至少满足2个特定条件
                'met_conditions': conditions_met,
                'profit_ratio': profit_ratio,
                'trend_strength': trend_strength,
                'technical_strength': technical_strength
            }

        except Exception as e:
            self.logger.error(f"检查级别特定条件异常 {symbol}: {e}")
            return {'met': False, 'met_conditions': [], 'profit_ratio': 0, 'trend_strength': 0, 'technical_strength': 0}

    def _check_holding_period(self, portfolio: Portfolio, symbol: str, current_level: int) -> bool:
        """
        检查持仓时间条件

        Args:
            portfolio: 投资组合
            symbol: 股票代码
            current_level: 当前级别

        Returns:
            bool: 是否满足持仓时间条件
        """
        try:
            active_batches = self._get_active_batches(portfolio, symbol)
            if not active_batches:
                return True  # 如果没有批次信息，默认通过

            # 检查最近一个批次的持仓时间
            latest_batch = max(active_batches, key=lambda x: x.entry_time)
            holding_days = (datetime.now() - latest_batch.entry_time).days

            min_holding_days = self.scaling_config['levels'].get(current_level + 1, {}).get('min_holding_days', 3)

            return holding_days >= min_holding_days

        except Exception as e:
            self.logger.error(f"检查持仓时间异常 {symbol}: {e}")
            return False

    def _check_market_condition(self) -> bool:
        """
        检查市场环境条件

        Returns:
            bool: 市场环境是否适合加仓
        """
        try:
            # 简化实现：获取市场指数数据
            if self.broker:
                # 这里可以添加具体的市场环境分析逻辑
                # 例如：检查主要指数趋势、市场波动率等
                return True
            return True

        except Exception as e:
            self.logger.error(f"检查市场环境异常: {e}")
            return False

    def _analyze_trend_strength(self, symbol: str, market_data: Dict[str, Any]) -> float:
        """
        分析趋势强度

        Args:
            symbol: 股票代码
            market_data: 市场数据

        Returns:
            float: 趋势强度分数 0-100
        """
        try:
            # 简化实现
            # 实际应该基于技术指标计算趋势强度
            from quant_system.utils.indicators import calculate_trend_strength

            if self.broker:
                hist_data = self.broker.get_history_kline(symbol, ktype="K_DAY", max_count=30)
                if hist_data is not None and len(hist_data) >= 20:
                    closes = hist_data['close'].values
                    trend_data = calculate_trend_strength(closes)
                    return trend_data.get('strength', 50)

            return 50  # 默认中等强度

        except Exception as e:
            self.logger.error(f"分析趋势强度异常 {symbol}: {e}")
            return 50

    def _check_volume_confirmation(self, symbol: str, market_data: Dict[str, Any]) -> bool:
        """
        检查成交量确认

        Args:
            symbol: 股票代码
            market_data: 市场数据

        Returns:
            bool: 成交量是否确认
        """
        try:
            # 简化实现：检查当前成交量是否高于平均
            current_volume = market_data.get('volume', 0)
            avg_volume = market_data.get('avg_volume', current_volume)

            if avg_volume > 0:
                volume_ratio = current_volume / avg_volume
                return volume_ratio >= self.scaling_config['conditions']['volume_increase_ratio']

            return False

        except Exception as e:
            self.logger.error(f"检查成交量确认异常 {symbol}: {e}")
            return False

    def _analyze_technical_strength(self, symbol: str, market_data: Dict[str, Any]) -> float:
        """
        分析技术面强度

        Args:
            symbol: 股票代码
            market_data: 市场数据

        Returns:
            float: 技术面强度分数 0-100
        """
        try:
            # 简化实现
            # 实际应该基于多个技术指标综合评分
            if self.broker:
                # 这里可以添加更复杂的技术分析逻辑
                return 60  # 默认中等偏强

            return 50

        except Exception as e:
            self.logger.error(f"分析技术面强度异常 {symbol}: {e}")
            return 50

    def _calculate_scaling_quantity(self, symbol: str, portfolio: Portfolio,
                                    target_level: int, current_price: float) -> int:
        """
        计算加仓数量

        Args:
            symbol: 股票代码
            portfolio: 投资组合
            target_level: 目标级别
            current_price: 当前价格

        Returns:
            int: 建议加仓数量
        """
        try:
            level_config = self.scaling_config['levels'].get(target_level, {})
            add_ratio = level_config.get('add_ratio', 0.05)

            # 计算加仓金额
            total_assets = getattr(portfolio, 'total_assets', 0)
            scaling_value = total_assets * add_ratio

            # 考虑可用资金限制
            available_cash = getattr(portfolio, 'available_cash', 0)
            scaling_value = min(scaling_value, available_cash * 0.8)  # 保留20%现金

            # 计算股数（考虑整手）
            stock_info = self._get_stock_info(symbol)
            lot_size = stock_info.get('lot_size', 100) if stock_info else 100

            raw_quantity = int(scaling_value / current_price)
            scaled_quantity = (raw_quantity // lot_size) * lot_size

            return max(scaled_quantity, lot_size) if scaled_quantity > 0 else 0

        except Exception as e:
            self.logger.error(f"计算加仓数量异常 {symbol}: {e}")
            return 0

    def _get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取股票信息

        Args:
            symbol: 股票代码

        Returns:
            Optional[Dict[str, Any]]: 股票信息
        """
        try:
            if self.broker:
                snapshot = self.broker.get_market_snapshot([symbol])
                return snapshot.get(symbol, {})
            return None
        except Exception as e:
            self.logger.error(f"获取股票信息异常 {symbol}: {e}")
            return None

    def _calculate_confidence_score(self, base_conditions: Dict[str, Any],
                                    level_conditions: Dict[str, Any], current_level: int) -> float:
        """
        计算置信度分数

        Args:
            base_conditions: 基础条件检查结果
            level_conditions: 级别特定条件检查结果
            current_level: 当前级别

        Returns:
            float: 置信度分数 0-100
        """
        score = 50  # 基础分数

        # 基础条件权重
        base_met_count = len(base_conditions.get('met_conditions', []))
        score += base_met_count * 10

        # 级别特定条件权重
        level_met_count = len(level_conditions.get('met_conditions', []))
        score += level_met_count * 15

        # 盈利比例加成
        profit_ratio = level_conditions.get('profit_ratio', 0)
        if profit_ratio > 0.15:  # 盈利超过15%
            score += 10
        elif profit_ratio > 0.10:  # 盈利超过10%
            score += 5

        # 趋势强度加成
        trend_strength = level_conditions.get('trend_strength', 50)
        if trend_strength > 80:
            score += 10
        elif trend_strength > 60:
            score += 5

        return min(score, 100)

    def _assess_scaling_risk(self, confidence_score: float, current_level: int, target_level: int) -> str:
        """
        评估加仓风险

        Args:
            confidence_score: 置信度分数
            current_level: 当前级别
            target_level: 目标级别

        Returns:
            str: 风险等级
        """
        if confidence_score >= 85:
            return "LOW"
        elif confidence_score >= 70:
            return "MEDIUM"
        elif confidence_score >= 60:
            return "HIGH"
        else:
            return "CRITICAL"

    def _generate_opportunity_reason(self, base_conditions: Dict[str, Any],
                                     level_conditions: Dict[str, Any],
                                     current_level: int, target_level: int) -> str:
        """
        生成加仓机会理由

        Args:
            base_conditions: 基础条件
            level_conditions: 级别特定条件
            current_level: 当前级别
            target_level: 目标级别

        Returns:
            str: 加仓理由
        """
        reasons = []

        # 添加基础条件理由
        base_met = base_conditions.get('met_conditions', [])
        if ScalingCondition.PROFIT_THRESHOLD in base_met:
            profit_ratio = base_conditions.get('profit_ratio', 0)
            reasons.append(f"盈利{profit_ratio:.1%}")

        if ScalingCondition.TREND_CONFIRMATION in base_met:
            reasons.append("趋势确认")

        # 添加级别特定条件理由
        level_met = level_conditions.get('met_conditions', [])
        if ScalingCondition.VOLUME_CONFIRMATION in level_met:
            reasons.append("成交量配合")

        if ScalingCondition.TECHNICAL_STRENGTH in level_met:
            reasons.append("技术面强势")

        reason_text = f"L{current_level}→L{target_level}: " + " + ".join(reasons)
        return reason_text

    def get_scaling_report(self) -> Dict[str, Any]:
        """
        获取分级仓位报告

        Returns:
            Dict[str, Any]: 分级仓位报告
        """
        return {
            'service': 'position_scaling',
            'enabled': self.scaling_config['enabled'],
            'last_analysis_time': self.last_analysis_time,
            'cached_opportunities': len(self.opportunity_cache),
            'config': self.scaling_config
        }


# 导出类
__all__ = ['PositionScalingService', 'ScalingOpportunity', 'ScalingCondition']